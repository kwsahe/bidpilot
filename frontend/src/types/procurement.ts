/**
 * backend `GET /api/procurements` 응답 (docs/real_data_migration.md §1 확정 형태).
 *
 * 나라장터 실호출 결과이며, 실패 시 source="cached"로 캐시가 내려온다.
 * 필드명은 g2b_mapper.py / opportunity_filter.py 에 실제로 존재하는 것만 쓴다.
 */

import type { NoticeWork } from "@/types/capability";

export interface HealthResponse {
  status: string;
  service: string;
  g2b_api_configured: boolean;
  /**
   * OpenAI 임베딩을 **부를 수 있는가** (EMBEDDING_LIVE · 15차 ISSUE-129).
   * 옛 스냅샷·옛 백엔드에는 없으므로 undefined 를 「모른다」로 다룬다 — false 로 단정하지 않는다.
   */
  embedding_live?: boolean;
  /** 의미 유사도를 **점수에 쓰는가** (SEMANTIC_FIT). 꺼져 있으면 사업영역 점수가 키워드 값이다. */
  semantic_fit?: boolean;
  /**
   * **완성**(제안서·사업계획서·제출 전 점검)을 AI 로 하는가 (LLM_LIVE · 16차 ISSUE-130).
   *
   * 「AI 초안이 붙는가」는 이 값과 `llm_credit_ok` 가 **둘 다** 참일 때다 — 켜 두어도
   * 크레딧이 없으면 규칙 초안이 나간다. 옛 스냅샷·옛 백엔드에는 없으므로 undefined 는
   * 「모른다」로 다룬다.
   */
  llm_live?: boolean;
  /** 크레딧이 살아 있다고 이미 확인됐는가. 부르지 않고 기록만 읽어 답한다. */
  llm_credit_ok?: boolean;
  /**
   * 출처별 실호출 문 (20차 §4-G). 사업기회 화면의 「나라장터 재수집」「기업마당 재수집」 단추가 이것으로 잠긴다.
   * 옛 백엔드 · 스냅샷 배포에는 없다 — 없으면 「모른다」이고 단추는 잠근다.
   */
  g2b_live?: boolean;
  bizinfo_live?: boolean;
  /** 「찾는 낱말」 바로 찾기 문(2.0.7 · `KEYWORD_SEARCH_LIVE` 또는 `G2B_LIVE_FETCH`). 옛 백엔드에는 없다 — 없으면 꺼짐으로 본다. */
  keyword_search_live?: boolean;
}

/** g2b 실시간 조회 / 캐시 fallback. */
export type ProcurementSource = "g2b" | "cached";

/** opportunity_filter.py 의 키워드 등급. */
export type CandidateTier = "high" | "medium" | "low" | "none";

/** raw_data.attachments 원소 (ntceSpecDocUrl1..10 에서 추출). */
export interface NoticeAttachment {
  name: string;
  url: string;
}

/** 키워드 매칭 판정 근거. 후보를 «걸러낸» 규칙 결과이며, 의미 유사도 점수가 아니다. */
export interface CandidateMatch {
  tier: CandidateTier;
  matched_ai_keywords: string[];
  matched_work_keywords: string[];
  method: string;
}

// ---------------------------------------------------------------------------
// 우리 회사 적합도를 «무엇으로» 쟀는가
// ---------------------------------------------------------------------------

/**
 * 적합도 판정 방식. backend `semantic_matcher.SemanticFit.method` 와 같은 값이다.
 * EMBEDDING = 의미 유사도로 점수를 냈다 · KEYWORD = 재지 못해 키워드 규칙 결과만 있다.
 */
export type FitMethod = "EMBEDDING" | "KEYWORD";

/**
 * 의미 매칭 결과. backend `recommendation.Recommendation.to_dict()` 가 **추가로** 실어 보낸다.
 *
 * 옛 배포 스냅샷에는 없으므로 전부 선택적이다. 값이 없으면 화면은 지금까지의 키워드 규칙
 * 표시를 그대로 쓴다 — 없는 값을 0으로 채우지 않는다 (CLAUDE.md 12조).
 */
export interface SemanticFitFields {
  fit_method?: FitMethod | null;
  /** 「AI 의미 매칭」·「키워드 규칙」. backend `FIT_METHOD_LABELS` 가 단일 출처다 */
  fit_method_label?: string | null;
  /** 0~1. null 이면 «재지 못했다»이며 0점이 아니다 */
  fit_score?: number | null;
  /** 「높음」·「보통」·「낮음」 */
  fit_label?: string | null;
  /** 화면에 그대로 내보내는 한국어 사유 */
  fit_reason?: string | null;
}

/** 화면이 바로 쓰는 형태로 정리한 적합도 판정. */
export interface SemanticFitView {
  /** 0~1. null 이면 재지 못했다 */
  score: number | null;
  label: string | null;
  reason: string | null;
  /** 담당자에게 보여 줄 판정 방식 이름 */
  methodLabel: string;
  /**
   * 의미 유사도로 **실제 점수가 나왔는가**.
   * false 면 키워드 규칙 결과뿐이므로 점수 자리를 바꾸지 않는다.
   */
  measured: boolean;
}

/**
 * 의미 매칭 결과를 여러 후보 자리에서 찾아 준다 (공고 자체 · 추천등급 순).
 *
 * 자리를 하나로 못 박지 않는 이유: 지금은 목록 응답의 추천등급에 실려 오지만, 상세 응답과
 * 통합 목록은 추천등급을 함께 주지 않는다. 아무 데도 없으면 null 이고, 그때 호출자는 지금
 * 화면을 그대로 두면 된다.
 */
export function semanticFitOf(...sources: (SemanticFitFields | null | undefined)[]): SemanticFitView | null {
  for (const source of sources) {
    if (!source) continue;
    const method = source.fit_method ?? null;
    // `??` 를 쓴다 — 0점은 «낮다»는 판정이지 «없다»가 아니므로 떨어뜨리면 안 된다.
    const score = source.fit_score ?? null;
    if (method === null && score === null && !source.fit_reason) continue;
    return {
      score: typeof score === "number" ? score : null,
      label: source.fit_label ?? null,
      reason: source.fit_reason ?? null,
      methodLabel: source.fit_method_label ?? (method === "EMBEDDING" ? "AI 의미 매칭" : "낱말 기준"),
      measured: method === "EMBEDDING" && typeof score === "number",
    };
  }
  return null;
}

export interface ProcurementRawData {
  attachments?: NoticeAttachment[];
  [key: string]: unknown;
}

/** 추천등급. NO_GO는 마감 경과처럼 점수와 무관하게 확정된 상태다. */
export type RecommendationGrade = "A" | "B" | "C" | "D" | "NO_GO";

/** 등급 산정 항목 1개. score가 null이면 목록 단계에서 계산하지 못한 항목이다. */
export interface RecommendationComponent {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  reason: string;
}

/**
 * 공고 1건의 추천등급 (backend recommendation.py).
 * **낙찰확률이 아니라 검토 우선순위다.** CLAUDE.md 12조 가중치를 따르되,
 * 계산한 항목만으로 정규화하고 빠진 항목은 skipped에 남긴다.
 */
export interface Recommendation extends SemanticFitFields {
  grade: RecommendationGrade;
  score: number;
  /** 점수와 무관하게 등급을 확정한 사유 (마감 경과 등). 없으면 null */
  gate_reason: string | null;
  /** 목록 단계에서 계산하지 못한 항목 라벨 */
  skipped: string[];
  components: RecommendationComponent[];
  method: string;
  note: string;
}

export interface ProcurementNotice extends SemanticFitFields {
  id: string;
  notice_no: string;
  title: string;
  agency: string;
  published_at: string;
  deadline_at: string | null;
  budget: number | null;
  region: string | null;
  description: string | null;
  source_url: string | null;
  raw_data: ProcurementRawData;
  /** 목록 응답에만 있다. 데모 시나리오 공고에는 없다. */
  candidate?: CandidateMatch;
  /** 목록 응답에만 있다. 행마다 표시하는 추천등급 (낙찰확률 아님). */
  recommendation?: Recommendation;
  /** 목록 응답에만 있다. 추천 점수 순 검토 우선순위 (1부터). */
  rank?: number | null;
  /** 일의 종류(갈래). 목록 응답에만 있고, 옛 배포 스냅샷에는 없다. */
  work?: NoticeWork;
  /** 같은 공고번호로 묶인 차수(정정·재공고) 개수. 1이면 묶인 것이 없다. */
  revision_count?: number;
  /**
   * 이번 조회 결과에 없어 고정 공고 저장소에서 되살려 붙인 공고인가.
   * 목록 전체의 source 가 "g2b"(실시간)라도 이 공고만은 방금 받아온 것이 아니다.
   * 옛 배포 스냅샷에는 이 필드가 없다.
   */
  pinned?: boolean;
}

export interface ProcurementListResponse {
  source: ProcurementSource;
  g2b_api_configured: boolean;
  /** 조회 시각 (ISO 8601). 캐시면 캐시가 만들어진 시각이다. */
  fetched_at: string;
  /** 필터 이전에 나라장터에서 받아온 전체 공고 수 */
  total_fetched: number;
  /** 후보로 남은 공고 수 (= notices.length) */
  count: number;
  /** 실호출 실패 사유 (캐시로 대체된 경우) */
  error: string | null;
  /**
   * 시연 고정 모드인가 (`G2B_LIVE_FETCH=0`).
   *
   * 「키가 없어서 캐시」와 「키가 있는데 일부러 안 부름」은 다른 사실이다.
   * 옛 스냅샷에는 이 필드가 없으므로 선택 필드로 둔다 — 없으면 「고정 아님」이다.
   */
  frozen?: boolean;
  /**
   * 나라장터를 「어떻게 받았는가」 — 「공고명 키워드 10개 · 마감 제외 · 최근 30일」.
   *
   * 수집 방식을 고친 뒤로(0920 §4-A-1) 이것이 화면에 보이지 않으면, 담당자는 여전히
   * 옛 방식으로 받는 줄 안다. 옛 캐시에는 없으므로 없을 수 있다 — 그때는 적지 않는다.
   */
  collected_by?: string | null;
  /** 그 수집에서 나라장터를 부른 횟수. */
  collect_calls?: number | null;
  notices: ProcurementNotice[];
}

/** 공고 첨부파일 목록 (없으면 빈 배열). */
export function noticeAttachments(notice: ProcurementNotice): NoticeAttachment[] {
  return notice.raw_data.attachments ?? [];
}
