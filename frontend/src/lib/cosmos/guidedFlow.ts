/**
 * Guided Flow — "이 화면을 이해하는 5단계". 기존 8단계 워크플로(실제 분석 업무 흐름)와는 별개다.
 *
 * ① 분석할 공고 → ② 과업·필수조건 → ③ 회사 수행근거 → ④ 제안서 반영 → ⑤ 위험 검증
 *
 * 규칙
 * - 설명 단계는 실제 분석 진행률(graph.progress)이나 완료 상태를 바꾸지 않는다. 카메라·강조·패널 내용만 바꾼다.
 * - 화면에 보이는 숫자는 전부 CosmosGraph에서 계산한다. 없는 단계는 "미실행"이라고 말한다.
 * - 기록은 localStorage `bidpilot.guided.v1` = { step, seen } (튜토리얼 기록 `bidpilot.tutorial.v1`과 별개).
 */

import type { CosmosGraph, CosmosNode, FocusSet, RequirementView, WorkflowStage } from "./graph";
import {
  AUDIT_NODE_ID,
  EMPTY_FOCUS,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  evidenceNodeId,
  isSevere,
  severityRank,
} from "./graph";
import { groupCounts, itemTypeOf } from "./itemTypes";
import type { CameraPreset } from "./presentation";

export type GuidedStep = 1 | 2 | 3 | 4 | 5;

export interface GuidedStepDef {
  id: GuidedStep;
  /** 한 줄 제목 ("분석할 공고") */
  title: string;
  /** 질문형 부제 ("어떤 사업인가") */
  question: string;
  /** 하단 Caption Bar 한 문장 */
  caption: string;
  /** 다음 단계 버튼 문구 (마지막 단계는 사람의 결정으로) */
  nextLabel: string;
  camera: CameraPreset;
  /** 이 단계의 노드가 보이려면 최소 몇 단계까지 드러나 있어야 하는가 (등장 애니메이션·레일과 무관한 표시 조건) */
  revealStage: WorkflowStage;
  /** 카메라가 향할 노드 */
  focusNodeId: (graph: CosmosGraph) => string | null;
}

export const GUIDED_STEPS: readonly GuidedStepDef[] = [
  {
    id: 1,
    title: "분석할 공고",
    question: "어떤 사업인가",
    caption: "이 공고가 우리 회사에 적합한지 확인하고 분석 범위를 결정합니다.",
    nextLabel: "다음: 과업과 필수조건 보기",
    camera: "notice",
    revealStage: 1,
    focusNodeId: () => NOTICE_NODE_ID,
  },
  {
    id: 2,
    title: "과업·필수조건",
    question: "무엇을 해야 하나",
    caption: "과업은 실제 수행할 일이고, 조건은 참가와 제출을 위해 반드시 지켜야 하는 사항입니다.",
    nextLabel: "다음: 회사 수행근거 보기",
    camera: "requirements",
    revealStage: 4,
    focusNodeId: (g) => representativeRequirement(g)?.nodeId ?? null,
  },
  {
    id: 3,
    title: "회사 수행근거",
    question: "우리가 할 수 있나",
    caption: "승인된 회사자료만 수행근거로 연결하며, 근거가 없으면 확인 필요로 남깁니다.",
    nextLabel: "다음: 제안서 반영 보기",
    camera: "evidence",
    revealStage: 5,
    focusNodeId: (g) => representativeEvidence(g)?.nodeId ?? representativeRequirement(g)?.nodeId ?? null,
  },
  {
    id: 4,
    title: "제안서 반영",
    question: "어떻게 답했나",
    caption: "제안요청서 원문과 회사 근거가 연결된 제안서 문장을 확인합니다.",
    nextLabel: "다음: 위험 검증 보기",
    camera: "proposal",
    revealStage: 6,
    focusNodeId: (g) => (g.hasProposal ? PROPOSAL_NODE_ID : null),
  },
  {
    id: 5,
    title: "위험 검증",
    question: "빠진 것은 없나",
    caption: "제출 전 누락 점검이 빠진 요구사항, 숫자 불일치와 근거 없는 주장을 제출 전에 찾습니다.",
    nextLabel: "사람의 결정으로",
    camera: "audit",
    revealStage: 7,
    focusNodeId: (g) => (g.hasAudit ? (representativeFinding(g)?.nodeId ?? AUDIT_NODE_ID) : null),
  },
];

export const GUIDED_STORAGE_KEY = "bidpilot.guided.v1";

export function guidedStepDef(step: GuidedStep): GuidedStepDef {
  return GUIDED_STEPS[step - 1];
}

// ---------------------------------------------------------------------------
// 대표 노드 (숫자·이름은 그래프에서만)
// ---------------------------------------------------------------------------

/** 설명에 쓸 대표 항목: BLOCKER 항목 › 누락 발견이 붙은 항목 › 과업(TASK) › 첫 항목. */
export function representativeRequirement(graph: CosmosGraph): RequirementView | null {
  if (graph.requirements.length === 0) return null;
  const blocker = graph.requirements.find((r) => graph.nodeById.get(r.nodeId)?.blocker);
  if (blocker) return blocker;
  const missing = graph.findings.find((f) => f.finding_type === "missing_requirement" && !f.resolved && f.requirement_id);
  if (missing) {
    const hit = graph.requirements.find((r) => r.requirement_id === missing.requirement_id);
    if (hit) return hit;
  }
  return (
    graph.requirements.find((r) => itemTypeOf(r) === "TASK" && r.evidence.length > 0) ??
    graph.requirements.find((r) => itemTypeOf(r) === "TASK") ??
    graph.requirements[0]
  );
}

/**
 * 설명에 쓸 대표 근거: 대표 항목에 채택된 근거 › 채택 근거가 있는 문서 › 첫 문서.
 * 같은 후보 안에서는 궤도 뒤쪽(z가 작은 쪽)을 고른다 — 기본 카메라(앞쪽 위)에서 라벨이 화면 아래로 잘리지 않게.
 */
export function representativeEvidence(graph: CosmosGraph) {
  if (graph.evidence.length === 0) return null;
  const depth = (nodeId: string) => graph.nodeById.get(nodeId)?.position[2] ?? 0;
  const byDepth = <T extends { nodeId: string }>(items: T[]): T[] => [...items].sort((a, b) => depth(a.nodeId) - depth(b.nodeId));
  const rep = representativeRequirement(graph);
  if (rep && rep.evidence.length > 0) {
    const ids = new Set(rep.evidence.filter((e) => e.selected).map((e) => e.evidence_id));
    const pool = ids.size > 0 ? ids : new Set(rep.evidence.map((e) => e.evidence_id));
    const candidates = byDepth(graph.evidence.filter((e) => pool.has(e.id)));
    if (candidates[0]) return candidates[0];
  }
  const withSelected = byDepth(graph.evidence.filter((e) => e.links.some((l) => l.selected)));
  return withSelected[0] ?? byDepth(graph.evidence)[0] ?? null;
}

/** 설명에 쓸 대표 발견: 미해결 누락 요구사항 › 미해결 높음 › 첫 발견. */
export function representativeFinding(graph: CosmosGraph) {
  if (graph.findings.length === 0) return null;
  return (
    graph.findings.find((f) => f.finding_type === "missing_requirement" && !f.resolved) ??
    graph.findings.find((f) => isSevere(f) && !f.resolved) ??
    graph.findings[0]
  );
}

// ---------------------------------------------------------------------------
// 단계별 Focus Mode 집합
// ---------------------------------------------------------------------------

/** 과업·조건 단계에서 밝힐 항목 수 상한 (전부 밝히면 다시 hairball이 된다). */
const STEP2_LIMIT = 7;
const STEP3_EVIDENCE_LIMIT = 8;
const STEP5_FINDING_LIMIT = 6;

function requirementPriority(graph: CosmosGraph, r: RequirementView): number {
  const node = graph.nodeById.get(r.nodeId);
  if (node?.blocker) return 0;
  if (r.criticality === "high") return 1;
  if (r.findings.length > 0) return 2;
  if (itemTypeOf(r) === "TASK") return 3;
  if (itemTypeOf(r) === "ELIGIBILITY" || itemTypeOf(r) === "SUBMISSION" || itemTypeOf(r) === "SCHEDULE") return 4;
  return 5;
}

/** 단계에 맞는 노드·연결선 집합. 노드가 없는 단계(미실행)는 앞 단계 집합에 머문다. */
export function guidedFocus(graph: CosmosGraph, step: GuidedStep): FocusSet {
  const nodeIds = new Set<string>();
  const linkIds = new Set<string>();
  const linkOrder = new Map<string, number>();
  const linkExists = new Set(graph.links.map((l) => l.id));
  const add = (linkId: string, order: number) => {
    if (!linkExists.has(linkId)) return;
    linkIds.add(linkId);
    linkOrder.set(linkId, order);
  };
  const rep = representativeRequirement(graph);
  if (!rep) return EMPTY_FOCUS;

  nodeIds.add(NOTICE_NODE_ID);
  if (step === 1) {
    // 공고만 강하게, 다음 대표 항목은 연결선으로만 예고한다.
    nodeIds.add(rep.nodeId);
    add(`link:notice:${rep.requirement_id}`, 0);
    return { nodeIds, linkIds, linkOrder, omitted: 0 };
  }

  const ranked = [...graph.requirements].sort((a, b) => requirementPriority(graph, a) - requirementPriority(graph, b));
  const shown = ranked.slice(0, STEP2_LIMIT);
  if (!shown.includes(rep)) shown[shown.length - 1] = rep;
  for (const r of shown) {
    nodeIds.add(r.nodeId);
    add(`link:notice:${r.requirement_id}`, 0);
  }
  if (step === 2) return { nodeIds, linkIds, linkOrder, omitted: Math.max(0, graph.requirements.length - shown.length) };

  // 3: 대표 항목의 근거 + 근거 궤도 일부
  const evidenceIds = new Set<string>();
  for (const e of rep.evidence) {
    evidenceIds.add(e.evidence_id);
    add(`link:${rep.requirement_id}:${e.evidence_id}`, 0);
  }
  for (const ev of graph.evidence) {
    if (evidenceIds.size >= STEP3_EVIDENCE_LIMIT) break;
    evidenceIds.add(ev.id);
  }
  for (const id of evidenceIds) nodeIds.add(evidenceNodeId(id));
  if (step === 3) return { nodeIds, linkIds, linkOrder, omitted: Math.max(0, graph.evidence.length - evidenceIds.size) };

  // 4: 제안서 — 대표 항목·근거에서 제안서로 가는 선
  if (graph.hasProposal) {
    nodeIds.add(PROPOSAL_NODE_ID);
    add(`link:${rep.requirement_id}:proposal`, 1);
    for (const e of rep.evidence) add(`link:${e.evidence_id}:proposal`, 1);
  }
  if (step === 4) return { nodeIds, linkIds, linkOrder, omitted: 0 };

  // 5: Auditor 경고 경로
  if (graph.hasAudit) {
    nodeIds.add(AUDIT_NODE_ID);
    add("link:proposal:audit", 2);
    // 참가 차단(critical) → 높음 → 나머지 순. 예전에는 high 만 앞으로 당겨 critical 이 뒤에 묻혔다.
    const findings = [...graph.findings].sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
    let count = 0;
    for (const f of findings) {
      if (count >= STEP5_FINDING_LIMIT) break;
      f.pathNodeIds.forEach((id) => nodeIds.add(id));
      f.pathLinkIds.forEach((id, index) => add(id, 2 + index));
      count += 1;
    }
    return { nodeIds, linkIds, linkOrder, omitted: Math.max(0, graph.findings.length - count) };
  }
  return { nodeIds, linkIds, linkOrder, omitted: 0 };
}

// ---------------------------------------------------------------------------
// 3D 직접 라벨 — 기본 화면에 보이는 핵심 5개
// ---------------------------------------------------------------------------

export interface KeyLabel {
  nodeId: string;
  /** 사람이 읽는 제목 ("분석 대상 공고") */
  title: string;
  /** 보조 설명 ("생성형 AI 교육 운영") — 그래프에서 계산 */
  subtitle: string;
  /** 작은 보조 정보 (코드·ID) */
  code?: string;
  /** 어느 Guided 단계의 앵커인가 */
  step: GuidedStep;
}

function shorten(text: string, max: number): string {
  const t = text.trim();
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
}

/** 핵심 라벨 5개(존재하는 노드만). 숫자·이름은 전부 데이터에서 온다. */
export function keyLabels(graph: CosmosGraph): KeyLabel[] {
  const labels: KeyLabel[] = [];
  const { notice, analysis } = graph.source;
  labels.push({
    nodeId: NOTICE_NODE_ID,
    title: "분석 대상 공고",
    subtitle: shorten(notice.title, 22),
    step: 1,
  });

  const rep = representativeRequirement(graph);
  if (rep) {
    const groups = groupCounts(graph.requirements);
    const blocker = analysis.conditions?.conditions.find((c) => c.status === "BLOCKER");
    const repNode = graph.nodeById.get(rep.nodeId);
    const tail = blocker ? blocker.title : repNode?.blocker ? "참가 차단 조건" : `조건 ${groups.conditions + groups.submit}건`;
    labels.push({
      nodeId: rep.nodeId,
      title: "수행 과업·참가조건",
      subtitle: `과업 ${groups.perform}건 · ${tail}`,
      code: repNode?.code ?? rep.requirement_id,
      step: 2,
    });
  }

  const ev = representativeEvidence(graph);
  if (ev) {
    const types = [...new Set(graph.evidence.map((e) => e.doc_type))].slice(0, 3);
    labels.push({
      nodeId: ev.nodeId,
      title: "회사 수행근거",
      subtitle: types.length > 0 ? types.join(" · ") : "근거 문서",
      step: 3,
    });
  }

  if (graph.hasProposal) {
    labels.push({
      nodeId: PROPOSAL_NODE_ID,
      title: "제안서 반영",
      subtitle: `근거가 연결된 대응 문장 ${graph.counts.sentences}개`,
      step: 4,
    });
  }

  if (graph.hasAudit) {
    const missing = graph.coverage.missingRequirementIds.length;
    labels.push({
      nodeId: AUDIT_NODE_ID,
      title: "제출 전 위험",
      subtitle:
        missing > 0
          ? `미반영 요구사항 ${missing}건`
          : graph.counts.findingsOpen > 0
            ? `발견 ${graph.counts.findingsOpen}건 미해결`
            : "발견 없음",
      step: 5,
    });
  }
  return labels;
}

export function keyLabelMap(graph: CosmosGraph): Map<string, KeyLabel> {
  return new Map(keyLabels(graph).map((k) => [k.nodeId, k]));
}

/** 어떤 노드가 어느 Guided 단계에 속하는지 (선택 시 단계 표시용). */
export function stepOfNode(node: CosmosNode): GuidedStep {
  switch (node.kind) {
    case "notice":
      return 1;
    case "requirement":
      return 2;
    case "evidence":
      return 3;
    case "proposal":
      return 4;
    default:
      return 5;
  }
}

// ---------------------------------------------------------------------------
// 기록 (localStorage)
// ---------------------------------------------------------------------------

export interface GuidedRecord {
  step: GuidedStep | null;
  /** 한 번이라도 안내를 보았는지 (첫 진입 판단) */
  seen: boolean;
}

const DEFAULT_RECORD: GuidedRecord = { step: null, seen: false };

export function readGuidedRecord(): GuidedRecord {
  try {
    const raw = window.localStorage.getItem(GUIDED_STORAGE_KEY);
    if (!raw) return DEFAULT_RECORD;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_RECORD;
    const record = parsed as Partial<Record<keyof GuidedRecord, unknown>>;
    const step = record.step;
    return {
      step: step === 1 || step === 2 || step === 3 || step === 4 || step === 5 ? step : null,
      seen: record.seen === true,
    };
  } catch {
    return DEFAULT_RECORD;
  }
}

export function writeGuidedRecord(patch: Partial<GuidedRecord>): void {
  try {
    const next = { ...readGuidedRecord(), ...patch };
    window.localStorage.setItem(GUIDED_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // 저장 실패는 무시한다 — 안내 자체는 동작해야 한다.
  }
}
