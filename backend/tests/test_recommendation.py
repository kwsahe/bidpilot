"""공고 추천등급 산정 테스트.

네트워크·LLM을 쓰지 않는다. 시각은 항상 주입해 같은 입력이면 같은 결과가 나오게 한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import recommendation
from app.services.opportunity_filter import CandidateMatch
from app.services.recommendation import WEIGHTS

NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


def make_notice(
    *,
    deadline_days: float | None = 30,
    budget: int | None = 100_000_000,
    region: str | None = None,
) -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-TEST0001-000",
        notice_no="TEST0001-000",
        title="생성형 AI 활용 실무교육 운영 용역",
        agency="테스트기관",
        published_at=NOW - timedelta(days=1),
        deadline_at=None if deadline_days is None else NOW + timedelta(days=deadline_days),
        budget=budget,
        region=region,
    )


def make_match(tier: str = "high") -> CandidateMatch:
    return CandidateMatch(
        tier=tier,  # type: ignore[arg-type]
        matched_ai=["AI", "생성형"] if tier in ("high", "medium") else [],
        matched_work=["교육"] if tier in ("high", "low") else [],
    )


#: 「회사가 적어 둔」 단독 수행 상한. 예전에는 합성 상수가 코드에 박혀 있었다(ISSUE-030).
#: 이제는 회사 자료에서 오므로, 테스트도 값을 «넘겨서» 잰다.
TEST_CAPACITY = 300_000_000
TEST_REGIONS = ("광주", "전남", "전라남도")


def evaluate(**kwargs):
    match = kwargs.pop("match", make_match())
    capacity = kwargs.pop("capacity_krw", TEST_CAPACITY)
    regions = kwargs.pop("preferred_regions", TEST_REGIONS)
    return recommendation.evaluate(
        make_notice(**kwargs), match, now=NOW, preferred_regions=regions, capacity_krw=capacity
    )


# --------------------------------------------------------------------------
# 등급
# --------------------------------------------------------------------------


def test_사업영역_일정_예산_지역이_모두_좋으면_A등급() -> None:
    result = evaluate(deadline_days=30, budget=100_000_000, region="광주광역시")
    assert result.grade == "A"
    assert result.score >= recommendation.GRADE_A


def test_키워드가_약하면_등급이_내려간다() -> None:
    strong = evaluate(match=make_match("high"))
    weak = evaluate(match=make_match("low"))
    assert weak.score < strong.score
    assert weak.grade != "A"


def test_마감이_지나면_점수와_무관하게_NO_GO다() -> None:
    result = evaluate(deadline_days=-5, budget=100_000_000, region="광주광역시")
    assert result.grade == "NO_GO"
    assert result.gate_reason is not None
    assert "마감" in result.gate_reason


def test_등급_경계값을_지킨다() -> None:
    assert recommendation.grade_of(recommendation.GRADE_A) == "A"
    assert recommendation.grade_of(recommendation.GRADE_A - 0.01) == "B"
    assert recommendation.grade_of(recommendation.GRADE_B) == "B"
    assert recommendation.grade_of(recommendation.GRADE_C - 0.01) == "D"


# --------------------------------------------------------------------------
# 미계산 항목 처리
# --------------------------------------------------------------------------


def test_수행근거_유사도는_목록_단계에서_계산하지_않는다() -> None:
    result = evaluate()
    evidence = next(c for c in result.components if c.key == "evidence_fit")
    assert evidence.computed is False
    assert "수행근거 유사도" in result.skipped


def test_미계산_항목은_점수를_끌어내리지_않는다() -> None:
    """계산한 항목만으로 정규화하므로 만점 조건이면 1.0이 나와야 한다."""
    result = evaluate(deadline_days=30, budget=100_000_000, region="전라남도")
    assert result.score == pytest.approx(1.0)


def test_예산이_없으면_예산항목을_계산하지_않는다() -> None:
    result = evaluate(budget=None)
    budget = next(c for c in result.components if c.key == "budget_fit")
    assert budget.computed is False
    assert "예산 적합도" in result.skipped


def test_마감일이_없으면_일정항목을_계산하지_않는다() -> None:
    result = evaluate(deadline_days=None)
    schedule = next(c for c in result.components if c.key == "schedule_fit")
    assert schedule.computed is False
    assert result.grade != "NO_GO"  # 마감이 없는 것과 지난 것은 다르다


# --------------------------------------------------------------------------
# 항목별 규칙
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("광주광역시", 1.0),
        ("전라남도", 1.0),
        ("전국", 0.7),
        (None, 0.7),  # 지역제한 표기 없음
        ("서울특별시", 0.25),
    ],
)
def test_지역_적합도(region: str | None, expected: float) -> None:
    result = evaluate(region=region)
    strategic = next(c for c in result.components if c.key == "strategic_fit")
    assert strategic.score == expected


def test_단독수행_범위를_넘는_예산은_감점된다() -> None:
    capacity = TEST_CAPACITY
    inside = evaluate(budget=capacity)
    outside = evaluate(budget=capacity * 3)
    assert inside.score > outside.score
    reason = next(c for c in outside.components if c.key == "budget_fit").reason
    assert "최대 사업비" in reason


def test_마감이_촉박할수록_일정점수가_낮다() -> None:
    scores = [
        next(
            c.score
            for c in evaluate(deadline_days=d).components
            if c.key == "schedule_fit"
        )
        for d in (30, 15, 10, 5, 1)
    ]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------
# 근거 보존 / 재현성
# --------------------------------------------------------------------------


def test_모든_항목에_근거_문장이_있다() -> None:
    result = evaluate()
    assert all(c.reason.strip() for c in result.components)


def test_가중치는_CLAUDE_md_12조를_따른다() -> None:
    assert WEIGHTS["business_fit"] == 0.35
    assert WEIGHTS["evidence_fit"] == 0.25
    assert WEIGHTS["schedule_fit"] == 0.20
    assert WEIGHTS["budget_fit"] == 0.10
    assert WEIGHTS["strategic_fit"] == 0.10
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_같은_입력이면_같은_등급이_나온다() -> None:
    first = evaluate()
    second = evaluate()
    assert first.to_dict() == second.to_dict()


def test_직렬화에_낙찰확률이_아니라는_표기가_남는다() -> None:
    payload = evaluate().to_dict()
    assert payload["method"] == "RULE"
    assert "낙찰확률" in payload["note"]


# --------------------------------------------------------------------------
# 사업 유형 판정 — 키워드만으로 올라오는 비대상 공고 걸러내기
# --------------------------------------------------------------------------


def notice_titled(title: str, **kwargs) -> ProcurementNotice:
    payload = {
        "id": "g2b-TEST0001-000",
        "notice_no": "TEST0001-000",
        "title": title,
        "agency": "테스트기관",
        "published_at": NOW - timedelta(days=1),
        "deadline_at": NOW + timedelta(days=20),
        "budget": 100_000_000,
        "region": "광주광역시",
    }
    payload.update(kwargs)
    return ProcurementNotice(**payload)


KEEP_TITLES = [
    "「AX활용역량 붐업 교육」 및 「사이버연수원 AI·디지털 분야(e러닝)」 위탁용역",
    "가천대학교 AI부트캠프 사업 생성형 AI 활용 교육 기획·운영 위탁 용역",
    "Agentic AI 교육 프로그램 기획 및 운영 지원 용역",
    "생성형 AI 활용교육 운영",
    "네이버클라우드 아카데미 교육과정 운영 용역(소버린 AI Literacy)",
]

# 샘플에듀가 «수행자»가 될 수 없는 유형. 전부 실제 나라장터 공고명이다.
#
# 2026-09-10 개정: 「TOD AI 학습용 데이터셋 구축 및 실증모델 개발」을 뺐다.
# 데이터셋 구축·모델 개발은 회사 프로필의 「AI SaaS·소프트웨어 개발」 영역 안이며,
# 감당하기 어려운 것은 **분야가 아니라 규모**다. 규모는 수행역량 판정이 회사가 정한
# 상한과 대조해 따로 본다(capability_service.CAP-SCALE).
EXCLUDE_TITLES = [
    "생성형 AI 법령검색 구축 감리용역",
    "AI·빅데이터 분석 기반 보훈심사 지원 시스템 구축 위탁감리",
    "AI데이터센터(AIDC) 국가전략산업 종합 체계 구축",
    "AI 기술 적용 지하시설물 성과심사 자동화",
    # 실측에서 A 0.853 으로 잘못 올라오던 정책연구 (스냅샷 34건, 2026-09-10)
    "미래 AI반도체 기술개발 로드맵 수립 연구",
]

# 비대상 유형이지만 «교육»이 주제로 언급돼 gate 까지는 가지 않고 **감점만** 되는 공고.
# 「생성형AI 교육을 위한 구독권 제공」은 교육용 물품을 사 주는 사업이지 교육을 수행하는 사업이
# 아니다. 실측에서 A 0.787 로 최우선에 올라와 있었다.
PENALIZED_TITLES = [
    "2026년 생성형AI 교육을 위한 구독권(Google AI Pro, Google Ads) 및 기념품 제공",
]

# 개발 사업이라 **비대상이 아니어야** 하는 공고. 전부 실제 나라장터 공고명이며,
# 예전 규칙(「시스템 구축」·「모델 개발」)에서는 D등급 out_of_scope 로 밀려 있었다.
DEVELOPMENT_TITLES = [
    "AI 활용 빌라시세 자동추정모델 개발 사업",
    "AI 감사혁신 플랫폼 구축 용역",
    "2026년 소상공인 생성형 AI 서비스 공급 용역",
]


@pytest.mark.parametrize("title", KEEP_TITLES)
def test_교육_사업은_비대상으로_보지_않는다(title: str) -> None:
    assert recommendation.out_of_scope_reason(title) is None


@pytest.mark.parametrize("title", EXCLUDE_TITLES)
def test_감리_데이터센터_데이터셋은_비대상이다(title: str) -> None:
    result = recommendation.out_of_scope_reason(title)
    assert result is not None, f"비대상으로 걸러지지 않았다: {title}"
    label, education_topic = result
    assert label
    assert education_topic is False, "교육 문구가 없어야 gate 대상이다"


@pytest.mark.parametrize("title", EXCLUDE_TITLES)
def test_비대상_공고는_A_B등급에_오르지_않는다(title: str) -> None:
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    assert result.grade not in ("A", "B"), f"{title} → {result.grade}"
    assert result.gate_reason is not None
    assert "사업영역" in result.gate_reason


@pytest.mark.parametrize("title", KEEP_TITLES)
def test_교육_공고는_등급이_떨어지지_않는다(title: str) -> None:
    """회귀 방지 — 비대상 필터가 교육 사업을 끌어내리면 안 된다."""
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    assert result.grade == "A"
    assert result.gate_reason is None


def test_교육을_직접_수행하면_구축_사업이어도_남긴다() -> None:
    """'교육 플랫폼 구축'처럼 검토 가치가 있는 사업을 단어 하나로 배제하지 않는다."""
    title = "AI 교육 플랫폼 구축 및 교육과정 운영 용역"
    assert recommendation.out_of_scope_reason(title) is None
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    assert result.grade == "A"


def test_교육이_주제로만_언급되면_제외하지_않고_감점한다() -> None:
    title = "교육분야 특화 수직 AI 모형 개발 및 현장 적용 방안 연구"
    scope = recommendation.out_of_scope_reason(title)
    assert scope is not None and scope[1] is True, "교육이 주제로 언급됨"

    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    assert result.gate_reason is None, "제외가 아니라 감점이어야 한다"
    fit = next(c for c in result.components if c.key == "business_fit")
    assert fit.score == recommendation.OUT_OF_SCOPE_TOPIC_SCORE
    assert "감점" in fit.reason
    assert result.grade not in ("A", "B")


def test_감점_사유가_사람이_읽을_수_있게_남는다() -> None:
    result = recommendation.evaluate(
        notice_titled("미래 AI반도체 기술개발 로드맵 수립 연구"), make_match("high"), now=NOW
    )
    fit = next(c for c in result.components if c.key == "business_fit")
    assert "연구·조사" in fit.reason
    assert "교육을 직접 수행하는 문구가 없습니다" in fit.reason


@pytest.mark.parametrize("title", PENALIZED_TITLES)
def test_교육이_주제로만_언급된_구매사업은_감점된다(title: str) -> None:
    """교육용 물품을 사 주는 사업은 교육 수행 사업이 아니다. 다만 «교육»이 있으니 gate 는 아니다."""
    scope = recommendation.out_of_scope_reason(title)
    assert scope is not None
    label, education_topic = scope
    assert education_topic is True, "교육이 주제로 언급되면 gate 가 아니라 감점이다"
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    fit = next(c for c in result.components if c.key == "business_fit")
    assert fit.score == recommendation.OUT_OF_SCOPE_TOPIC_SCORE
    assert result.grade not in ("A", "B")


@pytest.mark.parametrize("title", DEVELOPMENT_TITLES)
def test_소프트웨어_개발_사업은_비대상이_아니다(title: str) -> None:
    """회사 프로필에 「AI SaaS·소프트웨어 개발」이 있다. 개발 사업을 사업영역 밖으로 단정하지 않는다."""
    assert recommendation.out_of_scope_reason(title) is None
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    assert result.out_of_scope is False
    fit = next(c for c in result.components if c.key == "business_fit")
    assert fit.score is not None and fit.score > recommendation.OUT_OF_SCOPE_TOPIC_SCORE


def test_마감_경과가_비대상_판정보다_우선한다() -> None:
    """두 사유가 겹치면 마감 경과(No-Go)를 먼저 알린다."""
    result = recommendation.evaluate(
        notice_titled("AI 데이터센터 구축", deadline_at=NOW - timedelta(days=3)),
        make_match("high"),
        now=NOW,
    )
    assert result.grade == "NO_GO"
    assert "마감" in (result.gate_reason or "")


def test_비대상_판정에_의미유사도를_쓰지_않는다() -> None:
    """이것은 문구 규칙이지 Semantic Matching이 아니다 — 수행근거는 여전히 미계산."""
    result = recommendation.evaluate(
        notice_titled("AI 시스템 구축 감리용역"), make_match("high"), now=NOW
    )
    evidence = next(c for c in result.components if c.key == "evidence_fit")
    assert evidence.computed is False
    assert "수행근거 유사도" in result.skipped


@pytest.mark.parametrize("title", EXCLUDE_TITLES)
def test_교육_문구가_없는_비대상은_사업영역_점수도_감점된다(title: str) -> None:
    """교육 언급이 아예 없는 쪽이 더 나쁜데 감점에서 빠져 있었다.

    등급만 D로 내리고 점수를 그대로 두면, 목록이 점수순이라 감리 공고가
    정상 교육 공고보다 위에 남는다.
    """
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    fit = next(c for c in result.components if c.key == "business_fit")
    assert fit.score == recommendation.OUT_OF_SCOPE_TOPIC_SCORE, f"{title} 감점 안 됨"
    assert "감점" in fit.reason


@pytest.mark.parametrize("title", EXCLUDE_TITLES)
def test_비대상_공고는_out_of_scope로_표시된다(title: str) -> None:
    result = recommendation.evaluate(notice_titled(title), make_match("high"), now=NOW)
    assert result.out_of_scope is True
    assert result.to_dict()["out_of_scope"] is True


def test_정상_공고는_out_of_scope가_아니다() -> None:
    result = recommendation.evaluate(
        notice_titled(KEEP_TITLES[0]), make_match("high"), now=NOW
    )
    assert result.out_of_scope is False


def test_비대상_공고_점수가_교육_공고보다_낮다() -> None:
    """gate_reason이 '후순위로 내렸습니다'라고 적는 만큼 점수도 실제로 낮아야 한다."""
    education = recommendation.evaluate(
        notice_titled(KEEP_TITLES[1]), make_match("high"), now=NOW
    )
    audit = recommendation.evaluate(
        notice_titled(EXCLUDE_TITLES[1]), make_match("high"), now=NOW
    )
    assert audit.score < education.score


# ---------------------------------------------------------------------------
# 지역 오독 — 「본사또는참여지사소재지」는 지역 이름이 아니다
# ---------------------------------------------------------------------------


def test_지역제한_판단기준_이름을_지역으로_읽고_깎지_않는다():
    """실측: 캐시 76건의 `rgnLmtBidLocplcJdgmBssNm` 은 52건이 「본사또는참여지사소재지」,
    1건이 「본사소재지」, 23건이 빈 값이다 — 지역 이름은 0건.

    그것을 지역으로 읽으면 「본사또는참여지사소재지 — 우선 지역이 아닙니다」가 되어
    53건이 근거 없이 0.25 로 깎였다. 어느 지역인지 «모르는 것»이지 «우리 지역이 아닌 것»이 아니다.
    """
    for basis in ("본사또는참여지사소재지", "본사소재지"):
        component = recommendation._strategic_fit(basis)
        assert component.score == pytest.approx(0.7), f"{basis} 를 지역으로 읽고 깎았다"
        assert "판단 기준" in component.reason
        assert "우선 지역이 아닙니다" not in component.reason


def test_지역_이름이_실제로_적혀_있으면_그대로_판정한다():
    """오독을 막느라 진짜 지역 판정까지 무디게 만들면 안 된다."""
    assert recommendation._strategic_fit("광주광역시").score == pytest.approx(1.0)
    assert recommendation._strategic_fit("부산광역시").score == pytest.approx(0.25)
    # 「전국」은 지역 이름 목록에는 없지만 «제한 없음»이라는 뜻이라 예전 판정을 지킨다.
    nationwide = recommendation._strategic_fit("전국")
    assert nationwide.score == pytest.approx(0.7)
    assert "지역제한이 없습니다" in nationwide.reason


def test_회사가_규모를_적지_않으면_예산은_판정하지_않는다() -> None:
    """합성 상수 300,000,000원을 회사의 판단인 것처럼 말하던 자리 (ISSUE-030).

    0 점이 아니라 «판정 안 함»이다 — CLAUDE.md §12.
    """
    budget_fit = next(
        c for c in evaluate(budget=500_000_000, capacity_krw=None).components if c.key == "budget_fit"
    )
    assert budget_fit.score is None
    assert "아직 적지 않아" in budget_fit.reason


def test_회사가_활동_지역을_적지_않으면_지역은_판정하지_않는다() -> None:
    strategic = next(
        c for c in evaluate(region="부산광역시", preferred_regions=()).components if c.key == "strategic_fit"
    )
    assert strategic.score is None
    assert "활동 지역이 없어" in strategic.reason
