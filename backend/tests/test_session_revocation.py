"""검수 §3-A 의 남은 항목들 — S3·S5·S6·S8·S9.

각 항목이 왜 문제였는지는 해당 테스트 위에 적었다. 공통점은 하나다:
**화면에서는 보이지 않고, 잘못되어도 조용하다.** 그래서 테스트로 고정한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core import identity, storage
from app.core.config import get_settings
from app.main import app
from app.services import audit_log_service, g2b_client, user_service

SECRET = "bidpilot-revocation-test-token-91a2"
LIST_PATH = "/api/organizations"
MISSING_PATH = "/api/does-not-exist-at-all"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """토큰을 켜고, 계정 파일과 활동 기록을 tmp 로 돌린다."""
    monkeypatch.setattr(get_settings(), "api_token", SECRET)
    users = tmp_path / "users.json"
    monkeypatch.setattr(user_service, "USERS_FILE", users)
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", tmp_path / "audit_log.jsonl")
    # 공용 계정이 끼어들지 않게 한다 — 여기서 재는 것은 개인 계정이다.
    monkeypatch.delenv("DEMO_USER", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    user_service.clear_snapshot_cache()
    yield users
    user_service.clear_snapshot_cache()


def write_users(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"version": 1, "users": entries}, ensure_ascii=False), encoding="utf-8")
    user_service.clear_snapshot_cache()


def account(user: str, role: str, *, active: bool = True) -> dict[str, object]:
    return {
        "user": user,
        "display_name": user,
        "role": role,
        # 해시는 여기서 쓰이지 않는다(로그인이 아니라 «요청마다 대조»를 재는 곳이다).
        "password_hash": "pbkdf2_sha256$1$c2FsdA$aGFzaA",
        "created_at": "2026-09-18T00:00:00+00:00",
        "active": active,
    }


async def _no_notices(**_kwargs: object) -> list[dict]:
    """실호출 대신 빈 목록. 여기서 재는 것은 권한이지 수집 결과가 아니다."""
    return []


async def _no_collect(**_kwargs: object) -> g2b_client.CollectOutcome:
    """새 수집 경로의 같은 가짜. 두 문을 모두 막아야 실네트워크로 새지 않는다."""
    return g2b_client.CollectOutcome(
        items=[], calls=1, method="시험 수집", keyword_totals={}, truncated=()
    )


def headers_for(user: str, role: str) -> dict[str, str]:
    return {
        "X-API-Token": SECRET,
        "X-User": user,
        "X-User-Role": role,
        "X-User-Signature": identity.signature_for(user, role, SECRET),
    }


# ---------------------------------------------------------------------------
# S3 — 세션은 살아 있어도 계정이 죽었으면 통과시키지 않는다
# ---------------------------------------------------------------------------


def test_비활성_계정의_세션은_401이다(client: TestClient, isolated: Path) -> None:
    """세션은 12시간짜리다. 계정을 끈 뒤에도 반나절 동안 그대로 열려 있었다."""
    write_users(isolated, [account("hong", "admin")])
    assert client.get(LIST_PATH, headers=headers_for("hong", "admin")).status_code == 200

    write_users(isolated, [account("hong", "admin", active=False)])
    blocked = client.get(LIST_PATH, headers=headers_for("hong", "admin"))
    assert blocked.status_code == 401
    # 45차 L9 — 서명된 세션(그 계정으로 이미 로그인했던 사람)에게는 「계정이 꺼졌습니다 — 관리자에게」.
    # 「다시 로그인」이라 하면 같은 비밀번호로 또 들어가려 했다. 로그인 화면(아이디만 아는 사람)은 여전히 같은 401 문장이다.
    assert blocked.json()["detail"].startswith("계정이 꺼졌습니다")
    write_users(isolated, [])
    gone = client.get(LIST_PATH, headers=headers_for("hong", "admin"))
    assert gone.status_code == 401 and "다시 로그인" in gone.json()["detail"]


def test_없어진_계정의_세션도_401이다(client: TestClient, isolated: Path) -> None:
    write_users(isolated, [account("hong", "admin")])
    assert client.get(LIST_PATH, headers=headers_for("hong", "admin")).status_code == 200
    write_users(isolated, [])
    assert client.get(LIST_PATH, headers=headers_for("hong", "admin")).status_code == 401


def test_역할을_낮추면_바로_반영된다(client: TestClient, isolated: Path) -> None:
    """세션에 적힌 역할은 «로그인 시점의 사진»이다. 파일이 이긴다."""
    write_users(isolated, [account("hong", "admin")])
    assert client.get("/api/audit-log", headers=headers_for("hong", "admin")).status_code == 200

    write_users(isolated, [account("hong", "viewer")])
    # 세션은 여전히 admin 이라고 말하지만 파일이 viewer 다 → 관리자 전용 경로는 403.
    blocked = client.get("/api/audit-log", headers=headers_for("hong", "admin"))
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == identity.FORBIDDEN_ADMIN_DETAIL
    # 쓰기도 막힌다.
    assert client.post(MISSING_PATH, headers=headers_for("hong", "admin")).status_code == 403


def test_토큰만_있는_스크립트_호출은_계정_대조를_받지_않는다(client: TestClient, isolated: Path) -> None:
    """신원 헤더 없이 토큰만 오는 것은 운영자 직접 호출이다 — users.json 에 있을 리 없다."""
    write_users(isolated, [])
    assert client.get(LIST_PATH, headers={"X-API-Token": SECRET}).status_code == 200


def test_계정_파일이_바뀌면_캐시가_따라온다(isolated: Path) -> None:
    write_users(isolated, [account("kim", "editor")])
    assert user_service.live_role("kim") == "editor"
    write_users(isolated, [account("kim", "viewer")])
    assert user_service.live_role("kim") == "viewer"
    assert user_service.live_role("nobody") == user_service.LIVE_UNKNOWN


# ---------------------------------------------------------------------------
# S5 — 비ASCII 서명이 500 을 만들지 않는다
# ---------------------------------------------------------------------------


def test_비ASCII_서명은_500이_아니라_401이다(client: TestClient, isolated: Path) -> None:
    """`hmac.compare_digest(str, str)` 는 비ASCII 에서 TypeError 를 낸다.

    헤더 하나로 서버 오류를 만들 수 있었다. 모양이 hex 가 아니면 그 자리에서 401 이다.
    """
    write_users(isolated, [account("hong", "admin")])

    # HTTP 헤더는 바이트로 오고 Starlette 는 그것을 **latin-1** 로 읽는다. 그래서 「한글서명」을
    # UTF-8 로 보내면 파이썬 쪽에는 latin-1 범위의 비ASCII 문자열이 들어온다 — 그것이
    # `compare_digest(str, str)` 를 TypeError 로 터뜨리던 값이다. 그 모양을 그대로 만든다.
    mojibake = "한글서명".encode("utf-8").decode("latin-1")
    assert not mojibake.isascii()

    for bogus in [mojibake, "ZZ" * 32, "abc", "A" * 64, " " + "a" * 63, "0" * 63, "0" * 65]:
        with pytest.raises(identity.IdentityError):
            identity.resolve(
                Headers({"x-user": "hong", "x-user-role": "admin", "x-user-signature": bogus}),
                SECRET,
            )

    # HTTP 로도 한 번. 바이트로 실어야 테스트 클라이언트를 통과한다.
    response = client.get(
        LIST_PATH,
        headers=[
            (b"x-api-token", SECRET.encode()),
            (b"x-user", b"hong"),
            (b"x-user-role", b"admin"),
            (b"x-user-signature", "한글서명".encode("utf-8")),
        ],
    )
    assert response.status_code == 401, response.status_code


# ---------------------------------------------------------------------------
# S6 — 조직 단일 경로의 모든 쓰기가 관리자 전용
# ---------------------------------------------------------------------------


def test_조직_단일_경로는_모든_쓰기가_관리자_전용이다() -> None:
    for method in ("PATCH", "PUT", "DELETE", "POST"):
        assert identity.is_admin_only("/api/organizations/org-x", method) is True, method
    # 조회는 누구나. 그 «아래» 자료·색인은 편집자의 일이다.
    assert identity.is_admin_only("/api/organizations/org-x", "GET") is False
    assert identity.is_admin_only("/api/organizations/org-x/documents", "POST") is False
    assert identity.is_admin_only("/api/organizations/org-x/index/rebuild", "POST") is False
    # 켜고 끄기는 관리자.
    assert identity.is_admin_only("/api/organizations/org-x/activate", "POST") is True


# ---------------------------------------------------------------------------
# S8 — 상태를 바꾸는 GET 은 쓰기로 취급한다
# ---------------------------------------------------------------------------


def test_refresh가_붙은_목록_조회는_쓰기다() -> None:
    assert identity.is_write_request("GET", "/api/procurements", "days=14") is False
    assert identity.is_write_request("GET", "/api/procurements", "refresh=true") is True
    assert identity.is_write_request("GET", "/api/procurements", "days=14&refresh=1") is True
    assert identity.is_write_request("GET", "/api/business-opportunities", "refresh=TRUE") is True
    # 끄는 값과 이름이 비슷한 다른 파라미터에는 걸리지 않는다.
    assert identity.is_write_request("GET", "/api/procurements", "refresh=false") is False
    assert identity.is_write_request("GET", "/api/procurements", "norefresh=true") is False
    # 목록에 없는 경로는 그대로 조회다.
    assert identity.is_write_request("GET", "/api/rfp/x", "refresh=true") is False


def test_열람자는_refresh를_부를_수_없다(
    client: TestClient, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_users(isolated, [account("view", "viewer")])
    blocked = client.get("/api/procurements?refresh=true", headers=headers_for("view", "viewer"))
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == identity.FORBIDDEN_WRITE_DETAIL
    # 같은 경로라도 refresh 가 없으면 조회다. 실호출을 타지 않도록 빈 응답으로 대신한다.
    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _no_notices)
    monkeypatch.setattr(g2b_client, "collect_notices", _no_collect)
    assert client.get("/api/procurements", headers=headers_for("view", "viewer")).status_code != 403


def test_refresh_거절도_활동_기록에_남는다(client: TestClient, isolated: Path) -> None:
    write_users(isolated, [account("view", "viewer")])
    client.get("/api/procurements?refresh=true", headers=headers_for("view", "viewer"))
    entries = [
        json.loads(line)
        for line in audit_log_service.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert entries, "막힌 쓰기 시도가 기록되지 않았다"
    last = entries[-1]
    assert (last["user"], last["status"], last["path"]) == ("view", 403, "/api/procurements")
    # 쿼리 문자열은 기록에 넣지 않는다 (계약서 6장).
    assert "refresh" not in json.dumps(last, ensure_ascii=False)


# ---------------------------------------------------------------------------
# S9 — 활동 기록은 무한히 자라지 않는다
# ---------------------------------------------------------------------------


def test_활동_기록은_크기를_넘으면_회전한다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", path)
    monkeypatch.setattr(audit_log_service, "MAX_BYTES", 400)
    monkeypatch.setattr(audit_log_service, "MAX_BACKUPS", 2)

    for index in range(40):
        audit_log_service.append(
            user=f"u{index}", role="admin", method="POST", path="/api/x",
            organization_id=None, status=200,
        )

    assert path.exists()
    assert path.stat().st_size < 400 * 2, "회전하지 않고 계속 자랐다"
    assert path.with_name(f"{path.name}.1").exists(), "직전 벌이 없다"
    # 상한을 넘는 벌은 버린다 — 이 파일에는 누가 무엇을 했는지가 들어 있다.
    assert not path.with_name(f"{path.name}.3").exists()


def test_회전해도_최근_기록은_그대로_읽힌다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", path)
    monkeypatch.setattr(audit_log_service, "MAX_BYTES", 400)
    for index in range(40):
        audit_log_service.append(
            user=f"u{index}", role="admin", method="POST", path="/api/x",
            organization_id=None, status=200,
        )
    recent = audit_log_service.read_recent(5)
    assert [entry["user"] for entry in recent][0] == "u39", "최신 줄이 맨 앞에 와야 한다"


# ---------------------------------------------------------------------------
# S12 — 「누가 저장했는가」를 본문의 주장이 아니라 인증된 신원으로 남긴다
# ---------------------------------------------------------------------------


def test_해결_처리에_인증된_계정이_함께_남는다(
    client: TestClient, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검토자 이름은 화면이 채워 보내는 값이라 «주장»이다.

    열람자로 로그인한 사람이 본문에 「박부장」이라고 적어 보내면 기록에는 박부장이 판단한
    것으로 남았다. 미들웨어가 이미 확인한 신원을 한 칸 더 남긴다 — `reviewer` 는 그대로다.
    """
    write_users(isolated, [account("kim", "editor")])
    from app.services import finding_resolution_service, review_service

    monkeypatch.setattr(review_service, "known_procurement", lambda _pid: True)
    monkeypatch.setattr(
        finding_resolution_service, "resolution_path", lambda *_a, **_k: isolated.parent / "res.json"
    )

    response = client.put(
        "/api/auditor/synthetic-rfp-0001/resolutions",
        headers=headers_for("kim", "editor"),
        json={
            "key": "missing_requirement:req:REQ-001",
            "status": "resolved",
            "finding_type": "missing_requirement",
            "reviewer": "박부장",
            "note": "운영계획에 추가함",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # 본문의 주장은 그대로 남는다 — 두 가지는 다른 뜻이다.
    assert body["reviewer"] == "박부장"
    # 그리고 실제로 누른 계정이 함께 남는다.
    assert body["recorded_by"] == "kim"


def test_인증이_꺼진_로컬은_local_admin으로_남는다() -> None:
    """`None` 은 「필드가 생기기 전」과 「인증이 꺼진 기계」를 같은 값으로 뭉갠다.

    `local-admin` 은 지어낸 이름이 아니라 그 상태에서 백엔드가 실제로 쓰는 신원이다.
    (4차의 판단을 0919.md §4-A-1 지시에 따라 뒤집었다.)
    """
    from app.core import identity as identity_module
    from app.core import requester

    class FakeState:
        pass

    class FakeRequest:
        def __init__(self, who: object | None) -> None:
            self.state = FakeState()
            if who is not None:
                self.state.identity = who

    # 요청에 신원 자체가 없으면(스크립트·테스트) None 이다 — 기록할 요청이 없다.
    assert requester.recorded_by(FakeRequest(None)) is None
    local = identity_module.Identity("local-admin", "admin", "local")
    assert requester.recorded_by(FakeRequest(local)) == "local-admin"
    signed = identity_module.Identity("kim", "editor", "signed")
    assert requester.recorded_by(FakeRequest(signed)) == "kim"
    token = identity_module.Identity("api-token", "admin", "token")
    assert requester.recorded_by(FakeRequest(token)) == "api-token"


# ---------------------------------------------------------------------------
# N1 — 「쓰기 취급 GET」 판정이 프레임워크와 같은 눈으로 본다
# ---------------------------------------------------------------------------


def test_프레임워크가_참으로_읽는_값을_모두_쓰기로_본다() -> None:
    """검수가 재현한 우회 경로.

    판정은 쿼리 문자열을 눈으로 훑어 `1·true·yes·on` 만 봤는데, pydantic 은 `t`·`y` 도
    참으로 읽고 `%31` 은 URL 디코딩을 거쳐 `1` 이 된다. 그래서 `?refresh=t` 는
    **판정에서는 읽기, 라우트에서는 새로고침**이 됐다 — 열람자가 막히지도 기록되지도 않은 채
    실호출을 일으킬 수 있었다.
    """
    for value in ("1", "true", "TRUE", "t", "T", "y", "yes", "on", "%31", "%74rue"):
        assert identity.is_write_request("GET", "/api/procurements", f"refresh={value}") is True, value
    for value in ("0", "false", "f", "n", "no", "off", ""):
        assert identity.is_write_request("GET", "/api/procurements", f"refresh={value}") is False, value
    # 이름이 비슷한 다른 파라미터에는 걸리지 않는다.
    assert identity.is_write_request("GET", "/api/procurements", "norefresh=true") is False
    assert identity.is_write_request("GET", "/api/procurements", "days=14&include_low=true") is False


def test_목록_GET은_refresh를_아예_받지_않는다(
    client: TestClient, isolated: Path, monkeypatch: pytest.MonkeyPatch, live_fetch_on: None
) -> None:
    """파라미터를 없앴으므로 파싱이 어긋날 자리 자체가 사라졌다 (N1 · S8 종결).

    옛 클라이언트가 보내면 **무시하되 조용히 무시하지 않는다** — 응답이 그렇게 말한다.

    스위치를 켜는 이유: 이 테스트가 재는 것은 「목록을 **받아 오는** 경로가 200 을 주고
    거기에 `refresh_ignored` 가 실리는가」다. 고정 모드에서는 수집을 건너뛰고 빈 캐시를
    읽어 503 이 되므로, 재려던 자리에 닿지도 못한다. 바깥으로는 나가지 않는다 —
    수집 두 문을 위에서 가짜로 갈아 끼운다.
    """
    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _no_notices)
    monkeypatch.setattr(g2b_client, "collect_notices", _no_collect)
    write_users(isolated, [account("edit", "editor")])

    plain = client.get("/api/procurements", headers=headers_for("edit", "editor"))
    assert plain.status_code == 200
    assert "refresh_ignored" not in plain.json()

    ignored = client.get("/api/procurements?refresh=t", headers=headers_for("edit", "editor"))
    assert ignored.status_code == 200
    assert ignored.json()["refresh_ignored"] is True


def test_열람자는_옛_refresh_주소로도_통과하지_못한다(
    client: TestClient, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _no_notices)
    monkeypatch.setattr(g2b_client, "collect_notices", _no_collect)
    write_users(isolated, [account("view", "viewer")])
    for value in ("t", "y", "%31"):
        blocked = client.get(f"/api/procurements?refresh={value}", headers=headers_for("view", "viewer"))
        assert blocked.status_code == 403, f"refresh={value} 에서 {blocked.status_code}"


# ---------------------------------------------------------------------------
# N5 — 계정 파일을 동시에 써도 한쪽이 사라지지 않는다
# ---------------------------------------------------------------------------


def test_계정을_동시에_추가해도_둘_다_남는다(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`manage_users.py` 를 창 두 개에서 돌리는 일이 실제로 있다.

    잠그지 않으면 둘 다 옛 목록을 읽고 자기 것만 더해 써서, 먼저 만든 계정이 사라진다.
    파일이 깨지지 않으니 그 사람은 로그인이 안 되는 이유를 비밀번호에서 찾는다.
    """
    import threading

    monkeypatch.setattr(storage, "LOCK_DIR", isolated.parent / "locks")
    write_users(isolated, [])
    started = threading.Barrier(2)
    errors: list[BaseException] = []

    def add(name: str) -> None:
        try:
            started.wait(timeout=5)
            # 사람이 실제로 부르는 경로로 재현한다 (`manage_users.py add` → `add_user`).
            # 반복 횟수를 줄여 pbkdf2 60만 회를 두 번만 돌게 한다.
            user_service.add_user(name, "test-password-0919", role="viewer")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(n,)) for n in ("kim", "lee")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    assert not errors, errors
    user_service.clear_snapshot_cache()
    names = {r.user for r in user_service.load_users()}
    assert names == {"kim", "lee"}, names
