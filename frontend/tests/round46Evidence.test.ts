/**
 * 46차 H5 — 45차 전 초안(옛 사유 글)에도 「AI 검색 꺼 둠」. 지금 상태는 서버 값(`evidence_summary.ai_search_off`)으로 가른다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { evidenceEmptyState } from "../src/components/support/evidenceEmpty.ts";
import { rfpEvidenceView } from "../src/components/opportunities/requirementEvidenceView.ts";
import { evidenceRunState, type CosmosGraph } from "../src/lib/cosmos/graph.ts";

const OLD_NO_SETTING = "AI 검색 설정이 없어 회사 수행근거 연결을 건너뜁니다.";
const OLD_KEY = "회사 수행근거 연결에 실패했습니다. AI 검색 키가 거부되었습니다.";

function graphOf(note: string, aiSearchOff: boolean | undefined): CosmosGraph {
  return {
    hasScenario: false,
    source: {
      origin: { kind: "real", source: "cached", fetchedAt: null },
      analysis: {
        proposal: {
          generated_at: "2026-10-11T00:00:00Z",
          evidence_grounded_count: 0,
          evidence_summary: {
            used_document_count: 0,
            used_chunk_count: 0,
            synthetic_evidence_used: false,
            real_evidence_used: false,
            note,
            ...(aiSearchOff === undefined ? {} : { ai_search_off: aiSearchOff }),
          },
        },
        readiness: null,
      },
    },
  } as unknown as CosmosGraph;
}

describe("46차 H5 — 옛 사유 글 + 지금 꺼짐 → 「AI 검색 꺼 둠」", () => {
  for (const note of [OLD_NO_SETTING, OLD_KEY]) {
    it(`대시보드 · 정리표: 「${note.slice(0, 14)}…」 + 꺼짐 → off`, () => {
      assert.equal(evidenceRunState(graphOf(note, true)).status, "off");
      const view = rfpEvidenceView(graphOf(note, true));
      assert.equal(view.mode, "off");
      assert.equal(view.kpiValue, "AI 검색 꺼 둠");
    });
    it(`지원사업 5단계: 「${note.slice(0, 14)}…」 + 꺼짐 → 배지 「AI 검색 꺼 둠」`, () => {
      assert.equal(evidenceEmptyState(note, true).badge, "AI 검색 꺼 둠");
    });
  }

  it("켜져 있는데 실패 → 실패(대시보드 · 정리표 · 지원사업)", () => {
    assert.equal(evidenceRunState(graphOf(OLD_KEY, false)).status, "failed_key");
    assert.equal(rfpEvidenceView(graphOf(OLD_KEY, false)).mode, "failed");
    assert.notEqual(evidenceEmptyState(OLD_KEY, false).badge, "AI 검색 꺼 둠");
  });

  it("값이 없는 옛 응답은 사유 글 낱말 그대로(옛 판과 같음)", () => {
    assert.equal(evidenceRunState(graphOf(OLD_KEY, undefined)).status, "failed_key");
    assert.equal(evidenceRunState(graphOf("회사 근거 연결(AI 검색)은 꺼 두었습니다 — 원장 후보에서 고르세요.", undefined)).status, "off");
  });
});
