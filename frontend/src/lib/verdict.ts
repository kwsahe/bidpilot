/**
 * **판정 알약** — 「가능 · 확인 필요 · 불가 · 간접」을 한 곳에서 만든다 (0925 §4-F-3).
 *
 * ## 왜 이 파일이 있나
 *
 * 10차의 기업마당 카드에서 가장 밝은 줄은 「주의 신청자격(업력·기업유형…)은 공고
 * 원문에서 확인해야 합니다」(주황, 10.5:1)였다. 그것은 모든 카드에 똑같이 붙는
 * 일반 경고였고, 정작 **판정은 카드 어디에도 배지가 없었다** — 대시보드 「이번 주
 * 할 일」에는 있는데 목록에는 없었다. 담당자가 100건을 훑을 때 가장 먼저 읽어야
 * 하는 것이 「이 사업에 우리가 신청할 수 있는가」인데 그것이 안 보였다.
 *
 * 두 화면이 같은 말을 같은 색으로 해야 한다. 그래서 **말과 색을 여기 한 벌만** 둔다 —
 * 대시보드도 목록도 이 함수를 부른다. `support_application_service.verdict_of`(백엔드)
 * 와 같은 네 값이고, 엑셀 `verdict_of` 와도 같은 말이다 (CLAUDE.md §11 화면 어휘).
 */

import { VERDICT_TONES, type Tone } from "@/lib/cosmos/theme";
import type { EligibilityGate } from "@/types/opportunity";

export type Verdict = "가능" | "확인 필요" | "불가" | "간접 참여" | "미확인";

/**
 * 판정 한 벌. `participation`(간접 참여 자리 이름)이 있으면 그것이 판정 자리에 온다 —
 * 「가능」이라고 적으면 회사가 직접 신청하는 줄 알기 때문이다.
 */
export function verdictOf(
  gate: EligibilityGate | null | undefined,
  participation?: string | null,
): { label: Verdict; tone: Tone; title: string } {
  if (participation) {
    return {
      label: "간접 참여",
      tone: "info",
      title: `회사가 직접 신청하는 자리가 아닙니다 — ${participation}`,
    };
  }
  // 색은 판정 4색(`theme.VERDICT_TONES`) — 「가능」 청록 · 「불가」 빨강이 지도 · 패널 · 레이더와 같다 (27차 §3-E · UNI-10).
  if (gate === "PASS") {
    return { label: "가능", tone: VERDICT_TONES.PASS, title: "규칙 판정: 회사 사실이 요건과 맞습니다" };
  }
  if (gate === "FAIL") {
    return { label: "불가", tone: VERDICT_TONES.FAIL, title: "규칙 판정: 막는 조항이 있습니다" };
  }
  if (gate === "CHECK") {
    return { label: "확인 필요", tone: VERDICT_TONES.CHECK, title: "규칙 판정: 확정하지 못한 요건이 남아 있습니다" };
  }
  return { label: "미확인", tone: VERDICT_TONES.NONE, title: "아직 판정하지 않았습니다" };
}
