"""사업계획서 초안 규칙 검증 (25차 · prompt_15 §4-C-3) — **LLM 이 아니다.**

AI 가 쓴 초안을 그대로 믿지 않는다. 규칙으로 다시 본다:

- 회사 근거 문장: 가리킨 근거(`source_ids`)가 실재하고, 문장의 숫자 · 기관명 · 연도가 그 근거 글에 있어야 한다.
  아니면 `AI_SUGGESTION` 으로 내리고 「근거 확인 필요」.
- 숫자는 **원 단위로 맞춘 뒤** 비교한다(「1억원」 = 100,000,000원 · 단위 없는 표 금액은 「금액(원)」 열이라 원).
- 일정은 협약 기간 안이어야 한다 — 「’27.3월」 · 「26.11.01」 · 「～」(U+FF5E)를 읽는 작은 날짜 파서.
- 양식 예시 값(3,448,000 · ’24.3.6 …)과만 같은 숫자 · 날짜는 근거가 아니다 — 지우고 「(담당자 입력)」.
- 사람만 채우는 칸(연락처 · 이메일 · 사업자등록번호 · 법인등록번호 · 주소 · 매출액 · 고용인원 …)이 채워져 있으면 지운다.
- 금칙어(보장 · 100% · 최고 · 완벽 · 무조건 · 반드시 달성 · 유일 · 선정 확률).
- 공고 문장 복사 — 공고문과 연속 30자(공백 무시) 이상 같거나, 문장의 70% 이상이 공고 한 대목과 겹친다.
"""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.services import support_requirement_extractor, text_match
from app.services.auditor_service import _ABSOLUTE_CLAIM_RE
from app.services.plan_form_service import HUMAN_INPUT, unwritten_count

#: 금칙어 목록 하나 — Auditor 의 단정 표현에 「유일」 · 「선정 확률」을 더한다.
BANNED_RE = re.compile(f"{_ABSOLUTE_CLAIM_RE.pattern}|유일|선정\\s*확률")

_MONEY_UNITS = {"억원", "만원", "원", "억", "만"}
#: 쉼표 숫자 = 표의 금액(원). 뒤에 개수 · 천 단위가 붙으면 금액이 아니다 — 「1,000곳」 · 「100,000천원」(27차 R26-08).
_BARE_AMOUNT_RE = re.compile(
    r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])"
    r"(?!\s*(?:%|퍼센트|회|시간|분|일|개월|년|명|건|개|점|억|만|천|백|원|페이지|쪽|배|곳|팀|단계|여"
    r"|종(?![료합사])|차(?![등례량])|주(?![요제의관최간])|인(?![상하건증정])|대(?![상학표회비응한\d])))"
)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
#: 기관명 모양. 「~부터」·「~처럼」은 기관이 아니다(9-28 시험 실행: 협약일부터 · 라벨링처럼이 기관으로 잡혔다).
_ORG_RE = re.compile(r"[가-힣A-Za-z]{2,}(?:청|처|부|공사|공단|재단|센터|대학교|병원|협회|진흥원|연구원|정보원|교육원)(?![터럼])")
#: 기관 꼬리를 가졌지만 보통 낱말인 것 — 데이터바우처 · 활용신청 · 표제부 · 제공처 · 일부 …
_NOT_ORG_TAILS = ("바우처", "신청", "요청", "표제부", "제공처", "사용처", "출처", "일부", "전부", "내부", "외부", "세부")
#: 한국어 수 한 덩어리 — 「5천만원 · 3백만원 · 2천만 원 · 1억 5천만원 · 1억 2,000만원 · 3천5백만원 · 100,000천원 · 1억」
#: (26차 ISSUE-152 · 27차 R26-10). 값은 `support_requirement_extractor._krw_phrase` **한 곳**이 정한다. 숫자 비교(number_keys) ·
#: 표 금액(won) · 사람 칸 지우기(strip_human_fields)가 이 정규식 하나를 같이 쓴다. 뒤에 개수 단위가 오면 금액이 아니라
#: 개수다 — 「2만 건」 · 「5천 명」(R26-07 · 08). 끝의 「원」 앞 공백만 먹는다 — 「3억 규모」의 공백은 남긴다(26차 검수 DV-7).
_KRW_UNIT = r"(?:[천백십][억만]?|[억만])"
_MONEY_RE = re.compile(
    rf"(?<![\d.,])\d[\d,]*(?:\.\d+)?\s*{_KRW_UNIT}(?:\s*\d[\d,]*(?:\.\d+)?\s*{_KRW_UNIT})*(?:\s*원)?"
)
#: 개수 단위 뒤 경계 — 조사 · 이음말 하나까지만 붙고 그 뒤는 한글이 아니어야 한다. 「1억 부가세」 · 「5천만 개발비」 ·
#: 「10억원 회사」의 부 · 개 · 회는 단위가 아니라 다음 낱말의 첫 글자다(27차 검수 C1 · C2).
_COUNT_TAIL = (
    r"(?:이|가|을|를|은|는|의|에|과|와|도|로|만|씩|에게|에서|으로|까지|부터|이상|이하|이내|미만|초과|가량|정도|내외|규모|당)?"
    r"(?![가-힣])"
)
#: 수 뒤에 붙으면 금액이 아닌 개수 단위 (「2만 건」 · 「5천 명」 · 「3인」 = 명 · 「1만 시간」 · 「5천 점」).
_AFTER_COUNT_RE = re.compile(
    r"\s*(개월|시간|페이지|명|인(?![상하건증정])|건|곳|개|회|팀|종(?![료합사])|대(?![상학표회비응한\d])|주(?![요제의관최간])"
    r"|부|권|장|점|일|년|배|쪽|분)" + _COUNT_TAIL
)
#: 「500여 곳」 · 「2만여 명」의 「여」 — 대략이라는 말일 뿐 값은 같다(27차 R26-07). 셈 전에 뺀다.
_APPROX_RE = re.compile(r"(\d[천백십만억]?)\s*여(?![성자름부행유러])(?=\s*[가-힣])")
#: 공고 근거 대조에서 더 보는 개수 단위 — number_keys 가 읽지 않는 것(26차 검수 DV-1 · 27차 R26-07 · 08).
#: 앞이 「:」 · 숫자면 개수가 아니다(「16:00 종료」) · 「종료」 · 「차등」 · 「주요」 · 「인상」 · 「대상」은 낱말이다.
_COUNT_RE = re.compile(
    r"(?<![\d:.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(곳|팀|종(?![료합사])|단계|차(?![등례량])|주(?![요제의관최간])|인(?![상하건증정])|대(?![상학표회비응한\d]))"
)
#: 온전한 날짜 — 공고 근거 대조가 양쪽에서 **(월, 일) 짝** 하나로 읽는다(27차 R26-01 · 검수 C3). 「2026.9.15.」 · 「’27.5.31.」 ·
#: 「2026-10-08」 · 「10.8.(목)」 · 범위 「9.15.(화) ~ 10.6.(화)」. 일을 따로 열쇠로 두면 기간 「30일 이내」와 섞이고,
#: 월 · 일을 따로 맞추면 「10.15.」가 「9.15. ~ 10.6.」을 통과했다. 「90.5점」 · 「4.2~4.5.」 같은 소수는 날짜가 아니다 —
#: 연도 · 요일이 붙었거나, 범위의 왼쪽이 「M.D.」(끝에 점)일 때만 날짜다.
_DATE_SIDE = r"(?:(?:20\d{2}|[’'‘]\d{2})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})"
_WEEKDAY = r"(?:\s*\(\s*[월화수목금토일]\s*\))?"
_DATE_RANGE_RE = re.compile(
    rf"(?<![\d.]){_DATE_SIDE}\s*\.{_WEEKDAY}\s*(?:\d{{1,2}}:\d{{2}}\s*)?[~～∼–]\s*{_DATE_SIDE}\s*\.?(?!\d)"
)
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![\d-])20\d{2}-(\d{1,2})-(\d{1,2})(?![\d-])"),
    re.compile(r"(?<![\d.])(?:20\d{2}|[’'‘]\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)"),
    re.compile(r"(?<![\d.])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*\(\s*[월화수목금토일]\s*\)"),
)
#: 「10월 6일」 — 풀어 쓴 날짜도 같은 (월, 일) 짝이다(공고 「10.6.(화)」와 같은 날).
_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
#: 두 자리 연도 + 월(「27년 3월」) — 따옴표가 없어도 날짜다(기간 「27년」이 아니다 · 검수 C7).
_BARE_SHORT_YEAR_RE = re.compile(r"\s*\d{1,2}\s*월")
_MONTH_WORD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*월")  # 「’27.3월」의 3월도 읽는다 — 「월」이 붙은 것만
#: 두 자리 연도 「’27.3월」 · 「’27. 3.」 · 「’27년」 — 공고의 날짜 모양. 「2027년」과 같은 해로 본다.
_SHORT_YEAR_RE = re.compile(r"[’'‘](\d{2})(?=\s*(?:년|\.\s*\d{1,2}\s*(?:월|\.)))")
_EXAMPLE_DATE_RE = re.compile(r"[’'‘](\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


# ---------------------------------------------------------------------------
# 숫자 — 원 단위로 맞춰 비교
# ---------------------------------------------------------------------------


def _without_approx(text: str) -> str:
    """「500여 곳」 → 「500곳」 — 대략이라는 「여」는 값을 바꾸지 않는다 (27차 R26-07)."""
    return _APPROX_RE.sub(r"\1", text or "")


def _scaled_keys(text: str, spans: list[tuple[int, int]]) -> set[tuple[str, float]]:
    """한국어 수 덩어리 → 금액(("won", 원)) 또는 개수(("명", 5000)). 읽은 자리는 `spans` 에 적는다.

    「2만 건」 · 「5천 명」은 금액이 아니다(R26-08). 천 · 백만 붙고 원도 개수 단위도 없으면(「5천」) 읽지 않는다.
    """
    keys: set[tuple[str, float]] = set()
    for match in _MONEY_RE.finditer(text):
        phrase = match.group(0)
        value = float(support_requirement_extractor._krw_phrase(phrase))
        with_won = phrase.rstrip().endswith("원")
        after = None if with_won else _AFTER_COUNT_RE.match(text, match.end())
        if after:
            unit = "명" if after.group(1) == "인" else after.group(1)
            keys.add((unit, value))
            spans.append((match.start(), after.end()))
        elif with_won or re.search(r"[억만]", phrase):
            keys.add(("won", value))
            spans.append(match.span())
    return keys


def number_keys(text: str) -> set[tuple[str, float]]:
    """글 속 숫자를 비교 열쇠로 — 돈은 ("won", 원), 연도는 ("year", 2026), 나머지는 (단위, 값).

    「1억 5천만원」은 **한 값**(150,000,000원)이다 — 예전에는 「1억」만 읽고 「5천만원」을 못 읽었다.
    두 자리 연도(「’27년」)는 ("year", 2027) 과 ("yy", 27) — 기간(「업력 27년」 = ("년", 27))과 열쇠가 다르다(27차 R26-09).
    """
    text = hours(_without_approx(text))
    keys: set[tuple[str, float]] = set()
    spans: list[tuple[int, int]] = []
    for match in _MONTH_DAY_RE.finditer(text):
        month, day = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            keys.add(date_key(month, day))  # 「6일」을 기간 열쇠로 따로 두지 않는다(검수 C3)
            spans.append(match.span())
    keys |= _scaled_keys(text, spans)
    for match in text_match._NUMBER_UNIT_RE.finditer(text or ""):
        if any(a <= match.start() < b for a, b in spans):
            continue
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = match.group(2)
        spans.append(match.span())
        if unit in _MONEY_UNITS:
            keys.add(("won", float(support_requirement_extractor._krw(value, unit))))
        elif unit == "년" and 2000 <= value <= 2100:
            keys.add(("year", value))
        elif (unit == "년" and value < 100 and len(match.group(1)) == 2 and "." not in match.group(1)
              and match.start() and text[match.start() - 1] in "’'‘"):
            # 「’27년」 — 두 자리 연도(26차 §4-J 시험). 연도 전용 열쇠 ("yy", 27)로 — 기간 「업력 27년」과 섞이지 않게(R26-09).
            # 여는 따옴표는 공고의 연도 표기에도 흔하다(‘27년 · 검수 C25). **닫는 따옴표가 곧 따라오는** 「‘10년 이상’」만
            # 강조로 보고 기간 열쇠도 남긴다.
            keys.add(("year", 2000 + value))
            keys.add(("yy", value))
            if text[match.start() - 1] == "‘":
                ahead = text[match.end(): match.end() + 15]
                if "’" in ahead and "‘" not in ahead[: ahead.index("’")]:
                    keys.add((unit, value))
                    keys.add(("‘yy", value))
        elif unit == "년" and value < 100 and len(match.group(1)) == 2 and _BARE_SHORT_YEAR_RE.match(text, match.end()):
            # 「27년 3월」 — 따옴표 없이도 월이 따라오면 날짜의 연도다(검수 C7).
            keys.add(("year", 2000 + value))
            keys.add(("yy", value))
        else:
            keys.add((unit, value))
    for match in _BARE_AMOUNT_RE.finditer(text or ""):
        if any(a <= match.start() < b for a, b in spans):
            continue
        keys.add(("won", float(match.group(0).replace(",", ""))))
    for match in _YEAR_RE.finditer(text or ""):
        keys.add(("year", float(match.group(1))))
    for match in _SHORT_YEAR_RE.finditer(text or ""):
        keys.add(("year", 2000.0 + int(match.group(1))))  # 「’27.3월」 · 「’27. 3.」 — 공고의 협약 기간 모양
        keys.add(("yy", float(int(match.group(1)))))
    return keys


def won(value: str | int | float | None) -> int | None:
    """표의 금액 칸 → 원. 「7,000,000」(단위 없음 = 원) · 「1억원」 · 「700만원」."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    money = [k for k in number_keys(text) if k[0] == "won"]
    if money:
        return int(money[0][1])
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


# ---------------------------------------------------------------------------
# 날짜 — 협약 기간 안인가
# ---------------------------------------------------------------------------

_FULL_DATE_RE = re.compile(r"[’'‘]?(\d{4}|\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\.?")
_YM_APOS_RE = re.compile(r"[’'‘](\d{2})\s*\.\s*(\d{1,2})\s*월?")
_YM_FULL_RE = re.compile(r"(?<!\d)(20\d{2})\s*[.년]\s*(\d{1,2})\s*월?")
_MONTH_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*월")


def _year(raw: str) -> int:
    value = int(raw)
    return value + 2000 if value < 100 else value


def parse_months(text: str) -> list[tuple[int | None, int]]:
    """글 속 날짜를 (연, 월) 목록으로. 연을 알 수 없는 「3월」은 (None, 3)."""
    found: list[tuple[int, tuple[int | None, int]]] = []
    taken: list[tuple[int, int]] = []

    def add(match: re.Match, year: int | None, month: int) -> None:
        if any(a < match.end() and match.start() < b for a, b in taken) or not 1 <= month <= 12:
            return
        taken.append(match.span())
        found.append((match.start(), (year, month)))

    for match in _FULL_DATE_RE.finditer(text or ""):
        add(match, _year(match.group(1)), int(match.group(2)))
    for match in _YM_APOS_RE.finditer(text or ""):
        add(match, _year(match.group(1)), int(match.group(2)))
    for match in _YM_FULL_RE.finditer(text or ""):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in _MONTH_RE.finditer(text or ""):
        add(match, None, int(match.group(1)))
    return [ym for _, ym in sorted(found)]


def agreement_window(period: dict[str, Any] | None) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """협약 기간 → ((시작 연, 월), (끝 연, 월)). 「협약일～’27.3월(5개월)」 → ((2026, 11), (2027, 3)).
    시작이 날짜가 아닌 입찰 사업기간(「계약 체결일 ~ 2027년 12월 15일」 · `open_start` · 개월 수 없음)은 끝 쪽만 본다(시작 (1, 1) · 2.8.0 B6)."""
    if not period or not period.get("end"):
        return None
    year, month = (int(x) for x in str(period["end"]).split("-"))
    if period.get("open_start") and not period.get("months"):
        return (1, 1), (year, month)
    months = int(period.get("months") or 12)
    start_index = year * 12 + (month - 1) - (months - 1)
    return (start_index // 12, start_index % 12 + 1), (year, month)


def outside_window(text: str, window: tuple[tuple[int, int], tuple[int, int]] | None) -> list[str]:
    """협약 기간 밖의 날짜(원문 조각). 기간을 모르면 빈 목록."""
    if window is None:
        return []
    (sy, sm), (ey, em) = window
    start, end = sy * 12 + sm, ey * 12 + em
    bad: list[str] = []
    for year, month in parse_months(text):
        if year is None:
            inside = any(start <= y * 12 + month <= end for y in (sy, ey))
        else:
            inside = start <= year * 12 + month <= end
        if not inside:
            bad.append(f"{year or ''}.{month}월".lstrip("."))
    return bad


# ---------------------------------------------------------------------------
# 근거 대조
# ---------------------------------------------------------------------------


def won_label(amount: float) -> str:
    """원 단위 금액을 사람이 쓰는 모양으로 — 300,000,000 → 「3억원」 · 50,000,000 → 「5,000만원」."""
    if amount and amount % 100_000_000 == 0:
        return f"{amount / 100_000_000:g}억원"
    if amount >= 100_000_000 and amount % 10_000 == 0:
        eok, rest = divmod(amount, 100_000_000)
        return f"{eok:g}억 {rest / 10_000:,.0f}만원"
    if amount and amount % 10_000 == 0:
        return f"{amount / 10_000:,.0f}만원"
    return f"{amount:,.0f}원"


def date_keys(text: str) -> set[tuple[str, float]]:
    """온전한 날짜 — (월, 일) 짝 열쇠 하나와 그 달 ("월", m) (27차 R26-01 · 검수 C3). 「10월 6일」은 number_keys 가 같은 짝으로 읽는다."""
    keys: set[tuple[str, float]] = set()
    taken: list[tuple[int, int]] = []

    def add(month: int, day: int) -> None:
        if 1 <= month <= 12 and 1 <= day <= 31:
            keys.add(("월", float(month)))
            keys.add(date_key(month, day))

    for match in _DATE_RANGE_RE.finditer(text or ""):
        taken.append(match.span())
        add(int(match.group(1)), int(match.group(2)))
        add(int(match.group(3)), int(match.group(4)))
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            if any(a < match.end() and match.start() < b for a, b in taken):
                continue
            taken.append(match.span())
            add(int(match.group(1)), int(match.group(2)))
    return keys


def _notice_extra_keys(text: str) -> set[tuple[str, float]]:
    # 달은 「월」로 적힌 것과 온전한 날짜만 — 「‘90.5점」을 날짜로 읽지 않게(parse_months 는 ’YY.M 을 날짜로 읽는다).
    text = _without_approx(text)
    months = {("월", float(m)) for m in _MONTH_WORD_RE.findall(text or "") if 1 <= int(m) <= 12}
    counts = {("명" if unit == "인" else unit, float(n.replace(",", ""))) for n, unit in _COUNT_RE.findall(text or "")}
    return months | counts | date_keys(text)


def _same_year(key: tuple[str, float], have: set[tuple[str, float]]) -> bool:
    """「’27년」(두 자리) ↔ 「2027년」 · 「’27.3월」 — 같은 해를 다른 모양으로 쓴 것.

    두 자리 연도는 전용 열쇠 ("yy", 27) 로만 잇는다 — 기간 「업력 27년」(("년", 27))이 지어낸 「’27년」을 통과시키지 않게(R26-09).
    """
    if key[0] == "year" and 2000 <= key[1] < 2100:
        return ("yy", key[1] - 2000) in have
    if key[0] == "yy":
        return ("year", 2000 + key[1]) in have
    return False


def date_key(month: int, day: int) -> tuple[str, float]:
    return ("날짜", float(month * 100 + day))


def _key_label(key: tuple[str, float]) -> str:
    """사람이 읽는 꼴 — 3억원 · 2027년 · 10월 8일 · 1,000,000명 · 90.5점 (지수 표기 없이 · 검수 C12)."""
    unit, value = key
    if unit == "won":
        return won_label(value)
    if unit == "year":
        return f"{int(value)}년"
    if unit == "날짜":
        return f"{int(value) // 100}월 {int(value) % 100}일"
    return f"{value:,.0f}{unit}" if float(value).is_integer() else f"{value:g}{unit}"


def unsupported_bits(text: str, sources: Iterable[str], *, orgs: bool = True) -> list[str]:
    """문장의 숫자 · 연도 · 기관명 중 근거 글에 없는 것. `orgs=False` 면 숫자 · 금액 · 연도만 본다."""
    joined = " ".join(s for s in sources if s)
    have = number_keys(joined)
    keys = number_keys(text)
    if not orgs:
        # 공고 근거 대조는 월 · 곳 · 팀 · 종 · 단계 · 차도 본다 — 「최종 보고 ’27.5월」 · 「학교 5곳」이 3월 조항을 달고 나가지 않게.
        have |= _notice_extra_keys(joined)
        keys |= _notice_extra_keys(text)
    missing: list[str] = []
    for key in sorted(keys, key=lambda k: (k[0], k[1])):
        if key in have or _same_year(key, have):
            continue
        if key[0] in ("년", "yy", "‘yy") and key[1] < 100 and ("year", 2000 + key[1]) in keys:
            continue  # 「’28년」의 두 번째 · 세 번째 열쇠 — 연도로 한 번만 적는다
        if key[0] == "year" and ("‘yy", key[1] - 2000) in keys and ("년", key[1] - 2000) in have:
            continue  # 닫는 따옴표까지 있는 강조 「‘10년 이상’」 — 근거에 기간 「10년」이 있으면 그 뜻이다(그 밖에는 연도)
        label = _key_label(key)
        missing.append(label)
    if not orgs:
        return missing
    joined_compact = compact(joined)
    for match in _ORG_RE.finditer(text or ""):
        if match.group(0).endswith(_NOT_ORG_TAILS):
            continue
        if compact(match.group(0)) not in joined_compact:
            missing.append(match.group(0))
    return missing


def strip_examples(text: str, examples: dict[str, Any], sources: Iterable[str] = ()) -> tuple[str, int]:
    """양식 예시 값과**만** 같은 숫자 · 날짜를 「(담당자 입력)」으로 바꾼다. (바꾼 글, 바꾼 수)."""
    example_won = {float(n) for n in examples.get("numbers") or []}
    example_dates = set(examples.get("dates") or [])
    have = number_keys(" ".join(s for s in sources if s))
    removed = 0

    def swap_amount(match: re.Match) -> str:
        nonlocal removed
        keys = number_keys(match.group(0))
        money = {k for k in keys if k[0] == "won"}
        if money and all(k[1] in example_won and k not in have for k in money):
            removed += 1
            return HUMAN_INPUT
        return match.group(0)

    out = re.sub(r"\d{1,3}(?:,\d{3})+\s*(?:원|만원|억원)?|\d+(?:\.\d+)?\s*(?:억원|만원|원)", swap_amount, text or "")

    def swap_date(match: re.Match) -> str:
        nonlocal removed
        iso = f"20{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        if iso in example_dates:
            removed += 1
            return HUMAN_INPUT
        return match.group(0)

    out = _EXAMPLE_DATE_RE.sub(swap_date, out)
    # 양식의 자리표시(000 · 0000.00.00 · 00.00.00.~00.00.00. · 0000년 00월 00일 · 000-0000-0000)가 그대로 나오면 빈칸이다.
    # 끝의 점은 떼고 찾는다(「0000.00.00.」 — 문장 끝 마침표와 같은 모양).
    zeros = {r.rstrip(". ") for r in examples.get("raw") or [] if re.fullmatch(r"[0\s.,:~\-()‘’'년월일]+", r)}
    placeholders = sorted((p for p in zeros if "0" in p), key=len, reverse=True)
    if placeholders:
        # 숫자에 붙어 있거나 쉼표 · 점 · 붙임표로 숫자와 이어지면 자리표시가 아니다 — 「1,000원」 · 「062-000-1234」 · 「3.000」.
        pattern = re.compile("|".join(f"(?<!\\d)(?<!\\d[,.\\-]){re.escape(p)}(?!\\d)(?![,.\\-]\\d)" for p in placeholders))
        out, count = pattern.subn(HUMAN_INPUT, out)
        removed += count
    return out, removed


# ---------------------------------------------------------------------------
# 사람만 채우는 칸
# ---------------------------------------------------------------------------

_HUMAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("연락처", re.compile(r"(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("사업자등록번호", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")),
    ("법인등록번호", re.compile(r"(?<!\d)\d{6}-\d{7}(?!\d)")),
    ("대표자", re.compile(r"대표자(?:명)?\s*[:：]\s*[가-힣A-Za-z]{2,10}")),
    ("주소", re.compile(r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\S*\s+\S+(?:구|시|군)\s+\S+(?:로|길)\s*\d+(?:-\d+)?")),
)
#: 사람 칸의 금액 · 사람 수 한 덩어리 — 「1억원」 · 「5천 명」(개수 단위까지 함께 지운다).
_HUMAN_AMOUNT_RE = re.compile(f"(?:{_MONEY_RE.pattern})(?:(?<!원){_AFTER_COUNT_RE.pattern})?")
_PEOPLE_MONEY_RE = re.compile(r"매출(?:액)?|고용\s*인원|직원\s*수|임직원|상시\s*근로자")
#: 회사 규모를 사람 수로 말하는 모양 — 「17인 규모」 · 「당사는 17명」(고용인원은 사람만 채운다).
_COMPANY_SIZE_RE = re.compile(r"\d+\s*(?:명|인)\s*규모|(?:당사|회사|우리)\S{0,2}\s+\d+\s*(?:명|인)")


def strip_human_fields(text: str, keep: Iterable[str] = ()) -> tuple[str, list[str]]:
    """사람만 채우는 값을 지우고 「(담당자 입력)」. (바꾼 글, 지운 칸 이름들).

    `keep` — 지우지 않을 글(공고에서 확인한 인용). 공고 자격 조항 「직전년도 매출액 5천만원 이상」을 인용한 문장에서 공고의
    기준값을 지우면 안 된다(26차 검수 DV-3). 호출자가 공고문에서 찾은 조각만 넘긴다 — 지어낸 인용은 지켜 주지 않는다.
    """
    removed: list[str] = []
    out = text or ""
    # 긴 것부터 가린다 — 짧은 조각이 긴 인용의 일부를 먼저 가려 긴 인용을 못 찾게 되지 않게(27차 R26-02).
    # 사람 칸을 지키는 인용은 길거나(압축 8자 이상) 자격 낱말(매출 · 고용 …)이 든 것만 — 「1억원 규모」 같은 조각은
    # 회사 매출을 지켜 주지 못한다(검수 C8).
    guard = [p for p in keep if p and p in out and (len(compact(p)) >= 8 or _PEOPLE_MONEY_RE.search(p) or _COMPANY_SIZE_RE.search(p))]
    ordered = sorted(set(guard), key=len, reverse=True)
    masks = {chr(0xE000 + i): piece for i, piece in enumerate(ordered)}
    for mark, piece in masks.items():
        out = out.replace(piece, mark)
    out, removed = _strip_human(out, removed)
    for mark, piece in masks.items():
        out = out.replace(mark, piece)
    return out, removed


def _strip_human(out: str, removed: list[str]) -> tuple[str, list[str]]:
    for name, pattern in _HUMAN_PATTERNS:
        if pattern.search(out):
            out = pattern.sub(HUMAN_INPUT, out)
            removed.append(name)
    # 「17인」은 number_keys 가 숫자로 읽지 않는다 — 숫자가 있기만 하면 본다. **실제로 바꾼 것이 있을 때만** 적는다
    # (「2027년까지 매출 확대를 목표로 3단계로」는 바꿀 것이 없다 · 26차 ISSUE-152).
    if (_PEOPLE_MONEY_RE.search(out) or _COMPANY_SIZE_RE.search(out)) and re.search(r"\d", out):
        out, money = _HUMAN_AMOUNT_RE.subn(HUMAN_INPUT, out)
        out, plain = re.subn(r"\d[\d,]*(?:\.\d+)?\s*(?:억원|만원|원|억|만|명|인)", HUMAN_INPUT, out)
        if money + plain:
            removed.append("매출액·고용인원")
    return out, removed


#: 인용 조각으로 세지 않는 말 — 단위 · 이음말만으로는 「공고에서 확인한 문장」이 아니다.
_QUOTE_FILLER = frozenset(
    {"억원", "만원", "천원", "천만원", "백만원", "개월", "시간", "이상", "이하", "이내", "미만", "초과",
     "까지", "부터", "정도", "내외", "최대", "최소", "연간", "과제별", "기업당"}
)


def meaningful_quote(piece: str) -> bool:
    """공고 인용으로 쓸 만한 조각인가 (27차 R26-02 · 06).

    「1억원」 · 「/ 22개」 같은 짧은 조각은 공고 어디에나 있어, 인용이라며 달면 숫자 대조 · 사람 칸 지우기를 빠져나갔다.
    압축 8자 이상이거나, 단위 · 이음말이 아닌 2자 이상 한글 낱말이 있어야 한다.
    """
    if len(compact(piece)) >= 8:
        return True
    return any(word not in _QUOTE_FILLER for word in re.findall(r"[가-힣]{2,}", piece or ""))


def banned_words(text: str) -> list[str]:
    return sorted({m.group(0) for m in BANNED_RE.finditer(text or "")})


# ---------------------------------------------------------------------------
# 공고 문장 복사
# ---------------------------------------------------------------------------


class NoticeIndex:
    """공고문을 한 번 다듬어 두고 여러 문장을 잰다."""

    WINDOW = 30
    RATIO = 0.7

    def __init__(self, notice_text: str | None) -> None:
        lines = [re.sub(r"\f?\[쪽 \d+\]", "", line).strip() for line in (notice_text or "").split("\n")]
        lines = [line for line in lines if line]
        self.compact = compact(" ".join(lines))
        # 공고 한 대목 = 이어진 세 줄(PDF 줄은 문장 중간에서 끊긴다).
        self.units = [compact(" ".join(lines[i : i + 3])) for i in range(len(lines))]

    def copy_reason(self, sentence: str, *, exclude: Iterable[str] = ()) -> str | None:
        text = sentence or ""
        for token in exclude:
            if token and len(token) >= 2:
                text = text.replace(token, " ")
        body = compact(text)
        if not self.compact or len(body) < 10:
            return None
        for start in range(0, max(0, len(body) - self.WINDOW + 1)):
            if body[start : start + self.WINDOW] in self.compact:
                return f"공고문과 연속 {self.WINDOW}자 이상 같다"
        grams = {body[i : i + 8] for i in range(0, max(0, len(body) - 7))}
        for unit in self.units:
            if len(unit) < 10 or sum(1 for g in grams if g in unit) < 2:
                continue
            matched = sum(block.size for block in SequenceMatcher(None, body, unit, autojunk=False).get_matching_blocks())
            if matched / len(body) >= self.RATIO:
                return f"문장의 {int(self.RATIO * 100)}% 이상이 공고 한 대목과 겹친다"
        return None

    def contains(self, quote: str) -> bool:
        body = compact(quote)
        return bool(body) and body in self.compact


# ---------------------------------------------------------------------------
# 정량값 — 개월차 · 자기 나열 단계 · 문장 안 합계 · 원문 기준 수치 · 계산값(3차 지시서 §5 · 2.9.0)
# ---------------------------------------------------------------------------

#: 숫자 바로 뒤 「H」 = 시간(「7H * 5회」 — 원문 과정표 꼴). 입찰 숫자 대조(`number_keys` · 합계 · 기준 수치)에서만 읽는다 — 공용 숫자 정규식
#: (`text_match` · 제출 전 점검 일치 점수)은 그대로 둔다(3차 검토 — 점검에 「14H 는 원문에 없는 숫자」 오탐이 생겼다). 「235 H스퀘어」 · 「H.310」 ·
#: 「4H-클럽」은 아니다.
_HOURS_RE = re.compile(r"(?<=\d)H(?![A-Za-z0-9.\-])")


def hours(text: str) -> str:
    return _HOURS_RE.sub("시간", text or "")


#: 「n개월차 · n~m개월차 · n~m주차」 — 작성 지시가 일정을 이 꼴로 쓰라고 한다(원문에 없는 숫자가 아니다 · 주차는 짧은 사업 · 2.10.0 D1).
_MONTH_ORDINAL_RE = re.compile(r"\d+\s*(?:~\s*\d+\s*)?(?:개월|주)\s*차")
_STEP_RE = re.compile(r"(\d+)\s*(?:개\s*)?단계")
#: 줄 머리 단계 번호(「1단계(1개월차): …」) — 단계 이름표다. 「○ 5단계: …」(쌍점)는 나열 수와 견주도록 남긴다.
_STEP_HEAD_RE = re.compile(r"^[\s\-–•○]*\d+\s*단계\s*(?=[(（])")


def number_text(text: str) -> str:
    """원문 숫자 대조에 넣을 글 — 개월차 · 줄 머리 단계 번호(「1단계(1개월차)」) · 문장이 스스로 나열한 단계 수(「→」나 「 · 」로 나눈 항목 수와
    같은 「n단계」)를 뺀다(11-11 2 · 3위 Claude 「4단계 · 6단계」 · 1804104 「… · 보완 및 납품의 5단계」가 「없는 숫자」 오경보였다).
    나열과 수가 다르면 그대로 대조한다."""
    out = _STEP_HEAD_RE.sub("", _MONTH_ORDINAL_RE.sub("", text or ""))
    listed = {out.count(sep) + 1 for sep in ("→", " · ") if sep in out}
    return _STEP_RE.sub(lambda m: "" if int(m.group(1)) in listed else m.group(0), out)


#: 「총 210회」 · 「합계 51회」 — 문장 안 합계(단위가 같은 앞 숫자들의 합과 견준다).
_TOTAL_RE = re.compile(r"(?:총|합계|합\s*계)\s*(?:은|는|:|：)?\s*(\d[\d,]*)\s*(회|명|건|개|시간)(?!차|사|단|예|물|강|월|발|선|표)")
#: 곱셈 인수 · 주기 값(「7시간×5회」 · 「월 1회」 · 「격주 2회」)이 있는 문장은 합계를 견주지 않는다(오경보보다 놓침).
_FACTOR_RE = re.compile(r"[×xX*]\s*\d|(?<![가-힣])(?:매월|매주|매년|격월|격주|월|주|분기|반기|연|회당|인당)\s*\d")
#: 단위당 값(「회당 50명」 · 「1인당 10만원」 · 「20명씩」)은 합계의 구성이 아니다 — 지운다.
_PER_RE = re.compile(r"당\s*\d[\d,]*(?:\.\d+)?\s*(?:회|명|건|개|시간)|\d[\d,]*(?:\.\d+)?\s*(?:회|명|건|개|시간)\s*씩")
#: 앞 절(「…를 열고, 」 · 「…하며, 」)의 숫자는 이 합계의 몫이 아니다.
_CLAUSE_RE = re.compile(r"(?:고|며)\s*[,，]\s*")


def sum_breaks(text: str) -> str | None:
    """한 문장 안 합계가 어긋나면 그 까닭 — 「정보주체 160회 · 처리자 40회 · 관리자 10회 등 총 200회」(앞 숫자 합 210 ≠ 200).
    괄호 안 구성(「16회(10+6)」) · 단위당 값 · 앞 절 숫자는 세지 않는다. 같은 단위 앞 숫자가 둘 이상일 때만 · 곱셈 · 주기 값이 있거나
    마지막 항목과 「총」 사이에 다른 숫자가 끼면(「5회 운영해 총 35시간」 · 「등 6기수로 총 120명」) 견주지 않는다(3차 검토)."""
    text = hours(text)
    for match in _TOTAL_RE.finditer(text or ""):
        unit = match.group(2)
        total = float(match.group(1).replace(",", ""))
        before = _CLAUSE_RE.split(_PER_RE.sub("", re.sub(r"[(（][^)）]*[)）]", "", text[: match.start()])))[-1]
        if _FACTOR_RE.search(before):
            continue
        last = None
        for last in re.finditer(r"\d[\d,]*(?:\.\d+)?\s*" + unit, before):
            pass
        if last and re.search(r"\d", before[last.end():]):
            continue
        parts = [token.value for token in text_match.extract_numbers(before) if token.unit == unit]
        if len(parts) >= 2 and abs(sum(parts) - total) > 1e-6:
            return f"{' + '.join(f'{v:g}' for v in parts)} = {sum(parts):g}{unit} ≠ 총 {total:g}{unit}"
    return None


#: 원문 기준 수치 — 「낱말(값 단위)」(「뉴스레터(4회)」 · 「전문가 풀(105명)」 · 「멘토(최소 5명)」) · 「낱말 값 단위 이상 · 이하 · 내외」.
#: 괄호도 한정어도 없는 맨 「낱말 값 단위」는 뜻이 흐려(「정보주체: 아동 110회」) 받지 않는다(오경보보다 놓침 · 2.9.0 실측).
_FACT_PAREN_RE = re.compile(r"(?<![가-힣A-Za-z])([가-힣A-Za-z]{2,12})\s*[(（]\s*(총|연|월|회당|최소|최대|약)?\s*(\d[\d,]*(?:\.\d+)?)\s*(회|명|건|점|%|시간)(?![가-힣A-Za-z])")
_FACT_BOUND_RE = re.compile(r"(?<![가-힣A-Za-z])([가-힣A-Za-z]{2,12})\s*(?:은|는|:|：)?\s*(최소|최대)?\s*(\d[\d,]*(?:\.\d+)?)\s*(회|명|건|점|%|시간)\s*(이상|이하|내외|미만)")
#: 괄호 앞머리 → 한정어(「최소 5명」 = 5명 이상) · 연 · 월 · 회당은 비율이라 기준 수치로 쓰지 않는다.
_FACT_PREFIX = {"최소": "이상", "최대": "이하", "약": "내외", "총": "", "": ""}
#: 낱말 끝 조사 — 「가 · 이」는 떼지 않는다(「전문가」 · 「기술능력평가」가 잘렸다 · 주격 「이」는 아래에서 따로).
_FACT_JOSA = ("으로", "은", "는", "을", "를", "의", "에", "와", "과", "로", "만")
#: 기준 수치 이름으로 쓰기에 흔한 낱말 — 여러 뜻이라 짝으로 쓰지 않는다.
_FACT_GENERIC = frozenset(
    "교육 운영 과정 사업 전체 인원 기준 이상 이하 최소 최대 대상 내외 이내 매년 매월 연간 기간 회차 실시 진행 목표 달성 규모 합계 총 약 "
    "연 월 주 회당 각 기타 등 및 집합 온라인 오프라인 과목 강의 프로그램 지원 제공 참여 실습 특강 시간 일정 인력 전문가 위한 관리 기획 "
    "활용 제작 배포 분석 완료일 지급시 추가선금 선금 고정점수 가격평가 기술능력평가 기술평가 배점 점수 평가 경우 미만 비율 평가기준 배점한도 "
    "기관 기업".split())
#: 한글 문서의 사용자 정의 글자(낱말을 가르는 기호로 쓰인다 — 「워크샵세미나」).
_PUA_RE = re.compile("[\ue000-\uf8ff]")


def _fact_label(raw: str) -> str:
    for josa in _FACT_JOSA:
        if raw.endswith(josa) and len(raw) - len(josa) >= 2:
            return raw[: -len(josa)]
    if raw.endswith("이") and len(raw) >= 3 and raw[:-1] not in _FACT_GENERIC:  # 「실적이」 → 「실적」(주격 · 「인원이」는 흔한 낱말이라 버려짐)
        return raw[:-1]
    return raw


def notice_facts(text: str) -> list[dict[str, Any]]:
    """원문(발췌)의 기준 수치 — [{label, value, unit, bound, quote}]. 같은 이름 · 단위에 값이 둘 이상이거나 앞 낱말이 여럿이면(「보건·의료 특화(4회)」 ·
    「행정·공공 특화(4회)」 — 뜻이 여럿) 뺀다(오경보보다 놓침 · 3차 검토). bound — 「이상 · 이하 · 미만 · 내외」(없으면 정확한 값).
    평가 탈락 문턱(「85% 미만 … 탈락」) · 비율(연 · 월 · 회당) · 관형형 이름(「이용한」)은 기준 수치가 아니다. 작성기가 같은 값을 보고 쓰고,
    거르기 · 품질 게이트가 같은 값과 다시 대조한다(3차 지시서 §5 「같은 데이터를 참조」)."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for line in hours(_PUA_RE.sub("·", text or "")).splitlines():
        if "탈락" in line:
            continue
        for pattern in (_FACT_PAREN_RE, _FACT_BOUND_RE):
            for match in pattern.finditer(line):
                label = _fact_label(match.group(1))
                if len(label) < 2 or label in _FACT_GENERIC or label.endswith("한") or line[max(0, match.start(1) - 1):match.start(1)] in "·‧ㆍ" and match.start(1):
                    continue
                prefix = match.group(2) or ""
                if prefix in ("연", "월", "회당"):
                    continue
                bound = (match.group(5) or "") if pattern is _FACT_BOUND_RE else _FACT_PREFIX.get(prefix, "")
                previous = re.search(r"([가-힣A-Za-z·‧ㆍ]+)\s+$", line[:match.start(1)])
                entry = seen.setdefault((label, match.group(4)), {"label": label, "unit": match.group(4), "values": set(), "prev": set(),
                                                                  "bound": bound, "quote": line.strip()[:120]})
                entry["values"].add(float(match.group(3).replace(",", "")))
                entry["prev"].add(previous.group(1) if previous else "")
                entry["bound"] = entry["bound"] or bound
    return [{"label": e["label"], "unit": e["unit"], "value": next(iter(e["values"])), "bound": e["bound"], "quote": e["quote"]}
            for e in seen.values() if len(e["values"]) == 1 and len(e["prev"]) == 1]


#: 기준 수치 이름 뒤 몇 글자 안의 첫 숫자를 그 값으로 본다(「뉴스레터는 격월 2회」 · 「정보주체: 아동 110회」는 9자라 보지 않는다).
FACT_WINDOW = 8


def fact_conflicts(text: str, facts: list[dict[str, Any]], allowed: Iterable[tuple[str, float]] = ()) -> list[str]:
    """문장 속 기준 수치가 원문 값과 어긋나면 「뉴스레터 2회 · 원문 4회」 — 이름(앞이 낱말 경계 · 「비대면」 속 「대면」 아님) 바로 뒤(8자 안)
    첫 숫자의 단위가 같을 때만 견준다(숫자만 같다고 일치로 보지 않는다 · 3차 지시서 §5). 「이상」 기준은 더 낮을 때만 · 「이하 · 미만」은 더
    높을 때만(더 엄격한 계획 · 지난 실적 「4.9점」은 어긋남이 아니다) · 「1회당」 같은 단위당 값은 견주지 않는다. allowed — 원문 계산값(「53건」)."""
    text = hours(text)
    keep = set(allowed)
    out: list[str] = []
    for fact in facts:
        for match in re.finditer(rf"(?<![가-힣A-Za-z]){re.escape(fact['label'])}", text or ""):
            tail = text[match.end(): match.end() + FACT_WINDOW]
            tokens = text_match.extract_numbers(tail)
            if not tokens:
                continue
            token = tokens[0]
            after = match.end() + tail.find(token.raw) + len(token.raw)
            if token.unit != fact["unit"] or (token.unit, token.value) in keep or re.match(r"\s*당", text[after:]):
                break
            bound = fact.get("bound") or ""
            wrong = (token.value < fact["value"] if bound == "이상" else token.value > fact["value"] if bound in ("이하", "미만")
                     else abs(token.value - fact["value"]) > 1e-9 if bound != "내외" else False)
            if wrong:
                out.append(f"{fact['label']} {token.raw} · 원문 {fact['value']:g}{fact['unit']}{(' ' + bound) if bound else ''}")
            break
    return out


_PERCENT_RE = re.compile(r"전체[^.\n]{0,30}?(?:최소\s*)?(\d{1,3})\s*%")
_POOL_RE = re.compile(r"[(（]\s*(\d{2,4})\s*명\s*[)）]")
_APPROX_TAIL_RE = re.compile(r"약\s*(\d+)\s*(건|명)")


def derived_counts(text: str) -> list[dict[str, Any]]:
    """원문 백분율의 계산값 — 「전문가 풀(105명)」 뒤 「전체 … 최소 50%(약 50건)」 → 최소 53(올림 · 3차 지시서 §5 사례 1).
    원문 근사값(「약 50건」)과 다르면 approx 에 남긴다 — 원문 표현은 그대로 두고 검토 목록에서 확인한다(모호한 원문을 고쳐 쓰지 않는다)."""
    out: list[dict[str, Any]] = []
    for match in _PERCENT_RE.finditer(text or ""):
        pools = list(_POOL_RE.finditer(text, max(0, match.start() - 1500), match.start()))
        if not pools:
            continue
        base, percent = int(pools[-1].group(1)), int(match.group(1))
        if not 0 < percent <= 100:
            continue
        approx = _APPROX_TAIL_RE.search(text[match.end(): match.end() + 20])
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        out.append({"base": base, "percent": percent, "value": math.ceil(base * percent / 100),
                    "unit": approx.group(2) if approx else "명", "approx": int(approx.group(1)) if approx else None,
                    "quote": text[start: end if end != -1 else None].strip()[:120]})
    return out


# ---------------------------------------------------------------------------
# 과업 용어 — 원문 과업 줄의 행위 · 대상 · 방식 낱말을 본문이 약한 말로 바꿨나(2.10.0 T3 · 11-13 동국대 「해외 VC 대상 피칭 코칭」 →
# 「해외 VC 관점의 피칭 코칭」 · 「현지화 실무 컨설팅」 → 「현지화 실무 점검」 · 저장 초안 1,451문장 중 1건)
# ---------------------------------------------------------------------------

#: 과업 구의 끝 낱말(행위) — 조사가 붙은 낱말(「교육을」)은 구가 아니다.
_TASK_HEAD_RE = re.compile(r"(?:컨설팅|코칭|미팅|교육|강의|진단|실증|매칭|네트워킹)$")
#: 과업 줄 — 글머리(「- ∙ ○ •」)로 시작하는 줄 · 구는 「→ , ( ) 및」에서 끊는다.
_TASK_LINE_RE = re.compile(r"^\s*[-∙•○◦ㅇ·]\s*")
_TASK_SPLIT_RE = re.compile(r"→|[,，()（）]|\s및\s")
#: 구 머리가 될 수 없는 낱말 — 꾸밈 서술어(「위한 · 통해 · 따른」) · 조사로 끝나는 낱말(「운영에 · 전략을」) · 기호만(「+」).
#: 이 낱말이 창 안에 있으면 그 뒤부터 구(T3 검토 — 「위한 기업별 맞춤형 컨설팅」은 본문에 「위한」까지 있어야 맞아 약화를 놓쳤다).
_PHRASE_STOP_RE = re.compile(r"(?:위한|위해|통한|통해|따른|따라|대한|관한|의한)$|\S(?:에|을|를|에서|으로)$|^[^가-힣A-Za-z0-9]+$")
#: 약한 말(「대상 → 관점」 · 「컨설팅 → 점검」) — 「과제로 정리해 전달」 같은 서술어 약화는 이 검사가 못 잡는다(지시문으로 막음).
_WEAK = r"(관점|점검|정리|검토|안내|전달|참고|소개)"
#: 낱말 뒤 조사까지만 — 「관점의」 · 「코칭으로」는 같은 낱말 · 「점검표를」은 다른 낱말.
_PARTICLE = r"(?:의|을|를|은|는|이|가|으로|로|과|와|에|도|만)?(?![가-힣])"
#: 다른 방식을 발주기관과 협의할 대안 · 지연 대응으로 쓴 문장은 약화가 아니다.
_SOFT_OK_RE = re.compile(r"협의|대안|지연|어려운")


def task_phrases(excerpt: str) -> list[str]:
    """원문 과업 줄(글머리)에서 행위 낱말로 끝나는 2~4 낱말 구(낱말 사이 공백은 하나로) — 「VC 대상 피칭 코칭」 · 「현지화 실무 컨설팅」 ·
    「PoC 실증」 · 「대면 미팅」."""
    out: dict[str, None] = {}
    for line in (excerpt or "").splitlines():
        if not _TASK_LINE_RE.match(line):
            continue
        for part in _TASK_SPLIT_RE.split(_TASK_LINE_RE.sub("", line)):
            words = part.split()
            for end, word in enumerate(words):
                if not (end and _TASK_HEAD_RE.search(word)):
                    continue
                start = max(0, end - 3)
                start = next((k + 1 for k in range(end - 1, start - 1, -1) if _PHRASE_STOP_RE.search(words[k])), start)
                if end > start:
                    out.setdefault(" ".join(words[start: end + 1]))
    return list(out)


def softened_terms(text: str, phrases: Iterable[str], sources: Iterable[str] = ()) -> list[tuple[str, str]]:
    """본문이 원문 과업 구의 낱말 하나만 약한 말로 바꾼 곳 → [(원문 구, 본문 글)]. 협의 대안 · 지연 대응 문장 · 원문 구를 그대로 쓴 문장 ·
    원문(`sources`)이 이미 그 말을 쓴 곳은 아니다(근사 · 경고만). 괄호 · 병기 대안(「대면(화상) 미팅」 · 「대면 · 화상 미팅」)은 품질 게이트 REMOTE_SWAP 이 본다."""
    text = text or ""
    if _SOFT_OK_RE.search(text):
        return []
    body = compact(text)
    joined: str | None = None
    out: list[tuple[str, str]] = []
    for phrase in phrases:
        words = phrase.split()
        # 낱말 하나만 바뀐 창만 — 나머지 낱말이 모두 본문에 있을 때만 정규식을 만든다(대부분 여기서 걸러짐)
        if len(words) < 2 or compact(phrase) in body or sum(1 for w in words if w in text) < len(words) - 1:
            continue
        for i, word in enumerate(words):
            if re.fullmatch(_WEAK, word):
                continue
            parts = [_WEAK + _PARTICLE if k == i else re.escape(w) + _PARTICLE for k, w in enumerate(words)]
            parts[-1] = parts[-1].replace(_PARTICLE, f"(?={_PARTICLE})")  # 끝 낱말 뒤 조사는 본문 글에 넣지 않는다
            match = re.search(r"(?<![가-힣A-Za-z0-9])" + r"\s*".join(parts), text)
            if not match:
                continue
            if joined is None:
                joined = compact(" ".join(s for s in sources if s))
            if compact(" ".join([*words[:i], match.group(1), *words[i + 1:]])) in joined:
                continue  # 원문이 그 말을 이미 쓴다
            out.append((phrase, match.group(0).strip()))
            break
    return out


# ---------------------------------------------------------------------------
# 예산 표 산수(2.10.0 D3 · 11-13 동국대 — 수정본은 렌더 스크립트 assert 로만 검산했다) — 품질 게이트 · 제출 PDF 검사가 같은 함수
# ---------------------------------------------------------------------------

#: 끝 줄 이름 — 합계(「합계(부가세 포함)」이라 부가세 낱말보다 먼저 본다) · 소계(공급가액) · 부가가치세. 이름 머리에서만(과업 이름 속
#: 「사. 총사업비 집행 계획」은 항목 줄 · T5 검토).
_BUDGET_TOTAL_RE = re.compile(r"^\s*(?:총\s*)?(?:합\s*계|총\s*계|총\s*액|총\s*사업비)")
_BUDGET_SUB_RE = re.compile(r"^\s*(?:소\s*계|공급\s*가액)")
_BUDGET_VAT_RE = re.compile(r"^\s*(?:부가\s*(?:가치)?\s*세|VAT)", re.I)
#: 산출 「10개사 × 1회 × 300,000」 · 「1.5개월 × 1,600,000」 · 「5,000,000 × 50%」 — 곱하는 수(수 뒤 % · 단위 낱말은 건너뜀 · 괄호는 지우고 본다).
_PRODUCT_NUM = r"\d[\d,]*(?:\.\d+)?\s*%?\s*[가-힣]{0,4}"
_PRODUCT_RE = re.compile(rf"{_PRODUCT_NUM}(?:\s*[×xX*✕]\s*{_PRODUCT_NUM})+")
#: 한 줄 글(PDF) 끝 금액 — 「… 2회 × 2,000,000 4,000,000」 · 「소계(공급가액) 37,000,000원」.
_LINE_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원?\s*$")


def _budget_row(row: Any) -> tuple[str, str, int | None]:
    """예산 표 한 행 → (이름, 산출 글, 금액). 칸 목록이면 끝 칸이 금액 · 그 앞이 산출 · 나머지가 이름(과업 · 항목),
    한 줄 글이면 끝 숫자가 금액 · 곱셈 앞이 이름."""
    if isinstance(row, str):
        tail = _LINE_AMOUNT_RE.search(row)
        body = row[: tail.start()] if tail else row
        product = _PRODUCT_RE.search(body)
        return (body[: product.start()] if product else body).strip(" (（"), body, won(tail.group(1)) if tail else None
    cells = [str(cell) for cell in row]
    name = " ".join(c.strip() for c in cells[:-2] if c.strip()) or (cells[0] if cells else "")
    return name, " ".join(cells[-2:-1]), won(cells[-1]) if cells else None


def is_budget_total(row: Any) -> bool:
    """예산 표 끝 「합계」 줄인가(칸 목록 · 한 줄 글) — 제출 PDF 검사가 표 끝을 찾는다(2.10.0 T8)."""
    return bool(_BUDGET_TOTAL_RE.search(_budget_row(row)[0]))


def budget_breaks(rows: Iterable[Any], cap_won: int | None = None) -> list[str]:
    """예산 표 산수가 어긋난 곳(글 목록) — 행마다 「수량 × 단가 = 금액」 · 항목 합 = 소계(공급가액 · 소계 · 부가세 줄이 없으면 합계) ·
    부가세 = 소계의 10%(원 끝수 ±1) · 소계 + 부가세 = 합계 · 합계 ≤ 사업금액(`cap_won`).
    행은 칸 목록(초안 · 워드 표)이나 한 줄 글(PDF — 끝 숫자가 금액). 사람이 채운 항목 금액이 하나도 없으면 판정하지 않고(빈 표 · 코드가 채운
    끝 줄만), 빈칸(「(담당자 입력)」) 항목이 남으면 합은 견주지 않는다."""
    out: list[str] = []
    items: list[int] = []
    blank = False
    sub = vat = total = None
    for row in rows:
        name, basis, amount = _budget_row(row)
        if _BUDGET_TOTAL_RE.search(name):
            total = amount
        elif _BUDGET_SUB_RE.search(name):
            sub = amount
        elif _BUDGET_VAT_RE.search(name):
            vat = amount
        elif amount is not None:
            items.append(amount)
            if product := _PRODUCT_RE.search(re.sub(r"[()（）]", " ", basis)):
                value = math.prod(float(n.replace(",", "")) / (100 if pct else 1)
                                  for n, pct in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(%?)", product.group(0)))
                if abs(value - amount) >= 1:
                    out.append(f"「{name}」 {re.sub(r'\s+', ' ', product.group(0)).strip()} = {round(value):,} ≠ {amount:,}")
        elif unwritten_count(row if isinstance(row, str) else " ".join(str(c) for c in row)):
            blank = True
    if not items:
        return []
    head = sub if sub is not None else total if vat is None else None
    if not blank and head is not None and sum(items) != head:
        out.append(f"항목 합 {sum(items):,} ≠ {'소계' if sub is not None else '합계'} {head:,}")
    if sub is not None and vat is not None and abs(vat * 10 - sub) > 10:
        out.append(f"부가세 {vat:,} ≠ 소계의 10% {round(sub / 10):,}")
    if sub is not None and vat is not None and total is not None and sub + vat != total:
        out.append(f"소계 + 부가세 {sub + vat:,} ≠ 합계 {total:,}")
    if cap_won and total is not None and total > cap_won:
        out.append(f"합계 {total:,} > 사업금액 {cap_won:,}")
    return out
