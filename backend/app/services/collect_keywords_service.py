"""「찾는 낱말」 — 나라장터 공고명 검색 낱말 = 기본 낱말(고칠 수 없음) + 추가 낱말 (2.0.7 · 대표 10-27).

대표 요청: 「(나라장터 공고를 찾는) 낱말 추가를 대시보드에서 할 수 있게 · 그리고 바로 재검색」.

- 추가 낱말은 **이 서버(설치) 전체에 하나**다(결정 ③) — 받은 공고 저장본 · 분류가 회사별이 아니다. 편집자 이상이 더하고 지운다
  (POST 라 열람자는 미들웨어가 403).
- 매일 받기(`procurement_service.list_ai_candidates`) · 분류(`opportunity_filter.classify`) · 사전규격 · 발주계획 거르기
  (`prespec_service.wanted`)가 `all_keywords()` 를 쓴다. 추가 낱말로만 받은 공고에 본업 낱말이 없으면 「관련 낮음」 + 사유로 접는다
  (결정 ② — 버리지 않는다).
- 파일 `DATA_ROOT/private/collect_keywords.json`(Git 밖) = {keywords: [{word, added_by, added_at}], searches: {KST 날짜: n}, updated_at, updated_by}.
  바로 찾기 횟수는 `updated_at` 을 바꾸지 않는다 — 남이 찾기만 했는데 내 저장이 409 가 되지 않게.
- **낱말 규칙의 기준은 여기 한 곳**이다(화면 `lib/collectKeywords.ts` 는 안내용 사본 · 흔한 낱말 목록은 여기에만).
- 상한(결정 ④): 추가 낱말 10개 · 바로 찾기 하루 10번(KST 날짜).
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from datetime import datetime
from typing import Any

from app.core import storage
from app.core.config import get_settings
from app.core.paths import DATA_ROOT
from app.services.opportunity_filter import COLLECT_KEYWORDS

logger = logging.getLogger(__name__)

KEYWORDS_FILE = DATA_ROOT / "private" / "collect_keywords.json"
MAX_EXTRA = 10
SEARCHES_PER_DAY = 10
MIN_LENGTH = 2
MAX_LENGTH = 20

#: 거의 모든 공고명에 드는 낱말 — 더하면 낱말당 300건씩 「관련 낮음」만 쌓인다. 띄어쓰기를 뺀 낱말이 **같을 때만** 막는다(「교육운영」은 된다).
COMMON_WORDS = frozenset({
    "용역", "사업", "운영", "서비스", "구매", "지원", "관리", "계약", "공사", "물품", "입찰", "공고", "제작", "개발", "설치",
    "유지보수", "유지관리", "위탁", "대행", "구축", "시스템", "연구", "조사", "용역사업", "임차", "수리", "점검",
})

#: 한글(자모 포함) · 영문 · 숫자 · 띄어쓰기 · 점 · 하이픈. 화면 사본과 같은 집합이다(화면이 서버보다 좁으면 맞는 낱말을 막는다).
_ALLOWED = re.compile(r"[0-9A-Za-zㄱ-ㆎ가-힣 .\-]+")
#: 파일 읽고-고치고-쓰기를 한 번에 하나만(같은 프로세스). 여러 사람 사이의 덮어쓰기는 `updated_at` 409 가 막는다.
_WRITE = threading.Lock()
#: 파일 시각 메모 — 분류가 공고마다 부르므로 파일을 매번 풀지 않는다.
_MEMO: dict[str, Any] = {"key": None, "payload": {}}


class KeywordRuleError(ValueError):
    """낱말 규칙 · 상한에 어긋난다(400) — 사유를 그대로 화면에 보인다."""


def normalize(raw: str | None) -> str:
    """NFC · 앞뒤 공백 제거 · 연속 공백 하나로(화면 `normalizeKeyword` 와 같다)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw or "")).strip()


def _key(word: str) -> str:
    """같은 낱말 비교 — 띄어쓰기 · 대소문자 무시(나라장터 공고명 검색이 띄어쓰기를 무시한다)."""
    return word.replace(" ", "").lower()


def file_stamp() -> tuple[str, int, int]:
    """(경로 · 파일 시각 · 크기) — 고정 모드 목록 메모의 열쇠에도 든다(낱말만 지워도 옛 분류가 남지 않게)."""
    try:
        stat = KEYWORDS_FILE.stat()
    except OSError:
        return str(KEYWORDS_FILE), 0, 0
    return str(KEYWORDS_FILE), stat.st_mtime_ns, stat.st_size


def _read() -> dict[str, Any]:
    """파일(파일 시각 메모). 없거나 깨졌으면 빈 것 — 분류가 이 파일 하나로 멈추지 않는다(기본 낱말만으로 돈다)."""
    key = file_stamp()
    if _MEMO["key"] != key:
        try:
            payload = storage.read_json(KEYWORDS_FILE, default=None, quarantine=False)  # 곁 읽기는 옮기지 않는다(2.0.6)
        except storage.CorruptJsonError:
            logger.warning("추가 수집 낱말 파일을 읽지 못해 기본 낱말만 씁니다: %s", KEYWORDS_FILE)
            payload = None
        _MEMO["key"], _MEMO["payload"] = key, payload if isinstance(payload, dict) else {}
    return _MEMO["payload"]


def _entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in payload.get("keywords") or [] if isinstance(e, dict) and isinstance(e.get("word"), str) and e["word"].strip()]


def extra_words() -> tuple[str, ...]:
    return tuple(e["word"] for e in _entries(_read()))


def all_keywords() -> tuple[str, ...]:
    """기본 낱말 + 추가 낱말 — 매일 받기 · 사전규격 · 발주계획이 이것으로 찾는다."""
    return (*COLLECT_KEYWORDS, *extra_words())


def matches(title: str | None, word: str) -> bool:
    """공고명에 추가 낱말이 드는가 — 공고명 검색처럼 띄어쓰기 · 대소문자 무시. 영문 3자 이하는 단어 경계(「VR」이 「OVRA」에 걸리지 않게).

    기본 낱말의 규칙(`opportunity_filter._contains`)은 건드리지 않는다 — 기존 분류가 그대로여야 정밀도(D25)가 그대로다."""
    text = title or ""
    if len(word) <= 3 and word.isascii():
        return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.IGNORECASE) is not None
    return _key(word) in _key(text)


def full_reason() -> str:
    return f"추가 낱말은 {MAX_EXTRA}개까지입니다 — 하나를 지운 뒤 더하세요"


def validate(raw: str, extra: tuple[str, ...] | list[str]) -> str:
    """다듬은 낱말. 어긋나면 `KeywordRuleError`. 순서는 화면 안내와 같다: 꽉 참 → 길이 → 글자 → 이미 있음 → 너무 흔함."""
    word = normalize(raw)
    if len(extra) >= MAX_EXTRA:
        raise KeywordRuleError(full_reason())
    if len(word) < MIN_LENGTH:
        raise KeywordRuleError("두 글자 이상 적으세요")
    if len(word) > MAX_LENGTH:
        raise KeywordRuleError(f"{MAX_LENGTH}자까지 적을 수 있습니다")
    if not _ALLOWED.fullmatch(word):
        raise KeywordRuleError("한글 · 영문 · 숫자 · 띄어쓰기 · 점(.) · 하이픈(-)만 쓸 수 있습니다")
    same = next((w for w in (*COLLECT_KEYWORDS, *extra) if _key(w) == _key(word)), None)
    if same is not None:
        raise KeywordRuleError(f"이미 있는 낱말입니다(「{same}」) — 띄어쓰기 · 대소문자만 다르면 같은 낱말로 봅니다")
    # (2.0.7 검토 back-2) 정확히 같은 낱말만 막으면 「2026」 · 「운영 용역」 · 「운영용역」 · 「--」가 통과해 낱말당 300건 「관련 낮음」이 쌓였다.
    if not re.search(r"[A-Za-z가-힣]", word):
        raise KeywordRuleError("숫자 · 기호만으로는 더할 수 없습니다 — 사업 낱말을 적으세요")
    if _only_common(_key(word)) or re.fullmatch(r"(?:19|20)\d{2}(?:년도?)?", _key(word)):
        raise KeywordRuleError(f"「{word}」 낱말은 거의 모든 공고명에 들어 있어 더할 수 없습니다 — 더 좁은 낱말을 적으세요")
    return word


def _only_common(key: str) -> bool:
    """흔한 낱말만으로 이어 붙인 낱말인가(「운영용역」 = 운영 + 용역). 하나라도 다른 조각이 있으면 아니다."""
    if not key:
        return False
    reach = [True] + [False] * len(key)
    for end in range(1, len(key) + 1):
        reach[end] = any(reach[start] and key[start:end] in COMMON_WORDS for start in range(end))
    return reach[-1]


def find_extra(raw: str) -> str:
    """이미 더한 추가 낱말(저장된 표기). 없으면 `KeywordRuleError` — 다시 찾기는 추가 낱말만 한다."""
    key = _key(normalize(raw))
    word = next((w for w in extra_words() if _key(w) == key), None)
    if word is None:
        raise KeywordRuleError(f"「{normalize(raw)}」 낱말은 추가 낱말 목록에 없습니다 — 먼저 더하세요")
    return word


def search_live() -> bool:
    """이 서버가 바로 찾기를 할 수 있는가 — 좁은 문(`KEYWORD_SEARCH_LIVE`) 또는 나라장터 실호출 문(`G2B_LIVE_FETCH` · 노트북)."""
    settings = get_settings()
    return bool(settings.keyword_search_live or settings.g2b_live_fetch)


def _searches(payload: dict[str, Any]) -> int:
    raw = (payload.get("searches") or {}).get(storage.kst_today().isoformat())
    return raw if isinstance(raw, int) and raw > 0 else 0


def searches_today() -> int:
    return _searches(_read())


def state() -> dict[str, Any]:
    """화면 「찾는 낱말」 칸(`CollectKeywordsState`). 읽기만 — 바깥 호출 없음."""
    from app.services import user_service  # 계정 파일 — 분류 경로(import 시점)에 끌어오지 않는다

    payload = _read()
    updated_at = payload.get("updated_at")
    return {
        "base": list(COLLECT_KEYWORDS),
        "extra": [
            {
                "word": entry["word"],
                "added_by": entry.get("added_by") or "",
                # 로그인 없는 로컬(노트북)은 누가 더했는지 모른다 — 「이 PC」
                "added_by_name": user_service.display_name_of(entry.get("added_by")) or "이 PC",
                "added_at": entry.get("added_at") or "",
            }
            for entry in _entries(payload)
        ],
        "max_extra": MAX_EXTRA,
        "searches_today": _searches(payload),
        "searches_limit": SEARCHES_PER_DAY,
        "search_live": search_live(),
        "updated_at": updated_at if isinstance(updated_at, str) else None,
    }


def _load_for_write() -> dict[str, Any]:
    try:
        payload = storage.read_json(KEYWORDS_FILE, default=None)  # 깨졌으면 옆으로 옮겨 두고(격리 · 지우지 않음) 빈 목록에서 시작
    except storage.CorruptJsonError:
        payload = None
    return payload if isinstance(payload, dict) else {}


def _ensure_fresh(payload: dict[str, Any], expected_updated_at: datetime | None) -> None:
    """처음 읽은 뒤 남이 먼저 바꿨으면 409(43차 M25 · `storage.ensure_unchanged`)."""
    raw = payload.get("updated_at")
    try:
        stored_at = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        stored_at = None
    storage.ensure_unchanged(stored_at, expected_updated_at, stored_by=payload.get("updated_by"))


def _save(payload: dict[str, Any], *, by: str | None) -> None:
    payload["updated_at"] = storage.utc_now().isoformat()
    payload["updated_by"] = by
    storage.write_json_atomic(KEYWORDS_FILE, payload)


def add(raw: str, *, by: str | None, expected_updated_at: datetime | None) -> str:
    """추가 낱말을 더하고 저장된 표기를 돌려준다. 409(그사이 남이 바꿈) → 400(규칙 · 10개) 순으로 막는다."""
    with _WRITE:
        payload = _load_for_write()
        _ensure_fresh(payload, expected_updated_at)
        entries = _entries(payload)
        word = validate(raw, [e["word"] for e in entries])
        payload["keywords"] = [*entries, {"word": word, "added_by": by, "added_at": storage.utc_now().isoformat()}]
        _save(payload, by=by)
    return word


def remove(raw: str, *, by: str | None, expected_updated_at: datetime | None) -> str:
    """추가 낱말을 지운다. 기본 낱말 · 목록에 없는 낱말은 400.

    그 낱말로만 받은 공고는 저장본에 남아 있다가 다음 아침 받기에서 빠진다 — 그 감소는 줄어듦 차단 비교에서 뺀다
    (`procurement_service.save_cache` · 낱말을 지운 다음 날 받기가 「저장하지 않음」으로 막히지 않게)."""
    word = normalize(raw)
    with _WRITE:
        payload = _load_for_write()
        _ensure_fresh(payload, expected_updated_at)
        entries = _entries(payload)
        kept = [e for e in entries if _key(e["word"]) != _key(word)]
        if len(kept) == len(entries):
            if any(_key(k) == _key(word) for k in COLLECT_KEYWORDS):
                raise KeywordRuleError("기본 낱말은 지울 수 없습니다")
            raise KeywordRuleError(f"「{word}」 낱말은 추가 낱말 목록에 없습니다 — 목록을 다시 불러오세요")
        payload["keywords"] = kept
        _save(payload, by=by)
    return word


def count_search() -> int:
    """바로 찾기 한 번을 센다(오늘 KST · 지난 날은 지운다). `updated_at` 은 그대로 — 낱말 목록이 바뀐 것이 아니다."""
    with _WRITE:
        payload = _load_for_write()
        count = _searches(payload) + 1
        payload["searches"] = {storage.kst_today().isoformat(): count}
        storage.write_json_atomic(KEYWORDS_FILE, payload)
    return count
