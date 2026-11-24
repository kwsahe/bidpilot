"""45차 H5 — 실적 원장 후보 채택(43차 결정 3 의 빈 곳). 호출 없음.

AI 검색을 꺼 둔 회사는 원장 후보(미채택)만 받는다. 「쓸 것을 골라 채택하세요」라는데 고를 곳이 없었다.
- 채택은 공고마다 (요구사항 번호, 후보 번호)로 남는다 — 누가 · 서버가 본 사람 · 언제.
- 초안은 채택한 후보만 근거로 쓴다(채택 전 후보는 「확인 필요」 문장 그대로).
- 지금 후보에 없는 번호 · 가상 예시(공용) 공고에는 남기지 않는다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.organization import AnalysisContext
from app.schemas.requirement import Requirement
from app.services import evidence_adoption_service, evidence_service, proposal_service, rfp_parser

ORG = get_settings().default_organization_id
CTX = AnalysisContext(organization_id=ORG, evidence_scope="internal")
PID = "g2b-R26BK45000001-000"


def _req(rid: str, title: str, content: str) -> Requirement:
    return Requirement(id=f"{PID}-{rid}", requirement_id=rid, procurement_id=PID, category="수행실적", requirement_type="mandatory",
                       title=title, content=content, page=3, source_text=content, status="unmatched")


REQS = [
    _req("REQ-001", "교육 운영 실적", "생성형 AI 교육 운영 실적을 제출하여야 한다."),
    _req("REQ-002", "강사 자격", "강사는 AI 교육 경력 3년 이상이어야 한다."),
]


def _ledger_match(rid: str, seq: int):
    return evidence_service.EvidenceMatch(
        requirement_id=rid, evidence_id=f"ledger-{seq}", document_name=f"실적 원장 {seq}번 — 생성형 AI 실무교육",
        doc_type="ledger", page=None, source_text=f"2025 · 생성형 AI 실무교육 {seq}", similarity_score=0.0, selected=False,
        note="원장 후보 실적(미채택)", synthetic=False, data_class="internal", source_kind="ledger", organization_id=ORG,
    )


@pytest.fixture(autouse=True)
def ai_search_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rfp_parser, "load_generated", lambda _pid: SimpleNamespace(requirements=REQS))
    monkeypatch.setattr(evidence_service, "load_index", lambda **_kw: [])
    monkeypatch.setattr(evidence_service, "ledger_candidates", lambda reqs, _ctx: [_ledger_match("REQ-001", 3), _ledger_match("REQ-001", 7)])


def test_채택_전에는_후보뿐이고_초안은_확인_필요() -> None:
    view = evidence_adoption_service.ledger_view(PID, CTX)
    assert view["ai_search_off"] is True and view["adopted_count"] == 0 and len(view["candidates"]) == 2
    links, _info = proposal_service._resolve_links(PID, REQS, CTX)
    drafts = proposal_service.build_drafts(REQS, links)
    first = next(d for d in drafts if d.requirement.requirement_id == "REQ-001")
    assert first.evidence is None and first.needs_review


def test_채택하면_누가_언제가_남고_초안이_그_실적을_근거로_쓴다() -> None:
    view = evidence_adoption_service.set_adoption(PID, CTX, requirement_id="REQ-001", evidence_id="ledger-7", adopted=True,
                                                  by="김담당", recorded_by="hajin")
    chosen = next(c for c in view["candidates"] if c["evidence_id"] == "ledger-7")
    assert chosen["adopted"]["by"] == "김담당" and chosen["adopted"]["recorded_by"] == "hajin" and chosen["adopted"]["at"]
    assert view["adopted_count"] == 1
    links, _info = proposal_service._resolve_links(PID, REQS, CTX)
    drafts = proposal_service.build_drafts(REQS, links)
    first = next(d for d in drafts if d.requirement.requirement_id == "REQ-001")
    assert first.grounding_type == "COMPANY_EVIDENCE_GROUNDED" and first.evidence.evidence_id == "ledger-7"
    # 채택 취소 — 다시 확인 필요
    evidence_adoption_service.set_adoption(PID, CTX, requirement_id="REQ-001", evidence_id="ledger-7", adopted=False, by="김담당")
    links, _info = proposal_service._resolve_links(PID, REQS, CTX)
    assert not any(link.selected for link in links)


def test_지금_후보에_없는_번호와_가상_예시_공고는_받지_않는다() -> None:
    with pytest.raises(evidence_adoption_service.AdoptionError):
        evidence_adoption_service.set_adoption(PID, CTX, requirement_id="REQ-002", evidence_id="ledger-3", adopted=True, by="김담당")
    demo = AnalysisContext(organization_id=ORG, evidence_scope="public_demo")
    with pytest.raises(evidence_adoption_service.AdoptionError):
        evidence_adoption_service.set_adoption(PID, demo, requirement_id="REQ-001", evidence_id="ledger-3", adopted=True, by="김담당")


def test_API_로_고르고_다시_읽는다() -> None:
    client = TestClient(app)
    res = client.put(f"/api/evidence/{PID}/ledger?organization_id={ORG}",
                     json={"requirement_id": "REQ-001", "evidence_id": "ledger-3", "adopted": True, "by": "김담당"})
    assert res.status_code == 200 and res.json()["adopted_count"] == 1
    got = client.get(f"/api/evidence/{PID}/ledger?organization_id={ORG}").json()
    assert next(c for c in got["candidates"] if c["evidence_id"] == "ledger-3")["adopted"]["by"] == "김담당"
    bad = client.put(f"/api/evidence/{PID}/ledger?organization_id={ORG}",
                     json={"requirement_id": "REQ-002", "evidence_id": "ledger-9", "adopted": True, "by": "김담당"})
    assert bad.status_code == 422
