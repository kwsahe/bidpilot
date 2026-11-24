"""D. 레거시 마이그레이션 — dry-run 은 쓰지 않음, 원본 보존, 멱등, 집계 유지, organization_id 부여, 레거시 읽기 호환.

실제 data/company 가 아니라 tmp 에 작은 레거시 폴더를 만들어 검증한다 (conftest 가 경로를 tmp 로 돌린다).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.core import org_storage, storage
from app.services import company_service as cs
from app.services import organization_service

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "migrate_company_to_organizations.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_company_to_organizations", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["migrate_company_to_organizations"] = module
    spec.loader.exec_module(module)
    return module


def _make_legacy(root: Path) -> None:
    """documents 2 · candidates 3(승인 2) · uploads 2 · index chunks 2 · ledger rows 2."""
    docs = []
    for n, (doc_id, status) in enumerate((("CD-aaaa1111-001", "indexed"), ("CD-bbbb2222-002", "review")), start=1):
        docs.append(
            {
                "id": doc_id,
                "file_name": f"doc{n}.md",
                "title": f"doc{n}",
                "doc_type": "수행실적",
                "status": status,
                "size_bytes": 10,
                "sha256": hashlib.sha256(f"doc{n}".encode()).hexdigest(),
                "uploaded_at": "2026-09-07T00:00:00+00:00",
                "candidate_count": 2 if n == 1 else 1,
                "approved_chunk_count": 2 if n == 1 else 0,
                "indexed_chunk_count": 2 if n == 1 else 0,
                "metadata": {"source_kind": "upload", "location": f"doc{n}.md", "data_class": "real", "approved": n == 1, "scope": "internal", "retired": False},
            }
        )
        (root / "uploads").mkdir(parents=True, exist_ok=True)
        (root / "uploads" / f"{doc_id}.md").write_text(f"# doc{n}\n\n본문 {n}\n", encoding="utf-8")
    storage.write_json_atomic(root / "documents.json", {"documents": docs})
    storage.write_json_atomic(root / "candidates" / "CD-aaaa1111-001.json", {"document_id": "CD-aaaa1111-001", "candidates": [
        {"id": "CD-aaaa1111-001:001", "document_id": "CD-aaaa1111-001", "page": 1, "source_text": "x" * 30, "approved": True},
        {"id": "CD-aaaa1111-001:002", "document_id": "CD-aaaa1111-001", "page": 1, "source_text": "y" * 30, "approved": True},
    ]})
    storage.write_json_atomic(root / "candidates" / "CD-bbbb2222-002.json", {"document_id": "CD-bbbb2222-002", "candidates": [
        {"id": "CD-bbbb2222-002:001", "document_id": "CD-bbbb2222-002", "page": 1, "source_text": "z" * 30, "approved": None},
    ]})
    storage.write_json_atomic(root / "index" / "company_index.json", {"chunk_count": 2, "document_count": 1, "chunks": [
        {"evidence_id": "CD-aaaa1111-001:001", "document_id": "CD-aaaa1111-001", "document_name": "doc1", "doc_type": "수행실적", "page": 1, "source_text": "x" * 30, "embedding": [1.0, 0.0], "data_class": "real"},
        {"evidence_id": "CD-aaaa1111-001:002", "document_id": "CD-aaaa1111-001", "document_name": "doc1", "doc_type": "수행실적", "page": 1, "source_text": "y" * 30, "embedding": [0.0, 1.0], "data_class": "real"},
    ]})
    storage.write_json_atomic(root / "performance_ledger.json", {"ledger_date": "2026-07-28", "rows": [{"seq": 1, "eligible": True}, {"seq": 2, "eligible": False}]})
    (root / "ledger_docs").mkdir(parents=True, exist_ok=True)
    (root / "ledger_docs" / "ledger_a.md").write_text("# a\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture()
def legacy(tmp_path: Path) -> Path:
    root = org_storage.legacy_company_dir()
    _make_legacy(root)
    return root


def test_legacy_data_is_readable_before_migration(legacy: Path) -> None:
    """마이그레이션 전에도 기본 조직은 레거시 폴더를 읽는다 (organization_id 없는 데이터 호환)."""
    org = org_storage.DEFAULT_ORGANIZATION_ID
    listing = cs.list_documents(org)
    assert [d.id for d in listing.documents] == ["CD-aaaa1111-001", "CD-bbbb2222-002"]
    assert all(d.organization_id == org for d in listing.documents)
    assert listing.index.company_index["chunk_count"] == 2
    detail = cs.get_document(org, "CD-aaaa1111-001")
    assert len(detail.candidates) == 2 and all(c.organization_id == org for c in detail.candidates)
    # 다른 조직은 레거시를 보지 않는다
    organization_service.create_organization(__import__("app.schemas.organization", fromlist=["OrganizationCreateRequest"]).OrganizationCreateRequest(display_name="B", organization_id="org-demo-second", data_class="synthetic", created_by="k"))
    assert cs.list_documents("org-demo-second").documents == []


def test_dry_run_writes_nothing_and_apply_preserves_originals(legacy: Path) -> None:
    script = _load_script()
    before = _snapshot(legacy)
    target = org_storage.storage_for(org_storage.DEFAULT_ORGANIZATION_ID)

    assert script.run(apply=False, org_id=org_storage.DEFAULT_ORGANIZATION_ID, verify_only=False) == 0
    assert not target.documents_file.exists() and not target.index_file.exists()
    assert _snapshot(legacy) == before

    assert script.run(apply=True, org_id=org_storage.DEFAULT_ORGANIZATION_ID, verify_only=False) == 0
    assert _snapshot(legacy) == before  # 원본 그대로
    assert target.documents_file.exists() and target.index_file.exists() and target.ledger_file.exists()
    assert script.legacy_counts(legacy) == script.target_counts(target)
    assert script.target_counts(target)["documents"] == 2 and script.target_counts(target)["index_chunks"] == 2

    # organization_id 가 붙었다
    docs = json.loads(target.documents_file.read_text(encoding="utf-8"))
    assert docs["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID
    assert all(d["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID for d in docs["documents"])
    index = json.loads(target.index_file.read_text(encoding="utf-8"))
    assert all(c["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID for c in index["chunks"])
    cand = json.loads(target.candidate_path("CD-aaaa1111-001").read_text(encoding="utf-8"))
    assert cand["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID and all(c["organization_id"] == org_storage.DEFAULT_ORGANIZATION_ID for c in cand["candidates"])
    # 문서 id 유지
    assert [d["id"] for d in docs["documents"]] == ["CD-aaaa1111-001", "CD-bbbb2222-002"]
    # 등록부에 마이그레이션 표시
    assert organization_service.get_organization(org_storage.DEFAULT_ORGANIZATION_ID).migrated_from_legacy is True

    # 반복 실행해도 중복·변경 없음 (멱등)
    after_first = _snapshot(target.root)
    assert script.run(apply=True, org_id=org_storage.DEFAULT_ORGANIZATION_ID, verify_only=False) == 0
    assert _snapshot(target.root) == after_first
    assert script.run(apply=False, org_id=org_storage.DEFAULT_ORGANIZATION_ID, verify_only=True) == 0

    # 마이그레이션 후 서비스는 조직 폴더를 읽는다 (레거시와 같은 내용)
    listing = cs.list_documents(org_storage.DEFAULT_ORGANIZATION_ID)
    assert [d.id for d in listing.documents] == ["CD-aaaa1111-001", "CD-bbbb2222-002"]
    assert cs.active_document_ids(org_storage.DEFAULT_ORGANIZATION_ID) == {"CD-aaaa1111-001"}


def test_conflicting_target_file_stops_without_touching_originals(legacy: Path) -> None:
    script = _load_script()
    target = org_storage.storage_for(org_storage.DEFAULT_ORGANIZATION_ID)
    target.uploads_dir.mkdir(parents=True, exist_ok=True)
    (target.uploads_dir / "CD-aaaa1111-001.md").write_text("다른 내용", encoding="utf-8")
    before = _snapshot(legacy)
    assert script.run(apply=True, org_id=org_storage.DEFAULT_ORGANIZATION_ID, verify_only=False) == 3
    assert _snapshot(legacy) == before
    assert not target.documents_file.exists()


# ---------------------------------------------------------------------------
# 안정 ID 규칙이 바뀌었을 때 «구성이 그대로인 초안»을 이전 기준으로 밀지 않는다
# ---------------------------------------------------------------------------

REQ_SET_SCRIPT = REPO_ROOT / "scripts" / "migrate_requirement_sets.py"


def _load_req_set_script():
    spec = importlib.util.spec_from_file_location("migrate_requirement_sets", REQ_SET_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["migrate_requirement_sets"] = module
    spec.loader.exec_module(module)
    return module


def test_옛_규칙_집합해시를_다시_계산해_같은_구성임을_증명한다() -> None:
    """2026-09-14 실측 사고의 회귀 테스트.

    안정 ID 재료에서 첨부 파일명을 빼자 «요구사항이 한 건도 바뀌지 않은» 공고의
    집합 해시까지 갈렸다. 그 결과 g2b-R26BK01718694-000 은 전체 60 · 필수 57 그대로인데
    제안서가 「이전 기준」으로 밀렸고, 화면은 「필수 요구사항이 57건에서 57건으로
    변경되었습니다」라고 말했으며 제출 전 점검은 409 로 막혔다.

    옛 규칙 해시를 다시 계산할 수 있으면 «구성은 같고 규칙만 바뀐 것»이 증명된다.
    """
    from app.services import requirement_set

    module = _load_req_set_script()

    payload = {
        "procurement_id": "g2b-TEST9999-000",
        "document": "1_2. 제안요청서.hwp",
        "requirements": [
            {"requirement_id": "REQ-001", "source_text": "교육은 총 20회 이상 운영한다", "requirement_type": "mandatory"},
            {"requirement_id": "REQ-002", "source_text": "만족도 조사를 실시한다", "requirement_type": "mandatory"},
        ],
    }

    legacy = module.legacy_set_hash(payload)
    assert legacy

    # 새 규칙으로 신원을 찍고 집합 해시를 낸다 — 구성은 하나도 건드리지 않았다.
    requirement_set.assign_identity(
        payload["requirements"], procurement_id=payload["procurement_id"], document=payload["document"]
    )
    fresh = requirement_set.set_hash(payload["requirements"])

    assert legacy != fresh, "규칙이 바뀌었으므로 표기는 달라야 한다"
    # 그리고 옛 값은 «다시 계산할 수 있다» — 그래서 같은 구성임이 증명된다.
    assert module.legacy_set_hash(payload) == legacy

    # 구성이 실제로 달라지면 옛 해시도 달라진다 (증명이 아무 때나 성립하면 안 된다).
    changed = json.loads(json.dumps(payload))
    changed["requirements"].append(
        {"requirement_id": "REQ-003", "source_text": "새로 생긴 요구사항", "requirement_type": "mandatory"}
    )
    for req in changed["requirements"]:
        req.pop("stable_id", None)
    assert module.legacy_set_hash(changed) != legacy
