"use client";

import Link from "next/link";

import { Button, EmptyState } from "@/components/ui/primitives";

/**
 * 화면 코드 예외 — 기본 오류 화면에는 메뉴도 돌아갈 길도 없었다 (CMN-13).
 * 공통 머리(AppShell)는 쓰지 않는다 — 머리에서 난 예외면 여기서 또 난다.
 */
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="mc-page-bg flex min-h-dvh items-center justify-center px-4 py-10 font-sans text-cosmos-text">
      <EmptyState
        tone="warn"
        title="화면을 그리다 문제가 생겼습니다"
        action={
          <span className="flex flex-wrap items-center justify-center gap-3">
            <Button size="sm" onClick={reset}>
              다시 그리기
            </Button>
            <Link href="/" className="mc-focus rounded text-[13px] font-medium text-cosmos-cyan underline-offset-2 hover:underline">
              대시보드로 →
            </Link>
          </span>
        }
      >
        저장된 자료는 그대로입니다. 다시 그려도 계속되면 관리자에게 알려 주세요.
      </EmptyState>
    </main>
  );
}
