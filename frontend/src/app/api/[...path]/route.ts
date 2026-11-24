import { NextRequest, NextResponse } from "next/server";
import { forward, proxyEnabled } from "@/lib/backendProxy";

/**
 * `/api/*` 의 단일 통로.
 *
 * 배포본은 두 가지 모드로 돈다.
 *
 * 1. **중계 모드** (`BACKEND_URL` 설정됨 — 사내 배포)
 *    브라우저는 백엔드를 직접 부르지 않는다. 여기서 같은 메서드·본문으로 백엔드에 넘기고
 *    응답을 그대로 돌려준다. 이 라우트에 오는 요청은 `proxy.ts` 의 로그인 게이트를
 *    이미 통과한 요청이다.
 * 2. **읽기 전용 스냅샷 모드** (`BACKEND_URL` 없음 — 심사·시연용 Vercel 배포)
 *    저장해 둔 GET 응답만 돌려주고 쓰기는 503. 이 배포본이 아직 살아 있으므로 이 동작은 지운다.
 *
 * `/api/login`, `/api/logout` 은 더 구체적인 라우트라 여기로 오지 않는다.
 */

// 요청 본문 스트림과 바이너리 응답(제안서 docx/pdf 내려받기, 파일 업로드)을 그대로 흘려보내려면
// Node 런타임이어야 한다. Next 16 기본값이 nodejs 지만, 이 라우트에서는 바뀌면 곤란하므로 못 박아 둔다.
export const runtime = "nodejs";

/** 쓰기는 막는다 — 저장할 곳이 없다. 화면에 이유가 그대로 뜬다. */
function readOnly(): NextResponse {
  return NextResponse.json(
    {
      detail:
        "이 배포본은 저장된 스냅샷을 보는 열람용입니다. 검사 실행·제안서 생성·저장은 동작하지 않습니다.",
    },
    { status: 503 },
  );
}

/**
 * 저장해 둔 GET 응답을 돌려준다.
 *
 * 스냅샷 모듈은 6MB JSON 을 정적 import 하므로 **필요할 때만** 불러온다.
 * 중계 모드 배포본은 이 JSON 을 아예 읽지 않는다.
 */
async function snapshot(pathWithQuery: string): Promise<NextResponse> {
  const { lookup } = await import("@/lib/demoSnapshot");
  const body = lookup(pathWithQuery);
  if (body === undefined) {
    // 원래 백엔드도 파싱 안 된 공고에는 404를 준다. 화면은 이걸 「미실행」으로 표시한다.
    return NextResponse.json(
      { detail: "이 데모 배포본에 저장되지 않은 응답입니다." },
      { status: 404 },
    );
  }
  return NextResponse.json(body);
}

/**
 * 중계 모드면 전부 백엔드로, 아니면 기존 스냅샷 동작.
 *
 * 중계 모드에서 백엔드가 죽어 있어도 스냅샷으로 몰래 되돌아가지 않는다.
 * 옛날 응답을 지금 데이터인 것처럼 보여 주는 편이 502 를 보여 주는 것보다 위험하다.
 */
async function handle(request: NextRequest): Promise<Response> {
  const { pathname, search } = request.nextUrl;
  if (proxyEnabled()) return forward(request, pathname + search);
  if (request.method === "GET") return snapshot(pathname + search);
  return readOnly();
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
