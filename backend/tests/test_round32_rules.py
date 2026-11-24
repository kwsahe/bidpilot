"""32차 §3-C — 「가능」 판정 잔여(recheck24 R31-01~08). 거짓 「불가」(목록에서 숨음)를 먼저 막는다."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.services import bizinfo_document_store as store
from app.services import eligibility_engine
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor

TODAY = date(2026, 10, 7)
SAMPLEEDU = eligibility_engine.CompanyFacts(
    location_region="전남광주",
    certifications=("사회적기업", "데이터바우처 공급기업"),
    founded_year=2021,
    employee_count=None,
    activity_regions=("광주광역시", "전라남도"),
)


def target(line: str, company=SAMPLEEDU, *, category: str = "중소기업") -> Any:
    from tests.test_support_biz_rules import _target  # 31차 도우미와 같은 길

    return _target(line, company, category=category)


# --------------------------------------------------------------------------
# R31-01 절차 문장은 선행 선정 요건이 아니다
# --------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "ㅇ (결과통보) 선정기업에 한하여 선정심사일로부터 5일 이내 개별 통보",  # 122147
    "최종 선정된 기관에 한하여 제출 선정기관 협약전",  # 126384
])
def test_R31_01_선정_뒤_절차_문장은_선행_선정_요건이_아니다(line: str) -> None:
    text = store.join_pages([f"○ 신청자격\n{line}"])
    keys = [c.detail.get("requirement") for c in extractor.extract_from_text("P", text).of("prerequisite")]
    assert "prior_selection" not in keys


def test_R31_01_자격_꼴의_선정업소는_그대로_요건이다() -> None:
    text = store.join_pages(["○ 신청자격\n강진군 밀키트 사업 선정업소로 (식육)즉석판매제조가공업 영업 신고 및 사업자등록 되어 있는 업소"])
    keys = [c.detail.get("requirement") for c in extractor.extract_from_text("P", text).of("prerequisite")]
    assert "prior_selection" in keys


# --------------------------------------------------------------------------
# R31-02 진입 앞말 「이/가」 · 꼬리 자르기
# --------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "사회적기업이거나 사회적기업으로 전환하려는 협동조합",
    "사회적기업이며 마을기업으로 지정받고자 하는 기업",
])
def test_R31_02_앞_인증이_진입_꼴이_아니면_불가가_아니다(line: str) -> None:
    result = target(line)
    assert result.status != "FAIL", result.reason


def test_R31_02_이가_뒤가_되고자면_진입_꼴이다() -> None:
    assert sas._aspiring_flags("사회적기업이 되고자 하는 기업", "사회적기업") == [True]
    assert sas._aspiring_flags("사회적기업이거나 협동조합", "사회적기업") == [False]


# --------------------------------------------------------------------------
# R31-03 괄호 안 단서 · v2 창업 연차
# --------------------------------------------------------------------------


def test_R31_03_괄호_안_단서가_있으면_창업_연차_불가가_아니다() -> None:
    old = eligibility_engine.CompanyFacts(location_region="전남광주", founded_year=2018)  # 업력 8년
    result = target("창업 7년 이내 기업(신산업 분야기업은 10년 이내까지 인정)", old)
    assert result.status == "CHECK", result.reason
    assert sas._founding_alternative("창업 7년 이내 기업(신산업 분야기업은 10년 이내까지 인정)")
    assert not sas._founding_alternative("창업 7년 이내 기업(단순 유통 판매업 제외)")


def test_R31_03_v2_창업_연차도_단서가_있으면_확인_필요() -> None:
    old = eligibility_engine.CompanyFacts(location_region="전남광주", founded_year=2018)
    text = store.join_pages(["○ 신청자격\n창업 7년 이내 기업(신산업 분야기업은 10년 이내까지 인정)"])
    requirements = extractor.extract_from_text("P", text)
    rule = sas._biz_age(requirements, old, TODAY)
    if rule is not None:
        assert rule.status != "FAIL", rule.reason


# --------------------------------------------------------------------------
# R31-04 낱말 안의 인증 낱말
# --------------------------------------------------------------------------


def test_R31_04_중소벤처기업부의_벤처기업은_회사_인증이_아니다() -> None:
    venture = eligibility_engine.CompanyFacts(location_region="전남광주", certifications=("벤처기업",), founded_year=2021)
    result = target("중소벤처기업부 혁신제품 지정 기업", venture)
    assert result.status != "PASS", result.reason


def test_R31_04_예비사회적기업_안의_사회적기업은_맞추지_않는다() -> None:
    assert sas._cert_matches("예비사회적기업으로 지정된 기업", "사회적기업") == []
    assert len(sas._cert_matches("(예비)사회적기업으로 지정된 기업", "사회적기업")) == 1


# --------------------------------------------------------------------------
# R31-05 분류 이름만 맞고 대상 줄은 다른 조직 형태
# --------------------------------------------------------------------------


def test_R31_05_분류만_맞고_대상_줄이_마을기업이면_확인_필요() -> None:
    result = target("마을기업 · 협동조합", category="사회적기업")
    assert result.status == "CHECK", result.reason


# --------------------------------------------------------------------------
# R31-06 창업 연차로 가능이어도 같은 갈래의 엄한 조건 · 설립 연도 미입력
# --------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "창업 7년 이내 기업으로서 사회적기업으로 진입하고자 하는 기업",
    "창업 7년 이내 협동조합",
    "창업 7년 이내 입주기업",
])
def test_R31_06_창업_연차가_맞아도_같은_갈래의_엄한_조건이면_확인_필요(line: str) -> None:
    result = target(line)
    assert result.status == "CHECK", result.reason


def test_R31_06_설립_연도가_없으면_확인_필요와_적는_법() -> None:
    nofounded = eligibility_engine.CompanyFacts(location_region="전남광주", certifications=(), founded_year=None)
    result = target("창업 7년 이내 기업", nofounded)
    assert result.status == "CHECK" and "설립 연도" in result.reason
    assert result.unlock_condition and "설립 연도" in result.unlock_condition


# --------------------------------------------------------------------------
# R31-07 갈래 밖은 위치 조건만
# --------------------------------------------------------------------------


def test_R31_07_다른_갈래의_비위치_조건으로_맞은_갈래를_내리지_않는다() -> None:
    result = target("사회적기업 또는 만 39세 이하 청년 창업자")
    assert result.status == "PASS", result.reason


def test_R31_07_위치_조건은_갈래를_가로질러_본다() -> None:
    result = target("사회적기업으로 본사 또는 공장이 북구 관내에 있는 기업")
    assert result.status == "CHECK" and "세부 지역" in result.reason


# --------------------------------------------------------------------------
# R31-08 메모 열쇠가 추출기 · 점수 파일 변경도 따라간다
# --------------------------------------------------------------------------


def test_R31_08_메모_열쇠에_판정_추출기_점수_파일_지문이_든다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import opportunity_service

    stamp = opportunity_service._inputs_stamp()
    assert stamp.split("-")[1] == opportunity_service._rule_code_fingerprint()
    assert "support_requirement_extractor.py" in opportunity_service._RULE_CODE_FILES
    assert "opportunity_priority.py" in opportunity_service._RULE_CODE_FILES
    opportunity_service._rule_code_fingerprint.cache_clear()
    monkeypatch.setattr(opportunity_service, "_RULE_CODE_FILES", ("support_kinds.py",))
    assert opportunity_service._rule_code_fingerprint() != stamp.split("-")[1]
    opportunity_service._rule_code_fingerprint.cache_clear()


def test_R31_03_조건_자체인_괄호는_단서가_아니다() -> None:
    """117583 「춘천시에 소재한 중소기업(창업 7년 이내)」 — 괄호가 조건 자체다."""
    assert not sas._founding_alternative("신청일 현재 춘천시에 소재한 중소기업(창업 7년 이내)")


@pytest.mark.parametrize("line", [
    "OO 지원사업 선정기업에 한하여 신청할 수 있음(최종 선정 결과는 개별 통보)",  # 절차 낱말이 괄호 안에만
    "OO 지원사업 선정기업에 한하여 신청 가능하며, 협약 기간은 1년",  # 신청 자격 꼴(절차 낱말 「협약」이 같은 줄에)
])
def test_마지막_검토_진짜_선행_선정_요건은_절차_낱말이_있어도_남는다(line: str) -> None:
    text = store.join_pages([f"○ 신청자격\n{line}"])
    keys = [c.detail.get("requirement") for c in extractor.extract_from_text("P", text).of("prerequisite")]
    assert "prior_selection" in keys
