"""40차 §3-E — 켤 때 받기(D30 「하루 한 번」) · 받기 잠금(D29) · 꺼 둔 예약 작업(D28) · 받은 때 한 줄(`auto_collect.collect_state`).

호출 없음 — 로그 · 잠금 파일은 conftest `auto_collect_sandbox` 가 tmp 로 돌리고, 예약 작업 상태는 「Ready」로 둔다.
39차의 07:30 기준(「제때」 · 「늦게 받음」) 시험은 걷어 냈다 — 로그 끝 64KB · 긴 줄 · 실패 줄 시험만 옮겨 왔다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.business_opportunity import CollectState
from app.services import auto_collect, opportunity_brief_service

KST = timezone(timedelta(hours=9))


def _run(at: datetime, *, ok: bool = True, partial: bool = False, biz_error: bool = False) -> str:
    """`collect_daily.py --run --json` 이 남기는 실행 줄 하나(시각은 UTC 로 적힌다)."""
    g2b: dict = {"출처": "나라장터", "결과": "g2b"} if ok else {"출처": "나라장터", "오류": "G2BClientError"}
    if partial:
        g2b["일부_실패"] = "일부 실패 — 낱말 「교육」 조회 실패 1회"
    biz = {"출처": "기업마당", "오류": "BizinfoClientError"} if biz_error else {"출처": "기업마당", "결과": "bizinfo"}
    return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True, "결과": [g2b, biz]}, ensure_ascii=False)


def _skip(at: datetime, why: str) -> str:
    """받지 않은 줄(하루 한 번 건너뜀 · 네트워크 없음 · 이미 받는 중) — `실행: false`."""
    return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": False, "사유": why}, ensure_ascii=False)


def _log(lines: list[str]) -> None:
    auto_collect.LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


# --------------------------------------------------------------------------
# D30 「하루 한 번」
# --------------------------------------------------------------------------


def test_오늘_오류_없는_성공이_있으면_건너뛴다() -> None:
    _log([_run(_at(20, 9, 12))])
    assert auto_collect.daily_gate(_at(20, 13, 0)) == (False, "오늘 이미 받음 09:12")


def test_오늘_실패만_있으면_60분_안은_건너뛰고_넘으면_다시() -> None:
    _log([_run(_at(20, 9, 0), ok=False)])
    assert auto_collect.daily_gate(_at(20, 9, 30)) == (False, "마지막 시도 09:00 — 10:00 뒤에 다시")
    assert auto_collect.daily_gate(_at(20, 10, 1)) == (True, None)


def test_일부_실패도_다시_받을_까닭이다() -> None:
    _log([_run(_at(20, 9, 0), partial=True)])
    assert auto_collect.daily_gate(_at(20, 9, 59))[0] is False
    assert auto_collect.daily_gate(_at(20, 10, 0)) == (True, None)


def test_하루_3번_넘게는_시도하지_않는다() -> None:
    _log([_run(_at(20, h), ok=False) for h in (8, 10, 12)])
    go, why = auto_collect.daily_gate(_at(20, 18, 0))
    assert go is False and why == "오늘 3번 시도함(하루 최대 3번) — 「지금 받기」로만 다시"


def test_어제_시도는_오늘_3번에_세지_않는다() -> None:
    _log([_run(_at(19, h), ok=False) for h in (8, 10, 12)])
    assert auto_collect.daily_gate(_at(20, 8, 0)) == (True, None)


def test_네트워크_없음_건너뜀_줄은_시도로_세지_않는다() -> None:
    _log([_skip(_at(20, 8, h), "네트워크가 아직 없습니다(60초 기다림)") for h in range(5)])
    assert auto_collect.daily_gate(_at(20, 8, 10)) == (True, None)


def test_기업마당만_못_받은_날은_다시_받지_않고_받은_때_줄에_적는다() -> None:
    _log([_run(_at(20, 9, 12), biz_error=True)])
    assert auto_collect.daily_gate(_at(20, 13, 0))[0] is False
    state = auto_collect.collect_state(_at(20, 13, 0))
    assert state["kind"] == "ok" and state["suffix"] == " · 기업마당 못 받음"
    assert state["text"] == "매일 처음 켤 때 자동으로 받음 · 오늘 09:12 · 기업마당 못 받음"


def test_KST_자정이_하루의_경계다_로그_시각은_UTC() -> None:
    # 10-19 23:50 KST(= 10-19 14:50Z) 성공 → 10-20 00:10 KST 에는 「오늘」 몫이 없다
    _log([_run(_at(19, 23, 50))])
    assert auto_collect.daily_gate(_at(20, 0, 10)) == (True, None)
    # 10-20 00:30 KST(= 10-19 15:30Z · UTC 로는 어제) 성공 → 10-20 08:00 KST 에는 오늘 받은 것
    _log([_run(_at(20, 0, 30))])
    assert auto_collect.daily_gate(_at(20, 8, 0)) == (False, "오늘 이미 받음 00:30")
    # 10-20 08:00 KST(= 10-19 23:00Z) 성공 → 10-20 10:00 KST(= 10-20 01:00Z) — UTC 날짜는 달라도 같은 날
    _log([_run(_at(20, 8, 0))])
    assert auto_collect.daily_gate(_at(20, 10, 0))[0] is False


# --------------------------------------------------------------------------
# D29 받기 잠금
# --------------------------------------------------------------------------


def test_잠금은_하나만_잡히고_놓으면_다시_잡힌다() -> None:
    now = datetime.now(timezone.utc)
    assert auto_collect.acquire_lock(now) is True
    assert auto_collect.acquire_lock(now) is False  # 내 pid 가 살아 있다 — 「이미 받는 중」
    assert auto_collect.lock_info(now)["pid"] == os.getpid()
    auto_collect.release_lock()
    assert not auto_collect.LOCK_FILE.exists()
    assert auto_collect.acquire_lock(now) is True


def test_죽은_pid_의_잠금은_넘기고_잡는다(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    auto_collect.LOCK_FILE.write_text(json.dumps({"pid": 424242, "started": now.isoformat()}), encoding="utf-8")
    monkeypatch.setattr(auto_collect, "pid_alive", lambda pid: False)
    assert auto_collect.lock_info(now) is None
    assert auto_collect.acquire_lock(now) is True
    assert json.loads(auto_collect.LOCK_FILE.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_2시간_넘은_잠금은_살아_있는_pid_라도_넘긴다() -> None:
    now = datetime.now(timezone.utc)
    auto_collect.LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "started": (now - timedelta(hours=3)).isoformat()}), encoding="utf-8")
    assert auto_collect.lock_info(now) is None
    assert auto_collect.acquire_lock(now) is True


def test_깨진_잠금_파일도_넘긴다() -> None:
    auto_collect.LOCK_FILE.write_text("{망가짐", encoding="utf-8")
    assert auto_collect.acquire_lock() is True


def test_남의_잠금은_놓지_않는다() -> None:
    auto_collect.LOCK_FILE.write_text(json.dumps({"pid": os.getpid() + 1, "started": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    auto_collect.release_lock()
    assert auto_collect.LOCK_FILE.exists()


def test_pid_0_과_음수는_살아_있지_않다() -> None:
    assert auto_collect.pid_alive(0) is False and auto_collect.pid_alive(-5) is False
    assert auto_collect.pid_alive(os.getpid()) is True


# --------------------------------------------------------------------------
# collect_daily.py main — 잠금 → 하루 한 번(--force 는 건너뜀) → 네트워크 → 받기
# --------------------------------------------------------------------------


@pytest.fixture
def daily(monkeypatch: pytest.MonkeyPatch):
    """`scripts/collect_daily.py` — 고정 해제 · 네트워크 있음 · `collect` 는 부른 횟수만 센다(바깥 호출 없음)."""
    from tests.test_round38_strength import _load_collect_daily

    module = _load_collect_daily()
    calls: list[int] = []

    async def fake_collect(days: int, **_: object) -> list[dict]:
        calls.append(days)
        return [{"출처": "나라장터", "결과": "g2b"}]

    monkeypatch.setattr(module, "collect", fake_collect)
    monkeypatch.setattr(module, "_frozen", lambda: (False, []))
    monkeypatch.setattr(module, "network_ready", lambda wait=0: True)

    def run(*argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["collect_daily.py", "--run", "--json", *argv])
        return module.main()

    return SimpleNamespace(module=module, calls=calls, run=run)


def test_main_오늘_받았으면_네트워크_없이_한_줄로_끝난다(daily, capsys) -> None:
    _log([_run(datetime.now(timezone.utc) - timedelta(seconds=1))])
    daily.module.network_ready = lambda wait=0: pytest.fail("하루 한 번 검사 전에 네트워크를 보면 안 된다")
    assert daily.run() == 0
    assert daily.calls == []
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["실행"] is False and line["사유"].startswith("오늘 이미 받음")
    assert not auto_collect.LOCK_FILE.exists()  # 건너뛰어도 잠금은 놓는다


def test_main_force_는_하루_한_번_검사를_건너뛴다(daily) -> None:
    _log([_run(datetime.now(timezone.utc) - timedelta(seconds=1))])
    assert daily.run("--force") == 0
    assert daily.calls == [daily.module.DEFAULT_DAYS]
    assert not auto_collect.LOCK_FILE.exists()


def test_main_잠금이_잡혀_있으면_이미_받는_중_force_만_3(daily, capsys) -> None:
    auto_collect.LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "started": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    assert daily.run() == 0  # 예약 작업 — 작업 결과가 실패로 보이지 않게
    assert daily.run("--force") == 3  # 지금 받기 — bat 이 「이미 받는 중」으로 알린다
    assert daily.calls == []
    out = capsys.readouterr().out
    assert out.count("이미 받는 중") == 2
    assert auto_collect.LOCK_FILE.exists()  # 남의(먼저 돈) 잠금은 지우지 않는다


def test_main_네트워크가_없으면_받지_않고_시도로도_세지_않는다(daily, capsys) -> None:
    daily.module.network_ready = lambda wait=0: False
    assert daily.run() == 4  # 41차 COLLECT-R40-02 — 0 이 아니다(지금 받기 bat 이 「다 받았습니다」라고 하지 않게)
    assert daily.calls == []
    row = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(row)["실행"] is False and "네트워크가 아직 없습니다" in row
    _log([row])
    assert auto_collect.daily_gate(datetime.now(timezone.utc)) == (True, None)


def test_main_받다가_멈춰도_잠금은_놓는다(daily) -> None:
    async def boom(days: int, **_: object) -> list[dict]:
        raise RuntimeError("멈춤")

    daily.module.collect = boom
    with pytest.raises(RuntimeError):
        daily.run()
    assert not auto_collect.LOCK_FILE.exists()


# --------------------------------------------------------------------------
# 받은 때 한 줄(collect_state) — D30 글 · D28 꺼 둠 · D29 받는 중
# --------------------------------------------------------------------------


def test_키트는_기록도_예약_작업도_없어_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_collect, "task_state", lambda: "NONE")
    assert auto_collect.collect_state(_at(20, 10)) == {"kind": "none", "text": None, "last_success": None, "suffix": None}


def test_오늘_받았으면_매일_처음_켤_때_자동으로_받음() -> None:
    _log([_run(_at(20, 9, 12))])
    state = auto_collect.collect_state(_at(20, 13))
    assert state["kind"] == "ok" and state["text"] == "매일 처음 켤 때 자동으로 받음 · 오늘 09:12" and state["suffix"] is None


def test_오늘_아직이면_경고와_지금_받기() -> None:
    _log([_run(_at(19, 9, 41))])
    state = auto_collect.collect_state(_at(20, 8, 0))
    assert state["kind"] == "missed"
    assert state["text"] == "오늘 목록을 아직 받지 않았습니다 — 마지막 10/19 09:41 · 「지금 받기」를 두 번 누르세요(scripts\\지금_받기.bat)"


def test_실패한_실행은_받은_것으로_세지_않는다() -> None:
    _log([_run(_at(19, 9, 0)), _run(_at(20, 9, 0), ok=False)])
    state = auto_collect.collect_state(_at(20, 10))
    assert state["kind"] == "missed" and "마지막 10/19 09:00" in state["text"]


def test_일부_실패는_받았지만_꼬리로_적는다() -> None:
    _log([_run(_at(20, 9, 0), partial=True)])
    state = auto_collect.collect_state(_at(20, 10))
    assert state["kind"] == "ok" and state["suffix"] == " · 일부 실패(지난 저장본으로 채움)"
    assert state["text"].endswith(" · 일부 실패(지난 저장본으로 채움)")


@pytest.mark.parametrize("task", ["Disabled", "NONE"])
def test_예약_작업이_꺼졌거나_없으면_자동_받기_꺼_둠(monkeypatch: pytest.MonkeyPatch, task: str) -> None:
    _log([_run(_at(19, 9, 41))])
    monkeypatch.setattr(auto_collect, "task_state", lambda: task)
    state = auto_collect.collect_state(_at(20, 10))
    assert state["kind"] == "off" and state["text"] == "자동 받기 꺼 둠 — 목록은 10/19 09:41 그대로"


def test_예약_작업_상태를_못_읽으면_꺼_둠으로_단정하지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    _log([_run(_at(20, 9, 12))])
    monkeypatch.setattr(auto_collect, "task_state", lambda: "unknown")
    assert auto_collect.collect_state(_at(20, 10))["kind"] == "ok"


def test_잠금이_살아_있으면_받는_중_경고_아님() -> None:
    _log([_run(_at(19, 9, 41))])
    now = datetime.now(timezone.utc)
    auto_collect.LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "started": now.isoformat()}), encoding="utf-8")
    state = auto_collect.collect_state(now)
    assert state["kind"] == "running" and state["text"] == f"오늘 목록 받는 중 — {now.astimezone(KST):%H:%M} 시작"


# --------------------------------------------------------------------------
# 대시보드 띠 메모(COLLECT-02) · 브리핑 한 줄
# --------------------------------------------------------------------------


def test_브리핑_한_줄은_오늘_아직일_때만_경고() -> None:
    def line(**state: object) -> str | None:
        return opportunity_brief_service.collect_line(SimpleNamespace(collect_state=CollectState(**state)))  # type: ignore[arg-type]

    assert line(kind="none") is None
    assert line(kind="missed", text="오늘 목록을 아직 받지 않았습니다 — …") == "⚠ 오늘 목록을 아직 받지 않았습니다 — …"
    assert line(kind="ok", text="매일 처음 켤 때 자동으로 받음 · 오늘 09:12") == "자동 받기: 매일 처음 켤 때 자동으로 받음 · 오늘 09:12"
    assert line(kind="running", text="오늘 목록 받는 중 — 09:12 시작") == "자동 받기: 오늘 목록 받는 중 — 09:12 시작"
    assert line(kind="off", text="자동 받기 꺼 둠 — 목록은 10/19 09:41 그대로") == "자동 받기 꺼 둠 — 목록은 10/19 09:41 그대로"  # 43차 NUM-13


def test_대시보드_띠의_꺼짐_메모는_자동_받기_기록이_없을_때만(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from tests.test_daily_digest import NOW, build, notice, seed

    monkeypatch.setattr(get_settings(), "g2b_live_fetch", False)
    seed(notice_cache_file, [notice("g2b-A-000", published=NOW, deadline=None)], fetched_at=NOW)
    _log([_run(NOW - timedelta(minutes=1))])
    digest = build()
    assert digest["frozen"] is True and digest["collect_state"]["kind"] == "ok"
    assert not any("새 공고 받기가 꺼져" in note for note in digest["notes"])


# --------------------------------------------------------------------------
# 로그 읽기(39차 §3-F-4 에서 옮겨 옴)
# --------------------------------------------------------------------------


def test_로그_끝_64KB_에_성공_줄이_없어도_직전_성공을_찾는다() -> None:
    """pdfminer 경고(「Could not get FontBBox …」)가 수백 줄 붙어도 직전 성공을 놓치지 않는다."""
    noise = ["Could not get FontBBox from font descriptor because None cannot be parsed as 4 floats"] * 3000  # 약 250KB
    _log([_run(_at(18, 7, 30)), *noise])
    assert auto_collect.last_success() == _at(18, 7, 30)


def test_긴_줄이_조각에_걸쳐도_성공_줄을_읽는다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_collect, "_TAIL_BYTES", 50)  # 성공 줄 하나가 여러 조각에 걸치게
    _log([_run(_at(17, 7, 31)), "경고 줄", _run(_at(18, 7, 31))])
    assert [m for m, _ in auto_collect._successes_backward()] == [_at(18, 7, 31), _at(17, 7, 31)]
