"""기업마당 **공고문 원본**과 거기서 뽑은 텍스트 저장소 (0924.md §4-A-1 · ISSUE-096).

## 왜 필요한가

앱은 기업마당을 **요약문·해시태그로만** 판정했다. 그래서 1,605건 대부분이 55점
「확인 필요」에 묶였고, 검수자가 공고문을 직접 읽어 만든 기준 답안과 견주면 1순위가 앱
66위, 2순위가 107위, **불가인 것이 27위 「우선 검토」**였다
(`docs/reports/2026-09-24_bizinfo_candidates.md` §3).

판정에 쓰이는 조건 — 본사 소재, 조직 형태, 고용 인원, 창업 연차, 매출, 선행사업, 역할,
정부지원 비율, 제외 조항 — 은 **공고문에만** 있다. 앱이 공고문을 읽어야 같은 표가 나온다.

## 무엇을 하는가

    목록 항목 → fileDown.do 로 원본 내려받기 → <pblancId>.<ext>
                                             → document_extractor → <pblancId>.txt
                                             → index.json 에 결과 한 줄

- 저장 위치는 **비공개**다(`data/private/bizinfo_docs/`, Git 제외). 기관이 만든 공고문을
  공개 저장소에 담지 않는다.
- **공고당 한 번만 받는다.** 이미 받은 것은 건너뛴다 — 파일 서버를 예의 있게 쓴다.
- 실패·이미지는 **사유와 함께 기록한다.** 「없음」과 「못 읽었음」은 다른 사실이다.

## 이미지 공고문

포스터 한 장짜리(JPG·PNG) 공고가 있고, 텍스트가 없는 이미지 PDF 도 있다. OCR 은 쓰지
않는다 — 그 대신 `status="image"` 로 남기고 화면이 「공고문 이미지 · 요약문 기준」이라고
적는다. 못 읽은 것을 읽은 척하지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from app.core import storage
from app.core.paths import DATA_ROOT
from app.services import bizinfo_client, document_extractor, wording

logger = logging.getLogger(__name__)

#: 공고문 원본과 추출 텍스트가 사는 곳. **비공개**다 (Git 제외).
DOCS_DIR = DATA_ROOT / "private" / "bizinfo_docs"
INDEX_FILE = DOCS_DIR / "index.json"

STORE_VERSION = 1

#: 텍스트가 이보다 짧으면 「읽었다」고 보지 않는다. 이미지 PDF 가 공백 몇 자를 준다.
MIN_TEXT_CHARS = 200

#: 텍스트를 뽑을 수 없는 형식. 받아 두기는 하지만 판정은 요약문으로 한다.
IMAGE_SUFFIXES = frozenset({"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff"})

#: 공고문 하나의 처리 결과.
#:
#: text   — 텍스트를 뽑았다 (판정에 쓴다)
#: image  — 이미지 공고문이라 텍스트가 없다 (요약문으로 판정한다)
#: failed — 내려받기·추출이 실패했다 (사유를 남긴다)
DocumentStatus = Literal["text", "image", "failed"]

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class DocumentRecord:
    """공고문 한 건의 처리 기록. 화면·보고서가 이것을 그대로 센다."""

    program_id: str
    status: DocumentStatus
    file_name: str | None = None
    suffix: str | None = None
    bytes: int = 0
    pages: int = 0
    chars: int = 0
    downloaded_at: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "status": self.status,
            "file_name": self.file_name,
            "suffix": self.suffix,
            "bytes": self.bytes,
            "pages": self.pages,
            "chars": self.chars,
            "downloaded_at": self.downloaded_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "DocumentRecord | None":
        program_id = str(row.get("program_id") or "").strip()
        status = row.get("status")
        if not program_id or status not in ("text", "image", "failed"):
            return None
        return cls(
            program_id=program_id,
            status=status,  # type: ignore[arg-type]
            file_name=row.get("file_name"),
            suffix=row.get("suffix"),
            bytes=int(row.get("bytes") or 0),
            pages=int(row.get("pages") or 0),
            chars=int(row.get("chars") or 0),
            downloaded_at=row.get("downloaded_at"),
            # 저장된 메모는 **그대로** 읽는다 — 읽을 때 바꾸면 다음 수집이 색인을 새 글로 다시 저장했다(33차 R32-13).
            # 옛 메모 → 새 말은 화면으로 내보내는 곳(`support_requirement_extractor.load`)에서만.
            note=row.get("note"),
        )


@dataclass
class DocumentIndex:
    """받아 둔 공고문 전체의 목록. 파일이 없으면 빈 목록이다."""

    records: dict[str, DocumentRecord] = field(default_factory=dict)
    #: 과제소개서([별첨 1]) — 공고 id → 받은 기록 (30차 §3-A). 공고문 기록과 따로 센다.
    annexes: dict[str, DocumentRecord] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        out = {"total": len(self.records), "text": 0, "image": 0, "failed": 0}
        for record in self.records.values():
            out[record.status] += 1
        return out


def _safe_id(program_id: str) -> str:
    """파일 이름으로 쓸 수 있는 공고 id 인가. 아니면 거부한다 (경로 탈출 방지)."""
    value = (program_id or "").strip()
    if not _ID_RE.match(value):
        raise ValueError(f"공고 id 형식이 아닙니다: {program_id!r}")
    return value


def text_path(program_id: str) -> Path:
    return DOCS_DIR / f"{_safe_id(program_id)}.txt"


#: 과제소개서 파일 이름 꼬리 — `plan_form_service.annex_excerpt` 가 이 이름을 읽는다(30차 §3-A).
ANNEX_TAG = "annex1"


def annex_text_path(program_id: str) -> Path:
    return DOCS_DIR / f"{_safe_id(program_id)}.{ANNEX_TAG}.txt"


def annex_record(program_id: str) -> DocumentRecord | None:
    """받아 둔 과제소개서 기록(받은 시각 · 쪽 · 글자 수 · 원래 이름). 없으면 None."""
    try:
        record = load_index().annexes.get(_safe_id(program_id))
    except ValueError:
        return None
    # 옛 기록은 공고문 메모 글을 그대로 담았다 — 과제소개서 말로(32차 R31-34)
    if record is not None and wording.modernize_text(record.note or "") in (IMAGE_NOTE, NO_TEXT_NOTE):
        return replace(record, note=ANNEX_UNREADABLE_NOTE)
    return record


def _binary_path(program_id: str, suffix: str) -> Path:
    return DOCS_DIR / f"{_safe_id(program_id)}.{suffix}"


#: 목록 파일을 읽은 결과를 잠깐 들고 있는다 (파일 수정 시각이 열쇠다).
#:
#: 통합 목록은 지원사업 1,605건을 한 번에 훑는다. 건마다 목록 파일을 다시 읽으면
#: 같은 JSON 을 1,605번 파싱한다.
_INDEX_CACHE: tuple[int, "DocumentIndex"] | None = None


def load_index() -> DocumentIndex:
    global _INDEX_CACHE
    try:
        stamp = INDEX_FILE.stat().st_mtime_ns
    except OSError:
        stamp = 0
    if _INDEX_CACHE is not None and _INDEX_CACHE[0] == stamp:
        return _INDEX_CACHE[1]
    index = _read_index()
    _INDEX_CACHE = (stamp, index)
    return index


def _read_index() -> DocumentIndex:
    try:
        payload = storage.read_json(INDEX_FILE, default=None)
    except storage.CorruptJsonError:
        logger.warning("공고문 목록 파일이 깨져 빈 목록으로 시작합니다: %s", INDEX_FILE)
        return DocumentIndex()
    if not isinstance(payload, dict):
        return DocumentIndex()
    records: dict[str, DocumentRecord] = {}
    for row in payload.get("records") or []:
        if not isinstance(row, dict):
            continue
        record = DocumentRecord.from_dict(row)
        if record is not None:
            records[record.program_id] = record
    annexes: dict[str, DocumentRecord] = {}
    for row in payload.get("annexes") or []:
        record = DocumentRecord.from_dict(row) if isinstance(row, dict) else None
        if record is not None:
            annexes[record.program_id] = record
    return DocumentIndex(records=records, annexes=annexes)


def save_index(index: DocumentIndex) -> Path:
    global _INDEX_CACHE
    _INDEX_CACHE = None
    # 일괄 받기(collect_daily · 다른 프로세스)는 시작 때 읽은 색인을 끝에 통째로 쓴다 — 그 사이 단추로 받은 과제소개서 기록이
    # 사라졌다. 쓰기 직전 파일의 annexes 를 다시 읽어, 이 색인에 없는 것은 살린다(30차 §4 마지막 검토). 같은 공고가 양쪽에
    # 있으면 **늦게 받은 기록**을 남긴다 — 일괄 받기의 옛 기록이 단추로 새로 받은 기록을 덮었다(31차 R30-24).
    on_disk = storage.read_json(INDEX_FILE, default=None)
    if isinstance(on_disk, dict):
        for row in on_disk.get("annexes") or []:
            pid = row.get("program_id") if isinstance(row, dict) else None
            if not pid:
                continue
            record = DocumentRecord.from_dict(row)
            if record is None:
                continue
            mine = index.annexes.get(pid)
            if mine is None or (record.downloaded_at or "") > (mine.downloaded_at or ""):
                index.annexes[pid] = record
    payload = {
        "_note": "기업마당 공고문 내려받기·추출 기록 (내부 전용, Git 제외).",
        "store_version": STORE_VERSION,
        "counts": index.counts(),
        "records": [r.to_dict() for r in sorted(index.records.values(), key=lambda r: r.program_id)],
        "annexes": [r.to_dict() for r in sorted(index.annexes.values(), key=lambda r: r.program_id)],
    }
    storage.stamp(payload)
    return storage.write_json_atomic(INDEX_FILE, payload, compact=True)


def load_text(program_id: str) -> str | None:
    """추출해 둔 공고문 텍스트. 없으면 None — 「빈 공고문」이 아니라 「아직 없다」이다."""
    try:
        path = text_path(program_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("공고문 텍스트를 읽지 못했습니다: %s", path.name, exc_info=True)
        return None


def known_ids() -> set[str]:
    """이미 처리한 공고 id. **실패한 것도 포함한다** — 같은 것을 매일 다시 받지 않는다."""
    return set(load_index().records)


#: 그림 공고문 · 글 없는 문서 — `fetch_one` 이 이 글로 「image」 상태를 가른다.
IMAGE_NOTE = "공고문이 그림 파일이라 글을 읽지 못해, 기업마당 요약만 보고 판정했습니다"
NO_TEXT_NOTE = "공고문 파일에 글이 없어(그림 문서) 기업마당 요약만 보고 판정했습니다"
#: 과제소개서는 판정에 쓰지 않는다 — 그림(스캔) 파일이면 과제 절 발췌 없이 초안을 만든다는 사실만(32차 R31-34).
ANNEX_UNREADABLE_NOTE = "과제소개서가 그림(스캔) 파일이라 글자를 읽지 못했습니다 — 과제 절 발췌 없이 초안을 만듭니다. 과제 내용은 파일을 직접 보고 채우세요"


def _extract(path: Path, suffix: str) -> tuple[list[str], str | None]:
    """텍스트를 쪽별로 뽑는다. 못 뽑으면 `([], 사유)`. 느리다(PDF 99쪽 15~20초) — 이벤트 루프에서는 `asyncio.to_thread` 로."""
    if suffix in IMAGE_SUFFIXES:
        return [], IMAGE_NOTE
    try:
        document = document_extractor.extract_document(path)
    except document_extractor.DocumentExtractionError as exc:
        return [], f"원문 읽기 실패 — {exc}"
    except Exception as exc:  # noqa: BLE001 — 깨진 첨부 하나가 수집 전체를 죽이지 않게
        # 예외 이름 · 원문은 로그로만 — 원문 칸에는 사람 말만 (28차)
        logger.warning("기업마당 원문 읽기 실패 %s: %s: %s", path.name, type(exc).__name__, exc)
        return [], "원문 읽기 실패 — 파일을 열지 못했습니다(깨졌거나 지원하지 않는 형식)"
    pages = [page.text for page in document.pages]
    if sum(len(t) for t in pages) < MIN_TEXT_CHARS:
        return [], NO_TEXT_NOTE
    return pages, None


#: 쪽 구분자. 조항의 **페이지 근거**를 남기려고 텍스트 파일에 그대로 적어 둔다.
PAGE_MARK = "\f[쪽 {page}]\n"

_PAGE_MARK_RE = re.compile(r"\f\[쪽 (\d+)\]\n")


def join_pages(pages: Iterable[str]) -> str:
    """쪽 구분자를 끼워 한 덩어리로. 페이지 번호를 잃지 않기 위한 것이다."""
    return "".join(PAGE_MARK.format(page=index) + text for index, text in enumerate(pages, start=1))


def split_pages(text: str) -> list[tuple[int, str]]:
    """`join_pages` 가 만든 텍스트를 `(쪽, 본문)` 으로 되돌린다. 구분자가 없으면 1쪽 하나."""
    marks = list(_PAGE_MARK_RE.finditer(text))
    if not marks:
        return [(1, text)]
    out: list[tuple[int, str]] = []
    for index, match in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        out.append((int(match.group(1)), text[match.end() : end]))
    return out


async def fetch_one(item: dict[str, Any], *, force: bool = False) -> DocumentRecord:
    """공고문 하나를 받아 텍스트까지 만든다. 이미 있으면 받지 않는다(`force` 로 다시 받는다)."""
    program_id = _safe_id(str(item.get("pblancId") or ""))
    suffix = bizinfo_client.announcement_extension(item)
    binary = _binary_path(program_id, suffix)
    now = datetime.now(timezone.utc).isoformat()

    if force or not binary.exists():
        try:
            await bizinfo_client.download_announcement(item, target=binary)
        except bizinfo_client.BizinfoDocumentError as exc:
            return DocumentRecord(
                program_id=program_id,
                status="failed",
                file_name=item.get("printFileNm"),
                suffix=suffix,
                downloaded_at=now,
                note=str(exc),
            )

    pages, note = await asyncio.to_thread(_extract, binary, suffix)
    if not pages:
        return DocumentRecord(
            program_id=program_id,
            status="image" if (suffix in IMAGE_SUFFIXES or note in (IMAGE_NOTE, NO_TEXT_NOTE)) else "failed",
            file_name=item.get("printFileNm"),
            suffix=suffix,
            bytes=binary.stat().st_size if binary.exists() else 0,
            downloaded_at=now,
            note=note,
        )

    body = join_pages(pages)
    path = text_path(program_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return DocumentRecord(
        program_id=program_id,
        status="text",
        file_name=item.get("printFileNm"),
        suffix=suffix,
        bytes=binary.stat().st_size if binary.exists() else 0,
        pages=len(pages),
        chars=sum(len(t) for t in pages),
        downloaded_at=now,
    )


async def fetch_annex(item: dict[str, Any], index: int) -> DocumentRecord:
    """과제소개서 첨부 한 개를 받아 `{id}.annex1.{확장자}` · 텍스트 `{id}.annex1.txt` 로 두고 색인에 적는다 (30차 §3-A).

    부르는 곳은 사람이 누른 단추와 명시 실행 스크립트뿐이다 — 자동 · 일괄로 받지 않는다. 실패도 색인에 남긴다.
    """
    program_id = _safe_id(str(item.get("pblancId") or ""))
    _file_id, _file_sn, name, suffix = bizinfo_client.attachment_ref(item, index)  # 주소 · 형식 검사(실패하면 예외)
    binary = DOCS_DIR / f"{program_id}.{ANNEX_TAG}.{suffix}"
    now = datetime.now(timezone.utc).isoformat()
    try:
        await bizinfo_client.download_attachment(item, index, target=binary)
        # 99쪽 PDF 글자 읽기가 15~20초 — 이벤트 루프에서 돌리면 서버 전체가 멈췄다(31차 R30-20)
        pages, note = await asyncio.to_thread(_extract, binary, suffix)
    except bizinfo_client.BizinfoDocumentError as exc:
        pages, note = [], str(exc)
    if not pages and note in (IMAGE_NOTE, NO_TEXT_NOTE):
        note = ANNEX_UNREADABLE_NOTE
    if pages:
        path = annex_text_path(program_id)
        await asyncio.to_thread(_write_text, path, join_pages(pages))
    record = DocumentRecord(
        program_id=program_id,
        status="text" if pages else "failed",
        file_name=name,
        suffix=suffix,
        bytes=binary.stat().st_size if binary.exists() else 0,
        pages=len(pages),
        chars=sum(len(t) for t in pages),
        downloaded_at=now,
        note=note,
    )
    await asyncio.to_thread(_save_annex_record, record)
    return record


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _save_annex_record(record: DocumentRecord) -> None:
    index_file = load_index()
    index_file.annexes[record.program_id] = record
    save_index(index_file)


async def fetch_many(
    items: list[dict[str, Any]], *, limit: int | None = None, force: bool = False
) -> tuple[DocumentIndex, list[DocumentRecord]]:
    """여러 건을 순서대로 받는다. 이미 처리한 것은 건너뛴다.

    **동시에 여러 개를 받지 않는다.** 남의 파일 서버다 — 한 번에 하나씩 예의 있게 받는다.
    """
    index = load_index()
    fresh: list[DocumentRecord] = []
    for item in items:
        program_id = str(item.get("pblancId") or "").strip()
        if not program_id or not _ID_RE.match(program_id):
            continue
        if not force and program_id in index.records:
            continue
        if limit is not None and len(fresh) >= limit:
            break
        try:
            record = await fetch_one(item, force=force)
        except ValueError:
            continue
        index.records[record.program_id] = record
        fresh.append(record)
    if fresh:
        save_index(index)
    return index, fresh
