"""신원·역할·활동기록 계약 테스트 (계약서 4·5·6장).

여기서 지키려는 약속은 네 가지다.

1. **`API_TOKEN` 이 없으면 아무것도 달라지지 않는다.** 신원 헤더가 와도 무시하고, 막지 않고,
   기록 파일도 만들지 않는다. 기존 테스트 전부가 이 상태로 돈다.
2. 서명된 신원만 믿는다. 위조·반쪽 신원은 **401**(403 이 아니다 — 누구인지부터 모른다).
3. 역할 매트릭스: viewer 는 조회만, editor 는 쓰기까지, 조직 관리·활동기록은 admin 만.
4. 쓰기 요청은 한 줄 기록되고, 그 줄에 **본문·쿼리·토큰 값이 들어가지 않는다.**

기록 파일 경로는 반드시 tmp 로 돌린다. 저장소의 `data/private/` 는 사람의 실제 기록이다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core import auth as auth_middleware
from app.core import identity
from app.core.config import get_settings
from app.core.paths import DATA_ROOT
from app.main import app
from app.services import audit_log_service

SECRET = "bidpilot-identity-test-token-7c1d"

# 아래 fixture 가 tmp 로 바꾸기 «전»의 값. import 시점에 한 번 잡아 둔다.
ORIGINAL_AUDIT_FILE = audit_log_service.AUDIT_LOG_FILE

# 외부 호출 없이 항상 답하는 경로들.
LIST_PATH = "/api/organizations"
MISSING_PATH = "/api/does-not-exist-at-all"
AUDIT_PATH = "/api/audit-log"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def audit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """기록 파일을 tmp 로 돌린다 — 저장소의 `data/private/audit_log.jsonl` 을 건드리지 않는다."""
    path = tmp_path / "private" / "audit_log.jsonl"
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", path)
    return path


@pytest.fixture(autouse=True)
def trust_session_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일은 **역할 매트릭스**를 본다 — 계정 파일 대조(S3)는 꺼 둔다.

    S3 는 서명된 신원이 올 때마다 `users.json` 에서 그 계정이 살아 있는지 다시 본다.
    여기 테스트들은 `v`·`e`·`a` 같은 임시 아이디를 쓰고, 한 아이디를 세 역할로 돌려 쓰기도
    한다(관리자 전용 경로 검사). 그 아이디들을 파일에 심으면 «파일이 이긴다»는 S3 규칙 때문에
    역할이 하나로 고정돼 이 파일이 재려는 것을 못 재게 된다.

    그래서 여기서는 세션의 역할을 그대로 믿고, 계정 대조 자체는 `test_session_revocation.py`
    가 따로 본다. 두 가지를 한 파일에서 재면 어느 쪽이 깨졌는지 알 수 없다.
    """
    monkeypatch.setattr(auth_middleware, "_confirm_account", lambda who: who)


@pytest.fixture()
def no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "api_token", "")


@pytest.fixture()
def with_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "api_token", SECRET)
    return SECRET


def headers_for(user: str, role: str, *, signature: str | None = None) -> dict[str, str]:
    """중계자(Next.js)가 붙이는 것과 같은 헤더 묶음."""
    return {
        "X-API-Token": SECRET,
        "X-User": user,
        "X-User-Role": role,
        "X-User-Signature": signature if signature is not None else identity.signature_for(user, role, SECRET),
    }


def org_body(name: str = "테스트회사") -> dict[str, object]:
    return {"display_name": name, "created_by": "tester", "data_class": "real"}


def lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 4장 — 신원 판정 (순수 함수)
# ---------------------------------------------------------------------------


def test_without_token_identity_is_local_admin() -> None:
    who = identity.resolve(Headers({"x-user": "hong", "x-user-role": "viewer", "x-user-signature": "x"}), "")
    assert (who.user, who.role, who.source) == ("local-admin", "admin", "local")
    # 공백뿐인 토큰도 「없음」이다.
    assert identity.resolve(Headers({}), "   ").source == "local"


def test_signed_headers_are_trusted() -> None:
    who = identity.resolve(Headers({
        "x-user": "hong",
        "x-user-role": "editor",
        "x-user-signature": identity.signature_for("hong", "editor", SECRET),
    }), SECRET)
    assert (who.user, who.role, who.source) == ("hong", "editor", "signed")
    assert who.can_write is True
    assert who.is_admin is False


def test_forged_signature_is_rejected() -> None:
    with pytest.raises(identity.IdentityError):
        identity.resolve(Headers({"x-user": "hong", "x-user-role": "admin", "x-user-signature": "0" * 64}), SECRET)
    # 다른 역할로 서명해 두고 역할만 올려 보내는 것도 막힌다(서명 입력에 역할이 들어 있다).
    with pytest.raises(identity.IdentityError):
        identity.resolve(Headers({
            "x-user": "hong",
            "x-user-role": "admin",
            "x-user-signature": identity.signature_for("hong", "viewer", SECRET),
        }), SECRET)
    # 다른 키로 만든 서명도 막힌다.
    with pytest.raises(identity.IdentityError):
        identity.resolve(Headers({
            "x-user": "hong",
            "x-user-role": "admin",
            "x-user-signature": identity.signature_for("hong", "admin", SECRET + "-other"),
        }), SECRET)


def test_unknown_role_is_rejected_even_with_valid_signature() -> None:
    with pytest.raises(identity.IdentityError):
        identity.resolve(Headers({
            "x-user": "hong",
            "x-user-role": "superuser",
            "x-user-signature": identity.signature_for("hong", "superuser", SECRET),
        }), SECRET)


def test_no_headers_means_token_holder() -> None:
    who = identity.resolve(Headers({}), SECRET)
    assert (who.user, who.role, who.source) == ("api-token", "admin", "token")


def test_partial_identity_is_rejected() -> None:
    combos = (
        {"x-user": "hong"},
        {"x-user-role": "admin"},
        {"x-user-signature": "abc"},
        {"x-user": "hong", "x-user-role": "admin"},  # 서명만 떼면 통과하는 길을 남기지 않는다
        {"x-user": "hong", "x-user-signature": identity.signature_for("hong", "admin", SECRET)},
    )
    for combo in combos:
        with pytest.raises(identity.IdentityError):
            identity.resolve(Headers(combo), SECRET)


def test_blank_header_values_count_as_absent() -> None:
    # 빈 문자열은 「보내지 않은 것」과 같다. 셋 다 비어 있으면 토큰 보유자다.
    who = identity.resolve(Headers({"x-user": "  ", "x-user-role": "", "x-user-signature": " "}), SECRET)
    assert who.source == "token"
    # 하나만 비어 있으면 반쪽 신원이다.
    with pytest.raises(identity.IdentityError):
        identity.resolve(Headers({
            "x-user": " ",
            "x-user-role": "admin",
            "x-user-signature": identity.signature_for("hong", "admin", SECRET),
        }), SECRET)


def test_signature_input_is_exactly_user_newline_role() -> None:
    """계약서 3장의 서명 입력 문자열. 한 글자만 달라도 반대쪽 구현과 어긋난다."""
    import hashlib
    import hmac

    expected = hmac.new(SECRET.encode("utf-8"), b"hong\neditor", hashlib.sha256).hexdigest()
    assert identity.signature_for("hong", "editor", SECRET) == expected
    assert expected == expected.lower()


# ---------------------------------------------------------------------------
# 5장 — 역할 매트릭스 (순수 함수)
# ---------------------------------------------------------------------------


def test_admin_only_paths() -> None:
    """관리자 전용은 «회사 자체»를 다루는 것뿐이다 (0917.md §4-5-4).

    처음에는 `/api/organizations` 아래 POST·PATCH·DELETE 를 통째로 관리자 전용으로 뒀는데,
    그러면 편집자가 회사자료를 못 올린다 — 그 접두어 아래에 업로드·승인·색인이 다 있다.
    지시서는 「조직 생성·비활성·사용자 관리 제외」라고 더 좁게 적었고 그쪽이 맞다.
    """
    # 회사 자체 — 관리자만
    assert identity.is_admin_only("/api/organizations", "POST") is True
    assert identity.is_admin_only("/api/organizations/org-x", "PATCH") is True
    assert identity.is_admin_only("/api/organizations/org-x/activate", "POST") is True
    assert identity.is_admin_only("/api/organizations/org-x/deactivate", "POST") is True
    # 활동 기록 — 조회조차 관리자만
    assert identity.is_admin_only("/api/audit-log", "GET") is True
    # 조회는 누구나
    assert identity.is_admin_only("/api/organizations", "GET") is False
    # 접두어만 같은 남의 경로를 관리자 전용으로 오인하지 않는다.
    assert identity.is_admin_only("/api/organizations-export", "POST") is False
    # 회사«자료»는 편집자의 일이다 — 업로드·추출·승인·폐기·삭제·색인·원장·프로필 전부.
    for editor_ok, verb in (
        ("/api/organizations/org-x/documents", "POST"),
        ("/api/organizations/org-x/documents/d1/extract", "POST"),
        ("/api/organizations/org-x/documents/d1/approve", "POST"),
        ("/api/organizations/org-x/documents/d1/retire", "POST"),
        ("/api/organizations/org-x/documents/d1", "DELETE"),
        ("/api/organizations/org-x/documents/d1/candidates", "PUT"),
        ("/api/organizations/org-x/index/rebuild", "POST"),
        ("/api/organizations/org-x/index/search", "POST"),
        ("/api/organizations/org-x/ledger/import", "POST"),
        ("/api/organizations/org-x/profile", "PUT"),
    ):
        assert identity.is_admin_only(editor_ok, verb) is False, f"{verb} {editor_ok}"


def test_forbidden_reason_matrix() -> None:
    viewer = identity.Identity("v", "viewer", "signed")
    editor = identity.Identity("e", "editor", "signed")
    admin = identity.Identity("a", "admin", "signed")

    assert identity.forbidden_reason(viewer, "/api/rfp/parse", "GET") is None
    assert identity.forbidden_reason(viewer, "/api/rfp/parse", "POST") == identity.FORBIDDEN_WRITE_DETAIL
    assert identity.forbidden_reason(viewer, AUDIT_PATH, "GET") == identity.FORBIDDEN_ADMIN_DETAIL
    assert identity.forbidden_reason(editor, "/api/rfp/parse", "POST") is None
    assert identity.forbidden_reason(editor, LIST_PATH, "POST") == identity.FORBIDDEN_ADMIN_DETAIL
    assert identity.forbidden_reason(editor, LIST_PATH, "GET") is None
    assert identity.forbidden_reason(editor, "/api/organizations/org-x/profile", "PUT") is None
    # 편집자는 회사자료를 올릴 수 있어야 한다 (0917.md §4-5-4 「업로드 등 쓰기」).
    assert identity.forbidden_reason(editor, "/api/organizations/org-x/documents", "POST") is None
    assert identity.forbidden_reason(viewer, "/api/organizations/org-x/documents", "POST") == identity.FORBIDDEN_WRITE_DETAIL
    # 회사 자체를 끄는 것은 관리자만.
    assert identity.forbidden_reason(editor, "/api/organizations/org-x/deactivate", "POST") == identity.FORBIDDEN_ADMIN_DETAIL
    assert identity.forbidden_reason(admin, "/api/organizations/org-x/deactivate", "POST") is None
    assert (
        identity.forbidden_reason(viewer, "/api/organizations/org-x/profile", "PUT")
        == identity.FORBIDDEN_WRITE_DETAIL
    )
    for path, method in (("/api/rfp/parse", "POST"), (LIST_PATH, "POST"), (AUDIT_PATH, "GET")):
        assert identity.forbidden_reason(admin, path, method) is None
    # 로컬(인증 꺼짐)은 무엇도 막지 않는다.
    assert identity.forbidden_reason(identity.Identity("local-admin", "admin", "local"), LIST_PATH, "POST") is None


# ---------------------------------------------------------------------------
# 5장 — 역할 매트릭스 (실제 요청)
# ---------------------------------------------------------------------------


def test_viewer_can_read_but_not_write(client: TestClient, with_token: str) -> None:
    assert client.get(LIST_PATH, headers=headers_for("v", "viewer")).status_code == 200

    blocked = client.post(MISSING_PATH, headers=headers_for("v", "viewer"))
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "이 작업은 편집자 이상만 할 수 있습니다."


def test_editor_can_write_but_not_manage_organizations(client: TestClient, with_token: str) -> None:
    # 조직 관리가 아닌 쓰기는 역할 게이트를 통과한다(경로가 없어 404 — 403 이 아니다).
    assert client.post(MISSING_PATH, headers=headers_for("e", "editor")).status_code == 404

    blocked = client.post(LIST_PATH, json=org_body(), headers=headers_for("e", "editor"))
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "이 작업은 관리자만 할 수 있습니다."
    # 조회는 막지 않는다 — 막으면 화면이 회사 목록조차 못 그린다.
    assert client.get(LIST_PATH, headers=headers_for("e", "editor")).status_code == 200


def test_admin_can_do_everything(client: TestClient, with_token: str) -> None:
    created = client.post(LIST_PATH, json=org_body(), headers=headers_for("a", "admin"))
    assert created.status_code == 201
    assert client.get(AUDIT_PATH, headers=headers_for("a", "admin")).status_code == 200


def test_audit_log_is_admin_only(client: TestClient, with_token: str) -> None:
    for role in ("viewer", "editor"):
        response = client.get(AUDIT_PATH, headers=headers_for("u", role))
        assert response.status_code == 403, role
        assert response.json()["detail"] == "이 작업은 관리자만 할 수 있습니다."


def test_token_without_identity_headers_is_admin(client: TestClient, with_token: str) -> None:
    """스크립트·운영자 직접 호출. 토큰을 가진 쪽은 이미 전권이다."""
    created = client.post(LIST_PATH, json=org_body("스크립트회사"), headers={"X-API-Token": SECRET})
    assert created.status_code == 201


def test_forged_identity_is_401_not_403(client: TestClient, with_token: str) -> None:
    response = client.get(LIST_PATH, headers=headers_for("mallory", "admin", signature="deadbeef" * 8))
    assert response.status_code == 401
    assert response.json()["detail"] == "신원 서명이 올바르지 않습니다."
    # 응답 어디에도 토큰·서명 값이 남지 않는다.
    assert SECRET not in response.text


def test_half_identity_is_401(client: TestClient, with_token: str) -> None:
    response = client.get(LIST_PATH, headers={"X-API-Token": SECRET, "X-User": "hong", "X-User-Role": "admin"})
    assert response.status_code == 401
    assert response.json()["detail"]


def test_identity_check_runs_after_token_check(client: TestClient, with_token: str) -> None:
    """토큰이 틀리면 신원 헤더를 보나 마나다. 사유도 토큰 쪽 문장이어야 한다."""
    response = client.get(LIST_PATH, headers={**headers_for("hong", "admin"), "X-API-Token": "wrong"})
    assert response.status_code == 401
    assert "인증 토큰" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 무회귀 — `API_TOKEN` 이 없으면 예전 그대로
# ---------------------------------------------------------------------------


def test_without_token_nothing_is_blocked(client: TestClient, no_token: None, audit_file: Path) -> None:
    # 신원 헤더가 와도 무시한다. viewer 라고 주장해도 쓰기가 된다(인증 자체가 꺼진 상태).
    created = client.post(LIST_PATH, json=org_body("로컬회사"), headers={"X-User": "v", "X-User-Role": "viewer"})
    assert created.status_code == 201
    assert client.get(AUDIT_PATH).status_code == 200
    # 기록 파일을 만들지 않는다 — 로컬 개발이 디스크에 남기는 것을 늘리지 않는다.
    assert not audit_file.exists()


def test_without_token_broken_identity_headers_do_not_401(client: TestClient, no_token: None) -> None:
    response = client.get(LIST_PATH, headers={"X-User": "hong", "X-User-Signature": "nonsense"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 6장 — 활동 기록
# ---------------------------------------------------------------------------


def test_audit_log_default_path_is_under_data_private() -> None:
    """실제 경로는 `DATA_ROOT` 에서 만든다(컨테이너 볼륨 이동 대비)."""
    assert ORIGINAL_AUDIT_FILE == DATA_ROOT / "private" / "audit_log.jsonl"


def test_write_request_is_recorded(client: TestClient, with_token: str, audit_file: Path) -> None:
    response = client.post(
        f"{LIST_PATH}?organization_id=org-sample",
        json=org_body("기록회사"),
        headers=headers_for("hong", "admin"),
    )
    assert response.status_code == 201

    recorded = lines(audit_file)
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["user"] == "hong"
    assert entry["role"] == "admin"
    assert entry["method"] == "POST"
    assert entry["path"] == LIST_PATH
    assert entry["organization_id"] == "org-sample"
    assert entry["status"] == 201
    assert entry["ts"].endswith("+00:00")
    # 계약서 6장의 항목 그대로. 모르는 항목을 늘리지 않는다.
    assert set(entry) == {"ts", "user", "role", "method", "path", "organization_id", "status"}


def test_read_requests_are_not_recorded(client: TestClient, with_token: str, audit_file: Path) -> None:
    assert client.get(LIST_PATH, headers=headers_for("hong", "admin")).status_code == 200
    assert client.get("/health").status_code == 200
    assert not audit_file.exists()


def test_blocked_write_is_recorded_with_403(client: TestClient, with_token: str, audit_file: Path) -> None:
    assert client.post(MISSING_PATH, headers=headers_for("v", "viewer")).status_code == 403
    recorded = lines(audit_file)
    assert len(recorded) == 1
    assert recorded[0]["status"] == 403
    assert recorded[0]["user"] == "v"


def test_unverified_identity_is_not_recorded(client: TestClient, with_token: str, audit_file: Path) -> None:
    """서명이 틀린 요청은 이름을 믿을 수 없다. 믿을 수 없는 이름을 기록에 적지 않는다."""
    assert client.post(MISSING_PATH, headers=headers_for("mallory", "admin", signature="00" * 32)).status_code == 401
    assert not audit_file.exists()


def test_record_never_contains_body_query_or_token(
    client: TestClient, with_token: str, audit_file: Path
) -> None:
    client.post(
        f"{LIST_PATH}?organization_id=org-sample&keyword=비밀검색어",
        json={**org_body("비밀회사"), "note": "비밀메모"},
        headers=headers_for("hong", "admin"),
    )
    raw = audit_file.read_text(encoding="utf-8")
    for leaked in (SECRET, "비밀검색어", "비밀메모", "비밀회사", "keyword"):
        assert leaked not in raw, leaked


def test_unsafe_organization_id_is_recorded_as_null(
    client: TestClient, with_token: str, audit_file: Path
) -> None:
    client.post(
        f"{LIST_PATH}?organization_id=../../etc/passwd",
        json=org_body("경로회사"),
        headers=headers_for("hong", "admin"),
    )
    assert lines(audit_file)[0]["organization_id"] is None


def test_record_failure_does_not_break_the_request(
    client: TestClient, with_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기록은 부가 기능이다. 쓰지 못해도 담당자의 작업은 성공해야 한다."""
    blocker = tmp_path / "blocker"
    blocker.write_text("파일이라 폴더를 만들 수 없다", encoding="utf-8")
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", blocker / "private" / "audit_log.jsonl")

    response = client.post(LIST_PATH, json=org_body("장애회사"), headers=headers_for("hong", "admin"))
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# 6장 — 기록 읽기 · 조회 API
# ---------------------------------------------------------------------------


def test_read_recent_is_newest_first_and_capped(audit_file: Path) -> None:
    for index in range(5):
        audit_log_service.append(
            user=f"u{index}", role="viewer", method="POST", path="/api/x", organization_id=None, status=200
        )
    recent = audit_log_service.read_recent(3)
    assert [row["user"] for row in recent] == ["u4", "u3", "u2"]
    assert len(audit_log_service.read_recent(1000)) == 5  # 상한을 넘겨도 터지지 않는다


def test_read_recent_without_file_is_empty(audit_file: Path) -> None:
    assert audit_log_service.read_recent() == []


def test_read_recent_skips_broken_lines(audit_file: Path) -> None:
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text('{"user":"a"}\n깨진 줄\n{"user":"b"}\n', encoding="utf-8")
    assert [row["user"] for row in audit_log_service.read_recent()] == ["b", "a"]


def test_tail_does_not_read_whole_file(audit_file: Path) -> None:
    """파일이 커져도 끝에서만 읽는다. 한글이 블록 경계에 걸려도 최신 줄은 멀쩡해야 한다."""
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with audit_file.open("w", encoding="utf-8") as handle:
        for index in range(3000):
            handle.write(json.dumps({"user": f"사용자{index}", "status": 200}, ensure_ascii=False) + "\n")
    recent = audit_log_service.read_recent(2)
    assert [row["user"] for row in recent] == ["사용자2999", "사용자2998"]


def test_audit_log_api_returns_newest_first(client: TestClient, with_token: str, audit_file: Path) -> None:
    for index in range(3):
        audit_log_service.append(
            user=f"u{index}", role="editor", method="POST", path="/api/x", organization_id="org-sample", status=200
        )
    body = client.get(f"{AUDIT_PATH}?limit=2", headers=headers_for("a", "admin")).json()
    assert body["count"] == 2
    assert body["limit"] == 2
    assert [row["user"] for row in body["entries"]] == ["u2", "u1"]


def test_audit_log_api_rejects_out_of_range_limit(client: TestClient, with_token: str) -> None:
    admin = headers_for("a", "admin")
    assert client.get(f"{AUDIT_PATH}?limit=201", headers=admin).status_code == 422
    assert client.get(f"{AUDIT_PATH}?limit=0", headers=admin).status_code == 422
    assert client.get(f"{AUDIT_PATH}?limit=200", headers=admin).status_code == 200


def test_audit_log_api_without_file_is_empty(client: TestClient, with_token: str) -> None:
    body = client.get(AUDIT_PATH, headers=headers_for("a", "admin")).json()
    assert body == {"entries": [], "count": 0, "limit": audit_log_service.DEFAULT_LIMIT}
