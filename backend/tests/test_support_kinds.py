"""기업마당 지원사업 갈래 판정 — 「AI가 들어 있다」와 「우리가 할 수 있다」는 다르다.

이 분류기가 생긴 이유는 실측 결과 하나다.
2026-09-10, org-sample, 기업마당 100건에서 상위 1·2위가 이랬다:

    81점  2026년 3차 디지털혁신기술국제공동연구사업
    81점  2026년 시설농업 AI로봇 실증기반 구축사업

둘 다 회사가 신청해서 직접 수행할 성격이 아닌데, 회사 프로필에서 뽑은 토큰이 25개나 되어
(AI·교육·컨설팅·개발·로봇·제조·대학·비전 …) 아무 공고나 두어 개는 스쳤고
`len(hits)/2` 규칙에서 그것만으로 사업영역 만점이 나왔기 때문이다.

여기서 고정하는 계약:
  - 「AI」 한 낱말로는 어느 갈래도 되지 않는다
  - 사업의 «대상»이 로봇·제조면 요약문에 「SW 등을 개발」이 스쳐도 개발 사업이 아니다
  - 판정 근거를 반드시 함께 돌려준다
  - 모르면 판정 보류다 — 억지로 넣지 않는다

이 점수는 **선정확률이 아니다.**
"""

from __future__ import annotations

import pytest

from app.services import support_kinds as sk


def kind_of(text: str) -> str:
    return sk.detect(text).primary


# ---------------------------------------------------------------------------
# 우리가 주체가 될 수 있는 갈래
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "생성형 AI 활용 실무교육 운영 지원사업",
        "중소기업 재직자 인공지능 역량강화 교육과정 지원",
        "디지털 인력양성 사업 참여기업 모집",
    ],
)
def test_AI_교육_사업을_찾는다(text: str):
    assert kind_of(text) == "ai_education"
    assert sk.detect(text).is_ours is True


@pytest.mark.parametrize(
    "text",
    [
        "제조업 AI융합 기반 조성 사업 AX클리닉 — AI 도입 사전 진단 지원",
        "중소기업 디지털 전환 지원 컨설팅 사업",
        "인공지능 업무 자동화 자문 지원",
    ],
)
def test_AI_컨설팅_사업을_찾는다(text: str):
    assert kind_of(text) == "ai_consulting"


def test_대학_협력_사업은_함께_하는_사업일_때만이다():
    """「대학」은 신청 자격에 흔히 적힌다. 스치기만 해도 걸리면 안 된다."""
    assert kind_of("산학협력 기반 AI 교육과정 공동개발 지원") in {"ai_education", "academic_public"}
    assert sk.detect("대학·공공기관 연계 위탁교육 지원사업").is_ours is True
    # 단순 자격 언급
    assert "academic_public" not in sk.detect("신청자격: 중소기업, 대학, 연구소").kinds


# ---------------------------------------------------------------------------
# 회사가 주체가 되기 어려운 갈래
# ---------------------------------------------------------------------------


def test_로봇_실증사업은_AI가_들어_있어도_우리_갈래가_아니다():
    result = sk.detect("2026년 시설농업 AI로봇 실증기반 구축사업 기술지원 수혜기업 모집")
    assert result.is_ours is False
    assert "low_relevance" in result.kinds


def test_요약문에_SW_개발이_스쳐도_로봇사업은_로봇사업이다():
    """실제로 이 한 구절 때문에 로봇 실증 사업이 소프트웨어 개발로 분류돼 2위에 올랐다."""
    text = "시설농업 AI로봇 실증기반 구축 — 수혜기업이 필요한 SW 등을 개발할 수 있도록 기술지도"
    result = sk.detect(text)
    assert result.primary == "physical_ai"
    assert result.is_ours is False


def test_국제공동연구는_우리_갈래가_아니다():
    result = sk.detect("2026년 3차 디지털혁신기술국제공동연구사업 신규지원 대상과제 공고")
    assert result.is_ours is False


def test_의료_진단은_업무_진단이_아니다():
    """「AI 헬스케어 빅데이터 모바일진단」이 컨설팅으로 분류돼 1위에 올랐던 적이 있다."""
    result = sk.detect("HLTH USA 디지털헬스케어 한국관 참가기관 모집 — AI 헬스케어 빅데이터 모바일진단")
    assert result.is_ours is False


def test_수출_준비_사전진단도_우리_일이_아니다():
    """무엇에 대한 진단인지가 중요하다 — AI·디지털이 함께 있어야 한다."""
    result = sk.detect("글로벌 진출 태국 온라인 수출상담회 참가기업 모집 — 사전진단 후 매칭")
    assert result.is_ours is False


@pytest.mark.parametrize(
    "text,expected",
    [
        ("스마트공장 구축 지원사업", "manufacturing"),
        ("수출 바이어 매칭 및 해외 전시회 참가 지원", "commercialization"),
        ("기술개발 R&D 과제 공고", "rnd"),
    ],
)
def test_대상_갈래를_구분한다(text: str, expected: str):
    assert kind_of(text) == expected
    assert sk.detect(text).is_ours is False


# ---------------------------------------------------------------------------
# 모르면 모른다고 한다
# ---------------------------------------------------------------------------


def test_근거가_없으면_판정_보류다():
    result = sk.detect("2026년 상반기 지원사업 안내")
    assert result.primary == "unclassified"
    assert result.is_ours is False
    assert "원문을 확인" in result.basis


def test_판정_근거를_항상_돌려준다():
    """점수만 바뀌고 이유를 모르면 담당자가 신뢰할 수 없다."""
    for text in [
        "생성형 AI 실무교육 운영",
        "스마트공장 구축 지원",
        "아무 단서 없는 공고",
    ]:
        assert sk.detect(text).basis.strip()


def test_AI_한_낱말로는_어느_갈래도_되지_않는다():
    """두 번째 낱말(무엇을 지원해 주는가)이 있어야 갈래가 된다."""
    result = sk.detect("AI 관련 지원사업")
    assert result.primary == "unclassified"


# ---------------------------------------------------------------------------
# 점수에 반영되는 방식
# ---------------------------------------------------------------------------


def test_우리_갈래가_아니면_사업영역_점수에_상한이_걸린다():
    from app.services import opportunity_priority as priority

    assert 0 < priority.NON_MATCHING_KIND_CAP < 1.0, "0으로 만들지 않는다 — 담당자 판단 여지를 남긴다"


# ---------------------------------------------------------------------------
# 기관명과 요약문 — 실측에서 오탐 4건 중 3건이 여기서 나왔다
# ---------------------------------------------------------------------------


def program(**kwargs) -> "SupportProgram":
    from app.schemas.business_opportunity import SupportProgram

    base = {"id": "biz-test", "title": "", "agency": "테스트기관"}
    return SupportProgram(**{**base, **kwargs})


def test_기관_이름이_사업_성격으로_읽히지_않는다():
    """「전북대학교산학협력단」이 발주처로 적혔다고 산학협력 사업이 되지는 않는다."""
    result = sk.of_program(
        program(
            title="2026년 지식재산 창출 지원사업",
            summary="전북대학교산학협력단에서 특허 출원 비용을 지원합니다.",
        )
    )
    assert result.is_ours is False, result.basis


def test_공사_이름이_사업화_수출로_읽히지_않는다():
    """「한국관광공사」의 「한국관」이 걸리던 실측 오탐."""
    result = sk.of_program(
        program(title="관광 콘텐츠 공모전", summary="한국관광공사가 주관합니다.")
    )
    assert result.primary != "commercialization", result.basis


def test_요약문에만_걸린_갈래는_우리_일로_치지_않는다():
    """방화벽 도입 사업의 품목 목록에 「디지털 역량강화」가 섞여 AI 교육이 됐던 실측 오탐."""
    result = sk.of_program(
        program(
            title="2026년 수리조선산업 맞춤형 지원사업",
            category="경영",
            summary="정보보호 솔루션(방화벽·백신), 디지털 역량강화 교육 등을 지원합니다.",
        )
    )
    assert result.declared is False
    assert result.is_ours is False
    assert "기업마당 요약에만" in result.basis


def test_제목이_밝힌_목적이면_그대로_우리_일이다():
    """강등 규칙이 정탐까지 깎으면 안 된다 — 부산 AX클리닉은 이름 자체가 컨설팅 창구다."""
    result = sk.of_program(
        program(title="[부산] 제조업 AI융합 기반 조성 사업 부산 AX클리닉 지원기업 모집 공고")
    )
    assert result.primary == "ai_consulting"
    assert result.declared is True
    assert result.is_ours is True
