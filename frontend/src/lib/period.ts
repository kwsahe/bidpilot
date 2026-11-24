"use client";

/**
 * 조회 기간 — **네 화면이 같은 값을 쓴다** (0920 §4-B-2-e · ISSUE-075-e).
 *
 * ## 왜 필요한가
 *
 * 목록만 14/30/60 을 고를 수 있고 대시보드·레이더·RFP 분석은 14일로 굳어 있었다. 그래서
 * 목록에서 60일로 찾아낸 공고를 대시보드 선택창에서 찾을 수 없었다 — 같은 앱인데 서로
 * 다른 공고 집합을 보고 있었던 것이다.
 *
 * ## 어디에 남기나
 *
 * 브라우저 `localStorage`(`bidpilot.period.v1`) 하나다. 회사 선택(`lib/organization.ts`)과
 * 같은 방식이라 화면을 옮겨도 따라간다. 목록 화면은 이 값을 주소(`?days=`)에도 적어
 * 링크로 공유할 수 있게 하지만, **값을 정하는 곳은 여기 하나**다.
 *
 * ## 기본값이 30인 이유
 *
 * 수집을 공고명 키워드 조회로 바꾸면서(§4-A-1) 기준 창이 30일이 됐다. 화면 기본이 14면
 * 저장된 30일치를 두고도 절반만 보여 주게 된다.
 */

import { useSyncExternalStore } from "react";

export const PERIOD_STORAGE_KEY = "bidpilot.period.v1";
export const PERIOD_OPTIONS = [14, 30, 60] as const;
export type PeriodDays = (typeof PERIOD_OPTIONS)[number];
export const DEFAULT_PERIOD_DAYS: PeriodDays = 30;

const listeners = new Set<() => void>();

function isPeriod(value: unknown): value is PeriodDays {
  return typeof value === "number" && (PERIOD_OPTIONS as readonly number[]).includes(value);
}

/** 주소의 `?days=` 가 저장값보다 먼저다 — 링크로 받은 조건이 이긴다. */
export function readPeriodDays(): PeriodDays {
  try {
    const fromUrl = Number(new URLSearchParams(window.location.search).get("days"));
    if (isPeriod(fromUrl)) return fromUrl;
    const raw = Number(window.localStorage.getItem(PERIOD_STORAGE_KEY));
    if (isPeriod(raw)) return raw;
  } catch {
    // 저장소·주소를 못 읽는 환경 — 기본값으로 둔다.
  }
  return DEFAULT_PERIOD_DAYS;
}

export function setPeriodDays(days: number): void {
  if (!isPeriod(days)) return;
  try {
    window.localStorage.setItem(PERIOD_STORAGE_KEY, String(days));
  } catch {
    // 무시 — 이번 화면에서만 반영된다.
  }
  // 45차 H3 — 주소의 `?days=` 가 저장값보다 먼저라, 주소를 그대로 두면 새로 고른 값이 다음 읽기에서 옛 주소 값으로 돌아갔다
  // (14일을 한 번 고르면 30 · 60 · 「✕」 · 「조건 초기화」가 듣지 않음). 주소에 days 가 있으면 함께 바꾸고, 기본값이면 지운다.
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.has("days")) {
      if (days === DEFAULT_PERIOD_DAYS) url.searchParams.delete("days");
      else url.searchParams.set("days", String(days));
      window.history.replaceState(window.history.state, "", url.toString());
    }
  } catch {
    // 주소를 못 고치는 환경 — 저장값만 바뀐다.
  }
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

const getServer = () => DEFAULT_PERIOD_DAYS;

/** 지금 조회 기간(일). 서버 렌더·hydration 중에는 기본값이다. */
export function usePeriodDays(): PeriodDays {
  return useSyncExternalStore(subscribe, readPeriodDays, getServer);
}
