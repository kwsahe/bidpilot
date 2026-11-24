/**
 * 사업기회 「재수집」 단추 (20차 §4-G · 담당자 「사업기회에 재수집 버튼 추가. 나라장터, 기업마당으로.」).
 *
 * 단추는 **있되 시연 고정 모드에서는 이유를 말하며 잠긴다** — 시연 자료를 지키는 규칙은 그대로다.
 * 잠김 판단은 `/health` 의 출처별 문(`g2b_live` · `bizinfo_live`)이다. 값이 없으면(옛 백엔드 · 스냅샷 배포)
 * 「모른다」이고, 모를 때는 잠근다 — 눌러서 시연 캐시를 바꾸는 쪽이 더 나쁘다.
 */

export type RecollectSource = "g2b" | "bizinfo";

export const RECOLLECT_LABELS: Record<RecollectSource, string> = { g2b: "나라장터", bizinfo: "기업마당" };

/** 「전체」 — 「찾는 낱말」 바로 찾기(낱말 하나)는 따로 열릴 수 있다(2.0.7 · 같은 도구모음에서 어긋나 보였다). */
export const RECOLLECT_LOCKED_REASON = "전체 새로 받기는 꺼져 있습니다(저장본만 씀)";
/** 서버 상태를 받지 못했다(연결 끊김 · 옛 백엔드) — 「시연 고정」이라 단정하지 않는다 (OPP-18). 잠그는 것은 같다. */
export const RECOLLECT_UNKNOWN_REASON = "서버 상태를 확인하지 못해 새로 받기를 잠갔습니다 — 잠시 뒤 다시 열어 보세요";

export interface RecollectResult {
  source: RecollectSource;
  before: { count: number; fetched_at: string | null };
  after: { count: number; fetched_at: string | null };
  new: number;
  gone: number;
  qualification: { days_fetched: number; calls: number; note: string | null } | null;
  clauses_missing: number;
  clauses_note: string | null;
  took_ms: number;
}

/** 이 출처의 재수집 단추가 잠겼으면 그 이유, 열렸으면 null. */
export function recollectLock(
  health: { g2b_live?: boolean; bizinfo_live?: boolean } | null | undefined,
  source: RecollectSource,
): string | null {
  const live = source === "g2b" ? health?.g2b_live : health?.bizinfo_live;
  if (live === true) return null;
  return live === false ? RECOLLECT_LOCKED_REASON : RECOLLECT_UNKNOWN_REASON;
}

/** 결과 한 줄 — 「나라장터 185 → 190 · 새 공고 5 · 빠짐 3 · 참가자격 조항 없는 새 공고 5 · 자격 표 2일 받음」. */
export function recollectSummary(result: RecollectResult): string {
  const parts = [
    `${RECOLLECT_LABELS[result.source]} ${result.before.count} → ${result.after.count}`,
    `새 공고 ${result.new}`,
    `빠짐 ${result.gone}`,
  ];
  if (result.source === "g2b") {
    parts.push(`참가자격 조항 없는 새 공고 ${result.clauses_missing}`);
    if (result.qualification) parts.push(`자격 표 ${result.qualification.days_fetched}일 받음`);
  }
  return parts.join(" · ");
}
