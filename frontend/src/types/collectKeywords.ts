/**
 * 「찾는 낱말」 응답 (2.0.7 · 백엔드 `GET · POST /api/collect-keywords`) — 나라장터 공고명 검색 낱말 = 기본(고칠 수 없음) + 추가(이 서버 전체에 하나).
 */

export interface CollectKeywordEntry {
  word: string;
  /** 더한 사람 아이디 — 화면에는 `added_by_name` 을 쓴다 */
  added_by: string;
  added_by_name: string;
  added_at: string;
}

export interface CollectKeywordsState {
  /** 기본 낱말(서버 `opportunity_filter.COLLECT_KEYWORDS`) — 화면에서 고칠 수 없다 */
  base: string[];
  extra: CollectKeywordEntry[];
  max_extra: number;
  /** 오늘(KST) 바로 찾기 횟수 · 하루 상한 */
  searches_today: number;
  searches_limit: number;
  /** 이 서버가 바로 찾기를 할 수 있는가(KEYWORD_SEARCH_LIVE 또는 G2B_LIVE_FETCH) — 꺼져 있으면 낱말 저장만 된다 */
  search_live: boolean;
  /** 목록을 마지막으로 바꾼 시각 — 저장할 때 `expected_updated_at` 으로 돌려보낸다(그사이 남이 바꿨으면 409) */
  updated_at: string | null;
}

export interface KeywordSearchResult {
  word: string;
  found: number;
  new_notices: number;
  candidates: number;
  /** 본업 낱말이 없어 「관련 낮음」으로 접힌 수 */
  low: number;
  /** 호출 상한에서 다 받지 못했는가(7일 창마다 첫 쪽 + 2쪽 · 2.8.1) */
  truncated: boolean;
  /** 받지 못한 기간(창) 호출 수 — 옛 응답에는 없다 */
  failed_calls?: number;
  calls: number;
  searched_at: string;
}

/** 더하기 · 다시 찾기 응답 — 저장은 늘 먼저 되고, 바로 찾기를 못 했으면 `search` 는 null 이고 `search_error` 에 사유(할 일 포함)가 온다. */
export interface CollectKeywordsResponse {
  state: CollectKeywordsState;
  search: KeywordSearchResult | null;
  search_error: string | null;
}
