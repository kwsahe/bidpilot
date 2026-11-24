"use client";

/**
 * 3D 노드 — 평면 기호 하나가 카메라를 향한다 (21차 · prompt_11 §3-3 · §4-B).
 *
 * 공고 ● · 요구사항 ▪ · 근거 ▫ · 제안서 ─ · 점검 ⚠ · 발견 ⚠ — 색은 판정 뜻만(`nodeHex`).
 * 예전의 발광 셸 · 내부 코어 · 궤도 링 · 경고 후광 · 맥동은 없앴다. 남긴 것: 등장(0 → 1) · 선택 링 · hover/선택 확대.
 *
 * 정거장 지도(입찰)에서는 밝기 단계(`tier`)를 받는다 — 지금 정거장 온전 · 옆 반투명 · 나머지는 작고 흐린 점.
 */

import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import {
  findingNodeId,
  isSevere,
  type CosmosGraph,
  type CosmosNode,
  type FindingView,
  type WorkflowStage,
} from "@/lib/cosmos/graph";
import { SEVERITY_LABELS, truncate } from "@/lib/cosmos/format";
import { verdictPill } from "@/lib/cosmos/itemTypes";
import type { KeyLabel } from "@/lib/cosmos/guidedFlow";
import type { StationTier } from "@/lib/cosmos/stations";
import type { CosmosVocabulary } from "@/lib/cosmos/vocabulary";

import {
  APPEAR_DURATION,
  APPEAR_STAGGER,
  LABEL_PRIORITY,
  MATERIAL_DAMP_LAMBDA,
  SELECTION_RING,
  type Vec3,
} from "./constants";
import { nodeHex, type CosmosGeometries } from "./geometries";
import {
  DemoTag,
  FloatingLabel,
  KeyLabelChip,
  LabelChip,
  NoticeCard,
  useCameraDraggingRef,
  type LabelAnchor,
} from "./labels";
import { RiskTooltipCard } from "./tooltip";

/** 강조 스케일: 선택 1.12 / hover 1.08. */
const EMPHASIS_SCALE = { hover: 1.08, selected: 1.12 } as const;

/** 밝기 단계별 불투명도 · 크기. 단계가 없으면(지원사업 지도) 온전하게. */
export const TIER_OPACITY: Record<StationTier, number> = { current: 1, near: 0.55, far: 0.35 };
const TIER_SCALE: Record<StationTier, number> = { current: 1, near: 0.85, far: 0.6 };
/** 강조(선택한 노드의 이웃) 밖 노드의 불투명도 배수 — 지금 정거장 안에서만 쓴다. */
const DIMMED_OPACITY = 0.3;

/** 위험 툴팁 오프셋 — 일반 라벨보다 위에 두어 둘 다 보이게 한다. */
const TOOLTIP_OFFSET: Record<"requirement" | "finding", Vec3> = {
  requirement: [0, 1.4, 0],
  finding: [0, 1.2, 0],
};

/** 선택 링은 hover 대상이 아니다. */
function noRaycast(): void {}

function easeOutCubic(t: number): number {
  const u = 1 - t;
  return 1 - u * u * u;
}

/** 평면 기호 재질 — 조명 없이 그 색 그대로(판정 뜻만 전하는 색이 조명으로 바뀌지 않게). */
export function createFlatMaterial(): THREE.MeshBasicMaterial {
  return new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
}

/** 재질 값 바꾸기 — 렌더 밖(효과·프레임 루프)에서만 부른다. 훅이 준 값을 컴포넌트 안에서 직접 고치지 않는다(lint). */
export function setFlatColor(material: THREE.MeshBasicMaterial, hex: string): void {
  material.color.set(hex);
}
export function setFlatOpacity(material: THREE.Material, opacity: number): void {
  material.opacity = opacity;
}

// ---------------------------------------------------------------------------
// 노드 메시
// ---------------------------------------------------------------------------

export interface CosmosNodeMeshProps {
  node: CosmosNode;
  graph: CosmosGraph;
  stage: WorkflowStage;
  geometries: CosmosGeometries;
  /** 같은 종류 안에서의 순번 — 등장 stagger용 */
  orbitIndex: number;
  hovered: boolean;
  selected: boolean;
  highlighted: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
  /** 남겨 둔다 — 유휴 애니메이션이 없어졌으므로 쓰지 않는다 */
  paused?: boolean;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  /** 기본 화면에 항상 보이는 핵심 라벨 (지원사업 지도). 없으면 일반 라벨 정책. */
  keyLabel?: KeyLabel;
  /** 이 노드가 화면에 적는 말 (Cosmos3D 가 기본값 BID_VOCABULARY 를 채워 넘긴다) */
  vocabulary: CosmosVocabulary;
  /** 정거장 지도의 밝기 단계. 없으면 지원사업 궤도 지도(예전 라벨 정책). */
  tier?: StationTier;
  /** 지금 정거장 긴 라벨의 최대 폭(px) — 두 열이면 좁다 */
  labelMaxWidth?: number;
  /** 라벨을 달지 않는다 — 나머지 정거장 · 점이 많은 옆 정거장(정거장 이름과 건수가 말한다) */
  quiet?: boolean;
}

export const CosmosNodeMesh = memo(function CosmosNodeMesh({
  node,
  graph,
  stage,
  geometries,
  orbitIndex,
  hovered,
  selected,
  highlighted,
  dimmed,
  reducedMotion,
  onSelect,
  onHover,
  keyLabel,
  vocabulary,
  tier,
  labelMaxWidth,
  quiet = false,
}: CosmosNodeMeshProps) {
  const groupRef = useRef<THREE.Group>(null);
  const faceRef = useRef<THREE.Group>(null);
  const selectionRef = useRef<THREE.Mesh>(null);
  /** 등장 애니메이션 시작 시각 (clock 기준). null이면 아직 첫 프레임 전. */
  const appearStartRef = useRef<number | null>(null);
  const emphasisRef = useRef(1);
  const opacityRef = useRef(1);
  const selectionOpacityRef = useRef(0);
  const hoveringRef = useRef(false);
  const draggingRef = useCameraDraggingRef();
  const onHoverRef = useRef(onHover);
  useEffect(() => {
    onHoverRef.current = onHover;
  }, [onHover]);

  const hex = nodeHex(node);
  const shape = geometries.node[node.kind];
  const material = useMemo(() => createFlatMaterial(), []);
  const selectionMaterial = useMemo(() => createFlatMaterial(), []);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => selectionMaterial.dispose(), [selectionMaterial]);
  useEffect(() => {
    setFlatColor(material, hex);
    setFlatColor(selectionMaterial, hex);
  }, [material, selectionMaterial, hex]);

  // 마운트 직후 첫 렌더 전에 scale 0 (reducedMotion이면 첫 useFrame에서 즉시 1).
  useLayoutEffect(() => {
    groupRef.current?.scale.setScalar(0);
  }, []);

  // 언마운트 시 커서·hover 상태 정리 (자체 setState 없음).
  useEffect(() => {
    return () => {
      if (hoveringRef.current) {
        hoveringRef.current = false;
        document.body.style.cursor = "";
        onHoverRef.current(null);
      }
    };
  }, []);

  const tierOpacity = tier ? TIER_OPACITY[tier] : 1;
  const tierScale = tier ? TIER_SCALE[tier] : 1;

  useFrame((state, delta) => {
    const group = groupRef.current;
    if (!group) return;
    const dt = Math.min(delta, 0.1);

    // 등장 (scale 0→1, 0.35s ease-out, 같은 종류 안에서 30ms stagger)
    let appear = 1;
    if (reducedMotion) {
      appearStartRef.current = Number.NEGATIVE_INFINITY;
    } else {
      if (appearStartRef.current === null) {
        appearStartRef.current = state.clock.elapsedTime + orbitIndex * APPEAR_STAGGER;
      }
      const progress = (state.clock.elapsedTime - appearStartRef.current) / APPEAR_DURATION;
      appear = progress <= 0 ? 0 : progress >= 1 ? 1 : easeOutCubic(progress);
    }

    const targetEmphasis = selected ? EMPHASIS_SCALE.selected : hovered ? EMPHASIS_SCALE.hover : 1;
    emphasisRef.current = reducedMotion
      ? targetEmphasis
      : THREE.MathUtils.damp(emphasisRef.current, targetEmphasis, MATERIAL_DAMP_LAMBDA, dt);
    group.scale.setScalar(appear * emphasisRef.current * tierScale);

    // 기호는 언제나 카메라를 향한다 — 드래그로 돌려도 같은 모양으로 읽힌다.
    faceRef.current?.quaternion.copy(state.camera.quaternion);

    const targetOpacity = tierOpacity * (dimmed ? DIMMED_OPACITY : 1);
    opacityRef.current = reducedMotion
      ? targetOpacity
      : THREE.MathUtils.damp(opacityRef.current, targetOpacity, MATERIAL_DAMP_LAMBDA, dt);
    setFlatOpacity(material, opacityRef.current);

    const selection = selectionRef.current;
    if (selection) {
      const targetSelection = selected ? SELECTION_RING.opacity : 0;
      selectionOpacityRef.current = reducedMotion
        ? targetSelection
        : THREE.MathUtils.damp(selectionOpacityRef.current, targetSelection, MATERIAL_DAMP_LAMBDA, dt);
      const visible = selectionOpacityRef.current > 0.01;
      if (selection.visible !== visible) selection.visible = visible;
      if (visible) setFlatOpacity(selectionMaterial, selectionOpacityRef.current);
    }
  });

  const handlePointerOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    // 지도를 끄는 동안 포인터가 지나가는 노드는 hover 가 아니다 — 칩이 글자로 펼쳐졌다 접힌다 (ISSUE-141).
    if (draggingRef?.current) return;
    hoveringRef.current = true;
    document.body.style.cursor = "pointer";
    onHover(node.id);
  };
  // 끌기를 노드 위에서 놓으면 R3F 는 이미 hover 로 세어 pointerover 를 다시 부르지 않는다 — 첫 움직임에서 잡는다 (22차 검토).
  const handlePointerMove = (event: ThreeEvent<PointerEvent>) => {
    if (!hoveringRef.current && !draggingRef?.current) handlePointerOver(event);
  };
  const handlePointerOut = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    hoveringRef.current = false;
    document.body.style.cursor = "";
    onHover(null);
  };
  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect(selected ? null : node.id);
  };

  const [x, y, z] = node.position;
  const label = renderLabel({
    node,
    graph,
    stage,
    hovered,
    selected,
    highlighted,
    dimmed,
    reducedMotion,
    // requirement 라벨은 hover로 뜨므로 stagger 없이, 상시 라벨은 노드 등장과 맞춘다.
    appearDelay: node.kind === "requirement" ? 0 : orbitIndex * APPEAR_STAGGER,
    palette: hex,
    keyLabel,
    vocabulary,
    tier,
    radius: shape.radius,
    labelMaxWidth,
    quiet,
    // 정거장 지도의 이름표는 눌러서 고른다(27차 검수 R27D-OWN-02) — 기호와 같은 동작.
    onPick: tier !== undefined ? () => onSelect(selected ? null : node.id) : undefined,
  });
  // hover가 없는 터치 환경에서도 "왜 위험한지"를 볼 수 있게 선택 시에도 툴팁을 띄운다.
  // 정거장 지도는 예외 — 고른 발견은 이미 긴 라벨과 상세 패널에 나오고, 툴팁이 지금 정거장 라벨을 덮는다(21차 발표 8장면).
  const tooltip =
    hovered || (selected && node.kind === "finding" && !tier) ? renderRiskTooltip(node, graph, reducedMotion) : null;

  return (
    <group position={[x, y, z]}>
      <group ref={groupRef} onPointerOver={handlePointerOver} onPointerMove={handlePointerMove} onPointerOut={handlePointerOut} onClick={handleClick}>
        <group ref={faceRef}>
          {shape.parts.map((geometry, index) => (
            <mesh key={index} geometry={geometry} material={material} scale={shape.scale} renderOrder={1} />
          ))}
          {/* 선택 링 (선택 시에만 보임) */}
          <mesh
            ref={selectionRef}
            geometry={geometries.selectionRing}
            material={selectionMaterial}
            scale={shape.radius * SELECTION_RING.scale}
            visible={false}
            raycast={noRaycast}
            renderOrder={2}
          />
        </group>
      </group>
      {label}
      {tooltip}
    </group>
  );
});

// ---------------------------------------------------------------------------
// 위험 툴팁 — finding 노드, warning 상태 요구사항 hover 시
// ---------------------------------------------------------------------------

function riskFindingOf(node: CosmosNode, graph: CosmosGraph): FindingView | null {
  if (node.kind === "finding") return graph.findingByNodeId.get(node.id) ?? null;
  if (node.kind === "requirement" && node.state === "warning") {
    const first = graph.requirementByNodeId.get(node.id)?.findings[0];
    return first ? (graph.findingByNodeId.get(findingNodeId(first.id)) ?? null) : null;
  }
  return null;
}

function renderRiskTooltip(node: CosmosNode, graph: CosmosGraph, reducedMotion: boolean) {
  if (node.kind !== "finding" && node.kind !== "requirement") return null;
  const finding = riskFindingOf(node, graph);
  if (!finding) return null;
  return (
    <FloatingLabel
      nodePosition={node.position}
      offset={TOOLTIP_OFFSET[node.kind]}
      anchor="center"
      dimmed={false}
      reducedMotion={reducedMotion}
      appearDelay={0}
    >
      <RiskTooltipCard finding={finding} />
    </FloatingLabel>
  );
}

// ---------------------------------------------------------------------------
// 라벨 정책
//  정거장 지도: 지금 정거장 → 긴 라벨(번호로 줄이지 않는다) · 옆 → 짧은 라벨 · 나머지 → 없음(점과 정거장 이름)
//  지원사업 지도: 기본 짧은 라벨, hover·선택·강조·핵심 라벨에서 긴 라벨
// ---------------------------------------------------------------------------

interface LabelInput {
  node: CosmosNode;
  graph: CosmosGraph;
  stage: WorkflowStage;
  hovered: boolean;
  selected: boolean;
  highlighted: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
  appearDelay: number;
  palette: string;
  keyLabel?: KeyLabel;
  vocabulary: CosmosVocabulary;
  tier?: StationTier;
  radius: number;
  labelMaxWidth?: number;
  quiet: boolean;
  /** 이름표를 눌러 고른다 — 정거장 지도의 지금 정거장 긴 이름표만 */
  onPick?: () => void;
}

/** 노드 로컬 좌표 기준 라벨 오프셋 (지원사업 궤도 지도). */
function labelPlacement(kind: CosmosNode["kind"]): { offset: Vec3; anchor: LabelAnchor } {
  switch (kind) {
    case "notice":
      return { offset: [0.9, 0.15, 0], anchor: "left" };
    case "requirement":
      return { offset: [0, 0.6, 0], anchor: "center" };
    case "evidence":
      return { offset: [0, -0.7, 0], anchor: "center" };
    case "proposal":
      return { offset: [0.8, 0, 0], anchor: "left" };
    case "audit":
      return { offset: [0, 0.9, 0], anchor: "center" };
    case "finding":
      return { offset: [0, -0.6, 0], anchor: "center" };
    case "requirement-group":
      return { offset: [0, 0.8, 0], anchor: "center" };
    case "finding-group":
      return { offset: [0, -0.8, 0], anchor: "center" };
  }
}

/** 짧은 라벨의 이름 길이 상한 (prompt_01 §4-A-1: 「이름 ≤ 14자」). */
const SHORT_LABEL_MAX = 14;

/**
 * 짧은 라벨 뒤에 붙는 **상태 조각**.
 *
 * 수치는 여기서 새로 세지 않는다 — 어휘 객체(`proposalBadge`·`auditBadge`)와 노드가
 * 이미 들고 있는 값만 읽는다. 실행하지 않은 것을 「0」으로 적지 않는다 — 값이 없으면 null.
 */
function shortBadge(node: CosmosNode, graph: CosmosGraph, vocabulary: CosmosVocabulary): string | null {
  switch (node.kind) {
    case "requirement-group":
    case "finding-group":
      return node.groupCount !== undefined ? `${node.groupCount}건` : null;
    case "proposal":
      return vocabulary.proposalBadge(graph);
    case "audit":
      return vocabulary.auditBadge(graph);
    case "requirement":
      return node.code ?? node.requirementId ?? null;
    case "finding":
      if (node.state === "resolved") return "해결";
      return node.severity && isSevere({ severity: node.severity }) ? SEVERITY_LABELS[node.severity] : null;
    case "evidence":
    case "notice":
      return null;
  }
}

function shortContent(node: CosmosNode, graph: CosmosGraph, vocabulary: CosmosVocabulary, palette: string, max: number) {
  const badge = shortBadge(node, graph, vocabulary);
  return (
    <LabelChip dot={palette}>
      <span>{truncate(node.short || node.label, max)}</span>
      {badge !== null && <span className="ml-1.5 font-mono text-[13px] tabular-nums text-cosmos-secondary">{badge}</span>}
    </LabelChip>
  );
}

function longContent(input: LabelInput, emphasis: boolean) {
  const { node, graph, stage, vocabulary } = input;
  // 정거장 지도(입찰)에서는 이름표 안 ● 를 빼고(기호를 이미 색으로 그렸다) 호박 · 빨강이면 끝에 같은 색 낱말을 붙인다
  // (27차 §3-D-4 · 6). 지원사업 지도(tier 없음)는 그대로다.
  const station = input.tier !== undefined;
  const palette = station ? undefined : input.palette;
  const verdict = station ? verdictPill(node.state) : null;
  switch (node.kind) {
    case "notice":
      return <NoticeCard graph={graph} stage={stage} node={node} vocabulary={vocabulary} />;
    case "requirement":
      return (
        <LabelChip dot={palette} emphasis={emphasis} verdict={verdict}>
          <span>{node.short}</span>
          {/* 잘린 코드(SCH- · REQ- …)는 지도에서 빼고 상세 · 목록에만 둔다(27차 §3-D-6). */}
          {!station && <span className="ml-1.5 font-mono text-[13px] text-cosmos-muted">{node.code ?? node.requirementId}</span>}
        </LabelChip>
      );
    case "evidence":
      return (
        <LabelChip dot={palette} emphasis={emphasis} verdict={verdict}>
          {node.short}
        </LabelChip>
      );
    case "proposal":
    case "audit": {
      // 수치도 꼬리표도 어휘가 정한다. null 이면 수치 span 자체를 그리지 않는다.
      const badge = node.kind === "proposal" ? vocabulary.proposalBadge(graph) : vocabulary.auditBadge(graph);
      return (
        <LabelChip dot={palette} emphasis={emphasis} verdict={verdict}>
          {node.short}
          {badge !== null && <span className="ml-1.5 font-mono text-[13px] tabular-nums text-cosmos-secondary">{badge}</span>}
          {/* 실제로 생성한 결과면 데모 꼬리표를 붙이지 않는다 — 실검사 결과를 데모로 읽히게 하면 안 된다 */}
          {vocabulary.showDemoTag(graph, node.kind) ? <DemoTag /> : null}
        </LabelChip>
      );
    }
    /* 묶음 둘: 긴 라벨은 줄인 이름 대신 **온전한 이름**. 건수 조각을 붙이지 않는다 — `label` 이 이미
       「과업 17건」처럼 건수로 끝난다 (prompt_04 §3-A-5). */
    case "requirement-group":
    case "finding-group":
      return (
        <LabelChip dot={palette} emphasis={emphasis} verdict={verdict}>
          {node.label}
        </LabelChip>
      );
    case "finding":
      // 높음 이상은 이미 빨강 심각도 알약(「높음」 · 「참가 차단」)이 같은 색 낱말이다 — 판정 알약은 호박(확인 필요)일 때만.
      return (
        <LabelChip dot={palette} emphasis={emphasis} verdict={node.state === "check" ? verdict : null}>
          {node.short}
          {node.state === "resolved" ? (
            // 해결됨 = 충족(청록) — 지도 기호와 같은 색(27차 §3-D-4 · 예전에는 초록).
            <span className="ml-1.5 rounded-[3px] border border-cosmos-cyan/50 bg-cosmos-cyan/10 px-1 py-px text-[13px] font-semibold tracking-[0.08em] text-cosmos-cyan">
              해결
            </span>
          ) : (
            node.severity &&
            isSevere({ severity: node.severity }) && (
              <span className="ml-1.5 rounded-[3px] border border-cosmos-red/50 bg-cosmos-red/10 px-1 py-px text-[13px] font-semibold tracking-[0.08em] text-cosmos-red">
                {SEVERITY_LABELS[node.severity]}
              </span>
            )
          )}
        </LabelChip>
      );
  }
}

function renderLabel(input: LabelInput) {
  const { node, graph, hovered, selected, highlighted, dimmed, reducedMotion, appearDelay, palette, keyLabel, vocabulary, tier } = input;
  const emphasis = hovered || selected;

  if (tier) {
    // 정거장 지도 — 지금 정거장만 그린다(27차 §3-D-1). 다른 정거장 노드는 이 부품까지 오지 않지만, 와도 이름표는 없다.
    if (tier !== "current") return null;
    return (
      <FloatingLabel
        nodePosition={node.position}
        // 긴 라벨이 노드 오른쪽에 붙는다(격자 열 안에서 읽힌다).
        offset={[input.radius + (node.kind === "notice" ? 0.35 : 0.25), 0, 0]}
        // 공고 카드는 키가 크다(약 260px) — 세로 가운데에 두면 위쪽 정거장 이름을 덮는다. 윗변을 노드 높이에.
        anchor={node.kind === "notice" ? "top-left" : "left"}
        dimmed={dimmed}
        reducedMotion={reducedMotion}
        appearDelay={appearDelay}
        labelId={node.id}
        variant="long"
        kind={node.kind}
        tone={palette}
        active={emphasis}
        alwaysOn
        current
        station={node.stage}
        maxWidth={input.labelMaxWidth}
        onPick={input.onPick}
      >
        {longContent(input, emphasis)}
      </FloatingLabel>
    );
  }

  const active = hovered || selected || highlighted;
  const isKey = keyLabel !== undefined;
  /**
   * 짧은 라벨로 그릴 것인가 (ISSUE-109 · prompt_01 §4-A) — 기본은 한 줄짜리 짧은 라벨, 긴 라벨(카드·핵심 라벨)은
   * hover·선택·강조에서만 편다. 「라벨이 없는 점」은 0 이어야 한다.
   */
  const short = !(active || isKey);
  const { offset, anchor } = labelPlacement(node.kind);

  let content: React.ReactNode;
  if (short && node.kind !== "notice") {
    // 공고(notice)는 예외다 — 중앙 카드가 곧 그 노드의 라벨이라 이미 글자가 있다.
    content = shortContent(node, graph, vocabulary, palette, SHORT_LABEL_MAX);
  } else if (isKey && node.kind !== "notice") {
    content = (
      <KeyLabelChip
        title={keyLabel.title}
        subtitle={keyLabel.subtitle}
        code={keyLabel.code}
        step={keyLabel.step}
        dot={palette}
        tone={palette}
        active={emphasis}
      />
    );
  } else {
    content = longContent(input, emphasis);
  }

  // 상시 라벨만 충돌 회피에 등록한다 (requirement hover 라벨은 등록하지 않는다). 핵심 라벨은 항상 등록.
  const registered = node.kind !== "requirement" || isKey;

  return (
    <FloatingLabel
      nodePosition={node.position}
      offset={offset}
      anchor={anchor}
      dimmed={dimmed}
      reducedMotion={reducedMotion}
      appearDelay={appearDelay}
      labelId={registered ? node.id : undefined}
      variant={short ? "short" : "long"}
      priority={isKey ? LABEL_PRIORITY[node.kind] + 500 : undefined}
      kind={node.kind}
      tone={palette}
      active={emphasis}
      alwaysOn={registered}
      persistent={isKey}
      dimmedOpacity={isKey ? 0.6 : undefined}
    >
      {content}
    </FloatingLabel>
  );
}
