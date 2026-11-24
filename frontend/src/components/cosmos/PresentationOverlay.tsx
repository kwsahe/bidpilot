"use client";

/**
 * 발표 모드 하단 오버레이: 장면 번호 · 제목 · 캡션 · 진행 바 · 이전/재생/다음/종료.
 */

import type { CosmosGraph } from "@/lib/cosmos/graph";
import type { PresentationController } from "@/lib/cosmos/usePresentation";

export interface PresentationOverlayProps {
  controller: PresentationController;
  graph: CosmosGraph;
  reducedMotion: boolean;
}

const CONTROL_CLASS =
  "rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2.5 py-1 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan disabled:cursor-not-allowed disabled:opacity-40";

export default function PresentationOverlay({ controller, graph, reducedMotion }: PresentationOverlayProps) {
  const { scene, index, total, playing, isFirst, isLast } = controller;
  if (!scene) return null;

  const caption = scene.caption(graph);

  return (
    <div
      role="region"
      aria-label="발표 모드"
      className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-center p-3"
    >
      <div className="pointer-events-auto w-full max-w-3xl overflow-hidden rounded-xl border border-cosmos-border bg-cosmos-panel shadow-[0_18px_48px_var(--cosmos-shadow)] backdrop-blur">
        <div className="flex items-start gap-4 px-4 pt-3">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-cyan">
              <span className="font-mono tabular-nums">
                {index + 1}/{total}
              </span>
              <span aria-hidden="true" className="text-cosmos-muted">·</span>
              <span className="text-cosmos-muted">장면</span>
            </p>
            <h2 className="mt-0.5 text-[16px] font-semibold text-cosmos-text" aria-live="polite">
              {scene.title}
            </h2>
            <p className="mt-1 text-[13px] leading-6 text-cosmos-secondary">{caption}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 pt-1">
            <button
              type="button"
              onClick={controller.prev}
              disabled={isFirst}
              className={CONTROL_CLASS}
              aria-label="이전 장면 (←)"
            >
              ←
            </button>
            <button
              type="button"
              onClick={controller.togglePlay}
              className={CONTROL_CLASS}
              aria-label={playing ? "일시정지 (Space)" : "재생 (Space)"}
              aria-pressed={playing}
            >
              {playing ? "일시정지" : isLast ? "다시 재생" : "재생"}
            </button>
            <button
              type="button"
              onClick={controller.next}
              disabled={isLast}
              className={CONTROL_CLASS}
              aria-label="다음 장면 (→)"
            >
              →
            </button>
            <button
              type="button"
              onClick={controller.exit}
              className={`${CONTROL_CLASS} border-cosmos-red/40 text-cosmos-red hover:border-cosmos-red/70`}
              aria-label="발표 종료 (Esc)"
            >
              종료
            </button>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3 px-4 pb-3">
          <div
            className="h-1 flex-1 overflow-hidden rounded-full bg-cosmos-slate/60"
            role="progressbar"
            aria-label="장면 진행"
            aria-valuemin={1}
            aria-valuemax={total}
            aria-valuenow={index + 1}
          >
            {reducedMotion || !playing ? (
              // 감속 모드·일시정지: 장면 위치만 정적으로 표시
              <div
                className={`h-full rounded-full bg-cosmos-cyan ${playing ? "" : "opacity-50"}`}
                style={{ width: `${((index + 1) / total) * 100}%` }}
              />
            ) : (
              // 재생 중: 장면 길이에 맞춰 0→100% (재생 재개 시 타이머와 함께 처음부터)
              <div
                key={index}
                className="h-full rounded-full bg-cosmos-cyan"
                style={{
                  animation: `cosmos-scene-progress ${scene.durationMs}ms linear forwards`,
                }}
              />
            )}
          </div>
          <p className="shrink-0 font-mono text-[12px] tabular-nums text-cosmos-muted">
            ← → 이동 · Space 재생/정지 · Esc 종료
          </p>
        </div>
      </div>
    </div>
  );
}
