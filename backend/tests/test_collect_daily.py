"""scripts/collect_daily.py 의 판단 로직 (0919 §4-B-2).

이 스크립트가 실제로 하는 일은 **바깥을 부르고 저장소가 추적하는 캐시 파일을 덮어쓰는**
것이다. 그래서 여기서 지키는 약속은 「언제 부르지 않는가」 셋이다.

1. 옵션 없이 돌리면 **부르지 않는다**(기본 `--dry-run`).
2. `--run` 과 `--dry-run` 이 함께 오면 **부르지 않는다**(안전한 쪽이 이긴다).
3. 시연 고정 모드면 `--run` 을 붙여도 **부르지 않는다**(ISSUE-062).

네트워크를 실제로 부르는 경로는 테스트하지 않는다 — 이 저장소의 규칙상 실호출 0회다.
대신 「불렀는가」를 지뢰로 깔아 두고 밟히지 않는 것을 확인한다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "collect_daily.py"
spec = importlib.util.spec_from_file_location("collect_daily", SCRIPT)
assert spec is not None and spec.loader is not None
collect_daily = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collect_daily
spec.loader.exec_module(collect_daily)


class LiveCallAttempted(AssertionError):
    """스크립트가 바깥을 불렀다. 이 예외가 뜨면 §4-B-2 의 전제가 깨진 것이다."""


@pytest.fixture(autouse=True)
def landmine(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(*_args: object, **_kwargs: object) -> object:
        raise LiveCallAttempted("collect_daily 가 목록을 받아오려 했습니다")

    monkeypatch.setattr(collect_daily.procurement_service, "list_ai_candidates", _explode)
    monkeypatch.setattr(collect_daily.bizinfo_service, "list_programs", _explode)


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["collect_daily.py", *argv])
    return collect_daily.main()


def test_옵션_없이_돌리면_받아오지_않는다(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(monkeypatch) == 0
    out = capsys.readouterr().out
    assert "예정만 출력" in out
    # 「무엇을 덮어쓰는가」를 반드시 말한다. 이 줄이 없으면 --run 이 무슨 일인지 모른 채 붙인다.
    # 33차부터 살아 있는 저장본은 Git 밖 · 추적 파일은 기준본이라 그대로 — 둘 다 말한다.
    assert "살아 있는 저장본" in out and "Git 밖" in out and "기준본" in out
    assert "자격" in out and "최대 120회" in out  # 자격 하루치 호출도 예정에 적는다(33차 §3-A-4)


def test_run_과_dry_run_이_함께_오면_받아오지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """안전한 쪽이 이긴다. 스케줄러 등록 줄에 둘이 섞여 들어가는 일이 실제로 있다."""
    assert run(monkeypatch, "--run", "--dry-run") == 0


def test_고정한_출처만_건너뛰고_나머지는_받는다(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """한쪽만 고정이면 **그쪽만** 건너뛴다 (0920 §4-A-4).

    예전에는 한쪽만 고정이어도 통째로 그만뒀다. 그러면 「나라장터만 다시 받고 기업마당은
    그대로 둔다」를 할 수 없는데, 그게 바로 이번에 해야 하는 일이다.
    고정한 쪽을 건드리지 않는 것이 목적이지 다른 쪽을 막는 것이 목적이 아니다.
    """
    monkeypatch.setattr(collect_daily.procurement_service, "live_fetch_enabled", lambda: False)
    monkeypatch.setattr(collect_daily.bizinfo_service, "live_fetch_enabled", lambda: True)

    # 기업마당은 살아 있으므로 실제로 불린다 — 지뢰가 터지는 것이 «맞는» 동작이다.
    assert run(monkeypatch, "--run") == 1
    out = capsys.readouterr().out
    assert "나라장터" in out and "시연 고정 모드" in out


def test_두_출처가_모두_고정이면_아무것도_하지_않는다(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """시연 주간에 스케줄러를 끄는 것을 잊어도 캐시가 바뀌지 않아야 한다 (ISSUE-062)."""
    monkeypatch.setattr(collect_daily.procurement_service, "live_fetch_enabled", lambda: False)
    monkeypatch.setattr(collect_daily.bizinfo_service, "live_fetch_enabled", lambda: False)
    assert run(monkeypatch, "--run") == 0
    assert "시연 고정 모드" in capsys.readouterr().out


def test_고정_모드를_json_으로도_말한다(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """스케줄러 로그가 「돌았는데 아무것도 안 했다」를 구분할 수 있어야 한다."""
    monkeypatch.setattr(collect_daily.procurement_service, "live_fetch_enabled", lambda: False)
    monkeypatch.setattr(collect_daily.bizinfo_service, "live_fetch_enabled", lambda: False)
    assert run(monkeypatch, "--run", "--json") == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["실행"] is False
    assert "고정 모드" in payload["사유"]


def test_예정_문구는_고정_모드일_때_그_사실을_먼저_말한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect_daily.procurement_service, "live_fetch_enabled", lambda: False)
    monkeypatch.setattr(collect_daily.bizinfo_service, "live_fetch_enabled", lambda: False)
    frozen, sources = collect_daily._frozen()
    assert frozen is True
    assert len(sources) == 2
    assert any("--run 을 붙여도 받아오지 않습니다" in line for line in collect_daily.plan(30, sources))


def test_공고문_줄도_받은_수를_적는다() -> None:
    """예약 작업 기록에서 공고문을 받았는지 보이게(33차 — 실호출 때 「[OK] 기업마당 공고문」 뒤가 비어 있었다)."""
    line = collect_daily.row_detail(
        {"출처": "기업마당 공고문", "결과": "받음", "새로_받은_건수": 40, "본문": 180, "이미지": 10, "실패": 4, "저장소_전체": 194}
    )
    assert line == "받음 · 새로 받음 40건 · 저장소 194건(글 180 · 그림 10 · 실패 4)"
    assert collect_daily.row_detail(
        {"출처": "나라장터", "결과": "g2b", "받아온_건수": 198, "후보_건수": 102, "수집_방식": "키워드", "호출_횟수": 42}
    ) == "g2b · 받아옴 198 · 후보 102 · 키워드 · 호출 42회"
