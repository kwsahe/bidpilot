/**
 * 데모 공고 날짜는 화면을 연 시각 기준 (ISSUE-160 · 27차 §3-F).
 * 마감이 박혀 있으면 그날이 지난 뒤 첫 화면이 「입찰 종료 · 참여할 수 없습니다」로 열린다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DEMO_DEADLINE_DAYS, DEMO_NOTICE, buildDemoNotice } from "../src/lib/cosmos/demoNotice.ts";
import { daysUntil, urgencyTierOf } from "../src/lib/deadline.ts";

const DAY = 86_400_000;

describe("데모 공고 마감 — 로드 시각 기준", () => {
  for (const offset of [0, 30, 365]) {
    it(`+${offset}일 시계에서 연 데모 첫 화면은 마감이 아니다`, () => {
      const now = Date.now() + offset * DAY;
      const notice = buildDemoNotice(now);
      const days = daysUntil(notice.deadline_at, now);
      assert.equal(days, DEMO_DEADLINE_DAYS);
      assert.notEqual(urgencyTierOf(days, false), "closed");
      assert.ok(Date.parse(notice.published_at) < now, "공고일은 연 시각보다 앞");
    });
  }

  it("모듈 값도 지금 기준이다 (박힌 날짜 없음)", () => {
    assert.equal(daysUntil(DEMO_NOTICE.deadline_at, Date.now()), DEMO_DEADLINE_DAYS);
  });

  it("KST 자정 직전 · 직후에도 마감 시각은 18:00 +09:00", () => {
    const beforeMidnight = Date.parse("2026-12-31T23:59:00+09:00");
    assert.equal(buildDemoNotice(beforeMidnight).deadline_at, "2027-01-21T18:00:00+09:00");
    assert.equal(buildDemoNotice(beforeMidnight + 2 * 60_000).deadline_at, "2027-01-22T18:00:00+09:00");
  });
});
