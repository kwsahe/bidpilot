/** 45차 H6 — 최근 활동 표: 화면 서버 줄(api-token)은 빼고, 동작 · 결과는 사람 말로. */

import assert from "node:assert/strict";
import test from "node:test";

import { actionLabel, resultText, visibleActivity } from "../src/lib/activityLog.ts";
import type { AuditLogEntry } from "../src/types/audit.ts";

const row = (user: string, method: string, path: string, status = 200): AuditLogEntry =>
  ({ ts: "2026-10-24T13:00:00Z", user, role: "admin", method, path, organization_id: "org-sample", status }) as AuditLogEntry;

test("화면 서버가 남긴 로그인 확인 줄(api-token)은 표에 없다", () => {
  const rows = visibleActivity([row("api-token", "POST", "/api/auth/login"), row("hajin", "POST", "/api/auditor/run")]);
  assert.deepEqual(rows.map((r) => r.user), ["hajin"]);
});

test("흔한 일은 사람 말 · 결과는 「성공 · 권한 없음」", () => {
  assert.equal(actionLabel(row("hajin", "POST", "/api/auditor/run")), "제출 전 점검 실행");
  assert.equal(actionLabel(row("hajin", "POST", "/api/proposal/generate")), "제안서 초안 만들기");
  assert.equal(actionLabel(row("hajin", "DELETE", "/api/actions/g2b-1/a-1")), "할 일 지움");
  assert.equal(actionLabel(row("hajin", "PUT", "/api/evidence/g2b-1/ledger")), "원장 실적 채택 · 취소");
  assert.equal(resultText(200), "성공");
  assert.equal(resultText(403), "권한 없음");
  assert.equal(resultText(204), "성공");
});
