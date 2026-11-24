"""AI 검색(임베딩)을 쓸 수 없을 때의 계약 (ISSUE-002 · 007 · 022).

## 무엇을 막는가

`.env` 의 키가 OpenAI 에서 거부되자(401) 이런 일이 벌어졌다.

  1. `embed()` 만 예외를 감싸지 않아 그대로 밖으로 나갔다 → **500**.
  2. 그 500 은 Starlette 의 기본 오류 처리에서 만들어져 **CORS 헤더가 없다.**
  3. 브라우저 fetch 는 상태 코드조차 못 보고 `TypeError` 로 떨어졌다.
  4. 화면은 그것을 「Backend에 연결할 수 없습니다. localhost:8000 에서 FastAPI 가
     실행 중인지 확인해 주세요」로 안내했다. **서버는 멀쩡히 떠 있었다.**

그래서 여기서 고정하는 것은 세 가지다. 예외는 `LLMUnavailableError` 로 감싸질 것,
사유는 사용자에게 보여줄 한국어일 것(키 값은 절대 담지 않는다), 그리고 처리하지 못한
오류도 JSON + CORS 헤더로 나갈 것.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_client


#: conftest 의 autouse 픽스처가 테스트 중 `embedding_available` 을 «키 존재 확인»으로 바꿔 둔다
#: (다른 테스트가 바깥으로 나가지 않게 하려고). 이 파일은 그 함수 «자체»를 재는 곳이므로
#: 모듈을 읽는 시점(픽스처가 돌기 전)에 진짜 구현을 붙잡아 둔다.
_REAL_EMBEDDING_AVAILABLE = llm_client.embedding_available
#: `embed` 도 같은 이유로 붙잡아 둔다 — conftest 가 「즉시 실패」로 바꿔 두는데,
#: 이 파일은 그 함수가 «예외를 어떻게 감싸는지»를 재는 곳이다 (ISSUE-069).
_REAL_EMBED = llm_client.embed


@pytest.fixture()
def real_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "embedding_available", _REAL_EMBEDDING_AVAILABLE)


@pytest.fixture(autouse=True)
def real_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "embed", _REAL_EMBED)


class FakeAuthError(Exception):
    """openai.AuthenticationError 를 이름만 흉내낸다 (SDK 를 끌어오지 않기 위해)."""


FakeAuthError.__name__ = "AuthenticationError"


class FakeRateLimitError(Exception):
    pass


FakeRateLimitError.__name__ = "RateLimitError"


# ---------------------------------------------------------------------------
# embed() 가 예외를 감싼다
# ---------------------------------------------------------------------------


def test_embed는_인증_실패를_LLMUnavailableError로_감싼다(
    monkeypatch: pytest.MonkeyPatch, embedding_live_on: None
) -> None:
    class Client:
        class embeddings:  # noqa: N801
            @staticmethod
            def create(**_kwargs):
                raise FakeAuthError("Incorrect API key provided: sk-svcacct-XXXX")

    # `_client` 는 탐침용 인자(timeout·max_retries)를 받는다 — 무엇이 오든 같은 대역을 준다.
    monkeypatch.setattr(llm_client, "_client", lambda **_kw: Client())
    with pytest.raises(llm_client.LLMUnavailableError) as exc:
        llm_client.embed(["문장"])
    message = str(exc.value)
    assert "AI 검색 설정" in message
    # 키 값이 사용자에게 나가면 안 된다.
    assert "sk-" not in message


class QuotaError(Exception):
    """크레딧 소진. OpenAI 는 이것도 429 `RateLimitError` 로 던진다."""

    status_code = 429
    code = "insufficient_quota"


class BusyError(Exception):
    """진짜 「잠깐 몰림」. 기다리면 풀린다."""

    status_code = 429
    code = "rate_limit_exceeded"


def test_크레딧_소진과_잠깐_몰림을_다른_말로_안내한다() -> None:
    """같은 429 인데 담당자가 할 일이 정반대다 (0920 §4-B-5 · ISSUE-078).

    예전에는 둘 다 「잠시 후 다시 시도해 주세요」였다. 이 기계의 크레딧은 0 이라 실제로
    뜨던 문구가 그것이었고 — **기다려도 영원히 풀리지 않는다.**
    """
    assert llm_client.failure_reason(QuotaError("x")) == llm_client.CREDIT_EXHAUSTED_REASON
    assert "충전" in llm_client.CREDIT_EXHAUSTED_REASON
    assert llm_client.failure_reason(BusyError("x")) == llm_client.RATE_LIMITED_REASON
    assert "잠시" in llm_client.RATE_LIMITED_REASON


def test_가릴_수_없는_429는_크레딧_소진으로_본다() -> None:
    """코드가 없으면 못 가린다. 그때는 **충전하라**고 말한다.

    이 저장소에서 429 가 나는 원인이 크레딧 소진이고(0920 §2), 「충전하라」를 보고 기다리는
    것보다 「기다리라」를 보고 영영 기다리는 쪽이 더 나쁘다.
    """
    assert llm_client.failure_reason(FakeRateLimitError("x")) == llm_client.CREDIT_EXHAUSTED_REASON


def test_키_거부는_크레딧과_다른_말이다() -> None:
    assert llm_client.failure_reason(FakeAuthError("x")) == llm_client.KEY_REJECTED_REASON
    assert llm_client.KEY_REJECTED_REASON != llm_client.CREDIT_EXHAUSTED_REASON


def test_왜_못_쓰는지를_화면이_읽어_갈_수_있다(
    monkeypatch: pytest.MonkeyPatch, embedding_live_on: None
) -> None:
    """사유가 탐침 안에서 버려지면 문구를 고쳐도 화면에 닿지 않는다.

    회사자료 화면은 크레딧이 바닥났을 때도 「AI 검색 설정이 없습니다」라고만 말했다 —
    설정 문제로 보이니 담당자가 있지도 않은 키 문제를 찾아 헤맨다.
    """
    monkeypatch.setattr(llm_client, "_embedding_reason", None)
    monkeypatch.setattr(
        llm_client,
        "embed",
        lambda *_a, **_k: (_ for _ in ()).throw(llm_client.LLMUnavailableError(llm_client.CREDIT_EXHAUSTED_REASON)),
    )
    assert llm_client._probe_embedding() is False
    assert llm_client.embedding_unavailable_reason() == llm_client.CREDIT_EXHAUSTED_REASON


def test_사유_문장에_기술어와_키가_없다() -> None:
    for error in (FakeAuthError("x"), FakeRateLimitError("x"), TimeoutError("x")):
        reason = llm_client.embed_failure_reason(error)
        assert "sk-" not in reason
        assert "openai" not in reason.lower()
        assert any(ord(ch) > 0x3000 for ch in reason), f"한국어가 아니다: {reason}"


def test_embedding_available은_호출이_실패하면_False다(real_probe, monkeypatch: pytest.MonkeyPatch) -> None:
    """키 «문자열이 있는지»가 아니라 실제로 쓸 수 있는지를 답해야 한다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client,
        "embed",
        lambda *_a, **_k: (_ for _ in ()).throw(llm_client.LLMUnavailableError("거부됨")),
    )
    assert llm_client.embedding_available(refresh=True) is False


def test_embedding_available은_성공하면_True고_한_번만_묻는다(
    real_probe, monkeypatch: pytest.MonkeyPatch, embedding_live_on: None
) -> None:
    calls: list[int] = []

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "embed", lambda *_a, **_k: calls.append(1) or [[0.0]])

    assert llm_client.embedding_available(refresh=True) is True
    assert llm_client.embedding_available() is True
    assert len(calls) == 1, "요청마다 바깥에 다시 물으면 안 된다"


# ---------------------------------------------------------------------------
# 처리하지 못한 오류도 JSON + CORS
# ---------------------------------------------------------------------------


def test_처리못한_오류는_JSON과_CORS_헤더로_나간다() -> None:
    """이것이 「서버가 꺼졌다」 오안내의 뿌리였다."""
    probe = "/__test_boom__"

    @app.get(probe)
    async def boom():  # pragma: no cover - 예외를 내기 위한 경로
        raise RuntimeError("의도적 실패")

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(probe, headers={"Origin": "http://localhost:3110"})
        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3110"
        detail = response.json()["detail"]
        assert "처리 중 문제가 생겼습니다" in detail
        # 내부 사정을 사용자에게 흘리지 않는다.
        assert "RuntimeError" not in detail and "Traceback" not in detail
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != probe]
