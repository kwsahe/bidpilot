"""기업마당 지원사업 목록 + 지원 적합도.

- 실호출 → 실패하면 캐시 → 캐시도 없으면 **합성 샘플**(source="sample", 화면에 그대로 표시).
- 지원 적합도(support_fit)는 조달공고 추천등급과 다른 점수다. 섞지 않는다.
- 사업영역은 의미 유사도를 «잴 수 있을 때만» 그것으로, 못 재면 키워드 규칙으로 판정한다.
  지역·대상·기간은 언제나 규칙이다. 무엇으로 쟀는지는 method 에 남긴다.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Final

from app.core import storage
from app.core.config import get_settings
from app.core.paths import DATA_ROOT
from app.schemas.business_opportunity import (
    SupportAttachment,
    SupportFit,
    SupportFitComponent,
    SupportProgram,
    SupportProgramListResponse,
    SupportProgramView,
)
from app.services import audience_filter, bizinfo_client, company_service

logger = logging.getLogger(__name__)

DATA_DIR = DATA_ROOT / "public" / "sample_bizinfo"
# 실호출 캐시는 내부 전용(Git 제외)에 둔다. 실제 원본 응답을 공개 저장소에 남기지 않는다.
CACHE_DIR = DATA_ROOT / "private" / "cache" / "bizinfo"
CACHE_FILE = CACHE_DIR / "bizinfo_cache.json"
# 합성 샘플만 공개 위치에 둔다 (키가 없을 때 화면이 비지 않게 하는 용도).
SAMPLE_FILE = DATA_DIR / "bizinfo_sample.json"
CACHE_TTL_SECONDS = 3600


def live_fetch_enabled() -> bool:
    """기업마당을 실제로 불러도 되는가 (`BIZINFO_LIVE_FETCH`, 기본 켬).

    나라장터 쪽 `procurement_service.live_fetch_enabled()` 와 같은 뜻이다 (ISSUE-062).
    끄면 캐시(없으면 합성 샘플)만 쓰고 네트워크를 건드리지 않는다.
    """
    return bool(get_settings().bizinfo_live_fetch)
KST = timezone(timedelta(hours=9))

# 2026-09-08 실응답 확인 완료 (scripts/verify_bizinfo_api.py — 문서 필드 12개 전부 존재, 100/100 매핑).
FIELD_MAPPING_VERIFIED = True

# --------------------------------------------------------------------------
# 매핑 (문서 필드명 → 내부 모델). 실응답이 다르면 여기만 고친다.
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"(20\d{2})[.\-/]?\s*(\d{1,2})[.\-/]?\s*(\d{1,2})")


def _text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def _parse_period(value: str | None) -> tuple[date | None, date | None]:
    """'20260901 ~ 20260930' 또는 '2026-09-01~2026-09-30'."""
    if not value:
        return None, None
    parts = re.split(r"[~∼～]", value)
    start = _parse_date(parts[0]) if parts else None
    end = _parse_date(parts[1]) if len(parts) > 1 else None
    return start, end


# 실응답의 15%는 날짜가 아니라 문구다 ('상시 접수', '예산 소진시까지', '모집 마감시' …).
# 날짜가 없다고 "마감일 없음"으로 뭉뚱그리면 상시 접수 사업이 후순위로 밀린다.
_PERIOD_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("always_open", ("상시", "수시", "연중")),
    ("until_budget", ("예산 소진", "예산소진", "소진시", "소진 시")),
    ("conditional", ("마감시", "마감 시", "완료시", "완료 시", "선착순", "충원", "모집시")),
    ("unknown", ("상이", "별도", "추후", "미정")),
)


def _period_kind(value: str | None, start: date | None, end: date | None) -> str:
    """신청 기간 원문의 성격. 날짜가 읽히면 dated."""
    if start or end:
        return "dated"
    if not value:
        return "unknown"
    for kind, needles in _PERIOD_PATTERNS:
        if any(n in value for n in needles):
            return kind
    return "unknown"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", value)
    if not match:
        return None
    hour = int(match[4]) if match[4] else 0
    minute = int(match[5]) if match[5] else 0
    return datetime(int(match[1]), int(match[2]), int(match[3]), hour, minute, tzinfo=KST)


def _hashtags(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip().lstrip("#") for t in re.split(r"[,\s]+", value) if t.strip()]


# 사업 개요(bsnsSumryCn)는 HTML 조각으로 온다. 화면에 태그가 그대로 보이지 않게 여기서 평문으로 바꾼다.
_TAG_RE = re.compile(r"<[^>]+>")
# HTML 엔티티는 표준 라이브러리(html.unescape)로 전부 푼다 — &alpha; 같은 것까지.


def _plain_text(value: str | None) -> str | None:
    """HTML 태그·엔티티를 걷어낸 평문. 줄바꿈은 살리고 연속 공백만 줄인다."""
    if not value:
        return value
    text = re.sub(r"<\s*(br|/p|/div|/li|/tr)\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = unescape(_TAG_RE.sub("", text)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


# 기업마당은 첨부가 여럿이면 이름도 주소도 **「@」로 이어** 한 칸에 담아 준다.
# 126482 실측: fileNm = "…모집공고.hwpx@[별첨_2]_사업_신청_매뉴얼.pdf@[별첨_1]_공공기관_과제소개서.pdf"
_ATTACHMENT_SEP: Final = "@"
# 목록이 주는 주소는 뷰어다. 같은 질의로 이 경로를 부르면 원본 파일이 온다(0924.md §2).
_VIEWER_PATH: Final = "getImageFile.do"
_DOWNLOAD_PATH: Final = "fileDown.do"


def _split_field(value: str | None) -> list[str]:
    """「@」로 이어 붙인 칸을 조각으로. 빈 조각은 버린다."""
    if not value:
        return []
    return [part.strip() for part in value.split(_ATTACHMENT_SEP) if part.strip()]


def _download_url(url: str) -> str:
    """뷰어 주소(`getImageFile.do`)를 내려받기 주소(`fileDown.do`)로.

    질의 문자열(`atchFileId`·`fileSn`)은 그대로 둔다 — 같은 값으로 경로만 바뀐다.
    이미 `fileDown.do` 이거나 기업마당이 아닌 주소면 손대지 않는다.
    """
    return url.replace(_VIEWER_PATH, _DOWNLOAD_PATH) if _VIEWER_PATH in url else url


def _extension(name: str) -> str | None:
    """이름 끝의 확장자. 「hwpx」·「pdf」처럼 짧은 글자만 인정한다."""
    match = re.search(r"\.([A-Za-z0-9]{1,5})$", name)
    return match.group(1).lower() if match else None


#: 첨부 이름 → 종류 (30차 §3-A). 차례대로 본다 — 「과제소개서」가 「서식」보다, 「서식」이 「공고」보다 먼저.
_KIND_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("annex", re.compile(r"과제\s*소개서|수요\s*과제|과제\s*(?:목록|설명)")),
    ("manual", re.compile(r"매뉴얼|안내서|가이드")),
    ("form", re.compile(r"신청서|사업\s*계획서|양식|서식")),
    ("notice", re.compile(r"공고")),
)


def attachment_kind(name: str, default: str = "form") -> str:
    """첨부 이름으로 종류를 단다 — 모르면 `default`(신청 서식 칸은 예전처럼 「form」)."""
    compact = re.sub(r"[_\s]+", " ", name or "")
    return next((kind for kind, pattern in _KIND_RULES if pattern.search(compact)), default)


def annex_attachment(item: dict[str, Any]) -> SupportAttachment | None:
    """그 공고의 과제소개서 첨부(신청 서식 칸에서 이름이 과제소개서인 첫 첨부). 없으면 None (30차 §3-A)."""
    return next((a for a in _attachments(item) if a.kind == "annex" and a.index is not None), None)


def _attachments(item: dict[str, Any]) -> list[SupportAttachment]:
    """신청 서식(fileNm/flpthNm)과 공고문(printFileNm/printFlpthNm).

    한 칸에 여러 파일이 「@」로 들어 있어서, 예전에는 세 파일이 **이름 하나·주소 하나**로
    합쳐져 링크가 열리지 않았다(ISSUE-111). 이름과 주소를 각각 나눠 **차례대로 짝짓는다.**

    개수가 어긋나면 **주소 수만큼** 만든다 — 주소가 없는 줄은 눌러도 갈 곳이 없어서
    화면에 둘 이유가 없다. 이름이 모자란 자리는 「파일 n」으로 채운다
    (프롬프트 §4-C-4 의 「이름 2 · 주소 3 → 3건에 「파일 3」」이 이 규칙이다).
    """
    result: list[SupportAttachment] = []
    for name_key, url_key, kind in (("fileNm", "flpthNm", "form"), ("printFileNm", "printFlpthNm", "notice")):
        names = _split_field(_text(item, name_key))
        urls = _split_field(_text(item, url_key))
        for index, view_url in enumerate(urls):
            name = names[index] if index < len(names) else f"파일 {index + 1}"
            result.append(
                SupportAttachment(
                    name=name,
                    url=_download_url(view_url),
                    # 신청 서식 칸(fileNm)은 이름으로 종류를 단다 — 과제소개서에 「신청 서식」 배지가 붙었다(30차 §3-A)
                    kind=attachment_kind(name) if name_key == "fileNm" else kind,  # type: ignore[arg-type]
                    view_url=view_url,
                    ext=_extension(name),
                    index=index if name_key == "fileNm" else None,
                )
            )
    return result


# 공개 스냅샷에서 가릴 연락처 패턴 (기관 담당자 이메일·전화가 원문에 섞여 있다).
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}")


def mask_contacts(value: str | None) -> str | None:
    """공개 데모 스냅샷용 마스킹. 로컬 내부 화면에서는 원문 그대로 쓴다."""
    if not value:
        return value
    masked = _EMAIL_RE.sub("[이메일 원문 확인]", value)
    return _PHONE_RE.sub("[전화 원문 확인]", masked)


# --------------------------------------------------------------------------
# 정규 필드: 지역 태그 · 「☞」 대상 문장 (0921.md §4-A-4)
# --------------------------------------------------------------------------

#: 지역 이름의 **대표 이름과 별칭**. 통합 이후 광주·전남은 한 이름 「전남광주」다.
#:
#: 기업마당 해시태그에는 통합 전 이름(「광주」·「전남」)과 통합 이름이 섞여 있다. 같은
#: 지역을 두 이름으로 세면 회사 소재지와 대조할 때 어긋난다 — 대표 이름 하나로 접는다.
REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "전남광주": ("전남광주", "광주광역시", "광주", "전라남도", "전남"),
    "서울": ("서울특별시", "서울"),
    "부산": ("부산광역시", "부산"),
    "대구": ("대구광역시", "대구"),
    "인천": ("인천광역시", "인천"),
    "대전": ("대전광역시", "대전"),
    "울산": ("울산광역시", "울산"),
    "세종": ("세종특별자치시", "세종"),
    "경기": ("경기도", "경기"),
    "강원": ("강원특별자치도", "강원도", "강원"),
    "충북": ("충청북도", "충북"),
    "충남": ("충청남도", "충남"),
    "전북": ("전북특별자치도", "전라북도", "전북"),
    "경북": ("경상북도", "경북"),
    "경남": ("경상남도", "경남"),
    "제주": ("제주특별자치도", "제주"),
}


def region_tags_of(*sources: str | None) -> list[str]:
    """해시태그·기관명·제목에서 **대표 지역 이름**을 뽑는다. 순서는 위 표의 순서다.

    긴 별칭부터 맞춰야 「광주광역시」가 「광주」로만 잡히지 않는다.
    """
    text = " ".join(part for part in sources if part)
    if not text:
        return []
    found: list[str] = []
    for canonical, aliases in REGION_ALIASES.items():
        if any(alias in text for alias in aliases) and canonical not in found:
            found.append(canonical)
    return found


#: 기업마당 요약문에서 대상 요건을 가리키는 표시. 실캐시 100건 전부가 이것을 쓴다.
_REQUIREMENT_MARK = "☞"


def requirement_sentences_of(summary: str | None) -> list[str]:
    """요약문의 「☞ …」 줄들. **원문 그대로** 돌려준다 (0921 §4-B: 생성 금지).

    평문화(`_plain_text`)를 거친 뒤 줄 단위로 고른다 — `&nbsp;` 가 이미 공백으로 풀려 있다.
    """
    if not summary:
        return []
    out: list[str] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if _REQUIREMENT_MARK in stripped:
            # 한 줄에 여러 개가 붙어 오는 경우가 있어 표시 기준으로 다시 나눈다.
            for chunk in stripped.split(_REQUIREMENT_MARK):
                text = chunk.strip(" ·-–—	")
                if text and text not in out:
                    out.append(text)
    return out


def map_program(item: dict[str, Any]) -> SupportProgram | None:
    program_id = _text(item, "pblancId")
    title = _text(item, "pblancNm")
    if not program_id or not title:
        return None
    period_text = _text(item, "reqstBeginEndDe")
    start, end = _parse_period(period_text)
    return SupportProgram(
        id=f"bizinfo-{program_id}",
        title=title,
        agency=_text(item, "jrsdInsttNm") or "기관 미상",
        executing_agency=_text(item, "excInsttNm"),
        summary=_plain_text(_text(item, "bsnsSumryCn")),
        apply_start=start,
        apply_end=end,
        apply_period_text=period_text,
        apply_period_kind=_period_kind(period_text, start, end),  # type: ignore[arg-type]
        category=_text(item, "pldirSportRealmLclasCodeNm"),
        subcategory=_text(item, "pldirSportRealmMlsfcCodeNm"),
        hashtags=_hashtags(_text(item, "hashtags")),
        target=_text(item, "trgetNm"),
        # 캐시에 미리 넣어 둔 값이 있으면 그것을 쓰고, 없으면(옛 캐시) 여기서 계산한다.
        region_tags=(
            [str(x) for x in item["region_tags"]]
            if isinstance(item.get("region_tags"), list)
            else region_tags_of(_text(item, "hashtags"), _text(item, "jrsdInsttNm"), title)
        ),
        requirement_sentences=(
            [str(x) for x in item["requirement_sentences"]]
            if isinstance(item.get("requirement_sentences"), list)
            else requirement_sentences_of(_plain_text(_text(item, "bsnsSumryCn")))
        ),
        url=_text(item, "pblancUrl"),
        created_at=_parse_datetime(_text(item, "creatPnttm")),
        updated_at=_parse_datetime(_text(item, "updtPnttm")),
        apply_method=_plain_text(_text(item, "reqstMthPapersCn")),
        contact=_text(item, "refrncNm"),
        reception_url=_text(item, "rceptEngnHmpgUrl"),
        attachments=_attachments(item),
    )


# --------------------------------------------------------------------------
# 지원 적합도 (조달 추천등급과 별개)
# --------------------------------------------------------------------------

# 사업영역 키워드를 «핵심»과 «약한 신호»로 나눈다.
#
# 예전에는 13개를 한 묶음으로 두고 3개만 맞으면 만점을 줬다. 그런데 「디지털·데이터·스마트」
# 류는 공공 지원사업 공고문 대부분에 들어 있어서, SampleEdu 과 관계가 먼 사업
# (국제공동연구·시설농업 로봇·제조 지원)도 이 셋만으로 만점을 받았다.
#
# 핵심어는 이 회사가 실제로 하는 일이고, 약한 신호는 «있으면 참고» 수준이다.
# 약한 신호만으로는 만점이 나오지 않게 배점을 나눈다.
_DOMAIN_CORE_KEYWORDS = ("AI", "인공지능", "생성형", "교육", "컨설팅", "역량", "소프트웨어", "SW")
_DOMAIN_WEAK_KEYWORDS = ("디지털", "DX", "데이터", "스마트", "바우처")
# 호환용 — 기존 호출부와 테스트가 쓰던 전체 목록.
_DOMAIN_KEYWORDS = _DOMAIN_CORE_KEYWORDS + _DOMAIN_WEAK_KEYWORDS
# 지역 한정 사업인지 보기 위한 전체 시·도 토큰 (판정용이지 회사 우선 지역이 아니다).
#: 시 · 도 이름을 이만큼 넘게 단 공고는 전국 대상으로 본다(해시태그에 17개를 다 단다 · 43차 BIZ-01).
NATIONWIDE_TAGS = 5
#: 활동 지역 정식 이름 → 대표 낱말.
_REGION_SHORT = {
    "전라남도": "전남", "전라북도": "전북", "전북특별자치도": "전북", "충청남도": "충남", "충청북도": "충북",
    "경상남도": "경남", "경상북도": "경북", "광주광역시": "광주", "전남광주통합특별시": "광주",
}
_ALL_REGION_TOKENS = (
    "광주", "전남", "서울", "경기", "부산", "대구", "인천", "대전", "울산",
    "세종", "강원", "충북", "충남", "전북", "경북", "경남", "제주",
)
# 「기업」을 뺐다 — 실측(2026-09-10, 100건)에서 100건 전부가 이 한 글자에 걸려
# 변별력이 0이면서 모든 항목에 상수로 가산됐다. 나머지는 실제로 대상을 좁히는 말이다.
_TARGET_KEYWORDS = ("중소기업", "소기업", "소상공인", "창업", "벤처", "교육기관")
_WEIGHTS = {"domain": 0.4, "target": 0.2, "region": 0.2, "period": 0.2}
# 지원 적합도를 «무엇으로 쟀는가» (SupportFit.method 값).
# 키워드 값은 화면·기존 호출부가 알고 있는 "keyword_rule" 그대로 두고, 의미 매칭 쪽만
# 담당자가 읽을 수 있는 말로 새로 붙인다 — 화면이 원값을 그대로 찍어도 읽히게.
KEYWORD_FIT_METHOD: Final[str] = "keyword_rule"
SEMANTIC_FIT_METHOD: Final[str] = "AI 의미 매칭"
# 회사가 신청자가 될 수 없어 보이는 안내의 적합도 상한. 「검토」(0.4) 아래로 내려
# 「낮음」에 둔다 — 목록에서 사라지지는 않는다.
_AUDIENCE_SCORE_CAP: Final[float] = 0.35


def _contains_any(text: str, keywords: tuple[str, ...]) -> list[str]:
    found = []
    for keyword in keywords:
        if len(keyword) <= 2 and keyword.isascii():
            if re.search(rf"(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])", text):
                found.append(keyword)
        elif keyword.lower() in text.lower():
            found.append(keyword)
    return found


def support_fit(program: SupportProgram, *, today: date | None = None, organization_id: str | None = None) -> SupportFit:
    """지원 적합도. organization_id 가 없으면 설정의 기본 조직 프로필을 쓴다 (호환 계층 — 새 호출은 명시한다).

    사업영역은 의미 유사도를 잴 수 있으면 그것을, 못 재면 키워드 규칙을 쓴다.
    """
    from app.core.config import get_settings
    from app.services import opportunity_priority as priority, recommendation, semantic_matcher

    profile = company_service.load_profile(organization_id or get_settings().default_organization_id)
    text = " ".join(filter(None, [program.title, program.summary, program.category, program.subcategory, " ".join(program.hashtags)]))
    # 기준일은 KST 다. date.today() 는 서버 로컬 시간대라, UTC 서버에서는 KST 기준
    # 하루 전 날짜로 판정해 접수 기간 점수가 하루 어긋난다.
    # 다른 경로(opportunity_priority._today)와 같은 규칙을 쓴다.
    moment = today or priority._today(None)

    # 핵심어는 **선택한 회사의 사업영역**에서 뽑는다.
    #
    # 예전에는 SampleEdu 전용 목록이 하드코딩돼 모든 회사에 똑같이 쓰였다. 그러면 제조 회사가
    # 「스마트공장」 사업을 봐도 자기 영역으로 인정받지 못한다. 회사가 프로필에 적어 둔
    # 사업영역이 그 회사의 핵심어다. 프로필이 비어 있을 때만 기본 목록으로 돌아간다.
    profile_core = tuple(
        t for t in priority.profile_tokens(list(profile.business_domains)) if len(t) >= 2
    )
    core_keywords = profile_core or _DOMAIN_CORE_KEYWORDS
    # 약한 신호는 회사와 무관한 범용어다. 핵심어와 겹치면 핵심 쪽으로 보낸다.
    weak_keywords = tuple(k for k in _DOMAIN_WEAK_KEYWORDS if k not in core_keywords)

    # 핵심어는 하나당 1/2점, 약한 신호는 하나당 1/6점. 약한 신호만 셋이면 0.5 로 그친다.
    core_hits = _contains_any(text, core_keywords)
    weak_hits = _contains_any(text, weak_keywords)
    domain_hits = core_hits + weak_hits
    domain_score = min(1.0, len(core_hits) / 2 + len(weak_hits) / 6) if domain_hits else 0.0
    # 「키워드 · 약한 신호」는 개발 말이다 — 다른 화면처럼 「낱말」(32차 어려운 글 #10)
    if core_hits and weak_hits:
        domain_reason = f"맞는 낱말: {', '.join(core_hits)} · 흔한 낱말: {', '.join(weak_hits)}"
    elif core_hits:
        domain_reason = f"맞는 낱말: {', '.join(core_hits)}"
    elif weak_hits:
        domain_reason = f"흔한 낱말만 있음: {', '.join(weak_hits)} — 우리 사업과 이어지는지 원문에서 확인하세요"
    else:
        domain_reason = "공고에 우리 사업 낱말이 없습니다"

    # 의미 유사도로 잴 수 있으면 사업영역 점수를 그것으로 바꾼다.
    # 「디지털·데이터」 같은 범용어가 스쳤다고 점수가 오르는 것을 막는 것이 이 항목의 목적인데,
    # 글자 수를 세는 규칙으로는 한계가 있다. 못 재면(임베딩 불가) 위 규칙 값 그대로다.
    #
    # 문구 쪼개기는 `recommendation.company_phrases` 가 마지막 결과를 재사용한다 —
    # 목록 한 번에 지원사업 100건이 들어오므로 건마다 다시 쪼개면 안 된다.
    semantic = semantic_matcher.match(
        notice=semantic_matcher.notice_text(title=program.title, summary=program.summary),
        phrases=list(
            recommendation.company_phrases(
                business_domains=profile.business_domains,
                target_clients=profile.target_clients,
                certifications=profile.certifications,
            )
        ),
    )
    # 쟀을 때만 바꾼다. 못 쟀으면 fit_score 가 None 이고, 그것은 0 점이 아니라 «재지 못함»이다.
    semantic_score = (
        semantic.fit_score if semantic.method == "EMBEDDING" and semantic.fit_score is not None else None
    )
    if semantic_score is not None:
        domain_score = semantic_score
        # 키워드 사유를 지우지 않고 함께 남긴다 — 점수가 왜 그런지 두 근거로 읽히게.
        domain_reason = f"{domain_reason} · {semantic.reason}"

    domain = SupportFitComponent(
        key="domain",
        label="사업영역 낱말" if semantic_score is None else "사업영역 적합도",
        weight=_WEIGHTS["domain"],
        score=round(domain_score, 3),
        reason=domain_reason,
    )

    target_text = f"{program.target or ''} {text}"
    target_hits = _contains_any(target_text, _TARGET_KEYWORDS)
    # 「누구를 모집하는가」가 개인·수강생이면 회사는 신청자가 아니다 (ISSUE-005).
    # 실측 1위가 「공예작가 교육생 모집」이었다 — 「AI」「교육」「역량 강화」가 다 들어 있어
    # 사업영역 1.0 을 받았지만 샘플에듀가 신청할 수 있는 사업이 아니다.
    audience = audience_filter.audience_note(target_text)
    audience_kind = audience_filter.audience_kind(target_text)
    if audience is not None:
        target = SupportFitComponent(
            key="target",
            label="지원 대상",
            weight=_WEIGHTS["target"],
            score=0.0,
            reason=f"대상: {program.target or '명시 없음'} — {audience}",
        )
    else:
        target = SupportFitComponent(
            key="target",
            label="지원 대상",
            weight=_WEIGHTS["target"],
            score=1.0 if target_hits else (None if not program.target else 0.3),
            reason=f"대상: {program.target or '명시 없음'}" + (f" (매칭: {', '.join(target_hits)})" if target_hits else ""),
        )

    # 지역 판정은 **선택한 회사 프로필의 활동 지역**만 본다.
    # (예전에는 광주·전남을 항상 끼워 넣어 다른 지역 회사도 광주 사업에서 만점을 받았다.)
    regions = [r for r in profile.preferred_regions if r not in ("전국",)]
    # 「전라남도」의 앞 두 글자 「전라」는 전북에도 걸렸다(43차 BIZ-01) — 대표 이름(전남 · 광주 …)으로 바꿔 본다
    region_tokens = tuple({_REGION_SHORT.get(r, r[:2]) for r in regions if len(r) >= 2})
    # 열일곱 시 · 도를 다 단 해시태그는 지역 언급이 아니다(43차 BIZ-01 — 429건이 「활동 지역 연관」으로 지역 만점이었다)
    listed = _contains_any(text, _ALL_REGION_TOKENS)
    nationwide = any(k in text for k in ("전국", "전 국")) or not listed or len(listed) >= NATIONWIDE_TAGS
    region_hits = [] if len(listed) >= NATIONWIDE_TAGS else (_contains_any(text + " " + program.agency, region_tokens) if region_tokens else [])
    if not region_tokens:
        region = SupportFitComponent(
            key="region",
            label="지역",
            weight=_WEIGHTS["region"],
            score=None,
            reason="회사 프로필에 활동 지역이 없어 판정하지 않았습니다",
        )
    else:
        region = SupportFitComponent(
            key="region",
            label="지역",
            weight=_WEIGHTS["region"],
            score=1.0 if region_hits else (0.7 if nationwide else 0.0),
            reason=(
                f"회사 활동 지역({', '.join(regions)}) 언급"
                if region_hits
                else ("지역 제한 없음으로 보임" if nationwide else f"회사 활동 지역({', '.join(regions)}) 밖으로 보임")
            ),
        )

    if program.apply_end is None and program.apply_period_kind in ("always_open", "until_budget"):
        period = SupportFitComponent(
            key="period",
            label="접수 기간",
            weight=_WEIGHTS["period"],
            score=1.0 if program.apply_period_kind == "always_open" else 0.7,
            reason=f"{program.apply_period_text or ''} (마감일 지정 없음)".strip(),
        )
    elif program.apply_end is None:
        period = SupportFitComponent(
            key="period",
            label="접수 기간",
            weight=_WEIGHTS["period"],
            score=None,
            reason=f"접수 기간 원문: {program.apply_period_text}" if program.apply_period_text else "신청 마감일 없음",
        )
    elif program.apply_end < moment:
        period = SupportFitComponent(key="period", label="접수 기간", weight=_WEIGHTS["period"], score=0.0, reason=f"신청 마감 지남 ({program.apply_end.isoformat()})")
    else:
        days = (program.apply_end - moment).days
        period = SupportFitComponent(key="period", label="접수 기간", weight=_WEIGHTS["period"], score=1.0 if days >= 7 else 0.5, reason=f"신청 마감까지 {days}일")

    components = [domain, target, region, period]
    computed = [c for c in components if c.score is not None]
    weight_sum = sum(c.weight for c in computed) or 1.0
    score = sum(c.weight * (c.score or 0.0) for c in computed) / weight_sum
    # 회사가 신청자가 될 수 없는 안내는 상단에 두지 않는다.
    # 대상 항목(0.2)만 0 으로 깎으면 나머지 세 항목이 받쳐 0.65 를 넘길 수 있다 —
    # 실측 1위가 정확히 그랬다. 지우지는 않는다: 규칙이 틀렸을 때 담당자가 목록에서
    # 찾을 수조차 없게 되는 쪽이 더 나쁘다.
    if audience is not None:
        score = min(score, _AUDIENCE_SCORE_CAP)
    if program.apply_end is not None and program.apply_end < moment:
        label = "낮음"
    elif score >= 0.65:
        label = "적합"
    elif score >= 0.4:
        label = "검토"
    else:
        label = "낮음"
    return SupportFit(
        label=label,  # type: ignore[arg-type]
        score=round(score, 3),
        components=components,
        audience_note=audience,
        audience_kind=audience_kind,
        method=KEYWORD_FIT_METHOD if semantic_score is None else SEMANTIC_FIT_METHOD,
        note=(
            # 고정 모드는 AI 비교를 설정으로 「꺼 둔」 것이다 — 「쓸 수 없었습니다」는 다른 이유를 댔다(32차 뜻 틀린 곳 #7)
            "지원 적합도는 낱말 · 지역 · 대상 · 기간 규칙으로 판정했습니다"
            " — AI 의미 매칭은 꺼 두었습니다(점수가 바뀌지 않게 고정 — 켜는 것은 서버 설정). 조달공고 추천등급과 다른 축입니다."
            if semantic_score is None and not semantic_matcher.semantic_fit_enabled()
            else "지원 적합도는 낱말 · 지역 · 대상 · 기간 규칙으로 판정했습니다"
            " — AI 의미 매칭을 쓸 수 없었습니다(키 없음 · 사용량 소진 등). 조달공고 추천등급과 다른 축입니다."
            if semantic_score is None
            else "사업영역은 AI 의미 매칭으로, 지역 · 대상 · 기간은 규칙으로 판정했습니다. 조달공고 추천등급과 다른 축입니다."
        ),
    )


# --------------------------------------------------------------------------
# 목록 (실호출 → 캐시 → 샘플)
# --------------------------------------------------------------------------


def _views(items: list[dict[str, Any]], organization_id: str | None = None) -> list[SupportProgramView]:
    views: list[SupportProgramView] = []
    for item in items:
        program = map_program(item)
        if program is None:
            continue
        views.append(SupportProgramView(program=program, support_fit=support_fit(program, organization_id=organization_id)))
    order = {"적합": 0, "검토": 1, "낮음": 2}
    views.sort(key=lambda v: (order[v.support_fit.label], -(v.support_fit.score), v.program.apply_end or date.max))
    return views


def _from_file(path: Path, source: str, organization_id: str | None = None) -> SupportProgramListResponse | None:
    try:
        payload = storage.read_json(path, default=None)
    except storage.CorruptJsonError:
        return None
    if not isinstance(payload, dict):
        return None
    items = payload.get("items") or bizinfo_client.extract_items(payload)
    views = _views(items, organization_id)
    fetched = payload.get("fetched_at")
    return SupportProgramListResponse(
        source=source,  # type: ignore[arg-type]
        bizinfo_api_configured=bizinfo_client.is_configured(),
        fetched_at=datetime.fromisoformat(fetched) if isinstance(fetched, str) else None,
        total_fetched=int(payload.get("total_fetched") or len(items)),
        count=len(views),
        error=payload.get("error") if source != "sample" else "기업마당 인증키가 없어 가상 예시 목록을 표시합니다. 실제 지원사업이 아닙니다.",
        field_mapping_verified=FIELD_MAPPING_VERIFIED,
        total_available=payload.get("total_available"),
        items=views,
    )


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """원본 항목에 **정규 필드를 덧붙인다** (0921 §4-A-4).

    원본 키는 하나도 지우지 않는다 — 나중에 다른 값을 봐야 할 때 근거가 남아 있어야 한다.
    매번 다시 파싱하지 않으려고 저장 시점에 한 번만 계산한다(1,600건이면 값이 크다).
    """
    return {
        **item,
        "region_tags": region_tags_of(
            _text(item, "hashtags"), _text(item, "jrsdInsttNm"), _text(item, "pblancNm")
        ),
        "requirement_sentences": requirement_sentences_of(_plain_text(_text(item, "bsnsSumryCn"))),
    }


def _cached_count() -> int:
    """지금 캐시에 든 건수. 파일이 없거나 깨졌으면 0 이다."""
    try:
        payload = storage.read_json(CACHE_FILE, default=None)
    except storage.CorruptJsonError:
        return 0
    if not isinstance(payload, dict):
        return 0
    return len(payload.get("items") or [])


def _save_cache(items: list[dict[str, Any]], fetched_at: datetime) -> str | None:
    """캐시를 쓴다. **크게 줄어드는 저장은 막고** 사유를 돌려준다 (ISSUE-121).

    13차에 100건짜리 응답이 1,620건 캐시를 말없이 덮었다. 여기서 막지 않으면 다음에도
    조용히 같은 일이 난다 — 파일이 깨지는 것이 아니라 정상적으로 쓰이기 때문이다.
    """
    reason = storage.cache_shrink_reason(existing=_cached_count(), incoming=len(items))
    if reason:
        logger.warning("기업마당 저장본을 쓰지 않았습니다 — %s", reason)
        return reason

    payload = {
        "_note": "기업마당 실호출 결과 캐시 (내부 전용, Git 제외). 인증키는 포함하지 않는다.",
        "fetched_at": fetched_at.isoformat(),
        "total_fetched": len(items),
        "total_available": bizinfo_client.total_count(items),
        "items": [_normalize_item(item) for item in items],
    }
    storage.stamp(payload)
    storage.write_json_atomic(CACHE_FILE, payload)
    return None


async def list_programs(
    *, refresh: bool = False, count: int = bizinfo_client.DEFAULT_COUNT, organization_id: str | None = None
) -> SupportProgramListResponse:
    """지원사업 목록. 시연 고정 모드면 실호출 없이 저장된 것만 쓴다.

    고정 여부는 응답의 `frozen` 에 싣는다 — `source` 만으로는 「키가 없어 캐시」와
    「키가 있는데 일부러 안 부름」이 구분되지 않는다.
    """
    frozen = not live_fetch_enabled()
    response = await _list_programs(
        refresh=refresh and not frozen, count=count, organization_id=organization_id, frozen=frozen
    )
    response.frozen = frozen
    return response


async def _list_programs(
    *,
    refresh: bool = False,
    count: int = bizinfo_client.DEFAULT_COUNT,
    organization_id: str | None = None,
    frozen: bool = False,
) -> SupportProgramListResponse:
    if frozen:
        # TTL 도 보지 않는다. 저장된 것이 아무리 오래됐어도 그것이 시연이 보여 줄 값이다.
        cached = _from_file(CACHE_FILE, "cached", organization_id)
        if cached:
            return cached
        sample = _from_file(SAMPLE_FILE, "sample", organization_id)
        if sample:
            return sample
        return SupportProgramListResponse(
            source="sample",
            bizinfo_api_configured=bizinfo_client.is_configured(),
            fetched_at=None,
            total_fetched=0,
            count=0,
            error="새 공고 받기가 꺼져 있는데 저장된 지원사업 목록이 없습니다.",  # 설정 이름은 화면에 적지 않는다(27차 §3-H)
            field_mapping_verified=FIELD_MAPPING_VERIFIED,
            items=[],
        )

    if not refresh:
        cached = _from_file(CACHE_FILE, "cached", organization_id)
        if cached and cached.fetched_at and (storage.utc_now() - cached.fetched_at).total_seconds() < CACHE_TTL_SECONDS:
            return cached

    error: str | None = None
    if bizinfo_client.is_configured():
        try:
            body = await bizinfo_client.fetch_programs_raw(count=count)
            items = bizinfo_client.extract_items(body)
            # 바로 위 신선도 계산이 이 값을 되읽는다 — 그래서 같은 시계여야 한다.
            now = storage.utc_now()
            # 저장을 막았으면 **그 사실이 화면까지 간다** (ISSUE-121). 받아 온 목록은
            # 그대로 보여 주되, 캐시를 지켰다는 것을 `source_errors` 로 말한다.
            shrink = _save_cache(items, now)
            views = _views(items, organization_id)
            return SupportProgramListResponse(
                source="bizinfo",
                bizinfo_api_configured=True,
                fetched_at=now,
                total_fetched=len(items),
                count=len(views),
                error=shrink,
                field_mapping_verified=FIELD_MAPPING_VERIFIED,
                total_available=bizinfo_client.total_count(items),
                items=views,
            )
        except bizinfo_client.BizinfoError as exc:
            error = str(exc)
            logger.warning("기업마당 호출 실패, 캐시/샘플로 대체: %s", error)

    cached = _from_file(CACHE_FILE, "cached", organization_id)
    if cached:
        cached.error = error or cached.error
        return cached
    sample = _from_file(SAMPLE_FILE, "sample", organization_id)
    if sample:
        if error:
            sample.error = f"{error} — 가상 예시 목록을 표시합니다."
        return sample
    return SupportProgramListResponse(
        source="sample",
        bizinfo_api_configured=bizinfo_client.is_configured(),
        fetched_at=None,
        total_fetched=0,
        count=0,
        error=error or "기업마당 데이터가 없습니다 (키·캐시·샘플 모두 없음)",
        field_mapping_verified=FIELD_MAPPING_VERIFIED,
        items=[],
    )
