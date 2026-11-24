"""회사자료 등록 파이프라인 테스트 (업로드 → 추출 → 검토 → 승인 → 색인/역추적) — 조직별.

네트워크·임베딩 호출 없음. 키가 없을 때 '승인·색인 대기'로 정직하게 남는지도 확인한다.
저장 경로는 conftest 가 tmp 로 돌린다 — 실제 data/private·data/company 를 건드리지 않는다.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import org_storage
from app.main import app
from app.schemas.company import (
    CandidateReview,
    CandidateReviewRequest,
    DocumentApproveRequest,
    DocumentRetireRequest,
)
from app.schemas.organization import AnalysisContext, OrganizationCreateRequest, OrganizationProfileUpdate
from app.services import company_service as cs
from app.services import evidence_service, llm_client, organization_service

client = TestClient(app)

ORG = "org-testco"

MD_DOC = """---
document_name: 교육 운영 매뉴얼(테스트)
doc_type: 운영 매뉴얼
---

> 테스트용 문서입니다.

# 교육 운영 체계

수강생별 교육용 계정을 일괄 생성하고 종료 후 회수하는 절차를 운영합니다. 출결과 만족도 조사를 매 회차 기록합니다.

# 강사 배정

생성형 AI 실무 강의 경력이 3년 이상인 강사를 배정하고, 보조 강사를 회차당 1명 이상 둡니다.

# 확인되지 않은 사항

연도별 누적 교육생 수는 공개 자료에서 확인되지 않았습니다.
"""


@pytest.fixture(autouse=True)
def test_org(monkeypatch: pytest.MonkeyPatch) -> str:
    # 임베딩 키 없음 (색인은 만들지 않는다)
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    # 실제 자료 등급 회사 — internal 범위는 실제·비식별 문단만 본다
    organization_service.create_organization(
        OrganizationCreateRequest(display_name="테스트회사", organization_id=ORG, data_class="real", created_by="김담당")
    )
    return ORG


def upload_md(name: str = "manual.md", text: str = MD_DOC, org: str = ORG):
    return cs.register_upload(org, file_name=name, payload=text.encode("utf-8"), doc_type="운영 매뉴얼", uploaded_by="김담당")


# --------------------------------------------------------------------------
# 프로필
# --------------------------------------------------------------------------


def test_profile_defaults_to_synthetic_when_no_file() -> None:
    profile = organization_service.load_profile(ORG)
    assert profile.source == "default_synthetic"
    assert profile.data_class == "synthetic"
    assert profile.organization_id == ORG
    assert "생성형 AI 교육" in profile.business_domains


def test_profile_save_and_reload() -> None:
    saved = organization_service.save_profile(
        ORG,
        OrganizationProfileUpdate(name="테스트회사", business_domains=["AI 교육"], preferred_regions=["광주광역시"], updated_by="김담당", data_class="real"),
    )
    assert saved.source == "file"
    again = organization_service.load_profile(ORG)
    assert again.name == "테스트회사" and again.updated_at is not None and again.approved_for_public is False
    assert again.organization_id == ORG
    assert organization_service.preferred_regions(ORG) == ("광주광역시",)


# --------------------------------------------------------------------------
# 업로드 · 추출 · 후보
# --------------------------------------------------------------------------


def test_markdown_upload_extracts_candidates_and_flags_gap() -> None:
    detail = upload_md()
    assert detail.status == "review"
    assert detail.doc_format == "md"
    assert detail.organization_id == ORG
    assert detail.candidate_count == 3
    gap = [c for c in detail.candidates if c.is_gap]
    assert len(gap) == 1 and gap[0].approved is False
    assert all(c.approved is None for c in detail.candidates if not c.is_gap)
    assert all(c.organization_id == ORG for c in detail.candidates)
    assert detail.metadata.data_class == "real" and detail.metadata.approved is False
    assert detail.sha256 and detail.metadata.checksum == detail.sha256
    # 파일은 조직 폴더 안에만 있다
    store = org_storage.storage_for(ORG)
    assert store.upload_path(detail.id, ".md").exists()
    assert store.candidate_path(detail.id).exists()


def test_rejects_unknown_type_and_empty_and_too_large() -> None:
    with pytest.raises(cs.CompanyDocumentError):
        cs.register_upload(ORG, file_name="x.exe", payload=b"MZ")
    with pytest.raises(cs.CompanyDocumentError):
        cs.register_upload(ORG, file_name="x.md", payload=b"")
    with pytest.raises(cs.CompanyDocumentError):
        cs.register_upload(ORG, file_name="x.txt", payload=b"a" * (cs.MAX_UPLOAD_BYTES + 1))


def test_duplicate_content_is_detected_within_organization_only() -> None:
    first = upload_md()
    with pytest.raises(cs.DuplicateDocumentError) as exc:
        upload_md(name="copy.md")
    assert exc.value.existing_id == first.id
    # 같은 파일을 다른 조직이 등록하는 것은 허용한다
    organization_service.create_organization(OrganizationCreateRequest(display_name="다른회사", organization_id="org-other", data_class="synthetic", created_by="k"))
    other = upload_md(org="org-other")
    assert other.organization_id == "org-other"


def test_docx_upload_extracts_paragraphs_and_tables() -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("수행실적: 2025년 광주광역시 생성형 AI 실무교육 12회 운영 (교육생 240명).")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "인증"
    table.rows[0].cells[1].text = "ISO 9001 품질경영시스템 인증 보유 (합성)"
    buffer = io.BytesIO()
    doc.save(buffer)
    detail = cs.register_upload(ORG, file_name="실적.docx", payload=buffer.getvalue(), doc_type="수행실적")
    assert detail.status == "review" and detail.doc_format == "docx"
    texts = " ".join(c.source_text for c in detail.candidates)
    assert "12회" in texts and "ISO 9001" in texts


def test_corrupt_pdf_marks_failed_not_crash() -> None:
    detail = cs.register_upload(ORG, file_name="broken.pdf", payload=b"%PDF-1.4 not really a pdf")
    assert detail.status == "failed" and detail.error


# --------------------------------------------------------------------------
# 검토 · 승인 · 색인 대기 · 비활성 · 삭제
# --------------------------------------------------------------------------


def test_approve_requires_reviewed_candidates_and_no_key_leaves_pending() -> None:
    detail = upload_md()
    with pytest.raises(cs.DocumentStateError):
        cs.approve_document(ORG, detail.id, DocumentApproveRequest(reviewer="김담당"))

    good = [c for c in detail.candidates if not c.is_gap]
    reviewed = cs.review_candidates(
        ORG,
        detail.id,
        CandidateReviewRequest(reviewer="김담당", reviews=[CandidateReview(candidate_id=good[0].id, approved=True), CandidateReview(candidate_id=good[1].id, approved=False, note="중복")]),
    )
    assert reviewed.approved_chunk_count == 1
    assert next(c for c in reviewed.candidates if c.id == good[0].id).reviewer == "김담당"

    approved = cs.approve_document(
        ORG,
        detail.id,
        DocumentApproveRequest(reviewer="김담당", data_class="anonymized", scope="internal", valid_to=date.today() + timedelta(days=365)),
    )
    assert approved.status == "approved"  # 키가 없어 색인은 하지 않았다
    assert approved.metadata.approved is True and approved.metadata.approved_by == "김담당"
    assert approved.metadata.data_class == "anonymized"
    status = cs.index_status(ORG)
    assert status.organization_id == ORG
    assert status.embedding_available is False
    assert status.pending_documents == 1
    assert status.company_index["exists"] is False
    assert cs.rebuild_index(ORG).ok is False
    assert cs.active_document_ids(ORG) == {detail.id}


def test_한_번에_여러_문단을_채택하고_제외한다() -> None:
    """화면의 「선택 채택」·「선택 제외」가 쓰는 경로 (0919 §4-B-4).

    한 건씩 보내면 문서 등록부를 문단 수만큼 다시 쓴다. 한 번에 보내면 한 번만 쓴다 —
    화면이 8건을 연달아 처리해도 저장이 한 번이라는 것이 이 개선의 전제다.

    「근거 아님(규칙)」으로 표시된 문단은 **화면의 「전체 선택」이 담지 않는다.** 여기서는
    담당자가 한 건씩 체크해 보낸 경우를 본다 — 그건 사람이 보고 내린 판단이라 막지 않는다.
    """
    detail = upload_md()
    good = [c for c in detail.candidates if not c.is_gap]
    gap = [c for c in detail.candidates if c.is_gap]
    assert len(good) >= 2 and len(gap) == 1

    reviewed = cs.review_candidates(
        ORG,
        detail.id,
        CandidateReviewRequest(
            reviewer="김담당",
            reviews=[CandidateReview(candidate_id=c.id, approved=True) for c in good],
        ),
    )
    assert reviewed.approved_chunk_count == len(good)
    assert all(c.reviewer == "김담당" for c in reviewed.candidates if not c.is_gap)
    # 보내지 않은 문단은 그대로다 — 한꺼번에 처리한다고 나머지가 휩쓸리지 않는다.
    assert next(c for c in reviewed.candidates if c.is_gap).reviewer is None

    # 같은 경로로 한꺼번에 되돌릴 수도 있어야 한다.
    undone = cs.review_candidates(
        ORG,
        detail.id,
        CandidateReviewRequest(
            reviewer="김담당",
            reviews=[CandidateReview(candidate_id=c.id, approved=False) for c in good],
        ),
    )
    assert undone.approved_chunk_count == 0


def test_expired_document_is_not_active() -> None:
    detail = upload_md()
    good = [c for c in detail.candidates if not c.is_gap]
    cs.review_candidates(ORG, detail.id, CandidateReviewRequest(reviewer="k", reviews=[CandidateReview(candidate_id=good[0].id, approved=True)]))
    cs.approve_document(ORG, detail.id, DocumentApproveRequest(reviewer="k", valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1)))
    assert cs.active_document_ids(ORG) == set()


def test_retire_then_delete_and_delete_rules() -> None:
    detail = upload_md()
    good = [c for c in detail.candidates if not c.is_gap]
    cs.review_candidates(ORG, detail.id, CandidateReviewRequest(reviewer="k", reviews=[CandidateReview(candidate_id=good[0].id, approved=True)]))
    cs.approve_document(ORG, detail.id, DocumentApproveRequest(reviewer="k"))
    with pytest.raises(cs.DocumentStateError):
        cs.delete_document(ORG, detail.id)
    retired = cs.retire_document(ORG, detail.id, DocumentRetireRequest(reviewer="k", note="구버전"))
    assert retired.status == "retired" and retired.metadata.retired is True
    assert cs.active_document_ids(ORG) == set()
    cs.delete_document(ORG, detail.id)
    with pytest.raises(cs.DocumentNotFoundError):
        cs.get_document(ORG, detail.id)
    assert not org_storage.storage_for(ORG).upload_path(detail.id, ".md").exists()


# --------------------------------------------------------------------------
# 회사 인덱스가 매칭에 들어가는 규칙 (승인·유효 문서만, 그 조직만)
# --------------------------------------------------------------------------


def test_company_index_chunks_filtered_by_registry() -> None:
    detail = upload_md()
    good = [c for c in detail.candidates if not c.is_gap]
    cs.review_candidates(ORG, detail.id, CandidateReviewRequest(reviewer="k", reviews=[CandidateReview(candidate_id=good[0].id, approved=True)]))
    cs.approve_document(ORG, detail.id, DocumentApproveRequest(reviewer="k"))
    # 임베딩 키 없이 인덱스 파일만 손으로 만든다 (형식 검증용, 벡터는 단위 벡터).
    from app.core import storage

    storage.write_json_atomic(
        org_storage.storage_for(ORG).index_file,
        {
            "chunks": [
                {"evidence_id": good[0].id, "document_id": detail.id, "document_name": "테스트", "doc_type": "운영", "page": 1, "source_text": good[0].source_text, "embedding": [1.0, 0.0], "data_class": "real", "source_kind": "upload"},
                {"evidence_id": "CD-other:001", "document_id": "CD-other", "document_name": "비활성", "doc_type": "운영", "page": 1, "source_text": "x" * 30, "embedding": [0.0, 1.0], "data_class": "real", "source_kind": "upload"},
                {"evidence_id": "CD-exp:001", "document_id": detail.id, "document_name": "만료", "doc_type": "운영", "page": 1, "source_text": "y" * 30, "embedding": [0.0, 1.0], "valid_to": "2020-01-01"},
                {"evidence_id": "EV-syn:001", "document_id": detail.id, "document_name": "합성", "doc_type": "운영", "page": 1, "source_text": "z" * 30, "embedding": [0.0, 1.0], "data_class": "synthetic", "synthetic": True},
                {"evidence_id": "CD-foreign:001", "document_id": detail.id, "document_name": "다른조직", "doc_type": "운영", "page": 1, "source_text": "w" * 30, "embedding": [0.0, 1.0], "data_class": "real", "organization_id": "org-other"},
            ]
        },
    )
    context = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    chunks = evidence_service.load_index(context=context, today=date(2026, 9, 7))
    assert [c.evidence_id for c in chunks] == [good[0].id]
    assert chunks[0].data_class == "real"
    # public_demo 범위는 이 조직 인덱스를 아예 보지 않는다
    assert all(c.organization_id is None for c in evidence_service.load_index(context=AnalysisContext(organization_id=ORG, evidence_scope="public_demo")))


# --------------------------------------------------------------------------
# 역추적 — 이 조직의 분석 결과만
# --------------------------------------------------------------------------


def test_usage_backtrace_reads_saved_proposals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import storage

    monkeypatch.setattr(cs, "PROPOSALS_DIR", tmp_path / "proposals")
    detail = upload_md()
    store = org_storage.storage_for(ORG)
    storage.write_json_atomic(
        store.analysis_dir("g2b-X-000") / "proposal.json",
        {"procurement_id": "g2b-X-000", "organization_id": ORG, "sentences": [{"id": "S1", "requirement_id": "REQ-002", "evidence_id": f"{detail.id}:001"}, {"id": "S2", "evidence_id": "EV-01"}]},
    )
    # 다른 조직 폴더의 제안서는 훑지 않는다
    storage.write_json_atomic(
        org_storage.storage_for("org-other").analysis_dir("g2b-Y-000") / "proposal.json",
        {"procurement_id": "g2b-Y-000", "organization_id": "org-other", "sentences": [{"id": "S1", "evidence_id": f"{detail.id}:001"}]},
    )
    usage = cs.usage_of(ORG, detail.id)
    assert usage.organization_id == ORG
    assert len(usage.used_in) == 1
    assert usage.used_in[0].procurement_id == "g2b-X-000" and usage.used_in[0].requirement_id == "REQ-002"


# --------------------------------------------------------------------------
# API — 레거시 호환(/api/company → 기본 조직) 과 조직 API
# --------------------------------------------------------------------------


def test_api_upload_review_approve_flow_via_legacy_company_api() -> None:
    response = client.post(
        "/api/company/documents",
        files={"file": ("manual.md", MD_DOC.encode("utf-8"), "text/markdown")},
        data={"doc_type": "운영 매뉴얼", "uploaded_by": "김담당"},
    )
    assert response.status_code == 201, response.text
    assert response.headers["X-Organization-Id"] == org_storage.DEFAULT_ORGANIZATION_ID
    assert response.headers["X-Compat-Api"] == "company"
    body = response.json()
    doc_id = body["id"]
    assert body["status"] == "review"
    assert body["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID

    dup = client.post("/api/company/documents", files={"file": ("again.md", MD_DOC.encode("utf-8"), "text/markdown")})
    assert dup.status_code == 409

    candidate = next(c for c in body["candidates"] if not c["is_gap"])
    reviewed = client.put(
        f"/api/company/documents/{doc_id}/candidates",
        json={"reviewer": "김담당", "reviews": [{"candidate_id": candidate["id"], "approved": True}]},
    )
    assert reviewed.status_code == 200 and reviewed.json()["approved_chunk_count"] == 1

    approved = client.post(f"/api/company/documents/{doc_id}/approve", json={"reviewer": "김담당", "data_class": "real"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    listing = client.get("/api/company/documents").json()
    assert listing["counts"]["approved"] == 1
    assert listing["index"]["embedding_available"] is False
    assert client.get(f"/api/company/documents/{doc_id}/usage").json()["used_in"] == []
    assert client.get("/api/company/index").status_code == 200
    assert client.post("/api/company/index/rebuild").json()["ok"] is False
    assert client.get("/api/company/documents/CD-nope").status_code == 404
    assert client.post("/api/company/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415

    # 같은 문서가 조직 API 에서도 기본 조직으로 보인다 (같은 구현)
    via_org = client.get(f"/api/organizations/{org_storage.DEFAULT_ORGANIZATION_ID}/documents/{doc_id}")
    assert via_org.status_code == 200 and via_org.json()["id"] == doc_id
    profile = client.get("/api/company/profile")
    assert profile.status_code == 200 and profile.json()["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID


# --------------------------------------------------------------------------
# 등록부 JSON 손상 — 「자료 없음」과 「읽기 실패」를 구분한다 (BE-5 (4))
# --------------------------------------------------------------------------


def test_corrupt_document_registry_raises_instead_of_looking_empty() -> None:
    """깨진 등록부를 조용히 빈 목록으로 돌려주면 화면에는 「등록한 자료가 없습니다」로 보인다.

    담당자에게는 등록해 둔 회사자료가 통째로 증발한 것과 구분되지 않는다.
    첫 읽기는 명확한 예외로 올라오고, 원본은 `.corrupt-*` 로 격리돼 사실이 남아야 한다.
    """
    detail = upload_md()
    assert detail.status == "review"
    registry = org_storage.storage_for(ORG).documents_file
    registry.write_text('{"documents": [ 깨진 JSON', encoding="utf-8")

    with pytest.raises(cs.CompanyRegistryUnavailableError) as exc:
        cs.list_documents(ORG)
    assert exc.value.organization_id == ORG

    # 격리 흔적이 남는다 — 두 번째 읽기부터는 「파일 없음」이 되므로 이 흔적만이 사실을 보존한다
    quarantined = cs.registry_quarantine_files(ORG)
    assert len(quarantined) == 1 and quarantined[0].name.startswith("documents.json.corrupt-")
    assert cs.list_documents(ORG).documents == []


def test_registry_quarantine_files_is_empty_when_healthy() -> None:
    upload_md()
    assert cs.registry_quarantine_files(ORG) == []


def test_evidence_reason_says_read_failure_not_missing_data() -> None:
    """근거가 0건일 때의 사유가 「자료가 없다」로만 나오면 안 된다 — 못 읽은 것이면 그렇게 말해야 한다."""
    ctx = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    plain = evidence_service._empty_pool_reason(ctx)
    assert "승인·색인된 회사자료가 없습니다" in plain
    # 화면에 붙는 문장이다 — 회사 코드(org-…) 대신 회사 이름 (NEW-RFP-조직코드)
    assert plain.startswith("테스트회사의 ") and ORG not in plain

    upload_md()
    org_storage.storage_for(ORG).documents_file.write_text("{{{", encoding="utf-8")
    with pytest.raises(cs.CompanyRegistryUnavailableError):
        cs.list_documents(ORG)
    broken = evidence_service._empty_pool_reason(ctx)
    assert "읽지 못했습니다" in broken and "격리" in broken
    assert "자료가 없는 것이 아니라" in broken
    assert ORG not in broken


def test_approved_document_count_definition_is_approved_plus_indexed() -> None:
    """백엔드가 세는 「승인」의 정의를 못박는다 — approved(색인 전) + indexed(색인 완료).

    DocumentListResponse.counts 는 상태별 원자료라 counts["approved"] 는 「색인 전」만 센다.
    두 숫자를 같은 「승인 N건」이라고 적으면 화면에서 서로 어긋난다 (프론트 담당 별건).
    """
    detail = upload_md()
    good = [c for c in detail.candidates if not c.is_gap]
    cs.review_candidates(ORG, detail.id, CandidateReviewRequest(reviewer="김담당", reviews=[CandidateReview(candidate_id=good[0].id, approved=True)]))
    cs.approve_document(ORG, detail.id, DocumentApproveRequest(reviewer="김담당", data_class="real"))

    listing = cs.list_documents(ORG)
    summary = organization_service.summarize(organization_service.get_organization(ORG))
    assert listing.counts.get("approved") == 1 and listing.counts.get("indexed") is None
    assert summary.approved_document_count == 1
    # 임베딩 키가 없어 색인은 대기 상태다 — 그래도 「승인」에는 들어간다
    assert summary.pending_index_documents == 1
