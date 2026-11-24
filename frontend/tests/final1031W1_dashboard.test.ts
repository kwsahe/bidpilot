/**
 * 10-31 최종 점검 W1 — 입찰 분석 읽는 중 · 고르기 칸(A3 · A5 · 고르기 칸 검토 순서 전).
 *
 * 부품(.tsx)은 node 시험이 바로 불러오지 못한다 — 순수 함수는 불러서, 부품은 고친 자리의 소스 글을 본다.
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/final1031W1_dashboard.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { buildNoticeOptions, loadingText } from "../src/lib/cosmos/useCosmosDashboard.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

const SUPPORT_ID = "bizinfo-PBLN_000000000125618";
const BID_ID = "g2b-R26BK00000009-000";

test("A3 — 목록 · 상세를 받는 중이면 고른 지원사업 줄에 id 글자 · 「목록에서 확인되지 않음」을 쓰지 않는다", () => {
  const waiting = buildNoticeOptions(null, SUPPORT_ID, [], new Map(), null, false, true).find((o) => o.id === SUPPORT_ID);
  assert.equal(waiting?.title, "지원사업 불러오는 중…");
  assert.equal(waiting?.agency, "");
  assert.equal(waiting?.support, true);
  // 다 받은 뒤에도 없으면 그때만 「목록 밖」
  const settled = buildNoticeOptions(null, SUPPORT_ID, [], new Map(), null, false, false).find((o) => o.id === SUPPORT_ID);
  assert.equal(settled?.title, SUPPORT_ID);
  assert.equal(settled?.agency, "목록에서 확인되지 않음");
  // 상세가 먼저 오면 읽는 중이어도 제 이름
  const named = buildNoticeOptions(null, SUPPORT_ID, [], new Map(), { title: "두바이 자동차부품전", agency: "경상북도" }, false, true).find((o) => o.id === SUPPORT_ID);
  assert.equal(named?.title, "두바이 자동차부품전");
  assert.equal(named?.agency, "경상북도");
  // 입찰도 같은 규칙
  const bid = buildNoticeOptions(null, BID_ID, [], new Map(), null, false, true).find((o) => o.id === BID_ID);
  assert.equal(bid?.title, "공고 불러오는 중…");
  assert.equal(bid?.agency, "");
});

test("A3 — 훅은 지원사업이면 통합 목록 · 신청 분석, 입찰이면 나라장터 목록 · 연 공고를 다 받았는지로 「읽는 중」을 정한다", () => {
  const hook = read("lib", "cosmos", "useCosmosDashboard.ts");
  assert.match(hook, /\? !priorityCurrent \|\| supportLoad\.status === "idle" \|\| supportLoad\.status === "loading"\s*: listState\.status === "loading" \|\| load\.kind === "loading";/);
  assert.match(hook, /priorityCurrent && priorityState\.loaded, selectedPending\);/);
  // 기관이 빈 자리표시 줄은 「 · 」로 끝나지 않는다
  const picker = read("components", "cosmos", "NoticePicker.tsx");
  assert.equal((picker.match(/\$\{option\.agency \? ` · \$\{option\.agency\}` : ""\}/g) ?? []).length, 2);
});

test("A5 — 읽는 동안 「… 아직 안 함」은 「… 불러오는 중…」, 「아직 안 읽음」(이미 아는 값)과 읽은 뒤는 그대로", () => {
  assert.equal(loadingText("참가 판정: 아직 안 함", true), "참가 판정: 불러오는 중…");
  assert.equal(loadingText("근거·제안서·제출 전 점검: 아직 안 함", true), "근거·제안서·제출 전 점검: 불러오는 중…");
  assert.equal(loadingText("아직 안 함", true), "불러오는 중…"); // 8단계 3번 카드 요약
  assert.equal(loadingText("참가 판정: 아직 안 함", false), "참가 판정: 아직 안 함");
  assert.equal(loadingText("요구사항: 제안요청서 아직 안 읽음", true), "요구사항: 제안요청서 아직 안 읽음");
  assert.equal(loadingText("참가 판정: 확인 필요 (정해 둔 규칙으로 판정)", true), "참가 판정: 확인 필요 (정해 둔 규칙으로 판정)");
});

test("A5 — 쉬운 보기 출처 줄 · 8단계 요약 · 바닥 출처 줄 · KPI 칩과 안내가 같은 읽는 중 값을 본다", () => {
  const simple = read("components", "cosmos", "SimpleDashboard.tsx");
  assert.match(simple, /sourceBadges\(graph\)\.map\(\(b\) => loadingText\(b\.label, analysisLoading\)\)/);
  assert.match(simple, /const LOADED_LATER = new Set<WorkflowStage>\(\[3, 5, 6, 7\]\);/);
  assert.match(simple, /const summary = loadingText\(step\.summary, analysisLoading && LOADED_LATER\.has\(step\.id\)\);/);
  assert.doesNotMatch(simple, /\{step\.summary\}/);
  const bottom = read("components", "cosmos", "BottomStrip.tsx");
  assert.match(bottom, /label=\{loadingText\(badge\.label, loading\)\}/);
  const strip = read("components", "cosmos", "MissionStrip.tsx");
  // 값이 없을 때만(값이 「불러오는 중…」인 칸) — 「결정 전」 · 「AI 검색 꺼 둠」은 실제 상태라 그대로
  assert.match(strip, /const waiting = useAnalysisLoading\(\) && pending;/);
  assert.match(strip, /<SourceBadge kind=\{metric\.source\} label=\{sourceLabel\} \/>/);
  assert.match(strip, /leading-4 text-cosmos-secondary">\{hint\}<\/span>/);
  assert.doesNotMatch(strip, /\{metric\.hint\}<\/span>/);
});

test("고르기 칸 — 검토 순서(통합 목록)를 받기 전에는 나라장터 묶음을 접지 않은 채 보이지 않고 「불러오는 중」", () => {
  const hook = read("lib", "cosmos", "useCosmosDashboard.ts");
  assert.match(hook, /priorityPending: !priorityCurrent,/);
  const picker = read("components", "cosmos", "NoticePicker.tsx");
  assert.match(picker, /const listLoading = \(noticeList\.status === "loading" && allReal\.length === 0\) \|\| Boolean\(noticeList\.priorityPending\);/);
  assert.match(picker, /disabled=\{disabled \|\| listLoading\}/);
});
