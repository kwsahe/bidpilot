"""34차 §3-B — 서버 끄기 판단(scripts/process_safety.ps1)을 가짜 프로세스 표로 본다(R33-K1 · K2).

실제 프로세스는 건드리지 않는다 — 표를 JSON 으로 넘겨 판단 함수의 답만 받는다. PowerShell 이 없으면 건너뛴다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "process_safety.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell 없음")


def ps(table: list[dict], expression: str):
    """표를 `$Table` 로 두고 식 하나의 결과를 JSON 으로 받는다."""
    command = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f". '{SCRIPT}'; "
        f"$Table = @(ConvertFrom-Json @'\n{json.dumps(table)}\n'@ | ForEach-Object {{ $_ }}); "
        f"ConvertTo-Json -Compress @({expression})"
    )
    out = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    text = out.stdout.strip()
    return json.loads(text) if text else None


ROWS = [
    {"Id": 100, "ParentId": 1, "Name": "powershell.exe", "Created": "2026-10-08T10:00:00"},   # 우리가 띄운 창
    {"Id": 101, "ParentId": 100, "Name": "python.exe", "Created": "2026-10-08T10:00:02"},     # 그 창의 자식(늦게 생김)
    {"Id": 102, "ParentId": 101, "Name": "python.exe", "Created": "2026-10-08T10:00:03"},     # 손자
    {"Id": 200, "ParentId": 100, "Name": "node.exe", "Created": "2026-10-07T09:00:00"},       # 죽은 옛 부모 번호를 물려받은 남의 프로세스(부모보다 먼저 생김)
    {"Id": 201, "ParentId": 200, "Name": "node.exe", "Created": "2026-10-07T09:00:05"},       # 그 아래 — 모으면 안 됨
    {"Id": 300, "ParentId": 100, "Name": "secret.exe", "Created": None},                     # 시작 시각을 못 읽는 프로세스
]


def test_자식은_부모보다_늦게_생긴_것만_모은다() -> None:
    ids = ps(ROWS, "Get-OwnedDescendants $Table 100 | ForEach-Object { $_.Id }")
    assert ids == [102, 101]  # 깊은 자식이 먼저 · 200 · 201 · 300 은 빠짐


def test_기록된_창은_기록_시각_전에_생겼을_때만_우리_것() -> None:
    assert ps(ROWS, "Test-RecordedRow $Table 100 '2026-10-08T10:00:10'") == [True]
    # PID 재사용 — 기록(10-08 09:00) 뒤에 생긴 프로세스가 같은 번호
    assert ps(ROWS, "Test-RecordedRow $Table 100 '2026-10-08T09:00:00'") == [False]


def test_시작_시각을_못_읽거나_기록_시각이_없으면_남의_것() -> None:
    assert ps(ROWS, "Test-RecordedRow $Table 300 '2026-10-08T10:00:10'") == [False]
    assert ps(ROWS, "Test-RecordedRow $Table 100 ''") == [False]
    assert ps(ROWS, "Test-RecordedRow $Table 999 '2026-10-08T10:00:10'") == [False]  # 없는 번호
    assert ps(ROWS, "Get-OwnedDescendants $Table 300 | ForEach-Object { $_.Id }") in (None, [])  # 뿌리 시각을 모르면 아무것도 모으지 않음
