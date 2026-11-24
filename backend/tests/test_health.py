"""헬스체크 + 공고 목록 API 계약 테스트.

실호출은 conftest의 `block_network`가 막는다. 나라장터 응답은 저장해 둔 실제
응답 item으로 대체한다. 계약(docs/real_data_migration.md §1):
    - 실호출 성공 -> source "g2b"
    - 실호출 실패 + 캐시 있음 -> source "cached" (error 메시지 포함)
    - 실호출 실패 + 캐시 없음 -> 503
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import g2b_client


def _outcome(items: list[dict[str, Any]]) -> g2b_client.CollectOutcome:
    """수집기가 돌려주는 모양. 공고와 «어떻게 받았는가»를 함께 들고 다닌다."""
    return g2b_client.CollectOutcome(
        items=items,
        calls=1,
        method="시험 수집",
        keyword_totals={"AI": len(items)},
        truncated=(),
    )


def _fake_fetch(items: list[dict[str, Any]]):
    async def collect_notices(**_kwargs: Any) -> g2b_client.CollectOutcome:
        return _outcome(items)

    return collect_notices


def _failing_fetch(message: str = "G2B API error 99: 임시 장애"):
    async def collect_notices(**_kwargs: Any) -> g2b_client.CollectOutcome:
        raise g2b_client.G2BApiError("99", message)

    return collect_notices


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "bidpilot-api"
    assert isinstance(body["g2b_api_configured"], bool)


def test_list_procurements_reports_source_g2b_on_live_fetch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    live_fetch_on: None,
) -> None:
    # source "g2b" 는 **부르고 받았을 때만** 나오는 답이다 — 그래서 스위치를 켠다.
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))

    response = client.get("/api/procurements")
    assert response.status_code == 200
    body = response.json()

    assert body["source"] == "g2b"
    assert body["error"] is None
    assert body["total_fetched"] == len(raw_items)
    assert body["count"] == len(body["notices"])
    assert body["count"] >= 1
    assert isinstance(body["g2b_api_configured"], bool)

    first = body["notices"][0]
    assert first["notice_no"]
    assert first["title"]
    assert first["id"].startswith("g2b-")
    # 후보 판정 근거가 항상 함께 온다.
    assert first["candidate"]["tier"] == "high"
    assert first["candidate"]["method"] == "KEYWORD"


def test_include_low_widens_candidate_list(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    live_fetch_on: None,
) -> None:
    # 재는 것은 include_low 이지만, 비교할 공고가 실조회 경로로만 들어온다.
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))

    default_count = client.get("/api/procurements").json()["count"]
    widened = client.get("/api/procurements", params={"include_low": True}).json()

    assert widened["count"] > default_count
    assert {n["candidate"]["tier"] for n in widened["notices"]} >= {"low"}


def test_list_procurements_falls_back_to_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    live_fetch_on: None,
) -> None:
    # 호출 성공 → 실패 → 캐시 대체를 잇는 테스트다. 부르지 않으면 이 길 자체가 없다.
    # 1) 성공 호출로 캐시를 만든다.
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    live = client.get("/api/procurements").json()
    assert live["source"] == "g2b"

    # 2) 이후 호출이 실패하면 캐시로 대체된다.
    monkeypatch.setattr(g2b_client, "collect_notices", _failing_fetch())
    # 다시 받아 오는 것은 **POST** 다 (N1 · S8). GET 은 조회만 하므로 캐시·메모를 그대로
    # 돌려주고, 그러면 실호출 실패 경로를 아예 지나지 않는다.
    cached = client.post("/api/procurements/refresh").json()

    assert cached["source"] == "cached"
    assert cached["error"]
    assert cached["count"] == live["count"]
    assert [n["id"] for n in cached["notices"]] == [n["id"] for n in live["notices"]]


def test_list_procurements_returns_503_without_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(g2b_client, "collect_notices", _failing_fetch())

    response = client.get("/api/procurements")
    assert response.status_code == 503
    assert "캐시" in response.json()["detail"]


def test_get_procurement_by_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    live_fetch_on: None,
) -> None:
    # 상세로 찾아갈 id 가 실조회로 들어온 목록에서 나온다.
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    notice_id = client.get("/api/procurements").json()["notices"][0]["id"]

    response = client.get(f"/api/procurements/{notice_id}")
    assert response.status_code == 200
    assert response.json()["id"] == notice_id

    assert client.get("/api/procurements/g2b-does-not-exist-000").status_code == 404
