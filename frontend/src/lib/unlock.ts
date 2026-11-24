/**
 * 「갖추면 가능」 줄의 머리말 하나(32차 §3-B-2). 나라장터 입찰참가자격 등록은 회사자료에 적어 확정되는 값이 아니라
 * 등록증으로 **직접 확인**할 일이다 — 「갖추면 가능:」을 붙이면 「적으면 확정된다」로 읽혔다.
 * 사업기회 행 · 레이더 상세 · 3단계 판정 줄 · 「이번 주」가 같은 판별을 쓴다.
 */

export const UNLOCK_HEAD = "갖추면 가능";
export const DIRECT_CHECK_HEAD = "직접 확인";

const REGISTRATION_RULE = "ELIG-REGISTRATION";
/** 백엔드 `eligibility_engine.REGISTRATION_UNLOCK` 문장의 표식 — 목록(문장만 오는 곳)에서 가른다. 시험이 두 파일을 함께 본다. */
export const REGISTRATION_UNLOCK_MARK = "등록증에서";

export function isDirectCheck(condition: string, ruleId?: string | null): boolean {
  return ruleId === REGISTRATION_RULE || condition.includes(REGISTRATION_UNLOCK_MARK);
}

/**
 * 백엔드 열쇠 「공동수급 파트너 확보 시」(`eligibility_engine` 사업 규모 · 공동수급 조항 — 갭 리포트가 같은 글로 센다).
 * 이 줄과 「규모 큼」 주의 줄에는 가이드 2-6(함께 참가 · 하도급) 링크를 붙인다(33차 §3-B-5).
 */
export const CONSORTIUM_UNLOCK = "공동수급 파트너 확보 시";
export const SIZE_CAUTION_MARK = "규모 큼";
/** 「규모 큼」 중 상한을 아직 안 적은 꼴(`opportunity_priority.caution_line`) — 넘었는지 모르니 링크를 붙이지 않는다. */
const CEILING_MISSING_MARK = "회사자료에 적어";
/** 사업 규모 줄이 상한을 넘었을 때만 쓰는 글(`eligibility_engine._rule_budget`) — 시험이 두 파일을 함께 본다. */
export const OVER_CEILING_MARKS = ["보다 큽니다", "보다 크고", "금액을 넘습니다"] as const;

/** 「규모 큼」 주의가 상한을 실제로 넘은 꼴인가 — 가이드 2-6 링크는 이 줄에만(34차 R33-S3). */
export function isOverCeilingCaution(line: string): boolean {
  return line.includes(SIZE_CAUTION_MARK) && !line.includes(CEILING_MISSING_MARK);
}

/** 상세의 사업 규모 줄이 상한을 넘었나 — 예산을 모르거나 상한 안이면 링크를 붙이지 않는다(34차 R33-S3). */
export function isOverCeilingRow(row: { rule_id: string; status: string; reason: string }): boolean {
  return row.rule_id === "ELIG-BUDGET" && row.status === "CHECK" && OVER_CEILING_MARKS.some((m) => row.reason.includes(m));
}

/** 문장 목록을 「갖추면 가능」 · 「직접 확인」으로 가른다. */
export function splitUnlocks(conditions: readonly string[]): { gain: string[]; direct: string[] } {
  return {
    gain: conditions.filter((c) => !isDirectCheck(c)),
    direct: conditions.filter((c) => isDirectCheck(c)),
  };
}
