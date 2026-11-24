"use client";

/**
 * 분석 상태 배지 — **목록 행과 레이더 상세가 같은 것을 그린다** (0920 §4-B-3 · ISSUE-076).
 *
 * 한 공고를 네 화면에서 열었을 때 같은 카드로 보이려면, 상태를 그리는 코드가 한 벌이어야
 * 한다. 두 벌이면 한쪽만 고치는 일이 반드시 생긴다.
 *
 * **모르는 것은 적지 않는다.** 조건을 탐지한 적이 없으면 「참가 차단 0」이 아니라 아무 말도
 * 하지 않는다 — 0 은 「막는 것이 없다」는 뜻이고, 그건 다른 사실이다.
 *
 * 낱말은 대시보드 카드와 **같은 「참가 차단」**이다. 예전에는 여기만 「차단 조건」이라고
 * 적어서, 같은 공고를 네 화면에서 열면 같은 값이 두 이름으로 보였다 (0920 §4-B 완료 조건).
 */

import { Badge } from "@/components/ui/primitives";
import { DECISION_LABELS, labelOf } from "@/lib/scoreNames";
import { DECIDED_SENTENCES, UNDECIDED } from "@/lib/terms";
import type { AnalysisState } from "@/types/opportunity";

export default function AnalysisStateBadges({ state }: { state: AnalysisState | null | undefined }) {
  if (!state) return null;
  const decided = state.decision && state.decision !== "UNREVIEWED";
  return (
    <>
      {state.parsed ? (
        <Badge tone="info">
          공고 분석함
          {state.requirement_count !== null ? ` · 요구사항 ${state.requirement_count}개` : ""}
          {state.check_count ? ` · 확인할 것 ${state.check_count}개` : ""}
        </Badge>
      ) : (
        <Badge tone="muted">분석 전</Badge>
      )}
      <Badge tone={decided ? "ok" : "warn"}>
        {decided ? (DECIDED_SENTENCES[state.decision ?? ""] ?? labelOf(DECISION_LABELS, state.decision)) : UNDECIDED}
      </Badge>
      {state.blocking_conditions ? <Badge tone="fail">참가 차단 조건 {state.blocking_conditions}개</Badge> : null}
      {state.open_findings > 0 && <Badge tone="warn">점검에서 고칠 것 {state.open_findings}개</Badge>}
    </>
  );
}
