"""기업마당(bizinfo.go.kr) 지원사업정보 OpenAPI 클라이언트.

실응답 확인 완료 (2026-09-08, scripts/verify_bizinfo_api.py):
    GET https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do
        crtfcKey=<인증키>&dataType=json&searchCnt=<건수>[&hashtags=...]
    성공: {"jsonArray": [ {pblancId, pblancNm, jrsdInsttNm, excInsttNm, bsnsSumryCn, reqstBeginEndDe,
                          pldirSportRealmLclasCodeNm, pldirSportRealmMlsfcCodeNm, hashtags, trgetNm,
                          pblancUrl, creatPnttm, updtPnttm, reqstMthPapersCn, refrncNm, rceptEngnHmpgUrl,
                          fileNm, flpthNm, printFileNm, printFlpthNm, inqireCo, totCnt}, ... ]}
    빈 결과: {"jsonArray": []}
    오류: **HTTP 200** + {"reqErr": "존재하지 않는 인증키 입니다."}  ← 상태코드로는 알 수 없다

인증키는 로그·오류 메시지·캐시 어디에도 남기지 않는다 (CLAUDE.md 21).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.services import wording

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
DEFAULT_COUNT = 100
# 한 번에 받을 수 있는 최대 건수.
#
# 500 으로 묶여 있었는데, 그 상한이 **기준 답안 16건 중 15건을 못 보게 하고 있었다**
# (0921 §4-A-4). 기업마당은 페이지 파라미터가 없고 `searchCnt` 단발이라, 전체(실측
# 1,604건)를 보려면 이 수를 넘겨야 한다. 검수자가 큰 값으로 전체를 받아 확인했다(0921 §2).
# 무한정은 아니다 — 응답 크기와 호출 예의를 위해 여유 있는 상한 하나를 둔다.
MAX_COUNT = 5000
#: 「전체를 받는다」는 뜻의 값. `collect_daily` 와 통합 목록이 이것을 쓴다.
FULL_COUNT = MAX_COUNT


class BizinfoError(RuntimeError):
    """호출 실패 (키 없음·네트워크·인증 오류·형식 오류)."""


def is_configured() -> bool:
    return bool(get_settings().bizinfo_api_key)


def _redact(text: str) -> str:
    """인증키가 섞인 문자열(예외 메시지·URL)을 가린다. 키가 없으면 그대로."""
    key = get_settings().bizinfo_api_key
    return text.replace(key, "***") if key else text


async def fetch_programs_raw(*, count: int = DEFAULT_COUNT, hashtags: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.bizinfo_api_key:
        raise BizinfoError("BIZINFO_API_KEY가 설정되지 않았습니다")
    params: dict[str, Any] = {
        "crtfcKey": settings.bizinfo_api_key,
        "dataType": "json",
        "searchCnt": max(1, min(int(count), MAX_COUNT)),
    }
    if hashtags:
        params["hashtags"] = hashtags
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(BASE_URL, params=params)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise BizinfoError(f"기업마당 호출 실패: {_redact(str(exc))}") from exc
    except ValueError as exc:
        raise BizinfoError("기업마당 응답이 JSON이 아닙니다") from exc
    if not isinstance(body, dict):
        raise BizinfoError("기업마당 응답 형식이 예상과 다릅니다 (dict 아님)")
    # 인증 오류도 HTTP 200으로 온다. 조용히 빈 목록으로 떨어뜨리지 않는다.
    error = body.get("reqErr")
    if error:
        raise BizinfoError(f"기업마당 인증/요청 오류: {_redact(str(error))}")
    return body


def extract_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """루트 키는 jsonArray (실응답 확인). 다른 키로 오면 첫 list 값을 쓴다 (형식 변경 방어)."""
    items = body.get("jsonArray")
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    for value in body.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def total_count(items: list[dict[str, Any]]) -> int | None:
    """각 항목에 실린 totCnt(전체 공고 수). 받은 건수가 아니라 기업마당 전체 등록 건수다."""
    for item in items:
        raw = item.get("totCnt")
        if raw is None:
            continue
        try:
            return int(str(raw).strip())
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# 공고문 원본 내려받기 (0924.md §4-A-1 · ISSUE-096)
# --------------------------------------------------------------------------
#
# 목록 API 의 `printFlpthNm` 은 **뷰어 HTML** 을 준다. 같은 `atchFileId`·`fileSn` 으로
# `fileDown.do` 를 부르면 PDF/HWP/HWPX **원본**이 온다 (검수자 실측 2026-09-18,
# `docs/reports/2026-09-24_bizinfo_candidates.md` §3 — 26건 전부 성공).
#
# 이것은 OpenAPI 가 아니라 **파일 서버** 호출이라 인증키가 필요 없고 API 한도와도 무관하다.
# 그래도 한 번에 1,605건을 받지 않는다 — 받는 범위는 부르는 쪽이 정한다(§4-A-2).

#: 원본 파일 주소. 뷰어(`getImageFile.do`)와 경로만 다르다.
FILE_DOWNLOAD_URL = "https://www.bizinfo.go.kr/cmm/fms/fileDown.do"

#: 브라우저처럼 보이는 헤더. 이것이 없으면 파일 서버가 본문 대신 안내 페이지를 준다.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Referer": "https://www.bizinfo.go.kr/",
}

#: 한 파일의 상한. 실측은 80KB~1.3MB 였다 — 여유를 두되 무한정 받지는 않는다.
MAX_DOCUMENT_BYTES = 40 * 1024 * 1024

DOCUMENT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

_FILE_ID_RE = re.compile(r"atchFileId=([A-Za-z0-9_]+)")
_FILE_SN_RE = re.compile(r"fileSn=(\d+)")


class BizinfoDocumentError(RuntimeError):
    """공고문 내려받기 실패 (주소 없음·네트워크·빈 응답)."""


def announcement_ref(item: dict[str, Any]) -> tuple[str, str] | None:
    """목록 항목에서 `(atchFileId, fileSn)` 을 읽는다. 없으면 None."""
    url = _text_of(item, "printFlpthNm") or _text_of(item, "flpthNm")
    if not url:
        return None
    file_id = _FILE_ID_RE.search(url)
    file_sn = _FILE_SN_RE.search(url)
    if not file_id:
        return None
    return file_id.group(1), (file_sn.group(1) if file_sn else "0")


def announcement_extension(item: dict[str, Any]) -> str:
    """`printFileNm` 의 확장자. 모르면 `bin` — 형식 판별은 내려받은 뒤 내용으로도 한다."""
    name = _text_of(item, "printFileNm") or _text_of(item, "fileNm") or ""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return suffix if suffix.isalnum() and 1 <= len(suffix) <= 5 else "bin"


def _text_of(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return str(value).strip() if value is not None and str(value).strip() else None


async def download_announcement(item: dict[str, Any], *, target: Path) -> Path:
    """공고문 원본을 `target` 에 내려받는다. 성공하면 그 경로를 돌려준다.

    `target` 의 확장자는 부르는 쪽이 `announcement_extension` 으로 정한다 — 파일 서버는
    `application/octet-stream` 으로만 답해서 내용 형식을 헤더로 알 수 없다.
    """
    ref = announcement_ref(item)
    if ref is None:
        raise BizinfoDocumentError("공고문 첨부 주소가 목록 항목에 없습니다")
    file_id, file_sn = ref
    return await _download_file(file_id, file_sn, target=target, label="공고문")


async def _download_file(file_id: str, file_sn: str, *, target: Path, label: str) -> Path:
    """파일 서버에서 원본 한 개 — 같은 주소 · 헤더 · 크기 상한 · 안내 HTML 거절(공고문 · 첨부 공통)."""
    params = {"atchFileId": file_id, "fileSn": file_sn}
    try:
        async with httpx.AsyncClient(timeout=DOCUMENT_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(FILE_DOWNLOAD_URL, params=params, headers=_BROWSER_HEADERS)
            response.raise_for_status()
            body = response.content
    except httpx.HTTPError as exc:
        # 10-31 최종 점검 — httpx 영어 예외 글(바깥 주소 포함)이 화면 「출처:」 줄에 그대로 나왔다 → 우리말 한 줄 · 원문은 로그에만
        logger.warning("기업마당 %s 내려받기 실패: %s", label, _redact(str(exc)))
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        raise BizinfoDocumentError(wording.download_failure_line(label, status)) from exc
    if not body:
        raise BizinfoDocumentError(f"{label} 응답이 비어 있습니다")
    if len(body) > MAX_DOCUMENT_BYTES:
        raise BizinfoDocumentError(f"{label}이(가) 상한({MAX_DOCUMENT_BYTES}바이트)보다 큽니다")
    # 파일 서버가 본문 대신 안내 HTML 을 줄 때가 있다. 그것을 원본으로 저장하지 않는다.
    head = body[:512].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        raise BizinfoDocumentError(f"{label} 대신 안내 페이지가 왔습니다 (원문 주소 확인 필요)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


#: 받을 수 있는 첨부 형식 (30차 §3-A) — 문서만.
ATTACHMENT_SUFFIXES = frozenset({"pdf", "hwp", "hwpx"})


def _split_at(value: str | None) -> list[str]:
    """「@」로 이어 붙인 칸을 조각으로(bizinfo_service._split_field 와 같은 규칙)."""
    return [part.strip() for part in (value or "").split("@") if part.strip()]


def attachment_ref(item: dict[str, Any], index: int) -> tuple[str, str, str, str]:
    """신청 서식 칸(fileNm/flpthNm)의 `index` 번째 첨부 → (atchFileId, fileSn, 원래 이름, 확장자).

    주소가 기업마당(bizinfo.go.kr)이 아니거나 형식이 pdf · hwp · hwpx 가 아니면 BizinfoDocumentError.
    """
    urls = _split_at(_text_of(item, "flpthNm"))
    names = _split_at(_text_of(item, "fileNm"))
    if not 0 <= index < len(urls):
        raise BizinfoDocumentError("그 순번의 첨부가 목록 항목에 없습니다")
    url = urls[index]
    host = (urlparse(url).hostname or "").lower()
    if not (host == "bizinfo.go.kr" or host.endswith(".bizinfo.go.kr")):
        raise BizinfoDocumentError("기업마당 주소가 아닌 첨부는 받지 않습니다")
    name = names[index] if index < len(names) else ""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in ATTACHMENT_SUFFIXES:
        raise BizinfoDocumentError("pdf · hwp · hwpx 첨부만 받습니다")
    file_id = _FILE_ID_RE.search(url)
    file_sn = _FILE_SN_RE.search(url)
    if not file_id:
        raise BizinfoDocumentError("첨부 주소에 파일 번호가 없습니다")
    return file_id.group(1), (file_sn.group(1) if file_sn else "0"), name, suffix


async def download_attachment(item: dict[str, Any], index: int, *, target: Path) -> Path:
    """신청 서식 칸의 첨부 한 개(예 과제소개서)를 `target` 에 받는다 — `download_announcement` 와 같은 틀 (30차 §3-A)."""
    file_id, file_sn, _name, _suffix = attachment_ref(item, index)
    return await _download_file(file_id, file_sn, target=target, label="첨부")
