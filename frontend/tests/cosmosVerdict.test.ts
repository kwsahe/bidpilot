/**
 * 판정 낱말 · 색 한 벌 (27차 §3-D-4) — 지도 · 범례 · 목록 · 상세가 같은 사전을 읽는다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { VERDICT_KEY, VERDICT_WORDS, lineColorHex, nodeColorHex, verdictPill } from "../src/lib/cosmos/itemTypes.ts";
import { COSMOS_COLORS, STATE_LABELS, type CosmosNodeState } from "../src/lib/cosmos/theme.ts";

const FOUR = new Set<string>([COSMOS_COLORS.cyan, COSMOS_COLORS.amber, COSMOS_COLORS.red, COSMOS_COLORS.slate]);

test("모든 상태에 판정 낱말이 있고 색은 4색 안 · 범례 넷과 짝이 맞는다", () => {
  // STATE_LABELS 는 Record<CosmosNodeState, …> 라 tsc 가 모든 상태를 강제한다 — 그 키로 합집합을 런타임에 돈다.
  for (const state of Object.keys(STATE_LABELS) as CosmosNodeState[]) {
    assert.ok(VERDICT_WORDS[state], state);
    assert.ok(FOUR.has(nodeColorHex({ state })), state);
    assert.ok(VERDICT_KEY.some((key) => key.word === VERDICT_WORDS[state] && key.color === nodeColorHex({ state })), state);
  }
  assert.deepEqual(VERDICT_KEY.map((key) => key.word), ["충족", "확인 필요", "문제", "판정 전"]);
});

test("낱말 알약은 호박 · 빨강에만 · 선은 청록 · 호박 · 빨강 셋뿐", () => {
  assert.equal(verdictPill("ok"), null);
  assert.equal(verdictPill("neutral"), null);
  assert.equal(verdictPill("check")?.word, "확인 필요");
  assert.equal(verdictPill("warning")?.color, COSMOS_COLORS.red);
  assert.deepEqual(
    (["active", "candidate", "warning"] as const).map(lineColorHex),
    [COSMOS_COLORS.cyan, COSMOS_COLORS.amber, COSMOS_COLORS.red],
  );
});

test("참가 판정 색은 theme 한 곳 — 가능 청록 · 확인 필요 호박 · 불가 빨강 · 판정 전 회청, 초록 없음 (27차 §3-E · UNI-10)", async () => {
  const { verdictOf } = await import("../src/lib/verdict.ts");
  const { TONE_COLORS, VERDICT_BOX_CLASS, VERDICT_COLORS, VERDICT_TONES } = await import("../src/lib/cosmos/theme.ts");
  assert.deepEqual(VERDICT_COLORS, { PASS: COSMOS_COLORS.cyan, CHECK: COSMOS_COLORS.amber, FAIL: COSMOS_COLORS.red, NONE: COSMOS_COLORS.slate });
  for (const gate of ["PASS", "CHECK", "FAIL"] as const) {
    const verdict = verdictOf(gate);
    assert.equal(verdict.tone, VERDICT_TONES[gate], gate);
    assert.equal(TONE_COLORS[verdict.tone], VERDICT_COLORS[gate], gate);
  }
  assert.equal(verdictOf(null).tone, VERDICT_TONES.NONE);
  // 「불가」는 목록에서도 빨강 — 예전에는 회색(muted)이었다.
  assert.equal(TONE_COLORS[verdictOf("FAIL").tone], COSMOS_COLORS.red);
  // 판정 상자는 청록 · 호박 · 빨강 클래스만 쓴다.
  assert.match(VERDICT_BOX_CLASS.PASS.box, /cosmos-cyan/);
  assert.match(VERDICT_BOX_CLASS.CHECK.box, /cosmos-amber/);
  assert.match(VERDICT_BOX_CLASS.FAIL.box, /cosmos-red/);
  // 초록은 판정 · 통과 색이 아니다. 합성(demo)은 보라가 아니다 — 보라는 기업마당 한 뜻(UNI-19).
  assert.ok(!(Object.values(TONE_COLORS) as string[]).includes(COSMOS_COLORS.green));
  assert.notEqual(TONE_COLORS.demo as string, COSMOS_COLORS.violet);
});
