/**
 * 회사자료 준비 상태의 중소기업(소상공인) 확인서 줄 — 판정에 쓰는 유일한 줄 · 「확인서 구분」(담당자 결정 2026-10-10).
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { isSmeRow, readinessRows, readinessToSave } from "../src/lib/firstTimeGuide.ts";
import { READINESS_HELP, READINESS_NOT_USED, SME_GRADES } from "../src/lib/terms.ts";

const ROOT = join(import.meta.dirname, "..");

test("판정에 쓰는 줄은 중소기업 확인서 하나 — 백엔드 이름 규칙과 같다", () => {
  assert.ok(isSmeRow("중소기업(소상공인) 확인서"));
  assert.ok(isSmeRow("중소기업확인서"));
  assert.ok(!isSmeRow("창업기업 확인서"));
  const engine = readFileSync(join(ROOT, "..", "backend", "app", "services", "eligibility_engine.py"), "utf8");
  for (const key of ["중소기업확인서", "중소기업·소상공인확인서", "중소기업소상공인확인서"]) assert.ok(engine.includes(`"${key}"`), key);
  const schema = readFileSync(join(ROOT, "..", "backend", "app", "schemas", "delivery_capacity.py"), "utf8");
  assert.ok(schema.includes(`Literal[${SME_GRADES.map((g) => `"${g}"`).join(", ")}]`), "구분 값이 백엔드와 같다");
});

test("구분은 저장된 값으로 열리고 중소기업 확인서 줄에만 붙는다", () => {
  const rows = readinessRows([
    { name: "중소기업확인서", held: true, note: null, source: "x", valid_until: "2027-03-31", grade: "소상공인" },
    { name: "창업기업 확인서", held: true, note: null, source: "x", valid_until: null, grade: "중기업" },
  ]);
  const sme = rows.find((r) => isSmeRow(r.label));
  assert.equal(sme?.grade, "소상공인");
  assert.equal(rows.find((r) => r.label === "창업기업 확인서")?.grade, null);
});

test("구분은 「있음」일 때만 저장한다 — 없음 · 모름으로 바꾸면 지운다 · 바뀌면 출처를 새로", () => {
  const rows = readinessRows([{ name: "중소기업확인서", held: true, note: null, source: "옛 출처", valid_until: null, grade: "중기업" }]);
  const sme = rows.findIndex((r) => isSmeRow(r.label));
  const saved = readinessToSave(rows, "새 출처").find((r) => r.name === "중소기업확인서");
  assert.equal(saved?.grade, "중기업");
  assert.equal(saved?.source, "옛 출처"); // 손대지 않았다
  const changed = rows.map((r, i) => (i === sme ? { ...r, grade: "소기업" as const } : r));
  const out = readinessToSave(changed, "새 출처").find((r) => r.name === "중소기업확인서");
  assert.equal(out?.grade, "소기업");
  assert.equal(out?.source, "새 출처");
  const none = rows.map((r, i) => (i === sme ? { ...r, held: false } : r));
  assert.equal(readinessToSave(none, "새 출처").find((r) => r.name === "중소기업확인서")?.grade, null);
});

test("안내 글 — 준비 상태 중 이 줄만 판정에 쓴다 · 숫자는 3월 31일만", () => {
  assert.ok(READINESS_HELP.includes("중소기업(소상공인) 확인서 줄") && !READINESS_HELP.includes("판정에도 쓰지 않습니다"));
  assert.ok(READINESS_NOT_USED.includes("중소기업(소상공인) 확인서 줄만"));
  assert.ok(!/\d/.test(READINESS_NOT_USED));
});
