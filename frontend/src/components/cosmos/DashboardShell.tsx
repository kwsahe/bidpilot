"use client";

/**
 * Evidence Mission Control 셸.
 * TopBar / MissionStrip / WorkflowRail / CosmosStage / DetailPanel / BottomStrip을 배치하고
 * 선택·Focus·카메라·발표 모드·튜토리얼·Quick Tour·Guided Flow(5단계 화면 이해 흐름)·Human Review 상태를 한 곳에서 관리한다.
 *
 * Guided Flow는 "화면을 이해하는 순서"이고 왼쪽 8단계 레일은 "실제 분석 업무 흐름"이다.
 * Guided 단계는 카메라·강조·오른쪽 패널 내용만 바꾸며 분석 진행률·완료 상태를 바꾸지 않는다.
 */

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import BottomStrip from "@/components/cosmos/BottomStrip";
import { FocusChip, MapKey } from "@/components/cosmos/CosmosLegend";
import DayStrip from "@/components/cosmos/DayStrip";
import CosmosStage from "@/components/cosmos/CosmosStage";
import SupportDashboardBody, { SupportPageLink } from "@/components/cosmos/SupportDashboardBody";
import DetailPanel from "@/components/cosmos/DetailPanel";
import SimpleDashboard from "@/components/cosmos/SimpleDashboard";
import SupportSimpleView from "@/components/support/SupportSimpleView";
import { defaultReviewer, storeReviewer } from "@/components/cosmos/GatePanel";
import { GuidedCaptionBar } from "@/components/cosmos/GuidedFlowBar";
import LegendSheet from "@/components/cosmos/LegendSheet";
import MissionStrip from "@/components/cosmos/MissionStrip";
import ThisWeekPanel from "@/components/cosmos/ThisWeekPanel";
import TodayPanel from "@/components/cosmos/TodayPanel";
import PresentationOverlay from "@/components/cosmos/PresentationOverlay";
import { RunTimelineStrip } from "@/components/cosmos/RunTimeline";
import TopBar from "@/components/cosmos/TopBar";
import TutorialOverlay from "@/components/cosmos/TutorialOverlay";
import WelcomeDialog from "@/components/cosmos/WelcomeDialog";
import WorkflowRail from "@/components/cosmos/WorkflowRail";
import type { CosmosViewMode } from "@/components/cosmos/types";
import { Badge, Button, Skeleton } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/cosmos/format";
import { SCREEN_NAMES, SYNTHETIC_NOTICE } from "@/lib/terms";
import { REVIEW_STATUS_LABELS } from "@/lib/scoreNames";
import type { ReviewChecklist, ReviewDecision as SavedReview, ReviewStatus } from "@/types/analysis";
import {
  AUDIT_NODE_ID,
  EMPTY_FOCUS,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  detailNodeOf,
  focusIds,
  type ReviewDecision,
  type WorkflowStage,
  type WorkflowStepView,
} from "@/lib/cosmos/graph";
import {
  guidedFocus,
  guidedStepDef,
  readGuidedRecord,
  writeGuidedRecord,
  type GuidedRecord,
  type GuidedStep,
} from "@/lib/cosmos/guidedFlow";
import { PRESENTATION_SCENES, type CameraPreset, type PresentationScene } from "@/lib/cosmos/presentation";
import { QUICK_TOUR_STEPS, QUICK_TOUR_STORAGE_KEY } from "@/lib/cosmos/quickTour";
import {
  useCosmosDashboard,
  useDocumentVisible,
  useReducedMotion,
  type RunLog,
  type ReviewState,
  useNowMs,
} from "@/lib/cosmos/useCosmosDashboard";
import { landingStageOf } from "@/lib/cosmos/mission";
import { isSupportProgramId, requirementSheetHref } from "@/lib/selection";
import { TUTORIAL_STEPS, type TutorialActions, type TutorialState } from "@/lib/cosmos/tutorial";
import { usePresentation } from "@/lib/cosmos/usePresentation";
import { useSeenRecord, useTutorial, WELCOME_STORAGE_KEY } from "@/lib/cosmos/useTutorial";
import { useWebGLSupport } from "@/lib/cosmos/webgl";
import { useOrganizationId, useOrganizations } from "@/lib/organization";
import { Modal } from "@/components/ui/overlays";
import { AnalysisLoadingProvider } from "@/lib/cosmos/analysisLoading";
import { confirmDiscard as confirmUnsaved, forgetUnsaved, hasUnsaved } from "@/lib/unsavedGuard";
import { setDisplayMode, useDashboardOpensSimple, useDisplayMode, type DisplayMode } from "@/lib/viewMode";

const RAIL_CAMERA: Record<WorkflowStage, CameraPreset> = {
  1: "notice",
  2: "notice",
  3: "notice",
  4: "requirements",
  5: "evidence",
  6: "proposal",
  7: "audit",
  8: "review",
};

const RAIL_SELECT: Record<WorkflowStage, string | null> = {
  1: NOTICE_NODE_ID,
  2: NOTICE_NODE_ID,
  3: NOTICE_NODE_ID,
  4: null,
  5: null,
  6: PROPOSAL_NODE_ID,
  7: AUDIT_NODE_ID,
  8: null,
};

/** 실행 타임라인 단계 → 워크플로 단계 (레일의 "실행 중" 표시용). */
const PHASE_STAGE: Partial<Record<keyof RunLog, WorkflowStage>> = {
  notice: 1,
  candidate: 2,
  fit: 2,
  eligibility: 3,
  parse: 4,
  evidence: 5,
  proposal: 6,
  audit: 7,
};

/** 셸 전용 키프레임 — 이전 이름을 쓰는 하위 컴포넌트(패널·발표·튜토리얼)를 위해 유지한다. */
const SHELL_KEYFRAMES = `
@keyframes cosmos-panel-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes cosmos-pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--cosmos-blue) 45%, transparent); } 50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--cosmos-blue) 0%, transparent); } }
@keyframes cosmos-scene-progress { from { width: 0%; } to { width: 100%; } }
@keyframes cosmos-skeleton { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
`;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

const COMPACT_QUERY = "(max-width: 1023px)";
function subscribeCompact(onChange: () => void): () => void {
  const media = window.matchMedia(COMPACT_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const getCompact = () => window.matchMedia(COMPACT_QUERY).matches;
const getCompactServer = () => false;

/** 1024px 미만(레일이 칩으로 바뀌는 폭)인지. 서버 렌더에서는 false. */
function useSyncExternalStoreCompat(): boolean {
  return useSyncExternalStore(subscribeCompact, getCompact, getCompactServer);
}

/**
 * URL 옵션 — 발표·검수용.
 *   ?view=2d|3d|list  첫 뷰 모드 (기본 3d)
 *   ?welcome=0        환영 대화상자 생략 (튜토리얼·안내 기록은 건드리지 않는다)
 *   ?guided=0         저장된 Guided 단계를 무시하고 탐색 모드로 시작 (기록은 건드리지 않는다)
 *   ?guided=1..5      해당 Guided 단계로 시작 (검수·스크린샷용. 카메라는 기본 시점, 강조·패널만 그 단계)
 *   ?stage=1..8       첫 내려앉기를 그 단계로 (다른 화면이 넘겨준 단계 · 27차 LNK-07) — 아래 `readUrlStage`
 * hydration 중(서버 스냅샷)에는 항상 기본값이라 첫 화면이 서버와 같다.
 */
interface UrlOptions {
  view: CosmosViewMode | null;
  welcome: boolean;
  guided: boolean;
  guidedStart: GuidedStep | null;
}
const DEFAULT_URL_OPTIONS: UrlOptions = { view: null, welcome: true, guided: true, guidedStart: null };
let cachedUrlOptions: UrlOptions | null = null;
function readUrlOptions(): UrlOptions {
  if (cachedUrlOptions) return cachedUrlOptions;
  try {
    const params = new URLSearchParams(window.location.search);
    const view = params.get("view");
    const guidedParam = Number(params.get("guided"));
    cachedUrlOptions = {
      view: view === "2d" || view === "3d" || view === "list" ? view : null,
      welcome: params.get("welcome") !== "0",
      guided: params.get("guided") !== "0",
      guidedStart: guidedParam >= 1 && guidedParam <= 5 ? (guidedParam as GuidedStep) : null,
    };
  } catch {
    cachedUrlOptions = DEFAULT_URL_OPTIONS;
  }
  return cachedUrlOptions;
}
const getUrlOptionsServer = () => DEFAULT_URL_OPTIONS;
const subscribeNever = () => () => {};

/**
 * `?stage=1..8` — 요구사항 정리표 등 다른 화면이 넘겨준 단계 (27차 LNK-07).
 *
 * `readUrlOptions` 에 넣지 않는다 — 그쪽은 첫 방문 값을 모듈에 굳혀 두므로, 정리표에서 링크로 돌아오는
 * 두 번째 방문에는 새 값을 못 읽는다. 여기서는 매번 주소를 읽고, 한 번 내려앉으면 주소에서 지운다
 * (남겨 두면 다른 공고를 골라도 계속 그 단계로 내려앉는다).
 */
function readUrlStage(): WorkflowStage | null {
  try {
    const value = Number(new URLSearchParams(window.location.search).get("stage"));
    return Number.isInteger(value) && value >= 1 && value <= 8 ? (value as WorkflowStage) : null;
  } catch {
    return null;
  }
}
const readUrlStageServer = (): WorkflowStage | null => null;
function dropUrlStage(): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete("stage");
    window.history.replaceState(window.history.state, "", url.toString());
  } catch {
    // history 접근 실패는 무시한다 — 다음 등장도 같은 단계로 내려앉을 뿐이다.
  }
}

/** 저장된 Guided 기록 — mount 때 한 번만 읽는다 (이후 변경은 state가 담당). 서버 스냅샷은 "탐색 모드·이미 봄". */
const GUIDED_SERVER_RECORD: GuidedRecord = { step: null, seen: true };
let cachedGuidedRecord: GuidedRecord | null = null;
function readGuidedRecordOnce(): GuidedRecord {
  if (!cachedGuidedRecord) cachedGuidedRecord = readGuidedRecord();
  return cachedGuidedRecord;
}
const getGuidedServer = () => GUIDED_SERVER_RECORD;

/**
 * 화면 뼈대.
 *
 * `loading` 은 「지금 분석 결과를 불러오는 중인가」다. 이 값이 없으면 공고를 바꾼 직후
 * 2~5초 동안 KPI·패널이 「미실행」을 보여주고, 담당자는 그것을 「안 돌렸구나」로 읽어
 * 이미 돌아간 분석을 다시 누른다 (ISSUE-011). 값 하나를 화면 전체가 같은 답으로 쓰도록
 * context 로 내린다.
 */
function Frame({ children, loading = false }: { children: ReactNode; loading?: boolean }) {
  return (
    <AnalysisLoadingProvider loading={loading}>
      {/* 높이를 뷰포트에 **묶지 않는다** (ISSUE-122 · prompt_04 §3-B-1).

          예전에는 `lg:h-dvh` 로 페이지 높이를 창 높이에 못 박았다. 의도는 「아래 3단
          (레일·3D·상세)이 남은 공간을 정확히 나눠 갖는다」였는데, 이 화면은 3D 위에
          「오늘 달라진 것 · 이번 주 할 일 · 지금 할 일 · 미션」이 먼저 오도록 짜여 있어
          그 크롬만 **873px** 이다(2000×669 실측, 창 높이와 무관하게 같다). 그래서 남는
          공간이 창 높이 669 에서 0, 1200 에서도 287 뿐이었고 — `flex-1` 인 가운데 행이
          눌리면서 우측 상세 열이 **0px(669)·263px(1200)** 로 접혀, `shrink-0` 인 머리와
          「사람의 최종 결정」 블록이 열 밖으로 흘러 바닥 출처줄 위에 겹쳐 그려졌다.
          스크롤 본문은 32px 로 눌려 내용 758px 을 담지 못했다.

          `min-h-dvh` 만 남기면 둘 다 된다 — 남는 공간이 있으면 `flex-1` 이 그대로 받아
          한 화면을 채우고, 없으면 페이지가 길어져 스크롤된다. 높이를 푸는 것이 낮은 창만의
          문제가 아니었다: **높이 1200 에서도 접혀 있었다.** 검사가 높이 하나로만 재서
          못 잡았을 뿐이다. */}
      <div className="mc-page-bg relative flex min-h-dvh flex-col font-sans text-[14px] text-cosmos-text">
        <style>{SHELL_KEYFRAMES}</style>
        {children}
      </div>
    </AnalysisLoadingProvider>
  );
}

/**
 * 불러오는 중. **무엇을** 불러오는지 적는다.
 *
 * 지원사업으로 갈아탈 때 이전 입찰 분석이 그대로 남아 있으면 담당자가 다른 사업의 결과를
 * 이 사업의 것으로 읽는다. 그래서 결과를 먼저 지우고(useCosmosDashboard.fetchAll)
 * 이 화면을 띄운다 — 빈 화면이 아니라 «지금 무엇을 기다리는가»가 보여야 한다.
 */
function LoadingView({ reducedMotion, kind = "notice" }: { reducedMotion: boolean; kind?: "notice" | "support" }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:flex-row" role="status" aria-live="polite">
      <div className="mc-panel flex shrink-0 flex-col gap-2 p-3 lg:w-[236px]">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" reducedMotion={reducedMotion} />
        ))}
      </div>
      <div className="flex min-h-[420px] flex-1 items-center justify-center rounded-xl border border-cosmos-border">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="text-[12px] font-medium uppercase tracking-[0.18em] text-cosmos-cyan">
            근거 기반 AI 수주 도우미
          </span>
          <span className="text-[20px] font-semibold text-cosmos-text">BidPilot AI</span>
          <span className="text-[13px] text-cosmos-secondary">
            {kind === "support" ? "기업마당 지원사업 신청 분석을 불러오는 중" : "나라장터 입찰 분석 데이터를 불러오는 중"}
          </span>
          <Skeleton className="mt-2 h-1.5 w-40" reducedMotion={reducedMotion} />
        </div>
      </div>
      <div className="mc-panel flex shrink-0 flex-col gap-3 p-4 lg:w-[380px]">
        <Skeleton className="h-4 w-1/2" reducedMotion={reducedMotion} />
        <Skeleton className="h-16 w-full" reducedMotion={reducedMotion} />
        <Skeleton className="h-4 w-2/3" reducedMotion={reducedMotion} />
        <Skeleton className="h-24 w-full" reducedMotion={reducedMotion} />
      </div>
    </div>
  );
}

function ErrorView({ message, onRetry }: { message: string; onRetry: () => void }) {
  // 서버 실행 안내는 정말 연결이 안 될 때만 띄운다. 서버가 멀쩡한데 이 문구가 뜨면
  // 엉뚱한 곳을 고치게 된다 (실제로 발표 준비 중 그런 일이 있었다).
  const looksOffline = /연결할 수 없습니다|Failed to fetch|NetworkError/i.test(message);
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center p-6" role="alert">
      <div className="mc-panel max-w-md border-cosmos-red/40 p-6">
        <p className="text-[15px] font-semibold text-cosmos-text">분석 데이터를 불러오지 못했습니다</p>
        <p className="mt-2 text-[13px] leading-6 text-cosmos-secondary">{message}</p>
        {/*
          예전에는 여기에 「backend 폴더에서 uvicorn app.main:app --reload 로 FastAPI 를 실행하세요」가 떴다.
          이 화면을 쓰는 사람은 사업담당자다 — 그 문장으로 할 수 있는 일이 없고, 게다가 틀린 안내였다
          (서버는 떠 있는데 AI 검색 키가 거부돼 실패한 경우에도 같은 문장이 나왔다).
        */}
        {looksOffline && (
          <p className="mt-2 text-[12px] leading-5 text-cosmos-muted">
            잠시 후 다시 시도해 주세요. 계속되면 관리자에게 알려 주세요.
          </p>
        )}
        <Button variant="primary" className="mt-4" onClick={onRetry}>
          다시 시도
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 사람의 최종 검토 저장 — 화면 state 로만 두면 공고를 바꾸는 순간 사라진다
// ---------------------------------------------------------------------------

// 단추 · 대화상자와 같은 「검토 승인」 — 「제출 승인」은 「시스템은 제출을 확정하지 않습니다」와 부딪혔다 (DSH-19).
const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  ...(REVIEW_STATUS_LABELS as Record<ReviewStatus, string>),
  pending: "검토 전",
};

/** 승인 전에 사람이 직접 확인해야 하는 항목 (backend review_service 가 강제한다). */
const REVIEW_CHECKS: Array<{ key: keyof ReviewChecklist; label: string }> = [
  { key: "auditor_findings_reviewed", label: "제출 전 누락 점검 발견 항목을 확인했습니다" },
  { key: "eligibility_check_resolved", label: "「확인 필요」 자격조건을 해소했습니다" },
  { key: "evidence_confirmed", label: "회사 근거 원문을 확인했습니다" },
  { key: "numbers_verified", label: "제안서 수치를 원문과 대조했습니다" },
];

const EMPTY_REVIEW_CHECKLIST: ReviewChecklist = {
  auditor_findings_reviewed: false,
  eligibility_check_resolved: false,
  evidence_confirmed: false,
  numbers_verified: false,
};

const reviewInputClass =
  "mc-focus min-h-9 w-full rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2.5 text-[12.5px] text-cosmos-text placeholder:text-cosmos-muted";

/**
 * 승인/보류를 «저장»하는 대화상자.
 *
 * 담당자 이름과 확인 항목 없이는 backend 가 승인을 받지 않는다(422). 그것을 화면에서
 * 미리 묻지 않으면 버튼은 눌리는데 저장은 매번 실패한다.
 */
function ReviewSaveDialog({
  target,
  saved,
  review,
  audited,
  openConditions = 0,
  onClose,
}: {
  target: "approved" | "hold";
  saved: SavedReview | null;
  review: ReviewState;
  /** 제출 전 누락 점검을 돌렸는가 — 안 돌렸으면 첫 확인 항목이 그 사실을 확인하게 한다 (DSH-02) */
  audited: boolean;
  /** 남은 참가 차단 + 확인 전 자격 조항 수(43차 M17 · E2E-08) — 「해소했습니다」 칸에 경고를 붙인다. */
  openConditions?: number;
  onClose: () => void;
}) {
  const approving = target === "approved";
  const checks = (audited
    ? REVIEW_CHECKS
    : REVIEW_CHECKS.map((c) =>
        c.key === "auditor_findings_reviewed" ? { ...c, label: "제출 전 누락 점검을 돌리지 않았음을 확인했습니다" } : c,
      )
  ).map((c) =>
    c.key === "eligibility_check_resolved" && openConditions > 0
      ? { ...c, label: `${c.label} — ⚠ 화면에는 아직 참가 차단 · 확인 전 조항 ${openConditions}건이 남아 있습니다` }
      : c,
  );
  // 이미 저장된 검토가 있으면 그때 적은 이름이 이긴다 — 다른 사람이 승인한 기록을
  // 지금 로그인한 사람 이름으로 덮어쓰면 안 된다.
  const [reviewer, setReviewer] = useState(() => saved?.reviewer ?? defaultReviewer());
  const [note, setNote] = useState(saved?.note ?? "");
  const [checklist, setChecklist] = useState<ReviewChecklist>(saved?.checklist ?? EMPTY_REVIEW_CHECKLIST);

  const unchecked = checks.filter((c) => !checklist[c.key]);
  const canSave = reviewer.trim().length > 0 && (!approving || unchecked.length === 0);

  const submit = () => {
    if (!canSave || review.saving) return;
    storeReviewer(reviewer.trim());
    void review
      .save({
        status: approving ? "approved" : "on_hold",
        checklist,
        reviewer: reviewer.trim(),
        note: note.trim() || null,
      })
      .then((ok) => {
        // 실패하면 닫지 않는다 — 사유를 그 자리에서 보여준다.
        if (ok) onClose();
      });
  };

  // 공용 Modal 로 옮긴다 (ISSUE-033). 예전에는 여기서 Escape 만 직접 처리했고,
  // 초기 포커스·Tab 가둠·포커스 복원이 없었다 — 키보드로 쓰는 사람은 대화상자가 떠 있는데
  // Tab 을 누르면 뒤 화면을 헤매게 된다. 전역 Escape 가 선택 해제로 가로채는 문제도 함께 사라진다.
  return (
    <Modal open onClose={onClose} title={approving ? "검토 승인 저장" : "보류 저장"}>
      <>
        <p className="text-[12px] leading-5 text-cosmos-secondary">
          이 판단은 담당자 이름과 함께 서버에 남습니다. 시스템은 제출을 확정하지 않습니다.
        </p>

        <label className="text-[12px] text-cosmos-muted" htmlFor="review-reviewer">
          담당자 (필수)
        </label>
        <input
          id="review-reviewer"
          className={reviewInputClass}
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          placeholder="이름"
        />

        {approving && (
          <fieldset className="flex flex-col gap-1.5 rounded-md border border-cosmos-border px-2.5 py-2">
            <legend className="px-1 text-[12px] text-cosmos-muted">확인 항목 — 모두 체크해야 승인됩니다</legend>
            {checks.map((check) => (
              <label key={check.key} className="flex cursor-pointer items-start gap-2 text-[12.5px] leading-5 text-cosmos-text">
                <input
                  type="checkbox"
                  aria-label={check.label}
                  className="mt-0.5 h-4 w-4 accent-cosmos-cyan"
                  checked={checklist[check.key]}
                  onChange={(e) => setChecklist((prev) => ({ ...prev, [check.key]: e.target.checked }))}
                />
                <span>{check.label}</span>
              </label>
            ))}
          </fieldset>
        )}

        <label className="text-[12px] text-cosmos-muted" htmlFor="review-note">
          메모 (선택)
        </label>
        <input
          id="review-note"
          className={reviewInputClass}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="무엇을 보고 결정했는지"
        />

        {approving && unchecked.length > 0 && (
          <p className="text-[12px] leading-4 text-cosmos-amber" role="note">
            남은 확인 항목 {unchecked.length}건: {unchecked.map((c) => c.label).join(" · ")}
          </p>
        )}
        {review.error && (
          <p role="alert" className="rounded-md border border-cosmos-red/40 bg-cosmos-red/10 px-2.5 py-1.5 text-[12px] leading-5 text-cosmos-red">
            {review.error}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-1.5">
          <Button size="sm" variant="secondary" onClick={onClose}>
            취소
          </Button>
          <Button size="sm" variant="primary" disabled={!canSave || review.saving} onClick={submit}>
            {review.saving ? "저장 중…" : "저장"}
          </Button>
        </div>
      </>
    </Modal>
  );
}

/**
 * 저장된 검토 상태 한 줄.
 *
 * 화면 토글과 서버 저장분이 다르면 「임시 (저장 전)」이라고 적는다 — 저장되지 않은
 * 승인이 저장된 결정처럼 보이면 안 된다.
 */
function ReviewStatusBar({
  review,
  onSave,
}: {
  review: ReviewState;
  onSave: () => void;
}) {
  const saved = review.saved;
  if (!saved && !review.unsaved && !review.error) return null;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-cosmos-border bg-cosmos-panel px-3 py-1.5 text-[12px]">
      <span className="text-cosmos-muted">최종 검토</span>
      {saved ? (
        <>
          <Badge tone={saved.status === "approved" ? "pass" : saved.status === "rejected" ? "fail" : "warn"} glyph>
            {REVIEW_STATUS_LABEL[saved.status]}
          </Badge>
          <span className="min-w-0 truncate text-cosmos-secondary">
            {saved.reviewer} · {formatDateTime(saved.decided_at)}
          </span>
        </>
      ) : (
        <Badge tone="muted" glyph>
          저장된 검토 없음
        </Badge>
      )}
      {review.saving ? (
        <Badge tone="muted">저장 중…</Badge>
      ) : (
        review.unsaved && (
          <>
            <Badge tone="warn" glyph>
              임시 (저장 전)
            </Badge>
            <button type="button" onClick={onSave} className="mc-focus rounded text-cosmos-cyan hover:underline">
              다시 저장
            </button>
          </>
        )
      )}
      {review.error && (
        <span role="alert" className="min-w-0 flex-1 text-cosmos-red">
          {review.error}
        </span>
      )}
    </div>
  );
}

export default function DashboardShell() {
  // 대시보드는 열 때마다 쉬운 보기(37차 §3-F · 담당자 결정 2026-10-14) — 주소 `?mode=full`(시연 링크)만 예외. 다른 훅보다 먼저.
  useDashboardOpensSimple();
  const reducedMotion = useReducedMotion();
  const documentVisible = useDocumentVisible();
  const webglSupported = useWebGLSupport();
  const compact = useSyncExternalStoreCompat();
  const urlOptions = useSyncExternalStore(subscribeNever, readUrlOptions, getUrlOptionsServer);
  const urlStage = useSyncExternalStore(subscribeNever, readUrlStage, readUrlStageServer);
  const storedGuided = useSyncExternalStore(subscribeNever, readGuidedRecordOnce, getGuidedServer);
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();
  // 상세 패널(전체 · 쉬운 보기)에 같은 회사 표시 이름을 넘긴다(26차 ISSUE-149).
  const organizationName = organizations.list?.organizations.find((o) => o.organization.organization_id === organizationId)?.organization.display_name ?? null;
  const dashboard = useCosmosDashboard({ reducedMotion, organizationId });
  const { graph, stage, setStage } = dashboard;
  /** 「찾는 낱말」 바로 찾기로 새 공고가 들어왔다(2.0.7) — 고르기 칸 목록과 펼친 「이번 주 할 일」만 다시 받는다(접힌 줄 숫자만 새로 세면 목록과 갈렸다). */
  const [weekTick, setWeekTick] = useState(0);
  const onKeywordNotices = () => {
    dashboard.reloadLists();
    setWeekTick((n) => n + 1);
  };

  /**
   * 등장 애니메이션이 끝나면 **가장 먼저 처리할 단계**로 내려앉는다.
   *
   * 예전에는 언제나 8단계(담당자 최종 결정)가 열린 채로 멈췄다. 진행 현황이 2/8 인 공고에서도
   * 오른쪽 패널에 최종 검토가 떠 있어서, 담당자가 「지금이 8단계인가」로 읽었다.
   * 등장마다 한 번만 내려앉고, 그 뒤 단계 이동은 사용자 몫이다 — 열어 본 것이 완료로 바뀌지 않는다.
   * 등장은 공고를 바꿀 때만이 아니라 분석 실행·회사 전환으로 같은 공고를 다시 불러올 때도 돈다 — 그때도
   * 8 에 멈추지 않고 내려앉는다(21차: 8 이면 지도가 ⑧ 결정만 밝혀 새 결과가 이름 없는 점이 된다).
   */
  const landedRef = useRef<string | null>(null);
  const landingKey = graph ? `${graph.source.notice.id}:${dashboard.revealRun}` : null;
  // 레이아웃 효과 — 등장이 끝난 커밋(단계 8)이 지도에 한 프레임도 그려지지 않게 같은 커밋 안에서 내려앉힌다.
  // 지도는 단계마다 카메라가 정거장을 옮겨 가므로, 8 로 한 번 갔다가 돌아오면 그 이동이 보인다 (21차).
  // 판정·조건·제안서가 **도착한 뒤에** 내려앉는다(22차) — 먼저 내려앉으면 조항 확인(③)을 모르는 그래프로 정해져
  // 움직임을 줄인 환경(등장 없음)이나 느린 응답에서 ⑧ 에 내려앉았다. 기다리는 동안 사람이 고르면 그것이 먼저다(goStage).
  useLayoutEffect(() => {
    if (!graph || !landingKey || !dashboard.revealDone || dashboard.analysisLoading) return;
    if (landedRef.current === landingKey) return;
    landedRef.current = landingKey;
    // 주소가 넘겨준 단계가 있으면 그리로 — 한 번만 쓰고 지운다 (27차 LNK-07).
    const target = urlStage ?? landingStageOf(graph);
    if (urlStage !== null) dropUrlStage();
    if (target !== stage) setStage(target);
  }, [graph, landingKey, dashboard.revealDone, dashboard.analysisLoading, stage, setStage, urlStage]);

  /**
   * 사람이 고른 단계로 옮긴다. 등장 중에 고르면 `setStage` 가 등장을 끝내는데, 그 순간 「내려앉기」가 돌아
   * 방금 고른 단계를 덮는다(21차 리허설: 1단계를 눌렀는데 3단계로 돌아감) — 고른 것으로 내려앉은 셈 친다.
   * 레일·노드 선택·안내·발표·튜토리얼·화살표 키가 모두 이 길을 쓴다.
   */
  /**
   * 이번 등장에서 사람이 이미 골랐는가 — 렌더에서 읽어야 하므로 ref 가 아니라 state(이벤트 처리기에서만 바꾼다).
   * 골랐으면 내려앉기가 덮지 않고, 기다리는 동안에도 고른 것을 그린다.
   */
  const [chosenKey, setChosenKey] = useState<string | null>(null);
  const markChosen = useCallback(() => {
    landedRef.current = landingKey;
    setChosenKey(landingKey);
  }, [landingKey]);
  const goStage = useCallback(
    (target: WorkflowStage) => {
      markChosen();
      setStage(target);
    },
    [markChosen, setStage],
  );
  /**
   * 내려앉기를 기다리는 동안(등장 중 · 판정이 아직 오는 중)에는 **내려앉을 정거장**을 그린다 — 원래 단계(등장이
   * 끝난 8)를 그리면 ⑧ 이 보였다가 ③ 으로 뛴다(움직임 줄이기에서는 늘, 판정이 늦으면 ③ → ⑧ → ③) (22차 검토).
   * 지도는 등장 중에도, 레일·상세·KPI 는 등장이 끝난 뒤부터(등장 중에는 단계가 차례로 켜지는 것이 등장이다).
   */
  const landingPending =
    graph !== null && landingKey !== null && chosenKey !== landingKey && (!dashboard.revealDone || dashboard.analysisLoading);
  const landingTarget = landingPending && graph ? (urlStage ?? landingStageOf(graph)) : null;
  const mapStage: WorkflowStage = landingTarget ?? stage;
  const panelStage: WorkflowStage = dashboard.revealDone && landingTarget !== null ? landingTarget : stage;

  /**
   * 잃을 것이 있을 때만 확인을 받는다.
   *
   * 공고 전환의 확인은 여기서 띄운다. 회사 전환은 모든 화면이 같은 선택기(`OrganizationPicker`)로 묻는다 —
   * 화면마다 따로 물어보면 조건이 서로 어긋나고, 어느 한쪽만 고쳐지는 일이 생긴다.
   */
  const confirmDiscard = useCallback(
    (losing: boolean, message: string) => !losing || window.confirm(message),
    [],
  );

  /**
   * 회사 변경: 기존 분석 결과는 다른 회사 결과처럼 재사용하지 않는다 — 결과가 있으면 확인 후 바꾸고 다시 불러온다.
   * 묻고 바꾸는 일은 회사 선택기(`OrganizationPicker`)가 모든 화면에서 같게 한다 (27차 UNI-07) — 여기서는 물을 말만 정한다.
   */
  const hasOrganizationResults = Boolean(
    graph && (graph.source.analysis.proposal || graph.source.analysis.audit || graph.source.analysis.conditions),
  );
  const organizationLoseMessage = hasOrganizationResults
    ? "회사를 바꾸면 현재 공고의 분석 결과(제안서·점검·조건)는 새 회사 기준으로 다시 실행해야 합니다. 계속할까요?"
    : null;

  // 사용자가 토글하기 전까지는 URL의 ?view= 를 따른다 (effect 없이 파생값으로 처리).
  //
  // 작은 화면에서는 2D 가 기본이다. 3D 는 관계를 보여주는 데는 좋지만 좁은 폭에서는
  // 라벨이 겹치고 조작이 어렵다 — 업무를 못 하게 되면 안 된다.
  // 3D 는 그대로 있고, 위 전환 버튼으로 언제든 켤 수 있다.
  /**
   * 보기 선택. null = 사람이 고르지 않음(URL ?view= 가 있으면 그것, 없으면 지도 기본값) · "auto" = 지도 기본값(안내·발표가
   * 목록에서 지도로 돌려놓을 때 — URL 이 목록이어도 지도, 사람이 고른 것으로 치지 않는다) · 그 밖 = 사람이 고른 보기.
   */
  const [viewOverride, setViewMode] = useState<CosmosViewMode | "auto" | null>(null);
  // Guided Flow 단계 — 저장된 단계(재방문)는 사용자가 바꾸기 전까지 그대로 쓴다. 보기 계산이 읽으므로 여기 둔다.
  const [guidedOverride, setGuidedOverride] = useState<GuidedStep | null | undefined>(undefined);
  const rawGuidedStep: GuidedStep | null =
    guidedOverride !== undefined ? guidedOverride : (urlOptions.guidedStart ?? (urlOptions.guided ? storedGuided.step : null));
  /** 사람이 보기를 고르지 않았을 때의 지도. */
  // 10-31 대표 결정 — 3D 는 화면에서 뺀다(「보기도 힘들고 메리트도 없다」 · 코드는 남김). 지도는 늘 2D 다.
  const mapDefault: CosmosViewMode = "2d";
  // 사람이 3D 를 **명시로** 고르면(상단 단추 · ?view=3d) 존중한다 — 대신 도구막대에 한 줄 알린다.
  // 기본은 **읽히는 단계 목록**이다 (28차 §3-F · 담당자 지시 「3D 대시보드는 여전히 개판」). 안내 · 발표 · 튜토리얼은
  // 「auto」로 지도를 연다(아래 · 지도를 비추는 장면이라) — 끝나면 목록으로 돌아온다.
  // 5단계 안내도 튜토리얼 · 발표처럼 **켜져 있는 동안 지도**다 — 안내 바가 지도 아래에만 그려져 목록 기본에서는 보이지 않았다
  // (29차 R28-03). 사람이 고른 보기(상단 단추 · ?view=)는 이긴다. 안내를 끝내면(「탐색 모드」) 목록으로 돌아온다.
  const pickedView: CosmosViewMode =
    viewOverride === "auto" ? mapDefault : (viewOverride ?? urlOptions.view ?? (rawGuidedStep !== null ? mapDefault : "list"));
  // 옛 주소 ?view=3d · 안내 · 발표가 고른 3D 도 2D 로(10-31 대표 결정)
  const viewMode: CosmosViewMode = pickedView === "3d" ? "2d" : pickedView;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>("overview");
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [resetSignal, setResetSignal] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // 마감 임박 판정에 쓴다. 서버 렌더에서는 null 이라 「계산 중」으로 나온다.
  const nowMs = useNowMs();
  const [legendOpen, setLegendOpen] = useState(false);
  /**
   * 8단계 레일은 기본으로 접는다 (번호만, 폭 64px).
   *
   * 지도가 이미 8정거장의 길을 이름과 함께 보여 준다(21차) — 레일은 번호만으로 충분하다.
   * 레일 자체는 그대로 있고 머리의 버튼으로 언제든 펼친다.
   */
  const [railCollapsed, setRailCollapsed] = useState(true);

  // ---------------------------------------------------------------------------
  // Guided Flow — 5단계 화면 이해 흐름. 단계 상태(`guidedOverride` · `rawGuidedStep`)는 보기 계산 앞에 있다(29차 R28-03).
  // ---------------------------------------------------------------------------
  /**
   * 5단계 안내를 **사람이 직접 켰는가**(「?」 대화상자 · 도구막대 단추). 쉬운 보기에서 전체 보기로 잠시 넘기는 조건이다
   * (24차 §3-1) — 저장된 단계 복원 · `?guided=` · 환영 창 「둘러보기」는 조건이 아니다. 안내가 끝나는 길에서 지운다.
   */
  const [guidedByUser, setGuidedByUser] = useState(false);

  /**
   * 고른 노드의 정거장으로 옮긴다 (21차 — 지도는 한 번에 한 정거장을 밝힌다).
   * 목록 보기는 지금 단계**까지의** 행만 보이므로 올리기만 한다 — 내리면 고른 행 말고 전부 사라진다.
   */
  const followStage = useCallback(
    (nodeStage: WorkflowStage) => {
      if (viewMode === "list" ? nodeStage > stage : nodeStage !== stage) goStage(nodeStage);
      // 단계가 그대로여도 사람이 고른 것이다 — 기다리던 내려앉기가 이 선택을 덮지 않게 (22차 검토).
      // 등장도 여기서 멈춘다 — 남은 타이머가 고른 항목을 두고 ⑧ 까지 끌고 가지 않게(등장 중 4단계 줄을 누르면 ⑧ 에 멈췄다).
      else goStage(stage);
    },
    [viewMode, stage, goStage],
  );

  /** 노드 선택. 그 노드의 정거장(단계)이 지금 정거장이 된다. Guided 단계는 유지한다. */
  const selectNode = useCallback(
    (id: string | null) => {
      // 고른 묶음을 다시 누르면(목록 · 2D 는 선택 해제로 온다) 묶음도 접는다 — 한 번에 「눌러서 접기」 (DSH-20).
      if (!id && selectedId && graph?.nodeById.get(selectedId)?.kind === "requirement-group") dashboard.toggleCategory(null);
      setSelectedId(id);
      setFocusNodeId(id);
      setHoveredId(null);
      if (id) {
        // 묶음에 접혀 그림에 없는 요구사항 · 발견도 상세와 같은 노드로 본다 (R27U-LNK-R8)
        const node = graph ? detailNodeOf(graph, id) : null;
        if (node) followStage(node.stage);
        // 요구사항 묶음을 누르면 그 유형만 펼친다. 같은 묶음을 다시 누르면 접혀
        // 집계 Overview 로 돌아간다 — 「전체 보기」는 모든 원시 노드를 펼치는
        // 기능이 아니라 이 Overview 로 돌아가는 것이다.
        if (node?.kind === "requirement-group" && node.itemType) {
          dashboard.toggleCategory(node.itemType);
        } else if (node?.kind === "requirement" && node.itemType && !graph?.nodeById.has(id) && dashboard.expandedCategory !== node.itemType) {
          // 묶음에 접힌 요구사항(4단계 주의 항목 줄)이면 그 묶음을 펼친다 — 다음 그림에 노드가 생겨 지도에서도 강조된다.
          // ponytail: 펼친 묶음도 앞 MAX_EXPANDED_CHILDREN(8)건만 그린다 — 그 뒤 항목은 상세만 열린다.
          dashboard.toggleCategory(node.itemType);
        }
        setDrawerOpen(true);
      }
    },
    [graph, followStage, dashboard, selectedId],
  );

  /** Guided 단계 적용 — 카메라·강조·패널만 바꾸고 분석 상태는 건드리지 않는다. null이면 탐색 모드. */
  const applyGuided = useCallback(
    (step: GuidedStep | null) => {
      setGuidedOverride(step);
      writeGuidedRecord({ step, seen: true });
      setHoveredId(null);
      if (step === null) {
        setGuidedByUser(false);
        return;
      }
      const def = guidedStepDef(step);
      setSelectedId(null);
      if (!graph) return;
      // 안내 단계의 정거장으로 옮긴다 (등장 상태만 바꾸고, 진행률은 그대로).
      if (stage !== def.revealStage) goStage(def.revealStage);
      setFocusNodeId(def.focusNodeId(graph));
      setCameraPreset(def.camera);
    },
    [graph, stage, goStage],
  );

  const { toggleCategory } = dashboard;
  const resetView = useCallback(() => {
    setSelectedId(null);
    setHoveredId(null);
    setFocusNodeId(null);
    setCameraPreset("overview");
    setResetSignal((n) => n + 1);
    setGuidedOverride(null);
    setGuidedByUser(false);
    writeGuidedRecord({ step: null });
    // 「처음 상태」에는 펼친 묶음도 접힌 것이 들어간다 (DSH-20).
    toggleCategory(null);
  }, [toggleCategory]);

  const applyScene = useCallback(
    (scene: PresentationScene) => {
      goStage(scene.stage);
      setCameraPreset(scene.camera);
      const id = graph ? scene.focusNodeId(graph) : null;
      setSelectedId(id);
      setFocusNodeId(id);
      setHoveredId(null);
    },
    [graph, goStage],
  );

  /** 발표·튜토리얼을 마치면 「가장 먼저 처리할 단계」로 — 8 이면 지도가 ⑧ 결정만 밝힌다 (21차). */
  const exitScene = useCallback(() => {
    goStage(graph ? landingStageOf(graph) : 8);
    setSelectedId(null);
    setHoveredId(null);
    setFocusNodeId(null);
    setCameraPreset("overview");
    setResetSignal((n) => n + 1);
  }, [graph, goStage]);

  // 발표가 끝나면 기본 화면(단계 목록)으로 — 발표가 연 지도(「auto」)만 되돌린다 (28차 §3-F).
  const onPresentationExit = useCallback(() => {
    exitScene();
    setViewMode((current) => (current === "auto" ? null : current));
  }, [exitScene]);
  const presentation = usePresentation({
    scenes: PRESENTATION_SCENES,
    graph,
    onScene: applyScene,
    onExit: onPresentationExit,
  });

  // ---------------------------------------------------------------------------
  // 튜토리얼(15단계)·Quick Tour(3단계) — 발표 모드와 서로 배타적이다 (하나를 켜면 다른 것은 꺼진다)
  // ---------------------------------------------------------------------------

  /** 발표 시작 함수는 튜토리얼 훅보다 뒤에 정의되므로 ref로 넘긴다 (effect에서 동기화). */
  const beginPresentationRef = useRef<() => void>(() => {});

  const tutorialActions = useMemo<TutorialActions>(
    () => ({
      setStage: goStage,
      setCameraPreset,
      selectNode,
      // 안내가 「3D」로 돌려놓는 것은 사람이 고른 것이 아니다 — 지도 기본값으로(좁은 캔버스면 2D) (22차 §4-C).
      setViewMode: (mode: CosmosViewMode) => setViewMode(mode === "3d" ? "auto" : mode),
      resetView,
      startPresentation: () => beginPresentationRef.current(),
      openDetail: () => setDrawerOpen(true),
    }),
    [goStage, selectNode, resetView],
  );

  const tutorialState = useMemo<TutorialState>(
    () => ({
      stage,
      selectedId,
      viewMode,
      // 사람이 고른 보기 — 좁은 캔버스는 기본이 2D 라 「2D 를 눌러 보세요」가 누르기 전에 끝나 있었다 (22차 검토).
      viewPicked: viewOverride === "auto" ? null : viewOverride,
      reviewDecision: dashboard.reviewDecision,
      presentationActive: presentation.active,
    }),
    [stage, selectedId, viewMode, viewOverride, dashboard.reviewDecision, presentation.active],
  );

  /** 튜토리얼·Quick Tour 시작 직전: 발표 모드를 끄고 Guided 단계를 잠시 내린다 (안내가 장면을 정한다). */
  const onGuideStart = useCallback(() => {
    if (presentation.active) presentation.exit();
    setGuidedOverride(null);
    setGuidedByUser(false);
  }, [presentation]);

  const onTutorialExit = useCallback(() => {
    exitScene();
    // 안내가 끝나면 기본 화면(단계 목록)으로 돌아간다 — 안내가 연 지도(「auto」)만 되돌린다(사람이 고른 3D · 2D 는 둔다 · 28차 §3-F).
    setViewMode((current) => (current === "auto" ? null : current));
  }, [exitScene]);

  const tutorial = useTutorial({
    steps: TUTORIAL_STEPS,
    graph,
    state: tutorialState,
    actions: tutorialActions,
    onStart: onGuideStart,
    onExit: onTutorialExit,
  });

  /** Quick Tour가 끝나면 Guided 1단계로 들어간다 (공고 노드 강조 + 「다음: 과업과 필수조건 보기」). */
  const onQuickTourExit = useCallback(() => {
    setViewMode((current) => (current === "auto" ? null : current)); // 기본 화면(단계 목록)으로 (28차 §3-F)
    setResetSignal((n) => n + 1);
    applyGuided(1);
    // 30초 안내가 이어 켜는 5단계 안내는 사람이 켠 것이 아니다 — 쉬운 보기에서 출발했으면 쉬운 보기로 돌아간다.
    setGuidedByUser(false);
  }, [applyGuided]);

  const quickTour = useTutorial({
    steps: QUICK_TOUR_STEPS,
    storageKey: QUICK_TOUR_STORAGE_KEY,
    graph,
    state: tutorialState,
    actions: tutorialActions,
    onStart: onGuideStart,
    onExit: onQuickTourExit,
  });

  /**
   * 「쉬운 보기 ⇄ 전체 보기」 (24차 §3-1). 저장된 값이 쉬운 보기여도 **사람이 직접 시작한 안내**(발표 · 상세 튜토리얼 ·
   * 30초 안내 · 5단계 안내) 동안은 전체 보기로 그린다 — 안내가 비추는 것이 전체 보기의 요소이기 때문이다. 저장값은
   * 그대로라 안내가 끝나면 시작 전 모드로 돌아간다. 쉬운 보기에서는 저장된 Guided 단계를 무시한다(기록은 그대로).
   */
  const storedDisplayMode = useDisplayMode();
  const guideForcesFull =
    presentation.active || tutorial.active || quickTour.active || (guidedByUser && rawGuidedStep !== null);
  const displayMode: DisplayMode = storedDisplayMode === "simple" && guideForcesFull ? "full" : storedDisplayMode;
  const simpleView = displayMode === "simple";
  const guidedStep: GuidedStep | null = simpleView ? null : rawGuidedStep;

  /**
   * 「?」 안내가 이동(레일 · KPI · 상세 패널 · 안내 마지막 「다음」)으로 끝나면 쉬운 보기로 돌아가면서 그 단계를 펼친다
   * (26차 ISSUE-154). `seq` 는 SimpleDashboard 를 새로 그리는 열쇠다. 토글 · 안내를 명시적으로 닫으면 비운다 — 맨 위.
   */
  const [simpleLanding, setSimpleLanding] = useState<{ stage: WorkflowStage; nodeId: string | null } | null>(null);
  // 쉬운 보기를 새로 그리는 열쇠 — 복귀 단계가 생길 때만 바뀐다(복귀 단계를 비워도 다시 그리지 않는다).
  const [simpleMountKey, setSimpleMountKey] = useState(0);

  /** 토글. 안내가 켜진 동안에는 막는다(TopBar) — 켜진 채 쉬운 보기로 가면 안내가 비출 요소가 없다. */
  const changeDisplayMode = useCallback((mode: DisplayMode) => {
    // 안내 중 「전체 보기」를 누르면 안내를 끝내고 전체 보기로 고정한다 — 눌린 듯 보이고 아무 일도 없던 것(EZ-36).
    setGuidedByUser(false);
    setSimpleLanding(null);
    setDisplayMode(mode);
  }, []);

  const beginPresentation = useCallback(() => {
    if (tutorial.active) tutorial.exit();
    if (quickTour.active) quickTour.exit();
    if (viewMode === "list") setViewMode("auto");
    setDrawerOpen(false);
    setGuidedOverride(null);
    setGuidedByUser(false);
    presentation.start();
  }, [presentation, tutorial, quickTour, viewMode]);

  useEffect(() => {
    beginPresentationRef.current = beginPresentation;
  }, [beginPresentation]);

  const togglePresentation = useCallback(() => {
    if (presentation.active) {
      presentation.exit();
      return;
    }
    beginPresentation();
  }, [beginPresentation, presentation]);

  const startTutorial = useCallback(() => {
    if (quickTour.active) quickTour.exit();
    if (viewMode === "list") setViewMode("auto");
    tutorial.start(0);
  }, [tutorial, quickTour, viewMode]);

  const toggleTutorial = useCallback(() => {
    if (tutorial.active) {
      tutorial.exit();
      return;
    }
    startTutorial();
  }, [startTutorial, tutorial]);

  const startQuickTour = useCallback(() => {
    if (tutorial.active) tutorial.exit();
    if (viewMode === "list") setViewMode("auto");
    quickTour.start(0);
  }, [tutorial, quickTour, viewMode]);

  const welcome = useSeenRecord(WELCOME_STORAGE_KEY);
  const markAllSeen = useCallback(() => {
    welcome.markSeen();
    tutorial.markSeen();
    quickTour.markSeen();
    writeGuidedRecord({ seen: true });
  }, [welcome, tutorial, quickTour]);

  /**
   * 「시작하기」 · Esc · 바깥 누름 · 가이드로 가기: 창만 닫는다 — 보던 화면은 그대로(5단계 안내를 켜지 않는다 · 사용 설명서 A-0).
   * 이번 방문 동안은 기억도 따로 둔다 — 저장소 쓰기가 막힌 브라우저에서 창이 닫히지 않아 화면이 막혔다.
   */
  const [welcomeClosed, setWelcomeClosed] = useState(false);
  const closeWelcome = useCallback(() => {
    setWelcomeClosed(true);
    markAllSeen();
  }, [markAllSeen]);

  // 환영 창은 첫 진입이면 어느 공고 · 어느 보기 · 어느 상태(불러오는 중 · 지원사업 · 오류)에서든 띄운다(2.0.5) —
  // 예전엔 가상 예시 공고일 때만이라 실제 1위로 열리는 지금은 한 번도 뜨지 않았다. 안내 · 발표가 도는 중에는 겹치지 않는다.
  const showWelcome =
    welcome.firstVisit &&
    !welcomeClosed &&
    urlOptions.welcome &&
    !presentation.active &&
    !tutorial.active &&
    !quickTour.active;
  const welcomeDialog = showWelcome ? <WelcomeDialog onStart={closeWelcome} onLeave={closeWelcome} /> : null;

  /** 단계·노드로 이동 — 레일·KPI 카드·상세 패널의 "다음 행동"이 같은 경로를 쓴다. 워크플로 이동은 Guided 안내를 끝낸다. */
  const navigateTo = useCallback(
    (nextStage: WorkflowStage, nodeId: string | null) => {
      goStage(nextStage);
      setCameraPreset(RAIL_CAMERA[nextStage]);
      const target = nodeId && graph?.nodeById.has(nodeId) ? nodeId : RAIL_SELECT[nextStage];
      setSelectedId(target);
      setFocusNodeId(nodeId && graph?.nodeById.has(nodeId) ? nodeId : null);
      setHoveredId(null);
      setGuidedOverride(null);
      setGuidedByUser(false);
      writeGuidedRecord({ step: null });
      if (target) setDrawerOpen(true);
      // 「?」 안내(사람이 켠 5단계 안내)가 쉬운 보기에서 전체 보기로 넘겨 그리던 중이면, 돌아가서 이 단계를 펼친다.
      // 발표 · 튜토리얼 · 30초 안내는 여기에 들지 않는다(26차 검수 FE-1).
      if (storedDisplayMode === "simple" && guidedByUser && rawGuidedStep !== null) {
        setSimpleLanding({ stage: nextStage, nodeId });
        setSimpleMountKey((key) => key + 1);
      }
    },
    [graph, goStage, storedDisplayMode, guidedByUser, rawGuidedStep],
  );

  const onStepClick = useCallback(
    (step: WorkflowStepView) => navigateTo(step.id, null),
    [navigateTo],
  );

  /**
   * 쉬운 보기 맨 위 줄(「오늘 · 이번 주 할 일」)의 「n단계로 이동」 · 위험 줄 단추 — **쉬운 보기에서 그 단계를 펼친다**(37차 recheck29 UI-R36-01).
   * `navigateTo` 는 가려진 전체 보기 상태만 바꿔 눌러도 화면이 그대로였다. 「?」 안내가 끝날 때와 같은 길(`simpleLanding` + 다시 그리기)을 쓴다.
   */
  const simpleNavigate = useCallback((nextStage: WorkflowStage, nodeId: string | null) => {
    setSimpleLanding({ stage: nextStage, nodeId });
    setSimpleMountKey((key) => key + 1);
  }, []);

  /** Guided 다음 단계. 5단계 다음은 사람의 결정(8단계 개요 · Human Review · GO/HOLD/NO-GO). */
  const guidedNext = useCallback(() => {
    if (guidedStep === null) {
      applyGuided(1);
      return;
    }
    if (guidedStep < 5) {
      applyGuided((guidedStep + 1) as GuidedStep);
      return;
    }
    navigateTo(8, null);
  }, [applyGuided, guidedStep, navigateTo]);

  const guidedStart = useCallback(() => {
    applyGuided(1);
    setGuidedByUser(true);
  }, [applyGuided]);
  const guidedExit = useCallback(() => {
    setSimpleLanding(null); // 명시적으로 닫았다 — 쉬운 보기는 맨 위
    applyGuided(null);
  }, [applyGuided]);

  /**
   * 공고를 바꾸면 선택·카메라·발표/튜토리얼 상태를 초기화하고 새 공고를 불러온다 (Guided 단계는 유지).
   *
   * 예전에는 아무 말 없이 바꿨다. 그런데 이 화면에는 **저장되지 않는 것**이 둘 있다 —
   * 아직 저장 전인 검토 승인/보류, 그리고 Auditor 초안 입력칸이다. 담당자가 판단을
   * 적어 두고 다른 공고를 잠깐 열면 그대로 사라졌다. 잃을 것이 있을 때만 물어본다
   * (이미 서버에 저장된 검토는 돌아오면 복원되므로 묻지 않는다).
   */
  const selectNotice = useCallback(
    (id: string) => {
      // 검토 승인 미저장과 작성 중인 글(검사할 초안 · 사유 · 메모 — 어느 패널인지는 여기서 모른다 · ISSUE-010)을 **한 창**에 묻는다.
      // 따로 물으면 둘이 함께일 때 창이 두 번 연달아 떴다(2.0.6 통합 검토).
      if (dashboard.review.unsaved) {
        const losing = ["아직 저장하지 않은 검토 승인/보류", hasUnsaved() ? "작성 중인 내용" : null].filter(
          (item): item is string => item !== null,
        );
        if (!confirmDiscard(true, `공고를 바꾸면 다음이 사라집니다 — ${losing.join(" · ")}. 계속할까요?`)) return;
        forgetUnsaved();
      } else if (!confirmUnsaved("작성 중인 내용")) {
        return;
      }

      if (presentation.active) presentation.exit();
      if (tutorial.active) tutorial.exit();
      if (quickTour.active) quickTour.exit();
      setSelectedId(null);
      setHoveredId(null);
      setFocusNodeId(null);
      setCameraPreset("overview");
      setDrawerOpen(false);
      setResetSignal((n) => n + 1);
      // 펼친 요구사항 묶음은 이 공고의 것이다 — 새 공고로 넘겨 가지 않는다 (DSH-20).
      dashboard.toggleCategory(null);
      dashboard.selectNotice(id);
    },
    [confirmDiscard, dashboard, presentation, tutorial, quickTour],
  );

  const runAnalysis = useCallback(() => {
    setSelectedId(null);
    setHoveredId(null);
    setFocusNodeId(null);
    setCameraPreset("overview");
    setResetSignal((n) => n + 1);
    dashboard.runAnalysis();
  }, [dashboard]);

  /**
   * 검토 승인/보류.
   *
   * 예전에는 여기서 화면 state 만 바꿨다 — 저장되는 곳이 없어서 공고를 바꾸면 사라졌다.
   * 이제 담당자·확인 항목을 받아 `/api/review` 에 남긴다. 되돌릴 때(null)도 서버에서
   * 되돌린다. 저장에 실패하면 대화상자가 닫히지 않고 사유를 그대로 보여준다.
   */
  const [reviewDraft, setReviewDraft] = useState<"approved" | "hold" | null>(null);
  const onReviewDecision = useCallback(
    (decision: ReviewDecision) => {
      if (decision === null) {
        dashboard.review.clear();
        return;
      }
      setReviewDraft(decision);
    },
    [dashboard.review],
  );

  const guideActive = presentation.active || tutorial.active || quickTour.active;

  // Focus Mode: 선택(또는 hover) 노드 주변 핵심 관계만 순차 강조. 허브는 상위 7개로 제한.
  const focus = useMemo(() => {
    if (!graph) return EMPTY_FOCUS;
    const active = hoveredId ?? selectedId;
    if (active) return focusIds(graph, active);
    // 발표·튜토리얼 중에는 장면이 선택을 정하므로 기본 경로를 끼워 넣지 않는다.
    if (guideActive) return EMPTY_FOCUS;
    if (guidedStep !== null) return guidedFocus(graph, guidedStep);
    // 아무것도 고르지 않았을 때의 「핵심 흐름」 흐림은 없앴다 (21차) — 밝기는 정거장 단계(지금 · 옆 · 나머지)가 맡는다.
    return EMPTY_FOCUS;
  }, [graph, hoveredId, selectedId, guideActive, guidedStep]);
  /**
   * 지도 선의 기준 항목 (27차 §3-D-3) — 고른 항목. 없으면 5단계 안내가 가리키는 **지금 정거장** 항목(안내 강조선은 그대로
   * 둔다). hover 로는 긋지 않는다. 아무것도 고르지 않았고 안내도 없으면 선 0.
   */
  const lineAnchorId = useMemo(() => {
    if (!graph) return null;
    if (selectedId) return selectedId;
    if (guideActive || guidedStep === null) return null;
    // 오른쪽 패널이 설명하는 대표 항목부터 — 선이 다른 항목(수행기간)에서 나가면 패널(검수기준)과 어긋났다(27차 검수 R27D-OWN-04).
    const explained = guidedStepDef(guidedStep).focusNodeId(graph);
    if (explained && graph.nodeById.get(explained)?.stage === mapStage) return explained;
    for (const id of guidedFocus(graph, guidedStep).nodeIds) {
      if (graph.nodeById.get(id)?.stage === mapStage) return id;
    }
    return null;
  }, [graph, selectedId, guideActive, guidedStep, mapStage]);

  // Esc: 선택 해제 → 전체 보기 (발표·튜토리얼·환영 대화상자·상세 범례가 자기 Esc를 쓰는 동안은 양보한다)
  useEffect(() => {
    if (guideActive || showWelcome || legendOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || isEditableTarget(event.target)) return;
      if (!selectedId && !drawerOpen) return;
      // 「?」 대화상자처럼 제 Esc 를 쓰는 창이 떠 있으면 양보한다 (DSH-03).
      if (document.querySelector('[aria-modal="true"]')) return;
      event.preventDefault();
      setSelectedId(null);
      setFocusNodeId(null);
      setHoveredId(null);
      if (compact) setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [guideActive, showWelcome, legendOpen, selectedId, drawerOpen, compact]);

  /**
   * 화살표 키로 노드를 옮겨 다닌다.
   *
   * 3D 화면은 마우스로 집는 것이 기본이라 키보드만 쓰는 사람은 아무것도 고를 수 없었다.
   * 3D 없이도 모든 업무를 할 수 있어야 하고(목록·2D 가 있다), 3D 안에서도 최소한
   * 「다음/이전 항목」은 키보드로 움직일 수 있어야 한다.
   *
   * ← → : 이전/다음 노드   Home : 첫 노드
   * 입력 칸에 포커스가 있으면 양보한다.
   */
  useEffect(() => {
    if (!graph || guideActive || showWelcome || legendOpen || simpleView) return;
    const nodes = graph.nodes;
    if (nodes.length === 0) return;

    const onArrow = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      // 대화상자 · 메뉴가 떠 있거나 탭 줄처럼 제 화살표를 쓰는 곳이면 양보한다 (DSH-03).
      if (document.querySelector('[aria-modal="true"], [role="menu"]')) return;
      const from = event.target instanceof Element ? event.target : null;
      if (from?.closest('[role="dialog"], [role="tablist"], [role="radiogroup"], [role="listbox"]')) return;
      // ↑↓ · Home 은 페이지 스크롤 키다 — 지도 안에 초점이 있을 때만 항목 이동으로 쓴다.
      const inMap = Boolean(from?.closest('section[data-tour="stage"]'));
      const isNext = event.key === "ArrowRight" || (inMap && event.key === "ArrowDown");
      const isPrev = event.key === "ArrowLeft" || (inMap && event.key === "ArrowUp");
      const isHome = inMap && event.key === "Home";
      if (!isNext && !isPrev && !isHome) return;

      event.preventDefault();
      const current = nodes.findIndex((n) => n.id === selectedId);
      const next = isHome
        ? 0
        : current < 0
          ? 0
          : (current + (isNext ? 1 : -1) + nodes.length) % nodes.length;
      const target = nodes[next];
      setSelectedId(target.id);
      setFocusNodeId(target.id);
      // 고른 노드의 정거장으로 — 지도는 지금 정거장에만 라벨을 붙이고 카메라도 정거장을 따라간다 (21차).
      followStage(target.stage);
      if (compact) setDrawerOpen(true);
    };
    window.addEventListener("keydown", onArrow);
    return () => window.removeEventListener("keydown", onArrow);
  }, [graph, guideActive, showWelcome, legendOpen, selectedId, compact, followStage, simpleView]);

  const runningStages = useMemo(() => {
    const set = new Set<WorkflowStage>();
    for (const phase of Object.values(dashboard.runLog)) {
      if (phase.status !== "running") continue;
      const mapped = PHASE_STAGE[phase.key];
      if (mapped) set.add(mapped);
    }
    return set;
  }, [dashboard.runLog]);

  const paused = !documentVisible || (presentation.active && !presentation.playing);
  const busy = dashboard.analyzing || dashboard.analysisLoading;

  if (dashboard.status === "loading") {
    return (
      <Frame loading>
        <TopBar
        displayMode={displayMode}
        onDisplayModeChange={changeDisplayMode}
        displayToggleLocked={guideActive}
          graph={null}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          onResetView={resetView}
          onAnalyze={runAnalysis}
          analyzing={dashboard.analyzing}
          presentationActive={false}
          onTogglePresentation={togglePresentation}
          tutorialActive={false}
          onToggleTutorial={toggleTutorial}
          webglSupported={webglSupported}
          notices={dashboard.notices}
          selectedNoticeId={dashboard.selectedNoticeId}
          onSelectNotice={selectNotice}
          noticeList={dashboard.noticeList}
          supportError={dashboard.supportError}
          supportView={isSupportProgramId(dashboard.selectedNoticeId)}
          organizations={organizations.list}
          organizationId={organizationId}
        />
        {simpleView ? (
          // 쉬운 보기는 한 열이다 — 전체 보기의 3열 뼈대 · 바닥 출처줄을 그리지 않는다 (EZ-07)
          <p role="status" className="px-4 py-10 text-center text-[15px] text-cosmos-secondary">
            공고를 불러오는 중입니다
          </p>
        ) : (
          <>
            <LoadingView
              reducedMotion={reducedMotion}
              kind={isSupportProgramId(dashboard.selectedNoticeId) ? "support" : "notice"}
            />
            <BottomStrip graph={null} />
          </>
        )}
        {welcomeDialog}
      </Frame>
    );
  }

  /**
   * 기업마당 지원사업을 고른 경우.
   *
   * **입찰 8단계를 그리지 않는다.** 지원사업에는 요구사항도 제안서도 제출 전 누락 점검도 없어서
   * 그대로 그리면 전 단계가 「미실행」인 빈 화면이 된다 — 그건 고장이지 기능이 아니다.
   * 대신 같은 셸(상단 공고 선택기 · 회사 선택기) 안에서 신청 7단계와 전용 3D 를 그린다.
   *
   * 이 분기가 `!graph` 검사보다 **먼저** 와야 한다 — 지원사업일 때 graph 는 null 이다.
   */
  if (dashboard.supportResult) {
    return (
      <Frame>
        <TopBar
        displayMode={displayMode}
        onDisplayModeChange={changeDisplayMode}
        displayToggleLocked={guideActive}
          graph={null}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          onResetView={resetView}
          onAnalyze={dashboard.reload}
          analyzing={dashboard.analyzing}
          presentationActive={false}
          onTogglePresentation={togglePresentation}
          tutorialActive={false}
          onToggleTutorial={toggleTutorial}
          webglSupported={webglSupported}
          notices={dashboard.notices}
          selectedNoticeId={dashboard.selectedNoticeId}
          onSelectNotice={selectNotice}
          noticeList={dashboard.noticeList}
          supportError={dashboard.supportError}
          organizations={organizations.list}
          organizationId={organizationId}
          organizationLoseMessage={organizationLoseMessage}
          context={dashboard.context}
          supportView
        />
        {simpleView ? (
          <div className="px-4">
            <SupportSimpleView
              result={dashboard.supportResult}
              organizationLabel={
                organizations.list?.organizations.find((o) => o.organization.organization_id === organizationId)
                  ?.organization.display_name ?? "현재 회사"
              }
              footer={<SupportPageLink programId={dashboard.supportResult.program_id} />}
            />
          </div>
        ) : (
          <SupportDashboardBody
            result={dashboard.supportResult}
            organizationLabel={
              organizations.list?.organizations.find((o) => o.organization.organization_id === organizationId)
                ?.organization.display_name ?? "현재 회사"
            }
            reducedMotion={reducedMotion}
            webglSupported={webglSupported}
          />
        )}
        {welcomeDialog}
      </Frame>
    );
  }

  if (dashboard.status === "error" || !graph) {
    return (
      <Frame>
        <TopBar
        displayMode={displayMode}
        onDisplayModeChange={changeDisplayMode}
        displayToggleLocked={guideActive}
          graph={null}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          onResetView={resetView}
          onAnalyze={runAnalysis}
          analyzing={dashboard.analyzing}
          presentationActive={false}
          onTogglePresentation={togglePresentation}
          tutorialActive={false}
          onToggleTutorial={toggleTutorial}
          webglSupported={webglSupported}
          notices={dashboard.notices}
          selectedNoticeId={dashboard.selectedNoticeId}
          onSelectNotice={selectNotice}
          noticeList={dashboard.noticeList}
          supportError={dashboard.supportError}
          supportView={isSupportProgramId(dashboard.selectedNoticeId)}
          organizations={organizations.list}
          organizationId={organizationId}
        />
        <ErrorView
          message={dashboard.error ?? "알 수 없는 오류가 발생했습니다."}
          onRetry={dashboard.reload}
        />
        {!simpleView && <BottomStrip graph={null} />}
        {welcomeDialog}
      </Frame>
    );
  }

  /*
   * 고정 모드에서 첨부 캐시가 없는 실공고는 「공고 분석 시작」이 늘 실패한다 (DSH-12). 막다른 문장으로 두지 않고
   * 사람이 파일 이름을 보고 한 건만 받는 길(요구사항 정리표 확인 창)을 옆에 둔다.
   */
  const attachmentHint = dashboard.analysisError?.includes("저장해 둔 첨부만") ? (
    <>
      {" "}
      <Link href={requirementSheetHref(dashboard.selectedNoticeId)} className="mc-focus underline underline-offset-2">
        {SCREEN_NAMES.rfp}에서 제안요청서 1건 받기 →
      </Link>
    </>
  ) : null;
  // 요구사항 0건: 합성 데모 공고는 기존처럼 「공고 분석 시작」 안내 카드, 실공고는 공고 노드만 그리고 미실행 배너를 띄운다.
  const noRequirements = dashboard.status === "empty";
  const empty = noRequirements && graph.hasScenario;
  const realNoticeNotParsed = noRequirements && !graph.hasScenario;
  const stageOverlays = !presentation.active && !empty;
  const graphOverlays = stageOverlays && viewMode !== "list";
  const guidedDef = guidedStep ? guidedStepDef(guidedStep) : null;
  // 알림 영역도 상세와 같은 노드를 읽는다 — 묶음에 접힌 항목을 「n단계 개요」로 읽지 않게 (R27U-LNK-R8)
  const selectedNode = detailNodeOf(graph, selectedId);
  const liveMessage = selectedNode
    ? `선택: ${selectedNode.label}`
    : guidedDef
      ? `안내 ${guidedDef.id}/5 · ${guidedDef.title}. ${guidedDef.caption}`
      : `${stage}단계 개요`;

  return (
    <Frame loading={dashboard.analysisLoading}>
      <TopBar
        displayMode={displayMode}
        onDisplayModeChange={changeDisplayMode}
        displayToggleLocked={guideActive}
        graph={graph}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        onResetView={resetView}
        onAnalyze={runAnalysis}
        analyzing={dashboard.analyzing}
        presentationActive={presentation.active}
        onTogglePresentation={togglePresentation}
        tutorialActive={tutorial.active}
        onToggleTutorial={toggleTutorial}
        onStartQuickTour={startQuickTour}
        onStartGuidedFlow={guidedStart}
        supportError={dashboard.supportError}
        webglSupported={webglSupported}
        notices={dashboard.notices}
        selectedNoticeId={dashboard.selectedNoticeId}
        onSelectNotice={selectNotice}
        noticeList={dashboard.noticeList}
        organizations={organizations.list}
        organizationId={organizationId}
        organizationLoseMessage={organizationLoseMessage}
        context={dashboard.context}
      />

      {simpleView ? (
        <>
          <p className="sr-only" aria-live="polite">
            {liveMessage}
          </p>
          {/* 매일 순서 1 · 2단계(목록 받은 때 · 이번 주 할 일)가 처음 화면에 없었다(recheck28 DOC-01 · 담당자 결정 10-13).
              전체 보기의 접힌 띠 그대로 — 같은 응답 · 같은 펼침 기억 · 쉬운 보기 한 열 폭에 맞춘다. 발표 모드에서는 비운다. */}
          {!presentation.active && (
            <div data-simple-day-strip className="mx-auto w-full max-w-[992px] [&>section]:px-4">
              <DayStrip organizationId={organizationId} onNoticesChanged={onKeywordNotices}>
                <ThisWeekPanel organizationId={organizationId} reloadKey={weekTick} />
                <TodayPanel
                  graph={graph}
                  nowMs={nowMs}
                  onNavigate={simpleNavigate}
                  opportunitiesHref="/opportunities"
                  onGenerateProposal={dashboard.actions.generateProposal}
                  generating={dashboard.actions.proposalBusy}
                  onAnalyze={runAnalysis}
                  analyzing={dashboard.analyzing}
                />
              </DayStrip>
            </div>
          )}
          <SimpleDashboard
            key={simpleMountKey}
            returnTo={simpleLanding}
            onReturnConsumed={() => setSimpleLanding(null)}
            graph={graph}
            actions={dashboard.actions}
            runLog={dashboard.runLog}
            analyzing={dashboard.analyzing}
            analyzeLocked={presentation.active}
            onAnalyze={runAnalysis}
            reviewDecision={dashboard.reviewDecision}
            onReviewDecision={onReviewDecision}
            reducedMotion={reducedMotion}
            reviewStatus={<ReviewStatusBar review={dashboard.review} onSave={() => onReviewDecision(dashboard.reviewDecision)} />}
            context={dashboard.context}
            organizationName={organizationName}
            alerts={
              <>
                {dashboard.staleNotice && (
                  <p role="status" className="text-[14px] leading-6 text-cosmos-amber">
                    {dashboard.staleNotice}{" "}
                    <Link href="/opportunities" className="mc-focus underline underline-offset-2">
                      {SCREEN_NAMES.opportunities} 목록에서 찾기 →
                    </Link>
                  </p>
                )}
                {dashboard.analysisError && (
                  <p role="alert" className="text-[14px] leading-6 text-cosmos-amber">
                    {dashboard.analysisError} 화면에는 마지막으로 성공한 분석 결과가 표시됩니다.
                    {attachmentHint}
                  </p>
                )}
              </>
            }
          />
        </>
      ) : (
      <>
      {/*
        지금 보는 것이 데모라는 사실을 화면 상단에 상시 표시한다 (ISSUE-017).

        첫 화면은 합성 데모 공고에 샘플에듀가 결합된 8단계 결과다 — 「우리 회사 적합도 82점」이
        먼저 보인다. 그 82점은 합성 시나리오 고정값인데, 처음 온 사람은 「우리 회사 점수」로
        읽는다. 패널 안의 작은 배지로는 그 오해를 막지 못했다.
      */}
      {graph?.source.origin.kind === "demo" && !presentation.active && (
        <div className="px-3 pt-3 sm:px-5">
          <p
            role="note"
            // 합성 표시 = 회청 점선 + ◇ (Badge tone demo 와 같은 모양 · 보라는 기업마당 한 뜻 · 27차 §3-E UNI-19)
            className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-dashed border-cosmos-slate/70 bg-cosmos-slate/10 px-3 py-2 text-[12.5px] leading-5 text-cosmos-text"
          >
            <span className="font-semibold">
              <span aria-hidden="true" className="mr-1 text-cosmos-slate">◇</span>
              {SYNTHETIC_NOTICE}입니다
            </span>
            <span className="text-cosmos-secondary">
              {/* 쉬운 보기 · 환영 창과 같은 사실 — 데모에서 저장한 것은 공용 파일에 남는다(analysis_store.guard_public_demo_write · EZ-05) */}
              <span title="여기서 저장한 결정은 다른 사용자에게도 보입니다(기본 회사로 볼 때만 저장)">공고·회사자료·점수 모두 시연용 가상 자료입니다.</span>
            </span>
            <Link href="/opportunities" className="mc-focus underline underline-offset-2">
              내 공고로 시작 →
            </Link>
          </p>
        </div>
      )}

      {/*
        요청한 공고가 목록에 없어 데모로 돌아왔다 (ISSUE-020).

        예전에는 아무 말 없이 합성 데모 화면이 떴다. 공유받은 링크가 오래됐을 때
        담당자는 «자기 공고»를 보고 있다고 믿는다 — 사유가 title 툴팁에만 있었다.
      */}
      {dashboard.staleNotice && !presentation.active && (
        <div className="px-3 pt-3 sm:px-5">
          <p
            role="status"
            className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-cosmos-amber/50 bg-cosmos-amber/10 px-3 py-2 text-[12.5px] leading-5 text-cosmos-amber"
          >
            <span>{dashboard.staleNotice}</span>
            <Link href="/opportunities" className="mc-focus underline underline-offset-2">
              {SCREEN_NAMES.opportunities} 목록에서 찾기 →
            </Link>
          </p>
        </div>
      )}

      {/* 「오늘 달라진 것」·「이번 주 할 일」·「지금 할 일」은 조직 단위 정보라 **접힌 띠 하나**로 KPI 위에 둔다
          (21차 · prompt_11 §3-7) — 첫 화면에 지도가 있어야 한다. 펼치면 세 패널이 예전 순서 그대로 나온다.
          발표 모드에서는 함께 비운다. */}
      {!presentation.active && (
        <DayStrip organizationId={organizationId} onNoticesChanged={onKeywordNotices}>
          <ThisWeekPanel organizationId={organizationId} reloadKey={weekTick} />
          <TodayPanel
            graph={graph}
            nowMs={nowMs}
            onNavigate={navigateTo}
            opportunitiesHref="/opportunities"
            onGenerateProposal={dashboard.actions.generateProposal}
            generating={dashboard.actions.proposalBusy}
            onAnalyze={presentation.active ? undefined : runAnalysis}
            analyzing={dashboard.analyzing}
          />
        </DayStrip>
      )}

      {!presentation.active && (
        <MissionStrip
          graph={graph}
          stage={panelStage}
          onNavigate={navigateTo}
          reviewPriority={dashboard.selectedReviewPriority}
        />
      )}

      {dashboard.analysisError && (
        <p
          role="alert"
          className="mx-3 mt-3 rounded-lg border border-cosmos-amber/40 bg-cosmos-amber/10 px-4 py-2 text-[12px] text-cosmos-amber"
        >
          {dashboard.analysisError} 화면에는 마지막으로 성공한 분석 결과가 표시됩니다.
          {attachmentHint}
        </p>
      )}

      <p className="sr-only" aria-live="polite">
        {liveMessage}
      </p>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-3 lg:flex-row">
        {!presentation.active && (
          <WorkflowRail
            steps={graph.steps}
            stage={panelStage}
            onStepClick={onStepClick}
            reducedMotion={reducedMotion}
            runningStages={runningStages}
            collapsed={railCollapsed}
            onToggleCollapsed={() => setRailCollapsed((v) => !v)}
          />
        )}

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
          {/* 3D 는 이 화면의 주인공이다. 남은 공간을 받되 **바닥을 정해 둔다** —
              위 패널이 길어져도 이 아래로는 눌리지 않고, 대신 페이지가 스크롤된다. */}
          <section
            aria-label="Evidence Cosmos"
            data-tour="stage"
            // 목록(기본 · 28차)은 지도 칸과 같은 높이 안에서만 스크롤한다 — 높이를 묶지 않으면 페이지가 4,000px 넘게 늘어났다.
            className={`relative min-h-[440px] min-w-0 overflow-hidden rounded-xl border border-cosmos-border bg-cosmos-deep/40 lg:min-h-[560px] ${viewMode === "list" ? "h-[440px] flex-none lg:h-[560px]" : "flex-1"}`}
          >
            <CosmosStage
              graph={graph}
              stage={mapStage}
              selectedId={selectedId}
              hoveredId={hoveredId}
              onSelect={selectNode}
              onHover={setHoveredId}
              highlightNodeIds={focus.nodeIds}
              highlightLinkIds={focus.linkIds}
              highlightOrder={focus.linkOrder}
              cameraPreset={cameraPreset}
              focusNodeId={focusNodeId}
              resetSignal={resetSignal}
              reducedMotion={reducedMotion}
              paused={paused}
              viewMode={viewMode}
              webglSupported={webglSupported}
              empty={empty}
              analyzing={dashboard.analyzing}
              onAnalyze={runAnalysis}
              // 지금이 아닌 정거장 이름 알약을 누르면 레일과 **같은 이동**(선택 · 카메라 · 상세 서랍) — 27차 §3-D-2
              onStation={(id) => navigateTo(id, null)}
              onShowAll={() => setViewMode("list")}
              lineAnchorId={lineAnchorId}
            />

            {/* 3D 무대 로딩 표시 (ISSUE-011).

                공고를 바꾸면 무대가 완전히 비어 있다가 값이 늦게 들어온다(관찰: 5초 시점
                빈 화면, 8초 시점 렌더). 빈 화면은 「결과가 없다」로 읽힌다 — 지금 불러오는
                중이라고 말해 준다. 클릭은 막지 않는다(pointer-events-none). */}
            {dashboard.analysisLoading && !presentation.active && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-cosmos-deep/45">
                <span className="rounded-full border border-cosmos-border-strong bg-cosmos-panel/90 px-4 py-2 text-[13px] text-cosmos-secondary shadow-lg">
                  결과를 불러오는 중입니다…
                </span>
              </div>
            )}

            {presentation.active && (
              <PresentationOverlay controller={presentation} graph={graph} reducedMotion={reducedMotion} />
            )}

            {/* 지도 위에 겹치는 것은 **선택 노드 카드 하나뿐** (21차 · prompt_11 §3-5). 정거장 이름이 위에 있으므로
                아래 왼쪽에 둔다. 안내·범례·구조·「전체 보기」는 지도 아래 도구막대로 내렸다. */}
            {/* 안내가 긋는 선도 무엇에서 나가는지 카드로 말한다(검수 R27D-OWN-04) — 고른 항목이 없으면 선의 기준 항목 */}
            {stageOverlays && !busy && (selectedId ?? lineAnchorId) && viewMode !== "list" && graph.nodeById.get((selectedId ?? lineAnchorId) as string)?.stage === mapStage && (
              // 2D 는 정거장 머리가 맨 위라 설명은 아래(3D 는 10-31 대표 결정으로 화면에서 뺐다).
              <div className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-[calc(100%-1.5rem)]">
                <FocusChip graph={graph} selectedId={selectedId ?? lineAnchorId} stage={mapStage} />
              </div>
            )}
          </section>

          {/* 지도 아래 한 줄 도구막대 — 분석 중이면 실행 타임라인, 아니면 안내 한 줄 · 범례 · 전체 보기 · 상세 보기(좁은 화면).
              `absolute inset-0` 캔버스를 가진 section 안이 아니라 **형제**로 둔다(태블릿에서 캔버스 높이가 무너지는 함정). */}
          {stageOverlays && (
            <div data-visibility-strip="map-toolbar" className="flex min-h-11 min-w-0 flex-wrap items-center gap-2">
              {/* 늘 보이는 범례 한 줄 — 지금 정거장 기호 · 판정 낱말 넷 · 선 안내 (27차 §3-D-5) */}
              {graphOverlays && <MapKey stage={mapStage} />}
              {graphOverlays && (
                <div className="min-w-0 flex-1">
                  {busy ? (
                    <RunTimelineStrip runLog={dashboard.runLog} reducedMotion={reducedMotion} />
                  ) : (
                    <GuidedCaptionBar step={guidedStep} onNext={guidedNext} onStart={guidedStart} onExit={guidedExit} inline />
                  )}
                </div>
              )}
              <div className="ml-auto flex shrink-0 items-center gap-2">
                {graphOverlays && (
                  <button
                    type="button"
                    onClick={() => setLegendOpen(true)}
                    aria-haspopup="dialog"
                    aria-expanded={legendOpen}
                    className="mc-focus min-h-9 rounded-lg border border-cosmos-border px-3 text-[13px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
                  >
                    범례
                  </button>
                )}
                {graphOverlays && (
                  <button
                    type="button"
                    onClick={() => selectNode(null)}
                    disabled={!selectedId}
                    aria-describedby={selectedId ? undefined : "map-toolbar-nothing-selected"}
                    title="선택 해제 (Esc)"
                    className="mc-focus min-h-9 rounded-lg border border-cosmos-border px-3 text-[13px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {/* 상단 「쉬운 보기 · 전체 보기」 전환과 같은 이름이었다 — 하는 일대로 (DSH-21) */}
                    선택 해제
                  </button>
                )}
                {graphOverlays && !selectedId && (
                  <span id="map-toolbar-nothing-selected" className="sr-only">
                    고른 항목이 없습니다
                  </span>
                )}
                {!drawerOpen && (
                  <button
                    type="button"
                    onClick={() => setDrawerOpen(true)}
                    className="mc-focus min-h-9 rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 text-[13px] font-semibold text-cosmos-text transition-colors hover:border-cosmos-cyan/60 lg:hidden"
                  >
                    상세 보기
                  </button>
                )}
              </div>
            </div>
          )}
          {stageOverlays && realNoticeNotParsed && (
            <p className="text-[13px] leading-5 text-cosmos-secondary">
              <span className="font-semibold text-cosmos-text">요구사항을 아직 뽑지 않았습니다</span> — 위 「공고 분석 시작」을 누르면
              제안요청서에서 뽑습니다. 그 전에는 근거 · 제안서 · 점검 단계가 비어 있습니다.
            </p>
          )}
        </div>

        {/* 상세 패널: lg 이상은 우측 고정 열, 미만은 하단 드로어.

            `lg:max-h-[560px]` 가 필요한 이유 (ISSUE-122 · prompt_04 §3-B-1): 페이지 높이를
            뷰포트에 묶지 않게 되면서(위 `:203` 주석) 가운데 행의 높이가 **내용**으로 정해진다.
            이 열의 내용 높이는 스크롤 본문이 펼쳐진 크기까지 합쳐 3,025px 였다(1920 실측) —
            상한이 없으면 행이 3,049px 로 늘어나 3D 무대까지 같이 커지고, 패널 안의 스크롤이
            사라져 「사람의 최종 결정」 블록이 바닥에 붙지 않는다. 상한을 3D 무대의 최소
            높이(`lg:min-h-[560px]`)와 같은 값으로 두어 둘이 같은 바닥을 갖게 한다. */}
        <div
          className={`${
            drawerOpen ? "fixed inset-x-2 bottom-12 z-30 flex h-[62vh] flex-col" : "hidden"
          } lg:static lg:flex lg:h-auto lg:max-h-[560px] lg:w-[380px] lg:shrink-0 lg:flex-col`}
          data-panel-region="column"
        >
          {/* 저장된 최종 검토 상태. 화면 승인이 아직 저장 전이면 「임시 (저장 전)」으로 적는다. */}
          <ReviewStatusBar review={dashboard.review} onSave={() => onReviewDecision(dashboard.reviewDecision)} />
          <div className="min-h-0 flex-1 shadow-[0_18px_48px_var(--cosmos-shadow)] lg:shadow-none">
            <DetailPanel
              graph={graph}
              actions={dashboard.actions}
              selectedId={selectedId}
              stage={panelStage}
              runLog={dashboard.runLog}
              onSelect={selectNode}
              onNavigate={navigateTo}
              reviewDecision={dashboard.reviewDecision}
              onReviewDecision={onReviewDecision}
              reducedMotion={reducedMotion}
              onClose={() => setDrawerOpen(false)}
              guidedStep={guideActive ? null : guidedStep}
              onGuidedNext={guidedNext}
              onGuidedGoTo={applyGuided}
              onGuidedExit={guidedExit}
              context={dashboard.context}
              organizationName={organizationName}
            />
          </div>
        </div>
      </div>

      <BottomStrip graph={graph} />

      <LegendSheet open={legendOpen} onClose={() => setLegendOpen(false)} viewMode={viewMode} />
      </>
      )}

      {tutorial.active && <TutorialOverlay controller={tutorial} graph={graph} reducedMotion={reducedMotion} />}
      {quickTour.active && <TutorialOverlay controller={quickTour} graph={graph} reducedMotion={reducedMotion} />}

      {reviewDraft && (
        <ReviewSaveDialog
          target={reviewDraft}
          saved={dashboard.review.saved}
          review={dashboard.review}
          audited={graph.hasAudit}
          openConditions={(graph.source.analysis.conditions?.counts.blocker ?? 0) + (graph.source.analysis.eligibility?.results ?? []).filter((r) => r.status === "CHECK").length}
          onClose={() => setReviewDraft(null)}
        />
      )}

      {welcomeDialog}
    </Frame>
  );
}
