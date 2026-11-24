/**
 * 「언제 실행한 결과인가」 — 저장된 분석 결과에 붙이는 한 줄 (0923 §3-3 · ISSUE-093).
 *
 * ## 왜 필요한가
 *
 * 화면에 「근거 연결 완료 4문장」·「발견 26건」·「차단 조건 1건」이 떠 있다. 그런데 그것은
 * **9-8 에 돌린 결과**일 수 있다. 담당자는 그것을 지금 상태로 읽는다 — 그 사이에 공고가
 * 바뀌었어도.
 *
 * 그래서 상태 옆에 **실행 시각**을 함께 적는다. 그리고 실행 시각이 **공고의 마지막 변경보다
 * 앞이면** 「다시 실행 필요」를 덧붙인다. 그때의 숫자가 틀린 것이 아니라, **바뀌기 전의
 * 공고를 보고 낸 답**이기 때문이다.
 *
 * ## 규칙
 *
 * - 실행한 적이 없으면 아무 말도 붙이지 않는다(`null`). 「미실행」은 다른 곳이 이미 말한다.
 * - **실행 시각이 없는 옛 파일**은 「실행 시각 없음」이다 — 「방금 실행함」으로 읽히지 않게.
 * - 공고 변경 시각을 모르면(`notice_changed_at === null`) 「다시 실행 필요」를 적지 않는다.
 *   모르는 것을 근거로 경고하지 않는다.
 *
 * 문구는 **여기 한 곳에서만** 만든다. KPI·노드 상세·8단계 레일이 같은 함수를 부르기
 * 때문에 세 곳이 언제나 같은 말을 한다.
 */

import type { CosmosAnalysis } from "./graph";

/** 시각을 아는 단계. 저장 파일에 시각이 있는 것만 여기 있다. */
export type RunStampKey = "evidence" | "audit" | "conditions";

export interface RunStamp {
  /** 실행 시각(ISO). 옛 파일이라 시각이 없으면 null. */
  at: string | null;
  /** 실행한 적이 있는가. false 면 `text` 는 null 이다. */
  ran: boolean;
  /** 공고가 그 뒤로 바뀌었는가. 공고 변경 시각을 모르면 언제나 false. */
  needsRerun: boolean;
  /** 상태 옆에 그대로 붙일 문구. 실행한 적이 없으면 null. */
  text: string | null;
}

const NOT_RUN: RunStamp = { at: null, ran: false, needsRerun: false, text: null };

/** 「9-16」. 연도는 적지 않는다 — 옆에 붙는 짧은 꼬리말이다. */
function shortDate(iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getMonth() + 1}-${date.getDate()}`;
}

/** 저장된 결과의 실행 시각. 결과 자체가 없으면 `undefined`(= 실행한 적 없음). */
function executedAt(analysis: CosmosAnalysis, key: RunStampKey): string | null | undefined {
  if (key === "evidence") return analysis.proposal ? analysis.proposal.generated_at : undefined;
  if (key === "audit") return analysis.audit ? analysis.audit.created_at : undefined;
  return analysis.conditions ? analysis.conditions.detected_at : undefined;
}

/**
 * 한 단계의 실행 시각 꼬리말.
 *
 * 합성 데모 시나리오는 시각이 없는 고정값이라 꼬리말을 붙이지 않는다 — 「실행 시각 없음」은
 * 「옛 파일이다」라는 뜻이고, 데모는 옛 파일이 아니다.
 */
export function runStamp(analysis: CosmosAnalysis, key: RunStampKey): RunStamp {
  const at = executedAt(analysis, key);
  if (at === undefined) return NOT_RUN;
  if (!at) return { at: null, ran: true, needsRerun: false, text: "(실행 시각 없음)" };

  const changed = analysis.readiness?.notice_changed_at ?? null;
  const stamp = shortDate(at);
  const needsRerun =
    changed !== null && !Number.isNaN(new Date(changed).getTime()) && new Date(at) < new Date(changed);
  const when = stamp ? `${stamp} 실행` : "실행 시각 없음";
  return {
    at,
    ran: true,
    needsRerun,
    text: needsRerun ? `(${when} · 다시 실행 필요)` : `(${when})`,
  };
}

/** 상태 문장 뒤에 꼬리말을 붙인다. 붙일 것이 없으면 문장을 그대로 돌려준다. */
export function withRunStamp(text: string, stamp: RunStamp): string {
  return stamp.text ? `${text} ${stamp.text}` : text;
}
