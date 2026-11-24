"""실호출은 **기본이 꺼짐**이다 (ISSUE-120 · prompt_03 §4-A).

## 왜 이 파일이 있나

같은 사고가 세 번 났다.

- 11차: 진단 스크립트를 환경변수 없이 돌려 기업마당 목록이 다시 받아졌다. 캐시가
  1,605건에서 1,578건으로 줄었고 **기준 답안 두 건이 영구히 사라졌다**(gitignore 아래라
  되돌릴 수 없었다).
- 12차: 떠 있던 `start_dev.bat` 이 TTL 이 지나자 나라장터를 불러 git 이 추적하는
  공고 캐시를 덮었다.
- 13차: 또 진단 스크립트. 100건짜리 응답이 1,620건 캐시를 말없이 덮었다.

프롬프트 §2 에 세 번 적었고 세 번 옮겨 적었지만 세 번 다 어겼다. **규칙으로 막을 일이
아니었다** — 환경변수를 세우지 않으면 앱이 바깥을 부르는 **기본값**이 틀린 것이었다.
실수로 부르는 쪽이 아니라 실수로 안 부르는 쪽이 안전하다.

## 무엇을 재는가

1. 환경변수가 없으면 두 스위치가 **꺼져 있다**.
2. 앱을 import 하고 목록을 불러도 **네트워크 함수가 호출되지 않는다** — 규칙이 아니라
   실제로 부르는지로 잰다. 이 단언이 세 번의 사고를 잡았을 자리다.
3. 켜는 것은 **명시적 환경변수**뿐이다.

2번을 「호출되면 예외」로 재는 이유: 「캐시를 읽었다」만 보면 캐시가 신선할 때도 통과한다.
사고는 전부 **캐시가 오래됐을 때** 났다. 그래서 TTL 을 지난 것으로 만들어 두고,
그래도 부르지 않는지를 본다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.services import bizinfo_client, bizinfo_service, g2b_client, procurement_service


class LiveCallAttempted(AssertionError):
    """앱이 바깥을 불렀다. 이 예외가 뜨면 ISSUE-120 이 되살아난 것이다."""


#: 바깥으로 나가는 문 전부. 하나라도 빠지면 그 문으로 새 사고가 난다.
G2B_DOORS: tuple[str, ...] = (
    "fetch_bid_notices_raw",
    "search_bid_notices",
    "fetch_qualification_page",
    "fetch_qualifications_for_day",
    "collect_notices",
    "fetch_bid_notices",
)
BIZINFO_DOORS: tuple[str, ...] = ("fetch_programs_raw", "download_announcement")


@pytest.fixture()
def doors_explode(monkeypatch: pytest.MonkeyPatch) -> None:
    """모든 바깥 문을 「열면 터지는 것」으로 바꾼다."""

    async def _explode(*_args: object, **_kwargs: object) -> object:
        raise LiveCallAttempted("앱이 바깥을 불렀습니다")

    for name in G2B_DOORS:
        monkeypatch.setattr(g2b_client, name, _explode, raising=False)
    for name in BIZINFO_DOORS:
        monkeypatch.setattr(bizinfo_client, name, _explode, raising=False)


# --------------------------------------------------------------------------
# 1. 환경변수가 없으면 꺼짐
# --------------------------------------------------------------------------


def test_환경변수가_없으면_두_스위치가_꺼져_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    """**설정 기본값** 자체를 잰다 — 인스턴스가 아니라 모델의 기본값이다.

    `conftest.py` 의 `no_live_fetch_env` 가 테스트마다 이 값으로 되돌리므로, 여기가
    무너지면 저장소 전체의 테스트가 조용히 「켜짐」으로 돈다.
    """
    assert Settings.model_fields["g2b_live_fetch"].default is False
    assert Settings.model_fields["bizinfo_live_fetch"].default is False

    monkeypatch.delenv("G2B_LIVE_FETCH", raising=False)
    monkeypatch.delenv("BIZINFO_LIVE_FETCH", raising=False)
    get_settings.cache_clear()
    try:
        fresh = get_settings()
        assert fresh.g2b_live_fetch is False
        assert fresh.bizinfo_live_fetch is False
    finally:
        get_settings.cache_clear()


def test_켜는_것은_명시적_환경변수뿐이다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("G2B_LIVE_FETCH", "1")
    monkeypatch.setenv("BIZINFO_LIVE_FETCH", "1")
    get_settings.cache_clear()
    try:
        fresh = get_settings()
        assert fresh.g2b_live_fetch is True
        assert fresh.bizinfo_live_fetch is True
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------
# 2. 앱을 import 하고 목록을 불러도 바깥을 부르지 않는다
# --------------------------------------------------------------------------


def _stale_cache(path: Path) -> None:
    """**TTL 을 지난** 캐시를 심는다. 사고는 전부 캐시가 오래됐을 때 났다."""
    old = datetime.now(timezone.utc) - timedelta(seconds=procurement_service.CACHE_TTL_SECONDS * 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": old.isoformat(),
                "collected_by": "테스트",
                "collect_calls": 0,
                "days": 30,
                "total_fetched": 0,
                "notices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_기본값이면_나라장터_목록이_바깥을_부르지_않는다(
    doors_explode: None, notice_cache_file: Path
) -> None:
    """환경변수를 세우지 않은 상태 — `conftest` 가 기본값(꺼짐)으로 둔다."""
    _stale_cache(notice_cache_file)
    procurement_service.clear_memo()

    result = await procurement_service.list_ai_candidates(days=30, refresh=True)

    # 부르지 않았다는 것이 먼저다. 그 다음에 「그래서 캐시를 읽었다」를 본다.
    assert result.source in {"cached", "sample", "empty"}, result.source


@pytest.mark.anyio
async def test_기본값이면_기업마당_목록이_바깥을_부르지_않는다(doors_explode: None) -> None:
    await bizinfo_service.list_programs(organization_id="org-sample")


@pytest.mark.anyio
async def test_켜면_비로소_부른다(
    doors_explode: None, notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**꺼져 있어서 안 부른 것**인지, 원래 못 부르는 것인지 가른다.

    이 단언이 없으면 위의 둘은 「어차피 안 부르는 코드」여도 통과한다 —
    검사가 조용히 통과하는 자리가 된다.
    """
    _stale_cache(notice_cache_file)
    procurement_service.clear_memo()
    monkeypatch.setattr(get_settings(), "g2b_live_fetch", True)

    with pytest.raises(LiveCallAttempted):
        await procurement_service.list_ai_candidates(days=30, refresh=True)
