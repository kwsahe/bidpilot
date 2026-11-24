/**
 * Evidence Cosmos 대시보드 표시용 포맷 헬퍼.
 * 서버/클라이언트 렌더 결과가 달라지지 않도록 시간대는 Asia/Seoul로 고정한다.
 */

import type { CSSProperties } from "react";

import type { RequirementDisplayStatus } from "./graph";
import type {
  EligibilityMethod,
  EligibilityStatus,
  GroundingType,
  Severity,
} from "@/types/cosmos";
import type { ExtractionMethod, RequirementType } from "@/types/rfp";
import { DECISION_LABELS as DECISION_DICTIONARY, ELIGIBILITY_GATE_LABELS, TIER_LABELS } from "@/lib/scoreNames";
import { AI_ADDED_LABEL, COMPANY_EVIDENCE, NO_BUDGET } from "@/lib/terms";
import { withAlpha } from "./theme";

const TIME_ZONE = "Asia/Seoul";

const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeZone: TIME_ZONE,
});

const dateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: TIME_ZONE,
});

const numberFormatter = new Intl.NumberFormat("ko-KR");

function parseIso(value: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | null): string {
  const date = parseIso(value);
  return date ? dateFormatter.format(date) : "확인 필요";
}

export function formatDateTime(value: string | null): string {
  const date = parseIso(value);
  return date ? dateTimeFormatter.format(date) : "확인 필요";
}

/**
 * 금액 표기는 **이것 하나** — 「1.2억원 / 6,000만원」 (27차 UNI-08).
 *
 * 같은 예산이 3D 카드 「6,000만원」, 2D 카드 「6000만원」, 오른쪽 패널 「60,000,000원」으로 찍혔고
 * 없을 때도 「미공개 / 예산 미정 / 확인 필요」로 갈렸다. 상세도 카드도 이 꼴을 쓴다.
 */
export function formatBudgetCompact(value: number | null): string {
  if (value === null) return NO_BUDGET;
  if (value >= 100_000_000) {
    const eok = value / 100_000_000;
    const text = Number.isInteger(eok) ? String(eok) : eok.toFixed(1).replace(/\.0$/, "");
    return `${text}억원`;
  }
  if (value >= 10_000) {
    return `${numberFormatter.format(Math.round(value / 10_000))}만원`;
  }
  return `${numberFormatter.format(value)}원`;
}

/**
 * D-day 계산은 **lib/deadline 한 곳**에만 둔다.
 *
 * 예전에는 여기서 `Math.ceil((마감 - 지금) / 하루)` 로 셌다. 그 값은 마감 «시각»에 끌려가서
 * 같은 사업의 마감이 대시보드에서는 D-4, 목록·레이더·지원사업 화면에서는 D-5 로 갈렸다.
 * 화면마다 계산을 복제하지 않도록 여기서는 다시 내보내기만 한다.
 */
export { daysUntil, formatDDay } from "@/lib/deadline";

export function formatPercent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

export function formatSimilarity(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function formatPage(page: number | null): string {
  return page === null ? "쪽 모름" : `${page}쪽`;
}

/**
 * 조항 · 요구사항 코드를 사람 말로 — 「REQ-012」 → 「12번 요구사항」 · 「QC-03」 · 「RFP-QC-03」 → 「3번 조항」(31차 §3-D).
 * 저장 · 확인 단추는 코드 그대로 쓴다 — 화면 글자만.
 */
export function clauseRefText(id: string): string {
  const req = /^REQ-0*(\d+)$/.exec(id);
  if (req) return `${req[1]}번 요구사항`;
  const qc = /QC-0*(\d+)$/.exec(id);
  if (qc) return `${qc[1]}번 조항`;
  return id;
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

/** 색(var() · 16진)을 은은한 칩 스타일로 바꾼다 (텍스트=원색, 배경/테두리=투명도 적용). */
export function tintStyle(color: string): CSSProperties {
  return {
    color,
    backgroundColor: withAlpha(color, 12),
    borderColor: withAlpha(color, 33),
  };
}

// ---------------------------------------------------------------------------
// 라벨 사전 (한국어 UI)
// ---------------------------------------------------------------------------

export const GROUNDING_LABELS: Record<GroundingType, string> = {
  RFP_GROUNDED: "공고문 근거",
  COMPANY_EVIDENCE_GROUNDED: COMPANY_EVIDENCE,
  AI_SUGGESTION: AI_ADDED_LABEL,
};

/** 문장 표지 — AI 가 다듬은 문장(44차 M5 · `refined_from`)은 「AI 다듬음 — 근거: 공고문 근거」. 나머지는 근거 유형 그대로. */
export function groundingLabel(sentence: { grounding_type: GroundingType; refined_from?: GroundingType | null }): string {
  if (sentence.refined_from) return `AI 다듬음 — 근거: ${GROUNDING_LABELS[sentence.refined_from]}`;
  return GROUNDING_LABELS[sentence.grounding_type];
}

/** 키워드 후보 등급. 화면에 HIGH/MED/LOW 라고 쓰지 않는다. */
/**
 * 키워드 등급 — **`scoreNames.TIER_LABELS` 를 그대로 쓴다** (ISSUE-074-e · 0921 §4-E).
 *
 * 사본을 두면 갈린다. 실제로 갈려 있었다 — 이쪽에만 `none` 이 있었고, 상세 패널은 한 파일
 * 안에서 위아래가 다른 표를 봤다. 두 이름을 다 남기는 것은 호출부가 많아서다.
 */
export const CANDIDATE_TIER_LABELS: Record<string, string> = TIER_LABELS;

export const SEVERITY_LABELS: Record<Severity, string> = {
  critical: "탈락 위험",
  high: "심각",
  medium: "중간",
  low: "낮음",
  info: "참고",
};

/**
 * 「심각」 셈 — `findingsHigh*` 는 critical(탈락 위험)까지 센다. 「탈락 위험 2 · 심각 5」처럼 겹치는 두 수를 따로 센 것처럼
 * 나란히 두지 않고 「심각 5(탈락 위험 2 포함)」로 적는다(31차 R30-30).
 */
export function seriousText(high: number, blocking: number, unit = ""): string {
  return `${SEVERITY_LABELS.high} ${high}${unit}${blocking > 0 ? `(${SEVERITY_LABELS.critical} ${blocking}${unit} 포함)` : ""}`;
}

/**
 * 담당자가 이 도구를 켜고 가장 먼저 알고 싶은 것이 「내가 이 사업에 참여할 수 있는가」인데,
 * 그 답이 여태 CHECK 라는 영단어로 왔다. 표에서 자기 자신으로 매핑돼 있어 «번역이 없는 번역표»였다.
 * 비교식(`status === "FAIL"`)과 API 필드는 그대로 두고 **표시만** 한국어로 바꾼다.
 *
 * 사전은 `scoreNames.ELIGIBILITY_GATE_LABELS` 하나다 — 이 이름은 호출부가 많아 남긴 별칭이다.
 * 예전에는 여기만 「참가 가능 / 사람 확인 필요 / 참가 불가」라 같은 공고가 목록 「확인 필요」,
 * 대시보드 KPI 「사람 확인 필요」로 보였다 (27차 UNI-05).
 */
export const ELIGIBILITY_LABELS = ELIGIBILITY_GATE_LABELS as Record<EligibilityStatus, string>;

/** 자격 판정 집계를 사람 말로 편다 — 「P6/C8/F0」 같은 암호를 화면에 쓰지 않기 위한 것. */
export function eligibilityTallyText(pass: number, check: number, fail: number): string {
  return `가능 ${pass} · 확인 필요 ${check} · 불가 ${fail}`;
}

export const METHOD_LABELS: Record<EligibilityMethod | ExtractionMethod, string> = {
  RULE: "규칙 판정",
  AI_EXTRACTION: "AI 추출",
  HUMAN: "담당자 판단",
};

/**
 * 제안서 생성 방식 — 6단계 칩 · 제안서 상세 · 안내 · 출처가 같은 말 (DTL-37).
 * AI 가 쓴 문장도 규칙 검증(원문에 없는 숫자 · 근거 없는 주장 내림)을 거친다.
 */
export const GENERATION_METHOD_LABELS: Record<"RULE" | "LLM", string> = {
  LLM: "AI 생성 (규칙 검증)",
  RULE: "규칙 생성",
};

export const REQUIREMENT_TYPE_LABELS: Record<RequirementType, string> = {
  mandatory: "필수",
  optional: "선택",
};

export const REQUIREMENT_STATUS_LABELS: Record<RequirementDisplayStatus, string> = {
  matched: "회사 근거 있음",
  partial: "후보만 있음",
  unmatched: "회사 근거 없음",
  check: "확인 필요",
};

/**
 * 화면에 보이는 개념은 **여기를 거쳐** 한국어가 된다 (ISSUE-016 · TASK-009).
 *
 * ## 왜 필요한가
 *
 * 같은 화면에 「입찰 참가 가능 여부」와 `PASS 6 · CHECK 8 · FAIL 0` 이 함께 떠 있었다.
 * 카드 제목은 한국어로 바꿨는데 버튼·칩·패널 제목은 enum 값을 그대로 찍고 있었기 때문이다.
 * 담당자가 「GO 를 눌러야 하나 HOLD 를 눌러야 하나」를 영어로 판단하게 만든다.
 *
 * ## 규칙
 *
 * - **비교식과 API 필드는 그대로 둔다.** 바뀌는 것은 사람이 읽는 글자뿐이다.
 *   (`status === "FAIL"` 은 그대로, 저장 스키마도 그대로.)
 * - 영문 원어가 필요하면 `title` 툴팁으로만 보조한다. 본문에 병기하지 않는다 —
 *   병기하면 결국 영문을 읽게 된다.
 * - 새 enum 을 화면에 쓸 때 여기에 한 줄을 먼저 만든다.
 */

/** 참여 결정. 「GO/HOLD/NO-GO」는 담당자가 매일 쓰는 말이 아니다. */
export const DECISION_LABELS = DECISION_DICTIONARY as Record<"GO" | "HOLD" | "NO_GO" | "UNREVIEWED", string>;

/** 참여를 막는/확인이 필요한 조건의 상태. */
export const CONDITION_STATUS_LABELS: Record<"BLOCKER" | "ACTION" | "CHECK" | "CLEARED" | "INFO", string> = {
  BLOCKER: "참가 차단",
  ACTION: "할 일 있음",
  CHECK: "확인 필요",
  CLEARED: "해결됨",
  INFO: "참고",
};

/** 패널·섹션 제목. 영문 제목을 그대로 쓰던 자리. */
export const PANEL_TITLES = {
  conditions: "놓치면 안 되는 조건",
  actionChecklist: "할 일 목록",
  auditor: "제출 전 누락 점검",
  requirementMatrix: "요구사항 정리표",
  evidenceMapping: "회사 수행근거 연결",
  proposal: "제안서 초안",
  opportunity: "사업기회",
} as const;

/**
 * 조건 패널 근거 칸 — 백엔드가 이미 「나라장터 기본정보 …」 · 「공고 …」 · 「입찰공고문 …」 · 「제안요청서 …」로 적어 보내면 그대로,
 * 맨 필드 이름만 오면 앞말을 붙인다. 예전에는 「공고」로 시작하는지만 봐서 「나라장터 기본정보 나라장터 기본정보 …」로
 * 두 번 적혔고(33차 R32-01), 입찰공고문 · 제안요청서 인용에도 「나라장터 기본정보」가 붙었다(34차 R33-05).
 */
export function sourceFieldText(field: string): string {
  return /^(나라장터 기본정보|공고|입찰공고문|제안요청서)/.test(field) ? field : `나라장터 기본정보 ${field}`;
}
