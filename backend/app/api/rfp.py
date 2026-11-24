"""RFP 파싱 API.

- 합성 fixture(`synthetic-rfp-0001`)는 데모 시나리오·Gold 평가용 경로다.
- 그 외 `g2b-...` 형태의 ID는 실제 나라장터 공고로 보고, 제안요청서 첨부를
  내려받아 파싱한다.

라우터에 prefix를 두지 않고 경로를 전체로 적는다. 첨부 목록 엔드포인트가
`/api/procurements/...` 아래에 있어야 하기 때문이다 (main.py는 이 router 하나만 include).
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.schemas.requirement import RfpParseRequest, RfpParseResult
from app.services import attachment_service, document_extractor, procurement_service, rfp_parser

router = APIRouter(tags=["rfp"])

# 화면에 그대로 붙는 말이라 한국어로 — 영문 「Unknown RFP fixture id」가 보였다 (RFP-13).
UNSUPPORTED_NOTICE_DETAIL = "지원하지 않는 공고 주소입니다. 나라장터 공고나 가상 예시 공고만 분석할 수 있습니다."


def _raise_for_parse_error(exc: Exception) -> None:
    """실제 공고 파싱 실패를 의미 있는 HTTP 코드로 옮긴다 (500 스택트레이스 금지)."""
    if isinstance(exc, rfp_parser.RealNoticeNotFoundError):
        raise HTTPException(
            status_code=404,
            detail="현재 조회 창에서 해당 공고를 찾을 수 없습니다",
        )
    if isinstance(exc, rfp_parser.RfpAttachmentNotFoundError):
        raise HTTPException(status_code=422, detail=f"제안요청서 첨부를 찾을 수 없습니다: {exc}")
    if isinstance(exc, rfp_parser.RealExtractorUnavailableError):
        raise HTTPException(
            status_code=503,
            detail="실제 RFP 요구사항 추출기가 아직 준비되지 않았습니다",
        )
    if isinstance(exc, attachment_service.AttachmentFetchDisabledError):
        # 실패가 아니라 **고정 모드라서 안 받은 것**이다 (19차 §4-A-4). 화면이 「다운로드 실패」로
        # 읽지 않게 사유를 그대로 준다.
        raise HTTPException(status_code=409, detail=f"첨부를 새로 받지 않았습니다 — {exc}")
    if isinstance(exc, attachment_service.AttachmentTooLargeError):
        raise HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, attachment_service.AttachmentError):
        raise HTTPException(status_code=502, detail=f"첨부 다운로드 실패: {exc}")
    if isinstance(exc, document_extractor.DocumentExtractionError):
        raise HTTPException(status_code=502, detail=f"첨부 텍스트 추출 실패: {exc}")
    raise exc


@router.post("/api/rfp/parse", response_model=RfpParseResult)
async def parse_rfp(body: RfpParseRequest) -> RfpParseResult:
    """RFP를 파싱해 Requirement 목록을 생성·저장한다.

    - 등록된 fixture ID: 로컬 합성 RFP(PDF)
    - `g2b-...` 공고 ID: 실제 공고 첨부(HWP/HWPX/PDF). attachment_index 생략 시 자동 선택.
    """
    procurement_id = body.procurement_id

    if rfp_parser.is_fixture(procurement_id):
        # PDF 파싱은 동기·CPU 작업이다. 이벤트 루프에서 직접 돌리면 그동안 다른 요청이
        # 전부 선다 (ISSUE-031).
        return await run_in_threadpool(rfp_parser.parse_and_store, procurement_id)

    if not rfp_parser.is_real_notice_id(procurement_id):
        raise HTTPException(status_code=404, detail=UNSUPPORTED_NOTICE_DETAIL)

    try:
        return await rfp_parser.parse_real_notice(
            procurement_id, body.attachment_index, fetch_attachment=body.fetch_attachment
        )
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")
    except (
        rfp_parser.RealNoticeNotFoundError,
        rfp_parser.RfpAttachmentNotFoundError,
        rfp_parser.RealExtractorUnavailableError,
        attachment_service.AttachmentError,
        document_extractor.DocumentExtractionError,
    ) as exc:
        _raise_for_parse_error(exc)
        raise  # pragma: no cover - _raise_for_parse_error가 항상 올린다


@router.get("/api/rfp/{procurement_id}/requirements", response_model=RfpParseResult)
async def get_requirements(procurement_id: str) -> RfpParseResult:
    try:
        return rfp_parser.load_generated(procurement_id)
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail=UNSUPPORTED_NOTICE_DETAIL)
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(
            status_code=404,
            detail="아직 분석하지 않은 공고입니다. 먼저 공고 분석을 실행하세요.",
        )


@router.get("/api/procurements/{notice_id}/attachments")
async def list_notice_attachments(notice_id: str) -> dict[str, Any]:
    """공고 첨부 목록과 자동 선택된 제안요청서 인덱스를 반환한다."""
    try:
        view = await procurement_service.get_notice(notice_id)
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")
    if view is None:
        raise HTTPException(status_code=404, detail="Notice not found in current candidate window")

    attachments = rfp_parser.list_attachments(view)
    rfp_index = attachment_service.pick_rfp_attachment(attachments)
    notice_index = attachment_service.pick_notice_document(attachments)
    # 로컬에 이미 받아 둔 첨부인가 (27차 §3-A-1) — 화면이 「받고 분석」 확인 창을 띄울지 여기서 정한다.
    cached = [
        attachment_service.cached_attachment(view.notice.id, index, attachment["name"])
        for index, attachment in enumerate(attachments)
    ]
    return {
        "notice_id": view.notice.id,
        "notice_title": view.notice.title,
        "count": len(attachments),
        "rfp_index": rfp_index,
        "rfp_cached": rfp_index is not None and cached[rfp_index] is not None,
        "notice_index": notice_index,
        "notice_cached": notice_index is not None and cached[notice_index] is not None,
        "attachments": [
            {
                "index": index,
                "name": attachment["name"],
                "url": attachment["url"],
                "is_rfp": index == rfp_index,
                "downloadable": attachment_service.is_allowed_url(attachment["url"]),
                "cached": cached[index] is not None,
                "size_bytes": cached[index].stat().st_size if cached[index] is not None else None,
                # 이 첨부가 제안요청서류인가 입찰공고문인가 — 확인 창이 받을 문서를 제 이름으로 부르게(27차 검수 C17 ·
                # 「입찰공고」는 제안요청서 자리 3순위로 골라지지만 문서는 공고문이다). 압축 파일은 안을 열어야 안다(None).
                "document_role": None if attachment["name"].lower().endswith(".zip") else attachment_service.document_role(attachment["name"]),
            }
            for index, attachment in enumerate(attachments)
        ],
    }
