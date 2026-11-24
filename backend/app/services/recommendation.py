"""공고 추천등급 산정 (목록 화면용).

CLAUDE.md 12조의 Opportunity Score 가중치를 따르되, **목록 단계에서 실제로 계산할 수
있는 항목만** 계산하고 나머지는 `skipped`로 남긴다. 계산한 항목만으로 가중치를 다시
정규화하므로, 데이터가 없는 항목이 0점으로 잡혀 등급을 끌어내리지 않는다.

원칙
- **낙찰확률이 아니다.** 샘플에듀가 검토할 가치가 있는 순서를 매기는 값이다 (CLAUDE.md 12).
- 모든 항목에 근거 문장을 남긴다. 화면이 점수만 보여주고 이유를 감추지 않는다.
- 마감이 지난 공고는 점수와 무관하게 No-Go로 처리한다 (CLAUDE.md 12 마지막 문단).
- LLM·네트워크를 쓰지 않는다. 같은 입력이면 항상 같은 등급이 나온다.

목록 단계에서 계산하지 않는 것
- 수행근거 유사도(25%): 요구사항 ↔ Evidence 매칭이 필요하다. RFP를 파싱한 공고에만 있다.
- 인력 적합도: 투입 가능 인력 데이터가 없다. 같은 항목의 '일정'만 계산한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Literal

from app.core.config import get_settings
from app.core.money import won, won_pair
from app.core import storage
from app.schemas.procurement import ProcurementNotice
from app.services import g2b_mapper, semantic_matcher

# `eligibility_engine.COMPANY_PROFILE` 을 여기서 들여오던 줄을 없앴다 (0921 §4-B).
# **쓰는 곳이 한 군데도 없었는데 import 고리를 만들고 있었다** —
# eligibility_engine → procurement_service → recommendation → eligibility_engine.
# 평소에는 다른 모듈이 먼저 올라와 가려졌지만, eligibility_engine 을 먼저 들여오는 경로
# (갭 리포트·스크립트)에서는 그대로 ImportError 로 터졌다.
from app.services.opportunity_filter import CandidateMatch, CandidateTier
from app.services.semantic_matcher import SemanticFit

KST = timezone(timedelta(hours=9))

Grade = Literal["A", "B", "C", "D", "NO_GO"]

# CLAUDE.md 12조 초기 가중치. 계산한 항목만 다시 정규화해 쓴다.
WEIGHTS: Final[dict[str, float]] = {
    "business_fit": 0.35,  # 사업영역 적합도
    "evidence_fit": 0.25,  # 수행근거 유사도  (목록 단계 미계산)
    "schedule_fit": 0.20,  # 인력·일정 적합도 (일정만 계산)
    "budget_fit": 0.10,  # 예산·수익성 적합도
    "strategic_fit": 0.10,  # 전략적 적합도
}

LABELS: Final[dict[str, str]] = {
    "business_fit": "사업영역 적합도",
    "evidence_fit": "수행근거 유사도",
    "schedule_fit": "일정 여유",
    "budget_fit": "예산 적합도",
    "strategic_fit": "지역 적합도",
}

#: 키워드 등급을 담당자 말로 옮긴 표. 사유 문장은 그대로 화면에 나가므로 여기서 한국어로 바꾼다
#: (HIGH·LOW 를 화면에 그대로 내보내지 않는다).
TIER_LABELS: Final[dict[str, str]] = {
    "high": "높음",
    "medium": "보통",
    "low": "낮음",
    "none": "해당 없음",
}


def tier_label(tier: str | None) -> str:
    """모르는 값이 오면 지어내지 않고 원값을 그대로 쓴다."""
    return TIER_LABELS.get(tier or "", tier or "해당 없음")


#: 사업영역 적합도를 «무엇으로 쟀는가»를 담당자 말로 옮긴 표.
#: 화면이 "EMBEDDING" 같은 값을 그대로 쓰지 않도록 라벨을 함께 내려보낸다.
FIT_METHOD_LABELS: Final[dict[str, str]] = {
    "EMBEDDING": "AI 의미 매칭",
    "KEYWORD": "낱말 기준",
}

# 등급 경계. 테스트로 고정한다.
GRADE_A: Final[float] = 0.75
GRADE_B: Final[float] = 0.55
GRADE_C: Final[float] = 0.35

# 키워드 등급 -> 사업영역 적합도
_TIER_SCORE: Final[dict[CandidateTier, float]] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.25,
    "none": 0.0,
}

# 샘플에듀 우선 지역 (합성 프로필). 별칭까지 함께 본다.
_PREFERRED_REGION_TOKENS: Final[tuple[str, ...]] = ("광주", "전남", "전라남도")
_NATIONWIDE_TOKENS: Final[tuple[str, ...]] = ("전국", "제한없음", "제한 없음")

# 수익성이 낮아 검토 우선순위를 낮추는 소액 기준 (합성 가정).
_SMALL_BUDGET: Final[int] = 10_000_000


@dataclass(frozen=True)
class Component:
    """등급 산정 항목 1개. score가 None이면 계산하지 못한 항목이다."""

    key: str
    label: str
    weight: float
    score: float | None
    reason: str

    @property
    def computed(self) -> bool:
        return self.score is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": round(self.weight, 4),
            "score": None if self.score is None else round(self.score, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Recommendation:
    """공고 1건의 추천등급. 낙찰확률이 아니다."""

    grade: Grade
    score: float
    components: list[Component] = field(default_factory=list)
    # 마감 경과처럼 점수와 무관하게 등급을 확정한 사유 (없으면 None).
    gate_reason: str | None = None
    # 샘플에듀 사업영역 밖(감리·데이터센터 등)이라 후순위로 내린 공고인지.
    # 목록 정렬에서 정상 공고 뒤로 보내기 위해 필요하다.
    out_of_scope: bool = False
    # 사업영역 적합도를 의미 유사도로 쟀을 때의 결과. 못 쟀으면 method="KEYWORD" 이고
    # fit_score 는 None 이다 — 그때 점수는 예전 키워드 규칙 값 그대로다.
    fit: SemanticFit | None = None

    @property
    def skipped(self) -> list[str]:
        return [c.label for c in self.components if not c.computed]

    def to_dict(self) -> dict[str, Any]:
        # 사업영역 적합도를 무엇으로 쟀는지 화면이 알 수 있게 함께 내려보낸다.
        # 등급 자체는 여전히 가중치 규칙으로 계산하므로 method 는 "RULE" 그대로다.
        fit_method = self.fit.method if self.fit is not None else "KEYWORD"
        return {
            "grade": self.grade,
            "score": round(self.score, 4),
            "gate_reason": self.gate_reason,
            "out_of_scope": self.out_of_scope,
            "skipped": self.skipped,
            "components": [c.to_dict() for c in self.components],
            "method": "RULE",
            "fit_method": fit_method,
            "fit_method_label": FIT_METHOD_LABELS.get(fit_method, FIT_METHOD_LABELS["KEYWORD"]),
            "fit_score": self.fit.fit_score if self.fit is not None else None,
            "fit_label": self.fit.label if self.fit is not None else None,
            "fit_reason": self.fit.reason if self.fit is not None else None,
            "note": "낙찰확률이 아니라 검토 우선순위입니다.",
        }


def _now(now: datetime | None) -> datetime:
    return now or storage.utc_now()


def calendar_days_left(deadline: datetime | None, now: datetime) -> int | None:
    """마감까지 남은 날 — **KST 달력 날짜 차**(40차 SCREEN-02 · 화면 D-day `lib/deadline.ts` `daysUntil` · 실무순 `practical_priority.days_left` 와 같은 셈).

    지났으면 -1, 오늘 마감이면 0. 시간을 24로 나눠 내림하면 「D-4」 옆에 「마감 3일 남음」이 섰다(10/23 14:00 마감 · 10/19 저녁)."""
    if deadline is None:
        return None
    if deadline.tzinfo is None:  # 방어: 순진한 datetime은 KST로 본다
        deadline = deadline.replace(tzinfo=KST)
    if deadline <= now:
        return -1
    return (deadline.astimezone(KST).date() - now.astimezone(KST).date()).days


def days_until(deadline: datetime | None, now: datetime) -> float | None:
    if deadline is None:
        return None
    if deadline.tzinfo is None:  # 방어: 순진한 datetime은 KST로 본다
        deadline = deadline.replace(tzinfo=KST)
    return (deadline - now).total_seconds() / 86400



# ---------------------------------------------------------------------------
# 사업 유형 판정 — 키워드만으로는 샘플에듀와 무관한 사업이 상위에 올라온다
# ---------------------------------------------------------------------------
# opportunity_filter는 "AI 키워드 + 업무 키워드"만 보므로 `AI ... 위탁감리`,
# `AI 학습용 데이터셋 구축` 같은 공고가 HIGH로 잡힌다. 샘플에듀는 교육·컨설팅
# 수행사이지 감리사·SI·데이터 구축사가 아니다.
#
# 이것은 **의미 유사도(Semantic Matching)가 아니다.** 사업 유형을 문구로 가려내는
# 규칙이며, 판정 근거를 사람이 읽을 수 있게 남긴다.

# 샘플에듀가 수행하지 않는 사업 유형. (라벨, 패턴)
#
# 2026-09-10 개정 — 「시스템·플랫폼 구축」·「모델 개발」·「데이터셋 구축」을 **뺐다**.
#   회사 프로필의 사업영역에 「AI SaaS·소프트웨어 개발」과 「AI Agent·RAG·업무자동화」가 들어 있는데
#   이 세 규칙이 소프트웨어 개발 사업을 통째로 «사업영역 밖»으로 단정하고 있었다.
#   실측(스냅샷 34건): 「AI 활용 빌라시세 자동추정모델 개발 사업」이 D 0.410 out_of_scope,
#   「AI 감사혁신 플랫폼 구축 용역」도 D 0.410 — 개발진 3명이 검토할 만한 공고가 후순위로 밀렸다.
#   규모가 커서 어려운 것과 사업영역이 아닌 것은 다른 문제이며, 규모는 수행역량 판정이 따로 본다
#   (`capability_service`).
#
# 대신 실측에서 A등급으로 잘못 올라오던 두 유형을 **넣었다**.
#   「생성형AI 교육을 위한 구독권 및 기념품 제공」 A 0.787 — 물품 구매인데 최우선이었다.
#   「미래 AI반도체 기술개발 로드맵 수립 연구」 A 0.853 — 정책연구인데 최우선이었다.
_OUT_OF_SCOPE_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("감리", re.compile(r"위탁\s*감리|감리\s*용역|감리\s*사업|정보시스템\s*감리|감리원")),
    ("데이터센터", re.compile(r"데이터\s*센터|(?<![A-Za-z])AIDC(?![A-Za-z])")),
    (
        "구매·도입",
        re.compile(
            r"구독권|기념품|라이선스\s*(?:구매|구입|공급)|물품\s*(?:구매|구입|납품)"
            r"|장비\s*(?:납품|구매|임차)|기자재\s*(?:구매|납품)|도입\s*사업|단순\s*납품"
        ),
    ),
    (
        "연구·조사",
        re.compile(
            r"로드맵\s*수립|정책\s*연구|기초\s*연구|학술\s*연구|방안\s*연구"
            r"|실태\s*조사|동향\s*조사|타당성\s*조사"
        ),
    ),
    (
        "시설·장비",
        re.compile(r"기자재|설치\s*공사|시설물|인프라\s*구축|신축|증축|개축|실시설계"),
    ),
    ("개인정보 영향평가", re.compile(r"개인정보\s*영향평가|영향평가\s*용역")),
)

# 교육을 **직접 수행**한다는 신호. 이게 있으면 위 유형에 걸려도 제외하지 않는다.
# (예: "AI 교육 플랫폼 구축 및 교육과정 운영"은 샘플에듀가 할 수 있는 일이다)
_EDUCATION_EXECUTION_RE: Final[re.Pattern[str]] = re.compile(
    r"교육\s*과정|교육과정|교육\s*운영|교육운영|교육\s*기획|교육\s*프로그램"
    r"|커리큘럼|교안|강사|부트캠프|아카데미|리터러시|literacy"
    r"|역량\s*강화|역량강화|연수|실무\s*교육|실무교육|직무\s*교육"
    r"|이러닝|e\s*러닝|교육생|수강생|양성\s*과정|교재",
    re.IGNORECASE,
)

# 교육이 '주제'로만 언급된 약한 신호. 제외까지는 하지 않고 감점만 한다.
# 예: "교육분야 특화 AI 모형 개발", "교육 플랫폼 구축"
_EDUCATION_TOPIC_RE: Final[re.Pattern[str]] = re.compile(r"교육|교원|학생|학습자|평생학습")

# 비대상 유형인데 교육이 주제로만 언급된 경우의 사업영역 적합도.
# 0.15로는 다른 항목(일정·예산·지역)이 받쳐 B등급에 남았다. 검토 우선순위를
# 확실히 뒤로 보내되 0은 아니게 둔다 — 교육이 언급된 이상 볼 가치가 아주 없지는 않다.
OUT_OF_SCOPE_TOPIC_SCORE: Final[float] = 0.05


def out_of_scope_reason(text: str) -> tuple[str, bool] | None:
    """비대상 사업 유형이면 (유형명, 교육이 주제로라도 언급되는지)를 돌려준다.

    교육을 직접 수행하는 신호가 있으면 비대상으로 보지 않는다(None).
    """
    for label, pattern in _OUT_OF_SCOPE_RULES:
        if not pattern.search(text):
            continue
        if _EDUCATION_EXECUTION_RE.search(text):
            return None  # 교육 수행 사업이다 — 유형 문구만으로 배제하지 않는다
        return label, bool(_EDUCATION_TOPIC_RE.search(text))
    return None


def _notice_text(notice: ProcurementNotice) -> str:
    return " ".join([notice.title, notice.description or ""])


def development_only(notice: ProcurementNotice) -> bool:
    """일의 종류가 개발뿐이고 교육 수행 문구가 없는가.

    갈래 판정은 `work_kinds` 가 단일 출처다 — 여기서 낱말 규칙을 새로 만들지 않는다.
    """
    from app.services import work_kinds

    kinds = set(work_kinds.detect_work_kinds(work_kinds.notice_work_text(notice)))
    if kinds != {"development"}:
        return False
    return not _EDUCATION_EXECUTION_RE.search(_notice_text(notice))


# ---------------------------------------------------------------------------
# 의미 매칭 — 있으면 쓰고, 없으면 지금까지의 키워드 규칙 그대로
# ---------------------------------------------------------------------------
# 키워드 등급(CandidateMatch.tier)은 «후보를 고르는» 필터로 그대로 둔다. 여기서 바뀌는 것은
# 후보로 올라온 공고의 «점수와 사유»뿐이다.

#: 마지막으로 쪼갠 회사 프로필 문구. 목록 한 번에 공고 100건이 들어오는데, 공고마다 프로필을
#: 다시 쪼개면 같은 일을 100번 한다. 키가 프로필 «내용»이라 회사를 바꿔도 값이 낡지 않는다.
_PHRASE_MEMO: tuple[tuple[tuple[str, ...], ...], tuple[str, ...]] | None = None


def company_phrases(
    *,
    business_domains: list[str] | tuple[str, ...] = (),
    target_clients: list[str] | tuple[str, ...] = (),
    certifications: list[str] | tuple[str, ...] = (),
) -> tuple[str, ...]:
    """회사 프로필을 의미 비교용 문구로 쪼갠다 (마지막 결과 1벌을 재사용한다)."""
    global _PHRASE_MEMO
    key = (tuple(business_domains), tuple(target_clients), tuple(certifications))
    cached = _PHRASE_MEMO
    if cached is not None and cached[0] == key:
        return cached[1]
    phrases = tuple(
        semantic_matcher.profile_phrases(
            business_domains=key[0], target_clients=key[1], certifications=key[2]
        )
    )
    _PHRASE_MEMO = (key, phrases)
    return phrases


def semantic_fit(
    notice: ProcurementNotice, phrases: tuple[str, ...] | None
) -> SemanticFit | None:
    """공고 1건의 의미 유사도. 문구가 없으면 재지 않는다(None).

    텍스트 조립은 `semantic_matcher` 가 단일 출처다 — 여기서 따로 만들지 않는다.
    """
    if not phrases:
        return None
    return semantic_matcher.match(
        notice=semantic_matcher.notice_text(title=notice.title, summary=notice.description),
        phrases=list(phrases),
    )


def _measured(fit: SemanticFit | None) -> float | None:
    """의미 유사도를 «실제로 쟀을 때»만 점수를 돌려준다.

    임베딩을 못 쓰면 `method="KEYWORD"` · `fit_score=None` 이고, 그때는 재지 못한 것이지
    0점이 아니다 (CLAUDE.md §12). 호출부는 지금까지의 규칙 값을 그대로 쓴다.
    """
    if fit is None or fit.method != "EMBEDDING" or fit.fit_score is None:
        return None
    return fit.fit_score


def semantic_used(rec: Recommendation) -> SemanticFit | None:
    """추천등급이 사업영역 점수를 «의미 유사도로» 냈으면 그 결과를, 아니면 None.

    호출부가 method 값을 직접 비교하지 않게 한 곳에 모아 둔다.
    """
    return rec.fit if _measured(rec.fit) is not None else None


# ---------------------------------------------------------------------------
# 항목별 계산
# ---------------------------------------------------------------------------


def _business_fit(
    match: CandidateMatch | None,
    scope: tuple[str, bool] | None = None,
    fit: SemanticFit | None = None,
) -> Component:
    key, label, weight = "business_fit", LABELS["business_fit"], WEIGHTS["business_fit"]
    if match is None:
        # 키워드 판정이 없어도 «의미로 쟀다면» 그 값이 답이다 — 오히려 이럴 때 쓰라고 만든 것이다.
        # 여기서 그냥 미계산으로 돌려보내면, 점수는 안 쓰면서 to_dict() 는 「AI 의미 매칭」이라
        # 적는 어긋난 조합이 나온다(같은 함수의 fit 인자를 무시했기 때문이다).
        measured_only = _measured(fit)
        if measured_only is not None and fit is not None:
            return Component(key, label, weight, measured_only, f"키워드 판정 결과 없음 · {fit.reason}")
        return Component(key, label, weight, None, "키워드 판정 결과가 없습니다.")

    # 개발 키워드도 근거에 포함한다. 빠져 있으면 「마운트 에이전트 **개발**」처럼
    # 개발 낱말로 후보가 된 공고의 사유에 그 근거가 나타나지 않는다.
    matched = [*match.matched_ai, *match.matched_work, *match.matched_dev]
    reason = (
        f"키워드 등급 {tier_label(match.tier)} · 매칭 {', '.join(matched)}"
        if matched
        else f"키워드 등급 {tier_label(match.tier)} · 매칭 없음"
    )

    # 의미 유사도를 쟀으면 그것이 점수가 된다. 「AI」라는 글자가 들어 있는지가 아니라
    # 공고가 요구하는 일이 회사가 하는 일과 얼마나 가까운지를 본 값이다.
    # 키워드 사유는 «지우지 않고» 함께 남긴다 — 담당자가 두 근거를 모두 읽을 수 있어야 한다.
    measured = _measured(fit)
    if measured is not None and fit is not None:
        reason = f"{reason} · {fit.reason}"

    # 비대상 유형인데 교육이 주제로만 언급된 경우 — 제외하지는 않고 강하게 감점한다.
    if scope is not None:
        scope_label, _ = scope
        return Component(
            key, label, weight,
            # 비대상 유형의 상한은 의미 유사도보다 앞선다. 「감리·데이터센터」는 우리가 할 일이
            # 아니라는 판단이고, 문장이 가깝다는 사실이 그 판단을 뒤집지 않는다.
            OUT_OF_SCOPE_TOPIC_SCORE if measured is None else min(measured, OUT_OF_SCOPE_TOPIC_SCORE),
            f"{reason} · 다만 '{scope_label}' 사업으로 보여 감점했습니다"
            " (교육을 직접 수행하는 문구가 없습니다).",
        )

    return Component(
        key, label, weight,
        _TIER_SCORE[match.tier] if measured is None else measured,
        reason,
    )


def _evidence_fit() -> Component:
    """목록 단계에서는 계산하지 않는다 (RFP 파싱 + Evidence 매칭이 필요)."""
    return Component(
        "evidence_fit", LABELS["evidence_fit"], WEIGHTS["evidence_fit"], None,
        "요구사항 정리표를 만든 뒤 계산합니다. 지금은 점수에서 뺐습니다.",
    )


def _schedule_fit(days: float | None, left: int | None = None) -> Component:
    """`left` 는 문장에 적는 남은 날(KST 달력 날짜 차 · 43차 N6 — 같은 카드의 「마감까지 n일」과 같은 값)."""
    key, label, weight = "schedule_fit", LABELS["schedule_fit"], WEIGHTS["schedule_fit"]
    if days is None:
        return Component(key, label, weight, None, "공고에 마감일시가 없습니다.")
    shown = f"{left}일" if left is not None and left >= 0 else f"{days:.0f}일"
    if days >= 21:
        return Component(key, label, weight, 1.0, f"마감까지 {shown} — 여유 있습니다.")
    if days >= 14:
        return Component(key, label, weight, 0.85, f"마감까지 {shown} — 준비 가능합니다.")
    if days >= 7:
        return Component(key, label, weight, 0.6, f"마감까지 {shown} — 착수를 서둘러야 합니다.")
    if days >= 3:
        return Component(key, label, weight, 0.35, f"마감까지 {shown} — 촉박합니다.")
    return Component(key, label, weight, 0.15, f"마감까지 {shown} — 사실상 불가에 가깝습니다.")


def _real_deadline(notice: ProcurementNotice) -> datetime | None:
    """실제 마감 — 입찰 마감 · 참가자격 등록 마감 · 공고문 일정표 마감 중 가장 이른 것(43차 결정 1 · N6)."""
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    stamps = [notice.deadline_at]
    for key in ("qualification_deadline", "schedule_deadline"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            stamps.append(g2b_mapper.parse_datetime(value) or _iso(value.strip()))
    real = [d for d in stamps if d is not None]
    return min(real) if real else None


def _iso(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=KST)


def _budget_fit(budget: int | None, capacity: int | None = None) -> Component:
    """예산 적합도.

    `capacity` 는 **회사가 적어 둔** 혼자 맡을 수 있는 최대 사업비(`delivery_capacity.budget_ceiling_krw`)다.
    예전에는 합성 상수 300,000,000 원이 회사와 무관하게 쓰였고, 그 값이 실제 공고의 사유
    문장에 「단독 수행 검토 범위(300,000,000원) 안입니다」로 그대로 나갔다 (ISSUE-030).
    회사가 적지 않은 숫자를 회사의 판단인 것처럼 말하지 않는다.

    적힌 값이 없으면 점수를 내지 않는다 (`None`). 0 점이 아니다 — CLAUDE.md §12,
    「미확인 항목은 score=null 로 두고 0점으로 단정하지 않는다」.
    """
    key, label, weight = "budget_fit", LABELS["budget_fit"], WEIGHTS["budget_fit"]
    if budget is None or budget <= 0:
        return Component(key, label, weight, None, "공고에 예산·기초금액이 없습니다.")
    if capacity is None or capacity <= 0:
        return Component(
            key, label, weight, None,
            f"{won(budget)} — 회사가 혼자 맡을 수 있는 최대 사업비를 아직 적지 않아 판정하지 않았습니다.",
        )
    if budget < _SMALL_BUDGET:
        return Component(
            key, label, weight, 0.5,
            f"{won(budget)} — 소액이라 수익성 확인이 필요합니다.",
        )
    budget_text, capacity_text = won_pair(budget, capacity)  # 반올림하면 같아지는 금액은 정확히(34차 R33-04)
    if budget <= capacity:
        return Component(
            key, label, weight, 1.0,
            f"{budget_text} — 회사가 적은 최대 사업비({capacity_text}) 안입니다.",
        )
    if budget <= capacity * 2:
        return Component(
            key, label, weight, 0.5,
            f"{budget_text} — 회사가 적은 최대 사업비({capacity_text})보다 큽니다(함께 참가할 수 있는지는 참가 가능 여부의 사업 규모 줄).",
        )
    return Component(
        key, label, weight, 0.2,
        f"{won(budget)} — 회사가 적은 최대 사업비({won(capacity)})를 크게 넘습니다.",
    )


def _strategic_fit(region: str | None, preferred: tuple[str, ...] | None = None) -> Component:
    """지역 적합도.

    나라장터 응답의 `rgnLmtBidLocplcJdgmBssNm` 는 지역 «이름»이 아니라 «판단 기준의 이름»이다
    (실측: 캐시 76건 중 52건이 「본사또는참여지사소재지」, 1건이 「본사소재지」, 23건이 빈 값 —
    지역 이름은 0건). 그 값을 지역으로 읽으면 「본사또는참여지사소재지 — 우선 지역이 아닙니다」라는
    말이 되고, 53건이 근거 없이 0.25 로 깎였다. 지역 이름이 아니면 «표기 없음»과 같게 다룬다.
    """
    key, label, weight = "strategic_fit", LABELS["strategic_fit"], WEIGHTS["strategic_fit"]
    text = (region or "").strip()
    if not text:
        return Component(
            key, label, weight, 0.7,
            "공고에 지역제한 표기가 없습니다 — 제한 없음으로 보고 계산했습니다.",
        )
    # 우선 지역은 «선택한 회사의 프로필»에서 온다. 예전에는 광주·전남이 하드코딩돼 있어
    # 다른 지역 회사를 골라도 광주 공고가 만점을 받았다 (ISSUE-030).
    tokens = preferred if preferred is not None else (() if get_settings().neutral_company_defaults else _PREFERRED_REGION_TOKENS)
    if tokens and any(token in text for token in tokens):
        return Component(key, label, weight, 1.0, f"{text} — 회사 우선 활동 지역입니다.")
    if any(token in text for token in _NATIONWIDE_TOKENS):
        return Component(key, label, weight, 0.7, f"{text} — 지역제한이 없습니다.")
    if not tokens:
        # 회사가 활동 지역을 적지 않았다. 「우선 지역이 아니다」라고 깎을 근거가 없다.
        return Component(
            key, label, weight, None,
            f"{text} — 회사 프로필에 활동 지역이 없어 판정하지 않았습니다.",
        )
    if g2b_mapper.region_name(text) is None:
        # 지역 이름도 「전국」도 아니면 판단 기준의 «이름»이다. 그것을 지역으로 읽고
        # 「우선 지역이 아닙니다」라고 깎지 않는다 — 어느 지역인지 아직 모르는 것이다.
        return Component(
            key, label, weight, 0.7,
            f"「{text}」는 지역제한 판단 기준이고 대상 지역 이름이 아닙니다 — 원문에서 확인해야 합니다.",
        )
    return Component(key, label, weight, 0.25, f"{text} — 우선 지역이 아닙니다.")


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def grade_of(score: float) -> Grade:
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C:
        return "C"
    return "D"


def evaluate(
    notice: ProcurementNotice,
    match: CandidateMatch | None = None,
    *,
    now: datetime | None = None,
    preferred_regions: tuple[str, ...] | None = None,
    capacity_krw: int | None = None,
    phrases: tuple[str, ...] | None = None,
) -> Recommendation:
    """공고 1건의 추천등급을 계산한다.

    계산한 항목의 가중치 합으로 나눠 정규화하므로, 데이터가 없는 항목이
    0점으로 잡혀 등급을 끌어내리지 않는다.

    `preferred_regions`·`capacity_krw` 는 **선택한 회사**의 값이다. 넘기지 않으면
    지역은 예전의 합성 기본값을 쓰고(호출처를 한 번에 다 바꾸지 않기 위한 호환 계층),
    규모는 판정하지 않는다 — 회사가 적지 않은 숫자를 회사의 판단처럼 말하지 않는다.

    `phrases` 는 `company_phrases()` 로 쪼갠 회사 프로필 문구다. 넘기면 사업영역 적합도를
    의미 유사도로 재고, 넘기지 않거나 임베딩을 못 쓰면 지금까지의 키워드 규칙 그대로다.
    """
    current = _now(now)
    real_deadline = _real_deadline(notice)
    days = days_until(real_deadline, current)

    # 샘플에듀가 수행하지 않는 사업 유형인지 먼저 본다 (감리·데이터센터·시스템 구축 등).
    scope = out_of_scope_reason(_notice_text(notice))
    fit = semantic_fit(notice, phrases)

    components = [
        # 비대상 유형이면 교육이 주제로만 언급됐든(scope[1] is True)
        # 아예 언급이 없든 똑같이 감점한다. 언급이 없는 쪽이 더 나쁘므로
        # 그쪽만 감점에서 빠지면 안 된다.
        _business_fit(match, scope, fit),
        _evidence_fit(),
        _schedule_fit(days, calendar_days_left(real_deadline, current)),
        _budget_fit(notice.budget, capacity_krw),
        _strategic_fit(notice.region, preferred_regions),
    ]

    computed = [c for c in components if c.computed]
    total_weight = sum(c.weight for c in computed)
    score = (
        sum(c.weight * (c.score or 0.0) for c in computed) / total_weight
        if total_weight
        else 0.0
    )

    # 마감이 지났으면 점수와 무관하게 No-Go다 (CLAUDE.md 12).
    if days is not None and days < 0:
        return Recommendation(
            grade="NO_GO",
            score=score,
            components=components,
            gate_reason=f"입찰 마감이 {abs(days):.0f}일 지났습니다. 신규 참여가 불가합니다.",
            fit=fit,
        )

    # 교육 문구가 전혀 없는 비대상 사업 유형은 점수와 무관하게 후순위로 내린다.
    # 키워드만으로는 'AI ... 위탁감리'가 A등급에 올라온다.
    if scope is not None and not scope[1]:
        return Recommendation(
            grade="D",
            score=score,
            components=components,
            gate_reason=(
                # 「회사 사업영역과 맞지 않아」는 감리 · 연구 회사에 거짓이다 — 점수 이유와 같은 말로(32차 뜻 틀린 곳 #2)
                f"'{scope[0]}' 사업으로 보이고 교육 수행 문구가 없어 기본 규칙(AI · 교육 · 컨설팅 · 개발 기준)으로 "
                "뒤로 보냈습니다 — 회사 사업영역과 다르면 원문을 확인하세요."
            ),
            out_of_scope=True,
            fit=fit,
        )

    grade = grade_of(score)

    # 개발만 있는 공고는 A 를 주지 않는다 (ISSUE-005).
    #
    # 실측에서 A등급 1·2위가 「소방공무원 AI 다중모달 심리진단 **시스템 개발** 용역」과
    # 「마운트 에이전트 개발을 위한 **DB 구축** 용역」이었고, 정작 교육 공고(가천대 피지컬 AI)는
    # B 였다. 샘플에듀의 주된 일은 AI 교육·컨설팅이다.
    #
    # 여기서 «배제»하지는 않는다. 개발 공고를 사업영역 밖으로 되돌리는 것은 앞선 판단
    # (`_OUT_OF_SCOPE_RULES` 주석 — 「규모가 커서 어려운 것과 사업영역이 아닌 것은 다른 문제」)을
    # 뒤집는 일이고, 개발 인력이 검토할 만한 공고를 목록에서 잃는다. 상한만 B 로 둔다.
    if grade == "A" and development_only(notice):
        return Recommendation(
            grade="B",
            score=score,
            components=components,
            gate_reason=(
                "개발·구축 용역으로 보이며 교육 수행 문구가 없습니다. 원본 추천등급만 B 로 두었습니다"
                "(회사 기준 검토 순서와는 따로 · 43차 M4) — 개발 참여를 검토한다면 원문을 확인하세요."
            ),
            fit=fit,
        )

    return Recommendation(grade=grade, score=score, components=components, fit=fit)
