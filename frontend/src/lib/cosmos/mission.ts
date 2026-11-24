/**
 * Mission Control 요약 계산 — 상단 KPI, 주요 위험, 다음 행동.
 *
 * 모든 값은 CosmosGraph(실제 API 결과 또는 데모 시나리오)에서만 계산한다.
 * backend가 주지 않는 수치는 만들지 않고 `value: null` + 상태 문구("분석 전", "미실행")로 남긴다.
 */

import { blockingText, eligibilityGateView, gateCounts, pendingSidesText } from "@/lib/cosmos/eligibilityGate";
import type { SourceKind } from "@/components/ui/SourceBadge";
import type { Tone } from "@/lib/cosmos/theme";
import { DECISION_LABELS, labelOf, reviewPriorityText } from "@/lib/scoreNames";
import { COMPANY_EVIDENCE, DECISION_READ_FAILED, GENERAL_GUIDE_NOTE, NO_EVIDENCE, SUBMIT_OUTSIDE_LINE, UNDECIDED } from "@/lib/terms";
import { semanticFitOf, type SemanticFitView } from "@/types/procurement";
import type { ItemType, Requirement } from "@/types/rfp";

import { URGENCY_LABELS, daysUntil, deadlineTerm, formatDDay, urgencyTierOf } from "@/lib/deadline";
import { CANDIDATE_TIER_LABELS, CONDITION_STATUS_LABELS, ELIGIBILITY_LABELS, SEVERITY_LABELS, eligibilityTallyText, seriousText } from "./format";
import { runStamp, withRunStamp, type RunStampKey } from "./runStamp";
import { ITEM_TYPE_LABELS, ITEM_TYPE_ORDER, displayCodeOf, groupCounts, itemTypeOf, mandatoryCount } from "./itemTypes";
import {
  auditSource,
  conditionsSource,
  decisionSource,
  eligibilitySource,
  evidenceSource,
  fitSource,
  parseSource,
  proposalSource,
  type Provenance,
} from "./provenance";
import {
  AUDIT_NODE_ID,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  evidenceRunState,
  findingTypeLabel,
  landingStage,
  requirementNodeId,
  type CosmosGraph,
  type FindingView,
  type WorkflowStage,
} from "./graph";

// ---------------------------------------------------------------------------
// KPI
// ---------------------------------------------------------------------------

export type MissionMetricKey = "fit" | "eligibility" | "conditions" | "tasks" | "requirements" | "evidence" | "risk" | "draft" | "decision";

interface MissionMetricBase {
  key: MissionMetricKey;
  /** 영문 원래 이름 (Bid Fit 등) — 보조 표기 */
  label: string;
  /** 표시 값. null이면 아직 계산되지 않은 것 (hint에 사유) */
  value: string | null;
  unit?: string;
  hint: string;
  tone: Tone;
  source: SourceKind;
  ratio: number | null;
  /** 클릭 시 이동할 단계 */
  stage: WorkflowStage;
  /** 클릭 시 선택할 노드 (없으면 단계만 이동) */
  nodeId: string | null;
  /** 한국어 이름을 값에 맞춰 바꿀 때만 (없으면 METRIC_KO_LABELS) */
  koLabel?: string;
}

export interface MissionMetric extends MissionMetricBase {
  /** 한국어 우선 이름 ("우리 회사 적합도") */
  koLabel: string;
  /** 값의 출처 문구 ("합성 시나리오 고정값" 등) — SourceBadge 라벨 */
  sourceLabel: string;
  /** 기본으로 보이는 5개인지 (나머지는 「상세 지표」) */
  primary: boolean;
}

/** 한국어 우선 이름. 코드·API 필드는 바꾸지 않는다. */
export const METRIC_KO_LABELS: Record<MissionMetricKey, string> = {
  fit: "우리 회사 적합도",
  eligibility: "입찰 참가 가능 여부",
  conditions: "놓치면 안 되는 조건",
  tasks: "수행할 과업",
  requirements: "요구사항",
  evidence: `${COMPANY_EVIDENCE}가 붙은 요구사항`,
  draft: "필수 요구사항 반영",
  risk: "제출 전 발견된 문제",
  // 다른 세 화면(목록·레이더·요구사항 정리표)이 「결정 …」/「결정 전」으로 적는다. 같은 값에
  // 다른 이름을 두지 않는다 (0920 §4-B 완료 조건 · §3-12).
  decision: "결정",
};

/**
 * 반영 막대 · 배지 · 안내의 분모 이름 (UI c) — 점검을 돌렸으면 분모는 점검이 본 요구사항(평가 항목도 배점 · 서식 안내가
 * 아니면 셈 · 백엔드 `is_reference_requirement`)이라 정리표 「필수」와 수가 다르다. 같은 이름 「필수」로 두 수를 부르지 않는다.
 * 6 · 7단계 · /plan 의 본문 기준 수(같은 함수)도 「점검 대상 요구사항」 — 한 개념 한 이름.
 */
export function coverageNoun(graph: CosmosGraph): string {
  return graph.source.analysis.audit ? "점검 대상 요구사항" : "필수 요구사항";
}

const PRIMARY_KEYS: ReadonlySet<MissionMetricKey> = new Set(["fit", "eligibility", "conditions", "evidence", "risk"]);

/**
 * 이 공고의 적합도를 AI 의미 매칭으로 «실제로 쟀는가».
 * 데모 시나리오는 고정값이므로 보지 않는다. backend 가 값을 주기 전에는 null 이다.
 */
function semanticFit(graph: CosmosGraph): SemanticFitView | null {
  const { scenario, notice } = graph.source;
  if (scenario) return null;
  return semanticFitOf(notice, notice.recommendation);
}

function provenanceOf(key: MissionMetricKey, graph: CosmosGraph): Provenance {
  switch (key) {
    case "fit": {
      // 점수가 «나온» 경우에만 출처를 바꾼다. 못 쟀으면 지금까지처럼 키워드 규칙 배지다.
      const semantic = semanticFit(graph);
      return semantic?.measured ? { kind: "computed", label: semantic.methodLabel } : fitSource(graph);
    }
    case "eligibility":
      return eligibilitySource(graph);
    case "conditions":
      return conditionsSource(graph);
    case "tasks":
    case "requirements":
      return parseSource(graph);
    case "evidence":
      // 칩도 KPI 값 · 5단계 본문과 같은 `evidenceRunState` 하나를 본다(provenance.evidenceSource · ISSUE-166).
      // 예전에는 hasScenario 만 봐서 연결을 돌려 완료된 실공고도 칩이 「미실행」이었다.
      return evidenceSource(graph);
    case "draft":
      return proposalSource(graph);
    case "risk":
      return auditSource(graph);
    case "decision":
    default:
      return decisionSource(graph);
  }
}

/**
 * 근거 연결이 **돌아갔지만 아무것도 붙지 않은** 사유. 없으면 null(= 아직 안 돌렸다).
 *
 * 서버는 `evidence_summary.note` 에 사람이 읽을 사유를 담아 준다 —
 * 「AI 검색 설정이 잘못되었습니다…」, 「승인·색인된 회사자료가 없습니다…」 같은 것.
 */
export function evidenceNote(graph: CosmosGraph): string | null {
  // 규칙은 `graph.ts` 의 `evidenceRunState` 하나다 — RFP 분석 화면도 같은 것을 본다
  // (0920 §4-B-5 · ISSUE-078). 여기서 다시 적으면 두 화면이 또 갈린다.
  return evidenceRunState(graph).failureNote;
}

/**
 * 저장된 결과를 쓰는 KPI 와 그 실행 시각이 들어 있는 자리 (0923 §3-3 · ISSUE-093).
 *
 * 문구는 `runStamp` 한 곳에서만 만든다 — 같은 사실을 KPI·노드 상세·8단계 레일이
 * **같은 말로** 적어야 담당자가 세 곳을 견주지 않는다.
 */
const METRIC_RUN_STAMP: Partial<Record<MissionMetricKey, RunStampKey>> = {
  evidence: "evidence",
  risk: "audit",
  conditions: "conditions",
};

function decorate(base: MissionMetricBase, graph: CosmosGraph): MissionMetric {
  const prov = provenanceOf(base.key, graph);
  const stampKey = METRIC_RUN_STAMP[base.key];
  const stamp = stampKey ? runStamp(graph.source.analysis, stampKey) : null;
  return {
    ...base,
    hint: stamp ? withRunStamp(base.hint, stamp) : base.hint,
    source: prov.kind,
    sourceLabel: prov.label,
    koLabel: base.koLabel ?? METRIC_KO_LABELS[base.key],
    primary: PRIMARY_KEYS.has(base.key),
  };
}

export function missionMetrics(graph: CosmosGraph, reviewPriority: number | null = null): MissionMetric[] {
  const { scenario, analysis, notice, parse } = graph.source;

  // 1. Bid Fit — 세 갈래다: 데모 시나리오 고정값 / AI 의미 매칭으로 잰 점수 / 키워드 등급뿐.
  // 의미 매칭 값이 오지 않으면(임베딩을 쓸 수 없는 환경 포함) 셋째 갈래로 떨어져 화면이 그대로다.
  const semantic = semanticFit(graph);
  /*
   * 같은 공고가 목록·레이더에서는 「검토 우선순위 69」로 보이는데 대시보드만 다른 숫자를
   * 말하고 있었다(데모면 82, 실공고면 키워드 등급 글자). 이름을 뺏지 않고 **함께 적는다** —
   * 「우리 회사 적합도」는 «이 공고가 우리 일인가»이고, 검토 우선순위는 «먼저 볼 순서»다.
   *
   * 힌트 **맨 앞**에 둔다 — 힌트 칸은 한 줄로 잘리는데 끝에 붙이면 긴 사유 뒤에서 숫자가 잘려
   * 목록의 「검토 우선순위 83」이 대시보드에서는 보이지 않았다 (27차 UNI-13).
   */
  const priorityLead = reviewPriority === null ? "" : `${reviewPriorityText(reviewPriority)} · `;
  const fit: MissionMetricBase = scenario
    ? {
        key: "fit",
        label: "Bid Fit",
        value: String(Math.round(scenario.semantic_match.fit_score * 100)),
        unit: "/ 100",
        hint: `${priorityLead}${scenario.semantic_match.label} · ${scenario.semantic_match.matched_domains[0] ?? ""}`,
        tone: "ok",
        source: "demo",
        ratio: scenario.semantic_match.fit_score,
        stage: 2,
        nodeId: NOTICE_NODE_ID,
      }
    : semantic?.measured && semantic.score !== null
      ? {
          key: "fit",
          label: "Bid Fit",
          value: String(Math.round(semantic.score * 100)),
          unit: "/ 100",
          // 사유는 backend 가 만든 한국어 문장을 그대로 쓴다 — 「회사의 어느 사업영역과 가까운가」가
          // 보여야 담당자가 점수를 믿거나 물리칠 수 있다.
          hint: `${priorityLead}${semantic.reason ?? semantic.label ?? ""}`,
          tone: semantic.label === "높음" ? "ok" : semantic.label === "낮음" ? "muted" : "info",
          source: "computed",
          ratio: semantic.score,
          stage: 2,
          nodeId: NOTICE_NODE_ID,
        }
      : {
          key: "fit",
          label: "Bid Fit",
          value: notice.candidate ? CANDIDATE_TIER_LABELS[notice.candidate.tier] ?? notice.candidate.tier : null,
          // 「미실행」이라고만 적으면 «만들지 않았다»로 읽힌다. 실제로는 만들어 두었고
          // 지금 못 쓰는 것이므로, backend 가 보내는 사유(키 없음·크레딧 소진 등)를 그대로 쓴다.
          hint: notice.candidate
            ? `${priorityLead}낱말 관련도 · ${semantic?.reason ?? "AI 비교는 못 했습니다"}`
            : `${priorityLead}적합도를 아직 재지 않았습니다`,
          tone: notice.candidate?.tier === "high" ? "ok" : "muted",
          source: notice.candidate ? "computed" : "not_run",
          ratio: null,
          stage: 2,
          nodeId: NOTICE_NODE_ID,
        };

  // 2. Eligibility
  const report = analysis.eligibility;
  const eligibility: MissionMetricBase = report
    ? {
        key: "eligibility",
        label: "Eligibility",
        value: ELIGIBILITY_LABELS[report.verdict],
        // 둘째 줄은 ③ 의 두 수(22차 §4-B) — 「조항 확인 전 n · 공고 필드 확인 m」. 정거장 캡션과 같은 계산(gateCounts).
        hint: (() => {
          const view = eligibilityGateView(graph.eligibility, report.verdict);
          return view ? gateCounts(view) : eligibilityTallyText(report.counts.passed, report.counts.check, report.counts.failed);
        })(),
        tone: report.verdict === "PASS" ? "pass" : report.verdict === "FAIL" ? "fail" : "warn",
        source: "analysis",
        ratio: report.counts.total === 0 ? null : report.counts.passed / report.counts.total,
        stage: 3,
        nodeId: NOTICE_NODE_ID,
      }
    : graph.eligibility.length > 0
      ? (() => {
          const pass = graph.eligibility.filter((e) => e.status === "PASS").length;
          const fail = graph.eligibility.filter((e) => e.status === "FAIL").length;
          const check = graph.eligibility.length - pass - fail;
          return {
            key: "eligibility" as const,
            label: "Eligibility",
            value: ELIGIBILITY_LABELS[fail > 0 ? "FAIL" : check > 0 ? "CHECK" : "PASS"],
            // 시나리오 판정 줄도 같은 두 수로 (22차 §4-B).
            hint: gateCounts(eligibilityGateView(graph.eligibility)!),
            tone: (fail > 0 ? "fail" : check > 0 ? "warn" : "pass") as Tone,
            source: "demo" as const,
            ratio: pass / graph.eligibility.length,
            stage: 3 as const,
            nodeId: NOTICE_NODE_ID,
          };
        })()
      : {
          key: "eligibility",
          label: "Eligibility",
          value: null,
          hint: "자격 판정 아직 안 함",
          tone: "muted",
          source: "not_run",
          ratio: null,
          stage: 3,
          nodeId: NOTICE_NODE_ID,
        };

  // 3. Requirements
  const mandatory = mandatoryCount(graph.requirements);  // 45차 M6 — 정리표와 같은 수(참고 · 평가 뺌)
  const requirements: MissionMetricBase = parse
    ? {
        key: "requirements",
        label: "Requirements",
        value: String(graph.counts.requirements),
        unit: "건",
        // 분모를 이름으로 구분한다. 예전에는 라벨이 「필수 요구사항」인데 값은 «전체»라
        // 화면 다른 곳의 55(필수)와 설명 없이 섞였다.
        hint: `필수 ${mandatory} · 선택·조건부 · 참고 ${graph.counts.requirements - mandatory} · ${parse.page_count}p${parse.page_is_approximate ? " 근사" : ""}${parse.truncated ? " · 상한 잘림" : ""}`,
        tone: parse.truncated ? "warn" : "ok",
        source: "computed",
        ratio: null,
        stage: 4,
        nodeId: null,
      }
    : {
        key: "requirements",
        label: "Requirements",
        value: null,
        hint: "제안요청서 아직 안 읽음",
        tone: "muted",
        source: "not_run",
        ratio: null,
        stage: 4,
        nodeId: null,
      };

  // 4. Evidence coverage (Evidence Mapping은 데모 시나리오에만 있다)
  const matched = graph.requirements.filter((r) => r.displayStatus === "matched").length;
  const evidence: MissionMetricBase = graph.hasScenario
    ? {
        key: "evidence",
        label: "Evidence",
        value: `${matched}/${graph.counts.requirements}`,
        hint: `고른 근거 ${graph.counts.selectedLinks}개 · 근거 없는 요구사항 ${graph.counts.requirementsWithoutEvidence}`,
        tone: graph.counts.requirementsWithoutEvidence > 0 ? "warn" : "ok",
        source: "demo",
        ratio: graph.counts.requirements === 0 ? null : matched / graph.counts.requirements,
        stage: 5,
        nodeId: null,
      }
    : evidenceRunState(graph).status !== "not_run"
      ? {
          /**
           * 연결을 **돌렸다.** 「미실행」이라고 쓰면 담당자가 「안 돌렸구나」로 읽고 다시
           * 누른다 — 실측: 무효 키 상태에서 그렇게 보였다.
           *
           * 상태는 `evidenceRunState` 하나가 판정한다 (0922 §4-D-5 · ISSUE-090). 저장
           * 파일에 남은 옛 사유 문장을 «지금 상태»인 것처럼 내보내지 않는다 — 요구사항이
           * 바뀐 뒤라면 그것은 「이전 실행 결과」다.
           */
          key: "evidence",
          label: "Evidence",
          value: evidenceRunState(graph).label,
          hint:
            evidenceRunState(graph).status === "stale"
              ? `이전 실행 결과 — 요구사항이 바뀌었으니 다시 실행하세요${
                  evidenceNote(graph) ? ` (이전 사유: ${evidenceNote(graph)})` : ""
                }`
              : evidenceRunState(graph).status === "mixed"
                ? "가상 예시 근거가 섞여 쓰지 않습니다 — 이 회사 기준으로 제안서를 다시 만드세요"
                : evidenceRunState(graph).status === "candidates_only"
                  ? `후보 ${evidenceRunState(graph).candidateCount}문단 · 채택된 근거 없음 — 회사자료 확인 필요`
                  : evidenceRunState(graph).status === "off"
                    ? // 10-31 최종 점검 — 꺼 둠이면 옛 저장 사유(「키가 거부되었습니다」)를 싣지 않는다(「꺼 둠」 값 옆에 「실패」가 섰다)
                      "실패가 아닙니다 — 요구사항 정리표 행 상세에서 원장 후보 실적을 「채택」하세요"
                    : evidenceNote(graph) ?? `회사 근거 ${evidenceRunState(graph).groundedCount}문장 연결`,
          tone: evidenceRunState(graph).status === "done" ? "ok" : "warn",
          source: "computed",
          ratio: null,
          stage: 5,
          nodeId: null,
        }
      : {
          key: "evidence",
          label: "Evidence",
          value: null,
          hint: "회사 근거 연결 아직 안 함",
          tone: "muted",
          source: "not_run",
          ratio: null,
          stage: 5,
          nodeId: null,
        };

  // 5. Risk = Auditor 발견
  const risk: MissionMetricBase = graph.hasAudit
    ? {
        key: "risk",
        label: "Risk",
        value: String(graph.counts.findingsOpen),
        unit: graph.counts.findingsResolved > 0 ? "건 안 고침" : "건",
        hint:
          graph.counts.findings === 0
            ? "제출 전 점검에서 찾은 문제 없음"
            : graph.counts.findingsOpen === 0
              ? `찾은 문제 ${graph.counts.findings}건 모두 해결됨으로 표시`
              : `${seriousText(graph.counts.findingsHighOpen, graph.counts.findingsBlockingOpen)} · 해결 ${graph.counts.findingsResolved} · 빠진 요구사항 ${graph.coverage.missingRequirementIds.length}`,
        tone: graph.counts.findingsHighOpen > 0 ? "fail" : graph.counts.findingsOpen > 0 ? "warn" : "pass",
        source: analysis.audit ? "analysis" : "demo",
        ratio: null,
        stage: 7,
        nodeId: AUDIT_NODE_ID,
      }
    : {
        key: "risk",
        label: "Risk",
        value: null,
        hint: "제출 전 누락 점검 아직 안 함",
        tone: "muted",
        source: "not_run",
        ratio: null,
        stage: 7,
        nodeId: graph.hasProposal ? PROPOSAL_NODE_ID : null,
      };

  // 6. Draft readiness = Coverage
  //
  // 초안이 «이전 요구사항 집합» 기준이면 그때의 분모로 적는다. 예전에는 「19/56」이
  // 나왔는데, 19 는 필수 32건 기준으로 만든 문장 수이고 56 은 지금 집합의 전체
  // 건수였다. 서로 다른 기준을 나눈 값이라 아무 뜻이 없다.
  const staleProposal =
    Boolean(analysis.readiness?.blockers.includes("stale_requirements")) && analysis.proposal !== null;
  const draft: MissionMetricBase = staleProposal
    ? {
        key: "draft",
        label: "Draft",
        value: `${analysis.proposal!.requirements_with_sentence}/${analysis.proposal!.mandatory_total}`,
        hint: `이전 요구사항 기준 · 지금은 필수 ${mandatory}건 — 새 버전 필요`,
        tone: "warn",
        source: "analysis",
        ratio: null,
        stage: 6,
        nodeId: PROPOSAL_NODE_ID,
      }
    : graph.hasProposal
    ? {
        key: "draft",
        label: "Draft",
        value: `${graph.coverage.covered}/${graph.coverage.total}`,
        koLabel: `${coverageNoun(graph)} 반영`,  // 점검 뒤 분모는 점검 대상 — 정리표 「필수」와 수가 다르다 (UI c)
        hint: `${coverageNoun(graph)} ${graph.coverage.total}개 중 ${graph.coverage.covered}개에 답함 · 확인할 문장 ${graph.counts.sentencesNeedingReview}`,
        tone:
          graph.coverage.total > 0 && graph.coverage.covered === graph.coverage.total
            ? "pass"
            : graph.counts.sentencesNeedingReview > 0
              ? "warn"
              : "ok",
        source: analysis.proposal ? "analysis" : "demo",
        ratio: graph.coverage.total === 0 ? null : graph.coverage.covered / graph.coverage.total,
        stage: 6,
        nodeId: PROPOSAL_NODE_ID,
      }
    : {
        key: "draft",
        label: "Draft",
        value: null,
        hint: "제안서 초안 미생성",
        tone: "muted",
        source: "not_run",
        ratio: null,
        stage: 6,
        nodeId: null,
      };

  // 7. Critical Conditions — 규칙 탐지 + 사람의 해결 기록
  const conditionReport = analysis.conditions;
  // 43차 N8 — 제안요청서를 안 읽은 0은 「없음」이 아니라 「아직 모름」(큰 숫자 0 · 통과색을 내지 않는다)
  const conditionsUnread = conditionReport !== null && conditionReport !== undefined && !conditionReport.requirements_available && conditionReport.counts.total === 0;
  const conditions: MissionMetricBase = conditionReport && !conditionsUnread
    ? {
        key: "conditions",
        label: "Conditions",
        value:
          conditionReport.counts.blocker > 0
            ? `참가 차단 ${conditionReport.counts.blocker}`
            : String(conditionReport.counts.action + conditionReport.counts.check),
        unit: conditionReport.counts.blocker > 0 ? undefined : "건",
        // 큰 숫자와 같은 모집단(탐지된 조건)으로 센다 — 예전 둘째 줄은 요구사항 유형별 수라 합이 맞지 않았다 (DSH-13).
        hint: `${CONDITION_STATUS_LABELS.BLOCKER} ${conditionReport.counts.blocker} · ${CONDITION_STATUS_LABELS.ACTION} ${conditionReport.counts.action} · ${CONDITION_STATUS_LABELS.CHECK} ${conditionReport.counts.check} · ${CONDITION_STATUS_LABELS.CLEARED} ${conditionReport.counts.cleared}`,
        tone:
          conditionReport.counts.blocker > 0
            ? "fail"
            : conditionReport.counts.action + conditionReport.counts.check > 0
              ? "warn"
              : "pass",
        source: "rule",
        ratio: null,
        stage: 3,
        nodeId: NOTICE_NODE_ID,
      }
    : {
        key: "conditions",
        label: "Conditions",
        value: null,
        hint: conditionsUnread ? "아직 모름 — 제안요청서를 아직 안 읽었습니다" : graph.hasRequirements ? "조건 아직 안 찾음" : "요구사항을 뽑은 뒤 찾습니다",
        tone: "muted",
        source: "not_run",
        ratio: null,
        stage: 3,
        nodeId: NOTICE_NODE_ID,
      };

  // 8. Tasks — 무엇을 수행 / 어떤 조건 / 무엇을 언제 제출
  const groups = groupCounts(graph.requirements);
  const tasks: MissionMetricBase = parse
    ? {
        key: "tasks",
        label: "Tasks",
        value: String(groups.perform),
        unit: "과업",
        hint: `실제 수행할 일 · 조건 ${groups.conditions + groups.submit}건은 「놓치면 안 되는 조건」`,
        tone: "ok",
        source: "computed",
        ratio: graph.counts.requirements === 0 ? null : groups.perform / graph.counts.requirements,
        stage: 4,
        nodeId: null,
      }
    : {
        key: "tasks",
        label: "Tasks",
        value: null,
        hint: "제안요청서 아직 안 읽음",
        tone: "muted",
        source: "not_run",
        ratio: null,
        stage: 4,
        nodeId: null,
      };

  // 9. Decision — 사람이 저장한 GO/HOLD/NO_GO
  const decided = analysis.decision && analysis.decision.status !== "UNREVIEWED" ? analysis.decision : null;
  // 결정을 읽지 못했으면 「결정 전」이 아니다 — 결정 칸 · 8단계와 같은 말(2.0.6 마지막 검토)
  const decision: MissionMetricBase = analysis.decisionError
    ? {
        key: "decision",
        label: "Decision",
        value: DECISION_READ_FAILED,
        hint: "새로고침해 저장된 결정을 다시 읽으세요",
        tone: "warn",
        source: "failed",
        ratio: null,
        stage: 8,
        nodeId: null,
      }
    : decided
    ? {
        key: "decision",
        label: "Decision",
        // 저장 값(GO·HOLD·NO_GO)을 그대로 찍고 있었다. 표기는 사전을 거친다 (0920 §4-B-1).
      value: labelOf(DECISION_LABELS, decided.status),
        hint: decided.reasons[0] ?? (decided.decided_by ? `${decided.decided_by} 결정` : "사유 없음"),
        tone: decided.status === "GO" ? "pass" : decided.status === "HOLD" ? "warn" : "fail",
        source: "human",
        ratio: null,
        stage: 8,
        nodeId: null,
      }
    : {
        key: "decision",
        label: "Decision",
        // 「미실행」이 아니라 **「결정 전」**이다. 결정은 실행하는 것이 아니라 내리는 것이고,
        // 다른 세 화면(목록·레이더·요구사항 정리표)과 같은 말이다 (27차 UNI-15 · lib/terms).
        value: UNDECIDED,
        hint: conditionReport && !conditionReport.gate.can_go ? "참가를 막는 조건을 해결해야 「참여」 저장 가능" : "사람이 참여·보류·참여 안 함을 저장",
        tone: "muted",
        source: "not_run",
        ratio: null,
        stage: 8,
        nodeId: null,
      };

  return [fit, eligibility, conditions, evidence, risk, tasks, requirements, draft, decision].map((m) => decorate(m, graph));
}

// ---------------------------------------------------------------------------
// 주요 위험
// ---------------------------------------------------------------------------

export interface RiskItem {
  id: string;
  tone: Tone;
  label: string;
  detail: string;
  nodeId: string | null;
  stage: WorkflowStage;
}

const TONE_RANK: Record<Tone, number> = { fail: 0, warn: 1, info: 2, demo: 3, ok: 4, pass: 5, muted: 6 };

/** 원문 데이터에서 파생한 위험 목록 (심각한 것부터). 없으면 빈 배열. */
/**
 * 발견 여러 건을 한 줄로 요약한다.
 *
 * 예전에는 「REQ-051 요구사항 누락 · REQ-052 요구사항 누락 · …」처럼 REQ 번호를 전부 이어 붙여
 * 12건이면 한 줄이 화면 밖으로 흘렀고, 같은 유형 이름이 열두 번 되풀이됐다. 담당자가 그 줄에서
 * 얻는 정보는 «무엇이 몇 건인가»뿐이므로 유형별로 묶고 번호는 앞의 몇 개만 남긴다
 * (전체 목록은 아래 상세 패널에 그대로 있다 — 지우는 것이 아니라 접는 것이다).
 */
const RISK_CODE_PREVIEW = 3;

export function findingSummaryText(
  findings: Array<{ requirement_id: string | null; finding_type: FindingView["finding_type"] }>,
  requirements: ReadonlyArray<Pick<Requirement, "display_code" | "item_type" | "requirement_id">>,
): string {
  // 10-31 최종 점검 — 발견 목록과 같은 화면 코드(정리표 코드 · lib/cosmos/reqCode 와 같은 displayCodeOf). 저장 id(REQ-030)를
  // 그대로 이어 한 항목이 「REQ-030」 · 「SPC-030」 둘로 보였다. reqCode.tsx 는 JSX 라 순수 모듈에서 부르지 않는다.
  const codes = new Map(requirements.map((req) => [req.requirement_id, displayCodeOf(req)]));
  const byType = new Map<string, string[]>();
  for (const f of findings) {
    const key = findingTypeLabel(f.finding_type);
    const list = byType.get(key) ?? [];
    list.push(f.requirement_id ? (codes.get(f.requirement_id) ?? f.requirement_id) : "초안");
    byType.set(key, list);
  }
  return [...byType.entries()]
    .map(([label, codes]) => {
      const shown = codes.slice(0, RISK_CODE_PREVIEW).join(", ");
      const rest = codes.length - RISK_CODE_PREVIEW;
      return `${label} ${codes.length}건 (${shown}${rest > 0 ? ` 외 ${rest}건` : ""})`;
    })
    .join(" · ");
}

export function riskSummary(graph: CosmosGraph, nowMs: number | null = null): RiskItem[] {
  const items: RiskItem[] = [];
  const { notice, analysis, parse } = graph.source;

  if (nowMs !== null) {
    // 용어와 경계 값은 `lib/deadline` 이 정한다 (0920 §4-B-5 · ISSUE-078). 예전에는
    // 「마감 경과」라는 다섯 번째 용어를 여기서만 쓰고, 임박 경계 3 도 레이더(3/7/14)와
    // 따로 적어 두었다.
    const days = daysUntil(notice.deadline_at, nowMs);
    const tier = urgencyTierOf(days, false);
    if (tier === "closed" && days !== null) {
      items.push({
        id: "deadline",
        tone: "fail",
        label: deadlineTerm({ source: "g2b", closed: true, deadline: notice.deadline_at }),
        detail: "입찰 마감이 지났습니다. 참여할 수 없습니다.",
        nodeId: NOTICE_NODE_ID,
        stage: 1,
      });
    } else if (tier === "urgent") {
      items.push({
        id: "deadline",
        tone: "warn",
        label: `${URGENCY_LABELS.urgent} ${formatDDay(days)}`,
        detail: "제출 서류와 검토 일정을 우선 확인해야 합니다.",
        nodeId: NOTICE_NODE_ID,
        stage: 1,
      });
    }
  }

  const report = analysis.conditions;
  if (report && report.counts.blocker > 0) {
    const blockers = report.conditions.filter((c) => c.status === "BLOCKER");
    items.push({
      id: "conditions-blocker",
      tone: "fail",
      label: `참가를 막는 조건 ${blockers.length}건`,
      detail: `${blockers.map((c) => c.title).slice(0, 4).join(", ")} — 담당자가 「해결됨」으로 처리하기 전에는 「참여」를 저장할 수 없습니다`,
      nodeId: blockers[0]?.requirement_id ? requirementNodeId(blockers[0].requirement_id) : NOTICE_NODE_ID,
      stage: 3,
    });
  }
  const overdue = analysis.checklist?.counts.overdue ?? 0;
  if (overdue > 0) {
    items.push({
      id: "actions-overdue",
      tone: "warn",
      label: `기한 지난 체크리스트 ${overdue}건`,
      detail: "Action Checklist에서 완료 여부와 근거를 기록하세요.",
      nodeId: NOTICE_NODE_ID,
      stage: 3,
    });
  }

  // 참가자격은 **첫 줄**이다 (20차 §4-D-3) — 안 맞으면 입찰 신청 자체를 못 한다. 아래에서 맨 앞으로 옮긴다.
  const gate = eligibilityGateView(graph.eligibility, analysis.eligibility?.verdict ?? null);
  if (gate?.verdict === "FAIL") {
    items.push({
      id: "eligibility-fail",
      tone: "fail",
      label: "참가할 수 없습니다 — 「참여 안 함」으로 기록하세요",
      detail: gate.blocking ? blockingText(gate.blocking) : "참가를 막는 조건이 있습니다",
      nodeId: NOTICE_NODE_ID,
      stage: 3,
    });
  } else if (gate?.verdict === "CHECK") {
    items.push({
      id: "eligibility-check",
      tone: "warn",
      label: gate.pending > 0 ? `참가자격 조항 ${gate.pending}개 확인` : `공고 기본정보 ${gate.fieldCheck}개 확인`,
      detail:
        gate.pending > 0
          ? `${pendingSidesText(gate)}${gate.fieldCheck ? ` · 기본정보 ${gate.fieldCheck}` : ""} — 3단계에서 하나씩 확인하세요`
          : gate.total > 0
            ? `조항 ${gate.total}개는 다 봤습니다 — 3단계 「공고 기본정보 확인」의 확인 필요 줄이 남았습니다`
            : "공고문 참가자격 조항을 읽지 못했습니다 — 공고 기본정보와 공고문을 직접 확인하세요",
      nodeId: NOTICE_NODE_ID,
      stage: 3,
    });
  }

  if (parse?.truncated) {
    items.push({
      id: "truncated",
      tone: "warn",
      label: "요구사항을 앞쪽만 뽑음",
      detail: `후보 ${parse.candidate_count ?? "?"}건 중 ${parse.count}건만 담겼습니다. 반영률은 뽑아 낸 요구사항 안에서만 유효합니다.`,
      nodeId: null,
      stage: 4,
    });
  }

  // 참가 차단(critical)은 「심각도 높음」에 섞지 않는다 — 그 한 건이 나머지 전부보다 무겁다.
  // 예전에는 severity === "high" 만 세서 critical 이 이 목록에 아예 오르지 못했다.
  if (graph.hasAudit && graph.counts.findingsBlockingOpen > 0) {
    const blocking = graph.findings.filter((f) => f.severity === "critical" && !f.resolved);
    items.push({
      id: "findings-blocking",
      tone: "fail",
      label: `참가 자체가 막히는 문제 ${blocking.length}건`,
      detail: `${findingSummaryText(blocking, graph.requirements)} — 먼저 해결하지 않으면 제출해도 탈락합니다`,
      nodeId: blocking[0]?.nodeId ?? AUDIT_NODE_ID,
      stage: 7,
    });
  }
  if (graph.hasAudit) {
    const high = graph.findings.filter((f) => f.severity === "high" && !f.resolved);
    if (high.length > 0) {
      items.push({
        id: "findings-high",
        tone: "fail",
        // 「심각」은 탈락 위험을 포함하는 말이다(「그중 심각」 · 31차 R30-30) — 탈락 위험 줄이 따로 있으면 「말고도」(32차 R31-21)
        label: `${graph.counts.findingsBlockingOpen > 0 ? `${SEVERITY_LABELS.critical} 말고도 ` : ""}${SEVERITY_LABELS.high} ${high.length}건 안 고침`,
        detail: findingSummaryText(high, graph.requirements),
        nodeId: high[0]?.nodeId ?? AUDIT_NODE_ID,
        stage: 7,
      });
    }
  }
  // 담당자가 해결 처리한 누락 항목은 위험 목록에서 뺀다 (Auditor Coverage 수치 자체는 그대로다).
  const resolvedMissing = new Set(
    graph.findings
      .filter((f) => f.resolved && f.finding_type === "missing_requirement" && f.requirement_id)
      .map((f) => f.requirement_id as string),
  );
  const openMissing = graph.coverage.missingRequirementIds.filter((id) => !resolvedMissing.has(id));
  if (graph.hasAudit && openMissing.length > 0) {
    items.push({
      id: "coverage-missing",
      tone: "warn",
      label: `제안서에 빠진 요구사항 ${openMissing.length}건${resolvedMissing.size > 0 ? ` (해결 ${resolvedMissing.size}건 뺌)` : ""}`,
      // REQ 번호를 늘어놓지 않는다 — 6개만 적어도 읽히지 않고, 무엇을 해야 하는지도
      // 알 수 없다. 유형별로 몇 건인지 적고, 원시 번호는 상세 패널에서 본다.
      detail: byTypeSummary(graph, openMissing),
      nodeId: requirementNodeId(openMissing[0]),
      stage: 7,
    });
  }

  const checkReqs = graph.requirements.filter((r) => r.displayStatus === "check");
  if (checkReqs.length > 0) {
    items.push({
      id: "req-check",
      tone: "warn",
      label: `확인 필요 요구사항 ${checkReqs.length}건`,
      detail: byTypeSummary(graph, checkReqs.map((r) => r.requirement_id)),
      nodeId: checkReqs[0].nodeId,
      stage: 4,
    });
  }
  if (graph.hasScenario && graph.counts.requirementsWithoutEvidence > 0) {
    const missing = graph.requirements.filter((r) => r.evidence.length === 0);
    items.push({
      id: "no-evidence",
      tone: "warn",
      label: `근거 없는 요구사항 ${missing.length}건`,
      detail: `${byTypeSummary(graph, missing.map((r) => r.requirement_id))} ${NO_EVIDENCE} — 자동 충족 처리하지 않음`,
      nodeId: missing[0]?.nodeId ?? null,
      stage: 5,
    });
  }
  if (graph.hasProposal && graph.counts.sentencesNeedingReview > 0) {
    items.push({
      id: "needs-review",
      tone: "warn",
      label: `확인 필요 문장 ${graph.counts.sentencesNeedingReview}건`,
      detail: "회사 근거 없이 쓴 문장은 자동 확정하지 않습니다.",
      nodeId: PROPOSAL_NODE_ID,
      stage: 6,
    });
  }
  if (!analysis.eligibility && !graph.source.scenario) {
    items.push({ id: "elig-not-run", tone: "info", label: "자격 판정 아직 안 함", detail: "3단계 「다시 판정」을 누르면 공고 기본정보와 제안요청서 자격조항으로 참가 가능 여부를 계산합니다.", nodeId: NOTICE_NODE_ID, stage: 3 });
  }

  items.sort((a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone]);
  const first = items.findIndex((item) => item.id === "eligibility-fail" || item.id === "eligibility-check");
  if (first > 0) items.unshift(...items.splice(first, 1));
  return items.slice(0, 5);
}

// ---------------------------------------------------------------------------
// 다음 행동
// ---------------------------------------------------------------------------

export type NextActionKind =
  /** 참가자격 종합 불가 — 참여 대신 「참여 안 함」을 기록한다 (22차) */
  | "eligibility_fail"
  /** 확인 전 참가자격 조항이 남았다 — 3단계 체크리스트에서 하나씩 (22차) */
  | "clauses"
  /** 참가를 막는 조건(BLOCKER)이 남았다 (22차) */
  | "blockers"
  | "parse"
  | "eligibility"
  | "conditions"
  | "proposal"
  /** 초안이 이전 요구사항 집합 기준이다 — 새 판을 만들어야 한다 */
  | "regenerate_proposal"
  | "audit"
  | "decision"
  | "review"
  | "done";

export interface NextAction {
  kind: NextActionKind;
  label: string;
  detail: string;
  stage: WorkflowStage;
  nodeId: string | null;
}

/** 파이프라인에서 아직 실행되지 않은 첫 단계들 (최대 3개). */
/**
 * 요구사항 번호 목록을 «유형별 건수»로 바꾼다.
 *
 * 「REQ-025, REQ-026, REQ-027, REQ-029, REQ-030」은 상단 한 줄에 늘어놓아도
 * 읽히지 않고 무엇을 해야 하는지도 알려 주지 않는다. 「제출 7건 · 참가자격 4건」이면
 * 담당자가 바로 다음 일을 안다. 원시 번호는 상세 패널에서 본다.
 */
function byTypeSummary(graph: CosmosGraph, requirementIds: string[]): string {
  if (requirementIds.length === 0) return "";
  const wanted = new Set(requirementIds);
  const counts = new Map<ItemType, number>();
  for (const req of graph.requirements) {
    if (!wanted.has(req.requirement_id)) continue;
    const type = itemTypeOf(req);
    counts.set(type, (counts.get(type) ?? 0) + 1);
  }
  const parts = ITEM_TYPE_ORDER.filter((t) => counts.has(t)).map(
    (t) => `${ITEM_TYPE_LABELS[t]} ${counts.get(t)}건`,
  );
  return parts.length > 0 ? parts.join(" · ") : `${requirementIds.length}건`;
}

/**
 * 화면을 열었을 때 **기본으로 펼칠 단계**.
 *
 * 「다음 할 일」과 **같은 값**이어야 한다. 예전에는 등장 애니메이션이 끝나면 언제나 8단계가
 * 열려서, 진행 현황이 2/8 인 공고에서도 오른쪽에 최종 검토가 떠 있었다. 담당자는 그것을
 * 「지금이 8단계」로 읽었다.
 *
 * 우선 조치가 있으면 그 단계를, 없으면 아직 끝내지 못한 첫 단계를 연다.
 * 완료 판정은 진행 현황(n/8)과 같은 `isStepSettled` 하나만 쓴다.
 */
export function landingStageOf(graph: CosmosGraph): WorkflowStage {
  const first = nextActions(graph)[0];
  if (first) return first.stage;
  return landingStage(graph.steps);
}

export function nextActions(graph: CosmosGraph): NextAction[] {
  const actions: NextAction[] = [];

  /* 막는 것이 먼저다 (22차 · prompt_12 §4-A) — 자격 불가 → 조항 확인 → 조건 차단 → … → 최종 결정.
     사람이 할 일이 ③ 에 있으면 등장 내려앉기(`landingStageOf`)와 「지금 할 일」의 「다음」이 ③ 을 가리킨다.
     문구는 `riskSummary` 의 같은 항목과 같다 — 「지금 할 일」은 이 둘을 한 줄로 합친다(TodayPanel). */
  const gate = eligibilityGateView(graph.eligibility, graph.source.analysis.eligibility?.verdict ?? null);
  // 「참여 안 함」을 이미 저장했으면 막는 것 셋은 할 일이 아니다 — 그 결정이 답이다 (22차 검토).
  const declined = graph.source.analysis.decision?.status === "NO_GO";
  if (!declined && gate?.verdict === "FAIL") {
    actions.push({
      kind: "eligibility_fail",
      label: "참가할 수 없습니다 — 「참여 안 함」으로 기록하세요",
      detail: gate.blocking ? blockingText(gate.blocking) : "참가를 막는 조건이 있습니다",
      stage: 3,
      nodeId: NOTICE_NODE_ID,
    });
  } else if (!declined && gate && gate.pending > 0) {
    actions.push({
      kind: "clauses",
      label: `참가자격 조항 ${gate.pending}개 확인`,
      detail: `${pendingSidesText(gate)} — 3단계 체크리스트에서 하나씩 「충족 확인 · 미충족 · 보류」로 표시하세요`,
      stage: 3,
      nodeId: NOTICE_NODE_ID,
    });
  }
  const conditionReport = graph.source.analysis.conditions;
  if (!declined && conditionReport && conditionReport.counts.blocker > 0) {
    const blockers = conditionReport.conditions.filter((c) => c.status === "BLOCKER");
    actions.push({
      kind: "blockers",
      label: `참가를 막는 조건 ${blockers.length}건`,
      detail: `${blockers.map((c) => c.title).slice(0, 4).join(", ")} — 담당자가 「해결됨」으로 처리하기 전에는 「참여」를 저장할 수 없습니다`,
      stage: 3,
      // 「해결됨」 처리는 3단계 개요의 조건 체크리스트에만 있다 — 요구사항 상세(해결 단추 없음)가 아니라 개요로 (EZ-02 · DTL-04 와 같은 한 줄).
      nodeId: null,
    });
  }

  // 가장 먼저 말해야 하는 것 — 초안이 이전 요구사항 기준이면, 그 아래 숫자는
  // 전부 «다른 기준끼리 견준 값»이다. 이것을 맨 위에 두지 않으면 담당자가
  // 늘어난 요구사항을 자기 초안의 결함으로 읽는다.
  const readiness = graph.source.analysis.readiness;
  if (readiness && readiness.blockers.includes("stale_requirements")) {
    actions.push({
      kind: "regenerate_proposal",
      label: "새 요구사항을 반영해 제안서 업데이트",
      detail: readiness.message,
      stage: 6,
      nodeId: PROPOSAL_NODE_ID,
    });
  }

  if (!graph.hasRequirements) {
    actions.push({
      kind: "parse",
      label: "제안요청서에서 요구사항 뽑기",
      detail: "위 「공고 분석 시작」을 누르세요. 첨부 제안요청서에서 할 일과 조건을 쪽 번호와 함께 뽑습니다.",
      stage: 4,
      nodeId: null,
    });
  }
  if (!graph.hasEligibility) {
    actions.push({
      kind: "eligibility",
      label: "참가자격 판정",
      detail: "3단계를 펼쳐 「다시 판정」을 누르세요. 애매한 조건은 「확인 필요」로 남습니다.",
      stage: 3,
      nodeId: NOTICE_NODE_ID,
    });
  }
  if (graph.hasRequirements && !graph.source.analysis.conditions) {
    actions.push({
      kind: "conditions",
      label: "참가 차단 조건 찾기",
      detail: "설명회 필참·지역제한·보증금·방문제출 같은 참가 조건을 규칙으로 찾아 체크리스트에 올립니다.",
      stage: 3,
      nodeId: NOTICE_NODE_ID,
    });
  }
  if (graph.hasRequirements && !graph.hasProposal) {
    actions.push({
      kind: "proposal",
      label: "제안서 초안 만들기 (핵심 1부분)",
      detail: "요구사항과 채택된 회사 근거만으로 문장을 만들고 근거 없는 문장은 「확인 필요」로 둡니다.",
      stage: 6,
      nodeId: null,
    });
  }
  if (graph.hasProposal && !graph.hasAudit) {
    actions.push({
      kind: "audit",
      label: "제출 전 누락 점검",
      detail: "초안을 제안요청서 원문과 맞춰 보고 빠진 요구사항 · 틀린 숫자 · 근거 없는 문장을 찾습니다.",
      stage: 7,
      // 제안서 상세에는 점검 칸이 없다 — 7단계 개요의 「제출 전 점검」 칸으로 연다 (DTL-04).
      nodeId: null,
    });
  }
  // 결정을 읽지 못했으면 「결정하세요」로 잠긴 단추에 보내지 않는다 — 결정 칸이 「새로고침」을 안내한다(2.0.6)
  if (
    graph.hasAudit &&
    !graph.source.analysis.decisionError &&
    (!graph.source.analysis.decision || graph.source.analysis.decision.status === "UNREVIEWED")
  ) {
    actions.push({
      kind: "decision",
      label: "참여 · 보류 · 참여 안 함 결정",
      detail: "사유와 함께 저장합니다. 참가를 막는 조건이 남아 있으면 「참여」는 저장되지 않습니다.",
      stage: 8,
      nodeId: NOTICE_NODE_ID,
    });
  }
  if (graph.hasAudit && !graph.reviewDecision) {
    actions.push({
      kind: "review",
      label: "담당자 최종 검토",
      detail:
        graph.counts.findingsOpen > 0
          ? `점검에서 찾은 문제 ${graph.counts.findingsOpen}건(그중 ${seriousText(
              graph.counts.findingsHighOpen,
              graph.counts.findingsBlockingOpen,
            )})을 원문과 대조해 「해결됨」으로 표시하거나 보류하세요`
          : graph.counts.findings > 0
            ? `찾은 문제 ${graph.counts.findings}건을 모두 해결됨으로 표시했습니다. 근거를 다시 본 뒤 승인 또는 보류를 고르세요.`
            : "찾은 문제가 없어도 담당자가 승인해야 낼 수 있는 상태가 됩니다.",
      stage: 8,
      nodeId: AUDIT_NODE_ID,
    });
  }
  // 결정을 읽지 못했으면 「검토 승인 완료」로 끝났다고 하지 않는다(2.0.6)
  if (actions.length === 0 && graph.reviewDecision && !graph.source.analysis.decisionError) {
    actions.push({
      kind: "done",
      label: graph.reviewDecision === "approved" ? "검토 승인 완료" : "다시 검토 — 수정 권고 반영 뒤 다시 봄",
      // 실공고 · 검토 승인 · 참여(GO)일 때만 「어디서 · 무엇을」까지(31차 §3-B · 32차 R31-12 — 보류 · 참여 안 함에도
      // 「나라장터에서 직접 냅니다」라고 했다) + 일반 절차 꼬리. 그 밖에는 옛 문장.
      detail:
        graph.source.origin.kind === "real" && graph.reviewDecision === "approved" && graph.source.analysis.decision?.status === "GO"
          ? `${SUBMIT_OUTSIDE_LINE} (${GENERAL_GUIDE_NOTE})`
          : "시스템은 자동 제출하지 않습니다. 최종 제출은 담당자가 합니다.",
      stage: 8,
      nodeId: null,
    });
  }
  return actions.slice(0, 3);
}
