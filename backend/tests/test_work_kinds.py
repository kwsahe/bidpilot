"""work_kinds: 일의 종류(갈래) 판정 테스트.

이 모듈은 「무슨 일을 시키는가」의 **단일 출처**다. 목록과 상세가 같은 규칙표를 보므로,
여기가 틀리면 두 화면이 같은 공고를 다르게 부른다. 그래서 투영표를 값마다 못박는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import capability_service, work_kinds
from app.services.g2b_mapper import KST

BASE_TIME = datetime(2026, 9, 10, 9, 0, tzinfo=KST)


def notice(title: str, *, description: str | None = None, agency: str = "테스트기관") -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-TEST-000",
        notice_no="TEST-000",
        title=title,
        agency=agency,
        published_at=BASE_TIME,
        deadline_at=BASE_TIME + timedelta(days=10),
        description=description,
    )


# ---------------------------------------------------------------------------
# 투영 — 새 규칙이 아니라 접기
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        (["education"], ["education"]),
        (["consulting"], ["education"]),
        (["development"], ["development"]),
        (["education", "development"], ["education", "development"]),
        ([], ["unclassified"]),
        # 우리 역할이 아닌 갈래가 하나라도 섞이면 「그 밖」이다 — 개발 낱말과 함께 와도 마찬가지다.
        (["supervision", "consulting", "development"], ["other"]),
        (["procurement", "development"], ["other"]),
        (["research", "development"], ["other"]),
        (["construction", "development"], ["other"]),
    ],
)
def test_track_projection(kinds: list[str], expected: list[str]) -> None:
    assert work_kinds.work_tracks(kinds) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # 전부 실제 나라장터 공고명이다.
        ("디지털배움터 플랫폼 AI 실습 기능 개발 위탁감리", ["other"]),
        ("2026년 생성형AI 교육을 위한 구독권(Google AI Pro) 및 기념품 제공", ["other"]),
        ("미래 AI반도체 기술개발 로드맵 수립 연구", ["other"]),
        ("AI-Science 데이터센터 신축사업 설계용역(전기)", ["other"]),
        ("가천대학교 AI부트캠프 사업 피지컬 AI 교육 기획·운영 위탁 용역", ["education"]),
        ("AI 활용 빌라시세 자동추정모델 개발 사업", ["development"]),
    ],
)
def test_real_notices_land_in_the_right_track(title: str, expected: list[str]) -> None:
    assert work_kinds.work_tracks(work_kinds.detect_work_kinds(title)) == expected


def test_a_notice_can_belong_to_both_tracks() -> None:
    """둘 다인 공고는 양쪽 탭에 나온다 — 억지로 하나를 고르지 않는다."""
    tracks = work_kinds.work_tracks(
        work_kinds.detect_work_kinds("AI 교육 플랫폼 구축 및 교육과정 운영 용역")
    )
    assert tracks == ["education", "development"]


# ---------------------------------------------------------------------------
# 판정 입력 — 발주기관명을 넣지 않는다
# ---------------------------------------------------------------------------


def test_agency_name_is_not_part_of_the_judgment() -> None:
    """기관 이름이 일의 종류를 뒤집으면 안 된다.

    실측: 「지방자치인재**개발**원」·「노인인력**개발**원」이 개발로, 「한국**교육**과정평가원」이
    교육으로 잡혔다. opportunity_filter 의 searchable_text 는 기관명을 포함하는데,
    그건 「AI 후보인가」를 넓게 잡으려는 것이고 「무슨 일인가」와는 다른 축이다.
    """
    n = notice("급식실 및 학생식당 증축사업 설계용역", agency="서울특별시북부교육지원청")
    assert "교육지원청" not in work_kinds.notice_work_text(n)
    assert work_kinds.of_notice(n)["tracks"] == ["other"]  # 공사·시설


def test_of_notice_reports_what_it_looked_at() -> None:
    result = work_kinds.of_notice(notice("AI 챗봇 개발 용역"))
    assert result["tracks"] == ["development"]
    assert result["basis"] == "공고명·요약"
    assert result["method"] == "RULE"


# ---------------------------------------------------------------------------
# 목록과 상세가 같은 말을 한다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "디지털배움터 플랫폼 AI 실습 기능 개발 위탁감리",
        "AI 활용 빌라시세 자동추정모델 개발 사업",
        "가천대학교 AI부트캠프 사업 피지컬 AI 교육 기획·운영 위탁 용역",
        "미래 AI반도체 기술개발 로드맵 수립 연구",
    ],
)
def test_detail_and_list_agree_on_development(title: str) -> None:
    """상세의 `is_development` 와 목록의 「개발」 갈래가 같은 규칙을 쓴다.

    두 화면이 같은 공고를 하나는 「개발」, 하나는 「감리」라고 부르면 담당자가 어느 쪽도 믿지 않는다.
    """
    kinds = work_kinds.detect_work_kinds(title)
    from_list = "development" in work_kinds.work_tracks(kinds)
    from_detail = "development" in kinds and not any(k in work_kinds.NOT_OUR_ROLE for k in kinds)
    assert from_list == from_detail


def test_capability_service_reuses_the_same_rules() -> None:
    """상세 분석이 자기 규칙표를 따로 들고 있지 않다 (두 번째 출처를 만들지 않는다)."""
    assert capability_service.detect_work_kinds is work_kinds.detect_work_kinds
    assert capability_service._WORK_KIND_RULES is work_kinds.WORK_KIND_RULES
