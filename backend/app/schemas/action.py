"""공고별 Action Checklist — 담당자가 해야 할 일.

Critical Condition에서 자동으로 씨앗을 뿌리고(설명회 등록, 서류 준비 …), 담당자가 직접 추가·완료한다.
완료 여부는 사람이 정한다. 시스템이 done으로 바꾸지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.text_fields import PersonName, TitleText

ActionStatus = Literal["todo", "doing", "done", "blocked", "na"]
ActionPriority = Literal["urgent", "high", "normal", "low"]
ActionOrigin = Literal["auto", "manual"]


class ActionItem(BaseModel):
    id: str
    procurement_id: str
    title: str = Field(min_length=1, max_length=200)
    status: ActionStatus = "todo"
    priority: ActionPriority = "normal"
    due_at: datetime | None = None
    owner: str | None = Field(default=None, max_length=60)
    # 어느 Critical Condition에서 나왔는지 (자동 생성 항목의 중복 방지 키)
    source_condition_id: str | None = None
    requirement_id: str | None = None
    # 완료 근거 (예: "등록 확인 메일 2026-09-10", 파일명)
    evidence: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    origin: ActionOrigin = "manual"
    # 이 항목을 마지막으로 바꾼 **인증된 계정** (S12). `owner` 는 담당자가 적는 이름이고
    # 이것은 서명된 신원에서 온 사실이다. 인증이 꺼진 로컬에서는 None.
    recorded_by: str | None = Field(default=None, max_length=64)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ActionCounts(BaseModel):
    total: int = Field(ge=0)
    todo: int = Field(ge=0)
    doing: int = Field(ge=0)
    done: int = Field(ge=0)
    blocked: int = Field(ge=0)
    na: int = Field(ge=0)
    overdue: int = Field(ge=0)


class ActionChecklist(BaseModel):
    procurement_id: str
    items: list[ActionItem]
    counts: ActionCounts
    updated_at: datetime | None = None
    schema_version: int = 2
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False


class ActionCreateRequest(BaseModel):
    title: TitleText
    priority: ActionPriority = "normal"
    due_at: datetime | None = None
    owner: PersonName | None = None
    source_condition_id: str | None = Field(default=None, max_length=80)
    requirement_id: str | None = Field(default=None, max_length=16)
    note: str | None = Field(default=None, max_length=2000)


class ActionUpdateRequest(BaseModel):
    title: TitleText | None = None
    status: ActionStatus | None = None
    priority: ActionPriority | None = None
    due_at: datetime | None = None
    owner: PersonName | None = None
    evidence: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    # due_at / owner 를 비우고 싶을 때 명시적으로 true
    clear_due_at: bool = False
