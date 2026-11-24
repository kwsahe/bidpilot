import { NextResponse } from "next/server";
import { SESSION_COOKIE, authRequired, demoAccount, gateEnabled, verify } from "@/lib/demoAuth";
import { proxyEnabled, requestBackendJson } from "@/lib/backendProxy";
import { decideLogin, type LookupKind } from "@/lib/authPolicy";
import { clearAttempts, clientKey, noteAttempt } from "@/lib/loginThrottle";
import {
  SESSION_TTL_SECONDS,
  USER_COOKIE,
  isRole,
  sessionCookieOptions,
  sessionExpiry,
  signSession,
  userCookieOptions,
  userCookieValue,
  type Role,
} from "@/lib/session";

// 백엔드에 계정을 물어볼 때 fetch 를 쓴다. `api/[...path]` 와 같은 이유로 Node 런타임에 못 박는다.
export const runtime = "nodejs";

/** 세션에 담을 신원. */
interface Account {
  u: string;
  r: Role;
  n: string;
}

function pickString(source: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim().length > 0) return value.trim();
  }
  return null;
}

/**
 * 백엔드 로그인 응답에서 신원을 읽는다.
 *
 * 계약서는 `POST /api/auth/login` 의 **응답 형식을 정하지 않았다**. 그래서 흔한 이름들을
 * 함께 받아들이되, 역할이 셋(viewer·editor·admin) 중 하나가 아니면 **실패로 본다** —
 * 못 읽은 역할을 관리자로 채워 넣는 편이 훨씬 위험하다.
 */
function readAccount(data: unknown): Account | null {
  if (data === null || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;
  const nested =
    record.user !== null && typeof record.user === "object"
      ? (record.user as Record<string, unknown>)
      : null;
  const source = nested ?? record;

  const user = pickString(source, ["user", "username", "u", "id"]);
  const role = pickString(source, ["role", "r"]);
  if (user === null || !isRole(role)) return null;
  const name = pickString(source, ["display_name", "displayName", "n", "name"]) ?? user;
  return { u: user, r: role, n: name };
}

/** 백엔드에 계정을 물어본 결과. `unavailable` 은 「백엔드가 답을 못 줬다」는 뜻이다. */
type Lookup =
  | { kind: "account"; account: Account }
  | { kind: "rejected"; detail: string | null }
  | { kind: "unavailable" }
  | { kind: "skipped" };

/**
 * 거절 사유를 그대로 보여 줄지 고른다.
 *
 * 백엔드는 「아이디 또는 비밀번호가 올바르지 않습니다」와 「시도가 너무 많습니다」를 구분해
 * 준다. 뒤엣것은 사람이 알아야 하는 정보다(기다리면 풀린다). 둘 다 계정 존재 여부를
 * 드러내지 않는 문장이라 그대로 보여 준다. 길거나 문자열이 아니면 버린다.
 */
function rejectionDetail(data: unknown): string | null {
  if (data === null || typeof data !== "object") return null;
  const detail = (data as Record<string, unknown>).detail;
  if (typeof detail !== "string") return null;
  const trimmed = detail.trim();
  return trimmed.length > 0 && trimmed.length <= 200 ? trimmed : null;
}

async function askBackend(user: string, password: string): Promise<Lookup> {
  // 45차 M3 — 서버가 바쁠 때(07:30 받기 · 워커 하나) 5초로는 맞는 비밀번호에도 「계정 서버에 연결하지 못했습니다」가 났다
  const answer = await requestBackendJson("/api/auth/login", { user, password }, 15_000);
  if (answer === null) return { kind: "unavailable" };
  if (answer.status === 401 || answer.status === 403) {
    return { kind: "rejected", detail: rejectionDetail(answer.data) };
  }
  if (answer.status < 200 || answer.status >= 300) {
    // 404 는 「계정 API 가 아직 없는 백엔드」, 5xx 는 고장이다. 둘 다 «답을 못 받았다»로 본다.
    // 되돌아갈지 말지는 `fallbackAllowed()` 가 정한다 — 중계 배포에서는 되돌아가지 않는다 (S4).
    console.warn(`[login] 백엔드 계정 확인이 ${answer.status} 로 끝났습니다.`);
    return { kind: "unavailable" };
  }
  const account = readAccount(answer.data);
  if (account === null) {
    // 본문은 찍지 않는다 — 계정 정보가 로그에 남는다.
    console.warn("[login] 백엔드 로그인 응답에서 아이디·역할을 읽지 못했습니다.");
    return { kind: "unavailable" };
  }
  return { kind: "account", account };
}

/**
 * 로그인.
 *
 * 순서가 중요하다.
 *
 * 1. 중계가 켜져 있으면 백엔드의 개인 계정(`data/private/users.json`)에 먼저 물어본다.
 *    답이 오면 그 **역할 그대로** 세션을 굽는다.
 * 2. 백엔드에 **물어볼 수 없었을 때만** 기존 공용 계정(`DEMO_USER`)을 본다.
 *    공용 계정은 개인 계정이 생기기 전부터 있던 것이라 역할이 `admin` 이다 (계약서 §1 호환).
 *
 *    백엔드가 «거절»했을 때는 되돌아가지 않는다. 그렇게 하면 계약서 §1 의
 *    「users.json 이 이긴다」가 뒤집힌다 — `DEMO_USER` 이름이 users.json 의 아이디와 겹치면,
 *    그 계정이 열람자이거나 비활성이어도 공용 비밀번호를 아는 사람이 **관리자 세션**을 받는다.
 *    (검수에서 실제로 재현된 권한 상승이다.)
 *
 *    백엔드도 `DEMO_USER`/`DEMO_PASSWORD` 를 읽어 같은 규칙으로 판정하므로(user_service),
 *    중계가 켜진 배포에서는 이 되돌림이 없어도 공용 계정이 그대로 통한다.
 *    **단 백엔드 쪽에도 그 환경변수가 있어야 한다** — 배포 문서에 적어 두었다.
 * 3. 둘 다 아니면 401. 아이디가 틀렸는지 비밀번호가 틀렸는지는 구분해 알려주지 않는다.
 *
 * ## 되돌림은 스냅샷 배포에서만 (S4)
 *
 * 백엔드가 **거절이 아닌 이유**로 답을 못 줘도(타임아웃·5xx·404·파싱 실패) 예전에는
 * 공용 계정으로 되돌아갔다. 그러면 `users.json` 에서 열람자이거나 비활성인 계정이라도
 * `DEMO_USER` 와 이름이 같기만 하면 공용 비밀번호로 **관리자 세션**을 받는다. 백엔드를
 * 잠깐 멈추게 만들 수 있는 사람이면 그 상태를 만들 수도 있다.
 *
 * 그래서 되돌림은 **중계도 아니고 실데이터 빌드도 아닐 때**만 허용한다. 그 조건이면
 * 애초에 물어볼 백엔드가 없는 스냅샷 배포이고, 공용 계정이 유일한 신원이다.
 * 중계 배포에서 백엔드가 죽으면 로그인은 **503 으로 닫힌다** — 열리는 것보다 낫다.
 */

export async function POST(request: Request) {
  if (!gateEnabled()) {
    return NextResponse.json({ error: "로그인 게이트가 설정되지 않았습니다." }, { status: 503 });
  }

  /**
   * 주소 단위 제한 (S11). 백엔드는 **아이디**로 세는데, 아이디를 매번 바꿔 가며 두드리면
   * 그 잠금에 걸리지 않고 pbkdf2 60만 회를 계속 시킬 수 있다. 브라우저 주소가 보이는
   * 자리는 여기뿐이라 여기서 센다. 자격증명을 보기 **전에** 판정한다.
   */
  const throttleKey = clientKey(request.headers);
  const throttle = noteAttempt(throttleKey);
  if (throttle.limited) {
    return NextResponse.json(
      { error: "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요." },
      { status: 429, headers: { "retry-after": String(throttle.retryAfterSeconds) } },
    );
  }

  let user = "";
  let password = "";
  try {
    const body = (await request.json()) as { user?: string; password?: string };
    user = body.user ?? "";
    password = body.password ?? "";
  } catch {
    return NextResponse.json({ error: "요청 형식이 올바르지 않습니다." }, { status: 400 });
  }

  const lookup: Lookup =
    proxyEnabled() && user.length > 0 && password.length > 0
      ? await askBackend(user, password)
      : { kind: "skipped" };

  // 되돌림 규칙은 `authPolicy.decideLogin` 한 곳에 있다 (S4). 여기서는 환경만 읽어 넘긴다.
  const outcome = decideLogin(lookup.kind as LookupKind, await verify(user, password), {
    proxy: proxyEnabled(),
    requireAuth: authRequired(),
  });

  const account: Account | null =
    outcome === "personal" && lookup.kind === "account"
      ? lookup.account
      : outcome === "shared"
        ? demoAccount()
        : null;

  if (account === null) {
    if (outcome === "unavailable") {
      return NextResponse.json(
        {
          error:
            "계정 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요. " +
            "이 배포본은 계정 서버가 답하지 않는 동안 다른 경로로 열지 않습니다.",
        },
        { status: 503 },
      );
    }
    const detail = lookup.kind === "rejected" ? lookup.detail : null;
    return NextResponse.json(
      { error: detail ?? "아이디 또는 비밀번호가 맞지 않습니다." },
      { status: 401 },
    );
  }

  const exp = sessionExpiry();
  const value = await signSession({ ...account, exp });
  if (value === null) {
    // 게이트가 켜져 있으면 서명 키 재료가 하나는 있으므로 정상 경로에서는 오지 않는다.
    console.error("[login] 세션 서명 키를 만들지 못했습니다 (SESSION_SECRET·API_TOKEN 확인).");
    return NextResponse.json(
      { error: "세션 서명 키가 없어 로그인할 수 없습니다. 배포 설정을 확인해 주세요." },
      { status: 500 },
    );
  }

  // 맞게 들어온 사람에게 다음 시도까지 제한을 물려주지 않는다.
  clearAttempts(throttleKey);

  const response = NextResponse.json({
    ok: true,
    user: account.u,
    role: account.r,
    display_name: account.n,
  });
  response.cookies.set(SESSION_COOKIE, value, sessionCookieOptions(SESSION_TTL_SECONDS));
  // 화면이 「누구로 들어왔는지」를 찍기 위한 표시 전용 쿠키 (계약서 §8). 권한 판정에는 쓰지 않는다.
  response.cookies.set(USER_COOKIE, userCookieValue({ ...account, exp }), userCookieOptions(SESSION_TTL_SECONDS));
  return response;
}
