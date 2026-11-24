/**
 * 화면 라벨 사전 — 영문 값이 새지 않게 고정한다 (0920 §4-B-1 · §3-11).
 *
 * 실행: `npm test` (frontend 폴더에서).
 *
 * 검수에서 화면에 그대로 찍히던 영문 값들이다: 「등급 high」·「판정 KEYWORD」·
 * KPI 「GO」·레일 「참여 결정 (GO)」·레이더 「SCORE」·목록 「No-Go · 참여 불가」.
 * 저장 값(enum)은 그대로 두고 **표기만** 한국어로 고쳤으므로, 여기서 지키는 것은
 * 「사전의 **값**에 영문 낱말이 없다」이다. 키(GO·high·KEYWORD)는 저장 값이라 영문이 맞다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DECISION_LABELS,
  GRADE_LABELS,
  PRIORITY_THRESHOLDS,
  RECOMMENDATION_GRADE,
  REVIEW_PRIORITY,
  SCREEN_LABEL_DICTIONARIES,
  TIER_LABELS,
  labelOf,
  reviewPriorityText,
} from "../src/lib/scoreNames.ts";

/** A·B·C·D 는 등급 «기호»라 한 글자로 남는다. 그 밖의 영문 낱말은 화면에 두지 않는다. */
const GRADE_SYMBOLS = new Set(["A", "B", "C", "D"]);

/**
 * 이 제품의 한국어에 이미 들어와 있는 말. 이것까지 막으면 「AI 의미 매칭」을 쓸 수 없다.
 *
 * 막으려는 것은 **저장 값이 그대로 새는 것**이다 — `high`·`KEYWORD`·`GO`·`No-Go` 같은 것들.
 */
const KOREAN_VOCABULARY = ["AI", "RAG", "LLM"];

function hasLatinWord(value: string): boolean {
  let rest = value;
  for (const word of KOREAN_VOCABULARY) rest = rest.split(word).join("");
  return /[A-Za-z]{2,}/.test(rest);
}

test("화면 라벨 사전의 값에 영문 낱말이 없다", () => {
  for (const [name, dictionary] of Object.entries(SCREEN_LABEL_DICTIONARIES)) {
    for (const [key, label] of Object.entries(dictionary)) {
      if (GRADE_SYMBOLS.has(label)) continue;
      assert.ok(!hasLatinWord(label), `${name}.${key} = ${label}`);
    }
  }
});

test("마감은 「마감」이라고 쓴다 — 「No-Go」도 「참여 불가」도 아니다", () => {
  /*
   * 백엔드에서 NO_GO 등급은 **입찰 마감이 지났다**만 뜻한다(recommendation.py).
   * 「참여 불가」로 적으면 사람이 내린 결정처럼 읽히고, 실제로 대시보드는 「마감」,
   * 목록은 「No-Go · 참여 불가」로 갈려 있었다.
   */
  assert.equal(GRADE_LABELS.NO_GO, "마감");
});

test("참여 결정과 추천등급은 같은 열쇠를 써도 다른 말이다", () => {
  /* 둘 다 `NO_GO` 지만 뜻이 다르다 — 등급은 마감, 결정은 사람이 정한 「참여 안 함」이다. */
  assert.equal(DECISION_LABELS.NO_GO, "참여 안 함");
  assert.notEqual(DECISION_LABELS.NO_GO, GRADE_LABELS.NO_GO);
});

test("모르는 값이 와도 영문을 그대로 내보내지 않는다", () => {
  assert.equal(labelOf(TIER_LABELS, "high"), "높음");
  assert.equal(labelOf(TIER_LABELS, "UNKNOWN_FROM_SERVER"), "미확인");
  assert.equal(labelOf(TIER_LABELS, null), "미확인");
});

test("점수 이름은 둘뿐이고 둘 다 확률이 아니라고 말한다", () => {
  assert.equal(RECOMMENDATION_GRADE.label, "추천등급");
  assert.equal(REVIEW_PRIORITY.label, "검토 우선순위");
  assert.ok(RECOMMENDATION_GRADE.description.includes("낙찰확률이 아닙니다"));
  assert.ok(REVIEW_PRIORITY.description.includes("아닙니다"));
});

test("등급과 우선순위는 기준 회사가 다르다 — 그것을 화면에 적는다", () => {
  /* 추천등급은 회사를 바꿔도 안 바뀐다(기본 회사 고정). 그 사실이 이름 옆에 있어야 한다. */
  assert.equal(RECOMMENDATION_GRADE.scope, "기본 회사 기준");
  assert.equal(REVIEW_PRIORITY.scope, "선택한 회사 기준");
});

test("미산정은 0점이 아니다", () => {
  /* CLAUDE.md §12 — 미확인 항목을 0점으로 단정하지 않는다. */
  assert.equal(reviewPriorityText(null), "검토 우선순위 점수 없음");
  assert.equal(reviewPriorityText(0), "검토 우선순위 0");
  assert.equal(reviewPriorityText(68.6), "검토 우선순위 69");
});

test("「우선 검토」 경계 값이 화면 사전에 있다", () => {
  /*
   * 최고점 69 가 기준 70 바로 아래라 「우선 검토 0건」이 되는데, 담당자는 그 이유를 알 수 없었다.
   *
   * 8차에서 70 → 80 으로 올리고 **상위 15%** 규칙을 더했다 (0922 §4-B-6). 예전 기준으로는
   * 목록 107건 중 41건이 「우선 검토」였다 — 거의 전부가 그 이름을 달면 이름값이 없다.
   * 백엔드 `opportunity_priority.PRIORITY_HIGH/MID/PRIORITY_TOP_RATIO` 와 같은 값이어야 한다.
   */
  assert.equal(PRIORITY_THRESHOLDS.high, 80);
  assert.equal(PRIORITY_THRESHOLDS.mid, 45);
  assert.equal(PRIORITY_THRESHOLDS.topRatio, 0.15);
});
