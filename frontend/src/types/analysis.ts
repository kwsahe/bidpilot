/**
 * 실제 분석 API(Eligibility / Proposal / Auditor) 응답 타입.
 *
 * backend 스키마와 1:1 대응한다.
 * - backend/app/schemas/eligibility.py  EligibilityReport
 * - backend/app/schemas/proposal.py     ProposalSection
 * - backend/app/schemas/audit.py        AuditRun
 *
 * 세 스키마 모두 `schemas/demo.py`(데모 시나리오)와 **필드 호환**이라
 * 여기서는 데모 타입(@/types/cosmos)을 확장해 정의한다.
 */

import type {
  AuditFinding,
  EligibilityResult,
  EligibilityStatus,
  FindingType,
  ProposalSection,
} from "@/types/cosmos";
import type { RequirementStatus } from "@/types/rfp";

// ---------------------------------------------------------------------------
// Eligibility
// ---------------------------------------------------------------------------

export interface EligibilityCounts {
  total: number;
  passed: number;
  check: number;
  failed: number;
}

export interface EligibilityReport {
  procurement_id: string;
  /** FAIL > CHECK > PASS 순으로 종합한 판정 */
  verdict: EligibilityStatus;
  counts: EligibilityCounts;
  evaluated_at: string;
  /** 공고 원문 필드를 실제로 사용할 수 있었는지 */
  notice_available: boolean;
  /** 파싱된 RFP 요구사항을 사용할 수 있었는지 */
  requirements_available: boolean;
  /** LLM 보강을 실제로 사용했는지 (없어도 규칙 결과는 완전하다) */
  llm_used: boolean;
  results: EligibilityResult[];
  /** 다회사 구조: 판정이 고정된 회사·근거 범위. 지역 규칙에 쓴 활동 지역 */
  organization_id?: string | null;
  evidence_scope?: string | null;
  legacy_result?: boolean;
  regions_used?: string[];
  /** 참가자격 조항 (19차 §4-B) — 입찰공고문에서 가져온 절. 옛 백엔드에는 없다. */
  clause_document?: string | null;
  clause_count?: number;
  clause_pages?: string | null;
  clauses_status?: "ok" | "no_section" | "image" | "error" | "not_fetched";
  /** 참가자격 조항 줄의 종류별 개수 (20차 §4-B). 줄 수가 곧 조항 수다. */
  clause_summary?: Record<string, number>;
  /** 담당자 확인 수 (20차 §4-C). 기록이 없는 조항은 pending(확인 전)에 든다. */
  review?: { met: number; unmet: number; pending: number; stale: number };
  /** 조항을 읽은 문서와 원본 내려받기 링크 (20차 §4-E-2) — 나라장터 https 가 아니면 url 없음. */
  clause_documents?: ClauseDocument[];
}

export interface ClauseDocument {
  source_document: string;
  name: string;
  format?: string | null;
  url?: string | null;
}

/** PUT /api/eligibility/{id}/review/{clause_id} 본문. 충족·미충족은 note 필수(없으면 422). */
export interface ClauseReviewRequest {
  state: "met" | "unmet" | "pending";
  note?: string | null;
  decided_by: string;
  /** 화면이 읽은 이 조항의 확인 시각(43차 M25) — 없던 칸이면 null. 그사이 남이 확인했으면 409. */
  expected_decided_at?: string | null;
}

// ---------------------------------------------------------------------------
// Proposal
// ---------------------------------------------------------------------------

export type GenerationMethod = "RULE" | "LLM";

/** 실제로 생성된 제안서 섹션. 데모 ProposalSection에 생성 근거 통계를 덧붙인 형태다. */
export interface GeneratedProposalSection extends ProposalSection {
  procurement_id: string;
  generated_at: string | null;
  generation_method: GenerationMethod;
  /** 필수 요구사항 총수 */
  mandatory_total: number;
  requirements_with_sentence: number;
  /** 문장을 만들지 않은 요구사항 — 커버리지를 지어내지 않고 그대로 드러낸다 */
  requirements_without_sentence: string[];
  evidence_grounded_count: number;
  rfp_grounded_count: number;
  needs_review_count: number;
  /** 다회사 구조: 이 초안이 고정된 회사·근거 범위. 레거시(공개 위치) 결과는 organization_id=null */
  organization_id?: string | null;
  evidence_scope?: "internal" | "public_demo" | "explicit_test" | null;
  legacy_result?: boolean;
  /** 어떤 회사의 어떤 자료를 몇 건 썼는가 (EvidenceScopeInfo) */
  evidence_summary?: import("@/types/organization").EvidenceScopeInfo | null;
}

/** 제안서 **전체** 초안 (POST /api/proposal/generate/full · GET …/full) — 섹션 여러 개 (28차 사업계획서 작성 페이지). */
export interface ProposalDocumentView extends Omit<GeneratedProposalSection, "sentences" | "title" | "id"> {
  id: string;
  title: string;
  sections: GeneratedProposalSection[];
  /** 사업계획서 작성(Claude) — AI 다듬기 실패 섹션 수 · 첫 사유 / 있던 AI 초안을 지켰는가 (28차 검수 R1-01) */
  llm_note?: string | null;
  kept_llm_draft?: boolean;
  /** 이 판이 저장됐는가 — false 면 내려받기(저장된 판)를 숨긴다(30차 R29-03). */
  stored?: boolean;
}

// ---------------------------------------------------------------------------
// Auditor
// ---------------------------------------------------------------------------

export type DetectedBy = "RULE" | "AI_EXTRACTION";

export interface AuditFindingDetail extends AuditFinding {
  /** 이 발견을 만든 계층 (규칙 / LLM 2차 판단) */
  detected_by: DetectedBy;
  score: number | null;
}

export interface AuditCoverage {
  total: number;
  covered: number;
  partial: number;
  missing: number;
  missing_requirement_ids: string[];
  partial_requirement_ids: string[];
  /** 추출 상한에 잘려 검사 대상에서 빠진 요구사항이 있으면 true. 이때 total은 문서 전체가 아니다. */
  truncated: boolean;
  /** 상한 적용 전 후보 수 ("185건 중 120건만 검사" 표기용) */
  candidate_count: number | null;
}

export interface RequirementAuditState {
  requirement_id: string;
  requirement_type: "mandatory" | "optional";
  status: RequirementStatus;
  score: number;
  matched_sentence_id: string | null;
  page: number | null;
  method: DetectedBy;
  reason: string | null;
}

export interface ProposalSentenceRef {
  id: string;
  index: number;
  text: string;
}

/** 실제 Auditor 실행 결과 (POST /api/auditor/run). */
export interface AuditRunResult {
  id: string;
  procurement_id: string;
  created_at: string;
  coverage: AuditCoverage;
  counts: Record<string, number>;
  findings: AuditFindingDetail[];
  sentence_count: number;
  llm_used: boolean;
  llm_note: string | null;
  requirement_states: RequirementAuditState[];
  sentences: ProposalSentenceRef[];
  /** 업로드 검사일 때 원본 파일명 */
  source_document: string | null;
  organization_id?: string | null;
  evidence_scope?: string | null;
  legacy_result?: boolean;
}

// ---------------------------------------------------------------------------
// 담당자 최종 검토 (Human Review) — backend/app/schemas/review.py
// ---------------------------------------------------------------------------

/** pending: 검토 전 · on_hold: 보류 · rejected: 불참(No-Go) · approved: 제출 가능 */
export type ReviewStatus = "pending" | "on_hold" | "rejected" | "approved";

/** 승인 전에 담당자가 직접 확인해야 하는 항목. 전부 true여야 승인할 수 있다. */
export interface ReviewChecklist {
  auditor_findings_reviewed: boolean;
  eligibility_check_resolved: boolean;
  evidence_confirmed: boolean;
  numbers_verified: boolean;
}

/** 저장된 검토 결과 (GET /api/review/{id}). */
export interface ReviewDecision {
  procurement_id: string;
  status: ReviewStatus;
  checklist: ReviewChecklist;
  reviewer: string;
  note: string | null;
  decided_at: string;
  /** 무엇을 보고 결정했는지 — 승인 근거 */
  audit_run_id: string | null;
  proposal_id: string | null;
  coverage_covered: number | null;
  coverage_total: number | null;
}

/** 저장 요청 (POST /api/review). decided_at은 서버가 찍는다. */
export interface ReviewDecisionRequest {
  procurement_id: string;
  status: ReviewStatus;
  checklist: ReviewChecklist;
  reviewer: string;
  note?: string | null;
  audit_run_id?: string | null;
  proposal_id?: string | null;
}

// ---------------------------------------------------------------------------
// Auditor 발견 항목 해결 처리 — backend/app/schemas/finding_resolution.py
// ---------------------------------------------------------------------------

export type ResolutionStatus = "open" | "resolved";

/**
 * 발견 항목 1건에 대한 담당자 처리 기록. AI가 아니라 사람이 정하며(method=HUMAN),
 * 키는 검사마다 바뀌는 AF-id가 아니라 안정 키(`findingResolutionKey`)다.
 */
export interface FindingResolution {
  procurement_id: string;
  key: string;
  status: ResolutionStatus;
  finding_type: FindingType;
  requirement_id: string | null;
  finding_id: string | null;
  audit_run_id: string | null;
  reviewer: string;
  note: string | null;
  method: "HUMAN";
  decided_at: string;
}

export interface FindingResolutionRequest {
  key: string;
  status: ResolutionStatus;
  finding_type: FindingType;
  requirement_id?: string | null;
  finding_id?: string | null;
  audit_run_id?: string | null;
  reviewer: string;
  note?: string | null;
}

export interface FindingResolutionList {
  procurement_id: string;
  resolutions: FindingResolution[];
}


// ---------------------------------------------------------------------------
// 분석 준비 상태 — backend/app/api/auditor.py (readiness / change-impact)
// ---------------------------------------------------------------------------

/**
 * 제안서가 어느 요구사항 집합 기준인가.
 *
 * `stale_requirements` 이면 **오래된 제안서를 최신 결과처럼 표시하지 않는다.**
 * 실측으로 필수 32건 기준 초안이 55건 집합과 비교돼 26건이 한꺼번에 미반영 HIGH 가 됐다.
 */
export type ProposalBasis = "no_proposal" | "current" | "stale_requirements" | "unknown_basis";

export interface AuditReadiness {
  ready: boolean;
  basis: ProposalBasis;
  blockers: string[];
  message: string;
  requirement_set_id: string | null;
  requirement_set_hash: string | null;
  requirement_set_version: number | null;
  proposal_version: number | null;
  requirement_count: number | null;
  mandatory_count: number | null;
  /** 제안서를 만들 때의 필수 요구사항 수 (그때의 분모) */
  previous_mandatory_total: number | null;
  /**
   * **공고가 마지막으로 바뀐 시각** (0923 §3-3 · ISSUE-093).
   *
   * 저장된 결과가 이 시각보다 앞서 만들어졌으면 「다시 실행 필요」다. null 이면
   * 「안 바뀌었다」가 아니라 **「모른다」**이므로 화면은 아무 말도 덧붙이지 않는다.
   * 옛 배포 스냅샷에는 이 필드가 없다.
   */
  notice_changed_at?: string | null;
  /** 담당자가 고를 수 있는 다음 행동. 화면 버튼과 1:1. */
  actions: Array<{ key: string; label: string }>;
}

export interface ChangeImpactGroup {
  item_type: string;
  label: string;
  total: number;
  /** 기존 제안서가 이미 의미상 대응하고 있는 항목 */
  already_covered: number;
  /** 새 문장이 필요한 항목 */
  needs_sentence: number;
  examples: Array<{ requirement_id: string | null; title: string }>;
}

export interface ChangeImpact {
  available: boolean;
  reason?: string;
  /**
   * 무엇과 견줬는가.
   *  proposal_basis           — 이 초안이 실제로 보고 만든 판
   *  latest_previous_version  — 그 판을 못 찾아 «직전 판»으로 대신 견줬다
   *  null                     — 견줄 판이 없다
   * 이것이 latest_previous_version 인데 화면이 「제안서 대비 변화」라고 말하면,
   * 준비 상태의 「필수 32건 → 54건」과 여기 「새로 발견 0건」이 한 화면에서 서로를 부정한다.
   */
  compared_to?: "proposal_basis" | "latest_previous_version" | null;
  /** 초안의 기준 판을 찾았는가. available=false 면 「제안서 대비」라고 부르면 안 된다. */
  proposal_comparison?: {
    available: boolean;
    reason?: string | null;
    requirement_set_hash?: string | null;
    mandatory_total?: number | null;
  };
  previous?: {
    requirement_set_id: string | null;
    requirement_set_version: number | null;
    requirement_count: number;
    /** 견준 판의 필수 건수. 준비 상태 문구의 「필수 N건 → M건」과 대조하기 위한 값. */
    mandatory_count?: number | null;
  };
  current: { requirement_set_id: string | null; requirement_count: number; mandatory_count: number };
  counts: Record<string, number>;
  groups: ChangeImpactGroup[];
  entries?: Array<Record<string, unknown>>;
  uncertain?: Array<Record<string, unknown>>;
}
