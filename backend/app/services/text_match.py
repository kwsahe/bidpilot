"""한국어 텍스트 매칭 (형태소 분석기 없이 동작하는 결정론적 규칙).

Auditor(요구사항 ↔ 제안서 문장)와 Evidence 매칭이 함께 쓴다.
docs/auditor_spec.md 2장의 알고리즘을 구현한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 조사·어미 — 핵심어에서 떼어낸다.
_PARTICLES = (
    "으로서", "으로써", "에서는", "에게는", "이라는", "라고", "으로", "에서", "에게",
    "부터", "까지", "보다", "처럼", "만큼", "이나", "이며", "하며", "하고", "이고",
    "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "만",
)

# 수치 토큰: 값 + 단위 (12회, 3시간, 240명, 80%, 7일, 2명, 1억원)
_NUMBER_UNIT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*"
    r"(%|퍼센트|회차|회|시간|분|일|개월|년|명|건|개|점|억원|만원|원|억|만|페이지|쪽|배)"
)

# 한글 2글자 이상 덩어리
_HANGUL_RE = re.compile(r"[가-힣]{2,}")
# 영문/숫자 혼합 용어 (AI, LLM, PDF, XLSX, ChatGPT)
_ASCII_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,}")

# 한정어
_AT_LEAST = re.compile(r"이상|최소|넘게|초과")
_AT_MOST = re.compile(r"이하|최대|미만|이내")

# 수치 토큰 가중치 (숫자가 요구사항의 핵심이다)
NUMBER_WEIGHT = 3.0
TERM_WEIGHT = 1.0

# 판정 임계값 (테스트로 고정한다)
COVERED_THRESHOLD = 0.35
PARTIAL_THRESHOLD = 0.20

# 의미 없는 흔한 낱말 — 매칭 신호가 되지 못한다.
_STOPWORDS = {
    "경우", "관련", "대한", "대하여", "위하여", "위한", "통해", "통하여", "따라",
    "각각", "모든", "해당", "기타", "등의", "이와", "또는", "그리고", "하여야",
    "해야", "한다", "하며", "하고", "있는", "있음", "없음", "한다는", "사항",
    "내용", "경우에는", "제안", "사업", "본", "및",
}


def strip_particle(word: str) -> str:
    for particle in _PARTICLES:
        if len(word) > len(particle) + 1 and word.endswith(particle):
            return word[: -len(particle)]
    return word


@dataclass(frozen=True)
class NumberToken:
    value: float
    unit: str
    raw: str
    at_least: bool = False
    at_most: bool = False

    def key(self) -> str:
        return self.unit


def extract_numbers(text: str) -> list[NumberToken]:
    """수치 토큰과 한정어(이상/이하)를 함께 뽑는다."""
    tokens: list[NumberToken] = []
    for match in _NUMBER_UNIT_RE.finditer(text):
        raw_value, unit = match.group(1), match.group(2)
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            continue
        # 한정어는 수치 뒤 6글자 안에서 찾는다 ("20회 이상")
        tail = text[match.end() : match.end() + 6]
        tokens.append(
            NumberToken(
                value=value,
                unit=unit,
                raw=match.group(0).strip(),
                at_least=bool(_AT_LEAST.search(tail)),
                at_most=bool(_AT_MOST.search(tail)),
            )
        )
    return tokens


def extract_terms(text: str) -> set[str]:
    """핵심어 집합 (조사 제거, 불용어 제외)."""
    terms: set[str] = set()
    for word in _HANGUL_RE.findall(text):
        stem = strip_particle(word)
        if len(stem) >= 2 and stem not in _STOPWORDS:
            terms.add(stem)
    for word in _ASCII_TERM_RE.findall(text):
        terms.add(word.upper())
    return terms


@dataclass(frozen=True)
class MatchScore:
    score: float
    matched_terms: list[str]
    matched_numbers: list[str]

    @property
    def is_covered(self) -> bool:
        return self.score >= COVERED_THRESHOLD

    @property
    def is_partial(self) -> bool:
        return PARTIAL_THRESHOLD <= self.score < COVERED_THRESHOLD


def score_match(requirement_text: str, candidate_text: str) -> MatchScore:
    """요구사항 대비 후보 문장의 가중 커버리지 (0~1)."""
    req_terms = extract_terms(requirement_text)
    req_numbers = extract_numbers(requirement_text)
    if not req_terms and not req_numbers:
        return MatchScore(0.0, [], [])

    cand_terms = extract_terms(candidate_text)
    cand_number_raws = {t.raw.replace(" ", "") for t in extract_numbers(candidate_text)}

    matched_terms = sorted(req_terms & cand_terms)
    matched_numbers = [
        t.raw for t in req_numbers if t.raw.replace(" ", "") in cand_number_raws
    ]

    total = len(req_terms) * TERM_WEIGHT + len(req_numbers) * NUMBER_WEIGHT
    got = len(matched_terms) * TERM_WEIGHT + len(matched_numbers) * NUMBER_WEIGHT
    return MatchScore(
        score=got / total if total else 0.0,
        matched_terms=matched_terms,
        matched_numbers=matched_numbers,
    )


def best_match(requirement_text: str, candidates: list[str]) -> tuple[int, MatchScore]:
    """가장 잘 맞는 후보의 (인덱스, 점수). 후보가 없으면 (-1, 0점)."""
    best_index, best = -1, MatchScore(0.0, [], [])
    for index, candidate in enumerate(candidates):
        current = score_match(requirement_text, candidate)
        if current.score > best.score:
            best_index, best = index, current
    return best_index, best


@dataclass(frozen=True)
class NumberConflict:
    unit: str
    required: NumberToken
    found: NumberToken
    reason: str


def find_number_conflicts(requirement_text: str, candidate_text: str) -> list[NumberConflict]:
    """같은 단위끼리 비교해 수치 위반을 찾는다 (docs/auditor_spec.md 3.1)."""
    conflicts: list[NumberConflict] = []
    found_by_unit: dict[str, list[NumberToken]] = {}
    for token in extract_numbers(candidate_text):
        found_by_unit.setdefault(token.unit, []).append(token)

    for required in extract_numbers(requirement_text):
        found_list = found_by_unit.get(required.unit)
        if not found_list:
            continue  # 단위가 다르면 비교하지 않는다 (오탐 방지)
        # 요구를 만족하는 값이 하나라도 있으면 통과로 본다.
        if any(_satisfies(required, found) for found in found_list):
            continue
        closest = min(found_list, key=lambda f: abs(f.value - required.value))
        conflicts.append(
            NumberConflict(
                unit=required.unit,
                required=required,
                found=closest,
                reason=_conflict_reason(required, closest),
            )
        )
    return conflicts


def _satisfies(required: NumberToken, found: NumberToken) -> bool:
    if required.at_least:
        return found.value >= required.value
    if required.at_most:
        return found.value <= required.value
    return found.value == required.value


def _conflict_reason(required: NumberToken, found: NumberToken) -> str:
    if required.at_least:
        return f"제안요청서는 {required.raw} 이상인데 초안은 {found.raw}입니다."
    if required.at_most:
        return f"제안요청서는 {required.raw} 이하인데 초안은 {found.raw}입니다."
    return f"제안요청서 원문은 {required.raw}인데 초안은 {found.raw}입니다."
