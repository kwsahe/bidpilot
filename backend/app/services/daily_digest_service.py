"""「오늘 달라진 것」 — 담당자가 아침에 이 화면을 여는 이유 (0919.md §4-B-1).

지금은 아침에 열어도 어제와 같은 화면이다. 달라진 것이 있는지 알려면 목록을 눈으로 훑어야
한다. 한 줄로 먼저 말한다: **새 공고 n · 변경된 공고 n · 7일 내 마감 n · 내 결정 대기 n.**

## 실호출을 하지 않는다

이 집계는 **이미 받아 둔 목록**에서만 센다. 화면을 열 때마다 나라장터를 부르면 시연 중에
목록이 바뀌고(ISSUE-062) 호출 한도도 쓴다. 그래서 「마지막으로 받아온 시각」을 함께 돌려주고,
화면은 그것을 그대로 적는다. 언제 기준인지 모르는 숫자는 없느니만 못하다.

## 셀 수 있는 것과 없는 것

정직하게 갈라 둔다. 네 숫자가 각각 무엇을 근거로 하는지 `basis` 에 적는다.

- **새 공고**: 공고의 `published_at` 이 창 안. 나라장터가 준 게시일이라 확실하다.
- **변경된 공고**: `notice_version_service` 의 변경 기록이 창 안. 이 기록은 **실호출로 목록을
  받아올 때만** 쌓인다(`save_cache` → `record_many`). 그래서 시연 고정 모드나 캐시 적중이
  이어지면 새 변경이 잡히지 않는다 — 0 이 「변경이 없다」가 아니라 「그동안 받아온 적이
  없다」일 수 있다. 그 경우를 `notes` 로 말한다.
- **7일 내 마감**: `deadline_at`. 이미 지난 것은 세지 않는다.

「마감된 공고」를 세는지 아닌지는 숫자마다 다르다(`basis` 에 적는다). 목록 화면은 기본값으로
마감된 건을 숨기므로, **마감된 것을 포함해 센 숫자의 링크에는 `closed=1` 을 붙여야** 누른
숫자와 도착한 목록이 같아진다. 실제로 「내 결정 대기 5건」을 눌렀더니 2건이 나왔다 —
다섯 중 셋이 이미 마감된 공고였다.
- **내 결정 대기**: **분석을 시작한** 공고(요구사항이 저장된 것) 중 결정이 아직
  `UNREVIEWED` 인 것. 「결정 파일이 있는가」로 세지 않는 이유가 있다 — 결정 조회는 파일이
  없어도 `UNREVIEWED` 를 만들어 돌려주므로, 파일 유무로는 아무것도 구분되지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import storage
from app.schemas.organization import AnalysisContext
from app.services import notice_state_service, notice_version_service, procurement_service, review_queue_service

logger = logging.getLogger(__name__)

#: 「새로 올라온 것」으로 볼 기간(일). 주말을 건너뛰어도 월요일에 금요일치가 보이게 3일이다.
DEFAULT_NEW_DAYS = 3
#: 「곧 마감」으로 볼 기간(일).
DEFAULT_DUE_DAYS = 7
#: 응답에 실어 보낼 공고 id 상한. 목록이 통째로 바뀐 날에도 응답이 부풀지 않게 한다.
MAX_IDS = 300


@dataclass(frozen=True)
class Count:
    """숫자 하나와 «무엇을 근거로 셌는가»."""

    value: int
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "basis": self.basis}


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _changed_recently(procurement_id: str, since: datetime) -> bool:
    """이 공고에 창 안의 변경 기록이 있는가. 기록을 못 읽으면 「없음」으로 본다."""
    try:
        history = notice_version_service.load_history(procurement_id)
    except Exception as exc:  # noqa: BLE001 — 집계가 화면을 막지 않는다
        logger.debug("공고 버전 기록을 읽지 못했습니다 (%s): %s", procurement_id, exc.__class__.__name__)
        return False
    for change_set in history.changes:
        observed = _aware(change_set.observed_at)
        if observed is not None and observed >= since:
            return True
    return False


async def build(
    *,
    context: AnalysisContext | None = None,
    new_days: int = DEFAULT_NEW_DAYS,
    due_days: int = DEFAULT_DUE_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """한 줄 띠에 넣을 값. **네트워크를 부르지 않는다.**"""
    moment = now or storage.utc_now()
    new_since = moment - timedelta(days=new_days)
    due_until = moment + timedelta(days=due_days)
    # 40차 마지막 검토 — 받은 때 한 줄은 예약 작업 상태를 PowerShell 로 읽을 수 있다(5분 메모) — 이벤트 루프 밖 스레드에서 한 번
    collect = await asyncio.to_thread(_collect_state, moment)

    # 저장된 목록만 읽는다. `list_ai_candidates()` 를 쓰면 안 된다 — TTL 이 지나면 실호출로
    # 넘어가고 그 결과로 Git 이 추적하는 캐시 파일을 덮어쓴다. 이 집계를 만들다가 실제로
    # 한 번 그렇게 됐고(캐시 4,205줄이 바뀌어 되돌렸다), 그래서 `cached_only()` 를 따로 두었다.
    #
    # 범위는 목록 화면의 기본값과 **같다**(`include_low=False`). 처음에는 캐시를 통째로 셌는데
    # 「새 공고 78건」을 눌러 들어가면 8건짜리 목록이 나왔다 — 캐시에는 업무 키워드만 맞는
    # 공고까지 들어 있기 때문이다. 누른 곳과 도착한 곳의 숫자가 다르면 띠는 거짓말이 된다.
    result = procurement_service.cached_only()
    if result is None:
        return {
            "as_of": moment.isoformat(),
            "fetched_at": None,
            "source": None,
            "frozen": not procurement_service.live_fetch_enabled(),
            "auto_collect_at": _auto_collect_at(moment),
            "collect_state": collect,
            "new_days": new_days,
            "due_days": due_days,
            "total_notices": 0,
            "analysed_notices": 0,
            "new_notices": Count(0, "아직 목록을 받아온 적이 없습니다").to_dict(),
            "changed_notices": Count(0, "아직 목록을 받아온 적이 없습니다").to_dict(),
            "due_soon": Count(0, "아직 목록을 받아온 적이 없습니다").to_dict(),
            "awaiting_decision": Count(0, "아직 목록을 받아온 적이 없습니다").to_dict(),
            "changed_ids": [],
            "pending_ids": [],
            "notes": ["저장된 공고 목록이 없습니다. 목록 화면을 한 번 열어 받아 오세요."],
        }

    fresh = 0
    due_soon = 0
    awaiting = 0
    analysed = 0
    # 43차 BRIEF-05 · NUM-03 — 띠는 「누르면 가는 목록」과 같은 범위다: 그 목록은 참가 「불가」를 기본으로 숨긴다(지역 제한 등 20건 차이).
    found_blocked = await _blocked_ids(context, moment)
    blocked = found_blocked or set()
    # 「변경된 공고」만 id 를 함께 돌려준다. 새 공고·마감은 목록만 있으면 화면에서 셀 수
    # 있지만, 변경 여부는 버전 기록을 읽어야 알 수 있어 화면이 스스로 판단하지 못한다.
    changed_ids: list[str] = []
    # 「내 결정 대기」도 마찬가지다. 분석을 시작했는지 · 결정을 내렸는지는 저장소를 읽어야
    # 알 수 있어 화면이 목록만으로 판단하지 못한다.
    pending_ids: list[str] = []
    from app.services import opportunity_service

    for view in result.notices:
        notice = view.notice
        if notice.id in blocked:
            continue
        # 43차 NUM-02 — 실제 마감(등록 · 공고문 일정이 더 이르면 그쪽) · KST 달력 날짜 차(목록 D-day 와 같은 셈)
        real = review_queue_service.real_deadline(notice)
        # 10-31 최종 점검 B — 새 공고는 원공고 게시일(43차 M2 · 통합 목록 `published_at` 과 같은 함수 · 모르면 세지 않음) — 변경공고가 변경 게시일로 섰다
        published = _aware(opportunity_service._published_dates(notice)[0])
        # 2.1.0 — 실제 마감이 지난 새 공고는 세지 않는다 · 사업기회 기본 목록(마감 뺌) · 대시보드 「새 공고」와 같은 범위(2.1.0 검토 4)
        if published is not None and published >= new_since and (real is None or real >= moment):
            fresh += 1
        if real is not None and real >= moment and _calendar_days(real, moment) <= due_days:
            due_soon += 1
        if _changed_recently(notice.id, new_since):
            changed_ids.append(notice.id)
        if notice_state_service.state_of(notice.id, context).parsed:
            analysed += 1

    # 「내 결정 대기」는 **「검토 중」 탭과 같은 집합**이다 (0920 §4-B-3 · ISSUE-076-a).
    #
    # 예전에는 띠가 「목록에 있는 공고 중 파싱됨 + 결정 미정」을, 탭은 「결정·검토·발견 파일이
    # 있는 공고」를 셌다. 정의가 달라 같은 순간 띠 5건 · 탭 0건이었다. 지금은 두 화면이
    # 같은 함수를 부르고, 띠를 누르면 그 탭이 열린다.
    #
    # 이 숫자만 **목록 범위를 벗어난다** — 목록에서 내려간 공고도 검토 중인 일은 끝내야 하기
    # 때문이다. 나머지 세 숫자(새 공고·변경·마감)는 목록에서 센다.
    awaiting_open = 0
    queue_ids = notice_state_service.review_queue_ids(context)
    # (2.0.6 links-1) 지원사업 · 직접 넣은 공고는 나라장터 목록에 없다 — 「검토 중」 탭과 같은 곳에서 마감을 읽는다(살아 있는 사업이 「마감 지남」에 셌다)
    others = review_queue_service.other_notices(queue_ids, context=context)
    # (2.0.6) 「마감 전 · 지남」은 띠를 누르면 가는 탭과 같은 판단(`queue_place`) · 같은 넓은 저장본(관련 낮음 포함)이다 — 좁은 목록으로 세서
    # 분석한 관련 낮음 입찰 · 마감일 없는(상시) 사업이 띠는 「지남」, 탭은 「살아 있는 공고」였다. 위 새 공고 · 마감 셈은 좁은 목록 그대로.
    by_id, pinned_ids = review_queue_service.wide_listing()
    for procurement_id in queue_ids:
        if notice_state_service.state_of(procurement_id, context).awaiting_decision:
            awaiting += 1
            pending_ids.append(procurement_id)
            place, _deadline = review_queue_service.queue_place(
                procurement_id, by_id=by_id, pinned_ids=pinned_ids, others=others, moment=moment
            )
            if place == "live":
                awaiting_open += 1
    pending_ids.sort()

    changed = len(changed_ids)
    notes: list[str] = []
    frozen = not procurement_service.live_fetch_enabled()
    if frozen and collect.get("kind") == "none":
        # 40차 COLLECT-02 — 「꺼짐」 말은 자동 받기 기록도 예약 작업도 없을 때(키트)만. 예약 작업 PC 에서는 같은 띠의 받은 때 줄과
        # 두 말(「매일 받는다 / 꺼져 있다」)이 됐다 — 그 PC 는 매일 처음 켤 때 받으므로 메모를 붙이지 않는다.
        notes.append(
            "새 공고 받기가 꺼져 있습니다 — 저장된 목록으로 셌고, 변경 감지는 목록을 다시 받아올 때만 쌓입니다."
        )
    elif not frozen and changed == 0:
        notes.append("변경 기록은 목록을 실제로 받아올 때만 쌓입니다. 0 은 「그동안 받아온 적이 없다」일 수도 있습니다.")
    if found_blocked is None:
        # (2.0.6) 실패를 빈 집합으로 삼키면 띠 숫자가 목록보다 큰 이유를 알 수 없었다
        notes.append("참가 불가 공고를 가려내지 못해 불가도 함께 셌습니다 — 누르면 가는 목록보다 숫자가 클 수 있습니다.")

    return {
        "as_of": moment.isoformat(),
        # 화면이 「언제 기준인지」를 반드시 함께 적는다.
        "fetched_at": result.fetched_at.isoformat(),
        "source": result.source,
        "frozen": frozen,
        # 38차 §3-C-4 — 매일 아침 자동 받기의 마지막 성공(48시간 안일 때만). 화면이 「꺼짐」 대신 그 시각을 적는다.
        "auto_collect_at": _auto_collect_at(moment),
        # 39차 §3-F-2 · 40차 D30 — 화면 한 줄(오늘 받음 · 받는 중 · 오늘 아직 · 꺼 둠 · 기록 없음). 화면은 이것으로 고른다.
        "collect_state": collect,
        "new_days": new_days,
        "due_days": due_days,
        "total_notices": len(result.notices),
        "analysed_notices": analysed,
        "new_notices": Count(fresh, f"나라장터 후보 중 공고 게시일이 최근 {new_days}일 이내 (참가 불가 · 실제 마감이 지난 것은 뺌 · 목록과 같은 범위)").to_dict(),
        "changed_notices": Count(changed, f"공고 내용이 최근 {new_days}일 안에 바뀐 기록이 있음 (마감된 것 포함)").to_dict(),
        # 목록 화면이 「변경된 것만」으로 걸러 보려면 어느 공고인지 알아야 한다.
        # 상한을 둔다 — 전부 바뀐 날에도 응답이 부풀지 않게.
        "changed_ids": changed_ids[:MAX_IDS],
        "pending_ids": pending_ids[:MAX_IDS],
        "due_soon": Count(due_soon, f"나라장터 후보 중 실제 마감(등록 · 공고문 일정이 더 이르면 그쪽)이 {due_days}일 이내 (참가 불가 · 지난 것은 뺌)").to_dict(),
        "awaiting_decision": Count(
            awaiting, f"분석을 시작했는데 아직 참여 여부를 정하지 않음 — 마감 전 {awaiting_open} · 마감 지남 · 목록에서 내려감 {awaiting - awaiting_open}"
        ).to_dict(),
        # 43차 Q26 · NUM-09 — 「참여 미정」 띠 = 「마감 전 n · 마감 지남 m」
        "awaiting_open": awaiting_open,
        "awaiting_closed": awaiting - awaiting_open,
        "notes": notes,
    }


async def _blocked_ids(context: AnalysisContext | None, moment: datetime) -> set[str] | None:
    """목록이 기본으로 숨기는 참가 「불가」 공고 id — 목록과 같은 판정(메모)을 쓴다.

    못 구하면 None(2.0.6 — 띠는 막지 않되 「없음」과 갈라 notes 에 사유를 적는다). 회사가 없으면 빈 집합."""
    if context is None:
        return set()
    from app.services import opportunity_brief_service, opportunity_service

    try:
        listing = await opportunity_service.list_opportunities(
            context=context, source="g2b", days=60, include_blocked=True, include_closed=True, now=moment
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("띠의 참가 불가 집합을 만들지 못했습니다: %s", exc.__class__.__name__)
        return None
    if "g2b" in opportunity_brief_service.failed_sources(listing):
        # 나라장터를 못 읽은 목록은 불가를 가려내지 못한다(빈 목록이 「불가 0」으로 읽히지 않게).
        # 판단은 브리핑과 같은 함수 — 저장본으로 대신 받은 날은 오류 글이 있어도 항목에서 가려낼 수 있다
        return None
    return {item.id for item in listing.items if item.eligibility_gate == "FAIL"}


def _calendar_days(deadline: datetime, moment: datetime) -> int:
    kst = timezone(timedelta(hours=9))
    return (deadline.astimezone(kst).date() - moment.astimezone(kst).date()).days


def _collect_state(moment: datetime) -> dict[str, Any]:
    """자동 받기 한 줄(39차 §3-F-2) — 목록 응답과 같은 함수(`auto_collect.collect_state`)."""
    from app.services import auto_collect

    return auto_collect.collect_state(moment)


def _auto_collect_at(moment: datetime) -> str | None:
    """자동 받기 마지막 성공(48시간 안 · ISO). 로그가 없으면 None (38차 §3-C-4)."""
    from app.services import auto_collect

    found = auto_collect.fresh_success(moment)
    return found.isoformat() if found else None
