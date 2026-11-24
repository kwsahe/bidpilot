"use client";

/**
 * 「지금 불러오는 중인가」를 화면 전체가 같은 답으로 말하게 한다 (ISSUE-011 · TASK-013).
 *
 * ## 왜 필요한가
 *
 * 공고를 바꾸면 2~5초 동안 KPI 카드와 오른쪽 패널이 「미실행」을 보여주다가 값이
 * 나중에 튀어 들어왔다. 「미실행」은 «아직 실행하지 않았다»는 뜻이고, 담당자는 그것을
 * 「안 돌렸구나」로 읽고 재분석을 누른다 — 이미 돌아간 분석을 다시 돌린다.
 *
 * 로딩 상태(`analysisLoading`)는 대시보드 훅이 이미 가지고 있었지만, 소비처는
 * 타임라인 두 곳뿐이었다. 「미실행」을 쓰는 자리는 KPI·패널·칩에 흩어져 스무 곳이 넘는다.
 *
 * ## 왜 prop 이 아니라 context 인가
 *
 * 스무 곳에 prop 을 내리려면 그 사이의 컴포넌트를 전부 손봐야 한다. 그것은 이 화면의
 * 2,000줄짜리 패널을 쪼개는 일이 되고, 지금 하려는 것(문구 하나를 바로잡는 것)보다
 * 훨씬 큰 변경이다. 값은 하나뿐이고 읽기 전용이므로 context 가 맞다.
 *
 * 기본값은 `false` — provider 로 감싸지 않은 화면(예: 테스트, 다른 라우트)은
 * 예전과 똑같이 동작한다.
 */

import { createContext, useContext, type ReactNode } from "react";

const AnalysisLoadingContext = createContext(false);

export function AnalysisLoadingProvider({ loading, children }: { loading: boolean; children: ReactNode }) {
  return <AnalysisLoadingContext.Provider value={loading}>{children}</AnalysisLoadingContext.Provider>;
}

/** 지금 분석 결과를 불러오는 중인가. provider 밖에서는 false. */
export function useAnalysisLoading(): boolean {
  return useContext(AnalysisLoadingContext);
}

/** 불러오는 중이면 「불러오는 중…」, 아니면 준 문구(기본 「미실행」). */
export function useNotRunLabel(notRun = "아직 안 함"): string {
  return useAnalysisLoading() ? "불러오는 중…" : notRun;
}
