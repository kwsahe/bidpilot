"""사업계획서 작성 — Codex CLI 공급자 (29차 §3-A · prompt_19).

CLI 는 부르지 않는다 — `llm_client._run_codex` 를 가짜로 바꿔 끼워 인자 · stdin · 환경 · 스키마 파일 · 결과 파일을 잰다.
30차 R29-07 — `_run_codex` 자체는 가짜 Popen(이벤트 흐름)으로 잰다: 도구 항목이 시작되면 그 자리에서 트리를 끊는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core.config import get_settings
from app.services import llm_client

FAKE_CODEX = r"C:\fake\codex.exe"


class _Out(BaseModel):
    title: str
    note: str | None = None
    count: int = 0


def _events(*items: dict, usage: dict | None = None) -> str:
    rows = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"}, *items]
    if usage is not None:
        rows.append({"type": "turn.completed", "usage": usage})
    return "\n".join(json.dumps(r) for r in rows)


@pytest.fixture()
def codex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """켜진 문 + 가짜 Codex. 호출마다 인자 · stdin · 환경 · 스키마를 모으고, 정해 둔 답을 결과 파일에 쓴다."""
    settings = get_settings()
    monkeypatch.setattr(settings, "plan_writer_cli", True)
    monkeypatch.setattr(settings, "llm_live", False)
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "llm_usage.jsonl")
    monkeypatch.setattr(llm_client, "codex_cli_path", lambda: FAKE_CODEX)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    state: dict = {"calls": [], "answers": [], "usage": {"input_tokens": 900, "cached_input_tokens": 100, "output_tokens": 40,
                                                          "reasoning_output_tokens": 7}}

    def fake_run(args, **kwargs):
        args = list(args)
        assert "timeout" in kwargs and "capture_output" not in kwargs  # 30차 — 스트리밍(_run_codex) 길
        schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        state["calls"].append({"args": args, "input": kwargs.get("input"), "env": kwargs.get("env"), "schema": schema,
                               "cwd": kwargs.get("cwd")})
        answer = state["answers"].pop(0) if state["answers"] else {"answer": {"title": "제목", "note": None, "count": 2}}
        if "answer" in answer:
            Path(args[args.index("-o") + 1]).write_text(json.dumps(answer["answer"], ensure_ascii=False), encoding="utf-8")
        stdout = answer.get("stdout") or _events({"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
                                                  usage=state["usage"])
        return SimpleNamespace(returncode=answer.get("returncode", 0), stdout=stdout, stderr=answer.get("stderr", ""))

    monkeypatch.setattr(llm_client, "_run_codex", fake_run)
    return state


def _usage_rows(tmp_path_log: Path) -> list[dict]:
    return [json.loads(line) for line in tmp_path_log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_codex_args_stdin_env_schema_and_result(monkeypatch: pytest.MonkeyPatch, codex: dict) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-pass")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CODEX_SOMETHING", "x")
    monkeypatch.setenv("CODEX_HOME", r"C:\codex-home")
    out = llm_client.complete_structured(system="시스템 지시", user="허용 목록 본문", schema=_Out, plan_writer=True, writer="codex",
                                         purpose="plan_draft:시험")
    assert out == _Out(title="제목", note=None, count=2)
    call = codex["calls"][0]
    args = call["args"]
    assert args[:3] == [FAKE_CODEX, "exec", "-"]
    for flag in ("--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--json"):
        assert flag in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("-C") + 1] == call["cwd"]
    assert "shell_tool" in args and "-m" not in args  # 모델을 비우면 CLI 기본
    # 본문은 stdin — 시스템 지시 + 본문
    assert "시스템 지시" in call["input"] and "허용 목록 본문" in call["input"]
    assert "허용 목록 본문" not in " ".join(args)
    # 구독 로그인만 — API 키 · 다른 주소 · CODEX_* 는 빼고 CODEX_HOME 은 남긴다
    env = call["env"]
    assert "OPENAI_API_KEY" not in env and "OPENAI_BASE_URL" not in env and "CODEX_SOMETHING" not in env
    assert env.get("CODEX_HOME") == r"C:\codex-home"
    # 엄격한 스키마 — 모든 칸 필수 · 더 붙이지 않기 · default 없음
    schema = call["schema"]
    assert schema["additionalProperties"] is False and sorted(schema["required"]) == ["count", "note", "title"]
    assert "default" not in json.dumps(schema)
    # 누계 줄 — provider codex_cli · 토큰
    row = _usage_rows(llm_client.USAGE_LOG)[-1]
    assert row["provider"] == "codex_cli" and row["model"] == llm_client.CODEX_CLI_DEFAULT_MODEL_LABEL and row["result"] == "ok"
    assert row["prompt_tokens"] == 900 and row["completion_tokens"] == 40 and row["reasoning_tokens"] == 7
    assert "sk-should-not-pass" not in llm_client.USAGE_LOG.read_text(encoding="utf-8")


def test_codex_model_flag_when_configured(monkeypatch: pytest.MonkeyPatch, codex: dict) -> None:
    monkeypatch.setattr(get_settings(), "codex_cli_model", "gpt-5.5-codex")
    llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    args = codex["calls"][0]["args"]
    assert args[args.index("-m") + 1] == "gpt-5.5-codex"


@pytest.mark.parametrize(("stdout", "stderr", "expect"), [
    (_events({"type": "error", "message": "Not logged in. Run codex login"}), "", "로그인"),
    (_events({"type": "turn.failed", "error": {"message": json.dumps({"error": {"message": "You've hit your usage limit."}})}}), "", "사용 한도"),
    ("", "boom", "Codex CLI 실패(exit 1) — boom"),
])
def test_codex_failure_reasons(codex: dict, stdout: str, stderr: str, expect: str) -> None:
    codex["answers"] = [{"stdout": stdout, "stderr": stderr, "returncode": 1}]
    with pytest.raises(llm_client.LLMUnavailableError, match=re.escape(expect)):
        llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert len(codex["calls"]) == 1


def test_codex_tool_use_discards_answer(codex: dict) -> None:
    """끌 수 없는 도구(exec)를 모델이 썼다 — 답을 버린다."""
    codex["answers"] = [{"answer": {"title": "t", "note": None, "count": 0},
                         "stdout": _events({"type": "item.completed", "item": {"type": "command_execution", "command": "type x"}},
                                           usage={"input_tokens": 1, "output_tokens": 1})}]
    with pytest.raises(llm_client.LLMUnavailableError, match="도구"):
        llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert _usage_rows(llm_client.USAGE_LOG)[-1]["tool_items"] == ["command_execution"]


def test_token_race_retries_once(codex: dict) -> None:
    """로그인 토큰 갱신 겹침만 한 번 다시 부른다 (R28-16). 두 번째도 겹치면 사유를 돌려준다."""
    race = {"stdout": _events({"type": "error", "message": "Failed to refresh OAuth token: another process"}), "returncode": 1}
    codex["answers"] = [race]
    out = llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert out.title == "제목" and len(codex["calls"]) == 2
    codex["calls"].clear()
    codex["answers"] = [race, race]
    with pytest.raises(llm_client.LLMUnavailableError, match="refresh"):
        llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert len(codex["calls"]) == 2


def test_claude_token_race_retries_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Claude 쪽도 같은 규칙 (R28-16)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "plan_writer_cli", True)
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "u.jsonl")
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: r"C:\fake\claude.exe")
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    calls: list[int] = []

    def fake_run(args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            body = {"is_error": True, "result": "Failed to refresh OAuth token: another Claude Code process is refreshing"}
            return SimpleNamespace(returncode=1, stdout=json.dumps(body), stderr="")
        body = {"is_error": False, "structured_output": {"title": "ok", "note": None, "count": 1}, "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    out = llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True)
    assert out.title == "ok" and len(calls) == 2


def test_writer_gate_and_unknown_writer(monkeypatch: pytest.MonkeyPatch, codex: dict) -> None:
    monkeypatch.setattr(llm_client, "codex_cli_path", lambda: None)
    with pytest.raises(llm_client.LLMUnavailableError) as exc:
        llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert str(exc.value) == llm_client.PLAN_WRITER_NO_CODEX_REASON
    assert llm_client.plan_writer_ready("gemini") == (False, llm_client.PLAN_WRITER_UNKNOWN_REASON)
    monkeypatch.setattr(get_settings(), "plan_writer_cli", False)
    assert llm_client.plan_writer_ready("codex") == (False, llm_client.PLAN_WRITER_OFF_REASON)
    assert codex["calls"] == []


def test_codex_status_reads_login_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "plan_writer_cli", True)
    monkeypatch.setattr(llm_client, "codex_cli_path", lambda: FAKE_CODEX)
    seen: list[list[str]] = []

    def fake_run(args, **kwargs):
        seen.append(list(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="Logged in using ChatGPT\n")

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    status = llm_client.codex_cli_status()
    assert status["cli"] is True and status["logged_in"] is True and status["auth_method"] == "chatgpt"
    assert status["training_reminder"] is True
    assert seen == [[FAKE_CODEX, "login", "status"]]  # 모델을 부르지 않는다


class _FakePopen:
    """가짜 Codex 프로세스 — 정해 둔 이벤트 줄을 stdout 으로 흘린다. 끊기면 그 뒤 줄은 나오지 않는다."""

    def __init__(self, rows: list[dict], log: list[str]) -> None:
        self.pid, self.returncode, self._log = 4242, None, log
        self._rows = [json.dumps(r) + "\n" for r in rows]
        self.stdin = SimpleNamespace(write=lambda text: log.append("stdin"), close=lambda: None)
        self.stderr = iter(())
        self.killed = False

    @property
    def stdout(self):
        for row in self._rows:
            if self.killed:
                return
            self._log.append("line")
            yield row

    def wait(self, timeout=None):
        self.returncode = -9 if self.killed else 0
        return self.returncode

    def kill(self):
        self.killed = True


def test_30차_도구_항목이_시작되면_그_자리에서_트리를_끊는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """R29-07 — 예전에는 프로세스가 끝난 뒤 도구 사용을 보고 답을 버렸다(읽힌 파일 내용은 이미 나간 뒤)."""
    log: list[str] = []
    rows = [{"type": "thread.started"}, {"type": "item.started", "item": {"type": "reasoning"}},
            {"type": "item.started", "item": {"type": "command_execution", "command": "type secret.txt"}},
            {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "SECRET"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1}}]
    proc = _FakePopen(rows, log)
    killed: list[int] = []
    monkeypatch.setattr(llm_client.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(llm_client, "_kill_tree", lambda p: (killed.append(p.pid), p.kill()))
    result = llm_client._run_codex(["codex"], input="본문", timeout=30, cwd=".", env={})
    assert result.tool == "command_execution" and killed == [4242] and not result.timed_out
    assert "aggregated_output" not in result.stdout and len(result.stdout.splitlines()) == 3  # 도구가 시작된 줄에서 멈춤


def test_30차_도구로_멈추면_그_절은_실패_사유는_한_줄(codex: dict) -> None:
    from types import SimpleNamespace as NS

    import app.services.llm_client as lc

    def stopped(args, **kwargs):
        return NS(returncode=-9, stdout="", stderr="", tool="command_execution", timed_out=False)

    lc._run_codex = stopped  # codex 픽스처가 monkeypatch 로 되돌린다
    with pytest.raises(llm_client.LLMUnavailableError) as exc:
        llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert str(exc.value).startswith(llm_client.CODEX_TOOL_STOP)
    assert _usage_rows(llm_client.USAGE_LOG)[-1]["tool_items"] == ["command_execution"]


def test_30차_시간_초과는_트리를_끊고_시간_초과로(codex: dict) -> None:
    from types import SimpleNamespace as NS

    import app.services.llm_client as lc

    lc._run_codex = lambda args, **kwargs: NS(returncode=-9, stdout="", stderr="", tool=None, timed_out=True)
    with pytest.raises(llm_client.LLMUnavailableError) as exc:
        llm_client.complete_structured(system="s", user="u", schema=_Out, plan_writer=True, writer="codex")
    assert "답하지 않았습니다" in str(exc.value)


def test_claude_로그인이_끝났으면_한국어로_다시_로그인하라고_한다() -> None:
    """35차 §4-1 실측 — 「Failed to authenticate: OAuth session expired and could not be refreshed」가 영어 그대로 화면에 나왔다."""
    import subprocess

    from app.services import llm_client

    proc = subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr="")
    text = llm_client._cli_failure({"result": "Failed to authenticate: OAuth session expired and could not be refreshed"}, proc)
    assert text.startswith("Claude 로그인이 끝났습니다") and "claude auth login" in text
    race = llm_client._cli_failure({"result": "Failed to refresh OAuth token: another Claude Code process is refreshing"}, proc)
    assert not race.startswith("Claude 로그인이 끝났습니다")
