"use client";

/**
 * 「쉬운 보기 ⇄ 전체 보기」 (24차 · prompt_14 §3-1).
 *
 * 담당자 말: 「요소들이 너무 많아서 한눈에 보기 어려움. 보기 쉬운 모드를 따로 만들어줘. 지금까지 만든 기능은 삭제 금지.」
 * 그래서 전체 보기(지금 화면)는 그대로 두고, 같은 데이터를 한 열로 보여 주는 쉬운 보기를 따로 둔다.
 *
 * **37차 §3-F(담당자 결정 2026-10-14 「대시보드 쉬운 보기를 기본으로 고정」)**
 * - 지난번 고른 보기를 **기억하지 않는다** — 예전에는 `localStorage` `bidpilot.viewmode.v1` 에 남겨 다음에 열 때 그 보기로 열었다.
 *   이제 이 페이지(탭) 안에서만 기억한다. 새로 열면(새로고침 · 새 탭) 다시 쉬운 보기다.
 * - **대시보드는 열 때마다 쉬운 보기**다(`useDashboardOpensSimple`) — 다른 화면에서 전체 보기로 바꾼 채 메뉴로 와도 쉬운 보기로 연다.
 * - 주소 `?mode=simple|full` 이 먼저다(시연 링크 `?mode=full` 은 그대로 전체 보기로 연다). 주소는 **페이지를 열 때 한 번만** 본다
 *   (대시보드 `readUrlOptions` 처럼). 매번 주소를 보면 사업기회 목록이 주소를 다시 쓰며 `mode=full` 을 남기는 동안 토글이 먹지 않는다.
 * - 이름: 3D/2D/목록 전환이 이미 `viewMode`(`CosmosViewMode`)라 이것은 `DisplayMode` 다. 주소 키도 `?view=` 와 다른 `?mode=`.
 */

import { useState, useSyncExternalStore } from "react";

export type DisplayMode = "simple" | "full";

/** 기본 보기 — 담당자 결정(2026-10-14)으로 쉬운 보기에 고정. */
export const DEFAULT_VIEW_MODE: DisplayMode = "simple";
/** 옛 저장 열쇠 — 이제 읽지도 쓰지도 않는다. 남은 값은 처음 읽을 때 지운다(오해를 남기지 않게). */
export const VIEW_MODE_STORAGE_KEY = "bidpilot.viewmode.v1";
export const VIEW_MODE_QUERY_KEY = "mode";

export function parseDisplayMode(raw: string | null | undefined): DisplayMode | null {
  return raw === "simple" || raw === "full" ? raw : null;
}

function readUrlMode(): DisplayMode | null {
  try {
    return parseDisplayMode(new URLSearchParams(window.location.search).get(VIEW_MODE_QUERY_KEY));
  } catch {
    return null;
  }
}

const listeners = new Set<() => void>();
/** 이 페이지(탭)에서 정한 값 — 처음 읽을 때 주소 → 기본값으로 정한다. 저장소에 남기지 않는다. */
let cached: DisplayMode | null = null;

/** 옛 저장값을 지운다 — 다음에 열 때 그 보기로 열던 값이다(37차 §3-F). 한 번만. */
let forgotten = false;
function forgetStoredMode(): void {
  if (forgotten) return;
  forgotten = true;
  try {
    window.localStorage.removeItem(VIEW_MODE_STORAGE_KEY);
  } catch {
    // 저장소를 쓸 수 없는 창 — 지울 것도 없다.
  }
}

/** 주소 `?mode` → 기본값(쉬운 보기). 지난번 고른 보기는 보지 않는다(37차 §3-F). */
export function readDisplayMode(): DisplayMode {
  if (cached) return cached;
  forgetStoredMode();
  cached = readUrlMode() ?? DEFAULT_VIEW_MODE;
  return cached;
}

/** 사람이 토글로 고른 값 — 이 페이지에서만 유지한다. 주소에 `?mode` 가 있으면 그것도 맞춘다(새로고침 때 주소가 이기므로). */
export function setDisplayMode(mode: DisplayMode): void {
  cached = mode;
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.has(VIEW_MODE_QUERY_KEY)) {
      url.searchParams.set(VIEW_MODE_QUERY_KEY, mode);
      window.history.replaceState(window.history.state, "", url.toString());
    }
  } catch {
    // 주소를 못 고쳐도 이 페이지의 값은 남는다.
  }
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

const getServer = (): DisplayMode => DEFAULT_VIEW_MODE;

/** 지금 보기. 서버 렌더·hydration 중에는 기본값이고, 마운트 뒤 이 페이지 값으로 갈아탄다. */
export function useDisplayMode(): DisplayMode {
  return useSyncExternalStore(subscribe, readDisplayMode, getServer);
}

/**
 * 대시보드는 **열 때마다 쉬운 보기**다(37차 §3-F-1 · 2). 주소 `?mode=` 가 있으면 그 값(시연 링크 `?mode=full`).
 *
 * 화면이 처음 그려질 때 한 번만 정한다(`useState` 초기값) — 효과(effect)로 고치면 전체 보기가 한 번 그려졌다가 바뀌어
 * 3D 장면이 헛되이 올라왔다. 그 뒤 토글로 바꾼 값은 이 화면에 있는 동안 그대로다.
 */
export function useDashboardOpensSimple(): void {
  useState(() => {
    if (typeof window === "undefined") return null;
    forgetStoredMode();
    const fromUrl = readUrlMode();
    const next = fromUrl ?? DEFAULT_VIEW_MODE;
    if (cached !== next) {
      cached = next;
      // 같은 렌더 안의 다른 구독자(메뉴 꼬리표)는 아직 그리기 전이다 — 알림은 다음 틱에(렌더 중 setState 경고를 피한다).
      queueMicrotask(() => {
        for (const listener of listeners) listener();
      });
    }
    return null;
  });
}
