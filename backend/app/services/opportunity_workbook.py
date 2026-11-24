"""사업기회 **엑셀 출력** (0924.md §4-C · 담당자 지시 2).

## 왜 필요한가

담당자가 실제로 쓰는 도구는 엑셀이다. 지금까지는 Markdown·CSV 만 내려줬는데, CSV 는 시트가
하나라 「나라장터」와 「기업마당」과 「이번 주 할 일」을 한 파일에 담을 수 없었고, 링크도
글자였다. 검수자가 손으로 만든 두 표(`apply_candidates.csv`·`bizinfo_candidates.csv`)를
그대로 옮겨 놓을 수 있어야 사람이 다시 옮겨 적지 않는다.

## 시트 일곱

    사업기회        지금 조건 그대로 (화면과 같은 목록)
    나라장터        입찰 공고만
    기업마당        지원사업만 — 기준 답안 CSV 와 같은 열
    이번 주 할 일   7일 안에 닫히는 것 · 입찰과 지원사업을 나눠서
    갭 리포트       「무엇을 갖추면 몇 건이 열리는가」
    자격 판정 근거  공고별 규칙·판정·**공고문 원문 인용**
    브리핑          「오늘 브리핑」과 같은 목록 — 매출 → 지원금 · 회사 방식 순서 · 판단 낱말(37차 §3-H)

## 규율

- **여기서 새 판정을 만들지 않는다.** 목록·갭 리포트가 이미 만든 값을 형식만 바꿔 적는다.
  두 곳에서 따로 계산하면 화면과 파일이 갈린다.
- 링크는 하이퍼링크, 날짜는 날짜 셀. 글자로 적으면 엑셀에서 정렬이 안 된다.
- 머리글은 한국어이고 **기준 답안 CSV 와 같은 이름**이다.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core import storage
from app.schemas.business_opportunity import SOURCE_LONG_NAMES, SOURCE_NAMES, UnifiedOpportunity, UnifiedOpportunityListResponse
from app.services import practical_priority as practical
from app.services import opportunity_export_service as exporter

KST = timezone(timedelta(hours=9))

#: 시트 이름. 순서도 이대로다 — 수용 스크립트가 이 여섯을 센다.
SHEET_NAMES: tuple[str, ...] = (
    "사업기회",
    "나라장터",
    "기업마당",
    "이번 주 할 일",
    "갭 리포트",
    "자격 판정 근거",
    # 37차 §3-H — 「오늘 브리핑」과 같은 목록(매출 → 지원금 · 회사 방식 순서 · 판단 낱말 · 제외는 사유와 함께)
    "브리핑",
)

#: 기업마당 시트의 열. 검수자가 손으로 만든 `bizinfo_candidates.csv` 와 같은 이름이다.
#: 37차 §3-C-3 — 점수 · 분류 · 유형 · 접수방식 · 공고일을 함께 싣는다(정렬이 실무순이든 점수순이든). 「링크」는 맨 끝 그대로.
#: 40차 — 「꼬리표」(규모 큼 · 주제 확인 · AI 「본업 아닐 수 있음」 — 사업기회 행 · 브리핑 판단 칸과 같은 `practical_priority.tags_of`).
#: 43차 BRIEF-01 — 「비추천 사유」(D15 「비추천은 사유와 함께」를 내려받은 파일에서도 지킨다 · 비추천이 아니면 빈칸).
PRACTICAL_COLUMNS: tuple[str, ...] = ("회사 기준 검토 우선순위", "분류", "유형(근사)", "꼬리표", "비추천 사유", "접수방식", "공고일", "결정")

BIZINFO_COLUMNS: tuple[str, ...] = (
    "그룹", "순", "ID", "사업명", "주관/수행", "실제 마감", "마감 종류", "판정",
    "근거(공고문)", "회사 대조", "받는 것", "부담", "회사 역할", *PRACTICAL_COLUMNS, "링크",
)

#: 나라장터 시트의 열. `apply_candidates.csv` 와 같은 축이다.
G2B_COLUMNS: tuple[str, ...] = (
    "그룹", "순", "공고번호", "공고명", "발주기관", "예산(원)", "실제 마감", "마감 종류", "입찰 마감",
    "계약·낙찰", "제한·대상(확인값)", "남은 조건(갖추면 가능 · 직접 확인)", "메모", *PRACTICAL_COLUMNS, "링크",
)

WEEK_COLUMNS: tuple[str, ...] = ("출처", "남은 일수", "실제 마감", "마감 종류", "사업명", "발주/주관", "판정", "꼬리표", "결정", "우리 회사 입장에서", "링크")
GAP_COLUMNS: tuple[str, ...] = ("조건", "규칙", "막고 있는 건수", "확정을 막고 있는 건수", "예시 공고")
RULE_COLUMNS: tuple[str, ...] = ("출처", "공고명", "규칙", "항목", "판정", "근거(원문)", "남은 조건")

#: 「이번 주」의 길이. 화면(`ThisWeekPanel.WITHIN_DAYS`)과 같은 값이어야 한다.
THIS_WEEK_DAYS = 7
#: 기업마당에서 회사가 신청할 만한 지원분야. 화면(`SUPPORT_CATEGORIES`)과 같은 목록이다.
SUPPORT_CATEGORIES = frozenset({"기술", "창업", "인력", "경영"})
#: 출처마다 먼저 채우는 자리 수 — 입찰 4 + 지원사업 4 (0924 §4-B-3).
PER_SOURCE_ROWS = 4

_HEADER_FILL = PatternFill("solid", fgColor="1F2A44")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
_LINK_FONT = Font(color="0563C1", underline="single", size=10)
_BODY_FONT = Font(size=10)

#: 「자격 판정 근거」를 몇 건까지 담을까.
#:
#: 규칙을 다시 돌리는 것이라 1,700건을 전부 하면 파일 하나에 몇십 초가 걸린다.
#: 잘랐으면 시트 끝에 한 줄로 적는다 — **조용히 줄이지 않는다.**
MAX_RULE_ROWS = 300

#: 열 너비 상한. 공고명이 길어 한 열이 화면을 다 먹는 것을 막는다.
MAX_COLUMN_WIDTH = 52
MIN_COLUMN_WIDTH = 8


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _group_of(item: UnifiedOpportunity) -> str:
    """담당자가 실제로 나누는 축 (0924 §4-B-3).

    검수자의 A~E 그룹은 사람이 읽고 붙인 이름이라 앱이 그대로 만들 수 없다. 대신 앱이
    판정한 것으로 같은 뜻의 갈래를 만든다 — 지금 신청할 수 있는가, 무엇이 남았는가.
    43차 NUM-10 — 글자 접두어(A · B · C · D)를 뺐다. 실무 사전의 유형 A1~D(바로 옆 「유형(근사)」 열)와 같은 글자가 다른 뜻이었다.
    """
    if item.opportunity_type in ("procurement", "pre_spec"):
        tracks = set(item.work_tracks or ())
        if "education" in tracks:
            return "교육"
        if "development" in tracks:
            return "개발"
        return "그 밖"
    if item.participation:
        return "간접"
    if item.eligibility_gate == "FAIL":
        return "불가"
    if item.eligibility_gate == "PASS":
        return "바로 신청"
    if any("전남사회적경제통합지원센터" in c for c in (item.unlock_conditions or ())):
        return "소재 확인"
    return "확인 필요"


def unlock_cell(conditions: list[str] | tuple[str, ...] | None) -> str:
    """「갖추면 가능: … / 직접 확인: …」 — 브리핑과 같은 함수(43차 M7). 늦게 들여온다(브리핑이 이 모듈을 부른다)."""
    from app.services.opportunity_brief_service import unlock_cell as brief_unlock_cell

    return brief_unlock_cell(conditions)


def verdict_of(item: UnifiedOpportunity) -> str:
    """화면과 **같은 말**로 적는다 (규칙 11: 영문 판정값 금지)."""
    if item.participation:
        return item.participation
    return exporter.GATE_LABELS.get(item.eligibility_gate or "", "미확인")


def _money_parts(item: UnifiedOpportunity) -> tuple[str, str]:
    """「받는 것」과 「부담」을 「회사에 뜻하는 것」 한 줄에서 갈라 적는다."""
    line = item.company_meaning or ""
    parts = [p.strip() for p in line.split("·") if p.strip()]
    receive = [p for p in parts if any(w in p for w in ("무료", "최대", "만원", "억", "비율", "~"))]
    burden = [p for p in parts if "자부담" in p or "부담" in p]
    return " · ".join(p for p in receive if p not in burden), " · ".join(burden)


def practical_cells(item: UnifiedOpportunity) -> list[Any]:
    """점수 · 분류 · 유형(근사) · 접수방식 · 공고일 (37차 §3-C-3). 점수는 「회사 기준 검토 우선순위」 그대로 — 낙찰확률이 아니다."""
    published = item.published_at.astimezone(KST).replace(tzinfo=None) if item.published_at else ""
    return [
        item.company_priority_score if item.company_priority_score is not None else "미산정",
        item.practical_group or "",
        item.fit_type or "",
        " · ".join(practical.tags_of(item)),
        (item.relevance_note or "관련 낮음") if item.practical_group == "비추천" else "",
        " · ".join(item.submission_methods or ()),
        published,
        item.decision_text or "",  # 44차 M4 — 저장된 결정(참여 · 신청 …) 한 줄 · 브리핑 · 이번 주 할 일과 같은 값
    ]


def _deadline_cell(item: UnifiedOpportunity) -> Any:
    """**실제 마감**(입찰 · 등록 · 공고문 일정 중 가장 이른 것 · 43차 M1 · 브리핑과 같은 계산) — 날짜 셀, 없으면 문구(「마감 미상 — 개찰 …」)."""
    real = practical.effective_deadline(item)
    if real is not None and not practical.deadline_time_known(item):
        return practical.deadline_stamp(item)  # 날짜만 있던 공고문 일정 마감 — 23:59 를 적지 않는다(44차 M3)
    if real is not None:
        return real.astimezone(KST).replace(tzinfo=None)
    return practical.deadline_unknown_text(item) if practical.deadline_unknown(item) else (item.deadline_text or "")


def _deadline_kind_cell(item: UnifiedOpportunity) -> str:
    """실제 마감의 이름 — 「등록 마감」 · 「참가신청 마감」 · 「입찰 마감」 · 「신청 마감」(43차 M1)."""
    return practical.deadline_kind(item) or ("마감 미상" if practical.deadline_unknown(item) else "")


def _bid_deadline_cell(item: UnifiedOpportunity) -> Any:
    """나라장터 입찰 마감(`bidClseDt`) 그대로 — 실제 마감과 다를 수 있다. 없으면 빈칸(개찰일을 넣지 않는다 · H1)."""
    return item.deadline.astimezone(KST).replace(tzinfo=None) if item.deadline is not None else ""


# --------------------------------------------------------------------------
# 시트 쓰기
# --------------------------------------------------------------------------


def _write_header(sheet: Worksheet, columns: Sequence[str]) -> None:
    sheet.append(list(columns))
    for index in range(1, len(columns) + 1):
        cell = sheet.cell(row=1, column=index)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"  # 머리글 고정


def _autosize(sheet: Worksheet) -> None:
    """열 너비를 내용에 맞춘다. 한글은 두 칸으로 센다."""
    widths: dict[int, int] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            text = cell.value.strftime("%Y-%m-%d") if isinstance(cell.value, datetime) else str(cell.value)
            width = sum(2 if ord(ch) > 0x2000 else 1 for ch in text[:80])
            widths[cell.column] = max(widths.get(cell.column, 0), width)
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = max(
            MIN_COLUMN_WIDTH, min(MAX_COLUMN_WIDTH, width + 2)
        )


def _link(sheet: Worksheet, row: int, column: int, url: str | None) -> None:
    if not url:
        return
    cell = sheet.cell(row=row, column=column)
    cell.hyperlink = url
    cell.font = _LINK_FONT


def _cell_value(value: Any) -> Any:
    """엑셀이 받지 않는 제어 문자(세로 탭 등)를 뺀다 — 공고 요약에 섞여 오면 워크북 전체가 500 이었다(33차 최신화 뒤 실측)."""
    return ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value


def _append(sheet: Worksheet, values: Sequence[Any], *, link_column: int | None = None) -> int:
    sheet.append([_cell_value(value) for value in values])
    row = sheet.max_row
    for index in range(1, len(values) + 1):
        cell = sheet.cell(row=row, column=index)
        if cell.font is None or cell.font.size != 10:
            cell.font = _BODY_FONT
        if isinstance(cell.value, datetime):
            cell.number_format = "yyyy-mm-dd hh:mm"
        elif isinstance(cell.value, str) and cell.value.startswith("="):
            # 직접 넣은 · 붙여 넣은 제목이 「=」로 시작해도 수식이 아니라 글이다(38차 검토 · 수식 주입)
            cell.data_type = "s"
    if link_column is not None:
        _link(sheet, row, link_column, _text(values[link_column - 1]) or None)
    return row


def _g2b_row(item: UnifiedOpportunity) -> list[Any]:
    return [
        _group_of(item),
        item.source_rank or item.priority_rank,
        item.id.replace("g2b-", ""),
        item.title,
        item.agency,
        item.budget or "",
        _deadline_cell(item),
        _deadline_kind_cell(item),
        _bid_deadline_cell(item),
        item.award_line or "",
        " · ".join(filter(None, [verdict_of(item), item.gate_reason or ""])),
        unlock_cell(item.unlock_conditions),
        " · ".join(filter(None, [item.fit_line, item.caution_line])),
        *practical_cells(item),
        item.detail_url or "",
    ]


def _bizinfo_row(item: UnifiedOpportunity) -> list[Any]:
    receive, burden = _money_parts(item)
    quote = (item.clause_quotes or [item.document_note or ""])[0]
    return [
        _group_of(item),
        item.source_rank or item.priority_rank,
        item.id.replace("bizinfo-", ""),
        item.title,
        item.agency,
        _deadline_cell(item),
        _deadline_kind_cell(item),
        verdict_of(item),
        quote,
        item.gate_reason or "",
        receive,
        burden,
        item.participation or "직접 신청",
        *practical_cells(item),
        item.detail_url or "",
    ]


def _unified_row(item: UnifiedOpportunity) -> list[Any]:
    return [
        SOURCE_NAMES.get(item.source_type, item.source_type),
        _group_of(item),
        item.source_rank or item.priority_rank,
        item.id.replace("g2b-", "").replace("bizinfo-", ""),
        item.title,
        item.agency,
        item.budget or "",
        _deadline_cell(item),
        _deadline_kind_cell(item),
        _bid_deadline_cell(item) if item.source_type == "g2b" else "",
        verdict_of(item),
        item.company_meaning or item.fit_line or "",
        *practical_cells(item),
        item.detail_url or "",
    ]


UNIFIED_COLUMNS: tuple[str, ...] = (
    "출처", "그룹", "순", "공고번호/ID", "사업명", "발주/주관", "예산(원)", "실제 마감", "마감 종류", "입찰 마감",
    "판정", "우리 회사 입장에서", *PRACTICAL_COLUMNS, "링크",
)


def this_week(items: Iterable[UnifiedOpportunity], *, now: datetime) -> list[UnifiedOpportunity]:
    """「이번 주 할 일」 — 화면(`ThisWeekPanel.isThisWeek`)과 **같은 규칙**이다.

    두 곳에 규칙이 있는 것은 좋지 않다. 그래도 파일이 화면과 다른 목록을 담는 것보다는
    낫다 — 규칙을 고칠 때는 두 곳을 함께 고친다. 수용 스크립트가 두 목록을 대조한다.
    """
    chosen: list[UnifiedOpportunity] = []
    today = now.astimezone(KST).date()
    for item in items:
        if item.closed or item.eligibility_gate == "FAIL" or item.relevance_note:
            continue
        tracks = set(item.work_tracks or ())
        ours = bool(tracks & {"development", "education"}) or item.priority_label == "우선 검토"
        if not ours:
            continue
        if item.source_type == "bizinfo":
            if (item.category or "") not in SUPPORT_CATEGORIES:
                continue
            # **지금 손댈 수 있는 것만** (0925 §4-E-4). 회사가 아직 안 적은 값 때문에
            # 「확인 필요」인 건과 간접 참여는 이 자리에 두지 않는다 — 아침에 읽고
            # 바로 할 수 있는 일이 아니다. 목록에는 그대로 있다.
            if item.participation or item.check_side == "company":
                continue
            # **회사가 신청 주체가 아닐 수 있는 건**도 이 자리에 두지 않는다
            # (ISSUE-125 · prompt_05 §4-E-1). 「원문에서 확인하세요」는 아침에 읽고 바로
            # 할 수 있는 일이 아니다. 목록에는 그대로 있다.
            if item.audience_note:
                continue
            # 43차 M10 · BIZ-11 — 지원사업 자리는 사업 목적이 회사 갈래인 것만(`kind_fit`)
            if item.kind_fit is False:
                continue
        # 43차 M1 · NUM-04 — 실제 마감(입찰 · 등록 · 공고문 일정)과 **KST 달력 날짜 차**(화면 D-day · `practical.days_left` 하나).
        # 예전에는 흐른 시간을 내림해(내일 10:00 마감이 0) 화면 「이번 주 할 일」과 두 건이 달랐다.
        days = practical.days_left(item, today)
        if days is None or days < 0 or days > THIS_WEEK_DAYS:
            continue
        chosen.append(item)

    def left(item: UnifiedOpportunity) -> int:
        return practical.days_left(item, today) or 0

    def order(item: UnifiedOpportunity) -> tuple:
        """마감이 먼저. 같은 날이면 **지금 손댈 수 있는 것**이 앞이다 (0925 §4-E-4).

        같은 D-5 가 넷이면 어느 것이 오를지는 목록 순서(id)였다. 그래서 전남국방벤처센터가
        뒤로 밀렸다 — 「센터에 전화 한 통」이면 정해지는 건인데, 「대상 요건을 확정하지
        못했습니다」밖에 말할 게 없는 셋이 앞에 섰다.

        순서는 셋이다: **가능** → **열리는 조건을 아는 것** → 점수.
        """
        actionable = 0 if item.unlock_conditions else 1
        return (
            left(item),
            0 if item.eligibility_gate == "PASS" else 1,
            actionable,
            -(item.company_priority_score or 0),
            item.id,
        )

    chosen.sort(key=order)
    # 출처마다 자리를 나눠 준다 (0924 §4-B-3). 한쪽이 못 채우면 남은 자리는 다른 쪽이 쓴다.
    bid = [i for i in chosen if i.source_type == "g2b"][:PER_SOURCE_ROWS]
    support = [i for i in chosen if i.source_type == "bizinfo"][:PER_SOURCE_ROWS]
    picked = bid + support
    for item in chosen:
        if len(picked) >= PER_SOURCE_ROWS * 2:
            break
        if item not in picked:
            picked.append(item)
    picked.sort(key=order)
    return picked


def build(
    listing: UnifiedOpportunityListResponse,
    *,
    gaps: dict[str, Any] | None = None,
    rules: dict[str, list[Any]] | None = None,
    now: datetime | None = None,
    brief: tuple[list[list[Any]], list[str]] | None = None,
) -> bytes:
    """워크북 한 덩어리. `rules` 는 `{공고 id: [EligibilityResult, …]}` 다."""
    moment = now or storage.utc_now()
    book = Workbook()
    book.remove(book.active)

    unified = book.create_sheet(SHEET_NAMES[0])
    _write_header(unified, UNIFIED_COLUMNS)
    for item in listing.items:
        _append(unified, _unified_row(item), link_column=len(UNIFIED_COLUMNS))
    _autosize(unified)

    g2b_sheet = book.create_sheet(SHEET_NAMES[1])
    _write_header(g2b_sheet, G2B_COLUMNS)
    for item in listing.items:
        if item.source_type == "g2b":
            _append(g2b_sheet, _g2b_row(item), link_column=len(G2B_COLUMNS))
    _autosize(g2b_sheet)

    biz_sheet = book.create_sheet(SHEET_NAMES[2])
    _write_header(biz_sheet, BIZINFO_COLUMNS)
    for item in listing.items:
        if item.source_type == "bizinfo":
            _append(biz_sheet, _bizinfo_row(item), link_column=len(BIZINFO_COLUMNS))
    _autosize(biz_sheet)

    week_sheet = book.create_sheet(SHEET_NAMES[3])
    _write_header(week_sheet, WEEK_COLUMNS)
    for item in this_week(listing.items, now=moment):
        _append(
            week_sheet,
            [
                SOURCE_LONG_NAMES.get(item.source_type, item.source_type),
                practical.days_left(item, moment.astimezone(KST).date()),
                _deadline_cell(item),
                _deadline_kind_cell(item),
                item.title,
                item.agency,
                verdict_of(item),
                # 43차 BRIEF-14 — 목록 · 브리핑과 같은 꼬리표(규모 큼 · 주제 확인 · AI)
                " · ".join(practical.tags_of(item)),
                item.decision_text or "",
                item.company_meaning or item.fit_line or "",
                item.detail_url or "",
            ],
            link_column=len(WEEK_COLUMNS),
        )
    _autosize(week_sheet)

    gap_sheet = book.create_sheet(SHEET_NAMES[4])
    _write_header(gap_sheet, GAP_COLUMNS)
    for gap in (gaps or {}).get("gaps", []):
        _append(
            gap_sheet,
            [
                gap.get("condition", ""),
                gap.get("label", ""),
                gap.get("blocked", 0),
                gap.get("pending", 0),
                ", ".join(gap.get("blocked_examples") or gap.get("pending_examples") or []),
            ],
        )
    _autosize(gap_sheet)

    rule_sheet = book.create_sheet(SHEET_NAMES[5])
    _write_header(rule_sheet, RULE_COLUMNS)
    by_id = {item.id: item for item in listing.items}
    for notice_id, results in (rules or {}).items():
        item = by_id.get(notice_id)
        if item is None:
            continue
        for entry in results:
            _append(
                rule_sheet,
                [
                    SOURCE_NAMES.get(item.source_type, item.source_type),
                    item.title,
                    getattr(entry, "rule_id", ""),
                    getattr(entry, "label", ""),
                    exporter.GATE_LABELS.get(getattr(entry, "status", ""), "미확인"),
                    getattr(entry, "source", "") or "",
                    unlock_cell([getattr(entry, "unlock_condition", "") or ""]) if getattr(entry, "unlock_condition", "") else "",
                ],
            )
    if len(listing.items) > MAX_RULE_ROWS:
        _append(
            rule_sheet,
            [
                "",
                f"상위 {MAX_RULE_ROWS}건만 담았습니다",
                "",
                "",
                "",
                f"목록 {len(listing.items)}건 중 앞에서부터 {MAX_RULE_ROWS}건의 규칙만 다시 돌렸습니다."
                " 나머지는 화면의 상세 판정에서 봅니다.",
                "",
            ],
        )
    _autosize(rule_sheet)

    # 「브리핑」 시트 — 행은 브리핑 서비스가 만든 것을 그대로 적는다(새 판정 없음). 맨 아래에 출처 · 뜻 메모 줄.
    from app.services import opportunity_brief_service as brief_service

    brief_sheet = book.create_sheet(SHEET_NAMES[6])
    _write_header(brief_sheet, brief_service.SHEET_COLUMNS)
    rows, notes = brief if brief is not None else ([], [f"브리핑 목록을 만들지 못했습니다 — {brief_service.SOURCE_LINE}"])
    for row in rows:
        _append(brief_sheet, row, link_column=len(brief_service.SHEET_COLUMNS))
    for note in notes:
        _append(brief_sheet, [note])
    _autosize(brief_sheet)

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


_UNSAFE = re.compile(r"[^0-9A-Za-z가-힣._-]+")


def filename(organization_name: str, *, today: date | None = None) -> str:
    """`BidPilot_사업기회_<회사>_<YYYYMMDD>.xlsx` (0924 §4-C-1)."""
    stamp = (today or datetime.now(KST).date()).strftime("%Y%m%d")
    name = _UNSAFE.sub("", organization_name or "회사") or "회사"
    return f"BidPilot_사업기회_{name}_{stamp}.xlsx"
