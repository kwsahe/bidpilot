"""40차 §3-H — 화면 · 순위 글 · 사전규격(SCREEN-02 · REGRESS-03 · PRESPEC-02 · PRESPEC-03 · RANK-04). 호출 없음."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import opportunity_priority as priority
from app.services import opportunity_service, prespec_service, recommendation
from tests.test_round38_prespec import NOW, _build, _main, _pre

KST = timezone(timedelta(hours=9))


# --------------------------------------------------------------------------
# SCREEN-02 — D-day 와 「마감 n일 남음」이 같은 셈
# --------------------------------------------------------------------------


def test_남은_날은_KST_달력_날짜_차() -> None:
    now = datetime(2026, 10, 19, 18, 0, tzinfo=KST)
    # 10/23 14:00 마감 — 시간으로 나누면 3.8일(내림 3)이지만 화면 D-day 는 D-4
    assert recommendation.calendar_days_left(datetime(2026, 10, 23, 14, 0, tzinfo=KST), now) == 4
    assert recommendation.calendar_days_left(datetime(2026, 10, 19, 23, 59, tzinfo=KST), now) == 0
    assert recommendation.calendar_days_left(datetime(2026, 10, 19, 17, 0, tzinfo=KST), now) == -1
    assert recommendation.calendar_days_left(datetime(2026, 10, 20, 0, 30, tzinfo=KST), datetime(2026, 10, 19, 23, 50, tzinfo=KST)) == 1
    assert recommendation.calendar_days_left(None, now) is None


def test_주의와_왜_맞나는_오늘_마감을_0일이라_적지_않는다() -> None:
    caution = priority.caution_line(budget=None, ceiling=None, days_left=0, lead_days=4, joint_allowed=None, out_of_scope=False)
    assert caution == "오늘 마감 — 준비 시간 부족"
    assert priority.caution_line(budget=None, ceiling=None, days_left=4, lead_days=5, joint_allowed=None, out_of_scope=False) == "마감 4일 남음 — 준비 시간 부족"
    line = priority.fit_line(text="공고", tracks=[], procurement_class=None, budget=None, days_left=0, capacity=None)
    assert line == "오늘 마감"


def test_목록의_마감_글은_D_day_와_같은_날을_센다(monkeypatch: pytest.MonkeyPatch) -> None:
    """opportunity_service 가 「마감까지 n일」 · 「마감 n일 남음」에 쓰는 셈이 실무순 `days_left`(화면 D-day)와 같다."""
    import inspect

    source = inspect.getsource(opportunity_service._collect_procurements)
    assert source.count("recommendation.calendar_days_left(effective_close, now)") == 2
    assert "recommendation.days_until(" not in source


# --------------------------------------------------------------------------
# REGRESS-03 — 기업마당 메모 열쇠 지문
# --------------------------------------------------------------------------


def test_메모_열쇠_지문에_분류_파일이_든다() -> None:
    assert "opportunity_filter.py" in opportunity_service._RULE_CODE_FILES
    assert "practical_priority.py" in opportunity_service._RULE_CODE_FILES


# --------------------------------------------------------------------------
# PRESPEC-03 — 한 사전규격의 본공고 여럿
# --------------------------------------------------------------------------


def test_사전규격의_본공고가_둘이면_둘_다_적고_링크는_마감_전_새_공고() -> None:
    first, main1 = _main("R26BK01745342", "R26BD00276747", published=datetime(2026, 10, 10, 10, 0, tzinfo=KST))
    again, main2 = _main("R26BK01766975", "R26BD00276747", published=datetime(2026, 10, 16, 10, 0, tzinfo=KST))
    [row] = _build([_pre("R26BD00276747", "AI 교육 운영", rgst="2026-10-04 09:00:00")], [first, again], [main1, main2])
    assert main1.pre_spec_note == "사전규격 6일 전 공개" and main2.pre_spec_note == "사전규격 12일 전 공개"
    assert row.main_notice_id == main2.id  # 재공고(새 공고번호)
    # 재공고가 마감이면 마감 전 원공고로
    main2.closed = True
    main1.pre_spec_note = main2.pre_spec_note = None
    [row] = _build([_pre("R26BD00276747", "AI 교육 운영", rgst="2026-10-04 09:00:00")], [first, again], [main1, main2])
    assert row.main_notice_id == main1.id and main1.pre_spec_note and main2.pre_spec_note


# --------------------------------------------------------------------------
# PRESPEC-02 — 합쳐 남긴 옛 발주계획 행도 본공고 쪽에서 「본공고 나옴」
# --------------------------------------------------------------------------


def _plan(no: str, title: str = "생성형 AI 활용 역량강화 교육", **extra) -> dict:
    return {"orderPlanUntyNo": no, "orderPlanSno": "1", "bizNm": title, "orderInsttNm": "광주광역시교육청", "orderYear": "2026",
            "orderMnth": "10", "sumOrderAmt": "150000000", "cntrctMthdNm": "협상에 의한 계약", "ntceNticeYn": "N", "bidNtceNoList": "",
            "nticeDt": "2026-10-10 09:00:00", **extra}


def test_본공고_원본의_발주계획_번호로_본공고_나옴(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.procurement import ProcurementNotice

    monkeypatch.setattr(prespec_service, "load_order_plans", lambda: ([_plan("R26DD20893369"), _plan("R26DD20890000", title="AI 교육 과정 운영")], None))
    main = ProcurementNotice(id="g2b-R26BK01767120-000", notice_no="R26BK01767120-000", title="생성형 AI 교육", agency="기관",
                             published_at=NOW, raw_data={"item": {"orderPlanUntyNo": "R26DD20893369"}})
    old = ProcurementNotice(id="g2b-R26BK01700001-000", notice_no="R26BK01700001-000", title="옛 공고", agency="기관",
                            published_at=NOW, raw_data={"item": {"orderPlanUntyNo": "R26DD20893369"}})
    mapping = prespec_service.plan_mains([old, main], {main.id})
    assert mapping == {"R26DD20893369": main.id}
    keep, _ = prespec_service.order_plan_rows(NOW, main_ids={main.id}, plan_to_main=mapping)
    by_title = {row["title"]: row for row in keep}
    assert by_title["생성형 AI 활용 역량강화 교육"]["main_out"] is True
    assert by_title["생성형 AI 활용 역량강화 교육"]["main_notice_id"] == main.id
    assert by_title["AI 교육 과정 운영"]["main_out"] is False and by_title["AI 교육 과정 운영"]["main_notice_id"] is None
    # 목록 밖 본공고(마감 등)여도 「본공고 나옴」 · 링크는 없음
    keep, _ = prespec_service.order_plan_rows(NOW, main_ids=set(), plan_to_main=prespec_service.plan_mains([main]))
    row = next(r for r in keep if r["title"].startswith("생성형"))
    assert row["main_out"] is True and row["main_notice_id"] is None


# --------------------------------------------------------------------------
# RANK-04 — 「파트너형 후보」 설명
# --------------------------------------------------------------------------


def test_브리핑_파트너형_칸_머리는_교육_컨설팅_2배를_적는다() -> None:
    import inspect

    from app.services import opportunity_brief_service

    source = inspect.getsource(opportunity_brief_service)
    assert "개발 · 연구 · 그 밖은 상한 초과, 교육 · 컨설팅은 상한의 2배 초과" in source
    assert "넘는 개발 · 연구 · 그 밖(광주" not in source
