"""범용 설치 키트 — 샘플에듀 고정값을 남의 회사에 넣지 않는다 (30차 §3-G).

샘플에듀 설치(이 PC)는 설정 기본값 그대로라 동작이 같다. 키트는 `.env` 에 `NEUTRAL_COMPANY_DEFAULTS=1` 을 둔다.
저장 경로는 conftest 가 tmp 로 돌린다.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services import eligibility_engine, organization_service


def test_샘플에듀_설치는_합성_기본값이_그대로다() -> None:
    assert get_settings().neutral_company_defaults is False
    profile = organization_service.load_profile(organization_service.DEFAULT_ORGANIZATION_ID)
    assert profile.source == "default_synthetic" and "AI 활용 교육" in profile.business_domains
    assert eligibility_engine.active_regions() == eligibility_engine.COMPANY_PROFILE.preferred_regions


def test_키트는_사업영역_지역을_비워_회사_정보_필요로_둔다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "neutral_company_defaults", True)
    profile = organization_service.load_profile(organization_service.DEFAULT_ORGANIZATION_ID)
    assert profile.source == "default_synthetic"
    assert profile.business_domains == [] and profile.preferred_regions == [] and profile.target_clients == []
    assert eligibility_engine.active_regions() == ()
