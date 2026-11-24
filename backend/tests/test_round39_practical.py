"""39차 §3-B — 유형 · PMC · 기획 · 크기 문턱(결정 2) · 「규모 큼」 꼬리표 · 연구 · 평가 용역."""

from __future__ import annotations

import pytest

from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
from app.services import practical_priority as practical

CEILING = 200_000_000  # 회사 단독 상한 2억(샘플에듀 · 권장값)


def _item(title: str, *, typ: str, budget: int | None) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id="g2b-R26BK00000001-000", source_type="g2b", opportunity_type="procurement", title=title, agency="기관",
        organization_id="org-sample", priority_rank=1, priority_label="검토", eligibility_gate="CHECK", confidence="medium",
        score_components=[], next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached",
        budget=budget, fit_type=typ,
    )


@pytest.mark.parametrize(
    ("title", "kinds", "typ"),
    [
        ("EBS 방송 및 교육 인터넷서비스 통합 운영 사업", ["development"], "D"),
        ("2027년 광주교육정보시스템 유지관리 및 보안관제 용역", ["development"], "D"),
        ("가나 디지털 기초교육 역량강화 프로그램 PMC 용역", ["education"], "D"),
        ("우즈베키스탄 국가 행정아카데미 디지털 혁신사업 PMC", ["education"], "D"),
        ("울산 주력산업 연계 AI팩토리 및 AX확산 신규 과제 발굴·기획 연구", ["research"], "B1"),
        ("산단 AX 인프라 연계 실증 기획용역", ["research"], "B1"),
        ("현장 대응력 제고를 위한 건강피해조사 역량강화 방안 연구", ["education", "research"], "B2"),
        ("[연구,189] 라오스 공중보건위기대응 역량강화 사업 종료평가", ["education"], "B2"),
        ("[혁신]특성화 기반 교양·전공 교육과정 혁신 및 대학혁신 프로그램 운영 체계 구축 연구 용역", ["education"], "A1"),
        ("고품질 온라인 강의 교과목 개발 용역", ["development"], "A2"),
        ("AI 활용 교육 운영", ["education"], "A1"),
    ],
)
def test_유형_근사(title: str, kinds: list[str], typ: str) -> None:
    assert practical.type_of_kinds(kinds, title)[0] == typ


def test_제목은_A1_인데_일이_개발뿐이면_C() -> None:
    typ, basis = practical.type_of_kinds(["development"], "스마트 교육 지원 앱 고도화")
    assert typ == "C"
    typ, basis = practical.type_of_kinds(["development"], "디지털 교육 운영 지원")
    assert typ == "C" and "개발" in basis


@pytest.mark.parametrize(
    ("typ", "budget", "large", "tag"),
    [
        ("A1", 380_000_000, False, "규모 큼(단독 상한 2억)"),  # 상한 ~ 2배 — 본업에 남고 꼬리표
        ("A1", 400_000_000, False, "규모 큼(단독 상한 2억)"),  # 정확히 2배는 남음
        ("A1", 513_00_000_000, True, None),  # 2배 넘음 — 대형 · 파트너형 후보
        ("B1", 495_000_000, True, None),
        ("A2", 150_000_000, False, None),
        ("C", 283_000_000, True, None),  # 개발은 상한을 넘으면 대형(그대로)
        ("D", 199_000_000, False, None),
    ],
)
def test_크기_문턱(typ: str, budget: int, large: bool, tag: str | None) -> None:
    item = _item("공고", typ=typ, budget=budget)
    assert practical.is_partner_scale(item, CEILING) is large
    assert practical.scale_tag(item, CEILING) == tag
    assert (practical.block_of(item, CEILING, home=False) == practical.BLOCK_LARGE) is large


def test_광주_전남_발주는_대형이어도_본업에_남고_꼬리표만() -> None:
    item = _item("공고", typ="A1", budget=900_000_000)
    assert practical.block_of(item, CEILING, home=True) == practical.BLOCK_CORE
    assert practical.partner_tag(item, CEILING) is not None


# --------------------------------------------------------------------------
# D17 — 기업마당 지원금(수혜)은 점수 먼저(점수 → 시간 등급 → 마감) · 매출은 그대로
# --------------------------------------------------------------------------


def _biz(n: int, *, score: int, left: int, age: int, recruit: str = practical.RECRUIT_BENEFIT, source: str = "bizinfo") -> UnifiedOpportunity:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
    return UnifiedOpportunity(
        id=f"{source}-{n:03d}", source_type=source, opportunity_type="support_program" if source == "bizinfo" else "procurement",
        title=f"지원 {n}", agency="중소벤처기업부", organization_id="org-sample", priority_rank=n, priority_label="검토",
        eligibility_gate="CHECK", confidence="medium", score_components=[], company_priority_score=score,
        next_route=NextRoute(kind="support_application", path="/", label="열기"), source="cached",
        deadline=now + timedelta(days=left), published_at=now - timedelta(days=age), recruit_kind=recruit, fit_type="A1",
        submission_methods=["미상"],
    )


def _ordered(rows: list[UnifiedOpportunity]) -> list[str]:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
    practical.annotate(rows, now=now, ceiling_krw=CEILING)
    return [i.id for i in practical.order(rows, now=now, home_of=lambda _i: False)]


def test_기업마당_지원금은_점수가_시간_등급보다_먼저() -> None:
    fresh_low = _biz(1, score=30, left=30, age=1)  # T1 신규+여유 · 30점
    old_high = _biz(2, score=85, left=40, age=60)  # T4 · 85점
    urgent_mid = _biz(3, score=60, left=5, age=30)  # T6 긴급 · 60점
    # 43차 Q12 — 수혜 긴급(13일 이하)은 점수 다음 자리(점수가 높아도 긴급이 아닌 것 뒤)
    assert _ordered([fresh_low, urgent_mid, old_high]) == [old_high.id, fresh_low.id, urgent_mid.id]
    assert fresh_low.practical_group == "신규+여유"  # 칸(꼬리표)은 그대로


def test_기업마당_지원금_같은_점수면_시간_등급_다음_마감_빠른_순() -> None:
    t4_late = _biz(1, score=70, left=50, age=60)
    t4_soon = _biz(2, score=70, left=20, age=60)
    t1 = _biz(3, score=70, left=25, age=2)
    assert _ordered([t4_late, t4_soon, t1]) == [t1.id, t4_soon.id, t4_late.id]


def test_직접_넣은_수혜도_점수_먼저_줄이라_기업마당_수혜와_점수로_섞인다() -> None:
    """39차 마지막 검토 — 실무 순번은 출처 전체에 매기고 브리핑 지원금 칸은 그 순번으로 두 출처를 섞는다."""
    manual_low = _biz(1, score=30, left=30, age=1, source="manual")
    biz_high = _biz(2, score=80, left=40, age=60)
    assert _ordered([manual_low, biz_high]) == [biz_high.id, manual_low.id]


def test_매출은_37_38차_실무순_그대로() -> None:
    """나라장터 · 기업마당 수행기관 모집은 덩어리 → 시간 등급 → … → 점수(점수 먼저가 아니다)."""
    g2b_fresh = _biz(1, score=30, left=30, age=1, recruit=practical.RECRUIT_BID, source="g2b")
    g2b_high = _biz(2, score=90, left=40, age=60, recruit=practical.RECRUIT_BID, source="g2b")
    assert _ordered([g2b_high, g2b_fresh]) == [g2b_fresh.id, g2b_high.id]
    op_fresh = _biz(3, score=30, left=30, age=1, recruit=practical.RECRUIT_OPERATOR)
    op_high = _biz(4, score=90, left=40, age=60, recruit=practical.RECRUIT_OPERATOR)
    benefit = _biz(5, score=95, left=40, age=60)
    # 기업마당 안에서 수행기관 모집(매출)은 지원금보다 앞 — 매출 먼저(브리핑도 매출 칸이 먼저)
    assert _ordered([benefit, op_high, op_fresh]) == [op_fresh.id, op_high.id, benefit.id]


# --------------------------------------------------------------------------
# D22 — 「전체」 탭은 출처별 순위를 번갈아(서버 · 내려받은 파일 순서 = 화면)
# --------------------------------------------------------------------------


def test_전체는_출처를_번갈아_세우고_같은_칸끼리만(monkeypatch) -> None:
    import asyncio
    from datetime import datetime, timezone

    from app.schemas.organization import AnalysisContext
    from app.services import opportunity_service

    now = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
    g2b = [_biz(n, score=60, left=20 + n, age=30, recruit=practical.RECRUIT_BID, source="g2b") for n in range(1, 3)]
    biz = [_biz(10 + n, score=90 - n, left=30, age=1) for n in range(1, 5)]  # T1 · 실무순 한 줄이면 모두 앞
    biz.append(_biz(20, score=95, left=30, age=1).model_copy(update={"eligibility_gate": "FAIL"}))

    async def procurements(**_kwargs):
        return [x.model_copy() for x in g2b], "cached", None, None

    async def support(**_kwargs):
        return [x.model_copy() for x in biz], "cached", None, True, now

    monkeypatch.setattr(opportunity_service, "_collect_procurements", procurements)
    monkeypatch.setattr(opportunity_service, "_collect_support", support)
    monkeypatch.setattr(opportunity_service, "ranking_method_of", lambda _org: "practical")
    ctx = AnalysisContext(organization_id="org-sample", evidence_scope="internal")
    listing = asyncio.run(opportunity_service.list_opportunities(context=ctx, source="all", now=now, include_blocked=True))
    sources = [i.source_type for i in listing.items]
    assert sources == ["g2b", "bizinfo", "g2b", "bizinfo", "bizinfo", "bizinfo", "bizinfo"]
    assert listing.items[-1].eligibility_gate == "FAIL"  # 불가는 살아 있는 것 뒤
    assert [i.source_rank for i in listing.items if i.source_type == "bizinfo"] == [1, 2, 3, 4, 5]  # 출처 안 순위 그대로
    deadline = asyncio.run(opportunity_service.list_opportunities(context=ctx, source="all", now=now, sort="deadline"))
    assert [i.source_type for i in deadline.items][:2] == ["g2b", "g2b"]  # 날짜 정렬은 번갈지 않는다
