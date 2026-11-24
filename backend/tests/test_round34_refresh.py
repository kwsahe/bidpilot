"""34차 §3-C — 최신화 튼튼하게(R33-R1 · R3 · R4 · R5) · 시연 전 점검(R33-R2)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.services import procurement_service
from tests.test_demo_freeze_mode import _seed_cache

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"r34_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_R33_R1_깨진_살아_있는_저장본이면_기준본을_읽는다(notice_cache_file: Path) -> None:
    _seed_cache(procurement_service.BASELINE_CACHE_FILE)
    notice_cache_file.parent.mkdir(parents=True, exist_ok=True)
    notice_cache_file.write_text("{ 깨진 파일", encoding="utf-8")
    assert procurement_service.cache_read_path() == procurement_service.BASELINE_CACHE_FILE
    cached = procurement_service.load_cache()
    assert cached is not None and {v.notice.id for v in cached.notices} == {"g2b-TEST-000"}


def test_R33_R3_깨진_살아_있는_저장본이어도_줄어듦은_기준본과_견준다(notice_cache_file: Path) -> None:
    _seed_cache(procurement_service.BASELINE_CACHE_FILE)
    notice_cache_file.parent.mkdir(parents=True, exist_ok=True)
    notice_cache_file.write_text("{ 깨진 파일", encoding="utf-8")
    cached = procurement_service.load_cache()
    assert cached is not None
    reason = procurement_service.save_cache([], 0, cached.fetched_at, days=30)  # 0건 저장 — 기준본 1건과 견줘 막힌다
    assert reason is not None
    assert notice_cache_file.read_text(encoding="utf-8") == "{ 깨진 파일"  # 쓰지 않았다


def test_R33_R1_읽을_수_있는_살아_있는_저장본이_먼저(notice_cache_file: Path) -> None:
    _seed_cache(procurement_service.BASELINE_CACHE_FILE)
    _seed_cache(notice_cache_file)
    assert procurement_service.cache_read_path() == notice_cache_file


def test_R33_R4_매일_받기_결과_줄에_자격_하루치() -> None:
    collect_daily = _load_script("collect_daily")
    line = collect_daily.row_detail({
        "출처": "나라장터", "결과": "g2b", "받아온_건수": 198, "후보_건수": 102, "수집_방식": "키워드", "호출_횟수": 13,
        "자격_새로_받은_날": 1, "자격_호출": 5, "자격_사유": "2026-10-08 하루치를 6페이지 안에 다 받지 못했습니다",
    })
    assert "자격 새로 받은 날 1일(호출 5회)" in line and "다 받지 못했습니다" in line


def test_R33_R5_받다가_실패한_조항_파일은_다시_대상(monkeypatch) -> None:
    sys.argv = ["fetch_qualification_clauses.py", "--missing"]
    fqc = _load_script("fetch_qualification_clauses")
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    future = datetime.now(timezone.utc) + timedelta(days=5)

    def view(nid: str, no: str):
        return SimpleNamespace(notice=SimpleNamespace(id=nid, notice_no=no, deadline_at=future))

    views = [view("g2b-A-000", "R26A-000"), view("g2b-B-000", "R26B-000"), view("g2b-C-000", "R26C-000"),
             view("g2b-R26BK01726154-000", "R26BK01726154-000")]
    monkeypatch.setattr(fqc.procurement_service, "cached_only", lambda include_low=False: SimpleNamespace(notices=views))
    stored = {"g2b-A-000": {"status": "ok"}, "g2b-B-000": {"status": "not_fetched"}, "g2b-R26BK01726154-000": {"status": "not_fetched"}}
    monkeypatch.setattr(fqc.qc, "load", lambda nid: stored.get(nid))
    assert fqc.missing_targets() == ["g2b-B-000", "g2b-C-000"]  # 실패(B) · 없음(C) — 보류 1726154 는 빠짐


def test_R33_R2_시연_전_점검이_살아_있는_저장본과_기준본을_견준다(tmp_path: Path, monkeypatch, capsys) -> None:
    preflight = _load_script("demo_preflight")
    live, base = tmp_path / "live.json", tmp_path / "base.json"
    base.write_text(json.dumps({"fetched_at": "2026-10-08T03:01:46", "notices": [{"notice": {"id": "g2b-A"}}]}), encoding="utf-8")
    live.write_text(json.dumps({"fetched_at": "2026-10-09T22:30:00", "notices": [{"notice": {"id": "g2b-A"}}, {"notice": {"id": "g2b-B"}}]}), encoding="utf-8")
    monkeypatch.setattr(preflight, "LIVE_CACHE", live)
    monkeypatch.setattr(preflight, "BASELINE_CACHE", base)
    preflight.check_live_vs_baseline()
    out = capsys.readouterr().out
    assert "큐시트 기준본과 다릅니다" in out and "더해짐 1" in out


def test_36차_시각이_같고_내용만_다르면_그대로_말한다(tmp_path: Path, monkeypatch, capsys) -> None:
    """KIT-R35-04 — 「받은 시각이 다릅니다」라고 적으면 틀린 말이었다."""
    preflight = _load_script("demo_preflight")
    live, base = tmp_path / "live.json", tmp_path / "base.json"
    base.write_text(json.dumps({"fetched_at": "2026-10-08T03:01:46", "notices": [{"notice": {"id": "g2b-A", "title": "옛"}}]}), encoding="utf-8")
    live.write_text(json.dumps({"fetched_at": "2026-10-08T03:01:46", "notices": [{"notice": {"id": "g2b-A", "title": "새"}}]}), encoding="utf-8")
    monkeypatch.setattr(preflight, "LIVE_CACHE", live)
    monkeypatch.setattr(preflight, "BASELINE_CACHE", base)
    preflight.check_live_vs_baseline()
    out = capsys.readouterr().out
    assert "받은 시각은 같은데 공고 내용이 다릅니다" in out and "받은 시각이 다릅니다" not in out


def test_36차_화면과_health_가_BidPilot_인지_본다(monkeypatch, capsys) -> None:
    """KIT-R35-02 — 화면은 200 이면 무엇이든 OK 였고, /health 가 JSON 이 아니면 멈췄다."""
    preflight = _load_script("demo_preflight")
    pages = {
        "http://b/health": (200, "<html>not json</html>"),
        "http://f": (200, "<html><title>Directory listing for /</title></html>"),
    }
    monkeypatch.setattr(preflight, "fetch", lambda url, timeout=5.0: pages[url])
    assert preflight.check_servers("http://b", "http://f") is None
    out = capsys.readouterr().out
    assert "BidPilot 백엔드가 아닙니다" in out and "BidPilot 화면이 아닙니다" in out
    pages["http://b/health"] = (200, json.dumps({"status": "ok", "service": "bidpilot-api"}))
    pages["http://f"] = (200, "<html><title>대시보드 · BidPilot AI</title></html>")
    assert preflight.check_servers("http://b", "http://f") == {"status": "ok", "service": "bidpilot-api"}
    assert "화면 200" in capsys.readouterr().out
