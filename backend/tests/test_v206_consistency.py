"""2.0.6 — 화면끼리 모순 · 미연결(대표 10-27 「또 이런 문제가 없는지 전체 확인」) 중 서버 쪽.

약속.

1. 「검토 중」은 지원사업(기업마당) · 직접 넣은 공고의 결정을 입찰로 다루지 않는다 — 제목 · 결정 낱말 · 갈 곳이 그 화면 것이다(links-1).
   대시보드 띠 「참여 미정 — 마감 전 n」도 같은 마감으로 센다.
2. 지원사업 신청 분석의 「우선 검토」는 목록과 같은 규칙(같은 출처 상위 15%)이다(values-4).
3. 간접 참여(공급기업) 사업은 브리핑 판단 칸도 「간접 참여」다(values-6).
4. 출처를 읽지 못한 날의 브리핑 · 엑셀은 그 사실을 적고, 그 순위표는 남기지 않는다(fallback-4).
5. 선제준비 응답은 나라장터를 못 읽은 사유를 싣는다(fallback-2).
6. 후보함 · 열어 본 곳 저장본이 깨지면 빈 목록으로 덮어쓰지 않고 오류를 올린다(브리핑은 막지 않고 파일도 옮기지 않는다).
7. 「검토 중」 탭과 대시보드 띠 「참여 미정 — 마감 전 · 지남」은 같은 판단 · 같은 마감 · 같은 범위다(cross-1 · backend-1 · backend-4 · backend-5).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core import storage
from app.core.config import get_settings
from app.schemas.business_opportunity import (
    NextRoute,
    OpportunitySummary,
    PrepareSection,
    UnifiedOpportunity,
    UnifiedOpportunityListResponse,
)
from app.schemas.decision import DecisionRequest
from app.schemas.manual_notice import ManualNoticeInput
from app.schemas.organization import AnalysisContext
from app.services import (
    bizinfo_service,
    daily_digest_service,
    decision_service,
    manual_notice_service,
    notice_inbox_service,
    opportunity_service,
    review_queue_service,
    support_application_service,
    watchlist_service,
)
from app.services import opportunity_brief_service as brief
from app.services import opportunity_priority as priority

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)
ORG = get_settings().default_organization_id
PROGRAM = "bizinfo-PBLN_V206"


@pytest.fixture(autouse=True)
def own_generated_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """파싱 결과 폴더는 이 파일만의 빈 폴더 — 공용 사본의 「파싱된 공고」가 띠 수에 섞이지 않게(test_review_queue 와 같은 이유).

    공개 결정 · 검토 폴더(data/public/decisions · reviews — git 밖)도 빈 폴더로. 이 PC 에만 있는 옛 발견 기록(09-04)이
    「검토 중」 후보로 띠 「마감 지남」에 하나 더 섞여 worktree 에서는 통과하고 본 저장소에서는 실패했다(10-31 최종 점검).
    """
    from app.services import decision_service, review_service, rfp_parser

    own = tmp_path / "generated"
    own.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", own)
    monkeypatch.setattr(decision_service, "DECISION_DIR", tmp_path / "public_decisions")
    monkeypatch.setattr(review_service, "REVIEW_DIR", tmp_path / "public_reviews")


@pytest.fixture()
def context() -> AnalysisContext:
    return AnalysisContext(organization_id=ORG, evidence_scope="internal")


@pytest.fixture()
def bizinfo_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "bizinfo_cache.json"
    path.write_text(json.dumps({"items": [{
        "pblancId": "PBLN_V206", "pblancNm": "중소기업 AI 교육 바우처", "jrsdInsttNm": "시험 기관",
        "reqstBeginEndDe": "2026-10-01 ~ 2026-11-30",
    }]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", path)
    return path


def seed_notice_cache(cache_file: Path) -> None:
    """나라장터 저장본(띠가 「받은 적 없음」으로 일찍 끝나지 않게 한 건)."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"fetched_at": NOW.isoformat(), "days": 30, "total_fetched": 1, "notices": [{
        "notice": {
            "id": "g2b-A-000", "notice_no": "A-000", "title": "생성형 AI 교육 운영", "agency": "기관",
            "published_at": (NOW - timedelta(days=1)).isoformat(), "deadline_at": (NOW + timedelta(days=5)).isoformat(),
            "budget": None, "region": None, "description": None, "source_url": None, "raw_data": {},
        },
        "candidate": {}, "pinned": False,
    }]}, ensure_ascii=False), encoding="utf-8")


def decide(pid: str, status: str, context: AnalysisContext) -> None:
    decision_service.save_decision(
        pid, DecisionRequest(status=status, reasons=["시험 기록"], decided_by="시험"), gate=None, context=context
    )


def row_of(queue: dict, pid: str) -> dict:
    return next(row for row in queue["items"] if row["procurement_id"] == pid)


# --------------------------------------------------------------------------
# 1. 검토 중 — 지원사업 · 직접 넣은 공고 (links-1)
# --------------------------------------------------------------------------


def test_검토_중_지원사업은_제목_신청_낱말_지원사업_화면으로(bizinfo_cache: Path, context: AnalysisContext) -> None:
    decide(PROGRAM, "GO", context)
    row = row_of(review_queue_service.build(context=context, now=NOW), PROGRAM)
    assert row["kind"] == "support"
    assert row["title"] == "중소기업 AI 교육 바우처", "id 글자를 제목으로 쓰지 않는다"
    assert row["notice_known"] is True and row["queue_state"] == "live", "기업마당 목록에 살아 있는 사업이다"
    assert row["open_path"] == f"/support/{PROGRAM}"
    assert row["decision_label"] == "신청", "지원사업 결정 칸과 같은 낱말"
    assert "요구사항" not in row["next_step"], "제안요청서 · 정리표는 입찰 일이다"
    assert row["last_activity_kind"] == "신청 결정", "같은 줄의 결정 낱말(신청)과 맞춘다 — 「참여 결정」이 함께 보였다"


def test_검토_중_직접_넣은_수혜_공고는_직접_넣기_탭으로(context: AnalysisContext) -> None:
    saved = manual_notice_service.create(ORG, ManualNoticeInput(
        url="https://www.kosac.re.kr/menus/274/bns/PBANC_V206", title="AI 교육 지원금 공모", agency="시험 재단",
        deadline=datetime(2026, 11, 20, 18, 0, tzinfo=KST), recruit="benefit", methods=["이메일"],
    ))
    pid = saved.notice.id
    decide(pid, "HOLD", context)
    row = row_of(review_queue_service.build(context=context, now=NOW), pid)
    assert row["kind"] == "manual"
    assert row["title"] == "AI 교육 지원금 공모"
    assert row["open_path"] == f"/opportunities?tab=manual&manual={pid}"
    # backend-4 — 「검토 중」(HOLD)은 띠 「참여 미정」이 결정된 것으로 센다. 「신청 여부 결정」 기대는 탭만 정할 일이라 해
    # 띠 숫자 · 「참여 미정만」에서 빠지던 결함을 지키던 것이라 입찰 HOLD 와 같은 꼴(「없음 — 검토 중」)로 바꿨다.
    assert row["decision_label"] == "검토 중" and row["next_step"] == "없음 — 검토 중"
    assert row["queue_state"] == "live"


def test_목록에도_사본에도_없는_지원사업은_id_를_쓰고_지어내지_않는다(bizinfo_cache: Path, context: AnalysisContext) -> None:
    decide("bizinfo-PBLN_GONE", "HOLD", context)
    row = row_of(review_queue_service.build(context=context, now=NOW), "bizinfo-PBLN_GONE")
    assert row["title"] == "bizinfo-PBLN_GONE" and row["notice_known"] is False
    assert row["queue_state"] == "gone" and row["open_path"] is None


def test_띠의_마감_전_수는_지원사업_마감으로_센다(
    bizinfo_cache: Path, notice_cache_file: Path, context: AnalysisContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """결정 전으로 되돌린 지원사업 — 예전에는 나라장터 목록에 없어 「마감 지남 · 목록에서 내려감」으로 셌다."""
    seed_notice_cache(notice_cache_file)

    async def _none(*_a: object, **_k: object) -> set[str]:
        return set()

    monkeypatch.setattr(daily_digest_service, "_blocked_ids", _none)
    decide(PROGRAM, "UNREVIEWED", context)
    digest = asyncio.run(daily_digest_service.build(context=context, now=NOW))
    assert PROGRAM in digest["pending_ids"]
    assert digest["awaiting_open"] == 1 and digest["awaiting_closed"] == 0


def _band_and_tab(context: AnalysisContext, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, dict]:
    async def _none(*_a: object, **_k: object) -> set[str]:
        return set()

    monkeypatch.setattr(daily_digest_service, "_blocked_ids", _none)
    digest = asyncio.run(daily_digest_service.build(context=context, now=NOW))
    return digest, review_queue_service.build(context=context, now=NOW)


def test_등록마감이_지난_입찰은_탭도_띠도_마감_지남(
    notice_cache_file: Path, context: AnalysisContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(2.0.6 cross-1) 탭은 입찰 마감만 봐 「살아 있는 공고 · D-5」, 띠는 실제 마감(등록마감)으로 「지남」이었다."""
    seed_notice_cache(notice_cache_file)
    payload = json.loads(notice_cache_file.read_text(encoding="utf-8"))
    payload["notices"][0]["notice"]["raw_data"] = {"qualification_deadline": "2026-10-26 18:00:00"}  # 입찰 마감(+5일)보다 이른 등록마감 · 지남
    notice_cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    decide("g2b-A-000", "UNREVIEWED", context)
    digest, queue = _band_and_tab(context, monkeypatch)
    row = row_of(queue, "g2b-A-000")
    assert row["queue_state"] == "closed"
    assert datetime.fromisoformat(row["deadline_at"]) == datetime(2026, 10, 26, 18, 0, tzinfo=KST), "D-day 도 실제 마감으로"
    assert digest["awaiting_open"] == 0 and digest["awaiting_closed"] == 1


def test_관련_낮음_입찰과_마감일_없는_사업은_탭도_띠도_마감_전(
    bizinfo_cache: Path, notice_cache_file: Path, context: AnalysisContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(2.0.6 backend-1) 띠는 좁은 목록(관련 낮음 뺌)에서 마감을 찾고 마감 없음을 「지남」으로 셌다 — 탭은 둘 다 「살아 있는 공고」였다."""
    import dataclasses

    from app.services import procurement_service

    seed_notice_cache(notice_cache_file)
    payload = json.loads(bizinfo_cache.read_text(encoding="utf-8"))
    payload["items"][0]["reqstBeginEndDe"] = "상시 접수"
    bizinfo_cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    wide = procurement_service.cached_only(include_low=True)
    narrow = dataclasses.replace(wide, notices=[])  # g2b-A-000 을 관련 낮음으로 — 넓은 저장본에만 있다
    monkeypatch.setattr(procurement_service, "cached_only", lambda include_low=False: wide if include_low else narrow)
    decide("g2b-A-000", "UNREVIEWED", context)
    decide(PROGRAM, "UNREVIEWED", context)
    digest, queue = _band_and_tab(context, monkeypatch)
    assert row_of(queue, PROGRAM)["deadline_at"] is None
    assert {row_of(queue, pid)["queue_state"] for pid in ("g2b-A-000", PROGRAM)} == {"live"}
    assert digest["awaiting_open"] == 2 and digest["awaiting_closed"] == 0


def test_직접_넣은_공고는_참가신청_마감이_이르면_그쪽_결정_전은_미정(context: AnalysisContext) -> None:
    """(2.0.6 cross-1 · backend-5) 입찰 마감만 봐 직접 넣기 행과 D-day 가 달랐고, 결정 전은 「결정 결정 전」으로 찍혔다."""
    apply = datetime(2026, 11, 10, 18, 0, tzinfo=KST)
    saved = manual_notice_service.create(ORG, ManualNoticeInput(
        url="https://www.kosac.re.kr/menus/274/bns/PBANC_V206B", title="AI 교육 바우처 공모", agency="시험 재단",
        deadline=datetime(2026, 11, 20, 18, 0, tzinfo=KST), apply_deadline=apply, recruit="benefit", methods=["이메일"],
    ))
    pid = saved.notice.id
    decide(pid, "UNREVIEWED", context)
    row = row_of(review_queue_service.build(context=context, now=NOW), pid)
    assert datetime.fromisoformat(row["deadline_at"]) == apply
    assert row["decision_label"] == "미정", "입찰 줄과 같은 낱말(화면이 「결정 」을 붙인다)"
    assert row["next_step"] == "신청 여부 결정"


def test_띠의_참가_불가_집합은_저장본으로_대신한_날도_가려낸다(context: AnalysisContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """실시간 받기가 실패해 저장본으로 대신하면 오류 글과 항목이 함께 온다 — 브리핑처럼 실패로 보지 않는다(불가를 함께 세지 않게)."""
    blocked = _support_item(0, 40, id="g2b-FAIL-000", source_type="g2b", opportunity_type="procurement", eligibility_gate="FAIL")
    kept = _support_item(1, 70, id="g2b-OK-000", source_type="g2b", opportunity_type="procurement")

    async def _fallback(**_kwargs: object) -> UnifiedOpportunityListResponse:
        return _listing([blocked, kept], errors={"g2b": "나라장터 호출 실패 — 저장본으로 대신"})

    monkeypatch.setattr(opportunity_service, "list_opportunities", _fallback)
    assert asyncio.run(daily_digest_service._blocked_ids(context, NOW)) == {"g2b-FAIL-000"}

    async def _empty(**_kwargs: object) -> UnifiedOpportunityListResponse:
        return _listing([], errors={"g2b": "나라장터 수집 오류: 시험"})

    monkeypatch.setattr(opportunity_service, "list_opportunities", _empty)
    assert asyncio.run(daily_digest_service._blocked_ids(context, NOW)) is None, "칸이 빈 실패는 「불가 0」이 아니다"


def test_띠의_참가_불가_집합을_못_구하면_사유를_적는다(
    notice_cache_file: Path, context: AnalysisContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_notice_cache(notice_cache_file)

    async def _failed(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(daily_digest_service, "_blocked_ids", _failed)
    digest = asyncio.run(daily_digest_service.build(context=context, now=NOW))
    assert any("참가 불가 공고를 가려내지 못해" in note for note in digest["notes"])


# --------------------------------------------------------------------------
# 2. 지원사업 상세 라벨 = 목록 규칙 (values-4)
# --------------------------------------------------------------------------


def _support_item(index: int, score: int, **extra: object) -> UnifiedOpportunity:
    return UnifiedOpportunity(**{
        "id": f"bizinfo-T{index:03d}", "source_type": "bizinfo", "opportunity_type": "support_program",
        "title": f"사업 {index}", "agency": "기관", "organization_id": ORG, "company_priority_score": score,
        "priority_rank": 0, "priority_label": "미확인", "eligibility_gate": "CHECK", "confidence": "medium",
        "score_components": [], "next_route": NextRoute(kind="support_application", path="/", label="열기"), "source": "cached",
        **extra,
    })


def test_상세_라벨은_목록과_같은_상위_15퍼센트_규칙() -> None:
    today = NOW.astimezone(KST).date()
    company = object()
    items = [_support_item(0, 76), _support_item(1, 70), *(_support_item(i, 50) for i in range(2, 10))]
    key = (ORG, 0, today, company, opportunity_service._inputs_stamp())
    opportunity_service._SUPPORT_MEMO[key] = (items, "cached", None, True, None)
    label = support_application_service._listed_priority_label("bizinfo-T000", organization_id=ORG, today=today, company=company)
    assert priority.label_of(76, closed=False) == "검토", "점수만 보면 「검토」"
    assert label == "우선 검토", "목록은 같은 출처 상위 15% 라 「우선 검토」"
    assert items[0].priority_label == "미확인", "메모 속 항목은 고치지 않는다(사본으로 매긴다)"


def test_상세의_분류_칸은_목록과_같은_함수로_매긴다(monkeypatch: pytest.MonkeyPatch) -> None:
    """(2.0.6 cross-2) 실무순 회사 목록 · 레이더는 분류 칸인데 지원사업 신청 분석만 「우선 검토 · 검토」였다 — 응답에 같은 칸을 싣는다."""
    today = NOW.astimezone(KST).date()
    company = object()
    item = _support_item(0, 70, deadline=NOW + timedelta(days=3))
    key = (ORG, 0, today, company, opportunity_service._inputs_stamp())
    opportunity_service._SUPPORT_MEMO[key] = ([item], "cached", None, True, None)
    monkeypatch.setattr(storage, "utc_now", lambda: NOW)
    group = support_application_service._listed_practical_group("bizinfo-T000", organization_id=ORG, today=today, company=company)
    assert group == "긴급", "마감 3일 — 목록 행과 같은 칸"
    assert item.practical_group is None, "메모 속 항목은 고치지 않는다(사본에 매긴다)"
    assert support_application_service._listed_practical_group("bizinfo-NONE", organization_id=ORG, today=today, company=company) is None
    source = Path(support_application_service.__file__).read_text(encoding="utf-8")
    assert '"ranking_method": opportunity_service.ranking_method_of(context.organization_id)' in source


def test_상세_라벨은_관련_낮음을_후순위로_둔다() -> None:
    source = Path(support_application_service.__file__).read_text(encoding="utf-8")
    assert "not judgement.relevance.related and judgement.relevance.reason" in source
    assert "_listed_priority_label(program.id" in source


# --------------------------------------------------------------------------
# 3 · 4. 브리핑 (values-6 · fallback-4)
# --------------------------------------------------------------------------


def _listing(items: list[UnifiedOpportunity], *, errors: dict[str, str | None]) -> UnifiedOpportunityListResponse:
    return UnifiedOpportunityListResponse(
        organization_id=ORG, organization_name="시험 회사", total_count=len(items),
        g2b_count=sum(1 for i in items if i.source_type == "g2b"), bizinfo_count=sum(1 for i in items if i.source_type == "bizinfo"),
        returned_count=len(items), closed_count=0, source_status={}, source_errors=errors, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
    )


def test_간접_참여는_브리핑에서도_간접_참여() -> None:
    item = _support_item(0, 70, practical_group="조건부", participation="공급기업으로 참여")
    assert brief.verdict_word(item) == "간접 참여"
    assert "간접 참여" in brief.VERDICTS
    source = Path(brief.__file__).read_text(encoding="utf-8")
    assert "간접 참여 → 간접 참여" in source, "브리핑 판단 낱말 풀이도 이 낱말을 설명한다"
    assert brief.verdict_word(_support_item(1, 70, practical_group="조건부")) == "조건부 검토"


def test_나라장터를_못_읽은_날_브리핑은_적고_순위표를_남기지_않는다() -> None:
    listing = _listing([_support_item(0, 70, practical_group="신규+여유")], errors={"g2b": "나라장터 수집 오류: 시험", "bizinfo": None})
    body, snapshot = brief.build_markdown(listing, now=NOW, previous=None)
    assert "나라장터를 읽지 못했습니다 — 나라장터 수집 오류: 시험" in body
    assert snapshot["source_failed"] == ["g2b"]
    assert brief.save_snapshot(ORG, snapshot, now=NOW) is None, "실패본이 그날 순위표로 굳지 않는다"
    _rows, notes = brief.sheet_rows(listing, now=NOW)
    assert any("나라장터를 읽지 못했습니다" in note for note in notes), "엑셀 브리핑 시트도 같은 표지"
    previous = {"rows": {"g2b-OLD": {"part": "매출", "rank": 1, "source": "g2b", "title": "어제 공고"}}}
    assert not brief.changes(previous, snapshot).get("gone"), "못 읽은 출처의 어제 공고를 「탈락」으로 적지 않는다"


def test_오류가_있어도_항목이_왔으면_실패로_적지_않는다() -> None:
    listing = _listing([_support_item(0, 70, practical_group="신규+여유")], errors={"bizinfo": "기업마당 호출 실패 — 저장본으로 대신"})
    assert brief.failed_sources(listing) == {}


# --------------------------------------------------------------------------
# 5. 선제준비 (fallback-2)
# --------------------------------------------------------------------------


def test_선제준비는_나라장터를_못_읽은_사유를_싣는다(context: AnalysisContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import deps, insights

    async def _listing_fail(**_kwargs: object) -> UnifiedOpportunityListResponse:
        failed = _listing([], errors={"g2b": "나라장터 수집 오류: 시험"})
        failed.prepare = PrepareSection()
        return failed

    monkeypatch.setattr(deps, "context_or_400", lambda *_a, **_k: context)
    monkeypatch.setattr(opportunity_service, "list_opportunities", _listing_fail)
    section = asyncio.run(insights.prepare_section(organization_id=ORG, evidence_scope="internal", part="main"))
    assert section.source_error == "나라장터 수집 오류: 시험"


def test_선제준비는_저장본으로_대신한_날을_실패로_적지_않는다(context: AnalysisContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """오류 글이 있어도 나라장터 항목이 왔으면(저장본으로 대신) 사전규격은 골라졌다 — 브리핑과 같은 판단."""
    from app.api import deps, insights

    async def _listing_fallback(**_kwargs: object) -> UnifiedOpportunityListResponse:
        served = _listing(
            [_support_item(0, 70, id="g2b-OK-000", source_type="g2b", opportunity_type="procurement")],
            errors={"g2b": "나라장터 호출 실패 — 저장본으로 대신"},
        )
        served.prepare = PrepareSection()
        return served

    monkeypatch.setattr(deps, "context_or_400", lambda *_a, **_k: context)
    monkeypatch.setattr(opportunity_service, "list_opportunities", _listing_fallback)
    section = asyncio.run(insights.prepare_section(organization_id=ORG, evidence_scope="internal", part="main"))
    assert section.source_error is None


# --------------------------------------------------------------------------
# 6. 깨진 저장본 — 덮어쓰지 않는다
# --------------------------------------------------------------------------


def test_후보함이_깨지면_붙여넣기가_빈_목록으로_덮어쓰지_않는다() -> None:
    path = notice_inbox_service.path_of(ORG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{깨진", encoding="utf-8")
    with pytest.raises(storage.CorruptJsonError):
        notice_inbox_service.paste(ORG, "| 공고명 | 링크 |\n|---|---|\n| 시험 | https://www.example.go.kr/a |")
    assert not path.exists(), "새 파일을 쓰지 않았다(원본은 .corrupt-* 로 옮겨져 있다)"
    assert list(path.parent.glob(f"{path.name}.corrupt-*"))
    path.write_text("{깨진", encoding="utf-8")
    assert notice_inbox_service.pending(ORG) == [], "브리핑은 막지 않는다"
    # backend-2 — 브리핑이 먼저 읽어도 파일을 옮기지 않는다(옮기면 화면은 409 없이 빈 후보함을 보고 그 위에 저장했다)
    assert path.exists()
    with pytest.raises(storage.CorruptJsonError):
        notice_inbox_service.load(ORG)


def test_열어_본_곳이_깨지면_열기가_처음_목록으로_덮어쓰지_않는다() -> None:
    path = watchlist_service.path_of(ORG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{깨진", encoding="utf-8")
    first = watchlist_service.defaults()[0].id
    with pytest.raises(storage.CorruptJsonError):
        watchlist_service.mark_opened(ORG, first)
    assert not path.exists()
    path.write_text("{깨진", encoding="utf-8")
    assert watchlist_service.opened_today(ORG, now=NOW) == (0, 0), "브리핑은 막지 않는다"
    assert path.exists(), "브리핑이 먼저 읽어도 옮기지 않는다 — 첫 409 를 화면이 받는다(backend-2)"
    with pytest.raises(storage.CorruptJsonError):
        watchlist_service.load(ORG)


def test_깨진_파일_409_는_다음에_일어날_일을_말한다(tmp_path: Path) -> None:
    """(2.0.6 safety-1) 옮긴 뒤 다시 시도하면 처음 상태로 열린다 — 막지 않고, 원본 자리와 그 일을 미리 말한다."""
    from app import main

    moved = tmp_path / "notice_inbox.json.corrupt-20261027T030000Z"
    response = asyncio.run(main.corrupt_json(None, storage.CorruptJsonError(tmp_path / "notice_inbox.json", moved)))  # type: ignore[arg-type]
    detail = json.loads(response.body)["detail"]
    assert response.status_code == 409
    assert f"원본은 {moved.name} 에 그대로 있습니다" in detail and "다시 시도하면 옛 기록 없이 처음 상태에서 새로 시작합니다" in detail
    kept = asyncio.run(main.corrupt_json(None, storage.CorruptJsonError(tmp_path / "notice_inbox.json", None)))  # type: ignore[arg-type]
    assert "다시 시도하면" not in json.loads(kept.body)["detail"], "옮기지 못했으면 다음에도 같은 409 다"


def test_queue_place_opening_passed_without_any_deadline_is_closed() -> None:
    """(2.0.6 마지막 검토 back-1) 마감이 아무 데도 없는 입찰은 개찰이 지나면 탭 · 띠 모두 「지남」 — 통합 목록 closed 와 같은 규칙. 마감은 지어내지 않는다."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.services import review_queue_service

    moment = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
    past = SimpleNamespace(deadline_at=None, raw_data={"opening_at": "2026-09-15 10:00:00"})
    future = SimpleNamespace(deadline_at=None, raw_data={"opening_at": (moment + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")})
    by_id = {"g2b-past": past, "g2b-future": future}
    assert review_queue_service.queue_place("g2b-past", by_id=by_id, pinned_ids=set(), others={}, moment=moment) == ("closed", None)
    assert review_queue_service.queue_place("g2b-future", by_id=by_id, pinned_ids=set(), others={}, moment=moment) == ("live", None)
