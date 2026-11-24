#!/usr/bin/env python
"""게이트를 켠 상태를 **자동으로** 두드려 본다 (0919.md §4-A-2).

## 왜 필요한가

계정·역할·활동 기록은 `API_TOKEN` 과 로그인 게이트가 **둘 다 켜진** 배포에서만 뜻이 있다.
로컬 개발은 그 둘이 꺼져 있어서 `pytest` 를 아무리 돌려도 그 상태를 재지 못한다.
3차 작업에서는 사람이 환경변수를 손으로 넣고 브라우저로 15가지를 눌러 확인했는데,
4차에서 보안 수정을 하고 나서는 **아무도 그 확인을 다시 하지 못했다.**

이 스크립트가 그 확인을 대신한다. 임시 포트에 백엔드와 프런트를 게이트를 켠 채로 띄우고,
시험 계정 셋으로 HTTP 를 직접 두드려 표로 찍는다. 끝나면 프로세스와 임시 파일을 지운다.

    python scripts/check_gate.py
    python scripts/check_gate.py --keep      # 실패를 들여다보려면 서버를 남긴다

## 무엇을 건드리지 않는가

- 저장소의 `data/` 를 **읽지도 쓰지도 않는다.** `DATA_DIR` 을 임시 폴더로 돌린다.
  그래서 시험 계정(`users.json`)도 활동 기록도 임시 폴더에만 생기고 끝나면 함께 사라진다.
- 나라장터·기업마당을 부르지 않는다 (`G2B_LIVE_FETCH=0`).
- 저장소의 `.env` 를 읽지 않는다 — 환경변수를 여기서 전부 만들어 넘긴다.

## 앞서 해 둘 것

프런트는 **빌드된 것**을 쓴다(`npm run start`). dev 서버는 첫 컴파일이 오래 걸리고
그 사이 요청이 대기해 판정이 흔들린다. 빌드가 없으면 이 스크립트가 알려 준다.

    cd frontend && npm run build
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():  # 리눅스·맥
    VENV_PYTHON = BACKEND / ".venv" / "bin" / "python"

#: 공용 접근계정. 이 스크립트 안에서만 쓰는 값이다 — 저장소에도 사람 환경에도 남지 않는다.
DEMO_USER = "shared-test"
DEMO_PASSWORD = "shared-password-0919"
#: 시험 계정 셋. 비밀번호는 같아도 된다 — 재는 것은 역할이다.
TEST_PASSWORD = "gate-check-0919"
ACCOUNTS = [("viewer1", "viewer"), ("editor1", "editor"), ("admin1", "admin")]


# ---------------------------------------------------------------------------
# 결과 표
# ---------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    rows: list[Result] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.rows.append(Result(name, passed, detail))
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))

    def check(self, name: str, actual: object, expected: object, note: str = "") -> bool:
        ok = actual == expected
        self.add(name, ok, note if ok else f"기대 {expected!r} · 실제 {actual!r}{(' · ' + note) if note else ''}")
        return ok

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.rows if not r.passed]


# ---------------------------------------------------------------------------
# HTTP (의존성 없이)
# ---------------------------------------------------------------------------


@dataclass
class Response:
    status: int
    body: str
    headers: dict[str, str]
    set_cookies: list[str]

    def header(self, name: str) -> str:
        """헤더 이름은 대소문자를 가리지 않는다. `dict` 로 받아 두었으므로 여기서 맞춘다."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return ""

    def json(self) -> object:
        try:
            return json.loads(self.body)
        except ValueError:
            return None

    def detail(self) -> str:
        data = self.json()
        if isinstance(data, dict):
            for key in ("detail", "error"):
                value = data.get(key)
                if isinstance(value, str):
                    return value
        return ""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다 — 307 자체가 확인 대상이다."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_opener = urllib.request.build_opener(NoRedirect)


def request(
    url: str,
    *,
    method: str = "GET",
    body: object = None,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> Response:
    data = None
    send = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        send["Content-Type"] = "application/json"
    if cookies:
        send["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(url, data=data, method=method, headers=send)
    try:
        with _opener.open(req, timeout=timeout) as raw:  # noqa: S310 — 로컬 주소만 쓴다
            return Response(
                raw.status,
                raw.read().decode("utf-8", errors="replace"),
                dict(raw.headers),
                raw.headers.get_all("Set-Cookie") or [],
            )
    except urllib.error.HTTPError as exc:
        return Response(
            exc.code,
            exc.read().decode("utf-8", errors="replace"),
            dict(exc.headers),
            exc.headers.get_all("Set-Cookie") or [],
        )
    except (urllib.error.URLError, OSError) as exc:
        return Response(0, str(exc), {}, [])


def cookies_from(response: Response) -> dict[str, str]:
    """`Set-Cookie` 에서 이름=값만 뽑는다. 빈 값(삭제)도 그대로 담는다."""
    jar: dict[str, str] = {}
    for line in response.set_cookies:
        name, _, rest = line.partition("=")
        jar[name.strip()] = rest.split(";")[0].strip()
    return jar


def http_only(response: Response, name: str) -> bool:
    """그 쿠키가 `HttpOnly` 로 내려왔는가 — 브라우저 스크립트가 읽지 못한다는 뜻이다."""
    for line in response.set_cookies:
        if line.startswith(f"{name}=") and "httponly" in line.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# 서버 띄우기
# ---------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for(url: str, *, seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if request(url, timeout=3.0).status:
            return True
        time.sleep(0.5)
    return False


def stop(process: subprocess.Popen | None) -> None:
    """프로세스와 그 자식까지 끝낸다. 윈도우는 `taskkill /T` 가 유일하게 확실하다."""
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def write_users(path: Path) -> None:
    """시험 계정 셋을 임시 `users.json` 에 직접 쓴다.

    `manage_users.py` 를 쓰지 않는 이유: 그쪽은 비밀번호를 프롬프트로만 받는다(그게 맞다).
    여기서는 해시 함수만 빌려 쓴다.
    """
    sys.path.insert(0, str(BACKEND))
    from app.services.user_service import hash_password  # noqa: PLC0415 — 경로를 먼저 넣어야 한다

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "users": [
                    {
                        "user": user,
                        "display_name": f"시험 {role}",
                        "role": role,
                        "password_hash": hash_password(TEST_PASSWORD),
                        "created_at": "2026-09-19T00:00:00+00:00",
                        "active": True,
                    }
                    for user, role in ACCOUNTS
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def set_active(path: Path, user: str, active: bool) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for entry in payload["users"]:
        if entry["user"] == user:
            entry["active"] = active
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 15가지 확인
# ---------------------------------------------------------------------------


def login(front: str, user: str, password: str) -> Response:
    return request(f"{front}/api/login", method="POST", body={"user": user, "password": password})


def run_checks(front: str, back: str, users_file: Path, backend_proc: subprocess.Popen) -> Report:
    r = Report()
    print("\n== 게이트 확인 (16가지 · 17번은 44차 본인 비밀번호 바꾸기 · 18번은 45차 바꾼 뒤 이전 세션)")

    # 1 — 세션이 없으면 보호 경로는 로그인으로 보낸다.
    anon = request(f"{front}/")
    r.check("1. 세션 없이 / → 307 로그인", (anon.status, "/login" in anon.header("Location")), (307, True))

    # 2 — 개인 계정 셋이 각자의 역할로 들어온다.
    sessions: dict[str, dict[str, str]] = {}
    roles_ok = True
    for user, role in ACCOUNTS:
        res = login(front, user, TEST_PASSWORD)
        body = res.json()
        got = body.get("role") if isinstance(body, dict) else None
        if res.status != 200 or got != role:
            roles_ok = False
            r.add(f"2. {user} 로그인", False, f"{res.status} · 역할 {got!r} (기대 {role!r})")
        sessions[user] = cookies_from(res)
    if roles_ok:
        r.add("2. 개인 계정 3종 로그인 200 · 역할 그대로", True, " · ".join(f"{u}={ro}" for u, ro in ACCOUNTS))

    # 3 — 틀린 비밀번호는 401 이고 문구가 계정 존재 여부를 알려주지 않는다.
    wrong = login(front, "viewer1", "틀린비밀번호")
    missing = login(front, "no-such-user", "틀린비밀번호")
    r.check(
        "3. 틀린 비밀번호 401 · 없는 아이디와 같은 문구",
        (wrong.status, missing.status, wrong.detail() == missing.detail()),
        (401, 401, True),
        wrong.detail(),
    )

    # 4 — 세션 쿠키는 스크립트가 읽지 못한다(HttpOnly). 표시 쿠키는 읽을 수 있어야 한다.
    fresh = login(front, "admin1", TEST_PASSWORD)
    r.check(
        "4. 세션 쿠키 HttpOnly · 표시 쿠키는 읽힘",
        (http_only(fresh, "bidpilot_demo_session"), http_only(fresh, "bidpilot_user")),
        (True, False),
    )

    viewer, editor, admin = sessions["viewer1"], sessions["editor1"], sessions["admin1"]

    # 5 — 열람자는 읽는다.
    r.check("5. 열람자 읽기 200", request(f"{front}/api/organizations", cookies=viewer).status, 200)

    # 6 — 열람자는 쓰지 못한다.
    #
    # **편집자에게 열려 있는 쓰기**로 재야 한다. 회사 «만들기»는 원래 관리자 전용이라(S6)
    # 열람자가 막혀도 「편집자 이상」이 아니라 「관리자만」이 나온다 — 그러면 열람자·편집자
    # 경계가 아니라 관리자 경계를 잰 것이 된다. 색인 다시 만들기는 편집자의 일이다.
    blocked = request(
        f"{front}/api/organizations/org-sample/index/rebuild", method="POST", body={}, cookies=viewer
    )
    r.check("6. 열람자 쓰기 403 · 한국어 사유", (blocked.status, "편집자" in blocked.detail()), (403, True), blocked.detail())

    # 7 — 활동 기록은 관리자만.
    va = request(f"{front}/api/audit-log", cookies=viewer)
    ea = request(f"{front}/api/audit-log", cookies=editor)
    aa = request(f"{front}/api/audit-log", cookies=admin)
    r.check("7. 활동 기록은 관리자만 (403·403·200)", (va.status, ea.status, aa.status), (403, 403, 200), va.detail())

    # 8 — 표시 전용 쿠키를 admin 으로 위조해도 권한이 오르지 않는다.
    forged = dict(viewer)
    forged["bidpilot_user"] = '%7B%22u%22%3A%22viewer1%22%2C%22r%22%3A%22admin%22%2C%22n%22%3A%22x%22%7D'
    r.check("8. 표시 쿠키 위조는 무효", request(f"{front}/api/audit-log", cookies=forged).status, 403)

    # 9 — 편집자는 회사자료를 쓸 수 있다 (역할 경계를 너무 좁히지 않았는지).
    okw = request(
        f"{front}/api/organizations/org-sample/index/rebuild", method="POST", body={}, cookies=editor
    )
    r.check("9. 편집자 회사자료 쓰기 403 아님", okw.status != 403, True, f"HTTP {okw.status}")

    # 10 — 관리자만 하는 일은 편집자에게 막힌다.
    ec = request(
        f"{front}/api/organizations",
        method="POST",
        body={"display_name": "시험회사2", "created_by": "gate-check"},
        cookies=editor,
    )
    r.check("10. 편집자도 회사 «만들기»는 403", (ec.status, "관리자" in ec.detail()), (403, True), ec.detail())

    # 11 — 세션 없는 요청은 백엔드에 닿지 않는다.
    #
    # 게이트가 켜져 있으면 **게이트가 먼저** 로그인으로 보낸다(307). 중계의 401(S1)은
    # 게이트가 꺼진 조합을 위한 «두 번째 자물쇠»라 여기서는 지나가지 않는다 —
    # 그 조합 자체는 아래 `check_s1_combination()` 이 따로 확인한다.
    nosession = request(f"{front}/api/organizations", method="POST", body={"display_name": "x", "created_by": "y"})
    r.check(
        "11. 무세션 요청은 백엔드에 닿지 않는다",
        nosession.status in (307, 401, 503),
        True,
        f"HTTP {nosession.status} (게이트가 먼저 막으면 307)",
    )

    # 12 — 활동 기록에 열람자의 거부가 남는다.
    entries = aa.json()
    rows = entries.get("entries", []) if isinstance(entries, dict) else []
    denied = [e for e in rows if e.get("user") == "viewer1" and e.get("status") == 403]
    r.check("12. 활동 기록에 열람자 거부가 남는다", bool(denied), True, f"기록 {len(rows)}줄 중 거부 {len(denied)}건")

    # 13 (S3) — 계정을 끄면 이미 발급된 세션도 그 즉시 막힌다.
    set_active(users_file, "editor1", False)
    time.sleep(1.1)  # mtime 초 단위 해상도를 넘긴다
    disabled = request(f"{front}/api/organizations", cookies=editor)
    set_active(users_file, "editor1", True)
    r.check("13. (S3) 비활성 계정의 세션은 401", disabled.status, 401, disabled.detail())

    # 14 — 로그아웃하면 쿠키 둘 다 지워지고 보호 경로는 다시 로그인으로.
    out = request(f"{front}/api/logout", method="POST", cookies=admin)
    cleared = cookies_from(out)
    after = request(f"{front}/", cookies={k: v for k, v in cleared.items()})
    r.check(
        "14. 로그아웃 — 쿠키 둘 다 비고 보호 경로는 307",
        (cleared.get("bidpilot_demo_session"), cleared.get("bidpilot_user"), after.status),
        ("", "", 307),
    )

    # 17 (44차 S5) — 본인 비밀번호 바꾸기: 열람자도 자기 것은 바꾼다 · 틀린 지금 비밀번호는 400 · 바꾼 뒤 새 것만 들어온다.
    url = f"{front}/api/auth/password"
    wrong = request(url, method="POST", cookies=viewer, body={"old_password": "틀린-비밀번호", "new_password": "gate-check-new-44"})
    changed = request(url, method="POST", cookies=viewer, body={"old_password": TEST_PASSWORD, "new_password": "gate-check-new-44"})
    new_in = login(front, "viewer1", "gate-check-new-44").status
    old_in = login(front, "viewer1", TEST_PASSWORD).status
    r.check(
        "17. (44차 S5) 본인 비밀번호 바꾸기 — 틀림 400 · 바꿈 204 · 새 것 200 · 옛 것 401",
        (wrong.status, changed.status, new_in, old_in), (400, 204, 200, 401), changed.detail()[:60],
    )

    # 18 (45차 SEC-R37-03) — 비밀번호를 바꿔도 이미 발급된 다른 세션은 끊기지 않는다(문서 · 창에 적은 대로 · 끊으려면 계정 끄기 = 13번).
    # 이 줄이 401 이 되면 동작이 바뀐 것이다 — 화면 글(PasswordChange) · docs/limitations.md 를 함께 고친다.
    still = request(f"{front}/api/organizations", cookies=viewer)
    r.check("18. (45차 SEC-R37-03) 비밀번호를 바꾼 뒤에도 이전 세션은 그대로(문서에 적힌 동작)", still.status, 200, still.detail()[:60])

    # 15 (S4) — 백엔드가 답하지 않으면 로그인은 «열리지 않고» 닫힌다.
    stop(backend_proc)
    down = login(front, DEMO_USER, DEMO_PASSWORD)
    r.check("15. (S4) 백엔드 중단 시 공용 계정도 503", down.status, 503, down.detail()[:60])

    return r


def check_s1_combination(report: Report, back: str, token: str, front_port: int) -> None:
    """S1 — 중계 + 토큰인데 **게이트가 꺼진** 배포를 실제로 띄워 본다.

    검수가 High 로 지목한 조합이다. 이 상태에서 주소만 아는 익명 요청이 백엔드에 닿으면
    「토큰만 있고 신원 헤더가 없는 요청」이 되어 **관리자**로 처리된다.
    그래서 프런트가 아예 503 으로 닫아야 한다.

    앞선 15가지와 같은 프런트로는 잴 수 없다 — 거기는 게이트가 켜져 있다. 그래서 같은 빌드를
    `DEMO_USER`/`DEMO_PASSWORD` 없이 한 번 더 띄운다(몇 초).
    """
    print("")
    print("== S1 조합 (중계 + 토큰 + 게이트 꺼짐)")
    env = {
        **os.environ,
        "PORT": str(front_port),
        "BACKEND_URL": back,
        "API_TOKEN": token,
        "NODE_ENV": "production",
    }
    # 이 배포에는 공용 계정이 «없어야» 한다. 상위 셸에 남아 있으면 게이트가 켜져 버린다.
    env.pop("DEMO_USER", None)
    env.pop("DEMO_PASSWORD", None)
    env.pop("SESSION_SECRET", None)
    env.pop("REQUIRE_AUTH", None)
    ungated = f"http://127.0.0.1:{front_port}"
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(
            ["npm.cmd" if os.name == "nt" else "npm", "run", "start", "--", "--port", str(front_port)],
            cwd=FRONTEND,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for(f"{ungated}/", seconds=60.0):
            report.add("16. (S1) 게이트 꺼진 중계는 503", False, "프런트가 뜨지 않아 확인하지 못했다")
            return
        anon = request(f"{ungated}/api/organizations")
        report.check(
            "16. (S1) 게이트 꺼진 중계는 화면·API 를 503 으로 닫는다",
            anon.status,
            503,
            anon.detail()[:70],
        )
    finally:
        stop(process)


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="끝나도 서버와 임시 폴더를 남긴다 (실패를 볼 때)")
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        print(f"[!!] 백엔드 가상환경이 없습니다: {VENV_PYTHON}")
        print("     scripts/start_dev.ps1 을 한 번 돌려 만들어 주세요.")
        return 1
    if not (FRONTEND / ".next").exists():
        print("[!!] 프런트 빌드가 없습니다. 먼저 빌드해 주세요:")
        print("     cd frontend && npm run build")
        return 1

    token = secrets.token_hex(32)
    session_secret = secrets.token_hex(32)
    workdir = Path(tempfile.mkdtemp(prefix="bidpilot-gate-"))
    users_file = workdir / "private" / "users.json"
    back_port, front_port = free_port(), free_port()
    back, front = f"http://127.0.0.1:{back_port}", f"http://127.0.0.1:{front_port}"

    print("BidPilot AI — 게이트 켠 상태 확인")
    print(f"  임시 데이터 폴더: {workdir}")
    print(f"  백엔드 {back} · 프런트 {front}")
    print("  (저장소의 data/ 는 읽지도 쓰지도 않습니다)")

    write_users(users_file)

    backend_env = {
        **os.environ,
        "DATA_DIR": str(workdir),
        "API_TOKEN": token,
        "DEMO_USER": DEMO_USER,
        "DEMO_PASSWORD": DEMO_PASSWORD,
        "G2B_LIVE_FETCH": "0",
        "BIZINFO_LIVE_FETCH": "0",
        "APP_ENV": "production",
        # 저장소 .env 를 읽어 실제 키가 섞이지 않게 비운다.
        "OPENAI_API_KEY": "",
        "DATA_GO_KR_SERVICE_KEY": "",
    }
    frontend_env = {
        **os.environ,
        "PORT": str(front_port),
        "BACKEND_URL": back,
        "API_TOKEN": token,
        "SESSION_SECRET": session_secret,
        "DEMO_USER": DEMO_USER,
        "DEMO_PASSWORD": DEMO_PASSWORD,
        "NODE_ENV": "production",
    }

    backend_proc: subprocess.Popen | None = None
    frontend_proc: subprocess.Popen | None = None
    try:
        print("\n== 서버 기동")
        backend_proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(back_port)],
            cwd=BACKEND,
            env=backend_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for(f"{back}/health"):
            print("[!!] 백엔드가 뜨지 않았습니다.")
            return 1
        print(f"  [OK]   백엔드 (토큰 켬 · 고정 모드 · DATA_DIR={workdir.name})")

        frontend_proc = subprocess.Popen(
            ["npm.cmd" if os.name == "nt" else "npm", "run", "start", "--", "--port", str(front_port)],
            cwd=FRONTEND,
            env=frontend_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        if not wait_for(f"{front}/login"):
            print("[!!] 프런트가 뜨지 않았습니다.")
            return 1
        print("  [OK]   프런트 (게이트 켬 · 중계 켬)")

        report = run_checks(front, back, users_file, backend_proc)
        backend_proc = None  # 15번 확인에서 이미 내렸다

        # S1 조합은 게이트가 꺼진 프런트가 있어야 재진다 — 백엔드를 다시 띄운다.
        backend_proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(back_port)],
            cwd=BACKEND,
            env=backend_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if wait_for(f"{back}/health", seconds=60.0):
            check_s1_combination(report, back, token, free_port())
        else:
            report.add("16. (S1) 게이트 꺼진 중계는 503", False, "백엔드를 다시 띄우지 못했다")

        print()
        if report.failures:
            print(f"확인 {len(report.rows)}가지 중 **{len(report.failures)}가지 실패**")
            for row in report.failures:
                print(f"  - {row.name}: {row.detail}")
            return 1
        print(f"확인 {len(report.rows)}가지 전부 PASS")
        return 0
    finally:
        stop(backend_proc)
        stop(frontend_proc)
        if args.keep:
            print(f"\n(--keep: 임시 폴더를 남겼습니다 — {workdir})")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
            print("\n임시 폴더를 지웠습니다. 저장소의 data/ 는 건드리지 않았습니다.")


if __name__ == "__main__":
    raise SystemExit(main())
