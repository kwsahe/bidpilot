"""실적 원장(xlsx) → 조직별 근거 문서·구조화 JSON. 회사별 **import profile** 로 열·상태값 매핑을 분리한다.

샘플에듀 원장의 규칙(시트 「종합 실적 연혁」, 「외부 성공연혁 = 가능」, 상태 완료/확정/등록)은 기본 프로필
`sampleedu-performance-ledger-v1` 에만 있다. 다른 회사는 시트·열·상태값을 프로필로 바꾸거나 화면에서 매핑을 고친다.

흐름 (자동 추정은 preview 까지만):
  1. inspect  — 업로드한 xlsx 의 시트 목록·머리글 행·열 매핑 후보·상태값·외부사용값 (추정, 확정 아님)
  2. preview  — 프로필(+수정 매핑)로 변환했을 때 포함·제외 건수와 사유, 금액 단위, 주의사항
  3. import   — 담당자 승인 후 조직 등록부에 문서 등록(+검토 채택+승인). 승인자 이름이 기록에 남는다.

원본 추적: 근거 문단마다 원본 파일명·시트명·행 번호·원자료 식별번호(연번)·금액 단위·증빙상태를 남긴다.
금액은 원장 단위 그대로(기본 천원) 옮기고 임의 변환하지 않는다.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core import org_storage, storage
from app.services import performance_ledger as pl

MAX_LEDGER_BYTES = 20 * 1024 * 1024
LEDGER_UPLOAD_DIR_NAME = "ledger"


class LedgerImportError(ValueError):
    """시트·열·값 매핑이 맞지 않아 진행할 수 없다 (사용자가 매핑을 고쳐야 한다)."""


class LedgerImportProfile(BaseModel):
    """회사별 원장 매핑 프로필. 필수 열: seq·title·status·external_use."""

    profile_id: str = Field(min_length=1, max_length=80)
    label: str = ""
    sheet: str | None = None
    columns: dict[str, list[str]] = Field(default_factory=dict)
    # 「외부 성공연혁」 열이 이 값일 때만 근거로 채택
    approved_values: list[str] = Field(default_factory=lambda: [pl.EXTERNAL_OK])
    # 상태 열이 이 값 중 하나여야 완료 실적으로 본다 (미선정·검토 중·증빙 확인 전은 들어오지 않는다)
    completed_statuses: list[str] = Field(default_factory=lambda: list(pl.COMPLETED_STATUSES))
    amount_unit: str = "천원"
    note: str | None = None


SAMPLEEDU_PROFILE = LedgerImportProfile(
    profile_id="sampleedu-performance-ledger-v1",
    label="종합 실적 연혁 형식 (2026-07)",
    sheet=pl.MASTER_SHEET,
    columns={key: list(names) for key, names in pl.DEFAULT_COLUMNS.items()},
    approved_values=[pl.EXTERNAL_OK],
    completed_statuses=list(pl.COMPLETED_STATUSES),
    amount_unit="천원",
    note="열 이름으로 찾으므로 열 순서가 바뀌어도 된다. 다른 회사는 columns·approved_values·completed_statuses 를 바꾼다.",
)

GENERIC_PROFILE = LedgerImportProfile(
    profile_id="generic-performance-ledger-v1",
    label="일반 실적표 (매핑 직접 확인)",
    sheet=None,
    columns={
        "seq": ["연번", "번호", "No", "no"],
        "year": ["연도", "년도"],
        "period": ["기간", "수행기간", "계약기간"],
        "field": ["분야", "구분"],
        "title": ["사업명", "프로젝트명", "과제명", "사업·과제·연혁", "용역명"],
        "agency": ["발주기관", "고객사", "주관·발주·협력기관", "발주처"],
        "summary": ["주요 내용", "내용", "주요 내용·성과", "성과"],
        "amount": ["계약금액", "금액", "금액(천원)", "금액(원)"],
        "amount_basis": ["금액 구분", "금액구분", "비고"],
        "status": ["상태", "진행상태", "진행 상태"],
        "external_use": ["외부 성공연혁", "증빙확인", "외부 사용", "외부공개"],
        "evidence_note": ["증빙·주의사항", "증빙", "비고"],
    },
    note="머리글을 자동으로 찾지만 확정은 담당자가 한다. 상태값·외부사용값도 preview 에서 확인한다.",
)


def builtin_profiles() -> list[LedgerImportProfile]:
    return [SAMPLEEDU_PROFILE, GENERIC_PROFILE]


def profile_by_id(profile_id: str) -> LedgerImportProfile:
    for profile in builtin_profiles():
        if profile.profile_id == profile_id:
            return profile
    raise LedgerImportError(f"없는 프로필입니다: {profile_id}")


# --------------------------------------------------------------------------
# 업로드 보관
# --------------------------------------------------------------------------


def _ledger_upload_dir(organization_id: str) -> Path:
    return org_storage.storage_for(organization_id).uploads_dir / LEDGER_UPLOAD_DIR_NAME


def _stored_path(organization_id: str, upload_id: str) -> Path:
    return _ledger_upload_dir(organization_id) / f"{storage.safe_id(upload_id, what='업로드 id')}.xlsx"


class SheetInfo(BaseModel):
    name: str
    header_row: int | None
    headers: list[str]
    row_count: int
    suggested_mapping: dict[str, str | None]
    missing_required: list[str]
    status_values: list[str]
    external_use_values: list[str]


class LedgerInspectResult(BaseModel):
    organization_id: str
    upload_id: str
    file_name: str
    sheets: list[SheetInfo]
    suggested_sheet: str | None
    suggested_profile_id: str
    note: str


def inspect_upload(organization_id: str, *, file_name: str, payload: bytes) -> LedgerInspectResult:
    if not payload:
        raise LedgerImportError("빈 파일입니다")
    if len(payload) > MAX_LEDGER_BYTES:
        raise LedgerImportError("업로드 상한(20MB)을 초과했습니다")
    if not file_name.lower().endswith(".xlsx"):
        raise LedgerImportError("실적 원장은 .xlsx 만 지원합니다")
    upload_id = f"LG-{hashlib.sha256(payload).hexdigest()[:12]}"
    target = _stored_path(organization_id, upload_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return inspect_workbook(organization_id, upload_id, file_name=file_name)


def inspect_workbook(organization_id: str, upload_id: str, *, file_name: str) -> LedgerInspectResult:
    path = _stored_path(organization_id, upload_id)
    if not path.exists():
        raise LedgerImportError("업로드한 원장을 찾지 못했습니다. 다시 올려 주세요.")
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise LedgerImportError(f"openpyxl을 불러올 수 없습니다: {exc}") from exc
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    sheets: list[SheetInfo] = []
    for name in workbook.sheetnames:
        rows = [list(r) for r in workbook[name].iter_rows(values_only=True)]
        header_index, columns = pl.find_header(rows, GENERIC_PROFILE.columns | {k: SAMPLEEDU_PROFILE.columns[k] + GENERIC_PROFILE.columns.get(k, []) for k in SAMPLEEDU_PROFILE.columns})
        headers = [pl._cell(c) for c in rows[header_index]] if header_index is not None else []
        status_values: set[str] = set()
        external_values: set[str] = set()
        data_rows = rows[header_index + 1 :] if header_index is not None else []
        for raw in data_rows:
            if "status" in columns and columns["status"] < len(raw):
                value = pl._cell(raw[columns["status"]])
                if value:
                    status_values.add(value)
            if "external_use" in columns and columns["external_use"] < len(raw):
                value = pl._cell(raw[columns["external_use"]])
                if value:
                    external_values.add(value)
        mapping = {key: (headers[index] if index < len(headers) else None) for key, index in columns.items()}
        for key in pl.DEFAULT_COLUMNS:
            mapping.setdefault(key, None)
        sheets.append(
            SheetInfo(
                name=name,
                header_row=(header_index + 1) if header_index is not None else None,
                headers=headers,
                row_count=len(data_rows),
                suggested_mapping=mapping,
                missing_required=[k for k in pl.REQUIRED_COLUMNS if not mapping.get(k)],
                status_values=sorted(status_values),
                external_use_values=sorted(external_values),
            )
        )
    suggested = next((s.name for s in sheets if not s.missing_required), None)
    suggested_profile = SAMPLEEDU_PROFILE.profile_id if suggested == pl.MASTER_SHEET else GENERIC_PROFILE.profile_id
    return LedgerInspectResult(
        organization_id=organization_id,
        upload_id=upload_id,
        file_name=Path(file_name).name,
        sheets=sheets,
        suggested_sheet=suggested,
        suggested_profile_id=suggested_profile,
        # 45차 M20 — 화면에 그대로 나오는 글이라 존댓말 · 한국어로(「preview 에서 … 등록한다」가 보였다)
        note="엑셀 칸 맞추기 · 상태값 · 외부 사용값은 자동으로 짐작한 것이라 확정이 아닙니다. 「미리 보기」에서 넣을 줄 · 뺄 줄 수와 사유를 확인한 뒤 등록하세요.",
    )


# --------------------------------------------------------------------------
# preview / import
# --------------------------------------------------------------------------


class LedgerPreviewRequest(BaseModel):
    upload_id: str = Field(min_length=3, max_length=40)
    profile_id: str = Field(default=SAMPLEEDU_PROFILE.profile_id, max_length=80)
    sheet: str | None = Field(default=None, max_length=100)
    # 사용자가 고친 열 매핑 (필드 → 머리글). 프로필 후보보다 우선한다.
    column_overrides: dict[str, str] = Field(default_factory=dict)
    approved_values: list[str] | None = None
    completed_statuses: list[str] | None = None
    amount_unit: str | None = Field(default=None, max_length=10)


class LedgerImportRequest(LedgerPreviewRequest):
    reviewer: str = Field(min_length=1, max_length=60)
    # 후보 문단을 모두 채택하고 승인까지 진행할지. False 면 「검토 필요」로 남긴다.
    approve: bool = False
    source_name: str | None = Field(default=None, max_length=200)


class PreviewRow(BaseModel):
    seq: int
    row_number: int
    title: str
    status: str
    external_use: str
    eligible: bool
    exclusion_reason: str | None
    warnings: list[str]


class LedgerPreviewResult(BaseModel):
    organization_id: str
    upload_id: str
    profile_id: str
    sheet: str
    columns_used: dict[str, str]
    approved_values: list[str]
    completed_statuses: list[str]
    amount_unit: str
    total_rows: int
    included: int
    excluded: int
    exclusion_reasons: dict[str, int]
    by_group: dict[str, int]
    documents: list[str]
    rows: list[PreviewRow]
    warnings: list[str]


def _effective_profile(request: LedgerPreviewRequest) -> LedgerImportProfile:
    base = profile_by_id(request.profile_id)
    columns = {k: list(v) for k, v in base.columns.items()}
    for key, header in request.column_overrides.items():
        if header:
            columns[key] = [header, *columns.get(key, [])]
    return base.model_copy(
        update={
            "sheet": request.sheet or base.sheet,
            "columns": columns,
            "approved_values": request.approved_values or base.approved_values,
            "completed_statuses": request.completed_statuses or base.completed_statuses,
            "amount_unit": request.amount_unit or base.amount_unit,
        }
    )


def _read_rows(organization_id: str, request: LedgerPreviewRequest) -> tuple[LedgerImportProfile, str, list[pl.LedgerRow], dict[str, str]]:
    path = _stored_path(organization_id, request.upload_id)
    if not path.exists():
        raise LedgerImportError("업로드한 원장을 찾지 못했습니다. 다시 올려 주세요.")
    profile = _effective_profile(request)
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise LedgerImportError(f"openpyxl을 불러올 수 없습니다: {exc}") from exc
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    sheet = profile.sheet or (workbook.sheetnames[0] if workbook.sheetnames else None)
    if not sheet or sheet not in workbook.sheetnames:
        raise LedgerImportError(f"시트 '{sheet}'가 없습니다. 있는 시트: {workbook.sheetnames}")
    try:
        rows, columns_used = pl.read_ledger_rows(
            path,
            sheet=sheet,
            columns=profile.columns,
            approved_values=tuple(profile.approved_values),
            completed_statuses=tuple(profile.completed_statuses),
        )
    except pl.LedgerFormatError as exc:
        raise LedgerImportError(str(exc)) from exc
    return profile, sheet, rows, columns_used


def preview(organization_id: str, request: LedgerPreviewRequest) -> LedgerPreviewResult:
    profile, sheet, rows, columns_used = _read_rows(organization_id, request)
    reasons: dict[str, int] = {}
    for row in rows:
        if not row.eligible and row.exclusion_reason:
            key = re.sub(r"'[^']*'", "'…'", row.exclusion_reason)
            reasons[key] = reasons.get(key, 0) + 1
    eligible = [r for r in rows if r.eligible]
    by_group: dict[str, int] = {}
    for row in eligible:
        by_group[pl.group_key(row)] = by_group.get(pl.group_key(row), 0) + 1
    documents = pl.build_documents(rows, source_name="preview.xlsx", ledger_date="미상", sheet=sheet, amount_unit=profile.amount_unit)
    warnings = [f"#{r.seq} {r.title[:40]} — {'; '.join(r.warnings)}" for r in eligible if r.warnings]
    return LedgerPreviewResult(
        organization_id=organization_id,
        upload_id=request.upload_id,
        profile_id=profile.profile_id,
        sheet=sheet,
        columns_used=columns_used,
        approved_values=list(profile.approved_values),
        completed_statuses=list(profile.completed_statuses),
        amount_unit=profile.amount_unit,
        total_rows=len(rows),
        included=len(eligible),
        excluded=len(rows) - len(eligible),
        exclusion_reasons=reasons,
        by_group=by_group,
        documents=sorted(documents),
        rows=[
            PreviewRow(
                seq=r.seq, row_number=r.row_number, title=r.title, status=r.status, external_use=r.external_use,
                eligible=r.eligible, exclusion_reason=r.exclusion_reason, warnings=list(r.warnings),
            )
            for r in rows
        ],
        warnings=warnings,
    )


class LedgerImportResult(BaseModel):
    organization_id: str
    upload_id: str
    profile_id: str
    sheet: str
    source_name: str
    ledger_date: str
    included: int
    excluded: int
    registered: list[dict[str, Any]]
    skipped_duplicates: list[str]
    approved: bool
    ledger_file_written: bool
    note: str


def import_ledger(organization_id: str, request: LedgerImportRequest) -> LedgerImportResult:
    """담당자 승인 후 등록. 문서마다 등록부에 올리고(검토 필요), approve=True 면 후보 채택+승인까지."""
    from app.schemas.company import CandidateReview, CandidateReviewRequest, DocumentApproveRequest
    from app.services import company_service as cs

    profile, sheet, rows, _columns = _read_rows(organization_id, request)
    source_name = (request.source_name or f"{request.upload_id}.xlsx").strip()
    ledger_date = pl.ledger_date_from_name(source_name)
    documents = pl.build_documents(rows, source_name=source_name, ledger_date=ledger_date, sheet=sheet, amount_unit=profile.amount_unit)
    store = org_storage.storage_for(organization_id)
    store.ledger_docs_dir.mkdir(parents=True, exist_ok=True)
    for name, body in documents.items():
        (store.ledger_docs_dir / name).write_text(body, encoding="utf-8")
    payload = pl.ledger_payload(rows, source_name=source_name, ledger_date=ledger_date, sheet=sheet, amount_unit=profile.amount_unit)
    payload["organization_id"] = organization_id
    payload["profile_id"] = profile.profile_id
    storage.write_json_atomic(store.ledger_file, payload)

    registered: list[dict[str, Any]] = []
    skipped: list[str] = []
    reviewer = request.reviewer.strip()
    for name, body in documents.items():
        try:
            detail = cs.register_upload(
                organization_id, file_name=name, payload=body.encode("utf-8"), doc_type="수행실적", uploaded_by=reviewer, data_class="real"
            )
        except cs.DuplicateDocumentError as exc:
            skipped.append(f"{name} (기존 {exc.existing_id})")
            continue
        entry: dict[str, Any] = {"file_name": name, "document_id": detail.id, "status": detail.status, "candidates": detail.candidate_count}
        if request.approve and detail.status == "review":
            candidates = [c for c in detail.candidates if not c.is_gap]
            cs.review_candidates(
                organization_id,
                detail.id,
                CandidateReviewRequest(reviewer=reviewer, reviews=[CandidateReview(candidate_id=c.id, approved=True) for c in candidates]),
            )
            approved = cs.approve_document(
                organization_id,
                detail.id,
                DocumentApproveRequest(
                    reviewer=reviewer,
                    data_class="real",
                    scope="internal",
                    note=f"실적 원장 일괄 등록 — 프로필 {profile.profile_id} · 채택값 {', '.join(profile.approved_values)} · 시트 '{sheet}' ({ledger_date} 원장). 사용 전 증빙 대조.",
                ),
            )
            entry["status"] = approved.status
            entry["approved_chunks"] = approved.approved_chunk_count
        registered.append(entry)

    eligible = sum(1 for r in rows if r.eligible)
    return LedgerImportResult(
        organization_id=organization_id,
        upload_id=request.upload_id,
        profile_id=profile.profile_id,
        sheet=sheet,
        source_name=source_name,
        ledger_date=ledger_date,
        included=eligible,
        excluded=len(rows) - eligible,
        registered=registered,
        skipped_duplicates=skipped,
        approved=request.approve,
        ledger_file_written=True,
        note="원장 행은 문단 1개로 옮겼고 문장을 지어내지 않았다. 승인하지 않은 문서는 「검토 필요」로 남아 근거로 쓰이지 않는다.",
    )


def summary(organization_id: str) -> dict[str, Any]:
    """조직 실적 원장 요약 (행 본문은 돌려주지 않는다)."""
    from app.services import performance_match_service as pm

    ledger = pm.load_ledger(pm.ledger_path_for(organization_id))
    if ledger is None:
        return {"organization_id": organization_id, "available": False, "note": "실적 원장이 변환되지 않았습니다. 회사자료 화면에서 원장을 올리세요."}  # 스크립트 경로 · 옛 화면 이름을 화면에 적지 않는다(27차 §3-H)
    return {
        "organization_id": organization_id,
        "available": True,
        "ledger_date": ledger.get("ledger_date"),
        "source_file": ledger.get("source_file"),
        "sheet": ledger.get("sheet"),
        "amount_unit": ledger.get("amount_unit", "천원"),
        "profile_id": ledger.get("profile_id"),
        "counts": ledger.get("counts"),
        "by_group": ledger.get("by_group"),
        "project_rows": len(pm.project_rows(ledger)),
        "converted_at": ledger.get("converted_at"),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
