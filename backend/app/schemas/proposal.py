"""제안서 초안 스키마.

`schemas/demo.py`의 ProposalSection / ProposalSentence와 **필드 호환**을 유지한다
(기존 프론트엔드가 그대로 렌더링되어야 한다). 통계 필드는 뒤에 덧붙이기만 한다.

원칙 (CLAUDE.md 4-G, 11):
- 문장은 요구사항 원문 또는 채택된 Evidence 원문에서만 나온다.
- 근거가 없으면 충족을 단정하지 않고 `확인 필요`(needs_review=True)로 남긴다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GroundingType = Literal["RFP_GROUNDED", "COMPANY_EVIDENCE_GROUNDED", "AI_SUGGESTION"]
GenerationMethod = Literal["RULE", "LLM"]


class EvidenceCandidate(BaseModel):
    """요구사항 ↔ 회사자료 연결 1건.

    실제 Evidence 매칭기는 팀원이 만든다. 이 서비스는 아래 형태만 소비하므로
    매칭기가 준비되면 `generate_section(evidence_links=...)`로 넘기기만 하면 된다.
    """

    requirement_id: str = Field(pattern=r"^REQ-\d{3}$")
    evidence_id: str
    document_name: str
    source_text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    similarity_score: float | None = Field(default=None, ge=0, le=1)
    selected: bool = False


class ProposalSentence(BaseModel):
    """제안서 문장 1개. 근거 유형과 원본 요구사항/Evidence를 항상 함께 보관한다."""

    id: str
    text: str = Field(min_length=1)
    grounding_type: GroundingType
    requirement_id: str | None = None
    #: 이 문장이 대응하는 요구사항의 «안정 ID». REQ 번호는 재추출에서 밀리므로
    #: 연결의 진짜 근거는 이쪽이다. 옛 저장본에는 없어 None 을 허용한다.
    stable_requirement_id: str | None = None
    #: 마이그레이션으로 REQ 번호를 고쳤다면 고치기 «전» 번호. 기록을 지우지 않는다.
    original_requirement_id: str | None = None
    evidence_id: str | None = None
    needs_review: bool = False
    #: AI 가 다듬기 전 규칙 초안의 근거 유형(44차 M5 · E2E-04). 있으면 `grounding_type` 은 AI_SUGGESTION 이고 화면은
    #: 「AI 다듬음 — 근거: <원 근거>」, 내려받기는 「AI 덧붙임(다듬음 · 원 근거: …)」. 옛 저장본에는 없다.
    refined_from: GroundingType | None = None


class ProposalSection(BaseModel):
    """생성된 핵심 섹션 1개.

    id / title / sentences는 demo.ProposalSection과 동일한 형태이며,
    그 뒤 필드는 생성 근거를 설명하기 위한 부가 정보다(프론트는 무시해도 된다).
    """

    id: str
    title: str
    sentences: list[ProposalSentence]

    procurement_id: str = ""
    generated_at: datetime | None = None
    generation_method: GenerationMethod = "RULE"
    # 커버리지를 지어내지 않는다. 문장이 만들어지지 않은 요구사항은 그대로 드러낸다.
    mandatory_total: int = 0
    requirements_with_sentence: int = 0
    requirements_without_sentence: list[str] = Field(default_factory=list)
    evidence_grounded_count: int = 0
    rfp_grounded_count: int = 0
    needs_review_count: int = 0
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False
    # 어떤 회사의 어떤 자료를 몇 건 썼는가 (evidence_service.scope_info). 없으면 매칭을 돌리지 않은 결과.
    evidence_summary: dict | None = None
    # --- 어느 요구사항 집합을 보고 만들었는가 --------------------------------
    #
    # 이것이 없으면 2026-09-04 제안서를 2026-09-10 요구사항과 곧바로 견주게 된다.
    # 실측: 필수 32건 기준으로 만든 19문장을 55건 집합과 비교해 26건이 한꺼번에
    # 「미반영 HIGH」로 올라왔다. 늘어난 요구사항을 제안서 결함으로 읽은 것이다.
    requirement_set_id: str | None = None
    requirement_set_hash: str | None = None
    #: 제안서 자신의 판 번호. 새 요구사항으로 다시 만들면 오르고, 이전 판은 지우지 않는다.
    proposal_version: int = Field(default=1, ge=1)
    #: 어느 판에서 이어 만들었는가 (처음 생성이면 None).
    source_proposal_version: int | None = None
    #: 대응한 요구사항의 «안정 ID» 목록. REQ 번호는 밀리므로 이쪽을 기록한다.
    covered_requirement_ids: list[str] = Field(default_factory=list)
    #: 생성 주체. RULE/LLM 은 시스템, HUMAN 은 사람이 고친 판.
    author: str = "RULE"
    #: 사람이 문장을 고쳤는가. True 면 재생성이 자동으로 덮어쓰지 않는다.
    edited_by_human: bool = False
    #: 본문 해시 — 감사 결과가 이 초안을 본 것인지 대조하는 값.
    proposal_hash: str | None = None


class ProposalGenerateRequest(BaseModel):
    procurement_id: str = Field(min_length=1, max_length=64)
    section_title: str | None = Field(default=None, min_length=1, max_length=120)
    # 다회사 구조: 생략하면 호환 계층이 기본 조직·범위를 채운다. 새 호출은 명시한다.
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")


# --------------------------------------------------------------------------
# LLM 구조화 출력용 (문장 텍스트만 다듬는다. 근거 유형·확인필요는 규칙이 정한다)
# --------------------------------------------------------------------------


class GeneratedSentence(BaseModel):
    requirement_id: str
    text: str = Field(min_length=1)
    uses_evidence: bool = False
    needs_review: bool = False


class GeneratedSectionDraft(BaseModel):
    sentences: list[GeneratedSentence]
