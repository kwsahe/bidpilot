/**
 * Evidence Cosmos 그래프 빌더.
 *
 * 입력: 공고(ProcurementNotice — 나라장터 실공고 또는 데모 합성 공고)
 *      + RFP 파싱 결과(없을 수 있다)
 *      + 데모 시나리오(Evidence/Proposal/Auditor, source=demo_synthetic — 실제 공고에는 없다)
 * 출력: 3D/2D 렌더러와 상세 패널이 공유하는 노드·연결선·파생 상태.
 *
 * 우선순위는 항상 "실제 분석 결과 > 데모 시나리오 > 미실행"이다.
 * 자격판정/제안서/Auditor는 실제 API 결과(CosmosSource.analysis)가 있으면 그것을 쓰고,
 * 없을 때만 데모 시나리오 값을 쓰며, 둘 다 없으면 노드를 만들지 않고 "미실행"으로 남긴다
 * (가짜 수치를 만들지 않는다). Evidence Mapping은 아직 데모 시나리오에만 있다.
 *
 * 레이아웃과 상태 파생 규칙을 여기 한 곳에 두어 3D 없이도 같은 정보를 볼 수 있게 한다.
 */

import type {
  AuditFinding,
  DemoCosmosScenario,
  EligibilityResult,
  EvidenceDocument,
  EvidenceLink,
  ProposalSection,
  ProposalSentence,
  Severity,
} from "@/types/cosmos";
import type { CapabilityReport } from "@/types/capability";
import type {
  AuditReadiness,
  AuditRunResult,
  EligibilityReport,
  FindingResolution,
  GeneratedProposalSection,
} from "@/types/analysis";
import type { ProcurementNotice, ProcurementSource } from "@/types/procurement";
import type { Criticality, ItemType, Requirement, RfpParseResult } from "@/types/rfp";
import type { ActionChecklist, BidDecision, CriticalConditionReport } from "@/types/gate";
import type { SupportApplicationResult, SupportStepKey } from "@/types/opportunity";

// format.ts 는 graph.ts 에서 «타입만» 가져가므로(import type — 컴파일 뒤 사라진다) 순환이 생기지 않는다.
import { DECISION_LABELS, REVIEW_STATUS_LABELS, labelOf } from "@/lib/scoreNames";
import { DECISION_READ_FAILED, STEP_NAMES, SYNTHETIC_NOTICE, UNDECIDED } from "@/lib/terms";
import { runStamp, withRunStamp, type RunStampKey } from "./runStamp";
import { CANDIDATE_TIER_LABELS, ELIGIBILITY_LABELS, GENERATION_METHOD_LABELS, seriousText } from "./format";
import { eligibilityGateView, gateSummary } from "./eligibilityGate";
import { ITEM_TYPE_LABELS, ITEM_TYPE_ORDER, criticalityOf, displayCodeOf, itemTypeOf, requirementTypeChip } from "./itemTypes";

import type { CosmosNodeState } from "./theme";
import type { SourceKind } from "@/components/ui/SourceBadge";
import { parseSourceLabel } from "./provenance";

/** 아직 실행되지 않은 단계에 쓰는 공통 문구 — 가짜 수치 대신 이 문구를 쓴다. */
export const NOT_RUN_SUMMARY = "아직 안 함";

// ---------------------------------------------------------------------------
// 워크플로 단계
// ---------------------------------------------------------------------------

/**
 * 8단계 이름.
 *
 * 화면의 주표기는 **우리말**이다. 개발 용어(Eligibility Gate 같은)를 그대로 두면
 * 처음 보는 직원이 무슨 단계인지 알 수 없다. 영문은 `en` 에 보조표기로만 남긴다 —
 * 문서·코드와 대조할 때 필요하고, 지우면 오히려 추적이 어려워진다.
 */
export const WORKFLOW_STEPS = [
  { id: 1, key: "discover", label: STEP_NAMES[1], en: null },
  // 실제 공고에서는 키워드 규칙만 돈다. 의미 유사도 엔진은 미구현이므로
  // 단계 이름으로 "Semantic Matching"을 쓰지 않는다 (없는 기능을 있다고 말하지 않는다).
  { id: 2, key: "semantic", label: STEP_NAMES[2], en: "Bid Fit" },
  { id: 3, key: "eligibility", label: STEP_NAMES[3], en: "Eligibility Gate" },
  { id: 4, key: "rfp", label: STEP_NAMES[4], en: "RFP Matrix" },
  { id: 5, key: "evidence", label: STEP_NAMES[5], en: "Evidence Mapping" },
  { id: 6, key: "proposal", label: STEP_NAMES[6], en: "Proposal Draft" },
  { id: 7, key: "auditor", label: STEP_NAMES[7], en: "AI Auditor" },
  { id: 8, key: "review", label: STEP_NAMES[8], en: "Human Review" },
] as const;

export type WorkflowStage = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
export type StepKey = (typeof WORKFLOW_STEPS)[number]["key"];
export type StepStatus = "done" | "active" | "attention" | "failed" | "pending";

export interface WorkflowStepView {
  id: WorkflowStage;
  /**
   * 입찰 8단계의 키. 지원사업 그래프는 자기 7단계 키를 쓰므로 «타입만» 넓혀 둔다 —
   * 이 파일이 넣는 값은 여전히 StepKey 뿐이고, 넓힌 쪽은 읽는 곳이 아직 없다.
   */
  key: StepKey | SupportStepKey;
  label: string;
  status: StepStatus;
  summary: string;
}

export type ReviewDecision = "approved" | "hold" | null;

// ---------------------------------------------------------------------------
// 노드 / 연결선
// ---------------------------------------------------------------------------

export type CosmosNodeKind =
  | "notice"
  | "requirement"
  /** 요구사항 묶음 (「수행과업 15건」). 항목이 많을 때 개별 노드 대신 이것을 그린다. */
  | "requirement-group"
  | "evidence"
  | "proposal"
  | "audit"
  | "finding"
  /** 발견 묶음 (「제출서류 준비 필요 7건」). 같은 원인끼리 모은다. */
  | "finding-group";

export type CosmosLinkKind =
  /** 중앙 공고 → 요구사항 (AI가 공고에서 요구사항을 추출했다는 시각적 관계) */
  | "notice-requirement"
  /** 공고 → 요구사항 묶음, 묶음 → 펼친 요구사항 */
  | "notice-group"
  | "group-requirement"
  /** Auditor → 발견 묶음 */
  | "audit-group"
  | "requirement-evidence"
  | "requirement-proposal"
  | "evidence-proposal"
  | "audit-finding"
  | "finding-target";

export type CosmosLinkState =
  | "active"
  | "candidate"
  | "warning"
  | "neutral";

export interface CosmosNode {
  id: string;
  kind: CosmosNodeKind;
  label: string;
  /** 3D 라벨용 짧은 이름 (≤ 8자 권장) */
  short: string;
  state: CosmosNodeState;
  /** 이 단계 이상에서만 보인다 (분석 진행 애니메이션·발표 모드용) */
  stage: WorkflowStage;
  position: [number, number, number];
  position2d: [number, number];
  requirementId?: string;
  evidenceId?: string;
  findingId?: string;
  severity?: AuditFinding["severity"];
  /** 화면용 코드 (TSK-003 등). 저장 id는 requirementId */
  code?: string;
  /** 요구사항 노드의 항목 유형 (TASK / REQUIREMENT / …) */
  itemType?: ItemType;
  criticality?: Criticality;
  /** 미해결 BLOCKER 조건이 걸린 항목 */
  blocker?: boolean;
  // --- 묶음 노드 전용 ---------------------------------------------------
  /** 이 묶음에 들어 있는 건수 */
  groupCount?: number;
  /** 묶음 키 (요구사항은 ItemType, 발견은 backend 의 group_key) */
  groupKey?: string;
  /** 펼쳐져 있는가 */
  expanded?: boolean;
}

export interface CosmosLink {
  id: string;
  source: string;
  target: string;
  kind: CosmosLinkKind;
  state: CosmosLinkState;
  stage: WorkflowStage;
}

export const NOTICE_NODE_ID = "notice";
export const PROPOSAL_NODE_ID = "proposal";
export const AUDIT_NODE_ID = "audit";
export const requirementNodeId = (id: string) => `req:${id}`;
export const requirementGroupNodeId = (key: string) => `reqgroup:${key}`;

/** 심각도 순위. 낮을수록 급하다. 묶음의 대표 심각도를 고를 때 쓴다. */
export function severityRank(severity: Severity): number {
  return { critical: 0, high: 1, medium: 2, low: 3, info: 4 }[severity] ?? 5;
}

/**
 * 「그냥 넘기면 안 되는 발견」인가. critical 과 high 를 함께 센다.
 *
 * critical 은 2026-09-11 에 심각도를 5단계로 나누면서 생긴 등급인데, 집계·색·정렬이
 * 전부 `severity === "high"` 라는 옛 조건에 머물러 있어 **가장 위험한 발견만 화면에서 빠졌다**.
 * 판정을 한 곳에 모아 다시 갈리지 않게 한다.
 */
export function isSevere(f: { severity: Severity }): boolean {
  return f.severity === "critical" || f.severity === "high";
}

/**
 * 「끝난 단계」의 정의. 진행률과 레일의 「n/8」이 **반드시** 이 함수 하나를 써야 한다.
 *
 * 예전에는 레일이 done+attention 을, 진행률은 done+failed 를 세서 같은 화면에
 * 「7/8」과 「38%」가 나란히 떴다. 「확인 필요」는 완료가 아니고(볼 것이 남았다),
 * 「실패」는 완료다(실행했고 답이 나왔다 — 참가 불가라는 답도 답이다).
 */
export function isStepSettled(step: { status: StepStatus }): boolean {
  return step.status === "done" || step.status === "failed";
}

/**
 * 저장된 결정을 화면에 적을 때 쓰는 말. 「결정 NO_GO」 같은 영문 상수를 그대로 쓰지 않는다.
 * 비교식과 API 필드(DecisionStatus)는 그대로 두고 표기만 바꾼다.
 */
// 결정 표기는 `lib/scoreNames.ts` 하나만 쓴다. 예전에는 여기와 format.ts 두 벌이었고,
// 이 쪽만 「참여 결정 (GO)」처럼 영문을 병기하고 있었다 (0920 §4-B-1).

/** 묶음 순서를 모르는 옛 응답의 자리. 백엔드 auditor_service.DEFAULT_GROUP_RANK 와 같은 값이어야 한다. */
export const DEFAULT_FINDING_GROUP_RANK = 80;

/** 발견을 묶는 키. 백엔드가 준 group_key 를 그대로 쓰고, 옛 응답에는 유형으로 대체한다. */
export function findingGroupKeyOf(f: AuditFinding): string {
  return f.group_key || `type:${f.finding_type}`;
}

export const findingGroupNodeId = (key: string) => `findgroup:${key}`;

// ---------------------------------------------------------------------------
// 집계 모드 (CLUSTER_MODE)
// ---------------------------------------------------------------------------
//
// 요구사항 56건과 발견 39건을 전부 개별 노드로 그리면 노드 97개·연결선 133개가 된다.
// 실측으로 3D 가 붉은 구체 덩어리가 되고 라벨이 서로 겹쳐 아무것도 읽히지 않았다.
//
// **요구사항을 덜 추출해서 줄이는 것이 아니다.** 56건은 그대로 두고, 기본 화면에서만
// 유형별로 묶어 보여준다. 목록·2D·RFP Matrix 는 언제나 전체를 보여준다.

/** 이 개수부터 요구사항을 유형별로 묶는다. 24건 이하는 개별 노드를 그대로 쓴다. */
export const CLUSTER_REQUIREMENT_THRESHOLD = 25;
/** 이 개수부터 발견을 원인별로 묶는다. */
export const CLUSTER_FINDING_THRESHOLD = 10;
/** 묶음을 펼쳤을 때 한 번에 그리는 하위 노드 수. 나머지는 목록·상세에서 본다. */
export const MAX_EXPANDED_CHILDREN = 8;
/** 기본 화면에 동시에 보이는 주요 노드 상한. 넘으면 읽을 수 없다. */
export const MAX_PRIMARY_NODES = 18;
export const evidenceNodeId = (id: string) => `ev:${id}`;
export const findingNodeId = (id: string) => `finding:${id}`;

// ---------------------------------------------------------------------------
// 파생 뷰
// ---------------------------------------------------------------------------

export interface EvidenceLinkView extends EvidenceLink {
  document: EvidenceDocument;
}

export type RequirementDisplayStatus = "matched" | "partial" | "unmatched" | "check";

export interface RequirementView extends Requirement {
  nodeId: string;
  evidence: EvidenceLinkView[];
  sentences: ProposalSentence[];
  findings: AuditFinding[];
  /** 데모 Evidence 연결을 반영한 표시 상태 (backend status는 그대로 보존) */
  displayStatus: RequirementDisplayStatus;
  nodeState: CosmosNodeState;
}

export interface EvidenceView extends EvidenceDocument {
  nodeId: string;
  links: Array<EvidenceLink & { requirement: Requirement }>;
  findings: AuditFinding[];
  nodeState: CosmosNodeState;
}

export interface FindingView extends AuditFinding {
  nodeId: string;
  requirement: Requirement | null;
  evidence: EvidenceDocument | null;
  sentence: ProposalSentence | null;
  /** 경고 경로: audit → finding → 대상 노드 */
  pathNodeIds: string[];
  pathLinkIds: string[];
  /** 검사마다 바뀌는 AF-id 대신 같은 문제를 가리키는 안정 키 (backend finding_resolution_service와 같은 규칙) */
  resolutionKey: string;
  /** 담당자 해결/재오픈 기록 (없으면 null) */
  resolution: FindingResolution | null;
  /** 담당자가 해결로 전환했는지 — Auditor 판정을 바꾸지 않고 사람의 판단으로 덧붙인다 */
  resolved: boolean;
}

/**
 * 회사 수행근거 연결이 **어떤 상태인가** — 대시보드와 RFP 분석이 함께 쓰는 한 벌
 * (0920 §4-B-5 · ISSUE-078).
 *
 * RFP 분석은 이것을 `hasScenario`(= 합성 데모인가)로 판정하고 있었다. 그래서 실공고는
 * 근거 연결을 실제로 돌려 놓았어도 **언제나** 「매칭 미실행」이라고 적었고, 대시보드는
 * 같은 공고를 「회사자료 3종 · 4문장에 연결」이라고 적었다. 같은 순간 두 화면이 서로
 * 다른 말을 했다.
 */
/**
 * 수행근거 연결의 **상태 코드** (0922 §4-D-5 · ISSUE-090).
 *
 * 저장 파일에 남은 «문장»을 화면이 그대로 읽으면 안 된다. 가천대 피지컬 공고에서 KPI 는
 * 옛 결과의 「연결에 실패했습니다 … 키가 거부되었습니다」를 그대로 보여 주는데, 같은 화면의
 * 그래프 노드와 8단계 레일은 「회사 수행근거 연결 미실행」이라고 했다 — 한 화면이 두 가지
 * 말을 한 것이다. 상태를 코드로 한 번 판정하고 세 곳이 그것만 읽는다.
 */
export type EvidenceStatus =
  | "not_run" // 아직 안 돌렸다
  | "stale" // 돌렸지만 요구사항이 바뀌었다 — 이전 실행 결과다
  | "failed_key" // 돌렸는데 AI 검색 키가 거부됐다
  | "failed_credit" // 돌렸는데 크레딧이 소진됐다
  | "failed_other" // 돌렸는데 붙은 근거가 없다 (그 밖의 사유)
  | "mixed" // 실공고인데 합성 근거가 섞인 이전 결과 — 쓰지 않는다
  | "candidates_only" // 돌았고 후보 문단은 있지만 채택된 근거가 없다 (DTL 검증 R-2)
  | "off" // 회사 근거 연결(AI 검색)을 꺼 두었다 — 실패가 아니다 · 실적 원장 후보에서 사람이 고른다 (45차 H5)
  | "done"; // 연결됐다

/** 상태 코드 → 화면 세 곳이 **그대로 적는** 짧은 말. */
export const EVIDENCE_STATUS_LABELS: Record<EvidenceStatus, string> = {
  not_run: "아직 안 함",
  stale: "이전 실행 결과 — 다시 실행 필요",
  failed_key: "실패 — 키 거부",
  failed_credit: "실패 — 크레딧 소진",
  failed_other: "실패 — 붙은 근거 없음",
  mixed: "이전 결과 — 가상 예시 근거 섞임",
  candidates_only: "후보만 있음 — 채택된 근거 없음",
  off: "AI 검색 꺼 둠 — 원장 후보에서 고르기",
  done: "완료",
};

export interface EvidenceRunState {
  /** 상태 코드. **화면은 이것만 보고 글자를 고른다.** */
  status: EvidenceStatus;
  /** 상태 코드의 짧은 말. 세 화면이 같은 글자를 쓴다. */
  label: string;
  /** 근거 연결을 **실행한 적이 있는가.** 합성 데모이거나 제안서 결과가 있으면 참이다. */
  ran: boolean;
  /** 돌았는데 아무것도 붙지 않은 **사유**. 없으면 null — 「실패」와 「미실행」은 다르다. */
  failureNote: string | null;
  /** 제안서 문장이 실제로 회사 근거를 쓴 수. 후보 수가 아니다. */
  groundedCount: number;
  /** 후보 임계값을 넘은 회사자료 문단 수(`used_chunk_count` · 채택 안 된 것 포함). */
  candidateCount: number;
  /** 쓰인 회사자료 종 수. */
  documentCount: number;
  /** 합성 회사자료를 썼는가 (데모 시나리오 포함). */
  synthetic: boolean;
}

/**
 * 위 상태를 만든다. **화면은 이것만 보고 글자를 고른다.**
 *
 * 「연결됐다」의 기준은 `evidence_grounded_count`(제안서 문장이 실제로 쓴 수)다.
 * `used_chunk_count` 는 «후보 임계값을 넘은 매칭 전체»라 채택되지 않은 것까지 센다.
 */
export function evidenceRunState(graph: Pick<CosmosGraph, "source" | "hasScenario">): EvidenceRunState {
  const proposal = graph.source.analysis.proposal ?? null;
  const summary = proposal?.evidence_summary ?? null;
  const used = Boolean(summary?.real_evidence_used || summary?.synthetic_evidence_used);
  const note = typeof summary?.note === "string" ? summary.note.trim() : "";
  const grounded = proposal?.evidence_grounded_count ?? 0;
  // 실공고의 **예전 공개 결과**(이 회사 기준 분석이 없어 대신 읽은 것)는 이 회사가 돌린 것이 아니다 — 연결 전으로 본다.
  // 요구사항 정리표(app/rfp/evidenceView)와 같은 규칙이다 (RFP-03 · NEW-09 · 두 화면 말 한 벌).
  const real = graph.source.origin.kind !== "demo";
  // 실공고에 합성 근거가 섞인 결과(옛 공개 초안 인용 · 규칙 전 저장본)는 쓸 수 없는 이전 결과다 — 정리표가 먼저 보는 것과 같은 순서.
  const mixed = real && Boolean(summary?.synthetic_evidence_used);
  const legacy = real && proposal?.legacy_result === true;
  const ran = graph.hasScenario || (proposal !== null && !legacy);
  const failureNote = summary && !used && note && !legacy ? note : null;
  // 46차 H5 — 지금 AI 검색이 꺼져 있나는 서버 상태 값으로(45차 전 초안의 사유 「설정이 없어 … 건너뜁니다」 · 「키가 거부되었습니다」에는
  // 「꺼 두」 낱말이 없어 「실패」로 보였다). 값이 없는 옛 응답만 사유 글 낱말로 본다. 지원사업 5단계(evidenceEmpty)와 같은 규칙.
  const searchOff = summary?.ai_search_off ?? (failureNote !== null && /꺼 두/.test(failureNote));
  // **요구사항이 바뀌었으면 저장된 결과는 「이전 실행 결과」다.** 그 안의 사유 문장을
  // 지금 상태인 것처럼 보여 주면 담당자가 없는 문제를 고치러 간다 (ISSUE-090).
  const stale = Boolean(graph.source.analysis.readiness?.blockers.includes("stale_requirements"));

  const candidates = summary?.used_chunk_count ?? 0;

  let status: EvidenceStatus;
  if (mixed) status = "mixed";
  else if (!ran) status = "not_run";
  else if (stale) status = "stale";
  else if (graph.hasScenario || grounded > 0) status = "done";
  // 45차 H5 — AI 검색을 일부러 꺼 둔 것은 「실패 — 붙은 근거 없음」이 아니다(고장처럼 보였다) · 켜져 있는데 실패한 것만 실패
  else if (searchOff && summary !== null && !used) status = "off";
  // 돌았고 후보 문단도 찾았는데 채택이 0 — 「미실행」이 아니다(레일은 「후보 n문단 · 채택된 근거 없음」, KPI · 패널은
  // 「미실행」이라 했다 · R-2). 후보도 사유도 없으면 그대로 연결 전(요구사항 정리표 RFP-05 와 같은 규칙).
  else if (failureNote === null) status = candidates > 0 ? "candidates_only" : "not_run";
  else if (failureNote.includes("크레딧")) status = "failed_credit";
  else if (failureNote.includes("키")) status = "failed_key";
  else status = "failed_other";

  return {
    status,
    label:
      status === "done" && !graph.hasScenario
        ? `완료 ${grounded}건`
        : EVIDENCE_STATUS_LABELS[status],
    ran,
    failureNote,
    groundedCount: grounded,
    candidateCount: candidates,
    documentCount: summary?.used_document_count ?? 0,
    synthetic: graph.hasScenario || Boolean(summary?.synthetic_evidence_used),
  };
}

/** 회사 근거 연결 상태 한 줄 — 5단계 · 요구사항 상세 · 안내 · 30초 둘러보기가 같은 글(요구사항 정리표 evidenceView 와 같은 말 · DTL-03). */
export function evidenceRunSentence(run: EvidenceRunState): string {
  switch (run.status) {
    case "done":
      return `회사자료 ${run.documentCount}종 · 제안서 ${run.groundedCount}문장에 회사 근거를 연결했습니다. 요구사항별 연결은 저장되지 않아 항목마다 보이지 않습니다.`;
    case "stale":
      return "요구사항이 바뀌기 전의 근거 연결 결과입니다 — 제안서를 다시 만들어야 지금 요구사항과 맞습니다.";
    case "mixed":
      return "가상 예시 근거가 섞인 이전 결과입니다 — 이 회사 기준으로 제안서를 다시 만드세요.";
    case "not_run":
      return "회사 근거 연결을 아직 하지 않았습니다 — 제안서를 만들 때 함께 합니다. 근거가 없으면 「충족」으로 표시하지 않습니다.";
    case "off":
      return "회사 근거 연결(AI 검색)은 꺼 두었습니다 — 실패가 아닙니다. 실적 원장에서 분야 낱말로 맞춘 후보를 요구사항 정리표 행 상세에서 「채택」하면 다음에 만드는 초안부터 그 실적을 근거로 씁니다.";
    case "candidates_only":
      return `근거 연결은 실행했고 회사자료 후보 ${run.candidateCount}문단을 찾았지만, 채택 기준을 넘은 근거가 없어 제안서 문장에 쓰지 않았습니다 — 회사자료를 확인하세요.`;
    default:
      return `근거 연결은 실행했지만 붙은 근거가 없습니다 — ${run.failureNote ?? "사유 미확인"}`;
  }
}

/** 공고 출처. 실제 공고는 나라장터(실시간/캐시), 데모는 합성 공고다. */
export type NoticeOrigin =
  | { kind: "demo" }
  | { kind: "real"; source: ProcurementSource; fetchedAt: string | null };

export interface CosmosSource {
  notice: ProcurementNotice;
  origin: NoticeOrigin;
  /** RFP 파싱 전이면 null (실제 공고는 첨부 파싱이 아직 없다) */
  parse: RfpParseResult | null;
  /** 데모 시나리오 전용. 실제 공고는 null */
  scenario: DemoCosmosScenario | null;
  /** 실제 분석 API 결과. 실행하지 않은 단계는 null로 남긴다 (가짜 수치 금지) */
  analysis: CosmosAnalysis;
  /** 지원사업 그래프일 때만 채워진다. 입찰은 언제나 undefined */
  support?: SupportApplicationResult;
}

/**
 * 실제 backend 분석 결과.
 *
 * 각 항목은 해당 단계를 **실제로 실행했을 때만** 채워진다.
 * null이면 그 단계는 "미실행"이며, 데모 시나리오가 있을 때만 데모 값으로 대체한다.
 */
export interface CosmosAnalysis {
  /** POST /api/eligibility/evaluate */
  eligibility: EligibilityReport | null;
  /** GET·POST /api/proposal — 실제 생성된 핵심 섹션 */
  proposal: GeneratedProposalSection | null;
  /** POST /api/auditor/run — 실제 검사 결과 */
  audit: AuditRunResult | null;
  /** GET /api/conditions/{id} — Critical Condition 규칙 탐지 + 사람의 해결 기록 */
  conditions: CriticalConditionReport | null;
  /** GET /api/decision/{id} — 사람이 저장한 GO/HOLD/NO_GO (UNREVIEWED면 미결정) */
  decision: BidDecision | null;
  /**
   * 결정을 읽지 못한 사유 — null(「검토 전」)과 다르다. 있으면 판정 칸이 사유를 보이고 결정 단추를 잠근다
   * (못 읽은 채 「검토 전」으로 보이면 저장이 기존 결정을 확인 없이 덮었다 · 2.0.6).
   */
  decisionError?: string | null;
  /** GET /api/actions/{id} — Action Checklist */
  checklist: ActionChecklist | null;
  /** GET /api/capability/{id} — 개발 수행역량 판정 (개발 공고일 때 의미가 있다) */
  capability: CapabilityReport | null;
  /**
   * GET /api/auditor/{id}/readiness — 지금 초안이 어느 요구사항 집합 기준인가.
   *
   * null 이면 «확인하지 않았다»(옛 배포 스냅샷에는 이 경로가 없다).
   * 없는 것을 「최신」으로 읽지 않는다.
   */
  readiness: AuditReadiness | null;
}

/** 아무것도 실행하지 않은 초기 분석 상태. */
export const EMPTY_ANALYSIS: CosmosAnalysis = {
  capability: null,
  readiness: null,
  eligibility: null,
  proposal: null,
  audit: null,
  conditions: null,
  decision: null,
  checklist: null,
};

export interface CosmosGraph {
  source: CosmosSource;
  /** 증빙(Evidence Mapping) 데이터가 있는지. 현재는 데모 시나리오에만 있다. */
  hasScenario: boolean;
  /** RFP 요구사항이 추출되어 있는지 */
  hasRequirements: boolean;
  /** 참가자격 판정이 실행되었는지 (실판정 또는 데모 시나리오) */
  hasEligibility: boolean;
  /** 제안서 초안이 생성되었는지 */
  hasProposal: boolean;
  /** AI Auditor가 실행되었는지 */
  hasAudit: boolean;
  /** 화면에 표시할 참가자격 판정 목록 (실판정 우선, 없으면 데모) */
  eligibility: EligibilityResult[];
  /** 화면에 표시할 제안서 섹션 (실생성 우선, 없으면 데모). 없으면 null */
  proposal: ProposalSection | null;
  nodes: CosmosNode[];
  links: CosmosLink[];
  nodeById: Map<string, CosmosNode>;
  linksByNode: Map<string, CosmosLink[]>;
  neighbors: Map<string, Set<string>>;
  requirements: RequirementView[];
  requirementByNodeId: Map<string, RequirementView>;
  evidence: EvidenceView[];
  evidenceByNodeId: Map<string, EvidenceView>;
  findings: FindingView[];
  findingByNodeId: Map<string, FindingView>;
  /** 담당자 해결 처리 기록 전체 (현재 발견에 없는 키 = 재검사에서 사라진 항목) */
  resolutions: FindingResolution[];
  /**
   * 집계 모드. 항목이 많을 때 기본 3D 화면이 묶음을 그린다.
   *
   * **데이터를 줄이는 것이 아니다** — `requirements`·`findings` 는 언제나 전부 들어 있고
   * 목록·2D·RFP Matrix 가 그것을 쓴다. 줄이는 것은 3D 에 그리는 «노드»뿐이다.
   */
  cluster: {
    requirementsClustered: boolean;
    findingsClustered: boolean;
    expandedCategory: ItemType | null;
    /** 펼친 묶음에서 그리지 못하고 목록으로 넘긴 건수 */
    hiddenInExpanded: number;
    categories: Array<{
      key: ItemType;
      label: string;
      count: number;
      attention: number;
      blocker: boolean;
      expanded: boolean;
    }>;
    findingGroups: Array<{ key: string; label: string; total: number; open: number; severity: Severity; rank: number }>;
    /** 기본 화면에 실제로 그린 주요 노드 수 (상한 확인용) */
    primaryNodeCount: number;
  };
  /** partial — 점검이 「부분 반영」으로 본 수(점검 전 · 지원사업은 없음). 막대 · 문장이 같은 칸에서 어긋나지 않게 (DTL 검증 R-4). */
  coverage: { total: number; covered: number; partial?: number; missingRequirementIds: string[] };
  counts: {
    requirements: number;
    evidenceDocuments: number;
    selectedLinks: number;
    requirementsWithoutEvidence: number;
    sentences: number;
    sentencesNeedingReview: number;
    /** 발견 전체 (해결 처리 포함) */
    findings: number;
    /** 심각도 높음 전체 (참가 차단 critical 포함) */
    findingsHigh: number;
    /** 담당자가 아직 해결 처리하지 않은 발견 */
    findingsOpen: number;
    /** 담당자가 해결로 전환한 발견 */
    findingsResolved: number;
    /** 심각도 높음 중 미해결 (참가 차단 critical 포함) */
    findingsHighOpen: number;
    /** 참가 차단(critical) 전체 — 「높음」과 섞으면 참가 자체가 막힌다는 뜻이 흐려진다 */
    findingsBlocking: number;
    /** 참가 차단 중 미해결 */
    findingsBlockingOpen: number;
  };
  steps: WorkflowStepView[];
  /** 0~1. 단계 8(Human Review)은 결정이 내려져야 완료로 센다. */
  progress: number;
  reviewDecision: ReviewDecision;
}

/** 제안서 문장을 Auditor에 붙여넣을 초안 텍스트로 만든다 (문장당 한 줄). */
export function proposalDraftText(section: ProposalSection | null): string {
  if (!section) return "";
  return section.sentences.map((sentence) => sentence.text).join("\n");
}

// ---------------------------------------------------------------------------
// 레이아웃 상수 (3D 단위: 대략 1 = 노드 지름)
// ---------------------------------------------------------------------------

export const LAYOUT = {
  requirementRadius: 5.4,
  requirementY: 0,
  evidenceRadius: 9.2,
  evidenceY: -0.5,
  proposalY: 4.6,
  auditY: 8.4,
  findingRadius: 2.3,
  /** 2D(SVG) 단위: px */
  requirementRadius2d: 205,
  evidenceRadius2d: 345,
  proposalY2d: -470,
  auditY2d: -640,
  findingRadius2d: 110,
} as const;

export function ringPosition(
  index: number,
  count: number,
  radius: number,
  y: number,
  phase = -Math.PI / 2,
): [number, number, number] {
  const angle = phase + (index / Math.max(count, 1)) * Math.PI * 2;
  return [Math.cos(angle) * radius, y, Math.sin(angle) * radius];
}

export function ringPosition2d(
  index: number,
  count: number,
  radius: number,
  phase = -Math.PI / 2,
): [number, number] {
  const angle = phase + (index / Math.max(count, 1)) * Math.PI * 2;
  return [Math.cos(angle) * radius, Math.sin(angle) * radius];
}

// ---------------------------------------------------------------------------
// 상태 파생 규칙
// ---------------------------------------------------------------------------

function requirementDisplayStatus(
  req: Requirement,
  evidence: EvidenceLinkView[],
): RequirementDisplayStatus {
  // 담당자가 확정 · 정정한 항목은 분류 확인이 끝났다 — 요구사항 정리표(displayStatusOf)와 같은 규칙 (RFP-11 · 두 화면 말 한 벌).
  const reviewed = req.review_status === "confirmed" || req.review_status === "corrected";
  if (req.status === "check" && !reviewed) return "check";
  if (evidence.some((e) => e.selected)) return "matched";
  if (evidence.length > 0) return "partial";
  return "unmatched";
}

function requirementNodeState(
  status: RequirementDisplayStatus,
  sentences: ProposalSentence[],
  findings: AuditFinding[],
  hasScenario: boolean,
): CosmosNodeState {
  // 증빙 매핑을 실행하지 않았으면 "증빙 없음"이라고 단정하지 않는다 (RFP 원문 기준 상태로 둔다).
  if (!hasScenario) return status === "check" ? "check" : "neutral";
  if (findings.length > 0) return "warning";
  switch (status) {
    case "check":
      return "check";
    case "matched":
      return "ok";
    case "partial":
      return "partial";
    default:
      return sentences.some((s) => s.grounding_type === "RFP_GROUNDED")
        ? "neutral"
        : "missing";
  }
}

function evidenceNodeState(
  links: EvidenceLink[],
  findings: AuditFinding[],
): CosmosNodeState {
  if (findings.length > 0) return "warning";
  if (links.some((l) => l.selected)) return "ok";
  return links.length > 0 ? "partial" : "missing";
}

function findingTargetNodeId(f: AuditFinding): string {
  if (f.requirement_id) return requirementNodeId(f.requirement_id);
  if (f.evidence_id) return evidenceNodeId(f.evidence_id);
  return PROPOSAL_NODE_ID;
}

// ---------------------------------------------------------------------------
// 빌더
// ---------------------------------------------------------------------------

export function buildCosmosGraph(
  source: CosmosSource,
  options: {
    reviewDecision?: ReviewDecision;
    resolutions?: FindingResolution[];
    /** 펼쳐 볼 요구사항 유형. null 이면 집계 Overview 다. */
    expandedCategory?: ItemType | null;
  } = {},
): CosmosGraph {
  const { notice, parse, scenario, analysis } = source;
  const reviewDecision = options.reviewDecision ?? null;
  const resolutions = options.resolutions ?? [];
  const resolutionByKey = new Map(resolutions.map((r) => [r.key, r]));
  const isResolved = (f: AuditFinding) =>
    resolutionByKey.get(findingResolutionKey(f))?.status === "resolved";
  const isOpen = (f: AuditFinding) => !isResolved(f);

  // 실제 분석 결과가 있으면 그것을 쓰고, 없을 때만 데모 시나리오로 대체한다.
  // 둘 다 없는 단계는 "미실행"이며 노드 자체를 만들지 않는다 (가짜 수치 금지).
  const requirementsData = parse?.requirements ?? [];
  const evidenceDocuments = scenario?.evidence_documents ?? [];
  const evidenceLinkData = scenario?.evidence_links ?? [];
  const eligibility: EligibilityResult[] =
    analysis.eligibility?.results ?? scenario?.eligibility ?? [];
  const hasEligibility = analysis.eligibility !== null || scenario !== null;
  const proposalSection: ProposalSection | null =
    analysis.proposal ?? scenario?.proposal ?? null;
  const proposalSentences = proposalSection?.sentences ?? [];
  // 실제 검사를 돌렸으면 그 결과만 쓴다. 데모 발견 항목은 데모 초안에 대한 것이라
  // 실생성 초안과 섞으면 근거가 어긋난다 — 실제 제안서가 있으면 데모 발견은 쓰지 않는다.
  const auditRun = analysis.audit;
  const demoFindingsUsable = auditRun === null && analysis.proposal === null;
  const findingsAll: AuditFinding[] =
    auditRun?.findings ?? (demoFindingsUsable ? scenario?.audit.findings ?? [] : []);
  const hasProposal = proposalSection !== null;
  const hasAudit = auditRun !== null || (demoFindingsUsable && scenario !== null);
  const staleRequirements = Boolean(analysis.readiness?.blockers.includes("stale_requirements"));

  // BLOCKER 경로: 조건 보고서가 있으면 미해결 BLOCKER(사람이 CLEARED하면 빠진다), 없으면 항목의 criticality로 본다.
  const blockerReqIds = new Set<string>(
    analysis.conditions
      ? analysis.conditions.conditions
          .filter((c) => c.status === "BLOCKER" && c.requirement_id)
          .map((c) => c.requirement_id as string)
      : requirementsData.filter((r) => criticalityOf(r) === "blocker").map((r) => r.requirement_id),
  );

  const docById = new Map(evidenceDocuments.map((d) => [d.id, d]));
  const reqById = new Map(requirementsData.map((r) => [r.requirement_id, r]));
  const sentenceById = new Map(proposalSentences.map((s) => [s.id, s]));

  const linksByReq = new Map<string, EvidenceLinkView[]>();
  const linksByEv = new Map<string, Array<EvidenceLink & { requirement: Requirement }>>();
  for (const link of evidenceLinkData) {
    const document = docById.get(link.evidence_id);
    const requirement = reqById.get(link.requirement_id);
    if (!document || !requirement) continue;
    linksByReq.set(link.requirement_id, [
      ...(linksByReq.get(link.requirement_id) ?? []),
      { ...link, document },
    ]);
    linksByEv.set(link.evidence_id, [
      ...(linksByEv.get(link.evidence_id) ?? []),
      { ...link, requirement },
    ]);
  }

  const sentencesByReq = new Map<string, ProposalSentence[]>();
  for (const s of proposalSentences) {
    if (!s.requirement_id) continue;
    sentencesByReq.set(s.requirement_id, [
      ...(sentencesByReq.get(s.requirement_id) ?? []),
      s,
    ]);
  }

  const findingsByReq = new Map<string, AuditFinding[]>();
  const findingsByEv = new Map<string, AuditFinding[]>();
  for (const f of findingsAll) {
    if (f.requirement_id) {
      findingsByReq.set(f.requirement_id, [...(findingsByReq.get(f.requirement_id) ?? []), f]);
    }
    if (f.evidence_id) {
      findingsByEv.set(f.evidence_id, [...(findingsByEv.get(f.evidence_id) ?? []), f]);
    }
  }

  const nodes: CosmosNode[] = [];
  const links: CosmosLink[] = [];

  // 중앙: 공고
  nodes.push({
    id: NOTICE_NODE_ID,
    kind: "notice",
    label: notice.title,
    short: "입찰공고",
    state: "neutral",
    stage: 1,
    position: [0, 0, 0],
    position2d: [0, 0],
  });

  // 1궤도: 요구사항
  //
  // 항목이 많으면 개별 노드 대신 «유형별 묶음»을 그린다. 파생 뷰(requirements)는
  // 언제나 전부 만든다 — 목록·2D·RFP Matrix 가 그것을 쓰기 때문이다. 줄이는 것은
  // «그림»뿐이고 «데이터»가 아니다.
  const clusterRequirements = requirementsData.length >= CLUSTER_REQUIREMENT_THRESHOLD;
  const expandedCategory = clusterRequirements ? options.expandedCategory ?? null : null;
  const requirementGroupOrder: ItemType[] = ITEM_TYPE_ORDER.filter((type) =>
    requirementsData.some((req) => itemTypeOf(req) === type),
  );
  // 펼친 묶음에서 실제로 그릴 요구사항 (나머지는 상세 목록에서 본다).
  const expandedIds = new Set(
    expandedCategory
      ? requirementsData
          .filter((req) => itemTypeOf(req) === expandedCategory)
          .slice(0, MAX_EXPANDED_CHILDREN)
          .map((req) => req.requirement_id)
      : [],
  );

  const requirements: RequirementView[] = requirementsData.map((req, i, all) => {
    const evidence = linksByReq.get(req.requirement_id) ?? [];
    const sentences = sentencesByReq.get(req.requirement_id) ?? [];
    const findings = findingsByReq.get(req.requirement_id) ?? [];
    const displayStatus = requirementDisplayStatus(req, evidence);
    // 담당자가 해결 처리한 발견은 요구사항을 더 이상 "경고"로 물들이지 않는다.
    const baseState = requirementNodeState(displayStatus, sentences, findings.filter(isOpen), scenario !== null);
    // 미해결 BLOCKER 조건이 걸린 항목은 붉은 경로로 드러낸다 (참가 자체를 막는 조건).
    const blocked = blockerReqIds.has(req.requirement_id);
    const nodeState: CosmosNodeState = blocked ? "warning" : baseState;
    const nodeId = requirementNodeId(req.requirement_id);
    const type = itemTypeOf(req);
    const drawOwnNode = !clusterRequirements || expandedIds.has(req.requirement_id);
    if (drawOwnNode) {
      // 묶음 안에서는 묶음 옆에, 평소에는 궤도 위에 놓는다.
      const slot = clusterRequirements ? [...expandedIds].indexOf(req.requirement_id) : i;
      const slotCount = clusterRequirements ? expandedIds.size : all.length;
      const radius = clusterRequirements ? LAYOUT.requirementRadius * 1.55 : LAYOUT.requirementRadius;
      const radius2d = clusterRequirements ? LAYOUT.requirementRadius2d * 1.5 : LAYOUT.requirementRadius2d;
      nodes.push({
        id: nodeId,
        kind: "requirement",
        label: `${displayCodeOf(req)} ${req.title}`,
        short: req.title,
        state: nodeState,
        stage: 4,
        position: ringPosition(slot, slotCount, radius, LAYOUT.requirementY),
        position2d: ringPosition2d(slot, slotCount, radius2d),
        requirementId: req.requirement_id,
        code: displayCodeOf(req),
        itemType: type,
        criticality: criticalityOf(req),
        blocker: blocked,
      });
    }
    if (clusterRequirements) {
      // 묶여 있을 때는 공고 → 묶음 → (펼쳤다면) 항목 순으로 잇는다.
      if (drawOwnNode) {
        links.push({
          id: `link:group:${req.requirement_id}`,
          source: requirementGroupNodeId(type),
          target: nodeId,
          kind: "group-requirement",
          state: blocked ? "warning" : "neutral",
          stage: 4,
        });
      }
      return { ...req, nodeId, evidence, sentences, findings, displayStatus, nodeState };
    }
    links.push({
      id: `link:notice:${req.requirement_id}`,
      source: NOTICE_NODE_ID,
      target: nodeId,
      kind: "notice-requirement",
      state: blocked ? "warning" : "neutral",
      stage: 4,
    });
    return { ...req, nodeId, evidence, sentences, findings, displayStatus, nodeState };
  });

  // 요구사항 묶음 노드 — 「수행과업 15건」처럼 유형과 건수를 함께 읽는다.
  const requirementGroups = requirementGroupOrder.map((type) => {
    const members = requirements.filter((req) => itemTypeOf(req) === type);
    const open = members.filter((req) => req.findings.some(isOpen));
    const blocked = members.some((req) => blockerReqIds.has(req.requirement_id));
    return {
      key: type,
      label: ITEM_TYPE_LABELS[type],
      count: members.length,
      attention: open.length,
      blocker: blocked,
      expanded: expandedCategory === type,
      hidden: expandedCategory === type ? Math.max(0, members.length - MAX_EXPANDED_CHILDREN) : members.length,
    };
  });

  if (clusterRequirements) {
    requirementGroups.forEach((group, i, all) => {
      const nodeId = requirementGroupNodeId(group.key);
      nodes.push({
        id: nodeId,
        kind: "requirement-group",
        label: `${group.label} ${group.count}건`,
        /* 짧은 라벨은 **이름만** 이다 (prompt_04 §3-A-5). 건수는 상태 조각(`shortBadge`)이
           맡는다 — 예전에는 여기서도 건수를 붙여 3D 라벨이 「과업 17 17건」이 됐다.
           이름과 건수를 나눠 두면 이름이 길어 잘릴 때도 건수는 남는다. */
        short: group.label,
        // 색만으로 구분하지 않는다 — 상태·건수·아이콘이 라벨에 함께 들어간다.
        state: group.blocker ? "warning" : group.attention > 0 ? "check" : "neutral",
        stage: 4,
        position: ringPosition(i, all.length, LAYOUT.requirementRadius, LAYOUT.requirementY),
        position2d: ringPosition2d(i, all.length, LAYOUT.requirementRadius2d),
        itemType: group.key,
        groupCount: group.count,
        groupKey: group.key,
        expanded: group.expanded,
        blocker: group.blocker,
      });
      links.push({
        id: `link:notice:group:${group.key}`,
        source: NOTICE_NODE_ID,
        target: nodeId,
        kind: "notice-group",
        state: group.blocker ? "warning" : "neutral",
        stage: 4,
      });
    });
  }

  // 2궤도: 증빙 (데모 시나리오에만 있다)
  const evidence: EvidenceView[] = evidenceDocuments.map((doc, i, all) => {
    const evLinks = linksByEv.get(doc.id) ?? [];
    const findings = findingsByEv.get(doc.id) ?? [];
    const nodeState = evidenceNodeState(evLinks, findings.filter(isOpen));
    const nodeId = evidenceNodeId(doc.id);
    nodes.push({
      id: nodeId,
      kind: "evidence",
      label: doc.document_name,
      short: doc.doc_type,
      state: nodeState,
      stage: 5,
      position: ringPosition(i, all.length, LAYOUT.evidenceRadius, LAYOUT.evidenceY, -Math.PI / 2 + Math.PI / all.length),
      position2d: ringPosition2d(i, all.length, LAYOUT.evidenceRadius2d, -Math.PI / 2 + Math.PI / all.length),
      evidenceId: doc.id,
    });
    return { ...doc, nodeId, links: evLinks, findings, nodeState };
  });

  for (const link of evidenceLinkData) {
    if (!docById.has(link.evidence_id) || !reqById.has(link.requirement_id)) continue;
    links.push({
      id: `link:${link.requirement_id}:${link.evidence_id}`,
      source: requirementNodeId(link.requirement_id),
      target: evidenceNodeId(link.evidence_id),
      kind: "requirement-evidence",
      state: link.selected ? "active" : "candidate",
      stage: 5,
    });
  }

  // 제안서 (데모 시나리오에만 있다 — 실제 공고는 노드를 만들지 않는다)
  const needsReview = proposalSentences.filter((s) => s.needs_review).length;
  if (proposalSection) {
    nodes.push({
      id: PROPOSAL_NODE_ID,
      kind: "proposal",
      label: proposalSection.title,
      short: "제안서 초안",
      state: needsReview > 0 ? "check" : "ok",
      stage: 6,
      position: [0, LAYOUT.proposalY, 0],
      position2d: [0, LAYOUT.proposalY2d],
    });
  }
  const seenReqProposal = new Set<string>();
  const seenEvProposal = new Set<string>();
  for (const s of proposalSentences) {
    if (s.requirement_id && reqById.has(s.requirement_id) && !seenReqProposal.has(s.requirement_id)) {
      seenReqProposal.add(s.requirement_id);
      links.push({
        id: `link:${s.requirement_id}:proposal`,
        source: requirementNodeId(s.requirement_id),
        target: PROPOSAL_NODE_ID,
        kind: "requirement-proposal",
        state: s.needs_review ? "candidate" : "active",
        stage: 6,
      });
    }
    if (s.evidence_id && docById.has(s.evidence_id) && !seenEvProposal.has(s.evidence_id)) {
      seenEvProposal.add(s.evidence_id);
      links.push({
        id: `link:${s.evidence_id}:proposal`,
        source: evidenceNodeId(s.evidence_id),
        target: PROPOSAL_NODE_ID,
        kind: "evidence-proposal",
        state: "neutral",
        stage: 6,
      });
    }
  }

  // Auditor + 발견 항목 (검사를 실행했을 때만 만든다)
  if (hasAudit) {
    nodes.push({
      id: AUDIT_NODE_ID,
      kind: "audit",
      // 3D·2D 무대에 그대로 뜨는 이름이다. 화면의 다른 이름(7단계 「제출 전 누락 점검」)과
      // 같아야 담당자가 「이게 그거구나」를 다시 배우지 않는다 (ISSUE-061).
      label: "제출 전 누락 점검",
      short: "제출 전 점검",
      // 허브는 열린 발견 중 **높음 이상**이 있을 때만 빨강 — 모두 「높음 0」이면 호박(27차 §3-D-4). 발견 기호 색과 같은 규칙.
      state: findingsAll.some((f) => isOpen(f) && isSevere(f)) ? "warning" : findingsAll.some(isOpen) ? "check" : "ok",
      stage: 7,
      position: [0, LAYOUT.auditY, 0],
      position2d: [0, LAYOUT.auditY2d],
    });
    if (proposalSection) {
      links.push({
        id: "link:proposal:audit",
        source: PROPOSAL_NODE_ID,
        target: AUDIT_NODE_ID,
        kind: "audit-finding",
        state: "neutral",
        stage: 7,
      });
    }
  }

  // 발견 항목의 대상 노드가 실제로 존재할 때만 경고선을 잇는다
  // (제안서를 생성하지 않았거나 증빙 매핑을 돌리지 않았으면 그 노드는 없다).
  const existingNodeIds = new Set(nodes.map((n) => n.id));

  // 실공고는 발견이 수십 건 나올 수 있어 개수에 따라 고리를 넓힌다 (겹침 방지).
  const findingRadius = Math.max(LAYOUT.findingRadius, findingsAll.length * 0.22);
  const findingRadius2d = Math.max(LAYOUT.findingRadius2d, findingsAll.length * 11);

  // 발견이 많으면 원인별로 묶는다. 「REQ 번호 26개」를 늘어놓는 대신
  // 「제출서류 준비 필요 7건」처럼 담당자가 바로 읽을 수 있는 덩어리로 만든다.
  const clusterFindings = findingsAll.length >= CLUSTER_FINDING_THRESHOLD;

  const findings: FindingView[] = findingsAll.map((f, i, all) => {
    const nodeId = findingNodeId(f.id);
    const rawTargetId = findingTargetNodeId(f);
    const targetId = existingNodeIds.has(rawTargetId) ? rawTargetId : null;
    if (clusterFindings) {
      // 개별 노드를 그리지 않는다. 파생 뷰는 그대로 만들어 상세·목록이 전부 쓴다.
      const resolutionKeyOnly = findingResolutionKey(f);
      return {
        ...f,
        nodeId,
        requirement: f.requirement_id ? reqById.get(f.requirement_id) ?? null : null,
        evidence: f.evidence_id ? docById.get(f.evidence_id) ?? null : null,
        sentence: f.sentence_id ? sentenceById.get(f.sentence_id) ?? null : null,
        pathNodeIds: [AUDIT_NODE_ID, findingGroupNodeId(findingGroupKeyOf(f))],
        pathLinkIds: [`link:audit:group:${findingGroupKeyOf(f)}`],
        resolutionKey: resolutionKeyOnly,
        resolution: resolutionByKey.get(resolutionKeyOnly) ?? null,
        resolved: resolutionByKey.get(resolutionKeyOnly)?.status === "resolved",
      } as FindingView;
    }
    const hubLinkId = `link:audit:${f.id}`;
    const targetLinkId = `link:${f.id}:target`;
    const resolutionKey = findingResolutionKey(f);
    const resolution = resolutionByKey.get(resolutionKey) ?? null;
    const resolved = resolution?.status === "resolved";
    // 해결된 경로는 붉은 경고선 대신 시안 실선으로 남긴다 (탐지 기록은 지우지 않는다).
    // 선 색 = 발견 색 — 높음 미만 발견은 호박(확인이 필요한 연결)이다. 삼각형은 호박인데 선만 빨강이던 것(27차 §3-D-4).
    const pathState: CosmosLinkState = resolved ? "active" : isSevere(f) ? "warning" : "candidate";
    nodes.push({
      id: nodeId,
      kind: "finding",
      label: findingTypeLabel(f.finding_type),
      short: findingTypeLabel(f.finding_type),
      state: resolved ? "resolved" : isSevere(f) ? "warning" : "check",
      stage: 7,
      position: ringPosition(i, all.length, findingRadius, LAYOUT.auditY, Math.PI / 2),
      position2d: (() => {
        const [x, y] = ringPosition2d(i, all.length, findingRadius2d, Math.PI / 2);
        return [x, y + LAYOUT.auditY2d] as [number, number];
      })(),
      findingId: f.id,
      severity: f.severity,
    });
    links.push({
      id: hubLinkId,
      source: AUDIT_NODE_ID,
      target: nodeId,
      kind: "audit-finding",
      state: pathState,
      stage: 7,
    });
    if (targetId) {
      links.push({
        id: targetLinkId,
        source: nodeId,
        target: targetId,
        kind: "finding-target",
        state: pathState,
        stage: 7,
      });
    }
    return {
      ...f,
      nodeId,
      requirement: f.requirement_id ? reqById.get(f.requirement_id) ?? null : null,
      evidence: f.evidence_id ? docById.get(f.evidence_id) ?? null : null,
      sentence: f.sentence_id ? sentenceById.get(f.sentence_id) ?? null : null,
      pathNodeIds: targetId ? [AUDIT_NODE_ID, nodeId, targetId] : [AUDIT_NODE_ID, nodeId],
      pathLinkIds: targetId ? [hubLinkId, targetLinkId] : [hubLinkId],
      resolutionKey,
      resolution,
      resolved,
    };
  });

  // 발견 묶음 노드 — 「제출서류 준비 필요 7건」처럼 원인별로 모은다.
  // 심각도는 묶음 안에서 «가장 높은 것»을 쓴다. 참가를 막는 것 하나가
  // 보완 가능한 여섯 건에 묻히면 안 된다.
  const findingGroups = (() => {
    const order: string[] = [];
    const map = new Map<
      string,
      { key: string; label: string; total: number; open: number; severity: Severity; rank: number }
    >();
    for (const f of findings) {
      const key = findingGroupKeyOf(f);
      if (!map.has(key)) {
        order.push(key);
        map.set(key, {
          key,
          label: f.group_label || findingTypeLabel(f.finding_type),
          total: 0,
          open: 0,
          severity: "info",
          rank: DEFAULT_FINDING_GROUP_RANK,
        });
      }
      const group = map.get(key)!;
      group.total += 1;
      if (typeof f.group_rank === "number") group.rank = f.group_rank;
      if (!f.resolved) {
        group.open += 1;
        if (severityRank(f.severity) < severityRank(group.severity)) group.severity = f.severity;
      }
    }
    // 순서는 백엔드가 정한 rank 를 따른다 — 「참가 불가 위험」이 맨 위여야 한다.
    // rank 가 같으면(옛 저장본) 발견이 나온 순서를 그대로 지킨다.
    return order
      .map((key, index) => ({ group: map.get(key)!, index }))
      .sort((a, b) => a.group.rank - b.group.rank || a.index - b.index)
      .map(({ group }) => group);
  })();

  if (clusterFindings) {
    findingGroups.forEach((group, i, all) => {
      const nodeId = findingGroupNodeId(group.key);
      nodes.push({
        id: nodeId,
        kind: "finding-group",
        label: `${group.label} ${group.open}건`,
        // 이름만 (§3-A-5). 건수는 상태 조각이 맡는다.
        short: group.label,
        state: group.open === 0 ? "resolved" : isSevere({ severity: group.severity }) ? "warning" : "check",
        stage: 7,
        position: ringPosition(i, all.length, LAYOUT.findingRadius * 1.25, LAYOUT.auditY, Math.PI / 2),
        position2d: (() => {
          const [x, y] = ringPosition2d(i, all.length, LAYOUT.findingRadius2d * 1.3, Math.PI / 2);
          return [x, y + LAYOUT.auditY2d] as [number, number];
        })(),
        severity: group.severity,
        groupCount: group.open,
        groupKey: group.key,
      });
      links.push({
        id: `link:audit:group:${group.key}`,
        source: AUDIT_NODE_ID,
        target: nodeId,
        kind: "audit-group",
        state: group.open === 0 ? "active" : "warning",
        stage: 7,
      });
    });
  }

  // 인덱스
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const linksByNode = new Map<string, CosmosLink[]>();
  const neighbors = new Map<string, Set<string>>();
  for (const link of links) {
    for (const [a, b] of [
      [link.source, link.target],
      [link.target, link.source],
    ]) {
      linksByNode.set(a, [...(linksByNode.get(a) ?? []), link]);
      if (!neighbors.has(a)) neighbors.set(a, new Set());
      neighbors.get(a)!.add(b);
    }
  }

  // 요약 수치 (모두 데이터에서 계산)
  const coveredIds = new Set(
    proposalSentences.map((s) => s.requirement_id).filter((x): x is string => !!x),
  );
  // 제안서가 없으면 "미반영"이라고 단정하지 않는다 — 아직 실행되지 않은 단계다.
  // 실제 Auditor를 돌렸으면 그 커버리지(필수 요구사항 기준)를 그대로 쓴다.
  // 점검 전에도 **필수만** 센다 — 점검 뒤 분모(필수) · 제안서 문장 「필수 N건 중」과 한 칸에서 어긋났다 (DTL-13).
  // 점검 전 이름은 「필수 요구사항」이므로 정리표 「필수」와 같은 셈(`mandatoryCount` 규칙 — 참고 · 평가 뺌) · 외부 점검 UI c.
  // 점검 뒤에는 점검 분모(「점검 대상 요구사항」 · `coverageNoun`)를 쓴다.
  const mandatoryIds = requirementsData.filter((r) => requirementTypeChip(r).mandatory).map((r) => r.requirement_id);
  const missingRequirementIds = auditRun
    ? auditRun.coverage.missing_requirement_ids
    : hasProposal && !staleRequirements
      ? mandatoryIds.filter((id) => !coveredIds.has(id))
      : [];
  const counts = {
    requirements: requirementsData.length,
    evidenceDocuments: evidenceDocuments.length,
    selectedLinks: evidenceLinkData.filter((l) => l.selected).length,
    requirementsWithoutEvidence: requirements.filter((r) => r.evidence.length === 0).length,
    sentences: proposalSentences.length,
    sentencesNeedingReview: needsReview,
    findings: findingsAll.length,
    // 「높음」에는 critical 도 센다. 예전에는 severity === "high" 만 세서, 참가 자체를 막는
    // critical 발견이 집계에서 통째로 빠졌다 — 실측: 실공고 g2b-R26BK01690926-000 에서
    // 발견 141건 중 critical 16건이 「높음 미해결 0」과 나란히 떴다. 최종 승인 화면도 「없음」이라 답했다.
    findingsHigh: findingsAll.filter(isSevere).length,
    findingsOpen: findingsAll.filter(isOpen).length,
    findingsResolved: findingsAll.filter(isResolved).length,
    findingsHighOpen: findingsAll.filter((f) => isSevere(f) && isOpen(f)).length,
    // critical 만 따로도 센다 — 「높음」에 섞으면 «참가 자체가 막힌다»는 뜻이 흐려진다.
    findingsBlocking: findingsAll.filter((f) => f.severity === "critical").length,
    findingsBlockingOpen: findingsAll.filter((f) => f.severity === "critical" && isOpen(f)).length,
  };

  const steps = buildSteps(source, requirements, counts, reviewDecision, {
    hasEligibility,
    hasProposal,
    hasAudit,
    eligibility,
  });
  // 「확인 필요」는 완료가 아니다. 완료처럼 세면 2단계가 대기인데도 75%처럼 보인다.
  // 정의는 isStepSettled 하나뿐이다 — 레일(WorkflowRail)도 같은 함수를 쓴다.
  const completed = steps.filter(isStepSettled).length;

  return {
    source,
    hasScenario: scenario !== null,
    hasRequirements: requirementsData.length > 0,
    hasEligibility,
    hasProposal,
    hasAudit,
    eligibility,
    proposal: proposalSection,
    nodes,
    links,
    nodeById,
    linksByNode,
    neighbors,
    requirements,
    requirementByNodeId: new Map(requirements.map((r) => [r.nodeId, r])),
    evidence,
    evidenceByNodeId: new Map(evidence.map((e) => [e.nodeId, e])),
    findings,
    findingByNodeId: new Map(findings.map((f) => [f.nodeId, f])),
    resolutions,
    cluster: {
      requirementsClustered: clusterRequirements,
      findingsClustered: clusterFindings,
      expandedCategory,
      hiddenInExpanded: expandedCategory
        ? Math.max(0, requirements.filter((r) => itemTypeOf(r) === expandedCategory).length - MAX_EXPANDED_CHILDREN)
        : 0,
      categories: requirementGroups.map(({ key, label, count, attention, blocker, expanded }) => ({
        key,
        label,
        count,
        attention,
        blocker,
        expanded,
      })),
      findingGroups,
      primaryNodeCount: nodes.filter((n) => n.kind !== "requirement" || !clusterRequirements).length,
    },
    coverage: {
      total: auditRun
        ? auditRun.coverage.total
        : staleRequirements && analysis.proposal
          ? analysis.proposal.mandatory_total
          : mandatoryIds.length,
      covered: auditRun
        ? auditRun.coverage.covered
        : staleRequirements && analysis.proposal
          ? analysis.proposal.requirements_with_sentence
        : hasProposal
          ? mandatoryIds.length - missingRequirementIds.length
          : 0,
      partial: auditRun ? auditRun.coverage.partial : 0,
      missingRequirementIds,
    },
    counts,
    steps,
    progress: completed / WORKFLOW_STEPS.length,
    reviewDecision,
  };
}

/**
 * 상세 패널이 여는 노드 — 그림(`nodes`)에 없으면 파생 뷰에서 찾는다 (ISSUE-161 · DTL-01).
 *
 * 요구사항 25건 · 발견 10건 이상이면 지도는 묶음만 그려 원시 노드가 `nodeById` 에 없다. 그래도 목록 행
 * (7단계 발견 · 4단계 주의 항목 · 조건 「항목 보기」)은 그 id 로 고른다 — 예전에는 여기서 null 이 되어 상세 대신
 * 단계 개요가 다시 열렸다. 그림은 그대로 두고 상세만 파생 뷰를 본다(자리 값은 쓰이지 않는다).
 */
export function detailNodeOf(graph: CosmosGraph, id: string | null): CosmosNode | null {
  if (!id) return null;
  const drawn = graph.nodeById.get(id);
  if (drawn) return drawn;
  const place = { position: [0, 0, 0] as [number, number, number], position2d: [0, 0] as [number, number] };
  const req = graph.requirementByNodeId.get(id);
  if (req) {
    const code = displayCodeOf(req);
    return { id, kind: "requirement", label: `${code} ${req.title}`, short: req.title, state: req.nodeState, stage: 4, ...place, requirementId: req.requirement_id, code, itemType: itemTypeOf(req), criticality: criticalityOf(req) };
  }
  const finding = graph.findingByNodeId.get(id);
  if (finding) {
    const label = findingTypeLabel(finding.finding_type);
    return { id, kind: "finding", label, short: label, state: finding.resolved ? "resolved" : isSevere(finding) ? "warning" : "check", stage: 7, ...place, findingId: finding.id, severity: finding.severity };
  }
  return null;
}

function buildSteps(
  source: CosmosSource,
  requirements: RequirementView[],
  counts: CosmosGraph["counts"],
  reviewDecision: ReviewDecision,
  flags: {
    hasEligibility: boolean;
    hasProposal: boolean;
    hasAudit: boolean;
    eligibility: EligibilityResult[];
  },
): WorkflowStepView[] {
  const { notice, parse, scenario, analysis } = source;
  // 초안이 이전 요구사항 집합 기준이면 뒤 단계를 「미실행」이라고 쓰지 않는다 —
  // 실행하지 않은 것이 아니라 실행할 수 없는 상태다.
  const staleRequirements = Boolean(analysis.readiness?.blockers.includes("stale_requirements"));
  const matched = requirements.filter((r) => r.displayStatus === "matched").length;
  const evidenceAttention = requirements.some(
    (r) => r.displayStatus === "unmatched" || r.displayStatus === "check",
  );

  const rfpStep: { status: StepStatus; summary: string } =
    parse && parse.count > 0
      ? {
          status: "done",
          summary: `요구사항 ${parse.count}건 · ${parse.page_is_approximate ? "약 " : ""}${parse.page_count}쪽`,
        }
      : { status: "pending", summary: parse ? "요구사항 뽑기 필요" : "제안요청서 아직 안 읽음" };

  // 3단계: 상태는 판정(verdict)대로, 요약은 ③ 의 두 수(22차 §4-B — 「조항 확인 전 n · 공고 필드 확인 m」).
  // 정거장 캡션 · 레일 · 「다음 할 일」 머리가 이 요약을 쓰고, KPI 타일 둘째 줄과 같은 계산(gateCounts)이다.
  // 「가능 · 확인 필요 · 불가」 셈은 3단계 절 머리(체크리스트 위)에만 남긴다.
  const eligibilityStep: { status: StepStatus; summary: string } = (() => {
    const report = analysis.eligibility;
    if (report) {
      const view = eligibilityGateView(flags.eligibility, report.verdict);
      return {
        status: report.verdict === "PASS" ? "done" : report.verdict === "FAIL" ? "failed" : "attention",
        summary: view ? gateSummary(view) : ELIGIBILITY_LABELS[report.verdict],
      };
    }
    if (!flags.hasEligibility || flags.eligibility.length === 0) {
      return { status: "pending", summary: NOT_RUN_SUMMARY };
    }
    return {
      status: flags.eligibility.some((e) => e.status === "FAIL")
        ? "failed"
        : flags.eligibility.some((e) => e.status !== "PASS")
          ? "attention"
          : "done",
      summary: gateSummary(eligibilityGateView(flags.eligibility)!),
    };
  })();

  // 6단계: 제안서는 실제로 생성했을 때만 수치를 보여준다.
  const proposalStep: { status: StepStatus; summary: string } = staleRequirements && analysis.proposal
    ? {
        status: "attention",
        summary: `옛 판 ${analysis.proposal.requirements_with_sentence}/${analysis.proposal.mandatory_total} · 새로 만들기 필요`,
      }
    : flags.hasProposal
    ? {
        status: counts.sentencesNeedingReview > 0 ? "attention" : "done",
        summary: `문장 ${counts.sentences} · 확인할 것 ${counts.sentencesNeedingReview}`,
      }
    : { status: "pending", summary: NOT_RUN_SUMMARY };

  // 7단계: Auditor도 실행했을 때만. 0건은 "발견 없음"이지 "미실행"이 아니다.
  // 담당자가 전부 해결 처리했으면 완료로 보되, 발견 수는 그대로 적는다 (탐지 기록 보존).
  const auditorStep: { status: StepStatus; summary: string } = flags.hasAudit
    ? {
        status: counts.findingsOpen > 0 ? "attention" : "done",
        summary:
          counts.findings === 0
            ? "찾은 문제 없음"
            : counts.findingsOpen > 0
              ? // 「심각」은 탈락 위험을 포함한다 — 겹치는 두 수를 나란히 두지 않는다(31차 R30-30).
                `안 고친 문제 ${counts.findingsOpen} · 그중 ${seriousText(counts.findingsHighOpen, counts.findingsBlockingOpen)}${
                  counts.findingsResolved > 0 ? ` · 해결 ${counts.findingsResolved}` : ""
                }`
              : `찾은 문제 ${counts.findings}건 · 모두 해결`,
      }
    : staleRequirements
      ? {
          // 「미실행」이 아니다 — 돌릴 수 없는 상태다. 그 사실을 그대로 적는다.
          status: "attention",
          summary: "요구사항이 바뀌어 점검을 하지 않았습니다 — 제안서를 새로 만드세요",
        }
      : { status: "pending", summary: NOT_RUN_SUMMARY };

  // 8단계: 저장된 GO/HOLD/NO_GO 결정이 **먼저**다. 그다음이 화면의 검토 승인/보류.
  //
  // 예전에는 순서가 반대였다. 그래서 서버에 NO_GO 가 저장돼 있어도 화면에서 「검토 승인」을
  // 눌러 두면 8단계가 「제출 승인」이 되어, 사람이 사유와 함께 저장한 포기 결정을 가렸다.
  // 저장된 것이 사실이고 화면 토글은 아직 저장 전일 수 있다.
  const decision = analysis.decision;
  // 결정을 읽지 못했으면 「미결정」이라 단정하지 않는다 — 결정 칸은 잠겼는데 8단계는 「결정하세요」였다(2.0.6 통합 검토).
  const reviewStep: { status: StepStatus; summary: string } = analysis.decisionError
    ? { status: "attention", summary: DECISION_READ_FAILED }
    : decision && decision.status !== "UNREVIEWED"
      ? {
          status: decision.status === "NO_GO" ? "failed" : decision.status === "HOLD" ? "attention" : "done",
          // 폴백에도 저장 값을 그대로 쓰지 않는다 — 「결정 GO」가 화면에 새던 자리다.
          summary: labelOf(DECISION_LABELS, decision.status),
        }
      : reviewDecision
        ? // 「보류」만 적으면 참여 결정의 「보류」와 같은 말이다 — 단추 이름 「다시 검토」 그대로 (DTL 검증 R-3).
          { status: "done", summary: reviewDecision === "approved" ? REVIEW_STATUS_LABELS.approved : "다시 검토" }
        : flags.hasAudit
        ? { status: "active", summary: UNDECIDED }
        : staleRequirements
          ? {
              // 앞 단계가 준비되지 않았다. 「진행 중」이 아니라 «차단됨»이다.
              status: "pending",
              summary: "앞 단계가 막혀 검토할 수 없습니다 — 제안서를 최신 요구사항으로 갱신하세요",
            }
          : {
            // 검토할 결과가 아직 없다. 앞 단계가 끝나지도 않았는데 「진행 중」이라고 쓰면
            // 사람이 무언가 하고 있다는 뜻이 되어, 8단계 레일과 요약 카드가 서로 다른 말을 한다.
            status: "pending",
            summary: flags.hasProposal ? "제출 전 점검 후 검토" : "제안서 초안 후 검토",
          };

  const semanticStep: { status: StepStatus; summary: string } = scenario
    ? { status: "done", summary: `적합도 ${scenario.semantic_match.label}` } // 출처는 ◇ 칩이 말한다 (R27U-MSC-09)
    : {
        status: "pending",
        summary: notice.candidate
          ? `낱말 관련도 ${CANDIDATE_TIER_LABELS[notice.candidate.tier] ?? notice.candidate.tier} (AI 비교는 안 씀)`
          : NOT_RUN_SUMMARY,
      };

  // 5단계(Evidence Mapping)는 아직 데모 시나리오에만 있다.
  /**
   * 회사 수행근거 연결.
   *
   * 예전에는 합성 데모 시나리오가 있을 때만 「실행됨」으로 봤다. 그런데 실공고에서도
   * 제안서를 만들 때 근거 검색이 함께 돈다 — 그 결과가 proposal.evidence_summary 에 있다.
   * 실제로 회사자료 42문단을 검색해 3종·4문단을 연결해 놓고도 화면은 「미실행」이라고 말했다.
   */
  /**
   * 상태는 KPI · 5단계 패널과 **같은** `evidenceRunState` 하나가 정한다 (DTL 검증 R-1 · R-2). 예전에는 여기서
   * 따로 세서 실공고의 합성 근거 섞인 옛 결과에 ✓ 「1문장에 연결 (합성)」을, 후보만 있는 결과에 「후보 3문단」을
   * 적는 동안 KPI · 패널은 「이전 결과 — 합성 근거 섞임」 · 「미실행」이라 했다.
   *
   * 「연결됐다」의 기준은 **제안서 문장이 실제로 회사 근거를 쓴 수**다 — used_chunk_count(후보 전체)로 ✓ 를
   * 띄우면 채택 0건인 공고도 끝난 것처럼 읽힌다. 서버 사유(note)는 그대로 쓴다 — 일반 문구로 덮으면 담당자가
   * 무엇을 해야 하는지 알 수 없다.
   */
  const run = evidenceRunState({ source, hasScenario: scenario !== null });
  const evidenceStep: { status: StepStatus; summary: string } = scenario
    ? {
        status: evidenceAttention ? "attention" : "done",
        summary: `${matched}/${counts.requirements} 연결`,
      }
    : run.status === "not_run"
      ? { status: "pending", summary: NOT_RUN_SUMMARY }
      : run.status === "done"
        ? {
            status: "done",
            summary: `회사자료 ${run.documentCount}종 · ${run.groundedCount}문장에 연결${run.synthetic ? " (가상 예시)" : ""}`,
          }
        : {
            status: "attention",
            summary:
              run.status === "stale"
                ? `${EVIDENCE_STATUS_LABELS.stale} (요구사항이 바뀌었습니다)`
                : run.status === "candidates_only"
                  ? `후보 ${run.candidateCount}문단 · 채택된 근거 없음 — 회사자료 확인 필요`
                  : run.status === "off"
                    ? EVIDENCE_STATUS_LABELS.off
                    : run.failureNote
                      ? `연결 실패 — ${run.failureNote}`
                      : run.label,
          };

  const statusByKey: Record<StepKey, { status: StepStatus; summary: string }> = {
    discover: { status: "done", summary: notice.agency },
    semantic: semanticStep,
    eligibility: eligibilityStep,
    rfp: rfpStep,
    evidence: evidenceStep,
    proposal: proposalStep,
    auditor: auditorStep,
    review: reviewStep,
  };

  /*
   * 저장된 결과에는 **언제 돌린 것인지**를 함께 적는다 (0923 §3-3 · ISSUE-093).
   * 문구는 `runStamp` 한 곳에서만 만든다 — KPI·노드 상세·이 레일이 같은 말을 해야 한다.
   */
  const stamped: Partial<Record<StepKey, RunStampKey>> = {
    evidence: "evidence",
    auditor: "audit",
  };

  return WORKFLOW_STEPS.map((s) => {
    const view = { id: s.id, key: s.key, label: s.label, ...statusByKey[s.key] };
    const key = stamped[s.key];
    return key ? { ...view, summary: withRunStamp(view.summary, runStamp(analysis, key)) } : view;
  });
}

// ---------------------------------------------------------------------------
// 조회 헬퍼
// ---------------------------------------------------------------------------

/** FNV-1a 32bit 해시(8자리 hex). backend finding_resolution_service.fnv1a32 와 같은 결과여야 한다. */
export function fnv1a32(text: string): string {
  let value = 0x811c9dc5;
  const bytes = new TextEncoder().encode(text);
  for (const byte of bytes) {
    value ^= byte;
    value = Math.imul(value, 0x01000193) >>> 0;
  }
  return value.toString(16).padStart(8, "0");
}

/**
 * 발견 항목의 안정 키. AF-id는 검사마다 새로 매겨지므로 "같은 문제"를 가리키는 키를 따로 만든다.
 * 우선순위: 요구사항 id → 증빙 id → 초안 문장 fingerprint → 초안 전체.
 * backend `finding_resolution_service.resolution_key` 와 반드시 같은 규칙을 쓴다.
 */
export function findingResolutionKey(f: AuditFinding): string {
  // 서버가 원문으로 만든 키가 있으면 그것 — 응답 글은 새 말로 바뀌어 여기서 다시 만들면 저장된 해결 기록과 어긋난다(33차 R32-12)
  if (f.resolution_key) return f.resolution_key;
  if (f.requirement_id) return `${f.finding_type}:req:${f.requirement_id}`;
  if (f.evidence_id) return `${f.finding_type}:ev:${f.evidence_id}`;
  if (f.proposal_text) {
    const normalized = f.proposal_text.replace(/\s+/g, " ").trim().toLowerCase();
    return `${f.finding_type}:text:${fnv1a32(normalized)}`;
  }
  return `${f.finding_type}:draft:all`;
}

export function findingTypeLabel(type: AuditFinding["finding_type"]): string {
  switch (type) {
    case "missing_requirement":
      return "요구사항 누락";
    case "number_mismatch":
      return "수치 불일치";
    case "unsupported_claim":
      return "근거 없는 주장";
    case "unchecked_condition":
      return "미확인 조건";
    case "missing_document":
      return "제출서류 누락";
    case "blind_identity":
      return "평가본 식별 정보";
  }
}

export function isVisible(item: { stage: WorkflowStage }, stage: WorkflowStage): boolean {
  return item.stage <= stage;
}

/** 시각 계층: 1 핵심 Core / 2 주요 결과(제안서·Auditor) / 3 증빙·발견·상태 있는 요구사항 / 4 그 외 요구사항 */
export type ImportanceLevel = 1 | 2 | 3 | 4;

export function nodeImportance(node: CosmosNode): ImportanceLevel {
  switch (node.kind) {
    case "notice":
      return 1;
    case "proposal":
    case "audit":
      return 2;
    case "evidence":
    case "finding":
      return 3;
    // 묶음은 기본 화면의 주인공이다 — 개별 항목보다 위로 둔다.
    case "requirement-group":
    case "finding-group":
      return 2;
    case "requirement":
      return node.state === "neutral" || node.state === "missing" ? 4 : 3;
  }
}

/** 위험 노드 툴팁용 한 줄 설명 — 원문 데이터만 조합한다. */
export function findingWhy(f: AuditFinding): string {
  const page = f.source_page ? `제안요청서 ${f.source_page}쪽` : null;
  switch (f.finding_type) {
    case "number_mismatch":
      return `${page ?? "제안요청서"} 원문과 초안의 수치가 다릅니다.`;
    case "missing_requirement":
      return `${page ?? "제안요청서"} 필수 요구사항에 대응하는 초안 문장이 없습니다.`;
    case "unsupported_claim":
      return "근거 자료 없이 수치·성과를 단정한 표현입니다.";
    case "unchecked_condition":
      return `${page ?? "제안요청서"} 조건을 근거로 확정할 수 없습니다 — 직접 확인하세요.`;
    case "missing_document":
      return `${page ?? "제안요청서"} 필수 제출서류가 초안 목록에서 빠졌습니다.`;
    case "blind_identity":
      return "평가본에 회사를 알아볼 수 있는 정보가 남았습니다.";
  }
}

/** 노드와 직접 연결된 노드·연결선 (hover/선택 강조용). 발견 노드는 경고 경로 전체를 포함한다. */
export function relatedIds(
  graph: CosmosGraph,
  nodeId: string | null,
): { nodeIds: Set<string>; linkIds: Set<string> } {
  const nodeIds = new Set<string>();
  const linkIds = new Set<string>();
  if (!nodeId) return { nodeIds, linkIds };
  nodeIds.add(nodeId);
  for (const link of graph.linksByNode.get(nodeId) ?? []) {
    linkIds.add(link.id);
    nodeIds.add(link.source);
    nodeIds.add(link.target);
  }
  const finding = graph.findingByNodeId.get(nodeId);
  if (finding) {
    finding.pathNodeIds.forEach((id) => nodeIds.add(id));
    finding.pathLinkIds.forEach((id) => linkIds.add(id));
  }
  if (nodeId === AUDIT_NODE_ID) {
    for (const f of graph.findings) {
      f.pathNodeIds.forEach((id) => nodeIds.add(id));
      f.pathLinkIds.forEach((id) => linkIds.add(id));
    }
  }
  return { nodeIds, linkIds };
}

/** 데이터 소스 표기 — UI에서 항상 노출한다. */
/**
 * 출처 배지 한 줄. `kind` 는 출처 배지 모양(● ◐ ⚑ ◇ ✓ ▣ ○)이다 — 상단 선택기 · KPI 칩(provenance)과 같은 규칙으로 고른다
 * (DSH-17 · 예전에는 하단 줄만 tone 을 ● 실데이터로 바꿔 캐시 · 시연용 고정 · 합성 파싱도 ● 로 보였다).
 * `tone` 은 옛 호출부(상세 패널)를 위해 남긴다.
 */
export interface SourceBadgeLine {
  label: string;
  tone: "sample" | "real" | "demo";
  kind: SourceKind;
}

export function sourceBadges(graph: CosmosGraph): SourceBadgeLine[] {
  const { origin, parse, analysis, notice } = graph.source;

  // 6·7단계 배지: 실제 API 결과 / 합성 데모 / 미실행을 절대 섞지 않는다. 규칙만 돌았으면 ▣ (✓ 는 AI 분석).
  const analysisBadge: SourceBadgeLine = analysis.audit
    ? { label: `제출 전 점검: ${analysis.audit.llm_used ? "규칙 + AI 점검" : "규칙 점검"}`, tone: "real", kind: analysis.audit.llm_used ? "analysis" : "rule" }
    : analysis.proposal
      ? {
          label: `제안서: ${GENERATION_METHOD_LABELS[analysis.proposal.generation_method]} · 제출 전 누락 점검 아직 안 함`,
          tone: "real",
          kind: analysis.proposal.generation_method === "LLM" ? "analysis" : "rule",
        }
      : graph.hasScenario
        ? { label: `근거·제안서·제출 전 점검: ${SYNTHETIC_NOTICE}`, tone: "demo", kind: "demo" }
        : { label: `근거·제안서·제출 전 점검: ${NOT_RUN_SUMMARY}`, tone: "sample", kind: "not_run" };

  const eligibilityBadge: SourceBadgeLine = analysis.eligibility
    ? {
        // verdict 는 PASS/CHECK/FAIL 이다. 화면에 원문 그대로 찍으면 「입찰 참가 가능 여부」
        // 바로 옆에 `CHECK` 가 붙는다 (ISSUE-016). 사전을 거친다.
        label: `참가 판정: ${ELIGIBILITY_LABELS[analysis.eligibility.verdict] ?? analysis.eligibility.verdict} (${analysis.eligibility.llm_used ? "정해 둔 규칙 + AI로 판정" : "정해 둔 규칙으로 판정"})`,
        tone: "real",
        kind: analysis.eligibility.llm_used ? "analysis" : "rule",
      }
    : graph.hasScenario
      ? { label: `참가 판정: ${SYNTHETIC_NOTICE}`, tone: "demo", kind: "demo" }
      : { label: "참가 판정: 아직 안 함", tone: "sample", kind: "not_run" };

  if (origin.kind === "demo") {
    return [
      { label: `공고: ${SYNTHETIC_NOTICE}`, tone: "sample", kind: "demo" },
      parse
        ? { label: `요구사항: ${parseSourceLabel(graph)}`, tone: "real", kind: "demo" }
        : { label: "요구사항: 아직 안 읽음", tone: "sample", kind: "not_run" },
      eligibilityBadge,
      analysisBadge,
    ];
  }

  return [
    notice.pinned
      ? { label: "공고: 예시 공고(마감)", tone: "real", kind: "pinned" }
      : origin.source === "g2b"
        ? { label: "공고: 실제 나라장터 공고", tone: "real", kind: "g2b" }
        : { label: "공고: 나라장터 저장본", tone: "real", kind: "cached" },
    parse
      ? {
          label: `요구사항: ${parseSourceLabel(graph)}${parse.page_is_approximate ? " · 쪽 번호는 대략" : ""}`,
          tone: "real",
          kind: "computed",
        }
      : { label: "요구사항: 제안요청서 아직 안 읽음", tone: "sample", kind: "not_run" },
    eligibilityBadge,
    analysisBadge,
  ];
}

// ---------------------------------------------------------------------------
// Focus Mode — 선택 노드 주변의 핵심 관계만 순차적으로 강조한다
// ---------------------------------------------------------------------------

export interface FocusSet {
  nodeIds: Set<string>;
  linkIds: Set<string>;
  /** 링크별 강조 순서(0부터). 선택 노드에서 가까운 관계가 먼저 켜진다 (근거 → 제안서 → Auditor). */
  linkOrder: Map<string, number>;
  /** 상한 때문에 강조에서 빠진 직접 이웃 수 */
  omitted: number;
}

export const EMPTY_FOCUS: FocusSet = {
  nodeIds: new Set(),
  linkIds: new Set(),
  linkOrder: new Map(),
  omitted: 0,
};

/** 허브 노드(공고·제안서)를 골랐을 때 우선 강조할 직접 이웃 수. */
export const FOCUS_NEIGHBOR_LIMIT = 7;

/** 낮을수록 먼저 강조한다 — 위험·확인 필요·증빙 없음 순. 해결된 발견은 뒤로 민다. */
function focusPriority(graph: CosmosGraph, node: CosmosNode): number {
  if (node.kind === "finding") {
    if (node.state === "resolved") return 3;
    return node.severity && isSevere({ severity: node.severity }) ? 0 : 1;
  }
  switch (node.state) {
    case "warning":
      return 0;
    case "check":
      return 1;
    case "missing":
      return 2;
    case "ok":
      return 3;
    case "partial":
      return 4;
    default:
      return node.kind === "requirement" && (graph.requirementByNodeId.get(node.id)?.requirement_type === "mandatory")
        ? 5
        : 6;
  }
}

/** 선택 노드 기준으로 이 링크가 몇 번째 단계에서 켜지는지 (0: 근거, 1: 제안서, 2: Auditor 경로). */
function focusLinkOrder(selected: CosmosNode, link: CosmosLink): number {
  switch (link.kind) {
    case "notice-requirement":
      return 0;
    case "requirement-evidence":
      return 0;
    case "requirement-proposal":
    case "evidence-proposal":
      return selected.kind === "proposal" ? 0 : 1;
    case "audit-finding":
      return selected.kind === "audit" || selected.kind === "finding" ? 0 : 2;
    case "finding-target":
      return selected.kind === "audit" ? 1 : selected.kind === "finding" ? 1 : 2;
    case "notice-group":
    case "group-requirement":
      return 0;
    case "audit-group":
      return selected.kind === "audit" ? 0 : 2;
  }
}

/**
 * 선택 노드와 직접 연결된 핵심 노드·연결선. 직접 이웃이 limit를 넘는 허브(공고·제안서)는
 * 위험·확인 필요 순으로 상위 limit개만 남기고 나머지는 omitted로 센다.
 * 발견 노드는 경고 경로(audit → finding → 대상) 전체를, Auditor는 모든 발견 경로를 포함한다.
 */
export function focusIds(
  graph: CosmosGraph,
  nodeId: string | null,
  limit: number = FOCUS_NEIGHBOR_LIMIT,
): FocusSet {
  if (!nodeId) return EMPTY_FOCUS;
  const selected = graph.nodeById.get(nodeId);
  if (!selected) return EMPTY_FOCUS;

  const nodeIds = new Set<string>([nodeId]);
  const linkIds = new Set<string>();
  const linkOrder = new Map<string, number>();

  const candidates: Array<{ link: CosmosLink; other: CosmosNode; priority: number }> = [];
  for (const link of graph.linksByNode.get(nodeId) ?? []) {
    const otherId = link.source === nodeId ? link.target : link.source;
    const other = graph.nodeById.get(otherId);
    if (!other) continue;
    candidates.push({ link, other, priority: focusPriority(graph, other) });
  }
  candidates.sort((a, b) => a.priority - b.priority || focusLinkOrder(selected, a.link) - focusLinkOrder(selected, b.link));

  const isHub = selected.kind === "notice" || selected.kind === "proposal";
  const keep = isHub ? candidates.slice(0, limit) : candidates;
  for (const { link, other } of keep) {
    nodeIds.add(other.id);
    linkIds.add(link.id);
    linkOrder.set(link.id, focusLinkOrder(selected, link));
  }

  const addPath = (finding: FindingView) => {
    finding.pathNodeIds.forEach((id) => nodeIds.add(id));
    finding.pathLinkIds.forEach((id, index) => {
      linkIds.add(id);
      const base = selected.kind === "audit" || selected.kind === "finding" ? 0 : 2;
      linkOrder.set(id, Math.max(linkOrder.get(id) ?? 0, base + index));
    });
  };

  const finding = graph.findingByNodeId.get(nodeId);
  if (finding) addPath(finding);
  if (nodeId === AUDIT_NODE_ID) graph.findings.forEach(addPath);
  // 요구사항·증빙을 골랐으면 그 노드를 가리키는 Auditor 경로도 끝까지 잇는다 (근거 → 제안서 → 경고 순).
  if (selected.kind === "requirement" || selected.kind === "evidence") {
    for (const f of graph.findings) {
      if (f.pathNodeIds[f.pathNodeIds.length - 1] === nodeId) addPath(f);
    }
  }

  return { nodeIds, linkIds, linkOrder, omitted: Math.max(0, candidates.length - keep.length) };
}

/**
 * 기본 대표 경로 — 아무것도 고르지 않았을 때 3D가 처음 보여주는 한 줄기.
 * 공고 → (BLOCKER 조건이 걸린 항목 › 누락 발견 항목 › 증빙 있는 항목 › 첫 항목) → 그 항목의 증빙 → 제안서 → Auditor 경고.
 * 값은 전부 그래프에서 고른다. 없는 단계는 잇지 않는다.
 */
export function representativeFocus(graph: CosmosGraph): FocusSet {
  if (graph.requirements.length === 0) return EMPTY_FOCUS;
  const byId = new Map(graph.requirements.map((r) => [r.requirement_id, r]));
  const missing = graph.findings.find((f) => f.finding_type === "missing_requirement" && !f.resolved && f.requirement_id);
  const pick =
    graph.requirements.find((r) => graph.nodeById.get(r.nodeId)?.blocker) ??
    (missing?.requirement_id ? byId.get(missing.requirement_id) : undefined) ??
    graph.requirements.find((r) => r.findings.length > 0) ??
    graph.requirements.find((r) => r.evidence.length > 0) ??
    graph.requirements[0];
  const linkExists = new Set(graph.links.map((l) => l.id));
  const nodeIds = new Set<string>([NOTICE_NODE_ID, pick.nodeId]);
  const linkIds = new Set<string>();
  const linkOrder = new Map<string, number>();
  const add = (linkId: string, order: number) => {
    if (!linkExists.has(linkId)) return;
    linkIds.add(linkId);
    linkOrder.set(linkId, order);
  };
  add(`link:notice:${pick.requirement_id}`, 0);
  for (const ev of pick.evidence.slice(0, 3)) {
    nodeIds.add(evidenceNodeId(ev.evidence_id));
    add(`link:${pick.requirement_id}:${ev.evidence_id}`, 0);
  }
  if (graph.hasProposal && linkExists.has(`link:${pick.requirement_id}:proposal`)) {
    nodeIds.add(PROPOSAL_NODE_ID);
    add(`link:${pick.requirement_id}:proposal`, 1);
    if (graph.hasAudit) {
      nodeIds.add(AUDIT_NODE_ID);
      add("link:proposal:audit", 2);
    }
  }
  for (const f of graph.findings) {
    if (f.requirement_id !== pick.requirement_id) continue;
    f.pathNodeIds.forEach((id) => nodeIds.add(id));
    f.pathLinkIds.forEach((id, index) => add(id, 2 + index));
  }
  return { nodeIds, linkIds, linkOrder, omitted: 0 };
}

/**
 * 「지금 어느 단계인가」 — 정의는 여기 하나뿐이다.
 *
 * 예전에는 세 화면이 각자 다르게 계산했다. 등장 애니메이션용 stage 를 쓰거나,
 * pending 이 아닌 단계 수를 세거나, status==="active" 를 찾거나. 그래서 같은 화면에서
 * 「현재 단계: 제안서 초안」과 「진행률 25%」처럼 서로 안 맞는 값이 나란히 떴다.
 *
 * 규칙: 실행 중(active)이 있으면 그것이 현재 단계다. 없으면 «아직 안 한 첫 단계»이고,
 * 그것도 없으면(전부 끝났으면) 마지막 단계다.
 */
/**
 * 화면을 열었을 때 **기본으로 펼칠 단계** — 「가장 먼저 처리할 단계」다.
 *
 * 예전에는 등장 애니메이션이 끝나면 언제나 8단계(담당자 최종 결정)가 열렸다. 그래서
 * 진행 현황이 2/8 인 공고에서도 오른쪽에 최종 검토가 떠 있었고, 담당자는 「지금 8단계인가?」로
 * 읽었다. 아직 끝내지 못한 첫 단계를 열어야 «다음에 할 일»과 화면이 일치한다.
 *
 * 완료 판정은 isStepSettled 하나만 쓴다 — 진행 현황(2/8)을 세는 것과 같은 정의여야
 * 「2/8 인데 8단계가 열려 있다」 같은 모순이 생기지 않는다.
 * 전부 끝났으면 마지막 단계(사람의 최종 결정)가 맞다.
 */
export function landingStage(steps: WorkflowStepView[]): WorkflowStage {
  const pending = steps.find((step) => !isStepSettled(step));
  return (pending ?? steps[steps.length - 1]).id;
}

export function currentStep(steps: WorkflowStepView[]): WorkflowStepView {
  const active = steps.find((s) => s.status === "active");
  if (active) return active;
  const next = steps.find((s) => s.status === "pending");
  return next ?? steps[steps.length - 1];
}
