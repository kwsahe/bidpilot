"""공고 조회 서비스: 나라장터 실호출 -> 매핑 -> AI/교육 후보 필터 -> 캐시.

CLAUDE.md 20: API 실패 시 캐시된 응답을 쓰고 출처를 UI에 표시한다.
캐시에는 서비스키를 저장하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Sequence

from app.core import storage
from app.core.config import get_settings
from app.core.paths import DATA_ROOT
from app.schemas.procurement import ProcurementNotice
from app.services import (
    collect_keywords_service,
    g2b_client,
    g2b_mapper,
    home_agencies,
    opportunity_filter,
    qualification_store,
    recommendation,
    work_kinds,
)
from app.services.opportunity_filter import CandidateMatch, classify, filter_candidates

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_ROOT / "public" / "sample_procurements"
#: **살아 있는 나라장터 저장본** — Git 밖(33차 · `docs/refresh_procedure.md` §0). 받기(매일 아침 자동 받기 포함)는 늘 여기에 쓴다.
#: 예전에는 추적 파일을 덮어써 매일 작업 트리가 바뀌고 「시작 = 끝」 규칙이 깨졌다.
CACHE_FILE = DATA_ROOT / "private" / "cache" / "g2b" / "g2b_cache.json"
#: **기준본 · 장애 대비 예시**(Git 추적 · 키트에도 들어감). 살아 있는 저장본이 없을 때만 읽는다. 바꾸는 것은 담당자가 정할 때
#: 살아 있는 저장본을 복사해 커밋하는 것뿐이다.
BASELINE_CACHE_FILE = CACHE_DIR / "g2b_cache.json"
# 데모 고정 공고 저장소. 일반 캐시와 분리해 두어 캐시가 갱신돼도 사라지지 않는다.
PINNED_FILE = CACHE_DIR / "pinned_notices.json"

# 캐시 파일은 Git 에 커밋된다. 나라장터가 공개하는 값이라도 발주기관 담당자의
# 전화·이메일을 저장소에 그대로 들고 있을 이유가 없다 — 이름과 짝지어지면
# 이름 단독보다 훨씬 강한 개인 식별자가 된다.
# 배포 스냅샷은 이미 같은 값을 가리므로(scripts/snapshot_demo_api.py), 원본 캐시만
# 가리지 않으면 앞뒤가 맞지 않고 스냅샷을 다시 뜰 때마다 여기서 다시 흘러든다.
# 담당자 **이름**(ntceInsttOfclNm 등)은 입찰 실무에서 쓰이므로 남긴다.
CONTACT_MASKS = {
    "ntceInsttOfclTelNo": "[전화 원문 확인]",
    "ntceInsttOfclEmailAdrs": "[이메일 원문 확인]",
    "dminsttOfclEmailAdrs": "[이메일 원문 확인]",
}

TEL_MASK = "[전화 원문 확인]"
EMAIL_MASK = "[이메일 원문 확인]"

# 필드 이름 목록만으로는 부족하다 — **예상하지 못한 필드**가 연락처를 실어 나른다.
# 실측(2026-09-10 재수집): `dcmtgOprtnPlce`(설명회 운영 장소)에 「시설사업팀 신동수(043-871-5096)」처럼
# 담당자 이름과 전화번호가 함께 들어와 캐시에 그대로 저장됐다. 그 필드는 목록에 없었다.
# 그래서 값 자체에서도 연락처 모양을 가린다. 새 필드가 생겨도 자동으로 막힌다.
#
# 이름은 그대로 둔다 — 위 CONTACT_MASKS 주석과 같은 이유로 입찰 실무에서 쓰인다.
# 가리는 것은 이름과 짝지어졌을 때 개인 식별자가 되는 **번호**다.
# 39차 MANUAL-08 — 점 · 괄호 · 빈칸으로 나눈 꼴도(「010.1234.5678」 · 「062)123-4567」 · 「(062) 123-4567」 · 「010 1234 5678」).
_TEL_IN_TEXT_RE = re.compile(r"(?<![\d-])(?:\(0\d{1,2}\)\s?|0\d{1,2}(?:[-.)]\s?|\s))\d{3,4}[-.\s]\d{4}(?![\d-])")
# 39차 MANUAL-02 — 앞 글자가 주소 글자면 시작하지 않는다(경계에서만 시작 · 길이 상한). 「A」 수만 자에서 시작점마다 끝까지 훑어
# 제곱으로 느려졌다(4만 자 1.9초 · 1억 자 수 시간 — 그동안 서버 전체가 멈춤).
_EMAIL_IN_TEXT_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}")


def mask_contact_text(text: str) -> str:
    """자유 서술 안의 전화·이메일을 가린다. 주변 문맥(부서·이름)은 그대로 둔다."""
    masked = _TEL_IN_TEXT_RE.sub(TEL_MASK, text)
    return _EMAIL_IN_TEXT_RE.sub(EMAIL_MASK, masked)


def mask_contact_fields(value: Any) -> Any:
    """저장 전 담당자 연락처를 가린다. 빈 값은 그대로 둔다 (없는 것과 가린 것을 구분한다).

    두 겹으로 막는다 — 알려진 연락처 **필드**를 통째로 가리고, 그 밖의 모든 문자열에서
    연락처 **모양**을 가린다. 한 겹만 두면 새로 생긴 필드로 계속 새어 나간다.
    """
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if key in CONTACT_MASKS and isinstance(item, str) and item.strip():
                masked[key] = CONTACT_MASKS[key]
            else:
                masked[key] = mask_contact_fields(item)
        return masked
    if isinstance(value, list):
        return [mask_contact_fields(item) for item in value]
    if isinstance(value, str):
        return mask_contact_text(value)
    return value


NoticeSource = Literal["g2b", "cached"]

DEFAULT_DAYS = 14
#: 저장 상한 — 공고명 검색으로 받은 공고(중복 뺌)를 이만큼까지 둔다. 600 이던 때는 받은 649건 중 49건이 말없이 잘렸다
#: (2026-11-12 실측 — 예전에는 AI · 교육의 2 · 3쪽, 7일 창으로 나눈 2.8.1 처음에는 뒤쪽 낱말 컨설팅 · AX · ESG 의 마감 전 후보 29건).
#: 하루 호출 예산(`g2b_client.MAX_COLLECT_CALLS` 200회 · 100건씩)에 맞춘 여유 — 넘으면 자르고 기록에 남긴다.
DEFAULT_MAX_ITEMS = 2000

# 디스크 캐시를 그대로 쓸 수 있는 신선도(초). 발표 중 첫 화면이 11초씩 걸리지 않도록
# 이 시간 안에서는 나라장터를 다시 부르지 않는다. 사용자가 '분석 실행'을 누르면 강제 갱신한다.
CACHE_TTL_SECONDS = 900


def live_fetch_enabled() -> bool:
    """나라장터를 실제로 불러도 되는가 (`G2B_LIVE_FETCH`, **기본 끔** — ISSUE-120).

    14차부터 기본값이 꺼짐이다. 환경변수를 세우지 않고 앱을 import 하면 바깥을 부르지
    못한다 — 진단 스크립트가 캐시를 덮어쓴 사고가 세 번 나서 내린 결정이다. 켜는 자리는
    `scripts/start_dev.ps1`(고정 모드가 아닐 때)과 실제로 받아 오는 스크립트뿐이다.

    꺼진 상태가 **시연 고정 모드**다. TTL 이 지나든 `refresh=True` 가 오든 저장된 캐시만 읽는다.
    시연 중 목록을 한 번 새로 받으면 공고 건수·순위가 바뀌고 git 이 추적하는 캐시 파일까지
    덮어써져, 큐시트와 리허설 캡처가 통째로 어긋난다 (ISSUE-062).

    함수로 두는 이유: 설정은 `lru_cache` 라 기동 시 한 번 읽히지만, 테스트가
    `get_settings.cache_clear()` 로 갈아 끼울 수 있어야 한다. 모듈 상수로 굳히면 그게 막힌다.
    """
    return bool(get_settings().g2b_live_fetch)

# 본선 데모에서 목록에 반드시 있어야 하는 공고 (CLAUDE.md 20 "데모 샘플 고정").
# 나라장터 목록 조회는 최근 N일치를 앞에서부터 max_items건까지만 가져오므로, 조회 시점에
# 따라 특정 공고가 뒤로 밀려 빠질 수 있다. 빠지면 캐시에서 되살려 붙인다.
# 한 번 붙으면 save_cache가 함께 저장하므로 이후 조회에서도 계속 남는다.
PINNED_NOTICE_NOS: tuple[str, ...] = (
    "R26BK01699556",  # 가천대 AI부트캠프 생성형 AI 활용 교육 기획·운영
    "R26BK01697240",
    "R26BK01707959",
    "R26BK01704406",
)

# 프로세스 메모리 캐시 — 같은 요청 안에서 get_notice가 목록을 반복 조회하는 것을 막는다.
# 항상 include_low=True(전체 후보) 기준으로 담고, 읽을 때 걸러 쓴다.
_MEMO: dict[int, "ProcurementResult"] = {}
#: 11-01 — 실시간 받기가 실패하면 그 저장본 대체 결과를 잠시 기억한다. 조달청 점검 중 화면을 열 때마다
#: 21번씩 다시 불러 목록 하나가 5~10초 · 대시보드가 30초 넘게 걸렸다. 「새로 받기」(refresh)는 기다리지 않는다.
#: 저장본 파일(시각 · 크기)이 바뀌면 — 다른 프로세스(매일 받기)가 받았으면 — 기억을 버린다. 성공하면 모든 기간을 지운다.
_FAILED: dict[int, tuple[datetime, tuple[int, int] | None, "ProcurementResult"]] = {}
FAILED_RETRY_SECONDS = 600


def _cache_stamp() -> tuple[int, int] | None:
    try:
        stat = CACHE_FILE.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


class NoNoticeDataError(RuntimeError):
    """실호출도 실패하고 캐시도 없음."""


@dataclass(frozen=True)
class NoticeView:
    notice: ProcurementNotice
    match: CandidateMatch

    # 목록에서의 검토 우선순위 (1부터). 정렬 후 부여하며, 정렬 전에는 None이다.
    rank: int | None = None

    # 이번 조회에서 나라장터가 준 것이 아니라, 저장소에서 되살려 붙인 고정 공고인가.
    # 목록 전체의 source 는 "g2b" 라도 이 행만은 방금 받아온 것이 아니다 —
    # 마감이 지났거나 내용이 바뀌었을 수 있어서, 화면에 그대로 알려야 한다.
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = self.notice.model_dump(mode="json")
        # 화면 기관 칸은 통합 목록 · 브리핑과 같은 표시값(조달청 대행이면 「수요기관(조달청 대행)」 · 43차 BRIEF-03) — 10-31 최종 점검 B2:
        # 사업기회 행 · 입찰 분석 머리 · 고르기 칸은 「조달청」, 레이더 · 제안서 작성은 「한국인터넷진흥원(조달청 대행)」으로 갈렸다.
        # 저장된 원래 값(notice.agency)은 지역 판정에 쓰므로 응답에서만 바꾼다.
        payload["agency"] = home_agencies.display_agency(self.notice.agency, (self.notice.raw_data or {}).get("demand_institution"))
        payload["candidate"] = self.match.to_dict()
        # 목록 화면이 행마다 보여줄 추천등급 (낙찰확률 아님, CLAUDE.md 12).
        # 회사 프로필을 넘기지 않으면 지역은 합성 상수로, 규모는 「판정하지 않았습니다」로 굳는다.
        # 통합 목록은 이미 회사 값으로 계산하므로, 넘기지 않으면 같은 공고의 등급이 화면마다 갈린다.
        basis = _company_basis()
        payload["recommendation"] = recommendation.evaluate(
            self.notice,
            self.match,
            preferred_regions=basis.preferred_regions,
            capacity_krw=basis.capacity_krw,
            phrases=basis.phrases,
        ).to_dict()
        # 일의 종류(갈래) — 「AI 교육이냐 개발이냐」. 상세 분석과 **같은 규칙표**를 쓴다.
        # 캐시에는 담지 않는다 — load_cache 가 저장된 candidate 를 버리고 다시 계산하는 구조라
        # 규칙을 고치면 캐시를 다시 뜨지 않아도 다음 조회에 바로 반영된다.
        payload["work"] = work_kinds.of_notice(self.notice)
        payload["rank"] = self.rank
        payload["pinned"] = self.pinned
        return payload


@dataclass(frozen=True)
class ProcurementResult:
    source: NoticeSource
    notices: list[NoticeView]
    fetched_at: datetime
    total_fetched: int
    error: str | None = None
    # 어떤 조회 기간(일)으로 받은 결과인지. 캐시를 기간별로 구분하기 위해 쓴다.
    # 옛 캐시에는 없으므로 None 일 수 있다.
    days: int | None = None
    #: 「어떻게 받았는가」 — 화면의 「데이터 상태」에 그대로 적는다 (0920 §4-A-3).
    #: 옛 캐시에는 없으므로 None 일 수 있다. 그때 화면은 이 줄을 적지 않는다.
    collected_by: str | None = None
    #: 그때 나라장터를 부른 횟수. 캐시에서 읽은 결과면 「그 캐시를 만들 때」의 값이다.
    collect_calls: int | None = None
    #: 이번 실호출에서 자격 제한 하루 표를 **새로 받은** 날 수 · 부른 횟수 · 못 받은 사유 (20차 §4-G —
    #: 재수집 결과 한 줄). 캐시·`to_dict` 에는 넣지 않는다 — 읽을 때마다 파일이 다시 쓰이는 함정(ISSUE-038).
    qualification_days_fetched: int = 0
    qualification_calls: int = 0
    qualification_note: str | None = None
    #: 받아 왔지만 분류가 `none`(본업 낱말도 수집 낱말도 없음)이라 저장하지 않은 수(39차 COLLECT-09 — 조용히 사라지지 않게 매일 받기 기록에 적는다).
    dropped_none: int = 0
    #: 이번 실행에서 실패한 나라장터 호출 수(39차 DAILY-06 · 로그 「실패_호출」).
    failed_calls: int = 0
    #: 낱말 일부가 실패해 그 몫을 지난 저장본으로 채웠다 — 「일부 실패 — …」(39차 DAILY-02). 없으면 None.
    partial_failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "g2b_api_configured": g2b_client.is_configured(),
            # 시연 고정 모드인가. 화면이 「저장된 목록을 씁니다」를 띄우고 새로고침을 잠그는 근거.
            # 키가 있는데도 부르지 않는 상태이므로 `g2b_api_configured` 만으로는 구분되지 않는다.
            "frozen": not live_fetch_enabled(),
            "fetched_at": self.fetched_at.isoformat(),
            "total_fetched": self.total_fetched,
            "count": len(self.notices),
            "error": self.error,
            # 「어떻게 받았는가」와 「몇 번 불렀는가」. 화면이 데이터 상태에 그대로 적는다.
            "collected_by": self.collected_by,
            "collect_calls": self.collect_calls,
            "notices": [view.to_dict() for view in self.notices],
        }


#: 캐시 비교에서 빼는 키 — 내용과 무관하게 매번 달라진다.
_CACHE_VOLATILE_KEYS = ("fetched_at", "stored_at", "updated_at", "collect_calls")


#: 살아 있는 저장본을 읽을 수 있는가 — (파일 시각 · 크기) 한 벌만 기억한다(요청마다 1.6MB 를 다시 풀지 않게).
_LIVE_CACHE_OK: dict[tuple[str, int, int], bool] = {}


def _live_cache_ok() -> bool:
    """살아 있는 저장본이 있고 **읽을 수 있는가**(JSON · `notices` 목록). 34차 R33-R1 — 「파일이 있나」만 보면 깨진 파일 하나로
    기준본이 멀쩡해도 목록 전체가 「저장된 목록 없음」이 됐고(git checkout 으로도 안 나음), 줄어듦 차단도 풀렸다(R33-R3)."""
    try:
        stat = CACHE_FILE.stat()
    except OSError:
        return False
    key = (str(CACHE_FILE), stat.st_mtime_ns, stat.st_size)
    if key not in _LIVE_CACHE_OK:
        try:
            payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            ok = isinstance(payload, dict) and isinstance(payload.get("notices"), list)
        except (OSError, ValueError):
            ok = False
        if not ok:
            logger.warning("살아 있는 나라장터 저장본을 읽지 못해 기준본을 씁니다: %s", CACHE_FILE)
        _LIVE_CACHE_OK.clear()
        _LIVE_CACHE_OK[key] = ok
    return _LIVE_CACHE_OK[key]


def cache_read_path() -> Path:
    """읽을 저장본 — 살아 있는 저장본을 **읽을 수 있으면** 그것, 아니면 기준본(경고 로그). 백필 · 줄어듦 비교도 이 함수 하나."""
    return CACHE_FILE if _live_cache_ok() else BASELINE_CACHE_FILE


def _same_cache(payload: dict) -> bool:
    """저장된 캐시가 새 결과와 (받은 시각을 빼고) 같은가. 못 읽으면 False — 쓰는 쪽으로 기운다."""
    try:
        stored = storage.read_json(CACHE_FILE, default=None)
    except Exception:  # noqa: BLE001 — 깨진 캐시면 새로 쓴다
        return False
    if not isinstance(stored, dict):
        return False
    return {k: v for k, v in stored.items() if k not in _CACHE_VOLATILE_KEYS} == {
        k: v for k, v in payload.items() if k not in _CACHE_VOLATILE_KEYS
    }


def save_cache(
    views: list[NoticeView],
    total_fetched: int,
    fetched_at: datetime,
    days: int | None = None,
    *,
    collected_by: str | None = None,
    collect_calls: int | None = None,
) -> str | None:
    """캐시를 쓴다. **크게 줄어드는 저장은 막고** 사유를 돌려준다 (ISSUE-121). 쓰는 곳은 늘 살아 있는 저장본(Git 밖)."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    note = "나라장터 실호출 결과 캐시. API 장애 시 fallback으로 사용한다. 서비스키는 포함하지 않는다."
    if collected_by:
        note = f"{note} 수집 방식: {collected_by}."
    payload = {
        "_note": note,
        # 사람이 읽는 `_note` 와 별개로 화면이 그대로 쓸 수 있게 따로 둔다.
        # **가변값(호출 횟수)은 여기 넣지 않는다** — `_same_cache` 가 매번 달라져
        # 목록을 열 때마다 92만 바이트짜리 캐시가 다시 쓰인다 (ISSUE-038 재발).
        "collected_by": collected_by,
        "collect_calls": collect_calls,
        "fetched_at": fetched_at.isoformat(),
        # 어떤 조회 기간으로 받은 결과인지 남긴다. 이게 없으면 14일 요청이 60일 캐시를
        # (또는 그 반대를) 그대로 받아, 기간을 바꿔도 건수가 그대로인 것처럼 보인다.
        "days": days,
        "total_fetched": total_fetched,
        "notices": [
            {
                "notice": view.notice.model_dump(mode="json"),
                "candidate": view.match.to_dict(),
                # 되살려 붙인 고정 공고라는 사실을 캐시에도 남긴다. 이걸 빼면 다음 조회에서
                # 「방금 나라장터에서 받아온 공고」와 구분되지 않는다.
                "pinned": view.pinned,
            }
            for view in views
        ],
    }
    masked = mask_contact_fields(payload)

    # **크게 줄어드는 저장은 막는다** (ISSUE-121). 12차에 떠 있던 개발 서버가 캐시를
    # 덮었을 때 건수가 줄었고, 그 파일은 git 이 추적한다 — 줄어든 채로 커밋되면
    # 큐시트·기준 답안이 통째로 어긋난다. 의심스러우면 옛것을 지킨다.
    existing = 0
    stored = None
    try:
        # 줄어듦은 지금 읽고 있는 저장본과 견준다 — 살아 있는 저장본이 아직 없으면 기준본(33차 · 안 1)
        stored = storage.read_json(cache_read_path(), default=None)
    except storage.CorruptJsonError:
        stored = None
    if isinstance(stored, dict):
        # 2.0.7 — 지금 낱말(기본 + 추가) 어느 것에도 걸리지 않는 저장 공고는 다음 받기에서 빠지는 것이 맞다(추가 낱말을 지움).
        # 줄어듦 비교에서 뺀다 — 낱말을 지운 다음 날 받기가 「저장하지 않음」으로 막혀 그날 새 공고가 0 이 되지 않게.
        existing = sum(1 for entry in stored.get("notices") or [] if _still_searched(entry))
    shrink = storage.cache_shrink_reason(existing=existing, incoming=len(views))
    if shrink:
        logger.warning("공고 캐시를 쓰지 않았습니다 — %s", shrink)
        return shrink

    # 내용이 같으면 다시 쓰지 않는다 (ISSUE-038).
    #
    # 예전에는 이 파일을 git 이 추적해, 목록을 볼 때마다 `fetched_at` 만 바뀐 파일이 1,800줄짜리 diff 를 만들었다.
    # 33차부터 살아 있는 저장본은 Git 밖이지만, 같은 내용을 다시 쓰지 않는 규칙은 그대로 둔다(파일 시각이 메모 열쇠다).
    if _same_cache(masked):
        logger.info("공고 캐시가 이전과 같아 파일을 다시 쓰지 않았습니다")
    else:
        storage.write_json_atomic(CACHE_FILE, masked)
    # 공고 변경 감지: 핵심 필드 스냅샷을 남긴다. 실패해도 목록 조회는 계속된다.
    try:
        from app.services import notice_version_service

        notice_version_service.record_many([view.notice for view in views], observed_at=fetched_at)
    except Exception as exc:  # noqa: BLE001 — 부가 기능이 본 기능을 막지 않는다
        logger.warning("공고 버전 기록 건너뜀: %s", exc)
    return None


def _still_searched(entry: Any) -> bool:
    """저장본 한 줄이 지금 낱말로도 받히는가(고정 공고는 늘 참). 공고명 검색과 같은 부분 일치 — `prespec_service.wanted`."""
    from app.services import prespec_service

    if not isinstance(entry, dict):
        return False
    return bool(entry.get("pinned")) or bool(prespec_service.wanted((entry.get("notice") or {}).get("title")))


def _parse_stored_time(raw: object) -> datetime | None:
    """우리가 쓴 `fetched_at` 을 되읽는다.

    예전에는 `g2b_mapper.parse_datetime` 을 썼는데 **그것은 나라장터 형식**
    (`2026-08-20 01:14:56`)을 위한 함수다. 우리는 `.isoformat()` 으로 쓰므로
    (`2026-09-16T17:29:32.135523+00:00`) 한 번도 맞은 적이 없고, 그때마다 조용히
    `datetime.now()` 로 떨어졌다. 그래서 **캐시를 보여줄 때 화면의 「조회 시각」이 늘
    «지금»이었다** — 몇 시간 전 자료를 방금 받아온 것처럼 보였다.

    옛 캐시가 나라장터 형식으로 적혀 있을 수 있어 그쪽도 남겨 둔다.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return g2b_mapper.parse_datetime(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _with_schedule(notice: ProcurementNotice) -> ProcurementNotice:
    """공고문 일정표의 가장 이른 마감(43차 결정 1)을 `raw_data` 에도 싣는다 — 대시보드 머리(공고 원본을 읽는 화면)가 목록과 같은
    실제 마감을 세게(`frontend/src/lib/deadline.noticeDeadlinePair`). 조항 파일이 없으면 그대로."""
    from app.services import notice_schedule, qualification_clause_service

    payload = qualification_clause_service.load(notice.id)
    schedule = (payload or {}).get("schedule") if isinstance(payload, dict) else None
    first = notice_schedule.earliest(schedule, after=notice.published_at)
    if not first:
        return notice
    raw = dict(notice.raw_data or {})
    raw["schedule_deadline"] = first["at"]
    raw["schedule_deadline_label"] = first["label"]
    raw["schedule_deadline_time_known"] = bool(first.get("time_known"))  # 44차 M3 — 날짜만이면 화면이 「(시각 원문 확인)」
    raw["briefing_required"] = bool((schedule or {}).get("briefing_required"))
    return notice.model_copy(update={"raw_data": raw})


def _maybe_schedule(notice: ProcurementNotice, with_schedule: bool) -> ProcurementNotice:
    return _with_schedule(notice) if with_schedule else notice


def load_cache(*, with_schedule: bool = True) -> ProcurementResult | None:
    """저장본을 읽어 다시 분류한다. `with_schedule=False` 는 공고문 일정(조항 파일에서 읽는 값)을 `raw_data` 에 싣지 않는다 —
    읽은 것을 다시 저장하는 쪽(바로 찾기 합치기)이 옛 일정 값을 저장본에 굳히지 않게."""
    path = cache_read_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        views = [
            NoticeView(
                notice=(n := _maybe_schedule(g2b_mapper.normalized(ProcurementNotice.model_validate(entry["notice"])), with_schedule)),
                match=classify(n),
                pinned=bool(entry.get("pinned")),
            )
            for entry in payload.get("notices", [])
        ]
    except (ValueError, KeyError, TypeError):
        return None
    fetched_at = _parse_stored_time(payload.get("fetched_at")) or _now()
    raw_days = payload.get("days")
    raw_calls = payload.get("collect_calls")
    collected_by = payload.get("collected_by")
    return ProcurementResult(
        source="cached",
        notices=views,
        fetched_at=fetched_at,
        total_fetched=int(payload.get("total_fetched", len(views))),
        days=int(raw_days) if isinstance(raw_days, int) else None,
        # 옛 캐시에는 없다. 없으면 화면이 수집 방식 줄을 적지 않는다 — 지어내지 않는다.
        collected_by=collected_by if isinstance(collected_by, str) and collected_by else None,
        collect_calls=raw_calls if isinstance(raw_calls, int) else None,
    )


def clear_memo() -> None:
    """프로세스 메모리 캐시를 비운다 (테스트·캐시 경로 변경 시)."""
    global _COMPANY_BASIS
    _MEMO.clear()
    _FAILED.clear()
    _FROZEN_STAMPS.clear()
    _COMPANY_BASIS = None


def _now() -> datetime:
    """**이 모듈의 「지금」** — 시계를 읽는 자리는 여기 하나다 (ISSUE-118 · prompt_03 §4-C).

    왜 함수로 두는가: 캐시 신선도(`CACHE_TTL_SECONDS`)를 재는 쪽과 테스트가 캐시를
    **심는** 쪽이 서로 다른 시계를 보면, 테스트가 시각과 함께 늙는다. 실제로
    `test_daily_digest.py` 가 `NOW = 2026-09-19 03:00` 으로 캐시를 심고 서비스는 실제
    시계로 TTL 을 재서, 그 시각 + 15분이 지난 **다음 날부터** 「캐시가 오래됐다 → 다시
    받아라」가 되어 실패했다. 코드가 바뀌어서가 아니라 **날짜가 지나서** 빨개진 것이다.

    그런 테스트는 고쳐도 통과 여부를 믿을 수 없다. 그래서 「지금」을 한 자리에 모아
    테스트가 갈아 끼울 수 있게 한다 — `monkeypatch.setattr(procurement_service, "_now", ...)`.

    17차부터 그 시계는 **저장소 전체와 같은 것**이다(`storage.utc_now`, ISSUE-133).
    이 모듈만 앞당기면 목록·상세·마감 판정이 서로 다른 날을 본다.
    """
    return storage.utc_now()


def _age_seconds(moment: datetime) -> float:
    now = _now()
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return (now - aware).total_seconds()


@dataclass(frozen=True)
class CompanyBasis:
    """추천등급이 «선택한 회사»를 보고 판단하기 위해 필요한 값.

    둘 다 None 이면 예전과 같이 동작한다 — 지역은 합성 기본값, 규모는 미판정.
    회사가 적지 않은 값을 지어내지 않기 위한 기본형이다 (CLAUDE.md 11).
    """

    preferred_regions: tuple[str, ...] | None = None
    capacity_krw: int | None = None
    # 의미 매칭 비교 대상(회사 사업영역·주요 고객·보유 인증 문구). 비어 있으면 의미 매칭을
    # 아예 하지 않고 지금까지의 키워드 규칙 값을 쓴다.
    phrases: tuple[str, ...] = ()


# 목록 한 번에 공고 수십 건이 같은 회사 값을 쓴다. 행마다 프로필·역량 파일을 다시 읽지 않도록
# 한 번 읽어 재사용한다. 유지 시간을 짧게 둔 이유: 회사정보를 고친 뒤 목록으로 돌아왔을 때
# 바로 반영되어야 하는데, 저장하는 쪽에서 이 캐시를 비워 주는 고리가 아직 없다.
_COMPANY_BASIS_TTL_SECONDS = 30
_COMPANY_BASIS: tuple[datetime, CompanyBasis] | None = None


def _load_company_basis() -> CompanyBasis:
    """기본 조직의 활동 지역·단독 수행 규모를 읽는다.

    지역 토큰을 뽑는 규칙과 수행 규모를 읽는 규칙은 통합 목록(opportunity_priority)이 이미
    가지고 있다. 두 벌로 만들면 같은 공고의 등급이 화면마다 갈린다 — 그래서 그대로 쓴다.
    함수 안에서 import 하는 이유: 모듈 맨 위에서 부르면
    procurement_service → opportunity_priority → eligibility_engine → procurement_service 로
    고리가 닫혀 ImportError 가 난다.
    """
    try:
        from app.core.config import get_settings
        from app.services import company_service, opportunity_priority

        organization_id = get_settings().default_organization_id
        profile = company_service.load_profile(organization_id)
        return CompanyBasis(
            preferred_regions=opportunity_priority._profile_regions(profile),
            capacity_krw=opportunity_priority._capacity_krw(organization_id),
            # 통합 목록과 «같은» 문구를 쓴다. 여기만 빠뜨리면 목록 화면에서는 의미 매칭이
            # 영영 켜지지 않는다 (화면이 읽는 자리가 recommendation 이기 때문이다).
            phrases=recommendation.company_phrases(
                business_domains=profile.business_domains,
                target_clients=profile.target_clients,
                certifications=profile.certifications,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — 회사자료를 못 읽는다고 공고 목록이 죽으면 안 된다
        logger.warning("회사 프로필을 읽지 못해 추천등급을 예전 기준으로 계산합니다: %s", exc)
        return CompanyBasis()


def _company_basis() -> CompanyBasis:
    global _COMPANY_BASIS
    cached = _COMPANY_BASIS
    if cached is not None and _age_seconds(cached[0]) <= _COMPANY_BASIS_TTL_SECONDS:
        return cached[1]
    basis = _load_company_basis()
    _COMPANY_BASIS = (_now(), basis)
    return basis


def rank_notices(views: list[NoticeView]) -> list[NoticeView]:
    """추천 점수 순으로 정렬하고 1부터 순위를 매긴다.

    등급(HIGH/MEDIUM) 구간만으로는 같은 등급 안에서 무엇을 먼저 볼지 알 수 없다.
    뒤로 보내는 순서는 정상 → 사업영역 밖 → 마감 경과다.
    사업영역 밖 공고는 gate_reason에 "후순위로 내렸습니다"라고 적으므로
    정렬에서도 실제로 내려야 표시와 동작이 일치한다.
    """
    # 화면에 찍는 등급(to_dict)과 **같은 기준**으로 정렬해야 한다. 회사 프로필을 한쪽에만
    # 넘기면 1위로 정렬된 행이 화면에서는 다른 등급으로 보인다.
    basis = _company_basis()
    scored = [
        (
            recommendation.evaluate(
                v.notice,
                v.match,
                preferred_regions=basis.preferred_regions,
                capacity_krw=basis.capacity_krw,
                phrases=basis.phrases,
            ),
            v,
        )
        for v in views
    ]

    def sort_key(pair: tuple[Any, NoticeView]):
        rec, view = pair
        if rec.grade == "NO_GO":
            bucket = 2
        elif rec.out_of_scope:
            bucket = 1
        else:
            bucket = 0
        # 점수가 같으면 마감이 이른 순, 마감이 없으면 뒤로.
        deadline = view.notice.deadline_at
        return (bucket, -rec.score, deadline is None, deadline or view.notice.published_at)

    scored.sort(key=sort_key)
    return [
        replace(view, rank=index)
        for index, (_, view) in enumerate(scored, start=1)
    ]


def _narrow(result: ProcurementResult, include_low: bool) -> ProcurementResult:
    """요청한 범위만 남기고 그 안에서 순위를 다시 매긴다 (네트워크 호출 없음)."""
    kept = result.notices if include_low else [v for v in result.notices if v.match.is_candidate]
    return replace(result, notices=rank_notices(kept))


def cached_if_fresh(*, ttl: int = CACHE_TTL_SECONDS, days: int | None = None) -> ProcurementResult | None:
    """TTL 안의 캐시가 있으면 그대로 돌려준다 (네트워크 호출 없음).

    days 를 넘기면 **같은 조회 기간으로 받은 캐시**만 쓴다.
    기간이 다르면 담긴 공고 집합 자체가 다르므로, 그대로 돌려주면 화면의 기간 선택이
    아무 일도 하지 않는 것처럼 보인다. 기간을 모르는 옛 캐시(days=None)는 재사용하지 않는다.
    """
    cached = load_cache()
    if cached is None:
        return None
    if _age_seconds(cached.fetched_at) > ttl:
        return None
    if days is not None and cached.days != days:
        return None
    return cached


def _pin_key(view: NoticeView) -> str:
    """공고번호에서 차수를 뗀 값 (R26BK01699556-000 -> R26BK01699556)."""
    return g2b_mapper.base_notice_no(view.notice.notice_no)


def split_revisions(
    notices: list[ProcurementNotice],
) -> tuple[list[ProcurementNotice], dict[str, list[ProcurementNotice]]]:
    """차수를 최신 하나로 묶고, **밀려난 이전 차수도 함께 돌려준다**.

    정정·재공고가 나면 공고번호는 그대로고 차수만 올라간다(-000 → -001 → -002).
    묶지 않으면 한 사업이 화면에서 3건으로 세어져 숫자가 부풀고, 화면마다 자르는 개수가
    달라 어디서는 보이고 어디서는 안 보이게 된다. 실측(2026-09-17): 마감 전 후보 117건 중
    15건이 차수 중복이었다.

    이전 차수를 버리지 않고 돌려주는 이유는 그것이 **변경 기록**이기 때문이다 — 「무엇이
    바뀌어 재공고가 났는가」는 담당자가 가장 먼저 묻는 것이다(0920 §4-A-1).

    `revision_count` 는 **서로 다른 차수의 수**다. 「몇 번 수집됐는가」가 아니다 —
    키워드 조회는 같은 공고를 여러 키워드에서 물어오므로, 등장 횟수를 세면 차수가 하나뿐인
    공고가 「차수 3건 중 최신」이라고 거짓말한다.

    원래 순서를 지킨다 — 수집 순서가 뒤에서 정렬 기준으로 쓰인다.
    """
    best: dict[str, ProcurementNotice] = {}
    seen: dict[str, dict[int, ProcurementNotice]] = {}
    for notice in notices:
        key = g2b_mapper.base_notice_no(notice.notice_no)
        order = g2b_mapper.notice_order(notice.notice_no)
        # 같은 차수가 두 번 들어오면 한 번으로 센다 (키워드 조회는 중복이 정상이다).
        seen.setdefault(key, {})[order] = notice
        current = best.get(key)
        if current is None or order > g2b_mapper.notice_order(current.notice_no):
            # 최신 차수로 갈아끼우되 목록에서의 자리는 처음 자리를 유지한다.
            best[key] = notice
    latest = [
        notice.model_copy(update={"revision_count": len(seen[key])}) for key, notice in best.items()
    ]
    superseded = {
        best[key].id: [seen[key][order] for order in sorted(seen[key]) if seen[key][order] is not best[key]]
        for key in seen
        if len(seen[key]) > 1
    }
    return _collapse_reposts(latest, superseded)


def _repost_key(notice: ProcurementNotice) -> tuple[str, str, int | None]:
    """같은 사업이 **공고번호를 바꿔** 다시 올라온 것을 가리는 열쇠 (0922 §4-B-5).

    차수(`-000` → `-001`)만 바뀌는 정정은 위에서 이미 묶었다. 그런데 취소 뒤 새 번호로
    다시 올리는 일이 흔하다 — 실측: SBS 「미래인류 AI 페르소나」가 R26BK01726683 과
    R26BK01727020 으로 두 줄, 연암공과대 「AI Agent 성과관리」가 세 줄이었다.

    **제목·발주기관·예산이 모두 같을 때만** 같은 사업으로 본다. 셋 중 하나라도 다르면
    다른 로트일 수 있으므로 묶지 않는다 — 있는 공고를 지우는 쪽이 더 비싼 실수다.
    예산이 없는 공고(`budget is None`)는 아예 묶지 않는다: 금액이 빠지면 근거가 둘뿐이라
    같은 기관의 다른 사업까지 한 줄로 접힐 수 있다.
    """
    return (" ".join(notice.title.split()), notice.agency, notice.budget)


def _collapse_reposts(
    notices: list[ProcurementNotice], superseded: dict[str, list[ProcurementNotice]]
) -> tuple[list[ProcurementNotice], dict[str, list[ProcurementNotice]]]:
    """제목·기관·예산이 같은 재등록 건을 **가장 최근 게시된 것** 하나로 묶는다.

    시연용 고정 공고는 묶지 않는다 — 큐시트가 가리키는 줄이 사라지면 안 된다(ISSUE-056).
    """
    groups: dict[tuple[str, str, int], list[ProcurementNotice]] = {}
    kept: list[ProcurementNotice] = []
    for notice in notices:
        if notice.budget is None or g2b_mapper.base_notice_no(notice.notice_no) in PINNED_NOTICE_NOS:
            kept.append(notice)
            continue
        groups.setdefault(_repost_key(notice), []).append(notice)

    extra = dict(superseded)
    for members in groups.values():
        if len(members) == 1:
            kept.append(members[0])
            continue
        newest = max(members, key=lambda n: (n.published_at, n.notice_no))
        kept.append(newest)
        older = [n for n in members if n is not newest]
        extra[newest.id] = [*extra.get(newest.id, []), *older]
    # 원래 순서를 지킨다 — 수집 순서가 뒤에서 정렬 기준으로 쓰인다.
    order = {id(n): i for i, n in enumerate(notices)}
    kept.sort(key=lambda n: order.get(id(n), 0))
    return kept, extra


def collapse_revisions(notices: list[ProcurementNotice]) -> list[ProcurementNotice]:
    """`split_revisions` 의 최신 차수만. 이전 차수를 쓰지 않는 호출자를 위한 이름이다."""
    return split_revisions(notices)[0]


@dataclass(frozen=True)
class Collected:
    """수집 한 번의 결과. 공고와 «어떻게 받았는가»를 함께 들고 다닌다."""

    notices: list[ProcurementNotice]
    #: 밀려난 이전 차수 — {최신 차수 공고 id: [이전 차수…]}
    superseded: dict[str, list[ProcurementNotice]]
    #: 나라장터를 부른 횟수. 화면과 보고서가 묻는다 (0920 §4-A-3).
    calls: int
    #: 화면에 그대로 적는 한국어 한 줄.
    method: str
    #: 받아 온 공고 수 (차수를 묶기 전, 중복 제거 뒤).
    total_fetched: int
    #: 예산이 모자라 다 못 받은 키워드. 비어 있어야 정상이다.
    truncated: tuple[str, ...] = ()
    #: 페이지 조회가 실패한 키워드 · 실패한 호출 수(39차 DAILY-02 · 06).
    failed_keywords: tuple[str, ...] = ()
    failed_calls: int = 0
    #: 자격 제한(면허·참가가능지역)을 한 건이라도 붙였는가 (0922 §4-A-1).
    #: False 면 공고의 `license_limits`·`allowed_regions` 는 전부 「미확인」(None)이다.
    qualification_covered: bool = False
    #: 자격 정보를 받느라 부른 횟수. `calls` 에는 이미 합쳐져 있다.
    qualification_calls: int = 0
    #: 자격 정보를 못 받은 사유. 없으면 None.
    qualification_note: str | None = None
    #: 이번에 **새로 받은** 날 수. 이미 저장된 날은 다시 부르지 않는다.
    qualification_days_fetched: int = 0
    #: 후보 공고의 게시일 중 자격 정보를 가진 날 수 / 전체 날 수.
    qualification_days_known: int = 0
    qualification_days_total: int = 0


async def collect_candidates(
    *,
    days: int = DEFAULT_DAYS,
    keywords: Sequence[str] = opportunity_filter.COLLECT_KEYWORDS,
    full_window: bool = False,
    max_items: int = DEFAULT_MAX_ITEMS,
    with_qualifications: bool = True,
    qualification_max_calls: int = g2b_client.MAX_QUALIFICATION_CALLS,
    qualification_live: bool | None = None,
    max_calls: int = g2b_client.MAX_COLLECT_CALLS,
) -> Collected:
    """나라장터에서 후보 공고를 받아 온다. **수집의 단일 출입구다** (0920.md §4-A-1).

    기본은 **공고명 키워드 조회**다(`bidNtceNm` + `bidClseExcpYn=Y`). 옛 경로인 창 순회는
    `full_window=True` 로만 돈다 — 그것은 「마지막 페이지가 최신」이라는 틀린 가정 위에
    서 있어서, AI 교육·컨설팅 공고(전부 일반용역)를 구조적으로 못 봤다
    (docs/reports/2026-09-20_qa_recheck5.md §1-3).

    여기까지가 「받아 오기」다. 후보 판정(`filter_candidates`)은 부르는 쪽이 한다 —
    캐시는 항상 전체 후보를 담고 좁히기는 읽는 쪽에서 하기 때문이다.

    `qualification_max_calls` · `qualification_live` · `max_calls` 는 바로 찾기(2.0.7)용이다 — 자격 하루치 최대 6회 · 목록 호출 상한 ·
    좁은 문(`KEYWORD_SEARCH_LIVE`)을 부르는 쪽이 이미 확인했다(나라장터 실호출 문은 꺼진 채).
    """
    if full_window:
        items = await g2b_client.fetch_bid_notices(days=days, max_items=max_items)
        calls, method, truncated = 0, f"조회 창 순회 · 최근 {days}일", ()
        failed_keywords, failed_calls = (), 0
    else:
        outcome = await g2b_client.collect_notices(keywords=list(keywords), days=days, max_calls=max_calls)
        items = outcome.items[:max_items]
        if len(outcome.items) > max_items:  # 조용히 자르지 않는다 — 앞(낱말 순서 · 첫 쪽)부터 상한까지만 남긴 사실을 남긴다
            logger.warning("나라장터 공고 %d건 중 저장 상한 %d건만 남깁니다", len(outcome.items), max_items)
        calls, method, truncated = outcome.calls, outcome.method, outcome.truncated
        failed_keywords, failed_calls = outcome.failed, outcome.failures

    # 자격 제한(면허·참가가능지역)을 **하루 창**으로 받아 공고번호+차수로 붙인다 (0922 §4-A-1).
    # 실패해도 목록 수집을 죽이지 않는다 — 대신 「미확인」으로 남기고 사유를 들고 나간다.
    coverage = None
    qual_calls = 0
    qual_note: str | None = None
    fetched_days = 0
    wanted_days: list[date] = []
    if with_qualifications and not full_window:
        wanted_days = _publish_days(items)
        qual_calls, fetched_days, qual_note = await _ensure_qualification_days(
            wanted_days, max_calls=qualification_max_calls, live=qualification_live
        )
        calls += qual_calls
        coverage = qualification_store.coverage_for(wanted_days)

    notices = g2b_mapper.map_notices(items, qualifications=coverage)
    latest, superseded = split_revisions(notices)
    covered_count = sum(1 for n in latest if n.raw_data.get("license_limits") is not None)
    if coverage is not None and covered_count:
        # **세는 값을 문구에 넣지 않는다.** `collected_by`/`_note` 는 캐시 비교에서
        # 「달라졌는가」를 가리는 키라(volatile 목록에 없다), 건수를 끼워 넣으면 목록을
        # 읽을 때마다 한 건 차이로 1.5MB 파일이 다시 쓰인다 — ISSUE-038 과 같은 함정이다.
        method = f"{method} · 자격 제한 포함"
    return Collected(
        notices=latest,
        superseded=superseded,
        calls=calls,
        method=method,
        # 「받아 온 것」은 차수를 묶기 «전» 수다. 화면의 「수집 n건」이 이 값이다.
        total_fetched=len(notices),
        truncated=truncated,
        failed_keywords=failed_keywords,
        failed_calls=failed_calls,
        qualification_covered=bool(covered_count),
        qualification_calls=qual_calls,
        qualification_note=qual_note,
        qualification_days_fetched=fetched_days,
        qualification_days_known=len(coverage.records) if coverage else 0,
        qualification_days_total=len(wanted_days),
    )


def _publish_days(items: list[dict[str, Any]]) -> list[date]:
    """후보 item 들의 **게시일(KST)** 집합. 자격 정보를 받을 날들이다 (0922 §4-A-3).

    창 전체(30일)를 통째로 받지 않는다 — 후보가 한 건도 없는 날은 받을 이유가 없고,
    호출 예산은 그만큼 줄어든다.
    """
    days: set[date] = set()
    for item in items:
        moment = g2b_mapper.parse_datetime(
            str(item.get("bidNtceDt") or item.get("rgstDt") or "").strip()
        )
        day = qualification_store.published_day(moment)
        if day is not None:
            days.add(day)
    return sorted(days)


async def _ensure_qualification_days(
    days: Sequence[date], *, max_calls: int = g2b_client.MAX_QUALIFICATION_CALLS, live: bool | None = None
) -> tuple[int, int, str | None]:
    """저장소에 없는 날만 받아 저장한다. `(호출 수, 받은 날 수, 사유)`.

    **이미 받은 날은 다시 부르지 않는다.** 그래서 백필은 한 번이고, 그 뒤로는 새로 생긴
    날만 받아 매일 4~6회로 끝난다(0922 §2).
    """
    if not days or not (live_fetch_enabled() if live is None else live):  # live — 부르는 쪽이 이미 연 문(바로 찾기)
        return 0, 0, None
    # 그날 안에 받은 반쪽 하루치도 다시 받는다(33차 · 절차서 A — 파일이 있다고 「받은 날」이 아니다)
    settled = qualification_store.settled_days(days)
    missing = [day for day in days if day not in settled]
    if not missing:
        return 0, 0, None

    calls = 0
    fetched = 0
    problems: list[str] = []
    skipped: list[date] = []
    # 한 날이 두 오퍼레이션 × 쪽 상한까지 쓸 수 있다 — 부르기 전에 「남은 몫으로 한 날을 다 받을 수 있나」를 본다.
    # 「이미 다 썼나」만 보면 바로 찾기의 상한 6이 8~11회까지 갔다(2.0.7 검토 back-5). 첫 날은 지금처럼 늘 받는다.
    per_day = 2 * g2b_client.QUALIFICATION_MAX_PAGES_PER_DAY
    for day in missing:
        if calls >= max_calls or (calls > 0 and calls + per_day > max_calls):
            skipped.append(day)
            continue
        outcome = await g2b_client.fetch_qualifications_for_day(day)
        calls += outcome.calls
        if not outcome.complete:
            # 덜 받은 날은 **저장하지 않는다.** 저장하면 다음부터 「받은 날」이 되어
            # 빠진 공고가 영영 「제한 없음」으로 굳는다.
            problems.append(outcome.note or f"{day} 자격 정보를 다 받지 못했습니다")
            continue
        licenses, regions = qualification_store.normalize(outcome.licenses, outcome.regions)
        qualification_store.save_day(
            day,
            licenses=licenses,
            regions=regions,
            fetched_at=_now(),
            license_rows=outcome.license_rows,
            region_rows=outcome.region_rows,
        )
        fetched += 1
    if skipped:
        problems.append(f"호출 예산({max_calls}회)이 닿지 않아 {len(skipped)}일은 다음에 받습니다")
    return calls, fetched, " · ".join(problems) or None


def save_pinned(views: list[NoticeView]) -> None:
    """데모 고정 공고를 별도 파일에 저장한다 (일반 캐시 갱신에 지워지지 않게)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "_note": "본선 데모 고정 공고. 나라장터 목록 조회에서 밀려 빠져도 목록에 붙인다.",
        "notices": [
            {"notice": v.notice.model_dump(mode="json"), "candidate": v.match.to_dict()}
            for v in views
        ],
    }
    storage.write_json_atomic(PINNED_FILE, mask_contact_fields(payload))


def load_pinned() -> list[NoticeView]:
    """고정 공고 저장소를 읽는다. 없거나 깨졌으면 빈 목록."""
    if not PINNED_FILE.exists():
        return []
    try:
        payload = json.loads(PINNED_FILE.read_text(encoding="utf-8"))
        return [
            NoticeView(
                notice=(n := _with_schedule(g2b_mapper.normalized(ProcurementNotice.model_validate(entry["notice"])))),
                match=classify(n),
            )
            for entry in payload.get("notices", [])
        ]
    except (ValueError, KeyError, TypeError):
        logger.warning("고정 공고 파일을 읽지 못했습니다: %s", PINNED_FILE)
        return []


def _merge_pinned(views: list[NoticeView]) -> list[NoticeView]:
    """고정 공고에 표를 달고, 빠진 것은 저장소에서 되살려 붙인다.

    `pinned` 는 **「고정 목록(`PINNED_NOTICE_NOS`, 시연용 4건)에 있는가」**다
    (ISSUE-134 · prompt_07 §4-C). 예전에는 「저장소에서 되살렸는가」였다.

    그 차이가 시연에서 드러났다. 선택기의 **「시연용 (마감)」 그룹**은 `pinned` 가
    참인 공고만 묶는데, 네 건이 캐시에 이미 들어 있으면 되살릴 일이 없어 표가 안 붙고
    그룹이 그려지지 않았다. 체크리스트 3절과 `demo_preflight` 안내가 그 그룹을 가리키니,
    시연 당일 담당자가 그 문장대로 찾으면 없다. 「어디서 왔는가」가 아니라 「무엇인가」로
    정하면 그룹이 캐시 상태와 무관하게 늘 그려진다.

    저장소에도 없으면 그냥 둔다 — 없는 공고를 만들어내지 않는다.
    """
    if not PINNED_NOTICE_NOS:
        return views
    marked = [
        v if v.pinned or _pin_key(v) not in PINNED_NOTICE_NOS else replace(v, pinned=True)
        for v in views
    ]
    missing = {no for no in PINNED_NOTICE_NOS if no not in {_pin_key(v) for v in marked}}
    if not missing:
        return marked
    restored = [
        replace(v, pinned=True) for v in load_pinned() if _pin_key(v) in missing
    ]
    if restored:
        logger.info("고정 공고 %d건을 저장소에서 되살렸습니다", len(restored))
    return marked + restored


def cached_only(*, include_low: bool = False) -> ProcurementResult | None:
    """저장된 목록만 읽는다. **네트워크를 절대 부르지 않고 TTL 도 보지 않는다.**

    「이미 받아 둔 것으로만 센다」가 계약인 호출자(집계·요약)를 위한 것이다.
    `list_ai_candidates()` 는 TTL 이 지나면 실호출로 넘어가고 그 결과로 Git 이 추적하는
    캐시 파일을 덮어쓴다 — 집계 한 번이 시연 자료를 바꾸는 일이 실제로 일어났다
    (이 함수를 만든 이유다).

    `include_low` 의 기본값은 `list_ai_candidates()` 와 **같다**. 캐시에는 업무 키워드만
    맞는 공고까지 들어 있어서(읽을 때 걸러 쓴다) 여기서 걸러 주지 않으면 집계가 목록 화면의
    몇 배를 센다. 실제로 캐시 108건 · 기본 목록 8건이라 「새 공고 78건」을 눌러 들어가면
    8건짜리 목록이 나왔다.

    캐시가 아예 없으면 None. 호출자는 「아직 받아온 적이 없다」로 표시한다.
    """
    cached = load_cache()
    if cached is None:
        return None
    return _narrow(replace(cached, notices=_merge_pinned(cached.notices)), include_low)


def _frozen_result(days: int) -> ProcurementResult:
    """시연 고정 모드에서 돌려줄 목록. 저장된 캐시만 읽고 네트워크를 건드리지 않는다.

    조회 기간(days)이 캐시와 달라도 그대로 쓴다. 고정 모드에는 «다시 받아 올» 방법이
    없으므로, 기간이 다르다고 빈 목록을 주면 화면이 통째로 비어 시연이 멈춘다.
    무엇을 보고 있는지는 응답의 `source: "cached"` · `frozen: true` 가 말한다.
    """
    stamp = _cache_stamp()
    hit = _MEMO.get(days)
    if hit is not None and _FROZEN_STAMPS.get(days) == stamp:
        return hit
    cached = load_cache()
    if cached is None:
        raise NoNoticeDataError(
            "새 공고 받기가 꺼져 있는데 저장된 공고 목록이 없습니다. "  # 설정 이름은 화면에 적지 않는다(27차 §3-H)
            "고정을 풀고 한 번 받아 두거나 캐시 파일을 복구하세요."
        )
    result = replace(cached, notices=_merge_pinned(cached.notices))
    _MEMO[days] = result
    _FROZEN_STAMPS[days] = stamp
    return result


#: 고정 모드 메모를 만든 때의 저장본 (경로 · 파일 시각) — 다르면 다시 읽는다(33차 · 절차서 C).
#: 예전에는 받은 뒤 서버를 다시 띄우기 전까지 옛 목록을 보여 「오늘 달라진 것」 · 검토 대기열과 숫자가 갈렸다.
_FROZEN_STAMPS: dict[int, tuple[Any, ...]] = {}


def _cache_stamp() -> tuple[Any, ...]:
    """저장본 (경로 · 파일 시각) + 추가 낱말 파일 — 낱말만 더하거나 지워도 분류(사유 · 접힘)가 다시 계산된다(2.0.7)."""
    path = cache_read_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return str(path), mtime, collect_keywords_service.file_stamp()


async def list_ai_candidates(
    *,
    days: int = DEFAULT_DAYS,
    max_items: int = DEFAULT_MAX_ITEMS,
    include_low: bool = False,
    refresh: bool = False,
    ttl: int = CACHE_TTL_SECONDS,
    full_window: bool = False,
) -> ProcurementResult:
    """AI·AI교육 관련 공고 후보를 반환한다.

    refresh=False(기본)이면 TTL 안의 캐시를 먼저 쓴다 — 첫 화면이 빨라야 한다.
    refresh=True면 나라장터를 다시 부른다 ('분석 실행' 버튼).
    실호출 실패 시에는 신선도와 무관하게 캐시로 대체한다.

    **시연 고정 모드**(`G2B_LIVE_FETCH=0`)에서는 위 두 줄이 모두 적용되지 않는다.
    TTL 도 refresh 도 보지 않고 저장된 캐시만 돌려준다.
    """
    if not live_fetch_enabled():
        return _narrow(_frozen_result(days), include_low)
    # 같은 기간을 동시에 부르면 받기는 한 번 — 뒤 요청은 잠금 안에서 앞 요청이 채운 메모를 읽는다(2.9.1 검토: 입찰 분석 첫 보기에서
    # 역량 판정 · 첨부 목록 요청이 같은 순간 나가 나라장터 받기가 두 번 돌았다). 선례 `recollect_service._lock`.
    # ponytail: 프로세스 하나 안에서만 — 워커가 여럿이면 파일 잠금
    async with _collect_lock(days):
        return await _live_candidates(days=days, max_items=max_items, include_low=include_low, refresh=refresh, ttl=ttl,
                                      full_window=full_window)


_COLLECT_LOCKS: dict[int, asyncio.Lock] = {}


def _collect_lock(days: int) -> asyncio.Lock:
    if days not in _COLLECT_LOCKS:
        _COLLECT_LOCKS[days] = asyncio.Lock()
    return _COLLECT_LOCKS[days]


async def _live_candidates(*, days: int, max_items: int, include_low: bool, refresh: bool, ttl: int, full_window: bool) -> ProcurementResult:
    """`list_ai_candidates` 의 실호출 몸통 — 메모 · TTL 캐시 · 실패 기억을 본 뒤 받는다(잠금 안에서 부른다)."""
    if not refresh:
        hit = _MEMO.get(days)
        if hit is not None and _age_seconds(hit.fetched_at) <= ttl:
            return _narrow(hit, include_low)
        fresh_cache = cached_if_fresh(ttl=ttl, days=days)
        if fresh_cache is not None:
            # 캐시에 고정 공고가 없을 수 있다 (예전 캐시). 읽는 쪽에서도 붙인다.
            fresh_cache = replace(fresh_cache, notices=_merge_pinned(fresh_cache.notices))
            _MEMO[days] = fresh_cache
            return _narrow(fresh_cache, include_low)
        failed = _FAILED.get(days)
        if failed is not None and _age_seconds(failed[0]) <= FAILED_RETRY_SECONDS and failed[1] == _cache_stamp():
            return _narrow(failed[2], include_low)

    fetched_at = _now()
    try:
        # 2.0.7 — 기본 낱말 + 추가 낱말(이 서버 전체에 하나)
        collected = await collect_candidates(
            days=days, max_items=max_items, full_window=full_window, keywords=collect_keywords_service.all_keywords()
        )
    except g2b_client.G2BClientError as exc:
        cached = load_cache()
        if cached is None:
            raise NoNoticeDataError(str(exc)) from exc
        # `days` 를 넘기지 않던 결함을 함께 고친다 — 폴백 결과만 days 가 None 이라
        # 다음 조회에서 캐시 재사용 조건(`cached.days == days`)이 늘 어긋났다.
        # 39차 DAILY-06 — 호출 수는 **이번 실행** 것을 싣는다(지난 저장본의 호출 수를 적어 실패 21회가 가려졌다).
        fallback = replace(cached, notices=_merge_pinned(cached.notices), error=str(exc), failed_calls=getattr(exc, "failures", 0))
        if isinstance(getattr(exc, "calls", None), int):
            fallback = replace(fallback, collect_calls=exc.calls)
        _FAILED[days] = (fetched_at, _cache_stamp(), fallback)
        return _narrow(fallback, include_low)

    # 차수 묶기는 수집기 안에서 이미 끝났다 — 필터·캐시보다 먼저여야 모든 화면이 같은 개수를 본다.
    # 캐시·메모는 항상 전체 후보(low 포함)를 담는다. 좁히기는 읽는 쪽에서 한다.
    views_all = [
        NoticeView(notice=n, match=m)
        for n, m in filter_candidates(collected.notices, include_low=True)
    ]
    dropped_none = len(collected.notices) - len(views_all)
    previous = load_cache()
    # 38차 §3-A-4 — 게시 30일이 지나 조회 창 밖으로 밀린 **열린** 공고를 저장본에서 이어 붙인다(1726242 · 9/11 게시 · 10/22 마감).
    views_all = carry_open_notices(views_all, previous, now=fetched_at, days=days)
    # 39차 DAILY-02 — 낱말 페이지가 실패했으면 그 낱말 몫을 지난 저장본에서 잇는다(짧아진 목록으로 덮어쓰지 않는다).
    views_all, patched = carry_failed_keywords(views_all, previous, failed=collected.failed_keywords, now=fetched_at)
    partial = (
        f"일부 실패 — 낱말 {' · '.join(f'「{k}」' for k in collected.failed_keywords)} 조회 실패 {collected.failed_calls}회 · "
        f"그 낱말 공고 {patched}건은 지난 저장본으로 채움"
        if collected.failed_keywords else None
    )
    views_all = _merge_pinned(views_all)
    # 캐시에도 순위 순으로 담는다. 캐시만으로 화면을 그릴 때 순서가 달라지지 않게 한다.
    views_all = rank_notices(views_all)
    # 저장을 **먼저** 하고 그 사유를 결과에 싣는다 (ISSUE-121). 막았으면 받아 온 목록은
    # 그대로 보여 주되 「옛 캐시를 지켰다」를 사유로 말한다 — 조용히 넘어가면 13차와 같다.
    # (`ProcurementResult` 는 frozen 이라 만든 뒤에는 고칠 수 없다.)
    shrink = save_cache(
        views_all,
        collected.total_fetched,
        fetched_at,
        days=days,
        collected_by=collected.method,
        collect_calls=collected.calls,
    )
    result = ProcurementResult(
        source="g2b",
        notices=views_all,
        fetched_at=fetched_at,
        total_fetched=collected.total_fetched,
        days=days,
        collected_by=collected.method,
        collect_calls=collected.calls,
        error=shrink,
        qualification_days_fetched=collected.qualification_days_fetched,
        qualification_calls=collected.qualification_calls,
        qualification_note=collected.qualification_note,
        dropped_none=dropped_none,
        failed_calls=collected.failed_calls,
        partial_failure=partial,
    )
    # 밀려난 이전 차수를 변경 기록으로 남긴다 — 「무엇이 바뀌어 재공고가 났는가」.
    _record_superseded(collected.superseded, fetched_at)
    _MEMO[days] = result
    _FAILED.clear()
    return _narrow(result, include_low)


#: 바로 찾기(2.0.7)의 자격 하루치 호출 상한 — 대표 결정 ①(낱말당 최대 3쪽 · 자격 최대 6회). 다 못 받은 날은 아침 받기가 채운다.
KEYWORD_SEARCH_QUALIFICATION_CALLS = 6
#: 바로 찾기의 목록 호출 = 7일 창마다 첫 쪽 + 이만큼 더(2.8.1 — 조달청 조회 기간 상한 7일 때문에 30일은 창 다섯이라 결정 ①의 「최대 3쪽」을
#: 지킬 수 없다 · 그에 가장 가까운 상한: 30일이면 최대 7회 · 하루 10번이면 70회). 넘치는 몫은 아침 받기가 채운다.
KEYWORD_SEARCH_EXTRA_PAGES = 2


class NotSavedError(RuntimeError):
    """받았지만 저장본에 쓰지 않았다(줄어듦 차단 등) — 사유를 그대로 보인다."""


async def search_one_keyword(word: str) -> dict[str, Any]:
    """추가 낱말 **하나만** 나라장터 공고명 검색으로 받아 지금 저장본에 **합친다** (2.0.7 · 대표 결정 ①). 화면 `KeywordSearchResult`.

    - 빼지 않고 더하기만 한다 — 같은 공고 같은 차수는 저장된 것을 둔다(아침 받기의 자격 정보가 더 넓다) · 줄어듦 차단에 걸리지 않는다.
    - 목록은 7일 창마다 첫 쪽 + 2쪽(`KEYWORD_SEARCH_EXTRA_PAGES` · 30일이면 최대 7회 · 2.8.1 — 예전 「낱말당 최대 3쪽」) · 자격 하루치 최대 6회.
    - 일부 창을 받지 못했으면 `failed_calls` 로 알린다(받은 것은 합친다 — 못 받은 기간은 아침 받기가 채운다).
    - 저장본의 받은 시각 · 수집 방식은 그대로 둔다 — 낱말 하나 받은 것을 「목록 전체를 방금 받음」으로 적지 않는다.
    - 문 · 하루 횟수 · 잠금은 부르는 쪽(`recollect_service.search_keyword`)이 본다.
    """
    previous = load_cache(with_schedule=False)
    days = previous.days if previous is not None and previous.days else DEFAULT_DAYS
    now = _now()
    collected: Collected | None = None
    try:
        collected = await collect_candidates(
            days=days,
            keywords=[word],
            qualification_max_calls=KEYWORD_SEARCH_QUALIFICATION_CALLS,
            qualification_live=True,
            max_calls=len(g2b_client.inquiry_windows(now - timedelta(days=days), now)) + KEYWORD_SEARCH_EXTRA_PAGES,
        )
        calls = collected.calls
    except g2b_client.G2BCollectError as exc:
        if exc.failures:
            raise
        calls = exc.calls  # 실패 없이 0건 — 그 낱말로 마감 전 공고가 없다(실패가 아니다)
    fresh = [NoticeView(notice=n, match=m) for n, m in filter_candidates(collected.notices if collected else [], include_low=True)]
    stored = {g2b_mapper.base_notice_no(v.notice.notice_no): v.notice.id for v in (previous.notices if previous else [])}
    # 처음 보는 사업이거나 **더 높은 차수**일 때만 들인다 — 「다르면 바꿈」이라 저장본의 정정 차수(-001)를 옛 차수(-000)로 덮었다(2.0.7 검토 back-3).
    # stored 값은 id(「g2b-…-001」)라 notice_order 가 끝 조각을 그대로 읽는다.
    added = [
        v
        for v in fresh
        if (held := stored.get(g2b_mapper.base_notice_no(v.notice.notice_no))) is None
        or g2b_mapper.notice_order(v.notice.notice_no) > g2b_mapper.notice_order(held)
    ]
    new_count = sum(1 for v in added if g2b_mapper.base_notice_no(v.notice.notice_no) not in stored)
    if added:
        replaced = {g2b_mapper.base_notice_no(v.notice.notice_no) for v in added}
        kept = [v for v in (previous.notices if previous else []) if g2b_mapper.base_notice_no(v.notice.notice_no) not in replaced]
        shrink = save_cache(
            rank_notices(_merge_pinned([*kept, *added])),
            (previous.total_fetched if previous else 0) + new_count,
            previous.fetched_at if previous else now,
            days=days,
            collected_by=previous.collected_by if previous else (collected.method if collected else None),
            collect_calls=previous.collect_calls if previous else calls,
        )
        if shrink:
            raise NotSavedError(shrink)
        if collected is not None:
            _record_superseded(collected.superseded, now)
        clear_memo()
    return {
        "word": word,
        "found": len(fresh),
        "new_notices": new_count,
        "candidates": sum(1 for v in fresh if v.match.is_candidate),
        "low": sum(1 for v in fresh if v.match.tier == "low"),
        "truncated": bool(collected and collected.truncated),
        # 받지 못한 기간(창) 호출 수 — 0 이 아니면 화면이 「일부 기간을 받지 못했습니다」를 붙인다(2.8.1 검토 · 성공처럼 보였다)
        "failed_calls": collected.failed_calls if collected else 0,
        "calls": calls,
        "searched_at": now.isoformat(),
    }


def _real_deadline(notice: ProcurementNotice) -> datetime | None:
    """실제 마감 — 입찰 마감과 참가자격 등록 마감 중 이른 쪽(D-day 와 같은 규칙)."""
    qualification = g2b_mapper.parse_datetime((notice.raw_data or {}).get("qualification_deadline") or "")
    found = [d for d in (notice.deadline_at, qualification) if d is not None]
    return min(found) if found else None


def carry_open_notices(
    views: list[NoticeView], cached: ProcurementResult | None, *, now: datetime, days: int
) -> list[NoticeView]:
    """조회 창(게시 `days` 일) 밖으로 밀린 **마감 전** 공고를 저장본에서 이어 붙인다 (38차 §3-A-4).

    공고명 검색은 게시일 창으로만 받으므로, 9/11 에 올라와 10/22 에 마감하는 공고가 10/12 부터 창 밖으로 밀려
    저장본에서 사라졌다(recheck30 · 1726242). 이어 붙이는 것은 셋을 모두 만족하는 것뿐이다.

    - 게시일이 창 시작보다 앞이다(창 안인데 이번에 안 온 공고는 취소 · 삭제일 수 있어 붙이지 않는다).
    - 실제 마감이 아직 오지 않았다(마감일 모르는 공고는 붙이지 않는다 — 언제까지 남길지 모른다).
    - 같은 공고번호(차수 무시)가 이번 수집에 없다(새 차수가 왔으면 그것이 이긴다).
    """
    if cached is None:
        return views
    window_start = now - timedelta(days=days)
    present = {g2b_mapper.base_notice_no(v.notice.notice_no) for v in views}
    carried: list[NoticeView] = []
    for view in cached.notices:
        notice = view.notice
        base = g2b_mapper.base_notice_no(notice.notice_no)
        if base in present or view.pinned and base in PINNED_NOTICE_NOS:
            continue
        deadline = _real_deadline(notice)
        published = notice.published_at
        if deadline is None or deadline <= now or published is None or published >= window_start:
            continue
        carried.append(NoticeView(notice=notice, match=classify(notice)))
        present.add(base)
    if carried:
        logger.info("조회 창 밖으로 밀린 열린 공고 %d건을 저장본에서 이어 붙였습니다", len(carried))
    return [*views, *carried]


def carry_failed_keywords(
    views: list[NoticeView], cached: ProcurementResult | None, *, failed: Sequence[str], now: datetime
) -> tuple[list[NoticeView], int]:
    """실패한 낱말 몫을 지난 저장본에서 잇는다(39차 DAILY-02). `(목록, 이어 붙인 수)`.

    한 낱말 페이지가 읽기 시간 초과로 빠지면 그 낱말로만 걸리는 공고(10-16 저장본: 「교육」만 125건)가 짧아진 목록으로
    덮어써져 사라졌다. 잇는 것은 공고명이 실패한 낱말에 걸리고(수집 낱말 · 나라장터 공고명 검색과 같은 부분 일치) · 마감 전이고 ·
    같은 공고번호(차수 무시)가 이번 수집에 없는 것뿐이다.
    """
    if not failed or cached is None:
        return views, 0
    from app.services import prespec_service

    lost = set(failed)
    present = {g2b_mapper.base_notice_no(v.notice.notice_no) for v in views}
    carried: list[NoticeView] = []
    for view in cached.notices:
        notice = view.notice
        base = g2b_mapper.base_notice_no(notice.notice_no)
        if base in present or view.pinned:
            continue
        deadline = _real_deadline(notice)
        if deadline is not None and deadline <= now:
            continue
        if not lost.intersection(prespec_service.wanted(notice.title)):
            continue
        carried.append(NoticeView(notice=notice, match=classify(notice)))
        present.add(base)
    if carried:
        logger.warning("실패한 낱말 %s 몫 %d건을 지난 저장본에서 이어 붙였습니다", ", ".join(failed), len(carried))
    return [*views, *carried], len(carried)


def _record_superseded(
    superseded: dict[str, list[ProcurementNotice]], observed_at: datetime
) -> None:
    """밀려난 이전 차수를 **최신 차수의 변경 기록**으로 남긴다 (0920 §4-A-1).

    재공고가 나면 담당자가 가장 먼저 묻는 것은 「무엇이 바뀌었나」다. 그런데 공고 이력은
    공고 id(차수 포함) 단위로 파일이 나뉘어 있어, `-000` 과 `-001` 을 따로 적으면 둘 사이의
    차이는 어디에도 남지 않는다.

    그래서 **최신 차수의 이력 파일이 비어 있을 때만** 이전 차수를 오래된 순서로 먼저 적고
    최신을 적는다. 그러면 그 파일 안에서 「-000 → -001 에서 마감일이 바뀌었다」가 변경
    기록으로 잡힌다.

    이미 이력이 있는 공고에는 하지 않는다 — 옛 차수를 뒤늦게 끼워 넣으면 「최신 → 옛것 →
    최신」으로 오갔다는 **없던 변경**이 만들어진다.

    파일 이름 규칙은 건드리지 않았다. 차수 계열을 한 파일로 묶으려면 `history_path` 를
    바꿔야 하는데, 그러면 이미 쌓인 이력과 이어지지 않는다.
    """
    if not superseded:
        return
    try:
        from app.services import notice_version_service
    except Exception as exc:  # noqa: BLE001 — 부가 기능이 본 기능을 막지 않는다
        logger.warning("공고 차수 기록 건너뜀: %s", exc)
        return
    for latest_id, older in superseded.items():
        try:
            if notice_version_service.load_history(latest_id).versions:
                continue
            for notice in older:
                notice_version_service.record(
                    notice.model_copy(update={"id": latest_id}), observed_at=observed_at
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("공고 차수 기록 실패 (%s): %s", latest_id, exc)


async def get_notice(notice_id: str, *, days: int = DEFAULT_DAYS) -> NoticeView | None:
    """단건 조회. 후보 목록(캐시 포함)에서 id로 찾는다."""
    result = await list_ai_candidates(days=days, include_low=True)
    for view in result.notices:
        if view.notice.id == notice_id:
            return view
    return None
