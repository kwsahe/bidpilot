"""나라장터 **자격 정보 한 번 백필** — 하루 창으로 받아 저장소에 쌓는다 (0922.md §4-A-3).

## 무엇을 하나

1. 이미 받아 둔 공고 캐시(`g2b_cache.json`)에서 **후보 공고의 게시일**을 모은다.
2. 저장소에 없는 날만 하루 창으로 받아 `qualifications/<날짜>.json` 에 저장한다.
   (두 오퍼레이션 × 2페이지 = 하루 4회. 18일이면 72회.)
3. 캐시에 남아 있는 **원본 item** 을 새 자격 값으로 다시 매핑해 캐시를 갱신한다.

## 목록은 다시 부르지 않는다

공고 목록을 새로 받으면 건수·순위가 바뀌어 큐시트와 리허설 캡처가 통째로 어긋난다
(ISSUE-062). 캐시에는 113개 필드짜리 원본 item 이 그대로 남아 있으므로, **목록 호출 없이**
자격 값만 붙여 다시 매핑할 수 있다. 그래서 이 스크립트의 실호출은 자격 조회뿐이다.

## 실행

    backend/.venv/Scripts/python.exe scripts/backfill_qualifications.py [--dry-run]

`--dry-run` 은 「몇 날을 몇 번 불러야 하는가」만 적고 네트워크를 부르지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# 이 스크립트는 **자격 조회를 실제로 부르는 유일한 자리**다(0922 §3-10′).
# 설정 기본값은 꺼짐이므로(ISSUE-120) 여는 것은 아래 한 줄뿐이다. 다른 스크립트는
# 아무것도 세우지 않고 기본값(꺼짐)에 기댄다 — 그래야 실수로 열리지 않는다.
# `setdefault` 인 이유: 셸이 0 으로 고정해 두었으면 그 뜻을 이기지 않는다.
os.environ.setdefault("G2B_LIVE_FETCH", "1")
os.environ.setdefault("BIZINFO_LIVE_FETCH", "0")  # 기업마당은 이 스크립트의 일이 아니다
print(
    "실호출: 이 스크립트가 나라장터 자격 조회만 엽니다 "
    f"(G2B_LIVE_FETCH={os.environ.get('G2B_LIVE_FETCH')}) — 설정 기본값은 꺼짐",
)

from app.core import storage  # noqa: E402
from app.services import (  # noqa: E402
    g2b_mapper,
    procurement_service,
    qualification_store,
)

CACHE = procurement_service.cache_read_path()  # 살아 있는 저장본(Git 밖) · 없으면 기준본(33차 · 안 1)


def cached_items() -> list[dict]:
    """캐시에 남아 있는 원본 API item 들. 목록을 다시 부르지 않기 위한 것이다."""
    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    items = []
    for entry in payload.get("notices", []):
        raw = (entry.get("notice") or {}).get("raw_data") or {}
        item = raw.get("item")
        if isinstance(item, dict) and item:
            items.append(item)
    return items


async def main() -> int:
    parser = argparse.ArgumentParser(description="자격 정보 하루 창 백필 (0922 §4-A-3)")
    parser.add_argument("--dry-run", action="store_true", help="네트워크를 부르지 않고 계획만 적는다")
    args = parser.parse_args()

    items = cached_items()
    days = procurement_service._publish_days(items)
    known = qualification_store.settled_days(days)  # 그날 안에 받은 반쪽 하루치는 「받은 날」이 아니다(33차)
    missing = [day for day in days if day not in known]

    print(f"캐시 공고 {len(items)}건 · 게시일 {len(days)}일 · 이미 받은 날 {len(days) - len(missing)}일")
    print(f"받아야 할 날 {len(missing)}일 → 예상 호출 {len(missing) * 4}회 (두 오퍼레이션 × 2페이지)")
    if args.dry_run:
        for day in missing:
            print("  -", day)
        return 0

    started = datetime.now(timezone.utc)
    calls, fetched, note = await procurement_service._ensure_qualification_days(days)
    print(f"실호출 {calls}회 · 새로 받은 날 {fetched}일 · 시각 {started.isoformat()}")
    if note:
        print("사유:", note)

    # 캐시의 원본 item 을 새 자격 값으로 다시 매핑한다. **목록은 부르지 않는다.**
    coverage = qualification_store.coverage_for(days)
    notices = g2b_mapper.map_notices(items, qualifications=coverage)
    latest, _superseded = procurement_service.split_revisions(notices)
    views = [
        procurement_service.NoticeView(notice=n, match=m)
        for n, m in procurement_service.filter_candidates(latest, include_low=True)
    ]
    views = procurement_service.rank_notices(procurement_service._merge_pinned(views))

    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    procurement_service.save_cache(
        views,
        int(payload.get("total_fetched") or len(notices)),
        datetime.fromisoformat(payload["fetched_at"]),
        days=int(payload.get("days") or 30),
        collected_by=str(payload.get("collected_by") or ""),
        collect_calls=int(payload.get("collect_calls") or 0),
    )

    checked = sum(1 for v in views if (v.notice.raw_data or {}).get("qualification_checked_at"))
    limited = sum(1 for v in views if (v.notice.raw_data or {}).get("license_limits"))
    regioned = sum(1 for v in views if (v.notice.raw_data or {}).get("allowed_regions"))
    codes: Counter[str] = Counter()
    for view in views:
        for row in (view.notice.raw_data or {}).get("license_limits") or []:
            if row.get("code"):
                codes[str(row["code"])] += 1

    print(f"자격 확인된 공고 {checked}/{len(views)}건 · 업종제한 있는 공고 {limited}건 · 지역제한 있는 공고 {regioned}건")
    print("업종 코드 상위:", ", ".join(f"{code} {n}건" for code, n in codes.most_common(8)) or "(없음)")
    rows = sum(
        (qualification_store.load_day(day).license_rows if qualification_store.load_day(day) else 0)
        for day in days
    )
    # 40차 COLLECT-10 — 39차 D20 뒤 하루치는 Git 밖(data/private/qualifications)에 쓴다. 추적 폴더(STORE_DIR)를 적으면 거기서 새 날 파일을 찾는다.
    print(f"저장된 면허제한 행 합계 {rows:,}행 · 저장 폴더 {qualification_store.PRIVATE_STORE_DIR}")
    _ = storage  # 저장은 서비스가 한다. import 를 남겨 두는 것은 경로 초기화 때문이다.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
