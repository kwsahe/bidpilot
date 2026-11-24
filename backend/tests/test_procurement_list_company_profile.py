"""목록 화면의 추천등급이 «선택한 회사»의 프로필을 보고 판단하는가 (ISSUE-057).

예전에는 목록(`NoticeView.to_dict`)과 정렬(`rank_notices`)만 회사 프로필을 넘기지 않아,
지역은 합성 상수(광주·전남)로, 예산은 언제나 「아직 적지 않아 판정하지 않았습니다」로 굳었다.
통합 목록(opportunity_priority)은 이미 회사 값으로 계산하고 있었으므로 한 공고의 등급이
화면마다 달랐다. 여기서 보는 것은 «두 화면이 같은 기준을 쓰는가»다.

적어 둔 값이 없으면 숫자를 지어내지 않는다는 규칙(CLAUDE.md 11·12)도 함께 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.config import get_settings
from app.schemas.delivery_capacity import DeliveryCapacityUpdate
from app.schemas.organization import OrganizationProfileUpdate
from app.schemas.procurement import ProcurementNotice
from app.services import (
    company_service,
    delivery_capacity_service,
    organization_service,
    procurement_service,
)
from app.services.opportunity_filter import classify

CAPACITY_KRW = 300_000_000
NOTICE_BUDGET = 200_000_000


def default_org() -> str:
    return get_settings().default_organization_id


def make_notice(*, notice_id: str = "g2b-TEST-001", region: str | None = "부산광역시") -> ProcurementNotice:
    """마감이 남은 AI 교육 공고 1건. 마감 경과(No-Go)로 빠지지 않게 미래 날짜를 쓴다."""
    now = datetime.now(timezone.utc)
    return ProcurementNotice(
        id=notice_id,
        notice_no=notice_id.replace("g2b-", ""),
        title="생성형 AI 활용 실무교육 운영 용역",
        agency="테스트기관",
        published_at=now - timedelta(days=1),
        deadline_at=now + timedelta(days=30),
        budget=NOTICE_BUDGET,
        region=region,
        description="공공기관 직원 대상 생성형 AI 활용 실무교육 운영",
    )


def save_profile(*, regions: list[str]) -> None:
    organization_service.save_profile(
        default_org(),
        OrganizationProfileUpdate(
            name="가상 AI교육 컴퍼니",
            business_domains=["생성형 AI 교육", "AI 컨설팅"],
            target_clients=["공공기관"],
            preferred_regions=regions,
            data_class="synthetic",
            updated_by="테스트",
        ),
    )


def reasons_of(notice: ProcurementNotice) -> dict[str, str]:
    payload = procurement_service.NoticeView(notice=notice, match=classify(notice)).to_dict()
    return {c["key"]: c["reason"] for c in payload["recommendation"]["components"]}


@pytest.fixture(autouse=True)
def _fresh_basis() -> Any:
    """회사 프로필 캐시를 테스트 앞뒤로 비운다.

    같은 프로세스 안에서 앞 테스트가 읽어 둔 회사 값이 남아 있으면, 이 테스트가 무엇을
    적어 두든 결과가 앞 테스트의 회사로 나온다.
    """
    procurement_service.clear_memo()
    yield
    procurement_service.clear_memo()


def test_list_recommendation_uses_profile_region_and_recorded_capacity() -> None:
    """활동 지역·단독 수행 규모를 적어 두면 목록의 추천 사유에 그 값이 그대로 나온다."""
    save_profile(regions=["부산광역시"])
    delivery_capacity_service.save(
        default_org(),
        DeliveryCapacityUpdate(budget_ceiling_krw=CAPACITY_KRW, updated_by="테스트"),
    )

    reasons = reasons_of(make_notice(region="부산광역시"))

    # 합성 상수(광주·전남)가 아니라 회사가 적어 둔 지역으로 판정한다.
    assert "우선 활동 지역" in reasons["strategic_fit"]
    assert "부산광역시" in reasons["strategic_fit"]
    # 회사가 적어 둔 규모가 사유 문장에 숫자로 나온다.
    # 기대값 바꿈(27차 §3-E 금액 한 벌 · 검수 R27U-MSC-02): 「300,000,000원」 → 「3억원」
    from app.core.money import won

    assert won(CAPACITY_KRW) in reasons["budget_fit"]
    assert "판정하지 않았습니다" not in reasons["budget_fit"]


def test_list_recommendation_does_not_invent_values_when_profile_is_empty() -> None:
    """활동 지역·수행 규모를 적지 않았으면 「판정하지 않았습니다」로 남긴다 (0점이 아니다)."""
    # 「전국」은 지역 이름이 아니므로 대조할 지역이 하나도 없는 상태가 된다.
    save_profile(regions=["전국"])

    reasons = reasons_of(make_notice(region="부산광역시"))

    assert "활동 지역이 없어 판정하지 않았습니다" in reasons["strategic_fit"]
    assert "아직 적지 않아 판정하지 않았습니다" in reasons["budget_fit"]


def test_ranking_uses_the_same_company_basis_as_the_row() -> None:
    """정렬도 같은 회사 기준을 쓴다 — 1위로 올린 행과 화면에 찍히는 등급이 어긋나면 안 된다."""
    save_profile(regions=["부산광역시"])

    home = make_notice(notice_id="g2b-TEST-HOME", region="부산광역시")
    away = make_notice(notice_id="g2b-TEST-AWAY", region="대전광역시")
    views = [
        procurement_service.NoticeView(notice=n, match=classify(n)) for n in (away, home)
    ]

    ranked = procurement_service.rank_notices(views)

    assert [v.notice.id for v in ranked] == ["g2b-TEST-HOME", "g2b-TEST-AWAY"]
    assert "우선 활동 지역" in reasons_of(ranked[0].notice)["strategic_fit"]


def test_unreadable_company_data_does_not_break_the_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """회사자료를 못 읽어도 목록 조회는 계속된다 — 예전처럼 넘기지 않고 계산한다."""

    def _boom(_organization_id: str) -> Any:
        raise RuntimeError("회사 프로필 저장소 접근 실패")

    monkeypatch.setattr(company_service, "load_profile", _boom)

    reasons = reasons_of(make_notice(region="부산광역시"))

    # 회사 값 없이 계산한 결과라도 사유 문장은 남아 있어야 한다.
    assert reasons["strategic_fit"]
    assert "아직 적지 않아 판정하지 않았습니다" in reasons["budget_fit"]
