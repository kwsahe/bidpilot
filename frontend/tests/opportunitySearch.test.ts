/**
 * 사업기회 목록 검색 (0919 §4-B-6).
 *
 * 실행: `npm test` (frontend 폴더에서).
 *
 * 예전에는 제목·기관·공고번호만 봤다. 그래서 「RAG」·「챗봇」처럼 **본문에만 있는 말**로는
 * 한 건도 찾지 못했다. 범위를 넓히면서 판정 방식도 바꿔야 했는데, 그 이유를 여기 고정한다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { buildHaystack, matchesQuery } from "../src/lib/opportunitySearch.ts";

test("빈 값과 여분의 공백은 버린다", () => {
  assert.equal(buildHaystack(["가천대학교  AI 교육", null, "", undefined, "  광주  "]), "가천대학교 ai 교육 광주");
});

test("대소문자를 가리지 않는다", () => {
  const hay = buildHaystack(["생성형 AI 활용 실무교육"]);
  assert.ok(matchesQuery(hay, "ai"));
  assert.ok(matchesQuery(hay, "AI"));
});

test("검색어가 비면 전부 통과한다", () => {
  assert.ok(matchesQuery(buildHaystack(["무엇이든"]), "   "));
});

test("낱말을 따로 본다 — 붙여 찾으면 오히려 덜 찾는다", () => {
  /*
   * 범위를 넓히고 나면 찾는 말들이 **서로 다른 칸**에 흩어져 있다. 「AI」는 과업 키워드
   * 칩에, 「교육」은 제목에 있는 식이다. 입력한 글자를 통째로 찾으면 그 둘을 이어 붙인
   * 문자열이 어디에도 없어서 0건이 된다.
   */
  const hay = buildHaystack(["소방공무원 심리진단 시스템 개발", "AI", "교육"]);
  assert.ok(!hay.includes("ai 교육 시스템"), "전제: 통째로는 들어 있지 않다");
  assert.ok(matchesQuery(hay, "AI 교육"));
});

test("낱말 순서를 보지 않는다", () => {
  const hay = buildHaystack(["생성형 AI 활용 실무교육 운영"]);
  assert.ok(matchesQuery(hay, "교육 생성형"));
});

test("낱말이 하나라도 없으면 걸러낸다", () => {
  const hay = buildHaystack(["생성형 AI 활용 실무교육 운영"]);
  assert.ok(!matchesQuery(hay, "생성형 데이터베이스"));
});

test("요약·해시태그·과업 키워드까지 훑는다", () => {
  /* 담당자가 찾는 말은 대개 제목에 없다. 화면에 이미 보이는 것을 검색 대상에 넣는다. */
  const hay = buildHaystack([
    "경성대학교 다중모달 심리진단 시스템 개발 용역", // 제목
    "경성대학교 산학협력단", // 기관
    "R26BK01718694-000", // 공고번호
    "회사 사업영역과 일치: AI, 개발, 대학", // 한 줄 요약
    "RAG", // 과업 키워드 칩
    "#청년창업", // 해시태그
  ]);
  assert.ok(matchesQuery(hay, "RAG"), "본문에만 있는 말로도 찾아야 한다");
  assert.ok(matchesQuery(hay, "청년창업"));
  assert.ok(matchesQuery(hay, "산학협력단 RAG"), "서로 다른 칸의 낱말을 함께 찾아도 된다");
});
