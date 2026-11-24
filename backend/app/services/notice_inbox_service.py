"""GPT 결과 붙여넣기 → 「확인 전 후보함」 (38차 §3-E-5).

사업담당자 ㅁㅍㄷ 결과(마크다운 표 · `[바로가기](url)` · 맨 URL)를 붙여 넣으면 줄마다 **LLM 없이 기계적으로**
공식 링크 · 공고명 · 기관 · 날짜 문자열을 뽑는다. 점수 · 판정은 붙이지 않는다(확인 전).

- 글은 믿지 않는다: 200KB · 300줄 상한, https 만, `javascript:` · `data:` · http 링크는 「버림(사유)」으로 센다.
- 나라장터 `bidPbancNo` · 기업마당 `pblancId` 링크는 저장본과 맞춘다(있으면 그 공고 id — 화면이 「이미 있음(n위 · 판정)」).
- 저장은 `data/private/organizations/<org>/notice_inbox.json`(회사자료 `candidates/` 폴더와 다른 이름).
- 서버는 링크를 **열지 않는다**.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core import org_storage, storage
from app.schemas.manual_notice import (
    MAX_AGENCY,
    MAX_PASTE_BYTES,
    MAX_PASTE_LINES,
    MAX_TITLE,
    InboxEntry,
    InboxPasteResult,
    InboxRejected,
)
from app.services.procurement_service import mask_contact_text

FILE_NAME = "notice_inbox.json"
#: 후보함에 남기는 줄 수 상한(오래된 「넣음 · 버림」부터 지운다). 확인 전(대기) 줄은 지우지 않는다 — 넘으면 새 줄을 받지 않는다(39차 MANUAL-05).
MAX_ENTRIES = 500
#: 붙여 넣은 한 줄의 글자 상한(39차 MANUAL-02 — 끊김 없는 20만 자 한 줄이 연락처 가림 · 링크 찾기에서 50초 걸렸다). 넘는 뒤쪽은 보지 않는다.
MAX_LINE_CHARS = 4000
#: 맨 주소 끝에 붙은 한글 · 전각 문장부호(「…/12345에서」 · 「…?id=7）」 · 「…/1，마감」 · 「…/reg」」)는 주소가 아니다(39차 MANUAL-06).
#: 40차 MANUAL-04 — **끝에 붙은 것만** 자른다. 첫 한글부터 끝까지 지우면 「?schStr=인공지능&page=2」가 「?schStr=」로 잘렸다.
_URL_TAIL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3\u3000-\u303f\uff00-\uffef」』〉》]+$")
_URL_TAIL_MARKS_RE = re.compile(r"[\u3000-\u303f\uff00-\uffef」』〉》]+$")


def trim_url_tail(url: str) -> str:
    """맨 주소 끝의 한글 · 전각 부호를 자른다 — 「=」 바로 뒤 한글(쿼리 값 「?q=인공지능」)은 남기고 그 뒤 전각 부호만 자른다."""
    url = url.rstrip(".,;")
    found = _URL_TAIL_RE.search(url)
    if found:
        url = _URL_TAIL_MARKS_RE.sub("", url) if url[: found.start()].endswith("=") else url[: found.start()]
    return url.rstrip(".,;")

_MD_LINK_RE = re.compile(r"\[([^\]]{0,200})\]\(\s*([^)\s]+)\s*\)")
_BARE_URL_RE = re.compile(r"(?<![(\[\w])((?:https?|javascript|data|vbscript|file|ftp):[^\s<>|)\]]+)", re.IGNORECASE)
_DATE_RE = re.compile(r"(?:20\d{2}[-./]\s?)?\d{1,2}[-./]\s?\d{1,2}(?:\s*\(?[월화수목금토일]\)?)?(?:\s*\d{1,2}:\d{2})?")
_BOLD_RE = re.compile(r"\*\*|__|`")
_SEPARATOR_ROW_RE = re.compile(r"^\|?\s*:?-{2,}")
_EMOJI_ONLY_RE = re.compile(r"^[\W\d_]{0,4}$")
_TITLE_HEADS = ("공고명", "공고", "사업명", "사업", "후보", "제목")
_AGENCY_HEADS = ("기관", "발주", "주관")
_DATE_HEADS = ("마감", "기한")
#: 「접수」는 접수기간 · 접수마감일 때만 날짜 칸이다(43차 M15 · SOURCE-04 — 「접수방식」 칸을 날짜로 읽었다).
_DATE_HEAD_EXTRA_RE = re.compile(r"접수\s*(?:기간|마감|기한|일)")
_PUBLISHED_HEADS = ("공고일", "게시일", "등록일")
#: GPT 표의 판단 칸 — 「❌ 제외」 · 「제외 — 사유」(43차 Q19).
_JUDGE_HEADS = ("판단", "분류", "판정", "구분")
_EXCLUDE_RE = re.compile(r"❌|제외|비추천")
#: 링크 앞 글이 이런 것뿐이면 공고명이 아니다 — 가장 가까운 위쪽 제목을 쓴다(43차 M15 · SOURCE-05).
_NOT_TITLE_RE = re.compile(r"^(?:바로\s*가기|원문|공고|링크|규격서|판단|상세|보기|열기|→|-)?$")
_HEADING_RE = re.compile(r"^\s*#{1,4}\s+(.+)$")


def path_of(organization_id: str) -> Path:
    return org_storage.storage_for(organization_id).root / FILE_NAME


def load(organization_id: str, *, quarantine: bool = True) -> list[InboxEntry]:
    """후보함 줄. 저장본이 깨졌으면 `CorruptJsonError` 를 그대로 올린다 — 화면에 사유(원본을 옮겨 둔 파일 이름)가 간다.

    (2.0.6) 예전에는 [] 로 읽어, 다음 붙여넣기 · 버리기가 빈 목록으로 새 파일을 써 옛 줄이 화면에서 말없이 사라졌다.
    `quarantine=False` 는 오류를 삼키는 곁 읽기(브리핑 · 「넣음」 표시)용 — 파일을 옮기지 않아 첫 409 를 후보함 화면이 받는다.
    """
    payload = storage.read_json(path_of(organization_id), default=None, quarantine=quarantine)
    rows = (payload or {}).get("entries") if isinstance(payload, dict) else None
    out: list[InboxEntry] = []
    for row in rows or []:
        try:
            out.append(InboxEntry.model_validate(row))
        except ValueError:
            continue
    return out


def _save(organization_id: str, entries: list[InboxEntry]) -> None:
    pending = [e for e in entries if e.status == "pending"]
    done = [e for e in entries if e.status != "pending"]
    # 대기 줄이 상한을 넘으면 처리한 줄은 남기지 않는다(`done[-0:]` 은 전부라 파일이 계속 커졌다 · 38차 검토)
    room = MAX_ENTRIES - len(pending)
    keep = pending[-MAX_ENTRIES:] + (done[-room:] if room > 0 else [])
    storage.write_json_atomic(path_of(organization_id), {
        "_note": "확인 전 후보함 — GPT · 사람이 찾은 공고 링크(점수 · 판정 없음 · 38차 §3-E)",
        "entries": [e.model_dump(mode="json") for e in keep],
    })


def _entry_id(url: str, title: str | None = None) -> str:
    # 구분자 「|」는 공고명이 없어도 넣는다 — 38차 줄의 id 는 sha1(주소)였다. 빼면 공고명 없이 다시 붙인 같은 주소가 그 옛 줄과
    # id 가 겹쳐(중복 판정은 주소 + 공고명이라 둘 다 들어온다) 버리기 · 넣음 표시가 옛 줄에만 걸렸다(39차 마지막 검토).
    key = url.strip() + "|" + " ".join((title or "").split())
    return "inbox-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _key(url: str, title: str | None) -> tuple[str, str]:
    """같은 줄인가 — 주소 · 공고명 둘 다(39차 MANUAL-03 — 한 게시판 주소의 다른 공고 둘이 한 줄로 합쳐졌다)."""
    return url.strip(), "".join((title or "").split())


def _plain(text: str) -> str:
    """셀 글 — 굵게 · 코드 표시를 걷고 링크는 글자만 남긴다."""
    text = _MD_LINK_RE.sub(lambda m: m.group(1), text)
    return " ".join(_BOLD_RE.sub("", text).split()).strip(" -·:")


def _clip(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or stripped.count("|") < 3:
        return None
    return [c.strip() for c in stripped.strip("|").split("|")]


def _header_map(cells: list[str]) -> dict[str, int] | None:
    """표 머리줄이면 {title, agency, date} 칸 번호. 링크가 있는 줄은 머리줄이 아니다."""
    plain = [_plain(c) for c in cells]
    found: dict[str, int] = {}
    for index, cell in enumerate(plain):
        if "title" not in found and any(cell == h or (cell.startswith(h) and h != "공고") for h in _TITLE_HEADS) and "일" not in cell:
            found["title"] = index
        elif "agency" not in found and any(h in cell for h in _AGENCY_HEADS) and len(cell) <= 8:
            found["agency"] = index
        elif "published" not in found and any(h in cell for h in _PUBLISHED_HEADS) and len(cell) <= 8:
            found["published"] = index
        elif "date" not in found and (any(h in cell for h in _DATE_HEADS) or _DATE_HEAD_EXTRA_RE.search(cell)) and len(cell) <= 8:
            found["date"] = index
        elif any(cell.startswith(h) for h in _JUDGE_HEADS) and len(cell) <= 8 and ("judge" not in found or cell.startswith("판단")):
            found["judge"] = index  # 「판단」 칸이 있으면 그것(「분류」보다 사유가 길다)
    return found if "title" in found else None


def _links(line: str) -> list[tuple[int, int, str]]:
    """줄 안의 링크 — `(시작, 끝, 주소)`. 마크다운 링크와 맨 주소 둘 다."""
    # 마크다운 링크 중 대상이 주소 꼴이 아닌 것(「[52844](앵커)」 같은 문서 안 표시)은 링크가 아니다 — 버림으로도 세지 않는다.
    md = list(_MD_LINK_RE.finditer(line))
    spans: list[tuple[int, int, str]] = [(m.start(), m.end(), m.group(2)) for m in md if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", m.group(2))]
    taken = [(m.start(), m.end()) for m in md]
    for m in _BARE_URL_RE.finditer(line):
        if not any(a <= m.start() < b for a, b in taken):
            spans.append((m.start(), m.end(), trim_url_tail(m.group(1))))
    return sorted(spans)


def _reject_reason(url: str) -> str | None:
    lower = url.lower()
    if re.match(r"^(javascript|data|vbscript|file):", lower):
        return "위험한 링크 — 받지 않습니다"
    if not lower.startswith("https://"):
        return "https 가 아닌 주소 — 받지 않습니다"
    if len(url) > 2000 or re.search(r"[\s<>\"']", url):
        return "주소 꼴이 깨졌습니다"
    return None


def parse(text: str) -> tuple[list[dict[str, Any]], list[InboxRejected], int, int]:
    """붙여 넣은 글 → `(후보 줄들, 버린 링크, 링크 없는 줄 수, 상한을 넘어 안 본 줄 수)`. 저장본 대조는 하지 않는다."""
    raw = text.encode("utf-8")[:MAX_PASTE_BYTES].decode("utf-8", errors="ignore")
    lines = raw.splitlines()
    truncated = max(0, len(lines) - MAX_PASTE_LINES)
    lines = lines[:MAX_PASTE_LINES]
    header: dict[str, int] | None = None
    heading: str | None = None  # 가장 가까운 위쪽 제목(#) — 「## {사전규격명}」 · 「# 🥇 1순위 — {공고명}」
    found: list[dict[str, Any]] = []
    rejected: list[InboxRejected] = []
    without_link = 0
    for line_no, line in enumerate(lines, start=1):
        line = line[:MAX_LINE_CHARS]
        # 줄의 전화 · 이메일을 먼저 가린다 — 공고명 · 기관 칸에 남지 않고, 전화번호 조각이 날짜로 잡히지 않게(38차 검토)
        line = mask_contact_text(line)
        if not line.strip():
            header = None  # 빈 줄 = 표가 끝났다
            continue
        head = _HEADING_RE.match(line)
        if head:
            text_head = _plain(head.group(1))
            heading = text_head.split(" — ", 1)[1].strip() if " — " in text_head else text_head
        cells = _cells(line)
        if cells is not None and _SEPARATOR_ROW_RE.match(line.strip()):
            continue
        links = _links(line)
        if cells is not None and not links:
            header = _header_map(cells) or header
            continue
        if not links:
            if line.strip() and not line.lstrip().startswith("#"):
                without_link += 1
            continue
        good = []
        for start, end, url in links:
            reason = _reject_reason(url)
            if reason:
                rejected.append(InboxRejected(line_no=line_no, reason=reason))
            else:
                good.append((start, end, url))
        if not good:
            continue
        if cells is not None and len(good) == 1:
            # 표 한 줄 — 머리줄이 있으면 그 칸, 없으면 글자가 가장 긴 칸이 공고명 · 그다음이 기관.
            plain = [_plain(c) for c in cells]
            text_cells = [(i, c) for i, c in enumerate(plain) if c and not _EMOJI_ONLY_RE.match(c) and not _DATE_RE.fullmatch(c)]
            title = agency = None
            if header and header.get("title") is not None and header["title"] < len(plain):
                title = plain[header["title"]] or None
                if header.get("agency") is not None and header["agency"] < len(plain):
                    agency = plain[header["agency"]] or None
            if not title and text_cells:
                ranked = sorted(text_cells, key=lambda t: -len(t[1]))
                title = ranked[0][1]
                rest = [c for i, c in text_cells if c != title and not c.endswith("일") and "·" not in c]
                agency = rest[0] if rest else None
            dates = [c for c in plain if _DATE_RE.fullmatch(c)]
            published = None
            if header and header.get("published") is not None and header["published"] < len(plain):
                published = plain[header["published"]] or None
                dates = [d for d in dates if d != published]
            if header and header.get("date") is not None and header["date"] < len(plain):
                dates = [plain[header["date"]]] + dates
            judge = None
            if header and header.get("judge") is not None and header["judge"] < len(plain):
                judge = plain[header["judge"]] or None
            gpt_note = f"GPT: 제외 — {judge}" if judge and _EXCLUDE_RE.search(judge) else None
            found.append({"line_no": line_no, "url": good[0][2], "title": title, "agency": agency, "date_text": dates[0] if dates else None,
                          "published_text": published, "gpt_note": gpt_note})
            continue
        # 글 줄 — 링크마다 하나. 공고명은 앞 링크 끝에서 이 링크 앞까지의 글.
        previous_end = 0
        for start, end, url in links:
            chunk = _plain(line[previous_end:start])
            previous_end = end
            if (start, end, url) not in good:
                continue
            # 표 칸 · 「…12건: 」 같은 머리말은 버리고 링크 바로 앞 글만 — 공고명은 거기 있다.
            chunk = chunk.split("|")[-1]
            if ": " in chunk:
                chunk = chunk.rsplit(": ", 1)[-1]
            chunk = re.sub(r"^[,·|:\s]+|[,·|:\s]+$", "", chunk)
            date = _DATE_RE.search(chunk)
            title = re.sub(r"\(\s*\d{1,2}[/.-]\d{1,2}\s*\)\s*$", "", chunk).strip(" ,·") or None
            if (title is None or _NOT_TITLE_RE.match(title) or title.startswith(("조건부", "적극도전", "긴급검토", "판단"))) and heading:
                title = heading  # 43차 M15 — 링크 앞 글이 비었거나 판단 · 바로가기 글뿐이면 위쪽 제목
            found.append({"line_no": line_no, "url": url, "title": title, "agency": None, "date_text": date.group(0) if date else None,
                          "published_text": None, "gpt_note": None})
    return found, rejected, without_link, truncated


def paste(organization_id: str, text: str, *, now: datetime | None = None, preview: bool = False) -> InboxPasteResult:
    """붙여 넣은 글 → 후보함. `preview` 면 저장하지 않고 무엇이 들어갈지만 돌려준다(43차 N19 — 누르면 바로 저장됐다)."""
    from app.services import manual_notice_service

    moment = now or storage.utc_now()
    entries = load(organization_id)
    known = {_key(e.url, e.title) for e in entries}
    room = MAX_ENTRIES - sum(1 for e in entries if e.status == "pending")
    found, rejected, without_link, truncated = parse(text)
    index = manual_notice_service.StoreIndex()  # 저장본은 한 번만 읽는다(MANUAL-04)
    added = already = existing = maybe = refused = 0
    fresh: list[InboxEntry] = []
    for row in found:
        url = row["url"]
        title = _clip(row["title"], MAX_TITLE)
        if _key(url, title) in known:
            already += 1
            continue
        if len(fresh) >= room:
            refused += 1  # 확인 전 줄이 상한 — 지우지 않고 새 줄을 거절한다(MANUAL-05)
            continue
        known.add(_key(url, title))
        existing_id, _reason = manual_notice_service.find_existing(url, index=index)
        maybe_id = None
        if existing_id is None:
            # 43차 H4 — 공고명이 같은 나라장터 공고 · 44차 TEAM-R36-05 — 확정 「이미 있음」이 아니라 「같은 공고일 수 있음」(따로 셈)
            maybe_id, _reason = manual_notice_service.similar_existing(title, index=index)
        existing += 1 if existing_id else 0
        maybe += 1 if maybe_id else 0
        entry = InboxEntry(
            id=_entry_id(url, title), url=url, title=title, agency=_clip(row["agency"], MAX_AGENCY),
            date_text=_clip(row["date_text"], 40), existing_id=existing_id, maybe_existing_id=maybe_id,
            line_no=row["line_no"], created_at=moment,
            published_text=_clip(row.get("published_text"), 40), gpt_note=_clip(row.get("gpt_note"), 200),
        )
        fresh.append(entry)
        added += 1
    if not preview:
        _save(organization_id, entries + fresh)
    lines = text.encode("utf-8")[:MAX_PASTE_BYTES].decode("utf-8", errors="ignore").splitlines()
    first_unread = lines[MAX_PASTE_LINES] if truncated and len(lines) > MAX_PASTE_LINES else None
    return InboxPasteResult(
        preview=preview,
        first_unread_line=MAX_PASTE_LINES + 1 if truncated else None,
        first_unread_text=_clip(first_unread, 120),
        added=added, already_in_inbox=already, existing=existing, maybe_existing=maybe, lines_without_link=without_link,
        rejected=rejected, truncated_lines=truncated, entries=fresh, refused_full=refused,
    )


def discard(organization_id: str, entry_id: str, reason: str) -> InboxEntry:
    entries = load(organization_id)
    for entry in entries:
        if entry.id == entry_id:
            entry.status = "discarded"
            entry.discard_reason = " ".join(reason.split())[:300]
            _save(organization_id, entries)
            return entry
    raise LookupError(entry_id)


def mark_added(organization_id: str, entry_id: str, manual_id: str) -> None:
    try:
        # (2.0.6) 옮기지 않고 읽는다 — 여기서 옮기면 후보함 화면이 409 사유 없이 빈 목록으로 열렸다
        entries = load(organization_id, quarantine=False)
    except storage.CorruptJsonError:
        return  # 공고는 이미 저장됐다 — 후보함 「넣음」 표시만 못 한다(사유는 후보함 화면이 보인다)
    for entry in entries:
        if entry.id == entry_id:
            entry.status = "added"
            entry.manual_id = manual_id
            _save(organization_id, entries)
            return


def pending(organization_id: str) -> list[InboxEntry]:
    """확인 전 줄 — 브리핑이 센다. 저장본이 깨졌으면 브리핑은 막지 않고 빈 목록(사유는 후보함 화면이 409 로 보인다)."""
    try:
        # (2.0.6) 옮기지 않고 읽는다 — 브리핑이 먼저 옮기면 후보함 화면은 409 없이 빈 목록을 보고 그 위에 저장했다
        return [e for e in load(organization_id, quarantine=False) if e.status == "pending"]
    except storage.CorruptJsonError:
        return []
