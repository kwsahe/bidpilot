/**
 * 2.0.5 — 대시보드 끊김 · 모순(대표 10-27 「대시보드엔 bizinfo-PBLN 만, 레이더엔 나라장터」 · 점검 워크플로 확인 항목).
 *
 * 진짜 훅(`useCosmosDashboard`)을 가짜 창 · 가짜 응답으로 그린다(dashboardDefaultNotice.test.ts 와 같은 틀 · 바깥 호출 없음).
 * 이 파일은 `node --test` 가 따로 띄우는 프로세스에서 돌므로 전역(window · fetch)을 바꿔도 다른 시험에 새지 않는다.
 */

import assert from "node:assert/strict";
import { after, describe, it } from "node:test";

const NOTICE_ID = "g2b-R26BK00000001-000";
const TU_ID = "g2b-R26BK00000002-000";
const LOW_ID = "g2b-R26BK00000003-000";
const OTHER_ID = "g2b-R26BK00000004-000";
const BIZ = Array.from({ length: 14 }, (_, i) => `bizinfo-PBLN_0000000001000${String(i).padStart(2, "0")}`);
const BIZ_FAR = BIZ[13]; // 고르기 칸 앞 12건 밖
let href = "http://localhost:3110/";
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

const future = new Date(Date.now() + 20 * 86_400_000).toISOString();
const notice = (id: string, title: string, deadline: string | null) => ({
  id, notice_no: id.slice(4, 17), title, agency: "광주광역시", published_at: new Date().toISOString(), deadline_at: deadline,
  budget: 50_000_000, region: "광주", description: null, source_url: null, raw_data: {},
});
const CANDIDATES = [notice(NOTICE_ID, "생성형 AI 실무교육", future), notice(TU_ID, "AI 교육 운영(마감 미상)", null), notice(OTHER_ID, "디지털 역량 교육", future)];
const LOW = notice(LOW_ID, "요양병원 사이버 연수원 운영(비추천)", future);

/** 시험마다 바꾸는 가짜 서버 상태 */
const server = { listFails: false, firstIsTu: false, parseDelayMs: 0 };

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const list = (notices: unknown[]) => ({ source: "cache", g2b_api_configured: true, fetched_at: new Date().toISOString(), total_fetched: notices.length, count: notices.length, error: null, notices });
globals.fetch = async (input: string | URL, init: RequestInit = {}) => {
  const url = new URL(String(input));
  const method = (init.method ?? "GET").toUpperCase();
  calls.push(`${method} ${url.pathname}${url.search}`);
  const path = url.pathname;
  if (path === "/health") return json({ status: "ok" });
  if (path === "/api/procurements") {
    if (server.listFails) return json({ detail: "boom" }, 500);
    return json(list(url.searchParams.get("include_low") === "true" ? [...CANDIDATES, LOW] : CANDIDATES));
  }
  if (path === "/api/business-opportunities") {
    const g2b = [
      { id: server.firstIsTu ? TU_ID : NOTICE_ID, source_type: "g2b", closed: false, eligibility_gate: "CHECK", deadline: server.firstIsTu ? null : future, company_priority_score: 80, source_rank: 1 },
      { id: server.firstIsTu ? NOTICE_ID : TU_ID, source_type: "g2b", closed: false, eligibility_gate: "CHECK", deadline: server.firstIsTu ? future : null, company_priority_score: 70, source_rank: 2 },
    ];
    const bizinfo = BIZ.map((id, i) => ({ id, source_type: "bizinfo", title: `지원사업 ${i + 1}`, agency: "중소벤처기업부", deadline: future, closed: false, source_rank: i + 1 }));
    return json({ items: [...g2b, ...bizinfo], summary: {}, source_errors: [] });
  }
  if (path.startsWith("/api/support-programs/") && !path.endsWith("/plan-draft")) {
    const id = decodeURIComponent(path.split("/")[3]);
    return json({ program_id: id, organization_id: "org-sample", evidence_scope: "internal", source: "cache", field_mapping_verified: true, generated_at: new Date().toISOString(), program: { id, title: "멀리 있는 지원사업", agency: "창업진흥원", executing_agency: null } });
  }
  if (path.endsWith("/attachments")) return json({ attachments: [{ index: 0, name: "rfp.pdf", cached: true, downloadable: true }], rfp_index: 0, notice_index: 0 });
  if (path === "/api/rfp/parse" && method === "POST") {
    await sleep(server.parseDelayMs);
    return json({ procurement_id: NOTICE_ID, requirements: [] });
  }
  return json({ detail: "not found" }, 404);
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
type Option = { id: string; title: string; support: boolean };
type Dashboard = {
  status: string;
  error: string | null;
  analyzing: boolean;
  selectedNoticeId: string;
  notices: Option[];
  noticeList: { status: string };
  runAnalysis: () => void;
  selectNotice: (id: string) => void;
};
let latest: Dashboard | null = null;
let unmount: (() => void) | null = null;

async function mount(start: string, seed: Record<string, string> = {}): Promise<Dashboard> {
  unmount?.();
  href = start;
  store.clear();
  for (const [key, value] of Object.entries(seed)) store.set(key, value);
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
  await sleep(900);
  assert.ok(latest);
  return latest;
}

describe("대시보드 끊김 · 모순 (2.0.5)", () => {
  after(() => unmount?.());

  it("지원사업을 기억한 채 열어도 나라장터 목록을 받고, 앞 12건 밖 지원사업은 기업마당 묶음에 제 이름으로 선다", async () => {
    const d = await mount("http://localhost:3110/", { "bidpilot.selection-kind.v1": "support", "bidpilot.support.v1": BIZ_FAR });
    assert.equal(d.selectedNoticeId, BIZ_FAR);
    assert.equal(d.noticeList.status, "ready");
    assert.ok(d.notices.some((o) => o.id === NOTICE_ID && !o.support), "나라장터 공고가 고르기 칸에 있어야 한다");
    const far = d.notices.find((o) => o.id === BIZ_FAR);
    assert.ok(far?.support, "지원사업은 나라장터 묶음이 아니라 기업마당 묶음");
    assert.equal(far?.title, "지원사업 14");
    assert.ok(calls.some((c) => c.startsWith("GET /api/procurements")));
  });

  it("기업마당 목록에 없는 지원사업도 나라장터 묶음에 id 글자로 서지 않는다 — 신청 분석 머리의 제목", async () => {
    const gone = "bizinfo-PBLN_000000000199999";
    const d = await mount(`http://localhost:3110/analysis?support=${gone}`);
    const option = d.notices.find((o) => o.id === gone);
    assert.ok(option?.support);
    assert.equal(option?.title, "멀리 있는 지원사업");
  });

  it("사업기회가 「입찰 분석 열기」로 보낸 비추천 공고도 대시보드가 연다", async () => {
    const d = await mount(`http://localhost:3110/analysis?notice=${LOW_ID}`);
    assert.equal(d.selectedNoticeId, LOW_ID);
    assert.notEqual(d.status, "error");
    assert.ok(d.notices.some((o) => o.id === LOW_ID && o.title === LOW.title));
    assert.ok(calls.includes("GET /api/procurements?days=30&include_low=true"));
  });

  it("첫 1위가 「마감 미상」이어도 레이더 · 사업기회 1위와 같은 공고를 연다", async () => {
    server.firstIsTu = true;
    const d = await mount("http://localhost:3110/");
    server.firstIsTu = false;
    assert.equal(d.selectedNoticeId, TU_ID);
  });

  it("고른 것이 없는데 나라장터 목록을 못 받으면 말없이 가상 예시로 가지 않는다", async () => {
    server.listFails = true;
    const d = await mount("http://localhost:3110/");
    server.listFails = false;
    assert.equal(d.status, "error");
    assert.ok(d.error);
    assert.equal(d.noticeList.status, "error");
    // 예전엔 가상 예시 자료를 불러 그 화면으로 갔다
    assert.ok(!calls.some((c) => c.includes("synthetic-rfp-0001")), calls.join("\n"));
    // 그 오류 화면에서 고르기 칸의 「가상 예시」를 고르면 실제로 연다(같은 id 라 아무 일도 안 하던 것 · 검토 R1)
    latest?.selectNotice("synthetic-rfp-0001");
    await sleep(900);
    assert.equal(latest?.selectedNoticeId, "synthetic-rfp-0001");
    assert.ok(calls.some((c) => c.includes("synthetic-rfp-0001")), "가상 예시 자료를 불러야 한다");
  });

  it("분석 중에 뒤로가기로 공고가 바뀌면 「분석 중」이 풀린다", async () => {
    server.parseDelayMs = 4000;
    const d = await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    d.runAnalysis();
    await sleep(600);
    assert.equal(latest?.analyzing, true);
    href = `http://localhost:3110/analysis?notice=${OTHER_ID}`;
    globals.dispatchEvent instanceof Function && (globals.dispatchEvent as (e: Event) => boolean)(new Event("popstate"));
    await sleep(900);
    server.parseDelayMs = 0;
    assert.equal(latest?.selectedNoticeId, OTHER_ID);
    assert.equal(latest?.analyzing, false);
  });
});
