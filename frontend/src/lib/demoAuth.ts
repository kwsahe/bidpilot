/**
 * 배포본 접근 게이트.
 *
 * 심사·팀 공유용 링크를 아무나 열지 못하게 막는 최소 장치다. 실제 인증 시스템이 아니다.
 * 아이디·비밀번호는 Vercel 환경변수로만 두고, 검사는 서버(미들웨어·라우트 핸들러)에서만 한다.
 * 그래서 값이 브라우저 번들에도 git 기록에도 남지 않는다.
 *
 * 개인 계정·역할이 생기면서 이 파일은 **공용 접근계정(게이트가 켜졌는지·통과했는지)** 만 맡는다.
 * 세션 쿠키를 굽고 검증하는 일은 `lib/session.ts` 로 옮겼다 — 쿠키가 신원을 실어 나르게 되어
 * 서명이 필요해졌고, 예전처럼 「자격증명에서 파생한 고정 해시 하나」로는 누구인지 담을 수 없다.
 */

export const SESSION_COOKIE = "bidpilot_demo_session";

/**
 * 로그인 없이 열 수 있는 경로. **정확히 일치할 때만** 통과한다 (S7).
 *
 * 예전에는 접두사로 봤다(`pathname.startsWith("/api/login/")`). 그러면
 * `/api/login/아무거나` 가 게이트를 지나 `api/[...path]` catch-all 중계로 들어가고,
 * 중계는 토큰을 붙여 백엔드로 보낸다. 신원 헤더가 없으니 백엔드는 그것을
 * 「토큰을 쥔 관리자」로 본다 — 로그인하지 않은 사람이 관리자 권한을 얻는 길이었다.
 *
 * 이 경로들 아래에는 하위 경로가 없다. 생긴다면 그때 여기 명시적으로 더한다.
 * `/health`(42차 · 회사 서버 nginx · 점검)는 로그인하지 않은 요청에 판 · 규칙 판 · ok 만 준다(`app/health/route.ts`).
 * 중계(`api/[...path]`)가 아니라 제 라우트라 토큰을 쥔 관리자 길이 아니다.
 */
export const PUBLIC_PATHS = ["/login", "/api/login", "/api/logout", "/health"];

/** 이 경로가 게이트 없이 열리는가. 접두사가 아니라 정확히 같아야 한다. */
export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.includes(pathname);
}

function credentials(): { user: string; password: string } | null {
  const user = process.env.DEMO_USER;
  const password = process.env.DEMO_PASSWORD;
  // 둘 중 하나라도 없으면 게이트를 걸지 않는다 (로컬 개발용).
  if (!user || !password) return null;
  return { user, password };
}

/**
 * 이 빌드가 **실제 회사자료**를 담고 있는가 (`REQUIRE_AUTH=1`).
 *
 * 사내용 배포처럼 실데이터가 실린 빌드는 자격증명이 사라져도 **열려서는 안 된다**.
 * 이 값이 켜져 있으면 DEMO_USER/DEMO_PASSWORD 가 없을 때 화면을 여는 대신 잠근다(fail-closed).
 */
export function authRequired(): boolean {
  return process.env.REQUIRE_AUTH === "1";
}

/** 게이트가 켜져 있는가. 환경변수가 없으면 꺼진 상태다 (로컬 개발). */
export function gateEnabled(): boolean {
  return credentials() !== null;
}

/**
 * 자격증명이 없는데 REQUIRE_AUTH 만 켜진 상태 — 설정 사고다.
 * 이때는 통과시키지 말고 막아야 실데이터가 그대로 공개되는 일을 피한다.
 */
export function misconfigured(): boolean {
  return authRequired() && credentials() === null;
}

/**
 * 공용 접근계정으로 들어왔을 때 쓸 신원.
 *
 * 개인 계정이 생기기 전부터 있던 계정이라 역할은 `admin` 이다 (계약서 §1 — 호환).
 * 표시 이름은 따로 없으므로 아이디를 그대로 쓴다.
 */
export function demoAccount(): { u: string; r: "admin"; n: string } | null {
  const cred = credentials();
  if (!cred) return null;
  return { u: cred.user, r: "admin", n: cred.user };
}

/** 길이가 같은 문자열을 상수 시간에 비교한다 (타이밍 차이로 값을 추측하지 못하게). */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export async function verify(user: string, password: string): Promise<boolean> {
  const cred = credentials();
  if (!cred) return false;
  return safeEqual(user, cred.user) && safeEqual(password, cred.password);
}
