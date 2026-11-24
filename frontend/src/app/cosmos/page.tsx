"use client";

import DashboardShell from "@/components/cosmos/DashboardShell";

/**
 * Evidence Cosmos 대시보드의 고정 경로 별칭.
 *
 * 기본 진입점은 계속 "/"다. 다만 와이어프레임 전용 서버(포트 4120)에서는 "/"가
 * /wireframe 으로 rewrite되므로(next.config.ts), 그 서버에서도 Cosmos로 건너갈
 * 주소가 하나 필요하다. 두 포트 모두에서 통하는 링크가 이 경로다.
 */
export default function CosmosAliasPage() {
  return <DashboardShell />;
}
