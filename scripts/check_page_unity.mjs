/**
 * 페이지 통일 · 연결 검사 (27차 · prompt_17 §3-E-6) — 「화면을 옮겨도 같은 것이 같은 이름 · 같은 글자로 보이는가」.
 *
 * (1) 화면마다 보이는 h1 이 1개이고, 그 글이 상단 메뉴의 활성 항목 이름과 같다
 *     (지원사업 신청 분석은 메뉴 항목이 아니므로 h1 1개만).
 * (2) 머리 오른쪽 순서 — 회사 선택기 → 보기 전환 → 「?」 (있는 것만 · DOM 순서와 보이는 순서 둘 다) ·
 *     셋이 머리 밖에 있지 않다.
 * (3) 같은 공고를 대시보드 · 사업기회 목록 · 레이더 · 요구사항 정리표 탭(지원사업은 지원사업 화면)에서 열어
 *     참가 판정 · 마감 · 검토 우선순위 글자가 같은가 — 표. 보여 주지 않는 화면은 「—」(비교에서 뺀다).
 * (4) 메뉴로 한 바퀴(입찰 분석 → 레이더 → 사업기회 → 회사자료 → 실전 가이드 → 입찰 분석 · 2.1.0 부터 메뉴 여섯 — 대시보드(통계)는 공고를 싣지 않아 뺌) 돌며
 *     고른 공고 · 회사 · 보기(쉬운/전체)가 이어지는가 — 표. 지원사업 한 바퀴도.
 *     회사 한 바퀴는 합성 회사 `org-test-alpha` 로 돌되 **그 회사로 가는 백엔드 요청은 브라우저에서 막는다**
 *     (다른 회사로 목록을 읽으면 data/ 에 캐시 · 분석 파일이 생긴다). 막힌 요청의 회사 id 로
 *     「화면이 저장된 회사로 물었는가」를 잰다.
 *
 * 쓰기 없음 — 샘플에듀(기본 회사) 화면을 여는 것만 한다. check_map.mjs 와 같은 CDP 방식(Edge headless).
 * 실행: node scripts/check_page_unity.mjs [--base http://localhost:3110] [--json]
 */

import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const BASE = argOf("--base", "http://localhost:3110");
const BACKEND = argOf("--backend", "http://localhost:8110");
const PORT = Number(argOf("--port", "9243"));
const AS_JSON = args.includes("--json");
const DEMO = "synthetic-rfp-0001";
// 지원사업 예시 — 126482 가 2026-10-06 마감돼(마감 공고는 목록 · 레이더에서 숨음) 123852(10-30 마감)로 바꿨다.
// 고르는 조건(org-sample 기준): 열림 · 마감이 날짜로 정해짐 · 불가 아님 · 관련 낮음 없음 · 숫자 점수 · 기업마당 우선순위 상위 6건(레이더 기본 그림)
// · 링크 있는 첨부 · 신청 요건 1개 이상 · 저장된 사업계획서 초안(plan_draft · plan_form) · 공고문 읽음. 마감되면 이 조건으로 다시 고른다.
const SUPPORT = argOf("--support", "bizinfo-PBLN_000000000123852");
const TEST_ORG = "org-test-alpha";
const BROWSERS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 28차 §3-C — 요구사항 정리표는 사업기회 안의 탭 · 32차 §3-A-11 — 「실전 가이드」(/guide)
// 37차 §3-E — 사업계획서 작성은 메뉴에서 빠져 사업기회 행의 「사업계획서 작성 →」 · 「제안서 작성 →」 단추로 들어간다(메뉴 다섯)
const MENU = ["대시보드", "레이더", "사업기회", "회사자료", "실전 가이드"];
const PATH_OF = { 대시보드: "/", "입찰 분석": "/analysis", 레이더: "/radar", 사업기회: "/opportunities", 회사자료: "/company", "실전 가이드": "/guide" };

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.id = 0;
    this.pending = new Map();
    this.handlers = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.method) {
        for (const fn of this.handlers.get(message.method) ?? []) fn(message.params);
        return;
      }
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
    });
  }
  on(method, fn) {
    this.handlers.set(method, [...(this.handlers.get(method) ?? []), fn]);
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", { expression: `(async () => { ${HELPERS} ${expression} })()`, awaitPromise: true, returnByValue: true });
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

/** 페이지 안에서 쓰는 도우미 — 모든 evaluate 앞에 붙는다. */
const HELPERS = String.raw`
  const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const txt = (el) => (el ? (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim() : "");
  const VERDICTS = ["가능", "확인 필요", "불가"];
  const verdictIn = (root) => root ? ([...root.querySelectorAll("[data-chip]")].filter(vis).map(txt).find((t) => VERDICTS.includes(t)) ?? null) : null;
  const priorityIn = (root) => { const m = root && /검토 우선순위\s*(\d[\d,]*|미산정|점수 없음)\s*(점|\/\s*100)?/.exec(root.innerText || ""); return m ? m[0].replace(/\s+/g, " ").trim() : null; };
  // 등록마감이 먼저 닫히는 입찰은 네 화면 모두 「등록마감 D-n」(레이더 칩은 줄여 「등록 D-n」 — 같은 사실)으로 적는다(27차 R27U-MSC-01).
  // 28차 새 캐시의 첫 입찰이 그런 공고라 이 모양을 못 읽으면 화면이 맞아도 「다름」이 났다.
  const deadlineIn = (root) => {
    const text = (root && root.innerText) || "";
    const reg = /등록마감\s*(D-Day|D-\d+|지남)/.exec(text) || /(?:^|\s)등록\s+(D-Day|D-\d+)/.exec(text);
    if (reg) return "등록마감 " + reg[1];
    const m = /(입찰|신청) (마감|종료)\s*(D-Day|D-\d+|D\+\d+|마감|종료)?/.exec(text);
    return m ? m[0].replace(/\s+/g, " ").trim() : null;
  };
`;

/** 머리 · h1 · 메뉴 활성 항목 · 머리 오른쪽 순서 */
const PROBE_HEAD = String.raw`
  const h1s = [...document.querySelectorAll("h1")].filter(vis).map(txt);
  const nav = document.querySelector('nav[aria-label="화면 이동"]');
  const active = nav ? [...nav.querySelectorAll('[aria-current="page"]')].filter(vis).map((a) => txt(a).replace(/\((전체 화면|전체 보기)\)/g, "").trim()) : [];
  const header = document.querySelector("header");
  const want = [["회사", "[data-organization-picker]"], ["보기", "[data-view-toggle]"], ["?", 'button[aria-label^="처음 안내"]']];
  const inHead = [];
  const outside = [];
  for (const [name, sel] of want) {
    const els = [...document.querySelectorAll(sel)].filter(vis);
    const h = els.find((e) => header && header.contains(e));
    if (h) inHead.push({ name, el: h });
    if (els.some((e) => !header || !header.contains(e))) outside.push(name);
  }
  const orderProblems = [];
  for (let i = 1; i < inHead.length; i += 1) {
    const a = inHead[i - 1], b = inHead[i];
    const ra = a.el.getBoundingClientRect(), rb = b.el.getBoundingClientRect();
    const domAfter = !!(a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING);
    const seenAfter = rb.top >= ra.bottom - 2 || rb.left >= ra.right - 2;
    if (!domAfter || !seenAfter) orderProblems.push(a.name + "→" + b.name + (domAfter ? " (보이는 순서)" : " (DOM 순서)"));
  }
  return { url: location.pathname + location.search, h1s, active, order: inHead.map((x) => x.name), outside, orderProblems };
`;

/** 지금 화면이 보여 주는 참가 판정 · 마감 · 검토 우선순위 (화면마다 자리가 다르다). */
const PROBE_FIELDS = String.raw`
  const path = location.pathname;
  const out = { screen: path, verdict: null, deadline: null, priority: null, found: true, note: "" };
  if (path === "/analysis") {
    const strip = document.querySelector('[data-tour="mission-strip"]');
    if (strip) {
      const card = [...strip.querySelectorAll("button")].find((b) => (b.getAttribute("aria-label") || "").startsWith("입찰 참가 가능 여부"));
      out.verdict = card ? txt(card.querySelector("span.font-mono")) || null : null;
      out.priority = priorityIn(strip);
      const dl = document.querySelector('[data-tour="topbar-deadline"]');
      out.deadline = dl && vis(dl) ? txt(dl) : null;
    } else {
      // 대시보드 안 지원사업(/analysis?support=) — 머리 한 줄
      const title = [...document.querySelectorAll("[data-chip]")].find((c) => /기업마당 지원사업 · 신청/.test(txt(c)));
      const head = title ? title.parentElement : null;
      out.verdict = verdictIn(head);
      out.priority = priorityIn(head);
      // 머리 낱말 + D-day 전체를 읽는다(27차 §3-E 검증 G5-V1 — D-day 토막만 보면 「신청 마감」이 빠져도 통과했다)
      out.deadline = deadlineIn(head);
      out.found = !!head;
    }
  } else if (path === "/opportunities" && new URLSearchParams(location.search).get("tab") === "sheet") {
    const sheet = document.querySelector("[data-sheet-notice]");
    const chip = sheet ? [...sheet.querySelectorAll("[data-chip]")].find((c) => vis(c) && /^검토 우선순위/.test(txt(c))) : null;
    const row = chip ? chip.parentElement : null;
    out.screen = "/opportunities?tab=sheet";
    out.found = !!row;
    if (row) {
      out.verdict = verdictIn(row);
      out.priority = priorityIn(row);
      out.deadline = deadlineIn(row);
    } else out.note = "한 줄 카드 없음(통합 목록에 없는 공고)";
  } else if (path === "/opportunities") {
    const row = document.querySelector("[data-current-notice]");
    out.found = !!row;
    if (row) {
      out.verdict = verdictIn(row.querySelector('[data-visibility-strip="card-head"]') || row);
      out.priority = priorityIn(row);
      out.deadline = deadlineIn(row.querySelector('[data-visibility-strip="card-head"]') || row);
    } else out.note = "목록에 없음";
  } else if (path === "/radar") {
    const label = [...document.querySelectorAll(".mc-panel > span")].find((s) => vis(s) && txt(s) === "검토 우선순위");
    let root = label;
    while (root && !root.querySelector("h2")) root = root.parentElement;
    out.found = !!root;
    if (root) {
      out.verdict = verdictIn(root);
      out.priority = priorityIn(root);
      out.deadline = deadlineIn(root);
    } else out.note = "레이더에 없음";
  } else if (path.startsWith("/support/")) {
    const kpi = [...document.querySelectorAll(".mc-panel")].find((p) => txt(p.querySelector("span")) === "회사 기준 검토 우선순위");
    const value = kpi ? txt(kpi.querySelector("span.font-mono")) : "";
    out.priority = value ? "검토 우선순위 " + value : null;
    const dk = [...document.querySelectorAll(".mc-panel")].find((p) => /^신청 (마감|종료)/.test(txt(p.querySelector("span"))));
    const term = dk ? txt(dk.querySelector("span")) : "";
    const d = dk ? /(D-Day|D-\d+|D\+\d+|마감|종료)/.exec((dk.innerText || "").replace(term, "")) : null;
    out.deadline = dk ? term + (d ? " " + d[1] : "") : null;
    out.verdict = null;
  }
  return out;
`;

/** 한 바퀴 기록 — 고른 것 · 회사 · 보기 */
const PROBE_CARRY = String.raw`
  const path = location.pathname;
  const q = new URLSearchParams(location.search);
  const picker = document.querySelector("header [data-organization-picker] select");
  const toggle = document.querySelector("[data-view-toggle]");
  let shown = null;
  let detailTitle = null;
  const noticeSelect = document.querySelector('[data-tour="topbar-notice"] select');
  if (path === "/analysis") shown = noticeSelect ? noticeSelect.value : null;
  else if (path === "/plan") shown = document.querySelector("[data-plan-target]")?.getAttribute("data-plan-target") || null;
  else if (path === "/opportunities" && q.get("tab") === "sheet") shown = document.querySelector("[data-sheet-notice]")?.getAttribute("data-sheet-notice") || null;
  else if (path === "/opportunities") {
    const row = document.querySelector("[data-current-notice]");
    shown = row ? row.getAttribute("data-current-notice") || "(강조된 행 · id 없음)" : null;
  } else if (path === "/radar") {
    const label = [...document.querySelectorAll(".mc-panel > span")].find((s) => vis(s) && txt(s) === "검토 우선순위");
    let root = label;
    while (root && !root.querySelector("h2")) root = root.parentElement;
    detailTitle = root ? txt(root.querySelector("h2")) : null;
    shown = detailTitle ? "상세: " + detailTitle.slice(0, 18) : null;
  } else if (path === "/company") {
    const back = document.querySelector("a[data-back-to-selection]");
    shown = back && vis(back) ? back.getAttribute("href") : null;
  } else if (path.startsWith("/support/")) shown = decodeURIComponent(path.split("/")[2] || "");
  const rfpLocked = !!document.querySelector('nav[aria-label="화면 이동"] [data-nav-disabled]');
  let store = {};
  try { for (const k of ["bidpilot.notice.v1", "bidpilot.support.v1", "bidpilot.selection-kind.v1", "bidpilot.viewmode.v1", "bidpilot.organization.v1"]) store[k.replace(/^bidpilot\.|\.v1$/g, "")] = localStorage.getItem(k); } catch {}
  return {
    url: path + location.search,
    h1: [...document.querySelectorAll("h1")].filter(vis).map(txt).join(" | "),
    shown,
    urlNotice: q.get("notice") || q.get("support") || null,
    optionText: noticeSelect && noticeSelect.selectedOptions[0] ? txt(noticeSelect.selectedOptions[0]) : null,
    detailTitle,
    company: picker ? picker.value : null,
    toggle: toggle ? toggle.getAttribute("data-view-toggle") : null,
    fullOnlyNote: !!document.querySelector("[data-full-only-note]"),
    rfpLocked,
    store,
  };
`;

async function settle(cdp, extra = "true", timeout = 45000) {
  const deadline = Date.now() + timeout;
  let last = -1;
  let same = 0;
  const started = Date.now();
  while (Date.now() < deadline) {
    const now = await cdp
      .evaluate(`const h = [...document.querySelectorAll("h1")].some(vis); const ok = h && (${extra}); return ok ? (document.body.innerText || "").length : -1;`)
      .catch(() => -1);
    if (now >= 0 && now === last) same += 1;
    else same = 0;
    last = now;
    if (same >= 3 && Date.now() - started > 2500) return true;
    await sleep(600);
  }
  return false;
}

/** 화면마다 「다 불러왔다」로 볼 조건 */
function readyOf(path) {
  if (path === "/analysis") return `!!document.querySelector('[data-tour="topbar-notice"] select') && (!!document.querySelector('[data-tour="mission-strip"]') || !!document.querySelector("#simple-notice-title") || [...document.querySelectorAll("[data-chip]")].some((c) => /기업마당 지원사업 · 신청/.test(txt(c))))`;
  // 실공고는 한 줄 카드(「검토 우선순위」 칩)까지 기다린다 — 통합 목록을 늦게 받으면 칩 전에 재서 「못 찾음」 거짓 위반이 났다(36차 · 1751800).
  // 가상 예시(synthetic-)는 통합 목록에 없어 칩이 없다.
  if (path === "/opportunities?tab=sheet") return `!!document.querySelector("[data-sheet-notice]") && !/요구사항을 불러오는 중/.test(document.querySelector("main")?.innerText || "") && (/[?&]notice=synthetic-/.test(location.search) || [...document.querySelectorAll("[data-sheet-notice] [data-chip]")].some((c) => /^검토 우선순위/.test(txt(c))))`;
  if (path === "/opportunities") return `document.querySelectorAll("article").length > 0 && !/계산 중…/.test(document.querySelector("main")?.innerText || "")`;
  // 고른 것이 있으면(주소에 notice · support) 상세의 「검토 우선순위」까지 기다린다 — 부하가 있으면 상세 전에 재서 거짓 위반이 났다(검수 LNK-R9)
  // 「검토 우선순위」는 이제 범례 · 눈금 설명에도 늘 있다(27차 RDR-22) — 상세 칸 머리(.mc-panel > span)만 본다 · 불러오는 중이면 아직이다.
  if (path === "/radar") return `!/사업기회를 불러오는 중/.test(document.body.innerText || "") && (/[?&](notice|support)=/.test(location.search) ? [...document.querySelectorAll(".mc-panel > span")].some((s) => (s.textContent || "").trim() === "검토 우선순위") : /조회 시각|사업기회를 선택하세요|검토 우선순위/.test(document.body.innerText || ""))`;
  if (path === "/plan") return `!!document.querySelector("[data-plan-target]") && !/불러오는 중/.test(document.querySelector("main")?.innerText || "")`;
  if (path === "/company") return `!!document.querySelector("[data-organization-picker] select")`;
  if (path === "/guide") return `!!document.querySelector("article.guide-body h2") && !!document.querySelector("[data-organization-picker] select")`;
  return `!/불러오는 중/.test(document.querySelector("main")?.innerText || "")`;
}

/** 화면이 실제로 떴나(39차 §3-F-5) — 개발 캐시가 깨지면 동적 경로가 「찾는 화면이 없습니다」(404)로 끝났고 이 검사는 빈 통과로 셌다. */
const LANDED = `const text = document.body.innerText || "";
  if (/찾는 화면이 없습니다|This page could not be found/.test(text)) return "화면이 뜨지 않았다 — 404(찾는 화면이 없습니다)";
  if (!document.querySelector("h1")) return "화면이 뜨지 않았다 — 제목(h1) 없음";
  return null;`;
/** 뜨지 않은 화면 — 판정에서 문제로 센다(통과로 세지 않는다). */
const NOT_LANDED = [];

async function open(cdp, url) {
  await cdp.send("Page.navigate", { url: new URL(url, BASE).href });
  await sleep(1200);
  const parsed = new URL(url, BASE);
  const path = parsed.pathname === "/opportunities" && parsed.searchParams.get("tab") === "sheet" ? "/opportunities?tab=sheet" : parsed.pathname;
  await settle(cdp, readyOf(path.startsWith("/support/") ? "/support" : path));
  const missing = await cdp.evaluate(LANDED).catch(() => null);
  if (missing && !NOT_LANDED.some((m) => m.startsWith(url + " "))) NOT_LANDED.push(`${url} — ${missing}`);
}

async function clickMenu(cdp, label) {
  const result = await cdp.evaluate(`
    const nav = document.querySelector('nav[aria-label="화면 이동"]');
    if (!nav) return "메뉴 없음";
    const locked = [...nav.querySelectorAll("[data-nav-disabled]")].find((s) => txt(s).replace(/\\((전체 화면|전체 보기)\\)/g, "").trim() === ${JSON.stringify(label)});
    if (locked) return "잠김";
    const link = [...nav.querySelectorAll("a")].find((a) => vis(a) && txt(a).replace(/\\((전체 화면|전체 보기)\\)/g, "").trim() === ${JSON.stringify(label)});
    if (!link) return "항목 없음";
    link.click();
    return "눌림 " + link.getAttribute("href");`);
  if (!result.startsWith("눌림")) return result;
  const want = PATH_OF[label];
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const path = await cdp.evaluate(`return location.pathname;`).catch(() => "");
    if (path === want) break;
    await sleep(300);
  }
  await sleep(800);
  await settle(cdp, readyOf(want));
  return result;
}

async function clearStore(cdp) {
  await cdp.send("Page.navigate", { url: new URL("/favicon.ico", BASE).href });
  await sleep(700);
  await cdp.evaluate(`Object.keys(localStorage).filter((k) => k.startsWith("bidpilot.")).forEach((k) => localStorage.removeItem(k)); return true;`).catch(() => null);
}

async function setStore(cdp, key, value) {
  await cdp.evaluate(`localStorage.setItem(${JSON.stringify(key)}, ${JSON.stringify(value)}); return true;`);
}

async function roundTrip(cdp, startUrl, steps) {
  await open(cdp, startUrl);
  const rows = [{ step: "시작", clicked: "", ...(await cdp.evaluate(PROBE_CARRY)) }];
  for (const label of steps) {
    const clicked = await clickMenu(cdp, label);
    rows.push({ step: label, clicked, ...(await cdp.evaluate(PROBE_CARRY)) });
  }
  return rows;
}

async function main() {
  const browser = BROWSERS.find((p) => existsSync(p));
  if (!browser) throw new Error("Edge/Chrome 을 찾지 못했습니다");
  // 포트마다 다른 프로필 — 두 번 동시에 돌리면 같은 폴더를 지우다 EBUSY 로 죽었다(검수 R27U-HD-07)
  const profile = join(process.env.TEMP || ".", `bidpilot-check-page-unity-${PORT}`);
  rmSync(profile, { recursive: true, force: true });
  const child = spawn(browser, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--headless=new", "--no-first-run", "--hide-scrollbars", "--disable-background-timer-throttling", "about:blank"], { stdio: "ignore" });
  const heads = [];
  const fields = [];
  const trips = {};
  const orgRequests = [];
  let firstBid = null;
  let reviewSheet = { found: false };
  const planEntries = [];
  /** 예시 지원사업의 회사 방식(정렬 없이 받은 목록) 기업마당 자리 — 메뉴 한 바퀴의 기대를 정한다(37차). 못 읽으면 null. */
  let supportCompanyRank = null;
  // 위반 목록은 맨 앞에 — 첫 입찰을 못 찾았을 때 알리는 줄이 선언보다 먼저 돌아 ReferenceError 로 죽었다(검수 R27U-HD-02)
  const problems = [];
  try {
    const cdp = await connect(PORT);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await clearStore(cdp);
    try {
      const listing = await (await fetch(`${BACKEND}/api/business-opportunities?source=bizinfo&days=30`)).json();
      const at = (listing.items || []).findIndex((i) => i.id === SUPPORT);
      supportCompanyRank = at >= 0 ? at + 1 : Infinity;
      console.log(`예시 지원사업 ${SUPPORT} — 회사 방식(${listing.ranking_method ?? "?"}) 기업마당 ${Number.isFinite(supportCompanyRank) ? `${supportCompanyRank}위` : "목록에 없음"}`);
    } catch {
      supportCompanyRank = null;
    }

    // (1)(2) 머리
    const SCREENS = [
      { name: "대시보드", url: "/?mode=full", menu: "대시보드" },
      { name: "입찰 분석", url: `/analysis?notice=${DEMO}&welcome=0&mode=full&guided=0`, menu: "입찰 분석" },
      { name: "레이더", url: "/radar?mode=full", menu: "레이더" },
      { name: "사업기회", url: "/opportunities?mode=full", menu: "사업기회" },
      { name: "요구사항 정리표 탭", url: `/opportunities?tab=sheet&notice=${DEMO}&mode=full`, menu: "사업기회" },
      // 메뉴에 없다 — 사업기회에서 들어가는 화면이라 메뉴는 「사업기회」가 켜진다(37차 §3-E)
      { name: "사업계획서 작성", url: `/plan?notice=${DEMO}&mode=full`, menu: "사업기회", h1: "사업계획서 작성" },
      { name: "회사자료", url: "/company?mode=full", menu: "회사자료" },
      { name: "실전 가이드", url: "/guide?mode=full", menu: "실전 가이드" },
      { name: "지원사업 신청 분석", url: `/support/${SUPPORT}?mode=full`, menu: null },
    ];
    for (const screen of SCREENS) {
      await open(cdp, screen.url);
      heads.push({ ...screen, ...(await cdp.evaluate(PROBE_HEAD)) });
      if (screen.menu === "사업기회" && screen.name === "사업기회") {
        // 목록 첫 입찰 — 「●나라장터 입찰」 행의 첫 링크에서 id 를 읽는다. 입찰 탭으로 연다 — 37차부터 샘플에듀 기본이 실무 우선순위라
        // 「전체」 탭 첫 20행이 지원사업으로 찰 수 있다(두 출처를 한 축에 섞지 않는다).
        await open(cdp, "/opportunities?src=g2b&mode=full");
        firstBid = await cdp.evaluate(`
          const row = [...document.querySelectorAll("main article")].find((a) => /나라장터 입찰/.test(txt(a.querySelector('[data-visibility-strip="card-head"]'))));
          const href = row ? [...row.querySelectorAll("a[href]")].map((a) => a.getAttribute("href")).find((h) => /notice=/.test(h)) : null;
          const m = href ? /notice=([^&]+)/.exec(href) : null;
          return m ? decodeURIComponent(m[1]) : null;`);
      }
    }

    // (2b) 「검토 중」 탭의 「요구사항 정리표 열기」 — 행 입구와 같이 탭이 바뀌는가(29차 R28-02 · 같은 주소 링크는 무반응이었다)
    await open(cdp, "/opportunities?tab=review&mode=full");
    await sleep(1500);
    reviewSheet = await cdp.evaluate(`
      const b = document.querySelector("[data-review-sheet-open]");
      if (!b) return { found: false };
      b.click();
      await new Promise((r) => setTimeout(r, 1800));
      const tab = [...document.querySelectorAll("[role=tab][aria-selected=true]")].map((t) => txt(t))[0] ?? null;
      return { found: true, tab, notice: document.querySelector("[data-sheet-notice]")?.getAttribute("data-sheet-notice") ?? null };`);
    if (reviewSheet.found && (reviewSheet.tab !== "요구사항 정리표" || !reviewSheet.notice)) {
      problems.push(`(2b) 「검토 중」 → 「요구사항 정리표 열기」: 탭 「${reviewSheet.tab ?? "-"}」 · 공고 「${reviewSheet.notice ?? "-"}」`);
    }

    // (3) 같은 공고 네 화면
    const TARGETS = [
      // 목록 · 레이더는 점수순(sort=priority)을 주소에 적어 연다 — 37차부터 샘플에듀 기본이 실무 우선순위라 예시 공고가 첫 화면 밖일 수 있다.
      // 이 표는 「같은 공고의 값이 화면마다 같은가」를 재는 것이고 순서는 재지 않는다.
      { id: DEMO, kind: "notice", urls: [`/analysis?notice=${DEMO}&welcome=0&mode=full&guided=0`, `/opportunities?notice=${DEMO}&mode=full&sort=priority`, `/radar?notice=${DEMO}&sort=priority`, `/opportunities?tab=sheet&notice=${DEMO}`] },
      ...(firstBid ? [{ id: firstBid, kind: "notice", urls: [`/analysis?notice=${firstBid}&welcome=0&mode=full&guided=0`, `/opportunities?notice=${firstBid}&mode=full&src=g2b`, `/radar?notice=${firstBid}`, `/opportunities?tab=sheet&notice=${firstBid}`] }] : []),
      { id: SUPPORT, kind: "support", urls: [`/analysis?support=${SUPPORT}&welcome=0&mode=full&guided=0`, `/opportunities?support=${SUPPORT}&mode=full&sort=priority`, `/radar?support=${SUPPORT}&sort=priority`, `/support/${SUPPORT}?mode=full`] },
    ];
    for (const target of TARGETS) {
      const cells = [];
      for (const url of target.urls) {
        await open(cdp, url);
        cells.push({ url, ...(await cdp.evaluate(PROBE_FIELDS)) });
      }
      fields.push({ id: target.id, kind: target.kind, cells });
    }

    // (4) 한 바퀴 — 입찰 · 전체 보기
    const LOOP = ["레이더", "사업기회", "회사자료", "실전 가이드", "입찰 분석"];
    if (!firstBid) problems.push("(3)(4) 사업기회 목록에서 첫 입찰을 못 찾음 — 실공고 표와 입찰 바퀴 둘을 재지 못했다");
    if (firstBid) {
      await clearStore(cdp);
      trips["입찰 · 전체 보기"] = await roundTrip(cdp, `/analysis?notice=${firstBid}&welcome=0&mode=full&guided=0`, LOOP);
      await clearStore(cdp);
      trips["입찰 · 쉬운 보기"] = await roundTrip(cdp, `/analysis?notice=${firstBid}&welcome=0&mode=simple&guided=0`, LOOP);
    }
    await clearStore(cdp);
    trips["지원사업 · 전체 보기"] = await roundTrip(cdp, `/support/${SUPPORT}?mode=full`, ["입찰 분석", ...LOOP]);

    // (4c) 사업기회 행의 「사업계획서 작성 →」(지원사업) · 「제안서 작성 →」(입찰) — 그 공고로 열리고, 길 표시의
    //      「← 사업기회로」가 들어온 탭 · 정렬 · 검색을 그대로 싣는다(37차 §3-E-2 · 3). 쓰기 없음(보기만).
    const PLAN_ENTRIES = [
      // 정렬은 회사 기본(샘플에듀 실무순)이 아닌 것으로 — 돌아가기 주소에 정렬이 실려야 잴 수 있다. 예시 공고가 첫 20행 안에 드는 정렬을 고른다.
      { name: "지원사업", id: SUPPORT, kind: "bizinfo", sort: "priority", label: "사업계획서 작성 →", url: `/opportunities?src=bizinfo&sort=priority&support=${SUPPORT}&mode=full` },
      // 입찰은 공고번호 검색도 건다 — 실무순 1위가 마감 여유순 첫 화면 밖일 수 있다(39차 10-18). 돌아가기 주소에 검색도 실려야 한다.
      ...(firstBid ? [{ name: "입찰", id: firstBid, kind: "g2b", sort: "slack", q: firstBid.replace(/^g2b-/, "").replace(/-\d+$/, ""), label: "제안서 작성 →" }] : []).map((entry) => ({
        ...entry,
        url: `/opportunities?src=g2b&sort=slack&q=${encodeURIComponent(entry.q)}&notice=${firstBid}&mode=full`,
      })),
    ];
    for (const entry of PLAN_ENTRIES) {
      await clearStore(cdp);
      await open(cdp, entry.url);
      await sleep(1500);
      const clicked = await cdp.evaluate(`
        const rows = [...document.querySelectorAll("main article, main [data-simple-row]")];
        const row = rows.find((r) => r.getAttribute("data-current-notice") === ${JSON.stringify(entry.id)}) ?? null;
        const link = row ? row.querySelector('[data-plan-link="${entry.kind}"]') : null;
        if (!link) return { ok: false, why: row ? "행에 단추 없음" : "행을 못 찾음" };
        const text = txt(link);
        link.click();
        return { ok: true, text };`);
      if (!clicked.ok) {
        problems.push(`(4c) ${entry.name}: 사업기회에서 「${entry.label}」 — ${clicked.why}`);
        continue;
      }
      const until = Date.now() + 20000;
      while (Date.now() < until && (await cdp.evaluate(`return location.pathname;`).catch(() => "")) !== "/plan") await sleep(300);
      await sleep(1500);
      const landed = await cdp.evaluate(`return {
        path: location.pathname,
        target: document.querySelector("[data-plan-target]")?.getAttribute("data-plan-target") ?? null,
        back: document.querySelector("[data-plan-back]")?.getAttribute("href") ?? null,
        crumb: txt(document.querySelector("[data-plan-breadcrumb]")),
        active: [...document.querySelectorAll('nav[aria-label="화면 이동"] [aria-current="page"]')].map((a) => txt(a).replace(/[(]전체 (화면|보기)[)]/g, "").trim()),
      };`);
      planEntries.push({ ...entry, text: clicked.text, ...landed });
      if (clicked.text !== entry.label) problems.push(`(4c) ${entry.name}: 단추 글 「${clicked.text}」 ≠ 「${entry.label}」`);
      if (landed.path !== "/plan" || landed.target !== entry.id) problems.push(`(4c) ${entry.name}: 연 것 ${landed.path} · ${landed.target ?? "-"} ≠ ${entry.id}`);
      if (!landed.back || !landed.back.startsWith("/opportunities?") || !landed.back.includes(`src=${entry.kind}`) || !landed.back.includes(`sort=${entry.sort}`)) {
        problems.push(`(4c) ${entry.name}: 「← 사업기회로」 주소 ${landed.back ?? "없음"} — 들어온 탭 · 정렬이 없다`);
      }
      if (entry.q && !(landed.back || "").includes(`q=${encodeURIComponent(entry.q)}`)) {
        problems.push(`(4c) ${entry.name}: 「← 사업기회로」 주소 ${landed.back ?? "없음"} — 들어온 검색이 없다`);
      }
      if (!/사업기회\s*›\s*사업계획서 작성/.test(landed.crumb || "")) problems.push(`(4c) ${entry.name}: 길 표시 「${landed.crumb || "없음"}」`);
      if (landed.active.join() !== "사업기회") problems.push(`(4c) ${entry.name}: 메뉴 활성 「${landed.active.join() || "없음"}」 ≠ 사업기회`);
    }

    // 회사 한 바퀴 — 합성 회사로 가는 백엔드 요청은 막는다(쓰기 없음)
    await clearStore(cdp);
    await setStore(cdp, "bidpilot.organization.v1", TEST_ORG);
    let stepName = "시작";
    await cdp.send("Fetch.enable", { patterns: [{ urlPattern: `${BACKEND}/*`, requestStage: "Request" }] });
    cdp.on("Fetch.requestPaused", (p) => {
      const body = `${p.request.url} ${p.request.postData ?? ""}`;
      const org = /org-[a-z0-9-]+/.exec(body)?.[0] ?? null;
      if (org) orgRequests.push({ seq: orgRequests.length, step: stepName, org, path: new URL(p.request.url).pathname });
      if (body.includes(TEST_ORG)) cdp.send("Fetch.failRequest", { requestId: p.requestId, errorReason: "BlockedByClient" }).catch(() => null);
      else cdp.send("Fetch.continueRequest", { requestId: p.requestId }).catch(() => null);
    });
    await open(cdp, `/analysis?welcome=0&mode=full&guided=0`);
    const orgRows = [{ step: "시작", clicked: "", ...(await cdp.evaluate(PROBE_CARRY)) }];
    for (const label of LOOP) {
      stepName = label;
      const clicked = await clickMenu(cdp, label);
      orgRows.push({ step: label, clicked, ...(await cdp.evaluate(PROBE_CARRY)) });
    }
    trips["회사 · org-test-alpha(요청 막음)"] = orgRows;
    await cdp.send("Fetch.disable");
  } finally {
    child.kill();
  }

  // ---- 판정 ----
  for (const miss of NOT_LANDED) problems.push(`(0) ${miss}`);
  for (const h of heads) {
    if (h.h1s.length !== 1) problems.push(`(1) ${h.name}: 보이는 h1 ${h.h1s.length}개 — ${h.h1s.join(" | ")}`);
    if (h.menu) {
      if (h.active.length !== 1 || h.active[0] !== h.menu) problems.push(`(1) ${h.name}: 활성 메뉴 「${h.active.join(",")}」 ≠ 「${h.menu}」`);
      if (h.h1s[0] !== (h.h1 ?? h.menu)) problems.push(`(1) ${h.name}: h1 「${h.h1s[0] ?? "-"}」 ≠ 「${h.h1 ?? h.menu}」`);
    }
    if (h.orderProblems.length) problems.push(`(2) ${h.name}: 머리 오른쪽 순서 ${h.orderProblems.join(" · ")}`);
    if (h.outside.length) problems.push(`(2) ${h.name}: 머리 밖에 ${h.outside.join(" · ")}`);
    if (!h.order.includes("?")) problems.push(`(2) ${h.name}: 머리에 「?」 없음`);
  }
  // 마감은 **글자 전체**(「입찰 마감 D-7」 · 「입찰 종료」)를 견준다 — §3-E-6 「판정 · 마감 · 검토 우선순위 글자가 같은지」
  const dday = (s) => (s ? s.replace(/\s+/g, " ").trim() : null);
  const pnum = (s) => (s ? /(\d[\d,]*|미산정|점수 없음)/.exec(s)?.[1] ?? null : null);
  for (const f of fields) {
    const shown = f.cells.filter((c) => c.found);
    // 값이 사라진 화면을 조용히 빼지 않는다(검증 G5-V4) — 실공고 대상은 네 화면 모두 판정 · 마감 · 우선순위가 있어야 한다
    // 지원사업도 — 판정은 목록 · 레이더 칸에만, 마감 · 우선순위는 네 칸 모두(검수 R27U-HD-01)
    if (!String(f.id).startsWith("synthetic")) {
      for (const c of f.cells) {
        const need = f.kind === "support" && !/^\/(opportunities|radar)/.test(c.screen) ? ["deadline", "priority"] : ["verdict", "deadline", "priority"];
        if (!c.found) problems.push(`(3) ${f.id} ${c.screen}: 그 공고를 화면에서 못 찾음`);
        else for (const key of need) if (!c[key]) problems.push(`(3) ${f.id} ${c.screen}: ${key} 값 없음`);
      }
    }
    for (const [key, norm] of [["verdict", (v) => v], ["deadline", dday], ["priority", pnum]]) {
      const values = [...new Set(shown.map((c) => norm(c[key])).filter(Boolean))];
      if (values.length > 1) problems.push(`(3) ${f.id} ${key}: 화면마다 다름 — ${shown.map((c) => `${c.screen} 「${c[key] ?? "—"}」`).join(" · ")}`);
    }
    for (const c of shown) if (c.priority && /점|\/\s*100/.test(c.priority)) problems.push(`(3) ${f.id} ${c.screen}: 검토 우선순위에 단위 「${c.priority}」`);
  }
  for (const [name, rows] of Object.entries(trips)) {
    const start = rows[0];
    const company = start.company;
    for (const r of rows) {
      if (r.company !== null && r.company !== company) problems.push(`(4) ${name} ${r.step}: 회사 ${r.company} ≠ 시작 ${company}`);
      if (r.clicked && !r.clicked.startsWith("눌림")) problems.push(`(4) ${name} ${r.step}: 메뉴 ${r.clicked}`);
    }
    if (name.startsWith("입찰")) {
      const id = start.urlNotice ?? start.shown;
      for (const r of rows) {
        const path = r.url.split("?")[0];
        if ((path === "/analysis" || path === "/plan" || path === "/opportunities") && r.shown !== id) problems.push(`(4) ${name} ${r.step}: 공고 「${r.shown ?? "-"}」 ≠ 「${id}」`);
        if (path === "/radar" && !(r.detailTitle && start.optionText?.includes(r.detailTitle))) problems.push(`(4) ${name} ${r.step}: 레이더 상세 「${r.detailTitle ?? "없음"}」 ≠ 고른 공고`);
        if (path === "/company" && r.shown !== `/analysis?notice=${id}`) problems.push(`(4) ${name} ${r.step}: 「보던 공고로 돌아가기」 ${r.shown ?? "없음"}`);
      }
      // 37차 §3-F — 보기는 저장하지 않고 이 탭 안에서만 이어진다 · **대시보드는 열 때마다 쉬운 보기**(주소 ?mode= 가 있으면 그 값).
      // 그래서 기대 보기는 단계마다 따라간다: 시작은 시작 주소의 보기, 메뉴로 대시보드에 오면 쉬운 보기로 바뀌고 그 뒤 화면이 그것을 잇는다.
      let current = name.endsWith("쉬운 보기") ? "simple" : "full";
      for (const r of rows) {
        const path = r.url.split("?")[0];
        const urlMode = new URL(r.url, BASE).searchParams.get("mode");
        if (path === "/analysis" && r.step !== "시작") current = urlMode === "full" || urlMode === "simple" ? urlMode : "simple";
        const hasSimple = path === "/" || path === "/analysis" || path === "/opportunities";
        const oneScreen = path === "/plan" || path === "/guide"; // 두 보기 공통 한 화면(28차 · 32차 가이드) — 보기 전환 · 「전체 보기만」 줄 없음
        if (r.store.viewmode !== null) problems.push(`(4) ${name} ${r.step}: 보기를 저장소에 남김(${r.store.viewmode}) — 37차부터 저장하지 않는다`);
        if (hasSimple && r.toggle !== current) problems.push(`(4) ${name} ${r.step}: 보기 전환 ${r.toggle} ≠ ${current}`);
        if (!hasSimple && !oneScreen && r.fullOnlyNote !== (current === "simple")) problems.push(`(4) ${name} ${r.step}: 「전체 보기만 있습니다」 한 줄 ${r.fullOnlyNote ? "있음" : "없음"}`);
      }
    }
    if (name.startsWith("지원사업")) {
      // 메뉴로 가면 정렬이 회사 방식이다(샘플에듀 = 실무 우선순위 · 37차). 예시가 그 첫 화면(기업마당 6위 · 레이더 기본 그림) 밖이면
      // 레이더 상세 · 목록 강조는 재지 않는다 — 그 공고가 그 화면 첫 칸에 없는 것이 맞다. 대신 다른 공고를 연 것은 여전히 위반이다.
      const firstScreen = supportCompanyRank !== null && supportCompanyRank <= 6;
      for (const r of rows) {
        const path = r.url.split("?")[0];
        if (path === "/analysis" && r.shown !== SUPPORT) problems.push(`(4) ${name} ${r.step}: 입찰 분석이 연 것 「${r.shown ?? "-"}」 ≠ 지원사업`);
        if (path === "/opportunities" && (firstScreen ? r.shown !== SUPPORT : r.shown && r.shown !== SUPPORT)) problems.push(`(4) ${name} ${r.step}: 목록 강조 「${r.shown ?? "-"}」`);
        if (path === "/radar" && firstScreen && !(r.detailTitle && rows.find((x) => x.optionText)?.optionText?.includes(r.detailTitle))) problems.push(`(4) ${name} ${r.step}: 레이더 상세 「${r.detailTitle ?? "없음"}」 ≠ 지원사업`);
        if (path === "/company" && r.shown !== `/support/${SUPPORT}`) problems.push(`(4) ${name} ${r.step}: 「보던 지원사업으로 돌아가기」 ${r.shown ?? "없음"}`);
        // 28차 — 메뉴 잠금을 없앴다. 지원사업을 보는 중이면 사업계획서 작성이 그 지원사업을 연다.
        if (path === "/plan" && r.shown !== SUPPORT) problems.push(`(4) ${name} ${r.step}: 사업계획서 작성이 연 것 「${r.shown ?? "-"}」 ≠ 지원사업`);
        if (r.rfpLocked) problems.push(`(4) ${name} ${r.step}: 메뉴에 잠긴 항목이 남아 있다`);
      }
    }
    if (name.startsWith("회사")) {
      for (const r of rows) if (r.company !== TEST_ORG) problems.push(`(4) ${name} ${r.step}: 회사 선택기 ${r.company}`);
      // 첫 화면을 새로 열 때 hydration 렌더는 저장된 회사를 아직 모른다(서버 값 = 기본 회사) — 그 요청은 곧바로
      // 저장된 회사 요청으로 바뀌고 응답은 토큰으로 버린다. 그래서 **저장된 회사로 한 번 물은 뒤에** 다른 회사로 묻는 것만 위반이다.
      const firstTest = orgRequests.find((q) => q.org === TEST_ORG)?.seq ?? Infinity;
      for (const q of orgRequests) if (q.org !== TEST_ORG && (q.seq > firstTest || q.step !== "시작")) problems.push(`(4) ${name} ${q.step}: 백엔드 요청이 다른 회사로 — ${q.org} ${q.path}`);
    }
  }

  if (AS_JSON) {
    console.log(JSON.stringify({ firstBid, heads, fields, trips, orgRequests, problems }, null, 1));
  } else {
    console.log("## (1)(2) 머리 — 1440×900");
    console.log("| 화면 | 주소 | 보이는 h1 | 활성 메뉴 | 머리 오른쪽 순서 | 머리 밖 |");
    console.log("|---|---|---|---|---|---|");
    for (const h of heads) console.log(`| ${h.name} | \`${h.url}\` | ${h.h1s.join(" / ") || "—"} (${h.h1s.length}) | ${h.active.join(",") || "—"} | ${h.order.join(" → ")}${h.orderProblems.length ? " ✗" : ""} | ${h.outside.join(" · ") || "—"} |`);
    console.log(`\n(2b) 「검토 중」 → 「요구사항 정리표 열기」: ${reviewSheet.found ? `탭 「${reviewSheet.tab}」 · 공고 ${reviewSheet.notice}` : "검사 못 함 — 검토 중 공고에 정리표 단추가 없음(목록에 있는 공고뿐)"}`);
    console.log("\n(4c) 사업기회 → 사업계획서 작성 단추 (37차 §3-E)");
    for (const e of planEntries) console.log(`  ${e.name}: 「${e.text}」 → ${e.path} · ${e.target} · 돌아가기 ${e.back} · 메뉴 ${e.active.join() || "-"}`);
    console.log(`\n## (3) 같은 공고 — 참가 판정 · 마감 · 검토 우선순위 (첫 입찰 ${firstBid ?? "못 찾음"})`);
    for (const f of fields) {
      console.log(`\n**${f.id}**\n`);
      console.log(`| 항목 | ${f.cells.map((c) => c.screen).join(" | ")} |`);
      console.log(`|---|${f.cells.map(() => "---").join("|")}|`);
      for (const [key, label] of [["verdict", "참가 판정"], ["deadline", "마감"], ["priority", "검토 우선순위"]]) {
        console.log(`| ${label} | ${f.cells.map((c) => (c.found ? c[key] ?? "—" : `(${c.note})`)).join(" | ")} |`);
      }
    }
    for (const [name, rows] of Object.entries(trips)) {
      console.log(`\n## (4) 한 바퀴 — ${name}\n`);
      console.log("| 단계 | 메뉴 | 주소 | h1 | 보이는 선택 | 회사 | 보기 전환 · 저장 | 「전체 보기만」 줄 | 메뉴 잠김 |");
      console.log("|---|---|---|---|---|---|---|---|---|");
      for (const r of rows) console.log(`| ${r.step} | ${r.clicked.replace(/^눌림 /, "")} | \`${r.url}\` | ${r.h1.slice(0, 24)} | ${r.shown ?? "—"} | ${r.company ?? "—"} | ${r.toggle ?? "—"} · ${r.store.viewmode ?? "—"} | ${r.fullOnlyNote ? "있음" : "—"} | ${r.rfpLocked ? "잠김" : "—"} |`);
    }
    const byOrg = {};
    for (const q of orgRequests) byOrg[`${q.step} ${q.org}`] = (byOrg[`${q.step} ${q.org}`] ?? 0) + 1;
    console.log(`\n회사 한 바퀴 백엔드 요청(${TEST_ORG} 는 막음): ${Object.entries(byOrg).map(([k, n]) => `${k} ${n}`).join(" · ") || "없음"} — 「시작」의 기본 회사 요청은 첫 화면 hydration 렌더 몫(응답은 버려짐 · 위반 아님)`);
    console.log(problems.length ? `\n✗ 위반 ${problems.length}\n  - ${problems.join("\n  - ")}` : "\n✓ 페이지 통일 · 연결 위반 없음");
  }
  process.exit(problems.length ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
