/**
 * 튜토리얼 모드 정의.
 *
 * 처음 보는 사람(개발자가 아니어도)이 대시보드의 각 영역을 이해하도록, 화면 요소를 하나씩 비추며
 * 설명하고 간단한 "직접 해보기" 과제를 준다. 발표 모드(presentation.ts)처럼 각 단계가 실제
 * 대시보드 상태(단계·카메라·선택 노드·뷰 모드)를 바꾼다.
 *
 * 규칙: 화면에 보이는 숫자는 전부 CosmosGraph에서 계산된 값만 쓴다 (하드코딩 금지).
 */

import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import type { CosmosViewMode } from "@/components/cosmos/types";

import { CANDIDATE_TIER_LABELS, ELIGIBILITY_LABELS, GROUNDING_LABELS, REQUIREMENT_STATUS_LABELS, SEVERITY_LABELS, formatPage } from "./format";
import {
  AUDIT_NODE_ID,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  WORKFLOW_STEPS,
  findingNodeId,
  requirementNodeId,
  sourceBadges,
  type CosmosGraph,
  type ReviewDecision,
  type StepStatus,
  type WorkflowStage,
} from "./graph";
import { PRESENTATION_SCENES, type CameraPreset } from "./presentation";
import { VERDICT_WORDS, displayCodeOf } from "./itemTypes";
import { coverageNoun } from "./mission";
import { STATION_IDS, STATION_NAMES } from "./stations";

// ---------------------------------------------------------------------------
// 비출 대상 (data-tour 속성 값)
// ---------------------------------------------------------------------------

export const TOUR_TARGETS = [
  "topbar-brand",
  "topbar-notice",
  "topbar-deadline",
  "topbar-progress",
  "topbar-view-toggle",
  "topbar-reset",
  "topbar-analyze",
  "topbar-presentation",
  "topbar-tutorial",
  "rail",
  "rail-step-1",
  "rail-step-2",
  "rail-step-3",
  "rail-step-4",
  "rail-step-5",
  "rail-step-6",
  "rail-step-7",
  "rail-step-8",
  "stage",
  "panel",
  "panel-human-review",
  "bottom-sources",
  "mission-strip",
  "caption-bar",
] as const;

export type TourTarget = (typeof TOUR_TARGETS)[number];

export type TutorialPlacement = "right" | "left" | "top" | "bottom" | "auto";

// ---------------------------------------------------------------------------
// 셸이 제공하는 동작·상태
// ---------------------------------------------------------------------------

/** 튜토리얼이 대시보드를 움직일 때 쓰는 동작 묶음 (DashboardShell이 만든다). */
export interface TutorialActions {
  setStage: (stage: WorkflowStage) => void;
  setCameraPreset: (preset: CameraPreset) => void;
  selectNode: (id: string | null) => void;
  setViewMode: (mode: CosmosViewMode) => void;
  resetView: () => void;
  startPresentation: () => void;
  /** 작은 화면에서 상세 패널(드로어)을 연다. 큰 화면에서는 아무 일도 하지 않는다. */
  openDetail: () => void;
}

/** 과제 완료 판정에 쓰는 대시보드 상태 스냅샷. */
export interface TutorialState {
  stage: WorkflowStage;
  selectedId: string | null;
  viewMode: CosmosViewMode;
  /** 사람이 고른 보기(상단 단추 · 대신 해 주기). 기본값으로 그려진 보기는 null (22차). */
  viewPicked: CosmosViewMode | null;
  reviewDecision: ReviewDecision;
  presentationActive: boolean;
}

/** 문장은 고정 문자열이거나, 그래프 수치를 넣기 위한 함수다. */
export type TutorialText = string | ((graph: CosmosGraph) => string);

export interface TutorialTask {
  instruction: TutorialText;
  isDone: (state: TutorialState, graph: CosmosGraph) => boolean;
  /** 사용자가 직접 하기 어려울 때 대신 실행해 준다 */
  doItForMe?: (actions: TutorialActions, graph: CosmosGraph) => void;
  hint?: TutorialText;
}

export interface TutorialStep {
  id: string;
  title: string;
  /** 짧은 문단 여러 개 */
  body: TutorialText[];
  bullets?: TutorialText[];
  /** 비출 요소. null이면 화면 가운데 카드만 띄운다 */
  target: TourTarget | null;
  /** target과 함께 비출 추가 요소 (스포트라이트는 합집합 사각형) */
  extraTargets?: TourTarget[];
  placement?: TutorialPlacement;
  /** 단계 진입 시 대시보드를 움직인다 — 이벤트 핸들러/타이머에서만 호출된다 */
  apply?: (actions: TutorialActions, graph: CosmosGraph) => void;
  task?: TutorialTask;
}

export function resolveText(text: TutorialText, graph: CosmosGraph): string {
  return typeof text === "string" ? text : text(graph);
}

// ---------------------------------------------------------------------------
// 헬퍼 (presentation.ts와 같은 규칙)
// ---------------------------------------------------------------------------

const checkRequirement = (graph: CosmosGraph) =>
  graph.requirements.find((r) => r.displayStatus === "check") ??
  graph.requirements.find((r) => r.displayStatus === "unmatched") ??
  null;

const firstFindingOfType = (graph: CosmosGraph, type: string) =>
  graph.findings.find((f) => f.finding_type === type) ?? graph.findings[0] ?? null;

const sampleRequirement = (graph: CosmosGraph) => graph.requirements[1] ?? graph.requirements[0] ?? null;

/**
 * 실제 나라장터 공고에는 회사 수행근거·제안서·점검 결과가 아직 없다.
 * 그 단계의 설명은 가짜 수치 대신 "미실행"임을 알리고 데모 시나리오를 안내한다.
 */
const NOT_RUN_BODY =
  "지금 선택한 공고에서는 이 단계가 아직 실행되지 않았습니다. 오른쪽 패널에서 직접 실행하거나, 상단 공고 선택기에서 「가상 예시 공고」를 고르면 이 단계가 어떻게 동작하는지 볼 수 있습니다.";

/**
 * 단계 이름을 손으로 적지 않는다.
 *
 * 안내가 «화면에 없는 글자»를 누르라고 시켰다 — 4단계를 「RFP 분석」이라 불렀지만 레일의 실제 라벨은
 * WORKFLOW_STEPS 의 「요구사항 정리」다. 이름이 바뀌면 안내만 옛 이름에 남는다. 그래서 레일과 같은
 * 배열에서 읽는다.
 */
const stepLabel = (id: WorkflowStage): string => WORKFLOW_STEPS.find((s) => s.id === id)?.label ?? `${id}단계`;

/** 「4단계 「요구사항 정리」」처럼 번호와 이름을 함께 부른다 — 접힌 레일에서는 번호가, 펼친 레일에서는 이름이 단서다. */
const stepRef = (id: WorkflowStage): string => `${id}단계 「${stepLabel(id)}」`;

/** 상태 글리프 설명도 레일과 같은 출처에서 만든다 — 예전엔 4가지만 적어 「✕ 실패」가 통째로 빠져 있었다. */
const STEP_STATUS_ORDER: readonly StepStatus[] = ["done", "active", "attention", "failed", "pending"];

const STEP_STATUS_MEANING: Record<StepStatus, string> = {
  done: "이 단계는 끝났습니다",
  active: "지금 사람의 입력을 기다리는 단계입니다",
  attention: `끝났지만 확인할 것이 남았습니다 (예: 「${REQUIREMENT_STATUS_LABELS.check}」 항목, 점검에서 나온 발견)`,
  failed: "실행했지만 실패했습니다. 오른쪽 패널에서 사유를 확인하고 다시 실행합니다",
  pending: "아직 실행되지 않았습니다. 값이 0이라는 뜻이 아닙니다",
};

/**
 * 왼쪽 레일은 데스크톱에서 **기본이 접힌 상태**다(DashboardShell). 접히면 번호도 이름도 숨고
 * 상태 동그라미만 남으므로, 「이름을 읽고 누르라」는 안내는 그대로면 어긋난다.
 * 접힌 버튼에는 `${번호}. ${이름}` 툴팁이 붙고, 머리의 「»」가 펼치기 버튼이다.
 */
const RAIL_COLLAPSED_HINT =
  "데스크톱에서 이 막대는 접혀 있는 것이 기본이라 상태 동그라미만 보입니다. 막대 위쪽 「»」를 누르면 번호와 이름이 펼쳐지고, 접힌 채로도 동그라미에 마우스를 올리면 번호와 이름이 뜹니다. 좁은 화면에서는 단계가 위쪽에 가로로 나열됩니다.";

// ---------------------------------------------------------------------------
// 단계 정의
// ---------------------------------------------------------------------------

export const TUTORIAL_STEPS: TutorialStep[] = [
  {
    id: "welcome",
    title: "BidPilot AI 둘러보기에 오신 것을 환영합니다",
    target: null,
    body: [
      "BidPilot AI는 공공기관 입찰공고(제안요청서)를 읽고 그 안의 요구사항을 하나씩 뽑아낸 뒤, 우리 회사가 실제로 가진 자료(수행실적·인력·인증 등)와 연결해 주는 도구입니다.",
      `연결된 자료를 회사 수행근거로 삼아 제안서 문장을 만들고, 마지막에는 ${stepRef(7)}이 빠진 요구사항이나 숫자가 틀린 곳을 원문과 대조해 찾아냅니다. 제출 여부는 항상 사람이 결정합니다.`,
      (g) =>
        g.hasScenario
          ? "지금 화면의 공고·회사 수행근거·제안서는 모두 연습용 가상 예시(가짜) 데이터입니다. 마음껏 눌러 봐도 아무것도 제출되지 않습니다."
          : `지금은 나라장터 실공고를 보고 있습니다. 공고와 요구사항까지만 실제 데이터이고, 회사 수행근거·제안서·${stepLabel(7)} 단계는 아직 실행되지 않았습니다. 전체 흐름은 상단 선택기의 「가상 예시 공고」에서 볼 수 있습니다. 무엇을 눌러도 제출되지 않습니다.`,
    ],
    bullets: [
      // 흐름 이름도 레일과 같은 배열에서 읽는다 — 손으로 적으면 단계 이름이 바뀔 때 여기만 남는다.
      `전체 흐름: ${WORKFLOW_STEPS.map((s) => s.label).join(" → ")}`,
      () => `소요 시간: 약 5분 (${TUTORIAL_STEPS.length}단계)`,
      "키보드: → 다음 · ← 이전 · Esc 종료",
    ],
  },
  {
    id: "topbar",
    title: "상단 바 — 지금 무엇을 보고 있나",
    target: "topbar-notice",
    extraTargets: ["topbar-deadline", "topbar-progress"],
    placement: "bottom",
    body: [
      (g) =>
        `상단에는 지금 분석 중인 공고 이름이 보입니다. 지금은 ${g.source.notice.agency}의 「${g.source.notice.title}」이며, 상단 선택기에서 다른 공고나 가상 예시 공고로 바꿀 수 있습니다.`,
      "「입찰 마감 D-n」은 입찰 마감까지 남은 날짜입니다. 7일 이하로 남으면 주황색으로 바뀌고, 지났으면 빨간 「입찰 종료」로 표시됩니다.",
      (g) =>
        `「진행 ${Math.round(g.progress * WORKFLOW_STEPS.length)}/${WORKFLOW_STEPS.length}단계」는 분석 ${WORKFLOW_STEPS.length}단계 중 끝낸 단계 수입니다. 마지막 ${stepRef(8)}은 「검토 승인」이나 「다시 검토」를 골라야 완료로 셉니다.`,
    ],
  },
  {
    id: "rail",
    title: `왼쪽 세로 막대 — 분석 ${WORKFLOW_STEPS.length}단계`,
    target: "rail",
    placement: "right",
    body: [
      `왼쪽 세로 막대는 분석이 진행되는 ${WORKFLOW_STEPS.length}단계입니다. 공고를 찾는 것부터 사람이 최종 결정하는 것까지 순서대로 놓여 있고, 앞의 동그라미가 상태를 알려줍니다.`,
      "단계를 누르면 가운데 지도에서 그 정거장에만 기호와 이름표가 붙고 카메라가 그리로 옮겨 갑니다. 나머지 일곱 정거장은 이름 알약(번호 · 이름 · 개수 · 상태 기호)으로 남고, 알약을 눌러도 그 정거장으로 갑니다.",
      RAIL_COLLAPSED_HINT,
    ],
    bullets: STEP_STATUS_ORDER.map(
      (status) => `${STEP_STATUS_META[status].glyph} ${STEP_STATUS_META[status].label} — ${STEP_STATUS_MEANING[status]}`,
    ),
    task: {
      instruction: `왼쪽 세로 막대에서 위에서 네 번째 칸(${stepRef(4)})을 눌러 보세요`,
      isDone: (state) => state.stage === 4,
      doItForMe: (actions) => {
        actions.setStage(4);
        actions.setCameraPreset("requirements");
        actions.selectNode(null);
      },
      hint: RAIL_COLLAPSED_HINT,
    },
  },
  {
    id: "notice",
    title: "1 공고 정거장 — 모든 것의 출발점",
    target: "stage",
    placement: "auto",
    apply: (actions) => {
      actions.setStage(1);
      actions.setCameraPreset("notice");
      actions.selectNode(NOTICE_NODE_ID);
    },
    body: [
      `지도는 왼쪽에서 오른쪽으로 가는 한 길입니다 — ${STATION_IDS.map((id) => STATION_NAMES[id]).join(" → ")}. 맨 왼쪽 1 공고 정거장의 점(●)이 지금 분석 중인 입찰공고입니다.`,
      "지금 정거장에만 기호와 이름표가 붙고, 나머지 정거장은 이름 알약으로 남습니다. 공고 카드에는 공고명, 발주기관, 마감일, 예산, 회사와의 적합도, 현재 단계, 진행률이 요약돼 있습니다.",
      (g) => {
        const scenario = g.source.scenario;
        if (!scenario) {
          const candidate = g.source.notice.candidate;
          return candidate
            ? `이 공고는 낱말 기준으로 고른 공고입니다 — 관련도 ${CANDIDATE_TIER_LABELS[candidate.tier] ?? candidate.tier}, 맞은 낱말 ${[...candidate.matched_ai_keywords, ...candidate.matched_work_keywords].join(", ")}. AI 의미 매칭은 아직 안 했습니다.`
            : NOT_RUN_BODY;
        }
        return `적합도 「${scenario.semantic_match.label}」는 가상 예시 공고에 미리 넣어 둔 값입니다. 실공고의 AI 의미 매칭은 켜 두었을 때만 계산합니다(새 공고 받기가 꺼져 있으면 함께 꺼 둡니다).`;
      },
      // 자격 판정 표기는 format.ts 의 사전에서 읽는다 — 화면이 한국어로 바뀐 뒤에도 안내만 「PASS / CHECK / FAIL」로 남아 있었다.
      `오른쪽 패널에는 이 공고의 자세한 정보와 참가 자격 판정(${ELIGIBILITY_LABELS.PASS} / ${ELIGIBILITY_LABELS.CHECK} / ${ELIGIBILITY_LABELS.FAIL})이 함께 보입니다. 모호한 조건은 「${ELIGIBILITY_LABELS.FAIL}」도 「${ELIGIBILITY_LABELS.PASS}」도 아닌 「${ELIGIBILITY_LABELS.CHECK}」로 남겨 사람이 봅니다.`,
    ],
  },
  {
    id: "requirements",
    title: "4 요구사항 정거장 — 제안요청서 요구사항",
    target: "stage",
    placement: "auto",
    apply: (actions) => {
      actions.setStage(4);
      actions.setCameraPreset("requirements");
      actions.selectNode(null);
    },
    body: [
      (g) =>
        g.source.parse
          ? `4 요구사항 정거장의 네모(▪)들이 제안요청서에서 뽑아낸 요구사항입니다. 제안요청서 ${g.source.parse.page_count}쪽에서 ${g.counts.requirements}건을 찾았고, 각 항목은 몇 페이지 어떤 문장에서 나왔는지 기억하고 있습니다.`
          : "이 공고의 제안요청서는 아직 읽지 않아 요구사항 정거장이 비어 있습니다. 읽고 나면 각 요구사항이 몇 페이지 어떤 문장에서 나왔는지 함께 표시됩니다.",
      "색은 판정 뜻만 가집니다 — 지도 · 목록 · 오른쪽 패널 어디서나 같은 네 색 · 네 낱말입니다.",
    ],
    bullets: [
      `회청 — ${VERDICT_WORDS.neutral}(제안요청서 원문으로 정리된 기본 상태 · 근거 없음)`,
      `청록 — ${VERDICT_WORDS.ok}(회사 수행근거가 채택되어 연결됨 · 해결됨)`,
      `호박 — ${VERDICT_WORDS.check}(후보 근거만 있음 · 사람이 판단해야 함)`,
      `빨강 — ${VERDICT_WORDS.warning}(참가를 막는 조항 · ${stepLabel(7)}에서 높음 이상 문제)`,
    ],
    task: {
      instruction: "4 요구사항 정거장의 요구사항을 아무거나 클릭해 보세요",
      isDone: (state) => state.selectedId?.startsWith("req:") ?? false,
      doItForMe: (actions, g) => {
        const req = sampleRequirement(g);
        actions.setStage(4);
        actions.selectNode(req ? requirementNodeId(req.requirement_id) : null);
      },
      hint: "점이 작아 잘 안 잡히면 「대신 해주기」를 누르거나, 상단 「목록」 뷰에서 골라도 됩니다.",
    },
  },
  {
    id: "panel",
    title: "오른쪽 상세 패널 — 근거를 읽는 곳",
    target: "panel",
    placement: "left",
    apply: (actions) => {
      actions.openDetail();
    },
    body: [
      "오른쪽 패널은 지금 선택한 것의 자세한 내용을 보여줍니다. 요구사항을 선택했다면 위에서부터 이렇게 읽으면 됩니다.",
      "회사 수행근거가 하나도 연결되지 않으면 패널에 「근거 없음」이라고 적히고, 시스템은 절대 임의로 충족 처리하지 않습니다.",
    ],
    // 패널의 실제 구획 제목을 「」 안에 그대로 옮긴다 — 화면이 「증빙」이라 쓰는 곳을 안내만 다른 말로 부르면 또 어긋난다.
    bullets: [
      "REQ 번호와 필수/선택 구분, 그리고 「제안요청서 원문」 인용과 쪽 번호. AI가 지어낸 문장이 아니라 실제 문서 위치입니다",
      "「연결된 근거」 — 이 요구사항을 뒷받침하는 회사 수행근거. 문서명·페이지·유사도와 채택/후보 여부가 보입니다",
      "「제안서 문장」 — 이 요구사항에 대응해 만들어진 문장과 그 근거 종류",
      `「제출 전 점검 판단」 — ${stepLabel(7)}이 이 요구사항에서 찾은 문제와 수정 권고`,
    ],
  },
  {
    id: "evidence",
    title: `5 근거 정거장 — ${stepLabel(5)}`,
    target: "stage",
    placement: "auto",
    apply: (actions) => {
      actions.setStage(5);
      actions.setCameraPreset("evidence");
      actions.selectNode(null);
    },
    body: [
      (g) =>
        g.hasScenario
          ? `5 근거 정거장의 문서 카드(▫)가 회사 수행근거 ${g.counts.evidenceDocuments}종입니다. 회사소개서, 수행실적, 강사 이력, 인증서 같은 문서를 뜻하며, 지금은 연습용 가상 예시 문서입니다.`
          : NOT_RUN_BODY,
      "근거는 종류와 상관없이 모두 같은 문서 카드 모양입니다 — 모양은 종류(공고·요구사항·근거·문장·발견)를, 색은 판정을 말합니다.",
      (g) =>
        g.hasScenario
          ? `근거를 하나 누르면 연결된 정거장까지 선이 보입니다 — 청록 실선은 채택(${g.counts.selectedLinks}건), 호박 점선은 확인이 필요한 후보입니다.`
          : "회사 수행근거가 연결되면 근거를 눌렀을 때 연결된 정거장까지 선이 보입니다 — 청록 실선은 채택, 호박 점선은 후보입니다.",
    ],
    task: {
      instruction: "5 근거 정거장의 회사 수행근거를 하나 눌러 보세요",
      isDone: (state) => state.selectedId?.startsWith("ev:") ?? false,
      doItForMe: (actions, g) => {
        actions.setStage(5);
        actions.selectNode(g.evidence[0]?.nodeId ?? null);
      },
      hint: "수행근거를 누르면 오른쪽 패널의 「회사 근거」에 문서 원문과 연결된 요구사항이 보입니다.",
    },
  },
  {
    id: "gap",
    title: `회사 수행근거가 부족한 요구사항 — 「${REQUIREMENT_STATUS_LABELS.check}」`,
    target: "stage",
    placement: "auto",
    apply: (actions, g) => {
      actions.setStage(5);
      actions.setCameraPreset("requirements");
      actions.selectNode(checkRequirement(g)?.nodeId ?? null);
    },
    body: [
      (g) => {
        if (!g.hasScenario) return NOT_RUN_BODY;
        const r = checkRequirement(g);
        return r
          ? `${displayCodeOf(r)} 「${r.title}」(제안요청서 ${formatPage(r.page)})는 회사 수행근거가 부족하거나 조건이 모호한 요구사항입니다.`
          : "회사 수행근거가 부족하거나 조건이 모호한 요구사항은 따로 표시됩니다.";
      },
      `이런 항목은 「${REQUIREMENT_STATUS_LABELS.check}」 상태로 남깁니다. AI가 「아마 될 것」이라고 넘겨짚어 충족 처리하지 않고, 사람에게 판단을 넘긴다는 뜻입니다.`,
      (g) =>
        g.hasScenario
          ? `지금 회사 수행근거가 전혀 없는 요구사항은 ${g.counts.requirementsWithoutEvidence}건입니다. 오른쪽 패널에서 어떤 근거가 부족한지, 어떤 메모가 달려 있는지 확인할 수 있습니다.`
          : `${stepRef(5)}을 실행하면 어떤 요구사항에 근거가 부족한지 오른쪽 패널에서 확인할 수 있습니다.`,
    ],
  },
  {
    id: "proposal",
    title: "제안서 초안 — 문장마다 근거가 붙습니다",
    target: "stage",
    placement: "auto",
    apply: (actions) => {
      actions.setStage(6);
      actions.setCameraPreset("proposal");
      actions.selectNode(PROPOSAL_NODE_ID);
    },
    body: [
      (g) =>
        g.proposal
          ? `6 제안서 정거장의 긴 막대(─)가 제안서 초안 「${g.proposal.title}」이고, 그 아래 짧은 막대가 문장입니다. 채택된 회사 수행근거만 사용해 ${g.counts.sentences}개 문장을 만들었습니다.${
              g.source.analysis.proposal ? " (실제 생성 결과)" : ""
            }`
          : "제안서 초안을 아직 만들지 않았습니다. 오른쪽 패널의 「제안서 초안 만들기」를 누르면 요구사항과 채택된 회사 수행근거만으로 초안을 만듭니다.",
      "문장마다 어디에서 온 내용인지 근거 종류가 붙어 있습니다.",
      // 화면의 막대 이름을 「제안서 반영 상태」로 바꿨으므로(DetailPanel) 안내도 같은 글자를 쓴다.
      // 안내와 화면이 다른 이름을 쓰면 담당자가 찾을 글자가 없어진다 — 그것이 이 파일의 옛 사고였다.
      // 화면 글자를 그대로 두고 뜻을 옆에 붙인다.
      (g) =>
        g.hasProposal
          ? `패널의 「${coverageNoun(g)} 반영 ${g.coverage.covered}/${g.coverage.total}건」은 ${coverageNoun(g)} ${g.coverage.total}개 중 초안이 답한 개수입니다. 빠진 것이 있으면 다음 단계인 ${stepRef(7)}이 잡아냅니다.`
          : "패널의 「필수 요구사항 반영」은 필수 요구사항 중 초안이 답한 개수입니다. 제안서 초안을 만들면 보입니다.",
    ],
    // 근거 종류 이름은 화면의 배지 문구(format.ts GROUNDING_LABELS)와 같아야 한다.
    bullets: [
      "「공고문 근거」 — 공고 원문 내용을 그대로 반영한 문장",
      "「회사 근거」 — 회사 수행근거를 바탕으로 쓴 문장",
      `「${GROUNDING_LABELS.AI_SUGGESTION}」 — 근거 없이 AI가 덧붙인 문장. 반드시 「확인 필요」 표시가 붙습니다`,
    ],
  },
  {
    id: "audit",
    title: `${stepLabel(7)} — 초안을 제안요청서 원문과 맞춰 보기`,
    target: "stage",
    placement: "auto",
    apply: (actions) => {
      actions.setStage(7);
      actions.setCameraPreset("audit");
      actions.selectNode(AUDIT_NODE_ID);
    },
    body: [
      // 「높음」 집계는 이제 참가 차단(critical)까지 함께 센다. 그래서 「심각도 높음 N건」이라고만 적으면
      // 참가 자체가 막히는 건이 그 안에 묻힌다 — 차단 건수를 앞에 따로 적는다.
      (g) =>
        g.hasAudit
          ? `7 점검 정거장의 경고 삼각형(⚠)이 ${stepLabel(7)}(오른쪽 패널에서는 「제출 전 누락 점검」)입니다. 제안서 초안을 제안요청서 원문과 거꾸로 대조해 문제 ${g.counts.findings}건을 찾았습니다 — ${
              g.counts.findingsBlocking > 0 ? `그중 ${SEVERITY_LABELS.critical} ${g.counts.findingsBlocking}건 포함 ` : ""
            }심각도 높음 이상 ${g.counts.findingsHigh}건.${g.source.analysis.audit ? " (실제 검사 결과)" : ""}`
          : `${stepLabel(7)}은 아직 실행되지 않았습니다. 오른쪽 패널에서 초안을 붙여넣고 「제출 전 점검」을 누르면 누락 요구사항을 원문과 함께 찾아냅니다.`,
      "이 점검이 찾는 문제는 다섯 가지입니다.",
      "발견을 누르면 문제가 있는 요구사항 · 회사 수행근거 정거장까지 선이 보입니다(높음 이상은 빨강 · 그 밖은 호박 점선). 발견이 많으면 원인별 묶음(⚠)으로 모이고, 묶음을 누르면 오른쪽 패널에서 하나씩 봅니다.",
    ],
    bullets: [
      "요구사항 누락 — 제안요청서에는 있는데 초안에 대응 문장이 없음",
      "수치 불일치 — 원문 숫자와 초안 숫자가 다름",
      "근거 없는 주장 — 회사 수행근거 없이 성과·수치를 단정함",
      "미확인 조건 — 수행근거로 확정할 수 없어 사람 확인이 필요함",
      "제출서류 누락 — 필수 제출서류가 목록에서 빠짐",
    ],
  },
  {
    id: "finding",
    title: "발견 항목 확인 — 원문 vs 초안 vs 권고",
    target: "stage",
    placement: "auto",
    apply: (actions) => {
      actions.setStage(7);
      actions.setCameraPreset("audit");
    },
    body: [
      "제출 전 점검 정거장의 발견을 누르면 오른쪽 패널이 세 부분으로 나뉩니다. 「어디서(페이지) 무엇이(원문) 왜(초안과 비교) 문제인지」를 한 번에 볼 수 있습니다.",
    ],
    bullets: [
      "「제안요청서 원문」 — 문제의 근거가 되는 원문과 쪽",
      "「현재 초안」 — 초안에서 해당하는 문장. 없으면 「대응 문장 없음」",
      "「수정 권고」 — 어떻게 고치면 되는지",
    ],
    task: {
      instruction: "제출 전 점검 정거장의 발견을 눌러 보세요 (오른쪽 목록에서 눌러도 됩니다)",
      isDone: (state) => state.selectedId?.startsWith("finding:") ?? false,
      doItForMe: (actions, g) => {
        const f = firstFindingOfType(g, "number_mismatch");
        actions.setStage(7);
        actions.selectNode(f ? findingNodeId(f.id) : AUDIT_NODE_ID);
      },
      hint: "7 점검 정거장의 큰 경고 삼각형을 선택하면 오른쪽 패널에 발견 목록이 나옵니다. 거기서 항목을 눌러도 같은 화면입니다.",
    },
  },
  {
    id: "review",
    title: "담당자 최종 결정 — 결정은 사람이 합니다",
    target: "panel-human-review",
    placement: "left",
    apply: (actions) => {
      actions.setStage(8);
      actions.openDetail();
    },
    body: [
      "패널 맨 아래 「담당자 최종 결정」이 마지막 단계입니다. AI가 만든 결과는 모두 참고자료이고, 제출 여부는 담당자가 결정합니다.",
      "「검토 승인」은 제출해도 된다는 담당자의 판단, 「다시 검토」는 수정 권고를 반영한 뒤 다시 보겠다는 뜻입니다. 시스템이 자동으로 제출하는 일은 없습니다. 제출은 나라장터에서 직접 하고, 순서는 8단계 「BidPilot 밖에서 할 일」에 있습니다.",
      // findingsHighOpen 은 참가 차단(critical)까지 함께 센다. 「높음」이라고만 부르면
      // «참가 자체가 막힌다»는 뜻이 그 숫자 안에 묻힌다.
      (g) =>
        g.counts.findingsHighOpen > 0
          ? `심각 문제 ${g.counts.findingsHighOpen}건이 안 고친 채 남아 있어${
              g.counts.findingsBlockingOpen > 0 ? ` (${SEVERITY_LABELS.critical} ${g.counts.findingsBlockingOpen}건 포함)` : ""
            } 승인 버튼 옆에 경고가 뜹니다. 막지는 않지만, 한 번 더 보라는 뜻입니다.`
          : "심각 문제가 남아 있으면 승인 버튼 옆에 경고가 뜹니다. 막지는 않지만, 한 번 더 보라는 뜻입니다.",
    ],
    task: {
      instruction: "「다시 검토」 또는 「검토 승인」을 눌러 보세요",
      isDone: (state) => state.reviewDecision !== null,
      hint: "언제든 다시 눌러 바꾸거나 취소할 수 있습니다. 가상 예시 공고의 검토 기록은 모든 회사가 함께 보는 연습 기록이니, 실제 판단은 실제 공고에서 하세요.",
    },
  },
  {
    id: "controls",
    // 10-31 대표 결정 — 3D 는 화면에서 뺐다. 보기 단추는 「목록 · 지도(2D)」 둘.
    title: "보기 바꾸기 — 목록과 지도, 되돌리기",
    target: "topbar-view-toggle",
    extraTargets: ["topbar-reset"],
    placement: "bottom",
    // 튜토리얼은 지도로 시작하므로(startTutorial) 「지도」를 누르라 하면 아무것도 바뀌지 않았다 — 목록으로 바꿔 보게 한다.
    body: ["튜토리얼은 지도로 보여 드리고 있습니다. 평소 기본은 단계 목록이고, 「목록」 · 「지도」로 언제든 바꿀 수 있습니다."],
    bullets: [
      "드래그 — 지도 이동",
      "Ctrl + 휠 — 확대/축소 (휠만 굴리면 페이지가 내려갑니다)",
      // 버튼 문구가 「Reset View」에서 「화면 초기화」로 바뀐 뒤에도 안내만 옛 이름을 부르고 있었다.
      "「화면 초기화」 — 지도와 선택을 처음 상태로 되돌리기 (좁은 화면에서는 숨습니다)",
      "「목록」 — 마우스 없이 키보드만으로 모든 항목을 탐색",
    ],
    task: {
      instruction: "「목록」 버튼을 눌러 보세요",
      isDone: (state) => state.viewPicked === "list",
      doItForMe: (actions) => actions.setViewMode("list"),
      hint: "다음 단계로 넘어가면 지도로 돌아옵니다.",
    },
  },
  {
    id: "presentation",
    title: "발표 모드 — 전체 흐름을 자동으로",
    target: "topbar-presentation",
    placement: "bottom",
    apply: (actions) => {
      actions.setViewMode("3d");
      actions.setStage(8);
      actions.resetView();
    },
    body: [
      // 장면 수와 이름은 presentation.ts 에서 읽는다 — 예전엔 손으로 적은 목록이라 실제 장면 이름과 달랐다.
      `「발표 모드」를 누르면 방금 본 흐름이 ${PRESENTATION_SCENES.length}개 장면으로 자동 재생됩니다. ${PRESENTATION_SCENES.map(
        // 장면 제목 앞의 「1. 」은 목록에서 번호가 겹쳐 읽히므로 떼고 이름만 잇는다.
        (s) => s.title.replace(/^\d+\.\s*/, ""),
      ).join(" → ")} 순서입니다.`,
      "재생 중에도 노드를 눌러 볼 수 있습니다. 키보드는 ← → 이동, Space 재생/정지, Esc 종료입니다.",
      "이 안내가 끝난 뒤 한 번 눌러 보세요. 1분 남짓이면 전체 흐름을 다시 볼 수 있습니다.",
    ],
  },
  {
    id: "sources",
    title: "데이터 출처 — 이 화면은 어디까지 진짜인가",
    target: "bottom-sources",
    placement: "top",
    body: [
      // 배지 개수와 문구를 손으로 적었더니 화면과 어긋났다 — 안내는 「세 개」라 했는데 실제로는 네 개가 뜬다.
      // 그래서 배지를 만드는 sourceBadges() 를 그대로 불러 읽는다.
      (g) => `화면 아래 배지 ${sourceBadges(g).length}개는 지금 보는 데이터가 어디서 왔는지 알려줍니다.`,
      (g) => `지금은 ${sourceBadges(g).map((b) => `「${b.label}」`).join(" · ")} 입니다.`,
      "실제 공고를 고르면 나라장터 실제 데이터와 이 회사가 승인한 자료가 이 자리를 대신합니다. 화면의 숫자는 모두 데이터에서 계산된 값이며, 임의로 만든 성과 수치는 없습니다.",
      "여기까지입니다. 언제든 상단 「안내 ▾」 → 「상세 튜토리얼」로 다시 볼 수 있습니다. 수고하셨습니다!",
    ],
    bullets: [
      "「실제 …」 — 실제 공고·문서·API에서 나온 값입니다",
      "「가상 예시 공고」 · 「가상 예시 회사자료」 — 흐름을 보여주기 위한 연습용 고정값입니다",
      "「아직 안 함」 — 아직 하지 않았다는 뜻입니다. 값이 0이거나 문제가 없다는 뜻이 아닙니다",
    ],
  },
];
