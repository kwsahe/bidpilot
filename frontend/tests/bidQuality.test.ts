/**
 * 2.7.0 입찰 제안서 품질 게이트 화면(계획 12번) — 상태 · 심각도 낱말 · 묶기 · 승인 잠금 · 다시 쓰기 확인 창 · 「초안」 이름 · API 약속.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, it } from "node:test";

import {
  approveBidPlan,
  bidPlanQualityReportUrl,
  checkBidPlanPdf,
  revokeBidPlanApproval,
  type BidEvaluationCoverage,
  type BidHwpxCheck,
  type BidPdfCheck,
  type BidQuality,
  type BidQualityFinding,
} from "../src/lib/api.ts";
import {
  APPROVAL_NOTE_MAX,
  AXIS_VIEW,
  BLOCKED_INPUT_NOTE,
  GENERATION_VIEW,
  SEVERITY_VIEW,
  STAFFING_UNCONFIRMED_NOTE,
  STATUS_VIEW,
  approvalLine,
  approvalNote,
  approveBlockReason,
  axisLabel,
  blankGroup,
  blankGroups,
  blanksLine,
  PDF_CHECK_NOTE,
  pdfCheckView,
  checkedLine,
  countsLine,
  coverageOpen,
  coverageRows,
  coverageSummary,
  evidenceLines,
  findingAction,
  findingLine,
  generationView,
  hwpxCheckView,
  readinessChips,
  rewriteConsent,
  severityGroups,
  statusView,
  submitFileLabel,
} from "../src/lib/bidQuality.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

function finding(severity: BidQualityFinding["severity"], title: string, extra: Partial<BidQualityFinding> = {}): BidQualityFinding {
  return { code: "PLACEHOLDER", severity, title, detail: "", section: null, count: 1, ...extra };
}

function quality(extra: Partial<BidQuality> = {}): BidQuality {
  return {
    status: "BLOCKED",
    status_label: "차단",
    counts: { BLOCKER: 0, MAJOR: 0, MINOR: 0, INFO: 0 },
    findings: [],
    staffing_unconfirmed: false,
    approval: null,
    draft_hash: "abc",
    file_label: "초안",
    ...extra,
  };
}

describe("품질 게이트 낱말 (2.7.0)", () => {
  it("제출 상태 넷 — 차단 · 검토 필요 · 자동검증 통과 · 제출 준비 · 기호가 서로 달라 색 없이도 가른다", () => {
    assert.deepEqual(
      (["BLOCKED", "NEEDS_REVIEW", "VERIFIED_DRAFT", "READY_TO_SUBMIT"] as const).map((status) => STATUS_VIEW[status].label),
      ["차단", "검토 필요", "자동검증 통과", "제출 준비"],
    );
    assert.equal(new Set(Object.values(STATUS_VIEW).map((view) => view.glyph)).size, 4);
    // 서버 낱말이 있으면 그대로 · 모르는 상태는 「검토 필요」 모양
    assert.equal(statusView({ status: "READY_TO_SUBMIT", status_label: "제출 준비" }).tone, "pass");
    const unknown = statusView({ status: "SOMETHING_NEW" as BidQuality["status"], status_label: "새 상태" });
    assert.equal(unknown.label, "새 상태");
    assert.equal(unknown.tone, "warn");
  });

  it("심각도 넷 — 차단 · 중요 · 보통 · 참고 · 기호가 서로 다름", () => {
    assert.deepEqual(Object.values(SEVERITY_VIEW).map((view) => view.label), ["차단", "중요", "보통", "참고"]);
    assert.equal(new Set(Object.values(SEVERITY_VIEW).map((view) => view.glyph)).size, 4);
  });

  it("심각도 순서로 묶고 빈 묶음은 뺀다 · 같은 심각도 안은 서버 순서 · 차단 · 중요만 펼침 · 수는 서버 counts", () => {
    const q = quality({
      counts: { BLOCKER: 2, MAJOR: 1, MINOR: 0, INFO: 1 },
      findings: [finding("INFO", "원문 번호 건너뜀"), finding("MAJOR", "조견표 빈칸"), finding("BLOCKER", "빈칸 표시 남음", { count: 5 }), finding("BLOCKER", "인력 미확정")],
    });
    const groups = severityGroups(q);
    assert.deepEqual(groups.map((group) => group.severity), ["BLOCKER", "MAJOR", "INFO"]);
    assert.deepEqual(groups[0].items.map((item) => item.title), ["빈칸 표시 남음", "인력 미확정"]);
    assert.deepEqual(groups.map((group) => group.open), [true, true, false]);
    assert.deepEqual(groups.map((group) => group.total), [2, 1, 1]);
    assert.equal(countsLine(q), "차단 2 · 중요 1 · 보통 0 · 참고 1");
    // counts 가 비면 목록 건수
    assert.equal(countsLine({ counts: undefined as unknown as BidQuality["counts"], findings: q.findings }), "차단 2 · 중요 1 · 보통 0 · 참고 1");
  });

  it("항목 한 줄 — 여러 곳이면 「(n곳)」 · 소항목이 있으면 「소항목 「…」」", () => {
    assert.equal(findingLine(finding("BLOCKER", "빈칸 표시가 남음", { count: 5, section: "2. 수행 조직" })), "빈칸 표시가 남음 (5곳) · 소항목 「2. 수행 조직」");
    assert.equal(findingLine(finding("MAJOR", "표준 목차로 씀")), "표준 목차로 씀");
  });

  it("승인 잠금 — 역할 사유가 먼저 · 차단이 남으면 잠금 · 없으면 누를 수 있음", () => {
    const blocked = quality({ counts: { BLOCKER: 3, MAJOR: 0, MINOR: 0, INFO: 0 } });
    assert.equal(approveBlockReason(blocked, "열람자 — 보기만"), "열람자 — 보기만");
    assert.match(approveBlockReason(blocked, null) ?? "", /^차단 3건이 남아 승인할 수 없습니다/);
    assert.equal(approveBlockReason(quality({ status: "NEEDS_REVIEW", counts: { BLOCKER: 0, MAJOR: 2, MINOR: 0, INFO: 0 } }), null), null);
    // 남은 차단이 인력 칸뿐이면 「다시 쓰세요」 대신 받은 파일에서 채우라는 말(서버 approve_block_reason 과 같은 글)
    const staffOnly = quality({
      counts: { BLOCKER: 2, MAJOR: 0, MINOR: 0, INFO: 0 },
      findings: [finding("BLOCKER", "인력 미확정 — 조직", { code: "STAFFING_UNCONFIRMED" }), finding("BLOCKER", "인력 미확정 — 참여인력", { code: "STAFFING_UNCONFIRMED" })],
    });
    assert.match(approveBlockReason(staffOnly, null) ?? "", /^앱 안에서는 채울 수 없는 인력 칸만 남았습니다/);
    const mixed = quality({ ...staffOnly, counts: { BLOCKER: 3, MAJOR: 0, MINOR: 0, INFO: 0 }, findings: [...staffOnly.findings, finding("BLOCKER", "빈칸 표시 남음")] });
    assert.match(approveBlockReason(mixed, null) ?? "", /^차단 3건이 남아 승인할 수 없습니다/);
    // 차단이 0 이어도 승인 무효 검사가 있으면 잠근다 — 서버 approvable · approve_block_reason 과 같은 규칙 · 글(2.8.0 검토)
    const major = (code: string) => quality({ status: "NEEDS_REVIEW", counts: { BLOCKER: 0, MAJOR: 1, MINOR: 0, INFO: 0 }, findings: [finding("MAJOR", code, { code })] });
    assert.match(approveBlockReason(major("STALE"), null) ?? "", /^초안을 쓴 뒤 공고 · 요구사항이 바뀌어 승인할 수 없습니다/);
    assert.match(approveBlockReason(major("NOTICE_MISMATCH"), null) ?? "", /^초안을 쓴 뒤 공고 · 요구사항이 바뀌어/);
    assert.match(approveBlockReason(major("NOTICE_TERMS"), null) ?? "", /^본문의 사업기간 · 사업금액이 공고 원문과 달라 승인할 수 없습니다/);
    assert.equal(approveBlockReason(major("COMMITMENT"), null), null);  // 무효 검사가 아니면 누를 수 있다
    const failed = quality({ status: "BLOCKED", counts: { BLOCKER: 1, MAJOR: 0, MINOR: 0, INFO: 0 }, findings: [finding("BLOCKER", "검증 실패", { code: "GATE_ERROR" })] });
    assert.match(approveBlockReason(failed, null) ?? "", /^검증을 실행하지 못해 승인할 수 없습니다/);
    // 패널의 공통 풀이는 표 이름을 단정하지 않는다 — 조직 표만 있는 공고(실제 5건 중 3건)에 없는 참여인력 표를 말하지 않게
    assert.doesNotMatch(STAFFING_UNCONFIRMED_NOTE, /참여인력|성명/);
    assert.match(STAFFING_UNCONFIRMED_NOTE, /아래 「인력 미확정」 항목/);
  });

  it("승인 줄 — 표시 이름이 없으면 아이디 · 시각은 「11월 8일 09:05」", () => {
    const at = new Date(2026, 10, 8, 9, 5).toISOString();
    assert.equal(approvalLine({ by: "kwsahe", by_name: "홍길동", at, note: null }), "홍길동 님이 11월 8일 09:05에 승인");
    assert.equal(approvalLine({ by: "kwsahe", by_name: null, at: "엉뚱", note: null }), "kwsahe 님이 승인");
  });

  it("내려받기 이름 — 서버 file_label 그대로 · 칸이 없는 옛 초안은 「제출용」", () => {
    assert.equal(submitFileLabel(quality({ file_label: "초안" })), "초안");
    assert.equal(submitFileLabel(quality({ status: "READY_TO_SUBMIT", file_label: "제출용" })), "제출용");
    assert.equal(submitFileLabel(null), "제출용");
    assert.equal(submitFileLabel(undefined), "제출용");
  });

  it("다시 쓰기 확인 창 — 초안이 있을 때만 · 옛 판 보관 안내 · 승인됐으면 풀린다는 말", () => {
    assert.equal(rewriteConsent("Claude", false, false), null);
    const ask = rewriteConsent("Claude", true, false);
    assert.ok(ask);
    assert.match(ask.body, /있던 초안을 새로 씁니다 — 옛 판은 보관됩니다\./);
    assert.doesNotMatch(ask.body, /승인/);
    assert.equal(ask.confirmLabel, "Claude로 다시 쓰기");
    assert.match(rewriteConsent("Codex", true, true)?.body ?? "", /승인도 풀려/);
  });
});

describe("품질 게이트 2차 낱말 (2.8.0)", () => {
  it("항목 한 줄 — 서버 위치(location)가 소항목보다 먼저 · 고치는 법(action)은 따로 한 줄 · 둘 다 없으면 옛 꼴 그대로", () => {
    const placed = finding("BLOCKER", "조견표 목차 미연결", { section: "Ⅲ-2", location: "조견표 · 「취업현황조사 기획」 행", action: "평가 항목에 맞는 목차를 적고 다시 쓰세요" });
    assert.equal(findingLine(placed), "조견표 목차 미연결 · 위치: 조견표 · 「취업현황조사 기획」 행");
    assert.equal(findingAction(placed), "고치는 법 — 평가 항목에 맞는 목차를 적고 다시 쓰세요");
    assert.equal(findingLine(finding("MAJOR", "표준 목차로 씀", { section: "2. 조직", location: "  " })), "표준 목차로 씀 · 소항목 「2. 조직」");
    assert.equal(findingAction(finding("MAJOR", "표준 목차로 씀")), null);
    assert.equal(findingAction(finding("MAJOR", "표준 목차로 씀", { action: " " })), null);
  });

  it("검사 시각 · 규칙 판 · 미작성 칸 수 — 칸이 없는 옛 응답은 null(줄을 그리지 않음)", () => {
    const at = new Date(2026, 10, 11, 9, 5).toISOString();
    assert.equal(checkedLine({ checked_at: at, gate_version: 2 }), "자동 검사 11월 11일 09:05 · 검사 규칙 판 2");
    assert.equal(checkedLine({ gate_version: 2 }), "검사 규칙 판 2");
    assert.equal(checkedLine({}), null);
    assert.equal(blanksLine({ submit_blanks: 3, review_blanks: 5 }), "제출용 파일 미작성 칸 3곳 · 검토용 「담당자가 채울 항목」 5건");
    assert.equal(blanksLine({ submit_blanks: 0 }), "제출용 파일 미작성 칸 0곳");
    assert.equal(blanksLine({}), null);
  });

  it("한글 파일 검사 — 옛 응답 null · 아직 안 받음 · 맞음 · 다름(수 다름 · 다시 읽기 실패 · 구조 실패) · 번호 겹침", () => {
    const check = (extra: Partial<BidHwpxCheck> = {}): BidHwpxCheck => ({
      at: new Date(2026, 10, 11, 9, 5).toISOString(),
      ok: true,
      reextract_ok: true,
      placeholders: 4,
      gate_spots: 4,
      match: true,
      duplicate_majors: [],
      ...extra,
    });
    assert.equal(hwpxCheckView(undefined), null);
    assert.equal(hwpxCheckView(null)?.state, "none");
    assert.match(hwpxCheckView(null)?.text ?? "", /아직 받지 않음/);
    const same = hwpxCheckView(check());
    assert.equal(same?.state, "match");
    assert.equal(same?.text, "한글 파일 검사 — 맞음: 파일 안 미작성 칸 4곳 = 자동 검사 4곳 (11월 11일 09:05)");
    const differ = hwpxCheckView(check({ placeholders: 5, match: false }));
    assert.equal(differ?.state, "differ");
    assert.match(differ?.text ?? "", /파일 안 미작성 칸 5곳 · 자동 검사 4곳 — 그 파일은 「초안」 이름으로 받았습니다/);
    assert.match(hwpxCheckView(check({ reextract_ok: false }))?.text ?? "", /다시 읽지 못해/);
    assert.equal(hwpxCheckView(check({ ok: false }))?.tone, "fail");
    assert.match(hwpxCheckView(check({ duplicate_majors: ["Ⅵ"] }))?.text ?? "", /대항목 번호가 겹칩니다\(Ⅵ\) — 그 파일은 「초안」 이름으로/);
    assert.equal(hwpxCheckView(check({ duplicate_majors: ["Ⅵ"] }))?.state, "differ");
    // 어느 판을 검사했는지 밝힌다 — 평가본은 식별 칸을 가려 제출용보다 칸 수가 적다(2.8.0 검토)
    assert.match(hwpxCheckView(check({ variant: "blind", placeholders: 3, gate_spots: 3 }))?.text ?? "", /^평가본 한글 파일 검사 — 맞음: 파일 안 미작성 칸 3곳/);
    assert.match(hwpxCheckView(check({ variant: "submit" }))?.text ?? "", /^제출용 한글 파일 검사 — 맞음/);
    // 평가본만 받는 공고(2.10.0 D8) — 평가본이 제출 파일 · 회사명 판은 「회사명 포함본」
    assert.match(hwpxCheckView(check({ variant: "blind", blind_only: true }))?.text ?? "", /^제출용\(평가본\) 한글 파일 검사 — 맞음/);
    assert.match(hwpxCheckView(check({ variant: "submit", blind_only: true }))?.text ?? "", /^회사명 포함본 한글 파일 검사 — 맞음/);
    assert.match(hwpxCheckView(check({ reextract_ok: false, placeholders: null }))?.text ?? "", /다시 읽지 못해/);
    // 상태마다 기호가 달라 색 없이도 가른다
    assert.equal(new Set([hwpxCheckView(null), same, differ].map((view) => view?.glyph)).size, 3);
  });

  it("평가항목 대응표 — 행 낱말 · 요약 · 「목차 없음」이 있을 때만 처음부터 펼침 · 칸이 없으면 빈 목록", () => {
    const item = (extra: Partial<BidEvaluationCoverage>): BidEvaluationCoverage => ({
      name: "사업 이해도",
      area: "사업수행",
      kind: "정성",
      points: 5,
      mapped: "Ⅰ-1",
      source: "ai",
      body: "확인",
      status: "OK",
      ...extra,
    });
    const q = {
      evaluation_coverage: [
        item({}),
        item({ name: "취업현황조사 기획", mapped: "Ⅲ-4", source: "heading", body: "없음", status: "REVIEW" }),
        item({ name: "품질관리", area: null, points: null, mapped: null, source: null, body: "미확인", status: "MISSING" }),
      ],
    };
    const rows = coverageRows(q);
    assert.deepEqual(
      rows.map((row) => [row.name, row.points, row.mapped, row.source, row.body, row.status.label]),
      [
        ["사업수행 › 사업 이해도", "5점", "Ⅰ-1", "AI 가 적음", "내용 있음", "연결됨"],
        ["사업수행 › 취업현황조사 기획", "5점", "Ⅲ-4", "본문 소제목으로", "내용 없음(근사)", "검토"],
        ["품질관리", "—", "— 연결 안 됨", null, "확인 안 함", "목차 없음"],
      ],
    );
    assert.equal(new Set(rows.map((row) => row.status.glyph)).size, 3);
    assert.equal(coverageSummary(q), "평가 항목 3개 — 연결됨 1 · 검토 1 · 목차 없음 1");
    assert.equal(coverageOpen(q), true);
    assert.equal(coverageOpen({ evaluation_coverage: [item({}), item({ status: "REVIEW" })] }), false);
    assert.deepEqual(coverageRows({}), []);
    // 모르는 상태 값은 「검토」 모양
    assert.equal(coverageRows({ evaluation_coverage: [item({ status: "NEW" as BidEvaluationCoverage["status"] })] })[0].status.label, "검토");
  });

  it("근거 상태 — 0 인 칸은 빼고 · 미확인 · 빠짐 · 지남 · 명부 없음은 경고 줄 · 영문 상태 값이 화면 글에 새지 않음", () => {
    const lines = evidenceLines({
      ledger: { cited: 3, SELF_REPORTED: 2, UNVERIFIED: 1, MISSING: 0 },
      certifications: { cited: 0, SELF_REPORTED: 0, EXPIRED: 0, MISSING: 0 },
      personnel: "MISSING",
      notes: ["인증 「가상 인증 A」 유효기간을 모릅니다"],
    });
    assert.deepEqual(lines, [
      { text: "인용한 실적 3건 — 회사가 적은 값 2 · 증빙 미확인 1", warn: true },
      { text: "인용한 인증 없음", warn: false },
      { text: "참여인력 — 명부 없음: 앱은 사람 이름 · 경력을 짓지 않습니다(받은 파일에서 채우세요)", warn: true },
      { text: "인증 「가상 인증 A」 유효기간을 모릅니다", warn: false },
    ]);
    const certs = evidenceLines({
      ledger: { cited: 1, SELF_REPORTED: 1, UNVERIFIED: 0, MISSING: 0 },
      certifications: { cited: 2, SELF_REPORTED: 0, EXPIRED: 1, MISSING: 1 },
      personnel: "MISSING",
      notes: [],
    });
    assert.deepEqual(certs.slice(0, 2), [
      { text: "인용한 실적 1건 — 회사가 적은 값 1", warn: false },
      { text: "인용한 인증 2건 — 유효기간 지남 1 · 유효기간 모름 1", warn: true },
    ]);
    for (const line of [...lines, ...certs]) assert.doesNotMatch(line.text, /SELF_REPORTED|UNVERIFIED|MISSING|EXPIRED/);
    assert.deepEqual(evidenceLines(undefined), []);
    assert.deepEqual(evidenceLines(null), []);
  });

  it("승인 메모 — 앞뒤 공백 뗌 · 200자까지 · 빈 글은 보내지 않음", () => {
    assert.equal(APPROVAL_NOTE_MAX, 200);
    assert.equal(approvalNote("  대표 확인  "), "대표 확인");
    assert.equal(approvalNote("   "), undefined);
    assert.equal(approvalNote("가".repeat(250))?.length, 200);
  });
});

describe("품질 게이트 두 축 (2.9.0 · 게이트 판 3)", () => {
  const generation = (status: "PASS" | "REVIEW" | "FAIL" | "ERROR") => ({ status, label: GENERATION_VIEW[status].label, counts: { BLOCKER: 0, MAJOR: 0, MINOR: 0, INFO: 0 } });

  it("자동 작성 검사 — 서버 generation 을 낱말로 · 옛 응답은 null · 넷의 기호가 다름", () => {
    assert.equal(generationView(quality()), null);
    assert.equal(generationView(quality({ generation: generation("PASS") }))?.label, "자동 작성 완료");
    assert.equal(generationView(quality({ generation: generation("FAIL") }))?.tone, "fail");
    assert.equal(new Set(Object.values(GENERATION_VIEW).map((v) => v.label)).size, 4);
  });

  it("여섯 상태 칸 — 자동 작성 완료 · 수정 필요 · 담당자 입력 필요 · 증빙 필요 · 사실 확인 필요 · 검증 완료 · 옛 응답은 빈 목록", () => {
    assert.deepEqual(readinessChips(quality()), []);
    const chips = readinessChips(quality({ generation: generation("REVIEW"), axes: { auto: 2, input: 3, evidence: 0, fact: 1 } }));
    assert.deepEqual(chips.map((c) => c.label), ["자동 작성 완료", "수정 필요", "담당자 입력 필요", "증빙 필요", "사실 확인 필요", "검증 완료"]);
    assert.deepEqual(chips.map((c) => c.count), [null, 2, 3, 0, 1, null]);
    assert.deepEqual(chips.map((c) => c.active), [true, true, true, false, true, false]);
    const failed = readinessChips(quality({ generation: generation("FAIL"), axes: { auto: 1, input: 0, evidence: 0, fact: 0 } }));
    assert.equal(failed[0].active, false);
    const ready = readinessChips(quality({ status: "READY_TO_SUBMIT", generation: generation("PASS"), axes: { auto: 0, input: 0, evidence: 0, fact: 0 } }));
    assert.equal(ready.at(-1)?.active, true);
  });

  it("빈칸 묶음 — 붙일 서류 · 확인할 원문 값 · 회사가 정할 값 · 본문에서 뺀 문장 · 빈 묶음은 뺌", () => {
    const groups = blankGroups([
      { field: "서식 첨부", why: "[별첨 1] 제안사 일반현황 — 원문 서식을 채워 제안서와 함께 내세요" },
      { field: "참여인력 현황", why: "사람만 채우는 표" },
      { field: "원문 정량값 확인", why: "원문 「…」" },
      { field: "투입 인원 수", why: "회사가 정합니다" },
      { field: "회사 근거 없는 회사 주장", why: "근거를 붙이거나 지우세요 — …" },
      { field: "비용 항목", why: "[계산] 40만원*3명*30회 = 36,000,000원" },
    ]);
    assert.deepEqual(groups.map((g) => [g.key, g.items.length]), [["supplements", 2], ["notice", 1], ["decide", 1], ["cost", 1], ["moved", 1]]);
    assert.deepEqual(blankGroups([{ field: "투입 인원 수", why: "x" }]).map((g) => g.key), ["decide"]);
  });

  it("(검토) 자동 작성 낱말은 서버 label 이 먼저 · AI 가 못 쓴 소항목 빈칸은 「다시 쓰기」 묶음 · 무효 검사가 있으면 그 까닭이 먼저", () => {
    const review = { status: "REVIEW" as const, label: "서버 낱말", counts: { BLOCKER: 0, MAJOR: 0, MINOR: 0, INFO: 0 } };
    assert.equal(generationView(quality({ generation: review }))?.label, "서버 낱말");
    assert.equal(generationView(quality({ generation: { ...review, label: "" } }))?.label, "자동 작성 완료 · 검토할 경고 있음");
    assert.deepEqual(blankGroups([{ field: "사업 추진 전략", why: "AI 가 쓰지 못한 소항목 — 초안을 다시 쓰거나 직접 쓰세요" }]).map((g) => g.key), ["retry"]);
    const company = finding("BLOCKER", "일반현황 칸", { code: "PLACEHOLDER", axis: "input" });
    const staff = finding("BLOCKER", "인력 미확정", { code: "STAFFING_UNCONFIRMED", axis: "input" });
    const terms = finding("MAJOR", "기간 다름", { code: "NOTICE_TERMS", axis: "auto" });
    const stale = finding("MAJOR", "낡음", { code: "STALE", axis: "auto" });
    assert.match(approveBlockReason(quality({ counts: { BLOCKER: 1, MAJOR: 1, MINOR: 0, INFO: 0 }, findings: [company, terms] }), null) ?? "", /^본문의 사업기간 · 사업금액이 공고 원문과 달라/);
    assert.match(approveBlockReason(quality({ counts: { BLOCKER: 1, MAJOR: 1, MINOR: 0, INFO: 0 }, findings: [staff, stale] }), null) ?? "", /^초안을 쓴 뒤 공고 · 요구사항이 바뀌어/);
  });

  it("차단이 모두 담당자 입력이면 「자동 작성은 끝났습니다」 풀이 · 승인 잠금 글도 서버와 같게", () => {
    const staff = finding("BLOCKER", "인력 미확정", { code: "STAFFING_UNCONFIRMED", axis: "input" });
    const company = finding("BLOCKER", "일반현황 칸", { code: "PLACEHOLDER", axis: "input" });
    const both = quality({ counts: { BLOCKER: 2, MAJOR: 0, MINOR: 0, INFO: 0 }, findings: [staff, company] });
    assert.equal(statusView(both).note, BLOCKED_INPUT_NOTE);
    assert.match(approveBlockReason(both, null) ?? "", /^자동 작성은 끝났고 담당자 입력 칸만 남았습니다/);
    // 앱이 고칠 차단이 섞이면 예전 풀이 · 예전 잠금 글
    const auto = finding("BLOCKER", "조견표", { code: "EVAL_MAP_BLANK", axis: "auto" });
    const mixed = quality({ counts: { BLOCKER: 3, MAJOR: 0, MINOR: 0, INFO: 0 }, findings: [staff, company, auto] });
    assert.equal(statusView(mixed).note, STATUS_VIEW.BLOCKED.note);
    assert.match(approveBlockReason(mixed, null) ?? "", /^차단 3건이 남아/);
    // 갈래 칸이 없는 옛 응답 — 예전 그대로
    assert.equal(statusView(quality({ findings: [finding("BLOCKER", "x")] })).note, STATUS_VIEW.BLOCKED.note);
    assert.equal(axisLabel(staff), AXIS_VIEW.input.label);
    assert.equal(axisLabel(finding("MAJOR", "옛 응답")), null);
  });
});

describe("품질 게이트 API 약속 (2.7.0)", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("승인 POST …/plan-draft/approve(회사 · 범위 몸) · 취소 DELETE(회사 · 범위 쿼리) — 둘 다 갱신된 quality", async () => {
    const seen: { method: string; path: string; query: string; body: unknown }[] = [];
    const answer = quality({ status: "READY_TO_SUBMIT", status_label: "제출 준비", file_label: "제출용" });
    globalThis.fetch = (async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input));
      seen.push({ method: init.method ?? "GET", path: url.pathname, query: url.search, body: init.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify(answer), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch;
    const ctx = { organization_id: "org-x", evidence_scope: "internal" } as const;
    assert.equal((await approveBidPlan("g2b-R26BK01805118-000", ctx)).file_label, "제출용");
    // 화면이 읽은 초안 해시를 함께 보낸다 — 그사이 다른 사람이 다시 썼으면 서버가 409
    await approveBidPlan("g2b-R26BK01805118-000", ctx, "abc", "대표 확인");
    await revokeBidPlanApproval("g2b-R26BK01805118-000", ctx);
    assert.deepEqual(seen, [
      { method: "POST", path: "/api/proposal/g2b-R26BK01805118-000/plan-draft/approve", query: "", body: { organization_id: "org-x", evidence_scope: "internal" } },
      { method: "POST", path: "/api/proposal/g2b-R26BK01805118-000/plan-draft/approve", query: "", body: { organization_id: "org-x", evidence_scope: "internal", draft_hash: "abc", note: "대표 확인" } },
      { method: "DELETE", path: "/api/proposal/g2b-R26BK01805118-000/plan-draft/approve", query: "?organization_id=org-x&evidence_scope=internal", body: null },
    ]);
  });

  it("(2.8.0) 검증 보고서 주소 — GET …/plan-draft/quality-report(회사 · 범위 쿼리) · 옛 응답(새 칸 없음)도 타입이 받는다", () => {
    const url = new URL(bidPlanQualityReportUrl("g2b-R26BK01805118-000", { organization_id: "org-x", evidence_scope: "internal" }));
    assert.equal(url.pathname, "/api/proposal/g2b-R26BK01805118-000/plan-draft/quality-report");
    assert.equal(url.search, "?organization_id=org-x&evidence_scope=internal");
    // 2.7.0 응답 모양(새 칸 없음)이 그대로 BidQuality 로 읽힌다 — 새 칸은 모두 선택
    const old: BidQuality = quality();
    assert.equal(old.hwpx_check, undefined);
    assert.equal(hwpxCheckView(old.hwpx_check), null);
    assert.deepEqual(coverageRows(old), []);
  });
});

describe("/plan 입찰 초안 화면 연결 (2.7.0)", () => {
  const plan = read("app", "plan", "page.tsx");

  it("Claude · Codex 로 쓰기 — 초안이 있으면 쓰기 전에 화면 안 확인 창 · 취소면 요청 0", () => {
    assert.match(
      plan,
      /const consent = rewriteConsent\(writerOf\(writer\)\.label, doc !== null, Boolean\(doc\?\.quality\?\.approval\)\);\s*if \(consent && !\(await requestConsent\(consent\)\)\) return;\s*setBusy\(writer\);/,
    );
  });

  it("옛 초안(quality 없음)은 상태 패널 없이 · 빈칸 목록은 사업계획서와 같은 부품", () => {
    // 2.8.0 — 속성이 늘어 여러 줄 꼴(「{doc.quality && (」)도 같은 뜻
    assert.match(plan, /\{doc\.quality && \(?\s*<BidQualityPanel\s+quality=\{doc\.quality\}/);
    assert.match(plan, /<PlanBlanksList blanks=\{doc\.blanks \?\? \[\]\} grouped \/>/);
    assert.match(read("components", "support", "SupportEvidencePanel.tsx"), /\{draft\.blanks && <PlanBlanksList blanks=\{draft\.blanks\} annexFetchable=\{annexFetchable\} \/>\}/);
  });

  it("승인 단추 — 열람자는 기존 잠금 글 · 차단이 있으면 잠금 · 승인됨이면 취소 단추", () => {
    assert.match(plan, /const approveRoleBlock = viewer\s*\? `\$\{VIEWER_LOCK_LABEL\} — \$\{VIEWER_LOCK_REASON\}`/);
    assert.match(plan, /const block = approval \? roleBlock : approveBlockReason\(quality, roleBlock\);/);
    assert.match(plan, /disabled=\{busy \|\| block !== null\}[^>]*data-bid-approve>/);
    assert.match(plan, /disabled=\{busy \|\| block !== null\}[^>]*data-bid-revoke>/);
  });

  it("내려받기 단추 옆 이름 — 서버 file_label(「초안」 · 「제출용」)", () => {
    assert.match(plan, /submitLabel=\{submitFileLabel\(doc\.quality\)\}/);
    const panel = read("components", "support", "SupportEvidencePanel.tsx");
    // 2.10.0 D8 — 이름 규칙은 lib 한 곳(`variantName` · 평가본만 받는 공고는 평가본이 「제출용」 · 「초안」)
    assert.match(panel, /const nameOf = \(variant: PlanVariant\) => variantName\(variant, submitLabel, blindOnly\);/);
    assert.match(panel, /fallbackName=\{`\$\{fileStem\}_\$\{nameOf\(variant\)\}\.docx`\}/);
  });

  it("(2.8.0) 패널 — 검증 보고서 받기 · 평가항목 대응표는 접는 칸(「목차 없음」일 때만 펼침) · 고치는 법 · 근거 상태 → 회사자료", () => {
    const panel = plan.slice(plan.indexOf("function BidQualityPanel"), plan.indexOf("function BidWriter"));
    assert.match(panel, /<DownloadLink\s+href=\{reportUrl\}/);
    assert.match(plan, /reportUrl=\{bidPlanQualityReportUrl\(noticeId, ctx\)\}/);
    assert.match(panel, /<details open=\{coverageOpen\(quality\)\} data-bid-coverage>/);
    assert.match(panel, /const action = findingAction\(finding\);/);
    assert.match(panel, /const hwpx = hwpxCheckView\(quality\.hwpx_check\);/);
    assert.match(panel, /evidenceLines\(quality\.evidence_status\)/);
    // 회사자료 링크는 실제 있는 화면(/company)으로
    assert.match(panel, /<Link href="\/company"[^>]*data-bid-evidence-company>/);
    // 상태 · 근거 줄은 기호 + 글자(색만으로 뜻을 전하지 않음)
    assert.match(panel, /<span aria-hidden="true">\{hwpx\.glyph\} <\/span>/);
    assert.match(panel, /<Badge tone=\{row\.status\.tone\} glyph=\{row\.status\.glyph\}>/);
  });

  it("(2.8.0) 승인 메모 칸 — 선택 · 200자 · 다듬은 글을 승인 요청에 · 차단이면 칸도 잠금", () => {
    const panel = plan.slice(plan.indexOf("function BidQualityPanel"), plan.indexOf("function BidWriter"));
    assert.match(panel, /maxLength=\{APPROVAL_NOTE_MAX\}/);
    assert.match(panel, /onClick=\{\(\) => onDecide\(true, approvalNote\(note\)\)\}/);
    assert.match(panel, /disabled=\{busy \|\| block !== null\}\s*placeholder=/);
    assert.match(plan, /approveBidPlan\(noticeId, ctx, doc\?\.quality\?\.draft_hash, note\)/);
  });

  it("(2.8.0) 한글 파일을 받으면 품질 패널을 다시 읽는다 · 입찰 분석 PDF 단추는 상태를 박지 않는다(「제안서 PDF」)", () => {
    assert.match(plan, /onHwpxDone=\{\(\) => setTick\(\(n\) => n \+ 1\)\}/);
    assert.match(read("components", "support", "SupportEvidencePanel.tsx"), /fallbackName=\{`\$\{fileStem\}_\$\{nameOf\(variant\)\}\.hwpx`\}\s*className=\{linkClass\}\s*onDone=\{onHwpxDone\}/);
    const detail = read("components", "cosmos", "DetailPanel.tsx");
    assert.doesNotMatch(detail, /제안서 초안\(제출용\) PDF/);
    assert.match(detail, /fallbackName="제안서\.pdf"[\s\S]{0,600}제안서 PDF\s*<\/DownloadLink>/);
    assert.doesNotMatch(plan, /제안서 초안\(제출용\) PDF/);
  });

  it("색은 토큰만 — 새 파일 · 패널에 16진 · rgba 없음", () => {
    const lib = read("lib", "bidQuality.ts");
    const panel = plan.slice(plan.indexOf("function BidQualityPanel"), plan.indexOf("function BidWriter"));
    for (const source of [lib, panel]) {
      assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b/);
      assert.doesNotMatch(source, /rgba?\(/);
    }
  });

  it("(2.10.0 T8) 패널 — 검사 보고서(엑셀) 링크 · 한글에서 저장한 PDF 올리기(열람자 잠금) · 결과 줄 · 검사 줄", () => {
    const panel = plan.slice(plan.indexOf("function BidQualityPanel"), plan.indexOf("function BidWriter"));
    assert.match(panel, /<DownloadLink\s+href=\{workbookUrl\}/);
    assert.match(plan, /workbookUrl=\{bidPlanQualityReportUrl\(noticeId, ctx, "xlsx"\)\}/);
    assert.match(panel, /type="file"\s+accept="\.pdf,application\/pdf"/);
    assert.match(panel, /disabled=\{pdfBusy \|\| pdfBlock !== null\}[^>]*data-bid-pdf-check>/);
    assert.match(panel, /const pdf = pdfCheckView\(quality\.pdf_check\);/);
    assert.match(plan, /const pdfBlock = viewer\s*\? `\$\{VIEWER_LOCK_LABEL\} — \$\{VIEWER_LOCK_REASON\}`/);
    assert.match(plan, /await checkBidPlanPdf\(noticeId, file, ctx\)/);
  });
});

describe("제출 준비 산출물 화면 말 (2.10.0 T8)", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  function pdfCheck(extra: Partial<BidPdfCheck> = {}): BidPdfCheck {
    return { at: "2026-11-13T00:05:00+00:00", draft_hash: "h1", state: "ok", state_label: "통과", pages: 16, page_limit: 25,
      counts: { BLOCKER: 0, MAJOR: 0, MINOR: 0, INFO: 2 }, findings: [], ...extra };
  }

  it("공고 제출서류 · 제출 방법 빈칸은 「붙일 서류」 묶음", () => {
    assert.equal(blankGroup({ field: "공고 제출서류", why: "⑥ 소기업·소상공인 확인서 1부 — 1. 입찰공고문.pdf 2쪽" }), "supplements");
    assert.equal(blankGroup({ field: "제출 방법", why: "※ 입찰관련서류(①~⑩) …" }), "supplements");
  });

  it("PDF 검사 줄 — 아직 안 함 · 통과 · 고칠 곳(차단 · 중요 수) · 검사 못 함(통과 아님) · 옛 응답은 줄 없음", () => {
    assert.equal(pdfCheckView(undefined), null);
    assert.equal(pdfCheckView(null)?.state, "none");
    assert.match(pdfCheckView(null)?.text ?? "", /아직 하지 않음/);
    const ok = pdfCheckView(pdfCheck());
    assert.equal(ok?.tone, "pass");
    assert.match(ok?.text ?? "", /^한글에서 저장한 PDF 검사 — 통과: PDF 16쪽/);
    const issues = pdfCheckView(pdfCheck({ state: "issues", state_label: "고칠 곳 있음", counts: { BLOCKER: 1, MAJOR: 2, MINOR: 0, INFO: 1 } }));
    assert.equal(issues?.tone, "warn");
    assert.match(issues?.text ?? "", /고칠 곳 있음: 차단 1 · 중요 2/);
    const unread = pdfCheckView(pdfCheck({ state: "unreadable", state_label: "검사 못 함", pages: null }));
    assert.equal(unread?.tone, "fail");
    assert.match(unread?.text ?? "", /검사 못 함 — 통과가 아닙니다/);
    assert.match(PDF_CHECK_NOTE, /제출 상태 · 승인은 바꾸지 않습니다/);
  });

  it("API — 엑셀 보고서 주소(format=xlsx) · PDF 올리기 POST …/plan-draft/check-pdf(파일 몸 · 회사 · 범위 쿼리)", async () => {
    const ctx = { organization_id: "org-x", evidence_scope: "internal" } as const;
    const xlsx = new URL(bidPlanQualityReportUrl("g2b-R26BK01805885-000", ctx, "xlsx"));
    assert.equal(xlsx.pathname, "/api/proposal/g2b-R26BK01805885-000/plan-draft/quality-report");
    assert.equal(xlsx.searchParams.get("format"), "xlsx");
    assert.equal(xlsx.searchParams.get("organization_id"), "org-x");
    assert.equal(new URL(bidPlanQualityReportUrl("g2b-R26BK01805885-000", ctx)).searchParams.get("format"), null);
    const seen: { method: string; path: string; query: string; file: string | null }[] = [];
    globalThis.fetch = (async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input));
      const file = init.body instanceof FormData ? init.body.get("file") : null;
      seen.push({ method: init.method ?? "GET", path: url.pathname, query: url.search, file: file instanceof File ? file.name : null });
      return new Response(JSON.stringify(pdfCheck()), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch;
    const result = await checkBidPlanPdf("g2b-R26BK01805885-000", new File(["%PDF"], "제안서.pdf", { type: "application/pdf" }), ctx);
    assert.equal(result.state, "ok");
    assert.deepEqual(seen, [{ method: "POST", path: "/api/proposal/g2b-R26BK01805885-000/plan-draft/check-pdf",
      query: "?organization_id=org-x&evidence_scope=internal", file: "제안서.pdf" }]);
  });
});
