"""건수의 단일 분모 (0920.md §4-B-2 · ISSUE-075).

같은 화면 안에서도 숫자가 갈려 있었다 — 목록 머리는 「전체 107 · 나라장터 7 · 마감 1 제외」,
바로 아래 탭은 「전체 (104) · 나라장터 입찰 (4)」. 마감을 세는 기준이 달랐기 때문이다:
`closed_count` 는 **시연용 고정을 빼고** 세는데 목록은 고정이든 아니든 마감 행을 숨겼다.

그래서 백엔드가 한 벌만 세고 화면은 그것을 그대로 적는다. 여기서 지키는 약속은 넷이다.

1. 「마감 전」은 정말 마감 전만이다 — 시연용 고정이라도 마감이면 여기 들어가지 않는다.
2. 「마감」은 시연용 고정을 **포함**하고, 그중 몇 건이 고정인지 따로 말한다.
3. 「우선 검토」는 **전체 기준**이다 — 레이더가 그린 12건 안에서 세지 않는다.
4. `limit` 으로 잘라도 분모는 변하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from types import SimpleNamespace

from app.services import opportunity_service

NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)


def item(
    oid: str,
    *,
    source: str = "g2b",
    closed: bool = False,
    pinned: bool = False,
    priority: str = "검토",
    gate: str = "CHECK",
) -> SimpleNamespace:
    """집계가 보는 다섯 필드만 있는 최소 항목.

    통합 목록 항목 전체를 만들지 않는 이유는, 여기서 재는 것이 **세는 규칙**이지
    항목 스키마가 아니기 때문이다. 스키마는 `test_unified_opportunities.py` 가 본다.
    """
    return SimpleNamespace(
        id=oid,
        source_type=source,
        closed=closed,
        pinned=pinned,
        priority_label=priority,
        eligibility_gate=gate,
    )


def summarize(items: list[SimpleNamespace], days: int = 30):
    """**운영 코드를 그대로 부른다.** 여기서 다시 구현하면 테스트가 자기 자신을 잰다."""
    return opportunity_service.build_summary(items, days=days, fetched_at=NOW)


def test_마감_전과_마감을_한_기준으로_센다() -> None:
    """시연용 고정 공고는 마감이어도 목록에 남지만 «마감 전»은 아니다."""
    items = [
        item("a"),
        item("b", source="bizinfo"),
        item("c", closed=True),
        item("d", closed=True, pinned=True),
    ]
    summary = summarize(items)
    assert summary.open_total == 2
    assert summary.open_g2b == 1 and summary.open_bizinfo == 1
    assert summary.closed == 2, "마감은 시연용 고정도 포함해 센다"
    assert summary.closed_pinned == 1, "그중 몇 건이 고정인지 따로 말한다"


def test_우선_검토는_전체_기준이다() -> None:
    """레이더가 그린 12건 안에서 세면 같은 순간 목록과 다른 숫자가 된다."""
    items = [item(f"p{i}", priority="우선 검토") for i in range(5)] + [item("q")]
    assert summarize(items).priority == 5


def test_마감된_건은_우선_검토로_세지_않는다() -> None:
    items = [item("a", closed=True, priority="우선 검토"), item("b", priority="우선 검토")]
    assert summarize(items).priority == 1


@pytest.mark.parametrize("days", [14, 30, 60])
def test_조회_기간을_응답에_적는다(days: int) -> None:
    """네 화면이 같은 기간을 보고 있는지 확인할 길이 화면에 있어야 한다."""
    assert summarize([item("a")], days=days).days == days


def test_새_공고_기간도_응답이_말한다() -> None:
    """「새 공고」를 두 곳에서 따로 정하고 있었다 (0920 §4-B-5 · ISSUE-078).

    대시보드 띠는 응답의 `new_days` 를 읽는데 목록 화면은 자기 상수 `NEW_WINDOW_DAYS = 3`
    으로 걸렀다. 한쪽만 고치면 띠의 숫자와 목록의 건수가 조용히 갈린다. 여기서 재는 것은
    「목록 응답도 같은 값을 말하는가」다 — 값 자체가 3 인지가 아니라, **띠를 만드는 쪽과
    같은 곳에서 오는가**를 본다.
    """
    from app.services import daily_digest_service

    assert summarize([item("a")]).new_days == daily_digest_service.DEFAULT_NEW_DAYS


def test_띠와_목록이_같은_기간을_말한다() -> None:
    """`/api/dashboard/today` 의 기본값도 같은 상수에서 와야 한다."""
    import inspect

    from app.api import insights
    from app.services import daily_digest_service

    default = inspect.signature(insights.dashboard_today).parameters["new_days"].default
    assert default.default == daily_digest_service.DEFAULT_NEW_DAYS


# ---------------------------------------------------------------------------
# 「마지막 조회」는 두 출처 중 오래된 쪽 (0920 §4-B-5 · ISSUE-078-a)
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, moment: datetime | None) -> None:
        self.fetched_at = moment


def test_마지막_조회는_두_출처_중_오래된_쪽이다() -> None:
    """한쪽이 낡았으면 목록 전체가 그만큼 낡은 것이다.

    새것 쪽을 적으면 담당자가 낡은 줄을 방금 받은 것으로 읽는다.
    """
    older = NOW - timedelta(hours=9)
    assert opportunity_service._oldest_fetched_at(FakeResult(NOW), older) == older
    assert opportunity_service._oldest_fetched_at(FakeResult(older), NOW) == older


def test_한쪽만_있으면_그것을_쓴다() -> None:
    """기업마당은 저장된 것 없이 샘플로 답할 수 있다 — 그때는 시각이 정상적으로 없다."""
    assert opportunity_service._oldest_fetched_at(FakeResult(NOW), None) == NOW
    assert opportunity_service._oldest_fetched_at(None, NOW) == NOW


def test_둘_다_없으면_지어내지_않는다() -> None:
    assert opportunity_service._oldest_fetched_at(None, None) is None


def test_시간대가_없는_값도_비교한다() -> None:
    """저장된 옛 캐시에는 시간대가 없을 수 있다. 비교하다 터지면 목록이 통째로 죽는다."""
    naive = datetime(2026, 9, 16, 0, 0)
    assert opportunity_service._oldest_fetched_at(FakeResult(naive), NOW) == naive.replace(
        tzinfo=timezone.utc
    )


def test_숨긴_불가는_거르기_전에_센다() -> None:
    """예전에는 거른 «뒤»에 세어 언제나 0 이었다 — 화면이 「1,052건을 숨겼다」를 말할 수
    없었다 (0922 §4-D-2 · ISSUE-087)."""
    items = [item("a"), item("b", gate="FAIL"), item("c", gate="FAIL"), item("d", closed=True, gate="FAIL")]
    summary = summarize(items)
    # 마감 전 기준이다 — 마감된 불가는 「마감」으로 이미 세어진다.
    assert summary.blocked == 2
