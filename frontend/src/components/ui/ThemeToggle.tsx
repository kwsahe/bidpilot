"use client";

/**
 * 「밝은 화면」 단추 (2.4.0 ⑥) — 두 머리(AppShell · /analysis TopBar) 오른쪽 묶음, 「?」 바로 앞.
 *
 * 누르면 밝은 화면 ⇄ 어두운 화면. 눌림(aria-pressed)이 「밝은 화면 켜짐」이다. 좁은 폭(390)에서는 해 그림만 보이고
 * 이름은 aria-label 로만 남는다(가로 넘침 없게). 크기는 보기 전환(ViewModeToggle) · 「?」와 같다 — 쉬운 보기 40px · 전체 보기 32px.
 * `data-theme-toggle` — 단추 수 검사(check_visibility.mjs COMMON)가 공통 머리로 보고 세지 않는다.
 */

import { useLayoutEffect, useSyncExternalStore } from "react";

import { applyTheme, readTheme, setTheme, subscribeTheme, type Theme } from "@/lib/theme";
import { useDisplayMode } from "@/lib/viewMode";

/** 서버 렌더 · 하이드레이션 중에는 어두운 화면(layout 의 data-theme 기본값과 같다). */
const getServer = (): Theme => "dark";

export function useTheme(): Theme {
  return useSyncExternalStore(subscribeTheme, readTheme, getServer);
}

export function ThemeToggle() {
  const theme = useTheme();
  const simple = useDisplayMode() === "simple";
  // 개발 모드(Strict Mode)는 다시 붙일 때 <html> 속성을 JSX 값으로 되돌린다 — 저장 값을 다시 붙인다. 운영에서는 아무 일 없음
  // (Next 16 안내 preventing-flash-before-hydration § Re-applying attributes in development).
  useLayoutEffect(() => {
    applyTheme(readTheme());
  }, []);
  const light = theme === "light";
  return (
    <button
      type="button"
      data-theme-toggle
      aria-pressed={light}
      aria-label="밝은 화면"
      title={light ? "어두운 화면으로 바꾸기" : "밝은 화면으로 바꾸기"}
      onClick={() => setTheme(light ? "dark" : "light")}
      className={`mc-focus inline-flex ${simple ? "min-h-10 min-w-10" : "min-h-8 min-w-8"} shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-cosmos-border px-2 text-[12.5px] font-medium transition-colors ${
        light ? "bg-cosmos-blue/25 text-cosmos-text" : "bg-cosmos-panel text-cosmos-secondary hover:text-cosmos-text"
      }`}
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
        <circle cx="8" cy="8" r="3" />
        <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.06 1.06M11.54 11.54l1.06 1.06M3.4 12.6l1.06-1.06M11.54 4.46l1.06-1.06" />
      </svg>
      <span className="hidden sm:inline">밝은 화면</span>
    </button>
  );
}
