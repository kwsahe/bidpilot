/**
 * 사업기회 「재수집」 단추 (20차 §4-G) — 시연 고정 모드에서는 이유를 말하며 잠긴다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { RECOLLECT_LOCKED_REASON, RECOLLECT_UNKNOWN_REASON, recollectLock, recollectSummary } from "../src/lib/recollect.ts";

describe("재수집 단추", () => {
  it("g2b_live 가 false 면 나라장터 단추가 잠기고 이유를 말한다", () => {
    const frozen = { g2b_live: false, bizinfo_live: false };
    assert.equal(recollectLock(frozen, "g2b"), RECOLLECT_LOCKED_REASON);
    assert.equal(recollectLock(frozen, "bizinfo"), "전체 새로 받기는 꺼져 있습니다(저장본만 씀)");
  });

  it("값을 모르면(옛 백엔드 · 연결 끊김) 잠근다 — 이유는 「시연 고정」이 아니라 「서버 상태를 몰라」 (OPP-18)", () => {
    assert.equal(recollectLock(null, "g2b"), RECOLLECT_UNKNOWN_REASON);
    assert.equal(recollectLock({}, "bizinfo"), RECOLLECT_UNKNOWN_REASON);
    assert.equal(RECOLLECT_UNKNOWN_REASON, "서버 상태를 확인하지 못해 새로 받기를 잠갔습니다 — 잠시 뒤 다시 열어 보세요");
  });

  it("문이 켜진 출처만 열린다", () => {
    const live = { g2b_live: true, bizinfo_live: false };
    assert.equal(recollectLock(live, "g2b"), null);
    assert.equal(recollectLock(live, "bizinfo"), RECOLLECT_LOCKED_REASON);
  });

  it("결과 한 줄", () => {
    const line = recollectSummary({
      source: "g2b",
      before: { count: 210, fetched_at: null },
      after: { count: 215, fetched_at: null },
      new: 5,
      gone: 3,
      qualification: { days_fetched: 2, calls: 2, note: null },
      clauses_missing: 5,
      clauses_note: null,
      took_ms: 900,
    });
    assert.equal(line, "나라장터 210 → 215 · 새 공고 5 · 빠짐 3 · 참가자격 조항 없는 새 공고 5 · 자격 표 2일 받음");
  });
});
