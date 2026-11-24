/**
 * 백엔드 중계(프록시) — **서버 전용 모듈**. 클라이언트 컴포넌트에서 import 하지 마라.
 *
 * 사내 배포에서는 브라우저가 FastAPI 백엔드를 직접 부르지 않는다.
 * 백엔드에는 아직 자체 인증이 없어서 주소만 알면 회사자료를 읽고 쓸 수 있기 때문이다.
 * 그래서 다음 구조로 간다.
 *
 *   브라우저 → (로그인 게이트를 통과한) Next.js 라우트 핸들러 → 백엔드
 *
 * - 백엔드 주소는 `BACKEND_URL` (서버 전용, `NEXT_PUBLIC_` 아님) 에서만 읽는다.
 *   `NEXT_PUBLIC_` 접두사를 붙이면 값이 브라우저 번들에 박혀서 내부 주소가 그대로 공개된다.
 * - `API_TOKEN` 이 있으면 `Authorization` 헤더를 **여기 서버에서** 붙인다. 토큰은 브라우저로 내려가지 않는다.
 * - 브라우저 쿠키(로그인 세션)는 백엔드로 넘기지 않는다. 백엔드가 알 필요가 없다.
 *   대신 세션에서 **누구인지만** 꺼내 서명된 헤더 세 개로 넘긴다 (계약서 §3).
 *   쿠키를 그대로 넘기지 않는 이유는 그대로다 — 백엔드는 쿠키를 해석하지 않고, 넘길수록 샐 곳만 는다.
 */
import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/demoAuth";
import { headerSafe, identitySignature, readCookie, verifySession, type Role } from "@/lib/session";
import { identityKind } from "@/lib/authPolicy";

/** 백엔드로 그대로 넘길 요청 헤더. 나머지(쿠키·호스트·인증 헤더 등)는 버린다. */
const FORWARD_REQUEST_HEADERS = ["content-type", "accept"] as const;

/**
 * 브라우저로 돌려줄 응답 헤더.
 * 파일 내려받기(제안서 docx/pdf, Gold JSON)를 위해 `content-disposition` 을 반드시 보존한다.
 *
 * `content-length` 는 일부러 뺀다 — fetch 가 gzip 응답을 이미 풀어 준 경우 원래 길이와 어긋나
 * 브라우저가 본문을 잘라 버린다. 길이를 지우면 청크 전송으로 넘어가 안전하다.
 */
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "cache-control",
  "etag",
  "last-modified",
  "location",
] as const;

/** Node fetch 는 스트림 본문을 보낼 때 `duplex: "half"` 를 요구한다. 표준 타입에는 아직 없다. */
type ProxyRequestInit = RequestInit & { duplex?: "half" };

/** 빈 문자열·공백만 있는 환경변수는 «없음»으로 본다 (Vercel 에서 빈 값으로 남겨 두는 실수 방지). */
function readServerEnv(name: string): string | null {
  const value = process.env[name];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** 호스팅된 백엔드 주소. 설정하지 않았으면 null (= 중계하지 않음). */
export function backendUrl(): string | null {
  const raw = readServerEnv("BACKEND_URL");
  if (raw === null) return null;
  // 뒤 슬래시를 떼서 `${base}/api/...` 가 항상 한 겹으로 이어지게 한다.
  return raw.replace(/\/+$/, "");
}

/** 이 배포본이 백엔드를 중계하는가. 꺼져 있으면 라우트는 기존 스냅샷 동작을 그대로 쓴다. */
export function proxyEnabled(): boolean {
  return backendUrl() !== null;
}

/** 백엔드 토큰이 설정돼 있는가. **값은 절대 내보내지 않는다** — 있는지만 알린다. */
export function apiTokenSet(): boolean {
  return readServerEnv("API_TOKEN") !== null;
}

/**
 * 연결 실패 사유를 안전한 코드 문자열로만 뽑는다.
 * 내부 주소·토큰이 섞인 원본 메시지는 절대 밖으로 내보내지 않는다.
 */
/** 끊긴 연결 — 같은 읽기 요청을 한 번 더 보내도 되는 사유(백엔드가 쉬던 연결을 닫은 경우). */
const RETRYABLE_CODES: ReadonlySet<string> = new Set(["UND_ERR_SOCKET", "ECONNRESET"]);

function failureCode(error: unknown): string {
  const cause = error instanceof Error ? (error as { cause?: unknown }).cause : undefined;
  if (cause !== null && typeof cause === "object" && "code" in cause) {
    const code = (cause as { code?: unknown }).code;
    if (typeof code === "string" && /^[A-Z0-9_]{1,32}$/.test(code)) return code;
  }
  return "UNREACHABLE";
}

/**
 * 요청에 실린 세션에서 백엔드로 넘길 신원을 뽑는다 (계약서 §3).
 *
 * - 토큰이 없으면(로컬 개발) `none` — 백엔드도 아무것도 막지 않는 상태다.
 * - 세션이 없거나 서명이 틀리면 `none` — 게이트가 꺼진 배포거나 스크립트 호출이다.
 * - 아이디를 헤더에 실을 수 없으면 `unsafe`. 이때 **헤더만 빼고 보내면 안 된다** —
 *   백엔드는 헤더가 하나도 없는 요청을 「토큰을 쥔 관리자」로 보기 때문에(계약서 §4-3),
 *   열람 권한만 있는 사람이 조용히 관리자 권한으로 넘어간다.
 */
type Identity =
  | { kind: "none" }
  | { kind: "signed"; user: string; role: Role; signature: string }
  | { kind: "anonymous" }
  | { kind: "unsafe" };

async function identityFrom(source: Headers, token: string | null): Promise<Identity> {
  const session =
    token === null ? null : await verifySession(readCookie(source.get("cookie"), SESSION_COOKIE));
  // 판정 규칙 자체는 `authPolicy.identityKind` 에 있다 — 표로 두드려 검사하기 위해서다.
  const kind = identityKind({
    hasToken: token !== null,
    hasSession: session !== null,
    headerSafe: session !== null && headerSafe(session.u) && headerSafe(session.r),
  });
  if (kind !== "signed") return { kind };
  // `signed` 면 위 판정이 세션과 토큰이 둘 다 있음을 이미 보장한다.
  return {
    kind: "signed",
    user: session!.u,
    role: session!.r,
    signature: await identitySignature(token!, session!.u, session!.r),
  };
}

/** 백엔드로 보낼 헤더를 만든다 — 필요한 것만, 그리고 토큰·신원 서명은 서버에서만 붙인다. */
function buildRequestHeaders(source: Headers, token: string | null, identity: Identity): Headers {
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = source.get(name);
    if (value !== null) headers.set(name, value);
  }
  if (token !== null) headers.set("authorization", `Bearer ${token}`);
  if (identity.kind === "signed") {
    headers.set("x-user", identity.user);
    headers.set("x-user-role", identity.role);
    headers.set("x-user-signature", identity.signature);
  }
  return headers;
}

/** 백엔드 응답 헤더 중 브라우저에 필요한 것만 골라 옮긴다. */
function buildResponseHeaders(source: Headers): Headers {
  const headers = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = source.get(name);
    if (value !== null) headers.set(name, value);
  }
  return headers;
}

/**
 * 요청을 백엔드로 그대로 전달한다.
 *
 * @param request 들어온 요청 (로그인 게이트를 이미 통과한 상태다)
 * @param pathWithQuery 백엔드에 붙일 경로 + 쿼리. 예) `/api/procurements?days=14`
 *
 * 업로드(multipart)와 내려받기(binary) 모두 이 한 경로로 지나간다.
 * 요청 본문은 스트림 그대로, 응답 본문도 스트림 그대로 흘려보내 메모리에 통째로 담지 않는다.
 */
export async function forward(request: Request, pathWithQuery: string): Promise<Response> {
  const base = backendUrl();
  if (base === null) {
    // proxyEnabled() 로 걸러진 뒤 불리므로 정상 경로에서는 오지 않는다.
    return NextResponse.json(
      { detail: "백엔드 중계가 설정되지 않았습니다 (BACKEND_URL 없음)." },
      { status: 500 },
    );
  }

  const token = readServerEnv("API_TOKEN");
  const identity = await identityFrom(request.headers, token);
  if (identity.kind === "anonymous") {
    /**
     * 토큰은 있는데 세션이 없다. 그대로 보내면 백엔드가 **관리자**로 처리한다 (S1).
     *
     * 정상 경로에서는 오지 않는다 — 게이트가 요청을 먼저 막고, 게이트를 끈 채 토큰만 켠
     * 조합은 `proxy.ts` 가 503 으로 막는다. 여기는 그 두 겹이 모두 새더라도 권한 상승이
     * 일어나지 않게 하는 마지막 자리다. 401 이지 403 이 아니다 — 누구인지를 모르는 것이다.
     */
    console.error("[backendProxy] 세션 없는 요청이라 백엔드로 보내지 않았습니다.");
    return NextResponse.json(
      { detail: "로그인이 필요합니다. 세션이 만료되었으면 다시 로그인해 주세요." },
      { status: 401 },
    );
  }
  if (identity.kind === "unsafe") {
    console.error("[backendProxy] 계정 아이디를 헤더로 실을 수 없어 요청을 보내지 않았습니다.");
    return NextResponse.json(
      {
        detail:
          "계정 아이디에 헤더로 보낼 수 없는 문자가 있어 백엔드에 신원을 전달하지 못했습니다. " +
          "영문·숫자 아이디로 다시 발급해 주세요.",
      },
      { status: 500 },
    );
  }

  const method = request.method.toUpperCase();
  const init: ProxyRequestInit = {
    method,
    headers: buildRequestHeaders(request.headers, token, identity),
    // 백엔드 응답은 항상 지금 상태여야 한다 — 캐시에 걸리면 승인·색인 결과가 옛날 값으로 보인다.
    cache: "no-store",
    // 리다이렉트를 따라가지 않는다. 예상 못 한 호스트로 요청이 새는 것을 막는다.
    redirect: "manual",
  };

  // GET·HEAD 에는 본문이 없다. 그 밖에는 들어온 스트림을 그대로 넘긴다.
  if (method !== "GET" && method !== "HEAD" && request.body !== null) {
    init.body = request.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    try {
      upstream = await fetch(`${base}${pathWithQuery}`, init);
    } catch (first) {
      // 10-31 최종 점검 — 쉬던 연결을 백엔드(일꾼 1개)가 막 닫은 순간 다시 쓰면 UND_ERR_SOCKET · ECONNRESET 로 끊겨 목록이 502 였다
      // (세 사람이 동시에 목록을 열 때 계정마다 1~3건). 읽기(GET · HEAD)만 한 번 더 보낸다 — 쓰기는 두 번 처리될 수 있어 다시 보내지 않는다.
      if ((method !== "GET" && method !== "HEAD") || !RETRYABLE_CODES.has(failureCode(first))) throw first;
      upstream = await fetch(`${base}${pathWithQuery}`, init);
    }
  } catch (error) {
    const code = failureCode(error);
    // 경로와 사유 코드만 남긴다. 백엔드 주소·토큰은 로그에도 남기지 않는다.
    console.error(`[backendProxy] 백엔드 요청 실패 (${method}, ${code})`);
    return NextResponse.json(
      {
        detail:
          `백엔드에 연결하지 못했습니다 (${code}). ` +
          "서버가 실행 중인지, 배포 설정의 백엔드 주소가 맞는지 확인해 주세요.",
      },
      { status: 502 },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: buildResponseHeaders(upstream.headers),
  });
}

/** 백엔드에 짧은 질의 하나를 보낸다 (스트림 중계가 아니라 로그인처럼 묻고 답받는 용도). */
export interface BackendAnswer {
  status: number;
  data: unknown;
}

/**
 * `POST <백엔드>/<path>` 에 JSON 을 보내고 JSON 을 받는다.
 *
 * `forward()` 를 쓰지 않는 이유: 로그인 라우트는 요청 본문을 이미 읽어 버린 뒤라 스트림을
 * 그대로 넘길 수 없고, 아직 세션이 없으므로 신원 헤더도 붙지 않는다(계약서 §3).
 * 연결 실패·타임아웃이면 null 을 돌려준다 — 부르는 쪽이 예전 경로로 되돌아갈 수 있어야 한다.
 *
 * 타임아웃을 두는 이유: 백엔드가 응답하지 않으면 로그인 화면이 그만큼 멈춰 선다.
 * 공용 계정으로는 들어갈 수 있으므로 오래 기다리지 않고 끊는 편이 낫다.
 */
export async function requestBackendJson(
  pathWithQuery: string,
  body: unknown,
  timeoutMs = 5000,
): Promise<BackendAnswer | null> {
  const base = backendUrl();
  if (base === null) return null;

  const headers = new Headers({ "content-type": "application/json", accept: "application/json" });
  const token = readServerEnv("API_TOKEN");
  if (token !== null) headers.set("authorization", `Bearer ${token}`);

  try {
    const response = await fetch(`${base}${pathWithQuery}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const data = await response.json().catch(() => null);
    return { status: response.status, data };
  } catch (error) {
    // 경로도 사유 코드만 남긴다. 본문(아이디·비밀번호)은 절대 로그에 쓰지 않는다.
    console.error(`[backendProxy] 백엔드 질의 실패 (${failureCode(error)})`);
    return null;
  }
}
