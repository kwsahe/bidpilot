"""37차 §3-I-3 — 사업계획서 Word 표 세 가지(recheck29 EXP-01 · 02 · 03).

- EXP-01 표 칸 안 「(담당자 입력)」은 보통 빈칸 — 좁은 칸에서 어절 단위로 꺾인다(글자 단위로 꺾이지 않는다).
- EXP-02 4칸 현황 표(일반 현황 · 기업 현황)는 마지막 줄 빼고 keep_with_next — 제목과 첫 줄만 쪽 끝에 남지 않는다.
- EXP-03 9개월 이상 월별 표는 머리 「n월」 · 첫 칸을 한 달에 3mm씩 줄인다(최소 35mm).
"""

from __future__ import annotations

import io

from docx import Document

from app.services import plan_export_service as pe
from app.services.plan_form_service import HUMAN_INPUT
from tests.test_plan_export import material  # noqa: F401 — pytest 픽스처

NBSP = " "


def _tables(material, variant: str):  # noqa: F811
    draft, form = material
    return Document(io.BytesIO(pe.build_docx(draft, form, title="사업계획서 초안", variant=variant))).tables


def test_EXP01_표_칸_안_빈칸은_보통_빈칸이다(material) -> None:  # noqa: F811
    for variant in ("submit", "review"):
        cells = [c.text for t in _tables(material, variant) if t.rows[0].cells[0].text in ("연번", "기업명", "비목") for r in t.rows for c in r.cells]
        assert any(HUMAN_INPUT in text for text in cells)
        assert not any(NBSP in text for text in cells)


def test_EXP02_4칸_현황_표는_마지막_줄_빼고_다음_줄과_붙는다(material) -> None:  # noqa: F811
    fields = [t for t in _tables(material, "submit") if len(t.columns) == 4 and t.rows[0].cells[0].text in ("과제명", "기업명")]
    assert len(fields) == 2
    for table in fields:
        keep = [all(p.paragraph_format.keep_with_next for c in r.cells for p in c.paragraphs) for r in table.rows]
        assert len(table.rows) <= pe.FIELDS_WHOLE_ROWS
        assert keep == [True] * (len(table.rows) - 1) + [False]


def test_EXP03_9개월_이상이면_머리를_줄이고_첫_칸을_줄인다() -> None:
    table = {"rows": [["요구 분석", "1~2개월차", ""], ["개발", "3~12개월차", ""]]}
    # 시작 연월을 모르면 개월차 숫자 — 「1월」이 1개월차인데 1월로 읽혔다(2.8.0 B6 · 계약일을 모르는 공고)
    grid = pe.schedule_grid(table, 12)
    assert grid and grid["columns"][1:] == [str(m) for m in range(1, 13)] and grid["title"] == "추진 일정(개월차 · 협약 기간 12개월)"
    widths = pe.column_mm(grid["columns"])
    assert widths[0] == 38.0 and abs(sum(widths) - 166.0) < 1e-6  # 50 - 3 × (12 - 8)
    # 실제 시작 연월을 알면 달 이름(해를 넘기면 다시 1월부터)
    dated = pe.schedule_grid(table, 12, (2026, 11))
    assert dated and dated["columns"][1:4] == ["11월", "12월", "1월"] and dated["title"] == "추진 일정(월별 · 협약 기간 12개월)"
    assert pe.column_mm(dated["columns"]) == widths
    assert pe.cell_align("12월", "") == "c"
    long = pe.schedule_grid({"rows": [["개발", "1~20개월차", ""]]}, 20)
    assert long and pe.column_mm(long["columns"])[0] == pe.GRID_FIRST_MIN_MM


def test_EXP03_8개월까지는_그대로_n월차_50mm() -> None:
    grid = pe.schedule_grid({"rows": [["개발", "1~8개월차", ""]]}, 8)
    assert grid and grid["columns"][1:] == [f"{m}월차" for m in range(1, 9)]
    assert pe.column_mm(grid["columns"])[0] == pe.GRID_FIRST_MM
