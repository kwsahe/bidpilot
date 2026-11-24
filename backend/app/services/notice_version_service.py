"""공고 변경 감지 — 조회할 때마다 핵심 필드 스냅샷을 남기고 달라지면 새 버전을 만든다.

저장: data/public/notice_versions/<id>.versions.json
- 같은 값이면 버전을 늘리지 않는다 (조회 횟수와 무관).
- 비교 필드: 공고명·발주기관·마감·예산·지역·첨부 목록·입찰마감(bidClseDt)·개찰(opengDt)·공고 차수.
- 변경 내역(diff)은 연속한 두 버전의 필드 차이다.

이 기록은 procurement_service.save_cache에서 자동으로 쌓인다. 실패해도 목록 조회를 막지 않는다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.procurement import ProcurementNotice

logger = logging.getLogger(__name__)

VERSION_DIR = DATA_ROOT / "public" / "notice_versions"

TRACKED_FIELDS: tuple[str, ...] = (
    "title",
    "agency",
    "deadline_at",
    "budget",
    "region",
    "attachments",
    "bidClseDt",
    "opengDt",
    "bidNtceOrd",
    "ntceKindNm",
)

FIELD_LABEL: dict[str, str] = {
    "title": "공고명",
    "agency": "발주기관",
    "deadline_at": "마감일",
    "budget": "예산",
    "region": "지역",
    "attachments": "첨부파일",
    "bidClseDt": "입찰 마감(원문)",
    "opengDt": "개찰 일시(원문)",
    "bidNtceOrd": "공고 차수",
    "ntceKindNm": "공고 종류",
}


class NoticeVersion(BaseModel):
    version: int = Field(ge=1)
    observed_at: datetime
    fields: dict[str, Any]


class NoticeChange(BaseModel):
    field: str
    label: str
    before: Any
    after: Any


class NoticeChangeSet(BaseModel):
    from_version: int
    to_version: int
    observed_at: datetime
    changes: list[NoticeChange]


class NoticeVersionHistory(BaseModel):
    procurement_id: str
    versions: list[NoticeVersion]
    changes: list[NoticeChangeSet]
    schema_version: int = 2


def snapshot_fields(notice: ProcurementNotice) -> dict[str, Any]:
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    item = raw.get("item") if isinstance(raw.get("item"), dict) else raw
    attachments = raw.get("attachments") if isinstance(raw.get("attachments"), list) else []
    return {
        "title": notice.title,
        "agency": notice.agency,
        "deadline_at": notice.deadline_at.isoformat() if notice.deadline_at else None,
        "budget": notice.budget,
        "region": notice.region,
        "attachments": [f"{a.get('name')}" for a in attachments if isinstance(a, dict)],
        "bidClseDt": item.get("bidClseDt"),
        "opengDt": item.get("opengDt"),
        "bidNtceOrd": item.get("bidNtceOrd"),
        "ntceKindNm": item.get("ntceKindNm"),
    }


#: 「공고 변경」으로 적는 필드와 짧은 이름 (38차 §3-C-5). **지역 변경은 잡음이라 뺀다** — 판단기준 이름(「본사또는참여지사소재지」)과
#: 지역 이름이 번갈아 와서 바뀐 것이 없는데도 변경으로 잡혔다.
NOTABLE_LABELS: dict[str, str] = {"deadline_at": "마감", "bidClseDt": "마감", "attachments": "첨부", "bidNtceOrd": "차수", "ntceKindNm": "종류"}


def notable_changes_since(procurement_id: str, since: datetime | None) -> list[str]:
    """`since` 뒤로 바뀐 마감 · 첨부 · 차수 · 종류(짧은 이름 · 중복 없음). 없거나 못 읽으면 빈 목록. **파일 읽기뿐이다.**"""
    try:
        history = load_history(procurement_id)
    except (storage.CorruptJsonError, storage.InvalidIdError, OSError, ValueError):
        return []
    labels: list[str] = []
    for change_set in history.changes:
        moment = change_set.observed_at if change_set.observed_at.tzinfo else change_set.observed_at.replace(tzinfo=timezone.utc)
        if since is not None and moment <= since:
            continue
        for change in change_set.changes:
            label = NOTABLE_LABELS.get(change.field)
            if label and label not in labels:
                labels.append(label)
    return labels


def history_path(procurement_id: str) -> Path:
    return VERSION_DIR / f"{storage.safe_id(procurement_id, what='공고 id')}.versions.json"


def load_history(procurement_id: str) -> NoticeVersionHistory:
    payload = storage.read_json(history_path(procurement_id), default=None)
    if not isinstance(payload, dict):
        return NoticeVersionHistory(procurement_id=procurement_id, versions=[], changes=[])
    return NoticeVersionHistory.model_validate(payload)


def latest_title(procurement_id: str) -> str | None:
    """받아 둔 기록의 마지막 제목(45차 M15 · M20 — 목록에서 내려간 공고가 개발용 번호 · 「나라장터 입찰」로 보였다). 없으면 None."""
    try:
        versions = load_history(procurement_id).versions
    except Exception:  # noqa: BLE001 — 기록이 없거나 깨졌으면 모른다
        return None
    title = versions[-1].fields.get("title") if versions else None
    return title.strip() if isinstance(title, str) and title.strip() else None


def _mapping_only(field: str, before: dict[str, Any], after: dict[str, Any]) -> bool:
    """공고가 아니라 **읽는 규칙**이 바뀐 것 — 43차 H1: 입찰 마감이 빈 공고의 `deadline_at` 이 개찰일시에서 None 으로(원본 `bidClseDt` 그대로)."""
    return (
        field == "deadline_at"
        and after.get("deadline_at") is None
        and bool(before.get("opengDt"))
        and not after.get("bidClseDt")
        and before.get("bidClseDt") == after.get("bidClseDt")
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[NoticeChange]:
    changes: list[NoticeChange] = []
    for field in TRACKED_FIELDS:
        if before.get(field) != after.get(field) and not _mapping_only(field, before, after):
            changes.append(NoticeChange(field=field, label=FIELD_LABEL.get(field, field), before=before.get(field), after=after.get(field)))
    return changes


def record(notice: ProcurementNotice, *, observed_at: datetime | None = None) -> NoticeVersionHistory:
    """스냅샷을 비교해 달라졌을 때만 새 버전을 추가한다."""
    history = load_history(notice.id)
    fields = snapshot_fields(notice)
    moment = observed_at or storage.utc_now()
    if history.versions and history.versions[-1].fields == fields:
        return history
    if history.versions and not diff(history.versions[-1].fields, fields):
        return history  # 읽는 규칙만 바뀌었다(43차 H1) — 공고 변경으로 세지 않는다
    version = len(history.versions) + 1
    if history.versions:
        changes = diff(history.versions[-1].fields, fields)
        history.changes.append(NoticeChangeSet(from_version=version - 1, to_version=version, observed_at=moment, changes=changes))
    history.versions.append(NoticeVersion(version=version, observed_at=moment, fields=fields))
    payload = history.model_dump(mode="json")
    storage.stamp(payload)
    storage.write_json_atomic(history_path(notice.id), payload)
    return history


def record_many(notices: list[ProcurementNotice], *, observed_at: datetime | None = None) -> int:
    """목록 캐시 저장 시 호출. 실패해도 목록 조회를 막지 않는다. 새 버전이 생긴 공고 수를 돌려준다."""
    created = 0
    for notice in notices:
        try:
            before = len(load_history(notice.id).versions)
            after = len(record(notice, observed_at=observed_at).versions)
            created += 1 if after > before else 0
        except (storage.CorruptJsonError, storage.InvalidIdError, OSError, ValueError) as exc:
            logger.warning("공고 버전 기록 실패 (%s): %s", notice.id, exc)
    return created
