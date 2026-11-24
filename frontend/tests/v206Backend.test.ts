/**
 * 2.0.6 — 「검토 중」 · 「선제준비」 패널이 서버가 새로 싣는 값을 쓰는가(서버 쪽은 backend/tests/test_v206_consistency.py).
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/v206Backend.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

test("검토 중: 지원사업 · 직접 넣은 공고는 서버가 준 갈 곳으로 — 대시보드 주소는 입찰만", () => {
  const panel = read("components", "opportunities", "ReviewQueuePanel.tsx");
  assert.match(panel, /href=\{item\.open_path \?\? `\/analysis\?notice=/, "open_path 가 있으면 그 화면으로 링크해야 합니다");
});

test("검토 중: 입찰 정리표 단추는 입찰에만 — 지원사업 줄에서 직전에 보던 다른 입찰의 정리표가 열렸다", () => {
  const panel = read("components", "opportunities", "ReviewQueuePanel.tsx");
  assert.match(panel, /const bid = \(item\.kind \?\? "bid"\) === "bid";/);
  assert.match(panel, /\{!openable && bid && \(/, "정리표 단추 묶음이 bid 조건 안에 있어야 합니다");
});

test("검토 중 타입: kind · open_path 를 받는다", () => {
  const types = read("types", "reviewQueue.ts");
  assert.match(types, /kind\?: "bid" \| "support" \| "manual";/);
  assert.match(types, /open_path\?: string \| null;/);
});

test("선제준비: 나라장터를 못 읽었으면 「보일 것이 없습니다」 대신 사유를 보인다", () => {
  const panel = read("components", "opportunities", "PreparePanel.tsx");
  assert.match(panel, /section\?\.source_error && \(/, "사유 줄이 있어야 합니다");
  assert.match(panel, /나라장터 목록을 읽지 못해 사전규격을 고르지 못했습니다 — \{section\.source_error\}/);
  assert.match(panel, /section && !section\.source_error && section\.items\.length === 0 && \(/, "빈 안내는 오류가 없을 때만");
  assert.match(read("types", "opportunity.ts"), /source_error\?: string \| null;/);
});
