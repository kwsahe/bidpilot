"""39차 §3-C — 사전규격 「선제준비」 칸(결정 1 · PRESPEC-02~07).

- 사전규격은 입찰 목록 · 실무순 · 순번 · 건수 · limit 밖이다. `with_prepare` 로 부를 때만 「선제준비」 칸(`prepare`)이 온다.
- 칸: 본공고 나옴(빼고 본공고 행에 「사전규격 n일 전 공개」) → 본업 아님(「다른 사전규격」 접음) → 의견 마감 지남(접음) → 보임.
  순서는 의견 마감 남은 것 → 등록일 새것.
- 발주계획은 `ntceNticeYn=Y` 이거나 `bidNtceNoList` 가 있으면 「본공고 나옴」이고 「공고 전」이 아니다(PRESPEC-03).
- 브리핑: 매출 순위표 · 「지난 브리핑 대비」에서 사전규격을 뺀다(PRESPEC-04) · 본 것 줄은 사전규격을 따로 센다(PRESPEC-07).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.schemas.business_opportunity import NextRoute, PrepareSection, UnifiedOpportunity
from app.schemas.organization import AnalysisContext
from app.services import opportunity_brief_service as brief
from app.services import opportunity_service, prespec_service
from app.services import practical_priority as practical

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
ORG = "org-sample"


def _pre(n: int, *, title: str = "생성형 AI 활용 교육 운영", opinion: datetime | None = NOW + timedelta(days=3),
         published: datetime = NOW - timedelta(days=2), main: str | None = None, typ: str = "A1", budget: int | None = 100_000_000,
         note: str | None = None) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"g2bpre-R26BD000000{n:02d}", source_type="g2b", opportunity_type="pre_spec", title=title, agency="기관",
        organization_id=ORG, priority_rank=0, priority_label="미확인", eligibility_gate="CHECK", confidence="medium",
        score_components=[], next_route=NextRoute(kind="pre_spec", path="", label="본공고 전 — 규격서만 있음"), source="g2b",
        opinion_deadline=opinion, published_at=published, main_notice_id=main, fit_type=typ, budget=budget,
        relevance_note=note, deadline_text="의견 마감", detail_url="https://www.g2b.go.kr/x",
    )


def _bid(n: int, *, left: int = 20) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"g2b-R26BK0000000{n}-000", source_type="g2b", opportunity_type="procurement", title=f"AI 교육 운영 {n}", agency="기관",
        organization_id=ORG, priority_rank=n, priority_label="검토", eligibility_gate="CHECK", confidence="medium",
        score_components=[], next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached",
        deadline=NOW + timedelta(days=left), published_at=NOW - timedelta(days=1), fit_type="A1", company_priority_score=60,
    )


def _annotated(rows: list[UnifiedOpportunity]) -> list[UnifiedOpportunity]:
    practical.annotate(rows, now=NOW, ceiling_krw=200_000_000)
    return rows


# --------------------------------------------------------------------------
# 목록에서 뺌
# --------------------------------------------------------------------------


def test_사전규격은_입찰_목록_순번_건수_limit_밖이고_선제준비_칸으로_간다(monkeypatch) -> None:
    rows = [_pre(1), _pre(2), _bid(1), _bid(2), _pre(3), _bid(3)]

    async def collect(**_kwargs):
        return [r.model_copy() for r in rows], "cached", None, None

    monkeypatch.setattr(opportunity_service, "_collect_procurements", collect)
    ctx = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    plain = asyncio.run(opportunity_service.list_opportunities(context=ctx, source="g2b", limit=2, now=NOW))
    assert all(i.opportunity_type == "procurement" for i in plain.items) and plain.returned_count == 2
    assert plain.g2b_count == 3 and plain.summary.open_g2b == 3  # 「마감 전 나라장터」에 사전규격이 없다
    assert [i.source_rank for i in plain.items] == [1, 2]
    assert plain.prepare is None  # 부르지 않으면 칸이 없다 — 목록 응답이 가볍다
    full = asyncio.run(opportunity_service.list_opportunities(context=ctx, source="g2b", now=NOW, with_prepare=True))
    assert full.prepare is not None and full.prepare.total == 3
    assert {i.id for i in full.prepare.items} == {r.id for r in rows if r.opportunity_type == "pre_spec"}
    assert all(i.time_tier == "T3" for i in full.prepare.items)


# --------------------------------------------------------------------------
# 칸 나누기 · 순서
# --------------------------------------------------------------------------


def test_칸은_본공고_나옴_본업_아님_의견_마감_지남_보임으로_한_곳에만() -> None:
    merged = _pre(1, main="g2b-R26BK00000001-000")
    low = _pre(2, title="청사 시설 공사", note="본업 아님 — 시설 공사")
    large = _pre(3, budget=900_000_000)  # A1 · 상한 2배(4억) 넘음 → 대형 · 파트너형
    side = _pre(4, typ="D")  # 연구 · 감리 · 구매
    passed = _pre(5, opinion=NOW - timedelta(hours=1))
    shown = _pre(6)
    section = prespec_service.section(_annotated([merged, low, large, side, passed, shown]), now=NOW)
    assert [i.id for i in section.merged] == [merged.id]
    assert {i.id for i in section.others} == {low.id, large.id, side.id}
    assert [i.id for i in section.opinion_passed] == [passed.id]
    assert [i.id for i in section.items] == [shown.id]
    assert section.total == 6


def test_칸_안_순서는_의견_마감_남은_것_다음_등록일_새것() -> None:
    old_open = _pre(1, published=NOW - timedelta(days=9))
    new_open = _pre(2, published=NOW - timedelta(days=1))
    no_opinion = _pre(3, opinion=None, published=NOW)  # 의견 마감일 없음 — 남은 것 뒤
    section = prespec_service.section(_annotated([no_opinion, old_open, new_open]), now=NOW)
    assert [i.id for i in section.items] == [new_open.id, old_open.id, no_opinion.id]


# --------------------------------------------------------------------------
# 발주계획 — 본공고 나옴(PRESPEC-03)
# --------------------------------------------------------------------------


def _plans(rows: list[dict]) -> None:
    prespec_service.ORDERPLAN_CACHE_FILE.write_text(json.dumps({"fetched_at": NOW.isoformat(), "items": rows}, ensure_ascii=False), encoding="utf-8")


def _plan(name: str, **extra) -> dict:
    return {"bizNm": name, "orderInsttNm": "충청남도 공주시", "orderYear": "2026", "orderMnth": "10", "sumOrderAmt": "40000000",
            "cntrctMthdNm": "수의계약", "orderPlanDtlUrl": "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=R26DD1", **extra}


def test_발주계획은_본공고가_났으면_공고_전이_아니다() -> None:
    _plans([
        _plan("2026년 공주시 직원 워케이션 교육용역", ntceNticeYn="Y", bidNtceNoList="R26BK01774291000"),  # 실제 행(recheck31 PRESPEC-03)
        _plan("AI 리터러시 교육 운영 용역", ntceNticeYn="N"),
        _plan("생성형 AI 교육 컨설팅", ntceNticeYn="N", bidNtceNoList="R26BK01770009001"),
    ])
    keep, _low = prespec_service.order_plan_rows(NOW, main_ids={"g2b-R26BK01774291-000"})
    by = {r["title"]: r for r in keep}
    assert by["2026년 공주시 직원 워케이션 교육용역"]["main_out"] is True
    assert by["2026년 공주시 직원 워케이션 교육용역"]["main_notice_id"] == "g2b-R26BK01774291-000"
    assert by["생성형 AI 교육 컨설팅"]["main_out"] is True and by["생성형 AI 교육 컨설팅"]["main_notice_id"] is None  # 저장본 밖
    assert by["AI 리터러시 교육 운영 용역"]["main_out"] is False
    section = prespec_service.section([], now=NOW, main_ids={"g2b-R26BK01774291-000"})
    assert [p.main_out for p in section.plans] == [False, True, True]  # 본공고 안 난 것 먼저


def test_발주계획_본공고_id_는_차수까지() -> None:
    assert prespec_service.plan_main_id({"bidNtceNoList": "R26BK01774291001"}) == "g2b-R26BK01774291-001"
    assert prespec_service.plan_main_id({"bidNtceNoList": "R26BK01774291"}) == "g2b-R26BK01774291-000"
    assert prespec_service.plan_main_id({"bidNtceNoList": ""}) is None


# --------------------------------------------------------------------------
# 브리핑
# --------------------------------------------------------------------------


def _listing(items: list[UnifiedOpportunity], prepare: PrepareSection | None):
    from app.schemas.business_opportunity import OpportunitySummary, UnifiedOpportunityListResponse

    return UnifiedOpportunityListResponse(
        organization_id=ORG, organization_name="주식회사 샘플에듀", total_count=len(items), g2b_count=len(items), bizinfo_count=0,
        returned_count=len(items), closed_count=0, source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=len(items), open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items, prepare=prepare,
    )


def test_브리핑_발주_예정은_본공고_안_난_것만이고_사전규격은_순위표_밖() -> None:
    _plans([_plan("워케이션 교육용역", ntceNticeYn="Y", bidNtceNoList="R26BK01774291000"), _plan("AI 리터러시 교육 운영 용역")])
    bids = _annotated([_bid(1)])
    practical.order(bids, now=NOW, home_of=lambda _i: False)
    section = prespec_service.section(_annotated([_pre(1), _pre(2, main=bids[0].id)]), now=NOW, main_ids={bids[0].id})
    listing = _listing(bids, section)
    body, snapshot = brief.build_markdown(listing, now=NOW, previous=None)
    blue = body.split("# 🔵 선제준비")[1].split("# 📥")[0]
    assert "AI 리터러시 교육 운영 용역" in blue and "워케이션 교육용역" not in blue
    assert "본공고가 이미 난 것 1건" in blue and "본공고가 나온 1건" in blue
    assert set(snapshot["rows"]) == {bids[0].id}  # 순위표에 사전규격 없음
    assert snapshot["prespec_ids"] == [section.items[0].id]
    assert "나라장터 마감 전 입찰 1건" in body and "사전규격 2건(본업 · 의견 마감 남음 1건)" in body
    sheet, _notes = brief.sheet_rows(listing, now=NOW)
    plan_rows = [r for r in sheet if r[0] == "발주 예정(발주계획)"]
    assert [r[3] for r in plan_rows] == ["AI 리터러시 교육 운영 용역"]


def test_옛_순위표의_사전규격은_탈락으로_세지_않고_새_본업_사전규격만_센다() -> None:
    old = {
        "created_at": (NOW - timedelta(days=1)).isoformat(), "ranking_method": "practical", "days": 30,
        "rows": {
            "g2b-R26BK00000001-000": {"part": "매출", "rank": 1, "title": "AI 교육 운영 1"},
            "g2bpre-R26BD00000001": {"part": "매출", "rank": 2, "title": "사전규격 옛것"},  # 38차 순위표
            "g2bpre-R26BD00000009": {"part": "매출", "rank": 3, "title": "사라진 사전규격"},
        },
    }
    current = {"rows": {"g2b-R26BK00000001-000": {"part": "매출", "rank": 1}}, "prespec_ids": ["g2bpre-R26BD00000001", "g2bpre-R26BD00000002"],
               "ranking_method": "practical", "days": 30}
    diff = brief.changes(old, current)
    assert diff["gone"] == [] and diff["new"] == []
    assert diff["new_prespec"] == ["g2bpre-R26BD00000002"]
    again = brief.changes({**current, "created_at": NOW.isoformat()}, {**current, "prespec_ids": ["g2bpre-R26BD00000002", "g2bpre-R26BD00000003"]})
    assert again["new_prespec"] == ["g2bpre-R26BD00000003"]


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_선제준비_API_는_칸을_돌려준다(client, monkeypatch) -> None:
    # API 는 실제 시계를 쓴다 — 의견 마감일 없음(지나지 않음)으로 둔다.
    rows = [_pre(1, opinion=None), _bid(1), _pre(2, title="청사 시설 공사", note="본업 아님 — 시설 공사", opinion=None)]

    async def collect(**_kwargs):
        return [r.model_copy() for r in rows], "cached", None, None

    monkeypatch.setattr(opportunity_service, "_collect_procurements", collect)
    response = client.get("/api/business-opportunities/prepare", params={"organization_id": ORG})
    assert response.status_code == 200
    body = response.json()
    assert [i["id"] for i in body["items"]] == ["g2bpre-R26BD00000001"]
    assert [i["id"] for i in body["others"]] == ["g2bpre-R26BD00000002"]
    assert body["plans"] == [] and body["merged"] == []
    listing = client.get("/api/business-opportunities", params={"organization_id": ORG, "source": "g2b"}).json()
    assert listing["prepare"] is None and all(i["opportunity_type"] != "pre_spec" for i in listing["items"])
