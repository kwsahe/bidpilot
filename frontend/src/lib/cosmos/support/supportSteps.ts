/**
 * 지원사업 신청 분석 7단계 — 진행 바와 3D 자막이 **같은 수**를 쓰게 하는 단일 출처.
 *
 * 입찰 쪽에서 이미 한 번 갈렸다: 레일은 done+attention 을, 진행률은 done+failed 를 세서
 * 같은 화면에 「7/8」과 「38%」가 나란히 떴다(graph.ts `isStepSettled` 주석).
 * 지원사업은 그 실수를 반복하지 않으려고 «세는 함수를 여기 하나만» 둔다.
 *
 * 주의 — 여기서 계산을 «고치지» 마라. `SupportShell.tsx` 의 `stepStats`(98-115)를
 * 값이 같도록 그대로 옮긴 것이고, 두 곳의 숫자가 갈리면 같은 사업에서
 * 진행 바는 「확인 필요 1건」, 3D 자막은 「0건」이 된다.
 */

import type { SupportStepStat } from "@/components/support/SupportStepBar";
import type { CosmosGraph, WorkflowStage, WorkflowStepView } from "@/lib/cosmos/graph";
import { AUDIT_NODE_ID, PROPOSAL_NODE_ID, isStepSettled } from "@/lib/cosmos/graph";
import type { CameraPreset } from "@/lib/cosmos/presentation";
import { supportEvidenceTally } from "@/lib/cosmos/support/supportGraph";
import {
  SUPPORT_STEPS,
  type PlanDraft,
  type SupportApplicationResult,
  type SupportStepKey,
} from "@/types/opportunity";

/**
 * 단계 → 3D 등장 순서(stage).
 *
 * `WorkflowStage` 는 1..8 이고 지원사업은 1..7 만 쓴다(부분집합이라 타입이 그대로 맞는다).
 * 입찰 8단계의 뜻(3=참가 가능 여부 …)과 **대응하지 않는다** — 3D 가 노드를 순서대로
 * 드러내는 데에만 쓰는 번호다.
 */
export const SUPPORT_STAGE: Record<SupportStepKey, WorkflowStage> = {
  eligibility: 1,
  conditions: 2,
  schedule: 3,
  documents: 4,
  evidence: 5,
  draft: 6,
  check: 7,
};

/** 원문에서 «항목으로» 뽑히는 네 단계. 나머지 셋은 세는 방법이 다르다. */
const PLAN_KEYS = ["eligibility", "conditions", "schedule", "documents"] as const;
type PlanKey = (typeof PLAN_KEYS)[number];

/** 단계 라벨을 SUPPORT_STEPS 에서 찾는다 — 단계 이름을 여기서 다시 쓰지 않는다. */
function stepLabel(key: SupportStepKey): string {
  return SUPPORT_STEPS.find((step) => step.key === key)?.label ?? key;
}

/**
 * 진행 바에 붙는 건수. pending 은 담당자가 원문에서 확인해야 하는 항목 수다.
 * `SupportShell.tsx:98-115` 과 같은 계산이며, 바꾸면 두 화면의 숫자가 갈린다.
 *
 * 6단계(사업계획서)는 **저장된 공고 양식 초안**의 소항목 수(`checklist.form`)로 센다 (SUP-13). 예전 6절 뼈대
 * (`draft_outline`)는 접힌 참고라 초안을 만들어도 수가 안 바뀌었고, ④ 「양식 n/m」과 다른 진행도를 말했다.
 * `draft` 를 모르는 곳(undefined)은 세지 않는다 — 없는 수를 지어내지 않는다.
 */
export function supportStepStats(result: SupportApplicationResult, draft?: PlanDraft | null): SupportStepStat[] {
  const count = (key: PlanKey): SupportStepStat => {
    const items = result.plan[key];
    // 43차 N10 — 공고문을 읽었는데 그 갈래 조항이 없던 줄(clause_*)은 「확인 필요」가 아니라 「조항 없음」. 판정이 「가능」인데 단계가 「확인 필요 6」이라 했다.
    const absent = items.filter((item) => item.status === "unknown" && item.key.startsWith("clause_") && item.value === null).length;
    const pending = items.filter((item) => item.status === "unknown").length - absent;
    return { key, done: items.length - pending - absent, pending, ...(absent ? { absent } : {}) };
  };
  const form = draft?.checklist?.form;
  return [
    count("eligibility"),
    count("conditions"),
    count("schedule"),
    count("documents"),
    {
      // 「몇 건」은 **서로 다른 회사자료 수**다. evidence_matches 는 같은 자료를 검색 기준마다
      // 되풀이해 담고 있어서(백엔드가 「사업 개요」·「지원 분야」·「지원 대상」 세 기준으로 따로
      // 검색해 이어 붙인다) 그대로 세면 부풀려진다 — 실측: 6건 가운데 실제 자료는 3건.
      // 3D 는 중복을 접어 3개를 그리는데 단계바만 6이라고 적으면 담당자가 3개를 못 찾은 줄 안다.
      key: "evidence",
      // 45차 H5 — 실적 원장 후보(미채택)는 「연결된 회사 근거」가 아니다(「✓ 완료 · 연결된 회사 근거 5건」으로 보였다)
      done: supportEvidenceTally({ ...result, evidence_matches: result.evidence_matches.filter((m) => !m.evidence_id.startsWith("ledger-")) }).unique,
      pending: result.evidence_matches.length === 0 ? 1 : 0,
    },
    { key: "draft", done: form?.items_filled ?? 0, pending: form ? form.items_total - form.items_filled : 0 },
    { key: "check", done: 0, pending: result.pre_submit_checks.length },
  ];
}

/**
 * 3D 자막용 7단계.
 *
 * `id` 는 1..7(WorkflowStage 의 부분집합), `key` 는 SupportStepKey.
 * `status` 는 "done" | "attention" | "pending" 셋만 쓴다 — "failed" 는 «실행했고 답이
 * 나왔다»는 뜻인데 지원사업 쪽은 판정을 실행한 적이 없다. 「확인 필요」를 실패로 적으면
 * 담당자가 확인하면 끝날 일을 탈락으로 읽는다.
 *
 * 수치는 전부 `supportStepStats` 에서 가져온다 (두 곳에서 세지 않는다).
 */
export function buildSupportSteps(result: SupportApplicationResult, draft?: PlanDraft | null): WorkflowStepView[] {
  const statByKey = new Map(supportStepStats(result, draft).map((stat) => [stat.key, stat]));

  return SUPPORT_STEPS.map((step, index) => {
    const stat = statByKey.get(step.key);
    const done = stat?.done ?? 0;
    const pending = stat?.pending ?? 0;

    let status: WorkflowStepView["status"];
    let summary: string;

    if (step.key === "evidence") {
      // 근거 0건은 «틀렸다»가 아니라 «아직 연결된 것이 없다»다. 회사자료를 등록·승인하면 채워진다.
      status = done > 0 ? "done" : "attention";
      const ledger = result.evidence_matches.filter((m) => m.evidence_id.startsWith("ledger-")).length;
      summary = done > 0 ? `연결된 회사 근거 ${done}건` : ledger > 0 ? `원장 참고 후보 ${ledger}건` : "연결된 회사 근거 없음";
    } else if (step.key === "draft") {
      // 양식 소항목 수가 있으면 ④ 요약(「양식 n/m」)과 같은 수 · 없으면 초안이 있는지만 (SUP-13)
      const form = draft?.checklist?.form;
      const hasDraft = Boolean(draft?.sections.length);
      // 초안을 모르면(undefined) 「대기」로 단정하지 않는다 — 저장된 초안이 있을 수 있다. 「없음」은 초안 없음(null)일 때만.
      status = form ? (pending > 0 ? "attention" : "done") : draft === null ? "pending" : "attention";
      summary = form ? `양식 ${done}/${done + pending}` : hasDraft ? "초안 있음" : draft === null ? "초안 없음" : "초안은 사업계획서 칸에서 확인";
    } else if (step.key === "check") {
      // 점검은 «남은 확인 사항»만 센다. 0건이어도 마지막 사람 확인은 남아 있다.
      // KPI 「원문 확인 필요 조건」(미확인 조건 수)과 다른 것을 센다 — 점검 목록의 줄 수다 (SUP-26).
      status = pending > 0 ? "attention" : "done";
      summary = pending > 0 ? `점검 목록 ${pending}줄` : "점검 목록 없음";
    } else {
      const total = done + pending;
      status = total === 0 ? "pending" : pending > 0 ? "attention" : "done";
      // 45차 M6 — 전체 보기 띠(「확인 6 조항 없음 6」)와 같은 수 · 조항 없음도 적는다(쉬운 보기는 「확인 필요 0건」만 보였다)
      const absent = stat?.absent ?? 0;
      summary = total === 0 && absent === 0 ? "항목 없음" : `확인 ${done}건 · 확인 필요 ${pending}건${absent ? ` · 공고문에 조항 없음 ${absent}건` : ""}`;
    }

    return {
      id: (index + 1) as WorkflowStage,
      key: step.key,
      label: stepLabel(step.key),
      status,
      summary,
    };
  });
}

/**
 * 7단계 기준 진행률 (0~1).
 *
 * 「확인 필요」는 완료가 아니다 — 입찰과 같은 판정 함수(`isStepSettled`)를 쓴다.
 * 화면의 진행바는 `SUPPORT_VOCABULARY.centerProgress` 가 null 을 돌려 **그리지 않는다**
 * (아무 단계도 실행한 적이 없는데 0% 막대를 그리면 「실행했는데 0」으로 읽힌다).
 * 이 값은 그래프 구조를 채우기 위한 것이다.
 */
export function supportProgress(steps: WorkflowStepView[]): number {
  if (steps.length === 0) return 0;
  return steps.filter(isStepSettled).length / steps.length;
}

/**
 * 노드 id → 어느 단계인가. 노드를 누르면 본문이 그 단계로 간다.
 *
 * 중앙 코어(지원사업)는 «어느 단계도 아니다» → null. 1단계로 보내면 코어를 누를 때마다
 * 보고 있던 단계가 신청자격으로 되돌아간다.
 */
/**
 * 단계 → 그 단계를 대표하는 3D 노드. `supportStepOfNodeId` 의 반대 방향이다.
 *
 * 오른쪽에서 단계를 고르면 3D 에서도 그 노드와 경로가 강조되어야 «같은 것을 보고 있다»는 게
 * 전달된다. 예전에는 단계를 고르면 3D 선택이 통째로 풀려서 두 화면이 서로 다른 곳을 가리켰다.
 *
 * id 규칙의 주인은 supportGraph.ts 다. 값을 import 하면 순환(graph→steps→graph)이 되므로
 * 여기서는 같은 규칙을 적어 둔다 — 규칙을 바꾸려면 두 파일을 함께 고쳐야 한다.
 */
export function supportNodeIdOfStep(step: SupportStepKey): string {
  if (step === "draft") return PROPOSAL_NODE_ID;
  if (step === "check") return AUDIT_NODE_ID;
  if (step === "evidence") return "reqgroup:sup-basis";
  return `reqgroup:sup-${step}`;
}

export function supportStepOfNodeId(nodeId: string): SupportStepKey | null {
  if (nodeId === PROPOSAL_NODE_ID) return "draft";
  if (nodeId === AUDIT_NODE_ID) return "check";
  // id 규칙의 주인은 supportGraph.ts 다. 값을 import 하면 순환(graph→steps→graph)이 되므로
  // 여기서는 «같은 규칙»을 읽기만 한다 — 규칙을 바꾸려면 두 파일을 함께 고쳐야 한다.
  if (nodeId === "reqgroup:sup-basis") return "evidence";
  if (nodeId.startsWith("ev:")) return "evidence";
  if (nodeId.startsWith("finding:sup-")) return "check";

  const group = /^reqgroup:sup-(.+)$/.exec(nodeId);
  if (group) return planKeyOf(group[1]);

  const item = /^req:sup-([a-z]+)-/.exec(nodeId);
  if (item) return planKeyOf(item[1]);

  return null;
}

function planKeyOf(raw: string): SupportStepKey | null {
  return (PLAN_KEYS as readonly string[]).includes(raw) ? (raw as PlanKey) : null;
}

/**
 * 단계 → 3D 초점. 입찰 모드의 `focus`(DashboardShell.tsx:1249)에 대응하는 지원사업판이다.
 *
 * 왜 필요했나: 단계를 넘겨도 3D 가 따라오지 않았다(ISSUE-110). `highlightNodeIds` 가
 * 늘 빈 집합이라 어느 노드도 밝아지지 않았고, `cameraPreset` 이 "overview" 로 고정이라
 * 카메라도 제자리였다. 본문은 「제출서류」인데 3D 는 여전히 신청자격을 가리켰다.
 *
 * 노드를 고르는 규칙을 여기서 다시 쓰지 않는다 — `supportStepOfNodeId` 가 이미 id 규칙의
 * 유일한 독자다. 그 함수를 그래프 전체에 돌려 «이 단계에 속한 노드»를 모은다. 규칙이
 * 바뀌어도 한 곳만 고치면 양방향이 같이 맞는다.
 */
export interface SupportFocus {
  nodeIds: Set<string>;
  cameraPreset: CameraPreset;
  /** 3D 아래 자막. 오른쪽 「현재 보는 단계」와 **같은 말**이어야 한다. */
  caption: string;
}

/**
 * 단계별 카메라.
 *
 * 1~4 단계의 묶음은 같은 고리 위에 있어서 프리셋만으로는 구별되지 않는다 — 그쪽은
 * `focusNodeId` 가 고리의 다른 자리로 카메라를 돌리고, 여기서는 고리 전체를 담는
 * 프리셋을 준다. 5·6·7 은 높이가 다른 층(근거 궤도 · 사업계획서 · 점검)이라 프리셋이
 * 곧 눈에 보이는 이동이 된다.
 */
const STEP_CAMERA: Record<SupportStepKey, CameraPreset> = {
  eligibility: "notice",
  conditions: "requirements",
  schedule: "requirements",
  documents: "requirements",
  evidence: "evidence",
  draft: "proposal",
  check: "audit",
};

export function supportFocusOfStep(
  step: SupportStepKey,
  graph: Pick<CosmosGraph, "nodes" | "links">,
): SupportFocus {
  const nodeIds = new Set<string>();
  for (const node of graph.nodes) {
    if (supportStepOfNodeId(node.id) === step) nodeIds.add(node.id);
  }

  // 6단계는 «사업계획서와 그 근거»가 한 덩어리다. 근거 노드는 5단계 소속이라
  // 위 걸러내기에 안 잡히므로, 사업계획서에 이어진 것만 따로 더한다.
  if (step === "draft") {
    for (const link of graph.links) {
      if (link.source === PROPOSAL_NODE_ID) nodeIds.add(link.target);
      else if (link.target === PROPOSAL_NODE_ID) nodeIds.add(link.source);
    }
  }

  return { nodeIds, cameraPreset: STEP_CAMERA[step], caption: stepCaption(step) };
}

/** 3D 자막 — 단계 이름과 «지금 무엇이 밝은가»를 한 줄로. */
function stepCaption(step: SupportStepKey): string {
  const label = stepLabel(step);
  if (step === "evidence") return `${label} — 회사 자료와 이어진 근거를 밝힙니다`;
  if (step === "draft") return `${label} — 사업계획서와 그 근거를 밝힙니다`;
  if (step === "check") return `${label} — 신청 전 확인할 항목을 밝힙니다`;
  return `${label} — 이 단계의 조건 묶음과 항목을 밝힙니다`;
}
