"""0925 §4-D — 문구·분모·이력.

10차의 화면에는 **이미 아는 것을 다시 확인하라는 말**과 **서로 다른 세 개의 같은 숫자**가
있었다. 여기서 재는 것은 계산이 아니라 «화면이 사실을 말하는가»다.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from app.api import insights
from app.schemas.business_opportunity import (
    NextRoute,
    OpportunitySummary,
    SupportProgram,
    UnifiedOpportunity,
    UnifiedOpportunityListResponse,
)
from app.services import bizinfo_document_store as store
from app.services import opportunity_priority as priority
from app.services import bizinfo_service, opportunity_service, organization_service
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from app.services.eligibility_engine import CompanyFacts

TODAY = date(2026, 9, 18)
SAMPLEEDU = CompanyFacts(
    from_real_company=True,
    certifications=("사회적기업",),
    location_region="전남광주",
    # 43차 BIZ-16 — 「광주광역시」 소재는 회사 옛 지역을 본다(실제 샘플에듀 주소 광주 북구)
    location_old_region="광주",
    location_district="북구",
    founded_year=2021,
    employee_count=None,
)


def document(*pages: str) -> str:
    return store.join_pages(pages)


# --------------------------------------------------------------------------
# §4-D-1 — 「주의」는 **못 찾은 것**만
# --------------------------------------------------------------------------

#: 넷(업력·기업유형·중복지원·제외 대상)을 모두 담은 공고문.
ALL_FOUR = document(
    "○ 신청자격\n"
    "- 창업 7년 이내 중소기업\n"
    "- 사회적기업 또는 협동조합\n"
    "○ 지원 제외 대상\n"
    "- 타 사업과 중복지원을 받는 기업은 제외한다"
)


def test_넷을_다_찾았으면_주의_줄이_없다() -> None:
    requirements = extractor.extract_from_text("P", ALL_FOUR)
    assert sas.unfound_conditions(requirements) == []


def test_못_찾은_것만_이름으로_적는다() -> None:
    requirements = extractor.extract_from_text(
        "P", document("○ 신청자격\n- 사회적기업 또는 협동조합")
    )
    assert sas.unfound_conditions(requirements) == ["창업 연차", "중복 신청 제한", "제외 대상"]


def test_공고문을_못_읽었으면_못_찾은_것을_세지_않는다() -> None:
    """안 읽은 공고에 「못 찾았다」고 적으면 읽고 못 찾은 것과 구분이 사라진다."""
    requirements = extractor.load("없는-공고-아이디")
    assert requirements.document_read is False
    assert sas.unfound_conditions(requirements) == []


def _checks(*, read: bool, unfound: list[str]) -> list[str]:
    program = SupportProgram(id="bizinfo-T", title="시험 사업", agency="기관")  # type: ignore[arg-type]
    _, _, checks, _ = priority.score_support(
        program,
        bizinfo_service.support_fit(program, today=TODAY),
        profile=organization_service.load_profile("org-sample"),
        source="cached",
        gate="CHECK",
        signals={"read": read, "unfound": unfound},
    )
    return checks


def test_읽은_공고는_이미_읽은_것을_읽으라고_하지_않는다() -> None:
    """10차는 읽었든 안 읽었든 같은 문장을 냈다 (0925 §4-D-1)."""
    read_all = _checks(read=True, unfound=[])
    assert not any("공고 원문에서 확인해야" in c for c in read_all), read_all

    read_some = _checks(read=True, unfound=["창업 연차", "중복 신청 제한"])
    assert "공고문에 안 보이는 조건: 창업 연차 · 중복 신청 제한 — 원문에서 확인하세요" in read_some

    unread = _checks(read=False, unfound=[])
    assert any("신청자격(창업 연차 · 기업 유형 · 중복 신청 제한 · 제외 대상)" in c for c in unread)


# --------------------------------------------------------------------------
# §4-D-4 — 「왜 맞나」는 맞은 **회사 사실**만
# --------------------------------------------------------------------------


def test_왜_맞나는_맞은_회사_사실만_적는다() -> None:
    """10차의 이 줄은 「지원사업 · 인력 · 전남광주」 — 분류와 지역 해시태그였다."""
    requirements = extractor.extract_from_text(
        "P", document("○ 신청자격\n- 광주광역시 본사소재 사회적기업")
    )
    program = SupportProgram(id="bizinfo-T", title="시험", agency="기관")  # type: ignore[arg-type]
    rules, _ = sas.biz_rules_v2(program, requirements, company=SAMPLEEDU, today=TODAY)
    line = sas.company_fact_line(requirements, rules)
    assert "사회적기업" in line
    assert "광주" in line
    # 분류·지역 해시태그는 이 줄이 아니다.
    assert "지원사업" not in line


def test_맞은_회사_사실이_없으면_없다고_적는다() -> None:
    requirements = extractor.extract_from_text("P", document("○ 지원내용\n- 컨설팅 제공"))
    program = SupportProgram(id="bizinfo-T", title="시험", agency="기관")  # type: ignore[arg-type]
    rules, _ = sas.biz_rules_v2(program, requirements, company=SAMPLEEDU, today=TODAY)
    assert sas.company_fact_line(requirements, rules) == sas.NO_COMPANY_FACT


# --------------------------------------------------------------------------
# §4-D-2 — 칩의 분모는 지금 목록
# --------------------------------------------------------------------------


def _item(id_: str, source_type: str, gate: str) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=id_,
        source_type=source_type,  # type: ignore[arg-type]
        opportunity_type="support_program" if source_type == "bizinfo" else "procurement",
        title=id_,
        agency="기관",
        organization_id="org-sample",
        priority_rank=0,
        priority_label="검토",
        eligibility_gate=gate,  # type: ignore[arg-type]
        confidence="medium",
        score_components=[],
        next_route=NextRoute(kind="support_application", path="/", label="열기"),
        source="cached",
    )


def test_칩의_분모는_거른_뒤의_건수다() -> None:
    """탭은 578, 칩은 1578 을 말했다 — 같은 화면의 같은 숫자다 (0925 §4-D-2)."""
    items = [_item(f"b{i}", "bizinfo", "FAIL" if i >= 2 else "CHECK") for i in range(5)]
    items += [_item("g1", "g2b", "PASS")]
    opportunity_service.sort_opportunities(items, "priority")
    assert {i.source_total for i in items if i.source_type == "bizinfo"} == {5}

    shown = [i for i in items if i.eligibility_gate != "FAIL"]
    opportunity_service.renumber_sources(shown)
    bizinfo = [i for i in shown if i.source_type == "bizinfo"]
    assert {i.source_total for i in bizinfo} == {2}
    assert sorted(i.source_rank for i in bizinfo) == [1, 2]


# --------------------------------------------------------------------------
# §4-D-3 — 저장 이력의 조건
# --------------------------------------------------------------------------


def _listing(*items: UnifiedOpportunity) -> UnifiedOpportunityListResponse:
    """받아 둔 풀은 1,710건인데 내보낸 행은 넷 — 10차가 헷갈린 바로 그 차이다."""
    from datetime import datetime, timezone

    return UnifiedOpportunityListResponse(
        organization_id="org-sample",
        organization_name="주식회사샘플에듀",
        total_count=1710,
        g2b_count=105,
        bizinfo_count=1605,
        returned_count=len(items),
        closed_count=0,
        source_status={},
        source_errors={},
        fetched_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
        summary=OpportunitySummary(
            open_total=1710, open_g2b=105, open_bizinfo=1605,
            priority=0, closed=0, closed_pinned=0, days=30, new_days=3,
        ),
        sort="priority",
        field_mapping_verified=True,
        note="시험",
        items=list(items),
    )


def test_저장_이력은_필터와_내보낸_행을_적는다() -> None:
    """「(나라장터 105 · 기업마당 1605)」는 받아 둔 풀의 크기였다 (0925 §4-D-3)."""
    listing = _listing(_item("g1", "g2b", "PASS"), *[_item(f"b{i}", "bizinfo", "CHECK") for i in range(3)])
    line = insights.export_conditions(
        listing, days=30, source="all", include_closed=False, include_blocked=False
    )
    assert line == "출처 전체 · 최근 30일 · 회사 기준 검토 우선순위순 · 내보낸 4행 (나라장터 1 · 기업마당 3)"  # 37차 — 정렬 이름 다섯(점수순 = 「회사 기준 검토 우선순위순」)
    # 풀 크기는 적지 않는다.
    assert "1605" not in line

    with_flags = insights.export_conditions(
        listing, days=14, source="bizinfo", include_closed=True, include_blocked=True
    )
    assert "마감 포함" in with_flags and "불가 포함" in with_flags


# --------------------------------------------------------------------------
# §4-D-5 — 셸의 실조회 스위치가 테스트를 흔들지 않는다
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH"])
def test_실조회_스위치는_테스트에_새지_않는다(name: str) -> None:
    """`start_dev.ps1 -Frozen` 을 쓴 셸에서 pytest 가 통과해야 한다 (0925 §4-D-5).

    **기대값이 뒤집혔다** (14차 · prompt_03 §4-A-1 · ISSUE-120). 11차에 이 줄을 쓸 때는
    설정 기본값이 「켜짐」이라 「셸의 0 이 새지 않았다」를 `is True` 로 확인했다. 이제
    기본값이 「꺼짐」이므로 같은 뜻이 `is False` 다 — 재는 것은 그때나 지금이나
    **셸이 아니라 설정 기본값을 본다**는 것 하나다.
    """
    from app.core.config import Settings, get_settings

    assert name not in os.environ
    assert getattr(get_settings(), name.lower()) is False
    assert Settings.model_fields[name.lower()].default is False
