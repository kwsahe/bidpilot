/**
 * 지도는 「길」이다 (21차 · prompt_11 §3) — 공고 → 적합도 → 참가자격 → 요구사항 → 근거 → 제안서 → 점검 → 결정.
 *
 * 정거장 n 은 레일 n 단계와 같다(이름·순서). 노드의 `stage` 가 곧 그 노드의 정거장이다 —
 * 공고 1 · 요구사항 4 · 근거 5 · 제안서 6 · 점검 7. 그래프에 노드가 없는 정거장(참가자격 · 제안서 문장 · 결정)은
 * 이미 받아 둔 분석 결과에서 **그리기만 하는 표시(marker)** 를 만든다 — 새 자료를 부르지 않고, 고를 수 없다
 * (그 내용은 레일과 상세 패널이 이미 보여 준다).
 *
 * 순수 함수만 둔다 — 3D·2D·테스트가 같은 계산을 쓴다.
 */

import { blockingText, checklistOrder, gateBadge, inClauseSection, type EligibilityGateView } from "@/lib/cosmos/eligibilityGate";
import { focusIds, type CosmosGraph, type CosmosLinkState, type WorkflowStage, type WorkflowStepView } from "@/lib/cosmos/graph";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import type { CosmosNodeState } from "@/lib/cosmos/theme";

/**
 * 지도 위 정거장 이름 — 레일 단계 이름의 짧은 꼴(18px 로 좁은 정거장에도 들어가게). 온전한 이름은 레일에 있다.
 * **낱말은 모두 레일 이름 안의 낱말이다**(27차 §3-D-9) — 「참가 여부」 ⊂ 「참가 가능 여부」. 지금 정거장은 레일 이름 그대로 쓴다.
 */
export const STATION_NAMES: Record<WorkflowStage, string> = {
  1: "공고",
  2: "적합도",
  3: "참가 여부",
  4: "요구사항",
  5: "근거",
  6: "제안서",
  7: "점검",
  8: "결정",
};

export const STATION_IDS: readonly WorkflowStage[] = [1, 2, 3, 4, 5, 6, 7, 8];

/** 밝기 3단계 — 지금 정거장 · 바로 옆 · 나머지. */
export type StationTier = "current" | "near" | "far";

export function stationTier(station: WorkflowStage, current: WorkflowStage): StationTier {
  const distance = Math.abs(station - current);
  return distance === 0 ? "current" : distance === 1 ? "near" : "far";
}

/**
 * 정거장 폭 비율 — 지금 정거장은 긴 라벨 열 수만큼(한 열 4 · 두 열 5.5), 옆 1.2, 나머지 1.15 (아코디언).
 *
 * 똑같이 나누면 1440 에서 정거장 하나가 118px 이라 지금 정거장의 긴 라벨이 들어가지 않는다.
 * 여덟 이름이 한 화면에 다 보여야 하므로(첫 화면 검사) 길 전체 폭은 그대로 두고 나눔만 바꾼다.
 * 나머지 정거장 폭(1440 에서 약 76px)은 18px 이름 네 글자(「참가자격」 72px)가 들어가는 만큼이다.
 */
const TIER_WEIGHT: Record<Exclude<StationTier, "current">, number> = { near: 1.2, far: 1.15 };
const CURRENT_WEIGHT = { 1: 4, 2: 5.5 } as const;

/**
 * 이 정거장의 항목을 **그리고** 이름표를 다는가 — 지금 정거장만 (27차 §3-D-1).
 *
 * 예전에는 옆 정거장에 번호 칩을, 나머지 정거장에 흐린 점을 그렸다. 그 크기 · 밝기에서는 모양도 색도
 * 구별되지 않았고(1 공고 화면에서 점 68개 중 67개가 이름 없음), 번호가 화면마다 다른 뜻이었다. 지금이 아닌
 * 정거장은 이름 알약(번호 · 이름 · 개수 · 상태 기호)만 남는다 — `stationFlag`.
 */
export function stationLabelled(tier: StationTier): boolean {
  return tier === "current";
}

/**
 * 정거장 낱말 알약 — 레일이 「!」 「✕」인 단계에만 (27차 §3-D-2 · 레일과 지도가 같은 말). ✓ ● ○ 단계는 null.
 * 3 참가 여부는 확인 전 조항 수(`gateBadge`) 그대로 · 그 밖의 확인 필요는 「확인 필요」 · 실패는 「실패」.
 */
export function stationFlag(
  step: WorkflowStepView | undefined,
  gate: EligibilityGateView | null,
): { word: string; glyph: string; color: string } | null {
  if (!step) return null;
  if (step.status === "failed") {
    const meta = STEP_STATUS_META.failed;
    return { word: meta.label, glyph: meta.glyph, color: meta.color };
  }
  if (step.status !== "attention") return null;
  const meta = STEP_STATUS_META.attention;
  return { word: (step.id === 3 ? gateBadge(gate) : null) ?? meta.label, glyph: meta.glyph, color: meta.color };
}

/** 0..1 로 정규화한 정거장 구간 [x0, x1] — 왼쪽(1)에서 오른쪽(8)으로. `currentColumns` 는 지금 정거장의 열 수. */
export function stationSpans(
  current: WorkflowStage,
  currentColumns: 1 | 2 = 1,
  /** 지금 정거장이 차지할 몫(0~1) — 좁은 캔버스 3D 가 나머지 일곱을 번호 원 폭만 남기고 준다(`fitStationLayout`). 없으면 가중치대로 */
  currentShare?: number,
): Array<{ x0: number; x1: number }> {
  const weights = STATION_IDS.map((id) => {
    const tier = stationTier(id, current);
    return tier === "current" ? CURRENT_WEIGHT[currentColumns] : TIER_WEIGHT[tier];
  });
  if (currentShare !== undefined && currentShare > 0 && currentShare < 1) {
    const others = weights.reduce((sum, w, i) => (i === current - 1 ? sum : sum + w), 0);
    weights[current - 1] = (others * currentShare) / (1 - currentShare);
  }
  const total = weights.reduce((sum, w) => sum + w, 0);
  const spans: Array<{ x0: number; x1: number }> = [];
  let x = 0;
  for (const w of weights) {
    spans.push({ x0: x / total, x1: (x + w) / total });
    x += w;
  }
  return spans;
}

/** 그래프에 노드가 없는 정거장의 표시 모양 — 조건 ◆ · 자격 ▲ · 문장 ─ · 결정 ◉. */
export type MarkerShape = "diamond" | "triangle" | "bar" | "target";

export interface StationMarker {
  id: string;
  station: WorkflowStage;
  shape: MarkerShape;
  state: CosmosNodeState;
  /** 짧은 라벨(옆 정거장) */
  short: string;
  /** 긴 라벨(지금 정거장) */
  label: string;
  /** 묶을 때 쓰는 이름 (조항 종류) */
  group?: string;
  /** 묶음 표시면 그 안의 건수 */
  count?: number;
}

/**
 * 한 정거장에 표시가 이보다 많으면 **종류별로 묶는다** — 요구사항 묶음(`requirement-group`)과 같은 생각이다.
 * 제안요청서 조항이 많은 공고는 참가자격 조항이 68줄이다(1704406). 그것을 점 68개와 긴 라벨 68개로 그리면
 * 지도가 읽히지 않는다. 묶음 이름에 건수를 적고, 하나하나는 3단계 체크리스트에서 본다.
 */
export const MARKER_GROUP_THRESHOLD = 12;

/** 나쁜 상태가 먼저 — 묶음의 색은 그 안에서 가장 나쁜 것이다 · 지금 정거장도 이 순서로 선다(27차 §3-D-6). */
export const STATE_RANK: CosmosNodeState[] = ["warning", "check", "partial", "missing", "neutral", "ok", "resolved"];

/** 지금 정거장에 그리는 표시 상한 — 두 열 × 12 줄. 넘으면 나쁜 것부터 23개 + 「외 n건 · 전체 보기」 칩 (27차 §3-D-6). */
export const CURRENT_MARK_MAX = 24;

/**
 * 지금 정거장의 그리는 순서 — 허브(제안서 · 점검) 먼저, 그다음 판정이 나쁜 순(같은 판정은 원래 순서).
 * 24 를 넘으면 23 개만 그리고 나머지는 칩이 센다. **사람이 펼친 묶음**이 있으면 다 그린다(수용 기준의 예외).
 * 고른 항목은 상한 밖이어도 그린다 — 상세 · 목록에서 고른 것이 지도에 없으면 선의 시작이 없다.
 */
export function currentStationOrder<T extends { id: string; state: CosmosNodeState; hub?: boolean; expanded?: boolean }>(
  items: T[],
  selectedId: string | null = null,
  max: number = CURRENT_MARK_MAX,
): { shown: T[]; hidden: number } {
  const rank = (item: T) => (item.hub ? -1 : STATE_RANK.indexOf(item.state));
  const sorted = [...items].sort((a, b) => rank(a) - rank(b));
  if (sorted.length <= max || items.some((item) => item.expanded)) return { shown: sorted, hidden: 0 };
  const shown = sorted.slice(0, Math.max(1, max - 1));
  const picked = selectedId ? sorted.find((item) => item.id === selectedId) : undefined;
  if (picked && !shown.includes(picked)) shown[shown.length - 1] = picked;
  return { shown, hidden: sorted.length - shown.length };
}

/** 고른 항목에서 나가는 선 하나 — 상대 정거장 알약까지 (27차 §3-D-3). */
export interface SelectionLine {
  station: WorkflowStage;
  state: Exclude<CosmosLinkState, "neutral">;
}

export const STATION_LINE_MAX = 3;
const LINE_RANK: Record<SelectionLine["state"], number> = { warning: 0, candidate: 1, active: 2 };

/**
 * 고른 항목 → 관련 정거장마다 선 하나(가장 나쁜 연결의 색) · 최대 3 개. 고른 것이 없거나 지금 정거장에 없으면 [].
 *
 * 선은 청록(연결됨) · 호박(확인이 필요한 연결 · 점선) · 빨강(문제) 셋뿐이다 — 회청 선은 없다(중립 연결은 청록).
 * 공고 → 요구사항 스포크는 세지 않는다(모든 요구사항이 공고에 이어져 있어 뜻이 없다).
 */
export function selectionLines(graph: CosmosGraph, stage: WorkflowStage, anchorId: string | null): SelectionLine[] {
  const node = anchorId ? graph.nodeById.get(anchorId) : undefined;
  if (!node || node.stage !== stage) return [];
  const focus = focusIds(graph, node.id, Number.POSITIVE_INFINITY);
  const worst = new Map<WorkflowStage, SelectionLine["state"]>();
  for (const link of graph.links) {
    if (!focus.linkIds.has(link.id) || link.kind === "notice-requirement" || link.kind === "notice-group") continue;
    const state: SelectionLine["state"] = link.state === "warning" ? "warning" : link.state === "candidate" ? "candidate" : "active";
    for (const end of [link.source, link.target]) {
      const station = graph.nodeById.get(end)?.stage;
      if (!station || station === stage) continue;
      const prev = worst.get(station);
      if (!prev || LINE_RANK[state] < LINE_RANK[prev]) worst.set(station, state);
    }
  }
  return [...worst]
    .map(([station, state]) => ({ station, state }))
    .sort((a, b) => LINE_RANK[a.state] - LINE_RANK[b.state] || a.station - b.station)
    .slice(0, STATION_LINE_MAX)
    .sort((a, b) => a.station - b.station);
}

/**
 * 정거장마다 그리는 기호와 이름 — 늘 보이는 범례 줄(`MapKey`)과 범례 시트가 같이 읽는다 (27차 §3-D-5).
 * 모양의 근거: 3D `geometries.ts` · 2D `Cosmos2D` 의 기호. 한 정거장에 모양은 2 종 이하다.
 */
export const STATION_GLYPHS: Record<WorkflowStage, ReadonlyArray<{ glyph: string; name: string }>> = {
  1: [{ glyph: "●", name: "공고" }],
  2: [],
  3: [
    { glyph: "◆", name: "놓치면 안 되는 조건" },
    { glyph: "▲", name: "참가자격 조항" },
  ],
  4: [{ glyph: "▪", name: "요구사항" }],
  5: [{ glyph: "▫", name: "회사 근거" }],
  6: [{ glyph: "─", name: "제안서 문장" }],
  7: [{ glyph: "⚠", name: "점검 발견" }],
  8: [{ glyph: "◉", name: "결정" }],
};

const CONDITION_GROUP: Partial<Record<CosmosNodeState, string>> = {
  warning: "참가 차단",
  check: "조치·확인",
  ok: "해결",
};

function grouped(
  markers: StationMarker[],
  keyOf: (marker: StationMarker) => string,
  prefix: string,
  shape: MarkerShape,
  labelPrefix = "",
): StationMarker[] {
  if (markers.length <= MARKER_GROUP_THRESHOLD) return markers;
  const groups = new Map<string, StationMarker[]>();
  for (const marker of markers) {
    const key = keyOf(marker);
    groups.set(key, [...(groups.get(key) ?? []), marker]);
  }
  return [...groups].map(([key, members]) => ({
    id: `${prefix}:${key}`,
    station: members[0].station,
    shape,
    state: STATE_RANK.find((state) => members.some((m) => m.state === state)) ?? "neutral",
    short: `${clip(key, 10)} ${members.length}`,
    label: `${labelPrefix}${key} ${members.length}건`,
    count: members.length,
  }));
}

/**
 * 정거장 이름 아래 「n개」 — **항목** 수. 점 수와 다르다: 제안서·점검 허브는 항목이 아니고, 묶음 점은 그 안의
 * 건수로 센다. 점 수로 적으면 ⑦ 이 발견 2건에 「3개」, 요구사항 40건 묶음이 「6개」로 레일과 어긋났다 (21차 검토).
 */
export function stationItemCounts(graph: CosmosGraph, markers: StationMarker[]): number[] {
  const counts = STATION_IDS.map(() => 0);
  for (const node of graph.nodes) {
    if (node.kind === "proposal" || node.kind === "audit") continue;
    const group = node.kind === "requirement-group" || node.kind === "finding-group";
    // 펼친 묶음은 그 안의 항목이 따로 그려진다 — 묶음 점은 세지 않는다.
    if (group && node.expanded) continue;
    counts[node.stage - 1] += group ? (node.groupCount ?? 1) : 1;
  }
  for (const marker of markers) counts[marker.station - 1] += marker.count ?? 1;
  return counts;
}

const CONDITION_STATE: Record<string, CosmosNodeState> = {
  BLOCKER: "warning",
  ACTION: "check",
  CHECK: "check",
  CLEARED: "ok",
};

const VERDICT_STATE: Record<string, CosmosNodeState> = { FAIL: "warning", CHECK: "check", PASS: "ok" };

const STEP_STATE: Record<string, CosmosNodeState> = {
  done: "ok",
  failed: "warning",
  attention: "check",
};

function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

/**
 * ③ 조건 ◆ · 자격 ▲ · ⑥ 문장 ─ · ⑧ 결정 ◉.
 *
 * - 조건: 조건 패널이 보여 주는 것과 같다(참고 INFO 는 뺀다 — `GatePanel`).
 * - 자격: 3단계 체크리스트와 **같은 줄** — 실판정이면 참가자격 조항 절(`QUAL-*`), 데모는 판정 줄 전부.
 *   순서도 체크리스트와 같다(불가 → 확인 필요 → 가능).
 * - 문장: 제안서 초안 문장 하나에 하나.
 * - 결정: 8단계 요약 하나.
 */
export function stationMarkers(graph: CosmosGraph): StationMarker[] {
  // 제목이 같은 조건은 하나로 — 「실적·금액 요건」 두 줄이 같은 이름표 둘로 서지 않게(27차 §3-D-6).
  // ◆ 조건 · ▲ 자격은 모양 말고 글자로도 가른다: 이름표 앞 「조건 · 」 「자격 · 」.
  const byTitle = new Map<string, StationMarker[]>();
  for (const condition of graph.source.analysis.conditions?.conditions ?? []) {
    if (condition.status === "INFO") continue;
    const marker: StationMarker = {
      id: `cond:${condition.id}`,
      station: 3,
      shape: "diamond",
      state: CONDITION_STATE[condition.status] ?? "neutral",
      short: clip(condition.title, 12),
      label: `조건 · ${clip(condition.title, 24)}`,
    };
    byTitle.set(condition.title, [...(byTitle.get(condition.title) ?? []), marker]);
  }
  const conditions: StationMarker[] = [...byTitle].map(([title, same]) =>
    same.length === 1
      ? same[0]
      : {
          ...same[0],
          id: `cond-same:${title}`,
          count: same.length,
          state: STATE_RANK.find((state) => same.some((m) => m.state === state)) ?? "neutral",
          label: `조건 · ${clip(title, 20)} ${same.length}건`,
        },
  );
  const clauses: StationMarker[] = [];
  const rows = graph.source.analysis.eligibility ? graph.eligibility.filter(inClauseSection) : graph.eligibility;
  for (const row of checklistOrder(rows)) {
    clauses.push({
      id: `qual:${row.rule_id}`,
      station: 3,
      shape: "triangle",
      state: VERDICT_STATE[row.status] ?? "neutral",
      short: row.clause_id ? `${row.label} ${row.clause_id}` : row.label,
      label: `자격 · ${row.clause_text ? blockingText(row) : row.label}`,
      group: row.label,
    });
  }
  const markers: StationMarker[] = [
    ...grouped(conditions, (m) => CONDITION_GROUP[m.state] ?? "조건", "cond-group", "diamond", "조건 · "),
    ...grouped(clauses, (m) => m.group ?? m.short, "qual-group", "triangle", "자격 · "),
  ];
  for (const sentence of graph.proposal?.sentences ?? []) {
    markers.push({
      id: `sent:${sentence.id}`,
      station: 6,
      shape: "bar",
      state: sentence.needs_review ? "check" : "ok",
      short: clip(sentence.text, 10),
      label: clip(sentence.text, 26),
    });
  }
  const decision = graph.steps[7];
  if (decision) {
    markers.push({
      id: "decision",
      station: 8,
      shape: "target",
      state: STEP_STATE[decision.status] ?? "neutral",
      short: clip(decision.summary, 12),
      label: clip(decision.summary, 28),
    });
  }
  return markers;
}
