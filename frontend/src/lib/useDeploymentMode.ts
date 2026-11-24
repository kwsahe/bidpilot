"use client";

/**
 * 지금 이 배포본이 무엇인지 화면에서 읽는다.
 *
 * 미들웨어가 매 요청마다 쿠키에 찍어 둔 값을 그대로 읽을 뿐, 여기서 다시 판정하지 않는다.
 * 판정 규칙은 lib/deploymentMode.ts 한 곳에만 있다.
 *
 * 왜 쿠키인가 — 주요 화면이 정적으로 prerender 되기 때문이다. 서버 컴포넌트로는
 * 런타임 환경변수를 읽을 수 없고, /health 를 부르면 왕복이 한 번 더 들며 그동안
 * 화면이 틀린 문구를 보여준다. 쿠키는 첫 렌더에서 바로 읽힌다.
 *
 * 쿠키가 없을 수도 있다(미들웨어를 타지 않는 경로, 쿠키 차단). 그때는 **null** 이며,
 * 호출부는 모드에 기대는 문장을 아예 렌더하지 않는다 — 모르면 단정하지 않는다.
 */

import { useSyncExternalStore } from "react";

import { MODE_COOKIE, decodeMode, type DeploymentMode } from "@/lib/deploymentMode";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return null;
}

/** 쿠키는 조용히 바뀌지 않는다 — 구독은 아무것도 하지 않고, 값은 렌더마다 읽는다. */
function subscribe(): () => void {
  return () => {};
}

function getSnapshot(): string {
  return readCookie(MODE_COOKIE) ?? "";
}

/** 서버 렌더(정적 생성 포함)에서는 알 수 없다. hydration 불일치를 피하려고 빈 값을 준다. */
function getServerSnapshot(): string {
  return "";
}

export function useDeploymentMode(): DeploymentMode | null {
  const raw = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return decodeMode(raw);
}
