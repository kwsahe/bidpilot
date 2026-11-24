"""공고문 일정표 · 제출서류 뽑기 (43차 결정 1 · H1 · H6 · ELIG-06).

나라장터 직찰 · 우편 공고는 입찰 마감이 비어 있고, 공고문 1쪽 일정표에만 참가신청 · 입찰등록 · 제출 마감이 있다
(가천대 해커톤: 참가신청 10/30 10:00 · 필수 현장설명 11/02 · 입찰등록 11/10). 이 모듈은 **받아 둔 공고문 글**에서
그 날짜와 「필수 현장설명」 여부, 단계별 제출서류를 규칙으로 뽑는다. 판정은 하지 않는다 — 실제 마감은 부르는 쪽이
나라장터 값과 함께 가장 이른 것을 고른다(`practical_priority.effective_deadline`).

뽑지 않는 것: 개찰 · 평가 · 심사 · 발표 · 통보 · 선정 · 협상 · 접수 개시 · 제출 시작 · 사업 · 계약 · 보험 기간. 범위(「11/12 09:00 ~
11/16 10:00」 · 「11월 12일 09시 ~ 17일 18시」)는 끝 날짜만. 날짜 앞뒤에 마감 · 등록 · 신청 · 제출 낱말이 없으면 버린다(서명란 날짜 · 공고일).
표 행(한 줄에 날짜 여럿)은 머리줄 칸 수와 날짜 수가 같을 때만 칸 순서로 짝짓는다(44차 R36-J-02).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Final

KST: Final = timezone(timedelta(hours=9))

#: 마감으로 쓰는 갈래 — 실제 마감은 이 중 가장 이른 것(결정 1). 필수 현장설명은 지나면 「사실상 마감」이라 함께 센다.
DEADLINE_KINDS: Final = ("application", "registration", "submission")
KIND_LABEL: Final = {
    "application": "참가신청 마감",
    "registration": "입찰등록 마감",
    "submission": "제출 마감",
    "briefing": "현장설명",
}

_FULL_DATE: Final = re.compile(
    r"(?<!\d)(20\d\d)\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?\s*\.?\s*(?:\(\s*[월화수목금토일]\s*\))?"
)
_SHORT_DATE: Final = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\.|월)\s*(\d{1,2})\s*일?\s*\.?\s*\(\s*[월화수목금토일]\s*\)"
)
_TIME: Final = re.compile(r"(?<!\d)(\d{1,2})\s*(?::|：|시)\s*(\d{2})?(?:\s*분)?")
#: 시각을 읽지 않는 곳(44차 R36-J-05) — 괄호 안(「[점심시간 12:00~13:00]」) · 「점심 · 중식」 뒤
_BRACKETED: Final = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_LUNCH: Final = re.compile(r"점심|중식")
#: 범위 끝이 날만 적힌 꼴 — 「11월 12일(목) 09시 ~ 17일(화) 18시」 · 「11. 9.(월)~13.(금)」(연 · 월은 앞 날짜에서 · R36-J-01)
#: 「부터 5일간 · ~ 7일 이내」는 기간이지 날짜가 아니다(44차 마지막 검토) — 「일」 뒤 간 · 이내 · 동안 · 후 · 전 · 이상 · 째는 읽지 않는다.
_DAY_ONLY_END: Final = re.compile(
    r"(?:~|∼|부터)\s*(\d{1,2})\s*(?:일(?!\s*(?:간|이내|동안|후|전|이상|이전|째))|\.(?=\s*\())\s*\.?\s*(?:\(\s*[월화수목금토일]\s*\))?"
)
#: 날짜 바로 뒤 기간(「10. 26.(월)부터 5일간」 · 「~ 7일 이내」) — 그 날짜는 끝을 모르는 시작일이다(마감으로 쓰지 않음 · 44차 마지막 검토)
_DURATION_AFTER: Final = re.compile(r"^\s*(?:~|∼|부터)\s*\d{1,3}\s*일\s*(?:간|이내|동안)")
#: 범위 「A ~ B」 사이 — 시각 · 요일 괄호(「(화요일)」) · 짧은 낱말(「공고 시」)은 넘는다(44차 마지막 검토 — 넘지 못해 시작일이 마감으로 남았다)
_RANGE_GLUE: Final = re.compile(
    r"^\s*(?:\d{1,2}\s*(?::|시)\s*\d{0,2}\s*(?:분)?)?\s*(?:[(\[][^()\[\]]{0,6}[)\]])?\s*(?:[가-힣]{1,3}(?:\s+[가-힣]{1,2})?)?\s*(?:~|∼|-|부터)\s*$"
)

_APPLICATION: Final = re.compile(r"참가\s*신청|사전\s*(?:신청|등록)")
_REGISTRATION: Final = re.compile(r"입찰\s*등록|참가\s*등록|입찰참가\s*등록|등록\s*마감")
_SUBMISSION: Final = re.compile(
    r"(?:제출|접수)\s*(?:마감|기한|기간|일)|마감\s*일시|제안서\s*(?:제출|접수)|입찰서\s*(?:제출|접수)|서류\s*제출|까지\s*(?:제출|접수|도착)"
)
_BRIEFING: Final = re.compile(r"현장\s*설명|현설|설명회")
_BRIEFING_NONE: Final = re.compile(r"없으며|개최하지\s*않|진행하지\s*않|대체|생략|별도로\s*계획되어\s*있지\s*않")
_EXCLUDE: Final = re.compile(
    r"개찰|평가|심사|발표|통보|선정|협상|개시|시작|공고일|공고\s*기간|입찰공고|계약\s*기간|사업\s*기간|과업\s*기간|보험\s*기간|유효\s*기간|납품|발급|기준일|작성일"
)
_DEADLINE_WORD: Final = re.compile(r"마감|까지|기한")
#: 질의 · 질문 · 문의 · 이의 · 의견 · 정정 요청 기한은 참가 마감이 아니다(43차 마지막 검토) — 제안서 · 입찰서 · 등록 · 참가신청 낱말이 같이 있을 때만 마감으로 본다.
_NOT_DEADLINE: Final = re.compile(r"질의|질문|문의|이의|의견\s*(?:제출|등록|접수)|정정\s*요청")
_TRUE_DEADLINE: Final = re.compile(r"(?:제안서|입찰서|서류)\s*(?:제출|접수)|입찰\s*등록|참가\s*(?:신청|등록)")
#: 필수 현장설명 — 「미신청시 현설참여 불가」 · 「현장설명에 참가한 업체로서」 · 「미지참시 현장설명 참석 불가」 · 「지각 시 참여불가」
_REQUIRED: Final = re.compile(
    r"미\s*(?:신청|참석|참가)\s*시|불참|참가자에\s*한하여|참(?:여|석|가)\s*불가|현장\s*설명(?:회)?에\s*참(?:가|석)한\s*(?:업체|자)|필참|반드시\s*참석"
)
_HEADING: Final = re.compile(r"^\s*(?:\d{1,2}|[가-하])\s*[.)]\s*\S")
#: 날짜 바로 앞이 시작 쪽이면 마감이 아니다(44차 R36-J-01 — 「제출 시작일시: 11/12(목) 10:00」)
_START_SIDE: Final = re.compile(r"시작|개시")
#: 「바로 앞」 — 앞 글을 범위 기호 · 시각에서 끊은 마지막 조각(「접수 시작 및 마감: A ~ B」의 B 앞은 「~」 뒤 빈칸 · 44차 마지막 검토)
_NEAR_CUT: Final = re.compile(r"[~∼]|\d{1,2}\s*(?::|시)\s*\d{0,2}")
#: 표 머리줄의 칸 머리 — 갈래 낱말이 나오는 곳마다 새 칸(「참가신청 마감 현장설명 입찰등록 마감」 = 3칸 · 44차 마지막 검토)
_COLUMN_HEAD: Final = re.compile("|".join(p.pattern for p in (_APPLICATION, _REGISTRATION, _SUBMISSION, _BRIEFING, _EXCLUDE)))
#: 서명란(R36-J-02) — 「위와 같이 공고합니다.」 바로 뒤 날짜만 있는 줄은 공고일이다
_SIGNED: Final = re.compile(r"공고합니다|공고함")
#: 앞선 머리말로 갈래를 대신 정할 때는 그 줄(또는 바로 위 짧은 이름 줄)에 이 낱말이 있어야 한다(R36-J-02)
_ANCHOR: Final = re.compile(r"일\s*시|일\s*자|기\s*한|까지|마감")

#: 단계별 제출서류 머리말(H6) — 「5. 참가신청시 제출서류」 · 「6. 현장설명 준비서류」 · 「7. 입찰 등록 제출서류」
_DOC_HEADINGS: Final = (
    ("참가신청", re.compile(r"참가\s*신청\s*시?\s*(?:제출\s*)?서류")),
    ("현장설명", re.compile(r"현장\s*설명\s*(?:시\s*)?(?:준비|지참|제출)\s*서류")),
    ("입찰등록", re.compile(r"입찰\s*(?:참가\s*)?등록\s*(?:시\s*)?(?:제출\s*)?서류|입찰\s*참가\s*(?:제출\s*)?서류|등록\s*서류|입찰자\s*제출\s*서류")),
)
_ITEM_MARK: Final = re.compile(r"^\s*(?:[가-하]\s*[.)]|\d{1,2}\s*\)|[○◦·•\-－㉮-㉿①-⑳]|\(\d{1,2}\))\s*")
_TOP_HEADING: Final = re.compile(r"^\s*\d{1,2}\s*\.\s*\S")
#: 할 일로 따로 짚을 준비물(H6) — 보증보험 비율 · 인감 · 완납 · 청렴 · 재무 · 실적 · 제품소개서
KEY_DOCS: Final = ("인감", "보증", "완납", "청렴", "재무제표", "실적증명", "제품소개서", "직접생산", "등기", "사업자등록증")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _masked(window: str) -> str:
    """시각을 읽을 글 — 괄호 안과 「점심」 뒤는 같은 길이의 빈칸으로(자리는 그대로 · R36-J-05).

    괄호 밖에 시각이 하나도 없으면 괄호 안 시각을 쓴다(「2026.10.26. (10:00 ~ 17:00)」 — 점심 뒤는 그래도 지운다)."""

    def cut_lunch(text: str) -> str:
        lunch = _LUNCH.search(text)
        return text[: lunch.start()] + " " * (len(text) - lunch.start()) if lunch else text

    out = cut_lunch(_BRACKETED.sub(lambda m: " " * len(m.group()), window))
    return out if _TIME.search(out) else cut_lunch(window)


def _dates(line: str, year_hint: int) -> list[tuple[int, int, datetime, bool]]:
    """줄 안의 날짜 `(시작, 끝, 날짜시각, 시각을 읽었나)`. 시각이 범위(「09:00~15:00」 · 「09:00부터 15:00까지」)면 끝 시각."""
    spans: list[tuple[int, int, int, int, int]] = []
    for match in _FULL_DATE.finditer(line):
        spans.append((match.start(), match.end(), int(match.group(1)), int(match.group(2)), int(match.group(3))))
    for match in _SHORT_DATE.finditer(line):
        if any(s <= match.start() < e for s, e, *_ in spans):
            continue
        spans.append((match.start(), match.end(), year_hint, int(match.group(1)), int(match.group(2))))
    spans.sort()
    # 범위 끝이 날만 적힌 꼴 — 바로 앞 날짜의 연 · 월을 이어받는다(날이 작아지면 다음 달 · R36-J-01)
    for match in _DAY_ONLY_END.finditer(line):
        start = match.start(1)
        if any(s <= start < e for s, e, *_ in spans):
            continue
        before = [span for span in spans if span[1] <= match.start() and match.start() - span[1] <= 20]
        if not before:
            continue
        _s, _e, year, month, first_day = before[-1]
        day = int(match.group(1))
        if day < first_day:
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        spans.append((start, match.end(), year, month, day))
    spans.sort()
    out: list[tuple[int, int, datetime, bool]] = []
    for index, (start, end, year, month, day) in enumerate(spans):
        if not (1 <= month <= 12 and 1 <= day <= 31) or _DURATION_AFTER.match(line[end:]):
            continue
        limit = spans[index + 1][0] if index + 1 < len(spans) else min(len(line), end + 40)
        window = _masked(line[end:limit])
        hour, minute, known = 23, 59, False
        times = [(m, m.start()) for m in _TIME.finditer(window) if int(m.group(1)) <= 24]
        if times:
            until = next((m for m, pos in times if window[m.end():m.end() + 4].strip().startswith("까지")), None)
            chosen = until or times[-1][0]
            hour, minute, known = int(chosen.group(1)), int(chosen.group(2) or 0), True
            if hour == 24:
                hour, minute = 23, 59  # 「24:00까지」 = 그날 끝(같은 날 00:00 이 아니다 · 44차 마지막 검토)
            if hour < 12 and "오후" in window[max(0, chosen.start() - 4):chosen.start()]:
                hour += 12  # 「오후 6시까지」 = 18:00(R36-J-05)
            end = end + chosen.end()
        try:
            at = datetime(year, month, day, hour, minute, tzinfo=KST)
        except ValueError:
            continue
        out.append((start, end, at, known))
    # 범위 「A ~ B」 · 「A부터 B까지」 의 앞 날짜는 시작일이다 — 끝 날짜만 남긴다.
    kept: list[tuple[int, int, datetime, bool]] = []
    for index, item in enumerate(out):
        nxt = out[index + 1] if index + 1 < len(out) else None
        if nxt is not None and _RANGE_GLUE.match(line[item[1]:nxt[0]]):
            continue
        kept.append(item)
    return kept


def _columns(label: str, count: int) -> list[str]:
    """머리줄을 칸으로 — 갈래 낱말이 시작하는 곳에서 끊는다(첫 낱말 앞 글은 첫 칸에). 칸 수가 날짜 수와 다르면 빈 목록(R36-J-02)."""
    starts = [m.start() for m in _COLUMN_HEAD.finditer(label)]
    if not starts:
        return []
    starts[0] = 0
    cells = [label[a:b].strip() for a, b in zip(starts, starts[1:] + [len(label)])]
    return cells if len(cells) == count else []


def _kind(context: str) -> str | None:
    """날짜 앞뒤 글의 갈래. 마감 낱말이 있으면 「개찰 · 평가」가 같이 있어도 마감이다(「입찰마감 및 개찰」)."""
    has_deadline = bool(_DEADLINE_WORD.search(context))
    if _NOT_DEADLINE.search(context) and not _TRUE_DEADLINE.search(context):
        return None
    if _EXCLUDE.search(context) and not (has_deadline and (_REGISTRATION.search(context) or _SUBMISSION.search(context)
                                                           or _APPLICATION.search(context))):
        return None
    if _APPLICATION.search(context):
        return "application"
    if _REGISTRATION.search(context):
        return "registration"
    if _SUBMISSION.search(context):
        return "submission"
    if _BRIEFING.search(context) and not _BRIEFING_NONE.search(context):
        return "briefing"
    if re.search(r"까지", context) and re.search(r"제출|접수|등록", context):
        return "submission"
    return None


def extract(lines: Sequence[tuple[int, str]], *, year_hint: int, not_before: datetime | None = None) -> dict[str, Any]:
    """`lines` = `(쪽, 줄)` 목록(공고문 전체). 반환: `{items, briefing_required, briefing_required_text, documents}`.

    `items` 의 각 줄은 `{kind, label, at(ISO · KST), time_known, page, text}` — 같은 갈래 · 같은 날짜는 시각을 읽은 쪽 하나만.
    `not_before`(공고 게시일)보다 이른 날짜는 버린다(「2025. 1. 6 이후 …」 같은 안내 글)."""
    items: list[dict[str, Any]] = []
    label_line = ""
    plain_line = ""
    heading = ""
    for pos, (page, raw) in enumerate(lines):
        line = _norm(raw)
        if not line:
            continue
        found = _dates(line, year_hint)
        if not found:
            if _HEADING.match(line) and len(line) <= 40:
                heading = line
            label_line = line if len(line) <= 30 else ""
            plain_line = line
            continue
        if _SIGNED.search(plain_line) and len(line) <= 25:
            label_line = plain_line = ""
            continue  # 「위와 같이 공고합니다. / 2026. 9. 28.」 — 서명란 날짜(R36-J-02)
        # 표 행 — 짧은 머리줄은 칸 수가 날짜 수와 같을 때만 칸 순서로 짝짓는다. 다르면 버린다(첫 날짜에 붙이지 않음 · R36-J-02).
        # 칸 짝짓기는 날짜로 시작하는 표 행만(「가. 공고기간 : A ~ B」 같은 줄에 머리말 칸을 붙이지 않음 · 44차 마지막 검토)
        table_row = not _norm(line[: found[0][0]]).strip(" :·-")
        columns = _columns(label_line, len(found)) if len(found) > 1 and table_row else []
        # 첫 날짜 뒤 날짜마다 바로 앞에 「평가 · 개찰 …」이 붙은 줄(「10:00 / 평가 11.3」 · 「(개찰: …)」)은 표가 아니다 — 머리줄은 첫 날짜 것
        annotated = len(found) > 1 and all(_EXCLUDE.search(line[found[i - 1][1]:found[i][0]]) for i in range(1, len(found)))
        anchored = bool(_ANCHOR.search(f"{label_line} {line}"))
        prev_end = 0
        for index, (start, end, at, known) in enumerate(found):
            nxt = found[index + 1][0] if index + 1 < len(found) else len(line)
            context = f"{line[prev_end:start]} {line[end:nxt]}"
            prefix = line[prev_end:start]
            prev_end = end
            if _START_SIDE.search(_NEAR_CUT.split(prefix)[-1]) or re.match(r"\s*부터", line[end:]):
                continue  # 시작 쪽 날짜(R36-J-01) — 바로 앞 조각만 본다
            kind = _kind(context)
            if kind is None and len(found) > 1:
                # 칸 이름은 그 날짜 바로 앞에 「평가 · 개찰 …」이 없을 때만(개찰 시각에 「마감일시」를 붙이지 않음)
                if columns and not _EXCLUDE.search(prefix):
                    kind = _kind(columns[index])
                if kind is None and index == 0 and annotated and label_line and not _norm(line[:start]).strip(" :·-"):
                    kind = _kind(label_line)
            elif kind is None and index == 0 and not _norm(line[:start]).strip(" :·-"):
                # 바로 위 줄이 번호 붙은 머리말(「3. 제안서 제출」)이면 앞선 머리말과 같이 본다 — 마감 낱말이 있을 때만(R36-J-02)
                usable = bool(label_line) and (anchored or not _HEADING.match(label_line))
                kind = (_kind(label_line) if usable else None) or (_kind(f"{heading} {line[end:nxt]}") if heading and anchored else None)
            elif kind is None and re.search(r"일\s*시|일\s*자|기\s*한|기\s*간", context) and heading and not _EXCLUDE.search(context):
                kind = _kind(heading)  # 「1) 일 시: …」 · 「가. 기 간 : …」(44차) — 사업 · 공고 기간 같은 빼는 낱말이 있으면 머리말로 짓지 않음
            if kind is None and re.match(r"\s*까지", line[end:]):
                # 「10월 26일(월) 15시까지 실적증명서 …」 + 다음 줄 「… 직접 제출」 — 마감 문장이 줄을 넘긴 꼴(R36-J-02 연암대)
                following = next((_norm(t) for _p, t in lines[pos + 1:pos + 3] if _norm(t)), "")
                if re.search(r"제출|접수", following) and not _dates(following, year_hint):
                    kind = _kind(f"{context} {following}")
            if kind is None or (not_before is not None and at.date() < not_before.astimezone(KST).date()):
                continue
            items.append({"kind": kind, "label": KIND_LABEL[kind], "at": at.isoformat(), "time_known": known,
                          "page": page, "text": line[:120]})
        label_line = plain_line = ""
    # 같은 갈래 · 같은 날 — 시각을 읽은 것 중 이른 것 하나(KISA 표 「2026. 10. 28.」 줄과 「11:00 까지」 줄 · R36-J-05)
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["kind"], item["at"][:10])
        held = best.get(key)
        if held is None or (item["time_known"] and (not held["time_known"] or item["at"] < held["at"])):
            best[key] = item
    required_line = next(
        (_norm(t) for _p, t in lines if _BRIEFING.search(t or "") and _REQUIRED.search(t or "") and not _BRIEFING_NONE.search(t or "")),
        None,
    )
    return {
        "items": sorted(best.values(), key=lambda i: i["at"]),
        "briefing_required": required_line is not None,
        "briefing_required_text": required_line[:120] if required_line else None,
        "documents": documents(lines),
    }


def documents(lines: Sequence[tuple[int, str]]) -> list[dict[str, Any]]:
    """단계별 제출서류(H6) — 머리말 아래 표시 줄(가. · 1) · ○ · ㉮ …)을 다음 큰 머리말까지. 단계마다 12개까지."""
    out: dict[str, dict[str, Any]] = {}
    stage: str | None = None
    taken = 0
    for page, raw in lines:
        line = _norm(raw)
        if not line:
            continue
        hit = next((name for name, pattern in _DOC_HEADINGS if pattern.search(line) and len(line) <= 70), None)
        if hit is not None and (_TOP_HEADING.match(line) or _HEADING.match(line) or len(line) <= 30):
            stage, taken = hit, 0
            out.setdefault(stage, {"stage": stage, "page": page, "items": []})
            continue
        if stage is None:
            continue
        if _TOP_HEADING.match(line) and not _ITEM_MARK.match(line):
            stage = None
            continue
        if _ITEM_MARK.match(line) and taken < 12:
            item = _ITEM_MARK.sub("", line)[:70].rstrip(" .")
            if len(item) >= 3 and item not in out[stage]["items"]:
                out[stage]["items"].append(item)
                taken += 1
        if taken >= 12:
            stage = None
    return [value for value in out.values() if value["items"]]


def earliest(schedule: dict[str, Any] | None, *, after: datetime | None = None) -> dict[str, Any] | None:
    """실제 마감 후보 — 참가신청 · 입찰등록 · 제출 마감(+ 필수 현장설명) 중 가장 이른 것. `after`(공고 게시) 이전 날짜는 버린다."""
    if not schedule:
        return None
    kinds = set(DEADLINE_KINDS) | ({"briefing"} if schedule.get("briefing_required") else set())
    best: dict[str, Any] | None = None
    for item in schedule.get("items") or []:
        if item.get("kind") not in kinds:
            continue
        try:
            at = datetime.fromisoformat(str(item.get("at")))
        except ValueError:
            continue
        if after is not None and at <= after:
            continue
        if best is None or at < datetime.fromisoformat(best["at"]):
            best = item
    return best


def briefing(schedule: dict[str, Any] | None) -> dict[str, Any] | None:
    """현장설명 줄(있으면) — 필수 여부와 함께."""
    if not schedule:
        return None
    item = next((i for i in schedule.get("items") or [] if i.get("kind") == "briefing"), None)
    if item is None:
        return None
    return {**item, "required": bool(schedule.get("briefing_required"))}
