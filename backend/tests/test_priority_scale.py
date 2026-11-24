"""검토 우선순위 v3 — 마감을 점수에서 빼고 도메인·자격·규모를 등급화한다 (0922.md §4-B).

## 왜 고쳤나

재검증(ISSUE-083)에서 키워드가 맞는 공고가 **전부 사업영역 1.0** 이라 변별이 마감에만
남아 있었다. `score_components` 가 `domain 1.0 · eligibility 0.5 · evidence None ·
strategic 0.7` 로 같고 `schedule` 만 달라, 마감 순서가 곧 순위였다 — 81점 8건 · 77점 25건.
검수자가 손으로 고른 1순위(한양사이버대 챗봇)는 23위였고, 3.8억 강원대·박람회 대행·
SBS 방송 제작이 12위 안이었다.

## 두 축으로 나눈다

    적합도(점수) = 「우리와 맞는가」. **마감이 바뀌어도 그대로다.**
    긴급도       = 「언제까지인가」. D-day · 「마감 임박순」 · 「이번 주 할 일」 · 촉박 배지.

여기서 그 약속을 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.business_opportunity import UnifiedOpportunity
from app.schemas.procurement import ProcurementNotice
from app.services import opportunity_priority as priority
from app.services import opportunity_service, organization_service
from app.services.opportunity_filter import classify

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)
ALPHA = "org-test-alpha"


@pytest.fixture()
def company(isolated_organizations) -> Any:
    """개발도 교육도 한다고 적어 둔 회사. 실제 샘플에듀 프로필의 사업영역과 같은 축이다."""
    from app.schemas.organization import OrganizationCreateRequest, OrganizationProfileUpdate

    organization_service.create_organization(
        OrganizationCreateRequest(
            organization_id=ALPHA, display_name="가상 AI교육 컴퍼니", data_class="synthetic", created_by="테스트"
        )
    )
    return organization_service.save_profile(
        ALPHA,
        OrganizationProfileUpdate(
            name="가상 AI교육 컴퍼니",
            business_domains=["AI·AX 교육 및 인력양성", "AI SaaS·소프트웨어 개발", "AI Agent·RAG 컨설팅"],
            target_clients=["대학", "공공기관"],
            preferred_regions=["광주광역시", "전라남도"],
            certifications=["사회적기업"],
            data_class="synthetic",
            updated_by="테스트",
        ),
    )


def make_notice(
    nid: str,
    title: str,
    *,
    deadline: datetime | None = None,
    budget: int | None = 50_000_000,
    **item: Any,
) -> ProcurementNotice:
    return ProcurementNotice(
        id=f"g2b-{nid}-000",
        notice_no=f"{nid}-000",
        title=title,
        agency="시험기관",
        published_at=NOW - timedelta(days=3),
        deadline_at=deadline,
        budget=budget,
        region=None,
        description=None,
        source_url=None,
        raw_data={"source": "g2b", "item": {"bidNtceNo": nid, "bidNtceOrd": "000", **item}, **item},
    )


def score(notice: ProcurementNotice, *, profile, **kwargs: Any) -> tuple[int | None, list[Any]]:
    components, _r, _c, _s = priority.score_procurement(
        notice, classify(notice), profile=profile, source="g2b", now=NOW, **kwargs
    )
    return priority.normalize(components), components


# ---------------------------------------------------------------------------
# 마감은 점수에 들어가지 않는다 (§4-B-0)
# ---------------------------------------------------------------------------


def test_배점표에_마감이_없다() -> None:
    assert "schedule" not in priority.PRIORITY_WEIGHTS
    assert "scale" in priority.PRIORITY_WEIGHTS
    assert sum(priority.PRIORITY_WEIGHTS.values()) == 100


def test_마감일만_다른_두_공고는_점수가_같다(company: Any) -> None:
    """이것이 ISSUE-083 의 핵심이다. 마감이 배점에 있으면 순서가 곧 마감 순서가 된다."""
    profile = company
    soon = make_notice("URGENT", "생성형 AI 활용 실무교육 운영", deadline=NOW + timedelta(days=1))
    later = make_notice("ROOMY", "생성형 AI 활용 실무교육 운영", deadline=NOW + timedelta(days=40))

    a, components = score(soon, profile=profile)
    b, _ = score(later, profile=profile)
    assert a == b, f"마감만 다른데 점수가 갈렸다: {a} vs {b}"
    assert not any(c.key == "schedule" for c in components)
    assert all(c.key in priority.PRIORITY_WEIGHTS for c in components)


def test_마감이_지난_공고도_점수는_같고_라벨로만_구분된다(company: Any) -> None:
    """지난 공고를 0점으로 만들면 「왜 맞는 사업인가」라는 사실 자체가 지워진다."""
    profile = company
    past = make_notice("PAST", "생성형 AI 활용 실무교육 운영", deadline=NOW - timedelta(days=5))
    open_one = make_notice("OPEN", "생성형 AI 활용 실무교육 운영", deadline=NOW + timedelta(days=5))
    assert score(past, profile=profile)[0] == score(open_one, profile=profile)[0]
    assert priority.label_of(80, closed=True) == "마감"


def test_동점이면_마감이_빠른_쪽이_앞에_선다() -> None:
    """점수가 아니라 **2차 정렬**이다 (§4-B-8)."""
    early = _unified("early", score=70, deadline=NOW + timedelta(days=2))
    late = _unified("late", score=70, deadline=NOW + timedelta(days=20))
    ordered = opportunity_service.sort_opportunities([late, early], "priority")
    assert [i.id for i in ordered] == ["early", "late"]


def test_등록마감이_더_이르면_그것이_실제_데드라인이다() -> None:
    """한남대·KISTI 는 입찰 9-28 인데 참가자격 등록이 9-27 18:00 에 닫힌다."""
    item = _unified(
        "kisti",
        score=70,
        deadline=datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc),
        qualification_deadline=datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc),
    )
    assert opportunity_service.effective_deadline(item) == item.qualification_deadline

    # 정렬도 그 값을 본다 — 등록이 먼저 닫히는 쪽이 앞이다.
    other = _unified("other", score=70, deadline=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc))
    ordered = opportunity_service.sort_opportunities([other, item], "priority")
    assert [i.id for i in ordered] == ["kisti", "other"]


# ---------------------------------------------------------------------------
# 등급 (§4-B-1 · §4-B-3)
# ---------------------------------------------------------------------------


def test_사업영역은_네_등급이다(company: Any) -> None:
    profile = company

    def domain(title: str, **kwargs: Any) -> float | None:
        _s, components = score(make_notice("D", title, **kwargs), profile=profile)
        return next(c for c in components if c.key == "domain").score

    # 그 밖 — 전시·행사·대행·방송 제작·임차·감리·영향평가
    assert domain("2026 AI/SW 융합페어 및 Job Conference 대행 용역") == priority.DOMAIN_OTHER
    assert domain("AI기반 실종자 예측 시스템 구축 위탁 감리") == priority.DOMAIN_OTHER
    assert domain("AI 서비스 개인정보 영향평가") == priority.DOMAIN_OTHER
    # 우리 갈래
    assert domain("AI 기반 발파 설계 패턴 자동화 시스템 개발 용역") == priority.DOMAIN_TRACK
    # 두 축이 다 걸린다 — 만드는 일인데 대상이 교육이다
    assert domain("군 장병 맞춤형 AI 교육 서비스 개발") == priority.DOMAIN_BOTH_TRACKS


def test_검증_역량이_공고명에_있으면_만점이다(company: Any) -> None:
    profile = company
    capacity = SimpleNamespace(
        skills=[SimpleNamespace(name="챗봇", level="proven", aliases=("chatbot",))]
    )
    _s, components = score(
        make_notice("CHAT", "한양사이버대학교 AI 챗봇 서비스 구축"), profile=profile, capacity=capacity
    )
    domain = next(c for c in components if c.key == "domain")
    assert domain.score == priority.DOMAIN_PROVEN
    assert "챗봇" in domain.reason


def test_규모는_상한_기준으로_등급화된다() -> None:
    def value(budget: int, *, ceiling: int | None = None, joint: bool | None = None) -> float | None:
        return priority.scale_component(budget, ceiling=ceiling, joint_allowed=joint).score

    assert value(50_000_000) == 1.0  # 권장 2억의 절반 이하
    assert value(150_000_000) == 0.7
    assert value(250_000_000) == 0.3
    assert value(380_000_000) == 0.0  # 3인 단독으로는 할 수 없는 규모
    # 공동수급이 허용되면 어느 구간에서나 길이 열린다.
    assert value(380_000_000, joint=True) == 0.2
    assert value(190_000_000, joint=True) == 0.9
    # 회사가 상한을 적으면 그 값으로 잰다.
    assert value(50_000_000, ceiling=60_000_000) == 0.7
    assert priority.scale_component(None, ceiling=None, joint_allowed=None).score is None


def test_상한을_안_적었으면_화면_문구가_그렇게_말한다() -> None:
    reason = priority.scale_component(50_000_000, ceiling=None, joint_allowed=None).reason
    # 기대값 바꿈(27차 §3-E 금액 한 벌): 「2억」 → 「2억원」(프론트 formatBudgetCompact 와 같은 꼴)
    assert "권장 상한 2억원으로 가정" in reason and "회사 한도를 안 적어" in reason


def test_자격_판정_종합이_점수를_움직인다(company: Any) -> None:
    """4-A 뒤에는 업종·지역이 코드로 확정되므로 이 항목이 실제로 움직여야 한다 (§4-B-2)."""
    profile = company
    notice = make_notice("GATE", "생성형 AI 활용 실무교육 운영")
    a, _ = score(notice, profile=profile, gate="PASS")
    b, _ = score(notice, profile=profile, gate="CHECK")
    c, _ = score(notice, profile=profile, gate="FAIL")
    assert a > b > c


def test_발주기관이_광주_전남이면_전략_가산이다(company: Any) -> None:
    assert priority.home_ground("전남대학교 교육혁신본부", None) == "전남대학교 교육혁신본부"
    assert priority.home_ground("한국과학기술정보연구원", "광주광역시교육청") == "광주광역시교육청"
    assert priority.home_ground("한국과학기술정보연구원", "대전광역시") is None


# ---------------------------------------------------------------------------
# 「우선 검토」 (§4-B-6)
# ---------------------------------------------------------------------------


def test_우선_검토는_80점_이상이거나_상위_15퍼센트다() -> None:
    assert priority.PRIORITY_HIGH == 80
    scores = [90, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 4, 3, 2, 1, 0]
    cut = priority.top_cut_of(scores)
    # 20건의 상위 15% 는 3건 — 경계 점수는 세 번째다.
    assert cut == 65
    assert priority.label_of(90, closed=False, top_cut=cut) == "우선 검토"
    assert priority.label_of(65, closed=False, top_cut=cut) == "우선 검토"
    assert priority.label_of(60, closed=False, top_cut=cut) == "검토"
    # 점수가 낮게 깔려도 80점은 언제나 「우선 검토」다.
    assert priority.label_of(85, closed=False, top_cut=None) == "우선 검토"
    assert priority.top_cut_of([]) is None


def _unified(
    oid: str,
    *,
    score: int | None,
    deadline: datetime | None,
    qualification_deadline: datetime | None = None,
) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=oid,
        source_type="g2b",
        opportunity_type="procurement",
        title=f"정렬 확인용 {oid}",
        agency="시험기관",
        deadline=deadline,
        qualification_deadline=qualification_deadline,
        organization_id=ALPHA,
        company_priority_score=score,
        priority_rank=0,
        priority_label="검토",
        confidence="medium",
        score_components=[],
        next_route={"kind": "procurement_analysis", "path": "/", "label": "열기"},
        source="g2b",
    )
