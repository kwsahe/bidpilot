"use client";

/**
 * 사업기회 레이더 — 선택 항목 상세.
 *
 * 기본에 보이는 것: 통합 순위 · 출처 · 사업 유형 · 제목 · 기관 · 회사 적합도 · 마감 · 신뢰도 ·
 * 적합한 이유 2개 · 확인할 사항 2개 · 다음 분석 버튼 · 공식 원문 버튼.
 *
 * 접기(「점수 산정 근거 보기」)로 옮긴 것 — **삭제한 것은 없다**:
 * 5개 배점표 전체 · 이유/확인 사항 전부 · 원본 추천등급/지원 적합도 · 요약·지역·예산 같은 메타데이터 ·
 * 데이터 출처 설명.
 *
 * 규칙:
 *  - score=null 은 **미확인**이며 0점이 아니다 — 막대를 0으로 그리지 않는다.
 *  - 지원사업은 목록 API에 지원 규모가 없다 — 0원으로 표시하지 않는다.
 *  - 기업마당 항목에는 입찰 용어(입찰자격·낙찰·투찰·제안서 평가항목)를 쓰지 않는다.
 *  - summary 원문에 HTML 태그가 섞여 있다 — 평문으로 바꿔 넣고 절대 HTML로 렌더하지 않는다.
 */

import { requirementSheetHref } from "@/lib/selection";
import { PlaneTargetIcon } from "@/components/icons/aviation";
import { deadlineTerm, effectiveDeadline, firstLabel, formatDDay, formatPairDeadline, isOpenEnded, pairOf, registrationClosesFirst } from "@/lib/deadline";
import Link from "next/link";
import { useSyncExternalStore } from "react";

import { Badge, Panel } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { formatBudgetCompact, tintStyle, truncate } from "@/lib/cosmos/format";
import { GUIDE_LINK_TEXT, OPEN_REQUIREMENT_SHEET } from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import { CONSORTIUM_UNLOCK, DIRECT_CHECK_HEAD, UNLOCK_HEAD, splitUnlocks } from "@/lib/unlock";
import { GRADE_LABELS, RECOMMENDATION_GRADE, REVIEW_PRIORITY, labelOf } from "@/lib/scoreNames";
import { gradeOf } from "@/types/opportunity";
import AnalysisStateBadges from "@/components/ui/AnalysisStateBadges";
import { GROUP_HELP, GROUP_TONE, PracticalTags, useRankingMethod } from "@/components/opportunities/PracticalTags";
import { verdictOf } from "@/lib/verdict";
import { COSMOS_COLORS, TONE_COLORS, type Tone } from "@/lib/cosmos/theme";
import { scoreText, sourceBadgeOf, stripHtml, URGENCY_LABELS, type RadarNode } from "@/lib/radar/layout";
import {
  CONFIDENCE_LABELS,
  OPPORTUNITY_TYPE_LABELS,
  SOURCE_TYPE_LABELS,
  type PriorityLabel,
  type UnifiedOpportunity,
} from "@/types/opportunity";

const PRIORITY_TONE: Record<PriorityLabel, Tone> = {
  "우선 검토": "pass",
  검토: "ok",
  후순위: "muted",
  미확인: "warn",
  마감: "fail",
};

const CONFIDENCE_TONE = {
  high: "pass",
  medium: "warn",
  low: "muted",
} as const;

/** 기본에 보여줄 이유·확인 사항 개수. 나머지는 접기 안에 그대로 남는다. */
const PREVIEW_COUNT = 2;

// ---------------------------------------------------------------------------
// source_specific_score (출처별 원본 점수) 해석 — Record<string, unknown> 을 안전하게 읽는다
// ---------------------------------------------------------------------------

function readString(bag: Record<string, unknown>, key: string): string | null {
  const value = bag[key];
  return typeof value === "string" && value.trim() ? value : null;
}

interface SourceScoreView {
  /** 예: "추천등급 A" · "지원 적합도 적합" */
  text: string;
  /** 예: "낙찰확률 아님" — 반드시 함께 보여준다. */
  caveat: string;
  /** 참여 불가 사유 등 (있을 때만) */
  gateReason: string | null;
}

/** 조달=추천등급, 지원=지원 적합도. 두 값을 합치지 않고 원본 그대로 보여준다. */
function sourceScoreView(item: UnifiedOpportunity): SourceScoreView | null {
  const bag = item.source_specific_score;
  const kind = readString(bag, "kind");
  if (kind === "recommendation") {
    const grade = readString(bag, "grade");
    if (!grade) return null;
    return {
      text: `${RECOMMENDATION_GRADE.label} ${labelOf(GRADE_LABELS, grade)} (${RECOMMENDATION_GRADE.scope})`,
      caveat: "낙찰확률 아님",
      gateReason: readString(bag, "gate_reason"),
    };
  }
  if (kind === "support_fit") {
    const label = readString(bag, "label");
    if (!label) return null;
    return { text: `지원 적합도 ${label}`, caveat: "선정확률 아님", gateReason: null };
  }
  return null;
}

// ---------------------------------------------------------------------------
// 작은 조각
// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">{label}</dt>
      <dd className="mt-0.5 text-[13px] leading-5 text-cosmos-text">{children}</dd>
    </div>
  );
}

function BulletList({ items, tone }: { items: string[]; tone: Tone }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((text, index) => (
        <li
          key={`${index}-${text.slice(0, 12)}`}
          className="flex items-start gap-2 text-[12px] leading-5 text-cosmos-secondary"
        >
          <span
            aria-hidden="true"
            className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: TONE_COLORS[tone] }}
          />
          <span className="min-w-0">{text}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * 점수 산정 근거.
 *
 * 좁은 상세 패널(≈300px)에서도 가로 스크롤 없이 읽히도록 표 대신 목록으로 적는다.
 * 항목·배점·점수·이유 네 가지를 하나도 빼지 않는다.
 * score=null 은 막대를 그리지 않고 「미확인」으로 남긴다 — 0점이 아니다.
 */
function ScoreBreakdown({ item }: { item: UnifiedOpportunity }) {
  const computedWeight = item.score_components
    .filter((component) => component.score !== null)
    .reduce((sum, component) => sum + component.weight, 0);

  return (
    <div className="min-w-0">
      <ul className="flex flex-col gap-2.5">
        {item.score_components.map((component) => {
          const unknown = component.score === null;
          const percent = Math.round((component.score ?? 0) * 100);
          return (
            <li key={component.key} className="min-w-0 border-b border-cosmos-border/60 pb-2.5 last:border-b-0 last:pb-0">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
                <span className="text-[12px] font-medium text-cosmos-text">{component.label}</span>
                {unknown ? (
                  <Badge tone="warn" glyph="?" size="sm">
                    미확인 · 배점 {component.weight}
                  </Badge>
                ) : (
                  <span className="font-mono text-[12px] tabular-nums text-cosmos-secondary">
                    {percent}
                    <span className="text-cosmos-muted"> / 100 · 배점 {component.weight}</span>
                  </span>
                )}
              </div>
              {!unknown && (
                <span className="mt-1 block h-1 w-full overflow-hidden rounded-full bg-cosmos-slate/60" aria-hidden="true">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${percent}%`, backgroundColor: COSMOS_COLORS.cyan }}
                  />
                </span>
              )}
              <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{component.reason}</p>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[12px] leading-5 text-cosmos-muted">
        계산할 수 있는 만점 {computedWeight}점만으로 100점 만점으로 환산한 값입니다. 「미확인」 항목은 0점으로 세지 않습니다.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 미선택 상태 — 상위 3건만 짧게
// ---------------------------------------------------------------------------

function TopPick({ node, onSelect }: { node: RadarNode; onSelect: (id: string) => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.id)}
        className="mc-focus flex w-full min-w-0 items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-cosmos-elevated"
      >
        <PlaneTargetIcon filled size={13} className="mt-[3px] shrink-0" style={{ color: node.color }} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-1.5 text-[12px] text-cosmos-muted">
            {/* 같은 출처 안 순위 (27차 RDR-06) */}
            <span className="truncate">{node.sourceLabel}</span>
            <span className="font-mono tabular-nums">{node.sourceRank}위</span>
            <span className="ml-auto shrink-0 font-mono tabular-nums text-cosmos-secondary">
              {scoreText(node.item.company_priority_score)}
            </span>
          </span>
          <span className="mt-0.5 block truncate text-[13px] font-medium text-cosmos-text">
            {stripHtml(node.item.title)}
          </span>
        </span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// 본체
// ---------------------------------------------------------------------------

export interface RadarDetailProps {
  node: RadarNode | null;
  /** 목록 조회 시각 (출처 배지 툴팁). */
  fetchedAt: string | null;
  /** 목록이 비어 있을 때 안내에 쓸 현재 회사 이름. */
  companyName: string;
  /** 미선택 상태에 보여줄 상위 3건. */
  topNodes?: RadarNode[];
  onSelect?: (id: string) => void;
  /** 「순위 목록」 열기 — 키보드로 모든 항목을 고를 수 있는 자리. */
  onOpenList?: () => void;
  /** Sheet 안에서 쓸 때는 패널 테두리 없이 내용만 그린다. */
  bare?: boolean;
  className?: string;
}

export default function RadarDetail({
  node,
  fetchedAt,
  companyName,
  topNodes = [],
  onSelect,
  onOpenList,
  bare = false,
  className = "",
}: RadarDetailProps) {
  const body = node ? (
    <SelectedDetail node={node} fetchedAt={fetchedAt} />
  ) : (
    <div className="flex min-w-0 flex-col gap-3">
      <div>
        <h2 className="text-[15px] font-semibold text-cosmos-text">사업기회를 선택하세요</h2>
        <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">
          안쪽 노드부터 마감이 이릅니다. 큰 노드일수록 {companyName} 기준 검토 우선순위가 높습니다.
        </p>
      </div>
      {topNodes.length > 0 && onSelect && (
        <div className="border-t border-cosmos-border pt-2">
          <h3 className="px-2 text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">
            상위 {topNodes.length}건
          </h3>
          <ul className="mt-1 flex flex-col">
            {topNodes.map((top) => (
              <TopPick key={top.id} node={top} onSelect={onSelect} />
            ))}
          </ul>
        </div>
      )}
      {onOpenList && (
        <button
          type="button"
          onClick={onOpenList}
          className="mc-focus self-start rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 py-1.5 text-[12px] font-semibold text-cosmos-text transition-colors hover:border-cosmos-cyan/60"
        >
          순위 목록 전체 보기
        </button>
      )}
    </div>
  );

  if (bare) return <div className={`min-w-0 ${className}`}>{body}</div>;
  return (
    <Panel className={className} ariaLabel="선택 항목 상세">
      {body}
    </Panel>
  );
}

/**
 * 레이더 → 지원사업 신청 분석으로 갈 때 지금 레이더 조건(출처 · 갈래 · 정렬 …)을 `rfrom` 으로 싣는다 — 「← 레이더」가 그 조건으로 돌아온다.
 * 예전엔 고정 「/radar」라 기본 필터로 열렸다(2.0.6 · 사업기회의 `from` 과 같은 방식 · 받는 쪽 SupportShell 은 `?…` 조각만 받는다).
 */
const subscribeNever = () => () => {};
const readSearch = (): string => window.location.search;
const readSearchServer = (): string => "";
function nextHref(path: string, radarSearch: string): string {
  if (!path.startsWith("/support/") || !radarSearch) return path;
  return `${path}${path.includes("?") ? "&" : "?"}rfrom=${encodeURIComponent(radarSearch)}`;
}

function SelectedDetail({ node, fetchedAt }: { node: RadarNode; fetchedAt: string | null }) {
  const radarSearch = useSyncExternalStore(subscribeNever, readSearch, readSearchServer);
  const item = node.item;
  const badge = sourceBadgeOf(item.source, item.source_type, item.pinned);
  const score = sourceScoreView(item);
  const isSupport = item.source_type === "bizinfo";
  const pair = pairOf(isSupport ? {} : item, item.deadline);
  const registrationFirst = !isSupport && !node.closed && registrationClosesFirst(pair);
  const summary = stripHtml(item.summary);
  const reasonPreview = item.reasons.slice(0, PREVIEW_COUNT);
  const checkPreview = item.checks.slice(0, PREVIEW_COUNT);
  const moreCount = Math.max(0, item.reasons.length - reasonPreview.length) + Math.max(0, item.checks.length - checkPreview.length);
  // (2.0.6) 실무 우선순위 회사는 분류 칸이 「우선 검토 · 검토」를 대신한다 — 사업기회 행과 같은 값(37차 §3-B-4). 레이더만 점수 이름표였다.
  const practical = useRankingMethod() === "practical";
  const group = practical && item.eligibility_gate !== "FAIL" ? (item.practical_group ?? null) : null;
  // (2.0.6) 간접 참여(공급기업 등)는 판정 자리에 「간접 참여」 — 사업기회 · 지원사업 화면과 같은 함수. 「확인 필요」만 적으면 직접 신청하는 사업으로 읽혔다.
  const verdict = verdictOf(item.eligibility_gate, item.participation);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      {/* 머리 — 순위 · 출처 · 제목 */}
      <div className="min-w-0">
        <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">
          {/* 같은 출처 안의 순위를 앞세운다 — 두 출처를 섞은 통합 순위는 비교 근거가 아니다.
              나라장터는 우리가 수주하는 사업, 기업마당은 우리가 신청하는 사업이다. */}
          {(item.source_total ?? 0) > 0
            ? `${SOURCE_TYPE_LABELS[item.source_type]} ${item.source_total}건 중 ${item.source_rank}위`
            : `${SOURCE_TYPE_LABELS[item.source_type]} · 검토 순서 ${item.priority_rank}번째`}{" "}
          · {OPPORTUNITY_TYPE_LABELS[item.opportunity_type]}
        </p>
        <h2 className="mt-1 text-[15px] font-semibold leading-snug text-cosmos-text">{stripHtml(item.title)}</h2>
        <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{item.agency}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {group ? (
            <Badge tone={GROUP_TONE[group] ?? "muted"} glyph size="sm" title={GROUP_HELP[group] ?? group}>
              {group}
            </Badge>
          ) : (
            <Badge tone={item.eligibility_gate === "FAIL" ? "fail" : PRIORITY_TONE[item.priority_label]} glyph size="sm">
              {item.eligibility_gate === "FAIL" ? "불가" : item.priority_label}
            </Badge>
          )}
          <SourceBadge kind={badge.kind} label={badge.label} fetchedAt={fetchedAt} />
          {/* (2.0.6) 사업기회 행과 같은 꼬리표 부품(규모 큼 · 주제 확인 · 파트너형 · AI …) — 레이더에만 없어 같은 공고가 화면마다 달라 보였다 */}
          <PracticalTags item={item} withGroup={!practical} />
        </div>
      </div>

      {item.eligibility_gate === "FAIL" && item.gate_reason && (
        <div className="rounded-lg border border-cosmos-red/40 bg-cosmos-red/10 px-3 py-2.5 text-[12px] leading-5 text-cosmos-red">
          <strong className="block text-cosmos-text">점수보다 먼저 확인할 조건</strong>
          {item.gate_reason}
        </div>
      )}

      {/* 분석 상태 — 목록 행과 **같은 컴포넌트**를 쓴다 (0920 §4-B-3).
          레이더가 결정을 몰라서 「참여 안 함」으로 정한 공고를 한복판에 남겨 두고 있었다. */}
      <div className="flex flex-wrap items-center gap-1.5">
        {/* 추천등급 — 대시보드 선택창·RFP 화면과 **같은 자리에 같은 말**이다.
          예전에는 접힌 「점수 산정 근거」 안에만 있어서, 카드만 보면 등급을 알 수 없었다
          (0920 §4-B 완료 조건). */}
      {gradeOf(item) && (
        <Badge tone="info" title={`${RECOMMENDATION_GRADE.description} (${RECOMMENDATION_GRADE.scope})`}>
          {RECOMMENDATION_GRADE.label} {labelOf(GRADE_LABELS, gradeOf(item) as string)}
        </Badge>
      )}
        <AnalysisStateBadges state={item.analysis_state} />
        {/* 자격 배지 (0921 §4-D-5). 점수보다 먼저 알아야 하는 사실이다 — 점수가 높아도
            참가할 수 없는 사업이 실제로 있다. 말은 한 벌뿐이다(가능·확인 필요·불가). */}
        {item.eligibility_gate && (
          <Badge tone={verdict.tone} title={item.participation ? verdict.title : (item.gate_reason ?? undefined)}>
            {verdict.label}
          </Badge>
        )}
      </div>
      {/* 무엇을 갖추면 열리는가 (0921 §4-B). 「불가」를 그냥 닫아 두지 않는다. */}
      {(() => {
        const { gain, direct } = splitUnlocks(item.unlock_conditions ?? []);
        return (
          <>
            {gain.length ? (
              <p className="text-[12px] leading-4 text-cosmos-cyan">
                <span className="text-cosmos-muted">{UNLOCK_HEAD}: </span>
                {gain.join(" · ")}
                {gain.includes(CONSORTIUM_UNLOCK) && (
                  <>
                    {" "}
                    <GuideContextLink href={GUIDE_LINKS.consortium}>{GUIDE_LINK_TEXT.consortium}</GuideContextLink>
                  </>
                )}
              </p>
            ) : null}
            {/* 나라장터 등록은 등록증으로 직접 확인할 일(32차 §3-B-2) */}
            {direct.length ? (
              <p className="text-[12px] leading-5 text-cosmos-cyan">
                <span className="text-cosmos-muted">{DIRECT_CHECK_HEAD}: </span>
                {direct.join(" · ")} <GuideContextLink href={GUIDE_LINKS.register}>{GUIDE_LINK_TEXT.register}</GuideContextLink>
              </p>
            ) : null}
          </>
        );
      })()}

      {/* 핵심 수치 — 적합도 · 마감 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="mc-panel px-3 py-2">
          <span className="block text-[12px] font-semibold tracking-[0.1em] text-cosmos-muted" title={REVIEW_PRIORITY.description}>
            {REVIEW_PRIORITY.label}
          </span>
          <span
            className="mt-1 block font-mono text-[22px] font-semibold leading-none tabular-nums"
            style={{ color: node.scoreUnknown ? COSMOS_COLORS.amber : COSMOS_COLORS.cyan }}
          >
            {scoreText(item.company_priority_score)}
          </span>
          <span className="mt-1 block text-[12px] leading-4 text-cosmos-muted">
            {CONFIDENCE_LABELS[item.confidence]}
          </span>
        </div>
        <div className="mc-panel px-3 py-2">
          {/* 마감이 지났으면 「마감」이 아니라 「종료」다. lib/deadline.ts 가 정한다. */}
          <span className="block text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">
            {/* 등록마감이 먼저면 이름표 · 날짜도 그쪽 — D-day 는 이미 등록마감 기준이었다(한 칸 안에서 어긋남 · 검수 R27U-MSC-01) */}
            {registrationFirst
              ? firstLabel(pair)
              : deadlineTerm({
                  source: isSupport ? "bizinfo" : "g2b",
                  closed: node.closed,
                  periodKind: item.apply_period_kind ?? null,
                  // (2.0.6) 실제 마감 — 입찰 마감이 비어도 앞자리 마감이 있으면 「접수 기간 미정」이 아니다(값 줄 node.deadlineLabel 과 같은 마감)
                  deadline: effectiveDeadline(pair),
                })}
          </span>
          <span
            className="mt-1 block font-mono text-[18px] font-semibold leading-tight tabular-nums"
            style={{ color: node.urgency === "urgent" ? COSMOS_COLORS.red : COSMOS_COLORS.textPrimary }}
          >
            {/* 이름표가 이미 「등록마감」이면 값에 「등록」을 두 번 적지 않는다 — 목록 · 라벨용 짧은 글(「등록 D-7」)은 deadlineLabel (27차 RDR-03) */}
            {/* 등록마감은 지났고 입찰은 남은 건 — 「등록마감 / 마감」이 아니라 「지남」(§3-F RDR-03 검증) */}
            {registrationFirst && !isOpenEnded(item.apply_period_kind)
              ? node.days !== null && node.days < 0
                ? "지남"
                : formatDDay(node.days)
              : node.deadlineLabel}
          </span>
          <span className="mt-1 block truncate text-[12px] leading-4 text-cosmos-muted">
            {effectiveDeadline(pair)
              ? formatPairDeadline(pair, effectiveDeadline(pair), "datetime")
              : `원문 문구 · ${URGENCY_LABELS[node.urgency]}`}
          </span>
        </div>
      </div>

      {/* 이유 · 확인할 사항 (각 2개까지) */}
      <div className="flex flex-col gap-2.5 border-t border-cosmos-border pt-3">
        <div className="min-w-0">
          <h3 className="text-[12px] font-semibold text-cosmos-text">적합한 이유</h3>
          <div className="mt-1.5">
            {reasonPreview.length > 0 ? (
              <BulletList items={reasonPreview} tone="ok" />
            ) : (
              <p className="text-[12px] leading-5 text-cosmos-muted">근거로 제시할 항목이 없습니다 — 지어내지 않습니다.</p>
            )}
          </div>
        </div>
        <div className="min-w-0">
          <h3 className="text-[12px] font-semibold text-cosmos-text">
            {isSupport ? "신청 전 확인할 사항" : "확인할 사항"}
          </h3>
          <div className="mt-1.5">
            {checkPreview.length > 0 ? (
              <BulletList items={checkPreview} tone="warn" />
            ) : (
              <p className="text-[12px] leading-5 text-cosmos-muted">별도로 표시된 확인 사항이 없습니다.</p>
            )}
          </div>
        </div>
      </div>

      {/* 이동 */}
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={nextHref(item.next_route.path, radarSearch)}
          className="mc-focus inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-transparent bg-cosmos-blue-strong px-3 py-1.5 text-[13px] font-semibold text-white transition-[filter] hover:brightness-110"
        >
          {/* 백엔드 문구에 「→」가 이미 붙어 오는 것이 있다(「분석 계속 →」) — 화살표는 여기서 한 번만 (27차 RDR-18). */}
          {item.next_route.label.replace(/\s*→\s*$/, "")}
          <span aria-hidden="true">→</span>
        </Link>
        {/* 요구사항을 이미 뽑아 둔 공고는 곧장 표로 (0920 §4-B-4 · ISSUE-077-b).
            예전에는 이 링크를 대시보드 상세 한 곳에서만 만들었다. */}
        {item.analysis_state?.parsed && (
          <Link
            href={requirementSheetHref(item.id)}
            className="mc-focus inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 py-1.5 text-[13px] font-semibold text-cosmos-text transition-colors hover:border-cosmos-cyan/60"
          >
            {OPEN_REQUIREMENT_SHEET}
          </Link>
        )}
        {item.detail_url ? (
          <a
            href={item.detail_url}
            target="_blank"
            rel="noreferrer noopener"
            className="mc-focus inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 py-1.5 text-[13px] font-semibold text-cosmos-text transition-colors hover:border-cosmos-cyan/60"
          >
            공식 원문
            <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <span className="text-[12px] text-cosmos-muted">원문 링크가 응답에 없습니다.</span>
        )}
      </div>

      {/* 접기 — 배점표·전체 이유·원본 점수·메타데이터 */}
      <details className="group min-w-0 border-t border-cosmos-border pt-2">
        <summary className="mc-focus flex cursor-pointer list-none items-center gap-1.5 rounded text-[12px] font-semibold text-cosmos-secondary transition-colors hover:text-cosmos-text">
          <span aria-hidden="true" className="inline-block transition-transform group-open:rotate-90">
            ▸
          </span>
          점수 계산 내역 보기
          {moreCount > 0 && <span className="font-normal text-cosmos-muted">· 이유·확인 사항 {moreCount}개 더</span>}
        </summary>

        <div className="mt-3 flex flex-col gap-3">
          <ScoreBreakdown item={item} />

          {item.reasons.length > reasonPreview.length && (
            <div className="min-w-0">
              <h4 className="text-[12px] font-semibold text-cosmos-text">적합한 이유 전체</h4>
              <div className="mt-1.5">
                <BulletList items={item.reasons} tone="ok" />
              </div>
            </div>
          )}
          {item.checks.length > checkPreview.length && (
            <div className="min-w-0">
              <h4 className="text-[12px] font-semibold text-cosmos-text">
                {isSupport ? "신청 전 확인할 사항 전체" : "확인할 사항 전체"}
              </h4>
              <div className="mt-1.5">
                <BulletList items={item.checks} tone="warn" />
              </div>
            </div>
          )}

          <dl className="grid grid-cols-1 gap-3 border-t border-cosmos-border pt-3 sm:grid-cols-2">
            <Field label={isSupport ? "소관 기관" : "발주 기관"}>{item.agency}</Field>
            <Field label={isSupport ? "지원 분야" : "지역"}>
              {item.category ?? <span className="text-cosmos-muted">확인 필요</span>}
            </Field>
            <Field label={isSupport ? "지원 규모" : "예산"}>
              {isSupport ? (
                <span className="text-cosmos-amber">지원 규모 미확인</span>
              ) : item.budget === null ? (
                <span className="text-cosmos-muted">{formatBudgetCompact(null)}</span>
              ) : (
                formatBudgetCompact(item.budget)
              )}
              {isSupport && (
                <span className="mt-0.5 block text-[12px] leading-4 text-cosmos-muted">
                  목록 API에 지원 규모가 없습니다 — 공고 원문에서 확인하세요.
                </span>
              )}
            </Field>
            <Field label="신뢰도">
              <Badge tone={CONFIDENCE_TONE[item.confidence]} glyph size="sm">
                {CONFIDENCE_LABELS[item.confidence]}
              </Badge>
              <span className="mt-0.5 block text-[12px] leading-4 text-cosmos-muted">
                계산된 배점 비중 · 데이터 출처
              </span>
            </Field>
            {score && (
              <Field label="원본 점수">
                <span className="inline-flex flex-wrap items-center gap-1.5">
                  <span
                    className="rounded-md border px-1.5 py-0.5 text-[12px] font-semibold"
                    style={tintStyle(COSMOS_COLORS.blueText)} // 글자용 파랑 — 면용 blue 는 칩 위에서 4.44:1 이었다(26차 ISSUE-155)
                  >
                    {score.text}
                  </span>
                  <span className="text-[12px] text-cosmos-muted">({score.caveat})</span>
                </span>
                {score.gateReason && (
                  <span className="mt-0.5 block text-[12px] leading-4 text-cosmos-red">{score.gateReason}</span>
                )}
              </Field>
            )}
            {summary && (
              <Field label="요약">
                <span className="text-[12px] leading-5 text-cosmos-secondary">{truncate(summary, 220)}</span>
              </Field>
            )}
          </dl>

          <p className="text-[12px] leading-5 text-cosmos-muted">
            {isSupport
              ? "기업마당 지원사업은 입찰이 아닙니다. 신청자격·필수조건·신청기간·제출서류는 신청 분석 화면에서 확인하고, 최종 신청 여부는 담당자가 판단합니다."
              : "참가자격·요구사항은 입찰 분석 화면에서 원문 근거와 함께 확인합니다. 최종 판단은 담당자가 합니다."}
          </p>
        </div>
      </details>
    </div>
  );
}
