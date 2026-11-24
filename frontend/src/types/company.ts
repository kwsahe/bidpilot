/**
 * 회사정보·수행근거 (backend/app/schemas/company.py).
 * 화면 용어는 "AI 학습"이 아니라 **회사자료 등록 및 근거 색인**이다.
 */

export type DataClass = "real" | "anonymized" | "synthetic";
export type Scope = "internal" | "public_demo";
export type SourceKindMeta = "upload" | "markdown" | "manual" | "synthetic";

/** 대기 / 텍스트 추출 중 / 검토 필요 / 승인 / 색인 중 / 완료 / 실패 / 반려 / 비활성 */
export type DocumentStatus =
  | "pending"
  | "extracting"
  | "review"
  | "approved"
  | "indexing"
  | "indexed"
  | "failed"
  | "rejected"
  | "retired";

export const DOCUMENT_STATUS_LABELS: Record<DocumentStatus, string> = {
  pending: "처리 전",
  extracting: "글자 읽는 중",
  review: "문장 고르기 필요",
  approved: "등록됨(검색 준비 전)",
  indexing: "검색 준비 중",
  indexed: "사용 중", // 「색인 완료」는 개발 말(30차 §3-F #35)
  failed: "실패",
  rejected: "반려",
  retired: "근거에서 뺌",
};

/** 유효기간 안인가 — 기간을 안 적었으면 안으로 본다. `today` 는 「YYYY-MM-DD」(31차 R30-32). */
export function withinValidity(meta: { valid_from: string | null; valid_to: string | null }, today: string): boolean {
  return (!meta.valid_from || meta.valid_from.slice(0, 10) <= today) && (!meta.valid_to || meta.valid_to.slice(0, 10) >= today);
}

/** 기간 밖 문서 — 검색 준비가 끝났어도 공고 분석에 쓰지 않는다. */
export const OUT_OF_PERIOD_LABEL = "기간 밖";

/** 문서 상태 이름 — 「사용 중」(검색 준비 끝)이어도 유효기간 밖이면 「기간 밖」(31차 R30-32). */
export function documentStatusLabel(doc: { status: DocumentStatus; metadata?: { valid_from: string | null; valid_to: string | null } | null }, today: string): string {
  if (doc.status === "indexed" && doc.metadata && !withinValidity(doc.metadata, today)) return OUT_OF_PERIOD_LABEL;
  return DOCUMENT_STATUS_LABELS[doc.status];
}

export const DATA_CLASS_LABELS: Record<DataClass, string> = {
  real: "실제 자료",
  anonymized: "비식별 실제 자료",
  synthetic: "가상 예시 자료",
};

export interface CompanyProfile {
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
  updated_at: string | null;
  updated_by: string | null;
  note: string | null;
  /** default_synthetic = 파일 없음(합성 기본값) · file = 저장된 프로필 */
  source: "default_synthetic" | "file";
}

export interface CompanyProfileUpdate {
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
  data_class: DataClass;
  approved_for_public: boolean;
  updated_by: string;
  note: string | null;
}

export interface EvidenceMetadata {
  source_kind: SourceKindMeta;
  location: string;
  data_class: DataClass;
  approved: boolean;
  approved_by: string | null;
  approved_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  last_verified_at: string | null;
  scope: Scope;
  version: number;
  checksum: string | null;
  retired: boolean;
}

export interface EvidenceCandidate {
  id: string;
  document_id: string;
  page: number | null;
  source_text: string;
  /** null = 미검토, true = 채택, false = 제외 */
  approved: boolean | null;
  reviewer: string | null;
  reviewed_at: string | null;
  note: string | null;
  is_gap: boolean;
}

export interface CompanyDocument {
  id: string;
  /** 다회사 구조: 이 문서가 속한 회사 (레거시 응답에는 없을 수 있다) */
  organization_id?: string;
  file_name: string;
  title: string;
  doc_type: string;
  status: DocumentStatus;
  size_bytes: number;
  sha256: string;
  doc_format: string | null;
  uploaded_at: string;
  uploaded_by: string | null;
  extracted_at: string | null;
  page_count: number | null;
  candidate_count: number;
  approved_chunk_count: number;
  indexed_chunk_count: number;
  indexed_at: string | null;
  error: string | null;
  duplicate_of: string | null;
  metadata: EvidenceMetadata;
  note: string | null;
}

export interface CompanyDocumentDetail extends CompanyDocument {
  candidates: EvidenceCandidate[];
}

export interface IndexSummary {
  exists: boolean;
  path: string;
  built_at: string | null;
  chunk_count: number;
  document_count: number;
  model: string | null;
}

export interface IndexStatus {
  organization_id?: string;
  embedding_available: boolean;
  embedding_model: string | null;
  synthetic_index: IndexSummary;
  company_index: IndexSummary;
  pending_documents: number;
  stale: boolean;
  note: string;
}

export interface DocumentListResponse {
  documents: CompanyDocument[];
  counts: Partial<Record<DocumentStatus, number>>;
  index: IndexStatus;
  /**
   * 배포 스냅샷에서 제외된 문서 수. 백엔드는 보내지 않는다 —
   * `scripts/snapshot_demo_api.py` 가 직원 실명이 담긴 문서를 빼면서 붙인다.
   * 빠진 사실이 화면에 보여야 하므로(조용히 사라지면 안 된다) 타입에 둔다.
   */
  withheld_count?: number;
  snapshot_note?: string;
}

export interface CandidateReviewRequest {
  reviewer: string;
  reviews: Array<{ candidate_id: string; approved: boolean; note?: string | null }>;
}

export interface DocumentApproveRequest {
  reviewer: string;
  data_class: DataClass;
  scope: Scope;
  valid_from?: string | null;
  valid_to?: string | null;
  doc_type?: string | null;
  title?: string | null;
  note?: string | null;
}

export interface UsageEntry {
  procurement_id: string;
  requirement_id: string | null;
  evidence_id: string;
  where: "proposal" | "proposal_document";
  sentence_id: string | null;
}

export interface UsageResponse {
  document_id: string;
  used_in: UsageEntry[];
}

export interface ReindexResult {
  ok: boolean;
  reason: string;
  chunk_count: number;
  document_count: number;
  built_at: string | null;
}
