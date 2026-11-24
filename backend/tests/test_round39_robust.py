"""39차 §3-F-4 — 수집 견고성: DAILY-02(낱말 일부 실패) · DAILY-06(목록 실패 시 공고문 단계) · 발주계획 합침 · 급감 · DAILY-01(추출기 판)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import auto_collect

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# DAILY-02 — 낱말 페이지가 실패하면 그 낱말 몫은 지난 저장본으로 잇는다 · 「일부 실패」
# --------------------------------------------------------------------------


def test_키워드_페이지가_실패하면_실패한_낱말을_돌려준다() -> None:
    from app.services import g2b_client

    async def fake_raw(*, begin, end, page_no=1, num_rows=100, operation="", extra_params=None):
        keyword = (extra_params or {}).get(g2b_client.PARAM_NOTICE_NAME, "")
        if keyword == "교육":
            raise g2b_client.G2BClientError("read timeout")
        return {"totalCount": 1, "items": [{"bidNtceNo": f"R26BK0000{len(keyword)}", "bidNtceOrd": "000", "bidNtceNm": f"{keyword} 용역"}]}

    original = g2b_client.fetch_bid_notices_raw
    g2b_client.fetch_bid_notices_raw = fake_raw  # type: ignore[assignment]
    try:
        out = asyncio.run(g2b_client.collect_notices(keywords=["AI", "교육", "컨설팅"], days=30))
    finally:
        g2b_client.fetch_bid_notices_raw = original  # type: ignore[assignment]
    # 실패 수는 호출마다 — 30일은 7일 창 다섯이라(2.8.1) 「교육」 실패는 창마다 한 번씩 5회
    assert out.failed == ("교육",) and out.failures == 5 and len(out.items) == 2


def _view(no: str, title: str, *, deadline_days: int = 10, published_days: int = 3):
    from app.schemas.procurement import ProcurementNotice
    from app.services import procurement_service
    from app.services.opportunity_filter import classify

    notice = ProcurementNotice(
        id=f"g2b-{no}-000", notice_no=f"{no}-000", title=title, agency="기관", published_at=NOW - timedelta(days=published_days),
        deadline_at=NOW + timedelta(days=deadline_days),
    )
    return procurement_service.NoticeView(notice=notice, match=classify(notice))


def test_실패한_낱말_몫은_지난_저장본에서_마감_전인_것만_잇는다() -> None:
    from app.services import procurement_service

    kept = _view("R26BK01000001", "생성형 AI 활용 교육 운영")
    edu_only = _view("R26BK01000002", "신규 임용자 직무 교육 운영 용역")
    edu_closed = _view("R26BK01000003", "역량 교육 운영", deadline_days=-1)
    other = _view("R26BK01000004", "ESG 컨설팅 용역")
    cached = procurement_service.ProcurementResult(source="cached", notices=[kept, edu_only, edu_closed, other], fetched_at=NOW, total_fetched=4)
    views, patched = procurement_service.carry_failed_keywords([kept], cached, failed=("교육",), now=NOW)
    assert patched == 1 and [v.notice.id for v in views] == [kept.notice.id, edu_only.notice.id]
    assert procurement_service.carry_failed_keywords([kept], cached, failed=(), now=NOW) == ([kept], 0)


def test_일부_실패한_실행은_성공이지만_화면_줄에_적는다(tmp_path: Path, monkeypatch) -> None:
    row = {"시각": datetime(2026, 10, 18, 7, 30, tzinfo=KST).astimezone(timezone.utc).isoformat(), "실행": True,
           "결과": [{"출처": "나라장터", "결과": "g2b", "일부_실패": "일부 실패 — 낱말 「교육」 조회 실패 1회"}]}
    path = tmp_path / "collect_daily.log"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(auto_collect, "LOG_FILE", path)
    state = auto_collect.collect_state(datetime(2026, 10, 18, 9, 0, tzinfo=KST))
    assert state["kind"] == "ok" and state["text"].endswith("· 일부 실패(지난 저장본으로 채움)")


# --------------------------------------------------------------------------
# DAILY-06 — 목록을 못 받았으면 공고문 단계가 수집을 되풀이하지 않는다 · 이번 실행의 실패 호출 수
# --------------------------------------------------------------------------


def test_목록이_실패하면_공고문_단계를_건너뛴다(monkeypatch) -> None:
    from tests.test_round38_strength import _load_collect_daily

    daily = _load_collect_daily()
    called: list[str] = []

    async def failed_g2b(*args, **kwargs):
        return {"출처": "나라장터", "결과": "cached", "오류": "나라장터 키워드 조회에서 한 건도 받지 못했습니다 (호출 21회 · 실패 21회).", "실패_호출": 21}

    async def documents(*args, **kwargs):
        called.append("공고문")
        return {"출처": "나라장터 공고문"}

    async def nothing(*args, **kwargs):
        return {"출처": "x", "결과": "g2b"}

    monkeypatch.setattr(daily, "_collect_g2b", failed_g2b)
    monkeypatch.setattr(daily, "_collect_bizinfo", nothing)
    monkeypatch.setattr(daily, "_collect_g2b_documents", documents)
    monkeypatch.setattr(daily, "_collect_bizinfo_documents", nothing)
    monkeypatch.setattr(daily.prespec_service, "collect_prespecs", nothing)
    monkeypatch.setattr(daily.prespec_service, "collect_order_plans", nothing)
    monkeypatch.setattr(daily.procurement_service, "live_fetch_enabled", lambda: True)
    monkeypatch.setattr(daily.bizinfo_service, "live_fetch_enabled", lambda: False)
    rows = asyncio.run(daily.collect(30))
    assert called == []
    skipped = next(r for r in rows if r["출처"] == "나라장터 공고문")
    assert "건너뜁니다" in skipped["건너뜀"]


def test_목록이_다_실패하면_이번_실행의_호출_수를_싣는다(live_fetch_on, monkeypatch, notice_cache_file: Path) -> None:
    from app.services import g2b_client, procurement_service

    notice_cache_file.parent.mkdir(parents=True, exist_ok=True)
    notice_cache_file.write_text(
        json.dumps({"fetched_at": "2026-10-16T00:00:00+00:00", "days": 30, "collect_calls": 39, "notices": []}), encoding="utf-8"
    )

    async def broken(**_kwargs):
        raise g2b_client.G2BCollectError("나라장터 키워드 조회에서 한 건도 받지 못했습니다 (호출 21회 · 실패 21회).", calls=21, failures=21)

    monkeypatch.setattr(g2b_client, "collect_notices", broken)
    procurement_service.clear_memo()
    result = asyncio.run(procurement_service.list_ai_candidates(refresh=True))
    assert result.source == "cached" and result.collect_calls == 21 and result.failed_calls == 21


# --------------------------------------------------------------------------
# 발주계획 — 실행마다 합침 · 크게 줄면 「지난 자료 그대로」
# --------------------------------------------------------------------------


def _plan(no: str, name: str, month: str = "10") -> dict:
    return {"bizNm": name, "orderInsttNm": "기관", "orderYear": "2026", "orderMnth": month, "orderPlanUntyNo": no, "orderPlanSno": "0",
            "orderPlanDtlUrl": f"https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo={no}", "ofclNm": "홍길동", "telNo": "062-000-0000"}


def test_발주계획은_실행마다_합치고_크게_줄면_적는다(monkeypatch) -> None:
    from app.services import g2b_client, prespec_service

    prespec_service.ORDERPLAN_CACHE_FILE.write_text(json.dumps({"received": 401, "items": [
        _plan("R26DD1", "AI 리터러시 교육 운영"), _plan("R26DD2", "생성형 AI 컨설팅"), _plan("R26DD0", "AI 교육 9월 계획", month="09"),
    ]}, ensure_ascii=False), encoding="utf-8")

    async def small(**_kwargs):
        return g2b_client.AoOutcome(items=[_plan("R26DD3", "AI 직무 교육 운영"), _plan("R26DD1", "AI 리터러시 교육 운영(수정)")], calls=1, total=8, truncated=False)

    monkeypatch.setattr(g2b_client, "fetch_order_plans", small)
    row = asyncio.run(prespec_service.collect_order_plans(NOW))
    saved = json.loads(prespec_service.ORDERPLAN_CACHE_FILE.read_text(encoding="utf-8"))
    names = sorted(i["bizNm"] for i in saved["items"])
    assert names == ["AI 리터러시 교육 운영(수정)", "AI 직무 교육 운영", "생성형 AI 컨설팅"]  # 합침 · 같은 번호는 새것 · 지난 달은 뺌
    assert row["경고"] == prespec_service.ORDERPLAN_DROP_NOTE and saved["kept_note"] == prespec_service.ORDERPLAN_DROP_NOTE
    assert saved["received"] == 401 and saved["received_last"] == 8  # 기준은 지난번 양으로 남는다
    assert all(i["telNo"] == "<가림>" for i in saved["items"] if i["orderPlanUntyNo"] == "R26DD3")
    assert prespec_service.section([], now=NOW).plans_note == prespec_service.ORDERPLAN_DROP_NOTE


def test_발주계획이_보통으로_오면_경고_없음(monkeypatch) -> None:
    from app.services import g2b_client, prespec_service

    prespec_service.ORDERPLAN_CACHE_FILE.write_text(json.dumps({"received": 401, "items": []}), encoding="utf-8")

    async def normal(**_kwargs):
        return g2b_client.AoOutcome(items=[_plan("R26DD4", "AI 교육 운영")], calls=1, total=380, truncated=False)

    monkeypatch.setattr(g2b_client, "fetch_order_plans", normal)
    row = asyncio.run(prespec_service.collect_order_plans(NOW))
    assert row["경고"] is None and prespec_service.order_plan_note() is None


# --------------------------------------------------------------------------
# DAILY-01 — 조항 파일에 추출기 판
# --------------------------------------------------------------------------


def test_조항_파일에_추출기_판을_적는다() -> None:
    from app.services import qualification_clause_service as qc

    payload = qc.build_payload("g2b-R26BK00000001-000", [])
    assert payload["extractor_version"] == qc.EXTRACTOR_VERSION
