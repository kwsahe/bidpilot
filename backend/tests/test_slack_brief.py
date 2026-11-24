"""평일 아침 슬랙 브리핑(2.6.0) — 글 만들기 · 언제 보낼까 · 보내기(가짜 전송 · 네트워크 0) · 주소가 로그에 새지 않는다."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.services import auto_collect
from app.services import slack_brief_service as slack
from tests.test_round37_brief import NOW, item, listing

HOOK = "https://hooks.slack.com/services/T000/B000/secretsecret"
KST = timezone(timedelta(hours=9))


def _settings(url: str = HOOK, frontend: str = "https://bidpilot.example.kr") -> SimpleNamespace:
    return SimpleNamespace(slack_webhook_url=url, default_organization_id="org-sample", frontend_url=frontend)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(slack, "SENT_FILE", tmp_path / "slack_brief.json")
    monkeypatch.setattr(slack, "get_settings", lambda: _settings())


def _blocks_text(payload: dict[str, Any]) -> str:
    out = []
    for block in payload["blocks"]:
        out.append((block.get("text") or {}).get("text") or " ".join(e["text"] for e in block.get("elements") or []))
    return "\n".join(out)


def test_글은_브리핑과_같은_고르기에_공고명을_이스케이프하고_확률이_아님을_적는다() -> None:
    rows = [
        item(1, title="AI 교육 <운영> & 컨설팅", detail_url="https://example.invalid/1"),
        item(2, gate="CHECK", group="조건부", detail_url="javascript:alert(1)"),
        item(3, source="bizinfo", group="신규+여유"),
        item(4, gate="FAIL", group="제외"),
    ]
    payload = slack.build_message(listing(rows), now=NOW)
    text = _blocks_text(payload)
    assert payload["blocks"][0]["type"] == "header" and "주식회사 샘플에듀" in payload["blocks"][0]["text"]["text"]
    assert "AI 교육 &lt;운영&gt; &amp; 컨설팅" in text and "<운영>" not in text  # 바깥 글은 이스케이프
    assert "<https://example.invalid/1|" in text
    assert "javascript:" not in text  # https 가 아닌 주소는 링크로 싣지 않는다
    assert "시험 사업 4" not in text  # 제외 공고는 TOP 에 없다
    assert "지원금" in text and "시험 사업 3" in text
    assert "낙찰 · 선정 확률이 아닙니다" in text and "<https://bidpilot.example.kr/opportunities|BidPilot 사업기회>" in text
    assert all(len(b.get("text", {}).get("text", "")) <= 3000 for b in payload["blocks"])
    assert payload["text"].startswith("오늘 브리핑 — 주식회사 샘플에듀")


def test_마감_칸은_마감을_두_번_쓰지_않는다() -> None:
    line = slack.item_line(1, item(1), NOW.astimezone(KST).date())
    assert "마감 마감" not in line and " · 마감 " in line and "일 · *" in line


def _at(hour: int, *, day: int = 13) -> datetime:
    """2026-11-13(금) hour:00 KST."""
    return datetime(2026, 11, day, hour, 0, tzinfo=KST).astimezone(timezone.utc)


def test_언제_보낼까(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_collect, "attempts_today", lambda now: [])
    assert slack.due(_at(8, day=14)) == (False, "토요일 — 평일 아침에만 보냅니다")
    assert slack.due(_at(7))[0] is False and "아직 받지 못함" in slack.due(_at(7))[1]
    assert slack.due(_at(11)) == (True, None)  # 마지막 시도 — 받지 못했어도 그 사실과 함께
    monkeypatch.setattr(auto_collect, "attempts_today", lambda now: [(now, True)])
    assert slack.due(_at(7)) == (True, None)
    slack.mark_sent(_at(7))
    assert slack.due(_at(9)) == (False, "오늘 이미 보냄")
    assert slack.due(_at(7, day=16))[0] is True  # 다음 평일(월)


def _transport(status: int = 200, body: str = "ok", seen: list[Any] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handle)


def test_보내기_성공과_실패_글에_주소가_없다() -> None:
    seen: list[Any] = []
    slack.send({"text": "t", "blocks": []}, HOOK, transport=_transport(seen=seen))
    assert seen == [{"text": "t", "blocks": []}]
    with pytest.raises(slack.SlackBriefError) as gone:
        slack.send({"text": "t"}, HOOK, transport=_transport(404, "no_service"))
    assert "404 no_service" in str(gone.value) and "hooks.slack.com" not in str(gone.value)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(slack.SlackBriefError) as down:
        slack.send({"text": "t"}, HOOK, transport=httpx.MockTransport(boom))
    assert "ConnectError" in str(down.value) and "secretsecret" not in str(down.value)
    assert down.value.__cause__ is None and down.value.__suppress_context__  # 원문 예외(주소 든 글)를 달고 가지 않는다


def test_슬랙_주소가_아니면_보내지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(slack, "get_settings", lambda: _settings(url="https://evil.example.com/hook"))
    row = asyncio.run(slack.run(_at(8)))
    assert row["보냄"] is False and row["실패"] is True and "hooks.slack.com" in row["사유"]
    monkeypatch.setattr(slack, "get_settings", lambda: _settings(url=""))
    row = asyncio.run(slack.run(_at(8)))
    assert row["보냄"] is False and "꺼 둠" in row["사유"] and "실패" not in row


def test_실행은_하루_한_번_보내고_로그_줄에_주소를_싣지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    async def fake_listing(organization_id: str, now: datetime) -> Any:
        return listing([item(1), item(3, source="bizinfo", group="신규+여유")])

    monkeypatch.setattr(slack, "listing_for", fake_listing)
    monkeypatch.setattr(slack, "send", lambda payload, url, **_: sent.append((payload, url)))
    monkeypatch.setattr(auto_collect, "attempts_today", lambda now: [(now, True)])
    first = asyncio.run(slack.run(_at(7)))
    assert first["보냄"] is True and len(sent) == 1 and sent[0][1] == HOOK
    assert HOOK not in json.dumps(first, ensure_ascii=False)
    again = asyncio.run(slack.run(_at(9)))
    assert again == {"시각": _at(9).isoformat(), "보냄": False, "사유": "오늘 이미 보냄"} and len(sent) == 1
    forced = asyncio.run(slack.run(_at(9), force=True))  # 시험 보내기 — 하루 한 번 검사를 건너뛰고, 보낸 날은 그대로
    assert forced["보냄"] is True and len(sent) == 2
    preview = asyncio.run(slack.run(_at(9), send_it=False))  # 글만 — 주소 · 보낸 날과 상관없이
    assert preview["보냄"] is False and preview["글"]["blocks"] and len(sent) == 2


def test_보낸_날_파일이_깨져도_멈추지_않는다(tmp_path: Any) -> None:
    for broken in ("{깨진", "[1, 2]", '"문자열"'):
        slack.SENT_FILE.write_text(broken, encoding="utf-8")
        assert slack.sent_on() is None and slack.precheck(_at(8)) is None


def test_칸_글은_줄_단위로_자른다() -> None:
    long = [f"{n}. <https://example.invalid/{'x' * 400}|공고 {n}>" for n in range(12)]
    text = slack._fit(long)
    assert len(text) <= slack.SECTION_LIMIT and text.endswith("줄")
    assert all(line.endswith(">") or line.startswith("…외") for line in text.split("\n"))  # 링크 가운데서 끊지 않음


def _script(monkeypatch: pytest.MonkeyPatch) -> Any:
    import importlib.util
    from pathlib import Path

    for gate in ("G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "KEYWORD_SEARCH_LIVE"):
        monkeypatch.setenv(gate, "0")  # 스크립트가 import 때 고치는 값 — 시험이 끝나면 되돌린다
    path = Path(__file__).resolve().parents[2] / "scripts" / "send_slack_brief.py"
    spec = importlib.util.spec_from_file_location("send_slack_brief", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_cron_은_값싼_검사를_받기_기다림보다_먼저_하고_마지막_시도는_보낸다(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _script(monkeypatch)
    waited: list[int] = []
    monkeypatch.setattr(script, "wait_for_collect", lambda: waited.append(1) or False)  # 받기가 15분 넘게 도는 중
    monkeypatch.setattr(script, "datetime", SimpleNamespace(now=lambda tz=None: _at(7)))
    slack.mark_sent(_at(7))
    assert script.scheduled_skip(_at(7)) == {"시각": _at(7).isoformat(), "보냄": False, "사유": "오늘 이미 보냄"} and not waited
    slack.SENT_FILE.unlink()
    assert "다음 시도에 다시" in script.scheduled_skip(_at(7))["사유"] and waited  # 07:40 — 다음 시도에
    monkeypatch.setattr(script, "datetime", SimpleNamespace(now=lambda tz=None: _at(11)))
    assert script.scheduled_skip(_at(11)) is None  # 11:40 — 마지막 시도라 받는 중이어도 보낸다
    monkeypatch.setattr(slack, "get_settings", lambda: _settings(url=""))
    waited.clear()
    assert script.scheduled_skip(_at(7)) is None and not waited  # 꺼 둠은 `run` 이 한 줄로 — 기다리지 않는다
