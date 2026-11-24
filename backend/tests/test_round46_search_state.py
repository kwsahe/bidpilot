"""46차 H5 — 회사 근거 AI 검색이 지금 꺼져 있나는 서버 상태 값 하나(`evidence_service.ai_search_off`)로 정하고 응답에 붙인다. 호출 없음."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.schemas.organization import AnalysisContext
from app.services import evidence_adoption_service, evidence_service, llm_client

CTX = AnalysisContext(organization_id=get_settings().default_organization_id, evidence_scope="internal")


@pytest.mark.parametrize(("index", "configured", "off"), [([], True, True), (["chunk"], False, True), (["chunk"], True, False)])
def test_꺼짐은_색인_없음이나_AI_설정_없음(monkeypatch: pytest.MonkeyPatch, index: list, configured: bool, off: bool) -> None:
    monkeypatch.setattr(evidence_service, "load_index", lambda **_: index)
    monkeypatch.setattr(llm_client, "is_configured", lambda: configured)
    assert evidence_service.ai_search_off(CTX) is off
    # 옛 사유 글은 그대로 두고 지금 상태만 붙인다 · 요약이 없으면 None 그대로
    old = {"note": "AI 검색 설정이 없어 회사 수행근거 연결을 건너뜁니다.", "real_evidence_used": False}
    assert evidence_service.with_search_state(old, CTX) == {**old, "ai_search_off": off}
    assert evidence_service.with_search_state(None, CTX) is None


def test_원장_보기도_같은_한_곳(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_off(context: AnalysisContext) -> bool:
        calls.append(context.organization_id)
        return False

    monkeypatch.setattr(evidence_service, "ai_search_off", fake_off)
    monkeypatch.setattr(evidence_adoption_service, "load", lambda *_: {})

    class _Parsed:
        requirements: list = []

    from app.services import rfp_parser

    monkeypatch.setattr(rfp_parser, "load_generated", lambda _pid: _Parsed())
    view = evidence_adoption_service.ledger_view("g2b-R26BK01699556-000", CTX)
    assert view["ai_search_off"] is False and calls == [CTX.organization_id] and view["candidates"] == []
