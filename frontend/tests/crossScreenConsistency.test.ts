/**
 * 2.0.6 — 전체 화면 모순 · 미연결 점검(대표 10-27 「또 이런 문제가 없는지 전체 확인」).
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { buildNoticeOptions } from "../src/lib/cosmos/useCosmosDashboard.ts";
import type { ProcurementListResponse } from "../src/types/procurement.ts";
import type { UnifiedOpportunity } from "../src/types/opportunity.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

const notice = (id: string, grade: string) => ({
  id,
  notice_no: id,
  title: `공고 ${id}`,
  agency: "기관",
  published_at: "2026-10-20T09:00:00+09:00",
  deadline_at: null,
  budget: null,
  region: null,
  description: null,
  source_url: null,
  revision_count: 1,
  pinned: false,
  rank: 1,
  candidate: { tier: "high" },
  recommendation: { grade },
});

test("고르기 칸: 회사 목록(레이더 · 사업기회)에 없는 나라장터 공고는 「목록 밖」 — 받았을 때만", () => {
  const list = { notices: [notice("g2b-in", "B"), notice("g2b-out", "A")] } as unknown as ProcurementListResponse;
  const priority = new Map([["g2b-in", { id: "g2b-in", company_priority_score: 70, eligibility_gate: "CHECK", source_rank: 1 } as unknown as UnifiedOpportunity]]);
  const loaded = buildNoticeOptions(list, "g2b-in", [], priority, null, true);
  assert.equal(loaded.find((o) => o.id === "g2b-in")?.outside, false);
  assert.equal(loaded.find((o) => o.id === "g2b-out")?.outside, true);
  // 통합 목록을 못 받았으면 모른다 — 「불가 · 마감」이라 단정하지 않는다
  const unknown = buildNoticeOptions(list, "g2b-in", [], new Map(), null, false);
  assert.ok(unknown.every((o) => !o.outside));
});

test("고르기 칸: 목록 밖 공고는 마감처럼 접고 「[추천 A]」 대신 「[불가·마감]」 — 후보 수도 그것을 뺀 수", () => {
  const src = read("components", "cosmos", "NoticePicker.tsx");
  assert.match(src, /const isClosed = \(n: NoticeOption\) => n\.grade === "NO_GO" \|\| Boolean\(n\.outside\) \|\| n\.gate === "FAIL";/);
  // 판정이 불가인 고정 예시도 「[불가]」로 접는다 — 남겨 두면 118 대 116 으로 갈렸다(실측)
  assert.match(src, /option\.gate === "FAIL"\s*\? "\[불가\] "/);
  assert.match(src, /option\.outside\s*\? "\[불가·마감\] "/);
  assert.match(src, /everyReal\.filter\(\(n\) => !isClosed\(n\)\)\.length\}건 후보/);
  // 통합 목록은 자르지 않고 받는다 — 잘리면 목록 안 공고도 「목록 밖」이 된다
  const hook = read("lib", "cosmos", "useCosmosDashboard.ts");
  assert.match(hook, /getBusinessOpportunities\(\{ organizationId, source: "all", days \}\)/);
});

test("제안서 화면은 목록을 자르지 않는다 — 「n건 중」과 찾기 범위가 사업기회와 같다", () => {
  const src = read("app", "plan", "page.tsx");
  // 불가 · 마감도 받는다 — 사업기회 「불가 포함 · 마감 포함」 행에서 와도 머리에 판정 · 마감이 보이게(고르기는 화면에서 거름)
  for (const source of ["bizinfo", "g2b"]) {
    const call = new RegExp(`getBusinessOpportunities\\(\\{ organizationId, source: "${source}", days(, includeBlocked: true, includeClosed: true)? \\}\\)`);
    assert.match(src, call);
  }
  assert.doesNotMatch(src, /getBusinessOpportunities\(\{[^}]*limit:/);
});
