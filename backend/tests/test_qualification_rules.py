"""참가자격 조항을 회사 사실과 **따로** 판정한다 (19차 §4-B).

담당자 지시: 「자격요건은 확실하게 가져와서 판단해야 해. 따로 판단하도록 해줘.」

여기서 재는 원칙 셋:

1. **양면 근거가 있을 때만 가능·불가다.** 조항 원문과 회사 사실이 둘 다 있어야 확정한다 —
   빈 `CompanyFacts` 로는 참가자격 조항에서 가능이 하나도 나오지 않는다.
2. **공고문을 못 읽었으면 가능으로 새지 않는다.** 「공고문 참가자격 절」 한 줄이 확인 필요로 남는다.
3. **목록과 상세가 같은 줄을 만든다.** 둘 다 저장된 조항 파일과 파싱해 둔 RFP 를 파일로만 읽는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import eligibility_engine as ee
from app.services import procurement_service, qualification_clause_service as qc
from app.services.opportunity_filter import CandidateMatch

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=KST)
NOTICE_ID = "g2b-R26QUAL0000001-000"


@pytest.fixture(autouse=True)
def clause_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """조항 파일을 tmp 로 돌린다. 저장소의 실제 조항 파일은 건드리지 않는다."""
    monkeypatch.setattr(qc, "CLAUSE_DIR", tmp_path / "qualification_clauses")
    qc._MEMO.clear()
    yield tmp_path / "qualification_clauses"
    qc._MEMO.clear()


def save_clauses(*clauses: tuple[str, str], status: str = "ok", notice_id: str = NOTICE_ID) -> None:
    """(종류, 원문) 조항으로 조항 파일 하나를 만든다."""
    qc.save({
        "notice_id": notice_id,
        "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
        "status": status,
        "page_is_approximate": False,
        "section": {"heading": "3. 입찰참가자격", "page_from": 2, "page_to": 2} if status == "ok" else None,
        "clauses": [
            {"id": f"QC-{i:02d}", "text": text, "page": 2, "kind": kind}
            for i, (kind, text) in enumerate(clauses, start=1)
        ] if status == "ok" else [],
        "second_source": None,
        "note": None if status == "ok" else "머리글을 찾지 못했습니다",
    })


def raw(**overrides: Any) -> dict[str, Any]:
    """필드 규칙이 전부 가능이 되는 공고(업종·지역·실적 제한 없음, 마감 여유)."""
    item: dict[str, Any] = {
        "bidNtceNo": "R26QUAL0000001",
        "cntrctCnclsMthdNm": "일반경쟁",
        "bidQlfctRgstDt": "2026-09-20 18:00",
        "bidClseDt": "2026-09-21 10:00:00",
        "indstrytyLmtYn": "N",
        "bidPrtcptLmtYn": "N",
        "cmmnSpldmdCorpRgnLmtYn": "N",
        "jntcontrctDutyRgnNm1": "",
        "rgnLmtBidLocplcJdgmBssNm": "",
        "asignBdgtAmt": "55000000",
    }
    item.update(overrides)
    # 참가가능지역을 **받았는데 제한이 없다**([]) — 받아 본 적 없음(None)은 34차부터 「확인 필요」(R33-D2)
    return {"source": "g2b", "item": item, "allowed_regions": []}


def rules(company: ee.CompanyFacts, *, raw_data: dict[str, Any] | None = None) -> list[ee.EligibilityResult]:
    return ee.evaluate_notice_fields(raw_data or raw(), as_of=NOW, company=company, notice_id=NOTICE_ID)


def by_id(results: list[ee.EligibilityResult], rule_id: str) -> ee.EligibilityResult:
    match = [r for r in results if r.rule_id == rule_id]
    assert match, f"{rule_id} 없음: {[r.rule_id for r in results]}"
    return match[0]


ALL_KINDS = (
    ("industry", "나라장터에 소프트웨어사업자(컴퓨터관련서비스사업)(1468)로 등록한 자"),
    ("region", "법인등기부상 본점 소재지가 광주광역시인 업체"),
    ("company_type", "「중소기업기본법」에 따른 중소기업자로서 확인서를 소지한 자"),
    ("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 2건 이상"),
    ("staff", "총괄책임자는 관련 분야 경력 5년 이상인 자"),
    ("consortium", "공동수급체를 구성하여야 함"),
    ("disqualification", "부정당업자에 해당하지 아니한 자"),
    ("other", "현장설명에 참가한 업체로서 등록을 필한 업체"),
)


# ---------------------------------------------------------------------------
# 1) 빈 회사 사실로는 가능이 나오지 않는다
# ---------------------------------------------------------------------------


def test_빈_회사_사실로는_참가자격_조항에서_가능이_하나도_없다() -> None:
    save_clauses(*ALL_KINDS)
    results = rules(ee.CompanyFacts())
    qual = [r for r in results if r.rule_id.startswith("QUAL-") or r.clause_id]
    assert qual, "조항 줄이 하나도 없다"
    assert [r.rule_id for r in qual if r.status == "PASS"] == []
    # 조항마다 한 줄이다 — 여덟 종류가 다 있다.
    assert len([r for r in qual if r.clause_id]) == len(ALL_KINDS)
    assert {r.label for r in qual} >= {"업종 조항", "지역 조항", "기업 유형 조항", "실적 조항", "인력 조항",
                                        "공동수급 조항", "결격·등록 조항", "기타 조항"}


def test_확인_필요에는_누가_채워야_하는지가_붙는다() -> None:
    save_clauses(*ALL_KINDS)
    results = rules(ee.CompanyFacts())
    sides = {r.label: r.check_side for r in results if r.rule_id.startswith("QUAL-")}
    assert sides["업종 조항"] == "company"
    assert sides["결격·등록 조항"] == "company"
    assert sides["기타 조항"] == "notice"


# ---------------------------------------------------------------------------
# 2) 공고문을 못 읽으면 가능으로 새지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["no_section", "image", "error"])
def test_공고문을_못_읽으면_한_줄이_확인_필요로_남는다(status: str) -> None:
    save_clauses(status=status)
    doc = by_id(rules(ee.CompanyFacts()), "QUAL-DOC")
    assert doc.status == "CHECK"
    assert doc.check_side == "notice"


def test_조항_파일이_없어도_가능으로_새지_않는다() -> None:
    """필드 규칙만으로 가능이던 공고가 이제 「공고문 참가자격 절」 한 줄 때문에 확인 필요다 — 그것이 맞다."""
    # 규모 상한을 적어 두면 필드 규칙이 전부 가능이 된다(예산 5,500만 ≤ 상한 3억).
    results = rules(ee.CompanyFacts(budget_ceiling_krw=300_000_000))
    field_only = [r for r in results if r.rule_id.startswith("ELIG-")]
    assert all(r.status == "PASS" for r in field_only), [(r.rule_id, r.status) for r in field_only]
    assert by_id(results, "QUAL-DOC").status == "CHECK"
    assert ee.overall_verdict(results) == "CHECK"


def test_공고_id_를_모르면_조항을_찾을_수_없다고_적는다() -> None:
    save_clauses(*ALL_KINDS)
    results = ee.evaluate_notice_fields(raw(), as_of=NOW, company=ee.CompanyFacts())
    assert by_id(results, "QUAL-DOC").status == "CHECK"


# ---------------------------------------------------------------------------
# 3) 종류별 판정 — 양면 근거
# ---------------------------------------------------------------------------


def test_업종_조항은_등록_업종이_있으면_가능_없으면_열리는_조건() -> None:
    save_clauses(("industry", "나라장터에 소프트웨어사업자(컴퓨터관련서비스사업)(1468)로 등록한 자"))
    empty = by_id(rules(ee.CompanyFacts()), "QUAL-INDUSTRY-QC-01")
    assert empty.status == "CHECK"
    assert empty.unlock_options == ["업종코드 1468 등록 시 가능"]
    registered = by_id(rules(ee.CompanyFacts(registered_industry_codes=("1468",))), "QUAL-INDUSTRY-QC-01")
    assert registered.status == "PASS"
    assert registered.clause_id == "QC-01"


#: 실제 공고 원문(42차 BACK-R41-03) — 「모두 · 및 · 와 · 과」는 전부, 「또는 · 중 1개 이상」은 하나.
ALL_FORMS = (
    "조달청 국가종합전자조달시스템(나라장터, G2B)에 아래 업종을 모두 등록한 자 ∘ 이러닝콘텐츠업 (업종코드: 6527)"
    " ∘ 비디오물제작업 (업종코드: 3244)",
    "나라장터(G2B시스템)에 [소프트웨어사업자(컴퓨터관련서비스사업)(6527)과 정보통신공사업(3244)] 업종을 등록한 업체",
    "평생교육시설 (원격)(업종코드: 6527) 및 이러닝서비스업(업종코드: 3244)을 등록한 자",
    # 42차 마지막 검토 — 업종 사이가 「및」이면 다른 곳의 「또는」(단독 또는 공동수급)에 속지 않는다
    "단독 또는 공동수급으로 참가하는 자는 이러닝콘텐츠업(6527) 및 비디오물제작업(3244)을 등록한 자",
    "단독 또는 공동수급 모두 가능하며, 나라장터에 이러닝콘텐츠업 업종코드 6527, 비디오물제작업 업종코드 3244 를 모두 등록한 자",
)
ANY_FORMS = (
    "나라장터(G2B시스템)에 아래의 사항을 모두 입찰참가자격으로 등록한 자 [학술연구용역(6527)] 또는 [기타자유업종(3244)]"
    " 업종을 등록한 업체",
    "나라장터(G2B)에 다음 업종 중 1개 이상으로 입찰참가자격을 등록한 업체 1. 학술연구용역(업종코드 : 6527)"
    " 2. 소프트웨어사업자(업종코드 : 3244)",
    "「이러닝(전자학습)산업 발전 및 이러닝 활용 촉진에 관한 법률」에 따른 이러닝사업자(이러닝콘텐츠업. 업종코드 6527"
    " 또는 이러닝서비스업, 업종코드 3244)로서 관련 등록 요건을 충족한 자",
)


@pytest.mark.parametrize("text", ALL_FORMS)
def test_업종을_모두_요구하면_하나만_맞을_때_확인_필요다(text: str) -> None:
    save_clauses(("industry", text))
    one = by_id(rules(ee.CompanyFacts(registered_industry_codes=("6527",))), "QUAL-INDUSTRY-QC-01")
    assert one.status == "CHECK" and one.check_side == "company"
    assert one.unlock_options == ["업종코드 3244 등록 시 가능"]
    both = by_id(rules(ee.CompanyFacts(registered_industry_codes=("6527", "3244"))), "QUAL-INDUSTRY-QC-01")
    assert both.status == "PASS"


@pytest.mark.parametrize("text", ANY_FORMS)
def test_업종_중_하나면_하나만_맞아도_가능이다(text: str) -> None:
    save_clauses(("industry", text))
    one = by_id(rules(ee.CompanyFacts(registered_industry_codes=("3244",))), "QUAL-INDUSTRY-QC-01")
    assert one.status == "PASS"


def test_면허표와_같은_업종이면_조항_줄에_적고_합치지_않는다() -> None:
    """20차 §4-B — 조항은 하나씩 확인한다. 면허표 줄(공고 필드 검사)과 조항 줄(참가자격 조항)은 따로 둔다."""
    save_clauses(("industry", "나라장터에 소프트웨어사업자(컴퓨터관련서비스사업)(1468)로 등록한 자"))
    limits = [{"name": "소프트웨어사업자(컴퓨터관련서비스사업)", "code": "1468", "allowed_industries": []}]
    results = rules(ee.CompanyFacts(), raw_data={**raw(), "license_limits": limits})
    clause = by_id(results, "QUAL-INDUSTRY-QC-01")
    assert clause.reason.startswith("공고 면허표와 같은 업종입니다.")
    assert clause.check_side == "company" and "1468" in (clause.unlock_condition or "")
    table = by_id(results, "ELIG-INDUSTRY")
    assert table.clause_id is None and "1468" in table.source
    assert table.check_side == "company"


def test_지역_조항은_지역_이름이_적혔을_때만_불가다() -> None:
    save_clauses(("region", "법인등기부상 본점 소재지가 서울특별시인 업체"))
    seoul = by_id(rules(ee.CompanyFacts(location_region="전남광주")), "QUAL-REGION-QC-01")
    assert seoul.status == "FAIL"
    assert seoul.unlock_condition == "서울 소재 시 가능"
    home = by_id(rules(ee.CompanyFacts(location_region="서울")), "QUAL-REGION-QC-01")
    assert home.status == "PASS"
    unknown = by_id(rules(ee.CompanyFacts()), "QUAL-REGION-QC-01")
    assert unknown.status == "CHECK" and unknown.check_side == "company"


def test_전국은_가능이_아니라_원문_확인이다() -> None:
    """「전국 대상이니 가능」은 회사 사실 없이 나온 가능이다 — 조항 줄은 원문 확인으로 둔다."""
    save_clauses(("region", "전국 소재 업체 참가 가능"))
    results = rules(ee.CompanyFacts(location_region="전남광주"))
    region = by_id(results, "QUAL-REGION-QC-01")
    assert region.status == "CHECK" and region.check_side == "notice"
    assert by_id(results, "ELIG-REGION").clause_id is None


def test_기업_유형은_회사_인증에_있으면_가능() -> None:
    save_clauses(("company_type", "「사회적기업 육성법」에 따른 사회적기업"))
    assert by_id(rules(ee.CompanyFacts(certifications=("사회적기업",))), "QUAL-TYPE-QC-01").status == "PASS"
    missing = by_id(rules(ee.CompanyFacts(certifications=("데이터 공급기업",))), "QUAL-TYPE-QC-01")
    assert missing.status == "CHECK"
    assert missing.unlock_options == ["사회적기업 인증 시"]


@pytest.mark.parametrize(("founded", "status"), [(2024, "PASS"), (2019, "FAIL"), (2021, "CHECK")])
def test_창업_n년_이내는_설립연도로_센다(founded: int, status: str) -> None:
    save_clauses(("company_type", "공고일 기준 창업 5년 이내 기업"))
    assert by_id(rules(ee.CompanyFacts(founded_year=founded)), "QUAL-TYPE-QC-01").status == status


def test_공동수급_필수는_파트너_확보_여부로_가른다() -> None:
    save_clauses(("consortium", "공동수급체를 구성하여야 함"))
    assert by_id(rules(ee.CompanyFacts()), "QUAL-CONSORTIUM-QC-01").status == "CHECK"
    assert by_id(rules(ee.CompanyFacts(joint_bid_available=True)), "QUAL-CONSORTIUM-QC-01").status == "PASS"
    # 파트너 「없음(확인함)」도 불가가 아니다 — 함께할 회사는 구할 수 있다(35차 기본값)
    none = by_id(rules(ee.CompanyFacts(joint_bid_available=False)), "QUAL-CONSORTIUM-QC-01")
    assert none.status == "CHECK" and none.check_side == "company" and "구하면" in (none.unlock_condition or "")


@pytest.mark.parametrize("text", ["공동계약이 허용되지 않습니다.", "공동 수급(컨소시엄)은 허용하 지 않음"])
def test_허용되지_않는다는_불허로_읽는다(text: str) -> None:
    """실측 두 공고 — 공고 필드도 「공동수급불허」라 어긋남 줄이 생기면 안 된다."""
    save_clauses(("consortium", text))
    results = rules(ee.CompanyFacts(), raw_data=raw(cmmnSpldmdMethdNm="(없음)공동수급불허"))
    same = by_id(results, "QUAL-CONSORTIUM-QC-01")
    assert same.status == "CHECK" and "불허 조항" in same.reason and "허용인데" not in same.reason
    save_clauses(("consortium", "공동수급을 허용한다"))
    clash = by_id(rules(ee.CompanyFacts(), raw_data=raw(cmmnSpldmdMethdNm="(없음)공동수급불허")), "QUAL-CONSORTIUM-QC-01")
    assert clash.status == "CHECK" and "허용인데" in clash.reason


def test_공동수급체_구성_방법_안내는_필수가_아니다() -> None:
    """실측 3건 — 「공동수급체는 나라장터를 이용하여서만 구성하여야 합니다」는 방법이지 요건이 아니다."""
    save_clauses(("consortium", "공동수급체는 나라장터를 이용하여서만 구성하여야 합니다."))
    results = rules(ee.CompanyFacts(joint_bid_available=False), raw_data=raw(cmmnSpldmdMethdNm="(전자)공동이행"))
    row = by_id(results, "QUAL-CONSORTIUM-QC-01")
    assert row.status == "CHECK" and "구성이 필요" not in row.reason


def test_두_출처의_같은_조항은_한_번만_센다() -> None:
    """공고문과 제안요청서가 같은 문장을 옮겨 적는다 — 한 조항으로 센다."""
    qc.save({
        "notice_id": NOTICE_ID, "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
        "status": "ok", "page_is_approximate": False,
        "section": {"heading": "4. 입찰참가자격", "page_from": 1, "page_to": 1},
        "clauses": [{"id": "QC-01", "text": "부정당업자로 지정되지 아니한 업체", "page": 1, "kind": "disqualification"}],
        "second_source": {"document": {"name": "제안요청서.hwp", "index": 1, "format": "hwp"}, "page_is_approximate": True,
                          "section": None,
                          "clauses": [{"id": "QC-01", "text": "부정당업자로 지정되지 아니한 업체.", "page": 4, "kind": "disqualification"},
                                      {"id": "QC-02", "text": "청산·합병 등 정리절차 중이 아닌 업체", "page": 4, "kind": "disqualification"}]},
        "note": None,
    })
    rows = [r for r in rules(ee.CompanyFacts()) if r.rule_id.startswith("QUAL-DISQUAL-")]
    assert [r.clause_id for r in rows] == ["QC-01", "RFP-QC-02"]
    assert [r.source_document for r in rows] == ["입찰공고문", "제안요청서"]


def test_글머리만_다른_같은_조항은_한_줄이다() -> None:
    """실측(한양사이버대) — 공고문 조항과 RFP 요구사항이 「– 」 글머리 하나 차이로 두 줄이 됐다."""
    from types import SimpleNamespace

    save_clauses(("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 2건 이상"))
    req = SimpleNamespace(
        requirement_id="REQ-032", title="실적", content="실적", page=3,
        source_text="– 최근 3년 이내 AI 교육 용역 수행 실적 2건 이상",
    )
    assert [c.id for c in ee._clauses_of(qc.load(NOTICE_ID), [req])] == ["QC-01"]


@pytest.mark.parametrize("head", ["나. ", "가) ", "1. ", "(2) ", "① "])
def test_번호만_다른_같은_조항은_한_줄이다(head: str) -> None:
    """실측(한양사이버대) — 공고문 「국가를 당사자로 …」와 RFP 요구사항 「나. 국가를 당사자로 …」가 두 줄이 됐다(20차 검수)."""
    from types import SimpleNamespace

    text = "국가를 당사자로 하는 계약에 관한 법률 시행령 제12조 및 동법시행규칙 제14조에 의한 소정의 자격을 갖추어야 한다."
    save_clauses(("disqualification", text))
    req = SimpleNamespace(requirement_id="REQ-030", title="자격", content="자격", page=13, source_text=head + text)
    assert [c.id for c in ee._clauses_of(qc.load(NOTICE_ID), [req])] == ["QC-01"]


def test_결격_조항은_하나씩_한_줄이다() -> None:
    """20차 §4-B · ISSUE-138 — 묶음 줄(「외 n개 조항」)은 없다. 담당자가 조항마다 확인한다."""
    save_clauses(
        ("disqualification", "부정당업자에 해당하지 아니한 자"),
        ("disqualification", "조세포탈 등을 한 자로서 2년이 지나지 아니한 자는 입찰에 참여할 수 없습니다"),
    )
    rows = [r for r in rules(ee.CompanyFacts()) if r.label == "결격·등록 조항"]
    assert [r.rule_id for r in rows] == ["QUAL-DISQUAL-QC-01", "QUAL-DISQUAL-QC-02"]
    assert not [r for r in rows if "외" in r.source and "개 조항" in r.source]
    assert rows[1].clause_text == "조세포탈 등을 한 자로서 2년이 지나지 아니한 자는 입찰에 참여할 수 없습니다"
    assert rows[1].page == 2 and rows[1].kind == "disqualification"


def test_보고서_머리에_종류별_조항_수가_있다() -> None:
    save_clauses(*ALL_KINDS, ("disqualification", "청산·합병 등 정리절차 중이 아닌 업체"))
    notice = ProcurementNotice(
        id=NOTICE_ID, notice_no="R26QUAL0000001-000", title="AI 교육", agency="기관",
        published_at=datetime(2026, 8, 20, tzinfo=KST), raw_data=raw(),
    )
    view = procurement_service.NoticeView(notice=notice, match=CandidateMatch(tier="high", matched_ai=["AI"], matched_work=["교육"]))
    report = ee.evaluate_from_sources(NOTICE_ID, notice=view, parse_result=None, as_of=NOW, use_llm=False)
    assert report.clause_summary["disqualification"] == 2
    assert sum(report.clause_summary.values()) == len(ALL_KINDS) + 1 == len([r for r in report.results if r.clause_id])


# ---------------------------------------------------------------------------
# 4) 실적 조항 ↔ 실적 원장 — 창·건수·낱말
# ---------------------------------------------------------------------------


def ledger(*rows: tuple[str, str, str]) -> ee.CompanyFacts:
    packed = tuple(
        tuple((key, value) for key, value in {
            "seq": index, "year": year, "period": year, "field": "대학·교육기관", "title": title,
            "agency": "테스트대학교", "summary": summary, "amount_thousand_krw": 30000.0,
            "amount_basis": "", "evidence_note": "",
        }.items())
        for index, (year, title, summary) in enumerate(rows, start=1)
    )
    return ee.CompanyFacts(ledger_rows=packed, ledger_available=True)


def test_실적_조항은_원장에서_창_안의_낱말_맞는_행을_센다() -> None:
    save_clauses(("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 2건 이상"))
    enough = ledger(("2025", "생성형 AI 활용 교육", "교육 운영"), ("2024", "AI 리터러시 과정", "강의"))
    row = by_id(rules(enough), "QUAL-TRACK-QC-01")
    assert row.status == "PASS"
    assert "실적 목록에 비슷한 일 2건" in row.reason and "생성형 AI 활용 교육" in row.reason


def test_창_밖의_실적은_세지_않는다() -> None:
    save_clauses(("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 2건 이상"))
    old = ledger(("2025", "생성형 AI 활용 교육", "교육"), ("2019", "AI 교육 과정", "강의"))
    row = by_id(rules(old), "QUAL-TRACK-QC-01")
    assert row.status == "CHECK"
    assert "실적 목록에 비슷한 일 1건" in row.reason


def test_분야_낱말이_안_맞는_실적은_세지_않는다() -> None:
    save_clauses(("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 1건 이상"))
    row = by_id(rules(ledger(("2025", "회계 감사 용역", "재무 점검"))), "QUAL-TRACK-QC-01")
    assert row.status == "CHECK"


def test_교육_실적은_구축_실적을_채우지_않는다() -> None:
    """실측(한양사이버대) — 「AI/챗봇 … 소프트웨어 개발 분야 유사 구축 실적 3건」에 AI 교육 과정이 맞았었다.
    조항의 분야(AI · 소프트웨어)를 **모두** 담은 행만 센다."""
    save_clauses(("track_record", "최근 3년 이내 AI 챗봇 시스템 구축 유사 실적 2건 이상"))
    # 요약에 「플랫폼」「개발」이 있어도 제목이 교육이면 교육 실적이다 — 실측 행의 모양 그대로.
    education = ledger(("2025", "나만의 AI 비서 만들기 과정", "OpenAI 플랫폼으로 챗봇 개발 실습"),
                       ("2024", "AI 전문가 양성과정", "시스템 개발 실습"))
    row = by_id(rules(education), "QUAL-TRACK-QC-01")
    assert row.status == "CHECK"
    assert "실적 목록에 비슷한 일 0건" in row.reason
    built = ledger(("2025", "AI 챗봇 시스템 구축", "개발"), ("2024", "AI 상담 플랫폼 구축", "개발"))
    assert by_id(rules(built), "QUAL-TRACK-QC-01").status == "PASS"


def test_주제_없이_교육만_읽힌_실적은_확정하지_않는다() -> None:
    """실측(1728220) — 「K-pop 캠프·음악·영상 콘텐츠 창작 교육」에 AI 교육이 맞아 가능이 났었다."""
    save_clauses(("track_record", "최근 3년 이내 K-pop 캠프 등 음악·영상 콘텐츠 창작 교육 프로그램을 운영한 실적을 보유한 업체"))
    row = by_id(rules(ledger(("2025", "생성형 AI 활용 교육", "교육 운영"))), "QUAL-TRACK-QC-01")
    assert row.status == "CHECK"
    assert "「교육」뿐" in row.reason


def test_사업비_비율로_적힌_금액은_원장으로_확정하지_않는다() -> None:
    save_clauses(("track_record", "최근 3년 이내 추정가격의 70% 이상 규모의 AI 교육 실적 1건 이상"))
    row = by_id(rules(ledger(("2025", "생성형 AI 활용 교육", "교육"))), "QUAL-TRACK-QC-01")
    assert row.status == "CHECK"
    assert "사업비 비율" in row.reason


def test_원장에_없다고_불가를_내지_않는다() -> None:
    """원장에 없다 ≠ 실적이 없다 — 모자라도 확인 필요다."""
    save_clauses(("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 5건 이상"))
    row = by_id(rules(ledger(("2025", "생성형 AI 활용 교육", "교육"))), "QUAL-TRACK-QC-01")
    assert row.status == "CHECK"
    assert row.check_side == "company"


def test_원장은_내부_범위에서만_읽는다() -> None:
    facts = ee.company_facts_for("org-sample", evidence_scope="public_demo")
    assert facts.ledger_available is False and facts.ledger_rows == ()


# ---------------------------------------------------------------------------
# 5) 목록과 상세가 같은 줄
# ---------------------------------------------------------------------------


def test_목록과_상세가_같은_조항_줄을_만든다() -> None:
    save_clauses(*ALL_KINDS)
    company = ee.CompanyFacts(location_region="서울", certifications=("사회적기업",))
    listed = ee.evaluate_notice_fields(raw(), as_of=NOW, company=company, notice_id=NOTICE_ID)
    notice = ProcurementNotice(
        id=NOTICE_ID, notice_no="R26QUAL0000001-000", title="AI 교육 운영", agency="테스트기관",
        published_at=datetime(2026, 8, 20, tzinfo=KST), raw_data=raw(),
    )
    view = procurement_service.NoticeView(notice=notice, match=CandidateMatch(tier="high", matched_ai=["AI"], matched_work=["교육"]))
    report = ee.evaluate_from_sources(NOTICE_ID, notice=view, parse_result=None, as_of=NOW, use_llm=False, company=company)

    def qual(rows: list[ee.EligibilityResult]) -> list[tuple[str, str]]:
        return [(r.rule_id, r.status) for r in rows if r.rule_id.startswith("QUAL-") or r.clause_id]

    assert qual(listed) == qual(report.results)
    assert ee.overall_verdict(listed) == report.verdict
    assert report.clauses_status == "ok"
    assert report.clause_count == len(ALL_KINDS)
    assert report.clause_document == "입찰공고문.pdf"


def test_공고문을_읽었으면_RFP_파싱을_다시_요구하지_않는다() -> None:
    save_clauses(("disqualification", "부정당업자에 해당하지 아니한 자"))
    notice = ProcurementNotice(
        id=NOTICE_ID, notice_no="R26QUAL0000001-000", title="AI 교육", agency="기관",
        published_at=datetime(2026, 8, 20, tzinfo=KST), raw_data=raw(),
    )
    view = procurement_service.NoticeView(notice=notice, match=CandidateMatch(tier="high", matched_ai=["AI"], matched_work=["교육"]))
    report = ee.evaluate_from_sources(NOTICE_ID, notice=view, parse_result=None, as_of=NOW, use_llm=False)
    assert not [r for r in report.results if r.rule_id == "ELIG-RFP-DATA"]


# ---------------------------------------------------------------------------
# 6) 한 줄 요약 — 고정 문구 대신 실제 상태
# ---------------------------------------------------------------------------


def test_한_줄_요약은_조항_수와_누가_채울지를_센다() -> None:
    save_clauses(*ALL_KINDS)
    line = ee.qualification_line(rules(ee.CompanyFacts()))
    assert line is not None and line.startswith("참가자격 조항 ")
    assert "회사 정보 필요" in line and "공고문 더 읽기" in line


def test_공고문을_못_읽었으면_요약이_그렇게_말한다() -> None:
    line = ee.qualification_line(rules(ee.CompanyFacts()))
    assert line == "참가자격: 공고문의 참가자격 부분을 아직 안 읽었습니다"
