"""파일 기반 JSON 저장소 공통 규칙.

지금은 `data/` 아래 JSON 파일이 저장소다 (docs/data_model.md). PostgreSQL로 옮길 때
서비스 코드가 바뀌지 않도록, 파일을 직접 만지는 규칙을 여기 한 곳에 모은다.

규칙
- **원자적 쓰기**: 임시 파일에 쓴 뒤 `os.replace`로 바꿔치기한다. 조회 중 잘린 JSON을 읽지 않는다.
- **읽기-수정-쓰기는 잠근다**: 원자적 쓰기는 «반쪽 파일»만 막는다. 두 사람이 같은 체크리스트에
  항목을 하나씩 더하면 둘 다 옛 목록을 읽고 각자 한 건만 더해 쓰므로, 나중 쓰기가 앞 것을
  통째로 지운다. 파일이 깨지지 않아서 **아무도 모른다.** `locked(path)` 로 감싼다 (ISSUE-032).
- **깨진 파일 격리**: JSON 파싱에 실패하면 원본을 `.corrupt-<시각>`으로 옮겨 두고
  `CorruptJsonError`를 올린다. 조용히 덮어써서 사용자 기록을 잃지 않는다.
- **schema_version**: 새로 쓰는 문서에는 버전을 찍는다. 읽는 쪽은 버전을 보고 마이그레이션한다.
- **시각은 항상 tz-aware UTC**: naive datetime을 저장하지 않는다.
- **id 검증**: 파일명으로 쓰는 id는 경로 이동 문자를 허용하지 않는다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import re
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA_ROOT

# data/ 아래 JSON 문서의 현재 스키마 버전. 항목 유형(item_type)이 들어간 버전이 2다.
SCHEMA_VERSION = 2

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


class CorruptJsonError(RuntimeError):
    """JSON 파일이 깨져 있어 읽지 못했다. 원본은 `.corrupt-*`로 옮겨 두었다."""

    def __init__(self, path: Path, quarantined: Path | None) -> None:
        self.path = path
        self.quarantined = quarantined
        where = f" (원본 보관: {quarantined.name})" if quarantined else ""
        super().__init__(f"JSON 파일을 읽지 못했습니다: {path.name}{where}")


class InvalidIdError(ValueError):
    """저장 경로로 쓸 수 없는 id."""


class StaleWriteError(RuntimeError):
    """처음 읽은 뒤 다른 사람이 먼저 저장했다(43차 M25) — 나중 저장이 앞 저장을 말없이 되돌리지 않게 409 로 막는다."""

    def __init__(self, by: str | None, at: datetime | None) -> None:
        self.by = by
        self.at = at
        when = at.astimezone(KST).strftime("%m/%d %H:%M") if at else "방금"
        # 45차 M11 — 아이디가 아니라 표시 이름(머리의 「촬영 관리자」와 같은 이름). 계정 파일을 못 읽어도 알림은 낸다.
        try:
            from app.services import user_service

            shown = user_service.display_name_of(by)
        except Exception:  # noqa: BLE001
            shown = by
        who = f"{shown} 님이" if shown else "다른 사람이"
        super().__init__(f"{who} {when}에 먼저 바꿨습니다 — 다시 불러온 뒤 저장하세요(지금 쓴 내용은 화면에 그대로 있습니다).")


def ensure_unchanged(stored_at: datetime | None, expected_at: datetime | None, *, stored_by: str | None = None) -> None:
    """처음 읽은 시각(`expected_at`)과 지금 저장된 시각이 다르면 `StaleWriteError`. 둘 다 없으면(처음 저장) 통과."""
    if stored_at != expected_at:
        raise StaleWriteError(stored_by, stored_at)


def utc_now() -> datetime:
    """**이 저장소가 읽는 「지금」은 여기 하나다** (ISSUE-118 · ISSUE-133).

    판정에 쓰는 시각을 모듈마다 `datetime.now()` 로 읽으면, 두 경로가 날짜 경계에서
    갈린다. 실제로 두 번 났다 — 14차는 캐시 신선도와 테스트가 갈렸고(ISSUE-118),
    17차는 **목록과 상세가 갈렸다**(ISSUE-133): 목록은 주입된 시계로 메모 열쇠에
    `today` 를 넣는데 상세는 `datetime.now()` 로 만들어, 9-22 부터 상세가 목록 메모를
    못 찾고 다시 계산했다(48 ≠ 7). 9-21 에는 두 날짜가 같아 통과했다.

    그래서 「지금」을 뜻하는 자리는 전부 이 함수를 지난다. 테스트는 여기만 갈아 끼우면
    되고(`monkeypatch.setattr(storage, "utc_now", ...)`), `--timeshift-days` 도 여기만
    앞당긴다. 기록용 시각(생성 시각·파일명·로그)은 대상이 아니다 — 아무도 견주지 않는다.
    """
    return datetime.now(timezone.utc)


#: 이 시스템의 «업무 날짜»는 한국 시간이다. 공고 마감·서류 유효기간은 전부 KST 기준으로 적혀 있다.
KST = timezone(timedelta(hours=9))


def kst_today() -> date:
    """오늘 날짜(한국 시간) (ISSUE-042 · TASK-020).

    `date.today()` 는 **서버의 로컬 시간대**를 쓴다. UTC 로 도는 서버에서는 KST 기준
    하루 전 날짜가 나오고, 그래서 어제 만료된 서류가 다음 날 09:00 KST 까지 「유효」로
    판정됐다. 담당자가 보는 날짜와 시스템이 판정하는 날짜가 다르면, 그 판정은
    설명할 수 없는 값이 된다.

    화면의 D-day 는 이미 KST 로 계산하고 있었다 — 여기만 어긋나 있었다.

    「지금」은 `utc_now()` 에서 받는다 (ISSUE-133). 여기서 `datetime.now` 를 따로 읽으면
    시계를 갈아 끼운 테스트가 「지금」과 「오늘」을 서로 다른 날로 보게 된다.
    """
    return utc_now().astimezone(KST).date()


def ensure_aware(moment: datetime) -> datetime:
    """naive datetime은 UTC로 간주해 tz를 붙인다 (저장 전 정규화)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def safe_id(value: str, *, what: str = "id") -> str:
    """파일명으로 쓸 수 있는 id만 통과시킨다 (경로 이동 차단)."""
    if not _SAFE_ID_RE.match(value or ""):
        raise InvalidIdError(f"허용되지 않는 {what}입니다: {value!r}")
    return value


# ---------------------------------------------------------------------------
# 파일 잠금 (ISSUE-032)
# ---------------------------------------------------------------------------
#
# 잠금 파일을 «대상 파일 옆»에 두지 않는다. `data/public/` 아래는 git 이 추적하므로
# `*.lock` 이 생기면 작업 트리가 더러워지고, 시연 전에 `git status` 를 보는 사람이
# 그것을 무언가 고장난 신호로 읽는다. 그래서 gitignore 아래 한 곳에 모은다.
#
# 대상 파일 «자체»를 잠그지 않는 이유는 따로 있다. 윈도우에서는 열려 있는 파일을
# `os.replace` 로 덮어쓸 수 없다 — 원자적 쓰기가 바로 그 `os.replace` 다.
LOCK_DIR = DATA_ROOT / "private" / ".locks"

#: 같은 프로세스 안의 스레드끼리도 막아야 한다. OS 파일 잠금은 «프로세스» 단위라
#: 한 프로세스의 두 스레드가 서로를 막지 못한다 (윈도우 `msvcrt` 는 같은 프로세스의
#: 두 번째 잠금을 그냥 통과시킨다). 지금 실제로 겹치는 것도 스레드 쪽이다 — 무거운
#: 작업을 스레드풀로 넘기면서 생긴 경로다.
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()

#: 잠금을 기다리는 최대 시간(초). 넘으면 예외를 올린다 — 조용히 덮어쓰는 것보다 낫다.
LOCK_TIMEOUT_SECONDS = 15.0
_LOCK_POLL_SECONDS = 0.02


class LockTimeoutError(RuntimeError):
    """다른 쪽이 같은 파일을 너무 오래 잡고 있다. 덮어쓰지 않고 실패한다."""


def _thread_lock_for(key: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _lock_path(path: Path) -> Path:
    """대상 경로 하나당 잠금 파일 하나. 경로 해시로 이름을 만든다.

    파일명을 그대로 쓰지 않는 이유: 서로 다른 조직 폴더에 같은 이름의 파일이 있다
    (`org-a/.../actions.json` 과 `org-b/.../actions.json`). 이름만 쓰면 둘이 한 잠금을
    공유해 서로를 막는다 — 틀리지는 않지만 느려지고, 왜 느린지 알기 어렵다.
    """
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
    return LOCK_DIR / f"{path.name}.{digest}.lock"


def _try_os_lock(handle) -> bool:
    """이 핸들에 배타 잠금을 걸어 본다. 이미 잠겨 있으면 False (기다리지 않는다)."""
    try:
        import fcntl  # POSIX
    except ImportError:
        import msvcrt  # Windows

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release_os_lock(handle) -> None:
    try:
        import fcntl  # POSIX
    except ImportError:
        import msvcrt  # Windows

        with contextlib.suppress(OSError):
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    with contextlib.suppress(OSError):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """`path` 에 대한 읽기-수정-쓰기를 한 번에 하나만 하게 한다.

        with storage.locked(checklist):
            items = storage.read_json(checklist, default=[])
            items.append(new_item)
            storage.write_json_atomic(checklist, items)

    **읽기까지 감싸야 뜻이 있다.** 쓰기만 감싸면 두 쪽이 같은 옛 목록을 읽고 각자
    한 건만 더한 목록을 순서대로 쓰므로, 나중 쓰기가 앞 것을 지운다.

    잠금을 얻지 못하면 `LockTimeoutError`. 기다리다 포기하고 덮어쓰지 않는다 —
    사용자가 방금 저장한 것이 말없이 사라지는 쪽이 더 나쁘다.
    """
    key = str(path)
    thread_lock = _thread_lock_for(key)
    deadline = time.monotonic() + timeout
    if not thread_lock.acquire(timeout=max(0.0, timeout)):
        raise LockTimeoutError(f"다른 작업이 같은 파일을 쓰고 있습니다: {path.name}")
    handle = None
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock_file = _lock_path(path)
        # "a+b" 는 파일이 없으면 만들고, 있으면 내용을 지우지 않는다.
        handle = open(lock_file, "a+b")  # noqa: SIM115 — finally 에서 닫는다
        if handle.seek(0, os.SEEK_END) == 0:
            # msvcrt 는 «있는 바이트»를 잠근다. 빈 파일이면 잠글 것이 없다.
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        while not _try_os_lock(handle):
            if time.monotonic() >= deadline:
                raise LockTimeoutError(f"다른 프로세스가 같은 파일을 쓰고 있습니다: {path.name}")
            time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _release_os_lock(handle)
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()
        thread_lock.release()


def read_json(path: Path, *, default: Any = None, quarantine: bool = True) -> Any:
    """JSON 파일을 읽는다. 없으면 default. 깨졌으면 격리하고 CorruptJsonError.

    `quarantine=False` 는 깨진 파일을 옮기지 않고 CorruptJsonError 만 낸다(2.0.6) — 오류를 삼키는 곁 읽기(브리핑 수 세기)가
    먼저 옮겨 버리면, 정작 그 파일의 화면은 409 사유 없이 「파일 없음」(처음 목록)을 보고 그 위에 저장했다.
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        quarantined: Path | None = None
        if not quarantine:
            raise CorruptJsonError(path, None) from exc
        try:
            stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
            quarantined = path.with_name(f"{path.name}.corrupt-{stamp}")
            os.replace(path, quarantined)
        except OSError:
            quarantined = None
        raise CorruptJsonError(path, quarantined) from exc


def write_json_atomic(path: Path, payload: Any, *, compact: bool = False) -> Path:
    """임시 파일에 쓴 뒤 교체한다. 부모 디렉터리는 만든다.

    `compact=True` 는 들여쓰기를 뺀다. 사람이 읽을 일이 없고 **덩치가 문제가 되는**
    파일에만 쓴다 — 자격 저장소(0922 §4-A-2)가 그렇다: 들여쓰기가 파일의 3분의 1이다.

    임시 파일은 **처음부터 0600 으로 연다** (S10). 여기를 지나가는 것 중에는
    `users.json`(비밀번호 해시)처럼 주인만 읽어야 하는 파일이 있다. 예전에는 기본
    umask 로 만든 뒤 `os.replace` 다음에야 권한을 좁혀서, 그 사이 아주 짧은 동안
    같은 서버의 다른 계정이 읽을 수 있었다. 윈도우에서는 이 비트가 사실상 무시되지만
    (ACL 을 쓴다), 리눅스 사내 서버가 실제 배포 대상이다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # 같은 파일을 동시에 쓰더라도 임시 파일이 겹치지 않게 pid **와 thread id** 를 붙인다.
    #
    # pid 만으로는 부족하다: 무거운 작업을 스레드풀로 넘기면서(ISSUE-031) 한 프로세스
    # 안에서도 두 스레드가 같은 파일을 쓸 수 있게 됐다. 이름이 겹치면 한쪽이 쓰는 중에
    # 다른 쪽이 `replace` 해 버려 `FileNotFoundError` 가 나거나 내용이 섞인다 (ISSUE-032).
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    text = json.dumps(
        payload, ensure_ascii=False, **({"separators": (",", ":")} if compact else {"indent": 2})
    )
    # O_EXCL 은 쓰지 않는다 — 같은 pid·스레드가 앞서 죽으며 남긴 파일이 있으면 그것을 덮어써야 한다.
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    except BaseException:
        # 반쪽 임시 파일을 남기지 않는다. 지우기에 실패해도 원래 예외를 가리지 않는다.
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    os.replace(tmp, path)
    return path


def stamp(payload: dict[str, Any], *, schema_version: int = SCHEMA_VERSION) -> dict[str, Any]:
    """저장 직전에 버전과 갱신 시각을 찍는다 (원본 dict를 그대로 수정해 돌려준다)."""
    payload["schema_version"] = schema_version
    payload["updated_at"] = utc_now().isoformat()
    return payload


def schema_version_of(payload: Any) -> int:
    """문서의 schema_version. 없으면 1 (항목 유형 이전 형식)."""
    if isinstance(payload, dict):
        raw = payload.get("schema_version")
        if isinstance(raw, int) and raw >= 1:
            return raw
    return 1


#: 새로 받은 건수가 기존의 이 비율 아래면 **저장하지 않는다** (ISSUE-121).
#: 절반으로 잡은 이유: 마감으로 자연히 줄어드는 폭은 하루에 몇 %이고, 사고 때는
#: 1,620 → 100(6%)이었다. 그 사이는 넓어서 정상적인 감소를 막지 않는다.
CACHE_SHRINK_FLOOR: float = 0.5


def cache_shrink_reason(
    *, existing: int, incoming: int, allow_shrink: bool | None = None
) -> str | None:
    """캐시를 **크게 줄이는 저장**인가. 막아야 하면 사람이 읽는 사유, 아니면 None.

    ## 왜 이것이 있나

    13차에 기업마당 목록 조회가 100건만 받아 와 1,620건짜리 캐시를 덮었다. 파일이 깨진
    것이 아니라 **정상적으로** 쓰였기 때문에 아무도 몰랐고, 그 캐시는 gitignore 아래라
    되돌릴 수도 없었다. 11차에도 같은 모양으로 기준 답안 두 건이 영구히 사라졌다.

    목록이 절반 아래로 줄어드는 것은 거의 언제나 「덜 받아 온 것」이지 「그만큼밖에 없는
    것」이 아니다 — 조회 실패·부분 응답·인자 실수. **의심스러우면 옛것을 지킨다.**
    실제로 줄어든 것이 맞으면 담당자가 `CACHE_ALLOW_SHRINK=1` 로 켜거나 스크립트가
    `--force` 를 준다.

    빈 캐시(기존 0건)에는 걸리지 않는다 — 처음 받는 것을 막을 이유가 없다.
    0건을 받아 온 것은 **언제나** 막는다(기존이 있는 한). 그것이 가장 흔한 실패 모양이다.
    """
    if allow_shrink is None:
        from app.core.config import get_settings

        allow_shrink = bool(get_settings().cache_allow_shrink)
    if allow_shrink or existing <= 0:
        return None
    if incoming >= existing * CACHE_SHRINK_FLOOR:
        return None
    return (
        f"받은 건수 {incoming:,} < 기존 {existing:,} 의 절반 — 저장하지 않음 "
        "(맞는 감소면 서버 관리자가 감소 허용 설정으로 다시 받는다)"  # 설정 이름은 화면에 적지 않는다(27차 §3-H)
    )
