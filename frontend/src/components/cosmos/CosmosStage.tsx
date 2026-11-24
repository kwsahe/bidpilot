"use client";

/**
 * 중앙 스테이지. 뷰 모드(3D / 2D / 목록)와 WebGL 지원 여부, 3D 런타임 오류에 따라 렌더러를 고른다.
 * Cosmos3D는 next/dynamic(ssr:false)로만 불러오고, 오류 시 ErrorBoundary가 Cosmos2D로 대체한다.
 */

import dynamic from "next/dynamic";
import { Component, type ReactNode } from "react";

import Cosmos2D from "@/components/cosmos/Cosmos2D";
import NodeList from "@/components/cosmos/NodeList";
import type { CosmosViewMode, CosmosViewProps } from "@/components/cosmos/types";
import { Button, Spinner } from "@/components/ui/primitives";

const Cosmos3D = dynamic<CosmosViewProps>(
  () => import("@/components/cosmos/three/Cosmos3D"),
  {
    ssr: false,
    loading: () => <StagePlaceholder label="3D 뷰를 불러오는 중" />,
  },
);

export interface CosmosStageProps extends CosmosViewProps {
  viewMode: CosmosViewMode;
  /** null = 아직 감지 전 */
  webglSupported: boolean | null;
  /** 요구사항이 0건일 때 */
  empty: boolean;
  analyzing: boolean;
  onAnalyze: () => void;
}

function StagePlaceholder({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="flex h-full w-full items-center justify-center">
      <div className="flex items-center gap-3 rounded-full border border-cosmos-border bg-cosmos-panel px-4 py-2 text-[13px] text-cosmos-secondary backdrop-blur">
        <Spinner />
        {label}
      </div>
    </div>
  );
}

function FallbackChip({ children }: { children: ReactNode }) {
  return (
    <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-full border border-cosmos-amber/50 bg-cosmos-panel px-3 py-1 text-[13px] text-cosmos-amber backdrop-blur">
      {children}
    </div>
  );
}

interface BoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

interface BoundaryState {
  failed: boolean;
}

/** 3D 렌더러 런타임 오류를 잡아 2D로 대체한다. */
class ThreeErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export default function CosmosStage(props: CosmosStageProps) {
  const { viewMode, webglSupported, empty, analyzing, onAnalyze, ...view } = props;

  if (empty) {
    return (
      <div className="flex h-full w-full items-center justify-center p-6">
        <div className="mc-panel max-w-sm p-6 text-center">
          <p className="text-[15px] font-semibold text-cosmos-text">요구사항이 없습니다</p>
          <p className="mt-2 text-[13px] leading-6 text-cosmos-secondary">
            {view.graph.source.origin.kind === "demo"
              ? "제안요청서에서 뽑은 요구사항이 비어 있습니다. 「공고 분석 시작」을 누르면 가상 예시 제안요청서를 다시 읽어 요구사항을 만듭니다."
              : "이 공고의 제안요청서를 아직 읽지 않았습니다. 위 「공고 분석 시작」을 누르면 요구사항을 뽑습니다."}
          </p>
          {/* 상단 단추와 같은 이름 (DSH-05) — 요구사항이 0건이라 확인 없이 바로 돈다 */}
          <Button variant="primary" className="mt-4" onClick={onAnalyze} disabled={analyzing}>
            {analyzing ? "분석 중…" : "공고 분석 시작"}
          </Button>
        </div>
      </div>
    );
  }

  if (viewMode === "list") {
    return (
      <NodeList
        graph={view.graph}
        stage={view.stage}
        selectedId={view.selectedId}
        onSelect={view.onSelect}
        onStation={view.onStation}
      />
    );
  }

  if (viewMode === "2d") {
    return <Cosmos2D {...view} />;
  }

  if (webglSupported === null) {
    return <StagePlaceholder label="렌더러를 준비하는 중" />;
  }

  if (!webglSupported) {
    return (
      <>
        <FallbackChip>3D를 사용할 수 없어 2D로 표시</FallbackChip>
        <Cosmos2D {...view} />
      </>
    );
  }

  return (
    <ThreeErrorBoundary
      fallback={
        <>
          <FallbackChip>3D를 사용할 수 없어 2D로 표시</FallbackChip>
          <Cosmos2D {...view} />
        </>
      }
    >
      <Cosmos3D {...view} />
    </ThreeErrorBoundary>
  );
}
