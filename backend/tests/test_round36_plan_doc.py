"""36차 §3-F — 사업계획서 내려받기 문서 다듬기(SPEC `docs/reports/2026-10-30_plan_doc_design/SPEC.md`).

내용은 한 글자도 바꾸지 않는다: 묶은 블록에서 다시 뽑은 글 · 유형 · 근거 · 빈칸 수가 초안과 같다(SPEC §22-2).
DOCX XML 은 SPEC §22-4 를 본다: 빈 문단 없음 · 줄 간격 고정 · wordWrap 없음 · 자동 빈칸 끔 · 호환성 15 · 표 틀.
실제 4개 초안(123852 · 126482 × Claude · Codex)의 전후 대조는 scratch 스크립트로 했다(진행 기록 §3-F). `data/private` 는 읽지 않는다.
"""

from __future__ import annotations

import io
import re
import zipfile

from app.services import plan_draft_service, plan_export_service
from app.services.plan_form_service import HUMAN_INPUT
from tests.test_plan_export import material  # noqa: F401 — pytest 픽스처

NOTICE, COMPANY, AI = plan_draft_service.NOTICE, plan_draft_service.COMPANY, plan_draft_service.SUGGESTION
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _s(text: str, kind: str | None = AI, source: str | None = None) -> dict:
    return {"text": text, "type": kind, "source": source, "source_ids": [], "ai": kind == AI, "flags": []}


#: 묶는 규칙이 만나는 모양을 모두 담은 소항목 — 공고 현황 문단 · 줄바꿈 목록 · ○ 소제목 · ○ 항목 · 라벨 줄 · 조각 · 단계 · 당사.
SENTENCES = [
    _s("재해예방사업은 마음건강 자가진단 중심으로 운영되고 있다.", NOTICE, "재해예방사업은 마음건강 자가진단 중심으로 운영되고 있다"),
    _s("공공데이터가 개별적으로 제공되고 있다.", NOTICE, "공고문 2쪽 — 공공데이터가 개별 제공"),
    _s("주요 성과 목표는 다음과 같습니다.\n- 응답 정확도: (담당자 입력)%\n- 위기 신호 안내율: (담당자 입력)%"),
    _s("○ 목표 고객과 시장 현황"),
    _s("당사가 겨냥하는 고객은 (담당자 입력)입니다."),
    _s("이 고객들은 현재 (담당자 입력) 방식으로 업무를 처리하고 있습니다."),
    _s("○ 1단계 준비: 목표 시장과 고객 요구를 정리하고 수행 체계를 세웁니다."),
    _s("○ 외부 협력 범위: (담당자 입력)"),
    _s("- 데이터 정제는 외부 기관과 함께 합니다."),
    _s("시장 규모: (담당자 입력)원"),
    _s("「시범 적용」 단계에서는 고객 환경에 적용합니다."),
    _s("당사는 사용성 시험으로 오류를 점검합니다.", COMPANY, "회사소개서 3쪽"),
    _s("세부 일정(담당자 확인)"),
    _s("이를 통해 고객이 겪던 불편을 줄입니다."),
]


def _section_draft(material) -> tuple[dict, dict]:
    draft, form = material
    solve = next(s for s in draft["sections"] if s["section"] == "과제 해결방안")
    solve["sentences"] = [dict(x) for x in SENTENCES]
    return draft, form


def _stream_from_draft(draft: dict, *, review: bool) -> tuple[str, str]:
    """초안에서 바로 뽑은 글 · 글자마다 유형 — 문서에 싣는 순서(안내 줄 · 공고 인용 빼고 · 제출용에서 뺀 선택 절 빼고)."""
    text, types = [], []
    for section in draft["sections"]:
        if section.get("kind") == "fields":
            continue
        content = plan_export_service._content(section)
        if not review and section.get("optional") and plan_export_service._blank_only(section) and not plan_export_service._photo_section(section):
            continue
        if not content and not plan_export_service._photo_section(section):
            content = [{"text": HUMAN_INPUT, "type": None}]  # 문장이 없는 절은 빈칸 한 줄(사진 절은 사진 칸)
        for sentence in content:
            squashed = re.sub(r"\s+", "", sentence["text"])
            text.append(squashed)
            types.append(str(sentence.get("type")) * len(squashed))
    return "".join(text), "".join(types)


def _stream_from_blocks(blocks: list) -> tuple[str, str]:
    text, types = [], []
    for block in blocks:
        if block[0] in plan_export_service.TEXT_KINDS:
            for line, kind, _source in block[1]:
                squashed = re.sub(r"\s+", "", line)
                text.append(squashed)
                types.append(str(kind) * len(squashed))
    return "".join(text), "".join(types)


def test_묶어도_글_유형_근거_빈칸이_그대로다(material) -> None:  # noqa: F811
    draft, form = _section_draft(material)
    for variant in ("submit", "review"):
        blocks = plan_export_service.document_blocks(draft, form, variant=variant, meta={})
        assert _stream_from_blocks(blocks) == _stream_from_draft(draft, review=variant == "review")
        sources = [s for b in blocks if b[0] in plan_export_service.TEXT_KINDS for _, _, s in b[1] if s]
        assert sources == [s["source"] for s in SENTENCES if s["source"]]  # 줄바꿈으로 나뉜 둘째 줄부터는 근거를 갖지 않는다


def test_묶는_규칙_SPEC_7(material) -> None:  # noqa: F811
    draft, form = _section_draft(material)
    blocks = plan_export_service.document_blocks(draft, form, variant="submit", meta={})
    at = next(i for i, b in enumerate(blocks) if b[0] == "h2" and b[1].endswith("과제 해결방안"))
    end = next(i for i in range(at + 1, len(blocks)) if blocks[i][0] in ("h1", "h2", "table"))
    got = [(b[0], [s[0] for s in b[1]], b[2]) for b in blocks[at + 1:end]]
    assert got == [
        ("para", [SENTENCES[0]["text"], SENTENCES[1]["text"]], 0),          # 소항목 첫머리 공고 현황 문단
        ("para", ["주요 성과 목표는 다음과 같습니다."], 0),                    # 「다음과 같습니다」는 문단을 닫는다
        ("dash", ["- 응답 정확도: (담당자 입력)%"], 0),                         # 줄바꿈 → 하위 줄
        ("dash", ["- 위기 신호 안내율: (담당자 입력)%"], 0),
        ("sub", ["○ 목표 고객과 시장 현황"], 0),                              # 문장 끝 · 쌍점 없음 → 소제목
        ("para", [SENTENCES[4]["text"], SENTENCES[5]["text"]], 1),          # 소제목 아래 본문은 5.25mm 안쪽
        ("item", [SENTENCES[6]["text"]], 0),                                # 쌍점 있는 글머리 줄 → 항목
        ("item", ["○ 외부 협력 범위: (담당자 입력)"], 0),                      # 빈칸으로 끝나면 소제목이 아니다
        ("dash", ["- 데이터 정제는 외부 기관과 함께 합니다."], 0),
        ("label", ["시장 규모: (담당자 입력)원"], 1),                           # 라벨 줄(값이 빈칸)
        ("para", ["「시범 적용」 단계에서는 고객 환경에 적용합니다."], 1),
        ("para", [SENTENCES[11]["text"]], 1),                                # 유형이 바뀌면 새 문단
        ("para", ["세부 일정(담당자 확인)"], 1),                               # 조각은 한 줄로 두고 붙이지 않는다
        ("para", ["이를 통해 고객이 겪던 불편을 줄입니다."], 1),
    ]
    h2 = blocks[at]
    assert h2[2:] == (12, 15)  # AI 덧붙임 n/m — m 은 소제목을 뺀 줄 수(줄바꿈으로 나뉜 줄 포함 · 공고 2 · 회사 1 · AI 12)
    assert plan_export_service._label_end("○ 1단계 준비: 목표") and plan_export_service._kind("○ 기술 개발 — 단계별 계획") == "sub"


def test_검토용_표식은_문단에_한_번_근거가_문장과_같으면_뺀다(material) -> None:  # noqa: F811
    draft, form = _section_draft(material)
    page = plan_export_service.build_html(draft, form, title="공고", variant="review")
    lead = re.search(r'<p class="para">(<span class="tag">\[공고\]</span>.*?)</p>', page).group(1)
    assert lead.count("[공고]") == 1 and lead.count("(근거:") == 1 and "(근거: 공고문 2쪽" in lead  # 첫 문장은 근거 = 문장 → 뺀다
    assert '<p class="para in ai">' in page and "[AI 덧붙임]" not in page
    assert '<span class="nb"><span class="blank">(담당자 입력)</span>원</span>' in page  # 「원」 한 글자가 홀로 넘어가지 않게
    submit = plan_export_service.build_html(draft, form, title="공고", variant="submit")
    assert "[공고]" not in submit and "(근거:" not in submit and 'class="para in ai"' not in submit


def _docx_xml(payload: bytes) -> tuple[str, str, str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        return z.read("word/document.xml").decode(), z.read("word/styles.xml").decode(), z.read("word/settings.xml").decode()


def test_DOCX_XML_SPEC_22_4(material) -> None:  # noqa: F811
    from docx import Document
    from docx.enum.text import WD_LINE_SPACING

    draft, form = _section_draft(material)
    meta = {"notice": "공고", "task": "과제", "company": "회사", "date": "2026. 10. 13."}
    for variant in ("submit", "review"):
        payload = plan_export_service.build_docx(draft, form, title="공고", variant=variant, meta=meta)
        document_xml, styles_xml, settings_xml = _docx_xml(payload)
        doc = Document(io.BytesIO(payload))
        body = doc.element.body
        # 본문의 빈 문단 0 — 빈 문단으로 간격 · 쪽을 띄우지 않는다
        assert all("".join(t.text or "" for t in p.iter(f"{W}t")).strip() for p in body.findall(f"{W}p"))
        # 본문 문단의 줄 간격은 모두 고정(스타일을 거슬러 올라가 본다)
        def rule(paragraph):
            fmt, style = paragraph.paragraph_format, paragraph.style
            while fmt.line_spacing_rule is None and style is not None:
                fmt, style = style.paragraph_format, style.base_style
            return fmt.line_spacing_rule

        cells = [p for t in doc.tables for row in t.rows for c in row.cells for p in c.paragraphs]
        assert {rule(p) for p in doc.paragraphs + cells} == {WD_LINE_SPACING.EXACTLY}
        assert "w:wordWrap" not in document_xml + styles_xml
        assert re.search(r'w:styleId="Normal".*?<w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/>', styles_xml, re.S)
        assert 'w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"' in settings_xml
        assert 'w:eastAsia="ko-KR"' in styles_xml
        for name in ("Normal", "heading 1", "heading 2"):  # 테마 글꼴 · 테마 색이 남으면 맑은 고딕 · 남색을 이긴다
            style = re.search(rf'<w:style [^>]*><w:name w:val="{name}"/>.*?</w:style>', styles_xml, re.S).group(0)
            assert "Theme" not in style and "theme" not in style and 'w:ascii="맑은 고딕"' in style
        for table in body.findall(f"{W}tbl"):
            assert table.find(f"{W}tblPr/{W}tblLayout").get(f"{W}type") == "fixed"
            rows = table.findall(f"{W}tr")
            assert all(r.find(f"{W}trPr/{W}cantSplit") is not None for r in rows)
            grid = sum(int(c.get(f"{W}w")) for c in table.findall(f"{W}tblGrid/{W}gridCol"))
            assert grid in (plan_export_service.TEXT_TW, 1701 + 5102)  # 본문 폭 166mm · 표지 이름 · 값 표 120mm
            for tr in rows:  # gridCol 과 모든 tcW 가 같은 값
                widths = [int(tc.find(f"{W}tcPr/{W}tcW").get(f"{W}w")) for tc in tr.findall(f"{W}tc")]
                assert sum(widths) == grid
        data = [t for t in body.findall(f"{W}tbl") if t.find(f"{W}tr/{W}trPr/{W}tblHeader") is not None]
        assert len(data) >= 5 and all(t.find(f"{W}tblPr/{W}tblBorders/{W}top").get(f"{W}color") == plan_export_service.NAVY for t in data)
        # 사진 칸 — 높이 최소 50mm
        assert 'w:trHeight w:val="2835" w:hRule="atLeast"' in document_xml
        assert ("검토용 · 제출 금지" in doc.sections[0].header.paragraphs[0].text) == (variant == "review")


def test_일반_현황은_4칸_표_짧은_칸끼리_한_줄(material) -> None:  # noqa: F811
    rows = plan_export_service.field_rows([("기업명", "주식회사 샘플에듀", ""), ("대표자", HUMAN_INPUT, ""), ("개업연월일", HUMAN_INPUT, ""),
                                           ("사업장 소재지", "전남광주통합특별시 북구 가상로 77, 가상창업보육센터 303호", ""),
                                           ("사업자등록번호", HUMAN_INPUT, ""), ("연락처", "062-000-0000", ""), ("제품 및 서비스 사진", HUMAN_INPUT, ""),
                                           ("사업분야", "교육 · 컨설팅 · 개발", "")])
    assert [[f[0] for f in row] for row in rows] == [["기업명", "대표자"], ["개업연월일"], ["사업장 소재지"], ["사업자등록번호", "연락처"],
                                                       ["제품 및 서비스 사진"], ["사업분야"]]
    assert plan_export_service.split_items("교육 · 컨설팅 · 개발") == ["교육", "컨설팅", "개발"]
    assert plan_export_service.split_items("A / B") == ["A / B"]


def test_그린_DOCX_본문에_초안_문장_칸_값_표_칸이_순서대로_다_있다(material) -> None:  # noqa: F811
    """36차 마지막 검토 F-2 — 내용 보존 시험이 시험 대상의 묶음 함수로 기대값을 만들었다. 여기서는 **그린 문서**를 초안과 바로 견준다."""
    from docx import Document

    draft, form = _section_draft(material)
    meta = {"notice": "공고", "task": "과제", "company": "회사", "date": "2026. 10. 13."}
    doc = Document(io.BytesIO(plan_export_service.build_docx(draft, form, title="공고", variant="review", meta=meta)))
    drawn = re.sub(r"\s+", "", "".join(t.text or "" for t in doc.element.body.iter(f"{W}t")).replace("\u00a0", " "))
    tables = {t.get("key"): t for t in draft.get("tables") or []}
    expected: list[str] = []
    for section in draft["sections"]:
        if section.get("kind") == "fields":
            expected += [str(f.get("label")) for f in section.get("fields") or []]
        else:
            expected += [line for s in plan_export_service._content(section) for line in str(s["text"]).split("\n") if line.strip()]
        for key in section.get("tables") or []:
            if key in tables:
                expected += [str(c) for row in tables[key].get("rows") or [] for c in row if str(c).strip()]
    at = 0
    for text in expected:
        piece = re.sub(r"\s+", "", text)
        found = drawn.find(piece, at)
        assert found >= 0, f"문서에 없거나 순서가 다름: {text[:40]}"
        at = found + len(piece)
