"""사용자 저장소 — `data/private/users.json` 읽기·쓰기와 비밀번호 검증 (0917.md §4-5).

왜 파일인가
----------
지금 이 시스템의 저장소는 전부 `data/` 아래 JSON 파일이다(docs/data_model.md). 계정도 같은
규칙을 따른다. 사람 수가 두 자리인 사내 도구라 DB 를 하나 더 세우는 값이 이득보다 크다.
`data/private/` 는 통째로 .gitignore 대상이라 해시가 저장소에 들어갈 일도 없다.

왜 `storage.read_json` 을 쓰지 않는가
------------------------------------
공용 읽기 헬퍼는 JSON 이 깨지면 원본을 `.corrupt-<시각>` 으로 **옮겨 둔다**. 다른 문서라면
안전한 선택이지만 계정 파일에서는 그 순간 **모든 계정이 사라진다** — 로그인 한 번이
관리자까지 잠그는 사고가 된다. 그래서 여기서는 파일을 옮기지 않고 읽기만 실패시킨다
(`UserStoreError`). 쓰기는 공용 헬퍼(임시 파일 → 교체)를 그대로 쓴다.

비밀번호 해시 형식 (계약서 1장 — 한 글자도 바꾸지 않는다)

    pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>

- `hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=32)`
- salt 는 `secrets.token_bytes(16)`, base64 **표준** 인코딩(패딩 포함 — `$` 는 base64
  알파벳에 없으므로 `$` 로 자르는 것이 항상 안전하다).
- 기본 반복 600,000회. 검증은 `hmac.compare_digest` 로 상수 시간 비교.

절대 하지 않는 것
----------------
- 비밀번호·해시를 로그·예외 메시지에 싣지 않는다(CLAUDE.md 21).
- 「아이디가 없다」와 「비밀번호가 틀렸다」를 **호출자에게만** 구분해 주고(로그용),
  화면·응답에서는 구분하지 않는다. 계정 존재 여부는 그 자체로 정보다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core import storage
from app.core.paths import DATA_ROOT

logger = logging.getLogger(__name__)

# 테스트는 이 모듈 상수를 monkeypatch 한다. 함수는 호출 시점에 모듈 값을 읽는다
# (import 시점에 값을 묶어 두지 않는다 — org_storage 와 같은 규칙).
USERS_FILE = DATA_ROOT / "private" / "users.json"

#: 파일 맨 위의 `version`. 계약서가 정한 이름이다(`schema_version` 이 아니다).
FILE_VERSION = 1

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16
HASH_BYTES = 32
#: 파일에 적힌 반복 횟수의 상한. 누가 `999999999` 를 적어 두면 로그인 한 번이 서버를 멈춘다.
MAX_ITERATIONS = 10_000_000

ROLES: tuple[str, ...] = ("viewer", "editor", "admin")
DEFAULT_ROLE = "viewer"

#: 관리 명령이 새 계정을 만들 때만 강제한다. 이미 저장된 아이디는 그대로 인정한다
#: (규칙을 나중에 조이더라도 기존 계정이 잠기면 안 된다).
USER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
#: 파일을 손으로 고친 경우에도 받아 줄 아이디 길이 상한(헤더에 그대로 실리는 값이다).
MAX_USER_ID_LENGTH = 128
MIN_PASSWORD_LENGTH = 8
#: 검증에 받아 줄 비밀번호 길이 상한. 그 위는 계산만 시키는 요청으로 본다.
MAX_PASSWORD_LENGTH = 1024


class UserError(RuntimeError):
    """사람에게 그대로 보여 줄 수 있는 한국어 오류(관리 명령용). 값은 담지 않는다."""


class UserStoreError(UserError):
    """`users.json` 을 읽지 못했다. 파일은 옮기지 않았다 — 그대로 있다."""


@dataclass(frozen=True)
class UserRecord:
    """`users.json` 의 항목 하나. 계약서 1장의 필드만 담는다."""

    user: str
    display_name: str
    role: str
    password_hash: str
    created_at: str
    active: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "display_name": self.display_name,
            "role": self.role,
            "password_hash": self.password_hash,
            "created_at": self.created_at,
            "active": self.active,
        }


@dataclass(frozen=True)
class AuthenticatedUser:
    """로그인에 성공한 신원. 해시는 여기 담지 않는다 — 응답으로 나갈 값이다."""

    user: str
    display_name: str
    role: str
    source: str  # "file" | "demo"


@dataclass(frozen=True)
class AuthOutcome:
    """인증 결과. `reason` 은 **로그에만** 쓴다.

    화면·응답은 실패 사유를 구분하지 않는다(계약서 1장·2번 과업). 그래도 운영자가
    「비밀번호를 틀리고 있는지, 없는 아이디인지」를 모르면 장애를 못 푼다. 그래서 사유는
    여기까지만 올려 주고, 밖으로 내보낼지는 호출자가 정한다.
    """

    account: AuthenticatedUser | None
    #: "ok" | "invalid_input" | "no_such_user" | "wrong_password" | "inactive" | "invalid_role"
    #: 뒤의 셋은 **그 아이디가 실제로 있다**는 뜻이다 — 로그에 아이디를 남겨도 되는 경우가 그때뿐이다.
    reason: str

    @property
    def ok(self) -> bool:
        return self.account is not None


# ---------------------------------------------------------------------------
# 비밀번호 해시
# ---------------------------------------------------------------------------


def hash_password(password: str, *, iterations: int | None = None) -> str:
    """계약서 형식의 해시 문자열을 만든다. 빈 비밀번호는 만들지 않는다."""
    if not password:
        raise UserError("비밀번호가 비어 있습니다.")
    rounds = DEFAULT_ITERATIONS if iterations is None else iterations
    if rounds <= 0:
        raise UserError("반복 횟수는 1 이상이어야 합니다.")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=HASH_BYTES)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(digest).decode("ascii")
    return f"{ALGORITHM}${rounds}${salt_b64}${hash_b64}"


def verify_password(password: str, encoded: str) -> bool:
    """비밀번호가 저장된 해시와 맞는지. 형식이 깨졌으면 **예외 대신 False**.

    깨진 해시에 예외를 올리면 로그인 화면이 500 으로 죽는다. 맞지 않는 것과 같게 다룬다.
    """
    if not password or not encoded or len(password) > MAX_PASSWORD_LENGTH:
        return False
    parts = encoded.split("$")
    if len(parts) != 4:
        return False
    algorithm, raw_iterations, salt_b64, hash_b64 = parts
    if algorithm != ALGORITHM or not raw_iterations.isdigit():
        # `isdigit()` 로 먼저 막는다. `int()` 는 " 1000" 이나 "1_000" 도 받아 주는데,
        # 반대쪽 구현(다른 언어)은 그러지 않는다 — 여기서만 통과하는 해시를 만들지 않는다.
        return False
    try:
        iterations = int(raw_iterations)
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
    except (ValueError, binascii.Error):
        return False
    if not 0 < iterations <= MAX_ITERATIONS or not salt or not expected:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
    return hmac.compare_digest(candidate, expected)


@lru_cache(maxsize=4)
def _dummy_hash(iterations: int) -> str:
    """타이밍 맞추기용 버리는 해시. 반복 횟수별로 한 번만 만든다."""
    return hash_password(secrets.token_urlsafe(16), iterations=iterations)


def _equalize_timing() -> None:
    """없는 아이디에도 **있는 아이디와 같은 시간**을 쓰게 한다.

    없는 아이디면 즉시 돌아오고 있는 아이디면 0.2초쯤 걸린다면, 응답 시간만 재도 어떤
    아이디가 존재하는지 알 수 있다. 메시지를 똑같이 맞춰 놓고 시간으로 새면 의미가 없다.
    """
    verify_password("timing-equalizer", _dummy_hash(DEFAULT_ITERATIONS))


# ---------------------------------------------------------------------------
# 파일 읽기·쓰기
# ---------------------------------------------------------------------------


def _users_path() -> Path:
    return USERS_FILE


def _read_document() -> dict[str, Any]:
    """파일 전체를 읽는다. 없으면 빈 문서 — **오류가 아니다**(계약서 1장)."""
    path = _users_path()
    if not path.exists():
        return {"version": FILE_VERSION, "users": []}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            # 빈 파일은 「아직 아무도 없다」로 본다. 손으로 만들어 둔 파일이 흔하고,
            # 여기서 오류를 내면 로그인 화면이 500 으로 죽는다.
            return {"version": FILE_VERSION, "users": []}
        payload = json.loads(text)
    except ValueError as exc:
        # 파일은 옮기지 않는다. 내용도 찍지 않는다(해시가 들어 있다).
        raise UserStoreError(f"사용자 파일이 손상되어 읽지 못했습니다: {path.name}") from exc
    except OSError as exc:
        raise UserStoreError(f"사용자 파일을 열지 못했습니다: {path.name}") from exc
    if not isinstance(payload, dict):
        raise UserStoreError(f"사용자 파일 형식이 올바르지 않습니다: {path.name}")
    if "users" not in payload:
        # 손으로 `{"version": 1}` 만 적어 둔 경우. 오류로 보지 않고 「아직 아무도 없다」로 본다.
        payload["users"] = []
    if not isinstance(payload["users"], list):
        raise UserStoreError(f"사용자 파일의 users 항목이 목록이 아닙니다: {path.name}")
    return payload


def _record_from(raw: Any, *, where: int) -> UserRecord | None:
    """항목 하나를 해석한다. 못 읽는 항목은 **건너뛴다**(값은 로그에 남기지 않는다)."""
    if not isinstance(raw, dict):
        logger.warning("사용자 파일 %d번째 항목이 객체가 아니라 건너뜁니다.", where)
        return None
    user = raw.get("user")
    password_hash = raw.get("password_hash")
    if not isinstance(user, str) or not user or not isinstance(password_hash, str) or not password_hash:
        logger.warning("사용자 파일 %d번째 항목에 아이디 또는 비밀번호 해시가 없어 건너뜁니다.", where)
        return None
    if len(user) > MAX_USER_ID_LENGTH or any(ch < " " or ch == "\x7f" for ch in user):
        # 이 아이디는 그대로 `X-User` 헤더에 실린다(계약서 3장). 줄바꿈이 들어간 아이디를
        # 손으로 적어 두면 헤더를 쪼개는 값이 된다. 만드는 쪽(validate_user_id)에서 이미
        # 막지만, 파일을 직접 고칠 수 있으므로 읽는 쪽에서도 버린다.
        logger.warning("사용자 파일 %d번째 항목의 아이디에 쓸 수 없는 문자가 있어 건너뜁니다.", where)
        return None
    display_name = raw.get("display_name")
    role = raw.get("role")
    created_at = raw.get("created_at")
    active = raw.get("active")
    return UserRecord(
        user=user,
        display_name=display_name if isinstance(display_name, str) and display_name else user,
        role=role if isinstance(role, str) else "",
        password_hash=password_hash,
        created_at=created_at if isinstance(created_at, str) else "",
        # `active` 가 없으면 **활성**으로 본다. 사람이 손으로 적은 파일에서 흔한 누락이고,
        # 없다고 계정을 잠가 버리면 원인을 찾기 어렵다. 끄려면 명시적으로 false 를 적는다.
        active=True if active is None else bool(active),
    )


def load_users() -> list[UserRecord]:
    """등록된 사용자 목록. 파일이 없으면 빈 목록이다."""
    document = _read_document()
    records: list[UserRecord] = []
    for index, raw in enumerate(document.get("users", []), start=1):
        record = _record_from(raw, where=index)
        if record is not None:
            records.append(record)
    return records


def find_user(user: str) -> UserRecord | None:
    """아이디로 찾는다. 대소문자는 구분한다(저장된 문자열 그대로 비교)."""
    if not user:
        return None
    for record in load_users():
        if record.user == user:
            return record
    return None


# ---------------------------------------------------------------------------
# 세션 무효화 — 요청마다 «지금 파일»을 본다 (S3)
# ---------------------------------------------------------------------------
#
# 세션은 12시간짜리다. 그 사이에 계정을 끄거나 역할을 낮춰도 이미 발급된 세션에는
# 반영되지 않았다. 퇴사자의 브라우저가 반나절 동안 그대로 열려 있는 셈이다.
# 로그아웃도 브라우저 쿠키를 지울 뿐이라 서버가 아는 것이 없었다.
#
# 그래서 서명된 신원이 올 때마다 `users.json` 을 다시 본다. 파일을 매번 파싱하면
# 요청마다 디스크를 읽으므로, **mtime 과 크기가 그대로면 앞서 읽은 것을 쓴다.**
# 계정 관리는 사람이 가끔 하는 일이라 이 캐시는 거의 항상 적중한다.
_SNAPSHOT_LOCK = threading.Lock()
#: (mtime_ns, size, {아이디: 레코드}). 파일이 없으면 (None, None, {}).
_SNAPSHOT: tuple[int | None, int | None, dict[str, "UserRecord"]] | None = None


def _file_stamp() -> tuple[int | None, int | None]:
    try:
        stat = _users_path().stat()
    except OSError:
        return (None, None)
    return (stat.st_mtime_ns, stat.st_size)


def account_snapshot() -> dict[str, UserRecord]:
    """아이디 → 계정. `users.json` 이 바뀌었을 때만 다시 읽는다."""
    global _SNAPSHOT
    stamp = _file_stamp()
    with _SNAPSHOT_LOCK:
        cached = _SNAPSHOT
        if cached is not None and (cached[0], cached[1]) == stamp:
            return cached[2]
    # 파싱은 잠금 «밖»에서 한다 — 파일이 커도 다른 요청을 막지 않는다.
    # 같은 순간에 둘이 읽어 봐야 같은 결과이고, 나중 것이 캐시에 남는다.
    try:
        records = {record.user: record for record in load_users()}
    except UserStoreError:
        # 파일이 깨졌으면 「아무도 없다」로 본다. 여기서 예외를 올리면 **모든 요청**이
        # 500 이 된다 — 계정 파일 한 줄이 깨졌다고 서버 전체가 멈추면 안 된다.
        # 대신 아무도 통과하지 못하므로(아래 `live_role`) 조용히 열리지도 않는다.
        logger.warning("사용자 파일을 읽지 못해 이번 요청에서는 계정을 확인할 수 없습니다.")
        records = {}
    with _SNAPSHOT_LOCK:
        _SNAPSHOT = (stamp[0], stamp[1], records)
    return records


def clear_snapshot_cache() -> None:
    """캐시를 비운다 (테스트·계정 변경 직후)."""
    global _SNAPSHOT
    with _SNAPSHOT_LOCK:
        _SNAPSHOT = None


def display_name_of(user: str | None) -> str | None:
    """계정 아이디 → 화면에 적을 이름(45차 M11). 등록된 계정이면 표시 이름, 아니면(공용 계정 · 옛 기록 · 사람이 적은 이름) 받은 값 그대로.

    기록에는 아이디를 남기고(누가 했는가의 근거) 화면에만 이름을 쓴다 — 충돌 알림 · 「… 고침」 · 「열어 봄」에 아이디가 보였다."""
    if not user:
        return user
    record = account_snapshot().get(user)
    return record.display_name if record is not None and record.display_name.strip() else user


#: `live_role` 의 결과. 역할 문자열이거나, 통과시키면 안 되는 사유다.
LIVE_UNKNOWN = "unknown"
LIVE_INACTIVE = "inactive"


def live_role(user: str) -> str:
    """지금 파일 기준 역할. 계정이 없으면 `unknown`, 꺼져 있으면 `inactive`.

    공용 접근계정(`DEMO_USER`)은 `users.json` 에 없다 — 그쪽은 예전부터 있던 호환 계정이라
    관리자로 본다(계약서 §1). 같은 아이디가 파일에도 있으면 **파일이 이긴다.**
    """
    record = account_snapshot().get(user)
    if record is None:
        credentials = demo_credentials()
        if credentials is not None and credentials[0] == user:
            return "admin"
        return LIVE_UNKNOWN
    if not record.active:
        return LIVE_INACTIVE
    return record.role


def save_users(records: list[UserRecord]) -> Path:  # noqa: D401
    """사용자 목록을 통째로 다시 쓴다(임시 파일 → 교체).

    **이 함수는 잠그지 않는다.** 잠금은 `users_lock()` 으로 «읽고 고치고 쓰기» 전체를 감싸는
    쪽에 있다 (N5). 여기서만 잠그면 뜻이 없다 — 두 사람이 각자 옛 목록을 읽은 뒤 차례로
    쓰면, 쓰기가 아무리 안전해도 나중 것이 앞 것을 통째로 덮어쓴다. 실제로 그렇게 새는 것을
    테스트로 확인했다(먼저 만든 계정이 사라졌다).

    `locked()` 는 **재진입하지 않는다.** 그래서 여기서 또 잠그면 아래 `add_user` 류가
    자기 자신을 기다리다 실패한다. 원시 함수는 원시 함수로 둔다.
    """
    path = _users_path()
    document = _read_document()
    document["version"] = document.get("version", FILE_VERSION)
    document["users"] = [record.to_dict() for record in records]
    storage.write_json_atomic(path, document)
    _restrict_permissions(path)
    # 방금 바꾼 것이 다음 요청에 바로 보여야 한다 (S3). mtime 만 믿으면 같은 초에 두 번
    # 쓰는 경우를 놓칠 수 있다 — 쓴 쪽에서 직접 비운다.
    clear_snapshot_cache()
    return path


def users_lock():
    """계정 파일의 «읽고 고치고 쓰기»를 감싸는 잠금 (N5).

        with user_service.users_lock():
            records = user_service.load_users()
            ...
            user_service.save_users(records)

    계정 관리는 사람이 가끔 하는 일이지만, 여러 명을 한 번에 넣을 때 창 두 개를 띄워 돌리는
    일이 실제로 있다. 그때 잠그지 않으면 먼저 만든 계정이 **말없이 사라진다** — 파일이
    깨지지 않으니 그 사람은 로그인이 안 되는 이유를 비밀번호에서 찾는다.
    """
    return storage.locked(_users_path())


def _restrict_permissions(path: Path) -> None:
    """가능하면 주인만 읽게 한다(0600). 해시가 든 파일이다.

    Windows 에서는 이 호출이 사실상 아무것도 하지 않는다. 실패해도 저장은 성공이다.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - 플랫폼·파일시스템에 따라 다르다
        logger.debug("사용자 파일 권한을 좁히지 못했습니다: %s", path.name)


# ---------------------------------------------------------------------------
# 공용 데모 계정(DEMO_USER / DEMO_PASSWORD) 호환
# ---------------------------------------------------------------------------


def demo_credentials() -> tuple[str, str] | None:
    """환경변수의 공용 계정. 둘 다 있어야 켜진다(프런트엔드 `demoAuth.credentials()` 와 같은 규칙).

    값을 다듬지 않는 것도 프런트엔드와 같다 — 한쪽만 공백을 잘라 내면 같은 비밀번호가
    한쪽에서만 통과한다.

    **환경변수만 본다.** 배포 서버는 systemd `EnvironmentFile=.../.env` 로 이 값을 실제
    환경변수로 넣어 준다(docs/deploy_backend.md). `.env` 파일만 두고 환경변수로 넣지 않는
    로컬에서는 이 호환 계정이 꺼진 상태가 된다.
    """
    user = os.environ.get("DEMO_USER") or ""
    password = os.environ.get("DEMO_PASSWORD") or ""
    if not user or not password:
        return None
    return user, password


def demo_account_enabled() -> bool:
    """공용 데모 계정이 켜져 있는지. **값은 돌려주지 않는다.**"""
    return demo_credentials() is not None


def _demo_outcome(user: str, password: str) -> AuthOutcome | None:
    """공용 계정으로 인정되면 결과를, 아니면 None(다음 판단으로 넘긴다)."""
    credentials = demo_credentials()
    if credentials is None:
        return None
    expected_user, expected_password = credentials
    user_ok = hmac.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
    password_ok = hmac.compare_digest(password.encode("utf-8"), expected_password.encode("utf-8"))
    if user_ok and password_ok:
        # 표시이름은 아이디를 그대로 쓴다. 공용 계정에는 사람 이름이 없다.
        return AuthOutcome(AuthenticatedUser(expected_user, expected_user, "admin", "demo"), "ok")
    return None


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------


def authenticate(user: str, password: str) -> AuthOutcome:
    """아이디·비밀번호를 판정한다. **users.json 이 환경변수 공용 계정보다 이긴다**(계약서 1장).

    실패는 전부 `account=None` 이다. 왜 실패했는지는 `reason` 으로만 알린다.
    """
    if not isinstance(user, str) or not isinstance(password, str):
        return AuthOutcome(None, "invalid_input")
    if not user or not password or len(password) > MAX_PASSWORD_LENGTH:
        # 빈 비밀번호는 해시가 무엇이든 통과시키지 않는다(깨진 항목이 뒷문이 되지 않게).
        # 계정을 찾아보기 **전**이라 아이디가 있는지 모른다 — 사유를 `invalid_input` 으로 두어
        # 호출자가 아이디를 로그에 남기지 않게 한다.
        return AuthOutcome(None, "invalid_input")

    record = find_user(user)
    if record is not None:
        if not verify_password(password, record.password_hash):
            return AuthOutcome(None, "wrong_password")
        if not record.active:
            return AuthOutcome(None, "inactive")
        if record.role not in ROLES:
            # 역할이 셋 중 하나가 아니면 백엔드 신원 검사가 어차피 401 을 준다(계약서 4장).
            # 여기서 통과시키면 「로그인은 됐는데 아무것도 안 되는」 상태가 된다.
            logger.warning("사용자 %s 의 역할이 올바르지 않아 로그인을 거부했습니다.", record.user)
            return AuthOutcome(None, "invalid_role")
        return AuthOutcome(
            AuthenticatedUser(record.user, record.display_name, record.role, "file"), "ok"
        )

    demo = _demo_outcome(user, password)
    if demo is not None:
        return demo

    _equalize_timing()
    return AuthOutcome(None, "no_such_user")


# ---------------------------------------------------------------------------
# 관리 (scripts/manage_users.py 가 쓴다)
# ---------------------------------------------------------------------------


def validate_user_id(user: str) -> str:
    """새 아이디 형식 검사. 파일명으로 쓰지는 않지만 로그·헤더에 그대로 실린다."""
    if not isinstance(user, str) or not USER_ID_PATTERN.match(user):
        raise UserError(
            "아이디는 영문 소문자·숫자로 시작하고 2~32자여야 합니다(소문자·숫자·`.`·`_`·`-` 만)."
        )
    return user


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise UserError(f"역할은 {', '.join(ROLES)} 중 하나여야 합니다.")
    return role


def validate_password(password: str) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise UserError(f"비밀번호는 {MAX_PASSWORD_LENGTH}자 이하여야 합니다.")
    return password


def add_user(
    user: str, password: str, *, role: str = DEFAULT_ROLE, display_name: str | None = None
) -> UserRecord:
    """새 계정을 만든다. 같은 아이디가 있으면 거부한다(덮어쓰지 않는다)."""
    validate_user_id(user)
    validate_role(role)
    validate_password(password)
    # 「이미 있는가」를 읽어서 판정하므로, 그 사이에 다른 쪽이 같은 아이디를 넣으면 둘 다
    # 통과한다. 읽기부터 쓰기까지 한 잠금 안에 둔다 (N5).
    with users_lock():
        records = load_users()
        if any(record.user == user for record in records):
            raise UserError(f"이미 있는 아이디입니다: {user}")
        record = UserRecord(
            user=user,
            display_name=(display_name or user).strip() or user,
            role=role,
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc).isoformat(),
            active=True,
        )
        records.append(record)
        save_users(records)
    return record


def set_password(user: str, password: str) -> UserRecord:
    """비밀번호만 바꾼다. 역할·표시이름·생성 시각은 그대로 둔다."""
    validate_password(password)
    with users_lock():
        records = load_users()
        updated: UserRecord | None = None
        for index, record in enumerate(records):
            if record.user == user:
                updated = UserRecord(
                    user=record.user,
                    display_name=record.display_name,
                    role=record.role,
                    password_hash=hash_password(password),
                    created_at=record.created_at,
                    active=record.active,
                )
                records[index] = updated
                break
        if updated is None:
            raise UserError(f"없는 아이디입니다: {user}")
        save_users(records)
    return updated


def set_role(user: str, role: str) -> UserRecord:
    """역할만 바꾼다(44차 OPS-07 — 예전에는 JSON 을 손으로 고쳤다). 비밀번호 · 표시이름 · 상태는 그대로."""
    role = validate_role(role)
    with users_lock():
        records = load_users()
        updated: UserRecord | None = None
        for index, record in enumerate(records):
            if record.user == user:
                updated = UserRecord(
                    user=record.user,
                    display_name=record.display_name,
                    role=role,
                    password_hash=record.password_hash,
                    created_at=record.created_at,
                    active=record.active,
                )
                records[index] = updated
                break
        if updated is None:
            raise UserError(f"없는 아이디입니다: {user}")
        save_users(records)
    return updated


def set_active(user: str, active: bool) -> UserRecord:
    """계정을 끄거나 켠다. 기록은 지우지 않는다 — 누가 있었는지는 남아야 한다."""
    with users_lock():
        records = load_users()
        updated: UserRecord | None = None
        for index, record in enumerate(records):
            if record.user == user:
                updated = UserRecord(
                    user=record.user,
                    display_name=record.display_name,
                    role=record.role,
                    password_hash=record.password_hash,
                    created_at=record.created_at,
                    active=active,
                )
                records[index] = updated
                break
        if updated is None:
            raise UserError(f"없는 아이디입니다: {user}")
        save_users(records)
    return updated
