"""데이터 저장 위치 한 곳에서 정한다.

로컬에서는 저장소 안의 `data/` 를 그대로 쓰지만, 컨테이너로 호스팅하면 `data/` 는
재시작해도 남아야 하는 **영구 볼륨**이라 경로를 밖에서 정할 수 있어야 한다.
그래서 각 모듈이 `Path(__file__).parents[3] / "data"` 를 따로 계산하지 않고
여기서 `DATA_ROOT` 를 가져다 쓴다.

- `DATA_DIR` 환경변수가 있으면 그 경로가 데이터 루트다 (예: 볼륨 마운트 지점 `/data`).
- 없으면 지금까지와 동일하게 저장소 루트의 `data/` 다.

환경변수는 **import 시점에 한 번만** 읽는다. 각 모듈의 경로 상수(`CACHE_FILE`,
`ORGANIZATIONS_DIR` 등)도 import 시점에 값이 정해지므로, 테스트는 지금처럼
그 모듈 상수를 monkeypatch 한다 (`monkeypatch.setattr(mod, "CACHE_FILE", tmp)`).
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/app/core/paths.py → parents[3] 가 저장소 루트다.
REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_data_root() -> Path:
    """`DATA_DIR` 환경변수가 있으면 그 경로, 없으면 저장소의 `data/`."""
    raw = os.environ.get("DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return REPO_ROOT / "data"


DATA_ROOT = _resolve_data_root()
