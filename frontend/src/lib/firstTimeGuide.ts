/**
 * 처음 하는 사람 안내의 계산 (31차 §3-B) — 글은 `lib/terms`, 여기는 고르는 규칙만.
 *
 * - 회사자료 「준비 상태」: 기본 줄 일곱 + 이미 저장된 줄을 한 목록으로 · 저장할 목록 만들기(「모름 + 메모 없음」 기본 줄은 안 보냄)
 * - 유효기간: 30일 안 만료 · 지난 날짜
 * - 마감 며칠 전 할 일(나라장터): `URGENCY_DAYS` · `urgencyTierOf` 그대로
 */

import { daysUntil, effectiveDeadline, registrationClosesFirst, urgencyTierOf, type DeadlinePair } from "@/lib/deadline";
import { BID_DEADLINE_REGISTRATION_FIRST, BID_DEADLINE_STEPS, EXPIRED_HEAD, EXPIRING_SOON_HEAD, READINESS_ROWS } from "@/lib/terms";
import type { DeliveryCapacityCredential, SmeGrade } from "@/types/capability";

/** 준비 상태 한 줄 — 화면 칸. `saved` 는 이미 저장된 줄(이름 · 출처를 그대로 지킨다). */
export interface ReadinessRow {
  label: string;
  held: boolean | null;
  note: string;
  validUntil: string;
  /** 중소기업(소상공인) 확인서 줄만 쓴다(10-10) — 다른 줄은 늘 null. */
  grade: SmeGrade | null;
  saved: DeliveryCapacityCredential | null;
}

/** 이름 맞추기 — 띄어쓰기 · 괄호 안을 뺀다(「중소기업확인서」 = 「중소기업(소상공인) 확인서」). */
function nameKey(name: string): string {
  return name.replace(/\([^)]*\)/g, "").replace(/\s+/g, "");
}

/** 판정에 쓰는 준비 상태 줄인가 — 중소기업(소상공인) 확인서(백엔드 `eligibility_engine._SME_CERT_KEYS` 와 같은 이름 규칙 · 10-10). */
export function isSmeRow(label: string): boolean {
  return ["중소기업확인서", "중소기업·소상공인확인서", "중소기업소상공인확인서"].includes(nameKey(label));
}

/** 기본 줄 일곱(저장된 같은 이름 줄의 값으로) + 기본 줄에 없는 저장 줄. */
export function readinessRows(saved: readonly DeliveryCapacityCredential[]): ReadinessRow[] {
  const used = new Set<DeliveryCapacityCredential>();
  const fromSaved = (label: string, row: DeliveryCapacityCredential | null): ReadinessRow => ({
    label,
    held: row?.held ?? null,
    note: row?.note ?? "",
    validUntil: row?.valid_until ?? "",
    grade: isSmeRow(label) ? (row?.grade ?? null) : null,
    saved: row,
  });
  const rows = READINESS_ROWS.map((label) => {
    const match = saved.find((row) => !used.has(row) && nameKey(row.name) === nameKey(label)) ?? null;
    if (match) used.add(match);
    return fromSaved(label, match);
  });
  return [...rows, ...saved.filter((row) => !used.has(row)).map((row) => fromSaved(row.name, row))];
}

/**
 * 저장할 `credentials` — 이미 저장된 줄은 이름 · 출처를 지키고 값만 바꾼다. 새 기본 줄은 「모름 + 메모 없음 + 날짜 없음」이면
 * 보내지 않는다(빈 기본 줄로 파일을 채우지 않는다).
 */
export function readinessToSave(rows: readonly ReadinessRow[], source: string): DeliveryCapacityCredential[] {
  const out: DeliveryCapacityCredential[] = [];
  for (const row of rows) {
    const note = row.note.trim() || null;
    const validUntil = row.validUntil.trim() || null;
    if (!row.saved && row.held === null && !note && !validUntil && !row.grade) continue;
    // 손대지 않은 저장 줄은 출처를 그대로 둔다 — 저장할 때마다 모든 줄의 출처가 지금 사용자로 바뀌었다(32차 R31-11)
    // 구분은 「있음」일 때만 뜻이 있다 — 없음 · 모름으로 바꾸면 지운다(옛 구분이 판정에 남지 않게)
    const grade = row.held === true && isSmeRow(row.label) ? row.grade : null;
    const touched =
      !row.saved ||
      row.saved.held !== row.held ||
      (row.saved.note ?? null) !== note ||
      (row.saved.valid_until ?? null) !== validUntil ||
      (row.saved.grade ?? null) !== grade;
    out.push({
      name: row.saved?.name ?? row.label,
      held: row.held,
      note,
      source: touched ? source : (row.saved?.source ?? null),
      valid_until: validUntil,
      grade,
    });
  }
  return out;
}

/** 유효기간 상태 — 지난 날짜는 「만료됨」, `withinDays` 안이면 「곧 만료」. 날짜는 그날 끝(KST)까지 유효로 본다. */
export function validityOf(validUntil: string | null | undefined, nowMs: number, withinDays = 30): "expired" | "soon" | null {
  if (!validUntil || !/^\d{4}-\d{2}-\d{2}$/.test(validUntil)) return null;
  const days = daysUntil(`${validUntil}T23:59:59+09:00`, nowMs);
  if (days === null) return null;
  if (days < 0) return "expired";
  return days <= withinDays ? "soon" : null;
}

/** 「이번 주 할 일」에 올릴 유효기간 줄 — 지난 것 먼저, 그다음 가까운 날짜 순. */
export function expiringCredentials(
  credentials: readonly DeliveryCapacityCredential[],
  nowMs: number,
  withinDays = 30,
): Array<{ name: string; validUntil: string; state: "expired" | "soon" }> {
  return credentials
    .map((row) => ({ name: row.name, validUntil: row.valid_until ?? "", state: validityOf(row.valid_until, nowMs, withinDays) }))
    .filter((row): row is { name: string; validUntil: string; state: "expired" | "soon" } => row.state !== null)
    .sort((a, b) => (a.state === b.state ? a.validUntil.localeCompare(b.validUntil) : a.state === "expired" ? -1 : 1));
}

/**
 * 곧 만료 · 만료됨 한 줄 — 상태마다 머리말을 따로 단다(「만료됨: … · 곧 만료: …」). 첫 서류 상태 하나로 머리를 정하면
 * 아직 유효한 서류가 「만료됨」 뒤에 섞여 만료된 것처럼 읽혔다(32차 마지막 검토).
 */
export function expiringLine(rows: ReadonlyArray<{ name: string; validUntil: string; state: "expired" | "soon" }>): string {
  return (["expired", "soon"] as const)
    .map((state) => {
      const names = rows.filter((row) => row.state === state).map((row) => `${row.name} ${row.validUntil}`);
      return names.length > 0 ? `${state === "expired" ? EXPIRED_HEAD : EXPIRING_SOON_HEAD}: ${names.join(" · ")}` : null;
    })
    .filter(Boolean)
    .join(" · ");
}

/** 접힌 띠 머리용 수 — 「만료됨 1 · 곧 만료 2」(0 은 뺀다). 한 숫자로 합치면 몇 개가 이미 지났는지 몰랐다(33차 R32-11). */
export function expiringCounts(rows: ReadonlyArray<{ state: "expired" | "soon" }>): string {
  return (["expired", "soon"] as const)
    .map((state) => [state === "expired" ? EXPIRED_HEAD : EXPIRING_SOON_HEAD, rows.filter((row) => row.state === state).length] as const)
    .filter(([, count]) => count > 0)
    .map(([head, count]) => `${head} ${count}`)
    .join(" · ");
}

/** 마감 며칠 전 할 일(나라장터 1단계 한 줄). 마감이 지났거나 시계가 없으면 null. 등록마감이 먼저면 그 말을 앞세운다. */
export function bidDeadlineAdvice(pair: DeadlinePair, nowMs: number | null): string | null {
  if (nowMs === null) return null;
  const days = daysUntil(effectiveDeadline(pair), nowMs);
  if (days === null) return null; // 마감일 없음 — 줄을 내지 않는다
  const tier = urgencyTierOf(days, false);
  if (tier === "closed") return null;
  const line = tier === "urgent" ? BID_DEADLINE_STEPS.urgent : tier === "soon" ? BID_DEADLINE_STEPS.soon : BID_DEADLINE_STEPS.early;
  return registrationClosesFirst(pair) ? `${BID_DEADLINE_REGISTRATION_FIRST} ${line}` : line;
}
