"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import * as THREE from "three";

import { formatDeadlineStamp } from "@/lib/deadline";

import type { CosmosGraph, CosmosNode, CosmosNodeKind, WorkflowStage } from "@/lib/cosmos/graph";
import { CANDIDATE_TIER_LABELS } from "@/lib/cosmos/format";
import { VERDICT_WORDS } from "@/lib/cosmos/itemTypes";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import { COSMOS_HEX, cosmosHex } from "@/lib/cosmos/theme";
import type { CosmosVocabulary } from "@/lib/cosmos/vocabulary";

import {
  DIMMED_LABEL_OPACITY,
  LABEL_APPEAR_DURATION,
  LABEL_DISTANCE_HIDE,
  LABEL_PRIORITY,
  LABEL_SCALE,
  MATERIAL_DAMP_LAMBDA,
  COMPACT_LABEL_BREAKPOINT,
  DESKTOP_LABEL_LIMIT,
  MOBILE_LABEL_LIMIT,
  type Vec3,
} from "./constants";
import { SYNTHETIC_NOTICE } from "@/lib/terms";

// ---------------------------------------------------------------------------
// 포맷
// ---------------------------------------------------------------------------

/**
 * 3D 라벨의 마감 날짜. **`lib/deadline` 이 만든다** (0920 §4-B-5 · ISSUE-078).
 *
 * 예전에는 여기 자체 포맷터가 있었고 `getFullYear()`·`getMonth()` 를 써서 **브라우저
 * 시간대**로 찍었다 — KST 고정인 다른 화면과 날짜가 하루 어긋날 수 있었다. 6차가 시간대는
 * 고쳤지만 **형식이 남았다** — 3D 카드는 「2026.09.30」(날짜만), 상세 패널은
 * 「2026. 9. 30. 오후 6:00」(12시간제)이었다.
 *
 * 입찰 마감은 10:00 과 14:00 이 다른 일이라 **시각이 빠지면 안 된다.** 라벨 폭이 좁으므로
 * 연도만 뺀 짧은 형태를 쓴다 — 상세 패널의 `formatDeadlineDateTime` 과 **같은 값**이다.
 */
export function formatDeadline(iso: string | null): string {
  return formatDeadlineStamp(iso);
}

// ---------------------------------------------------------------------------
// 라벨 전용 상수 (계약 파일에 없는 값은 여기 둔다)
// ---------------------------------------------------------------------------

/** 충돌 회피 계산 주기 (프레임). */
const COLLISION_INTERVAL_FRAMES = 10;
/** 후보 배치 간 여백 (px). */
const COLLISION_PADDING = 10;
/** 라벨 이동 판정 임계값 (px). */
const OFFSET_EPSILON = 0.5;
/**
 * 번호 칩의 크기 (px). **재지 않고 아는 값을 쓴다.**
 *
 * 칩은 `NUMBER_CHIP_CLASS` 하나로만 그려지고 그 클래스가 크기를 24×24 로 못박는다(13px 글자 · 21차).
 * 「지금 그려진 모양」을 재던 것이 진동의 원인이었다 (검수 §3 · 아래 `measureText` 주석).
 */
const NUMBER_CHIP_SIZE = 24;
/**
 * 글자↔번호 전환을 적용하기까지 같은 판정이 이어져야 하는 패스 수 (ISSUE-124 · prompt_04 §3-A-2).
 *
 * 10프레임에 한 패스이므로 6패스 ≈ 1초다. 경계에 놓인 라벨이 «들어간다/안 들어간다» 사이를
 * 오갈 때 모양까지 따라 뒤집히지 않게 막는 이력 고정(hysteresis)이다.
 *
 * 카메라가 멈춘 직후의 첫 패스는 이 규칙을 건너뛴다 — 그 패스가 처음부터 다시 푸는
 * «정답»이고, 거기서 1초를 미루면 담당자가 그동안 겹친 글자를 본다.
 */
const SHAPE_HOLD_PASSES = 6;
/** 카메라가 멈춘 뒤 배치를 다시 풀기까지 기다리는 시간 (초). */
const CAMERA_SETTLE_SECONDS = 0.3;
/**
 * 「카메라가 움직였다」로 볼 최소 변화 — 위치는 제곱 거리, 방향은 라디안.
 *
 * **사람이 볼 수 있는 크기**로 잡는다. 카메라 전환은 damp(λ=5)로 목표에 다가가므로 오차가
 * 지수로 줄어든다. 처음에 1e-6(0.001 월드 단위)으로 잡았더니 그 **수학적 꼬리**가 끝날
 * 때까지 기다렸고, 단계 2 에서 배치가 누른 뒤 **2.6초**에야 한 번 풀렸다(실측). 화면에서는
 * 그보다 1초 먼저 멈춰 보이는데도.
 *
 * 이 화면의 카메라는 그래프에서 30~60 월드 단위 떨어져 있고 fov 45° 라 화면 1px 이 약
 * 0.06 월드 단위다. 0.02 단위(=√4e-4)는 프레임당 약 0.3px — 보이지 않는다. 회전도 같은
 * 크기로 맞춘다: 5e-4rad × 40단위 ≈ 0.02 단위.
 *
 * 이보다 작게 남은 흐름은 배치를 다시 풀지 않아도 어긋나 보이지 않는다 — 라벨은 dx/dy 를
 * 그대로 두고 **노드를 따라** 같이 흐른다(위치는 drei 가 매 프레임 다시 쓴다).
 */
const CAMERA_MOVE_EPSILON_SQ = 4e-4;
const CAMERA_TURN_EPSILON = 5e-4;
/** 노드 종류별 기본 배제 반경 (월드 단위) — 평면 기호의 크기(geometries.ts)에 맞춘다. nodeRadius prop이 없을 때 쓴다. */
const DEFAULT_NODE_RADIUS: Record<CosmosNodeKind, number> = {
  notice: 0.5,
  proposal: 0.5,
  audit: 0.4,
  "requirement-group": 0.4,
  "finding-group": 0.4,
  finding: 0.28,
  evidence: 0.3,
  requirement: 0.26,
};
/** 충돌 회피에서 "주요 노드"의 원을 장애물로 취급하는 종류. */
const MAJOR_KINDS: ReadonlySet<CosmosNodeKind> = new Set(["notice", "proposal", "audit", "requirement-group", "finding-group"]);

export type LabelWeight = 400 | 500 | 600;

/** 중요도별 font-weight: L1/L2 600, L3 500, L4 400. */
export function labelWeightForKind(kind: CosmosNodeKind | undefined): LabelWeight {
  switch (kind) {
    case "notice":
    case "proposal":
    case "audit":
      return 600;
    case "finding":
    case "evidence":
      return 500;
    default:
      return 400;
  }
}

/** `#rrggbb` → `rgba(...)`. 그 외 형식은 그대로 돌려준다. */
function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(cosmosHex(color));
  if (!m) return color;
  const r = parseInt(m[1], 16);
  const g = parseInt(m[2], 16);
  const b = parseInt(m[3], 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** 글래스 칩이 읽는 CSS 변수. FloatingLabel(active/tone/weight)이 내려주고 칩이 소비한다. */
type LabelCssVars = React.CSSProperties & Record<`--${string}`, string | undefined>;

const DEFAULT_CHIP_SHADOW = "0 4px 14px rgba(0,0,0,0.35)";
const DEFAULT_CARD_SHADOW = "0 10px 28px rgba(0,0,0,0.42)";

// ---------------------------------------------------------------------------
// 충돌 회피 레지스트리
// ---------------------------------------------------------------------------

/**
 * 라벨을 노드 기준 어디에 붙이는가. `top-left` 는 라벨 **윗변**을 노드 높이에 두고 아래로 늘어뜨린다 — 키가 큰
 * 공고 카드가 위쪽 정거장 이름을 덮지 않게(21차). `left` 는 세로 가운데.
 */
export type LabelAnchor = "center" | "left" | "top-left";
/** `top-left` 라벨이 노드 높이보다 위로 올라가는 양 (px) — CSS `-translate-y-3` 과 같은 값. */
const TOP_LEFT_LIFT = 12;

/**
 * 라벨 갈래 (ISSUE-109 · prompt_01 §4-A-2).
 *
 * `short` 는 점마다 기본으로 붙는 한 줄이고, `long` 은 hover·선택에서 펴는 카드다.
 * 개수 상한(DESKTOP_LABEL_LIMIT)은 **긴 라벨에만** 건다 — 짧은 라벨까지 6개로 자르면
 * 「점 대부분에 글자가 없다」는 처음 문제로 돌아간다.
 */
export type LabelVariant = "short" | "long";

interface LabelEntry {
  id: string;
  priority: number;
  active: boolean;
  /**
   * 정거장 지도의 **지금 정거장** 라벨 (21차 · prompt_11 §3-4) — 언제나 긴 라벨이다. 번호로 줄이지 않고,
   * 긴 라벨 개수 상한에 세지 않으며, 거리로 숨기지 않는다. 배치는 다른 라벨보다 먼저 자리를 잡는다.
   */
  current: boolean;
  /** 정거장 지도의 **옆 정거장** 라벨 — 언제나 번호 칩으로 그린다 (prompt_11 §3-4 「칩 번호는 이웃 정거장에만」). */
  chip: boolean;
  alwaysOn: boolean;
  variant: LabelVariant;
  kind: CosmosNodeKind | null;
  anchorMode: LabelAnchor;
  /** 라벨 앵커 월드 좌표 (노드 + 오프셋) */
  readonly anchorWorld: THREE.Vector3;
  /** 노드 월드 좌표 */
  readonly nodeWorld: THREE.Vector3;
  /** 노드 배제 반경 (월드 단위) */
  nodeRadius: number;
  el: HTMLDivElement | null;
  /** 라벨 본문 span — 번호 칩으로 줄었을 때 «글자 모양» 을 다시 재는 데 쓴다. */
  textEl: HTMLSpanElement | null;
  /** 번호 칩 span — 글자 모양을 잴 때 잠깐 감춘다. */
  chipEl: HTMLSpanElement | null;
  /** Provider가 계산한 추가 오프셋 (px). 라벨의 useFrame이 transform에 합성한다. */
  dx: number;
  dy: number;
  /**
   * Provider가 "지금은 숨겨라"라고 판단한 라벨 (겹칠 자리가 없거나 모바일 상한 초과).
   * active(선택·hover) 라벨은 절대 숨기지 않는다.
   */
  suppressed: boolean;
  /**
   * 자리를 못 찾은 **짧은** 라벨에 매기는 번호 (ISSUE-114 · prompt_02 §4-A-1).
   *
   * 예전에는 그냥 숨겼다. 그래서 입찰 대시보드 38개 중 14~17개가 opacity 0 으로 남았고,
   * DOM 개수를 세던 검사는 그것을 「있다」고 통과시켰다. 숨기는 대신 ①②③ 로 줄이면
   * 자리를 훨씬 덜 먹어 거의 언제나 놓을 수 있고, 무엇보다 **점이 무명이 되지 않는다.**
   * null 이면 온전한 짧은 라벨이다.
   */
  numbered: number | null;
  /**
   * «글자 모양» 의 크기 (px). 한 번 재서 들고 있고, 문구가 바뀔 때만 다시 잰다.
   *
   * 배치 판정은 **언제나 이 크기**로 한다 — 지금 번호 칩으로 그려져 있어도 글자 크기를
   * 알고 있어야 「글자로 돌아갈 자리가 있는가」를 한 가지 답으로 물을 수 있다(§3-A-1).
   */
  /**
   * **배율 1 기준** 글자 크기 (px). 카메라 거리에 따른 축소는 여기 들어 있지 않다.
   *
   * 예전에는 `getBoundingClientRect()` 값을 그대로 담았다. 그 값은 CSS `scale()` 을 이미
   * 곱한 크기라 **카메라가 가까워질수록 커졌다.** 그러면 「글자가 들어가는가」의 답이
   * 카메라와 함께 바뀌어, 전환 중에 글자↔번호 결정이 몇 번씩 뒤집히고 그때마다 배치가
   * 다시 풀렸다 — 실측으로 누른 뒤 0.5초·0.7초에 라벨 3개·5개가 최대 88px·112px 을 뛰었다.
   * 배율을 떼어 두면 크기가 카메라와 무관한 값이 되고, 자리를 묻는 쪽이 필요한 배율을 곱한다.
   */
  textW: number;
  textH: number;
  /** `textW/textH` 를 잴 때의 문구. 달라지면 다시 잰다. */
  measuredText: string;
  /** 이 패스가 자리를 물을 때 쓴 배율 — 도착지 카메라 기준. */
  solveScale: number;
  /** 지금 판정이 그려진 모양과 다른 채로 이어진 패스 수 (이력 고정). */
  pendingPasses: number;
  /** 한 번이라도 모양을 정한 적이 있는가 — 첫 판정은 미루지 않고 바로 적용한다. */
  decided: boolean;
  // --- 패스 중 임시값 (할당 없이 재사용) ---
  screenX: number;
  screenY: number;
  nodeX: number;
  nodeY: number;
  nodeRadiusPx: number;
  visible: boolean;
  sortKey: number;
}

interface LabelRegistry {
  register(entry: LabelEntry): void;
  unregister(id: string): void;
  /**
   * 카메라가 **가고 있는 자리**. `CameraRig` 가 매 프레임 넣고 배치가 읽는다 (ISSUE-127).
   *
   * `null` 이면 도착지가 없다(드래그·휠·정지). 값을 **바꿔 넣는다** — 남의 객체를 고치지
   * 않는 것이 이 저장소의 규칙이고 lint 도 그것을 본다. 전환 중 프레임마다 작은 객체
   * 하나가 생기지만, 전환은 1초짜리이고 이 루프에서 다른 할당은 없다.
   */
  goalRef: MutableRefObject<CameraGoal | null>;
  /**
   * 사람이 지도를 끌고 있는가(`OrbitControls` start ~ end). `CameraRig` 가 켜고 끈다.
   * 끄는 동안 포인터가 지나가는 노드에 hover 가 걸리면 번호 칩이 글자로 펼쳐졌다 접힌다(ISSUE-141) —
   * 노드는 이 값이 참이면 hover 를 받지 않는다.
   */
  draggingRef: MutableRefObject<boolean>;
}

/**
 * 카메라 전환의 **도착지**.
 *
 * 왜 필요한가 (ISSUE-127). 배치는 카메라가 움직이는 동안 다시 풀지 않는다 — 그건 맞다
 * (ISSUE-124: 도는 중에 자리를 다시 잡으면 노드의 이동과 배치의 이동이 겹쳐 난동이 된다).
 * 그런데 멈춘 뒤 **한 번에** 다시 풀면 그 한 번이 눈에 띈다: 실측으로 라벨 12개가 같은
 * 100ms 안에 10~111px 을 함께 옮겨 갔다(2000×669 · 2단계 · 누른 뒤 1.3초. 느린 기계에서는
 * 3.7~4.0초 — 재검증 §3-2 가 본 것이 같은 한 번이다).
 *
 * 단계 전환은 **도착지를 알고 있다.** 그러면 전환 중에 이미 그 자리로 풀어 둘 수 있고,
 * 카메라가 도착할 때 라벨은 이미 제자리에 있다 — 옮겨 갈 것이 남지 않는다.
 *
 * 드래그·휠은 도착지가 없다(`active=false`). 그때는 예전 그대로 멈춘 뒤에 푼다.
 */
export interface CameraGoal {
  /** 도착 위치 (월드). */
  position: readonly [number, number, number];
  /** 도착해서 바라볼 지점 (OrbitControls 의 target). */
  target: readonly [number, number, number];
}

const LabelCollisionContext = createContext<LabelRegistry | null>(null);

/** `CameraRig` 가 도착지를 넣어 두는 자리. 문맥이 없으면 null (Canvas 밖 테스트). */
export function useCameraGoalRef(): MutableRefObject<CameraGoal | null> | null {
  return useContext(LabelCollisionContext)?.goalRef ?? null;
}

/** 지도를 끌고 있는가 — `CameraRig` 가 쓰고 노드가 읽는다 (ISSUE-141). 문맥이 없으면 null. */
export function useCameraDraggingRef(): MutableRefObject<boolean> | null {
  return useContext(LabelCollisionContext)?.draggingRef ?? null;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Circle {
  x: number;
  y: number;
  r: number;
}

function rectsIntersect(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function rectCircleIntersect(rect: Rect, c: Circle): boolean {
  const cx = Math.max(rect.x, Math.min(c.x, rect.x + rect.w));
  const cy = Math.max(rect.y, Math.min(c.y, rect.y + rect.h));
  const dx = c.x - cx;
  const dy = c.y - cy;
  return dx * dx + dy * dy < c.r * c.r;
}

/**
 * 월드 좌표 → 캔버스 px. drei Html의 기본 calculatePosition과 같은 식.
 * 반환값은 NDC z (카메라 뒤/클립 밖 판정용).
 */
function projectToScreen(
  world: THREE.Vector3,
  camera: THREE.Camera,
  width: number,
  height: number,
  scratch: THREE.Vector3,
  out: { x: number; y: number },
): number {
  scratch.copy(world).project(camera);
  out.x = scratch.x * (width / 2) + width / 2;
  out.y = -(scratch.y * (height / 2)) + height / 2;
  return scratch.z;
}

/** 월드 반경 → 화면 px 반경 (원근 카메라 기준). */
function worldRadiusToPx(
  radius: number,
  world: THREE.Vector3,
  camera: THREE.Camera,
  height: number,
): number {
  if (!(camera instanceof THREE.PerspectiveCamera)) return radius * 20;
  const distance = camera.position.distanceTo(world);
  if (distance < 1e-3) return 0;
  const halfHeightWorld = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * distance;
  return (radius / halfHeightWorld) * (height / 2);
}

/**
 * 라벨 충돌 회피 Provider. Canvas 안(R3F 트리)에서 Scene을 감싼다.
 * labelId를 가진 FloatingLabel만 등록되며, 10프레임마다 화면 좌표 기반 greedy 배치를 1회 계산해
 * 각 entry의 dx/dy(px)에 기록한다. 라벨은 자기 useFrame에서 그 값을 transform에 합성한다.
 * setState 없음 — 모든 결과는 ref/entry 객체에만 쓴다.
 */
interface CollisionScratch {
  vec: THREE.Vector3;
  point: { x: number; y: number };
  base: Rect;
  candidate: Rect;
  ownCircle: Circle;
  placed: Rect[];
  circles: Circle[];
  order: LabelEntry[];
  /** `findSpot` 의 결과 — 절대 좌표와 기본 위치에서의 오프셋. */
  spot: { x: number; y: number; dx: number; dy: number; found: boolean };
  /** 목표 카메라 사본 — 전환 중에 «도착한 뒤의 화면»으로 투영할 때 쓴다 (ISSUE-127). */
  goalCamera: THREE.PerspectiveCamera;
}

function createScratch(): CollisionScratch {
  return {
    vec: new THREE.Vector3(),
    point: { x: 0, y: 0 },
    base: { x: 0, y: 0, w: 0, h: 0 },
    candidate: { x: 0, y: 0, w: 0, h: 0 },
    ownCircle: { x: 0, y: 0, r: 0 },
    placed: [],
    circles: [],
    order: [],
    spot: { x: 0, y: 0, dx: 0, dy: 0, found: false },
    goalCamera: new THREE.PerspectiveCamera(),
  };
}

/**
 * 살아 있는 카메라의 렌즈를 그대로 쓰면서 **도착지 자세**를 가진 사본.
 *
 * 렌즈(fov·aspect·near·far)는 지금 것과 같다 — 바뀌는 것은 어디서 어디를 보는가뿐이다.
 * 위쪽은 월드 Y 로 둔다(`OrbitControls` 와 같은 규칙).
 */
function poseGoalCamera(
  goalCamera: THREE.PerspectiveCamera,
  live: THREE.Camera,
  goal: CameraGoal,
): THREE.PerspectiveCamera {
  const [px, py, pz] = goal.position;
  const [tx, ty, tz] = goal.target;
  if (live instanceof THREE.PerspectiveCamera) {
    goalCamera.fov = live.fov;
    goalCamera.aspect = live.aspect;
    goalCamera.near = live.near;
    goalCamera.far = live.far;
    goalCamera.zoom = live.zoom;
  }
  goalCamera.position.set(px, py, pz);
  goalCamera.up.set(0, 1, 0);
  goalCamera.lookAt(tx, ty, tz);
  goalCamera.updateProjectionMatrix();
  // 카메라의 `updateMatrixWorld` 는 `matrixWorldInverse` 까지 갱신한다 — 투영이 그것을 쓴다.
  goalCamera.updateMatrixWorld(true);
  return goalCamera;
}

/**
 * 주어진 **크기**로 빈자리를 찾는다. 후보 순서: 기본 → 위 → 아래 → 오른쪽 → 왼쪽.
 * (발견 라벨을 점검 허브 바깥으로 미는 radial 후보는 없앴다 — 정거장 지도에서는 허브가 원점에 있지 않아
 * 발견 라벨이 옆 정거장으로 밀려났다. 21차)
 *
 * 크기를 인자로 받는 것이 이 핫픽스의 절반이다. 예전에는 «지금 그려진 모양» 을 재서 넣었고,
 * 그래서 같은 라벨이 패스마다 다른 크기로 물어보게 됐다 — 칩 크기로는 자리가 있고 글자
 * 크기로는 없으니 10프레임 주기로 뒤집혔다. 이제 판정은 항상 글자 크기로 묻고(§3-A-1),
 * 그려질 모양이 칩이면 칩 크기로 한 번 더 물어 **칩이 앉을 자리**를 정한다.
 */
function findSpot(
  entry: LabelEntry,
  w: number,
  h: number,
  scratch: CollisionScratch,
  width: number,
  height: number,
): void {
  const { base, candidate, ownCircle, placed, circles, spot } = scratch;
  base.w = w;
  base.h = h;
  base.y = entry.anchorMode === "top-left" ? entry.screenY - TOP_LEFT_LIFT : entry.screenY - h / 2;
  base.x = entry.anchorMode === "center" ? entry.screenX - w / 2 : entry.screenX;

  ownCircle.x = entry.nodeX;
  ownCircle.y = entry.nodeY;
  ownCircle.r = entry.nodeRadiusPx;

  const gap = entry.nodeRadiusPx + COLLISION_PADDING;
  const nx = entry.nodeX;
  const ny = entry.nodeY;

  spot.x = base.x;
  spot.y = base.y;
  spot.found = false;

  for (let step = 0; step < 5 && !spot.found; step += 1) {
    switch (step) {
      case 0:
        candidate.x = base.x;
        candidate.y = base.y;
        break;
      case 1:
        candidate.x = nx - w / 2;
        candidate.y = ny - gap - h;
        break;
      case 2:
        candidate.x = nx - w / 2;
        candidate.y = ny + gap;
        break;
      case 3:
        candidate.x = nx + gap;
        candidate.y = ny - h / 2;
        break;
      default:
        candidate.x = nx - gap - w;
        candidate.y = ny - h / 2;
        break;
    }
    candidate.w = w;
    candidate.h = h;

    if (candidate.x < 0 || candidate.y < 0 || candidate.x + w > width || candidate.y + h > height) {
      continue;
    }
    let blocked = false;
    for (let p = 0; p < placed.length && !blocked; p += 1) {
      blocked = rectsIntersect(candidate, placed[p]);
    }
    for (let c = 0; c < circles.length && !blocked; c += 1) {
      blocked = rectCircleIntersect(candidate, circles[c]);
    }
    if (!blocked && !(entry.kind && MAJOR_KINDS.has(entry.kind))) {
      blocked = rectCircleIntersect(candidate, ownCircle);
    }
    if (!blocked) {
      spot.x = candidate.x;
      spot.y = candidate.y;
      spot.found = true;
    }
  }

  spot.dx = spot.x - base.x;
  spot.dy = spot.y - base.y;
}

/**
 * «글자 모양» 의 크기를 재서 entry 에 둔다 (§3-A-1).
 *
 * ## 왜 캐시가 필요한가
 *
 * 예전에는 패스마다 컨테이너를 `getBoundingClientRect()` 로 쟀다(labels.tsx 338-339).
 * 번호 칩으로 줄어 있으면 그 값이 **칩 크기**였다 — 22×22 로는 자리가 있으니 다음 패스에
 * 글자로 돌아가고, 글자 크기로는 자리가 없으니 다시 칩이 되어 10프레임 주기로 뒤집혔다.
 * 담당자가 본 「제목이 마구잡이로 흔들리고 난동부리는」 것이 이것이다.
 *
 * 글자가 그려져 있는 동안은 컨테이너가 곧 글자 모양이라 그대로 잰다. 칩으로 줄어 있고
 * **문구까지 바뀐** 드문 경우에만 잠깐 되돌려 재고 즉시 복구한다 — 되돌리지 않으면
 * 바뀐 문구를 옛 크기로 재게 된다.
 */
function measureText(entry: LabelEntry): void {
  const el = entry.el;
  if (!el) return;
  const text = entry.textEl;
  if (entry.numbered === null) {
    const rect = el.getBoundingClientRect();
    store(entry, rect, text?.textContent ?? "");
    return;
  }
  const current = text?.textContent ?? "";
  if (entry.textW > 0 && current === entry.measuredText) return;
  if (!text) return;
  const chip = entry.chipEl;
  const textDisplay = text.style.display;
  const chipDisplay = chip?.style.display;
  text.style.display = "";
  if (chip) chip.style.display = "none";
  const rect = el.getBoundingClientRect();
  text.style.display = textDisplay;
  if (chip && chipDisplay !== undefined) chip.style.display = chipDisplay;
  store(entry, rect, current);
}

/**
 * 잰 사각형을 **배율 1 기준**으로 바꿔 담는다 (ISSUE-127).
 *
 * `getBoundingClientRect()` 는 CSS `scale()` 을 곱한 크기다. 그대로 담으면 카메라가
 * 가까워질 때 「글자가 들어가는가」의 답이 함께 바뀌어 배치가 카메라를 따라 흔들린다.
 */
function store(entry: LabelEntry, rect: DOMRect, text: string): void {
  if (rect.width <= 0 || rect.height <= 0) return;
  const scale = appliedScale(entry.el);
  entry.textW = rect.width / scale;
  entry.textH = rect.height / scale;
  entry.measuredText = text;
}

/**
 * 지금 **DOM 에 적용돼 있는** 배율. transform 이 없으면 1.
 *
 * 라벨이 자기 프레임 루프에서 쓴 값을 그대로 읽는다 — 그쪽에서 전해 받지 않는 이유는
 * 「실제로 적용된 값」이 여기 있기 때문이다. 라벨은 변화가 작으면(0.004) transform 을 다시
 * 쓰지 않으므로, 계산값을 전해 받으면 잰 사각형과 어긋난 배율로 나누게 된다.
 */
function appliedScale(el: HTMLElement | null): number {
  const transform = el?.style.transform;
  if (!transform) return 1;
  const start = transform.indexOf("scale(");
  if (start < 0) return 1;
  const value = Number.parseFloat(transform.slice(start + 6));
  return Number.isFinite(value) && value > 0.01 ? value : 1;
}

/**
 * 거리에 따른 라벨 배율. 라벨 자신과 배치 패스가 **같은 셈**을 쓴다 (ISSUE-127).
 *
 * 배치는 도착지 카메라로 이 값을 내고, 라벨은 지금 카메라로 낸다. 전환이 끝나면 둘이
 * 같아지므로 도착할 때 크기도 자리도 맞아 있다.
 */
function labelScaleAt(camera: THREE.Camera, anchorWorld: THREE.Vector3): number {
  const distance = camera.position.distanceTo(anchorWorld);
  const t = THREE.MathUtils.clamp(
    (distance - LABEL_SCALE.near) / (LABEL_SCALE.far - LABEL_SCALE.near),
    0,
    1,
  );
  return 1 - t * (1 - LABEL_SCALE.min);
}

/**
 * 노드 id 의 번호 (§3-A-4).
 *
 * 예전에는 패스마다 0 부터 다시 세어 같은 점이 ②였다가 ④가 됐다(검수 §3 · labels.tsx 371·378·488).
 * 이제 id 마다 한 번 정하고, 그 라벨이 번호로 있는 동안 바뀌지 않는다.
 *
 * 글자로 돌아가면 번호를 **놓아 준다** — 번호는 일련번호가 아니라 「지금 줄여 둔 것이
 * 몇 개인가」를 읽는 표시다. 놓지 않으면 화면을 오래 켜 둘수록 ⑳ 을 넘어 「(37)」 이 된다.
 */
function takeNumber(id: string, numbers: Map<string, number>): number {
  const existing = numbers.get(id);
  if (existing !== undefined) return existing;
  const used = new Set(numbers.values());
  let next = 1;
  while (used.has(next)) next += 1;
  numbers.set(id, next);
  return next;
}

/**
 * 모양을 바꿀지 정한다 — 이력 고정 (§3-A-2). 돌려주는 값은 «번호로 그린다» 인가.
 *
 * 첫 판정과 카메라가 멈춘 직후(`immediate`)는 바로 적용하고, 그 밖의 뒤집기는 같은 판정이
 * `SHAPE_HOLD_PASSES` 번 이어질 때만 적용한다.
 */
function applyShape(
  entry: LabelEntry,
  want: boolean,
  numbers: Map<string, number>,
  immediate: boolean,
): boolean {
  const isNumber = entry.numbered !== null;
  if (want === isNumber) {
    entry.pendingPasses = 0;
    entry.decided = true;
    return isNumber;
  }
  entry.pendingPasses += 1;
  if (!entry.decided || immediate || entry.pendingPasses >= SHAPE_HOLD_PASSES) {
    entry.pendingPasses = 0;
    entry.decided = true;
    if (want) {
      entry.numbered = takeNumber(entry.id, numbers);
    } else {
      entry.numbered = null;
      numbers.delete(entry.id);
    }
    return want;
  }
  return isNumber;
}

export function LabelCollisionProvider({ children, resetKey }: { children: ReactNode; resetKey?: string | number }) {
  const entriesRef = useRef<Map<string, LabelEntry>>(new Map());
  const frameRef = useRef(0);
  /** 패스용 임시 객체 — 첫 프레임에 한 번 만들고 재사용 (프레임당 할당 없음). */
  const scratchRef = useRef<CollisionScratch | null>(null);
  /** 노드 id → 번호. 번호로 줄어 있는 동안 바뀌지 않는다 (§3-A-4). */
  const numbersRef = useRef<Map<string, number>>(new Map());
  /** 카메라가 지난 프레임에 어디를 보고 있었나 — 「움직이는 중」 판정용. */
  const cameraRef = useRef({ pos: new THREE.Vector3(), quat: new THREE.Quaternion(), ready: false });
  /** 카메라가 멈춘 시각(초). 움직이는 동안은 null. */
  const stillSinceRef = useRef<number | null>(null);
  /** 멈춘 뒤 «처음부터 다시 푸는» 패스를 이미 돌렸는가. */
  const resolvedRef = useRef(false);
  /** 지난 프레임에 «도착지를 아는 전환»이 진행 중이었나 — 시작하는 순간을 잡는다 (ISSUE-127). */
  const goalWasActiveRef = useRef(false);
  /** 지난 패스의 라벨 수 — 붙거나 떨어졌으면 이력 고정을 건너뛴다 (ISSUE-127). */
  const labelCountRef = useRef(-1);
  /** 지난 패스에서 **크기를 잴 수 있었던** 라벨 수. 등록 수와 다르다 (아래 주석). */
  const measurableRef = useRef(-1);
  /** `CameraRig` 가 넣어 주는 도착지 (없으면 null). */
  const goalRef = useRef<CameraGoal | null>(null);
  const draggingRef = useRef(false);
  const sizeRef = useRef({ width: 0, height: 0 });

  /* 정거장이 바뀌면 노드가 새 자리로 옮겨 간다 — 카메라가 거의 그대로여도 **처음부터 다시 푼다**(21차).
     기다리면 이력 고정(6패스 ≈ 1초) 뒤에야 옮겨 가, 누른 뒤 한참 있다가 라벨이 뛰는 것으로 보인다. */
  useEffect(() => {
    resolvedRef.current = false;
  }, [resetKey]);

  const registry = useMemo<LabelRegistry>(
    () => ({
      register: (entry) => {
        entriesRef.current.set(entry.id, entry);
      },
      unregister: (id) => {
        entriesRef.current.delete(id);
        // 번호도 놓아 준다 — 떠난 노드가 번호를 물고 있으면 남은 라벨이 큰 수를 받는다.
        numbersRef.current.delete(id);
      },
      goalRef,
      draggingRef,
    }),
    [goalRef, draggingRef],
  );

  useFrame(({ camera, size, clock }) => {
    /* 카메라는 **매 프레임** 본다. 10프레임마다 보면 느린 이동을 정지로 읽는다.
       OrbitControls 는 `enableDamping` 이라 손을 뗀 뒤에도 잠시 더 흐르고,
       CameraRig 의 tween 도 damp 로 다가간다 — 둘 다 여기서 「움직이는 중」으로 잡힌다. */
    const cam = cameraRef.current;
    const moved =
      !cam.ready ||
      camera.position.distanceToSquared(cam.pos) > CAMERA_MOVE_EPSILON_SQ ||
      camera.quaternion.angleTo(cam.quat) > CAMERA_TURN_EPSILON;
    cam.pos.copy(camera.position);
    cam.quat.copy(camera.quaternion);
    cam.ready = true;

    /* 카메라가 움직이는 동안은 배치를 **다시 풀지 않는다** (§3-A-3).
       라벨은 마지막 dx/dy 를 그대로 쓰며 노드를 따라만 간다 — 카메라가 도는 중에 자리를
       다시 잡으면 노드의 이동과 배치의 이동이 겹쳐 「난동」으로 보인다. 드래그·휠·단계
       전환이 모두 이 한 가지 판정에 들어온다(그때마다 카메라가 움직이므로). */
    /* **도착지를 아는 전환은 미리 푼다** (ISSUE-127 · prompt_05 §4-C-2 (가)).

       단계 전환은 어디로 가는지 알고 있다(`CameraRig` 의 tween). 그러면 전환 중에 이미
       «도착한 뒤의 화면»으로 배치를 풀어 둘 수 있고, 카메라가 도착할 때 라벨은 이미 제자리다.
       예전에는 멈출 때까지 기다렸다가 한 번에 풀어서, 그 한 번이 라벨 12개를 같은 100ms 안에
       10~111px 옮겼다(실측). 사람 눈에는 「멈춘 뒤 한 박자 있다가 툭 옮겨간다」로 보인다.

       (나)안(멈춤 판정을 1초로 줄이고 첫 배치를 프레임당 40px 로 나눠 옮기기)을 쓰지 않은
       이유: 옮기는 총량이 그대로라 100ms 표본에는 여전히 100px 대가 찍히고, 무엇보다
       「제자리에 있다」가 아니라 「천천히 옮겨간다」가 된다. 도착지를 아는데 굳이 옮길 이유가 없다.

       드래그·휠은 도착지가 없다 — `goal.active` 가 거짓이고, 그때는 예전 그대로 멈춘 뒤 푼다. */
    const goal = goalRef.current;
    const solveCamera = goal
      ? poseGoalCamera((scratchRef.current ??= createScratch()).goalCamera, camera, goal)
      : camera;
    /* 전환이 **시작된 프레임**에 처음부터 다시 푼다. 이 한 줄이 없으면 바로 앞이 정지
       상태였을 때 `resolvedRef` 가 참으로 남아 있어 최대 10프레임을 기다린다 — 그 사이
       라벨은 옛 자리에 있고, 도착지로 푸는 의미가 그만큼 늦어진다. */
    if (goal !== null && !goalWasActiveRef.current) resolvedRef.current = false;
    goalWasActiveRef.current = goal !== null;

    if (moved && goal === null) {
      stillSinceRef.current = null;
      resolvedRef.current = false;
      return;
    }
    const now = clock.elapsedTime;
    if (goal !== null) {
      /* 전환이 시작되면 **그 프레임에** 한 번 처음부터 푼다. 도착지는 바뀌지 않으므로
         이 답이 전환이 끝난 뒤의 답과 같다 — 그래서 도착할 때 옮겨 갈 것이 없다. */
      if (!resolvedRef.current) stillSinceRef.current = null;
    } else {
      if (stillSinceRef.current === null) stillSinceRef.current = now;
      if (now - stillSinceRef.current < CAMERA_SETTLE_SECONDS) return;
    }

    /* 창 크기가 바뀌면 카메라는 가만히 있어도 화면 좌표가 달라진다 — 다시 푼다. */
    const sizeChanged = sizeRef.current.width !== size.width || sizeRef.current.height !== size.height;
    sizeRef.current.width = size.width;
    sizeRef.current.height = size.height;

    /* **라벨이 붙거나 떨어졌는가.** 바뀌었으면 입력이 달라진 것이므로 이력 고정을 건너뛴다
       (ISSUE-127 · prompt_05 §4-C).

       왜 이것이 필요한가. 단계를 누르면 노드와 라벨이 0.3초 남짓에 걸쳐 새로 붙는다. 그
       변화를 이력 고정(6패스 ≈ 1초)에 맡기면 글자↔번호 결정이 **1초 뒤에** 떨어지고, 그때
       크기가 바뀌면서 배치가 다시 풀려 라벨 여럿이 함께 옮겨 간다 — 실측으로 라벨이 붙은
       0.3초 뒤인 0.6초·1.3초에 각각 7개·3개가 최대 119px·94px 을 뛰었다.

       이력 고정은 「같은 입력에서 경계에 놓인 라벨이 오가는 것」을 막기 위한 것이다.
       입력 자체가 달라졌을 때는 미룰 이유가 없다 — 미루면 오히려 그 한 번이 늦게, 따로
       터진다. 그래서 라벨 수가 바뀐 패스는 그 자리에서 끝까지 푼다. */
    const setChanged = labelCountRef.current !== entriesRef.current.size;
    labelCountRef.current = entriesRef.current.size;

    /* 멈춘 뒤 첫 패스(또는 창 크기·라벨 구성이 바뀐 직후)는 이력 고정을 건너뛰고 처음부터 푼다.
       이 한 패스가 우선순위 순으로 위에서 아래로 내려가며 스스로 앞뒤가 맞는 답을 만든다 —
       그 뒤 같은 입력이 이어지는 동안 결과는 한 글자도 바뀌지 않는다. */
    const passImmediate = !resolvedRef.current || sizeChanged || setChanged;
    frameRef.current += 1;
    if (!passImmediate && frameRef.current % COLLISION_INTERVAL_FRAMES !== 0) return;
    resolvedRef.current = true;

    const entries = entriesRef.current;
    if (entries.size === 0) return;

    if (!scratchRef.current) scratchRef.current = createScratch();
    const scratch = scratchRef.current;
    const { vec, point, placed, circles, order, spot } = scratch;
    const width = size.width;
    const height = size.height;
    placed.length = 0;
    circles.length = 0;
    order.length = 0;

    // 1) 투영 + 측정 (라벨당 getBoundingClientRect 1회)
    for (const entry of entries.values()) {
      const el = entry.el;
      if (!el) {
        entry.visible = false;
        continue;
      }
      const z = projectToScreen(entry.anchorWorld, solveCamera, width, height, vec, point);
      entry.screenX = point.x;
      entry.screenY = point.y;
      projectToScreen(entry.nodeWorld, solveCamera, width, height, vec, point);
      entry.nodeX = point.x;
      entry.nodeY = point.y;
      entry.nodeRadiusPx = worldRadiusToPx(entry.nodeRadius, entry.nodeWorld, solveCamera, height);
      /* 재는 것은 «글자 모양» 하나뿐이다 — 지금 칩으로 그려져 있어도 글자 크기를 안다.
         이것이 10프레임 주기 진동을 끊는 자리다(`measureText` 주석). */
      measureText(entry);
      /* 자리를 묻는 크기는 **도착지에서 그려질 크기**다 — 지금 크기가 아니다.
         전환 중에 지금 크기로 물으면 답이 카메라와 함께 바뀌어 배치가 흔들린다. */
      entry.solveScale = labelScaleAt(solveCamera, entry.anchorWorld);
      entry.visible = z > -1 && z < 1 && entry.textW > 0 && entry.textH > 0;
      if (!entry.visible) {
        entry.dx = 0;
        entry.dy = 0;
        continue;
      }
      entry.sortKey = entry.priority + (entry.active ? 1000 : 0) + (entry.current ? 500 : 0);
      order.push(entry);
      if (entry.kind && MAJOR_KINDS.has(entry.kind)) {
        circles.push({ x: entry.nodeX, y: entry.nodeY, r: entry.nodeRadiusPx });
      }
    }
    if (order.length === 0) return;
    order.sort((a, b) => b.sortKey - a.sortKey);

    /* **잴 수 있는 라벨이 몇 개인가.** 등록 수(`entries.size`)와 다르다 — 라벨은 등록된 뒤
       한두 프레임 동안 크기를 잴 수 없고(아직 그려지지 않았다), 그 동안은 배치에 끼지 않는다.
       그래서 등록 수만 보면 「입력이 그대로인데 답이 달라지는」 패스가 생긴다: 새 라벨이
       뒤늦게 배치에 들어와 다른 라벨의 자리를 빼앗고, 그 결과로 바뀐 글자↔번호 결정은
       이력 고정(6패스 ≈ 1초)에 걸려 **1초 뒤에** 적용된다. 실측으로 1440×900 · 1단계에서
       라벨 둘이 그렇게 늦게 모양을 바꿨다.

       잴 수 있는 수가 바뀐 패스도 그 자리에서 끝까지 푼다 — 미룰 이유가 없다 (ISSUE-127). */
    const measurableChanged = measurableRef.current !== order.length;
    measurableRef.current = order.length;
    const immediate = passImmediate || measurableChanged;

    // 좁은 화면에서는 우선순위 상위 N개(+ 활성 라벨)만 남긴다 — 3D 라벨이 화면을 덮지 않게.
    //
    // 기준을 셸의 compact 판정(1023px)과 맞춘다. 예전에는 640px 이라
    // 태블릿 폭(640~1023px)에서만 상한이 풀려 라벨이 화면을 덮었다.
    // 상한은 **넓은 화면에도** 건다. 예전에는 좁은 화면에만 걸려 있어서
    // 1920×1080 에서 라벨 97개가 모두 배치를 시도했고, 겹침 회피가 밀어내다 못해
    // 글자가 서로 위에 얹혀 공고 제목조차 읽을 수 없었다.
    const mobile = width <= COMPACT_LABEL_BREAKPOINT;
    const limit = mobile ? MOBILE_LABEL_LIMIT : DESKTOP_LABEL_LIMIT;
    // 상한은 «긴 라벨»에만 건다. 짧은 라벨은 전부 배치를 시도하고, 자리를 못 찾은 것만
    // 숨는다 — 개수로 미리 자르지 않는다(prompt_01 §4-A-2).
    let shownLong = 0;

    // 2) greedy 배치 — 우선순위 순으로 내려가며 **한 패스 안에서** 앞뒤가 맞게 푼다.
    for (const entry of order) {
      /* 자리를 묻는 크기는 언제나 «글자 모양» 이다 — 지금 칩으로 그려져 있어도 마찬가지다.
         이것이 진동의 뿌리를 끊는다: 「글자로 돌아갈 자리가 있는가」에 답이 하나가 된다. */
      findSpot(entry, entry.textW * entry.solveScale, entry.textH * entry.solveScale, scratch, width, height);
      const textFits = spot.found;
      /* 상한을 넘은 긴 라벨은 **사라지지 않고** 번호로 줄어든다. 상한의 목적은
         화면이 글자로 덮이지 않게 하는 것이지 점을 무명으로 만드는 것이 아니다. */
      const overLimit = !entry.active && !entry.current && entry.variant === "long" && shownLong >= limit;
      /* 자리를 못 찾아도 숨기지 않는다 — 번호로 줄인다. 번호 칩은 작아서 대개 들어간다.
         「라벨 없는 점」을 만들지 않는 것이 규칙이고, 활성(hover·선택) 라벨만 예외로
         온전한 모양을 지킨 채 겹쳐 그린다. 그건 사용자가 지금 보려는 것이므로. */
      const want = (entry.chip && !entry.active) || overLimit || (!textFits && !entry.active && !entry.current);
      const asNumber = applyShape(entry, want, numbersRef.current, immediate);

      let w = entry.textW * entry.solveScale;
      let h = entry.textH * entry.solveScale;
      if (asNumber) {
        /* 그려질 모양이 칩이면 **칩 크기로 한 번 더** 물어 칩이 앉을 자리를 정한다.
           예전에는 번호로 줄인 라벨을 `dx=dy=0` 으로 두고 `placed` 에도 넣지 않았다
           (검수 §3 · labels.tsx 376-383·488-491) — 칩이 다른 라벨 위에 얹혔고, 장애물
           목록에서 빠져 있어 **다른 라벨의 자리가 패스마다 달라졌다.** */
        w = NUMBER_CHIP_SIZE;
        h = NUMBER_CHIP_SIZE;
        findSpot(entry, w, h, scratch, width, height);
      }

      entry.dx = spot.dx;
      entry.dy = spot.dy;
      /* 숨김은 더 쓰지 않는다 — 번호가 그 자리를 대신한다. 필드는 등록 해제 경로가 쓰므로 남긴다. */
      entry.suppressed = false;
      if (!asNumber && entry.variant === "long" && !entry.current) shownLong += 1;
      // 상시 라벨만 다른 라벨을 밀어낸다 (hover 라벨은 장애물이 되지 않아 배치 요동을 막는다).
      if (entry.alwaysOn || entry.active) {
        placed.push({ x: spot.x, y: spot.y, w, h });
      }
    }
  });

  return (
    <LabelCollisionContext.Provider value={registry}>{children}</LabelCollisionContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// 공통 라벨 래퍼
// ---------------------------------------------------------------------------

interface FloatingLabelProps {
  /** 노드 월드 좌표 (거리 계산용) */
  nodePosition: Vec3;
  /** 노드 기준 라벨 오프셋 (Html은 노드 group의 자식) */
  offset: Vec3;
  anchor: LabelAnchor;
  dimmed: boolean;
  reducedMotion: boolean;
  /** 등장 지연(초) — 노드의 stagger와 맞춘다 */
  appearDelay: number;
  children: ReactNode;
  // --- v2 선택 props (없으면 기존 동작 그대로) ---
  /** 주어지면 LabelCollisionProvider에 등록되어 충돌 회피 대상이 된다. */
  labelId?: string;
  /** 배치 우선순위 (기본 LABEL_PRIORITY[kind]). selected/hovered는 +1000. */
  priority?: number;
  /** 노드 배제 반경 (월드 단위). 매 패스마다 화면 px로 투영한다. 기본값은 종류별. */
  nodeRadius?: number;
  /** 상시 라벨 여부 (기본 true). false면 배치는 되지만 다른 라벨을 밀어내지 않는다. */
  alwaysOn?: boolean;
  /** 짧은 라벨인가 긴 라벨인가 (기본 long). 개수 상한은 긴 라벨에만 건다. */
  variant?: LabelVariant;
  /** 노드 종류 — 우선순위·weight·finding radial 배치에 쓴다. */
  kind?: CosmosNodeKind;
  /** 활성(hover/selected) 시 글로우 색 (상태색 hex). */
  tone?: string;
  /** hovered/selected 여부 — tone 글로우 + 최우선 배치. */
  active?: boolean;
  /** 중요도별 font-weight. 없으면 kind에서 파생. */
  weight?: LabelWeight;
  /** 핵심 라벨: 카메라 거리와 무관하게 항상 보인다 (공고 카드와 같은 취급). */
  persistent?: boolean;
  /** 흐림 상태에서의 최소 불투명도 (기본 DIMMED_LABEL_OPACITY). 핵심 라벨은 더 진하게 남긴다. */
  dimmedOpacity?: number;
  /** 정거장 지도의 지금 정거장 라벨 — 언제나 긴 라벨 (LabelEntry.current) */
  current?: boolean;
  /** 정거장 지도의 옆 정거장 라벨 — 언제나 번호 칩 (LabelEntry.chip). hover·선택하면 글자로 편다 */
  chip?: boolean;
  /** 이 라벨이 선 정거장 — DOM 에 `data-cosmos-station` 으로 적는다(라벨 검사가 지금 정거장 라벨을 센다) */
  station?: number;
  /** 긴 라벨 최대 폭(px) — 두 열로 선 정거장은 좁다 */
  maxWidth?: number;
  /**
   * 주면 이름표를 눌러 고른다(27차 검수 R27D-OWN-02) — 「선은 항목을 누르면 보입니다」인데 받는 곳이 6px 기호뿐이었다.
   * 캔버스를 감싼 div 의 끌어 돌리기 · 선택 풀기(onPointerMissed)로 번지지 않게 pointer 이벤트를 막는다.
   */
  onPick?: () => void;
}

const NO_POINTER: React.CSSProperties = { pointerEvents: "none" };
/** 번호 칩은 기본으로 숨어 있다 — 자리를 못 찾은 짧은 라벨에서만 드러난다. */
const NUMBER_HIDDEN: React.CSSProperties = { display: "none" };
/** 번호 칩 모양. 13px · 대비 4.5:1 (21차). 크기는 24×24 로 못박는다 — `NUMBER_CHIP_SIZE`. */
const NUMBER_CHIP_CLASS =
  "inline-flex h-6 min-w-6 items-center justify-center rounded-full border border-cosmos-border-strong bg-cosmos-panel/95 px-1 text-[13px] font-semibold leading-none text-cosmos-text";

/**
 * ①②③… 로 줄인 번호. 20 을 넘으면 「(21)」처럼 적는다 — 원문자가 ⑳ 까지뿐이다.
 */
export function circledNumber(n: number): string {
  return n >= 1 && n <= 20 ? String.fromCharCode(0x2460 + n - 1) : `(${n})`;
}
const HIDDEN_START: React.CSSProperties = { pointerEvents: "none", opacity: 0 };
const stopEvent = (event: React.SyntheticEvent) => event.stopPropagation();
const VISIBLE_START: React.CSSProperties = { pointerEvents: "none", opacity: 1 };

function easeOutCubic(t: number): number {
  const u = 1 - t;
  return 1 - u * u * u;
}

/** 배치 entry 에 라벨 요소를 이어 준다 — 프레임 루프에서 부르므로 컴포넌트 밖에 둔다(훅 값 직접 수정 금지 lint). */
function attachElements(entry: LabelEntry, el: HTMLDivElement, text: HTMLSpanElement | null, chip: HTMLSpanElement | null): void {
  entry.el = el;
  entry.textEl = text;
  entry.chipEl = chip;
}

function createEntry(id: string): LabelEntry {
  return {
    id,
    priority: 0,
    active: false,
    current: false,
    chip: false,
    alwaysOn: true,
    variant: "long",
    kind: null,
    anchorMode: "center",
    anchorWorld: new THREE.Vector3(),
    nodeWorld: new THREE.Vector3(),
    nodeRadius: 0.3,
    el: null,
    textEl: null,
    chipEl: null,
    dx: 0,
    dy: 0,
    suppressed: false,
    numbered: null,
    textW: 0,
    solveScale: 1,
    textH: 0,
    measuredText: "",
    pendingPasses: 0,
    decided: false,
    screenX: 0,
    screenY: 0,
    nodeX: 0,
    nodeY: 0,
    nodeRadiusPx: 0,
    visible: false,
    sortKey: 0,
  };
}

/**
 * drei Html 래퍼. 레이캐스트 대상이 아니며(pointerEvents none),
 * 카메라 거리에 따라 0.82~1.0 사이로만 살짝 줄어든다 (가독성 우선).
 * 투명도(등장·흐림)는 useFrame에서 ref로만 갱신한다 — setState 없음.
 * labelId가 있으면 충돌 회피 오프셋(dx/dy px)을 같은 transform에 합성한다.
 */
export function FloatingLabel({
  nodePosition,
  offset,
  anchor,
  dimmed,
  reducedMotion,
  appearDelay,
  children,
  labelId,
  priority,
  nodeRadius,
  alwaysOn = true,
  variant = "long",
  kind,
  tone,
  active = false,
  weight,
  persistent = false,
  dimmedOpacity,
  current = false,
  chip = false,
  station,
  maxWidth,
  onPick,
}: FloatingLabelProps) {
  const innerRef = useRef<HTMLDivElement>(null);
  /** 짧은 라벨 본문과 번호 칩. 배치 결과에 따라 프레임 루프가 하나만 보인다. */
  const fullRef = useRef<HTMLSpanElement>(null);
  const numberRef = useRef<HTMLSpanElement>(null);
  const appliedNumberRef = useRef<number | null>(null);
  const scaleRef = useRef(1);
  const appliedDxRef = useRef(0);
  const appliedDyRef = useRef(0);
  const opacityRef = useRef(1);
  const appliedOpacityRef = useRef(-1);
  const appearStartRef = useRef<number | null>(null);
  const anchorVec = useRef<THREE.Vector3 | null>(null);

  const registry = useContext(LabelCollisionContext);
  const registered = Boolean(labelId && registry);
  /** 충돌 회피 entry — 렌더 중에는 만들지 않고 layout effect에서 (재)생성한다. */
  const entryRef = useRef<LabelEntry | null>(null);

  const effectiveOffset = offset;
  const resolvedWeight = weight ?? labelWeightForKind(kind);
  const resolvedRadius = nodeRadius ?? (kind ? DEFAULT_NODE_RADIUS[kind] : 0.3);
  const resolvedPriority = priority ?? (kind ? LABEL_PRIORITY[kind] : 0);

  // entry 생성 + 필드 동기화 (렌더마다, setState 없음). useEffect(등록)보다 먼저 실행된다.
  useLayoutEffect(() => {
    if (!labelId) {
      entryRef.current = null;
      return;
    }
    if (!entryRef.current || entryRef.current.id !== labelId) {
      entryRef.current = createEntry(labelId);
    }
    const entry = entryRef.current;
    entry.el = innerRef.current;
    entry.textEl = fullRef.current;
    entry.chipEl = numberRef.current;
    entry.priority = resolvedPriority;
    entry.active = active;
    entry.current = current;
    entry.chip = chip;
    entry.alwaysOn = alwaysOn;
    entry.variant = variant;
    entry.kind = kind ?? null;
    entry.anchorMode = anchor;
    entry.nodeRadius = resolvedRadius;
    entry.nodeWorld.set(nodePosition[0], nodePosition[1], nodePosition[2]);
    entry.anchorWorld.set(
      nodePosition[0] + effectiveOffset[0],
      nodePosition[1] + effectiveOffset[1],
      nodePosition[2] + effectiveOffset[2],
    );
  });

  // 등록/해제 — Provider 없으면(또는 labelId 없으면) 아무것도 하지 않는다.
  useEffect(() => {
    const entry = entryRef.current;
    if (!registry || !labelId || !entry) return;
    registry.register(entry);
    return () => {
      registry.unregister(labelId);
      entry.dx = 0;
      entry.dy = 0;
      entry.suppressed = false;
    };
  }, [registry, labelId]);

  useFrame(({ camera, clock }, delta) => {
    const el = innerRef.current;
    if (!el) return;
    const dt = Math.min(delta, 0.1);

    // depth 스케일
    if (!anchorVec.current) anchorVec.current = new THREE.Vector3();
    anchorVec.current.set(
      nodePosition[0] + effectiveOffset[0],
      nodePosition[1] + effectiveOffset[1],
      nodePosition[2] + effectiveOffset[2],
    );
    const distance = camera.position.distanceTo(anchorVec.current);
    const scale = labelScaleAt(camera, anchorVec.current);
    const entry = registered ? entryRef.current : null;
    /* drei `Html` 은 자기 React 뿌리에 **나중에** 그린다 — 처음 붙는 라벨은 layout effect 가 돌 때 아직 요소가 없다.
       다시 렌더링되지 않으면(정거장 지도에서 새로 밝아진 정거장의 라벨) 배치가 영영 그 라벨을 재지 못했다(21차).
       요소가 생긴 첫 프레임에 여기서 이어 준다. */
    if (entry && entry.el !== el) attachElements(entry, el, fullRef.current, numberRef.current);
    const dx = entry ? entry.dx : 0;
    const dy = entry ? entry.dy : 0;
    const scaleChanged = Math.abs(scale - scaleRef.current) > 0.004;
    const offsetChanged =
      Math.abs(dx - appliedDxRef.current) > OFFSET_EPSILON ||
      Math.abs(dy - appliedDyRef.current) > OFFSET_EPSILON;
    if (scaleChanged || offsetChanged) {
      scaleRef.current = scale;
      appliedDxRef.current = dx;
      appliedDyRef.current = dy;
      el.style.transform = entry
        ? `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) scale(${scale.toFixed(3)})`
        : `scale(${scale.toFixed(3)})`;
    }

    // 등장 + 흐림
    let appear = 1;
    if (reducedMotion) {
      appearStartRef.current = Number.NEGATIVE_INFINITY;
    } else {
      if (appearStartRef.current === null) {
        appearStartRef.current = clock.elapsedTime + appearDelay;
      }
      const progress = (clock.elapsedTime - appearStartRef.current) / LABEL_APPEAR_DURATION;
      appear = progress <= 0 ? 0 : progress >= 1 ? 1 : easeOutCubic(progress);
    }
    /* 거리 숨김: 멀리 있는 **긴** 라벨만 사라진다 (prompt_02 §4-A-2).
       짧은 라벨과 번호 칩은 카메라가 멀어도 남는다 — 글자 크기는 화면 px 고정이라
       멀어도 읽히고, 사라지면 그 점이 다시 무명이 된다. */
    /* **번호 칩은 거리로 숨기지 않는다** (ISSUE-128 · prompt_05 §4-D).

       긴 라벨은 멀어지면 서서히 사라진다 — 글자가 화면을 덮지 않게 하는 규칙이다. 그런데
       자리를 못 찾아 **번호 칩으로 줄어든** 라벨까지 그 규칙에 걸렸다. 칩은 22×22 라
       화면을 덮지 않는데도 사라져, 그 점이 「이름 없는 점」이 됐다 — 재검증 실측으로
       대시보드 1280×1200 에 2개, 1920×720 에 1개였다.

       칩은 이미 「줄일 수 있는 데까지 줄인 모양」이다. 여기서 더 줄일 것은 숨기는 것뿐이고,
       숨기면 규칙(「라벨 없는 점을 만들지 않는다」)이 깨진다. 자리를 못 찾으면 `findSpot`
       이 기본 자리(점 위)를 돌려주므로, 겹쳐서라도 그려진다. */
    const drawnAsNumber = entry !== null && !active && entry.numbered !== null;
    const keepVisible =
      active ||
      current ||
      persistent ||
      drawnAsNumber ||
      kind === "notice" ||
      kind === undefined ||
      variant === "short";
    const farT = keepVisible
      ? 0
      : THREE.MathUtils.clamp(
          (distance - LABEL_DISTANCE_HIDE.hideStart) /
            (LABEL_DISTANCE_HIDE.hideEnd - LABEL_DISTANCE_HIDE.hideStart),
          0,
          1,
        );
    /* 번호로 줄일지 — 자리를 못 찾은 짧은 라벨만 해당한다(ISSUE-114).
       바뀔 때만 DOM 을 건드린다. 매 프레임 쓰면 레이아웃이 계속 다시 잡힌다. */
    const wantNumber = entry && !active ? entry.numbered : null;
    if (wantNumber !== appliedNumberRef.current) {
      appliedNumberRef.current = wantNumber;
      const full = fullRef.current;
      const chip = numberRef.current;
      if (full && chip) {
        if (wantNumber === null) {
          full.style.display = "";
          chip.style.display = "none";
        } else {
          full.style.display = "none";
          chip.textContent = circledNumber(wantNumber);
          chip.style.display = "";
        }
      }
    }

    const suppressed = entry ? entry.suppressed && !active : false;
    const target = suppressed ? 0 : (dimmed ? (dimmedOpacity ?? DIMMED_LABEL_OPACITY) : 1) * (1 - farT);
    opacityRef.current = reducedMotion
      ? target
      : THREE.MathUtils.damp(opacityRef.current, target, MATERIAL_DAMP_LAMBDA, dt);
    const opacity = appear * opacityRef.current;
    if (Math.abs(opacity - appliedOpacityRef.current) > 0.005) {
      appliedOpacityRef.current = opacity;
      el.style.opacity = opacity.toFixed(3);
    }
  });

  // 글래스 칩이 읽는 CSS 변수 (active 글로우·weight). transition은 등록된 라벨만.
  const innerStyle = useMemo<LabelCssVars>(() => {
    const style: LabelCssVars = { ...(reducedMotion ? VISIBLE_START : HIDDEN_START) };
    if (onPick) {
      style.pointerEvents = "auto";
      style.cursor = "pointer";
    }
    style["--lbl-weight"] = String(resolvedWeight);
    if (maxWidth) style["--lbl-max"] = `${maxWidth}px`;
    if (active && tone) {
      style["--lbl-border"] = withAlpha(tone, 0.55);
      style["--lbl-shadow"] = `0 0 0 1px ${withAlpha(tone, 0.28)}, 0 0 18px ${withAlpha(
        tone,
        0.22,
      )}, ${DEFAULT_CHIP_SHADOW}`;
    }
    /* transform 에 transition 을 걸지 않는다 (§3-A-4 · 검수 §3 labels.tsx:81).
       예전에는 배치가 바뀔 때 부드럽게 미끄러지도록 `transform 120ms ease-out` 을 걸었다.
       그런데 이 transform 은 배치 오프셋뿐 아니라 **카메라 거리에 따른 scale** 도 함께
       나르므로, 전환을 걸면 카메라가 움직이는 동안 라벨이 매 프레임 노드보다 한 박자
       늦게 따라간다 — 담당자가 본 「미끄러짐」의 절반이 이것이다. 배치는 이제 카메라가
       멈춘 뒤에만 한 번 바뀌므로 부드럽게 만들 이동 자체가 없다. */
    return style;
  }, [reducedMotion, resolvedWeight, active, tone, maxWidth, onPick]);

  return (
    <Html
      position={[effectiveOffset[0], effectiveOffset[1], effectiveOffset[2]]}
      center={anchor === "center"}
      zIndexRange={[10, 0]}
      pointerEvents="none"
      style={NO_POINTER}
    >
      <div
        ref={innerRef}
        style={innerStyle}
        /* 측정용 표시 — `scripts/check_visibility.mjs` 가 「라벨 없는 점」을 세는 근거다
           (prompt_01 §4-A-6). 기존 `data-visibility-strip` 과 같은 방식이다. */
        data-cosmos-label={variant}
        /* 흔들림 측정이 프레임끼리 **같은 라벨**을 짝지을 고리 (`scripts/measure_jitter.mjs`).
           DOM 순서로 짝지으면 라벨 하나가 붙고 떨어질 때 전부 밀려 거짓 흔들림이 된다. */
        data-cosmos-label-id={labelId}
        /* 정거장 지도에서 이 라벨이 선 정거장 — 「지금 정거장 라벨 100%」 검사가 읽는다 (21차). */
        data-cosmos-station={station}
        onClick={
          onPick
            ? (event) => {
                event.stopPropagation();
                onPick();
              }
            : undefined
        }
        onPointerDown={onPick ? stopEvent : undefined}
        onPointerUp={onPick ? stopEvent : undefined}
        onPointerMove={onPick ? stopEvent : undefined}
        className={`select-none ${
          anchor === "center" ? "origin-center" : anchor === "top-left" ? "origin-top-left -translate-y-3" : "origin-left -translate-y-1/2"
        }`}
      >
        {/* 본문과 번호 칩을 **둘 다** 두고 프레임 루프가 하나만 보여 준다.
            이 파일은 배치 결과를 setState 없이 DOM 에 직접 쓴다 — 번호로 줄이는 것도
            같은 방식이어야 매 프레임 React 를 깨우지 않는다. */}
        <span ref={fullRef} data-cosmos-text>
          {children}
        </span>
        <span ref={numberRef} data-cosmos-number style={NUMBER_HIDDEN} className={NUMBER_CHIP_CLASS} />
      </div>
    </Html>
  );
}

// ---------------------------------------------------------------------------
// 칩 (글래스: 패널색 + blur + 1px 테두리 + subtle shadow)
// ---------------------------------------------------------------------------

interface ChipProps {
  dot?: string;
  emphasis?: boolean;
  /** 상태색 — active일 때 테두리/글로우 (FloatingLabel의 tone/active 대신 직접 지정할 때) */
  tone?: string;
  active?: boolean;
  /** 명시하지 않으면 FloatingLabel이 내려준 --lbl-weight, 그것도 없으면 400 */
  weight?: LabelWeight;
  /**
   * 판정 낱말 알약 — 호박 · 빨강 항목의 이름표 끝(27차 §3-D-4). 색만으로 판정을 말하지 않게 같은 색 낱말을 붙인다.
   * 제목이 길어 잘려도 알약은 남도록 잘리는 글 **밖**에 둔다.
   */
  verdict?: { word: string; color: string } | null;
  children: ReactNode;
}

/** 판정 낱말 대신 쓰는 기호 — 레일 기호와 같다(확인 필요 「!」 · 문제 「✕」). 낱말은 title · 화면 읽기 글자로 남는다. */
function verdictGlyph(word: string): string {
  return word === VERDICT_WORDS.warning ? STEP_STATUS_META.failed.glyph : STEP_STATUS_META.attention.glyph;
}

export function LabelChip({ dot, emphasis = false, tone, active = false, weight, verdict, children }: ChipProps) {
  const glow = active && tone;
  /*
   * 판정 알약이 이름을 밀어내면(1440 에서 「증빙…」 · 1024 에서 「증·」) 담당자가 꼭 봐야 할 항목만 알아볼 수 없었다
   * (27차 검수 R27D-OWN-01). 이름 전체 + 낱말 알약이 칸에 안 들어가면 알약을 기호 하나로 줄인다 — 정거장 알약과 같은 규칙.
   */
  const nameRef = useRef<HTMLSpanElement>(null);
  const [compact, setCompact] = useState(false);
  useLayoutEffect(() => {
    const name = nameRef.current;
    const chip = name?.parentElement;
    if (!verdict || !name || !chip) return;
    const max = parseFloat(getComputedStyle(chip).maxWidth);
    if (!Number.isFinite(max)) return;
    // 알약 낱말 폭(13px 글자) + 알약 안쪽 여백 · 간격 + 칩 안쪽 여백 · 점
    const need = name.scrollWidth + Array.from(verdict.word).length * 13 + 16 + 20 + (dot ? 12 : 0);
    setCompact(need > max);
    // 이름표 폭(--lbl-max)은 부모가 바꾸고 그때 children 이 새로 만들어진다 — children 으로 다시 잰다.
  }, [verdict, dot, children]);
  const style: React.CSSProperties = {
    borderColor: glow
      ? withAlpha(tone, 0.55)
      : `var(--lbl-border, ${emphasis ? "var(--cosmos-border-strong)" : "var(--cosmos-border)"})`,
    boxShadow: glow
      ? `0 0 0 1px ${withAlpha(tone, 0.28)}, 0 0 18px ${withAlpha(tone, 0.22)}, ${DEFAULT_CHIP_SHADOW}`
      : `var(--lbl-shadow, ${DEFAULT_CHIP_SHADOW})`,
    fontWeight: weight ?? "var(--lbl-weight, 400)",
  };
  return (
    <div
      className="flex max-w-[var(--lbl-max,148px)] items-center gap-1.5 truncate whitespace-nowrap rounded-md border bg-cosmos-panel px-1.5 py-[2px] text-[13px] leading-4 text-cosmos-text backdrop-blur-md sm:max-w-[var(--lbl-max,240px)] sm:px-2 sm:py-[3px]"
      style={style}
    >
      {dot && (
        <span
          aria-hidden
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: dot }}
        />
      )}
      <span ref={nameRef} className="truncate">
        {children}
      </span>
      {verdict && (
        <span
          data-cosmos-verdict={verdict.word}
          data-cosmos-verdict-mode={compact ? "glyph" : "word"}
          title={compact ? verdict.word : undefined}
          className="shrink-0 rounded-[3px] border px-1 text-[13px] font-semibold leading-4"
          style={{ color: verdict.color, borderColor: withAlpha(verdict.color, 0.55), backgroundColor: withAlpha(verdict.color, 0.12) }}
        >
          {compact ? (
            <>
              <span aria-hidden="true">{verdictGlyph(verdict.word)}</span>
              <span className="sr-only">{verdict.word}</span>
            </>
          ) : (
            verdict.word
          )}
        </span>
      )}
    </div>
  );
}

/** 합성 이름표 둘 중 하나 — 맨 「데모」가 아니다 (27차 검수 R27U-MSC-09). */
export function DemoTag() {
  return <span className="ml-1 text-[13px] font-normal text-cosmos-muted">{SYNTHETIC_NOTICE}</span>;
}

// ---------------------------------------------------------------------------
// 핵심 라벨 — 기본 화면에서 보이는 5개 (제목 먼저, 데이터에서 만든 부제, 코드는 작게)
// ---------------------------------------------------------------------------

interface KeyLabelChipProps {
  title: string;
  subtitle: string;
  code?: string;
  /** Guided 단계 번호 (①~⑤) */
  step: number;
  dot: string;
  tone?: string;
  active?: boolean;
}

const KEY_STEP_GLYPH = ["①", "②", "③", "④", "⑤"] as const;

export function KeyLabelChip({ title, subtitle, code, step, dot, tone, active = false }: KeyLabelChipProps) {
  const glow = active && tone;
  const style: React.CSSProperties = {
    backgroundColor: "rgba(11, 19, 38, 0.92)",
    borderColor: glow ? withAlpha(tone, 0.6) : "var(--lbl-border, var(--cosmos-border-strong))",
    boxShadow: glow
      ? `0 0 0 1px ${withAlpha(tone, 0.3)}, 0 0 18px ${withAlpha(tone, 0.24)}, ${DEFAULT_CHIP_SHADOW}`
      : `var(--lbl-shadow, ${DEFAULT_CHIP_SHADOW})`,
  };
  return (
    <div
      className="flex max-w-[172px] flex-col gap-px whitespace-nowrap rounded-lg border px-2 py-1.5 text-cosmos-text backdrop-blur-md sm:max-w-[240px] sm:px-2.5"
      style={style}
    >
      <div className="flex items-center gap-1.5">
        <span aria-hidden className="inline-block h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: dot }} />
        <span className="truncate text-[13px] font-semibold leading-4">{title}</span>
        <span aria-hidden className="ml-auto shrink-0 pl-1 text-[13px] leading-4 text-cosmos-cyan">
          {KEY_STEP_GLYPH[step - 1] ?? step}
        </span>
      </div>
      <div className="truncate text-[13px] leading-4 text-cosmos-secondary">{subtitle}</div>
      {code && <div className="truncate font-mono text-[13px] leading-4 text-cosmos-muted">{code}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 공고 카드 — 공고명·발주기관·마감일·예산·현재 단계·진행률·적합도
// ---------------------------------------------------------------------------

interface NoticeCardProps {
  graph: CosmosGraph;
  stage: WorkflowStage;
  node: CosmosNode;
  /** 카드에 적히는 말. 입찰이면 BID_VOCABULARY 가 들어온다 */
  vocabulary: CosmosVocabulary;
}

function Row({
  label,
  value,
  mono = false,
  children,
}: {
  label: string;
  value?: string;
  mono?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="w-[44px] shrink-0 text-[13px] text-cosmos-muted sm:w-[52px]">{label}</dt>
      <dd
        className={`min-w-0 flex-1 truncate text-[13px] font-normal text-cosmos-secondary ${
          mono ? "font-mono tabular-nums" : ""
        }`}
      >
        {children ?? value}
      </dd>
    </div>
  );
}

export function NoticeCard({ graph, stage, vocabulary }: NoticeCardProps) {
  const { notice, scenario } = graph.source;
  const step = graph.steps[Math.min(Math.max(stage, 1), graph.steps.length) - 1];
  // 진행률이 null 이면 진행바를 «0%로 그리지 않고» DOM 자체를 만들지 않는다.
  const progress = vocabulary.centerProgress(graph);
  const progressPct = progress === null ? null : Math.round(progress * 100);
  // 상태 낱말은 레일 · 지도 알약과 같은 사전에서(27차 §3-D-9) — 두 벌이면 언젠가 갈린다.
  const stepStatusLabel = step ? STEP_STATUS_META[step.status].label : "-";
  const fit = scenario?.semantic_match ?? null;
  const originLabel = vocabulary.originLabel(graph);
  const rows = vocabulary.centerRows(graph);

  return (
    <div
      className="w-[168px] rounded-lg border bg-cosmos-panel px-2 py-2 backdrop-blur-md sm:w-[224px] sm:px-3 sm:py-2.5"
      style={{
        borderColor: "var(--lbl-border, var(--cosmos-border-strong))",
        boxShadow: `var(--lbl-shadow, ${DEFAULT_CARD_SHADOW})`,
      }}
    >
      {/* eyebrow: 카테고리 */}
      <div className="flex items-center gap-1.5">
        <span
          aria-hidden
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: COSMOS_HEX.blue }}
        />
        <span className="truncate text-[13px] font-semibold tracking-[0.08em] text-cosmos-cyan">
          {vocabulary.centerEyebrow}
        </span>
        <span className="ml-auto truncate text-[13px] text-cosmos-muted">{originLabel}</span>
      </div>

      {/* 제목 */}
      <p className="mt-1 line-clamp-2 text-[13px] font-semibold leading-[1.35] text-cosmos-text">
        {notice.title}
      </p>

      {/* 키-값 */}
      <dl className="mt-2 space-y-1 border-t border-cosmos-border pt-2">
        {rows.map((row) => (
          <Row key={row.label} label={row.label} mono={row.mono}>
            {row.value}
            {row.demo ? <DemoTag /> : null}
          </Row>
        ))}
        {vocabulary.showFitRow &&
          (fit ? (
            <Row label="적합도">
              <span className="text-cosmos-text">{fit.label}</span>
              <span className="ml-1.5 font-mono text-[13px] tabular-nums text-cosmos-muted">
                {Math.round(fit.fit_score * 100)}
              </span>
              <DemoTag />
            </Row>
          ) : (
            <Row
              label="후보"
              value={
                notice.candidate
                  ? `낱말 관련도 ${CANDIDATE_TIER_LABELS[notice.candidate.tier] ?? "확인 필요"} (AI 비교는 안 씀)`
                  : "적합도 아직 안 잼"
              }
            />
          ))}
        <Row
          label={vocabulary.centerStepLabel}
          value={step ? `${step.id}단계 · ${step.label} · ${stepStatusLabel}` : "-"}
        />
      </dl>

      {/* 진행률 */}
      {progressPct !== null && (
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-cosmos-cyan transition-[width] duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <span className="font-mono text-[13px] font-normal tabular-nums text-cosmos-secondary">
            {progressPct}%
          </span>
        </div>
      )}
    </div>
  );
}
