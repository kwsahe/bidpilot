"""첨부 다운로드 서비스 테스트. 네트워크를 타지 않는다 (httpx 전송을 fake로 대체)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest

from app.services import attachment_service as svc

G2B_URL = "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01691972"


# --------------------------------------------------------------------------
# URL 화이트리스트
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.g2b.go.kr/a/b.do?x=1",
        "https://g2b.go.kr/file",
        "https://sub.dept.g2b.go.kr/file",
    ],
)
def test_allows_g2b_domain(url: str) -> None:
    assert svc.is_allowed_url(url) is True


def test_평문_http는_허용하지_않는다() -> None:
    """도메인이 맞아도 http 면 막는다 (ISSUE-040).

    평문으로 받으면 경로상에서 내용이 그대로 보이고 바꿔치기도 막을 수 없다.
    나라장터는 https 를 제공하므로 잃는 것이 없다.
    """
    assert svc.is_allowed_url("http://g2b.go.kr/file") is False


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/file.hwp",
        "https://evil-g2b.go.kr/file.hwp",  # 단순 endswith였다면 통과했을 유사 도메인
        "https://g2b.go.kr.evil.com/file.hwp",
        "file:///C:/Windows/win.ini",
        "ftp://g2b.go.kr/file.hwp",
        "https://127.0.0.1:8000/internal",
        "",
    ],
)
def test_rejects_non_g2b_url(url: str) -> None:
    assert svc.is_allowed_url(url) is False
    with pytest.raises(svc.AttachmentNotAllowedError):
        svc.ensure_allowed_url(url)


def test_download_rejects_non_g2b_url_without_network() -> None:
    """허용 도메인이 아니면 HTTP 요청 자체를 시작하지 않는다."""
    with pytest.raises(svc.AttachmentNotAllowedError):
        asyncio.run(
            svc.download_attachment(
                "https://attacker.example/payload.hwp",
                file_name="제안요청서.hwp",
                notice_id="g2b-TEST-000",
                index=0,
            )
        )


# --------------------------------------------------------------------------
# 파일명/경로 정규화
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("★제안요청서.hwp", "★제안요청서.hwp"),
        ("../../../../etc/passwd", "passwd"),
        (r"..\..\Windows\System32\evil.exe", "evil.exe"),
        ("a/b/c/제안요청서.hwpx", "제안요청서.hwpx"),
        ("bad\x00name\x1f.pdf", "badname.pdf"),
        ('a<b>c:"d|e?f*.pdf', "abcdef.pdf"),
        ("..", "attachment"),
        ("   ", "attachment"),
    ],
)
def test_sanitize_file_name(raw: str, expected: str) -> None:
    assert svc.sanitize_file_name(raw) == expected


def test_sanitize_file_name_keeps_extension_when_truncating() -> None:
    name = "가" * 400 + ".hwpx"
    result = svc.sanitize_file_name(name)
    assert result.endswith(".hwpx")
    assert len(result) <= svc.MAX_FILE_NAME_LENGTH


def test_path_traversal_cannot_escape_cache_dir() -> None:
    """파일명·공고ID에 경로 이동 문자가 있어도 캐시 디렉터리를 벗어나지 못한다."""
    root = svc.CACHE_DIR.resolve()
    for notice_id, file_name in [
        ("../../../../etc", "../../../../etc/passwd"),
        ("g2b-R26BK01691972-000", r"..\..\..\Windows\System32\drivers\etc\hosts"),
        ("..", ".."),
        ("../evil", "a/b/../../../../evil.hwp"),
    ]:
        target = svc.cache_path(notice_id, 0, file_name)
        assert root in target.parents, f"{target} escaped {root}"


# --------------------------------------------------------------------------
# 제안요청서 자동 선택
# --------------------------------------------------------------------------


def _att(name: str) -> dict[str, str]:
    return {"name": name, "url": G2B_URL}


def test_pick_prefers_proposal_request_over_notice_document() -> None:
    attachments = [
        _att("★입찰공고문.hwp"),
        _att("★입찰공고문.pdf"),
        _att("★제안요청서.hwp"),
        _att("★입찰참가신청서, 서약서.hwp"),
    ]
    assert svc.pick_rfp_attachment(attachments) == 2


def test_pick_prefers_hwpx_hwp_pdf_over_other_extensions() -> None:
    attachments = [
        _att("제안요청서.zip"),
        _att("제안요청서.pdf"),
        _att("[제안요청서] AI 교육 용역.hwpx"),
    ]
    assert svc.pick_rfp_attachment(attachments) == 2


def test_pick_falls_back_to_task_and_notice_documents() -> None:
    assert svc.pick_rfp_attachment([_att("계약일반조건.hwp"), _att("과업지시서.hwp")]) == 1
    assert svc.pick_rfp_attachment([_att("붙임1.hwp"), _att("입찰공고문.pdf")]) == 1


def test_pick_returns_none_when_nothing_looks_like_rfp() -> None:
    attachments = [
        _att("0.직원 사칭 사기 주의 안내.pdf"),
        _att("1.(계약예규) 용역계약일반조건.hwp"),
    ]
    assert svc.pick_rfp_attachment(attachments) is None
    assert svc.pick_rfp_attachment([]) is None


def test_pick_ignores_attachment_without_url() -> None:
    assert svc.pick_rfp_attachment([{"name": "제안요청서.hwp", "url": ""}]) is None


# --------------------------------------------------------------------------
# 다운로드 (네트워크 대신 MockTransport)
# --------------------------------------------------------------------------


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(svc, "CACHE_DIR", tmp_path / "real_rfp")
    return tmp_path / "real_rfp"


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: object, *, calls: list[str]
) -> None:
    """httpx.AsyncClient가 네트워크 대신 MockTransport를 쓰도록 바꾼다."""
    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)  # type: ignore[assignment]
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    calls.clear()


def test_download_writes_and_reuses_cache(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, attachment_fetch_on: None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.4 fake")

    _install_transport(monkeypatch, handler, calls=calls)

    path = asyncio.run(
        svc.download_attachment(
            G2B_URL, file_name="★제안요청서.hwp", notice_id="g2b-R26BK01691972-000", index=2
        )
    )
    assert path.exists()
    assert path.read_bytes() == b"%PDF-1.4 fake"
    assert path.name == "2_★제안요청서.hwp"
    assert path.parent.name == "g2b-R26BK01691972-000"
    assert len(calls) == 1

    # 두 번째 호출은 캐시를 재사용하므로 요청이 늘지 않는다.
    again = asyncio.run(
        svc.download_attachment(
            G2B_URL, file_name="★제안요청서.hwp", notice_id="g2b-R26BK01691972-000", index=2
        )
    )
    assert again == path
    assert len(calls) == 1


MAINTENANCE_PAGE = (
    '<!DOCTYPE html>\r\n<html lang="ko">\r\n<head>\r\n<meta charset="UTF-8">\r\n<title>시스템 점검 안내</title>'
).encode("utf-8")


def test_안내_화면을_첨부로_저장하지_않고_예전에_저장된_것은_다시_받는다(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, attachment_fetch_on: None
) -> None:
    """11-01 — 조달청 점검 중 「제안요청서.hwpx」가 점검 안내 HTML 이었다(「지원하지 않는 문서 형식」 · 저장된 채 재시도도 막힘)."""
    calls: list[str] = []
    bodies = [MAINTENANCE_PAGE, b"PK\x03\x04 hwpx"]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=bodies[0])

    _install_transport(monkeypatch, handler, calls=calls)
    notice = "g2b-R26BK01793373-000"
    with pytest.raises(svc.AttachmentDownloadError) as caught:
        asyncio.run(svc.download_attachment(G2B_URL, file_name="제안요청서.hwpx", notice_id=notice, index=2))
    assert str(caught.value) == "나라장터가 첨부 파일 대신 안내 화면을 보냈습니다(「시스템 점검 안내」) — 조달청 점검이 끝난 뒤 다시 받으세요"
    assert not svc.cache_path(notice, 2, "제안요청서.hwpx").exists()

    # 예전 판이 저장해 둔 안내 화면 — 캐시로 쓰지 않고 지운 뒤 다시 받는다
    poisoned = svc.cache_path(notice, 2, "제안요청서.hwpx")
    poisoned.parent.mkdir(parents=True, exist_ok=True)
    poisoned.write_bytes(MAINTENANCE_PAGE)
    assert svc.cached_attachment(notice, 2, "제안요청서.hwpx") is None
    bodies.pop(0)
    path = asyncio.run(svc.download_attachment(G2B_URL, file_name="제안요청서.hwpx", notice_id=notice, index=2))
    assert path.read_bytes() == b"PK\x03\x04 hwpx"
    assert len(calls) == 2
    assert svc.cached_attachment(notice, 2, "제안요청서.hwpx") == path

    # 이름이 .html 인 첨부는 그대로 받는다
    assert svc.html_page_title(path.with_name("x.html"), "공고.html") is None


def test_download_aborts_when_stream_exceeds_limit(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, attachment_fetch_on: None
) -> None:
    monkeypatch.setattr(svc, "MAX_DOWNLOAD_BYTES", 1024)
    calls: list[str] = []

    async def body() -> "AsyncIterator[bytes]":
        yield b"x" * 512
        yield b"y" * 2048

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        # content-length를 알리지 않는 chunked 응답을 흉내낸다.
        return httpx.Response(200, content=body())

    _install_transport(monkeypatch, handler, calls=calls)

    with pytest.raises(svc.AttachmentTooLargeError):
        asyncio.run(
            svc.download_attachment(
                G2B_URL, file_name="big.hwp", notice_id="g2b-TEST-000", index=0
            )
        )
    # 부분 파일이 캐시에 남으면 안 된다.
    assert not (cache_dir / "g2b-TEST-000" / "0_big.hwp").exists()


def test_download_rejects_declared_content_length_over_limit(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, attachment_fetch_on: None
) -> None:
    monkeypatch.setattr(svc, "MAX_DOWNLOAD_BYTES", 100)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"x")

    _install_transport(monkeypatch, handler, calls=calls)

    with pytest.raises(svc.AttachmentTooLargeError):
        asyncio.run(
            svc.download_attachment(
                G2B_URL, file_name="big.hwp", notice_id="g2b-TEST-000", index=0
            )
        )


def test_download_maps_http_error(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, attachment_fetch_on: None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404, content=b"not found")

    _install_transport(monkeypatch, handler, calls=calls)

    with pytest.raises(svc.AttachmentDownloadError):
        asyncio.run(
            svc.download_attachment(
                G2B_URL, file_name="x.hwp", notice_id="g2b-TEST-000", index=0
            )
        )
    assert not (cache_dir / "g2b-TEST-000" / "0_x.hwp").exists()


def test_download_rejects_empty_response(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, attachment_fetch_on: None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"")

    _install_transport(monkeypatch, handler, calls=calls)

    with pytest.raises(svc.AttachmentDownloadError):
        asyncio.run(
            svc.download_attachment(
                G2B_URL, file_name="x.hwp", notice_id="g2b-TEST-000", index=0
            )
        )


# --------------------------------------------------------------------------
# 19차 §4-A-4 — 내려받기 문 (기본은 꺼짐)
# --------------------------------------------------------------------------


def test_꺼져_있으면_내려받지_않는다(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**요청이 한 번도 나가지 않는다.** 고정 모드에서 4단계가 조용히 실호출하던 길이다."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.4 fake")

    _install_transport(monkeypatch, handler, calls=calls)

    with pytest.raises(svc.AttachmentFetchDisabledError) as caught:
        asyncio.run(
            svc.download_attachment(G2B_URL, file_name="공고문.pdf", notice_id="g2b-TEST-000", index=0)
        )
    assert calls == []
    assert "새 공고 받기가 꺼져" in str(caught.value)
    assert not (cache_dir / "g2b-TEST-000").exists()


def test_꺼져_있어도_캐시에_있으면_쓴다(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _install_transport(monkeypatch, lambda r: calls.append("x") or httpx.Response(200, content=b"x"), calls=calls)
    target = svc.cache_path("g2b-TEST-000", 0, "공고문.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4 cached")

    path = asyncio.run(
        svc.download_attachment(G2B_URL, file_name="공고문.pdf", notice_id="g2b-TEST-000", index=0)
    )
    assert path == target
    assert calls == []
    assert svc.cached_attachment("g2b-TEST-000", 0, "공고문.pdf") == target
    assert svc.cached_attachment("g2b-TEST-000", 1, "없음.pdf") is None


def test_꺼진_문은_화면에_409_와_사유로_간다() -> None:
    """502 「다운로드 실패」가 아니라 「고정 모드라 안 받았다」로 읽혀야 한다."""
    from fastapi import HTTPException

    from app.api import rfp as rfp_api

    with pytest.raises(HTTPException) as caught:
        rfp_api._raise_for_parse_error(svc.AttachmentFetchDisabledError("첨부 내려받기 꺼짐 — 고정 모드"))
    assert caught.value.status_code == 409
    assert "고정 모드" in caught.value.detail


# --------------------------------------------------------------------------
# 19차 §4-A-1 — 입찰공고문 첨부 고르기
# --------------------------------------------------------------------------


def _atts(*names: str) -> list[dict[str, str]]:
    return [{"name": n, "url": f"{G2B_URL}&fileSeq={i}"} for i, n in enumerate(names)]


def test_공고문은_형식_순서로_고른다() -> None:
    atts = _atts("(공고서) 강원대 구축.pdf", "(공고서) 강원대 구축.hwpx", "제안요청서.hwp")
    assert svc.pick_notice_document(atts) == 1  # .hwpx > .pdf


def test_제안요청서를_공고문으로_쓰지_않는다() -> None:
    assert svc.pick_notice_document(_atts("제안요청서.hwp", "과업지시서.hwp")) is None
    # 「입찰공고」가 이름에 있어도 제안요청서면 공고문이 아니다.
    assert svc.pick_notice_document(_atts("입찰공고 제안요청서.hwp")) is None


def test_압축_공고문도_고른다() -> None:
    atts = _atts("[한국공학대 입찰공고] 운영 용역.zip", "제안요청서.hwp")
    assert svc.pick_notice_document(atts) == 0


def test_공고만_있는_이름도_공고문이다() -> None:
    """실측 72건 중 넷 — 「2. 공고_….pdf」·「…제출안내 공고.hwp」·「공고_개발_공동_수평.hwpx」·「입찰재공고」."""
    assert svc.pick_notice_document(_atts("2. 공고_교원 해외연수.pdf", "4. 제안요청서.hwp")) == 0
    assert svc.pick_notice_document(_atts("공고_개발_공동_수평.pdf", "공고_개발_공동_수평.hwpx")) == 1
    assert svc.pick_notice_document(_atts("[한국공학대 입찰재공고] 연구용역.zip")) == 0
    # 강한 이름이 있으면 그것이 먼저다.
    assert svc.pick_notice_document(_atts("공고 안내.hwpx", "입찰공고문.pdf")) == 1


def test_공고_서식은_공고문이_아니다() -> None:
    assert svc.pick_notice_document(_atts("공고 서식(입찰참가신청서).hwp", "공고_별지 양식.hwp")) is None
    # 실측(1726154) — 형식 순서로는 .hwp 가 앞이지만 서식이다. 옆의 공고문 PDF 를 고른다.
    atts = _atts("입찰공고문(협상).pdf", "과업지시서(보완).pdf", "입찰공고(일반용역)-업체작성양식 (3).hwp")
    assert svc.pick_notice_document(atts) == 0
    assert svc.pick_notice_document(_atts("입찰공고서 및 제출서식.zip")) == 0


def test_주소가_없는_첨부는_고르지_않는다() -> None:
    assert svc.pick_notice_document([{"name": "입찰공고문.pdf", "url": ""}]) is None
