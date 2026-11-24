/**
 * 로그인 화면.
 *
 * 서버 컴포넌트다 — 안내 문구가 실제 런타임 모드에 따라 갈려야 하는데,
 * 정적으로 prerender 되면 빌드 시점 값이 굳어 버리기 때문에 요청마다 렌더한다.
 * 실데이터 여부는 미들웨어(proxy.ts backendMode)와 같은 판정이다 — 중계(사내)든 직접 연결(로컬)이든 실데이터이고,
 * 「읽기 전용」은 스냅샷 배포(NEXT_PUBLIC_DEMO_MODE=1)일 때만 참이다 (CMN-14).
 * 게이트가 꺼져 있으면 로그인할 것이 없다 — 폼 대신 대시보드로 보낸다 (CMN-15).
 */

import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { proxyEnabled } from "@/lib/backendProxy";
import { gateEnabled } from "@/lib/demoAuth";
import { demoMode } from "@/lib/demoMode";

import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "로그인 · BidPilot AI" };

export default function LoginPage() {
  if (!gateEnabled()) redirect("/");
  const realBackend = proxyEnabled() || !demoMode();

  return (
    <main className="flex min-h-screen items-center justify-center bg-cosmos-bg px-6 py-12">
      <Suspense fallback={null}>
        <LoginForm realBackend={realBackend} />
      </Suspense>
    </main>
  );
}
