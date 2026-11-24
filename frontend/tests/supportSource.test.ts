/**
 * 지원사업 출처 배지 하나 · 목록에서 빠진 공고(34차 R33-A1 · A2 · A3).
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { ARCHIVED_CLOSED_MARK, supportSourceBadge } from "../src/lib/supportSource.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, ...parts), "utf8");

test("목록에서 빠진 사본 — 마감일이 지났을 때만 「마감」, 아니면 「목록에서 내려감」 · 가상 예시로 적지 않는다", () => {
  assert.match(supportSourceBadge("archived", true).label, /\(마감\)$/);
  assert.match(supportSourceBadge("archived", false).label, /\(목록에서 내려감\)$/);
  assert.equal(supportSourceBadge("archived").kind, "cached");
  assert.equal(supportSourceBadge("bizinfo").label, "기업마당 실시간");
  assert.equal(supportSourceBadge("sample").kind, "demo");
});

test("출처 배지는 함수 하나 — 신청 분석 · 쉬운 보기 · 대시보드 전체 · 3D 어휘가 같은 것을 부른다(R33-A2)", () => {
  for (const file of [
    ["src", "components", "support", "SupportShell.tsx"],
    ["src", "components", "support", "SupportSimpleView.tsx"],
    ["src", "components", "cosmos", "SupportDashboardBody.tsx"],
    ["src", "lib", "cosmos", "support", "supportVocabulary.ts"],
  ]) {
    const src = read(...file);
    assert.ok(src.includes("supportSourceBadge(result.source, result.archived_closed)"), file.join("/"));
    assert.ok(!src.includes("function sourceLabelOf") && !src.includes("export function supportSourceBadge"), file.join("/"));
  }
});

test("새 초안 409 의 마감 사유 표식은 백엔드 글의 머리 · 목록에서 내려간 글은 백엔드와 같다(R33-A1 · A3)", () => {
  const service = read("..", "backend", "app", "services", "support_application_service.py");
  const closed = /^ARCHIVED_NOTE = "([^"]+)"/m.exec(service)?.[1] ?? "";
  assert.ok(closed.startsWith(ARCHIVED_CLOSED_MARK), closed);
  assert.ok(service.includes('DELISTED_NOTE = "기업마당 목록에서 내려간 공고(마감일 전) — 취소 · 변경됐을 수 있으니 원문 확인"'));
  const plan = read("src", "app", "plan", "page.tsx");
  assert.ok(plan.includes("!error.detail?.startsWith(ARCHIVED_CLOSED_MARK)"), "409 마감 사본은 실패로");
  assert.ok(plan.includes("busy={busy !== null || closedBlock !== null}"), "과제 고르기도 끈다");
});
