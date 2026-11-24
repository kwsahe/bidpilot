/**
 * 이 배포본이 지금 무엇인지 — 한 곳에서만 정한다.
 *
 * 예전에는 판정 축이 넷으로 흩어져 있었고(NEXT_PUBLIC_DEMO_MODE, BACKEND_URL,
 * REQUIRE_AUTH, 백엔드 PUBLIC_DEMO_MODE), 화면 문구는 대부분 그중 아무것도 보지 않는
 * 하드코딩이었다. 그래서 실백엔드에 붙어 실제 회사자료를 띄워 놓고도 로그인 화면은
 * 「읽기 전용 배포본」, 회사자료 화면은 「인증 없이 실행되는 로컬 관리자 모드」,
 * 푸터는 「공개 데모는 합성 회사자료만 사용합니다」라고 말했다.
 *
 * 두 축은 서로 **독립**이며 하나로 합치면 안 된다:
 *
 *   backend  : 실백엔드를 중계하는가(proxy)  아니면 저장된 스냅샷인가(snapshot)   ← BACKEND_URL
 *   gate     : 로그인 게이트가 걸려 있는가                                        ← DEMO_USER/PASSWORD
 *
 * 「로그인은 걸려 있는데 내용은 스냅샷」도 성립하는 조합이다. 그래서 축을 나눠 둔다.
 *
 * 값을 브라우저까지 어떻게 보내는가:
 *   주요 화면이 정적으로 prerender 되기 때문에(빌드 결과의 ○ 표시) 서버 컴포넌트로는
 *   런타임 값을 못 읽는다. 그래서 **미들웨어가 매 요청마다 쿠키에 찍고** 클라이언트가 그걸 읽는다.
 *   미들웨어는 어차피 모든 경로에서 돌고 있으니 추가 왕복이 없다.
 *   이 쿠키에는 비밀이 들어가지 않는다 — 모드 이름 두 개뿐이다.
 */

export const MODE_COOKIE = "bidpilot_mode";

/**
 * 데이터를 어디서 가져오는가.
 *
 *   proxy     이 앱이 실백엔드를 중계한다 (사내 배포)
 *   direct    브라우저가 실백엔드를 직접 부른다 (로컬 개발 — `NEXT_PUBLIC_BACKEND_URL`)
 *   snapshot  빌드 시점에 박제된 응답만 본다 (공개 데모)
 *
 * `direct` 가 없어서 로컬 개발이 `snapshot` 으로 분류됐고, 실백엔드에 붙어
 * 실데이터를 보면서도 푸터가 「저장된 스냅샷을 보는 열람용 배포본」이라고 말했다
 * (ISSUE-021). 중계냐 직접이냐는 **경로**의 차이일 뿐, 둘 다 실데이터다.
 */
export type BackendMode = "proxy" | "direct" | "snapshot";

export interface DeploymentMode {
  /** 실백엔드를 중계하는가. */
  backend: BackendMode;
  /** 로그인 게이트가 걸려 있는가. */
  gated: boolean;
}

/** 아직 모르는 상태에서 쓸 값. 틀린 단정 대신 «중립»을 고른다. */
export const UNKNOWN_MODE: DeploymentMode | null = null;

/** 쿠키에 담을 짧은 표현 — "proxy:gated" 처럼 두 축을 콜론으로 잇는다. */
export function encodeMode(mode: DeploymentMode): string {
  return `${mode.backend}:${mode.gated ? "gated" : "open"}`;
}

export function decodeMode(raw: string | undefined | null): DeploymentMode | null {
  if (!raw) return null;
  const [backend, gate] = raw.split(":");
  if (backend !== "proxy" && backend !== "direct" && backend !== "snapshot") return null;
  return { backend, gated: gate === "gated" };
}

/**
 * 실제 회사자료를 다루는 배포인가.
 *
 * 실백엔드를 중계한다는 것은 회사 서버의 실데이터를 본다는 뜻이다.
 * 스냅샷 배포본은 빌드 시점에 박제된 응답만 본다.
 */
export function usesRealData(mode: DeploymentMode | null): boolean {
  return mode?.backend === "proxy" || mode?.backend === "direct";
}

/**
 * 화면 아래에 붙일 한 줄. 모드를 모르면 모드와 무관한 문장만 남긴다.
 *
 * 「추천등급·적합도는 낙찰확률이 아니다」는 어느 모드에서나 참이므로 호출부가 항상 덧붙인다.
 */
export function modeFooterLine(mode: DeploymentMode | null): string | null {
  if (mode === null) return null;
  if (mode.backend === "proxy") {
    return "사내 전용 · 현재 회사의 승인된 내부자료만 분석에 사용합니다.";
  }
  if (mode.backend === "direct") {
    // 로컬 운영. 실백엔드에 붙어 있으므로 「스냅샷」이라고 말하면 거짓말이 된다.
    // 「개발용으로 백엔드에…」는 담당자가 읽을 말이 아니었다 (CMN-18).
    return "이 컴퓨터의 서버에 연결해 실행 중입니다. 자료 범위는 각 화면의 출처 표시를 확인하세요.";
  }
  return "저장된 스냅샷을 보는 열람용 배포본입니다. 자료 범위는 각 화면의 출처 표시를 확인하세요.";
}

/**
 * 로그인한 사람 이름을 모를 때의 이름 — 이름은 표시 쿠키(`lib/currentUser`)에서 따로 읽는다.
 *
 * 직원별 계정이 생긴 뒤에도 「공용 접근계정으로 로그인됨」이라 적고 있었다 (CMN-07). 모를 때는 모른다고만 적는다.
 */
export function accessLabel(mode: DeploymentMode | null): string | null {
  if (mode === null) return null;
  return mode.gated ? "로그인됨" : "로그인 없이 열람 중";
}
