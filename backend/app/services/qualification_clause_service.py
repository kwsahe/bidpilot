"""입찰공고문의 「입찰참가자격」 절을 뽑아 조항으로 나눈다 (19차 §4-A).

## 왜 필요한가

담당자 지시(2026-09-23): **「자격요건은 확실하게 가져와서 판단해야 해. 따로 판단하도록 해줘.」**

나라장터 쪽 참가자격 판정은 목록 API 필드와 하루치 면허·지역 표만 봤다. 입찰공고문에 적힌
참가자격 절은 읽지 않았다. 검수자가 기준 답안에 「지역/업종 공고서」라고 적은 것이 바로 그
자리다 — 화면에 값이 없어 공고문을 열어야 확인됐다. 이 모듈이 그것을 연다.

## 하는 일 (판정은 하지 않는다)

1. 공고문(없으면 None — **제안요청서를 대신 쓰지 않는다**)의 쪽 텍스트를 얻는다.
2. 「N. 입찰참가자격」 같은 **번호가 붙은 머리글**에서 다음 절 머리글까지를 절로 잡는다.
   「입찰참가자격」이라는 낱말은 「부정당업자의 입찰참가자격 제한」·「입찰참가자격등록증」처럼
   절 밖에서도 흔하다. 그래서 줄 맨 앞의 번호·기호로 머리글을 가린다.
3. 절 안을 「가.」「①」「1)」「2-1.」「-」「※」 단위로 조항으로 나누고 종류(`kind`)를 붙인다.
4. `data/public/sample_procurements/qualification_clauses/<id>.json` 에 남긴다. 공개 문서의
   발췌이므로 커밋한다 — 시연은 이 파일로 고정 모드에서 돈다. 원본 첨부(`real_rfp/`)는 gitignore.

판정(회사 사실과 견주기)은 `eligibility_engine` 이 한다. 이 모듈은 원문만 다룬다.

## 지어내지 않는다

절을 못 찾으면 `no_section`, 글자가 거의 없으면(스캔 이미지) `image`, 열다가 실패하면 `error`,
받은 적이 없으면 `not_fetched`. 그 어느 것도 「조항 없음 = 제한 없음」이 아니다 — 판정 쪽은
이 넷을 전부 「확인 필요」로 받는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal, Mapping, Sequence

from app.core import storage
from app.core.paths import DATA_ROOT
from app.services import attachment_service, document_extractor, notice_schedule

logger = logging.getLogger(__name__)

CLAUSE_DIR: Path = DATA_ROOT / "public" / "sample_procurements" / "qualification_clauses"
#: 매일 받기(38차 §3-C-1 · `collect_daily.py`)가 만드는 조항 파일 — **Git 밖**이다. 매일 받기로 Git 추적 파일이 바뀌거나
#: 늘지 않게 한다. 읽을 때는 이쪽을 먼저 보고, 없으면 공개 폴더(기존 168 · 손으로 받은 것)를 본다.
PRIVATE_CLAUSE_DIR: Path = DATA_ROOT / "private" / "qualification_clauses"
#: 조항 추출기 판(39차 DAILY-01) — `extract_clauses` · `build_payload` 의 규칙을 바꾸면 올린다. 파일의 판이 다르면 매일 받기가
#: 받아 둔 첨부로 다시 뽑는다(네트워크 0 · Git 밖에 쓴다). 판이 없는 옛 파일은 0 으로 본다.
EXTRACTOR_VERSION = 10  # 10 = 44차 마지막 검토(「부터 N일간 · N일 이내」는 기간 · 「시작 및 마감: A ~ B」의 끝 · 표 머리줄 칸은 갈래 낱말 · 평가 · 개찰 날짜에 칸 이름 안 붙임 · 「24:00까지」는 그날 끝) · 9 = 44차 R36-J-01 · J-02 · J-05(제출 시작 · 날만 적힌 범위 끝 · 표 머리줄 칸 짝 · 서명란 · 괄호 · 점심 · 오후 시각) · 8 = 43차 마지막 검토(질의 · 질문 · 문의 · 이의 · 의견 기한은 일정표 마감이 아님) · 7 = 43차 결정 1 · H6(공고문 일정표 — 참가신청 · 입찰등록 · 제출 마감 · 필수 현장설명 · 단계별 제출서류 `schedule`) · 6 = 41차 마지막 검토(지역 조항이 업종 등록 문장보다 먼저) · 5 = 41차 2-C(업종 코드 목록 줄에서 절이 끊기지 않음 · 코드 없는 업종 등록 문장은 업종 조항 · 여는 말 꼴 더함 · 상한 60) · 2 = 39차 RANK_BRIEF-03(첫 표시 앞 줄 · 띄어 쓰지 않은 표시 · HWP 글꼴 기호) · 3 = 40차 CLAUSE-05(여는 말 · 절 머리글 거르기) · CLAUSE-02(코드 없는 업종 이름) · 4 = 40차 마지막 검토(여는 말은 「기타」로 갈리는 줄만 거름)

ClauseStatus = Literal["ok", "no_section", "image", "error", "not_fetched"]
ClauseKind = Literal[
    "industry", "region", "company_type", "track_record", "staff", "consortium", "disqualification", "other"
]

#: 한 절에서 읽는 줄 수 상한. 머리글을 잘못 잡아도 문서 끝까지 끌려가지 않게 한다.
MAX_SECTION_LINES: Final[int] = 120
#: 조항 한 개로 남기는 글자 수 상한 (원문은 공고문에 있다).
MAX_CLAUSE_CHARS: Final[int] = 600
#: 문서 전체 글자가 이보다 적으면 스캔 이미지로 본다.
MIN_TEXT_CHARS: Final[int] = 80

# ---------------------------------------------------------------------------
# 1) 절 찾기
# ---------------------------------------------------------------------------

_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_HANGUL_ORDER = "가나다라마바사아자차카타파하"

#: 머리글 낱말. 「입찰참가자격등록·제한·확인서류·판단기준」은 머리글이 아니다.
_HEAD_WORD = (
    r"(?:(?:(?:입찰|견적)\s*(?:에\s*)?)?참가\s*(?:자\s*의?\s*)?자격"
    r"(?!\s*(?:등록|제한|확인|의\s*판단|판단|심사|사전|을\s*갖춘|이\s*없|을\s*등록|증명|서류|을\s*증빙))"
    r"|입찰에\s*참가할\s*수\s*있는\s*자)"
)
#: 머리글 앞 기호. 실측 — 한국지능정보사회진흥원(NIA) 공고 셋이 「◐ 입찰참가자격」이다.
_MARKS = "□■○●◎◆◇▶▷◈【\\[<◐◑▣►▸◉★☞❖"
_HEAD_RE = re.compile(
    r"^\s*(?:"
    r"(?P<dash>\d{1,2}\s*-\s*\d{1,2})\s*[.)]?"
    r"|(?P<num>\d{1,2})\s*[.)]"
    rf"|(?P<roman>[{_ROMAN}]|[IVX]{{1,4}}\.)"
    rf"|(?P<hangul>[{_HANGUL_ORDER}])\s*[.)]"
    rf"|(?P<mark>[{_MARKS}])"
    r")?\s*" + _HEAD_WORD
)

#: 머리글 모양의 줄(번호·기호로 시작)이 이 낱말로 시작하면 다음 절이다.
_STOP_WORDS = re.compile(
    r"^(?:입찰\s*방법|입찰\s*및\s*개찰|개찰|낙찰\s*(?:자\s*)?결정|제출\s*서류|입찰\s*보증금|기타(?!\s*자유\s*업종)"
    r"|유의\s*사항|입찰서\s*(?:의\s*)?제출|제안서\s*(?:의\s*)?(?:제출|작성)|계약\s*(?:방법|체결|조건)"
    r"|입찰\s*일정|입찰\s*(?:의\s*)?무효|청렴|문의|현장\s*설명|가격\s*입찰|전자\s*입찰|제안\s*설명"
    r"|사업\s*개요|과업\s*(?:개요|내용)|예정\s*가격)"
)
_NUM_LINE = re.compile(r"^\s*(\d{1,2})\s*\.(?!\d)\s*(\S.*)$")
#: 「2-4.」 같은 작은 절 머리. 그 글이 안내·제출서류 같은 것이면 참가자격 절은 거기서 끝난다.
#: 실측: 감리 공고(1688513)의 「2-4. 조달청 입찰참가자격 등록관련 안내」, 물품 공고(1691972)의
#: 「3-1. 규격입찰 제출서류」 — 둘 다 번호로는 같은 절 안이지만 참가자격이 아니다.
_DASH_LINE = re.compile(r"^\s*\d{1,2}\s*-\s*\d{1,2}\s*[.)]?\s*(\S.*)$")
_SUB_STOP = re.compile(
    r"제출\s*서류|안내|참고\s*사항|유의\s*사항|입찰\s*방법|낙찰|보증금|입찰\s*일정"
    r"|제안서\s*(?:제출|작성)|규격\s*입찰|개찰"
)
_ROMAN_LINE = re.compile(rf"^\s*(?:[{_ROMAN}]|[IVX]{{1,4}}\.)\s*\S")
_HANGUL_LINE = re.compile(rf"^\s*([{_HANGUL_ORDER}])\s*[.)]\s*(\S.*)$")
_MARK_LINE = re.compile(rf"^\s*([{_MARKS}])\s*(\S.*)$")
_SEPARATOR = re.compile(r"^[\s\-─—―=_·⋅∙•.。]+$")
#: 조항 줄(「- 입찰방법 : …」)이 이 낱말로 시작하면 참가자격 절을 벗어난 것이다.
#: 실측: 가천대 피지컬 제안요청서의 「입찰 참가 자격」은 번호 없는 머리글이고, 다음 절이
#: 「2 사업자 선정 방법」「3 낙찰 및 계약」처럼 **마침표 없는 번호**라 절이 대금·지식재산권까지
#: 끌려갔다(19개 중 13개가 참가자격이 아니었다).
_NEXT_SECTION_WORDS = re.compile(
    r"^(?:입찰\s*방법|낙찰\s*및\s*계약|낙찰\s*(?:자\s*)?결정|사업자\s*선정|선정\s*방법|평가\s*(?:기준|방법|항목|점수|결과)"
    r"|계약\s*(?:방법|체결|조건)|대금|소유권|지식\s*재산|제출\s*서류|입찰\s*보증금|유의\s*사항)"
)
_HANGUL_CHAR = re.compile(r"[가-힣]")
#: 조항 머리의 글머리·번호(「– 」「가.」「나)」「1.」「(2)」「①」) — 원문 인용은 그대로 두고 **견줄 때만** 뗀다.
_CLAUSE_MARKER = re.compile(r"^(?:[\s\-–—•·○●◦▪※*]|[가-하]\s*[.)]|\(\s*[가-하0-9]{1,2}\s*\)|[0-9]{1,2}\s*[.)]|[①-⑳])+")


def clause_body(text: str) -> str:
    """글머리·번호를 뗀 조항 본문 — 두 출처의 같은 조항 견주기(`eligibility_engine._clauses_of`)와
    담당자 확인의 원문 지문(`qualification_review_service.clause_hash`)이 같은 규칙을 쓴다 (20차).

    실측(한양사이버대): 공고문 「국가를 당사자로 …」와 RFP 요구사항 「나. 국가를 당사자로 …」가 같은 조항이다.
    """
    return _CLAUSE_MARKER.sub("", text or "")


def _lines(pages: Sequence[document_extractor.DocumentPage]) -> list[tuple[int, str]]:
    """(쪽, 줄) 목록. 빈 줄·구분선은 버린다."""
    out: list[tuple[int, str]] = []
    for page in pages:
        for raw in page.text.splitlines():
            # 연암대 공고문 둘은 PDF 의 빈칸이 NUL(\x00)로 뽑힌다 — 「6.\x00입찰참가자격」.
            line = raw.replace("\x00", " ").strip()
            if not line or _SEPARATOR.match(line):
                continue
            out.append((page.page, line))
    return out


def _is_section_end(line: str, prefix: str, level: int | str | None) -> bool:
    """이 줄에서 절이 끝나는가. `prefix` 는 머리글의 번호 모양이다."""
    num = _NUM_LINE.match(line)
    if num and _STOP_WORDS.match(num.group(2)):
        return True
    marker = _CLAUSE_START.match(line)
    if marker and _NEXT_SECTION_WORDS.match(line[marker.end():]):
        return True
    bare_num = re.match(r"^\s*\d{1,2}\s+(\S.*)$", line)  # 「3 낙찰 및 계약」 — 마침표 없는 번호 머리글
    if bare_num and len(line) <= 30 and (_NEXT_SECTION_WORDS.match(bare_num.group(1)) or _STOP_WORDS.match(bare_num.group(1))):
        return True
    dash = _DASH_LINE.match(line)
    if dash and len(dash.group(1)) <= 40 and _SUB_STOP.search(dash.group(1)):
        return True
    mark = _MARK_LINE.match(line)
    if mark and _STOP_WORDS.match(mark.group(2)) and len(line) <= 40:
        return True
    if _ROMAN_LINE.match(line) and prefix != "roman_inner":
        # 로마 숫자 머리글은 번호 절보다 한 단계 위다 — 무엇으로 시작했든 여기서 끝난다.
        return prefix in ("roman", "num", "hangul", "mark", "none")
    if prefix == "num" and num is not None:
        return int(num.group(1)) > int(level)  # type: ignore[arg-type]
    if prefix == "dash":
        return dash is not None or num is not None
    if prefix == "hangul":
        han = _HANGUL_LINE.match(line)
        if han and _HANGUL_ORDER.find(han.group(1)) > _HANGUL_ORDER.find(str(level)):
            return True
        return num is not None
    if prefix in ("mark", "none") and not marker and len(line) <= 24 and (
        _STOP_WORDS.match(line) or _NEXT_SECTION_WORDS.match(line) or _BARE_NEXT_HEAD.match(line)
    ):
        # 41차 R40-CLAUSE-C — 표 꼴 공고문은 다음 절 머리글이 번호 없는 짧은 줄로 쪼개져 온다(「입찰참가시」 / 「제출서류(…)」 · 「낙찰자」 / 「선정방법」)
        return True
    if prefix in ("mark", "none"):
        # 41차 R40-CLAUSE-C — 「1. 학술연구용역(업종코드 : 1169)」은 앞 조항(「다음 업종 중 1개 이상으로 … 등록한 업체」)이 연 목록의 줄이다
        # (1764648 — 여기서 절이 끝나 업종 코드 줄 · 「공동수급 및 하도급은 불허함」이 빠졌다)
        if num is not None and not _CODE_LIST_LINE.search(line):
            return True
        if mark and mark.group(1) == level and len(line) <= 40:
            return True
    return False


#: 번호 없는 짧은 다음 절 머리(표 꼴 공고문에서 쪼개진 것) — 「입찰참가시」 · 「낙찰자」 · 「입찰 참가자」(뒤에 「유의사항」).
_BARE_NEXT_HEAD = re.compile(r"^(?:입찰\s*참가\s*시|낙찰\s*자|입찰\s*참가자|선정\s*방법)\s*$")
#: 업종 코드 목록 줄 — 「(업종코드 : 1169)」 · 「(1468)」.
_CODE_LIST_LINE = re.compile(r"업종\s*코드|\(\s*\d{4}\s*\)")


def _is_split_heading(lines: Sequence[tuple[int, str]], index: int, level: int | str | None) -> bool:
    """번호만 있는 줄 다음에 짧은 제목 줄이 오면 다음 절 머리글이다 — 「3」 / 「추진일정」.

    실측: 한글 공고서(1727923)는 절 번호와 제목을 다른 문단에 둔다. 번호만 있는 줄은 쪽 번호·표의
    행 번호일 수도 있으므로 **이 절 번호보다 크고**, 다음 줄이 조항 표시 없는 짧은 제목일 때만 끝으로
    본다. 실측: 박람회 공고(1712423)는 절 안 표의 「1」/「전시회,회의및 행사대행서비스」에서 끊겼다.
    """
    if not isinstance(level, int) or index + 1 >= len(lines):
        return False
    if not re.fullmatch(r"\d{1,2}", lines[index][1]) or int(lines[index][1]) <= level:
        return False
    title = lines[index + 1][1]
    return len(title) <= 20 and not _CLAUSE_START.match(title)


def find_sections(lines: Sequence[tuple[int, str]]) -> list[tuple[int, int, str]]:
    """참가자격 절 후보들 `(머리글 줄 번호, 끝 줄 번호(제외), 머리글)` — 앞에서부터.

    번호·기호 없이 낱말만 있는 줄은 **짧을 때만**(40자 이하) 머리글로 본다. 그렇지 않으면
    「입찰참가자격을 갖춘 자로서 …」 같은 문장이 머리글로 잡힌다.
    """
    found: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        _page, line = lines[index]
        match = _HEAD_RE.match(line)
        if not match:
            index += 1
            continue
        if match.group("dash"):
            prefix, level = "dash", match.group("dash")
        elif match.group("num"):
            prefix, level = "num", int(match.group("num"))
        elif match.group("roman"):
            prefix, level = "roman", match.group("roman")
        elif match.group("hangul"):
            prefix, level = "hangul", match.group("hangul")
        elif match.group("mark"):
            prefix, level = "mark", match.group("mark")
        else:
            if len(line) > 40:
                index += 1
                continue
            # 번호가 윗줄에 따로 있으면(「2」/「입찰참가자격」) 그것이 이 절의 번호다.
            above = lines[index - 1][1] if index else ""
            prefix, level = "none", int(above) if re.fullmatch(r"\d{1,2}", above) else None
        end = index + 1
        while end < len(lines) and end - index <= MAX_SECTION_LINES:
            if _is_section_end(lines[end][1], prefix, level) or _is_split_heading(lines, end, level):
                break
            end += 1
        found.append((index, end, line))
        index = end
    return found


# ---------------------------------------------------------------------------
# 2) 조항 나누기
# ---------------------------------------------------------------------------

_CLAUSE_START = re.compile(
    r"^\s*(?:"
    rf"[{_HANGUL_ORDER}]\s*[.)]"  # 가.  나)
    r"|\(?\d{1,2}\)"  # 1)  (1)
    r"|\d{1,2}(?:\s*-\s*\d{1,2})+\s*[.)]?"  # 2-1.  2-4-1.
    r"|[①-⑳㉮-㉻]"  # ①  ㉮
    r"|[-‐–•▪◦∙○●◆◇❍](?:\s|$)"  # - 항목 · 표시만 한 줄(HWPX 는 표시와 글을 다른 문단에 둔다)
    # 39차 RANK_BRIEF-03 — 띄어 쓰지 않은 표시(PDF 「○국가종합…」 · 「◐ 다음 중…」 · 「-[종합여행업(1261)]」)와
    # HWP 의 글꼴 기호 표시(사용자 영역 글자 · Wingdings 「」)도 조항의 시작이다. 「-」는 숫자 앞이면 표시가 아니다(「-1」 · 범위).
    r"|[○●◆◇❍◐◑■□▶▷►◈]"
    r"|[-‐–](?=[^\d\s])"
    r"|[\ue000-\uf8ff]"
    r"|※"
    r"|\*(?:\s|$)"
    r")\s*"
)
#: 「아래 자격을 모두 갖춘 자」 같은 머리 문장 — 조항이 아니라 조항들을 여는 말이다(짧을 때만 · `_INTRO_MAX`).
#: 40차 CLAUSE-05 — 추출기 2 가 첫 표시 앞 줄을 남기면서 절 제목 · 여는 말이 「기타 조항」 판정 줄이 되어 사람에게 「충족 확인」을 물었다
#: (「입찰참가자격 공지사항」 36건 · 「다음 중 어느 하나에 해당하는 자는 입찰참가자격이 없음」 · 「(모든 조건을 충족해야 참가 가능함)」 ·
#: 「아래의 참가자격을 모두 갖춘 자이어야 함.」 · 「<다음 각 호의 요건을 모두 갖춘 업체>」 · 「… 다음 요건을 모두 충족하여야 한다.」).
_INTRO = re.compile(
    r"^(?:아래|다음)(?:의)?\s*(?:각\s*호의?\s*)?(?:입찰\s*참가\s*)?(?:자격|조건|사항|요건)"
    # 머리글 낱말만 있는 줄 — 「입찰참가자격 공지사항」 · 「2. 입찰참가자격」 · 「참가자격 요건 :」
    r"|^(?:\d{1,2}\s*[.)]\s*)?(?:입찰\s*)?참가\s*자격(?:\s*(?:공지\s*사항|요건|사항|안내|조건))?\s*[:：]?\s*$"
    # 「다음/아래 … 모두 갖춘 · 충족」 — 앞에 「입찰에 참가하고자 하는 자는」이 와도
    r"|(?:아래|다음)\s*(?:의|각\s*호의?)?\s*.{0,20}?(?:모두|전부)\s*(?:갖춘|갖추|충족|만족|구비)"
    # 41차 R40-CLAUSE-E — 「다음 각 호 중 어느 하나에 해당하는 자」 · 「다음 각 호에 해당하는 업체이어야 합니다」(목록을 여는 말)
    r"|^(?:아래|다음)\s*(?:각\s*호|사항|요건)?\s*(?:의|중)?\s*(?:어느\s*하나)?\s*에?\s*해당하는\s*(?:자|업체|기업|법인|사업자)"
    # 「다음 중 어느 하나에 해당하는 자는 … 없음 · 제한」 — 결격 목록을 여는 말
    r"|(?:아래|다음)\s*(?:중|의)?\s*(?:어느|각)\s*(?:하나|호).{0,30}?(?:자격이\s*없|참가할\s*수\s*없|참여할\s*수\s*없|제한)"
    # 괄호만 있는 안내 — 「(모든 조건을 충족해야 참가 가능함)」 · 「<다음 각 호의 요건을 모두 갖춘 업체>」
    r"|^[(（<〈《\[](?=.{0,43}(?:조건|요건|자격)).{0,43}(?:충족|갖춘|갖추|해당)[^)）>〉》\]]{0,20}[)）>〉》\]]\s*[.。]?\s*$"
)
#: 41차 R40-CLAUSE-E — 「본 제안 사업의 수행이 가능한 업체로서 다음 요건을 모두 갖춘 사업자이어야 한다.」(48자)도 여는 말이다 — 거르는 것은
#: 여전히 「기타」로 갈리는 줄뿐이다(요건이 든 줄은 길이와 상관없이 남는다).
_INTRO_MAX = 60


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


#: 표시 없는 줄이 한 조항을 끝내는 꼴 — 「… 갖춘 자」 「… 등록한 업체」 「… 할 것」 「… 없음」(39차 RANK_BRIEF-03 · DOCX 목록은 표시가 글에 없다).
_LEAD_END = re.compile(r"(?:자|업체|기업|법인|것|함|음|됨|임|다)\s*[.。]?\s*$")


def _same_heading(text: str, heading: str | None) -> bool:
    """절 머리글과 같은 줄인가(40차 CLAUSE-05) — 「2. 입찰참가자격」이 머리글이면서 첫 조항이 됐다(1717796). 번호 · 기호 · 띄어쓰기는 보지 않는다."""
    if not heading:
        return False

    def bare(value: str) -> str:
        return re.sub(r"[\s\d.)(:：□■○●◆◇▶►※\-Ⅰ-Ⅻ]", "", value)

    return bool(bare(text)) and bare(text) == bare(heading)


def split_clauses(body: Sequence[tuple[int, str]], heading: str | None = None) -> list[dict[str, Any]]:
    """절 본문(머리글 다음 줄부터)을 조항으로 나눈다. `[{"text", "page"}]`.

    첫 표시 앞의 줄도 버리지 않는다(39차 RANK_BRIEF-03) — DOCX 목록은 번호가 글에 없고, PDF 는 「○국가종합…」처럼 띄어 쓰지 않은
    표시가 있어 첫 조항(업종 · 등록)이 통째로 사라졌다(1767741 · 1764812). 표시 없는 앞줄은 조항 끝 꼴(「… 자」 · 「… 업체」 · 「… 것」)
    에서 나누고, 짧은 여는 말(「아래 자격을 모두 갖춘 자」)은 아래 거르기가 뺀다.
    """
    raw: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page, line in body:
        marker = _CLAUSE_START.match(line)
        if marker:
            if current is not None:
                raw.append(current)
            current = {"page": page, "text": line[marker.end():]}
            continue
        if current is None:
            current = {"page": page, "text": line, "lead": True}  # 첫 표시 앞 줄 — 버리지 않는다
            continue
        if current.get("lead") and _LEAD_END.search(current["text"]):
            raw.append(current)  # 표시 없는 앞 조항이 끝났다 — 다음 줄은 새 조항
            current = {"page": page, "text": line, "lead": True}
            continue
        # PDF 는 한 문장을 여러 줄로 꺾는다 — 이어 붙인다.
        current["text"] += " " + line
    if current is not None:
        raw.append(current)

    clauses: list[dict[str, Any]] = []
    for entry in raw:
        text = _norm(entry["text"])
        hangul = len(_HANGUL_CHAR.findall(text))
        if hangul < 4:
            continue  # 「⋅ ⋅ ⋅ ⋅」처럼 표가 깨진 자리, 번호만 남은 줄
        if len(text) <= 8:
            continue  # 「자격사항」 같은 작은 머리글
        if len(text) < _INTRO_MAX and _INTRO.search(text) and classify(text) == "other":
            # 여는 말 · 머리글 낱말 — **요건이 없는 줄(「기타」)만** 거른다. 「입찰참가자는 다음 요건을 모두 갖춘 중소기업이어야 함」(기업 유형) ·
            # 「… 다음 중 어느 하나에 해당하면 참가할 수 없음」(결격) · 업종 줄은 짧아도 조항이다(40차 마지막 검토 — 버리면 거짓 「가능」).
            continue
        if _same_heading(text, heading):
            continue
        clauses.append({"text": text[:MAX_CLAUSE_CHARS], "page": entry["page"]})
    return clauses


# ---------------------------------------------------------------------------
# 3) 종류 가르기 — 먼저 맞는 것이 이긴다
# ---------------------------------------------------------------------------

#: 이름만으로 업종 조항임을 알 수 있는 업종들 (나라장터 등록 업종 이름).
#: 띄어쓰기는 견줄 때 지운다(`industry_names`) — 「소프트웨어 사업자」를 따로 두면 열리는 조건이
#: 「소프트웨어사업자 등록 시 가능 또는 소프트웨어 사업자 등록 시 가능」으로 두 번 나온다(실측 5건).
INDUSTRY_NAMES: Final[tuple[str, ...]] = (
    "소프트웨어사업자", "컴퓨터관련서비스", "정보통신공사업", "엔지니어링사업자",
    "엔지니어링활동주체", "감리법인", "기타자유업종", "학술연구용역", "정보보호전문서비스",
    "전기공사업", "산업디자인전문회사", "전시·행사대행업", "전시행사대행업", "직업능력개발훈련",
    "평생교육시설", "출판사", "인쇄업", "여행업", "시각디자인업", "광고대행업",
    # 40차 CLAUSE-02 — 코드 없이 이름만 적는 업종(1765752 「국제공인교정기관 및 교육서비스업으로 입찰참가자격을 등록한 사업자」가 기타로 갈렸다)
    "국제공인교정기관", "교육서비스업",
)
_CODE_IN_PARENS = re.compile(r"\(([^()]{0,80})\)")
_CODE_AFTER_WORD = re.compile(r"(?:업종\s*코드|업종|코드)\s*[:：]?\s*((?:\d{4}\s*[/,·ㆍ]?\s*)+)")
_FOUR_DIGITS = re.compile(r"(?<!\d)(\d{4})(?!\d)")
#: 괄호 안이 코드 목록일 때만 — 「(1468)」「(1426/1468/1469/1470)」「(업종코드 : 6146)」.
#: 「(☎ 053-589-7732)」·「(2026년)」·「(5/100)」 같은 것은 코드가 아니다.
_CODE_GROUP = re.compile(r"^\s*(?:업종\s*코드\s*[:：]?\s*)?\d{4}(?:\s*[/,·ㆍ]\s*\d{4})*\s*$")
#: 대괄호 안 「이름, 코드」 — 「[행사대행업, 9901]으로 등록한 업체」(44차 R36-J-04 — 결격 조항으로 가 회사 단위 확인으로 「통과」했다)
_CODE_IN_BRACKETS = re.compile(r"\[[^\[\]]{1,40}?[,，]\s*(\d{4})\s*\]")

_NEGATIVE = re.compile(
    r"(?:참가|참여|입찰)\s*할\s*수\s*없|제외(?:한다|됨|합니다|되는)|해당하지\s*(?:아니|않)"
    r"|아닌\s*자|아니한\s*(?:자|업체|법인)|지나지\s*아니한|지정되지\s*아니한"
)
#: 「… 수행실적 … 등은 별도의 입찰참가 제한요건으로 하지 않으며」 — **요구하지 않는다**는 문장이다.
#: 실측(1727020): 실적 조항으로 읽혀 「필요 1건 · 원장에서 8건 → 가능」이 나왔다(없는 요구를 지어냄).
#: 규칙으로 판정하지 않고 원문 확인(기타)으로 둔다.
#: 「… 예외를 적용하여 … 입찰참가를 허용」(1718593)도 요구가 아니라 **허용**이다.
_NOT_REQUIRED = re.compile(
    r"요건\s*으로\s*하지\s*않|제한\s*(?:을\s*)?(?:하지|두지)\s*않|요구\s*하지\s*않|참가\s*를\s*허용"
)
#: 실적을 **평가하거나 증빙하는 방법**을 말하는 문장은 참가 요건이 아니다 — 실측(구미대 1726679):
#: 「관련 수행실적은 제안서 평가 시 … 기준에 따라 평가합니다」「실적은 … 증빙 자료로 확인합니다」가
#: 실적 조항으로 읽혀 「필요 1건」이 붙었다(조항이 하나뿐이었다면 원장 23건으로 근거 없는 가능이 된다).
_TRACK_NOT_REQUIRED = re.compile(r"평가\s*시|평가\s*합니다|평가\s*기준에\s*따라|증빙\s*자료로\s*확인")
_REGION = re.compile(
    # 「관내」는 **업체가 관내에 있어야** 할 때만 지역이다 — 실측(1728220): 「지자체 관내 지역 주민 … 을 대상으로
    # … 운영한」(실적 문장)을 지역 조항으로 읽었다.
    r"소재지|소재한|소재하는|소재하고|관내\s*(?:업체|사업자|기업|에\s*(?:소재|주된|본점|본사))|주된\s*영업소|본점"
    r"|본사\s*(?:가|를|의)?\s*(?:소재|두|둔|있)"
    r"|지역\s*제한|지역제한"
)
_PERSON = re.compile(
    r"책임자|기술자(?!격)|기술\s*인력|전문\s*인력|투입\s*인력|참여\s*인력|인력|연구원|강사|트레이너|엔지니어"
    r"|\bPM\b|\bPL\b"
)
_PERSON_NEED = re.compile(r"경력|자격|보유|\d+\s*(?:명|인)\s*이상|확보")
_TRACK = re.compile(r"실적|수행\s*(?:한\s*)?경험|수행\s*이력|납품\s*이력|유사\s*(?:사업|용역|과업)")
_COMPANY_TYPE = re.compile(
    r"중소기업|중[·ㆍ]소기업|소기업|소상공인|사회적\s*기업|여성\s*기업|장애인\s*기업|벤처\s*기업"
    r"|창업\s*\d+\s*년|예비\s*사회적|협동\s*조합|마을\s*기업|자활\s*기업"
)
_CONSORTIUM = re.compile(r"공동\s*수급|공동\s*이행|공동\s*계약|분담\s*이행|컨소시엄|대표사|구성원")
_DISQUAL = re.compile(
    r"부정당|제\s*1[234]\s*조|제\s*76\s*조|경쟁\s*입찰\s*(?:참가\s*)?자격|입찰\s*참가\s*자격\s*(?:등록|을\s*갖춘)"
    r"|등록\s*규정|나라장터|G2B|국가종합전자조달|부도|파산|신용\s*(?:부실|불량)|조세\s*포탈|청렴"
    r"|자격\s*요건을\s*갖춘|허가.{0,6}인가.{0,6}면허"
)


#: 업종 등록을 요구하는 문장(코드 · 이름 없이) — 「다음 업종 중 1개 이상으로 … 등록한 업체」 · 「아래 업종으로 입찰참가자격을 등록한 자」.
_INDUSTRY_REGISTER = re.compile(r"업종\s*(?:중|으로|로)[^.。]{0,30}?등록(?:한|하여|된|을\s*필)")


def industry_codes(text: str) -> list[str]:
    """조항에 적힌 업종 코드(네 자리). 연도·금액과 섞이지 않게 **괄호 안** 또는 「업종코드」 뒤만 본다."""
    codes: list[str] = []
    for group in _CODE_IN_PARENS.findall(text):
        if _CODE_GROUP.match(group):
            codes.extend(_FOUR_DIGITS.findall(group))
    for group in _CODE_AFTER_WORD.findall(text):
        codes.extend(_FOUR_DIGITS.findall(group))
    codes.extend(_CODE_IN_BRACKETS.findall(text))
    out: list[str] = []
    for code in codes:
        if code.startswith(("19", "20")) or code in out:
            continue
        out.append(code)
    return out


def industry_names(text: str) -> list[str]:
    compact = text.replace(" ", "")
    return [name for name in INDUSTRY_NAMES if name.replace(" ", "") in compact]


def classify(text: str) -> ClauseKind:
    """조항 하나의 종류. 순서가 곧 규칙이다 (위에서 먼저 맞으면 그것이다).

    - 업종이 먼저다 — 「감리법인(업종코드 : 6146)으로 입찰참가자격을 등록한 자」는 등록 문장이지만
      업종을 말한다.
    - 「… 해당하는 자는 참여할 수 없다」 같은 **빼는 문장**은 결격 조항이다 — 「중소기업」이라는
      낱말이 들어 있어도 중소기업이어야 한다는 뜻이 아니다.
    - 사람(책임자·기술자)의 경력은 인력이다 — 회사 실적 원장으로 채우면 안 된다.
    - 코드 없이 업종 **이름만** 걸린 빼는 문장은 업종이 아니다 — 실측(1718615): 「대기업 및 중견기업
      소프트웨어 사업자는 본 입찰에 참여할 수 없으며」를 「소프트웨어사업자 등록 요구」로 읽었다.
    """
    if _NOT_REQUIRED.search(text):
        return "other"
    if industry_codes(text) or (industry_names(text) and not _NEGATIVE.search(text)):
        return "industry"
    if _NEGATIVE.search(text):
        return "disqualification"
    if _REGION.search(text):
        return "region"
    if _INDUSTRY_REGISTER.search(text):
        # 41차 R40-CLAUSE-C — 코드 · 이름이 다음 줄에 있는 업종 문장(「나라장터에 다음 업종 중 1개 이상으로 입찰참가자격을 등록한 업체」)은
        # 「나라장터 · 등록 규정」 낱말로 결격에 갔다 — 업종 조항이다(규칙은 요구 업종을 모르니 확인 필요). 지역 조항이 먼저다(마지막 검토 —
        # 「서울특별시에 본사를 두고 해당 업종으로 등록한 업체」의 지역 「불가」가 사라졌다).
        return "industry"
    if _PERSON.search(text) and _PERSON_NEED.search(text):
        return "staff"
    if _TRACK.search(text) and not _TRACK_NOT_REQUIRED.search(text):
        return "track_record"
    if _COMPANY_TYPE.search(text):
        return "company_type"
    if _CONSORTIUM.search(text):
        return "consortium"
    if _DISQUAL.search(text):
        return "disqualification"
    return "other"


# ---------------------------------------------------------------------------
# 4) 문서 하나에서 뽑기
# ---------------------------------------------------------------------------


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def extract_clauses(path: Path, *, file_name: str, published_at: datetime | None = None) -> dict[str, Any]:
    """문서 하나에서 참가자격 절과 조항을 뽑는다. 판정은 하지 않는다.

    반환: `{status, format, file, page_is_approximate, section, clauses, note, schedule}`
    DOCX 는 직접 넣은 공고문(38차 §3-E)만 온다 — 나라장터 첨부의 압축 판별은 그대로다.
    `schedule` 은 같은 글 전체에서 뽑은 일정표 · 제출서류(43차 결정 1 · `notice_schedule`) — 글을 못 읽었으면 None.
    """
    try:
        if path.suffix.lower() == ".docx":
            doc = document_extractor.ExtractedDocument(
                file_name=file_name, doc_format="docx", pages=document_extractor.extract_docx(path)
            )
        else:
            doc = document_extractor.extract_document(
                path, file_name=file_name, zip_priority=document_extractor.ZIP_NOTICE_PRIORITY
            )
    except document_extractor.DocumentExtractionError as exc:
        return {"status": "error", "format": None, "file": file_name, "page_is_approximate": False,
                "section": None, "clauses": [], "note": str(exc)[:200]}
    except Exception as exc:  # noqa: BLE001 — 한 파일이 깨져도 나머지는 계속한다
        return {"status": "error", "format": None, "file": file_name, "page_is_approximate": False,
                "section": None, "clauses": [], "note": f"{type(exc).__name__}: {exc}"[:200]}

    approx = doc.doc_format in ("hwp", "hwpx", "docx")
    base = {"format": doc.doc_format, "file": doc.file_name, "page_is_approximate": approx}
    if len(doc.text.strip()) < MIN_TEXT_CHARS:
        return {**base, "status": "image", "section": None, "clauses": [],
                "note": f"글자가 {len(doc.text.strip())}자뿐입니다 — 스캔 이미지로 보입니다"}

    lines = _lines(doc.pages)
    base["schedule"] = notice_schedule.extract(
        lines, year_hint=(published_at or datetime.now(timezone.utc)).year, not_before=published_at
    )
    for start, end, heading in find_sections(lines):
        clauses = split_clauses(lines[start + 1:end], heading)
        if not clauses:
            continue  # 목차의 한 줄이었거나 표가 깨졌다 — 다음 후보를 본다
        for number, clause in enumerate(clauses, start=1):
            clause["id"] = f"QC-{number:02d}"
            clause["kind"] = classify(clause["text"])
        section = {
            "heading": _norm(heading)[:80],
            "page_from": lines[start][0],
            "page_to": lines[max(start, end - 1)][0],
        }
        return {**base, "status": "ok", "section": section,
                "clauses": [{"id": c["id"], "text": c["text"], "page": c["page"], "kind": c["kind"]} for c in clauses],
                "note": None}
    heads = [h for _s, _e, h in find_sections(lines)]
    note = (
        f"머리글은 {len(heads)}곳 찾았지만 조항을 나누지 못했습니다: {heads[0][:40]}" if heads
        else "「N. 입찰참가자격」 모양의 머리글을 찾지 못했습니다"
    )
    return {**base, "status": "no_section", "section": None, "clauses": [], "note": note}


# ---------------------------------------------------------------------------
# 5) 공고 하나 — 공고문 + (있으면) 제안요청서
# ---------------------------------------------------------------------------


def _cached_doc(notice_id: str, attachments: Sequence[Mapping[str, Any]], index: int | None) -> Path | None:
    if index is None:
        return None
    return attachment_service.cached_attachment(notice_id, index, str(attachments[index].get("name") or ""))


def build_payload(notice_id: str, attachments: Sequence[Mapping[str, Any]], *, published_at: datetime | None = None) -> dict[str, Any]:
    """저장할 한 공고의 조항 파일. **네트워크를 부르지 않는다** — 캐시에 있는 첨부만 연다.
    `published_at`(공고 게시) — 일정표가 그보다 이른 날짜를 마감으로 읽지 않게(43차)."""
    notice_index = attachment_service.pick_notice_document(attachments)
    notice_path = _cached_doc(notice_id, attachments, notice_index)

    payload: dict[str, Any] = {
        "notice_id": notice_id,
        "extractor_version": EXTRACTOR_VERSION,
        "document": None,
        "fetched_at": None,
        "status": "not_fetched",
        "page_is_approximate": False,
        "section": None,
        "clauses": [],
        "second_source": None,
        "note": None,
        "schedule": None,
    }
    if notice_index is None:
        payload["note"] = "첨부 목록에 입찰공고문이 없습니다"
    elif notice_path is None:
        payload["note"] = "입찰공고문을 아직 내려받지 않았습니다"
    else:
        name = str(attachments[notice_index].get("name") or notice_path.name)
        result = extract_clauses(notice_path, file_name=name, published_at=published_at)
        payload.update(
            document={"name": result["file"] or name, "index": notice_index, "format": result["format"],
                      "hash": _file_hash(notice_path)},
            fetched_at=datetime.fromtimestamp(notice_path.stat().st_mtime, timezone.utc).isoformat(),
            status=result["status"],
            page_is_approximate=result["page_is_approximate"],
            section=result["section"],
            clauses=result["clauses"],
            note=result["note"],
            schedule=result.get("schedule"),
        )

    # 두 번째 출처 — 제안요청서 안의 같은 절. **이미 내려받아 둔 것만** 연다(여기서 받지 않는다).
    rfp_index = attachment_service.pick_rfp_attachment(attachments)
    if rfp_index is not None and rfp_index != notice_index:
        rfp_path = _cached_doc(notice_id, attachments, rfp_index)
        if rfp_path is not None:
            name = str(attachments[rfp_index].get("name") or rfp_path.name)
            second = extract_clauses(rfp_path, file_name=name)
            if second["status"] == "ok":
                payload["second_source"] = {
                    "document": {"name": second["file"] or name, "index": rfp_index, "format": second["format"]},
                    "page_is_approximate": second["page_is_approximate"],
                    "section": second["section"],
                    "clauses": second["clauses"],
                }
    return payload


# ---------------------------------------------------------------------------
# 6) 저장·읽기
# ---------------------------------------------------------------------------


def clause_path(notice_id: str, *, private: bool = False) -> Path:
    safe = attachment_service.sanitize_dir_name(notice_id)
    return (PRIVATE_CLAUSE_DIR if private else CLAUSE_DIR) / f"{safe}.json"


#: 읽은 결과가 있는 조항 파일 상태 — 못 받은 결과(not_fetched · error)로 덮지 않는다(40차 CLAUSE-08).
READ_STATUSES: frozenset[str] = frozenset({"ok", "no_section", "image"})


def save(payload: dict[str, Any], *, private: bool = False) -> Path:
    """조항 파일을 쓴다. `private=True` 면 Git 밖(매일 받기 · 38차) — 공개 폴더의 같은 공고 파일은 건드리지 않는다.

    40차 CLAUSE-08 — 새 결과가 못 받음 · 여는 중 실패(not_fetched · error)이고 그 자리의 기존 파일이 읽은 결과(ok · 절 없음 · 그림)면
    **덮지 않는다** — 첨부 캐시가 지워졌거나 `--cache-only` 로 다시 뽑을 때 Git 밖 「읽음」 파일이 「안 읽음」으로 돌아갔다."""
    path = clause_path(str(payload["notice_id"]), private=private)
    if payload.get("status") not in READ_STATUSES:
        existing = _read(path)
        if existing is None and private:
            # Git 밖이 비었어도 공개 폴더에 읽은 파일이 있으면 Git 밖에 「못 받음」을 쓰지 않는다 — 먼저 읽히는 쪽이 그것을 가렸다(40차 마지막 검토)
            existing = _read(clause_path(str(payload["notice_id"])))
        if existing is not None and existing.get("status") in READ_STATUSES:
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(path, payload)
    _MEMO.pop(str(path), None)
    return path


_MEMO: dict[str, tuple[float, dict[str, Any] | None]] = {}


def load(notice_id: str | None) -> dict[str, Any] | None:
    """저장된 조항 파일. 없으면 None. **파일 읽기뿐** — 목록 100여 건에 걸어도 네트워크가 없다.

    파일 시각으로 메모한다 — 목록이 같은 파일을 공고마다 다시 읽지 않게.
    """
    if not notice_id:
        return None
    # 38차 §3-C-1 — Git 밖(매일 받기)이 먼저, 없으면 공개 폴더.
    for path in (clause_path(notice_id, private=True), clause_path(notice_id)):
        payload = _read(path)
        if payload is not None:
            return payload
    return None


def _read(path: Path) -> dict[str, Any] | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _MEMO.get(str(path))
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("참가자격 조항 파일을 읽지 못했습니다: %s", path.name)
        payload = None
    _MEMO[str(path)] = (mtime, payload)
    return payload


# ---------------------------------------------------------------------------
# 7) 근거 줄 (38차 §3-C-2)
# ---------------------------------------------------------------------------

#: 근거 줄에 먼저 쓰는 조항 갈래 — 회사가 직접 갖출 것(업종 · 지역 · 기업 유형 · 실적 · 인력 · 공동수급)을 결격 · 일반 조항보다 먼저.
_EVIDENCE_ORDER: tuple[str, ...] = ("industry", "region", "company_type", "track_record", "staff", "consortium", "other", "disqualification")
#: 근거 줄로 고르는 조항 — 판정에 쓰이는 것(업종 · 지역 · 기업구분 · 실적 · 인력)만이다(39차 §3-G). 결격 · 전자입찰 등록 안내 · 입찰 일정 ·
#: 절 제목 같은 일반 조항(other · disqualification · consortium)은 고르지 않는다 — 브리핑이 「입찰참가자격 공지사항 …」을 근거로 적었다.
_EVIDENCE_KINDS: frozenset[str] = frozenset({"industry", "region", "company_type", "track_record", "staff"})
#: 「결정 조항 없음」은 상세의 「참가자격 조항 n개」와 반대로 읽혔다(P1-02 4장) — 무엇이 없는지(업종 · 지역 제한)를 적는다. 조항 수는 상세가 말한다.
NO_DECISION_CLAUSE = "공고문 읽음 · 업종 · 지역 제한 조항 없음(결격 등 일반 조항만 — 3단계에서 확인)"
#: 판정 조항이 없는데 그 말을 믿기 어려울 때(40차 CLAUSE-02) — 공고 필드가 업종 · 지역을 요구하거나, 조항이 기타뿐 · 하나뿐 · 옛 추출기 판.
#: 「결정 조항 없음」으로 단정하지 않는다(1765752 업종 이름 · 1722200 머리글 오독 · 1767741 옛 판).
NO_DECISION_UNSURE = "공고문 읽음 · 업종 · 지역 제한 조항을 못 찾음 — 원문 확인"
#: 근거 줄에 싣는 원문 글자 수.
EVIDENCE_CHARS = 70
NOT_READ = "공고문 아직 안 읽음"
#: 받았는데 열지 못함(43차 M8) — 원문을 직접 봐야 한다.
OPEN_FAILED = "공고문 열기 실패 — 원문 직접 확인"


def field_requires(rules: Sequence[Any]) -> bool:
    """공고 필드 규칙이 참가 요건을 말하나(40차 CLAUSE-02) — 업종 제한(요구 업종이 있거나 · 받지 못했거나 · 가능이 아님) · 지역 제한(가능이 아님)."""
    for rule in rules:
        rule_id, status, source = getattr(rule, "rule_id", ""), getattr(rule, "status", ""), str(getattr(rule, "source", "") or "")
        if rule_id == "ELIG-INDUSTRY" and ("요구 업종:" in source or status != "PASS"):
            return True
        if rule_id == "ELIG-REGION" and status != "PASS":
            return True
    return False


def evidence_line(payload: Mapping[str, Any] | None, *, field_requires: bool = False) -> tuple[str, int]:
    """`(근거 줄, 조항 수)`. 「근거: 공고문 p.N 「…」(QC-xx)」 — 읽은 조항이 없으면 「공고문 아직 안 읽음」 · 0.

    판정 조항이 없을 때 `field_requires`(공고 필드가 요건을 말함)거나 조항이 의심스러우면(기타뿐 · 하나뿐 · 옛 판)
    `NO_DECISION_UNSURE`(40차 CLAUSE-02), 그 밖은 `NO_DECISION_CLAUSE`."""
    if payload and payload.get("status") in ("error", "image"):
        # 43차 M8 · ELIG-08 — 받았는데 못 열었다(압축 이름 · 스캔 이미지 · 손상) — 「아직 안 읽음」으로 실패를 가리지 않는다
        return OPEN_FAILED, 0
    if not payload or payload.get("status") != "ok" or not payload.get("clauses"):
        return NOT_READ, 0
    clauses = [c for c in payload["clauses"] if isinstance(c, Mapping) and c.get("text")]
    if not clauses:
        return NOT_READ, 0
    decisive = [c for c in clauses if str(c.get("kind")) in _EVIDENCE_KINDS]
    if not decisive:
        kinds = {str(c.get("kind") or "other") for c in clauses}
        stale = int(payload.get("extractor_version") or 0) != EXTRACTOR_VERSION
        unsure = field_requires or kinds <= {"other"} or len(clauses) == 1 or stale
        return (NO_DECISION_UNSURE if unsure else NO_DECISION_CLAUSE), len(clauses)
    rank = {kind: i for i, kind in enumerate(_EVIDENCE_ORDER)}
    best = min(decisive, key=lambda c: rank.get(str(c.get("kind")), len(rank)))
    text = " ".join(str(best["text"]).split())
    if len(text) > EVIDENCE_CHARS:
        text = text[:EVIDENCE_CHARS].rstrip() + "…"
    page = best.get("page")
    approx = "≈" if payload.get("page_is_approximate") else ""
    where = f"공고문 p.{approx}{page} " if page else "공고문 "
    return f"근거: {where}「{text}」({best.get('id') or 'QC'})", len(clauses)

