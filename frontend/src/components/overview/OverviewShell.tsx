"use client";

/**
 * 대시보드 — 사업기회 통계 (2.1.0 · 대표 결정 2026-10-28).
 *
 * 대표 「대시보드는 사업기회 통계로 — 오늘 지원 가능한 사업 / 오늘 추가된 공고 / 오늘 마감된 공고 등으로」. 결정 셋:
 * 공고 분석 화면은 「입찰 분석」(/analysis)으로 옮김 · 「지금 검토할 사업」 + 그중 가능 · 오늘 + 기간 함께.
 *
 * 숫자는 사업기회 목록과 **같은 세 목록**(입찰 · 지원사업 · 통합 순위)을 **같은 함수**(`lib/opportunityRows`)로 센다 —
 * 숫자를 누르면 사업기회가 같은 조건으로 열리고 건수가 같다(2.0.6 원칙). 못 받은 출처는 0 이 아니라 「못 받음」이다.
 */

import Link from "next/link";
import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import ThisWeekPanel from "@/components/cosmos/ThisWeekPanel";
import WelcomeDialog from "@/components/cosmos/WelcomeDialog";
import CollectKeywordsPanel from "@/components/opportunities/CollectKeywordsPanel";
import AppShell from "@/components/ui/AppShell";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { InlineAlert, Spinner } from "@/components/ui/primitives";
import { getBusinessOpportunities, getPrepareSection, getProcurements, getSupportPrograms, getTodayDigest } from "@/lib/api";
import { keywordResultHref } from "@/lib/collectKeywords";
import { formatDateTime } from "@/lib/cosmos/format";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { useSeenRecord, WELCOME_STORAGE_KEY } from "@/lib/cosmos/useTutorial";
import { withinDaysText } from "@/lib/deadline";
import { describeFailure, sourceFailure } from "@/lib/errors";
import { OVERVIEW_DUE_DAYS, bizinfoRowsOf, g2bRowsOf, overviewCounts, type OverviewCounts } from "@/lib/opportunityRows";
import { useOrganizationId, useOrganizations } from "@/lib/organization";
import { usePeriodDays } from "@/lib/period";
import { SCREEN_NAMES, collectTerm, collectWarns } from "@/lib/terms";
import type { TodayDigest } from "@/types/digest";
import type { UnifiedOpportunity, UnifiedOpportunityListResponse } from "@/types/opportunity";
import type { ProcurementListResponse } from "@/types/procurement";
import type { SupportProgramListResponse } from "@/types/support";

type Source = "g2b" | "bizinfo";
const SOURCES: { key: Source; label: string }[] = [
  { key: "g2b", label: "나라장터 입찰" },
  { key: "bizinfo", label: "기업마당 지원사업" },
];

interface Lists {
  key: string;
  procurements: ProcurementListResponse | null;
  support: SupportProgramListResponse | null;
  unified: UnifiedOpportunityListResponse | null;
  errors: Partial<Record<Source | "unified", string>>;
}

/** 사업기회 목록과 같은 조건(`opportunities/page.tsx` · 조회 기간 · 관련 낮음 포함 · 통합 순위는 점수순 · 마감 뺌 · 불가 포함)으로 받는다. */
function fetchLists(organizationId: string, days: number): Promise<Omit<Lists, "key">> {
  return Promise.allSettled([
    getProcurements({ days, includeLow: true }),
    getSupportPrograms({ organizationId }),
    getBusinessOpportunities({ organizationId, source: "all", days, sort: "priority", includeClosed: false, includeBlocked: true }),
  ]).then(([procurements, support, unified]) => {
    const errors: Lists["errors"] = {};
    if (procurements.status === "rejected") errors.g2b = describeFailure(procurements.reason, "나라장터 목록을 받지 못했습니다.");
    if (support.status === "rejected") errors.bizinfo = describeFailure(support.reason, "기업마당 목록을 받지 못했습니다.");
    if (unified.status === "rejected") errors.unified = describeFailure(unified.reason, "판정 · 순위를 받지 못했습니다.");
    else
      for (const { key } of SOURCES) {
        const failed = sourceFailure(unified.value, key);
        if (failed && !errors[key]) errors[key] = failed;
      }
    return {
      procurements: procurements.status === "fulfilled" ? procurements.value : null,
      support: support.status === "fulfilled" ? support.value : null,
      unified: unified.status === "fulfilled" ? unified.value : null,
      errors,
    };
  });
}

/** `?welcome=0`(검사 · 시연 링크) — 입찰 분석(`DashboardShell`)과 같은 규칙으로 환영 창을 띄우지 않는다. 서버 렌더는 「띄움」. */
const subscribeNever = () => () => {};
const readWelcomeParam = () => new URLSearchParams(window.location.search).get("welcome") !== "0";
const readWelcomeParamServer = () => true;

function opportunitiesHref(source: Source, condition = ""): string {
  return `/opportunities?src=${source}${condition ? `&${condition}` : ""}`;
}

/** 숫자 하나 — 누르면 같은 조건의 사업기회 목록. 모르면(못 받음 · 읽는 중) 숫자 대신 「—」. */
function CountLink({ value, href, label, big = false }: { value: number | null; href: string; label: string; big?: boolean }) {
  const size = big ? "text-[30px] leading-9" : "text-[18px] leading-6";
  if (value === null) {
    return (
      <span className={`font-mono font-semibold tabular-nums text-cosmos-muted ${size}`} aria-label={`${label} — 모름`}>
        —
      </span>
    );
  }
  return (
    <Link
      href={href}
      aria-label={`${label} ${value}건 — ${SCREEN_NAMES.opportunities}에서 보기`}
      data-overview-count={href}
      className={`mc-focus rounded font-mono font-semibold tabular-nums underline-offset-4 hover:underline ${size} ${value > 0 ? "text-cosmos-text" : "text-cosmos-muted"}`}
    >
      {value}
    </Link>
  );
}

function StatPanel({ title, help, children }: { title: string; help: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="mc-panel flex flex-col gap-3 p-4">
      <div>
        <h2 className="text-[15px] font-semibold text-cosmos-text">{title}</h2>
        <p className="mt-0.5 text-[12.5px] text-cosmos-muted">{help}</p>
      </div>
      <dl className="flex flex-col gap-3">{children}</dl>
    </section>
  );
}

function SourceLine({ label, error, children }: { label: string; error: string | null; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-t border-cosmos-border pt-2 first:border-t-0 first:pt-0">
      <dt className="text-[13px] text-cosmos-secondary">{label}</dt>
      <dd className="flex flex-wrap items-baseline gap-x-4 gap-y-1">{error ? <span className="text-[13px] text-cosmos-amber">못 받음 — {error}</span> : children}</dd>
    </div>
  );
}

function Pair({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 text-[13px] text-cosmos-secondary">
      {label}
      {children}
    </span>
  );
}

export default function OverviewShell() {
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();
  const days = usePeriodDays();
  const nowMs = useNowMs();
  const welcome = useSeenRecord(WELCOME_STORAGE_KEY);
  const welcomeAllowed = useSyncExternalStore(subscribeNever, readWelcomeParam, readWelcomeParamServer);
  // 저장소 쓰기가 막힌 브라우저에서도 이번 방문 동안은 닫힌 채로(2.0.5 대시보드와 같은 규칙)
  const [welcomeClosed, setWelcomeClosed] = useState(false);
  const closeWelcome = () => {
    setWelcomeClosed(true);
    welcome.markSeen();
  };

  /** 「찾는 낱말」 바로 찾기로 새 공고가 들어오면 숫자 · 이번 주 할 일을 다시 받는다(2.0.7). */
  const [reloadTick, setReloadTick] = useState(0);
  const [keywordsOpen, setKeywordsOpen] = useState(false);
  const listKey = `${organizationId}|${days}|${reloadTick}`;
  const [lists, setLists] = useState<Lists | null>(null);
  const [digest, setDigest] = useState<TodayDigest | null>(null);
  const [prepare, setPrepare] = useState<{ key: string; count: number | null; error: string | null } | null>(null);

  useEffect(() => {
    let alive = true;
    void fetchLists(organizationId, days).then((value) => {
      if (alive) setLists({ key: listKey, ...value });
    });
    // 받은 때 한 줄 · 자동 받기 상태 — 부가 정보다. 못 받으면 그 줄만 비운다.
    getTodayDigest(organizationId).then(
      (value) => alive && setDigest(value),
      () => alive && setDigest(null),
    );
    getPrepareSection(organizationId, "main").then(
      (value) => alive && setPrepare({ key: listKey, count: value.items.length, error: value.source_error ?? null }),
      (failure: unknown) => alive && setPrepare({ key: listKey, count: null, error: describeFailure(failure, "선제준비 칸을 읽지 못했습니다.") }),
    );
    return () => {
      alive = false;
    };
  }, [organizationId, days, listKey]);

  const loaded = lists !== null && lists.key === listKey ? lists : null;
  const counts = useMemo<Partial<Record<Source, OverviewCounts>>>(() => {
    if (!loaded || nowMs === null) return {};
    const unifiedById = new Map<string, UnifiedOpportunity>((loaded.unified?.items ?? []).map((item) => [item.id, item]));
    const newDays = loaded.unified?.summary?.new_days ?? null;
    const out: Partial<Record<Source, OverviewCounts>> = {};
    if (loaded.procurements) out.g2b = overviewCounts(g2bRowsOf(loaded.procurements.notices, unifiedById, loaded.unified !== null), nowMs, newDays);
    if (loaded.support) out.bizinfo = overviewCounts(bizinfoRowsOf(loaded.support.items, unifiedById), nowMs, newDays);
    return out;
  }, [loaded, nowMs]);
  const newDays = loaded?.unified?.summary?.new_days ?? null;
  const errorOf = (source: Source): string | null => loaded?.errors[source] ?? null;
  const valueOf = (source: Source, pick: (c: OverviewCounts) => number | null): number | null => {
    const c = counts[source];
    return c && !errorOf(source) ? pick(c) : null;
  };
  const g2bPassZero = valueOf("g2b", (c) => c.pass) === 0;

  const headerAside = <OrganizationPicker id="overview-organization" list={organizations.list} organizationId={organizationId} />;

  return (
    <AppShell headerAside={headerAside}>
      {welcome.firstVisit && welcomeAllowed && !welcomeClosed && <WelcomeDialog onStart={closeWelcome} onLeave={closeWelcome} />}

      <header className="flex flex-col gap-1">
        <h1 className="text-[20px] font-semibold text-cosmos-text">{SCREEN_NAMES.dashboard}</h1>
        <p className="text-[13.5px] text-cosmos-secondary">
          오늘 검토할 사업 · 새 공고 · 마감이 다가오는 공고를 셉니다. 숫자를 누르면 같은 조건의 {SCREEN_NAMES.opportunities} 목록이 열립니다.
        </p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-cosmos-muted">
          {digest && (
            <span data-overview-fetched>
              목록 받은 때 {digest.fetched_at ? formatDateTime(digest.fetched_at) : "없음"}
              {digest.frozen && (
                <span className={collectWarns(digest.collect_state) ? "text-cosmos-amber" : undefined} data-auto-collect>
                  {" "}
                  · {collectTerm(digest.collect_state, digest.fetched_at)}
                </span>
              )}
            </span>
          )}
          <span>조회 기간 최근 {days}일</span>
          <button
            type="button"
            onClick={() => setKeywordsOpen((open) => !open)}
            aria-expanded={keywordsOpen}
            aria-controls={keywordsOpen ? "overview-keywords" : undefined}
            data-overview-keywords
            className="mc-focus flex min-h-7 items-center rounded-md border border-cosmos-border px-2 text-[13px] text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
          >
            찾는 낱말
          </button>
        </div>
      </header>

      {keywordsOpen && (
        <CollectKeywordsPanel
          id="overview-keywords"
          collectState={digest?.collect_state ?? null}
          onClose={() => setKeywordsOpen(false)}
          onSearched={(result) => {
            if (result.new_notices > 0) setReloadTick((n) => n + 1);
          }}
          resultAction={(result) =>
            result.found > 0 && (
              <Link href={keywordResultHref(result)} className="mc-focus rounded font-semibold text-cosmos-cyan underline underline-offset-2" data-keyword-result-link>
                {SCREEN_NAMES.opportunities}에서 결과 보기 →
              </Link>
            )
          }
        />
      )}

      {loaded?.errors.unified && (
        <InlineAlert tone="warn">
          {loaded.errors.unified} 판정이 없어 참가 불가 · 관련 낮음을 가르지 못하므로 숫자를 적지 않았습니다 — 잠시 뒤 새로고침해 주세요.
        </InlineAlert>
      )}

      {/* 읽는 동안 숫자 칸이 「—」뿐이면 멈춘 것처럼 보였다(2.1.1 · 대표 10-30) — 목록 셋이 크고, 노트북 앱은 켠 뒤 첫 화면을 그때 빌드한다 */}
      {(loaded === null || nowMs === null) && (
        <p role="status" aria-live="polite" data-overview-loading className="flex items-center gap-2 text-[13.5px] text-cosmos-secondary">
          <Spinner />
          사업기회 목록을 불러오는 중입니다 — 앱을 켠 뒤 처음 열 때는 조금 더 걸립니다.
        </p>
      )}

      <div className="grid gap-3 lg:grid-cols-3" data-overview-stats aria-busy={loaded === null || nowMs === null}>
        <StatPanel title="지금 검토할 사업" help="마감 · 참가 불가 · 관련 낮음을 뺀 수 — 사업기회 기본 목록과 같습니다">
          {SOURCES.map(({ key, label }) => (
            <SourceLine key={key} label={label} error={errorOf(key)}>
              <CountLink big value={loaded?.errors.unified ? null : valueOf(key, (c) => c.review)} href={opportunitiesHref(key)} label={`${label} 지금 검토할 사업`} />
              <Pair label="그중 가능">
                <CountLink value={loaded?.errors.unified ? null : valueOf(key, (c) => c.pass)} href={opportunitiesHref(key, "pass=1")} label={`${label} 참가 · 신청 가능`} />
              </Pair>
            </SourceLine>
          ))}
          {g2bPassZero && (
            <p className="text-[12.5px] text-cosmos-muted">
              나라장터 「가능」은 회사 단위 확인({SCREEN_NAMES.company} › 입찰 자격 자료)이 있어야 나옵니다 — 지금은 「확인 필요」가 가장 높은 판정입니다.
            </p>
          )}
        </StatPanel>

        <StatPanel title="새 공고" help={`지금 검토할 사업 중 게시일(기업마당은 등록일)이 오늘인 것 · ${newDays === null ? "최근 며칠" : `최근 ${newDays}일`} 안인 것`}>
          {SOURCES.map(({ key, label }) => (
            <SourceLine key={key} label={label} error={errorOf(key)}>
              <Pair label="오늘">
                <CountLink big value={loaded?.errors.unified ? null : valueOf(key, (c) => c.newToday)} href={opportunitiesHref(key, "new=today")} label={`${label} 오늘 올라온 공고`} />
              </Pair>
              <Pair label={newDays === null ? "최근" : `최근 ${newDays}일`}>
                <CountLink value={loaded?.errors.unified ? null : valueOf(key, (c) => c.newRecent)} href={opportunitiesHref(key, "new=1")} label={`${label} 최근 새 공고`} />
              </Pair>
            </SourceLine>
          ))}
        </StatPanel>

        <StatPanel title="마감" help={`지금 검토할 사업 중 실제 마감(참가 등록이 더 이르면 그 날)이 오늘인 것 · ${OVERVIEW_DUE_DAYS}일 안인 것`}>
          {SOURCES.map(({ key, label }) => (
            <SourceLine key={key} label={label} error={errorOf(key)}>
              <Pair label="오늘 마감">
                <CountLink big value={loaded?.errors.unified ? null : valueOf(key, (c) => c.dueToday)} href={opportunitiesHref(key, "due=today")} label={`${label} 오늘 마감`} />
              </Pair>
              <Pair label={withinDaysText(OVERVIEW_DUE_DAYS)}>
                <CountLink value={loaded?.errors.unified ? null : valueOf(key, (c) => c.dueWeek)} href={opportunitiesHref(key, `due=${OVERVIEW_DUE_DAYS}`)} label={`${label} ${withinDaysText(OVERVIEW_DUE_DAYS)}`} />
              </Pair>
            </SourceLine>
          ))}
        </StatPanel>
      </div>

      <section aria-label="선제준비" className="mc-panel flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 text-[13.5px] text-cosmos-secondary">
        <span className="font-semibold text-cosmos-text">선제준비</span>
        {prepare && prepare.key === listKey ? (
          prepare.count === null ? (
            <span className="text-cosmos-amber">못 받음 — {prepare.error}</span>
          ) : (
            <>
              <span>
                본공고 전 사전규격(본업 · 의견 마감 남음){" "}
                <Link href="/opportunities?tab=prepare" className="mc-focus rounded font-mono font-semibold tabular-nums text-cosmos-text underline-offset-4 hover:underline" data-overview-count="/opportunities?tab=prepare">
                  {prepare.count}
                </Link>
                건
              </span>
              {prepare.error && <span className="text-cosmos-amber">· {prepare.error}</span>}
            </>
          )
        ) : (
          <span className="text-cosmos-muted">읽는 중…</span>
        )}
      </section>

      <ThisWeekPanel organizationId={organizationId} reloadKey={reloadTick} />

      <p className="text-[13.5px] text-cosmos-secondary">
        공고 하나를 요구사항 → 회사 근거 → 제안서 → 제출 전 점검 순서로 보려면{" "}
        <Link href="/analysis" className="mc-focus rounded font-semibold text-cosmos-cyan underline underline-offset-2">
          {SCREEN_NAMES.analysis} 열기 →
        </Link>
      </p>
    </AppShell>
  );
}
