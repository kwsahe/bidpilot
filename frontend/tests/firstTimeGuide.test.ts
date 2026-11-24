/**
 * 처음 하는 사람 안내 (31차 §3-B) — 준비 상태 줄 합치기 · 저장 목록 · 유효기간 · 마감 며칠 전 할 일.
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { bidDeadlineAdvice, expiringCounts, expiringCredentials, expiringLine, readinessRows, readinessToSave, validityOf } from "../src/lib/firstTimeGuide.ts";
import {
  BID_DEADLINE_REGISTRATION_FIRST,
  BID_DEADLINE_STEPS,
  FIRST_TIME_END,
  FIRST_TIME_G2B,
  FIRST_TIME_SUPPORT,
  OUTSIDE_G2B,
  OUTSIDE_NOTE,
  READINESS_ROWS,
  SUPPORT_DEADLINE_LINE,
  FIRST_SUPPORT_LINE,
  SUPPORT_FINISH_LINES,
} from "../src/lib/terms.ts";

const DAY = 86_400_000;
// 2026-10-04 12:00 KST
const NOW = Date.parse("2026-10-04T12:00:00+09:00");
const at = (days: number) => new Date(NOW + days * DAY).toISOString();

test("준비 상태 — 기본 줄 일곱 + 저장된 다른 줄 · 이름이 비슷하면(띄어쓰기 · 괄호) 같은 줄", () => {
  const rows = readinessRows([
    { name: "중소기업확인서", held: null, note: "후보 문서 있음", source: null },
    { name: "소프트웨어사업자 신고 (컴퓨터관련서비스사업)", held: true, note: null, source: "담당자" },
    { name: "여성기업 확인서", held: false, note: null, source: null },
  ]);
  assert.equal(rows.length, READINESS_ROWS.length + 1);
  assert.deepEqual(rows.slice(0, 7).map((r) => r.label), [...READINESS_ROWS]);
  const sme = rows.find((r) => r.label === "중소기업(소상공인) 확인서");
  assert.equal(sme?.note, "후보 문서 있음");
  assert.equal(rows.find((r) => r.label === "소프트웨어사업자 신고(1468)")?.held, true);
  assert.equal(rows.at(-1)?.label, "여성기업 확인서");
});

test("저장 목록 — 「모름 + 메모 없음」 기본 줄은 안 보내고, 저장된 줄은 이름 · 출처를 지킨다", () => {
  const rows = readinessRows([{ name: "중소기업확인서", held: null, note: null, source: "옛 출처" }]);
  const g2b = rows.findIndex((r) => r.label === "나라장터 입찰참가자격 등록");
  rows[g2b] = { ...rows[g2b], held: true, validUntil: "2027-10-01" };
  const saved = readinessToSave(rows, "회사자료 준비 상태 · 시험");
  assert.deepEqual(saved.map((r) => r.name), ["나라장터 입찰참가자격 등록", "중소기업확인서"]);
  assert.equal(saved[0].source, "회사자료 준비 상태 · 시험");
  assert.equal(saved[0].valid_until, "2027-10-01");
  assert.equal(saved[1].source, "옛 출처"); // 모름이어도 이미 저장된 줄은 남는다
});

test("유효기간 — 오늘 + 10일은 곧 만료 · 비우면 사라짐 · 지난 날짜는 만료됨 · 31일 뒤는 없음", () => {
  assert.equal(validityOf("2026-10-14", NOW), "soon");
  assert.equal(validityOf("", NOW), null);
  assert.equal(validityOf(null, NOW), null);
  assert.equal(validityOf("2026-10-03", NOW), "expired");
  assert.equal(validityOf("2026-10-04", NOW), "soon"); // 그날 끝까지 유효
  assert.equal(validityOf("2026-11-05", NOW), null);
  const lines = expiringCredentials(
    [
      { name: "중소기업(소상공인) 확인서", held: true, note: null, source: null, valid_until: "2026-10-14" },
      { name: "공동인증서", held: true, note: null, source: null, valid_until: "2026-09-30" },
      { name: "창업기업 확인서", held: true, note: null, source: null, valid_until: null },
    ],
    NOW,
  );
  assert.deepEqual(lines.map((l) => [l.name, l.state]), [["공동인증서", "expired"], ["중소기업(소상공인) 확인서", "soon"]]);
});

test("마감 며칠 전 할 일 — 16 · 6 · 2일 전 문장이 바뀌고 마감 · 마감일 없음은 줄이 없다", () => {
  assert.equal(bidDeadlineAdvice({ qualification: null, bid: at(16) }, NOW), BID_DEADLINE_STEPS.early);
  assert.equal(bidDeadlineAdvice({ qualification: null, bid: at(6) }, NOW), BID_DEADLINE_STEPS.soon);
  assert.equal(bidDeadlineAdvice({ qualification: null, bid: at(2) }, NOW), BID_DEADLINE_STEPS.urgent);
  assert.equal(bidDeadlineAdvice({ qualification: null, bid: at(-1) }, NOW), null);
  assert.equal(bidDeadlineAdvice({ qualification: null, bid: null }, NOW), null);
  assert.equal(bidDeadlineAdvice({ qualification: null, bid: at(6) }, null), null);
});

test("등록마감이 먼저면 등록마감 문구를 앞세우고 그 날로 센다", () => {
  const advice = bidDeadlineAdvice({ qualification: at(2), bid: at(9) }, NOW);
  assert.ok(advice?.startsWith(BID_DEADLINE_REGISTRATION_FIRST));
  assert.ok(advice?.endsWith(BID_DEADLINE_STEPS.urgent));
});

test("화면 글에 숫자 · 기간 · 비용 없음 — 예외 셋(전날 18:00 · 3월 31일 · 1468 업종 코드)만", () => {
  const screen = [
    ...FIRST_TIME_G2B, ...FIRST_TIME_SUPPORT, FIRST_TIME_END, ...OUTSIDE_G2B, OUTSIDE_NOTE,
    ...Object.values(BID_DEADLINE_STEPS), SUPPORT_DEADLINE_LINE, ...SUPPORT_FINISH_LINES,
  ];
  for (const line of screen) {
    const rest = line.replace("전날 18:00", "").replace("3월 31일", "").replace("1468", "").replace("g2b", "");
    assert.doesNotMatch(rest, /\d/, line);
  }
  assert.ok(OUTSIDE_NOTE.includes("일반 절차 안내 · 공고문이 우선"));
  // 공고 조건 설명 옆에 붙는 안내 문장도 꼬리를 단다(31차 마지막 검토)
  for (const line of [FIRST_SUPPORT_LINE, SUPPORT_DEADLINE_LINE, SUPPORT_FINISH_LINES[SUPPORT_FINISH_LINES.length - 1]]) {
    assert.ok(line.endsWith("(일반 절차 안내 · 공고문이 우선)"), line);
  }
  assert.ok(FIRST_TIME_SUPPORT.some((line) => line.includes("K-Startup")));
});

test("32차 §3-B 새 안내 글 — 숫자 · 기간 · 비용 없음 · /plan 다음 할 일은 접수처를 넣는다", async () => {
  const terms = await import("../src/lib/terms.ts");
  for (const line of [terms.FIRST_BID_SHORT, terms.SUPPORT_WHERE_LINE, terms.AI_DRAFT_CAUTION, terms.SUBMIT_DRAFT_NOTE, terms.READINESS_NOT_USED, ...terms.planNextSteps(null)]) {
    assert.doesNotMatch(line, /\d/, line);
  }
  assert.ok(terms.planNextSteps("이메일 또는 방문 접수")[1].includes("접수처(이메일 또는 방문 접수)"));
  assert.ok(terms.planNextSteps(null)[1].includes("「신청 방법」"));
});

test("32차 §3-D — 신용평가 뺀 마감 여유 문장 · 곧 만료 꼬리는 그 서류가 필요한 공고만 · 손대지 않은 줄의 출처는 그대로", async () => {
  const terms = await import("../src/lib/terms.ts");
  assert.ok(!terms.BID_DEADLINE_STEPS.early.includes("신용평가"), "R31-09");
  assert.ok(terms.EXPIRING_SOON_TAIL.includes("이 서류가 필요한 공고"), "R31-13");
  // R31-11 — 저장된 줄 둘(하나는 출처 없음) 중 하나만 고쳤다
  const rows = readinessRows([
    { name: "중소기업(소상공인) 확인서", held: true, note: null, source: null, valid_until: "2027-03-31" },
    { name: "직접생산확인증명서", held: false, note: null, source: "예전 담당자", valid_until: null },
  ]);
  const edited = rows.map((r) => (r.label === "직접생산확인증명서" ? { ...r, held: true } : r));
  const saved = readinessToSave(edited, "지금 담당자");
  assert.equal(saved.find((r) => r.name === "중소기업(소상공인) 확인서")?.source, null, "손대지 않은 줄 — 출처 그대로(없음)");
  assert.equal(saved.find((r) => r.name === "직접생산확인증명서")?.source, "지금 담당자", "고친 줄 — 지금 담당자");
});


test("곧 만료 · 만료됨 한 줄은 상태마다 머리말을 단다 — 유효한 서류가 「만료됨」 뒤에 섞이지 않는다(32차 마지막 검토)", () => {
  const rows = [
    { name: "중소기업(소상공인) 확인서", validUntil: "2026-03-31", state: "expired" as const },
    { name: "사업자 범용 공동인증서", validUntil: "2026-10-20", state: "soon" as const },
  ];
  assert.equal(expiringLine(rows), "만료됨: 중소기업(소상공인) 확인서 2026-03-31 · 곧 만료: 사업자 범용 공동인증서 2026-10-20");
  assert.equal(expiringLine([rows[1]]), "곧 만료: 사업자 범용 공동인증서 2026-10-20");
});

test("접힌 띠 머리 — 만료됨 · 곧 만료를 따로 센다(33차 R32-11)", () => {
  assert.equal(expiringCounts([{ state: "expired" }, { state: "soon" }, { state: "soon" }]), "만료됨 1 · 곧 만료 2");
  assert.equal(expiringCounts([{ state: "soon" }]), "곧 만료 1");
  assert.equal(expiringCounts([]), "");
});
