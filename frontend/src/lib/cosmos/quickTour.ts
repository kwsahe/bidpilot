/**
 * Quick Tour — 20~30초, 3단계. 15단계 상세 튜토리얼(tutorial.ts)과 별개이며 기록도 따로 둔다
 * (`bidpilot.quicktour.v1`). 종료하면 셸이 Guided Flow 1단계로 들어간다.
 *
 * 숫자는 전부 그래프에서 읽는다. 미실행 단계는 그렇다고 말한다.
 */

import { SEVERITY_LABELS } from "./format";
import {
  AUDIT_NODE_ID,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  WORKFLOW_STEPS,
  evidenceRunSentence,
  evidenceRunState,
  type CosmosGraph,
  type WorkflowStage,
} from "./graph";
import { representativeFinding, representativeRequirement } from "./guidedFlow";
import { groupCounts } from "./itemTypes";
import type { TutorialStep } from "./tutorial";

export const QUICK_TOUR_STORAGE_KEY = "bidpilot.quicktour.v1";

const counts = (g: CosmosGraph) => groupCounts(g.requirements);

/**
 * 단계 이름은 레일과 같은 배열에서 읽는다 — 손으로 적어 두면 이름이 바뀔 때 안내만 옛 이름에 남는다.
 * 실제로 그렇게 어긋났었다: 안내는 「AI Auditor」라 불렀지만 화면 라벨은 「제출 전 누락 점검」이다.
 */
const stepLabel = (id: WorkflowStage): string => WORKFLOW_STEPS.find((s) => s.id === id)?.label ?? `${id}단계`;

export const QUICK_TOUR_STEPS: readonly TutorialStep[] = [
  {
    id: "quick-notice",
    title: "1. 공고와 과업",
    target: "stage",
    placement: "auto",
    apply: (actions, g) => {
      actions.setViewMode("3d");
      actions.setStage(4);
      actions.setCameraPreset("requirements");
      actions.selectNode(representativeRequirement(g)?.nodeId ?? NOTICE_NODE_ID);
    },
    body: [
      "지도는 공고에서 결정까지 한 길입니다 — 1 공고 정거장에서 실제 수행할 과업과 참가조건을 찾습니다.",
      (g) =>
        g.hasRequirements
          ? `4 요구사항 정거장이 그 공고에서 뽑은 항목입니다 — 과업 ${counts(g).perform}건, 조건 ${counts(g).conditions + counts(g).submit}건. 지금 정거장에만 기호와 이름표가 붙고, 나머지는 이름 알약으로 남습니다.`
          : "1 공고 정거장이 분석 대상 공고입니다. 이 공고는 아직 제안요청서를 읽지 않아 요구사항 정거장이 비어 있습니다.",
    ],
  },
  {
    id: "quick-evidence",
    title: "2. 회사 수행근거와 제안서",
    target: "stage",
    placement: "auto",
    apply: (actions, g) => {
      actions.setStage(6);
      actions.setCameraPreset("proposal");
      actions.selectNode(g.hasProposal ? PROPOSAL_NODE_ID : (representativeRequirement(g)?.nodeId ?? null));
    },
    body: [
      "승인된 회사자료를 연결해 근거가 있는 제안서 대응 문장을 만듭니다.",
      (g) =>
        g.hasScenario
          ? `6 제안서 정거장을 고르면 5 근거 정거장의 회사 수행근거(${g.counts.evidenceDocuments}종)와 4 요구사항 정거장까지 선이 보입니다. 근거가 없는 항목은 자동으로 충족 처리하지 않고 확인 필요로 남깁니다.`
          : // 실공고는 KPI · 5단계와 같은 실행 상태 한 벌 — 근거를 돌린 공고에서도 「실행되지 않았습니다」라 했다 (CMN-02 검증).
            evidenceRunState(g).status === "not_run"
            ? "이 공고에서는 회사 수행근거 연결이 아직 실행되지 않았습니다. 상단 메뉴 「회사자료」에서 자료를 등록·승인하면 연결됩니다."
            : evidenceRunSentence(evidenceRunState(g)),
    ],
  },
  {
    id: "quick-audit",
    title: `3. ${stepLabel(7)}과 사람의 결정`,
    target: "stage",
    extraTargets: ["panel-human-review"],
    placement: "auto",
    apply: (actions, g) => {
      actions.setStage(8);
      actions.setCameraPreset("audit");
      const finding = representativeFinding(g);
      actions.selectNode(g.hasAudit ? (finding?.nodeId ?? AUDIT_NODE_ID) : null);
      actions.openDetail();
    },
    body: [
      "제출 전 누락과 위험을 검사하고 최종 참여 여부는 사람이 결정합니다.",
      (g) =>
        g.hasAudit
          ? // 「높음」 집계는 참가 차단(critical)까지 함께 센다. 차단 건수를 앞에 따로 적지 않으면 그 안에 묻힌다.
            `7 점검 정거장의 경고 삼각형이 점검에서 나온 문제입니다 — 발견 ${g.counts.findings}건${
              g.counts.findingsBlockingOpen > 0 ? ` (${SEVERITY_LABELS.critical} ${g.counts.findingsBlockingOpen}건 미해결 포함)` : ""
            }, 미반영 요구사항 ${g.coverage.missingRequirementIds.length}건. 오른쪽 아래 「담당자 최종 결정」의 「검토 승인」·「다시 검토」는 사람만 누릅니다.`
          : `${stepLabel(7)}은 아직 실행되지 않았습니다. 초안을 붙여넣고 검사하면 7 점검 정거장에 문제를 보여줍니다. 최종 결정은 사람이 합니다.`,
    ],
  },
];
