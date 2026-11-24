"""검사 실행은 멱등이고, 결과 파일은 무한히 쌓이지 않는다 (ISSUE-003).

## 무엇을 막는가

대시보드를 한 번 열면 `POST /api/auditor/run` 이 나가고, 저장된 초안을 **다시** 검사해
새 파일을 만들었다. 13일 만에 546개 16MB 가 쌓였고 그중 80개는 바이트까지 같았다.
`load_run` 은 폴더 전체를 훑으므로 조회도 점점 느려진다. 「실행 기록」에는 매번 다른
id 가 찍혀 «무엇이 바뀌었나»를 추적할 수 없었다.

같은 초안을 같은 요구사항 집합으로 검사하면 결과도 같다. 그러면 다시 계산할 이유도,
새 파일을 만들 이유도 없다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.organization import AnalysisContext
from app.services import auditor_service

PID = "synthetic-rfp-0001"
DRAFT = "본 사업은 교육 20회를 운영하며 만족도 조사를 실시합니다."


def _runs(folder: Path) -> list[Path]:
    return sorted(folder.glob("audit-*.json")) if folder.exists() else []


def test_같은_입력이면_새_파일을_만들지_않는다(audit_run_dir: Path) -> None:
    first = auditor_service.run_and_store(PID, DRAFT, use_llm=False)
    after_first = _runs(audit_run_dir)
    second = auditor_service.run_and_store(PID, DRAFT, use_llm=False)
    after_second = _runs(audit_run_dir)

    assert first.id == second.id, "같은 입력인데 id 가 달라졌다 — 추적이 끊긴다"
    assert len(after_first) == len(after_second) == 1


def test_초안이_바뀌면_다른_결과다(audit_run_dir: Path) -> None:
    first = auditor_service.run_and_store(PID, DRAFT, use_llm=False)
    second = auditor_service.run_and_store(PID, DRAFT + " 추가 문장.", use_llm=False)
    assert first.id != second.id
    assert len(_runs(audit_run_dir)) == 2


def test_회사와_근거범위가_다르면_다른_결과다() -> None:
    """근거가 다르면 검사 결과도 다르다 — 한 파일로 합치면 안 된다."""
    a = auditor_service.run_key(
        PID, DRAFT, requirement_set_hash="h", mode="standard", use_llm=False,
        context=AnalysisContext(organization_id="org-a", evidence_scope="public_demo"),
    )
    b = auditor_service.run_key(
        PID, DRAFT, requirement_set_hash="h", mode="standard", use_llm=False,
        context=AnalysisContext(organization_id="org-b", evidence_scope="public_demo"),
    )
    assert a != b


def test_변경영향_분석은_일반_검사와_섞이지_않는다() -> None:
    standard = auditor_service.run_key(PID, DRAFT, requirement_set_hash="h", mode="standard", use_llm=False)
    impact = auditor_service.run_key(PID, DRAFT, requirement_set_hash="h", mode="change_impact", use_llm=False)
    assert standard != impact


def test_요구사항_집합이_바뀌면_다시_검사한다() -> None:
    """같은 초안이라도 기준이 바뀌면 결과가 달라진다."""
    before = auditor_service.run_key(PID, DRAFT, requirement_set_hash="old", mode="standard", use_llm=False)
    after = auditor_service.run_key(PID, DRAFT, requirement_set_hash="new", mode="standard", use_llm=False)
    assert before != after


def test_점검_규칙_판이_바뀌면_옛_결과를_돌려주지_않는다(audit_run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P1-04 · UI c — 규칙을 고친 뒤에도 같은 초안이면 10-11 옛 결과(단정 32건 · 필수 58 · 74문장)가 그대로 나왔다."""
    before = auditor_service.run_key(PID, DRAFT, requirement_set_hash="h", mode="standard", use_llm=False)
    old = auditor_service.run_and_store(PID, DRAFT, use_llm=False)
    monkeypatch.setattr(auditor_service, "AUDIT_LOGIC_VERSION", auditor_service.AUDIT_LOGIC_VERSION + 1)
    assert auditor_service.run_key(PID, DRAFT, requirement_set_hash="h", mode="standard", use_llm=False) != before
    new = auditor_service.run_and_store(PID, DRAFT, use_llm=False)
    assert new.id != old.id
    assert len(_runs(audit_run_dir)) == 2


def test_보존_상한을_넘으면_오래된_것부터_지운다(audit_run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auditor_service, "RUN_HISTORY_LIMIT", 3)
    for i in range(6):
        auditor_service.run_and_store(PID, f"{DRAFT} v{i}", use_llm=False)
    assert len(_runs(audit_run_dir)) == 3


def test_다른_공고의_결과는_지우지_않는다(audit_run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """정리는 «그 공고의» 결과만 본다. 남의 이력을 지우면 안 된다."""
    monkeypatch.setattr(auditor_service, "RUN_HISTORY_LIMIT", 1)
    other = auditor_service.run_and_store(PID, f"{DRAFT} 다른 초안", use_llm=False)
    # 다른 공고인 척 파일 하나를 바꿔 둔다.
    path = audit_run_dir / f"{other.id}.json"
    payload = path.read_text(encoding="utf-8").replace(f'"{PID}"', '"g2b-OTHER-000"', 1)
    path.write_text(payload, encoding="utf-8")

    for i in range(3):
        auditor_service.run_and_store(PID, f"{DRAFT} v{i}", use_llm=False)

    names = {p.name for p in _runs(audit_run_dir)}
    assert path.name in names, "다른 공고의 결과가 정리에 휩쓸렸다"
