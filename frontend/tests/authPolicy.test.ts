/**
 * 인증 판정 표 — S1·S4 가 다시 열리지 않게 고정한다.
 *
 * 실행: `npm test` (frontend 폴더에서). Node 22 가 `.ts` 를 그대로 돌린다 —
 * 새 의존성을 넣지 않으려고 이렇게 했다(vitest·jest 없음, `node --test` 만 쓴다).
 *
 * 검수(`docs/reports/2026-09-18_qa_recheck3.md` §3-A)가 지적한 대로, 이 두 경로에는
 * 테스트가 하나도 없었다. 둘 다 **조용한 권한 상승**이라 화면에서는 보이지 않는다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  canFallBackToSharedAccount,
  decideLogin,
  identityKind,
  relayWithoutGate,
  safeNextPath,
  type Deployment,
  type LookupKind,
} from "../src/lib/authPolicy.ts";

const SNAPSHOT: Deployment = { proxy: false, requireAuth: false };
const RELAY: Deployment = { proxy: true, requireAuth: false };
const REAL_DATA: Deployment = { proxy: false, requireAuth: true };
const RELAY_REAL: Deployment = { proxy: true, requireAuth: true };

// ---------------------------------------------------------------------------
// S4 — 공용 계정 되돌림 매트릭스
// ---------------------------------------------------------------------------

test("되돌림은 스냅샷 배포에서만 허용된다", () => {
  assert.equal(canFallBackToSharedAccount(SNAPSHOT), true);
  assert.equal(canFallBackToSharedAccount(RELAY), false);
  assert.equal(canFallBackToSharedAccount(REAL_DATA), false);
  assert.equal(canFallBackToSharedAccount(RELAY_REAL), false);
});

test("로그인 판정 매트릭스", () => {
  const cases: Array<[LookupKind, boolean, Deployment, string]> = [
    // 백엔드가 계정을 줬으면 언제나 그 계정이다.
    ["account", false, RELAY, "personal"],
    ["account", true, RELAY, "personal"],
    ["account", true, SNAPSHOT, "personal"],

    // **거절은 최종이다.** 공용 비밀번호가 맞아도 되돌아가지 않는다 —
    // 이것이 검수에서 재현된 권한 상승의 본체다.
    ["rejected", true, RELAY, "reject"],
    ["rejected", true, SNAPSHOT, "reject"],
    ["rejected", false, RELAY, "reject"],

    // 백엔드가 답을 못 줬다: 중계 배포에서는 **열지 않고 닫는다** (S4).
    ["unavailable", true, RELAY, "unavailable"],
    ["unavailable", true, REAL_DATA, "unavailable"],
    ["unavailable", true, RELAY_REAL, "unavailable"],
    // 스냅샷 배포에는 물어볼 백엔드가 없다 — 공용 계정이 유일한 신원이다.
    ["unavailable", true, SNAPSHOT, "shared"],
    ["unavailable", false, SNAPSHOT, "unavailable"],

    // 물어보지 않았다(중계가 꺼져 있다).
    ["skipped", true, SNAPSHOT, "shared"],
    ["skipped", false, SNAPSHOT, "reject"],
    // 중계가 켜져 있는데 skipped 면 아이디·비밀번호가 비어 있었던 것이다.
    ["skipped", true, RELAY, "reject"],
  ];
  for (const [lookup, shared, deployment, expected] of cases) {
    assert.equal(
      decideLogin(lookup, shared, deployment),
      expected,
      `${lookup} · 공용일치=${shared} · proxy=${deployment.proxy} requireAuth=${deployment.requireAuth}`,
    );
  }
});

test("백엔드가 죽었다고 공용 비밀번호로 관리자가 되지 않는다 (S4 회귀)", () => {
  // 검수가 재현한 경로: users.json 의 `hong` 은 열람자인데 DEMO_USER 도 `hong` 이다.
  // 백엔드를 잠시 멈추면 예전에는 공용 비밀번호로 **관리자** 세션이 나왔다.
  assert.equal(decideLogin("unavailable", true, RELAY), "unavailable");
});

// ---------------------------------------------------------------------------
// S1 — 세션 없는 요청을 백엔드로 보내지 않는다
// ---------------------------------------------------------------------------

test("토큰이 있는데 세션이 없으면 anonymous — 보내면 안 된다", () => {
  assert.equal(identityKind({ hasToken: true, hasSession: false, headerSafe: false }), "anonymous");
  assert.equal(identityKind({ hasToken: true, hasSession: false, headerSafe: true }), "anonymous");
});

test("토큰이 아예 없으면 none — 인증이 꺼진 로컬이다", () => {
  assert.equal(identityKind({ hasToken: false, hasSession: false, headerSafe: false }), "none");
  assert.equal(identityKind({ hasToken: false, hasSession: true, headerSafe: true }), "none");
});

test("아이디를 헤더에 못 실으면 unsafe — 헤더만 빼고 보내면 관리자가 된다", () => {
  assert.equal(identityKind({ hasToken: true, hasSession: true, headerSafe: false }), "unsafe");
});

test("세션이 있고 헤더에 실을 수 있으면 signed", () => {
  assert.equal(identityKind({ hasToken: true, hasSession: true, headerSafe: true }), "signed");
});

test("중계 + 토큰 + 게이트 꺼짐은 막는다 (S1)", () => {
  assert.equal(relayWithoutGate({ proxy: true, apiToken: true, gate: false }), true);
  // 하나라도 빠지면 그 조합이 아니다.
  assert.equal(relayWithoutGate({ proxy: true, apiToken: true, gate: true }), false);
  assert.equal(relayWithoutGate({ proxy: true, apiToken: false, gate: false }), false);
  assert.equal(relayWithoutGate({ proxy: false, apiToken: true, gate: false }), false);
});

// ---------------------------------------------------------------------------
// S11 — 주소 단위 로그인 제한
// ---------------------------------------------------------------------------

const { MAX_ATTEMPTS, WINDOW_MS, clientKey, noteAttempt, clearAttempts, resetAll } = await import(
  "../src/lib/loginThrottle.ts"
);

test("한 주소는 창 안에서 정해진 횟수까지만 시도할 수 있다", () => {
  resetAll();
  const now = 1_000_000;
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) {
    assert.equal(noteAttempt("1.2.3.4", now + i).limited, false, `${i + 1}번째는 통과해야 한다`);
  }
  const over = noteAttempt("1.2.3.4", now + MAX_ATTEMPTS);
  assert.equal(over.limited, true);
  assert.ok(over.retryAfterSeconds > 0, "다시 시도할 시각을 알려줘야 한다");
});

test("창이 지나면 다시 센다", () => {
  resetAll();
  const now = 2_000_000;
  for (let i = 0; i <= MAX_ATTEMPTS; i += 1) noteAttempt("5.6.7.8", now);
  assert.equal(noteAttempt("5.6.7.8", now).limited, true);
  assert.equal(noteAttempt("5.6.7.8", now + WINDOW_MS).limited, false);
});

test("성공하면 그 주소의 기록을 지운다", () => {
  resetAll();
  const now = 3_000_000;
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) noteAttempt("9.9.9.9", now);
  clearAttempts("9.9.9.9");
  assert.equal(noteAttempt("9.9.9.9", now).limited, false);
});

test("주소가 다르면 서로 막지 않는다", () => {
  resetAll();
  const now = 4_000_000;
  for (let i = 0; i <= MAX_ATTEMPTS; i += 1) noteAttempt("10.0.0.1", now);
  assert.equal(noteAttempt("10.0.0.1", now).limited, true);
  assert.equal(noteAttempt("10.0.0.2", now).limited, false);
});

test("주소 헤더에서 셀 기준을 뽑는다", () => {
  // 맨 «뒤» 값이다 (N2). 앞쪽은 클라이언트가 지어낼 수 있다.
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "203.0.113.5, 10.0.0.1" })), "10.0.0.1");
  assert.equal(clientKey(new Headers({ "x-real-ip": "203.0.113.9" })), "203.0.113.9");
  // 헤더가 없으면 한 덩어리로 묶는다 — 사실상 전역 제한이지만 없는 것보다 낫다.
  assert.equal(clientKey(new Headers()), "unknown");
  // 사용자가 정하는 값이라 길이를 자른다.
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "x".repeat(200) })).length, 64);
});

// ---------------------------------------------------------------------------
// S7 — 게이트 없이 열리는 경로는 «정확히 일치»할 때만
// ---------------------------------------------------------------------------

const { PUBLIC_PATHS, isPublicPath } = await import("../src/lib/demoAuth.ts");

test("공개 경로는 정확히 일치할 때만 통과한다 (S7 회귀)", () => {
  for (const p of PUBLIC_PATHS) assert.equal(isPublicPath(p), true, p);
  // 예전에는 접두사로 봤다 — `/api/login/아무거나` 가 게이트를 지나 catch-all 중계로 갔고,
  // 중계는 토큰을 붙여 보냈다. 신원 헤더가 없으니 백엔드는 그것을 관리자로 봤다.
  for (const bad of [
    "/api/login/x",
    "/api/login/",
    "/api/logout/x",
    "/login/x",
    "/api/loginx",
    "/api/organizations",
    "/health/x",
    "/api/health",
    "/",
    "",
  ]) {
    assert.equal(isPublicPath(bad), false, `막았어야 한다: ${bad}`);
  }
});

const { publicHealth } = await import("../src/lib/publicHealth.ts");

test("로그인 밖 /health 는 판 · 규칙 판 · ok 만 싣는다 (42차)", () => {
  const backend = {
    status: "ok", version: "1.5.0", rules_version: 77, service: "bidpilot-api", g2b_api_configured: true,
    default_organization_id: "org-x", llm_model: "m", auth_required: true, plan_writer_cli: true,
  };
  assert.deepEqual(publicHealth(backend), { status: "ok", version: "1.5.0", rules_version: 77 });
  assert.deepEqual(publicHealth(null), { status: "down", version: null, rules_version: null });
  assert.equal(publicHealth({ status: "degraded" }).status, "down");
});

// ---------------------------------------------------------------------------
// N2 — 주소는 프록시가 덧붙인 «마지막» 홉을 쓴다
// ---------------------------------------------------------------------------

test("x-forwarded-for 는 마지막 홉을 쓴다 — 앞쪽은 클라이언트가 지어낼 수 있다", () => {
  // 클라이언트가 앞에 아무 값이나 끼워 넣어도, 우리가 세는 값은 프록시가 붙인 마지막 홉이다.
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "1.1.1.1, 203.0.113.7" })), "203.0.113.7");
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "not-an-ip, 203.0.113.7" })), "203.0.113.7");
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "203.0.113.7" })), "203.0.113.7");
  // 빈 칸이 섞여도 흔들리지 않는다.
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "1.1.1.1, , 203.0.113.7 " })), "203.0.113.7");
});

test("주소를 바꿔 가며 표를 넘치게 해도 잠긴 주소가 풀리지 않는다", () => {
  resetAll();
  const now = 5_000_000;
  // 먼저 한 주소를 잠근다.
  for (let i = 0; i <= MAX_ATTEMPTS; i += 1) noteAttempt("victim", now);
  assert.equal(noteAttempt("victim", now).limited, true);
  // 그다음 서로 다른 주소를 잔뜩 보내 표를 넘치게 한다. 예전에는 여기서 전원 초기화됐다.
  for (let i = 0; i < 3000; i += 1) noteAttempt(`flood-${i}`, now + 1);
  assert.equal(noteAttempt("victim", now + 1).limited, true, "표를 넘치게 해서 제한이 풀렸다");
});

test("로그인 뒤 갈 주소는 이 사이트 안의 경로만 (CMN-03 · 열린 이동)", () => {
  assert.equal(safeNextPath("/rfp?notice=g2b-1"), "/rfp?notice=g2b-1");
  assert.equal(safeNextPath("https://example.com"), "/");
  assert.equal(safeNextPath("//example.com"), "/");
  assert.equal(safeNextPath("/\\example.com"), "/");
  assert.equal(safeNextPath(null), "/");
  assert.equal(safeNextPath(""), "/");
});

test("탭 · 줄바꿈 · 백슬래시를 끼운 주소도 바깥으로 보내지 않는다 (CMN-03 우회)", () => {
  // 주소 해석이 탭 · 줄바꿈을 지워 `//example.com` 이 된다 — 앞자리 검사만 하던 옛 코드는 그대로 통과시켰다.
  assert.equal(safeNextPath("/\t/example.com"), "/");
  assert.equal(safeNextPath("/\n/example.com"), "/");
  assert.equal(safeNextPath("/a\\..\\\\example.com"), "/");
  // 이 사이트 경로는 그대로.
  assert.equal(safeNextPath("/opportunities?mode=full#top"), "/opportunities?mode=full#top");
});
