"""사용자 저장소·로그인 API 계약 테스트 (계약서 1장 · 0917.md §4-5).

계약에서 반드시 지켜야 하는 것만 고른다.

- 해시 문자열 형식이 `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>` 다.
  **다른 사람이 같은 계약으로 반대쪽을 만들고 있다** — 형식이 어긋나면 로그인이 통째로 막힌다.
- 틀린 비밀번호·비활성 계정·없는 아이디가 **같은 401** 로 나온다(계정 존재 여부 비공개).
- `users.json` 이 없으면 오류가 아니라 「사용자 없음」이다.
- `DEMO_USER`/`DEMO_PASSWORD` 호환이 살아 있고, 같은 아이디면 users.json 이 이긴다.
- 응답·로그에 비밀번호·해시가 남지 않는다.

저장소의 `data/` 는 건드리지 않는다 — 계정 파일 경로를 전부 `tmp_path` 로 돌린다.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import logging
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.services import user_service

# 로그·응답 어디에도 새어 나오면 안 되는, 눈에 잘 띄는 값.
PASSWORD = "bidpilot-secret-8f2c41"
OTHER_PASSWORD = "bidpilot-other-71ab93"

HASH_PATTERN = re.compile(r"^pbkdf2_sha256\$(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)$")

#: 아래 픽스처가 반복 횟수를 낮추기 **전에** 읽어 둔 실제 기본값. 계약서는 600,000 을 정한다.
REAL_DEFAULT_ITERATIONS = user_service.DEFAULT_ITERATIONS


@pytest.fixture(autouse=True)
def users_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """계정 파일을 tmp 로 돌리고, 해시 반복 횟수를 낮춘다.

    반복 횟수를 낮추는 이유는 속도뿐이다. 기본값(600,000)이 계약대로인지는
    `test_해시_형식은_계약서가_정한_그대로다` 가 따로 본다.
    """
    path = tmp_path / "private" / "users.json"
    monkeypatch.setattr(user_service, "USERS_FILE", path)
    monkeypatch.setattr(user_service, "DEFAULT_ITERATIONS", 1_000)
    monkeypatch.delenv("DEMO_USER", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    auth_api.reset_login_throttle()
    return path


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """로그인 라우터만 붙인 앱.

    `app.main` 에 라우터가 붙었는지와 상관없이 이 계약을 확인할 수 있게 따로 조립한다
    (라우터를 붙이는 `main.py` 는 A 묶음의 파일이다).
    """
    app = FastAPI()
    app.include_router(auth_api.router)
    with TestClient(app) as test_client:
        yield test_client


def write_users(path: Path, users: list[dict[str, Any]], *, version: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": version, "users": users}, ensure_ascii=False), encoding="utf-8"
    )


def leaks_secret(text: str) -> bool:
    return PASSWORD in text or OTHER_PASSWORD in text


# ---------------------------------------------------------------------------
# 비밀번호 해시 — 계약서 1장
# ---------------------------------------------------------------------------


def test_해시_형식은_계약서가_정한_그대로다() -> None:
    """실제 기본값으로 만든 해시가 `pbkdf2_sha256$600000$<salt>$<hash>` 인지 본다(느리지만 한 번만)."""
    assert REAL_DEFAULT_ITERATIONS == 600_000
    encoded = user_service.hash_password(PASSWORD, iterations=REAL_DEFAULT_ITERATIONS)
    match = HASH_PATTERN.match(encoded)
    assert match is not None, "해시 형식이 계약서와 다르다"
    assert match.group(1) == "600000"
    assert len(base64.b64decode(match.group(2))) == 16  # salt 16바이트
    assert len(base64.b64decode(match.group(3))) == 32  # dklen=32
    assert user_service.verify_password(PASSWORD, encoded) is True


def test_해시_왕복() -> None:
    encoded = user_service.hash_password(PASSWORD)
    assert user_service.verify_password(PASSWORD, encoded) is True
    assert user_service.verify_password(OTHER_PASSWORD, encoded) is False
    assert user_service.verify_password(PASSWORD.upper(), encoded) is False


def test_같은_비밀번호라도_해시는_매번_다르다() -> None:
    """salt 가 매번 새로 나오는지 — 같은 값이면 같은 비밀번호를 쓰는 계정이 드러난다."""
    first = user_service.hash_password(PASSWORD)
    second = user_service.hash_password(PASSWORD)
    assert first != second
    assert user_service.verify_password(PASSWORD, second) is True


def test_다른_구현이_만든_해시도_그대로_검증된다() -> None:
    """계약서 식 그대로 손으로 만든 해시를 받아들이는지 — 반대쪽 구현과의 접점이다."""
    salt = b"0123456789abcdef"
    iterations = 1_000
    digest = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode("utf-8"), salt, iterations, dklen=32)
    encoded = (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    )
    assert user_service.verify_password(PASSWORD, encoded) is True
    assert user_service.verify_password(OTHER_PASSWORD, encoded) is False


@pytest.mark.parametrize(
    "broken",
    [
        "",
        "pbkdf2_sha256$1000$onlythree",
        "bcrypt$1000$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$abc$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$0$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$-5$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$1000$!!!$aGFzaA==",
        "pbkdf2_sha256$1000$$aGFzaA==",
        "pbkdf2_sha256$ 1000$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$1_000$c2FsdA==$aGFzaA==",
    ],
)
def test_깨진_해시는_예외가_아니라_거부다(broken: str) -> None:
    """형식이 깨졌다고 500 이 나면 로그인 화면이 통째로 죽는다. 「틀림」과 같게 다룬다."""
    assert user_service.verify_password(PASSWORD, broken) is False


def test_터무니없는_반복횟수는_계산하지_않고_거부한다() -> None:
    """파일에 `999999999` 가 적혀 있으면 로그인 한 번이 서버를 멈춘다."""
    encoded = f"pbkdf2_sha256$999999999${base64.b64encode(b'x' * 16).decode()}${base64.b64encode(b'y' * 32).decode()}"
    assert user_service.verify_password(PASSWORD, encoded) is False


def test_빈_비밀번호는_해시도_검증도_거부한다() -> None:
    with pytest.raises(user_service.UserError):
        user_service.hash_password("")
    assert user_service.verify_password("", user_service.hash_password(PASSWORD)) is False


# ---------------------------------------------------------------------------
# 저장소 — 파일이 없을 때 / 추가 / 변경
# ---------------------------------------------------------------------------


def test_파일이_없으면_오류가_아니라_사용자_없음이다(users_file: Path) -> None:
    assert users_file.exists() is False
    assert user_service.load_users() == []
    assert user_service.find_user("hong") is None
    outcome = user_service.authenticate("hong", PASSWORD)
    assert outcome.account is None and outcome.reason == "no_such_user"
    assert users_file.exists() is False  # 읽기만 해서는 파일을 만들지 않는다


def test_계정을_만들면_계약서_형식으로_저장된다(users_file: Path) -> None:
    record = user_service.add_user("hong", PASSWORD, role="editor", display_name="홍길동")
    assert record.role == "editor"

    saved = json.loads(users_file.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert len(saved["users"]) == 1
    stored = saved["users"][0]
    assert set(stored) == {"user", "display_name", "role", "password_hash", "created_at", "active"}
    assert stored["user"] == "hong"
    assert stored["display_name"] == "홍길동"
    assert stored["active"] is True
    assert HASH_PATTERN.match(stored["password_hash"])
    assert not leaks_secret(users_file.read_text(encoding="utf-8"))  # 평문은 어디에도 없다


def test_같은_아이디는_덮어쓰지_않고_거부한다() -> None:
    user_service.add_user("hong", PASSWORD)
    with pytest.raises(user_service.UserError):
        user_service.add_user("hong", OTHER_PASSWORD)
    assert user_service.authenticate("hong", PASSWORD).ok is True


def test_기본_역할은_viewer_다() -> None:
    record = user_service.add_user("hong", PASSWORD)
    assert record.role == "viewer"
    assert record.display_name == "hong"


def test_비밀번호를_바꾸면_예전_것은_막힌다() -> None:
    user_service.add_user("hong", PASSWORD, role="admin", display_name="홍길동")
    user_service.set_password("hong", OTHER_PASSWORD)
    assert user_service.authenticate("hong", PASSWORD).ok is False
    changed = user_service.authenticate("hong", OTHER_PASSWORD)
    assert changed.ok is True
    assert changed.account is not None
    assert changed.account.role == "admin"  # 역할·표시이름은 그대로 둔다
    assert changed.account.display_name == "홍길동"


def test_없는_아이디의_비밀번호는_바꿀_수_없다() -> None:
    with pytest.raises(user_service.UserError):
        user_service.set_password("nobody", PASSWORD)


def test_비활성_계정은_비밀번호가_맞아도_거부한다() -> None:
    user_service.add_user("hong", PASSWORD)
    user_service.set_active("hong", False)
    outcome = user_service.authenticate("hong", PASSWORD)
    assert outcome.account is None
    assert outcome.reason == "inactive"


def test_역할이_셋_중_하나가_아니면_로그인을_거부한다(users_file: Path) -> None:
    """백엔드 신원 검사가 어차피 401 을 준다(계약서 4장). 여기서 통과시키면 아무것도 안 되는 로그인이 된다."""
    write_users(
        users_file,
        [
            {
                "user": "hong",
                "display_name": "홍길동",
                "role": "owner",
                "password_hash": user_service.hash_password(PASSWORD),
                "created_at": "2026-09-17T20:00:00+00:00",
                "active": True,
            }
        ],
    )
    outcome = user_service.authenticate("hong", PASSWORD)
    assert outcome.account is None and outcome.reason == "invalid_role"


def test_손상된_계정_파일은_옮기지_않고_읽기만_실패한다(users_file: Path) -> None:
    """공용 read_json 은 깨진 파일을 격리(이름 변경)한다. 계정 파일에서 그러면 전원이 잠긴다."""
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text("{ 깨진 JSON", encoding="utf-8")
    with pytest.raises(user_service.UserStoreError):
        user_service.load_users()
    assert users_file.exists() is True
    assert users_file.read_text(encoding="utf-8") == "{ 깨진 JSON"
    assert list(users_file.parent.iterdir()) == [users_file]  # `.corrupt-*` 사본이 생기지 않았다


def test_빈_파일은_오류가_아니라_사용자_없음이다(users_file: Path) -> None:
    """손으로 만들어 둔 빈 파일 때문에 로그인 화면이 500 으로 죽지 않게 한다."""
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text("   \n", encoding="utf-8")
    assert user_service.load_users() == []
    assert user_service.authenticate("hong", PASSWORD).ok is False


def test_users_항목이_없는_파일도_사용자_없음이다(users_file: Path) -> None:
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text('{"version": 1}', encoding="utf-8")
    assert user_service.load_users() == []


def test_users_가_목록이_아니면_읽기를_실패시킨다(users_file: Path) -> None:
    """형식이 어긋난 파일을 「사용자 없음」으로 덮으면, 계정이 통째로 사라진 것을 아무도 모른다."""
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text('{"version": 1, "users": {"hong": {}}}', encoding="utf-8")
    with pytest.raises(user_service.UserStoreError):
        user_service.load_users()


def test_아이디에_줄바꿈이_들어간_항목은_건너뛴다(users_file: Path) -> None:
    """이 값은 그대로 `X-User` 헤더에 실린다(계약서 3장). 헤더를 쪼개는 값이면 안 된다."""
    write_users(
        users_file,
        [
            {
                "user": "hong\r\nX-User-Role: admin",
                "role": "admin",
                "password_hash": user_service.hash_password(PASSWORD),
            }
        ],
    )
    assert user_service.load_users() == []


def test_active_가_빠진_항목은_사용_중으로_본다(users_file: Path) -> None:
    write_users(
        users_file,
        [
            {
                "user": "hong",
                "role": "viewer",
                "password_hash": user_service.hash_password(PASSWORD),
            }
        ],
    )
    assert user_service.authenticate("hong", PASSWORD).ok is True


def test_해시가_없는_항목은_건너뛴다(users_file: Path) -> None:
    write_users(users_file, [{"user": "ghost", "role": "admin"}, "쓰레기"])
    assert user_service.load_users() == []
    assert user_service.authenticate("ghost", PASSWORD).ok is False


# ---------------------------------------------------------------------------
# 공용 데모 계정 호환 — 계약서 1장
# ---------------------------------------------------------------------------


def test_DEMO_USER_는_admin_으로_계속_인정된다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER", "sampleedu")
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    outcome = user_service.authenticate("sampleedu", PASSWORD)
    assert outcome.ok is True
    assert outcome.account is not None
    assert (outcome.account.role, outcome.account.source) == ("admin", "demo")
    assert user_service.authenticate("sampleedu", OTHER_PASSWORD).ok is False


def test_둘_중_하나만_있으면_공용_계정은_꺼진다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER", "sampleedu")
    assert user_service.demo_account_enabled() is False
    assert user_service.authenticate("sampleedu", PASSWORD).ok is False


def test_같은_아이디면_users_json_이_이긴다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER", "hong")
    monkeypatch.setenv("DEMO_PASSWORD", OTHER_PASSWORD)
    user_service.add_user("hong", PASSWORD, role="viewer", display_name="홍길동")

    fromfile = user_service.authenticate("hong", PASSWORD)
    assert fromfile.ok is True
    assert fromfile.account is not None
    assert (fromfile.account.role, fromfile.account.source) == ("viewer", "file")
    # 환경변수 쪽 비밀번호로는 더 이상 들어오지 못한다(파일이 이긴다).
    assert user_service.authenticate("hong", OTHER_PASSWORD).ok is False


# ---------------------------------------------------------------------------
# 로그인 API — 계약서 1장 2번 과업
# ---------------------------------------------------------------------------


def test_로그인_성공하면_신원_세_가지를_돌려준다(client: TestClient) -> None:
    user_service.add_user("hong", PASSWORD, role="editor", display_name="홍길동")
    response = client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"user": "hong", "display_name": "홍길동", "role": "editor"}
    assert not leaks_secret(response.text)


def test_없는_아이디와_틀린_비밀번호가_구분되지_않는다(client: TestClient) -> None:
    user_service.add_user("hong", PASSWORD)
    wrong_password = client.post("/api/auth/login", json={"user": "hong", "password": OTHER_PASSWORD})
    unknown_user = client.post("/api/auth/login", json={"user": "nobody", "password": PASSWORD})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["detail"] == auth_api.INVALID_CREDENTIALS_DETAIL


def test_비활성_계정도_같은_401_이다(client: TestClient) -> None:
    user_service.add_user("hong", PASSWORD)
    user_service.set_active("hong", False)
    response = client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.INVALID_CREDENTIALS_DETAIL


@pytest.mark.parametrize(
    "body",
    [
        {"user": "", "password": PASSWORD},
        {"user": "hong", "password": ""},
        {"user": "hong", "password": "x" * 5_000},
    ],
)
def test_빈_값과_지나치게_긴_비밀번호는_401_이고_되돌려주지_않는다(
    client: TestClient, body: dict[str, str]
) -> None:
    """422 로 떨어지면 FastAPI 가 입력값을 본문에 그대로 실어 돌려준다 — 비밀번호가 새는 길이다."""
    user_service.add_user("hong", PASSWORD)
    response = client.post("/api/auth/login", json=body)
    assert response.status_code == 401
    assert not leaks_secret(response.text)
    if body["password"]:
        assert body["password"] not in response.text


def test_응답과_로그에_비밀번호도_해시도_남지_않는다(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    user_service.add_user("hong", PASSWORD, role="admin", display_name="홍길동")
    stored = user_service.find_user("hong")
    assert stored is not None
    with caplog.at_level(logging.DEBUG):
        ok = client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD})
        bad = client.post("/api/auth/login", json={"user": "hong", "password": OTHER_PASSWORD})
    assert (ok.status_code, bad.status_code) == (200, 401)
    logged = caplog.text
    assert not leaks_secret(logged)
    assert not leaks_secret(ok.text + bad.text)
    assert stored.password_hash not in logged
    assert stored.password_hash not in ok.text + bad.text


def test_없는_아이디는_로그에도_남기지_않는다(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """비밀번호를 아이디 칸에 잘못 치는 사람이 있다. 그 값을 로그에 박으면 그게 유출이다."""
    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/login", json={"user": PASSWORD, "password": PASSWORD})
        # 비밀번호 칸이 비어 있으면 계정을 찾아보기 전에 끝난다 — 이때도 아이디를 남기지 않는다.
        client.post("/api/auth/login", json={"user": OTHER_PASSWORD, "password": ""})
    assert not leaks_secret(caplog.text)


def test_계정_파일이_깨졌으면_401_이_아니라_500_이다(client: TestClient, users_file: Path) -> None:
    """「비밀번호가 틀렸다」고 답하면 운영자가 원인을 못 찾는다."""
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text("{ 깨진 JSON", encoding="utf-8")
    response = client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD})
    assert response.status_code == 500
    assert not leaks_secret(response.text)


# ---------------------------------------------------------------------------
# 연속 실패 방어
# ---------------------------------------------------------------------------


def test_연속_실패가_쌓이면_맞는_비밀번호도_잠시_막힌다(client: TestClient) -> None:
    user_service.add_user("hong", PASSWORD)
    for _ in range(auth_api.MAX_FAILURES):
        assert client.post("/api/auth/login", json={"user": "hong", "password": OTHER_PASSWORD}).status_code == 401

    locked = client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD})
    assert locked.status_code == 401
    assert locked.json()["detail"] == auth_api.TOO_MANY_ATTEMPTS_DETAIL

    auth_api.reset_login_throttle()
    assert client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD}).status_code == 200


def test_잠금은_없는_아이디에도_똑같이_걸린다(client: TestClient) -> None:
    """있는 계정만 잠기면 잠금 메시지가 곧 「그 아이디는 있다」는 뜻이 된다."""
    for _ in range(auth_api.MAX_FAILURES):
        client.post("/api/auth/login", json={"user": "nobody", "password": OTHER_PASSWORD})
    response = client.post("/api/auth/login", json={"user": "nobody", "password": OTHER_PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.TOO_MANY_ATTEMPTS_DETAIL


def test_성공하면_실패_기록이_지워진다(client: TestClient) -> None:
    user_service.add_user("hong", PASSWORD)
    for _ in range(auth_api.MAX_FAILURES - 1):
        client.post("/api/auth/login", json={"user": "hong", "password": OTHER_PASSWORD})
    assert client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD}).status_code == 200
    for _ in range(auth_api.MAX_FAILURES - 1):
        client.post("/api/auth/login", json={"user": "hong", "password": OTHER_PASSWORD})
    # 기록이 지워졌으므로 아직 잠기지 않았다.
    assert client.post("/api/auth/login", json={"user": "hong", "password": PASSWORD}).status_code == 200


def test_임의의_아이디를_쏟아부어도_기억은_제한된다(client: TestClient) -> None:
    """실패 기록 표가 무한히 늘면 그 자체가 공격 수단이 된다."""
    monkey_ids = auth_api.MAX_TRACKED_IDS + 50
    for index in range(monkey_ids):
        auth_api._note_failure(f"flood-{index}")
    assert len(auth_api._FAILURES) <= auth_api.MAX_TRACKED_IDS


# ---------------------------------------------------------------------------
# 관리 스크립트 — scripts/manage_users.py
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manage() -> Any:
    script = Path(__file__).resolve().parents[2] / "scripts" / "manage_users.py"
    spec = importlib.util.spec_from_file_location("manage_users", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def answer_password(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    """getpass 프롬프트 응답을 순서대로 돌려준다."""
    queued = list(answers)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": queued.pop(0))


def test_스크립트가_계정을_만들고_로그인이_된다(
    manage: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_password(monkeypatch, PASSWORD, PASSWORD)
    assert manage.main(["add", "hong", "--role", "editor", "--name", "홍길동"]) == 0
    assert user_service.authenticate("hong", PASSWORD).ok is True
    assert not leaks_secret(capsys.readouterr().out)


def test_스크립트는_같은_아이디를_거부한다(manage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    answer_password(monkeypatch, PASSWORD, PASSWORD, OTHER_PASSWORD, OTHER_PASSWORD)
    assert manage.main(["add", "hong"]) == 0
    assert manage.main(["add", "hong"]) == 1
    assert user_service.authenticate("hong", PASSWORD).ok is True


def test_스크립트는_두_번_입력이_다르면_만들지_않는다(
    manage: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_password(monkeypatch, PASSWORD, OTHER_PASSWORD)
    assert manage.main(["add", "hong"]) == 1
    assert user_service.load_users() == []


def test_스크립트는_짧은_비밀번호를_거부한다(manage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    answer_password(monkeypatch, "short", "short")
    assert manage.main(["add", "hong"]) == 1
    assert user_service.load_users() == []


def test_스크립트_목록은_해시를_찍지_않는다(
    manage: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_password(monkeypatch, PASSWORD, PASSWORD)
    manage.main(["add", "hong", "--name", "홍길동"])
    capsys.readouterr()

    assert manage.main(["list"]) == 0
    printed = capsys.readouterr().out
    record = user_service.find_user("hong")
    assert record is not None
    assert "hong" in printed and "홍길동" in printed and "viewer" in printed
    assert record.password_hash not in printed
    assert "pbkdf2_sha256" not in printed
    assert not leaks_secret(printed)


def test_스크립트_목록은_공용_계정_값을_찍지_않는다(
    manage: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEMO_USER", "sampleedu")
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    assert manage.main(["list"]) == 0
    printed = capsys.readouterr().out
    assert "DEMO_USER" in printed  # 켜져 있다는 사실은 알린다
    assert "sampleedu" not in printed  # 값은 알리지 않는다
    assert not leaks_secret(printed)


def test_스크립트가_계정을_끄면_로그인이_막힌다(
    manage: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_password(monkeypatch, PASSWORD, PASSWORD)
    manage.main(["add", "hong"])
    assert manage.main(["disable", "hong"]) == 0
    assert user_service.authenticate("hong", PASSWORD).ok is False
    assert not leaks_secret(capsys.readouterr().out)


def test_스크립트가_비밀번호를_바꾼다(manage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    answer_password(monkeypatch, PASSWORD, PASSWORD, OTHER_PASSWORD, OTHER_PASSWORD)
    manage.main(["add", "hong"])
    assert manage.main(["passwd", "hong"]) == 0
    assert user_service.authenticate("hong", PASSWORD).ok is False
    assert user_service.authenticate("hong", OTHER_PASSWORD).ok is True


def test_없는_아이디면_비밀번호를_묻지도_않는다(manage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """새 비밀번호를 두 번 친 뒤에 「없는 아이디입니다」를 보는 일이 없게 한다."""

    def never(_prompt: str = "") -> str:
        raise AssertionError("없는 아이디인데 비밀번호를 물었다")

    monkeypatch.setattr("getpass.getpass", never)
    assert manage.main(["passwd", "nobody"]) == 1


def test_스크립트는_비밀번호를_인자로_받지_않는다(manage: Any) -> None:
    """인자로 받으면 셸 기록과 프로세스 목록에 그대로 남는다(계약서 7장)."""
    parser = manage.build_parser()
    for command in ("add", "passwd"):
        with pytest.raises(SystemExit):
            parser.parse_args([command, "hong", "--password", PASSWORD])
        with pytest.raises(SystemExit):
            parser.parse_args([command, "hong", PASSWORD])
