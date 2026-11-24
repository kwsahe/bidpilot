/**
 * 2.1.2 — 제안서 작성에서 바로 공고 분석 · 순서 줄 · 정리표 「제안서 작성 →」
 * (대표 10-30 「공고 분석이 안 되면 사업계획서 작성이 안 되고, 분석해도 돌아오는 게 어렵고 흐름을 모르겠다」).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { isParsableNoticeId } from "../src/lib/cosmos/demoNotice.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

describe("제안서 작성 흐름 (2.1.2)", () => {
  it("분석할 수 있는 공고 id — 나라장터 · 가상 예시만(정리표와 같은 규칙 한 곳)", () => {
    assert.equal(isParsableNoticeId("g2b-R26BK01781472-000"), true);
    assert.equal(isParsableNoticeId("synthetic-rfp-0001"), true);
    assert.equal(isParsableNoticeId("manual-3b41508f54f8"), false);
    assert.equal(isParsableNoticeId("g2b-../etc-000"), false);
    assert.doesNotMatch(read("components", "opportunities", "RequirementSheet.tsx"), /function isSupportedNoticeId/);
  });

  it("요구사항이 없으면 제안서 작성 화면에서 바로 「공고 분석 시작」 — 정리표와 같은 함수 · 끝나면 다시 읽어 초안 단계로", () => {
    const plan = read("app", "plan", "page.tsx");
    assert.match(plan, /const result = await parseRfpWithConsent\(noticeId, \{ onPhase: setParsePhase \}\);/);
    assert.match(plan, /if \(result === null\) return;\s*setNotice\(`요구사항 \$\{result\.count\}건을 뽑았습니다/);
    // 성공하면 바로 작성 단계로(다시 읽기가 실패해도 1단계에 머물지 않음 · 2.1.2 검토)
    assert.match(plan, /건을 뽑았습니다 — 위 단추로 초안을 쓰세요\.`\);\s*setNotParsed\(null\);\s*setTick\(\(n\) => n \+ 1\);\s*\} catch/);
    assert.match(plan, /data-plan-analyze/);
    // 열람자 · 읽기 전용 배포 · 마감 · 목록 읽는 중 · 분석할 수 없는 id 는 잠근다
    assert.match(plan, /const parseBlock =\s*\(closed \? "마감된 공고라 새로 분석하지 않습니다" : null\) \?\?\s*\(infoLoading \? INFO_LOADING_BLOCK : null\) \?\?\s*\(draftBlock \? draftBlock\.replace\("초안을 만들 수 없습니다", "공고를 분석할 수 없습니다"\) : null\) \?\?\s*\(isParsableNoticeId\(noticeId\) \? null : /);
    assert.match(plan, /disabled=\{parsing \|\| parseBlock !== null\}/);
  });

  it("순서 줄 — 분석 전 1 · 초안 쓰기 2 · 저장된 초안이 있으면 3(받기)", () => {
    const plan = read("app", "plan", "page.tsx");
    assert.match(plan, /const BID_STEPS = \["공고 분석 — 요구사항 뽑기", "초안 쓰기 — Claude · Codex", "워드 · 한글 파일 받기"] as const;/);
    assert.match(plan, /<BidSteps current=\{1\} \/>/);
    // 10-31 최종 점검 — 요구사항이 있는지 읽는 동안(adopted 없음)은 「1 끝남 · 2 지금」으로 적지 않는다
    // 11-03 — 새 제안서 초안은 늘 저장된다(옛 「저장되지 않은 초안」 · 가상 예시 초안 갈래 없음)
    assert.match(plan, /<BidSteps current=\{adopted === null \? null : doc \? 3 : 2\} \/>/);
    assert.match(plan, /const done = current !== null && step < current;/);
    assert.match(plan, /aria-current=\{now \? "step" : undefined\}/);
  });

  it("정리표 — 요구사항이 있으면 「제안서 작성 →」로 돌아오는 길", () => {
    const sheet = read("components", "opportunities", "RequirementSheet.tsx");
    assert.match(sheet, /\{state\.kind === "ready" && \(\s*<Link\s*href=\{`\/plan\?notice=\$\{encodeURIComponent\(bidId\)\}`\}\s*data-sheet-plan-link/);
    assert.match(sheet, /\{WRITE_PROPOSAL_BUTTON\}/);
  });
});

describe("10-31 최종 점검 — 정리표 · 제안서 작성 작은 결함", () => {
  it("정리표의 공고 분석은 열람자에게 미리 잠그고 이유를 단다(다시 불러오기는 그대로) · 실패 사유 마침표 하나", () => {
    const sheet = read("components", "opportunities", "RequirementSheet.tsx");
    assert.match(sheet, /disabled=\{parsing \|\| state\.kind === "loading" \|\| !supported \|\| \(viewerLock && state\.kind !== "error"\)\}/);
    assert.match(sheet, /\{VIEWER_LOCK_LABEL\} — 공고 분석은 편집자 이상이 합니다/);
    assert.match(sheet, /error\.detail\.replace\(\/\[\.\\s\]\+\$\/, ""\)/);
  });

  it("제안서 작성의 저장본 읽기 실패 사유도 마침표 하나", () => {
    const plan = read("app", "plan", "page.tsx");
    assert.match(plan, /읽지 못했습니다 — \{docFailed\.replace\(\/\[\.\\s\]\+\$\/, ""\)\}\. 초안이/);
  });
});

describe("10-31 독립 검토 — 정리표 빈 화면 본문 단추도 열람자 잠금", () => {
  it("본문 「공고 분석 시작」도 viewerLock 이면 잠근다", () => {
    const sheet = read("components", "opportunities", "RequirementSheet.tsx");
    assert.match(sheet, /onClick=\{runParse\} disabled=\{parsing \|\| viewerLock\}/);
  });
});
