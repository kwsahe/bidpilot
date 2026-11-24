"""같은 일을 동시에 두 번 돌리지 않는 문 (27차 R26-05 · R26-12).

사업계획서 초안 · 제안서 · 제출 전 점검은 한 번에 몇 분이 걸리고 AI 를 부를 수 있다. 같은 회사가 같은 공고로
두 번 누르면(쉬운 보기 한 줄 단추 + 패널 단추 · 두 탭) AI 를 두 번 부르고, 늦게 끝난 쪽이 판 번호를 덮어썼다.
처음 것이 끝날 때까지 두 번째는 `InFlightError` — 화면은 「이미 만드는 중입니다」를 보인다.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

# ponytail: 한 프로세스 안의 문이다 — uvicorn 작업자를 여럿 띄우면 파일 잠금으로 바꾼다.
_RUNNING: set[tuple[str, ...]] = set()
_GUARD = threading.Lock()

BUSY_MESSAGE = "이미 만드는 중입니다 — 끝날 때까지 기다린 뒤 다시 누르세요"


class InFlightError(RuntimeError):
    """같은 일이 이미 돌고 있다."""


#: 사업계획서 작성(Claude)은 서버에 한 번에 한 건 — 다른 공고를 만드는 중이면 (28차 §3-D)
# ponytail: 전역 한 건 — 사용자가 늘면 회사별
PLAN_WRITER_BUSY = "다른 공고의 초안을 Claude 로 만드는 중입니다 — 끝난 뒤(최대 5분) 다시 누르세요"


def _name(kind: str, key: tuple[str | None, ...]) -> tuple[str, ...]:
    return (kind, *(str(k or "") for k in key))


def running(kind: str, *key: str | None) -> bool:
    """(`kind`, key…) 가 지금 돌고 있는가 — 새로고침한 화면이 「만드는 중」을 읽는다 (28차 §3-D)."""
    with _GUARD:
        return _name(kind, key) in _RUNNING


@contextmanager
def hold(kind: str, *key: str | None, message: str = BUSY_MESSAGE) -> Iterator[None]:
    """(`kind`, key…) 로 한 번에 하나만. 이미 돌고 있으면 기다리지 않고 `InFlightError`."""
    name = _name(kind, key)
    with _GUARD:
        if name in _RUNNING:
            raise InFlightError(message)
        _RUNNING.add(name)
    try:
        yield
    finally:
        with _GUARD:
            _RUNNING.discard(name)
