"""공고 직접 넣기 · 확인 전 후보함 · 오늘 열어 본 곳 (38차 §3-E).

- GET    /api/manual-notices                       직접 넣은 공고 목록(원본 입력)
- POST   /api/manual-notices                       넣기(저장본에 있는 공고면 새로 만들지 않고 그 id)
- PUT    /api/manual-notices/{id}                  고치기
- DELETE /api/manual-notices/{id}                  지우기(그 회사 폴더 안에서만)
- POST   /api/manual-notices/{id}/document         공고문 파일(pdf · hwp · hwpx · docx · 20MB) — 조항을 뽑는다
- GET    /api/notice-inbox                         확인 전 후보함
- POST   /api/notice-inbox/paste                   GPT 결과 붙여넣기(LLM 없이 기계적으로)
- POST   /api/notice-inbox/{id}/discard            버리기(사유)
- GET    /api/watchlist                            오늘 열어 본 곳
- PUT    /api/watchlist                            고치기 · 더하기
- POST   /api/watchlist/{id}/opened                「열기」 누른 시각만 적는다(서버는 그 사이트를 읽지 않는다)

판정 · 순위는 통합 목록(`GET /api/business-opportunities?source=manual`)이 한다 — 여기서는 저장만 한다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api import deps
from app.api.organizations import read_upload
from app.core import requester
from app.schemas.manual_notice import (
    InboxDiscardRequest,
    InboxEntry,
    InboxPasteRequest,
    InboxPasteResult,
    ManualHumanPassRequest,
    ManualNotice,
    ManualNoticeInput,
    ManualSaveResult,
    WatchListUpdate,
    WatchSite,
)
from app.services import manual_notice_service, notice_inbox_service, user_service, watchlist_service

router = APIRouter(tags=["manual"])


def _org(organization_id: str | None) -> str:
    return deps.context_or_400(organization_id, None).organization_id


def _named(notice: ManualNotice) -> ManualNotice:
    """응답에 화면용 이름을 붙인다(45차 M11) — 저장본은 아이디 그대로."""
    return notice.model_copy(update={
        "created_by_name": user_service.display_name_of(notice.created_by),
        "updated_by_name": user_service.display_name_of(notice.updated_by),
    })


def _named_site(site: WatchSite) -> WatchSite:
    return site.model_copy(update={"last_opened_by_name": user_service.display_name_of(site.last_opened_by)})


@router.get("/api/manual-notices", response_model=list[ManualNotice])
async def list_manual_notices(organization_id: str | None = Query(default=None)) -> list[ManualNotice]:
    return [_named(n) for n in manual_notice_service.list_notices(_org(organization_id))]


@router.post("/api/manual-notices", response_model=ManualSaveResult, status_code=201)
async def create_manual_notice(body: ManualNoticeInput, organization_id: str | None = Query(default=None)) -> ManualSaveResult:
    deps.require_writable()
    result = manual_notice_service.create(_org(organization_id), body, created_by=requester.current_recorded_by())
    return result.model_copy(update={"notice": _named(result.notice)}) if result.notice is not None else result


@router.put("/api/manual-notices/{notice_id}", response_model=ManualNotice)
async def update_manual_notice(
    notice_id: str,
    body: ManualNoticeInput,
    organization_id: str | None = Query(default=None),
    expected_updated_at: datetime | None = Query(default=None),
) -> ManualNotice:
    deps.require_writable()
    try:
        # 44차 마지막 검토 — 모집 대상을 바꾸면 올린 공고문을 다시 읽는다(S7 · 수십 초) — 올리기처럼 따로 돌린다(워커 하나짜리 서버가 멈추지 않게)
        return _named(await run_in_threadpool(
            manual_notice_service.update, _org(organization_id), notice_id, body,
            updated_by=requester.current_recorded_by(), expected_updated_at=expected_updated_at,
        ))
    except manual_notice_service.ManualNoticeNotFoundError:
        raise HTTPException(status_code=404, detail="직접 넣은 공고를 찾지 못했습니다")


@router.delete("/api/manual-notices/{notice_id}", status_code=204)
async def delete_manual_notice(notice_id: str, organization_id: str | None = Query(default=None)) -> None:
    deps.require_writable()
    try:
        manual_notice_service.delete(_org(organization_id), notice_id)
    except manual_notice_service.ManualNoticeNotFoundError:
        raise HTTPException(status_code=404, detail="직접 넣은 공고를 찾지 못했습니다")


def _gate_now(organization_id: str, notice_id: str) -> str | None:
    """지금 규칙이 낸 판정(목록과 같은 길 · 44차 M6) — 「원문 확인함 — 가능으로」는 불가 줄이 있으면 받지 않는다."""
    return manual_notice_service.gate_now(organization_id, notice_id)


@router.put("/api/manual-notices/{notice_id}/human-pass", response_model=ManualNotice)
async def set_manual_human_pass(
    notice_id: str,
    body: ManualHumanPassRequest,
    organization_id: str | None = Query(default=None),
    expected_updated_at: datetime | None = Query(default=None),
) -> ManualNotice:
    """「원문 확인함 — 가능으로」(44차 M6 · D16) — 편집자 · 관리자만(열람자는 역할 검사가 403) · 누가 · 이유 필수 · 활동 기록에 남는다."""
    deps.require_writable()
    org = _org(organization_id)
    try:
        return _named(manual_notice_service.set_human_pass(
            org, notice_id, by=body.by, reason=body.reason, expected_updated_at=expected_updated_at, gate_now=_gate_now(org, notice_id),
            recorded_by=requester.current_recorded_by(),
        ))
    except manual_notice_service.ManualNoticeNotFoundError:
        raise HTTPException(status_code=404, detail="직접 넣은 공고를 찾지 못했습니다")
    except manual_notice_service.HumanPassRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/api/manual-notices/{notice_id}/human-pass", response_model=ManualNotice)
async def clear_manual_human_pass(
    notice_id: str,
    by: str = Query(min_length=1, max_length=60),
    organization_id: str | None = Query(default=None),
    expected_updated_at: datetime | None = Query(default=None),
) -> ManualNotice:
    """「가능」 되돌리기(44차 M6) — 다시 규칙 판정(확인 필요)으로."""
    deps.require_writable()
    try:
        return _named(manual_notice_service.set_human_pass(
            _org(organization_id), notice_id, by=by, reason=None, expected_updated_at=expected_updated_at,
            recorded_by=requester.current_recorded_by(),
        ))
    except manual_notice_service.ManualNoticeNotFoundError:
        raise HTTPException(status_code=404, detail="직접 넣은 공고를 찾지 못했습니다")


@router.post("/api/manual-notices/{notice_id}/document", response_model=ManualNotice)
async def upload_manual_document(
    notice_id: str, file: UploadFile = File(...), organization_id: str | None = Query(default=None)
) -> ManualNotice:
    deps.require_writable()
    org = _org(organization_id)
    payload = await read_upload(file)
    try:
        # 40차 MANUAL-03 — 문서 읽기(PDF · HWP 풀기 · 조항 뽑기)는 수십 초 걸릴 수 있다 — 그동안 다른 API(목록 · 대시보드)가 멈추지 않게 따로 돌린다
        return _named(await run_in_threadpool(
            manual_notice_service.attach_document, org, notice_id, file_name=file.filename or "공고문", payload=payload
        ))
    except manual_notice_service.ManualNoticeNotFoundError:
        raise HTTPException(status_code=404, detail="직접 넣은 공고를 찾지 못했습니다")
    except manual_notice_service.ManualNoticeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/notice-inbox", response_model=list[InboxEntry])
async def list_inbox(organization_id: str | None = Query(default=None)) -> list[InboxEntry]:
    return notice_inbox_service.load(_org(organization_id))


@router.post("/api/notice-inbox/paste", response_model=InboxPasteResult)
async def paste_inbox(
    body: InboxPasteRequest, organization_id: str | None = Query(default=None), preview: bool = Query(default=False)
) -> InboxPasteResult:
    deps.require_writable()
    return notice_inbox_service.paste(_org(organization_id), body.text, preview=preview)


@router.post("/api/notice-inbox/{entry_id}/discard", response_model=InboxEntry)
async def discard_inbox(entry_id: str, body: InboxDiscardRequest, organization_id: str | None = Query(default=None)) -> InboxEntry:
    deps.require_writable()
    try:
        return notice_inbox_service.discard(_org(organization_id), entry_id, body.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="후보함에 없는 줄입니다")


@router.get("/api/watchlist", response_model=list[WatchSite])
async def get_watchlist(organization_id: str | None = Query(default=None)) -> list[WatchSite]:
    return [_named_site(s) for s in watchlist_service.load(_org(organization_id))]


@router.put("/api/watchlist", response_model=list[WatchSite])
async def put_watchlist(body: WatchListUpdate, organization_id: str | None = Query(default=None)) -> list[WatchSite]:
    deps.require_writable()
    return [_named_site(s) for s in watchlist_service.replace(_org(organization_id), body.sites, base=body.base, saved_by=requester.current_recorded_by())]


@router.post("/api/watchlist/{site_id}/opened", response_model=WatchSite)
async def mark_watch_opened(site_id: str, organization_id: str | None = Query(default=None)) -> WatchSite:
    deps.require_writable()
    try:
        return _named_site(watchlist_service.mark_opened(_org(organization_id), site_id, by=requester.current_recorded_by()))
    except LookupError:
        raise HTTPException(status_code=404, detail="목록에 없는 곳입니다")
