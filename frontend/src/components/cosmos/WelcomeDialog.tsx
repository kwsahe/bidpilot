"use client";

/**
 * 첫 진입 환영 창 — 「BidPilot AI에 오신 것을 환영합니다 · 할 수 있는 것」(2.0.5 · 대표 요청 2026-10-27).
 * mount 이후 기록(`bidpilot.welcome.v2`)이 확정된 뒤에만 렌더된다 (SSR/hydration에 섞이지 않음).
 *
 * 예전 창은 「가상 예시 공고를 열었을 때만」 떴다. 10-13 부터 대시보드가 실제 1위 공고로 열려 한 번도 뜨지 않았고,
 * 내용도 가상 예시 둘러보기 기준이었다. 지금은 첫 진입이면 어느 공고 · 어느 보기에서든 뜬다.
 * 문구는 lib/terms.ts 한 곳 — 30초 안내 · 튜토리얼 · 발표 모드는 상단 「?」에 있다.
 */

import Link from "next/link";
import { useEffect, useId, useRef } from "react";

import { GUIDE_LINKS } from "@/lib/guide";
import {
  GUIDE_OPEN_LINK,
  WELCOME_CLOSING,
  WELCOME_FEATURES,
  WELCOME_FEATURES_TITLE,
  WELCOME_FIRST_TIME,
  WELCOME_HELP_NOTE,
  WELCOME_LEAD,
  WELCOME_START,
  WELCOME_TITLE,
} from "@/lib/terms";

export interface WelcomeDialogProps {
  /** 「시작하기」 · Esc · 바깥 누름 — 본 것으로 기록하고 닫는다. */
  onStart: () => void;
  /** 실전 가이드로 간다 — 본 것으로 기록한다(돌아오면 이 창이 또 뜨지 않게 · EZ-27). */
  onLeave: () => void;
}

export default function WelcomeDialog({ onStart, onLeave }: WelcomeDialogProps) {
  const headingId = useId();
  const descriptionId = useId();
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    primaryRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onStart();
        return;
      }
      // aria-modal 인데 Tab 이 뒤 화면으로 빠졌다 — 창 안 단추 · 링크 사이에서만 돈다 (EZ-25)
      const items = event.key === "Tab" ? [...(boxRef.current?.querySelectorAll<HTMLElement>("a[href], button") ?? [])] : [];
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = boxRef.current?.contains(active) ?? false;
      if (event.shiftKey ? active === first || !inside : active === last || !inside) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus({ preventScroll: true });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onStart]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 배경 누름 = 닫기(마우스). 키보드는 Esc — 테두리 없는 화면 전체 단추로 초점이 가지 않게 (EZ-25) */}
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onStart}
        className="absolute inset-0 cursor-default bg-cosmos-bg/70"
      />
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={descriptionId}
        data-welcome-dialog
        className="relative max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-xl border border-cosmos-border bg-cosmos-panel p-6 shadow-[0_18px_48px_var(--cosmos-shadow)]"
        style={{ backgroundColor: "var(--cosmos-overlay)" }}
      >
        <p className="text-[12px] font-medium tracking-[0.18em] text-cosmos-cyan">근거 기반 AI 수주 도우미</p>
        <h2 id={headingId} className="mt-1 text-[20px] font-semibold text-cosmos-text">
          {WELCOME_TITLE}
        </h2>
        <p id={descriptionId} className="mt-2 text-[14px] leading-6 text-cosmos-secondary">
          {WELCOME_LEAD}
        </p>

        <h3 className="mt-5 text-[13px] font-semibold text-cosmos-text">{WELCOME_FEATURES_TITLE}</h3>
        <ul className="mt-2 divide-y divide-cosmos-border/60 border-y border-cosmos-border/60">
          {WELCOME_FEATURES.map((feature) => (
            <li key={feature.title} className="py-2.5">
              <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <span className="text-[14px] font-semibold text-cosmos-text">{feature.title}</span>
                <span className="text-[12px] text-cosmos-muted">{feature.where}</span>
              </p>
              <p className="mt-0.5 text-[13px] leading-5 text-cosmos-secondary">{feature.detail}</p>
            </li>
          ))}
        </ul>

        <p className="mt-4 text-[13px] leading-5 text-cosmos-secondary">{WELCOME_CLOSING}</p>

        <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
          <button
            ref={primaryRef}
            type="button"
            onClick={onStart}
            className="min-h-11 rounded-lg bg-cosmos-blue-strong px-6 text-[14px] font-semibold text-white transition-[filter] hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
          >
            {WELCOME_START}
          </button>
          <span className="text-[13px] text-cosmos-secondary">
            {WELCOME_FIRST_TIME}{" "}
            <Link
              href={GUIDE_LINKS.start}
              onClick={onLeave}
              className="font-medium text-cosmos-cyan underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            >
              {GUIDE_OPEN_LINK}
            </Link>
          </span>
        </div>
        <p className="mt-4 text-[12px] leading-5 text-cosmos-muted">{WELCOME_HELP_NOTE}</p>
      </div>
    </div>
  );
}
