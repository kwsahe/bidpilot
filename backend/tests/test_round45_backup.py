"""45차 SEC-R37-01 — `deploy/server/backup.sh` 는 어떤 실패에도 backup.log 에 FAIL 줄을 남기고 임시 파일을 지운다.

경우 넷(정상 · .env 없음 · DATA_DIR 없음 · 자료 폴더 없음)을 가짜 HOME 에서 bash 로 돌린다. bash 가 없으면 건너뛴다.
옛 판(ERR trap)은 .env 없음 · DATA_DIR 없음에서 FAIL 줄 없이 끝났다(특수 내장 명령 실패 · set -u 확장 오류는 ERR trap 을 부르지 않음).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "server" / "backup.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or "system32" in (BASH or "").lower(), reason="bash 없음(또는 WSL 바꿔치기)")


def _run(home: Path) -> tuple[int, str]:
    env = {**os.environ, "HOME": str(home)}
    done = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)  # type: ignore[list-item]
    log = home / "bidpilot-backups" / "backup.log"
    last = log.read_text(encoding="utf-8").strip().splitlines()[-1] if log.exists() else ""
    assert not list((home / "bidpilot-backups").glob("*.part"))
    return done.returncode, last


def _home(tmp_path: Path, env_text: str | None) -> Path:
    home = tmp_path / "home"
    (home / "bidpilot").mkdir(parents=True)
    if env_text is not None:
        (home / "bidpilot" / ".env").write_text(env_text, encoding="utf-8")
    return home


def _posix(path: Path) -> str:
    # Git Bash 는 C:\… 대신 /c/… 를 읽는다
    text = path.as_posix()
    return f"/{text[0].lower()}{text[2:]}" if os.name == "nt" and text[1:2] == ":" else text


def test_정상이면_백업_한_줄(tmp_path: Path) -> None:
    data = tmp_path / "data" / "private" / "org"
    data.mkdir(parents=True)
    (data / "a.json").write_text("{}", encoding="utf-8")
    code, last = _run(_home(tmp_path, f"DATA_DIR={_posix(tmp_path / 'data')}\n"))
    assert code == 0 and "private-" in last and "FAIL" not in last


@pytest.mark.parametrize(
    ("env_text", "want"),
    [
        (None, "FAIL 설정 읽기 — .env 를 읽을 수 없음"),
        ("OTHER=1\n", "FAIL 설정 읽기 — DATA_DIR 이 .env 에 없음"),
        ("DATA_DIR=/nonexistent-bidpilot-data\n", "FAIL 설정 읽기 — 자료 폴더 없음"),
    ],
)
def test_실패는_언제나_FAIL_줄(tmp_path: Path, env_text: str | None, want: str) -> None:
    code, last = _run(_home(tmp_path, env_text))
    assert code != 0 and want in last
