"""capability_service: 개발 수행역량 판정 테스트.

이 판정의 위험은 «틀리는 것»보다 «모르는 것을 아는 척하는 것»이다. 그래서 테스트의 절반은
정확도가 아니라 **정직함**을 지킨다 — 부재가 부정으로 새어 나가지 않는지, 회사가 정하지 않은
숫자를 시스템이 대신 채우지 않는지, 낱말이 같다고 같은 기술이라고 말하지 않는지.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.delivery_capacity import Credential, DeliveryCapacity, SkillEntry
from app.schemas.procurement import ProcurementNotice
from app.services import capability_service
from app.services.g2b_mapper import KST

BASE_TIME = datetime(2026, 9, 10, 9, 0, tzinfo=KST)


def make_notice(
    title: str,
    *,
    description: str | None = None,
    budget: int | None = None,
    raw_data: dict | None = None,
) -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-TEST-000",
        notice_no="TEST-000",
        title=title,
        agency="테스트기관",
        published_at=BASE_TIME,
        deadline_at=BASE_TIME + timedelta(days=10),
        description=description,
        budget=budget,
        raw_data=raw_data or {},
    )


def capacity(**overrides) -> DeliveryCapacity:
    base = {
        "organization_id": "org-test",
        "developer_count": 3,
        "skills": [
            SkillEntry(name="RAG", level="proven", aliases=["검색증강"], source="테스트"),
            SkillEntry(name="챗봇", level="proven", aliases=["chatbot"], source="테스트"),
        ],
        "credentials": [Credential(name="소프트웨어사업자 신고", held=None)],
        "source": "file",
    }
    base.update(overrides)
    return DeliveryCapacity.model_validate(base)


@pytest.fixture()
def recorded(monkeypatch: pytest.MonkeyPatch):
    """회사 역량자료가 기록돼 있는 상태."""
    monkeypatch.setattr(capability_service.delivery_capacity_service, "load", lambda _oid: capacity())


@pytest.fixture()
def absent(monkeypatch: pytest.MonkeyPatch):
    """회사 역량자료가 없는 상태."""
    empty = DeliveryCapacity(organization_id="org-test", source="absent")
    monkeypatch.setattr(capability_service.delivery_capacity_service, "load", lambda _oid: empty)


# ---------------------------------------------------------------------------
# 일의 종류 — 「무슨 일을 시키는가」
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected_kind"),
    [
        ("디지털배움터 플랫폼 AI 실습 기능 개발 위탁감리", "supervision"),
        ("2026년 생성형AI 교육을 위한 구독권(Google AI Pro) 및 기념품 제공", "procurement"),
        ("미래 AI반도체 기술개발 로드맵 수립 연구", "research"),
        ("AI-Science 데이터센터 신축사업 설계용역(전기)", "construction"),
    ],
)
def test_not_our_role_work_kinds_are_detected(title: str, expected_kind: str) -> None:
    """감리·구매·연구·공사는 «개발 수행 사업»이 아니다. 전부 실제 나라장터 공고명이다."""
    kinds = capability_service.detect_work_kinds(title)
    assert expected_kind in kinds


def test_development_work_kind_survives(recorded) -> None:
    report = capability_service.evaluate(
        make_notice("AI 활용 빌라시세 자동추정모델 개발 사업"),
        organization_id="org-test",
        now=BASE_TIME,
    )
    assert "development" in report.work_kinds
    assert report.is_development is True


def test_supervision_notice_is_not_a_development_project(recorded) -> None:
    report = capability_service.evaluate(
        make_notice("디지털배움터 플랫폼 AI 실습 기능 개발 위탁감리"),
        organization_id="org-test",
        now=BASE_TIME,
    )
    assert report.is_development is False
    work = next(f for f in report.findings if f.finding_id == "CAP-WORKKIND")
    assert work.status == "gap"
    assert "감리" in work.reason


# ---------------------------------------------------------------------------
# 정직함 — 모르는 것을 아는 척하지 않는다
# ---------------------------------------------------------------------------


def test_absent_capacity_never_judges(absent) -> None:
    """회사자료가 없으면 인원·기술·규모를 판정하지 않는다. 3명으로 가정하지 않는다."""
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역", description="RAG 기반 상담 챗봇 개발"),
        organization_id="org-test",
        now=BASE_TIME,
    )
    assert report.capacity_recorded is False
    assert report.counts.get("supported", 0) == 0
    ids = {f.finding_id for f in report.findings}
    assert "CAP-STAFFING" not in ids
    assert "CAP-SCALE" not in ids
    # 인원 수가 응답 어디에도 새어 나오지 않는다.
    blob = report.model_dump_json()
    assert "3명" not in blob


def test_unknown_reasons_never_say_the_company_cannot(recorded) -> None:
    """부재가 부정으로 미끄러지지 않는다 — 이 테스트가 그 미끄럼틀을 막는다."""
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역", description="RAG 기반 상담 챗봇 개발"),
        organization_id="org-test",
        requirement_text="본 사업은 임베디드 펌웨어 개발을 포함한다.",
        now=BASE_TIME,
    )
    for finding in report.findings:
        if finding.status != "unknown":
            continue
        for banned in capability_service.FORBIDDEN_IN_UNKNOWN:
            assert banned not in finding.reason, f"{finding.finding_id}: {finding.reason}"


def test_skill_not_recorded_is_unknown_not_gap(recorded) -> None:
    """회사자료에 없는 기술은 «모른다»이지 «못 한다»가 아니다."""
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발", description="RAG 검색 기능 개발"),
        organization_id="org-test",
        requirement_text="RAG 검색과 챗봇 응답 기능을 개발한다.",
        now=BASE_TIME,
    )
    ids = {f.finding_id for f in report.findings}
    # 회사자료에 적혀 있지 않은 기술은 아예 항목이 만들어지지 않는다(추정하지 않는다).
    assert "CAP-SKILL-kubernetes" not in ids


def test_scale_is_not_judged_without_a_company_ceiling(recorded) -> None:
    """예산 상한은 회사가 정할 값이다. 코드 상수(3억 등)로 대신 채우지 않는다."""
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역", budget=2_000_000_000),
        organization_id="org-test",
        now=BASE_TIME,
    )
    scale = next(f for f in report.findings if f.finding_id == "CAP-SCALE")
    assert scale.status == "unknown"
    assert "3억" not in scale.reason
    assert "300,000,000" not in scale.reason


def test_scale_is_judged_once_the_company_sets_a_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        capability_service.delivery_capacity_service,
        "load",
        lambda _oid: capacity(budget_ceiling_krw=300_000_000),
    )
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역", budget=2_000_000_000),
        organization_id="org-test",
        now=BASE_TIME,
    )
    scale = next(f for f in report.findings if f.finding_id == "CAP-SCALE")
    assert scale.status == "gap"
    assert scale.evidence.company_where  # 회사 쪽 근거가 함께 붙는다


# ---------------------------------------------------------------------------
# 낱말이 같다고 같은 기술이 아니다 — 「마운트 에이전트」 사례
# ---------------------------------------------------------------------------


def test_same_word_in_another_field_is_not_a_capability_match(recorded) -> None:
    """비소프트웨어 어휘가 우세하면 낱말이 걸려도 «보유»로 판정하지 않는다.

    실측: 「마운트 에이전트 개발을 위한 DB 구축 용역」(한국기계연구원)의 «에이전트»는
    AI 에이전트가 아니라 방진 마운트 제품의 이름이었고, 과업은 제조장치 설계와 특성시험이었다.
    """
    mechanical = (
        "마운트 특성 DB 구축, 마운트 제조장치 설계. 정하중-변위 시험을 수행하고 "
        "하중 곡선과 동적 강성, 시험장비와 치구 정보를 기록한다. 재질과 열처리, "
        "방진 성능과 진동·소음을 분석하고 도면 작성을 한다."
    )
    report = capability_service.evaluate(
        make_notice("챗봇 마운트 개발을 위한 DB 구축 용역"),
        organization_id="org-test",
        requirement_text=mechanical,
        requirement_where="과업지시서",
        now=BASE_TIME,
    )
    domain = next(f for f in report.findings if f.finding_id == "CAP-DOMAIN")
    assert domain.status == "gap"
    skill = next((f for f in report.findings if f.finding_id.startswith("CAP-SKILL")), None)
    assert skill is not None
    assert skill.status == "unknown", "분야가 다르면 낱말이 같아도 보유로 단정하지 않는다"


def test_domain_is_not_decided_from_the_title_alone(recorded) -> None:
    """제목만으로 «소프트웨어가 아니다»를 단정하지 않는다."""
    report = capability_service.evaluate(
        make_notice("마운트 에이전트 개발을 위한 DB 구축 용역"),
        organization_id="org-test",
        now=BASE_TIME,
    )
    domain = next(f for f in report.findings if f.finding_id == "CAP-DOMAIN")
    assert domain.status == "unknown"
    assert report.used_requirements is False


# ---------------------------------------------------------------------------
# 투입 인력
# ---------------------------------------------------------------------------


def test_headcount_ignores_non_staffing_numbers() -> None:
    """「심사위원 8명 이상」·「참석 인원 25명 이상」은 요구 투입 인력이 아니다."""
    assert capability_service.required_headcount("기술 평가위원회는 심사위원 8명 이상으로 구성한다") is None
    assert capability_service.required_headcount("교육 참석 예정 인원이 25명 이상인 경우") is None
    assert capability_service.required_headcount("수강생 30명 이상 모집") is None


def test_headcount_reads_real_staffing_clauses() -> None:
    found = capability_service.required_headcount("본 사업에 투입 인력 5명 이상을 배치하여야 한다")
    assert found is not None and found[0] == 5


def test_dedicated_staff_clause_is_read(recorded) -> None:
    """「전담 PM 1인을 지정」은 이상(以上)이 없어도 인력 요구다. 실측: 마운트 과업지시서 8-라."""
    clause = "을은 전담 PM 또는 기술담당자 1인을 지정하여야 하며, 일정관리를 총괄한다."
    found = capability_service.required_headcount(clause)
    assert found is not None and found[0] == 1

    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역"),
        organization_id="org-test",
        requirement_text=clause,
        now=BASE_TIME,
    )
    staffing = next(f for f in report.findings if f.finding_id == "CAP-STAFFING")
    # 인원은 채우지만 전담이라 다른 사업과 함께 굴릴 수 없다 — 확정하지 않는다.
    assert staffing.status == "unknown"
    assert "전담" in staffing.reason


def test_headcount_gap_when_more_people_are_required(recorded) -> None:
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역"),
        organization_id="org-test",
        requirement_text="사업 수행 인력 10명 이상을 투입하여야 한다.",
        now=BASE_TIME,
    )
    staffing = next(f for f in report.findings if f.finding_id == "CAP-STAFFING")
    assert staffing.status == "gap"
    assert staffing.evidence.notice_quote and staffing.evidence.company_fact


# ---------------------------------------------------------------------------
# 참가자격 등록 마감 — 판정이 아니라 사실 전달
# ---------------------------------------------------------------------------


def test_qualification_deadline_is_reported_as_info(recorded) -> None:
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역", raw_data={"qualification_deadline": "2026-09-21 18:00"}),
        organization_id="org-test",
        now=BASE_TIME,
    )
    schedule = next(f for f in report.findings if f.finding_id == "CAP-SCHEDULE")
    assert schedule.status == "info"
    assert "2026-09-21 18:00" in schedule.reason


def test_no_qualification_deadline_means_no_item(recorded) -> None:
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역"), organization_id="org-test", now=BASE_TIME
    )
    assert all(f.finding_id != "CAP-SCHEDULE" for f in report.findings)


# ---------------------------------------------------------------------------
# 양면 근거
# ---------------------------------------------------------------------------


def test_supported_findings_always_carry_both_sides(recorded) -> None:
    """supported·gap 은 공고 쪽 근거와 회사 쪽 사실이 둘 다 있어야 한다."""
    report = capability_service.evaluate(
        make_notice("AI 챗봇 개발 용역", description="RAG 기반 상담 챗봇을 개발한다"),
        organization_id="org-test",
        requirement_text="RAG 검색 기능과 챗봇 응답 기능을 개발한다. 투입 인력 2명 이상.",
        requirement_where="과업지시서",
        now=BASE_TIME,
    )
    for finding in report.findings:
        if finding.finding_id in ("CAP-WORKKIND", "CAP-DOMAIN"):
            continue  # 공고 쪽만으로 판정하는 항목
        if finding.status in ("supported", "gap"):
            assert finding.evidence.notice_quote, f"{finding.finding_id}: 공고 근거 없음"
            assert finding.evidence.company_fact, f"{finding.finding_id}: 회사 근거 없음"
