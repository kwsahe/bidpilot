import Link from "next/link";

import AppShell from "@/components/ui/AppShell";
import { EmptyState } from "@/components/ui/primitives";

/**
 * 없는 주소 — Next 기본 영어 화면(「404 This page could not be found.」)에는 메뉴도 돌아갈 길도 없었다 (CMN-13).
 * 운영 빌드의 /wireframe(개발 전용)도 여기로 온다.
 */
export default function NotFound() {
  return (
    <AppShell>
      <EmptyState
        title="찾는 화면이 없습니다"
        action={
          <span className="flex flex-wrap justify-center gap-3 text-[13px] font-medium text-cosmos-cyan">
            <Link href="/" className="mc-focus rounded underline-offset-2 hover:underline">
              대시보드로 →
            </Link>
            <Link href="/opportunities" className="mc-focus rounded underline-offset-2 hover:underline">
              사업기회 목록 →
            </Link>
          </span>
        }
      >
        주소가 바뀌었거나 없는 화면입니다. 위 메뉴나 아래 링크로 이동하세요.
      </EmptyState>
    </AppShell>
  );
}
