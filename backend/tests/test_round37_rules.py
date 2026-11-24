"""37차 — 판정 기본값 D3 · D5 · 기획서 1-10 결함 · recheck29 R36-RV-03 · 05 · 06 (prompt_27 §3-G · 규칙 판 55 · 마지막 검토 56).

원문 문장은 공개 공고 글을 짧게 옮긴 회귀 상수다. 회사 값은 `dataclasses.replace` 로만 가정한다.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import bizinfo_document_store as store
from app.services import eligibility_engine as ee
from app.services import opportunity_priority as priority
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from app.services import work_kinds
from tests.test_support_application_v2 import DOMAINS, SAMPLEEDU, program

TODAY = date(2026, 10, 14)
KST = timezone(timedelta(hours=9))
GATE = {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}
PARTNER = dataclasses.replace(SAMPLEEDU, joint_bid_available=True)


def requirements(text: str):
    return extractor.extract_from_text("P", store.join_pages([text]))


def judged(text: str, company=SAMPLEEDU, **fields) -> tuple[str, str, list]:
    req = requirements(text)
    rules, indirect = sas.biz_rules_v2(program(**fields), req, company=company, today=TODAY, profile_domains=DOMAINS)
    gate, reason = sas.verdict_of(req, rules, indirect=indirect)
    return GATE[gate], reason, rules


def rule(rules, rule_id):
    return next(r for r in rules if r.rule_id == rule_id)


# --------------------------------------------------------------------------
# D3 — 촉박은 「불가」가 아니라 「확인 필요 · 촉박」 · 3일 이하 「원칙적으로 후순위」
# --------------------------------------------------------------------------


def _deadline(days: float):
    as_of = datetime(2026, 10, 14, 9, 0, tzinfo=KST)
    moment = (as_of + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    token = ee._ACTIVE_COMPANY.set(ee.CompanyFacts(proposal_lead_days=4))
    try:
        return ee._rule_bid_deadline({"bidClseDt": moment}, as_of)
    finally:
        ee._ACTIVE_COMPANY.reset(token)


def test_D3_준비_일수보다_짧으면_확인_필요_촉박():
    result = _deadline(3.5)
    assert result.status == "CHECK"
    assert result.reason.startswith("확인 필요 · 촉박")
    assert "원칙적으로 후순위" not in result.reason
    assert result.unlock_condition is None and result.check_side == "company"


def test_D3_3일_이하는_원칙적으로_후순위():
    assert "원칙적으로 후순위" in _deadline(2.5).reason
    assert "원칙적으로 후순위" in _deadline(3.0).reason


def test_D3_준비_일수_이상이면_그대로_통과_지난_마감은_그대로_불가():
    assert _deadline(5).status == "PASS"
    assert _deadline(-0.5).status == "FAIL"


# --------------------------------------------------------------------------
# D5 — 수행기관 모집은 「수행기관 모집(매출)」 · 확인 필요 (공고문을 읽지 않은 공고도)
# --------------------------------------------------------------------------


def test_D5_주관기관_모집은_불가가_아니라_확인_필요():
    verdict, _reason, rules = judged("1. 신청자격\n○ 전국 소재 기관\n", title="2027년 초격차 스타트업 프로젝트 주관기관 모집 공고")
    role = rule(rules, "BIZ-ROLE")
    assert role.status == "CHECK" and role.reason.startswith("수행기관 모집(매출)")
    assert verdict == "확인 필요"


def test_D5_공고문을_읽지_않은_공고도_같은_검사를_거친다():
    results = sas.biz_rules(program("2026년 AI 교육 운영기관 모집"), company=SAMPLEEDU, today=TODAY)
    role = next(r for r in results if r.rule_id == "BIZ-ROLE")
    assert role.status == "CHECK" and "수행기관 모집(매출)" in role.reason
    assert sas.is_operator_call(program("2026년 AI 교육 운영기관 모집"))
    assert not sas.is_operator_call(program("2026년 AI 교육 참여기업 모집"))


# --------------------------------------------------------------------------
# 기획서 1-10 결함 — 순천향 · 사용권 구매
# --------------------------------------------------------------------------


def test_순천향대학교는_광주전남_가산이_아니다():
    assert priority.home_ground("순천향대학교", None) is None
    assert priority.home_ground("순천시청", None) == "순천시청"
    assert priority.home_ground("국립순천대학교", None) == "국립순천대학교"


def test_사용권_구매는_구매_갈래():
    kinds = work_kinds.detect_work_kinds("AI 빅데이터 플랫폼 교수학습 지원 협업 플랫폼 사용권 구매 용역")
    assert "procurement" in kinds
    assert work_kinds.work_tracks(kinds) == ["other"]


# --------------------------------------------------------------------------
# R36-RV-03 — 컨소시엄 필수 + 파트너 「있음」 아님 → BIZ-ROLE 확인 필요 (125370)
# --------------------------------------------------------------------------

CONSORTIUM = (
    "1. 신청자격\n"
    "○ 양국 정부 간 합의에 기반하여 독일의 기관과 컨소시엄을 구성하고 공동 승인한 과제를 대상으로 자국 기관에 자금 지원\n"
    "○ 국내 주관연구개발기관 자격 : 창업 1년 이상 경과한 국내 기업\n"
)


def test_R36_RV_03_컨소시엄_필수인데_파트너가_없으면_확인_필요():
    verdict, _reason, rules = judged(CONSORTIUM)
    role = rule(rules, "BIZ-ROLE")
    assert role.status == "CHECK" and "컨소시엄" in role.reason
    assert role.unlock_condition == "컨소시엄 파트너 확보 시"
    assert verdict == "확인 필요"
    # 회사 쪽 확인이다(파트너 값)
    req = requirements(CONSORTIUM)
    assert "BIZ-ROLE" in sas.clause_signals(req, rules, indirect=None)["company_side_checks"]


def test_R36_RV_03_파트너_있음이면_이_규칙으로는_막지_않는다():
    _verdict, _reason, rules = judged(CONSORTIUM, company=PARTNER)
    assert rule(rules, "BIZ-ROLE").status == "PASS"


@pytest.mark.parametrize(
    "line",
    [
        "○ 광주광역시 소재 중소기업(컨소시엄 참여 가능)",
        "○ 형체력: 3,000톤 or 컨소시엄 구성 가능",  # 127152
        "○ 컨소시엄 구성이 가능하며, 연구개발과제 제안요청서를 따른다",  # 127025
        "○ 컨소시엄연구개발과제의 경우 컨소시엄을 구성하는 각 ‘연구개발과제’별 적용",  # 127081 · 127085
    ],
)
def test_R36_RV_03_선택_조건_꼴은_필수가_아니다(line: str):
    _verdict, _reason, rules = judged(f"1. 신청자격\n{line}\n")
    assert rule(rules, "BIZ-ROLE").status == "PASS"


@pytest.mark.parametrize(
    "line",
    [
        "○ 총괄 및 세부연구개발과제가 컨소시엄을 구성하여 신청",  # 126756
        "○ (양자 공동펀딩 R&D) 양국 정부간 합의한 협력국가의 기관과 컨소시엄을 구성",  # 126715
        "○ 지원 대상 : 중소벤처기업 주관(대학·출연연·전문연 등 컨소시엄 참여 필수)",  # 126812
        "○ 컨소시엄 구성 필수(단독 신청 불가능)",  # 37차 마지막 검토 — 「불가능」의 「가능」은 선택 꼴이 아니다
        "○ 반드시 컨소시엄으로 신청(단독 신청 불가능)",
    ],
)
def test_R36_RV_03_필수_꼴(line: str):
    _verdict, _reason, rules = judged(f"1. 신청자격\n{line}\n")
    assert rule(rules, "BIZ-ROLE").status == "CHECK"


# --------------------------------------------------------------------------
# R36-RV-05 — 「광주시 · 울산시 … 소재」 = 광역시 줄임말 · 「광주시」는 소관 · 수행기관으로 가린다
# --------------------------------------------------------------------------

METRO = "1. 신청자격\n○ 광주시 · 울산시에 본사가 소재한 중소기업\n"


def test_R36_RV_05_광역시_줄임말은_시군_조항이_아니다():
    clauses = requirements(METRO).of("location")
    assert {c.detail.get("alias") for c in clauses} == {"광주시", "울산시"}
    assert not any(c.detail.get("city") for c in clauses)
    gwangju = next(c for c in clauses if c.detail["alias"] == "광주시")
    assert gwangju.detail["region"] == "전남광주" and gwangju.detail.get("ambiguous")


def test_R36_RV_05_소관기관이_광주면_가능한_소재():
    _v, _r, rules = judged(METRO, agency="광주광역시", executing_agency="광주정보문화산업진흥원")
    assert rule(rules, "BIZ-LOCATION").status == "PASS"


def test_R36_RV_05_소관기관이_경기면_경기_광주시():
    _v, _r, rules = judged(METRO, agency="경기도", executing_agency="경기도경제과학진흥원")
    assert rule(rules, "BIZ-LOCATION").status == "FAIL"


def test_R36_RV_05_소관기관으로_못_가리면_확인_필요():
    _v, _r, rules = judged(METRO, agency="중소벤처기업부", executing_agency=None)
    loc = rule(rules, "BIZ-LOCATION")
    assert loc.status == "CHECK" and "경기도 광주시" in loc.reason


def test_R36_RV_05_경기도_광주시는_그대로_시군():
    clauses = requirements("1. 신청자격\n○ 경기도 광주시 소재 중소기업\n").of("location")
    assert any(c.detail.get("city") == "광주시" for c in clauses)


def test_R36_RV_05_울산시만이면_다른_지역():
    _v, _r, rules = judged("1. 신청자격\n○ 울산시에 본사가 소재한 기업\n")
    assert rule(rules, "BIZ-LOCATION").status == "FAIL"


# --------------------------------------------------------------------------
# R36-RV-06 — 「전담부서 미포함」은 같은 절 · 몇 줄 안에서만 · 「또는 연구개발전담부서」면 붙이지 않는다
# --------------------------------------------------------------------------


def _lab_only(text: str) -> list[bool]:
    return [c.detail.get("lab_only") for c in requirements(text).of("prerequisite") if c.detail.get("requirement") == "research_department"]


def test_R36_RV_06_또는_연구개발전담부서면_기업부설연구소만이_아니다():
    text = (
        "1. 신청자격\n○ 기업부설연구소 또는 연구개발전담부서를 보유한 중소기업\n"
        "※ 연구개발전담부서 인정서만 보유한 기업은 미포함\n"
    )
    assert _lab_only(text) == [False]


def test_R36_RV_06_멀리_떨어진_다른_절의_미포함은_붙이지_않는다():
    text = (
        "1. 신청자격\n○ 연구개발전담부서를 보유한 중소기업\n"
        "2. 지원내용\n○ 기술개발 자금 지원\n○ 시제품 제작 지원\n"
        "3. 가산 대상 아님\n□ 기타\n○ 전담부서 인정서만 보유한 기업은 미포함(다른 사업)\n"
    )
    assert _lab_only(text) == [False]


def test_R36_RV_06_바로_아래의_미포함은_붙인다():
    text = "1. 신청자격\n○ 연구개발전담부서 이상을 보유한 기업\n※ 전담부서 인정서만 보유한 기업은 미포함\n"
    assert _lab_only(text) == [True]


@pytest.mark.parametrize("joint", ["(전자)혼합방식", "주계약자관리방식"])
def test_혼합_주계약도_함께_참가할_수_있다고_적는다(joint: str):
    # `joint_allowed` 가 허용으로 보는 방식은 한 줄도 같은 말 — 브리핑 「파트너형」이 이 말을 읽는다(37차 마지막 검토)
    assert ee.joint_allowed({"cmmnSpldmdMethdNm": joint}) is True
    assert ee._joint_text(joint).startswith("다른 회사와 함께 참가할 수 있음")


def test_규칙_판_56_이상():
    # 38차 §3-A 가 57 로 올렸다(나라장터 분류) — 37차 규칙은 그대로다.
    assert sas.RULES_VERSION >= 56
