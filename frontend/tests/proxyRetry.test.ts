/**
 * 10-31 최종 점검 — 백엔드가 쉬던 연결을 막 닫은 순간 다시 쓰면 UND_ERR_SOCKET · ECONNRESET 로 끊겨 목록이 502 였다.
 * 읽기(GET · HEAD)만 한 번 더 보내고, 쓰기는 다시 보내지 않는다(두 번 처리될 수 있음).
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/proxyRetry.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

process.env.BACKEND_URL = "http://backend.test";
delete process.env.API_TOKEN;
const { forward } = await import("../src/lib/backendProxy.ts");

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function cut(code: string): TypeError {
  const error = new TypeError("fetch failed");
  (error as TypeError & { cause?: unknown }).cause = { code };
  return error;
}

function fakeFetch(failures: unknown[]): { calls: () => number } {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    const failure = failures.shift();
    if (failure) throw failure;
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  return { calls: () => calls };
}

test("읽기는 끊긴 연결(UND_ERR_SOCKET · ECONNRESET)이면 한 번 더 보내 받는다", async () => {
  for (const code of ["UND_ERR_SOCKET", "ECONNRESET"]) {
    const fake = fakeFetch([cut(code)]);
    const res = await forward(new Request("http://app.test/api/procurements"), "/api/procurements");
    assert.equal(res.status, 200, code);
    assert.equal(fake.calls(), 2, code);
  }
});

test("쓰기는 끊겨도 다시 보내지 않는다 · 다른 실패와 두 번째도 끊기면 502", async () => {
  const post = fakeFetch([cut("UND_ERR_SOCKET")]);
  const res = await forward(new Request("http://app.test/api/decisions", { method: "POST", body: "{}" }), "/api/decisions");
  assert.equal(res.status, 502);
  assert.equal(post.calls(), 1);

  const refused = fakeFetch([cut("ECONNREFUSED")]);
  assert.equal((await forward(new Request("http://app.test/api/x"), "/api/x")).status, 502);
  assert.equal(refused.calls(), 1);

  const twice = fakeFetch([cut("ECONNRESET"), cut("ECONNRESET")]);
  assert.equal((await forward(new Request("http://app.test/api/x"), "/api/x")).status, 502);
  assert.equal(twice.calls(), 2);
});
