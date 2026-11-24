"use client";

/**
 * 사업기회 레이더 — 3D 씬 (react-three-fiber).
 *
 * RadarShell 은 이 컴포넌트를 `next/dynamic(..., { ssr: false })` 로만 불러온다.
 * 좌표·크기·색은 2D SVG와 **같은** `lib/radar/layout.ts` 계산을 쓴다 — 두 화면은 같은 그림이다.
 *
 * 좌표는 전부 단위 좌표(반지름 0~1)로 두고, 캔버스 크기에 맞춘 배율 하나만 그룹에 건다.
 * 그래서 레이더가 언제나 캔버스의 짧은 변을 거의 다 채운다(노드가 가운데로 뭉치지 않는다).
 *
 * 움직임 규칙: 자동 회전 없음(멀미), 카메라 이동 없음. 마감 임박 링만 조용히 맥동한다.
 */

import { Html, Line } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { ControlTowerIcon } from "@/components/icons/aviation";
import { COSMOS_HEX, cosmosHex } from "@/lib/cosmos/theme";
import {
  BLIP_FLOOR,
  RADAR_RADIUS_MAX,
  SWEEP_ARC_DEG,
  SWEEP_SECONDS,
  bandLabelAngleAt,
  blipIntensity,
  radarAriaLabel,
  ringPoints,
  shouldShowLabel,
  sweepAlphaAt,
  type RadarLayout,
  type RadarNode,
  type RadarSceneProps,
} from "@/lib/radar/layout";
import { UNSCORED } from "@/lib/terms";

/** 레이더 원반 기울기(라디안). 너무 눕히면 "중심까지의 거리"가 왜곡되므로 얕게 준다. */
const DISC_TILT = -0.34;
/** 카메라 거리 (원근만 주고 움직이지 않는다). */
const CAMERA_Z = 13;
/** 라벨 여백까지 포함한 가로·세로 여유. 1에 가까울수록 레이더가 캔버스를 꽉 채운다. */
const MARGIN_X = 1.1;
const MARGIN_Y = 1.06;
/** 관제탑 글리프 높이 — 레이더 반지름(=1) 대비. 안쪽 띠의 접점을 덮지 않을 만큼만. */
const TOWER_UNITS = 0.17;

type Vec3 = [number, number, number];

function nodePosition(node: RadarNode): Vec3 {
  return [node.x, node.y, node.z];
}

// ---------------------------------------------------------------------------
// 공유 지오메트리 (단위 좌표 기준: 반지름 1짜리를 만들어 두고 노드마다 scale 만 준다)
// ---------------------------------------------------------------------------

interface RadarGeometries {
  /** 기체 실루엣(평면). 출처와 무관하게 **모든 접점이 같은 모양**을 쓴다. */
  plane: THREE.ShapeGeometry;
  centerShell: THREE.SphereGeometry;
  centerCore: THREE.SphereGeometry;
  /** 스윕 빔 부채꼴. 꼭짓점 알파로 «선행 엣지는 밝고 뒤로 사그라드는» 꼬리를 만든다. */
  sweep: THREE.BufferGeometry;
}

/**
 * 위에서 본 여객기 윤곽 — `components/icons/aviation.tsx` 의 PLANE_PATH 와 같은 비례다.
 * 24 격자 좌표를 중심 기준(±1 남짓)으로 옮겨 적었다. 기수는 +Y.
 * 두 화면이 같은 실루엣을 써야 하므로 비례를 바꿀 때는 양쪽을 함께 고친다.
 */
const PLANE_OUTLINE: Array<[number, number]> = [
  [0, 1.0],
  [0.162, 0.67],
  [0.17, 0.28],
  [0.95, -0.218],
  [0.95, -0.38],
  [0.17, -0.138],
  [0.17, -0.588],
  [0.46, -0.808],
  [0.46, -0.918],
  [0, -0.79],
  [-0.46, -0.918],
  [-0.46, -0.808],
  [-0.17, -0.588],
  [-0.17, -0.138],
  [-0.95, -0.38],
  [-0.95, -0.218],
  [-0.17, 0.28],
  [-0.162, 0.67],
];

function planeGeometry(): THREE.ShapeGeometry {
  const shape = new THREE.Shape();
  PLANE_OUTLINE.forEach(([x, y], index) => {
    if (index === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  });
  shape.closePath();
  return new THREE.ShapeGeometry(shape);
}

/**
 * 스윕 빔 부채꼴.
 *
 * 각도 0(= 3시 방향)이 **선행 엣지**이고 +방향(반시계)으로 꼬리가 누워 있다.
 * 그룹을 시계방향으로 굴리면(rotation.z 음수) 꼬리가 자연히 뒤로 끌린다.
 *
 * 알파를 꼭짓점에 실어 보낸다 — three.js 는 color 속성이 4성분이면 알파까지 읽는다.
 * 그래야 셰이더를 새로 쓰거나 텍스처를 만들지 않고 그라데이션을 낼 수 있다.
 */
function sweepGeometry(radius: number, arcDeg: number, segments = 40): THREE.BufferGeometry {
  const arc = (arcDeg * Math.PI) / 180;
  const tint = new THREE.Color(COSMOS_HEX.cyan);
  const positions: number[] = [];
  const colors: number[] = [];
  // 꼬리 알파는 layout.sweepAlphaAt 한 곳에서만 정한다 — 2D 스코프가 같은 식을 쓴다.
  const alphaAt = sweepAlphaAt;
  const push = (x: number, y: number, alpha: number) => {
    positions.push(x, y, 0);
    colors.push(tint.r, tint.g, tint.b, alpha);
  };
  for (let i = 0; i < segments; i += 1) {
    const t0 = i / segments;
    const t1 = (i + 1) / segments;
    const a0 = t0 * arc;
    const a1 = t1 * arc;
    push(0, 0, alphaAt((t0 + t1) / 2));
    push(Math.cos(a0) * radius, Math.sin(a0) * radius, alphaAt(t0));
    push(Math.cos(a1) * radius, Math.sin(a1) * radius, alphaAt(t1));
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 4));
  return geometry;
}

/** 씬에서 **한 번만** 만들고 모든 노드가 공유한다. 언마운트 때 dispose. */
function useRadarGeometries(): RadarGeometries {
  const geometries = useMemo<RadarGeometries>(
    () => ({
      plane: planeGeometry(),
      centerShell: new THREE.SphereGeometry(0.115, 32, 24),
      centerCore: new THREE.SphereGeometry(0.05, 20, 16),
      sweep: sweepGeometry(RADAR_RADIUS_MAX, SWEEP_ARC_DEG),
    }),
    [],
  );
  useEffect(() => {
    const owned: THREE.BufferGeometry[] = Object.values(geometries);
    return () => {
      for (const geometry of owned) geometry.dispose();
    };
  }, [geometries]);
  return geometries;
}

/** 노드를 감싸는 원형 링의 점 배열 (XY 평면). */
function circlePoints(radius: number, segments = 48): Vec3[] {
  return ringPoints(radius, segments).map(([x, y]): Vec3 => [x, y, 0]);
}

// ---------------------------------------------------------------------------
// 부분 컴포넌트
// ---------------------------------------------------------------------------

/** 마감 경계 안내 링. 회전하지 않는다 — 거리 해석을 흐리지 않기 위해 완전히 고정한다. */
function GuideRings({ layout }: { layout: RadarLayout }) {
  const rings = useMemo(
    () => layout.rings.map((ring) => circlePoints(ring.radius, 96)),
    [layout.rings],
  );
  return (
    <group>
      {rings.map((points, index) => (
        <Line
          key={layout.rings[index].days}
          points={points}
          color={COSMOS_HEX.slate}
          lineWidth={1}
          transparent
          opacity={0.6}
          dashed
          dashSize={0.05}
          gapSize={0.045}
        />
      ))}
    </group>
  );
}

/**
 * 도는 스윕 빔 — 부채꼴 꼬리 + 선행 엣지 선.
 *
 * **장식이다.** 실시간 탐지를 뜻하지 않는다. 그래서 눈금·라벨보다 **아래**에 깔고(renderOrder -1)
 * 옅게 더한다 — 빔이 접점이나 글자를 덮으면 읽는 데 방해가 된다.
 * reduced motion 이면 아예 그리지 않는다 (2D 와 같은 규칙).
 */
function SweepBeam({ geometries }: { geometries: RadarGeometries }) {
  const group = useRef<THREE.Group>(null);
  const edge = useMemo<Vec3[]>(() => [[0, 0, 0], [RADAR_RADIUS_MAX, 0, 0]], []);

  useFrame((state) => {
    if (!group.current) return;
    // 화면에서 시계방향 = 수학 좌표계에서 음의 회전. 2D SVG 와 방향을 맞춘다.
    group.current.rotation.z = -state.clock.elapsedTime * ((Math.PI * 2) / SWEEP_SECONDS);
  });

  return (
    <group ref={group} renderOrder={-1}>
      <mesh geometry={geometries.sweep}>
        <meshBasicMaterial
          vertexColors
          transparent
          depthTest={false}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.DoubleSide}
          toneMapped={false}
        />
      </mesh>
      {/* 선행 엣지 — 「한 바퀴씩 도는 선」 그 자체 */}
      <Line
        points={edge}
        color={COSMOS_HEX.cyan}
        lineWidth={1.6}
        transparent
        opacity={0.5}
        depthTest={false}
      />
    </group>
  );
}

/**
 * 출처 섹터 이름 — 레이더의 «방향»이 뜻하는 것.
 * 2D 스코프와 같은 설정(SOURCE_SECTORS)을 읽으므로 두 화면이 서로 다른 규칙을 말하지 않는다.
 */
function SectorLabels({ layout, compact }: { layout: RadarLayout; compact: boolean }) {
  return (
    <>
      {layout.sectors.map((sector) => {
        const angle = (sector.spec.centerDeg * Math.PI) / 180;
        const radius = RADAR_RADIUS_MAX + 0.16;
        return (
          <Html
            key={`sector-${sector.sourceType}`}
            center
            position={[Math.cos(angle) * radius, Math.sin(angle) * radius, 0]}
            zIndexRange={[12, 6]}
            style={{ pointerEvents: "none" }}
          >
            <span
              className={`flex flex-col items-center whitespace-nowrap ${compact ? "text-[12px]" : "text-[12px]"}`}
              style={{ opacity: sector.count === 0 ? 0.5 : 1 }}
            >
              <span className="font-semibold" style={{ color: sector.color }}>
                {compact ? sector.spec.label.split(" ")[0] : sector.spec.label}
              </span>
              <span className="font-mono tabular-nums text-cosmos-muted">{sector.count}건</span>
            </span>
          </Html>
        );
      })}
    </>
  );
}

/** 띠 이름 — 「사흘 안」·「이번 주」처럼 시간으로 읽는다. 섹터 사이 빈 각도에 적는다. */
function BandLabels({ layout, compact }: { layout: RadarLayout; compact: boolean }) {
  return (
    <>
      {layout.rings.map((ring, index) => {
        // 라벨을 한 칸씩 벌린다 — 같은 방향에 두면 서로 겹친다.
        const angle = bandLabelAngleAt(layout, index);
        return (
        <Html
          key={`band-${ring.days}`}
          center
          position={[Math.cos(angle) * ring.labelRadius, Math.sin(angle) * ring.labelRadius, 0]}
          zIndexRange={[12, 6]}
          style={{ pointerEvents: "none" }}
        >
          <span
            className={`whitespace-nowrap rounded-full border border-cosmos-border bg-cosmos-bg/85 px-1.5 py-0.5 text-cosmos-muted backdrop-blur ${
              compact ? "text-[12px]" : "text-[12px]"
            }`}
          >
            {ring.label}
          </span>
        </Html>
        );
      })}
    </>
  );
}

/**
 * 중심 = 현재 선택 회사 = **관제탑**. 항상 맨 위에 그려 다른 노드에 가려지지 않게 한다.
 *
 * 관제탑 글리프는 `<Html>` 로 세운다. 원반이 19.5°밖에 안 기울어 있어서 로컬 +Z 로 세우면
 * 거의 정면에서 보여 납작해지고, 원반에 눕히면 «위에서 본 건물»이 되어 관제탑으로 안 읽힌다.
 * 화면을 향해 똑바로 선 빌보드가 «원반 위에 서 있는 탑»으로 읽히고,
 * 덤으로 2D 스코프와 **완전히 같은 실루엣**(같은 path)을 쓴다.
 */
function CenterNode({
  geometries,
  companyName,
  compact,
  reducedMotion,
  towerPx,
}: {
  geometries: RadarGeometries;
  companyName: string;
  compact: boolean;
  reducedMotion: boolean;
  /** 관제탑 글리프의 화면 크기(px). 씬 배율에서 유도한다 — 아래 TOWER_UNITS 주석 참고. */
  towerPx: number;
}) {
  const pad = useRef<THREE.Mesh>(null);

  // 탑이 선 자리가 조용히 맥동한다 — 전파를 내보내는 쪽이라는 표시. 스윕과 달리 방향이 없다.
  useFrame((state) => {
    if (reducedMotion || !pad.current) return;
    const material = pad.current.material as THREE.MeshStandardMaterial;
    material.opacity = 0.3 + (Math.sin(state.clock.elapsedTime * 1.7) + 1) * 0.09;
  });

  return (
    <group renderOrder={4}>
      <mesh ref={pad} geometry={geometries.centerShell}>
        <meshStandardMaterial
          color={COSMOS_HEX.blue}
          emissive={COSMOS_HEX.blue}
          emissiveIntensity={0.5}
          transparent
          opacity={0.4}
          depthTest={false}
          roughness={0.4}
          metalness={0.1}
        />
      </mesh>
      <mesh geometry={geometries.centerCore}>
        <meshBasicMaterial color={COSMOS_HEX.cyan} toneMapped={false} depthTest={false} />
      </mesh>
      {/* 관제탑 — 받침(위 구체) 위에 서도록 살짝 들어 올린다 */}
      <Html center position={[0, 0, 0]} zIndexRange={[31, 21]} style={{ pointerEvents: "none" }}>
        <div style={{ transform: "translateY(-46%)" }}>
          <ControlTowerIcon
            size={towerPx}
            strokeWidth={1.4}
            className="text-cosmos-cyan drop-shadow-[0_0_6px_rgba(34,211,238,0.45)]"
          />
        </div>
      </Html>
      <Html center position={[0, -0.2, 0]} zIndexRange={[30, 20]} style={{ pointerEvents: "none" }}>
        <div className="whitespace-nowrap rounded-md border border-cosmos-border bg-cosmos-bg/90 px-2 py-1 text-center backdrop-blur">
          <span className={`block font-semibold text-cosmos-text ${compact ? "text-[12px]" : "text-[12px]"}`}>
            {companyName}
          </span>
          <span className="block text-[12px] text-cosmos-muted">우리 회사 (가운데 기준)</span>
        </div>
      </Html>
    </group>
  );
}

/**
 * 마감 임박 링.
 * 움직임을 켠 상태에서는 D-3 이하만 맥동하고, reduced motion 이면 pulse 없이
 * **정적 링 두께**로 임박도를 나타낸다 (정보가 사라지지 않게).
 */
function UrgencyRing({ node, reducedMotion }: { node: RadarNode; reducedMotion: boolean }) {
  const group = useRef<THREE.Group>(null);
  const radius = node.unitRadius * 1.5;
  const points = useMemo(() => circlePoints(radius, 40), [radius]);
  const color = node.urgency === "urgent" ? COSMOS_HEX.red : COSMOS_HEX.amber;
  const width = 1 + node.urgencyStrength * (reducedMotion ? 3 : 2);
  const animated = !reducedMotion && node.urgency === "urgent";

  useFrame((state) => {
    if (!animated || !group.current) return;
    const pulse = 1 + Math.sin(state.clock.elapsedTime * 2.4) * 0.08;
    group.current.scale.setScalar(pulse);
  });

  return (
    <group ref={group}>
      <Line points={points} color={color} lineWidth={width} transparent opacity={0.35 + node.urgencyStrength * 0.45} />
    </group>
  );
}

interface NodeMeshProps {
  node: RadarNode;
  geometries: RadarGeometries;
  selected: boolean;
  active: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
}

function RadarNodeMesh({
  node,
  geometries,
  selected,
  active,
  dimmed,
  reducedMotion,
  onSelect,
  onHover,
}: NodeMeshProps) {
  // 선택한 항목만 키우고 빛나게 한다 — 강한 glow 는 선택 상태 전용이다.
  const scale = node.unitRadius * (selected ? 1.3 : 1);
  // 기수를 중심(관제탑) 쪽으로 돌린다. 데이터가 아니라 구도다 — 전부 안쪽을 향한다.
  const heading = Math.atan2(node.x, -node.y);
  const selectionPoints = useMemo(() => circlePoints(scale * 1.9, 40), [scale]);
  const baseOpacity = dimmed ? 0.4 : active || selected ? 1 : 0.9;
  const material = useRef<THREE.MeshBasicMaterial>(null);

  /*
   * 깜빡임 — 빔이 이 접점을 지나갈 때 밝아졌다가 사그라든다.
   *
   * **밝기만** 흔든다. 크기는 건드리지 않는다 — 마커 크기는 실제 값(예산 규모)을 뜻하므로
   * 애니메이션으로 키우면 눈금이 거짓말을 하게 된다.
   * 바닥값(BLIP_FLOOR) 아래로는 내려가지 않아 접점이 사라진 것처럼 보이지 않는다.
   *
   * 시계(state.clock)로만 계산하므로 리렌더가 없고, 스윕 그룹과 같은 시계를 쓰므로
   * «빔이 지나가는 순간»과 어긋나지 않는다.
   */
  useFrame((state) => {
    // 흐려 놓은 항목은 깜빡이지 않는다 — 흐리게 한 이유가 「지금 보는 게 아니다」인데
    // 그게 계속 반짝이면 흐림이 무의미해진다.
    if (reducedMotion || dimmed || !material.current) return;
    const glow = blipIntensity(node.angle, state.clock.elapsedTime);
    material.current.opacity = baseOpacity * (BLIP_FLOOR + (1 - BLIP_FLOOR) * glow);
  });

  return (
    <group position={nodePosition(node)}>
      {node.urgencyStrength > 0 && <UrgencyRing node={node} reducedMotion={reducedMotion} />}

      {selected && <Line points={selectionPoints} color={cosmosHex(node.color)} lineWidth={2.4} transparent opacity={0.95} />}

      <mesh
        geometry={geometries.plane}
        scale={scale * 1.55}
        rotation={[0, 0, heading]}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(node.id);
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          onHover(node.id);
        }}
        onPointerOut={() => onHover(null)}
      >
        <meshBasicMaterial
          ref={material}
          color={cosmosHex(node.color)}
          toneMapped={false}
          transparent
          opacity={baseOpacity}
          side={THREE.DoubleSide}
        />
      </mesh>

    </group>
  );
}

/**
 * 순위별 강제 분산.
 *
 * 1·2·3위가 비슷한 각도·비슷한 반지름에 놓이면 라벨이 서로 붙어 제목을 읽을 수 없다.
 * 1366×768 에서 실제로 그랬다. 화면 크기와 무관하게 **높이와 밀어내는 거리**를 순위마다
 * 다르게 주어 셋이 같은 줄에 서지 못하게 한다. 겹침이 남더라도 제목은 줄임표로 자르고
 * 전체는 hover·선택 때 상세로 보여 준다 (아래 NodeLabel).
 */
const RANK_SPREAD: ReadonlyArray<{ lift: number; push: number }> = [
  { lift: 0, push: 0 },        // 1위 — 기준
  { lift: 0.09, push: 0.09 },  // 2위 — 살짝 띄우고 한 뼘 바깥
  { lift: -0.09, push: 0.17 }, // 3위 — 반대로 내리고 더 바깥
  // 원반이 19.5°밖에 안 기울어 있어 lift(z) 만으로는 화면에서 위아래가 거의 안 벌어진다.
  // 실제로 갈라놓는 것은 **반지름 방향 push** 다 — 셋이 같은 띠에 서지 못하게 한다.
];

/**
 * 라벨을 중심 **바깥쪽**으로 밀어낸다.
 * 아래로만 내리면 안쪽 노드의 라벨이 중앙(현재 회사)과 겹친다 — 반지름 방향으로 빼면 가운데가 항상 비어 있다.
 */
/**
 * 측정용 — 지금 그리는 레이더 노드 수를 문서에 적어 둔다 (prompt_01 §4-A-6).
 * 화면에는 영향이 없고 `scripts/check_visibility.mjs` 만 읽는다.
 */
function useNodeCountMarker(count: number): void {
  useEffect(() => {
    document.documentElement.dataset.cosmosNodes = String(count);
    return () => {
      delete document.documentElement.dataset.cosmosNodes;
    };
  }, [count]);
}

/** 이름표 쌓임 — 순위 1 이 25, 12위 아래는 14(관제탑 30 · 31 밑) · 펼친 것은 28. */
function labelZ(node: RadarNode, active: boolean): [number, number] {
  const z = active ? 28 : 26 - Math.min(node.rank, 12);
  return [z, z];
}

function labelPosition(node: RadarNode): Vec3 {
  const length = Math.hypot(node.x, node.y) || 1;
  const spread = RANK_SPREAD[node.rank - 1] ?? { lift: 0, push: 0 };
  const offset = node.unitRadius * 1.4 + 0.055 + spread.push;
  return [
    node.x + (node.x / length) * offset,
    node.y + (node.y / length) * offset,
    node.z + spread.lift,
  ];
}

/**
 * 노드 라벨 — **전부** 띄운다 (ISSUE-109 · prompt_01 §4-A-3).
 *
 * 예전에는 1·2·3위와 선택·hover 만 띄워 12점 중 9점이 무명이었다. 이제 기본은
 * 「순위 · 제목 · D-day」 한 줄이고, 좁은 화면(compact)에서는 **순위 번호만** 남긴다 —
 * 겹침은 숨겨서가 아니라 짧게 적어 막는다. 선택·hover 는 지금처럼 넓게 편다.
 */
function NodeLabel({ node, active, compact }: { node: RadarNode; active: boolean; compact: boolean }) {
  return (
    // 45차 M18 — 겹치면 높은 순위가 위(거리로 정하면 5위가 1위를 덮었다) · 펼친 것(선택 · hover)은 맨 위
    <Html center position={labelPosition(node)} zIndexRange={labelZ(node, active)} style={{ pointerEvents: "none" }}>
      <div
        data-cosmos-label={active ? "long" : "short"}
        className={`whitespace-nowrap rounded-md border px-1.5 py-0.5 text-center backdrop-blur ${
          // 펼쳐 보는 것(선택·hover)만 넓게 둔다. 그렇지 않으면 세 라벨이 서로를 덮는다.
          active ? "max-w-[220px]" : compact ? "max-w-[46px]" : "max-w-[132px]"
        } ${
          active ? "border-cosmos-border-strong bg-cosmos-bg/95" : "border-cosmos-border/60 bg-cosmos-bg/88"
        }`}
      >
        <span
          className={`block truncate font-medium ${compact ? "text-[12px]" : "text-[12px]"} ${
            active ? "text-cosmos-text" : "text-cosmos-secondary"
          }`}
        >
          {/* 같은 출처 안 순위 — 섞은 자리 번호면 기업마당 1위가 「2」였다(27차 RDR-06). 출처는 이 숫자의 색 · 섹터가 나른다. */}
          <span className="font-mono tabular-nums" style={{ color: node.color }}>
            {node.sourceRank}
          </span>
          {/* 좁은 화면에서는 순위 번호만 남긴다 — 제목까지 적으면 서로 덮는다. */}
          {!compact && (
            <>
              {" "}
              {node.shortTitle}
              {/* 마감은 선택하지 않아도 보여야 한다. 언제까지인지가 이 화면의 절반이다. */}
              {!active && node.deadlineLabel && (
                <span className="ml-1 font-mono tabular-nums text-cosmos-muted">{node.deadlineLabel}</span>
              )}
            </>
          )}
        </span>
        {active && (
          <span className="block text-[12px] text-cosmos-muted">
            {node.sourceLabel} · {node.deadlineLabel}
            {node.scoreUnknown ? ` · ${UNSCORED}` : ""}
          </span>
        )}
      </div>
    </Html>
  );
}

// ---------------------------------------------------------------------------
// 장면
// ---------------------------------------------------------------------------

function Scene({ layout, selectedId, hoveredId, onSelect, onHover, reducedMotion, companyName, compact }: RadarSceneProps) {
  useNodeCountMarker(layout.nodes.length);
  const geometries = useRadarGeometries();
  // 캔버스 비율이 어떻든(가로로 긴 데스크톱 / 세로로 긴 모바일) 레이더가 짧은 변을 거의 채우게 맞춘다.
  const viewport = useThree((state) => state.viewport);
  const size = useThree((state) => state.size);
  const fit = Math.min(
    viewport.width / 2 / MARGIN_X,
    viewport.height / 2 / (MARGIN_Y * Math.cos(DISC_TILT)),
  );
  /*
   * 관제탑 크기.
   *
   * 관제탑은 `<Html>` 이라 **CSS px** 로 그려지는데, 레이더는 `fit` 으로 캔버스에 맞춰 커진다.
   * px 를 상수로 박아 두면 큰 화면에서 탑만 쪼그라들고 작은 화면에서는 과하게 커진다.
   * 그래서 「반지름 단위 → 화면 px」 환산을 한 번 해서 씬 배율을 따라가게 한다.
   * (실루엣은 2D 스코프와 같은 path 를 쓰므로 두 화면이 같은 그림으로 남는다.)
   */
  const pxPerSceneUnit = viewport.height > 0 ? size.height / viewport.height : 0;
  const towerPx = Math.max(22, Math.min(56, TOWER_UNITS * fit * pxPerSceneUnit));
  const activeId = hoveredId ?? selectedId;
  const selectedNode = layout.nodes.find((node) => node.id === selectedId) ?? null;

  const linkPoints = useMemo<Vec3[] | null>(() => {
    if (!selectedNode) return null;
    return [[0, 0, 0], nodePosition(selectedNode)];
  }, [selectedNode]);

  return (
    <>
      <ambientLight intensity={1.9} />
      <directionalLight position={[4, 6, 9]} intensity={2.1} />

      <group rotation={[DISC_TILT, 0, 0]} scale={fit}>
        {!reducedMotion && <SweepBeam geometries={geometries} />}
        <GuideRings layout={layout} />
        <SectorLabels layout={layout} compact={compact} />
        <BandLabels layout={layout} compact={compact} />

        {linkPoints && selectedNode && (
          <Line points={linkPoints} color={cosmosHex(selectedNode.color)} lineWidth={2.4} transparent opacity={0.9} />
        )}

        <CenterNode
          geometries={geometries}
          companyName={companyName}
          compact={compact}
          reducedMotion={reducedMotion}
          towerPx={towerPx}
        />

        {layout.nodes.map((node) => (
          <RadarNodeMesh
            key={node.id}
            node={node}
            geometries={geometries}
            selected={node.id === selectedId}
            active={node.id === activeId}
            dimmed={selectedId !== null && node.id !== selectedId && node.id !== activeId}
            reducedMotion={reducedMotion}
            onSelect={onSelect}
            onHover={onHover}
          />
        ))}

        {layout.nodes
          .filter((node) => shouldShowLabel(node, activeId, compact))
          .map((node) => (
            <NodeLabel key={`label-${node.id}`} node={node} active={node.id === activeId} compact={compact} />
          ))}
      </group>
    </>
  );
}

export default function RadarScene3D(props: RadarSceneProps) {
  const { layout, companyName, reducedMotion, compact, onSelect } = props;

  return (
    <div role="img" aria-label={radarAriaLabel(layout, companyName)} className="absolute inset-0">
      <Canvas
        aria-hidden
        dpr={compact ? [1, 1.25] : [1, 1.75]}
        // reduced motion 이면 계속 그리지 않고 변화가 있을 때만 그린다.
        frameloop={reducedMotion ? "demand" : "always"}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={{ fov: 42, near: 0.1, far: 100, position: [0, 0, CAMERA_Z] }}
        onPointerMissed={() => onSelect(null)}
        className="h-full w-full"
      >
        <Scene {...props} />
      </Canvas>
    </div>
  );
}
