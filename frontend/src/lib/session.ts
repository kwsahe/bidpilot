/**
 * 서명된 세션 쿠키 — 만들기·검증, 그리고 백엔드로 보낼 신원 서명.
 *
 * 왜 서명인가
 * ----------
 * 예전 세션 쿠키는 `DEMO_USER`/`DEMO_PASSWORD` 에서 파생한 고정 해시 하나였다. 「맞는 값이냐」만
 * 물을 수 있었고 **누구로 들어왔는지**는 담기지 못했다. 개인 계정·역할이 생기면서 쿠키가
 * 신원을 실어 날라야 하는데, 신원을 그냥 담으면 브라우저에서 역할을 `admin` 으로 고쳐 쓸 수 있다.
 * 그래서 서버만 아는 키로 HMAC 서명을 붙이고, 들어올 때마다 다시 계산해 맞춰 본다.
 *
 * 왜 `crypto.subtle` 인가
 * ----------------------
 * 이 모듈은 `proxy.ts`(Edge 런타임)에서도 불린다. Edge 에는 Node 의 `crypto` 모듈이 없다.
 * 웹 표준 `crypto.subtle` 은 Edge·Node 양쪽에 있으므로 여기서만 쓴다.
 *
 * 이 파일은 **아무것도 import 하지 않는다.** 런타임 어디에서든 돌아야 하고, 서명·만료 검증을
 * 노드로 그대로 돌려 보며 확인할 수 있어야 하기 때문이다.
 *
 * 형식은 계약서(0917.md §4-5)가 정한 그대로다. 한 글자라도 바꾸면 백엔드 쪽 검증이 깨진다.
 *
 *     <payload_b64url>.<signature_b64url>
 *     payload   = {"u":"hong","r":"editor","n":"홍길동","exp":1790000000}   (exp 는 초 단위)
 *     signature = HMAC-SHA256(key = SESSION_SECRET, message = payload_b64url)
 *     base64url 은 패딩(`=`) 없음
 */

/** 화면 표시 전용 쿠키 (계약서 §8). httpOnly 가 아니며 **서버는 이 값을 믿지 않는다**. */
export const USER_COOKIE = "bidpilot_user";

/** 세션 유효기간 12시간. */
export const SESSION_TTL_SECONDS = 60 * 60 * 12;

/** 세션 서명 키를 `API_TOKEN` 에서 파생할 때 쓰는 고정 문자열. 계약서 §2. */
const DERIVATION_MESSAGE = "bidpilot-session-v1";

export const ROLES = ["viewer", "editor", "admin"] as const;
export type Role = (typeof ROLES)[number];

/** 쿠키에 담기는 값. 키 이름이 짧은 이유는 쿠키 길이를 줄이기 위해서다 (계약서 §2 고정). */
export interface SessionPayload {
  /** 계정 아이디 */
  u: string;
  /** 역할 */
  r: Role;
  /** 화면에 찍을 이름 */
  n: string;
  /** 만료 — 초 단위 UNIX epoch */
  exp: number;
}

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

/** 빈 문자열·공백만 있는 환경변수는 «없음»으로 본다 (Vercel 에서 빈 값으로 두는 실수 방지). */
function readEnv(name: string): string | null {
  const value = process.env[name];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

const encoder = new TextEncoder();

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value: string): Uint8Array | null {
  // base64url 문자만 허용한다. 점·패딩·공백이 섞여 있으면 우리 형식이 아니다.
  if (value.length === 0 || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  try {
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

function toHex(bytes: Uint8Array): string {
  let hex = "";
  for (let i = 0; i < bytes.length; i += 1) hex += bytes[i].toString(16).padStart(2, "0");
  return hex;
}

async function hmacSha256(secret: string, message: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret) as unknown as ArrayBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(message) as unknown as ArrayBuffer,
  );
  return new Uint8Array(signature);
}

/** 길이가 같은 문자열을 상수 시간에 비교한다 (타이밍 차이로 서명을 맞춰 가지 못하게). */
function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** 파생 키는 요청마다 다시 계산할 필요가 없다. 재료가 바뀌면 자동으로 다시 만든다. */
let derivedCache: { cacheKey: string; secret: string } | null = null;
let derivedWarned = false;

/**
 * 세션 서명 키.
 *
 * 1. `SESSION_SECRET` 이 있으면 그대로 쓴다.
 * 2. 없으면 `API_TOKEN` 에서 파생하고 **한 번만** 경고한다 (계약서 §2).
 * 3. 계약서에 없는 경우 하나 — 게이트(`DEMO_USER`/`DEMO_PASSWORD`)만 켜고 백엔드를 붙이지 않은
 *    배포다. 계약서는 「둘 다 없으면 게이트가 꺼진 상태」로 전제했지만 실제로는 이 조합이 가능하고,
 *    여기서 키를 못 만들면 **로그인이 통째로 막힌다**. 그래서 공용 계정 자격증명에서 파생한다.
 *    (예전 쿠키도 같은 재료에서 파생한 값이었다. 비밀 등급이 낮아지지 않는다.)
 * 4. 셋 다 없으면 게이트도 꺼진 상태다 — 세션을 만들지 않는다.
 */
async function sessionSecret(): Promise<string | null> {
  const explicit = readEnv("SESSION_SECRET");
  if (explicit !== null) return explicit;

  const token = readEnv("API_TOKEN");
  const demoUser = readEnv("DEMO_USER");
  const demoPassword = readEnv("DEMO_PASSWORD");

  // `keyMaterial` 은 HMAC 키 그 자체다 — 계약서 §2 가 「key = API_TOKEN」이라고 못 박았으므로
  // 여기에 접두어를 붙이면 안 된다. 접두어는 캐시 열쇠에만 붙여 두 경로를 구분한다.
  let keyMaterial: string;
  let cacheKey: string;
  if (token !== null) {
    keyMaterial = token;
    cacheKey = `token:${token}`;
  } else if (demoUser !== null && demoPassword !== null) {
    keyMaterial = `${demoUser}:${demoPassword}`;
    cacheKey = `demo:${demoUser}:${demoPassword}`;
  } else {
    return null;
  }

  if (!derivedWarned) {
    derivedWarned = true;
    // 어떤 환경변수가 없는지만 남긴다. 키 재료는 절대 로그에 쓰지 않는다.
    console.warn(
      `[session] SESSION_SECRET 이 없어 ${token !== null ? "API_TOKEN" : "DEMO_USER/DEMO_PASSWORD"} ` +
        "에서 서명 키를 파생합니다. 그 값이 바뀌면 이미 로그인한 사람은 다시 로그인해야 합니다.",
    );
  }

  if (derivedCache !== null && derivedCache.cacheKey === cacheKey) return derivedCache.secret;
  const secret = toHex(await hmacSha256(keyMaterial, DERIVATION_MESSAGE));
  derivedCache = { cacheKey, secret };
  return secret;
}

/** 서명 키가 있는가 — 세션을 만들 수 있는 상태인지 미리 볼 때 쓴다. */
export async function sessionSecretAvailable(): Promise<boolean> {
  return (await sessionSecret()) !== null;
}

/** 지금 시각 기준 만료 시각(초). */
export function sessionExpiry(ttlSeconds: number = SESSION_TTL_SECONDS, now: number = Date.now()): number {
  return Math.floor(now / 1000) + ttlSeconds;
}

/** 쿠키 값을 만든다. 서명 키가 없으면 null (게이트가 꺼진 상태). */
export async function signSession(payload: SessionPayload): Promise<string | null> {
  const secret = await sessionSecret();
  if (secret === null) return null;
  // 키 순서를 고정해 둔다 — 서명은 직렬화된 문자열 그대로를 대상으로 하므로 재현 가능해야 한다.
  const json = JSON.stringify({ u: payload.u, r: payload.r, n: payload.n, exp: payload.exp });
  const encoded = toBase64Url(encoder.encode(json));
  const signature = toBase64Url(await hmacSha256(secret, encoded));
  return `${encoded}.${signature}`;
}

/**
 * 쿠키 값을 검증한다. 서명이 틀리거나 만료됐으면 null — 부르는 쪽은 로그인 화면으로 보낸다.
 *
 * 예전 형식(점 없는 64자 hex)도 여기서 자연스럽게 null 이 된다. 이미 로그인해 둔 사람은
 * 한 번 다시 로그인한다 (계약서 §2).
 */
export async function verifySession(
  cookieValue: string | null | undefined,
  now: number = Date.now(),
): Promise<SessionPayload | null> {
  if (typeof cookieValue !== "string" || cookieValue.length === 0) return null;

  const parts = cookieValue.split(".");
  if (parts.length !== 2) return null;
  const [encoded, signature] = parts;

  const secret = await sessionSecret();
  if (secret === null) return null;

  const expected = toBase64Url(await hmacSha256(secret, encoded));
  if (!constantTimeEqual(signature, expected)) return null;

  const bytes = fromBase64Url(encoded);
  if (bytes === null) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object") return null;

  const record = parsed as Record<string, unknown>;
  const user = typeof record.u === "string" ? record.u.trim() : "";
  const role = record.r;
  const exp = record.exp;
  if (user.length === 0 || !isRole(role)) return null;
  if (typeof exp !== "number" || !Number.isFinite(exp)) return null;
  // 서명이 맞아도 기한이 지났으면 무효다 (서명 키가 새지 않아도 쿠키 수명은 끝난다).
  if (exp * 1000 <= now) return null;

  const name = typeof record.n === "string" && record.n.trim().length > 0 ? record.n : user;
  return { u: user, r: role, n: name, exp };
}

/** 세션 쿠키에 붙일 옵션. httpOnly 라 브라우저 스크립트가 읽지 못한다. */
export function sessionCookieOptions(maxAge: number = SESSION_TTL_SECONDS) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}

/**
 * 표시 전용 쿠키 옵션 (계약서 §8). 세션 쿠키와 만료가 같고 `httpOnly` 만 다르다.
 * 화면이 「누구로 로그인했는지」를 찍기 위한 것뿐이며, 권한 판정에는 절대 쓰지 않는다.
 */
export function userCookieOptions(maxAge: number = SESSION_TTL_SECONDS) {
  return {
    httpOnly: false,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}

/**
 * 표시 전용 쿠키의 값.
 *
 * 계약서 §8 이 말하는 쿠키 값은 `encodeURIComponent(JSON.stringify({u,r,n}))` 다.
 * Next 의 `cookies.set()` 이 값을 저장할 때 `encodeURIComponent` 를 **직접 걸어 준다**
 * (`@edge-runtime/cookies` 의 `stringifyCookie`). 그래서 여기서는 JSON 문자열만 넘긴다 —
 * 우리가 한 번 더 감싸면 브라우저에는 두 번 인코딩된 값이 저장돼 화면이 이름을 못 읽는다.
 */
export function userCookieValue(payload: Pick<SessionPayload, "u" | "r" | "n"> & { exp?: number }): string {
  // 43차 M28 — 만료 시각(`e`, 초)을 함께 싣는다. 화면이 「5분 안에 끝납니다」를 미리 알리려고 읽을 뿐 · 서버는 이 값을 믿지 않는다.
  return JSON.stringify({ u: payload.u, r: payload.r, n: payload.n, ...(payload.exp ? { e: payload.exp } : {}) });
}

/** 쿠키 헤더 한 줄에서 이름 하나를 꺼낸다 (NextRequest 가 아닌 평범한 Request 용). */
export function readCookie(header: string | null | undefined, name: string): string | null {
  if (typeof header !== "string" || header.length === 0) return null;
  for (const pair of header.split(";")) {
    const index = pair.indexOf("=");
    if (index === -1) continue;
    if (pair.slice(0, index).trim() !== name) continue;
    const raw = pair.slice(index + 1).trim();
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  return null;
}

/**
 * 백엔드로 신원을 넘길 때 붙이는 서명 (계약서 §3).
 *
 * 입력 문자열은 **정확히** `{user}\n{role}` 이고 키는 `API_TOKEN` 의 UTF-8 바이트다.
 * 백엔드가 같은 계산을 다시 해 맞춰 본다 — 토큰을 모르면 헤더를 위조하지 못한다.
 */
export async function identitySignature(token: string, user: string, role: string): Promise<string> {
  return toHex(await hmacSha256(token, `${user}\n${role}`));
}

/**
 * 헤더 값으로 그대로 실어도 되는 문자열인가.
 *
 * HTTP 헤더는 ASCII 만 담는다. 한글 아이디를 그대로 넣으면 fetch 가 예외를 던지고, 퍼센트
 * 인코딩해서 넣으면 백엔드가 계산하는 서명 대상과 달라져 401 이 된다. 그래서 여기서 걸러
 * 부르는 쪽이 「조용히 관리자 권한으로 넘어가는」 일 없이 멈추게 한다.
 */
export function headerSafe(value: string): boolean {
  return /^[\x21-\x7e]+$/.test(value);
}
