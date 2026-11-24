/**
 * 묶음으로 접힌 항목도 상세는 열린다 (ISSUE-161 · DTL-01) · 회사 근거 칩은 실행 상태 한 벌 (ISSUE-166 · DTL-03).
 *
 * 요구사항 25건 · 발견 10건 이상이면 지도는 묶음만 그려 원시 노드가 `nodeById` 에 없다. 목록 행은 그 id 로
 * 고르므로 상세 패널이 `nodeById` 만 보면 단계 개요로 떨어졌다 — 실공고 대부분(발견 60 · 요구사항 60)에서.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPTY_ANALYSIS,
  buildCosmosGraph,
  detailNodeOf,
  evidenceRunState,
  findingNodeId,
  requirementNodeId,
  type CosmosSource,
} from "../src/lib/cosmos/graph.ts";
import { evidenceSource } from "../src/lib/cosmos/provenance.ts";

const requirements = Array.from({ length: 30 }, (_, i) => ({
  requirement_id: `REQ-${String(i + 1).padStart(3, "0")}`,
  category: "과업",
  requirement_type: "mandatory",
  title: `요구사항 ${i + 1}`,
  content: "내용",
  page: 1,
  source_text: "원문",
  status: "unmatched",
}));

const findings = Array.from({ length: 12 }, (_, i) => ({
  id: `AF-${i + 1}`,
  finding_type: "missing_requirement",
  severity: i === 0 ? "critical" : "medium",
  requirement_id: requirements[i].requirement_id,
  evidence_id: null,
  source_page: 1,
  source_text: "원문",
  proposal_text: null,
  recommendation: "문장 추가",
}));

function source(proposal: unknown = null, demo = false): CosmosSource {
  return {
    notice: { id: "g2b-TEST-000", title: "시험 공고", agency: "기관", deadline_at: null, budget: null },
    origin: demo ? { kind: "demo" } : { kind: "real", source: "cached", fetchedAt: null },
    parse: { requirements, page_count: 3, document: "제안요청서.pdf", count: 30 },
    scenario: null,
    analysis: {
      ...EMPTY_ANALYSIS,
      proposal,
      audit: {
        id: "run-1",
        findings,
        coverage: { total: 30, covered: 18, partial: 0, missing: 12, missing_requirement_ids: [] },
        requirement_states: [],
        sentence_count: 0,
        llm_used: false,
      },
    },
  } as unknown as CosmosSource;
}

describe("상세 패널 노드 — 발견 12 · 요구사항 30", () => {
  const graph = buildCosmosGraph(source());

  it("지도는 묶음만 그린다 — 원시 요구사항 · 발견 노드가 nodeById 에 없다", () => {
    assert.equal(graph.cluster.requirementsClustered, true);
    assert.equal(graph.cluster.findingsClustered, true);
    assert.equal(graph.nodeById.has(requirementNodeId("REQ-030")), false);
    assert.equal(graph.nodeById.has(findingNodeId("AF-1")), false);
  });

  it("발견 행 id 로 발견 상세 노드를 찾는다", () => {
    const node = detailNodeOf(graph, findingNodeId("AF-1"));
    assert.equal(node?.kind, "finding");
    assert.equal(node?.stage, 7);
    assert.equal(node?.findingId, "AF-1");
    assert.equal(node?.state, "warning");
    assert.ok(graph.findingByNodeId.get(node!.id), "상세 본문이 같은 id 로 발견을 찾는다");
  });

  it("요구사항 행 id 로 요구사항 상세 노드를 찾는다", () => {
    const node = detailNodeOf(graph, requirementNodeId("REQ-030"));
    assert.equal(node?.kind, "requirement");
    assert.equal(node?.stage, 4);
    assert.equal(node?.requirementId, "REQ-030");
    assert.ok(graph.requirementByNodeId.get(node!.id));
  });

  it("그린 노드는 그대로 · 모르는 id 와 선택 없음은 null(개요)", () => {
    assert.equal(detailNodeOf(graph, "notice"), graph.nodeById.get("notice"));
    assert.equal(detailNodeOf(graph, "req:없는-항목"), null);
    assert.equal(detailNodeOf(graph, null), null);
  });
});

describe("회사 근거 칩 — evidenceRunState 한 벌", () => {
  const summary = (patch: object) => ({ used_document_count: 2, real_evidence_used: true, synthetic_evidence_used: false, note: null, ...patch });

  it("근거 연결이 완료된 실공고는 칩이 「미실행」이 아니다", () => {
    const graph = buildCosmosGraph(source({ evidence_grounded_count: 4, evidence_summary: summary({}), sentences: [] }));
    assert.equal(evidenceRunState(graph).status, "done");
    assert.deepEqual(evidenceSource(graph), { kind: "computed", label: "회사 근거 연결" });
  });

  it("돌렸는데 키가 거부되면 「연결 실패」(미실행과 가른다)", () => {
    const graph = buildCosmosGraph(
      source({ evidence_grounded_count: 0, evidence_summary: summary({ real_evidence_used: false, note: "키가 거부되었습니다" }), sentences: [] }),
    );
    assert.equal(evidenceRunState(graph).status, "failed_key");
    assert.equal(evidenceSource(graph).kind, "failed");
  });

  it("실공고의 예전 공개 결과는 연결 전 · 합성 근거가 섞이면 이전 결과(요구사항 정리표와 같은 말)", () => {
    const legacy = buildCosmosGraph(
      source({ legacy_result: true, evidence_grounded_count: 0, evidence_summary: summary({ real_evidence_used: false, note: "레거시 공개 결과" }), sentences: [] }),
    );
    assert.equal(evidenceRunState(legacy).status, "not_run");
    const mixed = buildCosmosGraph(
      source({ legacy_result: true, evidence_grounded_count: 3, evidence_summary: summary({ real_evidence_used: false, synthetic_evidence_used: true }), sentences: [] }),
    );
    assert.equal(evidenceRunState(mixed).status, "mixed");
    assert.equal(evidenceSource(mixed).label, "이전 결과");
  });
});
