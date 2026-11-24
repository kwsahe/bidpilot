"""무거운 동기 작업이 이벤트 루프 스레드에서 돌지 않는다 (ISSUE-031 · TASK-020).

## 무엇을 막는가

문서 파싱은 동기·CPU 작업이다(PDF·HWP 수십 페이지, 30MB 첨부면 수십 초).
그것을 `async def` 핸들러 안에서 그대로 돌리면 **그동안 이벤트 루프가 멈춘다** —
그 요청 하나가 아니라 서버에 들어오는 다른 모든 요청이 함께 선다.

컨테이너·nginx 는 `/health` 로 살아 있는지 본다. 담당자가 첨부를 올리는 동안
헬스체크가 실패하면, 멀쩡히 일하고 있는 서버가 죽은 것으로 판정돼 재시작된다
(그러면 그 업로드도 함께 죽는다).

## 왜 「/health 응답 시간」으로 재지 않았나

처음에는 업로드를 띄워 두고 `/health` 가 1초 안에 오는지 쟀다. **그 측정은 고치기
전 코드에서도 통과했다.** 테스트가 한 스레드·한 이벤트 루프 안에서 도는데, 루프가
막히면 「기다리는 것」 자체가 먼저 막혀서 결국 풀린 뒤에 재기 때문이다 —
측정이 자기가 재려는 것에 막혀 버린다.

그래서 성질 자체를 직접 고정한다: **무거운 동기 호출은 이벤트 루프 스레드가 아닌
곳에서 일어나야 한다.** 스레드로 넘기지 않으면 이 테스트가 곧바로 깨진다.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import document_extractor

#: conftest 가 실제 소켓을 막으려고 `AsyncClient.get` 을 통째로 갈아 끼운다. 여기서는 소켓을
#: 쓰지 않고 ASGI transport 로 이 앱만 부르므로, 진짜 구현을 import 시점에 붙잡아 둔다.
_REAL_ASYNC_GET = AsyncClient.get

UPLOAD_FORM = {"procurement_id": "synthetic-rfp-0001", "use_llm": "false"}
UPLOAD_FILE = {"file": ("제안서.pdf", b"%PDF-1.4 fake", "application/pdf")}


@pytest.mark.anyio
async def test_문서_추출은_이벤트_루프_스레드에서_돌지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    ran_on: dict[str, int] = {}

    def record_thread(*_args, **_kwargs):
        ran_on["ident"] = threading.get_ident()
        raise document_extractor.DocumentExtractionError("테스트용 추출 중단")

    monkeypatch.setattr(document_extractor, "extract_document", record_thread)
    monkeypatch.setattr(AsyncClient, "get", _REAL_ASYNC_GET)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auditor/run/upload", data=UPLOAD_FORM, files=UPLOAD_FILE, timeout=30.0
        )

    # 추출은 일부러 실패시켰다. 여기서 보는 것은 «어디서 돌았는가»뿐이다.
    assert response.status_code == 422
    assert "ident" in ran_on, "추출이 아예 불리지 않았다 — 테스트가 경로를 잘못 짚었다"
    assert ran_on["ident"] != loop_thread, (
        "문서 추출이 이벤트 루프 스레드에서 돌았다 — 그동안 /health 를 포함한 모든 요청이 "
        "멈춘다. run_in_threadpool 로 넘겨야 한다."
    )


@pytest.mark.anyio
async def test_추출이_도는_동안에도_health가_200이다(monkeypatch: pytest.MonkeyPatch) -> None:
    """성질이 지켜지면 실제 응답도 온다 — 두 가지를 함께 본다."""

    def slow(*_args, **_kwargs):
        time.sleep(0.5)
        raise document_extractor.DocumentExtractionError("테스트용 추출 중단")

    monkeypatch.setattr(document_extractor, "extract_document", slow)
    monkeypatch.setattr(AsyncClient, "get", _REAL_ASYNC_GET)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload = asyncio.create_task(
            client.post("/api/auditor/run/upload", data=UPLOAD_FORM, files=UPLOAD_FILE, timeout=30.0)
        )
        assert (await client.get("/health", timeout=30.0)).status_code == 200
        assert (await upload).status_code == 422


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
