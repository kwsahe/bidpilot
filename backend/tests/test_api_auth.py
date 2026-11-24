"""API 토큰 인증 미들웨어 계약 테스트.

계약(사내 호스팅 대비):
    - `API_TOKEN` 미설정 -> 아무것도 막지 않는다(로컬 개발·기존 동작 그대로).
    - `API_TOKEN` 설정   -> `Authorization: Bearer` 또는 `X-API-Token` 필요, 없으면 401.
    - `/health` 와 CORS preflight(OPTIONS)만 공개 예외.
    - 토큰이 설정되면 `/docs`·`/redoc`·`/openapi.json` 도 막힌다(엔드포인트 지도 노출 방지).
    - 401 응답의 본문·헤더 어디에도 토큰 값이 남지 않는다.

설정은 `get_settings()` 가 캐시한 단일 인스턴스를 monkeypatch 로 바꾼다
(test_organizations_api.py 의 `public_demo_mode` 와 같은 방식).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core import auth
from app.core.config import get_settings
from app.main import app

# 응답 어디에도 새어 나오면 안 되는, 눈에 잘 띄는 값.
SECRET = "bidpilot-test-token-9f3a2c7e"

# 토큰이 필요한 대표 엔드포인트(외부 호출 없이 항상 200이 나오는 경로).
PROTECTED_PATH = "/api/organizations"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """토큰 미설정 상태를 명시적으로 만든다(실제 .env 값에 좌우되지 않게)."""
    monkeypatch.setattr(get_settings(), "api_token", "")


@pytest.fixture()
def with_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "api_token", SECRET)
    return SECRET


def _leaks_secret(response) -> bool:  # type: ignore[no-untyped-def]
    """응답 본문 또는 헤더에 토큰 값이 섞여 있는지."""
    if SECRET in response.text:
        return True
    return any(SECRET in value for value in response.headers.values())


# ---------------------------------------------------------------------------
# 토큰 미설정 — 기존 동작을 하나도 바꾸지 않는다
# ---------------------------------------------------------------------------


def test_without_token_everything_passes(client: TestClient, no_token: None) -> None:
    assert auth.token_required() is False
    assert client.get("/health").status_code == 200
    assert client.get(PROTECTED_PATH).status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_without_token_health_reports_auth_not_required(
    client: TestClient, no_token: None
) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["auth_required"] is False


def test_without_token_unexpected_header_is_ignored(
    client: TestClient, no_token: None
) -> None:
    # 인증이 꺼져 있으면 엉뚱한 토큰을 보내도 그냥 통과한다. (HTTP 헤더는 ASCII 만 실린다)
    response = client.get(PROTECTED_PATH, headers={"X-API-Token": "anything"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 토큰 설정 — 헤더가 있어야 통과
# ---------------------------------------------------------------------------


def test_missing_header_is_rejected(client: TestClient, with_token: str) -> None:
    response = client.get(PROTECTED_PATH)
    assert response.status_code == 401
    assert response.json()["detail"]
    assert response.headers.get("www-authenticate") == "Bearer"


def test_wrong_token_is_rejected(client: TestClient, with_token: str) -> None:
    assert client.get(PROTECTED_PATH, headers={"X-API-Token": "wrong-token"}).status_code == 401
    assert (
        client.get(PROTECTED_PATH, headers={"Authorization": "Bearer wrong-token"}).status_code
        == 401
    )
    # 접두어만 같고 뒤가 잘린 값도 통과하면 안 된다.
    truncated = with_token[:-1]
    assert (
        client.get(PROTECTED_PATH, headers={"X-API-Token": truncated}).status_code == 401
    )


def test_unsupported_scheme_is_rejected(client: TestClient, with_token: str) -> None:
    # Basic 등 다른 스킴으로는 통과하지 못한다.
    response = client.get(PROTECTED_PATH, headers={"Authorization": f"Basic {with_token}"})
    assert response.status_code == 401


def test_bearer_token_passes(client: TestClient, with_token: str) -> None:
    response = client.get(PROTECTED_PATH, headers={"Authorization": f"Bearer {with_token}"})
    assert response.status_code == 200
    # 스킴 대소문자는 HTTP 규약상 구분하지 않는다.
    assert (
        client.get(PROTECTED_PATH, headers={"Authorization": f"bearer {with_token}"}).status_code
        == 200
    )


def test_x_api_token_header_passes(client: TestClient, with_token: str) -> None:
    response = client.get(PROTECTED_PATH, headers={"X-API-Token": with_token})
    assert response.status_code == 200
    assert response.json()["organizations"]


def test_auth_runs_before_routing(client: TestClient, with_token: str) -> None:
    # 토큰이 없으면 존재하지 않는 경로도 404가 아니라 401이다(경로 존재 여부를 알려주지 않는다).
    assert client.get("/api/does-not-exist-at-all").status_code == 401
    assert (
        client.get(
            "/api/does-not-exist-at-all", headers={"X-API-Token": with_token}
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# 공개 예외 — /health 와 preflight
# ---------------------------------------------------------------------------


def test_health_is_public_and_reports_auth_required(
    client: TestClient, with_token: str
) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["auth_required"] is True
    # 헬스체크가 토큰 값을 흘리면 안 된다.
    assert not _leaks_secret(response)


def test_preflight_passes_without_token(client: TestClient, with_token: str) -> None:
    response = client.options(
        PROTECTED_PATH,
        headers={
            "Origin": "http://localhost:3110",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-token",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin")


# ---------------------------------------------------------------------------
# 토큰 값 비노출 · 문서 화면 차단
# ---------------------------------------------------------------------------


def test_rejection_never_echoes_token(client: TestClient, with_token: str) -> None:
    for headers in (
        {},
        {"X-API-Token": with_token + "-wrong"},
        {"Authorization": f"Bearer {with_token}-wrong"},
    ):
        response = client.get(PROTECTED_PATH, headers=headers)
        assert response.status_code == 401
        assert not _leaks_secret(response)


def test_docs_are_blocked_when_token_configured(
    client: TestClient, with_token: str
) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 401, path
    # 토큰이 있으면 그대로 열린다.
    assert client.get("/openapi.json", headers={"X-API-Token": with_token}).status_code == 200


# ---------------------------------------------------------------------------
# 헬퍼 단위 테스트
# ---------------------------------------------------------------------------


def test_extract_token_prefers_x_api_token_and_ignores_blanks() -> None:
    assert auth.extract_token(Headers({"x-api-token": " abc "})) == "abc"
    assert auth.extract_token(Headers({"authorization": "Bearer abc"})) == "abc"
    assert auth.extract_token(Headers({"authorization": "Bearer   "})) is None
    assert auth.extract_token(Headers({"x-api-token": "   "})) is None
    assert auth.extract_token(Headers({})) is None


def test_is_public_only_health_and_options() -> None:
    assert auth.is_public({"type": "http", "method": "GET", "path": "/health"}) is True
    assert auth.is_public({"type": "http", "method": "GET", "path": "/health/"}) is True
    assert auth.is_public({"type": "http", "method": "OPTIONS", "path": "/api/x"}) is True
    assert auth.is_public({"type": "http", "method": "GET", "path": "/docs"}) is False
    assert auth.is_public({"type": "http", "method": "GET", "path": "/api/x"}) is False
    # root_path 하위 배포에서도 /health 는 공개다.
    assert (
        auth.is_public(
            {"type": "http", "method": "GET", "path": "/api/health", "root_path": "/api"}
        )
        is True
    )


def test_allowed_origin_list_splits_and_trims(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "allowed_origins", " https://a.example ,https://b.example, ")
    assert settings.allowed_origin_list == ["https://a.example", "https://b.example"]
    monkeypatch.setattr(settings, "allowed_origins", "")
    assert settings.allowed_origin_list == []
