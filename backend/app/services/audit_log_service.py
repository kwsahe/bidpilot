"""활동 기록 — 누가 무엇을 바꿨는지 한 줄씩 남긴다 (계약서 6장).

왜 남기는가
----------
사내에서 여러 사람이 같은 회사자료를 고치기 시작하면, 「이 항목을 언제 누가 지웠나」를
물어볼 곳이 필요하다. 결과 파일에는 최종 상태만 남고 그 전에 무슨 일이 있었는지는 남지 않는다.

무엇을 남기지 않는가
------------------
**본문·쿼리 문자열·헤더 값은 절대 남기지 않는다.** 이 시스템의 요청 본문에는 회사자료와
비밀번호·토큰이 실릴 수 있다. 남기는 것은 「누가·언제·어떤 메서드로·어느 경로를·어느 조직에서
불렀고 결과가 몇 번이었나」뿐이다. 조직 id 는 파일 이름으로 쓰는 안전한 식별자만 받는다.

왜 JSONL 인가
------------
한 줄이 한 사건이라 **덧붙이기만** 하면 된다. 기존 JSON 저장소(`storage.write_json_atomic`)처럼
통째로 읽고 다시 쓰면 기록이 쌓일수록 느려지고, 동시에 두 요청이 쓰면 하나가 사라진다.

기록은 **부가 기능**이다. 파일을 쓰지 못해도(권한 없음·디스크 가득) 요청은 그대로 성공해야 한다.
기록 때문에 담당자의 작업이 실패하는 것이 더 나쁘다.

왜 스레드풀로 감싸지 않는가
--------------------------
`append` 는 async 미들웨어 안에서 **동기 파일 쓰기**를 한다. 이 저장소는 예전에 블로킹
호출이 이벤트 루프를 잡아 `/health` 가 늦어진 적이 있어서 한 번 재 봤다(2026-09-17 실측).

    500줄 쓰기 110ms → 한 줄 평균 0.22ms
    501줄 파일에서 최근 20줄 읽기 0.64ms (뒤에서부터 읽는다)

이 앱의 가장 빠른 엔드포인트도 ms 단위라 0.22ms 를 스레드풀로 넘기는 비용이 더 크다.
파일이 아주 커지거나 기록 대상이 늘면 다시 재 볼 것.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA_ROOT

logger = logging.getLogger(__name__)

# `data/private/` 는 통째로 gitignore 아래다 (계약서 7장 — 기록을 커밋하지 않는다).
AUDIT_LOG_FILE = DATA_ROOT / "private" / "audit_log.jsonl"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# 회전 (S9). 기록은 **로그인 시도까지** 한 줄씩 남기므로 가만히 둬도 계속 자란다.
# `data/private/` 는 gitignore 아래라 `git status` 에도 안 보이고, 백업 대상이라
# 누군가 알아차릴 때쯤이면 이미 수백 MB 다.
#
# 5MB 씩 5벌 = 최대 약 30MB. 한 줄이 200바이트 안팎이니 5MB 는 대략 2만 5천 건이고,
# 다섯 벌이면 12만 건 남짓 — 사내 도구 규모에서는 몇 달치다.
# 크기로 자르는 이유: 날짜로 자르면 조용한 날과 바쁜 날의 파일 크기가 백 배 차이 난다.
MAX_BYTES = 5 * 1024 * 1024
MAX_BACKUPS = 5

# 조직 id 는 저장 경로에 쓰이는 값이라 이미 이 형식으로 제한돼 있다(`core/storage.safe_id`).
# 기록에도 같은 잣대를 적용한다 — 형식에서 벗어난 값은 기록하지 않고 null 로 둔다.
_SAFE_ORG_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# 한 프로세스 안에서 두 요청이 동시에 덧붙이는 것을 막는다. 여러 프로세스로 띄우면
# O_APPEND 의 성질에 기댄다(짧은 한 줄은 쪼개지지 않는다).
_LOCK = threading.Lock()


def sanitize_organization_id(value: str | None) -> str | None:
    """기록에 넣어도 되는 조직 id 만 통과시킨다. 아니면 None(=「없음」)."""
    candidate = (value or "").strip()
    if not candidate or not _SAFE_ORG_ID.match(candidate):
        return None
    return candidate


def append(
    *,
    user: str,
    role: str,
    method: str,
    path: str,
    organization_id: str | None,
    status: int,
    when: datetime | None = None,
    event: dict[str, str | int | None] | None = None,
) -> bool:
    """한 줄 덧붙인다. 성공하면 True, 실패해도 예외를 올리지 않고 False.

    호출하는 쪽(미들웨어)은 반환값을 보지 않아도 된다. 실패는 서버 로그에만 남긴다.

    `event` 는 **서비스가 남기는 사건**(조항 확인 · 목록 재수집 — 20차)의 짧은 요약이다. 식별자·상태·
    건수만 넣는다 — 메모·본문은 넣지 않는다(위 「무엇을 남기지 않는가」). 미들웨어 줄에는 없다.
    """
    moment = when or datetime.now(timezone.utc)
    entry: dict[str, Any] = {
        "ts": moment.isoformat(),
        "user": user,
        "role": role,
        "method": method,
        "path": path,
        "organization_id": sanitize_organization_id(organization_id),
        "status": status,
    }
    if event:
        entry["event"] = event
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    try:
        with _LOCK:
            AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed()
            # 처음 만들 때 0600 으로 연다 (N4). 이 파일에는 누가 언제 무엇을 했는지가 들어 있어
            # 같은 서버의 다른 계정이 읽을 이유가 없다. 이미 있는 파일의 권한은 바꾸지 않는다 —
            # 운영자가 일부러 넓혀 둔 것을 되돌리면 그쪽이 놀란다.
            descriptor = os.open(AUDIT_LOG_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(line)
        return True
    except Exception as exc:  # noqa: BLE001 — 기록 실패가 요청을 죽이면 안 된다(계약서 6장)
        # 디스크·권한 문제(OSError)가 대부분이지만 무엇이 나오든 삼킨다. 이 함수는 요청 처리의
        # `finally` 에서 불리므로, 여기서 예외가 올라가면 «원래 오류»까지 가려 버린다.
        # 실패 사유(예외 이름)만 남긴다 — 기록 내용(경로·사용자)을 다시 로그로 복사하지 않는다.
        logger.warning("활동 기록을 쓰지 못했습니다: %s", exc.__class__.__name__)
        return False


def _rotate_if_needed() -> None:
    """기록이 `MAX_BYTES` 를 넘으면 `.1` ~ `.5` 로 밀어내고 새 파일을 연다 (S9).

    **`_LOCK` 을 쥔 채로만 부른다.** 이름을 밀어내는 동안 다른 스레드가 쓰면 그 줄이
    옛 파일로 들어간다.

    가장 오래된 벌(`.5`)은 **버린다.** 영원히 남기지 않는 것이 여기서는 맞다 —
    이 파일에는 「누가 언제 무엇을 했는가」가 들어 있어 보존 자체가 개인정보 부담이다.
    더 오래 보관해야 하면 백업으로 떠 두는 것이 옳고, 그 판단은 사람이 한다.

    회전에 실패해도 조용히 넘어간다. 부르는 쪽이 이미 예외를 삼키지만, 여기서 실패해
    기록 한 줄을 못 쓰는 것보다 파일이 조금 큰 채로 계속 쓰는 편이 낫다.
    """
    try:
        if not AUDIT_LOG_FILE.exists() or AUDIT_LOG_FILE.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return
    try:
        oldest = AUDIT_LOG_FILE.with_name(f"{AUDIT_LOG_FILE.name}.{MAX_BACKUPS}")
        if oldest.exists():
            oldest.unlink()
        for index in range(MAX_BACKUPS - 1, 0, -1):
            source = AUDIT_LOG_FILE.with_name(f"{AUDIT_LOG_FILE.name}.{index}")
            if source.exists():
                os.replace(source, AUDIT_LOG_FILE.with_name(f"{AUDIT_LOG_FILE.name}.{index + 1}"))
        os.replace(AUDIT_LOG_FILE, AUDIT_LOG_FILE.with_name(f"{AUDIT_LOG_FILE.name}.1"))
    except OSError as exc:
        logger.warning("활동 기록을 회전하지 못했습니다: %s", exc.__class__.__name__)


def read_recent(limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """최신순 N줄. 파일이 없으면 빈 목록이고 오류가 아니다.

    파일 전체를 읽지 않는다. 기록은 계속 자라기만 하는 파일이라, 20행짜리 표를 그리려고
    수십 MB 를 메모리에 올릴 이유가 없다. 끝에서부터 블록 단위로 거슬러 읽는다.
    """
    count = max(1, min(limit, MAX_LIMIT))
    entries: list[dict[str, Any]] = []
    for line in reversed(_tail_lines(AUDIT_LOG_FILE, count)):
        parsed = _parse_line(line)
        if parsed is not None:
            entries.append(parsed)
    return entries


def _parse_line(line: str) -> dict[str, Any] | None:
    """깨진 줄은 조용히 버린다 — 한 줄 때문에 「최근 활동」 화면 전체가 죽지 않게."""
    text = line.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tail_lines(path: Path, count: int) -> list[str]:
    """파일 끝에서 최대 `count` 줄. 앞에서부터 읽지 않는다."""
    block = 64 * 1024
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            data = b""
            # 줄바꿈이 count 개를 넘길 때까지(=완전한 줄 count 개가 확보될 때까지) 거슬러 읽는다.
            while end > 0 and data.count(b"\n") <= count:
                start = max(0, end - block)
                handle.seek(start)
                data = handle.read(end - start) + data
                end = start
    except FileNotFoundError:
        return []
    except OSError as exc:
        # 읽기 실패도 화면에서는 「기록 없음」으로 보인다. 사유는 서버 로그에만 남는다.
        logger.warning("활동 기록을 읽지 못했습니다: %s", exc.__class__.__name__)
        return []
    # 블록 경계에서 한글이 반토막 날 수 있다. 그 반토막은 «맨 앞 줄»에만 생기고,
    # 그 줄은 아래 슬라이스에서 버려진다(줄이 count 개를 넘겨야 반복이 끝나므로).
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-count:]
