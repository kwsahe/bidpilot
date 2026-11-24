/**
 * 「구버전 결과」 — 지금 요구사항 기준이 아닌 저장 결과를 다루는 규칙. 정의는 여기 하나뿐이다.
 *
 * ## 왜 필요한가
 *
 * 요구사항 추출을 고치면 같은 공고의 필수 요구사항이 32건 → 54건처럼 바뀐다. 그러면 그 전에
 * 저장해 둔 자격판정·조건 분석·근거 연결·제안서·Auditor 결과는 **이전 기준의 값**이 된다.
 * 숫자 자체가 틀린 것이 아니라 «다른 자를 대고 잰 값»이다.
 *
 * 화면에는 「구버전」 경고가 떠 있었지만 그 아래 BLOCKER 1건·조건 분석·행동 목록이 평소와
 * 똑같은 빨강·초록으로 강하게 떠 있었다. 사업담당자는 그것을 최신 판정으로 읽는다.
 *
 * ## 규칙
 *
 * - 구버전 결과를 **지우지 않는다.** 이력이고, 다시 분석하기 전까지의 유일한 참고값이다.
 * - 대신 최신 결과처럼 보이지 않게 한다 — 채도를 낮추고, 카드마다 출처를 적고,
 *   숫자 옆에 「구버전 참고값」을 붙인다.
 * - 주 행동은 「다시 분석」과 「새 제안서 버전 만들기」다.
 * - 구버전 결과로 GO·승인을 저장할 수 없다. 화면에서 막고 backend 도 422 로 막는다
 *   (decision_service._refuse_stale_go · review_service._readiness_or_none).
 */

import type { CosmosGraph } from "./graph";
import type { AuditReadiness } from "@/types/analysis";

/** 저장된 결과가 지금 요구사항 기준인가. 아니면 그 사유(readiness)를 돌려준다. */
export function staleReadiness(graph: CosmosGraph): AuditReadiness | null {
  const readiness = graph.source.analysis.readiness;
  if (!readiness) return null;
  return readiness.blockers.includes("stale_requirements") ? readiness : null;
}

/** 화면 어느 곳에서든 같은 말을 쓴다. */
export const STALE_CARD_LABEL = "현재 요구사항 이전에 생성된 결과";
export const STALE_VALUE_LABEL = "구버전 참고값";

/**
 * 구버전 카드의 겉모습.
 *
 * 색을 지우지 않고 **낮춘다** — 빨강/초록이 그대로 남아 있으면 최신 판정으로 읽히고,
 * 아예 회색으로 덮으면 무엇이 문제였는지 읽을 수 없다.
 */
export const STALE_CARD_CLASS = "opacity-70 saturate-50";

/** 구버전 결과로는 할 수 없는 일에 붙이는 사유 한 줄. */
export function staleBlockReason(readiness: AuditReadiness): string {
  return `${STALE_CARD_LABEL}입니다. 다시 분석하거나 새 제안서 버전을 만든 뒤 결정하세요. ${readiness.message}`;
}
