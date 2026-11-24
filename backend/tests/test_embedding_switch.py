"""임베딩도 시연 고정 모드 안에 있다 (ISSUE-129 · prompt_05 §4-A).

## 무슨 일이 있었나

2026-09-21 11:20~11:26, **고정 모드로 띄운 서버가 OpenAI 임베딩 1,802건을 실제로 불렀다.**
`G2B_LIVE_FETCH=0`·`BIZINFO_LIVE_FETCH=0` 은 나라장터·기업마당만 막는다. OpenAI 는 별개
문이었고, 키에 크레딧이 생기자 `embedding_available()` 의 **탐침이 성공**해 `embed()` 가
열렸다. 목록 한 번이 6분 멈춘 것이 그 6분이다.

기록에도 남지 않았다 — `llm_usage.jsonl` 은 탐침만 적고 `embed()` 는 적지 않았다.
세지 못하는 호출은 막았는지도 확인할 수 없다.

그 순간 **점수가 바뀌었다.** 벡터가 생기기 전에 계산된 목록은 85점(키워드), 뒤에 계산된
상세는 74점(의미 유사도)이었고, 수용 스크립트의 두 화면 대조가 33건 불일치였다.

## 그래서 문이 둘이다

`EMBEDDING_LIVE` — 「바깥을 부르는가」. 꺼지면 탐침도 `embed()` 도 아무것도 부르지 않고,
    **OpenAI 클라이언트를 만들지도 않는다.**
`SEMANTIC_FIT`  — 「점수에 쓰는가」. 꺼지면 **캐시 벡터가 있어도** 사업영역 점수를 키워드
    규칙으로만 낸다.

앞의 것만 끄면 디스크의 벡터 1,802개로 점수가 계속 달라지고, 캐시를 지워야만 고정된다.
캐시를 지우는 것은 담당자 결정이므로(§4-A-5) 「읽지 않는 문」을 따로 둔다.

## 여기서 재는 것

두 문이 **기본값으로 닫혀 있는지**, 그리고 열면 실제로 열리는지다. 「켜면 비로소 부른다」를
함께 재지 않으면 「아무것도 안 하는 코드」도 이 검사를 통과한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import bizinfo_service, llm_client, recommendation, semantic_matcher

#: conftest 의 autouse 픽스처가 `embedding_available`·`embed` 를 «못 쓴다»로 바꿔 둔다.
#: 여기서 재려는 것이 바로 그 함수들이므로 진짜를 되돌린다.
_REAL_AVAILABLE = llm_client.embedding_available
_REAL_EMBED = llm_client.embed


@pytest.fixture()
def real_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "embedding_available", _REAL_AVAILABLE)
    monkeypatch.setattr(llm_client, "embed", _REAL_EMBED)
    # 키가 있는 상태로 둔다 — 「키가 없어서 안 불렀다」가 아니라 «꺼져 있어서» 안 불렀음을
    # 재야 한다. 키가 없으면 스위치를 켜도 안 부르므로 검사가 아무것도 증명하지 못한다.
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "_embedding_ok", None)
    monkeypatch.setattr(llm_client, "_embedding_checked_at", 0.0)
    monkeypatch.setattr(llm_client, "_probe_in_flight", False)
    monkeypatch.setattr(llm_client, "_embedding_reason", None)


@pytest.fixture()
def no_client(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """OpenAI 클라이언트를 **만들려고만 해도** 터진다.

    「부르지 않았다」를 호출 횟수로만 재면 부족하다. 클라이언트를 만드는 줄까지 갔다면
    다음 줄이 곧 호출이고, 그 사이에 코드가 한 줄 끼면 조용히 다시 새기 시작한다.
    """
    made: list[str] = []

    def _boom(**_kwargs: object):
        made.append("client")
        raise AssertionError("꺼져 있는데 OpenAI 클라이언트를 만들었습니다")

    monkeypatch.setattr(llm_client, "_client", _boom)
    return made


# ---------------------------------------------------------------------------
# 1) 기본값 — 환경변수 없이
# ---------------------------------------------------------------------------


def test_환경변수가_없으면_두_문이_닫혀_있다() -> None:
    settings = get_settings()
    assert settings.embedding_live is False
    assert settings.semantic_fit is False
    assert llm_client.embedding_live_enabled() is False
    assert semantic_matcher.semantic_fit_enabled() is False


def test_기본값_자체가_꺼짐이다() -> None:
    """설정 인스턴스가 아니라 **선언된 기본값**을 본다 (ISSUE-120 과 같은 방식).

    인스턴스만 보면 「테스트가 꺼 둔 것」과 「기본값이 꺼짐인 것」을 구분하지 못한다.
    """
    from app.core.config import Settings

    assert Settings.model_fields["embedding_live"].default is False
    assert Settings.model_fields["semantic_fit"].default is False


def test_꺼져_있으면_탐침이_뜨지_않고_클라이언트도_안_만든다(
    real_functions: None, no_client: list[str]
) -> None:
    """`embedding_available()` 이 **탐침을 띄우기 전에** 스위치를 본다 (§4-A-4).

    이 한 줄이 없으면 `/health` 한 번이 바깥을 부른다 — 재검증에서 실제로 그랬다.
    """
    assert llm_client.embedding_available() is False
    assert llm_client.embedding_available(refresh=True) is False
    llm_client.start_embedding_probe()
    assert no_client == [], "꺼져 있는데 클라이언트를 만들었습니다"


def test_꺼져_있으면_embed_가_부르지_않고_사유를_말한다(
    real_functions: None, no_client: list[str]
) -> None:
    with pytest.raises(llm_client.LLMUnavailableError) as caught:
        llm_client.embed(["확인"])
    assert "꺼져" in str(caught.value), str(caught.value)
    assert no_client == []


def test_켜면_비로소_부른다(real_functions: None, embedding_live_on: None) -> None:
    """이 검사가 없으면 「아무것도 안 하는 코드」도 위 셋을 통과한다."""
    calls: list[list[str]] = []

    class _Response:
        data = [type("Item", (), {"embedding": [1.0, 0.0]})()]

    class _Embeddings:
        def create(self, *, model: str, input: list[str]):  # noqa: A002 — SDK 이름 그대로
            calls.append(input)
            return _Response()

    class _Client:
        embeddings = _Embeddings()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(llm_client, "_client", lambda **_kw: _Client())
        # 기록은 다음 검사에서 따로 잰다. 여기서는 저장소의 누계 파일을 건드리지 않는 것만 본다.
        mp.setattr(llm_client, "note_usage", lambda **_kw: None)
        vectors = llm_client.embed(["확인"])

    assert calls == [["확인"]]
    assert vectors == [[1.0, 0.0]]
    assert llm_client.embedding_live_enabled() is True


# ---------------------------------------------------------------------------
# 2) 호출을 적는다 (§4-A-3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def usage_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """누계 기록을 tmp 로 돌린다. 저장소의 `llm_usage.jsonl`(2줄)은 건드리지 않는다."""
    path = tmp_path / "llm_usage.jsonl"
    monkeypatch.setattr(llm_client, "USAGE_LOG", path)
    return path


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_성공한_임베딩이_기록에_남는다(
    real_functions: None, embedding_live_on: None, usage_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Client:
        class embeddings:  # noqa: N801 — SDK 모양 그대로
            @staticmethod
            def create(*, model: str, input: list[str]):  # noqa: A002
                return type("R", (), {"data": [type("I", (), {"embedding": [1.0]})() for _ in input]})()

    monkeypatch.setattr(llm_client, "_client", lambda **_kw: _Client())

    llm_client.embed(["가나다", "라마"])

    rows = _lines(usage_log)
    assert len(rows) == 1, rows
    assert rows[0]["kind"] == "embedding"
    assert rows[0]["calls"] == 1, "요청 한 번이 한 줄이다"
    assert rows[0]["texts"] == 2
    assert rows[0]["chars"] == 5, "문자 수까지 적는다 — 돈이 거기서 나온다"
    assert rows[0]["result"] == "ok"


def test_실패한_임베딩도_기록에_남고_사유가_적힌다(
    real_functions: None, embedding_live_on: None, usage_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실패를 적는 것만으로 다음 `credit_ok()` 가 닫힌다 — 마지막 줄을 읽기 때문이다."""

    class _Rejected(Exception):
        status_code = 429
        code = None

    class _Client:
        class embeddings:  # noqa: N801
            @staticmethod
            def create(*, model: str, input: list[str]):  # noqa: A002
                raise _Rejected("quota")

    monkeypatch.setattr(llm_client, "_client", lambda **_kw: _Client())

    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.embed(["확인"])

    rows = _lines(usage_log)
    assert len(rows) == 1
    assert rows[0]["kind"] == "embedding"
    assert "크레딧" in rows[0]["result"], rows[0]["result"]
    assert llm_client._last_usage_was_rejected() is True


def test_기록을_못_남겨도_임베딩_결과는_그대로다(
    real_functions: None, embedding_live_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """기록은 근거일 뿐이다. 이것 때문에 화면이 멈추면 안 된다."""
    # 파일을 만들 수 없는 자리를 준다 (파일 아래의 하위 경로).
    blocked = tmp_path / "file.txt"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setattr(llm_client, "USAGE_LOG", blocked / "nested" / "usage.jsonl")

    class _Client:
        class embeddings:  # noqa: N801
            @staticmethod
            def create(*, model: str, input: list[str]):  # noqa: A002
                return type("R", (), {"data": [type("I", (), {"embedding": [1.0]})()]})()

    monkeypatch.setattr(llm_client, "_client", lambda **_kw: _Client())

    assert llm_client.embed(["확인"]) == [[1.0]]


# ---------------------------------------------------------------------------
# 3) SEMANTIC_FIT — 벡터가 있어도 점수에 쓰지 않는다
# ---------------------------------------------------------------------------

#: 「디지털·데이터·바우처」가 걸리는 제목. 키워드 셈이 0.833 이다 (test_semantic_fit_wiring 과 같은 값).
PROGRAM_TITLE = "디지털 전환 데이터 활용 바우처"


def _program():
    return bizinfo_service.map_program(
        {
            "pblancId": "SWITCH1",
            "pblancNm": PROGRAM_TITLE,
            "jrsdInsttNm": "테스트기관",
            "bsnsSumryCn": "중소기업의 데이터 활용을 지원하는 바우처 사업입니다.",
            "pldirSportRealmLclasCodeNm": "기술",
            "reqstBeginEndDe": "20260901 ~ 20261231",
        }
    )


@pytest.fixture()
def vectors_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """이 공고와 회사 문구의 벡터를 **전부** 캐시에 심는다 (합성 벡터).

    실제 사고 상태의 재현이다 — 디스크에 벡터가 이미 있고 바깥을 부를 필요가 없다.
    그래서 `EMBEDDING_LIVE` 가 꺼져 있어도 의미 유사도가 나올 수 있는 상태다.
    """
    monkeypatch.setattr(semantic_matcher, "CACHE_DIR", tmp_path / "embeddings")
    monkeypatch.setattr(semantic_matcher, "ALLOW_SYNTHETIC_VECTORS", True)
    recommendation._PHRASE_MEMO = None

    program = _program()
    from app.services import company_service

    profile = company_service.load_profile(get_settings().default_organization_id)
    phrases = list(
        recommendation.company_phrases(
            business_domains=profile.business_domains,
            target_clients=profile.target_clients,
            certifications=profile.certifications,
        )
    )
    notice = semantic_matcher.notice_text(title=program.title, summary=program.summary)

    # 공고와 첫 문구를 **거의 같은 방향**으로 둔다 → 코사인이 1 에 가깝고 점수가 천장(1.0)이다.
    # 키워드 값 0.833 과 확실히 다른 값이어야 「어느 경로로 냈는지」가 숫자로 갈린다.
    semantic_matcher.store_cached(notice, [1.0, 0.0, 0.0], synthetic=True)
    for index, phrase in enumerate(phrases):
        vector = [1.0, 0.0, 0.0] if index == 0 else [0.0, 1.0, 0.0]
        semantic_matcher.store_cached(phrase, vector, synthetic=True)
    yield program
    recommendation._PHRASE_MEMO = None


def _domain(fit) -> object:
    return next(c for c in fit.components if c.key == "domain")


def test_꺼져_있으면_벡터가_있어도_키워드_값이다(vectors_on_disk) -> None:
    """**여기가 이번 회차의 핵심이다.** 캐시를 지우지 않고도 숫자가 고정돼야 한다."""
    fit = bizinfo_service.support_fit(vectors_on_disk)

    domain = _domain(fit)
    assert domain.score == 0.833, "의미 유사도가 점수에 섞였습니다"
    assert domain.label == "사업영역 낱말"
    assert fit.method == bizinfo_service.KEYWORD_FIT_METHOD
    assert "유사도" not in domain.reason, domain.reason


def test_켜면_같은_벡터로_유사도_값이_된다(vectors_on_disk, semantic_fit_on: None) -> None:
    """꺼짐 검사가 「벡터를 못 읽어서」 통과한 것이 아님을 여기서 가른다."""
    fit = bizinfo_service.support_fit(vectors_on_disk)

    domain = _domain(fit)
    assert domain.score == 1.0, domain.reason
    assert domain.label == "사업영역 적합도"
    assert fit.method == bizinfo_service.SEMANTIC_FIT_METHOD
    # 키워드 사유를 **지우지 않고** 함께 남긴다 — 두 근거를 모두 읽어야 점수를 믿을 수 있다.
    assert domain.reason.startswith("맞는 낱말: 디지털")
    assert "유사도" in domain.reason


def test_꺼져_있으면_사유에_왜_안_썼는지_적는다(vectors_on_disk) -> None:
    """「키가 없어서」가 아니다. 꺼 둔 것과 없는 것은 다른 사실이다."""
    result = semantic_matcher.match(notice="생성형 AI 활용 실무교육 운영", phrases=["AI 활용 교육"])

    assert result.method == "KEYWORD" and result.fit_score is None
    assert "꺼 두어" in result.reason, result.reason


def test_벡터가_절반만_있으면_쓰지_않는다(vectors_on_disk, semantic_fit_on: None) -> None:
    """전부 있거나, 전부 없거나다 (§4-B-2).

    일부만 재면 「캐시에 있던 문구」만 후보가 되어 가장 가까운 문구가 뒤바뀐다 — 순위가
    캐시 상태에 따라 달라진다. 켜 놓아도 이 규칙은 그대로다.
    """
    fit = semantic_matcher.match(
        notice=semantic_matcher.notice_text(title=vectors_on_disk.title, summary=vectors_on_disk.summary),
        phrases=["AI 활용 교육", "캐시에 없는 문구 " + "x" * 20],
    )

    assert fit.method == "KEYWORD" and fit.fit_score is None
