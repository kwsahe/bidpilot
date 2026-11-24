/**
 * 2.0.6 — 레이더가 사업기회 · 대시보드와 같은 말을 하는가(대표 10-27 「모순이나 미연결이 발생하면 안 된다」).
 *
 * values-2 실무순 분류 칸 · 꼬리표 / values-6 간접 참여 / links-7 그림에 없는 까닭 · 전체 목록 조건 / 노드 마감 글.
 * 실행: `node --import ./tests/_register.mjs --test tests/v206Radar.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { deadlineText } from "../src/lib/radar/layout.ts";
import type { UnifiedOpportunity } from "../src/types/opportunity.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

const g2b = (over: Partial<UnifiedOpportunity>): UnifiedOpportunity =>
  ({ source_type: "g2b", closed: false, deadline: null, qualification_deadline: null, apply_period_kind: null, ...over }) as UnifiedOpportunity;

describe("레이더 노드 마감 글 — 실제 마감(pairOf · effectiveDeadline)", () => {
  it("입찰 마감이 비고 공고문 일정 마감만 있으면 그 이름과 D-day(예전: 「마감일 미정」)", () => {
    const item = g2b({ schedule_deadline: "2026-10-30T18:00:00+09:00", schedule_deadline_label: "참가신청 마감" });
    assert.equal(deadlineText(item, 5), "참가신청 마감 D-5");
  });
  it("입찰 마감이 비고 등록마감만 있으면 그 마감의 D-day — 대시보드 상세 「마감일」과 같은 날", () => {
    assert.equal(deadlineText(g2b({ qualification_deadline: "2026-10-30T18:00:00+09:00" }), 5), "D-5");
  });
  it("마감이 하나도 없으면 원문 문구 그대로", () => {
    assert.equal(deadlineText(g2b({ deadline_text: "공고문 참조" }), null), "공고문 참조");
    assert.equal(deadlineText(g2b({}), null), "마감일 미정");
  });
});

describe("실무 우선순위 회사 — 분류 칸 · 꼬리표가 사업기회와 같다(values-2)", () => {
  it("레이더 화면이 회사 순서 방식을 사업기회와 같은 Context 로 내린다", () => {
    assert.match(read("components", "radar", "RadarShell.tsx"), /<RankingMethodContext\.Provider value=\{data\?\.ranking_method \?\? "score"\}>/);
  });
  it("상세: 실무순이면 분류 칸 배지 · 사업기회 행과 같은 꼬리표 부품(withGroup 규칙도 같다)", () => {
    const src = read("components", "radar", "RadarDetail.tsx");
    assert.match(src, /const practical = useRankingMethod\(\) === "practical";/);
    assert.match(src, /practical && item\.eligibility_gate !== "FAIL" \? \(item\.practical_group \?\? null\) : null/);
    assert.match(src, /<PracticalTags item=\{item\} withGroup=\{!practical\} \/>/);
    // 사업기회 행도 같은 규칙(실무순이면 분류는 배지 자리에 있어 꼬리표에서 뺀다)
    assert.match(read("app", "opportunities", "page.tsx"), /<PracticalTags item=\{item\} withGroup=\{rankingMethod !== "practical"\} \/>/);
  });
  it("추적 카드: 실무순이면 분류 칸 글 · 「신규+여유」가 강조선", () => {
    const src = read("components", "radar", "RadarTrackedPanel.tsx");
    assert.match(src, /practical\s*\? \(node\.item\.practical_group \?\? null\)/);
    assert.match(src, /practical \? node\.item\.practical_group === "신규\+여유" : node\.item\.priority_label === "우선 검토"/);
  });
  it("계기: 실무순이면 사업기회에 없는 「우선 검토(전체)」 대신 그림 안 「신규+여유」", () => {
    const src = read("components", "radar", "RadarConsole.tsx");
    assert.match(src, /label: "신규\+여유\(그림\)"/);
    assert.match(src, /node\.item\.practical_group === "신규\+여유"/);
  });
});

describe("간접 참여 — 판정 자리가 사업기회 · 지원사업과 같은 함수(values-6)", () => {
  it("레이더 상세 판정 배지는 verdictOf(gate, participation)", () => {
    const src = read("components", "radar", "RadarDetail.tsx");
    assert.match(src, /verdictOf\(item\.eligibility_gate, item\.participation\)/);
    assert.doesNotMatch(src, /labelOf\(ELIGIBILITY_GATE_LABELS/);
  });
});

describe("다른 화면에서 고른 공고가 레이더에 없을 때(links-7)", () => {
  it("받아 온 목록에 없으면 까닭을 하나로 단정하지 않는다 — 잘렸으면 「상위 n건」, 출처 칩 밖이면 출처를 넓히는 단추", () => {
    const src = read("components", "radar", "RadarShell.tsx");
    // 목록을 아직 못 받았으면(로딩 · 실패) 모른다
    assert.match(src, /const selectionHidden = selectionOutside && data !== null && !data\.items\.some\(\(item\) => item\.id === selectedId\);/);
    // 출처마다 200건에서 잘렸으면(total_count 는 자르기 전) 순위 밖일 수도 있다 — 검토 지적(200위 밖 공고에 「불가」 까닭이 붙음)
    assert.match(src, /const selectionTruncated = data !== null && data\.items\.length < data\.total_count;/);
    assert.match(src, /출처마다 상위 \$\{FETCH_LIMIT\}건만 받고, /);
    assert.match(src, /참가 불가 · 관련 낮음\$\{\s*filters\.includeClosed \? "" : " · 마감된"\s*\} 공고와 직접 넣은 공고/);
    assert.match(src, /const selectionOtherSource = selectionHidden && source !== "all"/);
    assert.match(src, /출처 「모두」로 보기/);
  });
  it("불가 · 관련 낮음 · 마감 포함은 그 안내 링크에만 — 머리 · 도구줄 「전체 목록」은 레이더 조건 그대로", () => {
    const shell = read("components", "radar", "RadarShell.tsx");
    assert.match(shell, /for \(const key of \["blocked", "unrelated", "closed"\]\) query\.set\(key, "1"\);/);
    assert.match(shell, /href=\{selectionHidden \? withHiddenIncluded\(listHref\) : listHref\}/);
    assert.doesNotMatch(shell, /const listHref = selectionHidden/);
    const page = read("app", "opportunities", "page.tsx");
    for (const key of ["blocked", "unrelated", "closed"]) {
      assert.match(page, new RegExp(`p\\.get\\("${key}"\\) === "1"`), `사업기회 주소 키 ${key}`);
    }
  });
});
