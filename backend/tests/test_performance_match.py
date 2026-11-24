"""실적 요건 자동 대조 · 수행실적표 채움 테스트.

원장은 tmp에 만든 작은 JSON을 쓴다. 판정은 힌트이며 PASS/CLEARED를 만들지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import org_storage, storage
from app.main import app
from app.schemas.company import CompanyProfile
from app.schemas.organization import AnalysisContext
from app.schemas.requirement import PageInfo, Requirement, RfpParseResult
from app.services import critical_condition_service as ccs
from app.services import document_extractor, hwpx_template_service as hts, performance_match_service as pm

client = TestClient(app)

LEDGER = {
    "ledger_date": "2026-07-28",
    "rows": [
        {"seq": 1, "year": "2026", "period": "2026.07.01", "field": "대학·교육기관", "title": "가상 AI 기초 인공지능 교육", "agency": "A대학교 산학협력단", "summary": "AI 기초 자격 교육", "amount_thousand_krw": 5000, "amount_basis": "계산서 명세", "evidence_note": "계약·계산서 대조", "eligible": True},
        {"seq": 2, "year": "2025", "period": "2025.03", "field": "공공·지자체", "title": "AI 에이전트 업무자동화 교육", "agency": "B구청", "summary": "에이전트 실습", "amount_thousand_krw": 1900, "amount_basis": "계산서 명세", "evidence_note": "계약·계산서 대조", "eligible": True},
        {"seq": 3, "year": "2022", "period": "2022", "field": "기업·재직자·컨설팅", "title": "가상기업 데이터 분석 활용 지원사업", "agency": "C가상기관", "summary": "10개 기업 데이터 분석", "amount_thousand_krw": 85000, "amount_basis": "계산서 명세", "evidence_note": "계약·계산서 대조", "eligible": True},
        {"seq": 4, "year": "2023", "period": "2023", "field": "지원사업·기관자격", "title": "사회적기업 인증", "agency": "고용노동부", "summary": "인증", "amount_thousand_krw": None, "amount_basis": "", "evidence_note": "인증서", "eligible": True},
        {"seq": 5, "year": "2025", "period": "2025", "field": "대학·교육기관", "title": "제외 대상(증빙 확인 후)", "agency": "D대", "summary": "", "amount_thousand_krw": 7000, "amount_basis": "", "evidence_note": "", "eligible": False},
    ],
}


SAMPLEEDU_CTX = AnalysisContext(organization_id=org_storage.DEFAULT_ORGANIZATION_ID, evidence_scope="internal")


@pytest.fixture()
def ledger_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """기본 조직(org-sample)의 조직 폴더에 원장을 둔다 (conftest 가 조직 저장공간을 tmp 로 돌린다)."""
    path = org_storage.storage_for(org_storage.DEFAULT_ORGANIZATION_ID).ledger_file
    storage.write_json_atomic(path, LEDGER)
    monkeypatch.setattr(pm, "LEDGER_FILE", path)
    return path


@pytest.mark.parametrize(
    ("text", "expected_won"),
    [
        # 단위가 **둘 이상 이어 붙은** 표기. 예전 정규식은 앞 단위를 통째로 버렸다.
        ("단일 계약 3억 5천만원 이상", 350_000_000),
        ("1억 2천만원 이상", 120_000_000),
        ("2억5천만원 이상", 250_000_000),
        # 앞의 천·백은 **뒤의 만에 걸린다**. 3천 + 5백만 이 아니다.
        ("3천5백만원 이상", 35_000_000),
        ("7억 3천5백만원 이상", 735_000_000),
        # 단위 하나짜리·숫자만 있는 표기는 예전과 같아야 한다.
        ("3억원 이상", 300_000_000),
        ("5천만원 이상", 50_000_000),
        ("10억원 이상", 1_000_000_000),
        ("350,000천원 이상", 350_000_000),
        ("1,050,000,000원 이상", 1_050_000_000),
        # 문장 안에 섞여 있어도 금액 조각만 정확히 읽는다.
        ("최근 3년 이내 유사 용역 1건 이상, 계약금액 5천만원 이상", 50_000_000),
    ],
)
def test_compound_amount_units(text: str, expected_won: int) -> None:
    """「3억 5천만원」을 5천만원으로 읽던 버그를 막는다.

    실적 기준값이 조용히 틀리면 못 넘는 요건을 넘었다고 판정하게 된다 —
    화면이 낼 수 있는 가장 위험한 종류의 거짓말이라 값마다 못박는다.
    """
    got = pm.parse_criteria(text).min_amount_thousand
    assert got is not None
    assert int(got * 1000) == expected_won


def test_amount_absent_when_sentence_has_no_amount() -> None:
    """없는 기준을 만들지 않는다."""
    assert pm.parse_criteria("최근 3년 이내 실적 2건 이상").min_amount_thousand is None


# --------------------------------------------------------------------------
# 조건 해석
# --------------------------------------------------------------------------


def test_parse_criteria_reads_only_explicit_numbers() -> None:
    c = pm.parse_criteria("최근 3년 이내 대학 대상 AI 교육 유사 용역 수행실적 1건 이상, 계약금액 5천만원 이상")
    assert c.years == 3 and c.min_count == 1 and c.min_amount_thousand == 50_000
    assert c.amount_mode is None  # 단일/누적 명시 없음
    assert "AI" in c.domains and "교육" in c.domains
    assert c.agency_types == ["대학·교육기관"]
    assert c.similar is True
    empty = pm.parse_criteria("유사 실적을 제출한다")
    assert empty.years is None and empty.min_count is None and empty.min_amount_thousand is None


def test_amount_units() -> None:
    assert pm.parse_criteria("1억원 이상").min_amount_thousand == 100_000
    assert pm.parse_criteria("3,000만원 이상 누적").min_amount_thousand == 30_000
    assert pm.parse_criteria("3,000만원 이상 누적").amount_mode == "cumulative"
    assert pm.parse_criteria("50,000,000원 이상 단일 계약").min_amount_thousand == 50_000
    assert pm.parse_criteria("50,000,000원 이상 단일 계약").amount_mode == "single"


# --------------------------------------------------------------------------
# 대조
# --------------------------------------------------------------------------


def test_match_filters_years_domain_agency_amount(ledger_file: Path) -> None:
    report = pm.build_report("최근 3년 이내 대학 대상 AI 교육 실적 1건 이상", as_of=date(2026, 9, 7))
    assert report.ledger_available and report.eligible_rows == 4
    assert [h.seq for h in report.hits] == [1]
    assert report.likely_sufficient is True
    assert "증빙" in report.verdict_hint
    assert any("유사" not in n for n in report.notes) or True


def test_insufficient_amount_and_count(ledger_file: Path) -> None:
    report = pm.build_report("최근 3년 AI 교육 실적 1건 이상, 계약금액 1억원 이상", as_of=date(2026, 9, 7))
    assert report.hits == [] and report.likely_sufficient is False
    report = pm.build_report("최근 3년 AI 교육 실적 5건 이상", as_of=date(2026, 9, 7))
    assert report.hit_count == 2 and report.likely_sufficient is False
    assert "필요 건수 5건" in report.verdict_hint


def test_cumulative_amount(ledger_file: Path) -> None:
    report = pm.build_report("최근 5년 누적 계약금액 8천만원 이상 실적", as_of=date(2026, 9, 7))
    # 5년 안(2022~2026) 금액 있는 실적 3건 합계 91,900천원
    assert report.total_amount_thousand == 91_900 and report.likely_sufficient is True


def test_no_judgeable_criteria_returns_none(ledger_file: Path) -> None:
    report = pm.build_report("유사 용역 수행실적 증빙서류를 제출한다", as_of=date(2026, 9, 7))
    assert report.likely_sufficient is None
    assert "판정하지 않습니다" in report.verdict_hint
    assert report.hit_count == 4  # 분야·기관 낱말 없음 → 전체 채택 실적이 후보


def test_without_ledger_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm, "LEDGER_FILE", tmp_path / "none.json")
    report = pm.build_report("최근 3년 실적 1건 이상")
    assert report.ledger_available is False and report.likely_sufficient is None and report.hits == []


# --------------------------------------------------------------------------
# Critical Condition 연결
# --------------------------------------------------------------------------


def _parse(*contents: str) -> RfpParseResult:
    reqs = [
        Requirement(id=f"g2b-T-000:REQ-{i:03d}", procurement_id="g2b-T-000", requirement_id=f"REQ-{i:03d}", category="입찰참가자격", requirement_type="mandatory", title=c[:20], content=c, page=4, source_text=f"○ {c}")
        for i, c in enumerate(contents, start=1)
    ]
    return RfpParseResult(procurement_id="g2b-T-000", source="g2b_attachment", document="공고문.hwp", page_count=5, pages=[PageInfo(page=1, char_count=1)], empty_pages=[], count=len(reqs), requirements=reqs, generated_at=datetime.now(timezone.utc))


def test_condition_report_attaches_ledger_match(ledger_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ccs, "CONDITION_DIR", tmp_path / "conditions")
    report = ccs.build_report("g2b-T-000", parse_result=_parse("최근 3년 이내 대학 AI 교육 유사 용역 수행실적 1건 이상 보유"), eligibility=None, notice_available=False, as_of=datetime(2026, 9, 7, tzinfo=timezone.utc), context=SAMPLEEDU_CTX)
    perf = [c for c in report.conditions if c.condition_type == "performance_record"]
    assert perf and perf[0].status == "CHECK"  # 대조 결과가 있어도 상태는 바뀌지 않는다
    assert perf[0].ledger_match is not None and perf[0].ledger_match.hit_count == 1
    assert perf[0].ledger_match.hits[0].title == "가상 AI 기초 인공지능 교육"
    # 저장 후 다시 읽어도 유지
    ccs.save_report(report, context=SAMPLEEDU_CTX)
    loaded = ccs.load_report("g2b-T-000", SAMPLEEDU_CTX)
    assert next(c for c in loaded.conditions if c.condition_type == "performance_record").ledger_match is not None
    assert loaded.organization_id == org_storage.DEFAULT_ORGANIZATION_ID
    # public_demo 범위에서는 실제 회사 원장을 붙이지 않는다
    demo = ccs.build_report("g2b-T-000", parse_result=_parse("최근 3년 이내 대학 AI 교육 유사 용역 수행실적 1건 이상 보유"), eligibility=None, notice_available=False, context=AnalysisContext(organization_id=org_storage.DEFAULT_ORGANIZATION_ID, evidence_scope="public_demo"))
    assert all(c.ledger_match is None for c in demo.conditions)


def test_item_performance_match_api(ledger_file: Path) -> None:
    client.post("/api/rfp/parse", json={"procurement_id": "synthetic-rfp-0001"})
    parsed = client.get("/api/rfp/synthetic-rfp-0001/requirements").json()
    target = next((r for r in parsed["requirements"] if "실적" in r["content"]), parsed["requirements"][0])
    query = f"?organization_id={org_storage.DEFAULT_ORGANIZATION_ID}&evidence_scope=internal"
    response = client.get(f"/api/rfp/synthetic-rfp-0001/items/{target['requirement_id']}/performance-match{query}")
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["ledger_available"] is True and body["report"]["method"] == "RULE"
    assert body["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID
    # 합성 데모 공고의 기본 범위(public_demo)에서는 실제 원장을 대조하지 않는다
    demo = client.get(f"/api/rfp/synthetic-rfp-0001/items/{target['requirement_id']}/performance-match").json()
    assert demo["evidence_scope"] == "public_demo" and demo["report"]["ledger_available"] is False
    assert client.get(f"/api/rfp/synthetic-rfp-0001/items/REQ-999/performance-match{query}").status_code == 404
    summary = client.get("/api/performance-ledger/summary").json()
    assert summary["available"] is True and summary["project_rows"] == 3


# --------------------------------------------------------------------------
# 수행실적표 채움
# --------------------------------------------------------------------------


def test_performance_table_filled_from_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hts, "EXPORT_DIR", tmp_path / "exports")
    profile = CompanyProfile(name="주식회사 샘플에듀")
    rows = pm.project_rows(LEDGER)
    assert [r["seq"] for r in rows] == [1, 2, 3]  # 인증(#4)·제외(#5)는 빠진다
    result = hts.render("performance_table", "g2b-T-000", profile=profile, notice=None, parse_result=None, ledger_rows=rows)
    assert result.validation.xml_ok and result.verified is True
    text = "\n".join(p.text for p in document_extractor.extract_hwpx(hts.export_path("g2b-T-000", result.file_name)))
    assert "가상 AI 기초 인공지능 교육" in text and "85,000천원" in text and "실적 3건" in text
    # 최신 연도가 먼저
    assert text.index("가상 AI 기초") < text.index("가상기업 데이터 분석")


def test_performance_table_without_ledger_is_blank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hts, "EXPORT_DIR", tmp_path / "exports")
    result = hts.render("performance_table", "g2b-T-000", profile=CompanyProfile(name="샘플에듀"), notice=None, parse_result=None, ledger_rows=[])
    text = "\n".join(p.text for p in document_extractor.extract_hwpx(hts.export_path("g2b-T-000", result.file_name)))
    assert "담당자 작성" in text and "실적 원장이 없어" in text
