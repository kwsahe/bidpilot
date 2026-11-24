"use client";

import DashboardShell from "@/components/cosmos/DashboardShell";

// 입찰 분석 ("/analysis") — 공고 하나를 8단계로 보는 Evidence Cosmos 화면. 2.0.7 까지 "/" 였다(2.1.0 · 대표 결정 2026-10-28).
// 옛 주소(쿼리 notice · support · stage 가 붙은 "/")는 next.config 의 redirects 가 이리로 넘긴다.
// 클라이언트 컴포넌트라 metadata는 layout.tsx의 것을 그대로 쓴다.
export default function AnalysisPage() {
  return <DashboardShell />;
}
