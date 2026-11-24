/**
 * 값의 출처 문구 — 화면 어디서나 같은 규칙으로 만든다.
 * "실데이터"라고만 쓰지 않는다: 합성 RFP를 규칙 파서로 실제 파싱한 값은 「합성 RFP 실제 파싱」이다.
 */

import type { SourceKind } from "@/components/ui/SourceBadge";

// graph.ts 도 이 파일을 부른다(parseSourceLabel) — 둘 다 함수 선언이라 부를 때 풀려 순환이 문제되지 않는다.
import { NOT_RUN_SUMMARY, evidenceRunState, type CosmosGraph } from "./graph";
import { DECISION_READ_FAILED, SYNTHETIC_COMPANY, SYNTHETIC_NOTICE, UNDECIDED } from "@/lib/terms";
import { GENERATION_METHOD_LABELS } from "./format";

export interface Provenance {
  kind: SourceKind;
  label: string;
}

/**
 * 항목(과업·요구사항) 파싱 출처 문구. 목록이 실시간이었는지 캐시였는지는 보지 않는다 — 파싱한 것은 같은 저장 첨부이고,
 * 목록 출처는 공고 배지가 이미 말한다. 예전에는 고정 모드에서 같은 파싱을 「나라장터 캐시 공고 파싱」이라 불렀다 (CMN-25).
 * (쓰는 곳 없던 공고 출처 noticeSource 는 지웠다 — 공고 배지는 SourceBadge noticeSourceKind 가 정한다.)
 */
export function parseSourceLabel(graph: CosmosGraph): string {
  const { origin, parse } = graph.source;
  if (!parse) return "아직 안 읽음";
  return origin.kind === "demo" ? "가상 예시 공고 첨부에서 뽑음" : "공고 첨부에서 뽑음";
}

/**
 * 제안요청서가 첨부에 없어 입찰공고문에서 뽑았을 때 한 줄 (27차 §3-A-4) — /rfp KPI 와 대시보드 4단계(두 보기)가 같은 글.
 * 공고문에는 과업 세부 요구사항이 없는 경우가 많다. 표가 짧은 이유를 사람이 알아야 한다.
 */
export const NOTICE_DOCUMENT_WARNING =
  "제안요청서가 첨부에 없어 입찰공고문에서 뽑았습니다. 과업 세부 요구사항은 빠져 있을 수 있습니다 — 나라장터 공고 원문의 제안요청서를 확인하세요.";

export function parsedFromNotice(graph: CosmosGraph): boolean {
  return graph.source.parse?.document_role === "notice";
}

export function parseSource(graph: CosmosGraph): Provenance {
  const { origin, parse } = graph.source;
  if (!parse) return { kind: "not_run", label: "아직 안 읽음" };
  return { kind: origin.kind === "demo" ? "demo" : "computed", label: parseSourceLabel(graph) };
}

/** 적합도 */
export function fitSource(graph: CosmosGraph): Provenance {
  const { scenario, notice } = graph.source;
  if (scenario) return { kind: "demo", label: SYNTHETIC_NOTICE };
  if (notice.candidate) return { kind: "rule", label: "낱말 기준" };
  return { kind: "not_run", label: NOT_RUN_SUMMARY };
}

/** 참가 가능 여부 */
export function eligibilitySource(graph: CosmosGraph): Provenance {
  const report = graph.source.analysis.eligibility;
  // ✓ 는 범례에서 「AI 분석」이다 — 규칙만 돌았으면 ▣ 규칙 기반 (DSH-14).
  if (report) return report.llm_used ? { kind: "analysis", label: "규칙+AI 분석" } : { kind: "rule", label: "규칙 기반 판정" };
  if (graph.eligibility.length > 0) return { kind: "demo", label: SYNTHETIC_NOTICE };
  return { kind: "not_run", label: NOT_RUN_SUMMARY };
}

/** 놓치면 안 되는 조건 */
export function conditionsSource(graph: CosmosGraph): Provenance {
  return graph.source.analysis.conditions ? { kind: "rule", label: "규칙 기반 판정" } : { kind: "not_run", label: NOT_RUN_SUMMARY };
}

/**
 * 회사 수행근거 — 합성 데모가 아니면 실행 상태 한 벌(`evidenceRunState`)을 본다 (ISSUE-166 · DTL-03).
 * 예전에는 hasScenario 만 봐서, 근거를 연결해 완료된 실공고도 칩이 「미실행」이었다. 실패는 「미실행」과 가른다 —
 * 칩이 「미실행」이면 담당자는 「안 돌렸구나」로 읽고 같은 단추를 다시 누른다.
 */
export function evidenceSource(graph: CosmosGraph): Provenance {
  if (graph.hasScenario) {
    const anyReal = graph.evidence.some((e) => e.synthetic === false);
    return { kind: "demo", label: anyReal ? "회사자료 (비식별) · 임베딩 매칭" : SYNTHETIC_COMPANY };
  }
  const run = evidenceRunState(graph);
  if (run.status === "done") return { kind: "computed", label: "회사 근거 연결" };
  if (run.status === "stale" || run.status === "mixed") return { kind: "failed", label: "이전 결과" };
  if (run.status === "not_run") return { kind: "not_run", label: NOT_RUN_SUMMARY };
  if (run.status === "off") return { kind: "not_run", label: "AI 검색 꺼 둠" };  // 45차 H5 — 실패가 아니다
  return { kind: "failed", label: "연결 실패" };
}

/** 제안서 */
export function proposalSource(graph: CosmosGraph): Provenance {
  const proposal = graph.source.analysis.proposal;
  if (proposal) return { kind: proposal.generation_method === "LLM" ? "analysis" : "rule", label: GENERATION_METHOD_LABELS[proposal.generation_method] };
  if (graph.hasProposal) return { kind: "demo", label: SYNTHETIC_NOTICE };
  return { kind: "not_run", label: NOT_RUN_SUMMARY };
}

/** 제출 전 누락 점검 */
export function auditSource(graph: CosmosGraph): Provenance {
  const audit = graph.source.analysis.audit;
  if (audit) return audit.llm_used ? { kind: "analysis", label: "규칙 + AI로 검사" } : { kind: "rule", label: "규칙으로 검사" };
  if (graph.hasAudit) return { kind: "demo", label: SYNTHETIC_NOTICE };
  return { kind: "not_run", label: NOT_RUN_SUMMARY };
}

/** 결정 */
export function decisionSource(graph: CosmosGraph): Provenance {
  const decision = graph.source.analysis.decision;
  // 결정을 읽지 못했으면 「미결정」이 아니다 — 저장된 결정이 있을 수 있다(2.0.6)
  if (graph.source.analysis.decisionError) return { kind: "failed", label: DECISION_READ_FAILED };
  return decision && decision.status !== "UNREVIEWED" ? { kind: "human", label: "사람 확인" } : { kind: "not_run", label: UNDECIDED };
}
