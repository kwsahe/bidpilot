"""임베딩 가용성 «탐침»은 한 번에 하나만 돈다 (ISSUE-068).

## 왜

`embedding_available()` 은 절대 기다리지 않는다 — 캐시된 판정만 읽고, 아직 재지 않았으면
백그라운드 측정을 띄운 뒤 그 자리에서 `False` 를 돌려준다. 여기까지는 맞다.

문제는 **첫 측정이 끝나기 전까지 계속 「아직 재지 않았다」**라는 것이다. 기동 직후 첫 목록
계산은 공고 수백 건에 대해 의미 매칭을 부르고, 그 하나하나가 「아직 안 쟀네」를 보고
측정 스레드를 새로 띄운다. 공고 600건이면 스레드 600개와 OpenAI 임베딩 요청 600건이다.
크레딧이 있으면 그만큼 과금되고, 없으면 429 가 그만큼 쏟아진 뒤 SDK 가 재시도까지 한다.

그래서 진행 중 플래그로 **하나만** 띄운다. 나머지는 조용히 돌아가고, 곧 끝날 그 하나가
결과를 채운다. 돌아가는 쪽은 손해가 없다 — 어차피 지금 값을 쓰기로 되어 있었다.
"""

from __future__ import annotations

import threading

import pytest

from app.services import llm_client

#: conftest 의 autouse 픽스처가 `embedding_available`·`embed` 를 «못 쓴다»로 바꿔 둔다.
#: 여기서 재려는 것이 바로 그 함수들이므로 진짜를 되돌려 놓는다.
_REAL_EMBEDDING_AVAILABLE = llm_client.embedding_available


@pytest.fixture
def real_probe(monkeypatch: pytest.MonkeyPatch, embedding_live_on: None) -> None:
    """탐침을 재려면 **스위치를 켜야 한다** (15차 · ISSUE-129).

    15차부터 임베딩도 기본이 꺼짐이다 — 꺼져 있으면 `start_embedding_probe()` 가 스레드조차
    만들지 않는다. 그것은 여기서 재려는 것과 다른 동작이므로(그쪽은
    `test_embedding_switch.py` 가 잰다) 이 파일은 켜 놓고 「하나만 뜬다」를 잰다.
    """
    monkeypatch.setattr(llm_client, "embedding_available", _REAL_EMBEDDING_AVAILABLE)
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    # 「아직 한 번도 재지 않은」 상태로 되돌린다. monkeypatch 가 테스트 끝에 원래대로 돌린다.
    monkeypatch.setattr(llm_client, "_embedding_ok", None)
    monkeypatch.setattr(llm_client, "_embedding_checked_at", 0.0)
    monkeypatch.setattr(llm_client, "_probe_in_flight", False)
    # 실패 사유도 되돌린다 — 앞 테스트가 남긴 사유가 뒤 테스트의 화면 문구로 샌다.
    monkeypatch.setattr(llm_client, "_embedding_reason", None)


def _live_probe_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "embedding-probe" and t.is_alive()]


def test_공고_600건을_재도_탐침_스레드는_하나_임베딩_호출도_한_번(
    real_probe: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    held = threading.Event()
    release = threading.Event()

    def slow_embed(texts: list[str], **_kwargs: object) -> list[list[float]]:
        # 첫 탐침을 «진행 중» 상태로 붙잡아 둔다. 그 사이에 600번을 물어본다.
        calls.append(texts)
        held.set()
        release.wait(5.0)
        return [[1.0, 0.0]]

    monkeypatch.setattr(llm_client, "embed", slow_embed)

    assert llm_client.embedding_available() is False
    assert held.wait(5.0), "첫 탐침이 시작되지 않았습니다"

    for _ in range(600):
        # 아직 결론이 없으므로 전부 False. 중요한 것은 이 600번이 스레드를 만들지 않는 것이다.
        assert llm_client.embedding_available() is False

    assert len(_live_probe_threads()) == 1, "탐침 스레드가 하나보다 많습니다"
    assert len(calls) == 1, f"임베딩을 {len(calls)}번 불렀습니다 — 한 번이어야 합니다"

    release.set()
    for thread in _live_probe_threads():
        thread.join(5.0)


def test_탐침이_끝나면_다시_잴_수_있다(real_probe: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """진행 중 플래그를 내리지 않으면 **다시는** 재지 못한다 — 그쪽이 더 나쁜 고장이다."""
    calls: list[list[str]] = []

    def failing_embed(texts: list[str], **_kwargs: object) -> list[list[float]]:
        calls.append(texts)
        raise llm_client.LLMUnavailableError("크레딧 없음")

    monkeypatch.setattr(llm_client, "embed", failing_embed)

    llm_client.start_embedding_probe()
    for thread in _live_probe_threads():
        thread.join(5.0)
    assert len(calls) == 1

    # 실패한 뒤에도 플래그가 내려가 있어야 다음 탐침이 뜬다.
    assert llm_client._probe_in_flight is False
    llm_client.start_embedding_probe()
    for thread in _live_probe_threads():
        thread.join(5.0)
    assert len(calls) == 2


def test_탐침은_재시도를_켜지_않는다(real_probe: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """5초 제한이 SDK 재시도 대기에 다 쓰이면 「못 쓴다」 판정만 늦어진다."""
    seen: list[dict] = []

    def record(texts: list[str], **kwargs: object) -> list[list[float]]:
        seen.append(dict(kwargs))
        return [[1.0]]

    monkeypatch.setattr(llm_client, "embed", record)

    assert llm_client.refresh_embedding_availability() is True
    assert seen == [{"timeout": llm_client.EMBEDDING_PROBE_TIMEOUT, "max_retries": 0}]
