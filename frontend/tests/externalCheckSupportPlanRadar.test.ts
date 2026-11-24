/**
 * 외부 브라우저 점검(2026-11-24) — 지원사업 · 작성 화면 · 레이더 · 점수 설명 글이 옛 문장으로 돌아가지 않게.
 *
 * 실행: `npm test` (frontend 폴더에서). 화면을 띄우지 않고 소스 글로 본다(supportSource.test.ts 와 같은 방식).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

test("T4 — 쉬운 보기 표준 양식 안내는 서버 글(form.notice) 하나 · 제목 낱말로 따로 쓰지 않는다", () => {
  const src = read("components", "support", "SupportSimpleView.tsx");
  assert.match(src, /draft\.form\.notice/);
  assert.doesNotMatch(src, /startupOrRnd|창업 공통/);
});

test("UI f — /plan 입찰 초안은 새 저장본(제안요청서 목차대로)만 · 옛 전체 초안(가상 예시 포함) 내려받기를 쓰지 않는다", () => {
  // 11-03 — 옛 전체 초안(요구사항 한 줄 = 문장 한 줄 · 「확인 필요」 줄)은 /plan 에서 보이지도 받지도 않는다
  const src = read("app", "plan", "page.tsx");
  assert.doesNotMatch(src, /proposalFullExportUrl|getFullProposal|generateFullProposal/);
  assert.match(src, /urlFor=\{\(format, variant\) => bidPlanExportUrl\(noticeId, \{ format, variant \}, ctx\)\}/);
  assert.match(src, /data-bid-no-rfp/);
});

test("UI a · g — 레이더 끝줄은 점수순이라 하지 않고, 값 0 줄을 흐리게 하지 않는다", () => {
  assert.doesNotMatch(read("components", "radar", "RadarTrackedPanel.tsx"), /검토 우선순위가 높은/);
  assert.doesNotMatch(read("components", "radar", "RadarConsole.tsx"), /opacity: zero/);
  // 2D 글자 배율은 원래대로(키우면 원래 있던 겹침이 커졌다) — 데이터 블록 2행 간격은 배율을 따른다(배율 1이면 예전 9.4)
  const scene = read("components", "radar", "RadarScene2D.tsx");
  assert.match(scene, /const fs = compact \? 1\.2 : 1;/);
  assert.match(scene, /y=\{by \+ 2 \+ 7\.4 \* fs\}/);
});

test("UI b — 점수 기준 창: 「두 출처를 같은 순서에 놓는 값」을 빼고 실무 우선순위 회사에 순서 설명", () => {
  const src = read("app", "opportunities", "page.tsx");
  const start = src.indexOf("function ScoreBasisPopover");
  const popover = src.slice(start, src.indexOf("\nfunction ", start + 1));
  assert.ok(start > 0);
  assert.doesNotMatch(popover, /두 출처를 같은/);
  assert.match(popover, /useRankingMethod\(\) === "practical"/);
  assert.match(popover, /목록 순서는 점수순이 아닙니다/);
  assert.match(popover, /점수순으로 볼 때/);
});
