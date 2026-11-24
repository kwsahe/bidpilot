/**
 * 레이더 마감 글 — 등록마감이 먼저면 「등록」을 붙인다 (27차 RDR-03).
 * D-day 는 더 이른 참가자격 등록 마감 기준인데 순위 목록 · 3D 라벨 · 추적 카드가 입찰 마감처럼 적었다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { deadlineText } from "../src/lib/radar/layout.ts";
import type { UnifiedOpportunity } from "../src/types/opportunity.ts";

const item = (over: Partial<UnifiedOpportunity>): UnifiedOpportunity =>
  ({
    source_type: "g2b",
    closed: false,
    deadline: "2026-10-07T10:00:00+09:00",
    qualification_deadline: "2026-10-06T18:00:00+09:00",
    apply_period_kind: null,
    ...over,
  }) as UnifiedOpportunity;

describe("레이더 마감 글", () => {
  it("등록마감이 먼저면 「등록마감 D-n」(30차 §3-F #25)", () => {
    assert.equal(deadlineText(item({}), 7), "등록마감 D-7");
  });
  it("등록마감만 지났으면 「등록마감 지남」", () => {
    assert.equal(deadlineText(item({}), -1), "등록마감 지남");
  });
  it("등록마감이 없거나 입찰보다 늦으면 그대로", () => {
    assert.equal(deadlineText(item({ qualification_deadline: null }), 7), "D-7");
    assert.equal(deadlineText(item({ qualification_deadline: "2026-10-08T10:00:00+09:00" }), 7), "D-7");
  });
  it("기업마당 · 마감된 건에는 붙이지 않는다", () => {
    assert.equal(deadlineText(item({ source_type: "bizinfo" }), 7), "D-7");
    assert.equal(deadlineText(item({ closed: true }), -1), "마감");
  });
});
