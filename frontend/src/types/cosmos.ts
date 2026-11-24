/** backend/app/schemas/demo.py 의 DemoCosmosScenario 와 1:1 대응. */

export type EligibilityStatus = "PASS" | "CHECK" | "FAIL";
export type EligibilityMethod = "RULE" | "AI_EXTRACTION" | "HUMAN";
export type GroundingType =
  | "RFP_GROUNDED"
  | "COMPANY_EVIDENCE_GROUNDED"
  | "AI_SUGGESTION";
export type FindingType =
  | "missing_requirement"
  | "number_mismatch"
  | "unsupported_claim"
  | "unchecked_condition"
  | "missing_document"
  // (2.10.0) 평가본 공고에서 올린 글에 회사 식별 낱말이 남음 — 값은 싣지 않는다
  | "blind_identity";
// 제출에 실제로 어떤 영향을 주는가.
//   critical = 참가 자체를 막는다 · high = 배점·필수 제출물 · medium = 보완 가능
//   low = 계약 일반조건 등 본문에 다시 적지 않아도 되는 것 · info = 참고
// 옛 배포 스냅샷에는 high/medium/low 만 있다.
export type Severity = "critical" | "high" | "medium" | "low" | "info";

export interface SemanticMatch {
  fit_score: number;
  label: string;
  matched_domains: string[];
  reason: string;
  demo: true;
}

export interface EligibilityResult {
  rule_id: string;
  label: string;
  status: EligibilityStatus;
  method: EligibilityMethod;
  source: string;
  reason: string;
  requirement_id: string | null;
  /** **무엇을 갖추면 이 판정이 뒤집히는가** (0921 §4-B). 없으면 길이 없다는 뜻이다. */
  unlock_condition?: string | null;
  /** 공고문(또는 제안요청서·RFP)의 어느 조항에서 나왔나 — 「QC-01,QC-03」 (19차 §4-B). */
  clause_id?: string | null;
  /** 확인 필요일 때 누가 채워야 하나 — 회사 값이 비었다(company) · 원문을 사람이 읽어야 한다(notice). */
  check_side?: "company" | "notice" | null;
  /** 그중 하나만 갖추면 되는 조건들 (0922 §4-A-5). 옛 백엔드에는 없다. */
  unlock_options?: string[];
  /** 조항 원문 · 쪽 · 출처 문서(입찰공고문·제안요청서·RFP) · 종류 (20차 §4-B — 조항마다 한 줄). */
  clause_text?: string | null;
  page?: number | null;
  source_document?: string | null;
  kind?: string | null;
  /**
   * 담당자 확인 (20차 §4-C) — met(충족 → 가능) · unmet(미충족 → 불가) · pending(보류) ·
   * stale(확인한 뒤 조항 원문이 바뀌었다 — 다시 확인). 기록이 없으면 없음.
   */
  review_state?: "met" | "unmet" | "pending" | "stale" | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
}

export interface EvidenceDocument {
  id: string;
  document_name: string;
  doc_type: string;
  page: number | null;
  source_text: string;
  /** 합성 자료면 true. 비식별 처리한 실제 자료면 false. */
  synthetic: boolean;
  /** 실제 자료를 비식별 처리했으면 true */
  anonymized?: boolean;
}

export interface EvidenceLink {
  evidence_id: string;
  requirement_id: string;
  similarity_score: number;
  selected: boolean;
  note: string | null;
}

export interface ProposalSentence {
  id: string;
  text: string;
  grounding_type: GroundingType;
  /** AI 가 다듬기 전 근거 유형(44차 M5) — 있으면 「AI 다듬음 — 근거: …」. 옛 응답에는 없다. */
  refined_from?: GroundingType | null;
  requirement_id: string | null;
  evidence_id: string | null;
  needs_review: boolean;
}

export interface ProposalSection {
  id: string;
  title: string;
  sentences: ProposalSentence[];
}

export interface AuditFinding {
  id: string;
  finding_type: FindingType;
  severity: Severity;
  requirement_id: string | null;
  evidence_id: string | null;
  sentence_id: string | null;
  source_page: number | null;
  source_text: string | null;
  proposal_text: string | null;
  /** 해결 기록 키 — 서버가 새 말로 바꾸기 전 원문으로 만들어 싣는다(33차 R32-12). 옛 응답 · 데모 자료엔 없다. */
  resolution_key?: string | null;
  recommendation: string;
  /** 실검사(backend/app/schemas/audit.py)에서만 채워진다. 데모 시나리오에는 없다. */
  detected_by?: "RULE" | "AI_EXTRACTION";
  score?: number | null;
  /** 이 요구사항에 어디서 답하는가. 심각도의 근거이자 묶음 축이다. */
  response_scope?: string | null;
  /** 같은 원인에서 나온 발견을 묶는 키·이름. 옛 스냅샷에는 없다. */
  group_key?: string | null;
  group_label?: string | null;
  /**
   * 묶음 표시 순서. 작을수록 먼저 — 참가 불가 위험 10 … 참고 항목 90.
   * 백엔드(auditor_service._GROUP_RANK)가 정한다. 옛 저장본에는 없어서 기본 80(=나머지)으로 본다.
   * 화면이 순서를 따로 정하면 백엔드가 「참가 불가 위험을 맨 위로」라고 정한 것이 무시된다.
   */
  group_rank?: number | null;
}

export interface AuditRun {
  id: string;
  findings: AuditFinding[];
}

export interface DemoCosmosScenario {
  procurement_id: string;
  source: "demo_synthetic";
  note: string;
  semantic_match: SemanticMatch;
  eligibility: EligibilityResult[];
  evidence_documents: EvidenceDocument[];
  evidence_links: EvidenceLink[];
  proposal: ProposalSection;
  audit: AuditRun;
}
