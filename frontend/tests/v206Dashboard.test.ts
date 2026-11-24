/**
 * 2.0.6 — 대시보드 · 고르기 칸 · 판정 칸 · 메뉴(전체 점검 lists-2 · values-3 · fallback-1 · lists-3 · fallback-2 · lists-6 · lists-7 ·
 * state-1 · state-3 · state-4 · state-5 · fallback-8).
 *
 * 진짜 훅(`useCosmosDashboard`)을 가짜 창 · 가짜 응답으로 그린다(dashboardDisconnect.test.ts 와 같은 틀 · 바깥 호출 없음).
 * `node --test` 가 파일마다 프로세스를 따로 띄우므로 전역(window · fetch)을 바꿔도 다른 시험에 새지 않는다.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { after, describe, it } from "node:test";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

const NOTICE_ID = "g2b-R26BK00000001-000";
const OUT_ID = "g2b-R26BK00000002-000"; // 나라장터 목록엔 있지만 회사 목록(통합)엔 없음 = 불가 · 실제 마감
const LOW_ID = "g2b-R26BK00000003-000"; // 관련 낮음 — include_low 로만 옴
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
    href = new URL(String(next), href).href;
  },
  pushState(_state: unknown, _title: string, next: string) {
    href = new URL(String(next), href).href;
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
const notice = (id: string, title: string) => ({
  id, notice_no: id.slice(4, 17), title, agency: "광주광역시", published_at: new Date().toISOString(), deadline_at: future,
  budget: 50_000_000, region: "광주", description: null, source_url: null, raw_data: {}, recommendation: { grade: "A" },
});
const CANDIDATES = [notice(NOTICE_ID, "생성형 AI 실무교육"), notice(OUT_ID, "참가 불가 공고")];
const LOW = notice(LOW_ID, "관련 낮은 공고");

/** 시험마다 바꾸는 가짜 서버 상태 */
const server = { rankFails: false, wideFails: false, unifiedFails: false, sourceErrors: {} as Record<string, string>, keepItems: false, decisionFails: false };

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const list = (notices: unknown[]) => ({ source: "cache", g2b_api_configured: true, fetched_at: new Date().toISOString(), total_fetched: notices.length, count: notices.length, error: null, notices });
globals.fetch = async (input: string | URL, init: RequestInit = {}) => {
  const url = new URL(String(input));
  const method = (init.method ?? "GET").toUpperCase();
  calls.push(`${method} ${url.pathname}${url.search}`);
  const path = url.pathname;
  if (path === "/health") return json({ status: "ok" });
  if (path === "/api/procurements") {
    if (url.searchParams.get("include_low") === "true") return server.wideFails ? json({ detail: "boom" }, 503) : json(list([...CANDIDATES, LOW]));
    return json(list(CANDIDATES));
  }
  if (path === "/api/business-opportunities") {
    const g2bOnly = url.searchParams.get("source") === "g2b";
    if (g2bOnly && server.rankFails) return json({ detail: "rank down" }, 502);
    if (!g2bOnly && server.unifiedFails) return json({ detail: "unified down" }, 502);
    // keepItems — 저장본으로 대신 준 날(항목 + 오류 글이 함께 옴). g2b 전용 순위 요청에도 같은 오류를 싣는다.
    const errors = g2bOnly ? (server.keepItems ? server.sourceErrors : {}) : server.sourceErrors;
    const g2b = errors.g2b && !server.keepItems ? [] : [{ id: NOTICE_ID, source_type: "g2b", closed: false, eligibility_gate: "CHECK", deadline: future, company_priority_score: 80, source_rank: 1, practical_group: "긴급" }];
    const bizinfo = g2bOnly || (errors.bizinfo && !server.keepItems)
      ? []
      : Array.from({ length: 15 }, (_, i) => ({ id: `bizinfo-PBLN_00000000010${String(i).padStart(4, "0")}`, source_type: "bizinfo", title: `지원사업 ${i + 1}`, agency: "중기부", deadline: future, closed: false, source_rank: i + 1, practical_group: i < 13 ? "일반 접수 중" : "비추천" }));
    return json({ items: [...g2b, ...bizinfo], summary: {}, source_errors: errors });
  }
  if (path.startsWith("/api/decision/")) {
    return server.decisionFails ? json({ detail: "decision down" }, 500) : json({ procurement_id: NOTICE_ID, status: "UNREVIEWED", reasons: [], decided_by: null, decided_at: null });
  }
  return json({ detail: "not found" }, 404);
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
type Option = { id: string; title: string; support: boolean; outside?: boolean };
type Dashboard = {
  status: string;
  error: string | null;
  selectedNoticeId: string;
  notices: Option[];
  noticeList: { status: string; message: string | null; priorityMessage?: string | null; supportTotal?: number | null };
  supportError: string | null;
  graph: { source: { analysis: { decisionError?: string | null } } } | null;
  selectNotice: (id: string) => void;
  reload: () => void;
  reloadLists: () => void;
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
  await sleep(1200);
  assert.ok(latest);
  return latest;
}

describe("대시보드 모순 · 미연결 (2.0.6)", () => {
  after(() => unmount?.());

  it("처음 열 1위를 묻다 실패하면 말없이 가상 예시를 열지 않는다 — 사유를 보이고 고르기 칸은 쓸 수 있다", async () => {
    server.rankFails = true;
    const d = await mount("http://localhost:3110/");
    server.rankFails = false;
    assert.equal(d.status, "error");
    assert.match(d.error ?? "", /처음 열 공고\(회사 기준 1위\)를 정하지 못했습니다/);
    assert.ok(!calls.some((c) => c.includes("synthetic-rfp-0001")), calls.join("\n"));
    assert.equal(d.noticeList.status, "ready");
    assert.ok(d.notices.some((o) => o.id === NOTICE_ID));
    // 고르기 칸이 열지 않은 「가상 예시」를 고른 것처럼 보이지 않게 — 아무것도 열지 못했다는 표지(통합 검토 cross-6)
    assert.equal((d.noticeList as { openFailed?: boolean }).openFailed, true);
  });

  it("저장본으로 대신 받은 날(항목 + source_errors)은 실패가 아니다 — 1위를 열고, 「받지 못했습니다」를 띄우지 않는다", async () => {
    server.sourceErrors = { bizinfo: "기업마당 실시간 받기 실패 — 저장본", g2b: "나라장터 실시간 받기 실패 — 저장본" };
    server.keepItems = true;
    const d = await mount("http://localhost:3110/");
    server.sourceErrors = {};
    server.keepItems = false;
    assert.equal(d.selectedNoticeId, NOTICE_ID);
    assert.notEqual(d.status, "error");
    assert.equal(d.supportError, null);
    assert.equal(d.noticeList.priorityMessage, null);
  });

  it("기억한 공고를 다시 찾다 실패하면 「목록에 없다」고 하거나 기억을 지우지 않는다", async () => {
    server.wideFails = true;
    const d = await mount("http://localhost:3110/", { "bidpilot.notice.v1": LOW_ID, "bidpilot.selection-kind.v1": "notice" });
    server.wideFails = false;
    assert.equal(d.status, "error");
    assert.match(d.error ?? "", /다시 확인하지 못했습니다/);
    assert.equal(store.get("bidpilot.notice.v1"), LOW_ID, "기억한 선택이 남아야 한다");
  });

  it("회사 목록 밖(불가 · 실제 마감) 공고는 「목록 밖」 — 기업마당 전체 수는 비추천을 뺀 수", async () => {
    const d = await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    assert.equal(d.notices.find((o) => o.id === OUT_ID)?.outside, true);
    assert.equal(d.notices.find((o) => o.id === NOTICE_ID)?.outside, false);
    assert.equal(d.noticeList.supportTotal, 13);
  });

  it("한 출처만 실패(200 + source_errors)해도 「없음」이 아니라 실패로 — 기업마당은 오류 줄, 나라장터는 「목록 밖」으로 접지 않음", async () => {
    server.sourceErrors = { bizinfo: "기업마당 수집 오류", g2b: "나라장터 저장본 오류" };
    const d = await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    server.sourceErrors = {};
    assert.equal(d.supportError, "기업마당 수집 오류");
    assert.equal(d.noticeList.priorityMessage, "나라장터 저장본 오류");
    assert.ok(d.notices.filter((o) => !o.support).every((o) => !o.outside), "순위를 못 받으면 모두 접히면 안 된다");
  });

  it("통합 목록을 못 받으면 고르기 칸이 추천등급 순임을 밝히고, 「다시 시도」가 그것도 다시 받는다", async () => {
    server.unifiedFails = true;
    const d = await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    assert.ok(d.noticeList.priorityMessage);
    server.unifiedFails = false;
    const before = calls.filter((c) => c.startsWith("GET /api/business-opportunities?organization_id=org-sample&days=30")).length;
    latest?.reload();
    await sleep(1200);
    const afterCount = calls.filter((c) => c.startsWith("GET /api/business-opportunities?organization_id=org-sample&days=30")).length;
    assert.ok(afterCount > before, "다시 시도가 통합 목록도 다시 받아야 한다");
    assert.equal(latest?.noticeList.priorityMessage, null);
  });

  it("2.0.7 「찾는 낱말」 뒤 목록만 다시 받기 — 나라장터 목록 · 통합 순위만 다시 받고, 보는 공고 · 분석은 다시 부르지 않는다", async () => {
    const d = await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    const status = d.status;
    const start = calls.length;
    d.reloadLists();
    await sleep(900);
    const added = calls.slice(start);
    assert.ok(added.includes("GET /api/procurements?days=30"), added.join(" | "));
    assert.ok(added.some((c) => c.startsWith("GET /api/business-opportunities?organization_id=org-sample&days=30")), added.join(" | "));
    const others = added.filter((c) => c !== "GET /api/procurements?days=30" && !c.startsWith("GET /api/business-opportunities?"));
    assert.deepEqual(others, [], "분석 · 판정 · 결정을 다시 부르지 않는다");
    assert.equal(latest?.selectedNoticeId, NOTICE_ID);
    assert.equal(latest?.status, status);
  });

  it("2.0.7 목록만 다시 받다 통합 순위가 실패해도 잘 보이던 고르기 칸(기업마당 묶음 · 순번)을 오류로 덮지 않는다(frontend-6)", async () => {
    const d = await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    assert.equal(d.noticeList.supportTotal, 13);
    server.unifiedFails = true;
    d.reloadLists();
    await sleep(900);
    server.unifiedFails = false;
    assert.equal(latest?.supportError, null);
    assert.equal(latest?.noticeList.priorityMessage, null);
    assert.equal(latest?.noticeList.supportTotal, 13);
    assert.equal(latest?.notices.find((o) => o.id === OUT_ID)?.outside, true, "순번을 지켜 「목록 밖」 표시도 그대로");
  });

  it("처음 보여 준 1위를 고르기 칸에서 다시 고르면 기억하고, 다시 불러오지 않는다", async () => {
    const d = await mount("http://localhost:3110/");
    assert.equal(d.selectedNoticeId, NOTICE_ID);
    assert.equal(store.get("bidpilot.notice.v1"), undefined);
    const loads = calls.filter((c) => c.startsWith("GET /api/procurements?days=30")).length;
    d.selectNotice(NOTICE_ID);
    await sleep(900);
    assert.equal(store.get("bidpilot.notice.v1"), NOTICE_ID);
    assert.equal(calls.filter((c) => c.startsWith("GET /api/procurements?days=30")).length, loads, "같은 공고를 다시 불러오지 않는다");
    assert.equal(latest?.status === "error", false);
  });

  it("결정을 읽다 실패하면 「검토 전」이 아니라 실패 표지 — 판정 칸이 결정 단추를 잠근다", async () => {
    server.decisionFails = true;
    await mount(`http://localhost:3110/analysis?notice=${NOTICE_ID}`);
    await sleep(800);
    server.decisionFails = false;
    assert.ok(latest?.graph?.source.analysis.decisionError, "결정 읽기 실패가 남아야 한다");
    const gate = read("components", "cosmos", "GatePanel.tsx");
    assert.match(gate, /disabled=\{actions\.gateBusy \|\| Boolean\(decisionError\)\} onClick=\{\(\) => submit\("HOLD"\)\}/);
    assert.match(gate, /저장된 결정을 읽지 못했습니다/);
  });
});

describe("고르기 칸 · 임시 저장 · 메뉴 (2.0.6 · 소스)", () => {
  it("출처 실패는 그 출처 항목이 하나도 없을 때만 — 서버 failed_sources 와 같은 규칙", async () => {
    const { sourceFailure } = await import("../src/lib/errors.ts");
    const errors = { g2b: "오류", bizinfo: null };
    assert.equal(sourceFailure({ items: [{ source_type: "g2b" }], source_errors: errors }, "g2b"), null);
    assert.equal(sourceFailure({ items: [{ source_type: "bizinfo" }], source_errors: errors }, "g2b"), "오류");
    assert.equal(sourceFailure({ items: [], source_errors: errors }, "bizinfo"), null);
  });

  it("끝난 공고는 날짜가 비어도 「입찰 종료」 — 「접수 기간 미정」이 아니다", async () => {
    const { deadlineTerm } = await import("../src/lib/deadline.ts");
    assert.equal(deadlineTerm({ source: "g2b", closed: true, periodKind: null, deadline: null }), "입찰 종료");
    assert.equal(deadlineTerm({ source: "bizinfo", closed: true, periodKind: null, deadline: null }), "신청 종료");
    assert.equal(deadlineTerm({ source: "g2b", closed: false, periodKind: null, deadline: null }), "접수 기간 미정");
  });

  it("마지막 검토 몫 — 지표 띠 결정 실패 · 6단계 링크 글 · 결정 메모 비움 · 결정 · 검토 저장도 1위 기억 · 목록 밖 마감 입찰 잠금", () => {
    const mission = read("lib", "cosmos", "mission.ts");
    assert.match(mission, /const decision: MissionMetricBase = analysis\.decisionError\s*\? \{[^}]*value: DECISION_READ_FAILED/);
    assert.match(mission, /graph\.reviewDecision && !graph\.source\.analysis\.decisionError/);
    assert.match(read("components", "cosmos", "DetailPanel.tsx"), /페이지 열기 — 마감이라 새로 쓰기는 잠김 →/);
    assert.match(read("components", "cosmos", "GatePanel.tsx"), /setReasons\(loadDraft\(draftKey\)\);[\s\S]{0,200}setNote\(""\);\s*setPending\(null\);/);
    const hook = read("lib", "cosmos", "useCosmosDashboard.ts");
    assert.equal((hook.match(/adoptDefault\(activeNoticeId\)/g) ?? []).length, 2, "결정 · 검토 저장 성공에도 기억");
    const plan = read("app", "plan", "page.tsx");
    assert.match(plan, /bidClosed: value\.deadline_at \? Date\.parse\(value\.deadline_at\) <= Date\.now\(\) : null/);
    assert.match(plan, /const bidClosed = here \? here\.closed : far \? far\.bidClosed === true :/);
    assert.match(plan, /closed=\{bidClosed\}/);
  });

  it("통합 검토 화면 몫 — 로그아웃 · 판정 칸 다시 읽기 · 메뉴 · 공고 바꾸기 한 창 · 결정 실패 문구 · 정리 함수 · 6단계 · 제안서 안내", () => {
    assert.match(read("components", "cosmos", "TopBar.tsx"), /clearAllDrafts\(\);[^\n]*\r?\n\s*clearSelectionMemory\(\);/);
    const gate = read("components", "cosmos", "GatePanel.tsx");
    assert.match(gate, /`condition-note:\$\{organizationId\}:\$\{noticeId\}:\$\{condition\.id\}`/);
    assert.match(gate, /`action-evidence:\$\{organizationId\}:\$\{item\.procurement_id\}:\$\{item\.id\}`/);
    assert.match(gate, /if \(reasonsKey !== draftKey\) \{\s*setReasonsKey\(draftKey\);\s*setReasons\(loadDraft\(draftKey\)\);/);
    const shell = read("components", "ui", "AppShell.tsx");
    assert.match(shell, /onClick=\{active \? undefined : leaveGuard\}/);
    assert.match(shell, /onClick=\{onHome \? undefined : leaveGuard\}/);
    const dash = read("components", "cosmos", "DashboardShell.tsx");
    assert.match(dash, /hasUnsaved\(\) \? "작성 중인 내용" : null/);
    assert.match(dash, /forgetUnsaved\(\);/);
    assert.match(read("lib", "cosmos", "graph.ts"), /analysis\.decisionError\s*\? \{ status: "attention", summary: DECISION_READ_FAILED \}/);
    assert.match(read("lib", "cosmos", "mission.ts"), /!graph\.source\.analysis\.decisionError &&/);
    assert.match(read("lib", "cosmos", "provenance.ts"), /if \(graph\.source\.analysis\.decisionError\) return \{ kind: "failed", label: DECISION_READ_FAILED \};/);
    const hook = read("lib", "cosmos", "useCosmosDashboard.ts");
    assert.equal((hook.match(/return cleanup;/g) ?? []).length, 2, "건너뛰는 갈래도 정리 함수를 돌려준다");
    assert.match(hook, /const priorityCurrent = priorityState\.key === `\$\{organizationId\}:\$\{days\}`;/);
    assert.match(read("components", "cosmos", "DetailPanel.tsx"), /writeClosed \? `\$\{SCREEN_NAMES\.plan\} 페이지 열기 — 마감이라 새로 쓰기는 잠김 →`/);
    const plan = read("app", "plan", "page.tsx");
    // 지원사업 · 입찰(11-03 옛 가상 예시 초안 칸이 없어져 입찰은 한 곳)
    assert.equal((plan.match(/closedBlock \? "마감된 공고라 새로/g) ?? []).length, 2);
  });

  it("목록에 없는 입찰도 지금 연 공고 머리로 제 이름을 세운다(id 글자 금지)", async () => {
    const { buildNoticeOptions } = await import("../src/lib/cosmos/useCosmosDashboard.ts");
    const options = buildNoticeOptions(null, LOW_ID, [], new Map(), { title: "관련 낮은 공고", agency: "광주광역시" }, false);
    const picked = options.find((o) => o.id === LOW_ID);
    assert.equal(picked?.title, "관련 낮은 공고");
    assert.equal(picked?.support, false);
  });

  it("기업마당 묶음은 「N건 중 상위 n건」, 순위를 못 받으면 나라장터 묶음이 그 사실을 적는다", () => {
    const src = read("components", "cosmos", "NoticePicker.tsx");
    assert.match(src, /pickerHiddenLabel\(noticeList\.supportTotal \?\? supportOptions\.length, supportOptions\.length\)/);
    assert.match(src, /검토 순서를 받지 못해 추천등급 순/);
  });

  it("임시 저장 키에 회사 · 공고가 들어간다(판정 칸 · 해결 메모)", () => {
    const gate = read("components", "cosmos", "GatePanel.tsx");
    assert.match(gate, /`decision:\$\{organizationId\}:\$\{graph\.source\.notice\.id\}`/);
    assert.match(gate, /`condition-note:\$\{organizationId\}:\$\{noticeId\}:\$\{condition\.id\}`/);
    assert.match(gate, /`action-evidence:\$\{organizationId\}:\$\{item\.procurement_id\}:\$\{item\.id\}`/);
    const detail = read("components", "cosmos", "DetailPanel.tsx");
    assert.match(detail, /`finding-note:\$\{noticeId\}:\$\{finding\.resolutionKey\}`/);
  });

  it("상단 메뉴 · 로고로 떠날 때도 작성 중 확인 — 검사할 초안도 공통 확인이 함께 묻는다", () => {
    const shell = read("components", "ui", "AppShell.tsx");
    assert.match(shell, /function leaveGuard\(event: MouseEvent<HTMLAnchorElement>\): void \{\s*if \(!confirmDiscard\("작성 중인 내용"\)\) event\.preventDefault\(\);/);
    // 지금 화면 메뉴 · 대시보드의 로고는 떠나는 것이 아니라 묻지 않는다(통합 검토 dashboard-4)
    assert.equal((shell.match(/onClick=\{(active|onHome) \? undefined : leaveGuard\}/g) ?? []).length, 2);
    assert.match(read("components", "cosmos", "AuditorRunPanel.tsx"), /markDirty\("auditor-draft", next\)/);
  });

  it("로그아웃은 공고 · 지원사업 기억도 지운다 — 다음 계정이 앞 사람의 「보던 공고」로 가지 않게", () => {
    assert.match(read("components", "ui", "SessionControls.tsx"), /clearAllDrafts\(\);\s*clearSelectionMemory\(\);/);
    const selection = read("lib", "selection.ts");
    assert.match(selection, /export function clearSelectionMemory\(\): void \{\s*writeStore\(NOTICE_STORAGE_KEY, null\);\s*writeStore\(SUPPORT_STORAGE_KEY, null\);\s*writeStore\(SELECTION_KIND_KEY, null\);/);
  });

  it("레이더 → 지원사업 분석은 레이더 조건을 싣고, 「← 레이더」가 그 조건으로 돌아간다 · 추적 카드 꼬리표는 읽히는 색", () => {
    const detail = read("components", "radar", "RadarDetail.tsx");
    assert.match(detail, /href=\{nextHref\(item\.next_route\.path, radarSearch\)\}/);
    assert.match(detail, /rfrom=\$\{encodeURIComponent\(radarSearch\)\}/);
    const support = read("components", "support", "SupportShell.tsx");
    assert.match(support, /get\("rfrom"\)/);
    assert.match(support, /link\.href === "\/radar" \? radarHref/);
    const tracked = read("components", "radar", "RadarTrackedPanel.tsx");
    assert.match(tracked, /style=\{\{ color: tagColor, backgroundColor: withAlpha\(tagColor, 12\) \}\}/);
  });
});
