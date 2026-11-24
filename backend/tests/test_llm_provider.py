"""완성 공급자 스위치 — OpenAI · xAI(Grok) (25차 · prompt_15 §4-A).

담당자 질문: 「사업계획서 초안 — grok 무료 API로 연결해서 작성시킬 수 있는지?」
xAI 는 OpenAI 호환 주소(`https://api.x.ai/v1`)라 같은 SDK 로 부른다. 여기서 재는 것:

- **문이 둘이다** — 임베딩(`is_configured`)은 늘 OpenAI 키, 완성(`completion_configured`)은 고른 공급자 키.
- **클라이언트가 둘이다** — 완성만 공급자 주소·키·모델을 따르고 `embed()` 는 늘 OpenAI 기본 주소.
- **크레딧 판정은 같은 공급자 줄만** — OpenAI 의 429 가 xAI 를 닫지 않는다. xAI 는 모르면 닫힘.
- **시도마다 누계 한 줄** — 토큰은 적고 키는 적지 않는다. 스키마 실패 줄이 크레딧 판정을 흐리지 않는다.
- **xAI 가 받지 않는 스키마**(배열형 items · 변형 0개 enum · true/false 하위 스키마 · min/maxContains)를 부르기 전에 잡는다.

바깥은 부르지 않는다 — `openai` 모듈 자체를 가짜로 바꿔 끼운다.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.config import get_settings
from app.services import llm_client

#: conftest 가 `embed()` 를 즉시 실패로 바꿔 끼우기 전의 진짜 함수 (모듈을 읽을 때 잡아 둔다).
_REAL_EMBED = llm_client.embed

OPENAI_KEY = "sk-test-openai-DO-NOT-LOG"
XAI_KEY = "xai-test-key-DO-NOT-LOG"


class _Answer(BaseModel):
    ok: bool = True


class _FakeOpenAI:
    """OpenAI SDK 대역. 만든 인자와 보낸 요청을 기록한다."""

    made: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    replies: list[str] = []

    def __init__(self, **kwargs: Any) -> None:
        _FakeOpenAI.made.append(kwargs)
        outer = self

        class _Completions:
            @staticmethod
            def create(**request: Any):
                _FakeOpenAI.requests.append(request)
                content = _FakeOpenAI.replies.pop(0) if _FakeOpenAI.replies else '{"ok": true}'
                message = types.SimpleNamespace(content=content)
                usage = types.SimpleNamespace(
                    prompt_tokens=120,
                    completion_tokens=30,
                    completion_tokens_details=types.SimpleNamespace(reasoning_tokens=12),
                )
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=usage)

        class _Embeddings:
            @staticmethod
            def create(**request: Any):
                _FakeOpenAI.requests.append(request)
                return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.1, 0.2]) for _ in request["input"]])

        self.chat = types.SimpleNamespace(completions=_Completions())
        self.embeddings = _Embeddings()
        del outer


@pytest.fixture()
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type[_FakeOpenAI]:
    _FakeOpenAI.made = []
    _FakeOpenAI.requests = []
    _FakeOpenAI.replies = []
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))
    return _FakeOpenAI


@pytest.fixture()
def usage_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_usage.jsonl"
    monkeypatch.setattr(llm_client, "USAGE_LOG", path)
    return path


def configure(monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    """설정 인스턴스의 항목만 바꾼다 (conftest 와 같은 방식 — 캐시를 갈아 끼우지 않는다)."""
    settings = get_settings()
    defaults = {
        "llm_provider": "openai",
        "openai_api_key": "",
        "xai_api_key": "",
        "llm_model": "gpt-4.1-mini",
        "xai_model": "grok-4.7",
        "llm_base_url": "",
        "xai_reasoning_effort": "",
    }
    defaults.update(values)
    for name, value in defaults.items():
        monkeypatch.setattr(settings, name, value)


def write_usage(path: Path, *rows: dict) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def usage_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1) 문 둘 · 클라이언트 둘
# ---------------------------------------------------------------------------


def test_xai_키만_있으면_완성_문은_열리고_임베딩_문은_닫힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    assert llm_client.completion_configured() is True
    assert llm_client.is_configured() is False


def test_알_수_없는_공급자면_완성_문이_닫힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, llm_provider="grok", openai_api_key=OPENAI_KEY, xai_api_key=XAI_KEY)
    assert llm_client.completion_configured() is False


def test_xai_는_xai_주소_키_모델로_부른다(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    """루트 `.env` 에 `LLM_MODEL=gpt-4.1-mini` 가 남아 있어도 xAI 로는 grok 이름이 나간다."""
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY, openai_api_key=OPENAI_KEY, llm_model="gpt-4.1-mini")
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)

    answer = llm_client.complete_structured(system="s", user="u", schema=_Answer, purpose="plan_draft:테스트")

    assert answer.ok is True
    made = fake_sdk.made[-1]
    assert made["base_url"] == "https://api.x.ai/v1"
    assert made["api_key"] == XAI_KEY
    assert made["max_retries"] == llm_client.COMPLETION_MAX_RETRIES
    assert fake_sdk.requests[-1]["model"] == "grok-4.7"


def test_xai_모델_이름은_XAI_MODEL_을_따른다(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY, xai_model="grok-4.3")
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert fake_sdk.requests[-1]["model"] == "grok-4.3"


def test_openai_는_기본_주소와_LLM_MODEL(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="openai", openai_api_key=OPENAI_KEY, xai_api_key=XAI_KEY)
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    llm_client.complete_structured(system="s", user="u", schema=_Answer)
    made = fake_sdk.made[-1]
    assert "base_url" not in made
    assert made["api_key"] == OPENAI_KEY
    assert fake_sdk.requests[-1]["model"] == "gpt-4.1-mini"


def test_xai_인데_OpenAI_모델_이름이면_클라이언트를_만들지_않는다(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY, xai_model="gpt-4.1-mini")
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    with pytest.raises(llm_client.LLMUnavailableError) as caught:
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert "xAI 모델 이름이 아닙니다" in str(caught.value)
    assert fake_sdk.made == []
    assert usage_rows(usage_log) == []


def test_embed_는_xai_로_바꿔도_OpenAI_기본_주소(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    """xAI 에는 임베딩이 없다 — 공급자 스위치와 무관하게 OpenAI 키 · 기본 주소."""
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY, openai_api_key=OPENAI_KEY, llm_base_url="https://api.x.ai/v1")
    monkeypatch.setattr(get_settings(), "embedding_live", True)
    monkeypatch.setattr(llm_client, "embed", _REAL_EMBED)
    vectors = llm_client.embed(["문장"])
    assert vectors == [[0.1, 0.2]]
    made = fake_sdk.made[-1]
    assert made["api_key"] == OPENAI_KEY
    assert "x.ai" not in str(made.get("base_url", ""))


# ---------------------------------------------------------------------------
# 2) 크레딧 판정 — 같은 공급자 줄만
# ---------------------------------------------------------------------------

XAI_OK = {"at": "2026-10-01T00:00:00Z", "kind": "completion", "provider": "xai", "model": "grok-4.7", "calls": 1, "result": "ok"}
OPENAI_429 = {"at": "2026-10-01T00:01:00Z", "kind": "embedding_probe", "calls": 1, "result": "LLMUnavailableError(429)"}


def test_xai_성공_줄_뒤_OpenAI_429_여도_xai_는_열리고_openai_는_닫힌다(
    monkeypatch: pytest.MonkeyPatch, usage_log: Path
) -> None:
    write_usage(usage_log, XAI_OK, OPENAI_429)
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY, openai_api_key=OPENAI_KEY)
    assert llm_client.credit_ok() is True
    configure(monkeypatch, llm_provider="openai", xai_api_key=XAI_KEY, openai_api_key=OPENAI_KEY)
    assert llm_client.credit_ok() is False


def test_xai_줄이_없으면_모르므로_닫히고_충전_확인이면_열린다(monkeypatch: pytest.MonkeyPatch, usage_log: Path) -> None:
    write_usage(usage_log, OPENAI_429)
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    monkeypatch.setattr(llm_client, "_embedding_ok", True)  # OpenAI 탐침 결과는 xAI 를 말하지 못한다
    assert llm_client.credit_ok() is False
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    assert llm_client.credit_ok() is True


# ---------------------------------------------------------------------------
# 3) 누계 기록 — 시도마다 한 줄 · 키 없음
# ---------------------------------------------------------------------------


def test_꺼져_있으면_클라이언트_0_누계_0줄(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert fake_sdk.made == []
    assert usage_rows(usage_log) == []


def test_성공_한_번이면_한_줄_토큰은_적고_키는_적지_않는다(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    llm_client.complete_structured(system="s", user="u", schema=_Answer, purpose="plan_draft:추진 계획")

    rows = usage_rows(usage_log)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "completion" and row["provider"] == "xai" and row["model"] == "grok-4.7"
    assert row["purpose"] == "plan_draft:추진 계획" and row["result"] == "ok"
    assert (row["prompt_tokens"], row["completion_tokens"], row["reasoning_tokens"]) == (120, 30, 12)
    text = usage_log.read_text(encoding="utf-8")
    assert XAI_KEY not in text and OPENAI_KEY not in text


def test_검증_실패_뒤_성공이면_두_줄이고_크레딧_판정은_그대로(
    monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    monkeypatch.setattr(get_settings(), "llm_live", True)
    write_usage(usage_log, XAI_OK)
    fake_sdk.replies = ["not json", '{"ok": true}']

    llm_client.complete_structured(system="s", user="u", schema=_Answer)

    rows = usage_rows(usage_log)[1:]
    assert [r["result"] for r in rows] == ["schema_validation_failed", "ok"]
    # 검증 실패 줄을 마지막에 하나 더 붙여도 크레딧 판정은 흔들리지 않는다.
    with usage_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**rows[0]}, ensure_ascii=False) + "\n")
    assert llm_client.credit_ok() is True


def test_429_실패는_그_줄로_크레딧을_닫는다(
    monkeypatch: pytest.MonkeyPatch, usage_log: Path
) -> None:
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    monkeypatch.setattr(get_settings(), "llm_live", True)
    write_usage(usage_log, XAI_OK)

    class _RateLimitError(Exception):
        status_code = 429

    class _Client:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kw: Any):
                    raise _RateLimitError("insufficient quota")

    monkeypatch.setattr(llm_client, "_completion_client", lambda *_a, **_kw: _Client())
    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert usage_rows(usage_log)[-1]["result"].startswith("429")
    assert llm_client.credit_ok() is False


# ---------------------------------------------------------------------------
# 4) 스키마 — xAI 가 받지 않는 모양
# ---------------------------------------------------------------------------


def test_기존_구조화_출력_스키마는_xai_규칙_위반이_없다() -> None:
    from app.services.auditor_service import LlmCoverageBatch
    from app.services.eligibility_engine import _LlmQualificationBatch
    from app.schemas.proposal import GeneratedSectionDraft

    for schema in (GeneratedSectionDraft, LlmCoverageBatch, _LlmQualificationBatch):
        assert llm_client.xai_schema_violations(schema.model_json_schema()) == [], schema.__name__


def test_dict_Any_필드는_true_하위_스키마라_잡는다(monkeypatch: pytest.MonkeyPatch, fake_sdk: type[_FakeOpenAI], usage_log: Path) -> None:
    class _Loose(BaseModel):
        table: dict[str, Any]

    assert llm_client.xai_schema_violations(_Loose.model_json_schema())
    configure(monkeypatch, llm_provider="xai", xai_api_key=XAI_KEY)
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Loose)
    assert fake_sdk.made == []


def test_배열형_items_변형_0개_contains_를_잡는다() -> None:
    bad = {
        "type": "object",
        "properties": {
            "a": {"type": "array", "items": [{"type": "string"}]},
            "b": {"enum": []},
            "c": {"type": "array", "items": {"type": "string"}, "maxContains": 2},
        },
    }
    found = llm_client.xai_schema_violations(bad)
    assert any("배열형 items" in f for f in found)
    assert any("변형 0개" in f for f in found)
    assert any("maxContains" in f for f in found)
