/**
 * 45차 H5 — AI 검색을 꺼 둔 것은 「실패」가 아니다. 대시보드 5단계 · 정리표 · 지원사업 5단계가 같은 사실을 쓴다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { evidenceEmptyState, isLedgerMatch, SUPPORT_LEDGER_LINE } from "../src/components/support/evidenceEmpty.ts";
import { rfpEvidenceView } from "../src/components/opportunities/requirementEvidenceView.ts";
import { evidenceRunSentence, evidenceRunState, type CosmosGraph } from "../src/lib/cosmos/graph.ts";

const OFF_NOTE = "회사 근거 연결(AI 검색)은 꺼 두었습니다 — 원장 후보 실적(미채택) 40건을 규칙으로 맞췄습니다. 쓸 것을 골라 채택하세요(고르기 전에는 초안에 쓰지 않습니다).";

function graphOf(grounded: number, note: string): CosmosGraph {
  return {
    hasScenario: false,
    source: {
      origin: { kind: "real", source: "cached", fetchedAt: null },
      analysis: {
        proposal: {
          generated_at: "2026-10-24T00:00:00Z",
          evidence_grounded_count: grounded,
          evidence_summary: { used_document_count: 0, synthetic_evidence_used: false, real_evidence_used: false, note },
        },
        readiness: null,
      },
    },
  } as unknown as CosmosGraph;
}

describe("45차 H5 — AI 검색 꺼 둠", () => {
  it("대시보드 5단계: 「실패 — 붙은 근거 없음」이 아니라 「AI 검색 꺼 둠」 · 문장은 정리표에서 「채택」", () => {
    const run = evidenceRunState(graphOf(0, OFF_NOTE));
    assert.equal(run.status, "off");
    assert.match(run.label, /AI 검색 꺼 둠/);
    assert.doesNotMatch(evidenceRunSentence(run), /붙은 근거가 없습니다/);
    assert.match(evidenceRunSentence(run), /정리표 행 상세에서 「채택」/);
  });

  it("채택한 원장 실적이 초안에 쓰이면(grounded > 0) 「완료」", () => {
    assert.equal(evidenceRunState(graphOf(3, OFF_NOTE)).status, "done");
  });

  it("진짜 실패(키 거부)는 그대로 실패", () => {
    assert.equal(evidenceRunState(graphOf(0, "회사 수행근거 연결에 실패했습니다. AI 검색 키가 거부되었습니다.")).status, "failed_key");
  });

  it("정리표: mode off · 「붙이기 실패」가 아니다", () => {
    const view = rfpEvidenceView(graphOf(0, OFF_NOTE));
    assert.equal(view.mode, "off");
    assert.match(view.note, /실패가 아닙니다/);
    assert.equal(view.kpiValue, "AI 검색 꺼 둠");
  });

  it("지원사업 5단계: 배지 「AI 검색 꺼 둠」 · 원장 후보는 쪽 · 유사도 없이", () => {
    assert.equal(evidenceEmptyState(OFF_NOTE).badge, "AI 검색 꺼 둠");
    assert.equal(evidenceEmptyState("회사 수행근거 연결에 실패했습니다.").badge, "근거 검색 실패");
    assert.equal(isLedgerMatch({ evidence_id: "ledger-3" }), true);
    assert.equal(isLedgerMatch({ evidence_id: "CD-001" }), false);
  });

  it("외부 점검 P1-03 — 지원사업 5단계는 채택이 없다: 입찰용 사유 글은 숨기고 초안이 실제로 하는 일을 적는다", () => {
    const off = evidenceEmptyState(OFF_NOTE, true);
    assert.equal(off.showNote, false);
    assert.doesNotMatch(off.body, /채택하세요|근거 문장으로 쓰지 않습니다/);
    assert.match(off.body, /수행 실적 후보/);
    assert.doesNotMatch(SUPPORT_LEDGER_LINE, /채택/);
    assert.match(SUPPORT_LEDGER_LINE, /이 화면에서는 고르지 않습니다/);
    assert.match(SUPPORT_LEDGER_LINE, /수행 실적 후보/);
  });
});
