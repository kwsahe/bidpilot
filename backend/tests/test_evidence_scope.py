"""B. 근거 격리 — internal 은 선택한 조직의 승인 자료만, public_demo 는 합성만. 만료·비활성·미승인 제외. 캐시 키에 조직 포함.

인덱스 파일은 손으로 만든다 (임베딩 키 없음). 벡터는 단위 벡터라 코사인을 손으로 계산할 수 있다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core import org_storage, storage
from app.schemas.organization import AnalysisContext, OrganizationCreateRequest
from app.services import evidence_service as es
from app.services import organization_service

ORG_A = "org-demo-company"
ORG_B = "org-demo-second"


def _chunk(evidence_id: str, document_id: str, *, data_class: str = "real", organization_id: str | None = None, valid_to: str | None = None, synthetic: bool = False) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": document_id,
        "document_name": f"문서 {document_id}",
        "doc_type": "회사소개",
        "page": 1,
        "source_text": "생성형 AI 실무교육 운영 경험이 있습니다. " * 2,
        "embedding": [1.0, 0.0],
        "data_class": data_class,
        "synthetic": synthetic,
        "source_kind": "synthetic" if synthetic else "upload",
        "scope": "public_demo" if synthetic else "internal",
        "valid_to": valid_to,
        "organization_id": organization_id,
    }


@pytest.fixture()
def two_orgs(monkeypatch: pytest.MonkeyPatch) -> None:
    # 실제 자료 등급 회사 두 곳 — internal 범위는 실제·비식별 문단만 본다 (합성 등급 회사 규칙은 아래 별도 테스트)
    for org_id, name in ((ORG_A, "데모교육연구소"), (ORG_B, "두번째데모")):
        organization_service.create_organization(OrganizationCreateRequest(display_name=name, organization_id=org_id, data_class="real", created_by="k"))
    # 등록부: A 는 문서 CD-A1 승인, CD-A2 비활성, CD-A3 미승인; B 는 CD-B1 승인
    from app.services import company_service as cs

    monkeypatch.setattr(cs, "active_document_ids", lambda org: {ORG_A: {"CD-A1"}, ORG_B: {"CD-B1"}}.get(org, set()))
    storage.write_json_atomic(
        org_storage.storage_for(ORG_A).index_file,
        {
            "organization_id": ORG_A,
            "chunks": [
                _chunk("CD-A1:001", "CD-A1", organization_id=ORG_A),
                _chunk("CD-A2:001", "CD-A2", organization_id=ORG_A),  # 비활성(등록부에 없음)
                _chunk("CD-A1:002", "CD-A1", organization_id=ORG_A, valid_to="2020-01-01"),  # 만료
                _chunk("EV-syn:001", "CD-A1", data_class="synthetic", synthetic=True),  # 합성이 섞여 있어도 internal 에서 뺀다
                _chunk("CD-B9:001", "CD-B9", organization_id=ORG_B),  # 다른 조직 표시가 섞여 있어도 뺀다
            ],
        },
    )
    storage.write_json_atomic(org_storage.storage_for(ORG_B).index_file, {"organization_id": ORG_B, "chunks": [_chunk("CD-B1:001", "CD-B1", organization_id=ORG_B)]})
    # 합성 인덱스 (public_demo)
    monkeypatch.setattr(es, "INDEX_FILE", org_storage.ORGANIZATIONS_DIR.parent / "synthetic_index.json")
    storage.write_json_atomic(es.INDEX_FILE, {"chunks": [_chunk("EV-01", "EV-01", data_class="synthetic", synthetic=True), _chunk("CD-leak:001", "CD-leak", data_class="real")]})


def test_internal_scope_uses_only_the_selected_organization(two_orgs: None) -> None:
    a = es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="internal"), today=date(2026, 9, 7))
    assert [c.evidence_id for c in a] == ["CD-A1:001"]
    assert all(c.organization_id == ORG_A and not c.synthetic for c in a)
    b = es.load_index(context=AnalysisContext(organization_id=ORG_B, evidence_scope="internal"), today=date(2026, 9, 7))
    assert [c.evidence_id for c in b] == ["CD-B1:001"]


def test_internal_scope_has_zero_synthetic_chunks(two_orgs: None) -> None:
    a = es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="internal"))
    assert sum(1 for c in a if c.synthetic or c.data_class == "synthetic") == 0


def test_public_demo_scope_has_zero_real_chunks(two_orgs: None) -> None:
    demo = es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="public_demo"))
    assert [c.evidence_id for c in demo] == ["EV-01"]
    assert all(c.synthetic and c.data_class == "synthetic" for c in demo)
    assert all(not c.evidence_id.startswith("CD-") for c in demo)


def test_synthetic_company_internal_scope_uses_only_its_own_synthetic_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """합성 등급 회사(데모·테스트 회사)는 그 회사가 직접 올려 승인한 합성 문단만 internal 로 본다.

    실제 등급 문단도, 공유 합성 인덱스(EV-*)도 섞이지 않는다. 실제 회사에는 합성 문단이 들어가지 않는 규칙과 대칭이다.
    """
    org = "org-demo-synthetic"
    organization_service.create_organization(OrganizationCreateRequest(display_name="합성데모", organization_id=org, data_class="synthetic", created_by="k"))
    from app.services import company_service as cs

    monkeypatch.setattr(cs, "active_document_ids", lambda o: {"CD-S1"} if o == org else set())
    storage.write_json_atomic(
        org_storage.storage_for(org).index_file,
        {
            "organization_id": org,
            "chunks": [
                _chunk("CD-S1:001", "CD-S1", data_class="synthetic", organization_id=org),
                _chunk("CD-S1:002", "CD-S1", data_class="real", organization_id=org),  # 실제 등급 문단은 합성 회사 범위에 들어가지 않는다
            ],
        },
    )
    monkeypatch.setattr(es, "INDEX_FILE", org_storage.ORGANIZATIONS_DIR.parent / "synthetic_index_2.json")
    storage.write_json_atomic(es.INDEX_FILE, {"chunks": [_chunk("EV-01", "EV-01", data_class="synthetic", synthetic=True)]})

    internal = es.load_index(context=AnalysisContext(organization_id=org, evidence_scope="internal"))
    assert [c.evidence_id for c in internal] == ["CD-S1:001"]
    demo = es.load_index(context=AnalysisContext(organization_id=org, evidence_scope="public_demo"))
    assert [c.evidence_id for c in demo] == ["EV-01"]


def test_expired_inactive_unapproved_are_excluded(two_orgs: None) -> None:
    a = es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="internal"), today=date(2026, 9, 7))
    ids = {c.evidence_id for c in a}
    assert "CD-A2:001" not in ids and "CD-A1:002" not in ids and "CD-B9:001" not in ids


def test_match_reports_scope_and_never_mixes(two_orgs: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.requirement import Requirement

    req = Requirement(id="t:REQ-001", procurement_id="t", requirement_id="REQ-001", category="과업내용", requirement_type="mandatory", title="교육", content="생성형 AI 교육 운영", page=1, source_text="생성형 AI 교육 운영", status="unmatched")
    monkeypatch.setattr(es.llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(es, "embed_requirements", lambda reqs: {"REQ-001": [1.0, 0.0]})

    internal = es.match_requirements([req], context=AnalysisContext(organization_id=ORG_A, evidence_scope="internal"))
    assert internal.available and [m.evidence_id for m in internal.matches] == ["CD-A1:001"]
    assert internal.scope_info is not None
    assert internal.scope_info.model_dump() | {"note": None} == {
        "organization_id": ORG_A,
        "evidence_scope": "internal",
        "used_document_count": 1,
        "used_chunk_count": 1,
        "synthetic_evidence_used": False,
        "real_evidence_used": True,
        "note": None,
    }

    demo = es.match_requirements([req], context=AnalysisContext(organization_id=ORG_A, evidence_scope="public_demo"))
    assert [m.evidence_id for m in demo.matches] == ["EV-01"]
    assert demo.scope_info is not None and demo.scope_info.synthetic_evidence_used is True and demo.scope_info.real_evidence_used is False


def test_cache_key_contains_organization_and_scope() -> None:
    a = AnalysisContext(organization_id=ORG_A, evidence_scope="internal")
    b = AnalysisContext(organization_id=ORG_B, evidence_scope="internal")
    demo = AnalysisContext(organization_id=ORG_A, evidence_scope="public_demo")
    keys = {a.cache_key("g2b-1"), b.cache_key("g2b-1"), demo.cache_key("g2b-1")}
    assert len(keys) == 3
    assert ORG_A in a.cache_key("g2b-1") and "internal" in a.cache_key("g2b-1")


def test_eligibility_last_report_cache_is_per_organization() -> None:
    from datetime import datetime, timezone

    from app.schemas.eligibility import EligibilityCounts, EligibilityReport
    from app.services import eligibility_engine as ee

    report = EligibilityReport(procurement_id="g2b-X", verdict="PASS", counts=EligibilityCounts(total=0, passed=0, check=0, failed=0), evaluated_at=datetime.now(timezone.utc), notice_available=False, requirements_available=False, llm_used=False, results=[])
    ctx_a = AnalysisContext(organization_id=ORG_A, evidence_scope="internal")
    ctx_b = AnalysisContext(organization_id=ORG_B, evidence_scope="internal")
    ee._LAST_REPORTS[ee._cache_key("g2b-X", ctx_a)] = report
    assert ee.get_last_report("g2b-X", ctx_a) is report
    assert ee.get_last_report("g2b-X", ctx_b) is None
    assert ee.get_last_report("g2b-X") is None
    ee._LAST_REPORTS.pop(ee._cache_key("g2b-X", ctx_a), None)


def test_회사_사실이_바뀌면_지난_판정을_돌려주지_않는다(monkeypatch) -> None:
    """등록 업종을 적은 뒤 3단계가 옛 「확인 필요」를 보이면 목록과 어긋난다 (19차 §4-D 실측)."""
    from datetime import datetime, timezone

    from app.schemas.eligibility import EligibilityCounts, EligibilityReport
    from app.services import eligibility_engine as ee

    facts = {"now": ee.CompanyFacts()}
    monkeypatch.setattr(ee, "company_facts_for", lambda organization_id, evidence_scope=None: facts["now"])
    monkeypatch.setattr(ee, "_LAST_REPORTS", {})
    report = EligibilityReport(procurement_id="g2b-X", verdict="CHECK", counts=EligibilityCounts(total=0, passed=0, check=0, failed=0), evaluated_at=datetime.now(timezone.utc), notice_available=False, requirements_available=False, llm_used=False, results=[])
    ctx = AnalysisContext(organization_id=ORG_A, evidence_scope="internal")
    ee._LAST_REPORTS[ee._cache_key("g2b-X", ctx)] = report
    assert ee.get_last_report("g2b-X", ctx) is report
    facts["now"] = ee.CompanyFacts(registered_industry_codes=("1468",))
    assert ee.get_last_report("g2b-X", ctx) is None


def test_region_rule_uses_organization_regions_and_checks_when_missing() -> None:
    from app.services import eligibility_engine as ee

    raw = {"rgnLmtBidLocplcJdgmBssNm": "서울특별시"}
    ee._ACTIVE_REGIONS.set(("서울특별시",))
    try:
        assert ee._rule_region(raw).status == "PASS"
    finally:
        ee._ACTIVE_REGIONS.set(None)
    ee._ACTIVE_REGIONS.set(())
    try:
        result = ee._rule_region(raw)
        assert result.status == "CHECK" and "활동 지역" in result.reason
    finally:
        ee._ACTIVE_REGIONS.set(None)


# --------------------------------------------------------------------------
# 근거의 「공개 범위」(EvidenceMetadata.scope) — 인덱스에 실려 있기만 하고 아무도 보지 않던 값 (BE-5 (3))
# --------------------------------------------------------------------------


def test_public_demo_excludes_chunks_approved_as_internal_only(two_orgs: None) -> None:
    """담당자가 「내부 전용」으로 승인한 문단은 공개 데모 분석에 들어오면 안 된다.

    scope 는 승인 화면에서 고른 값이고 색인에도 실려 EvidenceChunk 까지 올라오는데,
    조회 쪽에서 «한 번도 읽지 않아» 스위치가 꺼진 채로 있었다.
    """
    payload = storage.read_json(es.INDEX_FILE)
    internal_only = _chunk("EV-02", "EV-02", data_class="synthetic", synthetic=True)
    internal_only["scope"] = "internal"
    payload["chunks"].append(internal_only)
    storage.write_json_atomic(es.INDEX_FILE, payload)

    demo = es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="public_demo"))
    assert [c.evidence_id for c in demo] == ["EV-01"]


def test_internal_keeps_legacy_chunks_without_scope(two_orgs: None) -> None:
    """scope 표시가 없는 레거시 chunk 를 internal 에서 빼면 회사 근거가 통째로 사라진다.

    표시가 없다는 이유로 지우는 쪽이 아니라 internal 로 보고 남기는 쪽으로 기운다.
    """
    path = org_storage.storage_for(ORG_A).index_file
    payload = storage.read_json(path)
    legacy = _chunk("CD-A1:003", "CD-A1", organization_id=ORG_A)
    legacy.pop("scope")
    payload["chunks"].append(legacy)
    storage.write_json_atomic(path, payload)

    ids = [c.evidence_id for c in es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="internal"), today=date(2026, 9, 7))]
    assert "CD-A1:003" in ids


def test_internal_also_uses_chunks_approved_for_public(two_orgs: None) -> None:
    """공개로 열어 둔 자료를 사내 분석에서 뺄 이유는 없다 — internal ⊇ public_demo."""
    path = org_storage.storage_for(ORG_A).index_file
    payload = storage.read_json(path)
    shared = _chunk("CD-A1:004", "CD-A1", organization_id=ORG_A)
    shared["scope"] = "public_demo"
    payload["chunks"].append(shared)
    storage.write_json_atomic(path, payload)

    ids = [c.evidence_id for c in es.load_index(context=AnalysisContext(organization_id=ORG_A, evidence_scope="internal"), today=date(2026, 9, 7))]
    assert "CD-A1:004" in ids
