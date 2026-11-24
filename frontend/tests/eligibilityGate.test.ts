/**
 * 「입찰 참가 가능 여부」를 앞에 세우는 숫자 (20차 §4-D · ISSUE-140).
 *
 * 상세 맨 위 띠 · KPI 타일 · 「지금 할 일」 첫 줄 · 3단계 체크리스트 머리가 같은 계산을 쓴다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  DOC_NOT_FETCHED_MARK,
  blockingText,
  checklistOrder,
  decisionGateLine,
  eligibilityGateView,
  endedWithoutDate,
  gateBadge,
  gateCounts,
  gateSummary,
} from "../src/lib/cosmos/eligibilityGate.ts";
import type { EligibilityResult } from "../src/types/cosmos.ts";

function row(patch: Partial<EligibilityResult> & Pick<EligibilityResult, "rule_id" | "status">): EligibilityResult {
  return {
    label: "조항",
    method: "RULE",
    source: "근거",
    reason: "사유",
    requirement_id: null,
    ...patch,
  };
}

const CLAUSES: EligibilityResult[] = [
  row({ rule_id: "QUAL-OTHER-QC-05", status: "CHECK", clause_id: "QC-05", check_side: "notice", label: "기타 조항" }),
  row({ rule_id: "QUAL-DISQUAL-QC-02", status: "PASS", clause_id: "QC-02", method: "HUMAN", review_state: "met", label: "결격·등록 조항" }),
  row({ rule_id: "QUAL-TRACK-QC-04", status: "CHECK", clause_id: "QC-04", check_side: "company", label: "실적 조항" }),
  row({ rule_id: "QUAL-STAFF-QC-06", status: "CHECK", clause_id: "QC-06", check_side: "company", review_state: "stale", label: "인력 조항" }),
];
const FIELDS: EligibilityResult[] = [
  row({ rule_id: "ELIG-REGISTRATION", status: "CHECK", label: "입찰참가자격 등록" }),
  row({ rule_id: "ELIG-REGION", status: "PASS", label: "지역제한" }),
];

describe("참가자격 띠 숫자", () => {
  it("조항 줄만 세고, 확인 전에는 보류·다시 확인이 든다", () => {
    const view = eligibilityGateView([...FIELDS, ...CLAUSES], "CHECK");
    assert.ok(view);
    assert.deepEqual(
      { total: view.total, done: view.done, pending: view.pending, stale: view.stale, company: view.company, notice: view.notice, fieldCheck: view.fieldCheck },
      { total: 4, done: 1, pending: 3, stale: 1, company: 2, notice: 1, fieldCheck: 1 },
    );
    // ③ 의 두 수 — 캡션 · 타일 · 레일이 같은 말 (22차 §4-B). stale 은 확인 전에 이미 들어 있다(두 번 세지 않는다).
    assert.equal(gateCounts(view), "확정 안 한 조항 3 · 기본정보 확인 1");
    assert.equal(gateSummary(view), "확정 안 한 조항 3 · 기본정보 확인 1");
  });

  it("불가면 막는 줄은 조항 줄이 먼저이고 원문 앞 60자를 적는다", () => {
    const text = "입찰공고일 전일부터 입찰서 제출일까지 법인등기부상 본점 소재지를 서울특별시·경기도·인천광역시에 둔 업체로서 유지할 것";
    const rows = [
      row({ rule_id: "ELIG-REGION", status: "FAIL", label: "지역제한", reason: "참가 가능 지역이 서울이다" }),
      row({ rule_id: "QUAL-REGION-QC-03", status: "FAIL", clause_id: "QC-03", clause_text: text, label: "지역 조항" }),
    ];
    const view = eligibilityGateView(rows);
    assert.equal(view?.verdict, "FAIL");
    assert.equal(view?.blocking?.rule_id, "QUAL-REGION-QC-03");
    assert.equal(blockingText(view!.blocking!), `지역 조항: ${text.slice(0, 60)}…`);
  });

  it("조항을 다 확인했고 공고 필드만 남았으면 「확인 전 0」 대신 남은 공고 필드를 적는다", () => {
    const reviewed = CLAUSES.map((r) => ({ ...r, status: "PASS" as const, method: "HUMAN" as const, review_state: "met" as const }));
    const view = eligibilityGateView([...FIELDS, ...reviewed], "CHECK");
    assert.equal(view?.pending, 0);
    assert.equal(gateCounts(view!), "조항 다 확정 · 기본정보 확인 1");
    const allDone = eligibilityGateView(reviewed, "PASS");
    assert.equal(gateCounts(allDone!), "조항 4개 다 확정");
    assert.equal(gateCounts(eligibilityGateView(FIELDS, "CHECK")!), "기본정보 확인 1");
    // 불가 머리는 판정 낱말 「불가」 하나(27차 §3-E 말 한 벌 — 레일 이름 「참가 가능 여부」가 이미 「참가」를 말한다)
    assert.equal(gateSummary(eligibilityGateView([...CLAUSES], "FAIL")!), "불가 · 확정 안 한 조항 3 · 기본정보 확인 0");
  });

  it("지도 ③ 배지 — 캡션의 앞 수를 짧게: 확인 전 조항 · 없으면 남은 공고 필드 · 불가·0 이면 없다", () => {
    assert.equal(gateBadge(eligibilityGateView([...FIELDS, ...CLAUSES], "CHECK")), "확정 안 한 조항 3");
    const reviewed = CLAUSES.map((r) => ({ ...r, status: "PASS" as const, review_state: "met" as const }));
    assert.equal(gateBadge(eligibilityGateView([...FIELDS, ...reviewed], "CHECK")), "기본정보 1");
    assert.equal(gateBadge(eligibilityGateView(reviewed, "PASS")), null);
    assert.equal(gateBadge(eligibilityGateView([...CLAUSES], "FAIL")), null);
    assert.equal(gateBadge(null), null);
  });

  it("줄이 없으면 판정 전이다", () => {
    assert.equal(eligibilityGateView([]), null);
  });
});

describe("체크리스트 줄 순서", () => {
  it("불가 → 확인 필요(회사 쪽) → 확인 필요(원문) → 가능, 같은 칸은 원래 순서", () => {
    const fail = row({ rule_id: "QUAL-REGION-QC-09", status: "FAIL", clause_id: "QC-09" });
    const ordered = checklistOrder([...CLAUSES, fail]).map((r) => r.rule_id);
    assert.deepEqual(ordered, [
      "QUAL-REGION-QC-09",
      "QUAL-TRACK-QC-04",
      "QUAL-STAFF-QC-06",
      "QUAL-OTHER-QC-05",
      "QUAL-DISQUAL-QC-02",
    ]);
  });
});

describe("공고문을 아직 안 읽은 실공고 (32차 §3-B-1)", () => {
  it("조항 0 · QUAL-DOC 확인 필요면 docUnread — 「조항 없음」이 「조건이 없다」로 읽히지 않게", () => {
    const unread = eligibilityGateView([...FIELDS, row({ rule_id: "QUAL-DOC", status: "CHECK", label: "공고문 참가자격 부분" })], "CHECK");
    assert.ok(unread);
    assert.equal(unread.total, 0);
    assert.equal(unread.docUnread, true);
    const read = eligibilityGateView([...FIELDS, ...CLAUSES], "CHECK");
    assert.equal(read?.docUnread, false);
  });

  it("스캔 · 절 없음은 그 사유 그대로 — 받기 전일 때만 「공고 분석 시작」 안내(33차 R32-06)", () => {
    const engine = readFileSync(join(import.meta.dirname, "..", "..", "backend", "app", "services", "eligibility_engine.py"), "utf8");
    assert.ok(engine.includes(`"not_fetched": "공고문의 참가자격 부분을 ${DOC_NOT_FETCHED_MARK}"`));
    const image = "공고문이 스캔 이미지라 글자를 읽지 못했습니다. 원문을 직접 확인하세요.";
    const scanned = eligibilityGateView([...FIELDS, row({ rule_id: "QUAL-DOC", status: "CHECK", reason: image })], "CHECK");
    assert.equal(scanned?.docNote, image);
    const notFetched = eligibilityGateView(
      [...FIELDS, row({ rule_id: "QUAL-DOC", status: "CHECK", reason: `공고문의 참가자격 부분을 ${DOC_NOT_FETCHED_MARK}. 원문을 직접 확인하세요.` })],
      "CHECK",
    );
    assert.equal(notFetched?.docNote, null);
  });
});

describe("결정 칸 한 줄 (P1-02)", () => {
  const blocked = { can_go: false, reason: "참가를 막는 조건 1건이 남아 있습니다 — 마감 경과." };
  const unknown = { can_go: true, reason: "아직 모름 — 제안요청서를 아직 읽지 않아 조건을 다 찾지 못했습니다. 정리표를 만든 뒤 다시 봅니다." };
  const clear = { can_go: true, reason: "확인된 참가 차단 조건이 없습니다." };

  it("막는 조건이 있으면 서버 문장 그대로", () => {
    assert.deepEqual(decisionGateLine(blocked, true, null), { text: blocked.reason, open: true });
  });

  it("확정 안 한 조항이 남으면 「아직 정해지지 않았습니다」 — 차단 없음으로 끝내지 않는다", () => {
    const view = eligibilityGateView([...FIELDS, ...CLAUSES], "CHECK");
    const line = decisionGateLine(clear, true, view);
    assert.ok(line?.open);
    assert.ok(line.text.startsWith("참가 가능 여부는 아직 정해지지 않았습니다 — 참가자격 조항 3개"));
    // pending 은 「보류」도 센다 — 레일 · 배지 「확정 안 한 조항」과 같은 뜻(「확인하지 않았습니다」라 하지 않는다 · 31차 R30-29)
    assert.ok(line.text.includes("3개를 아직 확정하지 않았습니다"));
    assert.ok(!line.text.includes("공고 분석"));
    assert.ok(decisionGateLine(unknown, false, view)?.text.includes("공고 분석(요구사항 정리)도 아직 하지 않았습니다"));
  });

  it("조항은 끝났어도 공고 분석 전이면 서버 「아직 모름」", () => {
    const done = eligibilityGateView([row({ rule_id: "QUAL-DISQUAL-QC-02", status: "PASS", clause_id: "QC-02", review_state: "met" })], "PASS");
    assert.deepEqual(decisionGateLine(unknown, false, done), { text: unknown.reason, open: true });
  });

  it("모두 끝나면 「확인된 참가 차단 조건이 없습니다.」 · 불가는 위 빨간 상자가 말하므로 줄을 내지 않는다", () => {
    const done = eligibilityGateView([row({ rule_id: "QUAL-DISQUAL-QC-02", status: "PASS", clause_id: "QC-02", review_state: "met" })], "PASS");
    assert.deepEqual(decisionGateLine(clear, true, done), { text: "확인된 참가 차단 조건이 없습니다.", open: false });
    const failed = eligibilityGateView([row({ rule_id: "ELIG-BID-DEADLINE", status: "FAIL" })], "FAIL");
    assert.equal(decisionGateLine(clear, true, failed), null);
  });
});

describe("마감일 없이 접수 끝남 (UI e)", () => {
  const ended = [row({ rule_id: "ELIG-BID-DEADLINE", status: "FAIL", reason: "개찰 09/15 10:00이 이미 지났습니다" })];
  it("마감일이 비었고 입찰 마감 판정이 불가면 끝난 공고", () => {
    assert.equal(endedWithoutDate(ended, null), true);
  });
  it("마감일이 있으면 날짜 규칙 그대로 · 판정이 불가가 아니면 아님", () => {
    assert.equal(endedWithoutDate(ended, "2026-10-30T10:00:00+09:00"), false);
    assert.equal(endedWithoutDate([row({ rule_id: "ELIG-BID-DEADLINE", status: "CHECK" })], null), false);
  });
});
