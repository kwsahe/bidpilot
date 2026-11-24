"""43차 §2-B — 판정 · 자격(H2 · H3 · H5 · M7 · M20 · M21 · 결정 2 · Q13 · Q24 · ELIG-09)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import eligibility_engine as ee

KST = timezone(timedelta(hours=9))
AS_OF = datetime(2026, 10, 23, 9, tzinfo=KST)

OLD_JEONNAM_22 = [f"전남광주통합특별시 {c}" for c in (
    "목포시", "여수시", "순천시", "나주시", "광양시", "담양군", "곡성군", "구례군", "고흥군", "보성군", "화순군",
    "장흥군", "강진군", "해남군", "영암군", "무안군", "함평군", "영광군", "장성군", "완도군", "진도군", "신안군",
)]
OLD_GWANGJU_5 = [f"전남광주통합특별시 {g}" for g in ("동구", "서구", "남구", "북구", "광산구")]

BUKGU = ee.CompanyFacts(location_region="전남광주", location_old_region="광주", location_district="북구", from_real_company=True)
NO_DISTRICT = ee.CompanyFacts(location_region="전남광주", from_real_company=True)


def _region(allowed: list[str], company: ee.CompanyFacts) -> ee.EligibilityResult:
    token = ee._ACTIVE_COMPANY.set(company)
    try:
        return ee._rule_region({"allowed_regions": allowed})
    finally:
        ee._ACTIVE_COMPANY.reset(token)


# --------------------------------------------------------------------------
# H2 — 「전남광주통합특별시 ○○시 · 군」 목록
# --------------------------------------------------------------------------


def test_옛_전남_22개_시군만_열린_공고는_광주_북구_회사에게_불가():
    row = _region(OLD_JEONNAM_22, BUKGU)
    assert row.status == "FAIL"
    assert "북구" in row.reason and "외 19곳" in row.reason
    assert not row.unlock_options  # 이전을 권하지 않는다(N3)


def test_광주_자치구_목록에_북구가_있으면_가능():
    assert _region(OLD_GWANGJU_5, BUKGU).status == "PASS"


def test_회사_주소의_구를_모르면_확인_필요():
    row = _region(OLD_JEONNAM_22, NO_DISTRICT)
    assert row.status == "CHECK" and row.check_side == "company"


def test_통합특별시_전체가_열려_있으면_가능():
    assert _region(["전남광주통합특별시", "충청북도"], BUKGU).status == "PASS"


def test_옛_광주광역시만_열린_공고는_옛_전남_회사에게_불가():
    jeonnam = ee.CompanyFacts(location_region="전남광주", location_old_region="전남", location_district="나주시", from_real_company=True)
    assert _region(["광주광역시"], jeonnam).status == "FAIL"
    assert _region(["광주광역시"], BUKGU).status == "PASS"


def test_주소에서_시군구를_읽는다():
    assert ee._home_units("전남광주통합특별시 북구 가상로 77") == ["북구"]
    assert ee._home_units("전라남도 나주시 빛가람로") == ["나주시"]
    assert ee._home_units("경기도 광주시 오포읍") == []


def _clause(text: str) -> ee._Clause:
    return ee._Clause(id="QC-01", text=text, page=1, origin="입찰공고문", approx=False, kind="region")


def test_조항_문장도_같은_규칙():
    assert ee._judge_region(_clause("전남광주통합특별시 영암군에 주된 영업소를 둔 업체"), BUKGU).status == "FAIL"
    assert ee._judge_region(_clause("광주광역시 북구에 본사를 둔 업체"), BUKGU).status == "PASS"
    # 둘째 시 · 군부터 도 이름이 없으면 단정하지 않는다
    assert ee._judge_region(_clause("전남광주통합특별시 목포시, 여수시, 북구에 소재한 업체"), BUKGU).status != "FAIL"
    assert ee._judge_region(_clause("주된 영업소의 소재지가 전남광주통합특별시인 업체"), BUKGU).status == "PASS"


# --------------------------------------------------------------------------
# H3 · H5 — 실적 조항
# --------------------------------------------------------------------------

from datetime import date  # noqa: E402

from app.services import performance_match_service as pm  # noqa: E402

TODAY = date(2026, 10, 23)


def _ledger(*rows: dict) -> ee.CompanyFacts:
    packed = tuple(tuple(sorted({"seq": i + 1, "period": "", "field": "기업·재직자·컨설팅", "agency": "", "amount_basis": "", "evidence_note": "", **r}.items()))
                   for i, r in enumerate(rows))
    return ee.CompanyFacts(ledger_rows=packed, ledger_available=True, from_real_company=True)


PRINTER = {"year": "2024", "title": "3D 프린터 가상 기초 과정", "summary": "가상여성인력개발센터 재직자 교육", "amount_thousand_krw": 54000}


def _track(text: str, company: ee.CompanyFacts, **kw) -> ee.EligibilityResult:
    return ee._judge_track_record(ee._Clause(id="QC-06", text=text, page=1, origin="입찰공고문", approx=False, kind="track_record"), company, TODAY, **kw)


def test_영상_콘텐츠_개발_실적에_3D_프린터_교육은_맞지_않는다():
    row = _track("최근 3년간 영상 콘텐츠(K-MOOC 강좌 개발 우대) 개발 관련 용역이 3천만원 이상의 실적", _ledger(PRINTER))
    assert row.status == "CHECK"
    assert "3D 프린터" not in row.reason


def test_기관_이름_속_개발은_분야가_아니다():
    assert "개발" not in pm.work_text("재직자 교육", "가상여성인력개발센터 위탁")


def test_실적_제한을_두지_않는다는_조항은_실적_요건이_아니다():
    row = _track("유사용역 수행실적에 따른 입찰참가자격 제한은 두지 않습니다.", _ledger(PRINTER))
    assert row.status == "PASS" and "실적 요건이 아닙니다" in row.reason
    assert "건 필요" not in row.reason


def test_원과_이상_사이_괄호_금액과_건당을_읽는다():
    c = pm.parse_criteria("최근 3년 이내 건당 3천만원(VAT포함) 이상 AI 교육 실적 1건 이상")
    assert c.min_amount_thousand == 30000 and c.amount_mode == "single"
    c2 = pm.parse_criteria("단일계약 5천만원(부가세 포함) 이상")
    assert c2.min_amount_thousand == 50000 and c2.amount_mode == "single"


def test_같은_공고의_금액_기준을_금액_없는_실적_조항에도_쓴다():
    small = {"year": "2025", "title": "생성형 AI 활용 교육", "summary": "공무원 대상 AI 교육", "amount_thousand_krw": 9000}
    company = _ledger(small)
    without = _track("최근 3년 이내 AI 교육 실적 1건 이상", company)
    with_amount = _track("최근 3년 이내 AI 교육 실적 1건 이상", company, notice_amount=(30000.0, "single"))
    assert without.status == "PASS"
    assert with_amount.status == "CHECK"


# --------------------------------------------------------------------------
# 결정 2 — 회사 단위 한 번 확인 · M7 0단계 · Q13 · M21 직접생산 · ELIG-09
# --------------------------------------------------------------------------

from app.services import opportunity_priority as priority  # noqa: E402

CHECKS_VALID = (
    ("g2b_registration", "2026-10-01", "2027-09-30", "대표"),
    ("no_sanction", "2026-10-01", "2026-12-31", "대표"),
    ("no_tax_arrears", "2026-10-01", "2026-12-31", "대표"),
)


def _registration(company: ee.CompanyFacts) -> ee.EligibilityResult:
    token = ee._ACTIVE_COMPANY.set(company)
    try:
        return ee._rule_business_registration(None, date(2026, 10, 23))
    finally:
        ee._ACTIVE_COMPANY.reset(token)


def test_회사_단위_확인_세_칸이_유효하면_등록_결격_줄이_통과():
    row = _registration(ee.CompanyFacts(from_real_company=True, company_checks=CHECKS_VALID))
    assert row.status == "PASS" and row.method == "HUMAN"
    assert "회사 확인 2026-10-01" in row.reason


def test_유효기간이_지나면_다시_확인():
    expired = (*CHECKS_VALID[:2], ("no_tax_arrears", "2026-01-01", "2026-03-31", "대표"))
    row = _registration(ee.CompanyFacts(from_real_company=True, company_checks=expired))
    assert row.status == "CHECK" and row.reason.startswith("다시 확인")


def test_한_칸이라도_비면_확인_필요_그대로():
    row = _registration(ee.CompanyFacts(from_real_company=True, company_checks=CHECKS_VALID[:2]))
    assert row.status == "CHECK" and "체납" in row.reason


def test_값이_없으면_예전처럼_등록증_확인():
    row = _registration(ee.CompanyFacts(from_real_company=True))
    assert row.status == "CHECK" and "등록증" in row.reason


def test_결격_조항도_회사_확인으로_통과():
    clause = ee._Clause(id="QC-09", text="부정당업자로 입찰참가자격 제한을 받고 있는 자는 참가할 수 없음", page=1, origin="입찰공고문", approx=False, kind="disqualification")
    assert ee._judge_disqualification(clause, ee.CompanyFacts(from_real_company=True, company_checks=CHECKS_VALID), date(2026, 10, 23)).status == "PASS"
    assert ee._judge_disqualification(clause).status == "CHECK"


def test_0단계_탈락_조건을_이름까지_적는다():
    raw = {"cmmnSpldmdMethdNm": "(없음)공동수급불허"}
    rows = [
        ee.EligibilityResult(rule_id="ELIG-INDUSTRY", label="업종제한", status="CHECK", method="RULE", source="s",
                             reason="공고는 소프트웨어사업자(1469)를 요구합니다.", unlock_condition="1469 등록 시 가능", unlock_options=["1469 등록 시 가능"]),
        ee.EligibilityResult(rule_id="QUAL-TYPE-QC-02", label="기업 유형 조항", status="CHECK", method="RULE", source="s",
                             reason="직접생산", clause_text="동영상제작서비스(8213160301)에 대한 직접생산확인증명서를 소지한 자"),
        ee.EligibilityResult(rule_id="ELIG-BRIEFING", label="필수 현장설명", status="CHECK", method="RULE", source="s",
                             reason="필수", unlock_condition="필수 현장설명 11/02 14:00 참석 시 가능"),
    ]
    assert priority.stage0_conditions(rows, raw) == ["1469 없으면 탈락(공동수급 불허)", "직접생산(동영상제작서비스)", "필수 설명회 11/02"]
    # 공동수급이 되면 업종 · 직접생산은 파트너로 보완할 수 있어 0단계에 넣지 않는다
    assert priority.stage0_conditions(rows, {"cmmnSpldmdMethdNm": "(전자)공동이행"}) == ["필수 설명회 11/02"]


def test_불가_사유는_판정_문장_먼저_원문_뒤():
    row = ee.EligibilityResult(rule_id="QUAL-REGION-QC-01", label="지역 조항", status="FAIL", method="RULE", source="s",
                               reason="조항은 서울 소재를 요구하는데 회사 소재는 전남광주입니다.", clause_text="본점 소재지를 서울특별시에 둔 업체")
    assert priority._gate_text(row).startswith("조항은 서울 소재를 요구") and "원문 「본점 소재지를" in priority._gate_text(row)


def test_직접생산_품명을_보유와_견준다():
    text = "회의기획(8014190201) · 기타행사기획 및 대행서비스(8014199001) 중 1건 이상에 대한 직접생산확인증명서를 소지한 자"
    clause = ee._Clause(id="QC-02", text=text, page=1, origin="입찰공고문", approx=False, kind="company_type")
    blank = ee._judge_company_type(clause, ee.CompanyFacts(from_real_company=True), TODAY)
    assert blank.status == "CHECK" and "보유 품명은 회사자료에 아직 없습니다" in blank.reason and blank.reason.startswith("직접생산확인증명서")
    held = ee.CompanyFacts(from_real_company=True, direct_production_items=("기타행사기획 및 대행서비스 8014199001",))
    # 43차 마지막 검토 — 품명이 맞아도 증명서 유효기간은 회사자료에 없다 · 확인 필요(품명은 맞음)
    matched = ee._judge_company_type(clause, held, TODAY)
    assert matched.status == "CHECK" and "품명은 맞음" in matched.reason and "유효기간" in matched.reason
    other = ee.CompanyFacts(from_real_company=True, direct_production_items=("동영상제작서비스 8213160301",))
    row = ee._judge_company_type(clause, other, TODAY)
    assert row.status == "CHECK" and row.reason.startswith("확인 필요 — 직접생산 보유 동영상제작서비스")


def test_공동수급_불허면_공동수급체_지역제한은_해당_없음():
    row = ee._rule_consortium_region({"cmmnSpldmdMethdNm": "(없음)공동수급불허", "cmmnSpldmdCorpRgnLmtYn": "N"})
    assert row.reason == "해당 없음(공동수급 불허)."


def test_본사_이전은_갖추면_가능에_넣지_않는다():
    from app.services import opportunity_brief_service as brief
    unlock, direct = brief.split_unlocks(["대구광역시 소재 시 가능", "1469 등록 시 가능", ee.REGISTRATION_UNLOCK])
    assert unlock == ["1469 등록 시 가능"] and direct == [ee.REGISTRATION_UNLOCK]


def test_대기업_중견_참여_제한은_업종_요구가_아니다():
    clause = ee._Clause(id="QC-09", text="대기업 및 중견기업인 소프트웨어사업자의 입찰 참여를 제한함", page=1, origin="입찰공고문", approx=False, kind="industry")
    row = ee._judge_industry(clause, {}, ee.CompanyFacts(from_real_company=True))
    assert row.status == "CHECK" and "업종 요구가 아님" in row.reason and not row.unlock_options


def test_결격_조항이_아닌_공급기업_제외는_보유_요건이_아니다():
    from app.services import support_requirement_extractor as extractor
    from app.services import bizinfo_document_store as store
    text = "□ 선정제외대상\n❍ 2026년 블록체인 바우처 지원사업 공급기업으로 등록된 기업\n□ 지원내용\n- 컨설팅"
    req = extractor.extract_from_text("P", store.join_pages([text]))
    assert not [c for c in req.of("prerequisite") if (c.detail or {}).get("requirement") == "supplier_registration"]


def test_빼는_문장_꼴_실적_지역_조항은_회사_확인으로_통과하지_않는다():
    """43차 마지막 검토 — 「유사 실적이 없는 자는 참가할 수 없다」가 결격 조항으로 갈려 회사 단위 확인 세 칸만으로 「통과」가 됐다(§11)."""
    company = ee.CompanyFacts(from_real_company=True, company_checks=CHECKS_VALID)
    for text in ("최근 3년간 유사 용역 실적이 없는 자는 참가할 수 없다", "서울특별시에 주된 영업소를 두지 않은 업체는 참여할 수 없다",
                 "부정당업자 및 최근 3년 실적이 없는 자는 참가할 수 없다"):
        clause = ee._Clause(id="QC-10", text=text, page=1, origin="입찰공고문", approx=False, kind="disqualification")
        assert ee._judge_disqualification(clause, company, date(2026, 10, 23)).status == "CHECK", text
