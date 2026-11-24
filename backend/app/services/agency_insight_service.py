"""발주기관 인사이트 — 캐시된 나라장터 공고에서 계산한다.

수치는 전부 `procurement_service`가 저장한 공고(실호출 캐시 + 고정 공고)에서 나온다.
조회 창 밖의 과거 공고나 낙찰 이력은 없으므로 "이 기관의 전체 발주 성향"이 아니라
**최근 조회 창 안의 관측치**다. 응답에 fetched_at과 window_days를 함께 실어 그 한계를 드러낸다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.services import g2b_mapper, procurement_service


class AgencyNotice(BaseModel):
    id: str
    title: str
    published_at: datetime
    deadline_at: datetime | None
    budget: int | None
    tier: str
    grade: str | None


class AgencyInsight(BaseModel):
    agency: str
    notice_count: int = Field(ge=0)
    ai_candidate_count: int = Field(ge=0)
    high_tier_count: int = Field(ge=0)
    budget_known_count: int = Field(ge=0)
    budget_avg: int | None
    budget_max: int | None
    latest_published_at: datetime | None
    regions: list[str]
    top_keywords: list[str]
    recent_notices: list[AgencyNotice]


class AgencyInsightList(BaseModel):
    source: str
    fetched_at: datetime | None
    window_days: int
    total_notices: int
    agencies: list[AgencyInsight]
    note: str


def _insight(agency: str, views: list[procurement_service.NoticeView]) -> AgencyInsight:
    budgets = [v.notice.budget for v in views if v.notice.budget]
    keywords: dict[str, int] = defaultdict(int)
    regions: dict[str, int] = defaultdict(int)
    for view in views:
        for keyword in view.match.matched_ai + view.match.matched_work:
            keywords[keyword] += 1
        # 캐시에 남아 있는 옛 공고는 region 에 지역 «이름»이 아니라 지역제한 «판단기준 이름»
        # (「본사또는참여지사소재지」)이 들어 있다. 그대로 세면 그것이 지역인 척 통계에 오른다.
        region = g2b_mapper.region_name(view.notice.region)
        if region:
            regions[region] += 1
    ordered = sorted(views, key=lambda v: v.notice.published_at, reverse=True)
    recent: list[AgencyNotice] = []
    for view in ordered[:5]:
        payload = view.to_dict()
        recent.append(
            AgencyNotice(
                id=view.notice.id,
                title=view.notice.title,
                published_at=view.notice.published_at,
                deadline_at=view.notice.deadline_at,
                budget=view.notice.budget,
                tier=view.match.tier,
                grade=(payload.get("recommendation") or {}).get("grade"),
            )
        )
    return AgencyInsight(
        agency=agency,
        notice_count=len(views),
        # 후보 판정은 CandidateMatch.is_candidate 한 곳에서만 한다 — 등급 목록을 여기서 다시 적으면 어긋난다.
        ai_candidate_count=sum(1 for v in views if v.match.is_candidate),
        high_tier_count=sum(1 for v in views if v.match.tier == "high"),
        budget_known_count=len(budgets),
        budget_avg=int(sum(budgets) / len(budgets)) if budgets else None,
        budget_max=max(budgets) if budgets else None,
        latest_published_at=ordered[0].notice.published_at if ordered else None,
        regions=[r for r, _ in sorted(regions.items(), key=lambda p: -p[1])],
        top_keywords=[k for k, _ in sorted(keywords.items(), key=lambda p: -p[1])[:5]],
        recent_notices=recent,
    )


def build_from_result(result: procurement_service.ProcurementResult, *, window_days: int) -> AgencyInsightList:
    by_agency: dict[str, list[procurement_service.NoticeView]] = defaultdict(list)
    for view in result.notices:
        by_agency[view.notice.agency or "기관 미상"].append(view)
    agencies = [_insight(name, views) for name, views in by_agency.items()]
    agencies.sort(key=lambda a: (-a.notice_count, -a.high_tier_count, a.agency))
    return AgencyInsightList(
        source=result.source,
        fetched_at=result.fetched_at,
        window_days=window_days,
        total_notices=len(result.notices),
        agencies=agencies,
        note=(
            "최근 조회 창(공고게시일 기준) 안의 AI·교육 후보 공고에서 계산한 관측치다. "
            "기관의 전체 발주 이력·낙찰 결과는 포함하지 않는다."
        ),
    )


async def list_agencies(*, days: int = procurement_service.DEFAULT_DAYS) -> AgencyInsightList:
    result = await procurement_service.list_ai_candidates(days=days, include_low=True)
    return build_from_result(result, window_days=days)


async def get_agency(name: str, *, days: int = procurement_service.DEFAULT_DAYS) -> AgencyInsight | None:
    listing = await list_agencies(days=days)
    for agency in listing.agencies:
        if agency.agency == name:
            return agency
    return None


def to_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
