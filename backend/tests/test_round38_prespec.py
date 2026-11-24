"""38차 §3-D — 사전규격 · 발주계획(data.go.kr 15129437 · 15129462).

- `/ao/` 목록은 창을 통째로(999행씩) 받고 같은 수집 낱말로 거른다 · 담당자 이름 · 전화는 가린다 · 캐시는 따로.
- 사전규격은 나라장터 갈래의 「사전규격」 항목 — T3 선제준비 · 「확인 필요 — 본공고 전」 · 의견 마감은 입찰 마감이 아니다.
- 본공고와 잇는다(사전규격 `bidNtceNoList` · 본공고 `bfSpecRgstNo`) — 본공고 행 「사전규격 n일 전 공개」 · 사전규격 행 「본공고 나옴 →」.
- 발주계획은 목록에 넣지 않고 브리핑 「선제준비」 칸 · 엑셀 브리핑 시트에만 싣는다.

시험 자료는 2026-10-15 실제 응답(L3 · 키 없음 · 담당자 이름 · 전화 가림)이다 — `tests/fixtures/g2b_ao/`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
from app.schemas.procurement import ProcurementNotice
from app.services import (
    company_service,
    delivery_capacity_service,
    g2b_client,
    opportunity_brief_service as brief,
    practical_priority as practical,
    prespec_service,
)
from app.services.rfp_parser import REAL_NOTICE_ID_RE

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "g2b_ao"


def _items(name: str) -> list[dict[str, Any]]:
    body = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]["body"]
    return list(body["items"])


def _pre(no: str, title: str, *, rgst: str = "2026-10-10 09:00:00", opinion: str = "2026-10-18 16:00:00", bid: str = "", **extra) -> dict:
    return {
        "bfSpecRgstNo": no, "prdctClsfcNoNm": title, "orderInsttNm": "광주광역시교육청", "asignBdgtAmt": "120000000",
        "rgstDt": rgst, "rcptDt": rgst, "opninRgstClseDt": opinion, "bidNtceNoList": bid, "ofclNm": "<가림>", "ofclTelNo": "<가림>",
        "specDocFileUrl1": f"https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do?bfSpecRegNo={no}&fileType=BFDTL&fileSeq=1",
        **extra,
    }


# --------------------------------------------------------------------------
# g2b_client — /ao/ 목록
# --------------------------------------------------------------------------


def test_사전규격은_등록일_창을_999행씩_받고_전체를_다_받으면_멈춘다(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []
    body = json.loads((FIXTURES / "prespec_masked.json").read_text(encoding="utf-8"))["response"]["body"]

    async def fake_page(service, operation, params):
        calls.append((service, operation, params))
        return body

    monkeypatch.setattr(g2b_client, "_ao_page", fake_page)
    out = asyncio.run(g2b_client.fetch_prespecs(days=7, now=NOW))
    assert len(calls) == 1 and out.calls == 1 and not out.truncated
    service, operation, params = calls[0]
    assert (service, operation) == ("HrcspSsstndrdInfoService", "getPublicPrcureThngInfoServc")
    assert params["inqryDiv"] == 1 and params["numOfRows"] == 999 and params["pageNo"] == 1
    assert params["inqryBgnDt"] == "202610081200" and params["inqryEndDt"] == "202610151200"  # KST 12:00 · 7일 창
    assert out.total == body["totalCount"] and len(out.items) == len(body["items"])


def test_발주계획은_이번_달부터_석_달_창(monkeypatch) -> None:
    seen: list[dict] = []

    async def fake_page(service, operation, params):
        seen.append(params)
        return {"totalCount": 0, "items": []}

    monkeypatch.setattr(g2b_client, "_ao_page", fake_page)
    asyncio.run(g2b_client.fetch_order_plans(months=3, now=datetime(2026, 11, 20, tzinfo=KST)))
    assert seen[0]["orderBgnYm"] == "202611" and seen[0]["orderEndYm"] == "202701"
    assert seen[0]["inqryDiv"] == 1


def test_예산을_넘으면_덜_받았다고_적는다(monkeypatch) -> None:
    async def fake_page(service, operation, params):
        return {"totalCount": 5000, "items": [{"bfSpecRgstNo": f"R{params['pageNo']}"}] * 999}

    monkeypatch.setattr(g2b_client, "_ao_page", fake_page)
    out = asyncio.run(g2b_client.fetch_prespecs(now=NOW, max_pages=2))
    assert out.calls == 2 and out.truncated and out.total == 5000


def test_ao_오류에도_서비스키가_남지_않는다(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(get_settings(), "data_go_kr_service_key", "SECRET-KEY-123")

    async def broken_get(self, url, *args, **kwargs):
        raise httpx.ConnectError(f"boom {url}?serviceKey=SECRET-KEY-123")

    monkeypatch.setattr(httpx.AsyncClient, "get", broken_get)
    with pytest.raises(g2b_client.G2BClientError) as caught:
        asyncio.run(g2b_client._ao_page("HrcspSsstndrdInfoService", "getPublicPrcureThngInfoServc", {}))
    assert "SECRET-KEY-123" not in str(caught.value)


# --------------------------------------------------------------------------
# prespec_service — 거르기 · 가리기 · 저장본
# --------------------------------------------------------------------------


def test_수집_낱말은_공고명_검색과_같은_부분_일치() -> None:
    assert "교육" in prespec_service.wanted("초등돌봄교육 청사진 위탁용역")
    assert "전략 수립" in prespec_service.wanted("디지털 전환 전략수립 용역")  # 띄어쓰기 무시
    assert prespec_service.wanted("통근버스 임차용역") == []
    assert "AI" not in prespec_service.wanted("MAINTENANCE 용역")  # 짧은 영문은 경계


def test_받은_사전규격을_낱말로_거르고_가려서_합친다(monkeypatch) -> None:
    real = _items("prespec_masked.json")
    leaked = _pre("R26BD00000009", "생성형 AI 활용 교육 운영", ofclNm="홍길동", ofclTelNo="062-000-0000")
    old_keep = _pre("R26BD00000001", "AI 컨설팅 용역", rgst="2026-09-20 09:00:00")
    old_drop = _pre("R26BD00000002", "AI 컨설팅 용역 옛것", rgst="2026-09-01 09:00:00")
    prespec_service.PRESPEC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    prespec_service.PRESPEC_CACHE_FILE.write_text(json.dumps({"items": [old_keep, old_drop]}, ensure_ascii=False), encoding="utf-8")

    async def fake_fetch(**kwargs):
        return g2b_client.AoOutcome(items=[*real, leaked], calls=1, total=len(real) + 1, truncated=False)

    monkeypatch.setattr(g2b_client, "fetch_prespecs", fake_fetch)
    row = asyncio.run(prespec_service.collect_prespecs(NOW))
    saved, fetched = prespec_service.load_prespecs()
    numbers = {i["bfSpecRgstNo"] for i in saved}
    assert "R26BD00000009" in numbers and "R26BD00000001" in numbers and "R26BD00000002" not in numbers  # 30일 넘은 것은 뺀다
    assert all(prespec_service.wanted(i["prdctClsfcNoNm"]) for i in saved)
    leaked_saved = next(i for i in saved if i["bfSpecRgstNo"] == "R26BD00000009")
    assert leaked_saved["ofclNm"] == "<가림>" and leaked_saved["ofclTelNo"] == "<가림>"
    assert row["출처"] == "사전규격" and row["호출_횟수"] == 1 and row["오류"] is None
    assert fetched is not None
    assert "serviceKey" not in prespec_service.PRESPEC_CACHE_FILE.read_text(encoding="utf-8")


def test_발주계획은_낱말로_거르고_후보_규칙으로_표를_가른다(monkeypatch) -> None:
    real = _items("orderplan_masked.json")
    extra = dict(real[0], bizNm="생성형 AI 활용 직원 역량강화 교육 운영", orderPlanUntyNo="R26DD00000001", telNo="062-111-1111")

    async def fake_fetch(**kwargs):
        return g2b_client.AoOutcome(items=[*real, extra], calls=1, total=len(real) + 1, truncated=False)

    monkeypatch.setattr(g2b_client, "fetch_order_plans", fake_fetch)
    row = asyncio.run(prespec_service.collect_order_plans(NOW))
    plans, _ = prespec_service.load_order_plans()
    assert row["출처"] == "발주계획" and row["후보_건수"] == len(plans)
    assert all(p["telNo"] in ("", "<가림>") for p in plans)
    keep, low = prespec_service.order_plan_rows(NOW)
    ours = next(p for p in keep if p["title"].startswith("생성형 AI"))
    assert ours["url"] and ours["url"].startswith("https://www.g2b.go.kr/")
    assert all(p["low_reason"] for p in low)


# --------------------------------------------------------------------------
# 목록 항목 — 「사전규격」 유형
# --------------------------------------------------------------------------


def _main(no: str, pre_no: str, *, published: datetime) -> tuple[ProcurementNotice, UnifiedOpportunity]:
    notice = ProcurementNotice(
        id=f"g2b-{no}-000", notice_no=f"{no}-000", title="생성형 AI 교육", agency="광주광역시교육청", published_at=published,
        raw_data={"item": {"bfSpecRgstNo": pre_no}},
    )
    unified = UnifiedOpportunity(
        id=notice.id, source_type="g2b", opportunity_type="procurement", title=notice.title, agency=notice.agency,
        organization_id="org-sample", priority_rank=1, priority_label="검토", eligibility_gate="CHECK", confidence="medium",
        score_components=[], next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached",
        published_at=published,
    )
    return notice, unified


def _build(prespecs: list[dict], notices=(), mains=()) -> list[UnifiedOpportunity]:
    prespec_service.PRESPEC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    prespec_service.PRESPEC_CACHE_FILE.write_text(json.dumps({"items": prespecs}, ensure_ascii=False), encoding="utf-8")
    org = get_settings().default_organization_id
    return prespec_service.build_items(
        notices=list(notices), organization_id=org, profile=company_service.load_profile(org),
        capacity=delivery_capacity_service.load(org), now=NOW, main_items=list(mains),
    )


def test_사전규격_행은_본공고_전_확인_필요이고_의견_마감은_마감이_아니다() -> None:
    [row] = _build([_pre("R26BD00000011", "생성형 AI 활용 교육 운영 용역")])
    assert row.opportunity_type == "pre_spec" and row.source_type == "g2b"
    assert row.id == "g2bpre-R26BD00000011" and not REAL_NOTICE_ID_RE.match(row.id)
    assert row.eligibility_gate == "CHECK" and row.gate_reason == "확인 필요 — 본공고 전"
    assert row.deadline is None and row.opinion_deadline is not None
    assert row.deadline_text == "의견 마감 10/18 16:00 (입찰 마감 아님)"
    assert row.next_route.kind == "pre_spec" and row.main_notice_id is None
    assert row.detail_url and row.detail_url.startswith("https://www.g2b.go.kr/")
    practical.annotate([row], now=NOW, ceiling_krw=200_000_000)
    assert row.time_tier == "T3" and row.practical_group == "선제준비" and row.deadline_note is None
    assert practical.days_left(row, NOW.date()) is None  # D-day · 마감 임박순 · 긴급 칸에 들지 않는다


def test_후보가_아닌_사전규격은_사유와_함께_비추천() -> None:
    [row] = _build([_pre("R26BD00000012", "청사 시설 공사 교육장 증축")])
    assert row.relevance_note
    practical.annotate([row], now=NOW, ceiling_krw=200_000_000)
    assert row.practical_group == "비추천"


def test_본공고가_나오면_서로_잇는다() -> None:
    notice, main = _main("R26BK01770001", "R26BD00000013", published=datetime(2026, 10, 14, 10, 0, tzinfo=KST))
    [row] = _build([_pre("R26BD00000013", "AI 역량강화 교육", rgst="2026-10-04 09:00:00")], [notice], [main])
    assert row.main_notice_id == main.id
    assert row.next_route.kind == "procurement_analysis" and row.next_route.path == f"/analysis?notice={main.id}"
    assert row.next_route.label == "본공고 나옴 →"
    assert main.pre_spec_note == "사전규격 10일 전 공개"


def test_사전규격의_본공고_번호로도_잇는다() -> None:
    notice, main = _main("R26BK01770002", "", published=datetime(2026, 10, 14, 10, 0, tzinfo=KST))
    [row] = _build([_pre("R26BD00000014", "AI 컨설팅", bid="R26BK01770002")], [notice], [main])
    assert row.main_notice_id == main.id


# --------------------------------------------------------------------------
# 브리핑 — 선제준비 칸 · 🔵 줄 · 발주계획 표
# --------------------------------------------------------------------------


def _listing(items: list[UnifiedOpportunity], prepare=None):
    from app.schemas.business_opportunity import OpportunitySummary, UnifiedOpportunityListResponse

    return UnifiedOpportunityListResponse(
        organization_id="org-sample", organization_name="주식회사 샘플에듀", total_count=len(items), g2b_count=len(items), bizinfo_count=0,
        returned_count=len(items), closed_count=0, source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
        collected_by="공고명 키워드 21개 · 마감 제외 · 최근 30일", prepare=prepare,
    )


def test_브리핑_선제준비_칸과_발주계획_표를_채운다() -> None:
    """39차 결정 1 — 사전규격은 목록(`items`) 밖 「선제준비」 칸(`prepare`)으로 온다."""
    rows = _build([_pre("R26BD00000015", "생성형 AI 활용 교육 운영 용역")])
    practical.annotate(rows, now=NOW, ceiling_krw=200_000_000)
    plan = {"bizNm": "AI 리터러시 교육 운영 용역", "orderInsttNm": "전라남도", "orderYear": "2026", "orderMnth": "12",
            "sumOrderAmt": "90000000", "cntrctMthdNm": "제한경쟁", "orderPlanUntyNo": "R26DD00000002",
            "orderPlanDtlUrl": "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=R26DD00000002"}
    prespec_service.ORDERPLAN_CACHE_FILE.write_text(json.dumps({"items": [plan]}, ensure_ascii=False), encoding="utf-8")
    listing = _listing([], prespec_service.section(rows, now=NOW))
    body, _ = brief.build_markdown(listing, now=NOW, previous=None)
    assert f"사전규격 · 발주계획 — {brief.NOT_COLLECTED}" not in body and "사전규격 · 발주계획은 2단계" not in body
    assert "기관 자체공고(이메일 · PMS · 온라인폼)는 BidPilot 이 자동으로 모으지 않습니다" in body  # 그것만 남는다(§3-E — 직접 넣은 것만)
    assert "사전규격 1건" in body and "발주 예정(발주계획) 후보 1건" in body  # 🔵 줄
    section = body.split("# 🔵 선제준비")[1].split("# 🚨")[0]
    assert "생성형 AI 활용 교육 운영 용역" in section and "의견 마감 10/18 16:00 (입찰 마감 아님)" in section
    assert "[규격서](https://www.g2b.go.kr/" in section and "본공고 전" in section
    assert "AI 리터러시 교육 운영 용역" in section and "2026-12" in section and "[발주계획](https://www.g2b.go.kr/" in section
    assert "사전규격 1건(본업 · 의견 마감 남음 1건) · 발주계획 1건" in body  # 본 것 줄 — 「마감 전 나라장터」와 따로(PRESPEC-07)
    g2b_pool = body.split("# 나라장터 후보")[1].split("#")[0]
    assert "생성형 AI 활용 교육 운영 용역" not in g2b_pool  # 사전규격은 나라장터 후보 표에 섞지 않는다
    sheet, notes = brief.sheet_rows(listing, now=NOW)
    assert any(r[0] == "발주 예정(발주계획)" and r[3] == "AI 리터러시 교육 운영 용역" for r in sheet)
    assert any(r[6].startswith("의견 마감") for r in sheet if r[3] == "생성형 AI 활용 교육 운영 용역")


def test_발주계획_링크는_나라장터_주소만() -> None:
    plan = {"bizNm": "AI 교육 운영", "orderInsttNm": "기관", "orderPlanDtlUrl": "javascript:alert(1)"}
    prespec_service.ORDERPLAN_CACHE_FILE.write_text(json.dumps({"items": [plan]}, ensure_ascii=False), encoding="utf-8")
    keep, _low = prespec_service.order_plan_rows(NOW)
    assert keep and keep[0]["url"] is None


# --------------------------------------------------------------------------
# 매일 받기 — 두 출처
# --------------------------------------------------------------------------


def test_매일_받기는_나라장터가_열렸을_때만_사전규격_발주계획을_받는다(monkeypatch) -> None:
    from tests.test_round38_strength import _load_collect_daily

    daily = _load_collect_daily()
    called: list[str] = []

    async def fake(name):
        called.append(name)
        return {"출처": name, "결과": "g2b", "받아온_건수": 0, "후보_건수": 0, "호출_횟수": 1}

    async def nothing(*args, **kwargs):
        return {"출처": "x", "결과": "g2b"}

    monkeypatch.setattr(daily, "_collect_g2b", nothing)
    monkeypatch.setattr(daily, "_collect_bizinfo", nothing)
    monkeypatch.setattr(daily, "_collect_g2b_documents", nothing)
    monkeypatch.setattr(daily, "_collect_bizinfo_documents", nothing)
    monkeypatch.setattr(daily.prespec_service, "collect_prespecs", lambda: fake("사전규격"))
    monkeypatch.setattr(daily.prespec_service, "collect_order_plans", lambda: fake("발주계획"))
    monkeypatch.setattr(daily.procurement_service, "live_fetch_enabled", lambda: True)
    monkeypatch.setattr(daily.bizinfo_service, "live_fetch_enabled", lambda: False)
    rows = asyncio.run(daily.collect(30, g2b_documents=0))
    assert called == ["사전규격", "발주계획"] and {"사전규격", "발주계획"} <= {r["출처"] for r in rows}

    called.clear()
    monkeypatch.setattr(daily.procurement_service, "live_fetch_enabled", lambda: False)
    asyncio.run(daily.collect(30, g2b_documents=0))
    assert called == []
