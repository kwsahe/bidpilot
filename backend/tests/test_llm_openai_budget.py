"""OpenAI · xAI 경로의 시간 상한 (27차 R26-13) — 시도마다 남은 시간만 · 마감이 있으면 SDK 재시도 끔.

26차에 Claude CLI 경로는 시험했지만 OpenAI SDK 경로는 테스트가 없었다. 네트워크 · 키 없이 가짜 클라이언트로 잰다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.config import get_settings
from app.services import llm_client


class _Answer(BaseModel):
    ok: bool


class _FakeClient:
    """`with_options` 로 받은 재시도 값과 `create` 에 넘어온 제한 시간을 적는다."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.options: list[dict[str, Any]] = []
        self.timeouts: list[float | None] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **kwargs: Any) -> "_FakeClient":
        self.options.append(kwargs)
        return self

    def _create(self, **kwargs: Any) -> Any:
        self.timeouts.append(kwargs.get("timeout"))
        content = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)


@pytest.fixture()
def openai_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    for name, value in {"llm_provider": "openai", "llm_live": True, "llm_model": "gpt-4.1-mini", "xai_reasoning_effort": ""}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(llm_client, "credit_ok", lambda: True)
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "llm_usage.jsonl")


def test_마감이_있으면_SDK_재시도를_끄고_시도마다_남은_시간만_쓴다(openai_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(['{"ok": "아마도"}', '{"ok": true}'])
    monkeypatch.setattr(llm_client, "_completion_client", lambda target: fake)
    ticks = [100.0, 100.0, 125.0]  # 마감 = 100 + 60 · 첫 시도 뒤 25초가 지났다
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])
    result = llm_client.complete_structured(system="s", user="u", schema=_Answer, timeout=60)
    assert result.ok is True
    assert fake.options == [{"max_retries": 0}]
    assert fake.timeouts == [60.0, 35.0]  # 스키마 재요청은 남은 35초만


def test_마감이_지나면_부르지_않고_시간_상한(openai_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(['{"ok": "아마도"}', '{"ok": true}'])
    monkeypatch.setattr(llm_client, "_completion_client", lambda target: fake)
    ticks = [100.0, 100.0, 200.0]
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])
    with pytest.raises(llm_client.LLMUnavailableError, match="시간 상한"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer, timeout=60)
    assert len(fake.timeouts) == 1


def test_마감이_없으면_SDK_설정_그대로(openai_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(['{"ok": true}'])
    monkeypatch.setattr(llm_client, "_completion_client", lambda target: fake)
    llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert fake.options == []  # 재시도 설정을 건드리지 않는다
