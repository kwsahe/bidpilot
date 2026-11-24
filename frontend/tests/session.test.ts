/**
 * 세션 쿠키 — 만료·변조·형식을 고정한다.
 *
 * 이 쿠키가 **유일한 신원**이다. 중계는 여기서 꺼낸 아이디·역할을 서명해 백엔드로 넘기고,
 * 백엔드는 그 역할 그대로 권한을 판정한다. 그런데 검수 시점까지 테스트가 하나도 없었다.
 *
 * `session.ts` 는 아무것도 import 하지 않는다(그렇게 만들어 두었다). 그래서 Next 런타임
 * 없이 그대로 불러 검사할 수 있다.
 */

import { test, before } from "node:test";
import assert from "node:assert/strict";

import {
  SESSION_TTL_SECONDS,
  isRole,
  readCookie,
  headerSafe,
  identitySignature,
  sessionCookieOptions,
  sessionExpiry,
  signSession,
  userCookieValue,
  verifySession,
} from "../src/lib/session.ts";

before(() => {
  // 서명 키. 실제 값이 아니라 이 테스트에서만 쓰는 문자열이다.
  process.env.SESSION_SECRET = "test-session-secret-0918";
});

const PAYLOAD = { u: "hong", r: "viewer" as const, n: "홍길동" };

test("구운 세션은 그대로 되읽힌다", async () => {
  const value = await signSession({ ...PAYLOAD, exp: sessionExpiry() });
  assert.ok(value, "서명에 실패했다");
  const session = await verifySession(value);
  assert.deepEqual(session && { u: session.u, r: session.r, n: session.n }, PAYLOAD);
});

test("만료된 세션은 거절한다", async () => {
  const expired = await signSession({ ...PAYLOAD, exp: Math.floor(Date.now() / 1000) - 1 });
  assert.ok(expired);
  assert.equal(await verifySession(expired), null);
});

test("본문을 한 글자만 바꿔도 거절한다 — 서명을 먼저 본다", async () => {
  const value = await signSession({ ...PAYLOAD, exp: sessionExpiry() });
  assert.ok(value);
  const [payload, signature] = value.split(".");
  // 역할을 admin 으로 올린 본문을 만들어 **원래 서명**과 붙여 본다.
  const forged = Buffer.from(JSON.stringify({ ...PAYLOAD, r: "admin", exp: sessionExpiry() }))
    .toString("base64url");
  assert.notEqual(forged, payload);
  assert.equal(await verifySession(`${forged}.${signature}`), null);
});

test("서명을 바꿔도 거절한다", async () => {
  const value = await signSession({ ...PAYLOAD, exp: sessionExpiry() });
  assert.ok(value);
  const [payload, signature] = value.split(".");
  const flipped = signature.slice(0, -1) + (signature.endsWith("a") ? "b" : "a");
  assert.equal(await verifySession(`${payload}.${flipped}`), null);
});

test("모양이 아닌 값은 전부 거절한다 (옛 형식 쿠키 포함)", async () => {
  for (const bad of [
    undefined,
    "",
    "점이없는hex값",
    "a.b.c",
    ".",
    "only.",
    ".onlysig",
    "!!!.!!!",
  ]) {
    assert.equal(await verifySession(bad), null, `거절했어야 한다: ${String(bad)}`);
  }
});

test("모르는 역할은 거절한다 — 낮은 권한으로 낮추지 않는다", async () => {
  // 역할이 셋 중 하나가 아니면 통째로 무효다. 오타가 조용히 권한을 바꾸는 것보다 낫다.
  const value = await signSession({ u: "x", r: "superuser" as never, n: "x", exp: sessionExpiry() });
  if (value !== null) assert.equal(await verifySession(value), null);
  assert.equal(isRole("superuser"), false);
  assert.equal(isRole("admin"), true);
});

test("서명 키가 없으면 굽지도 읽지도 않는다", async () => {
  const saved = process.env.SESSION_SECRET;
  const savedToken = process.env.API_TOKEN;
  const savedUser = process.env.DEMO_USER;
  const savedPassword = process.env.DEMO_PASSWORD;
  delete process.env.SESSION_SECRET;
  delete process.env.API_TOKEN;
  delete process.env.DEMO_USER;
  delete process.env.DEMO_PASSWORD;
  try {
    assert.equal(await signSession({ ...PAYLOAD, exp: sessionExpiry() }), null);
  } finally {
    if (saved !== undefined) process.env.SESSION_SECRET = saved;
    if (savedToken !== undefined) process.env.API_TOKEN = savedToken;
    if (savedUser !== undefined) process.env.DEMO_USER = savedUser;
    if (savedPassword !== undefined) process.env.DEMO_PASSWORD = savedPassword;
  }
});

test("쿠키는 httpOnly 이고 SameSite=Lax 다", () => {
  const options = sessionCookieOptions(SESSION_TTL_SECONDS);
  assert.equal(options.httpOnly, true);
  assert.equal(options.sameSite, "lax");
  assert.equal(options.path, "/");
});

test("헤더에 실을 수 없는 아이디를 걸러낸다", () => {
  assert.equal(headerSafe("hong"), true);
  assert.equal(headerSafe("hong.gil-dong_1"), true);
  assert.equal(headerSafe("홍길동"), false);
  assert.equal(headerSafe("a\nb"), false);
  assert.equal(headerSafe(""), false);
});

test("신원 서명은 토큰·아이디·역할 중 하나만 달라도 달라진다", async () => {
  const base = await identitySignature("tok", "hong", "viewer");
  assert.match(base, /^[0-9a-f]{64}$/);
  assert.notEqual(base, await identitySignature("tok", "hong", "admin"));
  assert.notEqual(base, await identitySignature("tok", "kim", "viewer"));
  assert.notEqual(base, await identitySignature("tok2", "hong", "viewer"));
  // 같은 입력이면 같은 값이어야 백엔드와 맞는다.
  assert.equal(base, await identitySignature("tok", "hong", "viewer"));
});

test("쿠키 헤더에서 이름이 겹치는 값을 잘못 집지 않는다", () => {
  const header = "other_session=xxx; bidpilot_demo_session=abc.def; x=1";
  assert.equal(readCookie(header, "bidpilot_demo_session"), "abc.def");
  assert.equal(readCookie(header, "session"), null);
  assert.equal(readCookie(null, "bidpilot_demo_session"), null);
});

test("표시 전용 쿠키에는 서명이 들어가지 않는다", () => {
  const value = userCookieValue(PAYLOAD);
  assert.ok(!value.includes("."), "표시 쿠키에 서명 형식이 섞였다");
});
