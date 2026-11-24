"use client";

/**
 * 하단 스트립: 한 줄 흐름 설명 + 데이터 출처 배지(합성 샘플 / 실데이터 / 데모 데이터 / 미실행).
 */

import { SourceBadge } from "@/components/ui/SourceBadge";
import { useAnalysisLoading } from "@/lib/cosmos/analysisLoading";
import { sourceBadges, type CosmosGraph } from "@/lib/cosmos/graph";
import { loadingText } from "@/lib/cosmos/useCosmosDashboard";

export const FLOW_DESCRIPTION =
  "분석 대상 공고 → 과업·필수조건 → 회사 수행근거 → 제안서 반영 → 제출 전 위험 검증 → 사람의 결정";

export interface BottomStripProps {
  graph: CosmosGraph | null;
}

export default function BottomStrip({ graph }: BottomStripProps) {
  const badges = graph ? sourceBadges(graph) : [];
  // 읽는 동안 「참가 판정: 아직 안 함」이 아니라 「불러오는 중…」(10-31 최종 점검 A5)
  const loading = useAnalysisLoading();
  return (
    <footer
      data-tour="bottom-sources"
      className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-cosmos-border bg-cosmos-bg/70 px-4 py-1.5 text-[12px] text-cosmos-secondary backdrop-blur lg:min-h-10 lg:flex-nowrap lg:gap-4 lg:py-1"
    >
      {/* 긴 흐름 설명은 좁은 화면에서 가로로 넘친다. 데이터 출처 배지가 더 중요하므로
          모바일에서는 감추고 lg 이상에서만 보인다.
          1366px 에서는 배지 넉 장과 이 문장이 함께 들어가지 않아 페이지에 가로 스크롤이
          생겼다(실측 64px). 배지가 더 중요하므로 이 설명이 먼저 줄어든다. */}
      <p className="hidden min-w-0 shrink truncate whitespace-nowrap xl:block">
        <span className="mr-2 font-semibold text-cosmos-muted">흐름</span>
        {FLOW_DESCRIPTION}
      </p>
      <div
        className="flex min-w-0 flex-wrap items-center gap-1.5 lg:ml-auto lg:gap-2"
        aria-label="데이터 출처"
      >
        {/* 모양은 상단 선택기 · KPI 칩과 같은 규칙(sourceBadges 의 kind) — 캐시 ◐ · 시연용 고정 ⚑ · 합성 ◇ (DSH-17).
            390 에서 긴 배지가 줄을 밀지 않게 칸 폭 안에서 자른다 (27차 검수 R27U-HD-08). */}
        {badges.map((badge) => (
          <SourceBadge key={badge.label} kind={badge.kind} label={loadingText(badge.label, loading)} className="max-w-full overflow-hidden" />
        ))}
        {!graph && <SourceBadge kind="not_run" label="데이터 출처 확인 중" />}
      </div>
    </footer>
  );
}
