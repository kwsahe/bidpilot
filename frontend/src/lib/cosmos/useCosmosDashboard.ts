"use client";

/**
 * Evidence Cosmos 대시보드 데이터 훅.
 *
 * - 나라장터 실공고 후보 목록(getProcurements)을 불러와 공고 선택기를 채운다.
 * - 선택한 공고에 따라 데이터를 다르게 모은다.
 *   · 데모 시나리오(synthetic-rfp-0001): 요구사항 + 증빙/제안서/Auditor 데모 시나리오
 *   · 실제 나라장터 공고: 요구사항만 (없으면 null). 증빙·제안서·Auditor는 아직 없다.
 * - 선택은 URL(?notice=)과 localStorage에 남겨 새로고침해도 유지된다.
 * - 로드 완료/분석 실행 시 stage 1→8 순차 등장 (reducedMotion이면 즉시 8)
 * - reviewDecision(Human Review)은 여기서 보관하고 buildCosmosGraph로 재계산하며,
 *   사람의 승인/보류는 화면 state 로만 두지 않고 `/api/review` 에 저장·복원한다
 *
 * setState는 effect 안에서 동기 호출하지 않고 promise 콜백·타이머·이벤트 핸들러에서만 부른다.
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  clearSelectedSupport,
  isSupportProgramId,
  readSelection,
  readSelectionServer,
  subscribeSelection,
  writeSelection,
} from "@/lib/selection";

import { readCurrentUser } from "@/lib/currentUser";
import {
  ApiError,
  createAction,
  deleteAction,
  detectConditions,
  evaluateEligibility,
  getEligibilityReport,
  saveClauseReview,
  generateProposal,
  getActions,
  getBusinessOpportunities,
  getCapability,
  getConditions,
  getDecision,
  getDemoCosmosScenario,
  getFindingResolutions,
  getHealth,
  getProcurements,
  getProposal,
  getReview,
  getRfpRequirements,
  getSupportProgram,
  askRfpConsent,
  parseRfp,
  RFP_PARSE_PHASE_LABEL,
  type RfpConsent,
  getAuditReadiness,
  getLatestAuditRun,
  runAuditor,
  runAuditorUpload,
  saveDecision,
  saveFindingResolution,
  saveReview,
  updateAction,
  updateCondition,
} from "@/lib/api";
import type {
  ActionCreateRequest,
  ActionUpdateRequest,
  ConditionUpdateRequest,
  DecisionRequest,
} from "@/types/gate";
import type {
  AuditRunResult,
  ClauseReviewRequest,
  FindingResolution,
  ResolutionStatus,
  ReviewChecklist,
  ReviewDecision as SavedReview,
  ReviewStatus,
} from "@/types/analysis";
import type { AuditFinding } from "@/types/cosmos";
import type {
  CandidateTier,
  ProcurementListResponse,
  ProcurementSource,
  RecommendationGrade,
} from "@/types/procurement";
import { semanticFitOf } from "@/types/procurement";
import type { EligibilityGate, SupportApplicationResult, UnifiedOpportunity, UnifiedOpportunityListResponse } from "@/types/opportunity";
import type { ItemType, RfpParseResult } from "@/types/rfp";
import type { AnalysisContextParams } from "@/types/organization";
import { usePeriodDays } from "@/lib/period";
import { describeFailure, sourceFailure } from "@/lib/errors";
import { DEFAULT_ORGANIZATION_ID, analysisContext } from "@/lib/organization";

import {
  DEMO_NOTICE,
  DEMO_NOTICE_LABEL,
  DEMO_PROCUREMENT_ID,
  isDemoProcurementId,
} from "./demoNotice";
import { CANDIDATE_TIER_LABELS, CONDITION_STATUS_LABELS, ELIGIBILITY_LABELS, eligibilityTallyText } from "./format";
import { STEP_NAMES, SYNTHETIC_NOTICE } from "@/lib/terms";
import {
  EMPTY_ANALYSIS,
  NOT_RUN_SUMMARY,
  WORKFLOW_STEPS,
  buildCosmosGraph,
  findingResolutionKey,
  proposalDraftText,
  type CosmosAnalysis,
  type CosmosGraph,
  type CosmosSource,
  type ReviewDecision,
  type WorkflowStage,
} from "./graph";

/** 최초 로드 순차 등장: 7단계 × 340ms ≈ 2.4s */
const INITIAL_REVEAL_INTERVAL_MS = 340;

/**
 * 선택기에 실어 보낼 기업마당 지원사업 수.
 *
 * 100건을 전부 받아 드롭다운에 붓으면 찾을 수가 없다. 백엔드가 이미 회사 기준 검토
 * 우선순위로 정렬해 보내므로 위에서 잘라 받고, 전체는 사업기회 목록 화면에서 본다.
 */
const SUPPORT_PICKER_LIMIT = 12;

/**
 * 기업마당 지원사업 id 인가.
 *
 * 대시보드는 나라장터 입찰을 8단계로 분석하는 화면이고, 지원사업은 신청자격 → 필수·우대조건 →
 * 신청기간 → 제출서류 → 회사 적합 근거 → 사업계획서 → 신청 전 점검 7단계다. 같은 화면 안에서
 * 열되 **불러오는 경로가 다르다** — 이 판정 하나로 갈린다.
 *
 * 이 구분이 없으면 loadDashboard 가 나라장터 목록에서 id 를 못 찾아(:736) 조용히 데모 공고로
 * 되돌리고 저장된 선택까지 지운다. 화면에는 「고른 것과 다른 공고」가 뜬다.
 */
export { isSupportProgramId };
/** 분석 실행 순차 등장: 700ms 간격 */
const ANALYSIS_REVEAL_INTERVAL_MS = 700;
const FINAL_STAGE: WorkflowStage = 8;

const NOTICE_QUERY_KEY = "notice";
const NOTICE_STORAGE_KEY = "bidpilot.notice.v1";


export type DashboardStatus = "loading" | "error" | "empty" | "ready";

/** 실행 타임라인 항목 — 실제 요청 상태와 1:1로 연결된다 (가짜 완료 표시 금지). */
export type RunPhaseKey =
  | "notice"
  | "candidate"
  | "fit"
  | "capability"
  | "eligibility"
  | "conditions"
  | "parse"
  | "evidence"
  | "proposal"
  | "audit";

export type RunPhaseStatus =
  /** 아직 시작 전 */
  | "pending"
  /** backend 요청 진행 중 */
  | "running"
  /** 실제 결과를 받음 */
  | "done"
  /** 데모 시나리오 고정값 사용 */
  | "demo"
  /** 이 공고에서는 실행하지 않음 (사유를 detail에 남긴다) */
  | "skipped"
  /** 요청 실패 */
  | "failed";

export interface RunPhase {
  key: RunPhaseKey;
  status: RunPhaseStatus;
  /** 결과 요약 또는 건너뛴 사유 */
  detail: string | null;
}

export type RunLog = Record<RunPhaseKey, RunPhase>;

export const RUN_PHASE_ORDER: RunPhaseKey[] = [
  "notice",
  "candidate",
  "fit",
  "capability",
  "eligibility",
  "conditions",
  "parse",
  "evidence",
  "proposal",
  "audit",
];

export const RUN_PHASE_LABELS: Record<RunPhaseKey, string> = {
  notice: "공고 메타데이터 확인",
  candidate: "AI·교육 관련성 분류",
  // 회사와 무관한 고정 이름(「SampleEdu 적합도」)을 쓰면 다른 회사를 골라도 샘플에듀 이름이 나온다 (DSH-15).
  fit: "우리 회사 적합도",
  capability: "개발 수행역량 판정",
  eligibility: "참가 자격 검토",
  // 영어 · 내부 용어 대신 단계 이름 사전의 낱말 (DSH-32).
  conditions: "참가 차단 조건 찾기",
  parse: "요구사항 정리",
  evidence: "근거 문서 연결",
  proposal: "제안서 초안 준비",
  audit: STEP_NAMES[7],
};

/** 조건 탐지 결과 한 줄 — 「BLOCKER · ACTION · CHECK」 대신 화면 낱말 (DSH-32). */
function conditionCountsText(counts: { blocker: number; action: number; check: number; cleared?: number }): string {
  const L = CONDITION_STATUS_LABELS;
  return `${L.BLOCKER} ${counts.blocker} · ${L.ACTION} ${counts.action} · ${L.CHECK} ${counts.check}${counts.cleared ? ` · ${L.CLEARED} ${counts.cleared}` : ""}`;
}

function emptyRunLog(): RunLog {
  return Object.fromEntries(
    RUN_PHASE_ORDER.map((key) => [key, { key, status: "pending", detail: null }]),
  ) as RunLog;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; source: CosmosSource };

/** 공고 선택기 항목. */
export interface NoticeOption {
  id: string;
  title: string;
  agency: string;
  deadline_at: string | null;
  /** 키워드 등급 (실공고만) */
  tier: CandidateTier | null;
  /** 검토 우선순위 (1부터). 백엔드가 추천 점수 순으로 매겨 보낸다. */
  rank: number | null;
  /** 추천등급 A/B/C/D/NO_GO */
  grade: RecommendationGrade | null;
  /** 데모 시나리오 항목인지 */
  demo: boolean;
  /** 공고번호(차수 포함). 사람이 공고를 특정할 때 쓰는 번호다. */
  noticeNo: string | null;
  /** 같은 공고번호로 묶인 차수 개수. 1보다 크면 「차수 N건 중 최신」을 표시한다. */
  revisionCount: number;
  /**
   * 시연용으로 저장해 둔 고정 공고인가.
   *
   * 선택기는 마감 공고를 기본으로 숨기는데(ISSUE-035), 고정 공고는 저장본이 있어
   * 마감 뒤에도 분석 화면이 그대로 열린다. 이 표시가 없으면 시연 동선이 날짜에 묶여
   * 마감일이 지나는 순간 준비해 둔 공고가 목록에서 사라진다.
   */
  pinned: boolean;
  /**
   * 기업마당 지원사업인가.
   *
   * 지원사업은 이 대시보드의 8단계(요구사항 → 회사 근거 → 제안서 → 제출 전 점검)를
   * 타지 않는다 — 신청자격 · 신청기간 · 제출서류 · 사업계획서로 이어지는 **다른 흐름**이고
   * 전용 화면이 따로 있다(`/support/{id}`, SupportShell). 여기 8단계에 끼워 넣으면
   * 요구사항도 제안서도 없는 공고가 전 단계 「미실행」으로 뜬다 — 그건 고장이지 기능이 아니다.
   * 그래서 목록에는 **함께 보이되** 고르면 그쪽 화면으로 보낸다.
   */
  support: boolean;
  /** 고르면 갈 곳. 지원사업만 채워진다 (`/support/{id}`). */
  route: string | null;
  /** 회사 기준 검토 우선순위 점수 (지원사업 표기용). 미확인이면 null — 0 이 아니다. */
  score: number | null;
  /** 신청 자격 게이트. FAIL 이면 점수보다 먼저 「불가」를 적는다. */
  gate: EligibilityGate | null;
  gateReason: string | null;
  /**
   * 나라장터 공고가 회사 목록(레이더 · 사업기회가 보이는 통합 목록) 밖인가 — 참가 불가이거나 실제 마감(등록 · 공고문 일정)이 지났다.
   * 통합 목록을 받았을 때만 true 가 된다. 고르기 칸은 마감 공고처럼 접고 「[불가·마감]」으로 적는다(2.0.6).
   */
  outside?: boolean;
  /**
   * **회사 방식의 순번**(같은 출처 안 · 1부터 · 37차 §3-C-4). 통합 목록을 회사 기본 정렬로 받은 `source_rank` 다 —
   * 샘플에듀 은 실무 우선순위, 그 밖은 점수순(동점이면 마감 빠른 순 · recheck29 UI-R36-03). 목록에 없으면 null(뒤로).
   */
  order?: number | null;
}

export interface NoticeListInfo {
  status: "loading" | "ready" | "error";
  source: ProcurementSource | null;
  fetchedAt: string | null;
  /** 필터 전 전체 공고 수 */
  totalFetched: number | null;
  /** 후보 공고 수 */
  count: number | null;
  /** 목록 조회 경고/실패 메시지 */
  message: string | null;
  /** 나라장터 검토 순서(통합 목록)를 못 받은 사유 — 있으면 고르기 칸이 추천등급 순임을 밝힌다(2.0.6). */
  priorityMessage?: string | null;
  /**
   * 지금 회사 · 기간의 검토 순서(통합 목록)를 아직 받는 중인가(실패해도 받은 것으로 본다). 받기 전에는 불가 · 관련 낮음을 접지 못해
   * 고르기 칸이 「220건 · 마감 41건 숨김」으로 섰다가 140건으로 바뀌었다 — 그동안은 「불러오는 중」이다(10-31 최종 점검).
   */
  priorityPending?: boolean;
  /** 받아 둔 기업마당 지원사업 전체 수 — 고르기 칸은 앞 12건만 싣는다(2.0.6 · 「(12)」만 보여 12건뿐인 줄 알았다). */
  supportTotal?: number | null;
  /** 아무 공고도 열지 못한 오류 화면인가 — 고르기 칸이 「가상 예시」를 고른 것처럼 보이지 않게(2.0.6). */
  openFailed?: boolean;
}

/** 최종 검토 저장 요청 (담당자·확인 항목은 사람이 채운다 — 시스템이 대신 체크하지 않는다). */
export interface ReviewSaveInput {
  status: ReviewStatus;
  checklist: ReviewChecklist;
  reviewer: string;
  note?: string | null;
}

/**
 * 사람의 최종 검토(Human Review) 저장 상태.
 *
 * 예전에는 화면의 「검토 승인/보류」가 **어디에도 저장되지 않는 React state** 였다.
 * 담당자가 A공고를 승인해 두고 B공고를 잠깐 열면 그 판단이 조용히 사라졌고,
 * 돌아와도 복원되지 않았다. 이제 backend `POST/GET /api/review` 에 남긴다.
 */
export interface ReviewState {
  /** 서버에 저장된 결과. null 은 «저장된 적 없음»이지 «검토하지 않기로 함»이 아니다. */
  saved: SavedReview | null;
  saving: boolean;
  /** 저장 실패 사유. 실패했으면 저장된 척하지 않는다. */
  error: string | null;
  /** 화면 토글이 서버 저장분과 다른가 (= 임시, 저장 전) */
  unsaved: boolean;
  /** POST /api/review — 승인은 확인 항목 4개를 모두 채워야 backend 가 받는다(422). 저장에 성공하면 true. */
  save: (input: ReviewSaveInput) => Promise<boolean>;
  /** 승인/보류를 되돌린다 (저장된 적이 있으면 서버에도 pending 으로 남긴다). */
  clear: () => void;
}

const EMPTY_CHECKLIST: ReviewChecklist = {
  auditor_findings_reviewed: false,
  eligibility_check_resolved: false,
  evidence_confirmed: false,
  numbers_verified: false,
};

/**
 * 저장된 검토 상태 → 화면 토글.
 *
 * `rejected`(불참)는 승인도 보류도 아니라 토글에 대응하는 값이 없다. 억지로 「보류」로
 * 옮기면 사람이 내린 «불참»이 화면에서 «보류»로 바뀌므로 null 로 두고, 저장 상태는
 * 셸의 검토 줄에 그대로 적는다.
 */
function reviewToggle(status: ReviewStatus | null | undefined): ReviewDecision {
  return status === "approved" ? "approved" : status === "on_hold" ? "hold" : null;
}

export interface CosmosDashboard {
  status: DashboardStatus;
  /** 지금 고른 공고의 검토 우선순위 (0~100, 선택 회사 기준). 모르면 null — 0 이 아니다. */
  selectedReviewPriority: number | null;
  /** status === "error" 일 때의 메시지 */
  error: string | null;
  /** 분석 실행 실패 메시지 (기존 그래프는 유지) */
  analysisError: string | null;
  /** 자격판정·제안서·Auditor 후속 로딩 중 */
  analysisLoading: boolean;
  graph: CosmosGraph | null;
  stage: WorkflowStage;
  /** 진행 중인 순차 등장을 취소하고 단계를 고정한다 */
  setStage: (stage: WorkflowStage) => void;
  /** 등장 애니메이션이 끝났는가. 끝난 뒤에 «가장 먼저 처리할 단계»로 내려앉는다. */
  revealDone: boolean;
  /**
   * 등장을 몇 번 시작했나. 공고를 바꿀 때만이 아니라 분석 실행·회사 전환으로 **같은 공고를 다시 불러올 때도**
   * 오른다 — 화면은 이 값이 바뀔 때마다 한 번 내려앉는다 (21차).
   */
  revealRun: number;
  analyzing: boolean;
  reviewDecision: ReviewDecision;
  setReviewDecision: (decision: ReviewDecision) => void;
  /** 사람의 최종 검토 — 서버 저장·복원 상태 */
  review: ReviewState;
  reload: () => void;
  /** 고르기 칸 목록만 다시 받는다(나라장터 목록 + 통합 순위) — 보는 공고 · 분석은 그대로(2.0.7 「찾는 낱말」 바로 찾기 뒤) */
  reloadLists: () => void;
  runAnalysis: () => void;
  /** 선택기에 표시할 공고 목록 (데모 항목 + 실공고 후보) */
  notices: NoticeOption[];
  selectedNoticeId: string;
  selectNotice: (id: string) => void;
  noticeList: NoticeListInfo;
  /** 요청한 공고가 목록에 없어 데모로 돌아왔을 때의 사유. 화면 상단 띠에 쓴다 (ISSUE-020). */
  staleNotice: string | null;
  /** 기업마당 목록을 못 받았을 때의 사유. null 이면 정상(0건일 수도 있다). */
  supportError: string | null;
  /**
   * 지금 고른 것이 기업마당 지원사업이면 그 신청 분석. 입찰이면 null.
   *
   * 이것이 null 이 아니면 화면은 **입찰 8단계 대신 지원사업 7단계**를 그린다.
   * 두 흐름은 단계도 말도 다르므로 섞어 그리지 않는다.
   */
  supportResult: SupportApplicationResult | null;
  /** 지원사업 분석 로딩 상태. idle 은 «입찰을 보고 있다»는 뜻이다. */
  supportLoad: { status: "idle" | "loading" | "ready" | "error"; message: string | null };
  /** 실제 분석 API 실행 상태·동작 (제안서 생성 / Auditor 검사 / 자격 재판정) */
  actions: AnalysisActions;
  /** 실행 타임라인 — 각 단계의 실제 요청 상태 */
  runLog: RunLog;
  /** 현재 공고 분석이 고정된 회사·근거 범위 (다회사 구조) */
  context: AnalysisContextParams;
  /** 3D 에서 펼쳐 본 요구사항 유형. null 이면 집계 Overview. */
  expandedCategory: ItemType | null;
  /** 같은 값을 다시 누르면 접힌다(= 집계 Overview 로 돌아간다). */
  toggleCategory: (key: ItemType | null) => void;
}

/** 사용자가 화면에서 직접 실행하는 실분석 동작. */
export interface AnalysisActions {
  /**
   * AI 초안이 붙는가 (`LLM_LIVE` + 크레딧 · ISSUE-130 · prompt_06 §4-A).
   *
   * `null` 은 **모른다**(`/health` 를 못 읽었거나 옛 백엔드). 모를 때는 화면이 아무 말도
   * 하지 않는다 — 꺼졌다고 단정하면 켜 놓고 시연하는 사람이 반대로 속는다.
   *
   * 순위·유사도와 다른 문이다. 담당자 방침이 「순위와 유사도는 규칙만, AI 는 제안서·
   * 사업계획서 초안과 제출 전 점검에만」이다.
   */
  aiDraft: boolean | null;
  proposalBusy: boolean;
  auditBusy: boolean;
  eligibilityBusy: boolean;
  proposalError: string | null;
  auditError: string | null;
  eligibilityError: string | null;
  /** POST /api/proposal/generate — 핵심 섹션을 새로 생성한다 */
  generateProposal: () => void;
  /** POST /api/auditor/run — 붙여넣은 초안을 검사한다 */
  runAudit: (proposalText: string, options?: { useLlm?: boolean }) => void;
  /** POST /api/auditor/run/upload — 제안서 파일을 올려 검사한다 */
  runAuditUpload: (file: File, options?: { useLlm?: boolean }) => void;
  /** POST /api/eligibility/evaluate — LLM 보강을 켜고 다시 판정한다 */
  refreshEligibility: (options?: { useLlm?: boolean }) => void;
  /** 참가자격 조항 확인을 저장 중인 조항 id (20차 §4-C). 없으면 null. */
  clauseReviewBusy: string | null;
  clauseReviewError: string | null;
  /** PUT /api/eligibility/{id}/review/{clause_id} — 담당자가 조항을 충족·미충족·보류로 확인한다 */
  /** 저장됐으면 true — 화면은 그때만 입력칸을 비운다(실패하면 적은 글이 남는다 · DTL-09). */
  saveClauseReview: (clauseId: string, body: ClauseReviewRequest) => Promise<boolean>;
  /** 발견 항목 해결/재오픈 저장 중 */
  resolutionBusy: boolean;
  resolutionError: string | null;
  /** PUT /api/auditor/{id}/resolutions — 담당자가 발견 항목을 해결로 전환하거나 다시 연다 */
  setFindingResolution: (
    finding: AuditFinding,
    body: { status: ResolutionStatus; reviewer: string; note?: string | null },
  ) => Promise<boolean>;
  /** 조건·체크리스트·결정 요청 진행 중 */
  gateBusy: boolean;
  gateError: string | null;
  /** POST /api/conditions/detect — 규칙으로 Critical Condition을 (다시) 탐지한다 */
  detectConditions: () => void;
  /** PUT /api/conditions/{id}/{cid} — 담당자가 조건 상태를 바꾼다 (CLEARED는 사람만) */
  updateCondition: (conditionId: string, body: ConditionUpdateRequest) => Promise<boolean>;
  /** PUT /api/actions/{id}/{aid} — 체크리스트 항목 완료/수정 */
  updateAction: (actionId: string, body: ActionUpdateRequest) => void;
  /** POST /api/actions/{id} — 담당자가 항목을 직접 추가 */
  createAction: (body: ActionCreateRequest) => void;
  /**
   * DELETE /api/actions/{id}/{aid} — 직접 추가한 항목을 지운다.
   *
   * 조건에서 «자동 생성»된 항목은 지우지 않는다 — 지워도 조건을 다시 찾으면
   * 되살아나므로 지운 사람이 「안 지워진다」고 읽는다. 그쪽은 「해당 없음」으로 둔다.
   */
  deleteAction: (actionId: string) => void;
  /** PUT /api/decision/{id} — GO/HOLD/NO_GO 저장 (미해결 BLOCKER면 GO는 422) */
  saveDecision: (body: DecisionRequest) => Promise<boolean>;
}

// ---------------------------------------------------------------------------
// 선택 상태 저장 (URL 우선, localStorage 보조)
// ---------------------------------------------------------------------------

/**
 * 지금 선택된 공고를 읽는다. **순수 읽기여야 한다.**
 *
 * 이 함수는 useSyncExternalStore 의 getSnapshot 으로 넘어가 렌더마다 불린다.
 * 예전에는 여기서 writeSelectedNotice() 를 불러 history.replaceState·localStorage.setItem·
 * dispatchEvent 를 실행했다 — 「렌더 중 부수효과」이자 다른 컴포넌트를 갱신하는 것이라
 * React 규칙 위반이고, 화면이 다시 그려질 때마다 replaceState 가 호출됐다.
 * Safari 는 30초에 100회를 넘기면 SecurityError 를 내는데 코드가 그것을 삼키므로,
 * 어느 순간부터 주소창이 조용히 선택과 어긋난다.
 *
 * 딥링크로 들어온 선택을 저장하는 일은 effect 로 옮겼다(persistDeepLinkedNotice).
 */
function readInitialNoticeId(): string | null {
  return readSelection();
}

// 저장된 선택은 useSyncExternalStore로 읽는다. useState 초기화에서 window를 읽으면
// 서버는 null, 클라이언트는 저장값으로 첫 화면을 그려 hydration 오류가 난다
// (새로고침이나 ?notice= 링크로 열 때 재현). 서버 스냅샷은 항상 null이고,
// hydration이 끝난 뒤 클라이언트 스냅샷으로 한 번 갈아탄다.
const subscribeNever = () => () => {};
const getHydrated = () => true;
const getHydratedServer = () => false;

/**
 * 목록에 없는 공고 id 를 지운다. 조회 창에서 빠진 공고 id가 계속 남아 화면을 막는 것을 막는다.
 *
 * **그 id 만** 지운다 — 링크(`/analysis?notice=`)로 들어온 id 가 목록에 없을 때 이전에 저장해 둔 선택까지 지우면
 * 「검토 중」에서 목록에 없는 공고를 누른 순간 보던 공고를 잃었다 (27차 LNK-04).
 * 돌려주는 값: 이전 선택이 남아 있는가(남았으면 대시보드는 그 공고로 돌아간다).
 */
function forgetNoticeId(id: string): boolean {
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.get(NOTICE_QUERY_KEY) === id) {
      url.searchParams.delete(NOTICE_QUERY_KEY);
      window.history.replaceState(window.history.state, "", url.toString());
    }
  } catch {
    // history 접근 실패는 무시한다.
  }
  try {
    if (window.localStorage.getItem(NOTICE_STORAGE_KEY) === id) window.localStorage.removeItem(NOTICE_STORAGE_KEY);
    return Boolean(window.localStorage.getItem(NOTICE_STORAGE_KEY));
  } catch {
    // 저장소 접근 실패는 무시한다.
    return false;
  }
}

/**
 * 고른 것을 주소와 저장소에 남긴다.
 *
 * 예전에는 지원사업이면 **아무 데도 남기지 않고 그냥 돌아왔다.** 입찰 저장값을 오염시키지 않으려는
 * 의도는 맞았지만, 그 바람에 주소가 `/analysis?notice=g2b-…` 로 남아 새로고침하면 이전 입찰이 열렸다.
 * 지금은 저장소를 둘로 나눠(`?notice=` / `?support=`) 둘 다 지킨다 —
 * 입찰 저장값은 그대로고, 지원사업도 주소에 남아 새로고침·링크 공유를 견딘다.
 */
function persistNoticeId(id: string): boolean {
  // 저장 규칙은 lib/selection 한 곳에만 둔다 — 화면마다 다르면 선택이 새어 나간다.
  // 지원사업은 `?support=`, 입찰은 `?notice=` 로 **각자의 자리**에 남는다.
  // 사람이 직접 고른 것이므로 히스토리에 쌓아 뒤로가기로 이전 선택으로 돌아갈 수 있게 한다.
  writeSelection(id, "push");
  // 주소·저장소가 모두 막힌 환경(시크릿 창 등)인지 바로 확인한다.
  // 남았다면 화면 안의 보조 기억은 필요 없다 — 주소 하나만 진실로 두는 편이 안전하다.
  const stored = readSelection();
  return stored === id || (isDemoProcurementId(id) && stored === null);
}

// ---------------------------------------------------------------------------
// 오류 문구
// ---------------------------------------------------------------------------

/**
 * 화면에 그대로 찍히는 문장. 사용자 문장에는 서버 주소·프레임워크·HTTP 코드를 쓰지 않는다.
 * 규칙은 lib/errors 한 곳에 있다 — 화면마다 다르게 쓰면 또 「FastAPI 를 확인하라」가 생긴다.
 */
function describeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "이 공고의 분석 결과가 아직 없습니다. 분석을 먼저 실행해 주세요.";
  }
  return describeFailure(error, "분석 데이터를 불러오지 못했습니다.");
}

function describeParseError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "이 공고의 제안요청서는 아직 파싱할 수 없습니다 (첨부 문서 미지원 또는 추출 실패).";
  }
  return describeError(error);
}

// ---------------------------------------------------------------------------
// 로딩
// ---------------------------------------------------------------------------

function loadRequirements(procurementId: string): Promise<RfpParseResult> {
  return getRfpRequirements(procurementId).catch((error: unknown) => {
    // 저절로 파싱하는 것은 합성 fixture 뿐이다 — 실공고는 첨부를 받아야 할 수 있어 사람이 확인해야 한다 (27차 §3-A-3).
    if (error instanceof ApiError && error.status === 404 && !procurementId.startsWith("g2b-")) {
      return parseRfp(procurementId);
    }
    throw error;
  });
}

/** 실제 공고는 아직 요구사항이 없을 수 있다 — 404는 오류가 아니라 "미추출"이다. */
function loadRequirementsOrNull(procurementId: string): Promise<RfpParseResult | null> {
  return getRfpRequirements(procurementId).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
}

interface LoadedDashboard {
  list: ProcurementListResponse | null;
  listMessage: string | null;
  selectedId: string;
  source: CosmosSource | null;
  sourceError: string | null;
  /** 요청한 공고가 목록에 없어 데모 공고로 되돌린 경우 그 id (사유를 화면에 남긴다) */
  droppedId?: string;
  /** 고른 공고가 없어(주소 · 저장소 모두 비어) 실제 1위 공고를 보여 주는 중 — 주소 · 저장소에 쓰지 않는다 */
  defaulted?: boolean;
}

/**
 * 고른 공고가 없을 때 처음 보여 줄 공고 — **회사 기준 검토 우선순위 나라장터 1위**(담당자 결정 10-13).
 *
 * 마감 전 · 불가 아님 · 가상 예시 아님 · 지금 목록에 있는 공고만. 없으면 `id: null`(가상 예시로 돌아간다).
 * **못 물어봤으면 `error`** — 실패를 「1위 없음」과 같은 null 로 삼키면 말없이 가상 예시가 열렸다(2.0.6).
 * 고르기만 한다 — 분석 · 첨부 내려받기 · 바깥 호출을 하지 않는다(그 공고를 목록에서 열 때와 같다).
 */
async function firstRealNoticeId(
  list: ProcurementListResponse,
  days: number,
  organizationId: string,
): Promise<{ id: string | null; error: string | null }> {
  try {
    const ranked = await getBusinessOpportunities({ organizationId, source: "g2b", limit: 30, days });
    // 나라장터 출처만 실패하면 서버는 200 + 빈 목록 + source_errors 다 — 이것도 「1위 없음」이 아니라 실패다(2.0.6).
    // 저장본으로 대신 준 날(항목이 옴)은 실패가 아니다 — 그 1위를 연다(sourceFailure).
    const sourceError = sourceFailure(ranked, "g2b");
    if (sourceError) return { id: null, error: sourceError };
    const now = Date.now();
    // 마감 전인지는 서버(`closed` · 실제 마감)가 정한다 — 입찰 마감 칸이 빈 「마감 미상」 공고를 여기서 빼면
    // 레이더 · 사업기회 1위와 다른 공고가 열렸다(2.0.5).
    const top = ranked.items.find(
      (item) =>
        !item.closed &&
        item.eligibility_gate !== "FAIL" &&
        !isDemoProcurementId(item.id) &&
        (item.deadline === null || Date.parse(item.deadline) > now) &&
        list.notices.some((notice) => notice.id === item.id),
    );
    return { id: top?.id ?? null, error: null };
  } catch (error: unknown) {
    return { id: null, error: describeFailure(error, "순위 목록을 받지 못했습니다.") };
  }
}

// 조회 기간은 바꿀 수 있다(usePeriodDays) — 숫자를 박지 않는다(27차 §3-E 검증).
// 「데모 공고」라 하지 않는다 — 고른 것이 없으면 실제 1위가 열린다(36차 · 2.0.5 · 1위가 없을 때만 가상 예시).
export const STALE_NOTICE_MESSAGE =
  "이전에 보던 공고가 나라장터 조회 기간에서 빠져 다른 공고를 엽니다. 위 목록에서 공고를 다시 선택해 주세요.";
/** 링크로 온 공고가 목록에 없고 그 전에 보던 공고도 없을 때 — 「이전에 보던」이 아니다(27차 §3-E 검증 G4-V2). */
export const STALE_NOTICE_LINK_MESSAGE =
  "링크로 연 공고가 지금 나라장터 조회 기간 목록에 없어 다른 공고를 엽니다. 조회 기간을 늘리거나 사업기회 「요구사항 정리표」 탭에서 여세요.";
/** 링크로 온 공고가 목록에 없고, 그 전에 보던 공고가 남아 있을 때 (27차 LNK-04). */
export const STALE_NOTICE_BACK_MESSAGE =
  "링크로 연 공고가 지금 나라장터 조회 기간 목록에 없어 이전에 보던 공고로 돌아왔습니다. 다른 공고는 위 목록에서 고르세요.";

/**
 * 실제 분석 API(자격판정 → 제안서 → Auditor)를 순서대로 실행/조회한다.
 *
 * 전부 best-effort다. 하나가 실패해도 null로 두고 나머지는 진행한다 —
 * 실패한 단계는 UI에서 "미실행"으로 정직하게 표시된다 (가짜 수치를 만들지 않는다).
 * LLM은 기본으로 끈다(use_llm=false): 키가 없어도 규칙 기반 결과는 항상 완전하다.
 */
type PhaseReporter = (key: RunPhaseKey, status: RunPhaseStatus, detail?: string | null) => void;

/** 실행 타임라인 한 줄. 여기도 코드 대신 사람의 말을 쓴다. */
function describePhaseError(error: unknown): string {
  return describeFailure(error, "요청을 처리하지 못했습니다.");
}

/**
 * 분석 결과를 단계마다 **즉시** 내보낸다.
 *
 * 예전에는 capability→eligibility→conditions→…→audit 를 전부 끝낸 뒤 한 번에 반영했다.
 * 그런데 실행 타임라인(runLog)은 단계마다 바로 갱신되므로,
 * 「타임라인에는 PASS/CHECK·BLOCKER 가 찍혔는데 카드는 미실행」이 구조적으로 발생했다.
 * 두 표시가 같은 순간에 같은 값을 말하도록 도착하는 대로 흘려보낸다.
 */
async function loadAnalysis(
  procurementId: string,
  hasRequirements: boolean,
  report: PhaseReporter,
  ctx: AnalysisContextParams,
  publish: (patch: Partial<CosmosAnalysis>) => void = () => {},
): Promise<CosmosAnalysis> {
  // 「이 일을 해낼 수 있는가」를 「참가할 수 있는가」보다 먼저 본다 — 읽는 순서가 판단 순서다.
  //
  // 데모(합성) 공고에는 아예 묻지 않는다. 이 판정은 «나라장터 후보 목록에 있는 공고»만
  // 대상이라 데모 공고에서는 반드시 404 가 나고, 화면을 열 때마다 콘솔에 빨간 줄이
  // 하나 남았다 (ISSUE-037). 없을 것을 알면서 묻지 않는다.
  let capability: CosmosAnalysis["capability"] = null;
  if (isDemoProcurementId(procurementId)) {
    report("capability", "skipped", "데모 공고에는 수행역량 판정을 실행하지 않습니다");
  } else {
    report("capability", "running");
    capability = await getCapability(procurementId, ctx).then(
      (value) => {
        const parts = [`${value.counts.supported ?? 0}건 확인`];
        if (value.counts.gap) parts.push(`${value.counts.gap}건 어긋남`);
        if (value.counts.unknown) parts.push(`${value.counts.unknown}건 확인 필요`);
        report("capability", "done", parts.join(" · "));
        return value;
      },
      (error: unknown) => {
        // 읽기 전용 스냅샷 배포본에는 이 응답이 저장돼 있지 않다(404). 그건 **실패가 아니라
        // 실행하지 않은 것**이라, 공고마다 빨간 「실패」를 띄우면 없는 고장을 있는 것처럼 보여 준다.
        if (error instanceof ApiError && error.status === 404) {
          report("capability", "skipped", "이 배포본에 저장되지 않은 공고입니다 — 판정을 실행하지 않았습니다");
        } else {
          report("capability", "failed", describePhaseError(error));
        }
        return null;
      },
    );
  }

  publish({ capability });

  report("eligibility", "running");
  // 43차 M26 — 열람자는 판정 요청(POST)이 서버에서 막힌다. 같은 판정을 읽기(GET)로 받는다.
  const viewer = readCurrentUser()?.role === "viewer";
  const eligibility = await (viewer ? getEligibilityReport(procurementId, ctx) : evaluateEligibility(procurementId, {}, ctx)).then(
    (value) => {
      report(
        "eligibility",
        "done",
        `${ELIGIBILITY_LABELS[value.verdict] ?? value.verdict} · ${eligibilityTallyText(value.counts.passed, value.counts.check, value.counts.failed)}`,
      );
      return value;
    },
    (error: unknown) => {
      report(
        "eligibility",
        "failed",
        viewer && error instanceof ApiError && error.status === 404 ? "편집자가 한 번 열어야 판정이 생깁니다" : describePhaseError(error),
      );
      return null;
    },
  );
  publish({ eligibility });

  const gate = await loadGate(procurementId, hasRequirements, report, ctx);
  publish(gate);

  if (!hasRequirements) {
    report("proposal", "skipped", "요구사항이 없어 생성할 수 없음");
    report("audit", "skipped", "초안 없음");
    return { ...EMPTY_ANALYSIS, capability, eligibility, ...gate };
  }

  // 이미 생성해 둔 섹션이 있으면 그대로 쓴다(없으면 404 → 미실행).
  report("proposal", "running");
  const proposal = await getProposal(procurementId, ctx).then(
    (value) => {
      report(
        "proposal",
        "done",
        `${value.sentences.length}문장 · 확인 필요 ${value.needs_review_count}${value.legacy_result ? " · 레거시 공개 결과" : ""}`,
      );
      return value;
    },
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 404) {
        report("proposal", "skipped", "생성된 초안 없음 — 상세 패널에서 생성");
      } else {
        report("proposal", "failed", describePhaseError(error));
      }
      return null;
    },
  );
  publish({ proposal });

  // 근거 연결 상태를 **여기서 다시** 보고한다.
  //
  // 실행 기록은 공고가 그려질 때 한 번 찍히는데, 그 시점에는 제안서가 아직 없어서
  // 「아직 실행하지 않았습니다」로 남았다. 그리고 다시 보고하는 곳이 없어서,
  // 같은 화면 안에서 단계 표시는 「연결됨」인데 실행 기록은 「미실행」이라고 말했다.
  if (proposal) {
    const grounded = proposal.evidence_grounded_count ?? 0;
    const documents = proposal.evidence_summary?.used_document_count ?? 0;
    if (grounded > 0) {
      report("evidence", "done", `회사자료 ${documents}종 · ${grounded}문장에 연결`);
    } else {
      report("evidence", "skipped", "검색은 했으나 채택된 회사 근거가 없습니다 — 회사자료 확인 필요");
    }
  }

  // 초안이 «어느 요구사항 집합 기준»인지 먼저 묻는다. 이것을 건너뛰면 32건 기준
  // 초안을 55건 집합과 견주고도 그 사실이 화면에 나타나지 않는다.
  const readiness = await getAuditReadiness(procurementId, ctx).catch(() => null);
  publish({ readiness });

  const draft = proposalDraftText(proposal);
  if (!draft) {
    // 2.1.6 — 6단계 초안 없이 워드 초안을 올려 점검했으면 그 저장 결과를 보인다. 다시 열면 「아직 안 함」이었는데
    // 「검토 중」 탭 · 머리 칩은 같은 결과를 세고 있었다(latest_stored_run).
    const stored = await getLatestAuditRun(procurementId, ctx).catch(() => null);
    report("audit", stored ? "done" : "skipped", stored ? `저장된 결과 · 발견 ${stored.findings.length}건` : "검사할 초안 없음");
    return { ...EMPTY_ANALYSIS, capability, eligibility, proposal, audit: stored, readiness, ...gate };
  }

  if (readiness && !readiness.ready && readiness.blockers.includes("stale_requirements")) {
    // 일반 검사를 돌리지 않는다. 돌리면 「늘어난 요구사항」이 「지금 초안의 결함」으로
    // 읽힌다. 담당자가 「기존 제안서와 비교」를 누르면 변경 영향 분석으로 실행된다.
    report("audit", "skipped", readiness.message);
    return { ...EMPTY_ANALYSIS, capability, eligibility, proposal, audit: null, readiness, ...gate };
  }

  report("audit", "running");
  /**
   * 쓰기가 막힌 회사에서는 **읽기만** 한다 (ISSUE-060).
   *
   * 공용 데모 공고의 검사 결과는 회사 구분 없이 한 파일이라, 기본 회사가 아니면 쓰기가 403 이다.
   * 그런데 화면은 열릴 때마다 자동으로 검사를 «실행»하려 했고, 403 을 받아 결과가 아예 없는 것처럼
   * 보였다 — 저장된 결과가 옆에 그대로 있는데도. 읽기는 모두에게 열려 있으므로 그것을 쓴다.
   *
   * 판정은 「이 회사가 이 결과를 쓸 수 있는가」다. 공용 데모 결과는 기본 회사만 쓸 수 있다.
   */
  // 45차 M5 — 열람자도 읽기만(저장된 점검 결과 GET). 열 때 점검을 «실행»(POST)해 403 을 받고 「아직 안 함」으로 보였다.
  const readOnlyAudit = viewer || (isDemoProcurementId(procurementId) && (ctx?.organization_id ?? null) !== DEFAULT_ORGANIZATION_ID);
  const audit = await (readOnlyAudit
    ? getLatestAuditRun(procurementId, ctx).then((value) => {
        if (value) {
          report("audit", "done", `저장된 결과 · 발견 ${value.findings.length}건`);
          return value;
        }
        report("audit", "skipped", viewer ? "저장된 점검 결과가 없습니다 — 편집자가 한 번 점검해야 생깁니다" : "이 회사는 공용 데모 결과를 다시 검사할 수 없습니다 — 저장된 결과도 없습니다");
        return null;
      }, (error: unknown) => {
        report("audit", "failed", describePhaseError(error));
        return null;
      })
    : dedupedAudit(procurementId, draft, ctx).then(
        (value) => {
          report("audit", "done", `발견 ${value.findings.length}건 · 점검 대상 요구사항 ${value.coverage.total}건 중 ${value.coverage.covered}건 반영`);
          return value;
        },
        (error: unknown) => {
          report("audit", "failed", describePhaseError(error));
          return null;
        },
      ));
  publish({ audit });
  return { ...EMPTY_ANALYSIS, capability, eligibility, proposal, audit, readiness, ...gate };
}

/**
 * 같은 검사를 **두 번 보내지 않는다.**
 *
 * 화면을 한 번 열면 `POST /api/auditor/run` 이 2회 나갔다. 로드 effect 가
 * hydration 직후 한 번, 저장된 선택이 들어와 `requestedId` 가 바뀌며 또 한 번 돌기 때문이다
 * (개발 모드의 effect 두 번 실행도 같은 결과를 만든다). 결과가 같은 검사를 두 번 계산하고
 * 파일을 두 개 만들었다.
 *
 * 여기서는 «같은 공고·같은 초안·같은 회사»의 진행 중 요청을 하나로 합친다. backend 도
 * 같은 입력이면 이전 결과를 그대로 돌려주므로(auditor_service.run_key) 파일은 늘지 않는다.
 * 끝난 뒤에도 잠깐(AUDIT_REUSE_MS) 들고 있는다. 두 번의 effect 실행이 «겹치지 않고 이어질» 때도
 * 있어서, 진행 중인 것만 합치면 요청이 2회로 남는다. 담당자가 누르는 「제출 전 다시 점검」은
 * 이 경로를 쓰지 않으므로(runAuditor 직접 호출) 항상 실제로 돈다.
 */
const AUDIT_REUSE_MS = 30_000;
const auditInFlight = new Map<string, Promise<AuditRunResult>>();

function dedupedAudit(
  procurementId: string,
  draft: string,
  ctx: AnalysisContextParams | null,
): Promise<AuditRunResult> {
  // 초안 전체를 키로 쓰면 메모리를 많이 잡는다. 길이+앞뒤 조각이면 같은 초안인지 가리기에 충분하다.
  const draftKey = `${draft.length}:${draft.slice(0, 64)}:${draft.slice(-64)}`;
  const key = [procurementId, ctx?.organization_id ?? "", ctx?.evidence_scope ?? "", draftKey].join("|");
  const running = auditInFlight.get(key);
  if (running) return running;
  const started = runAuditor(procurementId, draft, {}, ctx);
  auditInFlight.set(key, started);
  started.then(
    () => window.setTimeout(() => auditInFlight.delete(key), AUDIT_REUSE_MS),
    // 실패는 곧바로 버린다 — 다시 시도할 수 있어야 한다.
    () => auditInFlight.delete(key),
  );
  return started;
}

/** Critical Condition · 체크리스트 · 결정. 전부 best-effort — 실패하면 null(미실행)로 둔다. */
async function loadGate(
  procurementId: string,
  hasRequirements: boolean,
  report: PhaseReporter,
  ctx: AnalysisContextParams,
): Promise<Pick<CosmosAnalysis, "conditions" | "decision" | "decisionError" | "checklist">> {
  report("conditions", "running");
  const conditions = await getConditions(procurementId, ctx).then(
    (value) => {
      report(
        "conditions",
        "done",
        conditionCountsText(value.counts),
      );
      return value;
    },
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 404) {
        report("conditions", "skipped", hasRequirements ? "탐지 결과 없음" : "요구사항 파싱 후 탐지");
      } else {
        report("conditions", "failed", describePhaseError(error));
      }
      return null;
    },
  );
  const [decisionRead, checklist] = await Promise.all([
    // 못 읽은 것과 「검토 전」은 다르다 — 서버는 결정이 없어도 UNREVIEWED 를 200 으로 준다(2.0.6).
    getDecision(procurementId, ctx).then(
      (value) => ({ decision: value, decisionError: null }),
      (error: unknown) => ({ decision: null, decisionError: describePhaseError(error) }),
    ),
    getActions(procurementId, ctx).catch(() => null),
  ]);
  return { conditions, ...decisionRead, checklist };
}

/** 공고·요구사항이 확정된 뒤 앞 단계(공고·후보·적합도·파싱·증빙) 기록을 source에서 채운다. */
function logLoadedSource(report: PhaseReporter, source: CosmosSource): void {
  const { notice, origin, parse, scenario } = source;
  report(
    "notice",
    "done",
    origin.kind === "demo"
      ? SYNTHETIC_NOTICE
      : // 되살려 붙인 고정 공고는 목록이 실시간이어도 방금 받아온 것이 아니다.
        notice.pinned
        ? `고정 공고(저장본) · ${notice.notice_no}`
        : origin.source === "g2b"
          ? `나라장터 실시간 · ${notice.notice_no}`
          : `나라장터 저장본 · ${notice.notice_no}`,
  );
  if (notice.candidate) {
    const keywords = [...notice.candidate.matched_ai_keywords, ...notice.candidate.matched_work_keywords];
    report("candidate", "done", `낱말 관련도 ${CANDIDATE_TIER_LABELS[notice.candidate.tier] ?? notice.candidate.tier} · ${keywords.slice(0, 3).join(", ")}`);
  } else if (origin.kind === "demo") {
    report("candidate", "demo", `${DEMO_NOTICE_LABEL} — 목록 필터 대상 아님`);
  } else {
    report("candidate", "skipped", "목록 필터 정보 없음");
  }
  if (scenario) {
    report("fit", "demo", `적합도 ${scenario.semantic_match.label} (${DEMO_NOTICE_LABEL} 고정값)`);
  } else {
    // 엔진은 있다 — 고정 모드에서 꺼 둔 것이다. 점수가 나왔으면 그 점수, 아니면 백엔드 사유를 그대로 (DSH-16).
    const semantic = semanticFitOf(notice, notice.recommendation);
    if (semantic?.measured && semantic.score !== null) {
      report("fit", "done", `${semantic.methodLabel} ${Math.round(semantic.score * 100)} · ${semantic.label ?? ""}`);
    } else {
      report("fit", "skipped", `낱말 관련도만 사용 — ${semantic?.reason ?? "AI 의미 매칭은 쓰지 않았습니다"}`);
    }
  }
  if (parse) {
    report(
      "parse",
      "done",
      `${parse.count}건 · ${parse.page_count}p${parse.page_is_approximate ? " (근사)" : ""}${parse.truncated ? " · 상한 잘림" : ""}`,
    );
  } else {
    report("parse", "skipped", "제안요청서 아직 안 읽음");
  }
  if (scenario) {
    const selected = scenario.evidence_links.filter((l) => l.selected).length;
    report("evidence", "demo", `${scenario.evidence_documents.length}종 · 채택 ${selected}건 (가상 예시 자료)`);
  } else {
    // 여기서 무조건 「미실행」이라고 적으면 안 된다.
    // 제안서를 만들 때 근거 검색이 이미 돌았고, 그 결과가 proposal.evidence_summary 에 있다.
    // 실제로 회사자료 42문단을 검색해 3종·4문단을 연결해 놓고도 화면은 미실행이라고 말했다.
    report("evidence", "skipped", "제안서 생성 시 함께 실행됩니다 — 아직 실행하지 않았습니다");
  }
}

async function loadDashboard(requestedId: string | null, days: number, organizationId: string): Promise<LoadedDashboard> {
  let list: ProcurementListResponse | null = null;
  let listMessage: string | null = null;
  try {
    // 조회 기간은 네 화면이 함께 쓰는 값이다 (0920 §4-B-2-e). 예전에는 백엔드 기본(14일)에
    // 맡겨 두어, 목록에서 60일로 찾은 공고가 이 선택창에 없었다.
    list = await getProcurements({ days });
  } catch (error: unknown) {
    listMessage = describeError(error);
  }

  // 고른 것이 없는데 목록을 못 받았으면 말없이 가상 예시로 가지 않는다 — 사유와 「다시 시도」를 보인다(2.0.5).
  if (!list && requestedId === null) {
    return { list, listMessage, selectedId: DEMO_PROCUREMENT_ID, source: null, sourceError: listMessage };
  }

  // 고른 것이 없으면 실제 1위 공고(없으면 가상 예시) — 가상 예시는 고르기 목록에 그대로 남는다
  const first = requestedId === null && list ? await firstRealNoticeId(list, days, organizationId) : null;
  // 순위를 못 받았으면 「1위 없음」과 다르다 — 말없이 가상 예시를 열지 않고 목록 실패와 같은 길(사유 + 「다시 시도」)로 간다(2.0.6).
  if (first?.error) {
    const message = `처음 열 공고(회사 기준 1위)를 정하지 못했습니다 — ${first.error.replace(/[.\s]+$/, "")} · 고르기 칸에서 공고를 직접 고르거나 「다시 시도」를 누르세요.`;
    return { list, listMessage: message, selectedId: DEMO_PROCUREMENT_ID, source: null, sourceError: message };
  }
  const fallbackId = first?.id ?? null;
  const selectedId = requestedId ?? fallbackId ?? DEMO_PROCUREMENT_ID;
  const defaulted = fallbackId !== null && selectedId === fallbackId;

  if (isDemoProcurementId(selectedId)) {
    const [parse, scenario] = await Promise.all([
      loadRequirements(DEMO_PROCUREMENT_ID),
      getDemoCosmosScenario(DEMO_PROCUREMENT_ID),
    ]);
    // 분석 단계(자격판정·제안서·Auditor)는 화면을 먼저 그린 뒤 채운다 (첫 화면 지연 방지).
    return {
      list,
      listMessage,
      selectedId,
      source: {
        notice: DEMO_NOTICE,
        origin: { kind: "demo" },
        parse,
        scenario,
        analysis: EMPTY_ANALYSIS,
      },
      sourceError: null,
    };
  }

  // 목록 자체를 못 불러온 경우 — 공고를 바꿔도 소용없다. 사유를 그대로 보여준다.
  if (!list) {
    return { list, listMessage, selectedId, source: null, sourceError: listMessage };
  }

  let notice = list.notices.find((n) => n.id === selectedId);
  if (!notice) {
    // 사업기회는 비추천(관련 낮음) 공고에도 「입찰 분석 열기」를 단다 — 후보 목록에 없으면 같은 기간의 전체 목록에서 한 번 더 찾는다.
    // 예전엔 바로 「조회 기간 목록에 없어」로 돌아가 사업기회가 연 링크를 대시보드가 받지 않았다(2.0.5).
    const wide = await getProcurements({ days, includeLow: true }).then(
      (value) => ({ value, error: null as string | null }),
      (error: unknown) => ({ value: null, error: describeError(error) }),
    );
    const found = wide.value?.notices.find((n) => n.id === selectedId);
    if (found) {
      list = { ...list, notices: [...list.notices, found] };
      notice = found;
    }
    // 다시 찾기를 못 했으면 「목록에 없다」가 아니다 — 그렇게 말하고 기억한 선택까지 지우지 않는다(droppedId 없음 · 2.0.6).
    if (!notice && wide.error) {
      const message = `고른 공고를 목록에서 다시 확인하지 못했습니다 — ${wide.error.replace(/[.\s]+$/, "")} · 「다시 시도」를 누르세요.`;
      return { list, listMessage: message, selectedId, source: null, sourceError: message };
    }
  }
  if (!notice) {
    // 목록은 정상인데 그 공고만 없다. 나라장터 조회 창(14일)에서 빠진 경우가 대부분이며,
    // 브라우저에 저장된 옛 선택이 화면을 막는다. 막다른 오류로 두지 않고 데모 공고로 돌아간다.
    // 저장된 id를 지우는 것은 훅(applyLoaded)이 한다 — 사유 문구를 유지해야 하기 때문이다.
    const [parse, scenario] = await Promise.all([
      loadRequirements(DEMO_PROCUREMENT_ID),
      getDemoCosmosScenario(DEMO_PROCUREMENT_ID),
    ]);
    return {
      list,
      listMessage: STALE_NOTICE_MESSAGE,
      droppedId: selectedId,
      selectedId: DEMO_PROCUREMENT_ID,
      source: {
        notice: DEMO_NOTICE,
        origin: { kind: "demo" },
        parse,
        scenario,
        analysis: EMPTY_ANALYSIS,
      },
      sourceError: null,
    };
  }

  const parse = await loadRequirementsOrNull(selectedId);
  return {
    list,
    listMessage,
    selectedId,
    defaulted,
    source: {
      notice,
      origin: { kind: "real", source: list.source, fetchedAt: list.fetched_at },
      parse,
      scenario: null,
      analysis: EMPTY_ANALYSIS,
    },
    sourceError: null,
  };
}

/** 기업마당 지원사업을 선택기 항목으로. 8단계로 끌고 오지 않고 «갈 곳»만 들려 보낸다. */
function supportOption(item: UnifiedOpportunity): NoticeOption {
  return {
    id: item.id,
    title: item.title,
    agency: item.agency,
    deadline_at: item.deadline,
    tier: null,
    rank: item.priority_rank ?? null,
    grade: null,
    demo: false,
    noticeNo: null,
    revisionCount: 1,
    pinned: false,
    support: true,
    // 백엔드가 이미 갈 곳을 정해 보낸다 — 화면이 경로를 다시 만들지 않는다.
    route: item.next_route?.path ?? `/support/${item.id}`,
    score: item.company_priority_score ?? null,
    gate: item.eligibility_gate ?? null,
    gateReason: item.gate_reason ?? null,
    order: item.source_rank || null,
  };
}

/**
 * 선택창 항목 만들기. **내보낸다** — RFP 분석 화면이 같은 선택창을 쓴다 (0920 §4-B-4).
 */
export function buildNoticeOptions(
  list: ProcurementListResponse | null,
  selectedId: string,
  supportPrograms: UnifiedOpportunity[] = [],
  /**
   * 나라장터 공고의 검토 우선순위 (0920 §4-B-1).
   *
   * 여기가 비어 있던 것이 「선택창은 추천 점수 순, 목록은 우선순위 순」이라는 **순서 역전**의
   * 원인이었다. 선택창은 `/api/procurements` 응답 순서(= 추천 점수 순)를 그대로 썼고,
   * 목록·레이더는 통합 목록의 `company_priority_score`(선택 회사 기준) 순이었다.
   * 같은 값을 여기에도 넣어 두 화면이 같은 순서가 되게 한다.
   */
  priorityById: Map<string, UnifiedOpportunity> = new Map(),
  /**
   * 지금 연 것의 머리 — 지원사업은 신청 분석 결과, 입찰은 열린 공고. 목록에 없을 때 제목 · 기관을 여기서 쓴다
   * (입찰도 — 관련 낮음 공고가 목록을 다시 받은 뒤 id 글자로 섰다 · 2.0.6).
   */
  selectedSupport: { title: string; agency: string | null } | null = null,
  /** 통합 목록을 받았나 — 받았을 때만 거기 없는 공고를 「목록 밖」으로 본다(못 받았으면 모른다). */
  priorityLoaded = false,
  /** 고른 것의 목록 · 상세를 아직 받는 중인가 — 그동안은 목록에 없어도 id 글자 · 「목록에서 확인되지 않음」을 쓰지 않는다. */
  selectedPending = false,
): NoticeOption[] {
  const demo: NoticeOption = {
    id: DEMO_PROCUREMENT_ID,
    title: DEMO_NOTICE.title,
    agency: DEMO_NOTICE.agency,
    deadline_at: DEMO_NOTICE.deadline_at,
    tier: null,
    rank: null,
    grade: null,
    demo: true,
    noticeNo: null,
    revisionCount: 1,
    pinned: false,
    support: false,
    route: null,
    score: null,
    gate: null,
    gateReason: null,
  };
  const real: NoticeOption[] = (list?.notices ?? []).map((n) => {
    const unified = priorityById.get(n.id);
    return {
      id: n.id,
      title: n.title,
      agency: n.agency,
      deadline_at: n.deadline_at,
      tier: n.candidate?.tier ?? null,
      rank: n.rank ?? null,
      grade: n.recommendation?.grade ?? null,
      demo: false,
      noticeNo: n.notice_no,
      revisionCount: n.revision_count ?? 1,
      // 옛 배포 스냅샷에는 이 필드가 없다 — 없으면 고정이 아닌 것으로 본다.
      pinned: Boolean(n.pinned),
      support: false,
      route: null,
      // 통합 목록에 없으면 null 이다 — 0 으로 채우지 않는다 (CLAUDE.md §12).
      score: unified?.company_priority_score ?? null,
      gate: unified?.eligibility_gate ?? null,
      gateReason: unified?.gate_reason ?? null,
      outside: priorityLoaded && !unified,
      // 통합 목록(회사 기본 정렬)의 같은 출처 순번 — 선택창이 목록 · 레이더와 같은 순서로 선다(37차 §3-C-4).
      order: unified?.source_rank || null,
    };
  });
  const support: NoticeOption[] = supportPrograms.map(supportOption);
  const options = [demo, ...real, ...support];
  if (!options.some((o) => o.id === selectedId)) {
    // URL로 들어온 공고가 아직 목록에 없을 때(로딩 중·조회 기간 밖) 선택 상태를 잃지 않게 한다.
    // 지원사업이면 기업마당 묶음에 선다 — 예전엔 나라장터 묶음에 `bizinfo-PBLN_…` 글자로 섰다(2.0.5 · 대표 10-27).
    const support = isSupportProgramId(selectedId);
    // 10-31 최종 점검 A3 — 읽는 중에도 「bizinfo-PBLN_… · 목록에서 확인되지 않음」(id 글자 + 단정)이 잠깐 섰다. 다 받은 뒤에만 그렇게 적는다.
    const waiting = !selectedSupport && selectedPending;
    options.push({
      id: selectedId,
      title: selectedSupport?.title || (waiting ? (support ? "지원사업 불러오는 중…" : "공고 불러오는 중…") : selectedId),
      agency: selectedSupport?.agency || (waiting ? "" : "목록에서 확인되지 않음"),
      deadline_at: null,
      noticeNo: null,
      revisionCount: 1,
      pinned: false,
      tier: null,
      rank: null,
      grade: null,
      demo: false,
      support,
      route: support ? `/support/${selectedId}` : null,
      score: null,
      gate: null,
      gateReason: null,
    });
  }
  return options;
}

// ---------------------------------------------------------------------------
// 훅
// ---------------------------------------------------------------------------

export function useCosmosDashboard(options: { reducedMotion: boolean; organizationId: string }): CosmosDashboard {
  const { reducedMotion, organizationId } = options;

  // 서버 첫 화면과 클라이언트 첫 화면을 같게 유지한다 (위 subscribeNever 주석 참고).
  const hydrated = useSyncExternalStore(subscribeNever, getHydrated, getHydratedServer);
  /**
   * 주소·저장소의 선택을 **구독해서** 읽는다.
   *
   * 예전에는 구독하지 않아(subscribeNever) 뒤로가기·앞으로가기로 주소가 바뀌어도 화면이 그대로였다.
   * subscribeSelection 이 popstate 와 다른 탭의 storage 까지 듣는다.
   */
  const persistedId = useSyncExternalStore(
    subscribeSelection,
    readInitialNoticeId,
    readSelectionServer,
  );
  /**
   * 화면 안에서 고른 것. **주소·저장소가 모두 막힌 환경(시크릿 창 등)을 위한 보조 기억**이다.
   *
   * 고를 당시의 `persistedId` 를 함께 들고 있다가, 그 값이 달라지면(= 주소가 바뀌었다)
   * 기억을 버리고 주소를 따른다. 뒤로가기가 이 경로로 동작한다.
   * effect 로 지우지 않는 이유: 렌더 중에 판단할 수 있는 것을 effect 로 미루면
   * 한 박자 늦게 반영되고, setState-in-effect 는 불필요한 연쇄 렌더를 만든다.
   */
  const [chosen, setChosen] = useState<{ id: string; base: string | null } | null>(null);

  /**
   * AI 초안이 붙는지 **먼저** 물어 둔다 (ISSUE-130 · prompt_06 §4-A-4).
   *
   * 단추 문구가 누르기 **전에** 맞아야 한다 — 눌렀다가 「크레딧 소진」을 만나는 것보다
   * 「AI 없이 규칙으로」라고 미리 적어 두는 쪽이 낫다(지원사업 화면이 이미 그렇게 한다).
   * 한 번만 묻는다. 시연 중에 스위치가 바뀌는 일은 없고, 바뀌면 새로고침이 답이다.
   */
  const [aiDraft, setAiDraft] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    getHealth()
      .then((health) => {
        if (!alive) return;
        setAiDraft(
          health.llm_live === undefined ? null : Boolean(health.llm_live && health.llm_credit_ok),
        );
      })
      .catch(() => {
        // 못 물어봤으면 «모른다»로 둔다. 화면은 그때 아무 말도 하지 않는다.
        if (alive) setAiDraft(null);
      });
    return () => {
      alive = false;
    };
  }, []);

  /**
   * 딥링크(`/analysis?support=<id>`)로 들어온 선택을 저장소에도 남긴다. 입찰(`/analysis?notice=`)은 목록에서 찾은 뒤 applyLoaded 가 남긴다.
   *
   * URL 에만 있으면 쿼리 없는 `/` 로 돌아왔을 때 저장값이 없어 데모로 떨어진다.
   * 이 저장은 **부수효과**이므로 렌더가 아니라 effect 에서 한다 —
   * 예전에는 getSnapshot 안에서 해서 렌더마다 replaceState 가 돌았다.
   *
   * 종류에 맞는 저장소에 넣는다 — 지원사업 id 가 입찰 저장값(`bidpilot.notice.v1`)에
   * 들어가면 상단 네비게이션의 `/rfp` 가 있지도 않은 공고를 찾는다.
   * 링크로 들어온 것을 저장소에 맞추는 것뿐이므로 히스토리는 **늘리지 않는다**(replace).
   */
  // 입찰 공고는 **목록에서 찾은 뒤에** 남긴다(applyLoaded) — 찾기 전에 쓰면 목록에 없는 공고가 이전 선택을 덮고,
  // 데모로 돌아가며 둘 다 잃는다 (27차 LNK-04). 지원사업도 **조회에 성공한 뒤에** 남긴다(아래 getSupportProgram) — 없는
  // 지원사업 id 를 먼저 쓰면 요구사항 정리표가 잠기고 회사자료 돌아가기가 「없는 지원사업」으로 갔다(검수 LNK-R5).

  /** 저장된 선택이 조회 창에서 빠져 데모로 되돌린 사유. 사용자가 공고를 다시 고를 때까지 남긴다. */
  const [staleNotice, setStaleNotice] = useState<string | null>(null);
  const requestedId = chosen !== null && chosen.base === persistedId ? chosen.id : persistedId;
  /** 고른 것이 없을 때 보여 주는 공고 — 실제 1위 또는 가상 예시(loadDashboard 가 정한다 · 주소에 남기지 않는다). */
  const [fallbackId, setFallbackId] = useState<string>(DEMO_PROCUREMENT_ID);
  const [list, setList] = useState<ProcurementListResponse | null>(null);
  const [listState, setListState] = useState<{
    status: NoticeListInfo["status"];
    message: string | null;
  }>({ status: "loading", message: null });
  /**
   * 선택기에 함께 보여줄 기업마당 지원사업.
   *
   * 대시보드 첫 화면을 붙잡지 않도록 **따로** 불러온다 — 기업마당은 외부 API 라 느릴 때가 있고,
   * 이 목록이 없다고 입찰 분석이 막힐 이유가 없다. 실패하면 그 사실만 적고 묶음을 그리지 않는다
   * (빈 목록을 「지원사업 없음」으로 단정하지 않는다).
   */
  // 조회 기간은 네 화면이 함께 쓰는 값이다 (0920 §4-B-2-e).
  const days = usePeriodDays();
  const [supportPrograms, setSupportPrograms] = useState<UnifiedOpportunity[] | null>(null);
  /** 나라장터 공고 id → 통합 목록 항목. 선택창의 검토 우선순위·자격이 여기서 온다. */
  const [noticePriority, setNoticePriority] = useState<Map<string, UnifiedOpportunity>>(() => new Map());
  /** 나라장터 순위(통합 목록)를 받았나 · 못 받은 사유 — 받았을 때만 「목록 밖」을 가리고, 못 받으면 고르기 칸이 사유를 적는다(2.0.6). */
  // key 는 받은 회사 · 기간 — 회사를 바꾸고 새 순위가 오기까지 앞 회사 기준으로 「[불가·마감]」을 접지 않게 지금 열쇠와 같을 때만 쓴다(2.0.6 통합 검토).
  const [priorityState, setPriorityState] = useState<{ key: string; loaded: boolean; error: string | null }>({ key: "", loaded: false, error: null });
  const [supportError, setSupportError] = useState<string | null>(null);
  /** 지금 고른 것이 지원사업일 때의 신청 분석 결과. 입찰이면 언제나 null. */
  const [supportResult, setSupportResult] = useState<SupportApplicationResult | null>(null);
  const [supportLoad, setSupportLoad] = useState<{ status: "idle" | "loading" | "ready" | "error"; message: string | null }>({
    status: "idle",
    message: null,
  });
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  // 분석 결과는 source와 분리해 보관한다 — 화면에서 재실행하면 이 값만 갈아끼운다.
  const [analysis, setAnalysis] = useState<CosmosAnalysis>(EMPTY_ANALYSIS);
  /** 자격판정·제안서·Auditor를 뒤이어 불러오는 중 (첫 화면은 이미 그려져 있다) */
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [busy, setBusy] = useState({ proposal: false, audit: false, eligibility: false });
  const [actionError, setActionError] = useState<{
    proposal: string | null;
    audit: string | null;
    eligibility: string | null;
  }>({ proposal: null, audit: null, eligibility: null });
  const [stage, setStageRaw] = useState<WorkflowStage>(1);
  /**
   * 등장 애니메이션이 끝났는가.
   *
   * 끝난 뒤에야 화면이 «가장 먼저 처리할 단계»로 내려앉는다. 애니메이션 도중에 옮기면
   * 타이머가 그 위를 덮어써서 결국 8단계로 되돌아간다.
   */
  const [revealDone, setRevealDone] = useState(false);
  const [revealRun, setRevealRun] = useState(0);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [reviewDecision, setReviewDecision] = useState<ReviewDecision>(null);
  /** 서버에 저장된 최종 검토 결과. 공고를 열 때 복원한다. */
  const [savedReview, setSavedReview] = useState<SavedReview | null>(null);
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [runLog, setRunLog] = useState<RunLog>(() => emptyRunLog());
  /** 담당자 해결 처리 기록 (공고별). 서버에서 읽고, 저장하면 갱신한다. */
  const [resolutions, setResolutions] = useState<FindingResolution[]>([]);
  const [resolutionBusy, setResolutionBusy] = useState(false);
  const [resolutionError, setResolutionError] = useState<string | null>(null);
  const [clauseReviewBusy, setClauseReviewBusy] = useState<string | null>(null);
  const [clauseReviewError, setClauseReviewError] = useState<string | null>(null);

  // 진행 중 요청 토큰: 언마운트·재요청 시 증가시켜 늦게 도착한 응답을 무시한다.
  const requestRef = useRef(0);

  /** 토큰이 맞는 요청만 타임라인에 기록한다 (늦게 온 응답이 새 공고의 기록을 덮지 않게). */
  const makeReporter = useCallback(
    (token: number): PhaseReporter =>
      (key, status, detail = null) => {
        if (token !== requestRef.current) return;
        setRunLog((prev) => ({ ...prev, [key]: { key, status, detail } }));
      },
    [],
  );
  const timersRef = useRef<number[]>([]);
  const reducedMotionRef = useRef(reducedMotion);

  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
  }, [reducedMotion]);

  const clearTimers = useCallback(() => {
    for (const id of timersRef.current) window.clearTimeout(id);
    timersRef.current = [];
  }, []);

  const startReveal = useCallback(
    (intervalMs: number) => {
      clearTimers();
      setRevealDone(false);
      setRevealRun((n) => n + 1);
      if (reducedMotionRef.current) {
        // 움직임을 줄이는 환경에서는 애니메이션이 없다 — 바로 «내려앉을 단계»를 정하게 둔다.
        setStageRaw(FINAL_STAGE);
        setRevealDone(true);
        return;
      }
      setStageRaw(1);
      for (const step of WORKFLOW_STEPS) {
        if (step.id === 1) continue;
        const id = window.setTimeout(() => {
          setStageRaw(step.id);
          if (step.id === FINAL_STAGE) setRevealDone(true);
        }, intervalMs * (step.id - 1));
        timersRef.current.push(id);
      }
    },
    [clearTimers],
  );

  const setStage = useCallback(
    (next: WorkflowStage) => {
      clearTimers();
      // 사람이 직접 단계를 옮기면 등장 애니메이션은 끝난 것으로 본다 —
      // 남은 타이머가 뒤늦게 그 선택을 덮지 않게 한다.
      setRevealDone(true);
      setStageRaw(next);
    },
    [clearTimers],
  );

  const applyLoaded = useCallback(
    (loaded: LoadedDashboard, revealIntervalMs: number) => {
      setList(loaded.list);
      setListState({
        status: loaded.list ? "ready" : "error",
        message: loaded.listMessage,
      });
      if (loaded.droppedId) {
        // 목록에 없는 id를 지운다. 지우면 다시 불러오게 되므로 사유는 별도 state에 남긴다.
        // 이전 선택이 남아 있으면 대시보드는 그 공고로 돌아간다 — 사유 문장도 그 사실을 말한다.
        let fromLink = false;
        try {
          fromLink = new URLSearchParams(window.location.search).get("notice") === loaded.droppedId;
        } catch {
          fromLink = false;
        }
        const back = forgetNoticeId(loaded.droppedId);
        setStaleNotice(back ? STALE_NOTICE_BACK_MESSAGE : fromLink ? STALE_NOTICE_LINK_MESSAGE : STALE_NOTICE_MESSAGE);
      } else if (loaded.source?.origin.kind === "real" && !loaded.defaulted) {
        // 목록에서 찾은 공고만 저장소에 남긴다 — 링크로 온 공고도 여기서 남는다 (27차 LNK-04).
        // 처음 보여 주는 실제 1위(defaulted)는 남기지 않는다 — 고르지 않았으면 주소가 깨끗해야 한다.
        writeSelection(loaded.selectedId, "replace");
      }
      setFallbackId(loaded.defaulted ? loaded.selectedId : DEMO_PROCUREMENT_ID);
      if (loaded.source) {
        setAnalysis(loaded.source.analysis);
        setActionError({ proposal: null, audit: null, eligibility: null });
        setLoad({ kind: "ready", source: loaded.source });
        startReveal(revealIntervalMs);
      } else {
        setLoad({ kind: "error", message: loaded.sourceError ?? "공고를 불러오지 못했습니다." });
      }
    },
    [startReveal],
  );

  /** 해결 처리 기록은 best-effort로 읽는다 — 실패해도 발견 자체는 그대로 보인다. */
  const loadResolutions = useCallback((token: number, procurementId: string) => {
    getFindingResolutions(procurementId, analysisContext(procurementId, organizationId)).then(
      (list) => {
        if (token !== requestRef.current) return;
        setResolutions(list.resolutions);
      },
      () => {
        if (token !== requestRef.current) return;
        setResolutions([]);
      },
    );
  }, [organizationId]);

  /**
   * 저장된 최종 검토를 복원한다. 없으면(404 → null) 「저장된 적 없음」이다.
   *
   * 늦게 온 응답이 새 공고의 화면을 덮지 않도록 다른 조회와 같은 토큰 규칙을 쓴다.
   */
  const loadReview = useCallback(
    (token: number, procurementId: string) => {
      getReview(procurementId, analysisContext(procurementId, organizationId)).then(
        (saved) => {
          if (token !== requestRef.current) return;
          setSavedReview(saved);
          setReviewDecision(reviewToggle(saved?.status));
        },
        () => {
          if (token !== requestRef.current) return;
          // 조회 실패는 「저장된 적 없음」과 구분되지 않으므로 화면 판단을 만들지 않는다.
          setSavedReview(null);
        },
      );
    },
    [organizationId],
  );

  const fetchAll = useCallback(
    (revealIntervalMs: number) => {
      const token = ++requestRef.current;
      const report = makeReporter(token);

      /**
       * 지원사업이면 **입찰 체인을 아예 타지 않는다.**
       *
       * loadDashboard 는 나라장터 목록에서 공고를 찾고, 그 뒤로 요구사항·자격판정·제안서·
       * 제출 전 점검·해결기록·검토를 공고 id 로 부른다. 지원사업 id 로는 전부 404 가 나고
       * 실행 타임라인에 없는 고장이 찍힌다. 필요한 것은 신청 분석 한 번뿐이다.
       */
      if (isSupportProgramId(requestedId)) {
        const programId = requestedId as string;
        queueMicrotask(() => {
          if (token !== requestRef.current) return;
          /**
           * **이전 결과를 먼저 지운다.**
           *
           * 예전에는 지우지 않아서, 다른 지원사업을 고르면 새 응답이 도착할 때까지
           * 이전 사업의 신청조건·근거가 새 제목 아래 그대로 떠 있었다. 입찰에서 지원사업으로
           * 넘어올 때도 같은 이유로 입찰 분석이 잠깐 섞여 보였다.
           */
          setSupportResult(null);
          setSupportLoad({ status: "loading", message: null });
          setLoad({ kind: "loading" });
          setAnalysis(EMPTY_ANALYSIS);
        });
        // 나라장터 목록도 받는다 — 안 받으면 고르기 칸이 「불러오는 중」에 멈춰 나라장터로 돌아갈 길이 없었다
        // (2.0.5 · 마지막에 본 것이 지원사업이면 대시보드엔 기업마당만, 레이더엔 나라장터).
        getProcurements({ days }).then(
          (procurements) => {
            if (token !== requestRef.current) return;
            setList(procurements);
            setListState({ status: "ready", message: null });
          },
          (error: unknown) => {
            if (token !== requestRef.current) return;
            setListState({ status: "error", message: describeError(error) });
          },
        );
        return getSupportProgram(programId, organizationId).then(
          (result) => {
            if (token !== requestRef.current) return;
            setSupportResult(result);
            setSupportLoad({ status: "ready", message: null });
            writeSelection(programId, "replace");
          },
          (error: unknown) => {
            if (token !== requestRef.current) return;
            setSupportResult(null);
            // 없는 지원사업에 입찰 문장(「분석을 먼저 실행」)을 쓰지 않는다 — 지원사업 화면과 같은 말(2.0.5).
            const missing = error instanceof ApiError && error.status === 404;
            setSupportLoad({
              status: "error",
              message: missing ? "현재 목록에 없는 지원사업입니다 — 위 고르기 칸에서 다른 공고를 고르세요." : describeError(error),
            });
            // 없는 지원사업이면 저장값을 비운다(이전 입찰 선택은 그대로)
            if (error instanceof ApiError && error.status === 404) clearSelectedSupport();
          },
        );
      }
      // 타임라인 초기화는 effect 본문에서 동기 setState가 되지 않도록 마이크로태스크로 미룬다.
      queueMicrotask(() => {
        if (token !== requestRef.current) return;
        setRunLog(emptyRunLog());
        report("notice", "running");
      });
      return loadDashboard(requestedId, days, organizationId).then(
        (loaded) => {
          if (token !== requestRef.current) return;
          // 입찰 공고로 돌아왔다 — 이전 지원사업 결과가 화면에 남지 않게 지운다.
          setSupportResult(null);
          setSupportLoad({ status: "idle", message: null });
          // 「마지막에 본 것은 지원사업」이라는 기억도 함께 지운다. 남겨 두면 쿼리 없는 `/` 로
          // 돌아왔을 때 방금 닫은 지원사업이 되살아난다.
          clearSelectedSupport();
          applyLoaded(loaded, revealIntervalMs);
          if (!loaded.source) {
            report("notice", "failed", loaded.sourceError);
            return;
          }
          logLoadedSource(report, loaded.source);
          loadResolutions(token, loaded.selectedId);
          loadReview(token, loaded.selectedId);
          // 공고·요구사항이 그려진 뒤 자격판정 → 제안서 → Auditor를 뒤이어 채운다 (선택한 회사·근거 범위에 고정).
          setAnalysisLoading(true);
          const hasRequirements = (loaded.source.parse?.requirements.length ?? 0) > 0;
          void loadAnalysis(
            loaded.selectedId,
            hasRequirements,
            report,
            analysisContext(loaded.selectedId, organizationId),
            // 늦게 온 응답이 새 공고의 화면을 덮지 않도록 토큰을 확인한다.
            (patch) => {
              if (token !== requestRef.current) return;
              setAnalysis((prev) => ({ ...prev, ...patch }));
            },
          ).then(
            (analysis) => {
              if (token !== requestRef.current) return;
              setAnalysis(analysis);
              setAnalysisLoading(false);
            },
            () => {
              if (token !== requestRef.current) return;
              setAnalysisLoading(false);
            },
          );
        },
        (error: unknown) => {
          if (token !== requestRef.current) return;
          report("notice", "failed", describeError(error));
          setListState({ status: "error", message: null });
          setLoad({ kind: "error", message: describeError(error) });
        },
      );
    },
    [applyLoaded, days, loadResolutions, loadReview, makeReporter, organizationId, requestedId],
  );

  /**
   * 최신 fetchAll 을 ref 로 들고 다닌다 — **effect 의 의존성에서 빼기 위해서다.**
   *
   * fetchAll 은 useCallback 이고 그 deps(applyLoaded·loadResolutions·makeReporter 등)가
   * 하나라도 새 함수가 되면 identity 가 바뀐다. 그때마다 로드 effect 가 다시 돌아
   * 한 번 여는 동안 분석을 **두 번** 불러왔다 — `POST /api/auditor/run` 이 2회 나간 이유다
   * (첫 번째는 기본 회사, 두 번째는 저장된 회사로 돌아 검사 키까지 갈렸다).
   *
   * 다시 불러올 이유는 «무엇을 보는가»가 바뀔 때뿐이다: 고른 공고와 회사.
   */
  const fetchAllRef = useRef(fetchAll);
  useEffect(() => {
    fetchAllRef.current = fetchAll;
  }, [fetchAll]);

  /**
   * 처음 보여 준 실제 1위를 사람이 쓰기 시작하면(같은 공고를 다시 고름 · 분석을 마침) 그 공고를 기억한다 — 기억하지 않으면
   * 메뉴 · 회사자료 「보던 공고로」 · 정리표가 그 공고를 몰라 다른 화면과 끊겼다(2.0.6). 기억하면 requestedId 가 바뀌는데,
   * 이미 그 공고를 보고 있으니 **다시 불러오지 않는다**(다시 부르면 분석 결과를 처음부터 다시 그렸다). 그 한 번을 이 표시로 건너뛴다.
   */
  const adoptRef = useRef<string | null>(null);
  const adoptDefault = useCallback((id: string) => {
    // 이미 고른 것이 있거나(그때는 requestedId 가 바뀌지 않아 표시가 남는다) 가상 예시 · 지원사업이면 하지 않는다.
    if (readSelection() !== null || isDemoProcurementId(id) || isSupportProgramId(id)) return;
    adoptRef.current = id;
    writeSelection(id, "replace");
  }, []);

  useEffect(() => {
    // hydration 렌더에서는 저장된 선택을 아직 모른다. 여기서 데모 공고를 불러 버리면
    // 바로 다음 렌더에서 취소되므로, 스냅샷이 갈아탄 뒤 한 번만 불러온다.
    if (!hydrated) return;
    const cleanup = () => {
      // 보고 있는 1위를 기억만 하는 참이면 도는 일을 끊지 않는다(위 adoptDefault).
      if (adoptRef.current !== null) return;
      requestRef.current += 1;
      clearTimers();
      // 새 로드가 도는 분석을 대신한다 — 끊긴 분석 토큰은 finally 에서 풀리지 않아 「분석 중…」이 잠긴 채 남았다(2.0.5).
      setAnalyzing(false);
    };
    if (adoptRef.current !== null && adoptRef.current === requestedId) {
      adoptRef.current = null;
      // 다시 불러오지만 않는다 — 정리 함수는 그대로 둔다. 없으면 그 뒤 회사 · 공고가 바뀔 때 「분석 중…」이 잠긴 채 남았다(2.0.6 통합 검토).
      return cleanup;
    }
    adoptRef.current = null;
    void fetchAllRef.current(INITIAL_REVEAL_INTERVAL_MS);
    return cleanup;
    // fetchAll 은 일부러 넣지 않는다 (위 주석). 공고·회사가 바뀔 때만 다시 부른다.
  }, [hydrated, requestedId, organizationId, clearTimers]);

  /**
   * 조회 기간이 바뀌면(다른 탭) **나라장터 목록만** 새로 받는다 — 순위(아래 통합 목록)는 새 기간인데 목록은 옛 기간이었다(2.0.5).
   * 보는 공고 · 분석 · 저장 안 한 검토는 건드리지 않는다(전체를 다시 불러오면 도는 분석이 끊겼다). 첫 값은 위 로드가 받는다.
   */
  const listDaysRef = useRef(days);
  useEffect(() => {
    if (!hydrated || listDaysRef.current === days) return;
    listDaysRef.current = days;
    let live = true;
    getProcurements({ days }).then(
      (procurements) => {
        if (!live) return;
        setList(procurements);
        setListState({ status: "ready", message: null });
      },
      (error: unknown) => {
        if (live) setListState({ status: "error", message: describeError(error) });
      },
    );
    return () => {
      live = false;
    };
  }, [hydrated, days]);

  /**
   * 기업마당 지원사업을 선택기용으로 따로 불러온다.
   *
   * 회사가 바뀌면 다시 받는다 — 우선순위와 신청자격이 회사 기준으로 계산되기 때문이다.
   * 늦게 도착한 응답이 새 회사 목록을 덮지 않도록 토큰으로 막는다(다른 로더와 같은 방식).
   */
  const supportTokenRef = useRef(0);
  /** 「다시 시도」가 고르기 칸 통합 목록(순번 · 점수 · 기업마당)도 다시 받게 올리는 수 — 예전엔 회사 · 기간이 바뀔 때만 다시 받았다(2.0.6). */
  const [pickerTick, setPickerTick] = useState(0);
  /** 통합 목록 응답을 고르기 칸 상태에 싣는다 — 아래 effect 와 `reloadLists` 가 함께 쓴다. */
  const applyPicker = useCallback((response: UnifiedOpportunityListResponse, key: string) => {
    // 한 출처만 실패하면 서버는 200 + 그 출처 빈 목록 + source_errors 다 — 「없음」이 아니라 실패로 보인다(2.0.6).
    const g2bError = sourceFailure(response, "g2b");
    // 다 들고 있다가 고르기 칸에서 앞 n건만 싣는다 — 지금 고른 지원사업이 그 밖이어도 제 이름으로 서게(2.0.5).
    setSupportPrograms(response.items.filter((item) => item.source_type === "bizinfo"));
    setNoticePriority(new Map(response.items.filter((item) => item.source_type === "g2b").map((item) => [item.id, item])));
    // 나라장터 순위를 못 받았으면 거기 없는 공고를 「목록 밖」으로 보지 않는다 — 모두 「[불가·마감]」으로 접힐 뻔했다.
    setPriorityState({ key, loaded: !g2bError, error: g2bError });
    setSupportError(sourceFailure(response, "bizinfo"));
  }, []);
  useEffect(() => {
    const token = ++supportTokenRef.current;
    // 효과 본문에서 곧바로 setState 하지 않는다 — 응답이 온 뒤에만 상태를 건드린다.
    // 두 출처를 **함께** 받는다 (0920 §4-B-1). 예전에는 기업마당만 받아서 나라장터 공고의
    // 검토 우선순위를 대시보드가 아예 몰랐고, 그래서 선택창 순서가 목록과 뒤집혀 있었다.
    // 자르지 않고 다 받는다 — 여기 없는 나라장터 공고를 「목록 밖(불가 · 실제 마감)」으로 셀 수 있어야 고르기 칸이
    // 레이더 · 사업기회와 같은 후보 수를 보인다(2.0.6 · 200건에서 잘려 188 대 116 으로 갈렸다).
    getBusinessOpportunities({ organizationId, source: "all", days })
      .then((response) => {
        if (token !== supportTokenRef.current) return;
        applyPicker(response, `${organizationId}:${days}`);
      })
      .catch((error: unknown) => {
        if (token !== supportTokenRef.current) return;
        // 없는 것과 못 받은 것은 다르다. 「지원사업 없음」이라고 말하지 않는다.
        const message = describeError(error);
        setSupportPrograms(null);
        setNoticePriority(new Map());
        setPriorityState({ key: `${organizationId}:${days}`, loaded: false, error: message });
        setSupportError(message);
      });
  }, [organizationId, days, pickerTick, applyPicker]);

  /**
   * 고르기 칸 목록만 다시 받는다(2.0.7 · 「찾는 낱말」 바로 찾기로 새 공고가 들어왔을 때) — 나라장터 목록 + 통합 순위.
   * 보는 공고 · 분석 · 저장 안 한 검토는 건드리지 않는다(`reload` 는 분석을 처음부터 다시 그린다).
   * **둘 다 성공했을 때만 덮는다** — 바로 찾기는 됐는데 다시 받기가 실패해 잘 보이던 고르기 칸(기업마당 묶음 · 순번)이 오류로 바뀌면
   * 안 된다(frontend-6 · 한 출처만 실패한 200 응답도 실패로 본다). 그사이 회사 · 기간이 바뀌었으면 늦은 응답은 버린다(새 effect 가 받는다).
   * 토큰을 올리지 않는다 — 그 effect 의 요청을 끊지 않게 지금 토큰과 같을 때만 싣는다.
   */
  const reloadLists = useCallback(() => {
    const asked = days;
    getProcurements({ days: asked }).then(
      (procurements) => {
        if (listDaysRef.current !== asked) return;
        setList(procurements);
        setListState({ status: "ready", message: null });
      },
      () => {},
    );
    const token = supportTokenRef.current;
    getBusinessOpportunities({ organizationId, source: "all", days: asked }).then(
      (response) => {
        if (token !== supportTokenRef.current || sourceFailure(response, "g2b") || sourceFailure(response, "bizinfo")) return;
        applyPicker(response, `${organizationId}:${asked}`);
      },
      () => {},
    );
  }, [organizationId, days, applyPicker]);

  const reload = useCallback(() => {
    clearTimers();
    setAnalyzing(false);
    setAnalysisError(null);
    setAnalysis(EMPTY_ANALYSIS);
    setListState({ status: "loading", message: null });
    setLoad({ kind: "loading" });
    setPickerTick((n) => n + 1);
    void fetchAll(INITIAL_REVEAL_INTERVAL_MS);
  }, [clearTimers, fetchAll]);

  const selectNotice = useCallback(
    (id: string) => {
      // 처음 보여 준 1위를 고르기 칸에서 다시 고르면 「이 공고로 한다」는 뜻이다 — 기억만 하고 다시 불러오지 않는다(2.0.6).
      if (load.kind === "ready" && requestedId === null && id === fallbackId) {
        adoptDefault(id);
        return;
      }
      // 오류 화면에서는 같은 id 도 다시 연다 — 목록 실패 화면의 「가상 예시」(fallbackId 와 같은 id)가 아무 일도 안 했다(2.0.5).
      if (load.kind !== "error" && id === (requestedId ?? fallbackId)) return;
      clearTimers();
      setStaleNotice(null);
      setAnalyzing(false);
      setAnalysisError(null);
      setAnalysis(EMPTY_ANALYSIS);
      setReviewDecision(null);
      // 저장된 검토는 공고마다 다르다 — 새로 읽기 전까지 이전 공고의 값을 남기지 않는다.
      setSavedReview(null);
      setReviewError(null);
      setResolutions([]);
      setResolutionError(null);
      setListState((prev) => ({ status: "loading", message: prev.message }));
      setLoad({ kind: "loading" });
      /**
       * requestedId 변경 → fetchAll 재생성 → effect 가 다시 로드한다.
       *
       * 주소에 남았으면 보조 기억을 **비운다.** 남겨 두면 뒤로가기로 직전 공고에 돌아왔을 때
       * `base` 가 그 공고와 같아져 보조 기억이 되살아나고, 주소는 입찰인데 화면은 지원사업인
       * 상태가 된다 — 실제로 그랬다.
       */
      const persisted = persistNoticeId(id);
      // 가상 예시는 주소에 남기지 않는다 — 그래도 고른 것은 기억한다. 고르지 않은 첫 화면이 이제 실제 1위라서, 기억이 없으면
      // 첫 화면에서는 「불러오는 중」에 멈추고 실제 공고를 보던 중이면 가상 예시 대신 실제 1위가 열렸다(36차 마지막 검토 FE-1).
      // `base` 는 비운 **뒤의** 주소 — 뒤로가기로 주소가 바뀌면 기억을 버리고 주소를 따른다.
      setChosen(isDemoProcurementId(id) ? { id, base: readSelection() } : persisted ? null : { id, base: persistedId });
    },
    [clearTimers, requestedId, fallbackId, persistedId, load.kind, adoptDefault],
  );

  const runConsentedAnalysis = useCallback((targetId: string, consent: RfpConsent, keepDefault = false) => {
    const token = ++requestRef.current;
    const report = makeReporter(token);
    clearTimers();
    setAnalyzing(true);
    setAnalysisError(null);
    setRunLog(emptyRunLog());
    report("notice", "running");
    report("parse", "running", RFP_PARSE_PHASE_LABEL[consent === "fetch" ? "fetching" : "parsing"]);
    let parseFailure: string | null = null;
    parseRfp(targetId, { fetchAttachment: consent === "fetch" })
      .then(
        () => loadDashboard(targetId, days, organizationId),
        (error: unknown) => {
          // 파싱 자체가 안 되는 공고는 기존 화면을 유지하고 사유만 알린다.
          parseFailure = describeParseError(error);
          if (token === requestRef.current) setAnalysisError(parseFailure);
          return loadDashboard(targetId, days, organizationId);
        },
      )
      .then(
        (loaded) => {
          if (token !== requestRef.current) return;
          // 처음 보여 준 실제 1위(고르지 않음)를 분석했으면 그대로 「고르지 않은 기본」으로 둔다 — 주소에 쓰면 고른 공고가 바뀐 것으로
          // 보고 처음부터 다시 불러와, 분석 토큰이 끊겨 「분석 중…」이 잠긴 채 남고 판정도 두 번 돌았다(36차 마지막 검토 FE-2).
          applyLoaded(keepDefault ? { ...loaded, defaulted: true } : loaded, ANALYSIS_REVEAL_INTERVAL_MS);
          // 처음 보여 준 1위를 분석했으면 결과가 그려진 **지금** 기억한다 — 배경 읽기가 다 끝난 뒤에 하면 그 사이 메뉴로 떠날 때
          // 영영 기억되지 않았다(2.0.6 통합 검토). 기억해도 다시 불러오지 않고(adoptRef) 도는 읽기도 끊지 않는다(정리 함수가 건너뜀).
          if (keepDefault && loaded.source?.origin.kind === "real") adoptDefault(loaded.selectedId);
          if (!loaded.source) {
            report("notice", "failed", loaded.sourceError);
            return;
          }
          logLoadedSource(report, loaded.source);
          if (parseFailure) report("parse", "failed", parseFailure);
          loadResolutions(token, loaded.selectedId);
          loadReview(token, loaded.selectedId);
          setAnalysisLoading(true);
          const hasRequirements = (loaded.source.parse?.requirements.length ?? 0) > 0;
          void loadAnalysis(
            loaded.selectedId,
            hasRequirements,
            report,
            analysisContext(loaded.selectedId, organizationId),
            // 늦게 온 응답이 새 공고의 화면을 덮지 않도록 토큰을 확인한다.
            (patch) => {
              if (token !== requestRef.current) return;
              setAnalysis((prev) => ({ ...prev, ...patch }));
            },
          ).then(
            (analysis) => {
              if (token !== requestRef.current) return;
              setAnalysis(analysis);
              setAnalysisLoading(false);
            },
            () => {
              if (token !== requestRef.current) return;
              setAnalysisLoading(false);
            },
          );
        },
        (error: unknown) => {
          if (token !== requestRef.current) return;
          const message = describeError(error);
          setAnalysisError(message);
          // 이미 그래프가 있으면 유지하고 (CLAUDE.md §20), 없을 때만 error 상태로 간다.
          setLoad((prev) => (prev.kind === "ready" ? prev : { kind: "error", message }));
        },
      )
      .finally(() => {
        if (token === requestRef.current) setAnalyzing(false);
      });
  }, [adoptDefault, applyLoaded, clearTimers, days, loadResolutions, loadReview, makeReporter, organizationId]);

  const runAnalysis = useCallback(() => {
    const targetId = requestedId ?? fallbackId;
    // **먼저 묻는다** — 로컬에 없는 실공고 첨부는 사람이 파일 이름을 보고 확인해야 받는다(27차 §3-A-3 · /rfp 와 같은 도우미).
    // 취소하면 화면 상태를 하나도 바꾸지 않는다: 예전에는 토큰 · 실행 기록 · 오류를 먼저 비워서, 취소하면 「불러오는 중」이
    // 영영 남았다(27차 검수 C16).
    void askRfpConsent(targetId).then((consent) => {
      if (consent !== null) runConsentedAnalysis(targetId, consent, requestedId === null);
    });
  }, [requestedId, fallbackId, runConsentedAnalysis]);

  // -------------------------------------------------------------------------
  // 실분석 동작 (사용자가 화면에서 직접 실행)
  // -------------------------------------------------------------------------

  const activeNoticeId = requestedId ?? fallbackId;
  /** 현재 공고 분석이 고정된 회사·근거 범위. 회사를 바꾸면 fetchAll 이 다시 돌아 결과를 새로 읽는다. */
  const context = useMemo(() => analysisContext(activeNoticeId, organizationId), [activeNoticeId, organizationId]);

  /**
   * 사람이 **직접 누른 것**이 실패했을 때의 문구.
   *
   * 로드 경로(describeError)만 lib/errors 로 옮기고 이 함수는 남겨 뒀었다 — 그래서
   * 제안서 생성·제출 전 점검·참가자격·조건·결정·해결 처리 10곳의 실패가 여전히
   * 「(HTTP 500)」과 「FastAPI 서버가 실행 중인지 확인해 주세요」로 나왔다.
   * 사용자가 실제로 만나는 실패가 대부분 이 함수를 지난다.
   */
  const describeAction = useCallback(
    (error: unknown, fallback: string): string => describeFailure(error, fallback),
    [],
  );

  /**
   * 사용자가 누른 요청의 «임자»를 기억한다 (ISSUE-009 · TASK-011).
   *
   * 로드 경로는 `requestRef` 토큰으로 보호돼 있었지만, 사람이 직접 누른 요청들은
   * 응답 시점에 공고를 비교하지 않고 그대로 `setAnalysis` 했다. 느린 생성 중에 공고를
   * 바꾸면 **A 공고의 제안서·검사 결과가 B 공고 화면에 들어간다.**
   * 담당자는 그것을 B 의 결과로 읽는다 — 이 화면에서 제일 나쁜 종류의 오류다.
   *
   * 누를 때의 공고·회사를 붙잡아 두고, 응답이 왔을 때 화면이 아직 그것인지 묻는다.
   *
   *     const stale = analysisGuard();
   *     doSomething().then(() => { if (stale()) return; ... });
   */
  const analysisKey = `${activeNoticeId}::${organizationId}`;
  const analysisKeyRef = useRef(analysisKey);
  const [progressOwner, setProgressOwner] = useState(analysisKey);
  useEffect(() => {
    analysisKeyRef.current = analysisKey;
  }, [analysisKey]);

  const analysisGuard = useCallback(() => {
    const startedWith = analysisKeyRef.current;
    // 진행 표시(busy·오류 문구)의 «임자»도 함께 적어 둔다. 아래 `ownsProgress` 참고.
    setProgressOwner(startedWith);
    return () => analysisKeyRef.current !== startedWith;
  }, []);

  /**
   * 진행 표시는 그 요청을 **시작한** 공고·회사의 것이다.
   *
   * 가드가 늦게 온 응답을 반영하지 못하게 막아도, 그 요청이 켜 둔 `busy` 는 남는다.
   * 그러면 새 공고 화면에서 버튼이 「만드는 중…」인 채 영원히 비활성이 되고 담당자는
   * 돌아가지도 않는 작업을 기다린다. 지우는 대신 **읽을 때 임자를 확인**한다 —
   * effect 로 state 를 되돌리면 렌더가 한 번 더 돌고, 그 사이 한 프레임이 깜빡인다.
   */
  const ownsProgress = progressOwner === analysisKey;

  const logPhase = useCallback((key: RunPhaseKey, status: RunPhaseStatus, detail: string | null = null) => {
    setRunLog((prev) => ({ ...prev, [key]: { key, status, detail } }));
  }, []);

  const doGenerateProposal = useCallback(() => {
    const stale = analysisGuard();
    setBusy((prev) => ({ ...prev, proposal: true }));
    setActionError((prev) => ({ ...prev, proposal: null }));
    logPhase("proposal", "running");
    generateProposal(activeNoticeId, context)
      .then(
        (section) => {
          if (stale()) return;
          // 초안이 바뀌었으므로 이전 검사 결과는 무효다 — 지우고 다시 실행하게 한다.
          setAnalysis((prev) => ({ ...prev, proposal: section, audit: null }));
          logPhase("proposal", "done", `${section.sentences.length}문장 · 확인 필요 ${section.needs_review_count}`);
          logPhase("audit", "pending", "초안이 바뀌어 다시 검사 필요");
        },
        (error: unknown) => {
          if (stale()) return;
          setActionError((prev) => ({
            ...prev,
            proposal: describeAction(error, "제안서 생성에 실패했습니다."),
          }));
          logPhase("proposal", "failed", describePhaseError(error));
        },
      )
      .finally(() => setBusy((prev) => ({ ...prev, proposal: false })));
  }, [analysisGuard, describeAction, activeNoticeId, context, logPhase]);

  const applyAudit = useCallback(
    (run: AuditRunResult) => {
      setAnalysis((prev) => ({ ...prev, audit: run }));
      logPhase(
        "audit",
        "done",
        `발견 ${run.findings.length}건 · 필수 반영 ${run.coverage.covered}/${run.coverage.total}${run.llm_used ? " · AI 정밀" : ""}`,
      );
    },
    [logPhase],
  );

  const doRunAudit = useCallback(
    (proposalText: string, options: { useLlm?: boolean } = {}) => {
      const stale = analysisGuard();
      setBusy((prev) => ({ ...prev, audit: true }));
      setActionError((prev) => ({ ...prev, audit: null }));
      logPhase("audit", "running");
      runAuditor(activeNoticeId, proposalText, options, context)
        .then((run) => {
          if (stale()) return;
          applyAudit(run);
        }, (error: unknown) => {
          if (stale()) return;
          // 요구사항이 바뀐 뒤 저장된 초안 그대로면 서버가 409 로 막는다(사유는 객체라 글로 오지 않는다) — 새로 고쳐도
          // 풀리지 않으니 「새로 고치세요」 대신 할 일을 적는다 (DTL-12).
          const staleDraft = error instanceof ApiError && error.status === 409 && !error.detail;
          setActionError((prev) => ({
            ...prev,
            audit: staleDraft
              ? "요구사항이 바뀌어 저장된 초안으로는 점검할 수 없습니다 — 제안서를 다시 만들거나, 고친 초안을 붙여 넣은 뒤 점검하세요."
              : describeAction(error, "제출 전 누락 점검에 실패했습니다."),
          }));
          logPhase("audit", "failed", describePhaseError(error));
        })
        .finally(() => setBusy((prev) => ({ ...prev, audit: false })));
    },
    [analysisGuard, applyAudit, describeAction, activeNoticeId, context, logPhase],
  );

  const doRunAuditUpload = useCallback(
    (file: File, options: { useLlm?: boolean } = {}) => {
      const stale = analysisGuard();
      setBusy((prev) => ({ ...prev, audit: true }));
      setActionError((prev) => ({ ...prev, audit: null }));
      logPhase("audit", "running", `업로드 검사 · ${file.name}`);
      runAuditorUpload(activeNoticeId, file, options, context)
        .then((run) => {
          if (stale()) return;
          applyAudit(run);
        }, (error: unknown) => {
          if (stale()) return;
          setActionError((prev) => ({
            ...prev,
            audit: describeAction(error, "업로드한 제안서 검사에 실패했습니다."),
          }));
          logPhase("audit", "failed", describePhaseError(error));
        })
        .finally(() => setBusy((prev) => ({ ...prev, audit: false })));
    },
    [analysisGuard, applyAudit, describeAction, activeNoticeId, context, logPhase],
  );

  const doRefreshEligibility = useCallback(
    (options: { useLlm?: boolean } = {}) => {
      const stale = analysisGuard();
      setBusy((prev) => ({ ...prev, eligibility: true }));
      setActionError((prev) => ({ ...prev, eligibility: null }));
      logPhase("eligibility", "running", options.useLlm ? "규칙 + AI 보강" : "규칙 판정");
      evaluateEligibility(activeNoticeId, options, context)
        .then(
          (report) => {
            if (stale()) return;
            setAnalysis((prev) => ({ ...prev, eligibility: report }));
            logPhase(
              "eligibility",
              "done",
              `${ELIGIBILITY_LABELS[report.verdict] ?? report.verdict} · ${eligibilityTallyText(report.counts.passed, report.counts.check, report.counts.failed)}${report.llm_used ? " · AI 보강" : ""}`,
            );
          },
          (error: unknown) => {
            if (stale()) return;
            setActionError((prev) => ({
              ...prev,
              eligibility: describeAction(error, "참가자격 판정에 실패했습니다."),
            }));
            logPhase("eligibility", "failed", describePhaseError(error));
          },
        )
        .finally(() => setBusy((prev) => ({ ...prev, eligibility: false })));
    },
    [analysisGuard, describeAction, activeNoticeId, context, logPhase],
  );

  // -------------------------------------------------------------------------
  // Critical Condition · Action Checklist · GO/HOLD/NO_GO (사람의 기록)
  // -------------------------------------------------------------------------

  const [gateBusy, setGateBusy] = useState(false);
  const [gateError, setGateError] = useState<string | null>(null);

  const refreshChecklist = useCallback(() => {
    const stale = analysisGuard();
    getActions(activeNoticeId, context).then(
      (checklist) => {
        if (stale()) return;
        setAnalysis((prev) => ({ ...prev, checklist }));
      },
      () => undefined,
    );
  }, [analysisGuard, activeNoticeId, context]);

  const doDetectConditions = useCallback(() => {
    const stale = analysisGuard();
    setGateBusy(true);
    setGateError(null);
    logPhase("conditions", "running");
    detectConditions(activeNoticeId, context)
      .then(
        (conditions) => {
          if (stale()) return;
          setAnalysis((prev) => ({ ...prev, conditions }));
          logPhase("conditions", "done", conditionCountsText(conditions.counts));
          refreshChecklist();
        },
        (error: unknown) => {
          if (stale()) return;
          setGateError(describeAction(error, "참가 차단 조건 찾기에 실패했습니다."));
          logPhase("conditions", "failed", describePhaseError(error));
        },
      )
      .finally(() => setGateBusy(false));
  }, [analysisGuard, activeNoticeId, context, describeAction, logPhase, refreshChecklist]);

  const doUpdateCondition = useCallback(
    (conditionId: string, body: ConditionUpdateRequest): Promise<boolean> => {
      const stale = analysisGuard();
      setGateBusy(true);
      setGateError(null);
      return updateCondition(activeNoticeId, conditionId, body, context)
        .then(
          (conditions) => {
            if (stale()) return true;
            setAnalysis((prev) => ({ ...prev, conditions }));
            refreshChecklist();
            return true;
          },
          (error: unknown) => {
            if (stale()) return false;
            setGateError(describeAction(error, "조건 상태를 저장하지 못했습니다."));
            return false;
          },
        )
        .finally(() => setGateBusy(false));
    },
    [analysisGuard, activeNoticeId, context, describeAction, refreshChecklist],
  );

  const doUpdateAction = useCallback(
    (actionId: string, body: ActionUpdateRequest) => {
      const stale = analysisGuard();
      setGateBusy(true);
      setGateError(null);
      updateAction(activeNoticeId, actionId, body, context)
        .then(
          () => {
            if (stale()) return;
            refreshChecklist();
          },
          (error: unknown) => {
            if (stale()) return;
            setGateError(describeAction(error, "체크리스트 항목을 저장하지 못했습니다."));
          },
        )
        .finally(() => setGateBusy(false));
    },
    [analysisGuard, activeNoticeId, context, describeAction, refreshChecklist],
  );

  const doDeleteAction = useCallback(
    (actionId: string) => {
      const stale = analysisGuard();
      setGateBusy(true);
      setGateError(null);
      deleteAction(activeNoticeId, actionId, context)
        .then(
          () => {
            if (stale()) return;
            refreshChecklist();
          },
          (error: unknown) => {
            if (stale()) return;
            setGateError(describeAction(error, "체크리스트 항목을 지우지 못했습니다."));
          },
        )
        .finally(() => setGateBusy(false));
    },
    [analysisGuard, activeNoticeId, context, describeAction, refreshChecklist],
  );

  const doCreateAction = useCallback(
    (body: ActionCreateRequest) => {
      const stale = analysisGuard();
      setGateBusy(true);
      setGateError(null);
      createAction(activeNoticeId, body, context)
        .then(
          () => {
            if (stale()) return;
            refreshChecklist();
          },
          (error: unknown) => {
            if (stale()) return;
            setGateError(describeAction(error, "체크리스트 항목을 추가하지 못했습니다."));
          },
        )
        .finally(() => setGateBusy(false));
    },
    [analysisGuard, activeNoticeId, context, describeAction, refreshChecklist],
  );

  const doSaveDecision = useCallback(
    (body: DecisionRequest): Promise<boolean> => {
      const stale = analysisGuard();
      setGateBusy(true);
      setGateError(null);
      return saveDecision(activeNoticeId, body, context)
        .then(
          (decision) => {
            if (stale()) return true;
            setAnalysis((prev) => ({ ...prev, decision, decisionError: null }));
            // 처음 보여 준 1위에서 결정했으면 그 공고를 기억한다 — 분석을 다시 돌릴 때만 기억했다(2.0.6 마지막 검토 · adoptDefault 가 이미 고른 것 · 가상 예시는 거른다)
            adoptDefault(activeNoticeId);
            return true;
          },
          (error: unknown) => {
            if (stale()) return false;
            setGateError(describeAction(error, "결정을 저장하지 못했습니다."));
            return false;
          },
        )
        .finally(() => setGateBusy(false));
    },
    [adoptDefault, analysisGuard, activeNoticeId, context, describeAction],
  );

  const currentAuditRunId = analysis.audit?.id ?? null;

  /**
   * 담당자가 참가자격 조항 하나를 확인한다 (20차 §4-C). 응답은 그 확인을 합친 판정 전체라서
   * 띠·타일·체크리스트가 한 번에 바뀐다. 충족·미충족의 빈 메모(422)·스냅샷 배포(503)는 문구 그대로 보인다.
   */
  const doSaveClauseReview = useCallback(
    (clauseId: string, body: ClauseReviewRequest): Promise<boolean> => {
      const stale = analysisGuard();
      setClauseReviewBusy(clauseId);
      setClauseReviewError(null);
      return saveClauseReview(activeNoticeId, clauseId, body, context)
        .then(
          (report) => {
            if (stale()) return true;
            setAnalysis((prev) => ({ ...prev, eligibility: report }));
            return true;
          },
          (error: unknown) => {
            if (stale()) return false;
            setClauseReviewError(describeAction(error, "조항 확인을 저장하지 못했습니다."));
            return false;
          },
        )
        .finally(() => setClauseReviewBusy(null));
    },
    [analysisGuard, activeNoticeId, context, describeAction],
  );

  /** 담당자가 발견 항목을 해결/재오픈으로 기록한다. 검사 결과 파일은 바뀌지 않는다. */
  const doSetFindingResolution = useCallback(
    (finding: AuditFinding, body: { status: ResolutionStatus; reviewer: string; note?: string | null }): Promise<boolean> => {
      const stale = analysisGuard();
      setResolutionBusy(true);
      setResolutionError(null);
      return saveFindingResolution(activeNoticeId, {
        key: findingResolutionKey(finding),
        status: body.status,
        finding_type: finding.finding_type,
        requirement_id: finding.requirement_id ?? null,
        finding_id: finding.id,
        audit_run_id: currentAuditRunId,
        reviewer: body.reviewer,
        note: body.note ?? null,
      }, context)
        .then(
          (saved) => {
            if (stale()) return true;
            setResolutions((prev) => [...prev.filter((r) => r.key !== saved.key), saved]);
            return true;
          },
          (error: unknown) => {
            if (stale()) return false;
            setResolutionError(describeAction(error, "해결 처리를 저장하지 못했습니다."));
            return false;
          },
        )
        .finally(() => setResolutionBusy(false));
    },
    [analysisGuard, activeNoticeId, context, currentAuditRunId, describeAction],
  );

  // -------------------------------------------------------------------------
  // 사람의 최종 검토 (Human Review) — 화면 state 가 아니라 서버에 남긴다
  // -------------------------------------------------------------------------

  /**
   * 검토 결과를 저장한다.
   *
   * 승인은 backend 가 확인 항목 4개를 모두 요구한다(422). 화면 토글은 곧바로 바꾸되
   * **저장됐다고 말하지 않는다** — 저장 전·실패 상태는 `unsaved` 로 남아 화면에
   * 「임시 (저장 전)」과 실패 사유가 함께 뜬다.
   */
  const doSaveReview = useCallback(
    (input: ReviewSaveInput): Promise<boolean> => {
      const stale = analysisGuard();
      setReviewSaving(true);
      setReviewError(null);
      setReviewDecision(reviewToggle(input.status));
      return saveReview(
        {
          procurement_id: activeNoticeId,
          status: input.status,
          checklist: input.checklist,
          reviewer: input.reviewer,
          note: input.note ?? null,
          // 무엇을 보고 결정했는지 — 승인 근거를 함께 남긴다.
          audit_run_id: analysis.audit?.id ?? null,
          proposal_id: analysis.proposal?.id ?? null,
        },
        context,
      )
        .then(
          (saved) => {
            if (stale()) return false;
            setSavedReview(saved);
            setReviewDecision(reviewToggle(saved.status));
            adoptDefault(activeNoticeId);  // 결정 저장과 같다(2.0.6)
            return true;
          },
          (error: unknown) => {
            if (stale()) return false;
            setReviewError(describeAction(error, "최종 검토 결과를 저장하지 못했습니다."));
            return false;
          },
        )
        .finally(() => setReviewSaving(false));
    },
    [adoptDefault, analysisGuard, activeNoticeId, analysis.audit, analysis.proposal, context, describeAction],
  );

  const doClearReview = useCallback(() => {
    setReviewError(null);
    if (!savedReview) {
      setReviewDecision(null);
      return;
    }
    // 저장된 적이 있으면 서버에서도 되돌린다 (담당자·확인 항목 기록은 그대로 둔다).
    void doSaveReview({
      status: "pending",
      checklist: savedReview.checklist ?? EMPTY_CHECKLIST,
      reviewer: savedReview.reviewer,
      note: savedReview.note,
    });
  }, [doSaveReview, savedReview]);

  const review = useMemo<ReviewState>(
    () => ({
      saved: savedReview,
      saving: reviewSaving,
      error: reviewError,
      unsaved: reviewDecision !== reviewToggle(savedReview?.status),
      save: doSaveReview,
      clear: doClearReview,
    }),
    [doClearReview, doSaveReview, reviewDecision, reviewError, reviewSaving, savedReview],
  );

  const actions = useMemo<AnalysisActions>(
    () => ({
      // 진행 표시·오류 문구는 그 요청을 «시작한» 공고·회사의 것일 때만 보여 준다.
      // 다른 공고로 넘어간 뒤에도 남아 있으면, 눌러도 되는 버튼이 비활성으로 굳고
      // 이전 공고의 실패 문구가 새 공고의 것처럼 읽힌다 (ISSUE-009).
      aiDraft,
      proposalBusy: ownsProgress && busy.proposal,
      auditBusy: ownsProgress && busy.audit,
      eligibilityBusy: ownsProgress && busy.eligibility,
      proposalError: ownsProgress ? actionError.proposal : null,
      auditError: ownsProgress ? actionError.audit : null,
      eligibilityError: ownsProgress ? actionError.eligibility : null,
      generateProposal: doGenerateProposal,
      runAudit: doRunAudit,
      runAuditUpload: doRunAuditUpload,
      refreshEligibility: doRefreshEligibility,
      clauseReviewBusy: ownsProgress ? clauseReviewBusy : null,
      clauseReviewError: ownsProgress ? clauseReviewError : null,
      saveClauseReview: doSaveClauseReview,
      resolutionBusy: ownsProgress && resolutionBusy,
      resolutionError: ownsProgress ? resolutionError : null,
      setFindingResolution: doSetFindingResolution,
      gateBusy: ownsProgress && gateBusy,
      gateError: ownsProgress ? gateError : null,
      detectConditions: doDetectConditions,
      updateCondition: doUpdateCondition,
      updateAction: doUpdateAction,
      createAction: doCreateAction,
      deleteAction: doDeleteAction,
      saveDecision: doSaveDecision,
    }),
    [
      actionError,
      aiDraft,
      busy,
      clauseReviewBusy,
      clauseReviewError,
      doSaveClauseReview,
      doCreateAction,
      doDeleteAction,
      doDetectConditions,
      doGenerateProposal,
      doRefreshEligibility,
      doRunAudit,
      doRunAuditUpload,
      doSaveDecision,
      doSetFindingResolution,
      doUpdateAction,
      doUpdateCondition,
      gateBusy,
      gateError,
      ownsProgress,
      resolutionBusy,
      resolutionError,
    ],
  );

  // 3D 에서 펼쳐 본 요구사항 유형. null 이면 집계 Overview 다.
  // 「전체 보기」는 모든 원시 노드를 펼치는 것이 아니라 **이 값을 null 로 되돌리는 것**이다.
  const [expandedCategory, setExpandedCategory] = useState<ItemType | null>(null);

  const graph = useMemo(
    () =>
      load.kind === "ready"
        ? buildCosmosGraph({ ...load.source, analysis }, { reviewDecision, resolutions, expandedCategory })
        : null,
    [analysis, load, reviewDecision, resolutions, expandedCategory],
  );

  const toggleCategory = useCallback((key: ItemType | null) => {
    setExpandedCategory((current) => (current === key ? null : key));
  }, []);

  const selectedNoticeId = requestedId ?? fallbackId;
  const priorityCurrent = priorityState.key === `${organizationId}:${days}`;
  const notices = useMemo(() => {
    // 기업마당은 앞 n건만 싣되, 지금 고른 지원사업이 그 밖이면 함께 싣는다.
    const all = supportPrograms ?? [];
    const shown = all.slice(0, SUPPORT_PICKER_LIMIT);
    const picked = all.find((item) => item.id === selectedNoticeId);
    if (picked && !shown.includes(picked)) shown.push(picked);
    const openNotice = load.kind === "ready" && load.source.notice.id === selectedNoticeId ? load.source.notice : null;
    // 10-31 최종 점검 A3 — 지원사업은 통합 목록 · 신청 분석을, 입찰은 나라장터 목록 · 연 공고를 다 받기 전이면 「읽는 중」
    const selectedPending = isSupportProgramId(selectedNoticeId)
      ? !priorityCurrent || supportLoad.status === "idle" || supportLoad.status === "loading"
      : listState.status === "loading" || load.kind === "loading";
    return buildNoticeOptions(list, selectedNoticeId, shown, noticePriority, supportResult?.program ?? openNotice, priorityCurrent && priorityState.loaded, selectedPending);
  }, [list, selectedNoticeId, supportPrograms, noticePriority, supportResult, priorityCurrent, priorityState.loaded, load, listState.status, supportLoad.status]);

  const noticeList = useMemo<NoticeListInfo>(
    () => ({
      status: listState.status,
      source: list?.source ?? null,
      fetchedAt: list?.fetched_at ?? null,
      totalFetched: list?.total_fetched ?? null,
      count: list?.count ?? null,
      message: listState.message ?? staleNotice ?? list?.error ?? null,
      priorityMessage: priorityCurrent ? priorityState.error : null,
      priorityPending: !priorityCurrent,
      // 비추천(관련 낮음)은 사업기회 · 레이더처럼 세지 않는다 — 넣으면 523 대 208 로 갈렸다(실측 10-27)
      supportTotal: supportPrograms ? supportPrograms.filter((item) => item.practical_group !== "비추천").length : null,
      openFailed: load.kind === "error",
    }),
    [list, listState, staleNotice, priorityCurrent, priorityState.error, supportPrograms, load.kind],
  );

  const status: DashboardStatus = isSupportProgramId(selectedNoticeId)
    ? // 지원사업은 입찰 그래프를 만들지 않는다. 요구사항 0건은 «비었다»가 아니라 «해당 없음»이다.
      supportLoad.status === "error"
      ? "error"
      : supportLoad.status === "ready"
        ? "ready"
        : "loading"
    : load.kind === "loading"
      ? "loading"
      : load.kind === "error"
        ? "error"
        : graph && graph.counts.requirements === 0
          ? "empty"
          : "ready";

  return {
    status,
    /**
     * 지금 고른 공고의 **검토 우선순위** (0~100, 선택 회사 기준). 모르면 null.
     *
     * 대시보드 KPI 「우리 회사 적합도」 옆에 이 값을 함께 적는다 — 같은 공고가 목록·레이더에서
     * 이 숫자로 보이는데 대시보드만 다른 숫자를 보여주고 있었다 (0920 §4-B-1).
     */
    selectedReviewPriority: noticePriority.get(selectedNoticeId)?.company_priority_score ?? null,
    /**
     * 화면에 보일 오류 문구.
     *
     * 지원사업이 실패했을 때는 `load` 가 아니라 `supportLoad` 에 사유가 있다. 예전에는 그것을
     * 읽지 않아 status 만 "error" 가 되고 문구는 null 이었다 — 화면에 「알 수 없는 오류」만
     * 남고 무엇이 왜 실패했는지 사라졌다.
     */
    error: isSupportProgramId(selectedNoticeId)
      ? supportLoad.message
      : load.kind === "error"
        ? load.message
        : null,
    analysisError,
    analysisLoading,
    graph,
    stage,
    revealDone,
    revealRun,
    setStage,
    analyzing,
    reviewDecision,
    setReviewDecision,
    review,
    reload,
    reloadLists,
    runAnalysis,
    notices,
    supportError,
    supportResult,
    supportLoad,
    selectedNoticeId,
    selectNotice,
    noticeList,
    staleNotice,
    actions,
    context,
    runLog,
    expandedCategory,
    toggleCategory,
  };
}

// ---------------------------------------------------------------------------
// 환경 감지 훅 (hydration-safe: 서버 스냅샷은 보수적 기본값)
// ---------------------------------------------------------------------------

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeReducedMotion(onChange: () => void): () => void {
  const media = window.matchMedia(REDUCED_MOTION_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const getReducedMotion = () => window.matchMedia(REDUCED_MOTION_QUERY).matches;
const getReducedMotionServer = () => false;

/** `prefers-reduced-motion: reduce` 여부. mount 전(서버)에는 false. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReducedMotion, getReducedMotion, getReducedMotionServer);
}

function subscribeVisibility(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}
const getVisible = () => document.visibilityState !== "hidden";
const getVisibleServer = () => true;

/** 탭이 보이는 상태인지 (숨겨지면 유휴 애니메이션을 멈춘다). */
export function useDocumentVisible(): boolean {
  return useSyncExternalStore(subscribeVisibility, getVisible, getVisibleServer);
}

const MINUTE_MS = 60_000;

function subscribeMinute(onChange: () => void): () => void {
  const id = window.setInterval(onChange, MINUTE_MS);
  return () => window.clearInterval(id);
}
const getMinute = () => Math.floor(Date.now() / MINUTE_MS);
const getMinuteServer = (): number | null => null;

/** 현재 시각(ms). 분 단위로만 갱신되며 서버 렌더에서는 null (마감 카운트다운의 hydration 불일치 방지). */
export function useNowMs(): number | null {
  const minute = useSyncExternalStore(subscribeMinute, getMinute, getMinuteServer);
  return minute === null ? null : minute * MINUTE_MS;
}

/**
 * 판정 · 제안서 · 점검을 뒤이어 읽는 동안(`analysisLoading`) 「… 아직 안 함」을 「… 불러오는 중…」으로.
 *
 * 10-31 최종 점검 A5 — 큰 카드는 「판정 결과를 불러오는 중입니다…」인데 출처 줄 「참가 판정: 아직 안 함」 · 8단계 3번 「아직 안 함」이
 * 함께 보여 「안 돌렸구나」로 읽혔다. 「아직 안 읽음」(제안요청서 — 첫 화면에 이미 아는 값)은 그대로 둔다.
 * 부품(.tsx)은 시험이 불러오지 못해 이 파일에 둔다.
 */
export function loadingText(text: string, loading: boolean): string {
  return loading && text.endsWith(NOT_RUN_SUMMARY) ? `${text.slice(0, -NOT_RUN_SUMMARY.length)}불러오는 중…` : text;
}
