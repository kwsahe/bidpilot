import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SCREEN_NAMES } from "@/lib/terms";

// 탭 제목 — 다른 화면과 같은 꼴(CMN-12).
export const metadata: Metadata = { title: `${SCREEN_NAMES.guide} · BidPilot AI` };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
