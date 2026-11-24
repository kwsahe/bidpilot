import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forward, proxyEnabled } from "@/lib/backendProxy";
import { SESSION_COOKIE, gateEnabled } from "@/lib/demoAuth";
import { publicHealth } from "@/lib/publicHealth";
import { verifySession } from "@/lib/session";

// 백엔드 응답을 그대로 흘려보내므로 Node 런타임에 둔다 (`api/[...path]/route.ts` 와 같은 이유).
export const runtime = "nodejs";

/**
 * 화면의 연결 상태 표시가 부르는 곳.
 * 중계 모드면 실제 백엔드의 `/health` 를 그대로 보여 주고, 아니면 스냅샷 값을 돌려준다.
 *
 * 42차 — 이 경로는 로그인 게이트 밖이다(nginx · 서버 점검이 부른다). 로그인하지 않은 요청에는
 * 판 · 규칙 판 · ok 만(`publicHealth`) — 설정 · 회사 값은 로그인한 화면에만 간다.
 */
export async function GET(request: NextRequest): Promise<Response> {
  if (proxyEnabled()) {
    if (gateEnabled() && (await verifySession(request.cookies.get(SESSION_COOKIE)?.value)) === null) {
      try {
        const upstream = await fetch(`${backendUrl()}/health`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
        const body = publicHealth(await upstream.json().catch(() => null));
        return NextResponse.json(body, { status: upstream.ok && body.status === "ok" ? 200 : 503 });
      } catch {
        return NextResponse.json(publicHealth(null), { status: 503 });
      }
    }
    return forward(request, "/health");
  }
  const { lookup } = await import("@/lib/demoSnapshot");
  const body = lookup("/health");
  return NextResponse.json(body ?? { status: "ok", mode: "demo" });
}
