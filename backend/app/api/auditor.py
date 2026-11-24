"""AI Auditor API.

- POST /api/auditor/run          붙여넣은 초안 텍스트를 검사
- POST /api/auditor/run/upload   제안서 파일(HWP/HWPX/PDF)을 올려 검사
- GET  /api/auditor/{run_id}     저장된 검사 결과 재조회
- GET  /api/auditor/{procurement_id}/latest        이 공고의 가장 최근 검사 결과 (없으면 204)
- GET  /api/auditor/{procurement_id}/resolutions   발견 항목 담당자 해결 처리 조회
- PUT  /api/auditor/{procurement_id}/resolutions   발견 항목 해결/재오픈 저장 (사람이 정한다)

rfp.py와 같은 이유로 prefix 없이 전체 경로를 적는다.
비즈니스 로직은 전부 auditor_service에 있고 여기서는 입출력과 오류 변환만 한다.
"""

from __future__ import annotations

import importlib.util
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api import deps
from app.core import inflight, requester, storage
from app.schemas.audit import AuditRun, AuditRunRequest
from app.schemas.organization import AnalysisContext
from app.schemas.finding_resolution import (
    FindingResolution,
    FindingResolutionList,
    FindingResolutionRequest,
)
from app.services import (
    analysis_state,
    auditor_service,
    proposal_service,
    document_extractor,
    finding_resolution_service,
    review_service,
    rfp_parser,
    wording,
)

logger = logging.getLogger(__name__)


def _shown(run: AuditRun, context: AnalysisContext | None = None) -> AuditRun:
    """응답용 점검 결과 — 처리 키는 새 말로 바꾸기 **전** 원문으로 싣고(33차 R32-12) 글만 새 말로.

    화면이 응답 글로 키를 다시 만들면 저장된 해결 기록(옛 글로 만든 키)과 어긋나 「해결」이 떨어졌다.
    32차에 새 말 키로 남은 기록은 별칭으로 잇는다(34차 R33-08 · `finding_resolution_service.shown_key`).
    """
    stored = finding_resolution_service.stored_keys(run.procurement_id, context)
    findings = [f.model_copy(update={"resolution_key": finding_resolution_service.shown_key(f, stored)}) for f in run.findings]
    return wording.modernize_model(run.model_copy(update={"findings": findings}))

router = APIRouter(tags=["auditor"])

# 멀티파트 업로드는 python-multipart가 필요하다. 없으면 업로드 경로만 빼고
# 나머지 API는 그대로 살린다 (설치 누락으로 데모 전체가 죽지 않게 한다).
MULTIPART_AVAILABLE = bool(
    importlib.util.find_spec("python_multipart") or importlib.util.find_spec("multipart")
)

# 제안서 업로드 상한. 첨부 다운로드 상한(30MB)보다 보수적으로 잡는다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_CHUNK = 64 * 1024
#: .docx — 앱이 내려 주는 제안서 · 사업계획서 초안이 워드다(2.1.6 · 예전에는 「PDF 로 저장해 올리세요」).
ALLOWED_SUFFIXES = (".pdf", ".hwp", ".hwpx", ".docx", ".txt", ".md")


def _raise_for_requirements(exc: Exception) -> None:
    if isinstance(exc, rfp_parser.RfpFixtureNotFoundError):
        raise HTTPException(status_code=404, detail="Unknown RFP procurement id")
    if isinstance(exc, rfp_parser.RfpNotParsedError):
        raise HTTPException(
            status_code=404,
            detail="RFP not parsed yet. Call POST /api/rfp/parse first",
        )
    raise exc


def _guard_readiness(
    procurement_id: str, proposal_text: str, mode: str, context: AnalysisContext
) -> None:
    """이전 요구사항 집합 기준의 초안을 «일반 검사»로 돌리는 것을 막는다.

    막는 이유는 결과가 틀려서가 아니라 **읽는 사람이 속기 때문**이다. 32건 기준으로
    만든 초안을 55건 집합과 견주면 새로 발견된 요구사항이 전부 「지금 초안의 결함」
    처럼 보인다. 일부러 견주고 싶으면 mode="change_impact" 로 실행한다 —
    그 결과는 화면에서 「변경 영향 분석」으로 따로 표시된다.
    """
    if mode == "change_impact":
        return
    readiness = analysis_state.audit_readiness(procurement_id, context=context)
    if readiness.ready:
        return
    blocking = [b for b in readiness.blockers if b in analysis_state.HARD_BLOCKERS]
    if not blocking:
        return
    # **저장된 그 초안을 검사할 때만** 막는다. 담당자가 새 초안을 붙여넣거나 올린
    # 경우는 이전 집합 기준이 아니므로 그대로 돌린다 — 막으면 기존 기능이 사라진다.
    if not _is_stored_proposal(procurement_id, proposal_text, context):
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": blocking[0].upper(),
            "message": readiness.message,
            **readiness.to_dict(),
        },
    )


def _is_stored_proposal(procurement_id: str, proposal_text: str, context: AnalysisContext) -> bool:
    """검사 대상 본문이 저장된 초안과 같은가 (해시 대조)."""
    try:
        section = proposal_service.load_section(procurement_id, context)
    except Exception:  # noqa: BLE001 — 저장된 초안이 없으면 붙여넣기다
        return False
    stored = section.proposal_hash or proposal_service.section_hash(section.sentences)
    return stored == auditor_service.proposal_hash(proposal_text)


def _stored_text_for(procurement_id: str, proposal_text: str, context: AnalysisContext) -> str:
    """보낸 글이 **저장된 초안을 새 말로 바꾼 판**이면 저장된 원문을 돌려준다(32차 마지막 검토).

    화면은 저장된 초안을 옛 글 → 새 말로 바꿔(`wording`) 받고 그 글로 점검을 부른다. 그 글로 점검하면 해시가 저장 초안과
    달라져 「저장된 초안」 막음 · 저장 열쇠 · 승인 대조(review_service)가 어긋난다. 그래서 점검은 저장 원문으로 하고
    응답만 새 말로 바꾼다. 붙여넣은 다른 글 · 올린 파일은 그대로.
    """
    try:
        section = proposal_service.load_section(procurement_id, context)
    except Exception:  # noqa: BLE001 — 저장된 초안이 없으면 붙여넣기다
        return proposal_text
    sent = auditor_service.proposal_hash(proposal_text)
    raw = "\n".join(s.text for s in section.sentences)
    if auditor_service.proposal_hash(raw) == sent:
        return proposal_text
    if proposal_service.section_hash(wording.modernize_model(section).sentences) == sent:
        return raw
    return proposal_text


def _audit(
    procurement_id: str,
    proposal_text: str,
    *,
    use_llm: bool,
    document: str | None,
    context: AnalysisContext,
    mode: str = "standard",
) -> AuditRun:
    if document is None:
        proposal_text = _stored_text_for(procurement_id, proposal_text, context)
    _guard_readiness(procurement_id, proposal_text, mode, context)
    try:
        # **같은 검사**(회사 · 범위 · 공고 · 초안 · 방식 · AI 여부 = 저장 열쇠)는 한 번에 하나만 — 같은 파일을 두 번 쓰지 않게
        # (27차 R26-12). 입력이 다른 검사는 서로 다른 파일이라 막지 않는다 — 화면이 여는 순간 도는 규칙 검사가 오래 걸리는
        # AI 점검 때문에 409 가 되지 않게(검수 C15). 붙여넣기 · 파일 두 길이 같이 지난다.
        with inflight.hold(
            "auditor", context.organization_id, context.evidence_scope, procurement_id,
            auditor_service.proposal_hash(proposal_text), mode, str(use_llm),
        ):
            # 저장된 옛 결과를 그대로 돌려주는 경우가 있다(같은 열쇠) — 응답은 새 말로(32차 §3-E-2 · 마지막 검토)
            return _shown(auditor_service.run_and_store(
                procurement_id,
                proposal_text,
                use_llm=use_llm,
                source_document=document,
                context=context,
                mode=mode,
                # 평가본 식별 · 예산 산수는 올린 파일 · 붙여 넣은 글만 — 대시보드가 열 때 도는 앱 저장 초안(회사 이름이 든 내부 글)은 아님(T8 검토)
                uploaded=document is not None or not _is_stored_proposal(procurement_id, proposal_text, context),
            ), context)
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (rfp_parser.RfpFixtureNotFoundError, rfp_parser.RfpNotParsedError) as exc:
        _raise_for_requirements(exc)
        raise  # pragma: no cover - _raise_for_requirements가 항상 올린다
    except auditor_service.EmptyProposalError as exc:
        raise HTTPException(status_code=422, detail=f"제안서 초안이 비어 있습니다: {exc}")


@router.post("/api/auditor/run", response_model=AuditRun)
async def run_auditor(body: AuditRunRequest) -> AuditRun:
    """붙여넣은 제안서 초안을 RFP 요구사항과 역대조한다. 결과는 회사·근거 범위에 고정된다."""
    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=body.procurement_id)
    # 검사의 AI 2차 판단은 동기 호출(8개씩 최대 5번)이다 — 파일 검사처럼 스레드에서(ISSUE-144).
    return await run_in_threadpool(
        _audit,
        body.procurement_id,
        body.proposal_text,
        use_llm=body.use_llm,
        document=None,
        context=context,
        mode=body.mode,
    )


@router.get("/api/auditor/{procurement_id}/readiness")
async def auditor_readiness(
    procurement_id: str,
    organization_id: str | None = None,
    evidence_scope: str | None = None,
) -> dict:
    """지금 Auditor 를 돌려도 되는가. 안 되면 무엇을 할 수 있는지 함께 준다."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    return analysis_state.audit_readiness(procurement_id, context=context).to_dict()


@router.get("/api/auditor/{procurement_id}/change-impact")
async def auditor_change_impact(
    procurement_id: str,
    organization_id: str | None = None,
    evidence_scope: str | None = None,
) -> dict:
    """이전 요구사항 집합 → 현재 집합의 변화. 일반 감사 결과와 분리해 보여준다."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return analysis_state.change_impact(procurement_id, context=context)
    except (rfp_parser.RfpFixtureNotFoundError, rfp_parser.RfpNotParsedError) as exc:
        _raise_for_requirements(exc)
        raise  # pragma: no cover


async def run_auditor_upload(
    procurement_id: str = Form(...),
    file: UploadFile = File(...),
    use_llm: bool = Form(True),
    organization_id: str | None = Form(None),
    evidence_scope: str | None = Form(None),
) -> AuditRun:
    """업로드한 제안서 파일에서 텍스트를 뽑아 검사한다 (나라장터 첨부와 같은 추출 경로)."""
    file_name = Path(file.filename or "proposal").name
    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 형식입니다: {suffix or '확장자 없음'} "
            f"(허용: {', '.join(ALLOWED_SUFFIXES)})",
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"upload{suffix}"
        written = 0
        with tmp_path.open("wb") as handle:
            while chunk := await file.read(UPLOAD_CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"업로드 상한({MAX_UPLOAD_BYTES} bytes)을 초과했습니다",
                    )
                handle.write(chunk)

        if written == 0:
            raise HTTPException(status_code=422, detail="빈 파일입니다")

        if suffix in (".txt", ".md"):
            proposal_text = tmp_path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".docx":
            # 시그니처 판별(extract_document)은 워드를 압축 첨부로 본다 — 워드 전용 함수로 읽는다.
            try:
                pages = await run_in_threadpool(document_extractor.extract_docx, tmp_path)
            except document_extractor.DocumentExtractionError as exc:
                raise HTTPException(status_code=422, detail=f"문서 텍스트 추출 실패: {exc}")
            proposal_text = "\n".join(page.text for page in pages)
        else:
            try:
                # 문서 추출은 동기·CPU 작업이다. 이벤트 루프에서 직접 돌리면 그동안
                # `/health` 를 포함한 다른 모든 요청이 선다 (ISSUE-031).
                extracted = await run_in_threadpool(
                    document_extractor.extract_document, tmp_path, file_name=file_name
                )
            except document_extractor.DocumentExtractionError as exc:
                raise HTTPException(status_code=422, detail=f"문서 텍스트 추출 실패: {exc}")
            proposal_text = extracted.text

    if not proposal_text.strip():
        raise HTTPException(status_code=422, detail="문서에서 텍스트를 추출하지 못했습니다")

    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    # 검사 자체도 규칙 + (선택) LLM 으로 길다. 같은 이유로 스레드에서 돌린다.
    return await run_in_threadpool(
        _audit, procurement_id, proposal_text, use_llm=use_llm, document=file_name, context=context
    )


if MULTIPART_AVAILABLE:
    router.add_api_route(
        "/api/auditor/run/upload",
        run_auditor_upload,
        methods=["POST"],
        response_model=AuditRun,
        tags=["auditor"],
    )
else:  # pragma: no cover - 의존성이 없는 환경에서만 실행된다
    logger.warning(
        "python-multipart가 없어 /api/auditor/run/upload를 등록하지 않습니다. "  # 화면 문장 아님(서버 로그)
        "붙여넣기 검사(POST /api/auditor/run)는 그대로 동작합니다."  # 화면 문장 아님(서버 로그)
    )


@router.get("/api/auditor/{run_id}", response_model=AuditRun)
async def get_audit_run(
    run_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> AuditRun:
    # 컨텍스트를 주면 그 조직의 결과만, 없으면 공개(합성) 위치만 본다 — 다른 조직 결과는 보이지 않는다.
    context = deps.context_or_400(organization_id, evidence_scope) if (organization_id or evidence_scope) else None
    try:
        return _shown(auditor_service.load_run(run_id, context=context), context)
    except auditor_service.AuditRunNotFoundError:
        raise HTTPException(status_code=404, detail="Audit run not found")


def _latest_stored_run(procurement_id: str, context: AnalysisContext) -> AuditRun | None:
    """이 공고의 저장된 검사 결과 중 가장 최근 것(45차 M6 — 「검토 중」 탭 · 머리 칩도 같은 결과를 세려고 서비스로 옮김)."""
    return auditor_service.latest_stored_run(procurement_id, context)


@router.get(
    "/api/auditor/{procurement_id}/latest",
    response_model=AuditRun,
    responses={204: {"description": "아직 저장된 검사 결과가 없음"}},
)
async def get_latest_audit_run(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
):
    """이 공고의 «가장 최근 저장된» 검사 결과. 아직 없으면 **204**다.

    화면을 열 때마다 검사를 다시 돌리지 않아도 되게 하는 읽기 경로다 (ISSUE-060).
    공용 데모 결과는 «쓰기»만 기본 회사로 한정돼 있고 읽기는 모든 회사에 열려 있다 —
    그런데 화면이 로드마다 재검사를 요청하는 바람에 다른 회사에서는 저장된 결과가 있는데도
    403 이 나고 「아직 검사하지 않음」처럼 보였다.

    review.py 와 같은 이유로 없을 때 404 가 아니라 204 다: 「아직 없다」는 오류가 아니고,
    404 는 화면을 열 때마다 브라우저 콘솔에 빨간 줄을 남겨 진짜 오류를 묻는다.
    """
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        # 폴더 전체를 읽는 동기 I/O 다. 이벤트 루프에서 직접 돌리지 않는다 (ISSUE-031).
        run = await run_in_threadpool(_latest_stored_run, procurement_id, context)
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if run is None:
        return Response(status_code=204)
    return _shown(run, context)


@router.get("/api/auditor/{procurement_id}/resolutions", response_model=FindingResolutionList)
async def get_finding_resolutions(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> FindingResolutionList:
    """담당자가 해결/재오픈 처리한 발견 항목 기록. 없으면 빈 목록."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return finding_resolution_service.load_resolutions(procurement_id, context)
    except finding_resolution_service.InvalidProcurementIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/api/auditor/{procurement_id}/resolutions", response_model=FindingResolution)
async def put_finding_resolution(
    request: Request,
    procurement_id: str,
    body: FindingResolutionRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> FindingResolution:
    """발견 항목을 해결 또는 다시 열림으로 기록한다.

    AI가 아니라 담당자의 판단이며, Auditor 검사 결과 자체는 바꾸지 않는다.
    """
    if not review_service.known_procurement(procurement_id):
        raise HTTPException(
            status_code=404,
            detail="이 공고는 아직 분석 전입니다 — 「공고 분석 시작」으로 요구사항을 뽑은 뒤 저장하세요.",  # API 주소를 화면에 적지 않는다(27차 §3-H · DSH-02)
        )
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return finding_resolution_service.save_resolution(
            procurement_id, body, context=context, recorded_by=requester.recorded_by(request)
        )
    except finding_resolution_service.InvalidProcurementIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
