"""opportunity_filter: AI·AI교육 후보 키워드 필터 테스트.

이 단계는 의미 유사도가 아니라 **키워드 규칙**이며, 판정 근거(매칭 키워드)를
반드시 함께 남겨야 한다. 짧은 영문 키워드(AI/DX/LLM)가 다른 단어에 섞여
오탐하지 않는지(MAIN/RAIN 등)를 중점적으로 확인한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services.g2b_mapper import KST
from app.services.opportunity_filter import (
    classify,
    filter_candidates,
    matched_keywords,
    searchable_text,
)

BASE_TIME = datetime(2026, 8, 20, 9, 0, tzinfo=KST)


def make_notice(
    title: str,
    *,
    notice_id: str = "g2b-TEST-000",
    description: str | None = None,
    agency: str = "테스트기관",
    deadline_days: int | None = 10,
) -> ProcurementNotice:
    return ProcurementNotice(
        id=notice_id,
        notice_no=notice_id.removeprefix("g2b-"),
        title=title,
        agency=agency,
        published_at=BASE_TIME,
        deadline_at=None if deadline_days is None else BASE_TIME + timedelta(days=deadline_days),
        description=description,
    )


# --------------------------------------------------------------------------
# 등급 판정
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("생성형 AI 활용 실무교육 운영 용역", "high"),  # AI + 업무
        ("인공지능 역량강화 아카데미 운영", "high"),
        ("AI GPU 서버 구축 용역", "low"),  # AI만 — 2차 키워드가 없으면 후보로 올리지 않는다
        ("인공지능 데이터 라벨링 용역", "low"),
        ("2026학년도 급식 종사자 위생교육 위탁", "low"),  # 업무만
        ("도로 포장 보수 공사 감독 용역", "none"),
    ],
)
def test_tier_matrix(title: str, expected: str) -> None:
    assert classify(make_notice(title)).tier == expected


@pytest.mark.parametrize(
    "title",
    [
        "AI타워ㆍ지하주차장 착공 후 지하안전조사 용역",
        "AI-Science 데이터센터 신축사업 설계용역(전기)",
        "모빌리티 부품 제조AI 확산센터 기본 및 실시설계 용역",
    ],
)
def test_ai_in_building_name_is_not_a_candidate(title: str) -> None:
    """«AI» 가 건물·센터 **이름의 일부**인 시설 공고는 기본 화면에 올리지 않는다.

    셋 다 실제 나라장터 수집분이다. AI 키워드는 잡히지만 교육·컨설팅도 개발도 아니다.
    빠지는 게 아니라 `low` 로 내려간다 (API `include_low=true` 로는 조회된다).
    """
    match = classify(make_notice(title))
    assert match.matched_ai, "AI 키워드 자체는 잡혀야 한다 (근거는 남는다)"
    assert match.tier == "low"
    assert match.is_candidate is False


def test_only_high_is_a_candidate() -> None:
    """후보는 «AI + 2차 키워드» 하나뿐이다. `medium` 은 아무 공고도 받지 않는다."""
    assert classify(make_notice("생성형 AI 교육")).is_candidate is True
    assert classify(make_notice("AI 챗봇 개발 용역")).is_candidate is True
    assert classify(make_notice("AI 서버 구축")).is_candidate is False  # AI만
    # 38차 §3-A — 위탁교육은 회사 본업(대학 · 공공기관 위탁교육)이라 AI 낱말이 없어도 후보다(담당자 결정 1).
    assert classify(make_notice("직원 교육 위탁")).is_candidate is True
    assert classify(make_notice("도로 보수")).is_candidate is False


# --------------------------------------------------------------------------
# 짧은 영문 키워드 단어 경계 (오탐 방지)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "MAIN 시스템 유지관리 용역",
        "RAIN 강우 관측장비 구매",
        "CHAIN 물류 통합관리",
        "BRAIN 연구지원 사업",
        "FAIR 박람회 운영 용역",  # AI가 들어있지 않지만 유사 오탐 방지 확인
    ],
)
def test_short_ascii_keyword_does_not_match_inside_word(title: str) -> None:
    match = classify(make_notice(title))
    assert "AI" not in match.matched_ai


@pytest.mark.parametrize(
    "title",
    [
        "AI 기반 행정업무 지원",
        "(AI)활용 시범사업",
        "차세대 AI-플랫폼 구축",
        "ai 활용 컨설팅",  # 대소문자 무관
    ],
)
def test_short_ascii_keyword_matches_on_word_boundary(title: str) -> None:
    assert "AI" in classify(make_notice(title)).matched_ai


def test_dx_and_llm_follow_the_same_boundary_rule() -> None:
    assert matched_keywords("DX 추진 전략 수립", ("DX",)) == ["DX"]
    assert matched_keywords("INDXER 모듈 개발", ("DX",)) == []
    assert matched_keywords("LLM 파인튜닝 용역", ("LLM",)) == ["LLM"]
    assert matched_keywords("XLLMX 테스트", ("LLM",)) == []


def test_korean_keywords_are_plain_substring_matches() -> None:
    match = classify(make_notice("인공지능 교육과정 개발 및 컨설팅"))
    assert "인공지능" in match.matched_ai
    assert {"교육", "교육과정", "컨설팅"} <= set(match.matched_work)


# --------------------------------------------------------------------------
# 판정 근거
# --------------------------------------------------------------------------


def test_match_reports_evidence_keywords() -> None:
    match = classify(make_notice("생성형 AI 활용 실무교육 운영"))
    payload: dict[str, Any] = match.to_dict()

    assert payload["tier"] == "high"
    assert payload["method"] == "KEYWORD"
    assert "AI" in payload["matched_ai_keywords"]
    assert "생성형" in payload["matched_ai_keywords"]
    assert "교육" in payload["matched_work_keywords"]


def test_none_tier_reports_empty_evidence() -> None:
    payload = classify(make_notice("도로 포장 보수 공사")).to_dict()
    assert payload["tier"] == "none"
    assert payload["matched_ai_keywords"] == []
    assert payload["matched_work_keywords"] == []


def test_searchable_text_includes_description_and_agency() -> None:
    notice = make_notice("○○사업 용역", description="인공지능 교육 운영", agency="한국AI진흥원")
    text = searchable_text(notice)
    assert "인공지능 교육 운영" in text
    assert "한국AI진흥원" in text
    # 39차 §3-A(P5 · COLLECT-05) — AI 경로의 AI · 업무 · 개발 낱말은 제목에서만 본다. 설명(조달 분류명) · 기관명에만 있으면
    # 후보가 아니고, 그 사유를 남긴다(예전에는 「정보화교육서비스」 · 기관명 「한국AI진흥원」이 근거가 됐다).
    match = classify(notice)
    assert match.tier == "low" and "분류 · 기관명에만" in (match.low_reason or "")


# --------------------------------------------------------------------------
# 필터링·정렬
# --------------------------------------------------------------------------


def test_filter_candidates_drops_low_and_none_by_default() -> None:
    notices = [
        make_notice("AI 활용 실무교육", notice_id="g2b-HIGH-000"),
        make_notice("AI 서버 구축", notice_id="g2b-AIONLY-000"),  # AI만 -> low
        make_notice("급식 위생교육", notice_id="g2b-WORKONLY-000"),  # 업무만 -> low
        make_notice("도로 보수 공사", notice_id="g2b-NONE-000"),
    ]
    ids = [n.id for n, _ in filter_candidates(notices)]
    assert ids == ["g2b-HIGH-000"]


def test_include_low_adds_ai_only_and_work_only_notices() -> None:
    """「낮은 적합도 포함」은 한쪽만 걸린 공고를 되살린다 — 사라지는 게 아니라 내려갈 뿐이다."""
    notices = [
        make_notice("AI 서버 구축", notice_id="g2b-AIONLY-000"),
        make_notice("급식 위생교육", notice_id="g2b-WORKONLY-000"),
        make_notice("도로 보수 공사", notice_id="g2b-NONE-000"),
    ]
    ids = [n.id for n, _ in filter_candidates(notices, include_low=True)]
    assert ids == ["g2b-AIONLY-000", "g2b-WORKONLY-000"]


def test_ordering_is_tier_then_deadline_with_missing_deadline_last() -> None:
    notices = [
        make_notice("AI 서버 구축", notice_id="g2b-LOW-LATE", deadline_days=30),
        make_notice("AI 교육 운영", notice_id="g2b-HIGH-NODATE", deadline_days=None),
        make_notice("AI 서버 유지관리", notice_id="g2b-LOW-SOON", deadline_days=3),
        make_notice("인공지능 컨설팅", notice_id="g2b-HIGH-SOON", deadline_days=5),
    ]
    # 등급이 먼저다 — low 의 마감이 더 급해도 high 보다 위로 올라오지 않는다.
    ids = [n.id for n, _ in filter_candidates(notices, include_low=True)]
    assert ids == [
        "g2b-HIGH-SOON",  # high, 마감 있음
        "g2b-HIGH-NODATE",  # high, 마감 없음 -> 뒤로
        "g2b-LOW-SOON",
        "g2b-LOW-LATE",
    ]


def test_filter_on_real_sample_returns_candidates_with_evidence(
    raw_items: list[dict[str, Any]],
) -> None:
    from app.services import g2b_mapper

    notices = g2b_mapper.map_notices(raw_items)
    candidates = filter_candidates(notices)

    assert candidates, "저장된 실제 응답 샘플에 AI 후보가 최소 1건은 있어야 한다"
    for notice, match in candidates:
        assert match.tier == "high"
        assert match.matched_ai, f"{notice.title}: AI 키워드 근거가 비어 있다"


# ---------------------------------------------------------------------------
# 개발 공고 수집 (개발진 3명 기준)
# ---------------------------------------------------------------------------


def _notice(title: str, budget: int | None = None) -> ProcurementNotice:
    return ProcurementNotice(
        id="test",
        notice_no="test",
        title=title,
        agency="테스트기관",
        published_at=BASE_TIME,
        deadline_at=None,
        budget=budget,
        region=None,
        description=None,
        source_url=None,
        raw_data={},
    )


def test_dev_keywords_make_development_notices_candidates() -> None:
    """개발 공고도 후보가 된다 — 예전에는 교육·컨설팅 키워드만 2차로 인정했다."""
    match = classify(_notice("생성형 AI 챗봇 구축 개발 용역", 80_000_000))
    assert match.tier == "high"
    assert match.is_candidate
    assert match.matched_dev, "개발 키워드 근거가 남아야 한다"


def test_ai_tech_words_count_as_ai_not_dev() -> None:
    """RAG·챗봇·에이전트는 개발 어휘가 아니라 **AI 기술**이다.

    공고명에 「AI」가 없어도 이 말이 있으면 AI 사업으로 봐야 한다.
    (개발 키워드로만 두면 1차 관문을 못 넘어 후보에서 빠진다 — 실제로 그 버그가 있었다.)
    """
    match = classify(_notice("RAG 기반 지식검색 시스템 개발"))
    assert "RAG" in match.matched_ai
    assert match.tier == "high"


def test_oversized_development_stays_candidate() -> None:
    """교육 없이 개발만 하는 큰 사업도 **후보로 둔다** — 순위는 점수가 뒤로 보낸다(34차 R33-S2).

    예전에는 `low` 로 낮춰 기본 목록에서 조용히 빠졌다 — 「숨기지 않고」 결정과 어긋났다.
    """
    big = classify(_notice("차세대 AI 통합플랫폼 개발", 4_500_000_000))
    assert big.tier == "high"
    assert big.is_candidate
    assert big.oversized_reason and "후보로 두고" in big.oversized_reason and "후순위로 내렸" not in big.oversized_reason
    # 회사가 적은 최대 사업비(2억)와 다른 「권장 상한(3.0억원)」으로 읽히지 않게(33차 §3-B-4)
    assert "권장 상한" not in big.oversized_reason
    assert len(filter_candidates([_notice("차세대 AI 통합플랫폼 개발", 4_500_000_000)])) == 1


def test_unknown_budget_is_not_treated_as_oversized() -> None:
    """예산을 모르는 공고를 크다고 단정하지 않는다."""
    match = classify(_notice("AI 에이전트 개발 용역", None))
    assert match.tier == "high"
    assert match.oversized_reason is None


def test_non_ai_construction_stays_out() -> None:
    """개발 키워드를 넓혀도 AI와 무관한 대형 SI·공사는 후보가 되지 않는다."""
    assert classify(_notice("상수도 관제시스템 구축", 900_000_000)).tier == "none"
    assert classify(_notice("도로 포장 공사")).tier == "none"


def test_dev_keyword_alone_does_not_promote_irrelevant_notices() -> None:
    """「개발」 단독으로는 후보가 되지 않는다.

    도시개발·백신개발·기술개발처럼 소프트웨어와 무관한 곳에서도 흔히 쓰이는 낱말이라,
    AI 키워드 없이 이것만으로 올리면 폐기물처리·백신 공고가 딸려 온다(실데이터 600건에서 확인).
    """
    for title in (
        "광명 구름산지구 도시개발사업 부지조성공사 폐판넬 폐기물처리 용역",
        "멧돼지 유래 아프리카돼지열병 바이러스 백신개발 용역",
        "탄소순환형 재생 연료 화학원료화 기술개발사업 기획 연구",
    ):
        match = classify(_notice(title, 1_170_000_000))
        # 38차 — 「기획」이 업무 낱말이 되어 「기술개발사업 기획 연구」는 `low`(사유 있음)일 수 있다. 후보가 아닌 것은 같다.
        assert match.tier in ("none", "low") and not match.is_candidate, f"{title} → {match.tier}"
        assert match.oversized_reason is None, "후보가 아닌 공고에 팀 규모 사유를 붙이지 않는다"
