import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SCREEN_NAMES } from "@/lib/terms";

// 탭 제목만 준다 — 화면(page.tsx)이 클라이언트 컴포넌트라 metadata 를 못 낸다 (CMN-12).
export const metadata: Metadata = { title: `${SCREEN_NAMES.plan} · BidPilot AI` };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
