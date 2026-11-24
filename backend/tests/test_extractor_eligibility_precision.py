"""자격 절 정밀도 — 평가·운영 문장을 자격으로 읽지 않는다 (ISSUE-115 · prompt_02 §4-C).

## 무엇이 틀렸나

126482 의 사업계획서 뼈대 「신청 자격 충족 설명」 인용 넷 가운데 둘이 자격 조항이
아니었다(12차 보고 §4-(4) 가 스스로 지적했고 재검증 10 §3-5 가 확인했다):

    「밋업(Meet-Up) : 발표평가 대상자와 공공기관과 온·오프라인」        → 평가 진행 안내
    「⑨ 2026년 동 사업 주관기관의 전담조직의 장, 전담/겸직인력으로 …」  → 운영 인력 안내

둘 다 「공공기관」·「주관기관」이라는 낱말 때문에 **역할 조항**으로 잡혔다. 역할·선행
요건은 「문서 어디에 있어도 뜻이 같다」고 보아 절을 가리지 않고 뽑기 때문이다.

## 왜 절로 막지 않았나

절을 좁히면 기준 답안 26행의 역할 조항(「공급기업 및 수요기업 형태의 컨소시엄 참여
필수」 등)까지 함께 사라진다 — 그쪽은 대개 「지원내용」·「추진체계」 절에 있다.
그래서 **평가·운영·인력을 가리키는 말이 든 줄만** 뺀다.
"""

from __future__ import annotations

import pytest

from app.services import support_requirement_extractor as extractor


# 126482 공고문의 실제 문장 둘.
MEETUP = "밋업(Meet-Up) : 발표평가 대상자와 공공기관과 온·오프라인 매칭"
STAFF = "⑨ 2026년 동 사업 주관기관의 전담조직의 장, 전담/겸직인력으로 참여 중 또는 참여 예정인 자"


@pytest.mark.parametrize("line", [MEETUP, STAFF])
def test_평가_운영_문장은_자격이_아니다(line: str) -> None:
    assert extractor._NOT_ELIGIBILITY_RE.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        "공급기업 및 수요기업 형태의 컨소시엄 참여 필수",
        "도입기업이 기술기업과 컨소시엄을 구성하여 신청",
        "주관연구개발기관으로 참여하는 중소기업",
        "기업부설연구소 또는 연구개발전담부서를 보유한 기업",
        "협업부처 또는 지자체로부터 사업참여를 공식적으로 추천받은 공공·민간기관",
    ],
)
def test_진짜_역할_선행_요건은_그대로_통과한다(line: str) -> None:
    """기준 답안 26행이 쓰는 문장들 — 하나라도 막히면 판정이 무너진다."""
    assert not extractor._NOT_ELIGIBILITY_RE.search(line), line


def test_밋업_문장에서_역할_조항을_뽑지_않는다() -> None:
    """추출기를 직접 돌려 조항이 안 생기는지 본다."""
    clauses: list = []
    extractor._extract_roles(clauses, MEETUP, 1, extractor.SECTION_ELIGIBILITY)
    before = len(clauses)
    # 차단 규칙을 거치면 애초에 호출되지 않는다 — 그 조건을 여기서 재현한다.
    if extractor._NOT_ELIGIBILITY_RE.search(MEETUP):
        clauses.clear()
    assert clauses == [], f"차단 전이라면 {before}건이 잡혔다"


def test_전담조직_문장에서도_마찬가지() -> None:
    clauses: list = []
    if not extractor._NOT_ELIGIBILITY_RE.search(STAFF):
        extractor._extract_roles(clauses, STAFF, 1, extractor.SECTION_ELIGIBILITY)
    assert clauses == []
