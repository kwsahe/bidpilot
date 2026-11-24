/**
 * 대시보드 첫 공고 = 실제 1위(36차 결정 2) 뒤의 두 회귀 — 36차 마지막 검토 FE-1 · FE-2.
 *
 * - FE-1: 고르지 않은 첫 화면(실제 1위)에서 「가상 예시」를 고르면 「불러오는 중」에 멈췄고, 실제 공고를 보던 중이면 가상 예시 대신
 *   실제 1위가 열렸다.
 * - FE-2: 첫 화면의 실제 1위를 분석하면 끝에 주소를 써서 처음부터 다시 불러왔고, 분석 토큰이 끊겨 「분석 중…」이 잠긴 채 남았다.
 *
 * 진짜 훅(`useCosmosDashboard`)을 가짜 창 · 가짜 응답으로 그린다(브라우저 · 서버 없음 · 바깥 호출 없음).
 * 이 파일은 `node --test` 가 따로 띄우는 프로세스에서 돌므로 전역(window · fetch)을 바꿔도 다른 시험에 새지 않는다.
 */

import assert from "node:assert/strict";
import { after, describe, it } from "node:test";

type Snapshot = { selected: string; analyzing: boolean; href: string; stored: Record<string, string> };

const NOTICE_ID = "g2b-R26BK00000001-000";
const DEMO_ID = "synthetic-rfp-0001";
let href = "http://localhost:3110/analysis";
const store = new Map<string, string>();
const calls: string[] = [];
const events = new EventTarget();

const globals = globalThis as unknown as Record<string, unknown>;
globals.window = globalThis;
globals.addEventListener = events.addEventListener.bind(events);
globals.removeEventListener = events.removeEventListener.bind(events);
globals.dispatchEvent = events.dispatchEvent.bind(events);
Object.defineProperty(globalThis, "location", {
  configurable: true,
  get() {
    const url = new URL(href);
    return { href, search: url.search, pathname: url.pathname, origin: url.origin };
  },
});
globals.history = {
  state: null,
  replaceState(_state: unknown, _title: string, next: string) {
    href = String(next);
  },
  pushState(_state: unknown, _title: string, next: string) {
    href = String(next);
  },
};
const fakeStorage = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, String(value)),
  removeItem: (key: string) => void store.delete(key),
};
globals.localStorage = fakeStorage;
globals.sessionStorage = fakeStorage;
globals.HTMLIFrameElement = class {};

const future = new Date(Date.now() + 5 * 86_400_000).toISOString();
const notice = {
  id: NOTICE_ID, notice_no: "R26BK00000001", title: "생성형 AI 실무교육", agency: "광주광역시",
  published_at: new Date().toISOString(), deadline_at: future, budget: 50_000_000, region: "광주",
  description: null, source_url: null, raw_data: {},
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
globals.fetch = async (input: string | URL, init: RequestInit = {}) => {
  const url = new URL(String(input));
  const method = (init.method ?? "GET").toUpperCase();
  calls.push(`${method} ${url.pathname}`);
  const path = url.pathname;
  if (path === "/health") return json({ status: "ok" });
  if (path === "/api/procurements") {
    return json({ source: "cache", g2b_api_configured: true, fetched_at: new Date().toISOString(), total_fetched: 1, count: 1, error: null, notices: [notice] });
  }
  if (path === "/api/business-opportunities") {
    return json({ items: [{ id: NOTICE_ID, source_type: "g2b", closed: false, eligibility_gate: "PASS", deadline: future, company_priority_score: 90 }], summary: {}, source_errors: [] });
  }
  if (path.endsWith("/attachments")) return json({ attachments: [{ index: 0, name: "rfp.pdf", cached: true, downloadable: true }], rfp_index: 0, notice_index: 0 });
  if (path === "/api/rfp/parse" && method === "POST") return json({ procurement_id: NOTICE_ID, requirements: [] });
  return json({ detail: "not found" }, 404);
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
type Dashboard = { selectedNoticeId: string; analyzing: boolean; selectNotice: (id: string) => void; runAnalysis: () => void };
let latest: Dashboard | null = null;
let unmount: (() => void) | null = null;

async function mount(start: string): Promise<void> {
  href = start;
  store.clear();
  calls.length = 0;
  const React = (await import("react")).default;
  const { createRoot } = await import("react-dom/client");
  const { useCosmosDashboard } = await import("../src/lib/cosmos/useCosmosDashboard.ts");
  function Probe() {
    latest = useCosmosDashboard({ reducedMotion: true, organizationId: "org-sample" }) as unknown as Dashboard;
    return null;
  }
  const noop = () => {};
  const ownerDocument = { addEventListener: noop, removeEventListener: noop, nodeType: 9 };
  const container = {
    nodeType: 1, nodeName: "DIV", tagName: "DIV", localName: "div", namespaceURI: "http://www.w3.org/1999/xhtml",
    addEventListener: noop, removeEventListener: noop, ownerDocument, textContent: "", firstChild: null, removeChild: noop,
  };
  const root = createRoot(container as unknown as Element);
  root.render(React.createElement(Probe));
  unmount = () => root.unmount();
  await sleep(600);
}

function snap(): Snapshot {
  assert.ok(latest);
  return { selected: latest.selectedNoticeId, analyzing: latest.analyzing, href, stored: Object.fromEntries(store) };
}

describe("대시보드 첫 공고 = 실제 1위 — 고르기 · 분석", () => {
  after(() => unmount?.());

  it("첫 화면은 실제 1위이고 주소 · 저장소에 남기지 않는다", async () => {
    await mount("http://localhost:3110/analysis");
    const first = snap();
    assert.equal(first.selected, NOTICE_ID);
    assert.equal(first.href, "http://localhost:3110/analysis");
    assert.equal(first.stored["bidpilot.notice.v1"], undefined);
  });

  it("FE-2 처음 보여 준 실제 1위를 분석하면 한 번만 돌고 「분석 중」이 풀린다 · 끝난 뒤에 그 공고를 기억한다", async () => {
    assert.ok(latest);
    const before = calls.length;
    latest.runAnalysis();
    await sleep(2500);
    const after = snap();
    assert.equal(after.analyzing, false);
    // 2.0.6(state-1) — 분석을 마친 1위는 기억한다(메뉴 · 「보던 공고로」 · 정리표가 그 공고를 알게). 끝난 **뒤에** 쓰고 다시 불러오지 않아
    // FE-2(도중에 써서 다시 불러오며 분석이 끊김 · 판정 두 번)는 그대로 막힌다 — 아래 판정 1번.
    assert.equal(after.href, `http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    assert.equal(after.stored["bidpilot.notice.v1"], NOTICE_ID);
    assert.equal(calls.slice(before).filter((c) => c === "POST /api/eligibility/evaluate").length, 1);
    unmount?.();
  });

  it("FE-1 첫 화면에서 가상 예시를 고르면 가상 예시가 열린다", async () => {
    await mount("http://localhost:3110/analysis");
    assert.ok(latest);
    latest.selectNotice(DEMO_ID);
    await sleep(1500);
    const picked = snap();
    assert.equal(picked.selected, DEMO_ID);
    assert.equal(picked.href, "http://localhost:3110/analysis");  // 가상 예시는 주소에 남기지 않는다
    unmount?.();
  });

  it("FE-1 실제 공고를 보던 중에 가상 예시를 고르면 실제 1위가 아니라 가상 예시가 열린다", async () => {
    await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    assert.ok(latest);
    assert.equal(snap().selected, NOTICE_ID);
    latest.selectNotice(DEMO_ID);
    await sleep(1500);
    const picked = snap();
    assert.equal(picked.selected, DEMO_ID);
    assert.equal(picked.href, "http://localhost:3110/analysis");
    assert.equal(picked.stored["bidpilot.notice.v1"], undefined);
  });
});
