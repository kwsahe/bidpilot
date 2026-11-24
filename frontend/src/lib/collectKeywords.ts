/**
 * 「찾는 낱말」 (2.0.7 · 대표 10-27 「낱말 추가를 대시보드에서 할 수 있게 · 그리고 바로 재검색」).
 *
 * 나라장터 공고명 검색 낱말 = 기본 낱말(고칠 수 없음) + 추가 낱말(이 서버 전체에 하나 · 편집자 이상이 더하고 지움).
 * 「더하고 바로 찾기」는 더한 낱말 **하나만** 나라장터 입찰에서 찾는다 — 호출 상한(7일 창마다 첫 쪽 + 2쪽) · 하루 횟수 · 아침 받기와 같은 잠금은 서버가 지킨다.
 * 여기는 화면 판단과 문장만 둔다(잠김 이유 · 결과 한 줄 · 입력 안내). **낱말 규칙의 기준은 서버**이고 입력 안내는 미리 알려 주는 사본이다 —
 * 흔한 낱말 막기 목록은 서버 한 곳에만 둔다(사본을 두면 두 곳이 갈린다 · 걸리면 서버 사유가 그대로 보인다).
 */

import type { CollectKeywordsState, KeywordSearchResult } from "@/types/collectKeywords";
import type { CollectState } from "@/types/opportunity";
import { VIEWER_LOCK_LABEL } from "@/lib/viewerLock";

/**
 * 다음에 이 낱말로 찾는 때 — 「…부터」까지 (서버 `auto_collect.collect_state` · `collectTerm` 과 같은 갈림).
 * 자동 받기가 꺼진 곳(꺼 둠 · 키트)에는 아침 받기가 없다 — 「내일 아침」이라 하면 그 낱말로는 영영 찾지 않는다.
 * 상태를 아직 모르면(읽는 중 · 못 읽음) 때를 단정하지 않는다. 노트북은 켤 때 받기라 시각은 적지 않는다.
 */
export function keywordNextCollect(collect: CollectState | null | undefined): string {
  if (!collect) return "다음 목록 받기부터";
  if (collect.kind === "off" || collect.kind === "none" || !collect.text) return "자동 받기가 꺼져 있어 「지금 받기」를 돌릴 때부터";
  return "다음 자동 받기부터";
}

/** 서버 문이 꺼져 있다 — 낱말은 저장되고 다음 받기부터 찾는다. */
export function keywordSearchOffReason(collect: CollectState | null | undefined): string {
  return `이 서버에서는 바로 찾기가 꺼져 있습니다 — ${keywordNextCollect(collect)} 이 낱말로 찾습니다`;
}

export function keywordSearchLimitReason(limit: number, collect: CollectState | null | undefined): string {
  return `오늘 바로 찾기 ${limit}번을 다 썼습니다 — ${keywordNextCollect(collect)} 찾습니다`;
}

/**
 * 「바로 찾기」가 잠긴 이유 — 열람자 · 문 꺼짐 · 오늘 횟수를 다 씀. 열렸으면 null.
 * 낱말 더하기는 열람자만 막힌다(문 꺼짐 · 횟수 다 씀이면 저장만 된다).
 */
export function keywordSearchLock(
  state: Pick<CollectKeywordsState, "search_live" | "searches_today" | "searches_limit">,
  viewer: boolean,
  collect: CollectState | null | undefined = null,
): string | null {
  if (viewer) return VIEWER_LOCK_LABEL;
  if (!state.search_live) return keywordSearchOffReason(collect);
  if (state.searches_today >= state.searches_limit) return keywordSearchLimitReason(state.searches_limit, collect);
  return null;
}

/** 「찾는 낱말」 바로 찾기 문이 켜진 서버의 자료 상태 풀이 끝 — 「화면에서 바로 받지는 않습니다」와 어긋나지 않게(frontend-3). */
export const KEYWORD_SEARCH_EXCEPTION = "「찾는 낱말」의 바로 찾기(낱말 하나씩 · 나라장터 입찰만)는 예외입니다.";

/**
 * 결과 한 줄 — 「「메타버스」로 7건 찾음 · 새 공고 5 · 후보 2 · 관련 낮음 3(접힘)」 · 상한에서 잘렸으면 「너무 흔한 낱말이라 일부만 받음」 ·
 * 일부 기간을 못 받았으면 그 말도(2.8.1 — 30일을 7일 창으로 나눠 받아 받은 수가 300 을 넘을 수 있어 숫자를 박지 않는다).
 */
export function keywordSearchSummary(result: KeywordSearchResult, collect: CollectState | null | undefined = null): string {
  if (result.found === 0) return `「${result.word}」로 찾은 공고가 없습니다 — ${keywordNextCollect(collect)} 이 낱말로 다시 찾습니다`;
  const parts = [
    `「${result.word}」로 ${result.found}건 찾음`,
    `새 공고 ${result.new_notices}`,
    `후보 ${result.candidates}`,
    `관련 낮음 ${result.low}${result.low > 0 ? "(접힘)" : ""}`,
  ];
  if (result.truncated) parts.push("너무 흔한 낱말이라 일부만 받음 — 나머지는 다음 자동 받기에서");
  if ((result.failed_calls ?? 0) > 0) parts.push(`일부 기간(${result.failed_calls}회)을 받지 못했습니다 — 다음 받기에서 다시`);
  return parts.join(" · ");
}

/** 찾은 것이 모두 「관련 낮음」인가 — 기본 목록에서는 하나도 안 보이니 접힌 것을 함께 보는 길을 준다. */
export function keywordAllLow(result: KeywordSearchResult): boolean {
  return result.candidates === 0 && result.low > 0;
}

/**
 * 「사업기회에서 결과 보기 →」 주소 — 검색칸(`q`)에 그 낱말 · 나라장터 탭 · 모두 관련 낮음이면 접힌 것도 함께(`unrelated=1`).
 * 참가 불가 · 실제 마감이 지난 공고도 「n건 찾음」에 들므로 함께 켠다(`blocked` · `closed` — 기본으로 숨으면 찾은 수보다 적게 보였다 · frontend-1).
 */
export function keywordResultHref(result: KeywordSearchResult): string {
  const params = new URLSearchParams({ q: result.word, src: "g2b", blocked: "1", closed: "1" });
  if (keywordAllLow(result)) params.set("unrelated", "1");
  return `/opportunities?${params.toString()}`;
}

/** 서버와 같은 다듬기 — NFC · 앞뒤 공백 제거 · 연속 공백 하나로. */
export function normalizeKeyword(raw: string): string {
  return raw.normalize("NFC").trim().replace(/\s+/g, " ");
}

/** 같은 낱말 비교 — 띄어쓰기 · 대소문자 무시(공고명 검색이 띄어쓰기를 무시한다). */
const sameKey = (word: string) => normalizeKeyword(word).replace(/ /g, "").toLowerCase();

/** 한글(자모 포함) · 영문 · 숫자 · 띄어쓰기 · 점 · 하이픈. 서버보다 좁으면 안 된다(맞는 낱말을 화면이 막게 되므로). */
const ALLOWED_CHARS = /^[0-9A-Za-zㄱ-ㆎ가-힣 .-]+$/;

/** 추가 낱말이 다 찼다 — 서버 400 문장과 같다. */
export function keywordFullReason(max: number): string {
  return `추가 낱말은 ${max}개까지입니다 — 하나를 지운 뒤 더하세요`;
}

/**
 * 입력 안내 — 더하기 전에 미리 알린다(기준은 서버 · 서버 사유가 이긴다). 빈칸이거나 문제가 없으면 null.
 * 순서: 꽉 참 → 길이 → 글자 → 이미 있음.
 */
export function keywordInputProblem(raw: string, state: Pick<CollectKeywordsState, "base" | "extra" | "max_extra">): string | null {
  const word = normalizeKeyword(raw);
  if (!word) return null;
  if (state.extra.length >= state.max_extra) return keywordFullReason(state.max_extra);
  if (word.length < 2) return "두 글자 이상 적으세요";
  if (word.length > 20) return "20자까지 적을 수 있습니다";
  if (!ALLOWED_CHARS.test(word)) return "한글 · 영문 · 숫자 · 띄어쓰기 · 점(.) · 하이픈(-)만 쓸 수 있습니다";
  const key = sameKey(word);
  const same = [...state.base, ...state.extra.map((entry) => entry.word)].find((existing) => sameKey(existing) === key);
  if (same) return `이미 있는 낱말입니다(「${same}」) — 띄어쓰기 · 대소문자만 다르면 같은 낱말로 봅니다`;
  return null;
}
