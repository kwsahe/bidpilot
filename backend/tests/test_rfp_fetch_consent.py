"""27차 §3-A — 사람이 확인한 제안요청서 한 건 받기 · 입찰공고문 대체 · 첨부 목록의 캐시 표시.

네트워크를 타지 않는다: 공고 조회 · 추출 · 저장은 가짜로, 내려받기는 httpx MockTransport 로 센다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import attachment_service, document_extractor, prespec_service, procurement_service, rfp_parser

client = TestClient(app)
NOTICE_ID = "g2b-R26BK09999999-000"
G2B = "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK09999999&n="


@dataclass
class _Notice:
    id: str
    title: str
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class _View:
    notice: _Notice


@dataclass
class _Extracted:
    requirements: list[Any] = field(default_factory=list)
    candidate_count: int = 0
    truncated: bool = False


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """공고 한 건 · 받은 횟수 · 저장 결과를 담는 가짜 세계."""
    state: dict[str, Any] = {"attachments": [], "downloads": [], "stored": [], "opened": [], "item": {}, "prespecs": []}
    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    monkeypatch.setattr(prespec_service, "load_prespecs", lambda: (state["prespecs"], None))

    async def fake_get_notice(notice_id: str) -> _View:
        return _View(_Notice(notice_id, "시험 공고", {"attachments": state["attachments"], "item": state["item"]}))

    monkeypatch.setattr(procurement_service, "get_notice", fake_get_notice)

    def fake_extract(path: Path, *, file_name: str | None = None, **_: Any) -> Any:
        state["opened"].append(file_name)
        return document_extractor.ExtractedDocument(
            file_name=file_name or path.name,
            doc_format="pdf",
            pages=[document_extractor.DocumentPage(page=1, text="교육은 총 20회 이상 운영한다.")],
        )

    monkeypatch.setattr(document_extractor, "extract_document", fake_extract)
    monkeypatch.setattr(rfp_parser, "extract_with_stats", lambda notice_id, doc: _Extracted())

    def fake_store(result: Any) -> Any:
        state["stored"].append(result)
        return result

    monkeypatch.setattr(rfp_parser, "store_result", fake_store)

    original = httpx.AsyncClient.__init__

    def handler(request: httpx.Request) -> httpx.Response:
        state["downloads"].append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.4 fake")

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return state


def _parse(**extra: Any) -> httpx.Response:
    return client.post("/api/rfp/parse", json={"procurement_id": NOTICE_ID, **extra})


def test_캐시_없고_확인도_없으면_409_이고_받지_않는다(world: dict[str, Any]) -> None:
    world["attachments"] = [{"name": "제안요청서.hwp", "url": G2B + "1"}]
    response = _parse()
    assert response.status_code == 409
    assert world["downloads"] == []
    # 화면 문구에 개발자 설정 이름이 없다 (27차 §2)
    assert "ATTACHMENT_FETCH" not in response.json()["detail"]
    assert "새 공고 받기가 꺼져" in response.json()["detail"]


def test_사람이_확인하면_한_번만_받아_저장하고_분석한다(world: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    world["attachments"] = [{"name": "입찰공고문.pdf", "url": G2B + "0"}, {"name": "제안요청서.hwp", "url": G2B + "1"}]
    with caplog.at_level("INFO", logger="app.services.attachment_service"):
        response = _parse(fetch_attachment=True)
    # 받은 한 건은 로그에 공고 · 첨부 번호 · 파일명 · 바이트 · 「사람 확인」으로 남는다 (27차 §3-A-2)
    logged = [r.getMessage() for r in caplog.records if "사람 확인" in r.getMessage()]
    assert len(logged) == 1 and NOTICE_ID in logged[0] and "제안요청서.hwp" in logged[0] and "13바이트" in logged[0]
    assert response.status_code == 200, response.text
    assert len(world["downloads"]) == 1 and world["downloads"][0].endswith("n=1")
    assert attachment_service.cached_attachment(NOTICE_ID, 1, "제안요청서.hwp") is not None
    assert response.json()["document_role"] == "rfp"
    assert len(world["stored"]) == 1

    # 다시 눌러도 받지 않는다 — 이제 로컬에 있다
    again = _parse(fetch_attachment=True)
    assert again.status_code == 200
    assert len(world["downloads"]) == 1


def test_캐시에_있으면_확인이_있어도_받지_않는다(world: dict[str, Any]) -> None:
    world["attachments"] = [{"name": "제안요청서.hwp", "url": G2B + "1"}]
    target = attachment_service.cache_path(NOTICE_ID, 0, "제안요청서.hwp")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4 cached")
    assert _parse(fetch_attachment=True).status_code == 200
    assert _parse().status_code == 200
    assert world["downloads"] == []


def test_허용_밖_도메인은_확인이_있어도_오류(world: dict[str, Any]) -> None:
    world["attachments"] = [{"name": "제안요청서.hwp", "url": "https://attacker.example/rfp.hwp"}]
    response = _parse(fetch_attachment=True)
    assert response.status_code == 502
    assert world["downloads"] == []


def test_공고서만_있으면_입찰공고문에서_뽑고_notice_로_표시한다(world: dict[str, Any]) -> None:
    world["attachments"] = [
        {"name": "붙임2. 제출서식.hwp", "url": G2B + "0"},
        {"name": "입찰 공고서.hwpx", "url": G2B + "1"},
    ]
    response = _parse(fetch_attachment=True)
    assert response.status_code == 200, response.text
    assert response.json()["document_role"] == "notice"
    assert world["opened"] == ["입찰 공고서.hwpx"]


PRESPEC_URL = "https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do?bfSpecRegNo=R26BD09999999&fileType=BFDTL&fileSeq=1"
NOTICE_ONLY = [
    {"name": "공고서(국가+협상+자체평가).hwpx", "url": G2B + "0"},
    {"name": "공고서(국가+협상+자체평가).pdf", "url": G2B + "1"},
]


def test_공고서만_있으면_연결된_사전규격의_제안요청서를_읽는다(world: dict[str, Any]) -> None:
    # 11-03 g2b-R26BK01786460 — 본공고 첨부는 공고서뿐이고 제안요청서는 사전규격 R26BD00285788 에만 있었다
    world["attachments"] = list(NOTICE_ONLY)
    world["item"] = {"bfSpecRgstNo": "R26BD09999999", "bidNtceNo": "R26BK09999999"}
    world["prespecs"] = [{"bfSpecRgstNo": "R26BD09999999", "bidNtceNoList": "R26BK09999999", "specDocFileUrl1": PRESPEC_URL}]
    response = _parse(fetch_attachment=True)
    assert response.status_code == 200, response.text
    assert response.json()["document_role"] == "rfp"
    assert world["opened"] == ["사전규격 규격서 1(R26BD09999999)"]
    assert world["downloads"] == [PRESPEC_URL]


def test_사전규격_번호가_비어도_본공고_번호로_사전규격을_찾는다(world: dict[str, Any]) -> None:
    world["attachments"] = list(NOTICE_ONLY)
    world["item"] = {"bidNtceNo": "R26BK09999999"}
    world["prespecs"] = [{"bfSpecRgstNo": "R26BD09999999", "bidNtceNoList": "R26BK08888888, R26BK09999999", "specDocFileUrl1": PRESPEC_URL}]
    response = _parse(fetch_attachment=True)
    assert response.status_code == 200, response.text
    assert world["opened"] == ["사전규격 규격서 1(R26BD09999999)"]


def test_본공고에_제안요청서가_있으면_사전규격보다_그것을_읽는다(world: dict[str, Any]) -> None:
    world["attachments"] = [*NOTICE_ONLY, {"name": "과업지시서.hwp", "url": G2B + "2"}]
    world["item"] = {"bfSpecRgstNo": "R26BD09999999"}
    world["prespecs"] = [{"bfSpecRgstNo": "R26BD09999999", "specDocFileUrl1": PRESPEC_URL}]
    response = _parse(fetch_attachment=True)
    assert response.status_code == 200, response.text
    assert world["opened"] == ["과업지시서.hwp"]


def test_연결된_사전규격이_없으면_첨부_목록은_그대로(world: dict[str, Any]) -> None:
    world["attachments"] = list(NOTICE_ONLY)
    world["item"] = {"bfSpecRgstNo": "R26BD07777777"}
    world["prespecs"] = [{"bfSpecRgstNo": "R26BD09999999", "specDocFileUrl1": PRESPEC_URL}]
    response = _parse(fetch_attachment=True)
    assert response.json()["document_role"] == "notice"
    assert world["opened"] == ["공고서(국가+협상+자체평가).hwpx"]


def test_사전규격이_저장본에서_빠져도_처음_붙일_때_남긴_연결로_붙인다(world: dict[str, Any]) -> None:
    # 11-03 검토 — 사전규격 저장본은 30일 뒤 정리된다(기준 공고: 10-16 등록 · 마감 12-02). 그 뒤에도 같은 규격서를 고른다
    world["attachments"] = list(NOTICE_ONLY)
    world["item"] = {"bfSpecRgstNo": "R26BD09999999", "bidNtceNo": "R26BK09999999"}
    world["prespecs"] = [{"bfSpecRgstNo": "R26BD09999999", "specDocFileUrl1": PRESPEC_URL}]
    assert _parse(fetch_attachment=True).status_code == 200
    world["prespecs"] = []  # 30일 정리
    world["opened"].clear()
    response = _parse(fetch_attachment=True)
    assert response.status_code == 200, response.text
    assert world["opened"] == ["사전규격 규격서 1(R26BD09999999)"] and response.json()["document_role"] == "rfp"


def test_첨부_목록_API_는_사전규격_규격서를_받을_문서로_보인다(world: dict[str, Any]) -> None:
    world["attachments"] = list(NOTICE_ONLY)
    world["item"] = {"bfSpecRgstNo": "R26BD09999999"}
    world["prespecs"] = [{"bfSpecRgstNo": "R26BD09999999", "specDocFileUrl1": PRESPEC_URL, "specDocFileUrl2": "http://plain.example/x"}]
    body = client.get(f"/api/procurements/{NOTICE_ID}/attachments").json()
    assert body["rfp_index"] == 2 and body["rfp_cached"] is False
    assert [a["name"] for a in body["attachments"]][2:] == ["사전규격 규격서 1(R26BD09999999)"]  # https 가 아닌 주소는 붙이지 않는다
    assert body["attachments"][2]["document_role"] == "rfp"
    assert world["downloads"] == []


def test_첨부가_없으면_422(world: dict[str, Any]) -> None:
    world["attachments"] = []
    assert _parse(fetch_attachment=True).status_code == 422
    assert world["downloads"] == []


def test_첨부_목록은_캐시_여부와_크기_공고문_자리를_준다(world: dict[str, Any]) -> None:
    world["attachments"] = [
        {"name": "입찰공고문.hwpx", "url": G2B + "0"},
        {"name": "제안요청서.hwp", "url": G2B + "1"},
    ]
    target = attachment_service.cache_path(NOTICE_ID, 0, "입찰공고문.hwpx")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * 1234)
    body = client.get(f"/api/procurements/{NOTICE_ID}/attachments").json()
    assert body["rfp_index"] == 1 and body["rfp_cached"] is False
    assert body["notice_index"] == 0 and body["notice_cached"] is True
    first, second = body["attachments"]
    assert first["cached"] is True and first["size_bytes"] == 1234
    assert second["cached"] is False and second["size_bytes"] is None
    # 기존 필드는 그대로
    assert second["is_rfp"] is True and second["downloadable"] is True
    # 첨부마다 문서 역할 — 확인 창이 받을 문서를 제 이름으로 부른다(검수 C17)
    assert first["document_role"] == "notice" and second["document_role"] == "rfp"
    assert world["downloads"] == []


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("제안요청서.hwp", "rfp"),
        ("과업지시서.pdf", "rfp"),
        ("입찰공고문.pdf", "notice"),
        ("입찰공고서 및 제출서식.zip > 입찰공고문.hwp", "notice"),
        ("묶음.zip > ★제안요청서.hwpx", "rfp"),
        ("synthetic_rfp.pdf", "rfp"),
    ],
)
def test_문서_역할은_실제로_연_문서_이름으로(name: str, role: str) -> None:
    assert attachment_service.document_role(name) == role


def test_옛_저장_파일은_문서_이름으로_역할을_채우고_바뀐_것으로_세지_않는다() -> None:
    old_notice = {"source": rfp_parser.REAL_NOTICE_SOURCE, "document": "입찰공고문.pdf", "requirements": []}
    old_rfp = {"source": rfp_parser.REAL_NOTICE_SOURCE, "document": "제안요청서.hwp", "requirements": []}
    fixture = {"source": "synthetic_fixture", "document": "공고.pdf", "requirements": []}
    for payload in (old_notice, old_rfp, fixture):
        rfp_parser.migrate_payload(payload)
        # 한 번 올린 뒤 역할만 빠진 옛 파일 — 채우기만 하고 「바뀜」으로 세지 않는다(파일을 다시 쓰지 않는다)
        payload.pop("document_role")
        assert rfp_parser.migrate_payload(payload) is False
    assert old_notice["document_role"] == "notice"
    assert old_rfp["document_role"] == "rfp"
    assert fixture["document_role"] == "rfp"
