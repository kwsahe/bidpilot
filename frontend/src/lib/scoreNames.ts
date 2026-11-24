/**
 * 화면에 쓰는 «점수 이름»과 «상태 이름»의 단일 출처 (0920 §4-B-1 · ISSUE-074).
 *
 * ## 왜 이 파일이 있나
 *
 * 같은 공고 하나에 적합도가 **다섯 가지 이름**으로 붙어 있었다 —
 * 대시보드 「우리 회사 적합도 82」, 상세 「점수 0.69」, 상세·선택창 「등급 B」,
 * 목록 「회사 적합도 69점」, 레이더 「69 SCORE」. 담당자가 「화면이 서로 다르다」고 한 것이
 * 이것이다. 값의 종류는 실제로 둘뿐인데 이름이 다섯이었다.
 *
 * ## 이름은 둘뿐이다
 *
 * - **추천등급** — 나라장터 공고만. A/B/C/마감. **기본 회사 기준**으로 계산한다.
 * - **검토 우선순위** — 통합 0~100. **선택한 회사 기준**. 낙찰확률이 아니다 (CLAUDE.md §12).
 *
 * 0~1 값은 화면에 내지 않는다. 사람이 읽는 척도가 아니다.
 *
 * ## 이 파일의 규칙
 *
 * **import 를 하나도 두지 않는다.** 그래야 `node --test` 가 그대로 부를 수 있고,
 * 네 화면(대시보드·레이더·사업기회·RFP 분석)이 모두 같은 사전을 볼 수 있다.
 * 저장 값(enum)은 바꾸지 않는다 — 캐시·저장 파일이 그 값을 쓴다. 바꾸는 것은 **표기**뿐이다.
 */

/** 점수 하나의 이름·설명·범위. 화면은 이 세 가지를 그대로 적는다. */
export interface ScoreName {
  /** 화면에 찍는 이름 */
  label: string;
  /** 무엇을 재는가 — 툴팁·안내에 그대로 쓴다 */
  description: string;
  /** 어느 회사 기준인가 */
  scope: string;
  /** 값의 범위 */
  range: string;
}

/**
 * 나라장터 공고의 추천등급.
 *
 * **기본 회사 기준으로 계산한다** — 회사를 바꿔도 이 등급은 바뀌지 않는다
 * (`procurement_service._load_company_basis`). 그래서 등급 옆에 기준을 작게 적는다.
 */
export const RECOMMENDATION_GRADE: ScoreName = {
  label: "추천등급",
  description: "나라장터 공고를 먼저 볼 순서로 나눈 등급입니다. 낙찰확률이 아닙니다.",
  scope: "기본 회사 기준",
  range: "A · B · C · 마감",
};

/** 통합 목록의 검토 우선순위 (CLAUDE.md §12 의 이름 그대로). */
export const REVIEW_PRIORITY: ScoreName = {
  label: "검토 우선순위",
  description: "회사 기준으로 먼저 볼 순서입니다. 낙찰확률·선정확률이 아닙니다.",
  scope: "선택한 회사 기준",
  range: "0~100",
};

/** 「우선 검토」로 부르는 경계. 백엔드 `opportunity_priority.PRIORITY_HIGH/MID` 와 같아야 한다. */
/**
 * 「우선 검토」·「검토」 경계 (백엔드 `opportunity_priority.PRIORITY_HIGH/MID` 와 같아야 한다).
 *
 * 8차에서 70 → 80 으로 올리고 **상위 15%** 규칙을 더했다 (0922 §4-B-6). 예전 기준으로는
 * 목록 107건 중 41건이 「우선 검토」였다 — 거의 전부가 그 이름을 달면 담당자는 그 이름을
 * 읽지 않는다. 라벨 자체는 백엔드가 매겨 내려보내므로 화면이 다시 계산하지 않는다.
 */
export const PRIORITY_THRESHOLDS = { high: 80, mid: 45, topRatio: 0.15 } as const;

/**
 * 추천등급 표기.
 *
 * `NO_GO` 는 백엔드에서 **「입찰 마감이 지났다」만 뜻한다**(`recommendation.py`).
 * 「참여 불가」로 적으면 사람이 내린 결정처럼 읽힌다 — 그래서 「마감」이다.
 */
export const GRADE_LABELS: Record<string, string> = {
  A: "A",
  B: "B",
  C: "C",
  D: "D",
  NO_GO: "마감",
};

/** 추천등급 한 줄 설명. 배지 툴팁에 쓴다. */
export const GRADE_HINTS: Record<string, string> = {
  A: "먼저 볼 것",
  B: "검토",
  C: "낮음",
  D: "낮음",
  NO_GO: "입찰 마감이 지났습니다",
};

/** 키워드 후보 등급 (`candidate.tier`). */
/**
 * 키워드 등급 (`candidate.tier`).
 *
 * **사전은 하나다.** 예전에는 같은 등급 표가 여기와 `lib/cosmos/format` 두 곳에 있었고,
 * 상세 패널 한 파일 안에서도 위쪽은 `CANDIDATE_TIER_LABELS`, 아래쪽은 `TIER_LABELS` 를
 * 썼다 — `none` 이 한쪽에만 있어 값에 따라 답이 달랐다 (ISSUE-074-e · 0921 §4-E).
 * 지금은 `format.CANDIDATE_TIER_LABELS` 가 이 표를 그대로 다시 내보낸다.
 */
export const TIER_LABELS: Record<string, string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
  none: "해당 없음",
};

/** 참여 결정 (`decision.status`). 저장 값은 그대로 두고 표기만 한국어다. */
export const DECISION_LABELS: Record<string, string> = {
  GO: "참여",
  HOLD: "보류",
  NO_GO: "참여 안 함",
  // 「미결정」 · 「결정 미정」 · 「결정 대기」가 화면마다 갈렸다 — 「결정 전」 하나 (27차 UNI-15).
  UNREVIEWED: "결정 전",
};

/** 지원사업(수혜) 신청 여부 결정(44차 M4) — 저장 값은 입찰과 같고(GO · HOLD · NO_GO) 낱말만 신청 쪽. 서버 `decision_service.SUPPORT_LABELS` 와 같은 글. */
export const SUPPORT_DECISION_LABELS: Record<string, string> = {
  GO: "신청",
  HOLD: "검토 중",
  NO_GO: "신청 안 함",
  UNREVIEWED: "결정 전",
};

/** 담당자 최종 검토 (`review.status`). */
export const REVIEW_STATUS_LABELS: Record<string, string> = {
  pending: "검토 대기",
  approved: "검토 승인",
  on_hold: "다시 검토",
  rejected: "참여 안 함",
};

/**
 * 참가자격 규칙 판정 (`eligibility_gate`). 모호하면 「확인 필요」다 (CLAUDE.md §4-D).
 *
 * 말이 셋뿐이다 (0921 §3-11). 예전에는 같은 값이 화면마다 「규칙 판정 통과」·「사람 확인
 * 필요」·「참여 곤란」이었는데, 나라장터와 기업마당이 같은 규칙 모양을 쓰게 되면서
 * 한 벌의 어휘가 필요해졌다. **짧은 쪽으로 맞춘다** — 카드 한 줄에 들어가야 한다.
 */
export const ELIGIBILITY_GATE_LABELS: Record<string, string> = {
  PASS: "가능",
  CHECK: "확인 필요",
  FAIL: "불가",
};

/** 「무엇으로 판정했는가」 (`method`). 영문 코드가 화면에 새지 않게 한다. */
export const METHOD_LABELS: Record<string, string> = {
  KEYWORD: "낱말 기준",
  EMBEDDING: "AI 의미 매칭",
  RULE: "규칙 기반 판정",
  HUMAN: "사람 확인",
  AI_EXTRACTION: "원문에서 뽑음",
};

/** 사전에 없는 값이 와도 영문을 그대로 내보내지 않는다. */
export function labelOf(dictionary: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "미확인";
  return dictionary[value] ?? "미확인";
}

/** 점수가 없을 때의 말 — `terms.UNSCORED` 가 이것을 쓴다(사전 한 곳 · terms 가 이 파일을 가져와 반대로는 못 가져온다). */
export const UNSCORED_WORD = "점수 없음";

/** 검토 우선순위 한 줄. 값이 없으면 「점수 없음」 — 0점으로 단정하지 않는다 (CLAUDE.md §12). */
export function reviewPriorityText(score: number | null | undefined): string {
  if (score === null || score === undefined) return `${REVIEW_PRIORITY.label} ${UNSCORED_WORD}`;
  return `${REVIEW_PRIORITY.label} ${Math.round(score)}`;
}

/** 화면에 내보내는 모든 사전. 테스트가 「영문 값이 없다」를 여기서 한 번에 확인한다. */
export const SCREEN_LABEL_DICTIONARIES = {
  ELIGIBILITY_GATE_LABELS,
  GRADE_LABELS,
  GRADE_HINTS,
  TIER_LABELS,
  DECISION_LABELS,
  REVIEW_STATUS_LABELS,
  METHOD_LABELS,
} as const;
