"""입찰 참가자격 판정 스키마.

`schemas/demo.py`의 `EligibilityResult`와 **필드 호환**을 유지한다
(rule_id / label / status / method / source / reason / requirement_id).
기존 데모 시나리오 JSON과 프론트엔드가 그대로 렌더링될 수 있어야 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.text_fields import PersonName

EligibilityStatus = Literal["PASS", "CHECK", "FAIL"]
EligibilityMethod = Literal["RULE", "AI_EXTRACTION", "HUMAN"]


class EligibilityResult(BaseModel):
    """참가자격 판정 1건. 판정 근거(`source`)에는 공고 원문 필드값 또는 RFP 원문을 남긴다."""

    rule_id: str
    label: str
    status: EligibilityStatus
    method: EligibilityMethod
    # 판정에 사용한 실제 근거: 공고 API 필드명=값, 또는 'RFP p.8 "원문"'.
    source: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requirement_id: str | None = None
    #: **무엇을 갖추면 이 판정이 뒤집히는가** (0921 §4-B).
    #:
    #: 「소프트웨어사업자(1468) 등록 시 가능」·「공동수급 파트너 확보 시」처럼, 지금은 안 되지만
    #: 열 수 있는 길이 있으면 여기에 적는다. 없으면 None — 길이 없다는 뜻이다.
    #: 기본값 None 이어야 기존 저장 파일·데모 시나리오가 그대로 검증된다.
    unlock_condition: str | None = None
    #: **그중 하나만 갖추면 되는** 조건들 (0922 §4-A-5).
    #:
    #: 아산시 공고처럼 「1426·1468·1469·1470 중 하나」를 요구하는 경우, 사람이 읽는
    #: `unlock_condition` 한 줄로는 갭 리포트가 「1468 을 등록하면 몇 건이 열리는가」를 셀 수
    #: 없다. 그래서 셀 수 있는 낱개 조건을 따로 둔다. 비어 있으면 `unlock_condition` 하나만 센다.
    unlock_options: list[str] = Field(default_factory=list)
    #: 이 줄이 공고문(또는 제안요청서·RFP)의 **어느 조항**인가 — 「QC-04」·「RFP-QC-02」·「REQ-011」.
    #: 20차부터 조항마다 한 줄이라 id 도 하나다(§4-B). 참가자격 조항 줄(QUAL-*)에만 붙는다. 없으면 None.
    clause_id: str | None = None
    #: 조항 원문 · 쪽 · 출처 문서(「입찰공고문」·「제안요청서」·「RFP」) · 종류 — 화면 체크리스트가 그린다.
    clause_text: str | None = None
    page: int | None = None
    source_document: str | None = None
    kind: str | None = None
    #: 담당자 확인 (20차 §4-C) — `met`(충족 → 가능) · `unmet`(미충족 → 불가) · `pending`(보류) ·
    #: `stale`(확인한 뒤 조항 원문이 바뀌었다 — 판정에 쓰지 않고 다시 확인을 받는다). 기록이 없으면 None.
    review_state: Literal["met", "unmet", "pending", "stale"] | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    #: 확인 필요일 때 **누가 채워야 하나** — `company`(회사 값이 비었다) · `notice`(원문을 사람이
    #: 읽어야 한다). 가능·불가면 None.
    check_side: Literal["company", "notice"] | None = None


class EligibilityCounts(BaseModel):
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    check: int = Field(ge=0)
    failed: int = Field(ge=0)


class ClauseDocument(BaseModel):
    """조항을 읽은 문서와 그 **원본** 내려받기 링크 (20차 §4-E-2). 로컬 캐시는 내보내지 않는다.

    링크는 나라장터(g2b.go.kr) https 만 — 그 밖이면 None(화면은 이름만 적는다).
    """

    source_document: str
    name: str
    format: str | None = None
    url: str | None = None


class ReviewTally(BaseModel):
    """조항 줄의 담당자 확인 수 (20차 §4-C). 기록이 없는 조항은 `pending`(확인 전)에 든다."""

    met: int = Field(default=0, ge=0)
    unmet: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    stale: int = Field(default=0, ge=0)


class EligibilityReport(BaseModel):
    procurement_id: str
    # FAIL이 하나라도 있으면 FAIL, 없고 CHECK가 있으면 CHECK, 전부 PASS면 PASS.
    verdict: EligibilityStatus
    counts: EligibilityCounts
    evaluated_at: datetime
    # 공고 원문 필드 / 파싱된 요구사항을 실제로 사용할 수 있었는지 (UI 표시용).
    notice_available: bool
    requirements_available: bool
    # LLM은 선택 기능이다. False여도 규칙 기반 결과는 항상 완전하다.
    llm_used: bool
    results: list[EligibilityResult]
    # --- 다회사 구조: 이 결과가 고정된 회사와 근거 범위. 레거시 결과는 organization_id=None ---
    organization_id: str | None = None
    evidence_scope: str | None = None
    legacy_result: bool = False
    # 지역 규칙에 쓴 회사 활동 지역 (프로필 출처). 비어 있으면 지역 규칙은 CHECK 로 남는다.
    regions_used: list[str] = Field(default_factory=list)
    # --- 참가자격 조항 (19차 §4-B) — 입찰공고문에서 가져온 절 ---
    #: 조항을 읽은 공고문 이름. 못 읽었으면 None.
    clause_document: str | None = None
    #: 공고문에서 나눈 조항 수(제안요청서·RFP 요구사항은 세지 않는다).
    clause_count: int = Field(default=0, ge=0)
    #: 참가자격 절이 있는 쪽 — 「p.2」·「p.2–3(근사)」. HWP 는 쪽 정보가 없어 근사다.
    clause_pages: str | None = None
    #: 공고문 참가자격 절을 읽은 결과. 합성 공고처럼 공고문이 없는 것도 `not_fetched` 다.
    clauses_status: Literal["ok", "no_section", "image", "error", "not_fetched"] = "not_fetched"
    #: 참가자격 조항 줄의 종류별 개수 — 「disqualification: 2 · track_record: 1 …」 (20차 §4-B).
    #: 줄 수가 곧 조항 수다(조항마다 한 줄).
    clause_summary: dict[str, int] = Field(default_factory=dict)
    #: 담당자 확인 수 — 충족 · 미충족 · 확인 전(보류 포함) · 다시 확인.
    review: ReviewTally = Field(default_factory=ReviewTally)
    #: 조항을 읽은 문서(입찰공고문 · 제안요청서)와 원본 링크 — 3단계 머리글 옆에 건다.
    clause_documents: list[ClauseDocument] = Field(default_factory=list)


class ClauseReviewRequest(BaseModel):
    """담당자 확인 한 건 (20차 §4-C). 충족·미충족은 메모가 있어야 저장된다(서비스가 422 로 막는다)."""

    state: Literal["met", "unmet", "pending"]
    note: str | None = Field(default=None, max_length=500)
    decided_by: PersonName
    #: 화면이 읽은 이 조항의 확인 시각(43차 M25) — 없던 칸이면 null 로 보낸다. 보내지 않으면(옛 화면) 검사하지 않는다.
    expected_decided_at: datetime | None = None


class ClauseReviewEntry(BaseModel):
    clause_id: str
    state: Literal["met", "unmet", "pending"]
    note: str | None = None
    decided_by: str
    decided_at: datetime
    #: 확인한 뒤 조항 원문이 바뀌었다 — 판정에 쓰지 않는다.
    stale: bool = False


class ClauseReviewList(BaseModel):
    procurement_id: str
    reviews: list[ClauseReviewEntry] = Field(default_factory=list)


class EligibilityRequest(BaseModel):
    procurement_id: str = Field(min_length=1, max_length=64)
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    evidence_scope: str | None = Field(default=None, pattern=r"^(internal|public_demo)$")
    # 기한 판정 기준 시각. 생략하면 현재 시각. (과거 공고를 데모할 때 사용)
    as_of: datetime | None = None
    # LLM 보강을 끄고 순수 규칙 기반 결과만 보고 싶을 때 False.
    # 기본은 규칙만 — 결정론적이고 즉시 응답한다 (CLAUDE.md: LLM 없이 재현 가능한 baseline 우선).
    # LLM 보강은 화면의 'AI 정밀 판정' 버튼에서 명시적으로 켠다.
    use_llm: bool = False
