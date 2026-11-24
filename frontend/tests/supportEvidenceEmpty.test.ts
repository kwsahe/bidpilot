/**
 * 지원사업 5단계 근거 0건의 이유 (27차 SUP-01 · ISSUE-164).
 *
 * 실행: `npm test` (frontend 폴더에서).
 *
 * 고정 모드에서는 회사 근거 검색을 하지 않아 0건인데, 화면이 「자료를 등록·승인하라」고 했다 —
 * 승인 자료가 있는 회사에도. 백엔드 사유 문장(evidence_service.match_requirements)을 그대로 넣어
 * 「검색 안 함」이면 등록 단추를 숨기고 「승인한 자료는 그대로 있습니다」라고 말하는지 고정한다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { evidenceEmptyState } from "../src/components/support/evidenceEmpty.ts";

// 백엔드 문장 그대로 (llm_client.EMBEDDING_OFF_REASON 을 감싼 match_requirements 의 사유).
const OFF =
  "회사 수행근거 연결에 실패했습니다. AI 의미 매칭(임베딩)이 꺼져 있습니다. 이 설정에서는 바깥 AI(OpenAI)를 부르지 않습니다(켜려면 관리자에게 요청). 규칙 기반 결과만 표시합니다.";
const NO_KEY = "AI 검색 설정이 없어 회사 수행근거 연결을 건너뜁니다. 규칙 기반 결과만 표시합니다.";
const FAILED = "회사 수행근거 연결에 실패했습니다. OpenAI 응답이 없습니다. 규칙 기반 결과만 표시합니다.";
// 회사 코드 대신 회사 이름을 쓴다 (evidence_service._empty_pool_reason · NEW-RFP-조직코드).
const NO_DOCS = "가상 AI교육 컴퍼니의 승인·색인된 회사자료가 없습니다. 회사자료 화면에서 자료를 등록·승인·색인하세요.";

test("임베딩 꺼짐 → 「AI 검색이 꺼져 있어 … 하지 않았습니다 — 승인한 자료는 그대로」 · 등록 단추 숨김", () => {
  const state = evidenceEmptyState(OFF);
  assert.equal(state.title, "AI 검색이 꺼져 있어 회사 근거 검색을 하지 않았습니다 — 승인한 자료는 그대로 있습니다");
  assert.equal(state.showRegister, false);
  assert.ok(!/등록/.test(state.body), state.body);
});

test("검색 설정 없음 → 검색 안 함 · 등록 단추 숨김 (시연 고정이라고 단정하지 않는다)", () => {
  const state = evidenceEmptyState(NO_KEY);
  assert.match(state.title, /검색을 하지 않았습니다 — 승인한 자료는 그대로 있습니다/);
  assert.ok(!state.title.includes("시연 고정"), state.title);
  assert.equal(state.showRegister, false);
});

test("검색 실패 → 등록 단추 숨김 · 원문 사유 줄은 남긴다", () => {
  const state = evidenceEmptyState(FAILED);
  assert.match(state.title, /실패/);
  assert.equal(state.showRegister, false);
  assert.equal(state.showNote, true);
});

test("자료가 정말 없으면 예전 안내 그대로 — 등록 단추를 보인다", () => {
  for (const note of [NO_DOCS, null, undefined, ""]) {
    const state = evidenceEmptyState(note);
    assert.equal(state.title, "연결된 승인 근거가 없습니다");
    assert.equal(state.showRegister, true);
  }
  // 「자료 없음」 사유 줄은 본문과 같은 말(+ 회사 코드)이라 숨기고, 등록부 읽기 실패 같은 다른 사유는 남긴다.
  assert.equal(evidenceEmptyState(NO_DOCS).showNote, false);
  assert.equal(evidenceEmptyState("조직(x)의 회사자료 등록부를 읽지 못했습니다 — JSON 이 깨져 격리됐습니다").showNote, true);
});

test("사용자 문장에 설정 이름 · 영어 코드가 없다", () => {
  for (const note of [OFF, NO_KEY, FAILED, NO_DOCS]) {
    const { title, body } = evidenceEmptyState(note);
    assert.ok(!/[A-Z][A-Z_]{4,}/.test(title + body), title + body);
  }
});
