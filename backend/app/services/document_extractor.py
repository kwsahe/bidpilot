"""공고 첨부문서 텍스트 추출 (HWP 5.x / HWPX / PDF).

나라장터 제안요청서는 대부분 HWP(한글) 또는 HWPX이고 PDF가 함께 올라오기도 한다.
세 형식 모두 '문단 + 위치(페이지 또는 문단 묶음 순번)'를 보존해 추출한다.
Requirement의 page/source_text 근거를 남기기 위해 위치 정보를 절대 버리지 않는다.

- PDF   : pdfplumber (페이지 번호 그대로)
- HWPX  : zip + section XML
- HWP5  : OLE2 -> BodyText/Section* -> zlib raw-deflate -> 레코드 파싱 후
          HWPTAG_PARA_TEXT(67) 문단 텍스트
          (pyhwp는 Python 3.12에서 동작하지 않아 직접 파싱한다)
"""

from __future__ import annotations

import logging
import re
import shutil
import struct
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterator, Literal, Sequence
from xml.etree import ElementTree as ET

import olefile
import pdfplumber

#: 「docx」 — 회사자료 · 직접 넣은 공고문(38차 §3-E)만. 나라장터 첨부의 압축 판별(`detect_format`)은 그대로다.
logger = logging.getLogger(__name__)

DocumentFormat = Literal["pdf", "hwp", "hwpx", "zip", "docx", "unknown"]

HWPTAG_PARA_TEXT = 67
_HEADER_FLAG_OFFSET = 36

# HWP5 제어 문자 (한글문서파일형식 5.0 '제어 문자' 표). 폭이 세 가지다.
#  - char     : 0, 10, 13         — 1 word. 문단/줄 나눔.
#  - inline   : 4~9, 19, 20       — 8 word. 필드 끝, title mark, 탭 등.
#  - extended : 1~3, 11~18, 21~23 — 8 word. 구역 정의, 표, 각주, 자동번호 등.
#  - 24~31    : 예약, 1 word.
#
# inline과 extended는 둘 다 16바이트를 차지한다. 여는 코드 뒤에 파라미터 6워드가
# 오고 같은 코드로 닫힌다. 이 6워드를 건너뛰지 않으면 본문에 리터럴로 새어나온다.
# inline 쪽이 빠져 있어서 목차의 "…보안준수사항" 뒤 탭에서 chr(0x8322) 같은
# 문자가 그대로 튀어나왔다.
_INLINE_CONTROL_CHARS = {4, 5, 6, 7, 8, 9, 19, 20}
_EXTENDED_CONTROL_CHARS = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
_WIDE_CONTROL_CHARS = _INLINE_CONTROL_CHARS | _EXTENDED_CONTROL_CHARS

_TAB_CONTROL = 9

# HWP/HWPX는 본문에 페이지 정보가 없어 문단을 묶어 '페이지'로 근사한다.
PARAGRAPHS_PER_PAGE = 40


class DocumentExtractionError(RuntimeError):
    """문서 텍스트 추출 실패."""


@dataclass
class DocumentPage:
    page: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ExtractedDocument:
    file_name: str
    doc_format: DocumentFormat
    pages: list[DocumentPage] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def empty_pages(self) -> list[int]:
        return [p.page for p in self.pages if not p.text.strip()]


def detect_format(path: Path) -> DocumentFormat:
    """확장자가 아니라 파일 시그니처로 판별한다 (확장자가 틀린 첨부가 흔하다)."""
    head = path.read_bytes()[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    if head.startswith(b"PK\x03\x04"):
        # HWPX도 ZIP이다. 내부 구조를 봐야 일반 압축 첨부와 구분된다.
        return "hwpx" if _looks_like_hwpx(path) else "zip"
    return "unknown"


def _looks_like_hwpx(path: Path) -> bool:
    """ZIP 안에 HWPX 본문(Contents/sectionN.xml)이 있는지."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False
    return any(_SECTION_RE.match(name) for name in names)


# 압축 첨부 안에서 제안요청서를 고를 때 쓰는 이름 우선순위.
_ZIP_NAME_PRIORITY: tuple[tuple[str, ...], ...] = (
    ("제안요청서", "과업지시서", "과업내용서"),
    ("입찰공고", "공고문"),
    ("사업계획", "규격서", "시방서"),
)
_ZIP_EXT_PRIORITY: tuple[str, ...] = (".hwpx", ".hwp", ".pdf")
#: 입찰공고문을 먼저 고르는 순서 (19차 — 참가자격 절은 공고문에 있다).
ZIP_NOTICE_PRIORITY: tuple[tuple[str, ...], ...] = (
    ("입찰공고", "공고서", "공고문", "재공고"),
)


def _zip_member_score(
    name: str, priority: tuple[tuple[str, ...], ...] | None = None
) -> tuple[int, int] | None:
    """압축 안 파일의 우선순위. 텍스트를 못 뽑는 형식이면 None."""
    suffix = Path(name).suffix.lower()
    if suffix not in _ZIP_EXT_PRIORITY:
        return None
    compact = "".join(name.split())
    order = priority or _ZIP_NAME_PRIORITY
    keyword_rank = len(order)
    for rank, keywords in enumerate(order):
        if any(keyword in compact for keyword in keywords):
            keyword_rank = rank
            break
    return (keyword_rank, _ZIP_EXT_PRIORITY.index(suffix))


def zip_display_names(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """압축 안 파일 이름 → 항목. UTF-8 표시가 없는 이름은 한글 Windows(cp949)로 다시 읽는다(43차 M8 · ELIG-08 —
    「4. ┴ª╛╚┐Σ├╗╝¡.hwpx」가 원래 「4. 제안요청서.hwpx」라 제안요청서를 못 골랐다)."""
    out: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        name = info.filename
        if not info.flag_bits & 0x800:
            try:
                name = info.filename.encode("cp437").decode("cp949")
            except (UnicodeEncodeError, UnicodeDecodeError):
                name = info.filename
        out[name] = info
    return out


def pick_zip_member(
    names: Sequence[str], priority: tuple[tuple[str, ...], ...] | None = None
) -> str | None:
    """압축 첨부 안에서 열 파일을 고른다. 없으면 None (추측하지 않는다).

    기본은 제안요청서가 먼저다. `priority` 를 주면 그 순서로 고른다 — 참가자격을 읽을 때는
    공고문(`ZIP_NOTICE_PRIORITY`)이 먼저다. 그 순서에 맞는 것이 **없으면** None 이다.
    """
    best: tuple[tuple[int, int], str] | None = None
    for name in names:
        if name.endswith("/"):
            continue
        # 경로 이동이 섞인 항목은 열지 않는다.
        if ".." in Path(name).parts:
            continue
        score = _zip_member_score(name, priority)
        if score is None:
            continue
        if priority is not None and score[0] >= len(priority):
            continue  # 원하는 종류가 아니다 — 다른 문서를 대신 열지 않는다
        if best is None or score < best[0]:
            best = (score, name)
    return best[1] if best else None


#: 압축을 풀었을 때 허용하는 한 파일의 최대 크기 (ISSUE-025).
#: 나라장터 제안요청서는 큰 것이 30MB 안쪽이다. 200MB 는 충분히 여유 있는 상한이다.
MAX_UNCOMPRESSED_BYTES: Final[int] = 200 * 1024 * 1024

#: 허용하는 압축비. 텍스트 문서는 10:1 안쪽이고, 1000:1 이면 정상 문서가 아니다.
MAX_COMPRESSION_RATIO: Final[int] = 200

#: 압축비를 보기 시작하는 풀린 크기(40차 MANUAL-03) — 작은 칸(빈 표 · 머리말)은 압축비가 높아도 정상이라 이 크기를 넘을 때만 본다.
RATIO_FLOOR_BYTES: Final[int] = 1024 * 1024

#: 압축 안의 압축까지만 본다. 그 안의 또 압축은 열지 않는다.
MAX_ZIP_DEPTH: Final[int] = 1


def _check_zip_member(info: zipfile.ZipInfo) -> None:
    """풀기 전에 «선언된» 크기와 압축비를 본다 (ISSUE-025).

    예전에는 상한이 없었다. `zf.read()` 는 헤더가 뭐라 적혀 있든 끝까지 읽고,
    임시 폴더 복사에도 바이트 세기가 없었다. 몇 KB 짜리 첨부가 수 GB 로 펼쳐지면
    서버 메모리·디스크가 먼저 죽는다. 업로드 경로는 공개 데모에서도 열려 있다.

    헤더의 `file_size` 는 만든 쪽이 적는 값이라 «믿을 수는 없지만», 거짓말이면
    실제 복사에서 바이트 세기가 다시 막는다. 둘 다 둔다.
    """
    if info.file_size > MAX_UNCOMPRESSED_BYTES:
        raise DocumentExtractionError(
            f"압축을 풀면 너무 큽니다({info.file_size // (1024 * 1024)}MB). "
            f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB 이하 파일만 처리합니다."
        )
    if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise DocumentExtractionError("압축 비율이 비정상적으로 높습니다. 정상 문서인지 확인해 주세요.")


def _copy_with_limit(src, dst) -> None:
    """복사하면서 바이트를 센다. 헤더가 거짓말을 해도 여기서 멈춘다."""
    written = 0
    while True:
        chunk = src.read(1024 * 1024)
        if not chunk:
            return
        written += len(chunk)
        if written > MAX_UNCOMPRESSED_BYTES:
            raise DocumentExtractionError(
                f"압축을 푸는 중 {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB 를 넘었습니다. 정상 문서인지 확인해 주세요."
            )
        dst.write(chunk)


def extract_zip(
    path: Path,
    *,
    file_name: str | None = None,
    depth: int = 0,
    zip_priority: tuple[tuple[str, ...], ...] | None = None,
) -> ExtractedDocument:
    """압축 첨부에서 제안요청서 1건을 꺼내 텍스트를 추출한다.

    나라장터에는 공고문·제안요청서·서식을 ZIP 하나로 묶어 올리는 기관이 있다.
    안에서 제안요청서로 볼 파일을 고르고, 없으면 만들어내지 않고 실패시킨다.

    `depth` 는 압축 안의 압축을 몇 번까지 따라갈지다. 무제한이면 한 파일로 서버를
    재귀에 빠뜨릴 수 있다 (ISSUE-025).
    """
    if depth > MAX_ZIP_DEPTH:
        raise DocumentExtractionError("압축 안에 압축이 여러 겹입니다. 풀어서 다시 올려 주세요.")
    try:
        with zipfile.ZipFile(path) as archive:
            names = zip_display_names(archive)
            member = pick_zip_member(list(names), zip_priority)
            if member is None:
                raise DocumentExtractionError(
                    f"압축 안에서 제안요청서로 볼 파일을 찾지 못했습니다 (들어 있는 파일: {', '.join(list(names)[:8])})"
                )
            info = names[member]
            _check_zip_member(info)
            with tempfile.TemporaryDirectory() as tmp_dir:
                target = Path(tmp_dir) / Path(member).name
                with archive.open(info) as src, target.open("wb") as dst:
                    _copy_with_limit(src, dst)
                inner = extract_document(target, file_name=Path(member).name, depth=depth + 1)
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionError("압축 파일을 열지 못했습니다. 손상된 파일인지 확인해 주세요.") from exc

    # 압축 안에서 무엇을 열었는지 파일명에 남긴다 (근거 추적).
    label = f"{file_name or path.name} > {inner.file_name}"
    return ExtractedDocument(file_name=label, doc_format=inner.doc_format, pages=inner.pages)


def extract_zip_all(path: Path, *, file_name: str | None = None) -> list[ExtractedDocument]:
    """압축 첨부 안 문서를 **모두** 꺼낸다 — 제안서 목차 · 평가표가 과업지시서가 아닌 다른 문서(「제안서 작성방법」)에 있을 수 있다
    (11-06 1697240). 텍스트를 못 뽑는 형식 · 깨진 문서는 건너뛰고(이름 깨짐 허용 — 임시 파일은 순번 이름), 압축 안 압축은 열지 않는다.
    크기 · 압축비 상한은 `extract_zip` 과 같다 — 상한에 걸린 문서도 그 문서만 건너뛴다(빈 서식 PDF 하나가 압축 전체를 막지 않게).
    꺼낸 임시 파일은 읽은 뒤 바로 지운다."""
    out: list[ExtractedDocument] = []
    label = file_name or path.name
    try:
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as tmp_dir:
            for n, (name, info) in enumerate(zip_display_names(archive).items()):
                if name.endswith("/") or ".." in Path(name).parts or _zip_member_score(name) is None:
                    continue
                target = Path(tmp_dir) / f"{n}{Path(name).suffix.lower()}"
                try:
                    _check_zip_member(info)
                    with archive.open(info) as src, target.open("wb") as dst:
                        _copy_with_limit(src, dst)
                    inner = extract_document(target, file_name=Path(name).name, depth=MAX_ZIP_DEPTH)
                # 깨진 PDF(PdfminerException) · 깨진 HWPX(ParseError)도 그 문서만 뺀다 — 압축 전체가 버려졌다(11-06 검토 #12)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("압축 안 문서를 읽지 못했습니다: %s (%s)", name, type(exc).__name__)
                    continue
                finally:
                    target.unlink(missing_ok=True)
                out.append(ExtractedDocument(file_name=f"{label} > {inner.file_name}", doc_format=inner.doc_format, pages=inner.pages))
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionError("압축 파일을 열지 못했습니다. 손상된 파일인지 확인해 주세요.") from exc
    return out


#: 두 단 판별 (20차 §4-A · ISSUE-137). 실측: 한양사이버대 공고문 1쪽은 왼쪽 단이 「입찰참가자격」,
#: 오른쪽 단이 「입찰의 무효」라 `extract_text()` 가 줄마다 두 단을 이어 붙였다.
#: - 빈 띠: 낱말 x 구간을 합친 뒤 남는 틈이 쪽 너비의 3% 이상 (그 쪽은 12.5%)
#: - 양쪽 단이 세로로 쪽 높이의 60% 이상 겹친다 (표 옆 여백·꼬리 한 줄은 두 단이 아니다)
#: - 표가 그 띠를 가로지르지 않는다
#: - 양쪽 단이 각각 쪽 너비의 25% 이상 — 번호만 늘어선 내어쓰기 목록 · 쪽 번호만 오른쪽에 붙은 목차는
#:   「단」이 아니다 (그 쪽은 두 단 모두 40% 남짓)
#: - 양쪽 단이 각각 낱말의 25% 이상 — 칸 선 없는 표의 머리 칸(분류 이름 몇 개)은 「단」이 아니다
#:   (기업마당 122609 6쪽은 19%, 그 쪽은 49% · 51%)
#: - 그런 띠가 **딱 하나**일 때만 — 세 단 이상은 나누지 않는다
COLUMN_GAP_MIN_RATIO: Final[float] = 0.03
COLUMN_OVERLAP_MIN_RATIO: Final[float] = 0.6
COLUMN_MIN_WIDTH_RATIO: Final[float] = 0.25
COLUMN_MIN_WORD_SHARE: Final[float] = 0.25


def _column_cut(page: "pdfplumber.page.Page") -> float | None:
    """두 단이면 가르는 x 좌표, 아니면 None."""
    left_x, top, right_x, bottom = page.bbox
    # 쪽 밖(MediaBox 너머)에 찍힌 글자는 세지 않는다 — 그 글자로 띠를 잡으면 자르는 선이 쪽 밖에 떨어져
    # `crop()` 이 ValueError 를 낸다(예전 `extract_text()` 는 그런 쪽도 읽었다).
    words = [w for w in page.extract_words() if w["x0"] >= left_x and w["x1"] <= right_x]
    if len(words) < 2:
        return None
    width, height = right_x - left_x, bottom - top
    spans = sorted((w["x0"], w["x1"]) for w in words)
    gaps: list[tuple[float, float]] = []
    reach = spans[0][1]
    for start, end in spans[1:]:
        if start - reach >= width * COLUMN_GAP_MIN_RATIO:
            gaps.append((reach, start))
        reach = max(reach, end)
    cuts: list[float] = []
    for gap_left, gap_right in gaps:
        left = [w for w in words if w["x1"] <= gap_left]
        right = [w for w in words if w["x0"] >= gap_right]
        overlap = min(max(w["bottom"] for w in left), max(w["bottom"] for w in right)) - max(
            min(w["top"] for w in left), min(w["top"] for w in right)
        )
        if overlap < height * COLUMN_OVERLAP_MIN_RATIO:
            continue
        left_width = gap_left - min(w["x0"] for w in left)
        right_width = max(w["x1"] for w in right) - gap_right
        if min(left_width, right_width) < width * COLUMN_MIN_WIDTH_RATIO:
            continue
        if min(len(left), len(right)) < (len(left) + len(right)) * COLUMN_MIN_WORD_SHARE:
            continue
        cut = (gap_left + gap_right) / 2
        if any(table.bbox[0] < cut < table.bbox[2] for table in page.find_tables()):
            continue
        cuts.append(cut)
    return cuts[0] if len(cuts) == 1 and left_x < cuts[0] < right_x else None


def _page_text(page: "pdfplumber.page.Page") -> str:
    """쪽 텍스트 — 두 단이면 왼쪽 단 다음 오른쪽 단 순서로 읽는다."""
    cut = _column_cut(page)
    if cut is None:
        return page.extract_text() or ""
    left_x, top, right_x, bottom = page.bbox
    left = page.crop((left_x, top, cut, bottom)).extract_text() or ""
    right = page.crop((cut, top, right_x, bottom)).extract_text() or ""
    return f"{left}\n{right}".strip("\n")


def _check_pdf_streams(path: Path) -> None:
    """PDF 의 FlateDecode 스트림을 **상한을 두고** 미리 풀어 본다(40차 MANUAL-03).

    pdfminer 는 스트림을 `zlib.decompress` 로 상한 없이 푼다 — 306KB PDF 한 장이 315MB 로 펼쳐졌다(압축비 약 1000). 합계가
    `MAX_UNCOMPRESSED_BYTES` 를 넘거나 1MB 넘게 풀린 스트림의 압축비가 `MAX_COMPRESSION_RATIO` 를 넘으면 거절한다. 못 읽는 객체 ·
    암호 · 깨진 스트림은 건너뛴다(본 추출이 원래대로 알린다)."""
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import LITERALS_FLATE_DECODE, PDFStream

    too_big = DocumentExtractionError(
        f"PDF 를 풀면 너무 큽니다({MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB 넘음) 또는 압축 비율이 비정상적으로 높습니다. 정상 문서인지 확인해 주세요."
    )
    total = 0
    try:
        with open(path, "rb") as handle:
            document = PDFDocument(PDFParser(handle))
            seen: set[int] = set()
            for xref in document.xrefs:
                for objid in xref.get_objids():
                    if objid in seen:
                        continue
                    seen.add(objid)
                    try:
                        obj = document.getobj(objid)
                    except Exception:  # noqa: BLE001 — 못 읽는 객체는 본 추출에 맡긴다
                        continue
                    if not isinstance(obj, PDFStream) or obj.rawdata is None:
                        continue
                    if getattr(obj.attrs.get("Subtype"), "name", None) == "Image":
                        continue  # 그림은 글 뽑기가 풀지 않는다 — 빈 바탕 그림은 압축비 1000 이 정상이다(실측 공고문 셋 · 1MB · 1010:1)
                    if not any(name in LITERALS_FLATE_DECODE for name, _params in obj.get_filters()):
                        continue
                    budget = MAX_UNCOMPRESSED_BYTES - total
                    try:
                        inflater = zlib.decompressobj()
                        data = inflater.decompress(obj.rawdata, budget + 1)
                    except zlib.error:
                        continue
                    if inflater.unconsumed_tail or len(data) > budget:
                        raise too_big
                    if len(data) > RATIO_FLOOR_BYTES and len(data) / max(1, len(obj.rawdata)) > MAX_COMPRESSION_RATIO:
                        raise too_big
                    total += len(data)
    except DocumentExtractionError:
        raise
    except Exception:  # noqa: BLE001 — 미리 보기가 실패해도 본 추출이 원래대로 판단한다
        return


def extract_pdf(path: Path) -> list[DocumentPage]:
    _check_pdf_streams(path)
    pages: list[DocumentPage] = []
    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            pages.append(DocumentPage(page=index, text=_page_text(page)))
    return pages


_SECTION_RE = re.compile(r"Contents/section(\d+)\.xml")


def _section_order(name: str) -> int:
    match = _SECTION_RE.match(name)
    return int(match.group(1)) if match else 0


def _check_archive(path: Path) -> None:
    """HWPX · DOCX(압축 파일)를 읽기 전에 칸마다 선언 크기 · 압축비와 합계를 본다(39차 MANUAL-02 — 101KB 가 100MB 로 펼쳐졌다)."""
    try:
        with zipfile.ZipFile(path) as zf:
            total = 0
            for info in zf.infolist():
                _check_zip_member(info)
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise DocumentExtractionError(
                        f"압축을 풀면 너무 큽니다(합계 {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB 넘음). 정상 문서인지 확인해 주세요."
                    )
    except zipfile.BadZipFile:
        return  # 깨진 압축은 읽는 쪽이 원래대로 알린다


def extract_hwpx(path: Path) -> list[DocumentPage]:
    return group_paragraphs(hwpx_paragraphs(path))


def _own_texts(node: ET.Element) -> Iterator[str]:
    """문단 자기 글 — 안에 든 표 칸 문단(중첩 문단)의 글은 건너뛴다."""
    for child in node:
        if child.tag.endswith("}p"):
            continue
        if child.tag.endswith("}t"):
            yield child.text or ""
        else:
            yield from _own_texts(child)


def hwpx_paragraphs(path: Path, *, own: bool = False) -> list[str]:
    """HWPX 문단 글(빈 문단 뺌). 기본은 표를 품은 문단에 칸 글까지 붙인다(원문 읽기 그대로) ·
    `own=True` 는 문단마다 자기 글만 — 표 칸 글을 두 번 세지 않는다(만든 한글 파일을 다시 읽어 세는 검사 · 2.8.0 B9)."""
    _check_archive(path)
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = sorted((n for n in zf.namelist() if _SECTION_RE.match(n)), key=_section_order)
        if not names:
            raise DocumentExtractionError("HWPX 파일에서 본문을 찾지 못했습니다. 손상된 파일인지 확인해 주세요.")
        for name in names:
            root = ET.fromstring(zf.read(name))
            for node in root.iter():
                if not node.tag.endswith("}p"):
                    continue
                text = "".join(_own_texts(node) if own else (t.text or "" for t in node.iter() if t.tag.endswith("}t")))
                if text.strip():
                    paragraphs.append(text.strip())
    return paragraphs


def _decode_para_text(raw: bytes) -> str:
    """HWPTAG_PARA_TEXT의 UTF-16LE 본문에서 제어문자를 걸러 텍스트만 남긴다."""
    chars: list[str] = []
    i = 0
    while i < len(raw) - 1:
        code = struct.unpack("<H", raw[i : i + 2])[0]
        if code in (0, 10, 13):
            chars.append("\n")
            i += 2
        elif code == _TAB_CONTROL:
            # 탭은 목차 줄에서 제목과 쪽번호를 가르는 실제 구분자다. 통째로 버리면
            # "보안준수사항20"처럼 붙어 뒤의 쪽번호가 요구사항 본문에 섞인다.
            chars.append("\t")
            i += 16
        elif code < 32:
            i += 16 if code in _WIDE_CONTROL_CHARS else 2
        elif 0xD800 <= code <= 0xDFFF:
            # UTF-16 서로게이트. 유닛마다 chr()를 하면 고립 서로게이트가 남아
            # UTF-8 인코딩이 실패한다(JSON 응답이 500으로 죽는다).
            # 쌍이 맞으면 한 코드포인트로 합치고, 아니면 버린다.
            # (한컴이 도장·괄호 글리프에 쓰는 15면 사용자영역 글자다.)
            low = (
                struct.unpack("<H", raw[i + 2 : i + 4])[0]
                if code <= 0xDBFF and i + 3 < len(raw)
                else 0
            )
            if 0xDC00 <= low <= 0xDFFF:
                chars.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                i += 4
            else:
                i += 2
        else:
            chars.append(chr(code))
            i += 2
    return "".join(chars)


def _iter_records(data: bytes) -> Iterator[tuple[int, bytes]]:
    """HWP5 레코드: header 4바이트 (tag 10bit, level 10bit, size 12bit)."""
    pos = 0
    while pos < len(data) - 4:
        header = struct.unpack("<I", data[pos : pos + 4])[0]
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            size = struct.unpack("<I", data[pos : pos + 4])[0]
            pos += 4
        yield tag, data[pos : pos + size]
        pos += size


def extract_hwp(path: Path) -> list[DocumentPage]:
    try:
        ole = olefile.OleFileIO(str(path))
    except OSError as exc:
        raise DocumentExtractionError("HWP 파일을 열 수 없습니다. 손상된 파일인지 확인해 주세요.") from exc

    try:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[_HEADER_FLAG_OFFSET] & 0x01)
        sections = sorted(s for s in ole.listdir() if s and s[0] == "BodyText")
        if not sections:
            raise DocumentExtractionError("HWP 파일에서 본문을 찾지 못했습니다. 손상된 파일인지 확인해 주세요.")

        paragraphs: list[str] = []
        too_big = DocumentExtractionError(
            f"HWP 본문을 풀면 {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB 를 넘습니다. 정상 문서인지 확인해 주세요."
        )
        total = 0  # 39차 마지막 검토 — 상한은 본문 칸 전부를 합친 양이다(칸마다만 막으면 칸 100개 × 상한까지 풀렸다)
        for stream in sections:
            data = ole.openstream(stream).read()
            if compressed:
                budget = MAX_UNCOMPRESSED_BYTES - total
                if budget <= 0:  # zlib 의 max_length 0 은 「제한 없음」이다
                    raise too_big
                try:
                    # 39차 MANUAL-02 — 풀 크기 상한(압축 폭탄이 메모리를 다 쓰지 않게)
                    inflater = zlib.decompressobj(-15)
                    packed = len(data)
                    data = inflater.decompress(data, budget)
                    if inflater.unconsumed_tail:
                        raise too_big
                    # 40차 MANUAL-03 — 칸마다 압축비(61KB 가 21MB 로 펼쳐져 3.8초 · 200KB 면 200MB · 40초). 작은 칸은 보지 않는다.
                    if len(data) > RATIO_FLOOR_BYTES and len(data) / max(1, packed) > MAX_COMPRESSION_RATIO:
                        raise DocumentExtractionError("HWP 본문 압축 비율이 비정상적으로 높습니다. 정상 문서인지 확인해 주세요.")
                except zlib.error as exc:
                    raise DocumentExtractionError("HWP 본문 압축을 풀지 못했습니다. 손상된 파일인지 확인해 주세요.") from exc
            total += len(data)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise too_big
            for tag, payload in _iter_records(data):
                if tag != HWPTAG_PARA_TEXT:
                    continue
                for line in _decode_para_text(payload).split("\n"):
                    if line.strip():
                        paragraphs.append(line.strip())
    finally:
        ole.close()

    return group_paragraphs(paragraphs)


def group_paragraphs(paragraphs: list[str]) -> list[DocumentPage]:
    """문단 목록을 일정 개수씩 묶어 페이지처럼 만든다 (근사 페이지 번호)."""
    if not paragraphs:
        return []
    pages: list[DocumentPage] = []
    for index in range(0, len(paragraphs), PARAGRAPHS_PER_PAGE):
        chunk = paragraphs[index : index + PARAGRAPHS_PER_PAGE]
        pages.append(DocumentPage(page=len(pages) + 1, text="\n".join(chunk)))
    return pages


def extract_docx(path: Path) -> list[DocumentPage]:
    """DOCX 문단 · 표 → 쪽(문단 묶음 · 근사). 회사자료와 직접 넣은 공고문이 같은 함수를 쓴다(예전 `company_service._pages_from_docx`)."""
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:  # pragma: no cover
        raise DocumentExtractionError(f"python-docx를 불러올 수 없습니다: {exc}") from exc
    _check_archive(path)
    try:
        # 경로로 열면 python-docx 가 실패할 때 파일을 쥔 채 남아, 윈도에서 임시 폴더 정리가 「사용 중」으로 500 이 됐다(2.1.6 독립 검토)
        # — 파일은 우리가 열고 닫는다(python-docx 는 열 때 내용을 메모리로 다 읽는다).
        with path.open("rb") as handle:
            docx = DocxDocument(handle)
    except Exception as exc:  # noqa: BLE001 — 손상 파일은 추출 실패로 처리
        # 예외 문장을 그대로 실으면 서버 절대경로가 화면에 나온다 (ISSUE-040):
        #   Package not found at 'C:/…/data/private/organizations/…/uploads/CD-….docx'
        # 담당자에게는 쓸모가 없고, 바깥에 보여 줄 이유도 없다. 자세한 것은 로그에 남긴다.
        logger.warning("DOCX 열기 실패: %s", exc)
        raise DocumentExtractionError(
            "DOCX 파일을 열지 못했습니다. 파일이 손상되었거나 암호가 걸려 있는지 확인해 주세요."
        ) from exc
    paragraphs = [p.text.strip() for p in docx.paragraphs if p.text.strip()]
    for table in docx.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                paragraphs.append(" | ".join(cells))
    return group_paragraphs(paragraphs)


def extract_document(
    path: Path,
    *,
    file_name: str | None = None,
    depth: int = 0,
    zip_priority: tuple[tuple[str, ...], ...] | None = None,
) -> ExtractedDocument:
    """형식을 판별해 텍스트를 추출한다. `depth` 는 압축 중첩 깊이다 (ISSUE-025).

    `zip_priority` 는 압축 첨부 안에서 무엇을 먼저 열지다(없으면 제안요청서가 먼저).
    """
    doc_format = detect_format(path)
    if doc_format == "pdf":
        pages = extract_pdf(path)
    elif doc_format == "hwpx":
        pages = extract_hwpx(path)
    elif doc_format == "hwp":
        pages = extract_hwp(path)
    elif doc_format == "zip":
        return extract_zip(path, file_name=file_name, depth=depth, zip_priority=zip_priority)
    else:
        # 저장 이름(CD-….pdf)이 아니라 담당자가 올린 파일 이름으로 알린다.
        raise DocumentExtractionError(f"지원하지 않는 문서 형식입니다: {file_name or path.name}")
    return ExtractedDocument(file_name=file_name or path.name, doc_format=doc_format, pages=pages)
