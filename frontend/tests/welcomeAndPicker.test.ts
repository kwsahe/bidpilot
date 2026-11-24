/**
 * 2.0.5 — 첫 진입 환영 창 · 대시보드 고르기 칸 끊김(대표 10-27 「대시보드엔 기업마당만, 레이더엔 나라장터」).
 *
 * 실행: `npm test` (frontend 폴더에서). 화면을 띄우지 않고 소스 글로 본다(externalCheckSupportPlanRadar.test.ts 와 같은 방식).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { SCREEN_NAMES, WELCOME_FEATURES, WELCOME_LEAD, WELCOME_TITLE } from "../src/lib/terms.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

test("지원사업을 보던 중에도 나라장터 목록을 받는다 — 고르기 칸이 「불러오는 중」에 멈추지 않게", () => {
  const src = read("lib", "cosmos", "useCosmosDashboard.ts");
  const start = src.indexOf("if (isSupportProgramId(requestedId)) {");
  const branch = src.slice(start, src.indexOf("return getSupportProgram(", start));
  assert.ok(start > 0);
  assert.match(branch, /getProcurements\(\{ days \}\)/);
  assert.match(branch, /setList\(procurements\)/);
  assert.match(branch, /setListState\(\{ status: "error"/);
});

test("나라장터 목록을 못 받으면 고르기 칸이 말없이 빼지 않고 「목록을 받지 못했습니다」를 보인다", () => {
  const src = read("components", "cosmos", "NoticePicker.tsx");
  // 사유가 있을 때만(목록 요청 실패) — 가상 예시 자료만 실패한 경우는 아니다
  assert.match(src, /const g2bListError = [^;]*noticeList\.status === "error" && Boolean\(noticeList\.message\)/);
  assert.match(src, /\{g2bListError && \(\s*<optgroup label="나라장터 실공고 후보">/);
  // 오류 줄 값은 실제 공고 id 와 겹치지 않는다 — 겹치면 그 줄이 「지금 고른 것」 자리에 섰다
  assert.match(src, /<option value=\{G2B_LIST_ERROR_VALUE\} disabled>/);
  assert.match(src, /<option value=\{SUPPORT_LIST_ERROR_VALUE\} disabled>/);
  assert.doesNotMatch(src, /<option value=\{selectedNoticeId\} disabled>/);
});

test("목록에 없는 공고 안내는 「데모 공고」라 하지 않는다 — 실제 1위가 열린다", async () => {
  const { STALE_NOTICE_MESSAGE, STALE_NOTICE_LINK_MESSAGE } = await import("../src/lib/cosmos/useCosmosDashboard.ts");
  for (const message of [STALE_NOTICE_MESSAGE, STALE_NOTICE_LINK_MESSAGE]) assert.doesNotMatch(message, /데모/);
});

test("대시보드 상단 막대는 어느 상태에서든 기업마당 실패 사실을 받는다", () => {
  const shell = read("components", "cosmos", "DashboardShell.tsx");
  const bars = shell.split("<TopBar").slice(1).map((chunk) => chunk.slice(0, chunk.indexOf("/>")));
  assert.ok(bars.length >= 4);
  for (const bar of bars) assert.match(bar, /supportError=\{dashboard\.supportError\}/);
});

test("지원사업 화면은 없는 사업이면 저장해 둔 같은 선택을 비운다", () => {
  const src = read("components", "support", "SupportShell.tsx");
  assert.match(src, /notFound && readSelectedSupport\(\) === programId\) clearSelectedSupport\(\)/);
});

test("환영 창은 첫 진입이면 뜬다 — 가상 예시 공고일 때만 뜨던 조건이 없다", () => {
  const shell = read("components", "cosmos", "DashboardShell.tsx");
  const start = shell.indexOf("const showWelcome =");
  const condition = shell.slice(start, shell.indexOf(";", start));
  assert.match(condition, /welcome\.firstVisit/);
  assert.match(condition, /!welcomeClosed/); // 저장소가 막혀도 이번 방문 동안은 닫힌다
  assert.doesNotMatch(condition, /hasScenario|dashboard\.status/);
  // 불러오는 중 · 지원사업 · 오류 · 보통 화면 네 곳 모두 — 첫 화면이 지원사업이면 안 뜨다가 나중에 작업 중에 떴다(검토 R6)
  assert.equal(shell.split("{welcomeDialog}").length - 1, 4);
  // 「시작하기」는 창만 닫는다 — 5단계 안내를 켜지 않는다(검토 R4)
  assert.match(shell, /<WelcomeDialog onStart=\{closeWelcome\} onLeave=\{closeWelcome\} \/>/);
  assert.doesNotMatch(shell, /onWelcomeStart/);
  assert.match(read("lib", "cosmos", "useTutorial.ts"), /WELCOME_STORAGE_KEY = "bidpilot\.welcome\.v2"/);
});

test("환영 창 문구 — 제목 · 할 수 있는 것 · 숫자 없음 · 메뉴 이름은 SCREEN_NAMES", () => {
  assert.equal(WELCOME_TITLE, "BidPilot AI에 오신 것을 환영합니다");
  assert.ok(WELCOME_FEATURES.length >= 5);
  const menus = Object.values(SCREEN_NAMES);
  for (const feature of WELCOME_FEATURES) {
    // 처음 안내에는 숫자 · 기간 · 비용을 넣지 않는다(terms.ts 31차 규칙)
    assert.doesNotMatch(`${feature.title} ${feature.detail}`, /\d/, feature.title);
    assert.ok(menus.some((menu) => feature.where.includes(menu)) || feature.where.includes("작성 →"), feature.where);
  }
  assert.doesNotMatch(WELCOME_LEAD, /\d/);
  const dialog = read("components", "cosmos", "WelcomeDialog.tsx");
  assert.match(dialog, /WELCOME_FEATURES\.map/);
  assert.doesNotMatch(dialog, /데모로 둘러보기|처음 오셨군요/);
});
