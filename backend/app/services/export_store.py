"""내보낸 파일을 **회사 폴더에 남긴다** (0924.md §4-C-2).

## 왜 필요한가

담당자가 목록을 엑셀로 내려받아 메일로 보낸다. 그런데 「지난주에 보낸 표가 어떤 조건이었나」
를 나중에 알 수 없었다 — 파일은 내려받기 폴더 어딘가에 있고, 어떤 필터로 뽑았는지는 아무
데도 없다. 그래서 같은 워크북을 회사 폴더에 한 벌 남기고, **날짜·조건·건수**를 함께 적는다.

    data/private/organizations/<org>/exports/
        BidPilot_사업기회_샘플에듀_20260918.xlsx
        index.json      ← 언제 · 어떤 조건 · 몇 건

## 규율

- **비공개다.** `data/private/` 는 Git 이 추적하지 않는다.
- 같은 이름이면 덮어쓰지 않고 `_2` 를 붙인다 — 하루에 두 번 뽑은 두 조건이 다를 수 있다.
- 오래된 것부터 지운다(`MAX_FILES`). 내려받기 폴더를 대신하는 곳이 아니다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import storage
from app.core.paths import DATA_ROOT

logger = logging.getLogger(__name__)

#: 회사마다 몇 개까지 들고 있을까. 이력이지 보관소가 아니다.
MAX_FILES = 20

_SAFE_NAME = re.compile(r"^[0-9A-Za-z가-힣._-]{1,120}$")


def exports_dir(organization_id: str) -> Path:
    return DATA_ROOT / "private" / "organizations" / storage.safe_id(organization_id, what="조직 id") / "exports"


def index_path(organization_id: str) -> Path:
    return exports_dir(organization_id) / "index.json"


def load_index(organization_id: str) -> list[dict[str, Any]]:
    try:
        payload = storage.read_json(index_path(organization_id), default=None)
    except storage.CorruptJsonError:
        logger.warning("내보내기 이력 파일이 깨져 빈 목록으로 시작합니다")
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("files")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _unique(directory: Path, name: str) -> Path:
    """같은 이름이 있으면 `_2`, `_3` 을 붙인다. **덮어쓰지 않는다.**"""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = name.rsplit(".", 1) if "." in name else (name, "")
    for index in range(2, 100):
        alternative = directory / (f"{stem}_{index}.{suffix}" if suffix else f"{stem}_{index}")
        if not alternative.exists():
            return alternative
    return candidate


def save(
    organization_id: str,
    *,
    name: str,
    body: bytes,
    conditions: str,
    rows: int,
    sheets: list[str] | None = None,
) -> dict[str, Any]:
    """워크북을 남기고 이력 한 줄을 적는다. 실패해도 내려받기는 그대로 나간다."""
    if not _SAFE_NAME.match(name):
        raise ValueError(f"파일 이름 형식이 아닙니다: {name!r}")
    directory = exports_dir(organization_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = _unique(directory, name)
    path.write_bytes(body)

    entry = {
        "file": path.name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "conditions": conditions,
        "rows": rows,
        "bytes": len(body),
        "sheets": sheets or [],
    }
    rows_out = [entry, *load_index(organization_id)]
    # 오래된 것부터 지운다 — 파일도 함께.
    for old in rows_out[MAX_FILES:]:
        try:
            (directory / str(old.get("file"))).unlink(missing_ok=True)
        except OSError:
            logger.warning("옛 내보내기 파일을 지우지 못했습니다: %s", old.get("file"))
    rows_out = rows_out[:MAX_FILES]
    payload = {
        "_note": "내보낸 사업기회 파일 이력 (내부 전용, Git 제외).",
        "organization_id": organization_id,
        "files": rows_out,
    }
    storage.stamp(payload)
    storage.write_json_atomic(index_path(organization_id), payload)
    return entry


def read(organization_id: str, name: str) -> bytes | None:
    """저장해 둔 파일을 다시 읽는다. 목록에 없는 이름은 거부한다 (경로 탈출 방지)."""
    if not _SAFE_NAME.match(name):
        return None
    if not any(row.get("file") == name for row in load_index(organization_id)):
        return None
    path = exports_dir(organization_id) / name
    if not path.exists():
        return None
    return path.read_bytes()
