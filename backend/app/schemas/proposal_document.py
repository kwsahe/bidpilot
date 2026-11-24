"""제안서 전체 초안 스키마 (섹션 여러 개).

기존 `ProposalSection`(핵심 섹션 1개)은 그대로 두고, 그것을 여러 개 묶은 형태다.
데모 동선은 핵심 섹션 1개를 계속 쓰고, 이 문서는 "결과물"로 넘길 때 쓴다.

원칙은 같다 (CLAUDE.md 11, 4-G)
- 요구사항이 없는 섹션은 만들지 않는다. 빈 목차를 채우려고 문장을 지어내지 않는다.
- 근거 없는 문장은 「확인 필요」로 남긴다.
- 완성본이 아니라 초안이며, 확정은 사람이 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.proposal import GenerationMethod, ProposalSection


class ProposalDocument(BaseModel):
    """제안서 전체 초안. 섹션은 요구사항 카테고리를 목차 순서로 묶어 만든다."""

    id: str
    procurement_id: str
    title: str
    sections: list[ProposalSection] = Field(default_factory=list)
    generated_at: datetime | None = None
    generation_method: GenerationMethod = "RULE"

    # 전체 합계 — 섹션 값을 더한 것이며 지어내지 않는다.
    mandatory_total: int = 0
    requirements_with_sentence: int = 0
    requirements_without_sentence: list[str] = Field(default_factory=list)
    evidence_grounded_count: int = 0
    rfp_grounded_count: int = 0
    needs_review_count: int = 0
    # 어떤 카테고리가 어느 섹션으로 갔는지 (목차를 지어내지 않았음을 보이기 위해).
    section_categories: dict[str, list[str]] = Field(default_factory=dict)
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False
    evidence_summary: dict | None = None
    #: 사업계획서 작성 페이지(Claude)에서만 — AI 다듬기가 실패한 섹션 수와 첫 사유 · 있던 AI 초안을 지켰는가 (28차 검수 R1-01)
    llm_note: str | None = None
    kept_llm_draft: bool = False
    #: 이 판이 저장됐는가 — 합성 데모 공고의 AI 판은 저장하지 않는다(화면은 그 판의 내려받기를 숨긴다 · 30차 R29-03).
    stored: bool = True
    # 섹션과 같은 출처 기록 (schemas/proposal.py 의 설명 참고).
    requirement_set_id: str | None = None
    requirement_set_hash: str | None = None
    proposal_version: int = Field(default=1, ge=1)
    source_proposal_version: int | None = None
    covered_requirement_ids: list[str] = Field(default_factory=list)
    author: str = "RULE"
    edited_by_human: bool = False
    proposal_hash: str | None = None


class ProposalDocumentRequest(BaseModel):
    procurement_id: str = Field(min_length=1, max_length=64)
    use_llm: bool = True
    #: 사업계획서 작성 페이지(/plan)만 참을 보낸다 — CLI 전용 문(28차 §3-D). 대시보드 6단계는 보내지 않는다.
    use_claude: bool = False
    #: 그 단추의 쓰는 이 (29차 §3-A) — claude · codex.
    writer: Literal["claude", "codex"] = "claude"
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")
