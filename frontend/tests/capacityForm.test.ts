/**
 * 입찰 자격 카드 저장 값(33차 §3-B-3) — 「모름」을 「없음」으로, 한 줄을 두 줄로 바꾸지 않는다.
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { jointPartnerToSave, partnerChoiceOf, textLines } from "../src/lib/capacityForm.ts";

test("공동수급 파트너 — 모름 · 있음 · 없음 세 갈래 · 모름은 null(34차 R33-S4)", () => {
  // 저장본 null → 「모름」으로 열리고, 고르지 않고 저장하면 메모가 있어도 null 그대로
  assert.equal(partnerChoiceOf(null), "");
  assert.equal(partnerChoiceOf(undefined), "");
  assert.equal(jointPartnerToSave(partnerChoiceOf(null), "후보 A사"), null);
  assert.equal(jointPartnerToSave("", ""), null);
  assert.deepEqual(jointPartnerToSave("yes", ""), { available: true, note: null });
  assert.deepEqual(jointPartnerToSave("no", " 후보 A사 "), { available: false, note: "후보 A사" });
  // 이미 적어 둔 값은 그 갈래로 열린다
  assert.equal(partnerChoiceOf({ available: true, note: "A사" }), "yes");
  assert.equal(partnerChoiceOf({ available: false, note: null }), "no");
});

test("선행 사업 · 데이터 상품 · 공급기업 등록 — 줄바꿈으로만 나눈다(34차 R33-S5)", () => {
  const line = "없음 확인 — 해당 과제 수행 이력 없음 (검수자 조사 2026-09-18, docs/reports/x.md C4)";
  assert.deepEqual(textLines(line), [line]);
  assert.deepEqual(textLines("가 사업\r\n\n 나 사업, 2단계 \n"), ["가 사업", "나 사업, 2단계"]);
  assert.deepEqual(textLines("AI 바우처 공급기업(데이터 가공, 분석)"), ["AI 바우처 공급기업(데이터 가공, 분석)"]);
});
