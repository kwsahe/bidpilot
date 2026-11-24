"use client";

/**
 * 사업기회 레이더 — 화면 전체 조립.
 *
 * 이 화면이 답하는 질문은 하나다: **우리 회사가 지금 먼저 검토할 사업기회는 무엇인가?**
 *
 * 관제 콘솔 배치 — 스코프가 화면의 중심(약 70%)이고 오른쪽이 추적 목록(약 30%)이다.
 * 계기는 세 자리로 나눠 같은 숫자를 반복하지 않는다(RadarConsole 주석 참고):
 *   머리말 telemetry = 무엇을 보고 있나 · 좌측 rail = 무엇이 주의를 요구하나 ·
 *   우측 HUD = 자료가 언제 것인가.
 *
 * 스코프가 읽히는 규칙은 두 축뿐이다 — **거리 = 회사 적합도 점수**, **방향 = 출처**.
 * 방위 각도의 절대값은 뜻이 없으므로 숫자를 적지 않고 섹터 이름만 적는다(lib/radar/layout.ts).
 *
 * 뺀 것은 **지우지 않고** 자리를 옮겼다:
 *  - 정렬 · 표시 개수 · 3D/2D · 마감 포함 → 「필터」 시트(RadarFilterSheet)
 *  - 출처별 상태 · 캐시 · 조회 시각 · 새로고침 → 「데이터 상태」 팝오버(RadarDataStatus)
 *  - 노드 크기·링 경계·점수 산정 방식·확률 아님 설명 → 「읽는 법」 팝오버(RadarReadingGuide)
 *  - 전체 목록 → /opportunities · 배점표와 메타데이터 → 상세의 「점수 산정 근거 보기」 접기
 *
 * 상태를 전부 다룬다: 로딩 / API 오류 / 빈 결과 / 두 출처 정상 / 한쪽만 정상 / 캐시 /
 * 합성 샘플 / 마감일 없음 / 금액 없음 / WebGL 차단 / reduced motion / 모바일.
 *
 * 3D는 마우스 전용 조작이므로 **순위 목록(버튼 리스트)** 을 항상 열 수 있게 둔다 —
 * 키보드·모바일의 실제 조작 수단이다. 모바일에서는 그 목록이 기본 화면이고 3D는 선택이다.
 */

import dynamic from "next/dynamic";
import { SCREEN_NAMES } from "@/lib/terms";
import Link from "next/link";
import {
  Component,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  ScopeCorners,
  ScopeScaleNote,
  StatRail,
  StatusStrip,
  SystemBadge,
  TelemetryBar,
  TrackingHud,
  consoleTone,
} from "@/components/radar/RadarConsole";
import RadarDataStatus from "@/components/radar/RadarDataStatus";
import RadarDetail from "@/components/radar/RadarDetail";
import RadarFilterSheet, {
  DEFAULT_FILTERS,
  VISIBLE_OPTIONS,
  changedFilterCount,
  type RadarFilterState,
  type ViewMode,
  type VisibleCount,
} from "@/components/radar/RadarFilterSheet";
import RadarLegend, { RadarReadingGuide } from "@/components/radar/RadarLegend";
import RadarRankList from "@/components/radar/RadarRankList";
import RadarScene2D from "@/components/radar/RadarScene2D";
import RadarTrackedPanel from "@/components/radar/RadarTrackedPanel";
import { RankingMethodContext } from "@/components/opportunities/PracticalTags";
import AppShell from "@/components/ui/AppShell";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { Popover, Sheet } from "@/components/ui/overlays";
import { Button, Chip, EmptyState, InlineAlert, LoadingState, Panel, SectionHeader, Spinner } from "@/components/ui/primitives";
import { usePeriodDays } from "@/lib/period";
import {
  hrefWithConditions,
  isSupportProgramId,
  readSelection,
  readSelectionServer,
  subscribeSelection,
  writeSelection,
} from "@/lib/selection";
import { describeFailure } from "@/lib/errors";
import { ApiError, getBusinessOpportunities } from "@/lib/api";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { useNowMs, useReducedMotion } from "@/lib/cosmos/useCosmosDashboard";
import { useWebGLSupport } from "@/lib/cosmos/webgl";
import { organizationName, useOrganizationId, useOrganizations } from "@/lib/organization";
import { buildRadarLayout, type RadarNode, type RadarSceneProps } from "@/lib/radar/layout";
import { type OpportunitySort, type SourceType, type UnifiedOpportunityListResponse } from "@/types/opportunity";
import { WORK_TRACK_LABELS, type WorkTrack } from "@/types/capability";

// 3D는 SSR 금지 — 브라우저에서만, 그리고 실제로 볼 때만 불러온다.
const RadarScene3D = dynamic<RadarSceneProps>(() => import("@/components/radar/RadarScene3D"), {
  ssr: false,
  loading: () => <StagePlaceholder label="3D 레이더를 불러오는 중" />,
});

/**
 * 한 번에 받아 둘 최대 건수. 화면에 그리는 개수는 따로 정한다.
 *
 * 20 이었을 때 문제가 있었다 — 갈래 칩의 숫자는 서버가 «자르기 전 전체»에서 센 값인데
 * 거르기는 받아 온 20건 안에서만 돌았다. 그래서 「개발 12」라고 적힌 칩을 눌러도
 * 노드가 0건이 나오고, 「N건이 더 있습니다」 안내도 실제보다 훨씬 작은 수를 말했다.
 * 담당자는 필터가 고장 난 것인지 정말 없는 것인지 구분할 수 없다.
 *
 * 전체를 받아 두면 칩 숫자와 거르기 결과가 같은 집합을 가리킨다.
 * 응답은 실측 약 310KB 로, 3D 장면을 띄우는 화면에서 감당할 만하다.
 */
const FETCH_LIMIT = 200;

type SourceFilter = "all" | SourceType;
type TrackFilter = "all" | WorkTrack;

/**
 * 주소에 남기는 조건 — **키 이름은 사업기회 목록과 같다** (0920 §4-B-4 · ISSUE-077-d).
 *
 * 레이더의 출처·갈래·정렬·마감 포함은 전부 화면 안에만 있었다. 그래서 「기업마당 · 교육 ·
 * 마감 임박」으로 맞춰 놓은 그림을 남에게 보낼 수 없었고, 새로고침 한 번에 사라졌다.
 * 목록 화면(`/opportunities`)은 이미 같은 조건을 `src`·`track`·`sort`·`closed` 로 적고
 * 있으므로 **같은 이름을 쓴다** — 두 화면 사이를 오갈 때 주소가 그대로 통한다.
 *
 * 공고 선택(`notice`·`support`)은 `lib/selection` 이 쓰고 지운다. 여기서는 건드리지 않는다.
 */
const URL_KEYS = {
  source: "src",
  track: "track",
  sort: "sort",
  closed: "closed",
  // 표시 개수·보기 모드도 남긴다 (0921 §4-E · ISSUE-077-d). 예전에는 뒤로가기 한 번에
  // 12건·3D 로 되돌아갔고, 「20건으로 놓고 보라」는 조건을 남에게 보낼 수 없었다.
  count: "n",
  view: "view",
} as const;

const subscribeNever = () => () => {};
const readSearchString = () => (typeof window === "undefined" ? "" : window.location.search);
const readSearchServer = () => "";
const getHydrated = () => true;
const getHydratedServer = () => false;

const SORT_KEYS: OpportunitySort[] = ["practical", "priority", "slack", "deadline", "recent", "value"];

const SOURCE_FILTERS: Array<{ key: SourceFilter; label: string; hint: string; color: string }> = [
  // 켜진 칩은 글자도 이 색이다(tintStyle) — 글자용 파랑(26차 ISSUE-155 · 원본 점수 칩과 같은 모양).
  { key: "all", label: "모두", hint: "나라장터 입찰과 기업마당 지원사업을 한 화면에", color: COSMOS_COLORS.blueText },
  { key: "g2b", label: "나라장터", hint: "우리 회사가 용역을 따내는 입찰공고만", color: COSMOS_COLORS.cyan },
  { key: "bizinfo", label: "기업마당", hint: "우리 회사가 지원금·바우처를 신청하는 사업(수행기관 · 주관기관 모집은 매출)", color: COSMOS_COLORS.violet },
];

/**
 * 일의 종류(갈래) 필터 — 「AI 교육이냐 개발이냐」.
 *
 * **출처와 다른 축이다.** 출처는 «어디서 온 공고인가»(나라장터·기업마당)이고, 갈래는
 * «무슨 일을 시키는가»다. 그래서 같은 줄에 나란히 둔다 — 둘 다 「무엇을 보고 있나」를 정한다.
 *
 * 단일 선택이다. 겹치는 공고(교육이면서 개발)는 **양쪽 탭에 모두 나오므로** 다중 선택이
 * 필요 없고, 다중 OR 은 「둘 다 켬 ≈ 둘 다 끔」이라는 읽기 어려운 상태를 만든다.
 *
 * 색은 주지 않는다 — 레이더에서 색은 «출처»가 나른다(lib/radar/layout.ts).
 * 「그 밖」만 주의색을 써서 «우리 역할이 아닐 수 있다»를 표시한다.
 */
// 칩 이름은 사업기회 목록과 같은 사전(WORK_TRACK_LABELS) — 「AI 교육 · 개발 · 그 밖」으로 따로 부르고 「갈래 미분류」가 없었다 (27차 RDR-25).
const TRACK_FILTERS: Array<{ key: TrackFilter; label: string; hint: string; color?: string }> = [
  { key: "all", label: "모든 일", hint: "일의 종류로 좁히지 않습니다" },
  { key: "education", label: WORK_TRACK_LABELS.education, hint: "교육·연수·컨설팅 사업만" },
  { key: "development", label: WORK_TRACK_LABELS.development, hint: "개발·구축 사업만" },
  {
    key: "other",
    label: WORK_TRACK_LABELS.other,
    hint: "감리·연구·구매·공사 — 우리가 수행사로 들어가는 일이 아닐 수 있습니다",
    color: COSMOS_COLORS.amber,
  },
  { key: "unclassified", label: WORK_TRACK_LABELS.unclassified, hint: "일의 종류를 가리지 못한 나라장터 공고" },
];

// ---------------------------------------------------------------------------
// 작은 조각
// ---------------------------------------------------------------------------

function StagePlaceholder({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="flex h-full w-full items-center justify-center">
      <div className="flex items-center gap-2.5 rounded-full border border-cosmos-border bg-cosmos-panel px-4 py-2 text-[13px] text-cosmos-secondary backdrop-blur">
        <Spinner />
        {label}
      </div>
    </div>
  );
}

/** 오른쪽 아래 — 오른쪽 위 자료 상태 상자와 같은 모서리에 겹쳐 윗줄을 가렸다 (27차 RDR-26). 왼쪽 위는 계기 기둥이다. */
function FallbackChip({ children }: { children: ReactNode }) {
  return (
    <div className="pointer-events-none absolute bottom-3 right-3 z-10 rounded-full border border-cosmos-amber/50 bg-cosmos-panel px-3 py-1 text-[12px] text-cosmos-amber backdrop-blur">
      {children}
    </div>
  );
}

interface BoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

/** 3D 런타임 오류를 잡아 2D로 떨어뜨린다. */
class SceneErrorBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

// ---------------------------------------------------------------------------
// 화면 폭 — 모바일(목록 우선) / 태블릿(상세는 시트) / 데스크톱(상세는 고정 패널)
// ---------------------------------------------------------------------------

type LayoutMode = "mobile" | "tablet" | "desktop";

const MOBILE_QUERY = "(max-width: 767px)";
const DESKTOP_QUERY = "(min-width: 1024px)";

function subscribeLayout(onChange: () => void): () => void {
  const mobile = window.matchMedia(MOBILE_QUERY);
  const desktop = window.matchMedia(DESKTOP_QUERY);
  mobile.addEventListener("change", onChange);
  desktop.addEventListener("change", onChange);
  return () => {
    mobile.removeEventListener("change", onChange);
    desktop.removeEventListener("change", onChange);
  };
}

function getLayout(): LayoutMode {
  if (window.matchMedia(MOBILE_QUERY).matches) return "mobile";
  return window.matchMedia(DESKTOP_QUERY).matches ? "desktop" : "tablet";
}
const getLayoutServer = (): LayoutMode => "desktop";

function useLayoutMode(): LayoutMode {
  return useSyncExternalStore(subscribeLayout, getLayout, getLayoutServer);
}

// ---------------------------------------------------------------------------
// 무대 (3D / 2D / 빈 상태)
// ---------------------------------------------------------------------------

/**
 * 빈 결과에서 할 일 — 지금 조건을 보고 말한다. 이미 「통합」인데 「통합으로 바꾸라」고 하던 고정 문장이었다 (27차 RDR-27).
 */
function emptyHint(source: SourceFilter, track: TrackFilter): string {
  const ways = [source !== "all" ? "출처를 「통합」으로" : null, track !== "all" ? "갈래를 「전체 갈래」로" : null].filter(Boolean);
  return [...ways.map((way) => `${way} 바꾸거나`), "전체 목록에서 확인하세요."].join(" ");
}

/**
 * (2.0.6) 「전체 목록」 주소에 불가 · 관련 낮음 · 마감 포함을 켠다 — 사업기회 주소 키 `blocked` · `unrelated` · `closed`.
 * 다른 화면에서 고른 공고가 레이더에 없고 까닭을 모를 때만 쓴다 — 그 공고가 불가 · 관련 낮음 · 마감이면 기본 목록에서도 안 보였다.
 */
function withHiddenIncluded(href: string): string {
  const [path, search = ""] = href.split("?");
  const query = new URLSearchParams(search);
  for (const key of ["blocked", "unrelated", "closed"]) query.set(key, "1");
  return `${path}?${query.toString()}`;
}

interface StageProps {
  source: SourceFilter;
  track: TrackFilter;
  loading: boolean;
  fetchError: string | null;
  companyName: string;
  viewMode: "3d" | "2d";
  webglSupported: boolean | null;
  sceneProps: RadarSceneProps;
}

function Stage({ source, track, loading, fetchError, companyName, viewMode, webglSupported, sceneProps }: StageProps) {
  if (loading) return <StagePlaceholder label="사업기회를 불러오는 중" />;
  if (fetchError) {
    return (
      <div className="flex h-full w-full items-center justify-center p-4">
        <EmptyState title="레이더를 그릴 수 없습니다" tone="fail">
          {fetchError}
        </EmptyState>
      </div>
    );
  }
  if (sceneProps.layout.nodes.length === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center p-4">
        <EmptyState title="표시할 사업기회가 없습니다" tone="muted">
          현재 회사({companyName})와 지금 조건에 맞는 항목이 없습니다. {emptyHint(source, track)}
        </EmptyState>
      </div>
    );
  }
  if (viewMode === "2d") return <RadarScene2D {...sceneProps} />;
  if (webglSupported === null) return <StagePlaceholder label="렌더러를 준비하는 중" />;
  if (!webglSupported) {
    return (
      <>
        <FallbackChip>3D를 쓸 수 없어 2D로 표시</FallbackChip>
        <RadarScene2D {...sceneProps} />
      </>
    );
  }
  return (
    <SceneErrorBoundary
      fallback={
        <>
          <FallbackChip>3D를 쓸 수 없어 2D로 표시</FallbackChip>
          <RadarScene2D {...sceneProps} />
        </>
      }
    >
      <RadarScene3D {...sceneProps} />
    </SceneErrorBoundary>
  );
}

// ---------------------------------------------------------------------------
// 데이터
// ---------------------------------------------------------------------------

interface FetchState {
  key: string;
  data: UnifiedOpportunityListResponse | null;
  error: string | null;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail
      ? describeFailure(error, "사업기회를 불러오지 못했습니다.")
      : describeFailure(error, "사업기회를 불러오지 못했습니다.");
  }
  return describeFailure(null, "사업기회를 불러오지 못했습니다.");
}

// ---------------------------------------------------------------------------
// 본체
// ---------------------------------------------------------------------------

/**
 * 「통합」에서는 **출처별 상위를 번갈아** 고른다 (0924 §4-B-3).
 *
 * 점수 순으로만 자르면 한쪽 출처가 열두 자리를 다 가져간다. 두 출처는 하는 일이 다르고
 * (하나는 수주, 하나는 신청) 점수도 자기 출처 안에서만 뜻이 있으므로, 한 화면에 놓을 때는
 * 자리를 번갈아 준다 — 나라장터 1위 · 기업마당 1위 · 나라장터 2위 · …
 *
 * 한쪽이 모자라면 남은 자리는 다른 쪽이 쓴다. **빈 자리를 만들지 않는다.**
 * 출처를 하나로 골라 본 화면에서는 번갈 것이 없으므로 순서 그대로다.
 */
function pickAlternating<T extends { source_type: string }>(
  items: T[],
  count: number,
  source: string,
): T[] {
  if (source !== "all") return items.slice(0, count);
  const g2b = items.filter((item) => item.source_type === "g2b");
  const bizinfo = items.filter((item) => item.source_type === "bizinfo");
  const out: T[] = [];
  for (let index = 0; out.length < count && index < Math.max(g2b.length, bizinfo.length); index += 1) {
    if (index < g2b.length && out.length < count) out.push(g2b[index]);
    if (index < bizinfo.length && out.length < count) out.push(bizinfo[index]);
  }
  return out;
}

export default function RadarShell() {
  const organizationId = useOrganizationId();
  const { list: organizations, error: organizationsError } = useOrganizations();
  const companyName = organizationName(organizations, organizationId);
  // 브라우저에 저장된 회사가 그 사이 삭제됐을 수 있다 — 조용히 넘어가지 않고 다시 고르게 한다.
  const organizationMissing =
    organizations !== null &&
    !organizations.organizations.some((entry) => entry.organization.organization_id === organizationId);

  /**
   * 주소의 조건. 서버 렌더에서는 알 수 없으므로 빈 문자열로 시작하고, hydration 뒤
   * 진짜 값으로 넘어간다 (목록 화면과 같은 방식이다).
   */
  const hydrated = useSyncExternalStore(subscribeNever, getHydrated, getHydratedServer);
  const urlSearch = useSyncExternalStore(subscribeNever, readSearchString, readSearchServer);
  const urlParams = useMemo(() => {
    const q = new URLSearchParams(urlSearch);
    const rawCount = Number(q.get(URL_KEYS.count));
    const rawView = q.get(URL_KEYS.view);
    const rawSource = q.get(URL_KEYS.source);
    const rawTrack = q.get(URL_KEYS.track);
    const rawSort = q.get(URL_KEYS.sort);
    return {
      // 모르는 값은 null 로 둔다 — 기본값이 이기게 하고, 주소를 믿고 빈 화면을 내지 않는다.
      source: SOURCE_FILTERS.some((f) => f.key === rawSource) ? (rawSource as SourceFilter) : null,
      track: TRACK_FILTERS.some((f) => f.key === rawTrack) ? (rawTrack as TrackFilter) : null,
      sort: SORT_KEYS.includes(rawSort as OpportunitySort) ? (rawSort as OpportunitySort) : null,
      closed: q.get(URL_KEYS.closed) === "1",
      // 값을 지어내지 않는다 — 아는 값이 아니면 undefined 로 두고 기본값이 이긴다.
      count: (VISIBLE_OPTIONS as readonly number[]).includes(rawCount) ? (rawCount as VisibleCount) : undefined,
      // 10-31 대표 결정 — 3D 는 화면에서 뺐다. 옛 주소 ?view=3d 도 2D(기본값)로
      view: rawView === "2d" ? (rawView as ViewMode) : undefined,
    };
  }, [urlSearch]);

  // 사람이 만지기 전에는 주소가 정한다. 만진 뒤에는 그 값이 이긴다.
  const [sourceOverride, setSource] = useState<SourceFilter | null>(null);
  const [trackOverride, setTrack] = useState<TrackFilter | null>(null);
  const [filtersOverride, setFilters] = useState<RadarFilterState | null>(null);
  const source = sourceOverride ?? urlParams.source ?? "all";
  // 기업마당에는 갈래 축이 없다(work_tracks 빈 배열) — 기업마당만 볼 때 갈래를 두면 어느 칩이든 0건이었다 (27차 RDR-31).
  const track: TrackFilter = source === "bizinfo" ? "all" : (trackOverride ?? urlParams.track ?? "all");
  const filters = useMemo<RadarFilterState>(
    () =>
      filtersOverride ?? {
        ...DEFAULT_FILTERS,
        sort: urlParams.sort ?? DEFAULT_FILTERS.sort, // null = 회사 설정
        includeClosed: urlParams.closed,
        visibleCount: urlParams.count ?? DEFAULT_FILTERS.visibleCount,
        viewMode: urlParams.view ?? DEFAULT_FILTERS.viewMode,
      },
    [filtersOverride, urlParams.sort, urlParams.closed, urlParams.count, urlParams.view],
  );
  // 「전체 목록」으로 건널 때 지금 조건을 싣는다 — 목록 → 레이더와 같은 도우미 (27차 LNK-09 · RDR-37).
  const listHref = hrefWithConditions("/opportunities", { src: source, track, sort: filters.sort, closed: filters.includeClosed });

  /**
   * 열려 있는 공고. 주소(`?notice=`·`?support=`)에서 받고, 고르면 거기에 남긴다.
   *
   * 「고른 것을 지우는 것」은 주소에 쓰지 않는다 — 레이더에서 상세를 닫은 것뿐인데 다른
   * 화면의 선택까지 없애면, 상단 메뉴로 RFP 분석에 갔을 때 합성 데모로 되돌아간다.
   */
  const incomingSelection = useSyncExternalStore(subscribeSelection, readSelection, readSelectionServer);
  const [pickedId, setPicked] = useState<string | null | undefined>(undefined);
  const selectedId = pickedId === undefined ? incomingSelection : pickedId;
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  /**
   * 「재수집」이 눌렸는지. **이번 요청에만** refresh=true 를 붙이고 곧바로 내린다 —
   * 상태로 두면 이후 필터 변경까지 매번 외부 API 를 다시 부르게 된다.
   * ref 라서 여기서 내려도 다시 렌더되지 않는다.
   */
  // 네 화면이 같은 조회 기간을 본다 (0920 §4-B-2-e).
  const days = usePeriodDays();
  const pendingRecollect = useRef(false);
  const [result, setResult] = useState<FetchState | null>(null);

  const [filterOpen, setFilterOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [sceneOpen, setSceneOpen] = useState(false);

  const layoutMode = useLayoutMode();
  const reducedMotion = useReducedMotion();
  const nowMs = useNowMs();
  const webglSupported = useWebGLSupport();

  const requestKey = `${organizationId}|${source}|${filters.sort}|${filters.includeClosed}|${days}|${reloadTick}`;
  // 로딩 여부는 상태가 아니라 "요청 키가 아직 도착하지 않았다"로 판단한다
  // (effect 안에서 setState 하지 않기 위해서다).
  const loading = result?.key !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const refresh = pendingRecollect.current;
    pendingRecollect.current = false;
    getBusinessOpportunities({
      organizationId,
      source,
      // 고르지 않았으면 보내지 않는다 — 서버가 회사 방식의 기본 정렬로 세운다(37차 §3-C-4 · 순번이 회사 방식 1위를 따른다).
      sort: filters.sort ?? undefined,
      limit: FETCH_LIMIT,
      // 나라장터 「관련 낮음」은 그리지 않는다 — 받을 때 빼야 200칸을 그릴 공고가 쓴다(38차 §5 검토 · 사전규격은 39차부터 목록에 없다)
      forRadar: true,
      includeClosed: filters.includeClosed,
      // 네 화면이 같은 조회 기간을 본다 (0920 §4-B-2-e).
      days,
      refresh,
    }).then(
      (value) => {
        if (!cancelled) setResult({ key: requestKey, data: value, error: null });
      },
      (error: unknown) => {
        if (!cancelled) setResult({ key: requestKey, data: null, error: errorMessage(error) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [requestKey, organizationId, source, filters.sort, filters.includeClosed, days]);

  /**
   * 조건을 주소에 적는다 — 새로고침·공유·뒤로가기에서 살아남게 (0920 §4-B-4 · ISSUE-077-d).
   *
   * `replace` 라서 필터를 만질 때마다 뒤로가기 기록이 쌓이지 않는다. 기본값은 적지 않는다.
   * **다른 키는 손대지 않는다** — `notice`·`support`(공고 선택)와 `days`(조회 기간)는
   * 각자 주인이 따로 있고, 여기서 새로 쓰면 그쪽이 방금 적은 값을 지운다.
   */
  useEffect(() => {
    // hydration 첫 렌더에서는 주소를 아직 읽지 못했다. 그때 쓰면 링크로 들어온 조건을
    // 우리가 지운다. 「주소 문자열이 같은가」로 재지 않는다 — 공고 선택(`lib/selection`)도
    // 같은 주소를 고치므로, 그 순간 둘이 어긋나 필터가 영영 안 적히게 된다.
    if (!hydrated) return;

    const next = new URLSearchParams(window.location.search);
    const put = (key: string, value: string | null) => {
      if (value === null) next.delete(key);
      else next.set(key, value);
    };
    put(URL_KEYS.source, source === "all" ? null : source);
    put(URL_KEYS.track, track === "all" ? null : track);
    put(URL_KEYS.sort, filters.sort);
    put(URL_KEYS.closed, filters.includeClosed ? "1" : null);
    put(URL_KEYS.count, filters.visibleCount === DEFAULT_FILTERS.visibleCount ? null : String(filters.visibleCount));
    put(URL_KEYS.view, filters.viewMode === DEFAULT_FILTERS.viewMode ? null : filters.viewMode);

    const search = next.toString();
    const url = search ? `${window.location.pathname}?${search}` : window.location.pathname;
    if (url !== window.location.pathname + window.location.search) {
      window.history.replaceState(window.history.state, "", url);
    }
  }, [hydrated, source, track, filters.sort, filters.includeClosed, filters.visibleCount, filters.viewMode]);

  const data = result?.data ?? null;
  const fetchError = result?.error ?? null;
  /** 회사 방식의 기본 정렬(37차 §3-C-4) — 응답이 알려 준다. 응답 전 · 옛 응답은 점수순. */
  const companySort: OpportunitySort = data?.ranking_method === "practical" ? "practical" : "priority";

  /*
   * 갈래로 거른 다음 자른다.
   *
   * 서버에 갈래 파라미터를 만들지 않은 이유 — 읽기 전용 스냅샷 배포본은 저장된 쿼리 키가
   * 안 맞으면 «필터가 안 먹은 목록»을 200 으로 돌려준다. 조용히 틀린 답을 주느니
   * 화면에서 거른다. 기업마당 항목은 이 축이 없으므로(work_tracks 가 빈 배열) 갈래를 고르면 빠진다.
   * 옛 배포 스냅샷에는 work_tracks 자체가 없다 — `?? []` 로 막는다.
   */
  const trackedItems = useMemo(() => {
    if (!data) return [];
    // 직접 넣은 공고(38차 §3-E)는 그리지 않는다 — 레이더 섹터는 나라장터 · 기업마당 둘이다(사전규격은 39차부터 목록에 없다).
    const notices = data.items.filter((item) => item.source_type !== "manual");
    const kept = track === "all" ? notices : notices.filter((item) => (item.work_tracks ?? []).includes(track));
    /*
     * 「참여 안 함」으로 정한 공고를 **뒤로 보낸다** (0920 §4-B-3 · ISSUE-076-d).
     *
     * 지우지는 않는다 — 결정을 되돌리는 일이 있고, 지우면 「그 공고는 어디 갔나」가 된다.
     * 안정 정렬이라 나머지 순서는 그대로다.
     */
    const declined = (item: (typeof kept)[number]) => (item.analysis_state?.decision === "NO_GO" ? 1 : 0);
    return [...kept].sort((a, b) => declined(a) - declined(b));
  }, [data, track]);

  const visibleItems = useMemo(
    () => pickAlternating(trackedItems, filters.visibleCount, source),
    [trackedItems, filters.visibleCount, source],
  );
  /** 갈래를 고르면서 빠진 기업마당 항목 수 — 조용히 사라지지 않게 화면에 적는다. */
  // 받아 온 200건 안에서 세면 「192건」처럼 실제(기업마당 전체)보다 작았다 — 기업마당은 모두 갈래가 없으니 출처 건수를 쓴다 (27차 §3-F 새로 찾음).
  const trackDropped = !data || track === "all" ? 0 : data.bizinfo_count;
  const layout = useMemo(() => buildRadarLayout(visibleItems, nowMs), [visibleItems, nowMs]);
  const selectedNode: RadarNode | null = layout.nodes.find((node) => node.id === selectedId) ?? null;
  // 다른 화면에서 고른 공고가 그림(상위 N건) 밖이면 조용히 풀린 화면이 됐다 — 한 줄로 알린다 (27차 RDR-30).
  // 합성 데모 공고는 레이더 · 목록에 원래 없다 — 알릴 것이 아니다.
  const selectionOutside = Boolean(selectedId) && !selectedNode && !selectedId?.startsWith("synthetic-");
  // (2.0.6) 그림에 없는 까닭을 가른다 — 받아 온 목록에 있으면 표시 개수 · 갈래 밖(「상위 n건」 문장이 맞다), 없으면 모른다:
  // 레이더는 불가 · 관련 낮음 · 직접 넣음 · (마감 포함을 끄면) 마감을 받지 않는다(서버 for_radar). 「상위 n건」이라 하면 순위 탓으로 읽혔다.
  const selectionHidden = selectionOutside && data !== null && !data.items.some((item) => item.id === selectedId);
  // (2.0.6) 출처 칩 밖이면 그것이 까닭이다(그 출처는 받지 않았다) — 기업마당 id 는 bizinfo- 로 시작한다(lib/selection).
  const selectionOtherSource = selectionHidden && source !== "all" && source !== (isSupportProgramId(selectedId) ? "bizinfo" : "g2b");
  // (2.0.6) 까닭을 하나로 단정하지 않는다 — 출처마다 상위 200건에서 잘렸으면(total_count 는 자르기 전 수) 순위 밖일 수도 있다.
  const selectionTruncated = data !== null && data.items.length < data.total_count;
  const hiddenWhy = `레이더는 ${selectionTruncated ? `출처마다 상위 ${FETCH_LIMIT}건만 받고, ` : ""}참가 불가 · 관련 낮음${
    filters.includeClosed ? "" : " · 마감된"
  } 공고와 직접 넣은 공고${selectionTruncated ? "는" : "를"} 그리지 않습니다`;
  const topNodes = layout.nodes.slice(0, 3);
  /**
   * 「n건은 전체 목록에서」의 분모 (0922 §4-D-2 · ISSUE-087).
   *
   * 예전에는 `trackedItems.length - visibleItems.length` 였다. `trackedItems` 는 API 를
   * `limit=200` 으로 부른 결과라, 실제로는 1,709건인데 화면이 「188건은 전체 목록에서」라고
   * 적었다 — 분모를 1,709 로 통일한 6차 작업이 이 문구만 놓쳤다.
   *
   * 건수의 단일 분모는 `summary`(백엔드가 한 벌만 센다)와 `track_counts` 다.
   */
  // 전체 갈래도 **불가를 거른 뒤**의 수 — 예전 `summary.open_total` 은 레이더 · 목록 기본 보기가 숨기는 불가(약 900건)를
  // 넣어, 갈래를 고르는 순간 N 이 크게 뛰었다(27차 RDR-09 · 계기 분모도 같은 수 · RDR-01).
  const trackedTotal =
    track === "all"
      ? data?.total_count ?? trackedItems.length
      : data?.track_counts?.[track] ?? trackedItems.length;
  const hiddenCount = Math.max(0, trackedTotal - visibleItems.length);
  const changedFilters = changedFilterCount(filters);
  const compact = layoutMode === "mobile";
  /*
   * 「우선 검토」 건수는 **전체 기준**이다 (0920 §4-B-2-d · ISSUE-075-d).
   *
   * 예전에는 레이더가 그린 12건 안에서 셌다. 그래서 같은 순간 목록은 「우선 검토 26」,
   * 레이더는 「우선 검토 3」이었다. backend 가 센 값 하나만 쓴다.
   */
  const priorityCount = data?.summary?.priority ?? 0;
  const tone = consoleTone(data, loading, fetchError);

  /** 나라장터·기업마당을 다시 부른다 (캐시를 건너뛴다). 화면만 다시 그리는 것이 아니다. */
  const handleRecollect = useCallback(() => {
    pendingRecollect.current = true;
    setReloadTick((tick) => tick + 1);
  }, []);

  /** 선택 — 좁은 화면에서는 상세를 시트로 띄운다. */
  const handleSelect = useCallback(
    (id: string | null) => {
      setPicked(id);
      // 고른 것만 남긴다. 해제는 남기지 않는다 (위 주석).
      if (id) writeSelection(id, "replace");
      if (id === null) {
        setDetailOpen(false);
        return;
      }
      if (getLayout() !== "desktop") setDetailOpen(true);
    },
    [],
  );

  const sceneProps: RadarSceneProps = {
    layout,
    selectedId,
    hoveredId,
    onSelect: handleSelect,
    onHover: setHoveredId,
    reducedMotion,
    companyName,
    compact,
  };

  /*
   * 모바일 전체화면은 대화상자다 — 열리면 포커스를 안(「← 목록으로」)으로, 닫히면 연 단추로 돌린다.
   * 공용 Modal 처럼 해야 키보드 사용자가 뒤 화면을 헤매지 않는다 (27차 RDR-38).
   */
  const sceneDialogRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!sceneOpen) return;
    const opener = document.activeElement as HTMLElement | null;
    sceneDialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
    return () => opener?.focus?.({ preventScroll: true });
  }, [sceneOpen]);
  // 2D 로 두었거나 3D 를 못 쓰면 「3D로 보기」가 2D 를 열었다 — 이름을 실제에 맞춘다 (27차 RDR-33).
  const sceneButtonLabel = "그림으로 보기"; // 10-31 — 3D 를 뺀 뒤로 늘 2D 평면도

  // 모바일 전체화면 3D — Escape 로 닫는다 (이벤트 콜백 안에서만 상태를 바꾼다).
  // 위에 시트가 떠 있으면 그 시트만 닫히게 두고, 전체화면은 그대로 둔다.
  useEffect(() => {
    if (!sceneOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // 전체화면 자신은 빼고, 그 위에 뜬 시트가 있으면 시트만 닫히게 둔다.
      if (document.querySelector('[role="dialog"][aria-modal="true"]:not([data-radar-fullscreen])')) return;
      setSceneOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [sceneOpen]);

  const stage = (
    <Stage
      source={source}
      track={track}
      loading={loading}
      fetchError={fetchError}
      companyName={companyName}
      viewMode={filters.viewMode}
      webglSupported={webglSupported}
      sceneProps={sceneProps}
    />
  );

  const sourceErrors = data
    ? (Object.entries(data.source_errors).filter(([, message]) => Boolean(message)) as Array<[string, string]>)
    : [];

  /*
   * 순위 목록 아래 두 안내 — 시트에만 있어 모바일 본문 목록에서는 보이지 않았다(27차 RDR-36). 한 벌을 두 곳이 쓴다.
   * 표시 개수가 이미 최대(20)면 「20으로 바꾸라」를 말하지 않는다 (RDR-40).
   */
  const canShowMore = filters.visibleCount < VISIBLE_OPTIONS[VISIBLE_OPTIONS.length - 1];
  const listNotes = (
    <>
      {trackDropped > 0 && (
        <p className="mt-3 text-[12px] leading-5 text-cosmos-muted">
          {/* 수는 계기 줄(「기업마당 n건은 갈래가 없어 빠짐」)에 한 번만 — 여기서는 이유와 되돌리기(§3-F RDR-01 검증) */}
          지원사업에는 「무슨 일을 시키는가」라는 일의 종류가 없어 목록에서 빠집니다.{" "}
          <button
            type="button"
            className="mc-focus rounded text-cosmos-cyan underline underline-offset-2"
            onClick={() => setTrack("all")}
          >
            전체 갈래로 되돌리기
          </button>
        </p>
      )}
      {hiddenCount > 0 && (
        <p className="mt-3 text-[12px] leading-5 text-cosmos-muted">
          조건에 맞는 {hiddenCount.toLocaleString("ko-KR")}건이 더 있습니다.{" "}
          {/* 표시 칸이 남았는데도 못 그린 것은 받아 온 상위 목록 밖이다 — 표시 개수를 늘려도 오르지 않는다(§3-F RDR-09 검증) */}
          {visibleItems.length < filters.visibleCount
            ? `받아 온 상위 ${FETCH_LIMIT}건 밖이라 그림에 오르지 않습니다 — `
            : canShowMore
              ? "「보기 설정」에서 표시 개수를 20으로 바꾸거나 "
              : ""}
          <Link href={listHref} className="mc-focus rounded text-cosmos-cyan underline underline-offset-2">
            전체 목록
          </Link>
          에서 보세요.
        </p>
      )}
    </>
  );

  const page = (
    <AppShell
      width="wide"
      headerAside={
        // 머리 오른쪽 맨 앞 — 모든 화면이 같은 회사 선택기 (27차 UNI-07). 바꾸면 고른 항목을 풀고 다시 계산한다.
        <OrganizationPicker id="radar-organization" list={organizations} organizationId={organizationId} onChanged={() => handleSelect(null)} />
      }
    >
      {/* ---- 헤더 + 컨트롤 ---- */}
      <div className="flex flex-col gap-3">
        {/* 좁은 화면에서는 제목만으로 충분하다 — 설명 한 줄을 접어 목록을 위로 끌어올린다. */}
        <SectionHeader
          as="h1"
          title={SCREEN_NAMES.radar}
          description={
            <span className="hidden sm:inline">나라장터와 기업마당에서 우리 회사가 먼저 볼 사업을 찾습니다.</span>
          }
          aside={
            <>
              {/* 자료가 실시간인지 캐시인지 한눈에 — 관제 화면의 첫 질문이다.
                  좁은 폭(640 미만)에서는 접는다 — 옆 「자료 상태」 단추가 같은 말을 하고, 셋을 한 줄에 두면 375 · 390 폭에서 문서가 392px 로 넘쳤다(40차 FRONT-01 검사). */}
              <div className="hidden sm:block">
                <SystemBadge tone={tone} fetchedAt={data?.fetched_at ?? null} reducedMotion={reducedMotion} collectState={data?.collect_state ?? null} />
              </div>
              <RadarDataStatus
                data={data}
                loading={loading}
                error={fetchError}
                onReload={handleRecollect}
              />
              <Link
                href={listHref}
                className="mc-focus inline-flex min-h-8 items-center gap-1.5 rounded-full border border-cosmos-border bg-cosmos-panel px-2.5 py-1 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
              >
                전체 목록
                <span aria-hidden="true">→</span>
              </Link>
            </>
          }
        />

        {/* 항상 보이는 컨트롤은 한 줄: 출처 · 필터 (회사는 머리 오른쪽 맨 앞 · 27차 UNI-07) */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div role="group" aria-label="출처" className="flex flex-wrap items-center gap-1.5">
            {SOURCE_FILTERS.map((filter) => (
              <Chip
                key={filter.key}
                active={source === filter.key}
                title={filter.hint}
                color={filter.color}
                onClick={() => {
                  handleSelect(null);
                  setSource(filter.key);
                }}
              >
                {filter.label}
              </Chip>
            ))}
          </div>

          {/*
            갈래 정보가 없는 응답(옛 읽기 전용 스냅샷 배포본)에서는 필터를 아예 그리지 않는다.
            누르면 언제나 0건인 필터를 보여 주는 것은 안 보여 주는 것보다 나쁘다 —
            담당자는 필터가 고장 났는지 정말 없는지 구분할 수 없다.
          */}
          {data?.track_counts !== undefined && source !== "bizinfo" && (
          <div role="group" aria-label="일의 종류 (나라장터 전용)" className="flex flex-wrap items-center gap-1.5">
            {TRACK_FILTERS.map((filter) => {
              const count = filter.key === "all" ? null : data?.track_counts?.[filter.key];
              // 「갈래 미분류」는 그런 공고가 있을 때만 — 늘 0건인 칩은 고장으로 읽힌다(RDR-25).
              if (filter.key === "unclassified" && !count && track !== "unclassified") return null;
              return (
                <Chip
                  key={filter.key}
                  active={track === filter.key}
                  title={filter.hint}
                  color={filter.color}
                  onClick={() => {
                    handleSelect(null);
                    setTrack(filter.key);
                  }}
                >
                  {filter.label}
                  {count !== null && count !== undefined && (
                    <span className="ml-1 font-mono text-[12px] tabular-nums opacity-80">{count}</span>
                  )}
                </Chip>
              );
            })}
          </div>
          )}

          <Button
            size="sm"
            variant="secondary"
            onClick={() => setFilterOpen(true)}
            aria-label={changedFilters > 0 ? `보기 설정 — 기본값과 다른 설정 ${changedFilters}개` : undefined}
          >
            {/* 보이는 이름 = 접근성 이름 = 시트 제목(「보기 설정」) — 「필터」로 보이고 「보기 설정」으로 읽혔다 (27차 RDR-32) */}
            보기 설정
            {changedFilters > 0 && (
              <span
                aria-hidden="true"
                className="ml-0.5 inline-flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-cosmos-cyan px-1 font-mono text-[12px] font-bold leading-none text-cosmos-bg"
              >
                {changedFilters}
              </span>
            )}
          </Button>

          <p className="min-w-[200px] flex-1 text-[12px] leading-4 text-cosmos-muted">
            {/* 목록 점수는 승인된 수행근거를 쓰지 않는다(나라장터는 공고 분석 전 미산정 · 기업마당은 프로필 낱말) (27차 RDR-07). */}
            우리 회사의 사업 분야·지역·참가 조건으로 순서를 매깁니다. 회사 근거(실적 자료)는 공고를 분석한 뒤에 반영됩니다.
          </p>
        </div>

        {/* ---- 상태 안내 (정상일 때는 아무것도 나오지 않는다) ---- */}
        {organizationsError && <InlineAlert tone="warn">{organizationsError} 기본 회사로 계산합니다.</InlineAlert>}
        {organizationMissing && (
          <InlineAlert tone="warn">
            이 브라우저에 저장된 회사 <code className="font-mono">{organizationId}</code> 가 더 이상 등록되어 있지
            않습니다. 위 회사 선택에서 다른 회사를 고르면 순위를 다시 계산합니다.
          </InlineAlert>
        )}
        {fetchError && (
          <InlineAlert tone="fail">
            {fetchError} 「자료 상태」에서 다시 불러오거나, 전체 목록 화면에서 상태를 확인하세요.
          </InlineAlert>
        )}
        {sourceErrors.length > 0 && (
          <InlineAlert tone="warn">
            한쪽 출처를 불러오지 못했습니다 — 나머지 출처만으로 화면을 계속 씁니다.{" "}
            {sourceErrors.map(([key, message]) => `${key === "g2b" ? "나라장터" : "기업마당"}: ${message}`).join(" · ")}
          </InlineAlert>
        )}
        {data && data.source_status.bizinfo === "sample" && (
          <InlineAlert tone="demo" role="status">
            기업마당 항목이 가상 예시 공고입니다 — 실제 공고가 아닙니다.
          </InlineAlert>
        )}
        {!loading && !fetchError && selectionOutside && layout.nodes.length > 0 && (
          <InlineAlert tone="info" role="status">
            {selectionOtherSource ? (
              // (2.0.6) 「전체 목록」은 지금 출처 칩을 싣고 열려 그 공고가 거기서도 안 보인다 — 출처를 넓히는 단추를 준다.
              <>
                다른 화면에서 고른 공고는 지금 보는 출처({SOURCE_FILTERS.find((f) => f.key === source)?.label})에 없습니다 —{" "}
                <button type="button" className="mc-focus rounded underline underline-offset-2" onClick={() => setSource("all")}>
                  출처 「모두」로 보기
                </button>
              </>
            ) : (
              <>
                {selectionHidden
                  ? `다른 화면에서 고른 공고가 이 레이더에 없습니다. ${hiddenWhy} — `
                  : `다른 화면에서 고른 공고는 지금 그림(상위 ${layout.nodes.length}건)에 없습니다 — `}
                {/* (2.0.6) 불가 · 관련 낮음 · 마감 포함은 이 링크에만 싣는다 — 머리 · 도구줄 「전체 목록」은 레이더 조건 그대로 */}
                <Link href={selectionHidden ? withHiddenIncluded(listHref) : listHref} className="mc-focus rounded underline underline-offset-2">
                  전체 목록
                </Link>
                {selectionHidden ? "(불가 · 관련 낮음 · 마감 포함)에서 보세요." : "에서 보세요."}
              </>
            )}
          </InlineAlert>
        )}
        {data && !data.field_mapping_verified && (
          <InlineAlert tone="warn">
            기업마당 자료의 항목을 아직 다 맞춰 보지 못했습니다. 금액·기간 같은 중요한 값은 공고 원문에서 한 번 더
            확인하세요.
          </InlineAlert>
        )}

        {/* ---- telemetry — 무엇을 보고 있나 ---- */}
        {!fetchError && (
          <div className="border-t border-cosmos-border pt-3">
            <TelemetryBar
              layout={layout}
              hiddenCount={hiddenCount}
              loading={loading}
              data={data}
              trackTotal={track === "all" ? null : trackedTotal}
            />
          </div>
        )}
      </div>

      {/* ---- 본문 ---- */}
      {compact ? (
        /* 모바일: 순위 목록이 기본. 3D는 눌러서 전체화면으로 본다 (자동 로드하지 않는다). */
        <div className="flex flex-col gap-3">
          {/* 목록 아래에만 두면 12건을 지나쳐야 보인다 — 첫 화면에서 바로 고를 수 있게 위에도 둔다. */}
          <Button
            variant="secondary"
            onClick={() => setSceneOpen(true)}
            disabled={layout.nodes.length === 0}
            className="w-full"
          >
            {sceneButtonLabel}
          </Button>
          <Panel ariaLabel="사업기회 순위" className="flex min-w-0 flex-col gap-2">
            {loading ? (
              <LoadingState label="사업기회를 불러오는 중" rows={4} />
            ) : fetchError ? (
              <EmptyState title="목록을 불러오지 못했습니다" tone="fail">
                {fetchError}
              </EmptyState>
            ) : layout.nodes.length === 0 ? (
              <EmptyState title="표시할 사업기회가 없습니다" tone="muted">
                현재 회사({companyName})와 지금 조건에 맞는 항목이 없습니다. {emptyHint(source, track)}
              </EmptyState>
            ) : (
              <>
                <RadarRankList
                  nodes={layout.nodes}
                  selectedId={selectedId}
                  onSelect={handleSelect}
                  onHover={setHoveredId}
                />
                {listNotes}
              </>
            )}
          </Panel>
          <Button
            variant="secondary"
            onClick={() => setSceneOpen(true)}
            disabled={layout.nodes.length === 0}
            className="w-full"
          >
            {sceneButtonLabel}
          </Button>
        </div>
      ) : (
        /* 데스크톱: 스코프가 화면의 중심(약 70%), 오른쪽은 추적 목록(약 30%). */
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,352px)] xl:grid-cols-[minmax(0,1fr)_minmax(0,396px)]">
          {/* ---- RADAR CONTROL ---- */}
          <section
            aria-label="사업기회 레이더"
            className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-cosmos-border bg-cosmos-panel"
          >
            <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-cosmos-border px-3.5 py-2">
              <div className="flex items-center gap-3">
                <h2 className="text-[12px] font-semibold leading-none tracking-[0.12em] text-cosmos-muted">레이더 지도</h2>
                {/* 3D/2D 전환 단추는 10-31 대표 결정(3D 를 화면에서 뺌)으로 없앴다 — 레이더는 2D 평면도만 */}
              </div>
              <ScopeScaleNote layout={layout} />
            </header>

            <div className="relative min-h-0 flex-1">
              {/* 스코프 — 카드 대부분을 차지한다 */}
              {/* isolate — 3D 이름표 · 관제탑(drei Html, z 14~31)이 스크롤 때 상단 바(z-30) 위로 올라오지 않게 이 상자 안에 가둔다.
                  계기 두 상자는 z-40 으로 그 위에 둔다 — 이름표가 자료 상태 상자를 덮었다 (27차 RDR-35). */}
              <div className="relative isolate h-[52vh] min-h-[340px] lg:h-[clamp(420px,60vh,700px)]">
                {stage}
                <ScopeCorners />

                {/* 좌측 rail — 무엇이 주의를 요구하나 */}
                {!loading && !fetchError && layout.nodes.length > 0 && (
                  <div className="pointer-events-none absolute left-3.5 top-3.5 z-40 hidden xl:block">
                    <StatRail layout={layout} priorityCount={priorityCount} />
                  </div>
                )}

                {/* 우측 HUD — 자료가 언제 것인가 */}
                <div className="absolute right-3.5 top-3.5 z-40 hidden w-[142px] md:block">
                  <TrackingHud data={data} tone={tone} reducedMotion={reducedMotion} />
                </div>
              </div>
            </div>

            <StatusStrip
              tone={tone}
              data={data}
              layout={layout}
              reducedMotion={reducedMotion}
              onRecollect={handleRecollect}
              loading={loading}
            />
          </section>

          {/* ---- TRACKED OPPORTUNITIES ---- */}
          <div className="hidden min-w-0 lg:flex lg:max-h-[calc(100vh-13rem)] lg:flex-col">
            <RadarTrackedPanel
              node={selectedNode}
              topNodes={loading || fetchError ? [] : topNodes}
              selectedId={selectedId}
              fetchedAt={data?.fetched_at ?? null}
              companyName={companyName}
              totalTracked={layout.nodes.length}
              onSelect={handleSelect}
              onHover={setHoveredId}
              onOpenList={layout.nodes.length > 0 ? () => setListOpen(true) : undefined}
              loading={loading}
              error={fetchError}
              interleaved={source === "all"}
            />
          </div>
        </div>
      )}

      {/* ---- 범례 한 줄 + 보조 이동 ---- */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <RadarLegend />
        {/* ml-auto — 줄이 바뀌어도 오른쪽 끝에 붙는다. 왼쪽으로 내려가면 오른쪽 맞춤 340px 「읽는 법」 창이 화면 왼쪽 밖으로 잘렸다 (27차 RDR-08). */}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* 모바일은 본문이 곧 순위 목록이다 — 같은 목록을 시트로 한 번 더 열던 단추는 넓은 화면에만 (27차 RDR-36). */}
          {layout.nodes.length > 0 && !compact && (
            <button
              type="button"
              onClick={() => setListOpen(true)}
              className="mc-focus inline-flex min-h-8 items-center gap-1.5 rounded-full border border-cosmos-border bg-cosmos-panel px-2.5 py-1 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
            >
              순위 목록
            </button>
          )}
          <Link
            href={listHref}
            className="mc-focus inline-flex min-h-8 items-center gap-1.5 rounded-full border border-cosmos-border bg-cosmos-panel px-2.5 py-1 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
          >
            전체 목록
            <span aria-hidden="true">→</span>
          </Link>
          {/*
            「읽는 법」은 줄 맨 끝 — 오른쪽 맞춤 340px 창이 트리거 오른쪽 끝에서 왼쪽으로 열리므로, 트리거가 오른쪽 끝이어야
            390 폭에서 창 왼쪽이 화면 밖으로 나가지 않는다 (27차 RDR-08).
            공용 Popover 는 트리거 **아래**로 열린다. 이 줄은 화면 맨 아래라 아래로 열면 잘리므로,
            공용 컴포넌트를 고치지 않고 이 자리에서만 위로 열리게 위치를 뒤집는다.
          */}
          <div className="[&_[role=dialog]]:bottom-[calc(100%+6px)] [&_[role=dialog]]:top-auto">
            <Popover
              align="end"
              width="340px"
              title="이 그림 읽는 법"
              triggerLabel="이 그림 읽는 법 — 거리·크기·링·축 밖의 뜻"
              trigger={
                <>
                  <span aria-hidden="true">?</span>
                  읽는 법
                </>
              }
            >
              <RadarReadingGuide />
            </Popover>
          </div>
        </div>
      </div>

      {/* ---- 모바일 전체화면 3D ---- */}
      {compact && sceneOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="사업기회 레이더 전체화면"
          data-radar-fullscreen=""
          ref={sceneDialogRef}
          className="fixed inset-0 z-40 flex flex-col"
          style={{ backgroundColor: COSMOS_COLORS.bg }}
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-cosmos-border px-3 py-2">
            <Button size="sm" variant="ghost" onClick={() => setSceneOpen(false)}>
              <span aria-hidden="true">←</span> 목록으로
            </Button>
            <span className="text-[12px] font-semibold text-cosmos-text">{SCREEN_NAMES.radar}</span>
            <Button size="sm" variant="secondary" onClick={() => setFilterOpen(true)}>
              보기 설정
            </Button>
          </div>
          <div className="relative min-h-0 flex-1">{stage}</div>
          <div className="shrink-0 border-t border-cosmos-border px-3 py-2">
            <RadarLegend />
            <p className="mt-1 text-[12px] leading-4 text-cosmos-muted">노드를 누르면 상세가 열립니다.</p>
          </div>
        </div>
      )}

      {/* ---- 시트: 보기 설정 · 순위 목록 · 선택 상세 ---- */}
      <RadarFilterSheet
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        state={filters}
        onChange={setFilters}
        webglBlocked={webglSupported === false}
        companySort={companySort}
      />

      <Sheet
        open={listOpen}
        onClose={() => setListOpen(false)}
        title="순위 목록"
        description={
          // 통합 보기는 정렬 순서가 아니라 출처별 상위를 번갈아 고른 순서다 (27차 RDR-39).
          source === "all"
            ? `나라장터 · 기업마당 상위를 번갈아 고른 ${layout.nodes.length}건입니다(순위는 같은 출처 안). 그림의 노드와 같은 항목입니다.`
            : `현재 정렬 기준 상위 ${layout.nodes.length}건입니다. 그림의 노드와 같은 항목입니다.`
        }
        width="420px"
      >
        <RadarRankList
          nodes={layout.nodes}
          selectedId={selectedId}
          onSelect={handleSelect}
          onHover={setHoveredId}
          onPick={() => setListOpen(false)}
        />
        {listNotes}
      </Sheet>

      <Sheet
        open={detailOpen && !!selectedNode && layoutMode !== "desktop"}
        onClose={() => setDetailOpen(false)}
        title="선택한 사업기회"
        width="440px"
      >
        <RadarDetail
          bare
          node={selectedNode}
          fetchedAt={data?.fetched_at ?? null}
          companyName={companyName}
        />
      </Sheet>
    </AppShell>
  );
  // (2.0.6) 회사 순서 방식을 상세 · 추적 카드 · 계기 · 꼬리표에 내린다 — 사업기회와 같은 Context(실무순이면 분류 칸이 「우선 검토」를 대신한다).
  // 응답 전 · 옛 응답은 점수순(사업기회와 같은 기본값).
  return <RankingMethodContext.Provider value={data?.ranking_method ?? "score"}>{page}</RankingMethodContext.Provider>;
}
