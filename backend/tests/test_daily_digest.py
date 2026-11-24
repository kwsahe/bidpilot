"""「오늘 달라진 것」 한 줄 (0919 §4-B-1).

여기서 지키는 약속은 셋이다.

1. **네트워크를 부르지 않는다.** 이 집계를 만들다가 실제로 실호출이 나가 Git 이 추적하는
   시연 캐시가 4,205줄 바뀌었다(되돌렸다). 화면을 열 때마다 집계가 돌므로, 여기가 새면
   시연 중에 공고 목록이 바뀐다.
2. **「언제 기준인지」를 함께 돌려준다.** 숫자만 있고 기준 시각이 없으면 없느니만 못하다.
3. 네 숫자가 각각 **무엇을 근거로 셌는지**(`basis`) 말한다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import daily_digest_service, g2b_client, notice_state_service, procurement_service

NOW = datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc)


class LiveCallAttempted(AssertionError):
    """집계가 나라장터를 불렀다. 이 예외가 뜨면 §4-B-1 의 전제가 깨진 것이다."""


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """서비스의 「지금」을 **테스트가 캐시를 심은 시각**에 맞춘다 (ISSUE-118 · prompt_03 §4-C).

    이 파일은 `NOW` 로 캐시를 심는데, 예전에는 서비스가 **실제 시계**로 신선도
    (`CACHE_TTL_SECONDS` = 900초)를 쟀다. 그래서 `NOW + 15분` 이 지난 **다음 날부터**
    「캐시가 오래됐다 → 다시 받아라」가 되어 `test_목록_화면과_같은_범위를_센다` 가
    `LiveCallAttempted` 로 죽었다. 코드가 바뀌어서가 아니라 **날짜가 지나서** 빨개진
    것이라, 고쳐도 통과 여부를 믿을 수 없는 테스트였다.

    심는 시계와 재는 시계를 같게 하면 언제 돌려도 같은 답이 나온다.
    """
    monkeypatch.setattr(procurement_service, "_now", lambda: NOW)


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(**_kwargs: object) -> list[dict]:
        raise LiveCallAttempted("집계가 나라장터를 불렀습니다")

    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _explode)
    monkeypatch.setattr(g2b_client, "collect_notices", _explode)
    procurement_service.clear_memo()


def notice(nid: str, *, published: datetime, deadline: datetime | None) -> dict:
    return {
        "notice": {
            "id": nid,
            "notice_no": nid.replace("g2b-", ""),
            "title": f"{nid} 생성형 AI 교육 운영",
            "agency": "테스트기관",
            "published_at": published.isoformat(),
            "deadline_at": deadline.isoformat() if deadline else None,
            "budget": None,
            "region": None,
            "description": None,
            "source_url": None,
            "raw_data": {},
        },
        "candidate": {},
        "pinned": False,
    }


def seed(cache_file: Path, notices: list[dict], *, fetched_at: datetime) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "_note": "테스트용 캐시",
                "fetched_at": fetched_at.isoformat(),
                "days": 30,
                "total_fetched": len(notices),
                "notices": notices,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build(**kwargs: object) -> dict:
    return asyncio.run(daily_digest_service.build(now=NOW, **kwargs))  # type: ignore[arg-type]


def test_저장된_목록만_읽고_나라장터를_부르지_않는다(notice_cache_file: Path) -> None:
    # TTL(900초)을 한참 넘긴 캐시다. `list_ai_candidates` 였다면 실호출로 넘어갔을 상황이다.
    seed(
        notice_cache_file,
        [notice("g2b-A-000", published=NOW - timedelta(days=1), deadline=NOW + timedelta(days=3))],
        fetched_at=NOW - timedelta(days=2),
    )
    digest = build()
    assert digest["source"] == "cached"
    assert digest["total_notices"] >= 1


def test_마지막으로_받아온_시각을_그대로_돌려준다(notice_cache_file: Path) -> None:
    """이 값이 틀리면 화면이 몇 시간 전 자료를 「방금」이라고 말한다.

    실제로 그랬다 — `load_cache` 가 우리 ISO 형식을 나라장터 형식 파서로 읽으려다 실패하고
    조용히 `now()` 로 떨어졌다. 캐시를 보여줄 때 「조회 시각」이 늘 «지금»이었다.
    """
    stored = NOW - timedelta(hours=9, minutes=31)
    seed(notice_cache_file, [notice("g2b-A-000", published=NOW, deadline=None)], fetched_at=stored)
    assert build()["fetched_at"] == stored.isoformat()


def test_네_숫자를_각자의_근거로_센다(notice_cache_file: Path) -> None:
    seed(
        notice_cache_file,
        [
            # 새 공고이면서 7일 내 마감
            notice("g2b-A-000", published=NOW - timedelta(hours=5), deadline=NOW + timedelta(days=2)),
            # 새 공고지만 마감이 멀다
            notice("g2b-B-000", published=NOW - timedelta(days=1), deadline=NOW + timedelta(days=30)),
            # 오래된 공고 · 마감 임박
            notice("g2b-C-000", published=NOW - timedelta(days=40), deadline=NOW + timedelta(days=1)),
            # 오래된 공고 · **이미 마감** → 「7일 내 마감」에 세지 않는다
            notice("g2b-D-000", published=NOW - timedelta(days=40), deadline=NOW - timedelta(days=1)),
        ],
        fetched_at=NOW,
    )
    digest = build()
    assert digest["new_notices"]["value"] == 2
    assert digest["due_soon"]["value"] == 2
    for key in ("new_notices", "changed_notices", "due_soon", "awaiting_decision"):
        assert digest[key]["basis"], f"{key} 에 근거 문장이 없다"


def test_실제_마감이_지난_새_공고는_새_공고로_세지_않는다(notice_cache_file: Path) -> None:
    """2.1.0 — 띠 「최근 n일 새 공고」 = 사업기회 기본 목록(마감 뺌) · 대시보드 「새 공고」와 같은 범위다(검토 4)."""
    seed(
        notice_cache_file,
        [
            notice("g2b-A-000", published=NOW - timedelta(days=1), deadline=NOW + timedelta(days=5)),
            # 어제 올라와 한 시간 전에 마감 — 목록 기본에서 빠지는 공고
            notice("g2b-B-000", published=NOW - timedelta(days=1), deadline=NOW - timedelta(hours=1)),
        ],
        fetched_at=NOW,
    )
    digest = build()
    assert digest["new_notices"]["value"] == 1
    assert "실제 마감이 지난 것은 뺌" in digest["new_notices"]["basis"]


def test_목록_화면과_같은_범위를_센다(live_fetch_on: None, notice_cache_file: Path) -> None:
    """누른 곳과 도착한 곳의 숫자가 달라지면 안 된다.

    캐시에는 업무 키워드만 맞는 공고까지 들어 있고(`include_low=True` 기준으로 담는다),
    목록 화면은 기본값으로 후보만 보여준다. 처음에는 집계가 캐시를 통째로 세서 실제
    시연 자료에서 「새 공고 78건」→ 목록 8건이 됐다.

    **실조회를 켜고 잰다** (prompt_03 §4-A-3 · §4-C). 14차부터 실조회는 기본이 꺼짐이라,
    켜지 않으면 서비스가 TTL 을 보지도 않고 고정 모드 갈래로 빠진다 — 그러면 이 파일의
    약속 1번(「집계가 나라장터를 부르지 않는다」)을 **재지 않고도 초록**이 된다.
    켜 두면 신선도를 실제로 재고, `frozen_clock` 덕분에 캐시가 갓 심은 것으로 읽혀
    부르지 않는다. 그것이 원래 재려던 것이다.
    """
    off_topic = notice("g2b-Z-000", published=NOW, deadline=NOW + timedelta(days=3))
    off_topic["notice"]["title"] = "체육관 바닥 보수공사"
    seed(
        notice_cache_file,
        [notice("g2b-A-000", published=NOW, deadline=NOW + timedelta(days=3)), off_topic],
        fetched_at=NOW,
    )
    listed = asyncio.run(procurement_service.list_ai_candidates(days=30))
    assert "g2b-Z-000" not in {view.notice.id for view in listed.notices}
    assert build()["total_notices"] == len(listed.notices)


def test_결정_대기는_숫자와_id가_같은_것을_가리킨다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """목록 화면이 `?pending=1` 로 거르려면 어느 공고인지 알아야 한다.

    숫자만 주고 id 를 빼면 화면은 「결정 대기 2건」이라고 써 놓고 목록은 거르지 못한다.
    """
    seed(
        notice_cache_file,
        [
            notice("g2b-A-000", published=NOW, deadline=None),
            notice("g2b-B-000", published=NOW, deadline=None),
        ],
        fetched_at=NOW,
    )
    # 「분석을 시작한」 공고는 A 뿐이다. B 는 목록에 있기만 하다.
    #
    # 띠와 「검토 중」 탭이 **같은 서비스**를 쓰므로 여기서 그 서비스를 가짜로 바꾼다
    # (0920 §4-B-3 · ISSUE-076-a). 예전에는 띠가 자기만의 판정을 갖고 있었다.
    monkeypatch.setattr(
        notice_state_service,
        "state_of",
        lambda pid, context=None: notice_state_service.NoticeState(
            procurement_id=pid, parsed=(pid == "g2b-A-000")
        ),
    )
    # 「내 결정 대기」는 **목록 범위를 벗어난다** — 「검토 중」 탭과 같은 집합이기 때문이다.
    # 그래서 후보 집합도 그쪽 함수에서 온다.
    monkeypatch.setattr(notice_state_service, "review_queue_ids", lambda context=None: {"g2b-A-000"})
    digest = build()
    assert digest["analysed_notices"] == 1
    assert digest["awaiting_decision"]["value"] == 1
    assert digest["pending_ids"] == ["g2b-A-000"]


def test_고정_모드면_변경_감지가_멈춰_있다고_말한다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0 이 「변경이 없다」가 아니라 「그동안 받아온 적이 없다」일 수 있다."""
    from app.core.config import get_settings

    from app.services import auto_collect

    monkeypatch.setattr(get_settings(), "g2b_live_fetch", False)
    # 키트 — 자동 받기 기록도 예약 작업도 없다(41차 REGRESS-05: 로그가 없어도 예약 작업이 있으면 키트가 아니다)
    monkeypatch.setattr(auto_collect, "task_state", lambda: "NONE")
    seed(notice_cache_file, [notice("g2b-A-000", published=NOW, deadline=None)], fetched_at=NOW)
    digest = build()
    assert digest["frozen"] is True
    assert any("새 공고 받기가 꺼져" in note for note in digest["notes"])


def test_캐시가_아예_없으면_0이_아니라_사유를_말한다(notice_cache_file: Path) -> None:
    assert not notice_cache_file.exists()
    digest = build()
    assert digest["fetched_at"] is None
    assert digest["total_notices"] == 0
    assert any("받아 오세요" in note for note in digest["notes"])
