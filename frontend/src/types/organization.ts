/**
 * 조직(회사) — 다회사 구조 (backend/app/schemas/organization.py).
 * 하나의 공고 분석은 하나의 회사(+근거 범위)에 고정된다. 실제자료와 합성 데모자료를 섞지 않는다.
 */

import type { CompanyProfile, DataClass, DocumentStatus } from "@/types/company";
import { SYNTHETIC_COMPANY } from "@/lib/terms";

export type OrganizationStatus = "active" | "inactive";

/** internal = 선택한 회사의 승인 자료만 · public_demo = 합성 자료만 · explicit_test = 테스트 전용(API 선택 불가) */
export type EvidenceScope = "internal" | "public_demo" | "explicit_test";

export const EVIDENCE_SCOPE_LABELS: Record<EvidenceScope, string> = {
  internal: "내부 승인자료",
  public_demo: SYNTHETIC_COMPANY,
  explicit_test: "테스트 인덱스",
};

export interface Organization {
  organization_id: string;
  display_name: string;
  legal_name: string | null;
  status: OrganizationStatus;
  data_class: DataClass;
  approved_for_public: boolean;
  created_at: string;
  created_by: string | null;
  updated_at: string;
  updated_by: string | null;
  migrated_from_legacy: boolean;
  note: string | null;
  schema_version: number;
}

export type ProfileSource = "default_synthetic" | "file" | "legacy_file";

/** 연도 하나의 값 — 매출(원) · 고용(명). 값이 없으면 null. */
export interface YearAmount {
  year: number;
  value: number | null;
}

/** 사업계획서 일반현황 — 사람이 입력한 회사 값 (29차 §3-B). 프로필 공개 응답 · AI 본문에는 없다. */
export interface PlanGeneralInfo {
  representative: string | null;
  business_number: string | null;
  opened_on: string | null;
  business_type: string | null;
  business_item: string | null;
  revenue_by_year: YearAmount[];
  employees_by_year: YearAmount[];
  staff: { role: string; count: number }[];
  updated_at: string | null;
  updated_by: string | null;
}

export type PlanGeneralUpdate = Omit<PlanGeneralInfo, "updated_at" | "updated_by"> & {
  updated_by: string;
  /** 처음 읽은 때의 저장 시각(44차 TEAM-R36-01) — 그사이 남이 저장했으면 서버가 409. */
  expected_updated_at?: string | null;
};

export interface OrganizationProfile extends Omit<CompanyProfile, "source"> {
  organization_id: string;
  source: ProfileSource;
}

export interface OrganizationProfileUpdate {
  /** 처음 읽은 때의 저장 시각(44차 TEAM-R36-01) — 그사이 남이 저장했으면 서버가 409. */
  expected_updated_at?: string | null;
  name: string;
  business_domains: string[];
  target_clients: string[];
  preferred_regions: string[];
  address: string | null;
  phone: string | null;
  website: string | null;
  founded_year: number | null;
  employee_count: number | null;
  certifications: string[];
  /** 인증 이력(지난 지정 · 만료 · 43차 Q23) — 판정 · 사업계획서에 쓰지 않는다. 옛 응답에는 없다. */
  certification_history?: string[];
  data_class: DataClass;
  approved_for_public: boolean;
  updated_by: string;
  note: string | null;
}

export interface OrganizationSummary {
  organization: Organization;
  profile_source: ProfileSource;
  document_count: number;
  /**
   * 「승인」의 정의는 **승인 + 색인 완료**다. 화면에서 「승인 N건」이라고 쓸 때
   * 아래 두 값 중 어느 것을 말하는지 반드시 갈라 적어야 한다 — 예전에 같은 화면 두 곳이
   * 이 값과 `counts["approved"]`(= 색인 전만)를 둘 다 「승인 N건」이라고 불러 다른 수를 말했다.
   */
  approved_document_count: number;
  /** 색인까지 끝나 실제로 근거 검색에 들어간 문서 수. */
  indexed_document_count: number;
  /** 승인은 됐는데 아직 색인 전. `counts["approved"]` 와 같은 수다. */
  approved_not_indexed_document_count: number;
  /** 승인 · 유효기간 안 · 비활성 아님 — 지금 공고 분석에 실제로 쓰이는 문서 수. */
  active_evidence_document_count: number;
  /** 등록부 JSON 이 깨져 격리됐을 때의 사유. null 이면 정상. «자료 없음»과 «읽기 실패»는 다르다. */
  document_registry_note: string | null;
  pending_index_documents: number;
  index_chunk_count: number;
  index_built_at: string | null;
  embedding_available: boolean;
  last_updated_at: string | null;
  usable_in_public_demo: boolean;
}

export interface OrganizationListResponse {
  organizations: OrganizationSummary[];
  default_organization_id: string;
  /** 인증이 없는 로컬 모드 (화면에 "로컬 관리자 모드"로 표시) */
  local_admin_mode: boolean;
  public_demo_mode: boolean;
}

export interface OrganizationCreateRequest {
  display_name: string;
  legal_name?: string | null;
  organization_id?: string | null;
  data_class: DataClass;
  approved_for_public: boolean;
  created_by: string;
  note?: string | null;
}

/** 분석 요청에 붙는 회사·근거 범위. 응답의 organization_id/evidence_scope 와 같은 뜻이다. */
export interface AnalysisContextParams {
  organization_id: string;
  evidence_scope: Exclude<EvidenceScope, "explicit_test">;
}

/** 분석 결과에 붙는 출처 범위 (backend EvidenceScopeInfo). */
export interface EvidenceScopeInfo {
  organization_id: string | null;
  evidence_scope: EvidenceScope;
  used_document_count: number;
  used_chunk_count: number;
  synthetic_evidence_used: boolean;
  real_evidence_used: boolean;
  note: string | null;
  /**
   * 지금 이 회사의 회사 근거 연결(AI 검색)이 꺼져 있나 — 서버가 응답 때 붙인다(46차 H5 · `evidence_service.ai_search_off`).
   * 저장된 초안의 옛 사유 글이 아니라 이 값으로 「AI 검색 꺼 둠」과 「실패」를 가른다. 옛 서버 · 옛 스냅샷에는 없다(undefined).
   */
  ai_search_off?: boolean | null;
}

/** 결과 객체에 공통으로 붙는 회사·범위 표시. 레거시 결과는 organization_id=null. */
export interface ScopedResult {
  organization_id?: string | null;
  evidence_scope?: EvidenceScope | null;
  legacy_result?: boolean;
}

export interface IndexSearchHit {
  score: number;
  evidence_id: string;
  document_id: string | null;
  document_name: string;
  doc_type: string;
  page: number | null;
  source_text: string;
  data_class: DataClass;
}

export interface IndexSearchResult {
  organization_id: string;
  evidence_scope: EvidenceScope;
  available: boolean;
  reason?: string;
  synthetic_evidence_used?: boolean;
  hits: IndexSearchHit[];
}

// ---------------------------------------------------------------------------
// 실적 원장 import (매핑 확인 → preview → 승인 등록)
// ---------------------------------------------------------------------------

export interface LedgerSheetInfo {
  name: string;
  header_row: number | null;
  headers: string[];
  row_count: number;
  suggested_mapping: Record<string, string | null>;
  missing_required: string[];
  status_values: string[];
  external_use_values: string[];
}

export interface LedgerInspectResult {
  organization_id: string;
  upload_id: string;
  file_name: string;
  sheets: LedgerSheetInfo[];
  suggested_sheet: string | null;
  suggested_profile_id: string;
  note: string;
}

export interface LedgerImportProfile {
  profile_id: string;
  label: string;
  sheet: string | null;
  columns: Record<string, string[]>;
  approved_values: string[];
  completed_statuses: string[];
  amount_unit: string;
  note: string | null;
}

export interface LedgerPreviewRequest {
  upload_id: string;
  profile_id: string;
  sheet?: string | null;
  column_overrides?: Record<string, string>;
  approved_values?: string[] | null;
  completed_statuses?: string[] | null;
  amount_unit?: string | null;
}

export interface LedgerPreviewRow {
  seq: number;
  row_number: number;
  title: string;
  status: string;
  external_use: string;
  eligible: boolean;
  exclusion_reason: string | null;
  warnings: string[];
}

export interface LedgerPreviewResult {
  organization_id: string;
  upload_id: string;
  profile_id: string;
  sheet: string;
  columns_used: Record<string, string>;
  approved_values: string[];
  completed_statuses: string[];
  amount_unit: string;
  total_rows: number;
  included: number;
  excluded: number;
  exclusion_reasons: Record<string, number>;
  by_group: Record<string, number>;
  documents: string[];
  rows: LedgerPreviewRow[];
  warnings: string[];
}

export interface LedgerImportResult {
  organization_id: string;
  upload_id: string;
  profile_id: string;
  sheet: string;
  source_name: string;
  ledger_date: string;
  included: number;
  excluded: number;
  registered: Array<{ file_name: string; document_id: string; status: DocumentStatus; candidates: number; approved_chunks?: number }>;
  skipped_duplicates: string[];
  approved: boolean;
  ledger_file_written: boolean;
  note: string;
}

export interface LedgerSummary {
  organization_id: string;
  available: boolean;
  note?: string;
  ledger_date?: string | null;
  source_file?: string | null;
  sheet?: string | null;
  amount_unit?: string;
  profile_id?: string | null;
  counts?: { total: number; eligible: number; excluded: number; with_amount: number };
  by_group?: Record<string, number>;
  project_rows?: number;
}
