"""제안서 초안을 문서(DOCX)로 내보낸다.

원칙
- **근거를 문서에 함께 찍는다.** 문장마다 RFP 페이지·원문과 회사 근거자료를 붙인다.
  화면에서만 보이던 근거가 파일로 나가면서 사라지면 이 시스템의 주장이 무너진다.
- **완성본이 아니라 초안이다.** 문서 첫머리에 사람이 검토·확정해야 한다고 못박는다
  (CLAUDE.md 4-I: AI 자동 제출 금지).
- 근거가 없는 문장은 「확인 필요」로 표시하고, 대응 문장이 없는 요구사항은 문서 끝에
  그대로 나열한다. 빠진 것을 숨기지 않는다.

CLAUDE.md 3.2/5: 전체 제안서 자동생성은 MVP 밖이다. 여기서는 이미 생성된
핵심 섹션 1개를 문서로 옮길 뿐, 없는 섹션을 만들어내지 않는다.
"""

from __future__ import annotations

import io
import logging
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from typing import Literal

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from starlette.concurrency import run_in_threadpool

from app.schemas.proposal import ProposalSection

if TYPE_CHECKING:  # 순환 import 를 피한다 — 주석에서만 쓴다
    from app.schemas.organization import AnalysisContext
from app.schemas.requirement import Requirement, RfpParseResult
from app.services import (
    evidence_service,
    home_agencies,
    plan_export_service,
    procurement_service,
    proposal_service,
    rfp_parser,
    wording,
)

KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)

GROUNDING_LABEL = {
    "COMPANY_EVIDENCE_GROUNDED": "회사 근거",
    "RFP_GROUNDED": "공고문 근거",
    "AI_SUGGESTION": "AI 덧붙임",
}



def grounding_label(sentence) -> str:
    """문장 표지 — AI 가 다듬은 문장(44차 M5)은 「AI 덧붙임(다듬음 · 원 근거: 공고문 근거)」. 나머지는 근거 유형 그대로."""
    refined = getattr(sentence, "refined_from", None)
    if refined:
        return f"{GROUNDING_LABEL['AI_SUGGESTION']}(다듬음 · 원 근거: {GROUNDING_LABEL.get(refined, refined)})"
    return GROUNDING_LABEL.get(sentence.grounding_type, sentence.grounding_type)


# 근거 인용을 지나치게 길게 싣지 않는다 (문서 가독성).
QUOTE_LIMIT = 160

_GREY = RGBColor(0x60, 0x60, 0x60)
_RED = RGBColor(0xB0, 0x20, 0x30)


class ProposalExportError(RuntimeError):
    """내보낼 제안서나 요구사항이 없음."""


class PdfConverterUnavailableError(ProposalExportError):
    """PDF 변환기(설치된 Microsoft Word)를 쓸 수 없음."""


# 내려받기 형식. JSON은 개발자용이라 담당자에게는 문서 형식으로 낸다.
ExportFormat = Literal["docx", "pdf", "txt"]

MEDIA_TYPES: dict[str, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
}

# Word COM이 문서 하나를 PDF로 저장하는 데 걸리는 상한. 첫 기동이 느리다.
PDF_TIMEOUT_SECONDS = 120


def stale_reason(sections, parsed: RfpParseResult, procurement_id: str) -> str | None:
    """옛 초안이면 그 사유(44차 S2 · E2E-10) — 요구사항 번호가 지금 정리표와 어긋남 · 옛 가상 예시 근거가 섞임(실공고).
    이런 초안은 경고만 붙여 내보내지 않고 「다시 만들기」를 요구한다. 새 초안이면 None."""
    current = {r.requirement_id: r for r in parsed.requirements}
    drift = 0
    for section in sections:
        for sentence in section.sentences:
            rid = sentence.requirement_id
            if not rid:
                continue
            requirement = current.get(rid)
            stable = getattr(sentence, "stable_requirement_id", None)
            if requirement is None or (stable and requirement.stable_id and stable != requirement.stable_id):
                drift += 1
    if drift:
        return f"요구사항 번호 {drift}건이 지금 요구사항 정리표와 어긋납니다(정리표를 다시 뽑은 뒤의 옛 초안)"
    real = not procurement_id.startswith("synthetic-")
    for section in sections:
        legacy = getattr(section, "legacy_result", False)
        synthetic = (getattr(section, "evidence_summary", None) or {}).get("synthetic_evidence_used")
        if legacy or (real and synthetic):
            return "옛 가상 예시 근거가 섞인 초안입니다"
    return None


def _refuse_stale(sections, parsed: RfpParseResult, procurement_id: str) -> None:
    reason = stale_reason(sections, parsed, procurement_id)
    if reason:
        raise ProposalExportError(f"옛 초안이라 내려받지 않습니다 — {reason}. 「다시 만들기」로 새 초안을 만든 뒤 내려받으세요.")


def _split_sentences(sentences, grounded_only: bool) -> tuple[list, list]:
    """(본문에 실을 문장, 뺀 문장).

    grounded_only면 회사 근거가 없어 「확인 필요」인 문장과 AI 제안 문장을 본문에서
    뺀다. 뺀 문장은 버리지 않고 문서 끝 「담당자 확인 목록」에 남긴다 — 빠진 것을
    숨기면 이 시스템의 주장이 무너진다.
    """
    if not grounded_only:
        return list(sentences), []
    kept, dropped = [], []
    for sentence in sentences:
        # AI 가 다듬은 근거 문장(44차 M5 · `refined_from`)은 본문에 남긴다 — 표지만 「AI 덧붙임(다듬음 …)」
        grounded = not sentence.needs_review and (sentence.grounding_type != "AI_SUGGESTION" or bool(getattr(sentence, "refined_from", None)))
        (kept if grounded else dropped).append(sentence)
    return kept, dropped


def _display_title(document, notice_line: str) -> str:
    """문서 제목 — 저장된 제목이 「제안서 초안 (g2b-…)」(공고 번호)이면 공고명으로(43차 E2E-12)."""
    default = f"{proposal_service.DEFAULT_DOCUMENT_TITLE} ({document.procurement_id})"
    name = notice_line.split("  (")[0].strip()
    if document.title == default and name and name != document.procurement_id:
        return f"{proposal_service.DEFAULT_DOCUMENT_TITLE} — {name}"
    return document.title


def _numbered(index: int, title: str) -> str:
    """절 제목 번호를 실은 절만 차례로(1 · 2 · 3 …) — 빠진 절 때문에 2 · 3 · 4 · 5 · 7 … 로 비었다(43차 E2E-12)."""
    bare = re.sub(r"^\d+\.\s*", "", title)
    return f"{index}. {bare}"


#: 만든 방식 — 파일에는 한국어로(45차 H4 · 「방식 RULE」 영어가 찍혔다).
_METHOD_LABEL = {"RULE": "규칙", "LLM": "AI"}


def method_label(method: str | None) -> str:
    return _METHOD_LABEL.get(str(method or "RULE"), str(method))


def _warning_text(grounded_only: bool, dropped: int, *, full: bool = False, method: str | None = "RULE") -> str:
    # 45차 H4 — AI 없이 규칙으로 만든 초안에도 「AI가 만든 초안」이 찍혔다. 만든 방식대로 적는다.
    made = "AI가 만든 초안" if method == "LLM" else "규칙으로 만든 초안"
    base = f"이 문서는 {made}입니다. 제출 전에 담당자가 내용을 확인하고 확정해야 합니다. "
    if full:
        base += (
            "목차는 제안요청서 요구사항의 종류를 따라 구성했습니다 — 요구사항이 없거나 실을 문장이 없는 절은 빼고, "
            "남은 절에 차례로 번호를 매겼습니다. "
        )
    if grounded_only:
        return base + (
            f"근거가 연결된 문장만 실었습니다. 회사 근거자료가 없는 「확인 필요」 문장 {dropped}건은 "
            "본문에서 빼고 문서 끝 「담당자 확인 목록」에 남겼습니다."
        )
    return base + "「확인 필요」로 표시된 문장은 회사 근거자료가 연결되지 않은 문장입니다."


def _made_line(section: Any) -> str:
    """「초안 만든 날 · 내려받은 때」(43차 E2E-10 — 「생성」이 내려받은 시각이었다) · 옛 가상 예시 근거가 섞였으면 그렇다고."""
    made = getattr(section, "generated_at", None)
    made_text = f"{made.astimezone(KST):%Y-%m-%d %H:%M}" if made else "알 수 없음"
    legacy = " · ⚠ 옛 가상 예시 근거가 섞인 초안 — 다시 만들기 권장" if getattr(section, "legacy_result", False) or (
        (getattr(section, "evidence_summary", None) or {}).get("synthetic_evidence_used")
    ) else ""
    return f"초안 만든 날  {made_text} · 내려받음 {datetime.now(KST):%Y-%m-%d %H:%M}{legacy}"


def _evidence_lines(sentence, requirements: dict[str, Requirement], evidence: dict) -> list[str]:
    """문장 하나에 붙는 근거 줄들 (DOCX·TXT가 같은 내용을 싣도록 한 곳에서 만든다)."""
    label = grounding_label(sentence)
    lines: list[str] = []
    requirement = requirements.get(sentence.requirement_id or "")
    if requirement is not None:
        lines.append(f"[{label}] {_ref(requirement)} “{_short(requirement.source_text)}”")
    else:
        lines.append(f"[{label}]")
    match = evidence.get((sentence.requirement_id or "", sentence.evidence_id or ""))
    if match is not None:
        origin = "가상 예시" if getattr(match, "synthetic", True) else "실제(비식별)"
        lines.append(
            f"회사 근거 · 「{match.document_name}」 ({origin}, 유사도 "
            f"{match.similarity_score:.3f})  “{_short(match.source_text)}”"
        )
    elif sentence.grounding_type == "COMPANY_EVIDENCE_GROUNDED":
        # 43차 E2E-10 — 근거 이름 · 원문 없이 「[회사 근거]」 표지만 남지 않게 — 무엇을 못 찾았는지 적는다
        lines.append(f"회사 근거 — 초안을 만들 때 붙은 근거(「{sentence.evidence_id or '-'}」)를 지금 다시 찾지 못했습니다. 회사자료에서 원문을 확인하세요.")
    # 11-03 대표 「「확인 필요 — 채택된 회사 근거자료가 없습니다」 모두 쓰지 마」 — 문장마다 붙던 확인 필요 줄은 없앴다(화면 배지로 본다)
    return lines


def _docx_review_list(document, dropped: list, requirements: dict[str, Requirement]) -> None:
    """근거만 실은 문서에서 뺀 문장을 요구사항 원문과 함께 나열한다."""
    if not dropped:
        return
    document.add_heading("담당자 확인 목록", level=1)
    lead = document.add_paragraph()
    _small(
        lead,
        f"회사 근거자료가 없어 본문에서 뺀 요구사항 {len(dropped)}건입니다. "
        "근거를 찾아 넣을지, 그대로 제안할지 담당자가 판단해야 합니다.",
    )
    for sentence in dropped:
        item = document.add_paragraph(style="List Bullet")
        requirement = requirements.get(sentence.requirement_id or "")
        if requirement is None:
            _small(item, sentence.requirement_id or sentence.id)
            continue
        _small(item, f"{_ref(requirement)}  ")
        _small(item, f"“{_short(requirement.source_text)}”")


def _ref(requirement: Requirement) -> str:
    """「제안요청서 17쪽 · 14번 요구사항」 — 내려받은 파일도 화면과 같은 말(32차 R31-24 · 어려운 글 #17)."""
    return wording.rfp_ref(requirement.page, requirement.requirement_id)


def _short(text: str, limit: int = QUOTE_LIMIT) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


# 규칙 생성 문장이 달고 나오는 장식. 문서에서는 근거를 문장 아래에 따로 찍으므로
# 본문에서 같은 내용을 두 번 읽게 하지 않는다. 문장의 주장 자체는 바꾸지 않는다.
_LEADING_TITLE_RE = re.compile(r"^\[[^\]]{1,120}\]\s*")
_TRAILING_NOTE_RE = proposal_service.TRAILING_NOTE_RE


def _display_text(text: str) -> str:
    """내보낼 본문 문장. 앞의 [요구사항 제목]과 뒤의 (근거: …)/(RFP p.N 요구사항 준수)만 걷어낸다."""
    cleaned = _LEADING_TITLE_RE.sub("", text.strip())
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _TRAILING_NOTE_RE.sub("", cleaned)
    return cleaned or text.strip()


def _small(paragraph, text: str, *, color: RGBColor = _GREY, bold: bool = False) -> None:
    run = paragraph.add_run(text)
    run.font.size = Pt(8.5)
    run.font.color.rgb = color
    run.bold = bold


async def _notice_line(procurement_id: str) -> str:
    """공고 제목·기관을 머리말에 넣는다. 조회 실패해도 문서는 나온다."""
    try:
        view = await procurement_service.get_notice(procurement_id)
    except Exception:  # pragma: no cover - 네트워크·캐시 상태에 좌우된다
        view = None
    if view is None:
        return procurement_id
    # 11-01 — 조달청 대행 공고가 워드에서만 「조달청 서울지방조달청」이었다(화면은 「대법원 사법연수원(조달청 대행)」 · 2.1.3)
    agency = home_agencies.display_agency(view.notice.agency, (view.notice.raw_data or {}).get("demand_institution"))
    return f"{view.notice.title}  ({agency})"


def _evidence_index(requirements: list[Requirement], context: "AnalysisContext | None") -> dict[tuple[str, str], object]:
    """채택된 증빙을 (요구사항, evidence_id)로 찾을 수 있게 모은다.

    evidence_id는 **문서 단위**라 chunk를 특정하지 못한다. 한 문서의 서로 다른 문단이
    각각 다른 요구사항에 채택되면 같은 evidence_id를 갖는다(실측: EV-01이 REQ-002와
    REQ-009에 각각 다른 문단으로 붙음). evidence_id만으로 찾으면 엉뚱한 원문을 인용한다.

    `context` 에 기본값을 두지 않는다 — 기본값이 있으면 넘기는 것을 빠뜨려도 조용히 돌아가고,
    그것이 이 함수가 모든 내보내기를 500 으로 만든 경위였다. 호출부가 «반드시» 적게 한다.

    `context` 는 **요청의 것을 그대로** 넘겨야 한다. 다회사 구조에서 근거는 회사·범위별로
    나뉘어 있어, 빠뜨리면 다른 회사의 근거가 문서에 실리거나(격리 붕괴) 호출 자체가
    깨진다. 실제로 빠져 있었고 모든 내보내기가 500 이었다 — match_requirements 가
    `context` 를 키워드 필수 인자로 받기 때문이다.
    """
    result = evidence_service.match_requirements(requirements, context=context)
    if not result.available:
        return {}
    return {
        (match.requirement_id, match.evidence_id): match
        for match in result.matches
        if match.selected
    }


def build_document(
    section: ProposalSection,
    parsed: RfpParseResult,
    *,
    notice_line: str,
    evidence: dict[tuple[str, str], object] | None = None,
    grounded_only: bool = False,
) -> bytes:
    """제안서 초안 DOCX 바이트를 만든다."""
    if not section.sentences:
        raise ProposalExportError("내보낼 제안서 문장이 없습니다")
    kept, dropped = _split_sentences(section.sentences, grounded_only)
    if not kept:
        raise ProposalExportError("근거가 연결된 문장이 없어 근거만 실은 문서를 만들 수 없습니다")

    evidence = evidence or {}
    requirements = {r.requirement_id: r for r in parsed.requirements}

    document = Document()
    plan_export_service.apply_document_style(document)  # 44차 S9 — 사업계획서와 같은 문서 모양(맑은 고딕 · 쪽 · 제목 색)
    document.core_properties.title = section.title
    document.core_properties.comments = "BidPilot AI 생성 초안 — 담당자 검토 필요"

    document.add_heading(section.title, level=0)

    head = document.add_paragraph()
    _small(head, f"공고  {notice_line}\n")
    _small(head, f"원문  {parsed.document} ({parsed.doc_format}, {parsed.page_count}쪽)")
    if parsed.page_is_approximate:
        _small(head, "  · 한글 파일이라 쪽 번호는 대략입니다")
    _small(head, f"\n{_made_line(section)} · 방식 {method_label(section.generation_method)}")

    warning = document.add_paragraph()
    _small(warning, _warning_text(grounded_only, len(dropped), method=section.generation_method), color=_RED, bold=True)

    # --- 요약 -------------------------------------------------------------
    document.add_heading("반영 현황", level=1)
    summary = document.add_paragraph()
    _small(
        summary,
        f"필수 요구사항 {section.mandatory_total}건 중 대응 {section.requirements_with_sentence}건"
        f"  ·  회사 근거 {section.evidence_grounded_count}"
        f"  ·  공고문 근거 {section.rfp_grounded_count}"
        f"  ·  확인 필요 {section.needs_review_count}",
    )
    if parsed.truncated:
        note = document.add_paragraph()
        _small(
            note,
            f"※ 추출 상한으로 요구사항 후보 {parsed.candidate_count}건 중 {parsed.count}건만 "
            "검사했습니다. 이 문서는 검사한 범위만 다룹니다.",
            color=_RED,
        )

    # --- 본문 -------------------------------------------------------------
    document.add_heading("제안 내용", level=1)
    for index, sentence in enumerate(kept, start=1):
        body = document.add_paragraph(f"{index}. {_display_text(sentence.text)}")
        body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        source = document.add_paragraph()
        source.paragraph_format.left_indent = Pt(18)
        label = grounding_label(sentence)
        _small(source, f"[{label}] ")

        requirement = requirements.get(sentence.requirement_id or "")
        if requirement is not None:
            _small(source, f"{_ref(requirement)} ")
            _small(source, f"“{_short(requirement.source_text)}”")

        match = evidence.get((sentence.requirement_id or "", sentence.evidence_id or ""))
        if match is not None:
            origin = "가상 예시" if getattr(match, "synthetic", True) else "실제(비식별)"
            _small(
                source,
                f"\n회사 근거 · 「{match.document_name}」 ({origin}, 유사도 "
                f"{match.similarity_score:.3f})  “{_short(match.source_text)}”",
            )

    # --- 미대응 요구사항 ---------------------------------------------------
    if section.requirements_without_sentence:
        document.add_heading("대응 문장이 없는 요구사항", level=1)
        lead = document.add_paragraph()
        _small(
            lead,
            f"{len(section.requirements_without_sentence)}건입니다. 제안서 본문에 추가할지 "
            "담당자가 판단해야 합니다.",
        )
        for requirement_id in section.requirements_without_sentence:
            requirement = requirements.get(requirement_id)
            item = document.add_paragraph(style="List Bullet")
            if requirement is None:
                _small(item, requirement_id)
                continue
            _small(item, f"{_ref(requirement)}  ")
            _small(item, f"“{_short(requirement.source_text)}”")

    _docx_review_list(document, dropped, requirements)

    footer = document.add_paragraph()
    _small(
        footer,
        "\nBidPilot AI · 근거는 제안요청서 원문과 회사 근거자료에서 그대로 인용했습니다. "
        "원문에 없는 내용은 생성하지 않았습니다.",
    )

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# TXT — 같은 내용을 서식 없이. Word가 없는 자리에서도 열린다.
# ---------------------------------------------------------------------------

FOOTER_TEXT = (
    "BidPilot AI · 근거는 제안요청서 원문과 회사 근거자료에서 그대로 인용했습니다. "
    "원문에 없는 내용은 생성하지 않았습니다."
)


def _text_head(title: str, notice_line: str, parsed: RfpParseResult, method: str) -> list[str]:
    lines = [title, "=" * min(len(title) * 2, 60), f"공고  {notice_line}"]
    origin = f"원문  {parsed.document} ({parsed.doc_format}, {parsed.page_count}쪽)"
    if parsed.page_is_approximate:
        origin += " · 한글 파일이라 쪽 번호는 대략입니다"
    lines.append(origin)
    lines.append(f"생성  {datetime.now(KST):%Y-%m-%d %H:%M} · 방식 {method_label(method)}")
    return lines


def _text_requirement_list(
    heading: str, lead: str, requirement_ids: list[str], requirements: dict[str, Requirement]
) -> list[str]:
    lines = ["", heading, "-" * 30, lead]
    for requirement_id in requirement_ids:
        requirement = requirements.get(requirement_id)
        if requirement is None:
            lines.append(f"- {requirement_id}")
            continue
        lines.append(f"- {_ref(requirement)}  “{_short(requirement.source_text)}”")
    return lines


def _text_body(
    blocks: list[tuple[str, list[str], list]],
    requirements: dict[str, Requirement],
    evidence: dict,
) -> list[str]:
    """blocks = [(섹션 제목, 카테고리 목록, 문장 목록)]."""
    lines: list[str] = []
    for title, categories, sentences in blocks:
        lines += ["", title, "-" * 30]
        if categories:
            lines.append(f"요구사항 카테고리: {', '.join(categories)}")
        for index, sentence in enumerate(sentences, start=1):
            lines.append(f"{index}. {_display_text(sentence.text)}")
            for line in _evidence_lines(sentence, requirements, evidence):
                lines.append(f"   {line}")
            lines.append("")
    return lines


def _text_review_list(dropped: list, requirements: dict[str, Requirement]) -> list[str]:
    if not dropped:
        return []
    return _text_requirement_list(
        "담당자 확인 목록",
        f"회사 근거자료가 없어 본문에서 뺀 요구사항 {len(dropped)}건입니다. "
        "근거를 찾아 넣을지, 그대로 제안할지 담당자가 판단해야 합니다.",
        [s.requirement_id or s.id for s in dropped],
        requirements,
    )


def _encode_text(lines: list[str]) -> bytes:
    # BOM을 붙인다 — 메모장 구버전이 한글 UTF-8을 EUC-KR로 오판하는 것을 막는다.
    return "\n".join(lines).encode("utf-8-sig")


def build_text(
    section: ProposalSection,
    parsed: RfpParseResult,
    *,
    notice_line: str,
    evidence: dict[tuple[str, str], object] | None = None,
    grounded_only: bool = False,
) -> bytes:
    """핵심 섹션 초안을 TXT 바이트로 만든다. DOCX와 같은 내용·같은 근거를 싣는다."""
    if not section.sentences:
        raise ProposalExportError("내보낼 제안서 문장이 없습니다")
    kept, dropped = _split_sentences(section.sentences, grounded_only)
    if not kept:
        raise ProposalExportError("근거가 연결된 문장이 없어 근거만 실은 문서를 만들 수 없습니다")
    evidence = evidence or {}
    requirements = {r.requirement_id: r for r in parsed.requirements}

    lines = _text_head(section.title, notice_line, parsed, section.generation_method)
    lines += ["", "※ " + _warning_text(grounded_only, len(dropped), method=section.generation_method)]
    lines += [
        "",
        "반영 현황",
        "-" * 30,
        f"필수 요구사항 {section.mandatory_total}건 중 대응 {section.requirements_with_sentence}건"
        f" · 회사 근거 {section.evidence_grounded_count}"
        f" · 공고문 근거 {section.rfp_grounded_count}"
        f" · 확인 필요 {section.needs_review_count}",
    ]
    if parsed.truncated:
        lines.append(
            f"※ 추출 상한으로 요구사항 후보 {parsed.candidate_count}건 중 {parsed.count}건만 "
            "검사했습니다. 이 문서는 검사한 범위만 다룹니다."
        )
    lines += _text_body([("제안 내용", [], kept)], requirements, evidence)
    lines += _text_review_list(dropped, requirements)
    if section.requirements_without_sentence:
        lines += _text_requirement_list(
            "대응 문장이 없는 요구사항",
            f"{len(section.requirements_without_sentence)}건입니다. 제안서 본문에 추가할지 "
            "담당자가 판단해야 합니다.",
            section.requirements_without_sentence,
            requirements,
        )
    lines += ["", FOOTER_TEXT, ""]
    return _encode_text(lines)


def build_full_text(
    document,
    parsed: RfpParseResult,
    *,
    notice_line: str,
    evidence: dict[tuple[str, str], object] | None = None,
    grounded_only: bool = False,
) -> bytes:
    """제안서 전체 초안을 TXT 바이트로 만든다."""
    if not document.sections:
        raise ProposalExportError("내보낼 섹션이 없습니다")
    evidence = evidence or {}
    requirements = {r.requirement_id: r for r in parsed.requirements}

    blocks: list[tuple[str, list[str], list]] = []
    dropped_all: list = []
    for section in document.sections:
        kept, dropped = _split_sentences(section.sentences, grounded_only)
        dropped_all += dropped
        if kept:
            blocks.append((_numbered(len(blocks) + 1, section.title), document.section_categories.get(section.title) or [], kept))
    if not blocks:
        raise ProposalExportError("근거가 연결된 문장이 없어 근거만 실은 문서를 만들 수 없습니다")

    lines = _text_head(_display_title(document, notice_line), notice_line, parsed, document.generation_method)
    lines += ["", "※ " + _warning_text(grounded_only, len(dropped_all), full=True, method=document.generation_method)]
    lines += [
        "",
        "반영 현황",
        "-" * 30,
        f"섹션 {len(blocks)}개 · 필수 요구사항 {document.mandatory_total}건 중 대응 "
        f"{document.requirements_with_sentence}건"
        f" · 회사 근거 {document.evidence_grounded_count}"
        f" · 공고문 근거 {document.rfp_grounded_count}"
        f" · 확인 필요 {document.needs_review_count}",
    ]
    if parsed.truncated:
        lines.append(
            f"※ 추출 상한으로 요구사항 후보 {parsed.candidate_count}건 중 {parsed.count}건만 다뤘습니다."
        )
    lines += _text_body(blocks, requirements, evidence)
    lines += _text_review_list(dropped_all, requirements)
    if document.requirements_without_sentence:
        lines += _text_requirement_list(
            "대응 문장이 없는 요구사항",
            f"{len(document.requirements_without_sentence)}건입니다. 근거도 의무 표현도 없어 "
            "문장을 만들지 않았습니다. 제안서에 넣을지 담당자가 판단해야 합니다.",
            document.requirements_without_sentence,
            requirements,
        )
    lines += ["", FOOTER_TEXT, ""]
    return _encode_text(lines)


# ---------------------------------------------------------------------------
# PDF — 설치된 Microsoft Word(COM)로 DOCX를 저장한다. Windows 전용.
# ---------------------------------------------------------------------------


def docx_to_pdf(payload: bytes) -> bytes:
    """DOCX 바이트를 PDF 바이트로 바꾼다.

    별도 PDF 라이브러리 없이 이 PC의 Word를 쓴다(한글 글꼴·표 서식이 그대로 유지된다).
    Word가 없거나 Windows가 아니면 PdfConverterUnavailableError — API는 503으로 알린다.
    """
    if sys.platform != "win32":
        raise PdfConverterUnavailableError("이 서버에서는 PDF로 바꿀 수 없습니다(Microsoft Word가 있는 Windows에서만 됩니다) — docx 로 받아 주세요")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / "draft.docx"
        dst = Path(tmp) / "draft.pdf"
        src.write_bytes(payload)
        # 17 = wdFormatPDF. 경로에 따옴표가 없으므로 PowerShell 단일따옴표 문자열로 안전하다.
        script = (
            "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
            f"$d = $w.Documents.Open('{src}', $false, $true); "
            f"$d.SaveAs2('{dst}', 17); $d.Close($false); $w.Quit()"
        )
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                check=True,
                capture_output=True,
                timeout=PDF_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # 예외 이름(「CalledProcessError」)은 로그에만 — 화면 문장에는 싣지 않는다 (DTL-14).
            logger.warning("PDF 변환 실패 — Word 실행 오류 %s: %s", type(exc).__name__, exc)
            raise PdfConverterUnavailableError(
                "PDF 변환 실패: Microsoft Word를 열 수 없습니다 — docx 로 받아 주세요"
            ) from exc
        if not dst.exists():
            raise PdfConverterUnavailableError("PDF 변환 실패: 결과 파일이 만들어지지 않았습니다")
        return dst.read_bytes()


# ---------------------------------------------------------------------------
# 내려받기 진입점
# ---------------------------------------------------------------------------


def _file_name(procurement_id: str, kind: str, fmt: str, grounded_only: bool) -> str:
    suffix = "_근거문장만" if grounded_only else ""
    return f"{procurement_id}_{kind}{suffix}_{datetime.now(KST):%Y%m%d}.{fmt}"


async def _finish(docx_payload: bytes, txt_payload_factory, fmt: str) -> bytes:
    if fmt == "docx":
        return docx_payload
    if fmt == "pdf":
        # Word 변환은 동기 `subprocess.run`(최대 120초)이다 — 이벤트 루프에서 기다리면 그동안 서버 전체가 선다(27차 R26-03).
        return await run_in_threadpool(docx_to_pdf, docx_payload)
    if fmt == "txt":
        return txt_payload_factory()
    raise ProposalExportError(f"지원하지 않는 형식입니다: {fmt}")


async def export_section(
    procurement_id: str, *, fmt: ExportFormat = "docx", grounded_only: bool = False, context=None) -> tuple[bytes, str, str]:
    """저장된 제안서를 문서로 만들어 (바이트, 파일명, media type)을 돌려준다."""
    section = wording.modernize_model(proposal_service.load_section(procurement_id, context=context))
    parsed = rfp_parser.load_generated(procurement_id)
    _refuse_stale([section], parsed, procurement_id)  # 44차 S2
    notice_line = await _notice_line(procurement_id)
    evidence = _evidence_index(parsed.requirements, context)
    common = dict(notice_line=notice_line, evidence=evidence, grounded_only=grounded_only)
    payload = await _finish(
        build_document(section, parsed, **common) if fmt != "txt" else b"",
        lambda: build_text(section, parsed, **common),
        fmt,
    )
    return payload, _file_name(procurement_id, "제안서초안", fmt, grounded_only), MEDIA_TYPES[fmt]


def build_full_document(
    document,
    parsed: RfpParseResult,
    *,
    notice_line: str,
    evidence: dict[tuple[str, str], object] | None = None,
    grounded_only: bool = False,
) -> bytes:
    """제안서 전체 초안(섹션 여러 개)을 DOCX로 만든다.

    섹션 구성은 요구사항 카테고리를 따른다. 요구사항이 없는 목차는 만들지 않는다.
    """
    if not document.sections:
        raise ProposalExportError("내보낼 섹션이 없습니다")
    all_sentences = [s for section in document.sections for s in section.sentences]
    kept_all, dropped_all = _split_sentences(all_sentences, grounded_only)
    if not kept_all:
        raise ProposalExportError("근거가 연결된 문장이 없어 근거만 실은 문서를 만들 수 없습니다")

    evidence = evidence or {}
    requirements = {r.requirement_id: r for r in parsed.requirements}

    doc = Document()
    plan_export_service.apply_document_style(doc)  # 44차 S9 — 사업계획서와 같은 문서 모양
    title = _display_title(document, notice_line)
    doc.core_properties.title = title
    doc.core_properties.comments = "BidPilot AI 생성 초안 — 담당자 검토 필요"

    doc.add_heading(title, level=0)

    head = doc.add_paragraph()
    _small(head, f"공고  {notice_line}\n")
    _small(head, f"원문  {parsed.document} ({parsed.doc_format}, {parsed.page_count}쪽)")
    if parsed.page_is_approximate:
        _small(head, "  · 한글 파일이라 쪽 번호는 대략입니다")
    _small(head, f"\n생성  {datetime.now(KST):%Y-%m-%d %H:%M} · 방식 {method_label(document.generation_method)}")

    warning = doc.add_paragraph()
    _small(warning, _warning_text(grounded_only, len(dropped_all), full=True, method=document.generation_method), color=_RED, bold=True)

    doc.add_heading("반영 현황", level=1)
    summary = doc.add_paragraph()
    _small(
        summary,
        f"섹션 {len(document.sections)}개  ·  "
        f"필수 요구사항 {document.mandatory_total}건 중 대응 {document.requirements_with_sentence}건"
        f"  ·  회사 근거 {document.evidence_grounded_count}"
        f"  ·  공고문 근거 {document.rfp_grounded_count}"
        f"  ·  확인 필요 {document.needs_review_count}",
    )
    if parsed.truncated:
        note = doc.add_paragraph()
        _small(
            note,
            f"※ 추출 상한으로 요구사항 후보 {parsed.candidate_count}건 중 {parsed.count}건만 "
            "다뤘습니다.",
            color=_RED,
        )

    shown = 0
    for section in document.sections:
        kept, _dropped = _split_sentences(section.sentences, grounded_only)
        if not kept:
            continue  # 근거 문장이 하나도 없는 섹션은 빈 제목만 남기지 않는다
        shown += 1
        doc.add_heading(_numbered(shown, section.title), level=1)
        categories = document.section_categories.get(section.title) or []
        if categories:
            meta = doc.add_paragraph()
            _small(meta, f"요구사항 카테고리: {', '.join(categories)}")

        for index, sentence in enumerate(kept, start=1):
            body = doc.add_paragraph(f"{index}. {_display_text(sentence.text)}")
            body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

            source = doc.add_paragraph()
            source.paragraph_format.left_indent = Pt(18)
            label = grounding_label(sentence)
            _small(source, f"[{label}] ")

            requirement = requirements.get(sentence.requirement_id or "")
            if requirement is not None:
                _small(source, f"{_ref(requirement)} ")
                _small(source, f"“{_short(requirement.source_text)}”")

            match = evidence.get((sentence.requirement_id or "", sentence.evidence_id or ""))
            if match is not None:
                origin = "가상 예시" if getattr(match, "synthetic", True) else "실제(비식별)"
                _small(
                    source,
                    f"\n회사 근거 · 「{match.document_name}」 ({origin}, 유사도 "
                    f"{match.similarity_score:.3f})  “{_short(match.source_text)}”",
                )

    if document.requirements_without_sentence:
        doc.add_heading("대응 문장이 없는 요구사항", level=1)
        lead = doc.add_paragraph()
        _small(
            lead,
            f"{len(document.requirements_without_sentence)}건입니다. 근거도 의무 표현도 없어 "
            "문장을 만들지 않았습니다. 제안서에 넣을지 담당자가 판단해야 합니다.",
        )
        for requirement_id in document.requirements_without_sentence:
            requirement = requirements.get(requirement_id)
            item = doc.add_paragraph(style="List Bullet")
            if requirement is None:
                _small(item, requirement_id)
                continue
            _small(item, f"{_ref(requirement)} · {requirement.category}  ")
            _small(item, f"“{_short(requirement.source_text)}”")

    _docx_review_list(doc, dropped_all, requirements)

    footer = doc.add_paragraph()
    _small(
        footer,
        "\nBidPilot AI · 근거는 제안요청서 원문과 회사 근거자료에서 그대로 인용했습니다. "
        "원문에 없는 내용은 생성하지 않았습니다.",
    )

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


async def export_full(
    procurement_id: str, *, fmt: ExportFormat = "docx", grounded_only: bool = False, context=None) -> tuple[bytes, str, str]:
    """제안서 전체 초안을 문서로 만들어 (바이트, 파일명, media type)을 돌려준다."""
    document = wording.modernize_model(proposal_service.load_document(procurement_id, context=context))
    parsed = rfp_parser.load_generated(procurement_id)
    _refuse_stale(document.sections, parsed, procurement_id)  # 44차 S2 — 옛 초안은 경고만 붙여 내보내지 않는다
    notice_line = await _notice_line(procurement_id)
    evidence = _evidence_index(parsed.requirements, context)
    common = dict(notice_line=notice_line, evidence=evidence, grounded_only=grounded_only)
    payload = await _finish(
        build_full_document(document, parsed, **common) if fmt != "txt" else b"",
        lambda: build_full_text(document, parsed, **common),
        fmt,
    )
    return payload, _file_name(procurement_id, "제안서전체초안", fmt, grounded_only), MEDIA_TYPES[fmt]
