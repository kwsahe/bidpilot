"""사업계획서 초안 내려받기 — 표 다섯이 양식 자리에 · AI 제안은 회색 · 안내 상자 없음 · 한글 파일명 (25차 · prompt_15 §4-E).

28차: 사업계획서 HWPX 는 담당자 결정으로 없앴다 — DOCX 만 · `?format=hwpx` 는 422.

입력 양식은 126482 원문 발췌(`test_plan_form.FULL`)이고 초안은 AI 없이 만든 규칙 초안(양식 뼈대)이다.
AI 제안 문장 하나를 손으로 넣어 회색 글자 모양을 잰다. `data/private` 는 읽지 않는다.
"""

from __future__ import annotations

import io
import re
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from app.services import plan_draft_service, plan_export_service, plan_form_service, support_requirement_extractor
from tests.test_plan_form import FULL

AI_TEXT = "우리 회사는 학교 에너지 데이터를 모아 이상 사용을 알리는 모델을 만듭니다."


@pytest.fixture()
def material() -> tuple[dict, dict]:
    form = plan_form_service.extract_form("bizinfo-PBLN_000000000126482", FULL)
    form["selected_task"] = next(t for t in form["tasks"] if t["no"] == 3)
    draft = plan_draft_service.generate(
        program=SimpleNamespace(id="PBLN_000000000126482"), form=form,
        requirements=support_requirement_extractor.extract_from_text("PBLN_000000000126482", FULL),
        company={"profile": {"business_domains": ["AI SaaS·소프트웨어 개발"]}, "capacity": {}, "ledger": []},
        facts=[], matches=[], notice_text=FULL, annex=None, company_name="주식회사 시험",
    )
    solve = next(s for s in draft["sections"] if s["section"] == "과제 해결방안")
    solve["sentences"].append({"text": AI_TEXT, "type": plan_draft_service.SUGGESTION, "source": None, "source_ids": [], "ai": True, "flags": []})
    return draft, form


def _docx_sequence(payload: bytes) -> list[tuple[str, str]]:
    from docx import Document

    document = Document(io.BytesIO(payload))
    out: list[tuple[str, str]] = []
    tables = iter(document.tables)
    paragraphs = iter(document.paragraphs)
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            table = next(tables)
            header = child.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblHeader") is not None
            out.append(("TABLE" if header else "BOX", table.rows[0].cells[0].text))
        elif tag == "p":
            paragraph = next(paragraphs)
            color = paragraph.runs[0].font.color.rgb if paragraph.runs and paragraph.runs[0].font.color and paragraph.runs[0].font.color.type else None
            out.append((f"p:{color}", paragraph.text))
    return out


def _at(texts: list[str], title: str) -> int:
    """본문 제목의 자리 — 「1. 일반 현황」 · 「2-3. 기업(팀) 역량」(29차 번호). 목차에도 같은 줄이 있어 마지막 것을 쓴다."""
    pattern = re.compile(rf"^\d+(?:-\d+)?\. {re.escape(title)}$")
    return max(i for i, text in enumerate(texts) if pattern.match(text))


def _between(sequence: list[tuple[str, str]], start: str, end: str | None) -> list[tuple[str, str]]:
    texts = [text for _, text in sequence]
    a = _at(texts, start)
    b = _at(texts, end) if end else len(texts)
    return sequence[a:b]


def _assert_positions(sequence: list[tuple[str, str]]) -> None:
    memo = next((i for i, (_, text) in enumerate(sequence) if text.startswith("검토 메모")), len(sequence))
    sequence = sequence[:memo]  # 검토 메모의 「담당자가 채울 항목」 표는 본문 표가 아니다(36차 §3-F)
    tables = [(kind, first) for kind, first in sequence if kind == "TABLE"]
    assert len(tables) == 5
    # 표 머리 첫 칸으로 표를 알아본다 — 인력 구성은 「연번」, 수상 이력은 「대회명」, 추진일정은 「추진 내용」, 사업비는 「비목」, 성과는 「구분」.
    def has(block, first):
        return any(kind == "TABLE" and text == first for kind, text in block)

    assert has(_between(sequence, "일반 현황", "과제 해결 방안"), "연번")
    assert has(_between(sequence, "기업(팀) 역량", "추진 계획"), "대회명")
    assert has(_between(sequence, "추진 계획", "집행 계획"), "추진 내용")
    assert has(_between(sequence, "집행 계획", "기업 현황"), "비목")
    assert has(_between(sequence, "기업 현황", None), "구분")
    text = " ".join(t for _, t in sequence)
    assert "표는 삭제 후 제출" not in text and "참고 사업비 집행 비목" not in text
    assert "공고 요구:" not in text and "겨냥하는 평가 항목" not in text


def test_DOCX_표_다섯이_양식_자리에_AI_제안은_회색(material) -> None:
    draft, form = material
    sequence = _docx_sequence(plan_export_service.build_docx(draft, form, title="사업계획서 초안", variant="review"))
    _assert_positions(sequence)
    ai = [kind for kind, text in sequence if text.endswith(AI_TEXT)]
    assert ai == [f"p:{plan_export_service.AI_INK}"]  # 검토용 — AI 덧붙임은 회색 글자(+ 왼쪽 세로줄 · 36차 §3-F)
    # 제출용 — 같은 자리 · 표식 없음 · 회색 아님
    submit = _docx_sequence(plan_export_service.build_docx(draft, form, title="사업계획서 초안", variant="submit"))
    _assert_positions(submit)
    assert [kind for kind, text in submit if text == AI_TEXT] == ["p:None"]
    # 30차 §3-B — 목차 · 제목에 「(선택)」 없음. 내용이 빈칸뿐인 선택 절은 제출용에서 빼지만,
    # 「이미지」 절은 담당자 결정(10-13 · SPEC §21-3)으로 두 판 모두 제목과 사진 칸(높이 50mm)을 남겨 번호를 잇는다
    assert not any("(선택)" in text for _, text in sequence + submit)
    for seq in (sequence, submit):
        at = max(i for i, (_, text) in enumerate(seq) if re.match(r"^\d+-\d+\. 이미지", text))  # 검토용은 목차에도 같은 줄
        assert seq[at + 1] == ("BOX", plan_form_service.HUMAN_INPUT.replace(" ", " "))  # 빈칸 안 빈칸은 줄바꿈 안 되는 빈칸
    # 첫머리 안내에 한컴 · Beta 말이 없다(HWPX 를 없앴다 · 28차)
    assert "한컴" not in plan_export_service.BETA_NOTE and "Beta" not in plan_export_service.BETA_NOTE


def test_파일_이름에서_못_쓰는_글자를_뺀다() -> None:
    from datetime import datetime

    name = plan_export_service.export_file_name('민관협력/오픈:이노베이션*"지원"<공공>|데이터 활용 지원 사업', "docx", now=datetime(2026, 10, 1))
    assert name.startswith("사업계획서_초안_") and name.endswith("_20261001.docx")
    assert not re.search(r'[\\/:*?"<>|]', name)


def test_내려받기_응답은_한글_파일명_헤더(monkeypatch: pytest.MonkeyPatch, material) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import support_application_service, support_plan_service

    draft, form = material

    async def _find(*_a, **_kw):
        return SimpleNamespace(id="PBLN_000000000126482", title="민관협력 오픈이노베이션 지원 공공데이터 활용"), None, "sample"

    monkeypatch.setattr(support_plan_service, "load", lambda **_kw: draft)
    monkeypatch.setattr(plan_form_service, "form_for", lambda *_a, **_kw: form)
    monkeypatch.setattr(support_application_service, "find_program", _find)
    client = TestClient(app)
    for query in ("?format=docx&organization_id=org-sample", "?organization_id=org-sample"):  # 기본값도 docx
        response = client.get(f"/api/support-programs/bizinfo-PBLN_000000000126482/plan-draft/export{query}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment; filename*=UTF-8''")
        name = unquote(disposition.split("''", 1)[1])
        assert name.startswith("사업계획서_제출용_민관협력 오픈이노베이션 지원 공") and name.endswith(".docx")  # 기본은 제출용(29차 §3-D)


def test_HWPX_요청은_422() -> None:
    """사업계획서 HWPX 는 없앴다(28차 담당자 결정) — 옛 주소 `?format=hwpx` 는 받지 않는다."""
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/api/support-programs/bizinfo-P/plan-draft/export?format=hwpx&organization_id=org-sample")
    assert response.status_code == 422


def test_초안이_없으면_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import support_plan_service

    monkeypatch.setattr(support_plan_service, "load", lambda **_kw: {})
    response = TestClient(app).get("/api/support-programs/bizinfo-P/plan-draft/export?format=docx&organization_id=org-sample")
    assert response.status_code == 404


def _docx(payload: bytes):
    from docx import Document

    return Document(io.BytesIO(payload))


def test_디자인_표지_표_머리색_점선_빈칸_바닥글_목차_머리말_없음(material) -> None:
    """29차 §3-D · 36차 §3-F(SPEC) — 표지(공고명 · 과제명 · 기업명 · 제출일) · 제목 번호 · 표 머리 옅은 색 · 「(담당자 입력)」 갈색 점선 밑줄 ·
    바닥글 「- n -」. 제출용에는 목차 · 머리말이 없다(담당자 결정 10-13). 본문 11pt · 줄 18pt 고정."""
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt

    draft, form = material
    meta = plan_export_service.export_meta(draft, form, notice="민관협력 오픈이노베이션 지원", company="주식회사 시험")
    doc = _docx(plan_export_service.build_docx(draft, form, title="민관협력 오픈이노베이션 지원", variant="submit", meta=meta))
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    assert texts[0] == "사업계획서" and texts[1] == "민관협력 오픈이노베이션 지원"
    cover = [[cell.text for cell in row.cells] for row in doc.tables[0].rows]  # 과제명 · 기업명 · 제출일은 테두리 없는 2칸 표
    assert cover[0][0] == "과제명" and "학교 에너지" in cover[0][1] and cover[1] == ["기업명", "주식회사 시험"] and cover[2][0] == "제출일"
    assert "목차" not in texts and texts[2] == "1. 일반 현황"
    first = next(p for p in doc.paragraphs if p.text == "1. 일반 현황")
    assert first.style.name == "Heading 1" and first.paragraph_format.page_break_before  # 표지 다음 쪽 — 빈 문단으로 띄우지 않는다
    xml = doc.element.xml
    assert 'w:fill="E8EEF5"' in xml and 'w:fill="FFF3B0"' not in xml  # 표 머리 · 제출용 빈칸은 바탕 없이
    assert 'w:u w:val="dotted" w:color="B8860B"' in xml and 'w:val="8A6100"' in xml
    assert "[AI 덧붙임]" not in "\n".join(texts) and "검토 메모" not in "\n".join(texts)  # 제출용은 표식 · 메모 없음
    section = doc.sections[0]
    assert section.header.is_linked_to_previous  # 머리말 없음(공식 양식에도 없다)
    assert "PAGE" in section.footer._element.xml and "NUMPAGES" not in section.footer._element.xml
    normal = doc.styles["Normal"]
    assert normal.font.name == "맑은 고딕" and normal.paragraph_format.line_spacing == Pt(18)
    assert normal.paragraph_format.line_spacing_rule == WD_LINE_SPACING.EXACTLY


def test_검토용은_표식_근거_검토_메모가_있다(material) -> None:
    draft, form = material
    draft = {**draft, "review_scores": [{"eval_item": "협업 과제 이해도", "grade": "하", "reason": "요구 분석이 얕다", "sections": ["과제 해결방안"],
                                         "fixes": [{"section": "과제 해결방안", "sentence": "모델을 만듭니다", "fix": "데이터를 밝힌다"}], "rewritten": False}]}
    doc = _docx(plan_export_service.build_docx(draft, form, title="초안", variant="review"))
    text = "\n".join(p.text for p in doc.paragraphs)
    # 36차 §3-F — 문장마다 붙이던 「[AI 덧붙임]」 글자 대신 왼쪽 세로줄 + 소항목 옆 「AI 덧붙임 n/m문장」 + 범례 상자
    assert "검토용 — 제출하지 마세요" in text and "[AI 덧붙임]" not in text and re.search(r"AI 덧붙임 \d+/\d+문장", text)
    legend = doc.tables[1].rows[0].cells[0].text
    assert "AI가 덧붙인 문장" in legend and "[공고] [회사]" in legend and "담당자가 채웁니다" in legend
    assert f'w:color="{plan_export_service.AI_BAR}"' in doc.element.xml and "목차" in text
    assert "검토 메모 — 제출용 파일에는 없습니다" in text and "협업 과제 이해도: 하" in text and "담당자가 채울 항목" in text
    assert doc.sections[0].header.paragraphs[0].text.startswith("검토용 · 제출 금지\t초안")


def test_추진일정_개월차를_월별_칸으로() -> None:
    table = {"title": "사업 추진일정", "columns": ["추진 내용", "추진 기간", "세부 내용"],
             "rows": [["요구 분석", "1~2개월차", "기관 협의"], ["개발", "M2~M4", "기능 구현"], ["검증", "5개월차", "현장 시험"], ["(담당자 입력)", "(담당자 입력)", ""]]}
    grid = plan_export_service.schedule_grid(table, 5)
    assert grid and grid["columns"] == ["추진 내용", "1월차", "2월차", "3월차", "4월차", "5월차"]
    assert grid["rows"][0] == ["요구 분석", "■", "■", "", "", ""] and grid["rows"][1][2:5] == ["■", "■", "■"] and grid["rows"][2][5] == "■"
    assert plan_export_service.schedule_grid({"rows": [["개발", "2026.11~12", ""]]}, 5) is None  # 개월차로 읽을 수 없으면 만들지 않는다


def test_추진일정_기간_칸의_여러_구간을_모두_칠한다() -> None:
    """심사 11-06 — 「1개월차 / 6~7개월차 / 12개월차」가 6 · 7월만 칠해졌다(첫 구간 하나)."""
    table = {"rows": [["주요 보고(착수·중간·결과)", "1개월차 / 6~7개월차 / 12개월차", ""], ["점검", "M2, M4 · 9개월차", ""]]}
    grid = plan_export_service.schedule_grid(table, 12)
    assert grid
    painted = [[m for m, cell in enumerate(row[1:], start=1) if cell == "■"] for row in grid["rows"]]
    assert painted == [[1, 6, 7, 12], [2, 4, 9]]


def test_짧은_사업은_주차_칸_간트_머리_W1부터() -> None:
    """2.10.0 D1 — 13주 미만 사업(weeks)은 추진 기간 「W1~W3」 꼴을 주차 칸으로 칠한다(11-13 동국대 — 개월차만 읽어 간트가 통째로 빠졌다)."""
    assert plan_export_service.period_weeks("W1~W3 / W5") == {1, 2, 3, 5}
    assert plan_export_service.period_weeks("W6(정산 12. 29. · 제출 12. 31.)") == {6}
    assert plan_export_service.period_weeks("1~2개월차") == set() and plan_export_service.period_weeks("AWS 3") == set()
    table = {"rows": [["모집", "W1~W2", ""], ["보고", "W6", ""], ["(담당자 입력)", "W1", ""]]}
    grid = plan_export_service.schedule_grid(table, None, weeks=6)
    assert grid and grid["columns"] == ["추진 내용", "W1", "W2", "W3", "W4", "W5", "W6"]
    assert grid["title"] == "추진 일정(주차별 · 사업기간 6주)" and grid["rows"] == [["모집", "■", "■", "", "", "", ""], ["보고", "", "", "", "", "", "■"]]
    # 주차 사업이어도 주차로 읽히는 줄이 없으면 개월차 간트(지금 그대로) · 주차가 없는 사업은 「W」 꼴을 읽지 않는다
    assert plan_export_service.schedule_grid({"rows": [["운영", "1~2개월차", ""]]}, None, weeks=6)["columns"][1] == "1월차"
    assert plan_export_service.schedule_grid({"rows": [["운영", "W1~W2", ""]]}, 12) is None
    columns = ["추진 내용", *(f"W{w}" for w in range(1, 7))]
    assert plan_export_service.column_mm(columns)[0] == 50.0
    assert plan_export_service.cell_align("W1", "") == "c"


def test_주차_사업은_착수일_기준_주차_표를_일정표_앞에() -> None:
    """2.10.0 D1 — 「주차 · 기간(착수일 D 기준)」 표는 앱이 계산한다(AI 아님 · 계약 예정일 참고 날짜 칸 없음) · 마지막 주는 고정 끝날까지."""
    period = {"text": "계약체결일 ~ 2026. 12. 31.", "end": "2026-12", "open_start": True, "contract_from": "2026-11-18", "days": 44, "weeks": 6}
    table = plan_export_service.week_table(period)
    assert table and table["title"] == "착수일 기준 주차" and table["columns"] == ["주차", "기간(착수일 D 기준)"]
    assert table["rows"][0] == ["W1", "D ~ D+6"] and table["rows"][1] == ["W2", "D+7 ~ D+13"]
    assert table["rows"][-1] == ["W6", "D+35 ~ 2026. 12. 31."] and len(table["rows"]) == 6
    assert plan_export_service.week_table({**period, "weeks": None}) is None and plan_export_service.week_table({}) is None
    draft = {"numbered_titles": True, "tables": [{"key": "schedule", "title": "세부 추진 일정", "columns": ["추진 과업", "추진 기간", "담당(역할)", "주요 활동", "산출물"],
                                                  "rows": [["모집", "W1~W2", "PM / 운영", "모집", ""], ["보고", "W6", "PM", "제출", "최종결과보고서"]]}],
             "sections": [{"key": "M1", "kind": "item", "section": "1. 추진 일정", "major_title": "Ⅰ. 사업 관리", "tables": ["schedule"],
                           "sentences": [{"text": "- 당사는 주차별로 운영합니다.", "type": "AI_SUGGESTION"}]}]}
    blocks = plan_export_service.document_blocks(draft, {"agreement_period": period}, variant="submit", meta={"rows": []})
    keys = [b[1].get("key") for b in blocks if b[0] == "table"]
    assert keys == ["schedule_weeks", "schedule", "schedule_grid"]
    plain = plan_export_service.document_blocks(draft, {"agreement_period": {**period, "weeks": None}}, variant="submit", meta={"rows": []})
    assert "schedule_weeks" not in [b[1].get("key") for b in plain if b[0] == "table"]
    # 주차 사업인데 일정표가 개월차(간트도 월별)면 주차 표를 붙이지 않는다 — 한 문서에 단위가 둘(T2 검토 · 게이트가 SCHEDULE_GRID 로 알림)
    draft["tables"][0]["rows"] = [["모집", "1~2개월차", "PM / 운영", "모집", ""]]
    monthly = plan_export_service.document_blocks(draft, {"agreement_period": period}, variant="submit", meta={"rows": []})
    assert [b[1].get("key") for b in monthly if b[0] == "table"] == ["schedule", "schedule_grid"]


def test_HTML_은_같은_블록_쪽_머리_바닥_노란_빈칸(material) -> None:
    draft, form = material
    page = plan_export_service.build_html(draft, form, title="민관협력 지원", variant="submit")
    assert '"- " counter(page) " -"' in page and '<span class="blank">(담당자 입력)</span>' in page
    # 36차 §3-F — 제출용은 머리말 · 목차 · 요약 상자 없음 · 본문 양쪽 정렬(「」 안쪽이 벌어지지 않게 inter-word)
    assert "@top-right" not in page and 'class="toc"' not in page and "1. 일반 현황" in page and "[AI 덧붙임]" not in page
    assert "text-align: justify; text-justify: inter-word;" in page and 'class="review"' not in page
    review = plan_export_service.build_html(draft, form, title="민관협력 지원", variant="review")
    assert '@top-left { content: "검토용 · 제출 금지"' in review and '@top-right { content: "민관협력 지원"' in review
    assert 'class="toc"' in review and 'class="legend' in review and '<body class="review">' in review
    assert "[AI 덧붙임]" not in review and 'class="para ai"' in review and "검토 메모" in review


def test_PDF_는_스레드에서_만들고_못_만들면_503_이유(monkeypatch: pytest.MonkeyPatch, material) -> None:
    """29차 §3-D — PDF 는 Edge/Chrome(없으면 Word). 둘 다 없으면 503 과 이유 · 상태 API 는 파일만 본다."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import plan_pdf_service, support_application_service, support_plan_service
    from app.services.proposal_export import PdfConverterUnavailableError

    draft, form = material

    async def _find(*_a, **_kw):
        return SimpleNamespace(id="PBLN_000000000126482", title="민관협력 오픈이노베이션 지원"), None, "sample"

    monkeypatch.setattr(support_plan_service, "load", lambda **_kw: draft)
    monkeypatch.setattr(plan_form_service, "form_for", lambda *_a, **_kw: form)
    monkeypatch.setattr(support_application_service, "find_program", _find)
    seen: list[str] = []

    def fake_pdf(d, f, *, title, variant, meta):
        seen.append(variant)
        assert meta["notice"] == "민관협력 오픈이노베이션 지원" and meta["date"]
        return b"%PDF-1.7 fake", "browser"

    monkeypatch.setattr(plan_pdf_service, "build_pdf", fake_pdf)
    client = TestClient(app)
    ok = client.get("/api/support-programs/bizinfo-PBLN_000000000126482/plan-draft/export?format=pdf&variant=review&organization_id=org-sample")
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/pdf" and seen == ["review"]
    assert unquote(ok.headers["content-disposition"].split("''", 1)[1]).startswith("사업계획서_검토용_")

    def no_pdf(*_a, **_kw):
        raise PdfConverterUnavailableError(plan_pdf_service.NO_PDF_REASON)

    monkeypatch.setattr(plan_pdf_service, "build_pdf", no_pdf)
    bad = client.get("/api/support-programs/bizinfo-PBLN_000000000126482/plan-draft/export?format=pdf&organization_id=org-sample")
    assert bad.status_code == 503 and bad.json()["detail"] == plan_pdf_service.NO_PDF_REASON
    # 상태 — 브라우저 · Word 가 없으면 이유(프로세스를 띄우지 않는다)
    monkeypatch.setattr(plan_pdf_service, "browser_path", lambda: None)
    monkeypatch.setattr(plan_pdf_service, "word_available", lambda: False)
    assert client.get("/api/plan-drafts/pdf-status").json() == {"available": False, "method": None, "browser": False, "word": False,
                                                              "reason": plan_pdf_service.NO_PDF_REASON}


def test_브라우저_실행기가_먼저_끝나도_파일이_다_써질_때까지_기다린다(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """29차 실측 — Edge 실행기는 PDF 를 쓰기 전에 끝난다. 끝난 뒤에 생기는 파일을 기다린다."""
    import threading

    from app.services import plan_pdf_service

    def fake_run(args, **_kw):
        out = next(a.split("=", 1)[1] for a in args if a.startswith("--print-to-pdf="))
        threading.Timer(0.6, lambda: open(out, "wb").write(b"%PDF" + b"0" * 2000)).start()  # 끝난 뒤에 쓴다
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(plan_pdf_service.subprocess, "run", fake_run)
    assert plan_pdf_service.html_to_pdf("<p>시험</p>", exe=r"C:\fake\msedge.exe").startswith(b"%PDF")


def test_30차_요약_상자는_자르지_않고_검토용_머리말_빈칸은_한_덩어리(material) -> None:
    """C-05 — 제출용 요약 상자 세 줄이 「…」로 잘렸다. 디자인 검토 — 검토용 머리말 · 「(담당자 입력)」 줄바꿈 · 칸 너비 · 같은 값 두 칸."""
    from docx import Document

    draft, form = material
    long = "학교 급식 데이터를 날마다 모아 남는 양과 모자란 양을 미리 알리고, 영양 교사가 다음 주 식단을 고칠 수 있게 돕는 화면을 만들고, 학교마다 다른 급식 인원과 행사 일정도 함께 반영합니다."
    assert len(long) > 90
    # 31차 R30-38 — 같은 문장은 요약 상자에 한 번만이라 두 절에는 서로 다른 긴 문장을 둔다
    other = "급식 관리 화면은 교육청 공공데이터와 학교 행사표를 함께 읽어, 주마다 남는 음식의 양을 그래프로 보여 주고 다음 달 발주량을 미리 계산해 영양 교사에게 알립니다."
    for title, text in (("공공데이터 활용 계획", long), ("과제 해결방안", other)):
        section = next(s for s in draft["sections"] if s["section"] == title)
        section["sentences"].insert(0, {"text": text, "type": plan_draft_service.SUGGESTION, "source": None, "source_ids": [], "ai": True, "flags": []})
    general = next(s for s in draft["sections"] if s.get("kind") == "fields")
    for field in general["fields"]:
        if field["label"] in ("사업장 소재지", "사업장 주소"):
            field["value"] = "광주광역시 북구 1"  # 양식에 두 칸이 있다 — 같은 회사 값이면 한 번만

    submit = plan_export_service.document_blocks(draft, form, variant="submit", meta={})
    # 36차(담당자 결정 10-13 · SPEC §11) — 요약 상자는 검토용에만 있다
    assert not [b for b in submit if b[0] == "summary"]
    review_blocks = plan_export_service.document_blocks(draft, form, variant="review", meta={})
    summaries = [line for b in review_blocks if b[0] == "summary" for line in b[1]]
    assert long in summaries and not any("…" in line for line in summaries)
    assert [b[1] for b in submit if b[0] == "field" and b[2] == "광주광역시 북구 1"] == ["사업장 소재지"]
    # 단추 옆 수는 **실제로 그린 제출용 문서**의 빈칸 수와 같다 — 구현 식을 다시 세지 않는다(36차 마지막 검토 F-1)
    meta = {"notice": "공고", "task": "과제", "company": "회사", "date": "2026. 10. 13."}
    count = plan_export_service.submit_blank_count(draft, form, meta)
    docx = Document(io.BytesIO(plan_export_service.build_docx(draft, form, title="공고", variant="submit", meta=meta)))
    drawn = "".join(t.text or "" for t in docx.element.body.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
    assert count == drawn.replace("\u00a0", " ").count(HUMAN)
    html_body = plan_export_service.build_html(draft, form, title="공고", variant="submit", meta=meta).split("<body", 1)[1]
    assert count == html_body.count(HUMAN)

    page = plan_export_service.build_html(draft, form, title="공고", variant="review")
    assert '@top-left { content: "검토용 · 제출 금지"' in page and '@top-right { content: "공고"' in page
    assert '<table class="data"><colgroup><col style="width:12.0mm">' in page  # 인력 구성 — 연번 12mm(SPEC §9)
    assert plan_export_service.column_mm(["비목", "산출근거", "금액(원)"]) == [30, 104, 32]
    assert [round(w, 1) for w in plan_export_service.column_mm(["연번", "성명", "직위", "담당업무", "보유 역량(경력 및 학력 등)", "구성 상태"])] == [
        12, 22, 20, 30, 60, 22]
    assert [round(w, 1) for w in plan_export_service.column_mm(["추진 내용", "추진 기간", "세부 내용"])] == [46.7, 26, 93.3]
    assert [round(w, 1) for w in plan_export_service.column_mm(["추진 내용", "1월차", "2월차", "3월차", "4월차", "5월차"])] == [50, 23.2, 23.2, 23.2, 23.2, 23.2]
    assert plan_export_service.cell_align("연번", "1") == "c" and plan_export_service.cell_align("금액(원)", "(담당자 입력)") == "r"
    assert plan_export_service.cell_align("세부 내용", "협의") == "" and plan_export_service.cell_align("1월차", "■") == "c"
    document = Document(io.BytesIO(plan_export_service.build_docx(draft, form, title="공고", variant="review")))
    assert document.sections[0].header.paragraphs[0].text.startswith("검토용 · 제출 금지\t")
    runs = [r.text for p in document.paragraphs for r in p.runs]
    assert HUMAN.replace(" ", " ") in runs and HUMAN not in runs  # 「(담당자 입력)」 — 띄어쓰기에서 줄이 바뀌지 않는다


HUMAN = plan_form_service.HUMAN_INPUT


def test_30차_표지_과제명의_제어문자와_PDF_머리글_이스케이프(material) -> None:
    """R29-04 — 표지 · 머리글 · 문서 제목에 제어문자가 있으면 DOCX 500 · R29-09 — PDF 머리글 「R&amp;D」 · 줄바꿈."""
    draft, form = material
    meta = {"notice": "R&D \"공고\"\n둘째 줄 <b>", "task": "과제\x0b이름", "company": "회사\x01", "date": "2026. 10. 1."}
    payload = plan_export_service.build_docx(draft, form, title="제목\x0c", variant="submit", meta=meta)
    assert payload[:2] == b"PK"
    page = plan_export_service.build_html(draft, form, title="제목\x0c", variant="review", meta=meta)  # 머리말은 검토용에만(36차 §3-F)
    assert r'content: "R&D \"공고\" 둘째 줄 \3C b>"' in page and "&amp;" not in page.split("<style>")[1].split("</style>")[0]
    assert "\x0b" not in page and "\x01" not in page


def test_30차_PDF_임시_폴더는_지우고_남은_것은_서버_시작_때(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """R29-11 — Edge 임시 프로필(약 7MB)이 지워지지 않고 %TEMP% 에 쌓였다."""
    import os
    import time as _time

    from app.services import plan_pdf_service

    monkeypatch.setattr(plan_pdf_service.tempfile, "gettempdir", lambda: str(tmp_path))
    old = tmp_path / f"{plan_pdf_service.TEMP_PREFIX}old"
    (old / "profile").mkdir(parents=True)
    fresh = tmp_path / f"{plan_pdf_service.TEMP_PREFIX}fresh"
    fresh.mkdir()
    past = _time.time() - 3600
    os.utime(old, (past, past))
    assert plan_pdf_service.cleanup_leftovers() == 1 and not old.exists() and fresh.exists()
    assert plan_pdf_service._remove_temp(fresh, wait=0) and not fresh.exists()


def test_30차_제출_전_채울_칸은_표지_빈칸도_센다(material) -> None:
    """§4 마지막 검토 — 단추 옆 수가 표지의 과제명 · 기업명 빈칸을 빠뜨려 실제 문서보다 1~2 적었다."""
    draft, form = material
    full = {"notice": "공고", "task": "과제", "company": "회사", "date": "2026. 10. 1."}
    base = plan_export_service.submit_blank_count(draft, form, full)
    assert plan_export_service.submit_blank_count(draft, form, {**full, "company": None}) == base + 1
    assert plan_export_service.submit_blank_count(draft, form, {"notice": "공고"}) == base + 3  # 과제명 · 기업명 · 제출일(36차 F-4)


def test_35차_요약_상자는_소제목_줄을_건너뛰고_글머리를_뗀다(material) -> None:
    """Claude 초안(123852)의 제출용 요약 상자 6줄 중 2줄이 「○ 목표 고객과 시장 현황」 같은 소제목이었다."""
    draft, form = material
    sentence = "○ 1단계 준비: 목표 시장과 고객 요구를 정리하고 수행 체계를 세웁니다."
    other = "급식 관리 화면은 교육청 공공데이터와 학교 행사표를 함께 읽어 주마다 남는 음식의 양을 보여 줍니다."
    for title, texts in (("과제 해결방안", (sentence, "○ 목표 고객과 시장 현황")), ("공공데이터 활용 계획", (other,))):
        section = next(s for s in draft["sections"] if s["section"] == title)
        for text in texts:
            section["sentences"].insert(0, {"text": text, "type": plan_draft_service.SUGGESTION, "source": None, "source_ids": [], "ai": True, "flags": []})
    submit = plan_export_service.document_blocks(draft, form, variant="submit", meta={})
    # 36차(담당자 결정 10-13 · SPEC §11) — 요약 상자는 검토용에만 있다
    assert not [b for b in submit if b[0] == "summary"]
    review_blocks = plan_export_service.document_blocks(draft, form, variant="review", meta={})
    summaries = [line for b in review_blocks if b[0] == "summary" for line in b[1]]
    assert "목표 고객과 시장 현황" not in "".join(summaries)
    assert sentence.removeprefix("○ ") in summaries and not any(line.startswith("○") for line in summaries)


def test_36차_검토용_요약_상자는_앞쪽_세_문장_안에서_가리키는_문장은_빼고_고른다(material) -> None:
    """PLAN-02 — 123852 요약 둘째 줄이 18문장 중 10번째 작성 지시문 「세 시장의 금액은 위 전체 시장과 …」였다."""
    draft, form = material
    late = "학교 급식 데이터를 날마다 모아 남는 양을 미리 알립니다."
    pointing = "세 시장의 금액은 위 전체 시장과 같은 기준 연도로 적습니다."
    first = next(s for s in draft["sections"] if s["section"] == "과제 해결방안")
    second = next(s for s in draft["sections"] if s["section"] == "공공데이터 활용 계획")
    filler = [{"text": f"(담당자 입력) 칸 {i}", "type": plan_draft_service.SUGGESTION, "source": None, "source_ids": [], "ai": True, "flags": []} for i in range(3)]
    first["sentences"][0:0] = [{"text": pointing, "type": plan_draft_service.SUGGESTION, "source": None, "source_ids": [], "ai": True, "flags": []}]
    second["sentences"][0:0] = filler + [{"text": late, "type": plan_draft_service.SUGGESTION, "source": None, "source_ids": [], "ai": True, "flags": []}]
    review = plan_export_service.document_blocks(draft, form, variant="review", meta={})
    summaries = [line for b in review if b[0] == "summary" for line in b[1]]
    assert pointing not in summaries and late not in summaries
