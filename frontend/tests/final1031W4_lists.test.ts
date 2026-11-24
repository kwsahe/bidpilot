/**
 * 10-31 최종 점검 W4 — 사업기회 머리 줄 · 이번 주 할 일 머리 글 · 검토 중 「id 를 씁니다」 문구.
 *
 * 부품(.tsx)은 node 시험이 바로 불러오지 못한다 — 고친 자리의 소스 글을 본다(v206Opportunities.test.ts 와 같은 방식).
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/final1031W4_lists.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

test("① 실무순 머리 줄 — 비추천 · 제외는 덩어리 대신 제 칸 머리 줄(같은 머리 되풀이 · 엉뚱한 머리 아래 없음)", () => {
  const page = read("app", "opportunities", "page.tsx");
  assert.match(page, /비추천: "여기부터 비추천\(관련 낮음\)"/);
  assert.match(page, /제외: "여기부터 제외\(불가 · 마감\)"/);
  // 열쇠는 서버 정렬(practical_key)처럼 비추천 · 제외를 덩어리보다 먼저 본다
  assert.match(page, /group === "비추천" \|\| group === "제외" \? group : row\.unified\?\.practical_block/);
  // 머리 줄 경계는 그 열쇠로만 — practical_block 을 바로 견주지 않는다
  assert.match(page, /const block = blockHeadKey\(row\);/);
  assert.match(page, /const prevBlock = index > 0 \? blockHeadKey\(pagedRows\[index - 1\]\) : null;/);
  assert.doesNotMatch(page, /pagedRows\[index - 1\]\.unified\?\.practical_block/);
});

test("② 이번 주 할 일 머리 — 지원사업을 고르는 기준(회사 갈래 · 지원분야)을 적는다", () => {
  const panel = read("components", "cosmos", "ThisWeekPanel.tsx");
  assert.match(panel, /지원사업은 회사 갈래 · 지원분야가 맞고 바로 손댈 수 있는 것만 올립니다/);
  // 규칙은 그대로
  assert.match(panel, /if \(item\.kind_fit === false\) return false;/);
  assert.match(panel, /if \(!SUPPORT_CATEGORIES\.has\(item\.category \?\? ""\)\) return false;/);
});

test("③ 검토 중 — 제목이 공고명이면 「공고명 대신 공고 id 를 씁니다」를 붙이지 않는다", () => {
  const panel = read("components", "opportunities", "ReviewQueuePanel.tsx");
  // id 문구는 제목이 id 그대로일 때만
  assert.match(panel, /item\.title === item\.procurement_id\s*\?\s*"받아 둔 목록에서 내려간 공고입니다 — 공고명 대신 공고 id 를 씁니다\."/);
  assert.match(panel, /"받아 둔 목록에서 내려간 공고입니다\."/);
  // 「입찰 분석으로는 열 수 없습니다」는 그대로 뒤에 붙는다
  assert.match(panel, /!openable && " 입찰 분석으로는 열 수 없습니다\."/);
});
