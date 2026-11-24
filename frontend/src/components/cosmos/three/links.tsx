"use client";

/**
 * 연결선 — 곧은 선 하나 (21차 · prompt_11 §3-3 「장식 없음」).
 *  - 3단계: neutral(얇은 slate) · active(청록) · warning(붉음). candidate 는 회청 점선.
 *  - 투명도는 useFrame에서 damp (값은 material에만, setState 없음). reducedMotion이면 즉시.
 *  - 정거장 지도에서는 밝은 쪽 끝의 밝기 단계를 곱한다(`tierOpacity`) — 지금 정거장에 닿은 선만 온전하다.
 * 예전의 곡선 · 글로우 · 흐름 파티클 · 궤도 안내선은 없앴다.
 */

import { Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { memo, useCallback, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { CosmosLink } from "@/lib/cosmos/graph";

import { DIMMED_LINK_OPACITY, LINK_DASH, LINK_STYLES, MATERIAL_DAMP_LAMBDA, WARNING_BLINK_SPEED, type Vec3 } from "./constants";

/** 공고→요구사항 스포크는 개수가 많으므로(≈23개) 기본 투명도의 60%만 쓴다 (지원사업 지도). */
const SPOKE_OPACITY_SCALE = 0.6;

/** drei Line의 실체(Line2)는 Mesh이고 재질은 LineMaterial 이다. */
type LineObject = THREE.Mesh & { material: THREE.Material };

export type LinkPoints = readonly [Vec3, Vec3];

export interface CosmosLinkLineProps {
  link: CosmosLink;
  points: LinkPoints;
  highlighted: boolean;
  dimmed: boolean;
  /** 강조된 warning 링크이며 paused/reducedMotion이 아닐 때만 true — 밝기 깜빡임(27차 §3-D-3) */
  pulse: boolean;
  reducedMotion: boolean;
  /** Focus Mode 순차 강조 지연(초). highlighted가 켜진 뒤 이 시간이 지나야 밝아진다. */
  highlightDelay?: number;
  /** 정거장 지도의 밝기 배수 (기본 1) */
  tierOpacity?: number;
}

export const CosmosLinkLine = memo(function CosmosLinkLine({
  link,
  points,
  highlighted,
  dimmed,
  pulse,
  reducedMotion,
  highlightDelay = 0,
  tierOpacity = 1,
}: CosmosLinkLineProps) {
  const lineRef = useRef<LineObject | null>(null);
  /** highlighted가 켜진 뒤 경과 시간(초) — 순차 강조용. 꺼지면 0으로 되돌린다. */
  const highlightAgeRef = useRef(0);
  const style = LINK_STYLES[link.state];
  const dashed = style.dashed;
  const dash = LINK_DASH;
  const opacityScale = (link.kind === "notice-requirement" ? SPOKE_OPACITY_SCALE : 1) * tierOpacity;

  const linePoints = useMemo(() => [points[0], points[1]] as Vec3[], [points]);
  const setLineRef = useCallback((object: THREE.Object3D | null) => {
    lineRef.current = object as LineObject | null;
  }, []);

  // 등장 시 0에서 시작해 목표 투명도로 감쇠한다 (reducedMotion이면 useFrame 첫 프레임에 즉시).
  useLayoutEffect(() => {
    const line = lineRef.current;
    if (line) line.material.opacity = 0;
  }, []);

  useFrame((state, delta) => {
    const line = lineRef.current;
    if (!line) return;
    const material = line.material;
    const dt = Math.min(delta, 0.1);
    if (highlighted) highlightAgeRef.current += dt;
    else highlightAgeRef.current = 0;
    const waiting = highlighted && !reducedMotion && highlightAgeRef.current < highlightDelay;
    const target =
      dimmed || waiting
        ? DIMMED_LINK_OPACITY * tierOpacity
        : (highlighted ? style.highlightOpacity : style.opacity) * opacityScale;
    const eased = reducedMotion ? target : THREE.MathUtils.damp(material.opacity, target, MATERIAL_DAMP_LAMBDA, dt);
    // 경고 선은 **밝기만** 깜빡인다 — 움직이는 점선은 「점선 = 확인이 필요한 연결」과 부딪혔다(27차 §3-D-3).
    const blink = pulse && !dimmed && !waiting ? 0.6 + 0.4 * (0.5 + 0.5 * Math.sin(state.clock.elapsedTime * WARNING_BLINK_SPEED)) : 1;
    material.opacity = pulse ? target * blink : eased;
  });

  return (
    <Line
      ref={setLineRef}
      points={linePoints}
      color={style.color}
      lineWidth={style.lineWidth}
      dashed={dashed}
      dashSize={dash.dashSize}
      gapSize={dash.gapSize}
      transparent
      depthWrite={false}
      toneMapped={false}
    />
  );
});
