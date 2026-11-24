/**
 * 정거장 배치 (21차 · prompt_11 §4-A · 27차 §3-D-1) — 단계 → 정거장 x 구간, **지금 정거장** 항목 → 열.
 *
 * 길은 월드 x 축을 따라 왼쪽(1)에서 오른쪽(8)으로 놓인다. 모두 z = 0 평면이고 이름은 위(y > 0), 노드는
 * 그 아래로 줄을 선다. 지금 정거장이 넓고(아코디언) 나머지는 좁다 — `stationSpans`.
 *
 * 지금이 아닌 정거장의 항목은 **그리지 않는다**(27차 §3-D-1). 이름 밑 한 점(알약 자리)에 모아 두기만 한다 —
 * 고른 항목에서 나가는 선이 그 정거장 알약에 닿게 하려는 자리다.
 *
 * 그래프 자체(노드 id · 링크 · 단계)는 바꾸지 않는다. 위치만 바꾼 **사본**을 돌려준다.
 * ponytail: 재배치는 순간 이동 — 부드럽게 하려면 노드·링크 위치를 damp 하라(카메라만 tween 한다).
 */

import type { CosmosGraph, CosmosNode, WorkflowStage } from "@/lib/cosmos/graph";
import { CURRENT_MARK_MAX, currentStationOrder, STATION_IDS, STATION_NAMES, stationSpans, type StationMarker } from "@/lib/cosmos/stations";
import type { CosmosNodeState } from "@/lib/cosmos/theme";

import type { Vec3 } from "./constants";

/** 길 전체 폭 (월드 단위). */
export const PATH_WIDTH = 40;
/**
 * 길 선과 정거장 번호 원의 높이 — 노드 줄(y ≤ 0) 위. 이름 · 요약 · 상태 알약이 원 **아래로**
 * CSS 로 흘러 내려온다(최대 약 88px). 1440 에서 1 단위가 약 19px 이므로 4.6 단위(약 88px)면 첫 노드 줄과 겹치지 않는다.
 */
export const STATION_PATH_Y = 4.6;
/**
 * 지금이 아닌 정거장의 알약 자리(월드 y) — 머리 블록(원 · 이름 · 캡션 · 알약) 아래쪽. 고른 항목의 선이 여기서 끝난다.
 * ponytail: 1440 캡처로 맞춘 값 — 선 끝이 알약 근처에 닿게 하는 것뿐이라 정확할 필요는 없다.
 */
export const STATION_ANCHOR_Y = 0.8;
/** 원 위 여백(카메라가 원을 자르지 않게). */
const PATH_HEADROOM = 0.9;
/** 선 길: 마지막 줄에서 첫 길까지 · 길 사이 · 바닥 여백(월드 · 세로 배율을 곱한다) */
const LANE_FIRST = 0.55;
const LANE_STEP = 0.28;
const LANE_ROOM = 1.3;

/** 지금 정거장: 한 열 최대 줄 수 · 줄 간격 · 왼쪽 여백. 라벨은 노드 오른쪽에 붙는다. */
export const CURRENT_ROWS = 12;
const CURRENT_PITCH = 1.5;
const CURRENT_INSET = 0.7;
/** 공고 카드가 첫 줄 아래로 차지하는 깊이 (월드 단위, 1440 에서 약 19px/단위 × 13 ≈ 250px). */
const NOTICE_CARD_DEPTH = 13;

export interface StationFrame {
  /** 정거장 가운데 x (월드) */
  centers: number[];
  /** 정거장 구간 [x0, x1] (월드) */
  spans: Array<{ x0: number; x1: number }>;
  /** 카메라가 담아야 할 위·아래 (이름 포함) */
  top: number;
  bottom: number;
  /** 정거장마다 몇 줄로 섰는가 — 지금 정거장 라벨 폭을 정한다 */
  columns: number[];
  /** 세로 배율 — 좁은 캔버스면 1 보다 커진다(`fitStationLayout`). 줄 간격 · 머리 깊이 · 공고 카드 깊이에 곱한다 */
  vscale: number;
  /** 지금 정거장이 그리는 상한 (기본 24 · 좁으면 줄어든다) */
  marks: number;
  /** 지금이 아닌 정거장 알약 자리(월드 y) — 고른 항목의 선이 여기서 끝난다 */
  anchorY: number;
  /** 좁은 캔버스 맞춤이면 참 — 지금 정거장 이름을 칸 폭 안에서 두 줄로 접는다(`stations.tsx`) */
  narrow: boolean;
  /** 고른 항목의 선이 달리는 첫 길(월드 y) — 지금 정거장 마지막 줄 아래. 선마다 `laneStep` 씩 더 아래로(27차 검수 R27D-OWN-03 · 02) */
  laneY: number;
  laneStep: number;
}

export interface StationLayout {
  graph: CosmosGraph;
  markerPos: Map<string, Vec3>;
  frame: StationFrame;
  /** 그리는 id — 지금 정거장에서 상한(24) 안에 든 것만 (27차 §3-D-1 · 6) */
  shownIds: Set<string>;
  /** 「외 n건 · 전체 보기」 칩 자리 — 지금 정거장이 24 를 넘을 때만 */
  more: { at: Vec3; count: number } | null;
}

/** 좁은 캔버스 맞춤 — 기본값이면 21차 배치 그대로 (`fitStationLayout`) */
export interface LayoutFit {
  vscale: number;
  marks: number;
  /** 지금 정거장 몫(0~1) */
  share?: number;
  /** 열 수 고정 */
  cols?: 1 | 2;
  /** 첫 줄을 더 내리는 깊이(월드) */
  headExtra?: number;
}

type Item = { id: string; node?: CosmosNode; state: CosmosNodeState; hub?: boolean; expanded?: boolean };

/** 정거장 안 항목 — 그래프 노드와 표시(marker). 순서는 `currentStationOrder` 가 판정 순으로 다시 세운다. */
function itemsByStation(graph: CosmosGraph, markers: StationMarker[]): Map<WorkflowStage, Item[]> {
  const byStation = new Map<WorkflowStage, Item[]>(STATION_IDS.map((id) => [id, []]));
  for (const node of graph.nodes) {
    byStation.get(node.stage)?.push({
      id: node.id,
      node,
      state: node.state,
      hub: node.kind === "proposal" || node.kind === "audit",
      expanded: node.expanded,
    });
  }
  for (const marker of markers) byStation.get(marker.station)?.push({ id: marker.id, state: marker.state });
  return byStation;
}

/**
 * 지금 정거장 노드 오른쪽으로 라벨이 쓸 수 있는 폭(월드 단위) — 다음 열이나 다음 정거장 경계까지.
 * 이보다 긴 라벨은 옆 열 라벨을 덮는다(21차 검토: 1440 에서 약 70px 넘쳤다).
 */
export function currentLabelRoom(frame: StationFrame, current: WorkflowStage): number {
  const span = frame.spans[current - 1];
  if (!span) return 0;
  const cols = frame.columns[current - 1] ?? 1;
  return (span.x1 - span.x0) / cols - CURRENT_INSET;
}

export function layoutStations(
  graph: CosmosGraph,
  markers: StationMarker[],
  current: WorkflowStage,
  selectedId: string | null = null,
  fit: LayoutFit = { vscale: 1, marks: CURRENT_MARK_MAX },
): StationLayout {
  const byStation = itemsByStation(graph, markers);
  const { shown, hidden } = currentStationOrder(byStation.get(current) ?? [], selectedId, fit.marks);
  const slots = shown.length + (hidden > 0 ? 1 : 0);
  const cols: 1 | 2 = fit.cols !== undefined ? (fit.cols === 2 && slots > 4 ? 2 : 1) : slots > CURRENT_ROWS ? 2 : 1;
  const unit = stationSpans(current, cols, fit.share);
  const spans = unit.map((s) => ({ x0: (s.x0 - 0.5) * PATH_WIDTH, x1: (s.x1 - 0.5) * PATH_WIDTH }));
  const centers = spans.map((s) => (s.x0 + s.x1) / 2);
  const positions = new Map<string, Vec3>();
  const columns: number[] = STATION_IDS.map((id) => (id === current ? cols : 1));
  let bottom = 0;

  // 지금 정거장 — 두 열까지. 노드는 정거장 왼쪽 끝 가까이, 오른쪽으로 붙는 라벨이 정거장 폭을 다 쓴다.
  const index = current - 1;
  const rows = Math.max(1, Math.ceil(slots / cols));
  const left = spans[index].x0 + CURRENT_INSET;
  const colWidth = (spans[index].x1 - spans[index].x0) / cols;
  // 세로 배율이 1 보다 크면(좁은 캔버스) 머리 블록(원 · 이름 · 캡션 · 알약 ≈ 88px)이 첫 줄을 덮지 않게 줄 전체를 내린다.
  const rowTop = STATION_PATH_Y * (fit.vscale - 1) + (fit.headExtra ?? 0);
  const pitch = CURRENT_PITCH * fit.vscale;
  const anchorY = STATION_PATH_Y - (STATION_PATH_Y - STATION_ANCHOR_Y) * fit.vscale;
  const at = (i: number): Vec3 => [left + Math.floor(i / rows) * colWidth, -rowTop - (i % rows) * pitch, 0];
  shown.forEach((item, i) => {
    const p = at(i);
    positions.set(item.id, p);
    bottom = Math.min(bottom, p[1]);
  });
  let more: StationLayout["more"] = null;
  if (hidden > 0) {
    const p = at(shown.length);
    more = { at: p, count: hidden };
    bottom = Math.min(bottom, p[1]);
  }
  // 그리지 않는 항목(다른 정거장 · 상한 밖)은 자기 정거장 알약 자리에 — 선 끝이 거기 닿는다.
  for (const [station, items] of byStation) {
    for (const item of items) {
      if (!positions.has(item.id)) positions.set(item.id, [centers[station - 1], anchorY, 0]);
    }
  }

  // 1 공고가 지금 정거장이면 공고 카드(약 260px)가 첫 줄 아래로 늘어진다 — 카메라가 그만큼 담게 바닥을 내린다.
  if (current === 1) bottom = Math.min(bottom, -rowTop - NOTICE_CARD_DEPTH * fit.vscale);

  const nodes = graph.nodes.map((node) => {
    const p = positions.get(node.id);
    return p ? { ...node, position: [p[0], p[1], p[2]] as [number, number, number] } : node;
  });
  const markerPos = new Map<string, Vec3>();
  for (const marker of markers) {
    const p = positions.get(marker.id);
    if (p) markerPos.set(marker.id, p);
  }
  return {
    graph: { ...graph, nodes, nodeById: new Map(nodes.map((node) => [node.id, node])) },
    markerPos,
    frame: {
      centers,
      spans,
      top: STATION_PATH_Y + PATH_HEADROOM * fit.vscale,
      // 선 길 셋이 마지막 줄 아래를 지나므로 여백을 조금 더 둔다.
      bottom: bottom - LANE_ROOM * fit.vscale,
      columns,
      vscale: fit.vscale,
      marks: fit.marks,
      anchorY,
      narrow: fit.share !== undefined,
      laneY: bottom - LANE_FIRST * fit.vscale,
      laneStep: LANE_STEP * fit.vscale,
    },
    shownIds: new Set(shown.map((item) => item.id)),
    more,
  };
}

/**
 * 세로 배치가 맞춰진 화면 배율(px / 월드 단위) — 줄 간격 1.5 가 이름표 높이(27px)를, 머리 깊이 4.6 이 머리 블록(88px)을
 * 담는 배율이다. 1440 은 이보다 크다(배율 1 그대로).
 */
const REF_PX_PER_UNIT = 18;
const MIN_MARKS = 4;
/**
 * 지금이 아닌 정거장 칸이 이보다 좁으면 이름 · 개수를 접고 번호 원과 상태 기호만 둔다(`stations.tsx`) — 그리고
 * 그 일곱 칸을 번호 원 폭(`TIGHT_SPAN_PX`)까지만 남기고 나머지를 지금 정거장에 준다.
 */
export const NAME_MIN_PX = 56;
const TIGHT_SPAN_PX = 30;
/** 좁은 캔버스에서 두 열로 세울 수 있는 한 열 폭(px) — 이름표 최소 폭 96 + 기호 · 여백 */
const LABEL_COLUMN_PX = 120;

/**
 * 좁은 캔버스(1024 · 390 에서 3D 를 고른 경우)의 배치 — 길 전체를 담느라 1 단위가 12px 아래로 줄면 줄 간격이
 * 이름표 높이보다, 머리 깊이가 머리 블록보다 좁아 이름표끼리 · 머리와 이름표가 겹쳤고(27차 §3-D 수용 검사:
 * 1024 에서 ④ 14쌍), 열 폭이 이름표보다 좁아 이름표가 옆으로 밀렸다.
 *  1) 가로가 정하는 배율(`pxH`)로 세로 배율을 정해 px 로 같은 줄 간격 · 머리 깊이를 되찾는다.
 *  2) 지금이 아닌 칸이 이름을 못 담을 만큼 좁으면 그 칸을 번호 원 폭만 남기고 지금 정거장에 몫을 준다 · 열 수는 폭으로.
 *  3) 그래도 화면 높이에 안 들어가면 그리는 수를 하나씩 줄여 나머지는 「외 n건 · 전체 보기」로 보낸다.
 * 넓은 창(1440)은 배율 1 · 상한 24 · 가중치 그대로다. `pxOf` 는 틀 → px/단위(카메라가 정한다 — 순환 import 를 피하려고 밖에서 받는다).
 */
/** 18px 이름이 `roomPx` 폭에서 낱말 단위로(break-keep) 몇 줄이 되는가 — 한글 18px · 그 밖 10px · 띄어쓰기 5px 어림. */
export function nameLines(name: string, roomPx: number): number {
  let lines = 1;
  let line = 0;
  for (const word of name.split(" ").filter(Boolean)) {
    const width = [...word].reduce((sum, ch) => sum + (/[가-힣]/.test(ch) ? 18 : 10), 0);
    if (line > 0 && line + 5 + width > roomPx) {
      lines += 1;
      line = width;
    } else {
      line += (line > 0 ? 5 : 0) + width;
    }
  }
  return lines;
}

export function fitStationLayout(
  graph: CosmosGraph,
  markers: StationMarker[],
  current: WorkflowStage,
  selectedId: string | null,
  pxOf: (frame: StationFrame) => number,
): StationLayout {
  let laid = layoutStations(graph, markers, current, selectedId);
  // 위아래가 없는 틀로 재면 가로(길 폭)가 정하는 배율이다 — 세로 배치를 바꿔도 변하지 않는 값.
  const pxH = pxOf({ ...laid.frame, top: 0, bottom: 0 });
  if (pxH <= 0) return laid;
  const other = laid.frame.spans.find((_, i) => i !== current - 1);
  const narrow = other !== undefined && (other.x1 - other.x0) * pxH < NAME_MIN_PX;
  if (!narrow && pxOf(laid.frame) >= REF_PX_PER_UNIT) return laid;
  const vscale = Math.max(1, (REF_PX_PER_UNIT / pxH) * 1.02);
  let base: LayoutFit = { vscale, marks: CURRENT_MARK_MAX };
  if (narrow) {
    const pathPx = PATH_WIDTH * pxH;
    const share = Math.min(0.75, Math.max(0.3, 1 - ((STATION_IDS.length - 1) * TIGHT_SPAN_PX) / pathPx));
    // 좁으면 지금 정거장 이름이 칸 폭 안에서 접힌다 — 접힌 줄(24px)만큼 첫 줄을 더 내린다(390 실측: 「회사 수행근거 연결」 세 줄).
    const lines = nameLines(graph.steps[current - 1]?.label ?? STATION_NAMES[current], Math.max(96, pathPx * share - 8));
    const extraPx = 24 * lines;
    base = { ...base, share, cols: (pathPx * share) / 2 >= LABEL_COLUMN_PX ? 2 : 1, headExtra: (extraPx * vscale) / REF_PX_PER_UNIT };
  }
  for (let marks = CURRENT_MARK_MAX; marks >= MIN_MARKS; marks -= 1) {
    laid = layoutStations(graph, markers, current, selectedId, { ...base, marks });
    if (pxOf(laid.frame) * vscale >= REF_PX_PER_UNIT * 0.98) return laid;
  }
  return laid;
}
