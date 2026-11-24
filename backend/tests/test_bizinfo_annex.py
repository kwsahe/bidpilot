"""과제소개서([별첨 1]) 받기 · 과제 절 자르기 (30차 · prompt_20 §3-A · 담당자 지시 「과제소개서도 다운받도록」).

- 첨부 짝짓기는 그대로(`_attachments`) — 이름으로 종류: 과제소개서 · 신청 매뉴얼 · 신청 서식 · 공고문.
- 한 개 받기: 같은 파일 서버 주소 · 헤더 · 크기 상한 · 안내 HTML 거절 + 기업마당 주소만 · pdf/hwp/hwpx 만.
- 저장 `{id}.annex1.{확장자}` + 텍스트 `{id}.annex1.txt` · 색인에 기록.
- 과제 절은 **과제 번호**로(목차 줄 · 다른 번호 제외) · 6,000자가 넘으면 덩어리 차례로.
- 단추 경로는 시연 고정 모드에서도 된다 · 공개(읽기 전용) 배포는 막는다.
네트워크는 부르지 않는다 — `httpx.AsyncClient` 를 가짜로.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import bizinfo_client, bizinfo_document_store, plan_form_service
from app.services.bizinfo_service import _attachments, annex_attachment, attachment_kind
from tests.test_bizinfo_attachments import ITEM_126482

client = TestClient(app)


def test_첨부_종류는_이름으로_단다() -> None:
    files = [a for a in _attachments(ITEM_126482) if a.index is not None]
    assert [(a.kind, a.index) for a in files] == [("notice", 0), ("manual", 1), ("annex", 2)]
    assert [a.kind for a in _attachments(ITEM_126482) if a.index is None] == ["notice"]  # 공고문 칸
    assert annex_attachment(ITEM_126482).name == "[별첨_1]_공공기관_과제소개서.pdf"
    assert attachment_kind("사업계획서 양식.hwp") == "form" and attachment_kind("수요과제 목록.pdf") == "annex"
    assert attachment_kind("붙임 3.zip") == "form"  # 모르면 예전처럼 신청 서식


def test_첨부_주소_형식_순번을_검사한다() -> None:
    assert bizinfo_client.attachment_ref(ITEM_126482, 2)[:2] == ("FILE_000000000773432", "3")
    with pytest.raises(bizinfo_client.BizinfoDocumentError, match="순번"):
        bizinfo_client.attachment_ref(ITEM_126482, 9)
    outside = {**ITEM_126482, "flpthNm": "https://evil.example.com/cmm/fms/getImageFile.do?atchFileId=FILE_1&fileSn=1"}
    with pytest.raises(bizinfo_client.BizinfoDocumentError, match="기업마당 주소"):
        bizinfo_client.attachment_ref(outside, 0)
    zipped = {**ITEM_126482, "fileNm": "과제소개서.zip", "flpthNm": ITEM_126482["flpthNm"].split("@")[0]}
    with pytest.raises(bizinfo_client.BizinfoDocumentError, match="pdf"):
        bizinfo_client.attachment_ref(zipped, 0)


class _FakeClient:
    body = b"%PDF-1.7 annex"
    calls: list[tuple[str, dict, dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url, params=None, headers=None):
        type(self).calls.append((url, dict(params or {}), dict(headers or {})))
        return httpx.Response(200, content=type(self).body, request=httpx.Request("GET", url))


@pytest.fixture()
def fake_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _FakeClient.calls = []
    _FakeClient.body = b"%PDF-1.7 annex"
    monkeypatch.setattr(bizinfo_client.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(bizinfo_document_store, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(bizinfo_document_store, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(bizinfo_document_store, "_INDEX_CACHE", None)
    monkeypatch.setattr(bizinfo_document_store, "_extract", lambda path, suffix: (["과제1 가 기관 과제소개서\n본문" * 30, "둘째 쪽"], None))
    return tmp_path


def test_받기는_같은_주소_헤더로_annex1_이름에_두고_색인에_적는다(fake_server: Path) -> None:
    record = asyncio.run(bizinfo_document_store.fetch_annex(ITEM_126482, 2))
    url, params, headers = _FakeClient.calls[0]
    assert url == bizinfo_client.FILE_DOWNLOAD_URL and params == {"atchFileId": "FILE_000000000773432", "fileSn": "3"}
    assert "Mozilla" in headers["User-Agent"]
    assert (fake_server / "PBLN_000000000126482.annex1.pdf").read_bytes() == b"%PDF-1.7 annex"
    assert (fake_server / "PBLN_000000000126482.annex1.txt").exists()
    assert record.status == "text" and record.pages == 2 and record.file_name == "[별첨_1]_공공기관_과제소개서.pdf"
    again = bizinfo_document_store.annex_record("PBLN_000000000126482")
    assert again is not None and again.chars == record.chars and again.downloaded_at
    # 공고문 기록과 따로 센다
    assert bizinfo_document_store.load_index().records == {}


def test_안내_HTML_과_크기_상한은_실패로(fake_server: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.body = b"<!DOCTYPE html><html>notice</html>"
    record = asyncio.run(bizinfo_document_store.fetch_annex(ITEM_126482, 2))
    assert record.status == "failed" and "안내 페이지" in (record.note or "")
    monkeypatch.setattr(bizinfo_client, "MAX_DOCUMENT_BYTES", 4)
    _FakeClient.body = b"%PDF-1.7 big"
    record = asyncio.run(bizinfo_document_store.fetch_annex(ITEM_126482, 2))
    assert record.status == "failed" and "상한" in (record.note or "")


ANNEX_TEXT = "\n".join([
    "목 차",
    "1. 국가데이터처 과제소개서 ················ 1",
    "2. 방위사업청 과제소개서 ···················· 5",
    "\f[쪽 2]",
    "과제1 국가데이터처 과제소개서",
    "□ 과제 제안 개요",
    "◦ (개요) 인구밀집도 지표를 만든다",
    "◦ (문제점) 지표가 흩어져 있다",
    "< 협업 창업기업 기준요건 및 요구사항 >",
    "▪ AI 모델 개발 경험이 있는 기업",
    "▪ 공공데이터 가공 역량",
    "  (최근 3년)",
    "< 역할 및 추진 로드맵 >",
    "▪ 기관이 데이터를 준다",
    "□ 협업 및 활용 계획",
    "- 3 -",
    "과제 2 방위사업청 과제소개서",
    "◦ (개요) 연구 과제 검토를 돕는다",
    "과제3 한국공항공사 과제소개서(1)",
    "◦ (개요) 짐 배송",
])


@pytest.fixture()
def annex_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(bizinfo_document_store, "DOCS_DIR", tmp_path)
    (tmp_path / "PBLN_X.annex1.txt").write_text(ANNEX_TEXT, encoding="utf-8")
    return tmp_path


def test_과제_번호로_자르고_목차_줄은_머리가_아니다(annex_file: Path) -> None:
    first = plan_form_service.annex_excerpt("bizinfo-PBLN_X", {"no": 1, "title": "인구밀집도"})
    assert first.splitlines()[0] == "과제1 국가데이터처 과제소개서" and "방위사업청" not in first
    assert "- 3 -" not in first and "[쪽" not in first  # 쪽 표시 · 쪽 번호 줄은 뺀다
    second = plan_form_service.annex_excerpt("bizinfo-PBLN_X", {"no": 2, "title": "연구 과제"})
    assert second.startswith("과제 2 방위사업청 과제소개서") and "공항공사" not in second
    # 같은 기관 과제가 둘이면 「과제소개서(1)」 꼬리 — 126482 실측 5~12번
    assert plan_form_service.annex_excerpt("bizinfo-PBLN_X", {"no": 3}).startswith("과제3 한국공항공사 과제소개서(1)")
    assert plan_form_service.annex_excerpt("bizinfo-PBLN_X", {"no": 7, "title": "없음"}) is None  # 못 찾으면 지어내지 않음
    assert plan_form_service.annex_excerpt("bizinfo-PBLN_Y", {"no": 1}) is None


def test_긴_과제는_덩어리를_차례로_상한_안에(annex_file: Path) -> None:
    long = ANNEX_TEXT.replace("◦ (문제점) 지표가 흩어져 있다", "◦ (문제점) " + "가나다라마바사 " * 900)
    (annex_file / "PBLN_X.annex1.txt").write_text(long, encoding="utf-8")
    out = plan_form_service.annex_excerpt("bizinfo-PBLN_X", {"no": 1}, limit=600)
    assert len(out) <= 600 and out.startswith("과제1 국가데이터처 과제소개서") and "(개요)" in out


def test_기준요건_줄을_과제마다_그대로(annex_file: Path) -> None:
    rows = plan_form_service.annex_task_requirements("bizinfo-PBLN_X")
    assert rows == {1: ["AI 모델 개발 경험이 있는 기업", "공공데이터 가공 역량 (최근 3년)"]}


def test_단추_경로는_고정_모드에서도_되고_공개_배포는_막는다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import insights

    monkeypatch.setattr(insights, "_bizinfo_item", lambda pid: ITEM_126482 if pid.endswith("126482") else None)
    seen: list[int] = []

    async def fake_fetch(item, index):
        seen.append(index)
        return bizinfo_document_store.DocumentRecord(program_id="PBLN_000000000126482", status="text", file_name="과제소개서.pdf",
                                                     suffix="pdf", bytes=10, pages=99, chars=69611, downloaded_at="2026-10-01T00:00:00+00:00")

    monkeypatch.setattr(bizinfo_document_store, "fetch_annex", fake_fetch)
    monkeypatch.setattr(bizinfo_document_store, "annex_record", lambda pid: None)
    monkeypatch.setattr(get_settings(), "bizinfo_live_fetch", False)  # 시연 고정 모드
    view = client.get("/api/support-programs/bizinfo-PBLN_000000000126482/annex").json()
    assert view["attachment"]["name"] == "[별첨_1]_공공기관_과제소개서.pdf" and view["record"] is None
    ok = client.post("/api/support-programs/bizinfo-PBLN_000000000126482/annex")
    assert ok.status_code == 200 and seen == [2]
    assert client.post("/api/support-programs/bizinfo-PBLN_000000000999999/annex").status_code == 404
    monkeypatch.setattr(get_settings(), "public_demo_mode", True)
    assert client.post("/api/support-programs/bizinfo-PBLN_000000000126482/annex").status_code == 403


def test_30차_일괄_받기가_먼저_읽은_색인으로_덮어도_과제소개서_기록은_남는다(fake_server: Path) -> None:
    """§4 마지막 검토 — collect_daily 가 시작 때 읽은 색인을 끝에 통째로 쓰면 그 사이 단추로 받은 기록이 사라졌다."""
    stale = bizinfo_document_store.load_index()  # 다른 프로세스가 먼저 읽어 둔 색인(과제소개서 없음)
    asyncio.run(bizinfo_document_store.fetch_annex(ITEM_126482, 2))
    bizinfo_document_store.save_index(stale)
    assert bizinfo_document_store.annex_record("PBLN_000000000126482") is not None
