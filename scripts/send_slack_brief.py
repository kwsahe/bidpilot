"""평일 아침 슬랙 브리핑 보내기(2.6.0 · 대표 11-06) — 회사 서버 cron(평일 07:40 · 09:40 · 11:40)이 `slack_brief_now.sh --scheduled` 로 부른다.

  python scripts/send_slack_brief.py                 # 글만 만들어 보여 준다(네트워크 0 · 기본)
  python scripts/send_slack_brief.py --run           # 평일 · 하루 한 번 · 오늘 목록을 받은 뒤에만 보낸다(cron)
  python scripts/send_slack_brief.py --run --force   # 지금 한 번 보낸다(시험 보내기 · 보낸 날은 적지 않는다)

목록은 **받아 둔 저장본만** 읽는다(이 스크립트는 나라장터 · 기업마당을 부르지 않는다 — 받기는 `collect_daily.py`).
아침 받기가 아직 돌고 있으면(받기 잠금) 최대 15분 기다린다. 결과는 JSON 한 줄(`--json`) — 슬랙 주소는 어디에도 싣지 않는다.
종료 코드: 0 보냄 · 안 보낼 때(주말 · 오늘 이미 보냄 · 주소 없음 · 아직 못 받음) · 1 보내기 실패.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

# 브리핑은 저장본만 읽는다 — 서버 .env 에 무엇이 있든 바깥 받기 문은 닫는다(받기는 collect_daily.py 의 몫).
for _gate in ("G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "KEYWORD_SEARCH_LIVE"):
    os.environ[_gate] = "0"

from app.services import auto_collect, slack_brief_service  # noqa: E402

LOCK_WAIT_SECONDS = 15 * 60
LOCK_POLL_SECONDS = 30


def wait_for_collect(limit: float = LOCK_WAIT_SECONDS) -> bool:
    """아침 받기가 돌고 있으면 끝날 때까지(최대 `limit` 초) 기다린다 — 끝났으면 True."""
    waited = 0.0
    while auto_collect.lock_info(datetime.now(timezone.utc)) is not None:
        if waited >= limit:
            return False
        time.sleep(LOCK_POLL_SECONDS)
        waited += LOCK_POLL_SECONDS
    return True


def scheduled_skip(now: datetime) -> dict | None:
    """cron 실행 앞 검사 — 안 보낼 까닭이면 로그 한 줄, 보낼 차례면 None.

    값싼 검사(주소 · 주말 · 오늘 이미 보냄)를 받기 잠금 기다림보다 **먼저** 한다 — 꺼 둔 날 15분을 헛되이 기다리지 않게.
    잠금이 15분 넘게 안 풀리면 다음 시도에 넘기되, 그날 마지막 시도(11시 뒤)는 「받는 중」 받은 때 한 줄과 함께 보낸다."""
    row = {"시각": now.isoformat(), "보냄": False}
    try:
        url = slack_brief_service.webhook_url()
    except slack_brief_service.SlackBriefError as exc:
        return {**row, "실패": True, "사유": str(exc)}
    if url is None:
        return None  # `run` 이 「꺼 둠」 한 줄을 적는다
    if why := slack_brief_service.precheck(now):
        return {**row, "사유": why}
    if not wait_for_collect() and not slack_brief_service.is_final(datetime.now(timezone.utc)):
        return {**row, "사유": "아침 받기가 15분 넘게 도는 중 — 다음 시도에 다시"}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="평일 아침 슬랙 브리핑 (기본은 글만 만들어 보여 줌)")
    parser.add_argument("--run", action="store_true", help="실제로 보낸다(평일 · 하루 한 번 · 오늘 목록을 받은 뒤)")
    parser.add_argument("--force", action="store_true", help="평일 · 하루 한 번 · 받기 기다림을 건너뛰고 지금 보낸다(시험)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로(로그용)")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    try:
        row = scheduled_skip(now) if args.run and not args.force else None
        if row is None:
            row = asyncio.run(slack_brief_service.run(datetime.now(timezone.utc), force=args.force, send_it=args.run))
    except Exception as exc:  # noqa: BLE001 — cron 로그에 실패 한 줄을 남긴다(원문은 .err · 주소는 send 가 예외에서 떼어 냄)
        traceback.print_exc(file=sys.stderr)
        row = {"시각": now.isoformat(), "보냄": False, "실패": True, "사유": f"브리핑을 만들지 못했습니다 — {type(exc).__name__}"}

    if args.json:
        print(json.dumps({k: v for k, v in row.items() if k != "글"}, ensure_ascii=False))
    elif "글" in row:
        payload = row["글"]
        print(payload["text"])
        for block in payload["blocks"]:
            text = (block.get("text") or {}).get("text") or " ".join(e.get("text", "") for e in block.get("elements") or [])
            print("\n" + text)
    else:
        print(("보냈습니다" if row.get("보냄") else "보내지 않음") + (f" — {row['사유']}" if row.get("사유") else ""))
    return 1 if row.get("실패") else 0


if __name__ == "__main__":
    raise SystemExit(main())
