"""41차 2-B — 받기(D33 공고문 하루 합계 · COLLECT-R40-02 네트워크 없음 종료 코드 · 03 잠금 pid 재사용 · 05 로그를 시각으로) ·
AI 적합도(AIFIT-01 목록 못 받은 날 건너뜀 · 02 시도 상한 240초 · 04 회사 값 섞임 · 07 로그 글 · CLI 없음 · 08 모델 · 09 오래된 답 · 한 번 읽기).

호출 없음 — 로그 · 잠금은 conftest `auto_collect_sandbox`, usage 는 tmp, CLI 는 가짜.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.services import ai_fit_service as ai
from app.services import auto_collect
from tests.test_round40_ai_fit import FakeAsk, _item, _listing, _pre_raw, _raw
from tests.test_round40_collect import _at, _log, _run

ORG = get_settings().default_organization_id
NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)


def _docs_run(at: datetime, *, g2b_targets: int, biz_fresh: int, partial: bool = False) -> str:
    line = json.loads(_run(at, partial=partial))
    line["결과"] += [{"출처": "나라장터 공고문", "결과": "받음", "대상": g2b_targets, "새로_받은_건수": g2b_targets},
                    {"출처": "기업마당 공고문", "결과": "받음", "새로_받은_건수": biz_fresh}]
    return json.dumps(line, ensure_ascii=False)


# --------------------------------------------------------------------------
# D33 — 공고문 하루 합계 · COLLECT-R40-05 — 로그를 시각으로
# --------------------------------------------------------------------------


def test_공고문_상한은_그날_합계로_센다() -> None:
    _log([_docs_run(_at(20, 9), g2b_targets=20, biz_fresh=40),  # 어제는 세지 않는다
          _docs_run(_at(21, 9), g2b_targets=12, biz_fresh=30, partial=True),
          _docs_run(_at(21, 10, 30), g2b_targets=8, biz_fresh=5, partial=True)])
    now = _at(21, 12)
    assert auto_collect.done_today(now, "나라장터 공고문", "대상") == 20
    assert auto_collect.done_today(now, "기업마당 공고문", "새로_받은_건수") == 35


def test_늦게_붙은_어제_줄이_오늘_성공을_가리지_않는다() -> None:
    # 어제 18:00 에 시작해 멈췄던 받기가 오늘 09:03 에 끝나며 오늘 09:00 성공 줄 뒤에 붙었다
    _log([_run(_at(21, 9, 0)), _run(_at(20, 18, 0))])
    assert auto_collect.daily_gate(_at(21, 10, 30)) == (False, "오늘 이미 받음 09:00")
    state = auto_collect.collect_state(_at(21, 10, 30))
    assert state["kind"] == "ok" and "오늘 09:00" in state["text"]


def test_마지막_성공은_시각이_가장_늦은_것() -> None:
    _log([_run(_at(21, 9, 0)), _run(_at(20, 18, 0))])
    assert auto_collect.last_success().astimezone(auto_collect.KST).hour == 9


# --------------------------------------------------------------------------
# COLLECT-R40-03 — 잠금 pid 재사용
# --------------------------------------------------------------------------


def _lock(pid: int, proc_start: float | None) -> None:
    body = {"pid": pid, "started": datetime.now(timezone.utc).isoformat()}
    if proc_start is not None:
        body["proc_start"] = proc_start
    auto_collect.LOCK_FILE.write_text(json.dumps(body), encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="프로세스 시작 시각은 Windows 에서만 잰다")
def test_pid_가_다른_프로세스에_다시_쓰였으면_남은_잠금을_넘긴다() -> None:
    mine = auto_collect.process_started(os.getpid())
    assert mine is not None
    _lock(os.getpid(), mine - 3600)  # 살아 있는 pid 지만 시작 시각이 다르다 = 다른 프로세스
    assert auto_collect.lock_info() is None
    assert auto_collect.acquire_lock() is True
    held = json.loads(auto_collect.LOCK_FILE.read_text(encoding="utf-8"))
    assert held["pid"] == os.getpid() and abs(held["proc_start"] - mine) < 1
    auto_collect.release_lock()


@pytest.mark.skipif(sys.platform != "win32", reason="프로세스 시작 시각은 Windows 에서만 잰다")
def test_같은_프로세스의_잠금은_살아_있다() -> None:
    _lock(os.getpid(), auto_collect.process_started(os.getpid()))
    assert auto_collect.lock_info() is not None
    _lock(os.getpid(), None)  # 시작 시각이 없는 옛 잠금 — pid · 2시간만 본다
    assert auto_collect.lock_info() is not None


# --------------------------------------------------------------------------
# COLLECT-R40-02 — 네트워크 없음은 0 이 아님 · 지금_받기.bat 안내
# --------------------------------------------------------------------------


@pytest.fixture
def daily(monkeypatch: pytest.MonkeyPatch):
    from tests.test_round38_strength import _load_collect_daily

    module = _load_collect_daily()
    monkeypatch.setattr(module, "_frozen", lambda: (False, []))
    monkeypatch.setattr(module, "network_ready", lambda wait=0: False)

    def run(*argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["collect_daily.py", "--run", "--json", *argv])
        return module.main()

    return SimpleNamespace(module=module, run=run)


def test_네트워크가_없으면_종료_코드_4_지금_받기도_예약_작업도(daily, capsys) -> None:
    assert daily.run() == daily.module.NETWORK_EXIT_CODE == 4
    assert daily.run("--force") == 4
    assert capsys.readouterr().out.count("네트워크가 아직 없습니다") == 2
    assert not auto_collect.LOCK_FILE.exists()


def test_지금_받기_bat_은_4_를_인터넷_확인으로_알린다() -> None:
    from pathlib import Path

    bat = (Path(__file__).resolve().parents[2] / "scripts" / "지금_받기.bat").read_bytes().decode("utf-8")
    assert "if errorlevel 4 goto nonet" in bat and "인터넷 연결을 확인하고 다시 누르세요" in bat
    # errorlevel 은 「이상」이라 큰 수부터 본다
    after = bat[bat.index("collect_daily.py --run --force"):]
    assert after.index("errorlevel 4") < after.index("errorlevel 3") < after.index("errorlevel 1")


# --------------------------------------------------------------------------
# AIFIT-01 — 나라장터 목록을 못 받은 날은 AI 단계를 건너뜀
# --------------------------------------------------------------------------


def test_나라장터_목록을_못_받으면_AI_단계를_건너뛴다(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_round38_strength import _load_collect_daily

    module = _load_collect_daily()
    monkeypatch.setattr(module.procurement_service, "live_fetch_enabled", lambda: True)
    monkeypatch.setattr(module.bizinfo_service, "live_fetch_enabled", lambda: False)

    async def broken(*_a, **_k):
        raise RuntimeError("나라장터 응답 없음")

    async def row(name):
        return {"출처": name, "결과": "g2b"}

    async def must_not_run(*_a, **_k):
        raise AssertionError("목록을 못 받은 날은 AI 단계를 부르지 않는다")

    monkeypatch.setattr(module, "_collect_g2b", broken)
    monkeypatch.setattr(module.prespec_service, "collect_prespecs", lambda: row("사전규격"))
    monkeypatch.setattr(module.prespec_service, "collect_order_plans", lambda: row("발주계획"))
    monkeypatch.setattr(module, "_collect_ai_fit", must_not_run)
    rows = asyncio.run(module.collect(30, g2b_documents=20))
    ai_row = next(r for r in rows if r["출처"] == "AI 적합도")
    assert "건너뜁니다" in ai_row["건너뜀"]


# --------------------------------------------------------------------------
# AI 적합도 — 02 · 04 · 07 · 08 · 09
# --------------------------------------------------------------------------


@pytest.fixture()
def assist_with_company_values():
    """회사 값이 **채워진** 시험 회사(AIFIT-04 — 값이 비어 있으면 섞임을 못 잡는다). 실제 PC 의 회사 값은 건드리지 않는다(시험 저장소)."""
    from app.core import org_storage, storage

    path = org_storage.storage_for(ORG).delivery_capacity_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = storage.read_json(path, default=None) or {}
    storage.write_json_atomic(path, {
        **payload, "ai_fit_assist": True, "organization_id": ORG, "budget_ceiling_krw": 370_000_000,
        "location_region": "제주특별자치도", "revenue_krw_last_year": 1_234_567_890,
        "registered_industries": [{"code": "9917", "name": "시험업종"}], "business_items": ["시험품목엑스"],
    })
    yield ["370000000", "3.70억", "3.7억", "제주특별자치도", "1234567890", "9917", "시험업종", "시험품목엑스"]


def test_보낸_글에_회사_값이_섞이지_않는다(assist_with_company_values) -> None:
    items = [_item(1, "생성형 AI 실무 교육 운영"), _item(2, "AI 교육 콘텐츠 개발", pre=True, typ="A2")]
    fake = FakeAsk()
    ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    (bodies,) = fake.calls
    sent = ai.SYSTEM + "\n" + ai.user_text(bodies)
    for value in assist_with_company_values:
        assert value not in sent, value


def test_시도_한_번의_상한도_240초(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import llm_client

    seen: dict = {}

    def fake_run(args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))

    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: "claude")
    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    monkeypatch.setattr(get_settings(), "llm_timeout_seconds", 180.0)
    with pytest.raises(llm_client.LLMUnavailableError):
        ai.ask_cli(["세무 교육 | 분류: 분류 없음 | 기관: 기관 | 예산: 미공개"])
    assert seen["timeout"] > 200  # 설정 180 이 먼저 끊지 않는다(남은 시간 = 240 안팎)


def test_CLI_가_없으면_호출로_세지_않아_같은_날_다시_묻는다(assist_with_company_values, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: None)
    items = [_item(1, "세무 교육 운영")]
    first = ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw)
    assert first["호출_수"] == 0 and first["실패_이유"]
    fake = FakeAsk()
    second = ai.run_daily(ORG, _listing(items), now=NOW + timedelta(hours=2), raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert len(fake.calls) == 1 and second["호출_수"] == 1


def test_답과_실행_기록에_모델을_적고_오래된_답은_지운다(assist_with_company_values, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import storage

    monkeypatch.setattr(ai, "model_name", lambda: "claude-test-model")
    storage.write_json_atomic(ai.store_path(ORG), {"entries": {
        "g2b-old": {"label": "core", "at": (NOW - timedelta(days=90)).isoformat()},
        "g2b-recent": {"label": "core", "at": (NOW - timedelta(days=5)).isoformat()},
    }, "runs": []})
    items = [_item(1, "세무 교육 운영")]
    ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=FakeAsk())
    store = ai.load_for_update(ORG)
    assert store["runs"][-1]["model"] == "claude-test-model"
    assert store["entries"][items[0].id]["model"] == "claude-test-model"
    assert "g2b-old" not in store["entries"] and "g2b-recent" in store["entries"]


def test_목록_요청에서_파일을_한_번만_읽는다(assist_with_company_values, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import storage

    storage.write_json_atomic(ai.store_path(ORG), {"entries": {}, "runs": []})
    reads: list[int] = []
    original = storage.read_json

    def counting(path, *a, **k):
        if str(path).endswith(ai.AI_FIT_FILE):
            reads.append(1)
        return original(path, *a, **k)

    monkeypatch.setattr(storage, "read_json", counting)
    ai.load(ORG)
    ai.load(ORG)
    assert len(reads) == 1


def test_AI_줄은_글자_출력에도_물은_수와_실패_이유() -> None:
    from tests.test_round38_strength import _load_collect_daily

    module = _load_collect_daily()
    detail = module.row_detail({"출처": "AI 적합도", "결과": "물음", "물은_수": 120, "아님_수": 30, "호출_수": 1, "실패_이유": None})
    assert "물은 수 120" in detail and "아님 30" in detail
    failed = module.row_detail({"출처": "AI 적합도", "결과": "물음", "물은_수": 120, "아님_수": 0, "호출_수": 1, "실패_이유": "시간 초과"})
    assert "실패: 시간 초과" in failed
