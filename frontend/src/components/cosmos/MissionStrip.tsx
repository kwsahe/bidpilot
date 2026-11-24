"use client";

/**
 * Mission Summary — 상단 KPI. 기본 5개(우리 회사 적합도 · 입찰 참가 가능 여부 · 놓치면 안 되는 조건 ·
 * 수행근거 충족도 · 제출 전 발견된 문제) + 「상세 지표」(수행할 과업 · 필수 요구사항 · 제안서 반영 상태 · 결정).
 * 값은 전부 lib/cosmos/mission.ts 가 CosmosGraph에서 계산한다. backend가 주지 않는 값은 "미실행"으로 표시하고,
 * 각 카드에 값의 출처(합성 시나리오 고정값 / 규칙 기반 판정 / 합성 RFP 실제 파싱 / 사람 확인 / 미실행)를 붙인다.
 * 카드를 누르면 해당 단계·노드로 이동한다. 지표를 없애지 않고 접을 뿐이다 (BLOCKER는 항상 기본 5개 안에 보인다).
 */

import { useCallback, useMemo, useSyncExternalStore } from "react";

import { SourceBadge } from "@/components/ui/SourceBadge";
import type { CosmosGraph, WorkflowStage } from "@/lib/cosmos/graph";
import { missionMetrics, type MissionMetric } from "@/lib/cosmos/mission";
import { TONE_COLORS, withAlpha } from "@/lib/cosmos/theme";
import { useAnalysisLoading, useNotRunLabel } from "@/lib/cosmos/analysisLoading";

export interface MissionStripProps {
  graph: CosmosGraph;
  stage: WorkflowStage;
  onNavigate: (stage: WorkflowStage, nodeId: string | null) => void;
  /**
   * 지금 고른 공고의 검토 우선순위 (0~100, 선택 회사 기준). 모르면 null.
   *
   * 「우리 회사 적합도」 옆에 함께 적는다 — 같은 공고가 목록·레이더에서 이 숫자로 보이는데
   * 대시보드만 다른 숫자를 말하고 있었다 (0920 §4-B-1).
   */
  reviewPriority?: number | null;
}

/** 「상세 지표」 펼침 기억 — 다른 기록(튜토리얼·안내)과 키가 겹치지 않는다. */
const KPI_STORAGE_KEY = "bidpilot.kpi.v1";
const kpiListeners = new Set<() => void>();
function readExpanded(): boolean {
  try {
    return window.localStorage.getItem(KPI_STORAGE_KEY) === "expanded";
  } catch {
    return false;
  }
}
function writeExpanded(value: boolean): void {
  try {
    window.localStorage.setItem(KPI_STORAGE_KEY, value ? "expanded" : "collapsed");
  } catch {
    // 저장 실패는 무시
  }
  for (const l of kpiListeners) l();
}
function subscribeExpanded(onChange: () => void): () => void {
  kpiListeners.add(onChange);
  return () => {
    kpiListeners.delete(onChange);
  };
}
const getExpandedServer = () => false;

function MetricCard({
  metric,
  current,
  onNavigate,
  compact,
}: {
  metric: MissionMetric;
  current: boolean;
  onNavigate: MissionStripProps["onNavigate"];
  compact: boolean;
}) {
  const color = TONE_COLORS[metric.tone];
  const pending = metric.value === null;
  // 값이 없을 때 「미실행」이라고 쓰면, 불러오는 중인 2~5초 동안 담당자가
  // 「안 돌렸구나」로 읽고 재분석을 누른다 (ISSUE-011).
  const notRun = useNotRunLabel();
  // 10-31 최종 점검 A5 — 값만 「불러오는 중…」이고 칩 「○ 아직 안 함」 · 안내 「자격 판정 아직 안 함」은 그대로였다 — 셋을 함께 바꾼다.
  // 값과 같은 조건(값 없음)만 — 「결정 전」 · 「AI 검색 꺼 둠」처럼 값이 있는 칸은 실제 상태라 그대로.
  const waiting = useAnalysisLoading() && pending;
  const sourceLabel = waiting ? "불러오는 중…" : metric.sourceLabel;
  const hint = waiting ? "결과를 불러오는 중…" : metric.hint;
  const alert = metric.tone === "fail";
  // 참가자격이 불가면 타일 자체를 붉게 (20차 §4-D-3) — 안 맞으면 입찰 신청 자체를 못 한다.
  const gateAlert = alert && metric.key === "eligibility";
  return (
    <button
      type="button"
      onClick={() => onNavigate(metric.stage, metric.nodeId)}
      aria-current={current ? "true" : undefined}
      aria-label={`${metric.koLabel} ${metric.value ?? notRun} ${metric.unit ?? ""} — ${hint}. 출처 ${sourceLabel}. ${metric.stage}단계로 이동`}
      className={`mc-focus group relative flex min-w-0 flex-col justify-between gap-0.5 rounded-xl border px-2.5 py-1.5 text-left transition-colors ${
        compact ? "min-h-[58px]" : "min-h-[64px]"
      } ${
        gateAlert
          ? `border-cosmos-red/70 ${current ? "bg-cosmos-elevated" : "bg-cosmos-panel hover:bg-cosmos-elevated/70"}`
          : current
            ? "border-cosmos-border-strong bg-cosmos-elevated"
            : "border-cosmos-border bg-cosmos-panel hover:border-cosmos-border-strong hover:bg-cosmos-elevated/70"
      }`}
      style={{ boxShadow: `inset 0 2px 0 ${pending ? "transparent" : withAlpha(color, 60)}` }}
    >
      <span className="flex min-w-0 items-center justify-between gap-1.5">
        {/* 영문 원어(Bid Fit 등)는 툴팁으로만 남긴다. 본문에 병기하면 결국 영문을 읽게
            되고, 같은 화면에 「입찰 참가 가능 여부」와 `Eligibility` 가 함께 뜬다 (ISSUE-016). */}
        <span
          className={`min-w-0 truncate text-[12px] font-semibold leading-4 ${gateAlert ? "text-cosmos-red-text" : "text-cosmos-secondary"}`}
          title={`${metric.koLabel} — ${hint}`}
        >
          {metric.koLabel}
        </span>
        {/* 640~1535px 에서는 칩 글자가 제목을 「우…」 「입찰 …」로 밀어냈다(1440 에서도) — 그 폭에서는 기호만
            (글자는 툴팁 · 읽는 이름에 그대로) (DSH-07). */}
        <span className="hidden shrink-0 sm:inline-flex 2xl:hidden" title={sourceLabel}>
          <SourceBadge kind={metric.source} label="" />
        </span>
        <span className="hidden shrink-0 2xl:inline-flex">
          <SourceBadge kind={metric.source} label={sourceLabel} />
        </span>
      </span>
      <span className="flex min-w-0 items-baseline gap-1">
        {alert && !pending && (
          <span aria-hidden="true" className="text-[13px] leading-none" style={{ color }}>
            ⚠
          </span>
        )}
        <span
          className={`truncate font-mono font-semibold tabular-nums leading-none ${
            pending ? "text-[13px] text-cosmos-muted" : "text-[20px]"
          }`}
          style={pending ? undefined : { color }}
        >
          {metric.value ?? notRun}
        </span>
        {metric.unit && !pending && <span className="shrink-0 text-[12px] text-cosmos-muted">{metric.unit}</span>}
      </span>
      {metric.ratio !== null && (
        <span className="block h-[3px] overflow-hidden rounded-full bg-cosmos-slate/60" aria-hidden="true">
          <span
            className="block h-full rounded-full transition-[width] duration-500"
            style={{ width: `${Math.round(metric.ratio * 100)}%`, backgroundColor: color }}
          />
        </span>
      )}
      <span className="truncate text-[12px] leading-4 text-cosmos-secondary">{hint}</span>
    </button>
  );
}

/**
 * 「불가 0」과 「참가 차단 1」 사이를 이어 주는 한 줄 (0920 §4-B-5 · ISSUE-078).
 *
 * 두 숫자가 나란히 붙어 있는데 관계를 아무도 설명하지 않았다. 담당자는 「불가가 0인데
 * 왜 차단이 1인가」를 알 수 없었다. 사실은 **자격 규칙 「불가」가 참가 차단 조건에 함께
 * 세어진다**(`critical_condition_service.detect_from_eligibility`) — 별개 항목이 아니다.
 *
 * 문구는 백엔드가 실제로 막는 것에 맞춘다. 막히는 것은 **「참여」(GO) 저장 하나뿐**이고
 * (`decision_service.save_decision`), 보류·참여 안 함은 차단 조건이 남아 있어도 저장된다.
 * 「결정 저장 불가」로 넓히면 거짓이 된다.
 *
 * 조건을 **탐지한 적이 없으면 아무 말도 하지 않는다.** 그때는 게이트가 없어 GO 도 막히지
 * 않는데, 「해결 전에는 저장 불가」라고 적으면 없는 제약을 지어내는 것이다.
 */
function ConditionGateLine({ graph }: { graph: CosmosGraph }) {
  const report = graph.source.analysis.conditions;
  if (!report) return null;
  const blockers = report.counts.blocker;
  if (blockers <= 0) return null;
  return (
    <p className="mt-1 px-1.5 text-[12px] leading-4 text-cosmos-amber" role="note">
      참가 차단 {blockers}건에는 자격 규칙 「불가」도 함께 셉니다 — 담당자가 「해결됨」으로
      처리하기 전에는 「참여」 결정을 저장할 수 없습니다(보류·참여 안 함은 저장됩니다).
    </p>
  );
}

export default function MissionStrip({ graph, stage, onNavigate, reviewPriority = null }: MissionStripProps) {
  const metrics = useMemo(() => missionMetrics(graph, reviewPriority), [graph, reviewPriority]);
  const primary = useMemo(() => metrics.filter((m) => m.primary), [metrics]);
  const secondary = useMemo(() => metrics.filter((m) => !m.primary), [metrics]);
  const expanded = useSyncExternalStore(subscribeExpanded, readExpanded, getExpandedServer);
  const toggle = useCallback(() => writeExpanded(!expanded), [expanded]);
  const notRun = useNotRunLabel();
  const secondarySummary = secondary
    // 값이 이름을 이미 품으면(「결정」 → 「결정 전」) 이름을 되풀이하지 않는다.
    .map((m) => `${(m.value ?? "").startsWith(m.koLabel) ? "" : `${m.koLabel} `}${m.value ?? notRun}${m.value !== null && m.unit ? m.unit : ""}`)
    .join(" · ");

  return (
    <section aria-label="분석 요약 지표" data-tour="mission-strip" className="shrink-0 px-3 pt-2">
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-5">
        {primary.map((metric) => (
          <MetricCard key={metric.key} metric={metric} current={metric.stage === stage} onNavigate={onNavigate} compact={!expanded} />
        ))}
      </div>
      <ConditionGateLine graph={graph} />
      <div className="mt-1 flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          aria-controls={expanded ? "mission-strip-secondary" : undefined}
          className="mc-focus flex min-h-6 shrink-0 items-center gap-1 rounded-md px-1.5 text-[12px] font-medium text-cosmos-secondary hover:bg-cosmos-elevated/70 hover:text-cosmos-text"
        >
          <span aria-hidden="true" className="text-[12px]">
            {expanded ? "▾" : "▸"}
          </span>
          상세 지표 {expanded ? "접기" : "보기"}
        </button>
        {!expanded && <span className="min-w-0 truncate text-[12px] text-cosmos-muted">{secondarySummary}</span>}
      </div>
      {expanded && (
        <div id="mission-strip-secondary" className="mt-1 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {secondary.map((metric) => (
            <MetricCard key={metric.key} metric={metric} current={metric.stage === stage} onNavigate={onNavigate} compact />
          ))}
        </div>
      )}
    </section>
  );
}
