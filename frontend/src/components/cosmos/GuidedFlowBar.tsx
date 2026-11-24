"use client";

/**
 * 5단계 화면 이해 안내의 한 줄(Caption Bar) — 지도 아래 도구막대에 놓인다 (21차 · prompt_11 §3-5).
 *
 * 예전에는 지도 위에 5단계 단추 바(GuidedFlowBar)가 따로 있었다. 지도가 이제 8정거장의 길을 이름과 함께 그리므로
 * 그 바를 없앴다 — 「단계가 8개인가 5개인가」를 헷갈리게 했다. 안내는 여기 「5단계 안내 시작」·「다음」으로 남는다.
 */

import { guidedStepDef, type GuidedStep } from "@/lib/cosmos/guidedFlow";
import { STATION_IDS, STATION_NAMES } from "@/lib/cosmos/stations";

// ---------------------------------------------------------------------------
// Caption Bar
// ---------------------------------------------------------------------------

/** 지도가 말하는 한 문장 — 정거장 8개의 이름 그대로 (21차). */
export const STRUCTURE_LINE = STATION_IDS.map((id) => STATION_NAMES[id]).join(" → ");

export interface GuidedCaptionBarProps {
  step: GuidedStep | null;
  onNext: () => void;
  onStart: () => void;
  onExit: () => void;
  /** 정적 배치(모바일, 3D 아래)인지 오버레이인지 */
  inline?: boolean;
}

export function GuidedCaptionBar({ step, onNext, onStart, onExit, inline = false }: GuidedCaptionBarProps) {
  const def = step ? guidedStepDef(step) : null;
  return (
    <div
      data-tour="caption-bar"
      role="status"
      aria-live="polite"
      className={`pointer-events-auto flex w-full items-center gap-x-3 gap-y-1.5 rounded-xl border border-cosmos-border px-3 text-[13px] leading-5 text-cosmos-text backdrop-blur-md ${
        inline ? "min-h-11 flex-wrap py-1 lg:flex-nowrap" : "max-w-3xl flex-wrap py-2 shadow-[0_8px_24px_var(--cosmos-shadow-soft)]"
      }`}
      style={{ backgroundColor: "var(--cosmos-overlay)" }}
    >
      {def ? (
        <>
          <span aria-hidden="true" className="shrink-0 font-semibold text-cosmos-cyan">
            {/* 원문자는 지도 정거장 번호와 헷갈린다 — 「안내 3/5」 꼴 (27차 §3-D-8) */}
            안내 {def.id}/5 · {def.title}
          </span>
          <span className="min-w-0 flex-1 basis-[16rem] truncate text-cosmos-secondary" title={def.caption}>{def.caption}</span>
          <span className="ml-auto flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={onNext}
              className="mc-focus min-h-9 rounded-lg bg-cosmos-blue-strong px-3 text-[12.5px] font-semibold text-white transition-[filter] hover:brightness-110"
            >
              {def.nextLabel}
            </button>
            <button
              type="button"
              onClick={onExit}
              className="mc-focus min-h-9 rounded-lg border border-cosmos-border px-2.5 text-[12px] text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
              title="안내를 끄고 자유롭게 탐색"
            >
              탐색 모드
            </button>
          </span>
        </>
      ) : (
        <>
          <span className="shrink-0 font-semibold text-cosmos-muted">구조</span>
          <span className="min-w-0 flex-1 basis-[14rem] truncate text-cosmos-secondary" title={STRUCTURE_LINE}>{STRUCTURE_LINE}</span>
          <span className="hidden text-[13px] text-cosmos-muted 2xl:inline">단계를 누르면 그 정거장으로 · 드래그 이동 · Ctrl+휠 확대</span>
          <button
            type="button"
            onClick={onStart}
            className="mc-focus min-h-9 shrink-0 rounded-lg border border-cosmos-cyan/50 px-3 text-[12.5px] font-semibold text-cosmos-cyan hover:bg-cosmos-cyan/10"
          >
            5단계 안내 시작
          </button>
        </>
      )}
    </div>
  );
}
