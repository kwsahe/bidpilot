/**
 * 「언제 돌린 결과인가」 꼬리말 (0923 §3-3 · ISSUE-093).
 *
 * 문구를 **한 곳에서만** 만들기 때문에 KPI·노드 상세·8단계 레일이 같은 말을 한다.
 * 그 한 곳이 여기서 재는 `runStamp` 다 — 세 화면이 각자 문장을 만들면 언젠가 갈린다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runStamp, withRunStamp } from "../src/lib/cosmos/runStamp.ts";

/** 분석 결과 한 벌. 재는 데 필요한 것만 채운다. */
function analysis(patch: Record<string, unknown> = {}) {
  return {
    eligibility: null,
    proposal: null,
    audit: null,
    conditions: null,
    decision: null,
    checklist: null,
    capability: null,
    readiness: null,
    ...patch,
  } as never;
}

describe("실행 시각 꼬리말", () => {
  it("실행한 적이 없으면 아무 말도 붙이지 않는다", () => {
    const stamp = runStamp(analysis(), "audit");
    assert.equal(stamp.ran, false);
    assert.equal(stamp.text, null);
    assert.equal(withRunStamp("발견 26건", stamp), "발견 26건");
  });

  it("저장된 결과에는 「(9-16 실행)」을 붙인다", () => {
    const stamp = runStamp(analysis({ audit: { created_at: "2026-09-16T08:40:41Z" } }), "audit");
    assert.equal(stamp.ran, true);
    assert.equal(stamp.needsRerun, false);
    assert.equal(stamp.text, "(9-16 실행)");
    assert.equal(withRunStamp("발견 26건", stamp), "발견 26건 (9-16 실행)");
  });

  it("공고가 그 뒤로 바뀌었으면 「다시 실행 필요」를 덧붙인다", () => {
    const stamp = runStamp(
      analysis({
        conditions: { detected_at: "2026-09-08T02:38:34Z" },
        readiness: { notice_changed_at: "2026-09-12T00:00:00Z" },
      }),
      "conditions",
    );
    assert.equal(stamp.needsRerun, true);
    assert.equal(stamp.text, "(9-8 실행 · 다시 실행 필요)");
  });

  it("공고 변경 시각을 모르면 경고하지 않는다", () => {
    // **모르는 것을 근거로 경고하지 않는다.** 옛 배포 스냅샷에는 이 필드가 없다.
    const stamp = runStamp(
      analysis({ conditions: { detected_at: "2026-09-08T02:38:34Z" }, readiness: {} }),
      "conditions",
    );
    assert.equal(stamp.needsRerun, false);
    assert.equal(stamp.text, "(9-8 실행)");
  });

  it("실행 시각이 없는 옛 파일은 「실행 시각 없음」이다", () => {
    const stamp = runStamp(analysis({ proposal: { generated_at: null } }), "evidence");
    assert.equal(stamp.ran, true);
    assert.equal(stamp.text, "(실행 시각 없음)");
  });

  it("세 단계가 같은 규칙을 쓴다", () => {
    const source = analysis({
      proposal: { generated_at: "2026-09-16T08:39:46Z" },
      audit: { created_at: "2026-09-16T08:40:41Z" },
      conditions: { detected_at: "2026-09-16T09:00:00Z" },
    });
    const texts = (["evidence", "audit", "conditions"] as const).map((key) => runStamp(source, key).text);
    assert.deepEqual(texts, ["(9-16 실행)", "(9-16 실행)", "(9-16 실행)"]);
  });
});
