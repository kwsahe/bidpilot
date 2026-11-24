"""사업기회 「재수집」 — 나라장터 · 기업마당 목록을 새로 받는다 (20차 §4-G).

담당자 지시(2026-09-23): 「사업기회에 재수집 버튼 추가. 나라장터, 기업마당으로.」

- **새 경로를 만들지 않는다.** 나라장터는 `procurement_service.list_ai_candidates(refresh=True)`
  (자격 제한 하루 표 포함), 기업마당은 `bizinfo_service.list_programs(refresh=True)` 를 그대로 부른다.
- **시연 고정 모드면 네트워크를 부르지 않고 거절한다**(409) — 시연 자료를 지키는 규칙이 먼저다.
- 캐시 축소 차단(`storage.cache_shrink_reason`)도 그대로다 — 막히면 409 와 사유, 캐시는 그대로.
- 같은 출처가 도는 중이면 409 「이미 받는 중」. 한 번에 하나만 돈다.
- 첨부(입찰공고문)는 **받지 않는다**(`ATTACHMENT_FETCH` 규칙). 새 공고 중 참가자격 조항 파일이 없는 수만 센다.

2.0.7 「찾는 낱말」 바로 찾기(`search_keyword`)도 여기 둔다 — 같은 출처 잠금(`_lock("g2b")`)을 함께 쓰고, 아침 받기와는
받기 잠금(`auto_collect` 의 `collect_daily.lock`)으로 겹치지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.services import (
    auto_collect,
    bizinfo_client,
    bizinfo_service,
    collect_keywords_service,
    g2b_client,
    procurement_service,
    qualification_clause_service,
)

RecollectSource = Literal["g2b", "bizinfo"]
SOURCE_LABELS: dict[str, str] = {"g2b": "나라장터", "bizinfo": "기업마당"}

_LOCKS: dict[str, asyncio.Lock] = {}


class RecollectRefusedError(Exception):
    """재수집을 하지 않았다(409) — 사유 문장을 그대로 화면에 보인다."""


@dataclass
class Snapshot:
    count: int
    fetched_at: str | None
    ids: set[str] = field(default_factory=set)

    def public(self) -> dict[str, Any]:
        return {"count": self.count, "fetched_at": self.fetched_at}


def _lock(source: str) -> asyncio.Lock:
    if source not in _LOCKS:
        _LOCKS[source] = asyncio.Lock()
    return _LOCKS[source]


def _g2b_snapshot() -> Snapshot:
    cached = procurement_service.load_cache()
    if cached is None:
        return Snapshot(count=0, fetched_at=None)
    return Snapshot(
        count=len(cached.notices),
        fetched_at=cached.fetched_at.isoformat(),
        ids={view.notice.id for view in cached.notices},
    )


def _bizinfo_snapshot() -> Snapshot:
    try:
        payload = json.loads(bizinfo_service.CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Snapshot(count=0, fetched_at=None)
    items = payload.get("items") or []
    return Snapshot(
        count=len(items),
        fetched_at=payload.get("fetched_at"),
        ids={str(item.get("pblancId")) for item in items if isinstance(item, dict) and item.get("pblancId")},
    )


def frozen_reason(source: str) -> str | None:
    """이 출처의 실호출 문이 꺼져 있으면 그 사유. 켜져 있으면 None."""
    live = procurement_service.live_fetch_enabled() if source == "g2b" else bizinfo_service.live_fetch_enabled()
    if live:
        return None
    return (
        f"새 공고 받기 꺼짐 — {SOURCE_LABELS[source]} 새로 받기가 꺼져 있습니다. "
        "켜려면 관리자에게 요청하세요"  # 스크립트 이름 · 옵션은 화면에 적지 않는다(27차 §3-H)
    )


async def recollect(source: str) -> dict[str, Any]:
    """재수집하고 전후를 돌려준다. 하지 않았으면 `RecollectRefusedError`."""
    if source not in SOURCE_LABELS:
        raise ValueError(f"알 수 없는 출처입니다: {source}")
    reason = frozen_reason(source)
    if reason is not None:
        raise RecollectRefusedError(reason)
    lock = _lock(source)
    if lock.locked():
        raise RecollectRefusedError(f"{SOURCE_LABELS[source]} 목록을 이미 받는 중입니다. 끝난 뒤 다시 누르세요.")
    async with lock:
        started = time.monotonic()
        if source == "g2b":
            body = await _recollect_g2b()
        else:
            body = await _recollect_bizinfo()
        body["took_ms"] = int((time.monotonic() - started) * 1000)
        return body


async def _recollect_g2b() -> dict[str, Any]:
    before = _g2b_snapshot()
    cached = procurement_service.load_cache()
    # 저장된 목록과 **같은 조회 기간**으로 받는다 — 기간이 다르면 다음 조회가 캐시를 못 쓰고 또 부른다.
    days = (cached.days if cached is not None and cached.days else procurement_service.DEFAULT_DAYS)
    procurement_service.clear_memo()
    try:
        result = await procurement_service.list_ai_candidates(days=days, include_low=True, refresh=True)
    except procurement_service.NoNoticeDataError as exc:
        raise RecollectRefusedError(f"나라장터에서 받지 못했고 저장된 목록도 없습니다: {exc}") from exc
    if result.source != "g2b":
        raise RecollectRefusedError(f"나라장터에서 받지 못했습니다 — 저장된 목록을 그대로 둡니다: {result.error or '사유 없음'}")
    if result.error:
        # 받은 건수가 저장된 것의 절반 아래 — 캐시를 지켰다(ISSUE-121).
        raise RecollectRefusedError(f"새 목록을 저장하지 않았습니다 — {result.error}")
    after = _g2b_snapshot()
    new_ids = sorted(after.ids - before.ids)
    return {
        "source": "g2b",
        "before": before.public(),
        "after": after.public(),
        "new": len(new_ids),
        "gone": len(before.ids - after.ids),
        "qualification": {
            "days_fetched": result.qualification_days_fetched,
            "calls": result.qualification_calls,
            "note": result.qualification_note,
        },
        "clauses_missing": sum(1 for notice_id in new_ids if not qualification_clause_service.clause_path(notice_id).exists()),
        "clauses_note": "새 공고의 입찰공고문은 받지 않았습니다 — scripts/fetch_qualification_clauses.py 로 받으세요",
    }


async def _recollect_bizinfo() -> dict[str, Any]:
    if not bizinfo_client.is_configured():
        raise RecollectRefusedError("기업마당 API 키가 없어 받을 수 없습니다 — 저장된 목록을 그대로 둡니다")
    before = _bizinfo_snapshot()
    response = await bizinfo_service.list_programs(refresh=True, count=bizinfo_client.FULL_COUNT)
    if response.source != "bizinfo":
        raise RecollectRefusedError(f"기업마당에서 받지 못했습니다 — 저장된 목록을 그대로 둡니다: {response.error or '사유 없음'}")
    if response.error:
        raise RecollectRefusedError(f"새 목록을 저장하지 않았습니다 — {response.error}")
    after = _bizinfo_snapshot()
    return {
        "source": "bizinfo",
        "before": before.public(),
        "after": after.public(),
        "new": len(after.ids - before.ids),
        "gone": len(before.ids - after.ids),
        "qualification": None,
        "clauses_missing": 0,
        "clauses_note": None,
    }


# --------------------------------------------------------------------------
# 「찾는 낱말」 바로 찾기 (2.0.7 · 대표 결정 ①)
# --------------------------------------------------------------------------

#: 화면 사본(`lib/collectKeywords.ts`)과 같은 글이다 — 노트북은 켤 때 받기라 시각을 적지 않는다.
# 「내일 아침」이라 박지 않는다 — 노트북 · 키트는 자동 받기가 꺼져 있을 수 있다(2.0.7 · 화면은 받은 때 한 줄로 더 정확히 고른다)
KEYWORD_SEARCH_OFF = "이 서버에서는 바로 찾기가 꺼져 있습니다 — 다음 목록 받기부터 이 낱말로 찾습니다"
KEYWORD_MORNING_BUSY = "아침 자동 받기가 도는 중입니다 — 끝난 뒤 다시 누르세요"
KEYWORD_BUSY = "나라장터 목록을 이미 받는 중입니다 — 끝난 뒤 다시 누르세요"


def keyword_limit_reason() -> str:
    return f"오늘 바로 찾기 {collect_keywords_service.SEARCHES_PER_DAY}번을 다 썼습니다 — 다음 목록 받기부터 찾습니다"


async def search_keyword(word: str) -> tuple[dict[str, Any] | None, str | None]:
    """추가 낱말 **하나만** 바로 찾는다. `(결과, 못 한 사유)` — 둘 중 하나는 None.

    문(`KEYWORD_SEARCH_LIVE` 또는 `G2B_LIVE_FETCH`) · 하루 10번 · 아침 받기 잠금 중 하나라도 걸리면 **바깥을 부르지 않고** 사유만 돌려준다
    (낱말 저장은 이미 끝났으므로 409 가 아니다). 받기 실패도 사유(아는 실패는 할 일 한 줄 · `auto_collect.failure_hint`) — 저장본은 그대로다.
    횟수는 바깥을 부르기 직전에 센다(실패해도 한 번).
    """
    if not collect_keywords_service.search_live():
        return None, KEYWORD_SEARCH_OFF
    lock = _lock("g2b")
    if lock.locked():
        return None, KEYWORD_BUSY
    async with lock:
        if collect_keywords_service.searches_today() >= collect_keywords_service.SEARCHES_PER_DAY:
            return None, keyword_limit_reason()
        if not auto_collect.acquire_lock():
            return None, KEYWORD_MORNING_BUSY
        try:
            collect_keywords_service.count_search()
            return await procurement_service.search_one_keyword(word), None
        except g2b_client.G2BClientError as exc:
            hint = auto_collect.failure_hint(str(exc))
            return None, f"나라장터에서 받지 못했습니다(저장된 목록은 그대로) — {hint or str(exc)[:160]}"
        except procurement_service.NotSavedError as exc:
            return None, f"새 목록을 저장하지 않았습니다 — {exc}"
        finally:
            auto_collect.release_lock()


async def add_keyword(word: str, *, by: str | None, expected_updated_at: datetime | None, search: bool) -> dict[str, Any]:
    """추가 낱말을 저장하고(늘 먼저) `search` 면 그 낱말 하나만 바로 찾는다. 규칙 · 10개 → `KeywordRuleError` · 그사이 바뀜 → `StaleWriteError`."""
    saved = collect_keywords_service.add(word, by=by, expected_updated_at=expected_updated_at)
    result, error = await search_keyword(saved) if search else (None, None)
    return {"word": saved, "state": collect_keywords_service.state(), "search": result, "search_error": error}


async def research_keyword(word: str) -> dict[str, Any]:
    """이미 더한 추가 낱말을 다시 바로 찾는다. 목록에 없으면 `KeywordRuleError`."""
    saved = collect_keywords_service.find_extra(word)
    result, error = await search_keyword(saved)
    return {"word": saved, "state": collect_keywords_service.state(), "search": result, "search_error": error}
