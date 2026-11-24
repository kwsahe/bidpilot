"""사업계획서 초안 내려받기 — 디자인한 DOCX · PDF, 제출용 · 검토용 두 판 (25차 §4-E · 28차 HWPX 없앰 · 29차 §3-D · 36차 §3-F).

**양식 순서 그대로**: 대항목 → 소항목 → 본문 → 그 자리의 표. 표는 몰아 쓰지 않는다(인력 구성 = 일반 현황 안 ·
정량적 성과 = 기업 현황 안 · 수상 이력 · 사업 추진일정 · 사업비 집행계획 = 해당 소항목 안).
넣지 않는 것: 양식의 안내 상자(「※ (표는 삭제 후 제출)」) · 「참고 사업비 집행 비목」 쪽 · 초안의 안내 줄(겨냥 평가 항목 ·
「공고 요구」 인용 — 화면에서만 본다).

두 판 (담당자 결정 2026-09-30 「디자인한 DOCX + PDF」 · 10-13 「더 정렬되고 세련되게」):
- **제출용** — 표식 · 회색 글자 · 근거 · 메모 · 요약 상자 · 목차 · 머리말 없음. 「(담당자 입력)」은 갈색 점선 밑줄.
- **검토용** — AI 덧붙임은 회색 글자 + 왼쪽 세로줄 · [공고] · [회사] 표식과 근거 · 범례 · 목차 · 요약 상자 · 끝에 검토 메모.

모양은 `docs/reports/2026-10-30_plan_doc_design/SPEC.md`(36차 §3-F) 하나를 따른다. **내용은 바꾸지 않는다** — 문장 글 ·
순서 · 유형 · 근거 · 빈칸 수가 그대로다. 묶는 규칙(○ 소제목 · ○ 항목 · - 하위 줄 · 라벨 줄 · 문단)은 `document_blocks`
한 곳에 있고 DOCX · HTML 이 같은 블록을 같은 숫자로 그린다: 맑은 고딕 · 본문 11pt / 줄 18pt 고정 · 양쪽 정렬 ·
개조식 내어쓰기 · 표 칸 너비 mm · 바닥글 「- n -」.

사업계획서 HWPX 는 담당자 결정으로 없앴다(2026-09-29). 입찰 「한글 서식(베타)」 5종은 `hwpx_template_service` 가 따로 만든다.
"""

from __future__ import annotations

import html
import io
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Literal

from app.services.plan_draft_service import COMPANY, NOTICE, SUGGESTION
from app.services.plan_fill_service import FIELD_MAP
from app.services.plan_form_service import HUMAN_INPUT, unwritten_count

BETA_NOTE = "회색 문장은 AI가 덧붙인 문장(근거 확인 후 고쳐 쓰기) · 「(담당자 입력)」은 담당자가 채웁니다"
KST = timezone(timedelta(hours=9))

#: blind = 평가본(입찰 제안서 · 11-06 B-3) — 제출용과 같고 회사 식별정보만 뺀 판(제안요청서가 평가본에 회사명 표기를 막을 때).
Variant = Literal["submit", "review", "blind"]
VARIANT_LABELS: dict[str, str] = {"submit": "제출용", "review": "검토용", "blind": "평가본"}

#: 디자인 값(SPEC §4 · §9 · §10 · §12) — DOCX 와 CSS 에 같은 숫자를 넣는다. 강조색은 남색 하나.
NAVY, INK, MUTED, RULE = "1F3A5F", "1A1A1A", "6B6B6B", "9AA7B8"
#: 표지 「공고 원문」 링크(2.9.1 · 대표 11-13) — 글자 색 · 이름 · 10pt 한 줄 근사 글자 수(값 칸 90mm) · 줄 간격 pt.
LINK_INK, LINK_LABEL, LINK_LINE_CHARS, LINK_LINE_PT = "0563C1", "공고 원문", 44, 15
HEAD_FILL = "E8EEF5"
BOX_FILL = "F3F6FA"
BLANK_INK, BLANK_LINE, BLANK_FILL = "8A6100", "B8860B", "FFF3B0"
AI_INK, AI_BAR, WARN = "5C5C5C", "C8C8C8", "B42318"
#: 글꼴 — 맑은 고딕 하나(SPEC §3). 없으면 나눔고딕 → 기본 글꼴(DOCX 는 받는 PC 의 Word 가 대신 고른다).
FONT = "맑은 고딕"
CSS_FONTS = '"Malgun Gothic", "맑은 고딕", "NanumGothic", "나눔고딕", sans-serif'
#: 검토용 표식 — 문단 첫머리에 한 번(SPEC §12). AI 덧붙임은 글자 대신 세로줄과 회색 글자.
TYPE_MARKS = {NOTICE: "공고", COMPANY: "회사"}
#: 본문 폭 166mm(twips) · 「○ 」 · 「- 」 · 「· 」 폭(맑은 고딕 11pt 실측, SPEC §6) · 검토 메모 하위 줄 6mm.
TEXT_TW: Final[int] = 9411
TW_GLYPH, TW_DASH, TW_DOT, TW_MEMO = 297, 168, 125, 340

#: 블록 — 튜플. 첫 칸이 종류다(`document_blocks` 설명).
Block = tuple
#: 글 블록 종류 — (종류, [(글, 유형, 근거)…], 깊이).
TEXT_KINDS: Final[tuple[str, ...]] = ("sub", "item", "dash", "label", "para")
#: XML 에 쓸 수 없는 제어문자 — 있으면 DOCX 가 500 이 됐다(26차 ISSUE-152). 블록을 만드는 곳에서 지운다.
#: U+FFFE · U+FFFF · 짝 없는 서러게이트도 XML 에 쓸 수 없다(36차 마지막 검토 F-3 — 「가\ufffe나.」 한 글자로 DOCX 500).
_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")
#: 추진 기간 칸 → 개월차 (「1~2개월차」 · 「3개월차」 · 「M1~M3」 · 「1-2개월」).
_MONTH_SPAN = re.compile(r"(?:M\s*)?(\d{1,2})\s*(?:개월\s*차?|월\s*차|차)?\s*[~\-–～∼]\s*(?:M\s*)?(\d{1,2})\s*(?:개월\s*차?|월\s*차|차)")
_MONTH_ONE = re.compile(r"(?:M\s*)?(\d{1,2})\s*(?:개월\s*차|월\s*차)")
_MONTH_M = re.compile(r"M\s*(\d{1,2})(?:\s*[~\-–～∼]\s*M?\s*(\d{1,2}))?")
#: 추진 기간 칸 → 주차(「W1~W3」 · 「W5」 — 13주 미만 짧은 사업 · 착수일 기준 · 2.10.0 D1).
_WEEK_SPAN = re.compile(r"(?<![A-Za-z])W\s*(\d{1,2})(?:\s*[~\-–～∼]\s*W?\s*(\d{1,2}))?")
#: 주차 칸 상한(주차는 91일 미만 사업만 · `bid_proposal_service.SHORT_PROJECT_DAYS`).
WEEK_CAP = 26
#: 양식 안내 「(선택)」 — 목차 · 제목에는 싣지 않는다(30차 §3-B).
_OPTIONAL_MARK = re.compile(r"\s*\(\s*선택\s*\)")
#: 검토용 머리글 앞말(30차 §3-B).
REVIEW_HEADER = "검토용 · 제출 금지"
#: 연번 칸 — 빈칸이면 1 · 2 · 3 으로 채운다(31차 R30-39).
_NARROW_COLUMN = re.compile(r"^(연번|순번|번호|No\.?)$", re.I)


def _clean(value: Any) -> str:
    return _XML_BAD.sub("", str(value if value is not None else ""))


def _css_string(value: Any) -> str:
    """CSS 문자열(`content: "…"`) 안에 넣을 글 — 백슬래시 · 큰따옴표 · `<` 를 CSS 이스케이프로 · 줄바꿈은 빈칸(30차 R29-09).
    `html.escape` 를 쓰면 「R&amp;D」가 그대로 찍혔고 줄바꿈이 있으면 머리글이 빠졌다."""
    text = re.sub(r"[\r\n\t]+", " ", _clean(value))
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3C ")


# ---------------------------------------------------------------------------
# 옛 블록 (25차 모양 — 화면 · 시험이 읽는다)
# ---------------------------------------------------------------------------


def plan_blocks(draft: dict[str, Any], form: dict[str, Any]) -> list[Block]:
    """초안 → 양식 순서의 블록(□ · ○ 머리). 글 · 표 칸의 제어문자는 여기서 지운다."""
    return [
        ("table", {**b[1], "title": _clean(b[1].get("title")), "columns": [_clean(c) for c in b[1].get("columns") or []],
                   "rows": [[_clean(cell) for cell in row] for row in b[1].get("rows") or []]})
        if b[0] == "table" else (b[0], _clean(b[1]))
        for b in _raw_blocks(draft, form)
    ]


def _raw_blocks(draft: dict[str, Any], form: dict[str, Any]) -> list[Block]:
    tables = {t.get("key"): t for t in draft.get("tables") or []}
    blocks: list[Block] = [("note", BETA_NOTE), ("heading", form.get("title") or draft.get("form_title") or "사업계획서 초안")]
    current_major = None
    for section in draft.get("sections") or []:
        major = section.get("major_title") or ""
        if major and major != current_major:
            blocks.append(("heading", f"□ {major}"))
            current_major = major
        if section.get("kind") == "fields":
            for field in section.get("fields") or []:
                blocks.append(("text", f"{field['label']}: {field.get('value') or HUMAN_INPUT}"))
        else:
            blocks.append(("subheading", f"○ {section['section']}" + (" (선택)" if section.get("optional") else "")))
            content = _content(section)
            if not content:
                blocks.append(("text", HUMAN_INPUT))
            for sentence in content:
                blocks.append(("suggestion" if sentence.get("type") == SUGGESTION else "text", str(sentence.get("text") or "")))
        for key in section.get("tables") or []:
            if key in tables:
                blocks.append(("table", tables[key]))
    return blocks


def _content(section: dict[str, Any]) -> list[dict[str, Any]]:
    """문서에 싣는 문장 — 안내 줄(겨냥 평가 항목 · 빈칸 안내)과 공고 요구 인용은 화면에서만 본다."""
    return [s for s in section.get("sentences") or [] if not s.get("note") and not s.get("notice_quote")]


# ---------------------------------------------------------------------------
# 새 블록 — 디자인 한 벌 (29차 §3-D · 36차 §3-F). DOCX · HTML 이 같은 목록을 그린다.
# ---------------------------------------------------------------------------


#: 월별 칸이 이보다 많으면 머리를 「n월」로 줄이고 첫 칸을 좁힌다(37차 EXP-03).
LONG_GRID_MONTHS = 8
#: 월별 칸 표 첫 칸 — 기본 50mm, 길면 줄이되 35mm 아래로는 줄이지 않는다.
GRID_FIRST_MM = 50.0
GRID_FIRST_MIN_MM = 35.0
_MONTH_HEAD = re.compile(r"^\d+월(?:차)?$|^\d{1,2}$|^W\d{1,2}$")  # 「1월차」 · 「12월」 · 개월차 숫자 「1」(2.8.0 B6) · 주차 「W1」(2.10.0 D1)
#: 4칸 현황 표를 통째로 한 쪽에 두는 최대 줄 수(37차 EXP-02).
FIELDS_WHOLE_ROWS = 8


def period_months(period: str) -> set[int]:
    """추진 기간 칸 → 칠할 개월차(1~36) — 「1~2개월차」 · 「3개월차」 · 「M1~M3」 · 구간이 여럿이면 「/ , ·」로 나눠 모두.
    개월차로 읽을 수 없는 칸(「계약체결일~착수보고」 · 「2027년 1~12월」)은 빈 집합(월별 칸 표 · 품질 게이트 SCHEDULE_GRID 가 함께 쓴다)."""
    marked: set[int] = set()
    for piece in re.split(r"[/,·]", period or ""):
        found = _MONTH_SPAN.search(piece) or _MONTH_M.search(piece) or _MONTH_ONE.search(piece)
        if not found:
            continue
        start = int(found.group(1))
        end = int(found.group(2)) if found.lastindex and found.lastindex >= 2 and found.group(2) else start
        if 1 <= start <= end <= 36:
            marked.update(range(start, end + 1))
    return marked


def period_weeks(period: str) -> set[int]:
    """추진 기간 칸 → 칠할 주차(1~26) — 「W1~W3」 · 「W5」 · 구간이 여럿이면 「/ , ·」로 나눠 모두(`period_months` 와 같은 모양 · 2.10.0 D1)."""
    marked: set[int] = set()
    for piece in re.split(r"[/,·]", period or ""):
        if not (found := _WEEK_SPAN.search(piece)):
            continue
        start = int(found.group(1))
        end = int(found.group(2) or start)
        if 1 <= start <= end <= WEEK_CAP:
            marked.update(range(start, end + 1))
    return marked


def period_reader(rows: list[Any], weeks: int | None) -> Callable[[str], set[int]]:
    """간트 칸 읽기 — 주차 사업(weeks)이고 추진 기간이 주차(Wn)로 읽히는 줄이 하나라도 있으면 주차, 아니면 개월차(지금 그대로).
    월별 칸 표(`schedule_grid`) · 품질 게이트 일정 검사 · 회귀 H 가 같은 함수로 읽는다(2.10.0 D1)."""
    if weeks and any(period_weeks(str(row[1])) for row in rows if len(row) > 1):
        return period_weeks
    return period_months


def week_table(period: dict[str, Any]) -> dict[str, Any] | None:
    """「착수일 기준 주차」 표(2.10.0 D1 · 앱이 계산 · AI 아님) — 주차마다 「D+n ~ D+m」 · 마지막 주는 고정 끝날까지(계약 예정일 + 일수 − 1).
    실제 착수일은 모르므로 계약 예정일로 계산한 참고 날짜 칸은 두지 않는다. 주차 사업(weeks · days · contract_from)이 아니면 None."""
    weeks, days = period.get("weeks"), period.get("days")
    if not (weeks and days and period.get("contract_from")):
        return None
    end = datetime.strptime(str(period["contract_from"]), "%Y-%m-%d") + timedelta(days=int(days) - 1)
    rows = [[f"W{w}", ("D" if w == 1 else f"D+{7 * (w - 1)}") + " ~ "
             + (f"{end.year}. {end.month}. {end.day}." if w == weeks else f"D+{7 * w - 1}")] for w in range(1, int(weeks) + 1)]
    return {"key": "schedule_weeks", "title": "착수일 기준 주차", "columns": ["주차", "기간(착수일 D 기준)"], "rows": rows,
            "widths_mm": [40.0, 126.0]}


def schedule_grid(table: dict[str, Any], months: int | None, begin: tuple[int, int] | None = None,
                  weeks: int | None = None) -> dict[str, Any] | None:
    """추진일정 표 → 월별 칸(■) 표. 추진 기간을 개월차로 읽을 수 있는 줄이 없으면 None(지어내지 않는다).
    기간 칸이 여러 구간이면(「1개월차 / 6~7개월차 / 12개월차」) 「/ , ·」로 나눠 모두 칠한다 — 첫 구간만 칠했다(11-06 심사).
    9개월 이상 머리는 실제 시작 연월(begin)을 알 때만 달 이름(「11월」 · 「12월」 · 「1월」 …) · 모르면 개월차 숫자(「1」 …)와 제목 「개월차」 —
    「1월」이 1개월차인데 1월로 읽혔다(2.8.0 B6 · 계약일을 모르는 공고).
    짧은 사업(weeks)은 주차 칸(머리 「W1」 … · `period_reader` — 주차로 읽히는 줄이 없으면 개월차 그대로 · 2.10.0 D1)."""
    rows = [row for row in table.get("rows") or [] if len(row) >= 2 and HUMAN_INPUT not in str(row[0])]
    read = period_reader(rows, weeks)
    spans = [(str(row[0]), marked) for row in rows if (marked := read(str(row[1])))]
    if not spans:
        return None
    if read is period_weeks:
        last = min(max(int(weeks or 0), max(max(m) for _, m in spans)), WEEK_CAP)
        return {
            "key": "schedule_grid",
            "title": f"추진 일정(주차별 · 사업기간 {weeks}주)",
            "columns": ["추진 내용", *(f"W{w}" for w in range(1, last + 1))],
            "rows": [[task] + ["■" if w in marked else "" for w in range(1, last + 1)] for task, marked in spans],
            "grid": True,
        }
    total = min(max(months or 0, max(max(m) for _, m in spans)), 36)
    long = total > LONG_GRID_MONTHS
    # 9개월 이상이면 머리를 줄인다 — 「1월 / 차」로 꺾였다(37차 recheck29 EXP-03)
    if long and begin:
        heads = [f"{(begin[1] + m - 2) % 12 + 1}월" for m in range(1, total + 1)]
    else:
        heads = [str(m) if long else f"{m}월차" for m in range(1, total + 1)]
    unit = "개월차" if long and not begin else "월별"
    return {
        "key": "schedule_grid",
        "title": f"추진 일정({unit} · 협약 기간 {total}개월)" if months else f"추진 일정({unit})",
        "columns": ["추진 내용", *heads],
        "rows": [[task] + ["■" if m in marked else "" for m in range(1, total + 1)] for task, marked in spans],
        "grid": True,
    }


def _similar(a: str, b: str) -> bool:
    """요약 상자에서 같은 문장으로 볼 만큼 비슷한가 — 띄어쓰기 · 문장부호를 뺀 글이 같거나 85% 넘게 겹친다(31차 R30-38)."""
    import difflib

    def squash(text: str) -> str:
        return re.sub(r"[\s.,·「」()\-]", "", text)

    x, y = squash(a), squash(b)
    return x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.85


#: 소항목 안 소제목 줄(「○ 목표 고객과 시장 현황」)은 문장이 아니다 — 요약 상자에 넣지 않는다(35차 Claude 초안 · 6줄 중 2줄이 소제목).
_BULLET_HEAD = re.compile(r"^[○□❍◦■▪•]\s*")
_SENTENCE_END = re.compile(r"(?:다|요|음|함)\s*[.。]?\s*$")


def _subheading(text: str) -> bool:
    return bool(_BULLET_HEAD.match(text)) and not _SENTENCE_END.search(text)


#: 요약 상자 후보는 소항목 앞쪽 이만큼 문장 안에서만 — 18문장 중 10번째 작성 지시문을 골랐다(36차 PLAN-02 · 123852).
SUMMARY_LOOKAHEAD: Final[int] = 3
#: 앞뒤 글을 가리키는 문장 — 혼자 옮기면 뜻이 없다(「세 시장의 금액은 위 전체 시장과 …」).
_POINTING_RE = re.compile(r"(?<![가-힣])(?:위|아래)(?:의|와|에서)?\s|(?<![가-힣])(?:앞서|상기|하기)(?![가-힣])")


def _summary(items: list[dict[str, Any]]) -> list[str]:
    """대항목 첫머리 핵심 요약(검토용만) — 소항목마다 첫 본문 문장 **전체**(최대 3줄). 기계적으로 자르지 않는다(30차 §3-B · C-05 「…」).
    없는 문장을 만들지 않는다. 같은 · 비슷한 문장은 한 번만 — 2-2 · 2-3 첫 문장이 같아 두 줄이 같았다(31차 R30-38)."""
    lines: list[str] = []
    for section in items:
        candidates = [s for s in _content(section) if not _subheading(_clean(s.get("text")).strip())][:SUMMARY_LOOKAHEAD]
        first = next((s for s in candidates
                      if HUMAN_INPUT not in str(s.get("text") or "") and not _POINTING_RE.search(_clean(s.get("text")))), None)
        # 글머리(「○」)는 요약 상자의 「·」와 겹친다 — 떼고 싣는다
        text = _BULLET_HEAD.sub("", _clean(first.get("text")).strip()) if first else ""
        if text and not any(_similar(text, line) for line in lines):
            lines.append(text)
        if len(lines) == 3:
            break
    return lines


def _blank_only(section: dict[str, Any]) -> bool:
    """내용이 빈칸뿐인 절 — 문장이 없거나 모든 문장이 「이름: (담당자 입력)」 꼴이고 표도 없다."""
    if section.get("tables"):
        return False
    return all(HUMAN_INPUT in str(s.get("text") or "") and len(str(s.get("text")).replace(HUMAN_INPUT, "").strip(" :·-.")) <= 30
               for s in _content(section))


#: 사진 절 — 문장 · 표가 하나도 없는 「이미지」 · 「사진」 절은 제출용에서도 제목과 사진 칸으로 남겨 번호를 잇는다(담당자 결정 10-13 · SPEC §21-3).
_PHOTO_RE = re.compile(r"이미지|사진")


def _photo_section(section: dict[str, Any]) -> bool:
    return (section.get("kind") != "fields" and not _content(section) and not section.get("tables")
            and bool(_PHOTO_RE.search(str(section.get("section") or ""))))


def _heading(text: Any) -> str:
    return _OPTIONAL_MARK.sub("", _clean(text)).strip()


# ---------------------------------------------------------------------------
# 묶는 규칙 (SPEC §7) — 문장 목록 → 소제목 · ○ 항목 · - 하위 줄 · 라벨 줄 · 문단. 글자는 바꾸지 않는다.
# ---------------------------------------------------------------------------

_GLYPH = re.compile(r"^([○□❍◦■▪•])\s*")
_DASH = re.compile(r"^([-–·])\s+")
_SENT_END = re.compile(r"(?:다|요|음|함)\s*[.。]?\s*\)?\s*$")
#: 「…다음과 같습니다.」 · 쌍점으로 끝나는 문장은 문단을 닫는다(뒤는 목록).
_LEAD_END = re.compile(r"(?:다음과|아래와) 같습니다[.。]?\s*$|[:：]\s*$")
#: 단계 이름으로 여는 문장 — 새 문단(연결어로 시작하면 붙인다).
_STAGE_CUE = re.compile(r"^(?:「[^」]{2,30}」\s*(?:단계)?(?:에서는|에서|의|결과는|에는)|[가-힣A-Za-z·\s]{2,25}단계(?:에서는|에서|의|에는)\s)")
_CONNECT = re.compile(r"^(?:이를 통해|이렇게|이에|또한|그러나|그 결과|따라서|다만|이후|이어|같은 |이 |그 |해당 |이러한|기록한|정리한|합의한|"
                      r"분석 결과|분류 결과|검증 의견|개선 목록|개발 목록|비교 기준)")
_OURS = re.compile(r"^당사(?:는|의|가)\s")
#: 문단 크기 — 3문장(연결어면 4번째까지) · 4문장 상한 · 220자(연결어 280자) · 소항목 첫머리 공고 현황 문단 4문장.
PARA_SOFT, PARA_HARD, PARA_CHARS, PARA_CHARS_GLUE, LEAD_MAX = 3, 4, 220, 280, 4
_OPEN, _CLOSE = "(（「", ")）」"


def _outside(text: str):
    """괄호 · 낫표 밖의 (자리, 글자)."""
    depth = 0
    for i, ch in enumerate(text):
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0:
            yield i, ch


def _label_end(text: str) -> tuple[int, str] | None:
    """「라벨: 값」 · 「라벨 — 값」 — 괄호 밖 첫 쌍점(또는 「 — 」) 앞이 2~30자이고 문장 끝이 아니면 (그 자리, ':' · '—')."""
    for i, ch in _outside(text):
        if ch in ":：" or text.startswith(" — ", i):
            label = text[:i].strip()
            if 2 <= len(label) <= 30 and not _SENT_END.search(label) and "." not in label:
                return i, ":" if ch in ":：" else "—"
            return None
    return None


def _kind(text: str) -> str:
    """한 줄의 종류 — sub · item · dash · label · lead · plain (SPEC §7-1~5)."""
    if _GLYPH.match(text):
        colon = any(ch in ":：" for _, ch in _outside(text))
        if not _SENT_END.search(text) and not colon and not text.endswith(HUMAN_INPUT):
            return "sub"
        return "item"
    if _DASH.match(text):
        return "dash"
    label = _label_end(text)
    if label and label[1] == ":":
        value = text[label[0] + 1:].strip()
        if HUMAN_INPUT in value or not _SENT_END.search(value) or len(value) <= 12:
            return "label"
    return "lead" if _LEAD_END.search(text) else "plain"


def _lines(content: list[dict[str, Any]]) -> list[tuple[str, Any, str | None]]:
    """문장 → 줄(글, 유형, 근거). 문장 안 줄바꿈은 줄을 나눈다 — 첫 줄이 근거를 갖고 둘째 줄부터는 유형만 물려받는다(SPEC §7-0)."""
    out: list[tuple[str, Any, str | None]] = []
    for sentence in content:
        source = _clean(sentence.get("source") or "") or None
        parts = [line.strip() for line in re.split(r"\r?\n", _clean(sentence.get("text"))) if line.strip()]
        out += [(line, sentence.get("type"), source if j == 0 else None) for j, line in enumerate(parts)]
    return out


def _group(lines: list[tuple[str, Any, str | None]]) -> list[Block]:
    """한 소항목의 줄 → 글 블록 (종류, [(글, 유형, 근거)…], 깊이). 유형이 바뀌면 문단을 끊어 문단마다 유형은 하나다."""
    blocks: list[list[Any]] = []  # [종류, 줄들, 깊이, 닫힘]
    lead = 0
    while (lead < len(lines) and lines[lead][2] and _kind(lines[lead][0]) == "plain" and _SENT_END.search(lines[lead][0])
           and lines[lead][1] == lines[0][1]):
        lead += 1
    for start in range(0, lead, LEAD_MAX):  # 소항목 첫머리 공고 인용 — 현황 문단(최대 4문장)
        blocks.append(["para", list(lines[start:min(start + LEAD_MAX, lead)]), 0, True])
    under_sub = False
    for line in lines[lead:]:
        text, sentence_type, _source = line
        kind = _kind(text)
        if kind == "sub":
            under_sub = True
            blocks.append(["sub", [line], 0, True])
            continue
        if kind in ("item", "dash"):
            blocks.append([kind, [line], 0, True])
            continue
        depth = 1 if under_sub else 0
        if kind == "label":
            blocks.append(["label", [line], depth, True])
            continue
        prev = blocks[-1] if blocks else None
        if prev and prev[0] == "para" and prev[2] == depth and not prev[3] and _SENT_END.search(text):
            cur = prev[1]
            glue = bool(_CONNECT.match(text))
            chars = sum(len(s[0]) for s in cur) + len(text)
            new = (cur[-1][1] != sentence_type
                   or (_STAGE_CUE.match(text) and not glue)
                   or (_OURS.match(text) and not any(_OURS.match(s[0]) for s in cur))
                   or (len(cur) >= PARA_SOFT and not glue) or len(cur) >= PARA_HARD
                   or chars > (PARA_CHARS_GLUE if glue else PARA_CHARS))
            if not new:
                cur.append(line)
                prev[3] = kind == "lead"
                continue
        # 조각(문장 끝이 아닌 줄)은 한 줄로 두고 뒤 문장을 붙이지 않는다
        blocks.append(["para", [line], depth, kind == "lead" or not _SENT_END.search(text)])
    return [(kind, sentences, depth) for kind, sentences, depth, _closed in blocks]


def column_mm(columns: list[str], total: float = 166.0) -> list[float]:
    """표 칸 너비(mm, 합 166) — 이름으로 고정 폭, 나머지는 긴 글 칸 2 : 그 밖 1. 월별 칸 표는 첫 칸 50mm(SPEC §9)."""
    if any(_MONTH_HEAD.match(str(c)) for c in columns):
        months = sum(1 for c in columns if _MONTH_HEAD.match(str(c)))
        # 9개월 이상이면 첫 칸을 한 달에 3mm씩 줄인다(최소 35mm · 37차 EXP-03) — 월 칸이 「12월」 글자를 담을 만큼 넓어진다
        first = GRID_FIRST_MM if months <= LONG_GRID_MONTHS else max(GRID_FIRST_MIN_MM, GRID_FIRST_MM - 3.0 * (months - LONG_GRID_MONTHS))
        return [first] + [(total - first) / months] * months if months == len(columns) - 1 else [total / len(columns)] * len(columns)
    fixed = ((r"^(연번|순번|번호)$", 12.0), (r"^성명$", 22.0), (r"^직위$", 20.0), (r"(구성\s*)?상태$", 22.0), (r"^비목$", 30.0),
             (r"금액|사업비\(|합계", 32.0), (r"기간$", 26.0))
    widths = [next((mm for pattern, mm in fixed if re.search(pattern, str(c))), None) for c in columns]
    # 「담당 업무」(띄어 씀)는 입찰 참여인력 표 — 본문 업무분장 글이 든다(2.10.0 D4). 사업계획서 인력 표 「담당업무」는 보유 역량 칸이 넓어야 해 그대로
    weight = [0 if w else (2 if re.search(r"산출\s*근거|세부\s*내용|보유\s*역량|주요\s*활동|^담당\s+업무$", str(c)) else 1) for c, w in zip(columns, widths)]
    rest = total - sum(w for w in widths if w)
    if not sum(weight):  # 모두 고정 폭 — 비율대로 맞춘다
        used = sum(w for w in widths if w) or 1.0
        return [w * total / used for w in widths if w]
    return [w if w else rest * k / sum(weight) for w, k in zip(widths, weight)]


def cell_align(column: str, value: str) -> str:
    """칸 정렬 — 연번 · 「…기간」 · 「n월차」 가운데(c) · 금액 칸이나 숫자 값 오른쪽(r) · 그 밖 왼쪽("")."""
    if re.search(r"^(연번|순번|번호)$|기간$|월차$|^\d+월$|^W\d+$", str(column)) or value == "■":
        return "c"
    if re.search(r"금액|사업비|합계|\(원\)|\(명\)|억원", str(column)) or re.match(r"^\s*\d[\d,.\s]*(원|명|%|건|개)?\s*$", str(value)):
        return "r"
    return ""


def split_items(value: str) -> list[str]:
    """「 · 」 · 「 / 」로 나뉜 조각이 3개 이상이면 칸 안에서 한 줄에 하나씩(SPEC §8). 덧붙이는 글자는 없다."""
    for sep in (" · ", " / "):
        parts = value.split(sep)
        if len(parts) >= 3:
            return parts
    return [value]


def _photo_field(label: str, value: str) -> bool:
    return bool(_PHOTO_RE.search(label)) and value.strip() == HUMAN_INPUT


def field_rows(fields: list[tuple[str, str, str]]) -> list[list[tuple[str, str, str]]]:
    """일반 현황 줄 — 짧은 칸(값 20자 이하 · 라벨 8자 이하 · 한 항목) 둘이 이어지면 한 줄, 아니면 값이 세 칸을 차지. 읽는 순서는 그대로."""
    def short(field: tuple[str, str, str]) -> bool:
        label, value = field[0], field[1]
        return len(value) <= 20 and len(label) <= 8 and len(split_items(value)) == 1 and not _photo_field(label, value)

    rows: list[list[tuple[str, str, str]]] = []
    i = 0
    while i < len(fields):
        if i + 1 < len(fields) and short(fields[i]) and short(fields[i + 1]):
            rows.append([fields[i], fields[i + 1]])
            i += 2
        else:
            rows.append([fields[i]])
            i += 1
    return rows


def document_blocks(draft: dict[str, Any], form: dict[str, Any], *, variant: Variant, meta: dict[str, Any]) -> list[Block]:
    """초안 → 문서 블록(제출용 · 검토용). meta: notice · task · company · date.

    블록: ("cover", dict) · ("legend",) · ("toc", [(층, 글)]) · ("h1", 글) · ("h2", 글, AI 문장 수, 문장 수) · ("summary", [줄]) ·
    ("field", 이름, 값, 출처) · ("photo", 글) · 글 블록 (sub · item · dash · label · para, [(글, 유형, 근거)…], 깊이) ·
    ("table", 표) · ("memo_h", 글) · ("memo", 글, 깊이) · ("memo_table", 표).
    범례 · 목차 · 요약 상자 · 검토 메모는 검토용만(담당자 결정 10-13 · SPEC §11 · §14).
    """
    review = variant == "review"
    if variant == "blind":
        draft, meta = blind_copy(draft, meta)
    tables = {t.get("key"): t for t in draft.get("tables") or []}
    period = form.get("agreement_period") or {}
    months = period.get("months")
    # 월별 칸 머리 달 이름은 실제 시작 연월을 알 때만(입찰 사업기간 두 날짜 꼴 · 2.8.0 B6)
    begin = tuple(int(x) for x in str(period["start"]).split("-")[:2]) if period.get("start") else None
    sections = draft.get("sections") or []
    majors: list[tuple[str, list[dict[str, Any]]]] = []
    for section in sections:
        major = section.get("major_title") or section.get("section") or ""
        if not majors or majors[-1][0] != major:
            majors.append((major, []))
        majors[-1][1].append(section)

    body: list[Block] = []
    toc: list[tuple[int, str]] = []
    # 입찰 제안서는 제안요청서가 정한 번호(「Ⅰ. 제안개요」 · 「1. 제안 목적」)를 그대로 쓴다(11-03 `bid_proposal_service`)
    numbered = not draft.get("numbered_titles")

    def dropped(section: dict[str, Any]) -> bool:
        # 제출용 — 내용이 빈칸뿐인 선택 절은 절 · 목차 줄을 뺀다(30차 §3-B). 검토용에는 둔다. 사진 절은 남긴다(SPEC §21-3).
        return (not review and bool(section.get("optional")) and section.get("kind") != "fields" and _blank_only(section)
                and not _photo_section(section))

    # 번호는 검토용과 같은 차례로 매긴다 — 뺀 절은 번호를 건너뛴다(31차 R30-26: 다시 매겨 두 판 번호가 달랐다).
    for m, (major, all_items) in enumerate(majors, start=1):
        items = [s for s in all_items if not dropped(s)]
        if not items:
            continue
        h1 = f"{m}. {_heading(major)}" if numbered else _heading(major)
        toc.append((1, h1))
        body.append(("h1", h1))
        summary = _summary([s for s in items if s.get("kind") not in ("fields", "table_only")])
        # 제출용에서는 뺀다 — 공식 양식에 없는 모양이고 엉뚱한 문장을 고르기도 했다(담당자 결정 10-13 · SPEC §11)
        if len(summary) >= 2 and review:
            body.append(("summary", summary))
        n = 0
        for section in all_items:
            if section.get("kind") == "table_only":
                # 표만 있는 절(입찰 「기술능력 평가항목별 조견표」) — 대항목 머리 아래 표만 둔다 · 머리와 같은 표 제목은 두 번 찍지 않는다(2.9.0)
                for key in section.get("tables") or []:
                    if key in tables:
                        table = _clean_table(tables[key], review=review)
                        body.append(("table", {**table, "title": None} if _heading(table.get("title")) == _heading(major) else table))
                continue
            if section.get("kind") != "fields" and dropped(section):
                n += 1  # 뺀 선택 절 — 번호만 센다
                continue
            if section.get("kind") == "fields":
                title = _heading(section.get("section"))
                if not numbered and title and title != _heading(major).split(". ", 1)[-1]:
                    # 입찰 제안서의 칸 절은 소항목이다(「Ⅱ. 제안사 일반 › 1. 일반현황」) — 소제목을 단다(11-03)
                    toc.append((2, title))
                    body.append(("h2", title, 0, 0))
                shown: dict[str, str] = {}  # 같은 회사 값 두 칸(사업장 소재지 · 주소)은 한 번(30차 §3-B)
                for field in section.get("fields") or []:
                    value = _clean(field.get("value") or HUMAN_INPUT)
                    key = FIELD_MAP.get(str(field.get("label") or "").strip())
                    if key and HUMAN_INPUT not in value and shown.get(key) == value:
                        continue
                    if key:
                        shown[key] = value
                    origin = "company" if field.get("filled_by") == "company" else ("human" if HUMAN_INPUT in value or value.startswith("(담당자") else "")
                    body.append(("field", _clean(field.get("label")), value, origin))
            else:
                n += 1
                h2 = f"{m}-{n}. {_heading(section.get('section'))}" if numbered else _heading(section.get("section"))
                # 소항목 없이 대항목 하나뿐인 절(「Ⅵ. 결과 활용성 부문」)은 같은 제목을 두 번 달지 않는다
                same = not numbered and h2 == _heading(major).split(". ", 1)[-1]
                if not same:
                    toc.append((2, h2))
                content = _content(section)
                if _photo_section(section):
                    body += [("h2", h2, 0, 0), ("photo", HUMAN_INPUT)]
                else:
                    lines = _lines(content)
                    counted = [line for line in lines if _kind(line[0]) != "sub"]
                    if not same:
                        body.append(("h2", h2, sum(1 for line in counted if line[1] == SUGGESTION), len(counted)))
                    body += _group(lines) if content else [("para", [(HUMAN_INPUT, None, None)], 0)]
            for key in section.get("tables") or []:
                if key not in tables:
                    continue
                if (key == "schedule" and period_reader(tables[key].get("rows") or [], period.get("weeks")) is period_weeks
                        and (weekly := week_table(period))):
                    # 짧은 사업 — 착수일 기준 주차 표를 일정표 앞에(2.10.0 D1) · 일정표가 개월차(월별 간트)면 단위가 둘이라 붙이지 않음(T2 검토)
                    body.append(("table", weekly))
                table = _clean_table(tables[key], review=review)
                body.append(("table", table))
                if key == "schedule":
                    grid = schedule_grid(table, months, begin, weeks=period.get("weeks"))  # type: ignore[arg-type]
                    if grid:
                        if not numbered:  # 입찰 제안서는 「사업기간」(원문 · 표지 낱말 · 2.9.0) — 「협약 기간」은 사업계획서 낱말
                            grid = {**grid, "title": grid["title"].replace("협약 기간", "사업기간")}
                        body.append(("table", grid))

    # 표지 값도 제어문자를 지운다 — 과제명에 제어문자 하나면 DOCX 가 500 이었다(30차 R29-04)
    cover = {k: _clean(v) if isinstance(v, str) else v for k, v in meta.items()}
    blocks: list[Block] = [("cover", {**cover, "variant": VARIANT_LABELS[variant]})]
    if review:
        blocks += [("legend",), ("toc", toc)]
    blocks += body
    if review:
        blocks += _memo_blocks(draft)
    return blocks


def _block_text(block: Block) -> str:
    """블록이 문서에 싣는 글(빈칸 세기 · 내용 보존 시험)."""
    kind = block[0]
    if kind in TEXT_KINDS:
        return " ".join(sentence[0] for sentence in block[1])
    if kind == "field":
        return str(block[2])
    if kind == "photo":
        return str(block[1])
    if kind in ("table", "memo_table"):
        return " ".join(str(cell) for row in block[1].get("rows") or [] for cell in row)
    return ""


def block_blanks(block: Block) -> int:
    """블록 하나가 문서에 싣는 미작성 칸 수(`unwritten_count` 한 규칙 · 2.8.0 B3) — 표지는 빈 줄마다(문서가 「(담당자 입력)」을 찍는다) ·
    표는 칸마다(칸 전체 「미정」도 센다)."""
    kind = block[0]
    if kind == "cover":
        # 제출일이 비어도 표지에 빈칸이 하나 생긴다(36차 마지막 검토 F-4 — 내려받기는 늘 날짜를 넣지만 세는 쪽이 빠뜨렸다)
        return sum(1 for _, value in cover_rows(block[1]) if not value)
    if kind in ("table", "memo_table"):
        return sum(unwritten_count(str(cell)) for row in block[1].get("rows") or [] for cell in row)
    return unwritten_count(_block_text(block))


def blank_total(draft: dict[str, Any], form: dict[str, Any], meta: dict[str, Any] | None = None, *, variant: Variant = "submit") -> int:
    """그 판 문서에 남는 미작성 칸 수 — 내려받는 파일과 같은 블록에서 센다(한글 다시 읽기 대조 · 2.8.0 B9)."""
    return sum(block_blanks(block) for block in document_blocks(draft, form, variant=variant, meta=meta or {}))


def submit_variant(draft: dict[str, Any]) -> Variant:
    """내는 파일의 판 — 원문이 평가본만 받는 공고(`format.blind_only` · 2.10.0 D8)는 평가본, 그 밖(옛 초안 · 사업계획서 포함)은 제출용.
    게이트 빈칸 · 화면 「제출 전 채울 칸」 · 한글 다시 읽기가 이 판을 센다(T6 검토 · Review Focus 5)."""
    return "blind" if (draft.get("format") or {}).get("blind_only") else "submit"


def submit_blank_count(draft: dict[str, Any], form: dict[str, Any], meta: dict[str, Any] | None = None) -> int:
    """내는 문서(`submit_variant`)에 남는 미작성 칸 수 — 내려받기 단추 옆 「제출 전 채울 칸 n개」(30차 §3-B) · 품질 게이트 `submit_blanks` 와 같은 값.
    meta 는 내려받기와 같은 표지 값(`export_meta`) — 과제명 · 기업명이 비면 표지에도 빈칸이 하나씩 생긴다."""
    return blank_total(draft, form, meta, variant=submit_variant(draft))


def official_link(url: Any) -> str | None:
    """나라장터 공식 공고 주소만(https · g2b.go.kr) — 표지 링크 · 화면 링크가 같은 규칙. 지어낸 주소 · 다른 곳 주소 · 빈칸 · 제어문자 ·
    URL 에 쓰지 않는 글자(< > " ' ` 백슬래시)는 None."""
    from urllib.parse import urlsplit

    text = str(url or "").strip()
    if not text or len(text) > 500 or any(ch.isspace() or ord(ch) < 32 or ch in "<>\"'`\\" for ch in text):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "g2b.go.kr" or host.endswith(".g2b.go.kr")):
        return None
    return text


def cover_link(info: dict[str, Any]) -> tuple[str, str] | None:
    """표지 맨 아래 「공고 원문」 줄(입찰 제안서 · 2.9.1) — (이름, 주소). 빈칸 셈(`cover_rows`)에는 들지 않는다(값이 없으면 줄도 없다)."""
    url = official_link(info.get("link_url"))
    return (LINK_LABEL, url) if url else None


def cover_rows(info: dict[str, Any]) -> list[tuple[str, Any]]:
    """표지 아래 줄 — 사업계획서는 과제명 · 기업명 · 제출일, 입찰 제안서는 `rows`(발주기관 · 제안사 · 제출일 · 11-03)."""
    rows = info.get("rows")
    if rows:
        return [(str(label), value) for label, value in rows]
    return [("과제명", info.get("task")), ("기업명", info.get("company")), ("제출일", info.get("date"))]


#: 평가본(11-06 B-3) — 회사를 알아볼 수 있는 칸을 뺐는데 그 절에 남는 칸이 하나도 없을 때만 넣는 자리표(2.10.0 D6).
BLIND_MARK = "(평가본 — 표기하지 않음)"
#: 일반현황 칸 중 회사를 알아볼 수 있는 것(상호 · 대표자 · 사업자번호 · 주소 · 연락처 · 홈페이지 + 설립일 · 주요 연혁 · 2.10.0 D5) —
#: `FIELD_MAP` 의 회사 값 열쇠. 보유 인증 이름 칸은 남긴다(평가에 쓰임 · 식별 여부는 식별 낱말 검사가 알린다).
_BLIND_KEYS = frozenset({"name", "representative", "business_number", "address", "phone", "website", "opened_on", "history"})
_BLIND_COVER = frozenset({"제안사", "기업명"})
#: 등록 · 인증 · 확인 번호(「제2000-123호」 · 「제0000-2000-00000호」 꼴) — 평가본 본문에서 회사자료 번호를 지우고(D5) 식별 검사가 찾는다(D7).
#: 붙임표 없는 법령 번호(「법률 제12345호」)는 아니다.
CERT_NO_RE = re.compile(r"제\s*\d+(?:\s*-\s*\d+)+\s*호")
_CORP = r"(?:주식회사|\(주\)|㈜)"
#: 「당사」 · 「대표」(받침 없음) 뒤 조사 — 받침 있는 이름(「○○21은」)을 지운 자리에 「당사은」이 남지 않게.
#: 긴 꼴(「과의」 · 「이라는」 · 「으로서」 · 「이었」 · 짧은 조사 + 는 · 도 · 만 · 「이랑」)은 뒤에 글이 이어져도 조사다 ·
#: 짧은 꼴은 뒤에 한글이 이어지면(「이며」 · 「이다」) 조사가 아니다. 정규식이 앞에서부터 고르므로 긴 꼴을 먼저 둔다.
_LONG_PARTICLE = {"으로부터": "로부터", "으로서": "로서", "으로써": "로써", "으로는": "로는", "으로도": "로도", "으로만": "로만",
                  "과의": "와의", "과는": "와는", "과도": "와도", "과만": "와만",
                  "이라는": "라는", "이라고": "라고", "이랑": "랑", "이라": "라", "이었": "였"}
_VOWEL_PARTICLE = {"으로": "로", "은": "는", "이": "가", "을": "를", "과": "와"}
_PARTICLE_RE = (rf"(?:({'|'.join(_LONG_PARTICLE)})|({'|'.join(_VOWEL_PARTICLE)})(?![가-힣]))?")


def _loose(name: str) -> str:
    """이름 글자 사이 띄어쓰기를 봐준다(「가나다 21」 · 「가 나 다21」도 같은 이름)."""
    return r"\s?".join(map(re.escape, "".join(name.split())))


def _swap(match: re.Match[str], word: str) -> str:
    return word + _LONG_PARTICLE.get(match.group(1) or "", "") + _VOWEL_PARTICLE.get(match.group(2) or "", "")


def blind_copy(draft: dict[str, Any], meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """평가본 사본 — 제출용과 같은 글에서 회사 식별정보만 뺀다(제안요청서 「업체명 · 로고 · 대표자 표기 금지」).

    - 이름은 회사자료에서 온 값으로 찾는다: 화면 · 내려받기가 붙인 회사 이름(`company_name` · 프로필) · 표지 제안사 칸 ·
      회사자료로 채운 일반현황 기관명 · 대표자 칸(`plan_fill_service`). 「주식회사 ○○」 · 「(주)○○」 · 「○○」 모두 「당사」로,
      대표자 이름(「홍길동 대표가」 · 「대표이사 홍길동은」)은 「대표」로. 영문 이름은 회사자료에 칸이 없어 찾지 못한다(화면 안내).
    - 일반현황의 상호 · 대표자 · 사업자번호 · 주소 · 연락처 · 홈페이지 · 설립일 · 주요 연혁 칸과 표지 제안사 줄은 줄째 뺀다 —
      그 절에 남는 칸이 하나도 없을 때만 칸에 `BLIND_MARK`(2.10.0 D5 · D6 — 예전에는 모두 자리표).
    - 회사자료로 채운 칸 속 등록 · 인증 번호(「제…호」)는 본문 · 표에서도 지운다(감싼 괄호째)."""
    names = {str(draft.get("company_name") or ""), str(meta.get("company") or "")}
    names |= {str(value or "") for label, value in cover_rows(meta) if label in _BLIND_COVER}
    reps: set[str] = set()
    numbers: set[str] = set()
    for section in draft.get("sections") or []:
        for f in section.get("fields") or []:
            key = FIELD_MAP.get(str(f.get("label") or "").strip())
            if f.get("filled_by") == "company" and key in ("name", "representative"):
                (names if key == "name" else reps).add(str(f.get("value") or ""))
            if f.get("filled_by") == "company":
                numbers |= {m.group(0) for m in CERT_NO_RE.finditer(str(f.get("value") or ""))}

    def usable(values: set[str]) -> list[str]:
        return sorted((v for v in values if len("".join(v.split())) >= 2 and v not in ("당사", HUMAN_INPUT, BLIND_MARK)), key=len, reverse=True)

    shorts = usable({re.sub(rf"^{_CORP}\s*|\s*{_CORP}$", "", n.strip()).strip() for n in names})
    reps_ = usable({r.strip() for r in reps})
    company = re.compile(rf"(?:{_CORP}\s*)?(?:{'|'.join(map(_loose, shorts))})(?:\s*{_CORP})?{_PARTICLE_RE}") if shorts else None
    person = (re.compile(rf"(?:대표(?:이사|자)?\s*)?(?:{'|'.join(map(_loose, reps_))})(?:\s*대표(?:이사|자)?)?{_PARTICLE_RE}")
              if reps_ else None)
    alt = "|".join(map(_loose, sorted(numbers, key=len, reverse=True)))
    number = re.compile(rf"\s*\(\s*(?:{alt})\s*\)|\s*(?:{alt})") if numbers else None

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            if company:
                value = company.sub(lambda m: _swap(m, "당사"), value)
            if number:
                value = number.sub("", value)
            return person.sub(lambda m: _swap(m, "대표"), value) if person else value
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(scrub(v) for v in value)
        return value

    out = scrub(draft)
    for section in out.get("sections") or []:
        fields = section.get("fields") or []
        hidden = {str(f.get("label") or "").strip() for f in fields if FIELD_MAP.get(str(f.get("label") or "").strip()) in _BLIND_KEYS}
        if not hidden:
            continue
        kept = [f for f in fields if str(f.get("label") or "").strip() not in hidden]
        if kept:
            section["fields"] = kept
            section["sentences"] = [s for s in section.get("sentences") or [] if str(s.get("text") or "").split(":", 1)[0].strip() not in hidden]
        else:
            for f in fields:
                f.update({"value": BLIND_MARK, "filled_by": None})
    cover = scrub(meta)
    # 표지 제안사 줄은 줄째 뺀다(사업계획서 꼴 표지 — 과제명 · 기업명 · 제출일 — 도 줄 목록으로 바꿔 기업명 줄을 뺀다)
    rows = cover_rows(cover)
    kept_rows = [(label, value) for label, value in rows if label not in _BLIND_COVER]
    cover["rows"] = kept_rows or [(label, BLIND_MARK if label in _BLIND_COVER else value) for label, value in rows]
    cover.pop("company", None)
    return out, cover


#: 표 칸 끝의 검토 표식(「 ⚠ 공고 문장과 거의 같음」 · 「 ⚠ 협약 기간 밖(…)」 · `plan_draft_service._clean_cell`) — 제출용에서는 뺀다(11-03).
_CELL_MARK = re.compile(r"\s*⚠.*$")


def _clean_table(table: dict[str, Any], *, review: bool = True) -> dict[str, Any]:
    """제어문자를 지우고, 연번 칸이 빈칸 표시면 1 · 2 · 3 으로 채운다 — 좁힌 연번 칸에서 「(담당자 입력)」이 옆 칸으로 넘쳤다(31차 R30-39).
    제출용(`review=False`)은 칸 끝의 검토 표식을 뺀다 — 제출용 일정표 칸에 「⚠ 공고 문장과 거의 같음」이 실렸다(11-03)."""
    columns = [_clean(c) for c in table.get("columns") or []]
    serial = [c for c, name in enumerate(columns) if _NARROW_COLUMN.match(name.strip())]
    rows = []
    for index, row in enumerate(table.get("rows") or [], start=1):
        cells = [_clean(cell) if review else _CELL_MARK.sub("", _clean(cell)) for cell in row]
        for c in serial:
            if c < len(cells) and cells[c].strip() in (HUMAN_INPUT, ""):
                cells[c] = str(index)
        rows.append(cells)
    return {**table, "title": _clean(table.get("title")), "columns": columns, "rows": rows}


#: 검토 메모에서 쌍점 앞을 굵게 하는 줄(SPEC §17).
_MEMO_BOLD = re.compile(r"^(점검표|AI 모의 채점|고치지 못한 약점|제출용에서 뺀 문장 · 나중에 내는 서식|담당자가 채울 항목)")


def _memo_blocks(draft: dict[str, Any]) -> list[Block]:
    """검토 메모(검토용만) — 평가위원 채점 · 고치지 못한 약점 · 제출용에서 뺀 문장 · 나중에 내는 서식 · 제출 전 채울 빈칸(표) · 점검표 · 회사자료 자동 채움."""
    out: list[Block] = [("memo_h", "검토 메모 — 제출용 파일에는 없습니다")]
    checklist = draft.get("checklist") or {}
    if checklist.get("summary"):
        out.append(("memo", _clean(f"점검표: {checklist['summary']}"), 0))
    fill = draft.get("company_fill") or {}
    if fill:
        out.append(("memo", _clean(f"회사자료로 채움 {fill.get('filled', 0)}칸 · 회사자료에 입력하면 채워질 칸 {fill.get('fillable', 0)}개"
                                   + (f" ({' · '.join(fill.get('fillable_fields') or [])})" if fill.get("fillable_fields") else "")), 0))
    for score in draft.get("review_scores") or []:
        line = f"AI 모의 채점(실제 심사 아님) — {score.get('eval_item')}: {score.get('grade')} · {score.get('reason')}"
        if score.get("rewritten"):
            line += " (「하」라서 한 번 고쳐 씀)"
        out.append(("memo", _clean(line), 0))
        for fix in score.get("fixes") or []:
            out.append(("memo", _clean(f"고칠 문장({fix.get('section')}): 「{fix.get('sentence')}」 → {fix.get('fix')}"), 1))
    weak, removed = draft.get("review_notes") or [], draft.get("removed_notes") or []
    if draft.get("kind") == "제안서":  # 입찰 제안서 초안의 메모는 앱이 한 정리(뺀 문장 · 나중에 내는 서식)다 — 옛 저장본은 review_notes 에 있다(4차 #7)
        weak, removed = [], [*removed, *weak]
    for head, notes in (("고치지 못한 약점", weak), ("제출용에서 뺀 문장 · 나중에 내는 서식", removed)):
        for note in notes:
            for item in note.get("items") or []:
                out.append(("memo", _clean(f"{head}({note.get('section')}): {item}"), 0))
    blanks = draft.get("blanks") or []
    if blanks:
        out.append(("memo", f"담당자가 채울 항목 {len(blanks)}개:", 0))
        rows = [[str(i), _clean(b.get("section") or ""), _clean(b.get("field") or ""), _clean(b.get("why") or "")] for i, b in enumerate(blanks, start=1)]
        if any(b.get("proof") for b in blanks):  # 채울 때 필요한 자료(2.10.0 m4) — 하나라도 있을 때만 칸을 붙인다(옛 초안 · 사업계획서는 네 칸)
            out.append(("memo_table", {"title": "", "columns": ["번호", "위치", "항목", "이유", "필요한 자료"], "widths_mm": [10, 32, 38, 54, 32],
                                       "rows": [[*row, _clean(b.get("proof") or "")] for row, b in zip(rows, blanks)]}))
        else:
            out.append(("memo_table", {"title": "", "columns": ["번호", "위치", "항목", "이유"], "widths_mm": [12, 40, 50, 64], "rows": rows}))
    if draft.get("llm_note"):
        out.append(("memo", _clean(f"AI 작성 메모: {draft['llm_note']}"), 0))
    return out


# ---------------------------------------------------------------------------
# 그리기 공통 — 표식 · 근거 · 목록 붙임
# ---------------------------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"[^\w]", "", text)


def _source_shown(text: str, sentence_type: Any, source: str | None) -> str | None:
    """검토용 근거 — 공고 · 회사 문장만. 근거가 문장과 같으면(띄어쓰기 · 문장부호 빼고) 뺀다(SPEC §12)."""
    if not source or sentence_type not in (NOTICE, COMPANY) or _squash(source) == _squash(text):
        return None
    return source[:80]


def _list_keep(blocks: list[Block]) -> set[int]:
    """6줄 이하 ○ · - 목록은 마지막 줄을 뺀 모든 줄을 다음 줄과 붙인다(SPEC §16)."""
    keep: set[int] = set()
    k = 0
    while k < len(blocks):
        if blocks[k][0] in ("item", "dash"):
            end = k
            while end + 1 < len(blocks) and blocks[end + 1][0] in ("item", "dash"):
                end += 1
            if end - k + 1 <= 6:
                keep.update(range(k, end))
            k = end + 1
        else:
            k += 1
    return keep


def _list_end(kind: str, nxt: str | None) -> bool:
    """목록 · 라벨 줄의 끝 — 아래 간격 6(아니면 2)."""
    if kind in ("item", "dash"):
        return nxt not in ("item", "dash")
    return kind == "label" and nxt != "label"


def _review_header_notice(meta: dict[str, Any], title: str) -> str:
    notice = re.sub(r"\s+", " ", _clean(meta.get("notice") or title)).strip()
    return notice[:30] + "…" if len(notice) > 30 else notice


def _ai_count(block: Block) -> str:
    """검토용 소항목 제목 옆 「AI 덧붙임 n/m문장」 — n 이 0 이면 빈 글."""
    return f"AI 덧붙임 {block[2]}/{block[3]}문장" if len(block) >= 4 and block[2] else ""


# ---------------------------------------------------------------------------
# DOCX (SPEC §18 — python-docx 1.2.0 · 새 의존성 없음)
# ---------------------------------------------------------------------------

#: pPr 자식 순서(ECMA-376) — 모르는 요소는 이 순서대로 끼운다.
_PPR_ORDER = ["w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl", "w:numPr",
              "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
              "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
              "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
              "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
              "w:sectPr", "w:pPrChange"]
_TBLPR_ORDER = ["w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW",
                "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook"]
#: 표 뒤 간격(pt) — 다음 문단 앞 간격으로 넣는다.
TABLE_AFTER = 9


def _put(parent: Any, tag: str, order: list[str], **attrs: Any) -> Any:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    old = parent.find(qn(tag))
    if old is not None:
        parent.remove(old)
    element = OxmlElement(tag)
    for key, value in attrs.items():
        element.set(qn(f"w:{key}"), str(value))
    parent.insert_element_before(element, *order[order.index(tag) + 1:])
    return element


def _border(ppr: Any, side: str, sz: int, color: str, space: int) -> None:
    """문단 테두리 한 변 — top · left · bottom · right 순서로 부른다."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    borders = ppr.find(qn("w:pBdr"))
    if borders is None:
        borders = _put(ppr, "w:pBdr", _PPR_ORDER)
    edge = OxmlElement(f"w:{side}")
    for key, value in (("val", "single"), ("sz", sz), ("space", space), ("color", color)):
        edge.set(qn(f"w:{key}"), str(value))
    borders.append(edge)


def _fonts(rfonts: Any) -> None:
    """rFonts 네 갈래를 맑은 고딕으로 · 테마 글꼴 속성은 지운다(남으면 테마 글꼴이 이긴다)."""
    from docx.oxml.ns import qn

    for name in list(rfonts.attrib):
        if name.lower().endswith("theme"):
            del rfonts.attrib[name]
    for name in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{name}"), FONT)


def _style(document: Any, name: str, *, size: float | None = None, bold: bool = False, color: str | None = None,
           line: float | None = None, before: float = 0, after: float = 0, align: Any = None, left: int = 0, hanging: int = 0,
           right: int = 0, keep_next: bool = False, keep_lines: bool = False) -> Any:
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt, RGBColor, Twips

    names = {s.name for s in document.styles}
    style = document.styles[name] if name in names else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    if name != "Normal":
        style.base_style = document.styles["Normal"]
    _fonts(style.element.get_or_add_rPr().get_or_add_rFonts())
    if size:
        style.font.size = Pt(size)
    style.font.bold = bold or None
    if color:
        style.font.color.rgb = RGBColor.from_string(color)
    fmt = style.paragraph_format
    if line:
        fmt.line_spacing_rule, fmt.line_spacing = WD_LINE_SPACING.EXACTLY, Pt(line)
    fmt.space_before, fmt.space_after = Pt(before), Pt(after)
    if align is not None:
        fmt.alignment = align
    if left or hanging or right:
        fmt.left_indent, fmt.first_line_indent, fmt.right_indent = Twips(left), Twips(-hanging), Twips(right)
    fmt.keep_with_next = keep_next or None
    fmt.keep_together = keep_lines or None
    return style


def _setup(document: Any) -> None:
    """쪽 · 호환성 · 스타일(SPEC §2~§5 · §18)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH as ALIGN
    from docx.oxml.ns import qn
    from docx.shared import Mm

    for setting in document.settings.element.iter(qn("w:compatSetting")):
        if setting.get(qn("w:name")) == "compatibilityMode":
            setting.set(qn("w:val"), "15")
    styles = document.styles.element
    lang = styles.find(qn("w:docDefaults")).find(".//" + qn("w:lang"))
    if lang is not None:
        lang.set(qn("w:eastAsia"), "ko-KR")
    for rfonts in styles.iter(qn("w:rFonts")):  # 기본값 · 제목 스타일에 남은 테마 글꼴 속성을 모두 지운다
        _fonts(rfonts)
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin, section.bottom_margin, section.left_margin, section.right_margin = Mm(22), Mm(20), Mm(22), Mm(22)
    section.header_distance, section.footer_distance = Mm(12), Mm(10)
    normal = _style(document, "Normal", size=11, color=INK, line=18, after=6, align=ALIGN.JUSTIFY)
    normal.paragraph_format.widow_control = True
    ppr = normal.element.get_or_add_pPr()
    # w:wordWrap 은 넣지 않는다 — 없으면 Word 가 어절 단위로 줄을 바꾼다. val=0 은 「업무/를」처럼 글자 단위로 끊었다(SPEC §0)
    _put(ppr, "w:autoSpaceDE", _PPR_ORDER, val=0)  # 「2026 년」 「링크 21」 자동 빈칸 끄기
    _put(ppr, "w:autoSpaceDN", _PPR_ORDER, val=0)
    h1 = _style(document, "Heading 1", size=15, bold=True, color=NAVY, line=22, before=22, after=8, align=ALIGN.LEFT,
                keep_next=True, keep_lines=True)
    _border(h1.element.get_or_add_pPr(), "bottom", 6, NAVY, 3)
    _style(document, "Heading 2", size=12.5, bold=True, color=NAVY, line=18, before=16, after=6, align=ALIGN.LEFT,
           keep_next=True, keep_lines=True)
    _style(document, "BP 소제목", bold=True, before=10, after=3, align=ALIGN.LEFT, left=TW_GLYPH, hanging=TW_GLYPH, keep_next=True)
    _style(document, "BP 들여쓴 문단", after=6, left=TW_GLYPH)
    _style(document, "BP 항목", after=2, align=ALIGN.LEFT, left=TW_GLYPH, hanging=TW_GLYPH, keep_lines=True)
    _style(document, "BP 하위항목", after=2, align=ALIGN.LEFT, left=TW_GLYPH + TW_DASH, hanging=TW_DASH, keep_lines=True)
    _style(document, "BP 라벨", after=2, align=ALIGN.LEFT, keep_next=True)
    _style(document, "BP 표", size=9.5, line=13, align=ALIGN.LEFT)
    _style(document, "BP 표 제목", size=10, bold=True, color=NAVY, line=14, before=8, after=3, align=ALIGN.CENTER, keep_next=True)
    _style(document, "BP 메모", size=10, line=15, after=3, align=ALIGN.LEFT)
    _style(document, "BP 요약", size=10.5, line=16, align=ALIGN.LEFT, left=80 + TW_DOT, hanging=TW_DOT, right=80,
           keep_next=True, keep_lines=True)
    _style(document, "BP 범례", size=9, line=14, after=1, align=ALIGN.LEFT)
    _style(document, "BP 목차 1", size=11, bold=True, line=18, before=8.5, align=ALIGN.LEFT)
    _style(document, "BP 목차 2", size=10.5, line=16, align=ALIGN.LEFT, left=454)


def apply_document_style(document: Any) -> None:
    """사업계획서와 같은 문서 모양(쪽 · 글꼴 · 제목 · 본문 · SPEC §2~§5)을 다른 DOCX 에도 — 입찰 제안서 내려받기(44차 S9)."""
    _setup(document)


def _hyperlink(paragraph: Any, url: str) -> None:
    """워드 하이퍼링크(외부 주소) — 보이는 글도 주소 그대로 · 10pt 파란 밑줄(표지 「공고 원문」 · 2.9.1)."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run = paragraph.add_run(url)
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor.from_string(LINK_INK)
    run.font.underline = True
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True))
    run._r.addprevious(link)
    link.append(run._r)


def _runs(paragraph: Any, text: str, *, review: bool, bold: bool = False, size: float | None = None, color: str | None = None,
          in_cell: bool = False) -> None:
    """글 한 덩어리 — 「(담당자 입력)」은 제출용 갈색 점선 밑줄 · 검토용 노란 바탕(SPEC §10). 빈칸 안 빈칸은 줄바꿈 안 되는 빈칸.

    **표 칸 안에서는 보통 빈칸**이다(37차 recheck29 EXP-01) — 좁은 칸(성명 22 · 직위 20 · 상태 22mm)에서 줄바꿈 안 되는 빈칸이
    「(담당자 입 / 력)」처럼 글자 단위로 꺾였다. 보통 빈칸이면 「(담당자 / 입력)」 어절 단위로 꺾인다.
    """
    from docx.enum.text import WD_UNDERLINE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    for piece in re.split(f"({re.escape(HUMAN_INPUT)})", text):
        if not piece:
            continue
        blank = piece == HUMAN_INPUT
        run = paragraph.add_run(piece.replace(" ", " ") if blank and not in_cell else piece)
        run.bold = bold or None
        if size:
            run.font.size = Pt(size)
        if blank and not review:
            run.font.color.rgb = RGBColor.from_string(BLANK_INK)
            run.font.underline = WD_UNDERLINE.DOTTED
            run._element.rPr.find(qn("w:u")).set(qn("w:color"), BLANK_LINE)
            continue
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        if blank:
            shading = OxmlElement("w:shd")
            for key, value in (("val", "clear"), ("color", "auto"), ("fill", BLANK_FILL)):
                shading.set(qn(f"w:{key}"), value)
            run._element.get_or_add_rPr().insert_element_before(
                shading, "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath")


def _labeled(paragraph: Any, text: str, *, review: bool, color: str | None) -> None:
    """「라벨: 값」 — 라벨만 굵게. 글자는 그대로 둔다."""
    found = _label_end(text)
    if found:
        _runs(paragraph, text[:found[0]], review=review, bold=True, color=color)
        _runs(paragraph, text[found[0]:], review=review, color=color)
    else:
        _runs(paragraph, text, review=review, color=color)


def _mm_tw(widths_mm: list[float]) -> list[int]:
    widths = [round(w / 25.4 * 1440) for w in widths_mm]
    widths[-1] += TEXT_TW - sum(widths)
    return widths


def _cell_fill(cell: Any, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shading = OxmlElement("w:shd")
    for key, value in (("val", "clear"), ("color", "auto"), ("fill", fill)):
        shading.set(qn(f"w:{key}"), value)
    cell._tc.get_or_add_tcPr().insert_element_before(shading, "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark")


def _table_frame(table: Any, widths_tw: list[int], *, header: bool, borders: str = "data", margins: tuple[int, int] = (68, 91)) -> None:
    """표 틀 — 고정 너비(gridCol = tcW) · 선 · 칸 안 여백 · 모든 행 나눔 방지 · 머리 행 반복(SPEC §9)."""
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Twips
    from docx.table import _Cell

    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblpr = table._tbl.tblPr
    _put(tblpr, "w:tblW", _TBLPR_ORDER, w=sum(widths_tw), type="dxa")
    if borders != "none":
        edges = _put(tblpr, "w:tblBorders", _TBLPR_ORDER)
        top = NAVY if borders == "data" else RULE
        top_sz = 8 if borders == "data" else 6
        inner = 4 if borders == "data" else 6
        for side, sz, color in (("top", top_sz, top), ("left", inner, RULE), ("bottom", inner, RULE), ("right", inner, RULE),
                                ("insideH", inner, RULE), ("insideV", inner, RULE)):
            edge = OxmlElement(f"w:{side}")
            for key, value in (("val", "single"), ("sz", sz), ("space", 0), ("color", color)):
                edge.set(qn(f"w:{key}"), str(value))
            edges.append(edge)
    _put(tblpr, "w:tblLayout", _TBLPR_ORDER, type="fixed")
    cell_margins = _put(tblpr, "w:tblCellMar", _TBLPR_ORDER)
    for side, width in (("top", margins[0]), ("left", margins[1]), ("bottom", margins[0]), ("right", margins[1])):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:w"), str(width))
        edge.set(qn("w:type"), "dxa")
        cell_margins.append(edge)
    for column, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths_tw):
        column.set(qn("w:w"), str(width))
    for r, tr in enumerate(table._tbl.tr_lst):
        trpr = tr.get_or_add_trPr()
        trpr.insert_element_before(OxmlElement("w:cantSplit"), "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden",
                                   "w:ins", "w:del", "w:trPrChange")
        if header and r == 0:
            trpr.insert_element_before(OxmlElement("w:tblHeader"), "w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del", "w:trPrChange")
        column = 0
        for tc in tr.tc_lst:
            span = tc.grid_span
            cell = _Cell(tc, table)
            cell.width = Twips(sum(widths_tw[column:column + span]))
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            column += span


def _page_number(paragraph: Any) -> None:
    """바닥글 「- n -」 — PAGE 필드만(NUMPAGES 는 뺀다 · SPEC §15)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    def run(text: str = "", field: str | None = None, code: str | None = None) -> None:
        r = paragraph.add_run(text)
        r.font.size, r.font.color.rgb = Pt(9), RGBColor.from_string(MUTED)
        if field:
            element = OxmlElement("w:fldChar")
            element.set(qn("w:fldCharType"), field)
            r._r.append(element)
        if code:
            element = OxmlElement("w:instrText")
            element.set(qn("xml:space"), "preserve")
            element.text = code
            r._r.append(element)

    run("- ")
    run(field="begin")
    run(code=" PAGE ")
    run(field="separate")
    run("2")
    run(field="end")
    run(" -")


def build_docx(draft: dict[str, Any], form: dict[str, Any], *, title: str, variant: Variant = "review", meta: dict[str, Any] | None = None) -> bytes:
    """디자인한 DOCX 한 벌 — 제출용 · 검토용(29차 §3-D · 36차 §3-F). 줄 간격 고정 · 빈 문단으로 띄우지 않는다."""
    from docx import Document
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    from docx.enum.text import WD_ALIGN_PARAGRAPH as ALIGN
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, Twips

    meta = {"notice": title, **(meta or {})}
    review = variant == "review"
    document = Document()
    # 입찰 제출용은 품질 게이트 이름(「초안」 · 「제출용」 · 2.7.0)을 따른다 — meta["file_label"]
    document.core_properties.title = f"{_clean(title)} ({meta.get('file_label') or VARIANT_LABELS[variant]})"
    if variant == "blind":  # 평가본 — 문서 정보 지은이 · 메모도 비운다(회사 칸 app.xml Company 는 처음부터 비어 있다)
        document.core_properties.author = document.core_properties.last_modified_by = document.core_properties.comments = ""
    _setup(document)
    section = document.sections[0]
    section.different_first_page_header_footer = True  # 표지에는 머리말 · 바닥글이 없다
    foot = section.footer.paragraphs[0]
    foot.alignment = ALIGN.CENTER
    _page_number(foot)
    if review:  # 제출용은 머리말 없음(공식 양식에도 없다 · SPEC §15)
        head = section.header.paragraphs[0]
        head.alignment = ALIGN.LEFT
        for position in (4680, 9360):  # 「Header」 스타일이 물려주는 가운데 · 오른쪽 탭을 지운다
            head.paragraph_format.tab_stops.add_tab_stop(Twips(position), WD_TAB_ALIGNMENT.CLEAR)
        head.paragraph_format.tab_stops.add_tab_stop(Twips(TEXT_TW), WD_TAB_ALIGNMENT.RIGHT)
        _runs(head, REVIEW_HEADER, review=True, bold=True, size=8.5, color=WARN)
        _runs(head, "\t" + _review_header_notice(meta, title), review=True, size=8.5, color=MUTED)

    blocks = document_blocks(draft, form, variant=variant, meta=meta)
    keep = _list_keep(blocks)
    state: dict[str, Any] = {"prev": None, "new_page": False}  # prev: 앞 블록 아래 간격(pt) · "table" · None(쪽 맨 위)

    def paragraph(style: str | None, before: float, after: float | None = None) -> Any:
        """새 문단 — 앞 간격은 max(0, 위 간격 − 앞 블록 아래 간격) · 표 뒤는 max(위 간격, 9) · 쪽 맨 위는 0(SPEC §4)."""
        p = document.add_paragraph(style=style)
        prev = state["prev"]
        if state["new_page"]:
            p.paragraph_format.page_break_before = True
            state["new_page"] = False
            space = 0.0
        elif prev == "table":
            space = max(before, TABLE_AFTER)
        elif prev is None:
            space = before
        else:
            space = max(0.0, before - prev)
        p.paragraph_format.space_before = Pt(space)
        if after is not None:
            p.paragraph_format.space_after = Pt(after)
        return p

    def ai_bar(p: Any, leftmost_tw: int) -> None:
        # 검토용 AI 덧붙임 — 글 왼쪽 선 바깥 3.5mm(10pt)에 2pt 회색 줄. space(pt) = 가장 왼쪽 들여쓰기 + 10(SPEC §12)
        _border(p._p.get_or_add_pPr(), "left", 16, AI_BAR, round(leftmost_tw / 20) + 10)

    def tagged(p: Any, sentence_type: Any) -> None:
        mark = TYPE_MARKS.get(sentence_type) if review else None
        if mark:
            _runs(p, f"[{mark}] ", review=True, bold=True, size=8, color=NAVY)

    def sourced(p: Any, text: str, sentence_type: Any, source: str | None) -> None:
        shown = _source_shown(text, sentence_type, source) if review else None
        if shown:
            _runs(p, f" (근거: {shown})", review=True, size=8.5, color=MUTED)

    def new_table(rows: int, cols: int, widths_tw: list[int], *, header: bool, borders: str = "data",
                  margins: tuple[int, int] = (68, 91)) -> Any:
        table = document.add_table(rows=rows, cols=cols)
        _table_frame(table, widths_tw, header=header, borders=borders, margins=margins)
        if state["new_page"]:  # 쪽 첫 블록이 표 — 첫 행 문단에 쪽 나눔(Word 는 첫 행의 「앞에서 쪽 나눔」을 따른다)
            table.rows[0].cells[0].paragraphs[0].paragraph_format.page_break_before = True
            state["new_page"] = False
        return table

    def cell_paragraph(cell: Any, *, align: Any = ALIGN.LEFT) -> Any:
        p = cell.paragraphs[0]
        p.style = document.styles["BP 표"]
        p.alignment = align
        return p

    def data_table(table: dict[str, Any]) -> None:
        if table.get("title"):
            caption = paragraph("BP 표 제목", 8)
            _runs(caption, f"< {table['title']} >", review=review)
        columns, rows = table["columns"], table["rows"]
        widths = _mm_tw(table.get("widths_mm") or column_mm(columns))
        grid = new_table(1 + len(rows), len(columns), widths, header=True)
        whole = len(rows) <= 6  # 본문 6행 이하 표는 통째로 한 쪽에
        for c, column in enumerate(columns):
            cell = grid.rows[0].cells[c]
            _cell_fill(cell, HEAD_FILL)
            p = cell_paragraph(cell, align=ALIGN.CENTER)
            p.paragraph_format.keep_with_next = True
            _runs(p, column, review=review, bold=True)
        for r, row in enumerate(rows, start=1):
            for c, column in enumerate(columns):
                value = str(row[c]) if c < len(row) else ""
                align = {"c": ALIGN.CENTER, "r": ALIGN.RIGHT}.get(cell_align(column, value), ALIGN.LEFT)
                p = cell_paragraph(grid.rows[r].cells[c], align=align)
                if whole and r < len(rows):
                    p.paragraph_format.keep_with_next = True
                _runs(p, value, review=review, color=NAVY if value == "■" else None, in_cell=True)
        state["prev"] = "table"

    def fields_table(fields: list[tuple[str, str, str]]) -> None:
        rows = field_rows(fields)
        grid = new_table(len(rows), 4, _mm_tw([30, 53, 30, 53]), header=False)
        # 「기업 현황」 제목과 첫 줄만 쪽 끝에 남지 않게 — 0행은 1행과 함께, 8행 이하는 통째로 한 쪽에(37차 recheck29 EXP-02)
        keep_rows = len(rows) - 1 if len(rows) <= FIELDS_WHOLE_ROWS else 1
        for r, row in enumerate(rows):
            if len(row) == 1:
                grid.rows[r].cells[1].merge(grid.rows[r].cells[3])
            for i, (label, value, origin) in enumerate(row):
                cells = grid.rows[r].cells
                th, td = cells[i * 2], cells[i * 2 + 1]
                _cell_fill(th, HEAD_FILL)
                _runs(cell_paragraph(th, align=ALIGN.CENTER), label, review=review, bold=True)
                photo = _photo_field(label, value)
                p = cell_paragraph(td, align=ALIGN.CENTER if photo else ALIGN.LEFT)
                if photo:  # 사진 칸 — 높이 최소 50mm(SPEC §8)
                    grid.rows[r].height, grid.rows[r].height_rule = Mm(50), WD_ROW_HEIGHT_RULE.AT_LEAST
                for j, item in enumerate(split_items(value)):
                    if j:
                        p.add_run().add_break()
                    _runs(p, item, review=review, in_cell=True)
                if review and origin == "company":
                    _runs(p, " [회사자료]", review=True, size=8, color=MUTED)
            if r < keep_rows:
                for cell in grid.rows[r].cells:
                    for para in cell.paragraphs:
                        para.paragraph_format.keep_with_next = True
        state["prev"] = "table"

    def photo_table(text: str) -> None:
        grid = new_table(1, 1, [TEXT_TW], header=False)
        grid.rows[0].height, grid.rows[0].height_rule = Mm(50), WD_ROW_HEIGHT_RULE.AT_LEAST
        _runs(cell_paragraph(grid.rows[0].cells[0], align=ALIGN.CENTER), text, review=review)
        state["prev"] = "table"

    def cover(info: dict[str, Any]) -> None:
        p = paragraph(None, 150, 34)
        p.alignment = ALIGN.CENTER
        p.paragraph_format.line_spacing = Pt(34)
        _runs(p, _clean(info.get("kind") or "사업계획서"), review=review, bold=True, size=26, color=NAVY)
        for run in p.runs:  # 자간 6pt
            spacing = OxmlElement("w:spacing")
            spacing.set(qn("w:val"), "120")
            run._element.get_or_add_rPr().insert_element_before(
                spacing, "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd",
                "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath")
        p = paragraph(None, 0, 0)  # 공고명 띠 — 폭 150mm · 위아래 1pt 남색 선
        p.alignment = ALIGN.CENTER
        p.paragraph_format.left_indent = p.paragraph_format.right_indent = Mm(8)
        p.paragraph_format.line_spacing = Pt(22)
        ppr = p._p.get_or_add_pPr()
        _border(ppr, "top", 8, NAVY, 8)
        _border(ppr, "bottom", 8, NAVY, 8)
        _runs(p, info.get("notice") or _clean(title), review=review, bold=True, size=14)
        rows = cover_rows(info)
        link = cover_link(info)
        link_lines = -(-len(link[1]) // LINK_LINE_CHARS) if link else 0
        meta_table = document.add_table(rows=len(rows) + bool(link), cols=2)
        _table_frame(meta_table, [1701, 5102], header=False, borders="none", margins=(0, 0))
        for r, (label, value) in enumerate(rows):
            value = _clean(value) if value else None
            a, b = meta_table.rows[r].cells
            pa, pb = a.paragraphs[0], b.paragraphs[0]
            for q in (pa, pb):
                q.paragraph_format.line_spacing, q.paragraph_format.space_after = Pt(24), Pt(0)
                # 쪽 바닥에서 약 30mm 위 — 0행 두 칸 모두(한 칸에만 주면 값이 줄 위쪽에 붙는다 · SPEC §13)
                q.paragraph_format.space_before = Pt(250 - link_lines * LINK_LINE_PT if r == 0 else 0)
            pa.alignment, pb.alignment = ALIGN.RIGHT, ALIGN.LEFT
            pa.paragraph_format.right_indent = Mm(5)  # 이름과 값 사이 5mm(HTML 의 th 오른쪽 여백과 같다)
            _runs(pa, label, review=review, size=11, color=MUTED)
            _runs(pb, value or HUMAN_INPUT, review=review, bold=True, size=12)
        if link:  # 「공고 원문」 — 10pt 파란 밑줄 하이퍼링크(주소 글자 그대로 · 인쇄본에서도 보이게)
            a, b = meta_table.rows[len(rows)].cells
            pa, pb = a.paragraphs[0], b.paragraphs[0]
            for q in (pa, pb):
                q.paragraph_format.line_spacing, q.paragraph_format.space_after = Pt(LINK_LINE_PT), Pt(0)
                q.paragraph_format.space_before = Pt(4)
            pa.alignment, pb.alignment = ALIGN.RIGHT, ALIGN.LEFT
            pa.paragraph_format.right_indent = Mm(5)
            _runs(pa, link[0], review=review, size=11, color=MUTED)
            _hyperlink(pb, link[1])
        state["prev"] = "table"
        if review:  # 붉은 상자 「검토용 — 제출하지 마세요」
            p = paragraph(None, 28, 0)
            p.alignment = ALIGN.CENTER
            p.paragraph_format.left_indent = p.paragraph_format.right_indent = Mm(45)
            ppr = p._p.get_or_add_pPr()
            for side, space in (("top", 6), ("left", 17), ("bottom", 6), ("right", 17)):
                _border(ppr, side, 8, WARN, space)
            _runs(p, "검토용 — 제출하지 마세요", review=True, bold=True, size=12, color=WARN)
        state["new_page"] = True

    def legend() -> None:
        grid = new_table(1, 1, [TEXT_TW], header=False, borders="box", margins=(170, 227))
        cell = grid.rows[0].cells[0]
        first = cell.paragraphs[0]
        first.style = document.styles["BP 범례"]
        _runs(first, "검토용 — 제출하지 마세요", review=True, bold=True, color=WARN)
        bar = cell.add_paragraph(style="BP 범례")
        bar.paragraph_format.left_indent = Twips(170)
        _border(bar._p.get_or_add_pPr(), "left", 16, AI_BAR, 5)
        _runs(bar, "왼쪽 회색 줄 · 회색 글자 — AI가 덧붙인 문장(근거 확인 후 고쳐 쓰기)", review=True, color=AI_INK)
        tags = cell.add_paragraph(style="BP 범례")
        _runs(tags, "[공고] [회사]", review=True, bold=True, size=8, color=NAVY)
        _runs(tags, " — 공고 · 회사 근거가 있는 문장, 뒤에 (근거: …)", review=True)
        blank = cell.add_paragraph(style="BP 범례")
        _runs(blank, HUMAN_INPUT, review=True)
        _runs(blank, " — 담당자가 채웁니다", review=True)
        state["prev"] = "table"

    def toc(entries: list[tuple[int, str]]) -> None:
        heading = paragraph(None, max(TABLE_AFTER, 14), 6)
        heading.alignment = ALIGN.LEFT
        heading.paragraph_format.line_spacing = Pt(18)
        heading.paragraph_format.keep_with_next = True
        _runs(heading, "목차", review=True, bold=True, size=12.5, color=NAVY)
        state["prev"] = 6
        for level, text in entries:
            p = paragraph("BP 목차 1" if level == 1 else "BP 목차 2", 8.5 if level == 1 else 0, 0)
            _runs(p, text, review=True)
            state["prev"] = 0
        state["new_page"] = True

    def text_block(index: int, block: Block, nxt: str | None) -> None:
        kind, sentences, depth = block
        text, sentence_type, source = sentences[0]
        ai = review and sentence_type == SUGGESTION and kind != "sub"
        color = AI_INK if ai else None
        end = _list_end(kind, nxt)
        if kind == "sub":  # ○ 소제목 — 표식 없음 · 소항목 바로 뒤는 위 간격 0
            p = paragraph("BP 소제목", 0 if state["prev_kind"] == "h2" else 10)
            _runs(p, text, review=review)
            state["prev"] = 3
            return
        if kind == "item":
            glyph = _GLYPH.match(text)
            p = paragraph("BP 항목", 0, 6 if end else None)
            _runs(p, glyph.group(1) + " ", review=review, color=color)
            tagged(p, sentence_type)
            _labeled(p, text[glyph.end():], review=review, color=color)
            leftmost = 0
        elif kind == "dash":
            dash = _DASH.match(text)
            p = paragraph("BP 하위항목", 0, 6 if end else None)
            _runs(p, dash.group(1) + " ", review=review, color=color)
            tagged(p, sentence_type)
            _runs(p, text[dash.end():], review=review, color=color)
            leftmost = TW_GLYPH
        elif kind == "label":
            p = paragraph("BP 라벨", 0, 6 if end else None)
            if depth:
                p.paragraph_format.left_indent = Twips(TW_GLYPH)
            tagged(p, sentence_type)
            _labeled(p, text, review=review, color=color)
            leftmost = TW_GLYPH if depth else 0
        else:
            p = paragraph("BP 들여쓴 문단" if depth else None, 0)
            tagged(p, sentence_type)
            for i, (line, line_type, line_source) in enumerate(sentences):
                _runs(p, (" " if i else "") + line, review=review, color=color)
                sourced(p, line, line_type, line_source)
            leftmost = TW_GLYPH if depth else 0
        if kind != "para":
            sourced(p, text, sentence_type, source)
        if index in keep:
            p.paragraph_format.keep_with_next = True
        if ai:
            ai_bar(p, leftmost)
        state["prev"] = 6 if (kind == "para" or end) else 2

    state["prev_kind"] = None
    k = 0
    while k < len(blocks):
        block = blocks[k]
        kind = block[0]
        nxt = blocks[k + 1][0] if k + 1 < len(blocks) else None
        if kind == "field":  # 이어진 칸들을 표 하나로(SPEC §8)
            end = k
            while end + 1 < len(blocks) and blocks[end + 1][0] == "field":
                end += 1
            fields_table([b[1:4] for b in blocks[k:end + 1]])
            state["prev_kind"] = "field"
            k = end + 1
            continue
        if kind == "cover":
            cover(block[1])
        elif kind == "legend":
            legend()
        elif kind == "toc":
            toc(block[1])
        elif kind == "h1":
            p = paragraph("Heading 1", 22)
            _runs(p, block[1], review=review)
            state["prev"] = 8
        elif kind == "h2":
            p = paragraph("Heading 2", 8 if state["prev_kind"] == "h1" else 16)
            _runs(p, block[1], review=review)
            count = _ai_count(block) if review else ""
            if count:
                _runs(p, "  " + count, review=True, size=8.5, color=MUTED)
                p.runs[-1].bold = False
            state["prev"] = 6
        elif kind == "summary":
            lines = block[1]
            box = [("핵심 요약(본문 첫 문장 자동 발췌)", True)] + [(f"· {line}", False) for line in lines]
            for i, (line, is_title) in enumerate(box):
                p = paragraph("BP 요약", 0, 0)
                ppr = p._p.get_or_add_pPr()
                for side, space in (("top", 7), ("left", 10), ("bottom", 7), ("right", 10)):
                    _border(ppr, side, 6, RULE, space)
                shading = OxmlElement("w:shd")
                for key, value in (("val", "clear"), ("color", "auto"), ("fill", BOX_FILL)):
                    shading.set(qn(f"w:{key}"), value)
                ppr.insert_element_before(shading, *_PPR_ORDER[_PPR_ORDER.index("w:shd") + 1:])
                if i == len(box) - 1:
                    p.paragraph_format.keep_with_next = False
                if is_title:
                    _runs(p, line, review=True, bold=True, size=9, color=NAVY)
                else:
                    _runs(p, line, review=True)
                state["prev"] = 0
        elif kind in TEXT_KINDS:
            text_block(k, block, nxt)
        elif kind == "photo":
            photo_table(block[1])
        elif kind in ("table", "memo_table"):
            data_table(block[1])
        elif kind == "memo_h":
            state["new_page"] = True
            p = paragraph("Heading 1", 0)
            _runs(p, block[1], review=True)
            state["prev"] = 8
        elif kind == "memo":
            _, text, depth = block
            p = paragraph("BP 메모", 0)
            if depth:
                p.paragraph_format.left_indent = Twips(TW_MEMO)
            found = next((i for i, ch in _outside(text) if ch in ":："), None) if _MEMO_BOLD.match(text) else None
            if found is not None:
                _runs(p, text[:found + 1], review=True, bold=True)
                _runs(p, text[found + 1:], review=True)
            else:
                _runs(p, text, review=True)
            state["prev"] = 3
        state["prev_kind"] = kind
        k += 1
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# HTML (→ PDF) — DOCX 와 같은 블록 · 같은 숫자 (SPEC §19)
# ---------------------------------------------------------------------------

_BLANK_HTML = html.escape(HUMAN_INPUT)
#: 빈칸 바로 뒤 한두 글자(원 · % · 명 · 곳 · 년 · 조사)는 빈칸과 한 덩어리 — 「원」 한 글자만 다음 줄로 넘어가지 않게(SPEC §10).
_NB_RE = re.compile(re.escape(_BLANK_HTML) + r"([^\s(<&]{1,2})(?=[\s,.)」]|$)")


def _h(text: Any) -> str:
    """HTML 글 — 「(담당자 입력)」 조각은 `span.blank`(제출용 점선 밑줄 · 검토용 노란 바탕)."""
    out = html.escape(_clean(text))
    mark = f'<span class="blank">{_BLANK_HTML}</span>'
    out = _NB_RE.sub(lambda m: f'<span class="nb">{mark}{m.group(1)}</span>', out)
    return re.sub(re.escape(_BLANK_HTML) + r"(?!</span>)", mark, out)


def _h_labeled(text: str) -> str:
    found = _label_end(text)
    return f"<b>{_h(text[:found[0]])}</b>{_h(text[found[0]:])}" if found else _h(text)


def _css(review: bool, notice: str) -> str:
    left = "18mm" if review else "22mm"
    first_head = "@top-left { content: none; } @top-right { content: none; } " if review else ""
    head = (f'@top-left {{ content: "{_css_string(REVIEW_HEADER)}"; padding-left: 4mm; font-family: {CSS_FONTS}; font-size: 8.5pt; '
            f'font-weight: 700; color: #{WARN}; }}\n  @top-right {{ content: "{_css_string(notice)}"; font-family: {CSS_FONTS}; '
            f'font-size: 8.5pt; color: #{MUTED}; }}' if review else "")
    return f"""
@page {{ size: A4; margin: 22mm 22mm 20mm {left};
  {head}
  @bottom-center {{ content: "- " counter(page) " -"; font-family: {CSS_FONTS}; font-size: 9pt; color: #{MUTED}; }} }}
@page :first {{ {first_head}@bottom-center {{ content: none; }} }}
html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
body {{ margin: 0; padding-left: {"4mm" if review else "0"}; font-family: {CSS_FONTS}; font-size: 11pt; line-height: 18pt; color: #{INK};
  word-break: keep-all; overflow-wrap: anywhere; }}
.cover {{ display: flex; flex-direction: column; align-items: center; text-align: center; min-height: 255mm; break-after: page; }}
.cover .kind {{ margin: 55mm 0 12mm; padding-left: 6pt; font-size: 26pt; line-height: 34pt; font-weight: 700; color: #{NAVY}; letter-spacing: 6pt; }}
.cover .notice {{ box-sizing: border-box; width: 150mm; margin: 0; padding: 8pt 4mm; border-top: 1pt solid #{NAVY}; border-bottom: 1pt solid #{NAVY};
  font-size: 14pt; line-height: 22pt; font-weight: 700; text-align: center; }}
.cover .meta {{ margin: auto 0 {"0" if review else "30mm"}; border-collapse: collapse; }}
.cover .meta th {{ width: 30mm; padding: 0 5mm 0 0; text-align: right; font-size: 11pt; line-height: 24pt; font-weight: 400; color: #{MUTED}; }}
.cover .meta td {{ width: 90mm; text-align: left; font-size: 12pt; line-height: 24pt; font-weight: 700; }}
.cover .meta tr.link th, .cover .meta tr.link td {{ vertical-align: top; padding-top: 4pt; line-height: {LINK_LINE_PT}pt; }}
.cover .meta tr.link td {{ font-size: 10pt; font-weight: 400; word-break: break-all; }}
.cover .meta tr.link a {{ color: #{LINK_INK}; text-decoration: underline; }}
.cover .flag {{ margin: 10mm 0 12mm; padding: 2mm 6mm; border: 1pt solid #{WARN}; color: #{WARN}; font-size: 12pt; line-height: 18pt; font-weight: 700; }}
.pb {{ break-before: page; margin-top: 0 !important; }}
h1 {{ margin: 22pt 0 8pt; padding-bottom: 3pt; border-bottom: 0.75pt solid #{NAVY}; font-size: 15pt; line-height: 22pt; color: #{NAVY};
  break-after: avoid; break-inside: avoid; }}
h2 {{ margin: 16pt 0 6pt; font-size: 12.5pt; line-height: 18pt; color: #{NAVY}; break-after: avoid; break-inside: avoid; }}
h1 + h2 {{ margin-top: 8pt; }}
p {{ margin: 0 0 6pt; orphans: 2; widows: 2; }}
p.para {{ text-align: justify; text-justify: inter-word; }}
p.in {{ margin-left: 5.25mm; }}
p.sub {{ margin: 10pt 0 3pt; font-weight: 700; padding-left: 5.25mm; text-indent: -5.25mm; break-after: avoid; }}
h2 + p.sub {{ margin-top: 0; }}
p.item {{ margin-bottom: 2pt; padding-left: 5.25mm; text-indent: -5.25mm; break-inside: avoid; }}
p.dash {{ margin-bottom: 2pt; padding-left: 8.21mm; text-indent: -2.96mm; break-inside: avoid; }}
p.label {{ margin-bottom: 2pt; break-after: avoid; }}
p.end {{ margin-bottom: 6pt; }}
p.kn {{ break-after: avoid; }}
.blank {{ color: #{BLANK_INK}; text-decoration: underline dotted #{BLANK_LINE}; text-decoration-thickness: 0.6pt; text-underline-offset: 2.5pt;
  display: inline-block; }}
.nb {{ display: inline-block; }}
.blank, .nb {{ text-indent: 0; }}
body.review .blank {{ color: inherit; background: #{BLANK_FILL}; text-decoration: none; padding: 0 0.5mm; }}
figure.tbl {{ margin: 8pt 0 9pt; }}
figure.keep {{ break-inside: avoid; }}
figcaption {{ margin-bottom: 3pt; font-size: 10pt; line-height: 14pt; font-weight: 700; color: #{NAVY}; text-align: center; break-after: avoid; }}
table.data, table.fields, table.photo {{ width: 166mm; max-width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 9.5pt;
  line-height: 13pt; border-top: 1pt solid #{NAVY}; }}
table.data th, table.data td, table.fields th, table.fields td, table.photo td {{ border: 0.5pt solid #{RULE}; padding: 1.2mm 1.6mm;
  vertical-align: middle; word-break: keep-all; overflow-wrap: anywhere; }}
table.data thead th, table.fields th {{ background: #{HEAD_FILL}; font-weight: 700; text-align: center; }}
table.data tr, table.fields tr {{ break-inside: avoid; }}
table.data thead {{ display: table-header-group; }}
td.c {{ text-align: center; }} td.r {{ text-align: right; }} td.mark {{ color: #{NAVY}; }}
table.fields, table.photo {{ margin: 0 0 9pt; }}
table.fields td.photo, table.photo td {{ height: 50mm; text-align: center; }}
.legend {{ margin: 0 0 10pt; padding: 3mm 4mm; border: 0.75pt solid #{RULE}; font-size: 9pt; line-height: 14pt; }}
.legend p {{ margin: 0 0 1pt; }}
.legend .legend-title {{ font-weight: 700; color: #{WARN}; }}
.legend .ai-sample {{ color: #{AI_INK}; }}
.sw.bar {{ display: inline-block; width: 2pt; height: 10pt; margin: 0 2mm -1pt 0; background: #{AI_BAR}; }}
.tag {{ font-size: 8pt; font-weight: 700; color: #{NAVY}; }}
.src {{ font-size: 8.5pt; color: #{MUTED}; }}
.count {{ margin-left: 3mm; font-size: 8.5pt; font-weight: 400; color: #{MUTED}; }}
p.ai {{ color: #{AI_INK}; position: relative; }}
p.ai::before {{ content: ""; position: absolute; left: -3.5mm; top: 2pt; bottom: 2pt; width: 2pt; background: #{AI_BAR}; }}
p.in.ai::before {{ left: calc(-5.25mm - 3.5mm); }}
.summary {{ margin: 0; padding: 2.5mm 3.5mm; background: #{BOX_FILL}; border: 0.75pt solid #{RULE}; font-size: 10.5pt; line-height: 16pt;
  break-inside: avoid; }}
.summary p {{ margin: 0; padding-left: 2.21mm; text-indent: -2.21mm; }}
.summary .summary-title {{ font-size: 9pt; font-weight: 700; color: #{NAVY}; }}
.toc-title {{ margin: 14pt 0 6pt; font-size: 12.5pt; line-height: 18pt; font-weight: 700; color: #{NAVY}; break-after: avoid; }}
.toc1 {{ margin: 8.5pt 0 0; font-size: 11pt; line-height: 18pt; font-weight: 700; }}
.toc2 {{ margin: 0 0 0 8mm; font-size: 10.5pt; line-height: 16pt; }}
p.memo {{ margin: 0 0 3pt; font-size: 10pt; line-height: 15pt; }}
p.memo.in {{ margin-left: 6mm; }}
"""


def build_html(draft: dict[str, Any], form: dict[str, Any], *, title: str, variant: Variant = "submit", meta: dict[str, Any] | None = None) -> str:
    """PDF 로 찍을 HTML 한 장(29차 §3-D · 36차 §3-F). 머리말 · 쪽 번호는 CSS 쪽 여백 상자(@page)로."""
    meta = {"notice": title, **(meta or {})}
    review = variant == "review"
    blocks = document_blocks(draft, form, variant=variant, meta=meta)
    keep = _list_keep(blocks)
    parts: list[str] = []
    new_page = False

    def page_class() -> str:
        nonlocal new_page
        if new_page:
            new_page = False
            return " pb"
        return ""

    def cls(name: str = "") -> str:
        value = (name + page_class()).strip()
        return f' class="{value}"' if value else ""

    def tag(sentence_type: Any) -> str:
        mark = TYPE_MARKS.get(sentence_type) if review else None
        return f'<span class="tag">[{mark}]</span> ' if mark else ""

    def src(text: str, sentence_type: Any, source: str | None) -> str:
        shown = _source_shown(text, sentence_type, source) if review else None
        return f' <span class="src">(근거: {html.escape(shown)})</span>' if shown else ""

    def table_html(table: dict[str, Any]) -> str:
        columns, rows = table["columns"], table["rows"]
        widths = table.get("widths_mm") or column_mm(columns)
        cols = "".join(f'<col style="width:{w:.1f}mm">' for w in widths)
        head = "".join(f"<th>{_h(c)}</th>" for c in columns)
        body = []
        for row in rows:
            cells = []
            for c, column in enumerate(columns):
                value = str(row[c]) if c < len(row) else ""
                classes = " ".join(x for x in (cell_align(column, value), "mark" if value == "■" else "") if x)
                cells.append(f'<td class="{classes}">{_h(value)}</td>' if classes else f"<td>{_h(value)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        caption = f"<figcaption>&lt; {_h(table['title'])} &gt;</figcaption>" if table.get("title") else ""
        whole = " keep" if len(rows) <= 6 else ""
        return (f'<figure class="tbl{whole}{page_class()}">{caption}<table class="data"><colgroup>{cols}</colgroup>'
                f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></figure>")

    def fields_html(fields: list[tuple[str, str, str]]) -> str:
        rows = []
        for row in field_rows(fields):
            cells = []
            for label, value, origin in row:
                shown = "<br>".join(_h(item) for item in split_items(value))
                if review and origin == "company":
                    shown += ' <span class="src">[회사자료]</span>'
                span = "" if len(row) == 2 else ' colspan="3"'
                photo = ' class="photo"' if _photo_field(label, value) else ""
                cells.append(f"<th>{_h(label)}</th><td{span}{photo}>{shown}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return (f'<table class="fields{page_class()}"><colgroup><col style="width:30mm"><col style="width:53mm"><col style="width:30mm">'
                '<col style="width:53mm"></colgroup><tbody>' + "".join(rows) + "</tbody></table>")

    def text_html(index: int, block: Block, nxt: str | None) -> str:
        kind, sentences, depth = block
        text, sentence_type, source = sentences[0]
        if kind == "sub":
            return f"<p{cls('sub')}>{_h(text)}</p>"
        ai = review and sentence_type == SUGGESTION
        classes = [kind]
        if depth and kind in ("para", "label"):
            classes.append("in")
        if _list_end(kind, nxt):
            classes.append("end")
        if index in keep:
            classes.append("kn")
        if ai:
            classes.append("ai")
        attr = cls(" ".join(classes))
        if kind == "item":
            glyph = _GLYPH.match(text)
            inner = f"{glyph.group(1)} {tag(sentence_type)}{_h_labeled(text[glyph.end():])}{src(text, sentence_type, source)}"
        elif kind == "dash":
            dash = _DASH.match(text)
            inner = f"{_h(dash.group(1))} {tag(sentence_type)}{_h(text[dash.end():])}{src(text, sentence_type, source)}"
        elif kind == "label":
            inner = f"{tag(sentence_type)}{_h_labeled(text)}{src(text, sentence_type, source)}"
        else:
            inner = tag(sentence_type) + " ".join(f"{_h(line)}{src(line, line_type, line_source)}" for line, line_type, line_source in sentences)
        return f"<p{attr}>{inner}</p>"

    k = 0
    while k < len(blocks):
        block = blocks[k]
        kind = block[0]
        nxt = blocks[k + 1][0] if k + 1 < len(blocks) else None
        if kind == "field":
            end = k
            while end + 1 < len(blocks) and blocks[end + 1][0] == "field":
                end += 1
            parts.append(fields_html([b[1:4] for b in blocks[k:end + 1]]))
            k = end + 1
            continue
        if kind == "cover":
            info = block[1]
            rows = "".join(f"<tr><th>{_h(label)}</th><td>{_h(value or HUMAN_INPUT)}</td></tr>" for label, value in cover_rows(info))
            link = cover_link(info)
            if link:  # 「공고 원문」 — PDF 에서도 눌리는 링크(2.9.1)
                url = html.escape(link[1], quote=True)
                rows += f'<tr class="link"><th>{_h(link[0])}</th><td><a href="{url}">{url}</a></td></tr>'
            flag = '<p class="flag">검토용 — 제출하지 마세요</p>' if review else ""
            parts.append(f'<section class="cover"><p class="kind">{_h(info.get("kind") or "사업계획서")}</p><p class="notice">{_h(info.get("notice") or title)}</p>'
                         f'<table class="meta">{rows}</table>{flag}</section>')
        elif kind == "legend":
            parts.append(f'<div{cls("legend")}><p class="legend-title">검토용 — 제출하지 마세요</p>'
                         f'<p class="ai-sample"><span class="sw bar"></span>왼쪽 회색 줄 · 회색 글자 — AI가 덧붙인 문장(근거 확인 후 고쳐 쓰기)</p>'
                         f'<p><span class="tag">[공고] [회사]</span> — 공고 · 회사 근거가 있는 문장, 뒤에 (근거: …)</p>'
                         f"<p>{_h(HUMAN_INPUT)} — 담당자가 채웁니다</p></div>")
        elif kind == "toc":
            items = "".join(f'<p class="toc{level}">{_h(text)}</p>' for level, text in block[1])
            parts.append(f'<section class="toc"><p class="toc-title">목차</p>{items}</section>')
            new_page = True
        elif kind == "h1":
            parts.append(f"<h1{cls()}>{_h(block[1])}</h1>")
        elif kind == "h2":
            count = _ai_count(block) if review else ""
            parts.append(f"<h2{cls()}>{_h(block[1])}" + (f' <span class="count">{count}</span>' if count else "") + "</h2>")
        elif kind == "summary":
            parts.append('<div class="summary"><p class="summary-title">핵심 요약(본문 첫 문장 자동 발췌)</p>'
                         + "".join(f"<p>· {_h(line)}</p>" for line in block[1]) + "</div>")
        elif kind in TEXT_KINDS:
            parts.append(text_html(k, block, nxt))
        elif kind == "photo":
            parts.append(f'<table class="photo{page_class()}"><tbody><tr><td>{_h(block[1])}</td></tr></tbody></table>')
        elif kind in ("table", "memo_table"):
            parts.append(table_html(block[1]))
        elif kind == "memo_h":
            parts.append(f'<h1 class="memo-h pb">{_h(block[1])}</h1>')
        elif kind == "memo":
            _, text, depth = block
            found = next((i for i, ch in _outside(text) if ch in ":："), None) if _MEMO_BOLD.match(text) else None
            inner = f"<b>{_h(text[:found + 1])}</b>{_h(text[found + 1:])}" if found is not None else _h(text)
            parts.append(f'<p class="memo{" in" if depth else ""}">{inner}</p>')
        if kind == "cover":
            new_page = True
        k += 1
    css = _css(review, _review_header_notice(meta, title))
    body_class = ' class="review"' if review else ""
    label = meta.get("file_label") or VARIANT_LABELS[variant]  # PDF 문서 정보 제목 — 워드 판과 같은 이름(2.7.0)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(_clean(title))} ({html.escape(label)})</title>'
            f"<style>{css}</style></head><body{body_class}>{''.join(parts)}</body></html>")


#: 원문이 평가본만 받는 공고(원본 · 사본 구분 없음 · 2.10.0 D8)의 회사명 판 이름 — 내지 않는 판(내부 보관용).
WITH_NAME_LABEL = "회사명 포함본"


def variant_label(variant: Variant, *, final: bool, blind_only: bool = False) -> str:
    """판 이름(워드 · PDF 문서 정보 제목 · 파일 이름 · 2.7.0 · 2.8.0 B9) — 제출용은 「제출용」(제출 준비가 아니면 「초안」) · 평가본은
    「평가본」 · 「평가본 초안」 · 검토용은 「검토용」. 원문이 평가본만 받는 공고(`format.blind_only` · D8)는 평가본이 「제출용」 · 「초안」이고
    회사명 판은 「회사명 포함본」."""
    if variant == "review":
        return VARIANT_LABELS["review"]
    if blind_only and variant == "submit":
        return WITH_NAME_LABEL
    if variant == "blind" and not blind_only:
        return VARIANT_LABELS["blind"] + ("" if final else " 초안")
    return VARIANT_LABELS["submit"] if final else "초안"


def export_file_name(program_title: str | None, extension: str, *, now: datetime | None = None, variant: Variant | None = None,
                     doc_kind: str = "사업계획서", draft: bool = False, blind_only: bool = False) -> str:
    """「사업계획서_초안_{사업명 앞 20자}_{날짜}.{확장자}」 — 판을 주면 「사업계획서_제출용_…」. 못 쓰는 `/\\:*?"<>|` 는 뺀다.
    입찰 제안서는 `doc_kind="제안서"`(11-03). `draft` — 품질 게이트가 「제출 준비」가 아니면 제출용은 「…_초안_…」 · 평가본은
    「…_평가본_초안_…」(2.8.0 B9). `blind_only` — 평가본만 받는 공고는 평가본이 「…_제출용_…」 · 회사명 판은 「…_회사명_포함본_…」(D8)."""
    name = re.sub(r'[\\/:*?"<>|]', "", (program_title or "지원사업").strip())[:20].strip()
    day = (now or datetime.now(KST)).strftime("%Y%m%d")
    kind = variant_label(variant, final=not draft, blind_only=blind_only).replace(" ", "_") if variant else "초안"
    return f"{doc_kind}_{kind}_{name}_{day}.{extension}"


def export_meta(draft: dict[str, Any], form: dict[str, Any], *, notice: str, company: str | None, now: datetime | None = None) -> dict[str, Any]:
    """표지 값 — 공고명 · 과제명(고른 과제) · 기업명(회사자료) · 제출일(내려받은 날 · 담당자가 고친다)."""
    task = form.get("selected_task") or {}
    task_name = draft.get("selected_task", {}).get("title") if isinstance(draft.get("selected_task"), dict) else None
    day = now or datetime.now(KST)
    return {
        "notice": notice,
        "task": task.get("title") or task_name,
        "company": company,
        "date": f"{day.year}. {day.month}. {day.day}.",
    }
