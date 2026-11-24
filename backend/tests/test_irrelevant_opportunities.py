"""무관 공고가 목록 상단을 차지하지 않는다 (ISSUE-005 · ISSUE-030 · ISSUE-041 · TASK-008).

## 2026-09-16 실데이터에서 무엇이 보였나

통합 목록 **1위**(76점 · 「우선 검토」):
「2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 **교육생 모집** 공고」.
본문은 「만 19세 이상 공예작가·유통사업자를 모집」 — 개인이 수강 신청하는 안내문이고
샘플에듀가 신청할 수 있는 사업이 아니다. 「AI」·「교육」·「역량 강화」가 다 들어 있어
사업영역 1.0 을 받았다.

같은 화면에 「반려동물 창업 아이디어 **경진대회 참가자 모집**」 55점,
「전주국제발효식품엑스포 **참가기업**」 54점.
나라장터 A등급 1·2위는 「AI 다중모달 심리진단 **시스템 개발** 용역」과
「마운트 에이전트 개발을 위한 **DB 구축** 용역」이었고, 정작 교육 공고는 B 였다.

1위가 엉뚱하면 목록 전체의 신뢰가 무너진다 — 담당자는 GPT 로 손수 하던
「무관 공고 빼기」를 이 화면에서 또 해야 한다.

## 이 파일이 고정하는 것

검수 보고서가 이름을 적은 **네 건**을 고정 케이스로 둔다. 규칙을 다시 손볼 때
이 네 건이 다시 올라오면 여기서 막힌다.

지우지는 않는다 — 점수를 낮추고 사유를 붙일 뿐이다. 규칙이 틀렸을 때 담당자가
목록에서 찾을 수조차 없게 되는 쪽이 더 나쁘다 (CLAUDE.md 11).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import SupportProgram
from app.schemas.procurement import ProcurementNotice
from app.services import audience_filter, bizinfo_service, recommendation
from app.services.opportunity_filter import classify

NOW = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 16)


# ---------------------------------------------------------------------------
# 판정 규칙 자체
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 교육생 모집 공고",
        "반려동물 창업 아이디어 경진대회 참가자 모집",
        "전주국제발효식품엑스포 참가기업 모집",
        "청년 디지털 아카데미 수강생 모집 안내",
    ],
)
def test_회사가_신청자가_아닌_안내에는_사유가_붙는다(text: str) -> None:
    note = audience_filter.audience_note(text)
    assert note is not None
    assert "원문에서 확인" in note


@pytest.mark.parametrize(
    "text",
    [
        "생성형 AI 실무교육 운영 용역",
        "공무원 대상 AI 리터러시 교육과정 운영 위탁",
        "교육생 200명 대상 AI 교육 운영 용역",  # 「교육생」이 있어도 우리가 «수행»한다
        "AI 활용 역량강화 교육 운영기관 모집",
    ],
)
def test_우리가_수행하는_사업은_그대로_둔다(text: str) -> None:
    """고치면서 진짜 일감까지 걸러 내면 더 나쁘다."""
    assert audience_filter.audience_note(text) is None


# ---------------------------------------------------------------------------
# 기업마당 — 적합도 점수
# ---------------------------------------------------------------------------


def _program(title: str, *, target: str | None = None, summary: str | None = None) -> SupportProgram:
    return SupportProgram(
        id="bizinfo-fixed",
        title=title,
        agency="가상기관",
        summary=summary or title,
        apply_end=TODAY + timedelta(days=20),
        target=target,
        hashtags=["AI", "교육"],
    )


@pytest.mark.parametrize(
    ("title", "target"),
    [
        ("2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 교육생 모집 공고", "만 19세 이상 공예작가·유통사업자"),
        ("반려동물 창업 아이디어 경진대회 참가자 모집", "예비창업자"),
        ("전주국제발효식품엑스포 참가기업 모집", "중소기업"),
    ],
)
def test_무관_지원사업은_적합_등급을_받지_못한다(title: str, target: str) -> None:
    """「적합」(0.65) 은 물론 「검토」(0.4) 아래로 내려간다 — 상단에 섞이지 않는다."""
    fit = bizinfo_service.support_fit(_program(title, target=target), today=TODAY)
    assert fit.label == "낮음", f"{title} → {fit.label} {fit.score}"
    assert fit.score <= bizinfo_service._AUDIENCE_SCORE_CAP
    # 왜 내렸는지가 화면에 그대로 나가야 한다.
    target_component = next(c for c in fit.components if c.key == "target")
    assert "원문에서 확인" in target_component.reason


def test_회사가_수행하는_지원사업은_점수를_잃지_않는다() -> None:
    plain = bizinfo_service.support_fit(
        _program("중소기업 재직자 대상 생성형 AI 실무교육 운영 지원", target="중소기업"), today=TODAY
    )
    assert plain.score > bizinfo_service._AUDIENCE_SCORE_CAP


# ---------------------------------------------------------------------------
# 나라장터 — 개발만 있는 공고
# ---------------------------------------------------------------------------


def _notice(title: str) -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-FIXED-000",
        notice_no="FIXED",
        title=title,
        agency="가상기관",
        published_at=NOW - timedelta(days=2),
        deadline_at=NOW + timedelta(days=30),
        budget=100_000_000,
        region="광주광역시",
        description=title,
    )


def _grade(title: str):
    notice = _notice(title)
    return recommendation.evaluate(
        notice,
        classify(notice),
        now=NOW,
        preferred_regions=("광주", "전남"),
        capacity_krw=300_000_000,
    )


def test_개발만_있는_공고는_A등급을_받지_않는다() -> None:
    """실측 A등급 1·2위가 시스템 개발·DB 구축이었고 교육 공고는 B 였다."""
    for title in (
        "소방공무원 AI 다중모달 심리진단 시스템 개발 용역",
        "마운트 에이전트 개발을 위한 DB 구축 용역",
    ):
        result = _grade(title)
        assert result.grade != "A", f"{title} → {result.grade} {result.score:.3f}"
        assert result.gate_reason and "교육 수행 문구가 없습니다" in result.gate_reason


def test_교육_수행_공고는_A등급을_받을_수_있다() -> None:
    result = _grade("공공기관 직원 대상 생성형 AI 실무교육 운영 용역")
    assert result.grade == "A"
    assert result.gate_reason is None


# ---------------------------------------------------------------------------
# 통합 목록의 「회사 기준 검토 우선순위」
#
# 적합도(support_fit)와 추천등급(recommendation)을 고쳐도 목록 순서는 안 바뀐다 —
# 통합 점수는 `score_support`·`score_procurement` 가 «다시» 계산하기 때문이다.
# 실제로 첫 수정 뒤에도 「교육생 모집」이 1위(74점) 그대로였다. 두 경로를 함께 고정한다.
# ---------------------------------------------------------------------------


def _profile():
    from app.schemas.company import CompanyProfile

    return CompanyProfile(
        name="주식회사 샘플에듀",
        business_domains=["AI 활용 교육", "생성형 AI 교육", "AI 컨설팅"],
        preferred_regions=["광주광역시", "전라남도"],
    )


def _unified_support_score(title: str, target: str) -> int | None:
    from app.services import opportunity_priority as priority

    program = _program(title, target=target)
    fit = bizinfo_service.support_fit(program, today=TODAY)
    components, _reasons, checks, _src = priority.score_support(
        program, fit, profile=_profile(), source="bizinfo", today=TODAY
    )
    assert any("원문에서 확인" in c for c in checks), f"사유가 붙지 않았다: {checks}"
    return priority.normalize(components)


def test_통합_점수에서도_무관_지원사업은_우선_검토가_아니다() -> None:
    for title, target in (
        ("2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 교육생 모집 공고", "중소기업"),
        ("2026년 제2회 반려동물 창업 아이디어 경진대회 참가자 모집 공고", "창업벤처"),
        ("제24회 전주국제발효식품엑스포 참가기업 4차 추가모집 공고", "중소기업"),
    ):
        from app.services import opportunity_priority as priority

        score = _unified_support_score(title, target)
        assert score is not None and score < priority.PRIORITY_HIGH, f"{title} → {score}"


def test_통합_점수에서_그_밖의_갈래는_우리_갈래보다_아래다() -> None:
    """8차에서 기준이 바뀌었다 (0922 §4-B-1).

    예전 규칙은 「개발만 있는 공고는 교육 공고보다 아래」였다. 그것은 「샘플에듀의 주된 일은
    교육」이라는 전제 위에 서 있었는데, 회사가 개발 3명을 두고 AI 에이전트·RAG·챗봇을
    직접 만든다고 적었으므로 그 전제가 틀렸다 — 검수자가 손으로 고른 1~3순위가 전부
    개발 공고였다(`apply_candidates.md` §2).

    그래서 개발형과 교육·훈련형은 **같은 등급**이고, 그 아래에 「그 밖」이 있다 —
    전시·행사·대행·방송 제작·임차·감리·영향평가. 우리가 수행자가 아닌 일들이다.
    """
    from app.services import opportunity_priority as priority

    def score(title: str) -> int | None:
        notice = _notice(title)
        components, _r, _c, _s = priority.score_procurement(
            notice, classify(notice), profile=_profile(), source="g2b", now=NOW
        )
        return priority.normalize(components)

    development = score("마운트 에이전트 개발을 위한 DB 구축 용역")
    education = score("가천대학교 AI부트캠프 사업 피지컬 AI 교육 기획·운영 위탁 용역")
    assert development is not None and education is not None
    assert development == education, f"개발 {development} · 교육 {education}"

    for other in (
        "AI기반 실종자 예측 시스템 구축 위탁 감리",
        "2026 AI/SW 융합페어 및 Job Conference 대행 용역",
        "SBS 창사특집 대기획 가제:미래인류 AI 페르소나 소프트웨어 구축 및 콘텐츠 제작 용역",
        "2026 AI·빅데이터 기반 학교 리더십 전략과정 직무연수 3기 연수시설 임차 용역",
        "AI 빅데이터 분석기반 보훈심사 지원시스템 구축 개인정보 영향평가",
    ):
        value = score(other)
        assert value is not None and value < development, f"{other} → {value} (개발 {development})"
