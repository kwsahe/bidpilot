"""AI Auditor 스키마.

`schemas/demo.py`의 AuditFinding/AuditRun 필드명을 그대로 유지한다(프론트가 이미 그 형태를
렌더링한다). 여기서는 실데이터 검사에 필요한 필드만 **추가**한다.

- AuditFinding: (기존) id, finding_type, severity, requirement_id, evidence_id, sentence_id,
  source_page, source_text, proposal_text, recommendation
  (추가) detected_by, score
- AuditRun: (기존) id, findings + (추가) procurement_id, created_at, coverage, counts 등
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FindingType = Literal[
    "missing_requirement",
    "number_mismatch",
    "unsupported_claim",
    "unchecked_condition",
    "missing_document",
    # 평가본 공고(입찰 제안서 초안 형식이 평가본)에서 올린 글에 회사 식별 낱말이 남음(2.10.0 T8 · blind6 — 값은 싣지 않음)
    "blind_identity",
]
# 심각도. 「제출에 실제로 어떤 영향을 주는가」로 정한다 — 미반영이면 무조건 high 가 아니다.
#   critical = 참가 자체를 막는다 (자격 미달·설명회 필참·등록 마감)
#   high     = 평가 배점·필수 과업·필수 제출물에 직접 걸린다
#   medium   = 보완 가능한 부족
#   low      = 계약 일반조건처럼 본문에 다시 적을 필요가 없는 준수사항
#   info     = 참고. 사람이 볼 필요는 있으나 결함이 아니다
# 옛 저장 파일에는 high/medium/low 만 있으므로 그대로 읽힌다.
Severity = Literal["critical", "high", "medium", "low", "info"]
# 이 finding을 만든 계층. RULE = 결정론적 규칙, AI_EXTRACTION = LLM 2차 판단.
DetectedBy = Literal["RULE", "AI_EXTRACTION"]
# 요구사항별 최종 대응 상태 (Requirement.status와 같은 어휘를 쓴다).
RequirementAuditStatus = Literal["matched", "partial", "unmatched", "check"]


class ProposalSentenceRef(BaseModel):
    """초안에서 잘라낸 문장 1개. text는 인용을 위해 원문 그대로 보존한다."""

    id: str
    index: int = Field(ge=0)
    text: str = Field(min_length=1)


class AuditFinding(BaseModel):
    id: str
    finding_type: FindingType
    severity: Severity
    requirement_id: str | None = None
    evidence_id: str | None = None
    sentence_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_text: str | None = None
    proposal_text: str | None = None
    recommendation: str = Field(min_length=1)
    # --- 추가 필드 (기존 프론트는 무시해도 동작한다) ---
    #: 이 요구사항에 «어디서» 답하는가. 심각도를 정한 근거이자 화면의 묶음 축이다.
    response_scope: str | None = None
    #: 같은 원인에서 나온 발견을 묶는 키. 화면이 REQ 번호 26개를 한 줄로 늘어놓지 않게 한다.
    group_key: str | None = None
    group_label: str | None = None
    #: 묶음을 보여주는 순서(작을수록 먼저). 순서를 화면마다 따로 정하면 같은 결과가
    #: 화면에 따라 다른 순서로 보인다 — 무엇이 먼저인지는 백엔드가 정한다
    #: (auditor_service._GROUP_RANK). 기본 80 = 「나머지」이므로 이 필드가 없던
    #: 옛 저장 파일도 그대로 읽힌다.
    group_rank: int = Field(default=80, ge=0)
    detected_by: DetectedBy = "RULE"
    score: float | None = Field(default=None, ge=0)
    #: 해결 기록의 키(`finding_resolution_service.resolution_key`) — 응답 때 **옛 글을 새 말로 바꾸기 전** 원문으로 만든다(33차 R32-12).
    #: 저장 파일에는 없다(None). 화면은 이 값이 있으면 그대로 쓴다.
    resolution_key: str | None = None


class AuditCoverage(BaseModel):
    """필수 요구사항 기준 커버리지. 모든 값은 실행 시점 계산값이다(하드코딩 금지)."""

    total: int = Field(ge=0)
    covered: int = Field(ge=0)
    partial: int = Field(ge=0)
    missing: int = Field(ge=0)
    missing_requirement_ids: list[str] = Field(default_factory=list)
    partial_requirement_ids: list[str] = Field(default_factory=list)
    # 추출 상한에 잘려 **검사 대상에서 빠진** 요구사항이 있으면 True.
    # 이때 total은 문서 전체가 아니라 검사한 범위이므로 비율을 그대로 읽으면 안 된다.
    truncated: bool = False
    # --- 분모를 화면 전체가 같이 쓰게 한다 ---------------------------------
    #
    # 예전에는 total 이 «필수만»(55)인데 화면 다른 곳은 «전체»(56)를 적어, 두 숫자가
    # 설명 없이 섞였다. 이제 네 가지를 한 곳에서 내려보낸다.
    total_all: int = Field(default=0, ge=0)
    mandatory_total: int = Field(default=0, ge=0)
    optional_or_conditional_total: int = Field(default=0, ge=0)
    #: 제안서 본문 대응 대상이 아닌 것 (계약 준수·참고·자격 증빙·제출 체크리스트 등).
    not_proposal_body_total: int = Field(default=0, ge=0)
    #: 제안서 본문 Coverage — 분모가 total 과 다르다.
    proposal_body: dict[str, int] = Field(default_factory=dict)
    #: 참가자격 Coverage (확인 완료/확인 필요/불충족/해당 없음).
    eligibility: dict[str, int] = Field(default_factory=dict)
    #: 제출 체크리스트 Coverage (준비 완료/미완료/확인 필요).
    submission: dict[str, int] = Field(default_factory=dict)
    # 상한 적용 전 후보 수 (없으면 None). "226건 중 120건만 검사" 표기에 쓴다.
    candidate_count: int | None = Field(default=None, ge=0)


class RequirementAuditState(BaseModel):
    """요구사항 1건의 검사 결과. LLM이 뒤집은 판정도 근거와 함께 남긴다."""

    requirement_id: str
    requirement_type: Literal["mandatory", "optional"]
    status: RequirementAuditStatus
    score: float = Field(ge=0)
    matched_sentence_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    method: Literal["RULE", "AI_EXTRACTION"] = "RULE"
    reason: str | None = None


class AuditRun(BaseModel):
    id: str
    procurement_id: str
    created_at: datetime
    coverage: AuditCoverage
    counts: dict[str, int] = Field(default_factory=dict)
    findings: list[AuditFinding] = Field(default_factory=list)
    # --- 재현·설명용 부가 정보 ---
    sentence_count: int = Field(default=0, ge=0)
    llm_used: bool = False
    llm_note: str | None = None
    requirement_states: list[RequirementAuditState] = Field(default_factory=list)
    sentences: list[ProposalSentenceRef] = Field(default_factory=list)
    source_document: str | None = None
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False
    # --- 무엇을 보고 검사했는가 ---------------------------------------------
    audit_version: int = Field(default=1, ge=1)
    requirement_set_id: str | None = None
    requirement_set_hash: str | None = None
    proposal_version: int | None = None
    proposal_hash: str | None = None
    #: "standard" = 최신 초안 검사. "change_impact" = 이전 초안을 최신 요구사항과 견주기.
    #: 둘을 섞어 보여주면 담당자가 「지금 제안서의 결함」과 「요구사항이 늘어난 것」을
    #: 구분할 수 없다.
    mode: Literal["standard", "change_impact"] = "standard"
    #: 검사한 초안이 이전 요구사항 집합 기준인가.
    stale_requirements: bool = False


class AuditRunRequest(BaseModel):
    procurement_id: str = Field(min_length=1, max_length=64)
    proposal_text: str = Field(min_length=1, max_length=400_000)
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")
    # 기본은 LLM 2차 판단 사용(키가 없으면 조용히 건너뛴다).
    use_llm: bool = True
    #: "standard" = 최신 초안 검사. 초안이 이전 요구사항 집합 기준이면 409로 막는다.
    #: "change_impact" = 이전 초안을 최신 요구사항과 «일부러» 견주기. 담당자가 명시할 때만.
    mode: Literal["standard", "change_impact"] = "standard"
