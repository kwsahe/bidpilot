/**
 * 기업마당 응답의 출처 → 배지 · 말 **하나**(34차 R33-A2). 신청 분석 화면 · 쉬운 보기 · 대시보드 전체 보기 · 3D 지도 머리가
 * 이것만 쓴다 — 대시보드가 따로 갈라 목록에서 빠진 실공고 사본을 「가상 예시 공고」로 적었다. 나라장터 라벨은 쓰지 않는다.
 */

import type { SourceKind } from "@/components/ui/SourceBadge";
import { CACHE_TERM, SYNTHETIC_NOTICE } from "@/lib/terms";

/** 백엔드 `support_application_service.ARCHIVED_NOTE` 의 머리 — 새 초안 409 가 이 사유면 「바쁨」이 아니라 실패다(R33-A3). */
export const ARCHIVED_CLOSED_MARK = "마감된 공고";

export function supportSourceBadge(source: string, archivedClosed?: boolean): { kind: SourceKind; label: string } {
  if (source === "bizinfo") return { kind: "computed", label: "기업마당 실시간" };
  if (source === "cached") return { kind: "cached", label: `기업마당 ${CACHE_TERM}` };
  if (source === "sample") return { kind: "demo", label: SYNTHETIC_NOTICE };
  // 목록에서 빠진 사업을 남겨 둔 공고 정보로 보이는 중 — 마감일이 지났을 때만 「마감」(33차 §3-A-6 · 34차 R33-A1)
  if (source === "archived") return { kind: "cached", label: `기업마당 ${CACHE_TERM}(${archivedClosed ? "마감" : "목록에서 내려감"})` };
  return { kind: "not_run", label: `출처 ${source}` };
}
