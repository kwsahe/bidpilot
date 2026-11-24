/**
 * 「입찰 참가 가능 여부」를 **앞에 세우는** 숫자 (20차 §4-D · ISSUE-140).
 *
 * 담당자 말: 「자격요건 같은 경우는 안 맞으면 입찰 신청 자체를 못하니까 더 강조되면서 보여줘야 함.
 * 하나하나씩 체크 및 확인할 수 있는 기능도 필요하고.」
 *
 * 상세 맨 위 띠 · KPI 타일 · 「지금 할 일」 첫 줄 · 3단계 체크리스트 머리가 **같은 숫자**를 쓴다 —
 * 계산은 여기 하나다. 조항 줄은 `clause_id` 가 있는 줄(QUAL-<종류>-<조항>)이고, 줄 하나가 조항 하나다
 * (백엔드 20차 §4-B). `QUAL-DOC`(공고문을 못 읽었다)은 조항이 아니라 확인할 수 없는 줄이다.
 */

import { ELIGIBILITY_GATE_LABELS } from "@/lib/scoreNames";
import type { EligibilityResult, EligibilityStatus } from "@/types/cosmos";

export interface EligibilityGateView {
  verdict: EligibilityStatus;
  /** 참가자격 조항 줄 수 (= 조항 수) */
  total: number;
  /** 담당자가 충족·미충족으로 확인한 조항 (원문이 바뀐 확인은 세지 않는다) */
  done: number;
  /** 아직 확인 전인 조항 (보류 · 다시 확인 포함) */
  pending: number;
  /** 확인한 뒤 조항 원문이 바뀌어 다시 확인해야 하는 조항 */
  stale: number;
  /** 확인 필요 중 회사가 채울 것 · 원문을 읽어야 할 것 */
  company: number;
  notice: number;
  /** 조항이 아닌 줄(공고 필드 검사 · 공고문 절)의 확인 필요 수 */
  fieldCheck: number;
  /** 종합이 불가일 때 막는 첫 줄 — 조항 줄을 먼저 본다 */
  blocking: EligibilityResult | null;
  /** 공고문 참가자격 절을 아직 못 읽었다(QUAL-DOC). */
  docUnread: boolean;
  /** 받았는데 못 읽은 사유(스캔 이미지 · 절 없음 · 여는 중 실패) — 「아직 안 읽음」(받기 전)이면 null(33차 R32-06). */
  docNote: string | null;
}

/** 백엔드 `eligibility_engine._doc_result` 의 「받기 전」 사유 표식 — 시험이 두 파일을 함께 본다. */
export const DOC_NOT_FETCHED_MARK = "아직 안 읽었습니다";

export function isClauseRow(row: EligibilityResult): boolean {
  return Boolean(row.clause_id);
}

/**
 * 3단계 「참가자격 조항」 절에 들어가는 줄 — 조항 줄(QUAL-<종류>-<조항>)과 공고문을 못 읽었다는 줄(QUAL-DOC).
 * 공고 필드 검사(ELIG-*)는 다른 절이다. 상세 체크리스트와 지도 ③ 정거장이 같은 줄을 쓴다.
 */
export function inClauseSection(row: EligibilityResult): boolean {
  return row.rule_id.startsWith("QUAL-");
}

function verdictOf(rows: EligibilityResult[]): EligibilityStatus {
  if (rows.some((r) => r.status === "FAIL")) return "FAIL";
  if (rows.some((r) => r.status === "CHECK")) return "CHECK";
  return "PASS";
}

/** 판정 줄들로 띠·타일 숫자를 만든다. 줄이 하나도 없으면 null(아직 판정 전). */
export function eligibilityGateView(
  rows: EligibilityResult[],
  verdict?: EligibilityStatus | null,
): EligibilityGateView | null {
  if (rows.length === 0) return null;
  const clauses = rows.filter(isClauseRow);
  const done = clauses.filter((r) => r.review_state === "met" || r.review_state === "unmet").length;
  const failed = rows.filter((r) => r.status === "FAIL");
  const doc = rows.find((r) => r.rule_id === "QUAL-DOC" && r.status !== "PASS");
  return {
    verdict: verdict ?? verdictOf(rows),
    total: clauses.length,
    done,
    pending: clauses.length - done,
    stale: clauses.filter((r) => r.review_state === "stale").length,
    company: clauses.filter((r) => r.status === "CHECK" && r.check_side === "company").length,
    notice: clauses.filter((r) => r.status === "CHECK" && r.check_side !== "company").length,
    fieldCheck: rows.filter((r) => !isClauseRow(r) && r.status === "CHECK").length,
    // 공고문 참가자격 절을 아직 못 읽었다(QUAL-DOC 확인 필요) — 조항이 0개여도 「조건이 없다」가 아니다(32차 §3-B-1)
    docUnread: Boolean(doc),
    // 스캔 · 절 없음이면 「공고 분석 시작」을 눌러도 같다 — 그 사유를 그대로 보인다(33차 R32-06)
    docNote: doc && !doc.reason.includes(DOC_NOT_FETCHED_MARK) ? doc.reason : null,
    blocking: failed.find(isClauseRow) ?? failed[0] ?? null,
  };
}

/**
 * 막는 줄 한 줄 — 「지역 조항: 입찰공고일 전일부터 …」(조항 원문 앞 60자, 없으면 판정 사유).
 * 10-31 최종 점검 — 사유 끝 「(기준시각 … KST)」는 떼고 끝 마침표도 뗀다(뒤에 문장을 잇는 조각이다) — 그 괄호 탓에
 * 60자에 걸려 「(기준시각 2026-10-31 15…」로 시각 중간이 잘렸다.
 */
export function blockingText(row: EligibilityResult): string {
  const text = (row.clause_text ?? row.reason)
    .replace(/\s*\(기준시각[^)]*\)/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[.\s]+$/, "");
  return `${row.label}: ${text.length > 60 ? `${text.slice(0, 60)}…` : text}`;
}

/**
 * 확정 안 한 조항의 내역 — 「회사 정보 필요 5 · 공고문 더 읽기 3 · 사람 확인만 남음 1」.
 * 10-31 최종 점검 — 규칙이 이미 「가능」으로 본 조항(사람 확인 전)에 이름이 없어 「9개 — 5 · 3」처럼 합이 안 맞아 보였다.
 */
export function pendingSidesText(view: EligibilityGateView): string {
  const ruleOnly = view.pending - view.company - view.notice;
  return `회사 정보 필요 ${view.company} · 공고문 더 읽기 ${view.notice}${ruleOnly > 0 ? ` · 사람 확인만 남음 ${ruleOnly}` : ""}`;
}

/** 3단계 체크리스트 줄 순서 — 불가 → 확인 필요(회사 쪽) → 확인 필요(원문) → 가능. 같은 칸 안은 원래 순서. */
export function checklistOrder(rows: EligibilityResult[]): EligibilityResult[] {
  const rank = (r: EligibilityResult): number =>
    r.status === "FAIL" ? 0 : r.status === "CHECK" ? (r.check_side === "company" ? 1 : 2) : 3;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => rank(a.row) - rank(b.row) || a.index - b.index)
    .map(({ row }) => row);
}

/**
 * ③ 의 **두 수** — 「조항 확인 전 n · 공고 필드 확인 m」 (22차 · prompt_12 §4-B).
 *
 * 정거장 캡션(3D·2D) · 레일 요약 · KPI 타일 둘째 줄 · 안내 패널 · 발표 자막이 이 한 문장을 쓴다. 전에는 캡션이
 * 판정 줄 전부의 셈(가능 5 · 확인 필요 12 · 불가 0), 배지가 조항만(확인 전 8), 타일이 조항과 회사 쪽(확인 전 8 · 회사
 * 쪽 3)을 말해 세 곳이 세 가지 수였다. 「가능 · 확인 필요 · 불가」 셈은 3단계 절 머리(체크리스트 위)에만 둔다.
 *
 * n 은 확인 전 조항(`pending` — 보류 · 원문이 바뀌어 다시 볼 것 포함), m 은 조항이 아닌 줄의 확인 필요(`fieldCheck`).
 * 조항을 다 확인했으면 「확인 전 0」 대신 끝났다고 적는다 — 「0개를 확인하라」는 할 일을 가린다.
 */
export function gateCounts(view: EligibilityGateView): string {
  // 30차 §3-F #1 — 「조항 확인 전 · 공고 필드 확인」은 누가 무엇을 안 했는지 말하지 않았다(개발 말 「필드」).
  // 「안 본 조항」은 「보류」로 표시한 조항도 셌다 — 보류도 아직 확정하지 않은 것이라 이름을 그 뜻으로(31차 R30-29)
  if (view.total > 0 && view.pending > 0) return `확정 안 한 조항 ${view.pending} · 기본정보 확인 ${view.fieldCheck}`;
  if (view.total > 0) return view.fieldCheck > 0 ? `조항 다 확정 · 기본정보 확인 ${view.fieldCheck}` : `조항 ${view.total}개 다 확정`;
  return view.fieldCheck > 0 ? `기본정보 확인 ${view.fieldCheck}` : "기본정보 확인 끝";
}

/** 레일 · 정거장 캡션 요약 — 두 수, 불가면 앞에 판정 낱말 「불가」(레일 단계 이름 「참가 가능 여부」가 이미 「참가」를 말한다 · 27차 §3-E 검증 G1-R6). */
export function gateSummary(view: EligibilityGateView): string {
  return view.verdict === "FAIL" ? `${ELIGIBILITY_GATE_LABELS.FAIL} · ${gateCounts(view)}` : gateCounts(view);
}

/**
 * 지도 ③ 정거장 배지 — `gateCounts` 의 **앞 수**를 짧게: 확인 전 조항이 있으면 「확인 전 n」, 조항을 다 봤고 공고
 * 필드만 남았으면 「필드 확인 m」. 없으면 null. 불가면 배지가 아니라 정거장이 잠긴다(붉은 이름 · 끊긴 길) — null.
 * ③ 이 지금 정거장이면 캡션이 같은 말을 하므로 그리는 쪽에서 숨긴다.
 */
export function gateBadge(view: EligibilityGateView | null): string | null {
  if (!view || view.verdict === "FAIL") return null;
  if (view.total > 0 && view.pending > 0) return `확정 안 한 조항 ${view.pending}`;
  if (view.verdict === "CHECK" && view.fieldCheck > 0) return `기본정보 ${view.fieldCheck}`;
  return null;
}

/**
 * 결정 칸 한 줄 (P1-02) — 조건 게이트(요구사항 · 참가자격 불가)만 보면 확정 안 한 조항이 남았는데도
 * 「차단 조건이 없습니다」라 했다. 막는 조건 · 아직 모름(조항 확인 전 · 공고 분석 전) · 확인된 차단 없음을 가른다.
 * open=true 면 안심할 말이 아니다(호박색). 참가자격 「불가」는 위 빨간 상자가 말하므로 null(차단 없음을 그 밑에 적지 않는다).
 */
export function decisionGateLine(
  gate: { can_go: boolean; reason: string },
  requirementsRead: boolean,
  view: EligibilityGateView | null,
): { text: string; open: boolean } | null {
  if (!gate.can_go) return { text: gate.reason, open: true };
  if (view?.verdict === "FAIL") return null;
  const pending = view?.pending ?? 0;
  if (pending > 0)
    return {
      text: `참가 가능 여부는 아직 정해지지 않았습니다 — 참가자격 조항 ${pending}개를 아직 확정하지 않았습니다${requirementsRead ? "" : " · 공고 분석(요구사항 정리)도 아직 하지 않았습니다"}. 지금까지 찾은 참가 차단 조건은 없습니다.`,
      open: true,
    };
  if (!requirementsRead) return { text: gate.reason, open: true }; // 서버 「아직 모름 — 제안요청서를 아직 읽지 않아 …」
  if (view?.verdict === "CHECK" && view.fieldCheck > 0)
    return { text: `확인된 참가 차단 조건은 없습니다 — 다만 공고 기본정보 ${view.fieldCheck}개는 아직 확인 전입니다.`, open: true };
  return { text: "확인된 참가 차단 조건이 없습니다.", open: false };
}

/**
 * 마감일이 비었는데 판정이 「접수 끝남」인 공고 (UI e) — 개찰일이 지나 백엔드가 ELIG-BID-DEADLINE 을 불가로 냈다.
 * 날짜로만 정하면 「마감일 미정」 옆에 「접수가 끝난 공고입니다」가 나란히 섰다. 날짜가 있으면 날짜 규칙 그대로.
 */
export function endedWithoutDate(results: EligibilityResult[], deadline: string | null): boolean {
  return !deadline && results.some((r) => r.rule_id === "ELIG-BID-DEADLINE" && r.status === "FAIL");
}
