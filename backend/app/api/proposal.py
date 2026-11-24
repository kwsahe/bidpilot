"""제안서 초안 API.

라우터에 prefix를 두지 않고 경로를 전체로 적는다(저장소의 다른 라우터와 동일한 방식).
"""

import json
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core import inflight, requester, storage
from app.api import deps

from app.schemas.proposal import ProposalGenerateRequest, ProposalSection
from app.schemas.proposal_document import ProposalDocument, ProposalDocumentRequest
from app.services import (
    analysis_store,
    bid_application_export,
    bid_proposal_service,
    bid_quality_gate,
    hwpx_template_service,
    plan_draft_service,
    plan_export_service,
    plan_hwpx_service,
    plan_pdf_service,
    procurement_service,
    evidence_adoption_service,
    evidence_service,
    proposal_export,
    proposal_service,
    rfp_parser,
    wording,
)

router = APIRouter(tags=["proposal"])


@router.post("/api/proposal/generate", response_model=ProposalSection)
async def generate_proposal(body: ProposalGenerateRequest) -> ProposalSection:
    """요구사항 + 채택된 회사 Evidence로 핵심 섹션 1개를 생성·저장한다.

    근거가 없는 요구사항은 문장을 만들지 않거나 `확인 필요`로 남긴다(커버리지를 지어내지 않는다).
    """
    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=body.procurement_id)
    try:
        # 같은 회사 · 같은 공고 제안서는 한 번에 하나만 — 두 요청이 AI 를 두 번 부르고 판 번호를 덮어썼다(27차 R26-12).
        with inflight.hold("proposal_section", context.organization_id, body.procurement_id):
            # AI 보강은 동기 호출(Claude CLI 는 subprocess)이다 — 이벤트 루프에서 돌면 그동안 서버 전체가 멈춘다(ISSUE-144).
            section = await run_in_threadpool(
                proposal_service.generate_section,
                body.procurement_id, section_title=body.section_title, context=context
            )
            return _with_search_state(section, context)
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown procurement id")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(
            status_code=404,
            detail="RFP not parsed yet. Call POST /api/rfp/parse first",
        )


@router.get("/api/proposal/{procurement_id}", response_model=ProposalSection)
async def get_proposal(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> ProposalSection:
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return _with_search_state(wording.modernize_model(proposal_service.load_section(procurement_id, context=context)), context)
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown procurement id")
    except proposal_service.ProposalNotGeneratedError:
        raise HTTPException(
            status_code=404,
            detail="Proposal not generated yet. Call POST /api/proposal/generate first",
        )


def _with_search_state(section: ProposalSection, context) -> ProposalSection:
    """응답에 지금 회사 근거 AI 검색 상태를 붙인다(46차 H5 — 45차 전 초안의 옛 사유 글로 「실패」가 보였다 · 저장본은 그대로)."""
    return section.model_copy(update={"evidence_summary": evidence_service.with_search_state(section.evidence_summary, context)})


ExportFormatParam = Literal["docx", "pdf", "txt"]


def _download(payload: bytes, file_name: str, media_type: str) -> Response:
    # 한글 파일명은 RFC 5987 형식으로 넘긴다 (브라우저가 깨뜨리지 않게).
    disposition = f"attachment; filename*=UTF-8''{quote(file_name)}"
    return Response(
        content=payload, media_type=media_type, headers={"Content-Disposition": disposition}
    )


@router.get("/api/evidence/{procurement_id}")
async def get_evidence_links(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """근거 연결 결과 조회.

    화면이 「Evidence Mapping 실행 여부」를 알 수 있는 유일한 통로다.
    예전에는 이 결과가 제안서 문장 안에만 녹아 있고 조회할 방법이 없어서,
    실제로 회사자료를 검색해 근거를 찾아 놓고도 화면이 「미실행」이라고 말했다.

    아직 실행하지 않았으면 404 다 — 빈 결과(0건 연결)와 구분해야 하기 때문이다.
    """
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        payload = proposal_service.load_evidence_result(procurement_id, context=context)
    except storage.InvalidIdError as exc:
        # 다른 라우트(capability·conditions·insights)와 같은 방식으로 막는다.
        # 여기서만 새어 나가면 이상한 id 하나로 500 이 난다.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="Evidence mapping not run yet. Generate a proposal section first.",
        )
    return wording.modernize(payload)


@router.get("/api/proposal/{procurement_id}/export")
async def export_proposal(
    procurement_id: str,
    format: ExportFormatParam = Query("docx", description="docx · pdf · txt"),
    grounded_only: bool = Query(
        False,
        description="회사 근거가 없는 「확인 필요」 문장을 본문에서 빼고 문서 끝 확인 목록으로 옮긴다",
    ),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> Response:
    """제안서 초안을 문서(DOCX/PDF/TXT)로 내려준다.

    문장마다 RFP 페이지·원문과 회사 근거자료를 함께 싣는다. 화면에서 보이던 근거가
    파일로 나가면서 사라지지 않게 한다. 완성본이 아니라 초안이며 문서에 그렇게 적는다.
    PDF는 이 서버의 Microsoft Word로 변환하며, 없으면 503.
    """
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        payload, file_name, media_type = await proposal_export.export_section(
            procurement_id, fmt=format, grounded_only=grounded_only, context=context
        )
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown procurement id")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(
            status_code=404,
            detail="RFP not parsed yet. Call POST /api/rfp/parse first",
        )
    except proposal_service.ProposalNotGeneratedError:
        raise HTTPException(
            status_code=404,
            detail="Proposal not generated yet. Call POST /api/proposal/generate first",
        )
    except proposal_export.PdfConverterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except proposal_export.ProposalExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _download(payload, file_name, media_type)


@router.post("/api/proposal/generate/full", response_model=ProposalDocument)
async def generate_full_proposal(body: ProposalDocumentRequest) -> ProposalDocument:
    """요구사항 카테고리별로 섹션을 나눠 제안서 전체 초안을 만든다.

    요구사항이 없는 목차는 만들지 않는다. 근거도 의무 표현도 없는 요구사항은 문장을
    만들지 않고 '대응 문장 없음'으로 남긴다 (CLAUDE.md 11).
    """
    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=body.procurement_id)
    try:
        with inflight.hold("proposal_full", context.organization_id, body.procurement_id):  # 27차 R26-12
            if body.use_claude:
                # 저장할 수 없는 곳이면 AI 를 부르기 전에 403 — 다 부른 뒤 저장에서 거절되면 사용량만 쓰였다(28차 검수 R1-02).
                analysis_store.guard_public_demo_write(context)
                # 사업계획서 작성 문 — 서버에 한 건(다른 공고도 기다리게 · 28차 §3-D)
                with inflight.hold("plan_writer", message=inflight.PLAN_WRITER_BUSY):
                    document = await run_in_threadpool(
                        proposal_service.generate_document, body.procurement_id, use_llm=True, context=context, plan_writer=True,
                        writer=body.writer,
                    )
            else:
                document = await run_in_threadpool(  # AI 보강이 켜져 있으면 동기 호출 — 스레드에서(ISSUE-144)
                    proposal_service.generate_document, body.procurement_id, use_llm=body.use_llm, context=context
                )
            # 「AI 초안 유지」면 저장된 옛 초안이 그대로 온다 — GET 처럼 새 말로(33차 R32W-2)
            return wording.modernize_model(document)
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown procurement id")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(
            status_code=404,
            detail="RFP not parsed yet. Call POST /api/rfp/parse first",
        )


class LedgerAdoptionRequest(BaseModel):
    """원장 후보 채택 · 채택 취소(45차 H5)."""

    requirement_id: str = Field(min_length=1, max_length=40)
    evidence_id: str = Field(min_length=1, max_length=60)
    adopted: bool
    by: str = Field(min_length=1, max_length=60)


@router.get("/api/evidence/{procurement_id}/ledger")
async def get_ledger_candidates(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """AI 검색을 꺼 둔 회사의 실적 원장 후보와 채택(45차 H5 · 43차 결정 3) — 정리표 행 상세가 「채택」 단추로 고른다."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return await run_in_threadpool(evidence_adoption_service.ledger_view, procurement_id, context)
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="알 수 없는 공고입니다")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(status_code=404, detail="요구사항을 아직 뽑지 않은 공고입니다")


@router.put("/api/evidence/{procurement_id}/ledger")
async def put_ledger_adoption(
    procurement_id: str,
    body: LedgerAdoptionRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """원장 후보 하나를 채택하거나 취소한다 — 누가(적은 이름) · 서버가 본 사람 · 언제를 남긴다. 열람자는 막힌다(게이트)."""
    deps.require_writable()
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return await run_in_threadpool(
            lambda: evidence_adoption_service.set_adoption(
                procurement_id, context, requirement_id=body.requirement_id, evidence_id=body.evidence_id,
                adopted=body.adopted, by=body.by.strip(), recorded_by=requester.current_recorded_by(),
            )
        )
    except evidence_adoption_service.AdoptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="알 수 없는 공고입니다")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(status_code=404, detail="요구사항을 아직 뽑지 않은 공고입니다")


@router.get("/api/proposal/{procurement_id}/adopted-evidence")
async def get_adopted_evidence(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """사업계획서 작성 페이지 — Claude 에 갈 **채택한 근거 문장 수** (보낼 본문과 같은 계산 · 28차 §3-D)."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return await run_in_threadpool(proposal_service.adopted_evidence, procurement_id, context)
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="알 수 없는 공고입니다")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(status_code=404, detail="요구사항을 아직 뽑지 않은 공고입니다 — 사업기회 › 요구사항 정리표에서 먼저 분석하세요")


@router.get("/api/proposal/{procurement_id}/full", response_model=ProposalDocument)
async def get_full_proposal(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> ProposalDocument:
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return wording.modernize_model(proposal_service.load_document(procurement_id, context=context))
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown procurement id")
    except proposal_service.ProposalNotGeneratedError:
        raise HTTPException(
            status_code=404,
            detail="Full proposal not generated yet. "
            "Call POST /api/proposal/generate/full first",
        )


@router.get("/api/proposal/{procurement_id}/full/export")
async def export_full_proposal(
    procurement_id: str,
    format: ExportFormatParam = Query("docx", description="docx · pdf · txt"),
    grounded_only: bool = Query(
        False,
        description="회사 근거가 없는 「확인 필요」 문장을 본문에서 빼고 문서 끝 확인 목록으로 옮긴다",
    ),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> Response:
    """제안서 전체 초안을 문서(DOCX/PDF/TXT)로 내려준다."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        payload, file_name, media_type = await proposal_export.export_full(
            procurement_id, fmt=format, grounded_only=grounded_only, context=context
        )
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown procurement id")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(
            status_code=404,
            detail="RFP not parsed yet. Call POST /api/rfp/parse first",
        )
    except proposal_service.ProposalNotGeneratedError:
        raise HTTPException(
            status_code=404,
            detail="Full proposal not generated yet. "
            "Call POST /api/proposal/generate/full first",
        )
    except proposal_export.PdfConverterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except proposal_export.ProposalExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _download(payload, file_name, media_type)


@router.get("/api/proposal/{procurement_id}/application/export")
async def export_bid_application(
    procurement_id: str,
    format: Literal["docx", "pdf"] = Query("docx", description="docx · pdf"),
    organization_id: str | None = Query(default=None),
) -> Response:
    """입찰참가신청서 서식 초안을 문서(DOCX/PDF)로 내려준다.

    발주기관이 준 서식 표를 그대로 두고 근거가 있는 칸만 채운다. 회사 상호·주소·
    대표자·주민등록번호·인감은 시스템이 지어낼 수 없어 빈칸으로 두고 담당자에게 넘긴다.
    표 모양이 무너지는 TXT는 지원하지 않는다.
    """
    context = deps.context_or_400(organization_id, None, procurement_id=procurement_id)
    try:
        payload, file_name, media_type = await bid_application_export.export_application(
            procurement_id, fmt=format, organization_id=context.organization_id
        )
    except proposal_export.PdfConverterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except bid_application_export.BidApplicationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _download(payload, file_name, media_type)


# ---------------------------------------------------------------------------
# 입찰 제안서 초안 — 제안요청서 목차 · 평가 기준대로 (11-03 · `bid_proposal_service`)
# ---------------------------------------------------------------------------


class BidPlanRequest(BaseModel):
    organization_id: str | None = None
    evidence_scope: str | None = None
    writer: Literal["claude", "codex"] = "claude"


@router.post("/api/proposal/{procurement_id}/plan-draft")
async def create_bid_plan(procurement_id: str, body: BidPlanRequest | None = None) -> dict:
    """제안서 초안을 만든다 — 대항목마다 Claude · Codex 한 번(한꺼번에 · 최대 270초). 제안요청서가 없으면 422."""
    request = body or BidPlanRequest()
    context = deps.context_or_400(request.organization_id, request.evidence_scope, procurement_id=procurement_id)
    analysis_store.guard_public_demo_write(context)  # 저장할 수 없는 곳이면 AI 를 부르기 전에 403
    try:
        with inflight.hold("bid_plan", context.organization_id, procurement_id):
            with inflight.hold("plan_writer", message=inflight.PLAN_WRITER_BUSY):
                view = await procurement_service.get_notice(procurement_id)
                if view is None:
                    raise HTTPException(status_code=404, detail="공고를 찾지 못했습니다")
                source = await run_in_threadpool(bid_proposal_service.load_source, procurement_id, view)
                company = plan_draft_service.company_sources(context.organization_id, context.evidence_scope)
                draft = await run_in_threadpool(bid_proposal_service.generate, source=source, company=company, writer=request.writer)
                shown, kept = bid_proposal_service.save(draft, context=context, procurement_id=procurement_id)
                view = await run_in_threadpool(bid_proposal_service.read_view, shown, context=context, procurement_id=procurement_id)
                bid_quality_gate.save_report(context, procurement_id, view, event="write")  # 품질 보고서 · 기록(2.7.0 · 2.8.0 B9)
                return {**view, "kept_previous": kept}
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except bid_proposal_service.BidPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/proposal/{procurement_id}/plan-outline")
async def get_bid_plan_outline(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """쓰기 전에 「이 양식으로 씁니다」 — 원문이 정한 제안서 목차 · 평가표 · 형식 규정(AI 없이 · 읽기만이라 열람자도 · 11-06 B-1).
    분석 전이면 422 · 제안요청서가 없으면 409(글은 POST 와 같다). 받아 둔 원문만 읽으므로 공고 목록(14일 창)을 묻지 않는다 —
    목록에서 빠진 공고도 저장된 초안 옆에서 양식을 볼 수 있어야 한다(검토 11-06)."""
    deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return await run_in_threadpool(bid_proposal_service.outline_preview, procurement_id, None)
    except bid_proposal_service.NoRfpError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except bid_proposal_service.BidPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/proposal/{procurement_id}/plan-draft")
async def get_bid_plan(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        draft = bid_proposal_service.load(procurement_id, context=context)
    except bid_proposal_service.BidPlanNotGeneratedError:
        raise HTTPException(status_code=404, detail="제안서 초안이 아직 없습니다 — 먼저 초안을 쓰세요")
    return await run_in_threadpool(bid_proposal_service.read_view, draft, context=context, procurement_id=procurement_id)


class BidPlanApproveRequest(BaseModel):
    organization_id: str | None = None
    evidence_scope: str | None = None
    note: str | None = Field(default=None, max_length=200)
    #: 승인하는 사람이 화면에서 본 초안 판(`quality.draft_hash`) — 그사이 다른 사람이 다시 썼으면 409(43차 M25 「읽은 판을 함께」 꼴 · 2.7.0 검토)
    draft_hash: str | None = Field(default=None, max_length=128)


def _load_bid_plan(procurement_id: str, context) -> dict:
    try:
        return bid_proposal_service.load(procurement_id, context=context)
    except bid_proposal_service.BidPlanNotGeneratedError:
        raise HTTPException(status_code=404, detail="제안서 초안이 아직 없습니다 — 먼저 초안을 쓰세요")


async def _bid_plan_view(procurement_id: str, context) -> dict:
    draft = _load_bid_plan(procurement_id, context)
    return await run_in_threadpool(bid_proposal_service.read_view, draft, context=context, procurement_id=procurement_id)


@router.post("/api/proposal/{procurement_id}/plan-draft/approve")
async def approve_bid_plan(procurement_id: str, body: BidPlanApproveRequest | None = None) -> dict:
    """사람 승인(2.7.0 · 계획 2) — 지금 초안 판에 묶인다(다시 쓰면 풀림). 차단 · 승인을 무효로 하는 검사(낡음 · 공고 불일치 · 검증 실패)가
    남으면 409 · 초안 없음 404 · 열람자는 미들웨어가 403."""
    request = body or BidPlanApproveRequest()
    context = deps.context_or_400(request.organization_id, request.evidence_scope, procurement_id=procurement_id)
    analysis_store.guard_public_demo_write(context)
    view = await _bid_plan_view(procurement_id, context)
    if request.draft_hash and request.draft_hash != view["quality"]["draft_hash"]:
        raise HTTPException(status_code=409, detail="그사이 초안이 바뀌었습니다 — 다시 읽은 뒤 승인하세요")
    if not bid_quality_gate.approvable(view["quality"]):
        raise HTTPException(status_code=409, detail=bid_quality_gate.approve_block_reason(view["quality"]))
    bid_quality_gate.save_approval(context, procurement_id, draft_hash=view["quality"]["draft_hash"], note=request.note)
    after = await _bid_plan_view(procurement_id, context)
    bid_quality_gate.save_report(context, procurement_id, after, event="approve")
    return after["quality"]


@router.delete("/api/proposal/{procurement_id}/plan-draft/approve")
async def revoke_bid_plan_approval(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """승인 취소 — 갱신된 품질."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    _load_bid_plan(procurement_id, context)  # 초안이 없으면 404
    bid_quality_gate.revoke_approval(context, procurement_id)
    after = await _bid_plan_view(procurement_id, context)
    bid_quality_gate.save_report(context, procurement_id, after, event="revoke")
    return after["quality"]


@router.get("/api/proposal/{procurement_id}/plan-draft/quality-report")
async def get_bid_plan_quality_report(
    procurement_id: str,
    format: Literal["json", "xlsx"] = Query("json"),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> Response:
    """검증 보고서 받기(2.8.0 B9 · 읽기만이라 열람자도) — 최신 품질 보고서 + 이 공고 기록 줄(JSON 파일) · `format=xlsx` 면 지금 초안의
    검사 항목 · 담당자 확인 사항 · 제출 서류 세 시트(2.10.0 T8 · `bid_quality_gate.quality_workbook`). 초안 없음 404."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    day = datetime.now(plan_export_service.KST).strftime("%Y%m%d")
    if format == "xlsx":
        view = await _bid_plan_view(procurement_id, context)
        payload = await run_in_threadpool(bid_quality_gate.quality_workbook, view)
        return _download(payload, f"제안서_검증보고서_{procurement_id}_{day}.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    _load_bid_plan(procurement_id, context)
    bundle = await run_in_threadpool(bid_quality_gate.quality_report, context, procurement_id)
    payload = json.dumps(bundle, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    return _download(payload, f"제안서_검증보고서_{procurement_id}_{day}.json", "application/json")


@router.post("/api/proposal/{procurement_id}/plan-draft/check-pdf")
async def check_bid_plan_pdf(
    procurement_id: str,
    file: UploadFile = File(...),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """한글에서 저장한 PDF 검사(2.10.0 T8 · D9 · D10 · 편집자 이상 — 열람자는 미들웨어가 403) — 쪽수 · A4 · 미작성 · 평가본 식별 낱말 ·
    표지 링크 · 예산 산수 · 조견표 실제 쪽. 결과는 품질 보고서 `last_pdf` · 기록 줄(event pdf_check)에 남기고 판정 · 승인은 바꾸지 않는다.
    .pdf 아님 415 · 20MB 넘음 413 · 빈 파일 422 · 초안 없음 404."""
    from app.api.organizations import read_upload

    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    if not str(file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="한글에서 「PDF 로 저장」한 .pdf 파일을 올리세요")
    payload = await read_upload(file)
    if not payload:
        raise HTTPException(status_code=422, detail="빈 파일입니다")
    try:
        # 같은 초안의 PDF 검사는 하나씩(11-13 독립 검토 — 큰 파일 여러 개가 작업자를 묶었다 · 읽기 쪽 · 시간 상한은 check_pdf 안)
        with inflight.hold("bid_pdf_check", context.organization_id, procurement_id):
            view = await _bid_plan_view(procurement_id, context)
            identity = await run_in_threadpool(bid_quality_gate.identity_for, view, context)
            result = await run_in_threadpool(bid_quality_gate.check_pdf, payload, view, identity=identity,
                                             draft_hash=view["quality"]["draft_hash"])
            view["quality"]["pdf_check"] = result  # 보고서 안 품질도 이번 검사(`last_pdf` 와 같은 값 · T8 검토)
            bid_quality_gate.save_report(context, procurement_id, view, event="pdf_check", pdf=result)
            return result
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/api/proposal/{procurement_id}/plan-draft/export")
async def export_bid_plan(
    procurement_id: str,
    format: Literal["docx", "pdf", "hwpx"] = Query("docx"),
    variant: Literal["submit", "review", "blind"] = Query("submit"),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> Response:
    """저장된 제안서 초안을 제출용(표식 · 메모 없음) · 검토용(근거 · 경고 · 메모) · 평가본(회사명 없음 · 11-06) 워드 · PDF · 한글(HWPX) 로 내려준다.

    막지 않는다(대표 결정 11-08) — 제출용 · 평가본 판은 품질 게이트가 「제출 준비」(차단 0 + 사람 승인)일 때만 「제안서_제출용_…」 ·
    「제안서_평가본_…」, 아니면 「제안서_초안_…」 · 「제안서_평가본_초안_…」(워드 · PDF 문서 정보 제목도). 본문 · 표지는 같다.
    내려받을 때마다 품질 보고서 · 기록을 남긴다. 한글은 구조 검사를 하고, 제출용 · 평가본은 만든 파일을 다시 읽어 미작성 칸 수를
    게이트 수와 맞춰 본다 — 다시 읽지 못하거나 수가 다르면 그 파일은 「초안」 이름으로 다시 만들어 내준다(2.8.0 B9)."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    shown = await _bid_plan_view(procurement_id, context)
    quality = shown["quality"]
    form = shown.get("form") or {}
    meta = bid_proposal_service.export_meta(shown, company=shown.get("company_name"))
    # 「초안」 · 「제출용」 — 제출용 · 평가본 판은 상태를 따른다(검토용 이름 규칙은 그대로) · 평가본만 받는 공고는 평가본이 「제출용」(2.10.0 D8)
    final = variant == "review" or quality["file_label"] == "제출용"
    blind_only = bool((shown.get("format") or {}).get("blind_only"))
    _label(meta, variant, final, blind_only)
    title = str(shown.get("title") or "제안서")
    hwpx_check = None
    if format == "pdf":
        try:
            payload, _method = await run_in_threadpool(plan_pdf_service.build_pdf, shown, form, title=title, variant=variant, meta=meta)
        except proposal_export.PdfConverterUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        media_type = "application/pdf"
    elif format == "hwpx":
        payload = await run_in_threadpool(plan_hwpx_service.build_hwpx, shown, form, title=title, variant=variant, meta=meta)
        media_type = plan_hwpx_service.MIMETYPE
        report = hwpx_template_service.validate_hwpx(payload)  # 한글 구조 검사(2.7.0 · 계획 11 — 있는 검사 함수)
        # blind_only — 평가본만 받는 공고면 화면 검사 줄이 판 이름을 바꿔 부른다(평가본 = 제출 파일 · 회사명 판 = 회사명 포함본 · 11-13 독립 검토)
        hwpx_check = {"at": datetime.now(timezone.utc).isoformat(), "variant": variant, "blind_only": blind_only, "draft_hash": quality["draft_hash"],
                      "ok": report.zip_ok and report.required_members_ok and report.xml_ok and report.mimetype_ok,
                      "missing_members": report.missing_members, "xml_errors": report.xml_errors[:5], "sections": report.section_count}
        if hwpx_check["ok"] and variant != "review":
            expected = plan_export_service.blank_total(shown, form, meta, variant=variant)
            hwpx_check.update(await run_in_threadpool(bid_quality_gate.recheck_hwpx, payload, expected=expected))
            if (not hwpx_check["match"] or hwpx_check.get("duplicate_majors")) and final:
                # 다시 읽은 파일이 게이트와 다르거나 대항목 번호가 겹치면 「제출용」 · 「평가본」으로 내주지 않는다 — 「초안」 이름으로 다시 만든다
                final = False
                _label(meta, variant, final, blind_only)
                payload = await run_in_threadpool(plan_hwpx_service.build_hwpx, shown, form, title=title, variant=variant, meta=meta)
                hwpx_check["relabeled"] = True
            hwpx_check["file_label"] = "제출용" if final else "초안"
    else:
        payload = await run_in_threadpool(plan_export_service.build_docx, shown, form, title=title, variant=variant, meta=meta)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    bid_quality_gate.save_report(context, procurement_id, shown, event="export", fmt=format, variant=variant, hwpx=hwpx_check)
    if hwpx_check is not None and not hwpx_check["ok"]:
        # 깨진 한글 파일은 내주지 않는다 — 열리지 않는 파일을 제출할 수 있다
        raise HTTPException(status_code=500, detail="한글(HWPX) 파일 구조 검사에 실패했습니다 — 워드 · PDF 로 받으세요")
    file_name = plan_export_service.export_file_name(title, format, variant=variant, draft=not final,
                                                     doc_kind=bid_proposal_service.DOC_KIND, blind_only=blind_only)
    return _download(payload, file_name, media_type)


def _label(meta: dict, variant: Literal["submit", "review", "blind"], final: bool, blind_only: bool = False) -> None:
    """워드 · PDF 문서 정보 제목의 판 이름(`plan_export_service.variant_label` — 파일 이름과 한 규칙) — 검토용은 그대로."""
    if variant != "review":
        meta["file_label"] = plan_export_service.variant_label(variant, final=final, blind_only=blind_only)
