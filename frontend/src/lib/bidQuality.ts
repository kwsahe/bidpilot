/**
 * 입찰 제안서 품질 게이트 화면 말(2.7.0 · 계획 12번) — 상태 · 심각도 낱말 · 묶기 · 승인 잠금 · 다시 쓰기 확인 창 글.
 *
 * 값은 서버(`bid_quality_gate` · 저장된 초안의 `quality`)가 정한 그대로이고 여기서 새 판단을 하지 않는다 —
 * 낱말 · 기호로 옮기고, 심각도 순서로 묶고, 단추를 누를 수 있는지 고를 뿐이다. 색만으로 뜻을 전하지 않게 기호 + 글자로 둔다.
 */

import type {
  BidEvaluationCoverage,
  BidEvidenceStatus,
  BidHwpxCheck,
  BidPdfCheck,
  BidQuality,
  BidQualityApproval,
  BidQualityAxis,
  BidQualityFinding,
  BidQualityGeneration,
  BidQualitySeverity,
  BidQualityStatus,
} from "@/lib/api";
import { WITH_NAME_LABEL } from "@/lib/bidOutline";
import type { ConsentRequest } from "@/lib/consentPrompt";
import type { Tone } from "@/lib/cosmos/theme";

export const SEVERITY_ORDER: readonly BidQualitySeverity[] = ["BLOCKER", "MAJOR", "MINOR", "INFO"];

/** 심각도 → 화면 낱말 · 기호 · 색(색은 덧붙임 — 낱말과 기호가 뜻을 말한다). */
export const SEVERITY_VIEW: Record<BidQualitySeverity, { label: string; glyph: string; tone: Tone }> = {
  BLOCKER: { label: "차단", glyph: "✕", tone: "fail" },
  MAJOR: { label: "중요", glyph: "!", tone: "warn" },
  MINOR: { label: "보통", glyph: "△", tone: "info" },
  INFO: { label: "참고", glyph: "○", tone: "muted" },
};

/** 제출 상태 → 낱말 · 기호 · 색 · 처음 하는 대표에게 할 말 한 줄. */
export const STATUS_VIEW: Record<BidQualityStatus, { label: string; glyph: string; tone: Tone; note: string }> = {
  BLOCKED: {
    label: "차단",
    glyph: "✕",
    tone: "fail",
    note: "제출 전에 꼭 채우거나 고칠 곳이 남았습니다 — 아래 「차단」 항목부터 처리하세요. 파일은 받을 수 있지만 이름이 「초안」입니다.",
  },
  NEEDS_REVIEW: {
    label: "검토 필요",
    glyph: "!",
    tone: "warn",
    note: "막는 항목은 없지만 사람이 확인할 곳이 있습니다 — 「중요」 항목을 보고 고친 뒤 승인하세요. 승인 전까지 파일 이름은 「초안」입니다.",
  },
  VERIFIED_DRAFT: {
    label: "자동검증 통과",
    glyph: "●",
    tone: "info",
    note: "자동 검사에서 막는 항목 · 중요 항목이 없습니다 — 담당자가 전체를 읽고 승인하면 「제출 준비」가 됩니다. 승인 전까지 파일 이름은 「초안」입니다.",
  },
  READY_TO_SUBMIT: {
    label: "제출 준비",
    glyph: "✓",
    tone: "pass",
    note: "사람이 읽고 승인했습니다 — 제출용 파일 이름으로 받습니다. 초안을 다시 쓰면 승인은 풀립니다.",
  },
};

/** 남은 차단이 모두 정상 담당자 입력(갈래 input)일 때 「차단」 풀이 — 앱이 고칠 것과 섞지 않는다(2.9.0 · 3차 지시서 §12). */
export const BLOCKED_INPUT_NOTE =
  "자동 작성은 끝났습니다 — 남은 차단은 담당자가 채울 칸(인력 · 회사 값)뿐입니다. 받은 한글 · 워드 파일에서 채우세요. 파일 이름은 「초안」입니다.";

/** 차단이 하나라도 있고 모두 담당자 입력 갈래인가(옛 응답 — 갈래 칸이 없으면 false). */
export function blockersAllInput(quality: Pick<BidQuality, "findings">): boolean {
  const blockers = (quality.findings ?? []).filter((f) => f.severity === "BLOCKER");
  return blockers.length > 0 && blockers.every((f) => f.axis === "input");
}

/** 알 수 없는 상태 값이 오면(새 서버 · 옛 화면) 서버 낱말을 그대로 쓰고 「검토 필요」 모양으로 그린다. */
export function statusView(quality: Pick<BidQuality, "status" | "status_label"> & Partial<Pick<BidQuality, "findings">>) {
  const known = STATUS_VIEW[quality.status];
  if (known) {
    const note = quality.status === "BLOCKED" && blockersAllInput({ findings: quality.findings ?? [] }) ? BLOCKED_INPUT_NOTE : known.note;
    return { ...known, label: quality.status_label || known.label, note };
  }
  return { ...STATUS_VIEW.NEEDS_REVIEW, label: quality.status_label || STATUS_VIEW.NEEDS_REVIEW.label };
}

/** 자동 작성 검사 → 낱말 · 기호 · 색 · 한 줄(2.9.0 · 서버 `generation`). */
export const GENERATION_VIEW: Record<BidQualityGeneration["status"], { label: string; glyph: string; tone: Tone; note: string }> = {
  PASS: { label: "자동 작성 완료", glyph: "✓", tone: "pass", note: "앱이 고칠 것이 없습니다 — 남은 것은 담당자 입력 · 증빙 · 사실 확인입니다." },
  REVIEW: { label: "자동 작성 완료 · 검토할 경고 있음", glyph: "!", tone: "warn", note: "앱이 쓴 글에 검토할 경고가 있습니다(아래 「수정 필요」 갈래)." },
  FAIL: { label: "자동 작성 결함 — 수정 필요", glyph: "✕", tone: "fail", note: "앱이 자동으로 채웠어야 할 곳이 비었거나 틀렸거나 공고와 달라졌습니다 — 초안을 다시 쓰거나 아래 「수정 필요」 항목을 고치세요." },
  ERROR: { label: "검증 못 함", glyph: "✕", tone: "fail", note: "자동 검사를 실행하지 못했습니다 — 잠시 뒤 다시 여세요." },
};

/** 서버가 `generation` 을 주면 그 낱말로 · 옛 응답은 null(줄을 그리지 않음). */
export function generationView(quality: Pick<BidQuality, "generation">) {
  const generation = quality.generation;
  if (!generation) return null;
  const known = GENERATION_VIEW[generation.status];
  return known ? { ...known, label: generation.label || known.label } : { ...GENERATION_VIEW.REVIEW, label: generation.label };
}

/** 갈래 → 화면 낱말(관리자 화면 상태 · 3차 지시서 §9). */
export const AXIS_VIEW: Record<BidQualityAxis, { label: string; glyph: string; tone: Tone }> = {
  auto: { label: "수정 필요", glyph: "✕", tone: "fail" },
  input: { label: "담당자 입력 필요", glyph: "✎", tone: "warn" },
  evidence: { label: "증빙 필요", glyph: "▣", tone: "warn" },
  fact: { label: "사실 확인 필요", glyph: "?", tone: "info" },
};

export interface ReadinessChip {
  key: string;
  label: string;
  glyph: string;
  tone: Tone;
  /** 건수 — 「자동 작성 완료」 · 「검증 완료」는 null(켜짐 · 꺼짐만) */
  count: number | null;
  active: boolean;
}

/**
 * 여섯 상태 칸(3차 지시서 §9) — 자동 작성 완료 · 수정 필요 · 담당자 입력 필요 · 증빙 필요 · 사실 확인 필요 · 검증 완료.
 * 서버 `generation` · `axes` · `status` 를 옮길 뿐이다. 두 칸이 없는 옛 응답은 빈 목록(그리지 않음).
 */
export function readinessChips(quality: Pick<BidQuality, "generation" | "axes" | "status">): ReadinessChip[] {
  const generation = quality.generation;
  const axes = quality.axes;
  if (!generation || !axes) return [];
  const done = generation.status === "PASS" || generation.status === "REVIEW";
  const chips: ReadinessChip[] = [
    { key: "generated", label: "자동 작성 완료", glyph: done ? "✓" : "—", tone: done ? "pass" : "muted", count: null, active: done },
  ];
  for (const axis of ["auto", "input", "evidence", "fact"] as const) {
    const count = axes[axis] ?? 0;
    chips.push({ key: axis, ...AXIS_VIEW[axis], tone: count > 0 ? AXIS_VIEW[axis].tone : "muted", count, active: count > 0 });
  }
  const verified = quality.status === "READY_TO_SUBMIT";
  chips.push({ key: "verified", label: "검증 완료", glyph: verified ? "✓" : "—", tone: verified ? "pass" : "muted", count: null, active: verified });
  return chips;
}

/** 빈칸 목록 묶음(3차 지시서 §9 · 2.9.0) — 붙일 서류 · 확인할 원문 값 · 회사가 정할 값 · 본문에서 뺀 문장. 서버 빈칸 이름(field)으로만 가른다. */
export const BLANK_GROUP_LABELS = {
  retry: "AI 가 못 쓴 소항목(다시 쓰기 · 앱이 고칠 것)",
  supplements: "붙일 서류 · 필요한 자료(공고가 요구)",
  notice: "확인할 제안요청서 값",
  decide: "회사가 정할 값 · 담당자 입력",
  cost: "예산 · 수행 가능성(내부 검토 — 제출용에 없음)",
  moved: "본문에서 뺀 문장(근거 · 표현 확인)",
} as const;
export type BlankGroupKey = keyof typeof BLANK_GROUP_LABELS;
/** 빈칸 한 줄 끝 「필요한 자료: …」(2.10.0 m4 · 서버 `proof` — 없으면 그리지 않음). */
export const BLANK_PROOF_LABEL = "필요한 자료";
// 「공고 제출서류」 · 「제출 방법」 — 입찰공고문 제출서류 · ※ 줄(2.10.0 T8 · 서버 `bid_proposal_service.PAPER_FIELD` · `PAPER_NOTE_FIELD`)
const SUPPLEMENT_FIELDS = new Set(["서식 첨부", "붙임 증빙", "공고 제출서류", "제출 방법"]);
const MOVED_BLANK_FIELDS = new Set(["회사 근거 없는 회사 주장", "값을 정하면 넣을 문장", "담당자 확인", "과장 표현"]);

export function blankGroup(blank: { field: string; why: string }): BlankGroupKey {
  if (blank.why.startsWith("AI 가 쓰지 못한 소항목")) return "retry";
  if (SUPPLEMENT_FIELDS.has(blank.field) || blank.why === "사람만 채우는 표" || blank.why.startsWith("서식 첨부")) return "supplements";
  if (blank.field === "원문 정량값 확인") return "notice";
  if (blank.field === "비용 항목") return "cost";
  if (MOVED_BLANK_FIELDS.has(blank.field)) return "moved";
  return "decide";
}

/** 묶음 순서대로 · 빈 묶음은 뺀다. */
export function blankGroups<T extends { field: string; why: string }>(blanks: readonly T[]): { key: BlankGroupKey; label: string; items: T[] }[] {
  return (Object.keys(BLANK_GROUP_LABELS) as BlankGroupKey[])
    .map((key) => ({ key, label: BLANK_GROUP_LABELS[key], items: blanks.filter((blank) => blankGroup(blank) === key) }))
    .filter((group) => group.items.length > 0);
}

/** 항목의 갈래 낱말(「담당자 입력 필요」) — 옛 응답은 null. */
export function axisLabel(finding: BidQualityFinding): string | null {
  return finding.axis ? AXIS_VIEW[finding.axis]?.label ?? null : null;
}

/** 심각도 하나의 수 — 서버 `counts` 가 먼저, 없으면 목록 건수. */
export function severityTotal(quality: Pick<BidQuality, "counts" | "findings">, severity: BidQualitySeverity): number {
  const counted = quality.counts?.[severity];
  if (typeof counted === "number") return counted;
  return (quality.findings ?? []).filter((finding) => finding.severity === severity).length;
}

/** 「차단 2 · 중요 3 · 보통 0 · 참고 1」. */
export function countsLine(quality: Pick<BidQuality, "counts" | "findings">): string {
  return SEVERITY_ORDER.map((severity) => `${SEVERITY_VIEW[severity].label} ${severityTotal(quality, severity)}`).join(" · ");
}

export interface SeverityGroup {
  severity: BidQualitySeverity;
  label: string;
  glyph: string;
  tone: Tone;
  total: number;
  items: BidQualityFinding[];
  /** 처음부터 펼칠지 — 차단 · 중요만 */
  open: boolean;
}

/** 심각도 순서(차단 → 중요 → 보통 → 참고)로 묶는다. 같은 심각도 안은 서버 순서 그대로 · 빈 묶음은 뺀다. */
export function severityGroups(quality: Pick<BidQuality, "counts" | "findings">): SeverityGroup[] {
  const findings = quality.findings ?? [];
  return SEVERITY_ORDER.map((severity) => ({
    severity,
    ...SEVERITY_VIEW[severity],
    total: severityTotal(quality, severity),
    items: findings.filter((finding) => finding.severity === severity),
    open: severity === "BLOCKER" || severity === "MAJOR",
  })).filter((group) => group.items.length > 0 || group.total > 0);
}

/** 항목 한 줄 — 「제출용에 빈칸 표시가 남음 (5곳) · 소항목 「2. 사업 수행 조직」」. 서버가 위치(2.8.0 `location`)를 주면 그것이 먼저. */
export function findingLine(finding: BidQualityFinding): string {
  const many = finding.count > 1 ? ` (${finding.count}곳)` : "";
  const location = finding.location?.trim();
  const where = location ? ` · 위치: ${location}` : finding.section ? ` · 소항목 「${finding.section}」` : "";
  return `${finding.title}${many}${where}`;
}

/** 「고치는 법 — …」 — 서버 `action`(2.8.0) 그대로 · 없으면 null(줄을 그리지 않음). */
export function findingAction(finding: BidQualityFinding): string | null {
  const action = finding.action?.trim();
  return action ? `고치는 법 — ${action}` : null;
}

/** 「자동 검사 11월 11일 09:05 · 검사 규칙 판 2」 — 두 칸이 모두 없는 옛 응답은 null. */
export function checkedLine(quality: Pick<BidQuality, "checked_at" | "gate_version">): string | null {
  const parts: string[] = [];
  const time = quality.checked_at ? approvalTime(quality.checked_at) : "";
  if (time) parts.push(`자동 검사 ${time}`);
  if (typeof quality.gate_version === "number") parts.push(`검사 규칙 판 ${quality.gate_version}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** 「제출용 파일 미작성 칸 3곳 · 검토용 「담당자가 채울 항목」 5건」 — 두 칸이 모두 없는 옛 응답은 null. */
export function blanksLine(quality: Pick<BidQuality, "submit_blanks" | "review_blanks">): string | null {
  const parts: string[] = [];
  if (typeof quality.submit_blanks === "number") parts.push(`제출용 파일 미작성 칸 ${quality.submit_blanks}곳`);
  if (typeof quality.review_blanks === "number") parts.push(`검토용 「담당자가 채울 항목」 ${quality.review_blanks}건`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export interface HwpxCheckView {
  /** none — 아직 안 받음 · match — 맞음 · differ — 다름 */
  state: "none" | "match" | "differ";
  glyph: string;
  tone: Tone;
  text: string;
}

/**
 * 마지막 한글(HWPX) 파일 검사 — 맞음 · 다름 · 아직 안 받음(2.8.0 `hwpx_check`).
 * 칸이 없는 옛 응답(undefined)은 null — 줄을 그리지 않는다. 서버가 정한 값을 낱말로만 옮긴다.
 */
export function hwpxCheckView(check: BidHwpxCheck | null | undefined): HwpxCheckView | null {
  if (check === undefined) return null;
  if (check === null) {
    return { state: "none", glyph: "○", tone: "muted", text: "한글 파일 검사 — 아직 받지 않음(한글 파일을 받으면 만든 파일 글을 다시 읽어 미작성 칸 수를 자동 검사와 맞춰 봅니다)" };
  }
  const time = approvalTime(check.at);
  const when = time ? ` (${time})` : "";
  const majors = check.duplicate_majors ?? [];
  const dup = majors.length > 0 ? ` · 대항목 번호 겹침 ${majors.join(" · ")}` : "";
  // 평가본은 식별 칸을 가려 미작성 칸 수가 제출용보다 적다 — 어느 판을 검사했는지 밝힌다(2.8.0 검토)
  // 평가본만 받는 공고(2.10.0 D8)는 평가본이 제출 파일 · 회사명 판은 「회사명 포함본」(서버 variant_label 과 같은 이름 · 11-13 독립 검토)
  const head = check.blind_only
    ? check.variant === "blind" ? "제출용(평가본) 한글 파일 검사" : check.variant === "submit" ? `${WITH_NAME_LABEL} 한글 파일 검사` : "한글 파일 검사"
    : check.variant === "blind" ? "평가본 한글 파일 검사" : check.variant === "submit" ? "제출용 한글 파일 검사" : "한글 파일 검사";
  if (!check.ok) return { state: "differ", glyph: "✕", tone: "fail", text: `${head} — 다름: 한글 파일 구조 검사를 통과하지 못했습니다${when}` };
  if (!check.reextract_ok || check.placeholders === null) {
    return { state: "differ", glyph: "!", tone: "warn", text: `${head} — 다름: 만든 파일 글을 다시 읽지 못해 그 파일은 「초안」 이름으로 받았습니다${when}${dup}` };
  }
  if (check.match && majors.length > 0) {
    return { state: "differ", glyph: "!", tone: "warn", text: `${head} — 다름: 파일 안 대항목 번호가 겹칩니다(${majors.join(" · ")}) — 그 파일은 「초안」 이름으로 받았습니다${when}` };
  }
  if (!check.match) {
    return {
      state: "differ",
      glyph: "!",
      tone: "warn",
      text: `${head} — 다름: 파일 안 미작성 칸 ${check.placeholders}곳 · 자동 검사 ${check.gate_spots}곳 — 그 파일은 「초안」 이름으로 받았습니다${when}${dup}`,
    };
  }
  return { state: "match", glyph: "✓", tone: "pass", text: `${head} — 맞음: 파일 안 미작성 칸 ${check.placeholders}곳 = 자동 검사 ${check.gate_spots}곳${when}${dup}` };
}

export const REPORT_LINK_LABEL = "검증 보고서 받기";
export const REPORT_LINK_TITLE = "자동 검사 결과와 검사 이력(언제 · 어떤 파일 · 결과)을 파일 하나(JSON)로 받습니다 — 관리자 · 개발자에게 보낼 때";
/** (2.10.0 T8) 검사 보고서 엑셀 — 대표 · 담당자가 열어 보는 판. */
export const REPORT_XLSX_LABEL = "검사 보고서(엑셀)";
export const REPORT_XLSX_TITLE = "검사 항목(수정 위치 · 근거 · 상태 · 남은 조치) · 담당자 확인 사항(필요한 자료) · 제출 서류(유효기간 · 마감) 세 시트를 엑셀로 받습니다";

/** (2.10.0 T8) 한글에서 저장한 PDF 검사 — 단추 · 풀이 · 잠금 · 실패 글. */
export const PDF_CHECK_LABEL = "한글에서 저장한 PDF 검사";
export const PDF_CHECK_BUSY = "PDF 검사하는 중…";
export const PDF_CHECK_NOTE =
  "받은 한글 파일을 고쳐 「PDF 로 저장」한 최종 파일을 올리면 쪽수 · A4 · 미작성 칸 · 평가본 회사 정보 · 표지 링크 · 예산 산수 · 조견표 실제 쪽을 봅니다. 제출 상태 · 승인은 바꾸지 않습니다.";
export const PDF_CHECK_BLOCKED = "PDF 검사 잠김";
export const PDF_CHECK_FAILED = "PDF 를 검사하지 못했습니다";
export const PDF_CHECK_FINDINGS = "PDF 검사 항목";

export interface PdfCheckView {
  /** none — 아직 안 함 · ok — 통과 · issues — 고칠 곳 · unreadable — 검사 못 함 */
  state: "none" | BidPdfCheck["state"];
  glyph: string;
  tone: Tone;
  text: string;
}

/**
 * 마지막 PDF 검사 한 줄(2.10.0 `pdf_check`) — 칸이 없는 옛 응답(undefined)은 null(줄을 그리지 않음).
 * 서버가 정한 상태를 낱말로만 옮긴다 · 검사 못 함은 통과가 아니다.
 */
export function pdfCheckView(check: BidPdfCheck | null | undefined): PdfCheckView | null {
  if (check === undefined) return null;
  if (check === null) return { state: "none", glyph: "○", tone: "muted", text: `${PDF_CHECK_LABEL} — 아직 하지 않음` };
  const time = approvalTime(check.at);
  const when = time ? ` (${time})` : "";
  const pages = check.pages ? `PDF ${check.pages}쪽${check.page_limit ? ` · 원문 상한 ${check.page_limit}쪽` : ""}` : "";
  if (check.state === "unreadable") {
    return { state: "unreadable", glyph: "✕", tone: "fail", text: `${PDF_CHECK_LABEL} — 검사 못 함 — 통과가 아닙니다(아래 항목)${when}` };
  }
  if (check.state === "issues") {
    const counts = `차단 ${check.counts?.BLOCKER ?? 0} · 중요 ${check.counts?.MAJOR ?? 0}`;
    return { state: "issues", glyph: "!", tone: "warn", text: `${PDF_CHECK_LABEL} — 고칠 곳 있음: ${counts}${pages ? ` · ${pages}` : ""}${when}` };
  }
  return { state: "ok", glyph: "✓", tone: "pass", text: `${PDF_CHECK_LABEL} — 통과: ${pages || "쪽수 모름"} · 차단 · 중요 없음${when}` };
}

/** 평가 항목 대응 상태 → 낱말 · 기호 · 색(기호 + 글자가 뜻 · 색은 덧붙임). */
export const COVERAGE_STATUS_VIEW: Record<BidEvaluationCoverage["status"], { label: string; glyph: string; tone: Tone }> = {
  OK: { label: "연결됨", glyph: "✓", tone: "pass" },
  REVIEW: { label: "검토", glyph: "!", tone: "warn" },
  MISSING: { label: "목차 없음", glyph: "✕", tone: "fail" },
};
const COVERAGE_BODY_LABEL: Record<BidEvaluationCoverage["body"], string> = { 확인: "내용 있음", 없음: "내용 없음(근사)", 미확인: "확인 안 함" };
const COVERAGE_SOURCE_LABEL: Record<NonNullable<BidEvaluationCoverage["source"]>, string> = {
  ai: "AI 가 적음",
  title: "제목 이름으로",
  heading: "본문 소제목으로",
  guide: "작성 방법 · 본문 기준으로",
  ai_retry: "AI 에 다시 물어",
};
/** 목차가 빈 항목의 세 상태(2.9.0 · 3차 지시서 §3). */
export function coverageGapText(gap: BidEvaluationCoverage["gap"], candidate: string | null | undefined): string | null {
  if (gap === "auto_link") return `본문${candidate ? ` ${candidate}` : ""}에 내용 있음 — 자동 연결 실패(앱이 고칠 것)`;
  if (gap === "evidence") return "인력 · 증빙 항목 — 참여인력 · 증빙을 정한 뒤 목차를 적을 것";
  if (gap === "no_body") return "본문에 그 평가 내용 없음 — 다시 쓰거나 보강";
  return null;
}

export interface CoverageRow {
  key: string;
  /** 「영역 › 항목」 */
  name: string;
  /** 「정성」 · 「정량」 · 빈 글 */
  kind: string;
  /** 「5점」 · 「—」 */
  points: string;
  /** 「Ⅲ-2」 · 「— 연결 안 됨」 */
  mapped: string;
  /** 「AI 가 적음」 · 「본문 소제목으로」 · null */
  source: string | null;
  body: string;
  status: { label: string; glyph: string; tone: Tone };
}

/** 평가항목 대응표 행(2.8.0 `evaluation_coverage`) — 칸이 없으면 빈 목록. 모르는 상태 값은 「검토」 모양. */
export function coverageRows(quality: Pick<BidQuality, "evaluation_coverage">): CoverageRow[] {
  return (quality.evaluation_coverage ?? []).map((item, index) => ({
    key: `${index}-${item.name}`,
    name: item.area && item.area !== item.name ? `${item.area} › ${item.name}` : item.name,
    kind: item.kind ?? "",
    points: typeof item.points === "number" ? `${item.points}점` : "—",
    mapped: item.mapped || ["— 연결 안 됨", coverageGapText(item.gap, item.candidate)].filter(Boolean).join(" · "),
    source: item.source ? COVERAGE_SOURCE_LABEL[item.source] ?? null : null,
    body: COVERAGE_BODY_LABEL[item.body] ?? item.body,
    status: COVERAGE_STATUS_VIEW[item.status] ?? COVERAGE_STATUS_VIEW.REVIEW,
  }));
}

/** 「평가 항목 9개 — 연결됨 7 · 검토 1 · 목차 없음 1」. */
export function coverageSummary(quality: Pick<BidQuality, "evaluation_coverage">): string {
  const items = quality.evaluation_coverage ?? [];
  const count = (status: BidEvaluationCoverage["status"]) => items.filter((item) => item.status === status).length;
  return `평가 항목 ${items.length}개 — ${(["OK", "REVIEW", "MISSING"] as const).map((status) => `${COVERAGE_STATUS_VIEW[status].label} ${count(status)}`).join(" · ")}`;
}

/** 대응표는 접어 둔다 — 「목차 없음」이 하나라도 있을 때만 처음부터 펼친다. */
export function coverageOpen(quality: Pick<BidQuality, "evaluation_coverage">): boolean {
  return (quality.evaluation_coverage ?? []).some((item) => item.status === "MISSING");
}

export const EVIDENCE_NOTE =
  "「회사가 적은 값」은 회사자료에 적은 그대로라 앱이 증빙(계약서 · 확인서)을 확인하지 않았다는 뜻입니다 — 제출 전에 증빙 서류를 챙기세요.";

/**
 * 근거 상태 요약 줄(2.8.0 `evidence_status`) — 인용한 실적 · 인증 · 참여인력 · 서버 메모. 칸이 없으면 빈 목록.
 * `warn` 은 사람이 챙길 것(미확인 · 빠짐 · 지남 · 명부 없음)이 있는 줄.
 */
export function evidenceLines(status: BidEvidenceStatus | null | undefined): { text: string; warn: boolean }[] {
  if (!status) return [];
  // 「인용한 실적 3건 — 회사가 적은 값 2 · 증빙 미확인 1」 · 0 인 칸은 뺀다 · 인용 0 이면 「… 없음」
  const line = (head: string, cited: number, pairs: [string, number][]) => {
    if (cited <= 0) return `${head} 없음`;
    const tail = pairs.filter(([, n]) => n > 0).map(([label, n]) => `${label} ${n}`).join(" · ");
    return `${head} ${cited}건${tail ? ` — ${tail}` : ""}`;
  };
  const { ledger, certifications: certs } = status;
  const lines: { text: string; warn: boolean }[] = [
    {
      text: line("인용한 실적", ledger.cited, [["회사가 적은 값", ledger.SELF_REPORTED], ["증빙 미확인", ledger.UNVERIFIED], ["원장에 없거나 기간 · 금액 빠짐", ledger.MISSING]]),
      warn: ledger.UNVERIFIED > 0 || ledger.MISSING > 0,
    },
    {
      text: line("인용한 인증", certs.cited, [["회사가 적은 값", certs.SELF_REPORTED], ["유효기간 지남", certs.EXPIRED], ["유효기간 모름", certs.MISSING]]),
      warn: certs.EXPIRED > 0 || certs.MISSING > 0,
    },
  ];
  if (status.personnel === "MISSING") {
    lines.push({ text: "참여인력 — 명부 없음: 앱은 사람 이름 · 경력을 짓지 않습니다(받은 파일에서 채우세요)", warn: true });
  }
  for (const note of status.notes ?? []) if (note.trim()) lines.push({ text: note.trim(), warn: false });
  return lines;
}

/** 승인 메모 칸 — 선택 · 200자. */
export const APPROVAL_NOTE_MAX = 200;
/** 보낼 승인 메모 — 앞뒤 공백을 떼고 200자까지 · 빈 글이면 undefined(보내지 않음). */
export function approvalNote(raw: string): string | undefined {
  const note = raw.trim().slice(0, APPROVAL_NOTE_MAX).trim();
  return note || undefined;
}

export const STAFFING_UNCONFIRMED_LABEL = "인력 미확정";
/** 어느 표가 비었는지는 아래 「인력 미확정」 항목이 표마다 말한다(조직 표만 있는 공고도 있음 — 2.7.0 검토). */
export const STAFFING_UNCONFIRMED_NOTE =
  "공고가 요구한 인력 칸이 비어 있습니다(어느 표인지는 아래 「인력 미확정」 항목) — 앱은 사람 이름 · 경력 · 업무를 지어내지 않습니다. 받은 한글 · 워드 파일에서 직접 채우세요.";

/** 이 검사가 있으면 차단이 0 이어도 승인할 수 없다(서버 `bid_quality_gate.VOID_CODES` 와 같은 목록 · 2.8.0 B2). */
export const APPROVAL_VOID_CODES: readonly string[] = ["STALE", "NOTICE_MISMATCH", "NOTICE_TERMS", "GATE_ERROR"];

/**
 * 승인 단추를 누를 수 없는 까닭 — 없으면 null. `roleBlock` 은 화면이 역할 훅으로 정한 글(열람자 · 읽기 전용 배포).
 * 규칙 · 글은 서버 `approvable` · `approve_block_reason` 과 같다(다르면 누를 수 있어 보이는 단추가 409 를 낸다 · 2.8.0 검토).
 */
export function approveBlockReason(quality: Pick<BidQuality, "counts" | "findings">, roleBlock: string | null): string | null {
  if (roleBlock) return roleBlock;
  const findings = quality.findings ?? [];
  const blockers = severityTotal(quality, "BLOCKER");
  const voids = new Set(findings.map((f) => f.code).filter((code) => APPROVAL_VOID_CODES.includes(code)));
  if (blockers <= 0 && voids.size === 0) return null;
  if (voids.has("GATE_ERROR")) return "검증을 실행하지 못해 승인할 수 없습니다 — 잠시 뒤 다시 열어 보고, 계속되면 관리자에게 알리세요";
  // 남은 차단이 앱 안에서 채울 수 없는 인력 칸뿐이면 「다시 쓰세요」를 권하지 않는다(2.7.0 검토) — 단 승인 무효 검사가 있으면 그 까닭이 먼저(2.9.0)
  const blockerFindings = findings.filter((f) => f.severity === "BLOCKER");
  const onlyInput = blockerFindings.length > 0 && blockerFindings.every((f) => f.axis === "input" || f.code === "STAFFING_UNCONFIRMED");
  if ((blockerFindings.length === 0 || onlyInput) && voids.size > 0) {
    if (voids.size === 1 && voids.has("NOTICE_TERMS")) {
      return "본문의 사업기간 · 사업금액이 공고 원문과 달라 승인할 수 없습니다 — 원문 값으로 고쳐 초안을 다시 쓴 뒤 승인하세요";
    }
    return "초안을 쓴 뒤 공고 · 요구사항이 바뀌어 승인할 수 없습니다 — 초안을 다시 쓴 뒤 승인하세요";
  }
  if (blockerFindings.length > 0 && blockerFindings.every((f) => f.code === "STAFFING_UNCONFIRMED")) {
    return "앱 안에서는 채울 수 없는 인력 칸만 남았습니다 — 받은 한글 · 워드 파일에서 채워 내세요(파일 이름은 「초안」으로 나갑니다)";
  }
  if (onlyInput) {
    return "자동 작성은 끝났고 담당자 입력 칸만 남았습니다 — 회사자료에 적거나 받은 한글 · 워드 파일에서 채워 내세요(파일 이름은 「초안」으로 나갑니다)";
  }
  return `차단 ${blockerFindings.length || blockers}건이 남아 승인할 수 없습니다 — 먼저 채우거나 고친 뒤 초안을 다시 쓰세요`;
}

/** 「11월 8일 09:05」 — 이 컴퓨터 시각. 못 읽으면 빈 글. */
export function approvalTime(at: string): string {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return "";
  const hh = String(when.getHours()).padStart(2, "0");
  const mm = String(when.getMinutes()).padStart(2, "0");
  return `${when.getMonth() + 1}월 ${when.getDate()}일 ${hh}:${mm}`;
}

/** 「홍길동 님이 11월 8일 09:05에 승인」 — 표시 이름이 없으면 아이디. */
export function approvalLine(approval: BidQualityApproval): string {
  const who = approval.by_name || approval.by;
  const time = approvalTime(approval.at);
  return `${who} 님이 ${time ? `${time}에 ` : ""}승인`;
}

/** 「제출용」 판 내려받기의 이름 표시 — 서버 `file_label` 그대로 · 칸이 없는 옛 초안은 늘 쓰던 「제출용」. */
export function submitFileLabel(quality: Pick<BidQuality, "file_label"> | null | undefined): "초안" | "제출용" {
  return quality?.file_label === "초안" ? "초안" : "제출용";
}

export const DRAFT_FILE_TITLE =
  "제출용과 같은 본문(표식 · 메모 없음)입니다 — 차단 · 중요 항목이 남았거나 사람 승인 전이라 파일 이름이 「제안서_초안_…」입니다";

/** 「Claude로 쓰기」 · 「Codex로 쓰기」를 누를 때 초안이 이미 있으면 묻는 창 — 없으면 null(묻지 않고 쓴다). */
export function rewriteConsent(writerLabel: string, hasDraft: boolean, approved: boolean): ConsentRequest | null {
  if (!hasDraft) return null;
  return {
    title: "있던 초안을 새로 쓸까요?",
    body: `있던 초안을 새로 씁니다 — 옛 판은 보관됩니다.${approved ? " 승인도 풀려 다시 승인해야 합니다." : ""} ${writerLabel} 가 대항목마다 다시 쓰며 3~5분 걸립니다.`,
    confirmLabel: `${writerLabel}로 다시 쓰기`,
    cancelLabel: "취소",
  };
}
