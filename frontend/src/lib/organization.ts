"use client";

/**
 * 현재 선택한 회사(organization_id)와 분석 컨텍스트.
 *
 * - 선택은 브라우저 localStorage `bidpilot.organization.v1` 에 남는다 (튜토리얼·안내 기록과 키가 겹치지 않는다).
 * - 서버 렌더·hydration 중에는 기본 조직으로 두고, mount 뒤 useSyncExternalStore 가 저장값으로 갈아탄다.
 * - 근거 범위: 공개 배포(데모 모드)는 항상 public_demo, 합성 데모 공고(`synthetic-*`)도 public_demo, 그 밖에는 internal.
 *   실제 회사자료와 합성 데모자료를 조용히 섞지 않는다.
 */

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { describeFailure } from "@/lib/errors";
import { listOrganizations } from "@/lib/api";
// 스냅샷 JSON(6MB)을 브라우저 번들에 끌어오지 않도록 가벼운 모듈에서 가져온다.
import { demoMode } from "@/lib/demoMode";
import { SYNTHETIC_COMPANY } from "@/lib/terms";
import type { AnalysisContextParams, EvidenceScope, EvidenceScopeInfo, OrganizationListResponse, OrganizationSummary, ScopedResult } from "@/types/organization";

export const ORGANIZATION_STORAGE_KEY = "bidpilot.organization.v1";
/** 기본 회사 — 키트는 `NEXT_PUBLIC_DEFAULT_ORGANIZATION_ID` 로 바꾼다(30차 §3-G · 없으면 그대로 org-sample). */
export const DEFAULT_ORGANIZATION_ID = process.env.NEXT_PUBLIC_DEFAULT_ORGANIZATION_ID || "org-sample";
const ORG_ID_RE = /^org-(?!-)(?:[a-z0-9]+-?){2,48}(?<!-)$/;

const listeners = new Set<() => void>();

export function readOrganizationId(): string {
  try {
    const raw = window.localStorage.getItem(ORGANIZATION_STORAGE_KEY);
    if (raw && ORG_ID_RE.test(raw)) return raw;
  } catch {
    // 저장소 접근 불가 — 기본 조직
  }
  return DEFAULT_ORGANIZATION_ID;
}

export function setOrganizationId(id: string): void {
  if (!ORG_ID_RE.test(id)) return;
  try {
    window.localStorage.setItem(ORGANIZATION_STORAGE_KEY, id);
  } catch {
    // 무시
  }
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

const getServer = () => DEFAULT_ORGANIZATION_ID;

/** 현재 선택한 회사 id. hydration 중에는 기본 조직. */
export function useOrganizationId(): string {
  return useSyncExternalStore(subscribe, readOrganizationId, getServer);
}

/** 공고 분석에 붙일 회사·근거 범위. */
export function analysisContext(procurementId: string, organizationId: string): AnalysisContextParams {
  const scope: AnalysisContextParams["evidence_scope"] =
    demoMode() || procurementId.startsWith("synthetic-") ? "public_demo" : "internal";
  return { organization_id: organizationId, evidence_scope: scope };
}

export interface OrganizationsState {
  list: OrganizationListResponse | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** 조직 목록 (best-effort). 실패해도 화면은 기본 조직으로 동작한다. */
export function useOrganizations(): OrganizationsState {
  const [list, setList] = useState<OrganizationListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    listOrganizations().then(
      (value) => {
        if (cancelled) return;
        setList(value);
        setError(null);
        setLoading(false);
      },
      (err: unknown) => {
        if (cancelled) return;
        setError(describeFailure(err, "회사 목록을 불러오지 못했습니다."));
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { list, error, loading, reload };
}

export function findOrganization(list: OrganizationListResponse | null, id: string): OrganizationSummary | null {
  return list?.organizations.find((o) => o.organization.organization_id === id) ?? null;
}

export function organizationName(list: OrganizationListResponse | null, id: string): string {
  return findOrganization(list, id)?.organization.display_name ?? (id === DEFAULT_ORGANIZATION_ID ? "주식회사 샘플에듀" : id);
}

/**
 * 실제 회사 결과에 합성(가상) 근거가 섞였는가 (ISSUE-018 · TASK-017).
 *
 * 섞였으면 그 초안은 제출용이 될 수 없다. 문장의 근거가 「(합성)」 문서이기 때문이다.
 * 사유 문장을 돌려주고(없으면 null), 화면은 내려받기를 막는 데 쓴다.
 *
 * 지금 생성 경로는 internal 범위에서 합성 연결을 읽지 않는다. 그 규칙이 생기기 전에
 * 저장된 초안이 남아 있어서 필요한 검사다 — 저장본을 고치지 않고 읽을 때 판정한다.
 */
export function syntheticMixLock(
  result: (ScopedResult & { evidence_summary?: EvidenceScopeInfo | Record<string, unknown> | null }) | null | undefined,
): string | null {
  if (!result) return null;
  const summary = (result.evidence_summary ?? null) as EvidenceScopeInfo | null;
  if (!summary?.synthetic_evidence_used) return null;
  // 레거시(옛 공개 위치) 결과는 실제 회사 화면에서 대체 표시된 것이다. 실측에서 상단 배지가
  // 「내부 승인자료 · 합성 데모자료 · 레거시」로 나온 경우가 정확히 이것이었다 — 화면은
  // 실제 회사인데 인용된 근거는 「(합성)」 문서였다. 그 초안도 내려받게 두면 안 된다.
  if (!result.legacy_result && result.evidence_scope !== "internal") return null;
  // 10-31 최종 점검 — 서버 메모(「레거시 공개 결과 — 현재 조직의 … 없어 표시」 · 끝나지 않은 문장)를 그대로 싣지 않는다 — 쉬운 말 한 문장
  return "이 초안은 가상 예시 회사자료를 근거로 인용하고 있습니다. 이 회사의 승인된 자료로 다시 생성하세요.";
}

/** 결과 객체의 회사·범위 표시 문구 — 배지용. */
export function scopeBadge(result: (ScopedResult & { evidence_summary?: EvidenceScopeInfo | Record<string, unknown> | null }) | null | undefined): {
  label: string;
  tone: "ok" | "demo" | "warn" | "muted";
  detail: string;
} {
  if (!result) return { label: "아직 안 함", tone: "muted", detail: "분석 결과 없음" };
  const summary = (result.evidence_summary ?? null) as EvidenceScopeInfo | null;
  if (result.legacy_result) {
    return { label: `${SYNTHETIC_COMPANY} · 레거시`, tone: "warn", detail: "현재 회사의 내부 분석 결과가 아직 없어 예전 공개 결과를 표시합니다. 재분석이 필요합니다." };
  }
  const scope: EvidenceScope | null | undefined = result.evidence_scope;
  // 실제 회사 결과에 합성 근거가 섞였으면 그것이 «유일한» 상태다 — 다른 무엇보다 먼저 말한다.
  const mixed = syntheticMixLock(result);
  if (mixed) return { label: "재생성 필요", tone: "warn", detail: mixed };
  if (summary?.real_evidence_used) return { label: "내부 승인자료", tone: "ok", detail: `승인 문서 ${summary.used_document_count}건 · 문단 ${summary.used_chunk_count}건` };
  if (summary?.synthetic_evidence_used || scope === "public_demo") return { label: SYNTHETIC_COMPANY, tone: "demo", detail: "가상 예시 회사자료만 사용 — 실제 회사자료 아님" };
  /**
   * 근거가 하나도 붙지 않았다. **왜** 그런지가 중요하다.
   *
   * 예전 라벨 「내부 승인자료 · 근거 없음」은 두 상태를 한 줄에 이어 붙인 것이라,
   * 화면에서 회사 이름·범위 칩과 겹쳐 「내부 승인자료 · 내부 승인자료 · 근거 없음」처럼 보였다.
   * 상태는 하나만 말하고, 사유는 서버가 준 note 를 그대로 쓴다(키 거부·자료 미등록 등).
   */
  if (scope === "internal") {
    return {
      label: "근거 없음",
      tone: "warn",
      detail: summary?.note ?? "이 회사의 승인·색인된 근거가 매칭되지 않았습니다",
    };
  }
  return { label: "범위 미표시", tone: "muted", detail: "회사·범위 정보가 없는 결과" };
}
