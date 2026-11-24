"""Critical Condition 탐지·저장 서비스.

입력: 파싱된 항목(Requirement 전체 유형) + 공고 원문 필드 + (선택) 참가자격 판정 결과
출력: CriticalConditionReport — BLOCKER / ACTION / CHECK / INFO 와 GO 게이트

원칙 (CLAUDE.md 4-D, 11, 25)
- 규칙만 쓴다 (LLM·네트워크 없음). 같은 입력이면 같은 결과.
- 규칙이 확신하지 못하면 CHECK. 시스템은 절대 CLEARED를 만들지 않는다 — 사람의 기록만 CLEARED가 된다.
- 조건 id는 (유형, 요구사항의 stable_id → REQ 번호 → 원문 앞부분)으로 만든 안정 키다. 재탐지해도
  같은 조건은 같은 id라 담당자의 해결 기록이 유지된다.
- 미해결 BLOCKER가 있으면 gate.can_go=False.
- 저장된 보고서에는 탐지 시점의 요구사항 집합 해시를 함께 적고, 읽을 때 지금 파일과 대조해
  stale 을 내려보낸다. stale 이라고 조건을 감추지는 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.critical_condition import (
    CONDITION_TYPE_LABEL,
    ConditionCounts,
    ConditionFreshness,
    ConditionGate,
    ConditionIdBasis,
    ConditionStatus,
    ConditionType,
    ConditionUpdateRequest,
    CriticalCondition,
    CriticalConditionReport,
)
from app.schemas.eligibility import EligibilityReport
from app.schemas.requirement import Requirement, RfpParseResult
from app.schemas.organization import AnalysisContext
from app.services import analysis_store, item_classifier, performance_match_service
from app.services.finding_resolution_service import fnv1a32

CONDITION_DIR = DATA_ROOT / "public" / "conditions"


class ConditionReportNotFoundError(LookupError):
    """아직 탐지한 적이 없는 공고."""


class ConditionNotFoundError(LookupError):
    """보고서에 없는 condition id."""


class ConditionNoteRequiredError(ValueError):
    """참가 차단(BLOCKER)으로 탐지된 조건을 메모 없이 풀려 했다 — 안전장치(28차 · DTL-11)."""

    MESSAGE = "참가 차단 조건을 풀려면 무엇을 확인했는지 메모를 적어야 합니다."


# --------------------------------------------------------------------------
# 1) 탐지 규칙 — 실제 제안요청서·입찰공고문에서 관찰한 표현
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rule:
    condition_type: ConditionType
    pattern: re.Pattern[str]
    status: ConditionStatus
    severity: str
    # 이 표현이 함께 있으면 확신이 떨어져 CHECK로 낮춘다.
    uncertain: re.Pattern[str] | None = None


_UNCERTAIN_GENERIC = re.compile(r"필요\s*시|해당\s*시|경우에\s*한하여|권장|가급적|선택\s*사항|희망\s*(?:업체|자)")
#: 업종 · 면허 규칙만 — 「허가·인가·면허·등록·신고 등을 요하거나 자격요건을 갖추어야 할 경우에는…」 같은 조건부 형식 문구는 업종 코드를
#: 정하지 않는다 — 참가 차단이 아니라 확인 항목(43차 M17 · E2E-07 · 저장된 분석 업종 차단 5건 중 4건이 이 문구였다).
_UNCERTAIN_LICENSE = re.compile(_UNCERTAIN_GENERIC.pattern + r"|요하거나|요하는\s*경우|갖추어야\s*할\s*경우|하여야\s*할\s*경우")

RULES: tuple[_Rule, ...] = (
    _Rule(
        "briefing_attendance",
        # 「설명회」만 보면 「현장설명」·「현장방문」을 놓친다 — 실측에서 1순위 조건
        # 「다. 현장설명에 참석하고 … 입찰등록을 필한 업체」가 통째로 새어 나갔다.
        re.compile(
            r"(?:설명회|현장\s*설명|현장\s*방문).{0,40}(?:필수|반드시|참석|필참|의무)"
            r"|(?:필수|반드시|의무|필참).{0,40}(?:설명회|현장\s*설명|현장\s*방문)"
            r"|미참석.{0,30}(?:제한|불가|없)"
        ),
        "BLOCKER",
        "high",
        re.compile(r"참석.{0,10}(?:권장|바람|자유|선택)|불참.{0,20}불이익.{0,10}없"),
    ),
    _Rule("pre_registration", re.compile(r"사전\s*등록|사전\s*신청|사전\s*접수"), "ACTION", "high"),
    _Rule(
        "region_restriction",
        re.compile(r"지역\s*제한|소재지.{0,20}(?:둔|위치|소재).{0,20}(?:업체|자|기업)|본점.{0,20}소재|(?:광주|전남|전라남도|서울|경기|부산|대구|인천|대전|울산|세종|강원|충북|충남|전북|경북|경남|제주).{0,15}(?:소재|본점|사업장).{0,20}(?:업체|자|기업|한함|만)"),
        "BLOCKER",
        "high",
        re.compile(r"제한\s*없|전국|가점|우대"),
    ),
    _Rule(
        "industry_license",
        re.compile(r"(?:업종|면허|업태).{0,30}(?:등록|보유|신고).{0,20}(?:자|업체|기업)|소프트웨어\s*사업자|정보통신공사업|학원\s*(?:등록|설립)|직업\s*능력\s*개발\s*훈련\s*시설|평생\s*교육\s*시설"),
        "BLOCKER",
        "high",
        _UNCERTAIN_LICENSE,
    ),
    _Rule("direct_production", re.compile(r"직접\s*생산\s*(?:확인|증명)"), "BLOCKER", "high"),
    _Rule("sme_certificate", re.compile(r"중소기업\s*확인서|소기업.{0,10}확인서|소상공인\s*확인서"), "ACTION", "medium"),
    _Rule(
        "performance_record",
        re.compile(r"(?:유사|동종|동일).{0,10}(?:용역|사업|과업)?\s*(?:수행)?\s*실적|실적.{0,20}(?:이상|보유|증명)|계약\s*금액.{0,20}이상"),
        "CHECK",
        "medium",
    ),
    _Rule(
        # 「인력 … 명」의 `명` 하나만 보고 걸면 "실적증**명**"·"완료확인증**명**"에 걸린다.
        # 실제로 데모 공고 REQ-021「제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명…」이
        # 「인력 요건」으로도 잡혀, 같은 항목이 인력·실적 두 조건으로 중복됐다.
        # 인력 «수»를 요구하는 문장에는 반드시 숫자가 앞에 온다 — 숫자+단위를 요구한다.
        "staffing",
        re.compile(r"(?:투입|배치|보유)\s*인력.{0,30}\d+\s*(?:명|인)|(?:경력|자격증).{0,20}(?:이상|보유).{0,20}(?:인력|기술자|강사|책임자)|(?:PM|사업\s*책임자|총괄\s*책임자).{0,30}(?:경력|자격)"),
        "CHECK",
        "medium",
    ),
    _Rule(
        "joint_venture",
        re.compile(r"공동\s*수급|공동\s*이행|공동\s*계약|컨소시엄"),
        "INFO",
        "low",
    ),
    _Rule("subcontract", re.compile(r"하도급|재위탁|하청"), "INFO", "low"),
    _Rule("bid_bond", re.compile(r"입찰\s*보증금|계약\s*보증금|보증금.{0,20}(?:납부|납입|제출)"), "ACTION", "medium"),
    _Rule(
        "onsite_submission",
        re.compile(r"방문\s*제출|직접\s*제출|우편\s*제출|(?:제출\s*처|제출\s*장소).{0,40}(?:실|과|팀|호|층)|지참\s*(?:하여|해서)?\s*(?:방문|제출)"),
        "ACTION",
        "high",
    ),
    _Rule("copies", re.compile(r"(?<![가-힣\d])\d+\s*부(?:씩|를|와|,|\s|$|\))|원본\s*\d+\s*부|사본\s*\d+\s*부"), "ACTION", "medium"),
    _Rule("file_format", re.compile(r"파일\s*형식|PDF\s*(?:파일|형식|로)|HWP\s*(?:파일|형식|로)|USB|CD"), "ACTION", "medium"),
    _Rule(
        "separate_price_tech",
        re.compile(r"(?:기술|가격)\s*(?:제안서|입찰서).{0,30}(?:분리|별도|각각)|가격\s*(?:제안서|입찰서).{0,20}(?:밀봉|봉인)"),
        "INFO",
        "medium",
    ),
    _Rule("presentation", re.compile(r"(?:제안|기술)\s*발표|시연|프레젠테이션|(?<![A-Za-z])PT(?![A-Za-z])"), "ACTION", "medium"),
    _Rule("security_pledge", re.compile(r"보안\s*서약|비밀\s*유지\s*(?:서약|각서|계약)|보안\s*각서|청렴\s*(?:서약|계약)"), "ACTION", "medium"),
    _Rule(
        "separate_procedure",
        re.compile(r"별도\s*(?:절차|신청|등록|심사|승인)|사전\s*(?:심사|적격|승인)|PQ\s*심사|적격\s*심사\s*(?:서류|신청)"),
        "ACTION",
        "medium",
    ),
    _Rule("attendance_certificate", re.compile(r"참석\s*확인서|참석\s*증명"), "ACTION", "high"),
    _Rule(
        "mandatory_form",
        re.compile(r"(?:지정|소정|별첨|붙임)\s*(?:서식|양식).{0,30}(?:작성|사용|제출)|서식.{0,20}(?:반드시|의무|따라)"),
        "ACTION",
        "medium",
    ),
)


def condition_id(
    condition_type: str,
    requirement_id: str | None,
    source_text: str | None,
    *,
    stable_id: str | None = None,
) -> str:
    """재탐지해도 같은 조건은 같은 id (담당자 해결 기록 유지용).

    닻(anchor)은 stable_id → REQ 번호 → 원문 앞부분 순이다.

    REQ 번호를 닻으로 쓰면 요구사항을 다시 뽑을 때 무너진다. REQ-nnn 은 문서 등장 순서
    일련번호라 항목 하나가 중간에 끼면 뒤 번호가 전부 밀리는데, 그러면 같은 조건이 다른
    id 를 갖고 사람이 CLEARED 로 표시한 기록은 옛 id 에 남는다 — 실측 g2b-R26BK01707959-000
    의 「현장설명에 참석하고 … 입찰등록을 필한 업체」(REQ-032)가 그런 자리에 있다.
    그래서 내용에서 나오는 stable_id 를 먼저 쓴다.

    stable_id 가 없는 옛 요구사항 파일은 지금처럼 REQ 번호로 떨어진다. 어느 쪽으로
    떨어졌는지는 CriticalCondition.id_basis 에 남긴다.
    """
    anchor = stable_id or requirement_id or re.sub(r"\s+", "", source_text or "")[:80]
    return f"CC-{fnv1a32(f'{condition_type}:{anchor}')}"


def _id_basis(requirement_id: str | None, stable_id: str | None) -> ConditionIdBasis:
    if stable_id:
        return "stable_id"
    return "requirement_id" if requirement_id else "source_text"


def _shorten(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


#: 확신도를 낮추는 표현(「필요시」 등)을 찾을 범위 — 규칙이 걸린 자리 앞뒤 글자 수.
#
# 예전에는 `content + source_text` **전문**에서 찾았다. 파싱된 요구사항 한 건의
# source_text 가 1만 자를 넘는 일이 흔한데(요구사항 정의서 표 하나가 통째로 들어온다),
# 그러면 전혀 상관없는 자리의 「필요시」 한 마디가 수천 자 떨어진 BLOCKER 를 CHECK 로
# 끌어내린다. 실측: 「소프트웨어사업자」가 787자 위치에서 걸렸는데 5,776자 위치의
# 「필요시」 때문에 업종·면허 BLOCKER 가 CHECK 로 강등됐다.
#
# 200자면 같은 문장·바로 옆 문장은 들어오고 먼 조항은 들어오지 않는다.
_UNCERTAIN_WINDOW_CHARS = 200


#: 「대기업 및 중견기업 소프트웨어 사업자는 본 입찰에 참여할 수 없으며」 — 업종 요건이 아니라 대기업 참여 제한이다(2.1.6 · 11-01
#: 사법연수원 공고에서 중소기업인 회사에 업종·면허 BLOCKER 로 떴다). 대기업 제한 조항은 참가자격 판정(확인서 유효면 통과)이 본다.
#: 사이 글 — 괄호 묶음(「(매출 1.5조 이상)」처럼 마침표가 든)은 통째로 건너뛴다.
_GAP = r"(?:\([^)\n]{0,30}\)|[^.\n])"
#: 「…소프트웨어 사업자는/의 … 참여할 수 없/제한」만 — 「중소 소프트웨어사업자만 참여 가능하며 …」(진짜 요건)는 가리지 않는다(독립 검토).
_LARGE_FIRM_EXCLUSION_RE = re.compile(
    r"(?:대기업|중견기업)" + _GAP + r"{0,40}소프트웨어\s*사업자(?:는|은|의|가)"
    r"(?:(?!가능)[^.,\n]){0,30}(?:참여|참가)[^.,\n]{0,10}(?:할\s*수\s*없|불가|제한)"
)
#: 「중소 소프트웨어사업자의 사업 참여 지원에 관한 지침(과학기술정보통신부 고시)」 같은 **행정 지침 · 고시** 이름 — 이름 속 낱말은
#: 요건이 아니다. 「…법 · 법률 · 령 · 규정」 이름은 가리지 않는다(「「정보통신공사업법」에 의한 공사업 등록」이 사라졌다 · 독립 검토).
_GUIDELINE_TITLE_RE = re.compile(
    r"[「｢“][^」｣”\n]{0,80}(?:지침|고시|기준)(?:\s*\([^)\n]{0,30}\))?[」｣”]"
    r"|중소\s*소프트웨어\s*사업자의?\s*사업\s*참여\s*지원"
)


def _match_text(rule: _Rule, text: str) -> str:
    """규칙을 대 볼 글 — 업종·면허는 대기업 참여 제한 구절 · 행정 지침 이름을 가린다(같은 글의 등록 요건은 그대로 걸린다)."""
    if rule.condition_type == "industry_license":
        return _GUIDELINE_TITLE_RE.sub(" ", _LARGE_FIRM_EXCLUSION_RE.sub(" ", text))
    return text


def _uncertain_window(text: str, rule: _Rule) -> str:
    """규칙이 걸린 자리 주변만 잘라 돌려준다. 못 찾으면 빈 문자열 — 확신을 낮추지 않는다."""
    text = _match_text(rule, text)
    found = rule.pattern.search(text)
    if found is None:
        return ""
    start = max(0, found.start() - _UNCERTAIN_WINDOW_CHARS)
    end = min(len(text), found.end() + _UNCERTAIN_WINDOW_CHARS)
    return text[start:end]


def _from_requirement(req: Requirement, rule: _Rule) -> CriticalCondition:
    text = f"{req.content}\n{req.source_text}"
    status: ConditionStatus = rule.status
    if rule.uncertain is not None and rule.uncertain.search(_uncertain_window(text, rule)):
        status = "CHECK"
    elif rule.status == "BLOCKER" and _UNCERTAIN_GENERIC.search(req.content):
        status = "CHECK"
    stable_id = getattr(req, "stable_id", None)
    new_id = condition_id(rule.condition_type, req.requirement_id, req.source_text, stable_id=stable_id)
    # 옛 방식(stable_id 무시)으로 계산한 id. 사람이 그 id 로 남긴 override 를 찾기 위한 이행 경로다.
    legacy_id = condition_id(rule.condition_type, req.requirement_id, req.source_text)
    return CriticalCondition(
        id=new_id,
        id_basis=_id_basis(req.requirement_id, stable_id),
        legacy_ids=[legacy_id] if legacy_id != new_id else [],
        procurement_id=req.procurement_id,
        condition_type=rule.condition_type,
        title=CONDITION_TYPE_LABEL[rule.condition_type],
        content=_shorten(req.content),
        severity=rule.severity,  # type: ignore[arg-type]
        status=status,
        detected_status=status,
        due_at=req.due_at or item_classifier.due_at_of("SCHEDULE", req.content, req.source_text),
        action_required=status in ("BLOCKER", "ACTION", "CHECK"),
        requirement_id=req.requirement_id,
        source_page=req.page,
        source_text=req.source_text,
        extraction_method="RULE",
    )


#: 「무엇을 언제 제출」 항목에서는 건너뛰는 규칙.
#
# 제출물 목록("제안서에는 투입인력표를 포함한다")은 **인력을 몇 명 보유해야 하는가**를
# 말하지 않는다. 그런데 문장에 「인력」이 있어 인력 요건으로 잡히고, 같은 항목이
# 조건 두 개·체크리스트 두 줄이 된다. 담당자는 「같은 걸 두 번 하라고?」로 읽는다.
#
# 실적(performance_record)은 제출 항목에서도 «증빙을 준비해야 한다»는 실제 할 일이라
# 여기 넣지 않는다.
_SKIP_ON_SUBMISSION = frozenset({"staffing"})


def detect_from_requirements(requirements: list[Requirement]) -> list[CriticalCondition]:
    found: dict[str, CriticalCondition] = {}
    for req in requirements:
        text = f"{req.content}\n{req.source_text}"
        for rule in RULES:
            if req.item_type == "SUBMISSION" and rule.condition_type in _SKIP_ON_SUBMISSION:
                continue
            if not rule.pattern.search(_match_text(rule, text)):
                continue
            condition = _from_requirement(req, rule)
            found.setdefault(condition.id, condition)
    return list(found.values())


def detect_from_eligibility(procurement_id: str, report: EligibilityReport | None) -> list[CriticalCondition]:
    """참가자격 규칙 FAIL은 BLOCKER, 마감 경과는 BLOCKER. 공고 필드가 근거다."""
    if report is None:
        return []
    conditions: list[CriticalCondition] = []
    for result in report.results:
        if result.status != "FAIL":
            continue
        kind: ConditionType = "deadline_passed" if "DEADLINE" in result.rule_id else "eligibility_fail"
        conditions.append(
            CriticalCondition(
                id=condition_id(kind, None, result.rule_id),
                procurement_id=procurement_id,
                condition_type=kind,
                title=f"{CONDITION_TYPE_LABEL[kind]} · {result.label}",
                content=_shorten(result.reason),
                severity="high",
                status="BLOCKER",
                detected_status="BLOCKER",
                action_required=True,
                requirement_id=result.requirement_id,
                source_field=result.source,
                # 담당자가 「미충족」으로 확인한 조항(HUMAN)을 AI 추출로 적지 않는다 (20차 §4-C).
                extraction_method=result.method,
            )
        )
    return conditions


# --------------------------------------------------------------------------
# 2) 저장 (사람의 상태 변경은 조건 id 기준으로 남기고, 재탐지 결과에 덧입힌다)
# --------------------------------------------------------------------------


def report_path(procurement_id: str, context: AnalysisContext | None = None) -> Path:
    safe = storage.safe_id(procurement_id, what='공고 id')
    return analysis_store.resolve_path(context, safe, public_path=CONDITION_DIR / f"{safe}.conditions.json", file_name="conditions.json")


def _load_store(procurement_id: str, context: AnalysisContext | None = None) -> dict[str, Any]:
    payload = storage.read_json(report_path(procurement_id, context), default=None)
    if not isinstance(payload, dict):
        return {"procurement_id": procurement_id, "overrides": {}, "report": None}
    analysis_store.assert_owner(payload, context)
    payload.setdefault("overrides", {})
    payload.setdefault("report", None)
    return payload


def _find_override(condition: CriticalCondition, overrides: dict[str, Any]) -> dict[str, Any] | None:
    """이 조건에 대한 사람의 기록. 지금 id 로 먼저 찾고, 없으면 옛 id 로도 찾는다.

    id 계산 방식을 REQ 번호에서 stable_id 로 바꾼 순간, 옛 id 로만 찾으면 담당자가
    CLEARED 로 표시해 둔 기록이 통째로 사라진다. 사람이 한 일을 잃는 것이 이 변경에서
    가장 나쁜 결과라 두 키를 모두 조회한다.
    """
    for key in (condition.id, *condition.legacy_ids):
        override = overrides.get(key)
        if isinstance(override, dict):
            return override
    return None


def _migrate_override_keys(overrides: dict[str, Any], conditions: list[CriticalCondition]) -> bool:
    """옛 id 에 남은 기록을 지금 id 에도 복사한다. 바뀐 것이 있으면 True.

    옛 항목은 지우지 않는다 — 지웠다가 id 규칙이 또 바뀌면 되돌릴 길이 없다.
    조회는 항상 id 로 하므로 남아 있어도 해가 없다.
    """
    changed = False
    for condition in conditions:
        if condition.id in overrides:
            continue
        for legacy in condition.legacy_ids:
            legacy_override = overrides.get(legacy)
            if isinstance(legacy_override, dict):
                overrides[condition.id] = dict(legacy_override)
                changed = True
                break
    return changed


def _apply_overrides(conditions: list[CriticalCondition], overrides: dict[str, Any]) -> None:
    for condition in conditions:
        override = _find_override(condition, overrides)
        if override is None:
            continue
        status = override.get("status")
        if status in ("BLOCKER", "ACTION", "CHECK", "CLEARED", "INFO"):
            condition.status = status
        condition.resolved_by = override.get("reviewer")
        condition.resolution_note = override.get("note")
        if override.get("owner"):
            condition.owner = override.get("owner")
        raw_at = override.get("updated_at")
        if isinstance(raw_at, str):
            try:
                condition.resolved_at = datetime.fromisoformat(raw_at)
            except ValueError:
                condition.resolved_at = None
        if condition.status == "CLEARED":
            condition.action_required = False
        condition.extraction_method = "HUMAN" if status else condition.extraction_method


def counts_of(conditions: list[CriticalCondition]) -> ConditionCounts:
    def count(status: str) -> int:
        return sum(1 for c in conditions if c.status == status)

    return ConditionCounts(
        total=len(conditions),
        blocker=count("BLOCKER"),
        action=count("ACTION"),
        check=count("CHECK"),
        cleared=count("CLEARED"),
        info=count("INFO"),
    )


def gate_of(conditions: list[CriticalCondition], *, requirements_read: bool = True) -> ConditionGate:
    blockers = [c for c in conditions if c.status == "BLOCKER"]
    if blockers:
        titles = ", ".join(c.title for c in blockers[:3])
        more = f" 외 {len(blockers) - 3}건" if len(blockers) > 3 else ""
        return ConditionGate(
            can_go=False,
            reason=f"참가를 막는 조건 {len(blockers)}건이 남아 있습니다 — {titles}{more}. 담당자가 확인해 「해결됨」으로 처리하기 전에는 「참여」 결정을 저장할 수 없습니다.",
            blocker_ids=[c.id for c in blockers],
        )
    checks = sum(1 for c in conditions if c.status == "CHECK")
    if checks:
        # 이 문장은 화면에 그대로 나간다. enum 원문(BLOCKER·CHECK)을 쓰면 담당자가 영어를 읽게 된다.
        return ConditionGate(
            can_go=True,
            reason=f"참가를 막는 조건은 없습니다. 확인이 필요한 조건 {checks}건은 사람이 원문을 봐야 합니다.",
        )
    if not requirements_read:
        # 안 읽은 0은 「없음」이 아니라 「아직 모름」(43차 N8 — 제안요청서를 안 읽었는데 「미해결 조건이 없습니다」라 했다)
        return ConditionGate(can_go=True, reason="아직 모름 — 제안요청서를 아직 읽지 않아 조건을 다 찾지 못했습니다. 정리표를 만든 뒤 다시 봅니다.")
    return ConditionGate(can_go=True, reason="확인된 참가 차단 조건이 없습니다.")


# --------------------------------------------------------------------------
# 2-1) 신선도 — 이 보고서가 «지금 요구사항 집합» 기준인가
# --------------------------------------------------------------------------


def current_requirement_set_hash(procurement_id: str) -> str | None:
    """지금 저장된 요구사항 파일의 집합 해시. 읽을 수 없으면 None(= 모른다, 최신이 아니다)."""
    # 늦은 import — 파서는 이 모듈을 참조하지 않지만, 조건 서비스가 파싱 경로 전체를
    # 끌고 들어오지 않도록 호출 시점에만 가져온다.
    from app.services import rfp_parser

    try:
        path = rfp_parser.generated_path(procurement_id)
    except Exception:  # noqa: BLE001 — fixture·실제 공고 형식이 아닌 id 는 요구사항 파일이 없다
        return None
    payload = storage.read_json(path, default=None)
    if not isinstance(payload, dict):
        return None
    value = payload.get("requirement_set_hash")
    if isinstance(value, str) and value:
        return value
    # schema_version 3 이전 파일에는 집합 해시가 없다. 읽기 시 마이그레이션이 채우는 값과
    # 같은 값을 여기서 계산해 둔다 (파일은 고쳐 쓰지 않는다).
    try:
        rfp_parser.migrate_payload(payload)
    except Exception:  # noqa: BLE001 — 계산에 실패하면 «모른다»로 둔다. 지어내지 않는다
        return None
    value = payload.get("requirement_set_hash")
    return value if isinstance(value, str) and value else None


def _freshness_of(saved: str | None, current: str | None) -> tuple[ConditionFreshness, bool, str | None]:
    """(신선도, stale, 사유). 대조할 수 없으면 unknown 이며 stale=True 다.

    한쪽 해시가 없다고 «최신»이라고 답하면, 사람은 옛 판정을 지금 판정으로 읽는다.
    모르는 것은 모른다고 한다.
    """
    if saved and current:
        if saved == current:
            return "current", False, None
        return (
            "stale",
            True,
            f"저장 당시 요구사항 집합({saved})과 지금 집합({current})이 다릅니다. 조건을 다시 탐지해야 합니다.",
        )
    if saved and not current:
        return "unknown", True, "지금 요구사항 집합을 읽을 수 없어 최신 여부를 확인할 수 없습니다."
    if current and not saved:
        return "unknown", True, "요구사항 집합 해시가 기록되기 전에 저장된 보고서라 최신 여부를 확인할 수 없습니다."
    return "unknown", True, "요구사항 집합 해시가 없어 최신 여부를 확인할 수 없습니다."


def _stamp_freshness(report: CriticalConditionReport) -> CriticalConditionReport:
    report.current_requirement_set_hash = current_requirement_set_hash(report.procurement_id)
    if not report.requirements_available and not report.requirement_set_hash and not report.current_requirement_set_hash:
        # 10-31 최종 점검 — 요구사항을 한 번도 뽑지 않았으면 「다시 뽑은 뒤 안 찾음」이 아니다(낡을 기준이 없다).
        # 화면은 「아직 모름 — 제안요청서를 아직 읽지 않았습니다」 한 줄만 보인다.
        report.freshness, report.stale, report.stale_reason = "unknown", False, None
        return report
    if not report.requirements_available and report.current_requirement_set_hash:
        # 11-01 — 제안요청서를 읽기 전에 만든 자리표시인데 그 뒤 요구사항을 뽑았다. 「모름」이면 결정 저장이
        # 「확인된 차단 0」으로 지나가므로 낡음으로 둔다(`decision_service._refuse_stale_conditions` 가 참여를 막음).
        report.freshness, report.stale = "stale", True
        report.stale_reason = "제안요청서를 읽기 전에 찾은 조건입니다 — 조건을 다시 찾아야 합니다."
        return report
    report.freshness, report.stale, report.stale_reason = _freshness_of(
        report.requirement_set_hash, report.current_requirement_set_hash
    )
    return report


def build_report(
    procurement_id: str,
    *,
    parse_result: RfpParseResult | None,
    eligibility: EligibilityReport | None,
    notice_available: bool,
    as_of: datetime | None = None,
    context: AnalysisContext | None = None,
) -> CriticalConditionReport:
    conditions = detect_from_requirements(parse_result.requirements if parse_result else [])
    conditions.extend(detect_from_eligibility(procurement_id, eligibility))
    attach_ledger_matches(conditions, as_of=as_of, context=context)
    _apply_overrides(conditions, _load_store(procurement_id, context)["overrides"])
    order = {"BLOCKER": 0, "ACTION": 1, "CHECK": 2, "INFO": 3, "CLEARED": 4}
    conditions.sort(key=lambda c: (order[c.status], c.requirement_id or "~", c.condition_type))
    report = CriticalConditionReport(
        procurement_id=procurement_id,
        detected_at=as_of or storage.utc_now(),  # 공고 변경 시각과 견준다 (runStamp)
        method="RULE",
        notice_available=notice_available,
        requirements_available=parse_result is not None,
        eligibility_used=eligibility is not None,
        counts=counts_of(conditions),
        gate=gate_of(conditions, requirements_read=parse_result is not None),
        conditions=conditions,
        # 탐지에 쓴 요구사항 «집합»의 신원. 나중에 이 보고서가 낡았는지 대조하는 재료다.
        requirement_set_hash=getattr(parse_result, "requirement_set_hash", None),
        requirement_set_id=getattr(parse_result, "requirement_set_id", None),
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
    )
    return _stamp_freshness(report)


def attach_ledger_matches(
    conditions: list[CriticalCondition], *, as_of: datetime | None = None, context: AnalysisContext | None = None
) -> int:
    """실적 조건에 **그 조직의** 실적 원장 대조 결과를 붙인다. 원장이 없거나 public_demo 면 아무것도 하지 않는다 (지어내지 않는다)."""
    ledger = performance_match_service.load_ledger_for(context)
    if ledger is None:
        return 0
    attached = 0
    for condition in conditions:
        if condition.condition_type != "performance_record":
            continue
        text = " ".join(filter(None, [condition.content, condition.source_text]))
        condition.ledger_match = performance_match_service.build_report(
            text, ledger=ledger, as_of=as_of.date() if as_of else None
        )
        attached += 1
    return attached


def save_report(report: CriticalConditionReport, *, context: AnalysisContext | None = None) -> CriticalConditionReport:
    with storage.locked(report_path(report.procurement_id, context)):
        return _save_report_locked(report, context)


def _save_report_locked(report: CriticalConditionReport, context: AnalysisContext | None) -> CriticalConditionReport:
    store = _load_store(report.procurement_id, context)
    # id 규칙을 바꾸기 전에 남긴 기록을 지금 id 로도 찾을 수 있게 옮겨 적는다 (옛 키는 남긴다).
    _migrate_override_keys(store["overrides"], report.conditions)
    store["report"] = report.model_dump(mode="json")
    analysis_store.stamp(store, context)
    storage.stamp(store)
    storage.write_json_atomic(report_path(report.procurement_id, context), store)
    return report


def load_report(procurement_id: str, context: AnalysisContext | None = None) -> CriticalConditionReport:
    store = _load_store(procurement_id, context)
    if not store.get("report"):
        raise ConditionReportNotFoundError(procurement_id)
    report = CriticalConditionReport.model_validate(store["report"])
    # 저장 이후 바뀐 사람의 기록을 다시 덧입힌다.
    _apply_overrides(report.conditions, store["overrides"])
    report.counts = counts_of(report.conditions)
    # 다시 셀 때도 「안 읽음」을 넘긴다 — 빠뜨리면 두 번째로 열 때부터 「아직 모름」이 「없음」으로 돌아갔다 (P1-02)
    report.gate = gate_of(report.conditions, requirements_read=report.requirements_available)
    # 저장 당시의 요구사항 집합과 지금 파일을 대조한다. 낡았어도 조건을 감추지 않는다 —
    # 감추면 BLOCKER 가 화면에서 사라져 지금보다 나빠진다. 판단은 사람이 한다.
    _stamp_freshness(report)
    if context is not None:
        report.organization_id = context.organization_id
        report.evidence_scope = context.evidence_scope
    return report


def _resolve_condition_key(stored_conditions: list[Any], condition_id_value: str) -> str | None:
    """요청받은 id 를 저장된 보고서의 지금 id 로 옮긴다. 모르는 id 면 None."""
    for raw in stored_conditions:
        if not isinstance(raw, dict):
            continue
        current = str(raw.get("id") or "")
        if condition_id_value == current:
            return current
        legacy = raw.get("legacy_ids")
        if isinstance(legacy, list) and condition_id_value in legacy:
            return current
    return None


def update_condition(
    procurement_id: str,
    condition_id_value: str,
    request: ConditionUpdateRequest,
    *,
    context: AnalysisContext | None = None,
    recorded_by: str | None = None,
) -> CriticalConditionReport:
    """담당자의 상태 변경. 보고서에 있는 조건만 바꿀 수 있다."""
    with storage.locked(report_path(procurement_id, context)):
        return _update_condition_locked(procurement_id, condition_id_value, request, context, recorded_by)


def _update_condition_locked(
    procurement_id: str,
    condition_id_value: str,
    request: ConditionUpdateRequest,
    context: AnalysisContext | None,
    recorded_by: str | None = None,
) -> CriticalConditionReport:
    store = _load_store(procurement_id, context)
    if not store.get("report"):
        raise ConditionReportNotFoundError(procurement_id)
    # 지금 id 로 찾고, 없으면 옛 id 로도 찾아 지금 id 에 기록한다. 화면이 들고 있던
    # 옛 id 로 «해결 처리»를 눌렀을 때 404 를 돌려주면 사람이 한 일이 저장되지 않는다.
    target = _resolve_condition_key(store["report"].get("conditions", []), condition_id_value)
    if target is None:
        raise ConditionNotFoundError(condition_id_value)
    # 안전장치(판정 규칙 변경 아님): 게이트는 BLOCKER 만 세므로, 탐지가 BLOCKER 인 조건을
    # 메모 없이 CHECK · CLEARED 로 바꾸면 근거 없이 「참여」가 풀린다 (DTL-11).
    raw = next((c for c in store["report"].get("conditions", []) if isinstance(c, dict) and c.get("id") == target), {})
    detected = raw.get("detected_status") or raw.get("status")
    if detected == "BLOCKER" and request.status != "BLOCKER" and not (request.note or "").strip():
        raise ConditionNoteRequiredError(ConditionNoteRequiredError.MESSAGE)
    store["overrides"][target] = {
        "status": request.status,
        "reviewer": request.reviewer,
        "note": request.note,
        "owner": request.owner,
        # 본문의 `reviewer` 는 클라이언트의 주장이고, 이것은 서명된 신원에서 온 사실이다 (S12).
        "recorded_by": recorded_by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.stamp(store)
    storage.write_json_atomic(report_path(procurement_id, context), store)
    return load_report(procurement_id, context)


def gate_for(procurement_id: str, context: AnalysisContext | None = None) -> ConditionGate | None:
    """결정 저장 시 참조하는 게이트. 탐지한 적이 없으면 None — 요구사항 없이 만든 자리표시도 아직 탐지 전이다(목록 배지 「차단 0」 아님)."""
    try:
        report = load_report(procurement_id, context)
    except ConditionReportNotFoundError:
        return None
    if not report.requirements_available and report.current_requirement_set_hash:
        return None
    return report.gate
