/**
 * 시인성 검사 — 화면의 글자를 **브라우저에서 실제로 재서** 위반을 센다 (0925 §4-F-6).
 *
 * ## 왜 스크립트로 재는가
 *
 * 검수자는 브라우저에서 computed style 로 재어 「본문 메타 `rgb(107,122,159)` 가 카드
 * 배경 위에서 4.32:1」·「11px 이 28곳」·「머리띠 두 요소가 99px 겹친다」를 적어 왔다.
 * 감으로 색을 고치면 다음 번에 같은 자리가 다시 어두워진다. **같은 방법으로 재서**
 * 전후를 비교할 수 있어야 한다.
 *
 * ## 무엇을 재는가 (하나라도 어기면 종료 코드 1)
 *
 *   a. 보이는 텍스트 노드 중 **12px 미만** 0건
 *   b. **18px 미만** 글자의 대비 **4.5:1 미만** 0건
 *      — 담당자가 결정에 쓰는 문장(판정 사유·회사에 뜻하는 것·사람이 할 일·
 *        갖추면 열린다)은 **7:1 미만**도 위반이다
 *   c. 머리띠·카드 머리 요소의 사각형 **겹침** 0건
 *   d. `{}`·`[]`·`null`·`undefined` 텍스트 노드 0건
 *
 * 배경은 조상 중 **첫 불투명 배경**을 찾아 그 위에 알파 있는 배경들을 차례로 합성한다.
 * 3D 레이더 캔버스 «안»의 글자는 DOM 이 아니라 그림이라 이 검사의 범위가 아니다
 * (0925 §4-F 하지 말 것).
 *
 * ## 왜 Playwright 가 아닌가
 *
 * 0925 §4-F-6 은 Playwright 를 적었지만 이 저장소에 없다. `capture_rehearsal.mjs` 가
 * 같은 이유로 **CDP 를 직접** 쓴다(의존성을 늘리지 않는다). 같은 방식을 그대로 따른다 —
 * 재는 값은 둘 다 `getComputedStyle`·`getBoundingClientRect` 라 방법이 아니라 도구만 다르다.
 *
 * 쓰기:
 *   node scripts/check_visibility.mjs
 *   node scripts/check_visibility.mjs --base http://localhost:3110 --widths 1280,1440,1920
 *   node scripts/check_visibility.mjs --sizes 2000x669,1920x720
 *   node scripts/check_visibility.mjs --json
 *   node scripts/check_visibility.mjs --only-new            (24차 쉬운 보기 · 삭제 없음 · 첫 방문 · 주소 유지만)
 *   node scripts/check_visibility.mjs --real-notice g2b-…    (쉬운 보기 표의 실공고를 정해서)
 *   node scripts/check_visibility.mjs --theme light           (2.4.0 ⑥ 밝은 화면 — 새 문서마다 저장 값을 넣고 연다 · 쉬운 보기 대비도 잰다)
 *
 * 기존 표는 모두 **전체 보기**(`?mode=full`)를 잰다. 쉬운 보기는 아래 「쉬운 보기」 표가 따로 잰다 (24차 §4-E).
 *
 * 기본은 높이 1200 의 폭 셋 + 낮은 창 둘(2000×669 · 1920×720) = **다섯 크기**다.
 * `--widths` 는 앞의 셋만 바꾼다(낮은 창 둘은 그대로 붙는다). 크기를 직접 정하려면 `--sizes`.
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
const PORT = Number(argOf("--port", "9233"));
const WIDTHS = argOf("--widths", "1280,1440,1920").split(",").map(Number);
const AS_JSON = args.includes("--json");
const HEIGHT = Number(argOf("--height", "1200"));
const ONLY_NEW = args.includes("--only-new");
/** 화면 밝기(2.4.0 ⑥) — light 면 화면을 열기 전에 `bidpilot.theme.v1 = light` 를 넣는다. 그 밖은 어두운 화면(기본). */
const THEME = argOf("--theme", "dark") === "light" ? "light" : "dark";
const THEME_LABEL = THEME === "light" ? "밝은 화면" : "어두운 화면";
/** 백엔드 — 첫 방문의 「회사 방식 1위」를 같은 목록에서 읽어 견준다(37차 §3-C-4 · 읽기만). */
const BACKEND = (() => {
  const i = args.indexOf("--backend");
  return i >= 0 && args[i + 1] ? args[i + 1] : "http://127.0.0.1:8110";
})();

/** 회사 방식(정렬 없이 받은 목록)의 나라장터 1위 — 대시보드 `firstRealNoticeId` 와 같은 거르기(마감 전 · 불가 아님 · 가상 예시 아님). */
async function companyFirstNotice() {
  try {
    const listing = await (await fetch(`${BACKEND}/api/business-opportunities?source=g2b&limit=30&days=30`)).json();
    const now = Date.now();
    // 화면(firstRealNoticeId)과 같은 규칙 — 마감 전 판단은 서버 `closed`, 입찰 마감 칸이 빈 「마감 미상」도 1위가 될 수 있다(2.0.5)
    const top = (listing.items || []).find((i) => !i.closed && i.eligibility_gate !== "FAIL" && !String(i.id).startsWith("synthetic-") && (!i.deadline || Date.parse(i.deadline) > now));
    return { id: top ? top.id : null, method: listing.ranking_method ?? null };
  } catch (error) {
    return { id: null, method: null, error: String(error.message || error) };
  }
}
// --screens a,b — 표의 화면을 이름으로 좁힌다(다시 잴 때 · 29차). 없으면 전부.
const SCREEN_FILTER = (() => { const i = args.indexOf("--screens"); return i >= 0 ? args[i + 1].split(",") : null; })();

/**
 * 재는 창 크기 — 기존 셋(높이 1200)에 **낮은 창 둘**을 더한다 (ISSUE-122 · prompt_04 §3-B-2).
 *
 * 2000×669 는 담당자가 우측 상세 패널이 접혀 겹치는 것을 본 창이고, 1920×720 은 그 경계
 * (창 높이 약 750px) 바로 아래다. 이 검사는 **높이 1200 으로만** 재고 있었다 — 그래서
 * 우측 열이 0px 로 접혀 머리·본문·결정 블록이 서로 겹쳐 흘러넘치는 것을 조용히 통과시켰다.
 * 폭만 늘려도 안 잡힌다. 높이가 문제였다.
 */
const SIZES = (() => {
  const explicit = argOf("--sizes", null);
  if (explicit) {
    return explicit.split(",").map((spec) => {
      const [width, height] = spec.trim().toLowerCase().split("x").map(Number);
      return { width, height };
    });
  }
  return [
    ...WIDTHS.map((width) => ({ width, height: HEIGHT })),
    { width: 2000, height: 669 },
    { width: 1920, height: 720 },
  ];
})().map((size) => ({ ...size, key: `${size.width}×${size.height}` }));

// 지원사업 예시 — 126482(10-06 마감) → 123852(신청 분석 A1 과 같은 공고). 고르는 조건은 check_page_unity.mjs 의 SUPPORT 주석.
// 단계 화면(아래 SCREENS)과 쉬운 보기 · 첨부 검사가 이 한 곳을 쓴다.
const SUPPORT_ID = "bizinfo-PBLN_000000000123852";

/** 네 화면. 신청 분석은 A1(기준 답안 1순위) 으로 고정한다. */
const SCREENS = [
  // 공고를 고른 상태로 연다 — 머리띠의 「입찰 마감 D-n」 칩은 분석 대상이 있을 때만
  // 그려지고, 검수자가 잰 99px 겹침이 바로 그 칩과 회사 칩 사이였다 (0925 §4-F-4).
  // `has3d` 인 화면은 노드 수를 못 읽으면 **위반**이다. 못 읽으면 「라벨 없는 점」 검사가
  // 조용히 건너뛰어 늘 통과하는 검사가 된다 (prompt_01 §4-A-6).
  /* `panel: true` 인 화면은 우측 상세 열의 세 블록(머리·본문·결정)을 반드시 잰다.
     `data-panel-region` 을 못 찾으면 **위반**이다 — 검사가 조용히 건너뛰면 다시 접힌다. */
  // 2.1.3 — 3D 를 화면에서 뺐다(대표 10-31). 지도는 2D 로 잰다(`data-cosmos-nodes` 는 3D 만 달아 has3d 는 끔).
  { key: "대시보드", path: "/analysis?notice=synthetic-rfp-0001&view=2d", has3d: false, panel: true },
  { key: "사업기회 목록", path: "/opportunities" },
  { key: "레이더", path: "/radar", has3d: false },
  { key: "신청 분석(A1)", path: `/support/${SUPPORT_ID}` },
  // 32차 §3-A-11 — 실전 가이드(문서 화면). 넓은 창 셋에 더해 390 폭에서도 잰다(narrow).
  { key: "실전 가이드", path: "/guide", narrow: true },
  /* 지원사업 대시보드 3D 를 **단계별로** 잰다 (prompt_02 §4-E-3).
     12차까지 이 화면은 검사에 없었다 — 라벨을 고친 곳이 바로 여기인데도.
     단계를 눌러 세 번 재는 이유는 단계마다 밝은 노드와 라벨 모양이 달라지기 때문이다. */
  // 28차 §3-F — 지원사업 대시보드는 그림(3D)을 사람이 켤 때만 그린다. 기본(그림 꺼짐)의 단계 본문을 잰다.
  { key: "지원사업 1단계", path: `/analysis?support=${SUPPORT_ID}`, has3d: false, step: "신청자격" },
  { key: "지원사업 4단계", path: `/analysis?support=${SUPPORT_ID}`, has3d: false, step: "제출서류" },
  { key: "지원사업 6단계", path: `/analysis?support=${SUPPORT_ID}`, has3d: false, step: "사업계획서" },
  // 2.1.3 — 지원사업 「그림으로 보기(3D)」 단추를 없앴다(3D 를 화면에서 뺌) — 그림 단계 검사도 뺀다.
];

const BROWSERS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// CDP — `capture_rehearsal.mjs` 와 같은 최소 구현
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
// 페이지 안에서 도는 검사 — CDP 는 함수를 못 보내므로 문자열이다
// ---------------------------------------------------------------------------

const PROBE = String.raw`
  /* 재기 전에 **끝난 것으로 볼 수 있는 애니메이션을 끝낸다.**

     이 검사는 「자리를 잡은 화면」의 글자와 사각형을 잰다. 그런데 상세 패널 본문은
     등장 애니메이션(cosmos-panel-in 200ms, opacity 0 → 1)을 달고 있어, 그 200ms 안에
     재면 opacity 0 으로 읽혀 「우측 열을 재지 못했다」가 된다 — 실제로 다섯 크기를 한 번에
     도는 실행에서 네 크기가 그렇게 떨어졌다. 애니메이션 중간을 재는 것은 앱의 상태가
     아니라 재는 순간의 운이다.

     무한 반복(cosmos-pulse 등)은 끝낼 수 없어 예외가 난다 — 그것만 조용히 넘긴다.
     판정을 느슨하게 하는 것이 아니다: 끝난 상태가 곧 담당자가 보는 화면이다. */
  if (document.getAnimations) {
    for (const animation of document.getAnimations()) {
      try { animation.finish(); } catch (error) { /* 무한 반복은 끝낼 수 없다 */ }
    }
  }

  // --- 색 ------------------------------------------------------------------
  /* 크롬은 color-mix() 결과를 color(srgb r g b / a)(0~1)로 돌려준다(11-04 실측). Tailwind 투명도 클래스
     (color-mix in oklab)는 oklab(L a b / a)로 올 것이다(아직 재지 않음). rgb() 만 읽으면 물든 칩 · 겹 패널 겹이
     빠져 대비가 틀린다 — color(srgb) · oklab · oklch 도 sRGB 0~255 로 바꿔 읽는다(2.4.0 ⑥). */
  const toByte = (linear) => {
    const c = Math.min(1, Math.max(0, linear));
    return 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
  };
  const fromOklab = (L, A, B) => {
    const l = Math.pow(L + 0.3963377774 * A + 0.2158037573 * B, 3);
    const m = Math.pow(L - 0.1055613458 * A - 0.0638541728 * B, 3);
    const s = Math.pow(L - 0.0894841775 * A - 1.291485548 * B, 3);
    return {
      r: toByte(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
      g: toByte(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
      b: toByte(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
    };
  };
  /** 낱말 하나 — 백분율이면 scale 의 몇 % 인지(rgb 255 · oklab a/b 0.4 · 그 밖 1). none 은 0. */
  const num = (token, scale = 1) => (token === "none" ? 0 : token.endsWith("%") ? (parseFloat(token) / 100) * scale : parseFloat(token));
  const parse = (value) => {
    const m = String(value || "").match(/(rgba?|color|oklab|oklch)\(([^)]+)\)/);
    if (!m) return null;
    const tokens = m[2].split(/[\s,\/]+/).filter(Boolean);
    if (m[1] === "color" && tokens.shift() !== "srgb") return null;
    if (tokens.length < 3) return null;
    const alpha = tokens.length > 3 ? num(tokens[3]) : 1;
    let rgb;
    if (m[1] === "color") rgb = { r: num(tokens[0]) * 255, g: num(tokens[1]) * 255, b: num(tokens[2]) * 255 };
    else if (m[1] === "oklab") rgb = fromOklab(num(tokens[0]), num(tokens[1], 0.4), num(tokens[2], 0.4));
    else if (m[1] === "oklch") {
      const chroma = num(tokens[1], 0.4);
      const hue = ((parseFloat(tokens[2]) || 0) * Math.PI) / 180;
      rgb = fromOklab(num(tokens[0]), chroma * Math.cos(hue), chroma * Math.sin(hue));
    } else rgb = { r: num(tokens[0], 255), g: num(tokens[1], 255), b: num(tokens[2], 255) };
    if ([rgb.r, rgb.g, rgb.b, alpha].some(Number.isNaN)) return null;
    return { r: rgb.r, g: rgb.g, b: rgb.b, a: alpha };
  };

  /** 알파 있는 색을 아래 색 위에 얹는다. */
  const over = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  });

  /* 맨 아래 바닥 — 실제 페이지 바닥(html 배경: 어두운 화면 --cosmos-bg-deep · 밝은 화면 #e8ecf3). 예전에는 투명이면 흰색,
     반투명 맨 아래는 검정 위에 얹었다 — 밝은 화면에서는 틀린 바닥이다(2.4.0 ⑥). 못 읽으면 흰색. */
  const PAGE_BG = (() => {
    const white = { r: 255, g: 255, b: 255, a: 1 };
    const color = parse(getComputedStyle(document.documentElement).backgroundColor);
    if (!color || color.a === 0) return white;
    return color.a < 1 ? over(color, white) : color;
  })();

  const luminance = ({ r, g, b }) => {
    const channel = (value) => {
      const c = value / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };

  const ratio = (fore, back) => {
    const a = luminance(fore);
    const b = luminance(back);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };

  /**
   * 글자 뒤의 실제 색. **조상 중 첫 불투명 배경**까지 올라가 알파 있는 것들을
   * 위에서부터 차례로 합성한다 (0925 §4-F-6).
   */
  const backgroundOf = (element) => {
    const stack = [];
    for (let node = element; node; node = node.parentElement) {
      const color = parse(getComputedStyle(node).backgroundColor);
      if (!color || color.a === 0) continue;
      stack.push(color);
      if (color.a >= 1) break;
    }
    if (!stack.length) return PAGE_BG;
    let base = stack[stack.length - 1];
    if (base.a < 1) base = over(base, PAGE_BG);
    for (let i = stack.length - 2; i >= 0; i -= 1) base = over(stack[i], base);
    return base;
  };

  const visible = (element) => {
    const style = getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (Number(style.opacity) === 0) return false;
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };

  /**
   * **담당자가 결정에 쓰는 문장** — 7:1 이 필요한 자리 (0925 §4-F-1).
   * 글자로 찾는다. 이 문구를 바꾸면 이 목록도 함께 고친다.
   */
  const DECISION_WORDS = [
    "우리 회사 입장에서", "전화로 확인할 일", "갖추면 가능", "왜 맞나",
    // 31차 §3-B — 「이번 주 할 일」의 등록 확인 · 유효기간 줄도 잘리면 안 되는 판단 글이다
    "직접 확인할 일", "곧 만료", "만료됨",
  ];
  const isDecision = (element) => {
    const own = (element.textContent || "").slice(0, 200);
    const near = (element.parentElement?.textContent || "").slice(0, 200);
    return DECISION_WORDS.some((w) => own.includes(w) || near.includes(w));
  };

  // --- 텍스트 노드를 모은다 -------------------------------------------------
  //
  // 3D 레이더는 <canvas> 에 그린 그림이라 텍스트 노드가 없다 — 자연히 빠진다.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const small = [];
  const lowContrast = [];
  const literals = [];
  const LITERALS = ["{}", "[]", "null", "undefined"];
  const seen = new Set();

  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.nodeValue || "").trim();
    if (!text) continue;
    const element = node.parentElement;
    if (!element || element.closest("script, style, noscript, svg, canvas")) continue;
    if (!visible(element)) continue;

    if (LITERALS.includes(text)) {
      literals.push({ text, where: element.className || element.tagName });
      continue;
    }

    const style = getComputedStyle(element);
    const size = Number.parseFloat(style.fontSize);
    const sample = text.slice(0, 38);
    const key = element.tagName + "|" + (element.className || "") + "|" + sample;
    if (seen.has(key)) continue;
    seen.add(key);

    if (size < 12) small.push({ size: Math.round(size * 100) / 100, text: sample });

    if (size >= 18) continue;
    const fore = parse(style.color);
    if (!fore) continue;
    const back = backgroundOf(element);
    const flat = fore.a < 1 ? over(fore, back) : fore;
    const value = Math.round(ratio(flat, back) * 100) / 100;
    // 굵은 14px 이상은 WCAG 「큰 글자」라 3:1 이지만, 이 화면은 본문 메타가
    // 문제라 구분하지 않는다 — 18px 미만은 전부 4.5:1 로 본다 (0925 §4-F-1).
    const need = isDecision(element) ? 7 : 4.5;
    if (value < need) {
      lowContrast.push({
        ratio: value, need, size: Math.round(size * 100) / 100, text: sample,
        color: style.color, background: "rgb(" + [back.r, back.g, back.b].map(Math.round).join(",") + ")",
      });
    }
  }

  // --- 겹침 ----------------------------------------------------------------
  //
  // 머리띠(대시보드 상단 칩 줄)와 카드 머리의 **형제 요소**끼리만 본다.
  // 부모·자식은 당연히 겹치므로 셀 수 없고, 줄바꿈으로 다른 줄에 선 것도 겹침이 아니다.
  const overlaps = [];
  const STRIPS = "[data-visibility-strip]";
  for (const strip of document.querySelectorAll(STRIPS)) {
    const kids = [...strip.children].filter(visible).map((el) => ({
      el, box: el.getBoundingClientRect(), text: (el.textContent || "").trim().slice(0, 24),
    }));
    for (let i = 0; i < kids.length; i += 1) {
      for (let j = i + 1; j < kids.length; j += 1) {
        const a = kids[i].box;
        const b = kids[j].box;
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        // 1px 는 테두리가 맞닿은 것이다. 2px 넘게 겹치면 글자가 가려진다.
        if (x > 2 && y > 2) {
          overlaps.push({ a: kids[i].text, b: kids[j].text, x: Math.round(x), y: Math.round(y) });
        }
      }
    }
  }
  const strips = document.querySelectorAll(STRIPS).length;

  /* 「라벨이 없는 점」 (prompt_01 §4-A-6).
     3D 노드는 캔버스 안 메시라 DOM 으로 셀 수 없다 — Cosmos3D 가 지금 그리는 노드 수를
     documentElement 에 적어 두고(측정 전용), 여기서 DOM 라벨 수와 견준다.
     노드 수를 안 적는 화면(목록 등)은 3D 가 없다는 뜻이라 검사 대상이 아니다. */
  const nodeCountRaw = document.documentElement.dataset.cosmosNodes;
  const allLabels = [...document.querySelectorAll("[data-cosmos-label]")];
  /* **보이는** 라벨만 센다 (ISSUE-114 · prompt_02 §4-E-1).
     12차는 DOM 개수를 셌다. 그런데 충돌로 자리를 못 찾거나 카메라에서 멀어진 라벨은
     DOM 에 남은 채 opacity 만 0 이 된다 — 재검증 실측으로 입찰 대시보드 38개 중 14개가
     그 상태였는데 검사는 「무명점 0」으로 통과했다. 눈에 안 보이면 라벨이 아니다. */
  const labelCount = allLabels.filter((el) => {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (Number(style.opacity) <= 0.05) return false;
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  }).length;
  const nodeCount = nodeCountRaw === undefined ? null : Number(nodeCountRaw);
  const unlabeled = nodeCount === null ? 0 : Math.max(0, nodeCount - labelCount);

  /* 정거장 지도(21차 · prompt_11 §4-F) — 입찰 3D 에서만 잰다(레이더·지원사업 3D 는 이 표시가 없다).
     (1) 라벨 글자 13px 이상: 계산된 글자 크기 × 라벨 transform 의 scale. CSS scale 은 계산된 font-size 를
         바꾸지 않으므로 곱해야 한다(0.82 배율이면 13px 가 10.7px 로 그려졌다).
     (2) 지금 정거장 점 전부에 **긴 라벨**: 지금 정거장의 점 수(data-cosmos-station-nodes)와, 그 정거장에 선
         보이는 긴 라벨 중 번호 칩으로 줄지 않은 것의 수를 견준다. 모자라면 그만큼 위반이다. */
  const station = document.documentElement.dataset.cosmosStation ?? null;
  const shownLabel = (el) => {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) <= 0.05) return false;
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };
  const scaleOf = (el) => {
    const m = /scale\(([0-9.]+)\)/.exec(el.style.transform || "");
    return m ? Number(m[1]) : 1;
  };
  const smallLabels = [];
  let stationMissing = 0;
  let stationLong = 0;
  /* 지금 정거장 긴 라벨끼리 겹친 쌍 — 「라벨이 있다」만 세면 서로 덮여 못 읽는 라벨도 통과한다 (21차 검토). */
  let stationOverlaps = 0;
  const stationNodes = station === null ? null : Number(document.documentElement.dataset.cosmosStationNodes ?? -1);
  if (station !== null) {
    for (const el of allLabels.filter(shownLabel)) {
      const scale = scaleOf(el);
      for (const node of el.querySelectorAll("*")) {
        if (!node.childNodes.length || ![...node.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
        if (!shownLabel(node)) continue;
        const px = parseFloat(getComputedStyle(node).fontSize) * scale;
        if (px < 12.95) smallLabels.push({ text: node.textContent.trim().slice(0, 24), size: Math.round(px * 10) / 10 });
      }
    }
    const longEls = allLabels.filter((el) => {
      if (el.getAttribute("data-cosmos-station") !== station || el.getAttribute("data-cosmos-label") !== "long") return false;
      if (!shownLabel(el)) return false;
      const chip = el.querySelector("[data-cosmos-number]");
      return !chip || getComputedStyle(chip).display === "none";
    });
    stationLong = longEls.length;
    const rects = longEls.map((el) => el.getBoundingClientRect());
    for (let i = 0; i < rects.length; i += 1) {
      for (let j = i + 1; j < rects.length; j += 1) {
        const a = rects[i], b = rects[j];
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (x > 2 && y > 2) stationOverlaps += 1;
      }
    }
    stationMissing = stationNodes >= 0 ? Math.max(0, stationNodes - stationLong) : 1;
  }
  /* ③ 캡션이 잘리는가 (22차 §4-B) — 「조항 확인 전 n · 공고 필드 확인 m」 두 수가 끝까지 읽혀야 한다.
     캡션은 max-w 220px · truncate 라 잘리면 scrollWidth 가 clientWidth 보다 크다(1px 는 반올림). */
  const caption3 = document.querySelector('[data-cosmos-station-name="3"] [data-cosmos-station-caption]');
  const caption3Text = caption3 ? caption3.textContent.trim() : null;
  // 2D(SVG 글자)는 폭에 맞춰 「…」로 자른다 — 끝이 「…」면 잘린 것이다.
  const caption3Clipped = !caption3 || !shownLabel(caption3) ? 0
    : caption3 instanceof SVGElement ? (caption3Text.endsWith("…") ? 1 : 0)
    : caption3.scrollWidth - caption3.clientWidth > 1 ? 1 : 0;

  /* 낮은 창에서 **우측 상세 열이 접히지 않는가** (ISSUE-122 · prompt_04 §3-B-2).

     2000×669 에서 우측 열이 0px 로 접혀, shrink-0 인 머리(105px)·결정(126px) 블록이
     열 밖으로 흘러 서로 겹쳤다. 스크롤 본문은 32px 로 눌려 내용 758px 을 담지 못했다.
     세 사각형이 서로 겹치지 않고 · 본문이 최소 160px 이고 · 열 높이가 0 이 아닌지 본다. */
  const regionOf = (name) => document.querySelector('[data-panel-region="' + name + '"]');
  const panel = {
    measured: false, column: 0, head: 0, body: 0, decision: 0,
    blocks: [], overlaps: [], footerOverlaps: [], overflowBelow: 0, short: 0, collapsed: 0, missing: [],
  };
  const columnEl = regionOf("column");
  const names = ["head", "body", "decision"];
  const found = names.map((name) => ({ name, el: regionOf(name) }));
  const boxes = found
    .filter((r) => r.el && visible(r.el))
    .map((r) => ({ name: r.name, box: r.el.getBoundingClientRect() }));
  /* 못 찾았으면 **무엇을** 못 찾았는지 적는다 — 「우측 열을 찾지 못했습니다」만으로는
     열이 없는 것인지 한 블록이 아직 안 그려진 것인지 알 수 없다. */
  panel.missing = [
    ...(columnEl ? (visible(columnEl) ? [] : ["column(안 보임)"]) : ["column(없음)"]),
    ...found.filter((r) => !r.el).map((r) => r.name + "(없음)"),
    ...found.filter((r) => r.el && !visible(r.el)).map((r) => {
      const box = r.el.getBoundingClientRect();
      const style = getComputedStyle(r.el);
      return r.name + "(안 보임 " + Math.round(box.width) + "×" + Math.round(box.height) +
        " display:" + style.display + " opacity:" + style.opacity + ")";
    }),
  ];
  if (columnEl && boxes.length === names.length) {
    panel.measured = true;
    const columnBox = columnEl.getBoundingClientRect();
    panel.column = Math.round(columnBox.height);
    for (const { name, box } of boxes) panel[name] = Math.round(box.height);
    panel.blocks = boxes.map(({ name, box }) => ({
      name, top: Math.round(box.top), height: Math.round(box.height),
    }));

    /* 「세 사각형이 서로 겹치는가」**만** 보면 결함이 있어도 통과한다 — 세로 flex 에서
       형제는 서로 겹치지 않는다. 실제로 본 것은 세 블록이 **열 밖으로 흘러** 바닥
       출처줄과 3D 오버레이 위에 그려지는 것이었다(검수 §4). 그래서 두 가지를 더 잰다:
       패널 바닥이 열 바닥을 넘는가 · 바닥 출처줄과 겹치는가. */
    panel.overflowBelow = Math.max(0, Math.round(boxes[boxes.length - 1].box.bottom - columnBox.bottom));
    const footer = document.querySelector('footer[data-tour="bottom-sources"]');
    if (footer && visible(footer)) {
      const f = footer.getBoundingClientRect();
      for (const { name, box } of boxes) {
        const x = Math.min(box.right, f.right) - Math.max(box.left, f.left);
        const y = Math.min(box.bottom, f.bottom) - Math.max(box.top, f.top);
        if (x > 2 && y > 2) panel.footerOverlaps.push({ name, x: Math.round(x), y: Math.round(y) });
      }
    }
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i].box;
        const b = boxes[j].box;
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        // 1px 는 테두리가 맞닿은 것이다. 2px 넘게 겹치면 글자가 가려진다 (머리띠 검사와 같은 기준).
        if (x > 2 && y > 2) {
          panel.overlaps.push({ a: boxes[i].name, b: boxes[j].name, x: Math.round(x), y: Math.round(y) });
        }
      }
    }
    // 본문 160px — 이보다 낮으면 「스크롤되는 상세」라고 할 수 없다 (실측 32px).
    if (panel.body < 160) panel.short = 1;
    if (panel.column <= 0) panel.collapsed = 1;
  }

  return {
    small, lowContrast, literals, overlaps, strips,
    nodeCount, labelCount, domLabelCount: allLabels.length, unlabeled, panel,
    station, stationNodes, stationLong, stationMissing, stationOverlaps, smallLabels, caption3Text, caption3Clipped,
    width: window.innerWidth, height: window.innerHeight,
  };
`;

/**
 * **첫 화면** (21차 · prompt_11 §3-7 · §4-F) — 스크롤 0 에서 정거장 이름 8개와 상세 열 머리가 보이는가.
 *
 * 재검증이 본 것은 1440×900 첫 화면에 지도가 없다는 것이었다(오늘 · 이번 주 · 지금 할 일 · KPI 가 900px 을 채웠다).
 * 이름은 투명도가 있는 조상까지 보고(0.05 넘게), 글자는 18px 이상, 사각형은 창 안 · 지도 구역 안이어야 한다
 * (getBoundingClientRect 는 overflow-hidden 을 모른다 — 구역 밖으로 나간 이름을 걸러야 한다).
 */
const PROBE_FIRST = `
  window.scrollTo(0, 0);
  await new Promise((r) => setTimeout(r, 400));
  const seen = (el) => {
    for (let x = el; x; x = x.parentElement) {
      const st = getComputedStyle(x);
      if (st.display === "none" || st.visibility === "hidden" || Number(st.opacity) <= 0.05) return false;
    }
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };
  const section = document.querySelector('section[data-tour="stage"]');
  const sec = section ? section.getBoundingClientRect() : null;
  const names = [...document.querySelectorAll("[data-cosmos-station-name]")];
  const byId = new Map();
  for (const el of names) byId.set(el.getAttribute("data-cosmos-station-name"), el);
  const problems = [];
  for (const id of ["1", "2", "3", "4", "5", "6", "7", "8"]) {
    const el = byId.get(id);
    if (!el) { problems.push(id + " 없음"); continue; }
    if (!seen(el)) { problems.push(id + " 안 보임"); continue; }
    const box = el.getBoundingClientRect();
    const size = Math.max(...[el, ...el.querySelectorAll("*")].map((x) => parseFloat(getComputedStyle(x).fontSize) || 0));
    if (size < 18) problems.push(id + " 글자 " + size + "px");
    if (box.top < 0 || box.bottom > innerHeight || box.left < 0 || box.right > innerWidth) problems.push(id + " 창 밖 y" + Math.round(box.top));
    if (sec && (box.top < sec.top || box.bottom > sec.bottom || box.left < sec.left || box.right > sec.right)) problems.push(id + " 지도 밖");
  }
  const head = document.querySelector('[data-panel-region="head"]');
  const hb = head ? head.getBoundingClientRect() : null;
  if (!head || !seen(head)) problems.push("상세 머리 없음");
  else if (hb.top < 0 || hb.bottom > innerHeight) problems.push("상세 머리 창 밖 " + Math.round(hb.top) + "~" + Math.round(hb.bottom));
  const nameTops = names.map((el) => Math.round(el.getBoundingClientRect().top));
  return {
    scrollY: window.scrollY, names: byId.size, problems,
    nameY: nameTops.length ? Math.min(...nameTops) : null,
    head: hb ? [Math.round(hb.top), Math.round(hb.bottom)] : null,
    section: sec ? [Math.round(sec.top), Math.round(sec.bottom)] : null,
  };
`;

/** 첫 화면을 재는 창 — `--sizes` 로 바꾸지 않는다(프롬프트가 정한 셋이다). */
const FIRST_SIZES = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 2000, height: 669 },
].map((size) => ({ ...size, key: `${size.width}×${size.height}` }));
const FIRST_URL = "/analysis?notice=synthetic-rfp-0001&welcome=0";
/** 첫 화면 · 정거장 순회는 지도(2D)로 고정 — 2.1.3 부터 3D 는 화면에 없다(이름은 옛 것 그대로). */
const FIRST_URL_3D = `${FIRST_URL}&view=2d`;

/**
 * 좁은 캔버스 (22차 · prompt_12 §4-C) — 창은 넓어도 레일을 펼치면 지도 칸이 좁다. 그때 정거장 이름 여덟 개가
 * 서로 겹치지 않는가(겹친 쌍 0). 2D·3D 모두 `[data-cosmos-station-name]` 을 달고, 그 안에서 가장 큰 글자가 이름이다.
 */
const NARROW_CASES = [
  { width: 1024, height: 1366, rail: "open" },
  { width: 1024, height: 1366, rail: "closed" },
  { width: 1280, height: 900, rail: "open" },
].map((c) => ({ ...c, key: `${c.width}×${c.height} 레일 ${c.rail === "open" ? "펼침" : "접힘"}` }));

const PROBE_NARROW = `
  const section = document.querySelector('section[data-tour="stage"]');
  const names = [...document.querySelectorAll("[data-cosmos-station-name]")];
  const nameBox = (g) => {
    let best = null, size = 0;
    for (const el of [g, ...g.querySelectorAll("*")]) {
      if (!el.childNodes.length || ![...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
      const px = parseFloat(getComputedStyle(el).fontSize) || 0;
      if (px > size) { size = px; best = el; }
    }
    return best ? { box: best.getBoundingClientRect(), size, text: best.textContent.trim() } : null;
  };
  const boxes = names.map(nameBox).filter(Boolean);
  const nameCount = boxes.length;
  // 27차 §3-D-11 — 정거장 낱말 알약도 이름 · 다른 알약과 겹치면 안 된다(이름 수에는 넣지 않는다).
  for (const flag of document.querySelectorAll("[data-station-flag]")) {
    const box = flag.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) boxes.push({ box, size: 13, text: "알약:" + flag.getAttribute("data-station-flag") });
  }
  const overlaps = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i].box, b = boxes[j].box;
      const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (x > 2 && y > 2) overlaps.push(boxes[i].text + "↔" + boxes[j].text);
    }
  }
  const cap3 = document.querySelector('[data-cosmos-station-name="3"] [data-cosmos-station-caption]');
  const cap3Text = cap3 ? cap3.textContent.trim() : null;
  const cap3Clipped = !cap3 ? 0 : cap3 instanceof SVGElement ? (cap3Text.endsWith("…") ? 1 : 0) : (cap3.scrollWidth - cap3.clientWidth > 1 ? 1 : 0);
  return {
    caption3: cap3Text, caption3Clipped: cap3Clipped,
    canvas: section ? Math.round(section.clientWidth) : null,
    view: section && section.querySelector("canvas") ? "3D" : section && section.querySelector("svg") ? "2D" : "?",
    names: nameCount,
    minSize: nameCount ? Math.min(...boxes.slice(0, nameCount).map((b) => b.size)) : null,
    overlaps,
    warning: !!document.querySelector("[data-narrow-canvas]"),
  };
`;

// ---------------------------------------------------------------------------

/**
 * **잴 것이 다 붙었는가** — 라벨이 노드 수만큼 보이고, 우측 열을 재는 화면이면 그 열도 있는가.
 *
 * 기다림이 판정을 바꾸지는 않는다. 참이 되면 바로 돌아오고, 안 되면 그대로 재서 위반으로
 * 센다 — 「조건이 참이 될 때까지 기다린 뒤 그 조건을 검사한다」가 아니다.
 */
const READY = (screen) => `
  /** 검사가 «보인다」고 셀 때와 **같은 조건**으로 본다 — 더 느슨하면 못 그려진 화면을 잰다. */
  const shown = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (Number(style.opacity) <= 0.05) return false;
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };
  if (document.getAnimations) {
    for (const animation of document.getAnimations()) {
      try { animation.finish(); } catch (error) { /* 무한 반복은 끝낼 수 없다 */ }
    }
  }
  const nodes = Number(document.documentElement.dataset.cosmosNodes ?? -1);
  const labels = [...document.querySelectorAll("[data-cosmos-label]")].filter(shown).length;
  const panel = ${
    screen.panel
      ? `["column", "head", "body", "decision"].every((name) => shown(document.querySelector('[data-panel-region="' + name + '"]')))`
      : "true"
  };
  return { ok: (${screen.has3d ? "nodes >= 0 && labels >= nodes" : "true"}) && panel, nodes };
`;

/**
 * 등장 애니메이션·우측 패널 마운트가 끝나기를 기다린다 (최대 20초).
 *
 * 예전에는 고정 2.5초였다. 바쁜 서버에서 1920×720 대시보드가 **우측 열이 아직 마운트되지
 * 않은 채로** 측정되어 「미측정 1 · 무명점 3」이 났다 — 같은 실행의 2000×669 는 통과했다.
 * 앱이 아니라 검사가 성급했던 자리다(12차의 3D 폴링과 같은 교훈).
 *
 * **노드 수가 멈출 때까지도 기다린다** (15차 · ISSUE-128). 조건이 참인 순간에 재는 것만으로는
 * 모자랐다 — 이 화면은 분석 결과가 뒤늦게 도착하며 그래프가 커진다(실측: 노드 35 → 38).
 * 그 사이에 재면 「노드 35개 중 라벨 32개」처럼, 아직 붙지 않은 라벨이 무명점으로 잡힌다.
 * 같은 실행에서 같은 화면이 0 이었다가 3 이 되는 흔들림의 정체가 이것이었다.
 *
 * 느슨해지는 것이 아니다: 앱이 **정말로** 라벨을 안 붙이면 조건이 끝내 참이 되지 않고,
 * 20초 뒤에 그 상태 그대로 재어 무명점으로 보고한다.
 */
async function waitForReady(cdp, screen) {
  const deadline = Date.now() + 20000;
  let lastNodes = null;
  let stableSince = Date.now();
  while (Date.now() < deadline) {
    try {
      const state = await cdp.evaluate(READY(screen));
      if (state && state.ok) {
        if (state.nodes !== lastNodes) {
          lastNodes = state.nodes;
          stableSince = Date.now();
        } else if (Date.now() - stableSince >= 1000) {
          break;
        }
      } else {
        lastNodes = null;
      }
    } catch {
      // 아직 문서가 갈아끼워지는 중
    }
    await sleep(500);
  }
  /* 마지막 한 박자 — 충돌 회피 패스가 카메라가 멈춘 뒤 한 번 자리를 정한다.
     **줄이지 마라.** 처음에 «있는가»만 보고 800ms 를 기다렸더니 상세 패널의 등장
     애니메이션(opacity 0 → 1, 200ms) 중에 재어 「우측 열을 찾지 못했다」가 났다 —
     조건을 느슨하게 잡고 대기를 줄인 탓이었다. 조건이 참이면 바로 오므로 손해가 없다. */
  await sleep(1500);
}

/**
 * 화면이 «잴 수 있는 상태»가 될 때까지 기다린다.
 *
 * 3D 화면은 `data-cosmos-nodes` 가 붙을 때까지, 그 밖의 화면은 본문이 그려질 때까지.
 * 최대 120초, 500ms 간격. 고정 대기보다 느려지지 않는다 — 준비되면 바로 돌아온다.
 */
async function waitForStage(cdp, screen) {
  /* 120초까지 기다린다. 60초로는 모자란 때가 실제로 있었다 — dev 서버가 3D 번들을
     **처음 컴파일**하는 동안(코드를 고친 직후 첫 실행) 1920px 대시보드가 「미측정」으로
     떨어졌다. 준비되면 바로 돌아오므로 평소 실행은 느려지지 않는다. */
  const deadline = Date.now() + 120000;
  const probe = screen.has3d
    ? `return document.documentElement.dataset.cosmosNodes !== undefined;`
    : `return document.body && document.body.innerText.trim().length > 200;`;
  while (Date.now() < deadline) {
    await sleep(500);
    try {
      if (await cdp.evaluate(probe)) break;
    } catch {
      // 아직 문서가 갈아끼워지는 중
    }
  }
  await waitForReady(cdp, screen);
}

/**
 * 단계 바에서 그 단계를 누른다 (prompt_02 §4-E-3).
 *
 * 단계마다 밝은 노드와 라벨 모양이 달라지므로, 한 번만 재면 1단계만 잰 것이 된다.
 * 버튼을 못 찾으면 조용히 넘어간다 — 그 경우 「1단계 화면을 세 번 잰 것」이 되고,
 * 라벨 수 검사는 여전히 유효하다.
 */
async function clickStep(cdp, label, screen) {
  await cdp.evaluate(`
    const button = [...document.querySelectorAll("button")].find(
      (b) => (b.textContent || "").trim().startsWith(${JSON.stringify(label)}),
    );
    if (button) button.click();
    return !!button;
  `);
  // 카메라 이동·라벨 재배치가 끝날 때까지. 단계를 누르면 노드가 새로 등장하므로
  // 여기서도 「잴 것이 다 붙었는가」를 기다린다.
  await sleep(1500);
  await waitForReady(cdp, screen);
}

// ---------------------------------------------------------------------------
// 쉬운 보기 (24차 · prompt_14 §4-E)
// ---------------------------------------------------------------------------

/** 기존 표는 **전체 보기**를 잰다 — 주소에 mode 를 문자열로 잇지 않고 searchParams 로 붙인다. */
const modeUrl = (path, mode) => {
  const url = new URL(path, BASE);
  url.searchParams.set("mode", mode);
  return url.href;
};
const fullUrl = (path) => modeUrl(path, "full");

/** 프로필이 실행 사이에 남는다 — 저장된 보기 방식을 지우고 시작한다(about:blank 에서는 저장소가 없어 같은 출처로 먼저 간다). */
async function clearStorage(cdp, all = false) {
  await cdp.send("Page.navigate", { url: new URL("/favicon.ico", BASE).href });
  const origin = new URL(BASE).origin;
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && (await cdp.evaluate(`return location.origin;`).catch(() => null)) !== origin) await sleep(200);
  await cdp.evaluate(
    all
      ? `try { Object.keys(localStorage).filter((k) => k.startsWith("bidpilot.")).forEach((k) => localStorage.removeItem(k)); } catch (e) {} return true;`
      : `try { localStorage.removeItem("bidpilot.viewmode.v1"); } catch (e) {} return true;`,
  );
}

/** 쉬운 보기 표 — 창 셋. ≤12 · ≤6 은 1440×900 · 390×844 에만 적용하고 1920×1080 은 적기만 한다(덩어리 6까지 들어온다). */
const SIMPLE_SIZES = [
  { width: 1440, height: 900, enforce: true },
  { width: 1920, height: 1080, enforce: false },
  { width: 390, height: 844, enforce: true },
].map((s) => ({ ...s, key: `${s.width}×${s.height}` }));

/** 공통 머리(BrandMark · 메뉴 5 · 「?」 · 세션)는 세지 않는다. */
const PAGE_HELPERS = `
  const vh = innerHeight;
  const seen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    return el.checkVisibility ? el.checkVisibility({ contentVisibilityAuto: true, opacityProperty: true, visibilityProperty: true }) : true;
  };
  const inView = (el) => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < vh && r.right > 0 && r.left < innerWidth; };
  const COMMON = 'nav[aria-label="화면 이동"], a[aria-label*="대시보드 홈"], button[aria-label^="처음 안내"], [data-tour="topbar-user"], [data-theme-toggle]';
  const common = (el) => !!el.closest(COMMON) || /^(로그아웃|나가는 중)/.test((el.textContent || "").trim());
  const label = (el) => (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.tagName).replace(/\\s+/g, " ").trim().slice(0, 24);
  const countControls = () => {
    let steps = false;
    const out = [];
    for (const el of document.querySelectorAll('button, a[href], select, summary, input:not([type="hidden"])')) {
      if (common(el) || !seen(el) || !inView(el)) continue;
      if (el.closest("[data-simple-row]")) continue;
      if (el.closest("[data-simple-step]")) { steps = true; continue; }
      out.push(label(el));
    }
    if (steps) out.push("[진행 단계 줄]");
    return out;
  };
  const countChips = () => [...document.querySelectorAll("[data-chip]")].filter((el) => !common(el) && seen(el) && inView(el)).map(label);
  const smallText = () => {
    const out = [];
    for (const frame of document.querySelectorAll('[data-view="simple"]')) {
      for (const el of frame.querySelectorAll("*")) {
        if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
        if (!seen(el)) continue;
        const px = parseFloat(getComputedStyle(el).fontSize);
        if (px < 14) out.push({ size: px, text: (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 30) });
      }
    }
    return out;
  };
  const decisionBlocks = () => [...document.querySelectorAll("*")].filter((el) => seen(el) && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim() === "참여 · 보류 · 참여 안 함")).length;
  const click = (el) => { if (el) el.click(); return !!el; };
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
`;

const PROBE_SIMPLE = `
  ${PAGE_HELPERS}
  const overlaps = [];
  const pairs = (els, where) => {
    const boxes = els.filter(seen).map((el) => ({ el, r: el.getBoundingClientRect() }));
    for (let i = 0; i < boxes.length; i += 1) for (let j = i + 1; j < boxes.length; j += 1) {
      // 한 칸이 다른 칸을 품고 있으면 겹침이 아니다(칸 안의 이름표 글자).
      if (boxes[i].el.contains(boxes[j].el) || boxes[j].el.contains(boxes[i].el)) continue;
      const a = boxes[i].r, b = boxes[j].r;
      const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (x > 2 && y > 2) overlaps.push(where + ": " + label(boxes[i].el) + " ↔ " + label(boxes[j].el));
    }
  };
  for (const frame of document.querySelectorAll('[data-view="simple"]')) pairs([...frame.children], "덩어리");
  for (const row of [...document.querySelectorAll("[data-simple-row] > button")].slice(0, 12)) {
    pairs([...row.querySelectorAll("span")].filter((s) => [...s.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())), "행");
  }
  const verdict = document.querySelector("[data-simple-verdict]");
  return {
    url: location.pathname + location.search,
    toggle: document.querySelector("[data-view-toggle]")?.getAttribute("data-view-toggle") ?? null,
    frames: document.querySelectorAll('[data-view="simple"]').length,
    scrollY: Math.round(window.scrollY),
    controls: countControls(),
    chips: countChips(),
    small: smallText(),
    overlaps,
    verdict: verdict ? verdict.getAttribute("data-simple-verdict") : null,
    verdictSeen: !!verdict && seen(verdict) && inView(verdict),
    rows: [...document.querySelectorAll("[data-simple-row]")].filter((r) => { const b = r.getBoundingClientRect(); return b.height > 0 && b.top >= 0 && b.bottom <= vh; }).length,
    // 2.3.0 — 사업기회 목록은 열 때 카드(「더 보기 ⋯ › 목록 모양」에서 한 줄 목록). 한 화면 행 수 기준이 모양마다 다르다.
    layout: document.querySelector("[data-simple-rows]")?.getAttribute("data-layout") ?? "list",
  };
`;

/** 한 화면(1440×900)에 온전히 들어와야 하는 수 — 한 줄 목록 10행(24차) · 카드 2장(2.3.0 · 카드 한 장 ≈ 210px). */
const MIN_ROWS = { list: 10, card: 2 };
const minRows = (row) => MIN_ROWS[row.layout] ?? MIN_ROWS.list;

/** 펼친 재사용 패널도 14px 바닥을 지키는가 — 한 번 펼쳐서 따로 잰다(1440×900). 결정 블록 수도 여기서. */
const EXPAND_SIMPLE = (kind) => `
  ${PAGE_HELPERS}
  const result = { small: [], steps: [] };
  const note = (name) => { for (const s of smallText()) result.small.push({ ...s, where: name }); };
  if (${JSON.stringify(kind)} === "dashboard") {
    click(document.querySelector("[data-simple-verdict] button[aria-expanded]"));
    await pause(600);
    note("판정 카드 체크리스트");
    for (const n of [3, 8, 4, 7, 6]) {
      click(document.querySelector('[data-simple-step="' + n + '"]'));
      await pause(1200);
      result.steps.push({ step: n, decision: decisionBlocks(), checklist: document.querySelectorAll("#eligibility-checklist").length, review: document.querySelectorAll('[data-tour="panel-human-review"]').length });
      note(n + "단계 펼침");
    }
  } else if (${JSON.stringify(kind)} === "support") {
    click(document.querySelector("#support-simple-verdict button[aria-expanded]"));
    await pause(600);
    note("신청 요건");
    for (const n of [2, 3, 4, 5, 6, 7]) {
      click(document.querySelector('[data-simple-step="' + n + '"]'));
      await pause(1000);
      result.steps.push({ step: n, eligibilityIds: document.querySelectorAll("#support-eligibility").length });
      note(n + "단계 펼침");
    }
  } else {
    click(document.querySelector("[data-simple-row] > button"));
    await pause(700);
    // 「왜 이 순위인가」 더 보기 — 2.4.0 공고문 질문 칸(details[data-notice-qa])은 펼치지 않는다(펼치면 원문 상태를 묻는다)
    const more = document.querySelector("[data-simple-row] details:not([data-notice-qa]) > summary");
    click(more);
    await pause(400);
    note("행 펼침");
  }
  return result;
`;

/** 그날 목록에서 마감 전 · 확인 필요 · 입찰 한 건을 고른다 — 앱 화면(쉬운 보기 목록)이 보여 주는 그대로. */
async function pickRealNotice(cdp) {
  const fixed = argOf("--real-notice", null);
  if (fixed) return fixed;
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: modeUrl("/opportunities?src=g2b", "simple") });
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    const ready = await cdp.evaluate(`
      const rows = [...document.querySelectorAll("[data-simple-row]")];
      return rows.length > 0 && !rows.some((r) => /계산 중/.test(r.innerText));
    `).catch(() => false);
    if (ready) break;
    await sleep(700);
  }
  return cdp.evaluate(`
    for (const row of document.querySelectorAll("[data-simple-row]")) {
      const t = row.innerText;
      if (!/입찰/.test(t) || !/확인 필요/.test(t) || !/D-\\d+/.test(t)) continue;
      row.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 500));
      const link = row.querySelector('a[href^="/analysis?notice="]');
      if (link) return new URL(link.href).searchParams.get("notice");
    }
    return null;
  `).catch(() => null);
}

async function waitForSimple(cdp, kind) {
  const probe = {
    dashboard: `return !!document.querySelector("[data-simple-verdict]") && !!document.querySelector("[data-simple-step]");`,
    list: `const rows = [...document.querySelectorAll("[data-simple-row]")]; return rows.length >= 10 && !rows.some((r) => /계산 중/.test(r.innerText));`,
    support: `return !!document.querySelector("#support-simple-verdict") && !!document.querySelector("[data-simple-step]");`,
  }[kind];
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(probe).catch(() => false)) break;
    await sleep(500);
  }
  await sleep(1500);
}

async function runSimplePasses(cdp) {
  const realNotice = await pickRealNotice(cdp);
  const screens = [
    { key: "대시보드 합성", kind: "dashboard", path: "/analysis?notice=synthetic-rfp-0001&welcome=0" },
    ...(realNotice ? [{ key: `대시보드 실공고`, kind: "dashboard", path: `/analysis?notice=${realNotice}&welcome=0`, id: realNotice }] : []),
    { key: "사업기회 목록", kind: "list", path: "/opportunities" },
    { key: "지원사업 /support", kind: "support", path: `/support/${SUPPORT_ID}` },
    { key: "지원사업 /?support", kind: "support", path: `/analysis?support=${SUPPORT_ID}&welcome=0` },
  ];
  const simpleRows = [];
  const expandRows = [];
  for (const size of SIMPLE_SIZES) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false });
    for (const screen of screens) {
      await cdp.send("Page.navigate", { url: modeUrl(screen.path, "simple") });
      await waitForSimple(cdp, screen.kind);
      let result;
      try {
        result = await cdp.evaluate(PROBE_SIMPLE);
        // 밝은 화면은 쉬운 보기(기본 보기)의 대비도 잰다 — 전체 보기와 같은 PROBE · 같은 기준(2.4.0 ⑥).
        if (THEME === "light") result.contrast = (await cdp.evaluate(PROBE)).lowContrast;
      } catch (error) {
        result = { error: String(error.message || error) };
      }
      simpleRows.push({ screen: screen.key, kind: screen.kind, size: size.key, enforce: size.enforce, id: screen.id ?? null, ...result });
      if (size.key === "1440×900") {
        let expanded;
        try {
          expanded = await cdp.evaluate(EXPAND_SIMPLE(screen.kind));
        } catch (error) {
          expanded = { error: String(error.message || error), small: [], steps: [] };
        }
        expandRows.push({ screen: screen.key, kind: screen.kind, ...expanded });
      }
    }
  }
  return { realNotice, simpleRows, expandRows };
}

/** 목록 「더 보기 ⋯」 메뉴를 **열고** 상자와 안의 컨트롤(기간 · 정렬 · 필터 · 내보내기 · 재수집 둘)이 창 안인지 (26차 ISSUE-151). */
async function runMoreMenuPass(cdp) {
  const rows = [];
  // 560 「검토 중」 — 검색칸이 없어 「더 보기」가 탭 옆 같은 줄에 서던 폭(26차 검수 FE-2).
  for (const size of [{ width: 390, height: 844 }, { width: 560, height: 900, tab: "review" }, { width: 1440, height: 900 }]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: modeUrl("/opportunities", "simple") });
    await waitForSimple(cdp, "list");
    const result = await cdp.evaluate(`
      ${size.tab ? `document.querySelector('[data-simple-tab="${size.tab}"]')?.click(); await new Promise((r) => setTimeout(r, 800));` : ""}
      const menu = document.querySelector("details[data-more-menu]");
      if (!menu) return { error: "더 보기 메뉴 없음" };
      menu.open = true;
      await new Promise((r) => setTimeout(r, 400));
      const box = menu.querySelector(":scope > div");
      const r = box.getBoundingClientRect();
      const controls = [...box.querySelectorAll("select, button, input, a[href], summary")].filter((el) => {
        const b = el.getBoundingClientRect();
        return b.width > 0 && b.height > 0;
      });
      const label = (el) => (el.getAttribute("aria-label") || el.innerText || el.tagName).replace(/\\s+/g, " ").trim().slice(0, 20);
      const outside = controls.filter((el) => { const b = el.getBoundingClientRect(); return b.left < 0 || b.right > innerWidth + 0.5; }).map(label);
      const out = { left: Math.round(r.left), right: Math.round(r.right), width: innerWidth, controls: controls.map(label), outside };
      menu.open = false;
      return out;
    `).catch((error) => ({ error: String(error.message || error) }));
    const ok = !result.error && result.left >= 0 && result.right <= result.width && result.outside.length === 0 && result.controls.length > 0;
    rows.push({ size: `${size.width}×${size.height}${size.tab ? ` ${size.tab}` : ""}`, ...result, ok });
  }
  return rows;
}

/** 레이더 좁은 폭 — 머리 「자료 상태」 단추가 창 안 · 가로 스크롤 없음(40차 FRONT-01 · 받은 때 긴 글이 줄바꿈 없이 창 밖으로 넘쳤다). */
async function runRadarNarrowPass(cdp) {
  const rows = [];
  for (const size of [{ width: 375, height: 812 }, { width: 390, height: 844 }]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: `${BASE}/radar` });
    let result = { error: "자료 상태 단추 없음" };
    for (let n = 0; n < 40; n += 1) {
      await sleep(500);
      result = await cdp.evaluate(`
        const button = [...document.querySelectorAll('button[aria-haspopup="dialog"]')].find((b) => (b.getAttribute("aria-label") || "").startsWith("자료 상태"));
        if (!button) return { error: "자료 상태 단추 없음" };
        const r = button.getBoundingClientRect();
        return { left: Math.round(r.left), right: Math.round(r.right), width: innerWidth, scroll: document.documentElement.scrollWidth,
                 text: button.innerText.replace(/\\s+/g, " ").trim().slice(0, 60) };
      `).catch((error) => ({ error: String(error.message || error) }));
      // 「불러오는 중」 글은 짧다 — 받은 때 글이 들어온 뒤의 폭을 잰다(40차 검토)
      if (!result.error && !result.text.includes("불러오는 중")) break;
    }
    const loaded = !result.error && !result.text.includes("불러오는 중");
    const ok = loaded && result.left >= 0 && result.right <= result.width + 0.5 && result.scroll <= result.width + 1;
    rows.push({ size: `${size.width}×${size.height}`, ...result, ok });
  }
  return rows;
}

/** 「삭제 없음」 — 전체 보기(?mode=full)에 예전 것이 다 있는가 · 쉬운 보기 CSS 가 전체 보기 상세 패널로 새지 않았는가. */
async function runKeepPass(cdp) {
  const checks = [];
  const put = (name, ok, detail) => checks.push({ name, ok: !!ok, detail: String(detail ?? "") });
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  // 대시보드 기본은 단계 목록이다(28차 §3-F) — 지도 · 발표 단추가 그대로 있는지 보려면 3D 를 명시로 연다.
  await cdp.send("Page.navigate", { url: fullUrl(FIRST_URL_3D) });
  await waitForStage(cdp, SCREENS[0]);
  const dash = await cdp.evaluate(`
    ${PAGE_HELPERS}
    const menu = [...document.querySelectorAll('button[aria-haspopup="menu"]')].find((b) => /안내/.test(b.textContent || ""));
    click(menu);
    await pause(400);
    const presentation = !!document.querySelector('[data-tour="topbar-presentation"]');
    click(menu);
    /* 바깥 틀 CSS 가 새지 않았는가 — 상세 패널 안 text-[Npx] 글자가 그 크기 그대로인가 */
    const leaks = [];
    for (const el of document.querySelectorAll('[data-tour="panel"] *')) {
      const m = /(?:^|\\s)text-\\[(\\d+(?:\\.\\d+)?)px\\]/.exec(el.getAttribute("class") || "");
      if (!m) continue;
      const px = parseFloat(getComputedStyle(el).fontSize);
      if (Math.abs(px - Number(m[1])) > 0.01) leaks.push(m[1] + "→" + px + " 「" + label(el) + "」");
    }
    click(document.querySelector('[data-tour="rail-step-3"]'));
    await pause(2500);
    return {
      kpi: document.querySelectorAll('[data-tour="mission-strip"] > div:first-child > button').length,
      rail: document.querySelectorAll('[data-tour^="rail-step-"]').length,
      stage: !!document.querySelector('section[data-tour="stage"]'),
      toolbar: !!document.querySelector('[data-visibility-strip="map-toolbar"]'),
      analyze: (document.querySelector('[data-tour="topbar-analyze"]')?.innerText || "").trim(),
      presentation,
      leaks,
      clauseRows: document.querySelectorAll("[data-clause-row]").length,
      simpleFrames: document.querySelectorAll('[data-view="simple"]').length,
    };
  `).catch((error) => ({ error: String(error.message || error) }));
  put("대시보드 KPI 타일 5", dash.kpi === 5, dash.kpi);
  put("레일 단계 8", dash.rail === 8, dash.rail);
  put("지도 무대 section[data-tour=stage]", dash.stage, dash.stage);
  put("지도 도구막대", dash.toolbar, dash.toolbar);
  put("TopBar 「공고 다시 분석」", /공고 (다시 분석|분석 시작)|분석 중/.test(dash.analyze ?? ""), dash.analyze);
  put("「안내 ▾」 → 발표 모드 항목", dash.presentation, dash.presentation);
  put("3단계 조항 행 [data-clause-row]", dash.clauseRows > 0, dash.clauseRows);
  put("전체 보기에 쉬운 틀 없음", dash.simpleFrames === 0, dash.simpleFrames);
  put("전체 보기 상세 패널 글자 크기 그대로", Array.isArray(dash.leaks) && dash.leaks.length === 0, (dash.leaks ?? [dash.error]).slice(0, 3).join(" / "));

  await cdp.send("Page.navigate", { url: fullUrl("/opportunities") });
  await waitForStage(cdp, { has3d: false });
  const list = await cdp.evaluate(`
    const until = Date.now() + 60000;
    while (Date.now() < until && document.querySelectorAll('[data-visibility-strip="card-head"]').length === 0) await new Promise((r) => setTimeout(r, 400));
    return {
      recollect: document.querySelectorAll("[data-recollect]").length,
      review: !!document.querySelector('[role="tab"][aria-label="검토 중"]'),
      cards: document.querySelectorAll('[data-visibility-strip="card-head"]').length,
    };
  `).catch((error) => ({ error: String(error.message || error) }));
  put("목록 재수집 단추 2", list.recollect === 2, list.recollect);
  put("목록 「검토 중」 탭", list.review, list.review);
  put("목록 카드", list.cards > 0, list.cards);

  await cdp.send("Page.navigate", { url: fullUrl(`/support/${SUPPORT_ID}`) });
  await waitForStage(cdp, { has3d: false });
  const support = await cdp.evaluate(`
    const until = Date.now() + 60000;
    while (Date.now() < until && !document.querySelector("#support-eligibility")) await new Promise((r) => setTimeout(r, 400));
    const step = [...document.querySelectorAll("button")].find((b) => /제출서류/.test(b.textContent || "") && !b.closest('[data-view="simple"]'));
    if (step) step.click();
    await new Promise((r) => setTimeout(r, 1200));
    return { attachments: document.querySelectorAll("[data-attachment-links] a[href]").length };
  `).catch((error) => ({ error: String(error.message || error) }));
  put("첨부 내려받기 링크", support.attachments > 0, support.attachments);
  return checks;
}

/**
 * 첫 방문 — 저장소를 비우고 `/analysis`(2.1.0 부터 `/` 는 통계 대시보드 — 그때 이 한 곳을 옮기지 않아 11-06 까지 늘 실패였다).
 *
 * 2.0.5: 첫 진입이면 어느 공고든 환영 창(`[data-welcome-dialog]`)이 뜬다 — 「시작하기」 · Esc 로 닫히고 보던 화면은 그대로.
 * 36차(담당자 결정 10-13): 고른 공고가 없으면 **실제 1위 공고**가 뜬다 — 쉬운 보기 · 맨 위 「오늘 · 이번 주 할 일」 줄 ·
 * 주소에 notice · mode 가 없다(고르지 않았으면 주소가 깨끗하다). 실제 공고가 하나도 없으면 가상 예시(맨 위 줄은 보지 않음).
 */
async function runFirstVisitPass(cdp) {
  const out = [];
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  // 37차 §3-C-4 — 첫 공고는 회사 방식(샘플에듀 = 실무 우선순위)의 나라장터 1위여야 한다. 조회 기간은 화면 기본(30일)과 같다.
  const expected = await companyFirstNotice();
  for (const how of ["시작하기", "Esc"]) {
    await clearStorage(cdp, true);
    await cdp.send("Page.navigate", { url: new URL("/analysis", BASE).href });
    const deadline = Date.now() + 90000;
    let dialog = false;
    while (Date.now() < deadline && !dialog) {
      dialog = await cdp.evaluate(`return !!document.querySelector("[data-welcome-dialog]");`).catch(() => false);
      if (!dialog) await sleep(500);
    }
    await sleep(800);
    if (how === "시작하기") {
      await cdp.evaluate(`const b = document.querySelector("[data-welcome-dialog] button"); if (b) b.click(); return !!b;`);
    } else {
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    }
    const read = `
      return {
        toggle: document.querySelector("[data-view-toggle]")?.getAttribute("data-view-toggle") ?? null,
        search: location.search,
        notice: document.querySelector('[data-tour="topbar-notice"] select')?.value ?? null,
        stored: (() => { try { return localStorage.getItem("bidpilot.notice.v1"); } catch (e) { return "?"; } })(),
        dayStrip: !!document.querySelector("[data-simple-day-strip] [data-day-strip-toggle]"),
        simpleCard: !!document.querySelector("[data-simple-verdict]"),
        dialogOpen: !!document.querySelector("[data-welcome-dialog]"),
      };
    `;
    let state = null;
    const until = Date.now() + 90000;
    while (Date.now() < until) {
      state = await cdp.evaluate(read).catch(() => null);
      if (state && state.simpleCard && state.notice) break;
      await sleep(500);
    }
    await sleep(1500);
    state = await cdp.evaluate(read).catch((error) => ({ error: String(error.message || error) }));
    const real = !!state.notice && !state.notice.startsWith("synthetic-");
    out.push({
      how,
      dialog,
      ...state,
      expected: expected.id,
      method: expected.method,
      ok: dialog && !state.dialogOpen && state.toggle === "simple" && (state.search ?? "") === "" && !state.stored && state.simpleCard
        && (real ? state.dayStrip && (expected.id === null || state.notice === expected.id) : expected.id === null),
    });
  }
  return out;
}

/** 주소 유지 — /opportunities?mode=full 에서 검색어를 바꾼 뒤에도 전체 보기이고 주소에 mode=full 이 남는다. */
async function runUrlKeepPass(cdp) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: fullUrl("/opportunities") });
  await waitForStage(cdp, { has3d: false });
  const state = await cdp.evaluate(`
    const until = Date.now() + 60000;
    let input = null;
    while (Date.now() < until && !(input = document.querySelector("#opp-search"))) await new Promise((r) => setTimeout(r, 400));
    if (!input) return { error: "검색창 없음" };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, "AI");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 1500));
    const params = new URLSearchParams(location.search);
    return { search: location.search, mode: params.get("mode"), q: params.get("q"), toggle: document.querySelector("[data-view-toggle]")?.getAttribute("data-view-toggle") ?? null };
  `).catch((error) => ({ error: String(error.message || error) }));
  return { ...state, ok: state.mode === "full" && state.q === "AI" && state.toggle === "full" };
}

/**
 * 대시보드 쉬운 보기 고정 (37차 §3-F · 담당자 결정 2026-10-14) — 셋을 본다.
 *  ① 옛 저장값(「full」)이 남아 있어도 `/` 는 쉬운 보기로 열리고 옛 값은 지워진다
 *  ② 전체 보기로 바꾼 뒤 새로 열면(같은 주소로 다시 들어가기) 다시 쉬운 보기 — 고른 보기를 기억하지 않는다
 *  ③ 시연 링크 `?mode=full` 은 그대로 전체 보기
 */
async function runDashboardFixedPass(cdp) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  const toggleOf = async () => {
    const until = Date.now() + 60000;
    let mode = null;
    while (Date.now() < until && !(mode = await cdp.evaluate(`return document.querySelector("[data-view-toggle]")?.getAttribute("data-view-toggle") ?? null;`).catch(() => null))) await sleep(400);
    return mode;
  };
  const out = [];
  await clearStorage(cdp, true);
  await cdp.evaluate(`try { localStorage.setItem("bidpilot.viewmode.v1", "full"); } catch (e) {} return true;`);
  await cdp.send("Page.navigate", { url: new URL("/analysis?welcome=0&guided=0", BASE).href });
  const first = await toggleOf();
  // 서버가 그린 HTML 의 토글이 먼저 보인다 — 화면이 붙은(hydration) 뒤에야 옛 값을 지운다. 지워질 때까지 잠깐 기다린다.
  let leftover = "?";
  for (let attempt = 0; attempt < 20; attempt += 1) {
    leftover = await cdp.evaluate(`try { return localStorage.getItem("bidpilot.viewmode.v1"); } catch (e) { return "?"; }`).catch(() => "?");
    if (leftover === null) break;
    await sleep(500);
  }
  out.push({ name: "옛 저장값 「full」이 있어도 쉬운 보기", ok: first === "simple" && leftover === null, detail: `토글 ${first} · 저장값 ${leftover ?? "없음"}` });
  // 화면이 다 붙은(hydration) 뒤에 누른다 — 그 전에 누르면 단추에 처리기가 아직 없어 아무 일도 없다. 바뀔 때까지 다시 누른다.
  await sleep(2500);
  let switched = null;
  for (let attempt = 0; attempt < 8 && switched !== "full"; attempt += 1) {
    await cdp.evaluate(`document.querySelector('[data-view-mode="full"]')?.click(); return true;`);
    await sleep(1000);
    switched = await toggleOf();
  }
  await cdp.send("Page.navigate", { url: new URL("/analysis?welcome=0&guided=0", BASE).href });
  await sleep(1500);
  const reopened = await toggleOf();
  const stored = await cdp.evaluate(`try { return localStorage.getItem("bidpilot.viewmode.v1"); } catch (e) { return "?"; }`).catch(() => "?");
  out.push({ name: "전체 보기로 바꾼 뒤 새로 열면 다시 쉬운 보기", ok: switched === "full" && reopened === "simple" && stored === null, detail: `바꾼 뒤 ${switched} · 새로 연 뒤 ${reopened} · 저장값 ${stored ?? "없음"}` });
  await cdp.send("Page.navigate", { url: new URL("/analysis?mode=full&welcome=0&guided=0", BASE).href });
  await sleep(1500);
  const demo = await toggleOf();
  out.push({ name: "시연 링크 ?mode=full 은 전체 보기", ok: demo === "full", detail: `토글 ${demo}` });
  return out;
}

/** 요구사항 정리표 탭 · /company — 단추·칩 수만 적는다(합격 기준 없음 · 28차 §3-C 에서 /rfp → 사업기회 탭). */
async function runFullOnlyCounts(cdp) {
  const out = [];
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  for (const path of ["/opportunities?tab=sheet&notice=synthetic-rfp-0001&mode=full", "/company"]) {
    await cdp.send("Page.navigate", { url: fullUrl(path) });
    await waitForStage(cdp, { has3d: false });
    await sleep(2500);
    const state = await cdp.evaluate(`
      ${PAGE_HELPERS}
      return { controls: countControls().length, chips: countChips().length };
    `).catch((error) => ({ error: String(error.message || error) }));
    out.push({ path, ...state });
  }
  return out;
}

const simpleTotal = (row) =>
  (row.error ? 1 : 0) +
  (row.enforce && (row.controls?.length ?? 0) > 12 ? 1 : 0) +
  (row.enforce && (row.chips?.length ?? 0) > 6 ? 1 : 0) +
  (row.kind !== "list" && !row.verdictSeen ? 1 : 0) +
  (row.small?.length ?? 0) +
  (row.overlaps?.length ?? 0) +
  (row.contrast?.length ?? 0) +
  (row.scrollY ? 1 : 0) +
  (row.toggle === "simple" ? 0 : 1) +
  (row.kind === "list" && row.size === "1440×900" && (row.rows ?? 0) < minRows(row) ? 1 : 0);

const expandTotal = (row) =>
  (row.error ? 1 : 0) +
  (row.small?.length ?? 0) +
  (row.steps ?? []).reduce(
    (n, s) =>
      n +
      (s.decision !== undefined && s.decision !== 1 ? 1 : 0) +
      (s.checklist !== undefined && s.checklist > 1 ? 1 : 0) +
      (s.review !== undefined && s.review !== 1 ? 1 : 0) +
      (s.eligibilityIds !== undefined && s.eligibilityIds > 1 ? 1 : 0),
    0,
  );

function printSimple({ realNotice, simpleRows, expandRows, keepChecks, firstVisit, urlKeep, fullOnly, moreMenu = [], dashboardFixed = [], radarNarrow = [] }) {
  console.log(`  쉬운 보기 (24차) — 스크롤 0 · 펼치기 전 · 본문만(공통 머리 제외) · 진행 단계 줄 = 1 · 목록 행은 따로`);
  console.log(`    그날 실공고(마감 전 · 확인 필요): ${realNotice ?? "찾지 못함"}`);
  if (THEME === "light") console.log("    밝은 화면 — 대비도 잽니다(합에 더함 · 아래 [대비])");
  console.log("    화면                 창          컨트롤  칩   판정카드  14px미만  겹침  행   합");
  for (const row of simpleRows) {
    if (row.error) {
      console.log(`    ${row.screen.padEnd(20)}${row.size.padEnd(12)}읽지 못함 — ${row.error.slice(0, 60)}`);
      continue;
    }
    console.log(
      `    ${row.screen.padEnd(20)}${row.size.padEnd(12)}` +
      `${String(row.controls.length).padEnd(8)}${String(row.chips.length).padEnd(5)}` +
      `${(row.kind === "list" ? "—" : row.verdictSeen ? "보임" : "안 보임").padEnd(10)}` +
      `${String(row.small.length).padEnd(10)}${String(row.overlaps.length).padEnd(6)}` +
      `${(row.kind === "list" ? String(row.rows) : "—").padEnd(5)}${simpleTotal(row)}${row.enforce ? "" : " (적기만)"}`,
    );
  }
  for (const row of simpleRows) {
    if (row.error || !simpleTotal(row)) continue;
    console.log(`    == ${row.screen} · ${row.size}`);
    if (row.enforce && row.controls.length > 12) console.log(`       [컨트롤 ${row.controls.length}] ${row.controls.join(" · ")}`);
    if (row.enforce && row.chips.length > 6) console.log(`       [칩 ${row.chips.length}] ${row.chips.join(" · ")}`);
    for (const s of row.small.slice(0, 6)) console.log(`       [14px 미만] ${s.size}px 「${s.text}」`);
    for (const o of row.overlaps.slice(0, 6)) console.log(`       [겹침] ${o}`);
    for (const c of (row.contrast ?? []).slice(0, 6)) {
      console.log(`       [대비] ${c.ratio}:1 (${c.need}:1 필요) ${c.size}px  ${c.color} on ${c.background}  「${c.text}」`);
    }
    if (row.scrollY) console.log(`       [스크롤] ${row.scrollY}px 에서 열렸습니다`);
    if (row.toggle !== "simple") console.log(`       [보기] 토글이 ${row.toggle} 입니다`);
    if (row.kind !== "list" && !row.verdictSeen) console.log("       [판정 카드] 첫 화면에 보이지 않습니다");
    if (row.kind === "list" && row.size === "1440×900" && row.rows < minRows(row)) {
      console.log(`       [행] 한 화면 ${row.rows}${row.layout === "card" ? "장(카드)" : "행"} — ${minRows(row)} 이상이어야 합니다`);
    }
  }
  const counts = simpleRows.filter((r) => !r.error).map((r) => `${r.screen} ${r.size} 컨트롤 ${r.controls.length}·칩 ${r.chips.length}`);
  console.log(`    수: ${counts.join(" / ")}`);
  console.log("");
  console.log("  쉬운 보기 펼친 뒤 (1440×900) — 14px 미만 · 결정 블록 1 · 체크리스트 id 1");
  for (const row of expandRows) {
    const steps = (row.steps ?? [])
      .map((s) => `${s.step}단계${s.decision !== undefined ? ` 결정 ${s.decision}·체크리스트 ${s.checklist}·최종결정 ${s.review}` : ""}${s.eligibilityIds !== undefined ? ` 요건 id ${s.eligibilityIds}` : ""}`)
      .join(" / ");
    console.log(`    ${row.screen.padEnd(20)}14px미만 ${String(row.small?.length ?? "?").padEnd(4)}${steps}${expandTotal(row) ? " — 위반" : " — 통과"}`);
    for (const s of (row.small ?? []).slice(0, 6)) console.log(`       [14px 미만] ${s.where} ${s.size}px 「${s.text}」`);
    if (row.error) console.log(`       [오류] ${row.error.slice(0, 80)}`);
  }
  console.log("");
  console.log("  삭제 없음 (?mode=full)");
  for (const c of keepChecks) console.log(`    ${c.ok ? "✓" : "✗"} ${c.name} — ${c.detail}`);
  console.log("");
  console.log("  첫 방문 (저장소 비움 · /analysis — 환영 창이 뜨고 「시작하기」 · Esc 로 닫힘 · 첫 공고는 회사 방식 1위)");
  for (const f of firstVisit) {
    const real = ` · 첫 공고 ${f.notice} · 회사 방식(${f.method ?? "?"}) 1위 ${f.expected ?? "못 읽음"} · 저장 ${f.stored ?? "없음"} · 맨 위 줄 ${f.dayStrip ? "있음" : "없음"}`;
    console.log(`    ${f.ok ? "✓" : "✗"} ${f.how} — 환영 창 ${f.dialog ? "있음" : "없음"} · 토글 ${f.toggle} · 주소 「${f.search}」 · 판정 카드 ${f.simpleCard ? "있음" : "없음"}${real}${f.error ? ` · ${f.error}` : ""}`);
  }
  console.log(`  주소 유지 — /opportunities?mode=full 에서 검색 「AI」: ${urlKeep.ok ? "✓" : "✗"} 주소 「${urlKeep.search ?? urlKeep.error}」 · 토글 ${urlKeep.toggle}`);
  console.log("  대시보드 쉬운 보기 고정 (37차 §3-F) — 지난 보기를 기억하지 않음 · 시연 링크 ?mode=full 은 그대로");
  for (const d of dashboardFixed) console.log(`    ${d.ok ? "✓" : "✗"} ${d.name} — ${d.detail}`);
  console.log("  목록 「더 보기 ⋯」 메뉴를 연 뒤 (26차) — 상자 0 ≤ 왼쪽 · 오른쪽 ≤ 창 폭 · 안의 컨트롤 모두 창 안");
  for (const m of moreMenu) {
    if (m.error) {
      console.log(`    ✗ ${m.size} — ${m.error}`);
      continue;
    }
    console.log(`    ${m.ok ? "✓" : "✗"} ${m.size} 상자 ${m.left}~${m.right} / ${m.width} · 컨트롤 ${m.controls.length}(${m.controls.join(" · ")}) · 창 밖 ${m.outside.length}${m.outside.length ? ` — ${m.outside.join(" · ")}` : ""}`);
  }
  console.log("  레이더 좁은 폭 (40차 FRONT-01) — 머리 「자료 상태」 단추가 창 안 · 가로 스크롤 없음");
  for (const r of radarNarrow) {
    console.log(r.error ? `    ✗ ${r.size} — ${r.error}` : `    ${r.ok ? "✓" : "✗"} ${r.size} 단추 ${r.left}~${r.right} / ${r.width} · 문서 폭 ${r.scroll} · 「${r.text}」`);
  }
  console.log(`  쉬운 보기가 없는 화면 (1440×900, 보고용): ${fullOnly.map((f) => `${f.path} 단추 ${f.controls ?? "?"} · 칩 ${f.chips ?? "?"}`).join(" / ")}`);
  console.log("");
}

const newTotal = ({ simpleRows, expandRows, keepChecks, firstVisit, urlKeep, moreMenu = [], dashboardFixed = [], radarNarrow = [] }) =>
  radarNarrow.filter((r) => !r.ok).length +
  dashboardFixed.filter((d) => !d.ok).length +
  simpleRows.reduce((n, r) => n + simpleTotal(r), 0) +
  expandRows.reduce((n, r) => n + expandTotal(r), 0) +
  keepChecks.filter((c) => !c.ok).length +
  firstVisit.filter((f) => !f.ok).length +
  (urlKeep.ok ? 0 : 1) +
  moreMenu.filter((m) => !m.ok).length;

async function main() {
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) {
    console.error("Edge·Chrome 을 찾지 못했습니다 — 시인성을 잴 수 없습니다.");
    return 2;
  }

  const profile = join(process.env.TEMP || ".", `bidpilot-visibility-${PORT}`);
  const browser = spawn(
    exe,
    [
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      `--window-size=${WIDTHS[0]},${HEIGHT}`,
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--hide-scrollbars",
      /* 렌더러를 잠재우지 않게 한다 — `measure_fps.mjs:138` 과 같은 이유이고, 이 검사에는
         빠져 있었다. 헤드리스는 창이 가려졌다고 보면 rAF 와 **CSS 애니메이션**을 멈춘다.
         그러면 상세 패널의 등장 애니메이션(`cosmos-panel-in`, opacity 0 → 1)이 0% 에서
         얼어 「본문이 안 보임(opacity:0)」이 되고, 라벨의 등장도 멈춰 「무명점」이 늘어난다.
         앱이 아니라 잰 환경이 멈춰 있던 것이다 — 실제로 1280·1440·2000·1920 네 크기에서
         「우측 열을 재지 못했다」가 났다. */
      "--disable-renderer-backgrounding",
      "--disable-backgrounding-occluded-windows",
      "--disable-background-timer-throttling",
      "about:blank",
    ],
    { stdio: "ignore", detached: false },
  );

  const rows = [];
  const firstRows = [];
  const narrowRows = [];
  const stationRows = [];
  let simple = null;
  try {
    const cdp = await connect(PORT);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    /* 화면 밝기(2.4.0 ⑥) — 새 문서마다 페이지 스크립트보다 먼저 저장 값을 맞춘다. clearStorage(all) 뒤에도 다음 문서에서 다시 들어가고,
       프로필이 실행 사이에 남으므로 어두운 화면 실행은 지난 밝은 화면 값을 지운다. */
    await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
      source: THEME === "light"
        ? `try { localStorage.setItem("bidpilot.theme.v1", "light"); } catch (e) {}`
        : `try { localStorage.removeItem("bidpilot.theme.v1"); } catch (e) {}`,
    });
    // 저장된 보기 방식을 지우고 시작한다 — 기존 표는 주소의 mode=full 로 전체 보기를 연다.
    await clearStorage(cdp);

    if (!ONLY_NEW) {
    for (const size of SIZES) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false,
      });
      for (const screen of SCREENS.filter((s) => !SCREEN_FILTER || SCREEN_FILTER.some((f) => s.key.includes(f)))) {
        await cdp.send("Page.navigate", { url: fullUrl(screen.path) });
        /* 3D 가 붙을 때까지 기다린다 (ISSUE-117 · prompt_02 §4-E-2).
           예전에는 고정 9초였다. 서버가 바쁘면(수용 스크립트와 동시 실행) 그 안에 못 붙어
           `data-cosmos-nodes` 를 못 읽고 「미측정」 위반이 났다 — 앱이 아니라 검사가
           성급했던 것이다. 붙을 때까지 최대 60초 폴링하고, 그래도 없으면 그때는 위반이다. */
        if (screen.picture) {
          // 지원사업 그림은 사람이 켤 때만 — 본문이 붙은 뒤 「그림으로 보기(3D)」를 누른다(29차 R28-14)
          await waitForStage(cdp, { has3d: false });
          // 단추는 분석 응답 뒤에 그려진다 — 나올 때까지(최대 20초) 기다렸다 누른다(첫 실행에서 두 행이 3D 가 붙기 전에 쟀다)
          await cdp.evaluate(`
            const until = Date.now() + 20000;
            let b = null;
            while (Date.now() < until && !(b = [...document.querySelectorAll("button")].find((x) => (x.textContent || "").includes("그림으로 보기")))) await new Promise((r) => setTimeout(r, 300));
            if (b) b.click();
            return !!b;`);
        }
        await waitForStage(cdp, screen);
        if (screen.step) await clickStep(cdp, screen.step, screen);
        let result;
        try {
          result = await cdp.evaluate(PROBE);
        } catch (error) {
          result = { error: String(error.message || error) };
        }
        rows.push({
          screen: screen.key, size: size.key, has3d: !!screen.has3d, wantPanel: !!screen.panel, ...result,
        });
      }
    }

    // 32차 §3-A-11 — 좁은 화면(390)에서도 재는 화면(실전 가이드). 같은 PROBE · 같은 위반 규칙.
    for (const screen of SCREENS.filter((s) => s.narrow && (!SCREEN_FILTER || SCREEN_FILTER.some((f) => s.key.includes(f))))) {
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
      await cdp.send("Page.navigate", { url: fullUrl(screen.path) });
      await waitForStage(cdp, screen);
      let result;
      try {
        result = await cdp.evaluate(PROBE);
      } catch (error) {
        result = { error: String(error.message || error) };
      }
      rows.push({ screen: screen.key, size: "390×844", has3d: false, wantPanel: false, ...result });
    }

    /* 첫 화면 — 접힌 띠(bidpilot.daystrip.v1)를 지우고 다시 연다. 프로필이 실행 사이에 남으므로 펼친 채 저장돼
       있으면 첫 화면이 아니다. */
    const dashboard = SCREENS[0];
    for (const size of FIRST_SIZES) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false,
      });
      await cdp.send("Page.navigate", { url: fullUrl(FIRST_URL_3D) });
      await waitForStage(cdp, dashboard);
      await cdp.evaluate(`try { localStorage.removeItem("bidpilot.daystrip.v1"); } catch (e) {} return true;`);
      await cdp.send("Page.navigate", { url: fullUrl(FIRST_URL_3D) });
      await waitForStage(cdp, dashboard);
      let result;
      try {
        result = await cdp.evaluate(PROBE_FIRST);
      } catch (error) {
        result = { error: String(error.message || error), problems: ["읽지 못함"] };
      }
      firstRows.push({ size: size.key, ...result });
    }

    /* 정거장마다 — 1440×900 에서 레일 단계 1~8 을 눌러 지금 정거장 라벨을 잰다. 레일 단추는 글자가 글리프로
       시작하므로 글자로 찾지 않고 data-tour 로 찾는다. */
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: fullUrl(FIRST_URL_3D) });
    await waitForStage(cdp, dashboard);
    for (let n = 1; n <= 8; n += 1) {
      const clicked = await cdp.evaluate(`
        const b = document.querySelector('[data-tour="rail-step-${n}"]');
        if (b) b.click();
        return !!b;
      `);
      const deadline = Date.now() + 10000;
      while (Date.now() < deadline) {
        const now = await cdp.evaluate(`return document.documentElement.dataset.cosmosStation ?? null;`).catch(() => null);
        if (now === String(n)) break;
        await sleep(300);
      }
      await sleep(2500);
      await waitForReady(cdp, dashboard);
      let result;
      try {
        result = await cdp.evaluate(PROBE);
      } catch (error) {
        result = { error: String(error.message || error) };
      }
      stationRows.push({ step: n, clicked, ...result });
    }

    /* 좁은 캔버스 — 레일을 펼치거나 접은 뒤 이름 겹침을 잰다. 기본은 목록이라(28차) 지도를 명시로 연다 — 28차 전
       이 폭의 자동 지도(좁은 캔버스 = 2D)와 같은 것을 재도록 2D. 좁은 칸 3D 는 check_map 이 따로 잰다(27차 §3-D). */
    for (const size of NARROW_CASES) {
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: size.width, height: size.height, deviceScaleFactor: 1, mobile: false });
      await cdp.send("Page.navigate", { url: fullUrl(`${FIRST_URL}&view=2d`) });
      let result;
      try {
        const deadline = Date.now() + 60000;
        while (Date.now() < deadline) {
          const n = await cdp.evaluate(`return document.querySelectorAll("[data-cosmos-station-name]").length;`).catch(() => 0);
          if (n >= 8) break;
          await sleep(500);
        }
        await sleep(3500);
        const want = size.rail === "open" ? "워크플로 레일 펼치기" : "워크플로 레일 접기";
        await cdp.evaluate(`const b = document.querySelector('button[aria-label="${want}"]'); if (b) b.click(); return !!b;`);
        await sleep(2500);
        result = await cdp.evaluate(PROBE_NARROW);
      } catch (error) {
        result = { error: String(error.message || error), overlaps: [] };
      }
      narrowRows.push({ size: size.key, ...result });
    }
    }

    /* 쉬운 보기 (24차) — 표 · 펼친 뒤 · 삭제 없음 · 첫 방문 · 주소 유지 · /rfp·/company 수 */
    simple = await runSimplePasses(cdp);
    simple.keepChecks = await runKeepPass(cdp);
    simple.firstVisit = await runFirstVisitPass(cdp);
    simple.urlKeep = await runUrlKeepPass(cdp);
    simple.dashboardFixed = await runDashboardFixedPass(cdp);
    simple.moreMenu = await runMoreMenuPass(cdp);
    simple.radarNarrow = await runRadarNarrowPass(cdp);
    simple.fullOnly = await runFullOnlyCounts(cdp);
  } finally {
    browser.kill();
  }

  /** 우측 상세 열의 위반 수 (접힘·겹침·본문 높이·미측정). */
  const panelTotal = (row) => {
    if (!row.wantPanel) return 0;
    if (!row.panel?.measured) return 1;
    const p = row.panel;
    return (
      p.overlaps.length + p.footerOverlaps.length + p.short + p.collapsed +
      (p.overflowBelow > 2 ? 1 : 0)
    );
  };

  const total = (row) =>
    (row.small?.length ?? 0) + (row.lowContrast?.length ?? 0) +
    (row.literals?.length ?? 0) + (row.overlaps?.length ?? 0) +
    // 라벨 없는 점도 위반이다 — 담당자가 「이 점이 무엇인지」를 못 읽는다.
    (row.unlabeled ?? 0) +
    // 정거장 지도: 13px 미만 라벨 · 지금 정거장에서 긴 라벨이 모자란 점 (21차).
    (row.smallLabels?.length ?? 0) + (row.stationMissing ?? 0) + (row.stationOverlaps ?? 0) + (row.caption3Clipped ?? 0) +
    // 3D 화면인데 노드 수를 못 읽었다 = 검사가 돌지 않았다. 통과로 세면 안 된다.
    (row.has3d && row.nodeCount === null ? 1 : 0) +
    panelTotal(row);

  const firstTotal = (row) => (row.error ? 1 : 0) + (row.problems?.length ?? 0) + (row.scrollY ? 1 : 0);
  const narrowTotal = (row) => (row.error ? 1 : 0) + (row.names === 8 ? 0 : 1) + (row.overlaps?.length ?? 0) + (row.caption3Clipped ?? 0);
  const stationTotal = (row) =>
    (row.error ? 1 : 0) + (row.clicked ? 0 : 1) + (row.station === String(row.step) ? 0 : 1) +
    (row.stationMissing ?? 0) + (row.stationOverlaps ?? 0) + (row.caption3Clipped ?? 0) +
    (row.smallLabels?.length ?? 0) + (row.unlabeled ?? 0);

  if (AS_JSON) {
    console.log(JSON.stringify({
      theme: THEME, rows, firstRows, stationRows, narrowRows, simple,
      violations: rows.reduce((n, r) => n + total(r), 0) +
        firstRows.reduce((n, r) => n + firstTotal(r), 0) + stationRows.reduce((n, r) => n + stationTotal(r), 0) +
        narrowRows.reduce((n, r) => n + narrowTotal(r), 0) + (simple ? newTotal(simple) : 1),
    }, null, 1));
  } else {
    console.log(`시인성 검사 — ${BASE} · ${THEME_LABEL} · 창 ${SIZES.map((s) => s.key).join(" · ")}\n`);
    console.log("  화면                창           12px미만  대비미만  겹침  리터럴  무명점   패널   합");
    for (const row of rows) {
      if (row.error) {
        console.log(`  ${row.screen.padEnd(18)}${row.size.padEnd(13)}읽지 못함 — ${row.error.slice(0, 50)}`);
        continue;
      }
      console.log(
        `  ${row.screen.padEnd(18)}${row.size.padEnd(13)}` +
        `${String(row.small.length).padEnd(10)}${String(row.lowContrast.length).padEnd(10)}` +
        `${String(row.overlaps.length).padEnd(6)}${String(row.literals.length).padEnd(8)}` +
        `${String(row.unlabeled ?? 0).padEnd(9)}${String(panelTotal(row)).padEnd(7)}${total(row)}`,
      );
    }
    console.log("");
    for (const row of rows) {
      if (row.error || !total(row)) continue;
      console.log(`== ${row.screen} · ${row.size}`);
      for (const s of row.small.slice(0, 6)) console.log(`   [작음]   ${s.size}px  「${s.text}」`);
      for (const c of row.lowContrast.slice(0, 8)) {
        console.log(`   [대비]   ${c.ratio}:1 (${c.need}:1 필요) ${c.size}px  ${c.color} on ${c.background}  「${c.text}」`);
      }
      for (const o of row.overlaps.slice(0, 6)) console.log(`   [겹침]   ${o.x}×${o.y}px  「${o.a}」 ↔ 「${o.b}」`);
      for (const l of row.literals.slice(0, 6)) console.log(`   [리터럴] 「${l.text}」  ${String(l.where).slice(0, 40)}`);
      if (row.unlabeled) {
        console.log(`   [무명점] 노드 ${row.nodeCount}개 중 라벨 ${row.labelCount}개 — ${row.unlabeled}개에 글자가 없습니다`);
      }
      // 정거장 지도 위반도 합에 들어간다 — 적지 않으면 「합 1 · 목록 비어 있음」이 된다 (21차 검토).
      for (const s of (row.smallLabels ?? []).slice(0, 6)) console.log(`   [13px 미만] ${s.size}px  「${s.text}」`);
      if (row.stationMissing) {
        console.log(`   [긴 라벨] 정거장 ${row.station} — 점 ${row.stationNodes}개 중 긴 라벨 ${row.stationLong}개`);
      }
      if (row.stationOverlaps) console.log(`   [라벨 겹침] 정거장 ${row.station} — 긴 라벨끼리 ${row.stationOverlaps}쌍`);
      if (row.caption3Clipped) console.log(`   [③ 캡션 잘림] 「${row.caption3Text}」`);
      if (row.has3d && row.nodeCount === null) {
        console.log("   [미측정] 3D 노드 수를 읽지 못했습니다 — 라벨 검사가 돌지 않았습니다 (data-cosmos-nodes 없음)");
      }
      if (row.wantPanel && !row.panel?.measured) {
        console.log(
          "   [미측정] 우측 상세 열을 재지 못했습니다 — " +
          (row.panel?.missing?.length ? row.panel.missing.join(" · ") : "`data-panel-region` 이 없습니다"),
        );
      } else if (row.wantPanel && panelTotal(row)) {
        const p = row.panel;
        console.log(`   [패널]   열 ${p.column}px · ${p.blocks.map((b) => `${b.name} y${b.top}·${b.height}px`).join(" · ")}`);
        if (p.collapsed) console.log("   [패널]   우측 열이 0px 로 접혔습니다 — 블록이 열 밖으로 흘러넘칩니다");
        if (p.short) console.log(`   [패널]   스크롤 본문이 ${p.body}px 입니다 — 160px 이상이어야 읽고 스크롤할 수 있습니다`);
        if (p.overflowBelow > 2) console.log(`   [패널]   패널이 우측 열 바닥을 ${p.overflowBelow}px 넘어 흘렀습니다`);
        for (const o of p.overlaps) console.log(`   [패널]   ${o.x}×${o.y}px 겹침 — ${o.a} ↔ ${o.b}`);
        for (const o of p.footerOverlaps) console.log(`   [패널]   ${o.x}×${o.y}px 겹침 — ${o.name} ↔ 바닥 출처줄`);
      }
      console.log("");
    }
    /* 우측 열 수치는 **위반이 없어도** 적는다 — prompt_04 §3-B-3 이 「캡처 대신 수치로」를
       요구하고, 다음에 이 값이 다시 눌리는지 보려면 통과한 값도 남아 있어야 한다. */
    const panels = rows.filter((r) => r.wantPanel && r.panel?.measured);
    if (panels.length) {
      console.log("  우측 상세 열 — 열 높이 · 세 블록의 y·높이");
      for (const row of panels) {
        const p = row.panel;
        console.log(
          `    ${row.size.padEnd(12)}열 ${String(p.column).padStart(4)}px · ` +
          p.blocks.map((b) => `${b.name} y${b.top}·${b.height}px`).join(" · ") +
          ` · 열 밖 넘침 ${p.overflowBelow}px · 겹침 ${p.overlaps.length + p.footerOverlaps.length}건`,
        );
      }
      console.log("");
    }

    console.log("  첫 화면 (스크롤 0) — 정거장 이름 8개 · 18px 이상 · 창 안 · 지도 안 · 상세 열 머리");
    for (const row of firstRows) {
      console.log(
        `    ${row.size.padEnd(12)}이름 ${row.names ?? 0}개 · 이름 y ${row.nameY ?? "?"} · 지도 ${row.section?.join("~") ?? "?"} · ` +
        `상세 머리 ${row.head?.join("~") ?? "?"} · 스크롤 ${row.scrollY ?? "?"} · ${firstTotal(row) ? `위반 ${row.problems?.join(" / ") || row.error}` : "통과"}`,
      );
    }
    console.log("");
    console.log("  정거장마다 (1440×900, 레일 단계를 누른 뒤) — 지금 정거장 점 · 긴 라벨 · 겹침 · ③캡션잘림 · 13px 미만 · 무명점");
    for (const row of stationRows) {
      console.log(
        `    ${String(row.step).padEnd(3)}지도 정거장 ${String(row.station ?? "?").padEnd(3)}점 ${String(row.stationNodes ?? "?").padEnd(4)}` +
        `긴 라벨 ${String(row.stationLong ?? "?").padEnd(4)}겹침 ${String(row.stationOverlaps ?? "?").padEnd(3)}` +
        `③캡션잘림 ${String(row.caption3Clipped ?? "?").padEnd(3)}` +
        `13px미만 ${String(row.smallLabels?.length ?? "?").padEnd(3)}` +
        `무명점 ${String(row.unlabeled ?? "?").padEnd(3)}${stationTotal(row) ? "위반" : "통과"}`,
      );
      for (const s of (row.smallLabels ?? []).slice(0, 3)) console.log(`         [13px 미만] ${s.size}px 「${s.text}」`);
      if (row.caption3Clipped) console.log(`         [③ 캡션 잘림] 「${row.caption3Text}」`);
    }
    console.log("");
    console.log("  좁은 캔버스 — 레일을 펼치거나 접은 뒤 정거장 이름 겹침 (22차 §4-C)");
    for (const row of narrowRows) {
      console.log(
        `    ${row.size.padEnd(24)}캔버스 ${String(row.canvas ?? "?").padStart(4)}px · ${row.view ?? "?"} · 이름 ${row.names ?? "?"}개 · ` +
        `겹침 ${row.overlaps?.length ?? "?"}쌍 · ③캡션 「${row.caption3 ?? "?"}」${row.caption3Clipped ? " 잘림" : ""}` +
        `${row.warning ? " · 좁은 캔버스 안내" : ""} · ${narrowTotal(row) ? "위반" : "통과"}`,
      );
      for (const o of (row.overlaps ?? []).slice(0, 4)) console.log(`         [이름 겹침] ${o}`);
      if (row.error) console.log(`         [오류] ${row.error.slice(0, 80)}`);
    }
    const cap3 = stationRows.find((r) => r.step === 3);
    if (cap3?.caption3Text) console.log(`    ③ 캡션(지금 정거장일 때): 「${cap3.caption3Text}」 · 잘림 ${cap3.caption3Clipped ?? "?"}`);
    console.log("");

    if (simple) printSimple(simple);
    else console.log("  [미측정] 쉬운 보기 표를 재지 못했습니다\n");

    const strips = rows.reduce((n, r) => n + (r.strips ?? 0), 0);
    if (!ONLY_NEW && !strips) {
      console.log("  [참고] `data-visibility-strip` 이 붙은 요소가 없어 겹침을 재지 못했습니다.");
      console.log("         겹침을 재려면 머리띠·카드 머리 줄에 그 표시를 달아야 합니다 (0925 §4-F-4).");
    }
  }

  const violations =
    rows.reduce((n, r) => n + total(r), 0) +
    firstRows.reduce((n, r) => n + firstTotal(r), 0) +
    stationRows.reduce((n, r) => n + stationTotal(r), 0) +
    narrowRows.reduce((n, r) => n + narrowTotal(r), 0) +
    (simple ? newTotal(simple) : 1);
  const failed = rows.some((r) => r.error) || violations > 0;
  if (!AS_JSON) {
    console.log(failed ? `시인성 위반 ${violations}건 — 위 목록을 보세요.` : "시인성 위반 없음.");
  }
  return failed ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error);
    process.exit(2);
  },
);
