/**
 * 44차 M3 — 날짜만 있던 공고문 일정 마감은 「23:59」가 아니라 「(시각 원문 확인)」(백엔드 `practical_priority.deadline_stamp` 와 같은 말).
 * D-day · 순서는 그날 끝으로 센다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { TIME_UNKNOWN_NOTE, effectiveDeadline, formatPairDeadline, noticeDeadlinePair, pairOf } from "../src/lib/deadline.ts";

const SCHED = "2026-10-30T23:59:00+09:00";

describe("시각 모르는 마감(44차 M3)", () => {
  it("공고문 일정 마감이 날짜만이면 시각 대신 「(시각 원문 확인)」", () => {
    const pair = pairOf(
      { schedule_deadline: SCHED, schedule_deadline_label: "참가신청 마감", schedule_deadline_time_known: false },
      "2026-11-10T10:00:00+09:00",
    );
    assert.equal(pair.firstTimeKnown, false);
    assert.equal(effectiveDeadline(pair), SCHED); // 순서 · D-day 는 그날 끝
    assert.equal(formatPairDeadline(pair, SCHED), `10-30${TIME_UNKNOWN_NOTE}`);
    assert.equal(formatPairDeadline(pair, SCHED, "datetime"), `2026. 10. 30.${TIME_UNKNOWN_NOTE}`);
    // 입찰 마감은 시각을 안다
    assert.equal(formatPairDeadline(pair, "2026-11-10T10:00:00+09:00"), "11-10 10:00");
  });

  it("시각을 읽은 일정 마감 · 등록마감은 그대로 시각", () => {
    const known = pairOf({ schedule_deadline: "2026-10-30T18:00:00+09:00", schedule_deadline_time_known: true }, null);
    assert.equal(formatPairDeadline(known, known.qualification), "10-30 18:00");
    const reg = pairOf({ qualification_deadline: "2026-10-29T18:00:00+09:00" }, "2026-10-30T10:00:00+09:00");
    assert.equal(formatPairDeadline(reg, reg.qualification), "10-29 18:00");
  });

  it("대시보드 공고 원본(raw_data)도 같은 값을 읽는다", () => {
    const pair = noticeDeadlinePair({
      deadline_at: null,
      raw_data: { schedule_deadline: SCHED, schedule_deadline_label: "제출 마감", schedule_deadline_time_known: false },
    });
    assert.equal(formatPairDeadline(pair, pair.qualification), `10-30${TIME_UNKNOWN_NOTE}`);
  });
});
