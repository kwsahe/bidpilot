"""대시보드 시연용 합성 시나리오 스키마.

Semantic Matching / Eligibility / Evidence Mapping / Proposal / Auditor는 아직 실제 구현 전이다.
이 모델들은 docs/data_model.md 초안을 따르며, 실제 서비스가 구현되면 같은 형태의 실데이터로 교체한다.
"""

from typing import Literal

from pydantic import BaseModel, Field

EligibilityStatus = Literal["PASS", "CHECK", "FAIL"]
EligibilityMethod = Literal["RULE", "AI_EXTRACTION", "HUMAN"]
GroundingType = Literal["RFP_GROUNDED", "COMPANY_EVIDENCE_GROUNDED", "AI_SUGGESTION"]
FindingType = Literal[
    "missing_requirement",
    "number_mismatch",
    "unsupported_claim",
    "unchecked_condition",
    "missing_document",
]
Severity = Literal["high", "medium", "low"]


class SemanticMatch(BaseModel):
    fit_score: float = Field(ge=0, le=1)
    label: str
    matched_domains: list[str]
    reason: str
    demo: Literal[True] = True


class EligibilityResult(BaseModel):
    rule_id: str
    label: str
    status: EligibilityStatus
    method: EligibilityMethod
    source: str
    reason: str
    requirement_id: str | None = None


class EvidenceDocument(BaseModel):
    id: str
    document_name: str
    doc_type: str
    page: int | None = Field(default=None, ge=1)
    source_text: str = Field(min_length=1)
    synthetic: Literal[True] = True


class EvidenceLink(BaseModel):
    evidence_id: str
    requirement_id: str
    similarity_score: float = Field(ge=0, le=1)
    selected: bool
    note: str | None = None


class ProposalSentence(BaseModel):
    id: str
    text: str = Field(min_length=1)
    grounding_type: GroundingType
    requirement_id: str | None = None
    evidence_id: str | None = None
    needs_review: bool = False


class ProposalSection(BaseModel):
    id: str
    title: str
    sentences: list[ProposalSentence]


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


class AuditRun(BaseModel):
    id: str
    findings: list[AuditFinding]


class DemoCosmosScenario(BaseModel):
    procurement_id: str
    source: Literal["demo_synthetic"]
    note: str
    semantic_match: SemanticMatch
    eligibility: list[EligibilityResult]
    evidence_documents: list[EvidenceDocument]
    evidence_links: list[EvidenceLink]
    proposal: ProposalSection
    audit: AuditRun
