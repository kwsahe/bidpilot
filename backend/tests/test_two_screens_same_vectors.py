"""목록과 상세는 **같은 벡터 집합**으로 계산된다 (ISSUE-129 · prompt_05 §4-B).

## 11차에 고친 것과 무엇이 다른가

11차(ISSUE-097)에 목록과 상세가 **같은 함수**(`support_application_service.judge`)를 쓰게
했다. 그런데 재검증에서 같은 공고가 목록 85점·상세 74점이었다. 함수는 하나인데 **입력이
시간에 따라 달라졌다** — 목록은 벡터가 생기기 전에 계산돼 메모에 남았고, 상세는 벡터가
생긴 뒤에 계산됐다. 그래서 「같은 함수」에 「같은 입력」을 더한다.

## 여기서 재는 것

1. 벡터가 **없을 때** 두 화면이 같은 점수다 (시연 기본 상태).
2. 벡터가 **전부 있을 때**도 같다 — 그리고 그 점수는 (1)과 **다르다**. 다르지 않으면
   이 검사는 의미 유사도 경로를 지나지 않은 것이다.
3. 벡터가 **절반만** 있으면 의미 유사도를 쓰지 않는다 — 키워드 값으로 둘이 같다.
4. 메모를 쓴 뒤 **벡터가 늘면** 메모가 무효가 된다. 이것이 목록 85·상세 74 의 직접 원인이다.

실제 임베딩은 부르지 않는다. 벡터는 합성이고(`synthetic=True`) tmp 캐시에만 있다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.core import storage
from app.core.config import get_settings
from app.schemas.organization import AnalysisContext
from app.services import (
    bizinfo_service,
    company_service,
    eligibility_engine,
    opportunity_service,
    recommendation,
    semantic_matcher,
    support_application_service,
)

NOW = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)
ORG = "org-sample"


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일의 「지금」은 `NOW` 로 고정이다 (ISSUE-133 · prompt_07 §4-A).

    예전에는 목록에만 `now=NOW` 를 넘겼다. 상세(`build`)는 인자가 없어 실제 시계를 읽었고,
    **9-22 가 되자** 상세가 다른 날짜로 메모 열쇠를 만들어 목록 메모를 못 찾았다(48 ≠ 7).
    9-21 에는 두 날짜가 같아 통과했다 — 코드가 아니라 날짜가 검사를 깨뜨린 것이다.

    지금은 앱이 판정에 쓰는 「지금」이 `storage.utc_now()` 하나이므로, 여기를 고정하면
    목록과 상세가 **같은 날**을 본다. 시계를 앞당겨 돌려도(`--timeshift-days`) 이 파일은
    절대 날짜를 고정한 채로 남는다 — 재는 것이 「두 화면이 같은가」이지 「오늘이 며칠인가」가
    아니기 때문이다.
    """
    monkeypatch.setattr(storage, "utc_now", lambda: NOW)


#: 「디지털·데이터·바우처」가 걸리는 제목 — 키워드 경로에서 사업영역 0.833 이 나온다.
PROGRAM_ID = "bizinfo-PBLN_TWOSCREEN_1"
TITLE = "디지털 전환 데이터 활용 바우처"
SUMMARY = "중소기업의 데이터 활용을 지원하는 바우처 사업입니다."


@pytest.fixture()
def bizinfo_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """지원사업 한 건만 담긴 캐시를 tmp 에 둔다. 저장소의 실제 캐시는 건드리지 않는다."""
    path = tmp_path / "bizinfo" / "bizinfo_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_note": "테스트용 기업마당 캐시",
                "fetched_at": NOW.isoformat(),
                "total_fetched": 1,
                "items": [
                    {
                        "pblancId": "PBLN_TWOSCREEN_1",
                        "pblancNm": TITLE,
                        "jrsdInsttNm": "테스트기관",
                        "bsnsSumryCn": SUMMARY,
                        "pldirSportRealmLclasCodeNm": "기술",
                        "reqstBeginEndDe": "20260901 ~ 20261231",
                        "trgetNm": "중소기업",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", path)
    return path


@pytest.fixture()
def tmp_vector_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """벡터 캐시를 tmp 로 돌리고 합성 벡터를 읽을 수 있게 한다. 처음에는 **비어 있다.**"""
    cache = tmp_path / "embeddings"
    monkeypatch.setattr(semantic_matcher, "CACHE_DIR", cache)
    monkeypatch.setattr(semantic_matcher, "ALLOW_SYNTHETIC_VECTORS", True)
    monkeypatch.setattr(opportunity_service, "_MEMO_DIR", tmp_path / "memo")
    recommendation._PHRASE_MEMO = None
    semantic_matcher._read_cache_file.cache_clear()
    yield cache
    recommendation._PHRASE_MEMO = None


def _texts() -> tuple[str, list[str]]:
    """이 공고의 비교 텍스트와 회사 프로필 문구들."""
    profile = company_service.load_profile(ORG)
    phrases = list(
        recommendation.company_phrases(
            business_domains=profile.business_domains,
            target_clients=profile.target_clients,
            certifications=profile.certifications,
        )
    )
    return semantic_matcher.notice_text(title=TITLE, summary=SUMMARY), phrases


#: 공고와 «가장 가까운 문구» 사이의 코사인. 0.65 는 정규화 구간(0.55~0.90) 안이라
#: 의미 점수가 0.286 이 되고, 키워드 값 0.833 **아래**다.
#:
#: 아래쪽 값을 고른 이유: 위로 올리면 사업영역 점수가 「우리 갈래가 아닌 사업」의 상한
#: (`opportunity_priority.NON_MATCHING_KIND_CAP`)에 걸려 두 경로가 **같은 값**으로 깎인다.
#: 처음에 1.0 으로 두었더니 48 == 48 이 나와, 벡터를 심었는데도 검사가 아무것도 가리지
#: 못했다. 점수가 달라지는 방향으로 심어야 「어느 경로로 냈는가」가 숫자에 보인다.
_COSINE = 0.65
_ORTHOGONAL = (0.0, 1.0, 0.0)


def seed_vectors(*, all_of_them: bool) -> None:
    """공고와 프로필 문구의 합성 벡터를 심는다.

    `all_of_them=False` 면 문구의 **절반만** 심는다 — 「일부만 있는 상태」다.
    """
    import math

    notice, phrases = _texts()
    semantic_matcher.store_cached(notice, [1.0, 0.0, 0.0], synthetic=True)
    near = [_COSINE, math.sqrt(1 - _COSINE**2), 0.0]
    chosen = phrases if all_of_them else phrases[: max(1, len(phrases) // 2)]
    for index, phrase in enumerate(chosen):
        semantic_matcher.store_cached(phrase, near if index == 0 else list(_ORTHOGONAL), synthetic=True)


def list_score() -> int | None:
    context = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    listing = asyncio.run(
        # `now=` 를 넘기지 않는다 — **기본 경로가 상세와 같은 날을 보는지**를 잰다.
        opportunity_service.list_opportunities(context=context, include_blocked=True)
    )
    item = next((i for i in listing.items if i.id == PROGRAM_ID), None)
    return item.company_priority_score if item else None


def detail_score() -> int | None:
    context = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    body = asyncio.run(support_application_service.build(PROGRAM_ID, context=context))
    return body["company_priority_score"]


# ---------------------------------------------------------------------------
# 1~3) 세 상태에서 두 화면이 같다
# ---------------------------------------------------------------------------


def test_벡터가_없으면_두_화면이_같다(bizinfo_one: Path, tmp_vector_cache: Path) -> None:
    """시연 기본 상태다. 여기가 깨지면 큐시트 숫자를 믿을 수 없다."""
    listed = list_score()
    assert listed is not None
    assert detail_score() == listed


def test_벡터가_전부_있어도_두_화면이_같다(
    bizinfo_one: Path, tmp_vector_cache: Path, semantic_fit_on: None
) -> None:
    """그리고 그 점수는 벡터가 없을 때와 **달라야** 한다 — 같으면 이 검사가 헛돈 것이다."""
    keyword_only = list_score()
    opportunity_service.clear_support_memo()

    seed_vectors(all_of_them=True)
    listed = list_score()
    assert listed is not None
    assert detail_score() == listed, "목록과 상세가 갈렸다"
    assert listed != keyword_only, (
        f"벡터를 심었는데 점수가 그대로다({listed}) — 의미 유사도 경로를 지나지 않았다"
    )


def test_벡터가_절반만_있으면_키워드_값으로_둘이_같다(
    bizinfo_one: Path, tmp_vector_cache: Path, semantic_fit_on: None
) -> None:
    """전부 있거나, 전부 없거나다 (§4-B-2).

    일부만 재면 「캐시에 있던 문구」만 후보가 되어 가장 가까운 문구가 뒤바뀐다 —
    순위가 캐시 상태에 따라 달라진다.
    """
    keyword_only = list_score()
    opportunity_service.clear_support_memo()

    seed_vectors(all_of_them=False)
    listed = list_score()
    assert listed == keyword_only, "절반만 있는 벡터로 점수를 냈다"
    assert detail_score() == listed


# ---------------------------------------------------------------------------
# 4) 메모가 벡터 집합을 본다 — 85 vs 74 의 직접 원인
# ---------------------------------------------------------------------------


def test_메모를_쓴_뒤_벡터가_늘면_메모가_무효다(
    bizinfo_one: Path, tmp_vector_cache: Path, semantic_fit_on: None
) -> None:
    """이것이 재검증의 목록 85 · 상세 74 였다.

    예전 메모 열쇠는 기업마당 캐시 시각과 공고문 목록 시각만 봤다. 벡터가 생겨도 열쇠가
    그대로라 목록은 옛 점수를 계속 내놓았고, 상세는 새 입력으로 계산해 다른 값을 냈다.
    """
    before = list_score()  # 메모가 만들어진다 (벡터 없음)

    seed_vectors(all_of_them=True)
    after = list_score()  # 같은 열쇠라면 옛 점수가 그대로 나온다

    assert after != before, "벡터가 늘었는데 목록이 옛 메모를 그대로 썼다"
    assert detail_score() == after


def test_지문은_꺼져_있으면_세지_않는다(tmp_vector_cache: Path) -> None:
    """꺼짐이 시연 기본값이다 — 매 요청마다 1,802개를 셀 이유가 없다."""
    seed_vectors(all_of_them=True)
    assert semantic_matcher.cache_fingerprint() == "off"


def test_지문은_벡터가_늘면_달라진다(tmp_vector_cache: Path, semantic_fit_on: None) -> None:
    empty = semantic_matcher.cache_fingerprint()
    seed_vectors(all_of_them=True)
    assert semantic_matcher.cache_fingerprint() != empty


# ---------------------------------------------------------------------------
# 상세가 목록의 점수를 먼저 읽는다
# ---------------------------------------------------------------------------


def test_상세는_목록이_이미_낸_점수를_먼저_읽는다(bizinfo_one: Path, tmp_vector_cache: Path) -> None:
    """메모가 살아 있다는 것은 입력 지문이 같다는 뜻이다 — 그래서 꺼내 써도 같은 값이다.

    여기서는 메모를 **일부러 다른 값으로 바꿔** 상세가 정말 그것을 읽는지 가린다.
    (운영에서 이렇게 갈리면 버그다. 그때는 로그에 남는다.)
    """
    assert list_score() is not None

    today = storage.kst_today()
    company = eligibility_engine.company_facts_for(ORG)
    found = opportunity_service.memoized_support_score(
        PROGRAM_ID, organization_id=ORG, today=today, company=company
    )
    assert found is not None, "목록 메모에서 점수를 찾지 못했다"

    for _key, outcome in opportunity_service._SUPPORT_MEMO.items():
        for item in outcome[0]:
            if item.id == PROGRAM_ID:
                item.company_priority_score = 7

    assert detail_score() == 7, "상세가 목록 메모를 읽지 않았다"


def test_메모가_없으면_상세가_스스로_계산한다(bizinfo_one: Path, tmp_vector_cache: Path) -> None:
    """목록을 한 번도 열지 않고 상세 링크로 바로 들어오는 경로다."""
    opportunity_service.clear_support_memo()
    assert detail_score() is not None
