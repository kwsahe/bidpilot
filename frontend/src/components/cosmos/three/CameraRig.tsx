"use client";

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from "react";
import * as THREE from "three";

import { isVisible, type CosmosGraph, type WorkflowStage } from "@/lib/cosmos/graph";
import type { CameraPreset } from "@/lib/cosmos/presentation";

import {
  CAMERA_DAMP_LAMBDA,
  CAMERA_PRESETS,
  FOCUS_DISTANCE,
  ORBIT_LIMITS,
  type Vec3,
} from "./constants";
import { useCameraDraggingRef, useCameraGoalRef } from "./labels";
import type { StationFrame } from "./stationLayout";

type OrbitControlsRef = ComponentRef<typeof OrbitControls>;

const SNAP_EPSILON_SQ = 4e-4;

const _goalOffset = new THREE.Vector3();
const _goalSpherical = new THREE.Spherical();
const _goalClamped = new THREE.Vector3();

/**
 * tween 의 목표 자세를 **OrbitControls 가 허용하는 자리**로 맞춘다 (ISSUE-127).
 *
 * 왜 필요한가. 라벨 배치는 이 도착지로 미리 풀린다(labels.tsx `CameraGoal`). 그런데
 * `OrbitControls` 는 매 프레임 거리와 극각을 자기 한계로 **자른다** — 프리셋이 그 한계를
 * 넘으면 카메라가 실제로 도착하는 자리는 tween 의 목표와 다르다. 그러면 「도착지로 푼
 * 배치」가 도착한 화면과 어긋나, 도착하는 순간 한 번 옮겨 간다(실측: 누른 뒤 0.7초에
 * 라벨 5개가 최대 111px). 여기서 같은 규칙으로 잘라 두면 그 어긋남이 없어진다.
 */
function clampToOrbit(
  out: THREE.Vector3,
  position: Vec3 | THREE.Vector3,
  target: THREE.Vector3,
  maxDistance: number = ORBIT_LIMITS.maxDistance,
  maxPolarAngle: number = ORBIT_LIMITS.maxPolarAngle,
): void {
  if (position instanceof THREE.Vector3) _goalOffset.copy(position);
  else _goalOffset.set(position[0], position[1], position[2]);
  _goalOffset.sub(target);
  _goalSpherical.setFromVector3(_goalOffset);
  _goalSpherical.radius = THREE.MathUtils.clamp(
    _goalSpherical.radius,
    ORBIT_LIMITS.minDistance,
    maxDistance,
  );
  _goalSpherical.phi = THREE.MathUtils.clamp(_goalSpherical.phi, 1e-6, maxPolarAngle);
  _goalOffset.setFromSpherical(_goalSpherical);
  out.copy(target).add(_goalOffset);
}

/**
 * 그래프가 화면에서 차지할 비율.
 *
 * 고정 프리셋(CAMERA_PRESETS.overview)은 **입찰 그래프 크기에 맞춰 손으로 잡은 값**이다.
 * 지원사업 그래프는 노드가 적고 더 납작해서 같은 자리에서 보면 아래쪽 작은 구역에 몰리고
 * 위쪽이 통째로 빈다. 1920×1080 에서 실제로 그랬다.
 * 그래서 프리셋을 쓰지 않고 **지금 그래프의 실제 크기**를 재서 거리를 정한다.
 */
const OVERVIEW_FILL = 0.62;

/**
 * 그래프를 오른쪽 상세 패널 반대편으로 살짝 민다.
 *
 * 카메라 target 을 오른쪽으로 옮기면 내용은 화면에서 왼쪽으로 온다. 선택한 노드와
 * 오른쪽 패널 사이의 시선 이동 거리가 줄어든다. 중앙에서 «약간» 왼쪽이지 치우치면 안 된다.
 */
const LEFT_BIAS = 0.12;

function dampVector(current: THREE.Vector3, target: THREE.Vector3, dt: number): void {
  current.x = THREE.MathUtils.damp(current.x, target.x, CAMERA_DAMP_LAMBDA, dt);
  current.y = THREE.MathUtils.damp(current.y, target.y, CAMERA_DAMP_LAMBDA, dt);
  current.z = THREE.MathUtils.damp(current.z, target.z, CAMERA_DAMP_LAMBDA, dt);
}

/** 카메라 tween 상태. React 상태가 아니라 ref로만 다룬다 (언마운트 시 setState 없음). */
class CameraTween {
  active = false;
  readonly position = new THREE.Vector3();
  readonly target = new THREE.Vector3();
  private readonly direction = new THREE.Vector3();

  start(position: Vec3, target: Vec3): void {
    this.position.set(position[0], position[1], position[2]);
    this.target.set(target[0], target[1], target[2]);
    this.active = true;
  }

  /** target=노드 위치, 카메라는 현재(또는 진행 중 tween의) 방향을 유지하며 distance만큼 떨어진다. */
  focus(
    nodePosition: Vec3,
    distance: number,
    camera: THREE.Camera,
    controlsTarget: THREE.Vector3,
  ): void {
    const fromPosition = this.active ? this.position : camera.position;
    const fromTarget = this.active ? this.target : controlsTarget;
    this.direction.subVectors(fromPosition, fromTarget);
    if (this.direction.lengthSq() < 1e-6) this.direction.set(0, 0.55, 1);
    this.direction.normalize();
    this.target.set(nodePosition[0], nodePosition[1], nodePosition[2]);
    this.position.copy(this.target).addScaledVector(this.direction, distance);
    this.active = true;
  }

  finish(camera: THREE.Camera, controls: OrbitControlsRef): void {
    camera.position.copy(this.position);
    controls.target.copy(this.target);
    controls.update();
    this.active = false;
  }

  cancel(): void {
    this.active = false;
  }

  step(camera: THREE.Camera, controls: OrbitControlsRef, delta: number): void {
    if (!this.active) return;
    const dt = Math.min(delta, 0.1);
    dampVector(camera.position, this.position, dt);
    dampVector(controls.target, this.target, dt);
    if (
      camera.position.distanceToSquared(this.position) < SNAP_EPSILON_SQ &&
      controls.target.distanceToSquared(this.target) < SNAP_EPSILON_SQ
    ) {
      this.finish(camera, controls);
    }
  }
}

const _dir = new THREE.Vector3();
const _right = new THREE.Vector3();
const _up = new THREE.Vector3();
const _forward = new THREE.Vector3();
const _point = new THREE.Vector3();
const _target = new THREE.Vector3();
const WORLD_UP = new THREE.Vector3(0, 1, 0);

/**
 * 지금 그래프가 화면의 약 62% 를 채우도록 overview 카메라를 다시 잡는다.
 *
 * **카메라가 보는 평면에서 잰다.** 처음에는 월드 좌표의 bounding box 중심을 target 으로 삼았는데,
 * 이 화면은 위에서 비스듬히 내려다보는 각도라 월드 중심을 겨눠도 화면 한가운데에 오지 않았다.
 * 1366×768 에서 그래프가 아래쪽으로 몰리고 위가 통째로 비었다 — 실제로 그랬다.
 * 그래서 노드를 카메라 축(오른쪽·위·앞)으로 투영해 **화면에서의 크기와 중심**을 구한다.
 *
 * 시선 «방향»은 기존 overview 프리셋 그대로다 — 위에서 약간 내려다보는 각도가 이 화면의
 * 성격이고, 그것까지 바꾸면 다른 장면이 된다. 바꾸는 것은 거리와 겨누는 점뿐이다.
 */
function fitOverview(
  graph: CosmosGraph,
  stage: WorkflowStage,
  fov: number,
  aspect: number,
): { position: Vec3; target: Vec3 } {
  const preset = CAMERA_PRESETS.overview;
  /**
   * **지금 보이는 노드만** 잰다.
   *
   * 그래프에는 뒷 단계 노드도 들어 있고 화면은 `isVisible(node, stage)` 로 걸러 그린다.
   * 전부를 재면 아직 그리지 않은 위쪽 노드까지 넣어 중심이 떠올라, 보이는 무리가 아래로 몰리고
   * 위가 빈다 — 1366×768 에서 실제로 그랬다. 화면에 있는 것만 담아야 화면이 채워진다.
   */
  const nodes = graph.nodes.filter((node) => isVisible(node, stage));
  if (nodes.length === 0) return preset;

  // 카메라 축 세 개. dir 은 target → camera 방향이다.
  _dir
    .set(
      preset.position[0] - preset.target[0],
      preset.position[1] - preset.target[1],
      preset.position[2] - preset.target[2],
    )
    .normalize();
  _forward.copy(_dir).multiplyScalar(-1);
  _right.crossVectors(_forward, WORLD_UP).normalize();
  _up.crossVectors(_right, _forward).normalize();

  let uMin = Infinity, uMax = -Infinity;
  let vMin = Infinity, vMax = -Infinity;
  let wMin = Infinity, wMax = -Infinity;
  for (const node of nodes) {
    _point.set(node.position[0], node.position[1], node.position[2]);
    const u = _point.dot(_right);
    const v = _point.dot(_up);
    const w = _point.dot(_forward);
    if (u < uMin) uMin = u;
    if (u > uMax) uMax = u;
    if (v < vMin) vMin = v;
    if (v > vMax) vMax = v;
    if (w < wMin) wMin = w;
    if (w > wMax) wMax = w;
  }
  if (!Number.isFinite(uMin) || !Number.isFinite(vMin)) return preset;

  // 노드는 점이 아니라 라벨을 달고 있으므로 조금 넉넉하게 본다.
  const halfU = Math.max((uMax - uMin) / 2, 0.5) * 1.15;
  const halfV = Math.max((vMax - vMin) / 2, 0.5) * 1.15;

  const tan = Math.tan((fov * Math.PI) / 180 / 2);
  const safeAspect = Math.max(aspect, 0.2);
  const distance = Math.max(halfV / (tan * OVERVIEW_FILL), halfU / (tan * safeAspect * OVERVIEW_FILL));

  // 겨누는 점: 화면 중심이 될 자리. 오른쪽 상세 패널 반대편으로 살짝 민다.
  const uMid = (uMin + uMax) / 2 + halfU * LEFT_BIAS;
  const vMid = (vMin + vMax) / 2;
  const wMid = (wMin + wMax) / 2;
  _target.copy(_right).multiplyScalar(uMid).addScaledVector(_up, vMid).addScaledVector(_forward, wMid);

  return {
    target: [_target.x, _target.y, _target.z],
    position: [
      _target.x + _dir.x * distance,
      _target.y + _dir.y * distance,
      _target.z + _dir.z * distance,
    ],
  };
}

/**
 * 정거장 지도의 시선 — **정면** (27차 §3-D-7). 21차의 「정면에서 약간 위」(0, 0.32, 1)는 이름표 줄이 비스듬히 밀렸다.
 * 방향은 고정이고, 거리는 길 전체(이름 여덟 개)가 화면에 들어오게 잡는다.
 */
const STATION_VIEW_DIR = new THREE.Vector3(0, 0, 1).normalize();
const STATION_FILL = 0.9;
const NAME_HALF_WIDTH = 1;

/**
 * 정거장 지도의 카메라 자세. 길 전체 상자를 담는 거리로 물러서고, 남는 폭이 있으면 **지금 정거장 쪽으로**
 * 겨누는 점을 민다 — 이름 여덟 개가 화면 밖으로 나가지 않는 만큼만.
 *
 * 시선이 x 성분이 없으므로 화면 가로는 월드 x 그대로, 세로는 y × cos(내려다보는 각)이다.
 */
function stationFit(frame: StationFrame, fov: number, aspect: number) {
  const x0 = frame.spans[0].x0;
  const x1 = frame.spans[frame.spans.length - 1].x1;
  // 이름 칸은 정거장 가운데에서 좌우로 조금 넘는다(「참가자격」 72px ≈ 1.6 단위) — 그만큼 넉넉히 담는다.
  const halfU = (x1 - x0) / 2 + NAME_HALF_WIDTH;
  const halfV = ((frame.top - frame.bottom) / 2) * STATION_VIEW_DIR.z;
  const tan = Math.tan((fov * Math.PI) / 180 / 2);
  const safeAspect = Math.max(aspect, 0.2);
  const distance = Math.max(halfV / (tan * STATION_FILL), halfU / (tan * safeAspect * STATION_FILL));
  return { x0, x1, halfU, tan, safeAspect, distance };
}

/**
 * 정거장 지도의 화면 배율(px / 월드 단위, 겨누는 점 깊이) — 지금 정거장 긴 라벨 폭을 **열 폭에 맞추는** 데 쓴다.
 * 고정 px 이면 1440 에서 라벨이 정거장 밖으로 나가 옆 정거장 점을 덮었다 (21차 검토).
 */
export function stationPixelsPerUnit(frame: StationFrame, fov: number, width: number, height: number): number {
  if (width <= 0 || height <= 0) return 0;
  const { distance, tan } = stationFit(frame, fov, width / height);
  return height / (2 * distance * tan);
}

function stationPose(
  frame: StationFrame,
  stage: WorkflowStage,
  fov: number,
  aspect: number,
): { position: Vec3; target: Vec3; distance: number } {
  const { x0, x1, halfU, tan, safeAspect, distance } = stationFit(frame, fov, aspect);
  const xMid = (x0 + x1) / 2;
  const y = (frame.top + frame.bottom) / 2;
  // 남는 폭은 **이름 줄의 깊이**에서 잰다 — 이름은 겨누는 점보다 위라 카메라에 더 가깝고, 그래서 더 넓게 퍼진다.
  // 겨누는 점의 깊이로 재면 끝 정거장 이름이 화면 밖으로 밀렸다(1440 · 4단계에서 「결정」이 7px 잘림).
  const nameDepth = distance - (frame.top - y) * STATION_VIEW_DIR.y;
  const slack = Math.max(0, nameDepth * tan * safeAspect * STATION_FILL - halfU);
  const x = THREE.MathUtils.clamp(frame.centers[stage - 1] ?? xMid, xMid - slack, xMid + slack);
  return {
    target: [x, y, 0],
    position: [
      x + STATION_VIEW_DIR.x * distance,
      y + STATION_VIEW_DIR.y * distance,
      STATION_VIEW_DIR.z * distance,
    ],
    distance,
  };
}

interface CameraRigProps {
  graph: CosmosGraph;
  /** 지금 그려지는 단계. 보이는 노드만 담아 카메라를 잡기 위해 필요하다. */
  stage: WorkflowStage;
  cameraPreset: CameraPreset;
  focusNodeId: string | null;
  resetSignal: number;
  reducedMotion: boolean;
  /**
   * 정거장 지도(입찰)면 그 배치의 틀. 있으면 카메라는 **단계(정거장)와 틀과 화면 크기만** 따른다 —
   * 프리셋·노드 포커스는 쓰지 않는다(길을 벗어나 한 노드로 날아가면 길이 안 보인다). 지원사업은 없다(예전 그대로).
   */
  frame?: StationFrame | null;
}

export function CameraRig({
  graph,
  stage,
  cameraPreset,
  focusNodeId,
  resetSignal,
  reducedMotion,
  frame = null,
}: CameraRigProps) {
  const camera = useThree((state) => state.camera);
  const size = useThree((state) => state.size);
  const gl = useThree((state) => state.gl);
  const connected = useThree((state) => state.events.connected) as HTMLElement | null | undefined;
  const controlsRef = useRef<OrbitControlsRef | null>(null);
  /*
   * 휠만 굴리면 페이지가 내려간다 — 확대는 Ctrl(⌘)+휠 · 터치패드 모으기 (DSH-18). 세로로 긴 전체 보기에서
   * 지도 위를 지나가다 스크롤이 멈추고 확대만 됐다. OrbitControls 가 듣는 요소에서 캡처로 먼저 받아 전파만 끊는다
   * (preventDefault 는 하지 않는다 — 그래야 페이지가 내려간다).
   */
  useEffect(() => {
    const target = connected ?? gl.domElement;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) event.stopImmediatePropagation();
    };
    target.addEventListener("wheel", onWheel, { capture: true });
    return () => target.removeEventListener("wheel", onWheel, { capture: true });
  }, [connected, gl]);
  const [tween] = useState(() => new CameraTween());
  /**
   * 라벨 배치에 **도착지**를 알려 준다 (ISSUE-127 · prompt_05 §4-C).
   *
   * 단계 전환은 어디로 가는지 알고 있다. 배치가 그것을 알면 전환 중에 이미 도착한 뒤의
   * 자리로 풀어 둘 수 있어, 카메라가 멈출 때 라벨이 옮겨 갈 것이 없다. 예전에는 멈춘 뒤
   * 한 번에 풀어서 라벨 12개가 같은 100ms 안에 10~111px 을 함께 옮겼다(실측).
   */
  const goalRef = useCameraGoalRef();
  const draggingRef = useCameraDraggingRef();

  // 효과 의존성에 넣지 않기 위해 최신 값을 ref로 보관한다.
  const reducedMotionRef = useRef(reducedMotion);
  const graphRef = useRef(graph);
  const mountedRef = useRef(false);
  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
  }, [reducedMotion]);
  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  /**
   * overview 는 그래프 크기에 맞춰 매번 다시 잡는다. 나머지 프리셋은 발표 장면용 고정값이다.
   *
   * 그래프·화면 크기가 바뀌면(공고 교체, 창 크기, 단계 이동으로 노드가 펼쳐짐) 다시 계산한다.
   */
  const overviewPose = useMemo(() => {
    const fov = camera instanceof THREE.PerspectiveCamera ? camera.fov : 45;
    const aspect = size.height > 0 ? size.width / size.height : 1.6;
    return fitOverview(graph, stage, fov, aspect);
  }, [graph, stage, camera, size.width, size.height]);

  const poseFor = useCallback(
    (preset: CameraPreset) => (preset === "overview" ? overviewPose : CAMERA_PRESETS[preset]),
    [overviewPose],
  );

  /** 정거장 지도의 자세 — 단계를 누르면 길을 따라 옮겨 간다. */
  const stationPoseValue = useMemo(() => {
    if (!frame) return null;
    const fov = camera instanceof THREE.PerspectiveCamera ? camera.fov : 45;
    const aspect = size.height > 0 ? size.width / size.height : 1.6;
    return stationPose(frame, stage, fov, aspect);
  }, [frame, stage, camera, size.width, size.height]);
  const stationPoseRef = useRef(stationPoseValue);
  useEffect(() => {
    stationPoseRef.current = stationPoseValue;
  }, [stationPoseValue]);

  // 0) 정거장 지도: 자세가 바뀌면(단계 · 배치 · 화면 크기) 그리로 옮긴다. 마운트 직후·reducedMotion 은 즉시.
  //    항목을 고르거나 풀면 배치 객체가 새로 만들어지지만 자세는 같다 — 그때 되돌아가면 사람이 돌려 놓은 시점이 사라졌다
  //    (27차 검수 R27D-01). 위치 · 겨누는 점이 같으면 옮기지 않는다.
  const lastPoseRef = useRef<{ position: Vec3; target: Vec3 } | null>(null);
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls || !stationPoseValue) return;
    const last = lastPoseRef.current;
    const same = (a: Vec3, b: Vec3) => a.every((v, i) => Math.abs(v - b[i]) < 1e-6);
    if (last && mountedRef.current && same(last.position, stationPoseValue.position) && same(last.target, stationPoseValue.target)) return;
    lastPoseRef.current = { position: stationPoseValue.position, target: stationPoseValue.target };
    tween.start(stationPoseValue.position, stationPoseValue.target);
    if (!mountedRef.current || reducedMotionRef.current) tween.finish(camera, controls);
  }, [stationPoseValue, camera, tween]);

  // 0') 정거장 지도의 「화면 초기화」 — 드래그로 돌려 놓은 것을 지금 정거장 정면으로 되돌린다.
  useEffect(() => {
    const controls = controlsRef.current;
    const pose = stationPoseRef.current;
    if (!mountedRef.current || !controls || !pose) return;
    tween.start(pose.position, pose.target);
    if (reducedMotionRef.current) tween.finish(camera, controls);
  }, [resetSignal, camera, tween]);

  // 1) 프리셋 변경 → 부드럽게 전환 (마운트 직후·reducedMotion은 즉시)
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls || stationPoseRef.current) return;
    const pose = poseFor(cameraPreset);
    tween.start(pose.position, pose.target);
    if (!mountedRef.current || reducedMotionRef.current) tween.finish(camera, controls);
  }, [cameraPreset, camera, tween, poseFor]);

  // 2) focusNodeId가 바뀌고 non-null이면 노드로 포커스 (프리셋 효과 다음에 실행되어 프리셋 방향을 이어받는다)
  useEffect(() => {
    if (!focusNodeId) return;
    const controls = controlsRef.current;
    if (!controls || stationPoseRef.current) return;
    const node = graphRef.current.nodeById.get(focusNodeId);
    if (!node) return;
    tween.focus(node.position, FOCUS_DISTANCE[node.kind], camera, controls.target);
    if (!mountedRef.current || reducedMotionRef.current) tween.finish(camera, controls);
  }, [focusNodeId, camera, tween]);

  // 3) resetSignal 변경 → overview
  useEffect(() => {
    if (!mountedRef.current) return;
    const controls = controlsRef.current;
    if (!controls || stationPoseRef.current) return;
    const pose = poseFor("overview");
    tween.start(pose.position, pose.target);
    if (reducedMotionRef.current) tween.finish(camera, controls);
  }, [resetSignal, camera, tween, poseFor]);

  // 위 효과들 뒤에 선언되어 마운트 시 마지막으로 실행된다.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      tween.cancel();
    };
  }, [tween]);

  useFrame((_, delta) => {
    const controls = controlsRef.current;
    if (!controls) return;
    tween.step(camera, controls, delta);
    /* 도착지를 적어 둔다. tween 이 끝나거나(`finish`) 사용자가 끌어 중단되면(`cancel`)
       `active` 가 거짓이 되고, 배치는 예전처럼 「멈춘 뒤에 푸는」 규칙으로 돌아간다. */
    if (goalRef) {
      /* 값을 **바꿔 넣는다** — 남의 객체를 고치지 않는다(저장소 규칙 · lint 도 본다).
         전환 중 프레임마다 작은 객체 하나가 생기는데, 전환은 1초짜리이고 이 루프에는
         다른 할당이 없다. 전환이 끝나거나(`finish`) 사용자가 끌어 중단되면(`cancel`)
         null 을 넣고, 배치는 예전처럼 「멈춘 뒤에 푸는」 규칙으로 돌아간다. */
      if (tween.active) {
        clampToOrbit(_goalClamped, tween.position, tween.target, controls.maxDistance, controls.maxPolarAngle);
        goalRef.current = {
          position: [_goalClamped.x, _goalClamped.y, _goalClamped.z],
          target: [tween.target.x, tween.target.y, tween.target.z],
        };
      } else if (goalRef.current !== null) {
        goalRef.current = null;
      }
    }
  });

  // 사용자가 드래그/휠을 시작하면 진행 중인 tween을 중단한다. 끄는 동안은 노드 hover 를 받지 않는다 (ISSUE-141).
  const handleStart = useCallback(() => {
    tween.cancel();
    if (draggingRef) draggingRef.current = true;
  }, [tween, draggingRef]);
  const handleEnd = useCallback(() => {
    if (draggingRef) draggingRef.current = false;
  }, [draggingRef]);

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      enableDamping
      dampingFactor={0.08}
      minDistance={ORBIT_LIMITS.minDistance}
      // 좁거나 키 큰 캔버스에서는 길 전체를 담는 거리가 기본 한계(60)를 넘는다 — 그러면 OrbitControls 가 잘라
      // ① · ⑧ 이 화면 밖으로 나가고 tween 이 끝나지 않았다. 정거장 자세만큼은 물러설 수 있게 한다 (21차 검토).
      maxDistance={stationPoseValue ? Math.max(ORBIT_LIMITS.maxDistance, stationPoseValue.distance * 1.1) : ORBIT_LIMITS.maxDistance}
      // 정거장 지도는 **정면**(극각 π/2)에서 본다(27차 §3-D-7). 궤도 한계(0.49π)에 잘리면 카메라가 목표에 닿지 못해 이동이
      // 끝나지 않는다 — 정거장 자세에서만 π/2 까지 연다(지원사업 궤도 지도는 그대로).
      maxPolarAngle={stationPoseValue ? Math.PI / 2 : ORBIT_LIMITS.maxPolarAngle}
      autoRotate={false}
      onStart={handleStart}
      onEnd={handleEnd}
    />
  );
}
