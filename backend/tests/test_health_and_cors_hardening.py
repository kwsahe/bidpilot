"""`/health` 는 기다리지 않고, 500 응답은 아무 Origin 에나 문을 열지 않는다 (ISSUE-048·050).

## 무엇을 막는가

**ISSUE-048** — `embedding_available()` 이 프로세스당 첫 호출에서 실제 임베딩 요청을
`async` 핸들러 안에서 **동기로** 보냈다. 키가 거부되면 빨리 끝나지만, 외부망이 막힌
서버(사내망·방화벽)에서는 SDK 기본 타임아웃(60초)과 재시도 때문에 첫 `/health` 와 첫
`/api/organizations` 가 수십 초 동안 이벤트 루프를 잡는다. nginx·컨테이너 HEALTHCHECK 가
`/health` 를 치므로 기동 직후 죽은 것으로 판정될 수 있다.

**ISSUE-050** — 전역 500 핸들러가 요청 Origin 을 허용 목록과 대조하지 않고 그대로
반사하면서 `Allow-Credentials: true` 까지 붙였다. 본문이 일반 문장이라 실해는 작지만
CORS 정책과 어긋난다.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_client


#: conftest 의 autouse 픽스처가 테스트 중 `embedding_available` 을 «키 존재 확인»으로 바꿔 둔다
#: (다른 테스트가 바깥으로 나가지 않게 하려고). 여기서는 그 함수 «자체»를 재므로 진짜 구현을 쓴다.
_REAL_EMBEDDING_AVAILABLE = llm_client.embedding_available


@pytest.fixture()
def real_probe(monkeypatch: pytest.MonkeyPatch, embedding_live_on: None) -> None:
    """진짜 함수 + **스위치 켜짐** (15차 · ISSUE-129).

    스위치를 켜지 않으면 `embedding_available()` 이 재지도 않고 False 를 답한다 — 아래
    「느려도 즉시 답한다」가 «측정을 안 해서» 통과하게 된다. 재려는 것을 실제로 재려면
    켜 두어야 한다. 꺼짐의 동작은 `test_embedding_switch.py` 가 잰다.
    """
    monkeypatch.setattr(llm_client, "embedding_available", _REAL_EMBEDDING_AVAILABLE)


@pytest.fixture()
def api() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# /health 는 절대 기다리지 않는다
# ---------------------------------------------------------------------------


def test_health는_임베딩이_느려도_즉시_답한다(real_probe, api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """임베딩을 5초 sleep 으로 바꿔 두고도 `/health` 가 곧바로 와야 한다."""

    def slow_embed(*_args, **_kwargs):
        time.sleep(5)
        return [[0.0]]

    monkeypatch.setattr(llm_client, "embed", slow_embed)
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    # 아직 재지 않은 상태로 되돌린다 — 최악의 경우를 만든다.
    monkeypatch.setattr(llm_client, "_embedding_ok", None, raising=False)
    monkeypatch.setattr(llm_client, "_embedding_checked_at", 0.0, raising=False)

    start = time.perf_counter()
    response = api.get("/health")
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed < 1.0, f"/health 가 {elapsed:.1f}초 걸렸다 — 측정을 기다리고 있다"
    # 아직 모르면 「사용 가능」이라고 답하지 않는다.
    assert response.json()["embedding_available"] is False


def test_측정은_타임아웃이_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    """외부망이 막혀 응답이 없어도 5초 안에 «사용 불가»로 결론 낸다."""
    monkeypatch.setattr(llm_client, "EMBEDDING_PROBE_TIMEOUT", 0.2)
    monkeypatch.setattr(llm_client, "embed", lambda *_a, **_k: time.sleep(5))

    start = time.perf_counter()
    assert llm_client._measure_embedding() is False
    assert time.perf_counter() - start < 2.0


def test_성공을_알리면_측정_없이_갱신된다(real_probe, monkeypatch: pytest.MonkeyPatch) -> None:
    """검색·색인이 실제로 성공했다면 다시 잴 이유가 없다."""
    calls: list[int] = []
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "embed", lambda *_a, **_k: calls.append(1) or [[0.0]])
    monkeypatch.setattr(llm_client, "_embedding_ok", False, raising=False)

    llm_client.note_embedding_success()
    assert llm_client.embedding_available() is True
    assert calls == [], "성공을 알렸는데도 바깥에 다시 물었다"


# ---------------------------------------------------------------------------
# 500 응답의 CORS
# ---------------------------------------------------------------------------


def _with_probe_route():
    path = "/__test_cors_boom__"

    @app.get(path)
    async def boom():  # pragma: no cover - 예외를 내기 위한 경로
        raise RuntimeError("의도적 실패")

    return path


def _drop_route(path: str) -> None:
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != path]


def test_허용된_Origin에는_CORS_헤더가_붙는다() -> None:
    path = _with_probe_route()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(path, headers={"Origin": "http://localhost:3110"})
        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3110"
    finally:
        _drop_route(path)


def test_허용되지_않은_Origin에는_붙지_않는다() -> None:
    """요청 Origin 을 그대로 반사하면 허용하지 않은 출처에도 문을 열어 주는 셈이다."""
    path = _with_probe_route()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(path, headers={"Origin": "https://evil.example.com"})
        assert response.status_code == 500
        assert "access-control-allow-origin" not in {k.lower() for k in response.headers}
        # 사유 문장은 그대로 한국어여야 한다.
        assert "처리 중 문제가 생겼습니다" in response.json()["detail"]
    finally:
        _drop_route(path)
