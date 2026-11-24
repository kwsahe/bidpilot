"use client";

/**
 * 실행 타임라인 — "AI가 지금 무엇을 하고 있는지".
 * useCosmosDashboard.runLog(실제 요청 상태)만 그린다. 실행하지 않은 단계는 완료로 표시하지 않고
 * 「건너뜀(사유)」 또는 「데모 시나리오」로 구분한다.
 *
 *  - Strip: 분석 실행 중 스테이지 위에 겹치는 가로 칩 (짧고 절제된 연출)
 *  - List : 상세 패널 개요의 실행 기록
 */

import { Spinner } from "@/components/ui/primitives";
import {
  RUN_PHASE_LABELS,
  RUN_PHASE_ORDER,
  type RunLog,
  type RunPhase,
  type RunPhaseStatus,
} from "@/lib/cosmos/useCosmosDashboard";
import { COSMOS_COLORS, withAlpha } from "@/lib/cosmos/theme";
import { SYNTHETIC_NOTICE } from "@/lib/terms";

const STATUS_META: Record<RunPhaseStatus, { glyph: string; color: string; label: string }> = {
  pending: { glyph: "○", color: COSMOS_COLORS.slate, label: "대기" },
  running: { glyph: "…", color: COSMOS_COLORS.cyan, label: "실행 중" },
  done: { glyph: "✓", color: COSMOS_COLORS.cyan, label: "완료" },
  // 합성 표시는 ◇ 회청 — 보라 ◆ 는 기업마당 한 뜻 (27차 §3-E · UNI-19).
  demo: { glyph: "◇", color: COSMOS_COLORS.slate, label: SYNTHETIC_NOTICE },
  skipped: { glyph: "–", color: COSMOS_COLORS.slate, label: "건너뜀" },
  failed: { glyph: "✕", color: COSMOS_COLORS.red, label: "실패" },
};

export function runLogSummary(runLog: RunLog): { running: number; done: number; failed: number } {
  let running = 0;
  let done = 0;
  let failed = 0;
  for (const key of RUN_PHASE_ORDER) {
    const status = runLog[key].status;
    if (status === "running") running += 1;
    else if (status === "done" || status === "demo") done += 1;
    else if (status === "failed") failed += 1;
  }
  return { running, done, failed };
}

function PhaseGlyph({ phase, reducedMotion }: { phase: RunPhase; reducedMotion: boolean }) {
  const meta = STATUS_META[phase.status];
  if (phase.status === "running") {
    return <Spinner className={reducedMotion ? "" : ""} />;
  }
  return (
    <span
      aria-hidden="true"
      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[12px] font-bold"
      style={{ color: meta.color, borderColor: withAlpha(meta.color, 47), backgroundColor: withAlpha(meta.color, 10) }}
    >
      {meta.glyph}
    </span>
  );
}

export function RunTimelineStrip({ runLog, reducedMotion }: { runLog: RunLog; reducedMotion: boolean }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="분석 진행"
      // 도구막대 안이라 지도를 가리지 않는다 — pointer-events 를 끄면 칩 툴팁(실패 사유)이 뜨지 않았다 (DSH-25).
      className="flex flex-wrap items-center gap-1.5 rounded-xl border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5 backdrop-blur"
    >
      {RUN_PHASE_ORDER.map((key) => {
        const phase = runLog[key];
        const meta = STATUS_META[phase.status];
        const dim = phase.status === "pending" || phase.status === "skipped";
        return (
          <span
            key={key}
            className={`relative flex items-center gap-1.5 overflow-hidden rounded-full border px-2 py-0.5 text-[12px] ${
              dim ? "text-cosmos-muted" : "text-cosmos-text"
            }`}
            style={{ borderColor: dim ? "var(--cosmos-border)" : withAlpha(meta.color, 40) }}
            title={phase.detail ?? meta.label}
          >
            <PhaseGlyph phase={phase} reducedMotion={reducedMotion} />
            <span className="whitespace-nowrap">{RUN_PHASE_LABELS[key]}</span>
            {phase.status === "running" && !reducedMotion && (
              <span
                aria-hidden="true"
                className="absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-cosmos-cyan/25 to-transparent"
                style={{ animation: "mc-scan 1.4s ease-in-out infinite" }}
              />
            )}
          </span>
        );
      })}
    </div>
  );
}

export function RunTimelineList({ runLog, reducedMotion }: { runLog: RunLog; reducedMotion: boolean }) {
  return (
    <ol className="flex flex-col gap-1" aria-label="실행 기록">
      {RUN_PHASE_ORDER.map((key, index) => {
        const phase = runLog[key];
        const meta = STATUS_META[phase.status];
        return (
          <li key={key} className="flex items-start gap-2.5 rounded-lg px-1 py-1">
            <span className="flex flex-col items-center gap-1 pt-0.5">
              <PhaseGlyph phase={phase} reducedMotion={reducedMotion} />
              {index < RUN_PHASE_ORDER.length - 1 && (
                <span aria-hidden="true" className="h-3 w-px bg-cosmos-border" />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline justify-between gap-2">
                <span className="text-[12.5px] font-medium text-cosmos-text">{RUN_PHASE_LABELS[key]}</span>
                <span className="shrink-0 text-[12px] font-medium" style={{ color: meta.color }}>
                  {meta.label}
                </span>
              </span>
              {phase.detail && (
                <span className="block truncate text-[12px] text-cosmos-secondary" title={phase.detail}>
                  {phase.detail}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
