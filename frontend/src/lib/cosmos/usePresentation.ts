"use client";

/**
 * 발표 모드 컨트롤러. 장면(PresentationScene)을 순서대로 적용하고 자동 진행·키보드를 처리한다.
 * 장면 적용(onScene)·종료(onExit)는 항상 이벤트 핸들러나 타이머 콜백에서만 호출한다.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { CosmosGraph } from "./graph";
import type { PresentationScene } from "./presentation";

export interface UsePresentationOptions {
  scenes: readonly PresentationScene[];
  graph: CosmosGraph | null;
  /** 장면 진입 시 대시보드 상태(stage·camera·selected)를 바꾼다 */
  onScene: (scene: PresentationScene, index: number) => void;
  /** 종료 시 대시보드 상태를 복구한다 */
  onExit: () => void;
}

export interface PresentationController {
  active: boolean;
  index: number;
  total: number;
  playing: boolean;
  scene: PresentationScene | null;
  isFirst: boolean;
  isLast: boolean;
  start: () => void;
  exit: () => void;
  next: () => void;
  prev: () => void;
  goTo: (index: number) => void;
  togglePlay: () => void;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function usePresentation(options: UsePresentationOptions): PresentationController {
  const { scenes, graph, onScene, onExit } = options;

  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);

  const onSceneRef = useRef(onScene);
  const onExitRef = useRef(onExit);
  useEffect(() => {
    onSceneRef.current = onScene;
    onExitRef.current = onExit;
  }, [onScene, onExit]);

  const total = scenes.length;
  const isLast = index >= total - 1;
  const isFirst = index <= 0;

  const goTo = useCallback(
    (target: number) => {
      if (total === 0) return;
      const clamped = Math.min(Math.max(target, 0), total - 1);
      const scene = scenes[clamped];
      if (!scene) return;
      setIndex(clamped);
      onSceneRef.current(scene, clamped);
    },
    [scenes, total],
  );

  const start = useCallback(() => {
    if (!graph || total === 0) return;
    setActive(true);
    setPlaying(true);
    goTo(0);
  }, [goTo, graph, total]);

  const exit = useCallback(() => {
    setActive(false);
    setPlaying(false);
    onExitRef.current();
  }, []);

  const next = useCallback(() => {
    if (isLast) {
      setPlaying(false);
      return;
    }
    goTo(index + 1);
  }, [goTo, index, isLast]);

  const prev = useCallback(() => {
    goTo(index - 1);
  }, [goTo, index]);

  const togglePlay = useCallback(() => {
    if (isLast && !playing) {
      // 마지막 장면에서 다시 재생하면 처음부터
      goTo(0);
      setPlaying(true);
      return;
    }
    setPlaying((p) => !p);
  }, [goTo, isLast, playing]);

  // 자동 진행 타이머
  useEffect(() => {
    if (!active || !playing) return;
    const scene = scenes[index];
    if (!scene) return;
    const id = window.setTimeout(() => {
      if (index >= scenes.length - 1) {
        setPlaying(false);
        return;
      }
      goTo(index + 1);
    }, scene.durationMs);
    return () => window.clearTimeout(id);
  }, [active, playing, index, scenes, goTo]);

  // 키보드: ← → Space Esc
  useEffect(() => {
    if (!active) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      switch (event.key) {
        case "ArrowRight":
          event.preventDefault();
          next();
          break;
        case "ArrowLeft":
          event.preventDefault();
          prev();
          break;
        case " ":
          event.preventDefault();
          togglePlay();
          break;
        case "Escape":
          event.preventDefault();
          exit();
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [active, next, prev, togglePlay, exit]);

  return {
    active,
    index,
    total,
    playing,
    scene: active ? (scenes[index] ?? null) : null,
    isFirst,
    isLast,
    start,
    exit,
    next,
    prev,
    goTo,
    togglePlay,
  };
}
