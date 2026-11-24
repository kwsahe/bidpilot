/**
 * 첫 화면은 사람이 할 일이 있는 첫 정거장 (22차 · prompt_12 §4-A).
 *
 * `nextActions` 는 막는 것이 먼저다 — 자격 불가 → 조항 확인 → 조건 차단 → … → 최종 결정.
 * 등장 내려앉기(`landingStageOf`)와 「지금 할 일」의 「다음」이 이 첫 줄을 따른다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { CosmosGraph } from "../src/lib/cosmos/graph.ts";
import { landingStageOf, nextActions } from "../src/lib/cosmos/mission.ts";
import type { EligibilityResult } from "../src/types/cosmos.ts";

function row(patch: Partial<EligibilityResult> & Pick<EligibilityResult, "rule_id" | "status">): EligibilityResult {
  return { label: "조항", method: "RULE", source: "근거", reason: "사유", requirement_id: null, ...patch };
}

const clause = (n: number, patch: Partial<EligibilityResult> = {}) =>
  row({ rule_id: `QUAL-TRACK-QC-0${n}`, status: "CHECK", clause_id: `QC-0${n}`, check_side: n % 2 ? "company" : "notice", ...patch });
const FIELD = row({ rule_id: "ELIG-REGISTRATION", status: "CHECK" });

/** 점검까지 끝난(결정만 남은) 공고 — 조항·조건만 바꿔 가며 본다. */
function graphWith(
  eligibility: EligibilityResult[],
  verdict: "PASS" | "CHECK" | "FAIL",
  blockers: string[] = [],
  decision: "UNREVIEWED" | "GO" | "HOLD" | "NO_GO" = "UNREVIEWED",
  reviewDecision: "approved" | "hold" | null = null,
  origin: "real" | "demo" = "real",
): CosmosGraph {
  return {
    eligibility,
    hasRequirements: true,
    hasEligibility: true,
    hasProposal: true,
    hasAudit: true,
    reviewDecision,
    counts: { findings: 0, findingsOpen: 0, findingsBlockingOpen: 0, findingsHighOpen: 0 },
    steps: [],
    source: {
      origin: origin === "real" ? { kind: "real", source: "cache", fetchedAt: null } : { kind: "demo" },
      analysis: {
        eligibility: { verdict, results: eligibility },
        conditions: {
          counts: { blocker: blockers.length },
          conditions: blockers.map((title, i) => ({ id: `C-${i}`, title, status: "BLOCKER", requirement_id: null })),
        },
        readiness: null,
        decision: { status: decision },
      },
    },
  } as unknown as CosmosGraph;
}

describe("다음 할 일 — 막는 것이 먼저", () => {
  it("확인 전 조항이 있으면 ③ 조항 확인이 첫 줄이고 첫 화면도 ③", () => {
    const graph = graphWith([clause(1), clause(2), FIELD], "CHECK");
    const actions = nextActions(graph);
    assert.equal(actions[0].kind, "clauses");
    assert.equal(actions[0].label, "참가자격 조항 2개 확인");
    assert.equal(actions[0].stage, 3);
    assert.equal(landingStageOf(graph), 3);
  });

  it("조항을 다 확인하면 조항 줄이 빠지고 지금처럼 ⑧ 최종 결정", () => {
    const met = { status: "PASS" as const, method: "HUMAN" as const, review_state: "met" as const };
    const graph = graphWith([clause(1, met), clause(2, met), FIELD], "CHECK");
    const actions = nextActions(graph);
    assert.ok(!actions.some((a) => a.kind === "clauses"));
    assert.equal(actions[0].kind, "decision");
    assert.equal(landingStageOf(graph), 8);
  });

  it("stale 은 다시 확인할 조항이다 — 확인 전으로 센다", () => {
    const graph = graphWith([clause(1, { review_state: "stale" }), clause(2, { status: "PASS", review_state: "met" })], "CHECK");
    assert.equal(nextActions(graph)[0].label, "참가자격 조항 1개 확인");
  });

  it("자격 불가 → (조항 확인 대신) 조건 차단 → 결정 순서", () => {
    const graph = graphWith([clause(1, { status: "FAIL", review_state: "unmet" }), clause(2)], "FAIL", ["현장설명회 필참"]);
    assert.deepEqual(
      nextActions(graph).map((a) => a.kind),
      ["eligibility_fail", "blockers", "decision"],
    );
    assert.equal(landingStageOf(graph), 3);
  });

  it("「참여 안 함」을 저장했으면 막는 것 셋은 할 일이 아니다 — 검토 승인까지 했으면 완료 · ⑧", () => {
    const graph = graphWith([clause(1, { status: "FAIL", review_state: "unmet" }), clause(2)], "FAIL", ["현장설명회 필참"], "NO_GO", "approved");
    assert.deepEqual(nextActions(graph).map((a) => a.kind), ["done"]);
    assert.equal(landingStageOf(graph), 8);
    // 32차 R31-12 — 「참여 안 함」에는 「나라장터에서 직접 냅니다」를 쓰지 않는다(낼 것이 없다) · 가상 예시 공고도 옛 문장
    assert.equal(nextActions(graph)[0].detail, "시스템은 자동 제출하지 않습니다. 최종 제출은 담당자가 합니다.");
    const demo = graphWith([clause(1, { status: "FAIL", review_state: "unmet" })], "FAIL", [], "NO_GO", "approved", "demo");
    assert.equal(nextActions(demo)[0].detail, "시스템은 자동 제출하지 않습니다. 최종 제출은 담당자가 합니다.");
  });

  it("실공고 · 검토 승인 · 참여(GO)일 때만 「나라장터에서 직접 냅니다」 + 일반 절차 꼬리 (32차 R31-12)", () => {
    const go = graphWith([clause(1, { status: "PASS", review_state: "met" })], "PASS", [], "GO", "approved");
    const detail = nextActions(go).find((a) => a.kind === "done")?.detail ?? "";
    assert.match(detail, /나라장터에서 담당자가 .*BidPilot 밖에서 할 일/);
    assert.ok(detail.endsWith("(일반 절차 안내 · 공고문이 우선)"), detail);
    const hold = graphWith([clause(1, { status: "PASS", review_state: "met" })], "PASS", [], "HOLD", "approved");
    assert.equal(nextActions(hold).find((a) => a.kind === "done")?.detail, "시스템은 자동 제출하지 않습니다. 최종 제출은 담당자가 합니다.");
  });

  it("조항 확인 → 조건 차단 → 결정 (세 줄까지)", () => {
    const graph = graphWith([clause(1), FIELD], "CHECK", ["보증금 납부"]);
    assert.deepEqual(
      nextActions(graph).map((a) => [a.kind, a.stage]),
      [["clauses", 3], ["blockers", 3], ["decision", 8]],
    );
  });
});
