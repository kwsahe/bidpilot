import type { CosmosGraph, WorkflowStage } from "@/lib/cosmos/graph";
import type { CameraPreset } from "@/lib/cosmos/presentation";
import type { CosmosVocabulary } from "@/lib/cosmos/vocabulary";

/** 3D(Cosmos3D)·2D(Cosmos2D) 렌더러가 공통으로 구현하는 인터페이스. */
export interface CosmosViewProps {
  graph: CosmosGraph;
  /** 입찰 지도(3D·2D): 지금 정거장 — 뒷 정거장을 숨기지 않는다(21차). 목록 · 지원사업 3D: item.stage <= stage 만 보인다 */
  stage: WorkflowStage;
  selectedId: string | null;
  hoveredId: string | null;
  /** 같은 노드 재클릭 → null, 빈 공간 클릭 → null */
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  /** 비어 있으면 아무것도 흐리게 하지 않는다 */
  highlightNodeIds: ReadonlySet<string>;
  highlightLinkIds: ReadonlySet<string>;
  /**
   * Focus Mode 순차 강조: 링크 id → 순서(0부터). 선택 노드에서 가까운 관계(근거)가 먼저,
   * 제안서·Auditor 경로가 뒤이어 켜진다. 없으면 동시에 켠다.
   */
  highlightOrder?: ReadonlyMap<string, number>;
  /** 3D 전용: 값이 바뀌면 카메라를 부드럽게 전환 */
  cameraPreset: CameraPreset;
  /** 3D 전용: 바뀌고 non-null이면 해당 노드로 포커스 */
  focusNodeId: string | null;
  /** 증가할 때마다 기본 시점으로 리셋 */
  resetSignal: number;
  /** true면 tween·펄스·등장 애니메이션 없이 즉시 반영 */
  reducedMotion: boolean;
  /** true면 유휴 애니메이션 정지 */
  paused: boolean;
  /** 화면 문구 묶음. 생략하면 BID_VOCABULARY (기존 호출부 무변경) */
  vocabulary?: CosmosVocabulary;
  /** 입찰 지도: 지금이 아닌 정거장 머리(이름 알약)를 누르면 그 정거장으로 — 레일과 같은 이동 (27차 §3-D-2) */
  onStation?: (stage: WorkflowStage) => void;
  /** 입찰 지도: 지금 정거장이 24 를 넘을 때 「외 n건 · 전체 보기」 — 목록 보기로 (27차 §3-D-6) */
  onShowAll?: () => void;
  /**
   * 입찰 지도: 선을 그을 항목 — 고른 항목(없으면 5단계 안내가 가리키는 지금 정거장 항목). 없으면 선 0 (27차 §3-D-3).
   * hover 로는 긋지 않는다 — 마우스가 지나갈 때마다 선이 생겼다 사라지면 읽을 수 없다.
   */
  lineAnchorId?: string | null;
}

export type CosmosViewMode = "3d" | "2d" | "list";
