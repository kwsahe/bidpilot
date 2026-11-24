/**
 * 「쉬운 보기 ⇄ 전체 보기」 저장 규칙 (24차 · prompt_14 §3-1).
 *
 * 주소 `?mode=` 가 먼저 · 페이지를 열 때 한 번만 본다 · 토글은 이 페이지에서만(37차 §3-F — 저장소에 쓰지 않는다), 주소에 `mode` 가 있으면 그것도 맞춘다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

type Store = Map<string, string>;

function fakeWindow(search: string, store: Store) {
  const location = { search, href: `http://localhost:3110/opportunities${search}` };
  return {
    location,
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
    history: {
      state: null,
      replaceState: (_s: unknown, _t: string, url: string) => {
        const u = new URL(url);
        location.search = u.search;
        location.href = u.href;
      },
    },
  };
}

describe("보기 모드 저장", () => {
  it("값 읽기 — simple·full 만, 나머지는 null", async () => {
    const { parseDisplayMode, DEFAULT_VIEW_MODE } = await import("../src/lib/viewMode.ts");
    assert.equal(parseDisplayMode("simple"), "simple");
    assert.equal(parseDisplayMode("full"), "full");
    assert.equal(parseDisplayMode("3d"), null);
    assert.equal(parseDisplayMode(null), null);
    assert.equal(DEFAULT_VIEW_MODE, "simple");
  });

  it("저장값을 보지 않는다(37차 §3-F) — 주소 → 쉬운 보기 · 한 번 정한 뒤에는 주소가 바뀌어도 그대로 · 토글은 주소의 mode 만 맞추고 저장소에 쓰지 않는다 · 옛 저장값은 지운다", async () => {
    const store: Store = new Map([["bidpilot.viewmode.v1", "full"]]);
    const win = fakeWindow("?q=AI&mode=full", store);
    (globalThis as unknown as { window: unknown }).window = win;
    const { readDisplayMode, setDisplayMode } = await import("../src/lib/viewMode.ts");
    assert.equal(readDisplayMode(), "full"); // 주소(시연 링크)가 먼저
    assert.equal(store.has("bidpilot.viewmode.v1"), false); // 옛 저장값은 지운다
    // 목록 화면이 주소를 다시 써서 mode 가 빠져도 이 페이지의 값은 그대로다.
    win.location.search = "?q=AI";
    assert.equal(readDisplayMode(), "full");
    win.location.search = "?q=AI&mode=full";
    win.location.href = "http://localhost:3110/opportunities?q=AI&mode=full";
    setDisplayMode("simple");
    assert.equal(readDisplayMode(), "simple");
    assert.equal(store.has("bidpilot.viewmode.v1"), false); // 저장소에 쓰지 않는다
    assert.equal(new URLSearchParams(win.location.search).get("mode"), "simple");
    assert.equal(new URLSearchParams(win.location.search).get("q"), "AI");
  });

  it("주소에 mode 가 없으면 저장값이 전체 보기였어도 쉬운 보기로 연다(37차 §3-F)", async () => {
    const store: Store = new Map([["bidpilot.viewmode.v1", "full"]]);
    (globalThis as unknown as { window: unknown }).window = fakeWindow("", store);
    const mod = await import(`../src/lib/viewMode.ts?fresh=${Date.now()}`);
    assert.equal(mod.readDisplayMode(), "simple");
  });
});
