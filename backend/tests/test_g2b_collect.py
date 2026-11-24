"""공고명 키워드 수집 (0920.md §4-A-1 · ISSUE-072).

## 무엇을 고치려고 만든 경로인가

옛 수집기(`fetch_bid_notices`)는 「나라장터는 공고게시일 오름차순으로 주니 마지막 페이지가
최신이다」라고 믿고 뒤에서 600건을 받았다. **그 가정이 틀렸다.** 실제 정렬은 «용역구분 →
게시일» 이라, 30일 창 12,807건 중 뒤쪽 600건은 전부 기술용역 꼬리였다. AI 교육·컨설팅
공고는 **전부 일반용역**이라 구조적으로 한 건도 들어오지 않았다 — 마감 전 후보 117건 중
앱이 아는 것은 4건뿐이었다 (docs/reports/2026-09-20_qa_recheck5.md §1-3).

여기서 지키는 약속은 넷이다.

1. **일반용역 뒤에 기술용역이 와도 후보를 놓치지 않는다.** 정렬을 가정하지 않는다.
2. 호출 예산을 지킨다. 다 못 받았으면 **말한다**(조용히 자르지 않는다).
3. 같은 공고를 여러 키워드에서 물어와도 한 건으로 센다.
4. 한 건도 못 받으면 예외를 올린다 — 호출자가 캐시로 넘어가는 계약이다.

네트워크는 부르지 않는다. `fetch_bid_notices_raw` 를 가짜로 바꿔 쓴다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.services import g2b_client, opportunity_filter, procurement_service


def item(no: str, *, order: str = "000", title: str = "생성형 AI 교육 운영 위탁") -> dict[str, Any]:
    return {"bidNtceNo": no, "bidNtceOrd": order, "bidNtceNm": title}


class Recorder:
    """어떤 키워드를 몇 페이지 불렀는지 기록하는 가짜 나라장터.

    (2.8.1) 수집기는 30일을 7일 창 다섯으로 나눠 **새 창부터** 부른다. 공고는 **가장 새 창(첫 호출의 창)에만** 있고
    그 앞 창은 0건이라고 흉내 낸다 — 창마다 같은 공고를 돌려주면 건수 · 호출 수가 뜻을 잃는다.
    조달청 상한(시작일 포함 7일)을 넘는 창이 오면 실제처럼 거절한다."""

    def __init__(self, pages: dict[str, list[list[dict[str, Any]]]], totals: dict[str, int]) -> None:
        self.pages = pages
        self.totals = totals
        self.calls: list[tuple[str, int]] = []
        self.params: list[dict[str, Any]] = []
        self.windows: list[tuple[Any, Any]] = []
        self.newest_end: Any = None

    async def __call__(
        self, *, begin, end, page_no=1, num_rows=100, operation="", extra_params=None
    ) -> dict[str, Any]:
        params = dict(extra_params or {})
        self.params.append(params)
        self.windows.append((begin, end))
        keyword = params.get(g2b_client.PARAM_NOTICE_NAME, "")
        self.calls.append((keyword, page_no))
        if (end.astimezone(g2b_client.KST).date() - begin.astimezone(g2b_client.KST).date()).days >= g2b_client.MAX_WINDOW_DAYS:
            raise g2b_client.G2BClientError("G2B API error 07: 입력범위값 초과 에러")
        if self.newest_end is None:
            self.newest_end = end
        if end != self.newest_end:
            return {"totalCount": 0, "items": []}
        pages = self.pages.get(keyword, [])
        items = pages[page_no - 1] if 0 < page_no <= len(pages) else []
        return {"totalCount": self.totals.get(keyword, len(items)), "items": items}


def collect(recorder: Recorder, **kwargs: Any) -> g2b_client.CollectOutcome:
    original = g2b_client.fetch_bid_notices_raw
    g2b_client.fetch_bid_notices_raw = recorder  # type: ignore[assignment]
    try:
        return asyncio.run(g2b_client.collect_notices(**kwargs))
    finally:
        g2b_client.fetch_bid_notices_raw = original  # type: ignore[assignment]


def test_공고명과_마감_제외를_함께_보낸다() -> None:
    """이 두 파라미터가 이번 수집의 뼈대다. 실측으로 확인한 이름이다."""
    recorder = Recorder({"AI": [[item("R1")]]}, {"AI": 1})
    collect(recorder, keywords=["AI"], days=30)
    sent = recorder.params[0]
    assert sent[g2b_client.PARAM_NOTICE_NAME] == "AI"
    assert sent[g2b_client.PARAM_CLOSED_EXCLUDED] == "Y"


def test_마감_포함을_고르면_그_파라미터를_빼고_부른다() -> None:
    recorder = Recorder({"AI": [[item("R1")]]}, {"AI": 1})
    collect(recorder, keywords=["AI"], days=30, closed_excluded=False)
    assert g2b_client.PARAM_CLOSED_EXCLUDED not in recorder.params[0]


def test_일반용역_뒤에_기술용역이_와도_후보를_놓치지_않는다() -> None:
    """정렬을 가정하지 않는 것이 이 수집기의 존재 이유다 (ISSUE-072).

    옛 경로는 「뒤쪽이 최신」이라고 믿고 마지막 페이지부터 받았다. 실제로는 용역구분이
    먼저라, 일반용역 9,078건 뒤에 기술용역이 다시 시작한다. 그 구조를 그대로 흉내 낸다 —
    찾는 공고(일반용역)는 **맨 앞**에 있고 뒤쪽은 전부 기술용역이다.
    """
    wanted = item("R26BK01716907", title="가천대 AI부트캠프 생성형 AI 활용 교육 기획·운영 위탁 — 재공고")
    general = [wanted] + [item(f"G{i}", title=f"AI 교육 운영 {i}") for i in range(99)]
    technical = [item(f"T{i}", title=f"AI 내진성능평가 용역 {i}") for i in range(100)]
    recorder = Recorder({"AI": [general, technical]}, {"AI": 200})

    outcome = collect(recorder, keywords=["AI"], days=30)

    got = {i["bidNtceNo"] for i in outcome.items}
    assert "R26BK01716907" in got, "찾는 공고가 앞 페이지에 있어도 받아야 한다"
    assert len(outcome.items) == 200, "두 페이지를 모두 받는다"
    assert outcome.truncated == ()


def test_호출_예산을_지키고_다_못_받으면_말한다() -> None:
    """조용히 자르면 다음 사람이 「그 공고는 원래 없다」로 읽는다."""
    recorder = Recorder(
        {"AI": [[item(f"A{i}") for i in range(100)]], "인공지능": [[item("B1")]]},
        {"AI": 900, "인공지능": 1},
    )
    outcome = collect(recorder, keywords=["AI", "인공지능"], days=30, max_calls=2)

    assert outcome.calls == 2
    assert recorder.calls == [("AI", 1), ("인공지능", 1)], "가장 새 창부터 낱말마다 한 쪽"
    # AI 는 900건 중 100건만 · 인공지능은 예산이 모자라 앞 창 넷을 부르지 못했다 — 둘 다 말한다
    assert outcome.truncated == ("AI", "인공지능")


def test_남은_예산은_못_받은_건수가_많은_키워드부터_쓴다() -> None:
    recorder = Recorder(
        {
            "AI": [[item(f"A{i}") for i in range(100)], [item(f"A2{i}") for i in range(93)]],
            "인공지능": [[item("B1")]],
        },
        {"AI": 193, "인공지능": 1},
    )
    # 낱말 둘 × 창 다섯 = 첫 쪽 10회 · 남은 1회가 AI 2쪽
    outcome = collect(recorder, keywords=["AI", "인공지능"], days=30, max_calls=11)

    assert recorder.calls[:2] == [("AI", 1), ("인공지능", 1)], "먼저 키워드마다 한 페이지씩"
    assert ("AI", 2) in recorder.calls, "남은 예산은 덜 받은 키워드에 준다"
    assert outcome.truncated == (), "193건을 두 페이지로 다 받았다"


def test_같은_공고가_여러_키워드에_걸려도_한_건이다() -> None:
    """「생성형 AI 교육」은 AI 에도 생성형에도 걸린다. 두 건으로 세면 화면 숫자가 부푼다."""
    both = item("R1", title="생성형 AI 활용 교육 운영")
    recorder = Recorder({"AI": [[both]], "생성형": [[both]]}, {"AI": 1, "생성형": 1})
    outcome = collect(recorder, keywords=["AI", "생성형"], days=30)
    assert len(outcome.items) == 1


def test_차수가_다르면_다른_공고로_받는다() -> None:
    """차수 병합은 수집기가 아니라 `split_revisions` 가 한다. 여기서는 둘 다 받아 둔다."""
    recorder = Recorder(
        {"AI": [[item("R1", order="000"), item("R1", order="001")]]}, {"AI": 2}
    )
    outcome = collect(recorder, keywords=["AI"], days=30)
    assert len(outcome.items) == 2


def test_한_건도_못_받으면_예외를_올린다() -> None:
    """조용히 빈 목록을 돌려주면 캐시가 빈 목록으로 덮어써진다."""
    recorder = Recorder({}, {})
    with pytest.raises(g2b_client.G2BClientError):
        collect(recorder, keywords=["AI"], days=30)


def test_한_키워드가_실패해도_나머지는_받는다() -> None:
    class Flaky(Recorder):
        async def __call__(self, **kwargs: Any) -> dict[str, Any]:
            keyword = dict(kwargs.get("extra_params") or {}).get(g2b_client.PARAM_NOTICE_NAME, "")
            if keyword == "AI":
                self.calls.append((keyword, kwargs.get("page_no", 1)))
                raise g2b_client.G2BClientError("timeout")
            return await super().__call__(**kwargs)

    recorder = Flaky({"인공지능": [[item("B1")]]}, {"인공지능": 1})
    outcome = collect(recorder, keywords=["AI", "인공지능"], days=30)
    assert len(outcome.items) == 1
    assert outcome.calls == 2 * 5, "실패한 호출도 한도를 썼으므로 센다(낱말 둘 × 창 다섯)"
    assert outcome.failed == ("AI",)


def test_수집_방식을_한국어_한_줄로_말한다() -> None:
    """화면의 「데이터 상태」가 이 문장을 그대로 적는다 (0920 §4-A-3)."""
    recorder = Recorder({"AI": [[item("R1")]]}, {"AI": 1})
    outcome = collect(recorder, keywords=["AI", "인공지능"], days=30)
    assert outcome.method == "공고명 키워드 2개 · 마감 제외 · 최근 30일"
    assert not any(ch.isascii() and ch.isalpha() for ch in outcome.method)


def test_받아_온_공고는_후보든_비추천이든_사유와_남는다() -> None:
    """38차 §3-A · D15 — 수집 낱말을 회사 사업영역으로 넓혔다(담당자 결정 1). 수집 낱말 하나만 든 제목도
    분류가 `none`(버림)이 되지 않는다 — 후보(`high`)거나 사유가 붙은 비추천(`low`)이다."""
    from datetime import datetime, timezone

    from app.schemas.procurement import ProcurementNotice

    for keyword in opportunity_filter.COLLECT_KEYWORDS:
        notice = ProcurementNotice(
            id="g2b-T-000", notice_no="T-000", title=f"{keyword} 용역", agency="시험 기관",
            published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), raw_data={},
        )
        match = opportunity_filter.classify(notice)
        assert match.tier in ("high", "low"), keyword
        assert match.tier == "high" or match.low_reason, keyword
    # AI 쪽은 분류 낱말 안에서 고른다 — 수집만 하고 분류가 모르는 AI 낱말이 생기지 않게
    ai_side = [k for k in opportunity_filter.COLLECT_KEYWORDS if k in ("AI", "인공지능", "챗봇", "에이전트", "머신러닝", "딥러닝", "RAG")]
    assert set(ai_side) <= set(opportunity_filter.AI_KEYWORDS)


def test_키워드_수가_호출_예산_안에_들어간다() -> None:
    """키워드 × 창 하나가 호출 하나다. 첫 페이지만으로 예산을 다 쓰면 두 번째 페이지가 없다(2.8.1 — 30일은 창 다섯)."""
    assert len(opportunity_filter.COLLECT_KEYWORDS) * 5 < g2b_client.MAX_COLLECT_CALLS


# ---------------------------------------------------------------------------
# 조달청 조회 기간 상한(2.8.1 · 2026-11-11 부터 · 시작일 포함 7일 · 넘으면 resultCode 07 「입력범위값 초과 에러」)
# ---------------------------------------------------------------------------


def test_30일은_시작일_포함_7일_창_다섯으로_빈틈없이_나눈다() -> None:
    from datetime import datetime, timedelta

    kst = g2b_client.KST
    end = datetime(2026, 11, 12, 10, 33, tzinfo=kst)
    begin = end - timedelta(days=30)
    windows = g2b_client.inquiry_windows(begin, end)
    assert len(windows) == 5
    assert windows[0][1] == end and windows[-1][0] == begin, "새 창 먼저 · 처음과 끝이 맞다"
    assert windows[0][0] == datetime(2026, 11, 6, 0, 0, tzinfo=kst), "오늘 포함 7일(11-06 ~ 11-12)"
    for lower, upper in windows:
        assert lower <= upper
        assert (upper.date() - lower.date()).days <= g2b_client.MAX_WINDOW_DAYS - 1, (lower, upper)
    for (newer_lower, _), (_, older_upper) in zip(windows, windows[1:]):
        assert newer_lower - older_upper == timedelta(minutes=1), "창 사이에 빈 분이 없다(앞 창은 전날 23:59 까지)"
    # 짧은 창은 하나 그대로
    assert g2b_client.inquiry_windows(end - timedelta(hours=5), end) == [(end - timedelta(hours=5), end)]
    # 시작이 23:59:초이고 일수가 7의 배수여도 시작일 23:59 의 1분을 버리지 않는다(조회 칸은 분 단위 · 2.8.1 검토)
    late = datetime(2026, 11, 12, 23, 59, 30, tzinfo=kst)
    two_weeks = g2b_client.inquiry_windows(late - timedelta(days=14), late)
    assert [g2b_client.format_inquiry_dt(b) for b, _ in two_weeks][-1] == "202610292359"
    assert len(two_weeks) == 3 and two_weeks[-1][0] <= two_weeks[-1][1]


def test_수집은_조달청_상한을_넘는_창을_보내지_않는다() -> None:
    """11-11 부터 30일 창이 「입력범위값 초과」로 21회 모두 거절됐다 — 나눠 부르면 받는다(가짜도 상한을 넘으면 거절)."""
    recorder = Recorder({"AI": [[item("R1")]], "교육": [[item("R2")]]}, {"AI": 1, "교육": 1})
    outcome = collect(recorder, keywords=["AI", "교육"], days=30)
    assert {i["bidNtceNo"] for i in outcome.items} == {"R1", "R2"}
    assert outcome.failures == 0 and outcome.truncated == ()
    assert len(recorder.windows) == 2 * 5
    for begin, end in recorder.windows:
        assert (end.date() - begin.date()).days <= g2b_client.MAX_WINDOW_DAYS - 1
    assert outcome.method == "공고명 키워드 2개 · 마감 제외 · 최근 30일", "받는 범위 · 화면 문장은 그대로"


def test_받은_공고는_낱말_순서로_줄_선다_상한에서_오래된_창이_잘리지_않게() -> None:
    """부르는 쪽은 앞에서부터 600건만 쓴다. 「새 창 먼저」로 쌓았더니 2~4주 전 게시된 마감 전 후보(2 · 3순위 공고 포함)가
    잘렸다(2.8.1 검토) — 창을 나누기 전처럼 첫 쪽 먼저 → 낱말 순서 → 새 창 먼저로 줄 세운다."""

    class ByWindow(Recorder):
        """첫 낱말(AI)은 가장 오래된 창에만 · 둘째 낱말(교육)은 가장 새 창에만 공고가 있다. AI 2쪽은 맨 뒤."""

        def __init__(self) -> None:
            super().__init__({}, {})
            self.ends: list[Any] = []

        async def __call__(self, *, begin, end, page_no=1, num_rows=100, operation="", extra_params=None) -> dict[str, Any]:
            keyword = dict(extra_params or {}).get(g2b_client.PARAM_NOTICE_NAME, "")
            if end not in self.ends:
                self.ends.append(end)
            window = self.ends.index(end)
            self.calls.append((keyword, page_no))
            if keyword == "AI" and window == 4:
                items = [item("A-old-1"), item("A-old-2")] if page_no == 1 else [item("A-old-p2")]
                return {"totalCount": 3, "items": items}
            if keyword == "교육" and window == 0:
                return {"totalCount": 1, "items": [item("E-new")]}
            return {"totalCount": 0, "items": []}

    outcome = collect(ByWindow(), keywords=["AI", "교육"], days=30)
    assert [i["bidNtceNo"] for i in outcome.items] == ["A-old-1", "A-old-2", "E-new", "A-old-p2"]


def test_모두_거절되면_잇달아_10번에서_멈춘다() -> None:
    """조달청이 모두 거절하는 날 낱말 21 × 창 5 = 105회를 헛되이 쓰지 않는다(하루 한도) — 예외 글에 마지막 오류를 붙인다."""

    class Refused(Recorder):
        async def __call__(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("", kwargs.get("page_no", 1)))
            raise g2b_client.G2BClientError("G2B API error 07: 입력범위값 초과 에러")

    recorder = Refused({}, {})
    with pytest.raises(g2b_client.G2BCollectError) as caught:
        collect(recorder, keywords=list(opportunity_filter.COLLECT_KEYWORDS), days=30)
    assert len(recorder.calls) == g2b_client.ABORT_AFTER_FAILURES
    assert caught.value.calls == caught.value.failures == g2b_client.ABORT_AFTER_FAILURES
    assert "입력범위값 초과" in str(caught.value)


# ---------------------------------------------------------------------------
# 녹화한 실제 응답 (0920 §4-A-1 · §4-A-4 에서 한 번 받아 저장)
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "g2b_search_AI_page1.json"


def recorded() -> dict[str, Any]:
    if not FIXTURE.exists():
        pytest.skip("녹화한 응답이 없다")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_녹화한_응답에_서비스키가_없다() -> None:
    """저장소에 들어가는 파일이다. 키가 섞이면 CLAUDE.md 21 위반이다."""
    text = FIXTURE.read_text(encoding="utf-8") if FIXTURE.exists() else ""
    assert "serviceKey" not in text


def test_녹화한_응답을_그대로_읽어_낸다() -> None:
    """실제 응답 봉투를 우리 파서가 읽는지 — 가짜만으로는 확인되지 않는 것이다."""
    body = recorded()["body"]
    items = g2b_client._items_of(body)
    assert g2b_client._total_count_of(body) == 195
    assert len(items) == 100
    assert all(i.get("bidNtceNo") for i in items)


def test_공고명_조회_1페이지는_전부_일반용역이다() -> None:
    """**이것이 옛 수집기가 놓친 이유다** (ISSUE-072).

    창 순회는 「마지막 페이지가 최신」이라 믿고 뒤에서 600건을 받았는데, 그 뒤쪽은
    용역구분이 «기술용역»인 구간이었다. AI 공고는 전부 일반용역이라 한 건도 들어오지
    않았다. 녹화한 실제 응답 100건이 **전부 일반용역**인 것이 그 증거다.
    """
    items = g2b_client._items_of(recorded()["body"])
    kinds = {i.get("srvceDivNm") for i in items}
    assert kinds == {"일반용역"}


def test_녹화한_응답에서_교육_갈래가_나온다() -> None:
    """수집과 갈래 분류가 이어지는지 — 실제 제목으로 확인한다 (§4-A-2 와 짝)."""
    from app.services import g2b_mapper, work_kinds

    notices = g2b_mapper.map_notices(g2b_client._items_of(recorded()["body"]))
    education = [
        n for n in notices if "education" in work_kinds.work_tracks(work_kinds.detect_work_kinds(n.title))
    ]
    assert len(education) >= 10, f"교육 갈래가 {len(education)}건뿐이다"


def test_녹화한_응답에_차수가_섞여_있다() -> None:
    """차수 병합이 실제로 필요한 상황인지 — 지어낸 걱정이 아니라는 확인이다."""
    items = g2b_client._items_of(recorded()["body"])
    assert {i.get("bidNtceOrd") for i in items} > {"000"}


# ---------------------------------------------------------------------------
# 차수 병합 (0920 §4-A-1)
# ---------------------------------------------------------------------------


def notice(no: str, order: str, title: str = "AI 교육 운영"):
    from app.schemas.procurement import ProcurementNotice

    return ProcurementNotice(
        id=f"g2b-{no}-{order}",
        notice_no=f"{no}-{order}",
        title=title,
        agency="시험기관",
        published_at="2026-09-10T00:00:00+09:00",
        deadline_at=None,
        budget=None,
        region=None,
        description=None,
        source_url=None,
        raw_data={},
    )


def test_차수는_최신_하나만_목록에_두고_이전_차수는_돌려준다() -> None:
    latest, superseded = procurement_service.split_revisions(
        [notice("R1", "000"), notice("R1", "001"), notice("R2", "000")]
    )
    assert [n.notice_no for n in latest] == ["R1-001", "R2-000"]
    assert [n.notice_no for n in superseded["g2b-R1-001"]] == ["R1-000"]
    assert "g2b-R2-000" not in superseded, "차수가 하나뿐이면 이전 차수가 없다"


def test_차수_수는_등장_횟수가_아니라_서로_다른_차수의_수다() -> None:
    """키워드 조회는 같은 공고를 여러 번 물어온다. 등장 횟수를 세면 화면이 거짓말한다.

    차수가 하나뿐인 공고가 「차수 3건 중 최신」으로 보이게 된다.
    """
    latest, superseded = procurement_service.split_revisions(
        [notice("R1", "000"), notice("R1", "000"), notice("R1", "000")]
    )
    assert len(latest) == 1
    assert latest[0].revision_count == 1
    assert superseded == {}


def test_차수가_여럿이면_그_수를_센다() -> None:
    latest, _ = procurement_service.split_revisions(
        [notice("R1", "000"), notice("R1", "001"), notice("R1", "001"), notice("R1", "002")]
    )
    assert latest[0].revision_count == 3
