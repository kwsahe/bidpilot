"""입찰참가신청서 서식 초안을 문서(DOCX/PDF)로 내보낸다.

가천대 공고 [붙임1] 「입찰참가신청서」처럼, 발주기관이 준 **서식 표**를 그대로 두고
채울 수 있는 칸만 채운 초안을 만든다. 산문 제안서가 아니라 제출 서식이라
담당자가 바로 손을 댈 수 있다.

원칙 (proposal_export와 같다)
- **근거가 있는 칸만 채운다.** 값마다 어디서 왔는지(공고 필드 / 입찰공고문 몇 쪽)를
  표 안에 함께 적는다.
- **회사 공개 등록정보(상호·주소·전화번호)는 등록해 둔 값으로 채운다.**
  `data/company/company_identity.json` 에 있는 것만 쓰고, 파일이 없으면 비워 둔다.
- **개인정보는 절대 채우지 않는다.** 대표자 성명·주민등록번호·인감·대리인은
  시스템이 넣지 않고 담당자가 직접 적는다 (CLAUDE.md 21: 개인정보 포함 데이터 사용 금지).
  법인등록번호도 등록정보에 없으면 비워 둔다.
- 보증액처럼 입찰금액이 정해져야 나오는 칸도 비워 둔다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from starlette.concurrency import run_in_threadpool

from app.core.paths import DATA_ROOT
from app.schemas.procurement import ProcurementNotice
from app.services import attachment_service, document_extractor, procurement_service, rfp_parser
from app.services.proposal_export import (
    KST,
    MEDIA_TYPES,
    ProposalExportError,
    _small,
    docx_to_pdf,
)

# 이 서식은 문서로만 낸다. TXT는 표 모양이 무너져 제출 서식으로 못 쓴다.
ApplicationFormat = str
ALLOWED_FORMATS: tuple[str, ...] = ("docx", "pdf")

_RED = RGBColor(0xB0, 0x20, 0x30)
_BLUE = RGBColor(0x0E, 0x4C, 0x92)

# 담당자가 직접 채워야 하는 칸에 넣는 표시.
TODO = "담당자 입력"

# 회사 공개 등록정보. 상호·주소·전화번호만 담고 개인정보는 담지 않는다.
IDENTITY_FILE = DATA_ROOT / "company" / "company_identity.json"
IDENTITY_SOURCE = "회사 등록정보"


def load_identity(organization_id: str | None = None) -> dict[str, str]:
    """회사 등록정보(상호·주소·전화)를 읽는다. 없으면 빈 dict — 그 칸은 비워 둔다.

    organization_id 가 있으면 그 조직의 프로필(담당자 입력 또는 레거시 파일)에서 읽는다. 합성 기본값은 쓰지 않는다.
    기본 조직은 레거시 company_identity.json(공개 사업자 정보)도 함께 본다.
    """
    allowed = ("name", "address", "phone", "corporate_number")
    result: dict[str, str] = {}
    if organization_id is not None:
        try:
            from app.services import organization_service

            profile = organization_service.load_profile(organization_id)
        except Exception:  # noqa: BLE001 — 조직이 없으면 빈 칸으로 둔다
            profile = None
        if profile is not None and profile.source != "default_synthetic":
            for key in ("name", "address", "phone"):
                value = getattr(profile, key, None)
                if isinstance(value, str) and value.strip():
                    result[key] = value.strip()
        from app.core import org_storage

        if organization_id != org_storage.DEFAULT_ORGANIZATION_ID:
            return result  # 공개 사업자 정보 파일(data/company)은 기본 조직 것이다 — 키트에는 그 폴더가 없다
    try:
        raw = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if not isinstance(raw, dict):
        return result
    # 개인정보로 오해할 값이 파일에 들어와도 서식에 새지 않게 화이트리스트로 막는다.
    for k in allowed:
        if k not in result and isinstance(raw.get(k), str) and raw[k].strip():
            result[k] = str(raw[k]).strip()
    return result

# 입찰공고문에서 뽑는 값들. 못 찾으면 그 칸은 비워 둔다 (추측하지 않는다).
_PATTERNS: dict[str, re.Pattern[str]] = {
    "notice_no": re.compile(r"제\s*(산학\d+호|\S*?제?\d{4,}\S*?호)"),
    "bid_at": re.compile(r"입\s*찰\s*일\s*자\s*(20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일\s*\d{1,2}:\d{2})"),
    "deposit_rate": re.compile(r"보\s*증\s*금\s*율\s*[:：]?\s*입찰금액의\s*(\d+)\s*%"),
    "deposit_method": re.compile(r"보증금납부방법\s*[:：]\s*(\S+)"),
}
_ATTACHMENT_LIST = re.compile(r"붙임서류\s*[:：]\s*(.+?)(?:20\s*\.\s*\.\s*\.|신\s*청\s*인)", re.S)
_ATTACHMENT_ITEM = re.compile(r"(\d)\.\s*([^\n]+?)(?=\s*\d\.\s|\Z)", re.S)


class BidApplicationError(ProposalExportError):
    """서식 초안을 만들 수 없음."""


@dataclass(frozen=True)
class Field:
    """서식의 한 칸. value가 비어 있으면 담당자가 채워야 하는 칸이다."""

    label: str
    value: str
    source: str

    @property
    def filled(self) -> bool:
        return bool(self.value)


@dataclass(frozen=True)
class ApplicationDraft:
    notice: ProcurementNotice
    applicant: list[Field]
    bid: list[Field]
    deposit: list[Field]
    agent: list[Field]
    documents: list[str]
    documents_source: str
    source_document: str | None

    @property
    def all_fields(self) -> list[Field]:
        return [*self.applicant, *self.bid, *self.deposit, *self.agent]

    @property
    def filled_count(self) -> int:
        return sum(1 for f in self.all_fields if f.filled)


def _find(pages: list[tuple[int, str]], key: str) -> tuple[str, str]:
    """(값, 쪽 표시). 쪽마다 패턴을 돌려 **그 값이 실제로 나온 쪽**을 집는다.

    값만으로 쪽을 찾으면 안 된다 — '10'이나 '보증보험증권'은 앞쪽에도 나와서
    엉뚱한 쪽을 근거로 달게 된다(실제로 보증금율이 p.4인데 p.1로 찍혔다).
    """
    pattern = _PATTERNS[key]
    for page, text in pages:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(1).split()), f"p.{page}"
    return "", ""


def _page_of(pages: list[tuple[int, str]], needle: str) -> str:
    """문구가 나온 쪽 번호 (붙임서류 목록처럼 패턴이 없는 경우에 쓴다)."""
    if not needle:
        return ""
    for page, text in pages:
        if needle.replace(" ", "") in text.replace(" ", ""):
            return f"p.{page}"
    return ""


def _parse_notice_document(path) -> tuple[list[tuple[int, str]], str]:
    doc = document_extractor.extract_document(path)
    return [(p.page, p.text) for p in doc.pages], doc.file_name


def build_draft(
    notice: ProcurementNotice,
    pages: list[tuple[int, str]] | None = None,
    *,
    source_document: str | None = None,
    identity: dict[str, str] | None = None,
) -> ApplicationDraft:
    """공고·입찰공고문·회사 등록정보에서 채울 수 있는 칸만 채운다."""
    pages = pages or []
    who = load_identity() if identity is None else identity
    text = "\n".join(t for _, t in pages)

    def sourced(key: str) -> tuple[str, str]:
        value, page = _find(pages, key)
        if not value:
            return "", ""
        return value, f"입찰공고문 {page}".strip() if page else "입찰공고문"

    bid_no, bid_no_src = sourced("notice_no")
    bid_at, bid_at_src = sourced("bid_at")
    rate, rate_src = sourced("deposit_rate")
    method, method_src = sourced("deposit_method")

    # 입찰일자는 공고 마감일로도 채울 수 있다 (입찰공고문이 없을 때).
    if not bid_at and notice.deadline_at is not None:
        bid_at = f"{notice.deadline_at.astimezone(KST):%Y년 %m월 %d일 %H:%M}"
        bid_at_src = "공고 마감일시"

    documents: list[str] = []
    documents_source = ""
    block = _ATTACHMENT_LIST.search(text) if text else None
    if block:
        documents = [
            f"{no}. {' '.join(body.split())}"
            for no, body in _ATTACHMENT_ITEM.findall(block.group(1).strip())
        ]
        page = _page_of(pages, "붙임서류")
        documents_source = f"입찰공고문 {page}".strip() if page else "입찰공고문"

    return ApplicationDraft(
        notice=notice,
        # 공개 등록정보(상호·주소·전화번호)는 채우고, 개인정보는 비워 둔다.
        applicant=[
            Field("상 호", who.get("name", ""), IDENTITY_SOURCE if who.get("name") else TODO),
            Field(
                "법인등록번호",
                who.get("corporate_number", ""),
                IDENTITY_SOURCE if who.get("corporate_number") else TODO,
            ),
            Field("주 소", who.get("address", ""), IDENTITY_SOURCE if who.get("address") else TODO),
            Field("전 화 번 호", who.get("phone", ""), IDENTITY_SOURCE if who.get("phone") else TODO),
            Field("대 표 자", "", f"{TODO} · 개인정보라 자동으로 채우지 않음"),
            Field("주민등록번호", "", f"{TODO} · 개인정보라 자동으로 채우지 않음"),
        ],
        bid=[
            Field("입찰공고(지명)번호", f"제 {bid_no}" if bid_no else "", bid_no_src or TODO),
            Field("입 찰 일 자", bid_at, bid_at_src or TODO),
            Field("입 찰 건 명", notice.title, "공고 제목"),
        ],
        deposit=[
            Field("보 증 금 율", f"입찰금액의 {rate} %" if rate else "", rate_src or TODO),
            Field("보 증 액", "", "입찰금액 확정 후 기재"),
            Field("보증금납부방법", method, method_src or TODO),
        ],
        agent=[
            Field("대리인 성명", "", f"{TODO} · 위임하는 경우에만"),
            Field("대리인 주민등록번호", "", f"{TODO} · 개인정보라 자동으로 채우지 않음"),
            Field("사 용 인 감", "", f"{TODO} · 인감 날인"),
        ],
        documents=documents,
        documents_source=documents_source,
        source_document=source_document,
    )


def _cell_text(cell, text: str, *, bold: bool = False, size: float = 10.5) -> None:
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)


def _field_rows(table, fields: list[Field], group: str) -> None:
    for index, field in enumerate(fields):
        row = table.add_row().cells
        _cell_text(row[0], group if index == 0 else "", bold=True)
        _cell_text(row[1], field.label, bold=True)
        if field.filled:
            _cell_text(row[2], field.value)
        else:
            paragraph = row[2].paragraphs[0]
            run = paragraph.add_run("(빈칸)")
            run.font.size = Pt(10.5)
            run.font.color.rgb = _RED
        _cell_text(row[3], field.source, size=8.5)


def build_document(draft: ApplicationDraft) -> bytes:
    """입찰참가신청서 초안 DOCX. 서식 표 하나로만 구성한다."""
    document = Document()
    document.core_properties.title = "입찰참가신청서 (초안)"
    document.core_properties.comments = "BidPilot AI 생성 초안 — 담당자 확인 필요"

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run("입 찰 참 가 신 청 서")
    run.bold = True
    run.font.size = Pt(18)

    lead = document.add_paragraph()
    lead.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _small(lead, f"{draft.notice.agency}  ·  {draft.notice.title}")

    warning = document.add_paragraph()
    blanks = len(draft.all_fields) - draft.filled_count
    _small(
        warning,
        f"이 문서는 AI가 채운 초안입니다. 근거가 있는 칸 {draft.filled_count}개를 채웠고 "
        f"{blanks}개는 비워 두었습니다. 공고·입찰공고문에서 확인된 값과 등록해 둔 회사 "
        "정보만 채웁니다. 대표자 성명·주민등록번호·인감·대리인은 개인정보라 시스템이 "
        "채우지 않습니다. 제출 전에 담당자가 빈칸을 채우고 전체를 확인해야 합니다.",
        color=_RED,
        bold=True,
    )

    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header = table.rows[0].cells
    for cell, label in zip(header, ("구분", "항목", "기재 내용", "근거 / 비고")):
        _cell_text(cell, label, bold=True, size=9.5)

    _field_rows(table, draft.applicant, "신 청 인")
    _field_rows(table, draft.bid, "입 찰 개 요")
    _field_rows(table, draft.deposit, "입찰보증금")
    _field_rows(table, draft.agent, "대리인 · 사용인감")

    if draft.documents:
        document.add_paragraph()
        docs_heading = document.add_paragraph()
        run = docs_heading.add_run("붙임서류")
        run.bold = True
        run.font.size = Pt(11)
        if draft.documents_source:
            _small(docs_heading, f"   ({draft.documents_source})")
        for item in draft.documents:
            row = document.add_paragraph(item, style="List Bullet")
            row.paragraph_format.left_indent = Pt(18)

    document.add_paragraph()
    consent = document.add_paragraph()
    _small(
        consent,
        f"본인은 위의 번호로 공고한 {draft.notice.agency}의 경쟁입찰에 참가하고자 "
        f"{draft.notice.agency}에서 정한 입찰유의서 및 입찰공고사항을 모두 승낙하고 "
        "별첨 서류를 첨부하여 입찰참가 신청을 합니다.",
    )

    sign = document.add_paragraph()
    sign.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _small(sign, "20      .      .      .          신 청 인 (대표자) :                    (인)")

    receiver = document.add_paragraph()
    receiver.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = receiver.add_run(f"{draft.notice.agency} 귀중")
    run.bold = True
    run.font.size = Pt(12)

    footer = document.add_paragraph()
    origin = f" · 근거 원문: {draft.source_document}" if draft.source_document else ""
    _small(
        footer,
        f"\nBidPilot AI · {datetime.now(KST):%Y-%m-%d %H:%M} 생성{origin}. "
        "채운 값은 공고와 입찰공고문에서 그대로 옮겼고, 없는 값은 만들지 않았습니다.",
    )

    import io

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def _notice_pages(notice_id: str, view) -> tuple[list[tuple[int, str]], str | None]:
    """입찰공고문 첨부를 열어 쪽별 텍스트를 돌려준다. 없으면 빈 목록."""
    attachments = rfp_parser.list_attachments(view)
    for index, attachment in enumerate(attachments):
        if "공고" not in attachment["name"]:
            continue
        try:
            path = await attachment_service.download_attachment(
                attachment["url"],
                file_name=attachment["name"],
                notice_id=notice_id,
                index=index,
            )
            return _parse_notice_document(path)
        except Exception:  # pragma: no cover - 첨부가 없거나 열리지 않으면 그냥 비운다
            return [], None
    return [], None


async def export_application(
    procurement_id: str, *, fmt: str = "docx", organization_id: str | None = None
) -> tuple[bytes, str, str]:
    """입찰참가신청서 초안을 (바이트, 파일명, media type)으로 돌려준다."""
    if fmt not in ALLOWED_FORMATS:
        raise BidApplicationError(
            f"이 서식은 {' · '.join(ALLOWED_FORMATS)} 로만 내려받을 수 있습니다 (요청: {fmt})"
        )
    view = await procurement_service.get_notice(procurement_id)
    if view is None:
        raise BidApplicationError("공고를 찾지 못했습니다")

    pages, source_document = await _notice_pages(procurement_id, view)
    draft = build_draft(view.notice, pages, source_document=source_document, identity=load_identity(organization_id))
    payload = build_document(draft)
    if fmt == "pdf":
        # Word 변환은 동기(최대 120초) — 스레드에서 기다린다(27차 R26-03).
        payload = await run_in_threadpool(docx_to_pdf, payload)
    file_name = f"{procurement_id}_입찰참가신청서_초안_{datetime.now(KST):%Y%m%d}.{fmt}"
    return payload, file_name, MEDIA_TYPES[fmt]
