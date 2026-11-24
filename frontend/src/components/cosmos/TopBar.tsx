"use client";

/**
 * 상단 바: 브랜드 · 화면 내비게이션 · 공고 선택기(출처 배지) · 마감 카운트다운 · 진행률 ·
 * 뷰 토글 · Reset · 분석 실행 · 발표 모드 · 튜토리얼.
 * 공고 선택기에는 나라장터 실공고 후보와 데모 시나리오가 함께 들어가며, 둘을 명확히 구분해 표기한다.
 * D-n은 mount 후(useNowMs)에만 계산해 hydration 불일치를 막는다.
 */

import { useEffect, useRef, useState } from "react";

import { useRouter } from "next/navigation";

import { BrandMark, BrandNav, NAV_ITEMS } from "@/components/ui/AppShell";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { Button } from "@/components/ui/primitives";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { WhyBidPilotButton } from "@/components/ui/WhyBidPilotDialog";
import { SUPPORT_VIEW_TITLES, ViewModeToggle } from "@/components/ui/ViewModeToggle";
import type { DisplayMode } from "@/lib/viewMode";
import { SourceBadge } from "@/components/ui/SourceBadge";
import type { CosmosViewMode } from "@/components/cosmos/types";
import { NoticePicker } from "@/components/cosmos/NoticePicker";
import PasswordChange from "@/components/ui/PasswordChange";
import { ROLE_LABELS, useCurrentUser } from "@/lib/currentUser";
import { analyzeControl } from "@/lib/cosmos/analyzeControl";
import { dDayText, daysUntil, deadlineTerm, effectiveDeadline, firstLabel, formatDeadlineDate, noticeDeadlinePair, registrationClosesFirst, urgencyTierOf, type DeadlinePair } from "@/lib/deadline";
import { endedWithoutDate } from "@/lib/cosmos/eligibilityGate";
import type { CosmosGraph } from "@/lib/cosmos/graph";
import type { NoticeListInfo, NoticeOption } from "@/lib/cosmos/useCosmosDashboard";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { scopeBadge } from "@/lib/organization";
import { EVIDENCE_SCOPE_LABELS, type AnalysisContextParams, type OrganizationListResponse } from "@/types/organization";
import { clearAllDrafts, confirmSignOut } from "@/lib/unsavedGuard";
import { clearSelectionMemory } from "@/lib/selection";
import { SCREEN_NAMES } from "@/lib/terms";

/** 입찰 분석 화면의 설명 한 줄 — 메뉴 설명과 같은 글(27차 §3-E 검증 G3-V1 · 2.1.0 부터 메뉴 둘째). */
const ANALYSIS_DESCRIPTION = NAV_ITEMS.find((item) => item.href === "/analysis")?.description ?? "";

/** 「안내」 메뉴 항목 — 발표 모드·튜토리얼·30초 안내를 한 곳으로 접었다 (ISSUE-017). */
const MENU_ITEM_CLASS =
  "mc-focus rounded-md px-2.5 py-2 text-left text-[12.5px] font-medium text-cosmos-text transition-colors hover:bg-cosmos-elevated";

export interface TopBarProps {
  graph: CosmosGraph | null;
  viewMode: CosmosViewMode;
  onViewModeChange: (mode: CosmosViewMode) => void;
  onResetView: () => void;
  onAnalyze: () => void;
  analyzing: boolean;
  presentationActive: boolean;
  onTogglePresentation: () => void;
  tutorialActive: boolean;
  onToggleTutorial: () => void;
  /** 30초 핵심 안내(3단계) 시작. 없으면 버튼을 숨긴다 */
  onStartQuickTour?: () => void;
  /** 화면 위 5단계 안내 시작. 「?」 안내 대화상자에서 바로 켤 수 있게 넘긴다 */
  onStartGuidedFlow?: () => void;
  /** null = 감지 전, false = 3D 불가 */
  webglSupported: boolean | null;
  /** 공고 선택기 항목 (데모 시나리오 + 나라장터 실공고 후보) */
  notices: NoticeOption[];
  selectedNoticeId: string;
  onSelectNotice: (id: string) => void;
  noticeList: NoticeListInfo;
  /** 기업마당 지원사업 목록을 못 받았을 때의 사유. 「없음」과 구분해 적기 위한 것 */
  supportError?: string | null;
  /** 기본 대표 경로만 밝히기 (3D 단순화). 없으면 토글을 숨긴다 */
  /** 다회사 구조: 현재 분석 회사와 근거 범위. 없으면 선택기를 숨긴다 */
  organizations?: OrganizationListResponse | null;
  organizationId?: string;
  /** 회사를 바꾸면 사라지는 분석 결과가 있을 때 묻는 말 (없으면 묻지 않는다 — 작성 중인 글은 선택기가 언제나 묻는다) */
  organizationLoseMessage?: string | null;
  context?: AnalysisContextParams | null;
  /** 「쉬운 보기 ⇄ 전체 보기」 (24차). 없으면 토글을 그리지 않는다 */
  displayMode?: DisplayMode;
  onDisplayModeChange?: (mode: DisplayMode) => void;
  /** 발표·튜토리얼·30초 안내가 켜진 동안 토글을 막는다 */
  displayToggleLocked?: boolean;
  /**
   * 기업마당 지원사업을 보는 중 (DSH-04). 입찰 지도의 3D/2D/목록 · 화면 초기화 · 공고 분석 · 안내 ▾ 는
   * 지원사업에 쓸 곳이 없다 — 회색으로 두지 않고 그리지 않는다.
   */
  supportView?: boolean;
}

/**
 * 「홍길동 · 편집자」와 로그아웃.
 *
 * 왜 여기인가 — 여러 사람이 같은 화면에서 승인·결정·해결 처리를 하고 그 이름이 기록에
 * 남는다. 지금 누구로 들어와 있는지 보이지 않으면, 옆자리 계정으로 열려 있는 브라우저에
 * 자기 판단을 남기고도 모른다.
 *
 * 로그인하지 않았으면(로컬 개발처럼 게이트가 꺼진 상태) **아무것도 그리지 않는다.**
 * 그 상태의 표시는 회사자료 화면의 「로컬 관리자 모드」 배지가 이미 하고 있다.
 *
 * 1행이 아니라 2행에 두는 이유: 1행은 xl(1280px)에서 줄바꿈을 끄는데 지금도 폭이 빠듯하다
 * (ISSUE-053, 실측 scrollWidth 1149). 2행은 공고 선택기가 flex-1 로 줄어들어 자리를 내준다.
 */
function CurrentUserChip() {
  const me = useCurrentUser();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!me) return null;

  // 실패하면 제자리에 이유를 적는다 — AppShell 화면의 SessionControls 와 같은 문장 (CMN-07). 예전에는 조용히 제자리였다.
  const signOut = async () => {
    if (!(await confirmSignOut())) return;  // 43차 M28 — 저장 안 된 글이 있으면 먼저 묻는다(45차 L5 화면 안 창)
    setBusy(true);
    setFailed(false);
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      clearAllDrafts();  // N3 — 남은 임시 저장본을 다음 사람에게 넘기지 않는다.
      clearSelectionMemory();  // 2.0.6 — 보던 공고 기억도(다음 계정이 앞 사람의 공고로 열리지 않게 · SessionControls 와 같다)
      router.replace("/login");
      router.refresh();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="flex min-w-0 shrink-0 items-center gap-1.5" data-tour="topbar-user">
      <span
        className="min-w-0 max-w-[10rem] truncate text-[12px] text-cosmos-secondary"
        title={`${me.displayName} · ${ROLE_LABELS[me.role]} · 아이디 ${me.user}`}
      >
        <span className="font-medium text-cosmos-text">{me.displayName}</span>
        <span className="text-cosmos-muted"> · {ROLE_LABELS[me.role]}</span>
      </span>
      <PasswordChange className="min-h-8" />
      <button
        type="button"
        onClick={() => void signOut()}
        disabled={busy}
        className="mc-focus min-h-8 shrink-0 rounded-lg border border-cosmos-border px-2 text-[12px] text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text disabled:opacity-50"
      >
        {busy ? "나가는 중…" : "로그아웃"}
      </button>
      {failed && (
        <span role="alert" className="text-[12px] text-cosmos-red">
          로그아웃하지 못했습니다 — 다시 눌러 주세요
        </span>
      )}
    </span>
  );
}

// 기본(단계 목록)이 맨 앞 — 2D 지도는 사람이 누를 때만 (28차 §3-F). 3D 는 10-31 대표 결정으로 화면에서 뺐다(코드는 남김).
const VIEW_OPTIONS: Array<{ mode: CosmosViewMode; label: string }> = [
  { mode: "list", label: "목록" },
  { mode: "2d", label: "지도" },
];

/**
 * 마감 배지. 글자는 전부 `lib/deadline` 이 만든다 (0920 §4-B-5 · ISSUE-078).
 *
 * 예전에는 고정 라벨 「마감」 옆에 `formatDDay` 결과를 붙였다. 그래서 마감이 지난 공고는
 * **「마감 마감」**, 마감일이 없으면 **「마감 마감일 미정」**이 찍혔다. 긴급도 경계도
 * `days <= 7` 이 여기 인라인으로 적혀 있어 레이더(3/7/14)와 따로 놀았다.
 */
function DeadlineBadge({ pair, ended = false }: { pair: DeadlinePair; ended?: boolean }) {
  const nowMs = useNowMs();
  // 등록마감이 먼저 닫히면 그쪽이 실제 데드라인 — 목록 · 레이더 · 이번 주 할 일과 같은 규칙(27차 검수 R27U-MSC-01)
  const deadline = effectiveDeadline(pair);
  const registrationFirst = registrationClosesFirst(pair);
  const days = nowMs === null ? null : daysUntil(deadline, nowMs);
  // 마감일이 비었어도 판정이 「접수 끝남」이면 「입찰 종료」 — 「접수 기간 미정」으로 보였다 (UI e)
  const tier = urgencyTierOf(days, ended);
  const tone =
    tier === "closed"
      ? "border-cosmos-red/50 text-cosmos-red"
      : tier === "urgent" || tier === "soon"
        ? "border-cosmos-amber/50 text-cosmos-amber"
        : "border-cosmos-border-strong text-cosmos-text";

  return (
    <span
      data-tour="topbar-deadline"
      className={`inline-flex min-h-8 shrink-0 items-center gap-2 rounded-full border px-3 font-mono text-[12px] tabular-nums ${tone}`}
      title={
        deadline
          ? registrationFirst
            ? `${firstLabel(pair)} ${formatDeadlineDate(pair.qualification)}${pair.bid ? ` · 입찰 마감 ${formatDeadlineDate(pair.bid)}` : ""}`
            : `입찰 마감 ${formatDeadlineDate(deadline)}`
          : ended
            ? "입찰 마감일이 공고에 없습니다 — 판정대로 접수가 끝난 공고입니다"
            : "마감일 미정"
      }
    >
      <span className={tier === "closed" ? undefined : "text-cosmos-muted"}>
        {ended ? "입찰 종료" : registrationFirst && tier !== "closed" ? firstLabel(pair) : deadlineTerm({ source: "g2b", closed: tier === "closed", deadline })}
      </span>
      {/* 마감된 공고는 「입찰 종료」 한 낱말 — 「마감」을 이어 붙이면 「입찰 종료 마감」(27차 §3-E 검증 G5-V2) */}
      {tier !== "closed" && <span aria-live="polite">{dDayText({ deadline, periodKind: null, nowMs })}</span>}
    </span>
  );
}

/**
 * 회사 범위와 공고 근거를 한 칩에 적되 **같은 말은 한 번만** (0925 §4-F-4).
 *
 * 「합성 데모자료 · 합성 데모자료」는 두 가지를 말하는 것처럼 보이지만 한 가지다.
 * 폭도 그만큼 잡아먹어 옆의 「입찰 마감」을 밀어냈다.
 */
export function scopeLabel(scope: string | null, evidence: string): string {
  if (!scope) return evidence;
  return scope === evidence ? scope : `${scope} · ${evidence}`;
}

export default function TopBar({
  graph,
  viewMode,
  onViewModeChange,
  onResetView,
  onAnalyze,
  analyzing,
  presentationActive,
  onTogglePresentation,
  tutorialActive,
  onToggleTutorial,
  onStartQuickTour,
  onStartGuidedFlow,
  supportError,
  webglSupported,
  notices,
  selectedNoticeId,
  onSelectNotice,
  noticeList,
  organizations,
  organizationId,
  organizationLoseMessage = null,
  context,
  displayMode,
  onDisplayModeChange,
  displayToggleLocked = false,
  supportView = false,
}: TopBarProps) {
  const ready = graph !== null;
  const [helpOpen, setHelpOpen] = useState(false);
  const helpRef = useRef<HTMLDivElement | null>(null);
  /*
   * 「안내 ▾」 메뉴 — 바깥을 누르거나 Esc 면 닫고(단추로 초점을 돌린다), ↑↓ 로 항목을 옮긴다 (DSH-29).
   * 예전에는 단추 · 항목을 눌러야만 닫혔고 Esc 는 뒤 지도의 선택만 풀었다.
   */
  useEffect(() => {
    if (!helpOpen) return;
    const wrap = helpRef.current;
    const items = () => [...(wrap?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    items()[0]?.focus({ preventScroll: true });
    const close = () => {
      setHelpOpen(false);
      wrap?.querySelector<HTMLElement>("button[aria-haspopup]")?.focus({ preventScroll: true });
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!wrap?.contains(event.target as Node)) setHelpOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        close();
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const list = items();
      const at = list.indexOf(document.activeElement as HTMLElement);
      if (at < 0) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      list[(at + (event.key === "ArrowDown" ? 1 : -1) + list.length) % list.length]?.focus();
    };
    window.addEventListener("pointerdown", onPointerDown);
    // 캡처로 먼저 받는다 — 대시보드의 창 전체 Esc(선택 해제) · 화살표(항목 이동)보다 앞서야 한다.
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [helpOpen]);
  /** 공고를 불러오기 전에는 지도 단추가 할 일이 없다 — 회색인 이유를 읽을 수 있게 한 줄(sr-only) 붙인다 (화면 규칙 ③). */
  const notReady = ready ? undefined : "topbar-not-ready";
  const presentingReason = "발표 중에는 바꿀 수 없습니다 — 발표를 끝낸 뒤 쓰세요";
  const evidence = scopeBadge(graph?.source.analysis.proposal ?? null);

  const progress = graph ? graph.progress : 0;
  const analyze = analyzeControl(graph, analyzing, onAnalyze);
  /**
   * 쉬운 보기(24차 §3-2)에서는 머리를 줄인다 — 3D/2D/목록 · 화면 초기화 · 「공고 다시 분석」(4단계 펼침으로) ·
   * 「안내 ▾」(「?」 로 합침) · 입찰 마감 칩 · 진행 % 막대 · 합성 데모자료 칩 · 공고 선택기 옆 칩과 링크.
   * 지우지 않는다 — 전체 보기에 그대로 있다.
   */
  const simple = displayMode === "simple";

  return (
    <header className="flex shrink-0 flex-col gap-2 border-b border-cosmos-border bg-cosmos-bg/70 px-3 py-2 backdrop-blur sm:px-4">
      {/* 1행: 브랜드 · 내비 · 실행 버튼. 겹침을 재는 표시는 2행과 같은 이유다 (0925 §4-F-4). */}
      {/*
        줄바꿈을 끄는 기준은 xl(1280px)이다 (ISSUE-053).

        예전에는 lg(1024px)부터 nowrap 이었는데, 이 행의 버튼을 다 펴면 1149px 가 필요해
        13인치 노트북 폭(1024~1148px, 배율 125~150%)에서 가로로 넘쳤다. 실측 scrollWidth 1149 >
        1024 — 브랜드가 왼쪽으로 잘려 나갔다. 버튼을 줄이는 대신 그 구간에서는 줄바꿈으로 되돌린다.
      */}
      <div className="flex min-h-10 flex-wrap items-center gap-2 xl:flex-nowrap xl:gap-3">
        <BrandMark compactBelowSm />
        <div className="mx-1 hidden h-6 w-px shrink-0 bg-cosmos-border md:block" aria-hidden="true" />
        <BrandNav />

        <div className="ml-auto flex w-full flex-wrap items-center gap-2 md:w-auto xl:flex-nowrap">
          {!ready && !supportView && (
            <span id="topbar-not-ready" className="sr-only">
              공고를 불러온 뒤 쓸 수 있습니다
            </span>
          )}
          {!simple && !supportView && (
          <div
            role="group"
            aria-label="뷰 전환"
            data-tour="topbar-view-toggle"
            className="flex items-center rounded-lg border border-cosmos-border bg-cosmos-panel p-0.5 backdrop-blur"
          >
            {VIEW_OPTIONS.map((option) => {
              const active = viewMode === option.mode;
              const unavailable = option.mode === "3d" && webglSupported === false;
              return (
                <button
                  key={option.mode}
                  type="button"
                  aria-pressed={active}
                  disabled={!ready}
                  aria-describedby={notReady}
                  title={unavailable ? "WebGL을 사용할 수 없어 2D로 표시됩니다" : undefined}
                  onClick={() => onViewModeChange(option.mode)}
                  className={`mc-focus min-h-8 rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                    active ? "bg-cosmos-blue/25 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          )}

          {!simple && !supportView && (
          <span className="hidden sm:block">
            <Button size="sm" variant="ghost" onClick={onResetView} disabled={!ready} aria-describedby={notReady} data-tour="topbar-reset" title="카메라와 선택을 처음 상태로 되돌립니다">
              화면 초기화
            </Button>
          </span>
          )}

          {!simple && !supportView && (
          <Button
            size="sm"
            variant="primary"
            onClick={analyze.run}
            disabled={analyzing || presentationActive || !ready}
            aria-busy={analyzing}
            aria-describedby={notReady}
            data-tour="topbar-analyze"
            title={presentationActive ? presentingReason : analyze.title}
          >
            {analyzing && (
              <span
                aria-hidden="true"
                className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white"
                style={{ animation: "mc-spin 0.9s linear infinite" }}
              />
            )}
            {analyze.label}
          </Button>
          )}

          {/*
            안내 세 가지(발표 모드 · 30초 안내 · 상세 튜토리얼)를 한 메뉴로 접는다 (ISSUE-017).

            상단 버튼이 열한 개였다. 처음 온 사람은 「무엇부터 눌러야 하나」를 열한 번
            고민하고, 그중 셋은 업무가 아니라 안내다. 지우지 않고 **접는다** —
            발표 모드는 발표자가 실제로 쓰고, 튜토리얼은 두 번째 방문에 필요하다.
          */}
          {!simple && !supportView && (
          <div ref={helpRef} className="relative hidden sm:block">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setHelpOpen((v) => !v)}
              disabled={!ready}
              aria-describedby={notReady}
              pressed={helpOpen}
              aria-expanded={helpOpen}
              aria-haspopup="menu"
              title="화면 안내 · 발표 모드"
            >
              안내 ▾
            </Button>
            {helpOpen && (
              <div
                role="menu"
                aria-label="화면 안내"
                className="absolute right-0 top-full z-30 mt-1 flex w-52 flex-col gap-1 rounded-lg border border-cosmos-border-strong bg-cosmos-panel p-1.5 shadow-[0_12px_32px_var(--cosmos-shadow)]"
                style={{ backgroundColor: "var(--cosmos-overlay)" }}
              >
                {onStartQuickTour && (
                  <button
                    type="button"
                    role="menuitem"
                    className={MENU_ITEM_CLASS}
                    onClick={() => {
                      setHelpOpen(false);
                      onStartQuickTour();
                    }}
                  >
                    30초 안내
                    <span className="block text-[12px] text-cosmos-muted">공고와 과업 → 근거와 제안서 → 점검과 결정 순서</span>
                  </button>
                )}
                <button
                  type="button"
                  role="menuitem"
                  className={MENU_ITEM_CLASS}
                  data-tour="topbar-tutorial"
                  onClick={() => {
                    setHelpOpen(false);
                    onToggleTutorial();
                  }}
                >
                  {tutorialActive ? "튜토리얼 종료" : "상세 튜토리얼"}
                  <span className="block text-[12px] text-cosmos-muted">15단계 · 약 5분</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className={MENU_ITEM_CLASS}
                  data-tour="topbar-presentation"
                  onClick={() => {
                    setHelpOpen(false);
                    onTogglePresentation();
                  }}
                >
                  {presentationActive ? "발표 종료" : "발표 모드"}
                  <span className="block text-[12px] text-cosmos-muted">큰 화면에서 자동으로 흐름을 보여줍니다</span>
                </button>
              </div>
            )}
          </div>
          )}
        </div>
      </div>

      {/*
        2행: 공고 선택기 · 출처 · 마감 · 진행률

        **줄바꿈을 끄지 않는다** (0925 §4-F-4 · ISSUE-106). `md:flex-nowrap` 이 있을 때
        1280px 에서 「◆합성 데모자료 · 합성 데모자료」(x901 · 폭 170)와 「입찰 마감 D-7」
        (x972 · 폭 111)이 **99px 겹쳤다** — 10차 캡처 03(1440px)에서도 잘려 있었다.
        자리가 모자라면 겹치는 대신 줄을 바꾼다. `data-visibility-strip` 은
        `scripts/check_visibility.mjs` 가 형제 요소의 사각형 겹침을 재는 표시다.
      */}
      <div
        data-visibility-strip="topbar-row2"
        data-view={simple ? "simple" : undefined}
        className={`flex min-h-9 flex-wrap items-center gap-2 md:gap-3 ${simple ? "mx-auto w-full max-w-[960px]" : ""}`}
      >
        {/* 화면 제목 = 메뉴 이름 (27차 §3-E-4). 쉬운 보기는 공고 카드가 제목(h1)을 갖는다(24차 §3-2). */}
        {!simple && (
          <>
            <h1 className="shrink-0 text-[15px] font-semibold text-cosmos-text" title={ANALYSIS_DESCRIPTION}>
              {SCREEN_NAMES.analysis}
            </h1>
            {/* 설명 한 줄 — 메뉴 설명과 같은 글(27차 §3-E 검증 G3-V1). 지도 높이를 지키려고 1280px 이상에서만 보인다(1440 시연 폭 포함 · 검수 R27U-HD-06). */}
            <span className="hidden shrink-0 text-[12px] text-cosmos-muted xl:inline">{ANALYSIS_DESCRIPTION}</span>
          </>
        )}
        <NoticePicker
          notices={notices}
          selectedNoticeId={selectedNoticeId}
          onSelectNotice={onSelectNotice}
          noticeList={noticeList}
          supportError={supportError ?? null}
          disabled={analyzing || presentationActive}
          disabledReason={presentationActive ? presentingReason : "분석 중에는 공고를 바꿀 수 없습니다"}
          origin={graph?.source.origin ?? null}
          pinned={graph?.source.notice.pinned}
          bare={simple}
        />
        {organizationId && !simple && (
          <span className="hidden xl:inline-flex" title={evidence.detail}>
            <SourceBadge
              kind={evidence.tone === "ok" ? "human" : evidence.tone === "demo" ? "demo" : evidence.tone === "warn" ? "rule" : "not_run"}
              label={scopeLabel(context ? EVIDENCE_SCOPE_LABELS[context.evidence_scope] : null, evidence.label)}
            />
          </span>
        )}
        {graph && !simple && (
          <>
            <DeadlineBadge
              pair={noticeDeadlinePair(graph.source.notice)}
              ended={endedWithoutDate(graph.eligibility, effectiveDeadline(noticeDeadlinePair(graph.source.notice)))}
            />
            <div
              data-tour="topbar-progress"
              className="hidden shrink-0 items-center gap-2 lg:flex"
              title="8단계 중 끝낸 단계 수"
            >
              <span className="text-[12px] text-cosmos-muted">진행</span>
              <span className="font-mono text-[12px] tabular-nums text-cosmos-text">{Math.round(progress * 8)}/8단계</span>
              <div
                className="h-1 w-24 overflow-hidden rounded-full bg-cosmos-slate/60"
                role="progressbar"
                aria-label="분석 진행률 — 8단계 중 완료된 단계 비율"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(progress * 100)}
              >
                <div
                  className="h-full rounded-full bg-cosmos-cyan transition-[width] duration-300"
                  style={{ width: `${Math.round(progress * 100)}%` }}
                />
              </div>
            </div>
          </>
        )}
        {/*
          오른쪽은 모든 화면이 같은 순서다 — 회사 선택기 → 보기 전환 → 접속 → 「?」 (27차 §3-E-4 · UNI-11).
          예전에는 「?」가 1행 가운데(화면 초기화와 공고 다시 분석 사이), 토글이 2행 회사 뒤에 있어
          넓은 폭에서는 3행 왼쪽으로 떨어졌다.
        */}
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2" data-header-right>
          {organizationId && (
            <span data-tour="topbar-organization" className="flex min-w-0">
              <OrganizationPicker
                id="cosmos-organization-picker"
                list={organizations ?? null}
                organizationId={organizationId}
                disabled={analyzing || presentationActive}
                disabledReason="분석 · 발표 중에는 회사를 바꿀 수 없습니다"
                loseMessage={organizationLoseMessage}
              />
            </span>
          )}
          {displayMode && onDisplayModeChange && (
            <ViewModeToggle
              mode={displayMode}
              onChange={onDisplayModeChange}
              disabled={displayToggleLocked}
              disabledReason="발표 · 안내 중에는 바꿀 수 없습니다 — 끝나면 시작 전 보기로 돌아갑니다"
              titles={supportView ? SUPPORT_VIEW_TITLES : undefined}
            />
          )}
          {/* 「누가 보고 있는가」 — AppShell 화면의 접속 칸과 같은 자리(「?」 바로 앞). */}
          <CurrentUserChip />
          <ThemeToggle />
          {/* 처음 안내는 여기 하나로 모은다 — 시작 순서 · GPT와의 차이 · 하지 않는 것 · 안내 시작 버튼. */}
          <WhyBidPilotButton
            variant="icon"
            actions={{
              onStartGuidedFlow,
              onStartTutorial: ready ? () => onToggleTutorial() : undefined,
              // 쉬운 보기에서는 「안내 ▾」 메뉴가 없다 — 발표 모드 · 30초 안내도 여기서 시작한다 (24차 §3-1).
              onStartQuickTour: ready ? onStartQuickTour : undefined,
              onStartPresentation: ready && !presentationActive ? onTogglePresentation : undefined,
            }}
          />
        </div>
      </div>
    </header>
  );
}
