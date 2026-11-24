"""사업기회 「재수집」 단추 (20차 §4-G · 담당자 「사업기회에 재수집 버튼 추가. 나라장터, 기업마당으로.」).

재는 것:
1. 문(실호출)이 꺼져 있으면 409 — **네트워크 클라이언트를 한 번도 만들지 않고** 캐시 파일은 한 바이트도 안 바뀐다.
2. 문이 켜져 있으면(가짜 수집) 전후 건수 · 새 공고 · 빠진 공고 · 자격 표 · 조항 없는 새 공고를 센다. 캐시가 바뀐다.
3. 받은 건수가 저장된 것의 절반 아래면(축소 차단) 409 와 사유 — 캐시는 그대로.
4. 같은 출처가 도는 중이면 409 「이미 받는 중」.
5. `/health` 가 출처별 문 상태를 알린다 · 활동 기록에 출처와 전후 수가 남는다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.procurement import ProcurementNotice
from app.services import audit_log_service, notice_version_service, procurement_service, recollect_service

client = TestClient(app)
KST = timezone(timedelta(hours=9))


def _notice(index: int) -> ProcurementNotice:
    return ProcurementNotice(
        id=f"g2b-R26RECOL{index:05d}-000",
        notice_no=f"R26RECOL{index:05d}-000",
        title=f"생성형 AI 활용 실무교육 운영 용역 {index}",
        agency="테스트기관",
        published_at=datetime(2026, 9, 20, 9, 0, tzinfo=KST),
        raw_data={},
    )


def _seed(cache_file: Path, count: int) -> None:
    views = [procurement_service.NoticeView(notice=_notice(i), match=None) for i in range(count)]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "_note": "테스트용 캐시", "fetched_at": "2026-09-17T10:00:00+00:00", "days": 30, "total_fetched": count,
        "notices": [{"notice": v.notice.model_dump(mode="json"), "candidate": {}, "pinned": False} for v in views],
    }, ensure_ascii=False), encoding="utf-8")


class CountingClient:
    made = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        CountingClient.made += 1
        raise AssertionError("재수집이 네트워크 클라이언트를 만들었다")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notice_version_service, "VERSION_DIR", tmp_path / "notice_versions")


def test_문이_꺼져_있으면_409_이고_아무것도_부르지_않는다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "g2b_live_fetch", False)
    monkeypatch.setattr(settings, "bizinfo_live_fetch", False)
    CountingClient.made = 0
    monkeypatch.setattr(httpx, "AsyncClient", CountingClient)
    _seed(notice_cache_file, 3)
    before = notice_cache_file.read_bytes()

    for source, word in (("g2b", "나라장터"), ("bizinfo", "기업마당")):
        response = client.post("/api/business-opportunities/recollect", json={"source": source})
        assert response.status_code == 409
        assert response.json()["detail"] == (
            # 기대값 바꿈(27차 §3-H): 화면 문구에 스크립트 이름 · 옵션을 적지 않는다
            f"새 공고 받기 꺼짐 — {word} 새로 받기가 꺼져 있습니다. 켜려면 관리자에게 요청하세요"
        )
    assert CountingClient.made == 0
    assert notice_cache_file.read_bytes() == before

    health = client.get("/health").json()
    assert health["g2b_live"] is False and health["bizinfo_live"] is False
    events = [json.loads(line).get("event") for line in audit_log_service.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()]
    assert {"kind": "recollect", "source": "g2b", "before": None, "after": None} in events


def _fake_collect(notices: list[ProcurementNotice]):
    async def collect(**_kwargs: object) -> procurement_service.Collected:
        return procurement_service.Collected(
            notices=notices, superseded={}, calls=5, method="공고명 키워드 조회", total_fetched=len(notices),
            qualification_calls=2, qualification_days_fetched=2, qualification_note=None,
        )
    return collect


def test_문이_켜져_있으면_전후와_새_공고를_센다(notice_cache_file: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(notice_cache_file, 4)  # 0 ~ 3
    fresh = [_notice(i) for i in (1, 2, 3, 4, 5)]  # 0 은 빠지고 4 · 5 가 새로
    monkeypatch.setattr(procurement_service, "collect_candidates", _fake_collect(fresh))

    response = client.post("/api/business-opportunities/recollect", json={"source": "g2b"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["before"]["count"] == 4 and body["before"]["fetched_at"].startswith("2026-09-17")
    ours = {n.id for n in fresh}
    stored = {v["notice"]["id"] for v in json.loads(notice_cache_file.read_text(encoding="utf-8"))["notices"]}
    assert ours <= stored and body["after"]["count"] == len(stored)
    assert body["gone"] == 1
    assert body["new"] == len(stored - {_notice(i).id for i in range(4)})  # 새 공고 4 · 5 (+ 시연용 고정 공고)
    assert body["qualification"] == {"days_fetched": 2, "calls": 2, "note": None}
    assert body["clauses_missing"] >= 2  # 새 공고 4 · 5 는 참가자격 조항 파일이 없다
    assert "fetch_qualification_clauses.py" in body["clauses_note"]


def test_축소_차단이면_409_이고_캐시는_그대로(notice_cache_file: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(notice_cache_file, 40)
    before = notice_cache_file.read_bytes()
    monkeypatch.setattr(procurement_service, "collect_candidates", _fake_collect([_notice(1)]))

    response = client.post("/api/business-opportunities/recollect", json={"source": "g2b"})
    assert response.status_code == 409
    assert response.json()["detail"].startswith("새 목록을 저장하지 않았습니다 — 받은 건수")
    assert notice_cache_file.read_bytes() == before


def test_이미_받는_중이면_409(live_fetch_on: None) -> None:
    async def run() -> str:
        async with recollect_service._lock("g2b"):
            try:
                await recollect_service.recollect("g2b")
            except recollect_service.RecollectRefusedError as exc:
                return str(exc)
        return "막히지 않았다"

    assert asyncio.run(run()) == "나라장터 목록을 이미 받는 중입니다. 끝난 뒤 다시 누르세요."
