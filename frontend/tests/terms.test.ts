/**
 * 화면 공통 사전 (27차 §3-E-1) — 같은 것을 두 사전이 다른 말로 부르지 않는다.
 *
 * 실행: `npm test` (frontend 폴더에서). 옛 말이 화면 문장에 남았는지는 `scripts/check_screen_vocabulary.mjs` 가 본다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { DECISION_LABELS, ELIGIBILITY_LABELS, formatBudgetCompact, sourceFieldText } from "../src/lib/cosmos/format.ts";
import { WORKFLOW_STEPS } from "../src/lib/cosmos/graph.ts";
import { withinDaysText } from "../src/lib/deadline.ts";
import { COLLECT_UNKNOWN_TERM, ELIGIBILITY_TERMS, FROZEN_TERM, NO_BUDGET, SCREEN_NAMES, STEP_NAMES, UNDECIDED, collectTerm, collectWarns, reviewPriorityText } from "../src/lib/terms.ts";

test("참가 판정은 한 사전 — 대시보드도 「가능 · 확인 필요 · 불가」 (UNI-05)", () => {
  assert.equal(ELIGIBILITY_LABELS, ELIGIBILITY_TERMS);
  assert.deepEqual([ELIGIBILITY_LABELS.PASS, ELIGIBILITY_LABELS.CHECK, ELIGIBILITY_LABELS.FAIL], ["가능", "확인 필요", "불가"]);
});

test("미정 상태는 「결정 전」 하나 (UNI-15)", () => {
  assert.equal(UNDECIDED, "결정 전");
  assert.equal(DECISION_LABELS.UNREVIEWED, UNDECIDED);
});

test("단계 이름 8 = 레일 이름 (graph 가 사전에서 읽는다)", () => {
  assert.deepEqual(
    WORKFLOW_STEPS.map((step) => step.label),
    Object.values(STEP_NAMES),
  );
});

test("금액은 「6,000만원」 꼴 하나 · 없으면 「예산 미공개」 (UNI-08)", () => {
  assert.equal(formatBudgetCompact(60_000_000), "6,000만원");
  assert.equal(formatBudgetCompact(150_000_000), "1.5억원");
  assert.equal(formatBudgetCompact(null), NO_BUDGET);
});

test("검토 우선순위는 단위 없이 · 없으면 「미산정」 (UNI-14)", () => {
  assert.equal(reviewPriorityText(83), "검토 우선순위 83");
  assert.equal(reviewPriorityText(null), "검토 우선순위 점수 없음");
});

test("곧 마감은 「7일 안 마감」 — 맨 「마감」은 지난 것에만 (UNI-06)", () => {
  assert.equal(withinDaysText(7), "7일 안 마감");
});

test("요구사항 정리표 탭 이름 · 사업계획서 작성 메뉴 이름 (LNK-05 · 28차)", () => {
  assert.equal(SCREEN_NAMES.plan, "사업계획서 작성");
  assert.equal(SCREEN_NAMES.rfp, "요구사항 정리표");
});

test("조건 근거 칸 — 「나라장터 기본정보」를 두 번 붙이지 않는다(33차 R32-01)", () => {
  assert.equal(sourceFieldText("나라장터 기본정보 — bidQlfctRgstDt=2026-10-10"), "나라장터 기본정보 — bidQlfctRgstDt=2026-10-10");
  assert.equal(sourceFieldText("공고 첨부"), "공고 첨부");
  // 입찰공고문 · 제안요청서 인용은 그대로(34차 R33-05)
  assert.equal(sourceFieldText("입찰공고문 「참가자격 … 」"), "입찰공고문 「참가자격 … 」");
  assert.equal(sourceFieldText('제안요청서 12쪽 "교육 운영은 …"'), '제안요청서 12쪽 "교육 운영은 …"');
  assert.equal(sourceFieldText("bidQlfctRgstDt"), "나라장터 기본정보 bidQlfctRgstDt");
  assert.equal(sourceFieldText("bidClseDt"), "나라장터 기본정보 bidClseDt");
});

test("자동 받기 한 줄은 collectTerm 하나 — 모름 · 키트 · 오늘 아직 · 받는 중 · 꺼 둠 · 오늘 받음 (39차 §3-F-2 · 40차 D30 · FRONT-05)", () => {
  // 상태를 아직 모르면(불러오는 중 · 통합 목록 실패) 중립 글 — 「꺼짐」을 그리지 않는다
  assert.equal(collectTerm(null), COLLECT_UNKNOWN_TERM);
  assert.equal(collectTerm(undefined, null, true), COLLECT_UNKNOWN_TERM);
  assert.equal(collectTerm({ kind: "none", text: null }), FROZEN_TERM);
  const missed = { kind: "missed" as const, text: "오늘 목록을 아직 받지 않았습니다 — 마지막 10/19 09:41 · 「지금 받기」를 두 번 누르세요(scripts\지금_받기.bat)" };
  assert.equal(collectTerm(missed), missed.text);
  assert.equal(collectTerm(missed, null, true), "오늘 목록 아직");
  const running = { kind: "running" as const, text: "오늘 목록 받는 중 — 09:12 시작" };
  assert.equal(collectTerm(running), running.text);
  assert.equal(collectTerm(running, null, true), "받는 중");
  const off = { kind: "off" as const, text: "자동 받기 꺼 둠 — 목록은 10/19 09:41 그대로" };
  assert.equal(collectTerm(off), off.text);
  assert.equal(collectTerm(off, null, true), "자동 받기 꺼 둠");
  const ok = { kind: "ok" as const, text: "매일 처음 켤 때 자동으로 받음 · 오늘 09:12", last_success: "2026-10-20T00:12:09Z" };
  assert.equal(collectTerm(ok), ok.text);
  assert.equal(collectTerm(ok, "2026-10-20T00:12:40Z"), "자동으로 받음"); // 「목록 받은 때」와 같은 분이면 짧게
  assert.equal(collectTerm(ok, null, true), "자동으로 받음");
  // COLLECT-01 — 일부 실패 꼬리는 줄인 글에도 남는다
  const partial = { ...ok, text: ok.text + " · 일부 실패(지난 저장본으로 채움)", suffix: " · 일부 실패(지난 저장본으로 채움)" };
  assert.equal(collectTerm(partial, "2026-10-20T00:12:40Z"), "자동으로 받음 · 일부 실패(지난 저장본으로 채움)");
  assert.equal(collectTerm(partial, null, true), "자동으로 받음 · 일부 실패");
  // 44차 마지막 검토 — AI 보조 쉼 꼬리 하나만이면 받기는 다 성공했다(줄인 글에 「일부 실패」를 붙이지 않음)
  const aiRest = { ...ok, text: ok.text + " · AI 보조 쉼 — Claude 로그인 필요(관리자)", suffix: " · AI 보조 쉼 — Claude 로그인 필요(관리자)" };
  assert.equal(collectTerm(aiRest, null, true), "자동으로 받음");
  const bizMiss = { ...ok, text: ok.text + " · 기업마당 못 받음", suffix: " · 기업마당 못 받음" };
  assert.equal(collectTerm(bizMiss, null, true), "자동으로 받음 · 일부 실패");
  // 경고(⏸ 호박)는 키트 · 오늘 아직만 — 모름 · 받는 중 · 꺼 둠 · 오늘 받음은 보통색(COLLECT-08 · FRONT-06)
  assert.deepEqual(
    [null, { kind: "none" as const }, missed, running, off, ok].map((s) => collectWarns(s)),
    [false, true, true, false, false, false],
  );
});
