"""입찰공고문을 **한 번** 내려받아 참가자격 조항 파일을 만든다 (19차 §4-A-5).

담당자 지시(2026-09-23): 「자격요건은 확실하게 가져와서 판단해야 해.」 — 입찰공고문 첨부
내려받기는 허락됐다. 나라장터 목록 API·기업마당·임베딩·완성은 여전히 부르지 않는다.

## 무엇을 받나

대상 = 시연용 고정 4건 + 기준 답안 나라장터 24행(마감된 행도 — 수용 대조에 쓴다) + 오늘 마감 전
후보 전부. 합집합이고 중복은 뺀다. 공고마다 **입찰공고문 첨부 하나**만 받는다(제안요청서는
받지 않는다 — 이미 받아 둔 것이 있으면 두 번째 출처로 읽을 뿐이다).

공고 목록은 **저장된 캐시**(`g2b_cache.json`, 시연 고정)에서 읽는다 — 목록을 새로 받지 않는다.

## 문

`ATTACHMENT_FETCH=1` 을 **이 스크립트 안에서, 앱을 import 하기 전에** 세운다. 서버는 켜지 않는다.
`--cache-only` 를 주면 세우지 않는다 — 이미 받은 파일로 조항만 다시 뽑는다(네트워크 0).
두 번째 실행은 받은 파일이 캐시에 있으므로 새로 받는 것이 0 이다.

## 쓰기

    backend\\.venv\\Scripts\\python.exe scripts\\fetch_qualification_clauses.py
    backend\\.venv\\Scripts\\python.exe scripts\\fetch_qualification_clauses.py --cache-only
    backend\\.venv\\Scripts\\python.exe scripts\\fetch_qualification_clauses.py --ids g2b-R26BK01707959-000
    backend\\.venv\\Scripts\\python.exe scripts\\fetch_qualification_clauses.py --missing

`--missing`(33차): 마감 전 후보 중 **조항 파일이 아직 없는** 공고만 받는다. 이미 있는 조항 파일은 다시 쓰지 않는다 —
옵션 없이 돌리면 추적 중인 조항 파일까지 다시 써서(`qc.save`) 추출기가 바뀌었을 때 diff 가 생긴다.
R26BK01726154 는 담당자가 따로 허락할 때만 받는다(`--ids` 로만).
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD_CSV = ROOT / "docs" / "reports" / "2026-09-20_apply_candidates.csv"
KST = timezone(timedelta(hours=9))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="입찰공고문을 받아 참가자격 조항 파일을 만든다 (19차 §4-A-5)")
    parser.add_argument("--ids", help="쉼표로 구분한 공고 id (주지 않으면 시연용 4 + 기준 답안 24 + 마감 전 후보)")
    parser.add_argument("--cache-only", action="store_true", help="내려받지 않고 이미 받은 파일로만 조항을 뽑는다")
    parser.add_argument("--missing", action="store_true", help="마감 전 후보 중 조항 파일이 없는 공고만(기존 조항 파일은 그대로 · 33차)")
    parser.add_argument("--delay", type=float, default=0.6, help="내려받기 사이 쉬는 초 (나라장터에 예의)")
    return parser.parse_args()


ARGS = _parse_args()

# 바깥 문은 **전부 닫고**, 첨부 하나만 연다 — 앱을 import 하기 전에 세워야 설정이 이 값을 읽는다.
for name in ("G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "EMBEDDING_LIVE", "SEMANTIC_FIT", "LLM_LIVE"):
    os.environ[name] = "0"
os.environ["ATTACHMENT_FETCH"] = "0" if ARGS.cache_only else "1"
sys.path.insert(0, str(ROOT / "backend"))

from app.services import (  # noqa: E402
    attachment_service,
    g2b_mapper,
    procurement_service,
    qualification_clause_service as qc,
)


def _now() -> datetime:
    return datetime.now(KST)


def _views_by_id() -> dict[str, procurement_service.NoticeView]:
    """저장된 목록(캐시) + 고정 공고 저장소. 네트워크를 부르지 않는다."""
    cached = procurement_service.load_cache()
    views = list(cached.notices) if cached else []
    views = procurement_service._merge_pinned(views)
    return {view.notice.id: view for view in views}


#: 담당자가 따로 허락할 때만 받는 공고(19차 메모) — `--missing` 에서 뺀다. 받으려면 `--ids` 로 하나씩.
HOLD_BASE_NOS = frozenset({"R26BK01726154"})


#: 다시 받을 조항 파일 상태 — 내려받기 실패 · 여는 중 실패(34차 R33-R5). 「절 없음 · 그림」은 받아도 같으니 다시 받지 않는다.
RETRY_STATUSES = frozenset({"not_fetched", "error"})


def missing_targets() -> list[str]:
    """마감 전 후보 중 조항 파일이 없거나 **받다가 실패한**(not_fetched · error) 공고 id — 네트워크 0.

    34차 R33-R5: 실패도 파일로 남아 「이미 있음」이 되어 다시 시도하지 않았다. 보류 공고(1726154)는 그대로 뺀다."""
    candidates = procurement_service.cached_only(include_low=False)
    now = _now()
    out: list[str] = []
    for view in candidates.notices if candidates else []:
        deadline = view.notice.deadline_at
        if deadline is not None and deadline.astimezone(KST) < now:
            continue
        if g2b_mapper.base_notice_no(view.notice.notice_no) in HOLD_BASE_NOS:
            continue
        if view.notice.id in out:
            continue
        stored = qc.load(view.notice.id)
        if stored is None or stored.get("status") in RETRY_STATUSES:
            out.append(view.notice.id)
    return out


def _targets(by_id: dict[str, procurement_service.NoticeView]) -> list[str]:
    if ARGS.ids is not None:
        ids = [i.strip() for i in ARGS.ids.split(",") if i.strip()]
        if not ids:
            # 빈 --ids 가 기본 대상 전체 받기로 넘어갔다(33차 — 목록 파일을 다른 폴더에 써서 92건을 받음)
            raise SystemExit("--ids 가 비어 있습니다 — 받을 공고 id 를 쉼표로 적으세요(기본 대상으로 넘어가지 않습니다)")
        return ids
    if ARGS.missing:
        return missing_targets()
    wanted: list[str] = []

    def add(notice_id: str | None) -> None:
        if notice_id and notice_id not in wanted:
            wanted.append(notice_id)

    by_base: dict[str, str] = {}
    for notice_id, view in by_id.items():
        by_base.setdefault(g2b_mapper.base_notice_no(view.notice.notice_no), notice_id)
    for base in procurement_service.PINNED_NOTICE_NOS:
        add(by_base.get(base))
    for row in csv.DictReader(GOLD_CSV.open(encoding="utf-8-sig")):
        if row["출처"] != "나라장터":
            continue
        exact = "g2b-" + row["공고번호/ID"]
        add(exact if exact in by_id else by_base.get(row["공고번호/ID"].split("-")[0]))
    candidates = procurement_service.cached_only(include_low=False)
    now = _now()
    for view in candidates.notices if candidates else []:
        deadline = view.notice.deadline_at
        if deadline is None or deadline.astimezone(KST) >= now:
            add(view.notice.id)
    return wanted


async def main() -> int:
    by_id = _views_by_id()
    targets = _targets(by_id)
    fetch = attachment_service.attachment_fetch_enabled()
    print(f"대상 {len(targets)}건 · 내려받기 {'켜짐' if fetch else '꺼짐(캐시만)'} · {_now():%Y-%m-%d %H:%M} KST")

    downloaded = cached_hits = failed = no_document = missing_notice = 0
    downloaded_bytes = 0
    failures: list[str] = []
    status = collections.Counter()
    for number, notice_id in enumerate(targets, start=1):
        view = by_id.get(notice_id)
        if view is None:
            missing_notice += 1
            failures.append(f"{notice_id}: 저장된 목록에 없는 공고")
            continue
        attachments = list(view.notice.raw_data.get("attachments") or [])
        index = attachment_service.pick_notice_document(attachments)
        if index is None:
            no_document += 1
        else:
            attachment = attachments[index]
            name = str(attachment.get("name") or "")
            if attachment_service.cached_attachment(notice_id, index, name) is not None:
                cached_hits += 1
            elif fetch:
                try:
                    path = await attachment_service.download_attachment(
                        str(attachment["url"]), file_name=name, notice_id=notice_id, index=index
                    )
                    downloaded += 1
                    downloaded_bytes += path.stat().st_size
                    time.sleep(ARGS.delay)
                except attachment_service.AttachmentError as exc:
                    failed += 1
                    failures.append(f"{notice_id}: {exc}")
        payload = qc.build_payload(notice_id, attachments, published_at=view.notice.published_at)
        # 40차 CLAUSE-08 — 못 받은 결과(not_fetched · error)는 읽은 파일(ok · 절 없음 · 그림)을 덮지 않는다(`qc.save` 가 지킨다 · 두 폴더 모두)
        qc.save(payload)
        # 39차 DAILY-01 — 매일 받기가 쓴 Git 밖 파일이 있으면 그것이 먼저 읽힌다(`qc.load`) — 같이 새로 써야 다시 뽑기가 화면에 닿는다
        if qc.clause_path(notice_id, private=True).exists():
            qc.save(payload, private=True)
        status[payload["status"]] += 1
        print(f"  {number:3}. {notice_id:26} {payload['status']:11} 조항 {len(payload['clauses']):2}"
              f"{' · 둘째 출처 ' + str(len(payload['second_source']['clauses'])) if payload.get('second_source') else ''}"
              f"{' · ' + payload['note'][:40] if payload.get('note') else ''}")

    print()
    print(f"새로 받음 {downloaded}건 · {downloaded_bytes:,} 바이트 · 캐시에 있음 {cached_hits}건 · 실패 {failed}건"
          f" · 공고문 첨부 없음 {no_document}건 · 목록에 없음 {missing_notice}건")
    print("조항 파일 status: " + " · ".join(f"{k} {v}" for k, v in sorted(status.items())))
    for line in failures:
        print("  실패 · " + line)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    raise SystemExit(asyncio.run(main()))
