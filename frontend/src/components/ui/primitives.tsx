"use client";

/**
 * Mission Control 공통 프리미티브.
 * 대시보드(/), 공고 탐색(/opportunities), 요구사항 정리표(/rfp)가 같은 배지·섹션 헤더·
 * 빈 상태·로딩 상태를 재사용한다. 색은 theme.ts 토큰만 쓴다.
 * KPI 칸은 둘이다 — 대시보드는 누르면 단계로 가는 `MissionStrip` 타일, 요구사항 정리표 · 지원사업 · 회사자료는
 * `KpiCard`. 제목 글꼴(12px 굵게 · 대문자·자간 없음)과 값 크기(20px)는 둘이 같다 (27차 UNI-22).
 */

import type { CSSProperties, ReactNode } from "react";

import { tintStyle } from "@/lib/cosmos/format";
import { COSMOS_COLORS, TONE_COLORS, withAlpha, type Tone } from "@/lib/cosmos/theme";

export type { Tone };

export const TONE_GLYPH: Record<Tone, string> = {
  ok: "●",
  pass: "✓",
  warn: "!",
  fail: "✕",
  info: "●",
  // 합성 · 데모 — 빈 마름모. 채운 보라 ◆ 는 기업마당(출처)만 뜻한다 (27차 §3-E · UNI-19).
  demo: "◇",
  muted: "○",
};

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

export interface BadgeProps {
  tone?: Tone;
  /** 상태색 hex를 직접 줄 때 (노드 상태색 등) */
  color?: string;
  /** 색 외에 글리프로도 상태를 전달한다 */
  glyph?: boolean | string;
  size?: "sm" | "md";
  mono?: boolean;
  title?: string;
  className?: string;
  children: ReactNode;
}

export function Badge({
  tone = "muted",
  color,
  glyph = false,
  size = "sm",
  mono = false,
  title,
  className = "",
  children,
}: BadgeProps) {
  const hex = color ?? TONE_COLORS[tone];
  const mark = typeof glyph === "string" ? glyph : glyph ? TONE_GLYPH[tone] : null;
  // 합성 · 데모는 색이 아니라 **점선 테두리**로 가른다 — 회청은 「판정 전」과 같은 색이라 모양이 한 번 더 말해야 한다.
  const dashed = !color && tone === "demo";
  return (
    <span
      title={title}
      // 칩 세기 표식 (24차 §4-E · check_visibility 쉬운 보기 표) — SourceBadge 도 이 Badge 를 그린다.
      data-chip
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border font-medium ${
        size === "sm" ? "px-2 py-0.5 text-[12px] leading-4" : "px-2.5 py-1 text-[12px] leading-4"
      } ${mono ? "font-mono tabular-nums" : ""} ${dashed ? "border-dashed" : ""} ${className}`}
      style={tintStyle(hex)}
    >
      {mark && (
        <span aria-hidden="true" className="text-[12px] leading-none">
          {mark}
        </span>
      )}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

export interface KpiCardProps {
  label: string;
  /** 큰 숫자/상태값. 없으면 "분석 전" 같은 문구를 hint로 준다 */
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  tone?: Tone;
  /** 값이 실제 데이터인지 데모/미실행인지 — 카드 우상단 배지 */
  badge?: ReactNode;
  /** 0~1 진행 막대 */
  ratio?: number | null;
  compact?: boolean;
  className?: string;
  dataTour?: string;
}

export function KpiCard({
  label,
  value,
  unit,
  hint,
  tone = "info",
  badge,
  ratio = null,
  compact = false,
  className = "",
  dataTour,
}: KpiCardProps) {
  const color = TONE_COLORS[tone];
  return (
    <div
      data-tour={dataTour}
      className={`mc-panel relative flex min-w-0 flex-col justify-between ${
        compact ? "gap-1 px-3 py-2" : "gap-2 px-4 py-3"
      } ${className}`}
      style={{ borderTopColor: withAlpha(color, 40) } as CSSProperties}
    >
      <div className="flex items-start justify-between gap-2">
        {/* 좁은 칸(390)에서 라벨 · 설명이 한 줄로 잘리고 전체를 볼 길이 없었다 — 두 줄까지 보이고 나머지는 풍선 도움말 (RFP-10 · CMP-27). */}
        <span className="line-clamp-2 min-w-0 text-[12px] font-semibold leading-4 text-cosmos-secondary" title={label}>
          {label}
        </span>
        {badge}
      </div>
      <div className="flex items-baseline gap-1.5">
        <span
          className="font-mono text-[20px] font-semibold tabular-nums leading-none"
          style={{ color }}
        >
          {value}
        </span>
        {unit && <span className="text-[12px] text-cosmos-muted">{unit}</span>}
      </div>
      {ratio !== null && (
        <div className="h-1 overflow-hidden rounded-full bg-cosmos-slate/60" aria-hidden="true">
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: `${Math.round(Math.min(1, Math.max(0, ratio)) * 100)}%`, backgroundColor: color }}
          />
        </div>
      )}
      {hint && (
        <div className="line-clamp-2 text-[12px] leading-4 text-cosmos-secondary" title={typeof hint === "string" ? hint : undefined}>
          {hint}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section header / Panel
// ---------------------------------------------------------------------------

export function SectionHeader({
  eyebrow,
  title,
  description,
  aside,
  as: Tag = "h2",
  id,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  as?: "h1" | "h2" | "h3";
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-cosmos-cyan">{eyebrow}</p>
        )}
        <Tag
          id={id}
          className={`font-semibold tracking-tight text-cosmos-text ${
            Tag === "h1" ? "mt-1 text-[24px] sm:text-[28px]" : Tag === "h2" ? "text-[17px]" : "text-[14px]"
          }`}
        >
          {title}
        </Tag>
        {description && <div className="mt-1 text-[13px] leading-5 text-cosmos-secondary">{description}</div>}
      </div>
      {aside && <div className="flex shrink-0 flex-wrap items-center gap-2">{aside}</div>}
    </div>
  );
}

export function Panel({
  children,
  className = "",
  padded = true,
  as: Tag = "section",
  ariaLabel,
  ariaLabelledBy,
  dataTour,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  as?: "section" | "div" | "aside" | "article";
  ariaLabel?: string;
  ariaLabelledBy?: string;
  dataTour?: string;
}) {
  return (
    <Tag
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      data-tour={dataTour}
      className={`mc-panel min-w-0 ${padded ? "p-4" : ""} ${className}`}
    >
      {children}
    </Tag>
  );
}

// ---------------------------------------------------------------------------
// Empty / Loading / Error
// ---------------------------------------------------------------------------

export function EmptyState({
  title,
  children,
  action,
  tone = "muted",
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-cosmos-border-strong px-5 py-8 text-center"
    >
      <span
        aria-hidden="true"
        className="flex h-8 w-8 items-center justify-center rounded-full border text-[13px] font-bold"
        style={tintStyle(TONE_COLORS[tone])}
      >
        {TONE_GLYPH[tone]}
      </span>
      <p className="text-[14px] font-semibold text-cosmos-text">{title}</p>
      {children && <p className="max-w-md text-[13px] leading-5 text-cosmos-secondary">{children}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "", reducedMotion = false }: { className?: string; reducedMotion?: boolean }) {
  return (
    <div
      aria-hidden="true"
      className={`rounded-lg bg-cosmos-elevated ${className}`}
      style={reducedMotion ? undefined : { animation: "mc-skeleton 1.6s ease-in-out infinite" }}
    />
  );
}

export function LoadingState({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="mc-panel flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2 text-[13px] text-cosmos-secondary">
        <Spinner />
        {label}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`h-9 ${i % 3 === 1 ? "w-3/4" : "w-full"}`} />
      ))}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-cosmos-cyan/30 border-t-cosmos-cyan ${className}`}
      style={{ animation: "mc-spin 0.9s linear infinite" }}
    />
  );
}

export function InlineAlert({
  tone = "warn",
  children,
  role = "alert",
}: {
  tone?: Tone;
  children: ReactNode;
  role?: "alert" | "status";
}) {
  return (
    <p role={role} className={`rounded-lg border px-3 py-2 text-[12px] leading-5 ${tone === "demo" ? "border-dashed" : ""}`} style={tintStyle(TONE_COLORS[tone])}>
      {children}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

/** 채움 단추는 `primary`(파랑) 하나다 — 청록은 상태색(충족 · 가능)이라 단추 면에 쓰지 않는다 (27차 §3-E · UNI-23). */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-cosmos-blue-strong text-white hover:brightness-110 border border-transparent",
  secondary:
    "border border-cosmos-border-strong bg-cosmos-panel text-cosmos-text hover:border-cosmos-cyan/60 backdrop-blur",
  ghost: "border border-transparent text-cosmos-secondary hover:text-cosmos-text hover:border-cosmos-border",
  danger: "border border-cosmos-red/50 text-cosmos-red hover:bg-cosmos-red/10",
};

export function Button({
  variant = "secondary",
  size = "md",
  pressed,
  className = "",
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  pressed?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={`mc-focus inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-semibold transition-[filter,color,border-color,background-color] disabled:cursor-not-allowed disabled:opacity-45 ${
        size === "sm" ? "min-h-8 px-2.5 py-1 text-[12px]" : "min-h-9 px-3 py-1.5 text-[13px]"
      } ${BUTTON_VARIANT[variant]} ${pressed ? "ring-1 ring-cosmos-cyan/60" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** 토글 칩 (필터·정렬). */
export function Chip({
  active = false,
  color,
  className = "",
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean; color?: string }) {
  const hex = color ?? COSMOS_COLORS.cyan;
  return (
    <button
      type="button"
      aria-pressed={active}
      data-chip
      className={`mc-focus inline-flex min-h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-[12px] font-medium transition-colors ${
        active
          ? ""
          : "border-cosmos-border bg-cosmos-panel text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
      } ${className}`}
      style={active ? tintStyle(hex) : undefined}
      {...rest}
    >
      {children}
    </button>
  );
}
