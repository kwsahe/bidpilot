/**
 * 사업기회 「전체」 탭 출처 번갈아 보이기 (39차 D22) — 서버 `interleave_sources` 와 같은 규칙.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { interleaveSources, type InterleaveItem } from "../src/lib/interleave.ts";

type Row = InterleaveItem & { id: string };

const row = (id: string, source: string, extra: Partial<InterleaveItem> = {}): Row => ({
  id, source, closed: false, blocked: false, notRecommended: false, ...extra,
});

describe("전체 탭 번갈아", () => {
  it("나라장터 1 · 기업마당 1 · 직접 넣음 1 · 나라장터 2 …(출처 안 순서는 그대로)", () => {
    const rows = [row("b1", "bizinfo"), row("b2", "bizinfo"), row("b3", "bizinfo"), row("g1", "g2b"), row("m1", "manual"), row("g2", "g2b")];
    assert.deepEqual(interleaveSources(rows, (r) => r, true).map((r) => r.id), ["g1", "b1", "m1", "g2", "b2", "b3"]);
  });

  it("같은 칸끼리만 번갈아 — 마감 · 불가는 살아 있는 것 뒤, 실무순 비추천은 그 사이", () => {
    const rows = [
      row("g1", "g2b"), row("gx", "g2b", { blocked: true }), row("gl", "g2b", { notRecommended: true }),
      row("b1", "bizinfo"), row("b2", "bizinfo"), row("bc", "bizinfo", { closed: true }),
    ];
    assert.deepEqual(interleaveSources(rows, (r) => r, true).map((r) => r.id), ["g1", "b1", "b2", "gl", "gx", "bc"]);
    // 점수순은 비추천 칸을 따로 두지 않는다(서버 점수순 키에 그 칸이 없다)
    assert.deepEqual(interleaveSources(rows, (r) => r, false).map((r) => r.id), ["g1", "b1", "gl", "b2", "gx", "bc"]);
  });
});
