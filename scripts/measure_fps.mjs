/**
 * 3D 프레임 속도 측정 (prompt_01 §4-A-5).
 *
 * 왜 재는가: 「점마다 라벨」로 바꾸면서 개수 상한을 «긴 라벨에만» 걸었다. 노드가 많은
 * 화면에서는 DOM 라벨도 그만큼 는다. 프롬프트는 「노드 200 에 라벨 200 이 60fps 를
 * 못 지키면 Html 대신 sprite 로 바꾸라」고 했고 **재기 전에는 바꾸지 말라**고 했다.
 * 그래서 먼저 잰다 — 바꾸는 것은 이 숫자를 보고 정할 일이다.
 *
 * 방법은 `check_visibility.mjs` 와 같다: 헤드리스 브라우저를 CDP 로 몰아
 * requestAnimationFrame 간격을 샘플링한다. 헤드리스는 기본으로 렌더러를 잠재우므로
 * 배경 억제 플래그를 꺼야 프레임이 온다.
 *
 * 실행: `node scripts/measure_fps.mjs`  (서버가 떠 있어야 한다)
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:3110";
const PORT = Number(process.env.CDP_PORT ?? 9333);
const WIDTH = 1440;
const HEIGHT = 900;
/** 대시보드 fps 기준 — `MIN_FPS` 환경변수로 바꿀 수 있다(프롬프트 기준 55). */
const MIN_FPS = Number(process.env.MIN_FPS ?? 55);
const SCREENS = [
  { key: "대시보드", path: "/analysis?notice=synthetic-rfp-0001" },
  { key: "레이더", path: "/radar" },
];
const BROWSERS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 24차: 기존 측정은 **전체 보기**를 잰다 — 주소에 mode 를 searchParams 로 붙이고, 시작할 때 저장된 보기 방식을 지운다. */
const fullUrl = (path) => {
  const url = new URL(path, BASE);
  url.searchParams.set("mode", "full");
  // 27차 §3-D-11 — 대시보드 지도는 3D 로 고정해 잰다(기본 보기가 바뀌어도 같은 것을 재게). 레이더에는 붙이지 않는다.
  if (url.pathname === "/analysis" && !url.searchParams.has("view") && !url.searchParams.has("support")) url.searchParams.set("view", "3d");
  return url.href;
};
async function clearViewMode(cdp) {
  await cdp.send("Page.navigate", { url: new URL("/favicon.ico", BASE).href });
  const origin = new URL(BASE).origin;
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && (await cdp.evaluate(`return location.origin;`).catch(() => null)) !== origin) await sleep(200);
  await cdp.evaluate(`try { localStorage.removeItem("bidpilot.viewmode.v1"); } catch (e) {} return true;`);
}

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
    const result = await this.send("Runtime.evaluate", {
      expression: `(async () => { ${expression} })()`,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description ?? "페이지 스크립트 오류");
    }
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

/** 페이지 안에서 도는 측정 — CDP 는 함수를 못 보내므로 문자열이다. */
const PROBE = `
  const nodes = document.documentElement.dataset.cosmosNodes ?? null;
  const labels = document.querySelectorAll("[data-cosmos-label]").length;
  const gaps = [];
  await new Promise((done) => {
    let last = performance.now();
    let n = 0;
    function tick(t) {
      gaps.push(t - last);
      last = t;
      n += 1;
      if (n < 150) requestAnimationFrame(tick);
      else done();
    }
    requestAnimationFrame(tick);
  });
  gaps.shift();
  if (gaps.length === 0) return { nodes, labels, samples: 0 };
  const sorted = [...gaps].sort((a, b) => a - b);
  const avg = gaps.reduce((s, x) => s + x, 0) / gaps.length;
  return {
    nodes, labels, samples: gaps.length,
    avgMs: +avg.toFixed(2),
    fps: +(1000 / avg).toFixed(1),
    p95Ms: +sorted[Math.floor(sorted.length * 0.95)].toFixed(2),
    maxMs: +sorted[sorted.length - 1].toFixed(2),
  };
`;

async function main() {
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) {
    console.error("Edge·Chrome 을 찾지 못했습니다 — fps 를 잴 수 없습니다.");
    return 2;
  }
  const profile = join(process.env.TEMP || ".", `bidpilot-fps-${PORT}`);
  const browser = spawn(
    exe,
    [
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      `--window-size=${WIDTH},${HEIGHT}`,
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--hide-scrollbars",
      // 헤드리스는 기본으로 렌더러를 잠재운다 — 끄지 않으면 rAF 가 한 프레임도 안 온다.
      "--disable-renderer-backgrounding",
      "--disable-backgrounding-occluded-windows",
      "--disable-background-timer-throttling",
      "about:blank",
    ],
    { stdio: "ignore", detached: false },
  );

  const rows = [];
  try {
    const cdp = await connect(PORT);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false,
    });
    await clearViewMode(cdp);
    for (const screen of SCREENS) {
      await cdp.send("Page.navigate", { url: fullUrl(screen.path) });
      await sleep(9000);
      let result;
      try {
        result = await cdp.evaluate(PROBE);
      } catch (error) {
        result = { error: String(error.message || error) };
      }
      rows.push({ screen: screen.key, ...result });
    }
  } finally {
    browser.kill();
  }

  console.log(`3D 프레임 속도 — ${BASE} · ${WIDTH}x${HEIGHT}
`);
  console.log("  화면          노드  라벨  표본  평균(ms)   fps   p95(ms)  최대(ms)");
  for (const r of rows) {
    if (r.error) {
      console.log(`  ${r.screen.padEnd(12)}읽지 못함 — ${String(r.error).slice(0, 60)}`);
      continue;
    }
    if (!r.samples) {
      console.log(`  ${r.screen.padEnd(12)}${String(r.nodes).padEnd(6)}${String(r.labels).padEnd(6)}프레임이 오지 않았습니다(렌더러 잠듦)`);
      continue;
    }
    console.log(
      `  ${r.screen.padEnd(12)}${String(r.nodes).padEnd(6)}${String(r.labels).padEnd(6)}` +
      `${String(r.samples).padEnd(6)}${String(r.avgMs).padEnd(11)}${String(r.fps).padEnd(6)}` +
      `${String(r.p95Ms).padEnd(9)}${r.maxMs}`,
    );
  }
  /* 기준을 **실제로 건다** (21차 · prompt_11 §4-F 「measure_fps ≥ 55」) — 예전에는 언제나 0 으로 끝나 숫자만 적었다.
     대시보드(입찰 3D 지도)가 기준 아래이거나 표본이 없으면 실패. 레이더는 적기만 한다. */
  const dashboard = rows.find((r) => r.screen === "대시보드");
  const ok = Boolean(dashboard && !dashboard.error && dashboard.samples && dashboard.fps >= MIN_FPS);
  console.log(ok ? `
대시보드 ${dashboard.fps} fps ≥ ${MIN_FPS} — 통과` : `
대시보드 fps 기준(${MIN_FPS}) 미달 또는 표본 없음 — 실패`);
  return ok ? 0 : 1;
}

process.exit(await main());
