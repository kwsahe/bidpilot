"""레거시 단일 회사 저장공간(data/company/) → 조직별 저장공간(data/private/organizations/org-sample/) 마이그레이션.

    backend/.venv/Scripts/python.exe scripts/migrate_company_to_organizations.py                       # dry-run (기본)
    backend/.venv/Scripts/python.exe scripts/migrate_company_to_organizations.py --dry-run
    backend/.venv/Scripts/python.exe scripts/migrate_company_to_organizations.py --apply --organization-id org-sample
    backend/.venv/Scripts/python.exe scripts/migrate_company_to_organizations.py --verify              # 전후 비교만

규칙
- **복사 + 검증** 방식. 원본(data/company/)은 절대 삭제·수정하지 않는다. 롤백 = 조직 폴더를 지우면 끝 (원본 그대로).
- 멱등: 이미 옮겨진 파일은 checksum 이 같으면 건너뛰고, 다르면 **중단**한다 (덮어쓰지 않는다).
- 문서 id 유지. 문서·후보·인덱스 문단·원장에 organization_id 를 추가한다.
- 전후 파일 수·문서 수·후보 수·승인 수·인덱스 문단 수를 비교하고, 어긋나면 실패로 끝낸다 (원본은 건드리지 않았다).
- 로그에 문단 원문·개인정보를 찍지 않는다 (파일명·건수·checksum 만).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core import org_storage, storage  # noqa: E402

DEFAULT_ORG = org_storage.DEFAULT_ORGANIZATION_ID


class MigrationError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    """저장소 안이면 상대 경로, 아니면(테스트 tmp) 절대 경로."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def legacy_counts(legacy: Path) -> dict[str, int]:
    registry = _json(legacy / "documents.json") or {}
    documents = registry.get("documents", []) if isinstance(registry, dict) else []
    candidates = 0
    approved = 0
    for path in sorted((legacy / "candidates").glob("*.json")) if (legacy / "candidates").exists() else []:
        payload = _json(path) or {}
        items = payload.get("candidates", []) if isinstance(payload, dict) else []
        candidates += len(items)
        approved += sum(1 for c in items if c.get("approved") is True)
    index = _json(legacy / "index" / "company_index.json") or {}
    chunks = index.get("chunks", []) if isinstance(index, dict) else []
    ledger = _json(legacy / "performance_ledger.json") or {}
    return {
        "documents": len(documents),
        "approved_documents": sum(1 for d in documents if d.get("status") in ("approved", "indexed")),
        "candidate_files": len(list((legacy / "candidates").glob("*.json"))) if (legacy / "candidates").exists() else 0,
        "candidates": candidates,
        "approved_candidates": approved,
        "uploads": len([p for p in (legacy / "uploads").iterdir() if p.is_file()]) if (legacy / "uploads").exists() else 0,
        "ledger_docs": len(list((legacy / "ledger_docs").glob("*.md"))) if (legacy / "ledger_docs").exists() else 0,
        "index_chunks": len(chunks),
        "ledger_rows": len(ledger.get("rows", [])) if isinstance(ledger, dict) else 0,
    }


def target_counts(store: org_storage.OrganizationStorage) -> dict[str, int]:
    return legacy_counts(store.root)  # 같은 구조라 같은 계산을 쓴다


def _stamp_org(payload: dict[str, Any], org_id: str) -> None:
    payload["organization_id"] = org_id
    payload["migrated_from"] = "data/company"
    payload["migrated_at"] = datetime.now(timezone.utc).isoformat()


def plan(legacy: Path, store: org_storage.OrganizationStorage) -> list[dict[str, Any]]:
    """옮길 파일 목록과 각 파일의 처리(copy / transform / skip-same / conflict)."""
    items: list[dict[str, Any]] = []

    def add(src: Path, dst: Path, mode: str) -> None:
        state = "copy"
        if dst.exists():
            if mode == "copy" and sha256_of(src) == sha256_of(dst):
                state = "skip-same"
            elif mode == "transform":
                # 변환 파일은 organization_id 가 찍혀 있으면 이미 옮긴 것으로 본다.
                existing = _json(dst)
                state = "skip-same" if isinstance(existing, dict) and existing.get("organization_id") == store.organization_id else "conflict"
            else:
                state = "conflict"
        items.append({"src": src, "dst": dst, "mode": mode, "state": state})

    if (legacy / "documents.json").exists():
        add(legacy / "documents.json", store.documents_file, "transform")
    if (legacy / "company_profile.json").exists():
        add(legacy / "company_profile.json", store.profile_file, "transform")
    if (legacy / "performance_ledger.json").exists():
        add(legacy / "performance_ledger.json", store.ledger_file, "transform")
    if (legacy / "index" / "company_index.json").exists():
        add(legacy / "index" / "company_index.json", store.index_file, "transform")
    for sub, dst_dir, mode in (("candidates", store.candidates_dir, "transform"), ("uploads", store.uploads_dir, "copy"), ("ledger_docs", store.ledger_docs_dir, "copy")):
        src_dir = legacy / sub
        if not src_dir.exists():
            continue
        for src in sorted(p for p in src_dir.iterdir() if p.is_file() and not p.name.endswith(".tmp")):
            add(src, dst_dir / src.name, mode)
    return items


def transform(src: Path, dst: Path, org_id: str) -> None:
    payload = _json(src)
    if not isinstance(payload, dict):
        raise MigrationError(f"JSON 이 아니거나 비어 있음: {src.name}")
    if src.name == "documents.json":
        for doc in payload.get("documents", []):
            doc.setdefault("organization_id", org_id)
    elif src.parent.name == "candidates":
        for c in payload.get("candidates", []):
            c.setdefault("organization_id", org_id)
    elif src.name == "company_index.json":
        for c in payload.get("chunks", []):
            c.setdefault("organization_id", org_id)
    _stamp_org(payload, org_id)
    storage.write_json_atomic(dst, payload)


def run(*, apply: bool, org_id: str, verify_only: bool) -> int:
    legacy = org_storage.legacy_company_dir()
    store = org_storage.storage_for(org_id)
    if not legacy.exists():
        print(f"레거시 폴더가 없습니다: {legacy}")
        return 1
    before = legacy_counts(legacy)
    print(f"원본: {legacy}")
    print(f"대상: {store.root}")
    print("원본 집계:", json.dumps(before, ensure_ascii=False))

    if verify_only:
        after = target_counts(store) if store.exists() else {}
        print("대상 집계:", json.dumps(after, ensure_ascii=False))
        ok = after == before
        print("검증:", "일치" if ok else "불일치")
        return 0 if ok else 2

    items = plan(legacy, store)
    conflicts = [i for i in items if i["state"] == "conflict"]
    todo = [i for i in items if i["state"] == "copy"]
    print(f"계획: 복사/변환 {len(todo)}건 · 이미 동일 {len(items) - len(todo) - len(conflicts)}건 · 충돌 {len(conflicts)}건")
    for item in items:
        print(f"  [{item['state']:>9}] {item['mode']:<9} {_rel(item['src'])} → {_rel(item['dst'])}")
    if conflicts:
        print("충돌: 대상에 내용이 다른 파일이 이미 있습니다. 덮어쓰지 않고 중단합니다. 대상 파일을 확인하세요.")
        return 3
    if not apply:
        print("\ndry-run — 파일을 쓰지 않았습니다. 반영하려면 --apply 를 붙이세요.")
        return 0

    # 적용: 등록부 항목 보장 → 파일 복사/변환 → 검증
    from app.services import organization_service

    organization_service.ensure_default_organization()
    if org_id != DEFAULT_ORG:
        organization_service.get_organization(org_id)
    store.root.mkdir(parents=True, exist_ok=True)
    for item in todo:
        item["dst"].parent.mkdir(parents=True, exist_ok=True)
        if item["mode"] == "copy":
            shutil.copy2(item["src"], item["dst"])
        else:
            transform(item["src"], item["dst"], org_id)
    after = target_counts(store)
    print("대상 집계:", json.dumps(after, ensure_ascii=False))
    mismatch = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
    if mismatch:
        print("검증 실패 — 전후 집계가 다릅니다:", json.dumps(mismatch, ensure_ascii=False))
        print("원본은 건드리지 않았습니다. 대상 폴더를 확인하거나 지우고 다시 실행하세요.")
        return 4
    # 복사 파일 checksum 재확인
    for item in items:
        if item["mode"] == "copy" and sha256_of(item["src"]) != sha256_of(item["dst"]):
            print(f"checksum 불일치: {item['dst'].name}")
            return 4
    organization_service.mark_migrated(org_id, updated_by="migrate_company_to_organizations.py")
    print(f"\n완료 — 원본 보존, 대상 organization_id={org_id}. 롤백: {store.root} 폴더를 삭제하면 레거시 읽기 대체로 돌아간다.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--organization-id", default=DEFAULT_ORG)
    parser.add_argument("--dry-run", action="store_true", help="계획만 출력 (기본)")
    parser.add_argument("--apply", action="store_true", help="실제로 복사·변환한다")
    parser.add_argument("--verify", action="store_true", help="전후 집계 비교만")
    args = parser.parse_args()
    org_id = org_storage.validate_organization_id(args.organization_id)
    raise SystemExit(run(apply=args.apply and not args.dry_run, org_id=org_id, verify_only=args.verify))


if __name__ == "__main__":
    main()
