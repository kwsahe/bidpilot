/**
 * 지도 수용 검사 (27차 · prompt_17 §3-D) — 「지금 정거장만 그리기」가 약속을 지키는가.
 *
 * 폭 셋(1440×900 · 1024×768 · 390×844) × 보기 둘(3D · 2D) × 레일 1~8 을 차례로 누르며 잰다:
 *  - 지금이 아닌 정거장에 그린 기호 0 — `cosmosDrawnMarks === cosmosStationNodes`
 *  - 지도 안 · 공고 카드 · 안내 줄의 원문자(①~⑳) 0
 *  - 그린 기호마다 이름표 하나(무명점 0) · 이름표 겹친 쌍 0 · 13px 미만 글자 0
 *  - 한 화면 모양 2 종 이하 · ▲ 와 ⚠ 가 같이 나오지 않음 · 지금 정거장 표시 24 이하
 *  - 아무것도 안 골랐을 때 선 0 · 고르면 3 이하(2D 는 색 · 움직이는 점선도)
 *  - 레일 「!」 「✕」 단계에만 같은 낱말 알약 (8/8)
 *  - 지금 정거장 이름 = 레일 이름 · 짧은 이름 낱말 ⊂ 레일 이름
 *  - 선택 카드는 고른 항목이 지금 정거장에 있을 때만 · 「생략」 글자 없음
 *  - 지금이 아닌 정거장 이름을 누르면 그 정거장으로
 * 그리고 1440 · 390 첫 화면에서 범례 줄(`data-map-key`)이 스크롤 한 번 안에 보이고 낱말 넷이 범례 시트와 같은가.
 *
 * 쓰기 없음 · 서버를 바꾸지 않음. 실행: node scripts/check_map.mjs [--base http://localhost:3110] [--json]
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
const PORT = Number(argOf("--port", "9241"));
const AS_JSON = args.includes("--json");
const SIZES = argOf("--sizes", "1440x900,1024x768,390x844").split(",").map((s) => {
  const [width, height] = s.split("x").map(Number);
  return { width, height };
});
const VIEWS = argOf("--views", "3d,2d").split(",");
const URL_OF = (view) => `/analysis?notice=synthetic-rfp-0001&welcome=0&mode=full&guided=0&view=${view}`;
const BROWSERS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];
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

/** 지금 화면을 잰다 — 페이지 안에서 도는 문자열. */
const PROBE = String.raw`
  const d = document.documentElement.dataset;
  const stage = document.querySelector('section[data-tour="stage"]');
  const view = stage?.querySelector("canvas") ? "3D" : stage?.querySelector("svg") ? "2D" : "?";
  const station = d.cosmosStation ?? null;
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const labels = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter((el) => el.getAttribute("data-cosmos-station") === station && visible(el));
  const sizeOf = (el) => {
    const own = parseFloat(el.getAttribute("font-size") || "") || parseFloat(getComputedStyle(el).fontSize) || 0;
    const parent = el.parentElement ? parseFloat(el.parentElement.getAttribute("font-size") || "") : 0;
    return own || parent;
  };
  const small = labels.filter((el) => sizeOf(el) < 12.95).length;
  const boxes = labels.map((el) => el.getBoundingClientRect());
  let overlaps = 0;
  for (let i = 0; i < boxes.length; i += 1) for (let j = i + 1; j < boxes.length; j += 1) {
    const a = boxes[i], b = boxes[j];
    if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2) overlaps += 1;
  }
  // 정거장 머리(가장 큰 글자) · 낱말 알약끼리 겹친 쌍 — check_visibility 좁은 캔버스 검사와 같은 방식
  const headBoxes = [];
  for (const g of document.querySelectorAll("[data-cosmos-station-name]")) {
    let best = null, size = 0;
    for (const el of [g, ...g.querySelectorAll("*")]) {
      if (!el.childNodes.length || ![...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 2 || r.height <= 2) continue;
      const px = parseFloat(getComputedStyle(el).fontSize) || 0;
      if (px > size) { size = px; best = el; }
    }
    if (best) headBoxes.push({ box: best.getBoundingClientRect(), text: best.textContent.trim() });
  }
  for (const flag of document.querySelectorAll("[data-station-flag]")) {
    const box = flag.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) headBoxes.push({ box, text: "알약:" + flag.getAttribute("data-station-flag") });
  }
  const headOverlaps = [];
  for (let i = 0; i < headBoxes.length; i += 1) for (let j = i + 1; j < headBoxes.length; j += 1) {
    const a = headBoxes[i].box, b = headBoxes[j].box;
    if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2) headOverlaps.push(headBoxes[i].text + "↔" + headBoxes[j].text);
  }
  // 머리 안 **모든** 글 조각을 다른 머리의 글 조각과 견준다 — 가장 큰 글자 하나만 보면 같은 크기 이름끼리 겹친 것을 놓쳤다
  const leaves = (g) => [...g.querySelectorAll("span, text, tspan")].filter((el) => !el.querySelector("span, tspan") && (el.textContent || "").trim() && (() => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; })());
  const heads = [...document.querySelectorAll("[data-cosmos-station-name]")].map((g) => ({ id: g.getAttribute("data-cosmos-station-name"), boxes: leaves(g).map((el) => ({ box: el.getBoundingClientRect(), text: (el.textContent || "").trim().slice(0, 8) })) }));
  for (let i = 0; i < heads.length; i += 1) for (let j = i + 1; j < heads.length; j += 1) {
    for (const a of heads[i].boxes) for (const b of heads[j].boxes) {
      if (Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left) > 2 && Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top) > 2) headOverlaps.push(heads[i].id + "「" + a.text + "」↔" + heads[j].id + "「" + b.text + "」");
    }
  }
  // 머리와 지금 정거장 이름표가 겹치는가
  labels.forEach((el, k) => {
    const r = boxes[k];
    for (const h of headBoxes) {
      if (Math.min(h.box.right, r.right) - Math.max(h.box.left, r.left) > 2 && Math.min(h.box.bottom, r.bottom) - Math.max(h.box.top, r.top) > 2) headOverlaps.push(h.text + "↔이름표 「" + (el.textContent || "").trim().slice(0, 12) + "」");
    }
  });
  // 지금이 아닌 정거장에 선 이름표(27차 검수 R27D-05 — 「그린 = 그릴」 만으로는 자기 참조라 실패할 수 없다)
  const offStation = [...document.querySelectorAll("[data-cosmos-label][data-cosmos-station]")].filter((el) => el.getAttribute("data-cosmos-station") !== station && visible(el) && parseFloat(getComputedStyle(el).opacity || "1") > 0.05).length;
  // 판정 낱말이 이름을 잘라 먹었는가(27차 검수 R27D-OWN-01) — 이름이 잘렸는데 알약이 낱말 그대로면 위반
  let verdictTrunc = 0;
  for (const pill of document.querySelectorAll("[data-cosmos-verdict]")) {
    if (pill.getAttribute("data-cosmos-verdict-mode") !== "word") continue;
    const holder = pill.closest("[data-cosmos-label]") || pill.parentElement;
    if (!holder || !visible(holder)) continue;
    if (pill instanceof SVGElement) {
      // 2D 는 글자 수로 줄인다 — 알약 때문에 줄였을 때만 적어 둔다(긴 문장은 longText 가 처음부터 줄인다)
      if (pill.getAttribute("data-cosmos-verdict-cut") === "1") verdictTrunc += 1;
    } else {
      const name = pill.previousElementSibling;
      if (name && name.scrollWidth - name.clientWidth > 1) verdictTrunc += 1;
    }
  }
  // 지금이 아닌 정거장 이름이 보이는가(27차 검수 R27REQ-01 — 좁은 칸에서 sr-only 로 숨었다)
  const hiddenNames = [...document.querySelectorAll('[data-cosmos-station-name]:not([data-cosmos-station-tier="current"])')].filter((g) => {
    const texts = [...g.querySelectorAll("span, text, tspan")].filter((el) => /[가-힣]{2}/.test(el.textContent || "") && !el.querySelector("span, tspan"));
    return !texts.some((el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; });
  }).map((g) => g.getAttribute("data-cosmos-station-name"));
  const circled = (root) => !!root && /[\u2460-\u2473]/.test(root.textContent || "");
  const mapCircled = [...(stage?.querySelectorAll('[data-cosmos-label], [data-cosmos-station-name], svg text') ?? [])].some(circled);
  const barCircled = circled(document.querySelector('[data-tour="caption-bar"]')) || circled(document.querySelector('[data-visibility-strip="map-toolbar"]'));
  const rail = [...document.querySelectorAll('[data-tour^="rail-step-"]')].map((b) => {
    const m = /^(\d)단계 (.+?) — (.+?)\./.exec(b.getAttribute("aria-label") || "");
    return m ? { n: m[1], label: m[2], status: m[3] } : null;
  }).filter(Boolean);
  const flags = {};
  for (const el of document.querySelectorAll("[data-station-flag]")) {
    const n = el.closest("[data-cosmos-station-name]")?.getAttribute("data-cosmos-station-name");
    if (n) flags[n] = el.getAttribute("data-station-flag");
  }
  const railFlagMismatch = rail.filter((r) => (["확인 필요", "실패"].includes(r.status)) !== Boolean(flags[r.n])).map((r) => r.n);
  const head = document.querySelector('[data-cosmos-station-name][data-cosmos-station-tier="current"]');
  const headText = head ? (head.textContent || "").replace(/\s+/g, " ") : "";
  const railLabel = rail.find((r) => r.n === station)?.label ?? "";
  const nameMatches = !!railLabel && headText.includes(railLabel);
  const chip = [...document.querySelectorAll('section[data-tour="stage"] [role="status"]')].map((el) => el.textContent || "").join(" ");
  return {
    fit: d.cosmosFit ?? "", view, station, nodes: Number(d.cosmosStationNodes ?? -1), drawn: Number(d.cosmosDrawnMarks ?? -2), links: Number(d.cosmosLinks ?? -1),
    shapes: [...new Set((d.cosmosShapes || "").split(",").filter(Boolean).map((s) => s.replace(/-lg$/, "")))], items: Number(d.cosmosStationItems ?? 0),
    labels: labels.length, small, overlaps, headOverlaps, offStation, verdictTrunc, hiddenNames, mapCircled, barCircled, railFlagMismatch, nameMatches, railLabel, headText: headText.slice(0, 40),
    chip: chip.slice(0, 80), omitted: /생략/.test(chip), more: !!document.querySelector("[data-cosmos-more]"),
    lineStates: [...document.querySelectorAll("[data-cosmos-line]")].map((l) => l.getAttribute("data-cosmos-line") + ":" + (l.getAttribute("stroke") || "")),
    // 움직이는 점선 = 애니메이션이 걸린 점선(깜빡임은 실선이라 괜찮다)
    animatedDash: [...document.querySelectorAll("svg [data-cosmos-line]")].some((l) => (getComputedStyle(l).animationName || "none") !== "none" && !!l.getAttribute("stroke-dasharray")),
  };
`;

async function openUrl(cdp, url) {
  await cdp.send("Page.navigate", { url: new URL(url, BASE).href });
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    const ok = await cdp.evaluate(`return !!document.querySelector('[data-tour^="rail-step-"]') && !!document.documentElement.dataset.cosmosStation;`).catch(() => false);
    if (ok) break;
    await sleep(500);
  }
  await sleep(2500);
}

async function goStation(cdp, n) {
  await cdp.evaluate(`const b = document.querySelector('[data-tour="rail-step-${n}"]'); if (b) b.click(); return !!b;`);
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if ((await cdp.evaluate(`return document.documentElement.dataset.cosmosStation ?? null;`).catch(() => null)) === String(n)) break;
    await sleep(250);
  }
  // 좁은 창에서 레일을 누르면 상세 서랍이 지도를 덮는다 — 닫는다(지도를 재려는 것).
  await cdp.evaluate(`
    const close = [...document.querySelectorAll("button")].find((b) => (b.getAttribute("aria-label") || "").includes("닫기") && b.getBoundingClientRect().width > 0 && b.closest("aside,[role=dialog]"));
    if (close && innerWidth < 1024) close.click();
    return true;`);
  await sleep(2200);
}

async function deselect(cdp) {
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await sleep(900);
}

async function main() {
  const browser = BROWSERS.find((p) => existsSync(p));
  if (!browser) throw new Error("Edge/Chrome 을 찾지 못했습니다");
  const profile = join(process.env.TEMP || ".", "bidpilot-check-map");
  const child = spawn(browser, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--headless=new", "--no-first-run", "--hide-scrollbars", "--disable-background-timer-throttling", "about:blank"], { stdio: "ignore" });
  const rows = [];
  const firstScreen = [];
  const clickRows = [];
  try {
    const cdp = await connect(PORT);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    for (const size of SIZES) {
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: size.width, height: size.height, deviceScaleFactor: 1, mobile: size.width < 768 });
      for (const view of VIEWS) {
        await openUrl(cdp, URL_OF(view));
        for (let n = 1; n <= 8; n += 1) {
          await goStation(cdp, n);
          const selected = await cdp.evaluate(PROBE).catch((error) => ({ error: String(error) }));
          // 레일이 고르는 허브 말고 **지금 정거장 첫 항목**을 이름표로 눌러 고른다(27차 검수 R27D-06 · OWN-02)
          const picked = await cdp.evaluate(`
            const st = document.documentElement.dataset.cosmosStation;
            const label = [...document.querySelectorAll('[data-cosmos-label="long"][data-cosmos-station="' + st + '"]')].find((el) => el.getBoundingClientRect().width > 0);
            if (!label) return null;
            const target = label.closest("g[role=button]") || label;
            target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
            await new Promise((r) => setTimeout(r, 900));
            const chip = [...document.querySelectorAll('section[data-tour="stage"] [role="status"]')].map((el) => el.textContent || "").join(" ");
            return { links: Number(document.documentElement.dataset.cosmosLinks ?? -1), chip: chip.slice(0, 80), name: (label.textContent || "").trim().slice(0, 20) };`).catch(() => null);
          if (selected && !selected.error) selected.picked = picked;
          await deselect(cdp);
          const none = await cdp.evaluate(PROBE).catch((error) => ({ error: String(error) }));
          rows.push({ size: `${size.width}×${size.height}`, view, n, selected, none });
        }
        // 지금이 아닌 정거장 이름을 누르면 그 정거장으로 — 8 → 3
        const clicked = await cdp.evaluate(`
          const head = document.querySelector('[data-cosmos-station-name="3"]');
          if (!head) return false;
          head.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
          head.dispatchEvent(new MouseEvent("click", { bubbles: true }));
          return true;`);
        await sleep(1800);
        const now = await cdp.evaluate(`return document.documentElement.dataset.cosmosStation ?? null;`).catch(() => null);
        clickRows.push({ size: `${size.width}×${size.height}`, view, clicked, station: now });
      }
      if (size.width !== 1024) {
        await openUrl(cdp, `/analysis?notice=synthetic-rfp-0001&welcome=0&mode=full&guided=0`);
        const key = await cdp.evaluate(`
          const el = document.querySelector("[data-map-key]");
          const words = el ? [...el.querySelectorAll("[data-map-key-verdict]")].map((s) => s.getAttribute("data-map-key-verdict")) : [];
          const r = el?.getBoundingClientRect();
          return { exists: !!el, top: r ? Math.round(r.top + scrollY) : null, withinOneScroll: r ? r.top + scrollY < innerHeight * 2 : false, words };`);
        // 범례 시트 낱말 — 「범례」 단추로 연다
        const sheet = await cdp.evaluate(`
          const b = [...document.querySelectorAll("button")].find((x) => (x.textContent || "").trim() === "범례");
          if (b) b.click();
          await new Promise((r) => setTimeout(r, 600));
          const dialog = [...document.querySelectorAll('[role="dialog"]')].find((x) => /상세 범례/.test(x.textContent || ""));
          const items = dialog ? [...dialog.querySelectorAll("li .font-semibold")].map((s) => (s.textContent || "").trim()) : [];
          return items;`);
        firstScreen.push({ size: `${size.width}×${size.height}`, ...key, sheetHas: ["충족", "확인 필요", "문제", "판정 전"].every((w) => sheet.includes(w)) });
      }
    }
  } finally {
    child.kill();
  }

  const problems = [];
  for (const row of rows) {
    const tag = `${row.size} ${row.view} ${row.n}`;
    for (const [phase, r] of [["고름", row.selected], ["안 고름", row.none]]) {
      if (r.error) { problems.push(`${tag} ${phase}: 오류 ${r.error}`); continue; }
      if (r.drawn !== r.nodes) problems.push(`${tag} ${phase}: 그린 ${r.drawn} ≠ 그릴 ${r.nodes}`);
      if (r.mapCircled || r.barCircled) problems.push(`${tag} ${phase}: 원문자`);
      if (r.labels < r.nodes) problems.push(`${tag} ${phase}: 이름표 ${r.labels} < 기호 ${r.nodes}`);
      if (r.overlaps) problems.push(`${tag} ${phase}: 이름표 겹침 ${r.overlaps}`);
      if (r.offStation) problems.push(`${tag} ${phase}: 다른 정거장 이름표 ${r.offStation}`);
      if (r.verdictTrunc) problems.push(`${tag} ${phase}: 판정 낱말이 이름을 잘라 먹음 ${r.verdictTrunc}`);
      if (r.hiddenNames.length) problems.push(`${tag} ${phase}: 안 보이는 정거장 이름 ${r.hiddenNames.join(",")}`);
      if (r.headOverlaps.length) problems.push(`${tag} ${phase}: 정거장 머리 겹침 ${r.headOverlaps.slice(0, 3).join(" · ")}${r.headOverlaps.length > 3 ? ` 외 ${r.headOverlaps.length - 3}` : ""}`);
      if (r.small) problems.push(`${tag} ${phase}: 13px 미만 ${r.small}`);
      if (r.shapes.length > 2 || (r.shapes.includes("triangle") && r.shapes.some((s) => s.startsWith("warn")))) problems.push(`${tag} ${phase}: 모양 ${r.shapes.join(",")}`);
      if (r.nodes > 24 && !r.more) problems.push(`${tag} ${phase}: 표시 ${r.nodes} > 24`);
      if (r.railFlagMismatch.length) problems.push(`${tag} ${phase}: 레일↔알약 다름 ${r.railFlagMismatch.join(",")}`);
      if (!r.nameMatches) problems.push(`${tag} ${phase}: 지금 정거장 이름 「${r.headText}」 ≠ 레일 「${r.railLabel}」`);
      if (r.omitted) problems.push(`${tag} ${phase}: 「생략」`);
      if (r.animatedDash) problems.push(`${tag} ${phase}: 움직이는 점선`);
      if (r.lineStates.some((s) => !/^(active|candidate|warning):/.test(s))) problems.push(`${tag} ${phase}: 선 색 ${r.lineStates.join(" ")}`);
    }
    if (row.none.links !== 0) problems.push(`${tag}: 안 골랐는데 선 ${row.none.links}`);
    if (row.selected.links > 3) problems.push(`${tag}: 선 ${row.selected.links} > 3`);
    const pk = row.selected.picked;
    if (row.selected.nodes > 0 && pk === null) problems.push(`${tag}: 이름표를 눌러 고를 항목을 못 찾음`);
    if (pk && pk.links > 3) problems.push(`${tag}: 항목 「${pk.name}」 선 ${pk.links} > 3`);
    if (pk && pk.links > 0 && !/^\s*선택 ·/.test(pk.chip)) problems.push(`${tag}: 항목을 골랐는데 선택 카드 「${pk.chip}」`);
  }
  for (const c of clickRows) if (c.station !== "3") problems.push(`${c.size} ${c.view}: 정거장 3 이름을 눌러도 ${c.station}`);
  for (const f of firstScreen) {
    if (!f.exists || !f.withinOneScroll) problems.push(`${f.size}: 범례 줄 ${f.exists ? `위치 ${f.top}` : "없음"}`);
    if (f.words.join(",") !== "충족,확인 필요,문제,판정 전" || !f.sheetHas) problems.push(`${f.size}: 범례 낱말 ${f.words.join(",")} · 시트 ${f.sheetHas}`);
  }

  if (AS_JSON) {
    console.log(JSON.stringify({ rows, clickRows, firstScreen, problems }, null, 1));
  } else {
    console.log("지도 수용 검사 — 3 폭 × 3D·2D × 정거장 1~8");
    for (const row of rows) {
      const s = row.selected, z = row.none;
      console.log(`  ${row.size} ${row.view} ${row.n} · ${s.view}${s.fit ? ` 맞춤 ${s.fit}` : ""}${s.picked ? ` · 이름표 고름 「${s.picked.name}」 선 ${s.picked.links}` : ""} 그린 ${s.drawn}/${s.nodes} · 이름표 ${s.labels} · 모양 ${(s.shapes || []).join("+") || "-"} · 선 고름 ${s.links}/안 고름 ${z.links} · 알약 불일치 ${(s.railFlagMismatch || []).length}`);
    }
    for (const c of clickRows) console.log(`  이름 누르기 ${c.size} ${c.view}: → ${c.station}`);
    for (const f of firstScreen) console.log(`  범례 줄 ${f.size}: ${f.exists ? `y ${f.top} · 한 번 안 ${f.withinOneScroll}` : "없음"} · 낱말 ${f.words.join(",")} · 시트 같음 ${f.sheetHas}`);
    console.log(problems.length ? `\n✗ 위반 ${problems.length}\n  - ${problems.join("\n  - ")}` : "\n✓ 지도 수용 기준 위반 없음");
  }
  process.exit(problems.length ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
