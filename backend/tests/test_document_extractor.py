"""document_extractor: 형식 판별 + 텍스트/위치 추출 테스트.

- `detect_format`은 확장자가 아니라 **파일 시그니처(매직 바이트)** 로 판별해야 한다.
- PDF는 실제 합성 RFP(6페이지)로 검증한다. 페이지 번호와 원문을 잃지 않아야
  Requirement의 page/source_text 근거를 만들 수 있다 (CLAUDE.md 25-6).
- HWP/HWPX는 페이지 정보가 없어 문단 묶음으로 근사한다.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from app.services import document_extractor as de
from tests.conftest import SAMPLE_RFP_DOCX, SAMPLE_RFP_PDF

# --------------------------------------------------------------------------
# 형식 판별 (매직 바이트)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"%PDF-1.7\n", "pdf"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "hwp"),  # OLE2 (HWP 5.x)
        # HWPX 본문이 없는 zip은 일반 압축 첨부로 본다 (안에서 제안요청서를 골라 연다).
        (b"PK\x03\x04\x14\x00\x00\x00", "zip"),
        (b"\x00\x01\x02\x03rubbish", "unknown"),
        (b"<?xml version=", "unknown"),
    ],
)
def test_detect_format_uses_magic_bytes(
    tmp_path: Path, head: bytes, expected: str
) -> None:
    # 확장자는 일부러 틀리게 준다 (실제 첨부에서 흔한 상황).
    path = tmp_path / "attachment.txt"
    path.write_bytes(head + b"\x00" * 64)
    assert de.detect_format(path) == expected


def test_detect_format_on_real_files() -> None:
    assert de.detect_format(SAMPLE_RFP_PDF) == "pdf"
    # docx도 zip 컨테이너지만 HWPX 본문(Contents/sectionN.xml)이 없으므로 zip으로 본다.
    assert de.detect_format(SAMPLE_RFP_DOCX) == "zip"


def test_unknown_format_raises_extraction_error(tmp_path: Path) -> None:
    path = tmp_path / "weird.bin"
    path.write_bytes(b"\x00\x01\x02\x03" * 8)
    with pytest.raises(de.DocumentExtractionError):
        de.extract_document(path)
    # 사유에는 저장 이름이 아니라 올린 파일 이름이 나온다
    with pytest.raises(de.DocumentExtractionError, match="원래이름.pdf"):
        de.extract_document(path, file_name="원래이름.pdf")


# --------------------------------------------------------------------------
# PDF 추출 (실제 합성 RFP)
# --------------------------------------------------------------------------


def test_extract_pdf_keeps_six_pages_with_no_empty_page() -> None:
    doc = de.extract_document(SAMPLE_RFP_PDF)

    assert doc.doc_format == "pdf"
    assert doc.file_name == SAMPLE_RFP_PDF.name
    assert doc.page_count == 6
    assert [p.page for p in doc.pages] == [1, 2, 3, 4, 5, 6]
    assert doc.empty_pages == []
    for page in doc.pages:
        assert page.text.strip()
        assert page.char_count > 0


def test_extract_pdf_text_joins_pages_in_order() -> None:
    doc = de.extract_document(SAMPLE_RFP_PDF)
    assert doc.text == "\n".join(p.text for p in doc.pages)
    assert doc.pages[0].text in doc.text


def _one_page_pdf(lines: list[tuple[float, float, str]], size: tuple[int, int] = (595, 842)) -> bytes:
    """한 쪽 PDF — (x, y, ASCII 글자)를 Helvetica 10pt 로 찍는다. 두 단 판별 픽스처용(실제 공고문은 담지 않는다)."""
    ops = "".join(f"BT /F1 10 Tf {x:.1f} {y:.1f} Td ({t}) Tj ET\n" for x, y, t in lines).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
        b"<< /Length " + str(len(ops)).encode() + b" >>\nstream\n" + ops + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


QUALIFICATION_LINES = [f"Qualification {i + 1}: bidder holds a similar AI project record" for i in range(24)]
INVALID_LINES = [f"Invalid bid {i + 1}: a bid without the bidder seal is void" for i in range(24)]


def test_두_단_쪽은_왼쪽_단을_먼저_끝까지_읽는다(tmp_path: Path) -> None:
    """가로 두 단 — 왼쪽 「입찰참가자격」, 오른쪽 「입찰의 무효」 (20차 §4-A · ISSUE-137, 한양사이버대 공고문 1쪽의 모양).

    원본 공고문은 담당자 이름·전화번호가 있어 픽스처로 두지 않고 같은 배치를 합성한다(.gitignore `data/public/real_rfp/`).
    """
    import pdfplumber

    lines = [(40, 540 - i * 18, text) for i, text in enumerate(QUALIFICATION_LINES)]
    lines += [(440, 540 - i * 18, text) for i, text in enumerate(INVALID_LINES)]
    path = tmp_path / "two_column.pdf"
    path.write_bytes(_one_page_pdf(lines, size=(841, 595)))
    with pdfplumber.open(str(path)) as pdf:
        # 예전 읽기는 줄마다 두 단을 이어 붙였다 — 실적 조항 뒤에 「입찰의 무효」가 붙던 모양.
        assert (pdf.pages[0].extract_text() or "").splitlines()[0] == f"{QUALIFICATION_LINES[0]} {INVALID_LINES[0]}"
    # 오른쪽 단은 버리지 않고 왼쪽 단 **뒤에** 온다.
    assert de.extract_pdf(path)[0].text.splitlines() == QUALIFICATION_LINES + INVALID_LINES


def test_쪽_밖에_찍힌_글자는_단을_만들지_않는다(tmp_path: Path) -> None:
    """MediaBox 너머 글자로 띠를 잡으면 자르는 선이 쪽 밖에 떨어져 crop() 이 ValueError 를 냈다(20차 검수)."""
    import pdfplumber

    body = "The bidder shall submit every listed document before the deadline written in this notice, without fail"
    lines = [(40, 800 - i * 20, body) for i in range(35)] + [(660, 800 - i * 20, "off page column entry") for i in range(35)]
    path = tmp_path / "off_page.pdf"
    path.write_bytes(_one_page_pdf(lines))
    with pdfplumber.open(str(path)) as pdf:
        raw = pdf.pages[0].extract_text() or ""
    assert de.extract_pdf(path)[0].text == raw


def test_한_단_쪽은_예전과_글자까지_같다() -> None:
    import pdfplumber

    with pdfplumber.open(str(SAMPLE_RFP_PDF)) as pdf:
        raw = [page.extract_text() or "" for page in pdf.pages]
    assert [p.text for p in de.extract_pdf(SAMPLE_RFP_PDF)] == raw


@pytest.mark.parametrize(
    "lines",
    [
        # 내어쓰기 번호 목록 — 번호(x=50)와 본문(x=90) 사이 틈이 3%를 넘고 둘 다 쪽 높이 60% 이상을 덮는다.
        [(50, 800 - i * 22, f"{i + 1}.") for i in range(30)]
        + [(90, 800 - i * 22, f"The bidder shall submit document {i + 1} before the deadline.") for i in range(30)],
        # 목차 — 쪽 번호만 오른쪽 끝에 붙는다.
        [(60, 800 - i * 22, f"Chapter {i + 1} Scope of the training programme") for i in range(30)]
        + [(520, 800 - i * 22, f"{i + 3}") for i in range(30)],
        # 칸 선 없는 표 — 왼쪽 머리 칸(분류 이름)은 넓지만 낱말이 적다.
        [(60, 800 - i * 66, f"Label {i + 1} operating requirement group") for i in range(10)]
        + [(330, 800 - i * 22, f"The system shall keep the temperature in range {i + 1}") for i in range(30)],
    ],
    ids=["내어쓰기-목록", "목차", "칸-선-없는-표"],
)
def test_좁은_쪽은_단이_아니다(tmp_path: Path, lines: list[tuple[float, float, str]]) -> None:
    import pdfplumber

    path = tmp_path / "one_column.pdf"
    path.write_bytes(_one_page_pdf(lines))
    with pdfplumber.open(str(path)) as pdf:
        raw = pdf.pages[0].extract_text() or ""
    assert de.extract_pdf(path)[0].text == raw
    assert raw.splitlines()[0].startswith(("1. The bidder", "Chapter 1", "Label 1"))


def test_file_name_can_be_overridden() -> None:
    doc = de.extract_document(SAMPLE_RFP_PDF, file_name="★제안요청서.pdf")
    assert doc.file_name == "★제안요청서.pdf"
    assert doc.page_count == 6


# --------------------------------------------------------------------------
# 문단 -> 근사 페이지 묶음
# --------------------------------------------------------------------------


def test_group_paragraphs_numbers_pages_from_one() -> None:
    per_page = de.PARAGRAPHS_PER_PAGE
    paragraphs = [f"문단 {i}" for i in range(per_page * 2 + 5)]

    pages = de.group_paragraphs(paragraphs)

    assert [p.page for p in pages] == [1, 2, 3]
    assert pages[0].text.splitlines()[0] == "문단 0"
    assert pages[1].text.splitlines()[0] == f"문단 {per_page}"
    assert len(pages[2].text.splitlines()) == 5


def test_group_paragraphs_exact_multiple_has_no_trailing_empty_page() -> None:
    paragraphs = [f"문단 {i}" for i in range(de.PARAGRAPHS_PER_PAGE * 2)]
    pages = de.group_paragraphs(paragraphs)
    assert len(pages) == 2
    assert all(p.text.strip() for p in pages)


def test_group_paragraphs_on_empty_input() -> None:
    assert de.group_paragraphs([]) == []


def test_extracted_document_reports_empty_pages() -> None:
    doc = de.ExtractedDocument(
        file_name="x.hwp",
        doc_format="hwp",
        pages=[
            de.DocumentPage(page=1, text="내용"),
            de.DocumentPage(page=2, text="   "),
            de.DocumentPage(page=3, text=""),
        ],
    )
    assert doc.page_count == 3
    assert doc.empty_pages == [2, 3]


# --------------------------------------------------------------------------
# HWPX 실패 경로 (section XML 없음)
# --------------------------------------------------------------------------


def test_hwpx_without_section_xml_raises() -> None:
    # docx는 zip이지만 Contents/section*.xml이 없다.
    with pytest.raises(de.DocumentExtractionError):
        de.extract_document(SAMPLE_RFP_DOCX)


def test_hwp_open_failure_raises_extraction_error(tmp_path: Path) -> None:
    fake = tmp_path / "broken.hwp"
    fake.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
    with pytest.raises(de.DocumentExtractionError):
        de.extract_document(fake)


# --------------------------------------------------------------------------
# 압축(zip) 첨부 — 공고문·제안요청서·서식을 한 덩어리로 올린 경우
# --------------------------------------------------------------------------


def make_zip(tmp_path: Path, members: dict[str, bytes]) -> Path:
    target = tmp_path / "attachment.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return target


def test_압축_안에서_제안요청서를_고른다() -> None:
    names = ["묶음/1. 입찰공고문.hwp", "묶음/2. 제안요청서.hwp", "묶음/서식모음.docx"]
    assert de.pick_zip_member(names) == "묶음/2. 제안요청서.hwp"


def test_제안요청서가_없으면_공고문을_고른다() -> None:
    assert de.pick_zip_member(["a/입찰공고문.pdf", "a/기타.txt"]) == "a/입찰공고문.pdf"


def test_열_수_있는_문서가_없으면_고르지_않는다() -> None:
    """추측해서 아무 파일이나 열지 않는다."""
    assert de.pick_zip_member(["a/서식.docx", "a/사진.png", "b/"]) is None


def test_경로_이동이_섞인_항목은_열지_않는다() -> None:
    assert de.pick_zip_member(["../밖으로/제안요청서.hwp"]) is None


def test_압축_첨부의_텍스트를_추출하고_연_파일을_밝힌다(tmp_path: Path) -> None:
    inner = SAMPLE_RFP_PDF.read_bytes()
    path = make_zip(tmp_path, {"공고/2. 제안요청서.pdf": inner, "공고/서식.docx": b"x"})

    doc = de.extract_document(path, file_name="입찰공고묶음.zip")

    assert doc.doc_format == "pdf"          # 안에 들어 있던 실제 형식
    assert "입찰공고묶음.zip" in doc.file_name  # 어떤 압축에서
    assert "제안요청서.pdf" in doc.file_name   # 어떤 파일을 열었는지
    assert doc.page_count == 6


def test_모두_꺼내기는_깨진_PDF_하나가_압축_전체를_버리지_않는다(tmp_path: Path) -> None:
    """검토 11-06 #12 — 잘린 PDF(PdfminerException)가 함수 밖으로 새어 같은 압축의 멀쩡한 제안요청서까지 빠졌다."""
    good = SAMPLE_RFP_PDF.read_bytes()
    path = make_zip(tmp_path, {"공고/1. 입찰공고문.pdf": good[: len(good) // 2], "공고/2. 제안요청서.pdf": good})
    docs = de.extract_zip_all(path, file_name="공고파일.zip")
    assert [d.file_name for d in docs] == ["공고파일.zip > 2. 제안요청서.pdf"] and docs[0].page_count == 6


def test_모두_꺼내기는_본문_XML_이_깨진_HWPX_만_뺀다(tmp_path: Path) -> None:
    """검토 11-06 #12 — 본문 XML 이 깨진 .hwpx(ParseError)도 그 문서만 건너뛴다."""
    import io

    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as hwpx:
        hwpx.writestr("mimetype", "application/hwp+zip")
        hwpx.writestr("Contents/section0.xml", "<hs:sec xmlns:hs='x'><hp:p>")
    path = make_zip(tmp_path, {"1. 과업지시서.hwpx": broken.getvalue(), "2. 제안요청서.pdf": SAMPLE_RFP_PDF.read_bytes()})
    assert [d.file_name for d in de.extract_zip_all(path)] == ["attachment.zip > 2. 제안요청서.pdf"]


def test_열_파일이_없는_압축은_실패시킨다(tmp_path: Path) -> None:
    path = make_zip(tmp_path, {"a/사진.png": b"x", "a/메모.txt": b"y"})
    with pytest.raises(de.DocumentExtractionError):
        de.extract_document(path)


# --------------------------------------------------------------------------
# HWPTAG_PARA_TEXT 제어문자 디코딩
#
# HWP5의 inline/extended 제어문자는 16바이트(여는 코드 + 파라미터 6워드 +
# 닫는 코드)를 차지한다. inline(4~9, 19, 20)이 빠져 있어서 파라미터 6워드가
# 리터럴 문자로 새어나왔다. 실제 공고 첨부에서 확인한 증상:
#   "Ⅰ. 과업 개요輖\nȃ   01"  (정상: "Ⅰ. 과업 개요\t01")
# --------------------------------------------------------------------------


def para_bytes(units: list[int]) -> bytes:
    """UTF-16LE 유닛 목록을 HWPTAG_PARA_TEXT 페이로드로 만든다."""
    return b"".join(struct.pack("<H", u) for u in units)


def test_스펙의_세_가지_제어문자_폭을_구분한다() -> None:
    """char 3개, 예약 24~31은 1워드. inline과 extended만 8워드다."""
    assert de._INLINE_CONTROL_CHARS == {4, 5, 6, 7, 8, 9, 19, 20}
    assert de._EXTENDED_CONTROL_CHARS == {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
    # 0, 10, 13(문단/줄 나눔)과 24~31(예약)은 폭이 넓지 않다.
    assert not (de._WIDE_CONTROL_CHARS & {0, 10, 13})
    assert not (de._WIDE_CONTROL_CHARS & set(range(24, 32)))
    # 32 미만에서 나머지는 모두 8워드다.
    assert de._WIDE_CONTROL_CHARS == set(range(1, 24)) - {0, 10, 13}


def test_탭_뒤의_필드_파라미터가_본문에_새지_않는다() -> None:
    """실제 공고(제안요청서)의 목차 줄 바이트 그대로."""
    payload = para_bytes(
        [ord("개"), ord("요"), 9, 0x8F16, 0x0000, 0x0203, 0x20, 0x20, 0x20, 9,
         ord("0"), ord("1"), 13]
    )
    text = de._decode_para_text(payload)
    assert "輖" not in text, "필드 인스턴스 ID가 새어나왔다"
    assert "ȃ" not in text, "필드 파라미터가 새어나왔다"
    assert text.strip() == "개요\t01"


def test_탭은_구분자로_남긴다() -> None:
    """통째로 버리면 '보안준수사항20'처럼 붙어 쪽번호가 본문에 섞인다."""
    payload = para_bytes(
        [ord("항"), 9, 0x8322, 0x0000, 0x0203, 0x0000, 0x0000, 0x0000, 9,
         ord("2"), ord("0"), 13]
    )
    text = de._decode_para_text(payload)
    assert text.strip() == "항\t20"
    assert "항20" not in text


@pytest.mark.parametrize("code", sorted({4, 5, 6, 7, 8, 9, 19, 20}))
def test_모든_inline_제어문자가_16바이트를_차지한다(code: int) -> None:
    payload = para_bytes([ord("가"), code, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
                          0xFFFF, code, ord("나")])
    text = de._decode_para_text(payload)
    assert "￿" not in text, f"제어문자 {code}의 파라미터가 새어나왔다"
    assert text.replace("\t", "") == "가나"


def test_예약_제어문자_24_31은_1워드다() -> None:
    """24~31을 16바이트로 건너뛰면 뒤 본문이 잘린다."""
    payload = para_bytes([ord("가"), 30, ord("나"), 31, ord("다")])
    assert de._decode_para_text(payload) == "가나다"


def test_서로게이트_쌍은_한_글자로_합친다() -> None:
    """유닛마다 chr()를 하면 고립 서로게이트가 남아 UTF-8 인코딩이 깨진다."""
    payload = para_bytes([ord("자"), 0xDB80, 0xDD2B, ord("인")])
    text = de._decode_para_text(payload)
    assert text == "자\U000F012B인"
    text.encode("utf-8")  # 예외가 나면 실패


def test_짝_없는_서로게이트는_버린다() -> None:
    for units in ([ord("가"), 0xDB80, ord("나")],       # 뒤짝 없음
                  [ord("가"), 0xDC00, ord("나")],       # 앞짝 없음
                  [ord("가"), 0xDB80]):                 # 레코드 끝에서 잘림
        text = de._decode_para_text(para_bytes(units))
        text.encode("utf-8")
        assert not any(0xD800 <= ord(c) <= 0xDFFF for c in text)


def test_실제_공고_첨부에_고립_서로게이트가_없다() -> None:
    """3개 파일에서 UTF-8 인코딩이 실패해 JSON 응답이 죽을 수 있었다."""
    docs = sorted(Path("../data/public/real_rfp").glob("*/*.hwp"))
    if not docs:
        pytest.skip("실제 공고 첨부가 없는 환경")
    for doc in docs:
        text = "\n".join(p.text for p in de.extract_document(doc).pages)
        text.encode("utf-8")
        assert not any(0xD800 <= ord(c) <= 0xDFFF for c in text), doc.name
