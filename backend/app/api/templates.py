"""HWPX 서식 템플릿 API (Beta).

- GET  /api/templates                              내장·등록 서식 목록
- POST /api/templates/render                       {template_id, procurement_id, manual{}} → 파일 생성 + 검증 보고서
- GET  /api/templates/{template_id}/report/{pid}   마지막 렌더링 보고서
- GET  /api/exports/{pid}/{file}                   생성한 한글 서식(HWPX) 파일 받기
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.schemas.text_fields import FillKey, FillText

from app.api import deps
from app.core import storage
from app.services import hwpx_template_service, organization_service, performance_match_service, procurement_service, rfp_parser

router = APIRouter(tags=["templates"])


class RenderRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=60)
    procurement_id: str = Field(min_length=1, max_length=64)
    # 담당자가 직접 넣는 값 (대표자·법인등록번호 등). 시스템은 지어내지 않는다.
    # 키·값 길이와 개수에 상한을 둔다 — 서식 자리 수는 수십 개고, 여기 들어온 것은
    # 그대로 파일에 기록된다.
    manual: dict[FillKey, FillText] = Field(default_factory=dict, max_length=200)
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")


@router.get("/api/templates")
async def list_templates() -> dict:
    templates = hwpx_template_service.list_templates()
    return {
        "count": len(templates),
        "status": "beta",
        "note": "HWPX(ZIP+XML)만 생성한다. 한컴오피스에서 실제로 열리는지는 이 환경에서 검증하지 못했다 — 열어서 확인 후 제출한다.",
        "templates": [t.model_dump(mode="json") for t in templates],
    }


@router.post("/api/templates/render")
async def render_template(body: RenderRequest) -> dict:
    try:
        storage.safe_id(body.procurement_id, what="공고 id")
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    notice = None
    if rfp_parser.is_real_notice_id(body.procurement_id):
        try:
            view = await procurement_service.get_notice(body.procurement_id)
            notice = view.notice if view else None
        except procurement_service.NoNoticeDataError:
            notice = None
    try:
        parse_result = rfp_parser.load_generated(body.procurement_id)
    except (rfp_parser.RfpNotParsedError, rfp_parser.RfpFixtureNotFoundError):
        parse_result = None

    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=body.procurement_id)
    try:
        result = hwpx_template_service.render(
            body.template_id,
            body.procurement_id,
            profile=organization_service.load_profile(context.organization_id),
            notice=notice,
            parse_result=parse_result,
            manual=body.manual,
            # 수행실적표 행은 **그 조직의** 원장에서만 (public_demo 는 원장 없음 → 빈 표)
            ledger_rows=performance_match_service.project_rows(performance_match_service.load_ledger_for(context)),
            context=context,
        )
    except hwpx_template_service.TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="등록되지 않은 서식입니다")
    except hwpx_template_service.TemplateRenderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result.model_dump(mode="json")


@router.get("/api/templates/{template_id}/report/{procurement_id}")
async def render_report(
    template_id: str,
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        report = hwpx_template_service.load_report(procurement_id, template_id, context)
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if report is None:
        raise HTTPException(status_code=404, detail="아직 생성한 적이 없습니다")
    return report.model_dump(mode="json")


@router.get("/api/exports/{procurement_id}/{file_name}")
async def download_export(
    procurement_id: str,
    file_name: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> FileResponse:
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        path = hwpx_template_service.export_path(procurement_id, file_name, context)
    except (storage.InvalidIdError, hwpx_template_service.TemplateNotFoundError):
        raise HTTPException(status_code=404, detail="없는 파일입니다")
    if not path.exists():
        raise HTTPException(status_code=404, detail="아직 생성하지 않은 파일입니다")
    return FileResponse(path, media_type="application/hwp+zip", filename=file_name)
