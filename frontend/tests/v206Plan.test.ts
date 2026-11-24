/**
 * 2.0.6 — 제안서 · 사업계획서 작성 화면(/plan)이 다른 화면과 같은 값 · 같은 후보를 말한다
 * (점검 워크플로 lists-1 · links-3 · values-1 · values-6 · lists-3 · fallback-2 · fallback-5 · state-2 · lists-4).
 *
 * page.tsx 는 JSX 라 Node 가 바로 읽지 못한다 — 순수 함수(realDeadline · isPickable · headDeadlineOf · savedBadge)는 소스에서 떼어
 * 임시 파일로 돌리고(타입은 Node 가 지운다), 나머지는 소스 글로 본다(externalCheckSupportPlanRadar.test.ts 와 같은 방식).
 */

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, describe, it } from "node:test";

const ROOT = join(import.meta.dirname, "..");
// Windows 작업 폴더는 CRLF 로 풀린다 — 함수 끝(「\n}\n」)을 찾으려고 줄바꿈을 맞춘다
const PAGE = readFileSync(join(ROOT, "src", "app", "plan", "page.tsx"), "utf8").replace(/\r\n/g, "\n");

/** 맨 앞 칸에서 시작하는 함수 하나를 소스에서 떼어 낸다(닫는 괄호도 맨 앞 칸). */
function fn(name: string): string {
  const start = PAGE.indexOf(`\nfunction ${name}(`);
  assert.ok(start >= 0, `page.tsx 에 ${name} 함수가 없다`);
  return PAGE.slice(start, PAGE.indexOf("\n}\n", start) + 3);
}

const dir = mkdtempSync(join(tmpdir(), "v206plan-"));
const helperFile = join(dir, "helpers.ts");
const deadlineUrl = pathToFileURL(join(ROOT, "src", "lib", "deadline.ts")).href;
writeFileSync(
  helperFile,
  `import { dDayText, deadlineTerm, effectiveDeadline, firstLabel, formatDeadlineStamp, isOpenEnded, pairOf, registrationClosesFirst } from ${JSON.stringify(deadlineUrl)};\n` +
    ["realDeadline", "isPickable", "headDeadlineOf", "savedBadge"].map(fn).join("\n") +
    "\nexport { realDeadline, isPickable, headDeadlineOf, savedBadge };\n",
);
type Item = Record<string, unknown>;
const helpers = (await import(pathToFileURL(helperFile).href)) as {
  realDeadline: (item: Item | undefined) => string | null;
  isPickable: (item: Item) => boolean;
  headDeadlineOf: (item: Item, nowMs: number | null) => { text: string; closed: boolean; bidLine: string | null };
  savedBadge: (saved: unknown, failed?: boolean) => { label: string };
};

// 2026-10-27 12:00 KST
const NOW = Date.parse("2026-10-27T03:00:00Z");
const BID = "2026-11-06T10:00:00+09:00"; // D-10
const REG = "2026-11-05T18:00:00+09:00"; // D-9
const g2b = (extra: Item = {}): Item => ({ source_type: "g2b", closed: false, deadline: BID, eligibility_gate: "CHECK", ...extra });

describe("/plan 머리 · 고르기 행 마감 — 다른 화면과 같은 실제 마감(values-1)", () => {
  after(() => rmSync(dir, { recursive: true, force: true }));

  it("등록마감이 먼저면 「등록마감 D-9」 + 입찰 마감은 옆 줄 — 예전엔 「입찰 마감 D-10」", () => {
    const head = helpers.headDeadlineOf(g2b({ qualification_deadline: REG }), NOW);
    assert.equal(head.text, "등록마감 D-9");
    assert.equal(head.closed, false);
    assert.match(head.bidLine ?? "", /^입찰 마감 11-6 10:00$/);
    assert.equal(helpers.realDeadline(g2b({ qualification_deadline: REG })), REG);
  });

  it("공고문 일정 마감이 더 이르면 그 이름으로 센다", () => {
    const head = helpers.headDeadlineOf(g2b({ qualification_deadline: REG, schedule_deadline: "2026-11-01T17:00:00+09:00", schedule_deadline_label: "참가신청 마감" }), NOW);
    assert.equal(head.text, "참가신청 마감 D-5");
  });

  it("등록마감만 지났으면 「등록마감 지남」(사업기회 행과 같은 낱말)", () => {
    assert.equal(helpers.headDeadlineOf(g2b({ qualification_deadline: "2026-10-26T18:00:00+09:00" }), NOW).text, "등록마감 지남");
  });

  it("마감 하나뿐이면 예전 그대로 · 마감된 공고는 「입찰 종료」 · 지원사업은 「신청 마감」", () => {
    assert.equal(helpers.headDeadlineOf(g2b(), NOW).text, "입찰 마감 D-10");
    assert.deepEqual(helpers.headDeadlineOf(g2b({ closed: true }), NOW), { text: "입찰 종료", closed: true, bidLine: null });
    assert.equal(helpers.headDeadlineOf({ source_type: "bizinfo", closed: false, deadline: "2026-11-03T23:59:00+09:00" }, NOW).text, "신청 마감 D-7");
    assert.equal(helpers.realDeadline(undefined), null);
  });

  it("상시 · 마감일 없음은 낱말 하나 — 예전엔 「상시·예산 소진 시 상시·예산 소진 시」 · 「접수 기간 미정 마감일 미정」", () => {
    const support = (extra: Item): Item => ({ source_type: "bizinfo", closed: false, deadline: null, ...extra });
    assert.equal(helpers.headDeadlineOf(support({ apply_period_kind: "always_open" }), NOW).text, "상시·예산 소진 시");
    assert.equal(helpers.headDeadlineOf(support({ apply_period_kind: "until_budget", deadline: "2026-11-03T23:59:00+09:00" }), NOW).text, "상시·예산 소진 시");
    assert.equal(helpers.headDeadlineOf(support({}), NOW).text, "접수 기간 미정");
    assert.equal(helpers.headDeadlineOf(g2b({ deadline: null }), NOW).text, "접수 기간 미정");
  });
});

describe("/plan 고르기 후보 · 머리 판정(lists-1 · links-3 · lists-4 · values-6)", () => {
  it("목록은 마감 · 불가까지 받고, 고르기 후보는 사업기회 기본 화면처럼 마감 · 불가 · 관련 낮음을 뺀다", () => {
    assert.match(PAGE, /getBusinessOpportunities\(\{ organizationId, source: "bizinfo", days, includeBlocked: true, includeClosed: true \}\)/);
    assert.match(PAGE, /getBusinessOpportunities\(\{ organizationId, source: "g2b", days, includeBlocked: true, includeClosed: true \}\)/);
    assert.doesNotMatch(PAGE, /limit: 200/);
    assert.match(PAGE, /filter\(\(item\) => isPickable\(item\) && \(matches\(item\.title\)/);
    assert.equal(helpers.isPickable(g2b()), true);
    assert.equal(helpers.isPickable(g2b({ closed: true })), false);
    assert.equal(helpers.isPickable(g2b({ eligibility_gate: "FAIL" })), false);
    assert.equal(helpers.isPickable(g2b({ practical_group: "비추천" })), false);
    assert.equal(helpers.isPickable({ source_type: "bizinfo", closed: false, relevance_note: "식품 사업" }), false);
  });

  it("고르기 행 마감 글은 머리와 같은 headDeadlineOf — 등록마감만 지난 열린 입찰이 행은 「마감」, 머리는 「등록마감 지남」이었다", () => {
    assert.match(PAGE, /const deadlineTextOf = \(item: UnifiedOpportunity \| undefined\) => \(item && realDeadline\(item\) \? headDeadlineOf\(item, nowMs\)\.text : null\);/);
    assert.match(PAGE, /deadlineText: deadlineTextOf\(item\) \}/);
    assert.match(PAGE, /deadlineText: deadlineTextOf\(unifiedById\.get\(row\.id\)\)/);
    assert.match(PAGE, /\{row\.deadlineText && <span[^>]*>\{row\.deadlineText\}<\/span>\}/);
    // 행에서 따로 세던 꼴 — 음수 일수를 「마감」으로 적었다
    assert.doesNotMatch(PAGE, /row\.closed \? "마감"/);
    assert.doesNotMatch(PAGE, /dDayText\(\{ deadline: row\.deadline/);
    assert.doesNotMatch(PAGE, /dDayText\(\{ deadline: here\.deadline/);
  });

  it("마감된 입찰 · 지원사업은 새 초안 단추를 잠근다(저장본 보기 · 내려받기는 그대로)", () => {
    assert.match(PAGE, /const closedBlock = closed \? CLOSED_BLOCK : null;/);
    assert.match(PAGE, /closed=\{bidClosed\}/);
    assert.match(PAGE, /closedNote=\{here\?\.closed \? CLOSED_BLOCK :/);
  });

  it("입찰도 목록을 다 받기 전(마감 여부를 모를 때)엔 새 초안 단추를 잠근다 — 지원사업 45차 M1 과 같은 꼴", () => {
    const bid = fn("BidWriter");
    assert.match(bid, /infoLoading = false,/);
    // 10-31 최종 점검 — 요구사항이 있는지 읽는 동안도 잠근다(읽기 전 몇 초 Claude 단추가 열렸다)
    // 11-03 — 분석 원문이 공고서뿐이면(제안요청서 없음) 쓰기를 잠그고 「제안요청서로 다시 분석」으로 보낸다
    // 열람자 · 읽기 전용 사유(draftBlock)가 그 앞 — 가려지지 않게 · 가상 예시 공고는 쓰지 않는다(11-03 검토)
    assert.match(bid, /const blockReason = closedBlock \?\? \(infoLoading \? INFO_LOADING_BLOCK : null\) \?\? \(checking \? "요구사항이 있는지 확인하는 중입니다" : null\) \?\? \(cutWait \? CUT_BLOCK : null\) \?\? draftBlock \?\? \(isDemoProcurementId\(noticeId\) \? DEMO_BID_BLOCK : null\) \?\? \(rfpRole === "notice" \? NO_RFP_BLOCK : null\);/);
    assert.match(bid, /const checking = adopted === null && notParsed === null && countFailed === null;/);
    assert.match(PAGE, /<BidWriter [^>]*closed=\{bidClosed\} infoLoading=\{infoLoading\} \/>/);
    // 지원사업도 같은 낱말(상수 하나)
    assert.match(fn("SupportWriter"), /\(infoLoading \? INFO_LOADING_BLOCK : null\)/);
  });

  it("머리 판정은 verdictOf — 공급기업 자리면 「간접 참여」(사업기회 행 · 지원사업 화면과 같은 말)", () => {
    assert.match(PAGE, /verdictOf\(here\.eligibility_gate, here\.participation\)/);
    assert.doesNotMatch(PAGE, /ELIGIBILITY_GATE_LABELS/);
  });

  it("머리에 판정 · 마감을 못 그리면 말없이 비우지 않는다 · 상세 읽기 실패는 사유 한 줄", () => {
    assert.match(PAGE, /setDetailFailed\(\{ id: target\.id, reason: describeFailure\(error\) \}\)/);
    assert.match(PAGE, /`공고 정보를 읽지 못했습니다 — \$\{farFailed\}`/);
    assert.match(PAGE, /판정 · 마감을 여기서 보이지 못합니다/);
  });

  it("머리 안내는 화면에서 따라 할 수 있는 길만 — 이때는 「공고 원문 ↗」 링크가 없어 「공고 원문에서 확인하세요」를 따를 수 없었다", () => {
    assert.doesNotMatch(PAGE, /공고 원문에서 확인하세요/);
    assert.match(PAGE, /"목록을 받지 못해 판정 · 마감을 여기서 보이지 못합니다 — 잠시 뒤 화면을 다시 열어 보세요"/);
    assert.match(PAGE, /사업기회에서 조회 기간을 넓혀 그 행에서 확인하세요"/);
  });
});

describe("/plan 실패와 「없음」 구분(lists-3 · fallback-2 · fallback-5)", () => {
  it("한 출처만 실패한 200 응답(source_errors)은 그 탭에 「받지 못했습니다」 · 「0건 중」을 그리지 않는다", () => {
    // 항목이 왔으면(저장본으로 대신 받은 날) 실패가 아니다 — 공통 sourceFailure(통합 검토 backend-3)
    assert.match(PAGE, /support: sourceFailure\(support, "bizinfo"\), notice: sourceFailure\(bid, "g2b"\)/);
    assert.match(PAGE, /!== null && !sourceFailed\[tab\] && \(\s*<span[^>]*data-plan-picker-count/);
    assert.match(PAGE, /목록을 받지 못했습니다 — \{sourceFailed\[tab\]\}/);
  });

  it("전체 초안 읽기는 404 만 「초안 없음」 · 다른 실패는 사유를 보이고 빈 안내를 그리지 않는다", () => {
    assert.doesNotMatch(PAGE, /\.catch\(\(\) => alive && setDoc\(null\)\)/);
    assert.match(PAGE, /setDocFailed\(error instanceof ApiError && error\.status === 404 \? null : describeFailure\(error\)\)/);
    assert.match(PAGE, /proposalBody \?\? \(!docFailed && \(/);
  });

  it("새 초안을 쓰면 읽기 실패 경고를 지운다 — 방금 만든 초안 위에 「읽지 못했습니다」가 남았다", () => {
    const bid = fn("BidWriter");
    const start = bid.indexOf("const write = async");
    assert.ok(start > 0);
    const write = bid.slice(start, bid.indexOf("\n  };\n", start));
    assert.match(write, /setDoc\(await createBidPlan\([^\n]*\n\s*setDocFailed\(null\);/);
  });

  it("저장본 목록을 못 읽으면 행 표지는 「초안 확인 못 함」 · 「저장본은 아래에」라 적지 않는다", () => {
    assert.doesNotMatch(PAGE, /\.catch\(\(\) => alive && setSaved\(\[\]\)\)/);
    assert.equal(helpers.savedBadge(undefined, true).label, "초안 확인 못 함");
    assert.equal(helpers.savedBadge(undefined).label, "초안 없음");
    assert.match(PAGE, /savedBadge\(savedById\.get\(row\.id\), savedFailed !== null\)/);
    assert.match(PAGE, /\{savedFailed \? "" : " \(저장본은 아래에 그대로 보입니다\)"\}/);
  });
});

describe("/plan 이 주소로 받은 대상을 기억한다(state-2)", () => {
  it("지원사업은 rememberSupport · 입찰은 writeSelection(replace) — 대상을 찾았을 때만 · 가상 예시 제외", () => {
    const start = PAGE.indexOf("const found = Boolean(here || far);");
    assert.ok(start > 0);
    const block = PAGE.slice(start, PAGE.indexOf("}, [targetKind, targetId, demo, found]);", start));
    assert.match(block, /if \(!targetId \|\| demo \|\| !found\) return;/);
    assert.match(block, /if \(targetKind === "support"\) rememberSupport\(targetId\);/);
    assert.match(block, /else writeSelection\(targetId, "replace"\);/);
  });
});
