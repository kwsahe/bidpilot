/**
 * 사용자 오류 문장 (lib/errors) — 서버 사유가 객체로 와도 버리지 않는다 (CMN-11).
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError } from "../src/lib/api.ts";
import { describeFailure, NETWORK_MESSAGE } from "../src/lib/errors.ts";

test("detail 이 객체({code, message})면 message 가 사용자 문장이 된다 — 일반 409 문장으로 덮지 않는다", () => {
  const error = new ApiError(409, "x", null, "필수 요구사항이 57건에서 60건으로 변경되었습니다.");
  assert.equal(error.detail, null); // 「detail 이 비었으면 객체 사유」로 가르는 화면(DTL-12)이 그대로 동작한다
  assert.equal(describeFailure(error, "점검에 실패했습니다."), "필수 요구사항이 57건에서 60건으로 변경되었습니다.");
});

test("문자열 detail 이 먼저 · 영어 사유는 사용자 문장으로 바꾼다", () => {
  assert.equal(describeFailure(new ApiError(400, "x", "회사 코드가 없습니다", "무시")), "회사 코드가 없습니다");
  assert.match(describeFailure(new ApiError(404, "x", "Not Found")), /저장된 결과가 없습니다/);
});

test("연결 실패는 원인을 단정하지 않는다 — 「인터넷」도 「서버 꺼짐」도 아니다 (CMN-26)", () => {
  assert.equal(describeFailure(new TypeError("Failed to fetch")), NETWORK_MESSAGE);
  assert.ok(!NETWORK_MESSAGE.includes("인터넷"));
});
