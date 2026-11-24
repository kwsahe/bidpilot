"""43차 §2-A — 실제 마감 = 공고문 일정표의 가장 이른 마감(결정 1 · H1 · H6 · M1 · M2).

개찰일은 마감이 아니다 · 입찰 마감이 비면 「마감 미상」 · 필수 현장설명은 「필수 — 불참 시 참가 불가」.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import UnifiedOpportunity
from app.services import eligibility_engine, notice_schedule
from app.services import practical_priority as practical
from app.services import qualification_clause_service

KST = timezone(timedelta(hours=9))

# 가천대 해커톤 꼴 — 직찰 · 나라장터 입찰 마감 빈칸 · 공고문 1쪽 일정표
GACHON = [
    (1, "1. 입찰 일정"),
    (1, "가. 참가신청 마감 : 2026. 10. 30.(목) 10:00까지"),
    (1, "나. 현장설명회 : 2026. 11. 2.(월) 14:00 (미신청시 현설참여 불가)"),
    (1, "다. 입찰등록 : 2026. 11. 10.(화) 17:00까지"),
    (1, "라. 개찰 일시 : 2026. 11. 11.(수) 11:00"),
    (2, "5. 참가신청시 제출서류"),
    (2, "- 참가신청서 1부"),
    (2, "- 사업자등록증 사본 1부"),
    (2, "6. 기타"),
]


def test_공고문_일정표에서_참가신청_필수_현장설명_입찰등록을_뽑고_개찰은_버린다():
    out = notice_schedule.extract(GACHON, year_hint=2026)
    kinds = [(i["kind"], i["at"][:16]) for i in out["items"]]
    assert kinds == [
        ("application", "2026-10-30T10:00"),
        ("briefing", "2026-11-02T14:00"),
        ("registration", "2026-11-10T17:00"),
    ]
    assert out["briefing_required"] is True
    assert out["documents"] == [{"stage": "참가신청", "page": 2, "items": ["참가신청서 1부", "사업자등록증 사본 1부"]}]
    first = notice_schedule.earliest(out)
    assert first is not None and first["label"] == "참가신청 마감"


def test_범위는_끝_날짜만_평가는_마감이_아니다():
    out = notice_schedule.extract(
        [(1, "제안서 제출 기간 : 2026. 11. 12.(목) 09:00 ~ 2026. 11. 16.(월) 10:00"), (1, "제안서 평가 : 2026. 11. 18.(수)")],
        year_hint=2026,
    )
    assert [(i["kind"], i["at"][:16]) for i in out["items"]] == [("submission", "2026-11-16T10:00")]


def _g2b(**kw) -> UnifiedOpportunity:
    base = dict(
        id="g2b-X-000", source_type="g2b", opportunity_type="procurement", title="AI 교육", agency="기관",
        organization_id="org-sample", priority_rank=0, priority_label="검토", confidence="medium", score_components=[],
        next_route={"kind": "procurement_analysis", "path": "/", "label": "l"}, source="g2b",
    )
    base.update(kw)
    return UnifiedOpportunity(**base)


def test_실제_마감은_입찰_등록_공고문_일정_중_가장_이른_것():
    bid = datetime(2026, 11, 16, 10, tzinfo=KST)
    reg = datetime(2026, 11, 15, 18, tzinfo=KST)
    sched = datetime(2026, 11, 12, 10, tzinfo=KST)
    item = _g2b(deadline=bid, qualification_deadline=reg, schedule_deadline=sched, schedule_deadline_label="참가신청 마감")
    assert practical.effective_deadline(item) == sched
    assert practical.deadline_kind(item) == "참가신청 마감"
    assert practical.deadline_display(item, date(2026, 11, 1)) == "11/12(참가신청 마감) · 입찰 11/16"


def test_입찰_마감이_비면_마감_미상이고_개찰은_제출_마감이_아니다():
    item = _g2b(deadline=None, opening_at=datetime(2026, 11, 20, 11, tzinfo=KST))
    assert practical.deadline_unknown(item)
    assert practical.deadline_display(item, date(2026, 11, 1)) == "마감 미상 — 개찰 11/20(제출 마감 아님)"
    assert practical.left_phrase(item, date(2026, 11, 1)) == "마감 미상"
    assert practical.time_tier(None, 3, unknown=True) == "TU"
    # 마감 미상은 「일반 접수 중(T4)」 뒤 · 긴급(T5 · T6) 앞
    assert practical._TIER_ORDER["T4"] < practical._TIER_ORDER["TU"] < practical._TIER_ORDER["T5"]


def test_오늘_마감은_남은_오늘이_아니라_오늘_마감():
    today = date(2026, 11, 1)
    item = _g2b(deadline=datetime(2026, 11, 1, 18, tzinfo=KST))
    assert practical.left_phrase(item, today) == "오늘 마감"


@pytest.fixture()
def gachon_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    schedule = notice_schedule.extract(GACHON, year_hint=2026)
    monkeypatch.setattr(qualification_clause_service, "load", lambda _nid: {"schedule": schedule, "clauses": []})


def _rows(raw: dict, as_of: datetime) -> dict[str, eligibility_engine.EligibilityResult]:
    rows = eligibility_engine.evaluate_notice_fields(raw, as_of=as_of, notice_id="g2b-GACHON-000")
    return {r.rule_id: r for r in rows}


def test_입찰_마감_빈칸이면_공고문_일정표의_참가신청_마감으로_판정한다(gachon_schedule: None):
    raw = {"bidNtceNo": "GACHON", "bidNtceDt": "2026-10-20 09:00:00", "bidClseDt": "", "opengDt": "2026-11-11 11:00:00"}
    rows = _rows(raw, datetime(2026, 10, 25, 9, tzinfo=KST))
    deadline = rows["ELIG-BID-DEADLINE"]
    assert "참가신청 마감(공고문 일정)" in deadline.label
    assert deadline.status != "FAIL"
    briefing = rows["ELIG-BRIEFING"]
    assert briefing.status == "CHECK" and "불참 시 참가 불가" in briefing.reason


def test_참가신청_마감이_지나면_불가(gachon_schedule: None):
    raw = {"bidNtceNo": "GACHON", "bidNtceDt": "2026-10-20 09:00:00", "bidClseDt": "", "opengDt": "2026-11-11 11:00:00"}
    rows = _rows(raw, datetime(2026, 10, 31, 9, tzinfo=KST))
    assert rows["ELIG-BID-DEADLINE"].status == "FAIL"


def test_일정표도_없으면_마감_미상_확인_필요(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(qualification_clause_service, "load", lambda _nid: None)
    raw = {"bidNtceNo": "NONE", "bidNtceDt": "2026-10-20 09:00:00", "bidClseDt": "", "opengDt": "2026-11-11 11:00:00"}
    row = _rows(raw, datetime(2026, 10, 25, 9, tzinfo=KST))["ELIG-BID-DEADLINE"]
    assert row.status == "CHECK"
    assert row.reason.startswith("마감 미상") and "제출 마감 아님" in row.reason


def test_질의_기한은_일정표_마감이_아니다():
    """43차 마지막 검토 — 「제안요청서 질의 접수 기한」이 제출 마감으로 뽑혀 실제 마감이 2주 당겨졌다."""
    from app.services import notice_schedule as ns

    lines = [(1, "1. 제안요청서 질의 접수 기한 : 2026. 10. 27.(화) 17:00까지"), (1, "질의는 2026. 10. 26.(월)까지 이메일로 제출"),
             (1, "2. 입찰등록 마감 : 2026. 11. 10.(화) 10:00"), (1, "제안서 제출 마감 : 2026. 11. 12.(목) 15:00")]
    kinds = [(it["kind"], it["at"][:10]) for it in ns.extract(lines, year_hint=2026)["items"]]
    assert kinds == [("registration", "2026-11-10"), ("submission", "2026-11-12")]
