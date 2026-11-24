/**
 * 2.0.6 — 사업기회 화면 · 직접 넣기 · 요구사항 정리표 · 결정 칸 · 이번 주 할 일 · 지원사업 머리의 모순 · 미연결(전체 점검 워크플로).
 *
 * 부품(.tsx)은 node 시험이 바로 불러오지 못한다 — 고친 자리의 소스 글을 본다(crossScreenConsistency.test.ts 와 같은 방식).
 * 마감 셈은 lib/deadline 을 직접 돌려 「직접 넣은 행」과 「이번 주 할 일」이 같은 날을 고르는지 본다.
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/v206Opportunities.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { effectiveDeadline, pairOf } from "../src/lib/deadline.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");
const page = () => read("app", "opportunities", "page.tsx");
const manual = () => read("components", "opportunities", "ManualInboxPanel.tsx");
const sheet = () => read("components", "opportunities", "RequirementSheet.tsx");

test("values-5: 직접 넣은 행의 D-day 는 참가신청 마감이 이르면 그 날 — 이번 주 할 일 `deadlineOf` 와 같은 셈", () => {
  // 서버는 직접 넣기 「참가신청 · 등록 · 협정 마감」을 qualification_deadline 으로 싣는다
  const item = { qualification_deadline: "2026-10-30T18:00:00+09:00", deadline: "2026-11-10T10:00:00+09:00" };
  assert.equal(effectiveDeadline(pairOf(item, item.deadline)), item.qualification_deadline);
  // 세 자리(직접 넣기 탭 · 「전체」 탭 쉬운 보기 · 카드)가 입찰 마감으로 바로 세지 않는다
  assert.doesNotMatch(manual(), /dDayText\(\{ deadline: item\.deadline/);
  assert.doesNotMatch(page(), /dDayText\(\{ deadline: item\.deadline/);
  for (const src of [manual(), page()]) {
    assert.match(src, /const pair = pairOf\(item, item\.deadline\);\s*const primary = effectiveDeadline\(pair\);/);
    assert.match(src, /dDayText\(\{ deadline: primary, periodKind: null, nowMs \}\)/);
    assert.match(src, /byRegistration && <span[^>]*>\{firstLabel\(pair\)\}/);
  }
});

test("state-5: 직접 넣기 임시 저장 열쇠는 회사별 · 회사가 바뀌면 패널을 새로 그린다", () => {
  const src = manual();
  assert.match(src, /const draftKey = `manual-form\.\$\{organizationId\}\./);
  assert.match(src, /`manual-inbox-paste:\$\{organizationId\}`/);
  assert.doesNotMatch(src, /loadDraft\(PASTE_DRAFT\)/);
  assert.match(page(), /<ManualInboxPanel[\s\S]{0,300}key=\{organizationId\}/);
});

test("links-4 · 같은 페이지 링크: 주소가 바뀌면 탭이 주소를 따른다(useSearchParams 를 Suspense 안에서)", () => {
  const src = page();
  assert.match(src, /import \{ useSearchParams \} from "next\/navigation";/);
  assert.match(src, /function SearchWatcher\(\{ onChange \}[\s\S]{0,120}useSearchParams\(\)\.toString\(\)/);
  assert.match(src, /const followUrl = useCallback\(\(\) => \{\s*setTab\(null\);\s*setManualFocusOverride\(null\);\s*rereadUrl\(\);/);
  // 쉬운 보기 · 전체 보기 둘 다
  assert.equal(src.match(/<Suspense fallback=\{null\}>\s*<SearchWatcher onChange=\{followUrl\} \/>/g)?.length, 2);
});

test("정리표 「← 목록으로」는 들어온 탭으로 — 늘 「전체」로 가지 않는다", () => {
  const src = page();
  assert.doesNotMatch(src, /<RequirementSheet[^\n]*onBack=\{\(\) => setTab\("list"\)\}/);
  assert.equal(src.match(/<RequirementSheet[^\n]*onBack=\{\(\) => setTab\(sheetBack\)\}/g)?.length, 2);
  assert.match(src, /if \(tab !== lastTab\) \{\s*setLastTab\(tab\);\s*if \(tab === "sheet"\) setSheetBack\(lastTab\);/);
});

test("출처 오류 줄: 직접 넣음 키를 「manual 수집 문제」로 적지 않는다", () => {
  const src = page();
  assert.doesNotMatch(src, /: key\} 수집 문제/);
  assert.match(src, /key === "manual" \? "직접 넣은 공고 목록"/);
});

test("「오늘 달라진 것」 변경 · 결정 조건: 읽는 중과 받기 실패를 가른다", () => {
  const src = page();
  assert.doesNotMatch(src, /digestIdsMissing/);
  assert.match(src, /digestIdsFailed\s*\?\s*" — 변경·결정 목록을 받지 못해 그 조건은 적용하지 않았습니다"\s*:\s*" — 변경·결정 목록을 읽는 중입니다/);
  assert.match(src, /\.catch\(\(\) => \{\s*if \(!alive\) return;\s*setDigestIds\(null\);\s*setDigestIdsFailed\(true\);/);
});

test("links-5 · fallback-3: 정리표는 나라장터 목록 · 통합 목록 오류를 받아 「대시보드 목록에 없는 공고」를 함부로 쓰지 않는다", () => {
  assert.equal(page().match(/<RequirementSheet[^\n]*list=\{procurements\} listError=\{unifiedError\}/g)?.length, 2);
  const src = sheet();
  assert.match(src, /const onDashboardList = list \? listNotice !== null : listError !== null;/);
  assert.match(src, /const openableOnDashboard = isDemoProcurementId\(bidId\) \|\| unified !== null \|\| onDashboardList;/);
  assert.match(src, /listNotice\?\.title \?\?/);
  assert.match(src, /listError && !unified && \(\s*<InlineAlert tone="warn">이 공고의 판정 · 마감 배지를 보일 수 없습니다 — \{listError\}/);
});

test("fallback-3 후속: 통합 목록 실패 사유에 목록 탭 꼬리(「출처별 목록은 그대로 표시합니다」)를 싣지 않는다 — 정리표 · 직접 넣기에는 출처별 목록이 없다", () => {
  const src = page();
  const fn = src.match(/function describeUnifiedError\(error: unknown\): string \{[\s\S]*?\n\}/)?.[0] ?? "";
  assert.ok(fn, "describeUnifiedError 를 찾지 못함");
  assert.doesNotMatch(fn, /출처별 목록/);
  // 꼬리는 목록 탭 경고에서 붙인다
  assert.match(src, /tab === "list" && unifiedError && <InlineAlert tone="warn">\{unifiedError\} 출처별 목록은 그대로 표시합니다\.<\/InlineAlert>/);
  // 정리표 경고는 같은 목록을 두 이름으로 부르지 않는다
  assert.doesNotMatch(sheet(), /순위 · 판정 목록을 받지 못해/);
});

test("fallback-6: 원장 후보를 읽는 중 · 못 읽음은 「근거 없음」이 아니다 · 사유와 다시 불러오기", () => {
  const src = sheet();
  assert.match(src, /if \(read === "loading"\) return "원장 후보 읽는 중";\s*if \(read === "failed"\) return "확인 못 함";/);
  assert.match(src, /ledgerStatusText\(ledger, requirementId, ledgerState\)/);
  assert.doesNotMatch(src, /\.catch\(\(\) => \{\s*if \(!cancelled\) setLedger\(null\);/);
  // 제안서를 만들기 전(연결 전)에도 채택 칸은 선다 — 실패 줄 · 표 위 경고를 근거 모드로 막지 않는다
  assert.doesNotMatch(src, /view\.mode === "off" && ledgerError !== null/);
  assert.doesNotMatch(src, /view\.mode !== "off" \? null/);
  assert.match(src, /const ledgerNote =\s*ledgerError !== null \? `실적 원장 후보를 읽지 못했습니다 — \$\{ledgerError\}` : view\.mode === "off" && ledgerLoading/);
  assert.match(src, /\{ledgerError !== null && \(\s*<InlineAlert tone="warn">/);
  // 「확인 못 함」은 행 상태가 원장 값을 쓰는 「AI 검색 꺼 둠」 모드에서만 말한다
  assert.match(src, /\{view\.mode === "off" \? " 행 상태는 「확인 못 함」으로 둡니다\." : ""\}/);
  assert.match(src, /onClick=\{\(\) => setLedgerTick\(\(n\) => n \+ 1\)\}/);
  // 행 상세: 채택 칸을 말없이 지우지 않고 한 줄로
  assert.match(src, /\{ledgerNote \? \(/);
});

test("fallback-8: 결정을 못 읽으면 「검토 전」이 아니라 사유 · 다시 불러오기 · 그동안 결정 단추 잠금", () => {
  const src = read("components", "opportunities", "DecisionPanel.tsx");
  assert.doesNotMatch(src, /\.catch\(\(\) => alive && setDecision\(null\)\)/);
  assert.match(src, /setLoadError\(describeFailure\(e\)\);/);
  assert.match(src, /저장된 결정을 읽지 못했습니다 — \{loadError\}/);
  assert.match(src, /const locked = busy \|\| !loaded \|\| loadError !== null;/);
  assert.equal(src.match(/disabled=\{locked\}/g)?.length, 2);
});

test("lists-3 · fallback-2: 이번 주 할 일은 못 받은 출처를 「없습니다」로 세지 않는다", () => {
  const src = read("components", "cosmos", "ThisWeekPanel.tsx");
  // 그 출처 항목이 하나도 없을 때만 실패(저장본으로 대신 받은 날은 아님 · 통합 검토 backend-3) — 공통 sourceFailure
  assert.match(src, /setSourceErrors\(\s*Object\.keys\(response\.source_errors \?\? \{\}\)\s*\.map\(\(source\) => \[source, sourceFailure\(response, source\)\] as const\)/);
  assert.match(src, /\?\? "다른 출처"\} 목록을 받지 못했습니다 — \{message\}/);
  assert.match(src, /\{sourceErrors\.length > 0 \? "받은 목록에서는 " : ""\}이번 주엔 마감이 닥친 건이 없습니다/);
});

test("links-6: 지원사업 신청 분석의 「← 사업기회」는 들어온 조건(from)으로 — 작성 화면과 같은 규칙", () => {
  const src = page();
  assert.match(src, /function rowRoute\(row: Row, back = ""\)/);
  assert.match(src, /back && base\.startsWith\("\/support\/"\) \? `\$\{base\}\$\{base\.includes\("\?"\) \? "&" : "\?"\}from=\$\{encodeURIComponent\(back\)\}`/);
  // 한 줄 행 · 전체 보기 카드 · 쉬운 보기 카드(2.3.0) — 셋 다 같은 돌아갈 주소 규칙
  assert.equal(src.match(/rowRoute\(row, useContext\(PlanBackContext\)\)/g)?.length, 3);
  const shell = read("components", "support", "SupportShell.tsx");
  assert.match(shell, /return \/\^\\\?\[\^#\\s\]\*\$\/\.test\(from\) \? `\/opportunities\$\{from\}` : "\/opportunities";/);
  // 「← 레이더」도 레이더 조건(rfrom)으로 돌아간다(2.0.6 · links-6 레이더 쪽)
  assert.match(shell, /href=\{link\.href === "\/opportunities" \? opportunitiesHref : link\.href === "\/radar" \? radarHref : link\.href\}/);
});
