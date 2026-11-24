"""F. 엑셀 실적 원장 import — 프로필 매핑, 다른 머리글, 필수 열 오류, 금액 단위 보존, 상태값 차단, 샘플에듀 원장(있을 때만).

합성 워크북을 tmp 에 만들어 검증한다. 실제 샘플에듀 원장은 docs/SampleEdu 에 있을 때만 (없으면 skip).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.core import org_storage
from app.schemas.organization import OrganizationCreateRequest
from app.services import ledger_import_service as lis
from app.services import llm_client, organization_service
from app.services import performance_ledger as pl

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLEEDU_XLSX = REPO_ROOT / "docs" / "SampleEdu" / "sample_ledger_20260728.xlsx"
ORG = "org-demo-company"


def _workbook(headers: list[str], rows: list[list[object]], *, sheet: str = "실적", title_rows: int = 2) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for _ in range(title_rows):
        ws.append(["회사 실적표 (제목 행)"])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


SAMPLEEDU_HEADERS = ["연번", "연도", "기간", "분야", "사업·과제·연혁", "주관·발주·협력기관", "주요 내용·성과", "금액(천원)", "금액 구분", "상태", "외부 성공연혁", "증빙·주의사항"]
SAMPLEEDU_ROWS = [
    [1, "2026", "2026.07", "대학·교육기관", "AI 기초 교육", "A대학교", "자격 교육", 5000, "계산서", "완료", "가능", "계약·계산서"],
    [2, "2025", "2025.03", "공공·지자체", "업무자동화 교육", "B구청", "실습", 1900, "계산서", "완료", "증빙 확인 후", ""],
    [3, "2025", "2025", "기업·재직자·컨설팅", "데이터 분석 지원", "C사", "분석", 85000, "계산서", "검토 중", "가능", ""],
    [4, "2024", "2024", "대학·교육기관", "미선정 과제", "D대", "", None, "", "미선정", "가능", ""],
    [5, "2023", "2023", "지원사업·기관자격", "사회적기업 인증", "고용노동부", "인증", None, "", "확정", "가능", "인증서"],
]


@pytest.fixture(autouse=True)
def org(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    organization_service.create_organization(OrganizationCreateRequest(display_name="데모교육연구소", organization_id=ORG, data_class="synthetic", created_by="k"))
    return ORG


def test_inspect_finds_sheet_headers_and_values() -> None:
    payload = _workbook(SAMPLEEDU_HEADERS, SAMPLEEDU_ROWS, sheet="종합 실적 연혁")
    result = lis.inspect_upload(ORG, file_name="ledger.xlsx", payload=payload)
    assert result.organization_id == ORG and result.upload_id.startswith("LG-")
    sheet = result.sheets[0]
    assert sheet.name == "종합 실적 연혁" and sheet.header_row == 3 and sheet.row_count == 5
    assert sheet.missing_required == []
    assert sheet.suggested_mapping["title"] == "사업·과제·연혁" and sheet.suggested_mapping["external_use"] == "외부 성공연혁"
    assert set(sheet.status_values) == {"완료", "검토 중", "미선정", "확정"}
    assert set(sheet.external_use_values) == {"가능", "증빙 확인 후"}
    assert result.suggested_profile_id == lis.SAMPLEEDU_PROFILE.profile_id
    # 원장은 조직 uploads/ledger 아래에만 저장된다 (다른 조직 폴더에는 없다)
    assert (org_storage.storage_for(ORG).uploads_dir / "ledger" / f"{result.upload_id}.xlsx").exists()


def test_preview_applies_sampleedu_rules_and_blocks_unfinished_rows() -> None:
    result = lis.inspect_upload(ORG, file_name="ledger.xlsx", payload=_workbook(SAMPLEEDU_HEADERS, SAMPLEEDU_ROWS, sheet="종합 실적 연혁"))
    preview = lis.preview(ORG, lis.LedgerPreviewRequest(upload_id=result.upload_id, profile_id=lis.SAMPLEEDU_PROFILE.profile_id))
    assert preview.total_rows == 5 and preview.included == 2 and preview.excluded == 3
    by_seq = {r.seq: r for r in preview.rows}
    assert by_seq[1].eligible and by_seq[5].eligible
    assert not by_seq[2].eligible and "외부 성공연혁" in (by_seq[2].exclusion_reason or "")
    assert not by_seq[3].eligible and "상태" in (by_seq[3].exclusion_reason or "")  # 검토 중 → 완료 실적 아님
    assert not by_seq[4].eligible  # 미선정
    assert preview.amount_unit == "천원"
    assert by_seq[1].row_number == 4  # 제목 2행 + 머리글 1행 다음
    assert preview.columns_used["title"] == "사업·과제·연혁"
    assert "ledger_대학_교육기관.md" in preview.documents


def test_generic_headers_are_mapped_by_profile_and_overrides() -> None:
    headers = ["No", "년도", "수행기간", "구분", "프로젝트명", "고객사", "내용", "계약금액", "비고", "진행상태", "증빙확인", "비고2"]
    rows = [[1, "2025", "2025", "기업", "챗봇 구축", "E사", "구축", 12000000, "원", "완료", "가능", ""], [2, "2024", "2024", "기업", "교육", "F사", "교육", 3000000, "원", "진행중", "가능", ""]]
    result = lis.inspect_upload(ORG, file_name="other.xlsx", payload=_workbook(headers, rows, sheet="실적"))
    sheet = result.sheets[0]
    assert result.suggested_profile_id == lis.GENERIC_PROFILE.profile_id
    assert sheet.suggested_mapping["title"] == "프로젝트명" and sheet.suggested_mapping["agency"] == "고객사"
    preview = lis.preview(
        ORG,
        lis.LedgerPreviewRequest(
            upload_id=result.upload_id,
            profile_id=lis.GENERIC_PROFILE.profile_id,
            sheet="실적",
            column_overrides={"amount": "계약금액"},
            amount_unit="원",
            completed_statuses=["완료"],
        ),
    )
    assert preview.included == 1 and preview.excluded == 1
    assert preview.amount_unit == "원"
    # 금액을 임의로 변환하지 않는다 — 문서 문단에 원장 값과 단위가 그대로 남는다
    docs = pl.build_documents(
        pl.read_ledger_rows(org_storage.storage_for(ORG).uploads_dir / "ledger" / f"{result.upload_id}.xlsx", sheet="실적", columns=lis.GENERIC_PROFILE.columns, completed_statuses=("완료",))[0],
        source_name="other.xlsx", ledger_date="미상", sheet="실적", amount_unit="원",
    )
    body = "\n".join(docs.values())
    assert "금액 12,000,000원" in body and "원본 행 4 (시트 '실적')" in body and "amount_unit: 원" in body


def test_missing_required_column_is_a_clear_error() -> None:
    headers = ["연번", "연도", "사업·과제·연혁", "상태"]  # 외부 성공연혁 없음
    result = lis.inspect_upload(ORG, file_name="bad.xlsx", payload=_workbook(headers, [[1, "2025", "x", "완료"]], sheet="종합 실적 연혁"))
    assert "external_use" in result.sheets[0].missing_required
    with pytest.raises(lis.LedgerImportError, match="필수 열"):
        lis.preview(ORG, lis.LedgerPreviewRequest(upload_id=result.upload_id))


def test_import_registers_documents_in_review_unless_approved() -> None:
    result = lis.inspect_upload(ORG, file_name="ledger_20260728.xlsx", payload=_workbook(SAMPLEEDU_HEADERS, SAMPLEEDU_ROWS, sheet="종합 실적 연혁"))
    imported = lis.import_ledger(ORG, lis.LedgerImportRequest(upload_id=result.upload_id, reviewer="김담당", approve=False, source_name="ledger_20260728.xlsx"))
    assert imported.included == 2 and imported.ledger_date == "2026-07-28"
    assert all(r["status"] == "review" for r in imported.registered)
    from app.services import company_service as cs

    listing = cs.list_documents(ORG)
    assert listing.counts.get("review") == len(imported.registered) and not listing.counts.get("approved")
    assert cs.active_document_ids(ORG) == set()  # 승인 전에는 근거로 쓰이지 않는다
    summary = lis.summary(ORG)
    assert summary["available"] is True and summary["counts"]["eligible"] == 2 and summary["sheet"] == "종합 실적 연혁"
    # 다시 import 하면 같은 내용은 중복으로 건너뛴다
    again = lis.import_ledger(ORG, lis.LedgerImportRequest(upload_id=result.upload_id, reviewer="김담당", approve=True, source_name="ledger_20260728.xlsx"))
    assert again.skipped_duplicates and not again.registered


def test_import_with_approval_marks_approved_and_records_reviewer() -> None:
    result = lis.inspect_upload(ORG, file_name="ledger.xlsx", payload=_workbook(SAMPLEEDU_HEADERS, SAMPLEEDU_ROWS, sheet="종합 실적 연혁"))
    imported = lis.import_ledger(ORG, lis.LedgerImportRequest(upload_id=result.upload_id, reviewer="박승인", approve=True))
    assert imported.approved and all(r["status"] == "approved" for r in imported.registered)
    from app.services import company_service as cs

    doc = cs.get_document(ORG, imported.registered[0]["document_id"])
    assert doc.metadata.approved_by == "박승인" and doc.organization_id == ORG


@pytest.mark.skipif(not SAMPLEEDU_XLSX.exists(), reason="샘플에듀 원장 원본이 없는 환경")
def test_sampleedu_ledger_keeps_42_included_16_excluded() -> None:
    rows = pl.read_ledger(SAMPLEEDU_XLSX)
    assert len(rows) == 58
    assert sum(1 for r in rows if r.eligible) == 42
    assert sum(1 for r in rows if not r.eligible) == 16
    # 프로필 경로로 읽어도 같은 결과
    rows2, used = pl.read_ledger_rows(SAMPLEEDU_XLSX, sheet=pl.MASTER_SHEET, columns=lis.SAMPLEEDU_PROFILE.columns)
    assert sum(1 for r in rows2 if r.eligible) == 42 and used["external_use"]
