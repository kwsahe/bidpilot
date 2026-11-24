"""조직(회사) API — 다회사 구조.

조직
- POST   /api/organizations                        회사 생성
- GET    /api/organizations                        목록 (요약: 문서 수·승인 수·근거 문단 수·색인 상태)
- GET    /api/organizations/{org}                  상세
- PATCH  /api/organizations/{org}                  수정
- POST   /api/organizations/{org}/activate · /deactivate
- GET/PUT /api/organizations/{org}/profile         프로필 (사업자번호·개인 연락처는 스키마에 없다)

회사자료 (조직별로 완전히 분리 — URL 의 조직과 문서 소유 조직이 다르면 404)
- GET    /api/organizations/{org}/documents
- POST   /api/organizations/{org}/documents        업로드(multipart) → 추출 → 후보
- GET    /api/organizations/{org}/documents/{id}
- POST   /api/organizations/{org}/documents/{id}/extract
- PUT    /api/organizations/{org}/documents/{id}/candidates
- POST   /api/organizations/{org}/documents/{id}/approve
- POST   /api/organizations/{org}/documents/{id}/retire
- DELETE /api/organizations/{org}/documents/{id}
- GET    /api/organizations/{org}/documents/{id}/usage
- GET    /api/organizations/{org}/index · POST /index/rebuild · POST /index/search (테스트 검색)

실적 원장(xlsx) 매핑 import (담당자 승인 후 등록)
- POST   /api/organizations/{org}/ledger/inspect   시트·머리글·열 매핑 후보·상태값
- POST   /api/organizations/{org}/ledger/preview   프로필로 변환 preview (포함·제외·사유·금액 단위)
- POST   /api/organizations/{org}/ledger/import    등록(+승인)

공개 배포(읽기 전용 데모) 모드에서는 쓰기 API 가 403 이다.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api import deps
from app.core import org_storage, storage
from app.schemas.company import (
    CandidateReviewRequest,
    CompanyDocument,
    CompanyDocumentDetail,
    DocumentApproveRequest,
    DocumentListResponse,
    DocumentRetireRequest,
    IndexStatus,
    ReindexResult,
    UsageResponse,
)
from app.schemas.organization import (
    AnalysisContext,
    Organization,
    OrganizationCreateRequest,
    OrganizationListResponse,
    OrganizationProfile,
    OrganizationProfileUpdate,
    PlanGeneralInfo,
    PlanGeneralUpdate,
    OrganizationSummary,
    OrganizationUpdateRequest,
)
from app.services import company_service, evidence_service, ledger_import_service, llm_client, organization_service

router = APIRouter(prefix="/api/organizations", tags=["organizations"])

UPLOAD_CHUNK = 64 * 1024


def _doc_id(value: str) -> str:
    try:
        return storage.safe_id(value, what="문서 id")
    except storage.InvalidIdError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")


class StatusChangeRequest(BaseModel):
    updated_by: str = Field(min_length=1, max_length=60)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


# --------------------------------------------------------------------------
# 조직
# --------------------------------------------------------------------------


@router.post("", response_model=Organization, status_code=201)
async def create_organization(body: OrganizationCreateRequest) -> Organization:
    deps.require_writable()
    try:
        return organization_service.create_organization(body)
    # 대화상자는 이 칸을 「회사 코드」라 부른다 — 영문 필드 이름(organization_id)을 화면에 내보내지 않는다 (CMP-15).
    except org_storage.InvalidOrganizationIdError:
        raise HTTPException(status_code=400, detail="허용되지 않는 회사 코드입니다 — org- 로 시작하고 영문 소문자·숫자·하이픈만 씁니다 (예: org-demo-company)")
    except organization_service.OrganizationExistsError as exc:
        raise HTTPException(status_code=409, detail=f"이미 있는 회사 코드입니다: {exc}")


@router.get("", response_model=OrganizationListResponse)
async def list_organizations() -> OrganizationListResponse:
    return organization_service.list_summaries()


@router.get("/{organization_id}", response_model=OrganizationSummary)
async def get_organization(organization_id: str) -> OrganizationSummary:
    org_id = deps.organization_or_404(organization_id)
    return organization_service.summarize(organization_service.get_organization(org_id))


@router.patch("/{organization_id}", response_model=Organization)
async def update_organization(organization_id: str, body: OrganizationUpdateRequest) -> Organization:
    deps.require_writable()
    org_id = deps.organization_or_404(organization_id)
    return organization_service.update_organization(org_id, body)


@router.post("/{organization_id}/activate", response_model=Organization)
async def activate_organization(organization_id: str, body: StatusChangeRequest) -> Organization:
    deps.require_writable()
    org_id = deps.organization_or_404(organization_id)
    return organization_service.set_status(org_id, "active", updated_by=body.updated_by)


@router.post("/{organization_id}/deactivate", response_model=Organization)
async def deactivate_organization(organization_id: str, body: StatusChangeRequest) -> Organization:
    deps.require_writable()
    org_id = deps.organization_or_404(organization_id)
    return organization_service.set_status(org_id, "inactive", updated_by=body.updated_by)


@router.get("/{organization_id}/profile", response_model=OrganizationProfile)
async def get_profile(organization_id: str) -> OrganizationProfile:
    return organization_service.load_profile(deps.organization_or_404(organization_id))


@router.put("/{organization_id}/profile", response_model=OrganizationProfile)
async def put_profile(organization_id: str, body: OrganizationProfileUpdate) -> OrganizationProfile:
    deps.require_writable()
    return organization_service.save_profile(deps.organization_or_404(organization_id), body)


@router.get("/{organization_id}/plan-general", response_model=PlanGeneralInfo)
async def get_plan_general(organization_id: str) -> PlanGeneralInfo:
    """사업계획서 일반현황 (29차 §3-B) — 대표자 · 사업자등록번호 · 개업연월일 · 업태/종목 · 연도별 매출 · 고용 · 인력 구성.

    프로필 공개 응답과 따로 둔다(사업자번호 등은 그 응답에 싣지 않는다). AI 본문에도 싣지 않는다.
    """
    deps.require_writable()  # 공개 배포(읽기 전용)에서는 열지 않는다 — 회사 값이다
    return organization_service.load_plan_general(deps.organization_or_404(organization_id))


@router.put("/{organization_id}/plan-general", response_model=PlanGeneralInfo)
async def put_plan_general(organization_id: str, body: PlanGeneralUpdate) -> PlanGeneralInfo:
    deps.require_writable()
    return organization_service.save_plan_general(deps.organization_or_404(organization_id), body)


# --------------------------------------------------------------------------
# 회사자료 (공통 구현 — /api/company 호환 라우터도 이 함수들을 쓴다)
# --------------------------------------------------------------------------


async def read_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK):
        total += len(chunk)
        if total > company_service.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="업로드 상한(20MB)을 초과했습니다")
        chunks.append(chunk)
    return b"".join(chunks)


def do_list_documents(org_id: str) -> DocumentListResponse:
    return company_service.list_documents(org_id)


def do_upload(org_id: str, *, file_name: str, payload: bytes, doc_type: str, data_class: str, uploaded_by: str | None) -> CompanyDocumentDetail:
    deps.require_writable()
    try:
        return company_service.register_upload(
            org_id, file_name=file_name, payload=payload, doc_type=doc_type, uploaded_by=uploaded_by, data_class=data_class
        )
    except company_service.DuplicateDocumentError as exc:
        # 내부 id(CD-…)를 두 번 찍던 문장 대신, 목록에서 찾을 수 있는 문서 이름을 한 번만 (CMP-15).
        try:
            existing = company_service.get_document(org_id, exc.existing_id).title
        except company_service.DocumentNotFoundError:
            existing = exc.existing_id
        raise HTTPException(status_code=409, detail=f"같은 내용의 문서가 이미 있습니다: 「{existing}」")
    except company_service.CompanyDocumentError as exc:
        raise HTTPException(status_code=415 if "형식" in str(exc) else 422, detail=str(exc))


def do_get_document(org_id: str, document_id: str) -> CompanyDocumentDetail:
    try:
        return company_service.get_document(org_id, _doc_id(document_id))
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")


def do_extract(org_id: str, document_id: str) -> CompanyDocumentDetail:
    deps.require_writable()
    try:
        return company_service.extract_document(org_id, _doc_id(document_id))
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")


def do_review(org_id: str, document_id: str, body: CandidateReviewRequest) -> CompanyDocumentDetail:
    deps.require_writable()
    try:
        return company_service.review_candidates(org_id, _doc_id(document_id), body)
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서 또는 후보입니다")
    except company_service.DocumentStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def do_approve(org_id: str, document_id: str, body: DocumentApproveRequest) -> CompanyDocumentDetail:
    deps.require_writable()
    try:
        return company_service.approve_document(org_id, _doc_id(document_id), body)
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")
    except company_service.DocumentStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def do_retire(org_id: str, document_id: str, body: DocumentRetireRequest) -> CompanyDocument:
    deps.require_writable()
    try:
        return company_service.retire_document(org_id, _doc_id(document_id), body)
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")


def do_delete(org_id: str, document_id: str) -> None:
    deps.require_writable()
    try:
        company_service.delete_document(org_id, _doc_id(document_id))
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")
    except company_service.DocumentStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def do_usage(org_id: str, document_id: str) -> UsageResponse:
    try:
        return company_service.usage_of(org_id, _doc_id(document_id))
    except company_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="없는 문서입니다")


def do_index_status(org_id: str) -> IndexStatus:
    return company_service.index_status(org_id)


def do_rebuild(org_id: str) -> ReindexResult:
    deps.require_writable()
    return company_service.rebuild_index(org_id)


@router.get("/{organization_id}/documents", response_model=DocumentListResponse)
async def list_documents(organization_id: str) -> DocumentListResponse:
    return do_list_documents(deps.organization_or_404(organization_id))


@router.post("/{organization_id}/documents", response_model=CompanyDocumentDetail, status_code=201)
async def upload_document(
    organization_id: str,
    file: UploadFile = File(...),
    doc_type: str = Form("기타"),
    data_class: str = Form("real"),
    uploaded_by: str | None = Form(None),
) -> CompanyDocumentDetail:
    org_id = deps.organization_or_404(organization_id)
    payload = await read_upload(file)
    # 문서 파싱은 CPU 를 오래 쓴다(PDF·HWP 수십 페이지). `async def` 안에서 그대로 돌리면
    # 그동안 이벤트 루프가 멈춰 **다른 모든 요청**이 함께 선다 — `/health` 도 포함이다.
    # 컨테이너·nginx 헬스체크가 그 사이에 실패하면 멀쩡한 서버가 죽은 것으로 판정된다 (ISSUE-031).
    return await run_in_threadpool(
        do_upload,
        org_id,
        file_name=file.filename or "document",
        payload=payload,
        doc_type=doc_type,
        data_class=data_class,
        uploaded_by=uploaded_by,
    )


@router.get("/{organization_id}/documents/{document_id}", response_model=CompanyDocumentDetail)
async def get_document(organization_id: str, document_id: str) -> CompanyDocumentDetail:
    return do_get_document(deps.organization_or_404(organization_id), document_id)


@router.post("/{organization_id}/documents/{document_id}/extract", response_model=CompanyDocumentDetail)
async def re_extract(organization_id: str, document_id: str) -> CompanyDocumentDetail:
    return do_extract(deps.organization_or_404(organization_id), document_id)


@router.put("/{organization_id}/documents/{document_id}/candidates", response_model=CompanyDocumentDetail)
async def review_candidates(organization_id: str, document_id: str, body: CandidateReviewRequest) -> CompanyDocumentDetail:
    return do_review(deps.organization_or_404(organization_id), document_id, body)


@router.post("/{organization_id}/documents/{document_id}/approve", response_model=CompanyDocumentDetail)
async def approve_document(organization_id: str, document_id: str, body: DocumentApproveRequest) -> CompanyDocumentDetail:
    return do_approve(deps.organization_or_404(organization_id), document_id, body)


@router.post("/{organization_id}/documents/{document_id}/retire", response_model=CompanyDocument)
async def retire_document(organization_id: str, document_id: str, body: DocumentRetireRequest) -> CompanyDocument:
    return do_retire(deps.organization_or_404(organization_id), document_id, body)


@router.delete("/{organization_id}/documents/{document_id}", status_code=204)
async def delete_document(organization_id: str, document_id: str) -> None:
    do_delete(deps.organization_or_404(organization_id), document_id)


@router.get("/{organization_id}/documents/{document_id}/usage", response_model=UsageResponse)
async def document_usage(organization_id: str, document_id: str) -> UsageResponse:
    return do_usage(deps.organization_or_404(organization_id), document_id)


@router.get("/{organization_id}/index", response_model=IndexStatus)
async def get_index_status(organization_id: str) -> IndexStatus:
    return do_index_status(deps.organization_or_404(organization_id))


@router.post("/{organization_id}/index/rebuild", response_model=ReindexResult)
async def rebuild_index(organization_id: str) -> ReindexResult:
    # 루프에서 돈다(일부러). 색인 갱신은 등록부를 읽고 → 임베딩 → 옛 사본으로 다시 쓴다. 스레드로 옮기면 그사이 올린 ·
    # 승인한 · 지운 문서를 되돌렸다(27차 검수 C13). 회사별 잠금이 생기기 전까지는 루프가 그 잠금 노릇을 한다.
    return do_rebuild(deps.organization_or_404(organization_id))


@router.post("/{organization_id}/index/search")
async def search_index(organization_id: str, body: SearchRequest) -> dict:
    """등록 흐름의 '테스트 검색' — 이 조직의 승인·색인 문단(internal)만 검색한다. 키가 없으면 정직하게 알린다."""
    org_id = deps.organization_or_404(organization_id)
    context = AnalysisContext(organization_id=org_id, evidence_scope="internal")
    if not llm_client.is_configured():
        # 503 으로 답한다 — 예전에는 200 + available:false 라 화면이 「성공인데 결과 0건」으로 읽었다.
        raise HTTPException(
            status_code=503,
            detail="AI 검색 설정이 없어 검색할 수 없습니다. 관리자에게 설정 확인을 요청해 주세요.",
        )
    if not evidence_service.index_exists(context):
        return {"organization_id": org_id, "evidence_scope": "internal", "available": False, "reason": "이 회사의 AI 검색 준비가 아직 없습니다. 근거로 등록한 뒤 「AI 검색 다시 준비」를 누르세요.", "hits": []}
    try:
        # 임베딩 호출 · 벡터 검색은 동기다 — 스레드에서(27차 R26-11).
        vector = (await run_in_threadpool(llm_client.embed, [body.query]))[0]
    except llm_client.LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    hits = await run_in_threadpool(evidence_service.search, vector, context=context, top_k=body.top_k)
    return {
        "organization_id": org_id,
        "evidence_scope": "internal",
        "available": True,
        "synthetic_evidence_used": any(c.synthetic for _s, c in hits),
        "hits": [
            {
                "score": round(score, 4),
                "evidence_id": c.evidence_id,
                "document_id": c.document_id,
                "document_name": c.document_name,
                "doc_type": c.doc_type,
                "page": c.page,
                "source_text": c.source_text,
                "data_class": c.data_class,
            }
            for score, c in hits
        ],
    }


# --------------------------------------------------------------------------
# 실적 원장 import (담당자 매핑 확인 → preview → 승인 후 등록)
# --------------------------------------------------------------------------


@router.post("/{organization_id}/ledger/inspect")
async def inspect_ledger(organization_id: str, file: UploadFile = File(...)) -> dict:
    org_id = deps.organization_or_404(organization_id)
    deps.require_writable()
    payload = await read_upload(file)
    try:
        return ledger_import_service.inspect_upload(org_id, file_name=file.filename or "ledger.xlsx", payload=payload).model_dump(mode="json")
    except ledger_import_service.LedgerImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{organization_id}/ledger/preview")
async def preview_ledger(organization_id: str, body: ledger_import_service.LedgerPreviewRequest) -> dict:
    org_id = deps.organization_or_404(organization_id)
    try:
        return ledger_import_service.preview(org_id, body).model_dump(mode="json")
    except ledger_import_service.LedgerImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{organization_id}/ledger/import")
async def import_ledger(organization_id: str, body: ledger_import_service.LedgerImportRequest) -> dict:
    org_id = deps.organization_or_404(organization_id)
    deps.require_writable()
    try:
        return ledger_import_service.import_ledger(org_id, body).model_dump(mode="json")
    except ledger_import_service.LedgerImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{organization_id}/ledger/summary")
async def ledger_summary(organization_id: str) -> dict:
    org_id = deps.organization_or_404(organization_id)
    return ledger_import_service.summary(org_id)


@router.get("/{organization_id}/ledger/profiles")
async def ledger_profiles(organization_id: str) -> dict:
    deps.organization_or_404(organization_id)
    return {"profiles": [p.model_dump(mode="json") for p in ledger_import_service.builtin_profiles()]}


def context_headers(response: Response, context: AnalysisContext, *, compat: bool = False) -> None:
    deps.stamp_context_headers(response, context, compat=compat)


__all__ = ["router", "json"]
