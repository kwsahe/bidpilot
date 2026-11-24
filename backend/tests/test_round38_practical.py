"""38차 §3-B — 실무순 세 덩어리(D12) · 3일 이하 뒤로(D13) · 대형 꼬리표 한 함수(D14 · DOCS-01) · 유형 제목 먼저(PRACTICAL-03) · 브리핑 TOP.

같은 덩어리 안은 37차 키 그대로다(시간 등급 → 접수방식 → 유형 → 점수 → 남은 기간). 점수는 바꾸지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import (
    NextRoute,
    OpportunitySummary,
    UnifiedOpportunity,
    UnifiedOpportunityListResponse,
)
from app.services import opportunity_brief_service as brief
from app.services import practical_priority as practical
from app.services import work_kinds

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
CEILING = 200_000_000


def item(n: int, *, left: int = 20, age: int = 3, typ: str = "A1", budget: int | None = None, agency: str = "서울 시험 기관",
         award: str | None = None, source: str = "g2b", recruit: str | None = None, score: int = 60, gate: str = "CHECK",
         methods: list[str] | None = None) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"{'g2b' if source == 'g2b' else 'bizinfo'}-T{n:03d}", source_type=source,
        opportunity_type="procurement" if source == "g2b" else "support_program",
        title=f"AI 교육 시험 {n}", agency=agency, deadline=NOW + timedelta(days=left), published_at=NOW - timedelta(days=age),  # 40차 — 주제 낱말(「주제 확인」 밖)
        organization_id="org-sample", company_priority_score=score, priority_rank=n, source_rank=n, priority_label="검토",
        eligibility_gate=gate, gate_reason="-", confidence="medium", score_components=[],
        next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached",
        fit_type=typ, budget=budget, award_line=award,
        recruit_kind=recruit or (practical.RECRUIT_BID if source == "g2b" else practical.RECRUIT_BENEFIT),
        submission_methods=methods or ["전자입찰"],
    )


def arrange(items: list[UnifiedOpportunity]) -> list[str]:
    home_of = lambda i: "광주" in i.agency  # noqa: E731
    practical.annotate(items, now=NOW, ceiling_krw=CEILING, home_of=home_of)
    return [i.id for i in practical.order(items, now=NOW, home_of=home_of)]


def test_세_덩어리_본업_다음_연구감리구매_다음_대형() -> None:
    big_new = item(1, typ="C", budget=3_270_000_000, age=2, left=29, award="다른 회사와 함께 참가할 수 있음(공동이행)")  # T1 대형
    research = item(2, typ="B2", budget=50_000_000, age=2, left=29)  # T1 연구
    core_urgent = item(3, typ="A1", left=9)  # T5 본업
    out = arrange([big_new, research, core_urgent])
    assert out == [core_urgent.id, research.id, big_new.id]
    assert [big_new.practical_block, research.practical_block, core_urgent.practical_block] == [
        practical.BLOCK_LARGE, practical.BLOCK_SIDE, practical.BLOCK_CORE,
    ]
    assert big_new.practical_group == practical.GROUP_PARTNER


def test_교육_컨설팅은_상한_2배를_넘으면_대형이다() -> None:
    """39차 담당자 결정 2(2026-10-18) — 38차 「교육 · 컨설팅은 크다고 대형이 아니다」를 바꿈: 상한(2억)의 2배를 넘으면 대형,
    2배 안이면 본업에 남고 「규모 큼」 꼬리표."""
    edu = item(1, typ="A1", budget=900_000_000)
    consult = item(2, typ="B1", budget=495_000_000)
    near = item(3, typ="A2", budget=380_000_000)
    arrange([edu, consult, near])
    assert edu.practical_block == consult.practical_block == practical.BLOCK_LARGE
    assert edu.partner_tag and consult.partner_tag
    assert near.practical_block == practical.BLOCK_CORE and near.partner_tag is None
    assert near.scale_tag == "규모 큼(단독 상한 2억)"


def test_광주_전남_발주_대형은_본업에_남고_꼬리표만() -> None:
    home_big = item(1, typ="C", budget=500_000_000, agency="광주광역시", award="다른 회사와 함께 참가할 수 없음(공동수급 불허)")
    arrange([home_big])
    assert home_big.practical_block == practical.BLOCK_CORE
    assert home_big.partner_tag == practical.PARTNER_TAG_NO
    assert home_big.practical_group != practical.GROUP_PARTNER


@pytest.mark.parametrize(
    ("award", "tag"),
    [
        ("제한경쟁 · 다른 회사와 함께 참가할 수 있음(공동이행)", practical.PARTNER_TAG_OK),
        ("제한경쟁 · 다른 회사와 함께 참가할 수 있음(혼합방식)", practical.PARTNER_TAG_OK),
        ("제한경쟁 · 다른 회사와 함께 참가할 수 없음(공동수급 불허)", practical.PARTNER_TAG_NO),
        (None, practical.PARTNER_TAG_UNKNOWN),
    ],
)
def test_대형_꼬리표와_브리핑_판단_낱말은_같은_값(award: str | None, tag: str) -> None:
    big = item(1, typ="C", budget=1_300_000_000, award=award)
    arrange([big])
    assert big.partner_tag == tag
    assert brief.verdict_of(big) == tag  # DOCS-01 — 행 꼬리표와 판단 낱말이 갈리지 않는다


def test_T6_안에서_3일_이하는_4_7일_뒤로() -> None:
    three = item(1, left=2, score=90)
    six = item(2, left=6, score=40)
    assert arrange([three, six]) == [six.id, three.id]
    assert three.deadline_note == practical.LATE_NOTE


def test_같은_덩어리_안은_37차_키_그대로() -> None:
    t2 = item(1, age=10, left=16)  # T2
    t1 = item(2, age=3, left=25)  # T1
    # 39차 D17 — 기업마당 지원금은 점수 먼저라 37차 키를 쓰는 매출(수행기관 모집)로 견준다
    t4_email = item(3, age=40, left=30, source="bizinfo", methods=["이메일"], recruit=practical.RECRUIT_OPERATOR)
    t4_bid = item(4, age=40, left=30)
    assert arrange([t4_bid, t4_email, t2, t1]) == [t1.id, t2.id, t4_email.id, t4_bid.id]


def test_기업마당_수혜_수행기관_모집은_본업() -> None:
    benefit = item(1, source="bizinfo", typ="수혜")
    operator = item(2, source="bizinfo", typ="B2", recruit=practical.RECRUIT_OPERATOR, budget=900_000_000)
    arrange([benefit, operator])
    assert benefit.practical_block == operator.practical_block == practical.BLOCK_CORE


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("2026년 AI 청년창업기업 동반성장 바우처 사업  클라우드형 GPU서비스 임차", "D"),  # 1768184
        ("연암공과대학교 AI Professor 시스템 개발 용역", "C"),  # 1762995
        ("ANCHOR AI&Tech 재직자 실무 아카데미 프로그램 용역", "A1"),  # 1756826
        ("AI기반 디지털트윈 EV 정비 교육용 콘텐츠 제작 용역(수정)", "A2"),  # 1759430
        ("2026년 초·중등 AI 활용 교과 수업모형·지도안 영상 및 교사 안내용 콘텐츠 개발·보급 위탁 용역", "A2"),  # 1758659
        ("KDB AI 거버넌스 수립 컨설팅", "B1"),  # 1736492
        ("한림대학교 커뮤니티교육원 2차년도 교육 프로그램 강의 개발 업체 선정", "A2"),
        ("[2026-047] KERIS 중장기 ESG 경영전략 수립 컨설팅 전자입찰 공고", "B1"),
        ("2026년 한국도로공사 AI 활용 직무 교육 운영", "A1"),  # 기관 이름의 「공사」는 공사가 아니다
        ("2026년 시흥교육지원청 시설공사 하자검사용역", "D"),
    ],
)
def test_유형은_제목_낱말을_먼저_본다(title: str, typ: str) -> None:
    # 조달 분류명이 「연구조사」 · 「교육서비스」여도 제목이 정한다(recheck30 PRACTICAL-03)
    kinds = work_kinds.detect_work_kinds(f"{title} 연구조사서비스 교육서비스")
    assert practical.type_of_kinds(kinds, title)[0] == typ


def test_제목에_갈래가_없을_때만_분류명_갈래() -> None:
    assert practical.type_of_kinds(["consulting"], "2026년 시험 사업")[0] == "B1"


# --------------------------------------------------------------------------
# 브리핑 TOP — 본업 덩어리의 매출 앞에서부터 10건 · 「본업 · 긴급」 · 파트너형 후보 칸
# --------------------------------------------------------------------------


def _listing(items: list[UnifiedOpportunity]) -> UnifiedOpportunityListResponse:
    return UnifiedOpportunityListResponse(
        organization_id="org-sample", organization_name="주식회사 샘플에듀", total_count=len(items),
        g2b_count=len(items), bizinfo_count=0, returned_count=len(items), closed_count=0,
        source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=len(items), open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
    )


def test_브리핑_TOP_은_본업만_대형은_파트너형_후보_칸() -> None:
    big = item(1, typ="C", budget=3_270_000_000, age=2, left=29, award="다른 회사와 함께 참가할 수 있음(공동이행)")
    big.title = "X-ray 판독 시스템 구축"
    edu = item(2, typ="A1", left=9)
    edu.title = "AI 활용 재학생 역량강화 위탁운영"
    arrange([big, edu])
    body, _ = brief.build_markdown(_listing([big, edu]), now=NOW, previous=None)
    top = body.split("## 매출 — 입찰 · 수행기관 모집")[1].split("## 지원금")[0]
    assert "AI 활용 재학생 역량강화" in top and "X-ray 판독" not in top
    assert "본업 · 긴급" in top  # T5 본업 줄
    partner = body.split("# 🤝 대형 · 파트너형 후보")[1].split("# ❌")[0]
    assert "X-ray 판독" in partner and practical.PARTNER_TAG_OK in partner
    assert body.index("# 🚨 긴급") < body.index("# 🤝 대형 · 파트너형 후보") < body.index("# ❌ 제외")
