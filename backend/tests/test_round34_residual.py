"""34차 §3-F — 판정 · 글 잔여(R33-03 · 04 · 06 · 08). 네트워크 0."""

from __future__ import annotations

import dataclasses

from app.core.money import won_pair
from app.schemas.audit import AuditFinding
from app.services import eligibility_engine, finding_resolution_service
from tests.test_round32_rules import SAMPLEEDU, target
from tests.test_round33_budget import budget_rule, raw


def test_R33_03_결격_줄은_회사_쪽_묶음() -> None:
    token = eligibility_engine._ACTIVE_COMPANY.set(eligibility_engine.CompanyFacts(from_real_company=True))
    try:
        rule = eligibility_engine._rule_business_registration(None)
    finally:
        eligibility_engine._ACTIVE_COMPANY.reset(token)
    assert rule.status == "CHECK" and rule.check_side == "company"


def test_R33_04_반올림하면_같은_금액은_정확히() -> None:
    assert won_pair(200_400_000, 200_000_000) == ("200,400,000원", "200,000,000원")
    assert won_pair(450_000_000, 200_000_000) == ("4.5억원", "2억원")
    assert won_pair(200_000_000, 200_000_000) == ("2억원", "2억원")
    rule = budget_rule(raw(budget="200400000"))
    assert "사업비 200,400,000원 — 회사가 정한 최대 사업비 200,000,000원보다 크고" in rule.reason, rule.reason


def test_R33_06_경계_해에_다른_갈래도_확인_필요면_창업_연차_사유가_남는다() -> None:
    founded = dataclasses.replace(SAMPLEEDU, certifications=(), founded_year=2023)  # 2026 - 2023 = 3 — 경계 해
    result = target("창업 3년 이내 기업 또는 지역 특화산업을 영위하는 기업", founded)
    assert result.status == "CHECK", result.reason
    assert "설립 월에 따라" in result.reason, result.reason


def test_R33_08_32차_새_말_키로_남은_해결_기록을_잇는다() -> None:
    finding = AuditFinding(
        id="AF-1", finding_type="unsupported_claim", severity="medium",
        proposal_text="교육은 20회 운영합니다 (RFP p.3 요구사항 준수)", recommendation="근거를 붙이세요",
    )
    canonical = finding_resolution_service.resolution_key(finding)
    from app.services import wording

    alias = finding_resolution_service.resolution_key(wording.modernize_model(finding))
    assert alias != canonical  # 32차 화면은 새 말 글로 키를 만들었다
    assert finding_resolution_service.shown_key(finding, set()) == canonical
    assert finding_resolution_service.shown_key(finding, {alias}) == alias
    assert finding_resolution_service.shown_key(finding, {alias, canonical}) == canonical
