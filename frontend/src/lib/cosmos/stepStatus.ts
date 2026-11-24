import type { StepStatus } from "@/lib/cosmos/graph";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";

/**
 * 단계 상태 기호 — 레일 · 지도 정거장 알약 · 범례 · 쉬운 보기 8단계 칸이 **같은 사전**을 읽는다 (27차 §3-D-2).
 *
 * 예전에는 레일(WorkflowRail)에만 있어서 지도는 ③ 에만 「확인 전 2」를 띄우고 레일은 ③⑤⑥⑦ 에 「!」를 띄웠다.
 * 상태는 색 + 기호 + 글자로 함께 말한다(색만으로 말하지 않는다).
 */
export const STEP_STATUS_META: Record<StepStatus, { glyph: string; color: string; label: string }> = {
  done: { glyph: "✓", color: COSMOS_COLORS.cyan, label: "완료" },
  active: { glyph: "●", color: COSMOS_COLORS.blueText, label: "진행 중" },
  attention: { glyph: "!", color: COSMOS_COLORS.amber, label: "확인 필요" },
  failed: { glyph: "✕", color: COSMOS_COLORS.red, label: "실패" },
  pending: { glyph: "○", color: COSMOS_COLORS.slate, label: "대기" },
};
