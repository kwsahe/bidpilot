/**
 * 사업기회 목록의 행 모델과 「보이는가 · 띠 조건에 맞는가」 판단 (2.1.0).
 *
 * 사업기회 화면(`app/opportunities/page.tsx`)과 대시보드 통계(`components/overview/OverviewShell.tsx`)가
 * **이 함수들 하나로** 센다 — 대시보드의 숫자를 누르면 사업기회가 같은 조건으로 열리고 건수가 같아야 한다(2.0.6 원칙).
 * 예전에는 사업기회 화면 안에만 있었다.
 */

import { daysOverdue, daysUntil, effectiveDeadline, normalizeApplyEnd, pairOf } from "@/lib/deadline";
import type { UnifiedOpportunity } from "@/types/opportunity";
import type { ProcurementNotice } from "@/types/procurement";
import type { SupportProgramView } from "@/types/support";

// ---------------------------------------------------------------------------
// 행 모델 — 두 출처를 한 목록에 놓되 원본 데이터는 그대로 들고 다닌다
// ---------------------------------------------------------------------------

export interface G2bRow {
  kind: "g2b";
  id: string;
  notice: ProcurementNotice;
  unified: UnifiedOpportunity | null;
}

export interface BizinfoRow {
  kind: "bizinfo";
  id: string;
  view: SupportProgramView;
  unified: UnifiedOpportunity | null;
}

/** 직접 넣은 공고 — 「전체」 탭에만 선다(40차 D27 · FRONT-02). 판정 · 순위는 서버 값(`unified`) 그대로다. */
export interface ManualRow {
  kind: "manual";
  id: string;
  unified: UnifiedOpportunity;
}

/** 나라장터 · 기업마당 행 — 카드 · 쉬운 보기 줄이 그리는 것. */
export type SourceRow = G2bRow | BizinfoRow;
export type Row = SourceRow | ManualRow;

/**
 * 나라장터 행 — 통합 목록(실제 마감 기준 · 마감 뺌)을 다 받았는데 거기 없는 입찰은 실제 마감(참가신청 · 제출 마감)이
 * 지난 공고다(45차 M9). `/api/procurements`(입찰 마감 기준)로만 열려 있어 목록 끝에 「판정 못 함 · D-2」로 섞이고 「n위/N」 분모에도
 * 들어갔다 — 마감을 켜지 않았으면 뺀다(`dropUnlisted` · 켜면 통합 목록이 마감까지 실어 그대로 보인다).
 * 사전규격은 39차부터 입찰 목록 밖 — 「선제준비」 탭(`PreparePanel`)에만 있다(결정 1).
 */
export function g2bRowsOf(notices: ProcurementNotice[], unifiedById: Map<string, UnifiedOpportunity>, dropUnlisted: boolean): SourceRow[] {
  const rows: SourceRow[] = notices.map((notice) => ({ kind: "g2b" as const, id: notice.id, notice, unified: unifiedById.get(notice.id) ?? null }));
  return dropUnlisted ? rows.filter((row) => row.unified !== null) : rows;
}

export function bizinfoRowsOf(items: SupportProgramView[], unifiedById: Map<string, UnifiedOpportunity>): SourceRow[] {
  return items.map((view) => ({ kind: "bizinfo" as const, id: view.program.id, view, unified: unifiedById.get(view.program.id) ?? null }));
}

export function parseMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * 정렬용 마감/신청 종료 시각. 통합 목록이 없으면 원본 필드로 대체한다.
 *
 * 기업마당 apply_end 는 날짜만(YYYY-MM-DD) 오므로 normalizeApplyEnd 로 23:59 KST 를 붙인다.
 * 그러지 않으면 Date.parse 가 UTC 자정(=KST 09:00)으로 읽어, 통합 목록이 준 datetime 과
 * 날짜만 문자열이 한 정렬 안에 섞이면서 마감 당일 건의 순서가 어긋난다.
 */
export function sortDeadline(row: Row): string | null {
  if (row.kind === "g2b") return row.notice.deadline_at;
  if (row.kind === "manual") return row.unified.deadline ?? null;
  return row.unified?.deadline ?? normalizeApplyEnd(row.view.program.apply_end);
}

/** 화면 표시용 마감 시각(ISO). 없으면 원문 문구를 대신 보여준다. */
export function displayDeadline(row: Row): string | null {
  return row.kind === "g2b" ? row.notice.deadline_at : row.unified?.deadline ?? null;
}

export function rowRegisteredAt(row: Row): string | null {
  if (row.kind === "manual") return row.unified.published_at ?? null;
  if (row.kind === "bizinfo") return row.view.program.created_at;
  // 10-31 최종 점검 B — 나라장터는 통합 목록 값(43차 M2 · 변경공고는 원공고 게시일 · 모르면 null = 새 공고로 세지 않음 · 띠와 같은 함수).
  // `/api/procurements` 의 게시일은 변경 게시일이라 변경공고가 「최근 3일 새 공고」에 섰다. 통합 목록이 없을 때(옛 스냅샷 · 못 받음)만 그 값.
  const m2 = row.unified?.published_at;
  return m2 !== undefined ? m2 : row.notice.published_at;
}

/** 실제 마감 — 등록마감이 더 이르면 그쪽(D-day · 「마감 여유순」이 같은 값을 쓴다). */
export function rowEffectiveDeadline(row: Row): string | null {
  return effectiveDeadline(pairOf(row.unified ?? {}, displayDeadline(row) ?? sortDeadline(row)));
}

/**
 * 마감 여부. 통합 목록에 있으면 backend 판정(`closed`)을 그대로 쓰고,
 * 없으면(=통합 목록이 마감 건을 제외했거나 조회에 실패했을 때) 마감일로만 판단한다.
 */
export function isClosedRow(row: Row, nowMs: number | null): boolean {
  if (row.unified) return row.unified.closed;
  if (nowMs === null) return false;
  const ms = parseMs(sortDeadline(row));
  return ms === null ? false : ms < nowMs;
}

/**
 * 기본 노출 여부 — 마감 · 불가 · 관련 낮음(검색어는 뺀 공통 조건). 사업기회 목록 · 출처별 건수 · 대시보드 통계가 같은 술어다.
 */
export function rowShown(row: Row, includeClosed: boolean, nowMs: number | null, includeBlocked: boolean = true, includeUnrelated: boolean = true): boolean {
  if (!includeClosed && isClosedRow(row, nowMs)) return false;
  // 참가·신청할 수 없다고 판정한 건은 기본으로 숨긴다 (0921 §4-C-2 · §4-D-1).
  // **지우는 것이 아니다** — 「불가 포함」을 켜면 그대로 돌아온다. 판정이 아예 없는 행
  // (통합 목록에 없는 건)은 숨기지 않는다 — 「모른다」는 「불가」가 아니다.
  if (!includeBlocked && row.unified?.eligibility_gate === "FAIL") return false;
  // 회사와 관련이 낮다고 판정한 지원사업도 기본으로 접는다 (0922 §4-C-2 · ISSUE-085).
  // 기업마당 1,582건에는 식품·관광·융자처럼 상관없는 사업이 섞여 있고, 그대로 두면
  // 「확인 필요 603건」이 마감 순으로 아침 화면을 채운다. 같은 규칙으로 되돌릴 수 있다.
  if (!includeUnrelated && row.unified?.relevance_note) return false;
  return true;
}

// ---------------------------------------------------------------------------
// 띠 조건 — 「오늘 달라진 것」(0919 §4-B-1) · 대시보드 통계(2.1.0)가 사업기회로 넘기는 조건
// ---------------------------------------------------------------------------

/**
 * 띠가 넘기는 조건. 다른 조건처럼 주소에 남긴다(`new` · `changed` · `pending` · `due` · `pass`). 새로고침·뒤로 가기·링크 공유에서
 * 살아남아야 하고, 사업기회의 주소 쓰기 effect 가 주소를 매번 처음부터 다시 만들기 때문에 거기서 같이 옮겨 적지 않으면
 * 들어오자마자 조건이 지워진다.
 *
 * 새 공고 · 마감 · 가능은 나라장터와 기업마당에 걸린다(2.1.0 — 대시보드가 출처마다 센다). 변경 · 결정 대기는 나라장터 공고만의
 * 기록이라 나라장터에만 걸린다. 직접 넣은 공고는 어느 조건에도 들지 않는다. 오늘 띠(나라장터만 세는 응답)의 링크는 `src=g2b` 를 단다.
 */
export interface DigestConditions {
  /** 게시 · 등록이 최근 n일(응답의 `new_days`) 안. */
  onlyNew: boolean;
  /** 게시 · 등록이 오늘(KST 달력일 · `new=today`). */
  newToday: boolean;
  onlyChanged: boolean;
  onlyPending: boolean;
  /** 마감이 n일 이내인 것만. 0 이면 끄기. */
  dueWithin: number;
  /** 실제 마감이 오늘(KST)이고 아직 지나지 않은 것(`due=today`). */
  dueToday: boolean;
  /** 참가 · 신청 「가능」 판정만(`pass=1`). */
  onlyPass: boolean;
}

export const NO_DIGEST: DigestConditions = { onlyNew: false, newToday: false, onlyChanged: false, onlyPending: false, dueWithin: 0, dueToday: false, onlyPass: false };

export function digestOn(d: DigestConditions): boolean {
  return d.onlyNew || d.newToday || d.onlyChanged || d.onlyPending || d.dueWithin > 0 || d.dueToday || d.onlyPass;
}

/**
 * 띠 조건에 맞는 행인가 (0919 §4-B-1).
 *
 * 조건이 하나도 없으면 전부 통과한다. 여러 개면 **모두** 만족해야 한다.
 *
 * id 목록(변경·결정 대기)을 아직 못 받았으면 그 조건만 **건너뛴다.** 조용히 빈 목록을
 * 보여주면 담당자는 「변경된 공고가 없다」로 읽는데, 사실은 「물어보지 못했다」이다.
 * 대신 목록 위에 그 사정을 적는다.
 */
export function rowMatchesDigest(
  row: Row,
  d: DigestConditions,
  nowMs: number | null,
  changedIds: Set<string> | null,
  pendingIds: Set<string> | null,
  /** 「새 공고」로 볼 기간(일). 응답에서 온다. null 이면 그 조건만 **건너뛴다.** */
  newDays: number | null,
): boolean {
  if (!digestOn(d)) return true;
  if (row.kind === "manual") return false;
  if ((d.onlyChanged || d.onlyPending) && row.kind !== "g2b") return false;
  if (d.onlyPass && row.unified?.eligibility_gate !== "PASS") return false;
  if (d.onlyNew && newDays !== null) {
    // 기간을 아직 모르면 이 조건은 건너뛴다. 임의의 3 으로 걸러 놓고 「새 공고 0건」이라고
    // 적으면, 사실은 「물어보지 못했다」인데 담당자는 「없다」로 읽는다 (바로 위 주석과 같은 규칙).
    const ms = parseMs(rowRegisteredAt(row));
    if (nowMs === null || ms === null || nowMs - ms > newDays * 86_400_000) return false;
  }
  if (d.newToday && (nowMs === null || daysOverdue(rowRegisteredAt(row), nowMs) !== 0)) return false;
  if (d.dueWithin > 0 || d.dueToday) {
    // 화면에 찍히는 D-n 과 **같은 함수**로 센다. 예전에는 여기만 밀리초를 직접 곱해서
    // (KST 달력일이 아니라 흐른 시간) 「3일 내 마감」에 D-3 이 빠지는 일이 있었다.
    // 43차 NUM-02 — 띠와 같은 실제 마감(등록 · 공고문 일정이 더 이르면 그쪽)
    const days = nowMs === null ? null : daysUntil(rowEffectiveDeadline(row), nowMs);
    if (days === null || days < 0 || days > (d.dueToday ? 0 : d.dueWithin)) return false;
  }
  if (d.onlyChanged && changedIds !== null && !changedIds.has(row.id)) return false;
  if (d.onlyPending && pendingIds !== null && !pendingIds.has(row.id)) return false;
  return true;
}

// ---------------------------------------------------------------------------
// 대시보드 통계 (2.1.0) — 출처 하나의 「지금 검토할 사업」과 그 안의 가능 · 새 공고 · 마감
// ---------------------------------------------------------------------------

/** 대시보드 「마감」의 기간 — 오늘 띠(`due_days`)와 같은 7일. */
export const OVERVIEW_DUE_DAYS = 7;

export interface OverviewCounts {
  /** 지금 검토할 사업 — 마감 · 참가 불가 · 관련 낮음을 뺀 수(사업기회 기본 목록 그 출처 탭과 같은 수). */
  review: number;
  pass: number;
  newToday: number;
  /** 기간(`new_days`)을 모르면 null — 지어 세지 않는다. */
  newRecent: number | null;
  dueToday: number;
  dueWeek: number;
}

/**
 * 한 출처의 행으로 센다. 모든 숫자는 「지금 검토할 사업」 안에서 센다 — 사업기회에 같은 조건(`src` + 띠 조건)을 걸면 같은 건수가 나온다.
 */
export function overviewCounts(rows: SourceRow[], nowMs: number, newDays: number | null): OverviewCounts {
  const shown = rows.filter((row) => rowShown(row, false, nowMs, false, false));
  const count = (only: Partial<DigestConditions>) => shown.filter((row) => rowMatchesDigest(row, { ...NO_DIGEST, ...only }, nowMs, null, null, newDays)).length;
  return {
    review: shown.length,
    pass: count({ onlyPass: true }),
    newToday: count({ newToday: true }),
    newRecent: newDays === null ? null : count({ onlyNew: true }),
    dueToday: count({ dueToday: true }),
    dueWeek: count({ dueWithin: OVERVIEW_DUE_DAYS }),
  };
}
