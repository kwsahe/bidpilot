/**
 * 43차 §2-H — 여러 사람 · 서버: 최근 활동 줄 고르기(TEAM-04) · 표시 쿠키 만료 시각(M28) · 409 「먼저 바뀜」 알아보기(M25).
 */
import assert from "node:assert/strict";
import test from "node:test";

import { actionLabel, visibleActivity } from "../src/lib/activityLog.ts";
import { parseUserCookie } from "../src/lib/currentUser.ts";
import { userCookieValue } from "../src/lib/session.ts";
import type { AuditLogEntry } from "../src/types/audit.ts";

const row = (ts: string, method: string, path: string, extra: Partial<AuditLogEntry> = {}): AuditLogEntry => ({
  ts, user: "hajin", role: "editor", method, path, organization_id: "org-sample", status: 200, ...extra,
});

test("최근 활동은 자동 판정 계산 줄과 사건 줄과 겹치는 요청 줄을 뺀다", () => {
  const rows = [
    row("2026-10-23T01:00:05Z", "PUT", "/api/eligibility/g2b-1/review/REQ-1", { event: { kind: "clause_review", procurement_id: "g2b-1", clause_id: "REQ-1" } }),
    row("2026-10-23T01:00:04Z", "PUT", "/api/eligibility/g2b-1/review/REQ-1"),
    row("2026-10-23T00:59:00Z", "POST", "/api/eligibility/evaluate"),
    row("2026-10-23T00:58:00Z", "PUT", "/api/capability/left-blank"),
  ];
  const shown = visibleActivity(rows);
  assert.deepEqual(shown.map(actionLabel), ["조항 확인 · REQ-1 · g2b-1", "「안 적음」 고름"]);
});

test("저장 요청은 무엇을 바꿨는지로 적고 설정 바꿈은 전후 값을 적는다", () => {
  assert.equal(actionLabel(row("2026-10-23T01:00:00Z", "PUT", "/api/manual-notices/manual-abc")), "직접 넣은 공고 고침");
  assert.equal(actionLabel(row("2026-10-23T01:00:00Z", "PUT", "/api/capability/profile")), "입찰 자격 자료 저장");
  const setting = row("2026-10-23T01:00:00Z", "PUT", "/api/capability/profile", {
    event: { kind: "capacity_setting", ranking_method: "score → practical" } as AuditLogEntry["event"],
  });
  assert.equal(actionLabel(setting), "순서 방식 · 단독 상한 · AI 보조 바꿈 · 순서 방식 score → practical");
  assert.equal(actionLabel(row("2026-10-23T01:00:00Z", "POST", "/api/모르는/길")), "실행 · 등록 요청");
});

test("표시 쿠키에 만료 시각이 실리고 화면은 밀리초로 읽는다 · 옛 쿠키는 null", () => {
  const value = userCookieValue({ u: "hajin", r: "editor", n: "김담당", exp: 1_790_000_000 });
  const parsed = parseUserCookie(encodeURIComponent(value));
  assert.equal(parsed?.expiresAt, 1_790_000_000_000);
  const old = parseUserCookie(encodeURIComponent(JSON.stringify({ u: "hajin", r: "editor", n: "김담당" })));
  assert.equal(old?.expiresAt, null);
});
