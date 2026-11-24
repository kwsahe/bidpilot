/**
 * 인증 «판정»만 모은 곳 — 환경변수도 네트워크도 `next/server` 도 건드리지 않는다.
 *
 * ## 왜 따로 떼는가
 *
 * 로그인 되돌림과 신원 전달은 검수에서 **둘 다 권한 상승 경로**로 지목됐다 (S1·S4).
 * 그런데 그 판정이 라우트 핸들러와 중계 모듈 안에 섞여 있어서, 검사하려면 Next 런타임과
 * 백엔드를 통째로 띄워야 했다. 실제로 이 두 경로에는 테스트가 하나도 없었다.
 *
 * 규칙만 순수 함수로 떼어 두면 조합을 표로 두드릴 수 있다. 부르는 쪽은 환경변수를 읽어
 * 불리언으로 바꿔 넘기기만 한다.
 */

/**
 * 로그인 뒤 갈 주소 — 이 사이트 안의 경로만 따른다 (CMN-03).
 * `?next=https://…` · `//다른사이트` · `/\다른사이트` 는 로그인 뒤 바깥 사이트로 보내는 열린 이동이었다.
 * 앞자리만 보면 `/\t/다른사이트` 가 샌다 — 주소 해석이 탭 · 줄바꿈을 지우고 `\` 를 `/` 로 읽어 `//다른사이트` 가 된다.
 * 그래서 제어 문자 · 백슬래시를 거절하고, 해석한 주소의 출처가 이 사이트 그대로인지 한 번 더 본다.
 */
const SITE = "http://bidpilot.invalid";
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || /[\u0000-\u001f\u007f\\]/.test(raw)) return "/";
  try {
    return new URL(raw, SITE).origin === SITE ? raw : "/";
  } catch {
    return "/";
  }
}

/** 백엔드에 계정을 물어본 결과. `unavailable` 은 「백엔드가 답을 못 줬다」는 뜻이다. */
export type LookupKind = "account" | "rejected" | "unavailable" | "skipped";

/** 이 배포본의 모양. 둘 다 거짓이면 스냅샷 배포다. */
export interface Deployment {
  /** 백엔드를 중계하는가 (`BACKEND_URL` 이 있는가). */
  proxy: boolean;
  /** 실제 회사자료가 실린 빌드인가 (`REQUIRE_AUTH=1`). */
  requireAuth: boolean;
}

/**
 * 공용 접근계정(`DEMO_USER`)으로 되돌아가도 되는가 (S4).
 *
 * 중계가 켜져 있거나 실데이터 빌드면 **안 된다.** 그런 배포에서 신원의 출처는
 * `users.json` 하나여야 한다. 되돌아가면 거기서 열람자이거나 비활성인 계정이라도
 * 이름만 `DEMO_USER` 와 같으면 공용 비밀번호로 관리자 세션을 받는다.
 */
export function canFallBackToSharedAccount(deployment: Deployment): boolean {
  return !deployment.proxy && !deployment.requireAuth;
}

/** 로그인 판정 결과. */
export type LoginOutcome =
  /** 백엔드가 준 개인 계정으로 세션을 굽는다. */
  | "personal"
  /** 공용 접근계정으로 세션을 굽는다. */
  | "shared"
  /** 아이디·비밀번호가 맞지 않는다. */
  | "reject"
  /** 계정 서버가 답하지 않는다 — 열지 않고 닫는다. */
  | "unavailable";

/**
 * 로그인 한 건의 결론 (S4 되돌림 매트릭스).
 *
 * @param lookup            백엔드에 물어본 결과
 * @param sharedMatches     공용 접근계정의 아이디·비밀번호와 맞는가
 * @param deployment        배포본의 모양
 *
 * 순서가 규칙이다.
 * 1. 백엔드가 계정을 줬으면 그 역할 그대로 간다.
 * 2. 백엔드가 **거절**했으면 거기서 끝이다 — 되돌아가면 §1 의 「users.json 이 이긴다」가 뒤집힌다.
 * 3. 그 밖에는 되돌아가도 되는 배포일 때만 공용 계정을 본다.
 * 4. 백엔드가 답을 못 준 것이면 401 이 아니라 **503** 이다. 자격증명이 틀렸다고 말하면
 *    사람이 비밀번호를 의심하며 계속 다시 친다.
 */
export function decideLogin(
  lookup: LookupKind,
  sharedMatches: boolean,
  deployment: Deployment,
): LoginOutcome {
  if (lookup === "account") return "personal";
  if (lookup === "rejected") return "reject";
  if (sharedMatches && canFallBackToSharedAccount(deployment)) return "shared";
  return lookup === "unavailable" ? "unavailable" : "reject";
}

/** 백엔드로 넘길 신원의 종류. */
export type IdentityKind =
  /** 토큰 자체가 없다 — 백엔드도 인증이 꺼진 로컬이다. */
  | "none"
  /** 토큰은 있는데 세션이 없다 — 보내면 백엔드가 관리자로 본다. 끊어야 한다 (S1). */
  | "anonymous"
  /** 아이디·역할을 헤더에 실을 수 없다 — 역시 끊는다. */
  | "unsafe"
  /** 서명해서 넘긴다. */
  | "signed";

/**
 * 중계가 이 요청에 어떤 신원을 실을지 (S1).
 *
 * `anonymous` 를 따로 두는 것이 이 함수의 전부다. 예전에는 「세션 없음」과 「토큰 없음」이
 * 둘 다 `none` 이었고, `none` 이면 신원 헤더를 **빼고** 보냈다. 백엔드는 「토큰만 있고
 * 신원 헤더가 없는 요청」을 운영자 직접 호출로 보아 관리자로 처리한다. 즉 게이트가
 * 꺼진 중계 배포에서 익명 요청이 관리자가 됐다.
 */
export function identityKind(input: {
  hasToken: boolean;
  hasSession: boolean;
  headerSafe: boolean;
}): IdentityKind {
  if (!input.hasToken) return "none";
  if (!input.hasSession) return "anonymous";
  if (!input.headerSafe) return "unsafe";
  return "signed";
}

/**
 * 열어 두면 안 되는 배포 조합인가 (S1).
 *
 * 중계 + 토큰 + 게이트 꺼짐. 셋이 겹치면 주소만 아는 사람이 백엔드에서 관리자가 된다.
 */
export function relayWithoutGate(input: {
  proxy: boolean;
  apiToken: boolean;
  gate: boolean;
}): boolean {
  return input.proxy && input.apiToken && !input.gate;
}
