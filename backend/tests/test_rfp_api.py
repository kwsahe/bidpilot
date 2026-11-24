from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURE_ID = "synthetic-rfp-0001"


def test_parse_endpoint_returns_requirements_with_evidence() -> None:
    response = client.post("/api/rfp/parse", json={"procurement_id": FIXTURE_ID})
    assert response.status_code == 200
    body = response.json()

    assert body["procurement_id"] == FIXTURE_ID
    assert body["source"] == "synthetic_fixture"
    assert body["document"] == "synthetic_ai_training_rfp.pdf"
    assert body["page_count"] == 6
    assert body["count"] >= 10
    assert len(body["requirements"]) == body["count"]
    assert all(1 <= r["page"] <= 6 for r in body["requirements"])
    assert all(r["source_text"] for r in body["requirements"])


def test_get_requirements_after_parse() -> None:
    client.post("/api/rfp/parse", json={"procurement_id": FIXTURE_ID})
    response = client.get(f"/api/rfp/{FIXTURE_ID}/requirements")
    assert response.status_code == 200
    assert response.json()["count"] >= 10


def test_parse_rejects_unregistered_fixture() -> None:
    response = client.post("/api/rfp/parse", json={"procurement_id": "not-registered"})
    assert response.status_code == 404
    # 화면에 그대로 붙는 말 — 영문 「Unknown RFP fixture id」가 보였다 (RFP-13)
    assert response.json()["detail"].startswith("지원하지 않는 공고 주소입니다")


def test_parse_rejects_path_like_ids() -> None:
    response = client.post(
        "/api/rfp/parse", json={"procurement_id": "../sample_rfp/synthetic_ai_training_rfp.pdf"}
    )
    assert response.status_code == 404


def test_get_requirements_unknown_id_is_404() -> None:
    response = client.get("/api/rfp/unknown-id/requirements")
    assert response.status_code == 404
