/**
 * 지도는 「길」이다 (21차 · prompt_11 §3) — 정거장 8개 · 밝기 3단계 · 아코디언 폭 · 표시 묶음.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { WORKFLOW_STEPS, type CosmosGraph, type WorkflowStage, type WorkflowStepView } from "../src/lib/cosmos/graph.ts";
import {
  CURRENT_MARK_MAX,
  MARKER_GROUP_THRESHOLD,
  STATION_IDS,
  STATION_NAMES,
  currentStationOrder,
  stationFlag,
  stationItemCounts,
  stationLabelled,
  stationMarkers,
  stationSpans,
  stationTier,
} from "../src/lib/cosmos/stations.ts";
import type { EligibilityResult } from "../src/types/cosmos.ts";

describe("정거장", () => {
  it("여덟 개 · 레일 순서 · 짧은 이름", () => {
    assert.deepEqual(STATION_IDS, [1, 2, 3, 4, 5, 6, 7, 8]);
    assert.deepEqual(Object.values(STATION_NAMES), ["공고", "적합도", "참가 여부", "요구사항", "근거", "제안서", "점검", "결정"]);
  });

  it("짧은 이름의 낱말은 모두 레일 이름 안에 있다 — 한 단계 이름 한 벌 (27차 §3-D-9)", () => {
    for (const step of WORKFLOW_STEPS) {
      for (const word of STATION_NAMES[step.id as WorkflowStage].split(" ")) assert.ok(step.label.includes(word), `${step.id} ${word} ⊄ ${step.label}`);
    }
  });

  it("밝기는 지금 · 옆 · 나머지", () => {
    assert.equal(stationTier(4, 4), "current");
    assert.equal(stationTier(3, 4), "near");
    assert.equal(stationTier(5, 4), "near");
    assert.equal(stationTier(1, 4), "far");
    assert.equal(stationTier(8, 4), "far");
  });

  it("기호와 이름표는 지금 정거장에만 — 옆 정거장 번호 칩 · 흐린 점 없음 (27차 §3-D-1)", () => {
    assert.equal(stationLabelled("current"), true);
    assert.equal(stationLabelled("near"), false);
    assert.equal(stationLabelled("far"), false);
  });

  it("정거장 알약 낱말은 레일 상태와 같다 — 「!」 「✕」 단계만 · ③ 은 확인 전 조항 수 (27차 §3-D-2)", () => {
    const step = (id: number, status: WorkflowStepView["status"]) => ({ id, key: "x", label: "x", status, summary: "" }) as unknown as WorkflowStepView;
    for (const status of ["done", "active", "pending"] as const) assert.equal(stationFlag(step(4, status), null), null);
    assert.equal(stationFlag(step(4, "attention"), null)?.word, "확인 필요");
    assert.equal(stationFlag(step(6, "failed"), null)?.word, "실패");
    assert.equal(stationFlag(step(6, "failed"), null)?.glyph, "✕");
    assert.equal(stationFlag(undefined, null), null);
  });

  it("지금 정거장은 허브 먼저 · 판정이 나쁜 순 · 24 넘으면 23 + 칩 · 펼친 묶음은 예외 · 고른 것은 늘 그린다 (27차 §3-D-6)", () => {
    const item = (id: string, state: string, extra: object = {}) => ({ id, state, ...extra }) as { id: string; state: "ok" | "check" | "warning"; hub?: boolean; expanded?: boolean };
    const few = [item("a", "ok"), item("b", "warning"), item("hub", "ok", { hub: true }), item("c", "check")];
    assert.deepEqual(currentStationOrder(few).shown.map((i) => i.id), ["hub", "b", "c", "a"]);
    const many = Array.from({ length: 30 }, (_, i) => item(`n${i}`, i === 29 ? "warning" : "ok"));
    const cut = currentStationOrder(many);
    assert.equal(cut.shown.length, CURRENT_MARK_MAX - 1);
    assert.equal(cut.hidden, 30 - (CURRENT_MARK_MAX - 1));
    assert.equal(cut.shown[0].id, "n29");
    assert.ok(currentStationOrder(many, "n28").shown.some((i) => i.id === "n28"));
    assert.equal(currentStationOrder([...many, item("g", "ok", { expanded: true })]).hidden, 0);
  });

  it("폭은 0~1 을 빈틈없이 덮고, 지금 정거장이 가장 넓다 · 두 열이면 더 넓다", () => {
    for (const current of STATION_IDS) {
      for (const cols of [1, 2] as const) {
        const spans = stationSpans(current, cols);
        assert.equal(spans.length, 8);
        assert.equal(spans[0].x0, 0);
        assert.ok(Math.abs(spans[7].x1 - 1) < 1e-9);
        spans.forEach((span, i) => {
          assert.ok(span.x1 > span.x0);
          if (i > 0) assert.ok(Math.abs(span.x0 - spans[i - 1].x1) < 1e-9);
        });
        const widths = spans.map((s) => s.x1 - s.x0);
        const own = widths[current - 1];
        assert.ok(widths.every((w, i) => i === current - 1 || w < own));
      }
      const one = stationSpans(current, 1)[current - 1];
      const two = stationSpans(current, 2)[current - 1];
      assert.ok(two.x1 - two.x0 > one.x1 - one.x0);
    }
  });
});

function graphWith(rows: EligibilityResult[], stage8Summary = "검토 대기"): CosmosGraph {
  return {
    source: { analysis: { eligibility: { verdict: "CHECK" }, conditions: null } },
    eligibility: rows,
    proposal: null,
    steps: Array.from({ length: 8 }, (_, i) => ({
      id: (i + 1) as WorkflowStage,
      key: "review",
      label: `단계 ${i + 1}`,
      status: "pending",
      summary: i === 7 ? stage8Summary : "",
    })),
  } as unknown as CosmosGraph;
}

function clause(n: number, label: string, status: "PASS" | "CHECK" | "FAIL" = "CHECK"): EligibilityResult {
  return {
    rule_id: `QUAL-X-QC-${String(n).padStart(2, "0")}`,
    label,
    status,
    method: "RULE",
    source: "공고문",
    reason: "사유",
    requirement_id: null,
    clause_id: `QC-${String(n).padStart(2, "0")}`,
    clause_text: `조항 원문 ${n}`,
  };
}

describe("정거장 표시(marker)", () => {
  it("③ 자격은 3단계 체크리스트와 같은 줄 · 같은 순서 (공고 필드 줄은 빠진다)", () => {
    const rows = [
      { rule_id: "ELIG-REGION", label: "지역", status: "CHECK", method: "RULE", source: "", reason: "", requirement_id: null } as EligibilityResult,
      clause(1, "결격·등록 조항", "PASS"),
      clause(2, "지역 조항", "FAIL"),
    ];
    const markers = stationMarkers(graphWith(rows));
    const qual = markers.filter((m) => m.station === 3);
    assert.deepEqual(qual.map((m) => m.id), ["qual:QUAL-X-QC-02", "qual:QUAL-X-QC-01"]);
    assert.deepEqual(qual.map((m) => m.state), ["warning", "ok"]);
    assert.equal(qual[0].short, "지역 조항 QC-02");
    const decision = markers.find((m) => m.id === "decision");
    assert.equal(decision?.station, 8);
    assert.equal(decision?.shape, "target");
  });

  it(`조항이 ${MARKER_GROUP_THRESHOLD}개를 넘으면 종류별로 묶고 가장 나쁜 상태를 딴다`, () => {
    const rows = Array.from({ length: 14 }, (_, i) => clause(i + 1, i < 10 ? "결격·등록 조항" : "실적 조항", i === 12 ? "FAIL" : "CHECK"));
    const qual = stationMarkers(graphWith(rows)).filter((m) => m.station === 3);
    assert.deepEqual(
      qual.map((m) => [m.label, m.state]),
      [["자격 · 실적 조항 4건", "warning"], ["자격 · 결격·등록 조항 10건", "check"]],
    );
  });
  it("정거장 이름 아래 「n개」는 점이 아니라 항목 — 허브는 빼고 묶음은 건수로 (21차 검토)", () => {
    const rows = Array.from({ length: 14 }, (_, i) => clause(i + 1, i < 10 ? "결격·등록 조항" : "실적 조항"));
    const graph = graphWith(rows);
    const node = (id: string, kind: string, stage: number, extra: object = {}) => ({ id, kind, stage, ...extra });
    (graph as unknown as { nodes: unknown[] }).nodes = [
      node("notice", "notice", 1),
      node("rg:TASK", "requirement-group", 4, { groupCount: 30 }),
      node("rg:REQ", "requirement-group", 4, { groupCount: 5, expanded: true }),
      ...Array.from({ length: 5 }, (_, i) => node(`req:${i}`, "requirement", 4)),
      node("proposal", "proposal", 6),
      node("audit", "audit", 7),
      node("f1", "finding", 7),
      node("f2", "finding", 7),
    ];
    const markers = stationMarkers(graph);
    const counts = stationItemCounts(graph, markers);
    // ③ 조항 14줄은 묶음 점 2개지만 14건 · ④ 접힌 묶음 30 + 펼친 5 · ⑦ 허브 빼고 발견 2 · ⑧ 결정 1
    assert.deepEqual(counts, [1, 0, 14, 35, 0, 0, 2, 1]);
    assert.equal(markers.filter((m) => m.station === 3).length, 2);
  });
});
