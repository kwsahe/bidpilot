"""중소기업 확인서 칸(담당자 결정 2026-10-10) — 회사자료 준비 상태의 「중소기업(소상공인) 확인서」 줄(있음 · 구분 · 유효기간)을 판정에 쓴다.

네트워크 0. 공고 문장은 실제 저장본 꼴(123682 · 119692 · 126412 · 나라장터 참가자격 조항)을 짧게 옮겼다.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

from app.services import bizinfo_document_store as store
from app.services import eligibility_engine as ee
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor

TODAY = date(2026, 10, 10)
BASE = ee.CompanyFacts(certifications=("사회적기업",), from_real_company=True)


def company(held: bool | None, grade: str | None = None, valid_until: date | None = None, **kw) -> ee.CompanyFacts:
    return dataclasses.replace(BASE, sme_held=held, sme_grade=grade, sme_valid_until=valid_until, **kw)


def sme_clauses(line: str):
    return extractor.extract_from_text("P", store.join_pages([f"○ 신청자격\n{line}"])).of("sme")


# --------------------------------------------------------------------------
# 회사자료 줄 읽기
# --------------------------------------------------------------------------


def test_준비_상태_줄을_이름_규칙으로_찾는다() -> None:
    rows = [SimpleNamespace(name="창업기업 확인서"), SimpleNamespace(name="중소기업(소상공인) 확인서", held=True)]
    assert ee.sme_credential(rows) is rows[1]
    assert ee.sme_credential([SimpleNamespace(name="중소기업확인서")]) is not None
    assert ee.sme_credential([SimpleNamespace(name="직접생산확인증명서")]) is None


def test_확인서_상태() -> None:
    assert ee.sme_state(company(None), TODAY) == "unknown"
    assert ee.sme_state(company(False), TODAY) == "none"
    assert ee.sme_state(company(True), TODAY) == "valid"  # 유효기간을 모르면 유효로 본다
    assert ee.sme_state(company(True, valid_until=date(2027, 3, 31)), TODAY) == "valid"
    assert ee.sme_state(company(True, valid_until=date(2026, 3, 31)), TODAY) == "expired"


# --------------------------------------------------------------------------
# 공고문에서 「중소기업」 요건 읽기
# --------------------------------------------------------------------------


def test_중소기업_하나만_요구하는_줄() -> None:
    for line in (
        "○ 「중소기업기본법」 제2조에 따른 중소기업",
        "□ 신청대상 : 중소기업기본법 제2조에 따른 중소기업",
        # 두 번 부정은 요건이다(119692)
        "□ 지원대상 : 신청 제외 대상에 해당되지 않는 ｢중소기업기본법｣ 제2조 및 시행령 제3조에 따른 중소기업",
        "◯ 「중소기업기본법」 제3조에 따른 '중소기업 확인서'를 보유한 중소기업",
    ):
        clauses = sme_clauses(line)
        assert len(clauses) == 1 and clauses[0].detail["clean"], line


def test_같은_줄에_다른_조건이_있으면_clean_이_아니다() -> None:
    clauses = sme_clauses("(모집 대상) 중소기업기본법 제2조에 따른 중소기업 중 지역 전략산업 영위기업 및 침해사고 피해기업 등")
    assert len(clauses) == 1 and not clauses[0].detail["clean"] and "전략산업" in clauses[0].detail["rest"]
    # 다음 줄로 이어지는 「…중소기업의」(126482 — 대표자 · 창업 조건이 이어진다)
    assert not sme_clauses("□ 신청자격 : ｢중소기업기본법｣ 제2조제1항에 따른 중소기업의")[0].detail["clean"]


def test_요건이_아닌_줄은_읽지_않는다() -> None:
    assert sme_clauses("• 중소기업기본법 시행령이 정한 중소기업에 해당되지 않는 경우") == []  # 제외 조항
    assert sme_clauses("ㅇ (지원 대상) SW관련 중소기업") == []  # 분명한 꼴만 읽는다(아직)
    assert sme_clauses("❹ 제출서류 등록(사업자등록증, 중소기업확인서, 국세 납입자료 등)") == []


# --------------------------------------------------------------------------
# 기업마당 BIZ-SME
# --------------------------------------------------------------------------


def _requirements(line: str):
    return extractor.extract_from_text("P", store.join_pages([f"○ 신청자격\n{line}"]))


CLEAN = "○ 「중소기업기본법」 제2조에 따른 중소기업"
MIXED = "(모집 대상) 중소기업기본법 제2조에 따른 중소기업 중 SW관련 기업"


def test_있음이면_가능이고_가능의_근거가_된다() -> None:
    req = _requirements(CLEAN)
    rule = sas._biz_sme(req, company(True, "중기업", date(2027, 3, 31)), TODAY)
    assert rule.status == "PASS" and "확인서가 있습니다" in rule.reason
    gate, reason = sas.verdict_of(req, [rule], indirect=None)
    assert gate == "PASS" and "중소기업 확인서" in reason


def test_모름_없음_지남은_확인_필요이고_불가로_닫지_않는다() -> None:
    req = _requirements(CLEAN)
    unknown = sas._biz_sme(req, company(None), TODAY)
    assert unknown.status == "CHECK" and unknown.unlock_condition == sas.SME_UNLOCK
    none = sas._biz_sme(req, company(False), TODAY)
    assert none.status == "CHECK" and "발급받으면" in none.unlock_condition
    expired = sas._biz_sme(req, company(True, valid_until=date(2026, 3, 31)), TODAY)
    assert expired.status == "CHECK" and "2026-03-31" in expired.reason and expired.unlock_condition
    # 회사 쪽 확인(서류를 갖추거나 적을 일)
    for rule in (unknown, none, expired):
        assert sas.clause_signals(req, [rule], indirect=None)["company_side_checks"] == ["BIZ-SME"]


def test_같은_줄에_못_읽은_조건이_있으면_있음이어도_확인_필요_공고_쪽() -> None:
    req = _requirements(MIXED)
    rule = sas._biz_sme(req, company(True), TODAY)
    assert rule.status == "CHECK" and "SW관련" in rule.reason and rule.unlock_condition is None
    assert sas.clause_signals(req, [rule], indirect=None)["company_side_checks"] == []


def test_소상공인만_대상은_확인서_구분을_먼저_본다() -> None:
    req = extractor.extract_from_text("P", store.join_pages(["○ 신청자격\n소상공인"]))
    program = SimpleNamespace(target="소상공인")
    small = sas._biz_small_business(req, program, company(True, "소상공인"), TODAY)
    assert small.status == "PASS"
    mid = sas._biz_small_business(req, program, company(True, "중기업"), TODAY)
    assert mid.status == "FAIL" and "중기업" in mid.reason
    # 소기업 · 모름 · 지난 확인서는 예전대로 상시근로자 수(미입력 → 확인 필요)
    for c in (company(True, "소기업"), company(None), company(True, "소상공인", date(2026, 3, 31))):
        assert sas._biz_small_business(req, program, c, TODAY).status == "CHECK"


# --------------------------------------------------------------------------
# 나라장터 기업 유형 조항
# --------------------------------------------------------------------------


def clause(text: str) -> ee._Clause:
    return ee._Clause(id="QC-01", text=text, page=2, origin="입찰공고문", approx=False, kind="company_type")


SME_TEXT = "「중소기업기본법」에 따른 중소기업자로서 중소기업·소상공인 확인서를 소지한 자"
SMALL_TEXT = "「판로지원법」에 따른 소기업 또는 소상공인으로서 소기업·소상공인 확인서를 소지한 자"
DIRECT_TEXT = "「중소기업제품 구매촉진 및 판로지원에 관한 법률」에 따른 직접생산확인증명서를 소지한 자"


def test_나라장터_중소기업_조항은_구분과_상관없이_있음이면_가능() -> None:
    assert ee._judge_company_type(clause(SME_TEXT), company(True, "중기업"), TODAY).status == "PASS"
    assert ee._judge_company_type(clause(SME_TEXT), company(True), TODAY).status == "PASS"


def test_나라장터_소기업_소상공인_조항은_구분으로_가른다() -> None:
    assert ee._judge_company_type(clause(SMALL_TEXT), company(True, "소상공인"), TODAY).status == "PASS"
    assert ee._judge_company_type(clause(SMALL_TEXT), company(True, "소기업"), TODAY).status == "PASS"
    mid = ee._judge_company_type(clause(SMALL_TEXT), company(True, "중기업"), TODAY)
    assert mid.status == "FAIL" and "중기업" in mid.reason
    unknown_grade = ee._judge_company_type(clause(SMALL_TEXT), company(True), TODAY)
    assert unknown_grade.status == "CHECK" and "구분" in unknown_grade.reason


def test_나라장터_없음_지남_모름은_확인_필요() -> None:
    for c in (company(False), company(True, "소상공인", date(2026, 3, 31)), company(None)):
        rule = ee._judge_company_type(clause(SME_TEXT), c, TODAY)
        assert rule.status == "CHECK" and rule.unlock_condition, c


def test_나라장터_직접생산_조항은_확인서로_맞추지_않는다() -> None:
    """법 이름 「중소기업제품 구매촉진 …」 때문에 기업 유형으로 들어온 직접생산 조항 — 다른 서류다."""
    assert ee._judge_company_type(clause(DIRECT_TEXT), company(True, "소상공인"), TODAY).status != "PASS"


def test_나라장터_인증으로_맞으면_그대로() -> None:
    text = "사회적기업 또는 「중소기업기본법」에 따른 중소기업으로서 확인서를 소지한 자"
    assert ee._judge_company_type(clause(text), company(None), TODAY).status == "PASS"  # 사회적기업 인증


def test_나라장터_중기업_불가는_자격_조항에서만() -> None:
    """같은 공고의 안내 · 절차 조항은 불가로 찍지 않는다 — 인용과 사유가 어긋났다(10-10 가정 실측 · 1756384 · 1744488)."""
    for text in (
        "발급된 ‘소기업·소상공인 확인서’가 입찰참가자격의 기업 구분과 다른 경우",
        "소기업자로 간주되는 특별법인 또는 비영리법인은 소기업‧소상공인확인서가 없어도 입찰 참여 가능",
        "전자입찰서 제출 마감일 전일까지 ‘소기업·소상공인확인서’를 신청하지 않은 경우",
    ):
        rule = ee._judge_company_type(clause(text), company(True, "중기업"), TODAY)
        assert rule.status == "CHECK", text
    assert ee._judge_company_type(clause(SMALL_TEXT), company(True, "중기업"), TODAY).status == "FAIL"


# --------------------------------------------------------------------------
# 확인서가 풀리면서 드러난 숨은 구멍(10-10 가정 감사) — 확인서가 있어도 가능이 아니어야 하는 넷
# --------------------------------------------------------------------------


def test_괄호_안_제외는_제외_조항이_아니고_점수_문턱은_신청_요건() -> None:
    """120566 — 「자가진단 결과가 50점 이상(… 제외 시 45점)인 경우에 한하여 … 신청」이 제외 조항으로 숨었다."""
    text = store.join_pages(["○ 신청대상 : 중소기업기본법 제2조에 따른 중소기업\n"
                             "* 인증을 받고자 하는 기업은 자가진단을 수행해야 하며, 자가진단\n"
                             "결과가 50점 이상(SMART5 등급 점수 제외 시 45점)인 경우에 한하여 인증 및 갱신을\n신청 할 수 있음\n"
                             "- 지원금 (정부지원금 제외) 안내"])
    req = extractor.extract_from_text("P", text)
    assert req.of("exclusion") == []
    assert [c.detail.get("requirement") for c in req.of("prerequisite")] == ["score_threshold"]
    rule = sas._biz_prerequisite(req, company(True), ())
    assert rule.status == "CHECK" and "점수" in rule.reason
    # 심사 기준(뒤가 선정)은 신청 요건이 아니다
    assert not extractor.extract_from_text("P", store.join_pages(["○ 평가\n평가 결과 70점 이상인 경우에 한하여 선정"])).of("prerequisite")


def test_거래_협력_중인_중소기업은_확인서로_가리지_못한다() -> None:
    """126412 — 「KCA와 거래·협력중인 중소기업 중 …」 + 「중소기업 확인서를 보유한 중소기업」."""
    req = extractor.extract_from_text("P", store.join_pages([
        "2. 모집대상 및 내용\nㅇ (모집대상) KCA와 거래·협력중인 중소기업 중 중소기업기술마켓 인증\n"
        "◯ 「중소기업기본법」 제3조에 따른 '중소기업 확인서'를 보유한 중소기업"]))
    rule = sas._biz_sme(req, company(True, "소기업"), TODAY)
    assert rule.status == "CHECK" and "거래·협력중인" in rule.reason


def test_수행기관_지역_기업_대상은_다른_지역이면_확인_필요() -> None:
    """123800 — 「지역정보보호지원센터가 속한 지역기업을 지원」 + 수행기관 인천테크노파크. 전국 기관(123682 한국인터넷진흥원)은 그대로."""
    req = extractor.extract_from_text("P", store.join_pages(["○ 신청자격\n「중소기업기본법」 제2조에 따른 중소기업\n※ 지역정보보호지원센터가 속한 지역기업을 지원"]))
    assert req.of("operator_region")
    loc = company(True, location_region="전남광주")
    incheon = SimpleNamespace(executing_agency="인천테크노파크", region_tags=(), agency="과학기술정보통신부", title="2026년 중소기업 정보보호 지원사업")
    rule = sas._biz_location(req, incheon, loc)
    assert rule.status == "CHECK" and "인천테크노파크" in rule.reason
    national = SimpleNamespace(executing_agency="한국인터넷진흥원", region_tags=(), agency="과학기술정보통신부", title="2026년 ICT 중소기업 정보보호 지원")
    assert sas._biz_location(req, national, loc).status == "PASS"


def test_나라장터_합쳐진_조항은_확인서만_보고_가능이라_하지_않는다() -> None:
    """1754106 QC-01 — 글머리표가 한 조항으로 합쳐졌다(확인서 · 나라장터 등록 · 부정당업자)."""
    text = ("「중소기업기본법」에 따른 중소기업자로서 중소기업·소상공인 확인서를 소지한 자 · 국가종합전자조달시스템(나라장터)에 "
            "입찰참가자격을 등록한 자 · 부정당업자 제재를 받지 않은 자")
    rule = ee._judge_company_type(clause(text), company(True, "소기업"), TODAY)
    assert rule.status == "CHECK" and "직접 확인" in rule.reason


def test_비용의_N퍼센트는_정부_지원_비율() -> None:
    """120083 「가치평가비용의 50%(최대 1,500만원, VAT 제외)」 — 괄호 속 「VAT 제외」로 제외 조항에 잘못 숨어 있던 줄. 부담 비용은 아니다."""
    def money(line: str) -> list[str]:
        return [c.label for c in extractor.extract_from_text("P", store.join_pages([f"○ 지원내용\n{line}"])).of("money")]

    assert "정부지원 비율 50%" in money("데이터 가치평가비용의 50%(최대 1,500만원, VAT 제외) 및 우대비율 최대 25% 가산 지원")
    assert money("정부가 구축 비용의 30% 이내 지원") == ["정부지원 비율 30%"]
    assert "정부지원 비율 30%" not in money("기업 부담 비용의 30%는 현금으로")
    # 기업부담 표(122147) · 비목 한도(127025)는 지원 비율이 아니다
    assert money("현금 - 900,000원(컨설팅 비용의 25%)") == []
    assert money("기술도입비 지원 기준 — 실제 기술 도입에 소요된 비용의 50% 이내)ㆍ연구재료비 현물") == []
    assert money("실제 기술 도입에 소요된 비용의 50% 이내)ㆍ연구재료비") == []
    req = extractor.extract_from_text("P", store.join_pages(["□ 지원내용\n데이터 가치평가비용의 50%(최대 1,500만원, VAT 제외) 지원"]))
    assert req.of("exclusion") == []


# --------------------------------------------------------------------------
# 변경 검토(10-10)에서 확정된 결함
# --------------------------------------------------------------------------


def test_나라장터_빗금_구분_소기업_확인서도_소기업_전용() -> None:
    """1725512 QC-03 — 「소기업/소상공인확인서」를 못 읽고 조문 제목 「(중소기업자와의 우선조달계약)」으로 중소기업 조항이 되어 중기업이 가능이었다."""
    text = ("「판로지원법」 제7조의2(중소기업자와의 우선조달계약)에 따른 소기업/소상공인으로서 "
            "중소기업확인시스템에서 발급된 소기업/소상공인확인서를 소지한 자")
    assert ee._judge_company_type(clause(text), company(True, "중기업"), TODAY).status == "FAIL"
    assert ee._judge_company_type(clause(text), company(True, "소기업"), TODAY).status == "PASS"


def test_나라장터_줄바꿈으로_끊긴_직접생산도_다른_서류() -> None:
    """1718615 QC-08 — PDF 줄바꿈 「직접생 산」. 확인서 칸을 적은 회사에게 「확인서 발급 시」를 안내했다."""
    text = "「중소기업제품 구매촉진 및 판로지원에 관한 법률」 제9조에 따른 직접생 산확인증명서를 소지한 자"
    for c in (company(True, "소상공인"), company(None)):
        rule = ee._judge_company_type(clause(text), c, TODAY)
        assert rule.status == "CHECK" and "직접생산확인증명서" in rule.reason
        assert rule.unlock_condition and "직접생산" in rule.unlock_condition


def test_나라장터_확인서로_못_가리는_중소기업_낱말() -> None:
    """적격조합(1751431) · 간주 특별법인(1744316) · 공공구매 정보망(1725512 QC-04 · 1740516) — 확인서가 있어도 가능이 아니고 「확인서를 아직 안 적음」도 아니다."""
    for text in (
        "「중소기업협동조합법」제3조에 따른 중소기업협동조합으로서 적격조합 확인서를 소지한 자는 입찰참가가 가능",
        "중소기업으로 간주되는 특별법인의 입찰참가",
        "모든 입찰참가자격은 ‘국가종합전자조달시스템’ 또는 ‘중소기업제품 공공구매 종합정보망(SMPP)’에서 확인 가능해야 하며",
        "마감 직후 중소기업 공공구매 종합정보망(smpp.go.kr)에서 확인되는 것",
    ):
        rule = ee._judge_company_type(clause(text), company(True, "중기업"), TODAY)
        assert rule.status == "CHECK" and "아직 안 적음" not in rule.reason, text


def test_나라장터_구분_모름_안내_조항은_공고_쪽_확인() -> None:
    text = "발급된 ‘소기업·소상공인 확인서’가 입찰참가자격의 기업 구분과 다른 경우"
    rule = ee._judge_company_type(clause(text), company(True), TODAY)
    assert rule.status == "CHECK" and "안내 조항" in rule.reason and not rule.unlock_condition


def test_나라장터_합쳐진_조항_사유는_읽을_수_있는_이름() -> None:
    text = ("「중소기업기본법」에 따른 중소기업자로서 중소기업·소상공인 확인서를 소지한 자 · 국가종합전자조달시스템(나라장터)에 "
            "입찰참가자격을 등록한 자 · 부정당업자 제재를 받지 않은 자")
    reason = ee._judge_company_type(clause(text), company(True), TODAY).reason
    assert "나라장터 입찰참가자격 등록" in reason and "부정당업자 제재" in reason


def test_법_조문_꼴이_달라도_중소기업_하나만_요구하는_줄() -> None:
    """126980 「및 동법 시행령」 · 126229 「제2조의 규정에 의한」 · 122147 「(개인사업자 포함)」 · 「및 중견기업」."""
    for line in (
        "○ ｢중소기업기본법｣ 제2조 제1항 및 동법 시행령 제3조에 따른 중소기업",
        "○ 「중소기업기본법」 제2조의 규정에 의한 중소기업",
        "○ 「중소기업기본법」제2조에 따른 중소기업(개인사업자 포함)",
        "○ 「중소기업기본법」 제2조에 따른 중소기업 및「중견기업 성장촉진 및 경쟁력 강화에 관한 특별법」 제2조에 따른 중견기업",
    ):
        clauses = sme_clauses(line)
        assert len(clauses) == 1 and clauses[0].detail["clean"], (line, clauses[0].detail if clauses else None)
    # 남은 조건은 띄어쓰기를 지키고 조사로 시작하지 않는다
    rest = sme_clauses("○ 「중소기업기본법」 제2조의 규정에 의한 중소기업으로 전남광주통합특별시 내 소재 기업")[0].detail["rest"]
    assert rest.startswith("전남광주통합특별시 내")


def test_없음이어도_못_읽은_조건이_있으면_발급하면_가능이라_하지_않는다() -> None:
    req = _requirements(MIXED)
    for c in (company(False), company(True, valid_until=date(2026, 3, 31))):
        rule = sas._biz_sme(req, c, TODAY)
        assert rule.status == "CHECK" and rule.unlock_condition is None and "공고 원문" in rule.reason


def test_제외_이름표_괄호와_제외한다는_제외_조항() -> None:
    """괄호를 통째로 지우면 「(지원제외)」 같은 진짜 제외 조항을 잃었다 · 「제외한」을 계산 꼴로 지우면 「제외한다」를 잃었다."""
    def exclusions(line: str) -> int:
        return len(extractor.extract_from_text("P", store.join_pages([f"○ 신청자격\n{line}"])).of("exclusion"))

    assert exclusions("- 국세 · 지방세 체납 기업(지원제외)") == 1
    assert exclusions("- 동일 과제로 다른 사업에 선정된 기업(중복지원 불가)") == 1
    assert exclusions("- 다음 각 호에 해당하는 기업은 지원 대상에서 제외한다") == 1
    assert exclusions("- 지원금 최대 2천만원(VAT 제외)") == 0


def test_나라장터_대상이_소기업이면_확인서_이름이_일반이어도_소기업_전용() -> None:
    """1732306 QC-03 — 「… 1호 … 소기업/소상공인으로서 … 중소기업/소상공인확인서를 소지한 자」."""
    head = "「중소기업제품 구매촉진 및 판로지원에 관한 법률」 시행령 제2조의2(중소기업자와의 우선조달계약) 1호 및 「소상공인 보호 및 지원에 관한 법률」 제2조에 따른 "
    tail = "으로서 「중소기업 범위 및 확인에 관한 규정」에 따라 중소벤처기업부에서 발급된 중소기업/소상공인확인서를 소지한 자"
    small = clause(head + "소기업/소상공인" + tail)
    assert ee._judge_company_type(small, company(True, "중기업"), TODAY).status == "FAIL"
    assert ee._judge_company_type(small, company(True, "소상공인"), TODAY).status == "PASS"
    # 1호를 들면서 대상을 「중소기업」으로 적은 공고(1752887 · 1750306)는 모호하다 — 중기업이면 확인 필요(공고 쪽), 소기업이면 가능
    vague = clause(head + "중소기업/소상공인" + tail)
    rule = ee._judge_company_type(vague, company(True, "중기업"), TODAY)
    assert rule.status == "CHECK" and "1호" in rule.reason and rule.check_side == "notice"
    assert ee._judge_company_type(vague, company(True, "소기업"), TODAY).status == "PASS"
    # 1호가 없는 보통 조항(중 · 소기업 또는 소상공인으로서 … 중 · 소기업 · 소상공인 확인서)은 그대로 가능
    plain = clause("「중소기업기본법」 제2조에 따른 중·소기업자 또는 「소상공인 보호 및 지원에 관한 법률」 제2조에 따른 소상공인으로서 "
                   "「중소기업 범위 및 확인에 관한 규정」에 따라 발급된 중·소기업·소상공인 확인서를 소지한 자")
    assert ee._judge_company_type(plain, company(True, "중기업"), TODAY).status == "PASS"
