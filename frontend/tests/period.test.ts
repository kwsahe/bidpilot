import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_PERIOD_DAYS, readPeriodDays, setPeriodDays } from "@/lib/period";

/** 브라우저 없이 주소 · 저장소만 흉내 낸다. */
function fakeWindow(href: string) {
  const store = new Map<string, string>();
  const win = {
    location: new URL(href),
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    },
    history: {
      state: null,
      replaceState(_state: unknown, _title: string, url: string) {
        win.location = new URL(url);
      },
    },
    addEventListener() {},
    removeEventListener() {},
  };
  (globalThis as unknown as { window: typeof win }).window = win;
  return win;
}

test("45차 H3 — 주소에 ?days= 가 있어도 새로 고른 기간이 이긴다(14 → 60 → 기본으로 되돌리기)", () => {
  const win = fakeWindow("http://127.0.0.1:3130/opportunities?days=14&mode=full");
  assert.equal(readPeriodDays(), 14);
  setPeriodDays(60);
  assert.equal(readPeriodDays(), 60);
  assert.equal(win.location.search, "?days=60&mode=full");
  setPeriodDays(DEFAULT_PERIOD_DAYS); // 「✕」 · 「조건 초기화」
  assert.equal(readPeriodDays(), DEFAULT_PERIOD_DAYS);
  assert.equal(win.location.search, "?mode=full");
});

test("주소에 days 가 없으면 주소는 건드리지 않고 저장값만 바꾼다", () => {
  const win = fakeWindow("http://127.0.0.1:3130/opportunities");
  setPeriodDays(14);
  assert.equal(readPeriodDays(), 14);
  assert.equal(win.location.search, "");
});
