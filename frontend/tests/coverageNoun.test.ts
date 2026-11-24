/**
 * 외부 점검 UI c 마무리 — 「필수 요구사항」은 정리표 「필수」와 같은 수, 점검 · 본문 기준 수는 「점검 대상 요구사항」 한 이름.
 *
 * 점검 전 반영 막대가 원시 셈(저장값 mandatory — 평가 항목 포함)을 「필수 요구사항」이라 불러 정리표 「필수」와 수가 달랐고,
 * 6 · 7단계 · /plan 은 같은 본문 기준 수를 「필수」 · 「점검 대상」 두 이름으로 불렀다.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { EMPTY_ANALYSIS, buildCosmosGraph, type CosmosSource } from "../src/lib/cosmos/graph.ts";
import { mandatoryCount } from "../src/lib/cosmos/itemTypes.ts";
import { coverageNoun } from "../src/lib/cosmos/mission.ts";

const req = (id: string, item_type: string, requirement_type = "mandatory") => ({
  requirement_id: id,
  category: item_type === "EVALUATION" ? "평가" : "과업",
  requirement_type,
  item_type,
  title: id,
  content: "내용",
  page: 1,
  source_text: "원문",
  status: "unmatched",
});

const requirements = [req("REQ-001", "TASK"), req("REQ-002", "TASK"), req("REQ-003", "SUBMISSION"), req("REQ-004", "EVALUATION"), req("REQ-005", "TASK", "optional")];

function source(audit: unknown = null): CosmosSource {
  return {
    notice: { id: "g2b-TEST-000", title: "시험 공고", agency: "기관", deadline_at: null, budget: null },
    origin: { kind: "real", source: "cached", fetchedAt: null },
    parse: { requirements, page_count: 1, document: "제안요청서.pdf", count: requirements.length },
    scenario: null,
    analysis: { ...EMPTY_ANALYSIS, audit },
  } as unknown as CosmosSource;
}

describe("반영 막대 분모 이름 (UI c)", () => {
  it("점검 전 「필수 요구사항」은 정리표 「필수」와 같은 수 — 평가 항목은 세지 않는다", () => {
    const graph = buildCosmosGraph(source());
    assert.equal(coverageNoun(graph), "필수 요구사항");
    assert.equal(graph.coverage.total, mandatoryCount(requirements as never));
    assert.equal(graph.coverage.total, 3);
  });

  it("점검 뒤는 점검 분모를 「점검 대상 요구사항」으로", () => {
    const audit = {
      id: "run-1",
      findings: [],
      coverage: { total: 4, covered: 2, partial: 0, missing: 2, missing_requirement_ids: [] },
      requirement_states: [],
      sentence_count: 0,
      llm_used: false,
    };
    const graph = buildCosmosGraph(source(audit));
    assert.equal(coverageNoun(graph), "점검 대상 요구사항");
    assert.equal(graph.coverage.total, 4);
  });

  it("본문 기준 수(초안 mandatory_total)를 「필수」로 부르는 글이 남지 않는다 · 지원사업 원장 후보는 「미채택」이라 하지 않는다", () => {
    const src = (...parts: string[]) => readFileSync(join(import.meta.dirname, "..", "src", ...parts), "utf8");
    assert.match(src("components", "cosmos", "DetailPanel.tsx"), /점검 대상 요구사항 \{generated\.mandatory_total\}건/);
    // 11-03 — /plan 입찰 초안은 요구사항 한 줄 = 문장 한 줄이 아니라 제안요청서 목차대로 쓴다(요구사항 수를 세지 않음)
    assert.doesNotMatch(src("app", "plan", "page.tsx"), /필수 요구사항 \{doc/);
    assert.doesNotMatch(src("lib", "cosmos", "mission.ts"), /필수 요구사항\(본문 기준\)/);
    assert.doesNotMatch(src("lib", "cosmos", "support", "supportSteps.ts"), /원장 후보 \$\{ledger\}건\(미채택\)/);
  });
});

describe("쉬운 보기 분석 단추 · 점검 문장 수 (P1-01 · UI d)", () => {
  const src = (...parts: string[]) => readFileSync(join(import.meta.dirname, "..", "src", ...parts), "utf8");

  it("쉬운 보기 4단계 안내는 「이 칸 바로 위」 단추를 가리킨다 — 단추가 없는 화면 맨 위를 찾게 했다", () => {
    const detail = src("components", "cosmos", "DetailPanel.tsx");
    assert.match(detail, /embedded\s*\?\s*"제안요청서를 아직 읽지 않았습니다\. 이 칸 바로 위 「공고 분석 시작」 단추/);
    assert.match(detail, /embedded\s*\?\s*"제안요청서 첨부를 아직 읽지 않았습니다 — 4단계를 펼쳐 「공고 분석 시작」/);
    // 분석 전에는 채운 단추 · 분석 뒤 「공고 다시 분석」은 테두리 단추 그대로
    assert.match(src("components", "cosmos", "SimpleDashboard.tsx"), /className=\{graph\.counts\.requirements > 0 \? LINE_BUTTON : BIG_BUTTON\}/);
  });

  it("7단계 점검 줄에 점검 문장 수(6단계와 셈이 다른 수)를 다시 싣지 않는다", () => {
    const detail = src("components", "cosmos", "DetailPanel.tsx");
    assert.doesNotMatch(detail, /run\.sentence_count\}문장/);
    assert.doesNotMatch(detail, /셈법이 다름/);
  });
});
