"""procurement_service: 실호출 -> 매핑 -> 필터 -> 캐시 흐름 테스트.

계약(docs/real_data_migration.md §1)
    - 실호출 성공: source="g2b", 결과를 캐시에 저장
    - 실호출 실패 + 캐시 있음: source="cached", error 메시지 유지
    - 실호출 실패 + 캐시 없음: NoNoticeDataError
    - 캐시 파일에는 서비스키가 절대 들어가지 않는다 (CLAUDE.md 21)

async 서비스 함수는 pytest 비동기 플러그인 없이 `asyncio.run`으로 직접 돌린다
(백엔드 의존성을 늘리지 않기 위해).

14차부터 실호출은 **기본이 꺼짐**이다(ISSUE-120 · prompt_03 §4-A). 꺼진 상태에서는
`list_ai_candidates()` 가 수집기를 부르지 않고 저장된 캐시만 읽으므로, 「부르는 쪽」을 재는
테스트는 `live_fetch_on` 픽스처를 인자로 받아 **자기가 켰다고 서명에 적는다.** 바깥으로
나가지는 않는다 — 아래 테스트는 모두 `collect_notices` 를 가짜로 갈아 끼운다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, TypeVar

import pytest

from app.core.config import get_settings
from app.schemas.procurement import ProcurementNotice
from app.services import g2b_client, g2b_mapper, procurement_service
from app.services import procurement_service as ps
from app.services.opportunity_filter import classify, filter_candidates

T = TypeVar("T")


def run(awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)  # type: ignore[arg-type]


def _outcome(items: list[dict[str, Any]]) -> g2b_client.CollectOutcome:
    """수집기가 돌려주는 모양. 공고와 «어떻게 받았는가»를 함께 들고 다닌다."""
    return g2b_client.CollectOutcome(
        items=items,
        calls=len(items) and 1,
        method="시험 수집",
        keyword_totals={"AI": len(items)},
        truncated=(),
    )


def _fake_fetch(items: list[dict[str, Any]]):
    async def collect_notices(**_kwargs: Any) -> g2b_client.CollectOutcome:
        return _outcome(items)

    return collect_notices


def _failing_fetch(exc: Exception):
    async def collect_notices(**_kwargs: Any) -> g2b_client.CollectOutcome:
        raise exc

    return collect_notices


# --------------------------------------------------------------------------
# 실호출 성공 경로
# --------------------------------------------------------------------------


def test_live_fetch_reports_source_g2b_and_writes_cache(
    live_fetch_on: None,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    notice_cache_file: Path,
) -> None:
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))

    result = run(procurement_service.list_ai_candidates())

    assert result.source == "g2b"
    assert result.error is None
    assert result.total_fetched == len(raw_items)
    assert len(result.notices) >= 1
    assert notice_cache_file.exists()


def test_분류_none_으로_버린_공고는_수를_남긴다(
    live_fetch_on: None,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    notice_cache_file: Path,
) -> None:
    """39차 COLLECT-09 — 본업 · 수집 낱말이 없어 저장하지 않는 공고가 조용히 사라지지 않게 결과(→ 매일 받기 기록)에 수를 싣는다."""
    extra = dict(raw_items[0], bidNtceNo="R26BK09999999", bidNtceOrd="000", bidNtceNm="폐기물 처리 용역")
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch([*raw_items, extra]))

    result = run(procurement_service.list_ai_candidates())

    assert result.dropped_none >= 1
    assert all(view.notice.notice_no != "R26BK09999999-000" for view in result.notices)


def test_cache_round_trip_preserves_notices(
    live_fetch_on: None,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    # 캐시는 항상 전체 후보(low 포함)를 담는다. 비교 대상도 같은 범위로 맞춘다.
    saved = run(procurement_service.list_ai_candidates(include_low=True))

    loaded = procurement_service.load_cache()

    assert loaded is not None
    assert loaded.source == "cached"
    assert loaded.total_fetched == saved.total_fetched
    assert [v.notice.id for v in loaded.notices] == [v.notice.id for v in saved.notices]
    assert [v.match.tier for v in loaded.notices] == [v.match.tier for v in saved.notices]


def test_save_and_load_cache_directly(
    raw_items: list[dict[str, Any]], notice_cache_file: Path
) -> None:
    notices = g2b_mapper.map_notices(raw_items)
    views = [
        procurement_service.NoticeView(notice=n, match=m) for n, m in filter_candidates(notices)
    ]
    fetched_at = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

    procurement_service.save_cache(views, total_fetched=len(raw_items), fetched_at=fetched_at)
    loaded = procurement_service.load_cache()

    assert loaded is not None
    assert len(loaded.notices) == len(views)
    assert loaded.total_fetched == len(raw_items)
    payload = json.loads(notice_cache_file.read_text(encoding="utf-8"))
    assert payload["notices"][0]["candidate"]["method"] == "KEYWORD"


# --------------------------------------------------------------------------
# 캐시 fallback
# --------------------------------------------------------------------------


def test_falls_back_to_cache_when_client_raises(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, raw_items: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    live = run(procurement_service.list_ai_candidates())

    monkeypatch.setattr(
        g2b_client, "collect_notices", _failing_fetch(g2b_client.G2BApiError("07", "요청 제한"))
    )
    # refresh=True 여야 캐시를 건너뛰고 실제로 클라이언트를 호출한다(그리고 실패 → 캐시 폴백).
    cached = run(procurement_service.list_ai_candidates(refresh=True))

    assert cached.source == "cached"
    assert cached.error is not None and "07" in cached.error
    assert [v.notice.id for v in cached.notices] == [v.notice.id for v in live.notices]


def test_key_missing_also_falls_back_to_cache(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, raw_items: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    run(procurement_service.list_ai_candidates())

    monkeypatch.setattr(
        g2b_client,
        "collect_notices",
        _failing_fetch(g2b_client.G2BKeyMissingError("no key")),
    )
    # refresh=True 여야 캐시를 건너뛰고 실호출을 시도한다(키 없음 → 캐시 폴백).
    cached = run(procurement_service.list_ai_candidates(refresh=True))
    assert cached.source == "cached"


def test_실호출이_실패하면_잠시_다시_부르지_않고_새로_받기는_부른다(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, raw_items: list[dict[str, Any]]
) -> None:
    """11-01 — 조달청 점검 중 화면을 열 때마다 21번씩 다시 불러 대시보드가 30초 넘게 걸렸다."""
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    run(procurement_service.list_ai_candidates())
    calls: list[int] = []
    failing = _failing_fetch(g2b_client.G2BClientError("조달청(나라장터)이 목록 대신 안내 화면을 보냈습니다"))

    async def counted(**kwargs: Any) -> g2b_client.CollectOutcome:
        calls.append(1)
        return await failing(**kwargs)

    monkeypatch.setattr(g2b_client, "collect_notices", counted)
    first = run(procurement_service.list_ai_candidates(ttl=0))
    second = run(procurement_service.list_ai_candidates(ttl=0))
    assert first.source == second.source == "cached"
    assert second.error == first.error and "안내 화면" in (second.error or "")
    assert len(calls) == 1

    run(procurement_service.list_ai_candidates(ttl=0, refresh=True))
    assert len(calls) == 2

    monkeypatch.setattr(procurement_service, "FAILED_RETRY_SECONDS", -1)
    run(procurement_service.list_ai_candidates(ttl=0))
    assert len(calls) == 3


def test_실패_기억은_다른_기간의_성공과_다른_프로세스의_저장에도_풀린다(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, raw_items: list[dict[str, Any]], notice_cache_file: Path
) -> None:
    """11-01 독립 검토 — 상세(14일)의 실패 기억이 목록(30일) 성공 · 매일 받기(다른 프로세스) 저장 뒤에도 10분 남았다."""
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    run(procurement_service.list_ai_candidates(days=30))
    monkeypatch.setattr(g2b_client, "collect_notices", _failing_fetch(g2b_client.G2BClientError("안내 화면")))
    assert run(procurement_service.list_ai_candidates(days=14, ttl=0)).error
    assert run(procurement_service.list_ai_candidates(days=30, ttl=0)).error

    # 같은 프로세스에서 다른 기간이 성공하면 모든 기억이 지워진다
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    run(procurement_service.list_ai_candidates(days=30, refresh=True))
    assert procurement_service._FAILED == {}

    # 다른 프로세스가 저장본을 바꾸면(시각 · 크기) 기억을 쓰지 않고 다시 부른다
    calls: list[int] = []
    failing = _failing_fetch(g2b_client.G2BClientError("안내 화면"))

    async def counted(**kwargs: Any) -> g2b_client.CollectOutcome:
        calls.append(1)
        return await failing(**kwargs)

    monkeypatch.setattr(g2b_client, "collect_notices", counted)
    run(procurement_service.list_ai_candidates(days=14, ttl=0))
    run(procurement_service.list_ai_candidates(days=14, ttl=0))
    assert len(calls) == 1
    notice_cache_file.write_text(notice_cache_file.read_text(encoding="utf-8") + " ", encoding="utf-8")
    run(procurement_service.list_ai_candidates(days=14, ttl=0))
    assert len(calls) == 2


def test_raises_when_fetch_fails_and_no_cache_exists(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, notice_cache_file: Path
) -> None:
    """「**실호출이 실패했고** 캐시도 없다」를 잰다 — 그래서 스위치를 켜야 한다.

    켜지 않으면 이 테스트는 **통과하지만 다른 것을 잰다.** 실호출이 꺼져 있으면
    `_failing_fetch` 는 한 번도 불리지 않고 고정 모드 갈래가 먼저 같은 예외를 던진다 —
    「장애가 나도 캐시가 없으면 못 연다」가 아니라 「캐시가 없으면 못 연다」를 재게 된다.
    같은 초록이지만 재던 계약이 사라진 자리다 (prompt_03 §4-A-3).
    """
    assert not notice_cache_file.exists()
    called: list[str] = []

    async def _boom(*args: object, **kwargs: object) -> object:
        called.append("collect_notices")
        return await _failing_fetch(g2b_client.G2BApiError("99", "장애"))(*args, **kwargs)

    monkeypatch.setattr(g2b_client, "collect_notices", _boom)

    with pytest.raises(procurement_service.NoNoticeDataError):
        run(procurement_service.list_ai_candidates())

    # 「부르려다 실패했다」까지가 이 테스트의 계약이다. 이 줄이 거짓 통과를 막는다.
    assert called == ["collect_notices"], "수집기를 부르지도 않고 예외가 났다"


def test_load_cache_returns_none_for_missing_or_broken_file(notice_cache_file: Path) -> None:
    assert procurement_service.load_cache() is None

    notice_cache_file.parent.mkdir(parents=True, exist_ok=True)
    notice_cache_file.write_text("{not json", encoding="utf-8")
    assert procurement_service.load_cache() is None

    notice_cache_file.write_text('{"notices": [{"wrong": 1}]}', encoding="utf-8")
    assert procurement_service.load_cache() is None


# --------------------------------------------------------------------------
# 보안: 캐시에 서비스키가 남지 않는다
# --------------------------------------------------------------------------


def test_cache_file_never_contains_the_service_key(
    live_fetch_on: None,
    monkeypatch: pytest.MonkeyPatch,
    raw_items: list[dict[str, Any]],
    notice_cache_file: Path,
) -> None:
    # 캐시 파일 자체가 실호출 결과로 쓰여야 검사할 내용이 생긴다 — 그래서 켠다.
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    run(procurement_service.list_ai_candidates())

    content = notice_cache_file.read_text(encoding="utf-8")
    key = get_settings().data_go_kr_service_key
    if key:
        assert key not in content
    # 키를 나르는 파라미터 이름 자체가 남아서도 안 된다.
    assert "serviceKey" not in content
    assert "ServiceKey" not in content


# --------------------------------------------------------------------------
# 단건 조회
# --------------------------------------------------------------------------


def test_get_notice_finds_by_id_and_returns_none_otherwise(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, raw_items: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    listed = run(procurement_service.list_ai_candidates())
    target = listed.notices[0].notice.id

    found = run(procurement_service.get_notice(target))
    assert found is not None
    assert found.notice.id == target

    assert run(procurement_service.get_notice("g2b-NOPE-000")) is None


def test_result_to_dict_matches_api_contract(
    live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, raw_items: list[dict[str, Any]]
) -> None:
    # `collected_by`·`collect_calls` 는 수집기를 실제로 부른 결과에서만 채워진다.
    monkeypatch.setattr(g2b_client, "collect_notices", _fake_fetch(raw_items))
    payload = run(procurement_service.list_ai_candidates()).to_dict()

    assert set(payload) == {
        "source",
        "g2b_api_configured",
        # 시연 고정 모드인지 (ISSUE-062). 키가 있어도 «부르지 않는» 상태가 있으므로
        # `source` 와 `g2b_api_configured` 만으로는 화면이 그것을 구분하지 못한다.
        "frozen",
        "fetched_at",
        "total_fetched",
        "count",
        "error",
        # 「어떻게 받았는가」와 「몇 번 불렀는가」 (0920 §4-A-3). 화면의 「데이터 상태」가
        # 이 둘을 그대로 적는다 — 수집 방식을 고친 뒤로 그것이 화면에서 보이지 않으면
        # 담당자는 여전히 옛 방식으로 받는 줄 안다.
        "collected_by",
        "collect_calls",
        "notices",
    }
    assert payload["count"] == len(payload["notices"])
    assert payload["collected_by"] == "시험 수집"
    first = payload["notices"][0]
    # 개발 공고를 수집하면서 두 필드가 늘었다 (추가만 했고 지운 키는 없다).
    assert set(first["candidate"]) == {
        "tier",
        "matched_ai_keywords",
        "matched_work_keywords",
        "matched_dev_keywords",
        "oversized_reason",
        "core_terms",
        "low_reason",
        "method",
    }


# --------------------------------------------------------------------------
# 데모 고정 공고
# --------------------------------------------------------------------------


def make_view(notice_no: str, title: str = "생성형 AI 활용 실무교육 운영 용역"):
    notice = ProcurementNotice(
        id=f"g2b-{notice_no}",
        notice_no=notice_no,
        title=title,
        agency="테스트기관",
        published_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    return ps.NoticeView(notice=notice, match=classify(notice))


def test_고정_공고가_빠지면_저장소에서_되살린다(tmp_path, monkeypatch) -> None:
    pinned = make_view("R26BK09999999-000")
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "pinned.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))
    ps.save_pinned([pinned])

    merged = ps._merge_pinned([make_view("R26BK00000001-000")])

    assert len(merged) == 2
    assert any(ps._pin_key(v) == "R26BK09999999" for v in merged)


def test_이미_들어있는_고정_공고는_두_번_붙이지_않는다(tmp_path, monkeypatch) -> None:
    pinned = make_view("R26BK09999999-000")
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "pinned.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))
    ps.save_pinned([pinned])

    merged = ps._merge_pinned([pinned])

    assert len(merged) == 1


def test_캐시에_이미_있는_고정_공고에도_표가_붙는다(tmp_path, monkeypatch) -> None:
    """**시연 당일 선택기에 「시연용 (마감)」 그룹이 그려지는가** (ISSUE-134 · §4-C).

    그 그룹은 `pinned` 가 참인 공고만 묶는다. 예전에는 `pinned` 가 「저장소에서
    되살렸는가」였고, 네 건이 캐시에 이미 들어 있으면 되살릴 일이 없어 표가 안 붙었다 —
    그래서 그룹이 아예 그려지지 않았다. 체크리스트 3절과 `demo_preflight` 안내가 그
    그룹을 가리키니, 담당자가 그 문장대로 찾으면 없다.

    커밋된 캐시를 되돌린 직후 실측으로 목록 요약의 `closed_pinned` 가 4 → 0 이었다.
    여기서 재는 것은 **되살리지 않아도** 표가 붙는가다.
    """
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "pinned.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))
    # 저장소는 비어 있다 — 되살릴 길이 없는 상태를 일부러 만든다.
    in_cache = make_view("R26BK09999999-000")
    other = make_view("R26BK00000001-000")
    assert in_cache.pinned is False

    merged = ps._merge_pinned([in_cache, other])

    by_key = {ps._pin_key(v): v for v in merged}
    assert len(merged) == 2, "되살리려 하지 않아야 한다"
    assert by_key["R26BK09999999"].pinned is True, "고정 목록에 있는데 표가 없다"
    assert by_key["R26BK00000001"].pinned is False


def test_차수가_올라간_고정_공고도_같은_공고로_본다(tmp_path, monkeypatch) -> None:
    """정정·재공고가 나면 차수만 올라간다(-000 → -002). 공고번호는 그대로다."""
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "pinned.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))

    merged = ps._merge_pinned([make_view("R26BK09999999-002")])

    assert merged[0].pinned is True


def test_되살린_고정_공고는_실시간으로_보이지_않는다(tmp_path, monkeypatch) -> None:
    """목록 전체의 source 는 "g2b" 라도 이 행만은 방금 받아온 것이 아니다.

    마감이 지났거나 내용이 바뀌었을 수 있는 저장본이므로, 화면이 「나라장터 실시간」으로
    적으면 담당자를 속이는 것이 된다.
    """
    pinned = make_view("R26BK09999999-000")
    live = make_view("R26BK00000001-000")
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "pinned.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))
    ps.save_pinned([pinned])

    merged = ps._merge_pinned([live])

    by_key = {ps._pin_key(v): v for v in merged}
    assert by_key["R26BK09999999"].pinned is True
    assert by_key["R26BK00000001"].pinned is False
    # 화면이 읽는 곳까지 전달돼야 뜻이 있다.
    assert by_key["R26BK09999999"].to_dict()["pinned"] is True


def test_순위를_매겨도_고정_공고_표시가_지워지지_않는다(tmp_path, monkeypatch) -> None:
    """rank_notices 가 NoticeView 를 다시 만들면서 표시를 잃던 자리."""
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "pinned.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))
    ps.save_pinned([make_view("R26BK09999999-000")])

    ranked = ps.rank_notices(ps._merge_pinned([make_view("R26BK00000001-000")]))

    assert any(v.pinned for v in ranked)
    assert all(v.rank is not None for v in ranked)


def test_캐시를_거쳐도_고정_공고_표시가_남는다(notice_cache_file: Path) -> None:
    """되살린 공고는 캐시에도 함께 저장된다. 표시를 안 남기면 다음 조회에서 실시간이 된다."""
    base = make_view("R26BK09999999-000")
    pinned = ps.NoticeView(notice=base.notice, match=base.match, pinned=True)
    ps.save_cache(
        [pinned, make_view("R26BK00000001-000")],
        total_fetched=2,
        fetched_at=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )

    cached = ps.load_cache()

    assert cached is not None
    assert [v.pinned for v in cached.notices] == [True, False]


def test_저장소가_없으면_아무것도_만들어내지_않는다(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ps, "PINNED_FILE", tmp_path / "없는파일.json")
    monkeypatch.setattr(ps, "PINNED_NOTICE_NOS", ("R26BK09999999",))

    merged = ps._merge_pinned([make_view("R26BK00000001-000")])

    assert len(merged) == 1


# --------------------------------------------------------------------------
# 검토 우선순위 (rank)
# --------------------------------------------------------------------------


def test_추천_점수가_높은_순으로_순위를_매긴다() -> None:
    from datetime import timedelta

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)

    def notice(no: str, title: str, days: int, budget: int) -> ProcurementNotice:
        return ProcurementNotice(
            id=f"g2b-{no}",
            notice_no=no,
            title=title,
            agency="테스트기관",
            published_at=now,
            deadline_at=now + timedelta(days=days),
            budget=budget,
            region="광주광역시",
        )

    # 「AI 시스템 구축」은 담당자 결정(2026-10-16)으로 개발 갈래 후보가 됐다 — 약한 쪽은 여전히 후보 아닌 장비 · 서버 구축
    weak = notice("R26BK00000001-000", "AI GPU 서버 구축", 30, 100_000_000)
    strong = notice("R26BK00000002-000", "생성형 AI 활용 실무교육 운영", 30, 100_000_000)

    ranked = ps.rank_notices([make_view_from(weak), make_view_from(strong)])

    assert [v.rank for v in ranked] == [1, 2]
    assert ranked[0].notice.id == strong.id, "키워드 등급이 높은 공고가 1위여야 한다"


#: 순위의 「지금」(storage.utc_now)과 공고 날짜를 같은 시계로 — 실제 시계로 만들면 시계를 앞당긴 날 둘 다 마감이 된다(26차 ISSUE-146).
PINNED_NOW = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)  # KST 정오


def test_마감이_지난_공고는_점수가_높아도_뒤로_보낸다(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    from app.core import storage

    monkeypatch.setattr(storage, "utc_now", lambda: PINNED_NOW)
    now = PINNED_NOW

    def notice(no: str, days: int) -> ProcurementNotice:
        return ProcurementNotice(
            id=f"g2b-{no}",
            notice_no=no,
            title="생성형 AI 활용 실무교육 운영",
            agency="테스트기관",
            published_at=now - timedelta(days=40),
            deadline_at=now + timedelta(days=days),
            budget=100_000_000,
            region="광주광역시",
        )

    expired = make_view_from(notice("R26BK00000001-000", -5))
    live = make_view_from(notice("R26BK00000002-000", 20))

    ranked = ps.rank_notices([expired, live])

    assert ranked[0].notice.id.endswith("0002-000"), "마감이 남은 공고가 앞에 와야 한다"
    assert ranked[0].rank == 1 and ranked[1].rank == 2


def test_순위는_1부터_빠짐없이_매겨진다() -> None:
    views = [make_view(f"R26BK0000000{i}-000") for i in range(1, 5)]
    ranked = ps.rank_notices(views)
    assert [v.rank for v in ranked] == [1, 2, 3, 4]


def test_to_dict에_rank가_실린다() -> None:
    ranked = ps.rank_notices([make_view("R26BK00000001-000")])
    assert ranked[0].to_dict()["rank"] == 1


def make_view_from(notice: ProcurementNotice) -> ps.NoticeView:
    return ps.NoticeView(notice=notice, match=classify(notice))


def test_사업영역_밖_공고는_정상_공고_뒤로_보낸다(monkeypatch: pytest.MonkeyPatch) -> None:
    """감리 공고는 gate_reason에 '후순위로 내렸습니다'라고 적힌다.

    등급만 D로 내리고 정렬은 점수순으로 두면 감리 공고가 교육 공고보다
    위에 남아 표시와 동작이 어긋난다.
    """
    from datetime import timedelta

    from app.core import storage

    monkeypatch.setattr(storage, "utc_now", lambda: PINNED_NOW)
    now = PINNED_NOW

    def notice(no: str, title: str) -> ProcurementNotice:
        return ProcurementNotice(
            id=f"g2b-{no}",
            notice_no=no,
            title=title,
            agency="테스트기관",
            published_at=now - timedelta(days=1),
            deadline_at=now + timedelta(days=20),
            budget=100_000_000,
            region="광주광역시",
        )

    audit = make_view_from(
        notice("R26BK00000001-000", "AI·빅데이터 분석 기반 시스템 구축 위탁감리")
    )
    teaching = make_view_from(
        notice("R26BK00000002-000", "2026 강경상업고 AI 실무 교재 위탁 개발용역")
    )
    expired_notice = notice("R26BK00000003-000", "생성형 AI 활용 실무교육 운영")
    expired_notice.deadline_at = now - timedelta(days=3)
    expired = make_view_from(expired_notice)

    ranked = ps.rank_notices([audit, teaching, expired])
    order = [v.notice.id for v in ranked]

    assert order.index(teaching.notice.id) < order.index(audit.notice.id), (
        "사업영역 밖 감리 공고가 교육 공고보다 앞에 오면 안 된다"
    )
    assert order[-1] == expired.notice.id, "마감 경과 공고가 마지막이어야 한다"


# ---------------------------------------------------------------------------
# 담당자 연락처 마스킹 (캐시 파일은 Git 에 커밋된다)
# ---------------------------------------------------------------------------


def test_mask_contact_fields_hides_phone_and_email_only() -> None:
    """담당자 전화·이메일만 가린다. 이름·코드·파일명은 건드리지 않는다.

    긴 숫자열을 가진 품목코드·접수번호를 전화번호로 오인해 지우면 화면이 상한다.
    담당자 **이름**은 입찰 실무에서 쓰이므로 남긴다 — 이 테스트가 그 경계를 못박는다.
    """
    payload = {
        "notices": [
            {
                "notice": {
                    "raw_data": {
                        "ntceInsttOfclNm": "홍길동",
                        "exctvNm": "홍길동",
                        "crdtrNm": "○○청장",
                        "ntceInsttOfclTelNo": "031-000-0000",
                        "ntceInsttOfclEmailAdrs": "someone@example.go.kr",
                        "dminsttOfclEmailAdrs": "",
                        "purchsObjPrdctList": "[1^8010169901^정보시스템감리서비스]",
                        "refNo": "R26BK01687776-000",
                        "bdgtAmt": 1050000000,
                    }
                }
            }
        ]
    }
    clean = ps.mask_contact_fields(payload)
    raw = clean["notices"][0]["notice"]["raw_data"]

    assert raw["ntceInsttOfclTelNo"] == "[전화 원문 확인]"
    assert raw["ntceInsttOfclEmailAdrs"] == "[이메일 원문 확인]"
    # 빈 값은 그대로 둔다 — 「없음」과 「가림」은 다른 정보다
    assert raw["dminsttOfclEmailAdrs"] == ""
    # 이름·코드·숫자는 그대로
    assert raw["ntceInsttOfclNm"] == "홍길동" and raw["exctvNm"] == "홍길동"
    assert raw["crdtrNm"] == "○○청장"
    assert raw["purchsObjPrdctList"] == "[1^8010169901^정보시스템감리서비스]"
    assert raw["refNo"] == "R26BK01687776-000"
    assert raw["bdgtAmt"] == 1050000000
    # 원본은 바뀌지 않는다
    assert payload["notices"][0]["notice"]["raw_data"]["ntceInsttOfclTelNo"] == "031-000-0000"


def test_mask_contact_text_hides_numbers_inside_free_text() -> None:
    """자유 서술 안의 연락처도 가린다 — 연락처를 실어 나르는 필드를 미리 다 알 수 없다.

    실측(2026-09-10 재수집): `dcmtgOprtnPlce` 에 「시설사업팀 ○○○(043-871-5096)」가 들어왔다.
    필드 이름 목록에 없던 필드라 한 겹(CONTACT_MASKS)만으로는 막지 못했다.
    """
    assert ps.mask_contact_text("시설사업팀 홍길동(043-871-5096)") == "시설사업팀 홍길동([전화 원문 확인])"
    assert ps.mask_contact_text("문의 abc@korea.kr") == "문의 [이메일 원문 확인]"
    # 공고번호·날짜·금액은 건드리지 않는다 — 지우면 화면이 상한다.
    for keep in ("공고번호 R26BK01718593-000", "마감 2026-09-21 18:00", "예산 94,554,000원"):
        assert ps.mask_contact_text(keep) == keep


def test_mask_contact_fields_reaches_unknown_fields() -> None:
    payload = {"raw_data": {"dcmtgOprtnPlce": "시설사업팀 홍길동(043-871-5096)"}}
    clean = ps.mask_contact_fields(payload)
    assert clean["raw_data"]["dcmtgOprtnPlce"] == "시설사업팀 홍길동([전화 원문 확인])"


def test_tracked_procurement_caches_carry_no_contact_details() -> None:
    """Git 에 커밋된 캐시 파일에 담당자 전화·이메일이 남아 있지 않다.

    배포 스냅샷은 이미 같은 값을 가린다. 원본 캐시만 가리지 않으면 앞뒤가 맞지 않고,
    스냅샷을 다시 뜰 때마다 여기서 다시 흘러든다.
    """
    import re

    repo_root = Path(__file__).resolve().parents[2]
    cache_dir = repo_root / "data" / "public" / "sample_procurements"
    if not cache_dir.exists():
        pytest.skip("캐시 폴더 없음")

    tel = re.compile(r"(?<!\d)0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    checked = 0
    for path in sorted(cache_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        leaked: list[str] = []

        # **모든** 문자열을 본다. 알려진 연락처 필드만 검사하면 코드와 같은 맹점이 생긴다 —
        # 실제로 `dcmtgOprtnPlce`(설명회 장소)에 「시설사업팀 ○○○(043-...)」가 들어와 있었는데
        # 그 필드가 CONTACT_MASKS 에 없어서 이 테스트가 통과해 버렸다 (2026-09-10).
        def walk(value: Any, key: str | None = None) -> None:
            if isinstance(value, str):
                if tel.search(value) or email.search(value):
                    leaked.append(f"{path.name}:{key}")
            elif isinstance(value, dict):
                for k, item in value.items():
                    walk(item, k)
            elif isinstance(value, list):
                for item in value:
                    walk(item, key)

        walk(payload)
        assert not leaked, f"연락처가 남아 있다: {sorted(set(leaked))}"
        checked += 1
    assert checked, "검사한 캐시 파일이 없다"


# --------------------------------------------------------------------------
# 차수 묶기 (정정·재공고)
# --------------------------------------------------------------------------


def _n(notice_no: str, title: str = "AI 교육 용역") -> ProcurementNotice:
    return ProcurementNotice(
        id=f"g2b-{notice_no}",
        notice_no=notice_no,
        title=title,
        agency="테스트기관",
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def test_collapse_revisions_keeps_only_the_latest_order() -> None:
    """같은 공고의 차수는 최신 하나만 남는다.

    정정·재공고는 공고번호가 같고 차수만 오른다. 묶지 않으면 한 사업이 3건으로 세어져
    「29건」 같은 숫자가 부풀고, 화면마다 자르는 개수가 달라 어디서는 보이고 어디서는 안 보인다.
    """
    collapsed = procurement_service.collapse_revisions(
        [_n("R26BK01701257-001"), _n("R26BK01701257-003"), _n("R26BK01701257-002")]
    )
    assert len(collapsed) == 1
    assert collapsed[0].notice_no == "R26BK01701257-003", "가장 높은 차수를 남긴다"
    assert collapsed[0].revision_count == 3, "몇 건이 접혔는지 화면이 말할 수 있어야 한다"


def test_collapse_revisions_keeps_distinct_notices_and_order() -> None:
    """다른 공고는 그대로 두고, 목록 순서도 흐트러뜨리지 않는다."""
    collapsed = procurement_service.collapse_revisions(
        [_n("AAA-000", "첫째"), _n("BBB-000", "둘째"), _n("AAA-001", "첫째"), _n("CCC-000", "셋째")]
    )
    assert [n.notice_no for n in collapsed] == ["AAA-001", "BBB-000", "CCC-000"]
    assert [n.revision_count for n in collapsed] == [2, 1, 1]


def test_collapse_revisions_handles_unreadable_order() -> None:
    """차수를 읽을 수 없어도 죽지 않는다 — 읽히는 쪽을 최신으로 본다."""
    collapsed = procurement_service.collapse_revisions([_n("XXX-abc"), _n("XXX-002")])
    assert len(collapsed) == 1
    assert collapsed[0].notice_no == "XXX-002"


def test_같은_기간을_동시에_부르면_받기는_한_번(live_fetch_on: None, monkeypatch: pytest.MonkeyPatch, notice_cache_file: Path) -> None:
    """2.9.1 검토 — 입찰 분석 첫 보기에서 역량 판정 · 첨부 목록 요청이 같은 순간 get_notice 를 불러 나라장터 받기가 두 번 돌았다.
    뒤 요청은 잠금 안에서 앞 요청이 채운 메모를 읽는다(바깥 호출 0 — collect_candidates 는 가짜)."""
    calls: list[int] = []

    async def fake_collect(**kwargs: Any) -> procurement_service.Collected:
        calls.append(int(kwargs["days"]))
        await asyncio.sleep(0.05)
        return procurement_service.Collected(notices=[], superseded={}, calls=1, method="시험", total_fetched=0)

    monkeypatch.setattr(procurement_service, "collect_candidates", fake_collect)

    async def both() -> None:
        await asyncio.gather(procurement_service.list_ai_candidates(days=14), procurement_service.list_ai_candidates(days=14))

    asyncio.run(both())
    assert calls == [14]
    # 다른 기간은 따로 받는다 · 「새로 받기」(refresh)는 메모를 건너뛴다
    asyncio.run(procurement_service.list_ai_candidates(days=30))
    asyncio.run(procurement_service.list_ai_candidates(days=14, refresh=True))
    assert calls == [14, 30, 14]
