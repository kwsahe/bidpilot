"""기업마당 **공고문을 내려받아 텍스트를 뽑는다** (0924.md §4-A-1·2 · ISSUE-096).

## 무엇을 하는가

    받아 둔 기업마당 목록 → 관련 · 마감 전 · 검토 우선순위 상위 N건
                          → fileDown.do 로 공고문 원본
                          → PDF/HWP/HWPX 텍스트 추출
                          → data/private/bizinfo_docs/ (비공개, Git 제외)

## 왜 필요한가

앱은 기업마당을 요약문·해시태그로만 판정했다. 본사 소재·조직 형태·고용 인원·창업 연차·
매출·선행사업·역할·정부지원 비율·제외 조항은 **공고문에만** 있다
(`docs/reports/2026-09-24_bizinfo_candidates.md` §3).

## 범위

**1,605건을 한 번에 받지 않는다.** 남의 파일 서버다.

- 기본은 **관련 있고 마감 전인 것 중 검토 우선순위 상위 150건**.
- `--reference` 를 주면 기준 답안 CSV 26건을 함께 받는다(이미 받은 것은 건너뛴다).
- 이미 받은 공고는 다시 받지 않는다 — 공고당 한 번이다. 다시 받으려면 `--force`.
- 한 번에 하나씩, 순서대로 받는다. 동시에 여러 개를 당기지 않는다.

이것은 OpenAPI 가 아니라 **파일 서버** 호출이라 기업마당 API 한도와 무관하다. 나라장터는
건드리지 않는다 — 이 스크립트는 `G2B_LIVE_FETCH=0` 으로 돈다.

## 쓰는 법

```
backend/.venv/Scripts/python.exe scripts/fetch_bizinfo_docs.py --limit 150 --reference
backend/.venv/Scripts/python.exe scripts/fetch_bizinfo_docs.py --dry-run
backend/.venv/Scripts/python.exe scripts/fetch_bizinfo_docs.py --annex PBLN_000000000126482
```

`--annex <공고 id>` (30차 §3-A) — 그 공고의 **과제소개서([별첨 1]) 첨부 한 개만** 받는다(`{id}.annex1.*`).
화면의 「과제소개서 받기」 단추와 같은 일이다. 자동 · 일괄로 받지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# 바깥을 부르지 않는다 — 목록은 저장된 캐시에서 읽는다 (0921 §3-10′).
os.environ.setdefault("G2B_LIVE_FETCH", "0")
os.environ.setdefault("BIZINFO_LIVE_FETCH", "0")

from app.schemas.organization import AnalysisContext  # noqa: E402
from app.services import bizinfo_document_store as store  # noqa: E402
from app.services import bizinfo_service, opportunity_service  # noqa: E402

REFERENCE_CSV = ROOT / "docs" / "reports" / "2026-09-24_bizinfo_candidates.csv"
DEFAULT_LIMIT = 150
ORG = "org-sample"


def _cached_items() -> dict[str, dict]:
    """받아 둔 기업마당 목록의 **원본 항목**. 공고문 주소가 여기 있다."""
    from app.core import storage

    payload = storage.read_json(bizinfo_service.CACHE_FILE, default=None)
    if not isinstance(payload, dict):
        return {}
    return {str(i.get("pblancId")): i for i in payload.get("items") or [] if isinstance(i, dict)}


async def _wanted_ids(limit: int, *, organization_id: str) -> list[str]:
    """관련 있고 마감 전인 것 중 **검토 우선순위 상위 N건**의 공고 id."""
    context = AnalysisContext(organization_id=organization_id, evidence_scope="internal")
    listing = await opportunity_service.list_opportunities(
        context=context, source="bizinfo", days=30, sort="priority", limit=200
    )
    out: list[str] = []
    for item in listing.items:
        if item.closed or item.relevance_note:
            continue
        out.append(item.id.removeprefix("bizinfo-"))
        if len(out) >= limit:
            break
    return out


def _reference_ids() -> list[str]:
    if not REFERENCE_CSV.exists():
        return []
    with REFERENCE_CSV.open(encoding="utf-8-sig") as handle:
        return [row["ID"].strip() for row in csv.DictReader(handle) if row.get("ID")]


async def main() -> int:
    parser = argparse.ArgumentParser(description="기업마당 공고문 내려받기 (0924 §4-A-1·2)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"상위 몇 건까지 (기본 {DEFAULT_LIMIT})")
    parser.add_argument("--reference", action="store_true", help="기준 답안 CSV 26건을 함께 받는다")
    parser.add_argument("--force", action="store_true", help="이미 받은 것도 다시 받는다")
    parser.add_argument("--dry-run", action="store_true", help="무엇을 받을지만 보여 준다")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로")
    parser.add_argument("--annex", metavar="공고ID", help="그 공고의 과제소개서 첨부 한 개만 받는다(30차)")
    args = parser.parse_args()

    items = _cached_items()
    if not items:
        print(f"받아 둔 기업마당 목록이 없습니다: {bizinfo_service.CACHE_FILE}")
        return 2

    if args.annex:
        program_id = args.annex.removeprefix("bizinfo-")
        item = items.get(program_id)
        attachment = bizinfo_service.annex_attachment(item) if item else None
        if attachment is None:
            print(f"{program_id}: 과제소개서 첨부가 목록 항목에 없습니다")
            return 2
        if args.dry_run:
            print(f"{program_id}: 받을 것 — {attachment.name}")
            return 0
        record = await store.fetch_annex(item, attachment.index)
        print(f"[{'본문' if record.status == 'text' else '실패'}] {program_id} · {record.file_name} · {record.bytes:,}바이트 · "
              f"{record.pages}쪽 · {record.chars:,}자" + (f" — {record.note}" if record.note else ""))
        return 0 if record.status == "text" else 1

    wanted = await _wanted_ids(args.limit, organization_id=ORG)
    if args.reference:
        for program_id in _reference_ids():
            if program_id not in wanted:
                wanted.append(program_id)

    known = set() if args.force else store.known_ids()
    todo = [items[pid] for pid in wanted if pid in items and pid not in known]

    print(f"목록 {len(items)}건 · 대상 {len(wanted)}건 · 이미 받음 {len(wanted) - len(todo)}건 · 받을 것 {len(todo)}건")
    if args.dry_run:
        for item in todo[:20]:
            print(f"  {item['pblancId']}  {str(item.get('pblancNm'))[:52]}")
        if len(todo) > 20:
            print(f"  … 그리고 {len(todo) - 20}건")
        return 0

    index, fresh = await store.fetch_many(todo, force=args.force)
    counts = index.counts()
    if args.json:
        print(json.dumps({"fetched": len(fresh), "counts": counts}, ensure_ascii=False, indent=1))
        return 0

    for record in fresh:
        mark = {"text": "본문", "image": "이미지", "failed": "실패"}[record.status]
        print(
            f"  [{mark}] {record.program_id} · {record.suffix or '?'} · "
            f"{record.bytes:,}바이트 · {record.pages}쪽 · {record.chars:,}자"
            + (f" — {record.note}" if record.note else "")
        )
    print(
        f"\n이번에 받은 것 {len(fresh)}건 · 저장소 전체 {counts['total']}건"
        f" (본문 {counts['text']} · 이미지 {counts['image']} · 실패 {counts['failed']})"
    )
    print(f"저장 위치: {store.DOCS_DIR} (비공개 · Git 제외)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
