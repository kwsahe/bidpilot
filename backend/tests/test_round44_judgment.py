"""44차 §2-B — 판정 · 회사 값(결정 4 공동수급 허용 업종 · R36-J-04 결격 조항 · 대표 결정 1 「안 적음」 넓히기). 호출 없음."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.schemas.business_opportunity import UnifiedOpportunity
from app.services import company_blank_fields, eligibility_engine
from app.services import practical_priority as practical

KST = timezone(timedelta(hours=9))
AS_OF = datetime(2026, 9, 20, 9, tzinfo=KST)
# 지금 서버의 샘플에듀와 같은 등록 업종(1169 학술.연구용역 · 9999 기타자유업종 · 대표 결정 10-23)
SERVER_LIKE = eligibility_engine.CompanyFacts(location_region="전남광주", registered_industry_codes=("1169", "9999"))
SW_1469 = {"name": "소프트웨어사업자(디지털콘텐츠개발서비스사업)", "code": "1469", "allowed_industries": []}


def _industry(joint: str | None) -> Any:
    item: dict[str, Any] = {"bidNtceNo": "R44J", "bidClseDt": "2026-09-30 10:00:00"}
    if joint is not None:
        item["cmmnSpldmdMethdNm"] = joint
    rows = eligibility_engine.evaluate_notice_fields(
        {"item": item, "license_limits": [SW_1469]}, as_of=AS_OF, regions=("광주광역시",), company=SERVER_LIKE,
    )
    return next(r for r in rows if r.rule_id == "ELIG-INDUSTRY"), rows, {"item": item}


@pytest.mark.parametrize("joint", ["(전자)공동이행", "(전자)혼합방식", "(수기)분담이행"])
def test_결정4_업종_없어도_공동수급_허용이면_확인_필요_파트너형(joint: str) -> None:
    row, rows, raw = _industry(joint)
    assert row.status == "CHECK"
    assert row.reason.startswith("업종 없음(필요: 소프트웨어사업자(디지털콘텐츠개발서비스사업), 1469) — 공동수급 허용(")
    assert "공동이행은 보통 구성원 모두 그 업종이 있어야 합니다(공고문 확인)" in row.reason
    # 열리는 조건은 그대로 — 갭 보고(「1469 등록 시」)가 계속 센다
    assert row.unlock_options == ["소프트웨어사업자(디지털콘텐츠개발서비스사업), 1469 등록 시 가능"]
    assert eligibility_engine.industry_partner(rows, raw) == "allowed"


def test_결정4_공동수급_불허면_그대로_불가() -> None:
    row, rows, raw = _industry("(없음)공동수급불허")
    assert row.status == "FAIL"
    assert eligibility_engine.industry_partner(rows, raw) is None


def test_결정4_공동수급_모름이면_확인_필요_공동수급_확인() -> None:
    row, rows, raw = _industry(None)
    assert row.status == "CHECK" and "공동수급 확인 필요" in row.reason
    assert eligibility_engine.industry_partner(rows, raw) == "unknown"


def _item(**kw: Any) -> UnifiedOpportunity:
    base: dict[str, Any] = dict(
        id="g2b-R44J-000", source_type="g2b", opportunity_type="procurement", title="이러닝 콘텐츠 개발", agency="광주광역시교육청",
        organization_id="org-sample", priority_rank=0, priority_label="검토", confidence="medium", score_components=[],
        next_route={"kind": "procurement_analysis", "path": "/", "label": "l"}, source="g2b", fit_type="A2", budget=50_000_000,
    )
    base.update(kw)
    return UnifiedOpportunity(**base)


def test_결정4_실무순은_크기와_지역에_상관없이_파트너형_덩어리_꼬리표_한_곳() -> None:
    small = _item(industry_partner="allowed")  # 5천만 원 · 광주 발주라도
    assert practical.block_of(small, 200_000_000, home=True) == practical.BLOCK_LARGE
    assert practical.partner_tag(small, 200_000_000) == "업종 없음 · 파트너형(공동수급 허용)"
    unknown = _item(industry_partner="unknown")
    assert practical.partner_tag(unknown, 200_000_000) == "업종 없음 · 파트너형(공동수급 확인 필요)"
    # 사업기회 행 · 브리핑 판단 칸 · 엑셀이 같은 값(꼬리표 한 곳)
    from app.services import opportunity_brief_service as brief

    practical.annotate([small], now=AS_OF, ceiling_krw=200_000_000, home_of=lambda _i: True)
    assert small.practical_group == practical.GROUP_PARTNER
    assert small.partner_tag in practical.tags_of(small)
    assert brief.verdict_of(small).startswith("업종 없음 · 파트너형(공동수급 허용)")
    # 「가능」은 나오지 않는다
    assert small.eligibility_gate != "PASS"


def _disqual(text: str, company: eligibility_engine.CompanyFacts) -> Any:
    clause = eligibility_engine._Clause(id="QC-01", kind="disqualification", text=text, page=2, origin="입찰공고문", approx=False)
    return eligibility_engine._judge_disqualification(clause, company, date(2026, 10, 24))


CHECKED = eligibility_engine.CompanyFacts(
    location_region="전남광주", from_real_company=True,
    company_checks=tuple((k, "2026-10-20", "2027-10-19", "대표") for k in eligibility_engine.REGISTRATION_CHECK_KEYS),
)


def test_J04_통과는_등록_제재_체납_낱말이_있을_때만() -> None:
    assert _disqual("국가를 당사자로 하는 계약에 관한 법률 시행령 제76조에 따라 부정당업자로 제재를 받은 자는 참가할 수 없음", CHECKED).status == "PASS"
    # 낱말이 없는 빼는 문장 — 회사 단위 확인으로 통과하지 않는다
    assert _disqual("입찰공고일 현재 휴면 중인 법인은 참가할 수 없음", CHECKED).status == "CHECK"


def test_J04_부도_회생_상호출자는_확인_필요() -> None:
    row = _disqual("부도 · 회생절차 진행 중이거나 상호출자제한기업집단 소속 기업은 참가할 수 없으며 부정당업자 제재를 받은 자도 제외", CHECKED)
    assert row.status == "CHECK" and "회사 단위 확인(등록 · 제재 · 체납)이 다루지 않습니다" in row.reason


def test_J04_대괄호_업종_코드는_업종_조건으로_회사_등록_업종과_대조() -> None:
    from app.services import qualification_clause_service as qc

    text = "국가종합전자조달시스템에 [행사대행업, 9901]으로 입찰참가자격을 등록한 업체가 아니면 참가할 수 없음"
    assert qc.industry_codes(text) == ["9901"]
    assert qc.classify(text) == "industry"
    clause = eligibility_engine._Clause(id="QC-02", kind="industry", text=text, page=2, origin="입찰공고문", approx=False)
    row = eligibility_engine._judge_industry(clause, {}, CHECKED.__class__(location_region="전남광주", registered_industry_codes=("1169", "9999")))
    assert row.status == "CHECK" and row.rule_id.startswith("QUAL-INDUSTRY")
    assert eligibility_engine._judge_industry(clause, {}, eligibility_engine.CompanyFacts(registered_industry_codes=("9901",))).status == "PASS"


def test_안_적음_넓히기_대표_값_칸이_빈칸_안내에_서고_고르면_빠진다() -> None:
    company = eligibility_engine.CompanyFacts(location_region="전남광주")
    fields = {f.key: f for f in company_blank_fields.count_fields([], company)}
    for key in ("company_checks", "direct_production_items", "digital_products", "founded_on", "women_enterprise", "certification_history"):
        assert fields[key].blank and fields[key].to_dict()["owner_value"], key
        assert key in company_blank_fields.FIELD_KEYS  # 「안 적음」 저장이 받는 열쇠
    kept = {f.key: f for f in company_blank_fields.count_fields([], company, left_blank={"company_checks", "founded_on"})}
    assert kept["company_checks"].left_blank and kept["founded_on"].left_blank
    assert not kept["digital_products"].left_blank
