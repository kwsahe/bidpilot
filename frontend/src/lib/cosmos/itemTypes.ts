/**
 * 문서 항목 유형 표시 규칙 — RFP Matrix 탭, 3D 노드 색/모양, 상세 패널 설명이 같은 값을 쓴다.
 * 색은 theme.ts 토큰만 쓴다.
 */

import type { Criticality, ItemType, Requirement, ReviewStatus } from "@/types/rfp";

import { COSMOS_COLORS, STATE_COLORS, type CosmosNodeState } from "./theme";

export const ITEM_TYPE_ORDER: ItemType[] = [
  "TASK",
  "REQUIREMENT",
  "ELIGIBILITY",
  "SUBMISSION",
  "SCHEDULE",
  "EVALUATION",
  "SPECIAL_CONDITION",
  "REFERENCE",
];

export const ITEM_TYPE_LABELS: Record<ItemType, string> = {
  TASK: "과업",
  REQUIREMENT: "필수 요구사항",
  ELIGIBILITY: "참가자격",
  SUBMISSION: "제출",
  SCHEDULE: "일정",
  EVALUATION: "평가기준",
  SPECIAL_CONDITION: "특이사항",
  REFERENCE: "참고정보",
};

export const ITEM_TYPE_PREFIX: Record<ItemType, string> = {
  TASK: "TSK",
  REQUIREMENT: "REQ",
  ELIGIBILITY: "ELG",
  SUBMISSION: "SUB",
  SCHEDULE: "SCH",
  EVALUATION: "EVL",
  SPECIAL_CONDITION: "SPC",
  REFERENCE: "REF",
};

export const ITEM_TYPE_COLORS: Record<ItemType, string> = {
  TASK: COSMOS_COLORS.cyan,
  REQUIREMENT: COSMOS_COLORS.blueText, // 칩 · 배지 글자로 쓰인다 — 면용 blue 는 4.44:1(26차 검수 FE-4)
  ELIGIBILITY: COSMOS_COLORS.amber,
  SUBMISSION: COSMOS_COLORS.violet,
  SCHEDULE: COSMOS_COLORS.violet,
  EVALUATION: COSMOS_COLORS.green,
  SPECIAL_CONDITION: COSMOS_COLORS.red,
  REFERENCE: COSMOS_COLORS.slate,
};

/** "무엇" — 이 유형이 제안서 작성자에게 뜻하는 것. */
export const ITEM_TYPE_WHAT: Record<ItemType, string> = {
  TASK: "수행해야 할 일. 제안서 사업수행계획이 이 항목에 답해야 한다.",
  REQUIREMENT: "충족해야 할 조건. 근거(회사자료)로 충족을 보여야 한다.",
  ELIGIBILITY: "입찰에 참가할 수 있는 자격. 하나라도 못 맞추면 참가 자체가 막힌다.",
  SUBMISSION: "무엇을 어떤 형식으로 제출하는가. 빠지면 형식 미비로 탈락한다.",
  SCHEDULE: "언제까지 무엇을 해야 하는가 (설명회·마감·기간).",
  EVALUATION: "어떻게 채점되는가. 배점이 큰 항목에 지면을 배분한다.",
  SPECIAL_CONDITION: "계약·보증·보안·공동수급 같은 특약. 계약 위험을 좌우한다.",
  REFERENCE: "배경·목적 같은 참고정보. 대응 문장을 만들 의무는 없다.",
};

/** RFP Matrix 탭 (전체 + 유형 묶음). */
export interface ItemTab {
  key: "all" | ItemType | "submission_schedule";
  label: string;
  types: ItemType[] | null;
}

export const ITEM_TABS: ItemTab[] = [
  { key: "all", label: "전체", types: null },
  { key: "TASK", label: "과업", types: ["TASK"] },
  { key: "REQUIREMENT", label: "필수 요구사항", types: ["REQUIREMENT"] },
  { key: "ELIGIBILITY", label: "참가자격", types: ["ELIGIBILITY"] },
  { key: "submission_schedule", label: "제출·일정", types: ["SUBMISSION", "SCHEDULE"] },
  { key: "EVALUATION", label: "평가기준", types: ["EVALUATION"] },
  { key: "SPECIAL_CONDITION", label: "특이사항", types: ["SPECIAL_CONDITION"] },
  { key: "REFERENCE", label: "참고정보", types: ["REFERENCE"] },
];

export const CRITICALITY_LABELS: Record<Criticality, string> = {
  // 화면에 그대로 나가는 말이다. 조건 상태 사전과 같은 이름을 쓴다 (ISSUE-061).
  blocker: "참가 차단",
  high: "높음",
  normal: "보통",
  low: "낮음",
};

export const CRITICALITY_COLORS: Record<Criticality, string> = {
  blocker: COSMOS_COLORS.red,
  high: COSMOS_COLORS.amber,
  normal: COSMOS_COLORS.slate,
  low: COSMOS_COLORS.slate,
};

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  unreviewed: "미검토",
  confirmed: "확정",
  corrected: "정정",
  rejected: "반려",
};

export function itemTypeOf(req: Pick<Requirement, "item_type">): ItemType {
  return req.item_type ?? "REQUIREMENT";
}

export function criticalityOf(req: Pick<Requirement, "criticality">): Criticality {
  return req.criticality ?? "normal";
}

/** REQ-003 → TSK-003 (backend display_code가 있으면 그대로). 저장 id는 바꾸지 않는다. */
export function displayCodeOf(req: Pick<Requirement, "display_code" | "item_type" | "requirement_id">): string {
  if (req.display_code) return req.display_code;
  const number = req.requirement_id.includes("-") ? req.requirement_id.split("-").slice(1).join("-") : req.requirement_id;
  return `${ITEM_TYPE_PREFIX[itemTypeOf(req)]}-${number}`;
}

/** 유형별 건수. 모든 유형 키를 0으로라도 넣는다. */
export function countByType(requirements: ReadonlyArray<Pick<Requirement, "item_type">>): Record<ItemType, number> {
  const counts = Object.fromEntries(ITEM_TYPE_ORDER.map((t) => [t, 0])) as Record<ItemType, number>;
  for (const req of requirements) counts[itemTypeOf(req)] += 1;
  return counts;
}

/** "무엇을 수행 / 어떤 조건 / 무엇을 언제 제출" 세 묶음 건수. */
/**
 * 평가 배점 · 참고 · 서식 항목인가(43차 E2E-13 · Q22) — 정리표 99건이 모두 빨간 「필수」라, 탈락을 가르는 조건(실무 문서 §2.5 0단계)과
 * 「평가점수는 대외비로 처리함」 · 「첨부. 관련 서식」이 같은 낱말이었다. 이것들은 「참고 · 평가」로 적고 「필수」 건수에서 뺀다.
 */
export function isReferenceItem(req: Pick<Requirement, "item_type">): boolean {
  return req.item_type === "EVALUATION" || req.item_type === "REFERENCE";
}

/** 정리표 「필수 여부」 칸 — 참고 · 평가 항목은 저장값(필수)과 상관없이 「참고 · 평가」(회청). */
export function requirementTypeChip(req: Pick<Requirement, "item_type" | "requirement_type">): { label: string; mandatory: boolean } {
  if (isReferenceItem(req)) return { label: "참고 · 평가", mandatory: false };
  return { label: req.requirement_type === "mandatory" ? "필수" : "선택", mandatory: req.requirement_type === "mandatory" };
}

/** 「필수」 건수 한 곳(45차 M6) — 정리표 · 대시보드 · 카드가 같은 수(참고 · 평가 항목 뺌). 저장값 99 · 정리표 73 으로 갈렸다. */
export function mandatoryCount(requirements: ReadonlyArray<Pick<Requirement, "item_type" | "requirement_type">>): number {
  return requirements.filter((req) => requirementTypeChip(req).mandatory).length;
}

export function groupCounts(requirements: ReadonlyArray<Pick<Requirement, "item_type">>): {
  perform: number;
  conditions: number;
  submit: number;
  other: number;
} {
  const counts = countByType(requirements);
  return {
    perform: counts.TASK,
    conditions: counts.REQUIREMENT + counts.ELIGIBILITY + counts.SPECIAL_CONDITION,
    submit: counts.SUBMISSION + counts.SCHEDULE,
    other: counts.EVALUATION + counts.REFERENCE,
  };
}

/**
 * 노드 색 — **판정 뜻만** (21차 · prompt_11 §3-3): 가능 청록 · 확인 필요 호박 · 불가 붉음 · 중립 회청.
 * 종류는 색이 아니라 모양이 말한다(● ◆ ▲ ▪ ▫ ─ ⚠ ◉). 3D·2D·범례가 같은 규칙을 쓴다.
 * 해결된 발견은 가능 쪽(청록), 후보 증빙만 있는 요구사항은 확인 필요 쪽(호박)이다.
 */
// 판정 4색은 theme 한 곳(27차 §3-E 색 한 벌) — 지도 · 목록 · 상세 · 범례가 같은 값을 읽는다.
const VERDICT_COLORS: Record<CosmosNodeState, string> = STATE_COLORS;

export function nodeColorHex(node: { state: CosmosNodeState }): string {
  return VERDICT_COLORS[node.state];
}

/**
 * 판정 낱말 — 색과 **한 벌** (27차 §3-D-4). 지도 범례 줄 · 범례 시트 · 목록 보기 · 상세 패널이 여기서 읽는다.
 * 색만으로 판정을 말하지 않는다 — 호박 · 빨강 항목은 이름표 끝에 같은 색 낱말을 붙인다.
 */
export const VERDICT_WORDS: Record<CosmosNodeState, string> = {
  ok: "충족",
  resolved: "충족",
  check: "확인 필요",
  partial: "확인 필요",
  warning: "문제",
  neutral: "판정 전",
  missing: "판정 전",
};

export function verdictWord(state: CosmosNodeState): string {
  return VERDICT_WORDS[state];
}

/** 이름표 끝 낱말 알약 — 호박 · 빨강만(충족 · 판정 전은 색이 조용해 낱말을 붙이지 않는다). */
export function verdictPill(state: CosmosNodeState): { word: string; color: string } | null {
  return state === "check" || state === "partial" || state === "warning" ? { word: VERDICT_WORDS[state], color: VERDICT_COLORS[state] } : null;
}

/** 선 색 — 판정 색을 다시 쓴다: 연결됨 청록 · 확인이 필요한 연결 호박 · 문제 빨강 (27차 §3-D-3 · 회청 선 없음). */
export function lineColorHex(state: "active" | "candidate" | "warning"): string {
  return VERDICT_COLORS[state === "active" ? "ok" : state === "candidate" ? "check" : "warning"];
}

/** 범례에 늘 보이는 네 가지 — 순서 · 글자 · 색이 지도 범례 줄과 범례 시트에서 같다. */
export const VERDICT_KEY: readonly { word: string; color: string }[] = [
  { word: VERDICT_WORDS.ok, color: VERDICT_COLORS.ok },
  { word: VERDICT_WORDS.check, color: VERDICT_COLORS.check },
  { word: VERDICT_WORDS.warning, color: VERDICT_COLORS.warning },
  { word: VERDICT_WORDS.neutral, color: VERDICT_COLORS.neutral },
];
