import type { ActionItem } from "@/types/gate";

/** 같은 할 일(제목 끝 「— REQ-083」만 다름)을 한 줄로 묶는다(45차 M22 — 41건 중 21건이 같은 세 줄이었다). 순서는 처음 나온 자리. */
const ACTION_TAIL = /\s—\s([A-Z]{2,4}-\d+)$/;

export function groupActions<T extends Pick<ActionItem, "title">>(items: T[]): Array<{ base: string; items: T[]; codes: string[] }> {
  const groups = new Map<string, { base: string; items: T[]; codes: string[] }>();
  for (const item of items) {
    const tail = ACTION_TAIL.exec(item.title);
    const base = tail ? item.title.slice(0, tail.index) : item.title;
    const group = groups.get(base) ?? { base, items: [], codes: [] };
    group.items.push(item);
    if (tail) group.codes.push(tail[1]);
    groups.set(base, group);
  }
  return [...groups.values()];
}
