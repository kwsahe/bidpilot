"""C. 공고 분석 격리 — 같은 공고를 A/B 로 분석하면 별도 결과, 제안서·Auditor 결과가 서로 보이지 않음, 레거시 결과 표시.

네트워크·임베딩 없음 (evidence_links 를 직접 넘기거나 인덱스 없음). 저장 경로는 conftest 가 tmp 로 돌린다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import org_storage, storage
from app.main import app
from app.schemas.organization import AnalysisContext, OrganizationCreateRequest
from app.schemas.proposal import EvidenceCandidate
from app.services import analysis_store, auditor_service, llm_client, organization_service, proposal_service, rfp_parser

client = TestClient(app)
PID = "synthetic-rfp-0001"
ORG_A = "org-demo-company"
ORG_B = "org-demo-second"
CTX_A = AnalysisContext(organization_id=ORG_A, evidence_scope="internal")
CTX_B = AnalysisContext(organization_id=ORG_B, evidence_scope="internal")
# 공용 데모 결과는 **기본 조직만** 쓸 수 있다 (ISSUE-006).
# 예전에는 아무 조직 id 로나 쓸 수 있었고, 그래서 다른 회사가 발표용 데모 화면을 바꿀 수 있었다.
CTX_DEMO = AnalysisContext(organization_id=org_storage.DEFAULT_ORGANIZATION_ID, evidence_scope="public_demo")
#: 기본 조직이 아닌 회사의 데모 컨텍스트 — 쓰기가 막혀야 한다.
CTX_DEMO_OTHER = AnalysisContext(organization_id=ORG_B, evidence_scope="public_demo")


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    monkeypatch.setattr(proposal_service, "PROPOSALS_DIR", tmp_path / "public_proposals")
    monkeypatch.setattr(auditor_service, "AUDIT_RUN_DIR", tmp_path / "public_audit_runs")
    for org_id, name in ((ORG_A, "데모교육연구소"), (ORG_B, "두번째데모")):
        organization_service.create_organization(OrganizationCreateRequest(display_name=name, organization_id=org_id, data_class="synthetic", created_by="k"))
    rfp_parser.parse_and_store(PID)


def _links(org_id: str) -> list[EvidenceCandidate]:
    return [
        EvidenceCandidate(requirement_id="REQ-001", evidence_id=f"CD-{org_id[-6:]}:001", document_name=f"{org_id} 회사소개", source_text=f"{org_id} 의 교육 운영 근거 문단", page=1, similarity_score=0.9, selected=True)
    ]


def test_same_procurement_two_organizations_get_separate_results() -> None:
    a = proposal_service.generate_section(PID, evidence_links=_links(ORG_A), context=CTX_A, use_llm=False)
    b = proposal_service.generate_section(PID, evidence_links=_links(ORG_B), context=CTX_B, use_llm=False)
    assert a.organization_id == ORG_A and b.organization_id == ORG_B
    assert a.evidence_scope == "internal" and a.legacy_result is False
    # 물리적으로 다른 파일
    path_a = proposal_service.proposal_path(PID, CTX_A)
    path_b = proposal_service.proposal_path(PID, CTX_B)
    assert path_a != path_b and path_a.exists() and path_b.exists()
    assert path_a.is_relative_to(org_storage.ORGANIZATIONS_DIR / ORG_A) and path_b.is_relative_to(org_storage.ORGANIZATIONS_DIR / ORG_B)
    # 공개 위치에는 아무것도 쓰지 않았다
    assert not (proposal_service.PROPOSALS_DIR / f"{PID}.proposal.json").exists()

    # A 제안서에 B 근거가 들어가지 않는다 (그 반대도)
    loaded_a = proposal_service.load_section(PID, CTX_A)
    loaded_b = proposal_service.load_section(PID, CTX_B)
    ids_a = {s.evidence_id for s in loaded_a.sentences if s.evidence_id}
    ids_b = {s.evidence_id for s in loaded_b.sentences if s.evidence_id}
    assert ids_a and ids_b and not (ids_a & ids_b)


def test_foreign_result_file_is_refused() -> None:
    proposal_service.generate_section(PID, evidence_links=_links(ORG_A), context=CTX_A, use_llm=False)
    # B 폴더에 A 조직 표시가 찍힌 파일이 놓여도 읽지 않는다
    payload = storage.read_json(proposal_service.proposal_path(PID, CTX_A))
    storage.write_json_atomic(proposal_service.proposal_path(PID, CTX_B), payload)
    with pytest.raises(analysis_store.ForeignResultError):
        proposal_service.load_section(PID, CTX_B)


def test_audit_runs_are_scoped_to_organization() -> None:
    run_a = auditor_service.run_and_store(PID, "교육은 총 12회 운영한다. 만족도 조사를 실시한다.", use_llm=False, context=CTX_A)
    assert run_a.organization_id == ORG_A
    assert auditor_service.load_run(run_a.id, context=CTX_A).id == run_a.id
    with pytest.raises(auditor_service.AuditRunNotFoundError):
        auditor_service.load_run(run_a.id, context=CTX_B)
    with pytest.raises(auditor_service.AuditRunNotFoundError):
        auditor_service.load_run(run_a.id)  # 공개 위치에는 없다
    assert not (auditor_service.AUDIT_RUN_DIR / f"{run_a.id}.json").exists()


def test_public_demo_results_go_to_public_location_with_scope_stamp() -> None:
    demo = proposal_service.generate_section(PID, context=CTX_DEMO, use_llm=False)
    assert demo.evidence_scope == "public_demo"
    path = proposal_service.proposal_path(PID, CTX_DEMO)
    assert path == proposal_service.PROPOSALS_DIR / f"{PID}.proposal.json" and path.exists()
    assert not path.is_relative_to(org_storage.ORGANIZATIONS_DIR)
    assert demo.evidence_summary is not None and demo.evidence_summary["real_evidence_used"] is False


def test_다른_회사는_공용_데모_결과를_바꿀_수_없다() -> None:
    """실측 사고: org-test-alpha 로 데모 제안서를 재생성하자 샘플에듀 대시보드의 발견 항목이
    2건에서 9건으로 바뀌었다. 데모 결과는 회사 구분 없이 한 파일이기 때문이다.

    저장 위치를 쪼개는 대신(발표 직전에 경로를 바꾸지 않는다) **쓰기를 기본 조직으로 한정**한다.
    읽기는 그대로 — 다른 회사도 데모를 볼 수는 있다.
    """
    with pytest.raises(analysis_store.PublicDemoReadOnlyError) as exc:
        proposal_service.generate_section(PID, context=CTX_DEMO_OTHER, use_llm=False)
    assert "함께 보는 자료" in str(exc.value)


def test_legacy_public_result_is_labelled_not_reused_as_current_org() -> None:
    """기본 조직의 internal 결과가 없으면 예전 공개 파일을 레거시로 돌려준다 — organization_id=None, public_demo 표시."""
    default_ctx = AnalysisContext(organization_id=org_storage.DEFAULT_ORGANIZATION_ID, evidence_scope="internal")
    proposal_service.generate_section(PID, context=CTX_DEMO, use_llm=False)  # 공개 위치의 합성 결과
    legacy = proposal_service.load_section(PID, default_ctx)
    assert legacy.legacy_result is True and legacy.organization_id is None and legacy.evidence_scope == "public_demo"
    assert legacy.evidence_summary is not None and legacy.evidence_summary["real_evidence_used"] is False
    # 다른 조직(B)에는 대체 조회가 없다 — 남의 결과처럼 보이지 않는다
    with pytest.raises(proposal_service.ProposalNotGeneratedError):
        proposal_service.load_section(PID, CTX_B)


def test_api_generate_and_get_are_bound_to_organization() -> None:
    r = client.post("/api/proposal/generate", json={"procurement_id": PID, "organization_id": ORG_A, "evidence_scope": "internal"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["organization_id"] == ORG_A and body["evidence_scope"] == "internal"
    # 내부 근거가 없으므로 (인덱스 없음) 합성 근거를 섞지 않는다
    assert body["evidence_grounded_count"] == 0
    assert body["evidence_summary"]["synthetic_evidence_used"] is False
    got = client.get(f"/api/proposal/{PID}?organization_id={ORG_A}&evidence_scope=internal").json()
    assert got["organization_id"] == ORG_A
    assert client.get(f"/api/proposal/{PID}?organization_id={ORG_B}&evidence_scope=internal").status_code == 404
    # 조직을 바꾸면 기존 결과를 재사용하지 않는다 — B 는 새 분석이 필요하다
    audit = client.post("/api/auditor/run", json={"procurement_id": PID, "proposal_text": "교육은 총 12회 운영한다.", "use_llm": False, "organization_id": ORG_A, "evidence_scope": "internal"}).json()
    assert audit["organization_id"] == ORG_A
    assert client.get(f"/api/auditor/{audit['id']}?organization_id={ORG_B}&evidence_scope=internal").status_code == 404
    assert client.get(f"/api/auditor/{audit['id']}?organization_id={ORG_A}&evidence_scope=internal").status_code == 200


def test_conditions_decision_review_are_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import critical_condition_service as ccs
    from app.services import decision_service, review_service

    monkeypatch.setattr(ccs, "CONDITION_DIR", tmp_path / "public_conditions")
    monkeypatch.setattr(decision_service, "DECISION_DIR", tmp_path / "public_decisions")
    monkeypatch.setattr(review_service, "REVIEW_DIR", tmp_path / "public_reviews")
    r = client.post("/api/conditions/detect", json={"procurement_id": PID, "organization_id": ORG_A, "evidence_scope": "internal"})
    assert r.status_code == 200, r.text
    assert r.json()["organization_id"] == ORG_A
    assert (org_storage.storage_for(ORG_A).analysis_dir(PID) / "conditions.json").exists()
    assert not (org_storage.storage_for(ORG_B).analysis_dir(PID) / "conditions.json").exists()
    decision = client.put(f"/api/decision/{PID}?organization_id={ORG_A}&evidence_scope=internal", json={"status": "HOLD", "reasons": ["검토 중"], "decided_by": "k"}).json()
    assert decision["organization_id"] == ORG_A and decision["status"] == "HOLD"
    other = client.get(f"/api/decision/{PID}?organization_id={ORG_B}&evidence_scope=internal").json()
    assert other["status"] == "UNREVIEWED" and other["organization_id"] == ORG_B
    review = client.post("/api/review", json={"procurement_id": PID, "status": "on_hold", "reviewer": "k", "organization_id": ORG_A, "evidence_scope": "internal"})
    assert review.status_code == 200 and review.json()["organization_id"] == ORG_A
    assert client.get(f"/api/review/{PID}?organization_id={ORG_B}&evidence_scope=internal").status_code == 204


def test_deleting_a_checklist_item_stays_in_the_organization_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """항목 삭제만 컨텍스트 없이 저장돼 공개 폴더로 새어 나가던 자리 (BE-5 (1)).

    context 가 없으면 analysis_store.resolve_path 가 data/public/actions/ 를 탄다.
    그러면 조직 폴더 파일은 지워지지 않은 채 남고 지운 결과만 공개 폴더에 새로 생겨,
    담당자가 「해당 없음」으로 지운 항목이 새로고침하면 되살아난다.
    """
    from app.schemas.action import ActionCreateRequest
    from app.services import action_service

    public_actions = tmp_path / "public_actions"
    monkeypatch.setattr(action_service, "ACTION_DIR", public_actions)

    first = action_service.create_action(PID, ActionCreateRequest(title="사전등록 완료"), context=CTX_A)
    second = action_service.create_action(PID, ActionCreateRequest(title="보안서약서 서명·제출"), context=CTX_A)
    action_service.delete_action(PID, first.id, context=CTX_A)

    # 공개 폴더에는 아무것도 생기지 않는다
    assert not public_actions.exists()
    # 조직 폴더의 실제 파일에서 지워졌다 — 다시 읽어도 되살아나지 않는다
    stored = storage.read_json(action_service.checklist_path(PID, CTX_A))
    assert [i["id"] for i in stored["items"]] == [second.id]
    assert stored["organization_id"] == ORG_A and stored["evidence_scope"] == "internal"
    assert [i.id for i in action_service.load_checklist(PID, CTX_A).items] == [second.id]
