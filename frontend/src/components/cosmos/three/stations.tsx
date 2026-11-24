"use client";

/**
 * 정거장 이름과 길 (21차 · prompt_11 §3 · 27차 §3-D) — 지도가 말해야 할 한 문장
 * 「공고 → 적합도 → 참가 여부 → 요구사항 → 근거 → 제안서 → 점검 → 결정」을 그린다.
 *
 * 지금 정거장만 기호와 이름표를 단다. 나머지 일곱 정거장은 **이름 알약**(번호 · 이름 · 개수 · 상태 기호)이고,
 * 레일이 「!」 「✕」인 단계에는 같은 낱말 알약(「확인 필요」 · 「실패」 · ③ 「확인 전 n」)이 붙는다. 알약을 누르면
 * 그 정거장으로 간다(레일과 같은 이동 — 키보드는 레일이 맡는다 · 캔버스가 aria-hidden 이다).
 *
 * 이름은 drei `Html` 이지만 **`data-cosmos-label` 을 달지 않는다** — 노드 라벨 수를 세는 검사(라벨 없는 점)와
 * 흔들림 짝짓기에 끼면 안 된다. 대신 `data-cosmos-station-name` 을 단다(첫 화면 검사가 읽는다).
 */

import { Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { EligibilityGateView } from "@/lib/cosmos/eligibilityGate";
import type { WorkflowStage, WorkflowStepView } from "@/lib/cosmos/graph";
import { lineColorHex, nodeColorHex, verdictPill } from "@/lib/cosmos/itemTypes";
import { STATION_IDS, STATION_NAMES, stationFlag, stationTier, type SelectionLine, type StationMarker } from "@/lib/cosmos/stations";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import { COSMOS_HEX, cosmosHex } from "@/lib/cosmos/theme";

import { APPEAR_DURATION, APPEAR_STAGGER, MATERIAL_DAMP_LAMBDA, WARNING_BLINK_SPEED, type Vec3 } from "./constants";
import type { CosmosGeometries } from "./geometries";
import { FloatingLabel, LabelChip } from "./labels";
import { createFlatMaterial, setFlatColor, setFlatOpacity } from "./nodes";
import { NAME_MIN_PX, STATION_PATH_Y, type StationFrame } from "./stationLayout";

const NO_POINTER: React.CSSProperties = { pointerEvents: "none" };
/** 번호 원(24px)의 가운데가 길 위에 오도록 — 이름과 요약은 원 아래로 흐른다. */
const ON_PATH: React.CSSProperties = { transform: "translate(-50%, -12px)" };
/**
 * 캔버스 안 누르는 요소 — 캔버스를 감싼 div 에 R3F 와 OrbitControls 가 리스너를 달아 두었다. 막지 않으면 누를 때
 * 끌어 돌리기가 시작되고(pointerdown), 선택이 풀리고(click → onPointerMissed), 알약 기준 좌표로 hover 가 걸린다(pointermove).
 */
const stop = (event: React.SyntheticEvent) => event.stopPropagation();
const STOP_EVENTS = { onPointerDown: stop, onPointerUp: stop, onPointerMove: stop } as const;
/** 칸 폭이 이보다 좁으면 낱말 알약을 두 줄(「확인/필요」)로 접는다. ponytail: 1440 · 1280 캡처로 맞춘 값. */
const FLAG_WORD_MIN_PX = 70;
/**
 * 이보다 좁으면 알약을 기호 하나로(낱말은 title · aria) — 그때는 캡션 줄의 상태 기호를 빼서 「!」가 두 번 보이지 않게 한다
 * (27차 검수 R27D-OWN-06: 1280 에서 모든 알약이 「(!)」가 되고 윗줄 「!」와 겹쳤다).
 */
const FLAG_FOLD_MIN_PX = 44;

interface StationPathProps {
  frame: StationFrame;
  stage: WorkflowStage;
  steps: WorkflowStepView[];
  /** 정거장마다 몇 건이 서 있는가 (이름 아래 작은 글자) */
  counts: number[];
  /** ③ 정거장의 문 — 참가자격 종합. null 이면 판정 전 */
  gate: EligibilityGateView | null;
  /** 월드 1 단위가 몇 px 인가 — 좁은 칸이면 알약을 기호로 줄인다 */
  pxPerUnit: number;
  /** 지금이 아닌 정거장 머리를 누르면 그 정거장으로 (레일과 같은 이동) */
  onStation?: (stage: WorkflowStage) => void;
}

/** ③ → ④ 구간 — 참가자격이 불가면 이 길이 끊긴다. */
const GATE_SEGMENT = 2;
/** 끊긴 길의 양쪽 토막 길이 (구간 비율) — 가운데가 비어 「여기서 막힌다」로 읽힌다. */
const BROKEN_STUB = 0.32;

export function StationPath({ frame, stage, steps, counts, gate, pxPerUnit, onStation }: StationPathProps) {
  const locked = gate?.verdict === "FAIL";
  const segments = useMemo(() => {
    const out: Array<{ key: string; points: Vec3[]; broken: boolean }> = [];
    for (let i = 0; i < frame.centers.length - 1; i += 1) {
      const a = frame.centers[i];
      const b = frame.centers[i + 1];
      if (locked && i === GATE_SEGMENT) {
        const stub = (b - a) * BROKEN_STUB;
        out.push({ key: `${i}a`, points: [[a, STATION_PATH_Y, 0], [a + stub, STATION_PATH_Y, 0]], broken: true });
        out.push({ key: `${i}b`, points: [[b - stub, STATION_PATH_Y, 0], [b, STATION_PATH_Y, 0]], broken: true });
      } else {
        out.push({ key: String(i), points: [[a, STATION_PATH_Y, 0], [b, STATION_PATH_Y, 0]], broken: false });
      }
    }
    return out;
  }, [frame, locked]);
  return (
    <>
      {segments.map((segment) => (
        <Line
          key={segment.key}
          points={segment.points}
          color={segment.broken ? COSMOS_HEX.red : COSMOS_HEX.slate}
          lineWidth={segment.broken ? 2 : 1.5}
          dashed={segment.broken}
          dashSize={0.3}
          gapSize={0.2}
          transparent
          opacity={segment.broken ? 0.9 : 0.45}
          depthWrite={false}
          toneMapped={false}
        />
      ))}
      {STATION_IDS.map((id) => {
        const tier = stationTier(id, stage);
        const current = tier === "current";
        const step = steps[id - 1];
        const meta = step ? STEP_STATUS_META[step.status] : null;
        const flag = stationFlag(step, gate);
        const isGate = id === 3;
        const gateLocked = isGate && locked;
        const span = frame.spans[id - 1];
        const spanPx = (span.x1 - span.x0) * pxPerUnit;
        const flagMode = spanPx >= FLAG_WORD_MIN_PX ? "word" : spanPx >= FLAG_FOLD_MIN_PX ? "fold" : "glyph";
        // 좁은 칸(3D 를 고른 1024 · 390)은 개수를 빼고 이름을 13px 로 줄여 칸 안에서 접는다(「요구/사항」) — sr-only 로 숨기면
        // 다시 「이름 없는 번호」가 됐다(27차 검수 R27REQ-01). 지금 정거장 이름 · 요약은 칸 폭 안에서 접힌다.
        const tight = !current && spanPx < NAME_MIN_PX;
        const glyphFlag = flag !== null && flagMode === "glyph";
        const room = Math.max(96, spanPx - 8);
        const clickable = !current && onStation !== undefined;
        const body = (
          <>
            <span
              aria-hidden
              className={`inline-flex h-6 w-6 items-center justify-center rounded-full border bg-cosmos-deep text-[13px] font-semibold tabular-nums ${
                gateLocked
                  ? "border-cosmos-red text-cosmos-red-text"
                  : current
                    ? "border-cosmos-cyan text-cosmos-cyan"
                    : "border-cosmos-border-strong text-cosmos-secondary"
              }`}
            >
              {id}
            </span>
            {/* 지금 정거장은 레일 이름 그대로 · 나머지는 그 이름 안의 낱말(27차 §3-D-9) */}
            {/* 지금이 아닌 정거장 칸은 좁다(1440 에서 약 75px) — 두 낱말 이름(「참가 여부」)은 두 줄로 접어 옆 이름과 붙지 않게 */}
            <span
              className={`${
                tight ? "whitespace-normal break-all text-[13px] leading-4" : `${current && !frame.narrow ? "whitespace-nowrap" : "whitespace-normal break-keep"} text-[18px] leading-6`
              } text-center font-semibold ${
                gateLocked ? "text-cosmos-red-text" : current ? "text-cosmos-text" : "text-cosmos-secondary"
              }`}
              // max-content 를 주지 않으면 Html 상자의 줄어든 폭에서 접혀 `nameLines` 어림(칸 폭)보다 줄이 많아졌다.
              style={current ? (frame.narrow ? { width: "max-content", maxWidth: room } : undefined) : { maxWidth: tight ? Math.max(26, spanPx - 2) : Math.max(40, spanPx - 6) }}
            >
              {current ? (step?.label ?? STATION_NAMES[id]) : STATION_NAMES[id]}
            </span>
            {gateLocked ? (
              // 불가면 요약 대신 잠김 — 사람이 「참여 안 함」을 기록하게 (prompt_11 §3-6).
              <span className="text-[13px] font-semibold leading-4 text-cosmos-red-text">참가 불가 · 잠김</span>
            ) : (
              <span className="flex items-center gap-1 text-[13px] leading-4 text-cosmos-secondary" style={{ maxWidth: current && frame.narrow ? Math.min(220, room) : 220 }}>
                {meta && !glyphFlag && (
                  <span aria-label={meta.label} title={meta.label} className="font-semibold" style={{ color: meta.color }}>
                    {meta.glyph}
                  </span>
                )}
                {/* 좁으면 개수는 뺀다(③ 의 두 수는 낱말 알약 · title 에 남는다) — sr-only 로 두면 잘림 검사가 잘린 캡션으로 읽는다 */}
                {!tight && (
                  <span data-cosmos-station-caption className="truncate">
                    {current ? step?.summary : counts[id - 1] > 0 ? `${counts[id - 1]}건` : ""}
                  </span>
                )}
              </span>
            )}
            {flag && (
              <span
                data-station-flag={flag.word}
                title={flag.word}
                aria-label={flag.word}
                data-station-flag-mode={flagMode}
                className={`mt-0.5 border bg-cosmos-deep text-center text-[13px] font-semibold ${
                  flagMode === "fold" ? "whitespace-normal break-keep rounded-lg px-1.5 leading-4" : "rounded-full px-2 leading-5"
                } ${flag.glyph === STEP_STATUS_META.failed.glyph ? "border-cosmos-red/60 text-cosmos-red-text" : "border-cosmos-amber/60 text-cosmos-amber"}`}
                style={flagMode === "fold" ? { maxWidth: spanPx - 4 } : undefined}
              >
                {flagMode === "glyph" ? flag.glyph : flag.word}
              </span>
            )}
          </>
        );
        return (
          <Html key={id} position={[frame.centers[id - 1], STATION_PATH_Y, 0]} zIndexRange={[20, 10]} style={NO_POINTER}>
            {clickable ? (
              <button
                type="button"
                tabIndex={-1}
                data-cosmos-station-name={id}
                data-cosmos-station-tier={tier}
                data-cosmos-gate={isGate && gate ? gate.verdict : undefined}
                title={`${step?.label ?? STATION_NAMES[id]} — 눌러서 이 정거장 보기`}
                onClick={(event) => {
                  event.stopPropagation();
                  onStation?.(id);
                }}
                {...STOP_EVENTS}
                className="pointer-events-auto flex cursor-pointer select-none flex-col items-center gap-0.5 whitespace-nowrap rounded-lg px-1 pb-1 transition-colors hover:bg-cosmos-elevated/60"
                style={ON_PATH}
              >
                {body}
              </button>
            ) : (
              <div
                data-cosmos-station-name={id}
                data-cosmos-station-tier={tier}
                data-cosmos-gate={isGate && gate ? gate.verdict : undefined}
                title={step?.label}
                className="flex select-none flex-col items-center gap-0.5 whitespace-nowrap"
                style={ON_PATH}
              >
                {body}
              </div>
            )}
          </Html>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// 고른 항목에서 나가는 선 — 관련 정거장마다 하나 · 최대 3 (27차 §3-D-3)
// ---------------------------------------------------------------------------

interface SelectionLinesProps {
  lines: SelectionLine[];
  from: Vec3;
  frame: StationFrame;
  /** 빨강(문제) 선을 밝기로 깜빡인다 — 움직이는 점선 대신(「점선 = 확인 필요」와 부딪히지 않게) */
  blink: boolean;
}

/** 기호 왼쪽 골(월드) — 선이 이름표를 지나지 않게 항목 왼쪽으로 먼저 나간다. 선마다 조금씩 더 왼쪽. */
const LINE_GUTTER = 0.4;
const LINE_GUTTER_STEP = 0.14;

/**
 * 선 경로 — 곧은 대각선은 다른 이름표 위를 지나고 셋이 한 줄로 겹쳤다(27차 검수 R27D-OWN-03 · 02).
 * 항목 → 기호 왼쪽 골 → 마지막 줄 아래 길(선마다 다른 높이) → 상대 정거장 세로줄(그 칸은 비어 있다) → 알약 아래.
 * 가까운 정거장이 위 길을 쓴다 — 세로줄과 가로 길이 서로 엇갈리지 않는다.
 */
export function selectionLinePoints(from: Vec3, stations: WorkflowStage[], frame: StationFrame): Map<WorkflowStage, Vec3[]> {
  const order = [...stations].sort((a, b) => Math.abs(frame.centers[a - 1] - from[0]) - Math.abs(frame.centers[b - 1] - from[0]));
  const out = new Map<WorkflowStage, Vec3[]>();
  order.forEach((station, i) => {
    const gx = from[0] - LINE_GUTTER - i * LINE_GUTTER_STEP;
    const lane = frame.laneY - i * frame.laneStep;
    const tx = frame.centers[station - 1];
    out.set(station, [from, [gx, from[1], 0], [gx, lane, 0], [tx, lane, 0], [tx, frame.anchorY, 0]]);
  });
  return out;
}

export function SelectionLines({ lines, from, frame, blink }: SelectionLinesProps) {
  const paths = selectionLinePoints(from, lines.map((line) => line.station), frame);
  return (
    <>
      {lines.map((line) => (
        <SelectionLineMesh
          key={line.station}
          line={line}
          points={paths.get(line.station) ?? [from, [frame.centers[line.station - 1], frame.anchorY, 0]]}
          blink={blink && line.state === "warning"}
        />
      ))}
    </>
  );
}

function SelectionLineMesh({ line, points, blink }: { line: SelectionLine; points: Vec3[]; blink: boolean }) {
  const ref = useRef<{ material: { opacity: number } } | null>(null);
  useFrame((state) => {
    const material = ref.current?.material;
    if (!material) return;
    material.opacity = blink ? 0.55 + 0.4 * (0.5 + 0.5 * Math.sin(state.clock.elapsedTime * WARNING_BLINK_SPEED)) : 0.95;
  });
  return (
    <Line
      // drei Line2 — 재질의 opacity 만 흔든다(점선을 움직이지 않는다).
      ref={ref as never}
      points={points}
      color={cosmosHex(lineColorHex(line.state))}
      lineWidth={2}
      dashed={line.state === "candidate"}
      dashSize={0.35}
      gapSize={0.25}
      transparent
      opacity={0.95}
      depthWrite={false}
      toneMapped={false}
    />
  );
}

/** 지금 정거장이 24 를 넘을 때 — 「외 n건 · 전체 보기」(누르면 목록 보기). 라벨 검사에 끼지 않게 data-cosmos-label 없음. */
export function MoreChip({ at, count, onShowAll }: { at: Vec3; count: number; onShowAll?: () => void }) {
  return (
    <Html position={[at[0], at[1], at[2]]} zIndexRange={[20, 10]} style={NO_POINTER}>
      <button
        type="button"
        tabIndex={-1}
        data-cosmos-more={count}
        onClick={(event) => {
          event.stopPropagation();
          onShowAll?.();
        }}
        {...STOP_EVENTS}
        className="pointer-events-auto -translate-y-1/2 whitespace-nowrap rounded-md border border-cosmos-border-strong bg-cosmos-panel px-2 py-[2px] text-[13px] leading-4 text-cosmos-secondary hover:text-cosmos-text"
      >
        외 {count}건 · 전체 보기
      </button>
    </Html>
  );
}

// ---------------------------------------------------------------------------
// 그래프에 노드가 없는 정거장의 표시 — ③ 조건 ◆·자격 ▲ · ⑥ 문장 ─ · ⑧ 결정 ◉ (고를 수 없다)
// ---------------------------------------------------------------------------

interface StationMarkerMeshProps {
  marker: StationMarker;
  position: Vec3;
  geometries: CosmosGeometries;
  reducedMotion: boolean;
  /** 같은 정거장 안 순번 — 등장 stagger */
  index: number;
  labelMaxWidth?: number;
}

/** 지금 정거장의 표시 하나 — 기호 + 이름표(호박 · 빨강이면 끝에 같은 색 낱말). 다른 정거장은 그리지 않는다. */
export function StationMarkerMesh({ marker, position, geometries, reducedMotion, index, labelMaxWidth }: StationMarkerMeshProps) {
  const groupRef = useRef<THREE.Group>(null);
  const faceRef = useRef<THREE.Group>(null);
  const appearStartRef = useRef<number | null>(null);
  const opacityRef = useRef(1);
  const shape = geometries.marker[marker.shape];
  const hex = cosmosHex(nodeColorHex(marker));
  const material = useMemo(() => createFlatMaterial(), []);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => {
    setFlatColor(material, hex);
  }, [material, hex]);
  useLayoutEffect(() => {
    groupRef.current?.scale.setScalar(0);
  }, []);

  useFrame((state, delta) => {
    const group = groupRef.current;
    if (!group) return;
    const dt = Math.min(delta, 0.1);
    let appear = 1;
    if (reducedMotion) {
      appearStartRef.current = Number.NEGATIVE_INFINITY;
    } else {
      if (appearStartRef.current === null) appearStartRef.current = state.clock.elapsedTime + index * APPEAR_STAGGER;
      const progress = (state.clock.elapsedTime - appearStartRef.current) / APPEAR_DURATION;
      appear = progress <= 0 ? 0 : progress >= 1 ? 1 : 1 - (1 - progress) ** 3;
    }
    group.scale.setScalar(appear);
    faceRef.current?.quaternion.copy(state.camera.quaternion);
    opacityRef.current = reducedMotion ? 1 : THREE.MathUtils.damp(opacityRef.current, 1, MATERIAL_DAMP_LAMBDA, dt);
    setFlatOpacity(material, opacityRef.current);
  });

  return (
    <group position={[position[0], position[1], position[2]]}>
      <group ref={groupRef}>
        <group ref={faceRef}>
          {shape.parts.map((geometry, i) => (
            <mesh key={i} geometry={geometry} material={material} scale={shape.scale} renderOrder={1} />
          ))}
        </group>
      </group>
      <FloatingLabel
        nodePosition={position}
        offset={[shape.radius + 0.25, 0, 0]}
        anchor="left"
        dimmed={false}
        reducedMotion={reducedMotion}
        appearDelay={index * APPEAR_STAGGER}
        labelId={marker.id}
        variant="long"
        nodeRadius={shape.radius}
        tone={hex}
        alwaysOn
        current
        station={marker.station}
        maxWidth={labelMaxWidth}
      >
        {/* 기호는 이미 색으로 그렸다 — 이름표 안 ● 는 두 번째 기호라 뺐다(27차 §3-D-6). */}
        <LabelChip verdict={verdictPill(marker.state)}>{marker.label}</LabelChip>
      </FloatingLabel>
    </group>
  );
}
