"""이미 빠진 열린 공고를 기준본에서 한 번 되살린다 (39차 §3-F-4 · recheck31 COLLECT-03). **바깥 호출 없음.**

38차 `carry_open_notices` 는 «지금 저장본에 있는» 열린 공고만 잇는다 — 그 전에 이미 빠진 공고(1726242 「연암공과대학교 AI Agent …」 ·
1725538 · 1722200)는 되살리지 못했다. 이 스크립트는 기준본(추적 파일 `data/public/sample_procurements/g2b_cache.json` · c22e38fd)에서
**살아 있는 저장본에 없는** 공고 중 마감 전이고 지금 분류가 후보인 것만 살아 있는 저장본(Git 밖)에 붙인다. 붙은 공고는 다음 매일 받기부터
`carry_open_notices` 가 마감까지 잇는다.

    python scripts/revive_open_notices.py            # 무엇을 붙일지만 보인다
    python scripts/revive_open_notices.py --apply    # 살아 있는 저장본에 붙인다(받은 때 · 받기 기록은 그대로)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ("LIVE_FETCH", "G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "EMBEDDING_LIVE", "SEMANTIC_FIT", "LLM_LIVE"):
    os.environ[name] = "0"
sys.path.insert(0, str(ROOT / "backend"))

from app.core import storage  # noqa: E402
from app.schemas.procurement import ProcurementNotice  # noqa: E402
from app.services import g2b_mapper, procurement_service  # noqa: E402
from app.services.opportunity_filter import classify  # noqa: E402

DEFAULT_BASELINE = ROOT / "data" / "public" / "sample_procurements" / "g2b_cache.json"


def candidates(baseline: Path) -> tuple[procurement_service.ProcurementResult, list[procurement_service.NoticeView]]:
    live = procurement_service.load_cache()
    if live is None:
        raise SystemExit("살아 있는 저장본이 없습니다 — 되살릴 곳이 없습니다")
    if procurement_service.cache_read_path() != procurement_service.CACHE_FILE:
        raise SystemExit("살아 있는 저장본(Git 밖)이 아니라 기준본을 읽고 있습니다 — 멈춤")
    now = storage.utc_now()
    # 창 안인데 이번 받기에 없던 공고는 취소 · 삭제일 수 있다 — `carry_open_notices` 와 같이 창 시작 전에 게시된 것만 되살린다
    window_start = live.fetched_at - timedelta(days=live.days or procurement_service.DEFAULT_DAYS)
    present = {g2b_mapper.base_notice_no(v.notice.notice_no) for v in live.notices}
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    found: list[procurement_service.NoticeView] = []
    for entry in payload.get("notices") or []:
        if entry.get("pinned"):
            continue
        notice = ProcurementNotice.model_validate(entry["notice"])
        base = g2b_mapper.base_notice_no(notice.notice_no)
        if base in present:
            continue
        deadline = procurement_service._real_deadline(notice)
        match = classify(notice)
        if deadline is None or deadline <= now or not match.is_candidate or notice.published_at is None or notice.published_at >= window_start:
            continue
        found.append(procurement_service.NoticeView(notice=notice, match=match))
        present.add(base)
    return live, found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    live, found = candidates(Path(args.baseline))
    print(f"살아 있는 저장본 {len(live.notices)}건(받은 때 {live.fetched_at:%Y-%m-%d %H:%M} UTC) · 되살릴 것 {len(found)}건")
    for view in found:
        deadline = procurement_service._real_deadline(view.notice)
        print(f"  {view.notice.id} · 마감 {deadline:%m-%d %H:%M} · {view.match.tier} · {view.notice.title[:50]}")
    if not args.apply or not found:
        return 0
    note = procurement_service.save_cache(
        [*live.notices, *found], live.total_fetched, live.fetched_at, live.days,
        collected_by=live.collected_by, collect_calls=live.collect_calls,
    )
    print("붙였습니다." if note is None else f"쓰지 않았습니다 — {note}")
    return 0 if note is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
