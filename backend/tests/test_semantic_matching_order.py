"""「우리 회사 적합도」가 공고를 세워 놓는 **순서**를 고정한다 (CLAUDE.md §4-C).

    교육·운영 공고 4건  >  개발·구축 공고 2건  >  나머지 6건

여기서 쓰는 것은 **합성 벡터**다(`backend/tests/fixtures/llm/semantic_vectors.json`,
`scripts/build_semantic_fixtures.py` 가 만든다). 이 컴퓨터에는 OpenAI 크레딧이 없어
진짜 임베딩을 받을 수 없고, conftest 가 네트워크를 막으므로 받아서도 안 된다.

**이 순서는 합성 벡터로 확인한 것이며, 진짜 임베딩의 품질을 증명하지 않는다.**
여기서 지키는 것은 `semantic_matcher` 쪽 계산이다 — 문구 단위 비교, 최댓값 선택,
정규화 구간, 「높음/보통/낮음」 경계. 실제 임베딩이 이 12건을 같은 순서로 세우는지는
크레딧이 생긴 뒤 사람이 따로 확인해야 한다.

공고 12건은 검수에서 이름이 확인된 실제 공고 제목이다. 회사 프로필은 CLAUDE.md §6 의
공개 가능한 Profile 이며 매출·인력·실적 같은 민감정보는 쓰지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import semantic_matcher

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "llm" / "semantic_vectors.json"

EDUCATION_NOTICES: list[str] = [
    "가천대학교 AI부트캠프 사업 피지컬 AI 교육 기획·운영 위탁 용역",
    "가천대학교 AI부트캠프 사업 생성형 AI 활용 교육 기획·운영 위탁 용역",
    "네이버클라우드 아카데미 교육과정 운영 용역(소버린 AI Literacy)",
    "Agentic AI 교육 프로그램 기획 및 운영 지원 용역",
]

DEVELOPMENT_NOTICES: list[str] = [
    "경성대학교 소방공무원 맞춤형 AI 다중모달 심리진단 및 통합 데이터 관리 시스템 개발 용역",
    "마운트 에이전트 개발을 위한 DB 구축 용역",
]

OTHER_NOTICES: list[str] = [
    "2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 교육생 모집 공고",
    "2026년 중소기업 특성화고 인력양성사업 참여기업 모집 공고",
    "2026년 제2회 반려동물 창업 아이디어 경진대회 참가자 모집 공고",
    "제24회 전주국제발효식품엑스포 참가기업 4차 추가모집 공고",
    "2027년 스마트공장 구축지원사업 주관기관 모집 공고",
    "2026년 성장단계별 우수 연구소기업(라이징스타ㆍ스타) 지정 신청 공고",
]

BUSINESS_DOMAINS: list[str] = [
    "AI 활용 교육",
    "생성형 AI 교육",
    "ChatGPT / Copilot 활용 교육",
    "업무자동화 교육",
    "디지털 역량 교육",
    "AI 컨설팅",
    "ESG 교육 및 컨설팅",
]

TARGET_CLIENTS: list[str] = ["공공기관", "대학", "기업", "교육기관"]


@pytest.fixture()
def synthetic_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, semantic_fit_on: None) -> None:
    """합성 벡터를 **tmp 캐시**에 넣는다. 저장소의 실제 임베딩 캐시는 건드리지 않는다.

    `semantic_fit_on` — 15차부터 의미 유사도는 **점수에 쓰지 않는 것이 기본**이다
    (ISSUE-129). 이 파일이 재는 것은 「쓸 때의 계산」이라 켜 놓는다. 꺼짐의 동작은
    `test_embedding_switch.py` 가 잰다. 바깥으로 나가지 않는다 — 벡터가 캐시에 다 있다.

    캐시에 다 들어 있으면 `embed_cached` 는 바깥으로 나가지 않는다 — 네트워크 없이 돈다.
    `synthetic=True` 를 붙여, 캐시만 보고도 「진짜 임베딩이 아니다」를 알 수 있게 한다.
    """
    if not FIXTURE_PATH.exists():
        pytest.skip(
            f"합성 벡터 픽스처가 없습니다({FIXTURE_PATH.name}). "
            "`python scripts/build_semantic_fixtures.py` 로 만든 뒤 다시 돌리세요."
        )
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    vectors = payload.get("vectors") or {}
    if not vectors:
        pytest.skip("합성 벡터 픽스처가 비어 있습니다. scripts/build_semantic_fixtures.py 로 다시 만드세요.")

    monkeypatch.setattr(semantic_matcher, "CACHE_DIR", tmp_path / "embeddings")
    # 합성 벡터는 평소 읽히지 않는다(운영이 시험용 값을 진짜로 착각하지 않게). 여기서만 켠다.
    monkeypatch.setattr(semantic_matcher, "ALLOW_SYNTHETIC_VECTORS", True)
    for text, vector in vectors.items():
        semantic_matcher.store_cached(text, vector, synthetic=True)


def _phrases() -> list[str]:
    return semantic_matcher.profile_phrases(
        business_domains=BUSINESS_DOMAINS,
        target_clients=TARGET_CLIENTS,
    )


def _score(title: str) -> float:
    """공고 한 건의 적합도. 캐시에 없으면 픽스처가 낡은 것이므로 바로 세운다."""
    fit = semantic_matcher.match(notice=semantic_matcher.notice_text(title=title), phrases=_phrases())
    assert fit.method == "EMBEDDING" and fit.fit_score is not None, (
        f"합성 벡터로 재지 못했습니다: 「{title}」 -> {fit.to_dict()}. "
        "픽스처가 이 제목이나 회사 프로필 문구를 담고 있지 않습니다 — "
        "`python scripts/build_semantic_fixtures.py` 로 다시 만드세요."
    )
    return fit.fit_score


def _table(scores: dict[str, float]) -> str:
    lines = []
    for group, titles in (
        ("교육", EDUCATION_NOTICES),
        ("개발", DEVELOPMENT_NOTICES),
        ("그 외", OTHER_NOTICES),
    ):
        for title in titles:
            lines.append(f"  [{group}] {scores[title]:.4f}  {title}")
    return "\n".join(lines)


@pytest.mark.usefixtures("synthetic_cache")
def test_education_notices_outrank_development_and_the_rest() -> None:
    """교육 4건 > 개발 2건 > 나머지 6건.

    합성 벡터로 확인한 순서이며, 진짜 임베딩의 품질을 증명하지 않는다.
    """
    all_titles = [*EDUCATION_NOTICES, *DEVELOPMENT_NOTICES, *OTHER_NOTICES]
    scores = {title: _score(title) for title in all_titles}
    table = _table(scores)

    education_low = min(scores[t] for t in EDUCATION_NOTICES)
    development_high = max(scores[t] for t in DEVELOPMENT_NOTICES)
    other_high = max(scores[t] for t in OTHER_NOTICES)

    assert education_low > development_high, (
        "교육 공고의 최저점이 개발 공고의 최고점보다 낮습니다 "
        f"({education_low:.4f} <= {development_high:.4f}).\n{table}"
    )
    assert development_high > other_high, (
        "개발 공고의 최고점이 나머지 공고의 최고점보다 낮습니다 "
        f"({development_high:.4f} <= {other_high:.4f}).\n{table}"
    )


@pytest.mark.usefixtures("synthetic_cache")
def test_recruitment_notice_does_not_ride_on_the_word_education() -> None:
    """「교육생 모집 공고」는 교육이라는 말이 들어 있어도 교육 용역보다 아래여야 한다.

    참가자를 뽑는 안내문이지 수행사를 뽑는 입찰이 아니다 — 이걸 가르지 못하면 담당자가
    제안서를 낼 수 없는 공고를 상단에서 보게 된다. 이 역시 합성 벡터로 확인한 것이다.
    """
    recruitment = "2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 교육생 모집 공고"
    scores = {title: _score(title) for title in (*EDUCATION_NOTICES, recruitment)}
    education_low = min(scores[t] for t in EDUCATION_NOTICES)

    assert scores[recruitment] < education_low, (
        f"모집 공고({scores[recruitment]:.4f})가 교육 용역 최저점({education_low:.4f}) 위에 있습니다.\n"
        + "\n".join(f"  {score:.4f}  {title}" for title, score in scores.items())
    )


@pytest.mark.usefixtures("synthetic_cache")
def test_fit_labels_follow_the_scores() -> None:
    """점수와 화면 라벨이 따로 놀지 않는지. 라벨은 한국어 「높음/보통/낮음」뿐이다."""
    for title in (*EDUCATION_NOTICES, *DEVELOPMENT_NOTICES, *OTHER_NOTICES):
        fit = semantic_matcher.match(notice=semantic_matcher.notice_text(title=title), phrases=_phrases())
        assert fit.label in {"높음", "보통", "낮음"}, f"「{title}」 라벨: {fit.label}"
        assert fit.fit_score is not None
        assert fit.label == semantic_matcher.label_of(fit.fit_score), (
            f"「{title}」 점수 {fit.fit_score} 와 라벨 {fit.label} 이 어긋납니다."
        )
        # 사유는 담당자가 그대로 읽는 문장이다. 어느 사업영역과 붙었는지가 들어 있어야 한다.
        assert "회사 사업영역" in fit.reason, f"「{title}」 사유: {fit.reason}"

    education = semantic_matcher.match(
        notice=semantic_matcher.notice_text(title=EDUCATION_NOTICES[0]), phrases=_phrases()
    )
    assert education.label == "높음"


def test_keyword_path_stays_healthy_without_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, semantic_fit_on: None
) -> None:
    """임베딩을 못 쓰는 지금 환경(크레딧 없음)이 **정상 경로**여야 한다.

    점수는 None 이다 — 0 이 아니다. 0 으로 채우면 「재봤더니 안 맞았다」로 읽힌다
    (CLAUDE.md §12). 방식은 키워드 규칙이고, 사유도 그렇게 나가야 한다.
    """
    # 빈 tmp 캐시로 돌린다. 저장소의 실제 캐시에 문구가 남아 있으면 임베딩 경로로 새어
    # 「키워드로 떨어지는가」를 재지 못한다.
    monkeypatch.setattr(semantic_matcher, "CACHE_DIR", tmp_path / "embeddings")
    monkeypatch.setattr(semantic_matcher.llm_client, "embedding_available", lambda **_kw: False)

    fit = semantic_matcher.match(
        notice=semantic_matcher.notice_text(title=EDUCATION_NOTICES[0]),
        phrases=_phrases(),
        keyword_reason="키워드 규칙으로 판정했습니다.",
    )

    assert fit.fit_score is None
    assert fit.label is None
    assert fit.method == "KEYWORD"
    assert fit.reason == "키워드 규칙으로 판정했습니다."
    assert fit.to_dict()["fit_score"] is None
