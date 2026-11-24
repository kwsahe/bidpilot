/**
 * 2.0.7 「찾는 낱말」 — 잠김 이유 셋 · 결과 한 줄 · 결과 주소 · 입력 안내(서버 규칙의 사본) · 네 호출의 몸 · 활동 기록 이름 · 부품 · 배치.
 *
 * 부품(.tsx)은 node 시험이 바로 불러오지 못한다 — 놓인 자리의 소스 글을 본다(v206Opportunities.test.ts 와 같은 방식).
 * 호출은 가짜 fetch 로만 본다(바깥 호출 없음).
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/collectKeywords.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { actionLabel } from "../src/lib/activityLog.ts";
import { addCollectKeyword, getCollectKeywords, removeCollectKeyword, searchCollectKeyword } from "../src/lib/api.ts";
import {
  KEYWORD_SEARCH_EXCEPTION,
  keywordInputProblem,
  keywordNextCollect,
  keywordResultHref,
  keywordSearchLock,
  keywordSearchOffReason,
  keywordSearchSummary,
} from "../src/lib/collectKeywords.ts";
import { buildHaystack, matchesQuery } from "../src/lib/opportunitySearch.ts";
import { RECOLLECT_LOCKED_REASON } from "../src/lib/recollect.ts";
import { VIEWER_LOCK_LABEL } from "../src/lib/viewerLock.ts";
import type { AuditLogEntry } from "../src/types/audit.ts";
import type { CollectKeywordsState, KeywordSearchResult } from "../src/types/collectKeywords.ts";
import type { CollectState } from "../src/types/opportunity.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

const state = (over: Partial<CollectKeywordsState> = {}): CollectKeywordsState => ({
  base: ["AI", "인공지능", "전략 수립", "e-Learning"],
  extra: [],
  max_extra: 10,
  searches_today: 0,
  searches_limit: 10,
  search_live: true,
  updated_at: null,
  ...over,
});
const ok: CollectState = { kind: "ok", text: "매일 처음 켤 때 자동으로 받음 · 오늘 07:31" };
const entry = (word: string) => ({ word, added_by: "hajin", added_by_name: "김담당", added_at: "2026-10-27T09:00:00+09:00" });
const result = (over: Partial<KeywordSearchResult> = {}): KeywordSearchResult => ({
  word: "메타버스",
  found: 7,
  new_notices: 5,
  candidates: 2,
  low: 3,
  truncated: false,
  calls: 2,
  searched_at: "2026-10-27T10:00:00+09:00",
  ...over,
});

describe("바로 찾기 잠김 이유 셋", () => {
  it("열람자는 「열람자 — 보기만」 — 문 · 횟수보다 먼저", () => {
    assert.equal(keywordSearchLock(state({ search_live: false, searches_today: 10 }), true), VIEWER_LOCK_LABEL);
    assert.equal(VIEWER_LOCK_LABEL, "열람자 — 보기만");
  });

  it("서버 문이 꺼져 있으면 저장만 — 다음 받기부터 찾는다", () => {
    assert.equal(keywordSearchLock(state({ search_live: false }), false, ok), keywordSearchOffReason(ok));
    assert.equal(keywordSearchOffReason(ok), "이 서버에서는 바로 찾기가 꺼져 있습니다 — 다음 자동 받기부터 이 낱말로 찾습니다");
  });

  it("오늘 횟수를 다 쓰면 잠긴다 — 숫자는 응답의 상한", () => {
    assert.equal(keywordSearchLock(state({ searches_today: 10 }), false, ok), "오늘 바로 찾기 10번을 다 썼습니다 — 다음 자동 받기부터 찾습니다");
    assert.equal(keywordSearchLock(state({ searches_today: 3, searches_limit: 3 }), false, ok), "오늘 바로 찾기 3번을 다 썼습니다 — 다음 자동 받기부터 찾습니다");
    assert.equal(keywordSearchLock(state({ searches_today: 9 }), false, ok), null);
  });
});

describe("다음에 이 낱말로 찾는 때 — 자동 받기 상태(frontend-2)", () => {
  it("자동 받기가 꺼진 곳(꺼 둠 · 키트)은 「내일 아침」이 아니라 「지금 받기」 · 모르면 단정하지 않음", () => {
    const off: CollectState = { kind: "off", text: "자동 받기 꺼 둠 — 목록은 10/27 07:30 그대로" };
    const kit: CollectState = { kind: "none", text: null };
    assert.equal(keywordNextCollect(off), "자동 받기가 꺼져 있어 「지금 받기」를 돌릴 때부터");
    assert.equal(keywordNextCollect(kit), "자동 받기가 꺼져 있어 「지금 받기」를 돌릴 때부터");
    assert.equal(keywordNextCollect({ kind: "missed", text: "오늘 목록을 아직 받지 않았습니다" }), "다음 자동 받기부터");
    assert.equal(keywordNextCollect(null), "다음 목록 받기부터");
    assert.equal(
      keywordSearchOffReason(off),
      "이 서버에서는 바로 찾기가 꺼져 있습니다 — 자동 받기가 꺼져 있어 「지금 받기」를 돌릴 때부터 이 낱말로 찾습니다",
    );
    assert.doesNotMatch(keywordSearchSummary(result({ found: 0, new_notices: 0, candidates: 0, low: 0 }), off), /내일 아침/);
  });

  it("패널 — 띠 · 사업기회가 자동 받기 상태를 넘기고, 패널 글에 「내일 아침」을 박아 두지 않는다", () => {
    const panelSrc = read("components", "opportunities", "CollectKeywordsPanel.tsx");
    assert.doesNotMatch(panelSrc, /내일 아침/);
    assert.match(panelSrc, /const next = keywordNextCollect\(collectState\);/);
    assert.match(read("components", "cosmos", "DayStrip.tsx"), /collectState=\{digest\?\.collect_state \?\? null\}/);
    assert.match(read("app", "opportunities", "page.tsx"), /collectState=\{unified\?\.collect_state \?\? null\}/);
    // 노트북 · 키트(direct)는 그 PC 의 백엔드 — 「이 서버 전체」라 하지 않는다
    assert.match(panelSrc, /const localPc = useDeploymentMode\(\)\?\.backend === "direct";/);
    assert.match(panelSrc, /이 PC 전체에 적용됩니다/);
  });
});

describe("결과 한 줄 · 결과 주소", () => {
  it("찾은 수 · 새 공고 · 후보 · 관련 낮음(접힘)", () => {
    assert.equal(keywordSearchSummary(result()), "「메타버스」로 7건 찾음 · 새 공고 5 · 후보 2 · 관련 낮음 3(접힘)");
    assert.equal(keywordSearchSummary(result({ low: 0 })), "「메타버스」로 7건 찾음 · 새 공고 5 · 후보 2 · 관련 낮음 0");
  });

  it("상한에서 잘렸으면 「일부만 받음」(숫자를 박지 않음 · 2.8.1) · 일부 기간 실패도 · 0건이면 없다고 적는다", () => {
    const cut = keywordSearchSummary(result({ found: 1346, truncated: true }));
    assert.match(cut, / · 너무 흔한 낱말이라 일부만 받음 — 나머지는 다음 자동 받기에서$/);
    assert.doesNotMatch(cut, /300건/, "7일 창으로 나눠 받아 받은 수가 300 을 넘을 수 있다 — 「1346건 찾음 … 300건까지만」처럼 어긋나지 않게");
    assert.match(keywordSearchSummary(result({ failed_calls: 2 })), / · 일부 기간\(2회\)을 받지 못했습니다 — 다음 받기에서 다시$/);
    assert.doesNotMatch(keywordSearchSummary(result({ failed_calls: 0 })), /받지 못했습니다/);
    assert.equal(
      keywordSearchSummary(result({ found: 0, new_notices: 0, candidates: 0, low: 0 }), ok),
      "「메타버스」로 찾은 공고가 없습니다 — 다음 자동 받기부터 이 낱말로 다시 찾습니다",
    );
  });

  it("사업기회 주소는 검색칸(q) · 나라장터 탭 · 불가 · 마감 포함(찾은 수 = 목록) — 모두 관련 낮음일 때만 접힌 것도 함께", () => {
    const plain = new URL(keywordResultHref(result({ word: "AI 교육" })), "http://x");
    assert.equal(plain.pathname, "/opportunities");
    assert.equal(plain.searchParams.get("q"), "AI 교육");
    assert.equal(plain.searchParams.get("src"), "g2b");
    assert.equal(plain.searchParams.get("unrelated"), null);
    // frontend-1 — 「n건 찾음」에는 참가 불가 · 실제 마감이 지난 공고도 든다. 기본으로 숨으면 찾은 수보다 적게 보였다.
    assert.equal(plain.searchParams.get("blocked"), "1");
    assert.equal(plain.searchParams.get("closed"), "1");
    const allLow = new URL(keywordResultHref(result({ candidates: 0, low: 4 })), "http://x");
    assert.equal(allLow.searchParams.get("unrelated"), "1");
    // 사업기회 화면이 읽는 주소 열쇠와 같아야 한다(parseParams 의 q · src · unrelated)
    const page = read("app", "opportunities", "page.tsx");
    assert.match(page, /q: p\.get\("q"\)/);
    assert.match(page, /unrelated: p\.get\("unrelated"\) === "1"/);
    assert.match(page, /blocked: p\.get\("blocked"\) === "1"/);
    assert.match(page, /closed: p\.get\("closed"\) === "1"/);
  });

  it("띄어쓰기 무시 — 「스마트팩토리」로 찾은 「스마트 팩토리 …」 공고도 검색칸에 걸린다(frontend-4)", () => {
    const hay = buildHaystack(["스마트 팩토리 실무교육", "광주광역시"]);
    assert.ok(matchesQuery(hay, "스마트팩토리"));
    assert.ok(matchesQuery(hay, "스마트 팩토리"));
    assert.ok(!matchesQuery(hay, "메타버스"));
  });
});

describe("입력 안내(서버 규칙의 사본)", () => {
  it("빈칸은 안내 없음 · 길이 2~20자 · 글자 종류", () => {
    assert.equal(keywordInputProblem("   ", state()), null);
    assert.equal(keywordInputProblem("메타버스", state()), null);
    assert.equal(keywordInputProblem("메", state()), "두 글자 이상 적으세요");
    assert.equal(keywordInputProblem("가".repeat(21), state()), "20자까지 적을 수 있습니다");
    assert.match(keywordInputProblem("AI!", state()) ?? "", /만 쓸 수 있습니다/);
    assert.equal(keywordInputProblem("Web 3.0", state()), null);
    assert.equal(keywordInputProblem("e-러닝", state()), null);
  });

  it("앞뒤 · 연속 공백을 다듬고 NFC 로 맞춘 뒤 잰다", () => {
    assert.equal(keywordInputProblem("  메타   버스  ", state()), null);
    assert.equal(keywordInputProblem("메타버스".normalize("NFD"), state()), null);
    assert.equal(keywordInputProblem(` ${"가".repeat(20)} `, state()), null);
  });

  it("기본 낱말 · 추가 낱말과 띄어쓰기 · 대소문자만 다르면 이미 있음", () => {
    assert.match(keywordInputProblem("전략수립", state()) ?? "", /이미 있는 낱말입니다\(「전략 수립」\)/);
    assert.match(keywordInputProblem("E-LEARNING", state()) ?? "", /이미 있는 낱말입니다\(「e-Learning」\)/);
    assert.match(keywordInputProblem("메타 버스", state({ extra: [entry("메타버스")] })) ?? "", /이미 있는 낱말입니다\(「메타버스」\)/);
  });

  it("추가 낱말이 다 찼으면 어떤 낱말이든 서버와 같은 문장", () => {
    const extra = Array.from({ length: 10 }, (_, i) => entry(`낱말${i}`));
    assert.equal(keywordInputProblem("메타버스", state({ extra })), "추가 낱말은 10개까지입니다 — 하나를 지운 뒤 더하세요");
  });
});

describe("네 호출 · 활동 기록 이름", () => {
  it("주소 · 방법 · 몸이 약속대로(처음 읽은 시각을 함께 보낸다)", async () => {
    const seen: { method: string; path: string; body: unknown }[] = [];
    const empty = state();
    globalThis.fetch = (async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input));
      seen.push({ method: init.method ?? "GET", path: url.pathname, body: init.body ? JSON.parse(String(init.body)) : null });
      const body = url.pathname === "/api/collect-keywords" && !init.method ? empty : { state: empty, search: null, search_error: null };
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch;
    await getCollectKeywords();
    await addCollectKeyword("메타버스", true, "2026-10-27T09:00:00+09:00");
    await searchCollectKeyword("메타버스");
    await removeCollectKeyword("메타버스", null);
    assert.deepEqual(seen, [
      { method: "GET", path: "/api/collect-keywords", body: null },
      { method: "POST", path: "/api/collect-keywords", body: { word: "메타버스", search: true, expected_updated_at: "2026-10-27T09:00:00+09:00" } },
      { method: "POST", path: "/api/collect-keywords/search", body: { word: "메타버스" } },
      { method: "POST", path: "/api/collect-keywords/remove", body: { word: "메타버스", expected_updated_at: null } },
    ]);
  });

  it("최근 활동 표에 「찾는 낱말 더함 · 지움 · 바로 찾기」", () => {
    const row = (path: string) => ({ ts: "2026-10-27T10:00:00Z", user: "hajin", role: "editor", method: "POST", path, organization_id: null, status: 200 }) as AuditLogEntry;
    assert.equal(actionLabel(row("/api/collect-keywords")), "찾는 낱말 더함");
    assert.equal(actionLabel(row("/api/collect-keywords/remove")), "찾는 낱말 지움");
    assert.equal(actionLabel(row("/api/collect-keywords/search")), "찾는 낱말 바로 찾기");
  });

  it("사건 줄(서버 `_audit_keyword`)이면 어떤 낱말 · 몇 건인지까지 — 지운 낱말은 여기에만 남는다(security-2)", () => {
    const ev = (path: string, event: AuditLogEntry["event"]) =>
      ({ ts: "2026-10-27T10:00:00Z", user: "hajin", role: "editor", method: "POST", path, organization_id: null, status: 200, event }) as AuditLogEntry;
    assert.equal(
      actionLabel(ev("/api/collect-keywords", { kind: "collect_keyword_add", word: "메타버스", found: 7, new: 5, search_error: null })),
      "찾는 낱말 더함 · 「메타버스」 · 7건 찾음(새 공고 5)",
    );
    assert.equal(
      actionLabel(ev("/api/collect-keywords", { kind: "collect_keyword_add", word: "메타버스", found: null, new: null, search_error: null })),
      "찾는 낱말 더함 · 「메타버스」",
    );
    assert.equal(
      actionLabel(
        ev("/api/collect-keywords/search", { kind: "collect_keyword_search", word: "메타버스", found: null, new: null, search_error: "아침 자동 받기가 도는 중입니다" }),
      ),
      "찾는 낱말 바로 찾기 · 「메타버스」 · 바로 찾기 못 함",
    );
    assert.equal(
      actionLabel(ev("/api/collect-keywords/remove", { kind: "collect_keyword_remove", word: "메타버스", found: null, new: null, search_error: null })),
      "찾는 낱말 지움 · 「메타버스」",
    );
    // 서버가 남기는 칸 이름과 같아야 한다(backend/app/api/insights.py `_audit_keyword`)
    const api = readFileSync(join(ROOT, "..", "backend", "app", "api", "insights.py"), "utf8");
    for (const kind of ["collect_keyword_add", "collect_keyword_remove", "collect_keyword_search"]) assert.ok(api.includes(`"${kind}"`), kind);
    for (const key of ['"word"', '"found"', '"new"', '"search_error"']) assert.ok(api.includes(key), key);
  });
});

describe("부품 · 배치", () => {
  const panel = () => read("components", "opportunities", "CollectKeywordsPanel.tsx");

  it("패널 — 읽는 중 · 못 읽음 · 비어 있음을 가르고, 지우기는 화면 안 확인 창 · 409 는 다시 불러오기 · 열람자는 보기만", () => {
    const src = panel();
    assert.match(src, /찾는 낱말을 읽는 중…/);
    assert.match(src, /describeFailure\(error, "찾는 낱말 목록을 읽지 못했습니다\."\)/);
    assert.match(src, /아직 더한 낱말이 없습니다\./);
    assert.match(src, /await requestConsent\(\{/);
    assert.doesNotMatch(src, /window\.confirm/);
    assert.match(src, /stale: isStaleWrite\(error\)/);
    assert.match(src, /다시 불러오기/);
    assert.match(src, /const viewer = useViewerLock\(\);/);
    assert.match(src, /\{viewer \? \(/);
    // 바로 찾기가 잠겼으면 저장만 보낸다(서버에 일부러 실패를 만들지 않음)
    assert.match(src, /addCollectKeyword\(clean, searchLock === null, state\.updated_at\)/);
    // security-4 — 길이는 다듬은(NFC) 뒤 keywordInputProblem 만 잰다. maxLength 는 정규화 전 글자 수로 잘라 맞는 낱말을 망쳤다.
    assert.doesNotMatch(src, /maxLength/);
    // frontend-7 — 더한 직후 못 찾았고 지금 다시 찾을 수 있으면 누를 곳(칩의 「다시 찾기」)을 적는다
    assert.match(src, /keywordSearchLock\(response\.state, viewer, collectState\) === null/);
    assert.match(src, /칩의 「다시 찾기」로 다시 찾을 수 있습니다/);
  });

  it("패널 안내 — 이 서버 전체 · 기업마당은 낱말과 상관없음 · 바로 찾기는 나라장터 입찰만 · 오늘 n/10 · 기본 낱말은 고칠 수 없음", () => {
    const src = panel();
    assert.match(src, /이 서버 전체에 적용됩니다/);
    assert.match(src, /기업마당은 전체를 받으므로 낱말과 상관없습니다\(관심 분야는/);
    assert.match(src, /\{SCREEN_NAMES\.company\} › 사업영역/);
    assert.match(src, /바로 찾기는 나라장터 입찰만 — 사전규격 · 발주계획 · 공고문은 \{next\} 함께 받습니다\./);
    assert.match(src, /바로 찾기 오늘 \{state\.searches_today\}\/\{state\.searches_limit\}/);
    assert.match(src, /기본 낱말 \{state\.base\.length\}개 보기\(고칠 수 없음\)/);
  });

  it("대시보드 — 쉬운 보기 · 전체 보기 둘 다의 「오늘 · 이번 주」 띠에 단추 · 새 공고가 있을 때만 고르기 칸 목록을 다시 받는다", () => {
    const strip = read("components", "cosmos", "DayStrip.tsx");
    assert.match(strip, /data-day-strip-keywords/);
    assert.match(strip, /<CollectKeywordsPanel/);
    assert.match(strip, /if \(result\.new_notices === 0\) return;\s*setDigestTick\(\(n\) => n \+ 1\);\s*onNoticesChanged\?\.\(\);/);
    assert.match(strip, /\{SCREEN_NAMES\.opportunities\}에서 결과 보기 →/);
    assert.match(strip, /href=\{keywordResultHref\(result\)\}/);
    const shell = read("components", "cosmos", "DashboardShell.tsx");
    assert.equal(shell.match(/<DayStrip organizationId=\{organizationId\} onNoticesChanged=\{onKeywordNotices\}>/g)?.length, 2);
    assert.match(shell, /const onKeywordNotices = \(\) => \{\s*dashboard\.reloadLists\(\);\s*setWeekTick\(\(n\) => n \+ 1\);/);
    // frontend-5 — 펼친 「이번 주 할 일」도 같이 다시 받는다(접힌 줄 숫자만 새로 세면 목록과 갈렸다)
    assert.equal(shell.match(/<ThisWeekPanel organizationId=\{organizationId\} reloadKey=\{weekTick\} \/>/g)?.length, 2);
    assert.match(read("components", "cosmos", "ThisWeekPanel.tsx"), /\}, \[organizationId, days, reloadKey\]\);/);
    // 목록만 다시 받기 — 분석을 처음부터 다시 그리는 reload 를 부르지 않는다
    const hook = read("lib", "cosmos", "useCosmosDashboard.ts");
    const body = hook.slice(hook.indexOf("const reloadLists = useCallback"), hook.indexOf("const reload = useCallback"));
    assert.match(body, /getProcurements\(\{ days: asked \}\)/);
    assert.match(body, /if \(listDaysRef\.current !== asked\) return;/);
    // frontend-6 — 통합 순위는 성공했을 때만 덮는다(pickerTick 을 올리면 실패가 오류 상태로 덮었다)
    assert.doesNotMatch(body, /setPickerTick/);
    assert.match(body, /sourceFailure\(response, "g2b"\) \|\| sourceFailure\(response, "bizinfo"\)\) return;/);
    assert.doesNotMatch(body, /fetchAll|setAnalysis|clearTimers|setLoad\(/);
  });

  it("사업기회 — 쉬운 보기 「더 보기 ⋯」와 전체 보기 도구모음(같은 단추 묶음) · 결과면 목록 다시 읽기 + 검색칸에 그 낱말 · 관련 낮음이 있으면 포함해서 보기", () => {
    const page = read("app", "opportunities", "page.tsx");
    const buttons = page.slice(page.indexOf("const recollectButtons = ("), page.indexOf("const keywordsPanel = "));
    assert.match(buttons, /data-collect-keywords-toggle/);
    assert.match(buttons, /if \(moreRef\.current\) moreRef\.current\.open = false;/);
    // frontend-3 — 「찾는 낱말」 단추는 잠김 사유 글 뒤(앞에 있으면 사유가 이 단추 설명처럼 읽혔다)
    assert.ok(buttons.indexOf('id="opp-recollect-reason"') < buttons.indexOf("data-collect-keywords-toggle"));
    // 단추 묶음은 쉬운 보기 메뉴 · 전체 보기 도구모음 두 곳에 놓인다
    assert.equal(page.match(/\{recollectButtons\}/g)?.length, 2);
    assert.equal(page.match(/\{keywordsPanel\}/g)?.length, 2);
    assert.match(page, /if \(result\.found === 0\) return;\s*reloadAll\(\);\s*setTab\("list"\);[\s\S]{0,240}setQuery\(result\.word\);/);
    // frontend-1 — 찾은 수 = 옮겨 간 목록: 참가 불가 · 실제 마감도 켠다
    assert.match(page, /setIncludeBlocked\(true\);\s*setIncludeClosed\(true\);\s*setQuery\(result\.word\);/);
    assert.match(page, /result\.low > 0 &&\s*!includeUnrelated && \(/);
    assert.match(page, /onClick=\{\(\) => setIncludeUnrelated\(true\)\}[^>]*>\s*관련 낮음 포함해서 보기/);
  });
});

describe("바로 찾기 문이 켜진 서버 — 같은 화면 글이 어긋나지 않게(frontend-3)", () => {
  it("재수집 잠김 사유는 「전체」 새로 받기 · 자료 상태 풀이는 바로 찾기 예외를 적는다", () => {
    assert.equal(RECOLLECT_LOCKED_REASON, "전체 새로 받기는 꺼져 있습니다(저장본만 씀)");
    assert.match(KEYWORD_SEARCH_EXCEPTION, /「찾는 낱말」의 바로 찾기/);
    const frozen = read("components", "ui", "FrozenNotice.tsx");
    assert.match(frozen, /\{keywordSearchLive && <p[^>]*>\{KEYWORD_SEARCH_EXCEPTION\}<\/p>\}/);
    const page = read("app", "opportunities", "page.tsx");
    assert.match(page, /keyword_search_live: healthResult\.value\.keyword_search_live/);
    assert.match(page, /keywordSearchLive=\{liveFlags\?\.keyword_search_live === true\}/);
    assert.match(page, /<FrozenNotice collectState=\{unified\?\.collect_state \?\? null\} keywordSearchLive=\{keywordSearchLive\} \/>/);
  });
});
