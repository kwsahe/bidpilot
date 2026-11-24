"""44차 §2-A — 마감을 바르게 읽기(R36-J-01 · J-02 · J-05 · J-03 · M3). 호출 없음.

- 「제출 시작일시」는 마감이 아니다 · 범위 「A ~ B」는 끝 · 끝이 날만 적혔으면 앞 날짜의 연 · 월을 이어받는다(조달청 표준 공고문 · 1759170).
- 표 머리줄은 칸 수가 날짜 수와 같을 때만 칸 순서로 짝짓는다 · 「위와 같이 공고합니다」 뒤 날짜는 버린다(1773618 연암대 · 1747255 계명대).
- 괄호 안 · 「점심」 뒤 시각은 읽지 않는다 · 「오후 N시」 = N+12 · 같은 날 둘이면 이른 시각(1763016 · 1739338).
- 입찰 마감이 있어도 공고문 일정 마감이 더 이르면 상세 판정에도 그 줄(목록 실제 마감과 같은 날 · 촉박도 그 마감으로).
- 시각을 모르는 마감은 「MM/DD(시각 원문 확인)」 — 판정 · 순서는 그날 끝으로 센다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import UnifiedOpportunity
from app.services import eligibility_engine, notice_schedule
from app.services import practical_priority as practical
from app.services import qualification_clause_service

KST = timezone(timedelta(hours=9))
PUBLISHED = datetime(2026, 9, 28, tzinfo=KST)


def _items(lines: list[tuple[int, str]]) -> list[tuple[str, str, bool]]:
    out = notice_schedule.extract(lines, year_hint=2026, not_before=PUBLISHED)
    return [(i["kind"], i["at"][:16], i["time_known"]) for i in out["items"]]


def _first(lines: list[tuple[int, str]]) -> str | None:
    first = notice_schedule.earliest(notice_schedule.extract(lines, year_hint=2026, not_before=PUBLISHED))
    return first["at"][:16] if first else None


# 조달청 표준 공고문 꼴(1759170 「2027년 이러닝 콘텐츠 개발 및 운영관리 용역」)
PPS_STANDARD = [
    (2, "2. 입찰(개찰) 일시 및 장소"),
    (2, "○ 제안서ㆍ가격 전자입찰서 제출 시작일시: 2026/11/12(목) 10:00"),
    (2, "○ 제안서ㆍ가격 전자입찰서 제출 마감일시: 2026/11/17(화) 10:00"),
    (2, "○ 개찰일시: 제안서 평가 완료 후"),
]


def test_J01_제출_시작일시는_마감이_아니다():
    assert _items(PPS_STANDARD) == [("submission", "2026-11-17T10:00", True)]


def test_J01_끝이_날만_적힌_범위는_앞_날짜의_연월을_잇는다():
    assert _first([(1, "○ 입찰서 접수기간 : 2026년 11월 12일(목) 09시 ~ 17일(화) 18시까지")]) == "2026-11-17T18:00"
    # 날이 작아지면 다음 달
    assert _first([(1, "○ 제안서 접수기간 : 2026. 11. 28.(토) 09:00 ~ 2.(수) 18:00까지")]) == "2026-12-02T18:00"
    # 「부터」로 끝난 줄은 시작 쪽 — 다음 줄의 「까지」가 마감
    assert _first([(1, "5. 제안서 제출"), (1, "○ 제출기간: 2026. 11. 12.(목) 09:00부터"), (1, "2026. 11. 17.(화) 18:00까지 제출")]) == "2026-11-17T18:00"


# 연암대(1773618) — 일정표의 머리줄 조각 「접수 마감 대상자 통보」(4칸)와 날짜 다섯 · 실제 접수 마감은 2쪽 「10월 26일(월) 15시까지 … 직접 제출」
YONAM = [
    (1, "2. 일정안내"),
    (1, "제안서  제안서 발표"),
    (1, "입찰 공고 제안서 발표 및 평가 낙찰자 통보"),
    (1, "접수 마감 대상자 통보"),
    (1, "2026.10.15.(목) 2026.10.26.(월) 2026.10.26.(월) 2026.10.29.(목) 2026.10.30.(금)"),
    (1, "15:00 15:00 16:00 이후 14:00 13:00 이후"),
    (2, "마. 2026년 10월 26일(월) 15시까지 실적증명서 1부, 제안서 및 제안요약서 각 7부(USB 1매 별도)"),
    (2, "등 대학에서 요구하는 입찰의 모든 서류를 직접 제출(우편 및 팩스 제출 불가) 하여야 하며, 미제출"),
]


def test_J02_표_머리줄은_첫_날짜에_붙이지_않는다():
    assert _items(YONAM) == [("submission", "2026-10-26T15:00", True)]


def test_J02_머리줄_칸_수와_날짜_수가_같으면_칸_순서로_짝짓는다():
    lines = [(1, "참가신청 현장설명 입찰등록"), (1, "2026. 10. 30.(금) 2026. 11. 2.(월) 2026. 11. 10.(화)")]
    assert [k for k, *_ in _items(lines)] == ["application", "briefing", "registration"]


def test_J02_서명란_날짜는_마감이_아니다():
    lines = [
        (2, "6. 입찰등록 및 서류접수"),
        (2, "가. 일시 및 장소: 2026. 11. 9.(월) 11:00까지, 성서캠퍼스 구매팀(행소관 235호)"),
        (4, "차. 제안서 제출 시「고등교육법」제2조에 따라"),
        (4, "위와 같이 공고합니다."),
        (4, "2026. 9. 28."),
    ]
    assert _items(lines) == [("registration", "2026-11-09T11:00", True)]


def test_J02_앞선_머리말_대체는_일시_기한_까지_마감이_있을_때만():
    # 머리말은 「제출」인데 날짜 줄에 마감 낱말이 없다 — 머리말로 갈래를 짓지 않는다
    assert _items([(1, "3. 제안서 제출"), (1, "2026. 10. 20.(화) 서울특별시 교육청")]) == []
    assert _items([(1, "3. 제안서 제출"), (1, "일   시"), (1, "2026. 10. 20.(화) 17:00")]) == [("submission", "2026-10-20T17:00", True)]


def test_J05_괄호_점심_뒤_시각은_읽지_않는다():
    lines = [(1, "사. 입찰참가신청 및 사업제안서 제출"), (1, "일   시"), (1, "2026. 10. 30.(금) 09:00~18:00 [점심시간 12:00~13:00 접수불가]")]
    assert _items(lines) == [("application", "2026-10-30T18:00", True)]
    lines = [(1, "5. 입찰참가등록 및 제안서 제출"), (1, "가. 제출일시 : 2026. 11. 2.(월) 10:00 ~ 16:00  (※점심시간 접수불가 12:00 ~ 13:00)")]
    assert _first(lines) == "2026-11-02T16:00"
    # 괄호 밖에 시각이 없으면 괄호 안 시각을 쓴다
    assert _first([(1, "다. 입찰 참가신청"), (1, "1) 일 시 : 2026.10.26. (10:00 ~ 17:00)")]) == "2026-10-26T17:00"


def test_J05_오후는_12시간을_더하고_같은_날_둘이면_이른_시각():
    assert _first([(1, "○ 제안서 제출 마감: 2026. 11. 5.(목) 오후 6시까지")]) == "2026-11-05T18:00"
    lines = [(1, "○ 제안서 제출 마감: 2026. 11. 5.(목) 18:00"), (2, "○ 제안서 제출 마감일시 2026. 11. 5.(목) 10:00까지")]
    assert _items(lines) == [("submission", "2026-11-05T10:00", True)]


def _rows(raw: dict, as_of: datetime) -> dict[str, eligibility_engine.EligibilityResult]:
    rows = eligibility_engine.evaluate_notice_fields(raw, as_of=as_of, notice_id="g2b-SCHED-000")
    return {r.rule_id: r for r in rows}


@pytest.fixture()
def early_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    """입찰 마감 11/16 · 등록 마감 11/15 인데 공고문 일정표의 참가신청 마감은 11/05 10:00."""
    schedule = notice_schedule.extract([(1, "가. 참가신청 마감 : 2026. 11. 5.(목) 10:00까지")], year_hint=2026)
    monkeypatch.setattr(qualification_clause_service, "load", lambda _nid: {"schedule": schedule, "clauses": []})


RAW = {"bidNtceNo": "SCHED", "bidNtceDt": "2026-10-20 09:00:00", "bidClseDt": "2026-11-16 10:00:00",
       "bidQlfctRgstDt": "2026-11-15 18:00:00", "opengDt": "2026-11-16 11:00:00"}


def test_J03_입찰_마감이_있어도_더_이른_일정표_마감이_상세_판정에_선다(early_schedule: None):
    rows = _rows(RAW, datetime(2026, 11, 6, 9, tzinfo=KST))
    assert rows["ELIG-BID-DEADLINE"].status == "PASS"  # 입찰 마감은 아직
    sched = rows["ELIG-SCHEDULE-DEADLINE"]
    assert sched.status == "FAIL" and "참가신청 마감" in sched.label and "11/05 10:00" in sched.reason
    # 목록의 실제 마감과 같은 날 — 목록 「제외」 · 상세 「N일 남음」이 갈리지 않는다
    item = UnifiedOpportunity(
        id="g2b-SCHED-000", source_type="g2b", opportunity_type="procurement", title="AI 교육", agency="기관",
        organization_id="org-sample", priority_rank=0, priority_label="검토", confidence="medium", score_components=[],
        next_route={"kind": "procurement_analysis", "path": "/", "label": "l"}, source="g2b",
        deadline=datetime(2026, 11, 16, 10, tzinfo=KST), qualification_deadline=datetime(2026, 11, 15, 18, tzinfo=KST),
        schedule_deadline=datetime(2026, 11, 5, 10, tzinfo=KST), schedule_deadline_label="참가신청 마감",
    )
    assert practical.effective_deadline(item) == datetime(2026, 11, 5, 10, tzinfo=KST)


def test_J03_촉박도_일정표_마감으로_센다(early_schedule: None, monkeypatch: pytest.MonkeyPatch):
    from dataclasses import replace

    company = replace(eligibility_engine.active_company(), proposal_lead_days=7)
    monkeypatch.setattr(eligibility_engine, "active_company", lambda: company)
    rows = _rows(RAW, datetime(2026, 11, 1, 9, tzinfo=KST))
    assert rows["ELIG-SCHEDULE-DEADLINE"].status == "CHECK" and "촉박" in rows["ELIG-SCHEDULE-DEADLINE"].reason
    assert rows["ELIG-BID-DEADLINE"].status == "PASS"  # 입찰 마감(15일 남음)만 보면 촉박이 아니었다


def test_J03_일정표_마감이_입찰_마감보다_늦으면_줄을_더하지_않는다(monkeypatch: pytest.MonkeyPatch):
    schedule = notice_schedule.extract([(1, "가. 참가신청 마감 : 2026. 11. 20.(금) 10:00까지")], year_hint=2026)
    monkeypatch.setattr(qualification_clause_service, "load", lambda _nid: {"schedule": schedule, "clauses": []})
    assert "ELIG-SCHEDULE-DEADLINE" not in _rows(RAW, datetime(2026, 11, 1, 9, tzinfo=KST))


def _item(**kw) -> UnifiedOpportunity:
    base = dict(
        id="g2b-X-000", source_type="g2b", opportunity_type="procurement", title="AI 교육", agency="기관",
        organization_id="org-sample", priority_rank=0, priority_label="검토", confidence="medium", score_components=[],
        next_route={"kind": "procurement_analysis", "path": "/", "label": "l"}, source="g2b",
    )
    base.update(kw)
    return UnifiedOpportunity(**base)


def test_M3_시각_모르는_마감은_23시59분을_적지_않는다():
    sched = datetime(2026, 10, 30, 23, 59, tzinfo=KST)
    item = _item(deadline=None, schedule_deadline=sched, schedule_deadline_label="참가신청 마감", schedule_deadline_time_known=False)
    assert practical.effective_deadline(item) == sched  # 판정 · 순서는 그날 끝
    assert not practical.deadline_time_known(item)
    assert practical.deadline_display(item, date(2026, 10, 1), with_time=True) == "10/30(참가신청 마감 · 시각 원문 확인)"
    assert practical.deadline_stamp(item) == "2026-10-30 (시각 원문 확인)"
    known = _item(deadline=None, schedule_deadline=datetime(2026, 10, 30, 18, tzinfo=KST), schedule_deadline_label="참가신청 마감",
                  schedule_deadline_time_known=True)
    assert practical.deadline_display(known, date(2026, 10, 1), with_time=True) == "10/30 18:00(참가신청 마감)"
    assert practical.deadline_stamp(known) == "2026-10-30 18:00"
    # 실제 마감이 입찰 마감이면(일정표 마감이 더 늦음) 시각을 안다
    later = _item(deadline=datetime(2026, 10, 29, 10, tzinfo=KST), schedule_deadline=sched, schedule_deadline_time_known=False)
    assert practical.deadline_time_known(later)
