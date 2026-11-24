"""담당자 최종 검토(Human Review) 스키마.

원칙 (CLAUDE.md 4-I, 25)
- **AI는 제출을 확정하지 않는다.** 최종 상태는 사람이 정하고, 그 결정을 여기 저장한다.
- 승인에는 근거가 남아야 한다. 무엇을(어떤 Auditor 실행 결과를) 보고 승인했는지 함께 기록한다.
- 체크리스트를 다 채우지 않으면 '승인'으로 갈 수 없다 (서비스에서 강제한다).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.text_fields import PersonName

# pending  : 아직 검토 전 (기본값)
# on_hold  : 보류 — 확인할 것이 남음
# rejected : 참여하지 않기로 결정 (No-Go)
# approved : 담당자가 제출 가능으로 승인
ReviewStatus = Literal["pending", "on_hold", "rejected", "approved"]

APPROVED: ReviewStatus = "approved"


class ReviewChecklist(BaseModel):
    """승인 전에 담당자가 직접 확인해야 하는 항목."""

    auditor_findings_reviewed: bool = False
    eligibility_check_resolved: bool = False
    evidence_confirmed: bool = False
    numbers_verified: bool = False

    @property
    def all_checked(self) -> bool:
        return all(
            (
                self.auditor_findings_reviewed,
                self.eligibility_check_resolved,
                self.evidence_confirmed,
                self.numbers_verified,
            )
        )

    def unchecked(self) -> list[str]:
        labels = {
            # 화면에 그대로 찍히는 이름이다 — 영문 값도, 영문 단계 이름도 쓰지 않는다.
            "auditor_findings_reviewed": "제출 전 점검 발견 항목 확인",
            "eligibility_check_resolved": "「확인 필요」 자격조건 해소",
            "evidence_confirmed": "회사 수행근거 원문 확인",
            "numbers_verified": "수치 대조",
        }
        return [label for key, label in labels.items() if not getattr(self, key)]


class ReviewDecision(BaseModel):
    """공고 1건에 대한 담당자 최종 검토 결과."""

    procurement_id: str = Field(min_length=1, max_length=64)
    status: ReviewStatus = "pending"
    checklist: ReviewChecklist = Field(default_factory=ReviewChecklist)
    reviewer: PersonName
    note: str | None = Field(default=None, max_length=2000)
    decided_at: datetime
    # 승인 근거 — 어떤 Auditor 실행/제안서를 보고 결정했는지.
    audit_run_id: str | None = Field(default=None, max_length=64)
    proposal_id: str | None = Field(default=None, max_length=64)
    # 결정 시점의 Coverage (나중에 되돌아볼 때 맥락이 된다).
    coverage_covered: int | None = Field(default=None, ge=0)
    coverage_total: int | None = Field(default=None, ge=0)
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False


class ReviewDecisionRequest(BaseModel):
    """검토 결과 저장 요청. decided_at은 서버가 찍는다."""

    procurement_id: str = Field(min_length=1, max_length=64)
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")
    status: ReviewStatus
    checklist: ReviewChecklist = Field(default_factory=ReviewChecklist)
    reviewer: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=2000)
    audit_run_id: str | None = Field(default=None, max_length=64)
    proposal_id: str | None = Field(default=None, max_length=64)
