"use client";

/**
 * 사업기회 레이더 — 관제 콘솔 껍데기.
 *
 * 스코프(RadarScene2D/3D) 주변에 붙는 계기 표시들이다. **여기 나오는 숫자는 전부 실제 응답에서 온다.**
 * 지연시간·위성·서버 부하 같은 만들어 낸 값은 두지 않는다 — 없는 데이터를 관제 화면처럼 꾸미면
 * 화면 전체의 신뢰가 깨진다.
 *
 * 계기를 세 자리로 나눠 같은 숫자를 반복하지 않는다.
 *   머리말 telemetry  = **무엇을 보고 있나** (표시 건수 · 출처별 건수)
 *   스코프 좌측 rail  = **무엇이 주의를 요구하나** (우선 검토 — 실무순 회사는 신규+여유 · 마감 임박 · 점수 미확인 · 마감 포함)
 *   스코프 우측 HUD   = **자료가 언제 것인가** (출처 상태 · 조회 시각)
 *
 * 아이콘은 인라인 SVG로 그린다. 아이콘 몇 개 때문에 의존성을 늘리지 않는다.
 */

import {
  DataFeedIcon,
  DeadlineIcon,
  LandedIcon,
  PriorityContactIcon,
  RadarSweepIcon,
  SignalLostIcon,
} from "@/components/icons/aviation";
import { formatDateTime } from "@/lib/cosmos/format";
import { formatDDay } from "@/lib/cosmos/format";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import type { RadarLayout } from "@/lib/radar/layout";
import type { UnifiedOpportunityListResponse } from "@/types/opportunity";
import { FROZEN_RELOAD_REASON } from "@/components/ui/FrozenNotice";
import { DATA_STATUS_MARK } from "@/components/ui/SourceBadge";
import { FROZEN_TERM, RELOAD_TERM, SYNTHETIC_NOTICE, UNSCORED, collectTerm, collectWarns } from "@/lib/terms";
import type { CollectState } from "@/types/opportunity";
import { REVIEW_PRIORITY } from "@/lib/scoreNames";
import { useRankingMethod } from "@/components/opportunities/PracticalTags";

// ---------------------------------------------------------------------------
// 자료 상태 — 문구와 색을 한 곳에서 정한다
// ---------------------------------------------------------------------------

export type ConsoleTone = "ok" | "cached" | "frozen" | "sample" | "error" | "loading";

/** 점 색은 데이터 상태 칩과 같은 곳(`DATA_STATUS_MARK`)에서 — 캐시가 칩은 파랑, 점은 주황이던 것을 없앴다 (27차 §3-E · UNI-18). */
const TONE_COLOR: Record<ConsoleTone, string> = {
  ok: DATA_STATUS_MARK.live.color,
  cached: DATA_STATUS_MARK.cached.color,
  frozen: DATA_STATUS_MARK.frozen.color,
  sample: DATA_STATUS_MARK.sample.color,
  error: DATA_STATUS_MARK.error.color,
  loading: DATA_STATUS_MARK.loading.color,
};

const TONE_WORD: Record<ConsoleTone, string> = {
  ok: "실시간 조회",
  cached: "저장본 사용 중",
  frozen: FROZEN_TERM,
  sample: "가상 예시 공고 포함",
  error: "조회 실패",
  loading: "조회 중",
};

/** 응답 상태 → 콘솔 톤. RadarDataStatus 의 판정과 같은 규칙이다. */
export function consoleTone(
  data: UnifiedOpportunityListResponse | null,
  loading: boolean,
  error: string | null,
): ConsoleTone {
  if (loading) return "loading";
  if (error) return "error";
  if (!data) return "cached";
  if (Object.values(data.source_errors).some(Boolean)) return "error";
  const values = Object.values(data.source_status);
  if (values.includes("sample")) return "sample";
  // 시연 고정이면 캐시는 사고가 아니라 의도 — 데이터 상태 칩과 같은 ⏸ 「시연 고정」 (27차 §3-E · UNI-18).
  if (data.frozen) return "frozen";
  if (values.includes("cached")) return "cached";
  return "ok";
}

// ---------------------------------------------------------------------------
// 작은 조각
// ---------------------------------------------------------------------------

/** 상태 점. 정상일 때만 아주 약하게 숨쉰다 — 깜빡이지 않는다. */
export function StatusDot({ tone, reducedMotion = false, calm = false }: { tone: ConsoleTone; reducedMotion?: boolean; calm?: boolean }) {
  // calm — 고정 모드인데 자동 받기가 경고가 아닐 때(오늘 받음 · 받는 중 · 꺼 둠 · 모름) 호박 대신 보통색(40차 COLLECT-08)
  const color = calm ? COSMOS_COLORS.slate : TONE_COLOR[tone];
  return (
    <span aria-hidden="true" className="relative inline-flex h-[7px] w-[7px] shrink-0">
      {tone === "ok" && !reducedMotion && (
        <span
          className="absolute inset-0 animate-ping rounded-full opacity-60"
          style={{ backgroundColor: color, animationDuration: "2.6s" }}
        />
      )}
      <span className="relative inline-flex h-full w-full rounded-full" style={{ backgroundColor: color }} />
    </span>
  );
}

/** 재수집 아이콘 — 도는 동안만 회전한다(항상 도는 장식이 아니다). */
function RecollectIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={11}
      height={11}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={spinning ? "animate-spin" : undefined}
    >
      <path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1" />
      <path d="M20.5 4.2v4.6h-4.6" />
    </svg>
  );
}

/** 관제 UI의 작은 머리 글자. 화면 글자는 한국어다(27차 RDR-34 — 「DATA FEED」 등 영문 라벨을 한국어로). */
function Micro({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`text-[12px] font-semibold uppercase leading-none tracking-[0.16em] text-cosmos-muted ${className}`}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// 머리말 telemetry — 무엇을 보고 있나
// ---------------------------------------------------------------------------

export interface TelemetryBarProps {
  layout: RadarLayout;
  hiddenCount: number;
  /** 아직 조회 중이면 숫자 대신 자리표시를 둔다. */
  loading: boolean;
  /**
   * 건수의 단일 분모 (0920 §4-B-2 · ISSUE-075-c).
   *
   * 레이더는 200건을 받아 12건만 그리는데 계기판이 「나라장터 1」이라고 적어, 같은 화면의
   * 데이터 상태(「나라장터 7건」)와 갈래 칩(「AI 교육 4」)이 서로 다른 숫자를 말했다.
   * **분모를 늘 함께 적는다** — 「1 / 102」.
   *
   * 분모는 **불가를 거른 뒤의 수**(`total_count` · `g2b_count` · `bizinfo_count`)다 — 레이더가 그릴 수 있는 집합이고
   * 데이터 상태 「기업마당 502건」 · 상세 「기업마당 1/502」와 같은 수다. 예전 `summary.open_*` 는 불가(약 900건)를
   * 포함해 한 화면에 분모가 둘이었다(27차 RDR-01). 숨긴 불가 수는 따로 적는다(RDR-05).
   */
  data: UnifiedOpportunityListResponse | null;
  /**
   * 갈래를 골랐을 때 그 갈래의 건수(`track_counts`) — 「전체 갈래」면 null.
   *
   * 갈래를 고르면 「N건은 전체 목록에서」는 갈래 기준인데 「표시」 분모는 갈래를 무시한 `total_count` 라
   * 한 줄 안에서 두 기준이 따로 놀았다(27차 RDR-01 · RDR-09). 갈래를 고르면 분모도 갈래 기준이다.
   * 갈래는 나라장터에만 있다(기업마당은 `work_tracks` 가 빈 배열) — 나라장터 분모도 같은 수다.
   */
  trackTotal?: number | null;
}

/** 큰 숫자 + 작은 이름. 지표를 카드로 감싸지 않고 한 줄에 붙여 관제 계기처럼 읽히게 한다. */
export function TelemetryBar({ layout, hiddenCount, loading, data, trackTotal = null }: TelemetryBarProps) {
  const blocked = data?.summary?.blocked ?? data?.blocked_count ?? 0;
  const byTrack = trackTotal !== null;
  // 갈래를 고르면 기업마당은 통째로 빠진다 — 「0 / 502」 대신 빠진 수를 글로 적는다.
  const trackDroppedBizinfo = byTrack ? (data?.bizinfo_count ?? 0) : 0;
  // 출처를 하나로 좁혀 부르지 않은 쪽(source_status null)은 「0 / 0」으로 적지 않는다 — 고장처럼 읽힌다 (27차 RDR-15).
  const excluded = (key: "g2b" | "bizinfo") => data !== null && data.source_status[key] === null;
  // 숫자 풀이(39차 §3-G) — 분모는 그릴 수 있는 것만이다(비추천 · 사전규격 · 직접 넣음 뺌) · 사업기회 머리 수와 다른 까닭
  const cells: Array<{ label: string; value: number; total?: number; color?: string; hidden?: boolean; hint?: string }> = [
    { label: "그림에 올림", value: layout.nodes.length, total: byTrack ? trackTotal : data?.total_count, hint: "분모는 레이더가 그릴 수 있는 사업기회(비추천 · 사전규격 · 직접 넣음 뺌)" },
    {
      label: "나라장터",
      value: layout.g2bCount,
      total: byTrack ? trackTotal : data?.g2b_count,
      color: COSMOS_COLORS.cyan,
      hidden: excluded("g2b"),
      hint: "분모는 그릴 수 있는 마감 전 입찰(비추천 · 사전규격 뺌) — 사업기회 머리 「나라장터 N」은 비추천까지 센다",
    },
    {
      label: "기업마당",
      value: layout.bizinfoCount,
      total: data?.bizinfo_count,
      color: COSMOS_COLORS.violet,
      hidden: excluded("bizinfo") || byTrack,
    },
    {
      label: "마감 임박",
      value: layout.urgentCount,
      color: layout.urgentCount > 0 ? COSMOS_COLORS.amber : undefined,
    },
  ];
  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
      {cells.filter((cell) => !cell.hidden).map((cell) => (
        <div key={cell.label} className="flex items-baseline gap-1.5" title={cell.hint}>
          <span
            className="font-mono text-[19px] font-semibold leading-none tabular-nums"
            style={{ color: cell.color ?? COSMOS_COLORS.textPrimary }}
          >
            {loading ? "–" : cell.value.toLocaleString("ko-KR")}
            {/* 분모 없는 숫자는 「전부」로 읽힌다. 레이더는 늘 일부만 그린다. */}
            {!loading && cell.total !== undefined && (
              <span className="text-[13px] text-cosmos-muted"> / {cell.total.toLocaleString("ko-KR")}</span>
            )}
          </span>
          <span className="text-[12px] leading-none text-cosmos-muted">{cell.label}</span>
        </div>
      ))}
      {hiddenCount > 0 && !loading && (
        <span className="text-[12px] leading-4 text-cosmos-muted">{hiddenCount.toLocaleString("ko-KR")}건은 전체 목록에서</span>
      )}
      {trackDroppedBizinfo > 0 && !loading && (
        <span className="text-[12px] leading-4 text-cosmos-muted">
          기업마당 {trackDroppedBizinfo.toLocaleString("ko-KR")}건은 일의 종류가 없어 빠짐
        </span>
      )}
      {/* 레이더는 불가 판정을 서버에서 숨긴 목록만 그린다 — 몇 건 숨겼는지 · 어디서 다시 보는지 (27차 RDR-05) */}
      {blocked > 0 && !loading && (
        <span className="text-[12px] leading-4 text-cosmos-muted">
          참가 불가 {blocked.toLocaleString("ko-KR")}건{byTrack ? "(전체 갈래 기준)" : ""}은 숨김 — 전체 목록 「불가 포함」에서 봅니다
        </span>
      )}
      {/* 조회 기간 — 실호출에서만 목록을 가른다(시연 고정은 저장 목록 전체라 적지 않는다 · 27차 RDR-28) */}
      {data && !data.frozen && !loading && data.summary?.days !== undefined && (
        <span className="text-[12px] leading-4 text-cosmos-muted">최근 {data.summary.days}일</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 머리말 우측 — 자료 상태 요약
// ---------------------------------------------------------------------------

export function SystemBadge({
  tone,
  fetchedAt,
  reducedMotion,
  collectState = null,
}: {
  tone: ConsoleTone;
  fetchedAt: string | null;
  reducedMotion: boolean;
  /** 자동 받기 한 줄(39차 §3-F-2) — 고정 모드면 「새 공고 받기 꺼짐」 대신 이 PC 의 자동 받기 상태를 짧게(`collectTerm` 하나). */
  collectState?: CollectState | null;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5">
      <StatusDot tone={tone} reducedMotion={reducedMotion} calm={tone === "frozen" && !collectWarns(collectState)} />
      <div className="flex flex-col gap-0.5">
        <span className="text-[12px] font-medium leading-none text-cosmos-text">{tone === "frozen" ? collectTerm(collectState, null, true) : TONE_WORD[tone]}</span>
        {/* 390 폭에서 머리 오른쪽 묶음이 창 밖으로 넘쳤다(약 430px) — 좁은 폭은 날짜 줄을 접는다.
            조회 시각은 「데이터 상태」 팝오버에 그대로 있다 (27차 RDR-10). */}
        <span className="hidden font-mono text-[12px] leading-none tabular-nums text-cosmos-muted sm:block">
          {fetchedAt ? formatDateTime(fetchedAt) : "조회 전"}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 스코프 좌측 rail — 무엇이 주의를 요구하나
// ---------------------------------------------------------------------------

export interface StatRailProps {
  layout: RadarLayout;
  /** 「우선 검토」 등급 건수 — backend 가 매긴 priority_label 을 그대로 센다. */
  priorityCount: number;
}

/** 카드 여러 장이 아니라 세로 정보 기둥 하나. 값이 0인 항목은 흐리게 둔다(자리는 유지). */
export function StatRail({ layout, priorityCount }: StatRailProps) {
  const practical = useRankingMethod() === "practical";
  // 아이콘은 전부 항공 관제 어휘로 통일한다 — 스코프·계기가 한 세계로 읽혀야 한다.
  const rows: Array<{ Icon: typeof RadarSweepIcon; label: string; value: number; color: string }> = [
    { Icon: RadarSweepIcon, label: "그림에 올린 건", value: layout.nodes.length, color: COSMOS_COLORS.textPrimary },
    // (2.0.6) 실무 우선순위 회사는 사업기회에 「우선 검토」 숫자가 없다(분류 칸 「신규+여유」가 대신 · 37차 §3-B-4) — 서버가 매긴 칸을
    // 그림 안에서 센다. 레이더는 불가 · 관련 낮음 · 직접 넣음을 받지 않아 전체 수가 사업기회와 같다고 말할 수 없으므로 「(그림)」이라 적는다.
    practical
      ? {
          Icon: PriorityContactIcon,
          label: "신규+여유(그림)",
          value: layout.nodes.filter((node) => node.item.practical_group === "신규+여유").length,
          color: COSMOS_COLORS.cyan,
        }
      : // 이 한 줄만 그림 밖(전체 목록) 기준이다 — 이름에 적는다 (27차 RDR-12).
        { Icon: PriorityContactIcon, label: "우선 검토(전체)", value: priorityCount, color: COSMOS_COLORS.cyan },
    { Icon: DeadlineIcon, label: "마감 임박", value: layout.urgentCount, color: COSMOS_COLORS.amber },
    { Icon: SignalLostIcon, label: UNSCORED, value: layout.unknownScoreCount, color: COSMOS_COLORS.amber },
    // 마감된 건 = 착륙해 더 이상 추적하지 않는 기체
    // 「마감 포함」은 설정 이름처럼 읽혔다 — 그림 속 마감된 노드 수다 (27차 RDR-13).
    { Icon: LandedIcon, label: "마감된 건", value: layout.closedCount, color: COSMOS_COLORS.textMuted },
  ];
  return (
    <dl className="flex flex-col gap-3">
      {rows.map((row) => {
        const zero = row.value === 0;
        return (
          /*
            dl 안에는 div > dt + dd 만 둔다 — 줄 div 안에 아이콘 · 한 겹 더 싼 div 가 있어 규칙에 어긋났다.
            이름(dt)이 값(dd)보다 먼저 와야 스크린리더가 짝을 맞게 읽고, 보이는 순서(값 위 · 이름 아래)는 flex-col-reverse 로 그대로다.
            아이콘은 dt 안에 두고 줄 왼쪽 가운데로 띄운다 (27차 RDR-14).
          */
          // 외부 점검 UI g — 값 0 줄을 흐리게(opacity 0.45 · 대비 약 2.4:1) 하지 않는다 · 회청 값 · 아이콘만으로 구분
          <div key={row.label} className="relative flex min-w-0 flex-col-reverse pl-[23px]">
            <dt className="mt-0.5 whitespace-nowrap text-[12px] leading-none text-cosmos-muted">
              <row.Icon
                size={15}
                className="absolute left-0 top-1/2 -translate-y-1/2"
                style={{ color: zero ? COSMOS_COLORS.textMuted : row.color }}
              />
              {row.label}
            </dt>
            <dd
              className="font-mono text-[15px] font-semibold leading-none tabular-nums"
              style={{ color: zero ? COSMOS_COLORS.textMuted : row.color }}
            >
              {row.value}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// 스코프 우측 HUD — 자료가 언제 것인가
// ---------------------------------------------------------------------------

export interface TrackingHudProps {
  data: UnifiedOpportunityListResponse | null;
  tone: ConsoleTone;
  reducedMotion: boolean;
}

const SOURCE_STATE_WORD: Record<string, string> = {
  g2b: "실시간",
  bizinfo: "실시간",
  cached: "캐시",
  sample: SYNTHETIC_NOTICE,
};

/** 출처 하나의 상태 낱말 — 출처를 하나로 좁혀 부르지 않은 쪽(null)은 고장이 아니라 「제외」다 (27차 RDR-15). */
function sourceStateWord(status: string | null | undefined): string {
  if (status === null || status === undefined) return "조회 제외";
  return SOURCE_STATE_WORD[status] ?? "미상";
}

export function TrackingHud({ data, tone, reducedMotion }: TrackingHudProps) {
  const rows: Array<[string, string]> = [
    ["나라장터", data ? sourceStateWord(data.source_status.g2b) : "–"],
    ["기업마당", data ? sourceStateWord(data.source_status.bizinfo) : "–"],
    ["조회 시각", data ? formatDateTime(data.fetched_at) : "–"],
  ];
  return (
    <div className="pointer-events-none rounded-md border border-cosmos-border bg-cosmos-panel/90 px-2.5 py-2 backdrop-blur">
      <div className="flex items-center gap-1.5">
        <StatusDot tone={tone} reducedMotion={reducedMotion} />
        <DataFeedIcon size={12} className="text-cosmos-muted" />
        <Micro>자료 상태</Micro>
      </div>
      <dl className="mt-1.5 flex flex-col gap-1">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="text-[12px] leading-none text-cosmos-muted">{label}</dt>
            <dd className="font-mono text-[12px] leading-none tabular-nums text-cosmos-secondary">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 스코프 하단 상태 줄
// ---------------------------------------------------------------------------

export interface StatusStripProps {
  tone: ConsoleTone;
  data: UnifiedOpportunityListResponse | null;
  layout: RadarLayout;
  reducedMotion: boolean;
  /** 나라장터·기업마당을 **다시 호출**한다 (캐시를 건너뛴다). */
  onRecollect: () => void;
  loading: boolean;
}

/**
 * 캐시 톤의 한 줄. 「한쪽」은 부른 출처끼리 실제로 다를 때만 쓴다 (27차 RDR-02).
 * 출처를 하나로 좁혀 부르지 않은 쪽(source_status null)은 「다름」이 아니라 판정에서 뺀다.
 */
function cachedMessage(data: UnifiedOpportunityListResponse | null): string {
  const called = Object.values(data?.source_status ?? {}).filter((status) => status !== null && status !== undefined);
  if (called.length > 0 && called.every((status) => status === "cached")) {
    return called.length > 1 ? "두 출처 모두 저장본입니다(실시간 아님). 받은 때를 확인하세요." : "저장본 목록입니다(실시간 아님). 받은 때를 확인하세요.";
  }
  return "한쪽 출처가 저장본입니다(실시간 아님). 받은 때를 확인하세요.";
}

/**
 * 스코프 아래 얇은 줄.
 * 「실시간」이라고 쓰지 않는다 — 이 화면은 열 때 한 번 조회하고, 「데이터 상태」에서 다시 부른다.
 */
export function StatusStrip({ tone, data, layout, reducedMotion, onRecollect, loading }: StatusStripProps) {
  /**
   * 시연 고정 모드면 재수집을 잠근다 (ISSUE-070).
   *
   * 「데이터 상태」 팝오버의 재수집은 이미 잠겨 있었는데 **여기 하나가 남아 있었다.**
   * 백엔드가 고정 모드라 눌러도 캐시가 돌아오므로 해는 없지만, 툴팁이
   * 「캐시를 쓰지 않습니다」라고 말하는 순간 그 문구가 거짓이 된다. 발표 중 이 단추를 눌러
   * 아무 일도 일어나지 않으면 발표자는 고장으로 읽는다.
   */
  const frozen = Boolean(data?.frozen);
  const message =
    tone === "error"
      ? "자료를 불러오지 못했습니다. 「자료 상태」에서 다시 시도하세요."
      : tone === "sample"
        ? "기업마당 항목에 가상 예시 공고가 섞여 있습니다 — 실제 공고가 아닙니다."
        : tone === "cached"
          ? cachedMessage(data)
          : tone === "loading"
            ? "사업기회를 불러오는 중입니다."
            : layout.nodes.length === 0
              ? // 빈 결과에 「0건을 마감이 이른 순서로 배치했습니다」라고 적었다 — 무대의 빈 상태와 같은 말 (27차 §3-F 새로 찾음).
                "지금 조건으로 표시할 사업기회가 없습니다."
              : `${layout.nodes.length}건을 마감이 이른 순서로 배치했습니다. 크기는 회사 기준 검토 우선순위 점수입니다.`;

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-cosmos-border px-3 py-2">
      <p className="flex min-w-0 items-center gap-2 text-[12px] leading-4 text-cosmos-secondary">
        <StatusDot tone={tone} reducedMotion={reducedMotion} />
        <span className="min-w-0">{message}</span>
      </p>
      <div className="flex flex-wrap items-center gap-2.5">
        <p className="font-mono text-[12px] leading-4 tabular-nums text-cosmos-muted">
          {data ? `조회 ${formatDateTime(data.fetched_at)}` : "조회 전"}
        </p>
        {/* 잠긴 이유를 툴팁에만 두면 터치 기기에서 볼 수 없다 — 보이는 글로 두고 단추와 잇는다 (27차 RDR-16). */}
        {frozen && (
          <span id="radar-strip-reload-reason" className="text-[12px] leading-4 text-cosmos-muted">
            {FROZEN_RELOAD_REASON}
          </span>
        )}
        {/*
          「다시 불러오기」는 화면 새로고침이 아니라 **출처를 다시 부르는** 동작이다. 사업기회의 「재수집」
          (확인 창 · 저장 목록 교체)과 다른 단추라 이름을 가른다 (27차 UNI-20).
          캐시를 건너뛰고 나라장터·기업마당 API 를 실제로 호출하므로 몇 초 걸린다.
          시연 고정 모드에서는 부르지 않으므로 잠근다 (ISSUE-070).
        */}
        <button
          type="button"
          onClick={onRecollect}
          disabled={loading || frozen}
          aria-describedby={frozen ? "radar-strip-reload-reason" : undefined}
          title={frozen ? FROZEN_RELOAD_REASON : "나라장터와 기업마당을 다시 조회합니다 (캐시를 쓰지 않습니다)"}
          className="mc-focus inline-flex items-center gap-1 rounded-full border border-cosmos-border px-2 py-0.5 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-cyan/60 hover:text-cosmos-text disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RecollectIcon spinning={loading && !frozen} />
          {frozen ? `${RELOAD_TERM} 잠김` : loading ? "불러오는 중…" : RELOAD_TERM}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 스코프 틀 — 모서리 괄호 + 눈금 설명
// ---------------------------------------------------------------------------

/** 관제 화면 느낌을 내는 최소한의 장식. 데이터가 아니므로 aria 에서 숨긴다. */
export function ScopeCorners() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      {(
        [
          ["left-0 top-0", "border-l border-t"],
          ["right-0 top-0", "border-r border-t"],
          ["left-0 bottom-0", "border-b border-l"],
          ["right-0 bottom-0", "border-b border-r"],
        ] as const
      ).map(([pos, edge]) => (
        <span key={pos} className={`absolute h-4 w-4 border-cosmos-border-strong ${pos} ${edge}`} />
      ))}
    </div>
  );
}

/** 반경 눈금이 무슨 값인지 한 줄로 적는다 — 스코프 안의 숫자가 뭔지 모르면 장식이 된다. */
/**
 * 스코프 눈금 설명.
 *
 * 축이 데이터에서 나오므로 **실제 양 끝 값**을 적는다 — 고정 문구를 쓰면 화면과 어긋난다.
 * 축에 올릴 항목이 없으면(전부 마감일 없음) 축 이야기를 하지 않는다.
 */
export function ScopeScaleNote({
  layout,
  className = "",
}: {
  layout: RadarLayout;
  className?: string;
}) {
  const { stops } = layout.deadlineAxis;
  // 불러오는 중 · 빈 결과에는 노드가 없다 — 「마감일이 있는 항목이 없어…」는 사실이 아니다 (27차 §3-F 새로 찾음).
  if (layout.nodes.length === 0) return null;
  if (stops.length === 0) {
    return (
      <p className={`text-[12px] leading-4 text-cosmos-muted ${className}`}>
        마감일이 있는 항목이 없어 시간축을 그리지 않았습니다 · 크기 = {REVIEW_PRIORITY.label}(마감 무관)
      </p>
    );
  }
  const inner = formatDDay(stops[0]);
  const outer = formatDDay(stops[stops.length - 1]);
  return (
    <p className={`text-[12px] leading-4 text-cosmos-muted ${className}`}>
      가운데일수록 마감이 빠름(<span className="font-mono tabular-nums">{inner}</span> ~{" "}
      <span className="font-mono tabular-nums">{outer}</span>) · 클수록 {REVIEW_PRIORITY.label}가 높음
    </p>
  );
}

export { Micro as ConsoleMicroLabel };
