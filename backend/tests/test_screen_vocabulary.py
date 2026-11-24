"""백엔드가 만드는 **화면 문장**에 영문 판정값이 섞이지 않는다 (0922 §4-D-6 · 규칙 11).

## 왜 필요한가

화면 어휘 검사(`scripts/check_screen_vocabulary.mjs`)는 프런트 소스만 본다. 그런데 화면에
찍히는 문장의 상당수는 **백엔드가 만든다** — 자격 판정의 `reason`, 제출 전 점검의
`recommendation`, 게이트 사유. 거기에 저장 값을 그대로 적으면 사전을 거치지 않고 화면에
나간다.

실제로 그렇게 새고 있었다 (2026-09-18 발견):

    auditor_service.py — 「… 조건은 원문만으로 충족을 확정할 수 없어 CHECK 상태입니다.」

와이어프레임·대시보드의 제출 전 점검 결과에 그대로 찍혔다. 프런트 검사로는 잡을 수 없었다.

## 무엇을 재는가

`app/services/**.py` 의 **한국어가 섞인 문자열 리터럴**에 `PASS`·`CHECK`·`FAIL`·`GO`·
`HOLD`·`NO_GO` 같은 저장 값이 들어 있으면 실패다. 비교식·딕셔너리 키·타입은 한국어가 없어
자연히 빠진다.

완벽한 파서가 아니다. 새는 모양이 늘면 여기에 규칙을 더한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / "app"

#: 화면 문장에 있으면 안 되는 저장 값. 낱말 경계로 찾는다.
FORBIDDEN = ("PASS", "CHECK", "FAIL", "NO_GO", "NO-GO", "GO", "HOLD", "UNREVIEWED", "BLOCKER")

#: 한국어가 한 글자라도 있으면 «사람에게 보여 주는 문장»으로 본다.
HAS_KOREAN = re.compile(r"[가-힣]")

#: 예외 — 화면 문장이 아니라 **개발자가 읽는 것**.
#:
#: `_note`/docstring 은 저장 파일의 머리말이고, 로그는 화면에 가지 않는다. 그래도 함수
#: 이름으로 가르는 대신 **파일 단위**로만 뺀다 — 규칙이 단순해야 다음 사람이 지킨다.
ALLOWED_FILES = {
    # 규칙 id 자체를 다루는 곳. 「ELIG-INDUSTRY 가 FAIL 이면」 같은 설명이 주석에 있다.
    "services/eligibility_gap_service.py",
    # 저장된 옛 글(「… CHECK 상태입니다」)을 **찾아서 새 말로 바꾸는** 표 — 화면에 내보내는 글이 아니다(32차 §3-E-2).
    "services/wording.py",
}


def _screen_strings(path: Path) -> list[tuple[int, str]]:
    """파일 안의 문자열 리터럴 중 한국어가 든 것. docstring 은 뺀다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if HAS_KOREAN.search(node.value):
                out.append((node.lineno, node.value))
    return out


def test_백엔드가_만드는_문장에_영문_판정값이_없다() -> None:
    offenders: list[str] = []
    for path in sorted(SERVICES.rglob("*.py")):
        rel = path.relative_to(SERVICES).as_posix()
        if rel in ALLOWED_FILES:
            continue
        for lineno, text in _screen_strings(path):
            for word in FORBIDDEN:
                if re.search(rf"(^|[^A-Za-z_]){re.escape(word)}([^A-Za-z_]|$)", text):
                    offenders.append(f"{rel}:{lineno} 「{word}」 — {text[:70]}")
                    break
    assert not offenders, "화면 문장에 저장 값이 새어 나갑니다:\n" + "\n".join(offenders)
