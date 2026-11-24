/**
 * 사업기회 「전체」 탭 — 출처별 순위를 번갈아 보인다 (39차 D22 · CLAUDE.md §12 「순위는 갈래 안에서만」).
 *
 * 나라장터 1 · 기업마당 1 · (직접 넣음 1) · 나라장터 2 … — 각 행의 「n위」는 출처 안 순위 그대로다. 한 축에 섞어 하나의 1위를
 * 만들지 않는다(실무순은 접수방식 · 시간 등급 규칙 때문에 첫 화면 10행이 모두 기업마당이었다 · recheck31).
 * 번갈아 세우는 것은 **같은 칸끼리**다 — 살아 있는 것 → (실무순) 비추천 → 마감 · 불가. 한 출처의 뒤쪽이 다른 출처의 앞쪽 사이에
 * 끼지 않는다. 서버 `opportunity_service.interleave_sources` 와 같은 규칙이다(내려받은 파일과 화면 순서가 같다).
 */

export interface InterleaveItem {
  source: string;
  closed: boolean;
  blocked: boolean;
  /** 실무순의 「비추천」 칸인가(점수순에서는 쓰지 않는다). */
  notRecommended: boolean;
}

/** 출처를 세우는 차례 — 서버 `SOURCE_TYPES` 와 같다. */
export const SOURCE_ORDER = ["g2b", "bizinfo", "manual"] as const;

function holdClass(item: InterleaveItem, practical: boolean): number {
  if (item.closed || item.blocked) return 2;
  return practical && item.notRecommended ? 1 : 0;
}

/** `rows` 는 이미 정렬된 목록(출처마다 그 순서를 지킨다). `practical` 이면 비추천을 따로 한 칸으로 둔다. */
export function interleaveSources<T>(rows: readonly T[], view: (row: T) => InterleaveItem, practical: boolean): T[] {
  const out: T[] = [];
  for (const cls of [0, 1, 2]) {
    const lanes = SOURCE_ORDER.map((source) => rows.filter((row) => view(row).source === source && holdClass(view(row), practical) === cls));
    const other = rows.filter((row) => !(SOURCE_ORDER as readonly string[]).includes(view(row).source) && holdClass(view(row), practical) === cls);
    const longest = Math.max(0, ...lanes.map((lane) => lane.length));
    for (let index = 0; index < longest; index += 1) {
      for (const lane of lanes) if (index < lane.length) out.push(lane[index]);
    }
    out.push(...other);
  }
  return out;
}
