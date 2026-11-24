"""실적 원장(xlsx) → 근거 문서(markdown) · 구조화 JSON 변환.

입력: 샘플에듀 「종합 실적 연혁」 원장 (열: 연번·연도·기간·분야·사업·과제·연혁·주관·발주·협력기관·주요 내용·성과·
      금액(천원)·금액 구분·상태·외부 성공연혁·증빙·주의사항). 열 이름으로 찾으므로 열 순서가 바뀌어도 된다.
출력:
  1. 분야별 markdown 문서 — 회사자료 등록 파이프라인(company_service)이 그대로 읽는 형식.
     행 1건 = 문단 1개 = 후보 문단 1개. 원장 셀 값만 옮기고 문장을 지어내지 않는다.
  2. 구조화 JSON — 전체 행(제외 사유 포함). 실적 요건 대조·수행실적표 채움에 쓴다.

근거 채택 규칙 (원장의 판단을 그대로 따른다):
  - 「외부 성공연혁」이 정확히 "가능"인 행만 근거 문서에 넣는다.
  - 「증빙 확인 후」「상태 확인 후」「출원으로만 가능」「운영사실만 가능」「현재 수행사업으로 가능」은 제외하고 사유를 남긴다.
  - 요약 시트의 집계 수치(건수·인원·매출 등)는 산출근거표가 없으므로 근거 문단으로 만들지 않는다.
  - 원장은 내부 자료다. 산출물은 data/company/ 아래(gitignore)에만 쓴다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MASTER_SHEET = "종합 실적 연혁"
EXTERNAL_OK = "가능"
# 완료 실적으로 보는 상태값 (샘플에듀 기본). 다른 회사는 import profile 로 바꾼다.
COMPLETED_STATUSES: tuple[str, ...] = ("완료", "확정", "등록")
REQUIRED_COLUMNS: tuple[str, ...] = ("seq", "title", "status", "external_use")

# 열 이름 → 필드. 원장 열 머리글의 공백·중점 차이를 흡수하기 위해 정규화해 비교한다 (샘플에듀 기본 프로필).
_COLUMNS: dict[str, tuple[str, ...]] = {
    "seq": ("연번",),
    "year": ("연도",),
    "period": ("기간",),
    "field": ("분야",),
    "title": ("사업·과제·연혁", "사업과제연혁", "사업명"),
    "agency": ("주관·발주·협력기관", "주관발주협력기관", "발주기관"),
    "summary": ("주요 내용·성과", "주요내용성과", "주요 내용"),
    "amount": ("금액(천원)", "금액천원", "금액"),
    "amount_basis": ("금액 구분", "금액구분"),
    "status": ("상태",),
    "external_use": ("외부 성공연혁", "외부성공연혁", "외부 사용"),
    "evidence_note": ("증빙·주의사항", "증빙주의사항", "증빙"),
}

DEFAULT_COLUMNS = _COLUMNS

GROUP_ORDER: tuple[str, ...] = (
    "대학·교육기관",
    "공공·지자체",
    "기업·재직자·컨설팅",
    "지원사업·기관자격",
    "지식재산",
    "회사 기본",
    "대외활동·네트워크",
)
DEFAULT_GROUP = "기타"


def _norm(text: Any) -> str:
    return re.sub(r"[\s·()]", "", str(text or "")).lower()


class LedgerFormatError(ValueError):
    """원장 시트나 필수 열을 찾지 못했다."""


@dataclass
class LedgerRow:
    seq: int
    year: str
    period: str
    field: str
    title: str
    agency: str
    summary: str
    amount_thousand_krw: float | None
    amount_basis: str
    status: str
    external_use: str
    evidence_note: str
    eligible: bool = False
    exclusion_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    # 원본 추적: 엑셀 행 번호(1부터)·시트명. 근거 문단과 JSON 에 함께 남긴다.
    row_number: int = 0
    sheet: str = ""


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "none" else text


def _amount(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[,\s천원]", "", str(value))
    try:
        return float(text)
    except ValueError:
        return None


def classify(
    row: LedgerRow,
    *,
    approved_values: tuple[str, ...] = (EXTERNAL_OK,),
    completed_statuses: tuple[str, ...] = COMPLETED_STATUSES,
) -> LedgerRow:
    """원장의 「외부 성공연혁」 판단을 그대로 채택 규칙으로 옮긴다. 채택값·완료 상태값은 프로필로 바꿀 수 있다."""
    use = row.external_use.strip()
    if use in approved_values:
        row.eligible = True
    elif not use:
        row.eligible = False
        row.exclusion_reason = "외부 성공연혁 칸이 비어 있음"
    else:
        row.eligible = False
        row.exclusion_reason = f"외부 성공연혁 「{use}」 — 원장에서 아직 쓸 수 있다고 표시하지 않아 쓰지 않습니다"
    if row.status.strip() not in completed_statuses and row.eligible:
        # 원장이 '가능'으로 표시했지만 상태가 완료 상태값이 아니면 보수적으로 제외한다 (미선정·검토 중·증빙 확인 전 차단).
        row.eligible = False
        row.exclusion_reason = f"상태 「{row.status}」 — {' · '.join(completed_statuses)}인 실적만 근거로 씁니다"
    if "외 " in row.title and "건" in row.title:
        row.warnings.append("'외 n건' 표기 — 계약 건수·회차 산정기준을 원증빙으로 확인")
    if row.eligible and row.amount_thousand_krw is None:
        row.warnings.append("금액 없음 — 실적 금액 요건 대조에는 쓸 수 없다")
    return row


#: 증빙을 아직 확인하지 않았다는 메모 · 외부 사용 값(「미확인」 · 「확인 필요」 · 「증빙 확인 후」).
_UNVERIFIED_RE = re.compile(r"미확인|확인\s*(?:이\s*)?필요|확인\s*후")
#: 기간 칸에 끝이 있나(「2024.03~2024.12」 · 「2024.3.~12.」 · 「2024.03 - 2024.12」) — 「2024-03」 한 날짜는 끝이 아니다.
_PERIOD_END_RE = re.compile(r"(?:[~～∼–]|\s-\s)\s*(?:\d{2,4}\s*[.년/-]\s*)?\d")


def evidence_state(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    """원장 행 근거 상태(2.8.0 B7 · 지금 있는 칸으로만 · 새 회사 값 없음) — (상태, 까닭).
    UNVERIFIED: 증빙 메모 · 외부 사용 값이 「미확인 · 확인 필요 · ~ 확인 후」이거나 외부 사용 「가능」+ 완료가 아님 ·
    MISSING: 끝날짜 · 금액 칸이 비었음 · SELF_REPORTED: 회사가 적은 「가능」+ 완료(증빙을 사람이 확인한 기록은 아님).
    VERIFIED 는 사람이 확인일 · 확인자를 적는 칸이 생길 때만 준다(지금 없음 · 대표 결정 필요)."""
    note = f"{row.get('evidence_note') or ''} {row.get('external_use') or ''}"
    usable = row.get("eligible") if "eligible" in row else str(row.get("external_use") or "").strip() == EXTERNAL_OK
    if _UNVERIFIED_RE.search(note) or not usable:
        return "UNVERIFIED", ["증빙 확인 전"]
    missing = [label for label, empty in (("끝날짜 없음", not _PERIOD_END_RE.search(str(row.get("period") or ""))),
                                          ("금액 없음", row.get("amount_thousand_krw") in (None, ""))) if empty]
    return ("MISSING", missing) if missing else ("SELF_REPORTED", [])


def find_header(rows: list[list[Any]], columns_spec: Mapping[str, Sequence[str]]) -> tuple[int | None, dict[str, int]]:
    """머리글 행(연번/번호 + 사업명 열이 있는 행)을 찾아 (행 index, 필드→열 index) 를 돌려준다."""
    seq_names = {_norm(n) for n in columns_spec.get("seq", ("연번",))}
    title_names = {_norm(n) for n in columns_spec.get("title", ())}
    for index, raw in enumerate(rows):
        cells = [_norm(c) for c in raw]
        if any(n in cells for n in seq_names) and any(n in cells for n in title_names):
            columns: dict[str, int] = {}
            for key, names in columns_spec.items():
                for name in names:
                    if _norm(name) in cells:
                        columns[key] = cells.index(_norm(name))
                        break
            return index, columns
    return None, {}


def read_ledger_rows(
    path: Path,
    *,
    sheet: str = MASTER_SHEET,
    columns: Mapping[str, Sequence[str]] | None = None,
    approved_values: tuple[str, ...] = (EXTERNAL_OK,),
    completed_statuses: tuple[str, ...] = COMPLETED_STATUSES,
) -> tuple[list[LedgerRow], dict[str, str]]:
    """xlsx 원장을 읽어 (행 목록, 실제로 쓴 열 머리글) 을 돌려준다. 열 매핑·채택값·완료 상태값은 프로필로 바꿀 수 있다."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise LedgerFormatError(f"openpyxl을 불러올 수 없습니다: {exc}") from exc

    spec: Mapping[str, Sequence[str]] = columns or _COLUMNS
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    if sheet not in workbook.sheetnames:
        raise LedgerFormatError(f"시트 '{sheet}'가 없습니다. 있는 시트: {workbook.sheetnames}")
    rows = [list(r) for r in workbook[sheet].iter_rows(values_only=True)]

    header_index, column_index = find_header(rows, spec)
    if header_index is None:
        raise LedgerFormatError("머리글 행(연번 · 사업명 …)을 찾지 못했습니다. 열 매핑을 확인하세요.")
    missing = [k for k in REQUIRED_COLUMNS if k not in column_index]
    if missing:
        raise LedgerFormatError(f"필수 열이 없습니다: {missing} — 열 매핑(프로필)을 고쳐 다시 시도하세요.")
    header_cells = [_cell(c) for c in rows[header_index]]
    columns_used = {key: header_cells[index] for key, index in column_index.items() if index < len(header_cells)}

    def get(raw: list[Any], key: str) -> Any:
        index = column_index.get(key)
        return raw[index] if index is not None and index < len(raw) else None

    result: list[LedgerRow] = []
    for offset, raw in enumerate(rows[header_index + 1 :], start=header_index + 2):
        seq_raw = get(raw, "seq")
        if seq_raw in (None, ""):
            continue
        try:
            seq = int(float(str(seq_raw)))
        except ValueError:
            continue
        row = LedgerRow(
            seq=seq,
            year=_cell(get(raw, "year")),
            period=_cell(get(raw, "period")),
            field=_cell(get(raw, "field")) or DEFAULT_GROUP,
            title=_cell(get(raw, "title")),
            agency=_cell(get(raw, "agency")),
            summary=_cell(get(raw, "summary")),
            amount_thousand_krw=_amount(get(raw, "amount")),
            amount_basis=_cell(get(raw, "amount_basis")),
            status=_cell(get(raw, "status")),
            external_use=_cell(get(raw, "external_use")),
            evidence_note=_cell(get(raw, "evidence_note")),
            row_number=offset,
            sheet=sheet,
        )
        if not row.title:
            continue
        result.append(classify(row, approved_values=approved_values, completed_statuses=completed_statuses))
    return result, columns_used


def read_ledger(path: Path, *, sheet: str = MASTER_SHEET) -> list[LedgerRow]:
    """샘플에듀 기본 프로필로 읽는다 (기존 호출자·테스트 호환)."""
    rows, _used = read_ledger_rows(path, sheet=sheet)
    return rows


def format_amount(value: float | None, basis: str, unit: str = "천원") -> str:
    if value is None:
        return ""
    number = f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"
    return f"금액 {number}{unit}" + (f"({basis})" if basis else "")


def to_paragraph(row: LedgerRow, *, amount_unit: str = "천원") -> str:
    """행 1건 → 근거 문단 1개. 원장 셀 값만 이어 붙인다 (금액 단위는 원장 그대로)."""
    head = f"[{row.year}] {row.title}"
    if row.agency:
        head += f" — {row.agency}"
    if row.period:
        head += f" ({row.period})"
    parts = [head + "."]
    if row.summary:
        parts.append(row.summary.rstrip(".") + ".")
    amount = format_amount(row.amount_thousand_krw, row.amount_basis, amount_unit)
    if amount:
        parts.append(amount + ".")
    parts.append(f"상태: {row.status}.")
    if row.evidence_note:
        parts.append(f"증빙 기준: {row.evidence_note}.")
    parts.append(f"원장 연번 {row.seq}.")
    if row.row_number:
        parts.append(f"원본 행 {row.row_number}" + (f" (시트 '{row.sheet}')" if row.sheet else "") + ".")
    return " ".join(parts)


def group_key(row: LedgerRow) -> str:
    return row.field if row.field in GROUP_ORDER else DEFAULT_GROUP


def _slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_") or "기타"


def build_documents(
    rows: list[LedgerRow],
    *,
    source_name: str,
    ledger_date: str,
    sheet: str = MASTER_SHEET,
    amount_unit: str = "천원",
) -> dict[str, str]:
    """채택 행을 분야별 markdown으로 만든다. 반환: {파일명: 본문}. front matter 에 원본 파일·시트·금액 단위를 남긴다."""
    eligible = [r for r in rows if r.eligible]
    groups: dict[str, list[LedgerRow]] = {}
    for row in eligible:
        groups.setdefault(group_key(row), []).append(row)

    documents: dict[str, str] = {}
    ordered = [g for g in GROUP_ORDER if g in groups] + [g for g in groups if g not in GROUP_ORDER]
    for group in ordered:
        items = sorted(groups[group], key=lambda r: r.seq)
        lines = [
            "---",
            f"document_name: 수행실적 원장 — {group} ({ledger_date})",
            "doc_type: 수행실적",
            "synthetic: false",
            "anonymized: false",
            "data_class: real",
            f"source_file: {source_name}",
            f"source_sheet: {sheet}",
            f"amount_unit: {amount_unit}",
            f"ledger_date: {ledger_date}",
            f"selection: 외부 성공연혁 = {EXTERNAL_OK} · 상태 완료/확정/등록",
            "---",
            "",
            f"> 내부 전용 실제 자료입니다. 원장 「{source_name}」의 「외부 성공연혁 = {EXTERNAL_OK}」 행만 옮겼으며, "
            "제안서에 쓰기 전 각 행의 증빙 기준(계약·계산서·결과자료)을 대조합니다. 집계 수치(누적 건수·인원·매출)는 담지 않았습니다.",
            "",
            f"# {group} 실적 {len(items)}건",
            "",
        ]
        for row in items:
            lines.append(to_paragraph(row, amount_unit=amount_unit))
            lines.append("")
        documents[f"ledger_{_slug(group)}.md"] = "\n".join(lines).rstrip("\n") + "\n"
    return documents


def ledger_payload(
    rows: list[LedgerRow], *, source_name: str, ledger_date: str, sheet: str = MASTER_SHEET, amount_unit: str = "천원"
) -> dict[str, Any]:
    """전체 행(제외 사유 포함)을 구조화 JSON으로. 내부 전용."""
    return {
        "_note": "실적 원장 구조화 데이터. 내부 전용 — Git에 올리지 않는다. eligible=false 행은 근거로 쓰지 않는다.",
        "source_file": source_name,
        "sheet": sheet,
        "amount_unit": amount_unit,
        "ledger_date": ledger_date,
        "converted_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "total": len(rows),
            "eligible": sum(1 for r in rows if r.eligible),
            "excluded": sum(1 for r in rows if not r.eligible),
            "with_amount": sum(1 for r in rows if r.eligible and r.amount_thousand_krw is not None),
        },
        "by_group": {
            group: sum(1 for r in rows if r.eligible and group_key(r) == group)
            for group in [*GROUP_ORDER, DEFAULT_GROUP]
            if any(group_key(r) == group for r in rows if r.eligible)
        },
        "rows": [asdict(r) for r in rows],
    }


def ledger_date_from_name(name: str) -> str:
    """파일명의 YYMMDD → 2026-07-28. 없으면 오늘이 아니라 '미상'으로 둔다 (추측하지 않는다)."""
    full = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
    if full:
        return f"{full.group(1)}-{full.group(2)}-{full.group(3)}"
    short = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", name)
    if not short:
        return "기준일 미상"
    yy, mm, dd = short.groups()
    return f"20{yy}-{mm}-{dd}"


def dump_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
