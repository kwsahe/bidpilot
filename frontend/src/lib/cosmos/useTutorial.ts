"use client";

/**
 * 튜토리얼 컨트롤러. usePresentation과 같은 구조로, 단계 진입(step.apply)·종료(onExit)는
 * 항상 이벤트 핸들러나 타이머 콜백에서만 호출한다 (effect 안에서 동기 setState 금지).
 *
 * 기록은 localStorage `bidpilot.tutorial.v1` = { seen, lastStep } 에 남기며,
 * 접근은 전부 try/catch로 감싼다 (프라이빗 모드·차단 환경 대비).
 * firstVisit(처음 방문 여부)은 useSyncExternalStore로 읽어 SSR/hydration 중에는 항상 false다.
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import type { CosmosGraph } from "./graph";
import type { TutorialActions, TutorialState, TutorialStep } from "./tutorial";

export const TUTORIAL_STORAGE_KEY = "bidpilot.tutorial.v1";

interface TutorialRecord {
  seen: boolean;
  lastStep: number;
}

const DEFAULT_RECORD: TutorialRecord = { seen: false, lastStep: 0 };

function readRecord(key: string): TutorialRecord {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return DEFAULT_RECORD;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_RECORD;
    const record = parsed as Partial<Record<keyof TutorialRecord, unknown>>;
    return {
      seen: record.seen === true,
      lastStep: typeof record.lastStep === "number" && Number.isFinite(record.lastStep) ? record.lastStep : 0,
    };
  } catch {
    return DEFAULT_RECORD;
  }
}

/** 저장 키별 기록 저장소 — 15단계 튜토리얼과 Quick Tour가 서로 다른 키를 쓴다. */
interface RecordStore {
  subscribe: (onChange: () => void) => () => void;
  getSeen: () => boolean;
  write: (patch: Partial<TutorialRecord>) => void;
}

const stores = new Map<string, RecordStore>();

function storeFor(key: string): RecordStore {
  const existing = stores.get(key);
  if (existing) return existing;
  const listeners = new Set<() => void>();
  const store: RecordStore = {
    subscribe: (onChange) => {
      listeners.add(onChange);
      window.addEventListener("storage", onChange);
      return () => {
        listeners.delete(onChange);
        window.removeEventListener("storage", onChange);
      };
    },
    getSeen: () => readRecord(key).seen,
    write: (patch) => {
      try {
        const next = { ...readRecord(key), ...patch };
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // 저장 실패는 무시한다 — 튜토리얼 자체는 동작해야 한다.
      }
      for (const listener of listeners) listener();
    },
  };
  stores.set(key, store);
  return store;
}

/** 서버/hydration 중에는 "이미 봤다"로 두어 환영 대화상자가 절대 SSR에 섞이지 않게 한다. */
const getSeenServer = () => true;

/** 첫 진입 환영 창 기록(2.0.5) — 새 키라 예전 환영 창 · 안내를 본 사람에게도 한 번 뜬다. */
export const WELCOME_STORAGE_KEY = "bidpilot.welcome.v2";

/** 「한 번 본 것」 기록 하나 — 튜토리얼과 같은 저장소 · 같은 SSR 규칙(서버 · hydration 중에는 본 것으로). */
export function useSeenRecord(key: string): { firstVisit: boolean; markSeen: () => void } {
  const store = useMemo(() => storeFor(key), [key]);
  const seen = useSyncExternalStore(store.subscribe, store.getSeen, getSeenServer);
  const markSeen = useCallback(() => store.write({ seen: true }), [store]);
  return { firstVisit: !seen, markSeen };
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export interface UseTutorialOptions {
  steps: readonly TutorialStep[];
  graph: CosmosGraph | null;
  state: TutorialState;
  actions: TutorialActions;
  /** 시작 직전에 호출 — 발표 모드 종료 등 */
  onStart?: () => void;
  /** 종료 시 대시보드 상태를 복구한다 */
  onExit: () => void;
  /** 기록 저장 키 (기본 bidpilot.tutorial.v1). Quick Tour는 별도 키를 쓴다 */
  storageKey?: string;
}

export interface TutorialController {
  active: boolean;
  index: number;
  total: number;
  step: TutorialStep | null;
  isFirst: boolean;
  isLast: boolean;
  /** 현재 단계의 과제가 끝났는지 (과제가 없으면 false) */
  taskDone: boolean;
  /** 한 번도 본 적이 없는지 (mount 후에만 true가 될 수 있다) */
  firstVisit: boolean;
  start: (fromIndex?: number) => void;
  exit: () => void;
  next: () => void;
  prev: () => void;
  goTo: (index: number) => void;
  /** 현재 단계의 과제를 대신 실행한다 */
  doTask: () => void;
  /** 환영 대화상자를 닫을 때 등 — 본 것으로 기록한다 */
  markSeen: () => void;
}

export function useTutorial(options: UseTutorialOptions): TutorialController {
  const { steps, graph, state, actions, onStart, onExit, storageKey = TUTORIAL_STORAGE_KEY } = options;

  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);

  const store = useMemo(() => storeFor(storageKey), [storageKey]);
  const seen = useSyncExternalStore(store.subscribe, store.getSeen, getSeenServer);

  // 최신 콜백·그래프·동작을 ref로 보관해 goTo 등이 매 렌더마다 바뀌지 않게 한다.
  const graphRef = useRef(graph);
  const actionsRef = useRef(actions);
  const onStartRef = useRef(onStart);
  const onExitRef = useRef(onExit);
  useEffect(() => {
    graphRef.current = graph;
    actionsRef.current = actions;
    onStartRef.current = onStart;
    onExitRef.current = onExit;
  }, [graph, actions, onStart, onExit]);

  const total = steps.length;
  const isFirst = index <= 0;
  const isLast = index >= total - 1;

  const goTo = useCallback(
    (target: number) => {
      if (total === 0) return;
      const clamped = Math.min(Math.max(target, 0), total - 1);
      const step = steps[clamped];
      if (!step) return;
      setIndex(clamped);
      const g = graphRef.current;
      if (g && step.apply) step.apply(actionsRef.current, g);
      store.write({ lastStep: clamped });
    },
    [steps, total, store],
  );

  const start = useCallback(
    (fromIndex = 0) => {
      if (!graphRef.current || total === 0) return;
      onStartRef.current?.();
      store.write({ seen: true });
      setActive(true);
      goTo(fromIndex);
    },
    [goTo, total, store],
  );

  const exit = useCallback(() => {
    setActive(false);
    store.write({ seen: true });
    onExitRef.current();
  }, [store]);

  const next = useCallback(() => {
    if (isLast) {
      exit();
      return;
    }
    goTo(index + 1);
  }, [exit, goTo, index, isLast]);

  const prev = useCallback(() => {
    goTo(index - 1);
  }, [goTo, index]);

  const doTask = useCallback(() => {
    const step = steps[index];
    const g = graphRef.current;
    if (!step?.task?.doItForMe || !g) return;
    step.task.doItForMe(actionsRef.current, g);
  }, [index, steps]);

  const markSeen = useCallback(() => {
    store.write({ seen: true });
  }, [store]);

  // 키보드: → ← Esc (입력창에 포커스가 있으면 무시)
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
  }, [active, next, prev, exit]);

  const step = active ? (steps[index] ?? null) : null;

  const taskDone = useMemo(() => {
    if (!step?.task || !graph) return false;
    return step.task.isDone(state, graph);
  }, [step, state, graph]);

  return {
    active,
    index,
    total,
    step,
    isFirst,
    isLast,
    taskDone,
    firstVisit: !seen,
    start,
    exit,
    next,
    prev,
    goTo,
    doTask,
    markSeen,
  };
}
