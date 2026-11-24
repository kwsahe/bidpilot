"use client";

/**
 * 「지금 누구로 로그인했는가」를 화면이 아는 방법.
 *
 * 세션 쿠키(`bidpilot_demo_session`)는 httpOnly 라 브라우저 스크립트가 읽지 못한다.
 * 그래서 로그인할 때 **표시 전용** 쿠키(`bidpilot_user`)를 하나 더 굽는다
 * (계정·권한 계약서 8장). 값은 `encodeURIComponent(JSON.stringify({u, r, n}))` 이다.
 *
 * 이 쿠키는 **권한 판정에 쓰지 않는다.** 브라우저에서 얼마든지 고칠 수 있는 값이라,
 * 여기서 읽은 역할로 무엇을 막으면 막은 척만 하는 것이 된다. 실제 판정은
 * 서명된 세션 쿠키(프런트 게이트)와 백엔드 서명 헤더가 한다. 이 모듈이 하는 일은
 * 이름을 찍고, 관리자에게만 의미 있는 화면 조각을 «보여줄지» 정하고,
 * 폼의 담당자 기본값을 채우는 것뿐이다.
 *
 * 쿠키가 없으면 null 이다 — 로컬 개발처럼 게이트가 꺼진 상태다. 그때 화면은
 * 지금까지 하던 대로(로컬 관리자 모드 표시, localStorage 기억값) 동작해야 한다.
 */

import { useSyncExternalStore } from "react";

/**
 * 계약서 §8 이 정한 이름. `lib/session.ts` 에도 같은 상수가 있지만 **거기서 가져오지 않는다** —
 * 그 모듈은 세션 서명 키를 다루는 서버 쪽 코드이고, 이 파일은 브라우저 번들에 들어간다.
 * 이름을 바꿀 일은 없다(바꾸면 계약이 깨진다).
 */
export const USER_COOKIE = "bidpilot_user";

export type UserRole = "viewer" | "editor" | "admin";

/** 화면에는 영문 enum 을 쓰지 않는다. */
export const ROLE_LABELS: Record<UserRole, string> = {
  viewer: "열람자",
  editor: "편집자",
  admin: "관리자",
};

export interface CurrentUser {
  /** 계정 아이디 */
  user: string;
  role: UserRole;
  /** 표시 이름 (예: 홍길동) */
  displayName: string;
  /** 세션 만료(밀리초 · 43차 M28) — 옛 쿠키에는 없다(null). 「5분 안에 끝납니다」 안내에만 쓴다. */
  expiresAt: number | null;
}

function isRole(value: unknown): value is UserRole {
  return value === "viewer" || value === "editor" || value === "admin";
}

/** 쿠키 값 → 사용자. 모양이 조금이라도 다르면 null 이다 (반쪽 신원을 믿지 않는다). */
export function parseUserCookie(raw: string | null): CurrentUser | null {
  if (!raw) return null;
  let decoded: unknown;
  try {
    decoded = JSON.parse(decodeURIComponent(raw));
  } catch {
    return null;
  }
  if (typeof decoded !== "object" || decoded === null) return null;
  const { u, r, n, e } = decoded as { u?: unknown; r?: unknown; n?: unknown; e?: unknown };
  if (typeof u !== "string" || u.length === 0) return null;
  if (!isRole(r)) return null;
  // 표시 이름이 비어 있으면 아이디로 대신한다 — 「 · 편집자」처럼 이름 없이 찍히지 않게.
  const displayName = typeof n === "string" && n.trim().length > 0 ? n.trim() : u;
  return { user: u, role: r, displayName, expiresAt: typeof e === "number" && Number.isFinite(e) ? e * 1000 : null };
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) return part.slice(prefix.length);
  }
  return null;
}

/** 브라우저에서만 값이 있다. 서버 렌더에서는 null. */
export function readCurrentUser(): CurrentUser | null {
  return withLive(parseUserCookie(readCookie(USER_COOKIE)));
}

/**
 * 폼의 담당자 기본값으로 쓸 이름. 로그인하지 않았으면 빈 문자열이다.
 * 호출부는 `currentUserName() || 기존_기억값()` 으로 쓴다 — 로컬 동작을 없애지 않는다.
 */
export function currentUserName(): string {
  return readCurrentUser()?.displayName ?? "";
}

/**
 * 서버가 지금 보는 역할 · 이름(45차 M4 · `GET /api/auth/me` — `users.json` 기준).
 *
 * 관리자가 역할을 바꾸면 서버는 바로 막는데 표시 쿠키는 로그인 때 사진이라, 머리 「이름 · 역할」과 열람자 잠금이
 * 다시 로그인할 때까지 옛 역할이었다. 화면이 처음 구독할 때 · 창으로 돌아올 때(1분에 한 번까지) 읽어 덮어쓴다.
 * 쿠키가 없으면(게이트 없는 로컬) 부르지 않는다. 이것도 표시용이다 — 막는 일은 서버가 한다.
 */
let live: { user: string; role: UserRole; displayName: string | null } | null = null;
let liveCheckedAt = 0;
const listeners = new Set<() => void>();

async function refreshLive(): Promise<void> {
  if (readCookie(USER_COOKIE) === null || Date.now() - liveCheckedAt < 60_000) return;
  liveCheckedAt = Date.now();
  try {
    const response = await fetch("/api/auth/me", { cache: "no-store" });
    if (!response.ok) return;
    const data = (await response.json()) as { user?: unknown; role?: unknown; display_name?: unknown };
    if (typeof data.user !== "string" || !isRole(data.role)) return;
    const name = typeof data.display_name === "string" && data.display_name.trim() ? data.display_name.trim() : null;
    if (live?.user === data.user && live.role === data.role && live.displayName === name) return;
    live = { user: data.user, role: data.role, displayName: name };
    listeners.forEach((notify) => notify());
  } catch {
    // 못 읽으면 쿠키 값 그대로 — 표시만 늦을 뿐 막는 일은 서버가 한다
  }
}

function onFocus(): void {
  void refreshLive();
}

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  if (listeners.size === 1 && typeof window !== "undefined") {
    window.addEventListener("focus", onFocus);
    void refreshLive();
  }
  return () => {
    listeners.delete(notify);
    if (listeners.size === 0 && typeof window !== "undefined") window.removeEventListener("focus", onFocus);
  };
}

function getSnapshot(): string {
  const raw = readCookie(USER_COOKIE) ?? "";
  return live ? `${raw}|${live.user}|${live.role}|${live.displayName ?? ""}` : raw;
}

/** 쿠키 사용자에 서버가 본 역할 · 이름을 덮는다(같은 아이디일 때만). */
function withLive(user: CurrentUser | null): CurrentUser | null {
  if (!user || !live || live.user !== user.user) return user;
  return { ...user, role: live.role, displayName: live.displayName ?? user.displayName };
}

/** 정적으로 prerender 되는 화면이 많다. 서버에서는 모른다고 답해 hydration 불일치를 막는다. */
function getServerSnapshot(): string {
  return "";
}

export function useCurrentUser(): CurrentUser | null {
  const raw = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return withLive(parseUserCookie(raw.split("|")[0] || null));
}
