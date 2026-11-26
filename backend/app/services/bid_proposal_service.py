"""입찰 제안서 초안 — 제안요청서가 정한 목차 · 평가 기준대로 절마다 쓴다(11-03 · 대표 「확인 필요 쓰지 마 · 바로 입찰할 품질」).

예전 전체 초안(`proposal_service.generate_document`)은 요구사항 한 줄마다 문장 하나라 입찰 절차 조항(청렴계약 · 보증금 ·
협정서 메뉴 경로)까지 본문이 됐고, 제안요청서의 「제안서 목차 및 작성 방법」 · 기술능력 평가 기준을 보지 않았다. 여기서는:

1. 분석에 쓴 제안요청서 파일에서 목차 · 작성 방법 · 평가 기준 · 작성 지침 · 사업 개요와 과업 발췌를 규칙으로 읽는다.
2. 대항목마다 Claude/Codex 를 한 번 부른다(한꺼번에 · 시간 상한은 사업계획서와 같은 270초). 보내는 것은 `llm_payload` 허용 목록뿐.
3. 사업계획서와 같은 규칙 검증(`plan_draft_service.validate_unit`)을 지나고, 「확인 필요」 · 작성 사정 문장은 본문에서 빼 빈칸 목록으로.
4. 문서는 사업계획서와 같은 조립(`plan_export_service`) — 제출용(표식 · 메모 없음) · 검토용(근거 · 경고 · 메모).

회사 사실은 지어내지 않는다: 프로필 · 인증 · 보유 자격 · 실적 원장(외부 사용 「가능」)만 근거다. 일반현황 칸은 문서를 조립할 때
회사자료로 채우고(`plan_fill_service`), 인력 성명 · 경력처럼 회사만 아는 값은 「(담당자 입력)」 빈칸으로 둔다.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.core import storage
from app.schemas.organization import AnalysisContext
from app.services import analysis_store, g2b_mapper, llm_client, performance_ledger, plan_draft_service, plan_export_service, plan_validation
from app.services.plan_draft_service import (
    COMPANY,
    NOTICE,
    SUGGESTION,
    PlanBlankOut,
    PlanSectionOut,
    PlanSentenceOut,
    PlanTablesOut,
    ScheduleRowOut,
)
from app.services.plan_form_service import HUMAN_INPUT, HUMAN_INPUT_RE

logger = logging.getLogger(__name__)
FILE_NAME = "bid_plan_draft.json"
DOC_KIND = "제안서"
#: 표지 제출일 — 월 · 일은 제출하는 날 한글에서 적는다(빈칸 = 전각 U+3000 두 자 · HTML 이 빈칸을 접지 않게) · 해는 입찰 마감의 해(모르면 내려받은 해) ·
#: 값이 있는 칸이라 미작성 셈 밖(2.11.0 D1 — 세면 승인 · 「제출용」 이름에 영영 못 간다). 사업계획서 표지는 날짜 그대로.
SUBMIT_DATE = "{year}년\u3000\u3000월\u3000\u3000일"
TIME_LIMIT_SECONDS = plan_draft_service.TIME_LIMIT_SECONDS
MIN_CALL_SECONDS = plan_draft_service.MIN_CALL_SECONDS
#: 대항목을 한꺼번에 쓴다 — 보통 5~8개라 차례로는 시간 상한에 못 든다. ponytail: 구독 한도에 걸리면 4로 줄인다.
MAX_PARALLEL = 8
EXCERPT_LIMIT = 30_000
RULES_LIMIT = 3_000
EVAL_TEXT_LIMIT = 6_000
#: 회사 실적 조각 수 — 대항목 호출마다 같은 조각(사업 낱말과 겹치는 순).
LEDGER_PIECES = 6
#: 소항목 목표 분량(글자) — 과업 절은 길게, 개요 절은 짧게.
TARGET_CHARS = {"task": 3_000, "overview": 700, "default": 1_100}
#: 쪽수 상한이 있으면 소항목 목표 분량을 줄인다(11-06 A-5) — 쪽당 글자 · 표 · 표지 · 별첨 몫 · 소항목 하나 최소.
CHARS_PER_PAGE = 1_100
RESERVED_SHARE = 0.25
MIN_UNIT_CHARS = 350


def unit_targets(units: list[dict[str, Any]], page_limit: int | None) -> dict[str, int]:
    """소항목마다 목표 분량(글자) — 쪽수 상한이 없으면 지금 값, 있으면 (상한 × 쪽당 글자 × 75%) ÷ 소항목 수 이하(최소 350자)."""
    if not page_limit or not units:
        return {u["key"]: TARGET_CHARS[u["target"]] for u in units}
    share = max(MIN_UNIT_CHARS, int(page_limit * CHARS_PER_PAGE * (1 - RESERVED_SHARE) / len(units)))
    return {u["key"]: min(TARGET_CHARS[u["target"]], share) for u in units}


class BidPlanError(Exception):
    """쓸 수 없는 까닭 — 화면에 그대로 보인다."""


class NoRfpError(BidPlanError):
    pass


class SourceMissingError(BidPlanError):
    pass


class BidPlanNotGeneratedError(Exception):
    pass


# ---------------------------------------------------------------------------
# 제안요청서 읽기 — 목차 · 평가 기준 · 작성 지침 · 사업 개요 · 과업 발췌 (규칙)
# ---------------------------------------------------------------------------

_ROMAN = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5, "Ⅵ": 6, "Ⅶ": 7, "Ⅷ": 8, "Ⅸ": 9, "Ⅹ": 10,
          "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_ROMAN_ALT = r"VIII|VII|VI|IV|IX|III|II|I|V|X|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]"
_ROMAN_GLYPHS = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_MAJOR_RE = re.compile(rf"^\s*({_ROMAN_ALT})\s*\.\s*(\S.*?)\s*$")
_DOTLESS_MAJOR_RE = re.compile(r"^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\s+(\S.*?)\s*$")
#: 숫자 대항목(「1. 제안 개요」) — 로마 숫자 대항목을 못 읽었을 때만(11-03 검토 · 흔한 숫자 목차)
_NUM_MAJOR_RE = re.compile(r"^\s*(\d{1,2})\s*\.\s*(?!\d)(\S.*?)\s*$")
_HANGUL_ORDER = "가나다라마바사아자차카타파하"
#: 소항목 꼴 — 대항목 안 첫 소항목의 꼴만 이어 받는다(작성 방법 속 「1) 목적을 기술」이 소항목이 되지 않게).
#: 「decimal」은 숫자 대항목 아래 「1.1. 제안사 사업현황」(11-06 1731641) — 앞 숫자가 대항목 번호여야 한다.
_MINOR_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("roman-dash", re.compile(rf"^\s*(?:{_ROMAN_ALT})\s*-\s*(\d{{1,2}})\s*[.)]?\s*(\S.*?)\s*$")),  # 「Ⅰ-1. 제안 목적」
    ("decimal", re.compile(r"^\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s+(\S.*?)\s*$")),
    ("dot", re.compile(r"^\s*(\d{1,2})\s*\.\s*(?!\d)(\S.*?)\s*$")),
    ("paren", re.compile(r"^\s*(\d{1,2})\s*\)\s*(\S.*?)\s*$")),
    ("hangul", re.compile(r"^\s*([가-하])\s*[.)]\s*(\S.*?)\s*$")),
)
#: 목차 끝 — 덩어리 머리(□ · ■)는 짧은 줄만(긴 줄은 ■ 글머리 작성 방법이다).
_BLOCK_HEAD_CHARS = 20
#: 제안서 목차 머리(11-06 넓힘) — 「제안서 목차 및 작성 방법」 · 「제안서 작성지침 및 목차」 · 「제안서 작성 목차 및 내용」 · 「제안서 목차(예시)」 ·
#: 「기술제안서 목차」 · 「사업내용제안서 목차」 · 「제안서 작성 양식」 · 「제안서 항목 및 작성 방법」 · 「제안서 구성」 · 「제안서 기재사항」(11-13 · 1817856).
#: 「제안서 작성 요령」은 형식 규정 절이라 머리로 보지 않는다(그 안의 「바. 제안서 목차」를 잡는다).
_OUTLINE_HEAD_RE = re.compile(r"제안서\s*(?:의\s*)?(?:작성\s*(?:지침\s*및\s*)?)?(?:목차|구성)|제안서\s*작성\s*양식|제안서\s*항목\s*및\s*작성|제안서\s*기재\s*사항")
_BLOCK_RE = re.compile(r"^\s*[□■]")
#: 문서 앞 목차 줄(「Ⅳ. 제안서 작성 안내\t25」) — 끝에 쪽 번호가 붙는다.
_TOC_PAGE_RE = re.compile(r"\s\d{1,3}\s*$")
_SKIP_WORDS = {"작성항목", "작성방법", "목차", "<목차>", "구분", "작성요령", "세부내용", "주요내용", "항목", "내용", "작성내용", "작성지침",
               "제안항목", "대항목", "중항목", "소항목", "비고", "작성지침의작성항목순서준수"}
#: 목차 머리 뒤 첫 대항목까지 넘길 수 있는 줄(표 머리 「작 성 항 목」 · 「작 성 방 법」).
_OUTLINE_LEAD_LINES = 8
#: 머리 줄이 길면(문장 속 「제안서 목차 및 작성방법을 준용하여」) 후보로는 두되 짧은 머리보다 뒤로.
_HEAD_CHARS = 30
#: 괄호 없는 서식 · 별첨 머리 줄(「별지 제1호 서식」 · 「별첨 14.」 · 「서식 3」) — 24자 이하 줄만. 짧아도 작성 방법 문장(「서식 3호 활용」 ·
#: 「별지 제2호 서식 참조」 · 「서식 제5호에 따라 작성」)은 아니다(11-06 3차 검토 #4 — 목차가 거기서 끝나 뒤 대항목이 빠졌다).
_ANNEX_RE = re.compile(r"^\s*(?=.{0,24}$)(?!.*(?:참조|참고|활용|따라|작성|기재|양식을))(?:별지\s*(?:제\s*)?\d{1,2}\s*호|별첨\s*(?:제\s*)?\d{1,2}\s*(?:호|[.)])|서식\s*(?:제\s*)?\d{1,2}\s*(?:호|[.)]|$))")
#: 서식 · 붙임이 시작하는 줄 — 목차가 끝났다(「【붙임서식 1호】」 · 「[붙임 1] 감리세부일정」 · 괄호 없는 「별지 제1호 서식」).
_FORM_MARK_RE = re.compile(r"^\s*(?:【|\[\s*(?:붙임|별지|별첨|서식)|<\s*(?:별지|서식)|붙임\s*\d)|" + _ANNEX_RE.pattern)
#: 두 칸 목차 표 오른쪽 칸의 제출 서류 목록(「1. [필수] 사업자 등록증」 · 「[별지 5] 일반현황」) — 소항목이 아니다(1782053).
_PAPER_ITEM_RE = re.compile(r"^\[\s*(?:필수|선택|별지|별첨|서식)")
#: 번호만 있는 줄(「3」 다음 줄 「제안서 작성지침 및 목차」) — 가천대 꼴 절 번호.
_BARE_NO_RE = re.compile(r"^\s*(\d{1,2})\s*$")
#: 목차 표가 끝난 뒤 다음 절(「4. 작성 시 유의사항」 · 「4. 제안서 평가방법」) — 번호가 이어져도 소항목이 아니다.
#: 「제안서 규격」 — 작성요령 표 뒤 「2. 제안서 규격」 · 「가. 제안서 규격」(11-13 동국대 — 마지막 대항목이 가~라를 소항목으로 삼켰다).
#: 맨 「규격」은 아니다 — 소항목 「4. AI 서버 규격 및 성능」 · 「1. 장비 규격」에서 목차가 끊겼다(11-13 T1 검토).
_SECTION_WORDS_RE = re.compile(r"유의\s*사항|평가|제출|입찰|계약|협상|작성\s*(?:요령|지침|방법)|안내|제안서\s*규격")
_SECTION_TITLE_RE = re.compile(r"유의\s*사항|작성\s*(?:요령|방법|지침)|평가\s*(?:방법|기준)|제출\s*(?:방법|서류)")
_HANGUL_LIST_RE = re.compile(r"^\s*가\s*[.)]\s*\S")
#: 소항목 제목이 다음 줄로 이어지는 꼴(표 칸 줄바꿈 — 「3. 추진내용/일정,」 + 「안전관리 방안」 · 「사업수행 조직」 + 「및 인력현황」).
_CONNECT_END_RE = re.compile(r"(?:[,·/]|및)$")
_CONNECT_START_RE = re.compile(r"^(?:및|등)(?:\s|$)")
_NUMBERED_RE = re.compile(rf"^\s*(?:\d|[가-하]\s*[.)]|[①-⑳]|(?:{_ROMAN_ALT})\s*\.)")
#: 소항목 · 작성 방법 글머리.
_BULLET_RE = re.compile(r"^\s*(?:(?:o|ㅇ|-|–)\s+|[◦○◯∘•·ㆍ‧∙⦁▸▪])\s*(\S.*)$")
_PLAIN_ITEM_RE = re.compile(r"^\s*[◦○∘•]\s*(\S.*)$")
#: 작성 방법 문장 끝(「… 기술」 · 「… 작성」) — 번호 없는 대항목 제목이 아니다.
_GUIDE_END_RE = re.compile(r"(?:기술|작성|제시|명시|기재|준수|포함|설명|요약|첨부|제출|활용|참조|[함음임됨것다]|\.)$")
#: 대항목 제목 낱말 — 제안서 목차답다(가점) · 제안요청서 장 낱말 — 문서 목차다(둘 이상이면 탈락).
_PROPOSAL_WORDS_RE = re.compile(r"제안\s*(?:개요|사|업체|내용)|일반\s*(?:현황|사항)|업체\s*현황|사업\s*(?:수행|관리)|수행\s*계획|추진\s*전략|참여\s*인력|조직|"
                                r"특징|장점|기대\s*효과|지원|기술\s*부문|과업\s*(?:개요|추진|수행)|세부\s*실행")
_CHAPTER_WORDS_RE = re.compile(r"사업\s*개요|제안\s*요청\s*사항|과업\s*(?:내용|지시)|입찰|제안\s*안내|평가\s*방법|서식|별첨|계약|기타\s*안내")


def _tidy(title: str) -> str:
    text = re.sub(r"\s+", " ", title).strip(" :·-")
    if re.fullmatch(r"(?:[가-힣] )+[가-힣]", text):  # 「기 타」 · 「작 성 항 목」
        text = text.replace(" ", "")
    return text


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _joined(lines: list[str], index: int) -> bool:
    """표 전체가 한 줄로 이어 붙은 줄인가(HWPX 표가 칸마다 한 줄 + 이어 붙인 한 줄로 나온다) — 다음 두 줄을 이어 붙인 글로 시작한다."""
    here = _compact(lines[index])
    following = [_compact(line) for line in lines[index + 1:index + 6] if line.strip()][:2]
    return len(following) == 2 and len(here) > len(following[0]) and here.startswith(following[0] + following[1])


def read_outline(text: str) -> list[dict[str, Any]]:
    """「제안서 목차 및 작성 방법」 → [{no, title, guide, items: [{no, title, guide}]}]. 대항목이 셋 미만이면 빈 목록."""
    return find_outline(text)[0]


def find_outline(text: str) -> tuple[list[dict[str, Any]], bool]:
    """(목차, 목차 머리를 찾았는가) — 글 하나를 `locate_outline` 으로 읽는다.
    머리는 찾았는데 못 읽었으면 화면이 「목차가 없다」가 아니라 「목차를 읽지 못했다」고 알린다(11-03 검토)."""
    found = locate_outline([_text_doc(text)])
    return found["outline"], found["found_head"]


def _text_doc(text: str, *, name: str | None = None, role: str = "rfp") -> dict[str, Any]:
    return {"name": name, "role": role, "pages": [(1, text or "")], "text": text or ""}


def _doc_lines(doc: dict[str, Any]) -> tuple[list[str], list[int]]:
    """(줄, 그 줄의 쪽) — 쪽 근거를 남기려고 쪽마다 줄을 나눈다."""
    lines: list[str] = []
    pages: list[int] = []
    for page, body in doc.get("pages") or [(1, doc.get("text") or "")]:
        for line in (body or "").splitlines():
            lines.append(line.strip())
            pages.append(page)
    return lines, pages


def _doc_toc_span(lines: list[str]) -> tuple[int, int] | None:
    """문서 앞 「목 차」 · 「차 례」 · 「CONTENTS」 덩어리(시작, 끝) — 첫 장 제목이 본문에서 다시 나오는 줄 앞까지(HWPX 목차는 쪽 번호가 빠져 줄만 보고는 모른다).
    머리가 없으면 장 줄만 셋 이상 연달아 선 덩어리(「Ⅰ. …」 「Ⅱ. …」 「Ⅲ. …」 — 사이에 다른 줄 없음)의 첫 장이 뒤에서 다시 나올 때."""
    # 표 머리 칸 「목 차」 / 「작 성 방 법」과 그 표가 이어 붙은 줄은 제안서 목차 표다(11-06 3차 검토 #1)
    start = next((i for i, line in enumerate(lines[:300]) if _TOC_HEAD_RE.match(_compact(line))
                  and not _table_head(lines, i) and not _row_head(lines, i)
                  and sum(1 for nxt in lines[i + 1:i + 40] if _MAJOR_RE.match(_TOC_PAGE_RE.sub("", nxt))) >= 2), None)
    if start is None:  # 표 머리 칸 「목차」(가천대 꼴)는 뒤에 장 줄이 없다
        start = _bare_toc_start(lines)
    if start is None:
        return None
    first: tuple[int, str] | None = None
    for j in range(start + 1, min(len(lines), start + 80)):
        if not lines[j] or _joined(lines, j):
            continue
        head = _MAJOR_RE.match(_TOC_PAGE_RE.sub("", lines[j])) or _NUM_MAJOR_RE.match(_TOC_PAGE_RE.sub("", lines[j]))
        if head:
            first = (j, _compact(head.group(2)))
            break
    if first is None:
        return start, start
    strip = re.compile(rf"^\s*(?:{_ROMAN_ALT}|\d{{1,2}})\s*\.?\s*")
    for k in range(first[0] + 1, min(len(lines), first[0] + 250)):
        if lines[k] and _compact(strip.sub("", lines[k])) == first[1] and not _TOC_PAGE_RE.search(lines[k]):
            return start, k - 1
    return start, min(len(lines) - 1, start + 80)


_TOC_HEAD_RE = re.compile(r"^(?:목차|차례|contents)", re.I)
_CHAPTER_NO_RE = re.compile(rf"^\s*(?:{_ROMAN_ALT}|\d{{1,2}})\s*\.?\s*")


def _chapter_of(line: str) -> tuple[int, str] | None:
    """로마 숫자 장 줄(쪽 번호 뺌) → (번호, 제목 · 띄어쓰기 없이)."""
    head = _MAJOR_RE.match(_TOC_PAGE_RE.sub("", line))
    return (_ROMAN[head.group(1)], _compact(_tidy(head.group(2)))) if head else None


def _bare_toc_start(lines: list[str]) -> int | None:
    """머리 없는 문서 앞 목차 — 문서 앞 300줄에서 장 줄 Ⅰ · Ⅱ · Ⅲ 이 사이에 다른 줄 없이 연달아 서고, Ⅰ 제목이 그 뒤에 다시 나온다.
    제안서 목차가 본문에 두 번 나오는 공고(본문 · 별지 · 1782053 · 1808716)는 대항목 사이에 소항목 · 작성 방법 줄이 있어 걸리지 않는다."""
    filled = [i for i in range(min(300, len(lines))) if lines[i] and not _joined(lines, i)]
    for n, i in enumerate(filled[:-2]):
        run = [_chapter_of(lines[j]) for j in filled[n:n + 3]]
        if all(run) and [c[0] for c in run] == [1, 2, 3]:  # type: ignore[index]
            title = run[0][1]  # type: ignore[index]
            if any(_compact(_CHAPTER_NO_RE.sub("", lines[k])) == title for k in range(filled[n + 2] + 1, min(len(lines), i + 300))):
                return i - 1
    return None


def _span_titles(lines: list[str], span: tuple[int, int] | None) -> set[str]:
    """문서 앞 목차 덩어리 안 장 제목 — 본문에서 이 장들을 제안서 목차로 읽지 않게(11-06 검토 P3 · 장 낱말 목록 밖 「사업의 개요」)."""
    if not span:
        return set()
    return {c[1] for i in range(max(0, span[0]), span[1] + 1) if (c := _chapter_of(lines[i]))}


def _toc_titles(lines: list[str]) -> set[str]:
    """문서 앞 목차의 장 제목(쪽 번호가 붙은 로마 숫자 줄) — 제안서 목차가 끝나고 다음 장(「입찰 및 제안 안내」)이 오면 멈춘다.
    숫자 절(「1. 제안사 사업현황\t15」)은 넣지 않는다 — 장 안의 절 제목이 제안서 대항목과 같을 수 있다(11-06 1731641)."""
    titles: set[str] = set()
    for line in lines[:150]:
        if not _TOC_PAGE_RE.search(line):
            continue
        head = _MAJOR_RE.match(_TOC_PAGE_RE.sub("", line))
        if head:
            titles.add(_compact(_tidy(head.group(2))))
    return titles


def _next_no(form: str, last: str | None) -> str:
    if form == "hangul":
        index = _HANGUL_ORDER.index(last) + 1 if last and last in _HANGUL_ORDER else 0
        return _HANGUL_ORDER[index] if index < len(_HANGUL_ORDER) else ""
    return str(int(last) + 1) if last and last.isdigit() else "1"


def _minor_of(line: str, major: dict[str, Any], style: str | None, *, numeric: bool, repeat: bool = False) -> tuple[str, str, str, str] | None:
    """(꼴, 차례 번호, 보이는 번호, 제목) — 대항목 안 첫 소항목이 꼴을 정하고, 그 뒤로는 같은 꼴 · 다음 번호만 소항목이다.
    바로 앞 줄도 소항목이면 같은 번호 되풀이를 받는다(「3.사업추진전략 및 목표」 · 「3.제안의 특징 및 장점」 · 11-06 1697240)."""
    items = major["items"]
    for form, pattern in _MINOR_FORMS:
        if numeric and form == "dot":
            continue  # 숫자 대항목 목차에서 「1.」은 대항목이다
        if style is not None and form != style:
            continue
        match = pattern.match(line)
        if not match:
            continue
        if form == "decimal":
            if int(match.group(1)) != major["value"]:
                return None
            seq, title = match.group(2), match.group(3)
            shown = f"{match.group(1)}.{seq}"
        else:
            seq, title = match.group(1), match.group(2)
            shown = seq
        last = items[-1]["_seq"] if items else None
        # 되풀이 판정은 꼬리를 뗀 제목끼리(저장된 제목은 꼬리를 뗐다 — 「1. 일반현황 <서식1>」 두 번이 다른 제목으로 보였다 · 3차 검토 #1)
        if seq != _next_no(form, last) and not (repeat and seq == last
                                                and _compact(_tidy(_split_note(title)[0])) != _compact(items[-1]["title"])):
            return None
        return form, seq, shown, _tidy(title)
    return None


#: PDF 두 칸 표에서 대항목 제목 뒤에 붙은 작성 방법 문장 조각(「Ⅰ. 제안개요 하고 제안의 목적 및 범위, 이해도, …」 · 1718694)
_MERGED_GUIDE_RE = re.compile(r"\s(?:하고|하며|하여|하는|하기|및|등)\s")


#: 목차 제목 뒤 지시 글(「제안서 요약 ※ <서식8> 참조하여 자율 작성」 · 1690926 · 「재무건정성(【붙임서식 2호】참조)」 · 1731641) —
#: 「※」 뒤 · 「<서식 n>」 · 「【…서식 n호】」 · 끝의 「(… 참조)」 괄호는 작성 방법이다(대항목 · 소항목 모두 · 11-06 3차 검토 #3).
_TITLE_NOTE_RE = re.compile(r"\s*(?:※.*|[<\[]\s*(?:별지\s*)?서식\s*(?:제\s*)?\d{1,2}(?:\s*-\s*\d{1,2})?\s*호?\s*[>\]].*"
                            r"|\(\s*[^()]{0,30}?참조\s*\)\s*|【[^】]{0,20}서식[^】]{0,10}】.*)$")


def _split_note(raw: str) -> tuple[str, str]:
    """(제목, 떼어 낸 지시 글) — 제목 뒤 「※ …」 · 서식 표기는 제출용 소제목에 찍히지 않게 작성 방법으로 옮긴다."""
    if (tail := _TITLE_NOTE_RE.search(raw)) and tail.start() >= 2:
        return raw[:tail.start()], tail.group(0).strip()
    return raw, ""


def _major_title(raw: str) -> tuple[str, str]:
    """(대항목 제목, 떼어 낸 지시 글) — 지시 꼬리는 작성 방법으로 옮기고, 길고 쉼표가 든 줄은 작성 방법 문장 조각 앞에서 자른다."""
    raw, note = _split_note(raw)
    title = _tidy(raw)
    if len(_compact(title)) > 20 and "," in title and (cut := _MERGED_GUIDE_RE.search(title)) and cut.start() >= 2:
        return title[:cut.start()].strip(), note
    return title, note


def _continues(title: str, line: str, following: str = "") -> bool:
    """표 칸 줄바꿈으로 쪼개진 소항목 제목의 둘째 줄인가 — 짧고 글머리 · 번호 없이, 앞 제목이 「,」 · 「및」로 끝나거나 「및」으로 시작하거나
    앞 제목이 아주 짧다(「2. 과업」 + 「세부실행계획」 · 11-06 1704406). 아주 짧은 제목 뒤라도 쉼표가 든 줄 · 바로 다음이 번호 줄인 줄
    (그 줄 하나가 작성 방법 칸 전부 — 「2. 특징」 / 「제안의 차별성」 / 「Ⅱ. …」)은 작성 방법이다."""
    text = line.strip()
    if not text or len(_compact(text)) > 15 or _BULLET_RE.match(text) or _NUMBERED_RE.match(text) or _FORM_MARK_RE.match(text):
        return False
    if _compact(text) in _SKIP_WORDS or re.search(r"서식|별지|별첨|붙임|[(\[<※*]", text) or _GUIDE_END_RE.search(text):
        return False
    if _CONNECT_END_RE.search(title) or _CONNECT_START_RE.match(text):
        return True
    return len(_compact(title)) <= 3 and "," not in text and not _NUMBERED_RE.match(following)


def _parse_outline(lines: list[str], *, numeric: bool = False, chapters: set[str] | None = None,
                   stops: tuple[re.Pattern[str], ...] = ()) -> list[dict[str, Any]]:
    """로마 숫자(또는 숫자) 대항목 목차. `stops` = 머리 다음 절 번호(머리 「3. …」이면 「4.」 · 감싼 「1) 제안서(본문)」이면 「2)」)."""
    majors: list[dict[str, Any]] = []
    style: str | None = None
    last = 0
    lead = 0
    prev_item = False
    chapters = chapters or set()
    leads: list[re.Pattern[str]] = []
    for index, line in enumerate(lines):
        if not line or _joined(lines, index):
            continue
        if _BLOCK_RE.match(line):
            if majors and len(_compact(line)) <= _BLOCK_HEAD_CHARS:
                break  # 다음 덩어리(「□ 입찰 방법」)
            if not majors:
                continue
        if _compact(line) in _SKIP_WORDS:
            continue
        if majors and (_ROMAN_ONLY_RE.match(line) or _compact(_tidy(line)) in chapters or _FORM_MARK_RE.match(line)
                       or _chapter_row(lines, index) or _SUPPLEMENT_HEAD_RE.match(line)):
            break  # 장 번호만 있는 줄(「V」 · 「5」 / 「제안서 평가」) · 문서 목차에 있는 장 제목 · 서식 시작 · 「※ 붙임」 목록 — 제안서 목차가 끝났다
        major = (_NUM_MAJOR_RE if numeric else _MAJOR_RE).match(line)
        if not major and not numeric and majors and (bare := _DOTLESS_MAJOR_RE.match(line)) \
                and _ROMAN[bare.group(1)] == last + 1 and not _CHAPTER_WORDS_RE.search(bare.group(2)):
            major = bare  # 점 없는 「Ⅲ 교육의 추진전략 및 시행방안」 — 앞 대항목 다음 번호 · 장 낱말 없을 때만(다음 장 「Ⅴ 입찰 및 제안 안내」와 가른다)
        if major and _compact(_tidy(major.group(2))) in chapters and majors:
            break
        if majors and any(stop.match(line) for stop in (*stops, *leads)):
            nxt = _minor_of(line, majors[-1], style, numeric=numeric)
            if nxt is None or _SECTION_WORDS_RE.search(line):
                break  # 목차 표가 끝나고 다음 절(「4. 작성 시 유의사항」 · 「2) 별첨」)
        value = (int(major.group(1)) if numeric else _ROMAN[major.group(1)]) if major else 0
        title, note = _major_title(major.group(2)) if major else ("", "")
        if major and majors and value == last and _compact(title) == _compact(majors[-1]["title"]):
            continue  # 같은 대항목 줄이 두 번(대항목 칸 · 중항목 칸 · 11-06 1690563)
        repeat_major = (major and not numeric and majors and value == last
                        and (majors[-1]["items"] or majors[-1]["guide"]))  # 원문이 같은 번호를 두 번(「Ⅵ」 둘 · 1805118)
        if repeat_major and (_SECTION_TITLE_RE.search(title) or _CHAPTER_WORDS_RE.search(title)):
            # 같은 번호로 다시 온 문서 장(「Ⅳ. 기 타」 뒤 「Ⅳ. 제안서 제출방법 등」 · 「Ⅴ. 제안서 평가 방법」 — 입찰 절차를 본문으로 썼다 ·
            # 11-14 1822864). 원문 오타로 번호가 겹친 진짜 대항목(「Ⅵ. 기 타」 · 1805118)은 문서 장 낱말이 없어 그대로 받는다
            break
        # 원문이 번호 하나를 건너뜀(「III.」 다음 「V. 사업수행관리」 · 11-07 1804104) — 장 낱말이 없을 때만(문서의 다른 장과 가른다)
        skip_one = major and not numeric and majors and value == last + 2 and not _CHAPTER_WORDS_RE.search(title)
        if major and (value == last + 1 or repeat_major or skip_one) and not (numeric and majors and _minor_of(line, majors[-1], style, numeric=True)):
            last = value
            style = None
            prev_item = False
            majors.append({"no": major.group(1), "title": title, "guide": [note] if note else [], "_note": note, "items": [], "value": value})
            continue
        if major and majors and not numeric:
            break  # 차례가 끊긴 로마 숫자 — 다른 목록이 시작됐다
        if not majors:
            lead += 1
            if lead > _OUTLINE_LEAD_LINES or _ROMAN_ONLY_RE.match(line):
                return []  # 머리 바로 뒤가 다음 장(「Ⅳ」 / 「제안안내 사항」) — 표가 머리보다 앞에 있다(1781608)
            # 감싼 줄 「1) 제안서(본문)」 · 「가. 제안서 목차(예시)」 — 「2) 별첨」 · 「나. 제안서 작성 지침」에서 끝난다(11-06 1691972 · 1690926)
            if (wrapper := re.match(r"^\s*(\d{1,2})\s*\)", line)):
                leads.append(re.compile(rf"^\s*{int(wrapper.group(1)) + 1}\s*\)\s*\S"))
            elif (wrapper := re.match(r"^\s*([가-하])\s*\.", line)) and wrapper.group(1) != _HANGUL_ORDER[-1]:
                leads.append(re.compile(rf"^\s*{_next_no('hangul', wrapper.group(1))}\s*\.\s*\S"))
            continue
        minor = _minor_of(line, majors[-1], style, numeric=numeric, repeat=prev_item)
        items = majors[-1]["items"]
        if not minor and items and _back_section(line, items[-1], style):
            break  # 「4. 부가지원사항」 뒤 「2. 입찰 및 제안서 관련서식」 — 거꾸로 간 번호의 문서 절(뒤 붙임 · 별지 목록이 소항목으로 붙었다 · 11-14 1821405)
        if minor and (_PAPER_ITEM_RE.match(minor[3]) or (items and minor[1] == items[-1]["_seq"] == _next_no(minor[0], None))):
            # 두 칸 표 오른쪽 칸 — 「1. 기타」 뒤에 「1. [필수] 사업자 등록증」 · 「2. …」(같은 번호 되풀이가 1부터 다시 시작 · 1782053)
            break
        if (minor and [g for g in majors[-1]["guide"] if g != majors[-1]["_note"]] and not majors[-1]["items"]
                and _SECTION_WORDS_RE.search(line)):
            # 대항목 작성 방법 글 뒤의 번호 줄 — 소항목이 아니라 다음 장(「1. 입찰 방법」)이다. 장 낱말이 없으면 소항목이다
            # (PDF 두 칸 표는 작성 방법 줄이 소항목보다 먼저 나온다 · 1718694). 제목에서 떼어 낸 꼬리(「※ <서식8> …」)는
            # 작성 방법 글로 치지 않는다(11-06 3차 검토 #2 — 첫 소항목 「1. 입찰 참가 신청서」에서 끊겨 뒤 대항목이 빠졌다)
            guide = majors[-1]["guide"]
            if guide[-1] != majors[-1]["_note"] and _NUMBERED_RE.match(guide[-1]) and _SECTION_WORDS_RE.search(guide[-1]):
                guide.pop()  # 바로 앞 번호 줄은 그 다음 절의 머리(「2. 제안서 규격」 / 「가. 제안서 규격」 · 11-13) — 작성 방법이 아니다
            break
        if minor and _SECTION_TITLE_RE.search(minor[3]) and _HANGUL_LIST_RE.match(next((n for n in lines[index + 1:] if n), "")):
            break  # 「3. 제안서 작성방법 및 유의사항」 + 「가. …」 — 번호가 이어져도 다음 절이다(머리가 표 뒤 문장일 때 · 1808716)
        if minor:
            style = minor[0]
            title, note = _split_note(minor[3])  # 「1. 입찰 참가 신청서 <서식1> ※ 원본 별도 제출」 — 꼬리는 작성 방법(#3)
            majors[-1]["items"].append({"no": minor[2], "title": _tidy(title), "guide": [note] if note else [], "_seq": minor[1], "_note": note})
            prev_item = True
            continue
        if prev_item and items and _continues(items[-1]["title"], line, next((n for n in lines[index + 1:] if n), "")):
            items[-1]["title"] = _tidy(f"{items[-1]['title']} {line}")
            continue
        prev_item = False
        target = items[-1] if items else majors[-1]
        target["guide"].append(line)
    return majors


#: 목차 표 뒤 붙임 · 별지 목록 머리(「※ 붙임」 · 「※ 별지서식」 — 뒤 「1. …」 목록이 소항목 차례를 이어 받았다 · 11-14 1821405).
#: 짧은 줄만 — 작성 방법 문장 「※ 붙임 3 서식을 활용하여 작성」은 아니다.
_SUPPLEMENT_HEAD_RE = re.compile(r"^\s*※\s*(?:붙임|별지|별첨)\s*(?:서식)?\s*(?:목록)?\s*$")


def _back_section(line: str, item: dict[str, Any], style: str | None) -> bool:
    """마지막 소항목과 같은 꼴(「1.」 · 「1)」)인데 번호가 거꾸로 갔고 문서 절 낱말(입찰 · 제출 · 서식 …)이 든 줄 — 목차 표 뒤 다음 절이다."""
    pattern = dict(_MINOR_FORMS).get(style or "") if style in ("dot", "paren") else None
    back = pattern.match(line) if pattern else None
    return bool(back and item["_seq"].isdigit() and int(back.group(1)) < int(item["_seq"])
                and (_SECTION_WORDS_RE.search(back.group(2)) or _CHAPTER_WORDS_RE.search(back.group(2))))


def _chapter_row(lines: list[str], index: int) -> bool:
    """장 머리 「5」 / 「제안서 평가」 — 숫자만 있는 줄 바로 다음이 번호 없는 짧은 장 · 절 제목(11-13 · 1828362 — 마지막 소항목이
    평가표를 작성 방법으로 삼켰다). 목차 표 쪽수 칸의 숫자 뒤에는 대항목 · 소항목 번호 줄이 온다."""
    if not _BARE_NO_RE.match(lines[index]):
        return False
    after = next((line for line in lines[index + 1:index + 3] if line), "")
    return (bool(after) and len(_compact(after)) <= _BLOCK_HEAD_CHARS and not _NUMBERED_RE.match(after)
            and bool(_SECTION_WORDS_RE.search(after) or _CHAPTER_WORDS_RE.search(after)))


def _title_like(line: str) -> bool:
    """번호 없는 대항목 제목 줄(「과업 추진 계획」 · 「제안사」 / 「개요」) — 짧고 글머리 · 번호 · 작성 방법 말끝이 없다.
    비고 칸 서식 표기(「자율 서식」 · 「별지 제2호」)는 아니다(다음 대항목 제목에 붙어 「자율 서식 사업 관리 부문」이 됐다 · 11-13 1822479)."""
    text = line.strip()
    return (0 < len(_compact(text)) <= 12 and not _BULLET_RE.match(text) and not _NUMBERED_RE.match(text)
            and not _GUIDE_END_RE.search(text) and not re.search(r"[(\[<※*:]|서식|별지|별첨|붙임", text) and _compact(text) not in _SKIP_WORDS)


#: 번호 없는 대항목 아래 「1)」 소항목(11-13 · 1822479) — 대항목마다 1부터 차례로. 차례가 아니면 작성 방법이다.
_PAREN_ITEM_RE = re.compile(r"^\s*(\d{1,2})\s*\)\s*(\S.*?)\s*$")


def _parse_plain(lines: list[str], *, stops: tuple[re.Pattern[str], ...] = ()) -> list[dict[str, Any]]:
    """번호 없는 대항목 목차(가천대 꼴 · 11-06 1699556 등 5건) — 「◦ 」 소항목 줄 바로 앞의 짧은 줄 한두 개가 대항목이다.
    소항목이 「1) …」 꼴이어도 같다(11-13 · 1822479 — 첫 소항목 꼴이 목차 전체의 꼴). 멈춤 줄(【붙임2】 · □ …) 바로 앞에 남은
    제목 한 줄은 소항목 없는 마지막 대항목이다(「기타」). 번호는 순서로 붙인다(Ⅰ · Ⅱ … / 1 · 2 …)."""
    majors: list[dict[str, Any]] = []
    run: list[str] = []
    lead = 0
    style: str | None = None  # 「◦」(bullet) · 「1)」(paren)
    ended = False
    for index, line in enumerate(lines):
        if not line or _joined(lines, index) or _compact(line) in _SKIP_WORDS:
            continue
        if majors and (_BARE_NO_RE.match(line) or _ROMAN_ONLY_RE.match(line) or _FORM_MARK_RE.match(line)
                       or (_BLOCK_RE.match(line) and len(_compact(line)) <= _BLOCK_HEAD_CHARS) or any(s.match(line) for s in stops)):
            ended = True
            break
        bullet = _PLAIN_ITEM_RE.match(line) if style != "paren" else None
        paren = _PAREN_ITEM_RE.match(line) if style != "bullet" and not bullet else None
        if paren and int(paren.group(1)) != (1 if run or not majors else len(majors[-1]["items"]) + 1):
            paren = None  # 차례가 아닌 번호 — 작성 방법 글
        if bullet or paren:
            style = "bullet" if bullet else "paren"
            if run:
                majors.append({"title": _tidy(" ".join(run[-2:])), "guide": [], "items": []})
                run = []
            if not majors:
                return []
            majors[-1]["items"].append({"title": _tidy(bullet.group(1) if bullet else paren.group(2)), "guide": []})
            continue
        if _title_like(line):
            run.append(line)
            continue
        run = []
        if majors and majors[-1]["items"]:
            majors[-1]["items"][-1]["guide"].append(line)
        elif not majors:
            lead += 1
            if lead > _OUTLINE_LEAD_LINES:
                return []
    if len(majors) < 3 or not all(m["items"] for m in majors):
        return []
    if ended and len(run) == 1 and not (_SECTION_WORDS_RE.search(run[0]) or _CHAPTER_WORDS_RE.search(run[0])):
        majors.append({"title": _tidy(run[0]), "guide": [], "items": []})  # 표 마지막 줄 「기타」(작성 내용 칸이 빔)
    roman = list(_ROMAN_GLYPHS)
    return [{"no": roman[m] if m < len(roman) else str(m + 1), "title": major["title"], "guide": major["guide"], "value": m + 1,
             "items": [{"no": str(n + 1), "title": item["title"], "guide": item["guide"], "_seq": str(n + 1)} for n, item in enumerate(major["items"])]}
            for m, major in enumerate(majors)]


#: 가운데 낀 대항목 표지(11-13 · 1817856) — 대 · 소문자 로마 숫자 + 점. 뒤에 그 묶음 소항목 하나가 붙을 수 있다(「ⅰ.제안 개요 2.제안 개괄 내용」).
_SMALL_ROMAN = "ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ"
_CENTER_MARK_RE = re.compile(rf"^\s*({_ROMAN_ALT}|[{_SMALL_ROMAN}])\s*\.\s*(\S.*?)(?:\s+(\d{{1,2}})\s*\.(?!\d)\s*(\S.*?))?\s*$")
#: 소항목 제목 뒤 「 : 」 설명(「1.일반현황 : 대표자, 설립연도, 연혁 등」) — 작성 방법이다.
_CENTER_NOTE_RE = re.compile(r"\s+[:：]\s+")


def _parse_centered(lines: list[str], *, stops: tuple[re.Pattern[str], ...] = ()) -> list[dict[str, Any]]:
    """PDF 표가 한 줄로 무너진 목차(11-13 · 1817856) — 대항목 칸이 세로 가운데라 그 묶음 소항목 줄 사이에 끼었다
    (「1.목차」 / 「ⅰ.제안 개요 2.제안 개괄 내용」 / 「3.제안 특징 및 장점」 / 「1.일반현황 …」 …). 소항목 번호가 1로 돌아가는 곳이
    대항목 경계이고, 묶음마다 대항목 표지가 꼭 하나 · 표지 번호가 1부터 차례여야 읽는다(아니면 빈 목록 — 억지로 맞추지 않는다).
    혼자 선 표지(「ⅳ. 기타 사항」)는 다음 소항목의 묶음이다. 표지 없는 마지막 묶음은 표 뒤 다른 목록이라 버린다.
    소문자 로마 숫자는 대문자 글자로 적는다(번호 고침 `major_numbers` · 쓰기가 같은 글자를 본다)."""
    groups: list[dict[str, Any]] = []
    waiting: list[tuple[str, str]] = []
    lead = 0
    for index, line in enumerate(lines):
        if not line or _joined(lines, index) or _compact(line) in _SKIP_WORDS:
            continue
        if groups and (_FORM_MARK_RE.match(line) or (_BLOCK_RE.match(line) and len(_compact(line)) <= _BLOCK_HEAD_CHARS)
                       or (any(stop.match(line) for stop in stops) and _SECTION_WORDS_RE.search(line))):
            break
        mark = _CENTER_MARK_RE.match(line)
        if mark and mark.group(3) is None:
            waiting.append((mark.group(1), mark.group(2)))
            continue
        found = (mark.group(3), mark.group(4)) if mark else ((item := _NUM_MAJOR_RE.match(line)) and (item.group(1), item.group(2)))
        if not found:
            if groups:
                groups[-1]["items"][-1]["guide"].append(line)
                continue
            lead += 1
            if lead > _OUTLINE_LEAD_LINES:
                return []
            continue
        seq = int(found[0])
        if seq != 1 and not (groups and seq == len(groups[-1]["items"]) + 1):
            break  # 차례가 끊겼다 — 표가 끝나고 다음 절(「6. 제안서 평가」)
        if seq == 1:
            groups.append({"items": [], "marks": []})
        groups[-1]["marks"] += waiting + ([(mark.group(1), mark.group(2))] if mark else [])
        waiting = []
        title, *note = _CENTER_NOTE_RE.split(found[1], maxsplit=1)
        groups[-1]["items"].append({"no": str(seq), "title": _tidy(title), "guide": note, "_seq": str(seq), "_note": ""})
    if groups and not groups[-1]["marks"] and not waiting:
        groups.pop()
    if len(groups) < 2 or any(len(group["marks"]) != 1 for group in groups):
        return []
    marks = [group["marks"][0] for group in groups]
    values = [_ROMAN.get(no) or _SMALL_ROMAN.index(no) + 1 for no, _ in marks]
    if values != list(range(1, len(groups) + 1)):
        return []
    majors = []
    for (no, raw), value, group in zip(marks, values, groups):
        title, note = _major_title(raw)
        majors.append({"no": _ROMAN_GLYPHS[value - 1] if no in _SMALL_ROMAN else no, "title": title, "guide": [note] if note else [],
                       "_note": note, "items": group["items"], "value": value})
    return majors


def _head_stops(lines: list[str], head: int) -> tuple[re.Pattern[str], ...]:
    """머리 줄 번호의 다음 번호(같은 꼴) — 목차 표가 끝난 뒤 다음 절에서 멈춘다. 「3」 / 「제안서 작성지침 및 목차」처럼 번호가 앞 줄에 혼자 서면 그 번호."""
    own = _successor(lines[head])
    if own:
        return (own,)
    before = next((lines[i] for i in range(head - 1, max(-1, head - 3), -1) if lines[i]), "")
    if (m := _BARE_NO_RE.match(before)):
        return (re.compile(rf"^\s*{int(m.group(1)) + 1}\s*$"),)
    # 머리에 번호가 없으면(「【사업내용제안서 목차】」) 바로 위 절(「나. 사업내용제안서 작성요령」)의 다음 절에서 멈춘다(1704406)
    for i in range(head - 1, max(-1, head - 12), -1):
        if (found := _successor(lines[i])) is not None:
            return (found,)
    return ()


def _successor(text: str) -> re.Pattern[str] | None:
    """번호 붙은 절 줄(「3. …」 · 「바. …」 · 「2) …」)의 다음 번호 꼴. 다음 절은 번호 뒤에 제목이 붙은 줄 — 표 칸의 번호만 있는 줄
    (「3.」 / 「연수 운영」 · 1690926)은 절이 아니다."""
    if (m := re.match(r"^\s*(\d{1,2})\s*\.(?!\d)\s*\S", text)):
        return re.compile(rf"^\s*{int(m.group(1)) + 1}\s*\.(?!\d)\s*\S")
    if (m := re.match(r"^\s*([가-하])\s*\.\s*\S", text)) and m.group(1) != _HANGUL_ORDER[-1]:
        return re.compile(rf"^\s*{_next_no('hangul', m.group(1))}\s*\.\s*\S")
    if (m := re.match(r"^\s*(\d{1,2})\s*\)\s*\S", text)):
        return re.compile(rf"^\s*{int(m.group(1)) + 1}\s*\)\s*\S")
    return None


def _outline_ok(majors: list[dict[str, Any]]) -> bool:
    """대항목 셋 이상 — 또는 대항목 하나 · 둘이어도 소항목이 셋 이상(「Ⅰ. 제안내용」 아래 가~마 · 11-06 1690465)."""
    return len(majors) >= 3 or (bool(majors) and sum(len(m["items"]) for m in majors) >= 3)


def _head_like(line: str) -> bool:
    """머리 줄다운가 — 짧고(※ 꼬리 빼고 30자 이하) 문장으로 끝나지 않는다(「… 권고사항입니다.」 · 1718593).
    「※」로 시작하는 줄(「※ 조견표 등록 방법 : … 제안서의 목차 …」)은 머리가 아니다(11-06 3차 검토 #5)."""
    text = line.split("※")[0].strip()
    return bool(text) and len(_compact(text)) <= _HEAD_CHARS and not _SENTENCE_END_RE.search(text)


def _chapterish(majors: list[dict[str, Any]], toc_titles: set[str] | None = None) -> bool:
    """문서 장 목록을 읽었다 — 대항목에 제안요청서 장 낱말(사업개요 · 입찰 · 서식 …)이 둘 이상이고 제안서 낱말(제안개요 · 사업관리 …)이
    하나도 없거나(「Ⅱ. 사업 개요 및 이해」가 든 제안서 목차는 받는다), 대항목 절반 이상(둘 이상)이 문서 앞 목차의 장 제목이다."""
    if sum(1 for m in majors if _CHAPTER_WORDS_RE.search(m["title"])) >= 2 and not any(_PROPOSAL_WORDS_RE.search(m["title"]) for m in majors):
        return True
    hits = sum(1 for m in majors if _compact(m["title"]) in (toc_titles or set()))
    return hits >= 2 and hits * 2 >= len(majors)


_TABLE_HEAD_CELLS = ("목차", "<목차>")
_TABLE_GUIDE_CELLS = ("작성방법", "작성요령", "작성내용")
_TABLE_HEADS = tuple(head + guide for head in _TABLE_HEAD_CELLS for guide in _TABLE_GUIDE_CELLS)  # 표가 이어 붙은 줄 「목 차작 성 방 법 Ⅰ. …」
#: 다른 목차 머리를 못 찾았을 때만 보는 표 머리 칸(「라. 제안서 작성요령」 아래 「작 성 항 목 / 작 성 방 법」 · 11-13 동국대) —
#: 늘 보면 제출 서류 · 서식 목록 표(1690926)를 목차로 잡는다.
_LOOSE_HEAD_CELLS = ("작성항목",)


def _outline_head(lines: list[str], index: int, *, loose: bool = False) -> bool:
    """목차 머리 줄 — 「제안서 목차 및 작성 방법」 꼴이거나, 표 머리 칸 「목 차」 바로 다음이 「작 성 방 법」(머리 절 이름은
    「다. 제안서 작성지침 및 유의사항」 · 11-06 3차 검토 #1 · 1808642). 문서 앞 목차의 「목 차」는 다음 줄이 장 줄이라 걸리지 않는다.
    `loose` 면 표 머리 칸 「작 성 항 목」도(다른 머리로 목차를 못 읽었을 때만 · `locate_outline`)."""
    line = lines[index]
    if _OUTLINE_HEAD_RE.search(line):
        return not _TOC_PAGE_RE.search(line)
    cells = _TABLE_HEAD_CELLS + _LOOSE_HEAD_CELLS if loose else _TABLE_HEAD_CELLS
    return _compact(line) in cells and (_table_head(lines, index, cells) or _row_head(lines, index))  # 이어 붙은 표 줄은 머리가 아니다


def _row_head(lines: list[str], index: int) -> bool:
    """표 머리 칸 「구분 | 목차」 — 앞 칸이 「구분」이고 바로 다음 줄이 「Ⅰ.」 대항목이면 문서 앞 목차가 아니라 제안서 목차 표다
    (11-13 · 1828362 — 문서 앞 목차로 오인해 그 뒤 80줄을 지웠고 평가표 머리까지 빠졌다)."""
    if _compact(lines[index]) not in _TABLE_HEAD_CELLS:
        return False
    before = next((_compact(lines[i]) for i in range(index - 1, max(-1, index - 3), -1) if lines[i]), "")
    after = next((lines[i] for i in range(index + 1, min(len(lines), index + 4)) if lines[i]), "")
    return before == "구분" and bool((major := _MAJOR_RE.match(after)) and _ROMAN[major.group(1)] == 1)


def _table_head(lines: list[str], index: int, cells: tuple[str, ...] = _TABLE_HEAD_CELLS) -> bool:
    """표 머리 칸 「목 차」 + 「작 성 방 법」 — 그 칸 줄이거나 그 표가 이어 붙은 줄(「목 차작 성 방 법 Ⅰ. …」)."""
    here = _compact(lines[index])
    if here.startswith(_TABLE_HEADS):
        return True
    return here in cells and next((_compact(n) for n in lines[index + 1:index + 4] if n), "") in _TABLE_GUIDE_CELLS


def _head_label(lines: list[str], head: int) -> str:
    """보이는 머리 줄 — 표 머리 칸 「목 차」 · 「작 성 항 목」이면 바로 위 절 줄(표가 이어 붙은 줄은 건너뜀). 「구분 | 목차」 표는 「목차」 그대로."""
    if _compact(lines[head]) in _TABLE_HEAD_CELLS + _LOOSE_HEAD_CELLS and not _row_head(lines, head):
        return next((lines[i] for i in range(head - 1, max(-1, head - 4), -1) if lines[i] and not _joined(lines, i)), lines[head])
    return lines[head]


def _outline_candidates(lines: list[str], toc_titles: set[str] | None = None, *, loose: bool = False) -> list[tuple[int, list[dict[str, Any]], int]]:
    """머리 줄마다 (머리 줄, 목차, 목차가 시작하는 줄). 로마 숫자 → 숫자 → 번호 없는 대항목 차례로 읽고, 앞으로 읽어 못 읽으면
    머리 바로 앞의 표(한글 표가 머리보다 먼저 추출된 꼴 · 1781608). 장 제목만 읽힌 결과는 실패로 보고 다음 방법으로 — 끝까지 그것뿐이면
    그대로 돌려 `locate_outline` 이 사유와 함께 탈락시킨다."""
    chapters = _toc_titles(lines)
    out: list[tuple[int, list[dict[str, Any]], int]] = []
    for head, line in enumerate(lines):
        if not _outline_head(lines, head, loose=loose):
            continue
        stops = _head_stops(lines, head)
        body = lines[head + 1:]
        first = next((i for i in range(head - 1, max(-1, head - 200), -1)
                      if (m := _MAJOR_RE.match(lines[i])) and _ROMAN[m.group(1)] == 1), None)
        attempts = [
            (lambda: _parse_outline(body, chapters=chapters, stops=stops), head + 1),
            (lambda: _parse_outline(body, numeric=True, chapters=chapters, stops=stops), head + 1),
            (lambda: _parse_plain(body, stops=stops), head + 1),
            (lambda: _parse_centered(body, stops=stops), head + 1),  # PDF 표가 무너져 대항목이 소항목 사이에 낀 꼴(11-13 · 1817856)
            (lambda: _parse_outline(lines[first:head], chapters=chapters) if first is not None else [], first or 0),
        ]
        chosen: tuple[list[dict[str, Any]], int] = ([], head + 1)
        bad: tuple[list[dict[str, Any]], int] | None = None
        for attempt, start in attempts:
            majors = attempt()
            if not _outline_ok(majors):
                continue
            if _chapterish(majors, toc_titles):
                bad = bad or (majors, start)
                continue
            chosen = (majors, start)
            break
        majors, start = chosen if chosen[0] else (bad or chosen)
        out.append((head, majors, start))
    return out


def _clean_outline(majors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # note = 제목에서 떼어 낸 지시 꼬리(「<서식1> ※ 원본 별도 제출」) — 쓰기가 서식 소항목을 알아본다(`build_form`)
    return [{"no": m["no"], "title": m["title"], "guide": m["guide"], "note": m.get("_note") or "",
             "items": [{"no": i["no"], "title": i["title"], "guide": i["guide"], "note": i.get("_note") or ""} for i in m["items"]]}
            for m in majors]


def _start_index(majors: list[dict[str, Any]], lines: list[str], start: int) -> int:
    first = majors[0]["title"] if majors else ""
    return next((i for i in range(start, min(len(lines), start + 40)) if first and _compact(first) in _compact(lines[i])), start)


def locate_outline(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """원문 여러 개에서 제안서 목차를 찾는다(11-06) — 머리 후보를 모두 읽어 점수로 고른다.

    탈락: 머리 줄이 문서 앞 「목 차」 덩어리 안 · 이어 붙은 줄(로마 숫자 장이 셋 이상 · 다음 줄들을 이어 붙인 글) · 읽은 대항목에 제안요청서 장
    낱말(사업개요 · 입찰 · 서식 · 별첨 …)이 둘 이상. 가점: 대항목에 제안서 낱말(제안개요 · 일반현황 · 사업수행 …). 머리 줄이 긴 문장이면 감점.
    → {"outline", "found_head", "where": {document, page, head} | None, "rejected": [{head, page, reason}]}
    다른 머리로 목차를 못 읽었을 때만 표 머리 칸 「작 성 항 목」도 머리로 한 번 더 본다(11-13) — 그래도 못 읽으면 첫 결과 그대로."""
    found = _locate_outline(docs)
    if found["outline"]:
        return found
    # 느슨한 시도도 엄격한 머리를 모두 다시 보므로 쓰지 않은 후보와 사유(/plan 「이 제안서 양식」)가 그대로 남는다
    loose = _locate_outline(docs, loose=True)
    return loose if loose["outline"] else found


def _locate_outline(docs: list[dict[str, Any]], *, loose: bool = False) -> dict[str, Any]:
    best: tuple[int, int, dict[str, Any]] | None = None
    found: dict[str, Any] | None = None
    rejected: list[dict[str, Any]] = []
    for order, doc in enumerate(docs):
        lines, pages = _doc_lines(doc)
        toc = _doc_toc_span(lines)
        toc_titles = _span_titles(lines, toc)
        for head, majors, start in _outline_candidates(lines, toc_titles, loose=loose):
            head_text = _head_label(lines, head)
            # 「목차 머리를 찾음」은 짧은 머리이거나 읽힌 것만 — 문장 속 「제안서 구성은 …」(1718593)은 머리가 아니다
            short = _head_like(head_text)
            if (short or majors) and (found is None or (found.get("_toc") and not (toc and toc[0] <= head <= toc[1]))):
                found = {"document": doc.get("name"), "page": pages[head], "head": head_text[:80], "_toc": bool(toc and toc[0] <= head <= toc[1])}
            reason = None
            if toc and toc[0] <= head <= toc[1]:
                reason = "문서 앞 목차(제안요청서 장 목록) 안의 줄입니다"
            elif _joined(lines, head) or sum(head_text.count(g) for g in _ROMAN_GLYPHS) >= 3:
                reason = "표 · 목차가 한 줄로 이어 붙은 줄입니다"
            elif majors and _chapterish(majors, toc_titles):
                reason = "읽은 대항목이 제안요청서 장 제목(사업개요 · 입찰 · 서식 …)입니다"
            if reason:
                entry = {"head": head_text[:80], "page": pages[head], "reason": reason, "document": doc.get("name")}
                if entry not in rejected:
                    rejected.append(entry)
                continue
            if not majors:
                continue
            score = (10 * len(majors) + sum(len(m["items"]) for m in majors)
                     + 5 * sum(1 for m in majors if _PROPOSAL_WORDS_RE.search(m["title"]))
                     - (0 if short else 15))
            where = {"document": doc.get("name"), "page": pages[_start_index(majors, lines, start)], "head": head_text.split("※")[0].strip()[:80]}
            if best is None or (score, -order) > (best[0], -best[1]):
                best = (score, order, {"outline": _clean_outline(majors), "where": where})
    return {
        "outline": best[2]["outline"] if best else [],
        "found_head": found is not None,
        "where": best[2]["where"] if best else None,
        "rejected": rejected,
        # 머리는 찾았는데 못 읽은 곳(「원문 n쪽을 확인하세요」) — 문서 앞 목차가 아닌 머리가 먼저
        "found_at": {k: v for k, v in found.items() if k != "_toc"} if found else None,
    }


#: 목차를 못 읽은 제안요청서에 쓰는 표준 목차(공공 용역 제안서의 흔한 꼴).
STANDARD_OUTLINE: tuple[dict[str, Any], ...] = (
    {"no": "Ⅰ", "title": "제안 개요", "guide": [], "items": [
        {"no": "1", "title": "제안 목적 및 목표", "guide": ["사업의 목적 · 목표와 제안 범위"]},
        {"no": "2", "title": "제안의 특징 및 장점", "guide": ["당사 제안의 핵심 전략 · 특징 · 장점"]}]},
    {"no": "Ⅱ", "title": "제안사 일반", "guide": [], "items": [
        {"no": "1", "title": "일반현황", "guide": ["제안사의 일반현황 및 주요 연혁"]}]},
    {"no": "Ⅲ", "title": "사업 수행 부문", "guide": [], "items": [
        {"no": "1", "title": "사업 이해 및 추진 전략", "guide": ["사업 목표와 추진 전략"]},
        {"no": "2", "title": "세부 과업별 수행 방안", "guide": ["제안요청 사항의 과업마다 수행 방안 · 운영 계획"]},
        {"no": "3", "title": "결과물 제출 계획", "guide": ["결과물 내역과 제출 · 활용 계획"]}]},
    {"no": "Ⅳ", "title": "사업 관리 부문", "guide": [], "items": [
        {"no": "1", "title": "추진 일정 계획", "guide": ["사업 기간 안의 단계별 일정"]},
        {"no": "2", "title": "수행 조직 및 투입 인력", "guide": ["수행 조직 · 역할 · 업무 분장 · 보고 체계"]},
        {"no": "3", "title": "품질 및 보안 관리", "guide": ["품질 관리 · 기밀 보안 · 위험 대응"]}]},
)

#: 평가표 머리(11-06 넓힘) — 「기술능력평가 기준」 · 「평가항목 및 배점(기준 · 한도)」 · 「세부평가 항목 배점」 · 「제안서 세부 평가 기준」 ·
#: 「평가기준」 · 「배점 기준표」. 덩어리 머리이거나 짧은 줄만(지침 문장 속 「평가항목별 조견표를 작성」은 머리가 아니다).
_EVAL_HEAD_RE = re.compile(r"평가\s*(?:항목|요소|기준)|배점\s*(?:기준|한도)|평가표")
_EVAL_HEAD_CHARS = 30
EVAL_BLOCK_LIMIT = 400
#: 배점 줄 — 「5」 · 「5점」 · 「/ 5점」 · 「2.8」(소수는 등급 점수라 항목 배점이 아니다 — 이름 줄 뒤 「점」이 붙은 반 점 「2.5점」만 배점 · 1799826)
_POINTS_RE = re.compile(r"^/?\s*(\d{1,3}(?:\.\d+)?)\s*점?$")
_HALF_POINTS_RE = re.compile(r"^/?\s*\d{1,2}\.5\s*점$")
#: 영역(또는 항목) 배점 — 「(15점)」 · 「공통사항 (15점)」 · 「(20)」 · 「투입인력 전문성(10)」 · 「가. 정성평가(80점)」
_AREA_POINTS_RE = re.compile(r"^(.*?)\s*\(\s*(\d{1,3})\s*점?\s*\)$")
#: 한 줄 「: n점」 꼴 — 「① 제안업체 경영상태 : 5점」 · 「2) 정성적 평가 : 70점」(11-06 1793373)
_COLON_POINTS_RE = re.compile(r"^(.*?\S)\s*[:：]\s*(\d{1,3})\s*점\s*$")
#: 문장 끝에 붙은 배점 — PDF 표 「… 핵심성과(Outcome) 인식 20」(11-06 1718694)
_TRAILING_POINTS_RE = re.compile(r"^(.*[가-힣)])\s+(\d{1,2})$")
_TOTAL_RE = re.compile(r"^(?:합계|총계|총점|합계점수)(\d{1,3})?점?$")
_SUBTOTAL_RE = re.compile(r"^(?:소계|계)(\d{1,3})?점?$")
#: 분류 줄(「정량」 · 「평가」 · 「기술능력평가」 · 「정 성 평 가」) — 항목 이름이 아니라 종류(정량 · 정성 · 가격)를 정한다.
_CATEGORY_RE = re.compile(r"^(?:[가-하]\.|\d\)|ㅇ|○)?(?:기술(?:능력)?|정량(?:적)?|정성(?:적)?|입찰\s*가격|가격)?(?:평가|지표|분야)?(?:\(\d+%\)|\((?:상대|절대)\))?$")
#: 줄 앞 영역 배점(PDF 두 칸 표 「(10점) 실무책임자 및 참여 조직원의 경력 5」 · 1718694) — 정량 영역이면 그 배점이 정량 몫이다.
_LEAD_POINTS_RE = re.compile(r"^\(\s*(\d{1,3})\s*점\s*\)\s*")
#: 「회사채 · 기업어음 · 기업신용」 — 배점 칸 안에 끼인 신용등급 표의 머리 칸(11-13 동국대 — 정량 항목 이름이 「회사채」로 잡혔다).
_EVAL_HEADER_RE = re.compile(
    r"^(?:세부)?평가(?:항목|요소|기준|내용|부문|분야|등급)(?:\(.*\))?(?:배점(?:한도)?)?$|^배점(?:한도|기준|\(점\))?$|"
    r"^(?:구분|비고|한도|점수|평점|입찰업체|단위:?점|등급부여기준|심사분야|평가방법|배점의|회사채|기업어음|기업신용)$|"
    r"^(?:매우|아주)?(?:우수|보통|미흡|적합)$|^\(보통\)$")
#: 등급 · 구간 줄(「3.5억원 이상」 · 「70% 이상」 · 「BBB0 이상」 · 「AA+, AA0」 · 「5건 이상」 · 강제배분표 「3개」 · 1799826) — 항목 이름이 아니다.
_GRADE_RE = re.compile(r"\d\s*(?:%|건|억\s*원|만\s*원|천\s*원|년|명|개월)?\s*(?:이상|미만|이하|초과)|\d\s*(?:%|건)$|^[A-Z0-9][A-Z0-9+\-,.\s/~()]*$|"
                       r"^[A-Z][A-Z0-9+\-,\s]*(?:이상|이하)|^\d{1,3}\s*(?:개|개사|명|곳)$")
#: 정량 평가 항목 이름(분류 줄이 없거나 뒤에 올 때 · 「유사 구축 실적」 · 「경영상태」)
_QUANT_NAME_RE = re.compile(r"^(?:[①-⑳]\s*)?(?:경영\s*상태|재무|신용|(?:회사\s*)?유사\s*(?:사업|용역|구축)?\s*(?:수행\s*)?실적|(?:사업\s*)?수행\s*실적|인력\s*규모|신인도)")
#: 두 줄로 쪼개진 이름을 잇는 꼴(「채용기업 발굴」 + 「및 관리」 · 「그 밖의」 + 「지원사항」)
_EVAL_JOIN_END_RE = re.compile(r"(?:및|의|,|·|/)$")
_EVAL_JOIN_START_RE = re.compile(r"^(?:및|등|\()")
_SENTENCE_END_RE = re.compile(r"(?:다|함|음|임)\.?$")
#: 비고 칸 글(「제안요청서 참조」 · 1690926) — 앞 행 끝 칸이라 영역 이름이 아니다
_EVAL_REMARK_RE = re.compile(r"(?:참조|참고)$")
#: 표 머리 칸 — 「배점」 칸이 「세부내용 · 평가기준」 칸보다 앞이면 이름 · 배점 · 기준 차례로 나온다(1799826 「세부 평가항목 / 기본배점 / 세부내용」)
_POINTS_HEAD_RE = re.compile(r"^(?:기본)?배점(?:한도)?$")
_CRITERIA_HEAD_RE = re.compile(r"^(?:세부)?(?:평가)?(?:내용|기준|요소)$")


def _points_first(lines: list[str]) -> bool:
    """첫 배점 줄 앞 머리 칸에서 배점 칸이 기준 칸보다 앞인가."""
    at: dict[str, int] = {}
    for index, line in enumerate(lines):
        if _POINTS_RE.match(line.strip()):
            break
        words = _compact(line)
        for key, pattern in (("points", _POINTS_HEAD_RE), ("criteria", _CRITERIA_HEAD_RE)):
            if key not in at and pattern.match(words):
                at[key] = index
    return len(at) == 2 and at["points"] < at["criteria"]


def _kind_of(text: str) -> str | None:
    """「사업수행능력평가」 영역은 객관 평가(실적 · 인력 보유 점수표)라 정량이다(1796326 — 「정량」 낱말 없는 표).
    「계량평가」는 정량 · 「비계량 평가」는 정성이다(11-13 · 1822479 — 모두 정성으로 읽었다)."""
    words = _compact(text)
    measured = "계량" in words and "비계량" not in words
    return ("가격" if "가격" in words else "정량" if "정량" in words or measured or words.endswith("수행능력평가")
            else "정성" if "정성" in words or "비계량" in words else None)


def _flatten_vertical(block: list[str]) -> list[str]:
    """세로 글자(「기」 「술」 「평」 「가」)를 한 줄로 — 분류 줄로 읽는다."""
    out: list[str] = []
    run: list[str] = []
    for line in block:
        word = _compact(line)
        if len(word) == 1 and re.match(r"[가-힣]", word):
            run.append(word)
            continue
        if run:
            out.append("".join(run))
            run = []
        out.append(line)
    if run:
        out.append("".join(run))
    return out


def _segments(texts: list[str]) -> list[str]:
    """이어지는 줄을 잇는다 — 「및 」로 시작 · 「및 · 의 · ,」로 끝남 · 두 글자 이하 조각 · 괄호 줄 · 번호만 있는 줄(「1.」)."""
    segs: list[str] = []
    for text in texts:
        line = text.strip()
        if segs and (_EVAL_JOIN_END_RE.search(segs[-1]) or _EVAL_JOIN_START_RE.match(line) or len(_compact(line)) <= 2
                     or len(_compact(segs[-1])) <= 2):
            # 두 글자 이하 한글 조각 뒤는 낱말 중간 줄바꿈(「프로」 / 「젝트 관리」 · 1781608) — 띄우지 않고 잇는다
            glue = "" if re.fullmatch(r"[가-힣]{1,2}", segs[-1].strip()) and re.match(r"[가-힣]", line) and not _EVAL_JOIN_START_RE.match(line) else " "
            segs[-1] = f"{segs[-1]}{glue}{line}"
        else:
            segs.append(line)
    return segs


def _long(segment: str) -> bool:
    """평가 기준 문장 — 길거나(30자 넘음) 쉼표 목록이거나 문장 끝."""
    return len(_compact(segment)) > 20 or segment.count(",") >= 2 or bool(_SENTENCE_END_RE.search(segment))


def _name_from(texts: list[str]) -> tuple[str, str, list[str], list[str]]:
    """(이름, 앞 조각(영역 단서), 앞 항목에 붙일 기준, 이 항목 기준). 앞의 긴 줄은 배점이 먼저 온 표의 앞 항목 기준(11-06 1731641)."""
    segs = _segments(texts)
    i = 0
    while i < len(segs) and _long(segs[i]):
        i += 1
    j = i
    while j < len(segs) and not _long(segs[j]):
        j += 1
    if i == j:  # 짧은 조각이 없다 — 첫 줄을 이름으로
        return segs[0][:80] if segs else "", "", [], segs[1:]
    shorts = segs[i:j]
    return shorts[-1], " ".join(shorts[:-1]), segs[:i], segs[j:]


#: 평가 주체 비고 칸(「담당 (사업) 부서」 · 「심사 위원 평가」) — 항목 이름 · 영역이 아니다(11-13 · 1828362 — 「담당 (사업) 부서 이행실적」이 이름이 됐다)
_EVAL_WHO_RE = re.compile(r"^(?:담당|사업|주관)?(?:\(사업\))?부서(?:평가|확인)?$|^(?:심사|평가)위원(?:회)?(?:평가)?$")


def _evaluator_cells(lines: list[str]) -> set[int]:
    """평가 주체 비고 칸 줄 차례 — 칸 안 줄바꿈으로 짧은 조각 두세 줄(「담당」 「(사업)」 「부서」)로 나오기도 한다."""
    found: set[int] = set()
    for index in range(len(lines)):
        for size in (3, 2, 1):
            chunk = [_compact(line) for line in lines[index:index + size]]
            if len(chunk) == size and all(len(c) <= (8 if size == 1 else 4) for c in chunk) and _EVAL_WHO_RE.match("".join(chunk)):
                found.update(range(index, index + size))
                break
    return found


def _one_head_bullet(entries: list[tuple[str, str, str]]) -> bool:
    """글머리 줄 하나 + 그 아래 다른 글머리 세부 줄뿐(「o 사업 기획」 / 「- 유사 사업 …」) — 한 항목의 이름과 기준이다(11-13 · 1828362)."""
    return bool(entries) and all(e[0] == "B" for e in entries) and all(e[2] != entries[0][2] for e in entries[1:])


def _parse_evaluation(block: list[str], *, stops: tuple[re.Pattern[str], ...] = ()) -> dict[str, Any]:
    """평가표 → {items: [{area, name, criteria, points, kind}], total, text}. 칸마다 한 줄로 나온 표를 줄 단위로 읽는다(11-06 꼴 넓힘):

    - 배점: 「5」 · 「5점」 · 「/ 5점」 · 「(20)」 · 「: 5점」 · 문장 끝 「… 인식 20」 · 이름 줄 뒤 반 점 「2.5점」. 그 밖의 소수 · 이름 없이
      뒤따르는 숫자(수우미양가 5 4 3 2 1) · 소계는 버린다. 머리 칸이 「배점」 → 「세부내용」 차례면 이름 · 배점 · 기준 차례로 읽는다.
    - 이름: 글머리 없는 줄이 이름(여러 줄이면 잇거나 마지막 조각) · 그런 줄이 없으면 첫 글머리 줄. 이름 앞의 글머리 줄 · 긴 줄은
      배점이 먼저 온 표의 앞 항목 기준이다. 「(5)」 바로 뒤 기준 · 같은 배점이면 그 「(5)」 줄 이름이 항목이다(1805118).
    - 종류: 분류 줄 · 영역 이름의 정량 · 정성 · 가격. 가격 항목은 싣지 않고 합계에만 센다 — 가격까지 100점이 되면 표가 끝났다.
    영역 배점이 있으면 영역마다 항목 합이 맞아야 하고, 셋 미만 · 합 100 초과면 항목을 비운다(원문 글은 남긴다).
    「※」 · 「*」 주석 줄은 이름 · 영역 · 배점 후보가 아니다 — 등급 소표 아래 「※ 신용평가등급은 …」이 소표 점수를 항목으로 닫았다(11-13 동국대) ·
    「* 관련 증빙서류가 있는 경우에만 인정」이 항목 이름이 됐다(11-13 · 1822479).
    기준 글로만 남긴다: 만드는 중인 항목이 있으면 그 항목 · 아니면 바로 앞 항목(1793373 「① 제안업체 경영상태」 기준 두 줄) · 첫 항목 앞은 버린다."""
    kept: list[str] = []
    notes_at: dict[int, list[str]] = {}  # kept 차례 → 그 앞의 「※」 · 「*」 줄
    for line in block:
        if re.match(r"\s*(?:※|\*(?!\*))", line):
            notes_at.setdefault(len(kept), []).append(line.strip())
        else:
            kept.append(line)
    lines: list[str] = []
    remarks: dict[int, list[str]] = {}  # lines 차례 → 그 앞의 「※」 줄
    start = 0
    for cut in sorted(notes_at):
        lines += _flatten_vertical(kept[start:cut])
        remarks[len(lines)], start = notes_at[cut], cut
    lines += _flatten_vertical(kept[start:])
    who = _evaluator_cells(lines)
    remark: list[str] = []  # 만드는 중인 항목에 붙일 「※」 줄
    items: list[dict[str, Any]] = []
    areas: list[dict[str, Any]] = []
    current: int | None = None
    pending: list[tuple[str, str, str]] = []  # (T · B, 글, 글머리)
    kind = "정성"
    category: list[str] = []
    hint = ""
    running = 0
    skip_number = False
    stop = False
    closed = False  # 합계 줄 · 100점에서 닫혔다(넘쳐서 멈춘 것이 아니다)
    first_lead: int | None = None  # 첫 항목 앞에 쌓인 줄 수 — 머리와 표가 가까울수록 그 표의 머리다
    trailing = 0  # 「… 인식 20」 꼴로 읽은 항목 수(PDF 두 칸 표)
    segment = 0  # 마지막 분류 줄 뒤 첫 항목 — 뒤에 붙은 분류가 종류를 정할 범위
    # 정량 몫(정량 영역 배점) — 정량 항목 합이 채우면 정량 상태가 끝난다(다음 영역 줄에 분류 낱말이 없어도 · 1718694)
    quant_cap: int | None = None
    quant_from: int | None = None
    seen = 0  # 앞 줄까지의 항목 수 — 바로 앞 줄이 항목을 닫았는가
    after_item: dict[int, str] = {}  # 항목 바로 뒤 분류 줄(「사업이해도」 「7」 「정성평가(상대)」 — 종류 칸이 뒤에 오는 표 · 1782053)
    frags: list[str] = []  # 바로 앞까지 이어진 세 글자 이하 한글 줄(분류 줄 포함) — 세로로 쪼갠 영역 칸
    points_first = _points_first(lines)
    split_seen = False  # 짧은 줄을 [영역 단서, 이름]으로 가른 항목이 있었다 — 영역 칸이 있는 표
    two_col = False  # 이름 한 줄 + 글머리 기준 항목이 있었다 — 이름 칸 · 기준 칸만 있는 표
    bullet_hint = False  # 지금 영역 단서가 「글 줄 = 영역 · 글머리 줄 = 이름」 칸에서 왔다
    numbered: list[tuple[str, str, str]] | None = None  # 「4.」 번호 줄 바로 뒤에 쌓인 pending(같은 목록일 때만 — 새 목록이면 지난 일)

    def carry(texts: list[str]) -> None:
        if items and texts:
            items[-1]["criteria"].extend(texts)

    def area_name() -> str:
        return areas[current]["name"] if current is not None else ""

    def add(name: str, points: float, criteria: list[str], area_hint: str) -> None:
        nonlocal running, stop, hint, closed, first_lead, kind, quant_cap, quant_from
        criteria, remark[:] = criteria + remark, []
        if kind == "가격":
            running += points
            closed = closed or running == 100
            stop = stop or running >= 100
            return
        if running + points > 100:
            stop = True
            return
        hint = (area_hint if not _EVAL_REMARK_RE.search(_compact(area_hint)) else "") or hint
        first_lead = len(pending) if first_lead is None else first_lead
        label = " · ".join(dict.fromkeys(p for p in (area_name(), hint) if p))
        item_kind = "정량" if kind == "정량" or _QUANT_NAME_RE.match(_compact(name)) else "정성"
        quant_from = (len(items) if quant_from is None else quant_from) if kind == "정량" else None
        items.append({"area": label, "name": _tidy(name), "criteria": criteria, "points": points, "kind": item_kind, "_area": current})
        if current is not None:
            areas[current]["count"] += 1
        running += points
        closed = running == 100
        stop = running >= 100
        if kind == "정량" and quant_cap and sum(i["points"] for i in items[quant_from:]) >= quant_cap:
            kind, quant_cap, quant_from = "정성", None, None

    def close(points: float) -> None:
        nonlocal pending, current, hint, split_seen, two_col, bullet_hint
        swap: tuple[str, str] | None = None
        from_bullet = False
        bullets = [p for p in pending if p[0] == "B"]
        texts = [p for p in pending if p[0] == "T"]
        if not pending:
            return  # 배점 뒤 등급 점수 · 소계 — 버린다
        if not texts and current is not None and areas[current]["count"] == 0 and areas[current]["points"] == points and areas[current]["fresh"]:
            # 「사업 이해도」 · 「(5)」 · 기준 · 「/ 5점」 — 「(5)」는 영역이 아니라 이 항목 배점이었다
            name = areas.pop(current)["name"]
            current = len(areas) - 1 if areas else None
            add(name, points, [p[1] for p in bullets], "")
            pending = []
            return
        first = pending[0]
        markers = [p[2] for p in bullets]
        lead_bullet = next((n for n, p in enumerate(pending) if p[0] == "B"), None)
        dashes = 1  # 이름이 되는 앞 글머리 줄 수
        if lead_bullet is not None and numbered is pending and markers[0] in "-–" and len(set(markers)) > 1:
            # 「4.」 / 「안전 및 추가 제안」 / 「- 창의적 운영 방안」 / 「- 헬스케어 서비스」 / 「·매우우수…」 — 번호 머리 행의 앞 「-」 줄이 모두
            # 이 항목 이름이다(1690926 — 다른 행은 「-」 한 줄이 이름)
            while lead_bullet + dashes < len(pending) and pending[lead_bullet + dashes][2] == markers[0]:
                dashes += 1
        prev = items[-1] if items else None
        unswap = _one_head_bullet(pending) and bool(prev and prev.get("_swap") and prev["_area"] == current)
        if (lead_bullet is not None and markers.count(markers[0]) == dashes and len(set(markers)) > 1
                and (lead_bullet == 0 or markers[0] in "-–") and not unswap):
            # 「- 경영상태」 · 「· 신용평가등급 확인서」 — 글머리가 둘이면 첫 글머리 줄이 이름 · 앞 글은 영역 · 비고 칸(1690926).
            # 앞에 이름 글이 있는 「o 기준」 · 「- 세부」 꼴은 기준의 위아래라 그대로 둔다
            before = _name_from([p[1] for p in pending[:lead_bullet]])[0] if lead_bullet else ""
            name = " · ".join(p[1] for p in pending[lead_bullet:lead_bullet + dashes])
            extra, crit = before, [p[1] for p in pending[lead_bullet + dashes:]]
        else:
            lead = 0
            while lead < len(pending) and pending[lead][0] == "B":
                lead += 1
            if lead == len(pending):
                name, extra, crit = first[1], "", [p[1] for p in pending[1:]]
                if unswap and prev:
                    # 「일반부문」 / 「∘경영상태」 / 5 / 「∘사업 수행실적」 / 10 — 같은 영역 둘째 항목이 글머리 한 줄뿐이면 이 칸은 글머리 줄이
                    # 이름이고 앞 항목의 글 줄은 영역 칸이다(첫 항목 이름이 「일반부문」이 되던 것 · 1697240 · 1733478 · 1802078).
                    # 글머리 줄 아래 다른 글머리 세부(「o 제안내용」 / 「- …」)도 한 줄로 친다(11-13 · 1828362 「사업수행 능력」 / 「o 사업 기획」)
                    head, bullet_name = prev.pop("_swap")
                    prev.update(name=_tidy(bullet_name), criteria=prev["criteria"][1:],
                                area=" · ".join(dict.fromkeys(p for p in (area_name(), head) if p)))
                    if _QUANT_NAME_RE.match(_compact(bullet_name)):
                        prev["kind"] = "정량"
                    extra, from_bullet = head, True
            else:
                carry([p[1] for p in pending[:lead]])
                rest = pending[lead:]
                run = 0
                while run < len(rest) and rest[run][0] == "T":
                    run += 1
                if points_first:
                    # 이름 · 배점 · 기준 차례 표 — 앞 줄은 앞 항목 기준이고 배점 바로 앞 조각이 이름이다(짧은 두 조각이면 칸 줄바꿈 「상호운용성」 / 「요구사항」)
                    segs = _segments([p[1] for p in rest[:run]])
                    cut = len(segs) - 2 if len(segs) >= 2 and all(len(_compact(s)) <= 6 for s in segs[-2:]) else len(segs) - 1
                    name, extra, before, after = " ".join(segs[cut:]), "", segs[:cut], []
                else:
                    name, extra, before, after = _name_from([p[1] for p in rest[:run]])
                shorts = len(_segments([p[1] for p in rest[:run]])) - len(before) - len(after)
                bulleted = run < len(rest) and rest[run][0] == "B"
                if extra and shorts == 2 and bulleted and two_col and not split_seen:
                    # 영역 칸 없는 표(앞 항목이 이름 한 줄 + 글머리 기준)의 짧은 두 줄은 칸 안 줄바꿈 — 「제안요청」 / 「내용 이해도」 ·
                    # 「참여인력」 / 「전문성」(앞 조각이 영역 단서로 뒤 항목에 이어지던 것 · 1802078)
                    name, extra = f"{extra} {name}", ""
                split_seen = split_seen or bool(extra)
                two_col = two_col or (not extra and shorts == 1 and bulleted)
                if bullet_hint and not extra:
                    hint, bullet_hint = "", False  # 글머리 줄이 이름인 영역 뒤 새 글 줄 — 앞 영역 칸을 물려받지 않는다(1802078 「참여인력 전문성」)
                if numbered is pending and not extra and hint:
                    extra = name  # 「4.」 / 「안전 및 추가 제안」 — 번호 머리 행은 영역이자 항목(앞 영역 「연수 운영」을 물려받던 것 · 1690926)
                if lead == 0 and not extra and not before and not after and _one_head_bullet(rest[run:]):
                    swap = (name, rest[run][1])  # 다음 항목이 글머리 한 줄(+ 다른 글머리 세부)뿐이면 뒤집는다
                carry(before)
                crit = after + [p[1] for p in rest[run:]]
        if extra:
            bullet_hint = from_bullet
        count = len(items)
        add(name, points, crit, extra)
        if swap and len(items) > count:
            items[-1]["_swap"] = swap
        pending = []

    for index, line in enumerate(lines):
        text = line.strip()
        words = _compact(text)
        if stop:
            if items and len(items) > seen and _CATEGORY_RE.match(words) and _kind_of(words) in ("정량", "정성"):
                after_item[len(items) - 1] = _kind_of(words) or ""  # 100점에 닿은 마지막 항목 뒤 종류 칸
            break
        if index in remarks and items:  # 만드는 중인 항목이 있으면 그 항목 · 없으면 바로 앞 항목(첫 항목 앞 「※」 — 가격 평가 · 표 안내 — 는 버림)
            if pending:
                remark.extend(remarks[index])
            else:
                carry(remarks[index])
        if (not words or not re.search(r"[가-힣A-Za-z0-9]", words) or _joined(lines, index) or _EVAL_HEADER_RE.match(words)
                or index in who):
            continue
        follows_item, seen = len(items) > seen, len(items)
        # 「…평가」로 끝난 조각에서 한 칸이 끝난다(「정량」 「평가」 | 「경영」 「상태」 「(5)」 · 1781608)
        run, frags = frags, (([] if frags and frags[-1].endswith("평가") else frags) + [words] if re.fullmatch(r"[가-힣]{1,3}", words) else [])
        if (m := _TOTAL_RE.match(words)):
            if items:
                closed = True
                break
            skip_number = m.group(1) is None
            continue
        if (m := _SUBTOTAL_RE.match(words)):
            skip_number = m.group(1) is None
            continue
        if items and (_ROMAN_ONLY_RE.match(text) or _FORM_MARK_RE.match(text) or any(s.match(text) for s in stops)):
            break
        if (m := _POINTS_RE.match(text)):
            value = m.group(1)
            half = bool(_HALF_POINTS_RE.match(text)) and any(p[0] == "T" for p in pending)
            if skip_number or ("." in value and not half):
                if "." in value:
                    pending = []  # 등급 점수 줄
                skip_number = False
                continue
            if float(value) > 100:
                break
            close(float(value) if half else int(value))
            continue
        skip_number = False
        if (m := _AREA_POINTS_RE.match(text)) and not _GRADE_RE.search(m.group(1)) and not _BULLET_RE.match(text):
            # 글머리 줄 끝의 「(1점)」은 등급 점수 안내(「·매우우수(5점), … 아주미흡(1점)」 · 1690926)지 영역 배점이 아니다
            own = m.group(1).strip()
            texts = [p[1] for p in pending if p[0] == "T"]
            carry([p[1] for p in pending if p[0] == "B"])
            if own:
                carry(texts)
                name = own
            elif len(run) >= 2:
                # 세로로 쪼갠 칸 「사업」 「수행」 「능력」 「평가」 「(20)」 — 끝 조각 「평가」를 분류 줄로 읽어 앞 조각을 버리고
                # 영역을 「평가」로 적던 것(1796326 · 1802078). 짧은 줄을 모두 잇는다.
                carry([t for t in texts if _compact(t) not in run])
                name = "".join(f" {r} " if r == "및" else r for r in run).strip()  # 「성능」 「및」 「규격」 → 「성능 및 규격」
            elif texts:
                name, extra, before, _after = _name_from(texts)
                carry(before)
                segs = _segments(texts)
                k = len(segs)
                while k and not _long(segs[k - 1]):
                    k -= 1
                if 0 < k < len(segs):
                    # 긴 글 뒤에 짧은 줄이 남았다 — 「(20)」 바로 앞 짧은 줄이 영역 이름이다
                    # (「사업명」 / 「2027년 … 지원」 / 「전략 및 방법론」 / 「(20)」 — 표 머리 「사업명」을 잡던 것 · 1805118)
                    name, extra = segs[-1], " ".join(segs[k:-1])
                open_area = current is not None and sum(i["points"] for i in items if i["_area"] == current) < areas[current]["points"]
                if extra and open_area and " " not in extra + name and len(extra) <= 6 and len(name) <= 6:
                    # 표 칸 줄바꿈 「연구반」 / 「운영역량」 / 「(10)」 → 「연구반운영역량」(1805118). 앞 영역(「전문성(20)」)이 아직 덜 찼을 때만 —
                    # 영역이 없거나 찼으면 앞 조각은 배점 없는 영역 칸이다(「사업수행」 / 「교육운영역량」 / 「(10)」 · 11-06 3차 검토 #11)
                    name = extra + name
            else:
                name = " ".join(category)
            pending = []
            if (found := _kind_of(name) or _kind_of(" ".join(category))):
                kind = found
                quant_cap = int(m.group(2)) if found == "정량" else None
            areas.append({"name": _tidy(name), "points": int(m.group(2)), "count": 0, "fresh": True})
            current = len(areas) - 1
            hint = ""
            category = []
            continue
        if (m := _COLON_POINTS_RE.match(text)):
            name, points = m.group(1).strip(), int(m.group(2))
            carry([p[1] for p in pending])
            pending = []
            if _compact(name).endswith("평가"):  # 「1) 정량적 평가 : 20점」 — 분류
                kind = _kind_of(name) or ("정성" if "기술" in name and kind == "가격" else kind)
                quant_cap = points if kind == "정량" else None
                if kind == "가격":
                    running += points
                continue
            add(re.sub(r"^\s*(?:ㅇ|○|-)\s*", "", name), points, [], "")
            continue
        if (m := _TRAILING_POINTS_RE.match(text)) and len(re.findall(r"[가-힣]", m.group(1))) >= 3 and not _GRADE_RE.search(m.group(1)):
            label = m.group(1).strip()
            texts = [p[1] for p in pending if p[0] == "T"]
            pending = []
            first_word = label.split()[0]
            if _CATEGORY_RE.match(_compact(first_word)) and _kind_of(first_word):
                kind = _kind_of(first_word) or kind  # PDF 두 칸이 섞인 줄 앞 「정량적 …」
            if (lead := _LEAD_POINTS_RE.match(label)):
                label = label[lead.end():]  # 「(10점) 실무책임자 …」 — 앞 칸 영역 배점
                if kind == "정량" and quant_cap is None:
                    quant_cap = int(lead.group(1))
            name = (texts[-1] if texts else label) if _CATEGORY_RE.match(_compact(label)) else label
            add(name, int(m.group(2)), [], texts[-1] if texts and name != texts[-1] else "")
            trailing += 1
            continue
        if _CATEGORY_RE.match(words):
            following = next((n.strip() for n in lines[index + 1:] if n.strip()), "")
            if not (pending and all(_compact(p[1]) in run for p in pending) and re.fullmatch(r"\(\s*\d{1,3}\s*점?\s*\)", following)):
                # 「제안서」 / 「평가」 / 「(60)」 — 세로로 쪼갠 영역 칸 조각은 앞 항목 기준이 아니다(1796326 「기술인력 보유상태」 기준에 「제안서」)
                carry([p[1] for p in pending])
                pending = []
            label = _kind_of(words)
            if follows_item and label in ("정량", "정성"):
                after_item[len(items) - 1] = label
            after = _POINTS_RE.match(following)
            if (label in ("정량", "정성") and after and "." not in after.group(1) and items[segment:]
                    and sum(i["points"] for i in items[segment:]) == int(after.group(1))):
                # 항목 뒤에 붙은 분류 · 소계(「정 량 평 가」 / 「15」 · 1697240) — 앞 항목들의 종류다
                for item in items[segment:]:
                    item["kind"] = label
                segment = len(items)
                skip_number = True
                continue
            kind = label or ("정성" if "기술" in words and kind == "가격" else kind)
            quant_cap = None if kind != "정량" else quant_cap
            segment = len(items)
            category.append(text)
            if current is not None:
                areas[current]["fresh"] = False
            continue
        if re.fullmatch(r"\d{1,2}\.", words) and not pending:
            numbered = pending
        if _GRADE_RE.search(text):
            continue
        category = []
        bullet = _BULLET_RE.match(text)
        pending.append(("B", bullet.group(1), text.lstrip()[:1]) if bullet else ("T", text, ""))
    carry([p[1] for p in pending if p[0] == "B" or points_first])  # 이름 · 배점 · 기준 차례 표는 끝 항목 기준까지
    if len(after_item) >= 3 and len(after_item) * 3 >= len(items) * 2:
        # 종류 칸이 항목 뒤에 오는 표 — 항목마다 바로 뒤 분류가 그 항목의 종류다(1782053 「시스템 요구사항」 「5」 「정성평가(상대)」)
        for at, label in after_item.items():
            items[at]["kind"] = label
    # PDF 두 칸 표(항목 절반 이상이 「문장 끝 배점」)는 영역 줄 「(80점)」이 엉뚱한 자리에 섞인다 — 영역 합 대신 가격까지 100점에서 닫혔는지 본다(1718694)
    merged = trailing * 2 >= len(items) and running == 100
    points = [i["points"] for i in items]
    # 배점 칸이 1 · 2 · 3 … 차례 수열이면 평가표가 아니라 산출물 · 서식 목록의 순번이다(1799826 별첨 표)
    numbered = len(points) >= 3 and 2 * sum(1 for a, b in zip(points, points[1:]) if b == a + 1) >= len(points) - 1
    if len(items) < 3 or numbered or not _evaluation_adds_up(items, [] if merged else areas):
        items = []
    for item in items:
        item.pop("_area", None)
        item.pop("_swap", None)
        if merged:
            item["area"] = ""  # PDF 두 칸 표는 영역 줄 · 앞 조각이 다른 칸 글이다(1718694 · 1764360) — 엉뚱한 조각보다 빈칸
    total = sum(i["points"] for i in items) if items else None
    return {"items": items, "total": int(total) if total is not None and total == int(total) else total,
            "text": "\n".join(block)[:EVAL_TEXT_LIMIT], "closed": closed, "lead": first_lead or 0}


def _evaluation_adds_up(items: list[dict[str, Any]], areas: list[dict[str, Any]]) -> bool:
    """읽은 배점이 맞는가 — 항목이 들어간 영역마다 항목 합 = 영역 배점 · 전체 100 이하. 틀리면 조견표를 만들지 않는다(11-03 검토:
    배점이 기준보다 먼저 오는 표 · 글머리 없는 정량 항목에서 이름 · 배점이 한 칸씩 밀렸다). 원문은 그대로 AI 에 간다."""
    if any(not isinstance(i.get("points"), (int, float)) or not i.get("name") for i in items):
        return False
    if sum(i["points"] for i in items) > 100:
        return False
    for index, area in enumerate(areas):
        own = [i["points"] for i in items if i.get("_area") == index]
        if own and sum(own) != area["points"]:
            return False
    return True


def read_evaluation(text: str) -> dict[str, Any]:
    """기술능력 평가 기준 → {items: [{area, name, criteria, points, kind}], total, text}. 셋 미만이면 items 는 빈 목록(글은 남긴다)."""
    found = locate_evaluation([_text_doc(text)])
    return {key: found[key] for key in ("items", "total", "text")}


def _eval_heads(lines: list[str]) -> list[int]:
    toc = _doc_toc_span(lines)
    return [i for i, line in enumerate(lines)
            if _EVAL_HEAD_RE.search(line) and not _TOC_PAGE_RE.search(line) and not _joined(lines, i)
            and (_BLOCK_RE.match(line) or len(_compact(line)) <= _EVAL_HEAD_CHARS) and not (toc and toc[0] <= i <= toc[1])
            # 문장 「□ 제안 요청 내용의 순서는 제안서 평가 기준 순서와 동일함.」은 머리가 아니다(뒤 요구사항 표의 순번을 배점으로 읽었다 · 1799826)
            and not _SENTENCE_END_RE.search(line.strip())]


def locate_evaluation(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """원문 여러 개에서 평가표를 찾는다 — 머리마다 읽어 배점이 맞는(합 · 영역 합) 것 중 항목이 가장 많은 것(같으면 앞 문서 · 앞 머리).
    맞는 표가 없으면 항목 없이 첫 머리(합계로 닫힌 머리가 있으면 그 머리) 아래 글만(AI 에 원문으로 보낸다). → {items, total, text, where}"""
    best: tuple[tuple[bool, int, int], int, dict[str, Any]] | None = None
    first: dict[str, Any] | None = None
    for order, doc in enumerate(docs):
        lines, pages = _doc_lines(doc)
        for head in _eval_heads(lines):
            block: list[str] = []
            for line in lines[head + 1:head + 1 + EVAL_BLOCK_LIMIT]:
                # 다음 덩어리 머리 · 괄호 없는 별첨 머리(「별첨 14.」 — 부록 표의 순번을 배점으로 읽지 않게 · 1799826)
                if (_BLOCK_RE.match(line) and len(_compact(line)) <= _BLOCK_HEAD_CHARS) or _ANNEX_RE.match(line):
                    break
                if line:
                    block.append(line)
            result = _parse_evaluation(block, stops=_head_stops(lines, head))
            result["where"] = {"document": doc.get("name"), "page": pages[head], "head": lines[head][:80]}
            # 합계 · 100점에서 닫힌 표가 먼저(넘쳐 멈춘 표는 다른 글을 섞어 읽었다) · 항목 많은 것 · 머리와 표가 가까운 것(1718593)
            rank = (result["closed"], len(result["items"]), -result["lead"])
            if result["items"] and (best is None or rank > best[0]):
                best = (rank, order, result)
            elif result["text"] and (first is None or (result["closed"] and not first["closed"])):
                # 못 읽었을 때 안내 위치 — 합계 · 100점에서 닫힌 표의 머리가 먼저(첫 머리 등급 기준표를 가리키던 것 · 1799826)
                first = result
    if best:
        return best[2]
    return first or {"items": [], "total": None, "text": "", "where": None}


#: 형식 규정(11-06 A-4) — 쪽수 상한 · 평가본 회사 식별정보 금지 · 가로 · PPT · 정량 · 정성 두 권.
#: 단위 「P」는 같은 마디 앞에 제안서 · 본문 · 분량이 있고 제목 · 글자 크기가 없을 때만 쪽이다(「제안서 1부(20P 이내」 · 1757039 —
#: 「표지제목 24P 이하」 · 1718694 는 글자 크기). 「페이지 80쪽 제한」(1719764)도 상한이다 — 「분량제한 없음」은 아니다(11-06 3차 검토 #15).
#: 단위 「장」(「매수 : 표지 및 간지 포함 25장 이내」 · 11-13 동국대)은 같은 마디에 제안서 · 본문 · 분량 · 매수 · 표지 · 간지가 있을 때만 —
#: 「사진은 5장 이내」 · 「제5장」 · 「결과보고서는 표지 포함 30장」 · 「교재 … 50장」은 아니다. 「P」의 단서는 그대로(「표지 24P」는 글자 크기).
_PAGE_LIMIT_RE = re.compile(r"(\d{1,3})\s*(?:페이지|쪽|page|매|(P|장))\s*(?:\([^)]{0,40}\))?\s*(?:을|를)?\s*"
                            r"(?:이내|이하|내외|넘지|초과\s*(?:금지|불가)|제한(?!\s*없))", re.I)
_P_UNIT_OK_RE = re.compile(r"제안서|본문|분량")
_P_UNIT_NOT_RE = re.compile(r"제목|글자|글씨|폰트|크기|포인트")
_SHEET_UNIT_OK_RE = re.compile(r"제안서|본문|분량|매수|표지|간지")
_SHEET_UNIT_NOT_RE = re.compile(r"제목|글자|글씨|폰트|크기|포인트|사진|그림|보고서|교재|결과물|산출물")
#: 평가본(회사 식별 금지) — 문장마다 본다(11-06 검토: 맨 「미표기」가 주민등록번호 줄 · 익명신고 줄에 걸렸다).
#: ① 식별 낱말 … 표기 · 기재 · 표시 · 공개 · 사용 … 금지 · 하지 않 · 하여서는 안(「기재하지 않은 경우 불이익」은 반드시 적으라는 말이라 뺀다)
#: ② 「표기되지 않은 평가용 사본」 ③ 식별 낱말 … 삭제 · 제외하고(「사본 9부 업체명 삭제,」) ④ 「미표기 · 미기재 · 무기명」 —
#: ①~④는 같은 문장에 제안서 · 사본 · 평가용 · 평가본 · 표지 · 「n부」가 있을 때만(발표 자료만 가리는 줄은 제안서 형식이 아니다)
#: ⑤ 「블라인드 평가」 · 「(블라인드)」 — 「블라인드 평가가 아닙니다 · 미적용」은 뺀다. 주민등록 · 신고 · 익명 · 청렴 · 부패 줄은 보지 않는다.
_BLIND_ID = r"(?:업체명|회사명|제안사명|상호|로고|대표자|식별|제안사를|제안업체를|업체를|업체\s*정보|제안사\s*표시)"
_NOT_CASE = r"(?!은\s*경우|을\s*경우|는\s*경우|으면)"
_BLIND_RE = re.compile(
    rf"{_BLIND_ID}[^\n]{{0,60}}?(?:표기|기재|표시|공개|사용)[^\n]{{0,20}}?"
    rf"(?:금지|불가|하지\s*않{_NOT_CASE}|(?:하여|해)서는\s*안|말\s*것|안\s*함|할\s*수\s*없)"
    rf"|{_BLIND_ID}[^\n]{{0,40}}?(?:표기|기재|표시)되지\s*않은\s*(?:평가용|사본|제안서)"
    rf"|{_BLIND_ID}[^\n]{{0,60}}?(?:삭제|제외)(?:\s*(?:하여야|하여|하고|하며|후|한\s*후)|\s*[,)]|\s*$)|식별\s*정보[^\n]{{0,20}}삭제"
    r"|미표기|미기재|무기명")
_BLIND_CTX_RE = re.compile(r"제안서|사본|평가용|평가본|표지|\d\s*부")
_BLIND_OPEN_RE = re.compile(r"블라인드\s*(?:평가|심사|방식)(?![^\n]{0,8}(?:아니|아닙|아님|미적용|미실시|않|없))|\(\s*블라인드\s*\)")
_BLIND_SKIP_RE = re.compile(r"주민\s*등록|신고|익명|청렴|부패")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[다함음됨임]\.)\s*|(?<=[다함음됨임])\s+(?=[①-⑳※*]|-\s|[가-하]\.\s|\(\S\)\s)")
#: ⑥ 「업체명 … 모두 블라인드 처리 후 제출」(1744426 — 제출서류 표 「제안서(제안서 표지 및 제안서)」 칸 아래 줄) — 맥락은 바로 위 두 줄까지 본다.
#: 「블라인드 처리 필요 없음」 · 발표 자료 칸 아래 줄은 아니다(11-06 3차 검토 #14).
_BLIND_PROC_RE = re.compile(rf"{_BLIND_ID}[^\n]{{0,60}}?블라인드\s*처리(?![^\n]{{0,10}}(?:필요\s*없|없|아님|않))")
_PRESENTATION_RE = re.compile(r"발표")
#: ⑦ 「제안사 · 업체 · 회사를 식별할 수 있는 정보(업체명 등)는 포함하지 않음」(11-13 동국대 작성요령 표) — 그 말이 제안서 규정이라
#: 맥락 낱말 없이 받는다. 제안사 · 업체가 「식별」의 목적어일 때만(사이 틈 없음 — 「수행업체는 교육생 개인을 식별할 수 있는 정보를 …
#: 포함하지 않아야」는 개인정보 규정 · 11-13 T1 검토). 발표 자료(그 줄 · 바로 위 두 줄) · 「… 기재한 경우 감점」은 아니다.
_BLIND_SUBJECT_RE = re.compile(rf"(?:제안사|제안업체|업체|회사)\s*(?:를|을)?\s*식별[^\n]{{0,30}}?(?:포함|기재|표기|작성)[^\n]{{0,10}}?"
                               rf"(?:하지\s*않{_NOT_CASE}|금지|불가|(?:하여|해)서는\s*안)")
#: 평가본 규정의 원본 · 사본 구분(2.10.0 D8) — 규정 줄이나 바로 위 두 줄에 이 낱말이 하나도 없으면 평가본이 곧 제출 파일(`blind_only`).
#: 「제안서 10부(업체명 미기재)」처럼 부수만 있어도 · 「평가본」(원본과 짝인 말 · T6 검토)도 구분 있음으로 본다(근사 — 틀리면 지금처럼 회사명 판이 「제출용」).
_SPLIT_WORDS = r"(?:원본|사본|정본|부본|평가본|평가용)"
_COPIES_N = r"\d\s*부(?!터|서|처|문)"
_BLIND_SPLIT_RE = re.compile(rf"{_SPLIT_WORDS}|{_COPIES_N}")
#: 규정 줄과 떨어진 제출 수량 줄(「사업제안서 및 … 요약본 각 9부(원본 각 1부 별도)」 · 1793373)도 구분이다(T6 검토) —
#: 제안서와 구분 낱말이 가까이 있고 그 줄에 「n부」가 있을 때만(「사업자등록증 사본 1부」는 제안서가 아니다).
_BLIND_COPIES_RE = re.compile(rf"제안서[^\n]{{0,30}}?{_SPLIT_WORDS}|{_SPLIT_WORDS}[^\n]{{0,10}}?제안서")
_COPIES_N_RE = re.compile(_COPIES_N)
#: 평가본 문장이 줄 바꿈으로 쪼개진 꼴(「… 회사 식별」 / 「정보를 제외하고 작성할 것」 · 1770994) — 말끝이 아니면 다음 줄을 잇는다(#13).
_CLAUSE_END_RE = re.compile(r"[다함음임됨것.)]\s*$")
_NEW_ITEM_RE = re.compile(r"^\s*(?:[※*\-□■【\[<(]|\d|[가-하]\s*[.)]|[①-⑳])")


def _blind_line(line: str, before: str = "") -> str | None:
    """평가본(회사 식별 금지) 규정 문장 — 문장마다 꼴 · 맥락을 본다. `before` = 바로 위 두 줄(표 칸 이름). 없으면 None."""
    if _BLIND_SKIP_RE.search(line):
        return None
    for part in _SENTENCE_SPLIT_RE.split(line):
        hit = _BLIND_OPEN_RE.search(part) or (_BLIND_CTX_RE.search(part) and _BLIND_RE.search(part))
        if not hit and (proc := _BLIND_PROC_RE.search(part)) and not _PRESENTATION_RE.search(part + before) \
                and (_BLIND_CTX_RE.search(part) or _BLIND_CTX_RE.search(before)):
            hit = proc
        if not hit and (subject := _BLIND_SUBJECT_RE.search(part)) and not _PRESENTATION_RE.search(part + before):
            hit = subject
        if hit:
            return part if len(part) <= _NOTE_CHARS else part[max(0, hit.start() - 40):]  # 표가 이어 붙은 긴 줄은 걸린 곳 앞뒤만
    return None


def _blind_at(lines: list[str], index: int) -> str | None:
    """이 줄의 평가본 규정 — 줄 하나로 먼저 본다. 안 걸리면 말끝이 아닌 줄에 바로 다음 줄(새 항목 · 표가 이어 붙은 줄이 아니면)을
    이어 본다 — 다음 줄 하나로 걸리면 그 줄 차례다(메모에 윗줄이 붙지 않게)."""
    line = lines[index]
    if (rule := _blind_line(line, " ".join(lines[max(0, index - 2):index]))):
        return rule
    nxt = lines[index + 1] if index + 1 < len(lines) else ""
    if not nxt or _CLAUSE_END_RE.search(line) or _NEW_ITEM_RE.match(nxt) or _joined(lines, index + 1) \
            or _blind_line(nxt, " ".join(lines[max(0, index - 1):index + 1])):
        return None
    return _blind_line(f"{line} {nxt}", " ".join(lines[max(0, index - 2):index]))


_LANDSCAPE_RE = re.compile(r"A4\s*(?:용지\s*)?가로|가로\s*형|가로\s*방향")
_PPT_RE = re.compile(r"PPT|파워\s*포인트|프리?[젠레]테이션", re.I)
_VOLUME_RES = (re.compile(r"정량\s*(?:적\s*)?(?:평가\s*)?제안서|사업\s*수행\s*능력\s*평가서"),
               re.compile(r"정성\s*(?:적\s*)?(?:평가\s*)?제안서|사업\s*내용\s*제안서"))
_NOTE_CHARS = 120
#: 쪽수 앞 요약본 · 발표 자료(「제안서 요약본은 10페이지 이내」 · 「발표자료는 15매 이내」) — 본문 상한이 아니다.
_SUMMARY_PAGES_RE = re.compile(r"요약|발표|프[리레]젠|PT")
#: 「표는 가로 방향 사용 가능」 — 표 · 그림만 가로를 허용하는 말이지 제안서가 가로형이 아니다.
_LANDSCAPE_ALLOW_RE = re.compile(r"(?:표|그림|도표|사진)[^\n]{0,15}가로[^\n]{0,15}(?:가능|허용|할\s*수)")
#: 「한글 또는 파워포인트로」 · 「(PPT, PDF 등)」 · 「PPT 형식은 접수하지 않음」 — PPT 로 쓰라는 규정이 아니다.
#: 「(PPT 등)」 한 형식은 PPT 다(1687776 「제안서 원본 파일 포함(PPT 등)」) — 다른 형식과 나란히(「PPT, PDF 등」)일 때만 거른다.
_PPT_NOT_RE = re.compile(r"(?:PPT|파워\s*포인트)[^\n]{0,25}?(?:또는|불가|접수하지\s*않|제출하지\s*않|금지)|또는\s*(?:PPT|파워\s*포인트)"
                         r"|(?:PPT|파워\s*포인트)\s*[,/·]\s*(?:PDF|HWP|한글|워드|DOCX?)|(?:PDF|HWP|한글|워드|DOCX?)\s*[,/·]\s*(?:PPT|파워)", re.I)
#: 「제안서 규격 및 수량」 아래 「○ 작성형태: 파워포인트 등」(1808642) — 줄에 「제안서」가 없어도 제안서 작성 형식 이름표다(#16).
_FORMAT_LABEL_RE = re.compile(r"작성\s*(?:형태|형식|도구)\s*[:：]")
#: 「PPT를 활용하여 제출을 희망할 경우 … 가능」(1813493) · 「PPT 작성 가능」 — 고를 수 있다는 말이지 PPT 로 쓰라는 규정이 아니다(2.7.0 · 계획 10).
#: 「희망 · 가능」이 PPT 사용 자체에 붙을 때만 선택(2.7.0 검토 — 「PPT로 작성하며 양면 인쇄 가능」 · 「PPT 형식으로 작성하며 발주기관이 희망 시 …」 ·
#: 「PPT로 작성하며, 희망 시 PPT 원본 …」을 선택으로 읽었다). 희망은 PPT 와 「(를) (활용 · 사용하여) 작성 · 제출(을)」로만 이어질 때 ·
#: 가능은 「PPT(로) (작성 · 제출 · 활용)(하는 것도)」 바로 뒤일 때. 1813493 「PPT를 활용하여 제출을 희망할 경우 … 가능」은 선택.
_PPT_WISH = r"희망\s*(?:시|할\s*경우|하는\s*경우|할\s*때)"
_PPT_OPTIONAL_RE = re.compile(
    rf"(?:PPT|파워\s*포인트)\s*(?:를|로|으로)?\s*(?:(?:활용|사용)\s*(?:하여|해)\s*)?(?:작성|제출)\s*(?:을|를|하기를)?\s*{_PPT_WISH}"
    r"|(?:PPT|파워\s*포인트)\s*(?:로|으로|를|도)?\s*(?:작성|제출|활용)?\s*(?:하는\s*것도|하는\s*것이|도)?\s*가능", re.I)


def ppt_optional(line: str) -> bool:
    """PPT 를 고를 수 있다는 줄인가(희망 시 · 가능) — 형식 읽기와 품질 게이트(옛 초안의 저장된 형식 메모)가 함께 쓴다."""
    return bool(_PPT_OPTIONAL_RE.search(line or ""))
#: 「정량제안서와 정성제안서를 하나의 파일로 합쳐」 — 두 권이 아니다(「분리하여 각각 하나의 파일로」는 두 권 · 1718615).
_ONE_VOLUME_RE = re.compile(r"합쳐|합본|한\s*권으로|하나로\s*(?:통합|묶)|하나의\s*(?:파일|문서)로\s*(?:통합|작성|묶)")
_SPLIT_VOLUME_RE = re.compile(r"각각|분리|별도")


#: 원문이 유사 경험 · 실적 기재를 막는 줄(「… 유사경험은 제안서상 제외하여 작성」 · 2.9.0).
_NO_SIMILAR_RE = re.compile(r"유사\s*(?:경험|실적|경력)[^.\n]{0,40}?(?:제외하여\s*작성|기재\s*(?:하지|불가|금지)|작성\s*(?:하지|불가))")
#: 원본 · 사본 표시(2.11.0 T3) — 평가본 규정의 원본 · 사본 구분 줄(제출 수량 줄 · 규정 줄 ±2 · 문서 끝까지) 하나에 두 말이 다 있을 때만 표지에 단다
#: (부수만 있는 근사 「제안서 10부(업체명 미기재)」로는 달지 않는다).
_ORIGINAL_WORD_RE = re.compile(r"원본|정본")
_COPY_WORD_RE = re.compile(r"사본|부본")
#: 원문이 목차(차례) 쪽을 요구 · 전제하는 줄(2.11.0 T4) — 「표지, 목차를 포함하여」 · 「표지와 목차를 제외한 각 면」 · 「표지·간지·목차」 ·
#: 「(목차/색인 등 작성)」 · 「목차를 작성」. 「제안서 목차 및 작성 방법」 · 「목차 순서에 따라」 · 「목차(순서)를 준수」는 제시 목차대로 쓰라는 말이다.
_TOC_ASK_RE = re.compile(r"(?:표지|간지)\s*(?:[,·ㆍ와과및]\s*|\s)(?:간지\s*[,·ㆍ]?\s*)?목\s*차|목\s*차\s*[/·]\s*색인"
                         r"|목\s*차\s*(?:를|을)\s*(?:포함|첨부|삽입|작성)")
#: 원문이 정한 제안서 표지 서식(2.11.0 T3b · 받아 둔 원문 490건 실측 18줄) — 「[서식 2] 제안서 표지 양식」 · 「□ 서식 2. 제안서 표지 (본교양식 준수)」 ·
#: 「[서식 제19호] - 사업내용제안서 표지」 · 「용역제안서(표지)-(서식 5호)」 · 「[표지양식 – 서식 1]」 · 「표지 : <서식 제19호>에 따라 작성」 ·
#: 「별지서식 내 ‘정량적 평가제안서’ 표지사용」 · 「제안서 표지 및 구성은 별지의 제안서 서식과 …」. 「(표지 및 목차 미포함) (별지 2호 서식)」 ·
#: 「[입찰참가신청서표지]」 · 「표지, 목차를 포함하여 … 관련 서식을 사용」은 아니다.
_COVER_FORM_RE = re.compile(r"(?:제안서|평가서)\s*[(（\[]?\s*표지[^\n]{0,15}?(?:양식|서식)"
                            r"|(?:서식|양식)[^\n]{0,15}?(?:제안서|평가서)\s*[(（]?\s*표지"
                            r"|표지\s*(?:양식|서식)|표지\s*[:：]\s*[<〈\[(]?\s*(?:별지\s*)?(?:서식|양식)"
                            r"|(?:서식|양식)[^\n]{0,20}?표지\s*(?:를\s*)?사용")
#: 「표지」 낱말 없이 표지 꼴만 있는 서식(1822113 「[별지 서식 7호]」 / 「정성제안서」 / 사업명 / 「제        안        서」 / 날짜 / 「대   표   자(인)」 ·
#: 1822864 「【서식 제1호】」 / 「제   안   서」 / 용역명 / 「제안자명 : (인)」) — 띄어 쓴 「제 안 서」만 있는 줄 위 몇 줄 안에 서식 머리가 있고
#: 아래 몇 줄 안에 날인 「(인)」이 있으면 표지 서식으로 본다(근사 · 받아 둔 원문 484건 실측 2건 · 「가 격 제 안 서」 · 날인 없는 서식은 아니다).
_FORM_HEAD_RE = re.compile(r"^[\[<〈【(（]\s*(?:별지|서식|양식)[^\]>〉】)）]{0,15}?\d[^\]>〉】)）]{0,8}[\]>〉】)）]")
_SPACED_TITLE_RE = re.compile(r"^제\s+안\s+서$")
_SEAL_RE = re.compile(r"[(（]\s*인\s*[)）]")
_FORM_SPAN = 6


def _cover_shape(lines: list[str], index: int) -> str | None:
    """이 줄이 표지 낱말 없는 표지 서식의 띄어 쓴 「제 안 서」 제목이면 「서식 머리 … 제 안 서」, 아니면 None(가장 가까운 서식 머리만 본다 —
    서식 목록 「【서식9호】 … 【서식13호】」가 바로 위에 있어도 머리는 하나)."""
    if not _SPACED_TITLE_RE.match(lines[index]) or not any(_SEAL_RE.search(line) for line in lines[index + 1:index + 1 + _FORM_SPAN]):
        return None
    head = next((line for line in reversed(lines[max(0, index - _FORM_SPAN):index]) if _FORM_HEAD_RE.match(line)), None)
    return f"{head} … {lines[index]}" if head else None


def _spot(line: str, doc: dict[str, Any], page: Any) -> dict[str, Any]:
    """형식 규정 한 줄의 자리 — {line(앞 120자), document, page}(no_similar · toc_required · cover_form)."""
    return {"line": re.sub(r"\s+", " ", line).strip()[:_NOTE_CHARS], "document": doc.get("name"), "page": page}


def read_format(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """원문의 제안서 형식 규정 → {page_limit, page_note, blind, blind_note, blind_only, landscape, ppt, two_volume, volumes, notes, where}.
    쪽수 상한은 가장 큰 값(이력서 상한보다 본문이 크다 · 요약본 · 발표 자료 상한은 빼고) · 발표 자료의 PPT 는 제안서 형식이 아니다.
    blind_only — 평가본 규정 줄 어디에도 원본 · 사본 구분이 없다(평가본이 곧 제출 파일 · 2.10.0 D8 · 옛 초안에는 칸이 없다).
    2.11.0(옛 초안에는 칸이 없다): original_copy — 구분 줄(창) 하나에 원본(정본)과 사본(부본)이 둘 다(표지 「제안서(원본)」 · 「제안서(사본)」) ·
    toc_required — 목차 쪽 요구 줄 · cover_form — 원문이 정한 제안서 표지 서식 줄({line, document, page} | None)."""
    out: dict[str, Any] = {"page_limit": None, "page_note": None, "blind": False, "blind_note": None, "blind_only": False, "landscape": False,
                           "ppt": False, "two_volume": False, "volumes": [], "notes": [], "where": None, "no_similar": None,
                           "original_copy": False, "toc_required": None, "cover_form": None}
    volumes: list[set[str]] = [set(), set()]
    one_volume = False
    blind_split = False
    # 구분 줄 · 규정 창 어디든 원본(정본)과 사본(부본)이 함께 있었다 — original_copy. 첫 구분 줄만 보면
    # 「제안서 11부(원본 1부, 평가본 10부)」 뒤의 「표지에는 원본과 사본을 명시」를 놓친다(1829687 · 1822113 · 2.11.0 A2 검토).
    copy_pair = False

    def pair(text: str) -> bool:
        return bool(_ORIGINAL_WORD_RE.search(text) and _COPY_WORD_RE.search(text))

    def note(line: str) -> None:
        text = re.sub(r"\s+", " ", line).strip()[:_NOTE_CHARS]
        if text not in out["notes"]:
            out["notes"].append(text)

    for doc in docs:
        lines, pages = _doc_lines(doc)
        for index, line in enumerate(lines):
            if not line or _joined(lines, index) or _TOC_PAGE_RE.search(line):
                continue
            for match in _PAGE_LIMIT_RE.finditer(line):
                value = int(match.group(1))
                clause = re.split(r"[,·/]", line[max(0, match.start() - 15):match.start()])[-1]
                if (lead := _SUMMARY_PAGES_RE.search(clause)) and not re.search(r"본문|포함", clause[lead.end():]):
                    continue  # 「프리젠테이션 요약본 20매 이내」 — 같은 마디 앞에 요약 · 발표(「요약서를 포함하여 본문을 100쪽」은 본문 상한)
                if (unit := match.group(2)):
                    ok, bad = (_SHEET_UNIT_OK_RE, _SHEET_UNIT_NOT_RE) if unit == "장" else (_P_UNIT_OK_RE, _P_UNIT_NOT_RE)
                    if not ok.search(clause) or bad.search(clause):
                        continue  # 「P」는 제안서 · 본문 · 분량 마디 · 「장」은 거기에 매수 · 표지 · 간지 마디에서만 쪽
                if 5 <= value <= 300 and (out["page_limit"] is None or value > out["page_limit"]):
                    out["page_limit"], out["page_note"] = value, re.sub(r"\s+", " ", line).strip()[:_NOTE_CHARS]
                    out["where"] = {"document": doc.get("name"), "page": pages[index]}
            if not out["no_similar"] and _NO_SIMILAR_RE.search(line):
                # 「가명정보 교육 운영 유사경험은 제안서상 제외하여 작성」(11-11 3위 원문 14쪽) — 회사 실적 문장이 있으면 게이트가 알린다
                out["no_similar"] = _spot(line, doc, pages[index])
            if not out["toc_required"] and _TOC_ASK_RE.search(line):
                out["toc_required"] = _spot(line, doc, pages[index])  # 제출용 · 평가본에 목차 쪽(2.11.0 D2)
            if not out["cover_form"] and (form := line if _COVER_FORM_RE.search(line) else _cover_shape(lines, index)):
                out["cover_form"] = _spot(form, doc, pages[index])  # 앱 표지는 앱 꼴 — 검토 목록 · /plan 이 사람에게 알린다(2.11.0 T3b)
            if _BLIND_COPIES_RE.search(line) and _COPIES_N_RE.search(line):
                blind_split = True  # 제출 수량 줄의 원본 · 사본 구분(규정 줄과 떨어져 있어도 · T6 검토)
                copy_pair = copy_pair or pair(line)
            if not (out["blind"] and copy_pair) and (rule := _blind_at(lines, index)):
                # 규정 줄마다 원본 · 사본 구분을 본다(그 줄 · 바로 위 두 줄 · 이어 본 다음 줄 — D8) · 메모는 첫 규정만
                window = " ".join(lines[max(0, index - 2):index + 2])
                if _BLIND_SPLIT_RE.search(window):
                    blind_split = True
                    copy_pair = copy_pair or pair(window)
                if not out["blind"]:
                    # 메모는 걸린 문장(표가 이어 붙은 긴 줄의 앞머리가 아니라)
                    out["blind"], out["blind_note"] = True, re.sub(r"\s+", " ", rule).strip()[:_NOTE_CHARS]
                    note(rule)
            if (not out["landscape"] and _LANDSCAPE_RE.search(line) and not re.search(r"부득이|일부", line)
                    and not _LANDSCAPE_ALLOW_RE.search(line)):
                out["landscape"] = True
                note(line)
            if (not out["ppt"] and _PPT_RE.search(line) and ("제안서" in line or _FORMAT_LABEL_RE.search(line))
                    and not re.search(r"발표|요약|설명|슬라이드", line)
                    and not _PPT_NOT_RE.search(line) and not ppt_optional(line)):
                out["ppt"] = True
                note(line)
            for n, pattern in enumerate(_VOLUME_RES):
                found = {re.sub(r"\s+", "", m.group(0)) for m in pattern.finditer(line)}
                volumes[n].update(found)
                one_volume = one_volume or bool(found and _ONE_VOLUME_RE.search(line) and not _SPLIT_VOLUME_RE.search(line))
    if out["page_note"]:
        note(out["page_note"])
    out["blind_only"] = out["blind"] and not blind_split
    out["original_copy"] = out["blind"] and copy_pair
    if volumes[0] and volumes[1] and not one_volume:
        out["two_volume"] = True
        out["volumes"] = [sorted(volumes[0])[0], sorted(volumes[1])[0]]
    return out


_CHAPTER_START_RE = re.compile(r"^(?:(?:[IⅠ]|\d{1,2})\s*[.)]?\s*)?사업\s*개요$")
#: 발췌가 이보다 짧으면 앞쪽 목차 줄을 잡은 것이다 — 다음 「사업 개요」 머리로 다시 찾는다(11-03 검토: HWPX 목차는 쪽 번호가 빠진다).
MIN_EXCERPT_LINES = 20
_WRITE_GUIDE_RE = re.compile(r"^(?:(?:[ⅠⅡⅢⅣⅤⅥⅦ]|[IVX]+)\s*\.?\s*)?제안서\s*작성\s*(?:안내|요령|지침)$")
_RULES_HEAD_RE = re.compile(r"제안서\s*작성\s*(?:지침|요령)|작성\s*(?:지침|요령)\s*및\s*유의")
#: 발주기관 담당자 전화 줄은 보내지 않는다(문의처 · 제안서에 쓸 일이 없다).
_PHONE_RE = re.compile(r"\(?0\d{1,2}\)?[\s.-]?\d{3,4}[\s.-]\d{4}")
_ROMAN_ONLY_RE = re.compile(r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[IVX]{1,4})$")


_PAGE_NO_LINE_RE = re.compile(r"^\d{1,3}$")


def _rules_head(lines: list[str]) -> int | None:
    """제안서 작성 지침 덩어리 머리 — 덩어리 머리(□ · ■)이거나 짧은 줄. □ · ■ 머리가 있으면 그것을 먼저.
    문서 앞 목차 줄은 건너뛴다: 「목 차」 덩어리 안 · 다음 줄(쪽 번호 줄 넘김)이 바로 다음 번호인 내용 없는 목록 줄 · 같은 줄이 뒤에 다시 나오는 줄
    (11-06 3차 심사 — 1805118 은 문서 앞 목차 「2. 제안서 작성지침 및 유의사항」을 잡아 목차 12줄을 지침으로 보냈다)."""
    span = _doc_toc_span(lines)
    last = {_compact(line): i for i, line in enumerate(lines)}
    heads: list[int] = []
    for i, line in enumerate(lines):
        if (not _RULES_HEAD_RE.search(line) or _TOC_PAGE_RE.search(line)
                or not (_BLOCK_RE.match(line) or len(_compact(line)) <= _BLOCK_HEAD_CHARS)):
            continue
        if span and span[0] <= i <= span[1]:
            continue
        following = next((n for n in lines[i + 1:i + 4] if n and not _PAGE_NO_LINE_RE.match(n)), "")
        if (nxt := _successor(line)) and nxt.match(following):
            continue  # 「5. 제안서 작성 지침」 / 「41」 / 「6. 제안서 제출 관련 서식」(1793373)
        if last[_compact(line)] > i:
            continue  # 「5.2. 제안서 작성지침 및 유의사항」이 본문에서 다시 나온다(1782053 — 「제n장」 목차는 「목 차」 덩어리로 못 잡는다)
        heads.append(i)
    return next((i for i in heads if _BLOCK_RE.match(lines[i])), heads[0] if heads else None)


def rfp_excerpt(text: str) -> tuple[str, str]:
    """(사업 개요 ~ 「제안서 작성 안내」 앞까지 발췌, 제안서 작성 지침 덩어리). 장 머리를 못 찾으면 앞에서부터 상한까지."""
    lines = (text or "").splitlines()

    def keep(line: str) -> bool:  # 장 번호만 있는 줄(「IV」)과 전화 줄은 뺀다
        return bool(line.strip()) and not _PHONE_RE.search(line) and not _ROMAN_ONLY_RE.match(line.strip())

    starts = [i for i, line in enumerate(lines) if _CHAPTER_START_RE.match(line.strip()) and not _TOC_PAGE_RE.search(line)]
    body: list[str] = []
    for begin in starts:
        end = next((i for i in range(begin + 1, len(lines)) if _WRITE_GUIDE_RE.match(lines[i].strip()) and not _TOC_PAGE_RE.search(lines[i])), len(lines))
        chunk = [line for line in lines[begin:end] if keep(line)]
        if len(chunk) >= MIN_EXCERPT_LINES:
            body = chunk
            break
    if not body:
        body = [line for line in lines if keep(line)]  # 장 머리를 못 찾았다 — 앞에서부터 상한까지
    rules: list[str] = []
    head = _rules_head([line.strip() for line in lines])
    if head is not None:
        for line in lines[head + 1:]:
            if _BLOCK_RE.match(line):
                break
            if line.strip():
                rules.append(line.strip())
    return "\n".join(body)[:EXCERPT_LIMIT], "\n".join(rules)[:RULES_LIMIT]


_PERIOD_RE = re.compile(r"(?:사업|용역|계약|과업)\s*기간\s*[:：]?\s*([^\n]{4,80})")
#: 기간 머리 뒤가 기간 안 일정 · 표 머리줄 · 문서 목차면 사업 기간 글이 아니다(「계약기간 내 …」 · 「계약기간 이행실적」 · 「사업기간 및 금액 3」).
_PERIOD_SKIP_RE = re.compile(r"^(?:내|중|및|안|동안|이내)(?![가-힣])|^이행")
#: 연 · 월 · (일) — 「2027년 12월 15일」 · 「2027. 12. 15.」 · 「2027.12」.
_YMD_RE = re.compile(r"(20\d{2})\s*[.년-]\s*(\d{1,2})(?:\s*[.월-]\s*(\d{1,2})(?!\d))?")
_MONTHS_RE = re.compile(r"(\d{1,2})\s*개월")
#: 사업 금액 머리 — 「사업 · 용역 + 금액 · 예산」은 어디서나, 「기초금액 · (총)사업비」는 줄 머리(번호 · 글머리 뒤)에서만(「운영 사업비 3,000,000원」은
#: 일부 금액 · 품질 게이트 `_TERM_MONEY_RE` 와 같은 선). 머리 뒤 괄호 한 쌍(「사업예산(기초금액)」) · 숫자 앞 「금 · 일금」(11-13 동국대 「나. 사업비 : 금40,700,000원」).
_BUDGET_RE = re.compile(
    r"(?:(?:사업|용역)\s*(?:금액|예산)|^[ \t]*(?:(?:[가-하]|\d{1,2})[ \t]*[.)][ \t]*|[□■○●◦·\-][ \t]*)?(?:기초[ \t]*금액|(?:총[ \t]*)?사업[ \t]*비))"
    r"[ \t]*(?:\([^)\n]{0,15}\))?\s*[:：]?\s*(?:일?금[ \t]*)?([\d,]+\s*원[^\n]{0,20})", re.M)
#: 금액 줄의 부가세 표시 — 「(부가세 포함)」 · 「(VAT 별도)」 · 「부가가치세 제외 · 미포함 · 불포함」(별도로 본다 · 「미 · 불」을 틈이 삼켜
#: 「포함」이 되던 것 · 11-13 T1 검토).
_VAT_RE = re.compile(r"(?:부가(?:가치)?세|VAT)[^\n)]{0,6}?((?:미|불)\s*포함|포함|별도|제외)", re.I)
#: 금액 원문 글 꼬리에 붙어 온 다음 항목(「□ 사업기간 …」)은 떼어 낸다.
_BUDGET_TAIL_RE = re.compile(r"\s{2,}.*$|\s*[□■○●◦※▶].*$")


def _ymd(year: str, month: str, day: str | None) -> str:
    return f"{int(year):04d}-{int(month):02d}" + (f"-{int(day):02d}" if day else "")


def project_terms(excerpt: str) -> dict[str, Any]:
    """사업 기간(원문 글 · 개월 수 · 끝 연월 · 시작 연월) · 사업 금액(원문 글 · 원) — 제안요청서 발췌에서만. 없으면 None.
    「계약 체결일 ~ 2027년 12월 15일」 꼴은 끝만 둔다 — 시작은 원문 말(`start_label`) · 개월 수는 짓지 않는다(2.8.0 B6).
    `end` 는 협약 기간 검사용 「연-월」 · `end_date` 는 끝날(「2027-12-15」 · 날이 없으면 「2027-12」)."""
    # 표지 「사업기간」 줄에 그대로 실리므로 날짜 · 개월 수가 읽히는 글만 쓴다(표 머리줄 · 목차 · 「계약기간 내 …」는 다음 자리로 · 2.8.0 검토)
    text = next((value for value in (m.group(1).split("\t")[0].strip() for m in _PERIOD_RE.finditer(excerpt or ""))
                 if value and not _PERIOD_SKIP_RE.match(value) and (_YMD_RE.search(value) or _MONTHS_RE.search(value))), None)
    months = end = start = end_date = start_label = None
    ok = False
    if text:
        dates = list(_YMD_RE.finditer(text))
        # 첫 날짜가 끝날인 꼴 — 뒤 괄호의 날짜(「(※ 1차 납품은 …)」 · 「(결과보고서는 …까지)」 · 「(하자보수기간 …)」)는 범위 끝이 아니다(2.8.0 검토):
        #  · 첫 날짜 앞에 「~ · 로부터」(「계약체결일 ~ 날짜 (…)」 · 「계약일로부터 날짜까지(…)」)
        #  · 첫 날짜 바로 뒤가 「까지」이고 둘째 날짜가 그 뒤에 연 괄호 안(「계약일(… 까지 체결 예정) ~ 끝날」 · 「… 까지 착수하여 … 까지 완료」는 범위)
        lead = bool(dates) and re.search(r"[~～∼]|로?부터", text[: dates[0].start()]) is not None
        first_until = bool(dates) and re.match(r"[\s.일]*까지", text[dates[0].end():]) is not None
        in_paren = len(dates) >= 2 and re.search(r"[(（]", text[dates[0].end(): dates[1].start()]) is not None
        if len(dates) >= 2 and not (lead or (first_until and in_paren)):
            (y1, m1, _d1), (y2, m2, d2) = dates[0].groups(), dates[1].groups()
            span = (int(y2) - int(y1)) * 12 + int(m2) - int(m1) + 1
            if span > 0:  # 둘째가 첫째보다 뒤인 범위만 — 아니면 첫 날짜 하나로 읽는다(괄호 속 착수 · 교육 일정)
                end_date = _ymd(y2, m2, d2) if 1 <= int(m2) <= 12 else None
                if span <= 60:
                    months, ok = span, True
                    end, start = f"{int(y2)}-{int(m2)}", f"{int(y1)}-{int(m1)}"
        if not ok and end_date is None:
            date = dates[0] if dates else None
            sign = re.search(r"[~～∼]|로?부터", text[: date.start()]) if date else None  # 「계약체결일로부터 2027년 12월 10일」도 끝날
            until = re.match(r"[\s.일]*까지", text[date.end():]) if date else None
            if date and (sign or until) and 1 <= int(date.group(2)) <= 12:
                end, end_date = f"{int(date.group(1))}-{int(date.group(2))}", _ymd(*date.groups())
                head = text[: sign.start()] if sign else text[: date.start()]
                start_label = re.sub(r"\s*(?:로?부터|에서)\s*$", "", head).strip(" :：(") or None
            elif (m := _MONTHS_RE.search(text)):
                months = int(m.group(1))
                ok = 0 < months <= 60
    budget = _BUDGET_RE.search(excerpt or "")
    budget_text = _BUDGET_TAIL_RE.sub("", budget.group(1)).strip(" ,.;") if budget else None
    while budget_text and budget_text.count("(") > budget_text.count(")"):
        # 20자에서 잘려 닫히지 않은 괄호(「148,244,000원(금일억…원, 부가세」 · 1687776)는 그 괄호 앞까지 — 표지 사업금액 줄에 깨진 글이 나간다
        budget_text = budget_text[:budget_text.rfind("(")].rstrip(" ,.;")
    digits = re.match(r"[\d,]+", budget_text or "")
    vat = _VAT_RE.search((excerpt or "")[budget.start():].split("\n", 1)[0]) if budget else None  # 금액 줄 끝까지
    return {"period": text, "months": months if ok else None, "end": end, "start": start, "end_date": end_date, "start_label": start_label,
            "budget": budget_text or None, "budget_won": int(digits.group(0).replace(",", "")) if digits and digits.group(0).strip(",") else None,
            "budget_vat": ("포함" if vat.group(1) == "포함" else "별도") if vat else None}


def stored_terms(terms: dict[str, Any]) -> dict[str, Any]:
    """초안에 남기는 사업 기본정보(2.8.0 B6) — 기간 · 금액은 원문 글 그대로(표지 · 게이트 대조가 쓴다).
    2.10.0: 부가세 포함 · 별도 · 나라장터 배정예산 · 추정가격(`notice_budget`) · 계약 예정일 · 일수 · 주차(`contract_span` · D1) ·
    입찰 마감 · 참가자격등록 마감(ISO · T8). 옛 초안에는 없다(읽는 쪽은 .get)."""
    return {"period": terms.get("period"), "start_label": terms.get("start_label"), "end": terms.get("end_date"),
            "budget": terms.get("budget"), "budget_won": terms.get("budget_won"), "budget_vat": terms.get("budget_vat"),
            "assigned_budget": terms.get("assigned_budget"), "estimated_price": terms.get("estimated_price"),
            "contract_from": terms.get("contract_from"), "days": terms.get("days"), "weeks": terms.get("weeks"),
            "deadline": terms.get("deadline"), "qualification_deadline": terms.get("qualification_deadline")}


def notice_budget(raw: dict[str, Any] | None) -> dict[str, int | None]:
    """나라장터 기본정보 금액 칸 — 배정예산(부가세 포함) · 추정가격(부가세 별도 · 원). 검토용 사업금액 비율은 원문 글보다 이 값을 먼저 쓴다
    (11-13 조사 바로잡음). 표지 「사업금액」 · 본문 금액 대조는 원문 글 그대로(`project_terms` · 2.8.0 B6). 없으면 None."""
    raw = raw or {}
    return {key: g2b_mapper.parse_amount(str(raw.get(key) or "")) for key in ("assigned_budget", "estimated_price")}


#: 입찰공고문 계약 예정일 — 「③ 계약체결 26.11.18.(수) 이후」(11-13 동국대). 「이후」가 없으면 읽지 않는다(애매하면 놓친다).
_CONTRACT_FROM_RE = re.compile(r"계약\s*체결[^\n]{0,20}?((?:20)?\d{2})\s*[.년-]\s*(\d{1,2})\s*[.월-]\s*(\d{1,2})[^\n]{0,15}?이후")
#: 이보다 짧은 사업은 주차(W1~Wn)로 짠다(D1 · 13주).
SHORT_PROJECT_DAYS = 91


def contract_from(docs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """입찰공고문(없으면 다른 원문)의 계약 예정일 → {date: "2026-11-18", quote, document, page}. 없으면 None."""
    for doc in sorted(docs, key=lambda d: d.get("role") != "notice"):
        lines, pages = _doc_lines(doc)
        for index, line in enumerate(lines):
            if not (match := _CONTRACT_FROM_RE.search(line)):
                continue
            year, month, day = (int(g) for g in match.groups())
            try:
                date = datetime(year + 2000 if year < 100 else year, month, day)
            except ValueError:
                continue
            return {"date": date.strftime("%Y-%m-%d"), "quote": re.sub(r"\s+", " ", line).strip()[:_NOTE_CHARS],
                    "document": doc.get("name"), "page": pages[index]}
    return None


def contract_span(terms: dict[str, Any], docs: list[dict[str, Any]]) -> dict[str, Any]:
    """계약 예정일 ~ 고정 끝날(D1) — 사업기간이 「계약체결일 ~ 날짜」 꼴(개월 수 없음)이고 끝날이 연-월-일이며 공고문에 「계약체결 … 이후」가
    있을 때만 → {contract_from, contract_quote, days(끝날 포함), weeks(91일 미만일 때만 · 온전한 주)}. 아니면 {}. 사업기간 글 · 표지는 그대로."""
    end = str(terms.get("end_date") or "")
    if terms.get("months") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) or not (found := contract_from(docs)):
        return {}
    days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(found["date"], "%Y-%m-%d")).days + 1
    if days <= 0:
        return {}
    return {"contract_from": found["date"], "contract_quote": found["quote"], "days": days,
            "weeks": days // 7 if days < SHORT_PROJECT_DAYS else None}


#: 입찰공고문 제출서류 머리 — 번호 · 글머리 뒤 「제출서류」 · 「구비 · 신청 · 등록 · 준비 서류」(「다. 제출서류 (각종 증명서는 …)」 · 「7. 입찰 등록 제출서류」).
#: 「… 신청 서류 등은 … 참고하여」 같은 문장 줄 · 「현장설명 준비서류(미지참시 …)」(인감도장 지참 · 1699556)는 제출서류 머리가 아니다.
#: 「3. 입찰참가자의 자격(구비서류 등)에 관한 사항」(1766093 · 자격 절 제목)도 머리가 아니다 — 닫는 괄호 뒤 조사 · 「에」를 본다(11-13 독립 검토).
_PAPERS_HEAD_RE = re.compile(r"^(?![^\n]*현장\s*설명)\s*(?:\d{1,2}\s*[.)]|[가나다라마바사아자차카타파하]\s*[.)]|\(\d{1,2}\)|[□■○])\s*[^\n]{0,15}?"
                             r"(?:제출|구비|신청|등록|준비|지참)\s*서류(?!\s*(?:등)?\s*\)?\s*(?:에|은|는|을|를|의|와|및))"
                             # 번호 없이 쌍점으로 끝나는 머리 — 조달청 표준 공고서 「제안서 관련 제출서류:」 아래 ① 목록(1805118 · 1786460)
                             r"|^\s*[^\n※:]{0,15}?(?:제출|구비|신청)\s*서류\s*[:：]\s*$"
                             # 「6-4. 기술제안서는 다음과 같이 파일명을 지정하여 제출하시기 바랍니다.」 아래 ① 목록(1822113 · 2.11.0 T6b — 받아 둔 공고문 19건이 같은 문장)
                             r"|^\s*\d{1,2}\s*-\s*\d{1,2}\s*\.\s*[^\n]{0,10}?제안서는\s*(?:다음과|아래와)\s*같이\s*파일\s*명을\s*지정하여\s*제출")
#: 「-」 글머리 서류 목록(「8. 입찰참가 신청서류」 아래 「- 입찰참가신청서(당 원 양식)」 · 1822864) — 머리 바로 아래 첫 줄이 짧은 이름일 때만
#: 항목으로 받는다. 문장(「…함 · 바람 · 다」로 끝남)이나 긴 줄은 머리 아래 설명이다.
_PAPER_DASH_ITEM_RE = re.compile(r"^\s*[-·ㆍ]\s*(?P<text>[^\n]{1,40}?)\s*$")
_PAPER_SENTENCE_RE = re.compile(r"(?:다|함|람|음|것|요)\s*[.。]?\s*$")
#: 「-」 목록을 받지 않는 머리 — 「마. 계약담당자는 제출서류(…)에 대하여 …」 같은 문장 머리(아래 「-」 줄은 규정 이름 목록 · 1778192).
#: 첫 「-」 줄이 「일시 : … · 제출방법 : …」 이름표 줄이면 서류가 아니라 접수 안내다(1806913).
_PAPER_SENTENCE_HEAD_RE = re.compile(r"[가-힣](?:는|은)\s")
_PAPER_LABEL_LINE_RE = re.compile(r"^[^:：]{1,8}[:：]")
#: 머리의 괄호 · 꺾쇠 안 안내(「<제출서류는 공고문 순서로 정리해주시기 바랍니다>」 · 1811356)는 문장 판정에서 뺀다.
_PAPER_ASIDE_RE = re.compile(r"[<(（〈][^>)）〉]*[>)）〉]")
#: 항목 번호 — 첫 항목의 꼴이 그 목록의 꼴(1. · 가. · 1) · (1) · ① · ○ — 이 차례가 위아래 · 1781608 은 「○ 정성제안서 1부」 꼴).
#: 그보다 아래 꼴 번호 줄은 그 항목의 하위 서류(「가. 입찰 참가 서류」 아래 「1) 입찰참가신청서 1부」 · 1718694) · 위 꼴 번호는 다음 절이다.
#: 「-」 · 「·」 글머리 줄은 앞 항목에 이어지는 설명이다.
_PAPER_MARKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 한글 번호는 「가나다 …하」 열네 글자만(「끝. 상기와 같이 공고 함」은 번호가 아니다 · 1748554 · 11-13 독립 검토)
    ("dot", re.compile(r"^\s*(\d{1,2}\s*\.)(?!\d)\s*")), ("hangul", re.compile(r"^\s*([가나다라마바사아자차카타파하]\s*[.)])\s*")),
    ("paren", re.compile(r"^\s*(\d{1,2}\s*\))\s*")), ("wrapped", re.compile(r"^\s*(\(\d{1,2}\))\s*")),
    ("circled", re.compile(r"^\s*([①-⑳])\s*")), ("bullet", re.compile(r"^\s*([○●◦])\s*")),
)
_PAPER_LEVEL = {kind: level for level, (kind, _pattern) in enumerate(_PAPER_MARKS)}
#: 목록 밖 줄 — 「3-2. 입찰참가자격등록 …」 같은 갈래 절 번호 · 가로줄(「————」 · 1691972).
_PAPER_STOP_RE = re.compile(r"^\s*\d{1,2}\s*-\s*\d{1,2}\s*\.|^\s*[—─━=_~-]{4,}\s*$")
#: 목록의 첫 번호 — 수열의 처음만. 다른 절의 번호 목록(「4. 낙찰자 공고」 · 「1) 입찰 참가 자격이 없는 …」 · 1731641)을 받지 않는다.
_PAPER_FIRST = frozenset({"①", "1)", "(1)", "가.", "가)", "1.", "○", "●", "◦"})
#: 머리와 첫 항목 사이 표시 없는 줄 상한 — 넘으면 이 머리 아래에는 서류 목록이 없다(다른 절 번호 목록까지 건너가던 것 · 1781608).
PAPER_LEAD_LINES = 3
PAPER_ITEM_CHARS = 160
PAPER_NOTE_CHARS = 200
_PAPER_DASH = ("-", "·", "ㆍ")
#: 첫 항목 전의 「※ 기타 유의사항」 같은 절 머리 ※ 줄(「유의사항」으로 끝나는 짧은 줄) — 그 뒤 번호 줄은 유의사항 문장이다(11-13 독립 검토).
#: 「※ 상세 제출서류와 유의사항은 … 확인하시기 바랍니다」(1821405) 같은 문장은 머리가 아니다.
_PAPER_ASIDE_HEAD_RE = re.compile(r"^※\s*[^\n]{0,10}?유의\s*사항\s*[:：]?\s*$")
#: 수열의 처음 차례(1 · 가 · ①) — 같은 머리 아래 둘째 목록(「입찰참가자격 확인 서류」 ①~)은 처음으로 다시 시작한다.
_PAPER_RESTART = frozenset({1, 0, ord("①")})


def submission_papers(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """입찰공고문의 제출서류 목록(11-13) → [{document, page, head, items: [{no, text, subs: [{no, text}]}], notes: [「※」 제출 방법 줄]}].

    머리 아래 같은 꼴 번호 줄이 항목(첫 항목은 수열의 처음 「1. · 가. · 1) · (1) · ① · ○」만) · 그보다 아래 꼴 번호 줄은 그 항목의 하위 서류(subs) ·
    「※」 줄이 제출 방법(파일 구분 · 용량 · 주민번호 가림) · 「-」 줄은 앞 항목에 · 표시 없는 줄은 앞 항목(또는 ※ 줄)에 이어 붙인다(PDF 줄바꿈 ·
    160 · 200자). 머리 다음 번호(「다.」 → 「라.」) · 위 꼴 번호(「6. 기타사항」) · 쪽 가운데 번호만 있는 줄(「8」 — 다음 절) · 「3-2.」 · 가로줄 ·
    덩어리 · 「< … >」 머리 · 첫 항목 전 표시 없는 줄 넷째에서 끝난다. 항목이 없는 머리(「제출서류 : 입찰공고서 참조」)는 뺀다.
    저장된 공고 일정표(`notice_schedule.documents`)는 그대로 둔다."""
    out: list[dict[str, Any]] = []
    for doc in docs:
        if doc.get("role") != "notice":
            continue
        lines, pages = _doc_lines(doc)
        current: dict[str, Any] | None = None
        style: str | None = None
        last: str | None = None  # 이어 붙일 곳 — "items" | "subs" | "notes"
        lead = 0  # 첫 항목 전 표시 없는 줄 수
        order: int | None = None  # 마지막 항목의 차례 — 같은 꼴 번호가 되돌아가면(4 → 3) 다음 장이다(1759644 · 11-13 독립 검토)
        for index, line in enumerate(lines + [""]):
            if current is not None and line:
                mark = next(((kind, m) for kind, pattern in _PAPER_MARKS if (m := pattern.match(line))), None)
                # 쪽 머리 · 꼬리의 번호만 있는 줄은 쪽 번호다(쪽을 넘는 목록은 이어 간다)
                section_no = _BARE_NO_RE.match(line) and 0 < index < len(lines) - 1 and pages[index - 1] == pages[index] == pages[index + 1]
                step = (_task_mark(line) or (None, None))[1] if mark and mark[0] == style else None
                if step is not None and order is not None and step < order and step not in _PAPER_RESTART and current["items"]:
                    tail = current["items"][-1]["text"].rstrip()
                    if tail.endswith(",") or tail.count("(") > tail.count(")"):
                        mark, step = None, None  # 「(서식6,」 다음 줄 「7) 각 1부」 — 앞 항목의 줄바꿈 조각(1747255)
                ended = ((current["_end"] and current["_end"].match(line)) or _BLOCK_RE.match(line) or line.startswith("<") or section_no
                         or _PAPER_STOP_RE.match(line) or (step is not None and order is not None and step < order and step not in _PAPER_RESTART)
                         or (line.startswith("※") and not current["items"] and _PAPER_ASIDE_HEAD_RE.search(line)))
                if not ended and line.startswith("※"):
                    if len(current["notes"]) < 8:
                        current["notes"].append(line.lstrip("※ ").strip()[:PAPER_NOTE_CHARS])
                        last = "notes"
                    continue
                if not ended and mark:
                    no, text = re.sub(r"\s+", "", mark[1].group(1)), line[mark[1].end():].strip()[:PAPER_ITEM_CHARS]
                    if mark[0] == style or (style is None and no in _PAPER_FIRST):
                        style = mark[0]
                        order = (_task_mark(line) or (None, None))[1]
                        if len(current["items"]) < 20:
                            current["items"].append({"no": no, "text": text, "subs": []})
                            last = "items"
                        continue
                    if style in _PAPER_LEVEL and _PAPER_LEVEL[mark[0]] > _PAPER_LEVEL[style]:
                        if len(subs := current["items"][-1]["subs"]) < 20:
                            subs.append({"no": no, "text": text})
                            last = "subs"
                        continue
                    # 위 꼴 번호 · 수열 처음이 아닌 첫 번호(「4. 낙찰자 공고」) — 다음 절
                dash = None if ended or mark else _PAPER_DASH_ITEM_RE.match(line)
                if dash and (style == "dash" or (style is None and not current["items"] and not _PAPER_SENTENCE_RE.search(dash["text"])
                                                  and not _PAPER_SENTENCE_HEAD_RE.search(_PAPER_ASIDE_RE.sub("", current["head"])) and not _PAPER_LABEL_LINE_RE.match(dash["text"]))):
                    style = "dash"  # 「-」 글머리 목록 — 위 꼴 번호(「9. 기타」)가 나오면 끝난다(_PAPER_LEVEL 밖 · 아래 꼴 없음)
                    if len(current["items"]) < 20:
                        current["items"].append({"no": "-", "text": dash["text"][:PAPER_ITEM_CHARS], "subs": []})
                        last = "items"
                    continue
                if not ended and not mark:
                    # ponytail: PDF 낱말 중간 줄바꿈도 띄어 잇는다(「바 랍니다」) — 붙여야 하면 앞 줄 길이로 가를 것
                    target = "items" if line.startswith(_PAPER_DASH) and last == "notes" and current["items"] else last
                    if target == "items":
                        current["items"][-1]["text"] = f"{current['items'][-1]['text']} {line}"[:PAPER_ITEM_CHARS]
                        continue
                    if target == "subs":
                        sub = current["items"][-1]["subs"][-1]
                        sub["text"] = f"{sub['text']} {line}"[:PAPER_ITEM_CHARS]
                        continue
                    if target == "notes":
                        current["notes"][-1] = f"{current['notes'][-1]} {line}"[:PAPER_NOTE_CHARS]
                        continue
                    if lead < PAPER_LEAD_LINES:
                        lead += 1  # 머리 바로 아래 설명 줄
                        continue
            if current is not None and (line or index == len(lines)):
                # 머리 다음 번호 · 다른 꼴 번호(위 절 「6. 기타사항」) · 덩어리 · 「< … >」 · 문서 끝 — 이 목록이 끝났다(이 줄은 새 머리일 수 있다)
                if current["items"]:
                    out.append({key: value for key, value in current.items() if key != "_end"})
                current = None
            if current is None and _PAPERS_HEAD_RE.match(line) and len(line) <= 70:
                current = {"document": doc.get("name"), "page": pages[index], "head": line, "items": [], "notes": [], "_end": _successor(line)}
                style, last, lead, order = None, None, 0, None
    return out


def draft_terms(draft: dict[str, Any]) -> dict[str, Any]:
    """초안의 사업 기본정보 — 저장된 `terms`. 옛 초안(2.8.0 전)은 협약 기간 글에서 기간 · 끝날만 다시 읽는다(금액은 저장하지 않았다)."""
    if isinstance(draft.get("terms"), dict):
        return draft["terms"]
    text = (((draft.get("form") or {}).get("agreement_period") or {}).get("text"))
    return stored_terms(project_terms(f"사업기간: {text}") if text else {})


# ---------------------------------------------------------------------------
# 목차 → 양식(form) · 절(unit)
# ---------------------------------------------------------------------------

#: 일반현황 칸 — 문서를 조립할 때 회사자료로 채운다(`plan_fill_service.FIELD_MAP`). AI 에는 보내지 않는다.
GENERAL_FIELDS: tuple[str, ...] = ("기관명", "대표자", "설립년월일", "주소", "전화번호", "주요 사업내용", "보유 인증", "주요 연혁", "주요 실적")
_GENERAL_RE = re.compile(r"일반\s*현황|회사\s*현황|제안사\s*현황|업체\s*현황")
#: 회사 자료가 없어 사람이 채우는 절 — AI 가 조직 · 인원을 지어내지 않게.
_HUMAN_RE = re.compile(r"조직\s*및\s*인원|인원\s*현황|인력\s*현황")
_PEOPLE_RE = re.compile(r"참여\s*인력|투입\s*인력|수행\s*인력")
#: 작성 방법이 투입인력 표를 요구하는 꼴 — 투입인력 + 이력 · 참여도 · 참여율 · 「(그림이나 표」(「공동수급 업체별 참여비율」은 아님 · 2.9.0) ·
#: 학력 · 경력 · 자격(2.10.0 D4 — 11-13 동국대 「참여 인력의 학력, 경력, 자격, 유사경력 등을 기술」에 표가 붙지 않았다).
_PEOPLE_GUIDE_RE = re.compile(r"이력|참여\s*(?:도|율)(?!\s*비율)|[(（]\s*그림\s*(?:이나|또는)?\s*표|학력|경력|자격")
#: 참여인력 표 사람 값 칸을 작성 방법 낱말로 지을 꼴(2.10.0 D4).
_PEOPLE_FIELD_RE = re.compile(r"학력|자격|유사\s*경력")
#: 배제 · 금지 줄(「불필요한 학력사항이나, 자격사항은 배제할 것」 · 1805118 「배재」 오타) — 표 · 칸 낱말로 읽지 않는다(T4 검토 · 1786460 회귀).
_PEOPLE_NEG_RE = re.compile(r"배[제재]|제외|불필요|하지\s*말")


def _asked(guide: str) -> str:
    """작성 방법에서 배제 · 금지 줄을 뺀 글 — 참여인력 표를 붙이고 칸 이름을 정할 때만."""
    return "\n".join(line for line in guide.splitlines() if not _PEOPLE_NEG_RE.search(line))
_SCHEDULE_RE = re.compile(r"추진\s*일정|수행\s*일정|일정\s*계획|사업\s*일정")
#: 작성 방법으로 일정표를 붙일 소항목 제목(2.10.0) — 계획 · 추진 · 일정 · 실행.
_PLAN_TITLE_RE = re.compile(r"계획|추진|일정|실행")
_TASK_RE = re.compile(r"세부\s*과(?:제|업)|과업별|수행\s*방안|추진\s*방안")
_CAPABILITY_RE = re.compile(r"특징|장점|역량|조직|인력|실적|업무\s*분장")

ORG_TABLE = {"key": "org", "title": "조직 및 인원 현황", "columns": ["구분", "인원(명)", "주요 업무"], "human_only": True}
PEOPLE_TABLE = {"key": "people", "title": "참여인력 현황", "columns": ["구분", "성명", "소속 · 직위", "관련 경력", "참여율(%)", "담당 업무"], "human_only": True}
#: 업무분장 역할 줄(「- PM(사업총괄): … 맡습니다」 · 2.10.0 T3 · D4 — 품질 게이트 ROLE_MISMATCH 와 한 곳) — 과업 이름표 낱말(담당 · 목표 · 방법 …)은 역할이 아니다.
ROLE_LINE_RE = re.compile(r"^\s*-\s*([^:：\-]{1,30}?)\s*[:：].*맡(?:습니다|고|아|으며)")
ROLE_LABELS = {"담당", "목표", "방법", "일정", "규모", "산출물검수", "위험→대응", "역할", "병행", "연결"}
#: 협업 체계로 적힌 발주 쪽 역할(「- 발주부서: … 승인을 맡습니다」)은 당사 참여인력이 아니다(11-13 2.10.0 독립 검토).
_CLIENT_ROLE_RE = re.compile(r"발주|수요\s*기관|전문\s*기관|감독|주관\s*기관|위원회")
#: 역할 · 담당 칸에 든 경력 · 자격 · 학위(품질 게이트 일정표 담당 칸 검사와 한 곳 · 2.9.0) — 그 칸은 역할 이름만.
PERSON_VALUE_RE = re.compile(r"경력|자격증?|기술사|박사|석사|현직|\d+\s*년\s*(?:이상|차)?|[(（][^)）]*(?:경력|자격|전문가)")
#: 담당 업무 칸의 사람 값(T4 검토) — 연차 · 괄호 안 경력 · 자격 · 「경력자 · 자격 보유」만(「AI 자격증 대비 과정」 · 「2027년 결과보고서」는 업무다).
_DUTY_PERSON_RE = re.compile(r"\d+\s*년\s*(?:이상|차|경력)|[(（][^)）]*(?:경력|자격|전문가)|경력자|자격\s*(?:증\s*)?(?:을\s*)?보유")
#: 담당 업무 칸 — 쌍점 뒤 글에서 「(을 · 를) 맡습니다 …」 꼬리를 뗀다.
_ROLE_DUTY_TAIL_RE = re.compile(r"\s*[을를]?\s*맡(?:습니다|고|아|으며).*$")
#: 참여인력 표 역할을 더 모을 소항목(제목 · 작성 방법) — 조직 · 업무분장 · 투입 인력 계획(11-14 평가: 투입 계획 소항목에만 있던 PM 이 표에서 빠졌다).
_ORG_UNIT_RE = re.compile(r"조직|업무\s*분장|투입\s*인력|인력\s*(?:투입|구성|운영|관리)")
#: 역할이 아니라 단계 · 기간인 줄(「- 마무리(11~12개월차): … 맡습니다」 · 11-14 평가 3위).
_STAGE_ROLE_RE = re.compile(r"개월\s*차|주\s*차|\bW\d|단계|착수|마무리|중간\s*점검|\d+\s*[~∼-]\s*\d+")
#: 비상대응 · 안전 · 산업재해 소항목의 「비상대응 조직」 역할 줄(「- 응급환자: … 맡고」 · 「- 운영인력: 대피 유도를 맡습니다」)은 참여인력이 아니다(11-14 · 1805118).
_SAFETY_UNIT_RE = re.compile(r"비상|재난|안전|산업\s*재해|재해\s*예방|응급")
STAFF_ROLE_ROWS = 12


def people_table(guide: str) -> dict[str, Any]:
    """참여인력 표 — 작성 방법이 학력 · 자격 · 유사경력을 요구하면 사람 값 칸을 그 낱말로(2.10.0 D4 · 아니면 지금 칸).
    구분(역할) · 담당 업무는 본문 업무분장에서(`staff_roles`) · 성명 · 학력 · 경력 · 참여율은 담당자 입력. 배제 줄은 보지 않는다(`_asked`)."""
    guide = _asked(guide)
    if not _PEOPLE_FIELD_RE.search(guide):
        return PEOPLE_TABLE
    career = "경력" + (" · 자격" if "자격" in guide else "") + ("(유사경력)" if re.search(r"유사\s*경력", guide) else "")
    return {**PEOPLE_TABLE, "columns": ["구분", "성명", "학력" if "학력" in guide else "소속 · 직위", career, "참여율(%)", "담당 업무"]}


def staff_roles(sections: list[dict[str, Any]], units: list[dict[str, Any]], item: str | None) -> list[list[str]]:
    """본문 업무분장 역할 줄 → [[역할, 담당 업무]](2.10.0 D4 · 11-13 동국대 — 본문에 역할 여섯이 있는데 참여인력 표는 한 줄 모두 빈칸이었다).
    참여인력 표 소항목 먼저, 그다음 제목 · 작성 방법에 조직 · 업무분장 · 투입 인력이 있는 AI 소항목(문서 순서)의 역할 줄을 **모두 합친다**
    (11-14 평가: 한 곳만 보아 다른 소항목에만 있던 PM 이 표에서 빠졌다 — 이름이 같거나 한쪽이 다른 쪽을 품으면(「운영 담당」 · 「교육운영 담당」) 앞 것 하나).
    단계 · 기간 줄(「마무리(11~12개월차)」) · 발주 쪽 역할은 뺀다. 경력 · 자격 꼴이 든 칸은 빈칸 표시(사람 값을 짓지 않는다 · 대표 결정 11-08) ·
    못 읽으면 빈 목록."""
    texts = {u["key"]: f"{u.get('plain') or ''} {u.get('guide') or ''}" for u in units}
    rows: list[list[str]] = []
    seen: list[str] = []
    for entry in sorted((e for e in sections if e.get("by") == "llm"), key=lambda e: e.get("key") != item):
        unit_text = texts.get(entry.get("key"), "")
        if entry.get("key") != item and (not _ORG_UNIT_RE.search(unit_text) or _SAFETY_UNIT_RE.search(unit_text)):
            continue
        for sentence in entry.get("sentences") or []:
            text = str(sentence.get("text") or "")
            if not (match := ROLE_LINE_RE.match(text)):
                continue
            role = match.group(1).strip()
            key = _name_key(re.sub(r"[(（][^)）]*[)）]", "", role))
            if (not key or key in ROLE_LABELS or _CLIENT_ROLE_RE.search(role) or _STAGE_ROLE_RE.search(role)
                    or any(key in other or other in key for other in seen)):
                continue
            seen.append(key)
            duty = _ROLE_DUTY_TAIL_RE.sub("", re.split(r"[:：]", text, maxsplit=1)[1]).strip()
            rows.append([HUMAN_INPUT if not role or PERSON_VALUE_RE.search(role) else role,
                         HUMAN_INPUT if not duty or _DUTY_PERSON_RE.search(duty) else duty])
    # 사업 책임자(PM · 총괄 · 책임자)를 표 맨 앞에 — 다른 소항목에서 모인 PM 이 맨 아래로 가지 않게
    rows.sort(key=lambda row: 0 if re.search(r"PM|총괄|책임자", row[0]) else 1)
    return rows[:STAFF_ROLE_ROWS]
#: 세부 추진 일정표(3차 지시서 §4 · 2.9.0) — 담당은 역할 이름만(사람 이름 없음 · 대표 결정 11-08) · 월별 칸 표(간트)는 내보낼 때 추진 기간 칸으로 그린다.
SCHEDULE_TABLE = {"key": "schedule", "title": "세부 추진 일정", "columns": ["추진 과업", "추진 기간", "담당(역할)", "주요 활동", "산출물"],
                  "human_only": False}
#: 핵심 마감과 책임(2.10.0 D2) — 일정표가 딸린 소항목에 AI 가 행을 돌려줄 때만 붙인다(세부 추진 일정표 5칸은 그대로).
MILESTONE_TABLE = {"key": "milestones", "title": "핵심 마감과 책임", "columns": ["항목", "책임 역할", "마감 기준", "확인 자료"], "human_only": False}
#: 과업별 대응(2.10.0 T3 · wording1) — 제목이나 작성 방법에 「범위」가 있는 첫 소항목(일정표 소항목 뺌)에 AI 가 행을 돌려줄 때만 붙인다
#: (원문에 과업 목록이 없으면 AI 가 비워 두고 표도 없다 — 빈 표는 「(담당자 입력)」 차단이 된다).
SCOPE_TABLE = {"key": "scope", "title": "과업별 대응", "columns": ["과업(제안요청서)", "제안 대응", "주요 산출물"], "human_only": False}
_SCOPE_RE = re.compile(r"범위")
#: 예산 배분안(2.10.0 D3 · 11-13 동국대 과업 「사. 구체적인 예산 계획 수립 및 집행」) — 사람 몫 표: 과업 줄은 원문 과업 이름 · 항목 · 산출 · 금액은
#: 담당자 입력 · 끝 줄(소계 · 부가세 · 합계)만 코드가 사업금액에서 나눈다. AI 에는 보내지 않는다(숫자를 짓지 않음 · §11).
BUDGET_TABLE = {"key": "budget", "title": "예산 배분안(사업금액 기준)", "columns": ["과업", "항목", "산출(수량 × 단가)", "금액(원)"], "human_only": True}
_BUDGET_TASK_RE = re.compile(r"예산\s*(?:계획|편성|수립|집행)")
_HANGUL_ORDER = "가나다라마바사아자차카타파하"
BUDGET_TASK_ROWS = 15


def _task_mark(line: str) -> tuple[str, int | None] | None:
    """번호 줄의 꼴 · 차례(가 = 0 · 1 = 1 · ① = 순서) — 글머리(「○」)는 차례 없음. 번호 줄이 아니면 None."""
    for kind, pattern in _PAPER_MARKS:
        if match := pattern.match(line):
            raw = re.sub(r"[\s.()]", "", match.group(1))
            if kind == "hangul":
                return kind, _HANGUL_ORDER.find(raw) if raw in _HANGUL_ORDER else None
            # 「①」.isdigit() 은 참이라 isdecimal 로 본다(원 번호 줄에서 int 가 멈추던 것 · 11-13)
            return kind, int(raw) if raw.isdecimal() else ord(raw) if kind == "circled" else None
    return None


def budget_tasks(excerpt: str) -> list[str]:
    """원문 과업 목록 중 예산 과업 줄(번호 줄 · 「사. 구체적인 예산 계획 수립 및 집행」)이 든 묶음 → 과업 이름(번호 포함 · 원문 그대로).
    같은 꼴 번호 줄만 · 차례가 이어질 때만(건너뜀 「사 → 자」은 받음) · 위 꼴 번호(「2. 세부 요구사항」)에서 멈추고 아래 꼴 번호 · 글머리 줄은 건너뛴다.
    예산 과업 줄이 없으면 빈 목록(글머리 줄 「- 예산 집행은 …」 · 「○ 예산 집행 계획」(작성요령 꼴)은 과업 줄이 아니다 · 맨 위 꼴 「4. 예산 집행 기준」은
    장 머리라 아니다 — 장 목록이 과업 줄이 되던 것 · T5 검토)."""
    # ponytail: 맨 위 꼴(1.)은 언제나 장으로 본다 — 「Ⅲ. 과업 내용」 아래 「2. 예산 편성」처럼 1. 꼴이 과업 목록인 공고는 표 없이 검토 줄만(놓치는 쪽)
    lines = [line.strip() for line in (excerpt or "").splitlines()]
    at = next((i for i, line in enumerate(lines)
               if _BUDGET_TASK_RE.search(line) and (mark := _task_mark(line)) and mark[0] not in ("bullet", "dot")), None)
    if at is None:
        return []
    kind, order = _task_mark(lines[at])  # type: ignore[misc]
    found = {at}
    for step in (-1, 1):
        last, i = order, at + step
        while 0 <= i < len(lines):
            mark = _task_mark(lines[i])
            if mark and _PAPER_LEVEL[mark[0]] < _PAPER_LEVEL[kind]:
                break  # 위 꼴 번호 — 다른 절
            if mark and mark[0] == kind:
                if last is not None and mark[1] is not None and (mark[1] - last) * step <= 0:
                    break  # 차례가 끊김 — 다른 목록
                found.add(i)
                last = mark[1]
            i += step
    return [re.sub(r"\s+", " ", lines[i])[:PAPER_ITEM_CHARS] for i in sorted(found)][:BUDGET_TASK_ROWS]


def budget_unit(form: dict[str, Any], tasks: list[str]) -> tuple[str, str] | None:
    """예산 배분안을 붙일 소항목 (대항목 key, 소항목 key) — 제목 · 작성 방법에 예산 계획 · 편성 · 수립 · 집행이 있는 첫 소항목,
    없고 원문 과업에 예산 과업이 있으면(`tasks`) 세부 추진 일정표 소항목(「항목별 · 단계별 · 기간별 세부계획」 자리 · 11-13 동국대 Ⅳ-2).
    둘 다 없으면 None(일정표도 없는 목차는 표 없이 검토 줄만)."""
    items = [(section["key"], item) for section in form.get("sections") or [] for item in section.get("items") or []
             if item.get("kind") == "item" and not item.get("annex")]
    found = next((pair for pair in items if _BUDGET_TASK_RE.search(f"{pair[1].get('plain') or ''} {pair[1].get('guide') or ''}")), None)
    if found is None and tasks:
        schedule = next((t.get("item") for t in form.get("tables") or [] if t.get("key") == SCHEDULE_TABLE["key"]), None)
        found = next((pair for pair in items if pair[1]["key"] == schedule), None)
    return (found[0], found[1]["key"]) if found else None


def budget_totals(won: int, vat: str | None) -> list[list[str]]:
    """사업금액 → 예산 배분안 끝 줄(칸 넷) — 부가세 포함이면 소계(공급가액) · 부가가치세(10%) · 합계(부가세 포함)(공급가액은 내림해
    합계가 사업금액과 같다 · 40,700,000 → 37,000,000 + 3,700,000), 별도 · 모름이면 합계 줄만(부가세를 짓지 않는다)."""
    if vat == "포함":
        supply = won * 10 // 11
        return [["소계(공급가액)", "", "", f"{supply:,}"], ["부가가치세(10%)", "", "", f"{won - supply:,}"],
                ["합계(부가세 포함)", "", "", f"{won:,}"]]
    return [[f"합계(부가세 {vat})" if vat else "합계", "", "", f"{won:,}"]]
#: 「마감 기준」 칸의 연도 없는 날짜(「12. 29.」) — 원문 숫자 대조는 소수와 헷갈려 읽지 않으므로 이 칸에서만 「12월 29일」로 읽는다(T2 검토).
_BARE_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?(?!\d)")
#: 원문이 요구한 보고(착수 · 중간 · 최종) — 일정표에 그 줄이 있어야 한다(품질 게이트 SCHEDULE_TASK_MISSING · 11-11 1위 Codex 중간보고 줄 없음).
SCHEDULE_REPORTS: tuple[tuple[str, str, str], ...] = (
    ("착수 보고", r"착수\s*(?:보고|계획\s*보고|보고서)|보고\s*[(（][^)）]{0,20}착수", r"착수"),
    ("중간 보고", r"중간\s*(?:보고|결과\s*보고|점검\s*보고|보고서)|보고\s*[(（][^)）]{0,20}중간", r"중간"),
    ("최종 보고", r"(?:최종|완료|결과)\s*(?:보고|결과\s*보고|보고서)|보고\s*[(（][^)）]{0,20}(?:결과|최종|완료)", r"최종|완료|결과\s*보고|결과보고"),
)


def report_task(name: str, task: str) -> bool:
    """일정표 과업 칸이 그 보고 줄인가(「착수 보고」 · 「중간 보고」 · 「최종 보고」) — 최종은 「최종 · 완료 보고 · 결과 보고」 꼴이되
    「중간 결과 보고 · 1차 결과 보고」는 아니다(3차 검토 — 세부 칸의 「종료 7일 이내 결과보고」 · 과업 「교육과정 개발 완료」를 최종으로 셌다)."""
    if name == "착수 보고":
        return bool(re.search(r"착수", task))
    if name == "중간 보고":
        return bool(re.search(r"중간", task))
    return bool(re.search(r"최종|(?:완료|결과)\s*보고", task)) and not re.search(r"중간|\d\s*차", task)


def schedule_expect(text: str) -> list[str]:
    """원문(발췌)이 요구한 보고 이름 — 일정표가 그 줄을 빼먹었는지 품질 게이트가 본다(3차 지시서 §4 「과업 누락」)."""
    return [name for name, required, _found in SCHEDULE_REPORTS if re.search(required, text or "")]


#: 원문이 대면 · 집합 · 현장으로 정한 활동(「대면 미팅」 · 「집합 교육」 · 「현장 실증」) — 품질 게이트 REMOTE_SWAP 이 본문의 온라인 · 원격 전환과 견준다
#: (2.10.0 · 11-13 동국대 「대면 미팅」 → 「온라인 미팅으로 전환」). 「현지 적합성 점검」처럼 활동 낱말이 바로 붙지 않으면 아니다.
_ONSITE_RE = re.compile(r"(?<!비)(?:대면|집합|현장|현지|오프라인|방문)\s*(?:형\s*)?"
                        r"(교육|강의|연수|미팅|회의|상담|컨설팅|멘토링|코칭|실증|행사|워크숍|네트워킹|교류|피칭|설명회|간담회|발표)"
                        r"(?!비|료|\s*부담)")  # 「오프라인 회의비 등 제안사 부담」은 비용 줄이지 활동이 아니다(T2 검토)
#: 같은 줄이 온라인을 허용하면(「온·오프라인」 · 「온라인 병행」 · 「비대면」) 대면으로 정한 것이 아니다.
_ONLINE_OK_RE = re.compile(r"온라인|비\s*대면|원격|화상|온\s*[·ㆍ/,]?\s*오프라인")


def onsite_activities(text: str) -> list[dict[str, str]]:
    """원문(발췌)이 대면으로 정한 활동 낱말과 그 원문 줄(낱말마다 첫 줄 · 10개) → [{word, quote}]. 없으면 빈 목록."""
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        if _ONLINE_OK_RE.search(line):
            continue
        for match in _ONSITE_RE.finditer(line):
            found.setdefault(match.group(1), re.sub(r"\s+", " ", line).strip()[:_NOTE_CHARS])
    return [{"word": word, "quote": quote} for word, quote in list(found.items())[:10]]
EVAL_TABLE_KEY = "evaluation_map"
ANNEX_TABLE_KEY = "annex"
#: 서식을 채워 붙이는 소항목(11-06 3차 검토 #21) — AI 가 쓸 본문이 없다(서약서 · 신청서 · 견적서 …). 제목 끝 낱말이거나, 제목에서 떼어 낸
#: 꼬리(「<서식1> ※ 원본 별도 제출」 · 「(【붙임서식 2호】참조)」 · 「※ 증빙서류 별도 제출」)가 서식 · 증빙이다(「※ <서식8> 참조하여 자율 작성」은 쓴다).
_FORM_TITLE_RE = re.compile(r"(?:서약서|각서|신청서|증명서|견적서|가격\s*제안서|동의서|협약서)\s*(?:\([^)]*\))?$")
_FORM_NOTE_RE = re.compile(r"서식|별지|별첨|붙임|증빙|별도\s*제출")
_FREE_NOTE_RE = re.compile(r"자율|자유")
#: 꼬리에서 서식 이름만(「<서식1>」 · 「【붙임서식 1호】」 → 「붙임서식 1호」 · 「[별지 제2호]」 → 「별지 제2호」) — 「※ …」 지시 · 「(…참조)」는 제출용에 싣지 않는다(4차 확인).
_FORM_NAME_RE = re.compile(r"<\s*(?:별지\s*)?서식[^<>]{0,10}>|【\s*([^】]{1,20}?)\s*】|\[\s*((?:별지|별첨|붙임|서식)[^\[\]]{0,12}?)\s*\]")
_FORM_ORDER_RE = re.compile(r"※\s*(.+)$")
DEFAULT_FORM = "제안요청서 서식"


def _form_name(note: str) -> str:
    if match := _FORM_NAME_RE.search(note):
        return match.group(1) or match.group(2) or re.sub(r"\s+", "", match.group(0))
    return DEFAULT_FORM
#: 제출 서류 목록 소항목(11-06 심사 ② — 「제안서 이외의 입찰 참가를 위한 별지서식 자료, 기타 제출 서류 목록을 작성 및 붙임」) — 과업 낱말이 없다.
_ANNEX_GUIDE_RE = re.compile(r"제출\s*서류\s*목록|별지\s*서식|붙임\s*$", re.M)
_ANNEX_TASK_RE = re.compile(r"과업|수행|운영|교육|방안|계획|전략|아이디어|추가\s*제안")


def _major_no(no: str) -> str:
    """대항목 번호 — 라틴 「V」는 로마 숫자 글자 「Ⅴ」로(나머지 「Ⅲ」 글자와 섞이지 않게 · 11-06 심사). 숫자는 그대로."""
    return _ROMAN_GLYPHS[_ROMAN[no] - 1] if no in _ROMAN and no not in _ROMAN_GLYPHS else no


def major_numbers(outline: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
    """대항목 번호(쓰기 `build_form` · 미리 보기 `outline_preview` 한 곳 · 2.8.0 B5) — (번호 목록, 고쳐 붙인 것 [{from, to, title}]).
    로마 숫자가 앞 번호 이하(같거나 거꾸로)면 앞 번호 + 1 로 고쳐 붙인다(원문 오타 「Ⅵ. 결과 활용성 부문」 → 「Ⅵ. 기 타」 · 1805118).
    건너뜀(「Ⅲ → Ⅴ」)은 원문대로 둔다(2.6.1). 원문 읽기(`_parse_outline`)는 원문 번호 그대로다."""
    numbers: list[str] = []
    fixed: list[dict[str, str]] = []
    previous = 0
    for major in outline:
        no = _major_no(str(major["no"]))
        value = _ROMAN.get(no)
        if value is not None and 0 < previous < len(_ROMAN_GLYPHS) and value <= previous:
            fixed.append({"from": no, "to": _ROMAN_GLYPHS[previous], "title": str(major.get("title") or "")})
            no, value = _ROMAN_GLYPHS[previous], previous + 1
        numbers.append(no)
        previous = value or 0
    return numbers, fixed


def build_form(outline: list[dict[str, Any]], evaluation: dict[str, Any], terms: dict[str, Any], *, title: str) -> dict[str, Any]:
    """목차 → 사업계획서와 같은 모양의 양식(sections · tables). 대항목 제목은 제안요청서 번호를 단다(「Ⅰ. 제안개요」 · 겹친 번호는
    `major_numbers` 가 고쳐 붙이고 `renumbered` 에 남긴다). 소항목 번호(`no`)는 원문 그대로 둔다 — 조견표 「제안서 해당 목차」가 이 값을 쓴다(「1.1」 · 「3」 · 「가」)."""
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    numbers, renumbered = major_numbers(outline)
    for m, major in enumerate(outline, start=1):
        no = numbers[m - 1]
        key = f"M{m}"
        items = major.get("items") or [{"no": "", "title": major["title"], "guide": major.get("guide") or [], "note": major.get("note") or "",
                                        "whole": True}]
        section = {"key": key, "no": no, "title": f"{no}. {major['title']}", "items": []}
        for n, item in enumerate(items, start=1):
            item_key = key if item.get("whole") else f"{key}-{n}"
            name = item["title"] if item.get("whole") else f"{item['no']}. {item['title']}"
            guide = "\n".join(item.get("guide") or [])
            entry = {"key": item_key, "no": "" if item.get("whole") else item["no"], "title": name, "plain": item["title"],
                     "guide": guide, "kind": "item"}
            note = item.get("note") or ""
            if _GENERAL_RE.search(item["title"]):
                entry["kind"] = "fields"
                entry["fields"] = [{"label": label, "human_only": False} for label in GENERAL_FIELDS]
            elif _HUMAN_RE.search(item["title"]):
                entry["kind"] = "human"
                tables.append({**ORG_TABLE, "section": key, "item": item_key})
            elif _PEOPLE_RE.search(item["title"]):
                tables.append({**people_table(guide), "section": key, "item": item_key})
            if entry["kind"] != "fields" and (_FORM_TITLE_RE.search(item["title"])
                                              or (_FORM_NOTE_RE.search(note) and not _FREE_NOTE_RE.search(note))):
                entry["kind"] = "human"
                entry["form"] = _form_name(note)
                entry["form_order"] = order.group(1).strip() if (order := _FORM_ORDER_RE.search(note)) else ""  # 「원본 별도 제출」 — 빈칸 목록으로
            elif entry["kind"] == "item" and _ANNEX_GUIDE_RE.search(guide) and not _ANNEX_TASK_RE.search(f"{item['title']} {guide}"):
                entry["annex"] = True
            if _SCHEDULE_RE.search(item["title"]) and not any(t["key"] == "schedule" for t in tables):
                tables.append({**SCHEDULE_TABLE, "section": key, "item": item_key})
            section["items"].append(entry)
        sections.append(section)
    if not any(t["key"] == PEOPLE_TABLE["key"] for t in tables):
        # 제목에 「참여인력」이 없어도 작성 방법이 투입인력 이력 · 참여도를 표로 요구하면 사람 몫 표를 붙인다(3차 지시서 §1 · 11-11 3위 Ⅳ-2 —
        # 원문이 요구한 인력 표가 없어 게이트가 「인력 미확정」을 조직 표로만 셌다 · 내용은 담당자 입력)
        for section in sections:
            item = next((i for i in section["items"] if i["kind"] == "item" and _PEOPLE_RE.search(_asked(i["guide"]))
                         and _PEOPLE_GUIDE_RE.search(_asked(i["guide"]))), None)
            if item:
                tables.append({**people_table(item["guide"]), "section": section["key"], "item": item["key"]})
                break
    if not any(t["key"] == SCHEDULE_TABLE["key"] for t in tables):
        # 제목에 일정 낱말이 없어도 작성 방법이 추진 일정을 요구하면 그 소항목에 세부 추진 일정표(첫 곳 · 2.10.0 — 11-13 동국대 Ⅳ-2
        # 「사업 수행계획」 작성 방법 「추진방법, 추진일정 등」 · 평가 「세부 일정의 구체성」인데 일정표 · 간트가 없었다). 제목이 계획 · 추진 ·
        # 실행 소항목일 때만 — 대항목 작성 방법이 마지막 소항목에 몰린 목차(1697240 「6. 산출물 내역」)에는 붙이지 않는다
        found = next(((section, i) for section in sections for i in section["items"] if i["kind"] == "item" and _SCHEDULE_RE.search(i["guide"])
                      and _PLAN_TITLE_RE.search(i["plain"])), None)
        if found:
            tables.append({**SCHEDULE_TABLE, "section": found[0]["key"], "item": found[1]["key"]})
    return {
        "title": title,
        "sections": sections,
        "tables": tables,
        "evaluation": evaluation,
        # start — 실제 시작 연월(두 날짜 꼴만 · 월별 칸 머리 달 이름) · open_start — 끝만 알고 시작은 날짜가 아님(「계약 체결일 ~ …」 ·
        # 일정표 「협약 기간 밖」은 끝 쪽만 본다 · 2.8.0 B6)
        # contract_from · days · weeks — 계약 예정일 ~ 고정 끝날(`contract_span` · D1 · 13주 미만이면 weeks)
        "agreement_period": {"text": terms.get("period"), "months": terms.get("months"), "end": terms.get("end"), "start": terms.get("start"),
                             "open_start": bool(terms.get("end") and not terms.get("months")),
                             "contract_from": terms.get("contract_from"), "days": terms.get("days"), "weeks": terms.get("weeks")}
        if terms.get("period") else None,
        "form_examples": {},
        "budget": None,
        "renumbered": renumbered,
    }


def form_units(form: dict[str, Any]) -> list[dict[str, Any]]:
    """양식 → 절 목록(사업계획서 `form_units` 와 같은 열쇠 + 입찰 표시)."""
    units: list[dict[str, Any]] = []
    sections = form.get("sections") or []
    for section in sections:
        for item in section.get("items") or []:
            plain = item.get("plain") or item["title"]
            # 「개요」 분량(700자)은 대항목이 여럿일 때 첫 대항목만 — 대항목 하나뿐인 목차는 그것이 본문 전부다(11-06 3차 검토 #20)
            overview = len(sections) > 1 and section is sections[0]
            units.append({
                "key": item["key"], "kind": "fields" if item["kind"] == "fields" else "item", "human": item["kind"] == "human",
                "title": item["title"], "plain": plain, "optional": False, "major_key": section["key"], "major_title": section["title"],
                "guide": item.get("guide") or "", "fields": item.get("fields") or [], "form": item.get("form") or "",
                "form_order": item.get("form_order") or "",
                "annex": bool(item.get("annex")),
                "tables": [t["key"] for t in form.get("tables") or [] if t.get("item") == item["key"]],
                "target": "task" if _TASK_RE.search(plain) else "overview" if overview else "default",
            })
    return units


def unit_number(form: dict[str, Any], key: str) -> str:
    """조견표의 「제안서 해당 목차」 — 「Ⅲ-4」 꼴(대항목만이면 「Ⅵ」 · 「1.1」 꼴 소항목은 그 번호 그대로 · 11-06 3차 검토 #19)."""
    for section in form.get("sections") or []:
        if section.get("key") == key:
            return section["no"]  # 대항목 자체(조견표 이름 짝 · `title_matches`)
        for item in section.get("items") or []:
            if item["key"] == key:
                minor = item.get("no") or ""
                return minor if "." in minor else f"{section['no']}-{minor}" if minor else section["no"]
    return ""


_SECTION_NO_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[IVX]{1,4}|\d{1,2})\s*\.\s*")


def title_matches(form: dict[str, Any], evaluation: dict[str, Any], written: set[str],
                  covered: dict[str, list[str]]) -> dict[str, list[str]]:
    """AI 가 적지 않은 평가 항목 → 이름이 같은 소항목(없으면 대항목) 열쇠. 본문이 남은 곳(`written`)만 · 짧은 이름(4자 미만)은 같을 때만
    (11-07 1804104 — 「사업수행조직」 ↔ Ⅴ-5 · 「사업수행 관리」 ↔ Ⅴ. 사업수행관리가 조견표에서 빈칸이었다)."""
    def hit(name: str, title: str) -> bool:
        return bool(title) and (title == name or (len(name) >= 4 and name in title))

    found: dict[str, list[str]] = {}
    sections = form.get("sections") or []
    for item in evaluation.get("items") or []:
        if covered.get(item["name"]):
            continue
        name = _compact(item["name"])
        keys = [unit["key"] for section in sections for unit in section.get("items") or []
                if unit["key"] in written and hit(name, _compact(unit.get("plain") or unit["title"]))]
        if not keys:
            keys = [section["key"] for section in sections
                    if any(unit["key"] in written for unit in section.get("items") or [])
                    and hit(name, _compact(_SECTION_NO_RE.sub("", section.get("title") or "")))]
        if keys:
            found[item["name"]] = keys
    return found


def _name_key(text: Any) -> str:
    """평가 항목 이름 맞추기 — 공백 · 문장부호를 뺀 글(「교육(수료)생 관리」 = 「교육 (수료) 생 관리」)."""
    return re.sub(r"[\s·ㆍ()（）\[\]「」『』\"'.,:：/-]+", "", str(text or ""))


#: 평가 항목 · 기준의 흔한 말 — 핵심 낱말에서 뺀다(2.8.0 B4). 「기획 / 운영」처럼 짝 항목을 가르는 말도 빼므로
#: 짝 항목은 핵심 낱말이 같아지고 소제목 짝을 짓지 않는다(`heading_matches`).
_EVAL_GENERIC = frozenset((
    "방안 계획 적정성 적절성 구체성 실행가능성 실현가능성 가능성 여부 평가 수립 제시 사업 위한 대한 통한 따른 관련 전체 세부 내용 "
    "우수성 효과성 신뢰성 실효성 타당성 충실성 적합성 차별성 전문성 요구사항 요구 사항 이해도 이해 능력 역량 방법 강화 제고 구성 진행 결과 "
    "목표 달성 도출 반영 기반 고려 특성 연계 실질적인 명확히 기획 운영 관리 수행 추진 전략 체계 분석 정도 등의 실행 구체 프로젝트").split())
#: 조사 — 「가 · 이」는 떼지 않는다(「전문가」 → 「전문」이 됐다).
_JOSA = ("에서", "으로", "에게", "의", "을", "를", "은", "는", "에", "과", "와", "로", "및", "등")
#: 풀이말 꼴(「이해했는지」 · 「구체적이고」 · 「실행가능한지」) — 내용 낱말이 아니다.
_PREDICATE_RE = re.compile(r"(?:는지|한지|인지|이고|하고|하는|되는|적인|하여|하게)$")


def _generic_word(token: str) -> bool:
    """흔한 말이거나 흔한 말끼리 붙은 낱말(「사업이해도」 = 사업 + 이해도 · 「방안이」 = 방안 + 조사)."""
    return token in _EVAL_GENERIC or token in _JOSA or token in ("이", "가") or any(
        token.startswith(g) and _generic_word(token[len(g):]) for g in _EVAL_GENERIC if len(token) > len(g))


def eval_core_words(text: Any) -> set[str]:
    """평가 항목 · 기준 글의 핵심 낱말(조사 · 흔한 말 · 풀이말을 뺀 2자 이상 낱말 · 끝에 붙은 흔한 말은 뗌 — 「품질관리」 → 「품질」 ·
    「연구반운영역량」 → 「연구반」) — 소제목 짝(`heading_matches`) · 품질 게이트 내용 검사가 함께 쓴다."""
    words: set[str] = set()
    for token in re.findall(r"[가-힣A-Za-z]+", str(text or "")):
        for josa in _JOSA:
            if token.endswith(josa) and len(token) - len(josa) >= 2:
                token = token[: -len(josa)]
                break
        if len(token) < 2 or _generic_word(token) or (len(token) >= 3 and _PREDICATE_RE.search(token)):
            continue
        while tail := next((g for g in _EVAL_GENERIC if token.endswith(g) and len(token) - len(g) >= 2), None):
            token = token[: -len(tail)]
        if not _generic_word(token):
            words.add(token)
    return words


#: 평가 항목 이름의 같은 뜻 낱말(본문은 우리말로 쓴다 — 「리스크 관리사항」 ↔ 「위험 대응」).
SAME_WORDS = {"리스크": "위험", "위험": "리스크"}


def word_re(word: str) -> re.Pattern[str]:
    """핵심 낱말 찾기 — 네 글자 넘는 붙은 한글 낱말은 두 글자씩 사이 4자까지 떨어져도(「교육개발」 ↔ 「교육과정개발」 · 「취업현황을조사」) ·
    같은 뜻 낱말(`SAME_WORDS`)도. 조견표 짝(`guide_matches`) · 품질 게이트 내용 검사가 함께 쓴다."""
    if len(word) < 4 or not re.fullmatch(r"[가-힣]+", word):
        pattern = re.escape(word)
    else:
        chunks = [word[i:i + 2] for i in range(0, len(word), 2)]
        if len(chunks[-1]) == 1:
            chunks[-2] += chunks.pop()
        pattern = ".{0,4}".join(map(re.escape, chunks))
    return re.compile(f"{pattern}|{re.escape(SAME_WORDS[word])}" if word in SAME_WORDS else pattern)


def criteria_words(item: dict[str, Any], texts: dict[str, str]) -> list[str]:
    """평가 항목 이름 + 세부 기준 글의 핵심 낱말(`_name_key` 꼴) — 다른 낱말 안에 든 짧은 낱말(「교육」 ⊂ 「교육과정」)과, 소항목이 넷 이상일 때
    그 절반 넘게 나오는 흔한 낱말은 뺀다(내용 근거가 아니다 · 3차 지시서 §3 「키워드 포함만으로 판단하지 않는다」)."""
    words = {_name_key(w) for w in eval_core_words(f"{item.get('name') or ''} {' '.join(map(str, item.get('criteria') or []))}")} - {""}
    words = {w for w in words if not any(w != other and w in other for other in words)}
    if len(texts) >= 4:
        words = {w for w in words if sum(1 for text in texts.values() if word_re(w).search(text)) <= len(texts) / 2}
    return sorted(words)


#: 작성 방법 짝 — 기준 낱말이 소항목 제목 · 작성 방법에 이만큼 이상 · 다음 소항목보다 이만큼 더 · 본문에도 이만큼 이상 들어야 붙인다.
GUIDE_MIN_WORDS = 2
GUIDE_MARGIN = 2


def guide_matches(form: dict[str, Any], evaluation: dict[str, Any], sections: list[dict[str, Any]],
                  covered: dict[str, list[str]]) -> dict[str, list[str]]:
    """AI · 이름 · 소제목 짝이 모두 없는 **정성** 평가 항목 → 평가 기준 낱말이 소항목 제목 · 작성 방법(원문이 그 소항목에 쓰라고 한 것)에
    가장 많이 든 소항목(3차 지시서 §3 · 11-11 3위 Claude 「사업 수행역량」 — 이름이 흔한 말뿐이라 소제목 짝도 못 지었다).
    관련성 확인: 단독 1위 · 다음과 2개 이상 차 · **본문**에도 기준 낱말 2개 이상일 때만. 아니면 빈칸 그대로(AI 재질문 · 품질 게이트로)."""
    guides = {item["key"]: _name_key(f"{item.get('plain') or item.get('title') or ''} {item.get('guide') or ''}")
              for section in form.get("sections") or [] for item in section.get("items") or []}
    bodies = {entry["key"]: _name_key(" ".join(str(s.get("text") or "") for s in entry.get("sentences") or []))
              for entry in sections if entry.get("by") == "llm" and entry.get("sentences")}
    found: dict[str, list[str]] = {}
    for item in evaluation.get("items") or []:
        if covered.get(item["name"]) or item.get("kind") == "정량" or not bodies:
            continue
        patterns = [word_re(w) for w in criteria_words(item, bodies)]
        if len(patterns) < GUIDE_MIN_WORDS:
            continue
        scores = sorted(((sum(1 for p in patterns if p.search(guides.get(key, ""))), key) for key in bodies), reverse=True)
        top, key = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0
        if top >= GUIDE_MIN_WORDS and top - second >= GUIDE_MARGIN and sum(1 for p in patterns if p.search(bodies[key])) >= GUIDE_MIN_WORDS:
            found[item["name"]] = [key]
    return found


def heading_matches(evaluation: dict[str, Any], sections: list[dict[str, Any]], covered: dict[str, list[str]]) -> dict[str, list[str]]:
    """AI · 이름 짝이 모두 없는 평가 항목 → 본문 「○」 소제목 줄에 이름의 핵심 낱말이 모두 든 소항목 — **한 곳뿐일 때만**(2.8.0 B4 ·
    11-10 2위 「○ 4.1 취업현황조사 및 DB 관리」 · 3위 「○ … 데이터 기반 품질관리」). 핵심 낱말이 같은 짝 항목(「취업현황조사 기획 / 운영」)이
    있으면 어느 쪽인지 가를 수 없어 붙이지 않는다(빈칸 그대로 — 품질 게이트가 차단으로 알린다)."""
    items = evaluation.get("items") or []
    cores = {item["name"]: frozenset(_name_key(word) for word in eval_core_words(item["name"])) for item in items}
    heads = {entry["key"]: [_name_key(s.get("text")) for s in entry.get("sentences") or []
                            if plan_export_service._subheading(str(s.get("text") or ""))]
             for entry in sections if entry.get("by") == "llm"}
    found: dict[str, list[str]] = {}
    for item in items:
        core = cores[item["name"]]
        if covered.get(item["name"]) or not core or list(cores.values()).count(core) > 1:
            continue
        keys = [key for key, lines in heads.items() if any(all(word in line for word in core) for line in lines)]
        if len(keys) == 1:
            found[item["name"]] = keys
    return found


# ---------------------------------------------------------------------------
# 회사 근거 · 밖(LLM)으로 보내는 본문 (허용 목록)
# ---------------------------------------------------------------------------


def _words(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z]{2,}", text or ""))


#: 실제 수행 실적 분야(`performance_match_service.project_rows` 와 같은 세 분야).
PROJECT_FIELDS = ("대학·교육기관", "공공·지자체", "기업·재직자·컨설팅")
#: 공고 제목의 흔한 낱말 — 주제 낱말이 아니다(실적 「주제 일치」를 가를 때).
_TOPIC_GENERIC = frozenset(
    "교육 운영 개발 지원 사업 과정 교육과정 프로그램 고도화 양성 인력 전문 전문인력 수료 수료생 교육생 년 및 등 위한 기반 관리 운영지원 "
    "용역 구축 추진 실무 활용 역량 강화 역량강화 실시 대상 기관 전문가 풀 지원사업 개선 확산".split())


def topic_terms(title: str) -> set[str]:
    """공고 제목의 주제 낱말(「개인정보 · 보호」 · 「가명정보」) — 흔한 낱말 · 숫자 · 연도는 뺀다."""
    words = {w for w in re.findall(r"[가-힣A-Za-z]{2,}", re.sub(r"[(（][^)）]*[)）]", " ", title or "")) if w not in _TOPIC_GENERIC}
    return {w for w in words if not re.fullmatch(r"\d+년?", w) and not re.search(r"[A-Za-z][가-힣]|[가-힣][A-Za-z]", w)}


def company_pieces(company: dict[str, Any], topic: str, title: str = "") -> dict[str, Any]:
    """회사 원자료 → 근거 조각(안). 실적 원장은 외부 사용 「가능」 행만 · 증빙 확인 전(`performance_ledger.evidence_state` 「UNVERIFIED」 —
    증빙 메모 「미확인 · 확인 필요」)은 빼고(2.8.0 B7) · 사업 낱말과 겹치는 순 · 최근 순으로 6행."""
    profile = company.get("profile") or {}
    capacity = company.get("capacity") or {}
    words = _words(topic)
    rows = [r for r in company.get("ledger_all") or [] if str(r.get("external_use") or "") == "가능"
            and performance_ledger.evidence_state(r)[0] != "UNVERIFIED"]

    def rank(row: dict[str, Any]) -> tuple[int, int, int]:
        year = str(row.get("year") or "0")
        # 실제 수행 실적(교육 · 컨설팅 · 공공 사업)을 지정 · 인증 · 지식재산 행보다 먼저(2.9.0 · 3차 지시서 §8 — 1위에 「창업기업 확인」이 실적으로 갔다)
        return (0 if str(row.get("field")) in PROJECT_FIELDS else 1,
                -len(words & _words(f"{row.get('title')} {row.get('summary')} {row.get('field')}")), -int(year) if year.isdigit() else 0)

    rows.sort(key=rank)
    picked = rows[:LEDGER_PIECES]
    topic = topic_terms(title)
    return {
        "profile": profile,
        "capacity": capacity,
        "ledger": [{**row, "id": f"ledger:{row.get('seq')}"} for row in picked],
        # 이 공고 분야(제목의 주제 낱말)가 든 실적이 있나 — 없으면 작성기에 「교육 운영 경험으로만」(3차 지시서 §8 「없는 전문성을 만들지 않는다」)
        "topic_match": not topic or any(any(term in f"{row.get('title')} {row.get('summary')}" for term in topic) for row in picked),
        "topic_terms": sorted(topic),
        # 평가본 공고에서 제목 · 요약 속 기관 이름을 유형으로 바꿀 때 — 그 행 기관만이 아니라 원장 모든 행의 기관 이름(품질 게이트 식별 낱말과 같은 집합 ·
        # 긴 이름 먼저 · 11-13 독립 검토: 다른 행 기관 「…사업단」이 제목에 남았다). AI 에는 보내지 않는다(llm_payload 가 쓰기만).
        "agency_names": sorted({name for r in company.get("ledger_all") or [] for name in agency_names(r.get("agency"))}, key=len, reverse=True),
    }


#: 실적 기관 유형(2.10.0 blind3) — 평가본 공고는 기관 이름 대신 이 유형만 AI 에 보낸다. 위에서부터 처음 맞는 것(대학 → 학교 → 법인 꼴 → 교육청 →
#: 지자체 → 공공기관 → 중앙행정기관 · 그 밖 「기관」). 근사다 — 틀려도 유형 낱말이 조금 어긋날 뿐 이름은 나가지 않는다.
_AGENCY_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("대학", re.compile(r"대학")),
    ("학교", re.compile(r"학교")),
    ("민간 단체", re.compile(r"사단법인|\(사\)|협회|조합|연합회")),
    ("민간 기업", re.compile(r"주식회사|㈜|\(주\)|유한회사")),
    ("공공기관", re.compile(r"교육(?:지원)?청")),
    ("지자체", re.compile(r"광역시|특별시|특별자치|[가-힣](?:시|군|구|도)청$|^[가-힣]{2,3}[시군구]$|[남북]도$")),
    ("공공기관", re.compile(r"재단|공단|진흥원|공사|연구원|개발원|정보원|평가원")),
    ("중앙행정기관", re.compile(r"[가-힣]{2,}(?:부|처|청)$")),  # 「고용노동부」 · 「조달청」(두 글자 「본부」는 아님)
)
#: 법인 꼴 머리 · 꼬리(「주식회사 ○○」 · 「㈜○○」 · 「사단법인 ○○」 · 「○○ 주식회사」) — 그 옆 조각이 이름이다.
_LEGAL_HEAD_RE = re.compile(r"(?:주식회사|㈜|유한회사|사단법인|재단법인)\s*([^\s,·/()]+)")
_LEGAL_TAIL_RE = re.compile(r"([^\s,·/()]+)\s*(?:주식회사|㈜)(?=$|[\s,·/])")
_LEGAL_SHORT = {"(주)": "㈜", "(사)": "사단법인 ", "(재)": "재단법인 "}


def agency_kind(name: Any) -> str:
    """실적 기관 이름 → 유형(대학 · 학교 · 지자체 · 중앙행정기관 · 공공기관 · 민간 기업 · 민간 단체 · 기관)."""
    text = re.sub(r"\([A-Za-z0-9 .&-]*\)", "", str(name or "")).strip()  # 「…진흥원(NIPA)」의 영문 약칭 괄호
    for kind, pattern in _AGENCY_KINDS:
        if any(pattern.search(part) for part in (text, *text.split())):
            return kind
    return "기관"


def agency_names(agency: Any) -> list[str]:
    """원장 기관 칸 → 식별 낱말로 쓸 이름 조각(평가본 AI 입력 가리기 · 식별 낱말 검사 · 2.10.0 blind3 · D7). 법인 꼴 옆 이름은 그대로,
    나머지 조각은 유형을 알 수 있는 것만(「OO대학교 산학협력단」 → 「OO대학교」 · 「관계기관」 · 「… 발급기관」 같은 일반 낱말은 없음).
    괄호 약칭 · 끝의 「등」은 뗀다."""
    text = re.sub(r"\((?:주|사|재)\)", lambda m: _LEGAL_SHORT[m.group(0)], str(agency or ""))
    text = re.sub(r"\s+등$", "", re.sub(r"\([^)]*\)", " ", text).strip())
    names = [m.group(1) for m in _LEGAL_HEAD_RE.finditer(text)]
    rest = _LEGAL_HEAD_RE.sub(" ", text)  # 머리 꼴을 먼저 지운다 — 「출원인 주식회사 ○○」의 「출원인」이 꼬리 꼴 이름이 되지 않게
    names += [m.group(1) for m in _LEGAL_TAIL_RE.finditer(rest)]
    names += [part for part in re.split(r"[\s,·/]+", _LEGAL_TAIL_RE.sub(" ", rest)) if part and agency_kind(part) != "기관"]
    return list(dict.fromkeys(name for name in names if len(name) >= 2))


#: 평가본 공고의 AI 입력에서 지울 인증 · 등록 번호(감싼 괄호째 · 앞 띄어쓰기도) — 렌더러 · 식별 검사와 같은 번호 꼴.
_CERT_STRIP_RE = re.compile(rf"\s*\(\s*{plan_export_service.CERT_NO_RE.pattern}\s*\)|\s*{plan_export_service.CERT_NO_RE.pattern}")


def blind_text(text: str, names: Iterable[str]) -> str:
    """평가본 공고의 실적 글 가리기 — 기관 이름 → 유형(긴 이름 먼저) · 인증 번호 지움. AI 입력과 식별 낱말 검사(`identity_words`)가 함께 쓴다."""
    for name in sorted(set(names), key=len, reverse=True):
        text = text.replace(name, agency_kind(name))
    return _CERT_STRIP_RE.sub("", text).strip()


def llm_payload(pieces: dict[str, Any], *, blind: bool = False) -> dict[str, Any]:
    """**밖(LLM)으로 보내는 회사 본문은 이 함수 하나로만 만든다** (사업계획서 `llm_payload` 와 같은 허용 목록).

    보내는 것: 사업영역 · 인증 이름 · 설립연도 · 활동 지역 · 실적 원장(외부 사용 「가능」 · 증빙 확인 전 제외)의 제목 · 연도 · 분야 ·
    기관(agency — 원장 「주관 · 발주 · 협력기관」 한 칸이라 역할을 모른다 · 2.8.0 B7) · 요약 · 역량(skills) 이름 · 보유(held) 자격 이름 · 사업자등록증 종목 이름.
    보내지 않는 것: 대표자 · 사업자등록번호 · 연락처 · 주소 · 매출 · 인원 · 원장 금액 · 증빙 메모 · 경고 · team_note.
    회사가 손으로 적은 글(원장 제목 · 분야 · 발주 · 요약 · 사업영역 · 활동 지역)은 `plan_draft_service.safe_text` 로 연락처 · 주민등록번호 · 비밀 열쇠 꼴을 가린다(2.7.0).
    blind — 원문이 평가본을 요구하는 공고(2.10.0 blind3): 실적 기관은 이름 대신 유형(`agency_kind`)만, 제목 · 요약 속 그 기관 이름도 유형으로 ·
    인증 · 등록 번호(「제…호」 · `plan_export_service.CERT_NO_RE`)는 감싼 괄호째 지운다(T6 검토).
    """
    profile = pieces.get("profile") or {}
    capacity = pieces.get("capacity") or {}
    safe = plan_draft_service.safe_text

    every_agency = pieces.get("agency_names") or []

    def row(r: dict[str, Any]) -> dict[str, Any]:
        title, summary, agency = safe(r.get("title")), safe(r.get("summary")), safe(r.get("agency"))
        if blind:
            names = {*agency_names(r.get("agency")), *every_agency}
            title, summary = (blind_text(v, names) if isinstance(v, str) else v for v in (title, summary))
            agency = agency_kind(r.get("agency"))
        return {"source_id": r["id"], "title": title, "year": r.get("year"), "field": safe(r.get("field")), "agency": agency, "summary": summary}

    return {
        "business_domains": {"source_id": "profile:domains", "values": [safe(str(d)) for d in profile.get("business_domains") or []]},
        "certifications": [{"source_id": f"profile:cert:{name}", "name": name} for name in plan_draft_service._certifications(profile)],
        # 평가본 공고는 설립연도를 보내지 않는다(D5 설립일 가림 — 「당사는 2021년에 설립」이 평가본 본문에 남았다 · 11-13 독립 검토)
        "founded_year": {"source_id": "profile:founded", "value": None if blind else profile.get("founded_year")},
        "activity_regions": {"source_id": "profile:regions", "values": [safe(str(r)) for r in profile.get("preferred_regions") or []]},
        "performance": [row(r) for r in pieces.get("ledger") or []],
        "skills": [{"source_id": f"skill:{s.get('name')}", "name": s.get("name"), "level": s.get("level")} for s in capacity.get("skills") or []],
        # 이 공고 분야 실적이 조각에 있나(없으면 「교육 운영 경험」으로만 · 2.9.0)
        "topic_match": pieces.get("topic_match", True),
        "credentials": [{"source_id": f"cap:cred:{name}", "name": name} for name in plan_draft_service._credentials(capacity)],
        "business_items": [{"source_id": f"cap:item:{name}", "name": name} for name in plan_draft_service._business_items(capacity)],
    }


def _bundle(unit: dict[str, Any], pieces: dict[str, Any], evaluation: dict[str, Any], terms: dict[str, Any]) -> dict[str, Any]:
    """`plan_draft_service.validate_unit` 이 읽는 근거 묶음 — 회사 조각은 모든 절에 · 평가 기준은 「eval:n」."""
    return {
        "unit": unit, "capability": True, "clauses": [], "task": None, "annex": None, "facts": [], "evidence": [],
        "targets": [{"id": f"eval:{i}", "name": item["name"], "detail": " / ".join(item.get("criteria") or [])}
                    for i, item in enumerate(evaluation.get("items") or [], start=1)],
        "ledger": pieces.get("ledger") or [], "profile": pieces.get("profile") or {}, "capacity": pieces.get("capacity") or {},
        "agreement": terms.get("period"), "agreement_months": terms.get("months"),
        "cutoff": None, "cap_krw": None, "allowed_items": [], "item_reference": None,
    }


SYSTEM_PROMPT = f"""당신은 공공기관 용역 입찰에 내는 **제안서**를 쓰는 제안사(당사) 담당자입니다. 결과는 그대로 제출할 본문입니다.
지킬 것:
- {llm_client.SOURCE_GUARD}
- 제안요청서가 정한 목차를 바꾸지 않습니다. 주어진 대항목의 소항목(items)만 key 를 그대로 돌려 씁니다.
- 소항목마다 작성 방법(guide)이 요구하는 것을 빠짐없이 씁니다. 평가 기준(evaluation)의 세부 평가 항목이 묻는 것을 그 항목을 맡은 소항목에서 구체적으로 보여 줍니다.
  배점(points)이 가장 큰 정성 항목(동점이면 모두)은 그 소항목에서 단계 · 시점 · 담당 역할 · 확인 자료 · 대체안까지 실행계획으로 씁니다.
- **당사가 무엇을 · 어떻게 · 언제 · 몇 번 · 어떤 역할이** 하는지 확정형으로 씁니다(「~하겠습니다」 · 「~합니다」 · 「~운영합니다」).
- 쓰지 않는 말(제안요청서가 「불가능」으로 봅니다): 「할 수 있습니다 · 가능합니다 · 고려하고 있습니다 · 검토하겠습니다 · 노력하겠습니다 · 예정입니다 · 필요 시 · 가급적 · 가능한 한」.
- 「확인 필요」 · 「확인이 필요합니다」 · 「담당자가 확인」 · 「(담당자 확인)」 · 근거가 없다는 설명 · 작성 사정 · 고치는 사람에게 하는 말
  (「증빙이 확인되면 추가합니다」 · 「확약 뒤 기재합니다」)은 본문에 쓰지 않습니다. 확인할 것은 blanks 에만 씁니다.
- 숫자(횟수 · 인원 · 기간 · 목표 · 금액 · 날짜)는 제안요청서 발췌와 회사 근거 조각에 있는 것만 씁니다. 제안요청서의 기준 수치는 그대로 지키겠다고 씁니다. 꼭 필요한데 근거가 없는 숫자는 「(담당자 입력)」으로 두고 blanks 에 올립니다.
- 기대효과 · 성과 지표 · 평가방안의 수치는 공식 요구(제안요청서가 정한 값 · 제안요청서 인용) · 제안 목표(당사 목표 · 근거가 없으면 「(담당자 입력)」) ·
  사후 측정(목표 수치 없이 측정 방법 · 시점만)으로 나눠 씁니다. 회사 실적의 과거 수치(만족도 · 수료율 · 인원)를 이 사업 목표로 옮기지 않고,
  측정 전 결과를 이미 얻은 성과처럼 쓰지 않습니다.
- 회사에 대한 주장(실적 · 인증 · 보유 자격 · 설립 연도 · 사업영역)은 반드시 회사 근거 조각의 source_id 를 답니다(COMPANY_EVIDENCE_GROUNDED). 조각에 없는 실적 · 인력 · 장비 · 협력기관 · 수상은 쓰지 않습니다. 사업영역 · 인증 이름만으로 그 분야를 수행한 경험이 있다고 쓰지 않습니다.
- 회사 사실과 그 사실로 하는 계획은 다른 문장으로 나눕니다. 회사 소개 · 실적은 「특징 · 장점」 · 「일반현황」 · 「수행조직」 같은 역량 소항목에서만 씁니다. 다른 소항목을 회사 소개로 시작하지 않습니다.
- 참여인력 소항목은 역할(PM · 운영인력 등)별 투입 시기 · 참여 방식 · 담당 과업만 쓰고 회사 실적은 쓰지 않습니다. 조직 구성 · 협업 체계 설명은
  수행조직 · 업무분장 소항목에서만 씁니다.
- 「다른 대항목」 목록의 대항목이 맡는 내용은 쓰지 않습니다 — 같은 문장 · 같은 실적 · 같은 기준 수치(횟수 · 건수 · 인원 · 만족도 목표)를
  대항목마다 되풀이하지 않고, 기준 수치는 그 수치를 다루는 소항목 한 곳에서만 씁니다.
  같은 대항목 안에서도 소항목끼리 되풀이하지 않습니다: 개요 · 목적 · 범위는 왜 · 무엇을 요약, 주요사업내용 · 세부과제는 어떻게(실행),
  결과물 제출은 산출물 목록 · 형식 · 시점, 보고 · 검토는 보고 주기 · 절차 — 착수 · 중간 · 최종 보고 설명은 보고 소항목에서만.
- 실적의 기관(agency)은 주관 · 발주 · 협력 중 어느 쪽인지 모릅니다 — 「OO이 발주한」으로 단정하지 않고, 「협력」이 든 기관은 발주처로 쓰지 않습니다.
  실적의 수행 역할 · 대상도 그 행 title · summary 낱말로만 씁니다 — 교육을 컨설팅으로, 운영을 설계 · 총괄로, 대상을 다른 집단으로 넓히지 않습니다
  (분야 field 는 분류 이름일 뿐 근거가 아닙니다).
  실적을 부를 때는 그 행 title 을 줄이거나 바꾸지 않습니다(아래 blind 공고는 예외).
  사업(JSON)에 blind 가 있으면 제안요청서가 회사 식별 정보를 막는 공고입니다 — 실적 기관은 agency 의 유형(대학 · 지자체 · 공공기관 …)으로만 쓰고
  기관 이름 · 회사 이름 · 인증 번호를 짓지 않으며, 실적은 수행 역할 · 역량 중심으로 씁니다. blind 면 사업명(title)을 쓰지 않고
  연도 · 분야 · 대상 · 기관 유형으로 부릅니다.
- 제안요청서가 요구하지 않은 약속은 쓰지 않습니다: 추가 교육 · 과정의 무상 · 당사 부담 개설, 전원 수료 · 수료율 보장, 사업기간 전체 전담 인력,
  외부 시스템 연동 확약, 수당 · 인건비 지급 · 지원. 확보한 것과 확보할 것을 나눠 쓰고, 제안요청서에 없는 비용 금액은 쓰지 않습니다.
- 인력 성명 · 경력 연수 · 학력 · 자격증 번호 · 대표자 · 연락처 · 사업자등록번호 · 주소 · 매출 · 직원 수는 본문에 쓰지 않습니다(표와 칸은 따로 채웁니다). 참여인력은 역할(PM · 운영인력 · 컨설턴트 등) · 투입 방식으로 씁니다.
- 회사 근거 조각의 topic_match 가 false 면 이 공고 분야의 실적이 조각에 없습니다 — 실적은 「교육 운영 경험」으로만 쓰고, 그 분야 전문성을 가진 것처럼 쓰지 않습니다.
- 회사 역량(skills)을 쓰는 계획은 그 source_id 를 달고, 제안요청서가 요구하지 않은 도구 · 시스템 · 챗봇 제작을 약속하지 않습니다(「이 역량으로 …를 만들어」 금지).
- 제안요청서 문장을 그대로 베끼지 않습니다. 요구를 당사의 수행 방법으로 바꿔 쓰되, 사업명 · 과정명 · 프로그램 · 산출물 이름과 과업의 행위 · 대상 ·
  방식 낱말(「컨설팅」 · 「코칭」 · 「실증」 · 「○○ 대상」 · 「대면」)은 제안요청서 그대로 씁니다 — 관점 · 점검 · 정리 · 전달 같은 약한 말로 바꾸거나
  과업을 「과제로 정리해 전달」로 줄이지 않습니다. 의무 문구의 주체(누가) · 수단 · 주기(매월 · 분기) · 범위(전 과정 · 전원)를 줄이거나 빼지 않습니다.
- RFP_GROUNDED 는 제안요청서의 요구 · 기준을 옮겨 말하는 문장에만 쓰고 source 에 인용한 제안요청서 문장을 그대로 둡니다. 당사의 계획 · 방법은 AI_SUGGESTION 입니다.
- 제안요청서의 요구를 옮길 때도 발주기관 말투(「~해야 합니다」 · 「~하여야 함」)로 쓰지 않고 당사가 지키는 꼴(「당사는 ~하겠습니다」)로 씁니다.
- 공동수급 · 하도급 여부, 투입 인원 수, 사무실 · 장비 보유처럼 회사가 정할 사항은 정하지 않습니다 — blanks 에 올립니다.
  사업(JSON)에 joint 가 있으면(공동수급 불허) 단독 수행은 공고 조건이라 수행조직 소항목에 한 번 씁니다(하도급은 여전히 회사가 정합니다).
  작성 방법이 하도급 계획을 요구해 적을 때는 제안요청서의 하도급 조건(발주기관 사전 승인 · 하도급 계획서 제출 · 비율 상한)을 함께
  「사전 승인을 받은 뒤에만 합니다」 꼴로 씁니다 — 하도급을 쓸지는 정하지 않습니다.
- blanks 마다 그 값을 채울 때 필요한 자료(증빙 서류 이름 · 회사자료 칸 이름)를 proof 에 한 줄로 씁니다 — 모르면 빈 글로 둡니다.
- 「보장 · 최고 · 유일 · 100% · 완벽 · 무조건」 같은 표현을 쓰지 않습니다. 회사를 부를 때는 「당사」 하나로 씁니다.
- 입찰 절차 · 계약 조건(청렴계약 · 보증금 · 하자보수 · 제출 방법 · 공동수급 협정 · 협상)은 제안서 본문 내용이 아닙니다 — 소항목이 요구할 때만 씁니다.
- 제안서를 어떻게 썼는지 · 무엇을 넣겠다는 문장(「확정형으로 썼습니다」 · 「대조표를 넣겠습니다」 · 「서식을 그대로 작성해 제출하겠습니다」)은 쓰지 않습니다. 사업을 어떻게 수행하는지만 씁니다.
- 「제안의 특징 및 장점」 · 「추진 전략」 · 「차별성」 소항목은 이 사업에서 당사가 다르게 하는 방법(차별점)을 씁니다. 근거 없는 회사 주장은 여기서도 쓰지 않습니다.
- 본문 · 표 칸에 「원문」이라는 낱말을 쓰지 않습니다 — 「제안요청서」(또는 「공고」 · 「과업지시서」)로 씁니다(「원문」은 자료 경계 표식이 쓰는 말입니다).
- 아직 하지 않은 일(서류 발급 · 첨부 · 협약 · 위촉)을 끝낸 일처럼(「받아 첨부했습니다」 · 「위촉했습니다」) 쓰지 않습니다 — 제출 때 붙일 서류는
  「붙임으로 제출합니다」로 씁니다.
- 위촉 · 외부 · 확정 전 인력의 경력 · 이력은 단정하지 않고 선정 기준(「…경력을 갖춘 전문가를 위촉 기준으로」)으로 씁니다.
- 작성 방법이 예시 · (안) · 계획안을 제시하라고 하면 본문에 그 예시 · 안을 직접 쓰고 「(안)」을 붙입니다 — 「협의 후 확정」으로 미루지 않으며,
  숫자는 근거 있는 것만 씁니다.
- 소항목 제목이 「A 및 B」 · 「A · B」면 A 와 B 를 각각 다룹니다.
쓰는 틀:
- 소항목마다 짧은 소제목(「○ …」)과 개조식 줄(「- …」)을 섞어 평가위원이 훑어보기 쉽게 씁니다. 한 문장에 한 뜻 · 120자 이내.
- 과업 소항목(세부과제별 추진방안 · 주요사업내용 등)은 제안요청 사항의 과업 번호 · 이름 순서대로 하나도 빠짐없이 다룹니다 — 과업마다 「○ 과업 이름」 소제목 아래
  이름표 줄을 씁니다: 「- 목표:」 「- 방법:」 「- 담당:」(역할 이름 · 「주 담당 / 지원」) 「- 일정:」(개월차 · weeks 가 있으면 주차) 「- 규모:」(횟수 · 인원 · 자원) 「- 산출물 · 검수:」 「- 위험 → 대응:」.
  제안요청서 · 회사 근거에 없는 값은 그 줄에 짓지 않습니다(회사가 정할 값은 blanks). 공고에 없는 의무 · 과업은 더하지 않습니다.
- 역할 이름은 문서 전체에서 한 벌입니다 — 수행조직 · 업무분장 소항목의 역할 이름을 과업 「- 담당:」 줄 · 일정표 owner · milestones owner 에
  글자 그대로 같은 순서(주 / 지원)로 쓰고 줄여 쓰지 않습니다(「컨설턴트」와 「○○ 컨설턴트」를 섞지 않음).
- 수행조직 · 업무분장 소항목은 역할마다 「- 역할 이름: 담당 업무를 맡습니다」 한 줄로 씁니다 — 참여인력 표의 구분 · 담당 업무 칸이 이 줄에서
  옮겨집니다(성명 · 학력 · 경력 · 자격 · 참여율은 쓰지 않습니다).
- 과업에 외부 전문가 · 강사 초빙이나 기관 · 기업 매칭이 있으면 그 과업에 섭외 단계(후보 발굴 → 사전 접촉 → 확정 → 대체 후보 전환)와
  단계마다 시점(일정표 period 와 같은 꼴) · 확인 자료(위촉 동의 · 일정 확정 서면)를 씁니다. 확약 근거가 없는 대상은 「후보」로 쓰고 이름을 짓지 않습니다.
- 과업에 실증 · PoC · 파일럿 · 시범 운영이 있으면 대상마다 착수 전에 정할 운영안(검증 과제 · 성공 판정 기준 · 수집 증빙 · 판정 결과별 다음 조치)을
  씁니다. 판정 수치는 근거가 없으면 예시로도 짓지 않고 「착수 전 대상 기관 · 기업과 합의」로 쓰며, 결과는 「예상 결과」와 「증빙으로 확인한 성과」를
  나눠 보고한다고 씁니다.
- 소항목 tables 에 scope 가 있으면 scope(과업별 대응)에 제안요청 과업마다 한 줄씩 씁니다: task 는 제안요청서 과업 번호 · 이름 그대로, detail 은 당사 대응
  한 줄, output 은 제안요청서 산출물 이름(없으면 빈 글) — 과업을 합치지 않고, 제안요청서에 과업 목록이 없으면 빈 목록.
- 제안요청 과업이나 작성 방법에 예산 계획 · 편성 · 집행이 있으면 그 과업의 「- 방법:」에 과업마다 드는 비목(강의 · 컨설팅 · 실증 · 운영 · 정산 등)을
  과업 이름과 짝지어 쓰고, 산출은 「수량 × 단가」 꼴로만 씁니다 — 단가 · 수량 · 금액 숫자는 쓰지 않고(사업금액은 제안요청서 글 그대로) 금액 표도
  만들지 않습니다(예산 배분안 표는 담당자가 채웁니다). 참여 수가 바뀌면 단가 · 횟수를 조정해 사업금액 안에서 유지한다고 씁니다.
- 평가 기준에 위험 요인 · 대응이 있으면 위험 → 대응 방안을 짝으로 씁니다.
- 소항목마다 주어진 목표 분량(target_chars)에 맞춥니다(±20%). 짧다고 지어내지 않습니다.
- 추진 일정 소항목에 일정표(schedule)가 딸리면 세부 추진 일정표입니다: 제안요청서 「추진 일정」 표의 행(과정 · 과업 · 착수 · 중간 · 최종 보고)과
  제안요청 과업마다 한 줄씩 쓰고 여러 행을 한 줄로 합치지 않습니다(소항목 JSON 의 schedule_reports 보고 줄은 꼭 둡니다).
  period(추진 기간)는 「n개월차」 · 「n~m개월차」(구간이 여럿이면 「 / 」로 · 사업(JSON)에 weeks 가 있으면 아래 주차)만 씁니다 — 날짜 · 「계약체결일~」 · 「2027년 n월」 같은 사건 · 달력 꼴은 쓰지 않습니다
  (개월차는 계약 · 착수부터 센 상대 기간이라 사업 시작일을 몰라도 늘 채웁니다 — 시작 날짜를 지어내지 않되, 기간 칸을 날짜 · 「(담당자 입력)」 · 빈 글로
  두지 않습니다 · months 가 있으면 그 안에서). 제안요청서가 정한 달 · 날짜 기한(「4월까지」 · 「(8월)」 · 「계약 후 10일 이내」)은
  detail 이나 output 칸에 제안요청서 글 그대로 둡니다. owner(담당)는 역할 이름(PM · 운영 담당 · 강사 · 컨설턴트)만 — 사람 이름은 쓰지 않습니다.
  담당이 둘 이상이면 「주 담당 / 지원」 꼴로 씁니다(주 담당은 하나 · 위 역할 이름 한 벌).
  detail(주요 활동)은 그 과업에서 하는 일, output(산출물)은 제안요청서 산출물 이름 그대로(없으면 빈 글).
- 사업(JSON)에 weeks 가 있으면 계약 예정일(contract_from)부터 끝날까지 weeks 주인 짧은 사업입니다: 일정표 period 와 과업 「- 일정:」 줄은
  착수일(D) 기준 주차 「Wn」 · 「Wn~Wm」(W1 ~ W[weeks])으로 쓰고 개월차 · 「n주차」 · 달 이름은 쓰지 않습니다. 제안요청서가 날짜로 정한 마감(결과보고 제출 · 정산)은
  제안요청서 날짜 그대로 detail · output 칸에 둡니다. 제안요청서 추진 일정(안)의 달이 계약 예정일보다 앞서면 그 달을 운영 기간으로 쓰지 않습니다.
- 제안요청서가 결과보고 제출일을 날짜로 정했으면 보고서 초안 검토와 정산을 그 날짜 앞의 마감으로 두고, 날짜로 고정한 마감은 마지막 주차(Wn) 안에만 둡니다.
  보고 · 점검 시점은 일정표 · 핵심 마감 표 · 본문에서 같은 값으로 씁니다(공고에 없는 보고를 새 의무로 만들지 않습니다).
- 일정표가 딸리면 milestones(핵심 마감과 책임)에 제안요청 과업 · 보고의 핵심 마감마다 한 줄씩 씁니다: item(항목) · owner(책임 역할 — 역할 이름만 ·
  「주 담당 / 지원」) · due(마감 기준 — 일정표 period 와 같은 꼴이거나 제안요청서 날짜) · proof(확인 자료 — 산출물 · 서면 이름). 일정표가 없으면 빈 목록.
- 추진 일정 소항목에는 「○ 선후관계」 소제목 아래 「- 병행: 과업 A와 과업 B를 같은 기간에 시작합니다」 · 「- 연결: 과업 A의 산출물(이름)이 나오면 과업 B를
  시작합니다」를 씁니다. 앞 과업 산출물(진단 결과 · 로드맵)을 쓰는 과업을 그 산출물이 나오는 기간보다 앞에 두지 않고, 같은 과업의 기간은 일정표 · 본문 ·
  다른 표에서 같은 값으로 씁니다(본문에서 앞당긴 시점도 일정표 그 과업 기간 안에).
- 일정 지연 · 위험 대응은 「상황 → 판단 시점(개월차 · 주차) · 병행 · 조정 · 발주기관 협의」로 쓰고 기본 계획에 이미 있는 방법을 되풀이하지 않습니다.
  제안요청서가 대면 · 집합 · 현장으로 정한 활동을 온라인 · 화상 · 원격으로 바꾸는 것은 「발주기관과 협의해 정하는 대안」으로만 쓰고(「대면(화상)」처럼
  괄호로 바꿔 쓰지 않습니다) 기본 계획이나 확정 조치로 쓰지 않습니다. 압축안은 기본안과 다른 조치와 날짜 마감으로 씁니다.
- eval_items 에는 평가 기준(evaluation) 목록을 하나씩 훑어, 그 소항목이 다룬 세부 평가 항목 이름(name)을 빠짐없이 그대로 적습니다.
  한 소항목이 여러 항목을 다루면 모두 적습니다(조견표 「제안서 해당 목차」가 이 값으로 만들어집니다)."""


class MilestoneRowOut(BaseModel):
    """핵심 마감과 책임(2.10.0 D2) — 항목 · 책임 역할(역할 이름만 · 「주 담당 / 지원」) · 마감 기준(일정표 기간 꼴 · 원문 날짜) · 확인 자료."""

    item: str
    owner: str = ""
    due: str = ""
    proof: str = ""


class ScopeRowOut(BaseModel):
    """과업별 대응(2.10.0 T3) — 과업(원문 번호 · 이름 그대로) · 제안 대응(당사 대응 한 줄) · 주요 산출물(원문 이름 · 없으면 빈 글)."""

    task: str
    detail: str = ""
    output: str = ""


class BidUnitOut(BaseModel):
    key: str
    sentences: list[PlanSentenceOut] = Field(default_factory=list)
    schedule: list[ScheduleRowOut] = Field(default_factory=list)
    milestones: list[MilestoneRowOut] = Field(default_factory=list)
    scope: list[ScopeRowOut] = Field(default_factory=list)
    blanks: list[PlanBlankOut] = Field(default_factory=list)
    eval_items: list[str] = Field(default_factory=list)


class BidMajorOut(BaseModel):
    units: list[BidUnitOut] = Field(default_factory=list)


class EvalPairOut(BaseModel):
    name: str
    keys: list[str] = Field(default_factory=list)


class EvalRetryOut(BaseModel):
    """조견표 다시 묻기(3차 지시서 §3) — 평가 항목마다 그 내용을 실제로 다룬 소항목 key(없으면 빈 목록)."""

    pairs: list[EvalPairOut] = Field(default_factory=list)


EVAL_RETRY_PURPOSE = "bid_plan:조견표 짝"
EVAL_RETRY_SYSTEM = f"""당신은 입찰 제안서의 「기술능력 평가항목별 조견표」를 맞추는 검토자입니다.
- {llm_client.SOURCE_GUARD}
- 평가 항목마다, 그 평가 기준이 묻는 내용을 **실제로 다룬** 소항목의 key 를 고릅니다(여러 곳이면 모두 · 가장 직접 다룬 곳을 앞에).
- 낱말이 같다고 고르지 않습니다. 소제목 · 첫 줄이 그 평가 기준의 내용을 다루는지 보고 고릅니다.
- 다룬 소항목이 없으면 keys 를 빈 목록으로 둡니다. 소항목 목록에 없는 key 는 쓰지 않습니다."""


def eval_retry_prompt(missing: list[dict[str, Any]], form: dict[str, Any], sections: list[dict[str, Any]]) -> str:
    """조견표 다시 묻기 본문 — 빈 정성 평가 항목(이름 · 기준) · 본문이 남은 소항목(key · 번호 · 제목 · 「○」 소제목 · 첫 줄). 원문 · 초안 글은 경계 표식 안에."""
    items = [{"name": item["name"], "area": item.get("area"), "criteria": item.get("criteria")} for item in missing]
    lines: list[str] = []
    for entry in sections:
        if entry.get("by") != "llm" or not entry.get("sentences"):
            continue
        texts = [str(s.get("text") or "") for s in entry["sentences"]]
        heads = [t for t in texts if plan_export_service._subheading(t)][:8]
        body = [t for t in texts if not plan_export_service._subheading(t)][:2]
        lines.append(f"[{entry['key']}] {unit_number(form, entry['key'])} {entry.get('section')}\n"
                     + "\n".join(f"  {t[:120]}" for t in [*heads, *body]))
    return "\n".join([
        "평가 항목(JSON — 조견표 「제안서 해당 목차」가 비어 있는 항목):\n" + llm_client.fenced("평가 항목", json.dumps(items, ensure_ascii=False)),
        "소항목(key · 번호 · 제목 · 소제목 · 첫 줄):\n" + llm_client.fenced("소항목", "\n".join(lines)),
        "pairs 에 평가 항목 이름(name)을 그대로 적고, keys 에는 위 대괄호 안 key 만 적습니다.",
    ])


def major_lines(form: dict[str, Any]) -> dict[str, str]:
    """대항목마다 한 줄 「제목: 소항목 · 소항목」(소항목 없는 대항목은 작성 방법) — 다른 대항목 호출에 「그 대항목이 맡는 내용」으로 보낸다(11-06 심사 ④)."""
    lines: dict[str, str] = {}
    for section in form.get("sections") or []:
        items = section.get("items") or []
        whole = len(items) == 1 and items[0]["key"] == section["key"]
        what = re.sub(r"\s+", " ", items[0].get("guide") or "") if whole else " · ".join(i.get("plain") or i["title"] for i in items)
        lines[section["key"]] = f"- {section['title']}: {what[:150]}"
    return lines


def major_prompt(major: dict[str, Any], units: list[dict[str, Any]], *, source: dict[str, Any], company: dict[str, Any],
                 others: list[str] | None = None) -> str:
    """대항목 한 번의 본문 — 소항목 · 다른 대항목 · 사업 · 평가 기준 · 작성 지침 · 회사 근거 조각 · 제안요청서 발췌."""
    # 소항목 제목 · 작성 방법은 제안요청서 원문이라 경계 표식 안에 — JSON 줄에는 key · 분량 · 표만(2.7.0 검토)
    items = [{"key": u["key"], "target_chars": u.get("target_chars") or TARGET_CHARS[u["target"]],
              "tables": (["schedule"] if "schedule" in u["tables"] else []) + (["scope"] if u.get("scope") else [])} for u in units]
    for item in items:
        if "schedule" in item["tables"]:  # 세부 추진 일정표만 — 개월차 상한 · 원문이 요구한 보고 줄(3차 지시서 §4 · 과업별 대응 소항목 아님)
            item["months"] = source["terms"].get("months")
            item["schedule_reports"] = schedule_expect(source.get("excerpt") or "")
    guides = "\n\n".join(f"[{u['key']}] {u['title']}\n작성 방법(guide): {u['guide'] or '없음'}" for u in units)
    # kind(정량 · 정성 — 원문에서 읽은 값)는 「배점이 가장 큰 정성 항목」을 가를 근거(T3 · m3)
    evaluation = [{"source_id": f"eval:{i}", "area": item.get("area"), "name": item["name"], "criteria": item.get("criteria"),
                   "points": item.get("points"), "kind": item.get("kind")}
                  for i, item in enumerate(source["evaluation"].get("items") or [], start=1)]
    lines = [
        f"대항목 「{major['title']}」의 소항목을 씁니다. items 의 key 를 그대로 돌려 주세요.",
        "소항목(JSON): " + json.dumps(items, ensure_ascii=False),
        "소항목 제목 · 작성 방법(제안요청서 — [key] 마다):\n" + llm_client.fenced("소항목 작성 방법", guides),
    ]
    if others:
        # 원문 작성 방법 글이 든 줄이라 경계 표식 안에(2.7.0 검토)
        lines.append("다른 대항목(그 대항목이 맡는 내용은 여기서 쓰지 않습니다):\n" + llm_client.fenced("다른 대항목", "\n".join(others)))
    lines += [
        "사업(JSON): " + json.dumps({"title": source["title"], "agency": source["agency"], "period": source["terms"].get("period"),
                                     "budget": source["terms"].get("budget"),
                                     # 짧은 사업만 — 계약 예정일 · 주차 수(지시문 「weeks 가 있으면 주차」 · 2.10.0 D1)
                                     **({"contract_from": source["terms"].get("contract_from"), "weeks": source["terms"]["weeks"]}
                                        if source["terms"].get("weeks") else {}),
                                     # 나라장터 공동수급 칸 「불허」만(단독 수행은 공고 조건 · 2.10.0 m0)
                                     **({"joint": "공동수급 불허"} if source.get("joint_solo") else {}),
                                     # 원문이 평가본(회사 식별 금지)을 요구할 때만(2.10.0 blind3)
                                     **({"blind": "회사 식별 정보 금지"} if source.get("blind") else {})}, ensure_ascii=False),
    ]
    # 원문 덩어리는 경계 표식 안에 — 그 안의 지시는 따르지 않는다(2.7.0 · `llm_client.SOURCE_GUARD`)
    if evaluation:
        lines.append("평가 기준(JSON — 평가위원이 채점하는 것):\n" + llm_client.fenced("평가 기준", json.dumps(evaluation, ensure_ascii=False)))
    elif source["evaluation"].get("text"):
        lines.append("평가 기준(제안요청서):\n" + llm_client.fenced("평가 기준", source["evaluation"]["text"]))
    if source.get("rules"):
        lines.append("제안서 작성 지침(제안요청서):\n" + llm_client.fenced("작성 지침", source["rules"]))
    if source.get("facts") or source.get("derived"):
        # 원문 정량값(3차 지시서 §5) — 본문에 그 수치를 쓸 때는 이 값 · 한정어 그대로(원문 표현이 모호하면 고쳐 쓰지 않는다)
        numbers = {"facts": [{k: f[k] for k in ("label", "value", "unit", "bound")} for f in source.get("facts") or []],
                   "percent_lines": [d["quote"] for d in source.get("derived") or []]}
        lines.append("제안요청서 기준 수치(JSON — 제안요청서에서 읽은 값 · 그 수치를 쓸 때는 값과 「이상 · 이하」를 그대로 · percent_lines 는 제안요청서 문장이니"
                     " 그 수치를 쓸 때 제안요청서 표현 그대로 쓰고 계산값으로 바꾸지 않습니다):\n"
                     + llm_client.fenced("기준 수치", json.dumps(numbers, ensure_ascii=False)))
    # 회사 조각에도 회사가 손으로 적은 글(원장 요약 …)이 있다 — 같은 경계 표식 안에(2.7.0)
    lines.append("회사 근거 조각(JSON) — 회사 주장은 이 source_id 로만 뒷받침합니다:\n"
                 + llm_client.fenced("회사 근거 조각", json.dumps(company, ensure_ascii=False)))
    lines.append("제안요청서 발췌(사업 개요 · 제안요청 사항 · 기타 안내):\n" + llm_client.fenced("제안요청서 발췌", source["excerpt"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 입찰 거르기 — 「확인 필요」는 본문에서 빼고, 모호한 표현은 검토용 경고
# ---------------------------------------------------------------------------

#: 본문에 남기지 않는 확인 · 작성 사정 문장(대표 11-03 「확인 필요 모두 쓰지 마」).
#: 「확인 필요」는 뒤에 무엇이 오든(괄호 · 대괄호 · 쌍점 · 빈칸 · 문장 끝) 잡고, 「확인이 필요한 수료생」 같은 꾸밈꼴만 남긴다.
#: 「확인되지 않은 수료생」 · 「담당자가 확인한 공고」 · 「근거가 없는 신고」 같은 계획 문장도 남긴다(11-03 검토).
_HEDGE_RE = re.compile(
    r"확인\s*(?:이\s*)?필요(?:합니다|하다|함|[^가-힣]|$)"
    r"|확인\s*(?:바랍|요망)|확인하시기|(?:협의|검토)\s*(?:가\s*)?필요(?:합니다|함|[^가-힣]|$)"
    r"|추후\s*(?:확인|확정|결정)(?:합니다|하겠|할\s*예정|[^가-힣]|$)"
    r"|담당자(?:가|께서)?\s*(?:확인|입력|기재|작성)\s*(?:해\s*주|하여\s*주|하시|바랍|필요)"
    r"|확인되지\s*않(?:았습니다|습니다|았다|는다)"
    r"|근거(?:\s*자료)?가\s*(?:없습니다|없어\s|부족합니다|연결되지)"
    r"|[(\[]\s*미정\s*[)\]]|미정(?:입니다|이다)|\bTBD\b"
    # 고치는 사람에게 하는 말(작성자 메모 · 2.10.0 T3 — 손 수정본 「증빙이 확인되는 경우에만 추가합니다」가 「경험이 없다」로 읽혔다) ·
    # 조건과 쓰기 동사가 바로 붙은 꼴만(「확인한 뒤 결과보고서에 기재합니다」는 계획 문장)
    r"|경우에(?:만|\s*한해)\s*(?:추가|기재|표기)(?:합니다|하겠|함)|확인되면\s*(?:추가|기재|표기)(?:합니다|하겠|함)"
    r"|(?:확약|확정|증빙)[^.]{0,12}(?:뒤|후)에?\s*(?:추가|기재|표기)(?:합니다|하겠|함)"
)
#: 「(담당자 확인)」만 남은 문장(`HUMAN_INPUT_RE` 의 확인 꼴) — 값을 정할 문장이 아니라 담당자 확인 목록으로(2.10.0 T3).
_CHECK_MARK_RE = re.compile(r"[(\[（]\s*담당자\s*확인\s*[)\]）]")
#: 제안요청서가 「불가능」으로 보는 모호한 표현 — 검토용 경고(문장은 남긴다).
_VAGUE_RE = re.compile(
    r"(?:할|될|받을|드릴|볼|줄)\s*수\s*있(?:습니다|다|음)(?=[.\s]*$)|가능(?:합니다|하다|함)(?=[.\s]*$)"
    r"|고려(?:하고\s*있|하겠|할\s*예정|중)|검토(?:하겠|할\s*예정|중입니다)|노력하겠|예정입니다|필요\s*시|필요한\s*경우|가급적|가능한\s*한"
)
FLAG_VAGUE = "제안요청서가 「불가능」으로 보는 모호한 표현"
FLAG_NUMBER = "제안요청서 · 회사 자료에 없는 숫자"
FLAG_RFP_VOICE = "제안요청서 말투(「~해야 합니다」) — 「당사는 ~하겠습니다」로 고치세요"
_RFP_VOICE_RE = re.compile(r"야\s*(?:합니다|함|한다)\s*[.]?\s*$")  # 「해야 · 시켜야 · 지켜야 합니다」
#: 회사가 정할 사항을 AI 가 정한 문장 — 제출용에 남기지 않는다(11-03 실측: 공동수급 허용 공고에 「단독 · 하도급 없이」).
#: 「참여인력은 당사 소속 직원으로 구성」 · 「하도급으로 간주하는 기준을 지켜」도 하도급 없음을 정하는 말이다(11-06 심사 — 빈칸 목록은 회사 결정으로 두고 본문은 단정했다).
_DECISION_RE = re.compile(r"단독으로\s*수행|공동수급(?:과|이나|·|\s)*(?:하도급\s*)?(?:없이|을\s*하지\s*않|은\s*하지\s*않)|하도급\s*(?:없이|을\s*하지\s*않|은\s*하지\s*않)"
                          r"|하도급으로\s*간주|소속\s*(?:임)?직원(?:으로|만으로)\s*(?:구성|투입|수행)")
#: 회사 근거 없이 쓴 회사 주장 — 제출용에 남기지 않는다(검증이 「AI 제안」으로 낮춘 회사 문장 · 근거 없는 「당사가 보유 · 수행한」).
_UNSUPPORTED_COMPANY_FLAGS = (plan_draft_service.FLAG_NO_COMPANY_SOURCE, plan_draft_service.FLAG_COMPANY_UNSUPPORTED,
                              plan_draft_service.FLAG_SELF_CLAIM)
#: 회사 주장 꼴(주어가 「당사」 · 회사 이름일 때) — 지난 실적 · 보유 · 인증 · 경험(11-03 검토: 공문체 「수행하였습니다」 ·
#: 「인증을 받은」 · 「확보하고 있습니다」 · 「운영한 경험으로」가 빠져나갔다). 「보유한」은 역량 · 인력 · 실적 같은 대상이 붙을 때만
#: (「당사가 보유한 개인정보는 파기」는 계획 문장).
_CLAIM_RE = re.compile(
    r"(?:수행|운영|진행|개발|구축|교육|협력|지원|컨설팅|양성|배출|확보)(?:했|하였)(?:습니다|으며|고|다|던)"  # 「확보했습니다」(2.7.0 · 계획 5)
    r"|(?:수행|운영|진행|교육|개발|구축)한\s*(?:경험|실적|노하우)"
    r"|(?:해|하여)\s*(?:온\s+(?![·ㆍ•/]\s*오프)|왔)"  # 「운영해 온 」 · 「적용해 왔습니다」(11-06 심사) · 「활용해 온 · 오프라인」은 아님(4차 검토)
    r"|(?:경험|실적|노하우|전문성)(?:을|를|이)?\s*(?:바탕|보유|갖추|갖고|가지고|쌓|살려)"
    r"|(?:인증|자격|지정)(?:을|를)?\s*(?:받은|받았|획득|보유)"
    r"|(?:보유|확보|갖추)(?:하고|고)\s*있(?:습니다|으며|다)"
    r"|보유한\s*[^.,]{0,15}?(?:역량|기술|노하우|네트워크|인력|인프라|실적|경험|전문\S*|DB|데이터베이스|플랫폼|솔루션|강사|컨설턴트|협약)"
    r"|경험이\s*있"
)
#: 주어가 없어도 회사 주장인 꼴 — 「경험이 풍부한 전문 강사진」 · 「다년간의 노하우」 · 아직 붙이지 않은 서류를 끝낸 일처럼 쓴 「받아 첨부했습니다」(2.11.0).
_CLAIM_ANYWHERE_RE = re.compile(r"경험이\s*풍부|풍부한\s*(?:경험|노하우)|다년간의?\s*(?:경험|노하우)|오랜\s*(?:경험|노하우)"
                                r"|(?:발급\s*)?받아\s*첨부(?:했|하였)|첨부(?:했|하였)습니다")
#: 지난 경험 꼴 — 역량 이름 · 사업영역 · 인증 이름만 근거로는 쓸 수 없다(11-06 심사 — 「RAG와 챗봇 기술을 개발에 적용해 왔습니다」(근거 skill: 뿐)).
#: 「온」 뒤 빈칸 — 「활용해 온라인」 · 「활용해 온 · 오프라인」은 지난 경험이 아니다(4차 #5 · `_CLAIM_RE` 와 같은 꼴).
_PAST_RE = re.compile(r"(?:했|하였)(?:습니다|으며|고|다|던)|(?:해|하여)\s*(?:왔|온\s+(?![·ㆍ•/]\s*오프))")
_WEAK_SOURCES = ("skill:", "profile:domains", "profile:cert:")
#: 지금 갖고 있다는 꼴 — 근거가 회사가 스스로 적은 역량(skill:)뿐이면 약한 근거다(2.7.0 · 계획 5 · 11-07 5건 「RAG · 챗봇 역량을 보유하고 있습니다」).
_HOLD_NOW_RE = re.compile(r"(?:보유|갖추|확보)(?:하고|고)\s*있")
#: 과장 표현(2.7.0 · 계획 5 · 11-07 1782790 「40%를 반드시 달성하겠습니다」) — 제출용 본문에 남기지 않고 빈칸 목록 「과장 표현」으로 옮긴다.
#: 금칙어 목록(`plan_validation.BANNED_RE`)보다 좁다 — 「정보주체의 권리 보장」 · 「100% 온라인」 · 「최고정보보호책임자」는 약속이 아니다.
HYPE_RE = re.compile(r"반드시\s*달성|완벽|100\s*%\s*(?:를|을)?\s*(?:달성|보장|만족|이행|준수|성공|확보)"
                     r"|보장(?:합니다|하겠|해\s*드리|하여\s*드리|드립니다|됩니다)")
HYPE_FIELD = "과장 표현"


def hype_words(sentence: dict[str, Any]) -> list[str]:
    """제출용 본문에 남기면 안 되는 과장 표현. 제안요청서 문장을 그대로 옮긴 RFP_GROUNDED(인용 원문에 같은 말이 있음)는 건드리지 않는다."""
    text = str(sentence.get("text") or "")
    found = list(dict.fromkeys(re.sub(r"\s+", " ", m.group(0)) for m in HYPE_RE.finditer(text)))
    if found and sentence.get("type") == NOTICE:
        quoted = re.sub(r"\s+", "", str(sentence.get("source") or ""))
        if all(re.sub(r"\s+", "", word) in quoted for word in found):
            return []
    return found
#: 인증 근거로 인증 취득 자체를 말하는 동사(「인증을 취득했습니다」) — 지난 경험 꼴에서 뺀다(4차 #5).
_CERT_PAST_RE = re.compile(r"(?:취득|획득|인증|지정|선정)\s*(?:했|하였|되었|됐)|받았")
#: 제안서 본문이 아닌 우리 제출 절차(편철 · 원본 대조 · 목록표 …) — 붙임 · 기타(제출 서류 목록) 소항목에서만, 제출 서류 낱말과 함께일 때 뺀다
#: (과업 · 결과물 · 보안 절의 「제본·편철해 납품」 · 「증빙서류 열람 권한」은 남긴다 · 11-06 심사 ② · 4차 #4).
_SUBMIT_STEP_RE = re.compile(r"편철|원본과\s*대조|제출일\s*기준|유효\s*기간을\s*점검|암호를\s*걸어|목록표를\s*둡니다|아래\s*순서로|열람\s*권한"
                             r"|(?:가린|가리고|가려)\s*(?:뒤\s*|후\s*)?제출")
_SUBMIT_CTX_RE = re.compile(r"붙임|제출\s*서류|서식|증명서|편철|제안\s*담당자|(?:인력|자격|경력|실적)\s*증빙")
DROP_SUBMIT = "제출 절차 문장(편철 · 원본 대조 · 목록표 …) — 제안서 본문이 아님"
#: 제출 서류를 다루는 소항목 — 제목(대항목 포함)이 첨부 · 증빙자료 · 제출 서류이거나 작성 방법이 「첨부문서 · 제본하여 제출」(4차 검토 —
#: 「Ⅵ. 첨부자료」 · 「5. 증빙자료」 · 「기타 지원사항 등」을 AI 가 쓰면 제출 절차 문장이 본문에 남았다).
_SUBMIT_UNIT_RE = re.compile(r"첨부|별첨|붙임|증빙\s*자료|제출\s*서류")
_SUBMIT_GUIDE_RE = re.compile(r"첨부\s*문서|제본하여\s*제출")


def submit_unit(unit: dict[str, Any]) -> bool:
    """제출 절차 그물(`bid_filter(annex=)`)을 켤 소항목인가. 「기타」는 작성 방법에 과업 낱말이 없을 때만(사업관리 · 추가 제안을 모은 「기타」는 본문)."""
    guide = str(unit.get("guide") or "")
    if unit.get("annex") or _SUBMIT_UNIT_RE.search(f"{unit['plain']} {unit.get('major_title') or ''}") or _SUBMIT_GUIDE_RE.search(guide):
        return True
    return bool(re.fullmatch(r"기타(?:\s*사항)?", unit["plain"])) and not _ANNEX_TASK_RE.search(guide)
DROP_DOMAINS = "사업영역만 근거인 문장 — 일반현황에 이미 있음"
#: 다른 기관이 주어인 마디(「발주기관이 보유한 협약기업」 · 「교육사가 운영해 온 프로그램」)는 회사 주장이 아니다.
_OTHER_SUBJECT_RE = re.compile(
    r"(?:발주기관|기관|진흥원|KISA|교육사|교육수행사|수행사|협약기업|참여기업|기업|정부|부처|학교|대학|센터|수료생|교육생)(?:이|가|에서)\s")
_SUBJECTS = ("당사", "우리 회사", "본사")
#: 회사 근거 문장의 마디 나누기 · 낱말 거르기(근거 원문과 대조).
_CLAUSE_SPLIT_RE = re.compile(r"[,，;](?![^()（）]*[)）])|(?<=며)\s")
_PARTICLE_RE = re.compile(r"(?:으로|에서|에게|까지|부터|과|와|을|를|이|가|은|는|의|에|로|도|만)$")
_VERB_HINT_RE = re.compile(r"했|하였|합니다|하며|하고|있습니다|있으며|됩니다|입니다|이며|으며|겠|한다|된다|받았")  # 「인증을 받았습니다」(4차 #5)
_CLAIM_STOP = {"당사", "본사", "우리", "회사", "보유", "확보", "운영", "수행", "경험", "역량", "바탕", "통해", "대상", "발주", "발주한", "관련", "분야"}


def _company_names(profile: dict[str, Any]) -> tuple[str, ...]:
    """회사를 부르는 이름 — 「당사」 · 「우리 회사」 · 회사 이름(「주식회사 샘플에듀」 → 「샘플에듀」)."""
    name = str(profile.get("name") or "").strip()
    short = re.sub(r"^(?:주식회사|\(주\)|㈜)\s*|\s*(?:주식회사|\(주\)|㈜)$", "", name).strip()
    return tuple(dict.fromkeys(n for n in (*_SUBJECTS, name, short) if len(n) >= 2))


#: 투입할 인력의 자격을 약속하는 문장(「… 경험을 다수 보유한 인력을 컨설턴트로 배치하겠습니다」) — 제안요청서가 요구하는 인력 요건을
#: 지키겠다는 약속이지 회사 실적이 아니다(11-03 실측 · 평가항목 「수행능력 및 전문성」). 그 꾸밈말만 빼고 회사 주장을 본다.
_STAFFING_COMMIT_RE = re.compile(r"(?:배치|투입|선발|채용|섭외|구성|배정)하겠습니다\s*[.]?\s*$")
_STAFF_QUALIFIER_RE = re.compile(
    r"(?:경험|노하우|자격|역량)(?:을|를|이)?\s*(?:다수\s*)?(?:보유한|갖춘|풍부한)\s*(?:인력|강사진|강사|컨설턴트|전문가|멘토|PM)"
    r"|(?:경험이\s*풍부한|풍부한\s*(?:경험|노하우)을\s*갖춘)\s*(?:\S+\s*)?(?:인력|강사진|강사|컨설턴트|전문가|멘토|PM)")


def is_company_claim(text: str, names: tuple[str, ...] = _SUBJECTS) -> bool:
    """근거 없이 쓰면 안 되는 회사 주장인가 — 회사가 주어인 지난 실적 · 보유 · 인증 · 경험(다른 기관이 주어인 마디는 뺀다)."""
    if _STAFFING_COMMIT_RE.search(text):
        text = _STAFF_QUALIFIER_RE.sub("", text)
    if _CLAIM_ANYWHERE_RE.search(text):
        return True
    alternation = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    for subject in re.finditer(rf"(?:{alternation})(?:는|은|가|이|의)?", text):
        rest = text[subject.end():]
        claim = _CLAIM_RE.search(rest)
        if claim and not _OTHER_SUBJECT_RE.search(rest[:claim.start()]):
            return True
    return False


def _content_words(clause: str) -> list[str]:
    words = []
    for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", clause):
        if _VERB_HINT_RE.search(token):
            continue
        token = _PARTICLE_RE.sub("", token)
        if len(token) >= 2 and token not in _CLAIM_STOP:
            words.append(token)
    return words


def unsupported_company_clause(text: str, cited: str) -> str | None:
    """회사 근거를 단 문장에서 근거 원문에 없는 보유 · 실적 주장 마디(11-03 검토: 「OO대 교육을 수행했으며, 채용기업 네트워크와
    보안 전문 강사진을 보유」 — 근거 한 줄로 지어낸 「보유」가 통과했다). 마디 낱말의 절반 넘게 근거에 없으면 그 마디."""
    for clause in _CLAUSE_SPLIT_RE.split(text):
        if not (_CLAIM_RE.search(clause) or _CLAIM_ANYWHERE_RE.search(clause)):
            continue
        words = _content_words(clause)
        if words and sum(1 for w in words if w in cited) / len(words) < 0.5:
            return clause.strip()
    return None


#: 문장 안 합계 · 원문 기준 수치 경고(2.9.0 · 품질 게이트가 NUMBER_SUM · NOTICE_VALUE 로 따로 센다).
FLAG_SUM = "합계가 맞지 않습니다"
FLAG_FACT = "제안요청서 기준 수치와 다릅니다"
#: 원문 과업 구의 행위 · 대상 낱말을 약한 말로 바꿈(2.10.0 T3 · `plan_validation.softened_terms` · 경고만 — 게이트 REVIEW_FLAGS).
FLAG_SOFTENED = "제안요청서 과업 용어를 약하게 바꿈"
#: 회사 실적 조각에만 있는 수치(만족도 · 비율 · 인원)를 이 사업 목표로 씀(2.10.0 T3 · 경고만).
FLAG_PAST_TARGET = "회사 과거 실적 수치를 이 사업 목표로 씀"
_TARGET_RE = re.compile(r"목표|달성|이상\s*(?:유지|확보)")
_TARGET_UNIT_RE = re.compile(r"(?:점|%|명)$")
#: 실적 문장의 수행 역할 · 대상 낱말 — 그 원장 행 제목 · 요약에 있어야 한다(분야 field 는 분류 이름이라 근거가 아니다 · 2.10.0 T3 ·
#: 「시각화 교육」 → 「기업별 컨설팅」 · 「교육 운영」 → 「설계와 운영을 총괄」). 「운영 · 교육」은 요약에 거의 없어 보지 않는다.
_ROLE_WORDS_RE = re.compile(r"설계|총괄|기획|컨설팅|자문|멘토링|코칭|개발|구축|진단"
                            r"|창업\s*기업|스타트업|예비\s*창업|소상공인|청년|대학생|재직자|중소기업|공무원|교원")


def wider_roles(text: str, cited: str) -> list[str]:
    """회사 실적 마디(지난 실적 꼴)의 역할 · 대상 낱말 중 인용한 원장 제목 · 요약(`cited`)에 없는 것 — 계획 마디(「…를 설계하겠습니다」)는 보지 않는다.
    실적 꼴 뒤가 계획 꼬리(「…운영한 경험으로 재직자 과정을 기획하겠습니다」)면 실적 꼴 끝까지만 본다(T3 검토)."""
    have = plan_validation.compact(cited)
    out: dict[str, str] = {}
    for clause in _CLAUSE_SPLIT_RE.split(text):
        ends = [m.end() for regex in (_CLAIM_RE, _CLAIM_ANYWHERE_RE) for m in regex.finditer(clause)]
        if ends:
            end = max(ends)
            for match in _ROLE_WORDS_RE.finditer(clause[:end] if "겠" in clause[end:] else clause):
                if (key := plan_validation.compact(match.group(0))) not in have:
                    out.setdefault(key, match.group(0))
    return list(out.values())


def bid_filter(sentences: list[dict[str, Any]], blanks: list[dict[str, str]], section: str, *,
               sources: list[str], company_texts: dict[str, str] | None = None,
               names: tuple[str, ...] = _SUBJECTS, dropped: list[str] | None = None, annex: bool = False,
               facts: list[dict[str, Any]] | None = None, allowed: set[tuple[str, float]] | None = None,
               notice_sources: list[str] | None = None, task_terms: list[str] | None = None,
               role_texts: dict[str, str] | None = None, solo: bool = False) -> tuple[list[dict[str, Any]], int]:
    """(본문에 남길 문장, 뺀 수). 제출용에 남기면 안 되는 문장은 빈칸 목록(담당자 확인)으로 옮긴다.

    - 「확인 필요」 · 작성 사정 · 고치는 사람에게 하는 말 · 본문 속 빈칸 문장(대표 11-03 「확인 필요 모두 쓰지 마」 · 「(담당자 확인)」 2.10.0).
    - 회사 근거 없이 쓴 회사 주장 · 회사 근거 문장에 덧붙인 근거 밖 보유 · 실적 마디(`company_texts` 와 대조) ·
      역량 이름 · 사업영역 · 인증 이름만 근거로 쓴 지난 경험(「적용해 왔습니다」 · 11-06 심사) · 원장 제목 · 요약(`role_texts`)보다 넓힌
      역할 · 대상(2.10.0).
    - 회사가 정할 사항(공동수급 · 하도급) — 공동수급 불허 공고(`solo`)의 단독 수행 문장은 공고 조건이라 남긴다(2.10.0).
    - 과장 표현(「반드시 달성」 · 「완벽」 · 「보장합니다」 · 「100% 달성」 — `hype_words` · 원문을 옮긴 RFP_GROUNDED 는 남김 · 2.7.0).
    빈칸 목록이 아니라 그냥 빼는 것(`dropped` 에 「사유 — 문장」 · 검토 메모): 우리 제출 절차 문장(`annex` = 붙임 · 기타 소항목만) ·
    사업영역만 근거인 문장.
    남기는 문장에는 검토용 경고만 단다: 모호한 표현 · 제안요청서 말투 · 제안요청서 · 회사 자료에 없는 숫자(`sources` 와 대조 · 개월차 ·
    스스로 나열한 단계 수는 빼고) · 문장 안 합계 어긋남 · 원문 기준 수치(`facts` — 같은 이름 뒤 숫자)와 다름(2.9.0 · 3차 지시서 §5) ·
    원문 과업 용어 약화(`task_terms`) · 원문(`notice_sources`)에 없고 회사 자료에만 있는 수치를 목표로 씀(2.10.0)."""
    company_texts = company_texts or {}
    kept: list[dict[str, Any]] = []
    moved = 0
    for sentence in sentences:
        text = str(sentence.get("text") or "")
        ids = [str(i) for i in sentence.get("source_ids") or []]
        drop = (DROP_SUBMIT if annex and _SUBMIT_STEP_RE.search(text) and _SUBMIT_CTX_RE.search(text)
                # 사업영역(+ 설립)만 근거인 문장 — 「2021년에 설립했고 … 사업영역으로 합니다」도(11-06 심사 — 절마다 다르게 걸렀다)
                else DROP_DOMAINS if (sentence.get("type") == COMPANY and "profile:domains" in ids
                                      and set(ids) <= {"profile:domains", "profile:founded"} and re.search(r"사업\s*영역", text))
                else None)
        if drop:
            if dropped is not None:
                dropped.append(f"{drop} — {text}")
            continue
        # 제안요청서 요구를 당사 말투로 풀어 쓰면 인용보다 길어진다 — 입찰 제안서에서는 그 경고가 잡음뿐이다(11-03 실측 61건)
        flags = [str(f) for f in sentence.get("flags") or [] if f != plan_draft_service.FLAG_NOTICE_EXTRA]
        # 「공고에 없는 값」은 인용 한 문장만 보고 낸다 — 제안요청서 전문 · 회사 조각에 있으면 지운다(사업 기간 「2027년 1월 1일」 오탐)
        if any(f.startswith(plan_draft_service.FLAG_NOTICE_VALUES) for f in flags):
            missing = plan_validation.unsupported_bits(text, sources, orgs=False)
            flags = [f for f in flags if not f.startswith(plan_draft_service.FLAG_NOTICE_VALUES)]
            if missing:
                flags.append(f"{plan_draft_service.FLAG_NOTICE_VALUES}: {', '.join(missing[:3])} — 확인하세요")
        if marks := HUMAN_INPUT_RE.findall(text):
            # 본문 속 빈칸 문장 — 제출용에 빈칸 문장을 남기지 않고, 숫자를 정하면 넣을 문장으로 넘긴다(변형 꼴은 「(담당자 입력)」 하나로 · 2.8.0 B3) ·
            # 「(담당자 확인)」만 있으면 담당자 확인 목록으로(2.10.0)
            if all(_CHECK_MARK_RE.fullmatch(mark) for mark in marks):
                blanks.append({"field": "담당자 확인", "why": text, "section": section})
            else:
                blanks.append({"field": "값을 정하면 넣을 문장", "why": HUMAN_INPUT_RE.sub(HUMAN_INPUT, text), "section": section})
            moved += 1
            continue
        if _HEDGE_RE.search(text):
            blanks.append({"field": "담당자 확인", "why": text, "section": section})
            moved += 1
            continue
        hype = hype_words(sentence)
        if hype:
            # 과장 표현(「반드시 달성」 · 「완벽」 · 「보장」 · 「100% 달성」) — 경고만 달고 남기던 것을 본문에서 뺀다(2.7.0 · 계획 5)
            blanks.append({"field": HYPE_FIELD, "why": f"「{'」 · 「'.join(hype)}」 — 빼거나 확정형 계획으로 고치세요 — {text}", "section": section})
            moved += 1
            continue
        unsupported = any(f.startswith(_UNSUPPORTED_COMPANY_FLAGS) for f in flags)
        wider: list[str] = []
        if sentence.get("type") == COMPANY:
            cited = " ".join(company_texts.get(i, "") for i in ids)
            # 인증 근거가 하나라도 있으면 인증 취득 동사는 지난 경험으로 세지 않는다(인증 + 역량 근거 문장 · 4차 검토)
            past = _CERT_PAST_RE.sub("", text) if any(i.startswith("profile:cert:") for i in ids) else text
            weak = bool(ids) and all(i.startswith(_WEAK_SOURCES) for i in ids) and bool(_PAST_RE.search(past))
            # 회사가 스스로 적은 역량(skill:)만 근거인 「보유하고 있습니다 · 갖추고 있습니다」도 약한 근거(2.7.0 · 계획 5)
            weak = weak or (bool(ids) and all(i.startswith("skill:") for i in ids) and bool(_HOLD_NOW_RE.search(text)))
            unsupported = unsupported or weak or unsupported_company_clause(text, cited) is not None
            # 실적의 역할 · 대상은 원장 제목 · 요약 낱말만(분야 · 기관 칸은 근거가 아니다 · 2.10.0)
            roles = " ".join((role_texts or {}).get(i, "") for i in ids if i.startswith("ledger:"))
            wider = wider_roles(text, roles) if role_texts is not None and roles.strip() else []
        else:
            unsupported = unsupported or is_company_claim(text, names)
        if unsupported or wider:
            note = f"(원장보다 넓은 역할 · 대상 「{'」 · 「'.join(wider)}」)" if wider and not unsupported else ""
            blanks.append({"field": "회사 근거 없는 회사 주장", "why": f"근거를 붙이거나 지우세요{note} — {text}", "section": section})
            moved += 1
            continue
        # 공동수급 불허 공고(나라장터 공동수급 칸)의 단독 수행은 공고 조건 — 하도급 · 소속 직원은 여전히 회사가 정한다(2.10.0 · m0)
        if _DECISION_RE.search(text) and not (solo and not re.search(r"하도급|소속", text)):
            blanks.append({"field": "회사가 정할 사항", "why": f"공동수급 · 하도급 여부는 회사가 정해 적으세요 — {text}", "section": section})
            moved += 1
            continue
        vague = sorted({m.group(0).strip() for m in _VAGUE_RE.finditer(text)})
        if vague:
            flags.append(f"{FLAG_VAGUE}: {', '.join(vague)} — 확정형으로 고치세요")
        if _RFP_VOICE_RE.search(text):
            flags.append(FLAG_RFP_VOICE)
        broken = plan_validation.sum_breaks(text)
        conflicts = plan_validation.fact_conflicts(text, facts or [], allowed or set())
        if sentence.get("type") == SUGGESTION:
            plain = plan_validation.number_text(text)
            numbers = plan_validation.unsupported_bits(plain, [*sources, *conflicts, broken or ""], orgs=False)
            if numbers:
                flags.append(f"{FLAG_NUMBER}: {', '.join(numbers[:3])} — 확인하세요")
            if notice_sources is not None and _TARGET_RE.search(text):
                # 원문에는 없고 회사 조각에만 있는 수치(「만족도 4.9점」)를 목표로 — 원문과 같은 수면 원문 근거로 본다(놓치는 쪽)
                borrowed = [b for b in plan_validation.unsupported_bits(plain, [*notice_sources, *conflicts, broken or ""], orgs=False)
                            if b not in numbers and _TARGET_UNIT_RE.search(b)]
                if borrowed:
                    flags.append(f"{FLAG_PAST_TARGET}: {', '.join(borrowed[:3])} — 원문 기준 수치로 쓰거나 당사 목표 값은 담당자가 정하세요")
        if task_terms and (soft := plan_validation.softened_terms(text, task_terms, notice_sources or sources)):
            flags.append(f"{FLAG_SOFTENED}: " + " · ".join(f"「{phrase}」 → 「{body}」" for phrase, body in soft[:2]))
        if broken:
            flags.append(f"{FLAG_SUM}: {broken}")
        if conflicts:
            flags.append(f"{FLAG_FACT}: {', '.join(conflicts[:3])}")
        kept.append({**sentence, "flags": flags})
    return kept, moved


# ---------------------------------------------------------------------------
# 한 벌 만들기
# ---------------------------------------------------------------------------


def _rule_sentences(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """AI 를 부르지 않는 절 · 실패한 절 — 작성 방법을 담은 빈칸 한 줄(지어내지 않는다)."""
    guide = re.sub(r"\s+", " ", unit.get("guide") or "").strip()
    return [plan_draft_service._sentence(f"{HUMAN_INPUT} — {guide or unit['plain']}", None)]


def _doc_sentence(text: str) -> dict[str, Any]:
    """문서에 싣는 규칙 문장 — 안내 줄(note)이 아니다."""
    return {"text": text, "type": None, "source": None, "source_ids": []}


def _human_sentences(unit: dict[str, Any], table_titles: dict[str, str]) -> list[dict[str, Any]]:
    """사람이 채우는 소항목. 사람 몫 표가 딸리면 표를 가리키는 한 줄만(표 위에 같은 빈칸 줄을 또 찍지 않는다 · 11-06 심사 ③) ·
    서식 소항목이면 「서식 첨부」 빈칸(3차 검토 #21) · 그 밖은 작성 방법을 담은 빈칸."""
    titled = [table_titles[key] for key in unit["tables"] if key in table_titles]
    if titled:
        return [_doc_sentence(f"{titled[0]}은 다음 표와 같습니다.")]  # 사람 몫 표 이름은 모두 「… 현황」
    if unit.get("form"):
        return [_doc_sentence(f"{HUMAN_INPUT} — 서식 첨부: {unit['form']}")]
    return _rule_sentences(unit)


#: 붙임 서식 머리 줄 — 「[별첨1]」(이름은 다음 줄) · 「[서식 1호] 개인정보수집이용동의서(…)」 · 「[별지 제2호] …」 · 「<서식 3>」 · 「【붙임서식 2호】」.
_ANNEX_HEAD_RE = re.compile(r"^\s*([\[<【]\s*(별첨|별지|서식|붙임)\s*(?:서식\s*)?(?:제\s*)?(\d{1,2}(?:\s*-\s*\d{1,2})?)\s*호?\s*[\]>】])\s*(.*?)\s*$")
_ANNEX_NAME_SKIP_RE = re.compile(r"참조|참고|활용|따라|작성하|기재|제출하|첨부하|[다함음임]\.?$")
_ANNEX_LATER: tuple[tuple[re.Pattern[str], str], ...] = ((re.compile(r"계약\s*상대자"), "계약 때 제출"),
                                                        (re.compile(r"발표\s*평가|발표자"), "발표평가 때 제출"))


#: 원문이 붙이라고 한 입증 자료 줄(「…입증할 수 있는 관련 자료는 제안서의 붙임으로 제출」 · 「…증명할 수 있는 자료를 붙임으로 첨부」 · 4차 #3).
_PROOF_LINE_RE = re.compile(r"(?:붙임|별첨)\s*(?:자료)?\s*(?:으로|로)\s*(?:제출|첨부)")
_PROOF_WORD_RE = re.compile(r"입증|증명|증빙")
_PROOF_OBJECT_RE = re.compile(r"([^.]{2,60}?)\s*(?:을|를)\s*(?:객관적으로\s*)?(입증|증명|증빙)\s*할\s*수\s*있는")
_PROOF_NOUN_RE = re.compile(r"([^\s.,]{2,20})\s*(?:은|는|을|를)\s*(?:제안서의\s*)?(?:붙임|별첨)")  # 「실적증명자료는 붙임으로 첨부」
#: 「투입인력 소속 확인을 위한 증빙서류(재직증명서 · 4대보험 가입확인서 등) 추가 … 제출」 — 붙임 · 별첨 낱말이 없는 인력 증빙 줄(11-06 심사 · 1805118 별첨2 주3).
_STAFF_PROOF_RE = re.compile(r"((?:투입|참여)\s*인력\s*\S{1,6}\s*확인을\s*위한\s*증빙\s*서류(?:\s*\([^)]{1,60}\))?)[^.]{0,30}?제출")
_LINE_HEAD_RE = re.compile(r"^[\s\-–◦○◯•·ㅇ※*▢□■]*(?:(?:\d{1,2}(?:\.\d{1,2})*|[가-하])\s*[.)]\s*)?")


def _proof_name(line: str) -> str:
    """입증 자료 줄 → 원문 낱말로 서류명(「제안서 내용 입증 자료」 · 「자격증, 경력 및 수행업무 증명 자료」 · 「실적증명자료」)."""
    if not (match := _PROOF_OBJECT_RE.search(line)):
        noun = _PROOF_NOUN_RE.search(line)
        return noun.group(1) if noun else f"{_PROOF_WORD_RE.search(line).group(0)} 자료"  # type: ignore[union-attr] — 부르는 쪽이 낱말을 확인했다
    # 앞 마디(「… 계약을 해지할 수 있으며,」) · 「또는」 앞 · 주어(「제안사는」)는 떼고 대상 낱말만
    what = re.split(r"(?<=[며고면나서]),\s|\s또는\s", _LINE_HEAD_RE.sub("", match.group(1)))[-1]
    what = re.sub(r"^\S+(?:는|은)\s+", "", what)
    what = re.sub(r"의\s+", " ", re.sub(r"\s*(?:와|과)?\s*관련된\s*사항$", "", what)).strip()
    return f"{what} {match.group(2)} 자료"


def _where_label(doc: dict[str, Any], page: int) -> str:
    """검토용 원문 자리 「문서 이름 n쪽」 — 한글 문서는 문단 묶음으로 센 쪽이라 「(근사)」(4차 검토). 형식은 추출기가 본 값
    (`format` · 사전규격 규격서는 앱이 붙인 이름이라 확장자가 없다), 없으면 확장자."""
    name = str(doc.get("name") or "").strip()
    hangul = doc.get("format") in ("hwp", "hwpx") or bool(re.search(r"\.hwpx?$", name.split(" > ")[-1], re.I))
    approx = "(근사)" if hangul else ""
    return f"{name or '원문'} {page}쪽{approx}"


def proof_lines(docs: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """받아 둔 원문 전부에서 「붙임(별첨)으로 제출 · 첨부」 + 「입증 · 증명 · 증빙」 줄 → (서류명, 원문 자리, 원문 줄). 같은 서류명은 처음 것만."""
    found: dict[str, tuple[str, str, str]] = {}
    for doc in docs:
        lines, pages = _doc_lines(doc)
        for line, page in zip(lines, pages):
            if _PROOF_LINE_RE.search(line) and _PROOF_WORD_RE.search(line):
                name = _proof_name(line)
            elif staff := _STAFF_PROOF_RE.search(line):
                name = re.sub(r"\s*확인을\s*위한\s*", " 확인 ", staff.group(1))
            else:
                continue
            found.setdefault(name, (name, _where_label(doc, page), _LINE_HEAD_RE.sub("", line)))
    return list(found.values())


def annex_rows(docs: list[dict[str, Any]], *, built: tuple[str, ...] = ()) -> tuple[list[list[str]], list[str]]:
    """받아 둔 원문 전부의 붙임 서식 머리 줄 → (「붙임 번호 · 서류명 · 서식 번호」 행, 검토 메모) · 11-06 심사 ②.
    같은 번호가 여러 번이면(서식 목록 + 서식 본문) 처음 이름을 쓰고, 괄호에 「계약상대자 대상」 · 「발표평가 … 대상」이 한 번이라도 있으면
    제출 서류에서 빼고 검토 메모 「계약 때 · 발표평가 때 제출」. `built` = 문서가 따로 만드는 서식 이름 낱말(조견표). 못 찾으면 빈 목록(그 소항목은 AI 가 쓴다).
    서식 표를 만들면 원문이 붙이라고 한 입증 자료(`proof_lines`)도 행으로 더한다 — 원문 서식이 없는 서류라 그 칸은 「—」
    (제출용에 앱의 원문 쪽 표기를 싣지 않는다 · 쪽은 검토용 빈칸 목록에만 · 4차 #3 · 4차 검토)."""
    found: dict[tuple[str, str], dict[str, str]] = {}
    for doc in docs:
        lines = [line.strip() for line in (doc.get("text") or "").splitlines()]
        for index, line in enumerate(lines):
            head = _ANNEX_HEAD_RE.match(line)
            if not head:
                continue
            name = head.group(4) or next((n for n in lines[index + 1:index + 3] if n), "")
            plain = re.sub(r"\s*\d{1,3}$", "", re.sub(r"\([^)]*\)", "", name)).strip()  # 괄호 · 목차 쪽 번호 뺌
            if (not plain or len(plain) > 30 or _ANNEX_HEAD_RE.match(name) or _ANNEX_NAME_SKIP_RE.search(plain)
                    or any(word in plain for word in built)):
                continue
            row = found.setdefault((head.group(2), re.sub(r"\s+", "", head.group(3))),
                                   {"mark": re.sub(r"\s+", " ", head.group(1)), "name": plain, "later": ""})
            note = " ".join(re.findall(r"\(([^)]*)\)", name))
            row["later"] = row["later"] or next((why for pattern, why in _ANNEX_LATER if pattern.search(note)), "")
    rows = [(row["name"], row["mark"]) for row in found.values() if not row["later"]]
    if rows:  # 서식 표를 만들 때만 — 서식 머리를 못 찾으면 그 소항목은 지금처럼 AI 가 쓴다
        rows += [(name, "—") for name, _, _ in proof_lines(docs)]
    return ([[f"붙임 {n}", name, mark] for n, (name, mark) in enumerate(rows, start=1)],
            [f"{row['mark']} {row['name']} — {row['later']}" for row in found.values() if row["later"]])


#: 앞 소항목과 견줄 문장의 최소 길이(띄어쓰기 · 문장부호 뺀 글자) — 짧은 줄은 우연히 비슷하다.
REPEAT_MIN_CHARS = 20
_SUBJECT_HEAD_RE = re.compile(r"^[-–·•\s]*(?:당사(?:는|가|의|도)?\s+)?")


def _squashed(text: str) -> str:
    return re.sub(r"[\s.,·「」()\-]", "", _SUBJECT_HEAD_RE.sub("", text))


def _close(a: str, b: str) -> bool:
    # 길이 차가 크면 85% 겹침이 나올 수 없다 — 문장 쌍이 수만 개라 비율 계산 전에 거른다
    return a == b or (2 * min(len(a), len(b)) / (len(a) + len(b)) >= 0.85 and plan_export_service._similar(a, b))


def _drop_empty_heads(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """본문 줄이 하나도 남지 않은 「○」 소제목(다음이 소제목이거나 끝)은 뺀다 — 거르기가 그 아래 문장을 모두 뺀 자리(11-06 심사 ③)."""
    heads = [plan_export_service._subheading(str(s.get("text") or "")) for s in sentences]
    return [s for k, s in enumerate(sentences) if not heads[k] or (k + 1 < len(sentences) and not heads[k + 1])]


#: 번호 매긴 목록 줄(「(목표 1) …」 · 「① …」 · 「전략 2. …」) — 그 절의 목록이라 절 사이 정리에서 빼지 않는다(4차 #2).
_LIST_LINE_RE = re.compile(r"^[-–·•\s]*(?:\(\s*(?:목표|전략)\s*\d|[①-⑳]|(?:목표|전략)\s*\d{1,2}\s*[.:)·])")
#: 앞 문장을 가리키는 문장(「이 방식을 …」 · 「위 역량을 …」) — 앞 문장을 빼면 함께 뺀다(4차 #6). 「이 사업 · 해당 과업」은 사업을 가리킨다.
_POINTER_RE = re.compile(r"^[-–·•\s]*(?:이와\s*같은|이러한|이런|이를|이|위|해당)\s+(?!사업|과업|용역)")
#: 요약 쪽 소항목(개요 · 목적 · 특징 · 전략) — 같은 문장이 전용 절에도 있으면 이쪽을 뺀다(4차 #2). 제목에 목표 · 보안 · 일정 ·
#: 인력 · 품질 · 보고가 있으면 전용 절이다(「추진목표 및 전략」 · 4차 검토).
_SUMMARY_TITLE_RE = re.compile(r"개요|목적|특징|장점|전략|요약")
_DEDICATED_TITLE_RE = re.compile(r"목표|보안|일정|인력|품질|보고")
#: 제목 · 작성 방법 겹침에서 세지 않는 흔한 낱말 — 어느 절에나 있다(「기타」가 「사업」 · 「교육」으로 이겼다 · 4차 검토).
_TIDY_COMMON = {"사업", "발주기관", "기관", "교육", "과정", "제안", "내용", "사항"}
_ETC_TITLE_RE = re.compile(r"기타(?:\s*사항)?")


def _evidence_ids(sentence: dict[str, Any]) -> list[str]:
    return [str(i) for i in sentence.get("source_ids") or [] if str(i).startswith(("ledger:", "profile:"))]


def _repeat_loser(first: tuple[str, str, str], second: tuple[str, str, str], *, evidence: bool = False) -> int | None:
    """같은 문장 둘(문장 · 소항목 제목 · 제목 + 작성 방법) 중 뺄 쪽(0 앞 · 1 뒤 · None 둘 다 남김). 그 내용을 맡은 절에 남긴다 —
    「기타」가 아닌 쪽 → 제목 낱말이 문장과 더 겹치는 쪽 → 작성 방법 낱말이 더 겹치는 쪽 → 번호 매긴 목록 줄 →
    (회사 근거 문장이면 처음 쓴 쪽 — 참여인력 절로 실적을 옮기지 않게) → 개요 · 목적 · 특징 · 전략이 아닌 쪽 → 앞 문장.
    번호 목록 줄은 빼지 않는다."""
    words = [{w for w in _content_words(text) if w not in _TIDY_COMMON} for text, _, _ in (first, second)]
    etc = [bool(_ETC_TITLE_RE.fullmatch(first[1].strip())), bool(_ETC_TITLE_RE.fullmatch(second[1].strip()))]
    titles = [sum(1 for w in words[n] if w in side[1]) for n, side in enumerate((first, second))]
    guides = [sum(1 for w in words[n] if w in side[2]) for n, side in enumerate((first, second))]
    listed = [bool(_LIST_LINE_RE.match(first[0])), bool(_LIST_LINE_RE.match(second[0]))]
    summary = [bool(_SUMMARY_TITLE_RE.search(t)) and not _DEDICATED_TITLE_RE.search(t) for t in (first[1], second[1])]
    if etc[0] != etc[1]:
        loser = 0 if etc[0] else 1
    elif titles[0] != titles[1]:
        loser = 0 if titles[0] < titles[1] else 1
    elif guides[0] != guides[1]:
        loser = 0 if guides[0] < guides[1] else 1
    elif listed[0] != listed[1]:
        loser = 1 if listed[0] else 0
    elif evidence:
        loser = 1
    elif summary[0] != summary[1]:
        loser = 0 if summary[0] else 1
    else:
        loser = 1
    return None if listed[loser] else loser


def tidy_sections(sections: list[dict[str, Any]], form: dict[str, Any], *, exempt: set[str] | frozenset[str] = frozenset()) -> dict[str, list[str]]:
    """대항목을 합친 뒤 문서 순서로 한 번 훑는다(대항목마다 따로 쓰니 생기는 되풀이 · 11-06 심사 ③ ④). AI 가 쓴 소항목만.
    - 다른 소항목 문장과 거의 같은 문장(「당사는」 빼고 `plan_export_service._similar`)은 그 내용을 맡은 절에 남기고 다른 쪽을 뺀다(`_repeat_loser`).
    - 앞 소항목에서 이미 쓴 회사 근거(ledger: · profile:)만 단 문장은 뺀다 — 회사 근거는 본문에서 한 번(`exempt` = 붙임 목록 소항목).
    - 뺀 문장 바로 뒤의 「이 · 위 · 해당 …」 문장도 함께 뺀다(가리킬 문장이 없어진다).
    - 한 소항목의 문장이 모두 빠지게 되면 첫 문장 하나는 남긴다(빈칸 줄로 떨어져 사람 몫 표와 겹치지 않게).
    - 본문 줄이 하나도 남지 않은 「○」 소제목은 뺀다.
    → {소항목 제목: [검토 메모(「Ⅰ-1 과 같은 문장이라 뺐습니다 — …」)]}."""
    items = {item["key"]: item for section in form.get("sections") or [] for item in section.get("items") or []}
    entries = [entry for entry in sections if entry.get("by") == "llm"]
    numbers = [unit_number(form, entry["key"]) for entry in entries]
    plains = [str((items.get(e["key"]) or {}).get("plain") or e["section"]) for e in entries]
    abouts = [f"{plain} {(items.get(e['key']) or {}).get('guide') or ''}" for plain, e in zip(plains, entries)]
    texts = [[str(s.get("text") or "") for s in entry.get("sentences") or []] for entry in entries]
    evidence = [[_evidence_ids(s) for s in entry.get("sentences") or []] for entry in entries]
    # 뺀 까닭 — ("same", 남은 문장 자리) · ("ids", (근거 번호들, 처음 쓴 소항목)) · ("pointer", None). 메모 글은 정리가 끝난 뒤 만든다
    # (뒤에서 앞 문장을 다시 빼면 「Ⅰ-1 과 같은 문장」이 빠진 자리를 가리켰다 · 4차 검토).
    drop: dict[tuple[int, int], tuple[str, Any]] = {}
    seen_text: list[tuple[str, int, int]] = []  # 앞 소항목들에 남은 문장(본문 · 소항목 · 문장 자리)
    seen_ids: dict[str, int] = {}
    for e, entry in enumerate(entries):
        pending: list[tuple[str, int, int]] = []
        ids_here: list[str] = []
        for k, text in enumerate(texts[e]):
            if plan_export_service._subheading(text):
                continue
            body = _squashed(text)
            ids = evidence[e][k]
            match = next((n for n, (prev, _, _) in enumerate(seen_text) if _close(prev, body)), None) if len(body) >= REPEAT_MIN_CHARS else None
            if match is not None:
                _, pe, pk = seen_text[match]
                loser = _repeat_loser((texts[pe][pk], plains[pe], abouts[pe]), (text, plains[e], abouts[e]),
                                      evidence=bool(ids or evidence[pe][pk]))
                if loser == 1:
                    drop[(e, k)] = ("same", (pe, pk))
                    continue
                if loser == 0:  # 앞 소항목 문장을 빼고 이 문장이 그 자리를 잇는다
                    drop[(pe, pk)] = ("same", (e, k))
                    seen_text.pop(match)
            elif ids and entry["key"] not in exempt and all(i in seen_ids for i in ids) and not _LIST_LINE_RE.match(text):
                drop[(e, k)] = ("ids", (ids, seen_ids[ids[0]]))
                continue
            if len(body) >= REPEAT_MIN_CHARS:
                pending.append((body, e, k))
            ids_here += ids
        seen_text += pending
        for source_id in ids_here:
            seen_ids.setdefault(source_id, e)
    for e in range(len(entries)):
        for k in range(1, len(texts[e])):
            if (e, k - 1) in drop and (e, k) not in drop and _POINTER_RE.match(texts[e][k]):
                drop[(e, k)] = ("pointer", None)
        body = [k for k, text in enumerate(texts[e]) if not plan_export_service._subheading(text)]
        if body and all((e, k) in drop for k in body):
            # 첫 문장을 남기면 그 문장을 가리키는 바로 뒤 「이 …」 문장도 되살린다(이 사업에 적용하는 유일한 새 문장 · 4차 검토)
            k = body[0]
            drop.pop((e, k))
            while drop.get((e, k + 1), ("",))[0] == "pointer":
                k += 1
                drop.pop((e, k))

    def same_at(key: tuple[int, int]) -> str:
        for _ in range(len(drop) + 1):  # 남은 문장이 다시 빠졌으면 그 문장을 이은 자리로
            if drop.get(key, ("",))[0] != "same":
                break
            key = drop[key][1]
        return numbers[key[0]]

    def ids_at(ids: list[str], first: int, here: tuple[int, int]) -> str:
        holder = next((e for e in range(len(entries)) for k in range(len(texts[e]))
                       if (e, k) != here and (e, k) not in drop and ids[0] in evidence[e][k]), first)
        return numbers[holder]

    notes: dict[str, list[str]] = {}
    for e, entry in enumerate(entries):
        for k in range(len(texts[e])):
            if (e, k) not in drop:
                continue
            kind, ref = drop[(e, k)]
            why = (f"{same_at(ref)} 과 같은 문장이라 뺐습니다" if kind == "same"
                   else f"{ids_at(ref[0], ref[1], (e, k))} 에서 이미 쓴 회사 근거({', '.join(ref[0])})라 뺐습니다" if kind == "ids"
                   else "앞 문장을 뺀 자리라 함께 뺐습니다")
            notes.setdefault(entry["section"], []).append(f"{why} — {texts[e][k]}")
    for e, entry in enumerate(entries):
        entry["sentences"] = _drop_empty_heads([s for k, s in enumerate(entry["sentences"]) if (e, k) not in drop])
    return notes


def generate(
    *,
    source: dict[str, Any],
    company: dict[str, Any],
    writer: str = "claude",
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    """초안 한 벌. source: title · agency · text(제안요청서 전문) · document · requirement_set_hash.

    대항목마다 한 번 · 한꺼번에 부른다(제안서 작성 문 — Claude · Codex CLI). 대항목 하나가 실패해도 다른 대항목은 남는다
    (그 절은 빈칸 한 줄).
    """
    started = clock()
    text = source["text"]
    # 목차 · 평가표 · 형식 규정은 받아 둔 원문 전부에서(11-06) — 원문 목록이 없으면(예전 호출 · 시험) 이 글 하나
    docs = source.get("docs") or [_text_doc(text, name=source.get("document"))]
    layout = read_layout(docs)
    # rfp — 제안요청서 목차대로 · unread — 목차 머리는 있는데 읽지 못해 표준 목차 · standard — 목차가 없어 표준 목차
    outline_source = layout["outline_source"]
    outline = layout["outline"]
    evaluation = layout["evaluation"]
    excerpt, rules = rfp_excerpt(text)
    terms = project_terms(excerpt)
    # 계약 예정일 ~ 끝날 일수 · 주차(입찰공고문 · D1) · 나라장터 배정예산 · 추정가격(공고 원본 칸 · 11-13)
    terms.update(contract_span(terms, docs))
    terms.update(source.get("notice_budget") or {})
    terms["deadline"] = source.get("deadline")  # 입찰 마감 — 제출서류 유효기간 기준(2.10.0 T8)
    terms["qualification_deadline"] = source.get("qualification_deadline")  # 참가자격등록 마감 — 보고서 엑셀 칸
    papers = submission_papers(docs)  # 입찰공고문 제출서류 — 조견표 정량 행 짝(T7) · 검토 「제출 서류」 묶음 · 보고서(T8)
    # 원문 정량값(3차 지시서 §5) — 기준 수치(이름 · 값 · 단위 · 한정어) · 백분율 계산값. 작성기 · 거르기 · 품질 게이트가 같은 값을 쓴다
    facts = plan_validation.notice_facts(excerpt)
    derived = plan_validation.derived_counts(excerpt)
    allowed = {(d["unit"], float(d["value"])) for d in derived}
    work = {**source, "evaluation": evaluation, "excerpt": excerpt, "rules": rules, "terms": terms, "facts": facts, "derived": derived,
            "blind": bool(layout["format"].get("blind"))}
    form = build_form(outline, evaluation, terms, title=source["title"])
    if any(t["key"] == SCHEDULE_TABLE["key"] for t in form["tables"]):
        form["schedule_expect"] = schedule_expect(excerpt)  # 원문이 요구한 보고 줄(품질 게이트가 일정표와 대조 · 2.9.0)
    if onsite := onsite_activities(excerpt):
        form["onsite"] = onsite  # 원문이 대면으로 정한 활동(품질 게이트 REMOTE_SWAP · 2.10.0)
    units = form_units(form)
    targets = unit_targets(units, layout["format"].get("page_limit"))
    for unit in units:
        unit["target_chars"] = targets[unit["key"]]
    # 과업별 대응 표를 맡길 소항목 — 제목 · 작성 방법에 「범위」가 있는 첫 곳(일정표 소항목 뺌 · 2.10.0 T3)
    if scope_unit := next((u for u in units if u["kind"] == "item" and not u["human"] and not u["annex"]
                           and SCHEDULE_TABLE["key"] not in u["tables"] and _SCOPE_RE.search(f"{u['plain']} {u['guide']}")), None):
        scope_unit["scope"] = True
    # 예산 배분안(2.10.0 D3) — 원문 과업 · 작성 방법에 예산 계획이 있고 사업금액을 읽었을 때만. 소항목 tables(AI 에 보내는 표 목록)에는
    # 넣지 않고 쓴 뒤 그 소항목 끝(핵심 마감과 책임 뒤)에 붙인다
    budget_names = budget_tasks(excerpt)
    budget_at = budget_unit(form, budget_names)
    if budget_at and terms.get("budget_won"):
        form["tables"].append({**BUDGET_TABLE, "section": budget_at[0], "item": budget_at[1]})
    pieces = company_pieces(company, f"{source['title']} {excerpt[:4000]}", title=source["title"])
    payload = llm_payload(pieces, blind=work["blind"])  # 평가본 공고는 실적 기관 이름 대신 유형(2.10.0 blind3)
    bundles = {u["key"]: _bundle(u, pieces, evaluation, terms) for u in units}
    all_text = "\n".join(doc.get("text") or "" for doc in docs) if source.get("docs") else text
    notice = plan_validation.NoticeIndex(all_text)
    # AI 계획 문장의 숫자를 대조할 글 — 받아 둔 원문 전부 + 보낸 회사 조각(원문 쪽만은 과거 실적 수치를 목표로 쓴 문장을 가린다 · 2.10.0)
    company_texts = plan_draft_service.source_texts(next(iter(bundles.values()))) if bundles else {}
    notice_sources = [all_text, " ".join(f"{d['value']}{d['unit']}" for d in derived),
                      # 계약 예정일 ~ 끝날로 계산한 주 · 일 수(「약 6주」 · 「44일」 — 원문에 없는 숫자가 아니다 · 2.10.0 D1)
                      f"{terms['weeks']}주 {terms['days']}일" if terms.get("weeks") else ""]
    number_sources = [*notice_sources, *company_texts.values()]
    # 실적 역할 · 대상의 근거는 원장 제목 · 요약만(분야 · 기관 칸 뺌) · 원문 과업 구(약화 경고) — 2.10.0 T3
    role_texts = {row["id"]: f"{row.get('title') or ''} {row.get('summary') or ''}" for row in pieces.get("ledger") or []}
    task_terms = plan_validation.task_phrases(excerpt)
    names = _company_names(pieces.get("profile") or {})

    ready, off_reason = llm_client.plan_writer_ready(writer)
    # 제출 서류 목록 소항목(「기타 — 별지서식 자료 · 제출 서류 목록」)은 원문 서식 머리 줄로 표를 만든다 — 못 찾으면 AI 가 쓴다(11-06 심사 ②)
    annex_units = [u for u in units if u["annex"]]
    # 평가표를 읽었으면 「기술능력 평가항목별 조견표」 서식은 문서 맨 앞 조견표가 맡는다
    annex, annex_later = annex_rows(docs, built=("조견표",) if evaluation.get("items") else ())
    annex_key = annex_units[0]["key"] if annex and annex_units else None
    writable = [u for u in units if u["kind"] == "item" and not u["human"] and u["key"] != annex_key]
    majors: dict[str, list[dict[str, Any]]] = {}
    for unit in writable:
        majors.setdefault(unit["major_key"], []).append(unit)
    outline_lines = major_lines(form)
    lock = threading.Lock()
    calls = 0

    def remaining() -> float:
        return TIME_LIMIT_SECONDS - (clock() - started)

    def write(major_key: str) -> BidMajorOut | str:
        nonlocal calls
        left = remaining()
        if left < MIN_CALL_SECONDS:
            return "시간 상한을 넘어 빈칸으로 둡니다"
        with lock:
            calls += 1
        group = majors[major_key]
        try:
            return llm_client.complete_structured(
                system=SYSTEM_PROMPT, user=major_prompt({"title": group[0]["major_title"]}, group, source=work, company=payload,
                                                        others=[line for key, line in outline_lines.items() if key != major_key]),
                schema=BidMajorOut, temperature=0.2, purpose=f"bid_plan:{group[0]['major_title']}", timeout=left,
                plan_writer=True, writer=writer, attempt_cap=TIME_LIMIT_SECONDS,  # 시도 한 번도 한 벌 상한까지(설정 180초에 끊겼다 · 2.9.0)
            )
        except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
            return str(exc)
        except OSError as exc:  # 임시 폴더 · 프로세스 오류도 그 대항목만 실패
            return f"AI 작성 중 시스템 오류({type(exc).__name__}) — 빈칸으로 둡니다"

    results: dict[str, BidMajorOut | str] = {}
    if ready and majors:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(majors))) as pool:
            futures = {key: pool.submit(write, key) for key in majors}
        results = {key: future.result() for key, future in futures.items()}

    tables = {t["key"]: plan_draft_service.rule_table(t) for t in form["tables"]}
    if BUDGET_TABLE["key"] in tables:  # 과업마다 사람 몫 한 줄(과업 목록을 못 읽으면 빈 줄 하나) + 끝 줄만 코드
        tables[BUDGET_TABLE["key"]]["rows"] = ([[name, HUMAN_INPUT, HUMAN_INPUT, HUMAN_INPUT] for name in budget_names] or [[HUMAN_INPUT] * 4]) \
            + budget_totals(terms["budget_won"], terms.get("budget_vat"))
    human_tables = {t["key"]: t["title"] for t in form["tables"] if t.get("human_only")}
    sections: list[dict[str, Any]] = []
    blanks: list[dict[str, str]] = []
    covered: dict[str, list[str]] = {}
    eval_claims: dict[str, list[str]] = {}
    review: dict[str, list[str]] = {}
    counts = {"demoted": 0, "copy": 0, "banned": 0, "moved": 0, "vague": 0, "dropped": 0, "repeated": 0}
    failures: list[str] = []
    for unit in units:
        entry: dict[str, Any] = {
            "key": unit["key"], "kind": unit["kind"], "section": unit["title"], "major_key": unit["major_key"],
            "major_title": unit["major_title"], "optional": False, "tables": unit["tables"], "fields": [], "llm_error": None, "by": "rules",
        }
        if unit["kind"] == "fields":
            entry["fields"] = [{"label": f["label"], "value": HUMAN_INPUT, "human_only": False, "source_ids": []} for f in unit["fields"]]
            entry["sentences"] = [plan_draft_service._sentence(f"{f['label']}: {HUMAN_INPUT}", None) for f in unit["fields"]]
            blanks += [{"field": f["label"], "why": "회사자료에 값이 없으면 담당자가 채웁니다", "section": unit["title"],
                        "proof": f"회사자료 › 일반현황 「{f['label']}」"} for f in unit["fields"]]
            sections.append(entry)
            continue
        if unit["key"] == annex_key:
            # 제출 서류 목록 — AI 없이 원문 서식 머리 줄로(계약 · 발표평가 때 내는 서식은 검토 메모로)
            entry["sentences"] = [_doc_sentence("제안서와 함께 내는 서류는 다음과 같습니다.")]
            entry["tables"] = [*unit["tables"], ANNEX_TABLE_KEY]
            tables[ANNEX_TABLE_KEY] = {"key": ANNEX_TABLE_KEY, "title": "제출 서류 목록", "columns": ["붙임 번호", "서류명", "서식 번호"],
                                       "rows": annex, "by": "rules", "human_only": False, "section": unit["major_key"], "item": unit["key"]}
            if annex_later:
                review.setdefault(unit["title"], []).extend(annex_later)
            # 원문이 붙이라고 한 입증 자료 — 붙이지 않으면 「인정하지 않음」이라 담당자가 챙길 줄로도(4차 #3)
            blanks += [{"field": "붙임 증빙", "why": f"{where} ‘{line}’", "section": unit["title"]} for _, where, line in proof_lines(docs)]
            sections.append(entry)
            continue
        if unit["human"]:
            entry["sentences"] = _human_sentences(unit, human_tables)
            if unit["form"]:
                named = DEFAULT_FORM if unit["form"] == DEFAULT_FORM else f"{DEFAULT_FORM}({unit['form']})"
                order = f" · 원문 지시: ※ {unit['form_order']}" if unit.get("form_order") else ""
                blanks.append({"field": unit["plain"], "why": f"서식 첨부 — {named}을 채워 붙이세요{order}", "section": unit["title"]})
            elif not any(key in human_tables for key in unit["tables"]):
                blanks.append({"field": unit["plain"], "why": "본문 — 담당자 입력", "section": unit["title"]})
            sections.append(entry)
            continue
        result = results.get(unit["major_key"])
        out = next((u for u in result.units if u.key == unit["key"]), None) if isinstance(result, BidMajorOut) else None
        if out is None:
            if unit in writable and isinstance(result, str):
                entry["llm_error"] = result
                failures.append(unit["title"])
            elif unit in writable and ready and isinstance(result, BidMajorOut):
                entry["llm_error"] = "AI 답에 이 소항목이 없었습니다"
                failures.append(unit["title"])
            entry["sentences"] = _rule_sentences(unit)
            blanks.append({"field": unit["plain"], "why": "AI 가 쓰지 못한 소항목 — 초안을 다시 쓰거나 직접 쓰세요", "section": unit["title"]})
            sections.append(entry)
            continue
        section_out = PlanSectionOut(sentences=out.sentences, tables=PlanTablesOut(schedule=out.schedule), blanks=out.blanks)
        # 입찰 일정표는 과업 행이라 「본문 n단계 = 일정표 n줄」 검사를 끈다(2.9.0 · 2 · 3위 Claude 오탐)
        sentences, rows, unit_blanks, unit_counts = plan_draft_service.validate_unit(section_out, bundles[unit["key"]], form=form, notice=notice,
                                                                                    steps_check=False)
        dropped: list[str] = []
        sentences, moved = bid_filter(sentences, unit_blanks, unit["title"], sources=number_sources, company_texts=company_texts, names=names,
                                      dropped=dropped, annex=submit_unit(unit), facts=facts, allowed=allowed, notice_sources=notice_sources,
                                      task_terms=task_terms, role_texts=role_texts, solo=bool(source.get("joint_solo")))
        for key in ("demoted", "copy", "banned"):
            counts[key] += unit_counts.get(key, 0)
        counts["moved"] += moved
        counts["dropped"] += len(dropped)
        if dropped:
            review.setdefault(unit["title"], []).extend(f"뺐습니다 — {line}" for line in dropped)
        entry["sentences"] = sentences
        entry["by"] = "llm"

        def soft(text: str, item: str, title: str) -> str:
            # 원문 과업 구를 약한 말로 바꾼 표 칸(본문 문장 FLAG_SOFTENED 와 같은 검사 · T3 검토) — 칸 끝 검토 표식 + 확인할 원문 값 한 줄
            found = plan_validation.softened_terms(plan_export_service._CELL_MARK.sub("", text), task_terms, notice_sources) if task_terms else []
            if not found:
                return text
            words = " · ".join(f"「{phrase}」 → 「{body}」" for phrase, body in found[:2])
            unit_blanks.append({"field": "원문 정량값 확인", "section": unit["title"],
                                "why": f"{title} 「{item}」 — {FLAG_SOFTENED}({words}) · 원문 과업 낱말로 고치세요"})
            return text + (" · " if "⚠" in text else " ⚠ ") + FLAG_SOFTENED

        for key, value in rows.items():
            if key in tables:
                if key == SCHEDULE_TABLE["key"]:  # 일정표 「주요 활동」 칸(5칸 일정표 넷째 칸 · 사업계획서 3칸은 그대로)
                    value = [[*row[:3], soft(row[3], row[0], tables[key]["title"]), *row[4:]] if len(row) == 5 else row for row in value]
                tables[key]["rows"], tables[key]["by"] = value, "llm"
        # AI 가 채운 덧붙임 표(핵심 마감과 책임 2.10.0 D2 · 과업별 대응 T3) — 일정표 칸과 같은 칸 검사(예시 값 · 사람 칸 · 금칙어 · 공고 복사) ·
        # 행이 없으면 표를 두지 않는다
        marks = {"examples": 0, "human": 0, "banned": 0, "copy": 0}

        def cell(value: str, item: str, title: str, *, due: bool = False, numbers: bool = True, copy: bool = True, terms: bool = False) -> str:
            # 마감 기준(원문 날짜) · 과업 이름(원문 그대로)은 지시대로 원문을 옮기는 칸이라 공고 복사 검사만 끈다(사람 칸 · 금칙어는 본다 · T2 검토) ·
            # terms — 과업 용어 약화도 보는 칸(과업별 대응 「제안 대응」)
            text = plan_draft_service._clean_cell(value, examples=form.get("form_examples") or {}, notice=notice, exclude=[],
                                                  counts=marks, blanks=unit_blanks, section=unit["title"], copy=copy and not due)
            probe = plan_export_service._CELL_MARK.sub("", text)
            # 원문에 없는 숫자 · 날짜(§11) — 본문 문장의 FLAG_NUMBER 와 같은 대조 · 마감 칸의 연도 없는 「12. 29.」도 날짜로(T2 검토)
            bits = plan_validation.unsupported_bits(plan_validation.number_text(_BARE_DATE_RE.sub(r"\1월 \2일", probe) if due else probe),
                                                    number_sources, orgs=False) if numbers else []
            if bits:
                unit_blanks.append({"field": "원문 정량값 확인", "section": unit["title"],
                                    "why": f"{title} 「{item}」 「{probe}」 — 제안요청서에 없는 날짜 · 숫자({', '.join(bits[:3])}) · "
                                           "원문 날짜나 일정표 기간으로 고치세요"})
                text += (" · " if "⚠" in text else " ⚠ ") + f"{FLAG_NUMBER}({', '.join(bits[:3])})"
            return soft(text, item, title) if terms else text

        extra: list[tuple[dict[str, Any], list[list[str]]]] = []
        if out.milestones and SCHEDULE_TABLE["key"] in unit["tables"]:
            title = MILESTONE_TABLE["title"]
            extra.append((MILESTONE_TABLE, [[cell(r.item, r.item, title), cell(r.owner, r.item, title, numbers=False),
                                             cell(r.due, r.item, title, due=True), cell(r.proof, r.item, title)]
                                            for r in out.milestones if r.item.strip()]))
        if out.scope and unit.get("scope"):
            title = SCOPE_TABLE["title"]
            extra.append((SCOPE_TABLE, [[cell(r.task, r.task, title, copy=False), cell(r.detail, r.task, title, terms=True),
                                         cell(r.output, r.task, title, copy=False)]
                                        for r in out.scope if r.task.strip()]))
        for table, table_rows in extra:
            if table_rows:
                tables[table["key"]] = {**table, "rows": table_rows, "by": "llm", "section": unit["major_key"], "item": unit["key"]}
                entry["tables"] = [*entry["tables"], table["key"]]
        counts["banned"] += marks["banned"]
        counts["copy"] += marks["copy"]
        blanks += unit_blanks
        eval_claims[unit["key"]] = out.eval_items
        entry["eval_items_raw"] = list(out.eval_items)  # AI 가 돌려준 그대로(진단용 · 조견표 빈칸 원인 · 2.8.0 B4)
        sections.append(entry)

    if budget_at and BUDGET_TABLE["key"] in tables:
        entry = next(e for e in sections if e["key"] == budget_at[1])
        entry["tables"] = [*entry["tables"], BUDGET_TABLE["key"]]
    # 대항목을 합친 뒤 — 절 사이 같은 문장 · 같은 회사 근거 · 빈 「○」 소제목을 뺀다(11-06 심사 ③ ④)
    for title, items in tidy_sections(sections, form, exempt={u["key"] for u in annex_units}).items():
        counts["repeated"] += len(items)
        review.setdefault(title, []).extend(items)
    by_key = {u["key"]: u for u in units}
    # AI 가 적은 이름은 공백 · 문장부호를 빼고 맞춘다 — 글자 하나 달라 빈칸이 됐다(11-10 2 · 3위 · 2.8.0 B4)
    eval_names = {_name_key(item["name"]): item["name"] for item in evaluation.get("items") or []}
    for entry in sections:
        if entry["by"] != "llm":
            continue
        if not entry["sentences"]:
            entry["sentences"], entry["by"] = _rule_sentences(by_key[entry["key"]]), "rules"
            continue
        counts["vague"] += sum(1 for s in entry["sentences"] if any(str(f).startswith(FLAG_VAGUE) for f in s.get("flags") or []))
        # 조견표 「제안서 해당 목차」 — 본문이 남은 소항목만(거르기로 모두 빠진 소항목을 가리키지 않게 · 11-03 검토)
        for name in eval_claims.get(entry["key"]) or []:
            if (real := eval_names.get(_name_key(name))) and entry["key"] not in covered.get(real, []):
                covered.setdefault(real, []).append(entry["key"])
    written = {entry["key"] for entry in sections if entry.get("sentences") or entry.get("tables")}
    # 짝 출처(행마다 · 제출용 표에는 싣지 않음) — AI 자기 신고 → 이름 짝(제목) → 본문 「○」 소제목 짝(한 곳뿐 · 짝 항목 없을 때만)
    pair_sources = dict.fromkeys(covered, "ai")
    found = title_matches(form, evaluation, written, covered)
    covered.update(found)
    pair_sources.update(dict.fromkeys(found, "title"))
    found = heading_matches(evaluation, sections, covered)
    covered.update(found)
    pair_sources.update(dict.fromkeys(found, "heading"))
    # 이름이 흔한 말뿐인 항목(「사업 수행역량」) — 평가 기준 낱말을 소항목 작성 방법 · 본문에 대 본다(3차 지시서 §3 · 11-11 3위)
    found = guide_matches(form, evaluation, sections, covered)
    covered.update(found)
    pair_sources.update(dict.fromkeys(found, "guide"))
    # 그래도 빈 정성 항목만 AI 에 한 번 더 묻는다 — 본문이 남은 소항목 key 만 받는다 · 실패하면 빈칸 그대로(품질 게이트 차단)
    missing = [item for item in evaluation.get("items") or [] if item.get("kind") != "정량" and not covered.get(item["name"])]
    llm_keys = {entry["key"] for entry in sections if entry.get("by") == "llm" and entry.get("sentences")}
    eval_retry = None
    if ready and missing and llm_keys and remaining() >= MIN_CALL_SECONDS:
        eval_retry = {"asked": [item["name"] for item in missing], "paired": [], "error": None}
        calls += 1
        try:
            answer = llm_client.complete_structured(
                system=EVAL_RETRY_SYSTEM, user=eval_retry_prompt(missing, form, sections), schema=EvalRetryOut, temperature=0.0,
                purpose=EVAL_RETRY_PURPOSE, timeout=remaining(), plan_writer=True, writer=writer, attempt_cap=TIME_LIMIT_SECONDS)
        except (llm_client.LLMUnavailableError, llm_client.LLMValidationError, OSError) as exc:
            eval_retry["error"] = str(exc)[:200]
        else:
            asked = {_name_key(item["name"]): item["name"] for item in missing}
            numbers = {unit_number(form, key): key for key in llm_keys}
            for pair in answer.pairs:
                real = asked.get(_name_key(pair.name))
                keys = list(dict.fromkeys(k if k in llm_keys else numbers.get(k.strip(), "") for k in pair.keys))
                keys = [k for k in keys if k]
                if real and keys and not covered.get(real):
                    covered[real] = keys
                    pair_sources[real] = "ai_retry"
                    eval_retry["paired"].append(real)

    # 다섯째 칸 「제안서 근거(소제목)」 · 짝 없는 정량 행은 공고문 제출서류 번호(2.10.0 T7 m5 · m6)
    eval_table = evaluation_table(form, evaluation, covered, sources=pair_sources, sections=sections, papers=papers)
    if eval_table is not None:
        tables[EVAL_TABLE_KEY] = eval_table
        sections.insert(0, {"key": "EVAL", "kind": "table_only", "section": eval_table["title"], "major_key": "EVAL",
                            "major_title": eval_table["title"], "optional": False, "tables": [EVAL_TABLE_KEY], "fields": [],
                            "sentences": [], "llm_error": None, "by": "rules"})
    # 참여인력 표 — 구분(역할) · 담당 업무만 본문 업무분장에서 · 사람 값 칸은 빈칸 그대로(2.10.0 D4 · 못 읽으면 지금처럼 한 줄 모두 빈칸)
    people = tables.get(PEOPLE_TABLE["key"])
    if people and (roles := staff_roles(sections, units, people.get("item"))):
        people["rows"] = [[role if i == 0 else duty if column == "담당 업무" else HUMAN_INPUT for i, column in enumerate(people["columns"])]
                          for role, duty in roles]
    blanks += [{"field": t["title"], "why": "사람만 채우는 표", "section": next((u["title"] for u in units if u["key"] == t.get("item")), "")}
               for t in form["tables"] if t.get("human_only")]
    if annex_key is None:
        # 붙임 소항목이 없는 목차 — 원문이 정한 제출 서식 · 입증 자료 · 계약 때 서식을 담당자 보완자료로(3차 지시서 §9 · 11-11 3위)
        def key(value: Any) -> str:
            return re.sub(r"[^0-9가-힣]", "", str(value))

        # 사람 몫 서식 소항목이 이미 「서식 첨부」 빈칸을 만든 서식은 다시 넣지 않는다(「<서식4-1>」 = 「[서식 4-1]」 · 3차 검토)
        taken = {key(u["form"]) for u in units if u["human"] and u.get("form")} | {key(u["plain"]) for u in units if u["human"]}
        blanks += [{"field": SUPPLEMENT_FORM, "why": f"{row[0]} {row[1]} — 원문 붙임 서식: 제안서와 함께 낼 서류인지 확인하고 채우세요",
                    "section": SUPPLEMENT_SECTION}
                   for row in annex if len(row) >= 3 and str(row[2]).strip() not in ("—", "") and not _SOURCE_DOC_RE.search(str(row[1]))
                   and not _ANNEX_REF_RE.search(str(row[1])) and key(row[2]) not in taken and key(row[1]) not in taken]
        blanks += [{"field": "붙임 증빙", "why": f"{where} ‘{line}’", "section": SUPPLEMENT_SECTION} for _, where, line in proof_lines(docs)]
        if annex_later:
            review.setdefault(SUPPLEMENT_SECTION, []).extend(annex_later)
    # 비용 · 수행 가능성(내부 검토용 · 제출용에 싣지 않는다 · 3차 지시서 §7)
    blanks += cost_lines(excerpt, terms.get("assigned_budget") or terms.get("budget_won"))  # 비율은 나라장터 배정예산 먼저(11-13)
    if budget_at or budget_names:  # 예산 과업이 있는 공고 — 공고 금액 · 기초금액과 투찰금액 · 총액 유지(2.10.0 D3)
        blanks += budget_lines(terms, table=BUDGET_TABLE["key"] in tables)
    # 원문 안에서 백분율과 근사값이 어긋나면(「105명의 최소 50%(약 50건)」 = 최소 53) — 원문 표현은 고치지 않고 사람이 확인(3차 지시서 §5 사례 1)
    body_text = " ".join(str(x.get("text") or "") for entry in sections for x in entry.get("sentences") or [])
    blanks += [{"field": "원문 정량값 확인",
                "why": f"원문 「{d['quote']}」 — {d['base']}명의 {d['percent']}%는 최소 {d['value']}{d['unit']}(올림)인데 원문은 「약 {d['approx']}{d['unit']}」입니다. "
                       + (f"본문에 계산값 「{d['value']}{d['unit']}」을 썼습니다 — 원문 표현으로 둘지 정하세요"
                          if re.search(rf"(?<!\d){d['value']}\s*{d['unit']}", body_text) else "발주기관 질의나 내부 기준을 정하세요"),
                "section": "제안요청서 정량값"} for d in derived if d.get("approx") is not None and d["approx"] != d["value"]]

    generated_by = "llm" if any(s["by"] == "llm" for s in sections) else "rules"
    if not ready:
        note = "AI 작성 꺼짐 — 목차와 빈칸만 만들었습니다" + (f" ({off_reason})" if off_reason else "")
    elif failures:
        # 첫 사유를 붙인다 — 화면이 「사용 한도」 안내를 이 글로 알아본다(11-03 검토)
        first = next((s["llm_error"] for s in sections if s.get("llm_error")), "")
        note = f"AI 작성 실패 소항목 {len(failures)}개 — 그 소항목은 빈칸으로 둡니다" + (f" · 첫 사유: {first}" if first else "")
    else:
        note = None
    return {
        "procurement_id": source.get("procurement_id"),
        "kind": DOC_KIND,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": generated_by,
        "writer": writer if generated_by == "llm" else None,
        "provider": llm_client.plan_writer_provider(writer) if generated_by == "llm" else None,
        "model": llm_client.plan_writer_model(writer) if generated_by == "llm" else None,
        "title": source["title"],
        "agency": source.get("agency"),
        "notice_no": source.get("notice_no"),  # 표지 「공고번호」(2.7.0 · 계획 4) — 옛 초안은 읽을 때 공고 저장본에서
        # 표지 「공고 원문」 링크(2.9.1) — 공고 저장본(최근 30일 게시)에서 빠진 뒤에도 마감 전 공고는 표지에 남게 초안에도 둔다
        "notice_url": plan_export_service.official_link(source.get("notice_url")),
        "rfp_document": source.get("document"),
        "sources": [doc.get("name") for doc in docs],  # 쓸 때 실제로 읽은 원문 이름 — 사전규격 규격서뿐인가(`source_gap` · 2.11.0 T9)
        "requirement_set_hash": source.get("requirement_set_hash"),
        "outline_source": outline_source,
        "evaluation_total": evaluation.get("total"),
        # 어디서 읽었나(11-06) — 화면 「이 제안서 양식」 · 초안 머리가 같은 값을 보인다
        "outline_where": layout["outline_where"],
        "outline_found_at": layout["outline_found_at"],
        "outline_rejected": layout["outline_rejected"],
        "evaluation_where": evaluation.get("where"),
        "format": layout["format"],
        "terms": stored_terms(terms),  # 사업기간 · 사업금액 원문 글(표지 · 품질 게이트 대조 · 2.8.0 B6)
        # 입찰공고문 제출서류 · ※ 제출 방법(원문 그대로) — 유효기간 짝은 읽을 때 지금 회사 자료로(`paper_rows` · 옛 초안에는 없음 · 2.10.0 T8)
        "papers": papers,
        # 원문 기준 수치 · 백분율 계산값(품질 게이트가 본문과 다시 대조 · 3차 지시서 §5 · 2.9.0)
        "facts": facts,
        "derived": derived,
        "form": form,
        "sections": sections,
        "tables": list(tables.values()),
        "blanks": _merge_blanks(blanks),
        "llm_note": note,
        "llm_failures": failures,
        # 검토용 메모 — 제출용에서 뺀 문장(절 사이 되풀이 · 제출 절차) · 계약 · 발표평가 때 내는 서식. 「고치지 못한 약점」(review_notes)이 아니다(4차 #7)
        "review_notes": [],
        "removed_notes": [{"section": title, "items": items} for title, items in review.items()],
        "review_scores": [],
        "numbered_titles": True,
        "validation": counts,
        "attempts": {"logical_calls": calls, "max_logical_calls": len(majors) + 1},
        # 조견표 다시 묻기(빈 정성 항목이 남았을 때만 · 3차 지시서 §3) — 물은 항목 · 짝을 지은 항목 · 실패 사유
        "eval_retry": eval_retry,
    }


EVAL_TITLE = "기술능력 평가항목별 조견표"
#: 비용 · 수행 가능성 검토(3차 지시서 §7 · 내부 검토용 — 제출용에 싣지 않는다).
COST_SECTION = "예산 · 수행 가능성(내부 검토)"
COST_FIELD = "비용 항목"
_COST_PRODUCT_RE = re.compile(r"(\d+)\s*만\s*원\s*[*×xX]\s*(\d+)\s*(?:명|인)\s*[*×xX]\s*(\d+)\s*회")
_COST_UNIT_RE = re.compile(r"(?:1\s*인당|인당|팀별|팀당|회당|1회당)\s*(?:최대\s*)?(\d[\d,]*)\s*만\s*원")
_COST_PRIZE_RE = re.compile(r"(대상|최우수상?|우수상?|장려상?|입선)\s*(\d+)\s*만\s*원\s*[(（]\s*(\d+)\s*(?:인|명|팀)")
_COST_BURDEN_RE = re.compile(r"제안사\s*(?:에서|가)?\s*(?:모두\s*)?(?:지급|부담)|별도\s*(?:의\s*)?비용\s*(?:지원\s*)?없|추가\s*개설\s*시\s*별도|자체\s*부담|수행사\s*부담")
_COST_WAGE_RE = re.compile(r"(\d+)\s*명[^.\n]{0,30}(?:인건비|최저\s*임금)")
_COST_MUST_RE = re.compile(r"반드시\s*달성|필수\s*달성|미달\s*시\s*(?:추가|재)")


def cost_lines(excerpt: str, budget_won: int | None) -> list[dict[str, str]]:
    """원문 비용 줄 → 검토용 빈칸(공고 확인 · 계산 · 추정 · 담당자 입력 · 3차 지시서 §7). 확정 지출 합과 사업금액 비율, 무료 추가 운영 위험도.
    금액을 짓지 않는다 — 원문 숫자로 계산할 수 있는 것만 「계산」, 수량을 모르면 「담당자 입력」."""
    out: list[dict[str, str]] = []
    fixed = 0
    seen: set[str] = set()
    burdens: list[str] = []

    def add(kind: str, text: str) -> None:
        if text not in seen:
            seen.add(text)
            out.append({"field": COST_FIELD, "why": f"[{kind}] {text}", "section": COST_SECTION})

    for line in (excerpt or "").splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        for match in _COST_PRODUCT_RE.finditer(clean):
            amount = int(match.group(1)) * 10_000 * int(match.group(2)) * int(match.group(3))
            fixed += amount
            add("계산", f"{match.group(0)} = {amount:,}원 — 원문 「{clean[:80]}」")
        prizes = [(m.group(1), int(m.group(2)) * 10_000 * int(m.group(3))) for m in _COST_PRIZE_RE.finditer(clean)]
        if prizes:
            total = sum(amount for _name, amount in prizes)
            fixed += total
            add("계산", f"부상 {' + '.join(f'{name} {amount:,}원' for name, amount in prizes)} = {total:,}원 — 원문 「{clean[:80]}」")
        for match in _COST_UNIT_RE.finditer(clean):
            add("담당자 입력", f"단가 {match.group(0)}(공고 확인) × 수량(인원 · 팀 수 — 담당자 입력) — 원문 「{clean[:80]}」")
        if match := _COST_WAGE_RE.search(clean):
            add("추정", f"{match.group(1)}명 인건비 — 금액은 원문에 없음(기준 임금 · 기간 추정 — 내부 검토) — 원문 「{clean[:80]}」")
        if (burden := _COST_BURDEN_RE.search(clean)) and clean not in burdens:
            burdens.append(clean[max(0, burden.start() - 30): burden.end() + 10].strip())
    if burdens:
        # 제안사 부담 줄은 한 줄로 묶는다(2위 원문 13곳 — 검토 목록이 비용 줄로 넘쳤다)
        more = f" 외 {len(burdens) - 3}곳" if len(burdens) > 3 else ""
        add("공고 확인", f"제안사 부담 · 별도 비용 없음 {len(burdens)}곳 — " + " · ".join(f"「…{b}…」" for b in burdens[:3]) + more)
    if fixed:
        ratio = f" · 사업금액의 {fixed / budget_won * 100:.1f}%" if budget_won else ""
        add("계산", f"원문으로 확정되는 지출 합 {fixed:,}원{ratio} — 나머지 예산으로 인건비 · 운영비가 되는지 확인")
    if re.search(r"추가\s*개설\s*시\s*별도", excerpt or "") and _COST_MUST_RE.search(excerpt or ""):
        add("공고 확인", "추가 개설은 별도 비용 없음 + 목표 반드시 달성 — 목표 미달 때 무료 추가 운영 위험(수행 가능성)")
    return out


def budget_lines(terms: dict[str, Any], *, table: bool) -> list[dict[str, str]]:
    """예산 과업이 있는 공고의 검토용 줄(2.10.0 D3 · 내부 검토 — 제출용에 싣지 않음) — 공고 금액(나라장터 배정예산 · 추정가격 먼저 ·
    없으면 제안요청서 사업금액 글) · 예산 배분안 공급가액이 추정가격과 다르면 알림 · 사업금액(기초금액)과 투찰금액 · 참여 수가 바뀌어도 총액 안.
    금액을 짓지 않는다(공급가액 나누기는 표 끝 줄 `budget_totals` 뿐)."""
    out: list[dict[str, str]] = []

    def add(kind: str, text: str) -> None:
        out.append({"field": COST_FIELD, "why": f"[{kind}] {text}", "section": COST_SECTION})

    assigned, estimated, won = terms.get("assigned_budget"), terms.get("estimated_price"), terms.get("budget_won")
    if assigned and estimated:
        add("공고 확인", f"나라장터 배정예산 {assigned:,}원 · 추정가격 {estimated:,}원(부가세 별도) · 차 {assigned - estimated:,}원")
    elif terms.get("budget"):
        add("공고 확인", f"제안요청서 사업금액 「{terms['budget']}」 — 나라장터 배정예산 · 추정가격은 공고 원본에서 확인하세요")
    if table and won and estimated and terms.get("budget_vat") == "포함" and (supply := won * 10 // 11) != estimated:
        add("공고 확인", f"예산 배분안 소계(공급가액) {supply:,}원은 사업금액에서 부가세 10%를 뺀 값 — 나라장터 추정가격 {estimated:,}원과 다릅니다. "
                       "면세 · 부가세 포함 여부를 확인하고 끝 줄을 고치세요")
    plan = "예산 배분안" if table else "예산 계획"
    add("담당자 입력", f"사업금액(기초금액)과 실제 투찰금액은 다릅니다 — 투찰금액은 가격 제안으로 따로 정하고, {plan}은 투찰금액에 맞춰 같은 구성으로 조정하세요")
    add("담당자 입력", f"{plan}의 과업마다 항목 · 수량 × 단가 · 금액을 채우고 소계 · 부가세 · 합계가 사업금액 안인지 검산하세요 — "
                    "참여 수가 바뀌면 같은 산식에서 단가 · 횟수를 조정해 총액 안에서 유지합니다")
    return out
#: 담당자 보완자료(3차 지시서 §9) — 원문이 요구한 제출 서식 · 입증 자료(붙임 소항목이 없는 목차는 이 이름의 빈칸 묶음으로).
SUPPLEMENT_SECTION = "제출 서류"
#: 붙임 목록에 섞인 원문 문서 이름(공고문의 첨부 목록) — 제출할 서식이 아니다.
#: 붙임 목록의 참고 기준 문서(보안위규 처리기준 · 준수사항 · 회의록 서식) — 낼 서식이 아니다.
_ANNEX_REF_RE = re.compile(r"기준$|준수\s*사항|대상\s*정보|회의록")
_SOURCE_DOC_RE = re.compile(r"제\s*안\s*요\s*청\s*서|입\s*찰\s*공\s*고|공\s*고\s*문|과\s*업\s*지\s*시\s*서|규\s*격\s*서")
SUPPLEMENT_FORM = "서식 첨부"
#: 조견표 「제안서 해당 목차」 — 짝이 없는 정량 항목(제출 서류로 평가)은 빈칸이 아니라 이 글(2.8.0 B3 · 품질 게이트는 참고로만 센다).
EVAL_NONE = "—"


#: 조견표 「제안서 근거(소제목)」 칸에 옮기는 소제목 수 · 다섯 칸 너비(mm · 합 166 — 근거 칸이 가장 넓다 · 2.10.0 T7 m5).
EVAL_HEADS = 3
EVAL_WIDTHS_MM = [27.0, 44.0, 13.0, 32.0, 50.0]  # 「사업수행 능력」 · 머리 「제안서 해당 목차」가 한 줄(한글 2024 로 확인)
#: 정량 항목 ↔ 공고문 제출서류 짝 — 이름 한글 두 글자 묶음이 이만큼 겹칠 때만(「신용평가등급」 ↔ 「기업신용등급평가서」 = 신용 · 평가 · 등급 · m6).
PAPER_MATCH_BIGRAMS = 3
#: 서류 이름 — 「1부」 · 「1식」 · 괄호 · 「:」 앞까지(「⑤ 국세, 지방세 완납증명서(최근 1개월 …) 1부」 → 「국세, 지방세 완납증명서」).
#: 「각 1부」 · 「각각 1통」의 「각」도 뗀다(「기타문서 각 1부」 → 「기타문서」 · 2.11.0 T6a) — 띄어 쓴 「각」만(「보안각서 1부」는 그대로).
_PAPER_NAME_END_RE = re.compile(r"\s*[(（:：]|\s+각(?:각)?\s*\d+\s*[부식통]|\s*\d+\s*[부식통]")


def _eval_blank(item: dict[str, Any]) -> str:
    return EVAL_NONE if item.get("kind") == "정량" else HUMAN_INPUT


def _bigrams(text: str) -> set[str]:
    return {run[i:i + 2] for run in re.findall(r"[가-힣]+", text) for i in range(len(run) - 1)}


def paper_for(name: str, papers: list[dict[str, Any]]) -> str | None:
    """정량 평가 항목 → 「제출 서류 ⑩ 기업신용등급평가서」(공고문 제출서류 · `submission_papers`) — 이름 두 글자 묶음이
    `PAPER_MATCH_BIGRAMS` 이상 겹치는 서류 중 가장 많이 겹치는 것(같으면 앞 서류). 하위 서류는 「가. 1)」 번호. 없으면 None."""
    want = _bigrams(name)
    best: tuple[int, str] | None = None
    for found in papers:
        for item in found.get("items") or []:
            for no, text in [(item["no"], item["text"]), *((f"{item['no']} {sub['no']}", sub["text"]) for sub in item.get("subs") or [])]:
                paper = _PAPER_NAME_END_RE.split(str(text), maxsplit=1)[0].strip()
                hit = len(want & _bigrams(paper))
                if paper and hit >= PAPER_MATCH_BIGRAMS and (best is None or hit > best[0]):
                    best = (hit, f"제출 서류 {no} {paper}")
    return best[1] if best else None


#: 검토 「제출 서류」 묶음(2.10.0 T8 · submit1) — 입찰공고문 서류 한 줄 · ※ 제출 방법 한 줄.
PAPER_FIELD = "공고 제출서류"
PAPER_NOTE_FIELD = "제출 방법"
#: 입찰공고문 제출서류를 하나도 읽지 못한 새 초안(2.11.0 T6b) — 검토 목록 한 줄 · 게이트 PAPERS_UNREAD(보통 · 판정 밖) · 보고서 엑셀이 같은 글.
#: 제출서류는 초안을 쓸 때만 읽으므로 2.10.0 판으로 쓴 초안(papers [])은 새 머리 꼴(1822113)이어도 0건 — 다시 쓰라는 말을 끝에 둔다.
PAPERS_UNREAD_NOTE = ("입찰공고문에서 제출서류 목록을 찾지 못했습니다(「제안요청서 참조」 · 나라장터 온라인 제출 안내뿐 · 표 꼴 · "
                      "입찰공고문을 받지 않은 공고) — 제안요청서 · 공고문의 제출 서류 · 파일 구분 줄을 직접 확인하세요 · "
                      "앱 2.11.0 전에 쓴 초안이면 초안을 다시 쓰면 읽힐 수 있습니다")


def papers_unread(draft: dict[str, Any]) -> bool:
    """제출서류 칸이 있는데 비었나 — 칸이 없는 옛 초안(2.10.0 전)은 아니다(지금 글 그대로)."""
    return isinstance(draft.get("papers"), list) and not draft["papers"]
#: 회사 입찰 자격 자료의 증명서 칸(화면 경로) — 유효기간을 적는 곳.
CREDENTIALS_PATH = "회사자료 › 입찰 자격 자료 › 준비 상태"
#: 유효기간을 짝지을 서류 — 이름이 확인서 · 증명서 · 인증서 · 등록증 · 평가서로 끝날 때만(「서약서, 보안각서, 확인서, 청렴계약이행 서약서」 · 지정양식 · 보증증권은 짝 없음).
#: 「서약서」가 든 묶음(「입찰업체 서약서 및 공동책임 확인서」 · 회사가 서명하는 서식)도 짝 없음 — T6a 로 「각」이 떨어져 확인서로 끝나게 된 이름.
_PAPER_CERT_RE = re.compile(r"(?:확인서|증명서|인증서|등록증|평가서|면허증)$")
_PAPER_PLEDGE = "서약서"
#: 중소기업 · 소상공인 확인서(짝은 `eligibility_engine.sme_credential` 한 곳) · 그중 소기업 · 소상공인을 요구하는 꼴(「중소기업」의 「소기업」은 아님).
_PAPER_SME_RE = re.compile(r"(?:중|소)\s*기업|소상공인")
_PAPER_SMALL_RE = re.compile(r"(?<!중)소\s*기업|소상공인")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_RANGE_RE = re.compile(r"([①-⑳])\s*[~∼～\-–]\s*([①-⑳])")
PAPER_FILE_CHARS = 80


def _paper_file(no: str, notes: list[str]) -> str:
    """제출 파일 구분 — 그 번호를 낱개(「⑪제안서 pdf파일」)나 범위(「①~⑩」)로 가리킨 첫 ※ 줄(없으면 빈 글)."""
    if no not in _CIRCLED:
        return ""
    at = _CIRCLED.index(no)
    for note in notes:
        if no in note or any(_CIRCLED.index(a) <= at <= _CIRCLED.index(b) for a, b in _CIRCLED_RANGE_RE.findall(note)):
            return note[:PAPER_FILE_CHARS]
    return ""


def paper_valid(name: str, credentials: list[Any], *, base: str, when: str) -> str:
    """서류 이름 → 회사 입찰 자격 자료(Credential) 유효기간 말 — 「회사자료 「중소기업확인서」(소기업) 유효기간 2027-03-31 · 입찰 마감 전일(…) 기준 유효」.
    증명서 꼴이 아니면 빈 글 · 짝 줄이 없으면 「… 준비 상태에 없음 — 유효기간 확인」. 짝은 중소기업 · 소상공인 확인서면 `sme_credential`, 그 밖은
    이름(4자 이상) 포함 짝 — 엉뚱한 짝을 짓지 않게 애매하면 「없음」."""
    from app.services import eligibility_engine

    if not _PAPER_CERT_RE.search(name) or _PAPER_PLEDGE in name:
        return ""
    if _PAPER_SME_RE.search(name) and name.endswith("확인서"):
        row = eligibility_engine.sme_credential(credentials)
    else:
        key = re.sub(r"[^0-9A-Za-z가-힣]", "", name)
        row = next((c for c in credentials if len(other := re.sub(r"[^0-9A-Za-z가-힣]", "", c.name or "")) >= 4
                    and (other in key or key in other)), None)
    if row is None:
        return f"{CREDENTIALS_PATH}에 없음 — 유효기간 확인"
    named = f"회사자료 「{row.name}」" + (f"({row.grade})" if row.grade else "")
    if row.held is False:
        return f"{named} 없음으로 적힘 — 발급 확인"
    gap = ""
    if _PAPER_SMALL_RE.search(name) and _PAPER_SME_RE.search(name):  # 소기업 · 소상공인 확인서를 요구 — 확인서 구분(Credential.grade)
        gap = (" · 확인서 구분이 중기업 — 소기업 · 소상공인 확인서가 아닙니다" if row.grade == "중기업"
               else " · 기업 구분 모름(소기업 · 소상공인인지 확인)" if not row.grade else "")
    if row.valid_until is None:
        return f"{named} 유효기간 모름 — {CREDENTIALS_PATH}에 적으세요{gap}"
    state = "유효" if row.valid_until.isoformat() >= base else "지남"
    return f"{named} 유효기간 {row.valid_until.isoformat()} · {when}({base}) 기준 {state}{gap}"


def paper_rows(papers: list[dict[str, Any]], credentials: list[Any], *, deadline: str | None,
               today: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """입찰공고문 제출서류(`submission_papers` · 초안 `papers`) → (서류 줄, ※ 줄). 서류 줄 {no, name, need(원문), file(제출 파일 구분 ※ 줄),
    valid(유효기간 말), where(문서 · 쪽)} — 하위 서류(「가. 1)」)도 한 줄. 유효기간 기준일은 입찰 마감 전일(공고 「입찰서 제출 마감일 전일까지
    발급된 … 유효기간 내」) · 마감을 모르면 오늘. 새 판정은 없다(검토 목록 · 보고서만 · D10)."""
    if deadline:
        try:
            base, when = (datetime.fromisoformat(deadline).astimezone(plan_export_service.KST).date() - timedelta(days=1)).isoformat(), "입찰 마감 전일"
        except ValueError:
            base, when = today, "오늘"
    else:
        base, when = today, "오늘"
    rows: list[dict[str, str]] = []
    notes: list[dict[str, str]] = []
    for found in papers or []:
        where = f"{found.get('document')} {found.get('page')}쪽"
        for item in found.get("items") or []:
            for no, text in [(item["no"], item["text"]), *((f"{item['no']} {sub['no']}", sub["text"]) for sub in item.get("subs") or [])]:
                name = _PAPER_NAME_END_RE.split(str(text), maxsplit=1)[0].strip() or str(text)
                rows.append({"no": no, "name": name, "need": str(text), "file": _paper_file(item["no"], found.get("notes") or []),
                             "valid": paper_valid(name, credentials, base=base, when=when), "where": where})
        notes += [{"text": str(note), "where": where} for note in found.get("notes") or []]
    return rows, notes


def paper_blanks(rows: list[dict[str, str]], notes: list[dict[str, str]], blanks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """검토 「제출 서류」 묶음 — 서류마다 「공고 제출서류」(필요한 자료 = 서류 이름) · ※ 줄마다 「제출 방법」. 원문 붙임 서식 빈칸(「서식 첨부」)이
    이미 그 서류를 가리키면 뺀다 — 서식 이름(「<서식 n>」 뗀)이 서류 이름과 같거나, 5자 이상 서류 이름을 통째로 품을 때만(「기술제안서 요약표」가
    「제안서」를 품는다고 제안서 줄을 빼지 않게 · T8 검토)."""
    def key(value: Any) -> str:
        return re.sub(r"[^0-9가-힣]", "", str(value))

    forms = [re.sub(r"^(?:서식|별지|별첨|붙임)[0-9]*", "", key(str(b.get("why")).split(" — ")[0]))
             for b in blanks if b.get("field") == SUPPLEMENT_FORM]

    def taken(name: str) -> bool:
        return bool(name := key(name)) and any(name == form or (len(name) >= 5 and name in form) for form in forms)

    out = [{"field": PAPER_FIELD, "why": f"{row['no']} {row['need']} — {row['where']}" + (f" · {row['valid']}" if row["valid"] else ""),
            "section": SUPPLEMENT_SECTION, "proof": row["name"]}
           for row in rows if not taken(row["name"])]
    return out + [{"field": PAPER_NOTE_FIELD, "why": f"※ {note['text']} — {note['where']}", "section": SUPPLEMENT_SECTION} for note in notes]


#: 원문이 제안서 표지 서식을 정한 공고(`format.cover_form` · 2.11.0 T3b) — 앱 표지는 앱 꼴이라 사람이 한글에서 바꾼다(검토 목록 한 줄).
COVER_FORM_FIELD = "표지 서식"
COVER_FORM_NOTE = "표지 — 원문 서식이 정한 칸 · 순서로 한글에서 바꾸세요(앱 표지는 앱 꼴)"


def cover_form_blanks(draft: dict[str, Any]) -> list[dict[str, str]]:
    """검토 목록 「표지 서식」 한 줄 — 원문 서식 줄 · 자리. 칸이 없는 옛 초안 · 서식이 없는 공고는 없음."""
    found = (draft.get("format") or {}).get("cover_form")
    if not isinstance(found, dict) or not found.get("line"):
        return []
    where = f" — {found['document']} {found['page']}쪽" if found.get("document") and found.get("page") else ""
    return [{"field": COVER_FORM_FIELD, "why": f"{COVER_FORM_NOTE} — 원문 「{found['line']}」{where}", "section": "표지"}]


#: 조견표 근거 소제목 고르기에서 뺄 흔한 낱말(평가 항목 이름 · 소제목에 두루 나와 짝을 가르지 못한다).
_HEAD_GENERIC = frozenset("방안 계획 관리 운영 제안 사업 능력 역량 적정성 구체성 우수성 타당성 제시 수행 및 등 위한 대한 체계 방법".split())


def _heads_of(keys: list[str], sections: list[dict[str, Any]], item: dict[str, Any] | None = None) -> str:
    """짝 목차(소항목 · 대항목 열쇠)의 본문 「○」 소제목 — 기호를 떼고 「 · 」로(본문 글 그대로 · AI 새 글 없음).
    평가 항목(이름 · 기준)과 낱말이 겹치는 소제목을 겹친 수 순으로 `EVAL_HEADS` 개(11-14 평가 — 대항목에 짝지은 여러 행이 그 대항목의 앞 소제목
    셋을 똑같이 받아 엉뚱한 문단을 가리켰다). 겹치는 것이 없으면 소항목 열쇠 짝은 그 소항목 앞 소제목, 대항목 열쇠 짝뿐이면 빈 글(가리킬 곳을 짓지 않는다)."""
    heads: list[tuple[str, bool]] = []  # (소제목, 소항목 열쇠로 찾음)
    for key in keys:
        for entry in sections:
            own = key == entry.get("key")
            if not own and key != entry.get("major_key"):
                continue
            for sentence in entry.get("sentences") or []:
                text = str(sentence.get("text") or "").strip()
                if plan_export_service._subheading(text):
                    heads.append((plan_export_service._BULLET_HEAD.sub("", text).strip(), own))
    seen: dict[str, bool] = {}
    for head, own in heads:
        if head:
            seen[head] = seen.get(head, False) or own
    if item:
        want = _words(f"{item.get('name') or ''} {' '.join(item.get('criteria') or [])}") - _HEAD_GENERIC
        scored = [(len(want & (_words(head) - _HEAD_GENERIC)), index, head) for index, head in enumerate(seen)]
        hits = [head for score, _index, head in sorted(scored, key=lambda s: (-s[0], s[1])) if score > 0]
        if hits:
            return " · ".join(hits[:EVAL_HEADS])
        return " · ".join([head for head, own in seen.items() if own][:EVAL_HEADS])
    return " · ".join(list(seen)[:EVAL_HEADS])


def evaluation_table(form: dict[str, Any], evaluation: dict[str, Any], covered: dict[str, list[str]],
                     sources: dict[str, str] | None = None, *, sections: list[dict[str, Any]] | None = None,
                     papers: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """기술능력 평가항목별 조견표 — 평가항목 · 세부평가항목 · 배점 · 제안서 해당 목차(AI 가 다뤘다고 적은 소항목).
    짝이 없으면 정성은 「(담당자 입력)」(품질 게이트 차단) · 정량은 공고문 제출서류에서 이름이 겹치는 서류(`papers` · `paper_for` · 없으면
    「—」 `EVAL_NONE`). `sections`(쓴 본문)를 주면 다섯째 칸 「제안서 근거(소제목)」 — 짝 목차의 「○」 소제목 앞 셋(정량은 「—」 · 짝 없으면 빈 글 ·
    2.10.0 T7 m5 · 게이트 · 옛 초안 정리는 넷째 칸만 읽는다). `sources` — 행마다 짝 출처(ai · title · heading · None — 진단 · 품질 게이트용 ·
    문서에는 싣지 않는다 · 2.8.0 B4)."""
    items = evaluation.get("items") or []
    if not items:
        return None
    rows = []
    for item in items:
        keys = covered.get(item["name"], [])
        mapped = ", ".join(dict.fromkeys(unit_number(form, key) for key in keys))
        if not mapped and item.get("kind") == "정량":
            mapped = paper_for(item["name"], papers or []) or ""
        row = [item.get("area") or "", item["name"], f"{item['points']}점" if item.get("points") is not None else "", mapped or _eval_blank(item)]
        if sections is not None:
            row.append(_heads_of(keys, sections, item) if keys else EVAL_NONE if item.get("kind") == "정량" else "")
        rows.append(row)
    table = {"key": EVAL_TABLE_KEY, "title": EVAL_TITLE, "columns": ["평가항목", "세부평가항목", "배점", "제안서 해당 목차"],
             "rows": rows, "sources": [(sources or {}).get(item["name"]) if covered.get(item["name"]) else None for item in items],
             "by": "rules", "human_only": False, "section": "EVAL", "item": None}
    if sections is not None:
        table["columns"].append("제안서 근거(소제목)")
        table["widths_mm"] = list(EVAL_WIDTHS_MM)
    return table


def _merge_blanks(blanks: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for blank in blanks:
        key = (str(blank.get("section")), str(blank.get("field")), str(blank.get("why")))
        if key not in seen:
            seen.add(key)
            out.append(blank)
    return out


# ---------------------------------------------------------------------------
# 원문 · 저장 · 읽기
# ---------------------------------------------------------------------------


#: 원문 종류(파일 이름으로) — rfp 제안요청서 · task 과업지시서 · spec 규격서(사전규격) · notice 입찰공고문 · guide 제안서 작성 · 평가 방법 · other.
_ROLE_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("guide", re.compile(r"제안서(?:작성|평가)")),
    ("rfp", re.compile(r"제안요청서")),
    ("task", re.compile(r"과업(?:지시|내용)서")),
    ("spec", re.compile(r"규격서|사양서|시방서")),
    ("notice", re.compile(r"입찰공고|공고서|공고문|재공고")),
)
NO_RFP_MESSAGE = "제안요청서를 받지 못해 제안서를 쓸 수 없습니다 — 공고 분석을 다시 하거나 나라장터에서 제안요청서를 확인하세요"


def _doc_role(name: str) -> str:
    words = re.sub(r"\s+", "", name or "")
    return next((role for role, pattern in _ROLE_WORDS if pattern.search(words)), "other")


def _plain_name(name: str) -> str:
    """캐시 파일 이름 앞 번호(「1_」)를 뗀 이름 — 옛 분석은 문서 이름에 이 번호까지 적었다(11-06 · notice_qa 와 같은 규칙)."""
    return re.sub(r"^\d+_", "", name or "")


def cached_source(procurement_id: str, file_name: str):
    """받아 둔 원문 파일 — 이름 그대로, 없으면 앞 번호를 뗀 이름으로 한 번 더(공고문 질문하기 · 제안서 쓰기가 함께 쓴다)."""
    return _cached_source(procurement_id, file_name) or _cached_source(procurement_id, _plain_name(file_name))


def _cached_source(procurement_id: str, file_name: str):
    """분석에 쓴 첨부를 받아 둔 파일 — 첨부 목록을 다시 만들지 않고 캐시 폴더에서 이름으로 찾는다(11-03 검토: 사전규격 저장본이
    30일 뒤 정리되면 목록에서 규격서가 빠져 받아 둔 파일이 있어도 쓰기가 막혔다). HTML 안내 화면 · 빈 파일은 없음으로."""
    from app.services import attachment_service

    folder = attachment_service.CACHE_DIR / attachment_service.sanitize_dir_name(procurement_id)
    pattern = re.compile(rf"^\d+_{re.escape(attachment_service.sanitize_file_name(file_name))}$")
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if pattern.match(path.name) and path.stat().st_size > 0 and attachment_service.html_page_title(path, file_name) is None:
            return path
    return None


def source_documents(procurement_id: str, analysed: str | None = None) -> list[dict[str, Any]]:
    """그 공고의 받아 둔 원문을 모두 읽는다(네트워크 없이 · 11-06) — [{name, role, pages: [(쪽, 글)], text}]. 분석 문서가 첫째.

    분석이 과업지시서를 골랐어도 같은 폴더의 제안요청서(1718593) · 압축 안 「제안서 작성방법」(1697240)에 목차 · 평가표가 있다.
    압축은 안의 문서를 모두 꺼낸다. 읽지 못하는 파일 · HTML 안내 화면은 건너뛴다."""
    from app.services import attachment_service, document_extractor, rfp_parser

    files: list[tuple[Any, str]] = []
    if rfp_parser.is_fixture(procurement_id):
        fixture = rfp_parser.get_fixture(procurement_id).path
        files.append((fixture, fixture.name))
    else:
        folder = attachment_service.CACHE_DIR / attachment_service.sanitize_dir_name(procurement_id)
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            if path.is_file() and path.stat().st_size > 0 and attachment_service.html_page_title(path, path.name) is None:
                files.append((path, _plain_name(path.name)))
    docs: list[dict[str, Any]] = []
    for path, name in files:
        try:
            if document_extractor.detect_format(path) == "zip":
                extracted = document_extractor.extract_zip_all(path, file_name=name)
            else:
                extracted = [document_extractor.extract_document(path, file_name=name)]
        except Exception:  # noqa: BLE001 — 깨진 첨부 하나가 제안서 쓰기를 막지 않게(그 문서만 뺀다 · 공고문 질문하기와 같다)
            logger.warning("받아 둔 원문을 읽지 못했습니다: %s", path.name, exc_info=True)  # 화면 문장 아님
            continue
        for doc in extracted:
            if doc.text.strip():
                docs.append({"name": doc.file_name, "role": _doc_role(doc.file_name.split(" > ")[-1]), "format": doc.doc_format,
                             "pages": [(page.page, page.text) for page in doc.pages], "text": doc.text})
    if analysed:
        outer, _, inner = analysed.partition(" > ")
        # 문서 이름은 캐시 번호를 뗀 이름 — 분석 이름이 번호까지 적었든(「2_2_과업지시서…」) 아니든 맞춘다
        keys = {attachment_service.sanitize_file_name(outer), attachment_service.sanitize_file_name(_plain_name(outer))}
        for doc in docs:
            d_outer, _, d_inner = doc["name"].partition(" > ")
            doc["analysed"] = attachment_service.sanitize_file_name(d_outer) in keys and (not inner or d_inner == inner)
        docs.sort(key=lambda doc: not doc["analysed"])
    return docs


def source_gap(draft: dict[str, Any], procurement_id: str, attachments: list[str] | None) -> dict[str, list[str]] | None:
    """사전규격 규격서만 읽고 쓴 초안인데 본공고 자기 첨부가 따로 있음 — {missing: 아직 안 받은 첨부, received: 초안을 쓴 뒤 받은 첨부,
    unread: 쓰기 전부터 받아 두었는데 글을 읽지 못한 첨부(그림 PDF · 깨진 파일 — 다시 써도 읽지 못한다)}.

    attachments 는 본공고 첨부 이름(모르면 None — 검사하지 않음). 같은 문서의 .hwpx · .pdf 는 하나로 묶는다. 읽은 원문 목록(`sources`)이 없는
    옛 초안(2.11.0 전)은 검사하지 않는다 — 「제출서류가 빔」으로 가늠하면 제출서류 꼴만 다른 공고도 걸렸다(2.11.0 검토). 네트워크 없음."""
    from app.services import attachment_service, prespec_service

    names = [name for name in attachments or [] if name and not prespec_service.is_spec_doc(name)]
    if not names:
        return None
    sources = draft.get("sources")
    if not sources or not all(prespec_service.is_spec_doc(name) for name in sources):
        return None
    try:
        written = datetime.fromisoformat(str(draft.get("executed_at"))).timestamp()
    except ValueError:
        written = None
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(re.sub(r"\.[^.]+$", "", attachment_service.sanitize_file_name(name)), []).append(name)
    gap: dict[str, list[str]] = {"missing": [], "received": [], "unread": []}
    for group in groups.values():
        paths = [path for name in group if (path := cached_source(procurement_id, name))]
        if not paths:
            gap["missing"].append(group[0])
        elif written is not None and all(path.stat().st_mtime <= written for path in paths):
            gap["unread"].append(group[0])  # 쓸 때 이미 있었는데 읽은 원문 목록에 없다 — 글을 못 뽑은 파일
        else:
            gap["received"].append(group[0])
    return gap


def load_documents(procurement_id: str) -> tuple[Any, list[dict[str, Any]]]:
    """(분석 결과, 받아 둔 원문 전부) — 분석이 없으면 SourceMissingError · 공고서뿐이면 NoRfpError(입찰 절차 조항만 있어 제안서가 되지 않는다)."""
    from app.services import rfp_parser

    try:
        parsed = rfp_parser.load_generated(procurement_id)
    except rfp_parser.RfpNotParsedError as exc:
        raise SourceMissingError("공고 분석을 먼저 하세요 — 제안요청서를 읽어야 제안서를 씁니다") from exc
    if parsed.document_role == "notice":
        raise NoRfpError(NO_RFP_MESSAGE)
    outer = parsed.document.split(" > ")[0]
    if not rfp_parser.is_fixture(procurement_id) and cached_source(procurement_id, outer) is None:
        raise SourceMissingError("분석에 쓴 제안요청서 파일이 이 서버에 없습니다 — 공고 분석을 다시 하세요")
    docs = source_documents(procurement_id, parsed.document)
    if not any(doc.get("analysed") for doc in docs):  # 분석 문서를 못 읽었으면 공고서 같은 다른 문서로 대신하지 않는다
        raise SourceMissingError("분석에 쓴 제안요청서 파일을 읽지 못했습니다 — 공고 분석을 다시 하세요")
    return parsed, docs


def load_source(procurement_id: str, view: Any) -> dict[str, Any]:
    """분석에 쓴 원문과 같은 공고의 받아 둔 문서를 모두 읽는다.

    text(발췌 · 숫자 대조)는 분석 문서 — 분석이 제안요청서가 아닌 문서를 골랐고 제안요청서가 따로 있으면 제안요청서. 목차 · 평가표 ·
    형식 규정은 docs 전체에서 찾는다(`locate_outline` · `locate_evaluation` · `read_format`)."""
    from app.services import eligibility_engine, home_agencies

    parsed, docs = load_documents(procurement_id)
    primary = docs[0]
    if primary["role"] != "rfp":
        primary = next((doc for doc in docs if doc["role"] == "rfp"), primary)
    notice = view.notice
    return {
        "procurement_id": procurement_id,
        "title": notice.title,
        "agency": home_agencies.display_agency(notice.agency, (notice.raw_data or {}).get("demand_institution")),
        "notice_no": getattr(notice, "notice_no", None),
        "notice_url": getattr(notice, "source_url", None),
        "notice_budget": notice_budget(getattr(notice, "raw_data", None)),  # 배정예산 · 추정가격(11-13)
        # 나라장터 공동수급 칸이 「불허」 — 단독 수행 문장은 회사 결정이 아니라 공고 조건(2.10.0 m0 · 모르면 지금 그대로)
        "joint_solo": eligibility_engine.joint_allowed(getattr(notice, "raw_data", None) or {}) is False,
        # 입찰 마감(나라장터 `bidClseDt`) — 공고 제출서류 유효기간 기준일(마감 전일 · 2.10.0 T8)
        "deadline": deadline.isoformat() if (deadline := getattr(notice, "deadline_at", None)) else None,
        # 참가자격등록 마감(`bidQlfctRgstDt`) — 검증 보고서 엑셀 「제출 서류」 칸(T8 검토 · 없으면 None)
        "qualification_deadline": qualify.isoformat() if (qualify := g2b_mapper.parse_datetime(
            str((getattr(notice, "raw_data", None) or {}).get("qualification_deadline") or ""))) else None,
        "text": primary["text"],
        "document": parsed.document,
        "requirement_set_hash": parsed.requirement_set_hash,
        "docs": docs,
    }


def read_layout(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """제안서 양식 — 목차(못 읽으면 표준 목차) · 평가표 · 형식 규정 · 경고. 쓰기(`generate`)와 미리 보기(`outline_preview`)가 같은 값을 쓴다.
    목차 · 평가표를 못 읽은 것은 화면이 목차 줄 · 평가표 줄로 알린다(경고에 다시 적지 않음) — 목차 머리를 찾은 곳은 `outline_found_at`."""
    located = locate_outline(docs)
    source = "rfp" if located["outline"] else "unread" if located["found_head"] else "standard"
    evaluation = locate_evaluation(docs)
    fmt = read_format(docs)
    warnings: list[str] = []
    if any(doc["role"] == "spec" and "사전규격" in (doc.get("name") or "") for doc in docs[:1]):
        warnings.append("원문이 사전규격 규격서입니다 — 본공고 제안요청서와 다를 수 있습니다")
    return {
        "outline_source": source,
        "outline": located["outline"] or [dict(m) for m in STANDARD_OUTLINE],
        "outline_where": located["where"],
        "outline_found_at": located["found_at"] if source == "unread" else None,
        "outline_rejected": [{"head": r["head"], "page": r["page"], "reason": r["reason"]} for r in located["rejected"]],
        "evaluation": evaluation,
        "format": fmt,
        "warnings": warnings,
    }


def outline_preview(procurement_id: str, view: Any) -> dict[str, Any]:
    """쓰기 전에 「이 양식으로 씁니다」 — AI 없이 원문만 읽는다(11-06 A-6). SourceMissingError · NoRfpError 는 그대로 던진다."""
    del view  # 라우트가 공고를 확인한 뒤 부른다 — 양식은 받아 둔 원문만 본다
    _parsed, docs = load_documents(procurement_id)
    layout = read_layout(docs)
    evaluation = layout["evaluation"]
    numbers, renumbered = major_numbers(layout["outline"])  # 쓰기(`build_form`)와 같은 번호(2.8.0 B5)
    return {
        "procurement_id": procurement_id,
        "outline_source": layout["outline_source"],
        "outline": [{"no": no, "title": m["title"], "items": [{"no": i["no"], "title": i["title"]} for i in m.get("items") or []]}
                    for no, m in zip(numbers, layout["outline"])],
        "renumbered": renumbered,
        "outline_where": layout["outline_where"],
        "outline_found_at": layout["outline_found_at"],
        "outline_rejected": layout["outline_rejected"],
        "evaluation": {"items": [{"area": i.get("area"), "name": i["name"], "points": i.get("points"), "kind": i.get("kind", "정성")}
                                 for i in evaluation.get("items") or []],
                       "total": evaluation.get("total"), "where": evaluation.get("where")},
        "format": layout["format"],
        "documents": [{"name": doc["name"], "role": doc["role"], "pages": len(doc.get("pages") or [])} for doc in docs],
        "warnings": layout["warnings"],
    }


def _public_path(procurement_id: str):
    from app.services import proposal_service

    return proposal_service.PROPOSALS_DIR / f"{procurement_id}.bid_plan.json"


#: 덮어쓴 옛 초안을 두는 폴더(공고 분석 폴더 안 · 사내 범위만).
VERSIONS_DIR = "bid_plan_versions"


def save(draft: dict[str, Any], *, context: AnalysisContext | None, procurement_id: str) -> tuple[dict[str, Any], bool]:
    """(화면에 보일 초안, 있던 AI 초안을 남겼는가). 새 초안에 AI 문장이 하나도 없고 있던 초안이 AI 초안이면 덮어쓰지 않는다
    (사용 한도 · 로그인 끊김으로 모두 실패한 다시 쓰기가 다 쓴 초안을 빈칸 초안으로 바꿨다 · 11-03 검토). 덮어쓸 때는 옛 판을 보관한다."""
    try:
        previous = load(procurement_id, context=context)
    except BidPlanNotGeneratedError:
        previous = None
    if previous and previous.get("generated_by") == "llm" and draft.get("generated_by") != "llm":
        note = draft.get("llm_note") or "AI 문장이 없습니다"
        return {**previous, "llm_note": f"새 AI 초안을 쓰지 못해 있던 AI 초안을 그대로 둡니다 — {note}"}, True
    if previous and analysis_store.is_private(context):
        stamp = re.sub(r"[^0-9A-Za-z]+", "-", str(previous.get("executed_at") or "old")).strip("-")
        storage.write_json_atomic(analysis_store.private_dir(context, procurement_id) / VERSIONS_DIR / f"{stamp}.json", previous)
    analysis_store.write_json(context, procurement_id, draft, public_path=_public_path(procurement_id), file_name=FILE_NAME)
    return draft, False


def load(procurement_id: str, *, context: AnalysisContext | None) -> dict[str, Any]:
    payload, _legacy = analysis_store.load_json(context, procurement_id, public_path=_public_path(procurement_id), file_name=FILE_NAME)
    if not payload or not payload.get("sections"):
        raise BidPlanNotGeneratedError(procurement_id)
    return payload


def stale(draft: dict[str, Any], procurement_id: str) -> bool:
    """분석이 바뀌었나(제안요청서를 다시 읽음) — 초안을 만든 뒤 요구사항 집합이 달라지면 참."""
    from app.services import rfp_parser

    try:
        current = rfp_parser.load_generated(procurement_id).requirement_set_hash
    except Exception:  # noqa: BLE001 — 분석이 없으면 판단하지 않는다
        return False
    return bool(draft.get("requirement_set_hash") and current and draft["requirement_set_hash"] != current)


def settle_eval_map(view: dict[str, Any]) -> dict[str, Any]:
    """옛 초안(2.8.0 전) 조견표 — 짝이 없는 정량 항목의 「(담당자 입력)」을 「—」로(`EVAL_NONE` · 읽을 때만 · 저장본은 그대로)."""
    kinds = {str(item.get("name")): item.get("kind") for item in ((view.get("form") or {}).get("evaluation") or {}).get("items") or []}
    tables = []
    for table in view.get("tables") or []:
        if table.get("key") == EVAL_TABLE_KEY:
            table = {**table, "rows": [[*row[:3], EVAL_NONE, *row[4:]] if len(row) >= 4 and kinds.get(str(row[1])) == "정량"
                                       and HUMAN_INPUT_RE.search(str(row[3])) else row for row in table.get("rows") or []]}
        tables.append(table)
    return {**view, "tables": tables}


def _company_evidence(context: AnalysisContext) -> dict[str, Any]:
    """근거 상태를 셀 회사 자료(읽기만) — 입찰 자격 자료(인증 유효기간) · 실적 원장 전체 행(공용 데모는 원장 없음)."""
    from app.services import delivery_capacity_service, performance_match_service

    ledger = performance_match_service.load_ledger_for(context)
    return {"capacity": delivery_capacity_service.load(context.organization_id).model_dump(mode="json"),
            "ledger_rows": [row for row in (ledger or {}).get("rows") or [] if isinstance(row, dict)]}


def _eligibility(procurement_id: str, context: AnalysisContext) -> Any:
    """입찰 분석 참가 자격 판정(「참여」 저장 거절과 같은 함수 · 네트워크 없음). 직접 넣은 공고는 None(결정 길도 따로 본다) ·
    판정 엔진 예외는 제안서 결함이 아니라 「판정 못 함」(`ELIGIBILITY_ERROR` — 게이트를 막지 않음 · 2.11.0 D3)."""
    from app.services import bid_quality_gate, eligibility_engine

    if procurement_id.startswith("manual-"):
        return None
    try:
        return eligibility_engine.offline_report(procurement_id, context)
    except Exception:  # noqa: BLE001 — 자격 판정 하나가 멀쩡한 제안서 승인을 막지 않게(D3)
        logger.exception("참가 자격 판정을 실행하지 못했습니다 (procurement_id=%s)", procurement_id)
        return bid_quality_gate.ELIGIBILITY_ERROR


def read_view(draft: dict[str, Any], *, context: AnalysisContext, procurement_id: str) -> dict[str, Any]:
    """화면 · 내려받기가 읽는 초안 — 일반현황 칸은 회사자료로 채우고(저장본에는 없다) 제출 전 채울 칸 수 · 낡음 ·
    품질 게이트(`quality` · 저장하지 않는 계산값 · 2.7.0)를 붙인다. 게이트가 예외를 내면 통과가 아니라 차단(GATE_ERROR · 2.8.0 B1)."""
    from app.services import bid_quality_gate, plan_export_service, plan_fill_service

    filled = settle_eval_map(plan_fill_service.fill_for(draft, context.organization_id, context.evidence_scope))
    # 2.9.0 전 초안의 단계 수 경고는 입찰 일정표(과업 행)에 맞지 않아 끈 검사다 — 화면 문장 경고 · 게이트가 같은 값을 보게 읽을 때 뺀다
    filled["sections"] = [{**entry, "sentences": [{**x, "flags": [f for f in x.get("flags") or [] if not plan_draft_service._STEP_FLAG_RE.match(str(f))]}
                                                  for x in entry.get("sentences") or []]} for entry in filled.get("sections") or []]
    values = plan_fill_service.company_values(context.organization_id, context.evidence_scope)
    company = values.get("name")
    draft_hash = bid_quality_gate.draft_hash(draft)
    view = {**filled, "company_name": company, "notice_no": draft.get("notice_no")}
    try:  # 공고 대조 · 표지 · 빈칸 셈 · 낡음 · 게이트 — 어디서 예외가 나도 500 이 아니라 차단(2.8.0 검토)
        notice = bid_quality_gate.stored_notice(procurement_id)  # 받아 둔 공고 목록에서(네트워크 없음) — 없으면 None
        view["notice_no"] = view["notice_no"] or (notice or {}).get("notice_no")
        # 표지 「공고 원문」 — 받아 둔 공고의 주소가 먼저, 없으면 초안을 쓸 때 남긴 주소(옛 초안은 저장본에서만 · 2.9.1)
        view["notice_url"] = (plan_export_service.official_link((notice or {}).get("url"))
                              or plan_export_service.official_link(draft.get("notice_url")))
        view["terms"] = draft_terms(view)  # 옛 초안은 협약 기간 글에서(2.8.0 B6)
        meta = export_meta(view, company=company)
        view["submit_blanks"] = plan_export_service.submit_blank_count(view, view.get("form") or {}, meta)
        view["stale"] = stale(draft, procurement_id)
        view["source_gap"] = source_gap(draft, procurement_id, (notice or {}).get("attachments"))
        # 인용한 회사 근거의 상태(실적 원장 · 인증 유효기간 — 회사 자료를 읽는 곳이 여기라 계산해 넘긴다 · 2.8.0 B7)
        company_rows = _company_evidence(context)
        evidence = bid_quality_gate.evidence_status(view, **company_rows)
        # 입찰공고문 제출서류 — 유효기간은 지금 회사 입찰 자격 자료로(초안을 쓴 날 값이 아니라 · 2.10.0 T8) · 검토 「제출 서류」 묶음
        from app.schemas.delivery_capacity import Credential

        credentials = [Credential.model_validate(c) for c in (company_rows["capacity"] or {}).get("credentials") or []]
        rows, notes = paper_rows(draft.get("papers") or [], credentials, deadline=(view["terms"] or {}).get("deadline"),
                                 today=storage.kst_today().isoformat())
        view["submission_papers"] = {"rows": rows, "notes": notes}
        unread = [{"field": PAPER_FIELD, "why": PAPERS_UNREAD_NOTE, "section": SUPPLEMENT_SECTION}] if papers_unread(draft) else []
        view["blanks"] = [*(view.get("blanks") or []), *paper_blanks(rows, notes, view.get("blanks") or []), *unread, *cover_form_blanks(view)]
        # 원문이 평가본을 요구하면 회사 식별 낱말(회사자료 · 실적 기관 이름 — 이번 공고 글에 있는 낱말은 뺌 · 2.10.0 D7)
        identity = (bid_quality_gate.identity_words(values, company_rows["ledger_rows"], exclude=bid_quality_gate.notice_text(view))
                    if (view.get("format") or {}).get("blind") else None)
        quality = bid_quality_gate.evaluate(view, meta=meta, notice=notice, draft_hash=draft_hash, evidence=evidence, identity=identity,
                                            eligibility=_eligibility(procurement_id, context),
                                            approval=bid_quality_gate.load_approval(context, procurement_id))
    except Exception as exc:  # noqa: BLE001 — 검증을 못 하면 차단으로(fail-closed) · 화면 · 「초안」 내려받기는 열어 둔다(대표 결정 11-08)
        logger.exception("품질 게이트를 실행하지 못했습니다 (procurement_id=%s)", procurement_id)
        quality = bid_quality_gate.error_quality(view, draft_hash=draft_hash)
        bid_quality_gate.log_event(context, procurement_id, {**view, "quality": quality}, event="error", error=type(exc).__name__)
    quality["hwpx_check"] = bid_quality_gate.last_hwpx(context, procurement_id, draft_hash)
    quality["pdf_check"] = bid_quality_gate.last_pdf(context, procurement_id, draft_hash)  # 한글에서 저장한 PDF 검사(판정 밖 · 2.10.0 D10)
    view["quality"] = quality
    return view


def export_meta(draft: dict[str, Any], *, company: str | None, now: datetime | None = None) -> dict[str, Any]:
    """표지 — 문서 종류 「제안서」 · 사업명 · 공고번호(있을 때만 · 2.7.0) · 발주기관 · 사업기간 · 사업금액(원문 글 그대로 · 있을 때만 ·
    2.8.0 B6) · 제안사 · 제출일(해만 · `SUBMIT_DATE` · 2.11.0 D1)."""
    from app.services import plan_export_service

    day = now or datetime.now(plan_export_service.KST)
    # 공고번호 · 사업기간 · 사업금액은 값이 있을 때만 줄을 둔다 — 빈 줄은 표지에 「(담당자 입력)」 칸이 된다(계획 4 「없으면 줄 없음」)
    number = [("공고번호", str(draft["notice_no"]))] if draft.get("notice_no") else []
    terms = draft_terms(draft)
    basics = [(label, str(terms[key])) for label, key in (("사업기간", "period"), ("사업금액", "budget")) if terms.get(key)]
    link = plan_export_service.official_link(draft.get("notice_url"))
    deadline = re.match(r"(\d{4})-", str(terms.get("deadline") or ""))  # 입찰 마감 isoformat(KST) — 2.10.0 뒤 초안만
    return {
        **({"link_url": link} if link else {}),  # 표지 맨 아래 「공고 원문」(2.9.1 · 빈칸 셈 밖)
        "kind": DOC_KIND,
        "notice": draft.get("title"),
        # 표지는 제안서를 받는 수요기관 이름 — 화면 표시값의 「(조달청 대행)」은 싣지 않는다(11-06 심사)
        "rows": [*number, ("발주기관", re.sub(r"\s*\(조달청 대행\)$", "", str(draft.get("agency") or "")) or None), *basics,
                 ("제안사", company), ("제출일", SUBMIT_DATE.format(year=deadline.group(1) if deadline else day.year))],
    }
