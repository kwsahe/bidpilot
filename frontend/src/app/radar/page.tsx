import type { Metadata } from "next";

import RadarShell from "@/components/radar/RadarShell";

/**
 * 사업기회 레이더 — 나라장터 입찰공고 + 기업마당 지원사업을 한 그림에서 본다.
 *
 * 화면 조립은 전부 클라이언트 컴포넌트(RadarShell)가 한다.
 * 여기서는 라우트와 메타데이터만 둔다.
 */

export const metadata: Metadata = {
  title: "사업기회 레이더 · BidPilot AI",
  description:
    "나라장터 입찰공고와 기업마당 지원사업을 현재 회사 기준 검토 우선순위로 한 화면에서 봅니다.",
};

export default function RadarPage() {
  return <RadarShell />;
}
