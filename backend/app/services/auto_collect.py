"""매일 자동 받기(`scripts/collect_daily.py` · 예약 작업)의 받은 때 한 줄 · 「하루 한 번」 판단 · 받기 잠금 (38차 §3-C-4 · 39차 §3-F-2 · 40차 D28 · D29 · D30).

화면이 「새 공고 받기 꺼짐」만 적으면, 자동 받기가 매일 도는데도 「받지 않는다」로 읽혔다(recheck30 §4-3).
고정 모드는 「화면에서 바로 받지 않는다」는 뜻이고, 목록은 예약 작업이 받는다 — 그 사실을 로그에서 읽어 함께 보인다.

40차(담당자 결정 3 · D30 · 「켤 때 받기」): 이 PC 는 노트북이고 늘 켜 두지 않는다 — 로그 11번 중 07:30 에 돈 날은 0 이었다. 그래서
예약 작업은 **로그인 · 잠금 해제 · (켜져 있으면) 07:30** 에 돌고, `collect_daily.py` 가 **하루 한 번**만 받는다(`daily_gate`).
화면 글은 한 함수(`collect_state`)가 정한다 — 대시보드 · 사업기회 · 레이더 · 브리핑 · 엑셀이 같은 글을 쓴다(두 말 없음).
「늦게 받음」 · 07:30~08:00 「제때」 구분은 없앴다(39차 · 07:30 을 기준으로 삼던 것).

로그(`data/private/logs/collect_daily.log`)는 실행마다 JSON 한 줄이다. **읽기만 한다.** 잠금(`collect_daily.lock`)은 `collect_daily.py` 가 만들고 지운다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time as _time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from typing import Any

from app.core.paths import DATA_ROOT

LOG_FILE = DATA_ROOT / "private" / "logs" / "collect_daily.log"
#: 받기 잠금(40차 D29) — 예약 작업 · 지금 받기 둘 다 지나는 `collect_daily.py` 가 O_EXCL 로 만든다(pid · 시작 시각).
LOCK_FILE = DATA_ROOT / "private" / "logs" / "collect_daily.lock"
#: 이보다 오래된 잠금은 죽은 것으로 보고 넘긴다(한 번 받는 데 길어야 몇 분 · 예약 작업 시간 상한 1시간).
LOCK_STALE = timedelta(hours=2)
#: 이 안의 성공이면 응답 `auto_collect_at` 에 싣는다(옛 화면 · 시험 호환 — 화면 글은 `collect_state` 가 정한다).
FRESH_HOURS = 48
#: 끝에서부터 처음 볼 바이트. 그 안에 성공 줄이 없으면 앞으로 이어 읽어 파일 처음까지 본다(39차 §3-F-4).
_TAIL_BYTES = 64_000
KST = timezone(timedelta(hours=9))
#: 받은 때 경고의 「지금 받기」 파일(두 번 누르면 하루 한 번 검사를 건너뛰고 받는다 · 39차 §3-F-3 · 40차 `--force`).
COLLECT_NOW_FILE = r"scripts\지금_받기.bat"
#: 회사 서버(42차 · Linux) 는 예약 작업 대신 cron 이 받는다 — `COLLECT_SCHEDULER=cron`. crontab 에 이 낱말이 든 줄이 있으면 「작업 있음」.
CRON_MARK = "collect_now.sh"
#: 예약 작업 이름 — `demo_preflight.check_scheduled_task` 와 같다.
TASK_NAME = "BidPilot-DailyCollect"
#: 「하루 한 번」(D30) — 오늘 실패 · 일부 실패만 있으면 마지막 시도 이만큼 뒤부터 다시 · 하루 최대 시도 수.
RETRY_AFTER = timedelta(minutes=60)
DAILY_MAX_ATTEMPTS = 3
#: 41차 COLLECT-R40-05 — 로그를 **시각으로** 읽는다(줄은 받기가 끝날 때 붙고 「시각」은 시작 시각이라 겹친 두 받기는 순서가 뒤집힌다).
#: 어제 줄을 만나도 멈추지 않고 이만큼 더 본다 · 마지막 성공은 끝에서부터 이만큼의 성공 중 시각이 가장 늦은 것.
_SCAN_PAST_LINES = 40
_SUCCESS_WINDOW = 20
#: 기업마당을 이만큼(날) 넘게 못 받으면 받은 때 한 줄을 경고색으로(44차 OPS-10).
BIZINFO_STALE_DAYS = 3
#: 기업마당 마지막 성공을 찾을 때 거슬러 볼 줄 수(하루 세 줄 남짓 · 한 달 넘게).
_BIZINFO_SCAN_LINES = 400

#: 아는 받기 실패 → 할 일(44차 OPS-09) — 원문은 뒤에 그대로 둔다. 위에서부터 처음 맞는 것.
_FAILURE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"SERVICE_KEY_IS_NOT_REGISTERED|DEADLINE_HAS_EXPIRED|SERVICE ?KEY.*(?:NOT|EXPIRED)|\('3[01]'"),
     "서비스키 미등록 · 만료 — 대표가 data.go.kr 에서 활용기간을 연장하세요"),
    (re.compile(r"LIMITED_NUMBER_OF_SERVICE_REQUESTS|\('22'"), "하루 호출 한도를 넘었습니다 — 내일 다시 받습니다"),
    (re.compile(r"기업마당 인증|인증키"), "기업마당 인증키 오류 — 대표가 기업마당 API 키(활용기간)를 확인하세요"),
    # 10-31 최종 점검 — 조달청이 JSON 대신 「시스템 점검 안내」 HTML 을 돌려준 날(원문은 <title> 앞에서 잘려 「non-JSON」만 남기도 함).
    # 지금 받기도 같은 까닭으로 실패하므로 권유하지 않는다(연결 문제 항목은 맨 끝 그대로 — 아래 retry 판단이 그것만 권유).
    # HTML 안내 화면만 — 게이트웨이 XML 오류(접근 거부 · IP 미등록)는 점검이 아니다(10-31 독립 검토)
    # 11-01 — 이제 g2b_client 가 HTML 안내 화면을 「목록 대신 안내 화면을 보냈습니다」로 적는다(옛 기록의 원문 꼴도 그대로 읽음)
    (re.compile(r"시스템\s*점검|목록 대신 안내 화면을 보냈습니다|non-JSON response:\s*<(?:!DOCTYPE|html)", re.I),
     "조달청(나라장터)이 시스템 점검 등으로 목록 대신 안내 화면을 보냈습니다 — 점검이 끝나면 다음 자동 받기 때 받습니다"),
    (re.compile(r"ConnectError|ConnectTimeout|ReadTimeout|TimeoutException|Timeout|getaddrinfo|Name or service not known|"
                r"Network ?is ?unreachable|연결|호출 실패"), "인터넷 · 상대 서버 연결 문제 — 관리자에게 알리세요"),
)
#: AI 적합도가 Claude 로그인 없음으로 쉬었을 때 받은 때 한 줄 꼬리(44차 OPS-12).
AI_RESTING_NOTE = "AI 보조 쉼 — Claude 로그인 필요(관리자)"


def failure_hint(text: str | None) -> str | None:
    """받기 오류 원문 → 한국어 할 일 한 줄(아는 것만 · OPS-09). 모르면 None(원문만)."""
    for pattern, hint in _FAILURE_HINTS:
        if pattern.search(text or ""):
            return hint
    return None


# --------------------------------------------------------------------------
# 로그 읽기
# --------------------------------------------------------------------------


def _parse(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _moment(payload: dict[str, Any]) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(payload.get("시각")))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _row(payload: dict[str, Any], source: str) -> dict[str, Any] | None:
    return next((r for r in payload.get("결과") or [] if isinstance(r, dict) and r.get("출처") == source), None)


def _success_at(line: str) -> tuple[datetime, dict[str, Any]] | None:
    """성공한 실행 줄이면 `(시각, 나라장터 줄)`. 나라장터 줄에 기업마당 오류 여부(`_기업마당_오류`)를 덧붙인다(COLLECT-06)."""
    payload = _parse(line)
    if payload is None or not payload.get("실행"):
        return None
    g2b = _row(payload, "나라장터")
    if not g2b or g2b.get("오류") or g2b.get("건너뜀"):
        return None
    moment = _moment(payload)
    if moment is None:
        return None
    biz = _row(payload, "기업마당")
    ai = _row(payload, "AI 적합도") or {}
    return moment, {
        **g2b,
        "_기업마당_오류": bool(biz and biz.get("오류")),
        "_기업마당_오류_원문": (biz or {}).get("오류"),
        # OPS-12 — AI 적합도가 Claude 로그인 없음 · 만료로 쉬었다(시간 초과 · 다른 CLI 오류는 「로그인 필요」가 아니다 · 44차 마지막 검토)
        "_AI_쉼": "로그인" in str(ai.get("실패_이유") or ""),
    }


def _lines_backward() -> Iterator[str]:
    """로그 줄 — 새것부터. 끝에서부터 `_TAIL_BYTES` 씩 읽는다(줄이 조각에 걸치면 다음 조각과 잇는다)."""
    try:
        with LOG_FILE.open("rb") as handle:
            handle.seek(0, 2)
            pos = handle.tell()
            carry = b""
            while pos > 0:
                step = min(_TAIL_BYTES, pos)
                pos -= step
                handle.seek(pos)
                parts = (handle.read(step) + carry).split(b"\n")
                carry = parts[0]  # 앞 조각과 이어질 수 있는 첫 줄
                for raw in reversed(parts[1:]):
                    yield raw.decode("utf-8", errors="replace")
            yield carry.decode("utf-8", errors="replace")
    except OSError:
        return


def _successes_backward() -> Iterator[tuple[datetime, dict[str, Any]]]:
    """성공한 실행의 `(시각, 나라장터 줄)` — 새것부터."""
    for line in _lines_backward():
        found = _success_at(line)
        if found is not None:
            yield found


def _last_success_row() -> tuple[datetime, dict[str, Any]] | None:
    """마지막 성공 — 파일 끝에서 처음 만난 것이 아니라 **시각이 가장 늦은 것**(41차 COLLECT-R40-05 · 늦게 붙은 어제 줄)."""
    return max(islice(_successes_backward(), _SUCCESS_WINDOW), key=lambda found: found[0], default=None)


def last_success() -> datetime | None:
    """나라장터를 오류 없이 받은 마지막 실행 시각. 없거나 못 읽으면 None."""
    found = _last_success_row()
    return found[0] if found else None


def fresh_success(now: datetime) -> datetime | None:
    """`FRESH_HOURS` 안의 마지막 성공. 오래됐거나 없으면 None."""
    moment = last_success()
    if moment is None:
        return None
    return moment if now - moment <= timedelta(hours=FRESH_HOURS) else None


def _kst_day(moment: datetime) -> Any:
    return moment.astimezone(KST).date()


def _stamp(moment: datetime) -> str:
    return f"{moment.astimezone(KST):%m/%d %H:%M}"


# --------------------------------------------------------------------------
# 하루 한 번 (D30)
# --------------------------------------------------------------------------


def _today_runs(now: datetime) -> Iterator[tuple[datetime, dict[str, Any]]]:
    """오늘(KST 자정 뒤) 시각의 `실행: true` 줄 — 파일 끝에서부터. 어제 시각 줄을 만나도 `_SCAN_PAST_LINES` 줄 더 본다(41차 COLLECT-R40-05 —
    늦게 끝난 어제 받기의 줄이 오늘 줄 뒤에 붙으면 거기서 멈춰 오늘 성공을 못 봤다)."""
    today = _kst_day(now)
    past = 0
    for line in _lines_backward():
        payload = _parse(line)
        moment = _moment(payload) if payload is not None else None
        if moment is None:
            continue
        if _kst_day(moment) < today:
            past += 1
            if past > _SCAN_PAST_LINES:
                return
            continue
        if _kst_day(moment) == today and payload.get("실행"):
            yield moment, payload


def bizinfo_failing_since() -> datetime | None:
    """기업마당을 이어서 못 받기 시작한 실행 시각(OPS-10) — 마지막 성공 바로 뒤의 첫 실패 · 로그에서 읽는다.

    성공 기록이 읽는 범위에 없으면 그 범위에서 가장 오래된 실패다(모르는 날을 지어 세지 않는다). 실패가 없으면 None."""
    since: datetime | None = None
    for count, line in enumerate(_lines_backward()):
        if count > _BIZINFO_SCAN_LINES:
            break
        payload = _parse(line)
        if payload is None or not payload.get("실행"):
            continue
        biz = _row(payload, "기업마당")
        if not biz or biz.get("건너뜀"):
            continue
        if not biz.get("오류"):
            break
        since = _moment(payload)
    return since


def _last_failure_today(now: datetime) -> str | None:
    """오늘 실패한 나라장터 받기의 원문(가장 최근) — 받은 때 한 줄의 원인 꼬리(OPS-09)."""
    for _moment_, payload in _today_runs(now):
        g2b = _row(payload, "나라장터") or {}
        if g2b.get("오류"):
            return str(g2b["오류"])
    return None


def _bizinfo_today(now: datetime) -> datetime | None:
    """오늘 실행에서 기업마당을 오류 없이 받은 가장 늦은 시각(KST) — 나라장터만 못 받은 날 받은 때 한 줄에 함께 적는다(10-31 최종 점검)."""
    best: datetime | None = None
    for moment, payload in _today_runs(now):
        biz = _row(payload, "기업마당") or {}
        # 실제로 새로 받은 줄만(키 없는 설치는 옛 저장본을 「cached」로 돌려준다 · 10-31 독립 검토)
        if biz.get("결과") != "bizinfo" or biz.get("오류"):
            continue
        try:
            at = datetime.fromisoformat(str(biz.get("조회_시각")))
        except ValueError:
            at = moment
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        if _kst_day(at) != _kst_day(now):
            continue
        best = at if best is None or at > best else best
    return best.astimezone(KST) if best else None


def attempts_today(now: datetime) -> list[tuple[datetime, bool]]:
    """오늘(KST 자정 뒤) 실제로 받으려 한 실행(`실행: true`) — `(시각, 오류 없는 성공인가)` · **시각 새것부터**.

    「오류 없는 성공」은 나라장터 줄에 오류 · 건너뜀 · 일부 실패가 없는 것이다(기업마당 오류는 다시 받을 까닭으로 세지 않는다 —
    하루 세 번 기업마당을 다시 부르지 않게 · 받은 때 줄에 「기업마당 못 받음」으로 보인다)."""
    out: list[tuple[datetime, bool]] = []
    for moment, payload in _today_runs(now):
        g2b = _row(payload, "나라장터") or {}
        clean = bool(g2b) and not (g2b.get("오류") or g2b.get("건너뜀") or g2b.get("일부_실패"))
        out.append((moment, clean))
    return sorted(out, key=lambda pair: pair[0], reverse=True)


def done_today(now: datetime, source: str, field: str) -> int:
    """오늘(KST) 실행들이 그 출처 줄에 적은 수의 합 — 공고문 하루 상한을 **그날 합계로** 센다(41차 D33 · COLLECT-R40-01 —
    일부 실패 뒤 다시 받기마다 상한 20 을 새로 채웠다)."""
    total = 0
    for _moment, payload in _today_runs(now):
        row = _row(payload, source) or {}
        try:
            total += int(row.get(field) or 0)
        except (TypeError, ValueError):
            continue
    return total


def daily_gate(now: datetime) -> tuple[bool, str | None]:
    """오늘 받을까 — `(받는다, 안 받는 까닭)`. **네트워크를 쓰지 않는다**(로그만 읽는다).

    오늘 오류 없는 성공이 있으면 「오늘 이미 받음 HH:MM」 · 오늘 실패 · 일부 실패만 있으면 마지막 시도 60분 뒤부터 다시(하루 최대 3번)."""
    tries = attempts_today(now)
    clean = next((moment for moment, ok in tries if ok), None)
    if clean is not None:
        return False, f"오늘 이미 받음 {clean.astimezone(KST):%H:%M}"
    if len(tries) >= DAILY_MAX_ATTEMPTS:
        return False, f"오늘 {len(tries)}번 시도함(하루 최대 {DAILY_MAX_ATTEMPTS}번) — 「지금 받기」로만 다시"
    if tries and now - tries[0][0] < RETRY_AFTER:
        again = (tries[0][0] + RETRY_AFTER).astimezone(KST)
        return False, f"마지막 시도 {tries[0][0].astimezone(KST):%H:%M} — {again:%H:%M} 뒤에 다시"
    return True, None


# --------------------------------------------------------------------------
# 받기 잠금 (D29)
# --------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    """그 pid 의 프로세스가 살아 있나. Windows 는 `os.kill(pid, 0)` 이 프로세스를 끝내 버리므로 OpenProcess 로 본다."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_started(pid: int) -> float | None:
    """그 pid 프로세스가 만들어진 때(유닉스 초). 모르면 None — Windows 는 GetProcessTimes, 그 밖은 None(41차 COLLECT-R40-03)."""
    if pid <= 0 or sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime  # 1601-01-01 부터 100ns
        return ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel32.CloseHandle(handle)


def lock_info(now: datetime | None = None) -> dict[str, Any] | None:
    """살아 있는 잠금이면 `{"pid", "started"}` — 파일이 없거나 pid 가 죽었거나 2시간 넘었으면 None.

    41차 COLLECT-R40-03 — 잠금에 적힌 프로세스 시작 시각(`proc_start`)이 지금 그 pid 의 시작 시각과 다르면 Windows 가 pid 를 다른 프로세스에
    다시 준 것이다(죽은 받기의 남은 잠금) — 넘긴다. 시작 시각이 없는 옛 잠금은 pid · 2시간만 본다."""
    try:
        payload = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        started = datetime.fromisoformat(str(payload.get("started")))
        pid = int(payload.get("pid") or 0)
        recorded = payload.get("proc_start")
        recorded = float(recorded) if recorded is not None else None
    except (OSError, ValueError, TypeError):
        return None
    current = now or datetime.now(timezone.utc)
    if (started.tzinfo is None) or current - started > LOCK_STALE or not pid_alive(pid):
        return None
    if recorded is not None:
        actual = process_started(pid)
        if actual is not None and abs(actual - recorded) > 2.0:
            return None
    return {"pid": pid, "started": started}


def acquire_lock(now: datetime | None = None) -> bool:
    """받기 잠금을 잡는다(O_EXCL). 살아 있는 잠금이 있으면 False. 죽었거나 2시간 넘은 잠금은 넘기고 잡는다."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = now or datetime.now(timezone.utc)
    body = json.dumps({"pid": os.getpid(), "started": current.isoformat(),
                       "proc_start": process_started(os.getpid())}).encode("utf-8")
    for _ in range(2):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if lock_info(current) is not None:
                return False
            try:
                LOCK_FILE.unlink()  # 죽은 잠금 — 넘긴다
            except OSError:
                return False
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        return True
    return False


def release_lock() -> None:
    """잡은 잠금을 놓는다 — 내 pid 의 잠금일 때만 지운다."""
    try:
        payload = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        if int(payload.get("pid") or 0) == os.getpid():
            LOCK_FILE.unlink()
    except (OSError, ValueError, TypeError):
        return


# --------------------------------------------------------------------------
# 예약 작업 상태 (D28)
# --------------------------------------------------------------------------

_TASK_MEMO: dict[str, Any] = {"at": 0.0, "state": None}
_TASK_MEMO_SECONDS = 300.0
#: 41차 REGRESS-03 — 메모가 끝난 순간 동시에 온 요청들이 저마다 PowerShell 을 띄웠다 — 하나만 묻고 나머지는 그 값을 기다린다.
_TASK_LOCK = threading.Lock()


def task_state() -> str:
    """예약 작업 상태 — 「Ready」 · 「Running」 · 「Disabled」 · 「NONE」(없음) · 「unknown」(못 읽음 · Windows 아님).
    `demo_preflight.check_scheduled_task` 와 같은 조회를 5분 메모한다(요청마다 PowerShell 을 띄우지 않게)."""
    if _time.monotonic() - _TASK_MEMO["at"] < _TASK_MEMO_SECONDS and _TASK_MEMO["state"]:
        return str(_TASK_MEMO["state"])
    with _TASK_LOCK:
        if _time.monotonic() - _TASK_MEMO["at"] < _TASK_MEMO_SECONDS and _TASK_MEMO["state"]:
            return str(_TASK_MEMO["state"])
        return _ask_task_state()


#: 이 설치의 저장소 폴더 — 예약 작업의 작업 폴더가 여기여야 「이 설치의 작업」이다(41차 — 같은 PC 의 키트가 본 저장소 작업을 제 것으로 읽었다).
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _same_folder(path: str) -> bool:
    try:
        return Path(path).resolve() == _REPO_ROOT
    except (OSError, ValueError):
        return False


def on_cron() -> bool:
    """회사 서버(42차) — 받기는 cron 이 한다(`COLLECT_SCHEDULER=cron`). 노트북(예약 작업)은 비워 둔다."""
    return os.environ.get("COLLECT_SCHEDULER", "").strip().lower() == "cron"


def _ask_cron_state() -> str:
    """crontab 에 받기 줄(`CRON_MARK` · 주석 아님)이 있으면 「Ready」 · 없으면 「NONE」 · 못 읽으면 「unknown」."""
    try:
        done = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if done.returncode != 0:  # 「no crontab for ksh」
        return "NONE"
    lines = [line.strip() for line in (done.stdout or "").splitlines()]
    return "Ready" if any(CRON_MARK in line and not line.startswith("#") for line in lines) else "NONE"


def _ask_task_state() -> str:
    state = "unknown"
    if on_cron():
        state = _ask_cron_state()
    elif sys.platform == "win32":
        command = (
            f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
            "if ($t) { [string]$t.State + '|' + [string]$t.Actions[0].WorkingDirectory } else { 'NONE' }"
        )
        try:
            done = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=15,
                                  encoding="utf-8", errors="replace")
            out = (done.stdout or "").strip()
            if done.returncode == 0 and out and not (done.stderr or "").strip():
                name, _, folder = out.partition("|")
                # 작업 폴더가 다른 설치(같은 PC 의 키트 ↔ 본 저장소)면 이 설치에는 작업이 없는 것이다
                state = name if name == "NONE" or not folder or _same_folder(folder) else "NONE"
        except (OSError, subprocess.SubprocessError):
            state = "unknown"
    _TASK_MEMO.update(at=_time.monotonic(), state=state)
    return state


# --------------------------------------------------------------------------
# 화면 한 줄 (D30 · D28 · D29)
# --------------------------------------------------------------------------


#: 회사 서버 cron 받는 시각(`deploy/server/crontab.txt` 「30 7,9,11」 · KST) — 이 시각 전은 「받을 예정」이지 경고가 아니다(43차 M27).
CRON_SLOTS: tuple[tuple[int, int], ...] = ((7, 30), (9, 30), (11, 30))


def _next_cron_slot(now: datetime) -> str | None:
    """오늘 남은 첫 받는 시각(「09:30」) — 11:30 도 지났으면 None(그때부터 경고)."""
    local = now.astimezone(KST)
    for hour, minute in CRON_SLOTS:
        if (local.hour, local.minute) < (hour, minute):
            return f"{hour:02d}:{minute:02d}"
    return None


def collect_state(now: datetime) -> dict[str, Any]:
    """화면 한 줄 — `kind` 와 그 글(`text`) · 마지막 성공(`last_success` · ISO) · 꼬리(`suffix` — 줄인 글에도 붙인다 · COLLECT-01).

    - none: 자동 받기 기록도 예약 작업도 없다(키트). 화면은 예전 글(「새 공고 받기 꺼짐」) 그대로다.
    - off: 예약 작업이 꺼져 있거나 없다(시연 · 검수 · 기록만 옮겨 온 PC · D28) — 「자동 받기 꺼 둠 — 목록은 MM/DD HH:MM 그대로」 · 경고 · 권유 없음.
    - running: 받기 잠금이 살아 있다(D29) — 「오늘 목록 받는 중 — HH:MM 시작」 · 경고 아님.
    - ok: 오늘(KST 자정 뒤) 받았다 — 「매일 처음 켤 때 자동으로 받음 · 오늘 HH:MM」.
    - missed: 오늘 아직 — 「오늘 목록을 아직 받지 않았습니다 — 마지막 MM/DD HH:MM · 「지금 받기」…」(경고).
    - waiting: 회사 서버가 오늘 받을 시각 전(43차 M27) — 「오늘 07:30에 받을 예정 · 목록은 MM/DD HH:MM」 · 실패 뒤 「09:30에 다시 받음 · …」.

    회사 서버(42차 · `COLLECT_SCHEDULER=cron`): 작업 있음 = crontab 받기 줄 · ok 는 「매일 아침 07:30 서버가 자동으로 받음 · 오늘 HH:MM」 ·
    missed 는 「… · 관리자에게 「지금 받기」를 부탁하세요」. 받는 중 · 꺼 둠은 같은 글.
    """
    found = _last_success_row()
    last = found[0] if found else None
    # 41차 REGRESS-05 — 로그가 없어도 예약 작업은 본다(등록만 하고 아직 한 번도 안 돈 PC 가 키트 글 「새 공고 받기 꺼짐」을 보였다)
    state = task_state()
    if not LOG_FILE.exists() and state in ("NONE", "unknown"):
        return {"kind": "none", "text": None, "last_success": None, "suffix": None}
    stamp = _stamp(last) if last else "기록 없음"
    held = lock_info(now)
    if held is not None:
        return {"kind": "running", "text": f"오늘 목록 받는 중 — {held['started'].astimezone(KST):%H:%M} 시작",
                "last_success": last.isoformat() if last else None, "suffix": None}
    if state in ("Disabled", "NONE"):
        text = f"자동 받기 꺼 둠 — 목록은 {stamp} 그대로" if last else "자동 받기 꺼 둠 — 받은 기록 없음"
        return {"kind": "off", "text": text, "last_success": last.isoformat() if last else None, "suffix": None}
    if last is None or _kst_day(last) != _kst_day(now):
        slot = _next_cron_slot(now) if on_cron() else None
        # 44차 OPS-09 — 오늘 실패한 까닭을 아는 것이면 할 일 한 줄을 붙인다(원문은 로그 · collect_daily.err 에)
        hint = failure_hint(_last_failure_today(now))
        cause = f" · 원인: {hint}" if hint else ""
        if slot is not None:
            # 43차 M27 — 서버는 07:30 · 09:30 · 11:30 에 받는다. 그 전은 경고가 아니다(새벽마다 「아직 안 받음 · 관리자에게 부탁」 헛경고가 떴다).
            lead = f"{slot}에 다시 받음" if attempts_today(now) else f"오늘 {slot}에 받을 예정"
            return {"kind": "waiting", "text": f"{lead} · 목록은 {stamp}{cause}", "last_success": last.isoformat() if last else None,
                    "suffix": None, "warn": False}
        # 서버 화면에는 실행 단추가 없다 — 바깥 호출을 화면이 일으키지 않는다(42차 · 관리자가 `scripts/collect_now.sh`)
        ask = "관리자에게 「지금 받기」를 부탁하세요" if on_cron() else f"「지금 받기」를 두 번 누르세요({COLLECT_NOW_FILE})"
        # 45차 M10 — 원인이 하루 한도 · 서비스키 · 인증키면 지금 받기도 같은 까닭으로 실패한다 — 권유를 빼고 원인의 할 일만 적는다
        retry = hint is None or hint == _FAILURE_HINTS[-1][1]
        # 10-31 최종 점검 — 오늘 시도했으면 「아직 안 받음」 대신 시도한 사실 · 기업마당을 받았으면 그 시각(나라장터만 못 받은 날)
        tries = attempts_today(now)
        lead = f"오늘 {len(tries)}번 받으려 했지만 나라장터 목록을 받지 못했습니다" if tries else "오늘 목록을 아직 받지 않았습니다"
        biz = _bizinfo_today(now) if tries else None
        biz_part = f" · 기업마당은 오늘 {biz:%H:%M} 받음" if biz else ""
        text = f"{lead} — 마지막 {stamp}{biz_part}{f' · {ask}' if retry else ''}{cause}"
        return {"kind": "missed", "text": text, "last_success": last.isoformat() if last else None, "suffix": None, "warn": True}
    # 39차 DAILY-02 · 40차 COLLECT-06 — 일부 낱말을 지난 저장본으로 채웠거나 같은 실행에서 기업마당을 못 받았으면 꼬리로 덧붙인다(경고 아님)
    parts = []
    warn = False
    if found and found[1].get("일부_실패"):
        parts.append("일부 실패(지난 저장본으로 채움)")
    if found and found[1].get("_기업마당_오류"):
        # 44차 OPS-10 — 며칠째 못 받았나(실패가 시작된 날부터 오늘까지 · 로그에서) · 3일 넘으면 경고색 · OPS-09 아는 원인은 괄호에 할 일
        since = bizinfo_failing_since()
        days = (_kst_day(now) - _kst_day(since)).days + 1 if since else 1
        hint = failure_hint(found[1].get("_기업마당_오류_원문"))
        if days > BIZINFO_STALE_DAYS:
            parts.append(f"기업마당 {days}일째 못 받음 — 관리자에게" + (f"({hint})" if hint else ""))
            warn = True
        else:
            parts.append("기업마당 못 받음" + (f"({hint})" if hint else ""))
    if found and found[1].get("_AI_쉼"):
        parts.append(AI_RESTING_NOTE)
    suffix = "".join(f" · {p}" for p in parts) or None
    when = "매일 아침 07:30 서버가 자동으로 받음" if on_cron() else "매일 처음 켤 때 자동으로 받음"
    text = f"{when} · 오늘 {last.astimezone(KST):%H:%M}"
    return {"kind": "ok", "text": text + (suffix or ""), "last_success": last.isoformat(), "suffix": suffix, "warn": warn}
