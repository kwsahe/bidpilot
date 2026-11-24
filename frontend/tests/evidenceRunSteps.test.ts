/**
 * 5단계(회사 수행근거 연결) — 레일 · KPI · 패널이 한 판정(`evidenceRunState`)을 쓴다 (27차 §3-F · DTL 검증 R-1 · R-2).
 *
 * R-1: 실공고의 합성 근거 섞인 옛 결과에 레일은 ✓ 「1문장에 연결 (합성)」, KPI 는 「이전 결과 — 합성 근거 섞임」.
 * R-2: 돌았고 후보 3문단 · 채택 0 — 레일은 「후보 3문단 · 채택된 근거 없음」, KPI · 패널은 「미실행」.
 * 그 밖에: 참가를 막는 조건 할 일은 개요로(EZ-02) · 지원사업 6 · 7단계 이름(SUP-13 · SUP-26).
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { EMPTY_ANALYSIS, EVIDENCE_STATUS_LABELS, buildCosmosGraph, evidenceRunState, type CosmosSource } from "../src/lib/cosmos/graph.ts";
import { missionMetrics, nextActions } from "../src/lib/cosmos/mission.ts";
import { QUICK_TOUR_STEPS } from "../src/lib/cosmos/quickTour.ts";
import { buildSupportSteps, supportStepStats } from "../src/lib/cosmos/support/supportSteps.ts";
import type { PlanDraft, SupportApplicationResult } from "../src/types/opportunity.ts";

const requirements = Array.from({ length: 4 }, (_, i) => ({
  requirement_id: `REQ-00${i + 1}`,
  category: "과업",
  requirement_type: "mandatory",
  title: `요구사항 ${i + 1}`,
  content: "내용",
  page: 1,
  source_text: "원문",
  status: "unmatched",
}));

function source(proposal: unknown, patch: Record<string, unknown> = {}): CosmosSource {
  return {
    notice: { id: "g2b-TEST-000", title: "시험 공고", agency: "기관", deadline_at: null, budget: null },
    origin: { kind: "real", source: "cached", fetchedAt: null },
    parse: { requirements, page_count: 3, document: "제안요청서.pdf", count: 4 },
    scenario: null,
    analysis: { ...EMPTY_ANALYSIS, proposal, ...patch },
  } as unknown as CosmosSource;
}

const proposal = (grounded: number, summary: object | null, extra: object = {}) => ({
  evidence_grounded_count: grounded,
  evidence_summary: summary,
  sentences: [],
  ...extra,
});

function step5(src: CosmosSource) {
  const graph = buildCosmosGraph(src);
  const kpi = missionMetrics(graph).find((m) => m.key === "evidence");
  return { graph, run: evidenceRunState(graph), rail: graph.steps[4], kpi };
}

describe("5단계 한 판정 — 레일 · KPI 가 같은 말", () => {
  it("R-2: 후보 3문단 · 채택 0 → 「후보만 있음」(미실행 아님) · 레일 확인 필요", () => {
    const { run, rail, kpi } = step5(
      source(proposal(0, { used_document_count: 2, used_chunk_count: 3, real_evidence_used: true, synthetic_evidence_used: false, note: null })),
    );
    assert.equal(run.status, "candidates_only");
    assert.equal(run.label, EVIDENCE_STATUS_LABELS.candidates_only);
    assert.equal(run.candidateCount, 3);
    assert.equal(rail.status, "attention");
    assert.match(rail.summary, /후보 3문단 · 채택된 근거 없음/);
    assert.equal(kpi?.value, "후보만 있음 — 채택된 근거 없음");
    assert.match(kpi?.hint ?? "", /후보 3문단/);
  });

  it("CMN-02 검증: 30초 둘러보기 근거 단계도 같은 판정 — 근거를 돌린 실공고에서 「실행되지 않았습니다」가 아니다", () => {
    const { graph } = step5(
      source(proposal(4, { used_document_count: 2, used_chunk_count: 6, real_evidence_used: true, synthetic_evidence_used: false, note: null })),
    );
    const line = QUICK_TOUR_STEPS[1].body[1];
    assert.equal(typeof line, "function");
    const said = (line as (g: typeof graph) => string)(graph);
    assert.doesNotMatch(said, /실행되지 않았습니다/);
    assert.match(said, /4문장에 회사 근거를 연결/);
  });

  it("R-1: 실공고의 합성 근거 섞인 옛 결과 → 레일도 ✓ 가 아니라 「이전 결과 — 가상 예시 근거 섞임」", () => {
    const { run, rail, kpi } = step5(
      source(proposal(1, { used_document_count: 0, used_chunk_count: 1, real_evidence_used: false, synthetic_evidence_used: true, note: "레거시 공개 결과" }, { legacy_result: true })),
    );
    assert.equal(run.status, "mixed");
    assert.equal(rail.status, "attention");
    assert.match(rail.summary, /^이전 결과 — 가상 예시 근거 섞임/);
    assert.equal(kpi?.value, run.label);
  });

  it("연결 완료 → 레일 ✓ 「회사자료 n종 · m문장에 연결」 · KPI 「완료 m건」", () => {
    const { run, rail, kpi } = step5(
      source(proposal(4, { used_document_count: 2, used_chunk_count: 6, real_evidence_used: true, synthetic_evidence_used: false, note: null })),
    );
    assert.equal(run.status, "done");
    assert.equal(rail.status, "done");
    assert.match(rail.summary, /^회사자료 2종 · 4문장에 연결/);
    assert.equal(kpi?.value, "완료 4건");
  });

  it("후보도 사유도 없으면 연결 전 — 레일 · KPI 모두 미실행 쪽(요구사항 정리표 RFP-05 와 같은 규칙)", () => {
    const { run, rail } = step5(
      source(proposal(0, { used_document_count: 0, used_chunk_count: 0, real_evidence_used: false, synthetic_evidence_used: false, note: null })),
    );
    assert.equal(run.status, "not_run");
    assert.equal(rail.status, "pending");
  });

  it("사유가 있으면 레일 · KPI 가 같은 사유(연결 실패)", () => {
    const { run, rail, kpi } = step5(
      source(proposal(0, { used_document_count: 0, used_chunk_count: 0, real_evidence_used: false, synthetic_evidence_used: false, note: "키가 거부되었습니다" })),
    );
    assert.equal(run.status, "failed_key");
    assert.match(rail.summary, /연결 실패 — 키가 거부되었습니다/);
    assert.equal(kpi?.value, "실패 — 키 거부");
  });
});

describe("할 일 — 참가를 막는 조건은 개요(해결 처리가 있는 곳)로", () => {
  it("EZ-02: blockers 할 일의 nodeId 는 null(3단계 개요)", () => {
    const graph = buildCosmosGraph(
      source(null, {
        conditions: {
          counts: { blocker: 1, action: 0, check: 0, resolved: 0 },
          conditions: [{ id: "C-1", title: "설명회 필참", status: "BLOCKER", requirement_id: "REQ-001" }],
        },
      }),
    );
    const blockers = nextActions(graph).find((a) => a.kind === "blockers");
    assert.ok(blockers);
    assert.equal(blockers.stage, 3);
    assert.equal(blockers.nodeId, null);
  });
});

describe("지원사업 6 · 7단계 (SUP-13 · SUP-26)", () => {
  const result = {
    plan: { eligibility: [], conditions: [], schedule: [], documents: [] },
    evidence_matches: [],
    // 예전 6절 뼈대 — 본문 초안이 아니라 세지 않는다
    draft_outline: Array.from({ length: 6 }, (_, i) => ({ title: `절 ${i + 1}`, grounded: i < 2 })),
    pre_submit_checks: ["a", "b", "c"],
  } as unknown as SupportApplicationResult;
  const draftOf = (form: object | null, sections = 1) =>
    ({ sections: Array.from({ length: sections }, () => ({})), checklist: form ? { summary: "", form } : null }) as unknown as PlanDraft;
  const step = (draft?: PlanDraft | null) => {
    const steps = buildSupportSteps(result, draft);
    return { draft: steps[5], check: steps[6] };
  };

  it("저장된 양식 초안의 소항목 수로 센다 — 6절 뼈대(2/6)가 아니다", () => {
    const form = { items_filled: 5, items_total: 8, empty_items: [], tables_present: 0, tables_total: 0, tables_filled: 0 };
    assert.equal(step(draftOf(form)).draft.summary, "양식 5/8");
    assert.equal(step(draftOf(form)).draft.status, "attention");
    assert.deepEqual(supportStepStats(result, draftOf(form))[5], { key: "draft", done: 5, pending: 3 });
  });

  it("양식 수가 없으면 초안 유무만 · 초안을 모르면 세지 않는다", () => {
    assert.equal(step(draftOf(null)).draft.summary, "초안 있음");
    assert.equal(step(null).draft.summary, "초안 없음");
    assert.doesNotMatch(step(undefined).draft.summary, /목차|\d/);
    assert.equal(step(null).draft.status, "pending");
    assert.equal(step(undefined).draft.status, "attention", "초안을 모르면 「대기」로 단정하지 않는다");
    assert.deepEqual(supportStepStats(result)[5], { key: "draft", done: 0, pending: 0 });
  });

  it("7단계는 KPI 「원문 확인 필요 조건」과 다른 이름 — 점검 목록 줄 수", () => {
    assert.equal(step().check.summary, "점검 목록 3줄");
  });
});
