"""크레딧이 확인되지 않으면 LLM 을 부르지 않는다 (prompt_02 §4-B-1).

## 무엇이 틀렸나

생성 경로 여덟 곳이 전부 `llm_client.is_configured()` 를 보고 있었다. 그 함수는 키
**문자열이 있는가**만 본다. 그래서 크레딧이 0 인 지금도 참이고, 「제안서 섹션 생성」을
누르면 **429 실호출**이 났다 — `data/private/llm_usage.jsonl` 의 두 줄이 그 흔적이다.

`embedding_available()` 로 바꿀 수도 없다. 그쪽은 아직 잰 적이 없으면 **탐침을 띄우는데**,
그 탐침 자체가 LLM 호출이라 「LLM 0회」를 어긴다.

## 여기서 지키는 약속

1. `credit_ok()` 는 **아무것도 부르지 않는다** — 이미 있는 것만 읽는다.
2. 모르면 **거짓**이다. 규칙 경로로 떨어질 뿐 화면이 멈추지 않으므로 그쪽이 안전하다.
3. 막는 자리는 `complete_structured` **하나**다. 호출자가 여덟이고 앞으로 더 느는데
   각자 확인하게 하면 반드시 하나가 빠진다.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services import llm_client


class _Out(BaseModel):
    text: str


@pytest.fixture(autouse=True)
def _reset_embedding_state():
    """테스트가 서로의 캐시 상태를 물려받지 않게 한다."""
    with llm_client._embedding_lock:  # noqa: SLF001 — 이 모듈의 내부 상태를 직접 되돌린다
        before = llm_client._embedding_ok  # noqa: SLF001
    yield
    with llm_client._embedding_lock:  # noqa: SLF001
        llm_client._embedding_ok = before  # noqa: SLF001


def _set_embedding(ok: bool | None) -> None:
    with llm_client._embedding_lock:  # noqa: SLF001
        llm_client._embedding_ok = ok  # noqa: SLF001


def test_키가_없으면_거짓(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    assert llm_client.credit_ok() is False


def test_마지막_호출이_429_면_거짓(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    _set_embedding(True)  # 임베딩은 「가능」인데도
    log = tmp_path / "llm_usage.jsonl"
    log.write_text(
        '{"at": "2026-09-17T05:15:48Z", "calls": 1, "result": "LLMUnavailableError(429)"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "USAGE_LOG", log)
    assert llm_client.credit_ok() is False, "마지막으로 알아낸 사실이 「크레딧 없음」이다"


def test_잰_적이_없으면_거짓(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """모르면 부르지 않는다. 여기서 참을 돌려주면 탐침 없이 429 를 맞는다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "none.jsonl")
    _set_embedding(None)
    assert llm_client.credit_ok() is False


def test_이미_가능으로_잰_적이_있으면_참(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "none.jsonl")
    _set_embedding(True)
    assert llm_client.credit_ok() is True


def test_credit_ok_는_탐침을_띄우지_않는다(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """이것이 `embedding_available()` 과 다른 점이고, 이 함수를 따로 만든 이유다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "none.jsonl")
    _set_embedding(None)

    called: list[str] = []
    monkeypatch.setattr(llm_client, "start_embedding_probe", lambda: called.append("probe"))
    monkeypatch.setattr(llm_client, "refresh_embedding_availability", lambda: called.append("refresh"))

    llm_client.credit_ok()
    assert called == [], f"탐침을 띄웠다: {called}"


def test_크레딧이_없으면_LLM_을_아예_부르지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """생성 경로가 어디든 나가는 문은 `complete_structured` 하나다."""
    monkeypatch.setattr(llm_client, "credit_ok", lambda: False)

    made: list[str] = []
    monkeypatch.setattr(llm_client, "_client", lambda: made.append("client"))
    monkeypatch.setattr(llm_client, "_completion_client", lambda *_a, **_kw: made.append("client"))

    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Out)

    assert made == [], "SDK 클라이언트를 만들지도 않아야 한다 — 만들면 곧 호출이다"


def test_입찰_제안서_경로도_같은_문을_지난다(monkeypatch: pytest.MonkeyPatch) -> None:
    """「제안서 섹션 생성」이 크레딧 0 에서 **호출 없이** 규칙 초안을 그대로 둔다.

    이 경로가 이번 수정의 출발점이다 — 예전에는 키만 있으면 그대로 나가 429 를 맞았다.
    """
    from app.schemas.requirement import Requirement
    from app.services import proposal_service

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)  # 키는 있다
    monkeypatch.setattr(llm_client, "credit_ok", lambda: False)  # 크레딧만 없다
    made: list[str] = []
    monkeypatch.setattr(llm_client, "_client", lambda: made.append("client"))
    monkeypatch.setattr(llm_client, "_completion_client", lambda *_a, **_kw: made.append("client"))

    requirement = Requirement(
        id="r1",
        procurement_id="p1",
        requirement_id="REQ-001",
        category="과업",
        title="교육 운영 횟수",
        requirement_type="mandatory",
        content="교육은 총 20회 이상 운영해야 한다.",
        page=17,
        source_text="교육 운영은 총 20회 이상 실시한다.",
        status="unmatched",
    )
    draft = proposal_service._Draft(  # noqa: SLF001 — 이 함수의 입력 타입이다
        requirement=requirement,
        text="교육을 20회 이상 운영합니다.",
        grounding_type="RFP_GROUNDED",
        evidence=None,
        needs_review=False,
        candidates=[],
    )

    assert proposal_service.refine_with_llm([draft]) is False
    assert made == [], "SDK 클라이언트를 만들지도 않아야 한다"
    assert draft.text == "교육을 20회 이상 운영합니다.", "규칙 문장이 그대로 남는다"
