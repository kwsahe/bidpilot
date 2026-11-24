import assert from "node:assert/strict";
import { test } from "node:test";

import { groupActions } from "../src/lib/cosmos/actionGroups.ts";

test("45차 M22 — 끝의 「— REQ-n」만 다른 할 일은 한 묶음 · 순서는 처음 나온 자리", () => {
  const groups = groupActions([
    { title: "요구하는 실적의 기간·금액·건수 기준 확인 — REQ-083" },
    { title: "나라장터 등록 확인" },
    { title: "요구하는 실적의 기간·금액·건수 기준 확인 — REQ-090" },
  ]);
  assert.deepEqual(groups.map((g) => [g.base, g.items.length, g.codes]), [
    ["요구하는 실적의 기간·금액·건수 기준 확인", 2, ["REQ-083", "REQ-090"]],
    ["나라장터 등록 확인", 1, []],
  ]);
});
