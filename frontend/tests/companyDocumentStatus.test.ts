/**
 * 회사자료 문서 상태 (31차 §3-G R30-32) — 「사용 중」은 유효기간 안일 때만, 기간 밖이면 「기간 밖」.
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { DOCUMENT_STATUS_LABELS, OUT_OF_PERIOD_LABEL, documentStatusLabel, withinValidity } from "../src/types/company.ts";

const TODAY = "2026-10-04";

test("기간을 안 적었으면 안으로 본다 · 끝난 날과 시작 전은 밖", () => {
  assert.equal(withinValidity({ valid_from: null, valid_to: null }, TODAY), true);
  assert.equal(withinValidity({ valid_from: "2026-01-01", valid_to: "2026-10-04T00:00:00" }, TODAY), true);
  assert.equal(withinValidity({ valid_from: null, valid_to: "2026-10-03" }, TODAY), false);
  assert.equal(withinValidity({ valid_from: "2026-10-05", valid_to: null }, TODAY), false);
});

test("검색 준비가 끝난 문서도 기간 밖이면 「기간 밖」 · 다른 상태는 그대로", () => {
  const expired = { valid_from: null, valid_to: "2026-03-31" };
  assert.equal(documentStatusLabel({ status: "indexed", metadata: expired }, TODAY), OUT_OF_PERIOD_LABEL);
  assert.equal(documentStatusLabel({ status: "indexed", metadata: null }, TODAY), DOCUMENT_STATUS_LABELS.indexed);
  assert.equal(documentStatusLabel({ status: "approved", metadata: expired }, TODAY), DOCUMENT_STATUS_LABELS.approved);
});
