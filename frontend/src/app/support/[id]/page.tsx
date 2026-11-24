import type { Metadata } from "next";

import SupportShell from "@/components/support/SupportShell";

/**
 * 기업마당 지원사업 **신청** 분석 (`/support/[id]`).
 *
 * 통합 사업기회 목록에서 지원사업을 고르면 `next_route.path` 가 이 경로로 온다.
 * 나라장터 입찰공고는 `/analysis?notice=<id>` (Mission Control)로 가며 흐름·용어가 다르다.
 *
 * Next 16 App Router: 동적 세그먼트 `params` 는 Promise 라서 await 해야 한다
 * (node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/dynamic-routes.md).
 * 아직 라우트 타입이 생성되기 전이므로 전역 `PageProps<'/support/[id]'>` 대신
 * 문서에 함께 명시된 명시적 `params: Promise<{ id: string }>` 형태를 쓴다.
 */

export const metadata: Metadata = {
  title: "지원사업 신청 분석 · BidPilot AI",
  description:
    "기업마당 지원사업의 신청자격·필수조건·신청기간·제출서류를 원문 근거와 함께 정리하고, 승인된 회사자료로 사업계획서 뼈대를 만듭니다.",
};

export default async function SupportProgramPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SupportShell programId={id} />;
}
