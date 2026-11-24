"""36차 — 값을 적은 뒤 생기는 거짓 판정(§3-B · recheck28).

원문 문장은 공개 공고 글을 짧게 옮긴 회귀 상수다. 회사 값은 `dataclasses.replace` 로만 가정한다.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from app.services import bizinfo_document_store as store
from app.services import eligibility_engine as ee
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from tests.test_support_application_v2 import DOMAINS, SAMPLEEDU, program

TODAY = date(2026, 10, 13)
GATE = {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}
OLD_GWANGJU = dataclasses.replace(SAMPLEEDU, location_old_region="광주")
LAB = dataclasses.replace(SAMPLEEDU, has_research_department=True, research_department_kind="lab")
DEPT = dataclasses.replace(SAMPLEEDU, has_research_department=True, research_department_kind="dept_only")
NO_LAB = dataclasses.replace(SAMPLEEDU, has_research_department=False)


def requirements(text: str):
    return extractor.extract_from_text("P", store.join_pages([text]))


def judged(text: str, company=SAMPLEEDU) -> tuple[str, str]:
    req = requirements(text)
    rules, indirect = sas.biz_rules_v2(program(), req, company=company, today=TODAY, profile_domains=DOMAINS)
    gate, reason = sas.verdict_of(req, rules, indirect=indirect)
    return GATE[gate], reason


# --------------------------------------------------------------------------
# R35-RULE-01 — 제외 · 서류 구간 (recheck28 verify t01)
# --------------------------------------------------------------------------

def test_신청자격_및_제외대상_머리는_제외_구간을_열지_않는다() -> None:
    text = "2. 신청자격 및 제외대상\n□ 공고일 기준 광주광역시 소재, 직전년도 매출액 10억원 이상인 중소기업\n□ 신청 제외 대상\n○ 국세 또는 지방세를 체납 중인 기업\n"
    assert judged(text, dataclasses.replace(SAMPLEEDU, revenue_krw_last_year=300_000_000))[0] == "불가"  # R1
    assert judged(text)[0] == "확인 필요"  # 매출 모름
    organisations = "2. 신청자격 및 제외대상\n□ 공고일 기준 광주광역시 소재 마을기업, 자활기업, 사회적협동조합\n□ 신청 제외 대상\n○ 국세 또는 지방세를 체납 중인 기업\n"
    assert judged(organisations)[0] == "불가"  # O1


@pytest.mark.parametrize(
    "text",
    [
        "1. 지원대상(참여제한 기업 제외)\n○ 광주광역시 소재 마을기업, 자활기업\n",  # E3
        "□ 지원대상 및 지원제외 대상\n ○ 광주광역시 소재 마을기업, 자활기업\n",  # E1
    ],
)
def test_자격_낱말이_함께_있는_머리_아래_형태_요건을_읽는다(text: str) -> None:
    assert judged(text)[0] == "불가"


def test_서류_구간은_윗단_글머리의_새_항목에서_끝난다() -> None:
    """D1 — 「※ 확인방법 : …」(목록 글머리) 아래 「○ 기업부설연구소를 보유한 기업」(윗단)은 요건이다."""
    text = "1. 신청자격\n○ 광주광역시 소재 중소기업\n※ 확인방법 : 중소기업현황정보시스템 조회\n○ 기업부설연구소를 보유한 기업\n"
    assert judged(text, NO_LAB)[0] == "불가"


def test_참여_제외_머리_아래는_대상_줄이_아니다() -> None:
    req = requirements("□ 지원 대상\nㅇ광주광역시 소재 기업\n□ 참여 제외\n① 신청일 현재 취업 중이거나 사업자등록 중인 자\n")
    assert req.unhandled_targets == []


# --------------------------------------------------------------------------
# R35-RULE-04 · R35-DV-04 — 옛 지역 · 이전 갈래
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "1. 지원대상\n○ 전남광주통합특별시 내 옛 전라남도 지역에 본사가 소재하거나 협약 전까지 이전 예정인 기업\n",  # M2
        "1. 지원대상\n○ 전남광주통합특별시 내 옛 전라남도 지역에 본사가 소재한 기업\n※ 프로그램별로 도내/외 기업 모두 신청 가능\n",  # M3
        "1. 지원대상\n○ 옛 전라남도 지역 소재 기업 또는 전남으로 이전 예정 기업\n",  # M4
    ],
)
def test_옛_지역이_달라도_이전_도내외_갈래가_있으면_확인_필요(text: str) -> None:
    assert judged(text, OLD_GWANGJU)[0] == "확인 필요"


def test_줄바꿈으로_갈린_이전_예정_갈래도_읽는다() -> None:
    """126963 — 「② … 창원특례시로 / 이전할 예정인 의료·바이오 관련 기업」."""
    text = (
        "□ 신청자격\n① 본사·공장·연구소 중 1개 이상이 경상남도 창원특례시에 소재하고 관내 의\n료·바이오 산업을 영위하는 기업\n"
        "② 공고일 기준 창원특례시 외 지역에 소재하나, 협약체결일로부터\n사업 종료일 전까지 본사·공장·연구소 중 1개 이상을 창원특례시로\n"
        "이전할 예정인 의료·바이오 관련 기업\n"
    )
    location = requirements(text).of("location")
    assert location and location[0].detail.get("relocation")
    assert judged(text)[0] == "확인 필요"


# --------------------------------------------------------------------------
# R35-RULE-12 — 「중 소기업ㆍ소상공인확인서」(1750115 QC-03 · 04)
# --------------------------------------------------------------------------

def test_끊긴_중_소기업_소상공인확인서는_셋_다_받는다() -> None:
    qc03 = "‘중 소기업ㆍ소상공인확인서’가 중소기업제품 공공구매 종합정보망(http://www.smpp.go.kr)에서 확인되지 않을 경우 입찰참가자격이 없습니다."
    qc04 = "‘중 소기업ㆍ소상공인확인서’를 전자입찰서 제출 마감일 전일까지 신청한 사항이 확인된 업체는 입찰참가가 가능하나"
    assert ee._sme_kind(qc03) == "sme" and ee._sme_kind(qc04) == "sme"
    assert ee._sme_kind("중소기업자 중 소기업자로서 중소기업·소상공인 확인서를 소지한 자") == "small"  # G2B-06 그대로


# --------------------------------------------------------------------------
# R35-DV-01 — 대상 절에 규칙이 못 읽은 줄이 남으면 「가능」이 아니다
# --------------------------------------------------------------------------

def test_못_읽은_대상_줄이_남으면_가능_대신_확인_필요() -> None:
    """125778 — 「미래모빌리티 인지부품 … 개발·제조 또는 사업화를 추진하는 국내 중소·중견기업」."""
    text = (
        "□ 신청자격\n○ 광주광역시 소재 기업\n"
        "○ 미래모빌리티 인지부품(라이다, 레이더 등) 및 관련 시스템의 개발·제조 또는 사업화를 추진하는 국내 기업\n"
    )
    gate, reason = judged(text)
    assert gate == "확인 필요" and sas.UNHANDLED_TARGET_PREFIX in reason and "인지부품" in reason
    assert judged("□ 신청자격\n○ 광주광역시 소재 기업\n")[0] == "가능"  # 규칙이 다 읽으면 가능 그대로


@pytest.mark.parametrize(
    "line",
    [
        "○ (지원방식) 프로그램 참여청년, 기업 등에 보조금 지급",  # 122145 지원방식
        "참여대상(기업/참여자)",  # 116832 머리
        "❏ 하반기 채용 예정 직무의 실무 적합성을 미리 확인하고 싶은 기업",  # 125426 추천 문구
        "개인정보 보유기업, AI, 가상융합, 제조산단",  # 123682 전략산업 표 칸
        "운영기관의 대표 및 임직원이 운영하는 기업(단체) 또는 계열 관계사인지 여부",  # 122145 확인 항목
    ],
)
def test_대상_요건이_아닌_대상_절_줄은_세지_않는다(line: str) -> None:
    assert requirements(f"□ 신청자격\n○ 광주광역시 소재 기업\n{line}\n").unhandled_targets == []


def test_절차_머리_아래_신청_대상은_회사_자격이_아니다() -> None:
    """121107 — 「【 측정결과 이의신청 절차 등 】 ○ (신청 대상) … 결과값에 오류가 있는 기업」."""
    text = "□ 신청자격\n○ 광주광역시 소재 사회적기업\n【 측정결과 이의신청 절차 등 】\n○ (신청 대상) 측정 참여기업 중 제출자료에 대한 측정\n결과값에 오류가 있는 기업\n"
    assert requirements(text).unhandled_targets == []


def test_연구소_문장_안의_중소_중견기업은_확인서_조항이다() -> None:
    req = requirements("□ 신청자격\n❍ 국내에 본사 또는 공장과 기업부설연구소를 보유한 중소·중견기업\n")
    assert [c.detail.get("clean") for c in req.of("sme")] == [True]


# --------------------------------------------------------------------------
# R35-DV-02 — 기업부설연구소만 · 전담부서만
# --------------------------------------------------------------------------

LAB_ONLY = (
    "□ 신청자격\n○ 주관연구개발기관 및 공동연구개발기관 中 국내기업은 접수마감일 현재 창업 1년 이상 경과하고, "
    "한국산업기술진흥협회가 발급한 “기업부설연구소 인정서”를 보유하고 있는 국내 사업자\n"
    "- 동 사업 지원대상에서 “연구개발전담부서 인정서”만 보유한 기업은 미포함\n"
)


def test_전담부서_미포함_공고는_전담부서만이면_확인_필요_열리는_조건은_연구소_인정() -> None:
    """125370 · 127116."""
    req = requirements(LAB_ONLY)
    research = [c for c in req.of("prerequisite") if c.detail.get("requirement") == "research_department"]
    assert research and all(c.detail.get("lab_only") for c in research)
    dept = sas._biz_prerequisite(req, DEPT, ())
    assert dept.status == "CHECK" and "기업부설연구소 인정을 받으면" in (dept.unlock_condition or "")
    assert sas._biz_prerequisite(req, LAB, ()).status == "PASS"
    none = sas._biz_prerequisite(req, NO_LAB, ())
    assert none.status == "FAIL" and "기업부설연구소 인정을 받으면" in (none.unlock_condition or "")
    assert "전담부서를 신고하면" not in (none.unlock_condition or "")


def test_전담부서도_받는_공고는_전담부서만이어도_맞고_없음이면_신고_안내() -> None:
    req = requirements("□ 신청자격\n○ 기업부설연구소 또는 연구개발전담부서를 보유한 기업\n")
    assert sas._biz_prerequisite(req, DEPT, ()).status == "PASS"
    assert "전담부서를 신고하면" in (sas._biz_prerequisite(req, NO_LAB, ()).unlock_condition or "")


# --------------------------------------------------------------------------
# R35-DV-03 · 127025 — 주관기관 자리에만 걸린 요건 · 과제 지역
# --------------------------------------------------------------------------

def test_주관기관_자리에만_걸린_연구소_요건은_없음이어도_확인_필요() -> None:
    """126756 — 「◦주관연구개발기관이 기업인 경우는 … 기업부설연구소를 보유하고 있어야 함」 · 공동연구개발기관 자리가 따로 있다."""
    text = (
        "4-2. 신청자격\n□ 주관연구개발기관 및 공동연구개발기관\n◦기업, 대학, 연구기관\n"
        "◦주관연구개발기관이 기업인 경우는 접수마감일 현재 법인사업자이어야 하며, 선정\n"
        "평가 개최일 이전에 기업부설연구소(한국산업기술진흥협회 인정서 기준)를 보유하고\n있어야 함\n"
    )
    rule = sas._biz_prerequisite(requirements(text), NO_LAB, ())
    assert rule.status == "CHECK" and "주관연구개발기관 자리에만" in rule.reason


def test_과제_지역_소재는_주관기관_자리면_확인_필요() -> None:
    """127025 — 「- (경북) 산불화재시 …」 과제 · 「< 주관연구개발기관 자격 조건 > … 해당 연구과제별 시·도에 소재해야 함」."""
    text = (
        "1. 사업개요\n○ 신규 연구개발과제 : 지정공모 1개 과제\n- (경북) 산불화재시 문화유산 보호 연소저지선 구축을 위한 AI기반\n"
        "③ 과제 수행기관 : 주관연구개발기관*, 공동연구개발기관**으로 편성된 컨소시엄 구성이 가능\n"
        "< 주관연구개발기관 자격 조건 >\n"
        "○ 주관연구개발기관은 기업만 신청가능하며 사업자등록증에 기재된 본점\n"
        "소재지가 공고일 전일까지 해당 연구과제별 시·도에 소재해야 함\n"
    )
    location = [c for c in requirements(text).of("location") if c.detail.get("task_region")]
    assert location and location[0].detail["region"] == "경북" and location[0].detail.get("role_limited")
    gate, reason = judged(text, LAB)
    assert gate == "확인 필요" and "경북" in reason


# --------------------------------------------------------------------------
# 36차 마지막 검토(R36-01 ~ 10) — 옛 코드(b906c32)와 견주어 재현된 회귀 · 규칙 판 54
# --------------------------------------------------------------------------

def test_R36_01_참여_신청_제외_문장_한_줄은_제외_구간을_열지_않는다() -> None:
    revenue = "□ 신청자격\n○ 광주광역시 소재 기업\n○ 대기업 및 계열사는 참여 제외\n○ 직전년도 매출액 10억원 이상인 기업\n"
    assert judged(revenue, dataclasses.replace(SAMPLEEDU, revenue_krw_last_year=300_000_000))[0] == "불가"
    organisations = "□ 신청자격\n○ 광주광역시 소재 기업\n○ 휴·폐업 중인 기업은 신청 제외\n○ 마을기업, 자활기업, 사회적협동조합\n"
    assert judged(organisations)[0] == "불가"
    # 머리 꼴(짧은 줄)은 그대로 제외 머리다
    assert extractor._exclusion_heading("□ 참여 제외") and not extractor._exclusion_heading("○ 대기업 및 계열사는 참여 제외")


@pytest.mark.parametrize("item", ["1. 사업신청서 1부\n2. 사업자등록증 사본 1부\n3.", "가. 사업신청서 1부\n나."])
def test_R36_02_제출서류의_번호_항목은_서류_구간을_끝내지_않는다(item: str) -> None:
    text = f"1. 신청자격\n○ 광주광역시 소재 기업\n□ 제출서류\n{item} 기업부설연구소 인정서(보유기업에 한함)\n"
    assert judged(text, NO_LAB)[0] == "가능"


@pytest.mark.parametrize(
    "text",
    [
        "□ 지원대상\n○ 광주광역시 소재 기업\n□ 지원 제외 대상(지원대상에서 제외되는 기업)\n- 비영리법인 및 협동조합\n- 국세 체납 기업\n",
        "1. 지원대상\n○ 광주광역시 소재 기업\n< 신청 제외 대상 > ※ 신청자격을 갖추었더라도 아래에 해당하면 제외\n- 사단법인, 재단법인 등 비영리법인\n",
    ],
)
def test_R36_03_괄호_속_자격_낱말이_있는_순수_제외_머리는_제외_구간을_연다(text: str) -> None:
    assert judged(text)[0] == "가능"


def test_R36_04_주관기관_한정_뒤_같은_값_줄은_한정_없는_조항으로_남지_않는다() -> None:
    text = ("4. 신청자격\n□ 주관연구개발기관 및 공동연구개발기관\nㅇ 기업, 대학, 연구기관 등\n"
            "- 주관연구개발기관으로 신청하는 기업의 경우는 접수마감일 현재 기업부설연구소를 보유하고 있는 법인사업자여야 함\n"
            "※ 기업부설연구소 보유여부 확인 : 한국산업기술진흥협회(www.rnd.or.kr)\n")
    research = [c for c in requirements(text).clauses if c.detail.get("requirement") == "research_department"]
    assert len(research) == 1 and research[0].detail.get("role_limited")
    assert judged(text, NO_LAB)[0] == "확인 필요"


def test_R36_05_과제_지역_소재는_문구가_시작하는_줄에만_붙는다() -> None:
    text = ("1. 사업개요\n- (경북) 산불 대응 AI 과제\n□ 신청자격\n"
            "○ 공동연구개발기관: 대학, 연구기관, 기업 모두 가능\n"
            "○ 주관연구개발기관: 해당 연구과제별 시·도에 소재한 기업\n")
    locations = [c for c in requirements(text).clauses if c.kind == "location"]
    assert len(locations) == 1 and locations[0].source_text.startswith("주관연구개발기관") and locations[0].detail.get("role_limited")
    assert judged(text)[0] == "확인 필요"


def test_R36_06_중소기업자_중_소기업_소상공인은_붙이지_않는다() -> None:
    assert ee._sme_kind("중소기업자 중 소기업 · 소상공인 확인서를 소지한 자") == "small"
    assert ee._sme_kind("본 입찰은 중소기업자 중 소기업·소상공인으로 참가자격을 제한합니다") == "small"
    assert ee._sme_kind("‘중 소기업ㆍ소상공인확인서’를 소지한 자") == "sme"  # 1750115 — 셋 다(R35-RULE-12 그대로)


@pytest.mark.parametrize(
    ("text", "company"),
    [
        ("□ 신청자격\n○ 경상북도 소재 중소기업\n○ 업력 7년 이내\n□ 의무사항\n○ 협약기간 중 본사를 타 지역으로 이전할 경우 지원금 환수\n", SAMPLEEDU),
        ("□ 신청자격\n○ 전남광주통합특별시 내 옛 전라남도 지역에 본사가 소재한 기업\n□ 사후관리\n○ 선정 후 3년 내 본사를 도외로 이전하는 경우 환수\n", OLD_GWANGJU),
    ],
)
def test_R36_07_사후관리의_이전_환수는_이전_갈래가_아니다(text: str, company) -> None:
    assert judged(text, company)[0] == "불가"


def test_R36_08_운영기관_주관기관_줄은_신청_자리_한정이_아니다() -> None:
    text = "□ 사업개요\n○ 주관기관 : 경북테크노파크\n○ 지원대상 : 경상북도 소재 중소기업\n□ 유의사항\n○ 참여기관은 협약 후 사업비를 집행한다\n"
    assert judged(text)[0] == "불가"
    lab = "□ 신청자격\n○ 주관기관(재단)이 정한 기준에 따라\n○ 기업부설연구소를 보유한 기업\n※ 참여기관 : 지역 대학\n"
    assert judged(lab, NO_LAB)[0] == "불가"


def test_R36_09_매출_문맥_아래_줄은_못_읽은_대상_줄이_아니다() -> None:
    text = "□ 신청자격\n○ 광주광역시 소재 기업\n○ 직전년도 매출액 기준\n- 10억원 이상인 기업\n"
    assert not requirements(text).unhandled_targets
    assert judged(text, dataclasses.replace(SAMPLEEDU, revenue_krw_last_year=1_500_000_000))[0] == "가능"


def test_R36_10_가점_문맥의_전담부서_불인정은_연구소만_요건이_아니다() -> None:
    text = ("□ 신청자격\n○ 기업부설연구소 또는 연구개발전담부서를 보유한 광주광역시 소재 기업\n"
            "□ 가점\n○ 연구개발전담부서 보유 기업은 가점 불인정(기업부설연구소만 가점)\n")
    assert judged(text, DEPT)[0] == "가능"
    only_lab = "□ 신청자격\n○ 기업부설연구소를 보유한 광주광역시 소재 기업(연구개발전담부서 인정서만 보유한 기업은 미포함)\n"
    assert judged(only_lab, DEPT)[0] == "확인 필요"


def test_연구소_종류는_보유일_때만_회사_사실로_간다(monkeypatch: pytest.MonkeyPatch) -> None:
    """검토 지적 — `company_facts_for` 의 연구소 종류 옮기기에 시험이 없었다(「없음」인데 옛 종류가 남으면 안 된다)."""
    from app.schemas.delivery_capacity import DeliveryCapacity
    from app.services import delivery_capacity_service, organization_service

    def raise_missing(_org):
        raise LookupError("프로필 없음")

    monkeypatch.setattr(organization_service, "load_profile", raise_missing)
    for has, kind, expected in ((True, "dept_only", "dept_only"), (False, "lab", None), (None, "lab", None)):
        capacity = DeliveryCapacity(organization_id="org-test", has_research_department=has, research_department_kind=kind)
        monkeypatch.setattr(delivery_capacity_service, "load", lambda _org, c=capacity: c)
        facts = ee.company_facts_for("org-test", evidence_scope="internal")
        assert facts.has_research_department is has and facts.research_department_kind == expected
