"use client";

/**
 * 「이번 주 할 일」 — 마감이 가까운 **우리가 실제로 손댈 수 있는** 사업 (0922.md §4-C-1).
 *
 * ## 왜 고쳤나
 *
 * 7차에서 이 자리는 「마감 임박 + 가능·확인 필요」였다. 그런데 기업마당 1,582건 중 603건이
 * 「확인 필요」라 **무엇이든 들어왔다** — 재검증에서 8칸 전부가 D-Day 기업마당이었고,
 * 무기체계 부품국산화 · SEOUL FOOD 페어링 홍콩 · 모두의 창업 · 별별동구 충장장터가
 * 담당자의 아침 화면을 채웠다(ISSUE-084). 마감만 보면 담당자가 볼 이유가 없다.
 *
 * ## 이제 무엇이 들어오나
 *
 * 1. 참가·신청할 수 있거나 확인만 하면 되는 건 (「불가」 제외)
 * 2. **우리 일인 것** — 갈래가 개발형·교육·훈련형이거나, 검토 우선순위가 「우선 검토」
 * 3. 기업마당은 지원분야가 기술·창업·인력·경영이고 **관련 낮음이 아닌** 것만
 * 4. 마감(**등록마감이 더 이르면 그것**)이 7일 이내
 *
 * 마감 순 8건. 모자라면 빈 칸을 「이번 주엔 더 없습니다」로 적는다 — 억지로 채우지 않는다.
 */

import { useEffect, useMemo, useState } from "react";

import Link from "next/link";

import { Badge } from "@/components/ui/primitives";
import { verdictOf } from "@/lib/verdict";
import ExportMenu from "@/components/opportunities/ExportMenu";
import { getBusinessOpportunities, getDeliveryCapacity, getEligibilityGaps } from "@/lib/api";
import { expiringCredentials } from "@/lib/firstTimeGuide";
import { analysisContext } from "@/lib/organization";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import {
  URGENCY_TONE,
  dDayText,
  daysUntil,
  effectiveDeadline,
  firstLabel,
  pairOf,
  urgencyTierOf,
} from "@/lib/deadline";
import { usePeriodDays } from "@/lib/period";
import { sourceFailure } from "@/lib/errors";
import { EXPIRED_HEAD, EXPIRED_TAIL, EXPIRING_SOON_HEAD, EXPIRING_SOON_TAIL, GUIDE_LINK_TEXT, SCREEN_NAMES } from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import { DIRECT_CHECK_HEAD, UNLOCK_HEAD } from "@/lib/unlock";
import type { DeliveryCapacityCredential } from "@/types/capability";
import { SOURCE_TYPE_LABELS, type EligibilityGapReport, type UnifiedOpportunity } from "@/types/opportunity";

/** 화면에 적는 최대 건수. 더 보려면 목록으로 간다 — 여기는 「오늘 뭘 하나」다. */
const MAX_ROWS = 8;

/** 출처마다 먼저 채우는 자리 수 — **입찰 4 + 지원사업 4** (0924 §4-B-3). */
const PER_SOURCE_ROWS = 4;

/**
 * 「전라남도 소재」 해석을 기다리는 건을 가리는 말 (0924 §4-B-4).
 *
 * 백엔드가 「열리는 조건」에 적어 준 문장의 일부다 — 화면이 규칙을 다시 만들지 않는다.
 * 문장이 바뀌면 `support_application_service.MERGED_REGION_UNLOCK` 과 함께 고친다.
 */
const MERGED_REGION_HINT = "전남사회적경제통합지원센터";

/** 「갖추면 열린다」 줄 수 상한 (0923 §3-1 · ISSUE-091). 네 줄째부터는 목록에서 본다. */
const MAX_GAP_LINES = 3;

/** 「이번 주」의 길이. 「D-7 이내」 필터·레이더 링과 같은 값이어야 한다. */
const WITHIN_DAYS = 7;

/** 기업마당에서 회사가 신청할 만한 지원분야. 그 밖(수출·내수·금융·기타)은 이 자리에 없다. */
const SUPPORT_CATEGORIES = new Set(["기술", "창업", "인력", "경영"]);

/** 이 항목의 실제 데드라인 — 등록마감이 더 이르면 그쪽이다. */
export function deadlineOf(item: UnifiedOpportunity): string | null {
  return effectiveDeadline(pairOf(item, item.deadline));
}

/** 담당자가 이번 주에 손댈 수 있는 건인가. **목록 화면과 같은 규칙을 쓴다.** */
export function isThisWeek(item: UnifiedOpportunity, nowMs: number): boolean {
  if (item.closed || item.eligibility_gate === "FAIL") return false;
  // 회사와 관련이 낮다고 판정한 것은 아침 화면에 올리지 않는다 (0922 §4-C-2).
  if (item.relevance_note) return false;
  const tracks = item.work_tracks ?? [];
  const ours =
    tracks.includes("development") ||
    tracks.includes("education") ||
    item.priority_label === "우선 검토";
  if (!ours) return false;
  if (item.source_type === "bizinfo") {
    if (!SUPPORT_CATEGORIES.has(item.category ?? "")) return false;
    /*
     * **지금 손댈 수 있는 것만** (0925 §4-E-4).
     *
     * 회사가 아직 안 적은 값(매출·연구소·상시근로자 수) 때문에 「확인 필요」인 건과
     * 간접 참여는 아침에 읽고 바로 할 수 있는 일이 아니다. 목록에는 그대로 있다.
     * **백엔드(`opportunity_workbook.this_week`)와 같은 규칙이다** — 화면과 엑셀이
     * 다른 목록을 담으면 담당자가 어느 쪽을 믿어야 할지 알 수 없다.
     */
    if (item.participation || item.check_side === "company") return false;
    /*
     * **회사가 신청 주체가 아닐 수 있는 건**도 빼낸다 (ISSUE-125 · prompt_05 §4-E-1).
     * 개인·수강생 모집 안내와 참가·출품 기회는 「원문에서 확인하세요」로 끝나는 건이라
     * 아침에 읽고 바로 할 수 있는 일이 아니다. 목록에는 그대로 있다.
     * **백엔드(`opportunity_workbook.this_week`)와 같은 규칙이다.**
     */
    if (item.audience_note) return false;
    // 43차 M10 · BIZ-11 — 지원사업 자리는 사업 목적이 회사 갈래인 것만(백엔드 `this_week` 와 같은 규칙)
    if (item.kind_fit === false) return false;
  }
  const days = daysUntil(deadlineOf(item), nowMs);
  return days !== null && days >= 0 && days <= WITHIN_DAYS;
}

/**
 * 「이번 주 할 일」의 줄 순서 (0925 §4-E-4).
 *
 * 마감이 먼저. 같은 날이면 **지금 손댈 수 있는 것**이 앞이다 — 「센터에 전화 한 통」이면
 * 정해지는 건이, 「대상 요건을 확정하지 못했습니다」밖에 말할 게 없는 건보다 먼저다.
 * 백엔드 `opportunity_workbook.this_week` 의 `order` 와 같은 규칙이다.
 */
export function weekOrder(item: UnifiedOpportunity, nowMs: number): [number, number, number, number, string] {
  return [
    daysUntil(deadlineOf(item), nowMs) ?? 9999,
    item.eligibility_gate === "PASS" ? 0 : 1,
    item.unlock_conditions?.length ? 0 : 1,
    -(item.company_priority_score ?? 0),
    item.id,
  ];
}

function compareWeek(a: UnifiedOpportunity, b: UnifiedOpportunity, nowMs: number): number {
  const left = weekOrder(a, nowMs);
  const right = weekOrder(b, nowMs);
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}

/** `reloadKey` — 올리면 다시 받는다(2.0.7 「찾는 낱말」 바로 찾기로 새 공고가 들어왔을 때). 받는 동안 옛 목록을 그대로 둔다. */
export default function ThisWeekPanel({ organizationId, reloadKey = 0 }: { organizationId: string; reloadKey?: number }) {
  const days = usePeriodDays();
  const nowMs = useNowMs();
  const [all, setAll] = useState<UnifiedOpportunity[] | null>(null);
  const [failed, setFailed] = useState(false);
  // 2.0.6 — 출처 하나만 못 받으면 서버는 200 + `source_errors` 로 답한다. items 만 보면 그 출처가 「없습니다」처럼 보였다(사유 없이).
  const [sourceErrors, setSourceErrors] = useState<[string, string][]>([]);
  const [gaps, setGaps] = useState<EligibilityGapReport | null>(null);
  // 회사자료 「준비 상태」의 유효기간 — 30일 안 만료 · 지난 날짜를 안내 줄로(31차 §3-B · 제품 반영 안 3-2)
  const [credentials, setCredentials] = useState<DeliveryCapacityCredential[]>([]);

  useEffect(() => {
    let alive = true;
    // 마감 임박순으로 넉넉히 받아 화면에서 고른다. 「불가」는 기본으로 빠져 있다.
    getBusinessOpportunities({ organizationId, source: "all", days, sort: "deadline", limit: 200 })
      .then((response) => {
        if (!alive) return;
        setAll(response.items);
        // 그 출처 항목이 하나도 없을 때만 실패 — 저장본으로 대신 받은 날은 목록을 보이면서 「받지 못했습니다」를 띄웠다(sourceFailure · 2.0.6)
        setSourceErrors(
          Object.keys(response.source_errors ?? {})
            .map((source) => [source, sourceFailure(response, source)] as const)
            .filter((entry): entry is readonly [string, string] => entry[1] !== null)
            .map(([source, message]) => [source, message]),
        );
        setFailed(false);
      })
      .catch(() => {
        // 부가 정보다 — 다만 칸이 통째로 사라지면 왜 없는지 모른다. 제목과 한 줄은 남긴다 (DSH-26).
        if (alive) setFailed(true);
      });
    getEligibilityGaps({ organizationId, days })
      .then((report) => {
        if (alive) setGaps(report);
      })
      .catch(() => undefined);
    getDeliveryCapacity(analysisContext("", organizationId))
      .then((capacity) => {
        if (alive) setCredentials(capacity.credentials ?? []);
      })
      .catch(() => undefined); // 부가 안내다 — 못 읽으면 줄을 내지 않는다
    return () => {
      alive = false;
    };
  }, [organizationId, days, reloadKey]);

  const items = useMemo(() => {
    if (all === null || nowMs === null) return null;
    const byDeadline = (a: UnifiedOpportunity, b: UnifiedOpportunity) => compareWeek(a, b, nowMs);
    const open = all.filter((item) => isThisWeek(item, nowMs)).sort(byDeadline);
    /*
     * **출처마다 자리를 나눠 준다** (0924 §4-B-3).
     *
     * 마감 순으로만 채우면 어느 한쪽이 여덟 자리를 다 가져간다. 실제로 그랬다 —
     * 입찰 마감이 촘촘한 주에는 지원사업이 한 건도 못 올라왔고, 담당자는 「이번 주에
     * 신청할 지원사업이 없다」고 읽었다. 두 출처는 하는 일이 다르므로 자리도 따로 준다.
     * 한쪽이 자기 몫을 못 채우면 남은 자리는 다른 쪽이 쓴다 — 빈칸을 만들지 않는다.
     */
    const bid = open.filter((item) => item.source_type === "g2b");
    const support = open.filter((item) => item.source_type === "bizinfo");
    const picked = [...bid.slice(0, PER_SOURCE_ROWS), ...support.slice(0, PER_SOURCE_ROWS)];
    if (picked.length < MAX_ROWS) {
      for (const item of open) {
        if (picked.length >= MAX_ROWS) break;
        if (!picked.includes(item)) picked.push(item);
      }
    }
    return picked.sort(byDeadline).slice(0, MAX_ROWS);
  }, [all, nowMs]);

  if (items === null) {
    return (
      <section className="mc-panel flex flex-col gap-1 px-3 py-2.5 sm:px-4" aria-label="이번 주 할 일" aria-busy={!failed}>
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">이번 주 할 일</h2>
        <p className={`text-[12.5px] ${failed ? "text-cosmos-amber" : "text-cosmos-muted"}`} role={failed ? "alert" : "status"}>
          {failed ? "이번 주 목록을 불러오지 못했습니다 — 사업기회 목록에서 마감 임박순으로 보세요." : "이번 주 목록을 불러오는 중…"}
        </p>
      </section>
    );
  }

  /*
   * 갭은 **세 줄까지**다 (0922 §4-A-5 · 0923 §3-1).
   *
   * 뜻이 다른 두 수를 하나로 합치지 않는다 — 「불가가 풀린다」와 「판정이 확정된다」.
   * 한 줄만 적으면 앞의 것(대개 마감 촉박)이 언제나 이겨서, 「소프트웨어사업자(1468) 등록
   * 시 25건이 확정된다」처럼 **담당자가 실제로 갖출 수 있는 조건**이 화면에 못 온다.
   *
   * 「막는 0 · 확정 0」인 줄은 백엔드가 이미 빼고 보낸다 — 여기서 다시 거르는 것은
   * 옛 응답(그 필드가 없던 스냅샷)을 열었을 때를 위한 것이다.
   */
  const usable = (gaps?.gaps ?? []).filter((gap) => gap.blocked > 0 || gap.pending > 0);
  const unblock = usable.find((gap) => gap.blocked > 0) ?? null;
  /*
   * 확정 쪽은 **밖에서 갖춰야 하는 조건**(업종·지역 등록)을 먼저 적는다.
   *
   * 「회사자료에 단독 수행 상한을 적으면」류가 건수는 더 크지만, 그것은 회사자료 화면이
   * 이미 칸으로 안내한다. 담당자가 이 자리에서만 알 수 있는 것은 「소프트웨어사업자
   * (컴퓨터관련서비스사업, 1468)를 등록하면 25건이 확정된다」처럼 **협회 신고·나라장터
   * 업종 추가가 필요한 조건**이다 — 기준 답안의 머리글도 그것이었다.
   */
  const registration =
    usable.find((gap) => gap.blocked === 0 && gap.pending > 0 && gap.condition.includes("등록 시 가능")) ?? null;
  const confirm = registration ?? usable.find((gap) => gap.blocked === 0 && gap.pending > 0) ?? null;
  // 세 번째 줄은 앞의 둘과 겹치지 않는 것 중 가장 큰 것. 없으면 두 줄로 끝난다.
  const picked = [unblock, confirm].filter(Boolean) as NonNullable<typeof unblock>[];
  const third = usable.find((gap) => !picked.some((p) => p.condition === gap.condition)) ?? null;
  const gapLines = [...picked, third].filter(Boolean).slice(0, MAX_GAP_LINES) as NonNullable<typeof unblock>[];
  const hint = gaps?.registration_hints?.[0] ?? null;
  /*
   * 「전라남도 소재」 해석을 기다리는 건수 (0924 §4-B-4).
   *
   * 판정이 붙여 준 **열리는 조건**을 센다 — 화면이 따로 규칙을 만들지 않는다.
   * 이번 주에 닫히는 것만이 아니라 목록 전체에서 센다. 전화 한 통의 값은 그만큼이다.
   */
  const mergedRegion = (all ?? []).filter((item) =>
    (item.unlock_conditions ?? []).some((condition) => condition.includes(MERGED_REGION_HINT)),
  ).length;
  const expiring = nowMs === null ? [] : expiringCredentials(credentials, nowMs).slice(0, MAX_GAP_LINES);

  return (
    <section className="mc-panel flex flex-col gap-2 px-3 py-2.5 sm:px-4" aria-label="이번 주 할 일">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">이번 주 할 일</h2>
        <p className="text-[12px] text-cosmos-muted">
          <span title="등록마감이 더 빠르면 그 날로 셉니다">{WITHIN_DAYS}일 안 마감 · 입찰 · 지원사업 {PER_SOURCE_ROWS}건씩(한쪽이 모자라면 다른 쪽이 채워 모두 {MAX_ROWS}건까지)</span>
          {/* 10-31 최종 점검 — 위 「7일 안 마감」 숫자보다 지원사업이 적은 까닭(isThisWeek 기업마당 규칙)을 머리에 적는다 */}
          <span className="block">지원사업은 회사 갈래 · 지원분야가 맞고 바로 손댈 수 있는 것만 올립니다 — 나머지는 사업기회 기업마당 탭에 그대로 있습니다.</span>
          {/* 43차 설명(BRIEF-13) — 이 칸은 마감 달력이다(37차 D2) · 무엇부터 볼지는 사업기회 실무순 */}
          <span className="block">마감 달력입니다 — 3일 이하는 원칙적으로 후순위이고, 무엇부터 볼지는 사업기회 목록 순서를 보세요.</span>
        </p>
        <span className="ml-auto flex items-center gap-2">
          {/* 아침 화면에서 바로 내보낸다 (0924 §4-C-3) — 워크북에 「이번 주 할 일」 시트가 있다. */}
          <ExportMenu
            query={{ organizationId, days, sort: "deadline" }}
            hint="워크북의 「이번 주 할 일」 시트가 이 목록과 같은 규칙으로 채워집니다."
          />
          <Link
            href="/opportunities?sort=deadline"
            className="mc-focus rounded px-1 text-[12px] text-cosmos-cyan hover:underline"
          >
            {SCREEN_NAMES.opportunities} 목록 →
          </Link>
        </span>
      </div>

      {/* 못 받은 출처는 「없음」으로 세지 않고 그 자리에 사유를 적는다(2.0.6) */}
      {sourceErrors.map(([key, message]) => (
        <p key={key} className="text-[12.5px] text-cosmos-amber" role="alert">
          {(SOURCE_TYPE_LABELS as Record<string, string>)[key] ?? "다른 출처"} 목록을 받지 못했습니다 — {message}
        </p>
      ))}
      {items.length === 0 ? (
        <p className="py-1 text-[12.5px] text-cosmos-secondary">
          {sourceErrors.length > 0 ? "받은 목록에서는 " : ""}이번 주엔 마감이 닥친 건이 없습니다. {SCREEN_NAMES.opportunities} 목록에서 다음 주 이후를 보세요.
        </p>
      ) : (
        <ol className="flex flex-col gap-1">
          {items.map((item) => {
            const deadline = deadlineOf(item);
            const left = nowMs === null ? null : daysUntil(deadline, nowMs);
            const tier = urgencyTierOf(left, item.closed);
            const pair = pairOf(item, item.deadline);
            const byRegistration = pair.qualification != null && deadline === pair.qualification && deadline !== item.deadline;
            return (
              <li key={item.id} className="flex min-w-0 items-baseline gap-2 text-[12.5px] leading-5">
                <span className={`w-[4.2rem] shrink-0 font-mono tabular-nums ${URGENCY_TONE[tier]}`}>
                  {dDayText({ deadline, periodKind: item.apply_period_kind, nowMs })}
                </span>
                <span
                  className="w-[3.4rem] shrink-0 text-[12px] text-cosmos-muted"
                  title={SOURCE_TYPE_LABELS[item.source_type]}
                >
                  {item.source_type === "g2b" ? "입찰" : item.source_type === "manual" ? "직접" : "지원사업"}
                </span>
                <Link
                  href={
                    item.source_type === "g2b"
                      ? `/analysis?notice=${encodeURIComponent(item.id)}`
                      : item.source_type === "manual"
                        ? item.next_route.path
                        : `/support/${encodeURIComponent(item.id)}`
                  }
                  className="mc-focus min-w-0 flex-1 truncate rounded text-cosmos-text underline-offset-2 hover:underline"
                  title={item.company_meaning ?? item.title}
                >
                  {item.title}
                </Link>
                {/* 43차 BRIEF-14 — 목록 · 브리핑과 같은 꼬리표(서버 `practical_priority.tags_of` 의 글) */}
                {/* 44차 M4 — 저장된 결정(브리핑 · 엑셀 「결정」 칸과 같은 값) */}
                {item.decision_text && (
                  <span className="shrink-0 rounded border border-cosmos-border px-1.5 text-[12px] text-cosmos-secondary" title="저장된 결정">
                    결정: {item.decision_text}
                  </span>
                )}
                {[item.partner_tag, item.scale_tag, item.topic_note, item.ai_fit_note].filter(Boolean).length > 0 && (
                  <span className="hidden shrink-0 text-[12px] text-cosmos-amber sm:inline" title="목록 · 브리핑과 같은 꼬리표">
                    {[item.partner_tag, item.scale_tag, item.topic_note, item.ai_fit_note].filter(Boolean).join(" · ").slice(0, 40)}
                  </span>
                )}
                {byRegistration && (
                  <span className="shrink-0 text-[12px] text-cosmos-amber" title="입찰 마감보다 먼저 닫힙니다">
                    {firstLabel(pair)}
                  </span>
                )}
                {item.participation ? (
                  <Badge tone="warn">{item.participation}</Badge>
                ) : (
                  <Badge tone={verdictOf(item.eligibility_gate).tone} title={verdictOf(item.eligibility_gate).title}>
                    {verdictOf(item.eligibility_gate).label}
                  </Badge>
                )}
              </li>
            );
          })}
          {items.length < MAX_ROWS && (
            <li className="pt-0.5 text-[12px] text-cosmos-muted">{sourceErrors.length > 0 ? "받은 목록에서는 이번 주에 더 없습니다." : "이번 주엔 더 없습니다."}</li>
          )}
        </ol>
      )}

      {/*
        **소재 해석 하나로 묶인 건** (0924 §4-B-4).
        통합특별시 출범 뒤 광주 북구가 「전라남도 소재」에 드는지는 앱이 정할 일이 아니다.
        전화 한 통이면 여러 건이 한꺼번에 정해지므로, 흩어진 배지 대신 한 줄로 모은다.
      */}
      {mergedRegion > 0 && (
        <p className="text-[12px] leading-4 text-cosmos-amber" role="note">
          <span className="text-cosmos-muted">전화로 확인할 일: </span>
          {/* 회사 주소를 박아 두면 다른 회사를 골라도 샘플에듀 주소가 나온다 (DSH-15) */}
          전남사회적경제통합지원센터에 「회사 본사가 전라남도 소재 요건에 드는가」를 확인하면 {mergedRegion}건이
          정해집니다
        </p>
      )}
      {expiring.map((row) => (
        <p key={`${row.name}-${row.validUntil}`} className="text-[12px] leading-4 text-cosmos-amber" role="note">
          <span className="text-cosmos-muted">{row.state === "expired" ? EXPIRED_HEAD : EXPIRING_SOON_HEAD}: </span>
          {row.name} {row.validUntil} — {row.state === "expired" ? EXPIRED_TAIL : EXPIRING_SOON_TAIL}{" "}
          <GuideContextLink href={GUIDE_LINKS.validity}>{GUIDE_LINK_TEXT.validity}</GuideContextLink>
        </p>
      ))}
      {gapLines.map((gap) =>
        // 나라장터 등록은 회사자료에 적어 확정되는 값이 아니다 — 「확정됩니다」 대신 직접 확인할 공고 수(31차 §3-B · 1-4).
        gap.rule_id === "ELIG-REGISTRATION" ? (
          <p key={gap.condition} className="text-[12px] leading-4 text-cosmos-cyan" role="note">
            <span className="text-cosmos-muted">{DIRECT_CHECK_HEAD}: </span>
            {gap.condition} — 「확인 필요」인 공고 {gap.pending}건{" "}
            <GuideContextLink href={GUIDE_LINKS.register}>{GUIDE_LINK_TEXT.register}</GuideContextLink>
          </p>
        ) : (
          <p key={gap.condition} className="text-[12px] leading-4 text-cosmos-cyan" role="note">
            <span className="text-cosmos-muted">{UNLOCK_HEAD}: </span>
            {gap.condition} —{" "}
            {gap.blocked > 0
              ? `지금 「불가」인 ${gap.blocked}건이 풀립니다`
              : `지금 「확인 필요」인 ${gap.pending}건을 확정할 수 있습니다`}
          </p>
        ),
      )}
      {hint && (
        <p className="text-[12px] leading-4 text-cosmos-secondary" role="note">
          <span className="text-cosmos-muted">등록 후보 </span>
          {hint.hint}
        </p>
      )}
    </section>
  );
}
