"""「찾는 낱말」 (2.0.7 · 대표 10-27 「낱말 추가를 대시보드에서 할 수 있게 · 그리고 바로 재검색」). 바깥 호출 없음 — 받기는 monkeypatch.

재는 것:
1. 낱말 규칙(길이 · 글자 · 기본과 같음 · 너무 흔함) · 11번째 낱말 400 · 그사이 남이 바꿨으면 409 · 열람자 403.
2. 문 꺼짐 · 아침 받기 잠금 · 하루 11번째는 200 + `search_error` 이고 **나라장터를 한 번도 부르지 않는다**(저장은 됨).
3. 바로 찾기는 그 낱말 하나만 · 자격 하루치 6회 상한으로 받고 저장본에 **합친다**(지우지 않음 · 받은 시각 그대로) · 활동 기록.
4. 추가 낱말로만 걸린 공고는 버려지지 않고 「관련 낮음」 + 사유(결정 ②) · 영문 짧은 낱말은 단어 경계.
5. 아침 받기 · 사전규격이 추가 낱말을 함께 쓴다 · 호출 예산 50 · 낱말을 지운 다음 날 받기가 줄어듦 차단에 막히지 않는다.
6. 하루 횟수는 한국 날짜(UTC 15:00 에 바뀜).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core import identity, storage
from app.core.config import get_settings
from app.main import app
from app.schemas.procurement import ProcurementNotice
from app.services import (
    audit_log_service,
    auto_collect,
    collect_keywords_service,
    g2b_client,
    notice_version_service,
    opportunity_filter,
    prespec_service,
    procurement_service,
    user_service,
)

client = TestClient(app)
KST = timezone(timedelta(hours=9))
SECRET = "bidpilot-keywords-token-207"


def _notice(no: str, title: str) -> ProcurementNotice:
    return ProcurementNotice(
        id=f"g2b-{no}-000", notice_no=f"{no}-000", title=title, agency="시험기관",
        published_at=datetime(2026, 10, 20, 9, 0, tzinfo=KST), raw_data={},
    )


def _seed(cache_file: Path, notices: list[ProcurementNotice]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "_note": "시험 저장본", "collected_by": "공고명 키워드 21개", "fetched_at": "2026-10-20T00:00:00+00:00", "days": 30,
        "total_fetched": len(notices),
        "notices": [{"notice": n.model_dump(mode="json"), "candidate": {}, "pinned": False} for n in notices],
    }, ensure_ascii=False), encoding="utf-8")


def _stored(cache_file: Path) -> dict:
    return json.loads(cache_file.read_text(encoding="utf-8"))


def _never(*_args: object, **_kwargs: object):
    raise AssertionError("나라장터를 불렀다")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notice_version_service, "VERSION_DIR", tmp_path / "notice_versions")


@pytest.fixture()
def no_outside(monkeypatch: pytest.MonkeyPatch) -> None:
    """나라장터 공고명 검색 · 수집이 불리면 실패한다."""
    monkeypatch.setattr(g2b_client, "search_bid_notices", _never)
    monkeypatch.setattr(procurement_service, "collect_candidates", _never)


def _add(word: str, *, search: bool = True, expected: str | None = None):
    return client.post("/api/collect-keywords", json={"word": word, "search": search, "expected_updated_at": expected})


# --- 1. 낱말 규칙 · 상한 · 409 · 403 -------------------------------------------------------------


@pytest.mark.parametrize(("word", "reason"), [
    ("가", "두 글자 이상"),
    ("가" * 21, "20자까지"),
    ("메타버스!", "한글 · 영문 · 숫자"),
    ("전략수립", "이미 있는 낱말입니다(「전략 수립」)"),  # 띄어쓰기 무시
    ("ai", "이미 있는 낱말입니다(「AI」)"),  # 대소문자 무시
    ("용 역", "거의 모든 공고명"),
    # (2.0.7 검토 back-2) 정확히 같은 낱말만 막으면 돌아갔다
    ("2026", "숫자 · 기호만"),
    ("--", "숫자 · 기호만"),
    ("2026년", "거의 모든 공고명"),
    ("운영 용역", "거의 모든 공고명"),
    ("운영용역", "거의 모든 공고명"),
])
def test_낱말_규칙에_어긋나면_400(word: str, reason: str) -> None:
    response = _add(word, search=False)
    assert response.status_code == 400
    assert reason in response.json()["detail"]
    assert collect_keywords_service.state()["extra"] == []


def test_다듬어_저장하고_11번째는_400() -> None:
    state = client.get("/api/collect-keywords").json()
    assert state["base"] == list(opportunity_filter.COLLECT_KEYWORDS) and state["updated_at"] is None
    assert (state["max_extra"], state["searches_limit"], state["search_live"]) == (10, 10, False)

    expected = None
    for index in range(10):
        response = _add(f"  메타버스　{index}  ", search=False, expected=expected)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["search"] is None and body["search_error"] is None
        expected = body["state"]["updated_at"]
    words = [entry["word"] for entry in body["state"]["extra"]]
    assert words[0] == "메타버스 0" and len(words) == 10
    assert body["state"]["extra"][0]["added_by_name"] == "이 PC"  # 로그인 없는 로컬

    full = _add("빅데이터", search=False, expected=expected)
    assert full.status_code == 400
    assert full.json()["detail"] == "추가 낱말은 10개까지입니다 — 하나를 지운 뒤 더하세요"
    assert opportunity_filter.COLLECT_KEYWORDS[0] in collect_keywords_service.all_keywords()
    assert len(collect_keywords_service.all_keywords()) == len(opportunity_filter.COLLECT_KEYWORDS) + 10
    # 낱말 10개를 더해도 아침 받기 첫 쪽들이 호출 예산 안이다(결정 ④ · 2.8.1 — 30일을 7일 창 다섯으로 나눠 낱말 × 창마다 첫 쪽)
    windows = len(g2b_client.inquiry_windows(datetime(2026, 10, 13, 10, 0, tzinfo=KST), datetime(2026, 11, 12, 10, 0, tzinfo=KST)))
    assert windows == 5
    assert len(collect_keywords_service.all_keywords()) * windows < g2b_client.MAX_COLLECT_CALLS


def test_그사이_남이_바꿨으면_409_이고_지우기도_같다() -> None:
    first = _add("메타버스", search=False).json()["state"]["updated_at"]
    stale = _add("빅데이터", search=False, expected=None)  # 처음 읽은 화면(빈 목록)으로 저장
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_write"
    assert "먼저 바꿨습니다" in stale.json()["detail"]["message"]

    gone = client.post("/api/collect-keywords/remove", json={"word": "메타버스", "expected_updated_at": None})
    assert gone.status_code == 409
    base = client.post("/api/collect-keywords/remove", json={"word": "AI", "expected_updated_at": first})
    assert base.status_code == 400 and base.json()["detail"] == "기본 낱말은 지울 수 없습니다"
    removed = client.post("/api/collect-keywords/remove", json={"word": "메타 버스", "expected_updated_at": first})
    assert removed.status_code == 200
    assert removed.json()["state"]["extra"] == []


@pytest.fixture()
def signed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "api_token", SECRET)
    monkeypatch.setattr(user_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.delenv("DEMO_USER", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    auth_api.reset_login_throttle()
    user_service.clear_snapshot_cache()
    user_service.add_user("staff1", "old-password-1", role="viewer", display_name="직원 하나")
    user_service.add_user("editor1", "old-password-2", role="editor", display_name="편집 하나")
    user_service.clear_snapshot_cache()
    yield
    user_service.clear_snapshot_cache()


def _headers(user: str, role: str) -> dict[str, str]:
    return {"X-API-Token": SECRET, "X-User": user, "X-User-Role": role, "X-User-Signature": identity.signature_for(user, role, SECRET)}


def test_열람자는_읽기만_편집자는_더하고_이름이_남는다(signed: None, no_outside: None) -> None:
    viewer = _headers("staff1", "viewer")
    assert client.get("/api/collect-keywords", headers=viewer).status_code == 200
    for path, body in (
        ("/api/collect-keywords", {"word": "메타버스"}),
        ("/api/collect-keywords/search", {"word": "메타버스"}),
        ("/api/collect-keywords/remove", {"word": "메타버스"}),
    ):
        assert client.post(path, json=body, headers=viewer).status_code == 403
    assert collect_keywords_service.extra_words() == ()

    added = client.post("/api/collect-keywords", json={"word": "메타버스", "search": False}, headers=_headers("editor1", "editor"))
    assert added.status_code == 200, added.text
    entry = added.json()["state"]["extra"][0]
    assert (entry["added_by"], entry["added_by_name"]) == ("editor1", "편집 하나")


# --- 2. 문 꺼짐 · 잠금 · 하루 한도: 바깥 호출 0 ---------------------------------------------------------


def test_문이_꺼져_있으면_저장만_되고_바깥은_부르지_않는다(no_outside: None) -> None:
    response = _add("메타버스")
    assert response.status_code == 200
    body = response.json()
    assert body["search"] is None
    assert body["search_error"] == "이 서버에서는 바로 찾기가 꺼져 있습니다 — 다음 목록 받기부터 이 낱말로 찾습니다"
    assert [e["word"] for e in body["state"]["extra"]] == ["메타버스"]
    assert body["state"]["searches_today"] == 0
    assert client.get("/health").json()["keyword_search_live"] is False
    events = [json.loads(line)["event"] for line in audit_log_service.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["kind"] == "collect_keyword_add" and events[-1]["word"] == "메타버스"
    assert events[-1]["search_error"].startswith("이 서버에서는 바로 찾기가 꺼져")


def test_아침_받기가_도는_중이면_사유만(no_outside: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "keyword_search_live", True)
    assert client.get("/health").json()["keyword_search_live"] is True
    assert auto_collect.acquire_lock()  # 아침 받기(같은 프로세스 pid 로 흉내)
    try:
        body = _add("메타버스").json()
    finally:
        auto_collect.release_lock()
    assert body["search"] is None
    assert body["search_error"] == "아침 자동 받기가 도는 중입니다 — 끝난 뒤 다시 누르세요"
    assert body["state"]["searches_today"] == 0  # 부르지 않았으니 세지 않는다


def test_하루_11번째는_사유만(no_outside: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "keyword_search_live", True)
    _add("메타버스", search=False)
    for _ in range(10):
        collect_keywords_service.count_search()
    body = client.post("/api/collect-keywords/search", json={"word": "메타버스"}).json()
    assert body["search"] is None
    assert body["search_error"] == "오늘 바로 찾기 10번을 다 썼습니다 — 다음 목록 받기부터 찾습니다"
    assert body["state"]["searches_today"] == 10
    assert client.post("/api/collect-keywords/search", json={"word": "빅데이터"}).status_code == 400  # 추가 낱말만 다시 찾는다


def test_하루_횟수는_한국_날짜로(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "utc_now", lambda: datetime(2026, 10, 27, 14, 59, tzinfo=timezone.utc))  # KST 23:59
    collect_keywords_service.count_search()
    assert collect_keywords_service.searches_today() == 1
    monkeypatch.setattr(storage, "utc_now", lambda: datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc))  # KST 다음 날 00:00
    assert collect_keywords_service.searches_today() == 0
    assert collect_keywords_service.count_search() == 1


# --- 3. 바로 찾기 = 낱말 하나 · 합치기 --------------------------------------------------------------------


def test_바로_찾기는_그_낱말만_받아_저장본에_합친다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "keyword_search_live", True)  # 나라장터 실호출 문(G2B_LIVE_FETCH)은 꺼진 채
    old = [_notice(f"R26KW{i:05d}", f"생성형 AI 활용 실무교육 운영 용역 {i}") for i in range(3)]
    _seed(notice_cache_file, old)
    seen: dict = {}

    async def fake_collect(**kwargs: object) -> procurement_service.Collected:
        seen.update(kwargs)
        notices = [old[1], _notice("R26KWNEW01", "메타버스 체험관 조성 용역"), _notice("R26KWNEW02", "메타버스 활용 교육 운영")]
        return procurement_service.Collected(
            notices=notices, superseded={}, calls=4, method="공고명 키워드 1개", total_fetched=3, truncated=("메타버스",),
            failed_keywords=("메타버스",), failed_calls=2,
        )

    monkeypatch.setattr(procurement_service, "collect_candidates", fake_collect)
    response = _add("메타버스")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["search_error"] is None
    result = body["search"]
    assert {k: result[k] for k in ("word", "found", "new_notices", "candidates", "low", "truncated", "calls")} == {
        "word": "메타버스", "found": 3, "new_notices": 2, "candidates": 2, "low": 1, "truncated": True, "calls": 4,
    }
    assert seen["keywords"] == ["메타버스"]
    assert seen["qualification_max_calls"] == 6 and seen["qualification_live"] is True
    # (2.8.1) 30일은 7일 창 다섯 — 목록 호출은 창마다 첫 쪽 + 2쪽(예전 「최대 3쪽」에 가장 가까운 상한) · 일부 기간 실패는 알린다
    assert seen["max_calls"] == 5 + procurement_service.KEYWORD_SEARCH_EXTRA_PAGES == 7
    assert result["failed_calls"] == 2

    stored = _stored(notice_cache_file)
    ids = {entry["notice"]["id"] for entry in stored["notices"]}
    ours = {i for i in ids if "R26KW" in i}  # (+ 시연용 고정 공고)
    assert {n.id for n in old} <= ours and "g2b-R26KWNEW01-000" in ours and len(ours) == 5  # 지우지 않고 더하기만
    assert stored["fetched_at"] == "2026-10-20T00:00:00+00:00"  # 목록 전체를 방금 받은 것처럼 적지 않는다
    assert body["state"]["searches_today"] == 1

    # 다음 조회부터 목록에 보인다 — 접힌 것은 사유와 함께
    listed = {view.notice.id: view.match for view in procurement_service.cached_only(include_low=True).notices}
    assert listed["g2b-R26KWNEW01-000"].tier == "low"
    assert listed["g2b-R26KWNEW01-000"].low_reason.startswith("추가 낱말 「메타버스」로 받았지만 본업")
    assert listed["g2b-R26KWNEW02-000"].is_candidate
    events = [json.loads(line)["event"] for line in audit_log_service.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()]
    assert {"kind": "collect_keyword_add", "word": "메타버스", "found": 3, "new": 2, "search_error": None} in events


def test_받기_실패는_사유와_할_일_저장본_그대로(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "keyword_search_live", True)
    _seed(notice_cache_file, [_notice("R26KW00001", "AI 교육 운영")])
    before = notice_cache_file.read_bytes()

    async def broken(**_kwargs: object):
        raise g2b_client.G2BCollectError("SERVICE_KEY_IS_NOT_REGISTERED_ERROR", calls=1, failures=1)

    monkeypatch.setattr(procurement_service, "collect_candidates", broken)
    body = _add("메타버스").json()
    assert body["search"] is None
    assert body["search_error"] == "나라장터에서 받지 못했습니다(저장된 목록은 그대로) — 서비스키 미등록 · 만료 — 대표가 data.go.kr 에서 활용기간을 연장하세요"
    assert notice_cache_file.read_bytes() == before
    assert not auto_collect.LOCK_FILE.exists()  # 잠금은 놓았다


def test_찾은_공고가_없으면_실패가_아니다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "keyword_search_live", True)

    async def empty(**_kwargs: object):
        raise g2b_client.G2BCollectError("한 건도 받지 못했습니다", calls=1, failures=0)

    monkeypatch.setattr(procurement_service, "collect_candidates", empty)
    result = _add("메타버스").json()["search"]
    assert (result["found"], result["new_notices"], result["calls"], result["truncated"]) == (0, 0, 1, False)


def test_자격_하루치는_문이_꺼져도_바로_찾기에서만_받는다(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    async def fetch(target: object, **_kwargs: object):
        called.append(target)
        return g2b_client.DayQualifications(day=target, licenses={}, regions={}, calls=2, complete=False, note="시험")

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", fetch)
    day = datetime(2026, 10, 20).date()
    assert asyncio.run(procurement_service._ensure_qualification_days([day])) == (0, 0, None)  # 실호출 문 꺼짐
    assert called == []
    calls, _fetched, _note = asyncio.run(procurement_service._ensure_qualification_days([day], max_calls=6, live=True))
    assert calls == 2 and called == [day]


# --- 4. 분류: 버리지 않고 「관련 낮음」 + 사유 -------------------------------------------------------------


def test_추가_낱말_공고는_버려지지_않고_관련_낮음() -> None:
    plain = _notice("R26KW00009", "메타버스 체험관 조성 용역")
    assert opportunity_filter.classify(plain).tier == "none"  # 낱말을 더하기 전 — 버려지는 모양
    collect_keywords_service.add("메타버스", by=None, expected_updated_at=None)
    match = opportunity_filter.classify(plain)
    assert match.tier == "low"
    assert match.low_reason == "추가 낱말 「메타버스」로 받았지만 본업(교육 · 과정 · 컨설팅 · ESG · AX · 디지털 역량) 낱말이 없습니다"
    assert [n for n, _ in opportunity_filter.filter_candidates([plain], include_low=True)] == [plain]
    # 기본 낱말 사유는 그대로
    assert opportunity_filter.classify(_notice("R26KW00010", "콘텐츠 저작권 등록")).low_reason.startswith("수집 낱말 「콘텐츠」")


def test_영문_짧은_낱말은_단어_경계() -> None:
    collect_keywords_service.add("VR", by=None, expected_updated_at=None)
    assert not collect_keywords_service.matches("KOVRA 연례 보고서", "VR")
    assert collect_keywords_service.matches("vr 체험관 조성", "VR")
    assert prespec_service.wanted("KOVRA 연례 보고서") == [] and prespec_service.wanted("VR 체험관 조성") == ["VR"]
    assert collect_keywords_service.matches("메타 버스 체험관", "메타버스")  # 띄어쓰기 무시(공고명 검색과 같다)


# --- 5. 아침 받기 · 사전규격 · 지운 다음 날 ---------------------------------------------------------------


def test_아침_받기와_사전규격이_추가_낱말을_함께_쓴다(live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    collect_keywords_service.add("메타버스", by=None, expected_updated_at=None)
    seen: dict = {}

    async def fake_collect(**kwargs: object) -> procurement_service.Collected:
        seen.update(kwargs)
        return procurement_service.Collected(
            notices=[_notice("R26KW00020", "AI 교육 운영")], superseded={}, calls=1, method="공고명 키워드", total_fetched=1,
        )

    monkeypatch.setattr(procurement_service, "collect_candidates", fake_collect)
    asyncio.run(procurement_service.list_ai_candidates(days=30, refresh=True))
    assert tuple(seen["keywords"]) == (*opportunity_filter.COLLECT_KEYWORDS, "메타버스")
    assert "메타버스" in prespec_service.wanted("메타버스 기반 체험 콘텐츠 사전규격")
    assert prespec_service.wanted("통근버스 임차용역") == []


def test_낱말을_지운_다음_날_받기는_줄어듦_차단에_막히지_않는다(notice_cache_file: Path) -> None:
    base = [_notice(f"R26KWB{i:04d}", f"AI 교육 운영 {i}") for i in range(10)]
    extra = [_notice(f"R26KWX{i:04d}", f"메타버스 체험관 {i}") for i in range(30)]
    _seed(notice_cache_file, base + extra)
    views = [procurement_service.NoticeView(notice=n, match=opportunity_filter.classify(n)) for n in base]
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)

    # 낱말이 아직 있으면 10 < 40 의 절반 — 막는다(덜 받아 온 것일 수 있다)
    stamp = collect_keywords_service.add("메타버스", by=None, expected_updated_at=None)
    assert procurement_service.save_cache(views, 10, now, days=30) is not None
    # 지운 뒤에는 그 낱말로만 받은 30건을 비교에서 뺀다 — 저장된다
    updated = datetime.fromisoformat(collect_keywords_service.state()["updated_at"])
    collect_keywords_service.remove(stamp, by=None, expected_updated_at=updated)
    assert procurement_service.save_cache(views, 10, now, days=30) is None
    assert len(_stored(notice_cache_file)["notices"]) == 10


def test_아침_받기_예산은_기본_낱말_2_3쪽이_먼저(monkeypatch: pytest.MonkeyPatch) -> None:
    """(2.0.7 검토 back-1) 넓은 추가 낱말 10개가 「교육」 · 「AI」 뒤쪽 쪽을 밀어내 본업 공고가 저장본에서 빠졌다."""
    extras = [f"넓은낱말{i}" for i in range(10)]
    totals = {"교육": 250, "AI": 150, **{w: 2000 for w in extras}}

    async def fake_search(keyword: str, *, page_no: int, **_kwargs: object):
        total = totals.get(keyword, 10)
        start = (page_no - 1) * 100
        count = max(0, min(100, total - start))
        return [{"bidNtceNo": f"{keyword}-{page_no}-{i}", "bidNtceOrd": "000"} for i in range(count)], total

    monkeypatch.setattr(g2b_client, "search_bid_notices", fake_search)
    outcome = asyncio.run(g2b_client.collect_notices(keywords=[*opportunity_filter.COLLECT_KEYWORDS, *extras]))
    assert outcome.calls <= g2b_client.MAX_COLLECT_CALLS
    assert not set(outcome.truncated) & set(opportunity_filter.COLLECT_KEYWORDS), outcome.truncated


def test_바로_찾기_합치기는_저장본의_높은_차수를_옛_차수로_덮지_않는다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """(2.0.7 검토 back-3) 「다르면 바꿈」이라 정정 차수(-001)가 옛 차수(-000)로 덮였다."""
    monkeypatch.setattr(get_settings(), "keyword_search_live", True)
    newer = ProcurementNotice(
        id="g2b-R26KW00100-001", notice_no="R26KW00100-001", title="메타버스 체험 교육 운영(정정)", agency="시험기관",
        published_at=datetime(2026, 10, 21, 9, 0, tzinfo=KST), raw_data={},
    )
    _seed(notice_cache_file, [newer])

    async def fake_collect(**_kwargs: object) -> procurement_service.Collected:
        older = _notice("R26KW00100", "메타버스 체험 교육 운영")  # -000
        return procurement_service.Collected(notices=[older], superseded={}, calls=1, method="공고명 키워드 1개", total_fetched=1, truncated=())

    monkeypatch.setattr(procurement_service, "collect_candidates", fake_collect)
    assert _add("메타버스").status_code == 200
    ids = {entry["notice"]["id"] for entry in _stored(notice_cache_file)["notices"]}
    assert "g2b-R26KW00100-001" in ids and "g2b-R26KW00100-000" not in ids


def test_한_건도_못_받으면_마지막_오류를_붙여_할_일_안내가_붙는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """(2.0.7 검토 back-4) 예외 원문을 버려 「서비스키 … 연장하세요」 안내가 실제로는 붙지 않았다."""

    async def refused(_keyword: str, **_kwargs: object):
        raise g2b_client.G2BApiError("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")

    monkeypatch.setattr(g2b_client, "search_bid_notices", refused)
    with pytest.raises(g2b_client.G2BCollectError) as caught:
        asyncio.run(g2b_client.collect_notices(keywords=["메타버스"]))
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in str(caught.value)
    hint = auto_collect.failure_hint(str(caught.value))
    assert hint is not None and "서비스키" in hint


def test_바로_찾기의_자격_호출은_상한_6을_넘지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """(2.0.7 검토 back-5) 부르기 전에 「이미 다 썼나」만 봐서 하루 4회씩 두 날이면 8회까지 갔다."""
    from types import SimpleNamespace

    from app.services import qualification_store

    async def fake_day(_day: object):
        return SimpleNamespace(calls=4, complete=False, note="시험 — 덜 받음")

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", fake_day)
    monkeypatch.setattr(qualification_store, "settled_days", lambda _days: set())
    days = [datetime(2026, 10, 26, tzinfo=KST).date(), datetime(2026, 10, 27, tzinfo=KST).date()]
    calls, _fetched, note = asyncio.run(procurement_service._ensure_qualification_days(days, max_calls=6, live=True))
    assert calls <= 6
    assert note and "다음에 받습니다" in note
