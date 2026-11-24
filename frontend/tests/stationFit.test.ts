/**
 * 좁은 캔버스 3D 배치 (27차 §3-D 수용) — 1024 · 390 에서 3D 를 골라도 이름표가 겹치지 않게 세로 배율 · 몫 · 상한을 맞춘다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { CosmosGraph } from "../src/lib/cosmos/graph.ts";
import { CURRENT_MARK_MAX } from "../src/lib/cosmos/stations.ts";
import { fitStationLayout, layoutStations, nameLines, NAME_MIN_PX, PATH_WIDTH, type StationFrame } from "../src/components/cosmos/three/stationLayout.ts";

function graphOf(count: number): CosmosGraph {
  const nodes = Array.from({ length: count }, (_, i) => ({ id: `req:${i}`, kind: "requirement", stage: 4, state: i < 3 ? "warning" : "ok" }));
  return { nodes, links: [], nodeById: new Map(), steps: [] } as unknown as CosmosGraph;
}

/** 가로가 정하는 배율 `pxH` · 캔버스 높이 `heightPx` 로 거리를 잡는 가짜 카메라 — 위아래가 길면 배율이 준다. */
function camera(pxH: number, heightPx: number) {
  return (frame: StationFrame) => {
    const tall = frame.top - frame.bottom;
    return tall <= 0 ? pxH : Math.min(pxH, (heightPx * 0.9) / tall);
  };
}

describe("좁은 캔버스 3D 배치", () => {
  it("이름 줄 수 어림 — 낱말 단위로 접는다", () => {
    assert.equal(nameLines("요구사항 정리", 200), 1);
    assert.equal(nameLines("회사 수행근거 연결", 102), 3);
    assert.equal(nameLines("참가 가능 여부", 102), 2);
  });

  it("넓은 창은 21차 배치 그대로 — 배율 1 · 상한 24", () => {
    const graph = graphOf(23);
    const wide = fitStationLayout(graph, [], 4, null, camera(20, 2000));
    const plain = layoutStations(graph, [], 4, null);
    assert.equal(wide.frame.vscale, 1);
    assert.equal(wide.frame.marks, CURRENT_MARK_MAX);
    assert.equal(wide.frame.narrow, false);
    assert.deepEqual(wide.frame.spans, plain.frame.spans);
    assert.equal(wide.shownIds.size, 23);
  });

  it("좁은 창은 줄 간격을 px 로 되찾고, 높이가 모자라면 그리는 수를 줄인다 · 나머지 칸은 번호 원 폭 이상", () => {
    const graph = graphOf(23);
    const pxOf = camera(7.8, 440);
    const laid = fitStationLayout(graph, [], 4, null, pxOf);
    assert.equal(laid.frame.narrow, true);
    assert.ok(laid.frame.vscale > 2);
    // 줄 간격(1.5 × 배율) × 실제 배율 ≥ 이름표 높이 근처(27px)
    assert.ok(1.5 * laid.frame.vscale * pxOf(laid.frame) >= 26);
    assert.ok(laid.shownIds.size < 23 && laid.more !== null);
    assert.equal(laid.shownIds.size + laid.more.count, 23);
    const px = pxOf(laid.frame);
    laid.frame.spans.forEach((span, i) => {
      if (i !== 3) assert.ok((span.x1 - span.x0) * px >= 24, `정거장 ${i + 1} 칸 ${((span.x1 - span.x0) * px).toFixed(1)}px`);
    });
    assert.ok((laid.frame.spans[3].x1 - laid.frame.spans[3].x0) * px > NAME_MIN_PX);
    assert.ok(Math.abs(laid.frame.spans[7].x1 - laid.frame.spans[0].x0 - PATH_WIDTH) < 1e-9);
  });
});
