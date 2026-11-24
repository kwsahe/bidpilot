/**
 * 3D 라벨 흔들림 측정 — 라벨이 제자리에 **가만히 있는가**를 기계가 센다 (ISSUE-124 · prompt_04 §3-A-6).
 *
 * ## 왜 이 스크립트가 있나
 *
 * 담당자: 「3D 대시보드에서 제목이 마구잡이로 흔들리고 난동부리고 있어.」
 * 검수자가 같은 창 크기(2000×669)에서 라벨 사각형을 100ms 간격으로 떠서 재현했다 —
 * 가천대 피지컬 2단계에서 라벨 15개 중 12개가 4초 동안 계속 움직이고, 가장 심한 것은
 * 3,371px 를 미끄러졌다(`docs/reports/2026-09-29_qa_hotfix_3d.md` §2). fps 는 60 이었다.
 * **프레임이 아니라 배치 결과가 매 패스 바뀌는 것**이라 `measure_fps.mjs` 로는 잡히지 않는다.
 *
 * 그래서 재는 것을 나눈다 — fps 는 `measure_fps.mjs`, 자리의 안정은 이 스크립트.
 *
 * ## 무엇을 재는가 (하나라도 어기면 종료 코드 1)
 *
 *   a. **누른 뒤 6초** (15차부터 · ISSUE-127 · prompt_05 §4-C-3). 세 가지를 함께 본다.
 *
 *      a-1. **배치가 언제 자리를 잡는가** — 라벨의 «노드 기준 오프셋»(dx/dy)이 6px 넘게
 *           바뀐 **마지막** 시각. 단계를 누르면 배치가 한 번은 새로 잡혀야 하지만, 그
 *           뒤로는 끝까지 그대로여야 한다. 이 시각이 1.0초를 넘으면 위반이다 — 담당자가
 *           본 「멈춘 뒤 한 박자 있다가 라벨이 툭 옮겨간다」가 정확히 이것이고, 이 기계에서는
 *           1.3초, 재검증 기계에서는 3.7~4.0초에 왔다.
 *      a-2. **카메라가 멈춘 뒤의 절대 이동** — 2초 이후 한 번에 6px 초과 이동 0.
 *           14차까지의 기준 그대로다(아래 「왜 오프셋인가」).
 *      a-3. 글자가 바뀌거나 · 글자↔번호 모양이 바뀌거나(1.0초 이후) · 보였다 안 보였다 함(2회 이상).
 *
 *   b. **드래그 중** — 캔버스를 4초 동안 끄는 동안 글자↔번호 **전환 0**
 *      위치는 재지 않는다. 카메라가 도는 동안 라벨이 노드를 따라 움직이는 것은 제자리다.
 *   c. 화면이 준비되지 않거나 단계 버튼을 못 찾으면 **위반**이다 — 조용히 건너뛰면
 *      늘 통과하는 검사가 된다 (`check_visibility.mjs` 의 「미측정」과 같은 규칙).
 *
 * ## 왜 오프셋인가 — 그리고 왜 이것이 느슨해진 것이 아닌가
 *
 * 14차까지는 **2초 뒤 4초**만 봤다. 그 2초가 빈틈이었다: 배치를 다시 푸는 그 한 번이
 * 빠른 기계에서는 1.3초에 와서 창 밖으로 빠졌다(핫픽스 보고가 「위반 0」이라 적은 이유).
 * 느린 기계에서는 3.7~4.0초에 와서 잡혔다(재검증 §3-2, 위반 8~12). **같은 결함이 기계
 * 속도에 따라 보이거나 숨었다.**
 *
 * 그래서 창을 누른 순간부터로 넓혔다. 그러면 카메라 전환 중의 이동이 들어오는데, 그것은
 * 결함이 아니다 — 이 파일이 드래그 항목에 이미 적어 둔 그대로 「카메라가 도는 동안 라벨이
 * 노드를 따라 움직이는 것은 제자리」다. 그 「제자리」를 이제 실제로 잰다: 라벨의 transform 에
 * 들어 있는 `translate(dx, dy)` 가 배치 결과이고, 그것이 바뀌면 **배치가 다시 풀린 것**이다.
 *
 * 14차 기준(2초 이후 절대 이동 0)은 **그대로 남겨** 함께 본다. 넓힌 것이지 바꾼 것이 아니다.
 *
 * ## 라벨을 어떻게 짝지어 보는가
 *
 * 프레임마다 DOM 순서로 i 번째끼리 견주면 라벨 하나가 붙고 떨어질 때 전부 밀려 거짓
 * 흔들림이 된다. `data-cosmos-label-id`(노드 id)가 있으면 **id 로** 짝짓고, 없으면 순서로
 * 짝짓는다. 어느 쪽으로 쟀는지 결과에 적는다 — 고치기 전과 후를 같은 방법으로 비교해야 한다.
 *
 * ## 왜 Playwright 가 아닌가
 *
 * `measure_fps.mjs`·`check_visibility.mjs` 와 같은 이유다 — 이 저장소에 없다. CDP 를 직접 쓴다.
 * 실호출은 하지 않는다. 이미 떠 있는 화면(3110)을 열어 DOM 만 읽는다.
 *
 * 쓰기:
 *   node scripts/measure_jitter.mjs
 *   node scripts/measure_jitter.mjs --sizes 2000x669 --notice g2b-R26BK01707959-000 --step 2
 *   node scripts/measure_jitter.mjs --width 1440 --height 900 --json
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};

const BASE = argOf("--base", "http://localhost:3110");
const PORT = Number(argOf("--port", "9337"));
const AS_JSON = args.includes("--json");

/**
 * 수용 조합 (prompt_04 §3-A-6): 2000×669 · 1440×900 × {합성 공고, 가천대 피지컬} × 단계 {1,4,6}.
 *
 * 2000×669 는 담당자가 결함을 본 그 창이고, 1440×900 은 평소 노트북이다.
 * 가천대 피지컬은 검수자가 12/15 흔들림을 잰 공고, 합성 공고는 노드가 가장 많은(38) 화면이다.
 * 단계는 **레일 단계**다 (21차) — 지도 위 5단계 단추 바가 없어졌다. 1·4·6 은 카메라가 공고·요구사항·제안서 정거장으로
 * 옮겨 가는 지점으로, 예전 안내 단계 1·2·4 와 같은 목적지다(12조합 그대로).
 */
const SIZES = (argOf("--width", null) !== null || argOf("--height", null) !== null
  ? [`${argOf("--width", "2000")}x${argOf("--height", "669")}`]
  : argOf("--sizes", "2000x669,1440x900").split(",")
).map((spec) => {
  const [width, height] = spec.trim().toLowerCase().split("x").map(Number);
  return { width, height, key: `${width}×${height}` };
});
const NOTICES = argOf("--notice", "synthetic-rfp-0001,g2b-R26BK01707959-000").split(",");
const STEPS = argOf("--step", "1,4,6").split(",").map(Number);

/**
 * 단계를 누른 뒤 표본을 뜨기 시작할 때까지 기다리는 시간.
 *
 * **0 이다** (15차 · §4-C-3). 14차까지는 2000 이었고, 그 2초가 결함이 숨는 빈틈이었다.
 */
const SETTLE_MS = Number(argOf("--settle", "0"));
/** 표본 수와 간격 (61 × 100ms = 6초). */
const SAMPLES = Number(argOf("--samples", "61"));
const SAMPLE_MS = 100;
/** 「흔들림」으로 세는 한 번의 이동 (px). */
const JUMP_PX = 6;
/**
 * 배치가 **자리를 잡아야 하는 시각** (누른 뒤 ms).
 *
 * 단계를 누르면 노드와 라벨이 바뀌므로 배치는 한 번 새로 잡힌다 — 그것은 옳다. 여기서
 * 재는 것은 「그 한 번이 언제 끝나는가」다. 실측으로 라벨이 붙는 데 0.3초, 자리가 정해지는
 * 데 0.5~0.8초가 걸린다. 1.0초를 넘으면 사람 눈에 「자리를 잡은 뒤에 또 옮겨간다」로 보인다.
 */
const LAYOUT_SETTLE_MS = Number(argOf("--layout-settle", "1000"));
/** 절대 이동을 보기 시작하는 시각 — 카메라 전환이 끝났을 시점 (14차 기준 그대로). */
const ABSOLUTE_FROM_MS = Number(argOf("--absolute-from", "2000"));

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
  // 27차 §3-D-11 — 대시보드 지도는 3D 로 고정해 잰다(기본 보기가 바뀌어도 같은 것을 재게).
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

// ---------------------------------------------------------------------------
// CDP — `check_visibility.mjs` 와 같은 최소 구현
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// 페이지 안에서 도는 코드 — CDP 는 함수를 못 보내므로 문자열이다
// ---------------------------------------------------------------------------

/** 3D 가 붙을 때까지. `check_visibility.mjs` 와 같은 폴링(최대 120초). */
const WAIT_STAGE = `
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    if (document.documentElement.dataset.cosmosNodes !== undefined) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
`;

/** 레일 단계 버튼 (21차) — `WorkflowRail` 이 `data-tour="rail-step-N"` 을 달아 둔다. */
const CLICK_STEP = (step) => `
  const button = document.querySelector('button[data-tour="rail-step-${step}"]');
  if (!button) return null;
  button.click();
  return (button.getAttribute("aria-label") || button.textContent || "").trim().slice(0, 40);
`;

/**
 * 화면이 **멈출 때까지** 기다린다 — 무대 크기와 **라벨 자리** 둘 다.
 *
 * 이 화면은 3D 위에 「오늘 달라진 것 · 이번 주 할 일 · 지금 할 일」이 먼저 오고, 그 패널들이
 * 자료를 나중에 받아 높이가 커진다. 그러면 남는 공간이 줄어 무대가 한 번 작아지고, 화면
 * 좌표가 달라지므로 라벨이 **한 번** 다시 놓인다 — 그건 고칠 진동이 아니라 크기 변화에
 * 따라야 하는 재배치다. 그 한 번을 「흔들림」으로 세면 측정이 앱을 잘못 고발한다.
 *
 * **크기만 보는 것으로는 모자랐다** (16차 실측). 창 크기를 바꾼 **직후 첫 단계**를 누르면,
 * 누른 뒤 1.2초에 라벨 12개가 글자↔번호를 한꺼번에 뒤집었다. 콘솔로 그 순간을 들여다보니
 * 배치가 쓰는 **도착 카메라의 배율이 1.000 에서 0.820 으로 바뀌어 있었다** — 캔버스 상자는
 * 이미 멈췄는데 3D 쪽이 새 크기에 맞춰 카메라를 다시 잡는 중이었고, 그 두 번째 목표가
 * 클릭 뒤에 도착한 것이다. 앱은 새 크기에 맞게 다시 잡은 것이고(옳다), 검사가 성급했다.
 * 15차에 `check_visibility.mjs` 가 「노드 수가 멈출 때까지」를 기다리게 된 것과 같은 자리다.
 *
 * 그래서 라벨의 화면 좌표가 1초 동안 2px 넘게 움직이지 않을 때까지 함께 기다린다.
 * 느슨해지는 것이 아니다 — 앱이 **정말로** 안 멈추면 20초 뒤에 그 상태 그대로 재고,
 * 결과에 「안 멈춤」이 적힌다.
 */
const STABLE_STAGE = `
  const key = () => {
    const canvas = document.querySelector("canvas");
    if (!canvas) return "없음";
    const box = canvas.getBoundingClientRect();
    return Math.round(box.width) + "×" + Math.round(box.height);
  };
  /** 라벨 자리의 지문. 2px 눈금으로 굴려 미세한 흐름은 「멈춘 것」으로 본다. */
  const labelKey = () =>
    [...document.querySelectorAll("[data-cosmos-label]")]
      .map((el) => {
        const box = el.getBoundingClientRect();
        return (el.dataset.cosmosLabelId || "") + ":" + Math.round(box.left / 2) + "," + Math.round(box.top / 2);
      })
      .join("|");
  const deadline = Date.now() + 20000;
  let last = key() + " " + labelKey();
  let since = Date.now();
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    const now = key() + " " + labelKey();
    if (now !== last) { last = now; since = Date.now(); continue; }
    if (Date.now() - since >= 1000) return key();
  }
  return key() + "(안 멈춤)";
`;

/**
 * 라벨 사각형·글자·모양·불투명도를 100ms 간격으로 떠서 라벨마다 요약한다.
 *
 * 「글자」는 **본문 span** 에서 읽는다 — 번호 칩으로 줄어도 본문은 DOM 에 display:none 으로
 * 남아 있어 컨테이너의 textContent 에는 둘이 섞여 들어온다. 모양은 칩이 그려져 있는지로 본다.
 */
const SAMPLE = `
  const stageKey = () => {
    const canvas = document.querySelector("canvas");
    if (!canvas) return "없음";
    const box = canvas.getBoundingClientRect();
    return Math.round(box.width) + "×" + Math.round(box.height);
  };
  /* 배치 결과(노드 기준 오프셋). 라벨의 transform 은 「translate(dx,dy) scale(s)」이고
     앞쪽 translate 가 충돌 회피가 정한 자리다 — 이것이 바뀌면 «배치가 다시 풀린» 것이다.
     scale 은 카메라 거리라 여기서 보지 않는다. */
  const offsetOf = (el) => {
    const m = /translate\\(([-0-9.]+)px,\\s*([-0-9.]+)px\\)/.exec(el.style.transform || "");
    return m ? { dx: Number(m[1]), dy: Number(m[2]) } : { dx: 0, dy: 0 };
  };
  const snap = () => [...document.querySelectorAll("[data-cosmos-label]")].map((el, index) => {
    const box = el.getBoundingClientRect();
    const chip = el.querySelector("[data-cosmos-number]");
    const body = el.querySelector("[data-cosmos-text]");
    const numbered = !!chip && getComputedStyle(chip).display !== "none";
    const off = offsetOf(el);
    return {
      id: el.dataset.cosmosLabelId || "",
      index,
      variant: el.dataset.cosmosLabel,
      text: ((body || el).textContent || "").trim().slice(0, 24),
      numbered,
      x: box.left,
      y: box.top,
      dx: off.dx,
      dy: off.dy,
      opacity: Number(getComputedStyle(el).opacity),
    };
  });

  const frames = [];
  const stages = [];
  for (let i = 0; i < ${SAMPLES}; i += 1) {
    stages.push(stageKey());
    frames.push(snap());
    if (i < ${SAMPLES} - 1) await new Promise((r) => setTimeout(r, ${SAMPLE_MS}));
  }
  // 재는 동안 무대 크기가 바뀌었는가 — 바뀌면 라벨이 따라 움직이는 것이 옳다.
  const stageResizes = stages.filter((key, i) => i > 0 && key !== stages[i - 1]).length;

  /* 짝짓기 — id 가 있는 라벨은 **id 로**, 없는 라벨(등록되지 않은 hover 라벨·위험 툴팁)은
     DOM 순서로. 전부 순서로 짝지으면 라벨 하나가 붙고 떨어질 때 뒤가 모두 밀려 거짓
     흔들림이 되고, 전부 id 를 요구하면 등록 안 된 라벨 하나 때문에 순서로 되돌아간다. */
  const keyOf = (sample) => (sample.id ? "id:" + sample.id : "ix:" + sample.index);
  const keys = [...new Set(frames.flat().map(keyOf))];
  const withId = frames.flat().filter((s) => s.id).length;
  const pairedBy = withId === 0 ? "순서" : withId === frames.flat().length ? "id" : "id+순서";

  const rows = [];
  for (const key of keys) {
    const series = frames.map((f) => f.find((s) => keyOf(s) === key) || null);
    let jump = 0, jumpAt = -1, path = 0, textChanges = 0, shapeChanges = 0, flick = 0, seen = 0, missing = 0;
    /* 배치가 마지막으로 바뀐 시각(ms) — 단계를 누른 뒤 기준. 한 번도 안 바뀌면 null. */
    let offsetSettledAt = null;
    let offsetJump = 0;
    /* 카메라가 멈춘 뒤(2초 이후)의 절대 이동 — 14차 기준 그대로. */
    let lateJump = 0, lateJumpAt = -1;
    /* 자리를 잡아야 하는 시각 이후의 모양·글자 변화. 그 전의 것은 화면이 붙는 중이다. */
    let lateShape = 0, lateText = 0;
    for (const sample of series) (sample ? seen++ : missing++);
    for (let i = 1; i < series.length; i += 1) {
      const a = series[i - 1];
      const b = series[i];
      if (!a || !b) continue;
      const at = i * ${SAMPLE_MS};
      if (a.text !== b.text) { textChanges += 1; if (at > ${LAYOUT_SETTLE_MS}) lateText += 1; }
      if (a.numbered !== b.numbered) { shapeChanges += 1; if (at > ${LAYOUT_SETTLE_MS}) lateShape += 1; }
      if ((a.opacity > 0.5) !== (b.opacity > 0.5)) flick += 1;
      /* 배치(오프셋)는 **보이든 안 보이든** 잰다 — 지금 흐려 있는 라벨이 자리를 옮기면
         조금 뒤 진해질 때 그 자리에서 나타난다. 옮긴 사실은 그대로 남는다. */
      const dOffset = Math.hypot(b.dx - a.dx, b.dy - a.dy);
      if (dOffset > ${JUMP_PX}) {
        offsetSettledAt = at;
        if (dOffset > offsetJump) offsetJump = dOffset;
      }
      // 위치는 **둘 다 보이는** 구간만 잰다 — 안 보이는 라벨이 움직여도 눈에 띄지 않는다.
      if (a.opacity > 0.05 && b.opacity > 0.05) {
        const d = Math.hypot(b.x - a.x, b.y - a.y);
        path += d;
        // 가장 큰 이동이 **몇 초째**에 일어났는가 — 한 번만 움직인 라벨의 원인을 가른다.
        if (d > jump) { jump = d; jumpAt = i; }
        if (at >= ${ABSOLUTE_FROM_MS} && d > lateJump) { lateJump = d; lateJumpAt = i; }
      }
    }
    const first = series.find(Boolean);
    rows.push({
      label: first ? (first.numbered ? "번호 " + first.text : first.text) : key,
      variant: first ? first.variant : "?",
      jump: Math.round(jump), jumpAt: jumpAt < 0 ? null : jumpAt * ${SAMPLE_MS},
      offsetSettledAt, offsetJump: Math.round(offsetJump),
      lateJump: Math.round(lateJump), lateJumpAt: lateJumpAt < 0 ? null : lateJumpAt * ${SAMPLE_MS},
      lateShape, lateText,
      path: Math.round(path),
      textChanges, shapeChanges, flick, seen, missing,
    });
  }

  /* 위반 판정 — 「배치가 늦게까지 바뀐다」·「멈춘 뒤에도 움직인다」·글자·모양·깜빡. */
  const offending = (r) =>
    (r.offsetSettledAt !== null && r.offsetSettledAt > ${LAYOUT_SETTLE_MS}) ||
    r.lateJump > ${JUMP_PX} ||
    r.lateText > 0 ||
    r.lateShape > 0 ||
    r.flick > 1;
  const shaking = rows.filter(offending);
  const settleTimes = rows.map((r) => r.offsetSettledAt).filter((v) => v !== null);
  return {
    pairedBy,
    stage: stages[0],
    stageResizes,
    nodes: Number(document.documentElement.dataset.cosmosNodes ?? -1),
    labels: keys.length,
    seconds: ${((SAMPLES - 1) * SAMPLE_MS) / 1000},
    shaking: shaking.length,
    /** 배치가 **마지막으로** 바뀐 시각 (라벨 전체에서 가장 늦은 것). 기준은 1.0초. */
    layoutSettledAt: settleTimes.length ? Math.max(...settleTimes) : 0,
    switched: rows.filter((r) => r.lateShape > 0).length,
    retitled: rows.filter((r) => r.lateText > 0).length,
    flickering: rows.filter((r) => r.flick > 1).length,
    worst: rows.sort((a, b) => (b.offsetSettledAt ?? -1) - (a.offsetSettledAt ?? -1) || b.path - a.path).slice(0, 8),
  };
`;

/** 캔버스 가운데 좌표 — 여기서부터 끈다. */
const CANVAS_CENTER = `
  const canvas = document.querySelector("canvas");
  if (!canvas) return null;
  const box = canvas.getBoundingClientRect();
  return { x: Math.round(box.left + box.width / 2), y: Math.round(box.top + box.height / 2) };
`;

// ---------------------------------------------------------------------------

/** 캔버스를 4초 동안 끄는 **동안** 표본을 뜬다. */
async function measureDuringDrag(cdp, center) {
  const sampling = cdp.evaluate(SAMPLE);
  await cdp.send("Input.dispatchMouseEvent", {
    type: "mousePressed", x: center.x, y: center.y, button: "left", clickCount: 1,
  });
  for (let i = 1; i <= SAMPLES; i += 1) {
    await cdp.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: center.x + i * 6,
      y: center.y + Math.round(Math.sin(i / 3) * 20),
      button: "left",
    });
    await sleep(SAMPLE_MS);
  }
  await cdp.send("Input.dispatchMouseEvent", {
    type: "mouseReleased", x: center.x + SAMPLES * 6, y: center.y, button: "left", clickCount: 1,
  });
  return sampling;
}

async function main() {
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) {
    console.error("Edge·Chrome 을 찾지 못했습니다 — 흔들림을 잴 수 없습니다.");
    return 2;
  }

  const profile = join(process.env.TEMP || ".", `bidpilot-jitter-${PORT}`);
  const browser = spawn(
    exe,
    [
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      `--window-size=${SIZES[0].width},${SIZES[0].height}`,
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--hide-scrollbars",
      // 창이 가려져도 프레임을 계속 그리게 한다 — 안 그러면 rAF 가 멈춰 0 이 나온다.
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
    await clearViewMode(cdp);

    for (const size of SIZES) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false,
      });
      /* 공고마다 **한 번만** 열고 단계를 차례로 누른다 — 담당자가 실제로 하는 순서다.
         단계마다 다시 열면 그때마다 화면이 처음부터 자료를 받아, 재는 4초 안으로 무대
         크기 변화가 들어온다(아래 `STABLE_STAGE` 주석). */
      for (const notice of NOTICES) {
        await cdp.send("Page.navigate", { url: fullUrl(`/analysis?notice=${notice}`) });
        await sleep(1500);
        const ready = await cdp.evaluate(WAIT_STAGE);
        let settledStage = null;
        if (ready) {
          // 선택을 풀어 hover·선택 라벨이 배치에 끼지 않게 한다.
          await cdp.evaluate(`document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); return true;`);
          settledStage = await cdp.evaluate(STABLE_STAGE);
        }
        for (const step of STEPS) {
          const row = { size: size.key, notice, step, ready, settledStage };
          if (!ready) {
            rows.push(row);
            continue;
          }
          row.clicked = await cdp.evaluate(CLICK_STEP(step));
          // 카메라가 옮겨 갈 시간을 준 뒤에 «정지» 를 잰다 (§3-A-6: 2초 뒤 4초).
          await sleep(SETTLE_MS);
          row.still = await cdp.evaluate(SAMPLE);
          const center = await cdp.evaluate(CANVAS_CENTER);
          row.drag = center ? await measureDuringDrag(cdp, center) : null;
          rows.push(row);
        }
      }
    }
  } finally {
    browser.kill();
  }

  // 위반: 정지 중 흔들림 · 드래그 중 모양 전환 · 못 잰 화면·단계
  const total = (row) =>
    (row.ready === false ? 1 : 0) +
    (row.ready && row.clicked === null ? 1 : 0) +
    (row.still?.shaking ?? 0) +
    (row.drag ? row.drag.switched : row.ready ? 1 : 0);

  const violations = rows.reduce((n, r) => n + total(r), 0);

  if (AS_JSON) {
    console.log(JSON.stringify({ rows, violations }, null, 1));
  } else {
    console.log(
      `3D 라벨 흔들림 — ${BASE} · 누른 뒤 ${(SETTLE_MS + (SAMPLES - 1) * SAMPLE_MS) / 1000}초` +
      ` (배치는 ${LAYOUT_SETTLE_MS / 1000}초 안에 자리를 잡아야 한다 · 절대 이동은 ${ABSOLUTE_FROM_MS / 1000}초 이후)` +
      ` · 드래그 ${(SAMPLES * SAMPLE_MS) / 1000}초\n`,
    );
    console.log("  창          공고                       단계  무대       노드  라벨  흔들림  자리잡음  전환  글자  깜빡  크기변화  드래그전환   합");
    for (const row of rows) {
      if (!row.ready) {
        console.log(`  ${row.size.padEnd(12)}${row.notice.padEnd(27)}${String(row.step).padEnd(6)}3D 가 붙지 않아 재지 못했습니다`);
        continue;
      }
      if (row.clicked === null) {
        console.log(`  ${row.size.padEnd(12)}${row.notice.padEnd(27)}${String(row.step).padEnd(6)}레일 단계 버튼(button[data-tour="rail-step-${row.step}"])을 찾지 못했습니다`);
        continue;
      }
      const s = row.still;
      console.log(
        `  ${row.size.padEnd(12)}${row.notice.padEnd(27)}${String(row.step).padEnd(6)}${String(s.stage).padEnd(11)}` +
        `${String(s.nodes).padEnd(6)}${String(s.labels).padEnd(6)}${String(s.shaking).padEnd(8)}` +
        `${(s.layoutSettledAt / 1000).toFixed(1).padEnd(10)}` +
        `${String(s.switched).padEnd(6)}${String(s.retitled).padEnd(6)}${String(s.flickering).padEnd(6)}` +
        `${String(s.stageResizes).padEnd(10)}${String(row.drag ? row.drag.switched : "못 잼").padEnd(13)}${total(row)}`,
      );
    }
    console.log("");
    for (const row of rows) {
      if (!row.still || !total(row)) continue;
      console.log(
        `== ${row.size} · ${row.notice} · 단계 ${row.step}` +
        ` (짝짓기: ${row.still.pairedBy} · 무대 ${row.still.stage}` +
        `${row.still.stageResizes ? ` · 재는 동안 무대 크기 ${row.still.stageResizes}번 바뀜` : ""})`,
      );
      for (const w of row.still.worst.slice(0, 6)) {
        const late = w.offsetSettledAt !== null && w.offsetSettledAt > LAYOUT_SETTLE_MS;
        if (!late && w.lateJump <= JUMP_PX && !w.lateText && !w.lateShape && w.flick <= 1) continue;
        console.log(
          `   [흔들림] 「${w.label.slice(0, 16)}」 ${w.variant}` +
          ` · 배치가 마지막으로 바뀐 때 ${w.offsetSettledAt === null ? "없음" : `${((SETTLE_MS + w.offsetSettledAt) / 1000).toFixed(1)}초(${w.offsetJump}px)`}` +
          `${w.lateJump > JUMP_PX ? ` · ${(ABSOLUTE_FROM_MS / 1000).toFixed(0)}초 이후 절대 이동 ${w.lateJump}px(${((SETTLE_MS + w.lateJumpAt) / 1000).toFixed(1)}초)` : ""}` +
          ` · 누적 ${w.path}px · 글자 ${w.lateText} · 모양 ${w.lateShape} · 깜빡 ${w.flick}`,
        );
      }
      if (row.drag?.switched) {
        for (const w of row.drag.worst.slice(0, 4)) {
          if (!w.shapeChanges) continue;
          console.log(`   [드래그] 「${w.label.slice(0, 16)}」 글자↔번호 ${w.shapeChanges}회`);
        }
      }
      console.log("");
    }
    const pairings = [...new Set(rows.map((r) => r.still?.pairedBy).filter(Boolean))];
    if (pairings.length) console.log(`  라벨 짝짓기: ${pairings.join(" · ")}`);
    console.log(violations ? `흔들림 위반 ${violations}건 — 위 목록을 보세요.` : "흔들림 없음 · 드래그 중 전환 없음.");
  }

  return violations > 0 ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error);
    process.exit(2);
  },
);
