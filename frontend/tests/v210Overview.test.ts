/**
 * 2.1.0 — 대시보드 = 사업기회 통계 · 공고 분석은 「입찰 분석」(/analysis) (대표 결정 2026-10-28).
 *
 * 대시보드 숫자와 사업기회 목록은 같은 함수(`lib/opportunityRows`)로 센다 — 숫자를 누르면 같은 조건 · 같은 건수.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { NO_DIGEST, bizinfoRowsOf, g2bRowsOf, overviewCounts, rowMatchesDigest, type Row } from "../src/lib/opportunityRows.ts";
import type { UnifiedOpportunity } from "../src/types/opportunity.ts";
import type { ProcurementNotice } from "../src/types/procurement.ts";
import type { SupportProgramView } from "../src/types/support.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, ...parts), "utf8");

// 2026-10-28 12:00 KST
const NOW = Date.parse("2026-10-28T03:00:00Z");

const notice = (id: string, published: string, deadline: string): ProcurementNotice =>
  ({ id, notice_no: id, title: id, agency: "기관", published_at: published, deadline_at: deadline, budget: null, region: null, description: null, source_url: null, raw_data: {} }) as unknown as ProcurementNotice;
const unified = (id: string, extra: Partial<UnifiedOpportunity> = {}): UnifiedOpportunity =>
  ({ id, closed: false, eligibility_gate: "CHECK", relevance_note: null, deadline: null, ...extra }) as unknown as UnifiedOpportunity;
const program = (id: string, created: string, applyEnd: string | null): SupportProgramView =>
  ({ program: { id, title: id, agency: "기관", created_at: created, apply_end: applyEnd, hashtags: [] }, support_fit: { score: 0.5, label: "검토", note: "" } }) as unknown as SupportProgramView;

const NOTICES = [
  notice("A", "2026-10-28T01:00:00Z", "2026-10-28T09:00:00Z"), // 오늘 게시 · 오늘 18:00 마감
  notice("B", "2026-10-26T03:00:00Z", "2026-11-02T09:00:00Z"), // 2일 전 · 5일 뒤 · 가능
  notice("C", "2026-10-20T03:00:00Z", "2026-11-20T09:00:00Z"), // 8일 전 · 23일 뒤
  notice("D", "2026-10-28T01:00:00Z", "2026-10-30T09:00:00Z"), // 불가
  notice("E", "2026-10-28T01:00:00Z", "2026-10-30T09:00:00Z"), // 관련 낮음
  notice("F", "2026-10-28T01:00:00Z", "2026-10-30T09:00:00Z"), // 마감(서버 판정)
  notice("G", "2026-10-28T01:00:00Z", "2026-10-30T09:00:00Z"), // 통합 목록에 없음 — 실제 마감 지남(45차 M9)
];
const UNIFIED = new Map<string, UnifiedOpportunity>(
  [
    unified("A"),
    unified("B", { eligibility_gate: "PASS" }),
    unified("C"),
    unified("D", { eligibility_gate: "FAIL" }),
    unified("E", { relevance_note: "관련 낮음" }),
    unified("F", { closed: true }),
    unified("P1"),
  ].map((item) => [item.id, item]),
);

describe("대시보드 통계 셈 (2.1.0)", () => {
  it("나라장터 — 마감 · 불가 · 관련 낮음 · 통합 목록 밖을 빼고, 가능 · 오늘/3일 새 공고 · 오늘/7일 마감을 그 안에서 센다", () => {
    const counts = overviewCounts(g2bRowsOf(NOTICES, UNIFIED, true), NOW, 3);
    assert.deepEqual(counts, { review: 3, pass: 1, newToday: 1, newRecent: 2, dueToday: 1, dueWeek: 2 });
  });

  it("기간(new_days)을 모르면 「최근 n일」은 null — 지어 세지 않는다", () => {
    assert.equal(overviewCounts(g2bRowsOf(NOTICES, UNIFIED, true), NOW, null).newRecent, null);
  });

  it("기업마당 — 등록일 · 신청 마감으로 같은 조건에 걸린다 · 판정이 없으면 날짜로 마감을 가린다", () => {
    const rows = bizinfoRowsOf(
      [program("P1", "2026-10-28T00:30:00Z", "2026-10-31"), program("P2", "2026-10-01T00:00:00Z", "2026-10-20"), program("P3", "2026-10-27T00:00:00Z", null)],
      UNIFIED,
    );
    assert.deepEqual(overviewCounts(rows, NOW, 3), { review: 2, pass: 0, newToday: 1, newRecent: 2, dueToday: 0, dueWeek: 1 });
  });

  it("변경 · 결정 대기는 나라장터에만, 직접 넣은 공고는 어느 띠 조건에도 들지 않는다", () => {
    const [biz] = bizinfoRowsOf([program("P1", "2026-10-28T00:30:00Z", "2026-10-31")], UNIFIED);
    const manual: Row = { kind: "manual", id: "manual-000000000001", unified: unified("manual-000000000001", { published_at: "2026-10-28T01:00:00Z" } as Partial<UnifiedOpportunity>) };
    const pending = new Set(["P1", "manual-000000000001"]);
    assert.equal(rowMatchesDigest(biz, { ...NO_DIGEST, onlyPending: true }, NOW, null, pending, 3), false);
    assert.equal(rowMatchesDigest(biz, { ...NO_DIGEST, newToday: true }, NOW, null, null, 3), true);
    assert.equal(rowMatchesDigest(manual, { ...NO_DIGEST, newToday: true }, NOW, null, null, 3), false);
  });
});

describe("경로 — 대시보드(/) · 입찰 분석(/analysis)", () => {
  it("/ 는 통계, /analysis 는 공고 분석 화면", () => {
    assert.match(read("src", "app", "page.tsx"), /import OverviewShell from "@\/components\/overview\/OverviewShell"/);
    assert.match(read("src", "app", "analysis", "page.tsx"), /import DashboardShell from "@\/components\/cosmos\/DashboardShell"/);
  });

  it("옛 주소 /?notice= · /?support= · /?stage= 는 /analysis 로 넘긴다", () => {
    const config = read("next.config.ts");
    assert.match(config, /\["notice", "support", "stage", "view", "guided"\]\.map\(\(key\) => \(\{ source: "\/", has: \[\{ type: "query" as const, key \}\], destination: "\/analysis"/);
    // 와이어프레임 서버(4120)는 `/` 가 와이어프레임이라 넘기지 않는다(2.1.0 검토 3)
    assert.match(config, /\.\.\.\(isWireframeServer\s*\? \[\]/);
  });

  it("화면 코드에 옛 분석 주소(/?notice= · /?support=)가 남지 않는다", () => {
    const left: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.(ts|tsx)$/.test(name) && /\/\?(notice|support)=/.test(readFileSync(path, "utf8"))) left.push(path);
      }
    };
    walk(join(ROOT, "src"));
    assert.deepEqual(left, []);
  });

  it("메뉴 — 대시보드(/)와 입찰 분석(/analysis) · 공고를 싣는 화면은 /analysis (대시보드는 통계라 싣지 않음)", () => {
    const shell = read("src", "components", "ui", "AppShell.tsx");
    assert.match(shell, /\{ href: "\/", label: SCREEN_NAMES\.dashboard/);
    assert.match(shell, /\{ href: "\/analysis", label: SCREEN_NAMES\.analysis/);
    assert.match(read("src", "lib", "selection.ts"), /const CARRIES_NOTICE = new Set\(\["\/analysis", "\/opportunities", "\/radar", "\/plan"\]\);/);
    assert.match(read("src", "lib", "terms.ts"), /analysis: "입찰 분석",/);
  });
});

describe("숫자 → 사업기회 같은 조건", () => {
  it("읽는 동안 숫자 칸 위에 「불러오는 중」 한 줄(2.1.1) — 「—」뿐이면 멈춘 것처럼 보였다", () => {
    const overview = read("src", "components", "overview", "OverviewShell.tsx");
    assert.match(overview, /\{\(loaded === null \|\| nowMs === null\) && \([\s\S]{0,200}role="status"[\s\S]{0,200}사업기회 목록을 불러오는 중입니다/);
  });

  it("대시보드는 사업기회와 같은 조건으로 세 목록을 받는다", () => {
    const overview = read("src", "components", "overview", "OverviewShell.tsx");
    const page = read("src", "app", "opportunities", "page.tsx");
    for (const call of ['getProcurements({ days, includeLow: true })', "getSupportPrograms({ organizationId })", 'getBusinessOpportunities({ organizationId, source: "all", days, sort: "priority", includeClosed']) {
      assert.ok(overview.includes(call), `대시보드: ${call}`);
      assert.ok(page.includes(call), `사업기회: ${call}`);
    }
    assert.match(page, /includeClosed, includeBlocked: true \}\)/);
    assert.match(overview, /includeClosed: false, includeBlocked: true \}\)/);
  });

  it("사업기회는 pass=1 · new=today · due=today 를 읽고 다시 쓴다", () => {
    const page = read("src", "app", "opportunities", "page.tsx");
    assert.match(page, /newToday: p\.get\("new"\) === "today",/);
    assert.match(page, /dueToday: p\.get\("due"\) === "today",/);
    assert.match(page, /onlyPass: p\.get\("pass"\) === "1",/);
    assert.match(page, /else if \(digest\.newToday\) next\.set\("new", "today"\);/);
    assert.match(page, /else if \(digest\.dueToday\) next\.set\("due", "today"\);/);
    assert.match(page, /if \(digest\.onlyPass\) next\.set\("pass", "1"\);/);
  });

  it("오늘 띠(나라장터만 세는 응답)의 링크는 src=g2b 를 단다 — 띠 조건이 기업마당에도 걸리게 된 뒤", () => {
    const strip = read("src", "components", "cosmos", "TodayDigestStrip.tsx");
    // 새 공고는 마감 지난 것을 세지 않으므로(백엔드 · 2.1.0 검토 4) closed=1 을 싣지 않는다
    assert.match(strip, /"\/opportunities\?src=g2b&new=1"/);
    assert.match(strip, /"\/opportunities\?src=g2b&changed=1&closed=1"/);
    assert.match(strip, /`\/opportunities\?src=g2b&due=\$\{digest\.due_days\}`/);
  });
});
