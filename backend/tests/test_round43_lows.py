"""43차 §2-I — 낮음(같은 파일에서 함께): 기업마당 「광주광역시」 소재(BIZ-16) · 창업 연차 경계 해(COMPANY-07) · 선행 사업 범위(COMPANY-09) ·
빈칸 안내 「이 칸만 걸린 m」 · 참고 칸(Q25). 호출 없음."""

from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

from app.services import bizinfo_document_store as store
from app.services import company_blank_fields
from app.services import eligibility_engine as ee
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from tests.test_support_application_v2 import SAMPLEEDU, program


def requirements(text: str):
    return extractor.extract_from_text("P", store.join_pages([text]))


GWANGJU_ONLY = "○ 신청자격\n- 공고일 기준 광주광역시에 본사를 둔 중소기업"


def test_광주광역시_소재는_회사_옛_지역이_광주일_때만_가능() -> None:
    req = requirements(GWANGJU_ONLY)
    gwangju = dataclasses.replace(SAMPLEEDU, location_old_region="광주", location_district="북구")
    passed = sas._biz_location(req, program("광주 기업 지원"), gwangju)
    assert passed.status == "PASS" and "회사 주소(북구)가 옛 광주광역시 지역이라 맞습니다" in passed.reason
    # 옛 전남 주소(여수) 회사는 거짓 「가능」이 아니라 확인 필요 — H2 와 같은 꼴
    yeosu = dataclasses.replace(SAMPLEEDU, location_old_region="전남", location_district="여수시")
    checked = sas._biz_location(req, program("광주 기업 지원"), yeosu)
    assert checked.status == "CHECK" and "옛 전라남도" in checked.reason
    unknown = dataclasses.replace(SAMPLEEDU, location_old_region=None, location_district=None)
    assert sas._biz_location(req, program("광주 기업 지원"), unknown).status == "CHECK"


def test_창업_연차_경계_해는_일반현황_개업일로_가른다() -> None:
    today = date(2026, 10, 23)
    opened = ee.CompanyFacts(founded_year=2021, founded_on=date(2021, 4, 15))
    assert ee.founding_edge(opened, 5, today) == ("FAIL", "개업일 2021-04-15(일반현황) — 창업 5년이 2026-04-15에 지났습니다")
    later = ee.CompanyFacts(founded_year=2021, founded_on=date(2021, 12, 15))
    status, why = ee.founding_edge(later, 5, today)
    assert status == "PASS" and "2026-12-15까지" in why
    near = ee.CompanyFacts(founded_year=2021, founded_on=date(2021, 11, 10))
    assert ee.founding_edge(near, 5, today) is None  # 30일 안 — 공고 기준일에 따라 갈림
    assert ee.founding_edge(ee.CompanyFacts(founded_year=2021), 5, today) is None  # 개업일 없음 — 지금처럼 확인 필요


def test_선행_사업_이름이_조항에_있으면_없음보다_먼저_확인_필요() -> None:
    none_line = "없음 확인 — 스마트제조혁신R&D 등 후속 과제의 신청 자격이 되는 선행 정부과제 수행 이력이 없다(검수자 조사 2026-09-18)"
    company = dataclasses.replace(SAMPLEEDU, completed_programs=(none_line, "데이터바우처 공급기업 선정"))
    assert sas._named_program(company, "2025년 데이터바우처 사업 선정 기업") == "데이터바우처 공급기업 선정"
    only_none = dataclasses.replace(SAMPLEEDU, completed_programs=(none_line,))
    assert sas._named_program(only_none, "2025년 데이터바우처 사업 선정 기업") is None


def test_빈칸_안내는_이_칸만_걸린_공고와_참고_칸을_센다() -> None:
    def item(n: int, unlocks: list[str]) -> SimpleNamespace:
        return SimpleNamespace(id=f"g{n}", title=f"공고 {n}", source_type="g2b", closed=False, relevance_note=None,
                               eligibility_gate="CHECK", unlock_conditions=unlocks)

    items = [item(1, ["매출 10억 이상이면 가능"]), item(2, ["매출 10억 이상이면 가능", "공동수급 파트너가 있으면 가능"])]
    fields = {f.key: f for f in company_blank_fields.count_fields(items, ee.CompanyFacts())}
    revenue = fields["revenue"].to_dict()
    assert revenue["count"] == 2 and revenue["only_count"] == 1 and revenue["reference"] is False
    partner = fields["joint_bid_partner"].to_dict()
    assert partner["reference"] is True and partner["only_count"] == 0
