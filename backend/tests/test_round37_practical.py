"""37차 — 회사별 우선순위 계산 방식 · 실무 우선순위(사업담당자 방식) (prompt_27 §3-A · §3-B).

점수는 바꾸지 않는다. 실무순은 순서와 분류 칸만 정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import UnifiedOpportunity
from app.schemas.delivery_capacity import DeliveryCapacityUpdate
from app.services import opportunity_service
from app.services import practical_priority as practical

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=KST)
TODAY = NOW.date()
CEILING = 200_000_000


def _at(days: int, hour: int = 18) -> datetime:
    """오늘에서 days 일 뒤 그날 hour 시(KST)."""
    base = datetime.combine(TODAY + timedelta(days=days), datetime.min.time(), tzinfo=KST)
    return base.replace(hour=hour)


def _item(
    item_id: str,
    *,
    score: int | None = 70,
    left: int | None = 20,
    age: int | None = 3,
    source: str = "g2b",
    gate: str = "CHECK",
    kinds: list[str] | None = None,
    budget: int | None = None,
    methods: list[str] | None = None,
    qualification_left: int | None = None,
    relevance_note: str | None = None,
    closed: bool = False,
    company_gap: bool = False,
) -> UnifiedOpportunity:
    is_g2b = source == "g2b"
    item = UnifiedOpportunity(
        id=item_id,
        source_type=source,  # type: ignore[arg-type]
        opportunity_type="procurement" if is_g2b else "support_program",
        title=f"AI {item_id}",  # 40차 — 주제 낱말(「주제 확인」 밖 · 유형은 kinds 그대로)
        agency="기관",
        organization_id="org-sample",
        priority_rank=0,
        priority_label="검토",
        confidence="medium",
        score_components=[],
        next_route={"kind": "procurement_analysis" if is_g2b else "support_application", "path": "/", "label": "l"},
        source=source,
        company_priority_score=score,
        eligibility_gate=gate,  # type: ignore[arg-type]
        deadline=_at(left) if left is not None else None,
        qualification_deadline=_at(qualification_left, 10) if qualification_left is not None else None,
        published_at=_at(-age, 9) if age is not None else None,
        work_kinds=kinds if kinds is not None else ["education"],  # type: ignore[arg-type]
        budget=budget,
        submission_methods=methods if methods is not None else (["전자입찰"] if is_g2b else ["미상"]),
        relevance_note=relevance_note,
        closed=closed,
        practical_company_gap=company_gap,
    )
    if is_g2b:
        item.fit_type, item.fit_type_basis = practical.g2b_type(item)
    else:
        item.fit_type = "수혜"
    return item


def _rank(items: list[UnifiedOpportunity]) -> list[str]:
    practical.annotate(items, now=NOW, ceiling_krw=CEILING)
    return [i.id for i in practical.order(items, now=NOW, home_of=lambda _i: False)]


# ---------------------------------------------------------------------------
# §3-B-6 실무 문서 §2.5 예시
# ---------------------------------------------------------------------------


def test_김담당_문서_예시_80점_어제_공고_마감30일이_85점_마감8일보다_위():
    fresh = _item("fresh", score=80, left=30, age=1)
    urgent = _item("urgent", score=85, left=8, age=2)
    assert _rank([urgent, fresh]) == ["fresh", "urgent"]
    assert fresh.time_tier == "T1" and fresh.practical_group == "신규+여유"
    assert urgent.time_tier == "T5" and urgent.practical_group == "긴급"
    # 점수는 그대로다
    assert (fresh.company_priority_score, urgent.company_priority_score) == (80, 85)


# ---------------------------------------------------------------------------
# T1~T6 경계 (21 · 14 · 13 · 8 · 7일)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "age", "tier"),
    [
        (21, 7, "T1"),   # 7일 이내 + 21일 이상
        (20, 7, "T2"),   # 21 미만이면 T2(14일 이내 + 14 이상)
        (21, 8, "T2"),   # 공고 8일 — 신규 아님 → T2
        (14, 14, "T2"),
        (14, 15, "T4"),  # 공고 15일 — T2 아님 → 일반 접수 중
        (13, 1, "T5"),   # 13일 이하 = 긴급(8~13)
        (8, 1, "T5"),
        (7, 1, "T6"),    # 7일 이하
        (0, 1, "T6"),
        (40, 30, "T4"),
    ],
)
def test_시간_등급_경계(left: int, age: int, tier: str):
    assert practical.time_tier(left, age) == tier


def test_마감일_없음은_일반_접수_중_T4():
    item = _item("always", left=None, age=1, source="bizinfo")
    _rank([item])
    assert item.time_tier == "T4"
    assert practical.time_tier(None, 1) == "T4"


def test_실제_마감이_참가자격_등록_마감인_공고():
    """입찰 마감은 30일 뒤지만 등록 마감이 10일 뒤면 남은 기간은 10일(T5)이다."""
    item = _item("reg", left=30, qualification_left=10, age=1)
    _rank([item])
    assert practical.days_left(item, TODAY) == 10
    assert item.time_tier == "T5"


def test_3일_이하는_원칙적으로_후순위_꼬리표():
    late = _item("late", left=3, age=1)
    ok = _item("ok", left=4, age=1)
    _rank([late, ok])
    assert late.deadline_note == practical.LATE_NOTE
    assert ok.deadline_note is None


# ---------------------------------------------------------------------------
# 같은 등급 안의 순서 — 접수방식 · 유형 · D8 · 점수 · 남은 기간
# ---------------------------------------------------------------------------


def test_대형_SI_는_그_등급_맨_뒤로():
    big = _item("big", score=95, kinds=["development"], budget=1_300_000_000, left=33, age=2)
    small = _item("small", score=40, kinds=["development"], budget=80_000_000, left=33, age=2)
    assert _rank([big, small]) == ["small", "big"]
    assert big.partner_scale and not small.partner_scale
    # 39차 결정 2 — 교육 공고도 상한의 2배를 넘으면 대형(13억 > 4억). 2배 안이면 대형이 아니다.
    edu = _item("edu", kinds=["education"], budget=1_300_000_000)
    near = _item("near", kinds=["education"], budget=300_000_000)
    _rank([edu, near])
    assert edu.partner_scale and not near.partner_scale


def test_같은_등급_안에서는_직찰이_전자입찰보다_먼저():
    direct = _item("direct", score=50, methods=["직찰"])
    online = _item("online", score=90, methods=["전자입찰"])
    assert _rank([online, direct]) == ["direct", "online"]


def test_같은_등급_같은_접수방식이면_유형_A1_이_C_보다_먼저():
    dev = _item("dev", score=90, kinds=["development"])
    edu = _item("edu", score=60, kinds=["education"])
    assert _rank([dev, edu]) == ["edu", "dev"]


def test_같은_조건이면_점수_높은_순_그다음_남은_기간_긴_순():
    a = _item("a", score=60, left=25)
    b = _item("b", score=70, left=22)
    c = _item("c", score=60, left=29)
    assert _rank([a, b, c]) == ["b", "c", "a"]


def test_비추천과_제외는_뒤로_모은다():
    low = _item("low", score=99, relevance_note="관련 낮음")
    fail = _item("fail", score=99, gate="FAIL")
    closed = _item("closed", score=99, closed=True)
    live = _item("live", score=10, left=5)
    ranked = _rank([closed, fail, low, live])
    assert ranked[:2] == ["live", "low"] and set(ranked[2:]) == {"closed", "fail"}
    assert low.practical_group == "비추천"
    assert fail.practical_group == "제외" and closed.practical_group == "제외"


def test_분류_칸_직접도전_조건부_일반():
    passed = _item("pass", gate="PASS", left=20, age=10)
    gap = _item("gap", gate="CHECK", left=20, age=10, company_gap=True)
    other = _item("other", gate="CHECK", left=20, age=10)
    _rank([passed, gap, other])
    assert (passed.practical_group, gap.practical_group, other.practical_group) == ("직접도전", "조건부", "일반 접수 중")


# ---------------------------------------------------------------------------
# 유형(근사) · 접수방식
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kinds", "title", "typ"),
    [
        (["education"], "AI 부트캠프 교육 운영", "A1"),
        (["education", "development"], "AI 교육 콘텐츠 개발 및 운영", "A2"),
        (["consulting"], "AX 컨설팅", "B1"),
        (["development"], "플랫폼 구축", "C"),
        (["research"], "정책 연구", "B2"),
        (["procurement", "education"], "교수학습 플랫폼 사용권 구매", "D"),
        (["construction"], "증축 설계", "D"),
        ([], "AI 행사", "D"),
    ],
)
def test_유형_근사(kinds: list[str], title: str, typ: str):
    assert practical.type_of_kinds(kinds, title)[0] == typ


def test_기업마당_수혜는_수혜_수행기관_모집은_제목으로():
    assert practical.bizinfo_type("소상공인 디지털 전환 지원", None, practical.RECRUIT_BENEFIT)[0] == "수혜"
    assert practical.bizinfo_type("AI 교육 운영기관 모집", None, practical.RECRUIT_OPERATOR)[0] == "A1"


@pytest.mark.parametrize(
    ("text", "url", "expected"),
    [
        ("이메일(abc@x.kr) 접수", None, ["이메일"]),
        ("K-Startup 누리집 온라인 신청", None, ["온라인/기관시스템(PMS)"]),
        ("방문 또는 우편(등기) 접수", None, ["방문", "우편"]),
        ("", "https://pms.ripc.org", ["온라인/기관시스템(PMS)"]),
        ("담당자 문의", None, ["미상"]),
    ],
)
def test_기업마당_접수방식(text: str, url: str | None, expected: list[str]):
    assert practical.bizinfo_methods(text, url) == expected


def test_기업마당_방문_접수는_광주전남_기관이면_기관_자체():
    visit = _item("visit", source="bizinfo", methods=["방문"])
    assert practical.method_rank(visit, home=True) == 1
    assert practical.method_rank(visit, home=False) == 2
    mail = _item("mail", source="bizinfo", methods=["이메일", "방문"])
    assert practical.method_rank(mail, home=False) == 0


# ---------------------------------------------------------------------------
# 점수순 회사 — 순서 불변 · 회사 방식 저장
# ---------------------------------------------------------------------------


def test_점수순_정렬은_점수_그다음_마감_빠른_순_그대로():
    """score 회사의 기본 정렬(priority)은 실무 값을 매겨도 바뀌지 않는다."""
    a = _item("a", score=80, left=30)
    b = _item("b", score=80, left=5)
    c = _item("c", score=90, left=40)
    items = [a, b, c]
    practical.annotate(items, now=NOW, ceiling_krw=CEILING)
    practical.order(items, now=NOW, home_of=lambda _i: False)
    ordered = opportunity_service.sort_opportunities(items, "priority")
    assert [i.id for i in ordered] == ["c", "b", "a"]
    practical_sorted = opportunity_service.sort_opportunities(list(items), "practical")
    assert [i.id for i in practical_sorted] == ["c", "a", "b"]


def test_마감_여유순과_최신_등록순():
    near = _item("near", left=3, age=10)
    far = _item("far", left=40, age=20)
    none = _item("none", left=None, age=1, source="bizinfo")
    slack = [i.id for i in opportunity_service.sort_opportunities([near, far, none], "slack")]
    assert slack == ["far", "near", "none"]
    recent = [i.id for i in opportunity_service.sort_opportunities([near, far, none], "recent")]
    assert recent == ["none", "near", "far"]


def test_회사_방식_기본은_점수순이고_비워_저장하면_그대로_둔다(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.core import org_storage
    from app.services import delivery_capacity_service

    path = tmp_path / "delivery_capacity.json"
    monkeypatch.setattr(org_storage, "storage_for", lambda org: SimpleNamespace(delivery_capacity_file=path))
    org = "org-sample"
    assert delivery_capacity_service.load(org).ranking_method == "score"
    assert opportunity_service.default_sort_of(org) == "priority"
    delivery_capacity_service.save(org, DeliveryCapacityUpdate(ranking_method="practical", updated_by="시험"))
    assert opportunity_service.default_sort_of(org) == "practical"
    # 이 칸을 모르는 화면이 저장해도(비워 보냄) 고른 방식이 남는다
    delivery_capacity_service.save(org, DeliveryCapacityUpdate(updated_by="옛 화면"))
    assert delivery_capacity_service.load(org).ranking_method == "practical"
    delivery_capacity_service.save(org, DeliveryCapacityUpdate(ranking_method="score", updated_by="시험"))
    assert opportunity_service.default_sort_of(org) == "priority"
