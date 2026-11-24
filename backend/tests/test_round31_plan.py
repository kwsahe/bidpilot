"""31차 §3-F — 과제소개서 · 사업계획서 · Codex (recheck23 R30-18~26 · 38 · 39).

- 과제소개서 절 자르기(R30-21) · 읽기 실패는 다시 읽지 않음(R30-20) · 색인은 늦게 받은 기록(R30-24)
- 내부 말 검사: 「해당없음입니다」는 양식이 요구하면 본문(R30-22) · 작성 사정 꼴로만(R30-23 · RAG 기술 문장은 남음)
- 기본 초안 머리말은 행 분야로(R30-25) · 제출용 · 검토용 번호 같게(R30-26) · 요약 상자 거름(R30-38) · 연번 자동(R30-39)
- Codex 진짜 프로세스(가짜 codex 스크립트): 도구 → 곧바로 끊김 · 끝난 뒤 손자가 남아도 시간 초과 아님 · 큰 stderr 교착 없음(R30-18 · 19)
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.services import bizinfo_document_store, llm_client, plan_draft_service, plan_export_service, plan_form_service
from app.services.bizinfo_document_store import DocumentIndex, DocumentRecord

HUMAN = plan_form_service.HUMAN_INPUT

# ---------------------------------------------------------------------------
# 과제소개서
# ---------------------------------------------------------------------------


def test_다른_과제로_시작하는_줄에서_앞_절이_끝나고_머리만_있는_조각은_버린다() -> None:
    text = "\n".join([
        "과제1 국가데이터처 과제소개서",
        "◦ (개요) 지표",
        "과제 2 일정 안내는 붙임 참고",  # 머리 꼴이 아니어도 다른 과제가 시작 — 1번 절은 여기서 끝
        "◦ (개요) 섞이면 안 되는 줄",
        "과제3 과제소개서",  # 기관 이름 없음 — 과제 머리가 아니다
        "◦ 내용",
        "과제4 한국공항공사 과제소개서",  # 본문 없는 조각(목차)
    ])
    sections = plan_form_service.annex_sections(text)
    assert sections[1] == "과제1 국가데이터처 과제소개서\n◦ (개요) 지표"
    assert 3 not in sections and 4 not in sections


def test_같은_번호_머리가_되풀이되면_이어_붙이고_떨어진_곳은_가장_긴_것() -> None:
    text = "\n".join([
        "과제7 기상청 과제소개서",  # 개요 목록의 짧은 조각
        "◦ 요약 한 줄",
        "과제8 해양수산부 과제소개서",
        "◦ (개요) 바다",
        "과제7 기상청 과제소개서",  # 본문 시작
        "◦ (개요) 날씨 데이터",
        "◦ (문제점) 흩어져 있다",
        "과제7 기상청 과제소개서",  # 쪽마다 되풀이되는 머리 — 같은 절
        "□ 협업 및 활용 계획",
    ])
    seven = plan_form_service.annex_sections(text)[7]
    assert "날씨 데이터" in seven and "협업 및 활용 계획" in seven and "요약 한 줄" not in seven


def test_읽기_실패로_적힌_과제소개서는_화면을_열_때마다_다시_읽지_않는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import document_extractor

    monkeypatch.setattr(bizinfo_document_store, "DOCS_DIR", tmp_path)
    (tmp_path / "PBLN_Z.annex1.pdf").write_bytes(b"%PDF-1.4 broken")
    failed = DocumentRecord(program_id="PBLN_Z", status="failed", note="원문 읽기 실패")
    monkeypatch.setattr(bizinfo_document_store, "annex_record", lambda pid: failed if pid == "PBLN_Z" else None)
    calls: list[Path] = []
    monkeypatch.setattr(document_extractor, "extract_document", lambda path: calls.append(path))
    assert plan_form_service.annex_excerpt("bizinfo-PBLN_Z", {"no": 1}) is None
    assert calls == []


def test_색인은_같은_공고면_늦게_받은_기록을_남긴다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core import storage

    monkeypatch.setattr(bizinfo_document_store, "INDEX_FILE", tmp_path / "index.json")
    newer = DocumentRecord(program_id="PBLN_A", status="text", downloaded_at="2026-10-04T10:00:00+00:00", pages=99)
    storage.write_json_atomic(tmp_path / "index.json", {"records": [], "annexes": [newer.to_dict()]})
    stale = DocumentIndex(records={}, annexes={"PBLN_A": DocumentRecord(program_id="PBLN_A", status="failed", downloaded_at="2026-10-01T09:00:00+00:00")})
    bizinfo_document_store.save_index(stale)
    saved = storage.read_json(tmp_path / "index.json", default={})
    assert saved["annexes"][0]["status"] == "text" and saved["annexes"][0]["pages"] == 99


# ---------------------------------------------------------------------------
# 내부 말 · 머리말
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "제공된 자료만으로는 확인할 수 없어 담당자가 채웁니다.",
    "주어진 정보로는 알 수 없습니다.",
    "근거 조각에는 실적이 없습니다.",
    "근거가 없어 단정하지 않았습니다.",
    "숫자를 지어내지 않고 빈칸으로 두었습니다.",
    "과제소개서 발췌에 따르면 기관 현황은 다음과 같습니다.",
])
def test_작성_사정_꼴은_내부_말이다(text: str) -> None:
    assert plan_draft_service._INTERNAL_RE.search(text), text


@pytest.mark.parametrize("text", [
    "RAG 파이프라인은 주어진 자료에서 근거 조각을 찾아 답변과 함께 보여 줍니다.",
    "AI가 답을 지어내지 않도록 제공된 정보만으로 답변합니다.",
    "상담 AI는 진단을 단정하지 않도록 의료 경계 규칙을 둡니다.",
])
def test_AI_RAG_과제의_기술_문장은_남는다(text: str) -> None:
    assert not plan_draft_service._INTERNAL_RE.search(text), text


def test_양식이_없을_시_해당없음을_요구하면_본문에_남는다() -> None:
    assert plan_draft_service._NONE_RE.search("유사 개발 이력은 해당없음입니다.")
    assert plan_draft_service._GUIDE_NONE_RE.search("유사 개발 이력(없을 시 「해당없음」 기재)")
    assert not plan_draft_service._GUIDE_NONE_RE.search("유사 개발 이력을 적습니다")


@pytest.mark.parametrize(("field", "head"), [
    ("대학·교육기관", "수행 실적 후보"),
    ("지원사업·기관자격", "지정 · 선정 후보"),
    ("지식재산", "지식재산 후보"),
])
def test_기본_초안_머리말은_행_분야로(field: str, head: str) -> None:
    assert plan_draft_service._ledger_head({"field": field}) == head


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------


def _draft() -> dict:
    return {"sections": [
        {"major_title": "과제 해결 방안", "section": "해결 방안", "sentences": [{"text": "공공데이터로 상담 흐름을 만듭니다."}]},
        {"major_title": "과제 해결 방안", "section": "산출물 (선택)", "optional": True, "sentences": [{"text": f"산출물: {HUMAN}"}]},
        {"major_title": "과제 해결 방안", "section": "추진 체계", "sentences": [{"text": "공공데이터로 상담 흐름을 만듭니다."}]},
        {"major_title": "기업 역량", "section": "참고 (선택)", "optional": True, "sentences": [{"text": f"비고: {HUMAN}"}]},
        {"major_title": "추진 일정", "section": "일정", "sentences": [{"text": "1~2개월차에 설계합니다."}]},
    ], "tables": []}


def _heads(variant: str) -> list[str]:
    blocks = plan_export_service.document_blocks(_draft(), {}, variant=variant, meta={})
    return [b[1] for b in blocks if b[0] in ("h1", "h2")]


def test_제출용은_뺀_절의_번호를_건너뛰어_검토용과_번호가_같다() -> None:
    review, submit = _heads("review"), _heads("submit")
    assert "1-2. 산출물" in review and "1-2. 산출물" not in submit
    assert "1-3. 추진 체계" in review and "1-3. 추진 체계" in submit  # 다시 매기지 않는다
    assert "2. 기업 역량" in review and not any(h.startswith("2.") for h in submit)
    assert "3. 추진 일정" in submit


def test_요약_상자는_같은_문장을_한_번만() -> None:
    blocks = plan_export_service.document_blocks(_draft(), {}, variant="review", meta={})
    summaries = [b[1] for b in blocks if b[0] == "summary"]
    assert all(len(lines) == len(set(lines)) for lines in summaries)
    assert plan_export_service._similar("공공데이터로 상담 흐름을 만듭니다.", "공공데이터로  상담 흐름을 만듭니다")


def test_연번_칸은_1_2_3_으로_채운다() -> None:
    table = plan_export_service._clean_table({"title": "인력 구성", "columns": ["연번", "직무", "인원"],
                                              "rows": [[HUMAN, HUMAN, HUMAN], [HUMAN, "개발", "2명"]]})
    assert [row[0] for row in table["rows"]] == ["1", "2"] and table["rows"][0][1] == HUMAN


# ---------------------------------------------------------------------------
# Codex — 진짜 프로세스 (가짜 codex 스크립트)
# ---------------------------------------------------------------------------

FAKE_CODEX = textwrap.dedent('''
    import json, subprocess, sys, time
    mode = sys.argv[1]
    sys.stdin.read()
    if mode == "tool":
        print(json.dumps({"type": "item.started", "item": {"type": "command_execution"}}), flush=True)
        time.sleep(30)
    elif mode == "grandchild":
        # 손자가 stdout 을 물려받아 쥔 채 남는다 — 본 프로세스는 바로 끝난다
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "끝"}}), flush=True)
    elif mode == "stderr":
        sys.stderr.write("x" * 3_000_000)
        sys.stderr.flush()
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "끝"}}), flush=True)
''')


@pytest.fixture()
def fake_codex(tmp_path: Path) -> Path:
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE_CODEX, encoding="utf-8")
    return script


def _run(script: Path, mode: str, tmp_path: Path, timeout: float = 20.0):
    started = time.monotonic()
    proc = llm_client._run_codex([sys.executable, str(script), mode], input="질문", timeout=timeout, cwd=str(tmp_path), env=dict(os.environ))
    return proc, time.monotonic() - started


def test_도구_항목이_나오면_곧바로_트리를_끊는다(fake_codex: Path, tmp_path: Path) -> None:
    proc, took = _run(fake_codex, "tool", tmp_path)
    assert proc.tool == "command_execution" and not proc.timed_out
    assert took < 6, took  # 30초 잠든 프로세스를 기다리지 않는다


def test_끝난_뒤_손자가_남아도_시간_초과가_아니다(fake_codex: Path, tmp_path: Path) -> None:
    proc, took = _run(fake_codex, "grandchild", tmp_path)
    assert not proc.timed_out and proc.tool is None and "agent_message" in proc.stdout
    assert took < 10, took


@pytest.mark.skipif(os.name != "nt", reason="Job Object 는 Windows 에만")
def test_정상_종료에도_작업_핸들을_닫는다(fake_codex: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs: list = []
    attach = llm_client._WinJob.attach.__func__

    def spy(cls, pid: int):
        job = attach(cls, pid)
        jobs.append(job)
        return job

    monkeypatch.setattr(llm_client._WinJob, "attach", classmethod(spy))
    proc, _ = _run(fake_codex, "stderr", tmp_path)
    assert not proc.timed_out and proc.tool is None
    assert jobs and all(job is not None and job.handle == 0 for job in jobs)


def test_큰_stderr_도_교착_없이_끝난다(fake_codex: Path, tmp_path: Path) -> None:
    proc, took = _run(fake_codex, "stderr", tmp_path)
    assert not proc.timed_out and "agent_message" in proc.stdout and len(proc.stderr) >= 1_000_000
    assert took < 15, took
