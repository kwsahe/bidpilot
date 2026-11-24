"""실적 원장 변환 테스트 (backend/app/services/performance_ledger.py).

실제 원장은 쓰지 않는다 — 같은 열 구조의 작은 xlsx를 tmp에 만들어 검사한다.
채택 규칙: 「외부 성공연혁 = 가능」 + 상태 완료·확정·등록. 문단은 원장 셀 값만 담는다.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from app.services import company_index_service as cis
from app.services import performance_ledger as pl

HEADER = ["연번", "연도", "기간", "분야", "사업·과제·연혁", "주관·발주·협력기관", "주요 내용·성과", "금액(천원)", "금액 구분", "상태", "외부 성공연혁", "증빙·주의사항"]

ROWS = [
    [1, 2026, "2026.07.01", "대학·교육기관", "국제인증 AI 기초 교육", "A대학교 산학협력단", "AI 기초 자격 교육", 5000, "계산서 명세", "완료", "가능", "계약·계산서·결과자료 대조"],
    [2, 2025, "2025.03~04", "공공·지자체", "AI 에이전트 업무자동화 교육", "B구청", "에이전트 실습", 1900, "계산서 명세", "완료", "가능", "계약·계산서·결과자료 대조"],
    [3, 2025, "", "대학·교육기관", "AI School 교육", "A대학교 산학협력단", "", 7000, "계산서 명세", "완료", "증빙 확인 후", "중복기재 여부 원증빙 확인"],
    [4, 2026, "2026.04 선정", "지원사업·기관자격", "훈련기관 선정·사업 수행", "C공단", "재직자 훈련", None, "승인과정 운영 훈련비", "수행 중", "현재 수행사업으로 가능", "선정공문 대조"],
    [5, 2023, "2023.11.10", "지식재산", "특허 출원 「X 시스템」", "출원인 주식회사 샘플에듀", "특허 출원", None, "", "출원", "출원으로만 가능", "등록특허로 표현 금지"],
    [6, 2022, "2022", "기업·재직자·컨설팅", "데이터 라벨링 교육 외 3건", "D진흥원", "라벨링", 15000, "계산서 명세", "완료", "가능", "외 3건 산정기준 확인"],
    [7, 2023, "2023", "지원사업·기관자격", "사회적기업 인증", "고용노동부", "인증", None, "", "확정", "가능", "인증서"],
    [8, 2026, "2026", "기업·재직자·컨설팅", "가능 표시지만 추진 중인 건", "E사", "", 1000, "", "추진 중", "가능", ""],
]


@pytest.fixture()
def ledger_xlsx(tmp_path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = pl.MASTER_SHEET
    ws.append(["SAMPLEEDU 종합 실적 연혁 · 전체본"])
    ws.append(["실적 항목", 8, "계산서 실적 합계", 30900])
    ws.append([])
    ws.append(HEADER)
    for row in ROWS:
        ws.append(row)
    other = wb.create_sheet("요약·범례")
    other.append(["AI 관련 교육 수행", "43건 이상"])
    path = tmp_path / "sample_ledger_20260728.xlsx"
    wb.save(path)
    return path


def test_read_and_classify(ledger_xlsx: Path) -> None:
    rows = pl.read_ledger(ledger_xlsx)
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5, 6, 7, 8]
    eligible = {r.seq for r in rows if r.eligible}
    assert eligible == {1, 2, 6, 7}
    reasons = {r.seq: r.exclusion_reason for r in rows if not r.eligible}
    assert "증빙 확인 후" in reasons[3]
    assert "현재 수행사업으로 가능" in reasons[4]
    assert "출원으로만 가능" in reasons[5]
    assert "추진 중" in reasons[8]  # 원장이 '가능'이어도 상태가 완료·확정·등록이 아니면 제외
    warned = next(r for r in rows if r.seq == 6)
    assert any("외 n건" in w for w in warned.warnings)
    assert any("금액 없음" in w for w in next(r for r in rows if r.seq == 7).warnings)


def test_paragraph_uses_only_cell_values(ledger_xlsx: Path) -> None:
    row = next(r for r in pl.read_ledger(ledger_xlsx) if r.seq == 1)
    text = pl.to_paragraph(row)
    assert text.startswith("[2026] 국제인증 AI 기초 교육 — A대학교 산학협력단 (2026.07.01).")
    assert "AI 기초 자격 교육." in text
    assert "금액 5,000천원(계산서 명세)." in text
    assert "상태: 완료." in text and "증빙 기준: 계약·계산서·결과자료 대조." in text and "원장 연번 1." in text
    # 집계 수치·미검증 표현은 없다
    assert "43건" not in text and "누적" not in text


def test_documents_are_grouped_and_pipeline_readable(ledger_xlsx: Path) -> None:
    rows = pl.read_ledger(ledger_xlsx)
    docs = pl.build_documents(rows, source_name=ledger_xlsx.name, ledger_date=pl.ledger_date_from_name(ledger_xlsx.name))
    assert set(docs) == {"ledger_대학_교육기관.md", "ledger_공공_지자체.md", "ledger_기업_재직자_컨설팅.md", "ledger_지원사업_기관자격.md"}
    body = docs["ledger_대학_교육기관.md"]
    meta, content = cis.parse_front_matter(body)
    assert meta["doc_type"] == "수행실적" and meta["synthetic"] == "false" and meta["data_class"] == "real"
    assert meta["ledger_date"] == "2026-07-28"
    chunks = cis.split_chunks(content)
    # 채택 행 1건 = 후보 문단 1개 (인용 안내문·제목은 문단이 아니다)
    assert len(chunks) == 1
    assert "국제인증 AI 기초 교육" in chunks[0]
    assert not cis.is_gap_chunk(chunks[0])
    # 제외 행은 어느 문서에도 없다
    joined = "\n".join(docs.values())
    assert "AI School 교육" not in joined and "특허 출원" not in joined and "추진 중인 건" not in joined


def test_payload_counts(ledger_xlsx: Path) -> None:
    rows = pl.read_ledger(ledger_xlsx)
    payload = pl.ledger_payload(rows, source_name=ledger_xlsx.name, ledger_date="2026-07-28")
    assert payload["counts"] == {"total": 8, "eligible": 4, "excluded": 4, "with_amount": 3}
    assert payload["by_group"]["대학·교육기관"] == 1
    assert payload["rows"][2]["exclusion_reason"]


def test_missing_sheet_or_header(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    wb.active.title = "다른시트"
    path = tmp_path / "x.xlsx"
    wb.save(path)
    with pytest.raises(pl.LedgerFormatError):
        pl.read_ledger(path)
    wb = openpyxl.Workbook()
    wb.active.title = pl.MASTER_SHEET
    wb.active.append(["연번", "제목"])
    wb.save(path)
    with pytest.raises(pl.LedgerFormatError):
        pl.read_ledger(path)


def test_amount_formatting() -> None:
    assert pl.format_amount(14904.9, "계산서 명세") == "금액 14,904.9천원(계산서 명세)"
    assert pl.format_amount(85000, "") == "금액 85,000천원"
    assert pl.format_amount(None, "x") == ""
