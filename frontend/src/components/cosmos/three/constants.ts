/**
 * Cosmos3D 전용 상수. 수치는 docs/cosmos_design.md 4장을 따른다.
 * 색은 theme.ts 토큰만 사용한다.
 */

import type { CosmosLinkState, CosmosNodeKind } from "@/lib/cosmos/graph";
import type { CameraPreset } from "@/lib/cosmos/presentation";
import { COSMOS_HEX } from "@/lib/cosmos/theme";

export type Vec3 = readonly [number, number, number];

export interface CameraPose {
  position: Vec3;
  target: Vec3;
}

/** 카메라 프리셋 (position → target). */
export const CAMERA_PRESETS: Record<CameraPreset, CameraPose> = {
  overview: { position: [0, 13, 21], target: [0, 2.5, 0] },
  notice: { position: [0, 4.5, 9], target: [0, 0.4, 0] },
  requirements: { position: [0, 9, 13], target: [0, 0, 0] },
  evidence: { position: [0, 15, 18], target: [0, 0, 0] },
  proposal: { position: [0, 7.5, 12], target: [0, 4, 0] },
  audit: { position: [0, 10.5, 11], target: [0, 7.5, 0] },
  review: { position: [14, 12, 18], target: [0, 3.5, 0] },
};

/** focusNodeId 포커스 시 노드 종류별 카메라 거리. */
export const FOCUS_DISTANCE: Record<CosmosNodeKind, number> = {
  notice: 10,
  requirement: 7,
  "requirement-group": 9,
  "finding-group": 9,
  evidence: 7,
  finding: 7,
  proposal: 9,
  audit: 9,
};

/** 초당 감쇠 계수. 60fps 기준 프레임당 약 0.08 lerp와 같다. */
export const CAMERA_DAMP_LAMBDA = 5;
/** 재질(발광·투명도)·강조 스케일 감쇠 계수. */
export const MATERIAL_DAMP_LAMBDA = 10;

export const ORBIT_LIMITS = {
  minDistance: 5,
  // 정거장 지도는 길 전체(40 단위)를 담으려고 좁은 화면에서 40 보다 멀리 물러선다 (21차).
  maxDistance: 60,
  maxPolarAngle: Math.PI * 0.49,
} as const;

/** 강조 집합이 비어 있지 않을 때 집합 밖 연결선의 투명도. */
export const DIMMED_LINK_OPACITY = 0.06;

/** 등장 애니메이션 (초). */
export const APPEAR_DURATION = 0.35;
export const APPEAR_STAGGER = 0.03;

/**
 * 경고(빨강) 선 깜빡임 — 밝기만 흔든다(라디안/초 · 약 0.6Hz). 예전의 움직이는 빨간 점선은 「점선 = 확인이 필요한 연결」과
 * 부딪혀 범례와 다른 뜻이 됐다(27차 §3-D-3). 점선을 움직이지 않는다.
 */
export const WARNING_BLINK_SPEED = 4;

export interface LinkStyle {
  color: string;
  opacity: number;
  /** 강조 집합에 포함됐을 때 */
  highlightOpacity: number;
  lineWidth: number;
  dashed: boolean;
}

export const LINK_STYLES: Record<CosmosLinkState, LinkStyle> = {
  active: {
    color: COSMOS_HEX.cyan,
    opacity: 0.6,
    highlightOpacity: 0.95,
    lineWidth: 1.6,
    dashed: false,
  },
  // 후보 증빙: 판정 뜻 색만 쓴다(21차) — 보라 대신 회청 점선.
  candidate: {
    color: COSMOS_HEX.slate,
    opacity: 0.35,
    highlightOpacity: 0.7,
    lineWidth: 1.2,
    dashed: true,
  },
  neutral: {
    color: COSMOS_HEX.slate,
    opacity: 0.25,
    highlightOpacity: 0.55,
    lineWidth: 1,
    dashed: false,
  },
  warning: {
    color: COSMOS_HEX.red,
    opacity: 0.85,
    highlightOpacity: 1,
    lineWidth: 1.4,
    dashed: false,
  },
};

export const LINK_DASH = { dashSize: 0.32, gapSize: 0.2 } as const;

/**
 * 라벨 depth 스케일: 카메라 거리 near 이하 1.0, far 이상 min.
 * **줄이지 않는다** (21차 · prompt_11 §3-4 「라벨 최소 13px」) — 0.82 면 13px 글자가 10.7px 로 그려졌다.
 */
export const LABEL_SCALE = { near: 12, far: 26, min: 1 } as const;
/**
 * 라벨 거리 숨김: 카메라에서 hideStart 이상 멀어지면 서서히 사라지고 hideEnd에서 완전히 숨는다.
 * 선택·hover·강조 라벨과 공고 카드는 예외다 (Focus Mode 요구사항 5·6).
 */
export const LABEL_DISTANCE_HIDE = { hideStart: 24, hideEnd: 32 } as const;
/** 좁은 화면(모바일)에서 동시에 보이는 상시 라벨 수 상한. */
export const MOBILE_LABEL_LIMIT = 3;
/**
 * 넓은 화면에서 기본으로 계속 보이는 라벨 수.
 *
 * 예전에는 상한이 «좁은 화면에만» 걸려 있어서(COMPACT_LABEL_BREAKPOINT 이하),
 * 1920×1080 데스크톱에서는 라벨 97개가 모두 배치를 시도했다. 겹침 회피가
 * 밀어내다 못해 글자가 서로 위에 얹혔고, 공고 제목조차 읽을 수 없었다.
 *
 * 항상 보이는 것은 «지금 무엇을 보고 있는가»를 말하는 것들뿐이다 —
 * 선택 공고, 참가를 막는 조건, 위험 요약, 선택한 묶음, 현재 단계.
 * 나머지는 hover·선택·키보드 탐색에서 나타난다.
 */
export const DESKTOP_LABEL_LIMIT = 6;
/** 남겨 둔다 — 다른 곳에서 「진짜 모바일」 판정에 쓸 수 있다. */
export const MOBILE_LABEL_BREAKPOINT = 640;
/**
 * 라벨 개수 상한을 거는 화면 폭.
 *
 * DashboardShell 의 compact 판정(max-width: 1023px)과 같은 값이어야 한다.
 * 예전에는 640px 이라 태블릿 폭에서만 상한이 풀려 라벨이 화면을 덮었다.
 */
export const COMPACT_LABEL_BREAKPOINT = 1023;
/** Focus Mode 순차 강조: 순서 1단계당 지연(초). 근거 → 제안서 → Auditor 경로. */
export const FOCUS_STEP_DELAY = 0.28;
export const LABEL_APPEAR_DURATION = 0.3;
export const DIMMED_LABEL_OPACITY = 0.2;

/** 선택 링 (카메라를 향하는 RingGeometry). */
export const SELECTION_RING = { scale: 1.75, innerRatio: 0.94, opacity: 0.7 } as const;

/** 라벨 충돌 회피 우선순위 (높을수록 먼저 배치). selected/hovered는 +1000. */
export const LABEL_PRIORITY: Record<CosmosNodeKind, number> = {
  notice: 100,
  // 묶음은 개별 항목보다 먼저 읽혀야 한다 — 기본 화면의 주인공이다.
  "requirement-group": 95,
  audit: 90,
  "finding-group": 88,
  proposal: 85,
  finding: 70,
  evidence: 50,
  requirement: 30,
};
