"""10-31 최종 점검 W3 — 공고문 내려받기 실패 메모가 httpx 영어 원문 · 바깥 주소 그대로 화면 「출처:」 줄에 나왔다.

새 메모는 우리말 한 줄로 만들고(`bizinfo_client._download_file`), 저장된 옛 메모는 내보낼 때 같은 말로 바꾼다(`wording.modernize_text`).
네트워크는 부르지 않는다 — `httpx.AsyncClient` 를 가짜로.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app.services import bizinfo_client, wording

OLD_NOTE = (
    "공고문 내려받기 실패: Client error '403 Forbidden' for url "
    "'https://www.bizinfo.go.kr/cmm/fms/fileDown.do?atchFileId=FILE_000000000778225&fileSn=2'\n"
    "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403"
)


def test_저장된_옛_메모는_우리말_한_줄로_바꿔_내보낸다() -> None:
    text = wording.modernize_text(OLD_NOTE)
    assert text == "기업마당이 공고문 내려받기를 막았습니다(403) — 공고 원문에서 직접 받으세요"
    assert "http" not in text and "Client error" not in text
    # 연결 실패(상태 번호 없음) · 다른 상태 번호 · 첨부도 같은 규칙
    assert wording.modernize_text("첨부 내려받기 실패: [Errno 11001] getaddrinfo failed").startswith("기업마당 파일 서버에 연결하지 못해 첨부 내려받기가")
    assert "(500)" in wording.modernize_text("공고문 내려받기 실패: Server error '500 Internal Server Error' for url 'https://x'")
    # 모르는 글 · 이미 우리말인 메모는 그대로
    assert wording.modernize_text("공고문 응답이 비어 있습니다") == "공고문 응답이 비어 있습니다"


class _Forbidden:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url, params=None, headers=None):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(403, content=b"no", request=request)


def test_새_메모도_우리말_한_줄_바깥_주소_없음(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bizinfo_client.httpx, "AsyncClient", _Forbidden)
    with pytest.raises(bizinfo_client.BizinfoDocumentError) as caught:
        asyncio.run(bizinfo_client._download_file("FILE_1", "2", target=tmp_path / "a.pdf", label="공고문"))
    assert str(caught.value) == "기업마당이 공고문 내려받기를 막았습니다(403) — 공고 원문에서 직접 받으세요"
    assert not (tmp_path / "a.pdf").exists()
