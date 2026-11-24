"""활동 기록 조회 API (계약서 6장).

- GET /api/audit-log?limit=   최근 쓰기 요청 기록 (최신순, 기본 50 · 최대 200)

**관리자 전용이다.** 그 판정은 여기가 아니라 `core/auth.py` 미들웨어가 한다
(계약서 5장 — `/api/audit-log` 는 메서드와 무관하게 admin). 라우트에서 한 번 더 막지 않는 이유:
권한 판정이 두 곳에 흩어지면 둘이 어긋났을 때 어느 쪽이 맞는지 알 수 없게 된다.

응답 모델을 `schemas/` 가 아니라 여기 둔 것은 이 화면 하나만 쓰기 때문이다.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, ValidationError

from app.services import audit_log_service, user_service

router = APIRouter(prefix="/api/audit-log", tags=["audit-log"])


class AuditLogEntry(BaseModel):
    """기록 한 줄. 예전에 쓴 줄에 없는 항목이 있어도 화면이 죽지 않도록 전부 기본값을 둔다."""

    ts: str = ""
    user: str = ""
    role: str = ""
    method: str = ""
    path: str = ""
    organization_id: str | None = None
    status: int | None = None
    #: 서비스가 남긴 사건 요약(20차 — 조항 확인 · 재수집). 미들웨어 줄에는 없다.
    event: dict[str, str | int | None] | None = None
    #: 그 계정의 표시 이름(44차 S4 — 활동 표가 아이디만 보였다). 계정 파일에 없으면(지운 · 로컬 · 토큰) None.
    display_name: str | None = None


class AuditLogResponse(BaseModel):
    entries: list[AuditLogEntry] = Field(default_factory=list)
    count: int = 0
    # 요청한 줄 수. 실제로 돌려준 수(`count`)와 다를 수 있다(기록이 그보다 적을 때).
    limit: int = audit_log_service.DEFAULT_LIMIT


@router.get("", response_model=AuditLogResponse)
def read_audit_log(
    limit: int = Query(default=audit_log_service.DEFAULT_LIMIT, ge=1, le=audit_log_service.MAX_LIMIT),
) -> AuditLogResponse:
    """최근 활동. 기록 파일이 없으면 빈 목록을 돌려준다(오류가 아니다)."""
    try:
        names = {record.user: record.display_name for record in user_service.load_users()}
    except user_service.UserStoreError:
        names = {}  # 계정 파일을 못 읽어도 활동 표는 아이디로 보인다
    entries: list[AuditLogEntry] = []
    for row in audit_log_service.read_recent(limit):
        try:
            entry = AuditLogEntry.model_validate(row)
        except ValidationError:
            # 사람이 손으로 고친 줄 하나 때문에 「최근 활동」 전체가 500 이 되지 않게 버린다.
            continue
        entry.display_name = names.get(entry.user)
        entries.append(entry)
    return AuditLogResponse(entries=entries, count=len(entries), limit=limit)
