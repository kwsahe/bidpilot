"use client";

/**
 * 실전 가이드 화면의 브라우저 쪽 부품(32차 §3-A) — 회사 고르기 · 기준일 경과 · 인쇄 · 앵커 초점 · 회사 「준비 상태」 읽기.
 *
 * 「준비 상태」는 **읽기만** 한다(고치는 곳은 회사자료 `#readiness`). 참가 판정에는 중소기업(소상공인) 확인서 줄만 쓴다(READINESS_HELP · 10-10).
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { Badge, Button, InlineAlert } from "@/components/ui/primitives";
import { getDeliveryCapacity } from "@/lib/api";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { readinessRows, validityOf } from "@/lib/firstTimeGuide";
import { daysSince, READINESS_GUIDE } from "@/lib/guide";
import { analysisContext, organizationName, useOrganizationId, useOrganizations } from "@/lib/organization";
import {
  EXPIRED_HEAD,
  EXPIRING_SOON_HEAD,
  GENERAL_GUIDE_NOTE,
  GUIDE_LEGAL_NOTE,
  GUIDE_NO_RECORD_NOTE,
  GUIDE_READINESS_TITLE,
  READINESS_HELD_LABELS,
  READINESS_HELP,
} from "@/lib/terms";
import type { DeliveryCapacityCredential } from "@/types/capability";

export function GuideOrganizationPicker() {
  const organizations = useOrganizations();
  const organizationId = useOrganizationId();
  return <OrganizationPicker id="guide-organization" list={organizations.list} organizationId={organizationId} />;
}

/** 머리 — 기준일 · 지난 날 수 · 해가 바뀌면 「YYYY년 기준 숫자」 띠 · 법률 자문 아님 · 공고문이 우선. */
export function GuideNotice({ baseDate }: { baseDate: string | null }) {
  const nowMs = useNowMs();
  const passed = nowMs === null ? null : daysSince(baseDate, nowMs);
  const baseYear = baseDate ? Number(baseDate.slice(0, 4)) : null;
  const thisYear = nowMs === null ? null : new Date(nowMs).getFullYear();
  return (
    <div className="flex flex-col gap-2 print:hidden" data-guide-notice>
      <p className="text-[14px] leading-6 text-cosmos-secondary">
        <span className="font-semibold text-cosmos-text">기준일 {baseDate ?? "—"}</span>
        {passed !== null && <span> · 오늘까지 {passed}일 지남</span>}
        <span> · {GUIDE_LEGAL_NOTE}</span>
      </p>
      {baseYear !== null && thisYear !== null && thisYear > baseYear && (
        <InlineAlert tone="warn" role="status">
          {baseYear}년 기준 숫자입니다 — 금액 · 일정 · 기간은 올해 공고와 기관 안내에서 다시 확인하세요.
        </InlineAlert>
      )}
    </div>
  );
}

/** 인쇄 단추 둘 — 전체 · 처음 준비 체크리스트만. 인쇄 전에 접힌 칸을 펼치고 인쇄한 날을 적는다. */
export function GuidePrintButtons() {
  useEffect(() => {
    const before = () => {
      document.querySelectorAll<HTMLDetailsElement>(".guide-doc details").forEach((d) => {
        if (!d.open) {
          d.dataset.printOpened = "1";
          d.open = true;
        }
      });
      const today = new Date().toLocaleDateString("sv-SE");
      document.querySelectorAll<HTMLElement>("[data-print-date]").forEach((el) => {
        el.textContent = today;
      });
    };
    const after = () => {
      document.querySelectorAll<HTMLDetailsElement>(".guide-doc details[data-print-opened]").forEach((d) => {
        d.open = false;
        delete d.dataset.printOpened;
      });
      delete document.documentElement.dataset.printScope;
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);
  const print = (scope: "all" | "checklist") => {
    if (scope === "checklist") document.documentElement.dataset.printScope = "checklist";
    window.print();
  };
  return (
    <div className="flex flex-wrap gap-2 print:hidden">
      <Button size="sm" variant="secondary" onClick={() => print("all")}>
        인쇄
      </Button>
      <Button size="sm" variant="secondary" onClick={() => print("checklist")}>
        처음 준비 체크리스트만 인쇄
      </Button>
    </div>
  );
}

/** 주소의 `#g-…` 로 온 뒤 그 제목에 초점 — 화면 읽기 프로그램도 그 자리부터 읽는다. */
export function GuideHashFocus() {
  useEffect(() => {
    const focus = () => {
      // 깨진 해시(`#g-1-7%`)는 디코딩이 던진다 — 가이드 전체가 오류 화면이 되지 않게 그냥 맨 위(33차 §3-E G4)
      let id = "";
      try {
        id = decodeURIComponent(window.location.hash.slice(1));
      } catch {
        return;
      }
      if (!id) return;
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ block: "start" });
        el.focus({ preventScroll: true });
        // 위쪽 「준비 상태」가 늦게 그려지며 높이가 줄어 제목이 머리 밑으로 올라갔다(33차 §3-E G2 실측 -10px).
        // 사람이 그새 스크롤하지 않았을 때만 한 번 더 맞춘다.
        const y = window.scrollY;
        settle = window.setTimeout(() => {
          if (window.scrollY === y) el.scrollIntoView({ block: "start" });
        }, 1200);
      }
    };
    let settle = 0;
    focus();
    window.addEventListener("hashchange", focus);
    return () => {
      window.clearTimeout(settle);
      window.removeEventListener("hashchange", focus);
    };
  }, []);
  return null;
}

type ReadinessState = { status: "loading" } | { status: "failed"; message: string } | { status: "ready"; credentials: DeliveryCapacityCredential[] };

/** 0-2 옆 — 고른 회사의 「준비 상태」(읽기만). */
export function GuideReadiness() {
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();
  const nowMs = useNowMs();
  // 읽은 결과를 회사 id 와 함께 둔다 — 회사를 바꾸면 그 회사 결과가 올 때까지 「읽는 중」(effect 안에서 상태를 비우지 않는다)
  const [loaded, setLoaded] = useState<{ org: string; credentials?: DeliveryCapacityCredential[]; error?: string } | null>(null);

  useEffect(() => {
    let alive = true;
    getDeliveryCapacity(analysisContext("", organizationId))
      .then((capacity) => {
        if (alive) setLoaded({ org: organizationId, credentials: capacity.credentials ?? [] });
      })
      .catch((error: unknown) => {
        if (alive) setLoaded({ org: organizationId, error: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      alive = false;
    };
  }, [organizationId]);
  const state: ReadinessState =
    !loaded || loaded.org !== organizationId
      ? { status: "loading" }
      : loaded.error !== undefined
        ? { status: "failed", message: loaded.error }
        : { status: "ready", credentials: loaded.credentials ?? [] };

  const company = organizationName(organizations.list, organizationId);
  return (
    <aside
      data-guide-readiness
      aria-label={GUIDE_READINESS_TITLE}
      className="my-4 flex flex-col gap-3 rounded-xl border border-cosmos-cyan/40 bg-cosmos-cyan/5 p-4 print:border-black"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-[15px] font-semibold text-cosmos-text">
          {GUIDE_READINESS_TITLE} — {company}
        </h4>
        <Link href="/company#readiness" className="mc-focus text-[14px] text-cosmos-cyan underline-offset-2 hover:underline print:hidden">
          회사자료에서 고치기 →
        </Link>
      </div>
      {state.status === "failed" && (
        <InlineAlert tone="warn" role="status">
          준비 상태를 읽지 못했습니다 — {state.message} (회사자료 화면에서 직접 보세요)
        </InlineAlert>
      )}
      {/* 읽는 동안에도 기본 일곱 줄을 그려 둔다 — 늦게 채워지며 아래 절이 밀려 앵커 자리가 어긋났다 */}
      {state.status !== "failed" && (
        <ul className="flex flex-col divide-y divide-cosmos-border/60 text-[14px]" aria-busy={state.status === "loading"}>
          {readinessRows(state.status === "ready" ? state.credentials : []).map((row) => {
            const held =
              state.status === "loading"
                ? "읽는 중"
                : row.held === true
                  ? READINESS_HELD_LABELS.yes
                  : row.held === false
                    ? READINESS_HELD_LABELS.no
                    : READINESS_HELD_LABELS.unknown;
            const validity = nowMs === null ? null : validityOf(row.validUntil, nowMs);
            const guide = READINESS_GUIDE[row.label];
            return (
              <li key={row.label} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2" data-readiness-row={row.label}>
                <span className="min-w-[12rem] flex-1 text-cosmos-text">
                  {guide ? (
                    <a href={guide.slice(guide.indexOf("#"))} className="mc-focus underline-offset-2 hover:underline">
                      {row.label}
                    </a>
                  ) : (
                    row.label
                  )}
                </span>
                <Badge tone={row.held === true ? "pass" : row.held === false ? "fail" : "muted"}>{held}</Badge>
                {row.validUntil && <span className="text-cosmos-secondary">유효기간 {row.validUntil}</span>}
                {validity === "soon" && <Badge tone="warn">{EXPIRING_SOON_HEAD}</Badge>}
                {validity === "expired" && <Badge tone="fail">{EXPIRED_HEAD}</Badge>}
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-[13px] leading-6 text-cosmos-muted">
        {READINESS_HELP} {GUIDE_NO_RECORD_NOTE} {GENERAL_GUIDE_NOTE}.
      </p>
    </aside>
  );
}
