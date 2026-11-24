/**
 * 10-31 최종 점검 W3 — 지원사업 화면 · 레이더 2D.
 *
 * ① 5단계 머리 문장이 AI 검색을 꺼 두었을 때 「승인·색인된 회사자료에서 …」라 아래 원장 참고 후보와 어긋났다.
 * ② 레이더 2D 「나라장터 입찰 · n건」 둘째 줄이 바깥 원 선에 걸렸다.
 * ③ 지원사업 쉬운 보기 머리에 같은 마감이 세 번(「… · 예산 소진시까지」 / 「상시·예산 소진 시」 / 「예산 소진시까지」).
 *
 * SupportSimpleView.tsx 는 JSX 라 Node 가 바로 읽지 못한다 — 순수 함수 headDeadlineParts 는 소스에서 떼어 임시 파일로 돌린다(v206Plan.test.ts 와 같은 방식).
 */

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, describe, it } from "node:test";

import { formatDeadlineDate } from "../src/lib/deadline.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8").replace(/\r\n/g, "\n");

const SIMPLE = read("components", "support", "SupportSimpleView.tsx");
const start = SIMPLE.indexOf("\nfunction headDeadlineParts(");
assert.ok(start >= 0, "SupportSimpleView.tsx 에 headDeadlineParts 함수가 없다");
const dir = mkdtempSync(join(tmpdir(), "final1031w3-"));
const helperFile = join(dir, "helpers.ts");
writeFileSync(
  helperFile,
  `import { deadlineTerm, formatDeadlineDate, isOpenEnded } from ${JSON.stringify(pathToFileURL(join(ROOT, "src", "lib", "deadline.ts")).href)};\n` +
    SIMPLE.slice(start, SIMPLE.indexOf("\n}\n", start) + 3) +
    "\nexport { headDeadlineParts };\n",
);
type Program = { apply_end: string | null; apply_period_text: string | null; apply_period_kind: string };
const { headDeadlineParts } = (await import(pathToFileURL(helperFile).href)) as {
  headDeadlineParts: (program: Program, meaning: string | null, closed: boolean) => { meaning: string | null; note: string | null };
};
after(() => rmSync(dir, { recursive: true, force: true }));

describe("③ 지원사업 쉬운 보기 머리 — 마감은 D-day 줄 한 곳", () => {
  it("예산 소진 공고(124841 꼴) — 뜻 줄 꼬리 · 옆 칸 원문을 빼서 「상시·예산 소진 시」 한 번만", () => {
    const head = headDeadlineParts(
      { apply_end: null, apply_period_text: "예산 소진시까지", apply_period_kind: "until_budget" },
      "직접 신청(참여기업) · 최대 200만원 · 예산 소진시까지",
      false,
    );
    assert.deepEqual(head, { meaning: "직접 신청(참여기업) · 최대 200만원", note: null });
  });

  it("날짜 있는 공고 — 뜻 줄 「n월 n일 마감」을 빼고 옆 칸 「신청 마감 날짜」 한 번", () => {
    const head = headDeadlineParts({ apply_end: "2026-10-30", apply_period_text: "2026.10.01 ~ 2026.10.30", apply_period_kind: "dated" }, "직접 신청 · 무료 · 10월 30일 마감", false);
    assert.equal(head.meaning, "직접 신청 · 무료");
    assert.equal(head.note, `신청 마감 ${formatDeadlineDate("2026-10-30")}`);
  });

  it("예산 소진인데 날짜도 있으면 옆 칸은 날짜만 · 끝난 공고 첫 조각 「신청 종료(…)」는 그대로 · 날짜도 원문도 없으면 원문 확인", () => {
    assert.equal(headDeadlineParts({ apply_end: "2026-11-03", apply_period_text: null, apply_period_kind: "until_budget" }, "직접 신청 · 11월 3일 마감", false).note, `${formatDeadlineDate("2026-11-03")}까지`);
    const closed = headDeadlineParts({ apply_end: "2026-10-07", apply_period_text: null, apply_period_kind: "dated" }, "신청 종료(10월 7일) · 무료", true);
    assert.deepEqual(closed, { meaning: "신청 종료(10월 7일) · 무료", note: `신청 종료 ${formatDeadlineDate("2026-10-07")}` });
    assert.deepEqual(headDeadlineParts({ apply_end: null, apply_period_text: null, apply_period_kind: "unknown" }, null, false), { meaning: null, note: "신청기간 원문 확인 필요" });
  });

  it("화면은 이 함수 값만 쓴다(뜻 줄 · 옆 칸)", () => {
    assert.match(SIMPLE, /const head = headDeadlineParts\(program, result\.company_meaning \?\? null, result\.priority_label === "마감"\);/);
    assert.match(SIMPLE, /\{head\.meaning\}/);
    assert.match(SIMPLE, /\{head\.note && <span className="text-\[14px\] text-cosmos-secondary">\{head\.note\}<\/span>\}/);
    assert.doesNotMatch(SIMPLE, /\{result\.company_meaning\}/);
  });
});

describe("① 5단계 머리 문장 — AI 검색 꺼짐이면 원장 참고 후보라고 말한다", () => {
  it("isSearchOff 이면 「실적 원장에서 분야 낱말로 맞춘 참고 후보」 · 켜져 있으면 예전 문장", () => {
    const panel = read("components", "support", "SupportEvidencePanel.tsx");
    assert.match(panel, /const searchOff = isSearchOff\(summary\?\.note, summary\?\.ai_search_off\);/);
    assert.match(panel, /const description = searchOff\s*\? `\$\{organizationLabel\}의 실적 원장에서 분야 낱말로 맞춘 참고 후보를 보여 줍니다\./);
    assert.match(panel, /: `\$\{organizationLabel\}의 승인·색인된 회사자료에서 신청 조건과 연결된 문단만 보여줍니다\./);
    assert.match(panel, /description=\{description\}/);
  });
});

describe("② 레이더 2D 출처 라벨 — 위쪽 섹터는 원 선 밖으로", () => {
  it("위쪽(나라장터 90°)이면 두 줄을 4.5 올려 「n건」 기준선이 바깥 원(+ 호 굵기) 밖에 놓인다 · 글자 크기는 그대로", () => {
    const scene = read("components", "radar", "RadarScene2D.tsx");
    assert.match(scene, /const ly = -Math\.sin\(a\) \* \(BEZEL \+ 9\) - \(Math\.sin\(a\) > 0 \? 4\.5 : 0\);/);
    assert.match(scene, /y=\{ly \+ 9\.5\}/);
    assert.match(scene, /const fs = compact \? 1\.2 : 1;/);
    const BEZEL = 112;
    const countBaseline = -(BEZEL + 9) - 4.5 + 9.5; // 90°
    // 호 굵기 1.6 의 바깥 끝(-112.8)보다 위에 「n건」 글자 아래 끝(기준선 + 약 0.7)이 놓인다
    assert.ok(countBaseline + 0.7 < -(BEZEL + 0.8), `「n건」 기준선 ${countBaseline}`);
  });
});
