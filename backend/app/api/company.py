"""회사정보·수행근거 **레거시 호환** API (단수형 `/api/company/...`).

다회사 구조로 바뀐 뒤에도 기존 프론트엔드 호출이 깨지지 않도록 남겨 둔다.
모든 경로는 설정의 기본 조직(`DEFAULT_ORGANIZATION_ID`, 기본 `org-sample`)으로 **위임**한다 —
별도의 단일 회사 로직을 중복 구현하지 않는다 (구현은 api/organizations.py 의 do_* 함수).

응답 헤더로 어느 조직에 위임했는지 남긴다: `X-Organization-Id`, `X-Compat-Api: company`.
새 코드는 `/api/organizations/{organization_id}/...` 를 써야 한다 (docs/api.md).
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.api import deps, organizations as org_api
from app.core.config import get_settings
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
from app.schemas.organization import AnalysisContext, OrganizationProfile, OrganizationProfileUpdate
from app.services import organization_service

router = APIRouter(prefix="/api/company", tags=["company (legacy compat)"])


def _default_org(response: Response) -> str:
    org_id = deps.organization_or_404(get_settings().default_organization_id)
    deps.stamp_context_headers(response, AnalysisContext(organization_id=org_id, evidence_scope="internal"), compat=True)
    return org_id


@router.get("/profile", response_model=OrganizationProfile)
async def get_profile(response: Response) -> OrganizationProfile:
    return organization_service.load_profile(_default_org(response))


@router.put("/profile", response_model=OrganizationProfile)
async def put_profile(body: OrganizationProfileUpdate, response: Response) -> OrganizationProfile:
    deps.require_writable()
    return organization_service.save_profile(_default_org(response), body)


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(response: Response) -> DocumentListResponse:
    return org_api.do_list_documents(_default_org(response))


@router.post("/documents", response_model=CompanyDocumentDetail, status_code=201)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    doc_type: str = Form("기타"),
    data_class: str = Form("real"),
    uploaded_by: str | None = Form(None),
) -> CompanyDocumentDetail:
    org_id = _default_org(response)
    payload = await org_api.read_upload(file)
    return org_api.do_upload(org_id, file_name=file.filename or "document", payload=payload, doc_type=doc_type, data_class=data_class, uploaded_by=uploaded_by)


@router.get("/documents/{document_id}", response_model=CompanyDocumentDetail)
async def get_document(document_id: str, response: Response) -> CompanyDocumentDetail:
    return org_api.do_get_document(_default_org(response), document_id)


@router.post("/documents/{document_id}/extract", response_model=CompanyDocumentDetail)
async def re_extract(document_id: str, response: Response) -> CompanyDocumentDetail:
    return org_api.do_extract(_default_org(response), document_id)


@router.put("/documents/{document_id}/candidates", response_model=CompanyDocumentDetail)
async def review_candidates(document_id: str, body: CandidateReviewRequest, response: Response) -> CompanyDocumentDetail:
    return org_api.do_review(_default_org(response), document_id, body)


@router.post("/documents/{document_id}/approve", response_model=CompanyDocumentDetail)
async def approve_document(document_id: str, body: DocumentApproveRequest, response: Response) -> CompanyDocumentDetail:
    return org_api.do_approve(_default_org(response), document_id, body)


@router.post("/documents/{document_id}/retire", response_model=CompanyDocument)
async def retire_document(document_id: str, body: DocumentRetireRequest, response: Response) -> CompanyDocument:
    return org_api.do_retire(_default_org(response), document_id, body)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str, response: Response) -> None:
    org_api.do_delete(_default_org(response), document_id)


@router.get("/documents/{document_id}/usage", response_model=UsageResponse)
async def document_usage(document_id: str, response: Response) -> UsageResponse:
    return org_api.do_usage(_default_org(response), document_id)


@router.get("/index", response_model=IndexStatus)
async def get_index_status(response: Response) -> IndexStatus:
    return org_api.do_index_status(_default_org(response))


@router.post("/index/rebuild", response_model=ReindexResult)
async def rebuild_index(response: Response) -> ReindexResult:
    # 조직 경로와 같다 — 등록부 경합 때문에 루프에서(27차 검수 C13).
    return org_api.do_rebuild(_default_org(response))
