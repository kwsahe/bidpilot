"""조건·체크리스트·결정 API 테스트 (합성 fixture 공고 사용, 네트워크 없음)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import action_service, critical_condition_service as ccs, decision_service, procurement_service

client = TestClient(app)
FIXTURE_ID = "synthetic-rfp-0001"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ccs, "CONDITION_DIR", tmp_path / "conditions")
    monkeypatch.setattr(action_service, "ACTION_DIR", tmp_path / "actions")
    monkeypatch.setattr(decision_service, "DECISION_DIR", tmp_path / "decisions")
    client.post("/api/rfp/parse", json={"procurement_id": FIXTURE_ID})


def test_detect_then_get_and_actions_seeded() -> None:
    response = client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["procurement_id"] == FIXTURE_ID
    assert body["method"] == "RULE"
    assert body["requirements_available"] is True
    assert body["notice_available"] is False  # 합성 공고는 나라장터 필드가 없다
    assert set(body["counts"]) == {"total", "blocker", "action", "check", "cleared", "info"}
    assert body["counts"]["cleared"] == 0  # 시스템은 CLEARED를 만들지 않는다
    for condition in body["conditions"]:
        assert condition["source_text"] or condition["source_field"]

    again = client.get(f"/api/conditions/{FIXTURE_ID}")
    assert again.status_code == 200
    assert again.json()["counts"] == body["counts"]

    actions = client.get(f"/api/actions/{FIXTURE_ID}")
    assert actions.status_code == 200
    # 조건 하나가 항상 «할 일 하나»는 아니다 — 설명회처럼 놓치는 자리가 여럿인 조건은
    # 실제로 해야 하는 순서대로 쪼갠다(action_service._STEPS_BY_TYPE). 그래서 개수가 아니라
    # «행동이 필요한 조건마다 항목이 있고, 그 밖의 조건에는 없다»를 본다 — 원래 의도 그대로다.
    actionable = {c["id"] for c in body["conditions"] if c["status"] in {"BLOCKER", "ACTION", "CHECK"}}
    seeded = {item["source_condition_id"] for item in actions.json()["items"] if item["source_condition_id"]}
    assert seeded <= actionable
    # 43차 E2E-14 — 같은 갈래 조건(쪼갠 세 줄이 같은 것)은 할 일 한 벌이고, 나머지 조건은 그 메모의 「관련 요구사항」 번호로 남는다.
    notes = " ".join(item.get("note") or "" for item in actions.json()["items"])
    for condition in body["conditions"]:
        if condition["id"] in actionable and condition["id"] not in seeded:
            assert condition["requirement_id"] and condition["requirement_id"] in notes, condition["id"]
    titles = [item["title"] for item in actions.json()["items"]]
    assert len(titles) == len(set(titles)), "같은 할 일이 두 번 생기지 않는다"

    # 다시 탐지해도 같은 조건에 항목이 또 생기지 않는다 (멱등).
    assert client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID}).status_code == 200
    again_actions = client.get(f"/api/actions/{FIXTURE_ID}").json()
    assert again_actions["counts"]["total"] == actions.json()["counts"]["total"]


def test_get_autodetects_when_missing() -> None:
    response = client.get(f"/api/conditions/{FIXTURE_ID}")
    assert response.status_code == 200
    assert response.json()["requirements_available"] is True


def test_detect_unknown_notice_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_notice(notice_id: str, **_kwargs):
        return None

    monkeypatch.setattr(procurement_service, "get_notice", no_notice)
    assert client.post("/api/conditions/detect", json={"procurement_id": "g2b-NOPE-000"}).status_code == 404
    assert client.get("/api/conditions/../etc").status_code in (404, 422)


def test_human_clear_and_decision_flow() -> None:
    report = client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID}).json()
    decision = client.get(f"/api/decision/{FIXTURE_ID}").json()
    assert decision["status"] == "UNREVIEWED"

    blockers = [c for c in report["conditions"] if c["status"] == "BLOCKER"]
    if blockers:
        blocked = client.put(
            f"/api/decision/{FIXTURE_ID}",
            json={"status": "GO", "reasons": ["적합"], "decided_by": "김담당"},
        )
        assert blocked.status_code == 422
        for blocker in blockers:
            cleared = client.put(
                f"/api/conditions/{FIXTURE_ID}/{blocker['id']}",
                json={"status": "CLEARED", "reviewer": "김담당", "note": "확인 완료"},
            )
            assert cleared.status_code == 200
        assert client.get(f"/api/conditions/{FIXTURE_ID}").json()["gate"]["can_go"] is True

    go = client.put(
        f"/api/decision/{FIXTURE_ID}",
        json={"status": "GO", "reasons": ["사업영역 적합", "일정 여유"], "decided_by": "김담당"},
    )
    assert go.status_code == 200, go.text
    assert go.json()["status"] == "GO"
    assert go.json()["decided_at"] is not None
    assert client.get(f"/api/decision/{FIXTURE_ID}").json()["status"] == "GO"


def test_decision_without_reason_is_422() -> None:
    response = client.put(f"/api/decision/{FIXTURE_ID}", json={"status": "NO_GO", "reasons": [], "decided_by": "김담당"})
    assert response.status_code == 422


def test_action_crud() -> None:
    created = client.post(f"/api/actions/{FIXTURE_ID}", json={"title": "인감증명서 발급", "priority": "high"})
    assert created.status_code == 201
    action_id = created.json()["id"]
    updated = client.put(f"/api/actions/{FIXTURE_ID}/{action_id}", json={"status": "done", "evidence": "발급 완료"})
    assert updated.status_code == 200 and updated.json()["completed_at"]
    assert client.delete(f"/api/actions/{FIXTURE_ID}/{action_id}").status_code == 204
    assert client.delete(f"/api/actions/{FIXTURE_ID}/{action_id}").status_code == 404


def test_report_carries_requirement_set_freshness() -> None:
    """방금 뽑은 요구사항으로 탐지했으면 current, 저장본이 낡으면 stale 을 그대로 내려보낸다.

    저장된 조건 보고서가 지금 요구사항 집합보다 오래됐는지 판정할 장치가 없어서,
    사람이 CLEARED 로 표시한 옛 판정이 최신인 것처럼 보였다. API 는 판정을 만들지 않고
    서비스가 준 값을 그대로 싣는다.
    """
    import json  # 파일 상단은 다른 작업자가 함께 쓰므로 여기서만 가져온다

    fresh = client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID}).json()
    assert fresh["freshness"] == "current"
    assert fresh["stale"] is False
    assert fresh["stale_reason"] is None
    assert fresh["requirement_set_hash"]
    assert fresh["requirement_set_hash"] == fresh["current_requirement_set_hash"]

    # 저장본만 옛 집합 기준으로 바꿔 둔다 (요구사항 파일은 그대로).
    store_path = ccs.report_path(FIXTURE_ID)
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["report"]["requirement_set_hash"] = "0000000000000000"
    store_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    stale = client.get(f"/api/conditions/{FIXTURE_ID}").json()
    assert stale["freshness"] == "stale"
    assert stale["stale"] is True
    assert stale["stale_reason"]
    # 낡았다고 조건을 감추지 않는다 — 목록도 게이트도 그대로 내려온다.
    assert len(stale["conditions"]) == len(fresh["conditions"])
    assert stale["gate"]["can_go"] == fresh["gate"]["can_go"]


def test_get_redetects_placeholder_made_before_requirements() -> None:
    """11-01 3순위 시험 — 공고를 분석 전에 열면 「제안요청서를 아직 읽지 않음」 보고서가 저장된다. 그 뒤 분석해도 GET 이
    그 자리표시를 그대로 돌려줘 결정 칸이 「공고 분석도 아직 하지 않았습니다」라 했다. 요구사항이 생겼으면 열 때 다시 찾는다."""
    import json

    fresh = client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID}).json()
    store_path = ccs.report_path(FIXTURE_ID)
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["report"].update(requirements_available=False, requirement_set_hash=None, requirement_set_id=None, conditions=[])
    store_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    # GET 을 거치기 전에는 결정 저장 · 목록 배지가 자리표시를 「확인된 차단 0」으로 읽지 않는다(독립 검토)
    assert ccs.load_report(FIXTURE_ID).freshness == "stale"
    assert ccs.gate_for(FIXTURE_ID) is None
    go = client.put(f"/api/decision/{FIXTURE_ID}", json={"status": "GO", "reasons": ["시험"], "decided_by": "pm"})
    assert go.status_code == 422, go.text
    # 공용 데모에 쓸 수 없는 다른 회사는 다시 찾지 않고 저장본 그대로(다시 찾으면 저장이 403 이었다 · 독립 검토)
    from app.schemas.organization import OrganizationCreateRequest
    from app.services import organization_service

    organization_service.create_organization(
        OrganizationCreateRequest(display_name="두번째데모", organization_id="org-demo-second", data_class="synthetic", created_by="k")
    )
    other = client.get(f"/api/conditions/{FIXTURE_ID}", params={"organization_id": "org-demo-second", "evidence_scope": "public_demo"})
    assert other.status_code == 200, other.text
    assert other.json()["stale"] is True and other.json()["requirements_available"] is False

    again = client.get(f"/api/conditions/{FIXTURE_ID}").json()
    assert again["requirements_available"] is True
    assert again["freshness"] == "current"
    assert len(again["conditions"]) == len(fresh["conditions"])


def test_condition_ids_are_content_based_when_stable_id_exists() -> None:
    """요구사항에 stable_id 가 있으면 조건 id 가 REQ 번호가 아니라 내용에서 나온다."""
    body = client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID}).json()
    from_requirements = [c for c in body["conditions"] if c["requirement_id"]]
    assert from_requirements, body["conditions"]
    assert all(c["id_basis"] == "stable_id" for c in from_requirements)
    # 옛 id 를 함께 들고 있어야 사람이 남긴 기록을 잃지 않는다.
    assert all(c["legacy_ids"] for c in from_requirements)


def _force_blocker() -> str:
    """탐지 결과에 참가 차단 조건이 없으면 하나를 BLOCKER 로 만든다(저장소를 직접 고쳐 — 게이트 계산은 그대로)."""
    report = client.post("/api/conditions/detect", json={"procurement_id": FIXTURE_ID}).json()
    blockers = [c for c in report["conditions"] if c["detected_status"] == "BLOCKER"]
    if blockers:
        return blockers[0]["id"]
    path = ccs.report_path(FIXTURE_ID, None)
    import json

    store = json.loads(path.read_text(encoding="utf-8"))
    first = store["report"]["conditions"][0]
    first["status"] = "BLOCKER"
    first["detected_status"] = "BLOCKER"
    path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    return first["id"]


def test_blocker_to_check_without_note_is_422_and_gate_stays_closed() -> None:
    """DTL-11 — 「확인 필요로」(CHECK)도 차단을 푼다. 메모 없이는 서버가 거절하고 참여는 막힌 채다."""
    condition_id = _force_blocker()
    assert client.get(f"/api/conditions/{FIXTURE_ID}").json()["gate"]["can_go"] is False
    for status in ("CHECK", "CLEARED"):
        refused = client.put(
            f"/api/conditions/{FIXTURE_ID}/{condition_id}",
            json={"status": status, "reviewer": "김담당", "note": "  "},
        )
        assert refused.status_code == 422, refused.text
        assert "메모" in refused.json()["detail"]
    assert client.get(f"/api/conditions/{FIXTURE_ID}").json()["gate"]["can_go"] is False


def test_blocker_to_check_with_note_is_200() -> None:
    condition_id = _force_blocker()
    ok = client.put(
        f"/api/conditions/{FIXTURE_ID}/{condition_id}",
        json={"status": "CHECK", "reviewer": "김담당", "note": "발주처에 확인 — 실적 인정 범위 문의 중"},
    )
    assert ok.status_code == 200, ok.text
    # 탐지가 BLOCKER 인 조건을 다시 BLOCKER 로 되돌리는 것은 메모가 없어도 된다
    back = client.put(f"/api/conditions/{FIXTURE_ID}/{condition_id}", json={"status": "BLOCKER", "reviewer": "김담당"})
    assert back.status_code == 200, back.text
