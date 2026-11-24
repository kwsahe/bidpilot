/**
 * Critical Condition · Action Checklist · GO/HOLD/NO_GO 결정 (backend/app/schemas/{critical_condition,action,decision}.py).
 *
 * - 미해결 BLOCKER가 있으면 GO를 저장할 수 없다 (backend가 422로 막는다).
 * - CLEARED는 사람만 만든다. 시스템은 절대 자동으로 해결 처리하지 않는다.
 */

export type ConditionStatus = "BLOCKER" | "ACTION" | "CHECK" | "CLEARED" | "INFO";
export type ConditionSeverity = "high" | "medium" | "low";
export type ConditionMethod = "RULE" | "AI_EXTRACTION" | "HUMAN";

/** 실적 조건 문장에서 읽어낸 기준. null이면 문장에 그 기준이 없다. */
export interface PerformanceCriteria {
  years: number | null;
  min_count: number | null;
  /** 천원 */
  min_amount_thousand: number | null;
  amount_mode: "single" | "cumulative" | null;
  domains: string[];
  agency_types: string[];
  similar: boolean;
  source_text: string;
}

export interface LedgerHit {
  seq: number;
  year: string;
  period: string;
  field: string;
  title: string;
  agency: string;
  summary: string;
  amount_thousand_krw: number | null;
  amount_basis: string;
  evidence_note: string;
  matched_on: string[];
}

/** 회사 실적 원장(외부 가능 행)과 대조한 힌트. PASS가 아니며 최종 판단은 사람이 한다. */
export interface PerformanceMatchReport {
  criteria: PerformanceCriteria;
  ledger_available: boolean;
  ledger_date: string | null;
  eligible_rows: number;
  hits: LedgerHit[];
  hit_count: number;
  total_amount_thousand: number;
  max_amount_thousand: number | null;
  /** true 충족해 보임 · false 원장 기준 부족 · null 판정 기준 없음/원장 없음 */
  likely_sufficient: boolean | null;
  verdict_hint: string;
  notes: string[];
  method: string;
}

export interface CriticalCondition {
  id: string;
  procurement_id: string;
  condition_type: string;
  title: string;
  content: string;
  severity: ConditionSeverity;
  status: ConditionStatus;
  /** 규칙이 처음 매긴 상태 (사람이 바꿔도 남는다) */
  detected_status: ConditionStatus;
  due_at: string | null;
  action_required: boolean;
  owner: string | null;
  requirement_id: string | null;
  source_page: number | null;
  source_text: string | null;
  /** 공고 API 필드 근거 ("field=value") */
  source_field: string | null;
  extraction_method: ConditionMethod;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  /** 실적 조건에만: 원장 대조 결과 (원장이 없으면 null) */
  ledger_match?: PerformanceMatchReport | null;
}

export interface ConditionCounts {
  total: number;
  blocker: number;
  action: number;
  check: number;
  cleared: number;
  info: number;
}

export interface ConditionGate {
  can_go: boolean;
  reason: string;
  blocker_ids: string[];
}

/** 저장된 조건 보고서가 «지금 요구사항 집합» 기준인가. unknown 은 «모른다»이지 «최신»이 아니다. */
export type ConditionFreshness = "current" | "stale" | "unknown";

export interface CriticalConditionReport {
  procurement_id: string;
  detected_at: string;
  method: ConditionMethod;
  notice_available: boolean;
  requirements_available: boolean;
  eligibility_used: boolean;
  counts: ConditionCounts;
  gate: ConditionGate;
  conditions: CriticalCondition[];
  /** 탐지 당시의 요구사항 집합 해시. 옛 저장본에는 없다. */
  requirement_set_hash?: string | null;
  requirement_set_id?: string | null;
  /** 읽는 시점 요구사항 파일의 해시. 파일이 없으면 null. */
  current_requirement_set_hash?: string | null;
  freshness?: ConditionFreshness;
  /**
   * 「지금 집합 기준임이 확인되지 않았다」. 옛 저장본(해시 없음)도 true 다.
   * true 라고 해서 조건을 감추면 안 된다 — 감추면 지금보다 나빠진다. 상태만 함께 적는다.
   */
  stale?: boolean;
  stale_reason?: string | null;
}

export interface ConditionUpdateRequest {
  status: ConditionStatus;
  reviewer: string;
  note?: string | null;
  owner?: string | null;
}

// ---------------------------------------------------------------------------
// Action Checklist
// ---------------------------------------------------------------------------

export type ActionStatus = "todo" | "doing" | "done" | "blocked" | "na";
export type ActionPriority = "urgent" | "high" | "normal" | "low";

export interface ActionItem {
  id: string;
  procurement_id: string;
  title: string;
  status: ActionStatus;
  priority: ActionPriority;
  due_at: string | null;
  owner: string | null;
  source_condition_id: string | null;
  requirement_id: string | null;
  evidence: string | null;
  note: string | null;
  origin: "auto" | "manual";
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ActionCounts {
  total: number;
  todo: number;
  doing: number;
  done: number;
  blocked: number;
  na: number;
  overdue: number;
}

export interface ActionChecklist {
  procurement_id: string;
  items: ActionItem[];
  counts: ActionCounts;
  updated_at: string | null;
}

export interface ActionCreateRequest {
  title: string;
  priority?: ActionPriority;
  due_at?: string | null;
  owner?: string | null;
  source_condition_id?: string | null;
  requirement_id?: string | null;
  note?: string | null;
}

export interface ActionUpdateRequest {
  title?: string;
  status?: ActionStatus;
  priority?: ActionPriority;
  due_at?: string | null;
  owner?: string | null;
  evidence?: string | null;
  note?: string | null;
  clear_due_at?: boolean;
}

// ---------------------------------------------------------------------------
// GO / HOLD / NO_GO
// ---------------------------------------------------------------------------

export type DecisionStatus = "GO" | "HOLD" | "NO_GO" | "UNREVIEWED";

export interface GateSnapshot {
  can_go: boolean;
  blocker_count: number;
  reason: string;
}

export interface BidDecision {
  procurement_id: string;
  status: DecisionStatus;
  reasons: string[];
  decided_by: string | null;
  decided_at: string | null;
  note: string | null;
  gate: GateSnapshot | null;
}

export interface DecisionRequest {
  status: DecisionStatus;
  reasons: string[];
  decided_by: string;
  note?: string | null;
  /** 처음 읽은 결정의 시각(44차 M4) — 그사이 남이 정했으면 서버가 409. */
  expected_decided_at?: string | null;
}
