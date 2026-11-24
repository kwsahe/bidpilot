"""완성(제안서·사업계획서·Auditor)도 스위치 아래에 있다 (ISSUE-130 · prompt_06 §4-A).

## 담당자 방침

**순위·유사도는 규칙만, AI 는 제안서·사업계획서 초안과 제출 전 점검에만.**

15차가 임베딩 문 둘(`EMBEDDING_LIVE`·`SEMANTIC_FIT`)을 만들었지만 완성 문은 `credit_ok()`
하나였다. 크레딧이 있으면 열리고 없으면 닫히는 값이라, 「AI 를 어디에 쓸 것인가」를
말할 수가 없었다. 이제 `LLM_LIVE` 가 그 방침을 말한다.

## 영원히 닫히던 자물쇠

`credit_ok()` 는 호출 누계(`llm_usage.jsonl`)의 마지막 줄이 429 면 거짓이다. 그런데 **한 번
429 가 찍히면 다시 열 길이 없었다** — 열려면 성공 기록이 있어야 하는데, 성공 기록은 부르지
않으면 생기지 않고, 닫혀 있으니 부르지 못한다. 충전을 해도 소용없었다.

두 길을 냈다: 누계에 **429 뒤 성공 줄**이 있거나, 담당자가 `LLM_CREDIT_CONFIRMED=1` 이라고
적었으면 참.

## 여기서 재는 것

문이 **기본값으로 닫혀 있는지**, 열면 실제로 열리는지, 그리고 자물쇠가 풀리는지다.
「켜면 비로소 부른다」를 함께 재지 않으면 「아무것도 안 하는 코드」도 통과한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.services import llm_client


class _Answer(BaseModel):
    ok: bool = True


@pytest.fixture()
def key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """키는 있는 상태로 둔다 — 「키가 없어서」가 아니라 «꺼져 있어서» 안 부르는 것을 잰다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)


@pytest.fixture()
def no_client(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """OpenAI 클라이언트를 **만들려고만 해도** 터진다 (임베딩 스위치 검사와 같은 방식)."""
    made: list[str] = []

    def _boom(**_kwargs: object):
        made.append("client")
        raise AssertionError("꺼져 있는데 OpenAI 클라이언트를 만들었습니다")

    monkeypatch.setattr(llm_client, "_client", _boom)
    # 25차: 완성은 공급자를 따르는 자기 클라이언트를 만든다 — 그쪽도 막는다.
    monkeypatch.setattr(llm_client, "_completion_client", _boom)
    return made


@pytest.fixture()
def usage_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """누계 기록을 tmp 로. conftest 가 이미 돌려 두지만 여기서는 **내용을 쓴다**."""
    path = tmp_path / "llm_usage.jsonl"
    monkeypatch.setattr(llm_client, "USAGE_LOG", path)
    return path


def write_usage(path: Path, *rows: dict) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


REJECTED = {"at": "2026-09-17T05:15:48Z", "kind": "embedding_probe", "calls": 1, "result": "LLMUnavailableError(429)"}
SUCCESS = {"at": "2026-09-21T06:12:49Z", "kind": "embedding", "calls": 1, "texts": 1, "chars": 2, "result": "ok"}


# ---------------------------------------------------------------------------
# 1) 기본값 — 환경변수 없이
# ---------------------------------------------------------------------------


def test_환경변수가_없으면_완성_문이_닫혀_있다() -> None:
    settings = get_settings()
    assert settings.llm_live is False
    assert settings.llm_credit_confirmed is False
    assert llm_client.llm_live_enabled() is False


def test_기본값_자체가_꺼짐이다() -> None:
    """설정 인스턴스가 아니라 **선언된 기본값**을 본다 (ISSUE-120 과 같은 방식)."""
    assert Settings.model_fields["llm_live"].default is False
    assert Settings.model_fields["llm_credit_confirmed"].default is False


def test_꺼져_있으면_클라이언트를_만들지_않는다(key_present: None, no_client: list[str]) -> None:
    """§4-A-1 — 지금 호출자 넷이 전부 규칙 경로로 가는 그 예외를 던진다."""
    with pytest.raises(llm_client.LLMUnavailableError) as caught:
        llm_client.complete_structured(system="s", user="u", schema=_Answer)

    assert "꺼져" in str(caught.value), str(caught.value)
    assert no_client == []


def test_꺼져_있으면_크레딧을_보지도_않는다(
    key_present: None, no_client: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """크레딧 확인은 기록을 읽는 일이다. 꺼져 있으면 그것조차 할 이유가 없다."""
    asked: list[str] = []
    monkeypatch.setattr(llm_client, "credit_ok", lambda: asked.append("credit") or True)

    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)

    assert asked == [], "꺼져 있는데 크레딧을 확인했습니다"


def test_켜면_비로소_부른다(key_present: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """이 검사가 없으면 「아무것도 안 하는 코드」도 위 셋을 통과한다."""
    monkeypatch.setattr(get_settings(), "llm_live", True)
    monkeypatch.setattr(llm_client, "credit_ok", lambda: True)
    calls: list[str] = []

    class _Client:
        class chat:  # noqa: N801 — SDK 모양 그대로
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs: object):
                    calls.append("create")
                    message = type("M", (), {"content": '{"ok": true}'})()
                    return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    monkeypatch.setattr(llm_client, "_completion_client", lambda *_a, **_kw: _Client())

    answer = llm_client.complete_structured(system="s", user="u", schema=_Answer)

    assert calls == ["create"]
    assert answer.ok is True


# ---------------------------------------------------------------------------
# 2) 세 경로가 **같은 문**을 지난다 (§4-A-4)
# ---------------------------------------------------------------------------


def test_세_경로가_각자_확인하지_않고_한_문을_지난다(
    key_present: None, no_client: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """제안서 · 사업계획서(=Auditor 와 같은 래퍼) · 자격 보강 — 넷 다 `complete_structured` 다.

    각 경로가 자기 자리에서 스위치를 확인하면 새로 생기는 경로가 반드시 하나 빠진다.
    그래서 여기서는 **호출자가 몇이든 문은 하나**임을 재고, 그 문이 닫혀 있을 때
    호출자들이 규칙 경로로 가는지(예외를 삼키는지)를 본다.
    """
    from app.services import auditor_service, eligibility_engine, proposal_service

    sources = [
        proposal_service.__file__,
        auditor_service.__file__,
        eligibility_engine.__file__,
    ]
    for path in sources:
        text = Path(path).read_text(encoding="utf-8")
        assert "llm_client.complete_structured(" in text, path
        # 자기 자리에서 스위치를 다시 보지 않는다 — 문은 하나다.
        assert "llm_live_enabled" not in text, f"{path}: 스위치를 여기서도 본다"

    # 문이 닫혀 있으면 클라이언트가 만들어지지 않는다 (호출자가 무엇이든).
    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert no_client == []


# ---------------------------------------------------------------------------
# 3) 자물쇠 — 429 뒤에 다시 여는 길 (§4-A-2)
# ---------------------------------------------------------------------------


def test_429_만_있으면_거짓이다(key_present: None, usage_log: Path) -> None:
    write_usage(usage_log, REJECTED)
    assert llm_client.credit_ok() is False


def test_429_뒤에_성공_줄이_있으면_참이다(key_present: None, usage_log: Path) -> None:
    """마지막으로 알아낸 사실이 「크레딧 있음」이다."""
    write_usage(usage_log, REJECTED, SUCCESS)
    assert llm_client.credit_ok() is True


def test_성공_뒤에_다시_429_면_거짓이다(key_present: None, usage_log: Path) -> None:
    """한 방향으로만 열리면 안 된다 — 크레딧은 다시 떨어진다."""
    write_usage(usage_log, SUCCESS, REJECTED)
    assert llm_client.credit_ok() is False


def test_담당자가_충전했다고_적으면_참이다(
    key_present: None, usage_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**이것이 없으면 429 한 줄로 영원히 닫힌다.**

    다시 열려면 성공 기록이 필요한데, 성공 기록은 부르지 않으면 생기지 않고, 닫혀 있으니
    부르지 못한다. 충전을 해도 길이 없었다.
    """
    write_usage(usage_log, REJECTED)
    assert llm_client.credit_ok() is False

    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    assert llm_client.credit_ok() is True


def test_기록이_없으면_예전_길을_따른다(
    key_present: None, usage_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """한 번도 부른 적이 없으면 「모른다」다 — 이미 잰 임베딩 결과를 따른다.

    모르면 부르지 않는 쪽이 안전하다. 규칙 경로로 떨어질 뿐 화면이 멈추지 않는다.
    """
    assert not usage_log.exists()
    monkeypatch.setattr(llm_client, "_embedding_ok", None)
    assert llm_client.credit_ok() is False

    monkeypatch.setattr(llm_client, "_embedding_ok", True)
    assert llm_client.credit_ok() is True


def test_키가_없으면_무엇을_적어도_거짓이다(usage_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """충전했다고 적어도 키가 없으면 부를 수 없다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    monkeypatch.setattr(get_settings(), "llm_credit_confirmed", True)
    write_usage(usage_log, SUCCESS)

    assert llm_client.credit_ok() is False
