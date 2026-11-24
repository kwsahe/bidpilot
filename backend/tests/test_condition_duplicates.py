"""같은 항목이 두 조건으로 잡히지 않고, 체크리스트 제목이 겹치지 않는다 (ISSUE-015 · TASK-016).

## 무엇이 문제였나

데모 공고 REQ-021 「제안서에는 사업수행계획, **투입인력표**, 유사사업 **실적증명**, …을 모두
포함해야 한다」가 「인력 요건」과 「실적·금액 요건」 **두 조건**으로 나왔다.

인력 규칙이 `(?:투입|배치|보유)\\s*인력.{0,30}(?:이상|명)` 이라, 「투입인력표 … 실적증**명**」의
마지막 글자 하나에 걸렸다. 그 결과 체크리스트에도 「투입 인력 자격·경력 증빙 준비」와
「유사 수행실적 증빙 준비」가 각각 두 번씩 생겼다.

담당자 입장에서 같은 할 일이 두 줄이면 체크리스트 전체를 의심하게 된다.

## 무엇을 고정하는가

1. 인력 요건은 인력 **수**를 말하는 문장(숫자+명/인)에서만 잡힌다 — 「증명」에 걸리지 않는다.
2. 「무엇을 언제 제출」 항목에서는 인력 규칙을 보지 않는다. 제출물 목록은 보유 인력 요건이 아니다.
3. 체크리스트 제목이 겹치면 어느 요구사항에서 나왔는지 붙여 구분한다(지우지 않는다 —
   요구사항이 둘이면 준비할 증빙도 둘이다).
"""

from __future__ import annotations

import collections

from app.schemas.requirement import Requirement
from app.services import critical_condition_service as ccs
from app.services import rfp_parser
from app.services.action_service import _STEPS_BY_TYPE, _TITLE_BY_TYPE

DEMO = "synthetic-rfp-0001"


def _req(requirement_id: str, content: str, item_type: str = "REQUIREMENT") -> Requirement:
    return Requirement(
        id=f"{DEMO}-{requirement_id}",
        title=content[:20],
        requirement_id=requirement_id,
        procurement_id=DEMO,
        category="일반",
        requirement_type="mandatory",
        content=content,
        source_text=content,
        item_type=item_type,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# 인력 규칙
# ---------------------------------------------------------------------------


def test_증명이라는_낱말에_인력_요건이_걸리지_않는다() -> None:
    req = _req("REQ-021", "제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명을 모두 포함해야 한다.")
    kinds = {c.condition_type for c in ccs.detect_from_requirements([req])}
    assert "staffing" not in kinds


def test_인력_수를_말하는_문장은_그대로_잡는다() -> None:
    """고치면서 진짜 인력 요건까지 놓치면 안 된다."""
    for text in (
        "투입 인력은 총 5명 이상으로 구성한다.",
        "배치인력 3인 이상을 상시 유지해야 한다.",
        "사업 책임자는 관련 분야 경력 7년 이상이어야 한다.",
    ):
        kinds = {c.condition_type for c in ccs.detect_from_requirements([_req("REQ-100", text)])}
        assert "staffing" in kinds, text


def test_제출_항목에서는_인력_규칙을_보지_않는다() -> None:
    text = "제안서 제출 시 투입인력표 10명분을 첨부한다."
    as_requirement = {c.condition_type for c in ccs.detect_from_requirements([_req("REQ-200", text)])}
    as_submission = {c.condition_type for c in ccs.detect_from_requirements([_req("REQ-200", text, "SUBMISSION")])}
    assert "staffing" in as_requirement
    assert "staffing" not in as_submission


# ---------------------------------------------------------------------------
# 데모 공고 실측 — 완료 조건 그대로
# ---------------------------------------------------------------------------


def test_데모_공고에서_REQ021은_인력_요건이_아니다() -> None:
    result = rfp_parser.load_generated(DEMO)
    assert result is not None, "데모 공고 파싱 결과가 없다"
    conditions = ccs.detect_from_requirements(result.requirements)
    req021 = [c.condition_type for c in conditions if c.requirement_id == "REQ-021"]
    assert "staffing" not in req021


def test_데모_공고_체크리스트에_같은_제목이_없다() -> None:
    result = rfp_parser.load_generated(DEMO)
    assert result is not None
    conditions = ccs.detect_from_requirements(result.requirements)

    # seed_from_report 와 같은 규칙으로 제목을 만든다 (저장하지 않는다 — 공용 데모는 읽기만).
    titles: list[str] = []
    seen: set[str] = set()
    for condition in conditions:
        if condition.status not in ("BLOCKER", "ACTION", "CHECK"):
            continue
        steps = _STEPS_BY_TYPE.get(condition.condition_type)
        candidates = list(steps) if steps else [_TITLE_BY_TYPE.get(condition.condition_type, f"{condition.title} 확인")]
        for title in candidates:
            if title in seen and condition.requirement_id:
                title = f"{title} — {condition.requirement_id}"
            seen.add(title)
            titles.append(title)

    duplicates = [title for title, count in collections.Counter(titles).items() if count > 1]
    assert duplicates == [], f"체크리스트 제목이 겹친다: {duplicates}"
