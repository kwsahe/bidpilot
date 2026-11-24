/**
 * 공고 선택 드롭다운에 보여줄 항목을 추린다.
 *
 * 후보가 100건을 넘으면 드롭다운이 너무 길어져 시연 중에 원하는 공고를 찾기 어렵다.
 * 순위 상위 N개만 남기되, **지금 선택된 공고는 순위가 밖이어도 반드시 남긴다**
 * (안 그러면 select가 선택 값을 잃고 첫 항목으로 튄다).
 *
 * 전체 목록은 /opportunities 표에서 본다.
 */

/** 드롭다운이 다루는 최소 형태. Cosmos와 와이어프레임이 각자의 타입으로 넘긴다. */
export interface PickerOption {
  id: string;
  rank?: number | null;
}

/** 드롭다운에 기본으로 보여줄 실공고 수. */
export const PICKER_LIMIT = 20;

export function limitNoticeOptions<T extends PickerOption>(
  options: T[],
  selectedId: string,
  limit: number = PICKER_LIMIT,
): T[] {
  if (options.length <= limit) return options;

  const kept = options.slice(0, limit);
  if (kept.some((option) => option.id === selectedId)) return kept;

  const selected = options.find((option) => option.id === selectedId);
  return selected ? [...kept, selected] : kept;
}

/** "106건 중 20건 표시" 같은 안내 문구. 다 보여주고 있으면 null. */
export function pickerHiddenLabel(
  total: number,
  shown: number,
): string | null {
  if (shown >= total) return null;
  return `${total}건 중 상위 ${shown}건 표시 · 전체는 공고 목록에서`;
}
