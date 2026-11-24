"use client";

/**
 * Evidence Cosmos — 2D 지도 (SVG). **3D 와 같은 길의 평면판**이다 (21차 · prompt_11 §3-8).
 *
 *   공고 → 적합도 → 참가 여부 → 요구사항 → 근거 → 제안서 → 점검 → 결정
 *
 * **지금 정거장만** 기호와 이름표를 그린다 — 나머지 일곱은 이름 알약(번호 · 이름 · 개수 · 상태 기호 · 레일과 같은 낱말)
 * 이고 누르면 그 정거장으로 간다. 선은 고른 항목에서 관련 정거장마다 하나(최대 3). 정거장 이름 · 폭(아코디언) ·
 * 표시(◆ ▲ ─ ◉) · ③ 문 · 선 · 알약 낱말은 모두 `lib/cosmos/stations.ts` 한 곳에서 온다 — 2D 와 3D 가 다른 말을 할 수
 * 없다 (27차 §3-D).
 *
 * SVG 좌표 1 단위 = 화면 1px 이 되도록 viewBox 를 **그리는 칸 크기**로 잡는다 — 라벨 13px · 정거장 이름 18px 가
 * 그 크기 그대로 그려진다(예전에는 1040×760 좌표를 늘여 11.5 단위가 8.5px 로 그려졌다). Ctrl+휠 확대 · 끌어 옮기기는 그대로.
 * 좁은 화면(767px 이하)은 정거장을 위에서 아래로 쌓는다. 외부 라이브러리 없음 · 렌더 중 window/document 를 만지지 않는다.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { eligibilityGateView } from "@/lib/cosmos/eligibilityGate";
import { findingTypeLabel, isSevere, type CosmosGraph, type CosmosNode, type WorkflowStage } from "@/lib/cosmos/graph";
import { SEVERITY_LABELS, formatBudgetCompact, seriousText } from "@/lib/cosmos/format";
import { lineColorHex, nodeColorHex, verdictPill } from "@/lib/cosmos/itemTypes";
import {
  STATION_IDS,
  STATION_NAMES,
  currentStationOrder,
  selectionLines,
  stationFlag,
  stationItemCounts,
  stationMarkers,
  stationSpans,
  stationTier,
  type MarkerShape,
  type StationMarker,
  type StationTier,
} from "@/lib/cosmos/stations";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import type { CosmosNodeState } from "@/lib/cosmos/theme";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { formatDeadlineStamp } from "@/lib/deadline";

import type { CosmosViewProps } from "./types";

// ---------------------------------------------------------------------------
// 상수
// ---------------------------------------------------------------------------

interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

const MIN_ZOOM = 0.7;
const MAX_ZOOM = 2.4;
const DRAG_THRESHOLD_PX = 4;
const FADE_MS = 320;
/** 그리기 전(서버 렌더 · 첫 그림) 칸 크기 — 1440 에서 지도 칸과 같다. */
const FALLBACK_SIZE = { w: 948, h: 560 } as const;

/**
 * 정거장 머리(번호 원 · 이름 · 요약 · 낱말 알약) 높이와 길 선 높이 (px). 알약(y 82~102)이 첫 줄 이름표(위 끝 ≈ 이 값 + 5)와
 * 겹치지 않는 높이 — 96 이면 1440 ③ ⑥ ⑦ 에서 알약과 첫 이름표가 몇 px 겹쳤다(27차 check_map).
 */
const HEAD_H = 106;
/** 세로 쌓기에서 지금 정거장 요약이 쓰는 둘째 줄 높이 (px). */
const VERTICAL_CAPTION_LINE = 20;
const PATH_Y = 20;
/** 지금 정거장: 줄 간격 · 한 열 최대 줄 · 기호 왼쪽 여백 */
const CURRENT_PITCH = 30;
const CURRENT_ROWS = 12;
const DIM_OPACITY = 0.3;
/** 칸 폭이 이보다 좁으면 낱말 알약 대신 기호 하나(낱말은 title · aria). 3D 와 같은 값. */
const FLAG_WORD_MIN_PX = 70;

const SCOPE = "c2d";
const SCOPED_CSS = `
.${SCOPE}-svg { touch-action: none; user-select: none; -webkit-user-select: none; display: block; }
.${SCOPE}-node { cursor: pointer; outline: none; }
.${SCOPE}-focus { opacity: 0; transition: opacity 120ms ease-out; }
.${SCOPE}-node:focus-visible .${SCOPE}-focus { opacity: 1; }
.${SCOPE}-label { paint-order: stroke; stroke: ${COSMOS_COLORS.bg}; stroke-width: 3px; stroke-linejoin: round; pointer-events: none; }
/* 항목 이름표는 눌러서 고른다(27차 검수 R27D-OWN-02) — 기호만 받으면 「선은 항목을 누르면 보입니다」가 거짓이 된다. */
.${SCOPE}-label.${SCOPE}-pick { pointer-events: auto; cursor: pointer; }
.${SCOPE}-station { cursor: pointer; }
.${SCOPE}-station:hover .${SCOPE}-station-bg { fill-opacity: 0.6; }
@keyframes ${SCOPE}-blink { 0%, 100% { stroke-opacity: 0.95; } 50% { stroke-opacity: 0.45; } }
.${SCOPE}-blink { animation: ${SCOPE}-blink 1.6s ease-in-out infinite; }
`;

// ---------------------------------------------------------------------------
// 순수 헬퍼
// ---------------------------------------------------------------------------

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function truncate(text: string, max: number): string {
  const chars = Array.from(text);
  return chars.length > max ? `${chars.slice(0, max - 1).join("")}…` : text;
}

function charsFor(widthPx: number): number {
  return Math.max(3, Math.floor(widthPx / 13));
}

/** 13px 글자 폭 어림 — 한글 13 · 숫자·영문 7.6 · 공백 3.6 · 가운뎃점 4.4 (Noto Sans KR). */
function textWidth13(text: string): number {
  let w = 0;
  for (const ch of text) w += /[\uAC00-\uD7A3]/.test(ch) ? 13 : ch === " " ? 3.6 : ch === "·" ? 4.4 : 7.6;
  return w;
}

/** 폭(px)에 들어가게 자른다 — 글자 수로 자르면 공백·숫자가 많은 「조항 확인 전 2 · 공고 필드 확인 2」가 남는 폭에서도 잘렸다. */
function fitText(text: string, widthPx: number): string {
  if (textWidth13(text) <= widthPx) return text;
  const chars = Array.from(text);
  while (chars.length > 1 && textWidth13(`${chars.join("")}…`) > widthPx) chars.pop();
  return `${chars.join("")}…`;
}

// ---------------------------------------------------------------------------
// 배치 — 3D 와 같은 정거장 · 같은 순서 · 같은 폭
// ---------------------------------------------------------------------------

interface StationBox {
  id: WorkflowStage;
  tier: StationTier;
  x: number;
  y: number;
  w: number;
  h: number;
  cx: number;
  /** 정거장 안 항목 수(이름 아래 「n건」) */
  count: number;
  /** 고른 항목의 선이 닿는 자리 — 이름 알약 */
  pill: { x: number; y: number };
}

interface Placed {
  x: number;
  y: number;
  /** 긴 라벨이 쓸 수 있는 폭 (px) */
  labelW: number;
}

interface FlowLayout {
  vertical: boolean;
  width: number;
  height: number;
  stations: StationBox[];
  /** 지금 정거장에서 그리는 항목만 자리가 있다(27차 §3-D-1) */
  pos: Map<string, Placed>;
  /** 지금 정거장 항목 수(상한 전) · 「외 n건 · 전체 보기」 칩 */
  currentItems: number;
  more: { x: number; y: number; count: number } | null;
  /** 가로 배치: 고른 항목의 선이 달리는 첫 길(y) — 지금 정거장 마지막 줄 아래(27차 검수 R27D-OWN-03 · 02) */
  laneY: number;
}

type Item = { id: string; state: CosmosNodeState; hub?: boolean; expanded?: boolean };

function itemsByStation(graph: CosmosGraph, markers: StationMarker[]): Map<WorkflowStage, Item[]> {
  const map = new Map<WorkflowStage, Item[]>(STATION_IDS.map((id) => [id, []]));
  for (const node of graph.nodes) {
    map.get(node.stage)?.push({ id: node.id, state: node.state, hub: node.kind === "proposal" || node.kind === "audit", expanded: node.expanded });
  }
  for (const marker of markers) map.get(marker.station)?.push({ id: marker.id, state: marker.state });
  return map;
}

/** 지금 정거장만 — 판정이 나쁜 순 · 24 넘으면 23 + 「외 n건」 칩(3D 와 같은 `currentStationOrder`). */
function placeCurrent(
  items: Item[],
  selectedId: string | null,
  box: { x: number; y: number; w: number },
  pos: Map<string, Placed>,
  currentColumns: 1 | 2,
): { used: number; more: FlowLayout["more"] } {
  const { shown, hidden } = currentStationOrder(items, selectedId);
  const slots = shown.length + (hidden > 0 ? 1 : 0);
  if (slots === 0) return { used: 0, more: null };
  const cols = Math.min(currentColumns, slots > CURRENT_ROWS ? 2 : 1);
  const rows = Math.ceil(slots / cols);
  const colW = box.w / cols;
  const at = (i: number) => ({ x: box.x + 14 + Math.floor(i / rows) * colW, y: box.y + 14 + (i % rows) * CURRENT_PITCH });
  shown.forEach((item, i) => pos.set(item.id, { ...at(i), labelW: colW - 34 }));
  return { used: rows * CURRENT_PITCH, more: hidden > 0 ? { ...at(shown.length), count: hidden } : null };
}

/**
 * 가로 배치에서 정거장 칸이 이보다 좁으면 이름(18px 네 글자 「참가자격」 ≈ 72px)이 옆 칸 이름과 겹친다 —
 * 그때는 위에서 아래로 쌓는다 (22차 §4-C · 1024 창 + 레일 펼침에서 캔버스 358px).
 */
const NAME_COLUMN_MIN = 76;

/** 정거장 칸 가운데 가장 좁은 칸의 몫(0~1). */
function narrowestShare(spans: { x0: number; x1: number }[]): number {
  return Math.min(...spans.map((s) => s.x1 - s.x0));
}
/** 지금 정거장이 한 열일 때 가장 좁은 칸의 몫 — 어느 단계든 가장 작은 값(단계와 무관한 가로/세로 기준). */
const ONE_COLUMN_MIN_SHARE = Math.min(...STATION_IDS.map((id) => narrowestShare(stationSpans(id, 1))));

export function buildLayout(
  graph: CosmosGraph,
  markers: StationMarker[],
  stage: WorkflowStage,
  size: { w: number; h: number },
  vertical: boolean,
  selectedId: string | null = null,
): FlowLayout {
  const byStation = itemsByStation(graph, markers);
  // 이름 아래 「n개」는 점 수가 아니라 항목 수 — 3D 와 같은 계산 (허브는 빼고 묶음은 건수로).
  const itemCounts = stationItemCounts(graph, markers);
  const pos = new Map<string, Placed>();
  const stations: StationBox[] = [];

  const rowPad = 16;
  const usable = Math.max(320, size.w - rowPad * 2);
  const currentItems = byStation.get(stage)?.length ?? 0;
  const currentCount = Math.min(currentItems, 24);
  // 가장 좁은 정거장 칸에 이름이 안 들어가면 가로로 두지 않는다 — 창이 아니라 **칸** 기준 (22차 §4-C).
  // 가로/세로는 **단계와 상관없는** 몫(한 열 기준 가장 좁은 칸)으로 정한다 — 단계를 누를 때마다 뒤집히지 않게(22차 검토).
  // 지금 정거장을 두 열로 펼치면 다른 칸이 좁아진다 — 그래도 이름이 들어갈 때만 두 열.
  const twoColumns = currentCount > CURRENT_ROWS && narrowestShare(stationSpans(stage, 2)) * usable >= NAME_COLUMN_MIN;
  const spans = stationSpans(stage, twoColumns ? 2 : 1);
  let more: FlowLayout["more"] = null;
  if (!vertical && ONE_COLUMN_MIN_SHARE * usable >= NAME_COLUMN_MIN) {
    let bottom = HEAD_H;
    for (const id of STATION_IDS) {
      const tier = stationTier(id, stage);
      const x = rowPad + spans[id - 1].x0 * usable;
      const w = (spans[id - 1].x1 - spans[id - 1].x0) * usable;
      if (tier === "current") {
        const placed = placeCurrent(byStation.get(id) ?? [], selectedId, { x, y: HEAD_H, w }, pos, twoColumns ? 2 : 1);
        more = placed.more;
        bottom = Math.max(bottom, HEAD_H + placed.used + 24);
      }
      const cx = x + w / 2;
      // 선 끝 = 알약 아래(y 82~102) — 선이 아래(빈 칸)에서 올라와 닿는다.
      stations.push({ id, tier, x, y: 0, w, h: 0, cx, count: itemCounts[id - 1], pill: { x: cx, y: PATH_Y + 86 } });
    }
    // 칸 높이(`size.h`)는 지도 구역이 정한다(감싸개가 absolute inset-0) — 내용이 더 길면 지도 안에서 굴린다.
    const height = Math.max(size.h, bottom);
    for (const s of stations) s.h = height;
    return { vertical: false, width: size.w, height, stations, pos, currentItems, more, laneY: bottom - 22 };
  }

  // 좁은 화면: 위에서 아래로 쌓는다. 머리는 한 줄(번호 · 이름 · 요약), 점은 그 아래.
  const width = Math.max(320, size.w);
  const pad = 12;
  let y = 8;
  // 지금 정거장만 펼친 아코디언 — 나머지 정거장은 머리 한 줄(번호 · 이름 · 개수 · 상태 기호 · 알약).
  for (const id of STATION_IDS) {
    const tier = stationTier(id, stage);
    let used = 0;
    // 지금 정거장은 요약(「조항 확인 전 2 · 공고 필드 확인 2」)을 이름 아래 둘째 줄에 — 레일 이름(「참가 가능 여부」)이
    // 길어져 이름 옆에 두면 358px 칸에서 요약이 잘렸다(27차 check_visibility).
    const capLine = tier === "current" ? VERTICAL_CAPTION_LINE : 0;
    if (tier === "current") {
      const placed = placeCurrent(byStation.get(id) ?? [], selectedId, { x: pad + 20, y: y + 30 + capLine, w: width - pad * 2 - 20 }, pos, 1);
      used = placed.used;
      more = placed.more;
    }
    const h = 36 + capLine + used + (used > 0 ? 8 : 0);
    stations.push({ id, tier, x: pad, y, w: width - pad * 2, h, cx: pad + 12, count: itemCounts[id - 1], pill: { x: pad + 12, y: y + 18 } });
    y += h + 6;
  }
  // 세로 쌓기는 내용 높이 그대로 — 재어 온 높이를 되먹이면 한 번 커진 지도가 다시 줄지 않는다 (21차).
  return { vertical: true, width, height: y, stations, pos, currentItems, more, laneY: 0 };
}

// ---------------------------------------------------------------------------
// 칸 크기 · 방향
// ---------------------------------------------------------------------------

const PORTRAIT_QUERY = "(max-width: 767px)";
function subscribePortrait(onChange: () => void): () => void {
  const media = window.matchMedia(PORTRAIT_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const getPortrait = () => window.matchMedia(PORTRAIT_QUERY).matches;
const getPortraitServer = () => false;

/** 그리는 칸의 크기 — ResizeObserver 콜백에서만 바꾼다(효과 안에서 setState 하지 않는다). */
function useBoxSize(ref: React.RefObject<HTMLDivElement | null>): { w: number; h: number } {
  const [size, setSize] = useState<{ w: number; h: number }>(FALLBACK_SIZE);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      const rect = entry?.contentRect;
      // 폭은 **스크롤바를 포함한** 테두리 상자로 잰다 — 내용 상자로 재면 가로 배치가 넘쳐 스크롤바가 생길 때 폭이
      // 15px 줄어 세로로 바뀌고, 세로에서는 스크롤바가 없어 다시 가로로 — 프레임마다 뒤집혔다 (22차 검토).
      const width = entry?.borderBoxSize?.[0]?.inlineSize ?? rect?.width ?? 0;
      if (rect && width > 0 && rect.height > 0) {
        setSize((prev) => (Math.abs(prev.w - width) < 1 && Math.abs(prev.h - rect.height) < 1 ? prev : { w: width, h: rect.height }));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

// ---------------------------------------------------------------------------
// 메인 컴포넌트
// ---------------------------------------------------------------------------

interface ViewState {
  /** 이 상태가 만들어졌을 때의 resetSignal · 정거장. props 와 다르면 기본 시점으로 본다. */
  key: string;
  box: ViewBox;
}

interface DragState {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startBox: ViewBox;
  scale: number;
  moved: boolean;
}

export default function Cosmos2D({
  graph,
  stage,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
  highlightNodeIds,
  highlightLinkIds,
  resetSignal,
  reducedMotion,
  paused,
  onStation,
  onShowAll,
  lineAnchorId = null,
}: CosmosViewProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const size = useBoxSize(wrapRef);
  const vertical = useSyncExternalStore(subscribePortrait, getPortrait, getPortraitServer);
  const markers = useMemo(() => stationMarkers(graph), [graph]);
  const layout = useMemo(
    () => buildLayout(graph, markers, stage, size, vertical, lineAnchorId ?? selectedId),
    [graph, markers, stage, size, vertical, lineAnchorId, selectedId],
  );
  // 좁은 칸 때문의 세로 쌓기는 지도 구역 안에서 굴린다 — 지금 정거장이 보이게 그 자리로 옮긴다(단계·발표 장면) (22차 검토).
  const currentTop = layout.vertical && !vertical ? (layout.stations.find((s) => s.id === stage)?.y ?? null) : null;
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || currentTop === null) return;
    el.scrollTo({ top: Math.max(0, currentTop - 8), behavior: reducedMotion ? "auto" : "smooth" });
  }, [currentTop, reducedMotion]);
  const gate = useMemo(
    () => eligibilityGateView(graph.eligibility, graph.source.analysis.eligibility?.verdict ?? null),
    [graph],
  );
  const defaultBox = useMemo<ViewBox>(() => ({ x: 0, y: 0, w: layout.width, h: layout.height }), [layout.width, layout.height]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const suppressClickRef = useRef(false);
  // 정거장이 바뀌거나 「화면 초기화」를 누르거나 칸 크기가 바뀌면 기본 시점 — setState 없이 파생 값으로.
  // 칸 크기를 빼면 첫 렌더의 임시 크기(948×560) 시점이 실제 크기를 잰 뒤에도 남는다 (21차).
  const viewKey = `${resetSignal}:${stage}:${layout.width}x${layout.height}`;
  const [view, setView] = useState<ViewState>({ key: viewKey, box: defaultBox });
  const [dragging, setDragging] = useState(false);
  const box = view.key === viewKey && view.box.w <= layout.width * 1.5 ? view.box : defaultBox;
  const aspect = defaultBox.h / defaultBox.w;

  const clampBox = useCallback(
    (next: ViewBox): ViewBox => {
      const w = clamp(next.w, defaultBox.w / MAX_ZOOM, defaultBox.w / MIN_ZOOM);
      const h = w * aspect;
      const cx = clamp(next.x + next.w / 2, 0, defaultBox.w);
      const cy = clamp(next.y + next.h / 2, 0, defaultBox.h);
      return { x: cx - w / 2, y: cy - h / 2, w, h };
    },
    [aspect, defaultBox.h, defaultBox.w],
  );

  // -- 휠 확대/축소: React onWheel 은 passive 라 preventDefault 가 안 되므로 직접 등록한다.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      // 휠만 굴리면 페이지가 내려간다 — 확대는 Ctrl(⌘)+휠 · 터치패드 모으기(ctrlKey 로 온다) (DSH-18).
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const factor = Math.exp(event.deltaY * 0.0015);
      setView((prev) => {
        const current = prev.key === viewKey ? prev.box : defaultBox;
        const scale = Math.min(rect.width / current.w, rect.height / current.h);
        const ox = (rect.width - current.w * scale) / 2;
        const oy = (rect.height - current.h * scale) / 2;
        const ux = current.x + (event.clientX - rect.left - ox) / scale;
        const uy = current.y + (event.clientY - rect.top - oy) / scale;
        const w = clamp(current.w * factor, defaultBox.w / MAX_ZOOM, defaultBox.w / MIN_ZOOM);
        const k = w / current.w;
        return { key: viewKey, box: clampBox({ x: ux - (ux - current.x) * k, y: uy - (uy - current.y) * k, w, h: w * aspect }) };
      });
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [aspect, clampBox, defaultBox, viewKey]);

  // -- 끌어 옮기기 (빈 배경에서 시작한 경우만; 노드는 pointerdown 전파를 막는다)
  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      if (event.button !== 0) return;
      const svg = event.currentTarget;
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      dragRef.current = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startBox: box,
        scale: Math.min(rect.width / box.w, rect.height / box.h),
        moved: false,
      };
      svg.setPointerCapture(event.pointerId);
    },
    [box],
  );
  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const dx = event.clientX - drag.startClientX;
      const dy = event.clientY - drag.startClientY;
      if (!drag.moved) {
        if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
        drag.moved = true;
        setDragging(true);
      }
      setView({
        key: viewKey,
        box: clampBox({ x: drag.startBox.x - dx / drag.scale, y: drag.startBox.y - dy / drag.scale, w: drag.startBox.w, h: drag.startBox.h }),
      });
    },
    [clampBox, viewKey],
  );
  const endDrag = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const svg = event.currentTarget;
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    if (drag.moved) suppressClickRef.current = true;
    dragRef.current = null;
    setDragging(false);
  }, []);
  const handleBackgroundClick = useCallback(() => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onSelect(null);
  }, [onSelect]);
  const toggleSelect = useCallback((id: string) => onSelect(id === selectedId ? null : id), [onSelect, selectedId]);

  const fade = reducedMotion ? "none" : `opacity ${FADE_MS}ms ease-out`;
  const highlightActive = highlightNodeIds.size > 0 || highlightLinkIds.size > 0;
  const locked = gate?.verdict === "FAIL";
  // 고른 항목(없으면 안내가 가리키는 지금 정거장 항목)에서 관련 정거장마다 선 하나 — 3D 와 같은 함수(27차 §3-D-3).
  const lines = useMemo(() => selectionLines(graph, stage, lineAnchorId), [graph, stage, lineAnchorId]);
  const from = lineAnchorId ? layout.pos.get(lineAnchorId) : undefined;
  const drawnLines = from ? lines : [];
  // 가까운 정거장이 위(항목 쪽) 길을 쓴다 — 세로줄과 가로 길이 엇갈리지 않는다.
  const laneOrder = from
    ? drawnLines.map((line) => line.station).sort((a, b) => Math.abs(layout.stations[a - 1].cx - from.x) - Math.abs(layout.stations[b - 1].cx - from.x))
    : [];
  const drawnNodes = graph.nodes.filter((node) => layout.pos.has(node.id));
  const drawnMarkers = markers.filter((marker) => layout.pos.has(marker.id));
  const shapes = [...new Set([...drawnNodes.map((node) => glyphOf(node)), ...drawnMarkers.map((marker) => marker.shape)])].sort().join(",");
  /** 검사가 읽는 값 — 3D 와 같은 이름(27차 §3-D-11). 2D 는 `cosmosNodes`(3D 라벨 수 기다림)를 쓰지 않는다. */
  useEffect(() => {
    const data = document.documentElement.dataset;
    data.cosmosStation = String(stage);
    data.cosmosStationNodes = String(layout.pos.size);
    data.cosmosDrawnMarks = String(drawnNodes.length + drawnMarkers.length);
    data.cosmosLinks = String(drawnLines.length);
    data.cosmosShapes = shapes;
    data.cosmosStationItems = String(layout.stations[stage - 1]?.count ?? 0);
    return () => {
      delete data.cosmosStation;
      delete data.cosmosStationNodes;
      delete data.cosmosDrawnMarks;
      delete data.cosmosLinks;
      delete data.cosmosShapes;
      delete data.cosmosStationItems;
    };
  }, [stage, layout, drawnNodes.length, drawnMarkers.length, drawnLines.length, shapes]);

  return (
    <div
      ref={wrapRef}
      // 가로 배치: 지도 구역 크기를 그대로 잰다(내용이 구역을 키우지 않게 absolute) · 세로 쌓기: 내용 높이만큼 흐른다.
      // 휴대폰(세로 창)만 내용 높이만큼 흐른다. 좁은 칸 때문에 세로로 쌓을 때는 지도 구역 안에서 굴린다 — 구역이
      // 길어지면 발표 자막(구역 바닥에 붙는다)이 화면 밖으로 밀렸다 (22차 검토).
      className={vertical ? "relative w-full" : "absolute inset-0 overflow-y-auto overflow-x-hidden"}
      role="group"
      aria-label="Evidence Cosmos 2D 정거장 지도"
    >
      <style>{SCOPED_CSS}</style>
      <svg
        ref={svgRef}
        className={`${SCOPE}-svg w-full`}
        style={{ height: layout.height, cursor: dragging ? "grabbing" : "grab" }}
        viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
        preserveAspectRatio="xMidYMin meet"
        role="group"
        aria-label={STATION_IDS.map((id) => STATION_NAMES[id]).join(" → ")}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onClick={handleBackgroundClick}
      >
        {/* 길 — 정거장 가운데를 잇는다. ③ 이 불가면 ③→④ 가 끊긴다 */}
        <PathLine layout={layout} locked={locked} />

        {/* 고른 항목의 선 — 관련 정거장 알약까지 · 최대 3 · 청록 실선 · 호박 점선 · 빨강(밝기 깜빡임) (27차 §3-D-3) */}
        <g aria-hidden="true">
          {from &&
            drawnLines.map((line) => {
              const to = layout.stations[line.station - 1].pill;
              const i = laneOrder.indexOf(line.station);
              // 세로 쌓기: 항목 기호 열을 따라 내려가면 기호와 겹친다 — 왼쪽 여백(원 바깥)을 따라 꺾어 정거장 원에 닿는다. 선마다 다른 골.
              // 가로: 기호 왼쪽 골 → 마지막 줄 아래 길(선마다 다른 높이) → 상대 정거장 세로줄(빈 칸) → 알약 아래 (27차 검수 R27D-OWN-03 · 02).
              const gx = from.x - 12 - i * 3;
              const lane = layout.laneY + i * 6;
              const points = layout.vertical
                ? `${from.x - 10},${from.y} ${4 + i * 4},${from.y} ${4 + i * 4},${to.y} ${to.x - 12},${to.y}`
                : `${from.x},${from.y} ${gx},${from.y} ${gx},${lane} ${to.x},${lane} ${to.x},${to.y}`;
              return (
                <polyline
                  key={line.station}
                  data-cosmos-line={line.state}
                  points={points}
                  fill="none"
                  stroke={lineColorHex(line.state)}
                  strokeWidth={2}
                  strokeOpacity={0.95}
                  strokeDasharray={line.state === "candidate" ? "5 4" : undefined}
                  className={line.state === "warning" && !reducedMotion && !paused ? `${SCOPE}-blink` : undefined}
                />
              );
            })}
        </g>

        {/* 정거장 머리 — 지금이 아닌 정거장은 이름 알약(누르면 그 정거장으로) */}
        {layout.stations.map((station) => (
          <StationHead
            key={station.id}
            station={station}
            vertical={layout.vertical}
            step={graph.steps[station.id - 1]}
            locked={station.id === 3 && locked}
            flag={stationFlag(graph.steps[station.id - 1], gate)}
            onStation={onStation}
          />
        ))}

        {/* 노드 */}
        {graph.nodes.map((node) => {
          const p = layout.pos.get(node.id);
          if (!p) return null;
          const inHighlight = highlightNodeIds.has(node.id);
          return (
            <FlowNode
              key={node.id}
              node={node}
              graph={graph}
              place={p}
              stage={stage}
              dimmed={highlightActive && !inHighlight}
              selected={node.id === selectedId}
              hovered={node.id === hoveredId}
              transition={fade}
              onToggleSelect={toggleSelect}
              onHover={onHover}
            />
          );
        })}

        {/* 그래프에 노드가 없는 정거장의 표시 — 고를 수 없다(레일 · 상세 패널이 내용을 보여 준다) */}
        {markers.map((marker) => {
          const p = layout.pos.get(marker.id);
          if (!p) return null;
          return <MarkerMark key={marker.id} marker={marker} place={p} stage={stage} transition={fade} />;
        })}

        {layout.more && <MoreChip x={layout.more.x} y={layout.more.y} count={layout.more.count} onShowAll={onShowAll} />}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 길 · 정거장 머리
// ---------------------------------------------------------------------------

function PathLine({ layout, locked }: { layout: FlowLayout; locked: boolean }) {
  const segments: ReactNode[] = [];
  for (let i = 0; i < layout.stations.length - 1; i += 1) {
    const a = layout.stations[i];
    const b = layout.stations[i + 1];
    const ax = layout.vertical ? a.cx : a.cx;
    const ay = layout.vertical ? a.y + 18 : PATH_Y;
    const bx = layout.vertical ? b.cx : b.cx;
    const by = layout.vertical ? b.y + 18 : PATH_Y;
    if (locked && a.id === 3) {
      // 끊긴 길 — 양쪽 토막만 붉은 점선, 가운데는 비운다.
      const t = 0.32;
      segments.push(
        <line key={`${i}a`} x1={ax} y1={ay} x2={ax + (bx - ax) * t} y2={ay + (by - ay) * t} stroke={COSMOS_COLORS.red} strokeWidth={2} strokeDasharray="5 4" />,
        <line key={`${i}b`} x1={bx - (bx - ax) * t} y1={by - (by - ay) * t} x2={bx} y2={by} stroke={COSMOS_COLORS.red} strokeWidth={2} strokeDasharray="5 4" />,
      );
    } else {
      segments.push(<line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke={COSMOS_COLORS.slate} strokeOpacity={0.5} strokeWidth={1.5} />);
    }
  }
  return <g aria-hidden="true">{segments}</g>;
}

function StationHead({
  station,
  vertical,
  step,
  locked,
  flag,
  onStation,
}: {
  station: StationBox;
  vertical: boolean;
  step: CosmosGraph["steps"][number] | undefined;
  locked: boolean;
  flag: { word: string; glyph: string; color: string } | null;
  onStation?: (stage: WorkflowStage) => void;
}) {
  const current = station.tier === "current";
  const label = step?.label ?? STATION_NAMES[station.id];
  const meta = step ? STEP_STATUS_META[step.status] : null;
  const ring = locked ? COSMOS_COLORS.red : current ? COSMOS_COLORS.cyan : COSMOS_COLORS.borderStrong;
  const nameColor = locked ? COSMOS_COLORS.redText : current ? COSMOS_COLORS.textPrimary : COSMOS_COLORS.textSecondary;
  // 지금 정거장은 레일 이름 그대로 · 나머지는 그 이름 안의 낱말(27차 §3-D-9).
  const name = current ? label : STATION_NAMES[station.id];
  const count = station.count > 0 ? `${station.count}건` : "";
  const caption = locked ? "참가 불가 · 잠김" : current ? (step?.summary ?? "") : count;
  const glyph = !locked && meta ? `${meta.glyph} ` : "";
  const cx = station.cx;
  const cy = vertical ? station.y + 18 : PATH_Y;
  // 세로: 이름 오른쪽(이름 폭만큼 · 적어도 x+110)부터 칸 끝까지 — 지금 정거장은 이름 아래 둘째 줄 전체 · 가로: 칸 폭.
  const capBelow = vertical && current;
  const capX = capBelow ? cx + 22 : vertical ? Math.max(cx + 110, cx + 22 + (textWidth13(name) * 18) / 13 + 12) : cx;
  const flagW = flag ? (station.w < FLAG_WORD_MIN_PX ? 28 : Math.max(44, textWidth13(flag.word) + 20)) : 0;
  const capWidth = capBelow
    ? station.x + station.w - capX - 8
    : vertical
      ? station.x + station.w - capX - 8 - (flag ? flagW + 8 : 0)
      : Math.max(station.w, 60) - 6;
  const flagText = flag ? (station.w < FLAG_WORD_MIN_PX ? flag.glyph : flag.word) : "";
  const flagFill = flag?.glyph === STEP_STATUS_META.failed.glyph ? COSMOS_COLORS.redText : COSMOS_COLORS.amber;
  const clickable = !current && onStation !== undefined;
  const flagAt = vertical ? { x: station.x + station.w - 8 - flagW, y: cy - 10 } : { x: cx - flagW / 2, y: cy + 62 };
  return (
    <g
      data-cosmos-station-name={station.id}
      data-cosmos-station-tier={station.tier}
      aria-label={`${station.id}단계 ${label}${locked ? " — 참가 불가" : ""}${flag ? ` — ${flag.word}` : ""}`}
      className={clickable ? `${SCOPE}-station` : undefined}
      // 끌어 옮기기 · 배경 클릭(선택 해제)으로 번지지 않게 — 키보드는 레일이 맡는다.
      onPointerDown={clickable ? (event) => event.stopPropagation() : undefined}
      onClick={
        clickable
          ? (event) => {
              event.stopPropagation();
              onStation?.(station.id);
            }
          : undefined
      }
    >
      {clickable && (
        <rect
          className={`${SCOPE}-station-bg`}
          x={station.x + 2}
          y={vertical ? station.y : 2}
          width={station.w - 4}
          height={vertical ? 36 : HEAD_H - 8}
          rx={10}
          fill={COSMOS_COLORS.bgElevated}
          fillOpacity={0}
        >
          <title>{`${label} — 눌러서 이 정거장 보기`}</title>
        </rect>
      )}
      {current && !vertical && (
        <rect x={station.x + 2} y={4} width={station.w - 4} height={station.h - 8} rx={12} fill={COSMOS_COLORS.bgElevated} fillOpacity={0.35} stroke={COSMOS_COLORS.cyan} strokeOpacity={0.25} />
      )}
      <circle cx={cx} cy={cy} r={12} fill={COSMOS_COLORS.bg} stroke={ring} strokeWidth={1.5} />
      <text x={cx} y={cy + 4.5} textAnchor="middle" fontSize={13} fontWeight={600} fill={ring === COSMOS_COLORS.borderStrong ? COSMOS_COLORS.textSecondary : ring} className={`${SCOPE}-label`}>
        {station.id}
      </text>
      {vertical ? (
        <>
          <text x={cx + 22} y={cy + 6} fontSize={18} fontWeight={600} fill={nameColor} className={`${SCOPE}-label`}>
            {name}
          </text>
          <text data-cosmos-station-caption x={capX} y={capBelow ? cy + 5 + VERTICAL_CAPTION_LINE : cy + 5} fontSize={13} fill={locked ? COSMOS_COLORS.redText : COSMOS_COLORS.textSecondary} className={`${SCOPE}-label`}>
            {glyph && <tspan fill={meta?.color}>{glyph}</tspan>}
            {fitText(caption, capWidth - textWidth13(glyph))}
          </text>
        </>
      ) : (
        <>
          {/* 좁은 칸에서 이름이 칸보다 길면(「참가 여부」 ≈ 77px) 글자 폭만 살짝 좁혀 칸 안에 — 옆 이름과 붙지 않게(27차).
              두 줄로 접으면 캡션 · 알약과 겹친다. 글자 크기(18px)는 그대로다. */}
          <text
            x={cx}
            y={cy + 38}
            textAnchor="middle"
            fontSize={18}
            fontWeight={600}
            fill={nameColor}
            className={`${SCOPE}-label`}
            // 이웃 이름과 적어도 14px 띄운다 — 6px 이면 「참가 여부 요구사항」처럼 한 이름으로 읽혔다(27차 검수 R27D-OWN-10).
            {...(!current && (textWidth13(name) * 18) / 13 > station.w - 14 ? { textLength: station.w - 14, lengthAdjust: "spacingAndGlyphs" } : {})}
          >
            {name}
          </text>
          <text data-cosmos-station-caption x={cx} y={cy + 56} textAnchor="middle" fontSize={13} fill={locked ? COSMOS_COLORS.redText : COSMOS_COLORS.textSecondary} className={`${SCOPE}-label`}>
            {glyph && <tspan fill={meta?.color}>{glyph}</tspan>}
            {fitText(caption, capWidth - textWidth13(glyph))}
          </text>
        </>
      )}
      {/* 레일이 「!」 「✕」인 단계에만 같은 낱말 알약 — 여덟 정거장 모두(27차 §3-D-2). 좁으면 기호 하나 · 낱말은 title */}
      {flag && (
        <g data-station-flag={flag.word} aria-label={flag.word}>
          <title>{flag.word}</title>
          <rect x={flagAt.x} y={flagAt.y} width={flagW} height={20} rx={10} fill={COSMOS_COLORS.bg} stroke={flagFill} strokeOpacity={0.7} />
          <text x={flagAt.x + flagW / 2} y={flagAt.y + 14} textAnchor="middle" fontSize={13} fontWeight={600} fill={flagFill} className={`${SCOPE}-label`}>
            {flagText}
          </text>
        </g>
      )}
    </g>
  );
}

/** 지금 정거장이 24 를 넘을 때 — 「외 n건 · 전체 보기」(누르면 목록 보기). */
function MoreChip({ x, y, count, onShowAll }: { x: number; y: number; count: number; onShowAll?: () => void }) {
  const text = `외 ${count}건 · 전체 보기`;
  const w = textWidth13(text) + 16;
  return (
    <g
      data-cosmos-more={count}
      className={onShowAll ? `${SCOPE}-station` : undefined}
      transform={`translate(${x - 6} ${y - 10})`}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onShowAll?.();
      }}
    >
      <rect width={w} height={20} rx={6} fill={COSMOS_COLORS.bgElevated} stroke={COSMOS_COLORS.borderStrong} />
      <text x={8} y={14} fontSize={13} fill={COSMOS_COLORS.textSecondary} className={`${SCOPE}-label`}>
        {text}
      </text>
    </g>
  );
}

// ---------------------------------------------------------------------------
// 기호 — 종류당 하나 (3D 와 같은 표)
// ---------------------------------------------------------------------------

type Glyph = "circle" | "square" | "square-lg" | "card" | "bar" | "warn" | "warn-lg" | MarkerShape;

function glyphOf(node: CosmosNode): Glyph {
  switch (node.kind) {
    case "notice":
      return "circle";
    case "requirement":
      return "square";
    case "requirement-group":
      return "square-lg";
    case "evidence":
      return "card";
    case "proposal":
      return "bar";
    case "audit":
    case "finding-group":
      return "warn-lg";
    case "finding":
      return "warn";
  }
}

function GlyphShape({ glyph, color, scale }: { glyph: Glyph; color: string; scale: number }) {
  const s = scale;
  switch (glyph) {
    case "circle":
      return <circle r={7 * s} fill={color} />;
    case "square":
      return <rect x={-4.5 * s} y={-4.5 * s} width={9 * s} height={9 * s} fill={color} />;
    case "square-lg":
      return <rect x={-7 * s} y={-7 * s} width={14 * s} height={14 * s} fill={color} />;
    case "card":
      return <rect x={-4 * s} y={-5.5 * s} width={8 * s} height={11 * s} fill="none" stroke={color} strokeWidth={1.8} />;
    case "bar":
      return <rect x={-8 * s} y={-1.5 * s} width={16 * s} height={3 * s} fill={color} />;
    case "warn":
      return <polygon points={`0,${-6 * s} ${5.5 * s},${4 * s} ${-5.5 * s},${4 * s}`} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" />;
    case "warn-lg":
      return <polygon points={`0,${-8.5 * s} ${7.5 * s},${5.5 * s} ${-7.5 * s},${5.5 * s}`} fill="none" stroke={color} strokeWidth={2.2} strokeLinejoin="round" />;
    case "diamond":
      return <polygon points={`0,${-6 * s} ${6 * s},0 0,${6 * s} ${-6 * s},0`} fill={color} />;
    case "triangle":
      return <polygon points={`0,${-6 * s} ${6 * s},${4.5 * s} ${-6 * s},${4.5 * s}`} fill={color} />;
    case "target":
      return (
        <>
          <circle r={7 * s} fill="none" stroke={color} strokeWidth={2} />
          <circle r={3 * s} fill={color} />
        </>
      );
  }
}

/** 지금 정거장 기호 크기 (다른 정거장은 그리지 않는다). */
const MARK_SCALE = 1.25;

function longText(node: CosmosNode, graph: CosmosGraph): { title: string; sub: string | null } {
  switch (node.kind) {
    case "notice": {
      const n = graph.source.notice;
      return { title: n.title, sub: `${n.agency} · 마감 ${formatDeadlineStamp(n.deadline_at)} · ${formatBudgetCompact(n.budget)}` };
    }
    case "requirement":
      // 코드(SCH- · REQ- …)는 지도에서 빼고 상세 · 목록에만 둔다(27차 §3-D-6). 판정은 끝 낱말 알약이 말한다.
      return { title: node.short, sub: null };
    case "requirement-group":
    case "finding-group":
      return { title: node.label, sub: null };
    case "evidence":
      return { title: node.short, sub: null };
    case "proposal":
      return { title: "제안서 초안", sub: `요구사항 ${graph.coverage.covered}/${graph.coverage.total} 반영 · ${graph.counts.sentences}문장` };
    case "audit":
      return { title: "제출 전 누락 점검", sub: `찾은 문제 ${graph.counts.findings}건 · ${seriousText(graph.counts.findingsHigh, graph.counts.findingsBlocking, "건")}` };
    case "finding": {
      const finding = graph.findingByNodeId.get(node.id);
      const severity = node.state === "resolved" ? "해결됨" : node.severity && isSevere({ severity: node.severity }) ? SEVERITY_LABELS[node.severity] : null;
      return { title: findingTypeLabel(finding?.finding_type ?? "missing_requirement"), sub: severity };
    }
  }
}

/** 이름표 끝 판정 낱말 — 호박 · 빨강만. 제목을 그만큼 줄인다(3D 와 같은 `verdictPill`). */
function TitleWithVerdict({ title, chars, state, stage, id }: { title: string; chars: number; state: CosmosNodeState; stage: WorkflowStage; id: string }) {
  const pill = verdictPill(state);
  // 이름 전체 + 낱말이 칸에 안 들어가면 낱말 대신 기호(「!」 · 「✕」) — 낱말이 이름을 네 글자로 잘라 먹었다(27차 검수 R27D-OWN-01).
  const word = pill ? Array.from(pill.word).length + 1 : 0;
  const fits = !pill || Array.from(title).length <= chars - word;
  const room = pill ? (fits ? chars - word : Math.max(3, chars - 2)) : chars;
  const glyph = state === "warning" ? STEP_STATUS_META.failed.glyph : STEP_STATUS_META.attention.glyph;
  return (
    <>
      <tspan data-cosmos-label="long" data-cosmos-label-id={id} data-cosmos-station={stage}>{truncate(title, room)}</tspan>
      {pill && (
        <tspan
          data-cosmos-verdict={pill.word}
          data-cosmos-verdict-mode={fits ? "word" : "glyph"}
          // 알약 때문에 이름을 줄였는가(검사가 읽는다) — longText 가 처음부터 줄인 긴 문장은 알약 탓이 아니다.
          data-cosmos-verdict-cut={Array.from(title).length > room ? "1" : "0"}
          fill={pill.color}
          fontWeight={700}
        >
          {` ${fits ? pill.word : glyph}`}
        </tspan>
      )}
    </>
  );
}

function FlowNode({
  node,
  graph,
  place,
  stage,
  dimmed,
  selected,
  hovered,
  transition,
  onToggleSelect,
  onHover,
}: {
  node: CosmosNode;
  graph: CosmosGraph;
  place: Placed;
  stage: WorkflowStage;
  dimmed: boolean;
  selected: boolean;
  hovered: boolean;
  transition: string;
  onToggleSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const color = nodeColorHex(node);
  const opacity = dimmed ? DIM_OPACITY : 1;
  const handleKeyDown = (event: ReactKeyboardEvent<SVGGElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      onToggleSelect(node.id);
    }
  };
  const text = longText(node, graph);
  const chars = charsFor(place.labelW);
  // 높음 이상 발견은 빨강 심각도 알약(부제)이 같은 색 낱말이다 — 판정 알약은 호박(확인 필요)일 때만.
  const verdictState: CosmosNodeState = node.kind === "finding" && node.state !== "check" ? "ok" : node.state;
  return (
    <g
      className={`${SCOPE}-node`}
      transform={`translate(${place.x} ${place.y})`}
      role="button"
      tabIndex={0}
      aria-label={`${node.label}${verdictPill(verdictState) ? ` — ${verdictPill(verdictState)?.word}` : ""}${selected ? " (선택됨)" : ""}`}
      aria-pressed={selected}
      style={{ opacity, transition }}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        onToggleSelect(node.id);
      }}
      onKeyDown={handleKeyDown}
      onPointerEnter={() => onHover(node.id)}
      onPointerLeave={() => onHover(null)}
      onFocus={() => onHover(node.id)}
      onBlur={() => onHover(null)}
    >
      {(selected || hovered) && <circle r={13} fill="none" stroke={COSMOS_COLORS.textPrimary} strokeOpacity={selected ? 0.9 : 0.4} strokeWidth={1.5} />}
      <circle className={`${SCOPE}-focus`} r={16} fill="none" stroke={COSMOS_COLORS.cyan} strokeWidth={2} strokeDasharray="4 3" />
      <GlyphShape glyph={glyphOf(node)} color={color} scale={MARK_SCALE} />
      <text x={16} y={text.sub ? -1 : 4.5} fontSize={13} fontWeight={600} fill={COSMOS_COLORS.textPrimary} className={`${SCOPE}-label ${SCOPE}-pick`}>
        <TitleWithVerdict title={text.title} chars={chars} state={verdictState} stage={stage} id={node.id} />
      </text>
      {text.sub && (
        <text x={16} y={13} fontSize={13} fill={COSMOS_COLORS.textSecondary} className={`${SCOPE}-label ${SCOPE}-pick`}>
          {truncate(text.sub, chars)}
        </text>
      )}
    </g>
  );
}

function MarkerMark({ marker, place, stage, transition }: { marker: StationMarker; place: Placed; stage: WorkflowStage; transition: string }) {
  const color = nodeColorHex(marker);
  const chars = charsFor(place.labelW);
  return (
    <g transform={`translate(${place.x} ${place.y})`} style={{ transition }}>
      <GlyphShape glyph={marker.shape} color={color} scale={MARK_SCALE} />
      <text x={16} y={4.5} fontSize={13} fontWeight={600} fill={COSMOS_COLORS.textPrimary} className={`${SCOPE}-label`}>
        <TitleWithVerdict title={marker.label} chars={chars} state={marker.state} stage={stage} id={marker.id} />
      </text>
    </g>
  );
}
