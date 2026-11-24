"""완성 공급자 `claude_cli` — 키 없이 이 PC 에 로그인된 Claude Code CLI(구독)로 쓴다 (25차 §4-F 담당자 제안).

담당자: 「API 쓰지 않고 클로드 코드 CLI 랑 연결시키는 게 어때?」 여기서 재는 것:

- **문** — 키가 아니라 CLI 실행 파일이 완성 문이다. 임베딩 문(OpenAI 키)은 그대로다.
- **크레딧 문은 늘 연다** — 구독이라 선불 크레딧이 없고, 사용 한도 줄이 문을 영원히 닫지 않게.
- **도구 0 · 훅/CLAUDE.md 없음 · 세션 기록 없음 · 빈 임시 폴더** — 모델은 파일을 못 읽는다. 본문은 stdin 으로만.
- **API 키 환경변수는 CLI 에 넘기지 않는다** — 있으면 구독 대신 API 과금으로 간다.
- **시도마다 누계 한 줄** — 토큰 · 추론 토큰 · 정가 환산 비용. 스키마 실패는 다시 요청한다.

CLI 는 부르지 않는다 — `subprocess.run` 을 가짜로 바꿔 끼운다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.config import get_settings
from app.services import llm_client

FAKE_EXE = r"C:\fake\claude.exe"


class _Answer(BaseModel):
    ok: bool = True


def configure(monkeypatch: pytest.MonkeyPatch, *, live: bool = True, model: str = "claude-opus-5-5", effort: str = "") -> None:
    settings = get_settings()
    for name, value in {
        "llm_provider": "claude_cli", "openai_api_key": "", "xai_api_key": "", "llm_model": "gpt-4.1-mini",
        "claude_cli_model": model, "claude_cli_effort": effort, "llm_live": live, "llm_credit_confirmed": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: FAKE_EXE)


@pytest.fixture()
def usage_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_usage.jsonl"
    monkeypatch.setattr(llm_client, "USAGE_LOG", path)
    return path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def payload(structured: Any = None, **extra: Any) -> str:
    body = {
        "type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "duration_ms": 9700,
        "total_cost_usd": 0.0275, "result": json.dumps(structured, ensure_ascii=False) if structured is not None else "",
        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 3754, "cache_read_input_tokens": 100, "output_tokens": 1249,
                  "output_tokens_details": {"thinking_tokens": 1027}},
        "modelUsage": {"claude-opus-5-5": {"inputTokens": 2}},
    }
    if structured is not None:
        body["structured_output"] = structured
    body.update(extra)
    return json.dumps(body, ensure_ascii=False)


class _Calls(list):
    """부른 기록 목록 + 다음에 돌려줄 대답(`replies`)."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: list[Any] = []


@pytest.fixture()
def fake_run(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    """`subprocess.run` 대역 — 부른 인자 · stdin · 폴더 · 환경을 적고 `replies` 를 차례로 돌려준다."""
    calls = _Calls()
    replies = calls.replies

    def _run(args, *, input, cwd, env, timeout, **_kw):
        calls.append({"args": list(args), "input": input, "cwd": cwd, "cwd_files": os.listdir(cwd), "env": dict(env), "timeout": timeout})
        reply = replies.pop(0) if replies else SimpleNamespace(returncode=0, stdout=payload({"ok": True}), stderr="")
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(llm_client.subprocess, "run", _run)
    return calls


# ---------------------------------------------------------------------------
# 1) 문
# ---------------------------------------------------------------------------


def test_CLI_가_있으면_완성_문이_열리고_임베딩_문은_그대로_닫힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    assert llm_client.completion_configured() is True
    assert llm_client.is_configured() is False
    assert llm_client.completion_model() == "claude-opus-5-5"
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: None)
    assert llm_client.completion_configured() is False


def test_크레딧_문은_늘_열린다_사용_한도_줄_뒤에도(monkeypatch: pytest.MonkeyPatch, usage_log: Path) -> None:
    configure(monkeypatch)
    usage_log.write_text(json.dumps({"kind": "completion", "provider": "claude_cli", "result": "429 한도"}) + "\n", encoding="utf-8")
    assert llm_client.credit_ok() is True


def test_다른_공급자_모델_이름은_보내지_않고_별칭은_통과한다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch, model="gpt-4.1-mini")
    with pytest.raises(llm_client.LLMUnavailableError, match="Claude 모델 이름이 아닙니다"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert fake_run == []
    configure(monkeypatch, model="opus")
    assert llm_client.complete_structured(system="s", user="u", schema=_Answer).ok is True


def test_AI_꺼짐이면_CLI_를_부르지_않는다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch, live=False)
    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert fake_run == [] and rows(usage_log) == []


# ---------------------------------------------------------------------------
# 2) 부르는 모양 — 도구 0 · 훅/CLAUDE.md 없음 · 빈 폴더 · stdin · API 키 빼기
# ---------------------------------------------------------------------------


def test_도구_없이_안전_모드로_빈_폴더에서_stdin_으로_부른다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch, effort="medium")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-DO-NOT-PASS")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.example")

    answer = llm_client.complete_structured(system="시스템 지시", user="허용 목록 본문", schema=_Answer, purpose="plan_draft:테스트")

    assert answer.ok is True
    call = fake_run[0]
    args = call["args"]
    assert args[0] == FAKE_EXE and args[1] == "-p"
    for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    assert args[args.index("--system-prompt") + 1] == "시스템 지시"
    assert args[args.index("--effort") + 1] == "medium"
    assert json.loads(args[args.index("--json-schema") + 1])["properties"]["ok"]["type"] == "boolean"
    assert "허용 목록 본문" not in " ".join(args)  # 본문은 명령줄이 아니라 stdin 으로
    assert call["input"] == "허용 목록 본문"
    assert call["cwd_files"] == [] and not Path(call["cwd"]).exists()  # 부를 때 빈 폴더 · 끝나면 지운다
    assert "ANTHROPIC_API_KEY" not in call["env"] and "ANTHROPIC_BASE_URL" not in call["env"]
    assert call["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert call["timeout"] == get_settings().llm_timeout_seconds


def test_누계_한_줄에_토큰_추론_정가환산을_적는다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch)
    llm_client.complete_structured(system="s", user="u", schema=_Answer, purpose="plan_draft:추진 계획")
    [row] = rows(usage_log)
    assert row["kind"] == "completion" and row["provider"] == "claude_cli" and row["model"] == "claude-opus-5-5"
    assert row["purpose"] == "plan_draft:추진 계획" and row["attempt"] == 1 and row["result"] == "ok"
    assert row["prompt_tokens"] == 2 + 3754 + 100 and row["completion_tokens"] == 1249 and row["reasoning_tokens"] == 1027
    assert row["api_equivalent_usd"] == 0.0275 and row["served_model"] == "claude-opus-5-5" and row["turns"] == 2
    assert "DO-NOT" not in usage_log.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3) 실패
# ---------------------------------------------------------------------------


def test_스키마가_틀리면_다시_요청하고_시도마다_적는다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch)
    fake_run.replies.append(SimpleNamespace(returncode=0, stdout=payload({"ok": "아마도"}), stderr=""))
    assert llm_client.complete_structured(system="s", user="본문", schema=_Answer).ok is True
    assert [r["result"] for r in rows(usage_log)] == ["schema_validation_failed", "ok"]
    assert fake_run[1]["input"].startswith("본문") and "스키마 검증에 실패" in fake_run[1]["input"]


def test_사용_한도면_규칙으로_가고_문은_닫지_않는다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch)
    limit = payload(None, is_error=True, subtype="error_during_execution", result="Claude AI usage limit reached|1790000000")
    fake_run.replies.append(SimpleNamespace(returncode=1, stdout=limit, stderr=""))
    with pytest.raises(llm_client.LLMUnavailableError, match="사용 한도"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    [row] = rows(usage_log)
    assert "사용 한도" in row["result"] and "429" not in row["result"]
    assert llm_client.credit_ok() is True


def test_제한_시간을_넘기면_규칙으로_간다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch)
    fake_run.replies.append(subprocess.TimeoutExpired(cmd="claude", timeout=180))
    with pytest.raises(llm_client.LLMUnavailableError, match="답하지 않았습니다"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert rows(usage_log)[0]["result"].startswith("timeout:")


def test_출력이_JSON_이_아니면_실패_사유를_적는다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    configure(monkeypatch)
    fake_run.replies.append(SimpleNamespace(returncode=1, stdout="", stderr="Invalid API key · Please run /login\n"))
    with pytest.raises(llm_client.LLMUnavailableError, match="Claude 로그인이 끝났습니다"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert "run /login" in rows(usage_log)[0]["result"]


# ---------------------------------------------------------------------------
# 4) 절을 동시에 쓴다 — 추론 모델로도 5분 안에
# ---------------------------------------------------------------------------


def test_사업계획서_절은_동시에_쓰되_상한_수를_넘지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import plan_draft_service, plan_form_service, support_requirement_extractor
    from tests.test_plan_form import FULL

    in_flight, peak, lock = [0], [0], threading.Lock()

    def _fake(**kwargs):
        with lock:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        time.sleep(0.05)
        with lock:
            in_flight[0] -= 1
        if kwargs["purpose"] == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return plan_draft_service.PlanSectionOut()

    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))
    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    form = plan_form_service.extract_form("bizinfo-PBLN_000000000126482", FULL)
    form["selected_task"] = next(t for t in form["tasks"] if t["no"] == 4)
    draft = plan_draft_service.generate(
        program=SimpleNamespace(id="PBLN_000000000126482"), form=form,
        requirements=support_requirement_extractor.extract_from_text("PBLN_000000000126482", FULL),
        company={"profile": {}, "capacity": {}, "ledger": []}, facts=[], matches=[], notice_text=FULL, annex=None, company_name="주식회사 시험",
    )
    assert 2 <= peak[0] <= plan_draft_service.PARALLEL_WRITES
    assert draft["attempts"]["logical_calls"] == 9  # 절 8 + 검토 1 (약점 없음 → 고침 0)
    assert [s["section"] for s in draft["sections"] if s["by"] == "llm"][:2] == ["공공데이터 활용 계획", "과제 해결방안"]  # 순서는 양식 그대로



def test_자식_CLI_에는_이_세션의_변수를_넘기지_않는다() -> None:
    """2차 검수 PRIV-1 — 백엔드를 Claude Code 세션 안에서 띄우면 세션 id · 메시지 소켓·토큰이 자식에 따라갔다."""
    env = llm_client.cli_env({
        "PATH": "C:/bin", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CODE_MESSAGING_SOCKET": "sock",
        "CLAUDE_CODE_MESSAGING_TOKEN": "tok", "CLAUDE_CODE_USE_BEDROCK": "1", "ANTHROPIC_API_KEY": "k", "OTEL_EXPORTER": "x",
        "CLAUDE_CODE_GIT_BASH_PATH": "C:/git/bash.exe", "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
    })
    assert env == {"PATH": "C:/bin", "CLAUDE_CODE_GIT_BASH_PATH": "C:/git/bash.exe", "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}


def test_Windows_에서는_exe_만_받는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """26차 ISSUE-153 — npm 판 claude.cmd 는 cmd.exe 가 여러 줄 --system-prompt 를 첫 줄에서 자르고 --model 이 빠진다."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(llm_client, "_WINDOWS", True)
    for name, allowed in (("claude.cmd", False), ("claude.bat", False), ("claude.exe", True)):
        path = tmp_path / name
        path.write_text("", encoding="utf-8")
        monkeypatch.setattr(settings, "claude_cli_path", str(path))
        assert llm_client.claude_cli_candidate() == str(path)
        assert (llm_client.claude_cli_path() == str(path)) is allowed, name
        assert llm_client.completion_configured() is allowed, name
    monkeypatch.setattr(settings, "claude_cli_path", str(tmp_path / "없는" / "claude.exe"))
    assert llm_client.claude_cli_candidate() is None and llm_client.completion_configured() is False


def test_마감이_있으면_시도마다_남은_시간만_쓴다(monkeypatch: pytest.MonkeyPatch, usage_log: Path, fake_run: _Calls) -> None:
    """26차 검수 — 스키마 재요청이 같은 제한 시간을 다시 써서 한 호출이 남은 시간의 세 배까지 걸렸다."""
    configure(monkeypatch)
    ticks = [100.0, 100.0, 130.0, 170.0]  # 마감 = 100 + 60 · 다 쓰면 마지막 값에 머문다(다른 곳이 불러도 깨지지 않게)
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])
    fake_run.replies.extend([SimpleNamespace(returncode=0, stdout=payload({"ok": "아마도"}), stderr="")] * 2)
    with pytest.raises(llm_client.LLMUnavailableError, match="시간 상한"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer, timeout=60)
    assert [c["timeout"] for c in fake_run] == [60.0, 30.0]  # 두 번째 시도는 남은 30초 · 세 번째는 부르지 않는다
    assert rows(usage_log)[-1]["result"].startswith("timeout: 시간 상한")


def test_Windows_에서는_PATH_의_claude_exe_를_먼저_찾는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """26차 검수 — PATH 앞쪽의 npm 판 claude.CMD 가 뒤쪽의 네이티브 claude.exe 를 가렸다."""
    settings = get_settings()
    monkeypatch.setattr(settings, "claude_cli_path", "")
    monkeypatch.setattr(llm_client, "_WINDOWS", True)
    found = {"claude.exe": r"C:\local\claude.exe", "claude": r"C:\npm\claude.CMD"}
    monkeypatch.setattr(llm_client.shutil, "which", lambda name: found.get(name))
    assert llm_client.claude_cli_candidate() == r"C:\local\claude.exe" and llm_client.claude_cli_path() == r"C:\local\claude.exe"
    found.pop("claude.exe")
    assert llm_client.claude_cli_candidate() == r"C:\npm\claude.CMD" and llm_client.claude_cli_path() is None
