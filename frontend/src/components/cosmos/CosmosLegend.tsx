"use client";

/**
 * 지도 위 · 아래의 작은 두 가지 (21차 · prompt_11 §3-5 · 27차 §3-D-3 · 5).
 *  - `FocusChip` — 지도 위에 겹치는 유일한 것. 고른 항목이 **지금 정거장에 있을 때만** 이름과 선이 닿는 정거장을 적는다.
 *  - `MapKey` — 지도 아래 도구막대 첫 줄에 늘 보이는 범례 한 줄: 지금 정거장 기호 · 판정 낱말 넷 · 선 안내.
 * 「범례」 단추와 상세 시트(LegendSheet)는 그대로 있다. 3D와 2D가 같은 부품을 쓴다.
 */

import type { CosmosGraph, WorkflowStage } from "@/lib/cosmos/graph";
import { VERDICT_KEY, nodeColorHex } from "@/lib/cosmos/itemTypes";
import { STATION_GLYPHS, STATION_NAMES, selectionLines } from "@/lib/cosmos/stations";

export interface FocusChipProps {
  graph: CosmosGraph;
  selectedId: string | null;
  stage: WorkflowStage;
}

export function FocusChip({ graph, selectedId, stage }: FocusChipProps) {
  if (!selectedId) return null;
  const node = graph.nodeById.get(selectedId);
  // 다른 정거장 항목을 고른 채 정거장을 옮기면 카드가 그 정거장 것을 계속 말했다 — 지금 정거장 것만(27차 §3-D-3).
  if (!node || node.stage !== stage) return null;
  const lines = selectionLines(graph, stage, node.id);
  return (
    <div
      role="status"
      className="pointer-events-auto flex max-w-full items-center gap-2 rounded-full border border-cosmos-border-strong bg-cosmos-panel py-1 px-3 text-[13px] text-cosmos-text shadow-[0_8px_24px_var(--cosmos-shadow-soft)] backdrop-blur"
    >
      <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: nodeColorHex(node) }} />
      <span className="font-semibold text-cosmos-cyan">선택 ·</span>
      {/* 묶음은 `short` 가 이름뿐이므로 건수가 든 온전한 이름을 쓴다. 코드(REQ- …)는 상세 · 목록에만(§3-D-6). */}
      <span className="min-w-0 truncate">{node.groupCount !== undefined ? node.label : node.short}</span>
      <span className="shrink-0 text-cosmos-secondary">
        ·{" "}
        {lines.length > 0
          ? `연결: ${lines.map((line) => `${line.station} ${STATION_NAMES[line.station]}`).join(" · ")}`
          : // 공고는 요구사항의 출발점이다 — 「연결 없음」이라 하면 요구사항과 끊긴 것으로 읽혔다(27차 검수 R27D-OWN-09).
            node.kind === "notice"
            ? `요구사항 ${graph.counts.requirements}건의 출발점`
            : "연결 없음"}
      </span>
    </div>
  );
}

/**
 * 늘 보이는 범례 한 줄 (27차 §3-D-5) — 판정 낱말 넷은 범례 시트와 **글자까지 같다**(`VERDICT_KEY`).
 * 도구막대 안 제 줄(basis-full)이라 다른 단추와 겹치지 않는다.
 */
export function MapKey({ stage }: { stage: WorkflowStage }) {
  return (
    <p data-map-key className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1 text-[13px] leading-5 text-cosmos-secondary">
      {STATION_GLYPHS[stage].map((glyph) => (
        <span key={glyph.name} className="inline-flex items-center gap-1">
          <span aria-hidden="true" className="text-cosmos-text">
            {glyph.glyph}
          </span>
          {glyph.name}
        </span>
      ))}
      {VERDICT_KEY.map((key) => (
        <span key={key.word} className="inline-flex items-center gap-1" data-map-key-verdict={key.word}>
          <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: key.color }} />
          {key.word}
        </span>
      ))}
      <span className="text-cosmos-muted">선은 항목을 누르면 보입니다</span>
    </p>
  );
}
