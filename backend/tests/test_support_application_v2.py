"""「가능」은 회사 사실이 맞았을 때만 (0925.md §4-A · §4-B · ISSUE-096 · 097).

## 왜 이 파일이 있나

10차는 공고문을 읽고 판정했는데 **「못 찾으면 가능」**이었다. 30일 목록의 「가능」 60건 중
44건에 회사 사실과 맞은 요건이 하나도 없었고, 장애인 창업 컨설팅이 통합 9위 「우선 검토」로
올라왔다(재검증 §3). CLAUDE.md §11 「Evidence 가 없는데 충족 판정 금지」에 어긋난다.

여기 있는 따옴표 안의 글은 전부 **공고문 원문**이다(재검증 §3 표의 file:line).
문장을 지어내면 검사가 스스로를 속인다.
"""

from __future__ import annotations

import dataclasses

import json
from datetime import date
from pathlib import Path

import pytest

from app.schemas.business_opportunity import SupportProgram
from app.services import bizinfo_document_store as store
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from app.services.eligibility_engine import CompanyFacts

TODAY = date(2026, 9, 18)

#: 샘플에듀 — **상시근로자 수·매출·연구소·데이터 상품은 미입력이다** (0925 §2).
SAMPLEEDU = CompanyFacts(
    from_real_company=True,
    certifications=("사회적기업", "데이터바우처 공급기업", "프리미엄 훈련기관"),
    location_region="전남광주",
    # 43차 BIZ-16 — 「광주광역시」 소재는 회사 옛 지역(광주 북구)을 본다 — 실제 샘플에듀 주소와 같게
    location_old_region="광주",
    location_district="북구",
    founded_year=2021,
    employee_count=None,
    completed_programs=("없음 확인 — 선행 정부과제 수행 이력이 없다",),
)
DOMAINS = ("AI·AX 교육 및 인력양성", "AI SaaS·소프트웨어 개발")


def program(title: str = "시험 공고", **fields) -> SupportProgram:
    # 접수 기간은 **상시**로 둔다. 그러지 않으면 BIZ-PERIOD 가 「종료일을 읽지 못했다」로
    # 확인 필요가 되어, 이 파일이 재려는 «대상 요건» 판정이 그것에 가린다.
    base = dict(
        id="bizinfo-TEST", title=title, agency="한국인터넷진흥원",
        apply_period_text="상시 접수", apply_period_kind="always_open",
    )
    base.update(fields)
    return SupportProgram(**base)  # type: ignore[arg-type]


def verdict(text: str, *, title: str = "시험 공고", **fields) -> tuple[str, str]:
    """공고문 한 덩어리로 판정한다. `(가능/확인 필요/불가, 사유)`."""
    requirements = extractor.extract_from_text("P", store.join_pages([text]))
    rules, indirect = sas.biz_rules_v2(
        program(title, **fields), requirements, company=SAMPLEEDU, today=TODAY, profile_domains=DOMAINS
    )
    gate, reason = sas.verdict_of(requirements, rules, indirect=indirect)
    return ("간접" if indirect else {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}[gate]), reason


# --------------------------------------------------------------------------
# §4-A-1 — 종합 규칙
# --------------------------------------------------------------------------


def test_막는_것도_맞는_것도_없으면_가능이_아니다() -> None:
    """10차의 기본값은 「가능」이었다. 근거 없는 확정이다 (CLAUDE.md §11)."""
    got, reason = verdict("○ 지원대상\n- 전국 소재 중소기업\n○ 지원내용\n- 컨설팅 제공")
    assert got == "확인 필요"
    assert sas.UNCONFIRMED_PREFIX in reason
    # **사유에 지원대상 절 원문이 인용된다.**
    assert "전국 소재 중소기업" in reason


def test_지원대상_절을_못_찾으면_그렇게_적는다() -> None:
    got, reason = verdict("1. 사업 개요\n○ 사업명 : 시험 사업\n○ 사업기간 : 2026년")
    assert got == "확인 필요"
    assert reason == sas.UNCONFIRMED_NO_SECTION


def test_회사_사실이_맞으면_가능이고_사유에_그_사실이_있다() -> None:
    # 43차 M20 — 「디지털 제품 보유」는 사업영역 낱말이 아니라 회사가 적은 **제품 이름**이 있을 때만 맞는다
    got, reason = verdict("○ 지원대상 : 디지털 제품(서비스)를 보유한 광주광역시 본사소재 기업")
    assert got == "확인 필요" and "디지털 제품" in reason
    with_product = dataclasses.replace(SAMPLEEDU, digital_products=("BidPilot AI(공공입찰 지원 SaaS)",))
    requirements = extractor.extract_from_text("P", store.join_pages(["○ 지원대상 : 디지털 제품(서비스)를 보유한 광주광역시 본사소재 기업"]))
    rules, indirect = sas.biz_rules_v2(program("시험 공고"), requirements, company=with_product, today=TODAY, profile_domains=DOMAINS)
    gate, reason = sas.verdict_of(requirements, rules, indirect=indirect)
    assert gate == "PASS" and ("광주광역시" in reason or "BidPilot" in reason)


def test_막는_규칙이_있으면_불가다() -> None:
    got, _ = verdict("○ 지원대상 : 광주시와 업무협약체결하고 광주시에서 사업을 개시한 AI유치기업")
    assert got == "불가"


# --------------------------------------------------------------------------
# §4-A-7 — 재검증 §3 표의 여덟 건. **공고문 원문 그대로**다.
# --------------------------------------------------------------------------


def test_장애인_창업_컨설팅은_가능이_아니다() -> None:
    """118350 — 27~29행이 「장애인등록증을 발급받은 자」, 40행은 **제외 목록**이다.

    10차는 40행 괄호 안의 「비영리사회적기업」에서 「사회적기업」을 부분 문자열로 읽어
    「회사가 갖고 있다」고 판정했다.
    """
    got, reason = verdict(
        "2\n신청자격\n□ 지원대상\n"
        "◦ (장애인) 「장애인복지법」 제32조에 따른 장애인등록증을 발급받은 자\n"
        "◦ (예비창업자) 모집 공고일 기준 창업을 준비하는 자로서, 사업자 등록하지 않은 자\n"
        "< 지원 제외 대상 >\n"
        "◦ 비영리사업(비영리 개인사업자와 법인사업자)\n"
        "* 「상법」에 의한 회사로서 「소득세법」 제168조의 적용을 받지 않는 사업"
        "(비영리사회적기업, 어린이집, 장기요양센터 등)"
    )
    assert got != "가능"
    assert "사회적기업" not in reason, "제외 목록의 낱말을 요건으로 읽었다"


def test_인증제품_보유는_회사_쪽_값이라_확인_필요다() -> None:
    """126159 벤처나라 — 34행. 인증제품 보유 여부는 회사자료에 없다."""
    got, _ = verdict(
        "○ (신청자격) 창업기업 또는 벤처기업이 직접 생산하거나 국내 제조 기업과 계약한 정보보호 인증제품"
    )
    assert got != "가능"


def test_소상공인만_대상이면_상시근로자_수로_판정한다() -> None:
    """124697 — 8차는 「소상공인만 → 불가」였다. 근거 없는 확정이었다 (0925 §4-A-3)."""
    got, reason = verdict(
        "○ 지원대상 : 소상공인\n- 소상공인에게 현장 맞춤형 컨설팅을 제공",
        target="소상공인",
    )
    assert got == "확인 필요"
    assert "상시 근로자" in reason
    # 회사가 적으면 판정된다.
    requirements = extractor.extract_from_text("P", store.join_pages(["○ 지원대상 : 소상공인"]))
    small = CompanyFacts(from_real_company=True, location_region="전남광주", employee_count=3)
    rules, _ = sas.biz_rules_v2(
        program(target="소상공인"), requirements, company=small, today=TODAY, profile_domains=DOMAINS
    )
    rule = next(r for r in rules if r.rule_id == "BIZ-SMALL-BUSINESS")
    assert rule.status == "PASS" and "3명" in rule.reason


def test_다른_사업의_선정업소만_신청할_수_있으면_불가다() -> None:
    """117367 강진군 밀키트 — 23행. 회사는 선행 사업 「없음 확인」이다."""
    got, reason = verdict(
        "3\n신청자격 및 제한\n 신청자격\n"
        "󰁾 강진군 밀키트 사업 선정업소로 (식육)즉석판매제조가공업 영업 신고 및 사업자등록 되어 있는 업소"
    )
    assert got == "불가"
    assert "선정 업소" in reason


def test_교육생_모집은_가능이_아니다() -> None:
    """126458 — 3행이 「교육생 모집요강」이다. 회사가 신청하는 사업이 아니다."""
    got, _ = verdict("교육생 모집요강\n○ 모집대상 : 공예 분야 종사자 및 예비 창업자")
    assert got != "가능"


def test_전국_소재_의료기기_개발_기업은_가능이_아니다() -> None:
    """126331 — 22행. 「전국 소재」라 소재는 막지 않지만 회사 사실과 맞은 요건이 없다."""
    got, reason = verdict("라. 지원대상 : 전국 소재 AI 융합 에스테틱 의료기기 개발 기업")
    assert got == "확인 필요"
    assert "에스테틱 의료기기" in reason


def test_수행기관이_다른_시도면_확인_필요다() -> None:
    """118729 창업-BuS at 경북 — 소관은 중기부, 수행이 경북창조경제혁신센터다."""
    got, reason = verdict(
        "○ (모집대상) 초격차 10대 분야에 해당되는 창업 후 7년 이내 기업",
        title="2026년 창업-BuS at 경북 참여기업 모집 공고",
        agency="중소벤처기업부",
        executing_agency="경북창조경제혁신센터",
    )
    assert got == "확인 필요"
    assert "경북창조경제혁신센터" in reason


def test_전국_사업을_수행기관_지역으로_막지_않는다() -> None:
    """126482 — 서울창조경제혁신센터가 운영하는 **전국** 사업이다. 공고명에 서울이 없다."""
    got, _ = verdict(
        "○ 모집대상 : 「중소기업창업 지원법」에 따른 모집공고일 기준 창업 7년 이내인 창업기업",
        title="민관협력 오픈이노베이션 지원 공공데이터 활용 지원 공공기관 제안형 (Top-Down)",
        agency="중소벤처기업부",
        executing_agency="서울창조경제혁신센터",
    )
    assert got == "가능"


def test_수수료와_보증한도를_받는_것으로_읽지_않는다() -> None:
    """120566 지식재산 경영인증 — 20·22·64행. 셋 다 받는 것이 아니다 (0925 §4-C-2)."""
    text = (
        "□ 신청대상 : 중소기업기본법 제2조에 따른 중소기업\n"
        "□ 신청수수료 : 33만원(VAT포함)\n"
        "* 최종심사 탈락 기업 당해 연도 재신청 시 1회에 한해 수수료 무료 및 당해 연도 이후\n"
        "‣ 지점장 전결 보증한도 10억원~30억원 확대(신용등급별 차등)"
    )
    requirements = extractor.extract_from_text("P", store.join_pages([text]))
    assert requirements.of("money") == []
    meaning = sas.company_meaning_line(program(), requirements, indirect=None, gate="CHECK")
    assert meaning is not None
    assert "무료" not in meaning and "10억" not in meaning and "자부담 없음" not in meaning


def test_자부담_없음은_공고문이_적었을_때만이다() -> None:
    """「무료」가 있다고 「자부담 없음」을 지어내지 않는다 (0925 §4-C-2)."""
    without = extractor.extract_from_text(
        "P", store.join_pages(["○ 지원내용\n- 웹 취약점 테스트 (무료)"])
    )
    assert "자부담 없음" not in (sas.company_meaning_line(program(), without, indirect=None, gate="PASS") or "")

    with_text = extractor.extract_from_text(
        "P", store.join_pages(["○ 지원내용\n- 사업화 자금 지원 · 자부담 의무 없음"])
    )
    assert "자부담 없음" in (sas.company_meaning_line(program(), with_text, indirect=None, gate="PASS") or "")


# --------------------------------------------------------------------------
# §4-A-7 — **가능이 유지돼야 하는 넷**. 사유에 회사 사실이 이름으로 있어야 한다.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, fact",
    [
        (
            # 조건 없는 인원 예외(122145 꼴). 「지침상 인정 요건 충족 시」처럼 조건이 붙은 예외는 확인 필요다(「가능」 좁히기 10-10)
            "○ 참여기업 자격\n고용보험 피보험자 수 10인 이상 기업, 공공기관, 지방공기업,\n"
            "다만, 고용보험 피보험자수 10인 미만의 기업이라도 다음의 기업은 참여 가능 ③ 사회적기업 육성법에 따른 사회적기업",
            "사회적기업",
        ),
        ("○ 모집대상 : 모집공고일 기준 창업 7년 이내인 창업기업", "창업 7년"),
    ],
)
def test_가능은_회사_사실을_이름으로_적는다(text: str, fact: str) -> None:
    got, reason = verdict(text)
    assert got == "가능"
    assert fact in reason


# --------------------------------------------------------------------------
# §4-B — 두 화면이 같은 판정을 낸다
# --------------------------------------------------------------------------

CACHE = Path(__file__).resolve().parents[2] / "data" / "private" / "cache" / "bizinfo" / "bizinfo_cache.json"

#: 두 화면을 견줄 다섯 건 (0925 §4-B-3).
COMPARE = {
    "PBLN_000000000123852": "A1 디지털 품질관리",
    "PBLN_000000000118350": "장애인 창업 컨설팅",
    "PBLN_000000000125426": "A3 미래내일 인턴형",
    "PBLN_000000000126347": "광양 실증 (간접)",
    "PBLN_000000000125978": "Multi AI Agent (불가)",
}


@pytest.mark.skipif(not CACHE.exists(), reason="기업마당 캐시가 없는 환경 (비공개 자료)")
def test_목록과_신청_분석이_같은_판정을_낸다() -> None:
    """**같은 함수**가 판정하므로 점수·판정·「회사에 뜻하는 것」이 글자까지 같다 (0925 §4-B-3).

    두 화면을 실제로 부르는 대신 **두 화면이 부르는 함수**를 같은 입력으로 두 번 부른다 —
    경로가 하나뿐이라는 것이 이 검사의 뜻이다.
    """
    from app.services import bizinfo_service, company_service, eligibility_engine

    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    items = {i["pblancId"]: i for i in raw.get("items", []) if isinstance(i, dict)}
    company = eligibility_engine.company_facts_for("org-sample")
    profile = company_service.load_profile("org-sample")
    for program_id, name in COMPARE.items():
        if program_id not in items:
            pytest.skip(f"캐시에 {name} 이 없다")
        mapped = bizinfo_service.map_program(items[program_id])
        fit = bizinfo_service.support_fit(mapped, today=TODAY, organization_id="org-sample")
        first = sas.judge(mapped, fit, company=company, profile=profile, source="cached", today=TODAY)
        second = sas.judge(mapped, fit, company=company, profile=profile, source="cached", today=TODAY)
        assert (first.score, first.verdict, first.company_meaning) == (
            second.score,
            second.verdict,
            second.company_meaning,
        ), name


@pytest.mark.skipif(not CACHE.exists(), reason="기업마당 캐시가 없는 환경 (비공개 자료)")
def test_판정이_바뀌어야_하는_여덟_건은_가능이_아니다() -> None:
    """재검증 §3 표 여덟 건을 **받아 둔 공고문 그대로** 다시 잰다 (0925 §4-A-7)."""
    from app.services import bizinfo_service, company_service, eligibility_engine

    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    items = {i["pblancId"]: i for i in raw.get("items", []) if isinstance(i, dict)}
    company = eligibility_engine.company_facts_for("org-sample")
    profile = company_service.load_profile("org-sample")
    negatives = {
        "PBLN_000000000118350": "장애인 창업 컨설팅",
        "PBLN_000000000126159": "정보보호 인증제품 벤처나라",
        "PBLN_000000000120566": "지식재산 경영인증",
        "PBLN_000000000124697": "소상공인 현장 맞춤형 컨설팅",
        "PBLN_000000000117367": "강진군 밀키트 장비",
        "PBLN_000000000126458": "공예 온라인 유통·AI 교육생",
        "PBLN_000000000126331": "AI 융합 에스테틱 의료기기",
        "PBLN_000000000118729": "창업-BuS at 경북",
    }
    checked = 0
    # 캐시(자료)에 없는 공고는 판정할 항목이 없다 — 「자료에 없음」. 9-29 캐시 교체(28차 · 담당자 결정)로
    # 126159 · 126458 · 126331 이 목록에서 빠졌다. 캐시에 있는 것은 **하나도 빼지 않고** 잰다(아래 등식).
    missing = [name for program_id, name in negatives.items() if program_id not in items]
    for program_id, name in negatives.items():
        if program_id not in items:
            continue
        assert store.load_text(program_id), f"{name}: 캐시에 있는데 받아 둔 공고문이 없다"
        mapped = bizinfo_service.map_program(items[program_id])
        fit = bizinfo_service.support_fit(mapped, today=TODAY, organization_id="org-sample")
        result = sas.judge(mapped, fit, company=company, profile=profile, source="cached", today=TODAY)
        assert result.verdict != "가능", f"{name}: {result.gate_reason}"
        checked += 1
    assert checked == len(negatives) - len(missing), f"캐시에 있는 것을 다 재지 않았다 ({checked}건 · 자료에 없음 {missing})"
    # 최신화하면 마감된 공고가 목록에서 빠진다 — 하한은 「있는 만큼」이고 하나도 없으면 잴 것이 없다(33차 · 절차서 §2)
    if checked == 0:
        pytest.skip(f"여덟 건 모두 지금 저장본에 없음 — 자료에 없음 {missing}")
