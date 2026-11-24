/**
 * 요구사항 정리표 「회사 근거 연결」 한 벌 (27차 §3-F · RFP-01 · 03 · 05 · 07).
 *
 * RFP-01(높음 · ISSUE-162): 실공고의 옛 공개 초안이 합성 근거를 인용했을 뿐인데 「합성 데모 공고라 합성 회사자료로 …」
 * 문장이 붙었다. 그 문장은 합성 데모 공고에서만 나와야 한다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { rfpEvidenceView, runDateText } from "../src/components/opportunities/requirementEvidenceView.ts";
import type { CosmosGraph } from "../src/lib/cosmos/graph.ts";

interface ProposalStub {
  generated_at?: string | null;
  legacy_result?: boolean;
  evidence_grounded_count?: number;
  evidence_summary?: Record<string, unknown> | null;
}

function graphOf(opts: { demo: boolean; proposal: ProposalStub | null; stale?: boolean }): CosmosGraph {
  return {
    hasScenario: opts.demo,
    source: {
      origin: opts.demo ? { kind: "demo" } : { kind: "real", source: "cached", fetchedAt: null },
      analysis: {
        proposal: opts.proposal,
        readiness: opts.stale ? { blockers: ["stale_requirements"] } : null,
      },
    },
  } as unknown as CosmosGraph;
}

const LEGACY_SYNTHETIC: ProposalStub = {
  generated_at: "2026-09-04T00:53:09Z",
  legacy_result: true,
  evidence_grounded_count: 2,
  evidence_summary: { used_document_count: 0, synthetic_evidence_used: true, real_evidence_used: false, note: "레거시 공개 결과 — 현재 조직의 내부 분석 결과가 아직 없어 표시" },
};

describe("rfpEvidenceView", () => {
  it("RFP-01: 실공고에 옛 합성 인용 → 합성 데모 공고 문장이 아니라 「합성 근거가 섞인 이전 결과」", () => {
    const view = rfpEvidenceView(graphOf({ demo: false, proposal: LEGACY_SYNTHETIC }));
    assert.equal(view.demo, false);
    assert.equal(view.mode, "old");
    assert.doesNotMatch(view.note, /가상 예시 공고/);
    assert.match(view.note, /가상 예시 근거가 섞인 이전 결과/);
    assert.match(view.note, /다시 만드세요/);
  });

  it("RFP-01: 합성 데모 공고는 그대로 합성 회사자료 연결 · 행별 연결 있음", () => {
    const view = rfpEvidenceView(graphOf({ demo: true, proposal: { evidence_grounded_count: 17, evidence_summary: null } }));
    assert.equal(view.demo, true);
    assert.equal(view.mode, "ran");
    assert.equal(view.rowLinks, true);
    assert.match(view.note, /가상 예시 공고라 가상 예시 회사자료/);
  });

  it("RFP-03: 합성 인용 없는 레거시 공개 결과 → 연결 실패가 아니라 근거 연결 전", () => {
    const view = rfpEvidenceView(
      graphOf({
        demo: false,
        proposal: { legacy_result: true, evidence_grounded_count: 0, evidence_summary: { synthetic_evidence_used: false, real_evidence_used: false, note: "레거시 공개 결과 — …" } },
      }),
    );
    assert.equal(view.mode, "not_run");
    assert.match(view.note, /이 회사 기준 근거 연결 결과가 없습니다/);
  });

  it("RFP-05: 붙은 문장 0 · 사유 없음 → 대시보드처럼 근거 연결 전(「실분석」 아님)", () => {
    const view = rfpEvidenceView(
      graphOf({ demo: false, proposal: { evidence_grounded_count: 0, evidence_summary: { used_document_count: 3, real_evidence_used: true, synthetic_evidence_used: false, note: null } } }),
    );
    assert.equal(view.mode, "not_run");
  });

  it("RFP-05: 요구사항이 바뀐 뒤 결과 → 이전 결과", () => {
    const view = rfpEvidenceView(
      graphOf({ demo: false, stale: true, proposal: { evidence_grounded_count: 3, evidence_summary: { used_document_count: 2, real_evidence_used: true, note: null } } }),
    );
    assert.equal(view.mode, "old");
  });

  it("RFP-07: 옛 실패 사유에 실행 날짜를 붙인다", () => {
    const view = rfpEvidenceView(
      graphOf({
        demo: false,
        proposal: { generated_at: "2026-09-16T08:39:46Z", evidence_grounded_count: 0, evidence_summary: { real_evidence_used: false, synthetic_evidence_used: false, note: "키가 거부되었습니다" } },
      }),
    );
    assert.equal(view.mode, "failed");
    assert.match(view.note, /키가 거부되었습니다 \(9월 16일 실행 결과\)/);
    assert.equal(runDateText("잘못된 값"), null);
  });

  it("RFP-04: 실공고 연결 완료는 행별 연결 없음 · KPI 는 문장 수", () => {
    const view = rfpEvidenceView(
      graphOf({ demo: false, proposal: { evidence_grounded_count: 4, evidence_summary: { used_document_count: 3, real_evidence_used: true, note: null } } }),
    );
    assert.equal(view.mode, "ran");
    assert.equal(view.rowLinks, false);
    assert.equal(view.kpiValue, "4문장");
  });
});
