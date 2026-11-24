/**
 * 10-31 최종 점검 W5 — 「새 공고」는 원공고 게시일(43차 M2).
 *
 * 변경공고(차수 001+)가 `/api/procurements` 의 변경 게시일로 대시보드 · 사업기회 「최근 3일 새 공고」에 섰다. 나라장터 행은 통합 목록의
 * `published_at`(서버 `opportunity_service._published_dates` — 띠도 같은 함수)으로 센다 · 원공고 게시일을 모르면(null) 새 공고가 아니다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { NO_DIGEST, g2bRowsOf, overviewCounts, rowMatchesDigest, rowRegisteredAt } from "../src/lib/opportunityRows.ts";
import type { UnifiedOpportunity } from "../src/types/opportunity.ts";
import type { ProcurementNotice } from "../src/types/procurement.ts";

// 2026-10-30 12:00 KST
const NOW = Date.parse("2026-10-30T03:00:00Z");

const notice = (id: string, published: string): ProcurementNotice =>
  ({ id, notice_no: id, title: id, agency: "기관", published_at: published, deadline_at: "2026-11-20T09:00:00Z", budget: null, region: null, description: null, source_url: null, raw_data: {} }) as unknown as ProcurementNotice;
const unified = (id: string, published: string | null | undefined): UnifiedOpportunity =>
  ({ id, closed: false, eligibility_gate: "CHECK", relevance_note: null, deadline: null, ...(published === undefined ? {} : { published_at: published }) }) as unknown as UnifiedOpportunity;

describe("새 공고 = 원공고 게시일 (43차 M2 · 10-31 최종 점검 B)", () => {
  // 변경공고 둘(원공고 게시일 모름 · 원공고가 오래전) + 원공고 하나
  const NOTICES = [
    notice("g2b-R26BK01791215-001", "2026-10-28T01:00:00Z"),
    notice("g2b-R26BK01798155-002", "2026-10-29T01:00:00Z"),
    notice("g2b-R26BK01800000-000", "2026-10-29T01:00:00Z"),
  ];
  const UNIFIED = new Map<string, UnifiedOpportunity>(
    [
      unified("g2b-R26BK01791215-001", null),
      unified("g2b-R26BK01798155-002", "2026-10-10T00:00:00+09:00"),
      unified("g2b-R26BK01800000-000", "2026-10-29T01:00:00Z"),
    ].map((item) => [item.id, item]),
  );

  it("나라장터 행은 통합 목록 값으로 센다 — 변경 게시일로 「최근 3일 · 오늘」에 서지 않는다", () => {
    const rows = g2bRowsOf(NOTICES, UNIFIED, true);
    assert.deepEqual(rows.map(rowRegisteredAt), [null, "2026-10-10T00:00:00+09:00", "2026-10-29T01:00:00Z"]);
    const counts = overviewCounts(rows, NOW, 3);
    assert.equal(counts.newRecent, 1);
    assert.equal(rows.filter((row) => rowMatchesDigest(row, { ...NO_DIGEST, onlyNew: true }, NOW, null, null, 3)).length, 1);
  });

  it("통합 목록이 없거나(못 받음) 옛 스냅샷이라 값이 없으면 나라장터 게시일 그대로", () => {
    const [row] = g2bRowsOf([notice("g2b-X-000", "2026-10-29T01:00:00Z")], new Map(), false);
    assert.equal(rowRegisteredAt(row), "2026-10-29T01:00:00Z");
    const [old] = g2bRowsOf([notice("g2b-Y-000", "2026-10-29T01:00:00Z")], new Map([["g2b-Y-000", unified("g2b-Y-000", undefined)]]), true);
    assert.equal(rowRegisteredAt(old), "2026-10-29T01:00:00Z");
  });
});
