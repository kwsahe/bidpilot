"""회사 기준 검토 우선순위 (company_priority_score).

나라장터 입찰공고와 기업마당 지원사업을 **한 화면에 나란히 놓기 위한 순서**만 계산한다.

이 점수가 아닌 것:
- 낙찰확률·수주확률 (나라장터)
- 선정확률·성공확률 (기업마당)
- AI 예측 확률

이 점수인 것:
- "현재 선택한 회사(organization_id)의 사업영역·자격·수행근거·일정·전략 관점에서 먼저 볼 순서"

원본 점수는 덮어쓰지 않는다. 조달공고는 recommendation(추천등급), 지원사업은 support_fit(지원 적합도)를
그대로 유지하고, 그 위에 공통 축 하나만 얹는다.

원칙 (CLAUDE.md 11·12 + 이번 작업 지시 5항)
- 값이 없는 항목을 0점으로 단정하지 않는다. 미확인은 `score=None`으로 남긴다.
- 계산 가능한 항목의 가중치 합으로만 정규화하고, 대신 `confidence`를 낮춘다.
- 실제 자격 확인 전에는 PASS로 확정하지 않는다 (자격 항목에 상한을 둔다).
- 모든 항목에 근거 문장을 남긴다.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final

from app.core.config import get_settings
from app.core.money import won, won_pair
from app.schemas.business_opportunity import (
    Confidence,
    EligibilityGate,
    PriorityComponent,
    PriorityLabel,
    SupportFit,
    SupportProgram,
)
from app.core import storage
from app.schemas.company import CompanyProfile
from app.schemas.eligibility import EligibilityResult
from app.schemas.procurement import ProcurementNotice
from app.services import audience_filter, g2b_mapper, home_agencies, recommendation, support_kinds, work_kinds

# 이 줄은 recommendation **뒤**에 있어야 한다. 알파벳 순으로 위에 올리면 import 가 깨진다.
#   eligibility_engine → procurement_service → recommendation → eligibility_engine.COMPANY_PROFILE
# 이 고리에서 eligibility_engine 을 먼저 부르면 COMPANY_PROFILE 이 아직 정의되기 전이라
# ImportError 가 난다 (recommendation 을 먼저 부르면 고리가 순서대로 풀린다).
# 이 순서가 지켜지는지는 test_unified_opportunities 의 import 회귀 테스트가 지킨다.
from app.services import eligibility_engine  # isort: skip
from app.services import opportunity_filter
from app.services.opportunity_filter import CandidateMatch

KST = timezone(timedelta(hours=9))

# 배점 합 100 (0922 §4-B).
#
# **마감이 빠졌다.** 예전에는 「일정 여유」 10점이 들어 있었고, 키워드가 맞는 공고끼리는
# 그것만으로 81점과 77점이 갈렸다 — 순서가 곧 마감 순서였다(ISSUE-083). 마감은 적합도가
# 아니라 긴급도이고, 매일 바뀐다. 그래서 두 축을 나눈다:
#
#   적합도(이 점수) = 「우리와 맞는가」. 마감이 바뀌어도 그대로다.
#   긴급도(D-day·「마감 임박순」·「이번 주 할 일」·촉박 배지) = 「언제까지인가」.
#
# 자리는 「규모 적합도」가 대신한다 — 3인 팀이 단독으로 할 수 있는 크기인가.
PRIORITY_WEIGHTS: Final[dict[str, int]] = {
    "domain": 35,  # 회사 사업영역 적합도
    "eligibility": 25,  # 참여·신청자격 적합도
    "evidence": 20,  # 수행근거·보유역량
    "scale": 10,  # 규모 적합도
    "strategic": 10,  # 전략적 가치
}

PRIORITY_LABELS: Final[dict[str, str]] = {
    "domain": "회사 사업영역 적합도",
    "eligibility": "참여·신청자격 적합도",
    "evidence": "수행근거·보유역량",
    "scale": "규모 적합도",
    "strategic": "전략적 가치",
}

# 우선순위 라벨 경계. 테스트로 고정한다.
#
# 「우선 검토」는 **80점 이상이거나 같은 출처 상위 15%** 다 (0922 §4-B-6). 예전 기준(70점)
# 으로는 목록 107건 중 41건이 「우선 검토」였다 — 거의 전부라 이름값을 못 했다.
PRIORITY_HIGH: Final[int] = 80
PRIORITY_MID: Final[int] = 45
#: 「우선 검토」로 부를 상위 비율. 점수가 낮게 깔린 날에도 맨 위 몇 건은 이름을 갖는다.
PRIORITY_TOP_RATIO: Final[float] = 0.15

# 자격을 원문으로 확인하기 전에는 이 값을 넘지 않는다 (PASS로 확정하지 않는다).
ELIGIBILITY_CAP: Final[float] = 0.6
# 목록 단계의 근거 연결은 키워드 일치일 뿐 검증된 수행근거가 아니다. 만점을 주지 않는다.
EVIDENCE_HINT_CAP: Final[float] = 0.6

# 참가자격을 지역으로 제한한다고 공고가 명시한 경우에만 지역 불일치를 감점 사유로 본다.
_REGION_LIMIT_RE = re.compile(r"(지역\s*제한|관내\s*(기업|업체)|소재\s*(기업|업체|하는)|본점\s*소재|주된\s*영업소)")

_TOKEN_SPLIT = re.compile(r"[\s/·,()]+")
_STOPWORDS: Final[frozenset[str]] = frozenset({"활용", "및", "관련", "기반", "지원", "사업", "교육및컨설팅"})


def _now(now: datetime | None) -> datetime:
    return now or storage.utc_now()


def _today(today: date | None) -> date:
    # 「업무 날짜」의 단일 출처. 두 벌이 되면 언젠가 갈린다 (ISSUE-042).
    return today or storage.kst_today()


def profile_tokens(values: list[str] | tuple[str, ...]) -> list[str]:
    """프로필 문자열(사업영역·인증 등)을 검색용 토큰으로 쪼갠다. 2글자 이상만 쓴다."""
    tokens: list[str] = []
    for value in values:
        for piece in _TOKEN_SPLIT.split(value or ""):
            piece = piece.strip()
            if len(piece) >= 2 and piece not in _STOPWORDS and piece not in tokens:
                tokens.append(piece)
    return tokens


#: 회사가 주체가 되기 어려운 갈래의 사업영역 점수 상한.
#: 0 으로 만들지 않는 이유 — 「관련 없음」이 아니라 「우리가 신청 주체가 되기 어렵다」이고,
#: 컨소시엄 참여처럼 다른 길이 있을 수 있어 담당자가 보고 판단할 여지를 남긴다.
NON_MATCHING_KIND_CAP = 0.45
# 회사가 신청자가 될 수 없어 보이는 안내의 사업영역 상한 (ISSUE-005).
# 「우선 검토」(70점) 밖으로 확실히 내보내되 목록에서 지우지는 않는다.
AUDIENCE_CAP: Final[float] = 0.2
# 개발만 있고 교육 수행 문구가 없는 입찰공고의 사업영역 상한 (ISSUE-005).
DEVELOPMENT_ONLY_CAP: Final[float] = 0.45


#: 회사가 «개발을 직접 한다»고 적었는지 가리는 낱말. 사업영역(`business_domains`)에서 찾는다.
_DEVELOPS_TOKENS: Final[tuple[str, ...]] = ("소프트웨어 개발", "SW 개발", "시스템 구축", "개발", "구축")

# --------------------------------------------------------------------------
# 사업영역 등급 (0922 §4-B-1)
#
# 예전에는 키워드가 맞는 공고가 **전부 1.0** 이었다. 그래서 「AI 기반 ○○ 개발」이면
# 3.8억 강원대도, 박람회 대행도, 방송 제작도 같은 점수였고 변별이 마감에만 남았다.
# 이제 네 등급으로 나눈다 — 회사가 적어 둔 **검증 역량**이 맨 위다.
# --------------------------------------------------------------------------

#: 회사가 「해 봤다」고 적은 역량이 공고명·요약에 그대로 있다.
DOMAIN_PROVEN: Final[float] = 1.0
#: **회사의 두 축이 다 걸린다** — 만드는 일인데 그 대상이 교육이다(또는 그 반대).
#:
#: 검수자가 KISTI 「군 장병 맞춤형 AI 교육 서비스 개발」을 1~3순위에 넣은 이유가 이것이다:
#: 「AI 교육 + 서비스 개발 = 회사 두 축이 다 걸린다」(`apply_candidates.md` §2-3).
#: 검증 역량만큼 확실하지는 않아 1.0 은 주지 않는다.
#:
#: **갈래 판정(`work_kinds`)을 건드리지 않는다.** 그쪽은 「무슨 일을 시키는가」를 재고,
#: 「AI 교육 서비스를 **개발**하는 일」의 답은 개발이 맞다(6차 ISSUE-073 이 그렇게 고정했다).
#: 여기서 재는 것은 다른 질문이다 — 「그 일의 **대상**이 우리 사업영역인가」.
DOMAIN_BOTH_TRACKS: Final[float] = 0.85

#: 공고의 **대상**이 교육·훈련 도메인인가. 갈래가 아니라 주제를 본다.
_EDUCATION_SUBJECT_RE: Final[re.Pattern[str]] = re.compile(
    r"교육|훈련|연수|학습|교수|강의|강좌|교안|커리큘럼|튜터|인재\s*양성|인력\s*양성"
    r"|부트캠프|아카데미|LMS|이러닝|에듀|학생|수강|교과|역량\s*강화",
    re.IGNORECASE,
)
#: 우리 갈래(개발형·교육·훈련형)다.
DOMAIN_TRACK: Final[float] = 0.7
#: AI 낱말만 걸렸다. 무슨 일인지는 아직 모른다.
DOMAIN_KEYWORD: Final[float] = 0.45
#: 「그 밖」 — 전시·행사·대행·방송 제작·임차·감리·영향평가·설계. **상한이다.**
DOMAIN_OTHER: Final[float] = 0.2

#: 조달 분류명(`pubPrcrmntClsfcNm`)이 「그 밖」이라고 말하는 값.
_OTHER_CLASS_RE: Final[re.Pattern[str]] = re.compile(
    r"전시|행사|대행|방송|영상|임차|임대|감리|영향평가|설계|인쇄|경비|청소|여행|공사|건축|측량"
)
#: 공고명이 「그 밖」이라고 말하는 값. 분류가 비어 있는 공고를 위한 두 번째 그물이다.
_OTHER_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"박람회|전시회|융합페어|페스티벌|경진대회|공모전|개관식|중계"
    r"|대행\s*용역|대행용역|행사\s*대행|콘텐츠\s*제작|방송\s*제작|프로그램\s*제작"
    r"|시설\s*임차|임차\s*용역|디스플레이\s*임차|해외\s*연수|위탁\s*감리|감리\s*용역|감리용역"
    r"|개인정보\s*영향평가|실시설계|기본\s*설계|설치\s*공사|구축\s*공사"
)


def is_other_work(*, text: str, tracks: list[str], procurement_class: str | None) -> str | None:
    """「그 밖」이면 그 이유를 한 줄로, 아니면 None (0922 §4-B-1).

    셋 중 하나면 「그 밖」이다 — 갈래 판정이 우리 역할이 아니라고 했거나(감리·구매·연구·공사),
    조달 분류명이 그렇게 말하거나, 공고명에 그 낱말이 있다.
    """
    if "other" in tracks:
        return "우리 회사가 일을 맡는 공고가 아님"
    klass = (procurement_class or "").strip()
    if klass and _OTHER_CLASS_RE.search(klass):
        return f"조달 분류 {klass}"
    match = _OTHER_TITLE_RE.search(text)
    if match:
        return f"공고명에 「{match.group(0).strip()}」"
    return None


#: 회사가 상한을 안 적었을 때 **순위에만** 쓰는 권장 상한 (개발 3명 기준, 0922 §2).
#:
#: **판정에는 쓰지 않는다.** 규모로 「불가」를 내려면 회사가 정한 값이 있어야 한다
#: (`eligibility_engine._rule_budget`). 여기는 순서를 정하는 자리라 참고값을 쓰고,
#: 화면 문구에 「권장 상한 2억 기준 · 회사 상한 미입력」이라고 밝힌다.
RECOMMENDED_CEILING_KRW: Final[int] = eligibility_engine.RECOMMENDED_CEILING_KRW


def scale_component(
    budget: int | None, *, ceiling: int | None, joint_allowed: bool | None
) -> PriorityComponent:
    """규모 적합도 — 3인 팀이 단독으로 할 수 있는 크기인가 (0922 §4-B-3).

    구간은 상한의 절반·상한·1.5배다. 상한을 안 적었으면 권장 2억으로 재고 그 사실을 적는다.

    **공동수급(공동이행)이 허용되면 어느 구간에서나 0.2 를 더한다.** 3인 팀에게 규모 위험을
    실제로 낮추는 값이기 때문이다 — 검수자도 KISTI 1.9억을 1~3순위에 넣으면서 그 이유로
    「공동이행 허용 · 3인 단독엔 큰 편 → 공동수급 권장」을 적었다(`apply_candidates.md` §2-3).
    """
    if budget is None:
        return _component("scale", None, "예산·기초금액이 공고에 없어 규모를 재지 못했습니다")
    limit = ceiling or RECOMMENDED_CEILING_KRW
    budget_text, limit_text = won_pair(budget, limit)  # 반올림하면 같아지는 금액은 정확히(35차 G2B-04 · 1758659)
    basis = (
        f"회사가 적은 혼자 맡을 수 있는 최대 사업비 {limit_text} 기준"
        if ceiling
        else f"회사 한도를 안 적어 권장 상한 {limit_text}으로 가정"
    )
    if budget <= limit // 2:
        score, note = 1.0, "혼자 맡을 수 있는 규모"
    elif budget <= limit:
        score, note = 0.7, "한도 안"
    elif budget <= limit + limit // 2:
        score, note = 0.3, "한도를 넘습니다"
    else:
        # 상한의 1.5배를 넘으면 3인 팀이 단독으로 맡을 수 있는 규모가 아니다. **모르는 값이
        # 아니라 «재어 본 값»이라** 0 을 쓴다 — 공동수급이 허용되면 그때 길이 열린다.
        score, note = 0.0, "혼자서는 맡기 어려운 규모입니다"
    reason = f"{budget_text} — {note} ({basis})"
    if joint_allowed:
        score = min(1.0, score + 0.2)
        reason += " · 공동수급 허용으로 나눌 수 있습니다"
    return _component("scale", round(score, 3), reason)


#: 광주 · 전남 기관 판정은 `home_agencies` 한 곳(43차 Q7 · 수요기관 기준 · 대학 · 22개 시군 · 빛가람 기관).
#: 홈그라운드 가산폭.
HOME_REGION_BONUS: Final[float] = 0.2
#: 재공고 가산폭 (0922 §4-B-4). 앞선 회차가 유찰·취소됐다는 뜻이라 경쟁이 적을 수 있다.
REPOST_BONUS: Final[float] = 0.2


def home_ground(agency: str | None, demand: str | None) -> str | None:
    """광주 · 전남 기관 발주인가 — **수요기관 기준**(43차 M6 · Q7 · 조달청 · 지방조달청은 대행). 맞으면 기관 이름을 돌려준다.

    기업마당은 `demand` 자리에 수행기관을 넘긴다 — 소관기관이 다른 곳이어도 수행기관이 광주 · 전남이면 우리 지역 사업이다(38차 PRACTICAL-05)."""
    deciding = home_agencies.deciding_agency(agency, demand)
    if deciding and home_agencies.is_home(deciding):
        return deciding
    if demand and agency and not home_agencies.PROCUREMENT_OFFICE_RE.search(agency) and home_agencies.is_home(agency):
        return agency.strip()  # 기업마당 — 소관기관이 광주 · 전남이면 그대로
    return None


def _company_develops(profile: CompanyProfile) -> bool:
    """회사 사업영역에 개발이 적혀 있는가 (0921 §4-C-2).

    적혀 있으면 개발형 공고에 점수 상한을 두지 않는다. **회사가 적은 값으로 판단한다** —
    시스템이 「이 회사는 교육 회사」라고 단정하지 않는다.
    """
    text = " ".join(profile.business_domains or ())
    return any(token in text for token in _DEVELOPS_TOKENS)


# --------------------------------------------------------------------------
# 「왜 맞나」·「주의」 한 줄 (0921.md §4-C-3)
#
# 목록 카드에 이유가 `reasons[]`·`checks[]` 로 여러 줄 붙어 있는데, 담당자가 100건을
# 훑을 때 읽는 것은 **첫 줄 하나**다. 검수자의 기준 답안도 공고마다 「왜 3인에 맞나」와
# 「주의」를 한 줄씩 적었다. 같은 모양으로 만든다.
#
# **LLM 을 쓰지 않는다.** 회사가 적어 둔 검증 역량(`skills`, level=proven)과 공고의
# 갈래·분류·예산·마감만 보고 규칙으로 잇는다 — 없는 사실을 지어내지 않는다.
# --------------------------------------------------------------------------


def proven_skill_hits(capacity: Any, text: str) -> list[str]:
    """공고 글에서 회사의 **검증된** 역량 이름을 찾는다. 별칭도 함께 본다."""
    if capacity is None:
        return []
    lowered = text.lower()
    found: list[str] = []
    for entry in getattr(capacity, "skills", ()) or ():
        if getattr(entry, "level", None) != "proven":
            continue
        names = [entry.name, *(entry.aliases or ())]
        if any(n and n.lower() in lowered for n in names) and entry.name not in found:
            found.append(entry.name)
    return found


def fit_line(
    *,
    text: str,
    tracks: list[str],
    procurement_class: str | None,
    budget: int | None,
    days_left: int | None,
    capacity: Any,
) -> str | None:
    """「왜 맞나」 한 줄. 근거가 하나도 없으면 None — 빈 말을 만들지 않는다."""
    parts: list[str] = []
    hits = proven_skill_hits(capacity, text)
    if hits:
        parts.append(f"해 본 일: {', '.join(hits[:3])}")
    track_words = {"education": "교육·훈련형", "development": "개발형"}
    named = [track_words[t] for t in tracks if t in track_words]
    if named:
        parts.append(" · ".join(named))
    if procurement_class:
        parts.append(procurement_class)
    if budget:
        # 43차 BRIEF-16 · NUM-11 — 상한 근처는 반올림하면 상한과 같아진다(「2억원 · 규모 큼(단독 상한 2억)」) — 그때는 정확한 금액
        ceiling = getattr(capacity, "budget_ceiling_krw", None) or RECOMMENDED_CEILING_KRW
        parts.append(f"예산 {won_pair(budget, ceiling)[0]}")
    if days_left is not None and days_left >= 0:
        # 소수가 오면(옛 `days_until`) 화면에 「14.48297561715278일」이 찍히면 안 된다 — 40차부터는 KST 달력 날짜 차(정수)
        parts.append("오늘 마감" if int(days_left) == 0 else f"마감까지 {int(days_left)}일")
    return " · ".join(parts) or None


def caution_line(
    *,
    budget: int | None,
    ceiling: int | None,
    days_left: int | None,
    lead_days: int,
    joint_allowed: bool | None,
    out_of_scope: bool,
) -> str | None:
    """「주의」 한 줄. 볼 것이 없으면 None."""
    parts: list[str] = []
    if out_of_scope:
        parts.append("회사 사업영역 밖으로 보임 — 과업 범위 확인")
    if budget and ceiling and budget > ceiling:
        # 공동수급 판단은 판정과 같은 `eligibility_engine.joint_allowed` 결과다(33차 §3-B-2). 모르면 모른다고.
        if joint_allowed is None:
            parts.append("규모 큼 — 함께 입찰 가능한지 공고문 확인")
        else:
            parts.append("규모 큼 — " + ("다른 회사와 함께 입찰 권장" if joint_allowed else "함께 입찰 안 됨 · 혼자 맡을지 정하기"))
    elif budget and ceiling is None and budget >= 150_000_000:
        parts.append("규모 큼 — 혼자 맡을 수 있는 금액을 회사자료에 적어 주세요")
    if days_left is not None and 0 <= days_left < lead_days:
        parts.append("오늘 마감 — 준비 시간 부족" if int(days_left) == 0 else f"마감 {int(days_left)}일 남음 — 준비 시간 부족")
    return " · ".join(parts) or None


def _won(amount: int) -> str:
    """금액을 사람이 읽는 말로 — 금액 한 벌은 `app.core.money.won` 한 곳(27차 §3-E · 검수 R27U-MSC-02)."""
    return won(amount)


#: 「왜 맞나」 근거에서 뺄 기관 이름 조각(「전남인력개발원」의 개발 · 「OO교육원」의 교육 · 43차 BIZ-02).
_HIT_ORG_RE: Final[re.Pattern[str]] = re.compile(
    r"[가-힣A-Za-z0-9·]{2,30}?(?:센터|재단|진흥원|개발원|교육원|연수원|협회|공단|공사|대학교|대학|학교|연구원|위원회|교육청|사업단|협의회|조합|산학협력단)(?![가-힣])"
)
_ASCII_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9]+$")


def _hits(text: str, tokens: list[str]) -> list[str]:
    """회사 낱말이 글에 있는가 — **영문은 낱말 경계**(「Main-Biz」 · 「Training」의 AI 가 아님) · 기관 이름 조각은 뺀다 ·
    「교육장」의 교육은 아니다(43차 BIZ-02 · 지원 적합도 계산은 이미 경계로 봤다)."""
    cleaned = _HIT_ORG_RE.sub(" ", text or "")
    out: list[str] = []
    for token in tokens:
        if _ASCII_TOKEN_RE.match(token):
            pattern = rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])"
        else:
            pattern = re.escape(token) + r"(?!장)"
        if re.search(pattern, cleaned, re.I):
            out.append(token)
    return out


def _component(key: str, score: float | None, reason: str) -> PriorityComponent:
    return PriorityComponent(key=key, label=PRIORITY_LABELS[key], weight=PRIORITY_WEIGHTS[key], score=score, reason=reason)


# --------------------------------------------------------------------------
# 정규화 · 신뢰도 · 라벨
# --------------------------------------------------------------------------


def normalize(components: list[PriorityComponent]) -> int | None:
    """계산된 항목만으로 0~100 정규화. 하나도 없으면 None (0점이 아니다)."""
    computed = [c for c in components if c.score is not None]
    total = sum(c.weight for c in computed)
    if not total:
        return None
    return round(100 * sum(c.weight * (c.score or 0.0) for c in computed) / total)


def confidence_of(components: list[PriorityComponent], *, source: str) -> Confidence:
    """계산된 배점 비중 + 데이터 출처로 신뢰도를 정한다. 합성 샘플이면 항상 low."""
    if source == "sample":
        return "low"
    computed = sum(c.weight for c in components if c.score is not None)
    if computed >= 80 and source in ("g2b", "bizinfo"):
        return "high"
    if computed >= 55:
        return "medium"
    return "low"


def label_of(score: int | None, *, closed: bool, top_cut: int | None = None) -> PriorityLabel:
    """점수 하나를 라벨로. `top_cut` 은 같은 출처 상위 15% 의 경계 점수다 (0922 §4-B-6).

    「우선 검토」는 **80점 이상이거나 상위 15%** 다. 둘 중 하나로 두는 이유: 점수가 낮게
    깔린 날에도 맨 위 몇 건은 이름을 가져야 하고, 잘 맞는 공고가 많은 날에는 상위 15%
    밖이라도 80점이면 「우선 검토」가 맞다.
    """
    if closed:
        return "마감"
    if score is None:
        # 「후순위」가 아니다. 뒤로 보낸 것과 아직 재지 못한 것은 담당자에게 다른 뜻이다
        # (ISSUE-041 · CLAUDE.md §12).
        return "미확인"
    if score >= PRIORITY_HIGH or (top_cut is not None and score >= top_cut):
        return "우선 검토"
    if score >= PRIORITY_MID:
        return "검토"
    return "후순위"


def top_cut_of(scores: list[int]) -> int | None:
    """상위 `PRIORITY_TOP_RATIO` 의 경계 점수. 셀 것이 없으면 None."""
    values = sorted((s for s in scores if s is not None), reverse=True)
    if not values:
        return None
    count = max(1, round(len(values) * PRIORITY_TOP_RATIO))
    return values[min(count, len(values)) - 1]


# --------------------------------------------------------------------------
# 나라장터 입찰공고
# --------------------------------------------------------------------------


def _profile_regions(profile: CompanyProfile) -> tuple[str, ...]:
    """회사 프로필의 활동 지역을 지역 대조용 토큰으로. 「전국」은 지역 이름이 아니다."""
    return tuple(r.strip() for r in profile.preferred_regions if r and r.strip() not in ("전국", "제한없음"))


def _capacity_krw(organization_id: str | None) -> int | None:
    """회사가 적어 둔 혼자 맡을 수 있는 최대 사업비. 적지 않았으면 None — 시스템이 숫자를 지어내지 않는다."""
    if not organization_id:
        return None
    from app.services import delivery_capacity_service

    try:
        return delivery_capacity_service.load(organization_id).budget_ceiling_krw
    except Exception:  # noqa: BLE001 — 역량 자료를 못 읽는다고 목록이 죽으면 안 된다
        return None


def score_procurement(
    notice: ProcurementNotice,
    match: CandidateMatch | None,
    *,
    profile: CompanyProfile,
    source: str,
    now: datetime | None = None,
    organization_id: str | None = None,
    gate: EligibilityGate | None = None,
    capacity: Any = None,
    tracks: list[str] | None = None,
    rules: "list[Any] | None" = None,
) -> tuple[list[PriorityComponent], list[str], list[str], dict[str, Any]]:
    """입찰공고의 검토 우선순위 항목. 추천등급(recommendation)은 그대로 두고 재사용만 한다.

    8차에서 바뀐 것 (0922 §4-B):
      - **마감이 배점에서 빠졌다.** 적합도와 긴급도를 두 축으로 나눈다.
      - 사업영역은 네 등급이다 — 검증 역량 1.0 · 우리 갈래 0.7 · AI 낱말만 0.45 · 그 밖 0.2.
      - 자격은 **판정 종합(gate)** 을 그대로 쓴다. 목록과 상세가 같은 답을 내야 한다.
      - 규모 10점이 일정 10점을 대신한다.
    """
    current = _now(now)
    ceiling = _capacity_krw(organization_id)
    rec = recommendation.evaluate(
        notice,
        match,
        now=current,
        preferred_regions=_profile_regions(profile),
        capacity_krw=ceiling,
        # 목록 한 번에 공고 100건이 들어온다. 문구 쪼개기는 `company_phrases` 가 마지막 결과를
        # 재사용하고, 문구 임베딩은 semantic_matcher 의 디스크 캐시가 맡는다.
        phrases=recommendation.company_phrases(
            business_domains=profile.business_domains,
            target_clients=profile.target_clients,
            certifications=profile.certifications,
        ),
    )
    by_key = {c.key: c for c in rec.components}
    text = " ".join(filter(None, [notice.title, notice.description or ""]))
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    reasons: list[str] = []
    checks: list[str] = []

    # 1) 사업영역 — 네 등급 (0922 §4-B-1).
    #
    # 갈래는 부르는 쪽이 이미 판정해 두었으면 그것을 쓰고(목록이 한 번만 돌리게), 없으면
    # 여기서 같은 규칙표로 판정한다 — **두 번째 규칙표를 만들지 않는다.**
    work_tracks = list(tracks) if tracks is not None else list(work_kinds.of_notice(notice)["tracks"])
    procurement_class = raw.get("procurement_class")
    # 43차 결정 4 — 제목이 우리 갈래(A1 · A2 · B1 · C)를 말하면 조달 분류 · 제목의 「그 밖」 낱말로 0.2 에 묶지 않는다(유형 근사와 같은 원칙)
    from app.services import practical_priority as _practical

    titled = _practical._title_type(notice.title or "")
    ours = titled is not None and titled[0] in ("A1", "A2", "B1", "C")
    if ours:
        # 조달 분류는 보지 않는다 · 제목의 「그 밖」 낱말은 보되, 교육 일 꼴(교육 콘텐츠 제작 · 교육 운영)이면 그 밖이 아니다(비추천 접기의 예외와 같은 함수)
        other = is_other_work(text=text, tracks=work_tracks, procurement_class=None)
        if other and opportunity_filter.event_edu_ok(notice.title or "", ai=True):
            other = None
    else:
        other = is_other_work(text=text, tracks=work_tracks, procurement_class=procurement_class)
    hits = proven_skill_hits(capacity, text)
    domain_tokens = profile_tokens(list(profile.business_domains))
    domain_hits = _hits(text, domain_tokens)
    if other:
        band, band_reason = (
            DOMAIN_OTHER,
            f"기본 규칙(AI · 교육 · 컨설팅 · 개발 기준)으로 뒤로 보냈습니다({other}) — 회사 사업과 다르면 원문을 확인하세요",
        )
        checks.append(f"회사가 하는 종류의 일이 아닌 사업으로 보입니다 ({other}). 과업 범위를 원문에서 확인하세요.")
    elif hits:
        band, band_reason = DOMAIN_PROVEN, f"회사가 해 본 일입니다 — 해 본 일: {', '.join(hits[:3])}"
        reasons.append(f"해 본 일과 맞음: {', '.join(hits[:3])}")
    elif {"development", "education"} & set(work_tracks):
        named = " · ".join(
            "개발형" if t == "development" else "교육·훈련형"
            for t in work_tracks
            if t in ("development", "education")
        )
        # 개발형인데 **대상이 교육**이면(또는 그 반대) 회사의 두 축이 다 걸린 것이다.
        both = {"development", "education"} <= set(work_tracks) or (
            "development" in work_tracks and bool(_EDUCATION_SUBJECT_RE.search(text))
        )
        band = DOMAIN_BOTH_TRACKS if both else DOMAIN_TRACK
        band_reason = (
            f"교육과 개발, 회사의 두 사업에 모두 맞습니다 ({named})"
            if both
            else f"회사가 하는 종류의 일입니다 ({named})"
        ) + (f" · 조달 분류 {procurement_class}" if procurement_class else "")
        reasons.append(("교육·개발 두 사업에 맞음: " if both else "회사가 하는 일: ") + named)
    elif match is not None and match.is_candidate:
        band = DOMAIN_KEYWORD
        band_reason = (
            f"공고에 「AI」 낱말만 있습니다 (낱말 관련도 {recommendation.tier_label(match.tier)})"
            " — 무슨 일인지는 원문 확인 필요"
        )
        checks.append("AI 낱말만으로 후보가 된 공고입니다. 과업이 우리 일인지 원문에서 확인하세요.")
    else:
        band, band_reason = DOMAIN_OTHER, "회사 사업영역과 이어지는 근거를 찾지 못했습니다"

    # 의미 유사도를 **실제로 쟀을 때만** 함께 본다 (CLAUDE.md §C Semantic Matching).
    #
    # 등급과 의미 유사도는 서로 다른 질문에 답한다 — 등급은 「무슨 일인가」, 유사도는
    # 「내용이 우리와 얼마나 가까운가」다. 둘 중 **높은 쪽**을 쓰되, 「그 밖」은 유사도로도
    # 올리지 않는다: 감리·전시 사업은 내용이 아무리 AI 여도 우리가 수행자가 아니다.
    semantic = recommendation.semantic_used(rec)
    if semantic is not None and not other:
        if semantic.fit_score > band:
            band_reason = f"{band_reason} · {semantic.reason}"
            band = round(semantic.fit_score, 3)
        else:
            band_reason = f"{band_reason} · {semantic.reason}"
        reasons.append(semantic.reason)
    domain = _component("domain", band, band_reason)
    if domain_hits:
        reasons.append(f"회사 사업영역과 일치: {', '.join(domain_hits[:3])}")
    if rec.out_of_scope:
        checks.append("회사 사업영역 밖으로 보이는 사업 유형입니다. 과업 범위를 원문에서 확인하세요.")

    # 2) 참가자격 — **판정 종합을 그대로 쓴다** (0922 §4-B-2).
    #
    # 예전에는 이 자리에서 지역만 다시 훑어 0.45~0.6 을 매겼다. 그래서 업종·지역이 코드로
    # 확정돼도 점수가 움직이지 않았다. 이제 규칙표의 종합(gate)을 그대로 읽는다 —
    # 목록 배지와 점수가 같은 사실에서 나온다.
    # 고정 문구 대신 **실제 상태**를 적는다 (19차 §4-B) — 공고문 조항을 몇 개 읽었고 그중 몇이
    # 회사 쪽 확인·원문 확인으로 남았는가. 규칙 결과를 받지 못한 호출자에게만 예전 문구가 간다.
    line = eligibility_engine.qualification_line(rules) if rules is not None else None
    checks.append(f"{line}." if line else "참가자격(면허 · 업종 · 유사실적)은 공고 원문에서 확인하세요.")
    if gate == "PASS":
        eligibility = _component("eligibility", 1.0, "참가 가능 — 나라장터에 등록된 조건은 모두 맞습니다")
        reasons.append("참가 자격 판정: 가능")
    elif gate == "FAIL":
        eligibility = _component("eligibility", 0.0, "불가 — 참가할 수 없는 조건이 있습니다")
    elif gate == "CHECK":
        eligibility = _component("eligibility", 0.5, "확인 필요 — 아직 정해지지 않은 조건이 있습니다")
    else:
        eligibility = _component("eligibility", None, "자격 판정 전 — 아직 규칙으로 보지 않았습니다")

    # 3) 수행근거 — RFP를 파싱해 요구사항↔근거를 매칭하기 전에는 계산하지 않는다.
    evidence = _component("evidence", None, "요구사항 정리표를 만든 뒤 계산합니다(지금은 점수 없음 — 0점 아님)")

    # 4) 규모 (0922 §4-B-3)
    scale = scale_component(
        notice.budget,
        ceiling=ceiling,
        joint_allowed=eligibility_engine.joint_allowed(raw),
    )
    if notice.budget is None:
        checks.append("예산(기초금액)이 공고에 없습니다. 수익성은 원문에서 확인하세요.")

    # 5) 전략적 가치 — 지역 + 재공고 (0922 §4-B-4).
    base = by_key["strategic_fit"].score
    value = base
    notes: list[str] = []
    # 키트(범용 설치)에서는 광주·전남 발주 가산을 붙이지 않는다 — 다른 지역 회사에 맞지 않는다(30차 §4 마지막 검토).
    home = None if get_settings().neutral_company_defaults else home_ground(notice.agency, raw.get("demand_institution"))
    if home:
        value = min(1.0, (value if value is not None else 0.5) + HOME_REGION_BONUS)
        notes.append(f"{home} — 광주·전남 기관 발주")
        reasons.append(f"광주·전남 기관 발주: {home}")
    # 재공고는 앞선 회차가 유찰·취소됐다는 뜻이라 **경쟁이 적을 수 있다.** 검수자도 한남대·
    # KISTI 를 1~3순위에 넣으며 그 점을 적었다(「취소 후 재등록된 건이라 경쟁이 적을 수 있다」).
    # 낙찰 «확률»이 아니다 — 담당자가 먼저 볼 이유 하나일 뿐이다.
    kind = (raw.get("notice_kind") or "").strip()
    if "재공고" in kind:
        value = min(1.0, (value if value is not None else 0.5) + REPOST_BONUS)
        notes.append(f"{kind} — 앞선 회차가 유찰·취소됐습니다 (경쟁이 적을 수 있습니다)")
        reasons.append("재공고 — 경쟁이 적을 수 있음")
    if value is None:
        strategic = _component("strategic", None, by_key["strategic_fit"].reason)
    else:
        strategic = _component(
            "strategic", round(value, 3), " · ".join(notes) or by_key["strategic_fit"].reason
        )

    components = [domain, eligibility, evidence, scale, strategic]
    source_score = {
        "kind": "recommendation",
        "grade": rec.grade,
        "score": round(rec.score, 4),
        "gate_reason": rec.gate_reason,
        "note": "추천등급은 낙찰확률이 아닙니다.",
        # 사업영역 점수를 무엇으로 쟀는지. 화면이 「AI 의미 매칭」인지 「키워드 규칙」인지
        # 구분해 적을 수 있게 값과 라벨을 함께 내려보낸다. 못 쟀으면 fit_score 는 None 이다.
        "fit_method": rec.fit.method if rec.fit is not None else "KEYWORD",
        "fit_method_label": recommendation.FIT_METHOD_LABELS.get(
            rec.fit.method if rec.fit is not None else "KEYWORD",
            recommendation.FIT_METHOD_LABELS["KEYWORD"],
        ),
        "fit_score": rec.fit.fit_score if rec.fit is not None else None,
        "fit_reason": rec.fit.reason if rec.fit is not None else None,
    }
    return components, reasons, checks, source_score


# 게이트 사유에 붙이는 FAIL 규칙 수 상한. 카드 한 줄에 들어가야 한다.
_GATE_FAIL_LIMIT: Final[int] = 2



def _gate_text(result: EligibilityResult) -> str:
    """불가 사유 한 칸 — **판정 문장 먼저, 원문은 뒤**(43차 Q13 · ELIG-10 — 원문 앞 60자에서 잘려 어느 지역인지 안 보였다)."""
    if not result.clause_text:
        return result.reason
    text = " ".join(result.clause_text.split())
    return f"{result.reason} — 원문 「{text[:60]}{'…' if len(text) > 60 else ''}」"


#: 공고마다 되풀이하지 않는 줄 — 나라장터 등록 · 결격(회사 단위 확인 하나로 닫힌다 · 43차 결정 2 · M7).
def _repeated_row(result: EligibilityResult) -> bool:
    return result.rule_id == "ELIG-REGISTRATION" or result.rule_id.startswith("QUAL-DISQUAL-")


_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_DIRECT_ITEM_RE = re.compile(r"([가-힣A-Za-z]{2,20}(?:서비스|제작|용역))")


def stage0_conditions(results: list[EligibilityResult], raw: dict[str, Any]) -> list[str]:
    """실무 문서 §2.5 0단계 — 이것이 없으면 바로 탈락하는 조건을 이름까지(43차 M7 · ELIG-07).

    「1469 없으면 탈락(공동수급 불허)」 · 「직접생산(동영상제작서비스)」 · 「필수 설명회 11/02」. 확인 필요 줄에서만 뽑는다(판정은 그대로)."""
    out: list[str] = []
    solo = eligibility_engine.joint_allowed(raw or {}) is False
    for r in results:
        if r.status != "CHECK":
            continue
        if solo and (r.rule_id == "ELIG-INDUSTRY" or r.rule_id.startswith("QUAL-INDUSTRY-")):
            codes = list(dict.fromkeys(_CODE_RE.findall(" ".join([*r.unlock_options, r.unlock_condition or "", r.reason]))))
            if codes:
                out.append(f"{' · '.join(codes[:3])} 없으면 탈락(공동수급 불허)")
        elif solo and r.clause_text and "직접생산" in r.clause_text:  # Q24 — 공동수급 불허면 0단계 탈락 줄에
            named = eligibility_engine._direct_items(r.clause_text)
            item = _DIRECT_ITEM_RE.search(r.clause_text)
            out.append(f"직접생산({' · '.join(n for n, _c in named[:2]) if named else item.group(1) if item else '공고문 품명'})")
        elif r.rule_id == "ELIG-BRIEFING":
            when = re.search(r"\d{2}/\d{2}", r.unlock_condition or r.reason)
            out.append(f"필수 설명회 {when.group(0) if when else ''}".strip())
    return list(dict.fromkeys(out))


def procurement_eligibility_gate(
    notice: ProcurementNotice,
    match: CandidateMatch | None,
    *,
    profile: CompanyProfile,
    now: datetime | None = None,
    organization_id: str | None = None,
    results: "list[Any] | None" = None,
) -> tuple[EligibilityGate, str | None]:
    """입찰공고에도 「내가 이 입찰에 참가할 수 있나」를 붙인다.

    지원사업만 게이트가 있고 나라장터 공고에는 없었다. 스키마 기본값 "CHECK" 가 그대로 굳어
    사유도 비어 있었고, 담당자는 카드 앞면에서 참가 가능 여부를 알 수 없었다.

    판정을 새로 지어내지 않는다. 상세 화면이 쓰는 규칙표(eligibility_engine)를 그대로 돌리고,
    그 결과에 이미 있는 추천 게이트(recommendation.gate_reason)를 얹기만 한다.

    - FAIL 은 «명백히 참가할 수 없다»일 때만이다. 규칙표에서 FAIL 이 나오는 경우는
      마감 경과(입찰서·참가자격 등록)와 «지역 이름이 실제로 적힌» 지역제한 불일치뿐이다.
      대상 지역을 모르는 지역제한은 CHECK 로 간다 — 들어갈 수 있는 공고를 버리지 않기 위해서다.
    - PASS 는 만들지 않는다. 면허·업종·유사실적은 공고 원문을 읽어야 알 수 있다 (CLAUDE.md 4-D).
    - 사업영역 밖(out_of_scope)은 «참가 불가»가 아니라 «우리가 할 일이 아닌 것 같다»이다.
      점수와 라벨이 이미 뒤로 보내고 있으므로 게이트에서 FAIL 로 닫지 않는다.
    """
    current = _now(now)
    rec = recommendation.evaluate(notice, match, now=current)
    regions = tuple(r for r in profile.preferred_regions if r)
    # 회사 쪽 사실(등록 업종·소재지·상한·준비 일수)을 함께 넘긴다 (0921 §4-B).
    # 목록과 상세가 **같은 함수**로 만든 같은 값을 봐야 두 화면이 같은 답을 낸다.
    # 이미 판정해 둔 결과가 있으면 그것을 쓴다 — 목록 100건에 같은 규칙을 두 번 돌리지 않는다.
    if results is None:
        results = eligibility_engine.evaluate_notice_fields(
            notice.raw_data,
            as_of=current,
            regions=regions,
            company=eligibility_engine.company_facts_for(organization_id),
            notice_id=notice.id,
        )

    # 참가자격 조항이 막으면 **조항 원문**(앞 60자)을 첫 사유로 적는다 (20차 §4-D-4) — 판정 문장보다
    # 원문이 근거다. 조항 줄을 공고 필드 줄보다 앞에 둔다(정렬은 안정적이라 나머지 순서는 그대로).
    failed = sorted((r for r in results if r.status == "FAIL"), key=lambda r: 0 if r.clause_text else 1)
    if failed:
        return "FAIL", " · ".join(f"{r.label}: {_gate_text(r)}" for r in failed[:_GATE_FAIL_LIMIT])
    if rec.grade == "NO_GO" and rec.gate_reason:
        # 공고 필드에 마감일시가 없어 규칙표가 잡지 못한 마감 경과를 여기서 잡는다.
        return "FAIL", rec.gate_reason

    parts: list[str] = []
    if rec.out_of_scope and rec.gate_reason:
        parts.append(rec.gate_reason)
    pending = list(dict.fromkeys(r.label for r in results if r.status == "CHECK"))
    stage0 = stage0_conditions(results, notice.raw_data if isinstance(notice.raw_data, dict) else {})
    if stage0:
        parts.append("0단계 확인: " + " · ".join(stage0))
    if not pending:
        # **확인할 것이 하나도 남지 않았다 → 가능이다** (0922 §4-B-2).
        #
        # 7차까지 이 함수는 PASS 를 만들지 않았다. 업종·지역을 받지 못해 언제나 「확인 필요」가
        # 남았기 때문이다. 8차에서 그 값이 코드로 오므로, 규칙이 전부 통과한 공고는 「가능」이라고
        # 말할 수 있다 — 근거는 공고 필드 값이고 규칙마다 `source` 에 적혀 있다.
        confirmed = " · ".join(f"{r.label}: {r.reason}" for r in results[:_GATE_FAIL_LIMIT])
        return "PASS", (confirmed or "나라장터에 등록된 참가 조건을 모두 충족합니다")
    # 공고문 쪽과 회사 쪽을 나눈다 — 「공고문에서 볼 것」 아래 사업 규모 · 결격 · 업종 같은 회사 쪽이 섞였다(33차 R32-08)
    # 등록 · 결격은 공고마다 되풀이하지 않는다 — 회사 단위 확인 한 번(43차 결정 2 · M7). 그것만 남았으면 그렇다고 한 번 적는다.
    rest = [r for r in results if r.status == "CHECK" and not _repeated_row(r)]
    company_side = list(dict.fromkeys(r.label for r in rest if r.check_side == "company"))
    notice_side = [label for label in dict.fromkeys(r.label for r in rest if r.check_side != "company")]
    if notice_side:
        parts.append("공고문에서 볼 것: " + " · ".join(notice_side))
    if company_side:
        parts.append("회사자료에 적거나 직접 확인할 것: " + " · ".join(company_side))
    if not rest:
        parts.append("남은 것: 회사 단위 확인(나라장터 등록 · 부정당 제재 · 체납 — 회사자료 › 입찰 자격 자료)")
    return "CHECK", " · ".join(parts)


# --------------------------------------------------------------------------
# 기업마당 지원사업
# --------------------------------------------------------------------------

# 지원분야 대분류(실응답 값): 경영·기술·수출·인력·내수·금융·창업·기타
_STRATEGIC_CATEGORY_SCORE: Final[dict[str, float]] = {
    "인력": 1.0,
    "기술": 0.8,
    "경영": 0.8,
    "창업": 0.6,
    "내수": 0.4,
    "수출": 0.3,
    "금융": 0.3,
    "기타": 0.3,
}


#: 조항 기반 사업영역 점수 (0924 §4-B-1).
SUPPORT_CLAUSE_SCORES: dict[str, float] = {
    # 「open」(가능인데 회사 사실과 이어지는 근거가 없음)은 **없앴다** (0925 §4-A-1).
    # 그런 건은 이제 「가능」이 아니라 「확인 필요」다 — 아래 `check` 로 간다.
    "match": 1.0,     # 가능 + 회사 인증·소재·보유·연차가 요건과 맞음
    "check": 0.6,     # 확인 필요 — 공고 쪽을 더 봐야 한다 (소재 해석 등)
    "check_company": 0.4,  # 확인 필요 — **회사가 아직 못 갖췄거나 안 적은 것**(매출·연구소·데이터)
    # 확인 필요지만 회사 사실이 하나 이상 맞음(인증 · 소재 · 보유 · 연차 · 전략산업) — 담당자 결정 10-10 「덜 깎기」.
    # 「가능」 좁히기로 검수자 1~3순위(123682 · 125426)가 44 · 48위로 떨어졌다 — 맞은 것이 있는 확인 필요는 아무것도 안 맞은 것과 다르다.
    "check_matched": 0.8,
    "indirect": 0.4,  # 신청 주체가 아니라 공급기업·기술기업으로 들어감
    "blocked": 0.0,   # 불가
}
SUPPORT_CLAUSE_REASONS: dict[str, str] = {
    "match": "우리 회사와 맞음(인증 · 소재 · 보유)",
    "check": "확인 필요 — 공고 원문을 더 봐야 합니다",
    "check_company": "확인 필요 — 회사 정보(매출 · 연구소 · 보유)가 아직 없습니다",
    "check_matched": "확인 필요 — 회사와 맞은 점이 있고 남은 것을 확인해야 합니다",
    "indirect": "간접 참여(공급·기술기업)",
    "blocked": "불가",
}
#: 「받는 것」이 클 때의 사업영역 가산 (0924 §4-B-1).
#:
#: 무료·전액 지원은 회사가 **지금 신청하면 실제로 받는 것**이다. 사업영역 낱말이 적게
#: 겹쳐도 담당자가 먼저 본다 — 검수자의 1·2순위가 정확히 그런 건이었다.
SUPPORT_BENEFIT_BONUS: Final[dict[str, float]] = {"free": 0.2, "large": 0.1}
SUPPORT_BENEFIT_BONUS_REASONS: Final[dict[str, str]] = {
    "free": "무료 지원이라 점수를 더했습니다",
    "large": "사업화 자금이 커서 점수를 더했습니다",
}

#: 다른 시·도가 소관인 사업의 전략적 가치 배수 (0924 §4-B-1).
OTHER_REGION_STRATEGIC_FACTOR: Final[float] = 0.5

SUPPORT_BENEFIT_LABELS: dict[str, str] = {
    "free": "무료·전액 지원",
    "large": "사업화 자금(5천만 이상)",
    "medium": "1천만~5천만",
    "small": "1천만 미만",
}


def _not_ours_reason(kind_result: Any) -> str:
    """점수 상한을 둔 사업 성격 사유 — 모른다 · 요약에만 · 다른 사업으로 보인다를 가른다(32차 R31-17)."""
    if kind_result.kinds == ["unclassified"]:
        return "공고 낱말로는 어떤 사업인지 알 수 없어 점수 상한을 둡니다 — 원문을 확인하세요"
    if not kind_result.declared:
        return f"{kind_result.basis} — 그래서 점수 상한을 둡니다"
    return f"{kind_result.basis} — 우리 회사가 직접 맡기 어려운 사업으로 보여 점수 상한을 둡니다"


def _clause_bucket(signals: dict) -> str:
    """점수 버킷. **판정이 정한다** — 「가능」은 회사 사실이 맞았을 때뿐이다 (0925 §4-A-1)."""
    if signals.get("gate") == "FAIL":
        return "blocked"
    if signals.get("indirect"):
        return "indirect"
    if signals.get("gate") == "CHECK":
        if signals.get("company_match"):
            return "check_matched"
        return "check_company" if signals.get("company_side_checks") else "check"
    return "match"


#: 신청자격 항목 — 확인 필요지만 회사 사실이 하나 이상 맞으면 덜 깎는다(담당자 결정 10-10). 가능 1.0 · 불가 0 은 그대로.
SUPPORT_CHECK_ELIGIBILITY: float = 0.5
SUPPORT_CHECK_MATCHED_ELIGIBILITY: float = 0.75


def softened_check(gate: str | None, signals: dict | None) -> bool:
    """확인 필요지만 회사 사실이 맞은 점이 있어 신청자격을 덜 깎는가 — 간접 참여는 아니다(담당자 결정 10-10 · 검토)."""
    return gate == "CHECK" and bool(signals) and bool(signals.get("company_match")) and not signals.get("indirect")


def score_support(
    program: SupportProgram,
    fit: SupportFit,
    *,
    profile: CompanyProfile,
    source: str,
    today: date | None = None,
    gate: EligibilityGate | None = None,
    relevance: Any = None,
    signals: dict | None = None,
) -> tuple[list[PriorityComponent], list[str], list[str], dict[str, Any]]:
    """지원사업의 검토 우선순위 항목. 지원 적합도(support_fit)는 그대로 두고 재사용만 한다.

    `today` 는 호출자가 「업무 날짜」를 고정할 수 있게 남겨 둔 인자다. **8차부터 점수는
    날짜를 보지 않는다** (0922 §4-B-0) — 마감은 D-day·정렬·「이번 주 할 일」에서만 쓴다.
    """
    # 지연 import — 이 모듈 맨 위의 import 고리(주석 참고)를 건드리지 않는다.
    from app.services import bizinfo_service

    by_key = {c.key: c for c in fit.components}
    text = " ".join(filter(None, [program.title, program.summary or "", program.category or "", program.subcategory or "", " ".join(program.hashtags), program.target or ""]))
    reasons: list[str] = []
    checks: list[str] = []

    # 1) 사업영역 — 「어떤 성격의 사업인가」를 먼저 보고, 그 다음에 키워드를 본다.
    #
    # 키워드만으로 점수를 매기면 안 된다. 회사 프로필에서 뽑은 토큰이 25개나 되어
    # (AI·교육·컨설팅·개발·로봇·제조·대학·비전 …) 거의 모든 공고가 두어 개는 스치고,
    # `len(hits)/2` 규칙에서는 그것만으로 만점이 나왔다.
    # 실측(2026-09-10, 100건): 「국제공동연구」·「시설농업 AI로봇 실증」이 나란히 1·2위였다.
    #
    # 그래서 support_kinds 로 사업의 성격을 먼저 판정하고, 회사가 주체가 되기 어려운
    # 갈래(R&D 과제·제조 설비·전시 지원 등)에는 상한을 둔다. 점수를 0으로 만들지는 않는다 —
    # 담당자가 보고 판단할 여지는 남긴다.
    kind_result = support_kinds.of_program(program)
    # 회사가 «신청자»가 될 수 없는 안내인가 (ISSUE-005).
    # 갈래 판정(support_kinds)은 「AI 교육이다」까지만 본다. 「AI 활용 역량 강화 교육」은
    # 우리 갈래가 맞지만, 그 공고가 모집하는 것이 «수강생»이면 회사가 신청할 자리가 없다.
    # 실측 1위가 정확히 그 경우였다 — 갈래는 통과하고 사업영역 1.0 을 받았다.
    audience = audience_filter.audience_note(f"{program.target or ''} {text}")
    audience_kind = audience_filter.audience_kind(f"{program.target or ''} {text}")
    base = by_key["domain"].score
    domain_tokens = profile_tokens(list(profile.business_domains))
    domain_hits = _hits(text, domain_tokens)
    profile_score = min(1.0, len(domain_hits) / 2) if domain_tokens else None
    # 지원 적합도가 사업영역을 «의미 유사도로» 판정했는가 (bizinfo_service.support_fit).
    # 그랬다면 그 값을 키워드 일치 횟수로 다시 희석하지 않는다.
    domain_is_semantic = fit.method == bizinfo_service.SEMANTIC_FIT_METHOD
    if base is None and profile_score is None:
        domain = _component("domain", None, "분야 낱말 정보 없음")
    else:
        if domain_is_semantic and base is not None:
            blended = base
        else:
            blended = profile_score if base is None else (base if profile_score is None else 0.6 * base + 0.4 * profile_score)
        reason = by_key["domain"].reason
        if domain_hits:
            reason += f" · 회사 사업영역 일치: {', '.join(domain_hits[:3])}"
            reasons.append(f"회사 사업영역과 일치: {', '.join(domain_hits[:3])}")

        blended = blended or 0.0
        if audience is not None:
            # 갈래 상한보다 먼저 적용한다 — 「우리 갈래」로 판정돼도 신청 주체가 아니면
            # 상단에 둘 이유가 없다. 0 으로 만들지는 않는다: 규칙이 틀렸을 때
            # 담당자가 목록에서 찾을 수 있어야 한다.
            blended = min(blended, AUDIENCE_CAP)
            reason += f" · {audience}"
            checks.append(audience)
        if not kind_result.is_ours:
            capped = min(blended, NON_MATCHING_KIND_CAP)
            if capped < blended:
                # 「알 수 없습니다」 뒤에 「직접 맡는 사업이 아니라」고 단정했다(76건) — 경우마다 다른 사유(32차 R31-17)
                reason += f" · 사업 성격: {_not_ours_reason(kind_result)}"
                # 괄호 세 겹(「(공고 낱말: …(「…」) — …)」)을 낱말만으로(32차 어려운 글 #3)
                words = " · ".join(kind_result.words[:2])
                checks.append(
                    "우리 회사가 직접 할 사업인지 공고 원문에서 확인하세요."
                    + (f" 공고에 「{words}」 같은 말이 있습니다." if words else "")
                )
            blended = capped
        else:
            reason += f" · 사업 성격: {kind_result.basis}"
            reasons.append(f"사업 성격: {kind_result.basis}")

        # 관련 어휘가 하나도 없거나 제외 어휘에 걸린 사업은 「그 밖」 상한을 둔다 (0922 §4-C-2).
        # **갈래 판정과 상관없이 적용한다** — 1,605건을 그대로 두면 식품 페어링·무기체계
        # 부품이 마감 순으로 「이번 주 할 일」에 올라온다.
        if relevance is not None and not relevance.related:
            blended = min(blended, DOMAIN_OTHER)
            reason += f" · {relevance.reason}"
            checks.append(f"회사와 관련이 낮아 보입니다 ({relevance.reason}). 원문에서 확인하세요.")

        # **공고문을 읽었으면 조항이 사업영역 점수를 절반 정한다** (0924 §4-B-1).
        #
        # 요약문 키워드만 볼 때는 「AI」 한 마디로 데이터센터 장비 실증이 우리 사업과 같은
        # 자리에 섰다. 조항을 읽고 나면 다르다 — 자격이 열렸는지, 회사 «사실»(인증·소재·
        # 보유·연차)이 요건과 실제로 맞았는지가 근거로 남는다.
        if signals and signals.get("read"):
            clause_score = SUPPORT_CLAUSE_SCORES[_clause_bucket(signals)]
            blended = round(0.5 * blended + 0.5 * clause_score, 3)
            reason += f" · 공고 조건: {SUPPORT_CLAUSE_REASONS[_clause_bucket(signals)]}"
            # **받는 것이 크면 가산한다** (0924 §4-B-1).
            #
            # 정보보호 지원(정부 80%)·품질관리 테스팅(무료)은 회사 사업영역과 겹치는 낱말이
            # 적어도 담당자가 먼저 보는 건이다 — 지금 신청하면 실제로 받는 것이 있기 때문이다.
            # 검수자가 그 둘을 1·2순위로 올린 이유가 그것이었다.
            # **판정이 「가능」이거나, 확인 필요여도 회사 사실이 맞은 것이 있을 때만 붙인다** (0925 §4-A-5 · 10-10 「덜 깎기」).
            # 아무것도 안 맞은 확인 필요 · 간접 · 불가에 붙이면 「무료」라는 이유로 신청할 수 없는 건이 목록 맨 위에 선다.
            bonus = SUPPORT_BENEFIT_BONUS.get(signals.get("benefit") or "", 0.0)
            if bonus and _clause_bucket(signals) in ("match", "check_matched"):
                blended = min(1.0, round(blended + bonus, 3))
                # 「가산 +0.2」는 0~1 소수 금지 위반이었다 — 말로(32차 어려운 글 #11)
                reason += f" · {SUPPORT_BENEFIT_BONUS_REASONS[signals.get('benefit')]}"
        domain = _component("domain", round(blended, 3), reason)

    # 2) 신청자격 — **판정 종합(gate)을 그대로 쓴다** (0922 §4-B-2). 나라장터와 같은 규칙이다.
    target_score = by_key["target"].score
    region_score = by_key["region"].score
    if (target_score or 0) >= 1.0:
        reasons.append(f"지원 대상 일치: {program.target}")
    if (region_score or 0) >= 1.0:
        reasons.append("회사 활동 지역과 연관된 지역 사업")
    if gate == "PASS":
        eligibility = _component("eligibility", 1.0, "가능 — 지역 · 대상 · 기간 요건이 맞습니다")
    elif gate == "FAIL":
        eligibility = _component("eligibility", 0.0, "불가 — 신청할 수 없는 요건이 있습니다")
    elif softened_check(gate, signals):
        # 간접 참여는 사업영역 칸(간접 0.4)처럼 여기서도 덜 깎지 않는다(검토 10-10). 「맞은 점」은 요건 · 우선 선정 · 요약 대상 줄을
        # 함께 부르는 말 — 「맞은 요건」이라 쓰면 전략산업(우선 선정)만 맞은 공고에 거짓이었다.
        eligibility = _component(
            "eligibility", SUPPORT_CHECK_MATCHED_ELIGIBILITY,
            "확인 필요 — 회사와 맞은 점이 있고, 남은 요건을 확인해야 합니다",
        )
    elif gate == "CHECK":
        eligibility = _component("eligibility", SUPPORT_CHECK_ELIGIBILITY, "확인 필요 — 아직 정해지지 않은 요건이 있습니다")
    elif target_score is not None or region_score is not None:
        parts = [x for x in (target_score, region_score) if x is not None]
        raw = sum(parts) / len(parts)
        eligibility = _component(
            "eligibility",
            round(min(raw, ELIGIBILITY_CAP), 3),
            f"{by_key['target'].reason} · {by_key['region'].reason} · 창업 연차 · 기업 유형 · 제외 대상은 공고 원문에서 확인하세요",
        )
    else:
        eligibility = _component("eligibility", None, "지원 대상·지역 정보 없음 — 원문 확인 필요")
    # **이미 읽은 것을 읽으라고 하지 않는다** (0925 §4-D-1). 공고문을 읽었으면 그 넷 중
    # 못 찾은 것만 적고, 넷 다 찾았으면 이 줄을 아예 내지 않는다.
    if signals is not None and signals.get("read"):
        unfound = signals.get("unfound") or []
        if unfound:
            checks.append(f"공고문에 안 보이는 조건: {' · '.join(unfound)} — 원문에서 확인하세요")
    else:
        checks.append("신청자격(창업 연차 · 기업 유형 · 중복 신청 제한 · 제외 대상)이 맞는지 공고 원문에서 확인하세요.")

    # 3) 수행근거·보유역량 — 회사 인증·사업영역이 지원 분야와 연결되는가 (규칙)
    capability_tokens = profile_tokens(list(profile.certifications) + list(profile.business_domains))
    capability_hits = _hits(text, capability_tokens)
    if not capability_tokens:
        evidence = _component("evidence", None, "회사 프로필에 인증·사업영역 정보가 없습니다")
    elif capability_hits:
        # 키워드 일치일 뿐 승인된 회사자료로 검증한 수행근거가 아니다 → 상한을 둔다.
        evidence = _component(
            "evidence",
            round(min(EVIDENCE_HINT_CAP, EVIDENCE_HINT_CAP * len(capability_hits) / 2), 3),
            f"회사가 적은 역량 「{', '.join(capability_hits[:3])}」이 공고에 나옵니다(회사자료로는 아직 확인 안 함)",
        )
        reasons.append(f"보유 역량과 연결: {', '.join(capability_hits[:3])}")
    else:
        evidence = _component("evidence", 0.2, "공고에 회사 인증 · 사업영역 낱말이 없습니다 — 회사자료로 다시 확인하세요")

    # 4) 규모 — **지원 규모는 목록 API 에 없다.** 0원으로도, 만점으로도 치지 않고 미확인으로
    #    두어 가중치 합에서 뺀다 (0922 §4-B-3). 마감은 점수에 들어가지 않는다 (§4-B-0) —
    #    대신 접수 조건의 주의는 아래처럼 「주의」 줄로 남긴다.
    scale = _component("scale", None, "지원 규모가 목록에 없습니다 — 배점에서 뺍니다")
    # **공고문에서 「받는 것」을 읽었으면 규모를 잰다** (0924 §4-B-1).
    # 무료·전액·사업화 자금이면 회사가 실제로 얻는 것이 크다.
    if signals and signals.get("benefit"):
        from app.services import support_application_service as _sas

        benefit = signals["benefit"]
        scale = _component(
            "scale",
            _sas.BENEFIT_SCORES[benefit],
            f"공고문에서 읽은 지원 규모: {SUPPORT_BENEFIT_LABELS[benefit]}",
        )
    if program.apply_period_kind == "until_budget":
        checks.append("예산 소진 시 조기 마감될 수 있습니다. 접수 현황을 확인하세요.")
    elif program.apply_period_kind == "conditional":
        checks.append("모집 마감 조건(선착순·충원 시 마감)을 원문에서 확인하세요.")
    elif program.apply_end is None and program.apply_period_kind not in ("always_open", "until_budget"):
        checks.append("신청 기간이 목록 정보로 확정되지 않습니다. 원문을 확인하세요.")

    # 5) 전략적 가치 — 지원 분야 대분류 + 주요 고객 유형
    category_score = _STRATEGIC_CATEGORY_SCORE.get((program.category or "").strip())
    # 43차 BIZ-15 — 지원금(수혜) 사업의 「기업」은 고객이 아니라 신청자(우리)다 — 고객 유형 일치는 수행기관 모집(매출)에서만 센다
    from app.services import support_application_service as _sas_kind

    client_hits = _hits(text, profile_tokens(list(profile.target_clients))) if _sas_kind.is_operator_call(program) else []
    strat_parts = [s for s in (category_score, (1.0 if client_hits else None)) if s is not None]
    if strat_parts:
        strategic_score = sum(strat_parts) / len(strat_parts)
        strategic_reason = f"지원분야 {program.category or '미상'}" + (
            f" · 주요 고객 유형 일치: {', '.join(client_hits[:2])}" if client_hits else ""
        )
        # **다른 시·도가 소관인 사업은 전략적 가치가 절반이다** (0924 §4-B-1).
        #
        # 나라장터 쪽 「홈그라운드 가산」(광주·전남 발주 +0.2)의 뒷면이다. 경북·강원 지자체가
        # 자기 지역 기업을 위해 만든 사업이 우리 목록 맨 위에 서면, 담당자가 신청도 못 할
        # 건을 먼저 읽게 된다.
        if signals and signals.get("other_region"):
            strategic_score *= OTHER_REGION_STRATEGIC_FACTOR
            strategic_reason += " · 소관 · 수행기관이 다른 시·도입니다"
        elif signals and signals.get("home_region"):
            # 43차 Q8 — 광주 · 전남(호남권 포함) 한정 사업은 나라장터 홈그라운드와 같은 +0.2
            strategic_score = min(1.0, strategic_score + HOME_REGION_BONUS)
            strategic_reason += " · 광주 · 전남 한정 사업(가산)"
        strategic = _component("strategic", round(strategic_score, 3), strategic_reason)
    else:
        strategic = _component("strategic", None, "지원분야 정보 없음")

    # **개인을 모집하는 안내는 전략적 가치도 낮다** (ISSUE-125 · prompt_05 §4-E-1).
    #
    # 사업영역에는 이미 상한(AUDIENCE_CAP)을 걸어 두었다. 그런데 전략적 가치는 「지원 분야가
    # 우리 분야인가 · 주요 고객 유형이 맞는가」만 보므로, 「AI 교육」 분야의 «교육생 모집»이
    # 여기서 1.0 을 받는다 — 회사가 신청조차 할 수 없는 건인데도. 실측으로 공예 교육생 모집이
    # 전략 1.0 을 받아 8위에 섰다(재검증 §3-7).
    #
    # 참가·출품 기회는 이 규칙에서 뺀다. 그쪽은 회사가 **신청은 할 수 있는** 자리다.
    if audience is not None and audience_kind == audience_filter.INDIVIDUAL:
        strategic = _component(
            "strategic",
            AUDIENCE_CAP,
            f"{strategic.reason} · {audience}",
        )

    components = [domain, eligibility, evidence, scale, strategic]
    source_score = {
        "kind": "support_fit",
        "label": fit.label,
        "score": fit.score,
        "method": fit.method,
        "note": "지원 적합도는 선정확률이 아닙니다.",
        # 조달공고 쪽(source_score kind=recommendation)과 «같은 이름·같은 값»으로 내려보낸다 —
        # 화면이 두 출처를 한 규칙으로 읽을 수 있어야 한다. 원본 method 는 위에 그대로 둔다.
        "fit_method": "EMBEDDING" if domain_is_semantic else "KEYWORD",
        "fit_method_label": (
            recommendation.FIT_METHOD_LABELS["EMBEDDING"]
            if domain_is_semantic
            else recommendation.FIT_METHOD_LABELS["KEYWORD"]
        ),
    }
    return components, reasons, checks, source_score


def support_eligibility_gate(
    fit: SupportFit,
    *,
    rules: "list[Any] | None" = None,
) -> tuple[EligibilityGate, str | None]:
    """목록 원문만으로도 분명한 신청 불가 신호를 점수보다 먼저 판정한다.

    `rules` 를 주면 **BIZ-* 규칙 결과가 먼저다** (0921 §4-B). 그쪽이 지역 태그·대상 요건
    원문·접수 기간을 근거와 함께 보므로, 점수 성분만 보는 아래 경로보다 확실하다.
    종합은 나라장터와 같다 — 하나라도 불가면 불가, 불가가 없고 확인 필요가 있으면 확인 필요.

    (아래는 규칙을 못 받았을 때의 예전 경로다.) 지역 점수 0은 공고에 특정 지역이 명시됐고
    회사 활동 지역과 겹치지 않는 경우다. 이때 업무 키워드가 많이 겹친다는 이유로
    「우선 검토」에 올리면 실제 담당자의 시간을 낭비한다.
    """
    if rules:
        failed = [r for r in rules if r.status == "FAIL"]
        if failed:
            return "FAIL", " · ".join(f"{r.label}: {r.reason}" for r in failed[:_GATE_FAIL_LIMIT])
        checks = [r for r in rules if r.status == "CHECK"]
        if checks:
            return "CHECK", " · ".join(f"{r.label}: {r.reason}" for r in checks[:_GATE_FAIL_LIMIT])
        return "PASS", " · ".join(f"{r.label}: {r.reason}" for r in rules[:_GATE_FAIL_LIMIT])

    by_key = {component.key: component for component in fit.components}
    region = by_key.get("region")
    if region is not None and region.score == 0.0 and "밖으로 보임" in region.reason:
        return "FAIL", f"신청 지역 불일치 — {region.reason}. 지점·사업장 등 예외 자격 증빙이 있으면 담당자가 재검토하세요."
    return "CHECK", "창업 연차 · 기업 유형 · 제외 대상 같은 자세한 신청자격은 공고 원문에서 확인하세요."
