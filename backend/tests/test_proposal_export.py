"""제안서 초안 문서 내보내기 테스트.

핵심 계약
    - 문장마다 RFP 페이지·원문이 문서에 함께 실린다. 화면에서 보이던 근거가
      파일로 나가면서 사라지면 안 된다.
    - **evidence_id는 문서 단위라 chunk를 특정하지 못한다.** 같은 문서의 다른 문단이
      각각 다른 요구사항에 채택되면 evidence_id가 겹친다. 요구사항까지 함께 봐야
      엉뚱한 원문을 인용하지 않는다 (실측 사고: EV-01이 REQ-002/REQ-009에 다른 문단으로 붙음).
    - 완성본이 아니라 초안임을 문서가 스스로 밝힌다.
    - 대응 문장이 없는 요구사항을 문서 끝에 그대로 나열한다. 빠진 것을 숨기지 않는다.

네트워크를 쓰지 않는다.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import docx
import pytest

from app.schemas.proposal import ProposalSection, ProposalSentence
from app.schemas.requirement import PageInfo, Requirement, RfpParseResult
from app.services import proposal_export


class FakeMatch:
    """evidence_service.EvidenceMatch 중 문서가 쓰는 필드만 흉내낸다."""

    def __init__(self, document_name: str, source_text: str, score: float, synthetic: bool = True):
        self.document_name = document_name
        self.source_text = source_text
        self.similarity_score = score
        self.synthetic = synthetic


def make_requirement(req_id: str, page: int, source_text: str) -> Requirement:
    return Requirement(
        id=f"test:{req_id}",
        procurement_id="test",
        requirement_id=req_id,
        category="과업내용",
        requirement_type="mandatory",
        title=source_text[:20],
        content=source_text,
        page=page,
        source_text=source_text,
    )


def make_parsed(requirements: list[Requirement], *, truncated: bool = False) -> RfpParseResult:
    return RfpParseResult(
        procurement_id="test",
        source="g2b_attachment",
        document="제안요청서.hwp",
        doc_format="hwp",
        page_is_approximate=True,
        page_count=11,
        pages=[PageInfo(page=1, char_count=100)],
        empty_pages=[],
        count=len(requirements),
        candidate_count=185 if truncated else len(requirements),
        truncated=truncated,
        requirements=requirements,
        generated_at=datetime.now(timezone.utc),
    )


def make_section(sentences: list[ProposalSentence], *, title: str | None = None, **kwargs) -> ProposalSection:
    payload = {
        "id": "PROP-test",
        "title": title or "사업수행계획 (핵심 섹션)",
        "sentences": sentences,
        "procurement_id": "test",
        "mandatory_total": 3,
        "requirements_with_sentence": len(sentences),
        "requirements_without_sentence": [],
        "evidence_grounded_count": 0,
        "rfp_grounded_count": len(sentences),
        "needs_review_count": 0,
    }
    payload.update(kwargs)
    return ProposalSection(**payload)


def text_of(payload: bytes) -> str:
    document = docx.Document(io.BytesIO(payload))
    return "\n".join(p.text for p in document.paragraphs)


# --------------------------------------------------------------------------
# 근거 보존
# --------------------------------------------------------------------------


def test_문장마다_RFP_페이지와_원문을_싣는다() -> None:
    requirements = [make_requirement("REQ-001", 2, "교육은 총 12회 운영하여야 한다")]
    section = make_section(
        [ProposalSentence(id="PS-01", text="교육을 12회 운영합니다.",
                          grounding_type="RFP_GROUNDED", requirement_id="REQ-001")]
    )

    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="테스트 공고"))

    assert "1번 요구사항" in body and "REQ-001" not in body  # 내보낸 파일도 화면 말(32차 R31-24)
    assert "제안요청서 2쪽" in body
    assert "교육은 총 12회 운영하여야 한다" in body


def test_같은_evidence_id라도_요구사항별로_다른_원문을_인용한다() -> None:
    """evidence_id는 문서 단위다. 요구사항까지 봐야 chunk가 특정된다."""
    requirements = [
        make_requirement("REQ-002", 2, "생성형 AI 교육과정을 기획한다"),
        make_requirement("REQ-009", 2, "AI Agent 프로젝트를 발표한다"),
    ]
    section = make_section([
        ProposalSentence(id="PS-01", text="교육과정을 기획합니다.",
                         grounding_type="COMPANY_EVIDENCE_GROUNDED",
                         requirement_id="REQ-002", evidence_id="EV-01"),
        ProposalSentence(id="PS-02", text="프로젝트를 발표합니다.",
                         grounding_type="COMPANY_EVIDENCE_GROUNDED",
                         requirement_id="REQ-009", evidence_id="EV-01"),
    ])
    evidence = {
        ("REQ-002", "EV-01"): FakeMatch("커리큘럼", "생성형 AI 활용 실무 모듈", 0.626),
        ("REQ-009", "EV-01"): FakeMatch("커리큘럼", "에이전트 프로젝트 설계·구현", 0.647),
    }

    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="테스트", evidence=evidence))

    assert "생성형 AI 활용 실무 모듈" in body
    assert "에이전트 프로젝트 설계·구현" in body
    assert "0.626" in body and "0.647" in body


def test_회사근거의_합성_여부를_문서에_밝힌다() -> None:
    requirements = [make_requirement("REQ-001", 1, "요구사항")]
    section = make_section([
        ProposalSentence(id="PS-01", text="문장.", grounding_type="COMPANY_EVIDENCE_GROUNDED",
                         requirement_id="REQ-001", evidence_id="EV-01")
    ])

    synthetic = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="t",
        evidence={("REQ-001", "EV-01"): FakeMatch("자료", "원문", 0.7, synthetic=True)}))
    real = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="t",
        evidence={("REQ-001", "EV-01"): FakeMatch("자료", "원문", 0.7, synthetic=False)}))

    assert "가상 예시" in synthetic
    assert "실제(비식별)" in real


# --------------------------------------------------------------------------
# 빠진 것을 숨기지 않는다
# --------------------------------------------------------------------------


def test_근거_없는_문장은_확인_필요로_표시한다() -> None:
    requirements = [make_requirement("REQ-001", 1, "요구사항")]
    section = make_section(
        [ProposalSentence(id="PS-01", text="문장.", grounding_type="RFP_GROUNDED",
                          requirement_id="REQ-001", needs_review=True)],
        needs_review_count=1,
    )
    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="t"))
    assert "확인 필요" in body


def test_대응_문장이_없는_요구사항을_문서_끝에_나열한다() -> None:
    requirements = [
        make_requirement("REQ-001", 1, "대응한 요구사항"),
        make_requirement("REQ-002", 4, "빠뜨린 요구사항 원문"),
    ]
    section = make_section(
        [ProposalSentence(id="PS-01", text="문장.", grounding_type="RFP_GROUNDED",
                          requirement_id="REQ-001")],
        requirements_without_sentence=["REQ-002"],
    )
    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="t"))

    assert "대응 문장이 없는 요구사항" in body
    assert "2번 요구사항" in body
    assert "빠뜨린 요구사항 원문" in body
    assert "제안요청서 4쪽" in body


def test_추출_상한에_잘렸으면_문서에_적는다() -> None:
    requirements = [make_requirement("REQ-001", 1, "요구사항")]
    section = make_section([ProposalSentence(id="PS-01", text="문장.",
                                             grounding_type="RFP_GROUNDED",
                                             requirement_id="REQ-001")])
    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements, truncated=True), notice_line="t"))
    assert "185" in body and "검사했습니다" in body


# --------------------------------------------------------------------------
# 초안임을 밝힌다
# --------------------------------------------------------------------------


def test_완성본이_아니라_초안임을_문서가_밝힌다() -> None:
    requirements = [make_requirement("REQ-001", 1, "요구사항")]
    section = make_section([ProposalSentence(id="PS-01", text="문장.",
                                             grounding_type="RFP_GROUNDED",
                                             requirement_id="REQ-001")])
    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="t"))

    assert "초안" in body
    assert "담당자가" in body and "확정" in body


def test_반영_현황_수치를_그대로_싣는다() -> None:
    requirements = [make_requirement("REQ-001", 1, "요구사항")]
    section = make_section(
        [ProposalSentence(id="PS-01", text="문장.", grounding_type="RFP_GROUNDED",
                          requirement_id="REQ-001")],
        mandatory_total=30, requirements_with_sentence=18,
        evidence_grounded_count=8, rfp_grounded_count=10, needs_review_count=5,
    )
    body = text_of(proposal_export.build_document(
        section, make_parsed(requirements), notice_line="t"))
    assert "30" in body and "18" in body


def test_문장이_없으면_내보내지_않는다() -> None:
    """빈 문서를 만들어 주지 않는다."""
    section = make_section([], requirements_with_sentence=0, rfp_grounded_count=0)
    with pytest.raises(proposal_export.ProposalExportError):
        proposal_export.build_document(section, make_parsed([]), notice_line="t")


# --------------------------------------------------------------------------
# 전체 초안 (섹션 여러 개)
# --------------------------------------------------------------------------


def make_document(sections, **kwargs):
    from app.schemas.proposal_document import ProposalDocument

    payload = {
        "id": "PROPDOC-test",
        "procurement_id": "test",
        "title": "제안서 초안 (test)",
        "sections": sections,
        "mandatory_total": 3,
        "requirements_with_sentence": sum(len(s.sentences) for s in sections),
        "requirements_without_sentence": [],
        "evidence_grounded_count": 0,
        "rfp_grounded_count": sum(len(s.sentences) for s in sections),
        "needs_review_count": 0,
        "section_categories": {},
    }
    payload.update(kwargs)
    return ProposalDocument(**payload)


def test_전체_초안은_섹션_제목을_문서에_싣는다() -> None:
    requirements = [
        make_requirement("REQ-001", 2, "과업 요구사항"),
        make_requirement("REQ-002", 3, "일정 요구사항"),
    ]
    sections = [
        make_section([ProposalSentence(id="PS-01", text="과업 문장.",
                                       grounding_type="RFP_GROUNDED",
                                       requirement_id="REQ-001")],
                     title="2. 과업 수행계획"),
        make_section([ProposalSentence(id="PS-02", text="일정 문장.",
                                       grounding_type="RFP_GROUNDED",
                                       requirement_id="REQ-002")],
                     title="3. 추진 일정"),
    ]
    document = make_document(
        sections, section_categories={"2. 과업 수행계획": ["과업내용"], "3. 추진 일정": ["일정"]}
    )

    body = text_of(proposal_export.build_full_document(
        document, make_parsed(requirements), notice_line="테스트 공고"))

    # 43차 E2E-12 — 1절(사업개요)이 빠져도 실은 절만 1 · 2 로 차례로 매긴다 · 제목은 공고명
    assert "1. 과업 수행계획" in body and "2. 추진 일정" in body
    assert "2. 과업 수행계획" not in body
    assert body.startswith("제안서 초안 — 테스트 공고")
    assert "요구사항 카테고리: 과업내용" in body
    assert "제안요청서 2쪽" in body and "제안요청서 3쪽" in body


def test_전체_초안도_대응_없는_요구사항을_원문과_함께_나열한다() -> None:
    requirements = [
        make_requirement("REQ-001", 2, "대응한 요구사항"),
        make_requirement("REQ-007", 5, "근거도 의무 표현도 없는 요구사항"),
    ]
    sections = [make_section([ProposalSentence(id="PS-01", text="문장.",
                                               grounding_type="RFP_GROUNDED",
                                               requirement_id="REQ-001")],
                             title="2. 과업 수행계획")]
    document = make_document(sections, requirements_without_sentence=["REQ-007"])

    body = text_of(proposal_export.build_full_document(
        document, make_parsed(requirements), notice_line="t"))

    assert "7번 요구사항" in body
    assert "근거도 의무 표현도 없는 요구사항" in body
    assert "제안요청서 5쪽" in body


def test_섹션이_없으면_전체_초안을_만들지_않는다() -> None:
    """빈 목차 문서를 내주지 않는다."""
    with pytest.raises(proposal_export.ProposalExportError):
        proposal_export.build_full_document(
            make_document([]), make_parsed([]), notice_line="t")


# --------------------------------------------------------------------------
# 근거 있는 문장만 / TXT / 형식
# --------------------------------------------------------------------------


def make_mixed_section() -> ProposalSection:
    return make_section(
        [
            ProposalSentence(
                id="PS-01", text="근거 있는 문장입니다.", grounding_type="COMPANY_EVIDENCE_GROUNDED",
                requirement_id="REQ-001", evidence_id="EV-01", needs_review=False,
            ),
            ProposalSentence(
                id="PS-02", text="근거 없는 문장입니다.", grounding_type="RFP_GROUNDED",
                requirement_id="REQ-002", needs_review=True,
            ),
            ProposalSentence(
                id="PS-03", text="AI 제안 문장입니다.", grounding_type="AI_SUGGESTION",
                requirement_id="REQ-003", needs_review=False,
            ),
        ],
        needs_review_count=1,
        evidence_grounded_count=1,
        rfp_grounded_count=1,
    )


def mixed_parsed() -> RfpParseResult:
    return make_parsed(
        [
            make_requirement("REQ-001", 2, "첫째 요구사항 원문"),
            make_requirement("REQ-002", 3, "둘째 요구사항 원문"),
            make_requirement("REQ-003", 4, "셋째 요구사항 원문"),
        ]
    )


def test_근거만_모드는_확인필요와_AI제안_문장을_본문에서_뺀다() -> None:
    text = text_of(proposal_export.build_document(
        make_mixed_section(), mixed_parsed(), notice_line="t", grounded_only=True))
    assert "1. 근거 있는 문장입니다." in text
    assert "근거 없는 문장입니다." not in text
    assert "AI 제안 문장입니다." not in text


def test_근거만_모드는_뺀_문장을_확인_목록에_원문과_함께_남긴다() -> None:
    """빠진 것을 숨기지 않는다 — 뺀 요구사항은 문서 끝에 원문과 함께 나열한다."""
    text = text_of(proposal_export.build_document(
        make_mixed_section(), mixed_parsed(), notice_line="t", grounded_only=True))
    assert "담당자 확인 목록" in text
    assert "제안요청서 3쪽 · 2번 요구사항" in text and "둘째 요구사항 원문" in text
    assert "제안요청서 4쪽 · 3번 요구사항" in text and "셋째 요구사항 원문" in text
    assert "문장 2건은 본문에서 빼고" in text


def test_기본_모드는_모든_문장을_싣고_확인_목록을_만들지_않는다() -> None:
    text = text_of(proposal_export.build_document(
        make_mixed_section(), mixed_parsed(), notice_line="t"))
    assert "근거 없는 문장입니다." in text
    assert "담당자 확인 목록" not in text


def test_근거_문장이_하나도_없으면_근거만_문서를_만들지_않는다() -> None:
    section = make_section([
        ProposalSentence(id="PS-01", text="확인 필요 문장", grounding_type="RFP_GROUNDED",
                         requirement_id="REQ-001", needs_review=True),
    ])
    with pytest.raises(proposal_export.ProposalExportError):
        proposal_export.build_document(section, mixed_parsed(), notice_line="t", grounded_only=True)


def test_TXT도_문장마다_RFP_페이지와_원문을_싣는다() -> None:
    payload = proposal_export.build_text(make_mixed_section(), mixed_parsed(), notice_line="공고 t")
    text = payload.decode("utf-8-sig")
    assert text.startswith("사업수행계획")
    assert "공고  공고 t" in text
    assert "1. 근거 있는 문장입니다." in text
    assert "[회사 근거] 제안요청서 2쪽 · 1번 요구사항 “첫째 요구사항 원문”" in text
    # 11-03 대표 「확인 필요 — 채택된 회사 근거자료가 없습니다 모두 쓰지 마」 — 문장마다 붙던 확인 필요 줄은 없다
    assert "확인 필요 — " not in text
    assert "규칙으로 만든 초안입니다" in text and "AI가 만든 초안" not in text  # 45차 H4 — 만든 방식대로
    assert "방식 규칙" in text and "RULE" not in text


def test_AI로_만든_초안은_AI가_만든_초안이라고_적는다() -> None:
    section = make_mixed_section().model_copy(update={"generation_method": "LLM"})
    text = proposal_export.build_text(section, mixed_parsed(), notice_line="공고 t").decode("utf-8-sig")
    assert "AI가 만든 초안입니다" in text and "방식 AI" in text and "LLM" not in text


def test_TXT_근거만_모드도_확인_목록을_남긴다() -> None:
    text = proposal_export.build_text(
        make_mixed_section(), mixed_parsed(), notice_line="t", grounded_only=True
    ).decode("utf-8-sig")
    assert "근거 없는 문장입니다." not in text
    assert "담당자 확인 목록" in text
    assert "제안요청서 3쪽 · 2번 요구사항" in text


def test_TXT는_BOM을_붙인다() -> None:
    payload = proposal_export.build_text(make_mixed_section(), mixed_parsed(), notice_line="t")
    assert payload.startswith(b"\xef\xbb\xbf")


def test_전체_초안_근거만_모드는_빈_섹션_제목을_남기지_않는다() -> None:
    only_review = make_section(
        [ProposalSentence(id="PS-09", text="확인 필요만", grounding_type="RFP_GROUNDED",
                          requirement_id="REQ-002", needs_review=True)],
        title="9. 평가 대응",
    )
    document = make_document([make_mixed_section(), only_review])
    docx_text = text_of(proposal_export.build_full_document(
        document, mixed_parsed(), notice_line="t", grounded_only=True))
    assert "9. 평가 대응" not in docx_text
    txt = proposal_export.build_full_text(
        document, mixed_parsed(), notice_line="t", grounded_only=True).decode("utf-8-sig")
    assert "9. 평가 대응" not in txt
    assert "담당자 확인 목록" in txt


def test_파일명은_형식과_근거만_여부를_담는다() -> None:
    name = proposal_export._file_name("g2b-X", "제안서초안", "pdf", True)
    assert name.startswith("g2b-X_제안서초안_근거문장만_") and name.endswith(".pdf")
    plain = proposal_export._file_name("g2b-X", "제안서초안", "docx", False)
    assert "근거문장만" not in plain and plain.endswith(".docx")


def test_형식별_media_type() -> None:
    assert proposal_export.MEDIA_TYPES["pdf"] == "application/pdf"
    assert proposal_export.MEDIA_TYPES["txt"].startswith("text/plain")


def test_PDF_변환은_Word가_있을_때만_동작한다() -> None:
    """Word가 없는 환경에서는 503으로 이어지는 예외를 낸다. 있으면 실제 PDF가 나온다."""
    payload = proposal_export.build_document(make_mixed_section(), mixed_parsed(), notice_line="t")
    try:
        pdf = proposal_export.docx_to_pdf(payload)
    except proposal_export.PdfConverterUnavailableError:
        pytest.skip("이 환경에는 Microsoft Word가 없다")
    assert pdf.startswith(b"%PDF")


def test_PDF_실패_문장에_예외_이름을_싣지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """DTL-14 — 「Microsoft Word를 열 수 없습니다 (CalledProcessError)」처럼 예외 이름이 화면에 나왔다. 이름은 로그에만."""
    import subprocess

    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "powershell.exe")

    monkeypatch.setattr(proposal_export.sys, "platform", "win32")
    monkeypatch.setattr(proposal_export.subprocess, "run", boom)
    with pytest.raises(proposal_export.PdfConverterUnavailableError) as info:
        proposal_export.docx_to_pdf(b"x")
    assert "Error" not in str(info.value) and "docx" in str(info.value)


def test_본문_문장에서_규칙_생성_장식만_걷어낸다() -> None:
    """[제목]과 (근거: …)는 문서 아래 근거 줄과 겹치므로 본문에서는 뺀다. 주장은 그대로 둔다."""
    raw = ('[교육용 계정 운영·관리] 요구사항 "교육용 계정 운영·관리" 을 이행합니다. '
           '(근거: 「교육용 클라우드 계정 운영 자료(합성)」 p.1 "교육용 계정을 일괄 생성합니다.")')
    assert proposal_export._display_text(raw) == '요구사항 "교육용 계정 운영·관리" 을 이행합니다.'
    assert proposal_export._display_text(
        "보안성 검사를 필하여야 합니다. (RFP p.3 요구사항 준수)"
    ) == "보안성 검사를 필하여야 합니다."
    # 내용에 있는 괄호는 건드리지 않는다
    assert proposal_export._display_text("주말(토요일, 일요일)을 이용한 40시간 교육") == "주말(토요일, 일요일)을 이용한 40시간 교육"
    # 장식뿐인 문장은 원문을 돌려준다
    assert proposal_export._display_text("[제목만]") == "[제목만]"


def test_내보낸_문서_본문에는_근거_괄호가_두_번_실리지_않는다() -> None:
    section = make_section([
        ProposalSentence(
            id="PS-01",
            text='[첫째] 요구사항 "첫째 요구사항 원문" 을 이행합니다. (근거: 「자료」 p.1 "회사 문단")',
            grounding_type="COMPANY_EVIDENCE_GROUNDED", requirement_id="REQ-001", evidence_id="EV-01",
        )
    ])
    text = text_of(proposal_export.build_document(section, mixed_parsed(), notice_line="t"))
    assert '1. 요구사항 "첫째 요구사항 원문" 을 이행합니다.' in text
    assert "(근거:" not in text
