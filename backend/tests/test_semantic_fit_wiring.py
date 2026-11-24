"""의미 매칭을 점수에 연결한 뒤에도 «못 쟀을 때»의 값이 그대로인가.

이 저장소의 기본 상태는 임베딩을 쓸 수 없는 상태다(키 없음·한도 초과). 그때
`semantic_matcher.match` 는 `method="KEYWORD"` · `fit_score=None` 을 돌려주고, 세 경로
(추천등급 · 검토 우선순위 · 지원 적합도)는 예전 키워드 규칙 값을 **한 자리도 바꾸지 않고**
그대로 써야 한다. 그래서 예전 값을 숫자로 박아 둔다 — 회귀 방지가 이 파일의 첫 목적이다.

의미 매칭이 **될 때**의 동작은 `semantic_matcher.match` 를 대신 세워 확인한다.
네트워크·키를 쓰지 않으며, 재지 못한 값을 0 으로 채우지 않는지도 함께 본다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.company import CompanyProfile
from app.schemas.procurement import ProcurementNotice
from app.services import (
    bizinfo_service,
    opportunity_priority,
    recommendation,
    semantic_matcher,
)
from app.services.opportunity_filter import CandidateMatch
from app.services.semantic_matcher import SemanticFit

NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 7)

#: 의미 매칭이 됐다고 가정할 때 돌려줄 값. 사유 문장은 화면에 그대로 나가는 한국어다.
SEMANTIC = SemanticFit(
    fit_score=0.83,
    label="높음",
    method="EMBEDDING",
    confidence="high",
    reason="회사 사업영역 「AI 활용 교육」와 가장 가깝습니다 (유사도 0.78).",
)


def make_notice(
    *,
    title: str = "인공지능 기반 민원 응대 역량강화 연수 위탁",
    description: str | None = "민원 담당자를 대상으로 한 연수 과정 운영",
) -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-SEMANTIC01-000",
        notice_no="SEMANTIC01-000",
        title=title,
        agency="테스트기관",
        published_at=NOW - timedelta(days=1),
        deadline_at=NOW + timedelta(days=30),
        budget=100_000_000,
        region=None,
        description=description,
    )


def make_match() -> CandidateMatch:
    return CandidateMatch(tier="medium", matched_ai=["인공지능"], matched_work=[])


def make_profile() -> CompanyProfile:
    return CompanyProfile(
        name="샘플에듀",
        business_domains=["AI 활용 교육", "생성형 AI 교육", "AI 컨설팅"],
        target_clients=["공공기관", "대학"],
        preferred_regions=["광주광역시", "전라남도", "전국"],
    )


def make_program(
    *,
    title: str = "디지털 전환 데이터 활용 바우처",
    program_id: str = "SEM1",
):
    program = bizinfo_service.map_program(
        {
            "pblancId": program_id,
            "pblancNm": title,
            "jrsdInsttNm": "광주광역시",
            "reqstBeginEndDe": "20260901 ~ 20261231",
            "trgetNm": "중소기업",
        }
    )
    assert program is not None
    return program


@pytest.fixture()
def cannot_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """임베딩을 쓸 수 없는 상태 — 지금 이 저장소의 기본값."""
    monkeypatch.setattr(semantic_matcher, "embed_cached", lambda _texts: None)
    recommendation._PHRASE_MEMO = None


@pytest.fixture()
def can_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """의미 매칭이 되는 상태. 판정 결과를 직접 세운다 (네트워크·키 없음)."""
    monkeypatch.setattr(semantic_matcher, "match", lambda **_kwargs: SEMANTIC)
    recommendation._PHRASE_MEMO = None


def phrases_of(profile: CompanyProfile) -> tuple[str, ...]:
    return recommendation.company_phrases(
        business_domains=profile.business_domains,
        target_clients=profile.target_clients,
        certifications=profile.certifications,
    )


# ---------------------------------------------------------------------------
# 1) 못 쟀을 때 — 예전 값 그대로 (회귀 방지)
# ---------------------------------------------------------------------------


def test_recommendation_keeps_keyword_score_without_embedding(cannot_embed: None) -> None:
    profile = make_profile()
    result = recommendation.evaluate(
        make_notice(),
        make_match(),
        now=NOW,
        preferred_regions=("광주", "전남"),
        capacity_krw=300_000_000,
        phrases=phrases_of(profile),
    )
    fit = next(c for c in result.components if c.key == "business_fit")
    # 키워드 등급 「보통」의 값과 사유. 의미 매칭이 붙어도 여기가 바뀌면 안 된다.
    assert fit.score == 0.6
    assert fit.reason == "키워드 등급 보통 · 매칭 인공지능"
    assert result.grade == "A" and round(result.score, 4) == 0.7733

    payload = result.to_dict()
    assert payload["fit_method"] == "KEYWORD"
    assert payload["fit_method_label"] == "낱말 기준"
    # 재지 못한 것은 0 이 아니라 «없음»이다 (CLAUDE.md §12).
    assert payload["fit_score"] is None and payload["fit_label"] is None


def test_recommendation_without_phrases_is_untouched(cannot_embed: None) -> None:
    """회사 프로필 문구를 넘기지 않으면 의미 매칭을 아예 하지 않는다."""
    result = recommendation.evaluate(
        make_notice(), make_match(), now=NOW, preferred_regions=("광주", "전남")
    )
    assert result.fit is None
    assert next(c for c in result.components if c.key == "business_fit").score == 0.6
    assert result.to_dict()["fit_method"] == "KEYWORD"


def test_priority_domain_keeps_keyword_score_without_embedding(cannot_embed: None) -> None:
    components, _reasons, _checks, source = opportunity_priority.score_procurement(
        make_notice(), make_match(), profile=make_profile(), source="g2b", now=NOW
    )
    domain = next(c for c in components if c.key == "domain")
    # 8차부터 사업영역은 **등급**이다 (0922 §4-B-1). 임베딩을 못 쓰면 등급만 남는다.
    # 교육·훈련형 공고이므로 「우리 갈래」 0.7 이다.
    assert domain.score == opportunity_priority.DOMAIN_TRACK
    assert domain.reason == "회사가 하는 종류의 일입니다 (교육·훈련형)"
    assert source["fit_method"] == "KEYWORD" and source["fit_score"] is None


def test_support_fit_keeps_keyword_score_without_embedding(cannot_embed: None) -> None:
    fit = bizinfo_service.support_fit(make_program(), today=TODAY)
    domain = next(c for c in fit.components if c.key == "domain")
    # 핵심어 1개(1/2) + 약한 신호 2개(2/6). 이 셈이 바뀌면 안 된다.
    assert domain.score == 0.833
    assert domain.label == "사업영역 낱말"
    assert domain.reason == "맞는 낱말: 디지털 · 흔한 낱말: 데이터, 바우처"
    assert fit.method == bizinfo_service.KEYWORD_FIT_METHOD == "keyword_rule"
    # 「의미 매칭이 아니다」가 아니라 «왜 못 썼는지»가 적혀야 한다 — 화면이 그대로 읽는 문장이다.
    # 스위치가 꺼져 있으면 「꺼 두었다」가 사실이다(32차 뜻 틀린 곳 #7) — 켜져 있는데 못 쟀을 때만 「쓸 수 없었다」.
    if semantic_matcher.semantic_fit_enabled():
        assert "AI 의미 매칭을 쓸 수 없었습니다" in fit.note
    else:
        assert "AI 의미 매칭은 꺼 두었습니다" in fit.note


# ---------------------------------------------------------------------------
# 2) 쟀을 때 — 점수와 사유가 의미 매칭을 따른다
# ---------------------------------------------------------------------------


def test_recommendation_uses_semantic_score(can_embed: None) -> None:
    profile = make_profile()
    result = recommendation.evaluate(
        make_notice(),
        make_match(),
        now=NOW,
        preferred_regions=("광주", "전남"),
        capacity_krw=300_000_000,
        phrases=phrases_of(profile),
    )
    fit = next(c for c in result.components if c.key == "business_fit")
    assert fit.score == 0.83
    # 키워드 사유를 지우지 않고 «함께» 남긴다.
    assert fit.reason.startswith("키워드 등급 보통 · 매칭 인공지능")
    assert SEMANTIC.reason in fit.reason

    payload = result.to_dict()
    assert payload["fit_method"] == "EMBEDDING"
    assert payload["fit_method_label"] == "AI 의미 매칭"
    assert payload["fit_score"] == 0.83 and payload["fit_label"] == "높음"
    assert payload["fit_reason"] == SEMANTIC.reason


def test_priority_domain_uses_semantic_score(can_embed: None) -> None:
    components, reasons, _checks, source = opportunity_priority.score_procurement(
        make_notice(), make_match(), profile=make_profile(), source="g2b", now=NOW
    )
    domain = next(c for c in components if c.key == "domain")
    # 의미 유사도를 키워드 일치 «횟수»로 희석하지 않는다. 등급(0.7)보다 높으면 그 값을 쓴다.
    assert domain.score == 0.83
    assert domain.reason.startswith("회사가 하는 종류의 일입니다")
    assert SEMANTIC.reason in domain.reason
    assert SEMANTIC.reason in reasons
    assert source["fit_method"] == "EMBEDDING"
    assert source["fit_method_label"] == "AI 의미 매칭"
    assert source["fit_score"] == 0.83


def test_support_fit_uses_semantic_score(can_embed: None) -> None:
    fit = bizinfo_service.support_fit(make_program(), today=TODAY)
    domain = next(c for c in fit.components if c.key == "domain")
    assert domain.score == 0.83
    assert domain.label == "사업영역 적합도"
    # 키워드 사유가 남아 있어야 담당자가 두 근거를 모두 읽는다.
    assert domain.reason.startswith("맞는 낱말: 디지털")
    assert SEMANTIC.reason in domain.reason
    assert fit.method == bizinfo_service.SEMANTIC_FIT_METHOD == "AI 의미 매칭"
    assert "AI 의미 매칭" in fit.note and "추천등급" in fit.note


def test_support_priority_domain_follows_semantic_fit(can_embed: None) -> None:
    program = make_program(title="중소기업 생성형 AI 활용 실무교육 운영 지원", program_id="SEM2")
    fit = bizinfo_service.support_fit(program, today=TODAY)
    components, _reasons, _checks, source = opportunity_priority.score_support(
        program, fit, profile=make_profile(), source="bizinfo", today=TODAY
    )
    domain = next(c for c in components if c.key == "domain")
    # 지원 적합도가 의미 매칭으로 나왔으면 그 값을 키워드 일치 횟수로 다시 희석하지 않는다.
    assert domain.score == 0.83
    assert source["fit_method_label"] == "AI 의미 매칭"


def test_out_of_scope_cap_beats_semantic_score(can_embed: None) -> None:
    """의미 유사도가 높아도 「감리」 사업이 상단으로 돌아오면 안 된다."""
    profile = make_profile()
    # 교육을 «직접 수행»한다는 문구가 없어야 사업 유형 규칙이 걸린다.
    notice = make_notice(title="AI 정보시스템 위탁감리 용역", description=None)
    result = recommendation.evaluate(
        notice,
        make_match(),
        now=NOW,
        preferred_regions=("광주", "전남"),
        phrases=phrases_of(profile),
    )
    fit = next(c for c in result.components if c.key == "business_fit")
    assert fit.score is not None and fit.score <= recommendation.OUT_OF_SCOPE_TOPIC_SCORE
    assert result.out_of_scope is True and result.grade == "D"


# ---------------------------------------------------------------------------
# 3) 목록 성능 — 회사 프로필 문구는 목록당 한 번만 쪼갠다
# ---------------------------------------------------------------------------


def test_profile_phrases_are_split_once_per_list(
    cannot_embed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    original = semantic_matcher.profile_phrases

    def counting(**kwargs):
        calls.append(1)
        return original(**kwargs)

    monkeypatch.setattr(semantic_matcher, "profile_phrases", counting)
    profile = make_profile()
    for index in range(5):
        opportunity_priority.score_procurement(
            make_notice(title=f"인공지능 교육 용역 {index}"),
            make_match(),
            profile=profile,
            source="g2b",
            now=NOW,
        )
    assert len(calls) == 1, "공고마다 프로필을 다시 쪼개면 안 된다"


def test_phrase_memo_follows_profile_content(cannot_embed: None) -> None:
    first = phrases_of(make_profile())
    again = phrases_of(make_profile())
    assert first is again  # 같은 프로필이면 쪼갠 결과를 다시 쓴다
    other = recommendation.company_phrases(business_domains=["제조 설비 자동화"])
    assert other != first  # 회사가 바뀌면 값도 바뀐다 (내용이 캐시 키다)
    assert first[0].startswith("AI")


# ---------------------------------------------------------------------------
# 4) 목록 화면이 «읽는 자리»에 실제로 실리는가
#
# 위 테스트들은 recommendation.evaluate 에 phrases 를 «넘겼을 때»를 본다. 그런데 목록
# 화면이 읽는 값은 procurement_service 가 만들고, 그 쪽이 phrases 를 넘기지 않으면
# 의미 매칭은 영영 켜지지 않는다 — 배선은 다 돼 있는데 화면만 그대로인 상태가 된다.
# 실제로 그랬다(검수에서 발견). 그래서 그 «연결»을 따로 고정한다.
# ---------------------------------------------------------------------------


def test_company_basis_carries_phrases() -> None:
    """목록이 쓰는 회사 기준값에 의미 매칭 비교 문구가 들어 있다."""
    from app.services import procurement_service

    basis = procurement_service._load_company_basis()
    assert basis.phrases, "회사 프로필 문구가 비어 있으면 의미 매칭이 아예 돌지 않는다"


def test_notice_payload_reports_semantic_fit(
    can_embed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """목록 payload 의 recommendation 자리에 판정 방식·점수·사유가 실린다."""
    from app.services import procurement_service

    monkeypatch.setattr(
        procurement_service,
        "_company_basis",
        lambda: procurement_service.CompanyBasis(phrases=("AI 활용 교육",)),
    )
    view = procurement_service.NoticeView(notice=make_notice(), match=make_match())
    payload = view.to_dict()

    fit = payload["recommendation"]
    assert fit["fit_method"] == "EMBEDDING"
    assert fit["fit_method_label"] == "AI 의미 매칭"
    assert fit["fit_score"] == SEMANTIC.fit_score
    assert fit["fit_reason"] == SEMANTIC.reason


def test_notice_payload_falls_back_to_keyword(
    cannot_embed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """못 재면 키워드 규칙으로 적고 점수 자리는 비운다 (0 으로 채우지 않는다)."""
    from app.services import procurement_service

    monkeypatch.setattr(
        procurement_service,
        "_company_basis",
        lambda: procurement_service.CompanyBasis(phrases=("AI 활용 교육",)),
    )
    fit = procurement_service.NoticeView(notice=make_notice(), match=make_match()).to_dict()["recommendation"]

    assert fit["fit_method"] == "KEYWORD"
    assert fit["fit_method_label"] == "낱말 기준"
    assert fit["fit_score"] is None
    # 「미실행」이 아니라 «왜 못 썼는지»가 적혀야 한다 — 화면이 그대로 읽는 문장이다.
    assert "낱말 기준으로만 판정했습니다" in (fit["fit_reason"] or "")
