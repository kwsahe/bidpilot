"use client";

/**
 * Evidence Cosmos 3D 뷰. Shell은 이 컴포넌트를 next/dynamic(..., { ssr: false })로만 불러온다.
 *
 * 입찰 지도는 **정거장 8개의 길**이다 (21차 · prompt_11): 길과 이름 → 정거장 사이 연결 → 평면 기호 → 카메라.
 * 지원사업 지도(어휘가 다르다)는 궤도 배치 그대로다. 배경 격자 · 궤도 안내선 · 흐름 파티클 · 조명은 없다.
 * 라벨 충돌 회피 Provider가 Scene 전체를 감싼다.
 */

import { Canvas, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { useEffect, useMemo, useSyncExternalStore } from "react";

import type { CosmosViewProps } from "@/components/cosmos/types";
import { BID_VOCABULARY, type CosmosVocabulary } from "@/lib/cosmos/vocabulary";
import { eligibilityGateView } from "@/lib/cosmos/eligibilityGate";
import { selectionLines, stationItemCounts, stationMarkers, stationTier, type StationTier } from "@/lib/cosmos/stations";
import { isVisible, type CosmosGraph, type CosmosNode, type CosmosNodeKind } from "@/lib/cosmos/graph";

import { CameraRig, stationPixelsPerUnit } from "./CameraRig";
import { CAMERA_PRESETS, FOCUS_STEP_DELAY, MOBILE_LABEL_BREAKPOINT } from "./constants";
import { useCosmosGeometries } from "./geometries";
import { LabelCollisionProvider } from "./labels";
import { CosmosLinkLine, type LinkPoints } from "./links";
import { CosmosNodeMesh } from "./nodes";
import { currentLabelRoom, fitStationLayout } from "./stationLayout";
import { MoreChip, SelectionLines, StationMarkerMesh, StationPath } from "./stations";

const COMPACT_QUERY = `(max-width: ${MOBILE_LABEL_BREAKPOINT - 1}px)`;
function subscribeCompact(onChange: () => void): () => void {
  const media = window.matchMedia(COMPACT_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const getCompact = () => window.matchMedia(COMPACT_QUERY).matches;
const getCompactServer = () => false;

/**
 * 지금 정거장 긴 라벨 폭(px) — **열 폭에 맞춘다**(노드 오른쪽 ~ 다음 열·다음 정거장 경계). 고정 px 이면
 * 1440 에서 라벨이 정거장 밖으로 약 70px 나가 옆 정거장 점을 덮었다 (21차 검토). 상한·하한만 둔다.
 */
const LABEL_WIDTH_MAX = 260;
const LABEL_WIDTH_MIN = 96;
/** 노드 가운데에서 라벨 왼쪽 끝까지(월드 단위 — nodes.tsx 의 offset `radius + 0.25`) + 여유 px. */
const LABEL_LEAD = 0.5;
const LABEL_MARGIN_PX = 8;

/** 그린 기호의 모양 이름 — 「한 화면에 모양 2 종 이하」를 재는 데이터 속성용(3D 는 메시라 DOM 으로 셀 수 없다). */
const NODE_SHAPE: Record<CosmosNodeKind, string> = {
  notice: "circle",
  requirement: "square",
  "requirement-group": "square-lg",
  evidence: "card",
  proposal: "bar",
  audit: "warn-lg",
  finding: "warn",
  "finding-group": "warn-lg",
};

export default function Cosmos3D(props: CosmosViewProps) {
  const { onSelect } = props;
  // 화면 문구는 어휘 객체에서 온다. 넘기지 않으면 입찰 기본 어휘 — 지금까지와 같은 말이 나온다.
  const vocabulary = props.vocabulary ?? BID_VOCABULARY;
  const initial = CAMERA_PRESETS.overview;
  // 모바일은 픽셀 밀도 상한을 낮춰 후처리 없이도 프레임을 지킨다.
  const compact = useSyncExternalStore(subscribeCompact, getCompact, getCompactServer);

  return (
    <div role="img" aria-label={vocabulary.ariaLabel} className="absolute inset-0">
      <Canvas
        aria-hidden
        dpr={compact ? [1, 1.25] : [1, 1.5]}
        flat
        frameloop="always"
        gl={{ antialias: true, powerPreference: "high-performance", alpha: true }}
        camera={{
          fov: 45,
          near: 0.1,
          far: 200,
          position: [initial.position[0], initial.position[1], initial.position[2]],
        }}
        onPointerMissed={() => onSelect(null)}
        className="h-full w-full"
      >
        {/* 정거장이 바뀌면 노드가 새 자리로 옮겨 간다 — 라벨 배치를 그 자리에서 다시 푼다. */}
        <LabelCollisionProvider resetKey={vocabulary === BID_VOCABULARY ? props.stage : undefined}>
          <Scene {...props} vocabulary={vocabulary} />
        </LabelCollisionProvider>
      </Canvas>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 장면
// ---------------------------------------------------------------------------

/** 같은 종류 안에서의 순번 — 등장 stagger에 쓴다. */
function buildOrbitIndex(graph: CosmosGraph): Map<string, number> {
  const counters: Partial<Record<CosmosNodeKind, number>> = {};
  const index = new Map<string, number>();
  for (const node of graph.nodes) {
    const next = counters[node.kind] ?? 0;
    index.set(node.id, next);
    counters[node.kind] = next + 1;
  }
  return index;
}

function buildLinkPoints(graph: CosmosGraph): Map<string, LinkPoints> {
  const points = new Map<string, LinkPoints>();
  for (const link of graph.links) {
    const source = graph.nodeById.get(link.source);
    const target = graph.nodeById.get(link.target);
    if (!source || !target) continue;
    points.set(link.id, [source.position, target.position]);
  }
  return points;
}

function Scene({
  graph,
  stage,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
  highlightNodeIds,
  highlightLinkIds,
  highlightOrder,
  cameraPreset,
  focusNodeId,
  resetSignal,
  reducedMotion,
  paused,
  vocabulary,
  onStation,
  onShowAll,
  lineAnchorId = null,
}: CosmosViewProps & { vocabulary: CosmosVocabulary }) {
  const geometries = useCosmosGeometries();
  /**
   * 입찰 지도는 **정거장 8개의 길**이다 (21차). 단계(stage)는 「지금 정거장」이고, **지금 정거장만 기호와 이름표를
   * 그린다**(27차 §3-D-1) — 나머지 일곱은 이름 알약. 선은 고른 항목에서만 관련 정거장마다 하나(§3-D-3).
   * 지원사업(어휘가 다르다)은 예전 궤도 배치 그대로다.
   */
  const stationMode = vocabulary === BID_VOCABULARY;
  const anchorId = lineAnchorId ?? null;
  const markers = useMemo(() => (stationMode ? stationMarkers(graph) : []), [stationMode, graph]);
  const size = useThree((state) => state.size);
  const camera = useThree((state) => state.camera);
  const fov = camera instanceof THREE.PerspectiveCamera ? camera.fov : 45;
  const laid = useMemo(
    () =>
      stationMode
        ? fitStationLayout(graph, markers, stage, anchorId ?? selectedId, (frame) => stationPixelsPerUnit(frame, fov, size.width, size.height))
        : null,
    [stationMode, graph, markers, stage, anchorId, selectedId, fov, size.width, size.height],
  );
  const g = laid?.graph ?? graph;
  const itemCounts = useMemo(() => stationItemCounts(graph, markers), [graph, markers]);
  const orbitIndex = useMemo(() => buildOrbitIndex(g), [g]);
  const linkPoints = useMemo(() => buildLinkPoints(g), [g]);
  const visibleNodes = useMemo(
    () => (laid ? g.nodes.filter((node) => laid.shownIds.has(node.id)) : g.nodes.filter((node) => isVisible(node, stage))),
    [laid, g, stage],
  );
  const drawnMarkers = useMemo(() => (laid ? markers.filter((marker) => laid.shownIds.has(marker.id)) : []), [laid, markers]);
  // 지원사업 궤도 지도만 예전 연결선을 그린다. 정거장 지도는 고른 항목의 선(`lines`)만.
  const visibleLinks = useMemo(() => (stationMode ? [] : g.links.filter((link) => isVisible(link, stage))), [stationMode, g, stage]);
  const lines = useMemo(() => (stationMode ? selectionLines(graph, stage, anchorId) : []), [stationMode, graph, stage, anchorId]);
  const anchorNode: CosmosNode | undefined = anchorId ? g.nodeById.get(anchorId) : undefined;
  const drawnLines = anchorNode && laid ? lines : [];
  // 정거장 지도에는 ①~⑤ 핵심 라벨을 달지 않는다 — 정거장 번호와 겹쳐 읽힌다.
  const keyLabels = useMemo(
    () => (stationMode ? new Map<string, never>() : vocabulary.keyLabels(graph)),
    [stationMode, vocabulary, graph],
  );
  const pxPerUnit = laid ? stationPixelsPerUnit(laid.frame, fov, size.width, size.height) : 0;
  const labelMaxWidth = laid
    ? Math.round(
        THREE.MathUtils.clamp(
          (currentLabelRoom(laid.frame, stage) - LABEL_LEAD) * pxPerUnit - LABEL_MARGIN_PX,
          LABEL_WIDTH_MIN,
          LABEL_WIDTH_MAX,
        ),
      )
    : undefined;

  /**
   * 측정용 — 라벨을 달아야 하는 점의 수를 문서에 적어 둔다 (prompt_01 §4-A-6).
   *
   * 3D 노드는 캔버스 안 메시라 DOM 으로 셀 수 없다. 라벨은 DOM(`data-cosmos-label`)이므로 「라벨 수 ≥ 점 수」를
   * 재려면 점 쪽 수를 밖으로 내보내야 한다. 정거장 지도는 지금 정거장에 **그리는** 것만 센다(27차 §3-D-1).
   */
  const labelledCount = laid ? laid.shownIds.size : visibleNodes.length;
  useEffect(() => {
    document.documentElement.dataset.cosmosNodes = String(labelledCount);
    return () => {
      delete document.documentElement.dataset.cosmosNodes;
    };
  }, [labelledCount]);
  /**
   * 지금 정거장 · 그릴 수 · 실제로 그린 수 · 선 수 · 모양 — 검사(check_visibility · check_map)와 리허설이 읽는다(27차 §3-D-11).
   * 「그린 수 = 그릴 수」가 「지금이 아닌 정거장에 그린 기호 0」의 증거다(그리는 목록 자체가 지금 정거장 것뿐이다).
   */
  const shouldDraw = laid ? laid.shownIds.size : 0;
  const drawnCount = visibleNodes.length + drawnMarkers.length;
  const shapes = useMemo(
    () => [...new Set([...visibleNodes.map((node) => NODE_SHAPE[node.kind]), ...drawnMarkers.map((marker) => marker.shape)])].sort().join(","),
    [visibleNodes, drawnMarkers],
  );
  const stationItems = laid ? itemCounts[stage - 1] ?? 0 : 0;
  useEffect(() => {
    if (!stationMode) return;
    const data = document.documentElement.dataset;
    data.cosmosStation = String(stage);
    data.cosmosStationNodes = String(shouldDraw);
    data.cosmosDrawnMarks = String(drawnCount);
    data.cosmosLinks = String(drawnLines.length);
    data.cosmosShapes = shapes;
    data.cosmosStationItems = String(stationItems);
    // 좁은 캔버스 맞춤(세로 배율 · 그리는 상한) — 1440 은 「1.00/24」
    data.cosmosFit = laid ? `${laid.frame.vscale.toFixed(2)}/${laid.frame.marks}` : "";
    return () => {
      delete data.cosmosStation;
      delete data.cosmosStationNodes;
      delete data.cosmosDrawnMarks;
      delete data.cosmosLinks;
      delete data.cosmosShapes;
      delete data.cosmosStationItems;
      delete data.cosmosFit;
    };
  }, [stationMode, stage, shouldDraw, drawnCount, drawnLines.length, shapes, stationItems, laid]);

  const hasHighlight = highlightNodeIds.size > 0 || highlightLinkIds.size > 0;
  const idleAnimation = !paused && !reducedMotion;
  const markerIndex = new Map<number, number>();
  /** ③ 정거장은 문이다 — 상세 띠·타일·체크리스트와 같은 계산(eligibilityGateView). */
  const gate = useMemo(
    () => (stationMode ? eligibilityGateView(graph.eligibility, graph.source.analysis.eligibility?.verdict ?? null) : null),
    [stationMode, graph],
  );
  const tierOf = (stageOfItem: number): StationTier | undefined =>
    stationMode ? stationTier(stageOfItem as typeof stage, stage) : undefined;

  return (
    <>
      {laid && (
        <StationPath
          frame={laid.frame}
          stage={stage}
          steps={graph.steps}
          counts={itemCounts}
          gate={gate}
          pxPerUnit={pxPerUnit}
          onStation={onStation}
        />
      )}
      {laid && anchorNode && (
        <SelectionLines lines={drawnLines} from={anchorNode.position} frame={laid.frame} blink={idleAnimation} />
      )}
      {laid?.more && <MoreChip at={laid.more.at} count={laid.more.count} onShowAll={onShowAll} />}

      {visibleLinks.map((link) => {
        const points = linkPoints.get(link.id);
        if (!points) return null;
        const highlighted = highlightLinkIds.has(link.id);
        return (
          <CosmosLinkLine
            key={link.id}
            link={link}
            points={points}
            highlighted={highlighted}
            dimmed={hasHighlight && !highlighted}
            pulse={link.state === "warning" && highlighted && idleAnimation}
            reducedMotion={reducedMotion}
            highlightDelay={(highlightOrder?.get(link.id) ?? 0) * FOCUS_STEP_DELAY}
          />
        );
      })}

      {visibleNodes.map((node) => {
        const highlighted = highlightNodeIds.has(node.id);
        const tier = tierOf(node.stage);
        return (
          <CosmosNodeMesh
            key={node.id}
            node={node}
            graph={g}
            stage={stage}
            geometries={geometries}
            orbitIndex={orbitIndex.get(node.id) ?? 0}
            hovered={hoveredId === node.id}
            selected={selectedId === node.id}
            highlighted={highlighted}
            dimmed={hasHighlight && !highlighted}
            reducedMotion={reducedMotion}
            paused={paused}
            onSelect={onSelect}
            onHover={onHover}
            keyLabel={keyLabels.get(node.id)}
            vocabulary={vocabulary}
            tier={tier}
            labelMaxWidth={labelMaxWidth}
          />
        );
      })}

      {laid &&
        drawnMarkers.map((marker) => {
          const position = laid.markerPos.get(marker.id);
          if (!position) return null;
          const index = markerIndex.get(marker.station) ?? 0;
          markerIndex.set(marker.station, index + 1);
          return (
            <StationMarkerMesh
              key={marker.id}
              marker={marker}
              position={position}
              geometries={geometries}
              reducedMotion={reducedMotion}
              index={index}
              labelMaxWidth={labelMaxWidth}
            />
          );
        })}

      <CameraRig
        graph={g}
        stage={stage}
        cameraPreset={cameraPreset}
        focusNodeId={focusNodeId}
        resetSignal={resetSignal}
        reducedMotion={reducedMotion}
        frame={laid?.frame ?? null}
      />
    </>
  );
}
