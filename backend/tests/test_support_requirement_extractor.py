"""기업마당 **공고문 조항 추출**과 판정 v2 (0924.md §4-A · ISSUE-096).

검수자가 공고문 26건을 직접 읽어 만든 기준 답안
(`docs/reports/2026-09-24_bizinfo_candidates.md`)의 **실제 문장**을 그대로 넣어 잰다.
문장을 지어내면 검사가 스스로를 속인다 — 여기 있는 따옴표 안의 글은 전부 원문이다.

여기서 지키는 약속 셋.

1. **원문 그대로 인용한다.** `source_text` 는 공고문 문장이지 요약이 아니다.
2. **못 찾은 조항은 「없음」이 아니다.** 판정은 「확인 필요」로 가고 「가능」이 되지 않는다.
3. **막는 문장을 요건으로 읽지 않는다.** 「… 공급기업으로 선정된 기업(은 신청 불가)」이
   「공급기업 등록이 필요하다」가 되면 판정이 거꾸로 선다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.schemas.business_opportunity import SupportProgram
from app.services import bizinfo_document_store as store
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from app.services.eligibility_engine import CompanyFacts

TODAY = date(2026, 9, 18)

#: 샘플에듀 — 인증 사회적기업 · 2021 설립 · 광주 북구 본사 · 프리미엄 훈련기관.
#: 상시근로자 수·매출·연구소 보유 여부는 **미입력**이다 (0924 §2).
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
    base = dict(id="bizinfo-TEST", title=title, agency="한국인터넷진흥원")
    base.update(fields)
    return SupportProgram(**base)  # type: ignore[arg-type]


def document(*pages: str) -> str:
    return store.join_pages(pages)


# --------------------------------------------------------------------------
# 조항 추출
# --------------------------------------------------------------------------


def test_소재_요건을_원문_그대로_뽑는다() -> None:
    text = document("○ 지원대상 : 디지털 제품(서비스)를 보유한 광주광역시 본사소재 기업")
    result = extractor.extract_from_text("P1", text)
    location = result.of("location")
    assert location, "「광주광역시 본사소재」를 못 찾았다"
    assert location[0].detail["region"] == "전남광주"
    # **원문 그대로다.** 요약·의역하지 않는다 (0924 §3-14).
    assert location[0].source_text == "지원대상 : 디지털 제품(서비스)를 보유한 광주광역시 본사소재 기업"
    assert result.of("prerequisite")[0].detail["requirement"] == "digital_product"


def test_자격_절_밖의_지역_이름은_소재_요건이_아니다() -> None:
    """안내문에 스친 지역 이름을 요건으로 읽으면 근거 없이 「불가」가 된다."""
    text = document(
        "1. 사업 개요\n○ 운영기관 : 경상북도 포항테크노파크에 사무국을 둔다\n○ 지원규모 : 10개사"
    )
    assert extractor.extract_from_text("P2", text).of("location") == []


def test_고용을_가리키는_낱말이_없으면_인원_요건이_아니다() -> None:
    """신청 흐름도의 「➊ … 10인 이상」 같은 줄이 고용 요건으로 잡히던 자리다."""
    fake = document("○ 신청자격\n지원 사업 흐름도 ➊ 접속 → ❷ 10인 이상 항목 선택 → ❸ 제출")
    assert extractor.extract_from_text("P3", fake).of("headcount") == []

    real = document("○ 신청자격\n고용보험 피보험자 수 10인 이상 기업, 공공기관, 지방공기업,")
    found = extractor.extract_from_text("P4", real).of("headcount")
    assert [c.detail["count"] for c in found] == [10]


def test_한_줄에_인원_기준이_둘이면_둘_다_뽑는다() -> None:
    """다른 숫자의 기준 둘이 한 줄에 오면 둘 다 읽는다 — 앞의 것만 읽으면 기준이 사라진다."""
    text = document("○ 사업대상\n- 참여기업 : 상시 근로자 5인 이상 50인 미만 기업")
    found = {(c.detail["count"], c.detail["comparator"]) for c in extractor.extract_from_text("P5", text).of("headcount")}
    assert found == {(5, "이상"), (50, "미만")}


def test_같은_숫자의_미만_이상에_비율이_붙으면_배정_비율이다() -> None:
    """125345 「근로자 5인 미만 기업(70%), 5인 이상 기업(30%)」 — 선정 몫을 나눈 비율이지 인원 요건이 아니다(35차 R34-DATA-04)."""
    text = document("○ 사업대상\n- 참여기업 : 근로자 5인 미만 기업(70%), 5인 이상 기업(30%)")
    assert extractor.extract_from_text("P5", text).of("headcount") == []


def test_제외_목록의_항목에는_제외라는_말이_없다() -> None:
    """머리글에만 「제외」가 있고 항목에는 없다. 회사를 막는 바로 그 줄이 거기 있다."""
    text = document(
        "2. 아래 지원 제외 항목에 해당하지 않는 기업\n"
        "- 최근 5년 이내 부정 훈련 처분 이력이 있는 기업\n"
        "- 교육·훈련을 주 사업으로 하는 훈련기관 또는 회원사를 관리하는 협회·단체"
    )
    quotes = [c.source_text for c in extractor.extract_from_text("P6", text).of("exclusion")]
    assert any("교육·훈련을 주 사업으로 하는 훈련기관" in q for q in quotes)


def test_막는_문장을_보유_요건으로_읽지_않는다() -> None:
    """「… 공급기업으로 선정된 기업」은 중복지원 제한이지 「공급기업 등록이 필요하다」가 아니다."""
    text = document("○ 신청자격\n○ 당해연도 ICT 중소기업 정보보호 지원 사업 공급기업으로 선정된 기업은 제외")
    assert extractor.extract_from_text("P7", text).of("prerequisite") == []


def test_이미지_공고문은_읽지_못했다고_적는다() -> None:
    """OCR 을 쓰지 않는다. 못 읽은 것을 읽은 척하지 않는다."""
    result = extractor.load("없는공고id")
    assert result.document_read is False
    assert result.document_note and "기업마당 요약" in result.document_note
    assert result.clauses == []


# --------------------------------------------------------------------------
# 판정 v2
# --------------------------------------------------------------------------


def judge(text: str, *, title: str = "시험 공고", **fields):
    requirements = extractor.extract_from_text("P", document(text))
    return sas.biz_rules_v2(
        program(title, **fields), requirements, company=SAMPLEEDU, today=TODAY, profile_domains=DOMAINS
    )


def status_of(rules, rule_id: str) -> str | None:
    return next((r.status for r in rules if r.rule_id == rule_id), None)


def test_광주_소재_요건은_가능이다() -> None:
    rules, indirect = judge("○ 지원대상 : 디지털 제품(서비스)를 보유한 광주광역시 본사소재 기업")
    assert status_of(rules, "BIZ-LOCATION") == "PASS"
    assert indirect is None


def test_전라남도_요건은_통합_이후_해석을_확인한다() -> None:
    """광주 북구가 「전라남도 소재」에 드는지는 **사람이 센터에 확인할 일**이다 (0924 §2)."""
    rules, _ = judge("○ 신청자격 : 공고일 이전부터 전라남도에 소재한 사회연대경제기업")
    rule = next(r for r in rules if r.rule_id == "BIZ-LOCATION")
    assert rule.status == "CHECK"
    assert "해석" in rule.reason
    assert rule.unlock_condition and "센터" in rule.unlock_condition


def test_다른_시군_소재_요건은_불가다() -> None:
    rules, _ = judge("○ (신청자격) 광양시 소재 제조 공장을 보유한 중소·중견기업")
    assert status_of(rules, "BIZ-LOCATION") == "FAIL"


def test_사회적기업_요건은_인증으로_가능이다() -> None:
    rules, _ = judge(
        "○ 참여 대상\n- ｢사회적기업 육성법｣에 따른 (예비)사회적기업\n- 행안부형 마을기업"
    )
    assert status_of(rules, "BIZ-ORG-TYPE") == "PASS"


def test_비영리법인만_대상이면_불가다() -> None:
    rules, _ = judge("○ 지원대상 : 고용 10인 미만 사회연대경제 관련 비영리법인･단체")
    # 「사회연대경제 **관련** 비영리법인 · 단체」는 사회연대경제기업이 아니다 — 비영리만 대상이다(35차 R34S-03 · 126473).
    assert status_of(rules, "BIZ-ORG-TYPE") == "FAIL"
    rules, _ = judge("○ 지원대상 : 사회연대경제기업")
    assert status_of(rules, "BIZ-ORG-TYPE") == "PASS"  # 사회연대경제기업은 사회적기업을 아우르는 이름이라 회사가 든다

    rules, _ = judge("○ 지원대상 : 광주시와 업무협약체결하고 광주시에서 사업을 개시한 AI유치기업")
    assert status_of(rules, "BIZ-ORG-TYPE") == "FAIL"


def test_인원_요건에_예외가_있으면_사회적기업은_가능이다() -> None:
    rules, _ = judge(
        "○ 참여기업 자격\n고용보험 피보험자 수 10인 이상 기업, 공공기관, 지방공기업,\n"
        "다만, 고용보험 피보험자수 10인 미만의 기업이라도 다음의 기업은 참여 가능 ③ 사회적기업 육성법에 따른 사회적기업"
    )
    assert status_of(rules, "BIZ-HEADCOUNT") == "PASS"


def test_조건이_붙은_인원_예외는_인증만으로_닫지_않는다() -> None:
    """「지침상 인정 요건 충족 시 10인 미만 기업도 참여 가능」(125426) — 「가능」 좁히기(10-10 담당자 결정)."""
    rules, _ = judge(
        "○ 참여기업 자격\n고용보험 피보험자 수 10인 이상 기업, 공공기관, 지방공기업,\n"
        "지침상 인정 요건 충족 시 10인 미만 기업도 참여 가능"
    )
    rule = next(r for r in rules if r.rule_id == "BIZ-HEADCOUNT")
    assert rule.status == "CHECK" and "조건이 붙어 있습니다" in rule.reason


def test_인원_요건에_예외가_없으면_확인_필요다() -> None:
    """회사 상시 근로자 수가 **미입력**이다. 「없다」고 단정하지 않는다."""
    rules, _ = judge("○ 신청자격\n상시고용 5명 이상인 기업")
    rule = next(r for r in rules if r.rule_id == "BIZ-HEADCOUNT")
    assert rule.status == "CHECK"
    assert rule.unlock_condition and "상시 근로자" in rule.unlock_condition


def test_창업_연차는_설립_연도로_잰다() -> None:
    rules, _ = judge("○ 신청자격 : 모집공고일 기준 창업 7년 이내인 창업기업")
    assert status_of(rules, "BIZ-AGE") == "PASS"
    rules, _ = judge("○ 신청자격 : 공고일 기준 창업 3년 이내 초기 창업기업")
    assert status_of(rules, "BIZ-AGE") == "FAIL"


def test_선행과제_없음을_확인했으면_불가다() -> None:
    """빈 목록은 「모른다」이고, 「없음 확인」은 **확인된 사실**이다 (0924 §4-A-4)."""
    text = "○ 신청자격\n접수 마감일 기준, 스마트제조혁신R&D 최종평가 결과 완료판정(60점 이상) 과제 수행기관"
    rules, _ = judge(text)
    assert status_of(rules, "BIZ-PREREQ") == "FAIL"

    unknown = CompanyFacts(from_real_company=True, location_region="전남광주", founded_year=2021)
    requirements = extractor.extract_from_text("P", document(text))
    rules, _ = sas.biz_rules_v2(program(), requirements, company=unknown, today=TODAY, profile_domains=DOMAINS)
    assert status_of(rules, "BIZ-PREREQ") == "CHECK", "모르는 것을 「불가」로 단정하면 안 된다"


def test_훈련기관_제외_조항은_회사를_막는다() -> None:
    rules, _ = judge(
        "2. 아래 지원 제외 항목에 해당하지 않는 기업\n"
        "- 교육·훈련을 주 사업으로 하는 훈련기관 또는 회원사를 관리하는 협회·단체"
    )
    rule = next(r for r in rules if r.rule_id == "BIZ-EXCLUSION")
    assert rule.status == "FAIL"
    assert "훈련기관" in rule.source


def test_운영기관_모집은_기업_지원사업이_아니다() -> None:
    """37차 D5(담당자 결정 2026-10-14) — 불가(숨김)가 아니라 「수행기관 모집(매출)」 · 확인 필요."""
    rules, _ = judge("○ 지원대상 : 협업부처 추천을 받은 공공·민간기관", title="2027년 스마트공장 구축지원사업 주관기관 모집")
    assert status_of(rules, "BIZ-ROLE") == "CHECK"
    assert next(r for r in rules if r.rule_id == "BIZ-ROLE").reason.startswith("수행기관 모집(매출)")


def test_도입기업이_신청하면_회사는_간접이다() -> None:
    """신청 주체가 될 수 없다고 목록에서 지우지 않는다 — 들어가는 길을 적는다."""
    rules, indirect = judge(
        "○ 지원대상\n기존 스마트서비스 도입기업이 기술기업과 컨소시엄을 구성하여 신청",
        title="2026년 중소기업 스마트서비스 지원사업 참여기업 모집",
    )
    assert indirect == "간접(기술기업)"
    assert all(r.status != "FAIL" for r in rules)


def test_소관기관이_다른_시도면_확인_필요다() -> None:
    rules, _ = judge("○ 지원대상 : 전국 IT·SW 기업", agency="경상북도")
    rule = next(r for r in rules if r.rule_id == "BIZ-LOCATION")
    assert rule.status == "CHECK"
    assert "경상북도" in rule.reason


# --------------------------------------------------------------------------
# 회사에 뜻하는 것 · 순위 신호
# --------------------------------------------------------------------------


def test_회사에_뜻하는_것은_역할과_받는_것과_마감을_한_줄로() -> None:
    # 돈은 **지원내용 절**에서만 읽는다 (0925 §4-C-2) — 절 제목을 함께 넣는다.
    requirements = extractor.extract_from_text(
        "P",
        document(
            "○ 지원대상 : 광주광역시 본사소재 기업\n○ 지원내용\n- 웹 애플리케이션 취약점 테스트 (무료)"
        ),
    )
    line = sas.company_meaning_line(
        program(apply_end=date(2026, 10, 30)), requirements, indirect=None, gate="PASS"
    )
    assert line and "무료" in line and "10월 30일 마감" in line


def test_순위_신호는_회사_사실이_맞았는지를_가린다() -> None:
    requirements = extractor.extract_from_text(
        "P", document("○ 참여 대상\n- ｢사회적기업 육성법｣에 따른 (예비)사회적기업")
    )
    rules, indirect = sas.biz_rules_v2(
        program(), requirements, company=SAMPLEEDU, today=TODAY, profile_domains=DOMAINS
    )
    signals = sas.clause_signals(requirements, rules, indirect=indirect)
    assert signals["read"] is True
    assert signals["company_match"] is True
    assert "BIZ-ORG-TYPE" in signals["matched_rules"]


def test_회사_쪽_값이_없어_확인_필요인_것을_따로_센다() -> None:
    """「전화 한 통이면 풀리는 확인」과 「회사가 아직 못 갖춘 것」은 다른 일이다 (0924 §4-B-1)."""
    requirements = extractor.extract_from_text(
        "P", document("○ 신청자격 : 기업부설연구소 또는 연구개발전담부서를 보유한 중소기업")
    )
    rules, indirect = sas.biz_rules_v2(
        program(), requirements, company=SAMPLEEDU, today=TODAY, profile_domains=DOMAINS
    )
    signals = sas.clause_signals(requirements, rules, indirect=indirect)
    # 36차 R35-DV-01 — 연구소 문장 안의 「중소기업」도 확인서 조항이다(확인서 「모름」이라 회사 쪽 확인이 하나 더)
    assert signals["company_side_checks"] == ["BIZ-SME", "BIZ-PREREQ"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("○ 지원내용\n- 웹 취약점 테스트 (무료)", "free"),
        ("○ 지원내용\n- 과제별 최대 1억원 사업화 자금", "large"),
        ("○ 기업지원금 월 130만원 지급", "small"),
    ],
)
def test_받는_것의_크기를_원문에서_읽는다(text: str, expected: str) -> None:
    """**지원내용 절이나 「지원·지급」 문장에서만** 읽는다 (0925 §4-C-2)."""
    requirements = extractor.extract_from_text("P", document(text))
    rules, _ = sas.biz_rules_v2(program(), requirements, company=SAMPLEEDU, today=TODAY)
    assert sas.clause_signals(requirements, rules, indirect=None)["benefit"] == expected


# --------------------------------------------------------------------------
# 0925 §4-C — 제외 절의 열거와 돈이 아닌 숫자 (ISSUE-098 · 099)
#
# 아래 따옴표 안은 실제 공고문 줄이다. 파일·행 번호를 적어 둔다 — 다음 사람이
# 원문을 열어 대조할 수 있어야 하고, 그래야 이 검사가 스스로를 속이지 않는다.
# --------------------------------------------------------------------------

#: `data/private/bizinfo_docs/PBLN_000000000118350.txt` 38~40행.
#: 장애인 창업 컨설팅 공고의 **지원 제외 대상** 절이다. 10차는 이 40행에서
#: 「사회적기업」을 읽어 조직 형태 요건으로 삼았고, 샘플에듀가 인증 사회적기업이라
#: 「가능 · 사회적기업 요건이 맞습니다」가 됐다. **막는 문장을 요건으로 읽은 것**이다.
EXCLUSION_118350 = (
    "< 지원 제외 대상 >\n"
    "◦ 비영리사업(비영리 개인사업자와 법인사업자)\n"
    "* 「상법」에 의한 회사로서 「소득세법」 제168조 또는 「부가가치세법」 제5조의 "
    "규정의 적용을 받지 않는 사업(비영리사회적기업, 어린이집, 장기요양센터 등)"
)


def test_제외_절의_괄호_열거는_조직_형태_요건이_아니다() -> None:
    """118350 40행 (0925 §4-C-1). 제외 절에서는 조직 형태를 뽑지 않는다."""
    requirements = extractor.extract_from_text("P", document(EXCLUSION_118350))
    assert requirements.of("org_type") == [], [c.label for c in requirements.of("org_type")]
    # 제외 조항 자체는 남는다 — 「없다」가 아니라 「막는 문장이다」로 읽어야 한다.
    assert requirements.of("exclusion")


def test_비영리사회적기업은_사회적기업이_아니다() -> None:
    """낱말 경계 (0925 §4-C-1). 한글에는 `\b` 가 없어 앞 글자를 직접 본다."""
    assert extractor.word_at("◦ 인증 사회적기업", "사회적기업")
    assert not extractor.word_at("(비영리사회적기업, 어린이집 등)", "사회적기업")


def test_수강할_강의_목록은_신청자_유형이_아니다() -> None:
    """118350 의 「… 수강」 줄. 강의 이름을 신청 자격으로 읽으면 안 된다."""
    text = document(
        "○ 지원대상\n"
        "- 장애인 예비창업자 및 3년 미만 초기창업자\n"
        "- 창업 강의(기초, 역량강화, 창업자 재기, 협동조합 등 택1) 수강 후 신청"
    )
    labels = [c.label for c in extractor.extract_from_text("P", text).of("org_type")]
    assert "협동조합" not in labels, labels


#: `data/private/bizinfo_docs/PBLN_000000000118204.txt`(2026년 여성기업 육성사업 · 중소벤처기업부) 98~100 · 329행.
#: 여성기업의 **법적 정의**(여성기업지원법 시행령 제2조)가 「상법상 회사, 개인사업자 또는 협동조합」을 나열한다 —
#: 주식회사도 드는 정의인데 「협동조합 · 사회적협동조합」만 조직 형태로 읽어 「사회적협동조합만 대상 → 불가」였다(10-31 대표 확인).
WOMEN_DEFINITION_118204 = (
    "□ 신청자격\n"
    "◦ 여성 (예비)창업자 및「중소기업기본법」상 중소기업인 중 여성기업*\n"
    "* 여성이 소유하고 실질적으로 경영하는 기업으로 ➊상법상 법인, ➋개인사업자, ➌협동조합\n"
    "* 여성이 소유하고 실질적으로 경영하는 기업으로서 상법상 회사, 개인사업자 또는 협동조합(사회적협동조합, 소비자생활협동조합 포함)에 해당하는 기업"
)


def test_상법상_회사를_함께_나열한_법적_정의는_조직_형태_요건이_아니다() -> None:
    labels = [c.label for c in extractor.extract_from_text("P", document(WOMEN_DEFINITION_118204)).of("org_type")]
    assert not {"조직 형태: 협동조합", "조직 형태: 사회적협동조합"} & set(labels), labels
    rules, _ = judge(WOMEN_DEFINITION_118204, title="2026년 여성기업 육성사업 공고")
    assert status_of(rules, "BIZ-ORG-TYPE") != "FAIL"


def test_사회적협동조합만_적은_대상_줄은_여전히_조직_형태_불가다() -> None:
    """위 고침이 진짜 제한까지 풀지 않는다 — 「상법상 회사」가 목록에 없으면 그대로 그 형태만 대상이다."""
    rules, _ = judge("□ 신청자격\n◦ 지원대상: 사회적협동조합")
    assert status_of(rules, "BIZ-ORG-TYPE") == "FAIL"
    rules, _ = judge("□ 신청자격\n◦ 지원대상: 상법상 회사가 아닌 사회적협동조합")
    assert status_of(rules, "BIZ-ORG-TYPE") == "FAIL"


#: `data/private/bizinfo_docs/PBLN_000000000120566.txt` 20 · 22 · 64행.
#: 지식재산 경영인증 공고다. 10차는 이 셋에서 「무료」와 「10억원」을 읽어
#: 「받는 것: 무료 · 최대 10억원」이라고 적었다. 20행은 **회사가 내는 돈**,
#: 22행의 무료는 **수수료 면제**, 64행은 **보증 한도**다 — 셋 다 받는 것이 아니다.
MONEY_120566 = (
    "□ 신청수수료 : 33만원(VAT포함)\n"
    "* 갱신수수료 : 11만원\n"
    "* 최종심사 탈락 기업 당해 연도 재신청 시 1회에 한해 수수료 무료 및 당해 연도 이후\n"
    "재신청 시 1회에 한해 수수료 감면(11만원)\n"
    "o SGI 서울보증\n"
    "‣ 지점장 전결 보증한도 10억원~30억원 확대(신용등급별 차등)"
)


def test_수수료와_보증한도는_받는_것이_아니다() -> None:
    """120566 20 · 22 · 64행 (0925 §4-C-2)."""
    requirements = extractor.extract_from_text("P", document(MONEY_120566))
    quotes = [c.source_text for c in requirements.of("money")]
    assert quotes == [], quotes
    assert not extractor.free_of(requirements), "「수수료 무료」는 무료 지원이 아니다"
    assert not extractor.no_self_burden_of(requirements)


def test_자부담_없음은_자부담_문장이_있을_때만() -> None:
    """「무료」가 곧 「자부담 없음」은 아니다 (0925 §4-C-2)."""
    without = extractor.extract_from_text("P", document("○ 지원내용\n- 컨설팅 (무료)"))
    assert extractor.free_of(without)
    assert not extractor.no_self_burden_of(without)

    withit = extractor.extract_from_text(
        "P", document("○ 지원내용\n- 컨설팅 비용 전액 지원 (기업 자부담 없음)")
    )
    assert extractor.no_self_burden_of(withit)
