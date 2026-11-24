"use client";

/**
 * 고른 회사의 「곧 만료 · 만료됨」 서류(32차 R31-10) — 접힌 「오늘 · 이번 주」 띠 머리와 쉬운 보기 첫 화면이 같이 쓴다.
 * 예전에는 전체 보기의 펼친 띠 안에만 있어 기본 상태에서 보이지 않았다. 못 읽으면 빈 목록(부가 안내다).
 */

import { useEffect, useState } from "react";

import { getDeliveryCapacity } from "@/lib/api";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { expiringCredentials } from "@/lib/firstTimeGuide";
import { analysisContext } from "@/lib/organization";
import type { DeliveryCapacityCredential } from "@/types/capability";

export function useExpiringCredentials(organizationId: string) {
  const nowMs = useNowMs();
  const [loaded, setLoaded] = useState<{ org: string; credentials: DeliveryCapacityCredential[] } | null>(null);
  useEffect(() => {
    let alive = true;
    getDeliveryCapacity(analysisContext("", organizationId))
      .then((capacity) => {
        if (alive) setLoaded({ org: organizationId, credentials: capacity.credentials ?? [] });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [organizationId]);
  if (!loaded || loaded.org !== organizationId || nowMs === null) return [];
  return expiringCredentials(loaded.credentials, nowMs);
}
