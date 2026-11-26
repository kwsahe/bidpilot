"""AI Auditor — 제안서 초안을 RFP 요구사항 원문과 역대조한다.

docs/auditor_spec.md 2~6장 구현.

2계층 구조다.

- **Tier 1 규칙(항상 실행, 결정론적)** — text_match의 가중 자카드 점수·수치 토큰 비교로
  누락/수치 불일치/제출서류 누락/근거 없는 주장/미확인 조건을 찾는다.
  LLM 키가 없어도 완전한 결과가 나온다.
- **Tier 2 LLM(선택)** — 애매한 구간(PARTIAL~COVERED)과 누락 후보만 다시 물어
  "표현만 다른 대응"인지 확인한다. 실패하면 조용히 Tier 1 결과를 그대로 쓴다.

절대 원칙 (spec 4장)
1. source_page/source_text는 Requirement에서 그대로 가져온다. 만들어내지 않는다.
2. 모호하면 finding을 만들되 severity를 낮추고 사람 확인으로 넘긴다. 조용히 넘어가지 않는다.
3. 탐지율·정확도는 하드코딩하지 않는다 (scripts/evaluate_auditor.py가 측정).
4. Auditor는 제출을 막지도, 자동 수정하지도 않는다. 최종 판단은 사람이 한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core import org_storage, storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext
from app.services import analysis_store
from app.schemas.audit import (
    AuditCoverage,
    AuditFinding,
    AuditRun,
    ProposalSentenceRef,
    RequirementAuditState,
)
from app.schemas.requirement import Requirement
from app.services import llm_client, rfp_parser, wording
from app.services.text_match import (
    COVERED_THRESHOLD,
    PARTIAL_THRESHOLD,
    MatchScore,
    best_match,
    extract_numbers,
    find_number_conflicts,
)

logger = logging.getLogger(__name__)

AUDIT_RUN_DIR = DATA_ROOT / "public" / "audit_runs"

RUN_ID_RE = re.compile(r"^audit-[0-9a-f]{8,32}$")

# --- 문장 분리 -------------------------------------------------------------
# 한국어 종결(다./함./음./임.) 뒤에서 자르고, 줄바꿈도 문장 경계로 본다.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[다함음임]\.)\s*")
MIN_SENTENCE_LENGTH = 2

# --- 근거 없는 주장 (spec 3.2) ----------------------------------------------
_ABSOLUTE_CLAIM_RE = re.compile(r"보장|100\s*%|최고|완벽|무조건|반드시\s*달성")
# --- 충족을 단정하는 표현 (unchecked_condition 판정용) -----------------------
# 일반 어미(「합니다 · 하겠습니다 · 있습니다」)만으로는 단정이 아니다 — 거의 모든 문장이 걸렸다 (P1-04).
# 충족 주장 낱말(보유 · 충족 · 갖춤 · 「실적이 있」)만 보고, 「만족도」는 뺀다.
_ASSERTION_RE = re.compile(
    r"보유|충족|만족(?!도)|확보|배치|투입|완료하였|수행하였|갖추|갖춘|가능합니다|(?:실적|경험|자격)\S{0,2}\s*있"
)
# 미확인(확인 필요 · 여부 · 확정할 수 없음) · 부정(…지 않 · 못)은 충족을 단정하지 않는다.
# 「차질이 생기지 않도록 … 인력을 투입」의 「않도록」은 부정이 아니라 목적이다 — 단정 그대로 본다.
_NOT_ASSERTION_RE = re.compile(
    r"확인\s*(?:이|할)?\s*필요|여부|확정할\s*수\s*없|확인\s*후|미확인|지\s*(?:않(?!도록)|못)|못한|못하"
)


def asserts_fulfillment(text: str) -> bool:
    """초안 문장이 조건 충족을 단정하나 — 「요건을 충족하는 인력을 투입하겠습니다」는 예, 유보 · 부정 · 미확인은 아니오."""
    return bool(_ASSERTION_RE.search(text or "")) and not _NOT_ASSERTION_RE.search(text or "")

#: 「확인 필요」 자리표시 문장(43차 M18 · E2E-03) — 단정으로도 반영으로도 세지 않는다.
#: 앱이 내려 주는 제안서의 빈칸 「(담당자 입력)」과 변형 꼴도 자리표시다(2.7.0 · 계획 7 — 빈칸 문장이 요구사항 「반영」으로 셌다).
_PLACEHOLDER_RE = re.compile(r"확인\s*필요|[(\[（]\s*담당자\s*(?:입력|기재|작성)\s*[)\]）]")
_TAIL_CHECK_RE = re.compile(r"^\(?\s*확인\s*필요\s*\)?\s*[.。]?$")


def is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(text or ""))


_BLANK_CELL_RE = re.compile(r"[(\[（]\s*담당자\s*(?:입력|기재|작성)\s*[)\]）]")
_CHECK_NEEDED_RE = re.compile(r"확인\s*필요")
#: 빈칸 칸을 지운 뒤 남은 표 행이 대응 후보가 되려면 이만큼 글이 있어야 한다(공백 뺀 글자 수).
MIN_ROW_REST_CHARS = 8


def match_text(text: str) -> str:
    """요구사항 대응 후보로 쓸 글 — 「확인 필요」 줄 · 빈칸만 든 줄은 빈 글. 워드 표 한 행(「 | 」로 이은 줄)은 빈칸 칸만 지우고
    나머지 칸을 남긴다(2.7.0 검토 — 「추진 기간」 칸 하나가 빈칸인 일정 행이 통째로 빠져 거짓 「누락」이 났다). PDF 는 같은 행이
    칸 경계 없이 공백으로 이어지므로 빈칸 표시만 지운다(워드 · PDF 결과가 같게). 「보고 주기: (담당자 입력)」처럼 이름표만 남으면 뺀다."""
    if not text or _CHECK_NEEDED_RE.search(text):
        return ""
    if not _BLANK_CELL_RE.search(text):
        return text
    if " | " in text:
        rest = " | ".join(cell for cell in text.split(" | ") if not _BLANK_CELL_RE.search(cell)).strip()
    else:
        rest = re.sub(r"\s+", " ", _BLANK_CELL_RE.sub(" ", text)).strip()
        if rest.endswith((":", "：")):
            return ""
    return rest if len(re.sub(r"\s", "", rest)) >= MIN_ROW_REST_CHARS else ""


# --- 제출서류 요구사항 판별 ---------------------------------------------------
_DOCUMENT_CATEGORY_HINT = ("제출", "서류", "증빙")
_DOCUMENT_CONTENT_HINT = ("제출서류", "포함하여 제출", "모두 포함", "함께 제출", "제출하여야")
# 목록 구분자
_DOC_SPLIT_RE = re.compile(r"[,·、/]|및")
# 목록 뒤에 붙는 서술부를 잘라낸다 ("...를 모두 포함해야 한다")
_DOC_TAIL_RE = re.compile(r"(?:을|를)?\s*(?:모두\s*)?(?:포함|제출|첨부|작성|구비)\S*.*$")
# 목록 앞 도입부를 잘라낸다 ("제안서에는 ...")
_DOC_HEAD_RE = re.compile(r"^[^,·、/]*?(?:에는|에게|에|은|는)\s+")
_DOC_TRAILING_PARTICLE_RE = re.compile(r"(?:을|를|이|가|은|는|와|과|등)$")
MIN_DOCUMENT_NAME_LENGTH = 3

# 수치 불일치는 "대응 문장"이 있을 때만 본다.
# 초안의 숫자가 틀리면 그 문장의 점수 자체가 떨어져 covered 밖으로 밀려나므로
# (수치 토큰 가중치 3.0) 기준을 PARTIAL로 잡는다. 단위가 다르면 비교하지 않으므로 오탐은 낮다.
NUMBER_CHECK_THRESHOLD = PARTIAL_THRESHOLD

# --- Tier 2 (LLM) 제한 -------------------------------------------------------
LLM_BATCH_SIZE = 8
MAX_LLM_REQUIREMENTS = 40
MAX_LLM_SENTENCES = 120
MAX_LLM_SENTENCE_CHARS = 300


class AuditRunNotFoundError(LookupError):
    """저장된 검사 결과가 없다."""


class EmptyProposalError(ValueError):
    """초안에서 문장을 하나도 뽑지 못했다."""


# ---------------------------------------------------------------------------
# 1) 초안 문장 분리
# ---------------------------------------------------------------------------


def split_sentences(text: str) -> list[ProposalSentenceRef]:
    """초안을 문장 단위로 자른다. 인용을 위해 원문 표기를 그대로 남긴다."""
    sentences: list[ProposalSentenceRef] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        for chunk in _SENTENCE_SPLIT_RE.split(stripped):
            candidate = chunk.strip()
            if len(candidate) < MIN_SENTENCE_LENGTH:
                continue
            if _TAIL_CHECK_RE.match(candidate) and sentences:
                # 43차 M18 · E2E-03 — 「…없습니다. 확인 필요.」를 두 문장으로 나누지 않는다(「확인 필요」 표시가 앞 문장에서 떨어져 단정으로 읽혔다)
                last = sentences[-1]
                sentences[-1] = last.model_copy(update={"text": f"{last.text} {candidate}"})
                continue
            index = len(sentences)
            sentences.append(
                ProposalSentenceRef(id=f"S-{index + 1:03d}", index=index, text=candidate)
            )
    return sentences


# ---------------------------------------------------------------------------
# 2) 제출서류 이름 추출
# ---------------------------------------------------------------------------


def is_document_requirement(requirement: Requirement) -> bool:
    """제출서류를 나열한 요구사항인지."""
    if any(hint in requirement.category for hint in _DOCUMENT_CATEGORY_HINT):
        return any(hint in requirement.content for hint in _DOCUMENT_CONTENT_HINT)
    return "제출서류" in requirement.content


def extract_document_names(content: str) -> list[str]:
    """요구사항 문장에서 나열된 서류명을 뽑는다 (구분자 , · 、 / 및)."""
    body = _DOC_TAIL_RE.sub("", content).strip()
    body = _DOC_HEAD_RE.sub("", body, count=1).strip()
    names: list[str] = []
    for fragment in _DOC_SPLIT_RE.split(body):
        name = _DOC_TRAILING_PARTICLE_RE.sub("", fragment.strip()).strip()
        if len(name) < MIN_DOCUMENT_NAME_LENGTH:
            continue  # "보안" 같은 짧은 조각은 서류명으로 보지 않는다 (오탐 방지)
        if name not in names:
            names.append(name)
    return names


def _document_mentioned(name: str, draft_compact: str, draft_text: str) -> bool:
    compact = name.replace(" ", "")
    if compact and compact in draft_compact:
        return True
    tokens = [token for token in name.split() if token]
    return bool(tokens) and all(token in draft_text for token in tokens)


# ---------------------------------------------------------------------------
# 3) Tier 2 — LLM 재판정
# ---------------------------------------------------------------------------


class LlmCoverageItem(BaseModel):
    requirement_id: str
    covered: bool
    matched_sentence_index: int | None = None
    reason: str = Field(default="")


class LlmCoverageBatch(BaseModel):
    items: list[LlmCoverageItem]


_LLM_SYSTEM = (
    "당신은 공공입찰 제안서 검토자다. RFP 필수 요구사항이 제안서 초안에 "
    "표현이 달라도 실질적으로 반영되어 있는지 판정한다. "
    "초안에 근거 문장이 없으면 covered=false로 답한다. "
    "초안에 없는 내용을 추측하거나 만들어내지 않는다. "
    "covered=true이면 matched_sentence_index에 근거 문장의 번호를 반드시 넣는다. "
    "reason은 한국어 한 문장으로 쓴다. "
    + llm_client.SOURCE_GUARD  # 초안 · 요구사항 글은 자료다(2.7.0 · 계획 8)
)


def _llm_batch_prompt(requirements: list[Requirement], sentences: list[ProposalSentenceRef]) -> str:
    # 초안 · 요구사항 글은 경계 표식 안에 — 그 안의 지시는 따르지 않는다(2.7.0 · `llm_client.SOURCE_GUARD`)
    lines = ["[제안서 초안 문장]",
             llm_client.fenced("제안서 초안", "\n".join(f"{s.index}. {s.text[:MAX_LLM_SENTENCE_CHARS]}" for s in sentences))]
    lines.append("")
    lines.append("[판정할 RFP 필수 요구사항]")
    lines.append(llm_client.fenced("요구사항", "\n".join(f"- {r.requirement_id}: {r.content}" for r in requirements)))
    lines.append("")
    lines.append(
        "각 요구사항마다 {requirement_id, covered, matched_sentence_index, reason}을 "
        "items 배열로 출력하라."
    )
    return "\n".join(lines)


def _review_with_llm(
    requirements: list[Requirement], sentences: list[ProposalSentenceRef]
) -> tuple[dict[str, LlmCoverageItem], str | None]:
    """애매한 요구사항만 LLM에 재확인한다. 실패하면 ({}, 사유)로 조용히 폴백한다."""
    if not requirements or not sentences:
        return {}, None

    targets = requirements[:MAX_LLM_REQUIREMENTS]
    prompt_sentences = sentences[:MAX_LLM_SENTENCES]
    notes: list[str] = []
    if len(requirements) > len(targets):
        notes.append(f"요구사항 {len(requirements)}건 중 {len(targets)}건만 LLM 재확인")
    if len(sentences) > len(prompt_sentences):
        notes.append(f"초안 문장 {len(sentences)}개 중 앞 {len(prompt_sentences)}개만 전달")

    valid_ids = {requirement.requirement_id for requirement in targets}
    results: dict[str, LlmCoverageItem] = {}

    for start in range(0, len(targets), LLM_BATCH_SIZE):
        batch = targets[start : start + LLM_BATCH_SIZE]
        try:
            response = llm_client.complete_structured(
                system=_LLM_SYSTEM,
                user=_llm_batch_prompt(batch, prompt_sentences),
                schema=LlmCoverageBatch,
                temperature=0.0,
            )
        except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
            # 예외 이름은 로그로만 — 화면 메모에는 사람 말만 (28차)
            logger.warning("Auditor LLM 재확인 실패(%s), 규칙 결과를 유지합니다: %s", type(exc).__name__, exc)
            notes.append("LLM 재확인 실패 — 규칙 결과 유지")
            break

        for item in response.items:
            if item.requirement_id not in valid_ids:
                continue  # 없는 요구사항 ID는 버린다 (환각 방지)
            index = item.matched_sentence_index
            if index is not None and not (0 <= index < len(prompt_sentences)):
                index = None
            results[item.requirement_id] = item.model_copy(
                update={"matched_sentence_index": index}
            )

    return results, " / ".join(notes) if notes else None


# ---------------------------------------------------------------------------
# 4) 본체
# ---------------------------------------------------------------------------


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(severity, 5)


# ---------------------------------------------------------------------------
# 심각도 — 「제출에 실제로 어떤 영향을 주는가」
# ---------------------------------------------------------------------------
#
# 예전에는 필수 요구사항이 unmatched 이면 조건 없이 severity="high" 였다. 그래서
# 요구사항 추출을 개선해 32건 → 56건이 되자 미반영 26건이 전부 HIGH 로 올라왔고,
# 그 안에 「성과품 납품 후 자문 요청에 성실히 응하여야」 같은 계약 일반조건이 섞였다.
# 제안서 본문에 다시 적을 것이 아니라 계약하면 지키는 조항이다.
#
# 이제 두 축으로 정한다.
#   (1) response_scope — 어디서 답하는가. 제안서 본문 대상이 아니면 본문 누락이 아니다.
#   (2) criticality    — 참가 자체를 막는가(blocker), 배점에 걸리는가(high).
#
# **요구사항을 덜 추출해서 경고를 줄이는 것이 아니다.** 56건은 그대로 두고,
# 그중 무엇이 실제로 급한지를 가린다.

#: 제안서 본문에 서술하지 않아도 되는 범위. 본문 누락으로 단정하지 않는다.
_NON_BODY_SCOPES = frozenset(
    {
        "ELIGIBILITY_DOCUMENT",
        "SUBMISSION_CHECKLIST",
        "PRICE_PROPOSAL",
        "CONTRACT_COMPLIANCE",
        "INTERNAL_ACTION",
        "REFERENCE_ONLY",
        "CONDITIONAL",
        "NOT_APPLICABLE",
    }
)

#: 대응 대상이 아닌 범위의 «미반영» 심각도. 여기 있는 것은 본문 누락이 아니다.
_NON_BODY_MISSING_SEVERITY: dict[str, str] = {
    "CONTRACT_COMPLIANCE": "low",  # 지키면 되는 조항 — 본문에 다시 적지 않는다
    "REFERENCE_ONLY": "info",      # 배경·목적
    "CONDITIONAL": "info",         # 협의로 정해진다
    "NOT_APPLICABLE": "info",
}


def missing_severity(requirement: Requirement) -> str:
    """이 요구사항이 초안에 없을 때의 심각도.

    판단 순서가 곧 실무의 급한 순서다.

    1. **참가 자체를 막는가** — criticality="blocker" 면 범위와 무관하게 critical.
    2. **대응 대상이 아닌가** — 계약 준수·참고·조건부는 본문 누락이 아니다.
    3. **되돌릴 수 없는 행동인가** — 설명회 참석·사전등록은 날짜를 놓치면 끝이다.
    4. **배점·자격에 직접 걸리는가** — 평가기준 항목과 중요도 high 는 high.
    5. 나머지는 medium — 「운영방안 일부 부족」처럼 보완 가능한 것들이다.

    5번이 핵심이다. 예전에는 여기까지 전부 high 라 미반영 26건이 모두 붉게 떴고,
    그 안에서 진짜 급한 2건이 묻혔다.
    """
    scope = str(requirement.response_scope or "PROPOSAL_BODY")

    if requirement.criticality == "blocker":
        return "critical"
    if scope in _NON_BODY_MISSING_SEVERITY:
        return _NON_BODY_MISSING_SEVERITY[scope]
    if scope == "INTERNAL_ACTION":
        # 기한이 붙어 있고 우리가 움직여야 하는 것. 놓치면 되돌릴 수 없다.
        return "high" if requirement.action_required else "medium"
    if requirement.criticality == "high":
        return "high"
    if requirement.item_type == "EVALUATION":
        # 평가 배점에 직접 걸린다 — 빠지면 점수를 그대로 잃는다.
        return "high"
    if _has_numeric_obligation(requirement):
        # 「응답률 80% 이상 확보해야 한다」처럼 **수치 의무**가 걸린 항목.
        # 초안이 그 수치를 아예 약속하지 않으면 「운영방안 일부 부족」이 아니라
        # 계약 구속력이 있는 조건을 빠뜨린 것이다. 지시서의 HIGH 기준 「핵심 성능·수치」다.
        return "high"
    if requirement.criticality == "low" or requirement.item_type == "REFERENCE":
        return "low"
    return "medium"


def _has_numeric_obligation(requirement: Requirement) -> bool:
    """요구사항이 지켜야 할 «숫자»를 제시하는가.

    단순히 숫자가 들어 있는 것과는 다르다 — 한정어(이상·이하·내외·까지)가 붙어
    기준선을 이루는 경우만 본다. 「2026년」·「3회차」 같은 서술 숫자는 제외한다.
    """
    return any(token.at_least or token.at_most for token in extract_numbers(requirement.content))


def partial_severity(requirement: Requirement, *, llm_says_covered: bool = False) -> str:
    """부분 대응의 심각도.

    두 갈래를 구분한다 — 뜻이 다르기 때문이다.

    - `llm_says_covered=False` — 규칙 점수가 애매한 구간(0.20~0.35)이다. 정말로
      부족한 것일 수 있으므로 요구사항의 무게를 따라 올린다.
    - `llm_says_covered=True` — LLM 이 「표현만 다른 대응 문장이 있다」고 했다.
      이건 결함이 아니라 **확인 요청**이다. 낮게 둔다. 다만 참가를 막는 조건은
      LLM 판단만 믿고 넘길 수 없으므로 한 단계 올린다.
    """
    if llm_says_covered:
        return "medium" if requirement.criticality == "blocker" else "low"
    if requirement.criticality == "blocker":
        return "high"
    missing = missing_severity(requirement)
    return {"critical": "high", "high": "medium", "medium": "low", "low": "info", "info": "info"}[missing]


#: 같은 원인에서 나온 발견을 묶는 축. 화면이 REQ 번호 26개를 한 줄로 늘어놓지 않게 한다.
_GROUP_LABEL: dict[str, str] = {
    "PROPOSAL_BODY": "제안서 본문 대응 필요",
    "ELIGIBILITY_DOCUMENT": "참가자격 증빙 필요",
    "SUBMISSION_CHECKLIST": "제출서류 준비 필요",
    "PRICE_PROPOSAL": "가격제안서 대응 필요",
    "CONTRACT_COMPLIANCE": "계약 준수 확인",
    "INTERNAL_ACTION": "기한 안에 할 일 있음",
    "REFERENCE_ONLY": "참고 항목",
    "CONDITIONAL": "조건부 — 확인 필요",
    "NOT_APPLICABLE": "해당 없음",
}


#: 묶음을 보여주는 순서. 「담당자가 먼저 봐야 하는 것」이 앞이다.
#
# 예전에는 순서가 없었다. 그래서 화면이 묶음을 받은 순서대로 늘어놓았고, 실측(실공고
# g2b-R26BK01707959-000, 발견 38건)에서 **참가 자체가 막히는 critical 2건이
# 「참가자격 증빙 필요」 12건 안에** 섞여 스크롤 아래로 내려갔다. 무엇이 먼저인지는
# 화면이 아니라 여기서 정한다 — 화면이 여럿이어도 순서가 갈리지 않게.
_GROUP_RANK: dict[str, int] = {
    "risk:eligibility": 10,          # 참가 불가 위험 — 이것부터다
    "scope:PROPOSAL_BODY": 20,       # 필수 요구사항 누락
    "type:number_mismatch": 30,      # 수치·일정 불일치
    "scope:SUBMISSION_CHECKLIST": 40,  # 제출서류 준비
    "scope:ELIGIBILITY_DOCUMENT": 50,  # 참가자격 증빙 (막히는 것은 위로 빠져 있다)
    "type:unsupported_claim": 60,    # 근거 없는 회사 주장
    "blind:identity": 65,            # 평가본에 남은 회사 식별 정보(2.10.0 T8)
    "risk:evaluation": 70,           # 평가기준 대응 부족
    "scope:REFERENCE_ONLY": 90,      # 참고 항목 — 결함이 아니다
    "scope:NOT_APPLICABLE": 90,
}
#: 위 표에 없는 묶음(계약 준수·가격제안·조건부·미확인 조건 등)의 자리. 「나머지」다.
DEFAULT_GROUP_RANK = 80


def group_rank(group_key: str | None) -> int:
    """묶음의 표시 순서. 작을수록 먼저 본다. 모르는 키는 「나머지」로 둔다."""
    if not group_key:
        return DEFAULT_GROUP_RANK
    return _GROUP_RANK.get(group_key, DEFAULT_GROUP_RANK)


def group_of(finding_type: str, requirement: Requirement | None) -> tuple[str, str]:
    """(묶음 키, 묶음 이름). 요구사항이 없는 발견은 유형으로 묶는다.

    보는 순서가 곧 규칙이다 — 먼저 걸리는 것이 이긴다.

    1. **참가를 막는가**(criticality="blocker") — 유형·범위보다 먼저다. 참가가 막히면
       제안서를 아무리 잘 써도 소용이 없다. `missing_severity()` 가 blocker 를 조건 없이
       critical 로 올리는 것과 **같은 재료**를 쓴다. 묶음과 심각도가 서로 다른 이야기를
       하면 담당자는 둘 중 무엇을 믿을지 알 수 없다.
    2. **발견 자체에 이름이 있는가**(수치 불일치·미확인 조건·제출서류 누락) — 이쪽은
       「요구사항이 무엇인가」가 아니라 「초안에 무엇이 잘못됐는가」다. 요구사항 성격보다
       먼저 잡아야 수치 불일치가 평가기준 묶음으로 내려앉지 않는다.
    3. **요구사항 성격**(평가기준 → 대응 범위).

    item_type="ELIGIBILITY"·response_scope="ELIGIBILITY_DOCUMENT" 를 ①의 재료로 쓰지
    **않는** 이유: 자격 항목이라고 다 참가가 막히는 것이 아니다. 실공고 실측에서
    ELIGIBILITY_DOCUMENT 12건 중 참가를 막는 것은 2건뿐이었다. 범위로 묶으면 그 2건이
    다시 10건 속에 묻힌다. 나머지 자격 항목은 「참가자격 증빙 필요」에 그대로 남는다.
    """
    if requirement is None:
        labels = {
            "unsupported_claim": "회사 근거 없는 주장",
            "number_mismatch": "수치 불일치",
        }
        return f"type:{finding_type}", labels.get(finding_type, finding_type)
    if requirement.criticality == "blocker":
        return "risk:eligibility", "참가 불가 위험"
    if finding_type == "number_mismatch":
        return "type:number_mismatch", "수치 불일치"
    if finding_type == "unchecked_condition":
        return "type:unchecked_condition", "원문 확인 필요 — 초안이 충족을 단정함"
    if finding_type == "missing_document":
        # 빠진 것은 «서류»다. 요구사항이 어느 범위든 제출 준비 묶음에서 함께 챙긴다.
        return "scope:SUBMISSION_CHECKLIST", _GROUP_LABEL["SUBMISSION_CHECKLIST"]
    if requirement.item_type == "EVALUATION":
        # 배점에 직접 걸린다 — 빠지면 점수를 그대로 잃는다.
        # `missing_severity()` 가 EVALUATION 을 high 로 올리는 것과 짝이다. 예전에는
        # 이것이 「제안서 본문 대응 필요」에 섞여, 배점을 잃는 항목과 운영방안 부족이
        # 같은 줄에 놓였다.
        return "risk:evaluation", "평가기준 대응 부족"
    scope = str(requirement.response_scope or "PROPOSAL_BODY")
    return f"scope:{scope}", _GROUP_LABEL.get(scope, scope)


#: 앱이 내려 준 제안서 워드(proposal_export)가 문장마다 붙이는 근거 표기 · 머리 · 꼬리 줄 — 초안 본문이 아니다(2.1.6).
#: 그대로 검사하면 요구사항 원문 인용이 지운 대응 문장 대신 「반영」이 되고, 「제안요청서 57쪽」의 57 이 근거 없는 숫자로 잡혔다.
#: 워드 · 텍스트 판 · 핵심 섹션 · 전체 초안의 표기 꼴을 모두 담는다(텍스트 판 목록 줄은 「- 」로 시작).
_APP_ANNOTATION_RE = re.compile(
    r"^\s*(?:- )?(?:"
    r"\[(?:회사 근거|공고문 근거|AI 덧붙임)[^\]\n]{0,60}\]"
    r"|제안요청서 (?:\d+쪽 · )?\d+번 (?:요구사항|조항)"
    r"|회사 근거 [·—] "
    r"|확인 필요 — "
    r"|요구사항 카테고리: "
    r"|(?:섹션 \d+개\s+·\s+)?필수 요구사항 \d+건 중 대응 \d+건"
    r"|(?:공고|원문|생성)  \S"
    r"|초안 만든 날  "
    r"|(?:※ )?이 문서는 (?:AI가|규칙으로) 만든 초안입니다"
    r"|※ 추출 상한으로 요구사항 후보 \d+건"
    r"|\d+건입니다\. (?:근거도 의무 표현도 없어|제안서 본문에 추가할지)"
    r"|회사 근거자료가 없어 본문에서 뺀 요구사항 \d+건"
    r"|BidPilot AI · 근거는 제안요청서 원문"
    r")"
)
#: 본문 문장 머리(「12. 당사는 …」) — 넘어간 인용을 이어 빼다가 여기서 멈춘다.
_BODY_LINE_RE = re.compile(r"^\s*\d+\.\s")
#: 넘어간 인용을 이어 빼는 줄 수 상한(붙여 넣은 글).
_QUOTE_CARRY_LINES = 3


def strip_app_annotations(text: str) -> str:
    """앱이 붙인 근거 표기 줄만 뺀다 — 사람이 쓴 문장은 그대로(줄 머리가 앱 표기 꼴일 때만).

    앱 표기 줄은 늘 「”」로 끝난다(인용을 한 줄로 모음). 붙여 넣은 글에서 인용이 줄을 넘으면 닫는 따옴표 · 본문 줄 ·
    다음 표기 줄이 나올 때까지 최대 세 줄을 함께 뺀다 — 인용 안의 짝 없는 「“」(원문을 자른 꼴)로 본문을 지우지 않는다."""
    kept: list[str] = []
    carry = 0
    for line in text.splitlines():
        if carry and not _BODY_LINE_RE.match(line) and not _APP_ANNOTATION_RE.match(line):
            carry = 0 if "”" in line else carry - 1
            continue
        carry = 0
        if _APP_ANNOTATION_RE.match(line):
            stripped = line.rstrip()
            carry = _QUOTE_CARRY_LINES if "“" in stripped and not stripped.endswith("”") else 0
            continue
        kept.append(line)
    return "\n".join(kept)


def run_audit(
    procurement_id: str,
    proposal_text: str,
    *,
    use_llm: bool = True,
    source_document: str | None = None,
    context: "AnalysisContext | None" = None,
    mode: str = "standard",
    upload: dict[str, Any] | None = None,
) -> AuditRun:
    """요구사항(load_generated) ↔ 초안 문장을 역대조해 AuditRun을 만든다. 결과는 컨텍스트(회사·범위)에 고정된다.
    `upload`(`upload_checks` — 올리거나 붙여 넣은 글일 때만)가 있으면 평가본 식별 낱말 · 예산 배분안 산수도 본다(2.10.0 T8).

    `mode="change_impact"` 는 **이전 요구사항 집합 기준으로 만든 초안**을 최신 집합과
    일부러 견주는 경우다. 일반 검사와 결과를 섞으면 담당자가 「지금 초안의 결함」과
    「요구사항이 늘어난 것」을 구분할 수 없어서 실행 모드를 결과에 남긴다.
    """
    parsed = rfp_parser.load_generated(procurement_id)
    proposal_version, stale_requirements = _proposal_provenance(procurement_id, parsed, context)
    sentences = split_sentences(strip_app_annotations(proposal_text))
    if not sentences:
        raise EmptyProposalError("초안에서 문장을 찾지 못했습니다")

    sentence_texts = [sentence.text for sentence in sentences]
    # 43차 M18 — 「확인 필요」 자리표시 문장은 다른 요구사항의 대응 문장이 되지 않는다(남의 확인 필요 줄로 과업 5건이 「반영」이었다)
    match_texts = [match_text(text) for text in sentence_texts]
    draft_text = "\n".join(sentence_texts)
    draft_compact = draft_text.replace(" ", "")

    # 43차 Q22 — 반영 숫자의 분모는 본문 기준(평가 배점 · 서식 · 참고는 초안 본문 밖 — 초안과 같은 함수)
    from app.services.proposal_service import is_reference_requirement

    mandatory = [req for req in parsed.requirements if req.requirement_type == "mandatory" and not is_reference_requirement(req)]

    # --- Tier 1: 요구사항별 최적 대응 문장 ---------------------------------
    matches: dict[str, tuple[int, MatchScore]] = {}
    for requirement in mandatory:
        matches[requirement.requirement_id] = best_match(requirement.content, match_texts)

    findings: list[AuditFinding] = []
    states: dict[str, RequirementAuditState] = {}

    # LLM에 물어볼 후보: 누락 후보 + 애매한 중간 구간
    llm_candidates = [
        requirement
        for requirement in mandatory
        if matches[requirement.requirement_id][1].score < COVERED_THRESHOLD
    ]

    llm_results: dict[str, LlmCoverageItem] = {}
    llm_note: str | None = None
    llm_used = False
    if use_llm and llm_candidates and llm_client.completion_configured():
        llm_results, llm_note = _review_with_llm(llm_candidates, sentences)
        llm_used = bool(llm_results)

    # --- 요구사항별 판정 ----------------------------------------------------
    for requirement in mandatory:
        req_id = requirement.requirement_id
        index, score = matches[req_id]
        matched_sentence = sentences[index] if index >= 0 else None
        llm_item = llm_results.get(req_id)

        method: str = "RULE"
        reason: str | None = None
        detected_by: str = "RULE"

        if score.score >= COVERED_THRESHOLD:
            status = "matched"
        elif score.score >= PARTIAL_THRESHOLD:
            status = "partial"
        else:
            status = "unmatched"

        # LLM이 "표현만 다른 대응"이라고 하면 누락을 취소하고 partial로 낮춰 기록한다.
        if llm_item is not None:
            method = "AI_EXTRACTION"
            detected_by = "AI_EXTRACTION"
            reason = llm_item.reason.strip() or None
            if llm_item.covered:
                status = "partial"
                if llm_item.matched_sentence_index is not None:
                    matched_sentence = sentences[llm_item.matched_sentence_index]
            else:
                status = "unmatched"

        # 1) 누락 요구사항
        if status == "unmatched":
            recommendation = _missing_recommendation(requirement, reason)
            group_key, group_label = group_of("missing_requirement", requirement)
            findings.append(
                AuditFinding(
                    id="",
                    finding_type="missing_requirement",
                    # 무조건 high 가 아니다 — 어디서 답하는 항목인지, 참가를 막는지를 본다.
                    severity=missing_severity(requirement),  # type: ignore[arg-type]
                    response_scope=requirement.response_scope,
                    group_key=group_key,
                    group_label=group_label,
                    group_rank=group_rank(group_key),
                    requirement_id=req_id,
                    source_page=requirement.page,
                    source_text=requirement.source_text,
                    proposal_text=None,
                    recommendation=recommendation,
                    detected_by=detected_by,  # type: ignore[arg-type]
                    score=round(score.score, 4),
                )
            )
        elif status == "partial" and llm_item is None:
            # 규칙만으로는 애매한 구간. 조용히 넘기지 않고 낮은 severity로 사람에게 넘긴다.
            group_key, group_label = group_of("missing_requirement", requirement)
            findings.append(
                AuditFinding(
                    id="",
                    finding_type="missing_requirement",
                    severity=partial_severity(requirement),  # type: ignore[arg-type]
                    response_scope=requirement.response_scope,
                    group_key=group_key,
                    group_label=group_label,
                    group_rank=group_rank(group_key),
                    requirement_id=req_id,
                    sentence_id=matched_sentence.id if matched_sentence else None,
                    source_page=requirement.page,
                    source_text=requirement.source_text,
                    proposal_text=matched_sentence.text if matched_sentence else None,
                    recommendation=(
                        f"{_page_label(requirement)}에 부분적으로만 대응합니다. "
                        f"'{_short(requirement.content)}'의 핵심 조건이 초안 문장에 모두 "
                        "드러나는지 사람이 확인하세요."
                    ),
                    detected_by="RULE",
                    score=round(score.score, 4),
                )
            )
        elif status == "partial" and llm_item is not None:
            group_key, group_label = group_of("missing_requirement", requirement)
            findings.append(
                AuditFinding(
                    id="",
                    finding_type="missing_requirement",
                    severity=partial_severity(requirement, llm_says_covered=True),  # type: ignore[arg-type]
                    response_scope=requirement.response_scope,
                    group_key=group_key,
                    group_label=group_label,
                    group_rank=group_rank(group_key),
                    requirement_id=req_id,
                    sentence_id=matched_sentence.id if matched_sentence else None,
                    source_page=requirement.page,
                    source_text=requirement.source_text,
                    proposal_text=matched_sentence.text if matched_sentence else None,
                    recommendation=(
                        f"{_page_label(requirement)}은 표현이 달라 규칙 매칭에는 "
                        f"잡히지 않았습니다. AI 판단: {reason or '표현이 다른 대응 문장이 있음'} "
                        "— 사람이 최종 확인하세요."
                    ),
                    detected_by="AI_EXTRACTION",
                    score=round(score.score, 4),
                )
            )

        # 2) 수치 불일치 — 대응 문장이 있을 때만
        if matched_sentence is not None and score.score >= NUMBER_CHECK_THRESHOLD:
            required_values = _values_by_unit(requirement.content)
            # 묶음은 한 곳(group_of)에서만 정한다. 예전에는 여기서 "type:number_mismatch"를
            # 직접 박아, 참가를 막는 조건의 수치 어긋남도 평범한 수치 묶음으로 내려갔다.
            num_group_key, num_group_label = group_of("number_mismatch", requirement)
            for conflict in find_number_conflicts(requirement.content, matched_sentence.text):
                # 요구사항 원문이 같은 단위로 여러 기준을 제시하고(예: "최근 3년 ... 단, 최근 7년")
                # 초안이 그중 하나를 쓴 경우는 단정하지 않고 사람 확인으로 넘긴다.
                alternatives = required_values.get(conflict.unit, set())
                ambiguous = len(alternatives) > 1 and conflict.found.value in alternatives
                if ambiguous:
                    recommendation = (
                        f"{conflict.reason} 다만 {_page_label(requirement)} 원문에는 같은 단위의 "
                        f"기준이 여러 개({', '.join(_format_values(alternatives, conflict.unit))}) "
                        "있습니다. 어느 기준이 적용되는지 원문을 확인한 뒤 담당자가 판정하세요."
                    )
                else:
                    recommendation = (
                        f"{conflict.reason} {_page_label(requirement)} 원문을 기준으로 "
                        f"초안의 '{conflict.found.raw}'{_object_particle(conflict.found.raw)} "
                        f"'{conflict.required.raw}'에 맞게 수정하세요."
                    )
                findings.append(
                    AuditFinding(
                        id="",
                        finding_type="number_mismatch",
                        severity="medium" if ambiguous else "high",
                        response_scope=requirement.response_scope,
                        group_key=num_group_key,
                        group_label=num_group_label,
                        group_rank=group_rank(num_group_key),
                        requirement_id=req_id,
                        sentence_id=matched_sentence.id,
                        source_page=requirement.page,
                        source_text=requirement.source_text,
                        proposal_text=matched_sentence.text,
                        recommendation=recommendation,
                        detected_by="RULE",
                        score=round(score.score, 4),
                    )
                )

        # 3) 제출서류 누락
        if is_document_requirement(requirement):
            names = extract_document_names(requirement.content)
            missing_docs = [
                name
                for name in names
                if not _document_mentioned(name, draft_compact, draft_text)
            ]
            if missing_docs:
                # blocker 면 severity 가 critical 이다 — 묶음도 「참가 불가 위험」으로
                # 같이 올라가야 한다. group_of 가 그 짝을 맞춘다.
                doc_group_key, doc_group_label = group_of("missing_document", requirement)
                findings.append(
                    AuditFinding(
                        id="",
                        finding_type="missing_document",
                        severity="critical" if requirement.criticality == "blocker" else "high",
                        response_scope=requirement.response_scope,
                        group_key=doc_group_key,
                        group_label=doc_group_label,
                        group_rank=group_rank(doc_group_key),
                        requirement_id=req_id,
                        sentence_id=matched_sentence.id if matched_sentence else None,
                        source_page=requirement.page,
                        source_text=requirement.source_text,
                        proposal_text=matched_sentence.text if matched_sentence else None,
                        recommendation=(
                            f"{_page_label(requirement)}에서 요구한 제출서류 중 "
                            f"{', '.join(missing_docs)}이(가) 초안에 언급되지 않았습니다. "
                            "제출서류 목록에 추가하고 실제 구비 여부를 확인하세요."
                        ),
                        detected_by="RULE",
                        score=round(score.score, 4),
                    )
                )

        # 4) 미확인 조건 — 원 요구사항 status가 check인데 초안이 충족을 단정
        if (
            requirement.status == "check"
            and matched_sentence is not None
            and score.score >= PARTIAL_THRESHOLD
            and asserts_fulfillment(matched_sentence.text)
        ):
            status = "check"
            chk_group_key, chk_group_label = group_of("unchecked_condition", requirement)
            findings.append(
                AuditFinding(
                    id="",
                    finding_type="unchecked_condition",
                    severity="medium",
                    response_scope=requirement.response_scope,
                    group_key=chk_group_key,
                    group_label=chk_group_label,
                    group_rank=group_rank(chk_group_key),
                    requirement_id=req_id,
                    sentence_id=matched_sentence.id,
                    source_page=requirement.page,
                    source_text=requirement.source_text,
                    proposal_text=matched_sentence.text,
                    recommendation=(
                        # 저장 값(`CHECK`)을 문장에 그대로 적던 자리다. 화면에 영문 판정값을
                        # 내지 않는다 (규칙 11 · 0922 §4-D-6) — 담당자가 읽는 말로 적는다.
                        f"{_page_label(requirement)}은 원문만으로 충족을 확정할 수 없어 "
                        "「확인 필요」로 남아 있습니다. 초안이 충족을 단정하고 있으니 "
                        "실적증명서·경력증명 등 객관적 증빙을 확인한 뒤 담당자가 판정하세요."
                    ),
                    detected_by="RULE",
                    score=round(score.score, 4),
                )
            )

        states[req_id] = RequirementAuditState(
            requirement_id=req_id,
            requirement_type=requirement.requirement_type,
            status=status,  # type: ignore[arg-type]
            score=round(score.score, 4),
            matched_sentence_id=matched_sentence.id if matched_sentence else None,
            page=requirement.page,
            method=method,  # type: ignore[arg-type]
            reason=reason,
        )

    # 5) 근거 없는 주장 — 초안에만 있는 수치·단정 표현
    findings.extend(_unsupported_claims(parsed.requirements, sentences, ledger_numbers=_ledger_numbers(context)))
    # 6) 올리거나 붙여 넣은 글만 — 평가본 공고면 남은 회사 식별 낱말(blind6) · 예산 배분안 산수(budget2 · 2.10.0 T8)
    if upload:
        findings.extend(_blind_identity(draft_text, upload.get("identity")))
        findings.extend(_budget_math(upload))

    # 심각도가 먼저다(기존 계약). 같은 심각도 안에서는 묶음 순서를 따른다 — 예전에는
    # finding_type 알파벳순이라 「참가 불가 위험」과 「참고 항목」이 뒤섞여 나왔다.
    findings.sort(
        key=lambda f: (
            _severity_rank(f.severity),
            group_rank(f.group_key),
            f.finding_type,
            f.requirement_id or "",
            f.sentence_id or "",
        )
    )
    for number, finding in enumerate(findings, start=1):
        finding.id = f"AF-{number:03d}"

    coverage_extra = _coverage_breakdown(parsed.requirements, states)
    covered_ids = [rid for rid, state in states.items() if state.status == "matched"]
    partial_ids = sorted(rid for rid, state in states.items() if state.status in ("partial", "check"))
    missing_ids = sorted(rid for rid, state in states.items() if state.status == "unmatched")

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.finding_type] = counts.get(finding.finding_type, 0) + 1

    return AuditRun(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        procurement_id=procurement_id,
        created_at=storage.utc_now(),  # 공고 변경 시각과 견준다 (runStamp)
        coverage=AuditCoverage(
            total=len(mandatory),
            covered=len(covered_ids),
            partial=len(partial_ids),
            missing=len(missing_ids),
            missing_requirement_ids=missing_ids,
            partial_requirement_ids=partial_ids,
            # 추출 상한에 잘렸으면 Coverage는 검사한 범위 안에서만 유효하다.
            truncated=parsed.truncated,
            candidate_count=parsed.candidate_count,
            **coverage_extra,
        ),
        counts=counts,
        findings=findings,
        sentence_count=len(sentences),
        llm_used=llm_used,
        llm_note=llm_note,
        requirement_states=[states[req.requirement_id] for req in mandatory],
        sentences=sentences,
        source_document=source_document or parsed.document,
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
        requirement_set_id=parsed.requirement_set_id,
        requirement_set_hash=parsed.requirement_set_hash,
        proposal_version=proposal_version,
        proposal_hash=proposal_hash(proposal_text),
        mode=mode,
        stale_requirements=stale_requirements,
    )


def _proposal_provenance(
    procurement_id: str, parsed: Any, context: "AnalysisContext | None"
) -> tuple[int | None, bool]:
    """저장된 초안이 몇 판인지, 그리고 이전 요구사항 집합 기준인지.

    저장된 초안이 없으면 (None, False) — 붙여넣기 검사는 판 번호가 없다.
    """
    from app.services import proposal_service

    try:
        section = proposal_service.load_section(procurement_id, context)
    except Exception:  # noqa: BLE001 — 초안이 없거나 못 읽어도 검사 자체는 계속한다
        return None, False
    # 판정 규칙은 requirement_set.proposal_basis 한 곳에만 둔다 — 두 벌이 되면
    # 화면의 「이전 기준입니다」와 감사 결과의 stale 플래그가 갈린다.
    from app.services import requirement_set

    basis = requirement_set.proposal_basis(
        proposal_set_hash=getattr(section, "requirement_set_hash", None),
        proposal_mandatory_total=getattr(section, "mandatory_total", None),
        current_set_hash=getattr(parsed, "requirement_set_hash", None),
        current_mandatory_count=getattr(parsed, "mandatory_count", None),
        has_proposal=True,
    )
    return getattr(section, "proposal_version", None), basis == "stale_requirements"


def proposal_hash(proposal_text: str) -> str:
    """초안 본문의 해시. 「이 감사 결과가 지금 초안을 본 것인가」를 대조하는 값."""
    normalized = re.sub(r"\s+", " ", proposal_text or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


#: 제안서 «본문»으로 답하는 범위. 나머지는 본문 Coverage 분모에서 빠진다.
_BODY_SCOPE = "PROPOSAL_BODY"


def _coverage_breakdown(
    requirements: list[Requirement], states: dict[str, RequirementAuditState]
) -> dict[str, Any]:
    """분모를 화면 전체가 같이 쓰도록 한 곳에서 센다.

    예전에는 `total` 하나뿐이었고 그 값이 «필수만»(55)인데 다른 화면은 «전체»(56)를
    적어 두 숫자가 설명 없이 섞였다. 이제 어느 분모인지 이름으로 구분한다.

    범위별 Coverage 도 여기서 낸다 — 참가자격은 「확인 완료/필요」, 제출물은
    「준비 완료/미완료」로 세어야 하고, 그것을 제안서 본문 Coverage 와 같은 통에
    넣으면 계약 준수사항이 본문 누락으로 읽힌다.
    """
    body = {"total": 0, "covered": 0, "partial": 0, "missing": 0}
    eligibility = {"total": 0, "confirmed": 0, "needs_check": 0, "unmet": 0}
    submission = {"total": 0, "ready": 0, "incomplete": 0, "needs_check": 0}
    not_body = 0
    mandatory_total = 0
    # 「참가 불가 위험」 건수. 범위별 통(eligibility/submission)으로는 셀 수 없다 —
    # blocker 는 자격뿐 아니라 제출·일정 항목에도 붙기 때문이다(item_classifier의
    # _BLOCKER_BY_TYPE). Auditor 묶음 risk:eligibility 와 **같은 재료**로 세서
    # 화면의 「참가 불가 위험 n건」과 묶음 안 건수가 어긋나지 않게 한다.
    blocking_total = 0
    blocking_unresolved = 0

    for req in requirements:
        if req.requirement_type == "mandatory":
            mandatory_total += 1
        scope = str(req.response_scope or _BODY_SCOPE)
        state = states.get(req.requirement_id)
        status = state.status if state else None

        if req.criticality == "blocker":
            blocking_total += 1
            if status != "matched":
                # 대응 문장이 없거나 애매하다. 「불충족」이라고 단정하지 않는다 —
                # 증빙 확인은 사람 몫이다.
                blocking_unresolved += 1

        if scope == _BODY_SCOPE:
            body["total"] += 1
            if status == "matched":
                body["covered"] += 1
            elif status in ("partial", "check"):
                body["partial"] += 1
            elif status == "unmatched":
                body["missing"] += 1
            continue

        not_body += 1
        if scope == "ELIGIBILITY_DOCUMENT":
            eligibility["total"] += 1
            # 원문만으로 「충족」을 단정하지 않는다 — 증빙을 사람이 확인해야 한다.
            if status == "matched":
                eligibility["confirmed"] += 1
            else:
                eligibility["needs_check"] += 1
        elif scope == "SUBMISSION_CHECKLIST":
            submission["total"] += 1
            if status == "matched":
                submission["ready"] += 1
            elif status == "unmatched":
                submission["incomplete"] += 1
            else:
                submission["needs_check"] += 1

    # AuditCoverage 에 blocker 전용 필드는 없다. eligibility 는 자유형 dict 이므로
    # 필드를 늘리지 않고 여기에 담는다 (키 이름으로 「범위와 무관하다」를 드러낸다).
    eligibility["blocking_total"] = blocking_total
    eligibility["blocking_unresolved"] = blocking_unresolved

    return {
        "total_all": len(requirements),
        "mandatory_total": mandatory_total,
        "optional_or_conditional_total": len(requirements) - mandatory_total,
        "not_proposal_body_total": not_body,
        "proposal_body": body,
        "eligibility": eligibility,
        "submission": submission,
    }


def _ledger_numbers(context: "AnalysisContext | None") -> dict[tuple[float, str], int]:
    """이 회사 실적 원장 중 외부 사용 「가능」 행의 숫자 → 행 번호(43차 M18 · E2E-09 — 원장에 있는 진짜 실적 숫자를 지우라고 했다).
    내부 범위가 아니면 비어 있다(공개 데모에 실제 회사 원장을 섞지 않는다)."""
    from app.services import performance_match_service as _pm

    out: dict[tuple[float, str], int] = {}
    for row in _pm.eligible_rows(_pm.load_ledger_for(context)):
        text = " ".join(str(row.get(k) or "") for k in ("year", "period", "title", "summary", "evidence_note"))
        for token in extract_numbers(text):
            out.setdefault((token.value, token.unit), int(row.get("seq") or 0))
    return out


def upload_checks(procurement_id: str, proposal_text: str, context: "AnalysisContext | None") -> dict[str, Any]:
    """제출 전 점검에 올리거나 붙여 넣은 글에만 도는 입찰 초안 검사의 재료(2.10.0 T8 — 앱이 만든 초안 글에는 돌리지 않는다):
    평가본 식별 낱말(`bid_quality_gate.draft_identity` · 평가본 공고가 아니면 None) · 예산 배분안 행(`budget_lines` · 표가 없으면 None) ·
    사업금액(저장 초안). 초안을 못 읽으면 그 검사만 건너뛴다(요구사항 점검은 그대로)."""
    from app.services import bid_quality_gate

    found = bid_quality_gate.budget_lines(proposal_text.splitlines())
    try:
        identity = bid_quality_gate.draft_identity(procurement_id, context)
        cap = bid_quality_gate.draft_budget_cap(procurement_id, context) if found else None
    except Exception:  # noqa: BLE001 — 식별 · 사업금액을 못 읽어도 요구사항 점검은 낸다
        logger.warning("입찰 초안 값을 읽지 못해 식별 · 사업금액 검사를 건너뜁니다 (procurement_id=%s)", procurement_id, exc_info=True)
        identity = cap = None
    return {"identity": identity, "budget": found[1] if found else None, "cap": cap}


def upload_key(upload: dict[str, Any]) -> str:
    """run_key 덧붙임 — 평가본 공고(식별 낱말 · 평가본만인가) · 예산 표의 사업금액이 결과를 바꾼다(같은 글이어도 초안을 다시 쓰면 다시 검사 ·
    T8 검토). 둘 다 없으면 빈 글 — 그 밖의 공고는 키 · 저장 결과 그대로(점검 규칙 판 5 그대로). 값은 키 해시에만 들어간다."""
    parts = []
    if upload.get("identity"):
        words, blind_only = upload["identity"]
        parts.append(f"blind:{blind_only}:" + "|".join(sorted(f"{kind}={word}" for kind, word in words)))
    if upload.get("budget") is not None:
        parts.append(f"budget:{upload.get('cap')}")
    return "".join(parts)


def _blind_identity(draft_text: str, identity: tuple[list[tuple[str, str]], bool] | None) -> list[AuditFinding]:
    """평가본 공고(저장된 입찰 제안서 초안 형식이 평가본)면 올린 글에 남은 회사 식별 낱말 — 품질 게이트 · PDF 검사와 같은 낱말 · 같은 세기
    (`bid_quality_gate.identity_findings` — 회사 이름 · 대표자 · 연락처 · 번호가 있으면 critical, 실적 기관 · 주소 등만이면 high · 원본 · 사본을
    함께 내는 공고는 올린 글이 회사명 포함본일 수 있어 high 까지). 종류는 한 줄로 모은다(처리 열쇠가 하나 — 하나를 「고침」으로 두면 다른 종류도
    풀리던 것 · T8 검토). 값 · 문장은 싣지 않는다(종류 · 수만 · D7)."""
    from app.services import bid_quality_gate

    if not identity:
        return []
    words, blind_only = identity
    found = bid_quality_gate.identity_findings([("올린 글", draft_text)], words)
    if not found:
        return []
    severity = "critical" if blind_only and any(f["severity"] == "BLOCKER" for f in found) else "high"
    head = "" if blind_only else "평가본(회사명 없는 판)을 올렸다면 — "
    detail = " / ".join(f"{f['title']} — {f['detail'].split(' — 자리')[0]}" for f in found)
    return [AuditFinding(
        id="", finding_type="blind_identity", severity=severity,  # type: ignore[arg-type]
        group_key="blind:identity", group_label="평가본에 회사 식별 정보가 남음", group_rank=group_rank("blind:identity"),
        recommendation=f"{head}{detail}. 공고가 평가본에 회사를 알아볼 수 있는 정보를 막습니다 — 회사 이름 · 대표자 · 연락처 · 번호 · "
                       "실적 기관 이름 · 실적 사업명을 지우거나 「당사」 · 기관 유형 · 연도와 분야로 바꾸세요(값은 기록에 남기지 않습니다).",
        detected_by="RULE",
    )]


def _budget_math(upload: dict[str, Any]) -> list[AuditFinding]:
    """올린 글의 예산 배분안 산수(품질 게이트 · PDF 검사와 같은 `plan_validation.budget_breaks` · 2.10.0 budget2) — 어긋남을 한 줄로
    (수치 불일치 묶음 · 요구사항 없음 · 처리 열쇠 하나)."""
    from app.services import plan_validation

    rows = upload.get("budget")
    breaks = plan_validation.budget_breaks(rows, upload.get("cap")) if rows else []
    if not breaks:
        return []
    key, label = group_of("number_mismatch", None)
    return [AuditFinding(
        id="", finding_type="number_mismatch", severity="high", group_key=key, group_label=label, group_rank=group_rank(key),
        recommendation=f"예산 배분안 산수가 맞지 않습니다 — {' · '.join(breaks[:5])}{' 외' if len(breaks) > 5 else ''}. "
                       "수량 × 단가 · 항목 합 · 부가세(10%) · 합계 · 사업금액을 다시 계산하세요.",
        detected_by="RULE",
    )]


def _unsupported_claims(
    requirements: list[Requirement], sentences: list[ProposalSentenceRef], *, ledger_numbers: dict[tuple[float, str], int] | None = None
) -> list[AuditFinding]:
    """RFP 어디에도 없는 수치나 단정 표현을 쓴 초안 문장 (spec 3.2). 회사 원장(외부 사용 가능)에 있는 숫자는 근거가 있다(43차 M18)."""
    rfp_numbers: set[tuple[float, str]] = set()
    for requirement in requirements:
        for token in extract_numbers(f"{requirement.content}\n{requirement.source_text}"):
            rfp_numbers.add((token.value, token.unit))

    findings: list[AuditFinding] = []
    for sentence in sentences:
        tokens = extract_numbers(sentence.text)
        unsupported = [
            token for token in tokens
            if (token.value, token.unit) not in rfp_numbers and (token.value, token.unit) not in (ledger_numbers or {})
        ]
        absolute = _ABSOLUTE_CLAIM_RE.search(sentence.text)
        if not unsupported and not absolute:
            continue
        # 수치가 모두 RFP 원문에 있으면 단정 표현이 있어도 근거 없는 주장으로 보지 않는다.
        if not unsupported and tokens:
            continue

        if unsupported:
            quoted = ", ".join(sorted({token.raw for token in unsupported}))
            recommendation = (
                f"초안의 「{quoted}」는 제안요청서 어디에도 없는 숫자입니다. "
                "회사 근거를 연결하거나 이 문장을 지우세요. "
                "근거가 확인되기 전에는 충족으로 판정하지 않습니다."
            )
        else:
            recommendation = (
                f"'{absolute.group(0) if absolute else ''}' 같은 단정 표현은 근거 없이 "
                "쓸 수 없습니다. 회사 수행근거를 연결하거나 표현을 완화하세요."
            )
        findings.append(
            AuditFinding(
                id="",
                finding_type="unsupported_claim",
                severity="medium",
                group_key="type:unsupported_claim",
                group_label="회사 근거 없는 주장",
                group_rank=group_rank("type:unsupported_claim"),
                sentence_id=sentence.id,
                proposal_text=sentence.text,
                recommendation=recommendation,
                detected_by="RULE",
            )
        )
    return findings


def _values_by_unit(text: str) -> dict[str, set[float]]:
    """요구사항 원문이 같은 단위로 제시한 값들 (복수 기준 판별용)."""
    values: dict[str, set[float]] = {}
    for token in extract_numbers(text):
        values.setdefault(token.unit, set()).add(token.value)
    return values


def _format_values(values: set[float], unit: str) -> list[str]:
    return [
        f"{int(value) if value.is_integer() else value}{unit}" for value in sorted(values)
    ]


def _object_particle(word: str) -> str:
    """목적격 조사 '을/를'을 고른다. 한글 받침이 있으면 '을'.

    수치 표현이 '10회'(받침 없음)와 '30시간'(받침 있음)처럼 섞여 있어
    하나로 고정하면 권고 문장이 어색해진다. 이 문장은 화면과 발표자료에
    그대로 나가므로 조사를 맞춘다.
    """
    if not word:
        return "를"
    last = word[-1]
    if "가" <= last <= "힣":
        return "을" if (ord(last) - 0xAC00) % 28 else "를"
    return "를"


def _short(text: str, limit: int = 60) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _page_label(requirement: Requirement) -> str:
    """「제안요청서 17쪽 · 14번 요구사항」 — 내부 번호(REQ-014)를 화면에 내지 않는다(32차 어려운 글 #18)."""
    return wording.rfp_ref(requirement.page, requirement.requirement_id)


def _missing_recommendation(requirement: Requirement, llm_reason: str | None) -> str:
    base = (
        f"{_page_label(requirement)} '{_short(requirement.title or requirement.content)}'에 "
        f"대응하는 문장이 초안에 없습니다. 원문: \"{_short(requirement.source_text, 90)}\" — "
        "해당 내용을 제안서 본문에 추가하세요."
    )
    if llm_reason:
        return f"{base} (AI 재확인: {llm_reason})"
    return base


# ---------------------------------------------------------------------------
# 5) 저장 / 조회
# ---------------------------------------------------------------------------


def run_path(run_id: str, context: "AnalysisContext | None" = None, procurement_id: str | None = None) -> Path:
    """저장 경로. internal 은 조직 분석 폴더(analyses/{pid}/audit_runs/), public_demo 는 공개 위치."""
    if not RUN_ID_RE.match(run_id):
        raise AuditRunNotFoundError(run_id)
    if analysis_store.is_private(context) and context is not None and procurement_id:
        return analysis_store.private_dir(context, procurement_id) / "audit_runs" / f"{run_id}.json"
    return AUDIT_RUN_DIR / f"{run_id}.json"


def save_run(run: AuditRun, *, context: "AnalysisContext | None" = None) -> AuditRun:
    target = run_path(run.id, context, run.procurement_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = run.model_dump(mode="json")
    analysis_store.stamp(payload, context)
    run.organization_id = payload["organization_id"]
    run.evidence_scope = payload["evidence_scope"]
    # 고정된 `.tmp` 이름은 동시에 쓰는 두 요청이 서로를 덮어쓴다. 저장소의 단일 쓰기
    # 경로를 쓴다 — 거기서 pid·thread 로 이름을 가른다 (ISSUE-032).
    storage.write_json_atomic(target, payload)
    return run


def latest_stored_run(procurement_id: str, context: "AnalysisContext") -> AuditRun | None:
    """이 공고의 저장된 검사 결과 중 가장 최근 것. 없으면 None.

    검사 결과 파일 이름은 run id 뿐이라 「공고 → 최신 결과」 색인이 없다. 그래서
    prune_runs 와 같은 폴더를 같은 방식으로 훑어 procurement_id 가 같은 것만 고른다.
    """
    storage.safe_id(procurement_id, what="공고 id")
    # 저장 위치 규칙(공개 위치 / 조직 분석 폴더)을 아는 곳은 run_path 하나뿐이다.
    # 여기서는 폴더만 필요하므로 형식만 맞는 더미 id 를 넘긴다 — prune_runs 도 같은 방법을 쓴다.
    folder = run_path("audit-000000000000", context, procurement_id).parent
    if not folder.exists():
        return None
    latest: AuditRun | None = None
    latest_key: tuple[datetime, float] | None = None
    # 공용 폴더에는 «모든» 공고의 결과가 섞여 있고 총량이 묶여 있지 않다(실측 546개·16MB).
    # 전부 파싱하면 화면을 열 때마다 수백 개 파일을 읽는다. 최근에 쓴 것부터 보고, 이 공고의
    # 결과를 찾으면 거기서 멈춘다 — 「가장 최근」을 찾는 일이라 그것으로 충분하다.
    paths = sorted(folder.glob("audit-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            run = AuditRun.model_validate_json(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            # 깨진 파일 한 개가 「검사한 적 없음」으로 둔갑하지 않게 건너뛴다.
            continue
        if run.procurement_id != procurement_id:
            continue
        if context.is_private and run.organization_id not in (None, context.organization_id):
            continue  # load_run 과 같은 규칙 — 다른 회사 결과는 보이지 않는다
        # created_at 이 같은 초에 겹치면 파일 시각으로 가른다.
        key = (storage.ensure_aware(run.created_at), mtime)
        if latest_key is None or key > latest_key:
            latest, latest_key = run, key
        # 파일 시각 내림차순으로 훑는다. 이 공고의 결과를 하나 찾았으면 그 뒤의 파일은 모두
        # 더 오래 전에 쓰인 것이므로 더 볼 이유가 없다 — 「가장 최근」을 찾는 일이다.
        if latest is not None:
            break
    return latest


def load_run(run_id: str, *, context: "AnalysisContext | None" = None) -> AuditRun:
    """run id 로 조회. 컨텍스트가 internal 이면 그 조직의 분석 폴더만, 아니면 공개 위치만 본다 (다른 조직 결과는 보이지 않는다)."""
    if not RUN_ID_RE.match(run_id):
        raise AuditRunNotFoundError(run_id)
    if analysis_store.is_private(context) and context is not None:
        root = org_storage.storage_for(context.organization_id).analyses_dir
        for path in root.glob(f"*/audit_runs/{run_id}.json") if root.exists() else []:
            run = AuditRun.model_validate_json(path.read_text(encoding="utf-8"))
            if run.organization_id in (None, context.organization_id):
                return run
        raise AuditRunNotFoundError(run_id)
    path = AUDIT_RUN_DIR / f"{run_id}.json"
    if not path.exists():
        raise AuditRunNotFoundError(run_id)
    return AuditRun.model_validate_json(path.read_text(encoding="utf-8"))


#: 공고 하나당 남겨 둘 검사 결과 개수. 넘으면 오래된 것부터 지운다.
#:
#: 13일 만에 546개 16MB 가 쌓였고 그중 80개는 바이트까지 같았다. 화면을 한 번 열 때마다
#: 저장된 초안을 **다시** 검사하고 새 파일을 만들었기 때문이다. 이력은 남기되 무한히 쌓지 않는다.
RUN_HISTORY_LIMIT = 20

#: 점검 규칙 판 — 규칙(문장 나누기 · 분모 · 단정 판단)을 바꾸면 올린다. run_key 에 들어가 같은 초안이어도 옛 결과를 돌려주지 않는다.
#: 1 = 처음 · 2 = 43차 M18 문장 합치기 · 45차 M6 본문 분모 · 3 = P1-04 단정 판단 좁힘(일반 어미 뺌 · 유보 · 부정 제외)
#: 4 = 2.1.6 앱이 붙인 근거 표기 줄을 초안 본문에서 뺌(`strip_app_annotations`)
#: 5 = 2.7.0 「(담당자 입력)」 빈칸도 자리표시 · 표 행은 빈칸 칸만 빼고 대조(`match_text`)
AUDIT_LOGIC_VERSION = 5


def run_key(
    procurement_id: str,
    proposal_text: str,
    *,
    requirement_set_hash: str | None,
    mode: str,
    use_llm: bool,
    context: "AnalysisContext | None" = None,
    extra: str = "",
) -> str:
    """같은 입력이면 같은 id. 검사를 두 번 돌릴 이유를 없앤다. `extra` — 올린 글 검사의 재료(`upload_key` · 비면 옛 키 그대로).

    같은 초안을 같은 요구사항 집합으로 검사하면 결과도 같다. 예전에는 실행마다 uuid 를
    새로 뽑아 바이트까지 같은 파일이 쌓였고, 「실행 기록」에 매번 다른 id 가 찍혀
    «무엇이 바뀌었나»를 추적할 수 없었다.

    회사·근거 범위도 키에 넣는다 — 근거가 다르면 결과가 다르다.
    """
    parts = [
        procurement_id,
        requirement_set_hash or "",
        proposal_hash(proposal_text),
        mode,
        "llm" if use_llm else "rule",
        (context.organization_id if context else "") or "",
        (context.evidence_scope if context else "") or "",
        f"v{AUDIT_LOGIC_VERSION}",  # 규칙을 고친 뒤에도 같은 초안이면 옛 결과가 나왔다 (P1-04 · UI c · d)
        extra,
    ]
    digest = hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
    return f"audit-{digest[:12]}"


def prune_runs(procurement_id: str, *, context: "AnalysisContext | None" = None, keep: int | None = None) -> int:
    """이 공고의 검사 결과를 최근 `keep` 개만 남긴다. 지운 개수를 돌려준다.

    기본값을 인자 자리에 두지 않는다 — 기본 인자는 «정의 시점»에 굳어서, 상한을 바꿔도
    (설정이든 테스트든) 따라오지 않는다.
    """
    if keep is None:
        keep = RUN_HISTORY_LIMIT
    folder = run_path("audit-000000000000", context, procurement_id).parent
    if not folder.exists():
        return 0
    runs: list[tuple[float, Path]] = []
    for path in folder.glob("audit-*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if payload.get("procurement_id") != procurement_id:
            continue
        runs.append((path.stat().st_mtime, path))
    if len(runs) <= keep:
        return 0
    runs.sort(reverse=True)
    removed = 0
    for _mtime, path in runs[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def run_and_store(
    procurement_id: str,
    proposal_text: str,
    *,
    use_llm: bool = True,
    source_document: str | None = None,
    context: "AnalysisContext | None" = None,
    mode: str = "standard",
    uploaded: bool = False,
) -> AuditRun:
    """검사하고 저장한다. **같은 입력이면 다시 돌리지 않고 이전 결과를 그대로 돌려준다.**

    POST 를 멱등으로 만드는 것이다 — 화면이 로드마다 검사를 요청해도 파일이 늘지 않는다.
    `uploaded`(올린 파일 · 붙여 넣은 글 — 앱이 만든 저장 초안이 아님)면 평가본 식별 · 예산 산수도 보고 그 재료를 키에 넣는다(2.10.0 T8).
    """
    upload = upload_checks(procurement_id, proposal_text, context) if uploaded else None
    try:
        parsed = rfp_parser.load_generated(procurement_id)
        set_hash = parsed.requirement_set_hash
    except Exception:  # noqa: BLE001 — 파싱 결과가 없으면 run_audit 가 제대로 된 오류를 낸다
        set_hash = None

    run_id = run_key(
        procurement_id,
        proposal_text,
        requirement_set_hash=set_hash,
        mode=mode,
        use_llm=use_llm,
        context=context,
        extra=upload_key(upload) if upload else "",
    )
    existing = _existing_run(run_id, procurement_id, context)
    if existing is not None:
        return existing

    run = run_audit(
        procurement_id,
        proposal_text,
        use_llm=use_llm,
        source_document=source_document,
        context=context,
        mode=mode,
        upload=upload,
    )
    run.id = run_id
    saved = save_run(run, context=context)
    prune_runs(procurement_id, context=context)
    return saved


def _existing_run(run_id: str, procurement_id: str, context: "AnalysisContext | None") -> AuditRun | None:
    """같은 키의 결과가 이미 있으면 읽어 온다. 읽지 못하면 없는 것으로 본다(다시 돌린다)."""
    path = run_path(run_id, context, procurement_id)
    if not path.exists():
        return None
    try:
        return AuditRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
