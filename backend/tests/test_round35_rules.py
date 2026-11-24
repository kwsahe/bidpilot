"""35차 — 회사 값을 적으면 생기는 거짓 불가(§3-A) · 거짓 「가능」 · 거짓 「맞음」(§3-B).

원문 문장은 공개 공고 글을 짧게 옮긴 회귀 상수다(recheck27 §2 · §3). 회사 값은 `dataclasses.replace` 로만 가정한다.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from app.services import bizinfo_document_store as store
from app.services import eligibility_engine as ee
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from tests.test_support_application_v2 import SAMPLEEDU, program


def requirements(text: str):
    return extractor.extract_from_text("P", store.join_pages([text]))


def research(text: str) -> list:
    return [c for c in requirements(text).of("prerequisite") if c.detail.get("requirement") == "research_department"]


NO_LAB = dataclasses.replace(SAMPLEEDU, has_research_department=False)


# --------------------------------------------------------------------------
# 1) R34-DATA-01 연구소 — 보유 동사가 붙은 대상 문장에서만
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "기업부설연구소 인정서, 벤처 인증 등",  # 120946 서류 이름
        "기업부설연구소, 연구개발전담부서, 조직도 상의 연구개발팀 등 조직 측면의 역량을 기재",  # 126672 작성요령
        "ex) 신사업기획팀 3명, 기업부설연구소 12명, 경영지원팀 2명 + 연구혁신팀 5명 등",  # 122147 예시
        "③ 기업부설연구소 및 연구개발전담부서의 연구전담요원",  # 122273 근로자 수에서 빼는 사람
        "③ 기업부설연구소 및 연구개발전담부서*의 연구전담요원",  # 121182
        "ˑ 기업부설연구소 20",  # 126926 배점
        "④ 사업자등록증(또는 공장등록증, 기업부설연구소 또는",  # 121945 서류
        "「2026년 연구조직(기업부설연구소 등) 설립 및",  # 122045 사업 이름 줄
    ],
)
def test_연구소_낱말만_있는_줄은_보유_요건이_아니다(line: str) -> None:
    assert research(f"□ 신청자격\n{line}") == []


def test_서류_목록_아래의_보유기업은_서류_이름이다() -> None:
    """117992 「추가 제출서류 · 확인 방법(증빙서류)」 표의 「…인정서 보유기업」."""
    text = "<참고> 필수 서류\n나. 추가 제출서류 : 아래 항목의 관련 서류 중, 1가지 이상 필수 제출\n연번\n추가 제출서류\n확인 방법 (증빙서류)\n①\n기업부설연구소 또는 연구개발전담부서 인정서 보유기업"
    assert research(text) == []


def test_보유_동사가_붙은_대상_문장은_요건이고_없음이면_불가() -> None:
    req = requirements("□ 신청자격(공통)\n❍ 국내에 본사 또는 공장과 기업부설연구소를 보유한 중소·중견기업")
    assert len([c for c in req.of("prerequisite") if c.detail.get("requirement") == "research_department"]) == 1
    rule = sas._biz_prerequisite(req, NO_LAB, ())
    assert rule is not None and rule.status == "FAIL"
    lab = sas._biz_prerequisite(req, dataclasses.replace(SAMPLEEDU, has_research_department=True, research_department_kind="lab"), ())
    assert lab is not None and lab.status == "PASS"
    # 36차 R35-DV-02 — 문장에 전담부서가 없으면 기업부설연구소만이다: 종류를 모르는 옛 「보유」는 확인 필요
    legacy = sas._biz_prerequisite(req, dataclasses.replace(SAMPLEEDU, has_research_department=True), ())
    assert legacy is not None and legacy.status == "CHECK"


def test_동사가_다음_줄에_오는_보유_요건도_읽는다() -> None:
    """127025 「* 연구개발조직(…기업부설연구소 또는 / 연구개발전담부서 인정서를 보유해야 함)이 … 소재해야 함」."""
    found = research(
        "□ 신청자격\n* 연구개발조직(한국산업기술진흥협회에서 발급하는 기업부설연구소 또는\n"
        "연구개발전담부서 인정서를 보유해야 함)이 접수 마감일 현재 해당 연"
    )
    assert len(found) == 1 and "보유해야" in found[0].source_text


def test_여러_갈래_중_하나인_보유는_없음이어도_확인_필요() -> None:
    """122045 「기업부설연구소, 연구개발전담부서, 기업부설창작연구소, 기업창작전담부서 / 중 1개 이상 보유」."""
    req = requirements("□ 신청자격\n▷ 기업부설연구소, 연구개발전담부서, 기업부설창작연구소, 기업창작전담부서\n중 1개 이상 보유 중소벤처기업")
    rule = sas._biz_prerequisite(req, NO_LAB, ())
    assert rule is not None and rule.status == "CHECK"


# --------------------------------------------------------------------------
# 2) R34-DATA-02 매출 — 제외 목록 · 배점 · 갈래는 매출 하한 불가가 아니다
# --------------------------------------------------------------------------

REVENUE_3 = dataclasses.replace(SAMPLEEDU, revenue_krw_last_year=300_000_000)
REVENUE_12 = dataclasses.replace(SAMPLEEDU, revenue_krw_last_year=1_200_000_000)


def test_119754_신청_제외_목록의_매출은_매출_요건이_아니다() -> None:
    req = requirements(
        "□ 지원 대상\nㅇ 창업하여 7년이 지나지 아니한 기업 ⑤ 기타 중소벤처기업부장관이 참여제한의 사유가 있다고 인정하는 자(기업)\n"
        "⑥ 다음의 기준 요건에 해당하는 창업기업\n1) 제안 사업 아이템과 연관된 직전 연도 매출액이 10억원 이상인 경우"
    )
    assert req.of("revenue") == []
    assert sas._biz_revenue(req, REVENUE_3) is None


def test_대상_문장의_매출_하한은_불가() -> None:
    req = requirements("○ 신청자격\n- 직전 연도 매출액 10억원 이상인 중소기업")
    rule = sas._biz_revenue(req, REVENUE_3)
    assert rule is not None and rule.status == "FAIL"
    assert sas._biz_revenue(req, REVENUE_12).status == "PASS"


@pytest.mark.parametrize(
    "text",
    [
        "• (신청자격(최소 정량기준)) 아래 기준 중 1개 이상을 충족하여야 함\n1. 최근 3개 사업연도 평균 매출액 10억원 이상*",  # 126497 갈래
        "□ 신청자격\n참여기업 규모\n• 전년도 기준 매출액(15점)\n5억원 이상",  # 126473 배점
    ],
)
def test_대상_문장이_아닌_매출_기준은_못_미쳐도_확인_필요(text: str) -> None:
    req = requirements(text)
    rule = sas._biz_revenue(req, REVENUE_3)
    assert rule is not None and rule.status == "CHECK"
    assert sas._biz_revenue(req, REVENUE_12) is None  # 넘으면 막을 것도 「맞음」도 없다


# --------------------------------------------------------------------------
# 3) R34-DATA-03 · 4) R34-DATA-04 인원
# --------------------------------------------------------------------------

T_116832 = (
    "참여대상(기업/참여자)\n(기업) 고용보험 피보험자 10인 이상 기업*\n"
    "*벤처기업, 이노비즈, 사회적기업 등 일부 기업은 10인 미만 사업장도 지원 가능."
)


def test_116832_N인_미만_사업장도_지원_가능은_인원_예외다() -> None:
    req = requirements(T_116832)
    assert req.of("headcount_waiver")
    assert req.of("org_type") == []  # 예외 문장의 형태 낱말은 대상 요건이 아니다
    for count in (None, 3):
        rule = sas._biz_headcount(req, dataclasses.replace(SAMPLEEDU, employee_count=count))
        assert rule is not None and rule.status == "PASS", (count, rule)


def test_125345_배정_비율은_인원_요건이_아니다() -> None:
    req = requirements("○ 사업대상\n- 참여기업 : 근로자 5인 미만 기업(70%), 5인 이상 기업(30%)")
    assert sas._biz_headcount(req, dataclasses.replace(SAMPLEEDU, employee_count=3)) is None


# --------------------------------------------------------------------------
# 5) R34S-06 소상공인만
# --------------------------------------------------------------------------


def test_다른_형태와_함께_나열된_소상공인은_소상공인만이_아니고_분류로_돌아가지_않는다() -> None:
    req = requirements("○ 지원대상 : 소상공인 및 사회적기업")
    mid = dataclasses.replace(SAMPLEEDU, sme_held=True, sme_grade="중기업")
    assert sas._biz_small_business(req, program(target="소상공인"), mid, date(2026, 10, 11)) is None


def test_조건이_붙은_소상공인_줄은_인원이_맞아도_가능이_아니다() -> None:
    """121182 「위기 소상공인으로 선별되어 위기 알림톡을 받은 자」 — 규칙이 못 읽는 조건."""
    small = dataclasses.replace(SAMPLEEDU, employee_count=3)
    req = requirements("□ 지원대상\n따라 위기 소상공인으로 선별**되어 위기 알림톡을 받은 자로서,")
    rule = sas._biz_small_business(req, program(target="소상공인"), small, date(2026, 10, 11))
    assert rule is not None and rule.status == "CHECK"
    plain = requirements("□ 지원대상\n지원대상 : 소상공인")
    assert sas._biz_small_business(plain, program(target="소상공인"), small, date(2026, 10, 11)).status == "PASS"


# --------------------------------------------------------------------------
# §3-B 1) G2B-01 실적 금액 꼴 · 2) G2B-02 컨설팅 실적
# --------------------------------------------------------------------------

from app.services import performance_match_service as pm  # noqa: E402

T_1751800 = "최근 3년 내 대학을 대상으로 수행한 AI·SW 분야 교육 중, 단일 계약금액 2,500만원 이상인 실적이 3건 이상이거나 누적 수료 인원이 100명 이상인 자"
T_1699556 = "최근 3년 내 대학 대상 AI·SW 분야 교육 수행 실적이 3건 이상이거나 누적 수료 인원을 100명 이상 보유한 자 (단, 2.5천만원 이상의 건만 인정)"


@pytest.mark.parametrize("text", [T_1751800, T_1699556])
def test_한_건_기준이_누적보다_먼저다(text: str) -> None:
    criteria = pm.parse_criteria(text)
    assert criteria.amount_mode == "single" and criteria.min_amount_thousand == 25_000


def ledger_company(*rows: dict) -> ee.CompanyFacts:
    return dataclasses.replace(
        SAMPLEEDU, ledger_available=True, ledger_rows=tuple(tuple(sorted(r.items())) for r in rows)
    )


def track(text: str, company: ee.CompanyFacts):
    clause = ee._Clause(id="QC-07", text=text, page=2, origin="입찰공고문", approx=False, kind="track_record")
    return ee._judge_track_record(clause, company, date(2026, 10, 11))


ROW = {"year": "2025", "title": "대학 AI·SW 교육 과정 운영", "summary": "AI 소프트웨어 교육", "agency": "OO대학교",
       "field": "대학·교육기관", "amount_thousand_krw": 30_000, "eligible": True}


def test_원장으로_못_보는_갈래가_있으면_건수가_맞아도_확인_필요() -> None:
    """1751800 · 1699556 — 「…3건 이상이거나 누적 수료 인원 100명」. 금액 3건이 맞아도 갈래가 남는다."""
    company = ledger_company(*({**ROW, "seq": i} for i in range(1, 5)))
    for text in (T_1751800, T_1699556):
        rule = track(text, company)
        assert rule.status == "CHECK" and "갈래" in rule.reason, rule.reason
    # 갈래가 없는 같은 꼴은 맞으면 가능
    plain = "최근 3년 내 대학을 대상으로 수행한 AI·SW 분야 교육 중, 단일 계약금액 2,500만원 이상인 실적이 3건 이상인 자"
    assert track(plain, company).status == "PASS"


def test_컨설팅_조항에는_교육_제목_행을_세지_않고_발주처를_못_읽으면_확정하지_않는다() -> None:
    """1736492 「금융기관을 대상으로 AI거버넌스 수립 및 컨설팅 사업 수행 실적」 — DX 전환교육 2건이 맞았다."""
    edu = {"year": "2025", "title": "AI DX 전환교육 과정", "summary": "DX 전환 교육 컨설팅", "agency": "OO은행",
           "field": "기업·재직자·컨설팅", "amount_thousand_krw": 20_000, "eligible": True}
    company = ledger_company({**edu, "seq": 1}, {**edu, "seq": 2})
    text = "최근 3년 이내 국내·외 금융지주회사, 은행 등 금융기관을 대상으로 AI거버넌스 수립 및 컨설팅 사업 수행 실적을 보유한 법인"
    rule = track(text, company)
    assert rule.status == "CHECK" and "0건" in rule.reason and "금융기관" in rule.reason
    assert "전환" not in pm._DOMAIN_GROUPS["컨설팅"] and "DX" not in pm._DOMAIN_GROUPS["컨설팅"]


# --------------------------------------------------------------------------
# 3) R34S-03 예외 · 붙임 문단의 형태 낱말 · 4) R34S-04 옛 지역
# --------------------------------------------------------------------------


def test_121182_비영리_예외_문단의_사회적기업은_대상_요건이_아니다() -> None:
    req = requirements(
        "□ 지원대상 : 아래의 요건을 모두 충족하는 자\n따라 위기 소상공인으로 선별**되어 위기 알림톡을 받은 자로서,\n"
        "◦ (비영리법인 중 예외적으로 중소기업 인정)\n- 다음 중 어느 하나에 해당하는 법인은 비영리가 목적이라도 중\n"
        "소기업으로 인정되므로 소상공인정책자금 지원대상에 포함.\n① 「사회적기업 육성법」제2조제1호 및 제7조에 따라 사회적기업\n"
        "으로 인증을 받은 경우"
    )
    assert not [c for c in req.of("org_type") if c.detail["org_type"] == "사회적기업"]


def test_126473_사회연대경제_관련_비영리는_사회연대경제기업이_아니고_조건_줄은_대상이_아니다() -> None:
    req = requirements(
        "□ 지원대상\n지원대상 : 행안부형 마을기업, 전남형 예비마을기업 및 협동조합, 고용 10인 미만 사회연대경제 관련 비영리법인･단체 등\n"
        "→ 사회적기업이면서 참여대상에 해당하는 기업은 타 국비 지원 일경험 사업에 참여하고 있지 않은 경우에 한하여 참여 가능"
    )
    targets = {c.detail["org_type"] for c in req.of("org_type") if not c.detail.get("conditional")}
    assert "사회연대경제기업" not in targets and "사회적기업" not in targets
    # 대상 목록에는 없지만 「사회적기업이면서 … 경우에 한하여 참여 가능」 길이 있다 — 불가가 아니라 확인 필요(기준 답안 「센터에 함께 확인」)
    org = sas._biz_org_type(req, SAMPLEEDU)
    assert org is not None and org.status == "CHECK" and "조건" in org.reason
    only = requirements("□ 지원대상\n지원대상 : 행안부형 마을기업, 전남형 예비마을기업 및 협동조합, 고용 10인 미만 사회연대경제 관련 비영리법인･단체 등")
    assert sas._biz_org_type(only, SAMPLEEDU).status == "FAIL"


def test_125345_전남형_사업은_옛_광주_주소_회사에게_소재_해석_확인() -> None:
    req = requirements("○ 사업대상\n- 참 여 자 : 전라남도 내 거주하고 있는 신중년")
    title = "[전남광주] 2026년 전남형 신중년 사회연대경제 노동통합 모델 구축사업"
    gwangju = dataclasses.replace(SAMPLEEDU, location_old_region="광주")
    rule = sas._biz_location(req, program(title, executing_agency="전남사회적경제통합지원센터"), gwangju)
    assert rule.status == "CHECK" and "옛 전라남도" in rule.reason
    jeonnam = dataclasses.replace(SAMPLEEDU, location_old_region="전남")
    assert sas._biz_location(req, program(title), jeonnam).status == "PASS"
    # 지역 기관이 운영하는 전국 사업(122145 미래내일 — 수행기관 전남인력개발원)은 건드리지 않는다
    assert sas._biz_location(req, program("2026년 미래내일 일경험 사업 참여기업 모집 공고", executing_agency="전남인력개발원"), gwangju).status == "PASS"


OLD = "○ 신청자격\n「중소기업기본법」 제2조의 규정에 의한 중소기업으로 전남광주통합특별시 내 옛 전라남도 지역에 주사무소와 사업장을 두고"


def test_126999_옛_전라남도_지역은_회사_주소의_구로_가린다() -> None:
    req = requirements(OLD)
    assert req.of("location")[0].detail.get("old_region") == "전남"
    gwangju = dataclasses.replace(SAMPLEEDU, location_old_region="광주")
    assert sas._biz_location(req, program(), gwangju).status == "FAIL"
    jeonnam = dataclasses.replace(SAMPLEEDU, location_old_region="전남")
    assert sas._biz_location(req, program(), jeonnam).status == "PASS"
    unknown = dataclasses.replace(SAMPLEEDU, location_old_region=None)
    assert sas._biz_location(req, program(), unknown).status == "CHECK"  # 못 가리면 「맞음」으로 세지 않는다


@pytest.mark.parametrize(
    ("address", "old"),
    [
        ("전남광주통합특별시 북구 가상로 77", "광주"),
        ("전남광주통합특별시 순천시 중앙로 1", "전남"),
        ("광주광역시 광산구 하남산단", "광주"),
        ("전라남도 나주시 빛가람로", "전남"),
        ("전남광주통합특별시", None),
    ],
)
def test_주소에서_옛_광주_전남을_읽는다(address: str, old: str | None) -> None:
    assert ee._old_region_from_address(address) == old


# --------------------------------------------------------------------------
# 5) R34S-02 나열 갈래 · 같은 뜻 낱말 · 6) R34S-05 괄호 속 제외 문장
# --------------------------------------------------------------------------

AI_DOMAINS = ("AI·AX 교육 및 인력양성", "AI SaaS·소프트웨어 개발")


def test_122609_나열_갈래_중_회사_분야와_같은_뜻이_있으면_안내를_달지_않는다() -> None:
    assert sas._biz_target_industry(program(requirement_sentences=("전국 ITㆍSW 및 데이터센터 관련 기업",)), AI_DOMAINS) is None
    assert sas._biz_target_industry(program(requirement_sentences=("인공지능 기술을 보유한 기업",)), AI_DOMAINS) is None
    rule = sas._biz_target_industry(program(requirement_sentences=("바이오 및 데이터센터 관련 기업",)), AI_DOMAINS)
    assert rule is not None and rule.status == "CHECK"


def test_주어가_있는_괄호_속_제외는_제외_조항으로_남는다() -> None:
    req = requirements("□ 신청자격\n- 사회적기업(교육 · 훈련을 주 사업으로 하는 훈련기관은 제외)")
    assert req.of("exclusion")
    rule = sas._biz_exclusion(req, SAMPLEEDU)  # 샘플에듀는 프리미엄 훈련기관
    assert rule is not None and rule.status == "FAIL"
    assert requirements("□ 신청자격\n- 국세 체납 기업(제외대상)").of("exclusion")
    assert not requirements("□ 지원내용\n- 지원금 최대 2천만원(VAT 제외)").of("exclusion")


# --------------------------------------------------------------------------
# 7) 낮음
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["o 「중소기업기본법」 제2조에 따른 중소기업", "가. 「중소기업기본법」 제2조에 따른 중소기업", "(공통) 「중소기업기본법」 제2조에 따른 중소기업"],
)
def test_확인서_줄_앞_글머리는_남은_조건이_아니다(line: str) -> None:
    clauses = requirements(f"○ 신청자격\n{line}").of("sme")
    assert clauses and clauses[0].detail["clean"], line


def test_끊긴_중_소기업_확인서는_셋_다_받고_중소기업자_중_소기업은_소기업_전용() -> None:
    assert ee._sme_kind("「중소기업기본법」에 따른 중소기업자로서 「중 소기업ㆍ소상공인확인서」를 소지한 자") == "sme"
    assert ee._sme_kind("중소기업자 중 소기업자로서 중소기업·소상공인 확인서를 소지한 자") == "small"


def test_조항_지역_줄임_도_이름과_시_군_한정() -> None:
    company = dataclasses.replace(SAMPLEEDU, location_region="전남광주")
    region = ee._Clause(id="QC-02", text="", page=2, origin="입찰공고문", approx=False, kind="region")
    assert ee._judge_region(dataclasses.replace(region, text="경기 광주시 소재 업체"), company).status == "FAIL"
    # 43차 — 시험 회사 주소가 광주 북구로 정해져(실제 샘플에듀) 나주 한정은 불가 · 구를 모르면 확인 필요(H2)
    assert ee._judge_region(dataclasses.replace(region, text="전라남도 나주시에 본사를 둔 업체"), company).status == "FAIL"
    unknown = dataclasses.replace(company, location_district=None)
    assert ee._judge_region(dataclasses.replace(region, text="전라남도 나주시에 본사를 둔 업체"), unknown).status == "CHECK"
    assert ee._judge_region(dataclasses.replace(region, text="광주광역시 소재 업체"), company).status == "PASS"


def test_대출_이차보전_금액은_받는_것이_아니다() -> None:
    req = requirements(
        "□ 지원내용\n· (융자사업) 사회적기업 이차보전사업 신청시 기본한도(최대 2억원)보다 높은 최대 3억원 대출에 대한 이차보전금 지급"
    )
    assert req.of("money") == []


def test_규모_점수_이유도_반올림하면_같은_금액은_정확히() -> None:
    from app.services import opportunity_priority as op

    reason = op.scale_component(201_830_000, ceiling=200_000_000, joint_allowed=False).reason
    assert "201,830,000원" in reason and "200,000,000원" in reason


# --------------------------------------------------------------------------
# 마지막 검토(검토자 하나) — 건너뛰기 구간 · 괄호 안 서류 낱말 · 우대 · 갈래 · 매출 갈래 · 옛 지역 「구」 · 가점 · 정규식 멈춤
# --------------------------------------------------------------------------

from tests.test_support_application_v2 import DOMAINS  # noqa: E402

NO_CERT = dataclasses.replace(SAMPLEEDU, certifications=())
OLD_GWANGJU = dataclasses.replace(SAMPLEEDU, location_old_region="광주")
OLD_JEONNAM = dataclasses.replace(SAMPLEEDU, location_old_region="전남")


def gate(text: str, company) -> str:
    req = requirements(text)
    rules, indirect = sas.biz_rules_v2(program(), req, company=company, today=date(2026, 10, 12), profile_domains=DOMAINS)
    return {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}[sas.verdict_of(req, rules, indirect=indirect)[0]]


@pytest.mark.parametrize(
    "text",
    [
        "□ 지원대상 및 지원 제외 대상\n○ 지원대상: 광주광역시 소재 사회적기업, 협동조합",
        "□ 지원 제외 대상\n- 국세 체납 기업\n- 휴폐업 기업\n□ 지원대상\n○ 광주광역시 소재 사회적기업, 협동조합",
        "□ 지원대상\n※ 「광주 소재」는 본점 소재지를 의미함\n○ 광주광역시 소재 사회적기업, 협동조합",
    ],
)
def test_건너뛰기_구간은_새_절에서_끝나_지원대상_형태를_삼키지_않는다(text: str) -> None:
    assert gate(text, NO_CERT) == "불가"


@pytest.mark.parametrize(
    "line",
    [
        "○ 광주광역시 소재 기업부설연구소를 보유한 기업 (증빙: 인정서 사본 제출)",
        "○ 신청서 제출일 현재 기업부설연구소를 보유한 중소기업",
        "○ 법인 설립 후 기업부설연구소를 보유한 기업",
        "○ 광주광역시 소재 중소기업 (확인방법: 사업자등록증)\n○ 기업부설연구소를 보유한 기업",
    ],
)
def test_괄호_안_서류_낱말_제출일_설립_후는_보유_요건을_지우지_않는다(line: str) -> None:
    assert gate(f"□ 신청자격\n{line}", NO_LAB) == "불가"


@pytest.mark.parametrize(
    "tail",
    ["※ 기업부설연구소 보유기업 우대", "□ 우대사항\n○ 기업부설연구소를 보유한 기업은 우대"],
)
def test_연구소_우대는_요건이_아니다(tail: str) -> None:
    assert gate(f"□ 신청자격\n○ 광주광역시 소재 중소기업\n{tail}", NO_LAB) == "가능"


def test_다음_줄의_갈래_표시도_갈래다() -> None:
    text = "□ 신청자격\n○ 광주광역시 소재 기업으로 기업부설연구소 보유, 벤처기업, 이노비즈\n중 1개 이상에 해당하는 기업"
    assert gate(text, NO_LAB) == "확인 필요"


def test_매출_또는_인원_갈래면_매출이_못_미쳐도_불가가_아니다() -> None:
    text = "□ 신청자격\n○ 광주광역시 소재, 최근 연도 매출액 10억원 이상인 기업 또는 고용 10인 이상인 기업"
    assert gate(text, dataclasses.replace(SAMPLEEDU, revenue_krw_last_year=300_000_000)) == "확인 필요"


@pytest.mark.parametrize(
    ("line", "company"),
    [
        ("○ 전남광주통합특별시 북구 전남대학교 일원 소재 기업", OLD_GWANGJU),
        ("○ 전남광주통합특별시 소재 기업(구 광주테크노파크 입주기업 포함)", OLD_JEONNAM),
        ("○ 전남광주통합특별시 소재 중소기업\n※ 옛 전라남도 지역 소재 기업은 가점 2점 부여", OLD_GWANGJU),
    ],
)
def test_낱_구_이름_끝글자_기관_옛이름_가점_줄은_옛_지역_요건이_아니다(line: str, company) -> None:
    assert gate(f"□ 신청자격\n{line}", company) == "가능"


def test_광주_전남_둘_다_제외는_옛_지역_한쪽이_아니다() -> None:
    assert extractor._old_region("전남광주통합특별시 소재 기업(광주·전남 제외)") is None
    assert extractor._old_region("전남광주통합특별시 내 옛 전라남도 지역") == "전남"
    assert extractor._old_region("전남광주통합특별시(광주 제외)") == "전남"


def test_나열_분야_정규식은_띄어쓰기_없는_긴_줄에서_멈추지_않는다() -> None:
    import time

    started = time.perf_counter()
    sas._FIELD_LIST_RE.search(("사과와배과" * 40)[:200])
    assert time.perf_counter() - started < 0.5
    assert sas._FIELD_SPLIT_RE.split(sas._FIELD_LIST_RE.search("ITㆍSW 및 데이터센터 관련 기업").group(1)) == ["IT", "SW", "데이터센터"]


def test_127455_대상이_소재_공방이면_소재만_맞았다고_가능으로_닫지_않는다() -> None:
    """10-31 최종 점검 E6 — 「구 광주광역시 … 소재 공방」(+ 디자인 전문기업 1:1 컨소시엄)이 소재 하나로 거짓 「가능」이었다.
    대상 문장이 「공방」으로 끝나 「○○ 기업」 꼴만 찾던 규칙에 걸리지 않았다."""
    rule = sas._biz_target_industry(program(requirement_sentences=("공고일 기준, 구 광주광역시 관할지역(5개 자치구) 소재 공방",)), AI_DOMAINS)
    assert rule is not None and rule.status == "CHECK" and "공방" in rule.reason
    assert sas._biz_target_industry(program(requirement_sentences=("공방전 형식의 토론 교육을 운영하는 AI 교육 기업",)), AI_DOMAINS) is None
