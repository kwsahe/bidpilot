/**
 * 「확인 필요」 배너 문구 (ISSUE-113 · prompt_01 §4-E).
 *
 * 실행: `npm test` (frontend 폴더에서).
 *
 * 공고문을 읽은 공고에까지 「기업마당 목록 정보만으로」가 그대로 떴다 —
 * 원문을 내려받아 조항까지 뽑아 놓고 아직 안 봤다고 말하는 문구였다.
 * 두 사실을 갈라 말하는지 고정한다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { supportUnknownBanner, supportUnknownNotice } from "../src/lib/supportUnknownNotice.ts";

test("공고문을 읽었으면 「목록 정보만으로」라고 말하지 않는다", () => {
  const text = supportUnknownNotice(12, true);
  assert.match(text, /공고문에서 못 찾은 조항 12건/);
  assert.ok(!text.includes("목록 정보만으로"), text);
});

test("공고문을 못 읽었으면 예전 문구 그대로", () => {
  const text = supportUnknownNotice(12, false);
  assert.match(text, /목록 정보만으로/);
  assert.match(text, /12건/);
});

test("옛 스냅샷(필드 없음)은 「못 읽음」으로 본다", () => {
  // 읽었다는 근거가 없으면 읽었다고 말하지 않는다.
  assert.match(supportUnknownNotice(3, undefined), /목록 정보만으로/);
  assert.match(supportUnknownNotice(3, null), /목록 정보만으로/);
});

test("건수는 그대로 적는다", () => {
  assert.match(supportUnknownNotice(1, true), /조항 1건/);
  assert.match(supportUnknownNotice(0, true), /조항 0건/);
});

test("배너 한 줄 — 공고문을 읽었으면 조항만 「못 찾은 조항」, 나머지는 「목록 정보에 없는 항목」 (SUP-07)", () => {
  const plan = {
    eligibility: [
      { key: "clause_1", status: "unknown" },
      { key: "clause_2", status: "met" },
      { key: "region", status: "unknown" },
    ],
  };
  const text = supportUnknownBanner({ unknown_count: 4, document_read: true, plan });
  assert.match(text, /공고문에서 못 찾은 조항 1건/);
  assert.match(text, /목록 정보에 없는 항목 3건/);
  assert.match(supportUnknownBanner({ unknown_count: 4, document_read: false, plan }), /목록 정보만으로/);
});
