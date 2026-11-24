/**
 * 2.4.0 ⑥ 밝은 화면 — 첫 그림 스크립트 · 색 토큰 두 벌 · JS 색(var) · 두 머리 단추.
 *
 * 어두운 화면이 지금 그대로인지는 「globals.css :root 값 = COSMOS_HEX(예전 16진값)」로 잰다.
 */

import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { COSMOS_COLORS, COSMOS_HEX, cosmosHex, withAlpha } from "../src/lib/cosmos/theme.ts";
import { THEME_INIT_SCRIPT, THEME_KEY } from "../src/lib/theme.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");
const CSS = read("app", "globals.css");

/** `선택자 { … }` 한 덩어리의 `--이름: 값` 들. */
function block(selector: string): Map<string, string> {
  const start = CSS.indexOf(`${selector} {`);
  assert.ok(start >= 0, `${selector} 덩어리가 없음`);
  const body = CSS.slice(start, CSS.indexOf("\n}", start));
  const out = new Map<string, string>();
  for (const m of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out.set(m[1], m[2].trim().toLowerCase().replace(/\s+/g, ""));
  return out;
}
const varName = (value: string) => /^var\((--[\w-]+)\)$/.exec(value)?.[1] ?? "";

/** 지시서 표(대비 계산 끝난 값) 그대로. */
const LIGHT: Record<string, string> = {
  "--cosmos-bg": "#eef1f6",
  "--cosmos-bg-deep": "#e8ecf3",
  "--cosmos-bg-elevated": "#ffffff",
  "--cosmos-panel": "rgba(255,255,255,0.92)",
  "--cosmos-panel-solid": "#ffffff",
  "--cosmos-border": "rgba(23,37,84,0.14)",
  "--cosmos-border-strong": "rgba(23,37,84,0.28)",
  "--cosmos-text": "#0f1830",
  "--cosmos-text-secondary": "#343f5a",
  "--cosmos-text-muted": "#3e4863",
  "--cosmos-blue": "#2b4fc4",
  "--cosmos-blue-text": "#1f45b5",
  "--cosmos-blue-strong": "#2f55d0",
  "--cosmos-cyan": "#08546a",
  "--cosmos-violet": "#5b34c7",
  "--cosmos-amber": "#7f3d04",
  "--cosmos-red": "#a81f2d",
  "--cosmos-red-text": "#781421",
  "--cosmos-green": "#035e45",
  "--cosmos-slate": "#4b5672",
  "--cosmos-overlay": "rgba(255,255,255,0.98)",
  "--cosmos-shadow": "rgba(15,24,48,0.16)",
  "--cosmos-shadow-soft": "rgba(15,24,48,0.1)",
  "--cosmos-link": "#08546a",
  "--cosmos-rfp": "#1f45b5",
};

describe("첫 그림 스크립트", () => {
  /** 가짜 창에서 스크립트를 돌려 <html data-theme> 값을 본다. */
  function run(stored: string | null | "throw"): string | null {
    let attr: string | null = null;
    const localStorage = {
      getItem: (key: string) => {
        if (stored === "throw") throw new Error("저장소 막힘");
        return key === THEME_KEY ? stored : null;
      },
    };
    const document = { documentElement: { setAttribute: (name: string, value: string) => { if (name === "data-theme") attr = value; } } };
    new Function("localStorage", "document", THEME_INIT_SCRIPT)(localStorage, document);
    return attr;
  }

  it("열쇠 bidpilot.theme.v1 을 읽고 'light' 일 때만 붙인다 · 저장소가 막혀도 오류 없음", () => {
    assert.equal(THEME_KEY, "bidpilot.theme.v1");
    assert.ok(THEME_INIT_SCRIPT.includes(JSON.stringify(THEME_KEY)));
    assert.match(THEME_INIT_SCRIPT, /try\{/);
    assert.equal(run("light"), "light");
    assert.equal(run("dark"), null);
    assert.equal(run(null), null);
    assert.equal(run("throw"), null);
  });

  it("layout 은 data-theme=dark · suppressHydrationWarning · <head> 인라인 스크립트", () => {
    const layout = read("app", "layout.tsx");
    assert.match(layout, /data-theme="dark"/);
    assert.match(layout, /suppressHydrationWarning/);
    assert.match(layout, /<script dangerouslySetInnerHTML=\{\{ __html: THEME_INIT_SCRIPT \}\} \/>/);
    // 서버 컴포넌트(layout)가 import 하므로 lib/theme.ts 는 React 훅을 가져오지 않는다
    assert.doesNotMatch(read("lib", "theme.ts"), /from "react"/);
  });

  it("두 머리(AppShell · TopBar)에 「밝은 화면」 단추가 「?」 바로 앞에", () => {
    assert.match(read("components", "ui", "AppShell.tsx"), /<ThemeToggle \/>\s*<WhyBidPilotButton/);
    assert.match(read("components", "cosmos", "TopBar.tsx"), /<ThemeToggle \/>\s*\{\/\* 처음 안내는[^}]*\*\/\}\s*<WhyBidPilotButton/);
    const toggle = read("components", "ui", "ThemeToggle.tsx");
    assert.match(toggle, /data-theme-toggle/);
    assert.match(toggle, /aria-pressed=\{light\}/);
    assert.match(toggle, /aria-label="밝은 화면"/);
    // 단추 수 검사가 공통 머리로 보고 세지 않는다
    assert.match(readFileSync(join(ROOT, "..", "scripts", "check_visibility.mjs"), "utf8"), /const COMMON = '[^']*\[data-theme-toggle\]'/);
  });
});

describe("색 토큰 두 벌", () => {
  it("밝은 판에 표의 모든 토큰이 표의 값으로", () => {
    const light = block(':root[data-theme="light"]');
    for (const [name, value] of Object.entries(LIGHT)) assert.equal(light.get(name), value, name);
  });

  it("어두운 판(:root)은 지금 값 그대로 — COSMOS_COLORS 가 가리키는 변수의 값 = COSMOS_HEX(예전 16진값)", () => {
    const dark = block(":root");
    for (const key of Object.keys(COSMOS_HEX) as (keyof typeof COSMOS_HEX)[]) {
      const name = varName(COSMOS_COLORS[key]);
      assert.equal(dark.get(name), COSMOS_HEX[key].toLowerCase().replace(/\s+/g, ""), `${key} → ${name}`);
    }
    // 새 토큰의 어두운 값 = 지금 박혀 있던 값
    assert.equal(dark.get("--cosmos-overlay"), "rgba(11,19,38,0.97)");
    assert.equal(dark.get("--cosmos-link"), "#67e8f9");
  });

  it("COSMOS_COLORS 는 모두 var(--cosmos-…) · 열쇠는 COSMOS_HEX 와 같다 · cosmosHex 로 되돌린다", () => {
    assert.deepEqual(Object.keys(COSMOS_COLORS).sort(), Object.keys(COSMOS_HEX).sort());
    for (const [key, value] of Object.entries(COSMOS_COLORS)) {
      assert.ok(value.startsWith("var(--cosmos-"), key);
      assert.equal(cosmosHex(value), COSMOS_HEX[key as keyof typeof COSMOS_HEX], key);
    }
    assert.equal(cosmosHex("#123456"), "#123456");
  });

  it("withAlpha — color-mix 한 꼴 (예전 16진 + 알파 두 자리를 대신)", () => {
    assert.equal(withAlpha(COSMOS_COLORS.cyan, 12), "color-mix(in srgb, var(--cosmos-cyan) 12%, transparent)");
    assert.equal(withAlpha("#22D3EE", 40), "color-mix(in srgb, #22D3EE 40%, transparent)");
  });
});

describe("토큰 밖 색이 남지 않음", () => {
  const files: string[] = [];
  (function walk(dir: string) {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(ts|tsx)$/.test(name)) files.push(path);
    }
  })(join(ROOT, "src"));
  const is3d = (path: string) => /[\\/]three[\\/]|RadarScene3D\.tsx$/.test(path);

  it("16진 + 알파 두 자리 꼴(`${색}1f`) 0 — var() 색에서 깨진다", () => {
    const hits = files.flatMap((path) =>
      readFileSync(path, "utf8").split("\n").filter((line) => /\$\{[^}]+\}[0-9a-fA-F]{2}(["`' ,;)]|$)/.test(line)).map((line) => `${path}: ${line.trim()}`),
    );
    assert.deepEqual(hits, []);
  });

  it("3D 는 COSMOS_HEX 만 · 그 밖 화면에 박힌 겹 패널 면 · Tailwind 기본 호박 · 시안 0", () => {
    for (const path of files) {
      const text = readFileSync(path, "utf8");
      if (is3d(path)) assert.doesNotMatch(text, /\bCOSMOS_COLORS\b/, path);
      else if (!/[\\/]lib[\\/]cosmos[\\/]theme\.ts$/.test(path)) {
        // 정의 파일(COSMOS_HEX)은 뺀다
        assert.doesNotMatch(text, /rgba\(11, ?19, ?38, ?0\.9/, path);
        assert.doesNotMatch(text, /amber-500|accent-cyan-400|accent-\[#22D3EE\]|"#FF7A86"/, path);
      }
    }
  });
});
