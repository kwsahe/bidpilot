"""33차 §3-B — 사업 규모: 최대 사업비를 넘어도 「불가」가 아니라 「확인 필요」, 공동수급 판단은 하나로.

네트워크 0. 공고는 실제 나라장터 필드명(`cmmnSpldmdMethdNm` · `asignBdgtAmt`)만 쓴 인라인 값이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.services import eligibility_engine
from app.services import opportunity_priority as priority

KST = timezone(timedelta(hours=9))
AS_OF = datetime(2026, 8, 25, 9, 0, tzinfo=KST)
CEILING = 200_000_000


def raw(budget: str = "270000000", joint: str | None = "(없음)공동수급불허") -> dict[str, Any]:
    item: dict[str, Any] = {"bidNtceNo": "R26TEST00000001", "asignBdgtAmt": budget}
    if joint is not None:
        item["cmmnSpldmdMethdNm"] = joint
    return {"source": "g2b", "item": item}


def budget_rule(data: dict[str, Any], ceiling: int | None = CEILING):
    rules = eligibility_engine.evaluate_notice_fields(
        data, as_of=AS_OF, company=eligibility_engine.CompanyFacts(budget_ceiling_krw=ceiling)
    )
    return next(r for r in rules if r.rule_id == "ELIG-BUDGET")


def test_불허여도_불가가_아니라_확인_필요다() -> None:
    rule = budget_rule(raw())
    assert rule.status == "CHECK"
    assert rule.reason == (
        "사업비 2.7억원 — 회사가 정한 최대 사업비 2억원보다 크고, 다른 회사와 함께 참가할 수도 없습니다(공동수급 불허). "
        "법이 막는 것이 아니라 회사 기준입니다 — 혼자 맡을지 정하세요"
    )
    assert rule.check_side == "company"
    assert rule.unlock_condition is None  # 함께할 회사를 구해도 열리지 않는다 — 회사가 정할 일


def test_허용이면_파트너_열쇠_그대로() -> None:
    rule = budget_rule(raw(joint="(전자)공동이행"))
    assert rule.status == "CHECK"
    assert rule.unlock_condition == "공동수급 파트너 확보 시"
    assert "함께 참가(공동수급)할 수 있어" in rule.reason


def test_모르면_공고문에서_방식_확인() -> None:
    rule = budget_rule(raw(joint=None))
    assert rule.status == "CHECK"
    assert rule.check_side == "notice"
    assert "공고문에서 공동수급 방식을 확인" in rule.reason
    assert rule.unlock_condition is None


def test_최대_사업비_이하면_가능_사유는_사업비로_시작() -> None:
    rule = budget_rule(raw(budget="150000000"))
    assert rule.status == "PASS"
    # 목록 사유가 「사업 규모: 사업 규모 …」로 되풀이되지 않게 — 사유는 「사업비」로 시작한다
    assert rule.reason.startswith("사업비 ")
    assert not budget_rule(raw()).reason.startswith("사업 규모")


@pytest.mark.parametrize(
    ("joint", "expected"),
    [
        ("(없음)공동수급불허", False),
        ("(전자)공동이행", True),
        ("(수기)공동이행", True),
        ("(전자)공동이행 또는 분담이행", True),
        ("(수기)분담이행", True),  # 예전 「주의」 · 점수는 「공동이행」 낱말로 봐서 이것을 불허로 읽었다
        ("(전자)혼합방식", True),  # 공동이행 · 분담이행을 섞은 방식(마지막 검토 · R26BK01725538)
        (None, None),
    ],
)
def test_공동수급_판단은_하나다(joint: str | None, expected: bool | None) -> None:
    assert eligibility_engine.joint_allowed(raw(joint=joint)) is expected


def test_분담이행은_주의_점수_판정이_같은_말을_한다() -> None:
    data = raw(budget="630000000", joint="(수기)분담이행")
    joint = eligibility_engine.joint_allowed(data)
    line = priority.caution_line(
        budget=630_000_000, ceiling=CEILING, days_left=20, lead_days=4, joint_allowed=joint, out_of_scope=False
    )
    assert line == "규모 큼 — 다른 회사와 함께 입찰 권장"
    assert "공동수급 허용" in priority.scale_component(630_000_000, ceiling=CEILING, joint_allowed=joint).reason
    assert budget_rule(data).unlock_condition == "공동수급 파트너 확보 시"


def test_모르면_주의도_모른다고() -> None:
    line = priority.caution_line(
        budget=300_000_000, ceiling=CEILING, days_left=20, lead_days=4, joint_allowed=None, out_of_scope=False
    )
    assert line == "규모 큼 — 함께 입찰 가능한지 공고문 확인"


def test_점수는_규모_항목에서만_낮아진다() -> None:
    """불허 2.7억: 종합 판정은 확인 필요라 자격 점수가 0 으로 떨어지지 않고, 규모 점수만 낮다."""
    rules = eligibility_engine.evaluate_notice_fields(
        raw(), as_of=AS_OF, company=eligibility_engine.CompanyFacts(budget_ceiling_krw=CEILING)
    )
    assert all(r.status != "FAIL" for r in rules if r.rule_id == "ELIG-BUDGET")
    inside = priority.scale_component(150_000_000, ceiling=CEILING, joint_allowed=False).score
    over = priority.scale_component(270_000_000, ceiling=CEILING, joint_allowed=False).score
    assert inside is not None and over is not None and over < inside


@pytest.mark.parametrize(
    ("joint", "says"),
    [
        ("(없음)공동수급불허", "혼자 맡을지 정하세요"),
        ("(전자)공동이행", "함께할 회사를 구할지"),
        (None, "공고문에서 공동수급 방식을 확인"),
    ],
)
def test_역량_판정_다음_할_일도_공동수급_방식대로(joint: str | None, says: str) -> None:
    from app.schemas.delivery_capacity import DeliveryCapacity
    from app.schemas.procurement import ProcurementNotice
    from app.services import capability_service

    notice = ProcurementNotice(
        id="g2b-TEST-000", notice_no="TEST-000", title="AI 교육", agency="테스트기관",
        published_at=AS_OF, budget=270_000_000, raw_data=raw(joint=joint),
    )
    capacity = DeliveryCapacity(organization_id="org-test", source="file", budget_ceiling_krw=CEILING)
    finding = capability_service._scale_finding(capacity, notice)
    assert finding.status == "gap"
    assert finding.next_action and says in finding.next_action
    assert "공동수급을 검토하세요" not in finding.next_action
    assert "단독 수행" not in finding.reason + (finding.evidence.company_fact if finding.evidence else "")


def test_마지막_검토_회사_쪽_빈_값은_회사_쪽_확인() -> None:
    """최대 사업비 미입력 · 소재지 없음 · 활동 지역 없음은 「회사자료에 적을 것」이다 — 「공고문에서 볼 것」으로 가지 않게."""
    rule = budget_rule(raw(budget="150000000"), ceiling=None)
    assert rule.status == "CHECK" and rule.check_side == "company"


def test_마지막_검토_불허_주의_줄은_회사_기준대로() -> None:
    line = priority.caution_line(
        budget=300_000_000, ceiling=CEILING, days_left=20, lead_days=4, joint_allowed=False, out_of_scope=False
    )
    assert line == "규모 큼 — 함께 입찰 안 됨 · 혼자 맡을지 정하기"
