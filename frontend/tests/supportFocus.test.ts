/**
 * 단계 → 3D 초점 (ISSUE-110 · prompt_01 §4-B-1).
 *
 * 실행: `npm test` (frontend 폴더에서).
 *
 * ## 무엇이 틀렸나
 *
 * 담당자: 「신청 분석에서 진행할 때마다 3D 디자인의 연관성이 없어.」
 *
 * 1단계 → 4단계 → 6단계를 눌러도 3D 는 그대로였다. `highlightNodeIds` 가 늘 빈
 * 집합이라 어느 노드도 밝아지지 않았고, 본문은 「제출서류」인데 3D 라벨은 여전히
 * 「신청자격」을 가리켰다.
 *
 * ## 여기서 지키는 약속
 *
 * 1. 단계마다 **밝은 노드가 다르다.** 겹치면 단계를 바꾼 티가 안 난다.
 * 2. 1~4단계는 «그 묶음 + 그 아래 항목»이다.
 * 3. 6단계는 사업계획서 노드와 **거기 이어진 근거**를 함께 밝힌다.
 * 4. 노드 id 규칙을 여기서 다시 쓰지 않는다 — `supportStepOfNodeId` 하나가 주인이다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { supportFocusOfStep } from "../src/lib/cosmos/support/supportSteps.ts";
import type { SupportStepKey } from "../src/types/opportunity.ts";

/** 실제 그래프 대신 id 만 있는 최소 그래프. 초점 함수는 id 규칙만 본다. */
const GRAPH = {
  nodes: [
    { id: "support" },
    { id: "reqgroup:sup-eligibility" },
    { id: "req:sup-eligibility-a" },
    { id: "req:sup-eligibility-b" },
    { id: "reqgroup:sup-conditions" },
    { id: "req:sup-conditions-a" },
    { id: "reqgroup:sup-schedule" },
    { id: "reqgroup:sup-documents" },
    { id: "req:sup-documents-a" },
    { id: "reqgroup:sup-basis" },
    { id: "ev:doc-1" },
    { id: "ev:doc-2" },
    { id: "proposal" },
    { id: "audit" },
    { id: "finding:sup-0" },
    { id: "finding:sup-1" },
  ],
  links: [
    { id: "l1", source: "proposal", target: "ev:doc-1" },
    { id: "l2", source: "audit", target: "proposal" },
  ],
} as unknown as Parameters<typeof supportFocusOfStep>[1];

const ALL_STEPS: SupportStepKey[] = [
  "eligibility",
  "conditions",
  "schedule",
  "documents",
  "evidence",
  "draft",
  "check",
];

test("1~4단계는 그 묶음과 그 아래 항목을 밝힌다", () => {
  const focus = supportFocusOfStep("eligibility", GRAPH);
  assert.deepEqual(
    [...focus.nodeIds].sort(),
    ["req:sup-eligibility-a", "req:sup-eligibility-b", "reqgroup:sup-eligibility"],
  );

  const documents = supportFocusOfStep("documents", GRAPH);
  assert.deepEqual([...documents.nodeIds].sort(), ["req:sup-documents-a", "reqgroup:sup-documents"]);
});

test("5단계는 근거 묶음과 회사자료 노드", () => {
  const focus = supportFocusOfStep("evidence", GRAPH);
  assert.deepEqual([...focus.nodeIds].sort(), ["ev:doc-1", "ev:doc-2", "reqgroup:sup-basis"]);
});

test("6단계는 사업계획서와 «거기 이어진» 근거를 함께 밝힌다", () => {
  const focus = supportFocusOfStep("draft", GRAPH);
  // proposal + 링크로 이어진 ev:doc-1 + audit(링크 상대)
  assert.ok(focus.nodeIds.has("proposal"), "사업계획서 노드");
  assert.ok(focus.nodeIds.has("ev:doc-1"), "이어진 근거");
  assert.ok(!focus.nodeIds.has("ev:doc-2"), "이어지지 않은 근거는 밝히지 않는다");
});

test("7단계는 점검 노드와 발견 항목", () => {
  const focus = supportFocusOfStep("check", GRAPH);
  assert.ok(focus.nodeIds.has("audit"));
  assert.ok(focus.nodeIds.has("finding:sup-0"));
  assert.ok(focus.nodeIds.has("finding:sup-1"));
});

test("코어(지원사업)는 어느 단계에도 들어가지 않는다", () => {
  for (const step of ALL_STEPS) {
    assert.ok(
      !supportFocusOfStep(step, GRAPH).nodeIds.has("support"),
      `${step} 단계가 코어를 밝히면 «어느 단계도 아닌 것»이 늘 밝다`,
    );
  }
});

test("단계마다 밝은 노드가 다르다", () => {
  const seen = new Map<string, string>();
  for (const step of ALL_STEPS) {
    const key = [...supportFocusOfStep(step, GRAPH).nodeIds].sort().join("|");
    assert.ok(key.length > 0, `${step} 단계에 밝은 노드가 없다`);
    const already = seen.get(key);
    assert.equal(already, undefined, `${step} 와 ${already} 의 밝은 노드가 같다`);
    seen.set(key, step);
  }
});

test("담당자가 본 세 단계(1·4·6)는 카메라도 서로 다르다", () => {
  const presets = (["eligibility", "documents", "draft"] as SupportStepKey[]).map(
    (step) => supportFocusOfStep(step, GRAPH).cameraPreset,
  );
  assert.equal(new Set(presets).size, 3, `카메라가 겹친다: ${presets.join(" · ")}`);
});

test("자막은 단계 이름으로 시작한다 — 오른쪽 단계 바와 같은 말", () => {
  assert.match(supportFocusOfStep("documents", GRAPH).caption, /^제출서류/);
  assert.match(supportFocusOfStep("draft", GRAPH).caption, /^사업계획서/);
});

test("빈 그래프에서도 터지지 않는다", () => {
  const empty = { nodes: [], links: [] } as unknown as Parameters<typeof supportFocusOfStep>[1];
  for (const step of ALL_STEPS) {
    const focus = supportFocusOfStep(step, empty);
    assert.equal(focus.nodeIds.size, 0);
    assert.ok(focus.caption.length > 0);
  }
});
