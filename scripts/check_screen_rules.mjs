/**
 * 화면 규칙 다섯 (27차 · prompt_17 §3-H) — 눈으로만 잡던 모양을 숫자로.
 *
 *  ① 글 기둥   — 보이는 글 상자가 폭 < 48px 인데 높이 > 줄 높이 × 3 (좁은 칸에 글이 세로로 쌓였다)
 *  ② 가로 넘침 — 문서가 창보다 넓다(가로 스크롤)
 *  ③ 이유 없는 비활성 — `[disabled]` · `aria-disabled=true` 인데 `aria-describedby`(글 있는 대상)도,
 *                     같은 부모 안의 보이는 사유 글도 없다
 *  ④ 탭 짝     — `role=tab` 인데 `aria-controls` 가 없거나 가리키는 요소가 없다
 *  ⑤ 창 밖 오버레이 — 보이는 `role=dialog` 의 제목 · 닫기 단추가 창 밖으로 나갔다
 *
 * 폭 390 · 800 · 1024 · 1440 × 화면(대시보드 두 보기 · 3D · 2D · 기본 · 사업기회 두 보기 · 레이더 · 요구사항 정리표 탭 합성 · 시연용 · 사업계획서 작성 ·
 * 회사자료 · 지원사업 두 화면 × 두 보기 · 「?」 연 상태). 목표 0 — 남기면 보고에 이유.
 *
 * 쓰기 없음. 실행: node scripts/check_screen_rules.mjs [--base http://localhost:3110] [--widths 390,800] [--json]
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const BASE = argOf("--base", "http://localhost:3110");
const PORT = Number(argOf("--port", "9243"));
const WIDTHS = argOf("--widths", "390,800,1024,1440").split(",").map(Number);
const HEIGHT = Number(argOf("--height", "900"));
const AS_JSON = args.includes("--json");
const ONLY = argOf("--only", null);
const AI_Q = argOf("--ai-q", "개인정보");
const BROWSERS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];
const SYN = "synthetic-rfp-0001";
const SHOWCASE = "g2b-R26BK01707959-000";
// 지원사업 예시 — 126482(10-06 마감) → 123852. 고르는 조건은 check_page_unity.mjs 의 SUPPORT 주석.
const SUPPORT = "bizinfo-PBLN_000000000123852";
const DASH = `/analysis?notice=${SYN}&welcome=0&guided=0`;
const PAGES = [
  { key: "대시보드 쉬운", path: `${DASH}&mode=simple` },
  { key: "대시보드 전체 기본", path: `${DASH}&mode=full` },
  { key: "대시보드 2D", path: `${DASH}&mode=full&view=2d` },
  { key: "대시보드 「?」", path: `${DASH}&mode=full`, help: true },
  { key: "사업기회 쉬운", path: "/opportunities?mode=simple&welcome=0" },
  { key: "사업기회 전체", path: "/opportunities?mode=full&welcome=0" },
  // 41차 FRONT-R40-01 — 긴 꼬리표(AI 「본업 아닐 수 있음 · 이유」)가 보이는 행. 살아 있는 저장본(10-21 첫 AI 호출 뒤)에서 그런 공고를 찾는 낱말 —
  // `--ai-q` 로 바꾼다. 꼬리표가 하나도 없으면 결과에 「AI 꼬리표 0」으로 적는다(넘침 0 이 꼬리표 없어서인지 가린다).
  { key: "사업기회 전체 · AI 꼬리표", path: `/opportunities?mode=full&welcome=0&q=${encodeURIComponent(AI_Q)}`, aiTags: true },
  { key: "선제준비 전체 · AI 꼬리표", path: "/opportunities?tab=prepare&mode=full&welcome=0", aiTags: true, openFolds: true },
  { key: "레이더", path: "/radar?welcome=0" },
  // 요구사항 정리표는 사업기회 안의 탭(28차 §3-C)
  { key: "정리표 합성", path: `/opportunities?tab=sheet&notice=${SYN}&mode=full&welcome=0` },
  { key: "정리표 시연용", path: `/opportunities?tab=sheet&notice=${SHOWCASE}&mode=full&welcome=0` },
  // 38차 §3-E — 직접 넣기 · 후보함 탭(사업기회 안 · 두 보기)
  { key: "직접 넣기 쉬운", path: "/opportunities?tab=manual&mode=simple&welcome=0" },
  { key: "직접 넣기 전체", path: "/opportunities?tab=manual&mode=full&welcome=0" },
  // 「+ 공고 직접 넣기」 양식(브라우저 기본 <dialog>)을 연 상태 — 제목 · 닫기가 창 안에 있나(⑤)
  { key: "직접 넣기 양식", path: "/opportunities?tab=manual&mode=simple&welcome=0", manualDialog: true },
  // 39차 결정 1 — 선제준비 탭(사전규격 · 발주계획 · 사업기회 안 · 두 보기)
  { key: "선제준비 쉬운", path: "/opportunities?tab=prepare&mode=simple&welcome=0" },
  { key: "선제준비 전체", path: "/opportunities?tab=prepare&mode=full&welcome=0" },
  { key: "사업계획서 작성", path: "/plan?welcome=0" },
  { key: "회사자료", path: "/company?welcome=0" },
  // 32차 §3-A-11 — 실전 가이드(문서 화면 · 표는 표 안쪽만 가로 스크롤)
  { key: "실전 가이드", path: "/guide?welcome=0" },
  { key: "지원사업 쉬운", path: `/support/${SUPPORT}?mode=simple&welcome=0` },
  { key: "지원사업 전체", path: `/support/${SUPPORT}?mode=full&welcome=0` },
  { key: "지원사업(대시보드) 쉬운", path: `/analysis?support=${SUPPORT}&welcome=0&guided=0&mode=simple` },
  { key: "지원사업(대시보드) 전체", path: `/analysis?support=${SUPPORT}&welcome=0&guided=0&mode=full` },
].filter((p) => !ONLY || p.key.includes(ONLY));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.id = 0;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", { expression: `(async () => { ${expression} })()`, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? "페이지 스크립트 오류");
    return result.result.value;
  }
}

async function connect(port) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
      const page = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) {
        const socket = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((ok, fail) => {
          socket.addEventListener("open", ok, { once: true });
          socket.addEventListener("error", () => fail(new Error("CDP 연결 실패")), { once: true });
        });
        return new Cdp(socket);
      }
    } catch {
      // 아직 안 떴다
    }
    await sleep(500);
  }
  throw new Error(`브라우저 원격 디버깅(${port})에 붙지 못했습니다`);
}

/** 규칙 다섯을 재는 페이지 안 스크립트. */
const PROBE = String.raw`
  const W = innerWidth, H = innerHeight;
  const shown = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) <= 0.05) return false;
    // sr-only(1px 잘라 낸 글)는 화면 글이 아니다
    if (r.width <= 1.5 && r.height <= 1.5) return false;
    return true;
  };
  const label = (el) => {
    const t = (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
    const tag = el.tagName.toLowerCase();
    return tag + (el.id ? "#" + el.id : "") + " 「" + t + "」";
  };
  // ① 글 기둥 — 글이 직접 든 요소만(부모 상자는 자식이 잰다)
  const pillars = [];
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest("svg, canvas, [aria-hidden='true']")) continue;
    const own = [...el.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent).join("").replace(/\s+/g, "");
    if (own.length < 4) continue;
    if (!shown(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right < 0 || r.left > W) continue;
    const s = getComputedStyle(el);
    const line = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.4 || 18;
    if (r.width < 48 && r.height > line * 3) pillars.push(label(el) + " " + Math.round(r.width) + "×" + Math.round(r.height));
  }
  // ② 가로 넘침
  const overflowX = Math.max(0, document.documentElement.scrollWidth - W);
  // ③ 이유 없는 비활성
  const unexplained = [];
  for (const el of document.querySelectorAll("button[disabled], input[disabled], select[disabled], textarea[disabled], [aria-disabled='true']")) {
    if (!shown(el)) continue;
    const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    const described = ids.some((id) => { const t = document.getElementById(id); return t && (t.textContent || "").trim().length > 0; });
    if (described) continue;
    const parent = el.parentElement;
    const own = (el.innerText || el.value || "").trim();
    let reason = "";
    if (parent) {
      for (const sib of parent.children) {
        if (sib === el || sib.contains(el) || !shown(sib)) continue;
        reason += (sib.innerText || "").trim();
      }
    }
    if (reason.replace(own, "").length >= 4) continue;
    unexplained.push(label(el));
  }
  // ④ 탭 짝
  const tabs = [];
  for (const el of document.querySelectorAll("[role='tab']")) {
    if (!shown(el)) continue;
    const id = el.getAttribute("aria-controls");
    if (!id || !document.getElementById(id)) tabs.push(label(el) + (id ? " → #" + id + " 없음" : " aria-controls 없음"));
  }
  // ⑤ 창 밖 오버레이
  const offscreen = [];
  const inside = (r) => r.left >= -1 && r.top >= -1 && r.right <= W + 1 && r.bottom <= H + 1;
  for (const dialog of document.querySelectorAll("[role='dialog'], [role='alertdialog'], dialog[open]")) {
    if (!shown(dialog)) continue;
    const labelled = dialog.getAttribute("aria-labelledby");
    const title = (labelled && document.getElementById(labelled)) || dialog.querySelector("h1, h2, h3");
    const close = [...dialog.querySelectorAll("button")].find((b) => /닫기|✕|×|취소/.test((b.getAttribute("aria-label") || "") + (b.textContent || "")));
    if (title && shown(title) && !inside(title.getBoundingClientRect())) offscreen.push("제목 " + label(title));
    if (close && shown(close) && !inside(close.getBoundingClientRect())) offscreen.push("닫기 " + label(close));
    if (!title) offscreen.push("제목 없음 " + label(dialog));
    if (!close) offscreen.push("닫기 없음 " + label(dialog));
  }
  return { pillars, overflowX, unexplained, tabs, offscreen, dialogs: document.querySelectorAll("[role='dialog']").length };
`;

/** 화면이 실제로 떴나(39차 §3-F-5) — 개발 캐시가 깨지면 동적 경로가 「찾는 화면이 없습니다」(404)로 끝났고 이 검사는 빈 통과로 셌다. */
const LANDED = `const text = document.body.innerText || "";
  if (/찾는 화면이 없습니다|This page could not be found/.test(text)) return "화면이 뜨지 않았다 — 404(찾는 화면이 없습니다)";
  if (!document.querySelector("h1")) return "화면이 뜨지 않았다 — 제목(h1) 없음";
  return null;`;

async function open(cdp, path) {
  await cdp.send("Page.navigate", { url: new URL(path, BASE).href });
  const deadline = Date.now() + 90000;
  let last = -1;
  let stable = 0;
  while (Date.now() < deadline) {
    const n = await cdp.evaluate(`return document.readyState === "complete" ? document.body.innerText.length : -1;`).catch(() => -1);
    if (n > 200 && n === last) stable += 1;
    else stable = 0;
    last = n;
    if (stable >= 3) break;
    await sleep(700);
  }
  // 자료가 도착한 뒤에 잰다 — 레이더 390 의 실제 가로 넘침(430px)을 「조회 전」 로딩 중에 재어 0 으로 보고했다(§3-F RDR 검증).
  const until = Date.now() + 30000;
  while (Date.now() < until) {
    const loading = await cdp.evaluate(`return /불러오는 중|조회 전|계산 중…|결과를 불러오는/.test(document.body.innerText || "");`).catch(() => false);
    if (!loading) break;
    await sleep(700);
  }
  await sleep(1500);
}

async function main() {
  const browser = BROWSERS.find((p) => existsSync(p));
  if (!browser) throw new Error("Edge/Chrome 을 찾지 못했습니다");
  // 프로필은 포트마다 — 한 폴더를 두 실행이 같이 쓰면 두 번째 브라우저가 첫 번째 창에 붙어 디버깅 포트가 열리지 않았다.
  const profile = join(process.env.TEMP || ".", `bidpilot-check-rules-${PORT}`);
  const child = spawn(browser, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--headless=new", "--no-first-run", "--hide-scrollbars", "--disable-background-timer-throttling", "about:blank"], { stdio: "ignore" });
  const rows = [];
  try {
    const cdp = await connect(PORT);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    for (const width of WIDTHS) {
      await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: HEIGHT, deviceScaleFactor: 1, mobile: width < 768 });
      for (const page of PAGES) {
        let result;
        try {
          await open(cdp, page.path);
          const missing = await cdp.evaluate(LANDED);
          if (missing) throw new Error(missing);
          if (page.help) {
            await cdp.evaluate(`const b = [...document.querySelectorAll("button")].find((x) => (x.getAttribute("aria-label") || "").startsWith("처음 안내") && x.getBoundingClientRect().width > 0); if (b) b.click(); return !!b;`);
            await sleep(900);
          }
          if (page.manualDialog) {
            await cdp.evaluate(`const b = [...document.querySelectorAll("button")].find((x) => (x.textContent || "").includes("공고 직접 넣기") && x.getBoundingClientRect().width > 0); if (b) b.click(); return !!b;`);
            await sleep(900);
          }
          if (page.openFolds) {
            await cdp.evaluate(`for (const d of document.querySelectorAll("details")) d.open = true; return true;`);
            await sleep(600);
          }
          result = await cdp.evaluate(PROBE);
          if (page.aiTags) {
            // 41차 FRONT-R40-01 — 긴 AI 꼬리표가 실제로 그려졌는지(넘침 0 이 꼬리표가 없어서인지 가린다)
            result.aiTagCount = await cdp.evaluate(`return [...document.querySelectorAll("[data-practical-tags] span")].filter((x) => (x.textContent || "").startsWith("AI: 본업 아닐 수 있음") && x.getBoundingClientRect().width > 0).length;`);
          }
          if (page.help && result.dialogs === 0) result.offscreen.push("「?」 대화상자가 열리지 않았다");
          if (page.manualDialog && !(await cdp.evaluate(`return !!document.querySelector("dialog[open]");`))) result.offscreen.push("「공고 직접 넣기」 양식이 열리지 않았다");
        } catch (error) {
          result = { error: String(error.message || error), pillars: [], overflowX: 0, unexplained: [], tabs: [], offscreen: [] };
        }
        rows.push({ width, page: page.key, ...result });
      }
    }
  } finally {
    child.kill();
  }
  const count = (r) => (r.error ? 1 : 0) + r.pillars.length + (r.overflowX > 1 ? 1 : 0) + r.unexplained.length + r.tabs.length + r.offscreen.length;
  const total = rows.reduce((sum, r) => sum + count(r), 0);
  if (AS_JSON) {
    console.log(JSON.stringify({ rows, total }, null, 1));
  } else {
    console.log(`화면 규칙 다섯 — ${BASE} · 폭 ${WIDTHS.join(" · ")} × 높이 ${HEIGHT}`);
    console.log("  폭     화면                         ①기둥 ②넘침 ③비활성 ④탭 ⑤창밖  합");
    for (const r of rows) {
      console.log(`  ${String(r.width).padEnd(6)} ${r.page.padEnd(26)} ${String(r.pillars.length).padEnd(5)} ${String(r.overflowX > 1 ? r.overflowX : 0).padEnd(5)} ${String(r.unexplained.length).padEnd(7)} ${String(r.tabs.length).padEnd(4)} ${String(r.offscreen.length).padEnd(5)} ${count(r)}${r.error ? " 오류 " + r.error : ""}${r.aiTagCount !== undefined ? ` · AI 꼬리표 ${r.aiTagCount}` : ""}`);
      for (const p of r.pillars.slice(0, 4)) console.log(`         ① ${p}`);
      if (r.overflowX > 1) console.log(`         ② 가로 ${r.overflowX}px 넘침`);
      for (const u of r.unexplained.slice(0, 6)) console.log(`         ③ ${u}`);
      for (const t of r.tabs.slice(0, 4)) console.log(`         ④ ${t}`);
      for (const o of r.offscreen.slice(0, 4)) console.log(`         ⑤ ${o}`);
    }
    console.log(total ? `\n✗ 규칙 위반 ${total}` : "\n✓ 화면 규칙 다섯 위반 없음");
  }
  process.exit(total ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
