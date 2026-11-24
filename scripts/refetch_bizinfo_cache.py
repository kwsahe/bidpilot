#!/usr/bin/env python
"""기업마당 목록 캐시만 다시 받는다 (13차 사고 복구).

## 왜 이 스크립트가 따로 있나

2026-09-18 19:32, 진단 스크립트가 **환경변수를 세우지 않고** 앱을 import 하는 바람에
기업마당 실호출이 일어나 캐시가 1,620건 → 100건으로 덮어써졌다(클라이언트 기본 count).
`data/private/` 는 Git 제외라 되돌릴 사본이 없다.

`scripts/collect_daily.py` 로도 받을 수 있지만 그쪽은 **나라장터까지 함께** 받고 공고문을
최대 40건 내려받는다. 나라장터 캐시(`g2b_cache.json`)는 Git 이 추적하고 지금 커밋과 다른
상태이며 **되돌릴지 말지는 담당자가 정할 일**이라(prompt_02 §1-5) 건드리면 안 된다.
그래서 「기업마당 목록 한 번」만 하는 문을 따로 둔다.

## 하는 일 — 그리고 하지 않는 일

**한다**: 기업마당 OpenAPI 목록을 `FULL_COUNT` 로 한 번 조회하고 캐시를 저장한다.

**하지 않는다**: 나라장터 조회(환경변수로 막는다) · 기업마당 파일 서버(공고문) · LLM ·
분석 · 요구사항 추출 · 회사자료 색인.

## 쓰는 법

    python scripts/refetch_bizinfo_cache.py            # 무엇을 할지만 출력
    python scripts/refetch_bizinfo_cache.py --run      # 실제로 받는다

기본이 dry-run 인 이유는 `collect_daily.py` 와 같다 — 이 스크립트가 하는 일은 바깥을
부르고 캐시를 덮어쓰는 것이다. 무심코 돌아가면 안 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# **앱을 import 하기 전에** 실호출 범위를 못 박는다.
#
# 이 순서가 이 파일의 핵심이다. 아래 import 가 설정을 읽으면서 클라이언트를 만들기
# 때문에, 그 뒤에 환경변수를 세우면 이미 늦다. 19:32 사고가 정확히 그 순서 문제였다.
# 본보기는 `scripts/check_gate.py` 다.
# ---------------------------------------------------------------------------
# 설정 기본값은 **꺼짐**이다 (ISSUE-120). 아래 두 줄이 이 스크립트가 여는 유일한 문이다.
os.environ["G2B_LIVE_FETCH"] = "0"  # 나라장터는 부르지 않는다 (담당자 결정 대기 중)
os.environ["BIZINFO_LIVE_FETCH"] = "1"  # 승인받은 복구 대상만 연다

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core import storage  # noqa: E402
from app.services import bizinfo_client, bizinfo_service  # noqa: E402


def _current() -> tuple[int, str | None]:
    payload = storage.read_json(bizinfo_service.CACHE_FILE, default=None)
    if not isinstance(payload, dict):
        return 0, None
    return len(payload.get("items") or []), payload.get("fetched_at")


async def main() -> int:
    parser = argparse.ArgumentParser(description="기업마당 목록 캐시만 다시 받는다")
    parser.add_argument("--run", action="store_true", help="실제로 받는다 (기본은 예정만 출력)")
    args = parser.parse_args()

    # 첫 줄에 「내가 바깥을 연다」 (prompt_03 §4-A-2).
    print("실호출: 이 스크립트가 기업마당만 엽니다 (BIZINFO_LIVE_FETCH=1) — 설정 기본값은 꺼짐")
    before, before_at = _current()
    print(f"지금 캐시: {before}건 (fetched_at {before_at})")
    print(f"받을 것  : 기업마당 목록 1회 · count={bizinfo_client.FULL_COUNT}")
    print("안 받을 것: 나라장터(G2B_LIVE_FETCH=0) · 공고문 파일 서버 · LLM")

    if not args.run:
        print("\n(예정만 출력했습니다. 실제로 받으려면 --run)")
        return 0

    if not bizinfo_service.live_fetch_enabled():
        print("\n기업마당 실호출이 막혀 있습니다 — 환경변수를 확인하세요.", file=sys.stderr)
        return 2

    response = await bizinfo_service.list_programs(refresh=True, count=bizinfo_client.FULL_COUNT)
    after, after_at = _current()
    print(
        "\n"
        + json.dumps(
            {
                "받은_건수": response.count,
                "출처": response.source,
                "캐시_전": before,
                "캐시_후": after,
                "fetched_at": after_at,
            },
            ensure_ascii=False,
        )
    )
    return 0 if after >= before else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
