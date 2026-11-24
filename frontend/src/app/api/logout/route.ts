import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/demoAuth";
import { USER_COOKIE } from "@/lib/session";

/**
 * 로그아웃 — 쿠키 두 개를 **함께** 지운다.
 *
 * 세션 쿠키만 지우면 표시 전용 쿠키(`bidpilot_user`)가 남아 화면 구석에 방금 나간 사람 이름이
 * 계속 뜬다. 그 쿠키는 권한과 무관하지만, 「아직 로그인돼 있다」고 오해하게 만든다 (계약서 §8).
 */
export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  response.cookies.set(USER_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
