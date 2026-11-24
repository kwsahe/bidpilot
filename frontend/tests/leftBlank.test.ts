/**
 * 42차 FRONT-R41-01 — 「안 적음」을 연달아 고르면 앞 선택이 사라졌다(다시 읽기 전 낡은 칸 목록으로 저장).
 * 저장 응답의 열쇠 목록을 칸에 바로 반영해, 다음 누름이 앞 선택을 포함한 목록으로 저장되게 한다.
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { applyLeftBlank } from "../src/components/company/leftBlank.ts";
import type { BlankFieldsResponse } from "../src/lib/api.ts";

const field = (key: string, left_blank = false) => ({ key, label: key, blank: true, left_blank, count: 1, where: "", examples: [] });

test("저장 응답의 열쇠가 칸에 바로 반영되고 다음 선택이 앞 선택을 포함한다", () => {
  const data = { fields: [field("revenue"), field("joint_bid_partner"), field("research")], note: "" } as unknown as BlankFieldsResponse;
  const first = applyLeftBlank(data, ["revenue"]);
  const kept = first.fields.filter((f) => f.left_blank).map((f) => f.key);
  assert.deepEqual(kept, ["revenue"]);
  // 화면은 다음 누름에서 [...kept, 새 칸] 을 저장한다 — 앞 선택이 남는다
  const second = applyLeftBlank(first, [...kept, "research"]);
  assert.deepEqual(second.fields.filter((f) => f.left_blank).map((f) => f.key), ["revenue", "research"]);
  assert.equal(data.fields[0].left_blank, false); // 원본은 바꾸지 않는다
});
