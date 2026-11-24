from fastapi.testclient import TestClient

from app.main import app
from app.services import demo_scenario, rfp_parser

client = TestClient(app)
FIXTURE_ID = "synthetic-rfp-0001"


def test_demo_scenario_endpoint_is_labeled_synthetic() -> None:
    response = client.get(f"/api/demo/cosmos/{FIXTURE_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "demo_synthetic"
    assert body["semantic_match"]["demo"] is True
    assert all(doc["synthetic"] is True for doc in body["evidence_documents"])
    assert body["evidence_documents"] and body["evidence_links"]
    assert body["proposal"]["sentences"] and body["audit"]["findings"]


def test_demo_scenario_references_only_parsed_requirements_and_known_ids() -> None:
    """데모 시나리오가 가리키는 REQ/EV/PS ID는 실제 파싱 결과와 시나리오 안에 존재해야 한다."""
    scenario = demo_scenario.load_demo_scenario(FIXTURE_ID)
    parsed = rfp_parser.parse_fixture(FIXTURE_ID)

    requirement_ids = {r.requirement_id for r in parsed.requirements}
    evidence_ids = {e.id for e in scenario.evidence_documents}
    sentence_ids = {s.id for s in scenario.proposal.sentences}

    for link in scenario.evidence_links:
        assert link.requirement_id in requirement_ids
        assert link.evidence_id in evidence_ids
    for sentence in scenario.proposal.sentences:
        assert sentence.requirement_id is None or sentence.requirement_id in requirement_ids
        assert sentence.evidence_id is None or sentence.evidence_id in evidence_ids
    for finding in scenario.audit.findings:
        assert finding.requirement_id is None or finding.requirement_id in requirement_ids
        assert finding.evidence_id is None or finding.evidence_id in evidence_ids
        assert finding.sentence_id is None or finding.sentence_id in sentence_ids
    for result in scenario.eligibility:
        assert result.requirement_id is None or result.requirement_id in requirement_ids


def test_demo_scenario_findings_quote_real_rfp_text() -> None:
    """Auditor 데모 발견 항목의 RFP 원문은 실제 파싱된 요구사항 원문에 있어야 한다 (없는 원문 금지)."""
    scenario = demo_scenario.load_demo_scenario(FIXTURE_ID)
    parsed = rfp_parser.parse_fixture(FIXTURE_ID)
    by_id = {r.requirement_id: r for r in parsed.requirements}

    for finding in scenario.audit.findings:
        if finding.source_text is None:
            continue
        assert finding.requirement_id is not None
        req = by_id[finding.requirement_id]
        assert finding.source_text == req.content
        assert finding.source_page == req.page


def test_demo_scenario_unknown_id_is_404() -> None:
    assert client.get("/api/demo/cosmos/unknown").status_code == 404


def test_합성_자료가_빠진_자료_폴더는_500_대신_까닭이_적힌_404(tmp_path, monkeypatch) -> None:
    """10-31 최종 점검 — 촬영 사본에 synthetic_company 가 없어 처리 못 한 FileNotFoundError 로 500 이었다."""
    monkeypatch.setattr(demo_scenario, "SYNTHETIC_DIR", tmp_path)
    response = client.get(f"/api/demo/cosmos/{FIXTURE_ID}")
    assert response.status_code == 404
    assert "synthetic_company" in response.json()["detail"]
