"use client";

/**
 * 「오늘 · 이번 주」 접힌 띠 (21차 · prompt_11 §3-7).
 *
 * 재검증(1440×900)이 본 것: 첫 화면에 지도가 없었다 — 「오늘 달라진 것」·「이번 주 할 일」·「지금 할 일」이 먼저
 * 900px 을 채웠다. 셋은 **조직 단위** 정보라(이 공고의 길이 아니라) 한 줄로 접어 KPI 위에 둔다.
 * 펼치면 예전 세 패널이 그대로 나온다. 기본은 접힘이고 펼침 여부는 브라우저에 기억한다(`bidpilot.daystrip.v1`).
 *
 * 접힌 줄의 숫자는 「오늘 달라진 것」과 **같은 응답**(getTodayDigest)이다. 못 받으면 숫자를 적지 않는다 —
 * 0 으로 적으면 「새 공고가 없다」로 읽힌다.
 */

import { useExpiringCredentials } from "@/components/guide/useExpiringCredentials";
import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import TodayDigestStrip from "@/components/cosmos/TodayDigestStrip";
import CollectKeywordsPanel from "@/components/opportunities/CollectKeywordsPanel";
import { getTodayDigest } from "@/lib/api";
import { keywordResultHref } from "@/lib/collectKeywords";
import { formatDateTime } from "@/lib/cosmos/format";
import { withinDaysText } from "@/lib/deadline";
import { expiringCounts } from "@/lib/firstTimeGuide";
import { collectTerm, collectWarns, SCREEN_NAMES, UNDECIDED } from "@/lib/terms";
import type { DigestCount, TodayDigest } from "@/types/digest";

/** 펼침 기억 — 다른 기록(KPI · 튜토리얼 · 안내)과 키가 겹치지 않는다. */
export const DAY_STRIP_STORAGE_KEY = "bidpilot.daystrip.v1";
const listeners = new Set<() => void>();
function readExpanded(): boolean {
  try {
    return window.localStorage.getItem(DAY_STRIP_STORAGE_KEY) === "expanded";
  } catch {
    return false;
  }
}
function writeExpanded(value: boolean): void {
  try {
    window.localStorage.setItem(DAY_STRIP_STORAGE_KEY, value ? "expanded" : "collapsed");
  } catch {
    // 저장 실패는 무시 — 이번 화면에서만 펼친다
  }
  for (const listener of listeners) listener();
}
function subscribeExpanded(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}
/** 서버 렌더와 첫 그림은 접힘 — 기본값이자 하이드레이션에 안전한 값. */
const getExpandedServer = () => false;

function Count({ label, count }: { label: string; count: DigestCount }) {
  return (
    <span title={count.basis} className="inline-flex items-baseline gap-1 text-[13px] text-cosmos-secondary">
      {label}
      <span className={`font-mono tabular-nums ${count.value > 0 ? "font-semibold text-cosmos-text" : "text-cosmos-muted"}`}>
        {count.value}
      </span>
    </span>
  );
}

interface DayStripProps {
  organizationId: string;
  /** 펼쳤을 때 「오늘 달라진 것」 아래에 놓을 패널 — 이번 주 할 일 · 지금 할 일 (접혀 있으면 그리지 않는다) */
  children: ReactNode;
  /** 「찾는 낱말」 바로 찾기로 새 공고가 들어왔다 — 대시보드 고르기 칸 목록 · 펼친 「이번 주 할 일」을 다시 받는다(2.0.7) */
  onNoticesChanged?: () => void;
}

export default function DayStrip({ organizationId, children, onNoticesChanged }: DayStripProps) {
  const expanded = useSyncExternalStore(subscribeExpanded, readExpanded, getExpandedServer);
  const toggle = useCallback(() => writeExpanded(!expanded), [expanded]);
  const [digest, setDigest] = useState<TodayDigest | null>(null);
  const expiring = useExpiringCredentials(organizationId);
  /**
   * 「찾는 낱말」(2.0.7 · 대표 「낱말 추가를 대시보드에서 · 바로 재검색」) — 쉬운 보기 · 전체 보기 둘 다 이 띠를 쓰므로 여기 둔다.
   * 기본은 닫힘(기억하지 않음) — 띠 한 줄에 단추 하나만 는다.
   */
  const [keywordsOpen, setKeywordsOpen] = useState(false);
  /** 바로 찾기로 새 공고가 들어오면 접힌 줄의 「최근 n일 새 공고」도 다시 센다. */
  const [digestTick, setDigestTick] = useState(0);

  useEffect(() => {
    let alive = true;
    // 선택한 회사를 넘긴다 (0920 §4-B-3) — 회사를 바꾸면 「결정 대기」도 그 회사 것이다.
    getTodayDigest(organizationId)
      .then((value) => {
        if (alive) setDigest(value);
      })
      .catch(() => {
        // 부가 정보다. 못 받으면 숫자 없이 접힌 줄만 둔다 — 오류 문구로 첫 화면을 어지럽히지 않는다.
      });
    return () => {
      alive = false;
    };
  }, [organizationId, digestTick]);

  return (
    <section aria-label="오늘 · 이번 주" className="px-3 pt-3 sm:px-5">
      <div className="mc-panel flex min-h-9 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          aria-controls={expanded ? "day-strip-panels" : undefined}
          data-day-strip-toggle
          className="mc-focus flex min-h-7 shrink-0 items-center gap-1.5 rounded-md px-1.5 text-[13px] font-semibold text-cosmos-text hover:bg-cosmos-elevated/70"
        >
          오늘 · 이번 주 할 일
          <span aria-hidden="true" className="text-[13px] text-cosmos-secondary">
            {expanded ? "▾ 접기" : "▸ 펼치기"}
          </span>
        </button>
        {digest && (
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            <Count label={`최근 ${digest.new_days}일 새 공고`} count={digest.new_notices} />
            <span aria-hidden className="text-cosmos-muted">·</span>
            <Count label={withinDaysText(digest.due_days)} count={digest.due_soon} />
            <span aria-hidden className="text-cosmos-muted">·</span>
            <Count label={`참여 ${UNDECIDED}`} count={digest.awaiting_decision} />
          </span>
        )}
        <button
          type="button"
          onClick={() => setKeywordsOpen((open) => !open)}
          aria-expanded={keywordsOpen}
          aria-controls={keywordsOpen ? "day-strip-keywords" : undefined}
          data-day-strip-keywords
          className="mc-focus flex min-h-7 shrink-0 items-center rounded-md border border-cosmos-border px-2 text-[13px] text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
        >
          찾는 낱말
        </button>
        {/* 곧 만료 · 만료됨 — 접힌 채로도 보이게(32차 R31-10). 자세한 줄은 펼친 「이번 주 할 일」 */}
        {expiring.length > 0 && (
          <span className="text-[13px] font-semibold text-cosmos-amber" data-day-strip-expiring>
            · {expiringCounts(expiring)}
          </span>
        )}
        {digest && (
          <span className="ml-auto flex flex-wrap items-center gap-x-2 text-[13px] text-cosmos-muted">
            <span>목록 받은 때 {digest.fetched_at ? formatDateTime(digest.fetched_at) : "없음"}</span>
            {digest.frozen && (
              <span className={collectWarns(digest.collect_state) ? "text-cosmos-amber" : "text-cosmos-secondary"} data-auto-collect title={collectWarns(digest.collect_state) ? undefined : collectTerm(digest.collect_state)}>
                · {collectTerm(digest.collect_state, digest.fetched_at)}
              </span>
            )}
          </span>
        )}
      </div>
      {keywordsOpen && (
        <div className="mt-2">
          <CollectKeywordsPanel
            id="day-strip-keywords"
            collectState={digest?.collect_state ?? null}
            onClose={() => setKeywordsOpen(false)}
            onSearched={(result) => {
              if (result.new_notices === 0) return;
              setDigestTick((n) => n + 1);
              onNoticesChanged?.();
            }}
            resultAction={(result) =>
              result.found > 0 && (
                <Link href={keywordResultHref(result)} className="mc-focus rounded font-semibold text-cosmos-cyan underline underline-offset-2" data-keyword-result-link>
                  {SCREEN_NAMES.opportunities}에서 결과 보기 →
                </Link>
              )
            }
          />
        </div>
      )}
      {expanded && (
        <div id="day-strip-panels" className="mt-2 flex flex-col gap-2">
          {digest && <TodayDigestStrip digest={digest} />}
          {children}
        </div>
      )}
    </section>
  );
}
