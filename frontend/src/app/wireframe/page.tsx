import type { Metadata } from "next";
import { notFound } from "next/navigation";

import WireframeShell from "@/components/wireframe/WireframeShell";

// 대시보드 와이어프레임 ("/wireframe").
// Evidence Cosmos("/")와 같은 backend API를 쓰되, 화면은 설계 단계 목업으로 그린다.
export const metadata: Metadata = {
  title: "와이어프레임 · BidPilot AI",
  description:
    "공고 → 자격 → 요구사항 → 증빙 → 제안서 → 역검증 전체 화면 설계 목업 (실 backend 연동)",
};

/**
 * 설계 단계 목업. **개발 환경에서만 연다** (ISSUE-043 · TASK-022).
 *
 * 배포본에도 이 라우트가 그대로 실려 있었다. 담당자가 우연히 들어가면 실제 화면과
 * 다른 목업을 보고 「이게 진짜 화면인가」를 헷갈린다. 지우지는 않는다 — 설계 대조에
 * 아직 쓰인다(포트 4120 전용 서버가 이 화면을 기본으로 띄운다).
 */
export default function WireframePage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <WireframeShell />;
}
