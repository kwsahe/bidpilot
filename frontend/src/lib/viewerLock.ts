"use client";

/**
 * 열람자 화면의 쓰기 단추 (43차 M26).
 *
 * 서버는 열람자의 쓰기를 이미 막는다(403). 그런데 화면은 직접 넣기 · 붙여넣기 · 회사자료 저장 · 안 적음 · 조항 확인 단추를 그대로 보여,
 * 폼 다섯 칸을 다 채운 뒤에야 막힌다는 것을 알았다. 역할이 열람자면 단추를 「열람자 — 보기만」으로 잠그고 이유를 적는다.
 * 표시 쿠키로 정하므로 **권한 판정이 아니다** — 막는 일은 지금처럼 서버가 한다.
 */

import { useCurrentUser } from "@/lib/currentUser";

export const VIEWER_LOCK_LABEL = "열람자 — 보기만";
export const VIEWER_LOCK_REASON = "열람자 계정은 보기만 합니다 — 저장 · 넣기 · 확인은 편집자 이상이 합니다(역할을 바꾸려면 관리자에게).";

/** 지금 로그인한 사람이 열람자인가. 로그인하지 않은 로컬은 false. */
export function useViewerLock(): boolean {
  return useCurrentUser()?.role === "viewer";
}
