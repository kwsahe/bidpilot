"""실적 원장(xlsx) → 근거 문서 + 구조화 JSON, 선택적으로 회사자료 파이프라인 등록·승인.

    backend/.venv/Scripts/python.exe scripts/import_performance_ledger.py                     # dry-run: 선별 결과만 출력
    backend/.venv/Scripts/python.exe scripts/import_performance_ledger.py --write             # md·json 생성 (data/company/)
    backend/.venv/Scripts/python.exe scripts/import_performance_ledger.py --write --register --reviewer "홍길동"
    backend/.venv/Scripts/python.exe scripts/import_performance_ledger.py --write --register --approve --reviewer "홍길동"

- 채택 규칙은 원장의 「외부 성공연혁 = 가능」이다. 규칙 본체는 backend/app/services/performance_ledger.py.
- --register: 생성한 md를 회사자료 등록부에 올려 텍스트 추출·후보 문단까지 만든다 (상태 「검토 필요」).
- --approve: 후보 문단을 모두 채택하고 근거로 등록한다(상태 「승인」). 임베딩 키가 있으면 색인까지 갱신된다.
  원장이 이미 담당자 검토를 거친 자료라는 전제이며, 승인자 이름(--reviewer)이 기록에 남는다.
- 산출물은 전부 조직 저장공간 data/private/organizations/{org}/ 아래(gitignore). 원장 원본은 docs/SampleEdu/ (gitignore).
- 화면에서 하려면 회사정보·수행근거 → 실적 원장 가져오기(매핑 확인 → preview → 승인 등록).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core import org_storage  # noqa: E402
from app.services import performance_ledger as pl  # noqa: E402

DEFAULT_XLSX = REPO_ROOT / "docs" / "SampleEdu" / "sample_ledger_20260728.xlsx"
DEFAULT_ORG = org_storage.DEFAULT_ORGANIZATION_ID
# 산출물은 조직 저장공간(data/private/organizations/{org}/, gitignore)에만 쓴다. 레거시 data/company/ 는 더 이상 쓰지 않는다.


def _print_summary(rows: list[pl.LedgerRow]) -> None:
    eligible = [r for r in rows if r.eligible]
    excluded = [r for r in rows if not r.eligible]
    print(f"원장 행 {len(rows)}건 → 근거 채택 {len(eligible)}건 · 제외 {len(excluded)}건")
    by_group: dict[str, int] = {}
    for row in eligible:
        by_group[pl.group_key(row)] = by_group.get(pl.group_key(row), 0) + 1
    for group, count in by_group.items():
        print(f"  채택 · {group}: {count}건")
    print("제외 사유:")
    for row in excluded:
        print(f"  #{row.seq:>2} [{row.status}] {row.title[:40]} — {row.exclusion_reason}")
    warned = [r for r in eligible if r.warnings]
    if warned:
        print("채택했지만 주의:")
        for row in warned:
            print(f"  #{row.seq:>2} {row.title[:40]} — {'; '.join(row.warnings)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--sheet", default=pl.MASTER_SHEET)
    parser.add_argument("--organization-id", default=DEFAULT_ORG, help="산출물을 둘 조직 (기본 org-sample)")
    parser.add_argument("--out-dir", type=Path, default=None, help="기본: 조직 폴더 ledger_docs/")
    parser.add_argument("--json", type=Path, default=None, help="기본: 조직 폴더 performance_ledger.json")
    parser.add_argument("--write", action="store_true", help="md·json을 파일로 쓴다 (기본은 dry-run)")
    parser.add_argument("--register", action="store_true", help="생성한 md를 회사자료 등록부에 올린다")
    parser.add_argument("--approve", action="store_true", help="후보 문단을 모두 채택하고 근거로 등록(승인)한다")
    parser.add_argument("--reviewer", default="", help="등록·승인자 이름 (--register/--approve에 필수)")
    args = parser.parse_args()

    if not args.xlsx.exists():
        raise SystemExit(f"원장 파일이 없습니다: {args.xlsx}")
    if (args.register or args.approve) and not args.reviewer.strip():
        raise SystemExit("--register/--approve 에는 --reviewer 이름이 필요합니다 (기록에 남습니다).")

    org_id = org_storage.validate_organization_id(args.organization_id)
    store = org_storage.storage_for(org_id)
    out_dir = args.out_dir or store.ledger_docs_dir
    json_path = args.json or store.ledger_file
    rows = pl.read_ledger(args.xlsx, sheet=args.sheet)
    ledger_date = pl.ledger_date_from_name(args.xlsx.name)
    _print_summary(rows)

    documents = pl.build_documents(rows, source_name=args.xlsx.name, ledger_date=ledger_date, sheet=args.sheet)
    if not args.write:
        print(f"\ndry-run — 생성될 문서 {len(documents)}개: {', '.join(documents)}")
        print("반영하려면 --write 를 붙이세요.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, body in documents.items():
        (out_dir / name).write_text(body, encoding="utf-8")
    payload = pl.ledger_payload(rows, source_name=args.xlsx.name, ledger_date=ledger_date, sheet=args.sheet)
    payload["organization_id"] = org_id
    pl.dump_json(payload, json_path)
    print(f"\n생성: {out_dir.relative_to(REPO_ROOT)} ({len(documents)}개 md) · {json_path.relative_to(REPO_ROOT)} · organization_id={org_id}")

    if not args.register:
        return

    from app.schemas.company import CandidateReview, CandidateReviewRequest, DocumentApproveRequest
    from app.services import company_service as cs

    reviewer = args.reviewer.strip()
    from app.services import organization_service

    organization_service.ensure_default_organization()
    print(f"\n회사자료 등록부에 올립니다 (내부 전용 · organization_id={org_id}):")
    for name, body in documents.items():
        try:
            detail = cs.register_upload(
                org_id,
                file_name=name,
                payload=body.encode("utf-8"),
                doc_type="수행실적",
                uploaded_by=reviewer,
                data_class="real",
            )
        except cs.DuplicateDocumentError as exc:
            print(f"  [중복] {name} — 이미 등록됨 ({exc.existing_id}); 건너뜀")
            continue
        print(f"  [{detail.status}] {name} → {detail.id} · 후보 {detail.candidate_count}건")
        if detail.status != "review" or not args.approve:
            continue
        candidates = [c for c in detail.candidates if not c.is_gap]
        cs.review_candidates(
            org_id,
            detail.id,
            CandidateReviewRequest(reviewer=reviewer, reviews=[CandidateReview(candidate_id=c.id, approved=True) for c in candidates]),
        )
        approved = cs.approve_document(
            org_id,
            detail.id,
            DocumentApproveRequest(
                reviewer=reviewer,
                data_class="real",
                scope="internal",
                note=f"실적 원장 일괄 등록 — 「외부 성공연혁 = 가능」 행만 ({ledger_date} 원장). 사용 전 증빙 대조.",
            ),
        )
        print(f"    승인 → 상태 {approved.status} · 채택 {approved.approved_chunk_count}건 · 색인 {approved.indexed_chunk_count}건")

    status = cs.index_status(org_id)
    print(f"\n색인 상태: 임베딩 {'가능' if status.embedding_available else '키 없음'} · 회사 인덱스 {status.company_index['chunk_count']}문단 · 색인 대기 {status.pending_documents}건")
    print(status.note)


if __name__ == "__main__":
    main()
