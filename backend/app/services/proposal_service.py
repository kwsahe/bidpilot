"""제안서 핵심 섹션 생성 서비스.

CLAUDE.md 4-G / 11의 원칙을 코드로 옮긴다.

1. **규칙이 먼저, LLM은 다듬기만** — 키가 없거나 호출이 실패해도 완전한 결과를 낸다.
2. **없는 사실을 만들지 않는다** — 문장의 수치·주장은 요구사항 원문 또는 채택된
   Evidence 원문에서만 나온다. LLM이 만든 문장은 수치를 원문과 대조해 검증하고,
   원문에 없는 수치가 섞이면 규칙 템플릿으로 되돌리고 `확인 필요`로 표시한다.
3. **커버리지를 지어내지 않는다** — 근거도 없고 그대로 옮길 의무 표현도 없는
   요구사항은 문장을 만들지 않는다. 그 빈칸을 AI Auditor가 잡아내는 것이 데모의 핵심이다.

Evidence 입력은 팀원이 만드는 실제 매칭기로 교체된다. 이 모듈은
`generate_section(..., evidence_links=[...])` 파라미터로만 소비하므로 교체는 한 줄이다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.proposal import (
    EvidenceCandidate,
    GeneratedSectionDraft,
    ProposalSection,
    ProposalSentence,
)
from app.schemas.organization import AnalysisContext, EvidenceScopeInfo
from app.schemas.requirement import Requirement
from app.services import analysis_store, evidence_service, llm_client, rfp_parser
from app.services.text_match import extract_numbers

logger = logging.getLogger(__name__)

PROPOSALS_DIR = DATA_ROOT / "public" / "proposals"
DEMO_SCENARIO_FILE = DATA_ROOT / "synthetic_company" / "demo_cosmos_scenario.json"

DEFAULT_SECTION_TITLE = "사업수행계획 (핵심 섹션)"
EXCERPT_LIMIT = 110


class ProposalNotGeneratedError(LookupError):
    """아직 제안서 초안이 생성되지 않음."""


# --------------------------------------------------------------------------
# 1) Evidence 입력 (팀원의 실제 매칭기로 교체 가능)
# --------------------------------------------------------------------------


def load_evidence_links(procurement_id: str) -> list[EvidenceCandidate]:
    """요구사항 ↔ 회사자료 연결을 읽어온다.

    현재는 합성 데모 시나리오(`demo_cosmos_scenario.json`)만 근거를 갖고 있다.
    실제 공고는 아직 회사자료 매칭 결과가 없으므로 빈 목록을 반환한다(지어내지 않는다).
    """
    if not DEMO_SCENARIO_FILE.exists():
        return []

    payload = json.loads(DEMO_SCENARIO_FILE.read_text(encoding="utf-8"))
    if payload.get("procurement_id") != procurement_id:
        return []

    documents = {
        str(doc["id"]): doc
        for doc in payload.get("evidence_documents", [])
        if isinstance(doc, dict) and doc.get("id")
    }

    links: list[EvidenceCandidate] = []
    for link in payload.get("evidence_links", []):
        if not isinstance(link, dict):
            continue
        document = documents.get(str(link.get("evidence_id")))
        if document is None:
            continue  # 원문이 없는 연결은 근거로 쓸 수 없다
        links.append(
            EvidenceCandidate(
                requirement_id=str(link["requirement_id"]),
                evidence_id=str(link["evidence_id"]),
                document_name=str(document.get("document_name") or "회사자료"),
                source_text=str(document["source_text"]),
                page=document.get("page"),
                similarity_score=link.get("similarity_score"),
                selected=bool(link.get("selected")),
            )
        )
    return links


def match_evidence_links(
    requirements: list[Requirement], *, context: AnalysisContext
) -> tuple[list[EvidenceCandidate], EvidenceScopeInfo | None]:
    """컨텍스트의 근거 범위(조직 internal / 합성 public_demo)에서만 요구사항별 근거를 찾는다.

    인덱스가 없거나 임베딩 키가 없으면 빈 목록을 돌려준다. 지어내지 않는다 —
    근거가 없으면 제안서 문장도 만들지 않고 '확인 필요'로 남는다 (CLAUDE.md 11).
    """
    result = evidence_service.match_requirements(requirements, context=context)
    if not result.available:
        logger.info("Evidence 매칭을 건너뜁니다: %s", result.reason)
        return [], result.scope_info
    return [
        EvidenceCandidate(
            requirement_id=match.requirement_id,
            evidence_id=match.evidence_id,
            document_name=match.document_name,
            source_text=match.source_text,
            page=match.page,
            similarity_score=match.similarity_score,
            selected=match.selected,
        )
        for match in result.matches
    ], result.scope_info


def _demo_scope_info(context: AnalysisContext, links: list[EvidenceCandidate]) -> EvidenceScopeInfo:
    """합성 데모 시나리오의 손질된 연결(public_demo)에 붙는 출처 범위."""
    return EvidenceScopeInfo(
        organization_id=context.organization_id,
        evidence_scope="public_demo",
        used_document_count=len({l.document_name for l in links}),
        used_chunk_count=len({l.evidence_id for l in links}),
        synthetic_evidence_used=bool(links),
        real_evidence_used=False,
        note="가상 예시 공고의 근거 연결",
    )


def _resolve_links(
    procurement_id: str, requirements: list[Requirement], context: AnalysisContext
) -> tuple[list[EvidenceCandidate], EvidenceScopeInfo | None]:
    """근거 연결을 컨텍스트 범위로 고른다. 합성 시나리오 연결은 public_demo 에서만 쓴다."""
    if context.evidence_scope == "public_demo":
        demo = load_evidence_links(procurement_id)
        if demo:
            return demo, _demo_scope_info(context, demo)
    links, info = match_evidence_links(requirements, context=context)
    # 45차 H5 — 사람이 채택한 원장 후보만 「채택」(초안 근거)으로. 채택 전 후보는 그대로 「확인 필요」 문장이 된다.
    from app.services import evidence_adoption_service

    return evidence_adoption_service.apply(procurement_id, context, links), info


def legacy_scope_info(sentences: list[ProposalSentence]) -> dict:
    """레거시(공개 위치) 결과의 출처 범위를 인용된 evidence_id 로 계산한다 (EV-=합성, CD-=회사자료)."""
    ids = [s.evidence_id for s in sentences if s.evidence_id]
    return EvidenceScopeInfo(
        organization_id=None,
        evidence_scope="public_demo",
        used_document_count=0,
        used_chunk_count=len(set(ids)),
        synthetic_evidence_used=any(i.startswith("EV-") for i in ids),
        real_evidence_used=any(i.startswith("CD-") for i in ids),
        note="레거시 공개 결과 — 현재 조직의 내부 분석 결과가 아직 없어 표시",
    ).model_dump(mode="json")


# --------------------------------------------------------------------------
# 2) 규칙 기반 문장 템플릿
# --------------------------------------------------------------------------

# 그대로 약속으로 옮길 수 있는 의무·금지 표현. 없으면 문장을 만들지 않는다.
OBLIGATION_RE = re.compile(
    r"[가-힣]야\s*(한다|하며|하고|함)|할\s*수\s*없|해서는\s*안|않아야|하지\s*않는다"
)

# 문장 어미를 제안서 어투로 바꾼다. 내용을 바꾸지 않고 어미만 손댄다.
_ENDING_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"해야\s*한다$"), "하겠습니다"),
    (re.compile(r"하여야\s*한다$"), "하겠습니다"),
    (re.compile(r"([가-힣])[아어]야\s*한다$"), r"\1겠습니다"),
    (re.compile(r"([가-힣])여야\s*한다$"), r"\1여야 합니다"),
    (re.compile(r"할\s*수\s*없다$"), "할 수 없습니다"),
    (re.compile(r"해서는\s*안\s*된다$"), "해서는 안 됩니다"),
    (re.compile(r"않는다$"), "않겠습니다"),
    (re.compile(r"된다$"), "됩니다"),
    (re.compile(r"한다$"), "합니다"),
]


def to_commitment(content: str) -> str | None:
    """요구사항 원문의 어미만 제안서 어투로 바꾼다. 바꿀 수 없으면 None."""
    body = " ".join(content.split()).rstrip()
    body = body[:-1].rstrip() if body.endswith(".") else body
    for pattern, replacement in _ENDING_RULES:
        if pattern.search(body):
            return pattern.sub(replacement, body) + "."
    return None


def _excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """근거 원문 발췌. 수치가 잘리지 않도록 공백 경계에서만 자른다."""
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    head = clean[:limit]
    if " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip() + "…"


def _page_label(page: int | None) -> str:
    return f" p.{page}" if page else ""


#: 규칙 초안 문장 끝의 출처 꼬리 — 「(근거: …)」 · 「(후보 근거: …)」 · 「(RFP p.3 요구사항 준수)」 · 「(제안요청서 p.17 요구사항)」.
#: 내보내기(`proposal_export._display_text`)와 이관 스크립트(`scripts/migrate_requirement_sets.py`)가 이 하나를 쓴다(32차 R31-23 —
#: 스크립트 쪽은 새 꼴 「제안요청서 …」를 못 걷었다).
TRAILING_NOTE_RE = re.compile(
    r"\s*\((?:근거|후보 근거|(?:RFP|제안요청서)(?: p\.\d+)? 요구사항(?: 준수)?)[^()]*(?:\([^()]*\)[^()]*)*\)\s*$"
)


def _evidence_sentence(requirement: Requirement, evidence: EvidenceCandidate) -> str:
    citation = (
        f"(근거: 「{evidence.document_name}」{_page_label(evidence.page)} "
        f"\"{_excerpt(evidence.source_text)}\")"
    )
    commitment = to_commitment(requirement.content)
    if commitment is None:
        return f"[{requirement.title}] 요구사항 \"{requirement.content}\" 을 이행합니다. {citation}"
    return f"{commitment} {citation}"


def _rfp_sentence(requirement: Requirement, commitment: str) -> str:
    # 「17쪽」으로 쓰면 숫자 검사(단위 「쪽」)가 그 수를 근거 없는 숫자로 읽는다 — 쪽 번호는 「p.17」 꼴로(31차 §3-D).
    return f"{commitment} (제안요청서{f' p.{requirement.page}' if requirement.page else ''} 요구사항)"


def _review_sentence(
    requirement: Requirement, candidates: list[EvidenceCandidate]
) -> str:
    # 43차 M19 · E2E-05 — 꼬리 글은 실제 사유(회사 근거 연결을 꺼 두었음 · 원장 후보를 아직 안 고름)
    why = "원장 후보 실적을 아직 고르지 않아" if candidates else "회사 근거 연결을 꺼 두어(원장 후보에서 고르세요)"
    base = f"[{requirement.title}] \"{requirement.content}\" — {why} 충족 여부를 확정할 수 없습니다. 확인 필요."
    if not candidates:
        return base
    best = max(candidates, key=lambda c: c.similarity_score or 0.0)
    # 「유사도 0.42」는 0~1 소수 금지 위반이었다 — 후보 문서와 쪽만(32차)
    return f"{base} (후보 근거: 「{best.document_name}」{_page_label(best.page)} — 미채택)"


# --------------------------------------------------------------------------
# 3) 규칙 기반 초안 생성
# --------------------------------------------------------------------------


#: 본문이 아니라 「참고」인 요구사항(43차 Q22 · E2E-05 · E2E-13) — 평가 배점 · 서식 · 확약서 · 대외비 · 점수 부여 · 첨부.
_REFERENCE_RE = re.compile(r"서식|확약서|대외비|배점|평가\s*점수|최저\s*점수|점수를?\s*(?:각각\s*)?부여|첨부\.\s*관련|평가\s*(?:항목|기준|방법)")


#: 회사가 무엇을 했다 · 가졌다고 단정하는 꼴(43차 M18 · E2E-04).
_COMPANY_CLAIM_RE = re.compile(r"(?:샘플에듀|당사|우리\s*회사|본사)(?:는|가|의)?[^.]{0,60}?(?:보유|운영해\s*온|수행한|수행해\s*온|개발한|구축한|경험을\s*바탕|실적을\s*보유)")


def is_reference_requirement(requirement: Requirement) -> bool:
    """제안서 본문에 쓸 과업 · 요건이 아니라 참고(평가 · 서식)인가 — 초안 · 점검 분모가 같은 함수를 쓴다."""
    category = requirement.category or ""
    # 분류 「평가」만으로는 빼지 않는다(「실적 증명서 제출 건만 평가」처럼 제출 요건이 평가 분류로 온다)
    return bool(re.search(r"서식|참고", category) or _REFERENCE_RE.search(f"{requirement.title} {requirement.content}"))


class _Draft:
    """문장 1개의 생성 근거. LLM 다듬기 단계에서도 그대로 유지된다."""

    def __init__(
        self,
        requirement: Requirement,
        text: str,
        grounding_type: str,
        evidence: EvidenceCandidate | None,
        needs_review: bool,
        candidates: list[EvidenceCandidate],
    ) -> None:
        self.requirement = requirement
        self.text = text
        self.grounding_type = grounding_type
        self.evidence = evidence
        self.needs_review = needs_review
        #: AI 가 문장을 바꿨으면 바꾸기 전 근거 유형(44차 M5) — 그때 `grounding_type` 은 AI_SUGGESTION 이 된다.
        self.refined_from: str | None = None
        self.candidates = candidates


def _group_links(
    links: list[EvidenceCandidate],
) -> dict[str, list[EvidenceCandidate]]:
    grouped: dict[str, list[EvidenceCandidate]] = {}
    for link in links:
        grouped.setdefault(link.requirement_id, []).append(link)
    return grouped


def build_drafts(
    requirements: list[Requirement], links: list[EvidenceCandidate]
) -> list[_Draft]:
    """요구사항 순서대로 규칙 기반 문장을 만든다. 만들 수 없으면 건너뛴다."""
    grouped = _group_links(links)
    drafts: list[_Draft] = []

    for requirement in requirements:
        if requirement.requirement_type != "mandatory":
            continue
        if is_reference_requirement(requirement):
            continue  # 43차 Q22 — 평가 배점 · 서식 · 참고는 본문 밖 「참고」(반영 숫자 분모도 본문 기준)

        candidates = grouped.get(requirement.requirement_id, [])
        selected = [c for c in candidates if c.selected]
        # 모호한 자격조건(status=check)은 근거가 있어도 자동 충족 판정하지 않는다.
        ambiguous = requirement.status == "check"

        if selected and not ambiguous:
            best = max(selected, key=lambda c: c.similarity_score or 0.0)
            drafts.append(
                _Draft(
                    requirement=requirement,
                    text=_evidence_sentence(requirement, best),
                    grounding_type="COMPANY_EVIDENCE_GROUNDED",
                    evidence=best,
                    needs_review=False,
                    candidates=candidates,
                )
            )
            continue

        if ambiguous or candidates:
            # 채택 근거 없음 / 모호조건 → 충족을 단정하지 않고 사람에게 넘긴다.
            drafts.append(
                _Draft(
                    requirement=requirement,
                    text=_review_sentence(requirement, candidates),
                    grounding_type="RFP_GROUNDED",
                    evidence=None,
                    needs_review=True,
                    candidates=candidates,
                )
            )
            continue

        commitment = to_commitment(requirement.content)
        if commitment is not None and OBLIGATION_RE.search(requirement.content):
            # 근거 없이도 그대로 지킬 수 있는 의무 문장은 RFP 근거로 복창한다.
            drafts.append(
                _Draft(
                    requirement=requirement,
                    text=_rfp_sentence(requirement, commitment),
                    grounding_type="RFP_GROUNDED",
                    evidence=None,
                    needs_review=False,
                    candidates=[],
                )
            )
            continue

        # 43차 M19 · Q22 — 근거도 의무 표현도 없는 **과업**은 건너뛰지 않고 「확인 필요」 자리표시 줄로 남긴다
        # (Claude · Codex 전체 초안에도 과업이 가게). 점검은 자리표시 줄을 「반영」으로 세지 않는다.
        drafts.append(
            _Draft(
                requirement=requirement,
                text=f"[{requirement.title}] \"{requirement.content}\" — 대응 문장을 아직 쓰지 않았습니다. 확인 필요.",
                grounding_type="RFP_GROUNDED",
                evidence=None,
                needs_review=True,
                candidates=[],
            )
        )

    return drafts


# --------------------------------------------------------------------------
# 4) LLM 다듬기 (선택) + 수치 검증
# --------------------------------------------------------------------------

_LLM_SYSTEM = (
    "당신은 공공입찰 제안서 작성을 돕는 한국어 어시스턴트입니다. "
    "주어진 RFP 요구사항과 회사 근거자료 원문만 사용해 제안서 문장을 다듬습니다. "
    "원문에 없는 수치, 실적, 인증, 회사 정보를 절대 만들지 마십시오. "
    "요구사항마다 정중한 제안서체 한국어 문장 1개만 작성하고, "
    "'확인 필요'로 표시된 항목은 충족을 단정하지 말고 확인이 필요하다고 쓰십시오."
)


def _allowed_numbers(draft: _Draft) -> set[tuple[float, str]]:
    """이 문장이 쓸 수 있는 수치 (요구사항 원문 + 인용 가능한 근거 원문)."""
    sources = [draft.requirement.content, draft.requirement.source_text]
    if draft.evidence is not None:
        sources.append(draft.evidence.source_text)
    else:
        sources.extend(candidate.source_text for candidate in draft.candidates)
    allowed: set[tuple[float, str]] = set()
    for source in sources:
        allowed.update((token.value, token.unit) for token in extract_numbers(source))
    return allowed


def has_unsupported_number(text: str, draft: _Draft) -> bool:
    """생성 문장의 수치가 원문에 없으면 True (환각 차단)."""
    allowed = _allowed_numbers(draft)
    return any(
        (token.value, token.unit) not in allowed for token in extract_numbers(text)
    )


#: 규칙 초안 끝의 「(후보 근거: 「문서」 p.n — 미채택)」 — 채택하지 않은 회사 문서 이름이라 AI 에 보내지 않는다 (28차 §3-D).
_CANDIDATE_TAIL_RE = re.compile(r"\s*\(후보 근거: .*?— 미채택\)$")


def _llm_payload(drafts: list[_Draft]) -> str:
    """AI 에 보내는 본문 — 요구사항 · 규칙 초안 · 확인 필요 · **채택된 근거 문장만**(`draft.evidence` — 근거 연결이 유사도 기준으로 채택 · 합성은 시나리오 값).

    채택하지 않은 후보 근거는 문장도 문서 이름도 보내지 않는다(규칙 초안 끝의 후보 꼬리를 뗀다 · 28차 담당자 결정).
    """
    items = []
    for draft in drafts:
        rule_draft = draft.text if draft.evidence is not None else _CANDIDATE_TAIL_RE.sub("", draft.text)
        item: dict[str, object] = {
            "requirement_id": draft.requirement.requirement_id,
            "requirement_title": draft.requirement.title,
            "requirement_text": draft.requirement.content,
            "rule_draft": rule_draft,
            "needs_review": draft.needs_review,
        }
        if draft.evidence is not None:
            item["evidence_document"] = draft.evidence.document_name
            item["evidence_text"] = draft.evidence.source_text
        items.append(item)
    return json.dumps({"items": items}, ensure_ascii=False, indent=2)


#: 사업계획서 작성 페이지의 입찰 제안서 한 벌 시간 상한(초) — 화면의 「최대 4분 30초」와 같다 · 전역 잠금을 오래 쥐지 않게 (29차 R28-06).
#: 중계 대기(nginx · 화면 중계 300초)보다 짧게(44차 M2 — 같으면 서버는 저장했는데 화면은 연결이 끊겨 실패로 보였다).
PLAN_WRITER_TIME_LIMIT = 270.0


def refine_with_llm(drafts: list[_Draft], *, plan_writer: bool = False, errors: list[str] | None = None,
                    writer: str = "claude", deadline: float | None = None) -> bool:
    """LLM으로 문장을 자연스럽게 다듬는다. 실패하면 규칙 초안을 그대로 둔다.

    `plan_writer` — 사업계획서 작성 페이지의 「Claude · Codex로 제안서 초안 쓰기」만 참(28차 §3-D · 29차 §3-A `writer`).
    보내는 것은 `_llm_payload()` 그대로 — 요구사항 · 규칙 초안 · **승인된 회사자료 문단 중 유사도 기준으로 고른 근거 문장만**
    (`draft.evidence` · 합성은 시나리오 값). `deadline` — 한 벌 마감 시각(`time.monotonic()` 기준 · R28-06).

    근거 유형·Evidence·요구사항 연결은 규칙이 정한 값을 유지한다(LLM이 바꾸지 못한다).
    `needs_review`는 올리는 방향으로만 반영한다.

    Returns: 한 문장이라도 LLM 문장으로 교체되었으면 True.
    """
    if not drafts:
        return False
    if plan_writer:
        ready, reason = llm_client.plan_writer_ready(writer)
        if not ready:
            if errors is not None:
                errors.append(reason or llm_client.PLAN_WRITER_OFF_REASON)
            return False
    elif not llm_client.completion_configured():
        return False
    left = None if deadline is None else deadline - time.monotonic()
    if left is not None and left < llm_client.MIN_ATTEMPT_SECONDS:
        if errors is not None:
            errors.append("시간 상한(5분)을 넘어 규칙 문장으로 둡니다")
        return False

    try:
        result = llm_client.complete_structured(
            system=_LLM_SYSTEM,
            user=(
                "다음 요구사항 목록에 대해 제안서 문장을 하나씩 작성하세요. "
                "rule_draft는 참고용 초안입니다. 원문에 없는 수치·사실을 추가하지 마세요.\n\n"
                + _llm_payload(drafts)
            ),
            schema=GeneratedSectionDraft,
            temperature=0.0,
            purpose="proposal_full:plan_writer" if plan_writer else "unspecified",
            plan_writer=plan_writer,
            writer=writer,
            timeout=left,
        )
    except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
        logger.warning("제안서 LLM 다듬기 실패, 규칙 초안 유지: %s", exc)  # 화면 문장 아님 — 서버 로그
        if errors is not None:
            errors.append(str(exc))
        return False

    generated = {item.requirement_id: item for item in result.sentences}
    used_llm = False
    for draft in drafts:
        item = generated.get(draft.requirement.requirement_id)
        if item is None:
            continue
        text = " ".join(item.text.split())
        if not text:
            continue
        if has_unsupported_number(text, draft):
            # 원문에 없는 수치 → 규칙 템플릿으로 되돌리고 사람 확인으로 넘긴다.
            logger.warning(
                "LLM 문장에 원문에 없는 수치가 있어 규칙 템플릿으로 되돌립니다: %s",
                draft.requirement.requirement_id,
            )
            draft.needs_review = True
            continue
        draft.needs_review = draft.needs_review or item.needs_review
        if draft.evidence is None and _COMPANY_CLAIM_RE.search(text):
            # 43차 M18 · E2E-04 — 회사 근거 없이 「샘플에듀/당사가 …했다 · 보유」라고 단정하면 확인 필요로 내린다(숫자 없는 회사 단정)
            draft.needs_review = True
        if draft.needs_review and "확인" not in text:
            # 확인이 필요한 항목은 문장에서도 그렇게 읽혀야 한다.
            text = f"{text} 확인 필요."
        if text != " ".join(draft.text.split()) and draft.grounding_type != "AI_SUGGESTION":
            # 44차 M5 · E2E-04 — AI 가 바꾼 문장은 근거 문장 표지(공고문 · 회사 근거)를 그대로 달지 않는다: 「AI 다듬음 — 근거: 원 근거」
            draft.refined_from = draft.grounding_type
            draft.grounding_type = "AI_SUGGESTION"
        draft.text = text
        used_llm = True
    return used_llm


# --------------------------------------------------------------------------
# 5) 섹션 조립 / 저장 / 조회
# --------------------------------------------------------------------------


def _to_section(
    procurement_id: str,
    section_title: str,
    requirements: list[Requirement],
    drafts: list[_Draft],
    generation_method: str,
    *,
    context: AnalysisContext | None = None,
    scope_info: EvidenceScopeInfo | None = None,
    parsed: Any | None = None,
    previous: ProposalSection | None = None,
) -> ProposalSection:
    sentences = [
        ProposalSentence(
            id=f"PS-{index:02d}",
            text=draft.text,
            grounding_type=draft.grounding_type,  # type: ignore[arg-type]
            requirement_id=draft.requirement.requirement_id,
            stable_requirement_id=draft.requirement.stable_id,
            evidence_id=draft.evidence.evidence_id if draft.evidence else None,
            needs_review=draft.needs_review,
            refined_from=draft.refined_from,  # type: ignore[arg-type]
        )
        for index, draft in enumerate(drafts, start=1)
    ]

    # 45차 M6 — 분모는 초안이 문장을 만드는 필수(참고 · 평가 · 서식 뺌 · `build_drafts` 와 같은 함수). 저장 필수 99건을 분모로 써
    # 「83 / 99」 · 정리표 「필수 73」이 갈렸다.
    mandatory = [r for r in requirements if r.requirement_type == "mandatory" and not is_reference_requirement(r)]
    covered = {draft.requirement.requirement_id for draft in drafts}
    return ProposalSection(
        id=f"PROP-{procurement_id}",
        title=section_title,
        sentences=sentences,
        procurement_id=procurement_id,
        generated_at=storage.utc_now(),  # 공고 변경 시각과 견준다 (runStamp)
        generation_method=generation_method,  # type: ignore[arg-type]
        mandatory_total=len(mandatory),
        requirements_with_sentence=len(covered),
        requirements_without_sentence=[
            r.requirement_id for r in mandatory if r.requirement_id not in covered
        ],
        evidence_grounded_count=sum(
            1 for s in sentences if s.grounding_type == "COMPANY_EVIDENCE_GROUNDED"
        ),
        rfp_grounded_count=sum(
            1 for s in sentences if s.grounding_type == "RFP_GROUNDED"
        ),
        needs_review_count=sum(1 for s in sentences if s.needs_review),
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
        evidence_summary=scope_info.model_dump(mode="json") if scope_info else None,
        # --- 어느 요구사항 집합을 보고 만들었는가 -----------------------------
        #
        # 이것이 없으면 옛 초안을 최신 요구사항과 곧바로 견주게 된다. 실측으로
        # 필수 32건 기준 초안이 55건 집합과 비교돼 26건이 한꺼번에 미반영 HIGH 가 됐다.
        requirement_set_id=getattr(parsed, "requirement_set_id", None),
        requirement_set_hash=getattr(parsed, "requirement_set_hash", None),
        proposal_version=(previous.proposal_version + 1) if previous else 1,
        source_proposal_version=previous.proposal_version if previous else None,
        # REQ 번호가 아니라 «안정 ID» 로 남긴다 — 번호는 재추출에서 밀린다.
        covered_requirement_ids=sorted(
            {
                draft.requirement.stable_id
                for draft in drafts
                if draft.requirement.stable_id
            }
        ),
        author=generation_method,
        edited_by_human=False,
        proposal_hash=section_hash(sentences),
    )


def section_hash(sentences: list[ProposalSentence]) -> str:
    """초안 본문의 해시. 감사 결과가 이 초안을 본 것인지 대조하는 값."""
    joined = "\n".join(s.text for s in sentences)
    normalized = re.sub(r"\s+", " ", joined).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]



def store_evidence_links(
    procurement_id: str,
    links: list[EvidenceCandidate],
    scope_info: EvidenceScopeInfo | None,
    *,
    context: AnalysisContext,
) -> None:
    """근거 연결 결과를 남긴다.

    예전에는 이 결과가 제안서 문장 안에만 녹아 들어가고 **어디에도 저장되지 않았다**.
    그래서 백엔드가 실제로 회사자료를 검색해 근거를 찾아 놓고도(로컬 확인: 실공고
    proposal.json 의 evidence_summary 가 used_document_count=3 · real_evidence_used=true),
    화면은 보여줄 데이터가 없어 「Evidence Mapping 미실행」이라고 말했다.

    제안서 스키마는 건드리지 않는다 — 파일 하나를 옆에 두는 편이 변경 폭이 작다.
    실패해도 제안서 생성 자체는 막지 않는다(best-effort).
    """
    try:
        payload = {
            "procurement_id": procurement_id,
            "links": [link.model_dump(mode="json") for link in links],
            "scope": scope_info.model_dump(mode="json") if scope_info is not None else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        }
        analysis_store.write_json(
            context,
            procurement_id,
            payload,
            public_path=PROPOSALS_DIR / f"{procurement_id}.evidence.json",
            file_name="evidence.json",
        )
    except Exception:  # noqa: BLE001 - 저장 실패가 제안서 생성을 막으면 안 된다
        pass


def load_evidence_result(procurement_id: str, *, context: AnalysisContext) -> dict | None:
    """저장해 둔 근거 연결 결과. 없으면 None (= 아직 실행하지 않았다)."""
    payload, _legacy = analysis_store.load_json(
        context,
        procurement_id,
        public_path=PROPOSALS_DIR / f"{procurement_id}.evidence.json",
        file_name="evidence.json",
    )
    return payload


def generate_section(
    procurement_id: str,
    *,
    section_title: str | None = None,
    evidence_links: list[EvidenceCandidate] | None = None,
    use_llm: bool = True,
    context: AnalysisContext | None = None,
) -> ProposalSection:
    """핵심 섹션 1개를 생성하고 저장한다. 하나의 분석은 하나의 회사(+근거 범위)에 고정된다.

    context 를 넘기지 않으면(레거시 테스트 진입점) 공개 합성 위치·범위를 쓴다 — 실제 회사를 고르지 않는다.
    evidence_links 를 직접 넘기면(explicit) 매칭기를 돌리지 않는다.
    """
    ctx = context or analysis_store.LEGACY_PUBLIC_CONTEXT
    parsed = rfp_parser.load_generated(procurement_id)
    scope_info: EvidenceScopeInfo | None = None
    if evidence_links is not None:
        links = evidence_links
    else:
        links, scope_info = _resolve_links(procurement_id, parsed.requirements, ctx)
    # 근거 연결 결과를 남긴다 — 화면이 「미실행」이라고 말하지 않도록.
    store_evidence_links(procurement_id, links, scope_info, context=ctx)

    drafts = build_drafts(parsed.requirements, links)
    used_llm = refine_with_llm(drafts) if use_llm else False

    # 이전 판을 읽어 판 번호를 이어 센다. **덮어쓰기 전에 읽는다** — 기존 초안은
    # 지우지 않고 버전 기록으로 보존한다(archive_section).
    previous: ProposalSection | None = None
    try:
        previous = load_section(procurement_id, ctx)
    except Exception:  # noqa: BLE001 — 첫 생성이면 없다
        previous = None

    section = _to_section(
        procurement_id=procurement_id,
        section_title=section_title or DEFAULT_SECTION_TITLE,
        requirements=parsed.requirements,
        drafts=drafts,
        generation_method="LLM" if used_llm else "RULE",
        context=ctx,
        scope_info=scope_info,
        parsed=parsed,
        previous=previous,
    )
    if previous is not None:
        archive_section(previous, context=ctx)
    return store_section(section, context=ctx)


def versions_dir(procurement_id: str, context: AnalysisContext | None = None) -> Path:
    """이전 판을 모아 두는 폴더. 새 판을 만들어도 옛 판을 지우지 않는다."""
    return proposal_path(procurement_id, context).parent / f"{procurement_id}.proposal.versions"


def archive_section(section: ProposalSection, *, context: AnalysisContext | None = None) -> Path | None:
    """이전 판을 버전 폴더에 보존한다. 이미 있으면 다시 쓰지 않는다(멱등).

    자동 덮어쓰기를 막는 장치다 — 사람이 고친 문장이 재생성으로 사라지면 안 된다.
    """
    if not section.procurement_id:
        return None
    folder = versions_dir(section.procurement_id, context)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"v{section.proposal_version:03d}.json"
    if target.exists():
        return target
    storage.write_json_atomic(target, section.model_dump(mode="json"))
    return target


def list_versions(procurement_id: str, context: AnalysisContext | None = None) -> list[ProposalSection]:
    """보존된 이전 판 목록 (오래된 것부터)."""
    folder = versions_dir(procurement_id, context)
    if not folder.is_dir():
        return []
    out: list[ProposalSection] = []
    for path in sorted(folder.glob("v*.json")):
        payload = storage.read_json(path)
        if isinstance(payload, dict):
            try:
                out.append(ProposalSection.model_validate(payload))
            except Exception:  # noqa: BLE001 — 깨진 판 하나가 목록 전체를 막지 않는다
                logger.warning("보존된 제안서 판을 읽지 못했습니다: %s", path)
    return out


def _check_procurement_id(procurement_id: str) -> None:
    """등록된 fixture ID와 실제 공고 ID 형태만 허용한다(경로 조작 차단)."""
    if not (
        rfp_parser.is_fixture(procurement_id) or rfp_parser.is_real_notice_id(procurement_id)
    ):
        raise rfp_parser.RfpFixtureNotFoundError(procurement_id)


def proposal_path(procurement_id: str, context: AnalysisContext | None = None) -> Path:
    """저장 경로. public_demo(또는 컨텍스트 없음)는 공개 위치, internal 은 조직 분석 폴더."""
    _check_procurement_id(procurement_id)
    return analysis_store.resolve_path(
        context, procurement_id, public_path=PROPOSALS_DIR / f"{procurement_id}.proposal.json", file_name="proposal.json"
    )


def store_section(section: ProposalSection, *, context: AnalysisContext | None = None) -> ProposalSection:
    _check_procurement_id(section.procurement_id)
    payload = section.model_dump(mode="json")
    analysis_store.write_json(
        context, section.procurement_id, payload,
        public_path=PROPOSALS_DIR / f"{section.procurement_id}.proposal.json", file_name="proposal.json",
    )
    return section


def load_section(procurement_id: str, context: AnalysisContext | None = None) -> ProposalSection:
    _check_procurement_id(procurement_id)
    payload, legacy = analysis_store.load_json(
        context, procurement_id, public_path=PROPOSALS_DIR / f"{procurement_id}.proposal.json", file_name="proposal.json"
    )
    if payload is None:
        raise ProposalNotGeneratedError(procurement_id)
    section = ProposalSection.model_validate(payload)
    if legacy:
        section.organization_id = None
        section.evidence_scope = "public_demo"
        section.legacy_result = True
        section.evidence_summary = legacy_scope_info(section.sentences)
    else:
        _flag_synthetic_in_internal(section)
    return section


#: 합성 회사자료 문단의 id 앞머리. 회사자료(실제)는 `CD-` 다.
SYNTHETIC_EVIDENCE_PREFIX = "EV-"

SYNTHETIC_MIX_NOTE = (
    "이 초안은 가상 예시 회사자료를 근거로 인용하고 있습니다. "
    "제출용으로 쓰지 말고 이 회사의 승인된 자료로 다시 생성하세요."
)


def _flag_synthetic_in_internal(section: ProposalSection) -> None:
    """실제 회사 결과에 합성 근거가 섞였으면 그렇다고 적는다 (ISSUE-018 · TASK-017).

    지금 생성 경로는 `internal` 범위에서 합성 연결을 읽지 않는다(`_resolve_links`).
    그런데 **그 규칙이 생기기 전에 저장된 초안**이 남아 있다. 실제 공고 + 주식회사 샘플에듀
    조합인데 문장의 근거가 전부 「(합성)」 문서인 파일이 실제로 있었다.

    저장된 파일을 고치지 않는다 — 기록이다. 읽을 때 사실을 덧붙일 뿐이다.
    화면은 이 표시를 보고 내려받기를 막고 「재생성 필요」로 잠근다.
    """
    if section.evidence_scope != "internal":
        return
    cited = [s.evidence_id for s in section.sentences if s.evidence_id]
    if not any(str(i).startswith(SYNTHETIC_EVIDENCE_PREFIX) for i in cited):
        return

    summary = dict(section.evidence_summary or {})
    summary.setdefault("organization_id", section.organization_id)
    summary.setdefault("evidence_scope", "internal")
    summary.setdefault("used_document_count", 0)
    summary.setdefault("used_chunk_count", len({i for i in cited}))
    summary["synthetic_evidence_used"] = True
    existing = str(summary.get("note") or "").strip()
    if SYNTHETIC_MIX_NOTE not in existing:
        summary["note"] = f"{existing} {SYNTHETIC_MIX_NOTE}".strip()
    section.evidence_summary = summary

# ---------------------------------------------------------------------------
# 제안서 전체 초안 (섹션 여러 개)
# ---------------------------------------------------------------------------

# 목차 순서와 각 섹션이 담을 요구사항 카테고리.
# rfp_extractor가 붙이는 카테고리 값을 그대로 쓴다 — 없는 목차를 만들지 않는다.
DOCUMENT_SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("1. 사업 이해 및 추진방향", ("사업개요",)),
    ("2. 과업 수행계획", ("과업내용",)),
    ("3. 추진 일정", ("일정",)),
    ("4. 투입 인력", ("인력",)),
    ("5. 보안 및 개인정보 보호", ("보안",)),
    ("6. 품질관리 및 사업관리", ("품질", "프로젝트관리", "프로젝트지원", "제약사항")),
    ("7. 제출서류 및 행정사항", ("제출서류",)),
    ("8. 참가자격 확인사항", ("입찰참가자격",)),
    ("9. 평가 대응", ("평가",)),
    ("10. 기타", ("기타",)),
]

DEFAULT_DOCUMENT_TITLE = "제안서 초안"


def _document_section_title(procurement_id: str) -> str:
    return f"{DEFAULT_DOCUMENT_TITLE} ({procurement_id})"


def adopted_evidence(procurement_id: str, context: AnalysisContext | None = None) -> dict[str, object]:
    """사업계획서 작성 페이지가 **보내기 전에** 보여 주는 수 — 「채택한 근거 문장 n개가 Claude 에 갑니다」 (28차 §3-D).

    AI 에 보낼 본문과 같은 계산이다(`build_drafts` 의 `draft.evidence` — 근거 연결이 채택(유사도 기준)했고 모호하지 않은 것만).
    """
    ctx = context or analysis_store.LEGACY_PUBLIC_CONTEXT
    parsed = rfp_parser.load_generated(procurement_id)
    links, _info = _resolve_links(procurement_id, parsed.requirements, ctx)
    drafts = build_drafts(parsed.requirements, links)
    return {
        "procurement_id": procurement_id,
        "adopted": sum(1 for d in drafts if d.evidence is not None),
        # 초안 · 점검 분모와 같은 셈(서식 · 참고 뺌) — 원시 필수 수가 /plan 에 따로 보였다 (UI c)
        "mandatory": sum(1 for r in parsed.requirements if r.requirement_type == "mandatory" and not is_reference_requirement(r)),
        "evidence_scope": ctx.evidence_scope,
    }


def generate_document(
    procurement_id: str,
    *,
    evidence_links: list[EvidenceCandidate] | None = None,
    use_llm: bool = True,
    context: AnalysisContext | None = None,
    plan_writer: bool = False,
    writer: str = "claude",
) -> "ProposalDocument":
    """요구사항 카테고리별로 섹션을 나눠 제안서 전체 초안을 만든다.

    `plan_writer` · `writer` — 사업계획서 작성 페이지의 단추(Claude · Codex). 한 벌 5분 상한 · 한 섹션도 AI 로 못 바꿨으면
    있던 AI 초안을 덮지 않는다 · 합성 데모 공고(Git 이 추적하는 공개 파일)에는 저장하지 않는다 (29차 R28-05~07).

    요구사항이 하나도 없는 카테고리는 섹션 자체를 만들지 않는다. 목차를 채우려고
    내용을 지어내지 않는다 (CLAUDE.md 11). 근거는 컨텍스트 범위에서만 찾는다.
    """
    from app.schemas.proposal_document import ProposalDocument

    ctx = context or analysis_store.LEGACY_PUBLIC_CONTEXT
    parsed = rfp_parser.load_generated(procurement_id)
    scope_info: EvidenceScopeInfo | None = None
    if evidence_links is not None:
        links = evidence_links
    else:
        links, scope_info = _resolve_links(procurement_id, parsed.requirements, ctx)

    by_category: dict[str, list[Requirement]] = {}
    for requirement in parsed.requirements:
        by_category.setdefault(requirement.category, []).append(requirement)

    assigned: set[str] = set()
    sections: list[ProposalSection] = []
    section_categories: dict[str, list[str]] = {}
    used_llm = False
    llm_errors: list[str] = []  # 사업계획서 작성(Claude · Codex) 경로의 실패 사유 — 화면에 한 줄로 (28차 검수 R1-01)
    deadline = time.monotonic() + PLAN_WRITER_TIME_LIMIT if plan_writer else None

    for title, categories in DOCUMENT_SECTIONS:
        picked: list[Requirement] = []
        present: list[str] = []
        for category in categories:
            items = by_category.get(category)
            if not items:
                continue
            picked.extend(items)
            present.append(category)
            assigned.add(category)
        if not picked:
            continue  # 요구사항이 없으면 섹션을 만들지 않는다

        drafts = build_drafts(picked, links)
        if not drafts:
            continue
        if use_llm and refine_with_llm(drafts, plan_writer=plan_writer, errors=llm_errors, writer=writer, deadline=deadline):
            used_llm = True
        sections.append(
            _to_section(
                procurement_id=procurement_id,
                section_title=title,
                requirements=picked,
                drafts=drafts,
                generation_method="RULE",
                context=ctx,
            )
        )
        section_categories[title] = present

    # 목차에 없는 카테고리가 생기면 마지막 섹션으로 몰아 넣는다 (요구사항을 잃지 않는다).
    leftovers = [
        requirement
        for category, items in by_category.items()
        if category not in assigned
        for requirement in items
    ]
    if leftovers:
        drafts = build_drafts(leftovers, links)
        if drafts:
            if use_llm and refine_with_llm(drafts, plan_writer=plan_writer, errors=llm_errors, writer=writer, deadline=deadline):
                used_llm = True
            title = "99. 분류되지 않은 요구사항"
            sections.append(
                _to_section(
                    procurement_id=procurement_id,
                    section_title=title,
                    requirements=leftovers,
                    drafts=drafts,
                    generation_method="RULE",
                    context=ctx,
                )
            )
            section_categories[title] = sorted(
                {r.category for r in leftovers}
            )

    covered_ids = {
        sentence.requirement_id
        for section in sections
        for sentence in section.sentences
        if sentence.requirement_id
    }
    mandatory = [r for r in parsed.requirements if r.requirement_type == "mandatory" and not is_reference_requirement(r)]  # 45차 M6

    document = ProposalDocument(
        id=f"PROPDOC-{procurement_id}",
        procurement_id=procurement_id,
        title=_document_section_title(procurement_id),
        sections=sections,
        generated_at=datetime.now(timezone.utc),
        generation_method="LLM" if used_llm else "RULE",
        mandatory_total=len(mandatory),
        requirements_with_sentence=len(covered_ids),
        requirements_without_sentence=[
            r.requirement_id for r in mandatory if r.requirement_id not in covered_ids
        ],
        evidence_grounded_count=sum(s.evidence_grounded_count for s in sections),
        rfp_grounded_count=sum(s.rfp_grounded_count for s in sections),
        needs_review_count=sum(s.needs_review_count for s in sections),
        section_categories=section_categories,
        organization_id=ctx.organization_id,
        evidence_scope=ctx.evidence_scope,
        evidence_summary=scope_info.model_dump(mode="json") if scope_info else None,
    )
    if not plan_writer:
        return store_document(document, context=ctx)
    note = (f"AI 다듬기 실패 {len(llm_errors)}건 — 그 섹션은 규칙 문장으로 둡니다 · 첫 사유: {llm_errors[0]}" if llm_errors
            else ("AI 가 바꾼 문장이 없습니다 — 규칙 문장 그대로입니다" if not used_llm else None))
    if not used_llm:
        # 한 섹션도 AI 로 바뀌지 않았다 — 실패 사유가 없어도 있던 AI 초안을 규칙 초안으로 덮지 않는다(28차 검수 R1-01 · 29차 R28-05).
        try:
            previous = load_document(procurement_id, context=ctx)
        except ProposalNotGeneratedError:
            previous = None
        if previous is not None and previous.generation_method == "LLM":
            previous.llm_note = f"새 AI 초안 없음 — 있던 AI 초안을 그대로 둡니다 · {note}"
            previous.kept_llm_draft = True
            return previous
    document.llm_note = note
    if not analysis_store.is_private(ctx):
        # 합성 데모 공고 — 결과가 Git 이 추적하는 공개 파일(`data/public/proposals/…`)에 가지 않게 이 화면에만 돌려준다 (29차 R28-07).
        demo = "가상 예시 공고라 공개 파일을 덮지 않도록 저장하지 않았습니다 — 이 화면에서만 보입니다"
        document.llm_note = f"{note} · {demo}" if note else demo
        document.stored = False  # 내려받기는 저장된 판을 준다 — 화면이 이 판의 내려받기를 숨긴다(30차 R29-03)
        return document
    return store_document(document, context=ctx)


def document_path(procurement_id: str, context: AnalysisContext | None = None) -> Path:
    rfp_parser.generated_path(procurement_id)  # id 형식 검증 재사용
    return analysis_store.resolve_path(
        context, procurement_id, public_path=PROPOSALS_DIR / f"{procurement_id}.document.json", file_name="proposal_document.json"
    )


def store_document(document: "ProposalDocument", *, context: AnalysisContext | None = None) -> "ProposalDocument":
    rfp_parser.generated_path(document.procurement_id)
    payload = document.model_dump(mode="json")
    analysis_store.write_json(
        context, document.procurement_id, payload,
        public_path=PROPOSALS_DIR / f"{document.procurement_id}.document.json", file_name="proposal_document.json",
    )
    return document


def load_document(procurement_id: str, context: AnalysisContext | None = None) -> "ProposalDocument":
    from app.schemas.proposal_document import ProposalDocument

    rfp_parser.generated_path(procurement_id)
    payload, legacy = analysis_store.load_json(
        context, procurement_id, public_path=PROPOSALS_DIR / f"{procurement_id}.document.json", file_name="proposal_document.json"
    )
    if payload is None:
        raise ProposalNotGeneratedError(procurement_id)
    document = ProposalDocument.model_validate(payload)
    if legacy:
        document.organization_id = None
        document.evidence_scope = "public_demo"
        document.legacy_result = True
        document.evidence_summary = legacy_scope_info([s for sec in document.sections for s in sec.sentences])
    return document
