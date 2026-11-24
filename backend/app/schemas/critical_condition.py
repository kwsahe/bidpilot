"""Critical Condition — 참가 자체를 막거나 담당자의 행동이 필요한 조건.

요구사항 목록(Requirement Matrix)과는 다른 축이다. 요구사항은 "제안서가 무엇을 담아야 하는가"이고,
Critical Condition은 "이 공고에 들어가려면 무엇을 먼저 해야 하는가"다 — 설명회 필참, 사전등록,
지역제한, 입찰보증금, 방문제출 같은 것들.

원칙
- 미해결 BLOCKER가 있으면 GO 결정을 막는다 (services/decision_service.py).
- 규칙이 확신하지 못하면 CHECK로 둔다. 시스템이 CLEARED로 바꾸는 일은 없다 — 사람만 한다.
- 모든 판정에 원문(source_text·page) 또는 공고 필드 근거를 남긴다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.text_fields import PersonName

from app.services.performance_match_service import PerformanceMatchReport

ConditionType = Literal[
    "briefing_attendance",  # 설명회 필참
    "pre_registration",  # 사전등록
    "region_restriction",  # 지역제한
    "industry_license",  # 업종·면허
    "direct_production",  # 직접생산확인
    "sme_certificate",  # 중소기업확인서
    "performance_record",  # 실적/금액 요건
    "staffing",  # 인력 요건
    "joint_venture",  # 공동수급
    "subcontract",  # 하도급
    "bid_bond",  # 입찰보증금
    "onsite_submission",  # 방문제출
    "copies",  # 부수
    "file_format",  # 파일형식
    "separate_price_tech",  # 가격·기술 분리
    "presentation",  # 발표·시연
    "security_pledge",  # 보안서약
    "separate_procedure",  # 별도 절차
    "attendance_certificate",  # 참석확인서
    "mandatory_form",  # 서식 의무
    "deadline_passed",  # 마감 경과 (공고 필드)
    "eligibility_fail",  # 자격 규칙 FAIL (공고 필드)
    "other",
]

# BLOCKER : 해결 전에는 GO 불가
# ACTION  : 담당자의 행동(등록·서류 준비·참석)이 필요
# CHECK   : 규칙이 확신하지 못함 — 사람이 원문을 확인
# CLEARED : 담당자가 해결 처리 (시스템은 절대 자동으로 만들지 않는다)
# INFO    : 알아 두어야 할 조건 (행동 불필요)
ConditionStatus = Literal["BLOCKER", "ACTION", "CHECK", "CLEARED", "INFO"]
ConditionSeverity = Literal["high", "medium", "low"]
ConditionMethod = Literal["RULE", "AI_EXTRACTION", "HUMAN"]

# 조건 id 를 무엇에서 뽑았는가.
#   stable_id      : 요구사항의 내용 기반 영구 식별자 — REQ 번호가 밀려도 같은 조건은 같은 id
#   requirement_id : REQ 번호 (옛 방식). 요구사항을 다시 뽑으면 번호가 밀려 id 가 바뀐다
#   source_text    : 요구사항에 붙지 않은 조건(자격 규칙 FAIL 등)
ConditionIdBasis = Literal["stable_id", "requirement_id", "source_text"]

# 저장된 보고서가 «지금 요구사항 집합» 기준인가.
#   current : 저장 당시 해시 == 지금 해시
#   stale   : 다르다 — 요구사항을 다시 뽑았으므로 조건도 다시 탐지해야 한다
#   unknown : 한쪽 해시가 없어 대조할 수 없다. «최신»이라고 단정하지 않는다
ConditionFreshness = Literal["current", "stale", "unknown"]

CONDITION_TYPE_LABEL: dict[str, str] = {
    "briefing_attendance": "설명회 필참",
    "pre_registration": "사전등록",
    "region_restriction": "지역제한",
    "industry_license": "업종·면허",
    "direct_production": "직접생산확인",
    "sme_certificate": "중소기업확인서",
    "performance_record": "실적·금액 요건",
    "staffing": "인력 요건",
    "joint_venture": "공동수급",
    "subcontract": "하도급",
    "bid_bond": "입찰보증금",
    "onsite_submission": "방문제출",
    "copies": "제출 부수",
    "file_format": "파일형식",
    "separate_price_tech": "가격·기술 분리",
    "presentation": "발표·시연",
    "security_pledge": "보안서약",
    "separate_procedure": "별도 절차",
    "attendance_certificate": "참석확인서",
    "mandatory_form": "서식 의무",
    "deadline_passed": "마감 경과",
    # 영문 판정값을 화면에 내지 않는다 (규칙 11 · 0922 §4-D-6).
    "eligibility_fail": "자격 규칙 불가",
    "other": "기타 조건",
}


class CriticalCondition(BaseModel):
    id: str
    procurement_id: str
    condition_type: ConditionType
    title: str
    content: str = Field(min_length=1)
    severity: ConditionSeverity
    status: ConditionStatus
    # 규칙이 처음 매긴 상태. 사람이 status를 바꿔도 여기엔 남는다.
    detected_status: ConditionStatus
    due_at: datetime | None = None
    action_required: bool = False
    owner: str | None = Field(default=None, max_length=60)
    requirement_id: str | None = None
    # --- 조건 id 의 신원 -------------------------------------------------
    #
    # 예전에는 id 를 REQ 번호로 만들었다. 요구사항을 다시 뽑으면 문서 중간에 항목 하나가
    # 끼는 것만으로 뒤 번호가 전부 밀리는데, 그때 사람이 CLEARED 로 표시해 둔 기록은
    # 옛 번호에 남아 엉뚱한 조건에 붙거나 아예 사라졌다(그러면 BLOCKER 가 화면에서
    # 없어진 것처럼 보인다). 그래서 요구사항의 내용 기반 stable_id 를 우선 쓴다.
    #
    # `legacy_ids` 는 옛 방식으로 계산한 같은 조건의 id 다. 사람이 남긴 override 를
    # 옛 id 로도 찾아보기 위한 이행 경로이며, 비어 있을 수 있다.
    id_basis: ConditionIdBasis = "source_text"
    legacy_ids: list[str] = Field(default_factory=list)
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = None
    # 공고 API 필드로 판정한 경우 "field=value" 형태의 근거.
    source_field: str | None = None
    extraction_method: ConditionMethod = "RULE"
    # 사람이 상태를 바꾼 기록
    resolved_at: datetime | None = None
    resolved_by: str | None = Field(default=None, max_length=60)
    resolution_note: str | None = Field(default=None, max_length=2000)
    # 이 요청을 보낸 **인증된 계정** (S12). 위 이름은 본문에 실려 온 «주장»이고, 이것은
    # 서명된 신원에서 온 사실이다. 둘은 다를 수 있다 — 담당자가 동료 이름을 적어 두는 일이
    # 실제로 있다. 인증이 꺼진 로컬에서는 None 이다(없는 것을 이름으로 채우지 않는다).
    recorded_by: str | None = Field(default=None, max_length=64)
    # 실적 조건(performance_record)에만: 회사 실적 원장과 대조한 힌트. 원장이 없으면 None. PASS가 아니다.
    ledger_match: PerformanceMatchReport | None = None


class ConditionCounts(BaseModel):
    total: int = Field(ge=0)
    blocker: int = Field(ge=0)
    action: int = Field(ge=0)
    check: int = Field(ge=0)
    cleared: int = Field(ge=0)
    info: int = Field(ge=0)


class ConditionGate(BaseModel):
    """GO 결정 가능 여부. 미해결 BLOCKER가 하나라도 있으면 막는다."""

    can_go: bool
    reason: str
    blocker_ids: list[str] = Field(default_factory=list)


class CriticalConditionReport(BaseModel):
    procurement_id: str
    detected_at: datetime
    method: ConditionMethod = "RULE"
    notice_available: bool
    requirements_available: bool
    eligibility_used: bool
    counts: ConditionCounts
    gate: ConditionGate
    conditions: list[CriticalCondition]
    # --- 신선도: 이 보고서가 «지금 요구사항 집합» 기준인가 -------------------
    #
    # 조건은 요구사항에서 탐지한다. 요구사항을 다시 뽑았는데 조건 보고서가 예전 것이면
    # 화면은 옛 판정을 최신인 양 보여준다. 그것을 알 수 있게 탐지 시점의 집합 해시를
    # 함께 적고, 읽을 때 지금 파일의 해시와 대조한다.
    #
    # stale 이어도 조건을 감추지 않는다 — 감추면 지금보다 나빠진다. 상태만 정직하게
    # 내려보내고 «다시 탐지» 여부는 사람이 정한다.
    requirement_set_hash: str | None = None
    requirement_set_id: str | None = None
    #: 읽는 시점 요구사항 파일의 해시 (응답용, 저장값과 대조 대상). 파일이 없으면 None.
    current_requirement_set_hash: str | None = None
    freshness: ConditionFreshness = "unknown"
    #: 「지금 집합 기준임이 확인되지 않았다」. unknown 도 True 다 — 모르는 것을 최신이라 하지 않는다.
    stale: bool = True
    stale_reason: str | None = None
    schema_version: int = 2
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False


class ConditionDetectRequest(BaseModel):
    procurement_id: str = Field(min_length=1, max_length=64)
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")
    # 마감 판정 기준 시각. 생략하면 현재.
    as_of: datetime | None = None


class ConditionUpdateRequest(BaseModel):
    """담당자가 조건 상태를 바꾼다. CLEARED는 사람만 만들 수 있다."""

    status: Literal["BLOCKER", "ACTION", "CHECK", "CLEARED", "INFO"]
    reviewer: PersonName
    note: str | None = Field(default=None, max_length=2000)
    owner: PersonName | None = None
