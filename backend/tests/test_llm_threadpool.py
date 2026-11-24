"""AI 를 부를 수 있는 핸들러는 스레드에서 — 그동안에도 `/health` 가 답한다 (26차 ISSUE-144 · prompt_16 §4-B).

Claude CLI 는 동기 `subprocess.run` 이라 한 호출에 1분 가까이 걸린다. `async` 핸들러가 그것을 이벤트 루프에서 기다리면
그동안 목록 · 다른 탭 · `/health` 가 모두 멈춘다. 여기서는 각 핸들러가 부르는 동기 서비스를 2초 잠드는 대역으로 바꾸고,
느린 요청을 보낸 뒤 1.5초 안에 `/health` 가 오는지 잰다(막히면 2초 뒤). AI 도 네트워크도 부르지 않는다.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Callable

import httpx
import pytest

from app.main import app
from app.services import auditor_service, eligibility_engine, proposal_service, rfp_parser, wording

PID = "synthetic-rfp-0001"


def _sleep_then(exc: Exception) -> Callable[..., Any]:
    def _slow(*_a, **_kw):
        time.sleep(2.0)
        raise exc
    return _slow


def _health_while(method: str, path: str, body: dict) -> float:
    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 느린 요청을 보낸 때부터 잰다 — 루프가 막히면 아래 sleep 자체가 늦게 깨므로, 그 뒤부터 재면 막힘이 안 보인다.
            started = time.monotonic()
            slow = asyncio.create_task(client.request(method, path, json=body))
            await asyncio.sleep(0.3)
            health = await client.request("GET", "/health")  # ASGI 전송 — 네트워크가 아니다
            elapsed = time.monotonic() - started
            assert health.status_code == 200
            response = await slow
            assert response.status_code == 404, response.text  # 대역이 「없음」으로 끝낸다 — 핸들러는 끝까지 돈다
            return elapsed

    return asyncio.run(scenario())


def test_제안서_섹션_생성_중에도_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proposal_service, "generate_section", _sleep_then(rfp_parser.RfpFixtureNotFoundError(PID)))
    assert _health_while("POST", "/api/proposal/generate", {"procurement_id": PID, "organization_id": "org-sample"}) < 1.5


def test_제안서_전체_생성_중에도_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proposal_service, "generate_document", _sleep_then(rfp_parser.RfpFixtureNotFoundError(PID)))
    body = {"procurement_id": PID, "organization_id": "org-sample", "use_llm": True}
    assert _health_while("POST", "/api/proposal/generate/full", body) < 1.5


def test_Auditor_실행_중에도_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auditor_service, "run_and_store", _sleep_then(rfp_parser.RfpFixtureNotFoundError(PID)))
    body = {"procurement_id": PID, "organization_id": "org-sample", "proposal_text": "제안서 초안", "use_llm": True}
    assert _health_while("POST", "/api/auditor/run", body) < 1.5


def test_자격_AI_보강_중에도_health(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sources(_pid: str):
        return None, None

    monkeypatch.setattr(eligibility_engine, "load_sources", _sources)
    monkeypatch.setattr(eligibility_engine, "company_facts_for", lambda *_a, **_kw: eligibility_engine.CompanyFacts())
    monkeypatch.setattr(eligibility_engine, "evaluate_from_sources", _sleep_then(eligibility_engine.EligibilityDataError(PID)))
    body = {"procurement_id": PID, "organization_id": "org-sample", "use_llm": True}
    assert _health_while("POST", "/api/eligibility/evaluate", body) < 1.5


# ---------------------------------------------------------------------------
# 27차 R26-03 — PDF 내보내기(Word 변환 `subprocess.run` · 최대 120초)도 스레드에서
# ---------------------------------------------------------------------------


def _slow_pdf(_payload: bytes) -> bytes:
    time.sleep(2.0)
    from app.services import proposal_export

    raise proposal_export.PdfConverterUnavailableError("PDF 변환기 없음(대역)")


def _health_while_get(path: str) -> tuple[float, int]:
    async def scenario() -> tuple[float, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = time.monotonic()
            slow = asyncio.create_task(client.request("GET", path))  # .get 은 conftest 가 막는다(네트워크 대역)
            await asyncio.sleep(0.3)
            health = await client.request("GET", "/health")
            elapsed = time.monotonic() - started
            assert health.status_code == 200
            response = await slow
            return elapsed, response.status_code

    return asyncio.run(scenario())


@pytest.fixture
def slow_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """문서 만들기까지는 가볍게 대역으로, 변환만 2초 잠든다 — 막힘이 변환에서 오는지만 잰다."""
    from app.services import bid_application_export, proposal_export

    async def _line(_pid: str) -> str:
        return "시험 공고"

    monkeypatch.setattr(proposal_export, "docx_to_pdf", _slow_pdf)
    monkeypatch.setattr(bid_application_export, "docx_to_pdf", _slow_pdf)
    monkeypatch.setattr(proposal_export, "_notice_line", _line)
    monkeypatch.setattr(proposal_export, "_evidence_index", lambda *_a, **_kw: {})
    monkeypatch.setattr(proposal_service, "load_section", lambda *_a, **_kw: object())
    monkeypatch.setattr(proposal_service, "load_document", lambda *_a, **_kw: SimpleNamespace(sections=[]))
    monkeypatch.setattr(wording, "modernize_model", lambda model: model)  # 대역 객체는 모델이 아니다(32차 옛 글 바꾸기)
    monkeypatch.setattr(proposal_export, "_refuse_stale", lambda *_a, **_kw: None)  # 44차 S2 옛 초안 검사도 대역 객체를 읽지 않게
    monkeypatch.setattr(proposal_export, "build_document", lambda *_a, **_kw: b"docx")
    monkeypatch.setattr(proposal_export, "build_full_document", lambda *_a, **_kw: b"docx")

    async def _pages(_pid: str, _view: Any) -> tuple[list, None]:
        return [], None

    async def _view(_pid: str) -> Any:
        return SimpleNamespace(notice=SimpleNamespace(id=PID, title="시험 공고"))

    monkeypatch.setattr(bid_application_export.procurement_service, "get_notice", _view)
    monkeypatch.setattr(bid_application_export, "load_identity", lambda *_a, **_kw: {})
    monkeypatch.setattr(bid_application_export, "_notice_pages", _pages)
    monkeypatch.setattr(bid_application_export, "build_draft", lambda *_a, **_kw: object())
    monkeypatch.setattr(bid_application_export, "build_document", lambda *_a, **_kw: b"docx")


@pytest.mark.parametrize(
    "path",
    [
        f"/api/proposal/{PID}/export?format=pdf&organization_id=org-sample",
        f"/api/proposal/{PID}/full/export?format=pdf&organization_id=org-sample",
        f"/api/proposal/{PID}/application/export?format=pdf&organization_id=org-sample",
    ],
)
def test_PDF_변환_중에도_health(slow_pdf: None, path: str) -> None:
    elapsed, status = _health_while_get(path)
    assert status == 503  # 대역이 「변환기 없음」으로 끝낸다 — 핸들러는 끝까지 돈다
    assert elapsed < 1.5


# ---------------------------------------------------------------------------
# 27차 R26-12 — 같은 공고 제안서 · 검사는 한 번에 하나만(판 번호 덮어쓰기 · AI 두 번)
# ---------------------------------------------------------------------------


def _second_while_first(path: str, body: dict) -> tuple[int, int]:
    async def scenario() -> tuple[int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.request("POST", path, json=body))
            await asyncio.sleep(0.4)
            second = await client.request("POST", path, json=body)
            return (await first).status_code, second.status_code

    return asyncio.run(scenario())


def test_같은_공고_제안서는_동시에_하나만(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proposal_service, "generate_section", _sleep_then(rfp_parser.RfpFixtureNotFoundError(PID)))
    first, second = _second_while_first("/api/proposal/generate", {"procurement_id": PID, "organization_id": "org-sample"})
    assert (first, second) == (404, 409)


def test_같은_공고_검사는_동시에_하나만(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auditor_service, "run_and_store", _sleep_then(rfp_parser.RfpFixtureNotFoundError(PID)))
    body = {"procurement_id": PID, "organization_id": "org-sample", "proposal_text": "제안서 초안", "use_llm": True}
    first, second = _second_while_first("/api/auditor/run", body)
    assert (first, second) == (404, 409)


def test_입력이_다른_검사는_서로_막지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """검수 C15 — 오래 걸리는 AI 점검 중 화면이 여는 순간 도는 규칙 검사(다른 초안 · 다른 방식)가 409 가 됐다."""
    monkeypatch.setattr(auditor_service, "run_and_store", _sleep_then(rfp_parser.RfpFixtureNotFoundError(PID)))

    async def scenario() -> tuple[int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ai = {"procurement_id": PID, "organization_id": "org-sample", "proposal_text": "AI 정밀 점검 초안", "use_llm": True}
            rule = {"procurement_id": PID, "organization_id": "org-sample", "proposal_text": "다른 초안", "use_llm": False}
            first = asyncio.create_task(client.request("POST", "/api/auditor/run", json=ai))
            await asyncio.sleep(0.4)
            second = await client.request("POST", "/api/auditor/run", json=rule)
            return (await first).status_code, second.status_code

    assert asyncio.run(scenario()) == (404, 404)
