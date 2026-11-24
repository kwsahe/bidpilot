"use client";

/**
 * 튜토리얼 코치마크 오버레이.
 *
 * - 전체 화면을 살짝 어둡게 하고, 현재 단계의 대상 요소(data-tour)만 둥근 구멍으로 남긴다 (SVG mask).
 * - 어두운 층은 pointer-events: none 이라 사용자가 실제 UI를 눌러 과제를 수행할 수 있다.
 * - 대상 위치는 단계 변경·창 크기 변경·requestAnimationFrame 루프에서 다시 잰다 (3D/패널이 움직일 수 있음).
 *   측정 결과 setState는 항상 rAF 콜백에서만 일어나고, 값이 바뀌었을 때만 갱신한다.
 * - 작은 화면(768px 미만)에서는 카드가 아래(또는 위) 시트로 바뀐다.
 */

import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";

import type { CosmosGraph } from "@/lib/cosmos/graph";
import { COSMOS_COLORS, withAlpha } from "@/lib/cosmos/theme";
import { resolveText, type TutorialPlacement, type TutorialStep } from "@/lib/cosmos/tutorial";
import type { TutorialController } from "@/lib/cosmos/useTutorial";

export interface TutorialOverlayProps {
  controller: TutorialController;
  graph: CosmosGraph;
  reducedMotion: boolean;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Layout {
  vw: number;
  vh: number;
  /** 대상 요소들의 합집합 사각형. 대상이 없거나 화면에 없으면 null */
  rect: Rect | null;
  cardW: number;
  cardH: number;
}

const CARD_WIDTH = 400;
const GAP = 14;
const MARGIN = 12;
const CUTOUT_PADDING = 6;
const CUTOUT_RADIUS = 12;
const SHEET_BREAKPOINT = 768;

const BUTTON_CLASS =
  "rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan disabled:cursor-not-allowed disabled:opacity-40";

function sameLayout(a: Layout | null, b: Layout): boolean {
  if (!a) return false;
  if (a.vw !== b.vw || a.vh !== b.vh || a.cardW !== b.cardW || a.cardH !== b.cardH) return false;
  if (a.rect === null || b.rect === null) return a.rect === b.rect;
  return a.rect.x === b.rect.x && a.rect.y === b.rect.y && a.rect.w === b.rect.w && a.rect.h === b.rect.h;
}

function measureTargets(ids: readonly string[]): Rect | null {
  let union: Rect | null = null;
  for (const id of ids) {
    const element = document.querySelector(`[data-tour="${id}"]`);
    if (!element) continue;
    const r = element.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const x = Math.round(r.left);
    const y = Math.round(r.top);
    const right = Math.round(r.right);
    const bottom = Math.round(r.bottom);
    if (!union) {
      union = { x, y, w: right - x, h: bottom - y };
    } else {
      const nx = Math.min(union.x, x);
      const ny = Math.min(union.y, y);
      const nr = Math.max(union.x + union.w, right);
      const nb = Math.max(union.y + union.h, bottom);
      union = { x: nx, y: ny, w: nr - nx, h: nb - ny };
    }
  }
  return union;
}

type ResolvedPlacement = "right" | "left" | "top" | "bottom" | "inside";

function resolvePlacement(layout: Layout, rect: Rect, requested: TutorialPlacement): ResolvedPlacement {
  const { vw, vh, cardW, cardH } = layout;
  const space = {
    right: vw - (rect.x + rect.w),
    left: rect.x,
    bottom: vh - (rect.y + rect.h),
    top: rect.y,
  };
  const fits = (p: "right" | "left" | "top" | "bottom") =>
    p === "right" || p === "left" ? space[p] >= cardW + GAP + MARGIN : space[p] >= cardH + GAP + MARGIN;

  if (requested !== "auto" && fits(requested)) return requested;

  // 대상이 화면 대부분을 차지하면(중앙 스테이지) 그 안쪽 오른쪽 위(5단계 안내 바 아래)에 둔다 — 하단 범례·Caption Bar를 가리지 않는다.
  if (rect.w > vw * 0.45 && rect.h > vh * 0.45) return "inside";

  const order: Array<"right" | "left" | "bottom" | "top"> = ["right", "left", "bottom", "top"];
  for (const p of order) if (fits(p)) return p;
  return order.reduce((best, p) => (space[p] > space[best] ? p : best), order[0]);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function cardStyle(layout: Layout | null, step: TutorialStep): CSSProperties {
  const base: CSSProperties = { position: "fixed", width: CARD_WIDTH, maxWidth: "calc(100vw - 24px)" };
  if (!layout) return { ...base, left: MARGIN, top: MARGIN, visibility: "hidden" };

  const { vw, vh, rect, cardW, cardH } = layout;
  const maxHeight = vh - MARGIN * 2;

  if (vw < SHEET_BREAKPOINT) {
    const nearBottom = rect ? rect.y + rect.h / 2 > vh / 2 : false;
    return {
      position: "fixed",
      left: 0,
      right: 0,
      width: "auto",
      maxWidth: "none",
      maxHeight: "55vh",
      ...(nearBottom ? { top: 0 } : { bottom: 0 }),
    };
  }

  if (!rect) {
    return {
      ...base,
      left: Math.round((vw - Math.min(cardW || CARD_WIDTH, vw)) / 2),
      top: Math.max(MARGIN, Math.round((vh - cardH) / 2)),
      maxHeight,
    };
  }

  const placement = resolvePlacement(layout, rect, step.placement ?? "auto");
  let left = 0;
  let top = 0;
  switch (placement) {
    case "right":
      left = rect.x + rect.w + GAP;
      top = rect.y;
      break;
    case "left":
      left = rect.x - GAP - cardW;
      top = rect.y;
      break;
    case "bottom":
      left = rect.x;
      top = rect.y + rect.h + GAP;
      break;
    case "top":
      left = rect.x;
      top = rect.y - GAP - cardH;
      break;
    case "inside":
      left = rect.x + rect.w - cardW - 16;
      top = rect.y + 72;
      break;
  }
  return {
    ...base,
    left: clamp(left, MARGIN, vw - cardW - MARGIN),
    top: clamp(top, MARGIN, vh - cardH - MARGIN),
    maxHeight,
  };
}

function Backdrop({ layout, maskId, hasTarget }: { layout: Layout | null; maskId: string; hasTarget: boolean }) {
  if (!layout) return null;
  const { vw, vh, rect } = layout;
  const cut = rect
    ? {
        x: rect.x - CUTOUT_PADDING,
        y: rect.y - CUTOUT_PADDING,
        w: rect.w + CUTOUT_PADDING * 2,
        h: rect.h + CUTOUT_PADDING * 2,
      }
    : null;
  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0"
      width={vw}
      height={vh}
      viewBox={`0 0 ${vw} ${vh}`}
    >
      <defs>
        <mask id={maskId} maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" x={0} y={0} width={vw} height={vh}>
          <rect x={0} y={0} width={vw} height={vh} fill="white" />
          {cut && <rect x={cut.x} y={cut.y} width={cut.w} height={cut.h} rx={CUTOUT_RADIUS} fill="black" />}
        </mask>
      </defs>
      <rect
        x={0}
        y={0}
        width={vw}
        height={vh}
        fill={COSMOS_COLORS.bg}
        fillOpacity={hasTarget && cut ? 0.62 : 0.3}
        mask={`url(#${maskId})`}
      />
      {cut && (
        <rect
          x={cut.x}
          y={cut.y}
          width={cut.w}
          height={cut.h}
          rx={CUTOUT_RADIUS}
          fill="none"
          stroke={COSMOS_COLORS.cyan}
          strokeOpacity={0.75}
          strokeWidth={1.5}
        />
      )}
    </svg>
  );
}

function Paragraphs({ items, graph }: { items: readonly (string | ((g: CosmosGraph) => string))[]; graph: CosmosGraph }) {
  return (
    <>
      {items.map((text, i) => (
        <p key={i} className="text-[13px] leading-5 text-cosmos-secondary">
          {resolveText(text, graph)}
        </p>
      ))}
    </>
  );
}

function TaskBox({
  step,
  graph,
  done,
  onDoTask,
}: {
  step: TutorialStep;
  graph: CosmosGraph;
  done: boolean;
  onDoTask: () => void;
}) {
  const task = step.task;
  if (!task) return null;
  const tone = done ? COSMOS_COLORS.cyan : COSMOS_COLORS.amber;
  return (
    <div
      className="rounded-lg border px-3 py-2.5"
      style={{ borderColor: withAlpha(tone, 40), backgroundColor: withAlpha(tone, 8) }}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.14em]" style={{ color: tone }}>
          직접 해보기
        </p>
        <span className="text-[12px] font-semibold" style={{ color: tone }} aria-live="polite">
          {done ? "✓ 완료" : "대기 중"}
        </span>
      </div>
      <p className="mt-1 text-[13px] leading-5 text-cosmos-text">{resolveText(task.instruction, graph)}</p>
      {task.hint && <p className="mt-1 text-[12px] leading-4 text-cosmos-muted">{resolveText(task.hint, graph)}</p>}
      {task.doItForMe && !done && (
        <button type="button" onClick={onDoTask} className={`${BUTTON_CLASS} mt-2`}>
          대신 해주기
        </button>
      )}
    </div>
  );
}

function Dots({ total, index, onGoTo }: { total: number; index: number; onGoTo: (i: number) => void }) {
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="튜토리얼 단계">
      {Array.from({ length: total }, (_, i) => {
        const current = i === index;
        const past = i < index;
        return (
          <li key={i}>
            <button
              type="button"
              onClick={() => onGoTo(i)}
              aria-label={`${i + 1}단계로 이동`}
              aria-current={current ? "step" : undefined}
              className="flex h-4 items-center rounded-full px-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            >
              <span
                aria-hidden="true"
                className={`block h-1.5 rounded-full ${current ? "w-4" : "w-1.5"}`}
                style={{
                  backgroundColor: current ? COSMOS_COLORS.cyan : past ? withAlpha(COSMOS_COLORS.cyan, 53) : COSMOS_COLORS.slate,
                }}
              />
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export default function TutorialOverlay({ controller, graph, reducedMotion }: TutorialOverlayProps) {
  const { step, index, total, taskDone, isFirst, isLast } = controller;
  const [layout, setLayout] = useState<Layout | null>(null);
  const layoutRef = useRef<Layout | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const maskId = useId();
  const headingId = useId();

  const targetIds = step ? [step.target, ...(step.extraTargets ?? [])].filter((t): t is NonNullable<typeof t> => t !== null) : [];
  const targetKey = targetIds.join("|");

  const measure = useCallback(() => {
    const ids = targetKey ? targetKey.split("|") : [];
    const card = cardRef.current?.getBoundingClientRect();
    const next: Layout = {
      vw: window.innerWidth,
      vh: window.innerHeight,
      rect: ids.length > 0 ? measureTargets(ids) : null,
      cardW: card ? Math.round(card.width) : 0,
      cardH: card ? Math.round(card.height) : 0,
    };
    if (!sameLayout(layoutRef.current, next)) {
      layoutRef.current = next;
      setLayout(next);
    }
  }, [targetKey]);

  // 위치 측정: rAF 루프 + resize/scroll. setState는 콜백에서만 일어난다.
  useEffect(() => {
    if (!step) return;
    let frame = 0;
    const loop = () => {
      measure();
      frame = window.requestAnimationFrame(loop);
    };
    frame = window.requestAnimationFrame(loop);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step, measure]);

  // 단계가 바뀌면 카드 제목에 포커스 (스크롤 없이)
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [index]);

  if (!step) return null;

  const isSheet = layout !== null && layout.vw < SHEET_BREAKPOINT;
  const style = cardStyle(layout, step);
  const nextLabel = isLast ? "완료" : "다음";

  let sheetRadius: string;
  if (!isSheet) sheetRadius = "rounded-xl";
  else sheetRadius = style.top === 0 ? "rounded-b-xl" : "rounded-t-xl";

  const bodyContent: ReactNode = (
    <div
      key={index}
      className="flex flex-col gap-3"
      style={reducedMotion ? undefined : { animation: "cosmos-panel-in 200ms ease-out" }}
    >
      <Paragraphs items={step.body} graph={graph} />
      {step.bullets && step.bullets.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
          {step.bullets.map((b, i) => (
            <li key={i} className="flex gap-2 text-[13px] leading-5 text-cosmos-secondary">
              <span aria-hidden="true" className="shrink-0 text-cosmos-cyan">
                ·
              </span>
              <span>{resolveText(b, graph)}</span>
            </li>
          ))}
        </ul>
      )}
      <TaskBox step={step} graph={graph} done={taskDone} onDoTask={controller.doTask} />
    </div>
  );

  return (
    <div className="pointer-events-none fixed inset-0 z-50" data-tutorial-overlay="">
      <Backdrop layout={layout} maskId={maskId} hasTarget={targetIds.length > 0} />

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="false"
        aria-labelledby={headingId}
        style={{ ...style, backgroundColor: "var(--cosmos-overlay)" }}
        className={`pointer-events-auto flex flex-col overflow-hidden border border-cosmos-border bg-cosmos-panel shadow-[0_18px_48px_var(--cosmos-shadow)] backdrop-blur ${sheetRadius}`}
      >
        <div className="flex shrink-0 items-center gap-3 border-b border-cosmos-border px-4 py-2.5">
          <span className="font-mono text-[12px] font-semibold tabular-nums text-cosmos-cyan">
            {index + 1}/{total}
          </span>
          <Dots total={total} index={index} onGoTo={controller.goTo} />
          <button
            type="button"
            onClick={controller.exit}
            aria-label="건너뛰기 — 안내 종료 (Esc)"
            className="ml-auto rounded-md px-2 py-1 text-[12px] text-cosmos-secondary transition-colors hover:text-cosmos-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
          >
            건너뛰기
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
          <h2
            id={headingId}
            ref={headingRef}
            tabIndex={-1}
            className="text-[16px] font-semibold leading-6 text-cosmos-text focus:outline-none"
          >
            {step.title}
          </h2>
          {bodyContent}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-cosmos-border px-4 py-2.5">
          <button type="button" onClick={controller.prev} disabled={isFirst} className={BUTTON_CLASS} aria-label="이전 단계 (←)">
            이전
          </button>
          <button
            type="button"
            onClick={controller.next}
            className="rounded-md bg-cosmos-blue-strong px-3.5 py-1.5 text-[12px] font-semibold text-white transition-[filter] hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            aria-label={isLast ? "튜토리얼 완료" : "다음 단계 (→)"}
          >
            {step.task && taskDone ? `✓ ${nextLabel}` : nextLabel}
          </button>
          <p className="ml-auto font-mono text-[12px] tabular-nums text-cosmos-muted">→ 다음 · ← 이전 · Esc 종료</p>
          {!isFirst && (
            <button
              type="button"
              onClick={() => controller.goTo(0)}
              className="text-[12px] text-cosmos-muted underline-offset-2 transition-colors hover:text-cosmos-text hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            >
              처음부터
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
