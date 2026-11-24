/**
 * 실전 가이드 앵커 · 내용 한 곳 (32차 §3-A-9 · §3-A-1) — 화면 속 모든 `/guide#…` 가 실제 제목 id 를 가리키는가.
 *
 * 실행: `npm test` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { GUIDE_LINKS, GUIDE_PATHS, READINESS_GUIDE, confirmItemIds, guideAnchorIds, guideBaseDate, parseGuide } from "../src/lib/guide.ts";
import { READINESS_ROWS } from "../src/lib/terms.ts";
import {
  CONSORTIUM_UNLOCK,
  OVER_CEILING_MARKS,
  REGISTRATION_UNLOCK_MARK,
  isDirectCheck,
  isOverCeilingCaution,
  isOverCeilingRow,
  splitUnlocks,
} from "../src/lib/unlock.ts";

const ROOT = join(import.meta.dirname, "..");
const MARKDOWN = readFileSync(join(ROOT, "content", "first_time_guide.md"), "utf8");
const IDS = guideAnchorIds(MARKDOWN);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

test("제목 id 는 절 번호 그대로 — 장 h2 · 절 h3 · 번호 없는 절은 장 안 순서 · 8장 항목", () => {
  const sections = parseGuide(MARKDOWN);
  assert.equal(sections.filter((s) => s.level === 2).length, 9); // 0~8장
  assert.ok(IDS.has("g-2") && IDS.has("g-1-7") && IDS.has("g-4-8") && IDS.has("g-7-d"));
  assert.equal(sections.find((s) => s.id === "g-7-d")?.title, "BidPilot 화면 말");
  assert.equal(sections.find((s) => s.id === "g-7-e")?.title, "BidPilot 매일 쓰는 순서"); // 35차 §4-3 — 사용 안내 §0 과 같은 순서
  const items = confirmItemIds(sections);
  assert.equal(items[0], "g-8-1");
  assert.equal(new Set(items).size, items.length, "8장 번호가 겹치지 않는다");
  assert.equal(guideBaseDate(MARKDOWN), "2026-10-04");
});

test("문맥 링크 · 준비 상태 줄 · 목차 갈래가 모두 실제 id 를 가리킨다", () => {
  for (const href of [...Object.values(GUIDE_LINKS), ...Object.values(READINESS_GUIDE)]) {
    assert.ok(IDS.has(href.split("#")[1]), href);
  }
  for (const row of READINESS_ROWS) assert.ok(READINESS_GUIDE[row], `준비 상태 줄 「${row}」에 가이드 절이 없다`);
  for (const path of GUIDE_PATHS) for (const id of path.ids) assert.ok(IDS.has(id), `${path.title}: ${id}`);
});

test("화면 코드 속 `/guide#…` 글자도 모두 실제 id", () => {
  const bad: string[] = [];
  for (const file of sourceFiles(join(ROOT, "src"))) {
    for (const m of readFileSync(file, "utf8").matchAll(/\/guide#(g-[0-9a-z-]+)/g)) {
      if (!IDS.has(m[1])) bad.push(`${file}: ${m[1]}`);
    }
  }
  assert.deepEqual(bad, []);
});

test("가이드 본문 안쪽 링크(#g-… · /guide#…)도 실제 id · 앱 안 링크는 있는 화면", () => {
  for (const m of MARKDOWN.matchAll(/\]\((?:\/guide)?#(g-[0-9a-z-]+)\)/g)) assert.ok(IDS.has(m[1]), m[0]);
  const screens = new Set(["/", "/opportunities", "/plan", "/company", "/radar", "/guide"]);
  for (const m of MARKDOWN.matchAll(/\]\((\/[^)#\s]*)(?:#[^)]*)?\)/g)) assert.ok(screens.has(m[1]), m[0]);
});

test("「BidPilot 화면 말」 풀이의 낱말은 화면 코드에 실제로 있는 말 — 이름이 달라지면 깨진다", () => {
  const section = parseGuide(MARKDOWN).find((s) => s.id === "g-7-d");
  assert.ok(section);
  const src = sourceFiles(join(ROOT, "src")).map((f) => readFileSync(f, "utf8")).join("\n");
  const terms = [...section.body.matchAll(/^\| ([^|]+?) \|/gm)].map((m) => m[1]).filter((t) => t !== "화면 말" && !t.startsWith("---"));
  assert.ok(terms.length >= 15, `풀이 줄 ${terms.length}개`);
  for (const term of terms) for (const word of term.split(" · ")) assert.ok(src.includes(word), `화면 코드에 없는 말: ${word}`);
});

test("공동수급 열쇠 — 백엔드 사업 규모 · 공동수급 조항과 같은 글 · 가이드 2-6 링크(33차 §3-B-5)", () => {
  const engine = readFileSync(join(ROOT, "..", "backend", "app", "services", "eligibility_engine.py"), "utf8");
  assert.ok(engine.includes(`unlock_condition="${CONSORTIUM_UNLOCK}"`), "사업 규모 줄의 열쇠");
  assert.ok(engine.includes(`unlock=["${CONSORTIUM_UNLOCK}"]`), "공동수급 조항의 열쇠");
  assert.equal(GUIDE_LINKS.consortium.split("#")[1], "g-2-6");
});

test("가이드 2-6 링크는 상한을 넘은 줄에만 — 백엔드 사업 규모 글과 같은 표식(34차 R33-S3)", () => {
  const engine = readFileSync(join(ROOT, "..", "backend", "app", "services", "eligibility_engine.py"), "utf8");
  const priority = readFileSync(join(ROOT, "..", "backend", "app", "services", "opportunity_priority.py"), "utf8");
  for (const mark of OVER_CEILING_MARKS) assert.ok(engine.includes(mark), mark);
  assert.ok(priority.includes("규모 큼 — 혼자 맡을 수 있는 금액을 회사자료에 적어 주세요"));
  const row = (reason: string) => ({ rule_id: "ELIG-BUDGET", status: "CHECK", reason });
  assert.ok(isOverCeilingRow(row("사업비 4.5억원 — 회사가 적은 최대 사업비 2억원보다 큽니다. …")));
  assert.ok(isOverCeilingRow(row("사업비 4.5억원 — 회사가 정한 최대 사업비 2억원보다 크고, …")));
  assert.ok(!isOverCeilingRow(row("예산 · 추정가격이 나라장터 기본정보에 없어 혼자 맡을 수 있는 규모인지 판단할 수 없습니다.")));
  assert.ok(!isOverCeilingRow(row("사업비 1.0억원 — … 권장 상한 2억원으로 가정했고, 그 안에 듭니다. …")));
  assert.ok(!isOverCeilingRow({ rule_id: "ELIG-BUDGET", status: "PASS", reason: "… 안입니다." }));
  assert.ok(isOverCeilingCaution("규모 큼 — 다른 회사와 함께 입찰 권장"));
  assert.ok(!isOverCeilingCaution("규모 큼 — 혼자 맡을 수 있는 금액을 회사자료에 적어 주세요"));
});

test("등록 조건 판별 — 백엔드 REGISTRATION_UNLOCK 문장에 표식이 있다 · 머리말 「직접 확인」", () => {
  const engine = readFileSync(join(ROOT, "..", "backend", "app", "services", "eligibility_engine.py"), "utf8");
  const sentence = /REGISTRATION_UNLOCK: Final\[str\] = "([^"]+)"/.exec(engine)?.[1] ?? "";
  assert.ok(sentence.includes(REGISTRATION_UNLOCK_MARK), sentence);
  assert.ok(isDirectCheck(sentence));
  assert.ok(isDirectCheck("아무 글", "ELIG-REGISTRATION"));
  assert.deepEqual(splitUnlocks([sentence, "회사자료에 매출을 적으면 판정할 수 있습니다"]), {
    gain: ["회사자료에 매출을 적으면 판정할 수 있습니다"],
    direct: [sentence],
  });
});
