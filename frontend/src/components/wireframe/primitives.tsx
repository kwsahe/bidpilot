"use client";

/**
 * 와이어프레임 UI 키트.
 *
 * 이 화면은 "아직 디자인이 확정되지 않은 설계 단계 목업"처럼 보이는 것이 목적이다.
 * 그래서 색·그림자·둥근 모서리를 쓰지 않고 회색조 + 손그림 테두리 + 주석만 쓴다.
 *
 * 표기 규칙 (화면 하단 범례와 동일)
 *  - 회색 블록/빗금  : 아직 만들지 않은 영역 (placeholder)
 *  - 파란 표시       : 실제 backend 응답에서 온 값
 *  - 빨간 글씨       : 검토 주석 (구현 상태·주의사항)
 *
 * 손그림 테두리는 SVG feTurbulence + feDisplacementMap 필터를 배경 레이어(::before)에만
 * 걸어서 만든다. 글자는 필터 밖에 있어 항상 또렷하다.
 * globals.css는 Evidence Cosmos와 공유하는 계약 파일이라 여기 스타일은 이 파일에만 둔다.
 */

import { SYNTHETIC_NOTICE } from "@/lib/terms";
import type { CSSProperties, ReactNode } from "react";

// ---------------------------------------------------------------------------
// 스타일 (이 화면 전용)
// ---------------------------------------------------------------------------

const WIREFRAME_CSS = `
.wf-root {
  --wf-paper: #f2f1ed;
  --wf-surface: #ffffff;
  --wf-ink: #1f1f1e;
  --wf-ink-2: #5c5c57;
  --wf-ink-3: #8d8d86;
  --wf-line: #b8b8b1;
  --wf-line-strong: #6e6e68;
  --wf-fill: #e3e2dc;
  --wf-fill-2: #d2d1c9;
  --wf-red: #bf3b30;
  --wf-blue: #2f5d8c;

  color: var(--wf-ink);
  /* 한글은 어절 단위로 끊고, 넘치는 긴 영문 토큰(API 경로·문서명)만 예외로 쪼갠다. */
  word-break: keep-all;
  overflow-wrap: break-word;
  background-color: var(--wf-paper);
  background-image:
    linear-gradient(to right, rgba(31, 31, 30, 0.05) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(31, 31, 30, 0.05) 1px, transparent 1px),
    linear-gradient(to right, rgba(31, 31, 30, 0.032) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(31, 31, 30, 0.032) 1px, transparent 1px);
  background-size: 96px 96px, 96px 96px, 16px 16px, 16px 16px;
}

/* 목차 앵커로 이동할 때 상단 도구막대에 가리지 않게 한다. */
.wf-root [id^="wf-panel-"] { scroll-margin-top: 86px; }

/* --- 손그림 상자 ---------------------------------------------------------- */
.wf-box { position: relative; }
.wf-box > * { position: relative; z-index: 1; }
.wf-box::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 0;
  background: var(--wf-surface);
  border: 1.5px solid var(--wf-line-strong);
  filter: url(#wf-rough-a);
  pointer-events: none;
}
.wf-box--b::before { filter: url(#wf-rough-b); }
.wf-box--flat::before { background: transparent; }
.wf-box--dashed::before { border-style: dashed; border-color: var(--wf-line); }
.wf-box--thin::before { border-width: 1px; border-color: var(--wf-line); }

/* --- 글자 ----------------------------------------------------------------- */
.wf-mono {
  font-family: var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace;
}
/*
 * 라벨은 대문자 변환하지 않는다. 이 클래스는 API 경로·문서명·RFP 원문 인용에도 쓰이는데
 * text-transform으로 글자를 바꾸면 근거가 원문과 달라진다 (CLAUDE.md §11).
 */
.wf-label {
  font-family: var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--wf-ink-3);
}
.wf-title { font-size: 13.5px; font-weight: 700; letter-spacing: -0.01em; }
.wf-body { font-size: 12.5px; line-height: 1.75; color: var(--wf-ink-2); }
.wf-note { font-size: 11.5px; line-height: 1.7; color: var(--wf-red); }
.wf-live { color: var(--wf-blue); font-weight: 600; }

/* --- 번호 동그라미 --------------------------------------------------------- */
.wf-num {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: none;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-geist-mono), ui-monospace, monospace;
}
.wf-num::before {
  content: "";
  position: absolute;
  inset: 0;
  border: 1.5px solid var(--wf-ink);
  border-radius: 50%;
  filter: url(#wf-rough-b);
}

/* --- 상태 스탬프 ----------------------------------------------------------- */
.wf-stamp {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  font-family: var(--font-geist-mono), ui-monospace, monospace;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  white-space: nowrap;
  transform: rotate(-1.8deg);
}
.wf-stamp::before {
  content: "";
  position: absolute;
  inset: 0;
  border: 1.5px solid currentColor;
  filter: url(#wf-rough-b);
}
.wf-stamp--live { color: var(--wf-blue); }
.wf-stamp--todo { color: var(--wf-red); }
.wf-stamp--partial { color: var(--wf-ink-2); }
.wf-stamp--demo { color: var(--wf-ink-3); }

/* --- 자리표시 블록 --------------------------------------------------------- */
.wf-bar { display: block; height: 9px; background: var(--wf-fill); }
.wf-bar--dark { background: var(--wf-fill-2); }
.wf-hatch {
  background-image: repeating-linear-gradient(
    45deg,
    transparent 0 5px,
    rgba(31, 31, 30, 0.09) 5px 6px
  );
}
.wf-xbox {
  border: 1px solid var(--wf-line);
  background-image:
    linear-gradient(to top right, transparent calc(50% - 0.5px), var(--wf-line) calc(50% - 0.5px), var(--wf-line) calc(50% + 0.5px), transparent calc(50% + 0.5px)),
    linear-gradient(to bottom right, transparent calc(50% - 0.5px), var(--wf-line) calc(50% - 0.5px), var(--wf-line) calc(50% + 0.5px), transparent calc(50% + 0.5px));
}
.wf-pulse { animation: wf-pulse 1.6s ease-in-out infinite; }
@keyframes wf-pulse { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }

/* --- 칩 / 표 / 버튼 -------------------------------------------------------- */
.wf-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--wf-line);
  padding: 1px 6px;
  font-family: var(--font-geist-mono), ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--wf-ink-2);
  white-space: nowrap;
}
.wf-chip--fill { background: var(--wf-fill); }
.wf-chip--ink { border-color: var(--wf-line-strong); color: var(--wf-ink); }
.wf-chip--blue { border-color: var(--wf-blue); color: var(--wf-blue); }
.wf-chip--red { border-color: var(--wf-red); color: var(--wf-red); }

.wf-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.wf-table th {
  font-family: var(--font-geist-mono), ui-monospace, monospace;
  font-size: 9.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--wf-ink-3);
  text-align: left;
  font-weight: 500;
  padding: 4px 6px;
  border-bottom: 1.5px solid var(--wf-line-strong);
  white-space: nowrap;
}
.wf-table td {
  padding: 5px 6px;
  border-bottom: 1px solid var(--wf-line);
  color: var(--wf-ink-2);
  vertical-align: top;
}
.wf-table tr:last-child td { border-bottom: none; }

.wf-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  font-family: var(--font-geist-mono), ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--wf-ink);
  background: transparent;
  cursor: pointer;
}
.wf-btn::before {
  content: "";
  position: absolute;
  inset: 0;
  background: var(--wf-surface);
  border: 1.5px solid var(--wf-line-strong);
  filter: url(#wf-rough-b);
}
.wf-btn > * { position: relative; }
.wf-btn:hover::before { background: var(--wf-fill); }
.wf-btn:disabled { color: var(--wf-ink-3); cursor: not-allowed; }
.wf-btn:disabled::before { border-color: var(--wf-line); background: transparent; }
.wf-btn:focus-visible { outline: 2px solid var(--wf-blue); outline-offset: 2px; }

.wf-select {
  width: 100%;
  appearance: none;
  background: transparent;
  border: none;
  padding: 6px 26px 6px 9px;
  font-size: 12px;
  color: var(--wf-ink);
  cursor: pointer;
}
.wf-select:focus-visible { outline: 2px solid var(--wf-blue); outline-offset: 1px; }

/* --- 게이지 --------------------------------------------------------------- */
.wf-gauge { position: relative; height: 12px; border: 1px solid var(--wf-line-strong); }
.wf-gauge > i {
  display: block;
  height: 100%;
  background-color: var(--wf-fill-2);
  background-image: repeating-linear-gradient(
    45deg,
    transparent 0 4px,
    rgba(31, 31, 30, 0.16) 4px 5px
  );
}
`;

/** 손그림 테두리용 SVG 필터. 페이지에 한 번만 렌더한다. */
function RoughFilters() {
  return (
    <svg
      width="0"
      height="0"
      aria-hidden="true"
      focusable="false"
      style={{ position: "absolute" }}
    >
      <defs>
        <filter id="wf-rough-a" x="-3%" y="-3%" width="106%" height="106%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.016"
            numOctaves={2}
            seed={7}
            result="n"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="n"
            scale={2.6}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
        <filter id="wf-rough-b" x="-6%" y="-6%" width="112%" height="112%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.05"
            numOctaves={2}
            seed={19}
            result="n"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="n"
            scale={1.6}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>
  );
}

/** 스타일 + 필터 정의. 와이어프레임 화면 최상단에 한 번 놓는다. */
export function WireframeStyles() {
  return (
    <>
      <style>{WIREFRAME_CSS}</style>
      <RoughFilters />
    </>
  );
}

// ---------------------------------------------------------------------------
// 프리미티브
// ---------------------------------------------------------------------------

export type StampKind = "live" | "partial" | "todo" | "demo";

const STAMP_TEXT: Record<StampKind, string> = {
  live: "실데이터 연결",
  partial: "부분 구현",
  todo: "미구현",
  demo: SYNTHETIC_NOTICE,
};

/** 패널 구현 상태 스탬프. */
export function Stamp({ kind, text }: { kind: StampKind; text?: string }) {
  return (
    <span className={`wf-stamp wf-stamp--${kind}`}>{text ?? STAMP_TEXT[kind]}</span>
  );
}

export type PanelSpan = 4 | 6 | 8 | 12;

const SPAN_CLASS: Record<PanelSpan, string> = {
  4: "lg:col-span-4",
  6: "lg:col-span-6",
  8: "lg:col-span-8",
  12: "lg:col-span-12",
};

export interface PanelProps {
  /** 화면 좌측 목차와 맞춘 번호 */
  index: number;
  title: string;
  /** 이 패널을 채우는 backend 엔드포인트 (없으면 "미정") */
  source: string;
  status: StampKind;
  span?: PanelSpan;
  /** 하단 빨간 검토 주석 */
  note?: ReactNode;
  children: ReactNode;
}

/** 번호·제목·데이터출처·구현상태를 머리에 붙인 손그림 패널. */
export function Panel({
  index,
  title,
  source,
  status,
  span = 6,
  note,
  children,
}: PanelProps) {
  return (
    <section
      id={`wf-panel-${index}`}
      className={`wf-box col-span-1 flex flex-col p-4 ${SPAN_CLASS[span]}`}
    >
      <header className="mb-3 flex items-start gap-2.5">
        <span className="wf-num" aria-hidden="true">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="wf-title">{title}</h2>
          <p className="wf-label mt-1 truncate" title={source}>
            SRC: {source}
          </p>
        </div>
        <Stamp kind={status} />
      </header>

      <div className="flex min-w-0 flex-1 flex-col gap-3">{children}</div>

      {note ? (
        <p className="wf-note mt-3 border-t border-dashed border-[var(--wf-line)] pt-2">
          <span aria-hidden="true">↳ </span>
          {note}
        </p>
      ) : null}
    </section>
  );
}

/** 회색 자리표시 막대 하나. */
export function Bar({
  width = "100%",
  dark = false,
  className = "",
}: {
  width?: string;
  dark?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`wf-bar ${dark ? "wf-bar--dark" : ""} ${className}`}
      style={{ width }}
    />
  );
}

/** 아직 만들지 않은 텍스트 영역 — 폭이 다른 회색 막대 여러 줄. */
export function BarLines({
  lines = 3,
  pulse = false,
}: {
  lines?: number;
  pulse?: boolean;
}) {
  const widths = ["100%", "86%", "94%", "72%", "90%", "64%"];
  return (
    <span
      aria-hidden="true"
      className={`flex flex-col gap-1.5 ${pulse ? "wf-pulse" : ""}`}
    >
      {Array.from({ length: lines }, (_, i) => (
        <Bar key={i} width={widths[i % widths.length]} />
      ))}
    </span>
  );
}

/** X가 그어진 빈 상자 — 아직 없는 컴포넌트 자리. */
export function XBox({
  height = 72,
  label,
}: {
  height?: number;
  label?: string;
}) {
  return (
    <div
      className="wf-xbox flex items-center justify-center"
      style={{ height }}
      aria-hidden="true"
    >
      {label ? <span className="wf-label">{label}</span> : null}
    </div>
  );
}

/** 빗금 친 영역 — "설계만 되어 있고 아직 동작하지 않음". */
export function Hatch({
  height = 56,
  label,
}: {
  height?: number;
  label?: string;
}) {
  return (
    <div
      className="wf-hatch flex items-center justify-center border border-dashed border-[var(--wf-line)]"
      style={{ height }}
    >
      {label ? <span className="wf-label">{label}</span> : null}
    </div>
  );
}

export type ChipTone = "default" | "fill" | "ink" | "blue" | "red";

const CHIP_CLASS: Record<ChipTone, string> = {
  default: "",
  fill: "wf-chip--fill",
  ink: "wf-chip--ink",
  blue: "wf-chip--blue",
  red: "wf-chip--red",
};

export function Chip({
  children,
  tone = "default",
  title,
}: {
  children: ReactNode;
  tone?: ChipTone;
  title?: string;
}) {
  return (
    <span className={`wf-chip ${CHIP_CLASS[tone]}`} title={title}>
      {children}
    </span>
  );
}

/**
 * 라벨 · 값 한 줄.
 * `live`면 값이 실제 backend 응답이라는 뜻으로 파랗게 표시한다.
 */
export function Field({
  label,
  value,
  live = false,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  live?: boolean;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="wf-label w-[86px] shrink-0">{label}</span>
      <span
        className={`min-w-0 flex-1 text-[12px] leading-6 ${mono ? "wf-mono" : ""} ${
          live ? "wf-live" : "text-[var(--wf-ink-2)]"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

/** 값이 아직 없을 때 쓰는 표시. 숫자를 지어내지 않는다. */
export function NotRun({ children = "미실행" }: { children?: ReactNode }) {
  return (
    <span className="wf-mono text-[12px] tracking-wider text-[var(--wf-ink-3)]">
      {children}
    </span>
  );
}

/** 비율 게이지 (0~1). 수치는 반드시 옆에 그대로 적는다. */
export function Gauge({
  ratio,
  caption,
}: {
  ratio: number;
  caption: ReactNode;
}) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  return (
    <div className="flex flex-col gap-1">
      <div className="wf-gauge">
        <i style={{ width: `${pct}%` }} />
      </div>
      <span className="wf-mono text-[12px] text-[var(--wf-ink-2)]">
        {caption}
      </span>
    </div>
  );
}

/** 와이어프레임 체크박스 (표시 전용 — 동작하지 않는다). */
export function Check({
  checked = false,
  children,
}: {
  checked?: boolean;
  children: ReactNode;
}) {
  return (
    <span className="flex items-start gap-2 text-[12px] leading-6 text-[var(--wf-ink-2)]">
      <span
        aria-hidden="true"
        className="mt-1 flex h-3 w-3 shrink-0 items-center justify-center border border-[var(--wf-line-strong)] text-[12px] leading-none"
      >
        {checked ? "×" : ""}
      </span>
      <span className="min-w-0">{children}</span>
    </span>
  );
}

/** 손그림 테두리를 두른 버튼. */
export function SketchButton({
  children,
  onClick,
  disabled = false,
  style,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  style?: CSSProperties;
}) {
  return (
    <button
      type="button"
      className="wf-btn"
      onClick={onClick}
      disabled={disabled}
      style={style}
    >
      <span>{children}</span>
    </button>
  );
}
