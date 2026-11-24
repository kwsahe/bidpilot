"""나라장터 공고 첨부문서 다운로드 서비스.

원칙 (docs/real_data_migration.md 3-3):
- **g2b.go.kr 도메인만** 허용한다. 사용자가 준 임의 URL을 서버가 대신 열지 않는다(SSRF 차단).
- 크기 상한을 스트리밍 중에 검사해 초과하면 즉시 중단한다.
- 받은 파일은 디스크에 캐시해 같은 첨부를 다시 내려받지 않는다.
- 파일명은 정규화하며, 저장 경로가 캐시 디렉터리를 벗어나면 거부한다.

첨부 URL은 `g2b_mapper.extract_attachments()`가 `ntceSpecDocUrl1..10`에서 뽑은 값이다.
실제 형태: https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.core.paths import DATA_ROOT

CACHE_DIR = DATA_ROOT / "public" / "real_rfp"

logger = logging.getLogger(__name__)

# 허용 도메인. 정확히 g2b.go.kr 이거나 그 하위 도메인(www.g2b.go.kr)만 통과시킨다.
# 단순 endswith는 "evil-g2b.go.kr" 같은 유사 도메인을 통과시키므로 쓰지 않는다.
ALLOWED_HOST = "g2b.go.kr"
# http 는 빼 둔다. 평문으로 받으면 경로상에서 내용이 그대로 보이고, 바꿔치기도 막을 수 없다 (ISSUE-040).
ALLOWED_SCHEMES = ("https",)

MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024  # 30MB
DOWNLOAD_TIMEOUT = httpx.Timeout(40.0, connect=10.0)
CHUNK_SIZE = 64 * 1024

MAX_FILE_NAME_LENGTH = 120
DEFAULT_FILE_NAME = "attachment"


class AttachmentError(RuntimeError):
    """첨부 처리 실패 공통 예외."""


class AttachmentNotAllowedError(AttachmentError):
    """허용되지 않은 URL(도메인/스킴) 또는 허용 범위를 벗어난 저장 경로."""


class AttachmentTooLargeError(AttachmentError):
    """첨부 크기 상한 초과."""


class AttachmentDownloadError(AttachmentError):
    """네트워크 오류 또는 비정상 응답."""


class AttachmentFetchDisabledError(AttachmentError):
    """첨부 내려받기가 꺼져 있고(고정 모드) 캐시에도 없다 (19차 §4-A-4)."""


def attachment_fetch_enabled() -> bool:
    """첨부를 실제로 내려받아도 되는가. `ATTACHMENT_FETCH=1` 일 때만 참 (기본은 꺼짐)."""
    return bool(get_settings().attachment_fetch)


# --------------------------------------------------------------------------
# 1) URL 검증
# --------------------------------------------------------------------------


def is_allowed_url(url: str) -> bool:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return host == ALLOWED_HOST or host.endswith("." + ALLOWED_HOST)


def ensure_allowed_url(url: str) -> None:
    """허용 도메인이 아니면 AttachmentNotAllowedError. 호스트만 메시지에 남긴다."""
    if not is_allowed_url(url):
        host = urlsplit(url.strip()).hostname or "(none)"
        raise AttachmentNotAllowedError(
            f"허용되지 않은 첨부 URL입니다. {ALLOWED_HOST} 도메인만 내려받습니다 (host={host})"
        )


# --------------------------------------------------------------------------
# 2) 파일명·경로 정규화
# --------------------------------------------------------------------------

# 경로 구분자, 제어문자, 윈도우 금지문자를 모두 걷어낸다.
_UNSAFE_CHARS_RE = re.compile(r'[\x00-\x1f\x7f<>:"|?*]')
_SEPARATOR_RE = re.compile(r"[\\/]+")
_DOT_RUN_RE = re.compile(r"\.{2,}")


def sanitize_file_name(name: str, *, default: str = DEFAULT_FILE_NAME) -> str:
    """디렉터리 이동·제어문자를 제거하고 확장자는 보존한 안전한 파일명을 만든다."""
    # 경로 구분자를 기준으로 마지막 조각만 취해 "../../x" 같은 입력을 무력화한다.
    base = _SEPARATOR_RE.split(name.strip())[-1]
    base = _UNSAFE_CHARS_RE.sub("", base)
    base = _DOT_RUN_RE.sub(".", base)
    base = base.strip().strip(". ")
    if not base or base in {".", ".."}:
        return default

    stem, dot, ext = base.rpartition(".")
    if not dot:  # 확장자가 없는 경우
        return base[:MAX_FILE_NAME_LENGTH] or default
    ext = ext[:16]
    keep = max(1, MAX_FILE_NAME_LENGTH - len(ext) - 1)
    return f"{stem[:keep]}.{ext}"


def sanitize_dir_name(name: str, *, default: str = "notice") -> str:
    """공고 ID를 디렉터리명으로 쓸 수 있게 정규화한다."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name.strip())
    cleaned = _DOT_RUN_RE.sub(".", cleaned).strip("._")
    return cleaned[:80] or default


def cache_path(notice_id: str, index: int, file_name: str) -> Path:
    """data/public/real_rfp/<공고ID>/<index>_<안전한 파일명>. 캐시 밖 경로는 거부한다."""
    safe_dir = sanitize_dir_name(notice_id)
    safe_name = f"{max(int(index), 0)}_{sanitize_file_name(file_name)}"
    target = (CACHE_DIR / safe_dir / safe_name).resolve()
    root = CACHE_DIR.resolve()
    if root != target and root not in target.parents:
        raise AttachmentNotAllowedError("첨부 저장 경로가 캐시 디렉터리를 벗어납니다")
    return target


# --------------------------------------------------------------------------
# 3) RFP 첨부 자동 선택
# --------------------------------------------------------------------------

# 앞쪽일수록 우선순위가 높다. 실제 첨부명은 "★제안요청서.hwp",
# "[제안요청서] ... 용역.hwpx", "26-HS086 00. 제안요청서.hwp" 처럼 장식이 붙는다.
RFP_NAME_KEYWORDS: tuple[tuple[str, ...], ...] = (
    ("제안요청서",),
    # 「사전규격 규격서 n(번호)」 — 본공고 첨부 뒤에 붙인 사전규격 문서(11-03 · `prespec_service.spec_docs_for`).
    # 본공고 자체 과업지시서와 같은 순위지만 확장자가 없어 뒤에 서고, 공고문보다는 앞선다.
    ("과업지시서", "과업내용서", "사전규격규격서"),
    ("입찰공고문", "입찰공고"),
)
# 텍스트 추출이 가능한 형식을 우선한다 (document_extractor 지원 범위).
# .zip은 공고문·제안요청서·서식을 한 덩어리로 올린 첨부다. 안에서 제안요청서를 골라 연다.
PREFERRED_EXTENSIONS: tuple[str, ...] = (".hwpx", ".hwp", ".pdf", ".zip")

_WHITESPACE_RE = re.compile(r"\s+")


def _keyword_rank(name: str) -> int | None:
    """첨부명이 RFP류인지 판정. 아니면 None."""
    compact = _WHITESPACE_RE.sub("", name)
    for rank, keywords in enumerate(RFP_NAME_KEYWORDS):
        if any(keyword in compact for keyword in keywords):
            return rank
    return None


def _extension_rank(name: str) -> int:
    suffix = Path(sanitize_file_name(name)).suffix.lower()
    if suffix in PREFERRED_EXTENSIONS:
        return PREFERRED_EXTENSIONS.index(suffix)
    return len(PREFERRED_EXTENSIONS)


#: 입찰공고문으로 볼 이름 조각. 「제안요청」·「과업」이 함께 있으면 공고문이 아니다 (19차 §4-A-1).
NOTICE_NAME_KEYWORDS: tuple[str, ...] = ("입찰공고", "공고서", "공고문", "재공고")
#: 「공고」만 있는 이름(「2. 공고_….pdf」·「…제출안내 공고.hwp」·「공고_개발_공동_수평.hwpx」)도 공고문이다 —
#: 실측 72건 중 넷이 이 꼴이었다. 다만 강한 이름보다 **뒤**에서 고르고, 서식·양식은 빼다.
NOTICE_WEAK_KEYWORD = "공고"
NOT_NOTICE_KEYWORDS: tuple[str, ...] = ("제안요청", "과업")
NOT_NOTICE_WEAK: tuple[str, ...] = ("서식", "양식", "별지", "별첨", "서약서", "위임장")


def pick_notice_document(attachments: Sequence[Mapping[str, Any]]) -> int | None:
    """입찰공고문 첨부의 인덱스. 없으면 None.

    **제안요청서를 대신 쓰지 않는다.** 참가자격은 공고문에 적히는 것이 원칙이고, 제안요청서의
    같은 절은 두 번째 출처로만 읽는다(`qualification_clause_service`). 형식은
    `.hwpx > .hwp > .pdf > .zip` — 같은 공고문을 두 형식으로 올린 기관이 많다.
    """
    best: tuple[int, int, int] | None = None
    best_index: int | None = None
    for index, attachment in enumerate(attachments):
        name = _WHITESPACE_RE.sub("", str(attachment.get("name") or ""))
        if not attachment.get("url"):
            continue
        if any(k in name for k in NOT_NOTICE_KEYWORDS):
            continue
        # 서식·양식이 붙은 이름은 공고문이 아니다 — 실측: 「입찰공고(일반용역)-업체작성양식.hwp」가
        # 옆의 「입찰공고문(협상).pdf」 대신 골라졌다. 「공고문·공고서」를 따로 적었으면 공고문이다
        # (「입찰공고서 및 제출서식.zip」). 「공고서식」의 「공고서」는 그 셈에 넣지 않는다.
        formish = any(w in name for w in ("서식", "양식"))
        explicit = any(k in name.replace("공고서식", "").replace("공고양식", "") for k in ("공고문", "공고서"))
        if any(k in name for k in NOTICE_NAME_KEYWORDS) and (not formish or explicit):
            strength = 0
        elif NOTICE_WEAK_KEYWORD in name and not any(k in name for k in NOT_NOTICE_WEAK):
            strength = 1
        else:
            continue
        score = (strength, _extension_rank(name), index)
        if best is None or score < best:
            best, best_index = score, index
    return best_index


def cached_attachment(notice_id: str, index: int, file_name: str) -> Path | None:
    """이미 내려받아 둔 첨부. 없으면 None (네트워크를 부르지 않는다)."""
    target = cache_path(notice_id, index, file_name)
    if not (target.exists() and target.stat().st_size > 0):
        return None
    return None if html_page_title(target, file_name) is not None else target


_HTML_HEAD_RE = re.compile(rb"^\s*(?:<!doctype\s+html|<html)", re.I)
_HTML_TITLE_RE = re.compile(rb"<title>\s*([^<]{1,120}?)\s*</title>", re.I)


def html_page_title(path: Path, file_name: str) -> str | None:
    """받은 첨부가 실제로는 HTML 안내 화면이면 그 제목(없으면 ""), 아니면 None.

    11-01 — 조달청 점검 중 「제안요청서.hwpx」로 받은 것이 1.9KB 「시스템 점검 안내」 HTML 이었다.
    「지원하지 않는 문서 형식」으로 실패했고, 저장된 채라 점검이 끝나도 다시 받지 않았다.
    """
    if file_name.lower().endswith((".html", ".htm")):
        return None
    with path.open("rb") as handle:
        head = handle.read(4096).removeprefix(b"\xef\xbb\xbf")
    if not _HTML_HEAD_RE.match(head):
        return None
    title = _HTML_TITLE_RE.search(head)
    return title.group(1).decode("utf-8", "replace") if title else ""


def document_role(file_name: str) -> str:
    """추출한 문서가 제안요청서류(`rfp`)인가 입찰공고문(`notice`)인가 (27차 §3-A-4).

    압축 첨부는 `바깥 > 안` 꼴이라 실제로 연 안쪽 이름으로 본다. 제안요청서 · 과업지시서 ·
    과업내용서만 `rfp` 다 — 공고문에서 뽑은 표에는 과업 세부 요구사항이 빠져 있을 수 있다.
    """
    inner = file_name.split(" > ")[-1]
    rank = _keyword_rank(inner)
    if rank is not None and rank < 2:
        return "rfp"
    compact = _WHITESPACE_RE.sub("", inner)
    if rank == 2 or any(k in compact for k in NOTICE_NAME_KEYWORDS) or NOTICE_WEAK_KEYWORD in compact:
        return "notice"
    return "rfp"


def pick_rfp_attachment(attachments: Sequence[Mapping[str, Any]]) -> int | None:
    """제안요청서로 보이는 첨부의 인덱스를 고른다. 없으면 None(추측하지 않는다)."""
    best: tuple[int, int, int] | None = None
    best_index: int | None = None

    for index, attachment in enumerate(attachments):
        name = str(attachment.get("name") or "")
        url = str(attachment.get("url") or "")
        if not url:
            continue
        rank = _keyword_rank(name)
        if rank is None:
            continue
        score = (rank, _extension_rank(name), index)
        if best is None or score < best:
            best, best_index = score, index

    return best_index


# --------------------------------------------------------------------------
# 4) 다운로드
# --------------------------------------------------------------------------


def _content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def download_attachment(
    url: str,
    *,
    file_name: str,
    notice_id: str,
    index: int = 0,
    allow_fetch: bool = False,
) -> Path:
    """첨부를 캐시 디렉터리에 내려받고 로컬 경로를 반환한다.

    이미 캐시에 있으면 재다운로드하지 않는다. **캐시에 없고 `ATTACHMENT_FETCH` 가 꺼져 있으면
    내려받지 않고 `AttachmentFetchDisabledError`** 를 던진다 (19차 §4-A-4) — 고정 모드에서
    4단계 「요구사항 정리표 생성」이 조용히 실호출하던 길을 막는다.

    `allow_fetch` 는 **사람이 확인 창에서 파일 이름을 보고 누른 한 건**이다 (27차 §3-A-2).
    `ATTACHMENT_FETCH` 의 뜻 · 기본값은 그대로이고, 그렇게 받으면 로그에 한 줄을 남긴다.
    """
    ensure_allowed_url(url)
    target = cache_path(notice_id, index, file_name)
    if target.exists() and target.stat().st_size > 0:
        if html_page_title(target, file_name) is None:
            return target
        target.unlink()  # 예전에 안내 화면이 첨부로 저장된 것 — 지우고 다시 받는다
    globally_enabled = attachment_fetch_enabled()
    if not (globally_enabled or allow_fetch):
        # 설정 이름은 로그에만 — 화면 문구에 개발자 설정 이름을 쓰지 않는다 (27차 §2).
        logger.info("첨부 내려받기 꺼짐(ATTACHMENT_FETCH=0) — %s 첨부 %d 받지 않음", notice_id, index)  # 화면 문장 아님(서버 로그)
        raise AttachmentFetchDisabledError("새 공고 받기가 꺼져 있어 저장해 둔 첨부만 씁니다")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    written = 0

    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                # 리다이렉트 최종 목적지도 허용 도메인이어야 한다.
                ensure_allowed_url(str(response.url))
                response.raise_for_status()

                declared = _content_length(response.headers)
                if declared is not None and declared > MAX_DOWNLOAD_BYTES:
                    raise AttachmentTooLargeError(
                        f"첨부가 상한({MAX_DOWNLOAD_BYTES} bytes)을 초과합니다: {declared} bytes"
                    )

                with tmp.open("wb") as handle:
                    async for chunk in response.aiter_bytes(CHUNK_SIZE):
                        written += len(chunk)
                        if written > MAX_DOWNLOAD_BYTES:
                            raise AttachmentTooLargeError(
                                f"첨부가 상한({MAX_DOWNLOAD_BYTES} bytes)을 초과해 중단했습니다"
                            )
                        handle.write(chunk)
    except httpx.HTTPStatusError as exc:
        tmp.unlink(missing_ok=True)
        raise AttachmentDownloadError(
            f"첨부 다운로드 실패 (HTTP {exc.response.status_code})"
        ) from exc
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise AttachmentDownloadError(f"첨부 다운로드 실패: {exc}") from exc
    except AttachmentError:
        tmp.unlink(missing_ok=True)
        raise

    if written == 0:
        tmp.unlink(missing_ok=True)
        raise AttachmentDownloadError("첨부 응답이 비어 있습니다")
    title = html_page_title(tmp, file_name)
    if title is not None:
        tmp.unlink(missing_ok=True)
        raise AttachmentDownloadError(
            "나라장터가 첨부 파일 대신 안내 화면을 보냈습니다" + (f"(「{title}」)" if title else "")
            + " — 조달청 점검이 끝난 뒤 다시 받으세요"
        )

    tmp.replace(target)
    if allow_fetch and not globally_enabled:
        logger.info(
            "첨부 받음(사람 확인) — 공고 %s · 첨부 %d · %s · %d바이트", notice_id, index, target.name, written
        )
    return target
