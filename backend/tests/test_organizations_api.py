"""조직(회사) API — 생성·목록·격리·보안·공개 데모 쓰기 차단.

A. 조직 격리: A/B 생성, 같은 파일 각각 등록, A 문서가 B 목록·B URL 에서 보이지 않음, 인덱스 재생성 독립.
E. 보안: 경로 순회 id 차단, 공개 배포 모드에서 쓰기 403, 응답 헤더로 위임 조직 표시.
저장 경로는 conftest 가 tmp 로 돌린다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import org_storage
from app.core.config import get_settings
from app.main import app
from app.services import llm_client

client = TestClient(app)

MD = """---
document_name: 회사소개(테스트)
---

# 사업영역

생성형 AI 실무교육과 업무자동화 컨설팅을 수행합니다. 공공기관과 대학을 대상으로 과정을 운영합니다.

# 운영 체계

수강생 계정을 일괄 생성하고 종료 후 회수하는 절차를 운영하며 만족도 조사를 기록합니다.
"""


@pytest.fixture(autouse=True)
def no_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)


def create(org_id: str, name: str, data_class: str = "synthetic") -> dict:
    r = client.post("/api/organizations", json={"organization_id": org_id, "display_name": name, "data_class": data_class, "created_by": "김담당"})
    assert r.status_code == 201, r.text
    return r.json()


def upload(org_id: str, name: str = "intro.md", text: str = MD) -> dict:
    r = client.post(f"/api/organizations/{org_id}/documents", files={"file": (name, text.encode("utf-8"), "text/markdown")}, data={"doc_type": "회사소개", "uploaded_by": "김담당"})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------
# 생성 · 목록 · 기본 조직
# --------------------------------------------------------------------------


def test_default_organization_exists_and_is_real_internal() -> None:
    body = client.get("/api/organizations").json()
    ids = [o["organization"]["organization_id"] for o in body["organizations"]]
    assert org_storage.DEFAULT_ORGANIZATION_ID in ids
    default = next(o for o in body["organizations"] if o["organization"]["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID)
    assert default["organization"]["display_name"] == "주식회사 샘플에듀"
    assert default["organization"]["data_class"] == "real" and default["organization"]["approved_for_public"] is False
    assert default["usable_in_public_demo"] is False
    assert body["default_organization_id"] == get_settings().default_organization_id
    assert body["local_admin_mode"] is True and body["public_demo_mode"] is False


def test_create_two_organizations_and_list() -> None:
    a = create("org-demo-company", "데모교육연구소")
    b = create("org-demo-second", "두번째데모")
    assert a["organization_id"] == "org-demo-company" and a["status"] == "active"
    assert a["created_by"] == "김담당" and a["updated_by"] == "김담당"
    listing = client.get("/api/organizations").json()
    ids = {o["organization"]["organization_id"] for o in listing["organizations"]}
    assert {"org-demo-company", "org-demo-second", org_storage.DEFAULT_ORGANIZATION_ID} <= ids
    assert b["data_class"] == "synthetic"
    # id 생략 시 회사명에서 slug 를 만든다 (한글 상호는 짧은 uuid)
    auto = client.post("/api/organizations", json={"display_name": "Acme Edu", "created_by": "k"}).json()
    assert auto["organization_id"].startswith("org-acme-edu")
    korean = client.post("/api/organizations", json={"display_name": "한글상호", "created_by": "k"}).json()
    assert korean["organization_id"].startswith("org-") and len(korean["organization_id"]) >= 8
    # 중복 id 는 409 — 화면 문장은 「회사 코드」로 말한다 (CMP-15)
    dup = client.post("/api/organizations", json={"organization_id": "org-demo-company", "display_name": "x", "created_by": "k"})
    assert dup.status_code == 409 and "이미 있는 회사 코드입니다" in dup.json()["detail"] and "organization_id" not in dup.json()["detail"]
    bad = client.post("/api/organizations", json={"organization_id": "Org Bad", "display_name": "x", "created_by": "k"})
    assert bad.status_code == 400 and "허용되지 않는 회사 코드입니다" in bad.json()["detail"] and "organization_id" not in bad.json()["detail"]


def test_update_activate_deactivate_and_profile() -> None:
    create("org-demo-company", "데모교육연구소")
    patched = client.patch("/api/organizations/org-demo-company", json={"display_name": "데모교육연구소(주)", "updated_by": "박검토"}).json()
    assert patched["display_name"] == "데모교육연구소(주)" and patched["updated_by"] == "박검토"
    assert patched["organization_id"] == "org-demo-company"  # 이름이 바뀌어도 id 는 그대로
    off = client.post("/api/organizations/org-demo-company/deactivate", json={"updated_by": "박검토"}).json()
    assert off["status"] == "inactive"
    # 비활성 조직으로는 분석 컨텍스트를 만들 수 없다
    r = client.get("/api/proposal/synthetic-rfp-0001?organization_id=org-demo-company&evidence_scope=public_demo")
    assert r.status_code == 409
    on = client.post("/api/organizations/org-demo-company/activate", json={"updated_by": "박검토"}).json()
    assert on["status"] == "active"
    profile = client.get("/api/organizations/org-demo-company/profile").json()
    assert profile["source"] == "default_synthetic" and profile["organization_id"] == "org-demo-company"
    saved = client.put(
        "/api/organizations/org-demo-company/profile",
        json={"name": "데모교육연구소", "business_domains": ["AI 교육"], "preferred_regions": ["서울특별시"], "data_class": "synthetic", "updated_by": "박검토"},
    ).json()
    assert saved["source"] == "file" and saved["preferred_regions"] == ["서울특별시"]
    # 프로필 공개 응답에 사업자번호·개인 연락처 키가 없다
    assert not {"business_registration_number", "corporate_number", "representative_phone"} & set(saved.keys())


# --------------------------------------------------------------------------
# A. 조직 간 문서 격리
# --------------------------------------------------------------------------


def test_documents_are_isolated_between_organizations() -> None:
    create("org-demo-company", "데모교육연구소")
    create("org-demo-second", "두번째데모")
    doc_a = upload("org-demo-company")
    doc_b = upload("org-demo-second")  # 같은 파일을 다른 조직이 등록 — 허용
    assert doc_a["organization_id"] == "org-demo-company" and doc_b["organization_id"] == "org-demo-second"
    assert doc_a["sha256"] == doc_b["sha256"]

    list_a = client.get("/api/organizations/org-demo-company/documents").json()
    list_b = client.get("/api/organizations/org-demo-second/documents").json()
    assert [d["id"] for d in list_a["documents"]] == [doc_a["id"]]
    assert [d["id"] for d in list_b["documents"]] == [doc_b["id"]]
    assert list_a["organization_id"] == "org-demo-company"

    # A 문서 id 를 B URL 로 조회하면 내용을 노출하지 않는다 (404, 존재 여부도 알 수 없다)
    cross = client.get(f"/api/organizations/org-demo-second/documents/{doc_a['id']}")
    assert cross.status_code == 404 and "없는 문서" in cross.json()["detail"]
    assert client.get(f"/api/organizations/org-demo-second/documents/{doc_a['id']}/usage").status_code == 404
    assert client.post(f"/api/organizations/org-demo-second/documents/{doc_a['id']}/approve", json={"reviewer": "k"}).status_code == 404
    assert client.delete(f"/api/organizations/org-demo-second/documents/{doc_a['id']}").status_code == 404

    # 같은 조직 안에서는 중복 409 — 내부 id 대신 문서 이름을 한 번만 (CMP-15)
    again = client.post("/api/organizations/org-demo-company/documents", files={"file": ("again.md", MD.encode("utf-8"), "text/markdown")})
    assert again.status_code == 409
    assert again.json()["detail"] == f"같은 내용의 문서가 이미 있습니다: 「{doc_a['title']}」"

    # 기본 조직(샘플에듀) 목록에도 테스트 회사 문서가 섞이지 않는다
    default = client.get(f"/api/organizations/{org_storage.DEFAULT_ORGANIZATION_ID}/documents").json()
    assert doc_a["id"] not in [d["id"] for d in default["documents"]]

    # 파일은 각자 폴더에만 있다
    assert org_storage.storage_for("org-demo-company").upload_path(doc_a["id"], ".md").exists()
    assert not org_storage.storage_for("org-demo-second").upload_path(doc_a["id"], ".md").exists()


def test_review_approve_index_do_not_leak_across_organizations() -> None:
    create("org-demo-company", "데모교육연구소")
    create("org-demo-second", "두번째데모")
    doc_a = upload("org-demo-company")
    doc_b = upload("org-demo-second")
    cand_a = next(c for c in doc_a["candidates"] if not c["is_gap"])
    reviewed = client.put(f"/api/organizations/org-demo-company/documents/{doc_a['id']}/candidates", json={"reviewer": "k", "reviews": [{"candidate_id": cand_a["id"], "approved": True}]})
    assert reviewed.status_code == 200
    approved = client.post(f"/api/organizations/org-demo-company/documents/{doc_a['id']}/approve", json={"reviewer": "k", "data_class": "synthetic"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    # B 문서는 미검토 상태 그대로
    b_detail = client.get(f"/api/organizations/org-demo-second/documents/{doc_b['id']}").json()
    assert b_detail["status"] == "review" and all(c["approved"] is None for c in b_detail["candidates"] if not c["is_gap"])

    # 인덱스 상태·재생성은 조직별 (키가 없어 ok:false 지만 서로 다른 organization_id 를 돌려준다)
    idx_a = client.get("/api/organizations/org-demo-company/index").json()
    idx_b = client.get("/api/organizations/org-demo-second/index").json()
    assert idx_a["organization_id"] == "org-demo-company" and idx_a["pending_documents"] == 1
    assert idx_b["organization_id"] == "org-demo-second" and idx_b["pending_documents"] == 0
    rebuild_a = client.post("/api/organizations/org-demo-company/index/rebuild").json()
    assert rebuild_a["ok"] is False and rebuild_a["organization_id"] == "org-demo-company"
    assert not org_storage.storage_for("org-demo-second").index_file.exists()
    # 검색은 AI 검색 설정이 없으면 정직하게 불가.
    #
    # 계약이 바뀌었다: 예전에는 200 + {"available": false} 였다. 그러면 화면이 «성공했는데
    # 결과가 0건»으로 읽어 「검색된 문단이 없습니다」를 보여줬다 — 설정이 없다는 사실이
    # 사라졌다. 지금은 503 + 한국어 사유로 답한다 (ISSUE-002).
    search = client.post("/api/organizations/org-demo-company/index/search", json={"query": "생성형 AI 교육"})
    assert search.status_code == 503
    detail = search.json()["detail"]
    assert "AI 검색 설정" in detail
    assert "키" not in detail and "임베딩" not in detail

    # 비활성 문서 검토는 409 — 사유는 영어 상태값(retired)이 아니라 한국어 이름으로 (CMP-09)
    assert client.post(f"/api/organizations/org-demo-company/documents/{doc_a['id']}/retire", json={"reviewer": "k"}).status_code == 200
    again = client.put(f"/api/organizations/org-demo-company/documents/{doc_a['id']}/candidates", json={"reviewer": "k", "reviews": [{"candidate_id": cand_a["id"], "approved": True}]})
    assert again.status_code == 409 and again.json()["detail"] == "「비활성」 상태의 문서는 검토할 수 없습니다"


# --------------------------------------------------------------------------
# E. 보안 — 경로 순회 · 공개 데모 쓰기 차단 · 호환 헤더
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["../org-sample", "..%2Forg-sample", "%2e%2e/org-sample", "org-sample/../x", "ORG-SAMPLEEDU", "org_sample", "C:%5Cwindows", "org-", "org--x", "org-x"],
)
def test_path_traversal_ids_are_rejected(bad: str) -> None:
    r = client.get(f"/api/organizations/{bad}/documents")
    assert r.status_code == 404, (bad, r.status_code, r.text)
    with pytest.raises(org_storage.InvalidOrganizationIdError):
        org_storage.validate_organization_id(bad)


def test_unknown_organization_is_404_without_leaking() -> None:
    r = client.get("/api/organizations/org-nope/documents")
    assert r.status_code == 404
    assert client.get("/api/organizations/org-nope").status_code == 404
    assert client.get("/api/proposal/synthetic-rfp-0001?organization_id=org-nope").status_code == 404


def test_public_demo_mode_blocks_writes_and_internal_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "public_demo_mode", True)
    try:
        assert client.post("/api/organizations", json={"display_name": "x", "created_by": "k"}).status_code == 403
        assert client.post(f"/api/organizations/{org_storage.DEFAULT_ORGANIZATION_ID}/documents", files={"file": ("a.md", MD.encode("utf-8"), "text/markdown")}).status_code == 403
        assert client.put(f"/api/organizations/{org_storage.DEFAULT_ORGANIZATION_ID}/profile", json={"name": "x", "updated_by": "k"}).status_code == 403
        assert client.post(f"/api/organizations/{org_storage.DEFAULT_ORGANIZATION_ID}/index/rebuild").status_code == 403
        assert client.post("/api/company/documents", files={"file": ("a.md", MD.encode("utf-8"), "text/markdown")}).status_code == 403
        # 수행역량 자료도 쓰기다 — 여기만 검사가 빠져 공개 링크에서 누구나 바꿀 수 있었다 (ISSUE-026).
        assert client.put("/api/capability/profile", json={"updated_by": "k"}).status_code == 403
        # 읽기는 된다
        assert client.get("/api/organizations").status_code == 200
        assert client.get("/api/organizations").json()["public_demo_mode"] is True
        # 공개 배포 모드에서는 internal 범위를 고를 수 없다
        assert client.get("/api/proposal/synthetic-rfp-0001?evidence_scope=internal").status_code == 400
    finally:
        monkeypatch.setattr(settings, "public_demo_mode", False)


def test_legacy_company_api_delegates_to_default_org_with_headers() -> None:
    r = client.get("/api/company/index")
    assert r.status_code == 200
    assert r.headers["X-Organization-Id"] == org_storage.DEFAULT_ORGANIZATION_ID
    assert r.headers["X-Compat-Api"] == "company"
    assert r.json()["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID


def test_explicit_test_scope_is_not_selectable_via_api() -> None:
    assert client.get("/api/proposal/synthetic-rfp-0001?evidence_scope=explicit_test").status_code == 400


# --------------------------------------------------------------------------
# F. 요약 숫자 — 「승인」 한 단어가 두 숫자를 말하지 않게
# --------------------------------------------------------------------------


def approve_first_candidate(org_id: str, doc: dict) -> None:
    cand = next(c for c in doc["candidates"] if not c["is_gap"])
    r = client.put(f"/api/organizations/{org_id}/documents/{doc['id']}/candidates", json={"reviewer": "김담당", "reviews": [{"candidate_id": cand["id"], "approved": True}]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/organizations/{org_id}/documents/{doc['id']}/approve", json={"reviewer": "김담당", "data_class": "synthetic"})
    assert r.status_code == 200, r.text


def test_summary_splits_approved_into_indexed_and_waiting() -> None:
    """요약이 「승인」을 조각으로 함께 내려준다.

    예전에는 요약의 approved_document_count(=approved+indexed) 하나뿐이라, 화면이
    문서 목록의 counts["approved"](=색인 전만)와 같은 「승인 N건」이라는 말로 서로 다른 수를 적었다.
    두 숫자가 각각 무엇인지 여기서 못박는다.
    """
    org = "org-demo-company"
    create(org, "데모교육연구소")
    doc = upload(org)

    before = client.get(f"/api/organizations/{org}").json()
    assert before["document_count"] == 1
    assert before["approved_document_count"] == 0
    assert before["indexed_document_count"] == 0 and before["approved_not_indexed_document_count"] == 0
    # 검토 중인 자료는 근거로 쓰이지 않는다 — 「등록 1건」과 「근거로 쓰임 0건」은 다른 말이다
    assert before["active_evidence_document_count"] == 0

    approve_first_candidate(org, doc)
    listing = client.get(f"/api/organizations/{org}/documents").json()
    after = client.get(f"/api/organizations/{org}").json()
    # 임베딩 키가 없어 색인은 대기 상태다 (conftest 의 no_embedding)
    assert listing["counts"].get("approved") == 1 and listing["counts"].get("indexed") is None
    assert after["approved_document_count"] == 1  # 기존 필드의 뜻은 그대로 (approved + indexed)
    assert after["approved_not_indexed_document_count"] == listing["counts"]["approved"] == 1
    assert after["indexed_document_count"] == 0
    assert after["approved_document_count"] == after["indexed_document_count"] + after["approved_not_indexed_document_count"]
    assert after["active_evidence_document_count"] == 1

    # 비활성 처리하면 승인 이력은 남지만 근거로는 쓰이지 않는다 — 이 차이가 사실이다
    r = client.post(f"/api/organizations/{org}/documents/{doc['id']}/retire", json={"reviewer": "김담당", "note": "구버전"})
    assert r.status_code == 200, r.text
    retired = client.get(f"/api/organizations/{org}").json()
    assert retired["active_evidence_document_count"] == 0
    assert retired["document_count"] == 1


def test_summary_says_registry_read_failure_instead_of_no_documents() -> None:
    """등록부를 못 읽은 것을 「자료 없음」으로 뭉개지 않는다.

    깨진 등록부는 첫 읽기에서 `.corrupt-*` 로 격리되고, 그 뒤로는 「파일 없음 = 빈 등록부」가 되어
    화면에 오류 없이 「등록된 회사자료가 없습니다」로만 보였다 — 자료가 증발한 것과 구분되지 않는다.
    """
    from app.services import company_service

    org = "org-demo-company"
    create(org, "데모교육연구소")
    upload(org)
    assert client.get(f"/api/organizations/{org}").json()["document_registry_note"] is None

    org_storage.storage_for(org).documents_file.write_text("{{{ 깨진 JSON", encoding="utf-8")
    with pytest.raises(company_service.CompanyRegistryUnavailableError):
        company_service.list_documents(org)  # 첫 읽기에서 격리된다

    body = client.get(f"/api/organizations/{org}").json()
    note = body["document_registry_note"]
    assert body["document_count"] == 0  # 목록은 비었지만
    assert note and "읽지 못했습니다" in note and "격리" in note
    assert "자료가 없는 것이 아니라" in note
