/**
 * 10-31 최종 점검 W2 — 입찰 분석 상세 · 자격 칸.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { blockingText, eligibilityGateView, pendingSidesText } from "../src/lib/cosmos/eligibilityGate.ts";
import { findingSummaryText } from "../src/lib/cosmos/mission.ts";
import type { EligibilityResult } from "../src/types/cosmos.ts";

const read = (...parts: string[]) => readFileSync(join(import.meta.dirname, "..", "src", ...parts), "utf8");

function row(patch: Partial<EligibilityResult> & Pick<EligibilityResult, "rule_id" | "status">): EligibilityResult {
  return { label: "조항", method: "RULE", source: "근거", reason: "사유", requirement_id: null, ...patch };
}

describe("10-31 최종 점검 W2", () => {
  it("① 7단계 — 점검 결과가 있으면 반영 수는 「점검 대상 요구사항 …」 한 줄만", () => {
    const detail = read("components", "cosmos", "DetailPanel.tsx");
    assert.match(detail, /\{breakdown && partial > 0 && \(/);
    assert.match(detail, /<CoverageBar graph=\{graph\} breakdown=\{!run\} \/>/);
  });

  it("② 요구사항을 뽑은 적 없으면 「기준 확인 안 됨」 배지를 그리지 않는다", () => {
    assert.match(read("components", "cosmos", "GatePanel.tsx"), /\(report\.requirements_available \|\| report\.stale === true\) && \(/);
  });

  it("③ 주요 위험 요약은 발견 목록과 같은 화면 코드(정리표 코드)", () => {
    const requirements = [
      { requirement_id: "REQ-030", item_type: "SUBMISSION" as const, display_code: "SPC-030" },
      { requirement_id: "REQ-019", item_type: "SCHEDULE" as const, display_code: null },
    ];
    const text = findingSummaryText(
      [
        { requirement_id: "REQ-030", finding_type: "missing_requirement" },
        { requirement_id: "REQ-019", finding_type: "missing_requirement" },
        { requirement_id: "REQ-999", finding_type: "missing_requirement" },
        { requirement_id: null, finding_type: "unsupported_claim" },
      ],
      requirements,
    );
    assert.match(text, /SPC-030/);
    assert.doesNotMatch(text, /REQ-030|REQ-019/);
    assert.match(text, /REQ-999/, "목록에 없는 id 는 그대로");
    assert.match(text, /초안/);
  });

  it("④ 불가 사유 — 기준시각 괄호 · 끝 마침표를 떼고 자르지 않는다 · 말줄임 뒤 마침표 없음", () => {
    const reason = "입찰등록 마감(10/27 11:00)이 이미 지났습니다. (기준시각 2026-10-31 15:20 KST)";
    const text = blockingText(row({ rule_id: "ELIG-BID-DEADLINE", status: "FAIL", label: "입찰 마감", reason }));
    assert.equal(text, "입찰 마감: 입찰등록 마감(10/27 11:00)이 이미 지났습니다");
    const gate = read("components", "cosmos", "GatePanel.tsx");
    assert.match(gate, /ineligibleReason\.trimEnd\(\)\.endsWith\("…"\) \? " " : "\. "/);
  });

  it("⑤ 확정 안 한 조항 내역의 합이 맞는다 — 규칙이 가능으로 본 조항은 「사람 확인만 남음」", () => {
    const rows = [
      row({ rule_id: "QUAL-A-1", status: "CHECK", clause_id: "1", check_side: "company" }),
      row({ rule_id: "QUAL-A-2", status: "CHECK", clause_id: "2", check_side: "notice" }),
      row({ rule_id: "QUAL-A-3", status: "PASS", clause_id: "3" }),
      row({ rule_id: "QUAL-A-4", status: "PASS", clause_id: "4", method: "HUMAN", review_state: "met" }),
    ];
    const view = eligibilityGateView(rows, "CHECK")!;
    assert.equal(view.pending, 3);
    assert.equal(pendingSidesText(view), "회사 정보 필요 1 · 공고문 더 읽기 1 · 사람 확인만 남음 1");
    const noRest = eligibilityGateView(rows.slice(0, 2), "CHECK")!;
    assert.equal(pendingSidesText(noRest), "회사 정보 필요 1 · 공고문 더 읽기 1");
    // 상세 띠 · 주요 위험 · 지금 할 일이 같은 함수를 쓴다
    assert.match(read("components", "cosmos", "DetailPanel.tsx"), /전체 \$\{view\.total\}개\) — \$\{pendingSidesText\(view\)\}/);
    assert.equal((read("lib", "cosmos", "mission.ts").match(/pendingSidesText\(gate\)/g) ?? []).length, 2);
  });

  it("⑥ 마감 실제 입찰은 「다시 만들기」 단추도 잠그고 /plan 과 같은 이유 글", () => {
    const detail = read("components", "cosmos", "DetailPanel.tsx");
    assert.match(detail, /const closed = useWriteClosed\(graph\) && graph\.source\.origin\.kind === "real";/);
    assert.match(detail, /disabled=\{actions\.proposalBusy \|\| viewer \|\| closed\}/);
    assert.match(detail, /CLOSED_WRITE_BLOCK = "마감된 공고라 새 초안을 만들 수 없습니다 — 저장된 초안 보기 · 내려받기만 됩니다"/);
    assert.match(read("app", "plan", "page.tsx"), /"마감된 공고라 새 초안을 만들 수 없습니다 — 저장된 초안 보기 · 내려받기만 됩니다"/);
  });

  it("⑦ 합성 근거 잠금 줄은 서버 메모가 아니라 쉬운 한 문장", async () => {
    const { syntheticMixLock } = await import("../src/lib/organization.ts");
    const lock = syntheticMixLock({
      legacy_result: true,
      evidence_scope: "public_demo",
      evidence_summary: { synthetic_evidence_used: true, note: "레거시 공개 결과 — 현재 조직의 내부 분석 결과가 아직 없어 표시" },
    } as never);
    assert.equal(lock, "이 초안은 가상 예시 회사자료를 근거로 인용하고 있습니다. 이 회사의 승인된 자료로 다시 생성하세요.");
  });

  it("회사 근거 카드 — AI 검색 꺼 둠이면 옛 실패 사유를 싣지 않는다", () => {
    const mission = read("lib", "cosmos", "mission.ts");
    assert.match(mission, /status === "off"\s*\?[^:]*"실패가 아닙니다 — 요구사항 정리표 행 상세에서 원장 후보 실적을 「채택」하세요"/);
  });
});
