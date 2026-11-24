"""공고문에 질문하기 (판 2.4.0) — 읽을 원문 상태(GET · 모두) · 질문(POST · 편집자 이상 · 미들웨어가 막고 활동 기록에 남긴다).

업무 로직은 `notice_qa_service` 에 있다. 같은 회사 · 같은 공고 동시 질문만 여기서 409 로 막는다(서버 전체 초안 잠금은 잡지 않음).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, field_validator

from app.api import deps
from app.core import inflight
from app.services import notice_qa_service

router = APIRouter()

UNKNOWN_DETAIL = "모르는 공고입니다 — 공고를 다시 골라 주세요"


class NoticeQuestion(BaseModel):
    question: str
    organization_id: str | None = None
    evidence_scope: str | None = None

    @field_validator("question")
    @classmethod
    def _tidy(cls, value: str) -> str:
        text = " ".join((value or "").split())
        if not 2 <= len(text) <= 300:
            raise ValueError("질문은 2~300자로 적어 주세요")
        return text


@router.get("/api/notice-qa/{item_id}")
async def notice_qa_state(
    item_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=item_id)
    try:
        return await run_in_threadpool(notice_qa_service.state, context, item_id)
    except notice_qa_service.UnknownItemError:
        raise HTTPException(status_code=404, detail=UNKNOWN_DETAIL)


@router.post("/api/notice-qa/{item_id}")
async def ask_notice_question(item_id: str, body: NoticeQuestion) -> dict:
    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=item_id)
    try:
        with inflight.hold("notice_qa", context.organization_id, item_id, message="이 공고에 대한 질문에 답하는 중입니다 — 끝난 뒤 다시 물어 주세요"):
            return await run_in_threadpool(notice_qa_service.ask, context, item_id, body.question)
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except notice_qa_service.UnknownItemError:
        raise HTTPException(status_code=404, detail=UNKNOWN_DETAIL)
