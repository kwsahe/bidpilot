"""시계를 앞당겨 돌리는 pytest 플러그인 (ISSUE-118 · prompt_03 §4-C).

## 왜 필요한가

`test_daily_digest.py` 가 어제는 통과하고 오늘은 실패했다. 코드가 바뀌어서가 아니라
**날짜가 지나서**다 — 고정 시각 `NOW` 로 캐시를 심고 서비스는 실제 시계로 신선도를
쟀기 때문에, `NOW + 15분` 을 넘긴 순간부터 「캐시가 오래됐다」가 됐다.

그런 테스트는 **오늘 초록이어도 믿을 수 없다.** 내일 빨개질 것을 오늘 알아야 한다.
그래서 시계를 앞당긴 채로 한 번 더 돌린다 — 오늘 돌려서 내일을 보는 것이다.

## 쓰기

**`backend` 폴더에서** 돌린다 (18차 §4-C):

    cd backend
    .venv/Scripts/python.exe -m pytest -q -p tests.timeshift_plugin --timeshift-days 1

저장소 루트에서 `pytest backend -p tests.timeshift_plugin` 으로 돌리면
`No module named 'tests'` 다 — `-p` 플러그인은 conftest 보다 먼저 읽혀서, 루트에서는
`tests` 를 찾을 경로가 아직 없다. 루트에서 `pytest backend` 로만 돌려도 1건이 skip 된다
(`test_document_extractor` 가 `../data/public/real_rfp` 를 상대 경로로 찾는다).

`--timeshift-days` 를 주지 않으면 아무것도 하지 않는다(평소 실행에 영향 없음).

## 무엇을 앞당기나

**`storage.utc_now()` 하나만.** 17차부터 앱이 판정에 쓰는 「지금」은 전부 그 함수를
지난다(ISSUE-133) — `procurement_service._now()` · `storage.kst_today()` ·
목록의 기본 시계 · 상세의 `today` · 기업마당 캐시 신선도가 모두 그렇다.

예전에는 `procurement_service._now` 도 따로 앞당겼다. 지금 그러면 그 함수가
`storage.utc_now()` 를 부르므로 **두 번 앞당겨진다** — 하루를 물으면 이틀이 온다.

`datetime.now` 자체를 통째로 바꾸지 않는 이유: 그러면 pytest·httpx·로깅까지 함께
움직여 무엇이 깨졌는지 가려낼 수 없다. 재려는 것은 「앱이 스스로 읽는 지금」이다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--timeshift-days",
        action="store",
        type=int,
        default=0,
        help="앱이 읽는 「지금」을 이만큼 앞당긴다 (ISSUE-118 확인용). 0 이면 아무것도 하지 않는다.",
    )


@pytest.fixture(autouse=True)
def _timeshift(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    days = request.config.getoption("--timeshift-days")
    if not days:
        return

    from app.core import storage

    offset = timedelta(days=days)
    real_utc_now = storage.utc_now

    monkeypatch.setattr(storage, "utc_now", lambda: real_utc_now() + offset)
