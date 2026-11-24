/**
 * 발표 모드 시나리오 — 9장면. 각 장면은 실제 대시보드의 단계(stage)·선택 노드를 제어한다.
 * 별도 영상이 아니라 대시보드 상태를 순서대로 바꾸는 정의다. 숫자는 전부 그래프에서 읽고, 자막은 한 문장이다.
 *
 * **지도의 길을 따라 간다** (21차 · prompt_11 §3-9) — 장면의 단계가 곧 정거장이고, 지도 카메라가 그 정거장으로 옮겨 간다.
 * 1 한 길(① 에서 시작) → 2 ① 공고 → 3 ② 적합도 → 4 ③ 참가자격·놓치면 안 되는 조건 → 5 ④ 수행 과업
 * → 6 ⑤ 회사 수행근거(근거 부족 항목 포함) → 7 ⑥ 제안서 문장 → 8 ⑦ 제출 전 점검 → 9 ⑧ 사람의 결정
 *
 * `camera` 프리셋은 지원사업 지도와 안내가 함께 쓰는 이름이라 남긴다 — 입찰 정거장 지도는 단계만 따른다.
 * reduced-motion이면 즉시 전환된다.
 */

// 자막이 영문 enum(HIGH·BLOCKER·GO)을 그대로 부르면 발표 중에 자막만 화면 다른 곳과 다른 말을 한다.
// 같은 한국어 이름을 쓰려고 라벨표를 그대로 가져온다 — 여기서 문구를 새로 지어내지 않는다.
import { CANDIDATE_TIER_LABELS, CONDITION_STATUS_LABELS, DECISION_LABELS } from "./format";
import {
  AUDIT_NODE_ID,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  findingNodeId,
  requirementNodeId,
  type CosmosGraph,
  type WorkflowStage,
} from "./graph";
import { blockingText, eligibilityGateView, gateCounts } from "./eligibilityGate";
import { groupCounts, itemTypeOf } from "./itemTypes";
import { STATION_IDS, STATION_NAMES } from "./stations";
import { SYNTHETIC_NOTICE } from "@/lib/terms";

export type CameraPreset =
  | "overview"
  | "notice"
  | "requirements"
  | "evidence"
  | "proposal"
  | "audit"
  | "review";

export interface PresentationScene {
  id: string;
  title: string;
  /** 한 문장 자막 — 그래프 수치를 넣기 위해 함수로 둔다 (숫자 하드코딩 금지). */
  caption: (graph: CosmosGraph) => string;
  stage: WorkflowStage;
  camera: CameraPreset;
  focusNodeId: (graph: CosmosGraph) => string | null;
  durationMs: number;
}

const NOT_RUN = "이 단계는 아직 실행되지 않았습니다 — 오른쪽 패널에서 직접 실행하거나 「가상 예시 공고」로 전체 흐름을 볼 수 있습니다.";

const firstFindingOfType = (graph: CosmosGraph, type: string) =>
  graph.findings.find((f) => f.finding_type === type && !f.resolved) ?? graph.findings[0] ?? null;

const blockerRequirement = (graph: CosmosGraph) => graph.requirements.find((r) => graph.nodeById.get(r.nodeId)?.blocker) ?? null;

const conditionRequirement = (graph: CosmosGraph) =>
  blockerRequirement(graph) ??
  graph.requirements.find((r) => r.criticality === "high") ??
  graph.requirements.find((r) => ["ELIGIBILITY", "SCHEDULE", "SUBMISSION"].includes(itemTypeOf(r))) ??
  null;

const taskRequirement = (graph: CosmosGraph) => graph.requirements.find((r) => itemTypeOf(r) === "TASK") ?? graph.requirements[0] ?? null;

const gapRequirement = (graph: CosmosGraph) =>
  // 지도 판정(노드 상태)으로 고른다 — 자막이 「확인 필요」라 말한 항목이 지도에서는 「문제」로 보였다(27차 검수 R27D-OWN-05).
  graph.requirements.find((r) => r.nodeState === "check") ?? graph.requirements.find((r) => r.displayStatus === "unmatched") ?? null;

const originLabel = (graph: CosmosGraph) =>
  graph.source.origin.kind === "demo" ? SYNTHETIC_NOTICE : graph.source.origin.source === "g2b" ? "실제 나라장터 공고" : "나라장터 저장본 공고";

export const PRESENTATION_SCENES: PresentationScene[] = [
  {
    id: "path",
    title: "1. 공고에서 결정까지 한 길",
    caption: () =>
      `${STATION_IDS.map((id) => STATION_NAMES[id]).join(" → ")} — 이 길을 근거가 끊기지 않고 지나는지 정거장마다 봅니다.`,
    stage: 1,
    camera: "overview",
    focusNodeId: () => null,
    durationMs: 5000,
  },
  {
    id: "select",
    title: "2. 공고",
    // 공고명은 받침이 있을 수도 없을 수도 있어 「…을」이 반쯤은 틀린 말이 된다(「…교육을」/「…아카데미을」).
    // 조사를 붙이지 않는 자리로 옮겨 어느 공고에서도 문장이 성립하게 둔다.
    caption: (g) => `${g.source.notice.agency}의 「${g.source.notice.title}」 — 이 공고를 분석 대상으로 골랐습니다 (${originLabel(g)}).`,
    stage: 1,
    camera: "notice",
    focusNodeId: () => NOTICE_NODE_ID,
    durationMs: 6000,
  },
  {
    id: "fit",
    title: "3. 우리 회사 적합도",
    caption: (g) => {
      const tier = g.source.notice.candidate?.tier;
      const fit = g.source.scenario
        ? `적합도 ${g.source.scenario.semantic_match.label}(${SYNTHETIC_NOTICE})`
        : tier
          ? `낱말 관련도 ${CANDIDATE_TIER_LABELS[tier] ?? tier}`
          : null;
      // 적합도가 없는 공고에서 예전 자막은 「적합도 미실행이라 …」로 이어져 판단 사유처럼 읽혔다.
      // 계산하지 않았다는 사실은 따로 한 문장으로 말한다 — 없는 값을 짐작해 말하지 않는다.
      if (!fit) return "우리 회사 적합도는 아직 계산하지 않았습니다 — 점수가 아니라 검토할 가치가 있는지를 보는 자리입니다.";
      return `${fit} — 우리 회사가 검토할 가치가 있는지부터 봅니다. 낙찰 가능성이 아닙니다.`;
    },
    stage: 2,
    camera: "notice",
    focusNodeId: () => NOTICE_NODE_ID,
    durationMs: 6000,
  },
  {
    id: "condition",
    title: "4. 참가 가능 여부 · 놓치면 안 되는 조건",
    caption: (g) => {
      // 지도 ③ 정거장 · 상세 띠 · 체크리스트와 같은 계산 (eligibilityGateView).
      const gate = eligibilityGateView(g.eligibility, g.source.analysis.eligibility?.verdict ?? null);
      if (gate?.verdict === "FAIL") {
        // 10-31 최종 점검 — 긴 사유는 「…」로 잘린다 — 그 뒤에 마침표를 또 붙이지 않는다(「…. 길이」)
        const why = gate.blocking ? blockingText(gate.blocking) : "막는 조건이 있습니다";
        return `참가할 수 없습니다 — ${why}${why.endsWith("…") ? "" : "."} 길이 여기서 끊깁니다.`;
      }
      const blocker = g.source.analysis.conditions?.conditions.find((c) => c.status === "BLOCKER");
      if (blocker) return `「${blocker.title}」은 점수 문제가 아니라, 놓치면 입찰에 참여할 수 없는 조건입니다${blocker.source_page ? ` (제안요청서 ${blocker.source_page}쪽)` : ""}.`;
      if (gate?.verdict === "CHECK") {
        // 확인 전 조항이 없는데 공고 필드만 남았으면 「조항 확인 전」이라 하지 않는다 — KPI 타일과 같은 말(gateCounts).
        if (gate.total > 0 && gate.pending > 0) {
          return `참가자격 조항은 사람이 하나씩 확인합니다 — 지금 ${gateCounts(gate)}. 자격·제출·일정 조건은 점수가 아니라 참가 자체를 좌우합니다.`;
        }
        if (gate.fieldCheck > 0) {
          return `참가자격은 아직 확인이 필요합니다 — ${gateCounts(gate)}. 자격·제출·일정 조건은 점수가 아니라 참가 자체를 좌우합니다.`;
        }
      }
      const cond = conditionRequirement(g);
      if (cond) return `「${cond.title}」처럼 자격·제출·일정 조건은 점수가 아니라 참가 자체를 좌우하므로 먼저 확인합니다.`;
      return `참가를 막는 「${CONDITION_STATUS_LABELS.BLOCKER}」 조건은 없고, 확인이 필요한 조건은 사람이 원문을 보고 정합니다.`;
    },
    stage: 3,
    camera: "requirements",
    focusNodeId: () => null,
    durationMs: 7500,
  },
  {
    id: "tasks",
    title: "5. 요구사항 정리",
    caption: (g) => {
      // 화면 버튼 이름은 「공고 분석 시작」이다 — 자막만 「파싱」이라고 부르면 담당자가 어디를 눌러야 할지 모른다.
      if (!g.source.parse) return "이 공고의 제안요청서를 아직 분석하지 않아 요구사항 정거장이 비어 있습니다 — 발표를 끝낸 뒤 위쪽 「공고 분석 시작」을 누르면 채워집니다(발표 중에는 잠깁니다).";
      const groups = groupCounts(g.requirements);
      return `제안요청서에서 실제 수행할 과업 ${groups.perform}건과 지켜야 할 조건 ${groups.conditions + groups.submit}건을 페이지 근거와 함께 뽑았습니다.`;
    },
    stage: 4,
    camera: "requirements",
    focusNodeId: (g) => taskRequirement(g)?.nodeId ?? null,
    durationMs: 7000,
  },
  {
    id: "evidence",
    title: "6. 회사 수행근거 연결",
    caption: (g) => {
      if (!g.hasScenario) return NOT_RUN;
      const r = gapRequirement(g);
      const gap = r ? ` 「${r.title}」처럼 근거가 부족한 항목은 자동으로 충족 처리하지 않고 「확인 필요」로 둡니다.` : "";
      return `회사자료 ${g.counts.evidenceDocuments}종이 요구사항과 연결됩니다 — 근거를 고르면 청록 실선(채택) · 호박 점선(확인 필요)으로 이어진 정거장이 보입니다.${gap}`;
    },
    stage: 5,
    camera: "evidence",
    focusNodeId: (g) => g.evidence[0]?.nodeId ?? null,
    durationMs: 8000,
  },
  {
    id: "proposal",
    title: "7. 제안서 초안",
    caption: (g) =>
      g.proposal
        ? // 「필수」 기준인 것은 제출 전 점검을 돌렸을 때뿐이다 (graph.ts 의 coverage 참고).
          // 돌리기 전에는 «뽑아 낸 요구사항 전체»가 분모다 — 자막이 없는 사실을 말하지 않게 갈라 쓴다.
          `채택된 근거만으로 「${g.proposal.title}」 ${g.counts.sentences}문장을 만들었고, ${
            g.hasAudit ? "필수 요구사항" : "요구사항"
          } ${g.coverage.total}건 중 ${g.coverage.covered}건이 반영됐습니다${g.source.analysis.proposal ? "" : ` (${SYNTHETIC_NOTICE})`}.`
        : "제안서 초안을 아직 만들지 않았습니다 — 오른쪽 패널의 「제안서 초안 만들기」로 요구사항과 고른 근거만으로 씁니다.",
    stage: 6,
    camera: "proposal",
    focusNodeId: () => PROPOSAL_NODE_ID,
    durationMs: 7000,
  },
  {
    id: "audit",
    title: "8. 제출 전 누락 점검",
    caption: (g) => {
      if (!g.hasAudit) return "제출 전 누락 점검을 아직 실행하지 않았습니다 — 초안을 붙여넣고 「제출 전 점검」을 누르면 누락을 원문과 함께 찾습니다.";
      const f = firstFindingOfType(g, "missing_requirement");
      // 요구사항 번호가 없는 발견도 있다. 번호 자리를 그냥 비우면 공백이 겹쳐 보여 조각을 따로 만든다.
      const where = f?.source_page ? ` ${f.requirement_id ? `${f.requirement_id} ` : ""}제안요청서 ${f.source_page}쪽처럼` : "";
      // 선은 **고른 항목에서만** 보인다(27차 §3-D-3) — 이 장면이 고른 발견에서 대상 정거장까지 선이 있을 때만 말한다.
      // 발견이 많으면(묶음) 발견 → 요구사항 선이 없다 (21차 검토).
      const target = f ? g.links.find((l) => l.source === findingNodeId(f.id) && l.kind === "finding-target")?.target : undefined;
      const targetStage = target ? g.nodeById.get(target)?.stage : undefined;
      return `제출 전 점검이 찾은 문제 ${g.counts.findings}건을${where} 원문 페이지와 함께 보여 주고, ${
        targetStage
          ? `골라 둔 발견에서 ${targetStage} ${STATION_NAMES[targetStage]} 정거장까지 선이 이어집니다`
          : "7 점검 정거장의 ⚠ 가 원인별 문제 묶음입니다"
      }.`;
    },
    stage: 7,
    camera: "audit",
    focusNodeId: (g) => {
      const f = firstFindingOfType(g, "missing_requirement");
      return f ? findingNodeId(f.id) : AUDIT_NODE_ID;
    },
    durationMs: 8000,
  },
  {
    id: "decision",
    title: "9. 담당자 최종 결정",
    caption: (g) => {
      const gate = g.source.analysis.conditions?.gate;
      const decision = g.source.analysis.decision;
      const decided =
        decision && decision.status !== "UNREVIEWED" ? `현재 결정은 「${DECISION_LABELS[decision.status]}」이며` : "아직 결정하지 않았으며";
      const blocked = gate && !gate.can_go
        ? `미해결 「${CONDITION_STATUS_LABELS.BLOCKER}」 조건이 있어 「${DECISION_LABELS.GO}」로는 넘어갈 수 없고`
        : "AI 결과는 참고자료이고";
      return `${decided} ${blocked} 최종 참여 여부는 사람이 사유와 함께 저장합니다.`;
    },
    stage: 8,
    camera: "review",
    focusNodeId: (g) => (g.hasAudit ? AUDIT_NODE_ID : g.requirements[0] ? requirementNodeId(g.requirements[0].requirement_id) : NOTICE_NODE_ID),
    durationMs: 7500,
  },
];
