"""42차 — 회사 서버(Linux · cron) 가정: 받은 때 한 줄 · crontab 받기 줄 · Codex 꺼짐. 노트북 글은 그대로(호출 없음)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.services import auto_collect, llm_client

KST = timezone(timedelta(hours=9))


def _ok_run(at: datetime) -> str:
    return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True,
                       "결과": [{"출처": "나라장터", "결과": "g2b"}, {"출처": "기업마당", "결과": "bizinfo"}]}, ensure_ascii=False)


def _at(hour: int, minute: int = 0, day: int = 23) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLECT_SCHEDULER", "cron")


def test_서버는_매일_아침_07시30분_서버가_받음(cron: None) -> None:
    auto_collect.LOG_FILE.write_text(_ok_run(_at(7, 31)) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(10))
    assert state["kind"] == "ok" and state["text"] == "매일 아침 07:30 서버가 자동으로 받음 · 오늘 07:31"


def test_서버에서_오늘_아직이면_관리자에게_부탁(cron: None) -> None:
    auto_collect.LOG_FILE.write_text(_ok_run(_at(7, 31, day=22)) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(12))  # 43차 M27 — 11:30 시도까지 지난 뒤에만 경고
    assert state["kind"] == "missed"
    assert state["text"] == "오늘 목록을 아직 받지 않았습니다 — 마지막 10/22 07:31 · 관리자에게 「지금 받기」를 부탁하세요"
    assert ".bat" not in state["text"]


def _failed_run(at: datetime) -> str:
    return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True,
                       "결과": [{"출처": "나라장터", "결과": "g2b", "오류": "시간 초과"}]}, ensure_ascii=False)


@pytest.mark.parametrize(
    ("now", "lines", "want"),
    [
        (_at(1, 57), [], "오늘 07:30에 받을 예정 · 목록은 10/22 07:31"),  # 새벽 헛경고 없음
        (_at(7, 29), [], "오늘 07:30에 받을 예정 · 목록은 10/22 07:31"),
        (_at(9, 0), [_failed_run(_at(7, 32))], "09:30에 다시 받음 · 목록은 10/22 07:31"),  # 07:30 실패 뒤 다시 받기 전
        (_at(11, 0), [_failed_run(_at(7, 32)), _failed_run(_at(9, 32))], "11:30에 다시 받음 · 목록은 10/22 07:31"),
    ],
)
def test_서버는_받을_시각_전이면_경고_대신_받을_예정(cron: None, now: datetime, lines: list[str], want: str) -> None:
    auto_collect.LOG_FILE.write_text("\n".join([_ok_run(_at(7, 31, day=22)), *lines]) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(now)
    assert state["kind"] == "waiting" and state["text"] == want


def test_조달청_점검으로_세_번_못_받은_날은_시도와_원인과_기업마당_시각(cron: None) -> None:
    """10-31 최종 점검 — 07:30 · 09:30 · 11:30 모두 조달청 「시스템 점검 안내」였고 기업마당은 받았다.
    예전 글 「오늘 목록을 아직 받지 않았습니다 … 지금 받기를 부탁」은 시도하지 않은 것처럼 읽히고 원인 · 기업마당을 말하지 않았다."""
    def maintenance(at: datetime) -> str:
        return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True, "결과": [
            {"출처": "나라장터", "결과": "cached", "오류": "… 마지막 오류: G2B API returned non-JSON response: <!DOCTYPE html>"},
            {"출처": "기업마당", "결과": "bizinfo", "조회_시각": at.astimezone(timezone.utc).isoformat(), "오류": None},
        ]}, ensure_ascii=False)
    runs = [_ok_run(_at(7, 31, day=22)), maintenance(_at(7, 30)), maintenance(_at(9, 30)), maintenance(_at(11, 30))]
    auto_collect.LOG_FILE.write_text("\n".join(runs) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(16))
    assert state["kind"] == "missed"
    assert state["text"].startswith("오늘 3번 받으려 했지만 나라장터 목록을 받지 못했습니다 — 마지막 10/22 07:31 · 기업마당은 오늘 11:30 받음")
    assert "시스템 점검" in state["text"] and "지금 받기" not in state["text"]


def test_기업마당을_옛_저장본으로_돌려준_날은_오늘_받음이라_적지_않는다(cron: None) -> None:
    """10-31 독립 검토 — 키 없는 설치는 기업마당을 「cached」 · 옛 조회 시각으로 돌려준다. 그 시각을 「오늘 받음」으로 적지 않는다."""
    def cached_biz(at: datetime) -> str:
        return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True, "결과": [
            {"출처": "나라장터", "결과": "cached", "오류": "… non-JSON response: <!DOCTYPE html>"},
            {"출처": "기업마당", "결과": "cached", "조회_시각": _at(7, 31, day=20).astimezone(timezone.utc).isoformat(), "오류": None},
        ]}, ensure_ascii=False)
    auto_collect.LOG_FILE.write_text("\n".join([_ok_run(_at(7, 31, day=22)), cached_biz(_at(7, 30)), cached_biz(_at(11, 30))]) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(16))
    assert state["kind"] == "missed" and "기업마당은 오늘" not in state["text"]


def test_노트북은_받을_예정_없이_예전처럼(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLECT_SCHEDULER", raising=False)
    auto_collect.LOG_FILE.write_text(_ok_run(_at(7, 31, day=22)) + "\n", encoding="utf-8")
    assert auto_collect.collect_state(_at(6))["kind"] == "missed"


def test_노트북_글은_그대로(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLECT_SCHEDULER", raising=False)
    auto_collect.LOG_FILE.write_text(_ok_run(_at(9, 12)) + "\n", encoding="utf-8")
    assert auto_collect.collect_state(_at(10))["text"] == "매일 처음 켤 때 자동으로 받음 · 오늘 09:12"


@pytest.mark.parametrize(
    ("code", "out", "want"),
    [
        (0, "30 7,9,11 * * * bash /home/x/bidpilot/current/scripts/collect_now.sh --scheduled\n", "Ready"),
        (0, "# 30 7 * * * bash /home/x/bidpilot/current/scripts/collect_now.sh --scheduled\n", "NONE"),  # 주석이면 꺼 둠
        (0, "0 3 * * * bash backup.sh\n", "NONE"),
        (1, "", "NONE"),  # no crontab for ksh
    ],
)
def test_crontab_받기_줄로_작업_있음을_안다(monkeypatch: pytest.MonkeyPatch, code: int, out: str, want: str) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=out, stderr=""))
    assert auto_collect._ask_cron_state() == want


def test_crontab_명령이_없으면_모름(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise FileNotFoundError("crontab")

    monkeypatch.setattr(subprocess, "run", boom)
    assert auto_collect._ask_cron_state() == "unknown"


def test_서버에서_crontab_받기_줄을_지우면_자동_받기_꺼_둠(cron: None, monkeypatch: pytest.MonkeyPatch) -> None:
    auto_collect.LOG_FILE.write_text(_ok_run(_at(7, 31, day=22)) + "\n", encoding="utf-8")
    monkeypatch.setattr(auto_collect, "task_state", lambda: "NONE")
    state = auto_collect.collect_state(_at(10))
    assert state["kind"] == "off" and state["text"] == "자동 받기 꺼 둠 — 목록은 10/22 07:31 그대로"


def test_서버는_Codex_를_끈다(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "plan_writer_cli", True)
    monkeypatch.setattr(settings, "plan_writer_codex", False)
    assert llm_client.plan_writer_ready("codex") == (False, llm_client.PLAN_WRITER_CODEX_OFF_REASON)
    status = llm_client.codex_cli_status(True)
    assert status["enabled"] is False and status["cli"] is False
    assert status["off_reason"] == llm_client.PLAN_WRITER_CODEX_OFF_REASON


def test_Claude_로그인_전이면_부르지_않고_호출로_세지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """42차 — 서버에 CLI 를 설치만 하고 로그인 전이면 「CLI 없음」처럼 규칙만 · 그날 1회 몫을 쓰지 않는다(담당자가 로그인한 뒤 같은 날 다시)."""
    from app.services import ai_fit_service as ai
    from tests.test_round41_collect import ORG, NOW, _item, _listing, _pre_raw, _raw

    calls: list[list[str]] = []
    monkeypatch.setattr(ai, "enabled", lambda _org: True)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: "claude")
    monkeypatch.setattr(llm_client, "claude_cli_auth_status", lambda: {"loggedIn": False})
    monkeypatch.setattr(llm_client, "_complete_via_cli", lambda **k: calls.append(k) or None)
    line = ai.run_daily(ORG, _listing([_item(1, "세무 교육 운영")]), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw)
    assert calls == [] and line["호출_수"] == 0
    assert line["실패_이유"] and llm_client.CLAUDE_NOT_LOGGED_IN_REASON in line["실패_이유"]
