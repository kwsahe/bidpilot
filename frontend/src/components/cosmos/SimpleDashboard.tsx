"use client";

/**
 * 쉬운 보기 — 입찰 공고 한 건 (24차 · prompt_14 §3-2).
 *
 * 담당자 말: 「시인성 대폭 개선… 보기 쉬운 모드를 만들어서 따로… 지금까지 만들어진 기능들은 삭제 금지.」
 * 그래서 새 판단·새 문장을 만들지 않는다. 전체 보기의 부품을 **그대로** 불러 한 열(본문 폭 960px)에
 * 위에서 아래로 놓는다 — ① 출처 한 줄 ② 공고 ③ 참가 판정 ④ 지금 할 일 ⑤ 진행 8단계 ⑥ 결정.
 * (① 의 공고 선택기 · 회사 · 토글은 `TopBar` 2행이 같은 폭으로 줄어 맡는다.)
 *
 * 글자 크기는 바깥 틀 `[data-view="simple"]` 의 CSS 가 올린다(globals.css) — 부품 안을 고치지 않는다.
 * 색은 판정 색(가능 · 확인 필요 · 불가)과 중립 둘뿐이다. 칩 · 아이콘 장식을 두지 않는다.
 */

import { requirementSheetHref } from "@/lib/selection";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import DetailPanel, { EligibilityGroups, HumanReviewBlock, PageLink, eligibilityBannerText } from "@/components/cosmos/DetailPanel";
import { DecisionBlock } from "@/components/cosmos/GatePanel";
import { endedWithoutDate } from "@/lib/cosmos/eligibilityGate";
import AttachmentLinks from "@/components/ui/AttachmentLinks";
import NoticeQaPanel from "@/components/ui/NoticeQaPanel";
import { RfpDownloadLink, useRfpLink } from "@/components/ui/NoticeSourceLinks";
import { attachmentLinkOf } from "@/lib/attachments";
import { noticeSourceHref } from "@/lib/noticeLinks";
import { useAnalysisLoading } from "@/lib/cosmos/analysisLoading";
import { analyzeControl } from "@/lib/cosmos/analyzeControl";
import { formatBudgetCompact } from "@/lib/cosmos/format";
import { FIRST_BID_SHORT, OPEN_REQUIREMENT_SHEET, PICK_REAL_NOTICE, SCREEN_NAMES, SYNTHETIC_NOTICE, WRITE_PROPOSAL_BUTTON } from "@/lib/terms";
import { expiringLine } from "@/lib/firstTimeGuide";
import { useExpiringCredentials } from "@/components/guide/useExpiringCredentials";
import { useOrganizationId } from "@/lib/organization";
import { AUDIT_NODE_ID, isStepSettled, sourceBadges, type CosmosGraph, type ReviewDecision, type WorkflowStage } from "@/lib/cosmos/graph";
import { landingStageOf, nextActions, type NextAction } from "@/lib/cosmos/mission";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import { VERDICT_BOX_CLASS } from "@/lib/cosmos/theme";
import { loadingText, useNowMs, type AnalysisActions, type RunLog } from "@/lib/cosmos/useCosmosDashboard";
import { dDayText, daysUntil, deadlineTerm, effectiveDeadline, firstLabel, formatDeadlineDateTime, formatPairDeadline, noticeDeadlinePair, registrationClosesFirst, urgencyTierOf } from "@/lib/deadline";
import type { AnalysisContextParams } from "@/types/organization";
import { noticeAttachments } from "@/types/procurement";

const SECTION = "flex flex-col gap-3 border-t border-cosmos-border pt-6";
const SECTION_TITLE = "text-[15px] font-semibold text-cosmos-secondary";
const BIG_BUTTON =
  "mc-focus min-h-11 w-fit rounded-lg bg-cosmos-blue-strong px-5 text-[15px] font-semibold text-white transition-colors hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";
const NOTICE_LINK = "mc-focus whitespace-nowrap rounded text-cosmos-cyan underline underline-offset-2 hover:brightness-110";
const LINE_BUTTON =
  "mc-focus min-h-10 w-fit rounded-lg border border-cosmos-border-strong px-4 text-[14px] font-medium text-cosmos-text transition-colors hover:border-cosmos-text/60";

/** 공고 · 요구사항을 그린 뒤 뒤이어 읽는 단계 — 판정 · 근거 · 제안서 · 점검(`loadAnalysis`). 2단계 「아직 안 함」은 읽는 것이 아니라 그대로다. */
const LOADED_LATER = new Set<WorkflowStage>([3, 5, 6, 7]);

/** 「지금 할 일」 단추가 가는 곳 — 결정·승인은 맨 아래 덩어리, 조항 확인은 판정 카드, 나머지는 그 단계 펼침. */
type Target = "checklist" | "decision" | "step";

function targetOf(action: NextAction): Target {
  if (action.kind === "clauses") return "checklist";
  if (action.kind === "eligibility_fail" || action.kind === "decision" || action.kind === "review" || action.kind === "done") return "decision";
  return "step";
}

/**
 * 단계를 펼칠 때 먼저 보일 것. 7단계는 점검을 한 번 돌린 뒤에는 개요에 실행 칸이 없다 —
 * 「제출 전 점검」 입력(`AuditorRunPanel`)은 점검 결과 상세에 있으므로 그리로 연다.
 */
function stepEntryNode(stage: WorkflowStage, graph: CosmosGraph): string | null {
  return stage === 7 && graph.hasAudit ? AUDIT_NODE_ID : null;
}

function nextButtonLabel(action: NextAction, graph: CosmosGraph): string {
  const target = targetOf(action);
  if (target === "checklist") return "조항 체크리스트 열기";
  if (target === "decision") return "결정으로 가기";
  return `${action.stage}단계 ${graph.steps[action.stage - 1].label} 열기`;
}

function scrollToId(id: string): void {
  // 클릭 처리 안에서 바꾼 상태는 이벤트가 끝나며 바로 그려진다 — 다음 프레임에 굴린다.
  window.requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
}

/** 간 곳으로 초점 — 누른 단추가 사라지거나(패널이 새로 그려짐) 화면만 굴러가면 초점이 <body> 에 남았다 (EZ-19). */
function focusById(id: string): void {
  window.requestAnimationFrame(() => document.getElementById(id)?.focus({ preventScroll: true }));
}

export interface SimpleDashboardProps {
  graph: CosmosGraph;
  actions: AnalysisActions;
  runLog: RunLog;
  analyzing: boolean;
  /** 발표 모드처럼 분석을 막아야 할 때 */
  analyzeLocked: boolean;
  onAnalyze: () => void;
  reviewDecision: ReviewDecision;
  onReviewDecision: (decision: ReviewDecision) => void;
  reducedMotion: boolean;
  /** 저장된 최종 검토 상태 줄 (셸의 `ReviewStatusBar`) */
  reviewStatus: ReactNode;
  /** 분석 오류 · 목록에 없는 공고 같은 알림 */
  alerts: ReactNode;
  /** 전체 보기 상세 패널과 같은 회사 · 근거 범위 — 없으면 내려받기 · 서식이 기본 회사로 간다(26차 ISSUE-149). */
  context?: AnalysisContextParams | null;
  organizationName?: string | null;
  /**
   * 「?」 안내(전체 보기로 그린다)가 **이동으로 끝나** 쉬운 보기로 돌아올 때 펼칠 단계 (26차 ISSUE-154).
   * 셸이 `key` 를 바꿔 새로 그리므로 처음 상태로만 읽는다. 안내를 명시적으로 닫았으면 없다 — 그때는 맨 위.
   */
  returnTo?: { stage: WorkflowStage; nodeId: string | null } | null;
  /** returnTo 를 읽었다 — 셸이 비운다(다시 그려질 때 옛 단계를 또 펼치지 않게 · 26차 검수 FE-1). */
  onReturnConsumed?: () => void;
}

export default function SimpleDashboard({
  graph,
  actions,
  runLog,
  analyzing,
  analyzeLocked,
  onAnalyze,
  reviewDecision,
  onReviewDecision,
  reducedMotion,
  reviewStatus,
  alerts,
  context = null,
  organizationName = null,
  returnTo = null,
  onReturnConsumed,
}: SimpleDashboardProps) {
  const nowMs = useNowMs();
  // 공고를 바꾼 직후 판정 · 제안서 · 점검을 뒤이어 불러오는 동안 — 「아직 판정하지 않았습니다」로 읽히지 않게 (EZ-03)
  const analysisLoading = useAnalysisLoading();
  const [checklistOpen, setChecklistOpen] = useState(false);
  // 한 번에 한 단계만 펼친다. 펼친 단계는 테두리로만 표시하고 ● 은 옮기지 않는다.
  const [open, setOpen] = useState<{ stage: WorkflowStage; nodeId: string | null } | null>(() =>
    returnTo ? { stage: returnTo.stage, nodeId: returnTo.nodeId ?? stepEntryNode(returnTo.stage, graph) } : null,
  );
  // **처음 그릴 때 한 번만**: 안내에서 누른 단계로 돌아왔으면 그 자리로(그리고 셸에 다 썼다고 알린다), 아니면 맨 위로 —
  // 전체 보기의 스크롤이 남지 않게. 셸이 returnTo 를 비워도 다시 굴리지 않는다.
  const mountReturn = useRef({ returnTo, onReturnConsumed });
  useEffect(() => {
    const first = mountReturn.current;
    if (first.returnTo) {
      scrollToId("simple-step-panel");
      // 안내가 끝나며 초점이 <body> 로 떨어졌다 — 펼친 단계 단추로 옮긴다(키보드 · 화면 읽기 · 27차 R26-17).
      window.requestAnimationFrame(() =>
        document.querySelector<HTMLElement>('[data-simple-step][aria-expanded="true"]')?.focus({ preventScroll: true }),
      );
      first.onReturnConsumed?.();
    } else {
      window.scrollTo({ top: 0 });
    }
  }, []);

  const { notice, origin } = graph.source;
  // 읽는 동안 「참가 판정: 아직 안 함」이 아니라 「불러오는 중…」(10-31 최종 점검 A5)
  const sources = sourceBadges(graph).map((b) => loadingText(b.label, analysisLoading)).join(" · ");
  const attachments = noticeAttachments(notice);
  const sourceHref = origin.kind === "demo" ? null : noticeSourceHref(notice.source_url);
  const rfp = useRfpLink(origin.kind === "demo" ? "" : notice.id);
  const otherAttachments = attachments.filter((file) => file.url !== rfp?.href).length;
  // 등록마감이 먼저 닫히면 D-day 는 그쪽으로(전체 보기 상단 · 목록 · 레이더와 같은 규칙 · 검수 R27U-MSC-01)
  const pair = noticeDeadlinePair(notice);
  const deadline = effectiveDeadline(pair);
  const registrationFirst = registrationClosesFirst(pair);
  const days = nowMs === null ? null : daysUntil(deadline, nowMs);
  // 마감일이 비었어도 판정이 「접수 끝남」이면 끝난 공고 — 「마감일 미정」 옆에 「접수가 끝난 공고」가 섰다 (UI e)
  const ended = endedWithoutDate(graph.eligibility, deadline);
  const tier = urgencyTierOf(days, ended);
  const banner = eligibilityBannerText(graph);
  // 판정 상자 · 글자는 판정 4색 한 곳(`theme.VERDICT_BOX_CLASS`) — 「가능」이 여기서만 초록이던 것을 없앴다 (27차 §3-E · UNI-10).
  // 불러오는 동안은 중간 판정의 색도 쓰지 않는다 — 문장과 함께 바뀌어 보였다 (EZ-03).
  const tone = banner && !analysisLoading ? VERDICT_BOX_CLASS[banner.view.verdict] : null;
  const next = nextActions(graph)[0] ?? null;
  const landing = landingStageOf(graph);
  const settledCount = graph.steps.filter(isStepSettled).length;
  const analyze = analyzeControl(graph, analyzing, onAnalyze);

  const go = (action: NextAction) => {
    const target = targetOf(action);
    if (target === "checklist") {
      setChecklistOpen(true);
      scrollToId("simple-verdict");
      focusById("simple-verdict");
    } else if (target === "decision") {
      scrollToId("simple-decision");
      focusById("simple-decision");
    } else {
      // 참가를 막는 조건 · 점검은 할 일 쪽(mission.nextActions)이 개요(nodeId null)를 가리킨다 (EZ-02 · DTL-04).
      setOpen({ stage: action.stage, nodeId: action.nodeId });
      scrollToId("simple-step-panel");
      focusById("simple-step-panel");
    }
  };
  // 펼친 칸 안에서 다른 항목 · 단계로 옮기면 패널이 새로 그려진다 — 초점을 칸 머리로 (EZ-19)
  const moveInPanel = (stage: WorkflowStage, nodeId: string | null) => {
    setOpen({ stage, nodeId });
    focusById("simple-step-panel");
  };
  // 4단계 「공고 분석 시작」이 실패한 사유 — 맨 위 출처 줄에만 뜨면 펼친 단추 옆에서는 보이지 않았다 (EZ-04)
  const parseFailure = runLog.parse.status === "failed" ? runLog.parse.detail : null;
  const expiring = useExpiringCredentials(useOrganizationId());

  return (
    <div data-view="simple" className="mx-auto flex w-full max-w-[992px] flex-col gap-6 px-4 pb-16 pt-4">
      {/* ① 출처 — 칩이 아니라 글줄. 라벨은 sourceBadges 그대로 잇기만 한다. */}
      <div className="flex flex-col gap-1" data-simple-chunk="source">
        <p className="text-[14px] leading-6 text-cosmos-secondary">출처: {sources}</p>
        {origin.kind === "demo" && (
          <p className="text-[14px] font-medium leading-6 text-cosmos-text">
            <span aria-hidden="true" className="mr-1 text-cosmos-slate">◇</span>
            {SYNTHETIC_NOTICE}입니다 — 여기서 저장한 결정은 다른 사용자에게도 보입니다{" "}
            <Link href="/opportunities" className="mc-focus whitespace-nowrap text-cosmos-cyan underline-offset-2 hover:underline">
              {PICK_REAL_NOTICE}
            </Link>
          </p>
        )}
        {alerts}
      </div>

      {/* ② 공고 */}
      <section aria-labelledby="simple-notice-title" className="flex flex-col gap-2" data-simple-chunk="notice">
        <h1 id="simple-notice-title" className="break-keep text-[20px] font-semibold leading-snug text-cosmos-text [overflow-wrap:anywhere]">
          {notice.title}
        </h1>
        <p className="text-[15px] text-cosmos-secondary">
          {notice.agency} · 예산 {formatBudgetCompact(notice.budget)}
        </p>
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span
            className={`text-[28px] font-semibold tabular-nums ${
              tier === "closed" ? "text-cosmos-red-text" : tier === "urgent" || tier === "soon" ? "text-cosmos-amber" : "text-cosmos-text"
            }`}
          >
            {ended ? "접수 끝남" : dDayText({ deadline, periodKind: null, nowMs })}
          </span>
          {ended && <span className="text-[14px] text-cosmos-secondary">입찰 마감일이 공고에 없습니다 — 아래 판정대로 접수가 끝난 공고입니다</span>}
          {/* 마감일이 없으면 큰 글 「마감일 미정」 하나로 — 옆에 「접수 기간 미정 마감일 미정」을 겹쳐 적지 않는다 (EZ-20) */}
          {(notice.deadline_at || (registrationFirst && tier !== "closed")) && (
            <span className="text-[14px] text-cosmos-secondary">
              {registrationFirst && tier !== "closed" && `${firstLabel(pair)} ${formatPairDeadline(pair, pair.qualification, "datetime")}${notice.deadline_at ? " · " : ""}`}
              {notice.deadline_at &&
                `${deadlineTerm({ source: "g2b", closed: tier === "closed", deadline: notice.deadline_at })} ${formatDeadlineDateTime(notice.deadline_at)}`}
            </span>
          )}
        </p>
        {/* 곧 만료 · 만료됨 — 쉬운 보기 첫 화면에도 한 줄(32차 R31-10) */}
        {expiring.length > 0 && (
          <p className="text-[14px] leading-6 text-cosmos-amber" data-simple-expiring role="note">
            {expiringLine(expiring)}{" "}
            <Link href="/company#readiness" className="mc-focus whitespace-nowrap text-cosmos-cyan underline-offset-2 hover:underline">
              회사자료에서 보기 →
            </Link>
          </p>
        )}
        {/* 처음 입찰하는 사람이 가장 먼저 볼 줄 — 1단계를 펼쳐야만 보였다(32차 §3-B-3). 가상 예시 공고에는 내지 않는다(R31-14).
            문장은 첫 화면에 두고 「처음 등록하는 법」 링크는 1단계 펼침 · 메뉴 「실전 가이드」로 — 아래 공고 원문 · 제안요청서 두 링크를
            첫 화면 단추 12개 상한 안에 두려고(2.9.1 · 대표 11-13 결정 「가이드 링크를 1단계로」). */}
        {origin.kind !== "demo" && tier !== "closed" && (
          <p className="text-[14px] leading-6 text-cosmos-secondary" data-simple-first-bid>
            {FIRST_BID_SHORT} 등록하는 법은 1단계 「공고 탐색」 · 메뉴 「실전 가이드」에 있습니다.
          </p>
        )}
        {/* 공고 원문 · 제안요청서 — 한 줄 두 링크(2.9.1 · 대표 11-13). 제안요청서를 찾으면 접힌 첨부 목록 대신이다 — 다른 첨부(공고문 ·
            서식)는 1단계 펼침 「공고 상세 · 첨부 보기」 · 전체 보기에 그대로 있다. 첫 화면 단추 12개 상한(24차)은 위 가이드 링크를 1단계로
            옮겨 맞춘다(링크 둘 = 접힌 목록 하나 + 가이드 링크 하나). */}
        {(sourceHref || rfp) && (
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[15px]" data-simple-notice-links>
            {sourceHref && (
              <a href={sourceHref} target="_blank" rel="noreferrer noopener" className={NOTICE_LINK}>
                나라장터 공고 원문 ↗
              </a>
            )}
            {rfp && <RfpDownloadLink link={rfp} className={NOTICE_LINK} />}
            {rfp && otherAttachments > 0 && (
              <span className="text-[14px] text-cosmos-secondary">다른 첨부 {otherAttachments}개는 1단계 「공고 상세」에</span>
            )}
          </p>
        )}
        {rfp === null && attachments.length > 0 && (
          <AttachmentLinks
            // 모두 한 줄(「첨부 n개 보기 ▸」)로 접는다 — 긴 첨부 이름 두 줄이 휴대폰 폭에서 판정 카드를 첫 화면 밖으로 밀었다(37차 · 실무순 1위 공고)
            collapseAfter={0}
            items={attachments.map((file, index) => ({ key: `${index}:${file.url || file.name}`, ...attachmentLinkOf(file) }))}
          />
        )}
        {/* 사업기회 행과 같은 두 길 — 6단계를 펼쳐야만 사업계획서 작성 페이지로 갈 수 있었다(10-26 대표 「입찰 분석에서 바로 사업계획서 작성이 안 보인다」).
            가상 예시 · 마감 공고에는 내지 않는다(사업계획서 작성 페이지가 잠근다). */}
        {origin.kind !== "demo" && tier !== "closed" && (
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[15px]" data-simple-write-links>
            <PageLink href={requirementSheetHref(notice.id)}>{OPEN_REQUIREMENT_SHEET}</PageLink>
            <PageLink href={`/plan?notice=${encodeURIComponent(notice.id)}`}>{WRITE_PROPOSAL_BUTTON}</PageLink>
          </p>
        )}
      </section>

      {/* ③ 참가 판정 — 가장 크게. 문장은 전체 보기 판정 띠와 같은 함수에서 온다. */}
      <section
        id="simple-verdict"
        tabIndex={-1}
        aria-labelledby="simple-verdict-question"
        data-simple-verdict={banner?.view.verdict ?? "none"}
        className={`flex scroll-mt-4 flex-col gap-3 rounded-xl border-2 px-5 py-4 outline-none ${tone ? tone.box : "border-cosmos-border"}`}
      >
        <h2 id="simple-verdict-question" className={SECTION_TITLE}>
          이 입찰에 참가할 수 있나요?
        </h2>
        <p className={`break-keep text-[22px] font-semibold leading-snug [overflow-wrap:anywhere] ${tone ? tone.text : "text-cosmos-text"}`}>
          {/* 불러오는 동안은 앞서 그린 판정이 있어도 기다린다 — 중간 판정이 보였다가 바뀌었다 (EZ-03) */}
          {analysisLoading
            ? "판정 결과를 불러오는 중입니다…"
            : banner
              ? banner.message
              : "아직 판정 전입니다 — 아래 「지금 할 일」을 따라 판정하세요"}
        </p>
        {banner?.note && !analysisLoading && <p className="text-[14px] text-cosmos-secondary">{banner.note}</p>}
        {graph.eligibility.length > 0 && !analysisLoading && (
          <>
            <button
              type="button"
              aria-expanded={checklistOpen}
              onClick={() => setChecklistOpen((v) => !v)}
              className="mc-focus min-h-10 w-fit rounded text-left text-[15px] font-medium text-cosmos-text underline-offset-4 hover:underline"
            >
              {/* 전체와 남은 수를 한 문장에 — ④ 「참가자격 조항 n개 확인」(남은 것)과 수가 둘로 보이지 않게 (EZ-21) */}
              {banner && banner.view.total > 0
                ? banner.view.pending > 0
                  ? `조항 ${banner.view.total}개 중 ${banner.view.pending}개 남음 — 하나씩 확인`
                  : `조항 ${banner.view.total}개 모두 확인함 — 다시 보기`
                : `판정 근거 ${graph.eligibility.length}개 보기`}{" "}
              {checklistOpen ? "▾" : "▸"}
            </button>
            {checklistOpen && <EligibilityGroups graph={graph} actions={actions} collapseFields />}
          </>
        )}
      </section>

      {/* ④ 지금 할 일 — 하나만. 분석 결과를 불러오는 동안은 정하지 않는다(판정 전 할 일이 먼저 보였다 · EZ-03). */}
      {analysisLoading && (
        <section aria-labelledby="simple-next-title" className={SECTION} data-simple-chunk="next">
          <h2 id="simple-next-title" className={SECTION_TITLE}>
            지금 할 일
          </h2>
          <p role="status" className="text-[14px] leading-6 text-cosmos-secondary">
            분석 결과를 불러오는 중입니다 — 다 불러온 뒤 할 일을 하나 고릅니다.
          </p>
        </section>
      )}
      {next && !analysisLoading && (
        <section aria-labelledby="simple-next-title" className={SECTION} data-simple-chunk="next">
          <h2 id="simple-next-title" className={SECTION_TITLE}>
            지금 할 일
          </h2>
          <p className="break-keep text-[17px] font-semibold leading-snug text-cosmos-text">{next.label}</p>
          <p className="text-[14px] leading-6 text-cosmos-secondary">
            {/* 쉬운 보기 머리에는 분석 단추가 없다 — 「상단 「공고 분석 시작」」 대신 단추가 실제로 있는 4단계 펼침을 가리킨다 (EZ-38).
                단추 이름은 늘 「공고 분석 시작」 — 분석 중 이름(「분석 중…」)을 끼우면 문장이 깨졌다. */}
            {next.kind === "parse" ? "4단계를 펼쳐 「공고 분석 시작」을 누르세요. 첨부 제안요청서에서 할 일과 조건을 쪽 번호와 함께 뽑습니다." : next.detail}
          </p>
          <button type="button" onClick={() => go(next)} className={BIG_BUTTON} data-simple-next>
            {nextButtonLabel(next, graph)}
          </button>
        </section>
      )}

      {/* 진행 8단계 — 기호는 레일과 같은 사전(✓ 완료 · ● 진행 중 · ! 확인 필요 · ✕ 실패 · ○ 대기 · 27차 §3-D-9) ·
          「지금」은 글자로(내려앉기와 같은 함수) */}
      <section aria-labelledby="simple-steps-title" className={SECTION} data-simple-chunk="steps">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="simple-steps-title" className={SECTION_TITLE}>
            진행 8단계
          </h2>
          <span className="text-[14px] text-cosmos-secondary">완료 {settledCount}/8</span>
        </div>
        {/* 칸 폭 700px(NARROW_CANVAS_PX) 미만이면 세로 목록 — 창 폭이 아니라 이 칸의 폭으로 판단한다. */}
        <div className="@container">
          <ol className="grid grid-cols-1 gap-2 @min-[700px]:grid-cols-8">
            {graph.steps.map((step) => {
              const now = step.id === landing;
              const expanded = open?.stage === step.id;
              // 뒤이어 읽는 단계(3 판정 · 5 근거 · 6 제안서 · 7 점검)는 읽는 동안 「아직 안 함」 대신 「불러오는 중…」(10-31 최종 점검 A5)
              const summary = loadingText(step.summary, analysisLoading && LOADED_LATER.has(step.id));
              return (
                <li key={step.id} className="flex">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    aria-controls={expanded ? "simple-step-panel" : undefined}
                    aria-current={now ? "step" : undefined}
                    data-simple-step={step.id}
                    onClick={() => setOpen(expanded ? null : { stage: step.id, nodeId: stepEntryNode(step.id, graph) })}
                    className={`mc-focus flex w-full items-baseline gap-2 rounded-lg border px-3 py-2 text-left transition-colors @min-[700px]:flex-col @min-[700px]:gap-1 ${
                      expanded ? "border-cosmos-text bg-cosmos-elevated/60" : "border-cosmos-border hover:border-cosmos-border-strong"
                    }`}
                  >
                    <span
                      className={`shrink-0 font-mono text-[15px] ${now ? "font-semibold text-cosmos-text" : "text-cosmos-secondary"}`}
                      title={STEP_STATUS_META[step.status].label}
                    >
                      <span aria-hidden="true">{STEP_STATUS_META[step.status].glyph}</span>
                      <span className="sr-only">{STEP_STATUS_META[step.status].label} </span> {step.id}
                      {now && <span className="ml-1.5 font-sans">지금</span>}
                    </span>
                    {/* 8칸(한 칸 89px)에서 긴 기관명이 옆 칸으로 넘쳤다 — 제목 · 판정과 같이 끊고, 요약은 두 줄에서 자른다(26차 ISSUE-154). */}
                    <span className={`min-w-0 break-keep text-[14px] leading-snug [overflow-wrap:anywhere] ${now ? "font-semibold text-cosmos-text" : "text-cosmos-text"}`}>
                      {step.label}
                    </span>
                    <span
                      className="ml-auto line-clamp-2 min-w-0 break-keep text-right text-[14px] leading-snug text-cosmos-secondary [overflow-wrap:anywhere] @min-[700px]:ml-0 @min-[700px]:text-left"
                      title={summary}
                    >
                      {summary}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
        {open && (
          <div
            id="simple-step-panel"
            role="region"
            aria-label={`${open.stage}단계 ${graph.steps[open.stage - 1].label} 펼침`}
            tabIndex={-1}
            className="flex scroll-mt-4 flex-col gap-3 outline-none"
          >
            {/* 조건 찾기 · 해결 처리 · 할 일 추가가 실패하면 펼친 칸 위에 — ⑥ 에만 뜨면 누른 곳에서 보이지 않았다.
                알림(role=alert)은 한 번만: 칸이 열려 있으면 여기서, ⑥ 은 같은 글을 조용히 (EZ-11). */}
            {actions.gateError && (
              <p role="alert" className="rounded-lg border border-cosmos-red/40 bg-cosmos-red/10 px-3 py-2 text-[14px] text-cosmos-red">
                {actions.gateError}
              </p>
            )}
            {open.stage === 4 && (
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={analyze.run}
                  disabled={analyzing || analyzeLocked}
                  aria-busy={analyzing}
                  title={analyze.title}
                  // 분석 전에는 채운 단추로 — 얇은 테두리라 칸과 따로 노는 것처럼 보였다 (P1-01)
                  className={graph.counts.requirements > 0 ? LINE_BUTTON : BIG_BUTTON}
                >
                  {analyze.label}
                </button>
                <span className="text-[14px] text-cosmos-secondary">{analyze.title}</span>
                {/* 알림(role)은 맨 위 출처 줄 한 곳 — 여기는 단추 옆에 같은 사유를 조용히 (EZ-04) */}
                {parseFailure && !analyzing && (
                  <p className="basis-full text-[14px] leading-6 text-cosmos-amber">
                    분석하지 못했습니다 — {parseFailure}
                    {parseFailure.includes("저장해 둔 첨부만") && (
                      <>
                        {" "}
                        <Link href={requirementSheetHref(notice.id)} className="mc-focus underline underline-offset-2">
                          {SCREEN_NAMES.rfp}에서 제안요청서 1건 받기 →
                        </Link>
                      </>
                    )}
                  </p>
                )}
              </div>
            )}
            <DetailPanel
              embedded
              graph={graph}
              actions={actions}
              selectedId={open.nodeId}
              stage={open.stage}
              runLog={runLog}
              onSelect={(id) => moveInPanel(open.stage, id)}
              onNavigate={moveInPanel}
              reviewDecision={reviewDecision}
              onReviewDecision={onReviewDecision}
              reducedMotion={reducedMotion}
              context={context}
              organizationName={organizationName}
            />
          </div>
        )}
      </section>

      {/* ⑥ 결정 — 참여 · 보류 · 참여 안 함, 그 아래 사람의 최종 결정(검토 승인 · 보류) */}
      <section id="simple-decision" tabIndex={-1} aria-label="결정" className={`${SECTION} scroll-mt-4 outline-none`} data-simple-chunk="decision">
        {/* 칸을 펼쳐 두면 같은 사유를 칸 맨 위에서 알린다 — 여기서 또 보이면 두 번이었다 (EZ-11) */}
        {actions.gateError && !open && (
          <p role="alert" className="rounded-lg border border-cosmos-red/40 bg-cosmos-red/10 px-3 py-2 text-[14px] text-cosmos-red">
            {actions.gateError}
          </p>
        )}
        <DecisionBlock graph={graph} actions={actions} />
        {reviewStatus}
        <HumanReviewBlock graph={graph} decision={reviewDecision} onDecision={onReviewDecision} decisionHere />
      </section>

      {/* 2.4.0 ⑦ 공고문에 질문하기 — 실제 입찰 공고만 · 결정 뒤 맨 아래(판정 카드 첫 화면 · 단추 12 상한을 깨지 않는 자리) */}
      {origin.kind === "real" && (
        <section aria-label="공고문에 질문하기" className={SECTION} data-simple-chunk="notice-qa">
          <NoticeQaPanel key={notice.id} itemId={notice.id} kind="bid" />
        </section>
      )}
    </div>
  );
}
