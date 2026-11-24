/**
 * 시연 리허설 캡처 — 큐시트대로 눌러 가며 화면을 찍는다.
 *
 * ## 왜 이렇게 만들었나
 *
 * 「확인했다」는 말은 캡처가 없으면 확인이 아니다. 그런데 이 저장소에는 브라우저 자동화
 * 의존성이 없고(playwright·puppeteer 미설치), 그것 하나 때문에 300MB 를 새로 받는 것은
 * 밤에 혼자 도는 작업에서 치를 값이 아니다.
 *
 * 그래서 이미 깔려 있는 Edge(또는 Chrome)를 원격 디버깅으로 띄우고 **Node 22 에 내장된
 * WebSocket** 으로 CDP 를 직접 말한다. 새 의존성이 0 이다.
 *
 * ## 쓰는 법
 *
 *   node scripts/capture_rehearsal.mjs
 *   node scripts/capture_rehearsal.mjs --out docs/screenshots/rehearsal-2026-09-17 --base http://localhost:3110
 *
 * 각 장면은 「무엇을 누르고 무엇을 기다린다」로 적혀 있다(SCENES). 큐시트를 고치면 여기도 고친다.
 * 결과는 `NN-이름.png` 와 `manifest.json`(장면·소요·화면에서 읽은 숫자)이다.
 */

import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};

const BASE = argOf("--base", "http://localhost:3110");
const OUT = resolve(argOf("--out", "docs/screenshots/rehearsal-2026-09-17"));
const PORT = Number(argOf("--port", "9222"));
const WIDTH = Number(argOf("--width", "1440"));
const HEIGHT = Number(argOf("--height", "900"));

const BROWSERS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 24차: 시작할 때 저장된 보기 방식을 지운다 — 기존 장면은 `url` 에 mode 가 없으면 full 을 붙여 전체 보기로 연다. */
async function clearViewMode(cdp) {
  await cdp.send("Page.navigate", { url: new URL("/favicon.ico", BASE).href });
  const origin = new URL(BASE).origin;
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && (await cdp.evaluate(`return location.origin;`).catch(() => null)) !== origin) await sleep(200);
  await cdp.evaluate(`try { localStorage.removeItem("bidpilot.viewmode.v1"); } catch (e) {} return true;`);
}

// ---------------------------------------------------------------------------
// CDP — 의존성 없이 필요한 것만
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
      if (message.error) waiter.reject(new Error(`${message.error.message} (${JSON.stringify(waiter.params).slice(0, 120)})`));
      else waiter.resolve(message.result);
    });
  }

  send(method, params = {}) {
    const id = ++this.id;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject, params }));
  }

  /** 페이지 안에서 식을 평가한다. 약속(Promise)이면 풀릴 때까지 기다린다. */
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
  // 브라우저가 뜰 때까지 기다린다.
  for (let attempt = 0; attempt < 40; attempt += 1) {
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

/**
 * 결함 초안 텍스트 — `evaluate_auditor.py --print-draft` 의 출력 그대로.
 *
 * 앱을 import 하므로 바깥 호출 문을 전부 닫고 부른다(기본값도 꺼짐이지만 명시한다).
 */
function defectiveDraft() {
  const root = resolve(".");
  const python = [
    join(root, "backend", ".venv", "Scripts", "python.exe"),
    join(root, "backend", ".venv", "bin", "python"),
  ].find((p) => existsSync(p));
  if (!python) throw new Error("backend/.venv 의 파이썬을 찾지 못했습니다 — 결함 초안을 만들 수 없습니다");
  const out = execFileSync(python, [join(root, "scripts", "evaluate_auditor.py"), "--print-draft"], {
    encoding: "utf-8",
    env: {
      ...process.env,
      PYTHONIOENCODING: "utf-8",
      G2B_LIVE_FETCH: "0",
      BIZINFO_LIVE_FETCH: "0",
      EMBEDDING_LIVE: "0",
      SEMANTIC_FIT: "0",
      LLM_LIVE: "0",
    },
  });
  const draft = out.replace(/\r\n/g, "\n").trim();
  if (!draft) throw new Error("결함 초안이 비어 있습니다");
  return draft;
}

// ---------------------------------------------------------------------------
// 페이지 안에서 쓸 도우미 — 문자열로 넣는다 (CDP 는 함수를 못 보낸다)
// ---------------------------------------------------------------------------

const HELPERS = `
  const $all = (sel) => [...document.querySelectorAll(sel)];
  const byText = (sel, re) => $all(sel).find((el) => re.test((el.textContent || "").trim()));
  /**
   * 기다렸다가 없으면 **null 을 돌려준다** — 장면을 죽이지 않는다.
   *
   * 다만 «기다렸는데 못 봤다»는 사실은 window.__missed 에 남긴다. 예전에는 그것이
   * 아무 데도 안 남아서, 화면 문구가 바뀌어 검사가 60초를 헛기다리고 값을 null 로 적어도
   * 캡처가 [OK] 였다 — 17차에 01번 장면이 실제로 그랬다(「사업기회 수집」이 화면에서
   * 「사업기회 마감 전 …」으로 바뀌어 있었다). 조용히 초록이 되지 않게 한다.
   */
  window.__missed = window.__missed || [];
  const waitFor = async (fn, ms = 45000, label = "") => {
    const started = Date.now();
    while (Date.now() - started < ms) {
      let hit = null;
      try { hit = fn(); } catch { hit = null; }
      if (hit) return hit;
      await new Promise((r) => setTimeout(r, 300));
    }
    window.__missed.push(label || String(fn).slice(0, 90));
    return null;
  };
  /**
   * 환영 창은 «데이터가 다 온 뒤에» 뜬다. 그래서 이동 직후에 찾으면 없고, 몇 초 뒤에 나타나
   * 그 다음 클릭을 전부 가로챈다. 보이면 닫고, 없으면 그냥 지나간다.
   */
  const dismissWelcome = async () => {
    const dlg = document.querySelector("[role=dialog]");
    if (!dlg) return false;
    const go = [...dlg.querySelectorAll("button")].find((b) => /^시작하기$/.test((b.textContent || "").trim()));
    if (go) { go.click(); await new Promise((r) => setTimeout(r, 1200)); return true; }
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await new Promise((r) => setTimeout(r, 800));
    return true;
  };
  /** 대시보드가 «다 그려졌는가». 8단계 레일이 뜨면 분석 결과가 붙은 것이다. */
  const dashboardReady = async () => {
    await waitFor(() => byText("button", /8담당자 최종 결정|8 담당자 최종 결정/));
    await dismissWelcome();
    await waitFor(() => byText("button", /8담당자 최종 결정|8 담당자 최종 결정/));
  };
`;

/** 큐시트의 각 장면. name 은 파일 이름이 된다. */
const SCENES = [
  {
    name: "01-사업기회-목록",
    url: "/opportunities",
    act: `await waitFor(() => /마감 전 [\\d,]+ · 나라장터/.test(document.body.innerText), 60000, "목록 첫 줄");`,
    settle: 3000,
    note: "0:00 실데이터 목록 — 순위와 사유",
    // 첫 줄은 **날마다 줄어드는 수**다(마감이 지나면 빠진다). 큐시트에 고정값으로 두지 않고
    // 「당일 아침 화면값」으로 적는다 — 여기서는 그 날의 값을 그대로 옮겨 적기만 한다.
    read: `const t = document.body.innerText;
           return { 첫줄: (t.match(/마감 전 [^\\n]*/) || [])[0] || null,
                    둘째줄: (t.match(/사업기회 마감 전 [^\\n]*/) || [])[0] || null,
                    A1: (t.match(/검토 우선순위 (\\d+)/) || [])[1] || null };`,
  },
  {
    name: "02-첫화면-환영창",
    url: "/analysis?notice=synthetic-rfp-0001",
    before: `Object.keys(localStorage).filter(k => k.startsWith("bidpilot.")).forEach(k => localStorage.removeItem(k));`,
    settle: 3000,
    act: `await waitFor(() => document.querySelector("[role=dialog]"), 60000);
          // 환영 창 뒤의 지도는 **사람이 할 일이 있는 첫 정거장**에 내려앉는다 — 합성 공고는 ③(확인 전 조항 2) (22차 §4-A).
          await waitFor(() => document.documentElement.dataset.cosmosStation === "3", 30000, "첫 화면 정거장 ③");`,
    note: "첫 방문 — 환영 창 세 갈래 · 뒤의 지도는 ③ 참가자격 (22차)",
    read: `const dlg = document.querySelector("[role=dialog]");
           const rail = [...document.querySelectorAll('[data-tour^="rail-step-"]')].findIndex((b) => b.getAttribute("aria-current")) + 1;
           return { 버튼: dlg ? [...dlg.querySelectorAll("button,a")].map(b => b.textContent.trim().split("\\n")[0]) : null,
                    첫화면정거장: document.documentElement.dataset.cosmosStation ?? null, 레일: rail || null };`,
  },
  {
    name: "03-데모-띠와-지금할일",
    settle: 2000,
    note: "0:25 데모 띠 · 지금 할 일 (접힌 「오늘 · 이번 주」 띠를 펼쳐서 — 21차)",
    act: `await dismissWelcome();
          await dashboardReady();
          // 「지금 할 일」은 21차부터 접힌 띠 안에 있다(첫 화면에 지도가 오게) — 펼쳐서 읽는다.
          const toggle = await waitFor(() => document.querySelector("[data-day-strip-toggle]"), 20000, "오늘 · 이번 주 띠");
          if (toggle && toggle.getAttribute("aria-expanded") === "false") toggle.click();
          await waitFor(() => /지금 할 일/.test(document.body.innerText), 20000, "지금 할 일");
          // 데모 날짜는 로드 시각 기준(마감 D-21 · ISSUE-160) — 첫 화면이 「입찰 종료」면 날짜가 다시 박힌 것이다.
          if (/입찰 마감이 지났습니다/.test(document.body.innerText)) window.__missed.push("데모 공고가 마감으로 열림(ISSUE-160)");`,
    read: `const t = document.body.innerText;
           return { 데모띠: /가상 예시 공고입니다/.test(t), 마감칩: (t.match(/입찰 (마감|종료)[^\\n]{0,12}/) || [])[0] || null,
                    지금할일: (t.match(/지금 할 일[\\s\\S]{0,80}/) || [])[0] || null };`,
  },
  {
    name: "04-공고-선택기",
    settle: 1500,
    // 03 에서 펼친 띠를 다시 접는다 — 이 뒤 장면은 첫 화면(지도가 보이는 화면) 그대로다.
    before: `const toggle = document.querySelector("[data-day-strip-toggle]");
             if (toggle && toggle.getAttribute("aria-expanded") === "true") toggle.click();`,
    act: `await dashboardReady();`,
    note: "선택기 — 시연용(마감) 그룹",
    read: `const sel = document.getElementById("cosmos-notice-picker");
           return { 그룹: sel ? [...sel.querySelectorAll("optgroup")].map(g => g.label) : null };`,
  },
  {
    name: "05-참가-가능-여부",
    settle: 2500,
    note: "0:45 3단계 참가 가능 여부 — 상세 맨 위 띠 · 조항 체크리스트 「확인 n/m」 (20차 §4-D)",
    act: `await dashboardReady();
          const step = await waitFor(() => byText("button", /3참가 가능 여부|3 참가 가능 여부/), 45000, "3단계 레일 단추");
          if (step) step.click();
          await new Promise(r => setTimeout(r, 2000));
          // 띠와 체크리스트 진행은 **못 보면 못 봤다고 센다** — 읽기만 하면 null 이어도 [OK] 로 지나간다.
          await waitFor(() => document.querySelector("[data-eligibility-banner]"), 20000, "참가 가능 여부 띠");
          await waitFor(() => document.querySelector("[data-clause-progress]"), 20000, "조항 체크리스트 「확인 n/m」");`,
    read: `const banner = document.querySelector("[data-eligibility-banner]");
           const progress = document.querySelector("[data-clause-progress]");
           return { 띠: banner ? banner.getAttribute("data-eligibility-banner") + " · " + banner.innerText.replace(/\\s+/g, " ").slice(0, 120) : null,
                    확인: progress ? progress.textContent.trim() : null,
                    // ③ 의 두 수 (22차 §4-B) — 레일 · 정거장 캡션 · KPI 타일이 같은 말.
                    요약: (document.body.innerText.match(/확정 안 한 조항 \\d+ · 기본정보 확인 \\d+|조항 다 확정 · 기본정보 확인 \\d+|조항 \\d+개 다 확정|기본정보 확인 (?:\\d+|끝)/) || [])[0] || null };`,
  },
  {
    name: "06-놓치면-안-되는-조건",
    settle: 2500,
    note: "조건·할 일 — 중복 없음",
    // 3단계에서는 「놓치면 안 되는 조건」이 접이식 단추가 아니라 **머리글로 이미 펼쳐져**
    // 있다(단추는 다른 단계에서만 접힌다). 둘 중 먼저 보이는 것을 기다리고, 접힌 단추일
    // 때만 누른다 — 17차는 단추만 45초 기다리다 못 찾았다(읽은 값은 유효했다).
    act: `await dashboardReady();
          const panel = await waitFor(() =>
            byText("button", /놓치면 안 되는 조건 · 체크리스트 · 결정/) ||
            $all("h2,h3,h4").find((h) => /^놓치면 안 되는 조건/.test((h.textContent || "").trim()) && h.offsetParent !== null),
            45000, "「놓치면 안 되는 조건」 단추 또는 머리글");
          if (panel && panel.tagName === "BUTTON" && panel.getAttribute("aria-expanded") === "false") panel.click();
          await new Promise(r => setTimeout(r, 2000));`,
    read: `const t = document.body.innerText;
           return { 참가차단: (t.match(/참가 차단 \\d+/) || [])[0] || null,
                    해시경고: /해시|다시 찾아야/.test(t) };`,
  },
  {
    name: "07-요구사항-정리표",
    settle: 2500,
    note: "1:05 4단계 요구사항 정리표",
    act: `await dashboardReady();
          const step = await waitFor(() => byText("button", /4요구사항 정리|4 요구사항 정리/));
          if (step) step.click();
          await new Promise(r => setTimeout(r, 2000));`,
    read: `return { 요약: (document.body.innerText.match(/\\d+건 · \\d+p/) || [])[0] || null };`,
  },
  {
    name: "08-회사-수행근거-연결",
    settle: 2500,
    note: "1:25 5단계 회사 수행근거 연결",
    act: `await dashboardReady();
          const step = await waitFor(() => byText("button", /5회사 수행근거 연결|5 회사 수행근거 연결/));
          if (step) step.click();
          await new Promise(r => setTimeout(r, 2000));`,
    read: `return { 요약: (document.body.innerText.match(/\\d+\\/\\d+ 연결/) || [])[0] || null };`,
  },
  {
    name: "09-제안서-초안과-내려받기",
    settle: 2500,
    note: "1:40 6단계 제안서 초안 · 내려받기",
    act: `await dashboardReady();
          const step = await waitFor(() => byText("button", /6제안서 초안|6 제안서 초안/));
          if (step) step.click();
          await new Promise(r => setTimeout(r, 2000));`,
    read: `const t = document.body.innerText;
           return { 문장: (t.match(/\\d+문장 · 확인 \\d+/) || [])[0] || null,
                    내려받기: [...document.querySelectorAll("button,a")].map(e => e.textContent.trim()).filter(x => /^(docx|pdf|txt)$/.test(x)) };`,
  },
  {
    name: "10-제출-전-점검-붙여넣기",
    settle: 3000,
    note: "2:00 7단계 — 결함 초안 붙여넣기 직전",
    act: `await dashboardReady();
          const step = await waitFor(() => byText("button", /7제출 전 누락 점검|7 제출 전 누락 점검/));
          if (step) step.click();
          await new Promise(r => setTimeout(r, 2500));
          const ta = await waitFor(() => document.querySelector("textarea"));
          if (ta) {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
            setter.call(ta, window.__seededDraft || "");
            ta.dispatchEvent(new Event("input", { bubbles: true }));
            ta.scrollIntoView({ block: "center" });
          }
          await new Promise(r => setTimeout(r, 800));`,
    read: `const ta = document.querySelector("textarea");
           return { 글자수: ta ? ta.value.length : 0,
                    점검버튼: !!byText("button", /제출 전 점검|점검 중/) };`,
  },
  {
    name: "11-점검-결과",
    settle: 4000,
    note: "2:15 점검 결과 — 발견 4건 · 높음 2",
    // **고정 6초가 아니라 결과 문구가 바뀔 때까지** 기다린다 (18차 §4-B-4). 점검 요약
    // 줄(「초안을 RFP 원문과 역대조합니다. 발견 n건 …」)이 바뀌거나, 「점검 중」을 본 뒤
    // 그것이 사라지면 끝난 것이다 — 같은 초안으로 다시 돌려 문구가 그대로인 경우를 위해서다.
    act: `const line = () => (document.body.innerText.match(/초안을 RFP 원문과 역대조합니다\\.[^\\n]*/) || [])[0] || "";
          const before = line();
          const run = await waitFor(() => byText("button", /^제출 전 점검$/), 45000, "「제출 전 점검」 단추");
          if (run) run.click();
          let sawBusy = false;
          await waitFor(() => {
            if (byText("button", /점검 중/)) { sawBusy = true; return null; }
            const now = line();
            return (now && now !== before) || (sawBusy && now) ? now : null;
          }, 60000, "점검 결과 문구");`,
    read: `const t = document.body.innerText;
           const long = (t.match(/초안을 RFP 원문과 역대조합니다\\.[^\\n]*/) || [])[0] || "";
           const n = (long.match(/발견 (\\d+)건/) || [])[1];
           const high = (long.match(/높음\\(차단 포함\\) (\\d+)건/) || [])[1];
           return { 발견: (t.match(/발견 \\d+건 · 높음 \\d+/) || [])[0] || (n ? "발견 " + n + "건 · 높음 " + high : null),
                    요약: (t.match(/초안을 RFP 원문과 역대조합니다\\.[^\\n]*/) || [])[0] || null,
                    수치불일치: /수치 불일치/.test(t), 누락: /요구사항 누락|미반영/.test(t) };`,
  },
  {
    name: "12-발견-항목-상세",
    settle: 2500,
    note: "2:25 수치 불일치 상세 — 원문·초안·권고",
    // 발견 목록의 **행 단추**를 누른다 — 「수치 불일치」와 요구사항 번호·쪽이 함께 적힌 것.
    // 같은 낱말을 가진 **묶음 머리글**(「수치 불일치 높음 · 미해결 1 ▾」)을 누르면 목록이
    // 접힐 뿐 상세가 안 열린다. 묶음이 접혀 있으면 먼저 편다.
    act: `await dashboardReady();
          const row = () => $all("button").find((b) =>
            /수치 불일치/.test(b.textContent || "") && /REQ-\\d+|p\\.\\d+/.test(b.textContent || "") && b.offsetParent !== null);
          let hit = await waitFor(() => row() || $all("button").find((b) => /^수치 불일치/.test((b.textContent || "").trim()) && b.offsetParent !== null),
            45000, "「수치 불일치」 발견 행");
          if (hit && !row()) { hit.click(); await new Promise(r => setTimeout(r, 800)); hit = row(); }
          if (hit) { hit.scrollIntoView({ block: "center" }); hit.click(); }
          await waitFor(() => /수정 권고/.test(document.body.innerText), 15000, "상세의 「수정 권고」");`,
    read: `const t = document.body.innerText;
           return { 선택: (t.match(/선택: [^\\n]+/) || [])[0] || null,
                    원문쪽: (t.match(/제안요청서 \\d+쪽|p\\.\\d+/) || [])[0] || null,
                    권고: /수정 권고/.test(t),
                    권고문: (t.match(/RFP 원문은[^\\n]*/) || [])[0] || null };`,
  },
  {
    name: "13-담당자-최종-결정",
    settle: 2500,
    note: "2:40 8단계 담당자 최종 결정",
    act: `await dashboardReady();
          const step = await waitFor(() => byText("button", /8담당자 최종 결정|8 담당자 최종 결정/));
          if (step) step.click();
          await new Promise(r => setTimeout(r, 2000));`,
    // 결정 블록(맨 아래 「사람의 최종 결정」)만 본다 — 3단계 체크리스트에도 「보류」 단추가 있다 (20차 §4-D).
    read: `const region = document.querySelector('[data-panel-region="decision"]') || document;
           return { 버튼: [...region.querySelectorAll("button")].map(b => b.textContent.trim()).filter(x => /^(참여|보류|참여 안 함|검토 승인|다시 검토)$/.test(x)) };`,
  },
  {
    name: "14-보류-저장-대화상자",
    settle: 2000,
    note: "보류 저장 — 담당자 이름과 함께 기록",
    act: `const region = () => document.querySelector('[data-panel-region="decision"]');
          const hold = await waitFor(() => [...(region() || document).querySelectorAll("button")].find((b) => (b.textContent || "").trim() === "다시 검토" && b.offsetParent !== null), 45000, "결정 블록 「다시 검토」");
          if (hold) { hold.scrollIntoView({ block: "center" }); hold.click(); }
          await new Promise(r => setTimeout(r, 1800));
          // 대화상자가 뜨면 담당자 이름을 채워 「저장할 수 있는 상태」를 찍는다 (저장은 누르지 않는다).
          const dlg = document.querySelector("[role=dialog]");
          if (dlg) {
            const input = dlg.querySelector("input");
            if (input) {
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
              setter.call(input, "김담당");
              input.dispatchEvent(new Event("input", { bubbles: true }));
            }
          }
          await new Promise(r => setTimeout(r, 800));`,
    read: `const dlg = document.querySelector("[role=dialog]");
           return { 대화상자: !!dlg, 제목: dlg ? (dlg.querySelector("h2") || {}).textContent : null };`,
  },
  {
    name: "15-발표-모드",
    settle: 3500,
    note: "안내 ▾ → 발표 모드 (9장면 자동)",
    act: `// 앞 장면의 대화상자를 닫는다 — 열려 있으면 상단 메뉴가 눌리지 않는다.
          for (let i = 0; i < 3 && document.querySelector("[role=dialog]"); i += 1) {
            window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            await new Promise(r => setTimeout(r, 700));
          }
          const menu = await waitFor(() => $all("button").find((b) => /^안내/.test((b.textContent || "").trim())));
          if (menu) menu.click();
          await new Promise(r => setTimeout(r, 900));
          const show = await waitFor(() => $all("[role=menuitem]").find((b) => /발표 모드/.test(b.textContent || "")));
          if (show) show.click();
          await new Promise(r => setTimeout(r, 3500));`,
    read: `return { 자막: (document.body.innerText.match(/[^\\n]{10,90}/g) || []).slice(0, 2) };`,
  },
  {
    name: "16-정거장-1-공고",
    url: "/analysis?notice=synthetic-rfp-0001&welcome=0",
    settle: 2500,
    clip: "stage",
    note: "정거장 1 공고 — 레일 1단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-1"]'), 20000, "레일 1단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "1", 10000, "정거장 1");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="1"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "17-정거장-2-적합도",
    settle: 2500,
    clip: "stage",
    note: "정거장 2 적합도 — 레일 2단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-2"]'), 20000, "레일 2단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "2", 10000, "정거장 2");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="2"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "18-정거장-3-참가자격",
    settle: 2500,
    clip: "stage",
    note: "정거장 3 참가자격 — 레일 3단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-3"]'), 20000, "레일 3단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "3", 10000, "정거장 3");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="3"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "19-정거장-4-요구사항",
    settle: 2500,
    clip: "stage",
    note: "정거장 4 요구사항 — 레일 4단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-4"]'), 20000, "레일 4단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "4", 10000, "정거장 4");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="4"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "20-정거장-5-근거",
    settle: 2500,
    clip: "stage",
    note: "정거장 5 근거 — 레일 5단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-5"]'), 20000, "레일 5단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "5", 10000, "정거장 5");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="5"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "21-정거장-6-제안서",
    settle: 2500,
    clip: "stage",
    note: "정거장 6 제안서 — 레일 6단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-6"]'), 20000, "레일 6단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "6", 10000, "정거장 6");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="6"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "22-정거장-7-점검",
    settle: 2500,
    clip: "stage",
    note: "정거장 7 점검 — 레일 7단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-7"]'), 20000, "레일 7단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "7", 10000, "정거장 7");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="7"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },
  {
    name: "23-정거장-8-결정",
    settle: 2500,
    clip: "stage",
    note: "정거장 8 결정 — 레일 8단계를 누른 뒤 지도 (21차 §4-F)",
    act: `await dashboardReady();
          const rail = await waitFor(() => document.querySelector('[data-tour="rail-step-8"]'), 20000, "레일 8단계");
          if (rail) rail.click();
          await waitFor(() => document.documentElement.dataset.cosmosStation === "8", 10000, "정거장 8");
          const s = document.querySelector('section[data-tour="stage"]');
          if (s) window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 8);`,
    read: `const cur = document.documentElement.dataset.cosmosStation;
           const name = document.querySelector('[data-cosmos-station-name="8"]');
           const long = [...document.querySelectorAll('[data-cosmos-label="long"]')].filter(el => el.getAttribute("data-cosmos-station") === cur && Number(getComputedStyle(el).opacity) > 0.05).length;
           return { 정거장: cur, 이름: name ? name.innerText.replace(/\\s+/g, " ").trim() : null, 점: Number(document.documentElement.dataset.cosmosStationNodes ?? -1), 긴라벨: long };`,
  },

  /* 쉬운 보기 (24차 · prompt_14 §4-E) — 여섯 장. `url` 에 mode=simple 을 적는다. 01~23 의 파일 이름은 그대로다. */
  {
    name: "24-쉬운보기-대시보드-합성",
    url: "/analysis?notice=synthetic-rfp-0001&welcome=0&mode=simple",
    settle: 2000,
    note: "쉬운 보기 — 합성 공고 한 열(출처 · 공고 · 참가 판정 · 지금 할 일 · 8단계 · 결정)",
    act: `await waitFor(() => document.querySelector("[data-simple-verdict]") && document.querySelector("[data-simple-step]"), 60000, "쉬운 보기 판정 카드");`,
    read: `const v = document.querySelector("[data-simple-verdict]");
           return { 보기: document.querySelector("[data-view-toggle]")?.getAttribute("data-view-toggle") ?? null,
                    판정: v ? v.getAttribute("data-simple-verdict") : null,
                    문장: v ? v.innerText.split("\\n").filter((s) => s.trim())[1] : null,
                    지금: document.querySelector('[data-simple-chunk="next"]')?.innerText.split("\\n").filter((s) => s.trim())[1] ?? null,
                    지금단계: document.querySelector('[data-simple-step][aria-current="step"]')?.getAttribute("data-simple-step") ?? null };`,
  },
  {
    name: "25-쉬운보기-대시보드-실공고",
    url: "/opportunities?src=g2b&mode=simple",
    settle: 2500,
    note: "쉬운 보기 — 그날 목록에서 마감 전 · 확인 필요 입찰 한 건 (목록 행 → 분석 계속/입찰 분석 시작)",
    act: `await waitFor(() => { const rows = $all("[data-simple-row]"); return rows.length > 0 && !rows.some((r) => /계산 중/.test(r.innerText)); }, 60000, "쉬운 보기 목록 행");
          const row = $all("[data-simple-row]").find((r) => /입찰/.test(r.innerText) && /확인 필요/.test(r.innerText) && /D-\\d+/.test(r.innerText));
          if (!row) window.__missed.push("마감 전 · 확인 필요 입찰 행");
          if (row) {
            row.querySelector("button").click();
            const link = await waitFor(() => row.querySelector('a[href^="/analysis?notice="]'), 5000, "행 이동 단추");
            if (link) link.click();
            await waitFor(() => location.pathname === "/analysis" && document.querySelector("[data-simple-verdict]") && document.querySelector("[data-simple-step]"), 60000, "실공고 쉬운 보기");
            await dismissWelcome();
          }`,
    read: `const v = document.querySelector("[data-simple-verdict]");
           return { 공고: new URLSearchParams(location.search).get("notice"),
                    보기: document.querySelector("[data-view-toggle]")?.getAttribute("data-view-toggle") ?? null,
                    판정: v ? v.getAttribute("data-simple-verdict") : null,
                    문장: v ? v.innerText.split("\\n").filter((s) => s.trim())[1] : null };`,
  },
  {
    name: "26-쉬운보기-사업기회-목록",
    url: "/opportunities?mode=simple",
    settle: 2000,
    note: "쉬운 보기 — 사업기회 한 줄 행(순위는 출처 안의 자리 · 판정은 색 글자)",
    act: `await waitFor(() => { const rows = $all("[data-simple-row]"); return rows.length >= 10 && !rows.some((r) => /계산 중/.test(r.innerText)); }, 60000, "쉬운 보기 목록 행 10");`,
    read: `const inView = $all("[data-simple-row]").filter((r) => { const b = r.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight; });
           return { 한화면행: inView.length, 첫행: inView[0] ? inView[0].innerText.replace(/\\s+/g, " ").slice(0, 90) : null };`,
  },
  {
    name: "27-쉬운보기-행-펼침",
    settle: 1500,
    note: "쉬운 보기 — 행을 눌러 「왜 이 순위인가」 셋 + 이동 단추 + 공고 원문",
    act: `const first = await waitFor(() => document.querySelector("[data-simple-row] > button"), 20000, "첫 행");
          if (first) first.click();
          await waitFor(() => document.querySelector('[data-simple-row] [id^="opp-simple-"]'), 5000, "행 펼침");`,
    read: `const d = document.querySelector('[data-simple-row] [id^="opp-simple-"]');
           return { 펼침: d ? d.innerText.replace(/\\s+/g, " ").slice(0, 160) : null,
                    이동: d ? [...d.querySelectorAll("a")].map((a) => a.innerText.trim()) : null };`,
  },
  {
    name: "28-쉬운보기-지원사업",
    url: "/support/bizinfo-PBLN_000000000123852?mode=simple",
    settle: 2000,
    note: "쉬운 보기 — 지원사업 123852 (사업 · 신청할 수 있나요? · 7단계 · 초안 한 줄) — 126482 는 10-06 마감",
    act: `await waitFor(() => document.querySelector("#support-simple-verdict") && document.querySelector("[data-simple-step]"), 60000, "지원사업 쉬운 보기");`,
    read: `const v = document.querySelector("#support-simple-verdict");
           return { 판정: v ? v.getAttribute("data-simple-verdict") : null,
                    문장: v ? v.innerText.split("\\n").filter((s) => s.trim())[1] : null,
                    출처: document.querySelector("[data-simple-source]")?.innerText ?? null,
                    초안: document.querySelector("[data-plan-summary]")?.innerText ?? null,
                    과제고르기: !!document.querySelector("[data-simple-task-picker]") };`,
  },
  {
    name: "29-쉬운보기-390",
    url: "/analysis?notice=synthetic-rfp-0001&welcome=0&mode=simple",
    viewport: { width: 390, height: 844 },
    settle: 2000,
    note: "쉬운 보기 — 390×844 (한 열 · 가로 넘침 없음)",
    act: `await waitFor(() => document.querySelector("[data-simple-verdict]") && document.querySelector("[data-simple-step]"), 60000, "쉬운 보기 판정 카드(390)");`,
    read: `const v = document.querySelector("[data-simple-verdict]");
           return { 가로: document.documentElement.scrollWidth, 판정카드위: v ? Math.round(v.getBoundingClientRect().top) : null };`,
  },
];

async function main() {
  if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) throw new Error("Edge·Chrome 을 찾지 못했습니다");

  const profile = join(process.env.TEMP || ".", `bidpilot-rehearsal-${PORT}`);
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
      // 렌더러를 잠재우지 않게 한다 — 헤드리스는 가려졌다고 보면 rAF 를 멈춰, 정거장 이동(카메라 tween)이
      // 끝나지 않은 채 찍힌다 (check_visibility · measure_fps 와 같은 이유 · 21차).
      "--disable-renderer-backgrounding",
      "--disable-backgrounding-occluded-windows",
      "--disable-background-timer-throttling",
      "about:blank",
    ],
    { stdio: "ignore", detached: false },
  );

  const cdp = await connect(PORT);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: WIDTH,
    height: HEIGHT,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await clearViewMode(cdp);
  let viewport = { width: WIDTH, height: HEIGHT };

  // 결함 초안을 페이지에 심어 둔다 (10번 장면에서 붙여넣는다).
  //
  // **환경변수가 없어도 돈다** (ISSUE-136 · 18차 §4-B). 17차 리허설은 이 값 없이 돌아
  // 10번이 「글자수 0」 → 11번이 저장된 옛 점검(발견 2건 · 높음 0)을 찍었다 — 시연
  // 클라이맥스를 안 담은 캡처였다. 단일 출처는 `evaluate_auditor.py --print-draft`
  // (= `build_draft(inject=True)`)이고, 체크리스트가 만드는 `docs/demo_defective_draft.txt`
  // 도 같은 것이다. `BIDPILOT_SEEDED_DRAFT` 를 주면 그것이 먼저다(다른 초안을 시험할 때).
  const seeded = process.env.BIDPILOT_SEEDED_DRAFT || defectiveDraft();

  const manifest = [];
  let index = 0;
  for (const scene of SCENES) {
    index += 1;
    const started = Date.now();
    try {
      // 장면이 창 크기를 정하면 그 장면 앞에서 바꾸고, 다음 장면에서 기본 크기로 되돌린다 (24차).
      const want = scene.viewport ?? { width: WIDTH, height: HEIGHT };
      if (want.width !== viewport.width || want.height !== viewport.height) {
        await cdp.send("Emulation.setDeviceMetricsOverride", { width: want.width, height: want.height, deviceScaleFactor: 1, mobile: false });
        viewport = want;
      }
      if (scene.before) {
        await cdp.evaluate(`${HELPERS}\n${scene.before}\nreturn null;`);
      }
      if (scene.url) {
        const target = new URL(scene.url, BASE);
        if (!target.searchParams.has("mode")) target.searchParams.set("mode", "full");
        // 27차 §3-D-11 — 대시보드 전체 보기 장면은 3D 로 고정(쉬운 보기 · 지원사업은 그대로).
        if (target.pathname === "/analysis" && target.searchParams.get("mode") === "full" && !target.searchParams.has("view") && !target.searchParams.has("support")) {
          target.searchParams.set("view", "3d");
        }
        await cdp.send("Page.navigate", { url: target.href });
        await sleep(1500);
      }
      // 결함 초안은 이동 뒤마다 다시 심는다 (페이지가 새로 뜨면 사라진다).
      if (seeded) {
        await cdp.evaluate(`window.__seededDraft = ${JSON.stringify(seeded)}; return null;`);
      }
      if (scene.act) {
        await cdp.evaluate(`${HELPERS}\n${scene.act}\nreturn null;`);
      }
      await sleep(scene.settle ?? 1500);

      const read = scene.read ? await cdp.evaluate(`${HELPERS}\n${scene.read}`) : null;
      // 이 장면에서 기다렸다가 못 본 것 (있으면 그 장면의 값을 믿을 수 없다).
      const missed = await cdp.evaluate(
        `const m = window.__missed || []; window.__missed = []; return m;`,
      );
      // `clip: "stage"` 장면은 지도 구역만 찍는다 (정거장 8장).
      const clip = scene.clip === "stage"
        ? await cdp.evaluate(`const s = document.querySelector('section[data-tour="stage"]');
            if (!s) return null; const r = s.getBoundingClientRect();
            return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height, scale: 1 };`)
        : null;
      const shot = await cdp.send("Page.captureScreenshot", clip ? { format: "png", clip } : { format: "png" });
      const file = `${String(index).padStart(2, "0")}-${scene.name.replace(/^\d+-/, "")}.png`;
      writeFileSync(join(OUT, file), Buffer.from(shot.data, "base64"));
      manifest.push({
        번호: index,
        파일: file,
        장면: scene.note,
        화면에서_읽은_값: read,
        기다렸는데_못_봤다: missed && missed.length ? missed : undefined,
        소요_ms: Date.now() - started,
      });
      console.log(`  [${missed && missed.length ? "주의" : "OK"}] ${file}  ${scene.note}`);
      if (read) console.log(`       ${JSON.stringify(read)}`);
      if (missed && missed.length) console.log(`       기다렸는데 못 봤다: ${missed.join(" · ")}`);
    } catch (error) {
      manifest.push({ 번호: index, 파일: null, 장면: scene.note, 오류: String(error).slice(0, 200) });
      console.log(`  [!!] ${scene.name} — ${String(error).slice(0, 160)}`);
    }
  }

  writeFileSync(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2), "utf-8");
  const blind = manifest.filter((m) => m.기다렸는데_못_봤다);
  console.log(`\n캡처 ${manifest.filter((m) => m.파일).length}장 · ${OUT}`);
  if (blind.length) {
    console.log(`기다렸는데 못 본 장면 ${blind.length}개 — 그 장면의 읽은 값은 믿지 마세요:`);
    for (const m of blind) console.log(`  ${m.번호}. ${m.장면} — ${m.기다렸는데_못_봤다.join(" · ")}`);
  }
  const failed = manifest.filter((m) => m.오류);
  console.log(`기다렸는데 못 본 장면 ${blind.length}개 · 오류 ${failed.length}개`);

  // **브라우저를 CDP 로 닫는다** (18차). Windows 의 Edge 는 띄운 프로세스가 곧 빠지고 실제
  // 브라우저가 따로 남아서, `browser.kill()` 은 이미 끝난 프로세스를 죽일 뿐이었다 — 남은
  // 브라우저가 디버깅 소켓을 쥔 채라 이 스크립트가 캡처를 다 찍고도 끝나지 않았다(18차에
  // 10분 넘게 남아 있었다). 닫히지 않아도 아래 `process.exit` 가 스크립트는 끝낸다.
  await Promise.race([cdp.send("Browser.close").catch(() => null), sleep(3000)]);
  browser.kill();
  // 못 본 장면이나 오류가 있으면 **종료 코드 1** — 조용히 초록이 되지 않게.
  process.exit(blind.length || failed.length ? 1 : 0);
}

main().catch((error) => {
  console.error(String(error));
  process.exit(1);
});
