from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUTPUT = Path(r"C:\sampleedu-bidpilot-ai\data\public\sample_rfp\synthetic_ai_training_rfp.docx")

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
LIGHT_GRAY = "F2F4F7"
PALE_BLUE = "E8EEF5"
MID_GRAY = "6B7280"
BLACK = "111827"


def set_run_font(run, size=11, bold=False, color=BLACK, italic=False):
    run.font.name = "Calibri"
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Calibri")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Calibri")
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = RGBColor.from_string(color)


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_table_borders(table, color="D1D5DB", size="6"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), size)
        tag.set(qn("w:color"), color)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths):
    total = sum(widths)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(total))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), "120")
    tbl_ind.set(qn("w:type"), "dxa")

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        grid_col = OxmlElement("w:gridCol")
        grid_col.set(qn("w:w"), str(width))
        grid.append(grid_col)

    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths[idx]))
            tc_w.set(qn("w:type"), "dxa")
            cell.width = Inches(widths[idx] / 1440)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_margins(cell)


def style_cell_text(cell, bold=False, color=BLACK, size=9.5, align=WD_ALIGN_PARAGRAPH.LEFT):
    for paragraph in cell.paragraphs:
        paragraph.alignment = align
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.05
        for run in paragraph.runs:
            set_run_font(run, size=size, bold=bold, color=color)


def add_table(doc, rows, widths, header=True):
    table = doc.add_table(rows=len(rows), cols=len(widths))
    set_table_geometry(table, widths)
    set_table_borders(table)
    for row_idx, row_data in enumerate(rows):
        for col_idx, value in enumerate(row_data):
            cell = table.cell(row_idx, col_idx)
            cell.text = str(value)
            if header and row_idx == 0:
                set_cell_shading(cell, PALE_BLUE)
                style_cell_text(cell, bold=True, color=DARK_BLUE, align=WD_ALIGN_PARAGRAPH.CENTER)
            else:
                style_cell_text(cell, align=WD_ALIGN_PARAGRAPH.CENTER if col_idx == 0 else WD_ALIGN_PARAGRAPH.LEFT)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_clause(doc, label, text, category=None):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.line_spacing = 1.10
    run = paragraph.add_run(label + "  ")
    set_run_font(run, size=11, bold=True, color=DARK_BLUE)
    if category:
        cat = paragraph.add_run(f"[{category}] ")
        set_run_font(cat, size=9.5, bold=True, color=MID_GRAY)
    body = paragraph.add_run(text)
    set_run_font(body, size=11)
    return paragraph


def add_note(doc, title, text):
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [9360])
    set_table_borders(table, color="B8C7D9")
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F4F6F9")
    cell.text = ""
    p = cell.paragraphs[0]
    title_run = p.add_run(title + "  ")
    set_run_font(title_run, size=10, bold=True, color=DARK_BLUE)
    text_run = p.add_run(text)
    set_run_font(text_run, size=10, color="374151")
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.05
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_page_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, text, end])
    set_run_font(run, size=9, color=MID_GRAY)


def add_page_break(doc):
    doc.add_page_break()


def configure_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    normal.font.size = Pt(11)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    for name, size, color, before, after in (
        ("Heading 1", 16, BLUE, 16, 8),
        ("Heading 2", 13, BLUE, 12, 6),
        ("Heading 3", 12, DARK_BLUE, 8, 4),
    ):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True


def add_running_header_footer(section):
    for header in (section.header, section.even_page_header):
        header.is_linked_to_previous = False
        hp = header.paragraphs[0]
        hp.text = ""

    for footer in (section.footer, section.even_page_footer):
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fp.text = ""
        run = fp.add_run("Page ")
        set_run_font(run, size=9, color=MID_GRAY)
        add_page_field(fp)


def add_page_title(doc, kicker, title, subtitle=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(kicker.upper())
    set_run_font(run, size=9.5, bold=True, color=BLUE)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(title)
    set_run_font(run, size=24, bold=True, color=BLACK)
    if subtitle:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(18)
        run = p.add_run(subtitle)
        set_run_font(run, size=12.5, color="4B5563")


def build_document():
    doc = Document()
    doc.settings.odd_and_even_pages_header_footer = True
    configure_styles(doc)
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    add_running_header_footer(section)

    # Page 1: cover and procurement metadata
    add_page_title(
        doc,
        "합성 테스트 문서",
        "2026 생성형 AI 실무역량 강화 교육 운영 용역",
        "BidPilot AI RFP Parsing · Evidence Mapping · Auditor 통합 테스트용",
    )
    add_note(
        doc,
        "중요",
        "이 문서는 실제 발주기관의 공고가 아닌 합성 RFP입니다. 실제 회사정보, 개인정보, 실적 또는 자격정보를 포함하지 않습니다.",
    )
    doc.add_heading("공고 기본정보", level=1)
    add_table(
        doc,
        [
            ("항목", "내용"),
            ("공고번호", "SYN-2026-0915-01"),
            ("발주기관", "광주미래학습진흥원(가상기관)"),
            ("사업명", "2026 생성형 AI 실무역량 강화 교육 운영 용역"),
            ("사업기간", "2026. 10. 1. ~ 2026. 12. 15."),
            ("기초금액", "금 60,000,000원(부가가치세 포함)"),
            ("계약방법", "제한경쟁 · 협상에 의한 계약(테스트 조건)"),
            ("제안서 제출기한", "2026. 9. 25. 18:00"),
        ],
        [2700, 6660],
    )
    add_note(doc, "테스트 목적", "페이지 근거 보존, 수치 추출, 모호 자격조건 CHECK 처리, 요구사항 누락과 숫자 불일치 탐지를 검증합니다.")

    # Page 2: overview and scope
    add_page_break(doc)
    add_page_title(doc, "과업지시서", "사업 개요와 수행 범위")
    doc.add_heading("사업 목적", level=1)
    p = doc.add_paragraph("공공·교육기관 종사자가 생성형 AI를 안전하고 실무적으로 활용하도록 직무별 실습교육을 제공하고, 교육 결과를 정량·정성 지표로 정리하는 것을 목적으로 한다.")
    p.paragraph_format.space_after = Pt(10)
    doc.add_heading("필수 수행조건", level=1)
    add_clause(doc, "수행기간", "계약상대자는 2026년 10월 1일부터 2026년 12월 15일까지 모든 과업을 완료해야 한다.", "일정")
    add_clause(doc, "교육횟수", "교육은 총 12회 운영해야 하며, 회차당 교육시간은 최소 3시간으로 한다.", "수치")
    add_clause(doc, "교육인원", "전체 교육대상은 누적 240명 이상으로 계획하며, 회차별 명단과 실제 참석인원을 구분해 관리해야 한다.", "수치")
    add_clause(doc, "운영방식", "총 12회 중 10회는 광주광역시 내 지정 교육장에서 대면으로 운영하고, 2회는 실시간 온라인 방식으로 운영해야 한다.", "운영")
    doc.add_heading("주요 수행범위", level=2)
    add_table(
        doc,
        [
            ("구분", "주요 내용", "필수 산출물"),
            ("기획", "수요분석, 수준진단, 과정 설계", "착수계획서"),
            ("운영", "강사·보조인력 배치, 출결·현장관리", "회차별 운영기록"),
            ("평가", "만족도 조사, 개선의견 분석", "결과 데이터"),
            ("보고", "주간 진척 공유, 성과 종합", "최종결과보고서"),
        ],
        [1500, 4860, 3000],
    )

    # Page 3: curriculum and data safety
    add_page_break(doc)
    add_page_title(doc, "과업지시서", "교육과정과 실습 운영 기준")
    doc.add_heading("교육과정 필수 구성", level=1)
    add_clause(doc, "과정내용", "교육과정에는 생성형 AI와 LLM의 기본 이해, 프롬프트 작성, 데이터·보안 유의사항, 문서작성 및 업무자동화 실습을 모두 포함해야 한다.", "필수내용")
    add_clause(doc, "사전승인", "계약상대자는 첫 교육일 10일 전까지 세부 커리큘럼, 교안, 실습파일을 제출해 발주기관의 승인을 받아야 한다.", "제출")
    add_clause(doc, "실습데이터", "모든 실습은 가상 또는 비식별 데이터로 진행해야 하며, 교육생이 개인정보와 기관 비공개자료를 외부 생성형 AI 서비스에 입력하지 않도록 안내해야 한다.", "보안")
    add_clause(doc, "보조인력", "회차별 참석 예정 인원이 25명 이상인 경우 주강사 외에 실습 보조인력 2명 이상을 배치해야 한다.", "인력")
    doc.add_heading("회차별 운영 흐름", level=1)
    add_table(
        doc,
        [
            ("단계", "권장 시간", "필수 활동"),
            ("도입", "20분", "사전 수준 확인과 보안 안내"),
            ("개념", "40분", "생성형 AI·LLM 핵심 개념"),
            ("실습", "100분", "직무별 프롬프트와 업무자동화"),
            ("정리", "20분", "결과 공유, 질의응답, 만족도 조사"),
        ],
        [1500, 1800, 6060],
    )
    add_note(doc, "AI 사용 원칙", "생성 결과를 사실로 단정하지 말고 출처 확인, 개인정보 보호, 사람의 최종 검토 절차를 교육내용에 포함합니다.")

    # Page 4: eligibility and personnel
    add_page_break(doc)
    add_page_title(doc, "제안요청서", "입찰 참가자격과 투입인력")
    doc.add_heading("입찰 참가자격", level=1)
    add_clause(doc, "기본자격", "입찰참가자는 사업자등록을 완료하고 공공계약 관련 법령상 입찰참가 제한을 받지 않는 사업자여야 한다.", "자격")
    add_clause(doc, "공동수급", "공동수급은 허용하지 않으며, 핵심 교육과업의 재위탁은 발주기관의 사전 서면승인 없이 할 수 없다.", "자격")
    doc.add_heading("핵심 투입인력", level=1)
    add_clause(doc, "총괄책임자", "총괄책임자는 관련 분야 경력 3년 이상이며 최근 3년 이내 공공기관 또는 교육기관의 AI 교육 유사사업 3건 이상 수행 경험을 보유해야 한다.", "모호조건")
    add_clause(doc, "전담관리자", "계약상대자는 일정·교육생·산출물을 관리하는 전담 프로젝트 관리자 1명을 지정해야 하며, 사업기간 중 발주기관 승인 없이 교체할 수 없다.", "인력")
    add_clause(doc, "증빙원칙", "경력과 수행실적은 계약서, 실적증명서, 재직증명서 등 객관적 증빙으로 확인되어야 하며, 증빙이 불충분한 경우 충족으로 확정하지 않는다.", "Evidence")
    doc.add_heading("자격 판정 원칙", level=2)
    add_table(
        doc,
        [
            ("조건", "판정", "근거 처리"),
            ("명확한 등록·제한 조건", "PASS / FAIL", "제출문서와 원문 대조"),
            ("유사사업 범위가 모호함", "CHECK", "계약서·실적증명서 사람 검토"),
            ("증빙 없음", "CHECK 또는 FAIL", "근거 없는 충족 판정 금지"),
        ],
        [2700, 1800, 4860],
    )

    # Page 5: operations and deliverables
    add_page_break(doc)
    add_page_title(doc, "과업지시서", "운영관리와 산출물")
    doc.add_heading("운영관리 필수사항", level=1)
    add_clause(doc, "출결관리", "계약상대자는 매 회차 교육생 서명부 또는 전자출결 기록을 작성하고, 결석·중도이탈 인원을 별도로 표시해야 한다.", "운영")
    add_clause(doc, "만족도조사", "계약상대자는 매 회차 종료 직후 만족도 조사를 실시하고, 전체 참석자 대비 응답률 80% 이상을 확보해야 한다.", "Auditor핵심")
    add_clause(doc, "주간보고", "교육이 진행되는 주에는 매주 금요일 17시까지 진행현황, 이슈, 다음 주 계획을 포함한 주간보고를 제출해야 한다.", "보고")
    add_clause(doc, "최종보고", "최종 교육일로부터 7일 이내에 전체 운영실적, 출결, 만족도, 개선의견을 포함한 최종결과보고서를 제출해야 한다.", "보고")
    doc.add_heading("필수 산출물 목록", level=1)
    add_table(
        doc,
        [
            ("산출물", "제출시점", "형식"),
            ("착수계획서", "계약 후 7일 이내", "PDF"),
            ("세부 커리큘럼·교안·실습파일", "첫 교육 10일 전", "원본 + PDF"),
            ("회차별 운영기록·출결·만족도", "각 회차 후 3일 이내", "XLSX/CSV + PDF"),
            ("주간보고", "매주 금요일 17시", "PDF"),
            ("최종결과보고서", "최종 교육 후 7일 이내", "원본 + PDF"),
        ],
        [3600, 3000, 2760],
    )
    add_clause(doc, "파일형식", "계약상대자는 편집 가능한 원본파일과 PDF 파일을 함께 제출하고, 파일명에 산출물명과 제출일자를 표시해야 한다.", "제출")

    # Page 6: security, proposal submission, auditor fixtures
    add_page_break(doc)
    add_page_title(doc, "제안요청서", "보안·제출·검수 기준")
    doc.add_heading("정보보호와 데이터 폐기", level=1)
    add_clause(doc, "데이터폐기", "계약상대자는 사업 종료 후 30일 이내에 교육생 명단, 연락처, 출결 원본 등 개인정보를 파기하고 파기확인서를 제출해야 한다.", "보안")
    add_clause(doc, "외부서비스", "외부 AI 또는 클라우드 서비스를 사용할 경우 개인정보와 기관 비공개자료를 전송해서는 안 되며, 사용 서비스와 데이터 처리방식을 사전에 설명해야 한다.", "보안")
    doc.add_heading("제안서 필수 포함자료", level=1)
    add_clause(doc, "제출서류", "제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명, 보안·개인정보 보호계획, 가격제안서를 모두 포함해야 한다.", "제출")
    doc.add_heading("검수와 최종 승인", level=1)
    add_clause(doc, "검수기준", "필수 요구사항의 반영 여부는 본 문서의 원문과 제출 산출물을 대조해 확인하며, 누락·수치 불일치·근거 없는 주장은 보완대상으로 처리한다.", "Auditor")
    add_clause(doc, "최종승인", "AI 분석결과는 참고자료이며, 자격판정, Evidence 채택, 제안서 확정 및 제출 여부는 담당자가 최종 승인해야 한다.", "Human Review")
    add_note(
        doc,
        "의도된 Auditor 테스트",
        "테스트 제안서에서 ‘매 회차 만족도 조사’를 누락하거나 교육횟수를 10회로 변경하거나 근거 없이 ‘만족도 95% 보장’을 주장했을 때 각각 누락·숫자 불일치·근거 부재로 탐지해야 합니다.",
    )
    doc.add_heading("문서 통제", level=2)
    add_table(
        doc,
        [
            ("버전", "작성일", "용도", "공개여부"),
            ("v1.0", "2026. 9. 2.", "BidPilot AI 로컬 통합 테스트", "합성 데이터 공개 가능"),
        ],
        [1200, 1800, 3900, 2460],
    )

    doc.core_properties.title = "2026 생성형 AI 실무역량 강화 교육 운영 용역 - 합성 테스트 RFP"
    doc.core_properties.subject = "BidPilot AI local test fixture"
    doc.core_properties.author = "BidPilot AI"
    doc.core_properties.keywords = "synthetic,RFP,AI education,requirement matrix,auditor"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build_document()
