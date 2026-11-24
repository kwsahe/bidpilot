"""조직(회사) 스키마 — 다회사 구조.

원칙
- 여러 회사가 등록될 수 있다. `organization_id`는 회사명과 분리된 영구 식별자다.
- 하나의 공고 분석은 하나의 회사에만 연결된다 (`AnalysisContext`).
- 선택한 회사의 **승인된** 근거만 분석에 쓴다. 실제자료와 합성 데모자료를 자동으로 섞지 않는다 (`EvidenceScope`).
- 이것은 모델 재학습이 아니라 "회사자료 등록·검토·승인·근거 색인"이다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.company import DataClass
from app.schemas.text_fields import LineText, PersonName, PhoneText, ShortText

OrganizationStatus = Literal["active", "inactive"]

# 근거 범위 — 분석이 어떤 자료를 검색할 수 있는가.
#   internal      선택한 조직의 승인된 real/anonymized 자료만 (합성 금지)
#   public_demo   합성 자료만 (실제 회사자료 금지)
#   explicit_test 테스트가 직접 넘긴 인덱스만 (운영 API에서 선택 불가)
EvidenceScope = Literal["internal", "public_demo", "explicit_test"]
API_EVIDENCE_SCOPES: tuple[str, ...] = ("internal", "public_demo")

ORGANIZATION_SCHEMA_VERSION = 1


class Organization(BaseModel):
    organization_id: str = Field(min_length=5, max_length=52)
    display_name: str = Field(min_length=1, max_length=100)
    legal_name: str | None = Field(default=None, max_length=100)
    status: OrganizationStatus = "active"
    data_class: DataClass = "real"
    # 공개 데모(배포본)에 이 회사 자료를 노출해도 되는지. 회사 승인 없이는 False.
    approved_for_public: bool = False
    created_at: datetime
    created_by: str | None = Field(default=None, max_length=60)
    updated_at: datetime
    updated_by: str | None = Field(default=None, max_length=60)
    # 레거시 data/company 에서 옮겨온 조직인지 (마이그레이션 기록)
    migrated_from_legacy: bool = False
    note: str | None = Field(default=None, max_length=1000)
    schema_version: int = ORGANIZATION_SCHEMA_VERSION


class OrganizationCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    legal_name: str | None = Field(default=None, max_length=100)
    # 비우면 회사명에서 안전한 slug를 만든다 (한글 상호는 짧은 uuid).
    organization_id: str | None = Field(default=None, min_length=5, max_length=52)
    data_class: DataClass = "real"
    approved_for_public: bool = False
    created_by: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=1000)


class OrganizationUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    legal_name: str | None = Field(default=None, max_length=100)
    data_class: DataClass | None = None
    approved_for_public: bool | None = None
    updated_by: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=1000)


class OrganizationProfile(BaseModel):
    """회사 프로필 (조직별). 시스템이 값을 채우지 않는다 — None은 미입력이다."""

    organization_id: str
    name: str = Field(min_length=1, max_length=100)
    business_domains: list[str] = Field(default_factory=list)
    target_clients: list[str] = Field(default_factory=list)
    preferred_regions: list[str] = Field(default_factory=list)
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    founded_year: int | None = Field(default=None, ge=1900, le=2100)
    employee_count: int | None = Field(default=None, ge=0)
    certifications: list[str] = Field(default_factory=list)
    #: 인증 **이력**(지난 지정 · 만료 · 43차 Q23 · COMPANY-05) — 판정 · 사업계획서 「인증」 칸에 쓰지 않는다. 현재 유효한 것만 `certifications`.
    #: 어느 쪽으로 옮길지는 대표가 정한다(앱은 칸만 만든다).
    certification_history: list[str] = Field(default_factory=list)
    # default_synthetic(파일 없음, 합성 기본값) | file(저장된 프로필) | legacy_file(레거시 data/company 프로필)
    source: Literal["default_synthetic", "file", "legacy_file"] = "default_synthetic"
    data_class: DataClass = "synthetic"
    approved_for_public: bool = False
    updated_at: datetime | None = None
    updated_by: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=1000)
    schema_version: int = ORGANIZATION_SCHEMA_VERSION


class OrganizationProfileUpdate(BaseModel):
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
    certification_history: list[ShortText] = Field(default_factory=list, max_length=40)
    data_class: DataClass = "real"
    approved_for_public: bool = False
    updated_by: PersonName
    note: str | None = Field(default=None, max_length=1000)
    #: 화면이 프로필을 처음 읽은 때의 `updated_at`(44차 TEAM-R36-01) — 그사이 남이 저장했으면 409. 보내지 않으면(키트 · 스크립트) 검사 안 함.
    expected_updated_at: datetime | None = None


#: 사업자등록번호 — 000-00-00000 (29차 §3-B 입력 검사).
BUSINESS_NUMBER_PATTERN = r"^\d{3}-\d{2}-\d{5}$"


class YearAmount(BaseModel):
    """연도 하나의 값 — 매출(원) · 고용 인원(명). 값이 없으면 None(0 으로 적지 않는다)."""

    year: int = Field(ge=1990, le=2100)
    value: int | None = Field(default=None, ge=0)


class StaffRole(BaseModel):
    """인력 구성 한 줄 — **성명 없이** 직무 · 인원만 (29차 §3-B)."""

    role: ShortText
    count: int = Field(ge=0, le=100000)


class PlanGeneralInfo(BaseModel):
    """사업계획서 일반현황 — 사람이 입력한 회사 값 (29차 §3-B · 담당자 결정 「회사자료에 있는 값 전부」).

    `profile.json`(비공개 회사 폴더)의 `plan_general` 에 둔다. 프로필 공개 응답 · AI 본문에는 싣지 않고,
    사업계획서를 조립할 때(화면 응답 · 내려받기)만 이 PC 에서 채운다. 사업자등록증 이미지에서 뽑아내지 않는다.
    """

    representative: str | None = Field(default=None, max_length=40)
    business_number: str | None = Field(default=None, pattern=BUSINESS_NUMBER_PATTERN)
    opened_on: date | None = None
    business_type: str | None = Field(default=None, max_length=60)
    business_item: str | None = Field(default=None, max_length=120)
    revenue_by_year: list[YearAmount] = Field(default_factory=list, max_length=3)
    employees_by_year: list[YearAmount] = Field(default_factory=list, max_length=3)
    staff: list[StaffRole] = Field(default_factory=list, max_length=20)
    updated_at: datetime | None = None
    updated_by: str | None = Field(default=None, max_length=60)


class PlanGeneralUpdate(BaseModel):
    """일반현황 저장 요청 — 빈 문자열은 「지움」(None)."""

    #: 화면이 일반현황을 처음 읽은 때의 `updated_at`(44차 TEAM-R36-01) — 그사이 남이 저장했으면 409. 보내지 않으면 검사 안 함.
    expected_updated_at: datetime | None = None

    representative: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    #: 비우면 지운다 · 적으면 000-00-00000 (아니면 422)
    business_number: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^$|^\d{3}-\d{2}-\d{5}$")] | None = None
    opened_on: date | None = None
    business_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    business_item: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    revenue_by_year: list[YearAmount] = Field(default_factory=list, max_length=3)
    employees_by_year: list[YearAmount] = Field(default_factory=list, max_length=3)
    staff: list[StaffRole] = Field(default_factory=list, max_length=20)
    updated_by: PersonName


class OrganizationSummary(BaseModel):
    """목록·선택기용 요약. 회사 간 격리: 다른 회사의 문서 내용은 절대 섞이지 않는다."""

    organization: Organization
    profile_source: Literal["default_synthetic", "file", "legacy_file"]
    document_count: int = Field(ge=0)
    # 「승인」이라는 한 단어가 두 숫자를 말하고 있었다.
    #   approved_document_count = status 가 approved(색인 전) + indexed(색인 완료)
    #   반면 DocumentListResponse.counts["approved"] 는 «색인 전»만 센다.
    # 화면 두 곳이 둘 다 「승인 N건」이라고 적어서 같은 페이지에 서로 다른 수가 떴다
    # (frontend/src/app/company/page.tsx 의 등록 진행 「승인」 힌트와 「등록 문서」 카드 힌트).
    # 기존 필드의 뜻은 그대로 두고(계약 유지), 라벨을 갈라 쓸 수 있도록 조각을 따로 내려보낸다.
    approved_document_count: int = Field(ge=0)
    indexed_document_count: int = Field(default=0, ge=0)
    approved_not_indexed_document_count: int = Field(default=0, ge=0)
    # 실제로 근거로 쓰일 수 있는 문서 — company_service.is_active 통과
    # (승인됨 · 비활성 아님 · 유효기간 안). 「승인 N건」과 다를 수 있고, 그 차이가 사실이다.
    active_evidence_document_count: int = Field(default=0, ge=0)
    # 등록부 JSON 이 깨져 격리된 흔적이 있으면 그 사실. 격리 후 두 번째 읽기부터는
    # 「파일 없음 = 빈 등록부」가 되어 화면에 「자료 없음」으로만 보였다 — 증발과 구분되지 않는다.
    document_registry_note: str | None = None
    pending_index_documents: int = Field(ge=0)
    index_chunk_count: int = Field(ge=0)
    index_built_at: str | None = None
    embedding_available: bool
    last_updated_at: datetime | None = None
    # 공개 데모에서 쓸 수 있는가 = 조직 승인 + 합성/비식별 자료
    usable_in_public_demo: bool


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationSummary]
    default_organization_id: str
    # 인증이 없는 로컬 모드인지 (화면에 "로컬 관리자 모드"로 표시)
    local_admin_mode: bool
    public_demo_mode: bool


class AnalysisContext(BaseModel):
    """공고 분석 하나가 고정되는 회사와 근거 범위. 결과 파일·캐시 키에 함께 기록된다."""

    model_config = {"frozen": True}

    organization_id: str = Field(min_length=5, max_length=52)
    evidence_scope: EvidenceScope = "internal"

    def cache_key(self, procurement_id: str) -> str:
        return f"{self.organization_id}|{self.evidence_scope}|{procurement_id}"

    @property
    def is_private(self) -> bool:
        """조직 저장공간에 결과를 두는 범위인지 (public_demo는 공개 위치)."""
        return self.evidence_scope != "public_demo"


class EvidenceScopeInfo(BaseModel):
    """분석 결과에 붙는 출처 범위 — 어떤 회사의 어떤 자료를 몇 건 썼는가."""

    organization_id: str | None
    evidence_scope: EvidenceScope
    used_document_count: int = Field(default=0, ge=0)
    used_chunk_count: int = Field(default=0, ge=0)
    synthetic_evidence_used: bool = False
    real_evidence_used: bool = False
    note: str | None = None


class AnalysisContextRequest(BaseModel):
    """분석 시작 계약 — organization_id 는 명시해야 한다 (호환 API만 기본 조직을 채운다)."""

    procurement_id: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=5, max_length=52)
    evidence_scope: Literal["internal", "public_demo"] = "internal"
