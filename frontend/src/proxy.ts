import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, authRequired, gateEnabled, isPublicPath, misconfigured } from "@/lib/demoAuth";
import { apiTokenSet, proxyEnabled } from "@/lib/backendProxy";
import { relayWithoutGate } from "@/lib/authPolicy";
import { USER_COOKIE, verifySession } from "@/lib/session";
import { MODE_COOKIE, encodeMode, type BackendMode } from "@/lib/deploymentMode";

/**
 * 로그인하지 않은 요청을 /login 으로 보낸다.
 *
 * 파일 이름이 `proxy.ts` 인 이유: Next.js 16 에서 `middleware` 파일 규칙이 deprecated 되고
 * `proxy` 로 이름이 바뀌었다(파일명과 내보내는 함수명 둘 다). 동작은 같고, 빌드 경고만 사라진다.
 * 인증 게이트·모드 쿠키·fail-closed 규칙은 그대로다.
 * DEMO_USER / DEMO_PASSWORD 가 없으면 게이트를 걸지 않는다 (로컬 개발).
 *
 * 단 `REQUIRE_AUTH=1` 인 빌드(실제 회사자료가 실린 사내 배포)는 예외다.
 * 자격증명이 사라지면 **열지 말고 잠근다** — 환경변수 실수 한 번으로 실데이터가
 * 공개되는 것을 막기 위해서다 (fail-open 이 아니라 fail-closed).
 *
 * 여기서 두 가지를 더 한다:
 *
 *  1. 배포 모드를 쿠키에 찍는다. 주요 화면이 정적으로 prerender 되어 서버에서
 *     런타임 값을 읽을 수 없기 때문이다. 비밀은 담지 않는다(모드 이름 두 개뿐).
 *  2. 실데이터 빌드인데 백엔드가 없으면 잠근다. REQUIRE_AUTH=1 은 「실회사자료 빌드」라는
 *     뜻인데 BACKEND_URL 이 빠지면 라우트가 조용히 옛 스냅샷을 돌려준다 — 로그인 게이트
 *     뒤에서 낡은 데이터를 실시간인 척 보여주는 것이라, 인증과 같은 이유로 fail-closed 다.
 */
/**
 * 데이터를 어디서 가져오는가 — `lib/api.ts` 의 `BACKEND_URL` 규칙과 **같은 판정**이어야 한다.
 *
 * 예전에는 「중계하지 않으면 스냅샷」이었다. 그런데 로컬 개발에서는 중계를 켜지 않아도
 * 브라우저가 `NEXT_PUBLIC_BACKEND_URL`(기본 localhost:8110)을 **직접** 부른다.
 * 그래서 실백엔드의 실데이터를 보면서 푸터는 「저장된 스냅샷을 보는 열람용 배포본」이라고
 * 말했다 (ISSUE-021). 경로가 다를 뿐 둘 다 실데이터다.
 */
function backendMode(): BackendMode {
  if (proxyEnabled()) return "proxy";
  return process.env.NEXT_PUBLIC_DEMO_MODE === "1" ? "snapshot" : "direct";
}

export async function proxy(request: NextRequest) {
  if (misconfigured()) {
    return NextResponse.json(
      {
        detail:
          "접근 설정이 완료되지 않았습니다. 이 배포본은 실제 회사자료를 담고 있어 " +
          "DEMO_USER / DEMO_PASSWORD 가 설정되기 전에는 열리지 않습니다.",
      },
      { status: 503 },
    );
  }
  /**
   * 중계를 켰고 백엔드 토큰도 있는데 **게이트는 꺼져 있다** — 이 조합은 열어 두면 안 된다 (S1).
   *
   * 중계는 요청마다 `API_TOKEN` 을 붙여 백엔드로 보낸다. 게이트가 꺼져 있으면 세션이 없고,
   * 세션이 없으면 신원 헤더도 없다. 백엔드는 「토큰만 있고 신원 헤더가 없는 요청」을
   * 스크립트·운영자 직접 호출로 보아 **관리자**로 처리한다(identity.py 판정 3항).
   * 즉 주소만 아는 익명 사용자가 회사자료를 읽고 쓸 수 있게 된다.
   *
   * 셋 중 하나를 고르게 만든다: 게이트를 켜거나, 토큰을 빼거나, 중계를 끄거나.
   */
  if (relayWithoutGate({ proxy: proxyEnabled(), apiToken: apiTokenSet(), gate: gateEnabled() })) {
    return NextResponse.json(
      {
        detail:
          "접근 설정이 위험한 조합입니다. 백엔드 중계와 API 토큰이 켜져 있는데 로그인 게이트가 " +
          "꺼져 있어, 로그인하지 않은 요청이 백엔드에서 관리자 권한을 받게 됩니다. " +
          "DEMO_USER / DEMO_PASSWORD 를 설정해 게이트를 켜거나 API_TOKEN 을 비워 주세요.",
      },
      { status: 503 },
    );
  }

  // 실데이터 빌드인데 백엔드가 없다 — 옛 스냅샷을 실시간인 척 보여주지 않는다.
  if (authRequired() && !proxyEnabled()) {
    return NextResponse.json(
      {
        detail:
          "백엔드 주소(BACKEND_URL)가 설정되지 않았습니다. 이 배포본은 실시간 데이터를 " +
          "전제로 하므로, 저장된 스냅샷으로 대신 열지 않습니다.",
      },
      { status: 503 },
    );
  }

  const mode = encodeMode({ backend: backendMode(), gated: gateEnabled() });

  /** 모드 쿠키를 실어 보낸다. httpOnly 가 아니다 — 화면이 읽어야 문구를 맞출 수 있다. */
  function withMode(response: NextResponse): NextResponse {
    response.cookies.set(MODE_COOKIE, mode, { path: "/", sameSite: "lax", httpOnly: false });
    return response;
  }

  if (!gateEnabled()) return withMode(NextResponse.next());

  const { pathname, search } = request.nextUrl;
  if (isPublicPath(pathname)) {
    return withMode(NextResponse.next());
  }

  // 서명과 만료를 함께 본다. 둘 중 하나라도 어긋나면 — 예전 형식(점 없는 hex) 쿠키도 여기서
  // 자연스럽게 걸린다 — 로그인 화면으로 보낸다 (계약서 §2).
  const session = await verifySession(request.cookies.get(SESSION_COOKIE)?.value);
  if (session !== null) return withMode(NextResponse.next());

  // 42차 — 데이터 요청(/api/*)은 로그인 화면으로 돌려보내지 않고 401 이다. 돌려보내면 화면의 fetch 가 로그인 HTML 을
  // 200 으로 받아 JSON 으로 읽다 깨진다(세션이 끝난 뒤) · 401 이면 「로그인 상태를 확인해 주세요」(lib/errors).
  if (pathname.startsWith("/api/")) {
    const denied = withMode(NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 }));
    denied.cookies.set(USER_COOKIE, "", { path: "/", maxAge: 0 });
    return denied;
  }

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  const redirect = withMode(NextResponse.redirect(url));
  // 세션이 죽었는데 표시 전용 쿠키만 남으면 화면 구석에 로그아웃한 사람 이름이 계속 뜬다.
  redirect.cookies.set(USER_COOKIE, "", { path: "/", maxAge: 0 });
  return redirect;
}

export const config = {
  // 정적 자산과 파비콘은 게이트에서 뺀다.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
