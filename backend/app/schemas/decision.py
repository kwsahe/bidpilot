"""입찰 참여 결정 (GO / HOLD / NO_GO / UNREVIEWED).

사람이 내리고 사람이 저장한다. AI는 제출 여부를 확정하지 않는다 (CLAUDE.md 4-I, 25).
GO는 미해결 BLOCKER(Critical Condition)가 없을 때만 저장할 수 있다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.text_fields import PersonName, ShortText

DecisionStatus = Literal["GO", "HOLD", "NO_GO", "UNREVIEWED"]


class GateSnapshot(BaseModel):
    """결정 시점의 Critical Condition 게이트 상태 (나중에 왜 그랬는지 볼 수 있게)."""

    can_go: bool
    blocker_count: int = Field(ge=0)
    reason: str


class BidDecision(BaseModel):
    procurement_id: str
    status: DecisionStatus = "UNREVIEWED"
    reasons: list[str] = Field(default_factory=list)
    decided_by: str | None = Field(default=None, max_length=60)
    # 이 요청을 보낸 **인증된 계정** (S12). 위 이름은 본문에 실려 온 «주장»이고, 이것은
    # 서명된 신원에서 온 사실이다. 둘은 다를 수 있다 — 담당자가 동료 이름을 적어 두는 일이
    # 실제로 있다. 인증이 꺼진 로컬에서는 None 이다(없는 것을 이름으로 채우지 않는다).
    recorded_by: str | None = Field(default=None, max_length=64)
    decided_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)
    gate: GateSnapshot | None = None
    schema_version: int = 2
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False


class DecisionRequest(BaseModel):
    status: Literal["GO", "HOLD", "NO_GO", "UNREVIEWED"]
    reasons: list[ShortText] = Field(default_factory=list, max_length=20)
    decided_by: PersonName
    note: str | None = Field(default=None, max_length=2000)
    #: 화면이 결정을 처음 읽은 때의 `decided_at`(44차 M4) — 그사이 남이 저장했으면 409. 보내지 않으면 검사 안 함.
    expected_decided_at: datetime | None = None
