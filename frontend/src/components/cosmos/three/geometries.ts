"use client";

/**
 * 3D 노드 모양 — **종류당 하나 · 장식 없음** (21차 · prompt_11 §3-3).
 *
 * 공고 ● · 조건 ◆ · 자격 ▲ · 요구사항 ▪ · 근거 ▫(문서 카드) · 문장 ─ · 발견 ⚠ · 결정 ◉.
 * 모두 평면 도형이고 노드가 카메라를 향해 돌린다(billboard) — 어느 각도에서 봐도 같은 기호로 읽힌다.
 * 예전의 궤도 행성 · 원뿔 · 고리 · 후광 · 발광 셸은 없앴다.
 */

import { useEffect, useMemo } from "react";
import * as THREE from "three";

import type { CosmosNode, CosmosNodeKind } from "@/lib/cosmos/graph";
import { nodeColorHex } from "@/lib/cosmos/itemTypes";
import { cosmosHex } from "@/lib/cosmos/theme";
import type { MarkerShape } from "@/lib/cosmos/stations";

import { SELECTION_RING } from "./constants";

const HALF_PI = Math.PI / 2;
const QUARTER_PI = Math.PI / 4;

/** 모양 하나 — 겹쳐 그리는 조각들(◉ 은 고리 + 점). */
export interface Shape {
  parts: THREE.BufferGeometry[];
  /** 선택 링 · 라벨 배제 반경 기준 (월드 단위) */
  radius: number;
  /** 가로·세로 비율 (근거 카드는 세로로 긴 사각형) */
  scale: readonly [number, number, number];
}

export interface CosmosGeometries {
  node: Record<CosmosNodeKind, Shape>;
  marker: Record<MarkerShape, Shape>;
  selectionRing: THREE.BufferGeometry;
}

const UNIT: readonly [number, number, number] = [1, 1, 1];

function createGeometries(): { geometries: CosmosGeometries; owned: THREE.BufferGeometry[] } {
  const owned: THREE.BufferGeometry[] = [];
  const own = <T extends THREE.BufferGeometry>(geometry: T): T => {
    owned.push(geometry);
    return geometry;
  };
  const circle = own(new THREE.CircleGeometry(0.45, 32));
  // 4분할 원을 45° 돌리면 축에 맞춘 정사각형 — ▪
  const square = own(new THREE.CircleGeometry(0.22, 4, QUARTER_PI));
  // 속이 빈 사각 테두리를 세로로 늘인 문서 카드 — ▫
  const card = own(new THREE.RingGeometry(0.17, 0.24, 4, 1, QUARTER_PI));
  const hubBar = own(new THREE.PlaneGeometry(0.9, 0.14));
  // 속이 빈 삼각형(꼭짓점 위) — ⚠
  const warnHub = own(new THREE.RingGeometry(0.2, 0.36, 3, 1, HALF_PI));
  const warn = own(new THREE.RingGeometry(0.12, 0.24, 3, 1, HALF_PI));
  const diamond = own(new THREE.CircleGeometry(0.22, 4));
  // 속이 찬 삼각형 — ▲ (⚠ 과 구분)
  const triangle = own(new THREE.CircleGeometry(0.24, 3, HALF_PI));
  const bar = own(new THREE.PlaneGeometry(0.6, 0.1));
  const targetRing = own(new THREE.RingGeometry(0.26, 0.36, 32));
  const targetDot = own(new THREE.CircleGeometry(0.14, 24));

  const geometries: CosmosGeometries = {
    node: {
      notice: { parts: [circle], radius: 0.45, scale: UNIT },
      requirement: { parts: [square], radius: 0.22, scale: UNIT },
      "requirement-group": { parts: [square], radius: 0.35, scale: [1.6, 1.6, 1] },
      evidence: { parts: [card], radius: 0.24, scale: [0.8, 1.15, 1] },
      proposal: { parts: [hubBar], radius: 0.45, scale: UNIT },
      audit: { parts: [warnHub], radius: 0.36, scale: UNIT },
      finding: { parts: [warn], radius: 0.24, scale: UNIT },
      "finding-group": { parts: [warn], radius: 0.36, scale: [1.5, 1.5, 1] },
    },
    marker: {
      diamond: { parts: [diamond], radius: 0.22, scale: UNIT },
      triangle: { parts: [triangle], radius: 0.24, scale: UNIT },
      bar: { parts: [bar], radius: 0.3, scale: UNIT },
      target: { parts: [targetRing, targetDot], radius: 0.36, scale: UNIT },
    },
    selectionRing: own(new THREE.RingGeometry(SELECTION_RING.innerRatio, 1, 64)),
  };
  return { geometries, owned };
}

export function useCosmosGeometries(): CosmosGeometries {
  const created = useMemo(() => createGeometries(), []);
  useEffect(() => {
    return () => {
      for (const geometry of created.owned) geometry.dispose();
    };
  }, [created]);
  return created.geometries;
}

/** 노드 색 — 판정 뜻만 (가능 청록 · 확인 필요 호박 · 불가 붉음 · 중립 회청). 2D·범례와 같은 규칙. */
export function nodeHex(node: CosmosNode): string {
  // 3D 재질은 16진만 받는다 — 공유 색(var())을 어두운 판 16진으로(2.4.0 ⑥).
  return cosmosHex(nodeColorHex(node));
}
