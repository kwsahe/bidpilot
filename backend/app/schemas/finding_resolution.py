"""Auditor 발견 항목의 담당자 해결 처리(Finding Resolution) 스키마.

원칙 (CLAUDE.md 4-I, 11, 25)
- AI Auditor는 문제를 **찾는** 쪽이고, 그것이 해결됐는지는 **사람이** 정한다.
  해결 처리는 항상 `method="HUMAN"`이며 누가·언제·무슨 근거(메모)로 했는지 남긴다.
- 발견 항목 id(`AF-001`)는 검사마다 새로 매겨지므로 저장 키로 쓰지 않는다.
  같은 문제를 가리키는 **안정 키**(`finding_type` + 요구사항/증빙/문장 fingerprint)를 쓴다.
- 해결 처리가 있어도 Auditor 재검사 결과를 지우거나 바꾸지 않는다. 화면은 "탐지됨 + 담당자 해결 처리"를
  같이 보여준다 — 초안을 실제로 고쳤다면 재검사에서 항목이 사라지는 것이 확인이다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.audit import FindingType

ResolutionStatus = Literal["open", "resolved"]

# 저장 키 형태: "<finding_type>:<scope>:<id>" (예: missing_requirement:req:REQ-015)
KEY_PATTERN = r"^[a-z_]+:(req|ev|text|draft):[A-Za-z0-9_.\-]{1,80}$"


class FindingResolution(BaseModel):
    """발견 항목 1건에 대한 담당자 처리 상태."""

    procurement_id: str = Field(min_length=1, max_length=64)
    key: str = Field(pattern=KEY_PATTERN)
    status: ResolutionStatus
    finding_type: FindingType
    requirement_id: str | None = Field(default=None, max_length=64)
    # 처리 당시 화면에 보이던 발견 항목 id·검사 실행 id (재검사하면 바뀔 수 있어 참고용이다).
    finding_id: str | None = Field(default=None, max_length=64)
    audit_run_id: str | None = Field(default=None, max_length=64)
    reviewer: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=2000)
    # 이 요청을 보낸 **인증된 계정** (S12). 위 이름은 본문에 실려 온 «주장»이고, 이것은
    # 서명된 신원에서 온 사실이다. 둘은 다를 수 있다 — 담당자가 동료 이름을 적어 두는 일이
    # 실제로 있다. 인증이 꺼진 로컬에서는 None 이다(없는 것을 이름으로 채우지 않는다).
    recorded_by: str | None = Field(default=None, max_length=64)
    method: Literal["HUMAN"] = "HUMAN"
    decided_at: datetime


class FindingResolutionRequest(BaseModel):
    """해결/재오픈 저장 요청. decided_at은 서버가 찍는다."""

    key: str = Field(pattern=KEY_PATTERN)
    status: ResolutionStatus
    finding_type: FindingType
    requirement_id: str | None = Field(default=None, max_length=64)
    finding_id: str | None = Field(default=None, max_length=64)
    audit_run_id: str | None = Field(default=None, max_length=64)
    reviewer: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=2000)


class FindingResolutionList(BaseModel):
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False
    procurement_id: str
    resolutions: list[FindingResolution] = Field(default_factory=list)
