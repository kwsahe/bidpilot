"""시연 고정 모드 — 실호출을 «할 수 있는데 하지 않는다» (ISSUE-062).

## 왜 이 테스트가 있는가

공고 목록은 캐시가 15분(TTL) 지나면 나라장터를 다시 부르고, 받은 결과로 Git 이 추적하는
`data/public/sample_procurements/g2b_cache.json` 을 덮어쓴다. 평소에는 그게 맞다.
그런데 **시연 중에는** 그 한 번으로 「수집 107건」이 다른 숫자가 되고, 큐시트와 리허설
캡처가 통째로 어긋난다. 실제로 밤사이 그런 일이 세 번 일어났다.

그때의 임시방편은 «키를 비우고 서버를 띄우는» 것이었다. 그건 두 가지가 나쁘다 —
화면이 「키 없음」이라고 거짓을 말하고, 다음 사람이 정상 기동하면 곧바로 원상복구된다.
그래서 키는 그대로 두고 **부르지 않는다**는 사실을 플래그로 세우고 화면에 표시한다.

여기서 고정하는 것은 세 가지다.

1. 고정 모드에서는 `refresh=True` 를 줘도 나라장터 클라이언트를 **부르지 않는다**.
2. 응답이 그 사실을 말한다 (`source="cached"` · `frozen=True`, `/health` 의 `live_fetch_frozen`).
3. 캐시 파일이 **한 바이트도** 바뀌지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import bizinfo_service, g2b_client, procurement_service

client = TestClient(app)


class LiveCallAttempted(AssertionError):
    """고정 모드인데 실호출을 시도했다. 이 예외가 뜨면 고정이 새고 있는 것이다."""


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """두 출처 모두 고정. 실호출 경로에는 «부르면 터지는» 지뢰를 깔아 둔다."""
    settings = get_settings()
    monkeypatch.setattr(settings, "g2b_live_fetch", False)
    monkeypatch.setattr(settings, "bizinfo_live_fetch", False)

    async def _explode(**_kwargs: object) -> list[dict]:
        raise LiveCallAttempted("고정 모드에서 나라장터를 불렀습니다")

    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _explode)
    monkeypatch.setattr(g2b_client, "collect_notices", _explode)
    procurement_service.clear_memo()


def _seed_cache(cache_file: Path) -> None:
    """캐시 파일 한 개를 심는다. 공고 한 건이면 충분하다 — 세는 것은 «변경 여부»다."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "_note": "테스트용 캐시",
                "fetched_at": "2020-01-01T00:00:00+00:00",
                "days": 30,
                "total_fetched": 1,
                "notices": [
                    {
                        "notice": {
                            "id": "g2b-TEST-000",
                            "notice_no": "TEST-000",
                            "title": "생성형 AI 활용 실무교육 운영 용역",
                            "agency": "테스트기관",
                            "published_at": "2020-01-01T00:00:00+09:00",
                            "deadline_at": None,
                            "budget": None,
                            "region": None,
                            "description": None,
                            "source_url": None,
                            "raw_data": {},
                        },
                        "candidate": {},
                        "pinned": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_고정_모드는_refresh를_줘도_나라장터를_부르지_않는다(
    frozen: None, notice_cache_file: Path
) -> None:
    _seed_cache(notice_cache_file)

    # TTL 을 0 으로 줘서 «신선한 캐시» 경로마저 막아 둔다. 그래도 실호출로 가면 안 된다.
    result = asyncio.run(procurement_service.list_ai_candidates(refresh=True, ttl=0, include_low=True))

    assert result.source == "cached"
    # 캐시에 심은 공고가 그대로 나온다. 함께 있는 나머지는 시연용 고정 공고(pinned)로,
    # 캐시를 읽는 경로가 늘 붙이는 것이지 나라장터에서 받아온 것이 아니다.
    assert "g2b-TEST-000" in {v.notice.id for v in result.notices}
    assert all(v.pinned for v in result.notices if v.notice.id != "g2b-TEST-000")


def test_고정_모드에서_캐시_파일이_바뀌지_않는다(frozen: None, notice_cache_file: Path) -> None:
    _seed_cache(notice_cache_file)
    before = notice_cache_file.read_bytes()

    for _ in range(3):
        procurement_service.clear_memo()
        asyncio.run(procurement_service.list_ai_candidates(refresh=True, ttl=0, include_low=True))

    assert notice_cache_file.read_bytes() == before


def test_응답과_health가_고정_사실을_말한다(frozen: None, notice_cache_file: Path) -> None:
    _seed_cache(notice_cache_file)

    result = asyncio.run(procurement_service.list_ai_candidates(include_low=True))
    assert result.to_dict()["frozen"] is True

    assert client.get("/health").json()["live_fetch_frozen"] is True


def test_고정이_아니면_frozen은_False다(monkeypatch: pytest.MonkeyPatch, notice_cache_file: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "g2b_live_fetch", True)
    monkeypatch.setattr(settings, "bizinfo_live_fetch", True)
    procurement_service.clear_memo()
    _seed_cache(notice_cache_file)

    # 고정이 아니면 낡은 캐시(2020년)를 보고 실호출로 간다 — 그것이 평소 동작이다.
    # 여기서 재는 것은 표시값이므로, 실호출은 빈 응답으로 대신한다.
    async def _nothing(**_kwargs: object) -> list[dict]:
        return []

    async def _nothing_collected(**_kwargs: object) -> g2b_client.CollectOutcome:
        return g2b_client.CollectOutcome(
            items=[], calls=1, method="시험 수집", keyword_totals={}, truncated=()
        )

    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _nothing)
    monkeypatch.setattr(g2b_client, "collect_notices", _nothing_collected)

    result = asyncio.run(procurement_service.list_ai_candidates(include_low=True))
    assert result.to_dict()["frozen"] is False
    assert client.get("/health").json()["live_fetch_frozen"] is False


def test_고정_모드에_캐시가_없으면_조용히_비지_않고_사유를_말한다(
    frozen: None, notice_cache_file: Path
) -> None:
    # 캐시 파일을 심지 않는다. 빈 목록을 돌려주면 화면이 「공고가 없다」로 읽혀
    # 원인을 찾는 데 시간이 걸린다 — 시연 중에 가장 나쁜 실패 방식이다.
    assert not notice_cache_file.exists()
    with pytest.raises(procurement_service.NoNoticeDataError) as caught:
        asyncio.run(procurement_service.list_ai_candidates(include_low=True))
    # 기대값 바꿈(27차 §3-H): 화면 문장에 설정 이름을 적지 않는다 — 사유(시연 고정 · 캐시 없음)와 할 일은 그대로
    assert "새 공고 받기가 꺼져" in str(caught.value) and "G2B_LIVE_FETCH" not in str(caught.value)


def test_기업마당도_같은_규칙을_따른다(frozen: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(**_kwargs: object) -> dict:
        raise LiveCallAttempted("고정 모드에서 기업마당을 불렀습니다")

    monkeypatch.setattr(bizinfo_service.bizinfo_client, "fetch_programs_raw", _explode)
    monkeypatch.setattr(bizinfo_service.bizinfo_client, "is_configured", lambda: True)

    response = asyncio.run(bizinfo_service.list_programs(refresh=True))

    assert response.frozen is True
    # 캐시가 없는 환경이면 합성 샘플로 떨어진다. 어느 쪽이든 «실호출은 없었다»가 핵심이다.
    assert response.source in {"cached", "sample"}


# ---------------------------------------------------------------------------
# 33차 §3-A-2 · 3 — 고정 모드 메모는 파일이 바뀌면 다시 읽는다 · 살아 있는 저장본(Git 밖)과 기준본
# ---------------------------------------------------------------------------


def _titles(result: procurement_service.ProcurementResult) -> set[str]:
    return {v.notice.title for v in result.notices if not v.pinned}


def test_고정_모드도_저장본이_바뀌면_서버를_다시_띄우지_않고_새_목록(frozen: None, notice_cache_file: Path) -> None:
    """매일 아침 자동 받기가 파일을 바꾸면 다음 요청부터 새 목록 — 「오늘 달라진 것」 · 검토 대기열과 숫자가 갈리지 않게(절차서 C)."""
    import os

    _seed_cache(notice_cache_file)
    first = asyncio.run(procurement_service.list_ai_candidates(include_low=True))
    payload = json.loads(notice_cache_file.read_text(encoding="utf-8"))
    payload["notices"][0]["notice"]["title"] = "생성형 AI 실무교육 2차 운영 용역"
    notice_cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    stat = notice_cache_file.stat()
    os.utime(notice_cache_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))  # 같은 초 안에 쓰여도 시각이 달라지게
    second = asyncio.run(procurement_service.list_ai_candidates(include_low=True))
    assert _titles(first) == {"생성형 AI 활용 실무교육 운영 용역"}
    assert _titles(second) == {"생성형 AI 실무교육 2차 운영 용역"}


def test_살아_있는_저장본이_없으면_기준본을_읽고_쓰기는_살아_있는_쪽에만(notice_cache_file: Path) -> None:
    """기준본(Git 추적)은 장애 대비 예시 — 받기가 덮어쓰지 않는다(절차서 §3-4 안 1)."""
    baseline = procurement_service.BASELINE_CACHE_FILE
    _seed_cache(baseline)
    assert not notice_cache_file.exists()
    assert procurement_service.cache_read_path() == baseline
    cached = procurement_service.load_cache()
    assert cached is not None and {v.notice.id for v in cached.notices} == {"g2b-TEST-000"}
    before = baseline.read_bytes()
    reason = procurement_service.save_cache(cached.notices, 1, cached.fetched_at, days=30)
    assert reason is None and notice_cache_file.exists()
    assert baseline.read_bytes() == before
    assert procurement_service.cache_read_path() == notice_cache_file
