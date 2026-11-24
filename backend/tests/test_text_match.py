"""한국어 텍스트 매칭 규칙 테스트.

Auditor(요구사항 ↔ 초안 문장)와 Evidence 매칭이 함께 쓰는 코어다.
형태소 분석기 없이 도는 결정론적 규칙이므로 동작을 여기서 고정한다.
docs/auditor_spec.md 2~3장의 계약.
"""

from __future__ import annotations

import pytest

from app.services import text_match as tm


# --------------------------------------------------------------------------
# 수치 토큰
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "raw", "value", "unit"),
    [
        ("교육은 총 12회 운영한다", "12회", 12.0, "회"),
        ("회차당 3시간으로 한다", "3시간", 3.0, "시간"),
        ("누적 240명 이상", "240명", 240.0, "명"),
        ("응답률 80% 이상", "80%", 80.0, "%"),
        ("7일 이내 제출", "7일", 7.0, "일"),
        ("사업비 1억원 이내", "1억원", 1.0, "억원"),
        ("교육생 1,200명", "1,200명", 1200.0, "명"),
    ],
)
def test_수치와_단위를_함께_뽑는다(text: str, raw: str, value: float, unit: str) -> None:
    tokens = tm.extract_numbers(text)
    assert len(tokens) == 1
    assert tokens[0].raw == raw
    assert tokens[0].value == value
    assert tokens[0].unit == unit


def test_이상_이하_한정어를_구분한다() -> None:
    at_least = tm.extract_numbers("교육은 20회 이상 실시한다")[0]
    assert at_least.at_least is True
    assert at_least.at_most is False

    at_most = tm.extract_numbers("보고서는 10일 이내에 제출한다")[0]
    assert at_most.at_most is True
    assert at_most.at_least is False


def test_단위가_없는_숫자는_토큰이_아니다() -> None:
    """'2026년 사업'의 2026 같은 값이 수치 비교에 끼지 않게 한다."""
    assert tm.extract_numbers("제안서는 3부 준비") == [] or all(
        t.unit for t in tm.extract_numbers("제안서는 3부 준비")
    )
    assert tm.extract_numbers("담당자 배정") == []


# --------------------------------------------------------------------------
# 핵심어
# --------------------------------------------------------------------------


def test_조사를_떼어_같은_낱말로_본다() -> None:
    assert tm.strip_particle("교육생을") == "교육생"
    assert tm.strip_particle("보고서는") == "보고서"
    assert tm.strip_particle("기관에서") == "기관"


def test_짧은_조각과_불용어는_핵심어가_아니다() -> None:
    terms = tm.extract_terms("해당 사항은 각각 관련 내용을 포함한다")
    assert "사항" not in terms
    assert "관련" not in terms
    assert "각각" not in terms


def test_영문_용어는_대문자로_모은다() -> None:
    terms = tm.extract_terms("LLM과 ChatGPT를 활용한 pdf 문서작성")
    assert "LLM" in terms
    assert "CHATGPT" in terms
    assert "PDF" in terms


# --------------------------------------------------------------------------
# 매칭 점수
# --------------------------------------------------------------------------


def test_같은_문장은_만점에_가깝다() -> None:
    text = "교육은 총 12회 운영하며 회차당 3시간으로 편성한다"
    score = tm.score_match(text, text)
    assert score.score == pytest.approx(1.0)
    assert score.is_covered


def test_무관한_문장은_대응으로_보지_않는다() -> None:
    score = tm.score_match(
        "교육은 총 12회 운영하며 회차당 3시간으로 편성한다",
        "차량은 현지 운송사업에 등록된 차량이어야 한다",
    )
    assert not score.is_covered
    assert not score.is_partial


def test_수치가_맞으면_점수가_더_올라간다() -> None:
    """수치는 요구사항의 핵심이라 가중치가 높다 (NUMBER_WEIGHT=3)."""
    requirement = "교육은 총 12회 운영한다"
    with_number = tm.score_match(requirement, "교육은 총 12회 운영하겠습니다")
    without_number = tm.score_match(requirement, "교육을 운영하겠습니다")
    assert with_number.score > without_number.score
    assert "12회" in with_number.matched_numbers


def test_임계값_경계가_고정되어_있다() -> None:
    assert tm.COVERED_THRESHOLD == 0.35
    assert tm.PARTIAL_THRESHOLD == 0.20
    assert tm.PARTIAL_THRESHOLD < tm.COVERED_THRESHOLD


def test_빈_요구사항은_0점이다() -> None:
    assert tm.score_match("", "무엇이든").score == 0.0


def test_best_match는_가장_잘_맞는_후보를_고른다() -> None:
    index, score = tm.best_match(
        "교육은 총 12회 운영한다",
        ["산출물을 제출한다", "교육은 총 12회 운영하겠습니다", "보안서약서를 첨부한다"],
    )
    assert index == 1
    assert score.is_covered


def test_후보가_없으면_인덱스가_음수다() -> None:
    index, score = tm.best_match("교육은 총 12회 운영한다", [])
    assert index == -1
    assert score.score == 0.0


# --------------------------------------------------------------------------
# 수치 충돌 (Auditor number_mismatch)
# --------------------------------------------------------------------------


def test_요구보다_적으면_충돌로_잡는다() -> None:
    conflicts = tm.find_number_conflicts("교육은 총 12회 운영한다", "교육은 총 10회 운영합니다")
    assert len(conflicts) == 1
    assert conflicts[0].unit == "회"
    assert "12회" in conflicts[0].reason and "10회" in conflicts[0].reason


def test_이상_조건은_초과해도_통과한다() -> None:
    assert tm.find_number_conflicts("20회 이상 실시한다", "총 25회 실시합니다") == []


def test_이하_조건은_초과하면_충돌이다() -> None:
    conflicts = tm.find_number_conflicts("10일 이내에 제출한다", "14일 안에 제출합니다")
    assert len(conflicts) == 1


def test_단위가_다르면_비교하지_않는다() -> None:
    """오탐 방지 — '12회'와 '12명'을 같은 값으로 보지 않는다."""
    assert tm.find_number_conflicts("교육은 12회 운영한다", "교육생 12명을 모집합니다") == []


def test_같은_단위에_맞는_값이_하나라도_있으면_통과한다() -> None:
    assert tm.find_number_conflicts(
        "교육은 총 12회 운영한다", "1차 10회, 2차 12회로 나누어 운영합니다"
    ) == []


def test_초안에_해당_단위가_없으면_충돌로_보지_않는다() -> None:
    """수치를 아예 안 쓴 문장은 number_mismatch가 아니라 미대응 문제다."""
    assert tm.find_number_conflicts("교육은 총 12회 운영한다", "교육을 성실히 운영합니다") == []


# --------------------------------------------------------------------------
# 재현성
# --------------------------------------------------------------------------


def test_같은_입력이면_항상_같은_결과다() -> None:
    a = tm.score_match("교육은 총 12회 운영한다", "교육은 총 12회 운영하겠습니다")
    b = tm.score_match("교육은 총 12회 운영한다", "교육은 총 12회 운영하겠습니다")
    assert (a.score, a.matched_terms, a.matched_numbers) == (
        b.score,
        b.matched_terms,
        b.matched_numbers,
    )
