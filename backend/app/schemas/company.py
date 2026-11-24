"""회사정보·수행근거(회사자료) 스키마.

화면 용어: "AI 학습"이 아니라 **회사자료 등록 및 근거 색인**이다. 자료를 올리면 텍스트를 뽑아
후보 문단을 보여주고, 담당자가 확인한 문단만 근거로 등록되어 색인된다.

데이터 등급(data_class)
- real       : 실제 자료 (내부 전용, 공개 배포 제외)
- anonymized : 비식별 처리한 실제 자료
- synthetic  : 합성 자료 (공개 데모용)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.text_fields import LineText, PersonName, PhoneText, ShortText

DataClass = Literal["real", "anonymized", "synthetic"]
Scope = Literal["internal", "public_demo"]
SourceKind = Literal["upload", "markdown", "manual", "synthetic"]

# 대기 / 텍스트 추출 중 / 검토 필요 / 승인 / 색인 중 / 완료 / 실패 (+ 반려 / 비활성)
DocumentStatus = Literal[
    "pending",
    "extracting",
    "review",
    "approved",
    "indexing",
    "indexed",
    "failed",
    "rejected",
    "retired",
]

DOCUMENT_STATUS_LABEL: dict[str, str] = {
    "pending": "대기",
    "extracting": "텍스트 추출 중",
    "review": "검토 필요",
    "approved": "승인",
    "indexing": "색인 중",
    "indexed": "완료",
    "failed": "실패",
    "rejected": "반려",
    "retired": "비활성",
}


class CompanyProfile(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    business_domains: list[str] = Field(default_factory=list)
    target_clients: list[str] = Field(default_factory=list)
    preferred_regions: list[str] = Field(default_factory=list)
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    # None = 미공개/미입력. 시스템이 채우지 않는다.
    founded_year: int | None = Field(default=None, ge=1900, le=2100)
    employee_count: int | None = Field(default=None, ge=0)
    certifications: list[str] = Field(default_factory=list)
    data_class: DataClass = "synthetic"
    # 공개 데모(배포본)에 노출해도 되는지. 회사 승인 없이는 False.
    approved_for_public: bool = False
    updated_at: datetime | None = None
    updated_by: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=1000)
    # 어디서 온 값인지: default_synthetic(파일 없음) | file
    source: Literal["default_synthetic", "file"] = "default_synthetic"
    schema_version: int = 2


class CompanyProfileUpdate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    business_domains: list[ShortText] = Field(default_factory=list, max_length=40)
    target_clients: list[ShortText] = Field(default_factory=list, max_length=40)
    preferred_regions: list[ShortText] = Field(default_factory=list, max_length=40)
    address: LineText | None = None
    phone: PhoneText | None = None
    website: LineText | None = None
    founded_year: int | None = Field(default=None, ge=1900, le=2100)
    employee_count: int | None = Field(default=None, ge=0)
    certifications: list[ShortText] = Field(default_factory=list, max_length=40)
    data_class: DataClass = "synthetic"
    approved_for_public: bool = False
    updated_by: PersonName
    note: str | None = Field(default=None, max_length=1000)


class EvidenceMetadata(BaseModel):
    source_kind: SourceKind = "upload"
    # 파일명 또는 경로 라벨 (실제 저장 경로는 노출하지 않는다)
    location: str
    data_class: DataClass = "real"
    approved: bool = False
    approved_by: str | None = Field(default=None, max_length=60)
    approved_at: datetime | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    last_verified_at: datetime | None = None
    scope: Scope = "internal"
    version: int = Field(default=1, ge=1)
    checksum: str | None = None
    retired: bool = False


class EvidenceCandidate(BaseModel):
    id: str
    document_id: str
    # 어느 조직의 후보인지. 레거시(없음)는 읽을 때 기본 조직으로 채운다.
    organization_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    source_text: str = Field(min_length=1)
    # None = 미검토, True = 근거로 채택, False = 제외
    approved: bool | None = None
    reviewer: str | None = Field(default=None, max_length=60)
    reviewed_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    # "확인되지 않은 사항"처럼 근거가 아닌 문단 (규칙 판정, 기본 제외)
    is_gap: bool = False


class CompanyDocument(BaseModel):
    id: str
    # 소유 조직 (영구 식별자, 회사명과 무관). 레거시 등록부에는 없을 수 있다 → 기본 조직으로 읽는다.
    organization_id: str | None = None
    file_name: str
    title: str
    doc_type: str = "기타"
    status: DocumentStatus = "pending"
    size_bytes: int = Field(ge=0)
    sha256: str
    doc_format: str | None = None
    uploaded_at: datetime
    uploaded_by: str | None = Field(default=None, max_length=60)
    extracted_at: datetime | None = None
    page_count: int | None = Field(default=None, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    approved_chunk_count: int = Field(default=0, ge=0)
    indexed_chunk_count: int = Field(default=0, ge=0)
    indexed_at: datetime | None = None
    error: str | None = None
    duplicate_of: str | None = None
    metadata: EvidenceMetadata
    note: str | None = Field(default=None, max_length=1000)
    # 이 문서를 마지막으로 바꾼 **인증된 계정** (S12). `uploaded_by` 는 업로드 화면이 채워 보낸
    # 이름(클라이언트의 주장)이고, 이것은 서명된 신원에서 온 사실이다. 둘은 다를 수 있다.
    # 인증이 꺼진 로컬에서는 None 이다 — 없는 것을 이름으로 채우지 않는다.
    recorded_by: str | None = Field(default=None, max_length=64)
    schema_version: int = 2


class CompanyDocumentDetail(CompanyDocument):
    candidates: list[EvidenceCandidate] = Field(default_factory=list)


class IndexStatus(BaseModel):
    """근거 색인 상태. 합성 인덱스와 회사 인덱스를 따로 보여준다 (섞지 않는다)."""

    organization_id: str | None = None
    embedding_available: bool
    embedding_model: str | None
    synthetic_index: dict
    company_index: dict
    # 승인됐지만 아직 색인되지 않은 문서 수 (키가 없거나 rebuild 전)
    pending_documents: int = Field(ge=0)
    # 회사 인덱스가 승인 문서 상태보다 오래됐는지
    stale: bool = False
    note: str


class DocumentListResponse(BaseModel):
    organization_id: str | None = None
    documents: list[CompanyDocument]
    counts: dict[str, int]
    index: IndexStatus


class CandidateReview(BaseModel):
    candidate_id: str
    approved: bool
    note: str | None = Field(default=None, max_length=500)


class CandidateReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=60)
    reviews: list[CandidateReview] = Field(min_length=1, max_length=500)


class DocumentApproveRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=60)
    data_class: DataClass = "real"
    scope: Scope = "internal"
    valid_from: date | None = None
    valid_to: date | None = None
    doc_type: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class DocumentRetireRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=1000)


class UsageEntry(BaseModel):
    procurement_id: str
    organization_id: str | None = None
    requirement_id: str | None
    evidence_id: str
    where: Literal["proposal", "proposal_document"]
    sentence_id: str | None = None


class UsageResponse(BaseModel):
    organization_id: str | None = None
    document_id: str
    used_in: list[UsageEntry]


class ReindexResult(BaseModel):
    ok: bool
    reason: str
    organization_id: str | None = None
    chunk_count: int = Field(default=0, ge=0)
    document_count: int = Field(default=0, ge=0)
    built_at: datetime | None = None
