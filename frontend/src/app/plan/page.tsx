"use client";

/**
 * 사업계획서 작성 — 공고마다 Claude · Codex CLI 로 초안을 쓰는 곳 (28차 §3-D · 29차 §3-A 「Codex 와 나란히」).
 *
 * - 지원사업(기업마당 → 사업계획서) · 입찰(나라장터 → 제안서 초안) 둘 다. 주소는 대시보드와 같은 키 `?support=` · `?notice=`.
 * - **AI 는 단추를 누를 때만** — 서버 전체 AI 는 꺼 둔 채 이 페이지 단추만 부른다(`use_claude` + `writer` · 서버 사업계획서 작성 문).
 * - 보내는 것은 서비스 허용 목록 그대로 — 사업계획서 `llm_payload()` · 입찰은 **승인된 회사자료 문단 중 유사도 기준으로 고른 근거 문장만**(합성은 시나리오 값).
 * - 쉬운 · 전체 보기 공통 한 화면. 내려받기는 DOCX 만(사업계획서 HWPX 는 담당자 결정으로 없앴다).
 */

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import AppShell from "@/components/ui/AppShell";
import AnnexFetch from "@/components/support/AnnexFetch";
import { DownloadLink } from "@/components/ui/DownloadLink";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { Badge, Button, EmptyState, InlineAlert, LoadingState, SectionHeader } from "@/components/ui/primitives";
import {
  CompanyFillLink,
  PlanBlanksList,
  PlanDownloadLinks,
  PlanDraftBody,
  PlanTaskPicker,
  planFormName,
  runLabel,
  sentenceCounts,
  useDraftBlockReason,
} from "@/components/support/SupportEvidencePanel";
import {
  ApiError,
  approveBidPlan,
  bidPlanExportUrl,
  bidPlanQualityReportUrl,
  checkBidPlanPdf,
  createBidPlan,
  createSupportPlanDraft,
  getAdoptedEvidence,
  getBidPlan,
  getBidPlanOutline,
  getBusinessOpportunities,
  getPlanWriterStatus,
  getProcurementNotice,
  getRfpRequirements,
  getSupportPlanDraft,
  getSupportProgram,
  listPlanDraftVersions,
  listPlanDrafts,
  parseRfpWithConsent,
  revokeBidPlanApproval,
  RFP_PARSE_PHASE_LABEL,
  type BidOutlinePreview,
  type BidPlanSection,
  type BidPlanTable,
  type BidPlanView,
  type BidQuality,
  type PlanDraftVersionMeta,
  type PlanWriterCliStatus,
  type PlanWriterName,
  type PlanWriterStatus,
  type RfpParsePhase,
  type SavedPlanDraft,
} from "@/lib/api";
import { NO_FORMAT_RULES, documentsLine, downloadVariants, entryLabel, draftOutlineLine, evaluationLine, formatLines, isBlindOnly, outlineFailureText, outlineLine, rejectedLine } from "@/lib/bidOutline";
import {
  APPROVAL_NOTE_MAX,
  DRAFT_FILE_TITLE,
  EVIDENCE_NOTE,
  PDF_CHECK_BLOCKED,
  PDF_CHECK_BUSY,
  PDF_CHECK_FAILED,
  PDF_CHECK_FINDINGS,
  PDF_CHECK_LABEL,
  PDF_CHECK_NOTE,
  REPORT_LINK_LABEL,
  REPORT_LINK_TITLE,
  REPORT_XLSX_LABEL,
  REPORT_XLSX_TITLE,
  STAFFING_UNCONFIRMED_LABEL,
  STAFFING_UNCONFIRMED_NOTE,
  approvalLine,
  approvalNote,
  approveBlockReason,
  axisLabel,
  blanksLine,
  checkedLine,
  countsLine,
  coverageOpen,
  coverageRows,
  coverageSummary,
  evidenceLines,
  findingAction,
  findingLine,
  generationView,
  hwpxCheckView,
  pdfCheckView,
  readinessChips,
  rewriteConsent,
  SEVERITY_VIEW,
  severityGroups,
  statusView,
  submitFileLabel,
} from "@/lib/bidQuality";
import { requestConsent } from "@/lib/consentPrompt";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import { DEMO_NOTICE, isDemoProcurementId, isParsableNoticeId } from "@/lib/cosmos/demoNotice";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { dDayText, deadlineTerm, effectiveDeadline, firstLabel, formatDeadlineStamp, isOpenEnded, pairOf, registrationClosesFirst } from "@/lib/deadline";
import { describeFailure, isConnectionCut, sourceFailure } from "@/lib/errors";
import { ARCHIVED_CLOSED_MARK } from "@/lib/supportSource";
import { analysisContext, useOrganizationId, useOrganizations } from "@/lib/organization";
import { usePeriodDays } from "@/lib/period";
import { NOTICE_CHANGE_EVENT, rememberSupport, requirementSheetHref, subscribeSelection, writeSelection } from "@/lib/selection";
import { verdictOf } from "@/lib/verdict";
import {
  AI_ADDED_SENTENCES,
  AI_DRAFT_CAUTION,
  BACK_TO_OPPORTUNITIES,
  GENERAL_GUIDE_NOTE,
  GUIDE_LINK_TEXT,
  OWNER_FILL_ITEMS,
  PLAN_NEXT_STEPS_TITLE,
  SCREEN_NAMES,
  STANDARD_FORM_BADGE,
  SUBMIT_DRAFT_NOTE,
  SYNTHETIC_NOTICE,
  planNextSteps,
} from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import type { PlanDraft, UnifiedOpportunity } from "@/types/opportunity";
import type { AnalysisContextParams } from "@/types/organization";

type Target = { kind: "support" | "notice"; id: string };

// 주소의 대상 — 지원사업이 먼저. 같은 주소면 같은 객체를 돌려준다(useSyncExternalStore 규칙).
let lastSearch: string | null = null;
let lastTarget: Target | null = null;
function readTarget(): Target | null {
  const search = window.location.search;
  if (search === lastSearch) return lastTarget;
  const q = new URLSearchParams(search);
  const support = q.get("support");
  const notice = q.get("notice");
  lastSearch = search;
  lastTarget = support ? { kind: "support", id: support } : notice ? { kind: "notice", id: notice } : null;
  return lastTarget;
}
const readTargetServer = (): Target | null => null;

/**
 * 「← 사업기회로」 주소 — 사업기회 행이 `from` 으로 실어 준 조건(탭 · 정렬 · 검색) 그대로 (37차 §3-E-3).
 * 주소 조각만 받는다(`?…`) — 다른 곳으로 가는 주소를 만들지 않는다. 없거나 모양이 다르면 그냥 `/opportunities`.
 */
function readBackHref(): string {
  const from = new URLSearchParams(window.location.search).get("from") ?? "";
  return /^\?[^#\s]*$/.test(from) ? `/opportunities${from}` : "/opportunities";
}
const readBackHrefServer = (): string => "/opportunities";

/** 대상 고르기 — 주소를 쓰고 알린다. 합성 데모도 주소에 남긴다(선택 저장소는 데모를 「선택 없음」으로 본다). */
function openTarget(target: Target | null): void {
  const url = new URL(window.location.href);
  url.searchParams.delete("support");
  url.searchParams.delete("notice");
  if (target) url.searchParams.set(target.kind, target.id);
  window.history.pushState(window.history.state, "", url.toString());
  if (target && !isDemoProcurementId(target.id)) writeSelection(target.id, "replace");
  window.dispatchEvent(new Event(NOTICE_CHANGE_EVENT));
  window.scrollTo({ top: 0 });
}

/**
 * 실제 마감 — 입찰 · 등록 · 공고문 일정 중 가장 이른 것(43차 결정 1 · 사업기회 행 · 대시보드 · 레이더와 같은 `pairOf`).
 * (2.0.6) 이 화면만 입찰 마감으로 세어 사업기회 「등록마감 D-9」이 여기서는 「입찰 마감 D-10」이었다.
 */
function realDeadline(item: UnifiedOpportunity | undefined): string | null {
  return item ? effectiveDeadline(pairOf(item, item.deadline)) : null;
}

/** (2.0.6) 고르기 후보 — 사업기회 기본 화면처럼 마감 · 불가 · 관련 낮음은 뺀다(머리 판정 · 마감을 늘 그리려고 목록은 모두 받는다). */
function isPickable(item: UnifiedOpportunity): boolean {
  return !item.closed && item.eligibility_gate !== "FAIL" && item.practical_group !== "비추천" && !item.relevance_note;
}

/** (2.0.6) 머리 마감 한 줄 — 사업기회 DeadlineLine 과 같은 규칙(앞자리 마감이 먼저면 그 이름 · D-day 는 실제 마감 · 입찰 마감은 옆에). */
function headDeadlineOf(item: UnifiedOpportunity, nowMs: number | null): { text: string; closed: boolean; bidLine: string | null } {
  const pair = pairOf(item, item.deadline);
  const real = effectiveDeadline(pair);
  const periodKind = item.apply_period_kind ?? null;
  const dDay = dDayText({ deadline: real, periodKind, nowMs });
  if (!item.closed && registrationClosesFirst(pair)) {
    return {
      text: dDay === "마감" ? `${firstLabel(pair)} 지남` : `${firstLabel(pair)} ${dDay}`,
      closed: false,
      bidLine: item.deadline ? `입찰 마감 ${formatDeadlineStamp(item.deadline)}` : null,
    };
  }
  const term = deadlineTerm({ source: item.source_type === "bizinfo" ? "bizinfo" : "g2b", closed: item.closed, periodKind, deadline: real });
  // (2.0.6) 상시 · 마감일 없음은 낱말 하나 — D-day 칸도 같은 말이라 「상시·예산 소진 시 상시·예산 소진 시」로 두 번 적혔다
  if (item.closed || isOpenEnded(periodKind) || !real) return { text: term, closed: item.closed, bidLine: null };
  return { text: `${term} ${dDay}`, closed: false, bidLine: null };
}

const CLOSED_BLOCK = "마감된 공고라 새 초안을 만들 수 없습니다 — 저장된 초안 보기 · 내려받기만 됩니다";
const INFO_LOADING_BLOCK = "공고 정보를 확인하는 중입니다";

function savedBadge(saved: SavedPlanDraft | undefined, failed = false): { label: string; tone: "info" | "muted" } {
  // (2.0.6) 저장본 목록을 못 읽었으면 「초안 없음」이라 단정하지 않는다 — 만든 초안을 다시 쓰게 했다
  if (!saved) return failed ? { label: "초안 확인 못 함", tone: "muted" } : { label: "초안 없음", tone: "muted" };
  const at = saved.executed_at ? new Date(saved.executed_at) : null;
  // 좁은 목록 칸이라 날짜만(시각은 초안 머리 「(9월 29일 만듦)」 · 판 목록에 있다) — 「9-29 14:10」은 날짜로 바로 읽히지 않았다(31차 §3-D).
  const when = at && !Number.isNaN(at.getTime()) ? ` ${at.getMonth() + 1}월 ${at.getDate()}일` : "";
  return saved.generated_by === "llm" ? { label: `AI 초안${when}`, tone: "info" } : { label: `기본 초안${when}`, tone: "muted" };
}

/** 사용 한도 문장인가 — CLI 가 「usage limit」 등을 돌려주면 백엔드가 한국어 사유로 바꾼다. */
function isUsageLimit(text: string | null | undefined): boolean {
  return !!text && /한도|limit/i.test(text);
}

// ---------------------------------------------------------------------------
// 연결 줄 — Claude · Codex (29차 §3-A)
// ---------------------------------------------------------------------------

const WRITERS: readonly { key: PlanWriterName; label: string; exe: string; login: string; training: string }[] = [
  {
    key: "claude",
    label: "Claude",
    exe: "Claude Code CLI(claude.exe)",
    login: "claude auth login",
    training: "Claude 개인 요금제입니다 — 학습 설정(claude.ai → 설정 → 개인정보 → 「Claude 개선에 도움 주기」)을 확인하세요.",
  },
  {
    key: "codex",
    label: "Codex",
    exe: "Codex CLI(codex.exe)",
    login: "codex login",
    training:
      "ChatGPT 로그인입니다 — 개인 요금제면 학습 설정(chatgpt.com → 설정 → 데이터 제어 → 「모두를 위한 모델 개선」)을 확인하세요. Codex 가 명령 · 파일 도구를 쓰려 하면 그 자리에서 멈추고 그 절은 규칙 내용으로 둡니다.",
  },
];

function writerOf(key: PlanWriterName) {
  return WRITERS.find((w) => w.key === key) ?? WRITERS[0];
}

/** 쓰는 이 하나의 상태 — Claude 는 맨 위 칸, Codex 는 `codex`(없는 서버면 「CLI 없음」). */
function writerStatus(status: PlanWriterStatus, key: PlanWriterName): PlanWriterCliStatus {
  if (key === "claude") return status;
  return status.codex ?? { ...status, cli: false, logged_in: false, model: "?", auth_method: null, subscription_type: null, training_reminder: false };
}

function WriterLine({ status, failed }: { status: PlanWriterStatus | null; failed: string | null }) {
  if (failed || !status || !status.enabled) {
    const text = failed ? `AI 연결 상태를 읽지 못했습니다 — ${failed}` : !status ? "AI 연결 상태를 읽는 중…" : status.off_reason ?? "이 서버에서는 사업계획서 작성(Claude · Codex)이 꺼져 있습니다";
    return (
      <p className={`text-[13px] leading-5 ${failed ? "text-cosmos-amber" : "text-cosmos-secondary"}`} role="status" data-plan-claude>
        {text}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1" data-plan-claude>
      {WRITERS.map((writer) => {
        const s = writerStatus(status, writer.key);
        const ok = s.enabled && s.cli && s.logged_in;
        // 42차 — 회사 서버는 Codex 를 끈다(서버가 사유를 준다 · 「프로그램이 없습니다」로 읽히지 않게)
        const text = !s.enabled
          ? `${writer.label} — ${s.off_reason ?? "이 서버에서는 꺼져 있습니다"}`
          : !s.cli
          ? `${writer.label} — 이 컴퓨터에 ${writer.label} 프로그램이 없습니다. 설치한 뒤 BidPilot 을 다시 켜세요(관리자에게 요청)`
          : !s.logged_in
            ? `${writer.label} — 로그인이 필요합니다. 관리자가 이 컴퓨터에서 로그인해 주세요(명령: ${writer.login})`
            : `${writer.label} 쓸 수 있음`;
        return (
          <div key={writer.key} className="flex flex-col" data-plan-writer={writer.key}>
            <p
              className={`text-[13px] leading-5 ${ok ? "text-cosmos-text" : "text-cosmos-amber"}`}
              role="status"
              title={ok ? `모델 ${s.model} · 로그인 ${s.auth_method ?? "?"}${s.subscription_type ? `(${s.subscription_type})` : ""}` : undefined}
            >
              {text}
            </p>
            {ok && s.training_reminder && <p className="text-[12.5px] leading-5 text-cosmos-muted">{writer.training}</p>}
          </div>
        );
      })}
      <p className="text-[12.5px] leading-5 text-cosmos-muted">
        AI 는 단추를 누를 때만 씁니다. 이 컴퓨터에 Claude · Codex 창이 따로 열려 있으면 실패할 수 있습니다. 실패하면 그 창을 닫고 다시 누르세요.
      </p>
    </div>
  );
}

/** 그 쓰는 이의 단추를 누를 수 없는 이유 (없으면 null). */
function writerBlock(status: PlanWriterStatus | null, key: PlanWriterName): string | null {
  const writer = writerOf(key);
  if (!status) return "AI 연결 상태를 읽는 중입니다";
  if (!status.enabled) return status.off_reason ?? "이 서버에서는 사업계획서 작성이 꺼져 있습니다";
  const s = writerStatus(status, key);
  if (!s.enabled) return s.off_reason ?? "이 서버에서는 꺼져 있습니다";
  if (!s.cli) return `${writer.exe}가 없습니다`;
  if (!s.logged_in) return `${writer.label} 에 로그인되어 있지 않습니다`;
  return null;
}

/** 저장본의 공급자 이름을 사람 말로. */
function providerLabel(provider: string | null | undefined): string {
  return provider === "claude_cli" ? "Claude" : provider === "codex_cli" ? "Codex" : provider ?? "?";
}

/** 쓰는 이 단추 둘 — 누를 수 없는 쪽은 비활성 + 이유. */
function WriterButtons({
  status,
  busy,
  elapsed,
  extraBlock,
  onWrite,
  evidenceCount,
}: {
  status: PlanWriterStatus | null;
  busy: string | null;
  elapsed: number;
  extraBlock: string | null;
  onWrite: (writer: PlanWriterName) => void;
  /** AI 에 가는 회사 근거 수(43차 결정 3) — 단추 옆에 「근거 n개」. 모르면 생략. */
  evidenceCount?: number | null;
}) {
  return (
    <>
      {evidenceCount != null && (
        <span className={`text-[12.5px] ${evidenceCount === 0 ? "text-cosmos-amber" : "text-cosmos-secondary"}`} data-plan-evidence-count>
          근거 {evidenceCount}개{evidenceCount === 0 ? " — 회사 근거 연결은 꺼 두었습니다. 원장 후보 실적에서 골라 채택하면 근거 문장이 됩니다" : ""}
        </span>
      )}
      {WRITERS.map((writer) => {
        const reason = extraBlock ?? writerBlock(status, writer.key);
        // 45차 M4 — 모든 단추에 같은 이유(열람자 · 마감 …)는 단추 줄 아래 한 번(PlanBlockLine) · 쓰는 쪽마다 다른 이유만 옆에
        const reasonId = extraBlock ? PLAN_BLOCK_ID : `plan-${writer.key}-reason`;
        return (
          <span key={writer.key} className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              onClick={() => onWrite(writer.key)}
              disabled={busy !== null || reason !== null}
              aria-busy={busy === writer.key}
              aria-describedby={reason ? reasonId : undefined}
              data-plan-claude-button={writer.key}
            >
              {busy === writer.key ? `${writer.label} 가 쓰는 중… ${elapsed}초 (최대 4분 30초)` : `${writer.label}로 쓰기`}
            </Button>
            {reason && !extraBlock && (
              <span id={reasonId} className="text-[12.5px] text-cosmos-muted">
                {writer.label}: {reason}
              </span>
            )}
          </span>
        );
      })}
    </>
  );
}

const PLAN_BLOCK_ID = "plan-block-reason";

/** 초안 단추가 모두 막힌 이유 한 줄(45차 M4 — 「AI 없이 기본 초안 만들기」는 이유 없이 흐리기만 했다). */
function PlanBlockLine({ reason, label = "초안 만들기 잠김" }: { reason: string | null; label?: string }) {
  if (!reason) return null;
  return (
    <p id={PLAN_BLOCK_ID} className="text-[12.5px] leading-5 text-cosmos-muted" data-plan-block>
      {label} — {reason}
    </p>
  );
}

function useElapsed(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) return;
    const begin = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - begin) / 1000)), 1000);
    return () => {
      window.clearInterval(timer);
      setElapsed(0);
    };
  }, [running]);
  return running ? elapsed : 0;
}

// ---------------------------------------------------------------------------
// 지원사업 — 사업계획서
// ---------------------------------------------------------------------------

/**
 * 내려받기 아래 「다음 할 일」(32차 §3-B-4) — 초안을 받은 뒤 할 일이 화면에 없었다. 접수처는 공고의 신청 방법(`apply_method`)을
 * 다시 쓴다(못 읽으면 일반 말). 일반 절차 안내 · 공고문이 우선.
 */
function PlanNextSteps({ programId, organizationId }: { programId: string; organizationId: string }) {
  const [place, setPlace] = useState<{ id: string; value: string | null } | null>(null);
  useEffect(() => {
    let alive = true;
    getSupportProgram(programId, organizationId)
      // 신청 방법은 여러 줄(접수처 · 이메일 …)이다 — 첫 줄만 쓴다(「이메일 또는 방문 접수」)
      .then((value) => alive && setPlace({ id: programId, value: value.program.apply_method?.split(/\r?\n/).map((s) => s.trim()).find(Boolean)?.slice(0, 60) ?? null }))
      .catch(() => alive && setPlace({ id: programId, value: null }));
    return () => {
      alive = false;
    };
  }, [programId, organizationId]);
  const steps = planNextSteps(place && place.id === programId ? place.value : null);
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-cosmos-border px-3 py-2.5" data-plan-next-steps>
      <p className="text-[13px] font-semibold text-cosmos-text">
        {PLAN_NEXT_STEPS_TITLE} <span className="font-normal text-cosmos-muted">({GENERAL_GUIDE_NOTE})</span>
      </p>
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-[13px] leading-5 text-cosmos-secondary">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="text-[12.5px]">
        <GuideContextLink href={GUIDE_LINKS.supportSubmit}>{GUIDE_LINK_TEXT.supportSubmit}</GuideContextLink>
      </p>
    </div>
  );
}

const CUT_NOTICE =
  "연결이 끊겼습니다 — 서버는 아직 쓰는 중일 수 있습니다. 같은 요청을 두 번 보내지 않도록 1분 동안 쓰기 단추를 막고, 1분 뒤 저장된 결과를 다시 읽습니다.";
const CUT_BLOCK = "연결이 끊겨 1분 뒤 저장된 결과를 다시 읽습니다(같은 요청을 두 번 보내지 않게)";

/**
 * 응답 전에 연결이 끊긴 뒤(44차 M2) — 중계 · nginx 가 먼저 끊어도 서버는 계속 써서 저장한다. 1분 동안 쓰기 단추를 막고(다시 누르면
 * 같은 요청이 두 번 돈다) 1분 뒤 저장된 초안을 다시 읽는다. 아직 쓰는 중이면 서버가 409 「쓰는 중」으로 막는다.
 */
function useCutRecovery(setNotice: (text: string | null) => void, setTick: (update: (n: number) => number) => void): [boolean, () => void] {
  const [waiting, setWaiting] = useState(false);
  const start = useCallback(() => {
    setWaiting(true);
    setNotice(CUT_NOTICE);
    window.setTimeout(() => {
      setWaiting(false);
      setTick((n) => n + 1);
    }, 60_000);
  }, [setNotice, setTick]);
  return [waiting, start];
}

function SupportWriter({
  programId,
  organizationId,
  status,
  onSaved,
  closedNote,
  infoLoading = false,
}: {
  programId: string;
  organizationId: string;
  status: PlanWriterStatus | null;
  onSaved: () => void;
  /** 목록에서 빠진 마감 사업 — 새 초안을 서버가 막는다. 단추 · 과제 고르기를 끄고 이 이유를 보인다(34차 R33-A3). */
  closedNote: string | null;
  /** 공고 정보(마감 여부)를 아직 읽는 중 — 그동안은 단추를 잠그고 그 이유를 적는다(45차 M1) */
  infoLoading?: boolean;
}) {
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const [loadNote, setLoadNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<PlanWriterName | "rules" | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pickedNo, setPickedNo] = useState<number | null>(null);
  const [versions, setVersions] = useState<PlanDraftVersionMeta[] | null>(null);
  const [tick, setTick] = useState(0);
  // 과제소개서 받기 단추가 보이는가 — 빈칸 목록의 「과제소개서 받기로 →」 링크를 그때만 그린다(31차 R30-36)
  const [annexFetchable, setAnnexFetchable] = useState(false);
  const elapsed = useElapsed((busy !== null && busy !== "rules") || (draft?.in_progress ?? false));
  const draftBlock = useDraftBlockReason();
  const closedBlock = closedNote ? CLOSED_BLOCK : null;
  const [cutWait, waitAndReread] = useCutRecovery(setNotice, setTick);
  const blockReason = closedBlock ?? (infoLoading ? INFO_LOADING_BLOCK : null) ?? (cutWait ? CUT_BLOCK : null) ?? draftBlock;

  useEffect(() => {
    let alive = true;
    getSupportPlanDraft(programId, organizationId)
      .then((saved) => {
        if (!alive) return;
        setDraft(saved);
        setLoadNote("");
      })
      .catch((error: unknown) => alive && setLoadNote(describeFailure(error)));
    listPlanDraftVersions(programId, organizationId)
      .then((value) => alive && setVersions(value.items))
      .catch(() => alive && setVersions([]));
    return () => {
      alive = false;
    };
  }, [programId, organizationId, tick]);

  // 새로고침해도 다른 창에서 만드는 중이면 기다린다 — 10초마다 다시 읽는다.
  useEffect(() => {
    if (!draft?.in_progress || busy) return;
    const timer = window.setTimeout(() => setTick((n) => n + 1), 10_000);
    return () => window.clearTimeout(timer);
  }, [draft?.in_progress, busy, tick]);

  const tasks = draft?.form?.tasks ?? [];
  const selectedNo = pickedNo ?? draft?.form?.selected_task?.no ?? null;
  const needsTask = tasks.length > 0 && selectedNo === null;
  const hasDraft = Boolean(draft && draft.sections.length > 0);
  const taskReason = needsTask ? "과제를 먼저 고르세요(AI 로 쓰는 것은 과제를 고른 뒤에만)" : null;

  // 규칙 초안 단추는 no_ai — 서버 AI 가 켜져 있어도 부르지 않는다(29차 R28-01).
  const generate = async (body: { use_claude?: boolean; writer?: PlanWriterName; force_rules?: boolean; no_ai?: boolean }) => {
    setBusy(body.use_claude ? body.writer ?? "claude" : "rules");
    setFailure(null);
    setNotice(null);
    try {
      setDraft(await createSupportPlanDraft(programId, organizationId, { task_no: selectedNo ?? undefined, ...body }));
      setPickedNo(null);
      setTick((n) => n + 1);
      onSaved();
    } catch (error: unknown) {
      // 409 중 마감 사본은 기다려도 안 풀린다 — 「바쁨 — 1분 뒤」가 아니라 실패(34차 R33-A3)
      if (error instanceof ApiError && error.status === 409 && !error.detail?.startsWith(ARCHIVED_CLOSED_MARK)) {
        setNotice(`${describeFailure(error)} — 1분 뒤 다시 읽습니다.`);
        window.setTimeout(() => setTick((n) => n + 1), 60_000);
      } else if (body.use_claude && isConnectionCut(error)) {
        waitAndReread();
      } else setFailure(describeFailure(error));
    } finally {
      setBusy(null);
    }
  };

  const switchToRules = async () => {
    const ok = await requestConsent({
      title: "기본 초안으로 바꿀까요?",
      body: `지금 보이는 AI 초안 대신 기본 초안(AI 미사용 · ${planFormName(draft)} 목차)을 만듭니다. AI 초안은 이전 판으로 남습니다.`,
      confirmLabel: "기본 초안으로 바꾸기",
    });
    if (ok) void generate({ force_rules: true, no_ai: true });
  };

  const limited = isUsageLimit(failure) || isUsageLimit(draft?.kept_reason) || isUsageLimit(draft?.llm_note);
  const counts = draft ? sentenceCounts(draft) : null;

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-label="사업계획서 초안">
      <SectionHeader as="h2" title={`사업계획서 초안 — ${planFormName(draft)} 순서`} description="공고 양식 · 공고문 조항 · 회사 사실로만 씁니다. 근거가 없는 내용은 채우지 않고 「(담당자 입력)」으로 남깁니다. 최종 신청은 담당자가 합니다." />
      {draft?.form?.notice && <InlineAlert tone="warn" role="status">{draft.form.notice}</InlineAlert>}
      {loadNote === null && <LoadingState label="저장된 초안을 불러오는 중" rows={3} />}
      {loadNote && <InlineAlert tone="warn" role="status">저장된 초안을 읽지 못했습니다 — {loadNote}</InlineAlert>}
      {/* 과제소개서 받기(30차 §3-A) — 과제소개서 첨부가 있는 공고에서만 · 받은 뒤 과제 목록의 기준요건 줄을 다시 읽는다 */}
      <AnnexFetch programId={programId} onFetched={() => setTick((n) => n + 1)} onFetchable={setAnnexFetchable} />

      {tasks.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-[13px] font-semibold text-cosmos-text">협업 과제 {tasks.length}개 — {selectedNo ? `${selectedNo}번을 골랐습니다` : "하나를 고르세요"}</p>
          <PlanTaskPicker tasks={tasks} selectedNo={selectedNo} busy={busy !== null || closedBlock !== null} onPick={setPickedNo} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <WriterButtons status={status} busy={busy} elapsed={elapsed} extraBlock={blockReason ?? taskReason} onWrite={(writer) => void generate({ use_claude: true, writer })} />
        <Button variant="secondary" onClick={() => void generate({ no_ai: true })} disabled={busy !== null || blockReason !== null} aria-busy={busy === "rules"} aria-describedby={blockReason ? PLAN_BLOCK_ID : undefined} data-plan-rules-button>
          {busy === "rules" ? "기본 초안 만드는 중…" : "AI 없이 기본 초안 만들기"}
        </Button>
      </div>
      {!closedBlock && <PlanBlockLine reason={blockReason ?? taskReason} label={blockReason ? undefined : "Claude · Codex"} />}
      {closedBlock && (
        <p className="text-[12.5px] leading-5 text-cosmos-amber" role="status" data-plan-closed>
          {closedBlock}
        </p>
      )}
      <p className="text-[12.5px] leading-5 text-cosmos-secondary" data-plan-ai-caution>
        {AI_DRAFT_CAUTION} <GuideContextLink href={GUIDE_LINKS.aiDraft}>{GUIDE_LINK_TEXT.aiDraft}</GuideContextLink>
      </p>
      {draft?.in_progress && !busy && <InlineAlert tone="info" role="status">다른 창에서 이 공고의 초안을 만드는 중입니다 — 끝나면 저절로 다시 읽습니다({elapsed}초).</InlineAlert>}
      {limited && <InlineAlert tone="warn" role="status">사용 한도 — AI 사용 한도에 걸렸습니다. 몇 시간 뒤 다시 누르거나 다른 쪽(Claude · Codex)으로 쓰세요. 실패한 절은 규칙 내용으로 남고, 있던 AI 초안은 그대로입니다.</InlineAlert>}
      {notice && <InlineAlert tone="info" role="status">{notice}</InlineAlert>}
      {failure && <InlineAlert tone="fail" role="status">초안을 만들지 못했습니다 — {failure}</InlineAlert>}

      {hasDraft && draft && (
        <div className="flex flex-wrap items-center gap-2 border-t border-cosmos-border pt-3">
          <Badge tone={draft.generated_by === "llm" ? "info" : "muted"}>
            {draft.generated_by === "llm" ? "AI 초안" : "기본 초안"}
            {runLabel(draft.executed_at)}
          </Badge>
          {draft.form?.source === "standard" && <Badge tone="warn">{STANDARD_FORM_BADGE}</Badge>}
          {draft.generated_by === "llm" && draft.model && <span className="text-[12px] text-cosmos-muted">{providerLabel(draft.provider)} · {draft.model}</span>}
          {counts && <span className="text-[12px] text-cosmos-muted">문장 {counts.body}개 · {AI_ADDED_SENTENCES} {draft.ai_sentence_count ?? 0}개(확인 필요)</span>}
          <PlanDownloadLinks programId={programId} organizationId={organizationId} blanks={draft.submit_blanks} />
          <span className="text-[12px] text-cosmos-muted">{SUBMIT_DRAFT_NOTE}</span>
          <CompanyFillLink draft={draft} />
        </div>
      )}
      {hasDraft && <PlanNextSteps programId={programId} organizationId={organizationId} />}
      {draft?.kept_llm_draft && (
        <p className="text-[12.5px] leading-5 text-cosmos-amber">
          AI 초안({providerLabel(draft.provider)}{runLabel(draft.executed_at)})을 유지합니다 — 새 AI 초안 없음: {draft.kept_reason ?? "AI 꺼짐"}.{" "}
          <button type="button" onClick={() => void switchToRules()} className="mc-focus rounded underline underline-offset-2">
            기본 초안으로 바꾸기
          </button>
        </p>
      )}
      {draft && hasDraft && <PlanDraftBody draft={draft} annexFetchable={annexFetchable} />}
      {/* 마감으로 단추가 잠겼으면 「위 단추로 만듭니다」라 하지 않는다(2.0.6 실측 — 잠긴 단추 아래에서 쓰라고 안내했다) */}
      {loadNote === "" && !hasDraft && (
        <EmptyState title="아직 만든 초안이 없습니다">
          {closedBlock ? "마감된 공고라 새로 만들 수 없습니다." : "위 단추로 만듭니다 — Claude · Codex 로 쓰거나(켜져 있을 때) AI 없이 기본 초안을 만듭니다."}
        </EmptyState>
      )}

      {versions && versions.length > 0 && (
        <details className="border-t border-cosmos-border pt-2" data-plan-versions>
          <summary className="mc-focus w-fit cursor-pointer rounded py-1 text-[12.5px] text-cosmos-secondary">이전 판 {versions.length}개 ▸</summary>
          <ul className="mt-1 flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
            {versions.map((version) => (
              <li key={version.name}>
                {version.generated_by === "llm" ? "AI 초안" : "기본 초안"}
                {runLabel(version.executed_at ?? undefined)}
                {version.kept_rules ? " · 저장하지 않은 기본 초안 결과" : ""} · {OWNER_FILL_ITEMS} {version.blanks}개{version.ai_sentences ? ` · ${AI_ADDED_SENTENCES} ${version.ai_sentences}개` : ""}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[12px] text-cosmos-muted">읽기 전용 기록입니다 — 되살리기는 없습니다.</p>
        </details>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 입찰 — 제안서 초안
// ---------------------------------------------------------------------------

/**
 * 제안서 작성 순서(2.1.2 · 대표 10-30 「흐름을 모르겠다」) — 지금 단계를 「지금」 글자로도 적는다(색만으로 전하지 않음).
 * 회사 근거는 점검 대상 요구사항에 맞춰 자동으로 고르므로 따로 할 단계가 없다.
 */
const BID_STEPS = ["공고 분석 — 요구사항 뽑기", "초안 쓰기 — Claude · Codex", "워드 · 한글 파일 받기"] as const;

/** `current` 가 null 이면 아직 모른다(요구사항이 있는지 읽는 중) — 어느 단계도 「끝남 · 지금」으로 적지 않는다(10-31 최종 점검). */
function BidSteps({ current }: { current: 1 | 2 | 3 | null }) {
  return (
    <ol aria-label="제안서 작성 순서" data-plan-steps className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
      {BID_STEPS.map((label, index) => {
        const step = index + 1;
        const done = current !== null && step < current;
        const now = step === current;
        return (
          <li key={label} aria-current={now ? "step" : undefined} className={`flex items-center gap-1.5 ${now ? "font-semibold text-cosmos-text" : done ? "text-cosmos-secondary" : "text-cosmos-muted"}`}>
            <span aria-hidden="true">{done ? "✓" : `${step}`}</span>
            {label}
            {now && <span className="rounded border border-cosmos-cyan/50 px-1 text-[11.5px] font-medium text-cosmos-cyan">지금</span>}
            {done && <span className="sr-only">(끝남)</span>}
            {step < BID_STEPS.length && <span aria-hidden="true" className="text-cosmos-muted">→</span>}
          </li>
        );
      })}
    </ol>
  );
}

/** 「이 제안서 양식」(11-06 B-2) — 쓰기 전에 원문이 정한 목차 · 평가표 · 형식 규정을 보인다. 처음 펼칠 때만 읽는다(읽기만 · 열람자도). */
function BidOutlinePanel({ noticeId, ctx, saved }: { noticeId: string; ctx: AnalysisContextParams; saved?: BidPlanView["format"] }) {
  const [opened, setOpened] = useState(false);
  return (
    <details className="group border-t border-cosmos-border pt-2" data-bid-outline-panel onToggle={(event) => event.currentTarget.open && setOpened(true)}>
      <summary className="mc-focus w-fit cursor-pointer list-none rounded py-1 text-[13px] font-semibold text-cosmos-text hover:text-cosmos-cyan">
        이 제안서 양식 <span aria-hidden="true" className="group-open:hidden">▸</span>
        <span aria-hidden="true" className="hidden group-open:inline">▾</span>
      </summary>
      {opened && <BidOutlineBody noticeId={noticeId} ctx={ctx} saved={saved} />}
    </details>
  );
}

function BidOutlineBody({ noticeId, ctx, saved }: { noticeId: string; ctx: AnalysisContextParams; saved?: BidPlanView["format"] }) {
  const [preview, setPreview] = useState<BidOutlinePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    getBidPlanOutline(noticeId, ctx).then(
      (value) => alive && setPreview(value),
      (failure: unknown) => alive && setError(outlineFailureText(failure)),
    );
    return () => {
      alive = false;
    };
  }, [noticeId, ctx, reload]);

  if (error) {
    return (
      <div className="flex flex-col items-start gap-2 pt-1">
        <InlineAlert tone="warn" role="status">{error}</InlineAlert>
        <Button
          variant="secondary"
          onClick={() => {
            setError(null);
            setReload((n) => n + 1);
          }}
        >
          다시 읽기
        </Button>
      </div>
    );
  }
  if (!preview) return <p role="status" className="pt-1 text-[12.5px] text-cosmos-muted">원문에서 제안서 양식을 읽는 중…</p>;
  const outline = outlineLine(preview);
  const evaluation = evaluationLine(preview.evaluation);
  const rules = formatLines(preview.format, saved); // 내려받는 파일은 저장 초안 형식 — 2.11.0 전 초안이면 그 말을 붙인다
  const auto = rules.filter((line) => !line.manual);
  const manual = rules.filter((line) => line.manual);
  const tone = (warn: boolean) => (warn ? "text-cosmos-amber" : "text-cosmos-text");
  return (
    <div className="flex flex-col gap-2 pt-1 text-[12.5px] leading-5" data-bid-outline-preview>
      {preview.warnings.map((warning, i) => (
        <InlineAlert key={`${i}-${warning}`} tone="warn" role="status">{warning}</InlineAlert>
      ))}
      <p className={tone(outline.warn)} data-bid-outline-line>{outline.text}</p>
      <ol className="flex flex-col gap-1 pl-1 text-cosmos-secondary">
        {preview.outline.map((major, m) => (
          <li key={`${m}-${major.title}`}>
            <span className="font-medium text-cosmos-text">{entryLabel(major.no, major.title)}</span>
            {(major.items ?? []).length > 0 && (
              <ol className="flex flex-wrap gap-x-3 pl-4">
                {major.items.map((item, i) => (
                  <li key={`${i}-${item.title}`}>{entryLabel(item.no, item.title)}</li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ol>
      {preview.outline_rejected.length > 0 && (
        <div className="text-cosmos-muted" data-bid-outline-rejected>
          제안서 목차가 아니라고 보고 쓰지 않은 것:
          <ul className="pl-4">
            {preview.outline_rejected.map((rejected, i) => (
              <li key={`${i}-${rejected.head}`}>{rejectedLine(rejected)}</li>
            ))}
          </ul>
        </div>
      )}
      <p className={tone(evaluation.warn)} data-bid-evaluation-line>{evaluation.text}</p>
      {rules.length === 0 && <p className="text-cosmos-muted">{NO_FORMAT_RULES}</p>}
      {auto.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-cosmos-text" data-bid-format-auto>
          {auto.map((line) => (
            <li key={line.text}>{line.text}</li>
          ))}
        </ul>
      )}
      {manual.length > 0 && (
        <div className="text-cosmos-amber" data-bid-format-manual>
          직접 맞춰야 할 것:
          <ul className="pl-4">
            {manual.map((line) => (
              <li key={line.text}>{line.text}</li>
            ))}
          </ul>
        </div>
      )}
      {preview.documents.length > 0 && (
        <p className="text-[12px] text-cosmos-muted">
          {documentsLine(preview.documents)}
        </p>
      )}
    </div>
  );
}

const APPROVE_BLOCK_ID = "bid-approve-block";
const PDF_BLOCK_ID = "bid-pdf-check-block";

/**
 * 품질 게이트(2.7.0 · 계획 12번 · 2.8.0 넓힘) — 제출 상태 · 검사 시각 · 미작성 칸 수 · 한글 파일 검사 · 심각도별 항목(위치 · 고치는 법) ·
 * 평가항목 대응표 · 근거 상태 · 「인력 미확정」 · 승인(메모 선택). 값은 서버 계산 그대로(`lib/bidQuality` 가 낱말로만 옮김) · 2.8.0 칸이 없는 옛 응답은 그 줄을 그리지 않는다.
 * 승인은 편집자 이상 · 차단이 남으면 잠금(서버도 409) · 승인됨이면 누가 언제 + 취소. 내려받기는 막지 않는다(이름만 「초안」).
 */
function BidQualityPanel({
  quality,
  reportUrl,
  workbookUrl,
  roleBlock,
  busy,
  failure,
  onDecide,
  pdfBlock,
  pdfBusy,
  pdfFailure,
  onCheckPdf,
}: {
  quality: BidQuality;
  /** 검증 보고서(JSON) 내려받기 주소 — 열람자도 받는다 */
  reportUrl: string;
  /** (2.10.0 T8) 검사 보고서 엑셀(세 시트) — 열람자도 받는다 */
  workbookUrl: string;
  /** 열람자 · 읽기 전용 배포 · 쓰는 중 — 승인 · 취소 둘 다 잠근다 */
  roleBlock: string | null;
  busy: boolean;
  failure: string | null;
  onDecide: (approve: boolean, note?: string) => void;
  /** (2.10.0 T8) 한글에서 저장한 PDF 검사 — 열람자 · 읽기 전용 배포면 잠금 */
  pdfBlock: string | null;
  pdfBusy: boolean;
  pdfFailure: string | null;
  onCheckPdf: (file: File) => void;
}) {
  const view = statusView(quality);
  const generation = generationView(quality);
  const chips = readinessChips(quality);
  const groups = severityGroups(quality);
  const approval = quality.approval;
  const block = approval ? roleBlock : approveBlockReason(quality, roleBlock);
  const [note, setNote] = useState("");
  const checked = checkedLine(quality);
  const blanks = blanksLine(quality);
  const hwpx = hwpxCheckView(quality.hwpx_check);
  const pdf = pdfCheckView(quality.pdf_check);
  const pdfRef = useRef<HTMLInputElement>(null);
  const coverage = coverageRows(quality);
  const evidence = evidenceLines(quality.evidence_status);
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-cosmos-border px-3 py-2.5" data-bid-quality={quality.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold text-cosmos-text">제출 상태</span>
        <Badge tone={view.tone} glyph={view.glyph} size="md">
          {view.label}
        </Badge>
        {quality.staffing_unconfirmed && (
          <Badge tone="warn" glyph="!">
            {STAFFING_UNCONFIRMED_LABEL}
          </Badge>
        )}
        <span className="text-[12px] text-cosmos-muted">{countsLine(quality)}</span>
      </div>
      <p className="text-[12.5px] leading-5 text-cosmos-secondary">{view.note}</p>
      {/* 2.9.0 — 자동 작성 검사(앱이 고칠 것만)는 제출 상태와 다른 축 · 여섯 상태 칸(3차 지시서 §9 · §12) */}
      {generation && (
        <div className="flex flex-wrap items-center gap-2" data-bid-generation={quality.generation?.status}>
          <span className="text-[13px] font-semibold text-cosmos-text">자동 작성 검사</span>
          <Badge tone={generation.tone} glyph={generation.glyph} size="md">
            {generation.label}
          </Badge>
          <span className="text-[12px] text-cosmos-muted">{generation.note}</span>
        </div>
      )}
      {chips.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="제안서 상태" data-bid-readiness>
          {chips.map((chip) => (
            <li key={chip.key} data-bid-readiness-chip={chip.key} data-active={chip.active ? "1" : "0"}>
              <Badge tone={chip.tone} glyph={chip.glyph}>
                {chip.label}
                {chip.count !== null ? ` ${chip.count}` : ""}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {quality.staffing_unconfirmed && <p className="text-[12px] leading-5 text-cosmos-amber" data-bid-staffing>{STAFFING_UNCONFIRMED_NOTE}</p>}
      {/* 2.8.0 F1 — 언제 · 어느 규칙으로 검사했나 · 미작성 칸 수 · 마지막 한글 파일 검사 · 검증 보고서 */}
      {(checked || blanks) && (
        <p className="text-[12px] leading-5 text-cosmos-muted" data-bid-quality-checked>
          {[checked, blanks].filter(Boolean).join(" · ")}
        </p>
      )}
      {hwpx && (
        <p className={`text-[12px] leading-5 ${hwpx.state === "differ" ? "text-cosmos-amber" : "text-cosmos-secondary"}`} data-bid-hwpx-check={hwpx.state}>
          <span aria-hidden="true">{hwpx.glyph} </span>
          {hwpx.text}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <DownloadLink
          href={reportUrl}
          fallbackName="제안서_검증보고서.json"
          className="mc-focus inline-flex min-h-8 items-center rounded-lg border border-cosmos-border-strong px-2.5 text-[12px] font-medium text-cosmos-text hover:border-cosmos-cyan/60"
          title={REPORT_LINK_TITLE}
        >
          {REPORT_LINK_LABEL}
        </DownloadLink>
        <DownloadLink
          href={workbookUrl}
          fallbackName="제안서_검증보고서.xlsx"
          className="mc-focus inline-flex min-h-8 items-center rounded-lg border border-cosmos-border-strong px-2.5 text-[12px] font-medium text-cosmos-text hover:border-cosmos-cyan/60"
          title={REPORT_XLSX_TITLE}
        >
          {REPORT_XLSX_LABEL}
        </DownloadLink>
        {/* 2.10.0 T8 — 사람이 한글에서 고쳐 저장한 최종 PDF 를 올려 검사(판정 · 승인은 그대로 · D10) */}
        <Button
          variant="secondary"
          onClick={() => pdfRef.current?.click()}
          disabled={pdfBusy || pdfBlock !== null}
          aria-busy={pdfBusy}
          aria-describedby={pdfBlock ? PDF_BLOCK_ID : undefined}
          title={PDF_CHECK_NOTE}
          data-bid-pdf-check>
          {pdfBusy ? PDF_CHECK_BUSY : PDF_CHECK_LABEL}
        </Button>
        <input
          ref={pdfRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) onCheckPdf(file);
          }}
        />
      </div>
      {pdfBlock && (
        <p id={PDF_BLOCK_ID} className="text-[12px] leading-5 text-cosmos-muted" data-bid-pdf-block>
          {PDF_CHECK_BLOCKED} — {pdfBlock}
        </p>
      )}
      {pdf && (
        <p className={`text-[12px] leading-5 ${pdf.state === "issues" || pdf.state === "unreadable" ? "text-cosmos-amber" : "text-cosmos-secondary"}`} data-bid-pdf-check-state={pdf.state}>
          <span aria-hidden="true">{pdf.glyph} </span>
          {pdf.text}
        </p>
      )}
      {quality.pdf_check && quality.pdf_check.findings.length > 0 && (
        <details open={pdf?.state !== "ok"} data-bid-pdf-findings>
          <summary className="mc-focus w-fit cursor-pointer rounded py-0.5 text-[12.5px] text-cosmos-text">
            {PDF_CHECK_FINDINGS} {quality.pdf_check.findings.length}건 ▸
          </summary>
          <ul className="mt-1 flex flex-col gap-1 pl-2 text-[12px] leading-5 text-cosmos-secondary">
            {quality.pdf_check.findings.map((finding, index) => {
              const action = findingAction(finding);
              return (
                <li key={`${finding.code}-${index}`} className="min-w-0 break-words">
                  <Badge tone={SEVERITY_VIEW[finding.severity]?.tone ?? "muted"} glyph={SEVERITY_VIEW[finding.severity]?.glyph ?? "○"}>
                    {SEVERITY_VIEW[finding.severity]?.label ?? finding.severity}
                  </Badge>{" "}
                  {findingLine(finding)}
                  {finding.detail && <span className="block text-cosmos-muted">{finding.detail}</span>}
                  {action && <span className="block text-cosmos-text">{action}</span>}
                </li>
              );
            })}
          </ul>
        </details>
      )}
      {pdfFailure && (
        <InlineAlert tone="fail" role="status">
          {PDF_CHECK_FAILED} — {pdfFailure}
        </InlineAlert>
      )}
      {groups.map((group) => (
        <details key={group.severity} open={group.open} data-bid-quality-group={group.severity}>
          <summary className="mc-focus flex w-fit cursor-pointer items-center gap-1.5 rounded py-0.5 text-[12.5px] text-cosmos-text">
            <Badge tone={group.tone} glyph={group.glyph}>
              {group.label}
            </Badge>
            {group.total}건 ▸
          </summary>
          <ul className="mt-1 flex flex-col gap-1 pl-2 text-[12px] leading-5 text-cosmos-secondary">
            {group.items.map((finding, index) => {
              const action = findingAction(finding);
              const axis = axisLabel(finding);
              return (
                <li key={`${finding.code}-${index}`} className="min-w-0 break-words" data-bid-finding-axis={finding.axis}>
                  {axis && <span className="text-cosmos-muted">[{axis}] </span>}
                  {findingLine(finding)}
                  {finding.detail && <span className="block text-cosmos-muted">{finding.detail}</span>}
                  {action && (
                    <span className="block text-cosmos-text" data-bid-finding-action>
                      {action}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
      ))}
      {/* 2.8.0 F2 — 평가항목 대응표(조견표 「제안서 해당 목차」와 그 본문) · 기본 접힘 · 「목차 없음」이 있을 때만 펼침 */}
      {coverage.length > 0 && (
        <details open={coverageOpen(quality)} data-bid-coverage>
          <summary className="mc-focus w-fit cursor-pointer rounded py-0.5 text-[12.5px] text-cosmos-text">
            평가항목 대응표 — {coverageSummary(quality)} ▸
          </summary>
          <div className="mt-1 overflow-x-auto">
            <table className="min-w-full border-collapse text-[12px]" aria-label="평가항목 대응표">
              <thead>
                <tr>
                  {["평가 항목", "배점", "제안서 해당 목차", "본문", "상태"].map((column) => (
                    <th key={column} scope="col" className="border border-cosmos-border px-2 py-1 text-left font-medium text-cosmos-muted">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {coverage.map((row) => (
                  <tr key={row.key} data-bid-coverage-row={row.status.label}>
                    <td className="border border-cosmos-border px-2 py-1 text-cosmos-secondary">
                      {row.name}
                      {row.kind && <span className="text-cosmos-muted"> ({row.kind})</span>}
                    </td>
                    <td className="whitespace-nowrap border border-cosmos-border px-2 py-1 text-cosmos-secondary">{row.points}</td>
                    <td className="border border-cosmos-border px-2 py-1 text-cosmos-secondary">
                      {row.mapped}
                      {row.source && <span className="block text-[11.5px] text-cosmos-muted">{row.source}</span>}
                    </td>
                    <td className="border border-cosmos-border px-2 py-1 text-cosmos-secondary">{row.body}</td>
                    <td className="border border-cosmos-border px-2 py-1">
                      <Badge tone={row.status.tone} glyph={row.status.glyph}>
                        {row.status.label}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      {/* 2.8.0 F2 — 초안이 인용한 회사 근거의 상태(지금 회사 칸으로만 · 증빙 확인 칸은 아직 없음) */}
      {evidence.length > 0 && (
        <div className="flex flex-col gap-0.5 text-[12px] leading-5" data-bid-evidence-status>
          <span className="font-medium text-cosmos-text">근거 상태</span>
          <ul className="flex flex-col gap-0.5 pl-2">
            {evidence.map((line, index) => (
              <li key={`${index}-${line.text}`} className={line.warn ? "text-cosmos-amber" : "text-cosmos-secondary"}>
                <span aria-hidden="true">{line.warn ? "! " : "· "}</span>
                {line.text}
              </li>
            ))}
          </ul>
          <span className="text-cosmos-muted">{EVIDENCE_NOTE}</span>
          <Link href="/company" className="mc-focus w-fit rounded font-medium text-cosmos-cyan hover:underline" data-bid-evidence-company>
            회사자료에서 실적 · 인증 확인 →
          </Link>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-cosmos-border pt-2" data-bid-approval={approval ? "approved" : "none"}>
        {approval ? (
          <>
            <span className="text-[12.5px] text-cosmos-text">
              ✓ {approvalLine(approval)}
              {approval.note ? <span className="text-cosmos-muted"> — {approval.note}</span> : null}
            </span>
            <Button variant="secondary" onClick={() => onDecide(false)} disabled={busy || block !== null} aria-busy={busy} aria-describedby={block ? APPROVE_BLOCK_ID : undefined} data-bid-revoke>
              {busy ? "승인 취소하는 중…" : "승인 취소"}
            </Button>
          </>
        ) : (
          <>
            {/* 2.8.0 F3 — 승인 메모(선택 · 200자) · 승인 줄 옆에 남는다 */}
            <label className="flex min-w-0 flex-1 basis-56 items-center gap-1.5 text-[12px] text-cosmos-muted">
              메모(선택)
              <input
                type="text"
                value={note}
                maxLength={APPROVAL_NOTE_MAX}
                onChange={(event) => setNote(event.target.value)}
                disabled={busy || block !== null}
                placeholder="예: 인력 칸은 한글 파일에서 채움"
                className="mc-focus min-h-9 min-w-0 flex-1 rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[12.5px] text-cosmos-text placeholder:text-cosmos-muted disabled:opacity-60"
                data-bid-approve-note
              />
            </label>
            <Button variant="primary" onClick={() => onDecide(true, approvalNote(note))} disabled={busy || block !== null} aria-busy={busy} aria-describedby={block ? APPROVE_BLOCK_ID : undefined} data-bid-approve>
              {busy ? "승인하는 중…" : "읽고 확인했습니다 — 승인"}
            </Button>
          </>
        )}
      </div>
      {block && (
        <p id={APPROVE_BLOCK_ID} className="text-[12.5px] leading-5 text-cosmos-muted" data-bid-approve-block>
          {approval ? "승인 취소 잠김" : "승인 잠김"} — {block}
        </p>
      )}
      {failure && (
        <InlineAlert tone="fail" role="status">
          승인을 바꾸지 못했습니다 — {failure}
        </InlineAlert>
      )}
    </div>
  );
}

function BidWriter({
  noticeId,
  organizationId,
  status,
  onSaved,
  closed = false,
  infoLoading = false,
}: {
  noticeId: string;
  organizationId: string;
  status: PlanWriterStatus | null;
  onSaved: () => void;
  /** (2.0.6) 마감된 입찰 — 지원사업 closedBlock 과 같이 새 초안 단추만 잠근다(저장된 초안 보기 · 내려받기는 그대로) */
  closed?: boolean;
  /** (2.0.6) 목록을 다 받기 전엔 마감 여부를 모른다 — 지원사업(45차 M1)처럼 그동안 잠근다. 마감된 입찰도 한 번 누르면 바로 AI 초안이 나갔다 */
  infoLoading?: boolean;
}) {
  const ctx = useMemo(() => analysisContext(noticeId, organizationId), [noticeId, organizationId]);
  const [adopted, setAdopted] = useState<{ adopted: number; mandatory: number } | null>(null);
  const [notParsed, setNotParsed] = useState<string | null>(null);
  const [countFailed, setCountFailed] = useState<string | null>(null);
  const [doc, setDoc] = useState<BidPlanView | null>(null);
  // 11-03 — 분석 원문이 공고서뿐(notice)이면 제안서를 쓰지 않는다 · 「제안요청서로 다시 분석」(사전규격 제안요청서를 받는다)
  const [rfpRole, setRfpRole] = useState<"rfp" | "notice" | null>(null);
  // (2.0.6) 404 가 아닌 실패 — 「초안 없음」으로 보여 이미 만든 AI 초안을 다시 쓰게 했다
  const [docFailed, setDocFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState<PlanWriterName | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const elapsed = useElapsed(busy !== null);
  const draftBlock = useDraftBlockReason();
  const [cutWait, waitAndReread] = useCutRecovery(setNotice, setTick);
  const closedBlock = closed ? CLOSED_BLOCK : null;
  // 2.7.0 승인 — 열람자는 기존 잠금 글(「열람자 — 보기만」) · 읽기 전용 배포 · 쓰는 중이면 잠금(누르면 초안이 바뀐다)
  const viewer = useViewerLock();
  const [approving, setApproving] = useState(false);
  const [approveFailure, setApproveFailure] = useState<string | null>(null);
  const approveRoleBlock = viewer
    ? `${VIEWER_LOCK_LABEL} — ${VIEWER_LOCK_REASON}`
    : (draftBlock ? draftBlock.replace("초안을 만들 수 없습니다", "승인할 수 없습니다") : null) ?? (busy !== null ? "초안을 쓰는 중입니다" : null);
  // 2.10.0 T8 — 한글에서 저장한 PDF 검사(편집자 이상 · 서버도 403) · 결과는 품질 패널의 pdf_check 로(판정 · 승인은 그대로)
  const [checkingPdf, setCheckingPdf] = useState(false);
  const [pdfFailure, setPdfFailure] = useState<string | null>(null);
  const pdfBlock = viewer
    ? `${VIEWER_LOCK_LABEL} — ${VIEWER_LOCK_REASON}`
    : draftBlock ? draftBlock.replace("초안을 만들 수 없습니다", "PDF 를 검사할 수 없습니다") : null;
  const checkPdf = async (file: File) => {
    setCheckingPdf(true);
    setPdfFailure(null);
    try {
      const result = await checkBidPlanPdf(noticeId, file, ctx);
      setDoc((current) => (current?.quality ? { ...current, quality: { ...current.quality, pdf_check: result } } : current));
    } catch (error: unknown) {
      setPdfFailure(describeFailure(error));
    } finally {
      setCheckingPdf(false);
    }
  };
  const decide = async (approve: boolean, note?: string) => {
    setApproving(true);
    setApproveFailure(null);
    try {
      const quality = await (approve ? approveBidPlan(noticeId, ctx, doc?.quality?.draft_hash, note) : revokeBidPlanApproval(noticeId, ctx));
      setDoc((current) => (current ? { ...current, quality } : current));
    } catch (error: unknown) {
      setApproveFailure(describeFailure(error));
      // 409(차단이 남음) · 404(초안 없음) — 서버가 본 지금 초안으로 다시 읽는다
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) setTick((n) => n + 1);
    } finally {
      setApproving(false);
    }
  };
  // 10-31 최종 점검 — 요구사항이 있는지 읽는 동안은 「2단계 지금」이 아니다(읽기 전 몇 초 Claude 단추가 열렸다). 읽기 실패(countFailed)는 그 사유만 보인다.
  const checking = adopted === null && notParsed === null && countFailed === null;
  // 11-03 검토 — 열람자 · 읽기 전용 사유(draftBlock)가 「다시 분석을 누르세요」에 가려지지 않게 앞에 둔다 · 가상 예시 공고는 쓰지 않는다
  const blockReason = closedBlock ?? (infoLoading ? INFO_LOADING_BLOCK : null) ?? (checking ? "요구사항이 있는지 확인하는 중입니다" : null) ?? (cutWait ? CUT_BLOCK : null) ?? draftBlock ?? (isDemoProcurementId(noticeId) ? DEMO_BID_BLOCK : null) ?? (rfpRole === "notice" ? NO_RFP_BLOCK : null);
  // 「제안요청서로 다시 분석」을 눌렀는데도 공고서뿐이면 같은 단추를 되풀이하지 않는다(연결된 사전규격이 없는 공고)
  const [retriedRfp, setRetriedRfp] = useState(false);
  // 2.1.2 — 요구사항이 없으면 여기서 바로 분석한다(정리표와 같은 함수 · 첨부를 받을 때는 확인 창 · 취소면 요청 0)
  const [parsing, setParsing] = useState(false);
  const [parsePhase, setParsePhase] = useState<RfpParsePhase | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const parseBlock =
    (closed ? "마감된 공고라 새로 분석하지 않습니다" : null) ??
    (infoLoading ? INFO_LOADING_BLOCK : null) ??
    (draftBlock ? draftBlock.replace("초안을 만들 수 없습니다", "공고를 분석할 수 없습니다") : null) ??
    (isParsableNoticeId(noticeId) ? null : "이 공고는 여기서 분석할 수 없습니다");
  const analyze = async () => {
    setParsing(true);
    setParseError(null);
    setParsePhase(null);
    try {
      const result = await parseRfpWithConsent(noticeId, { onPhase: setParsePhase });
      if (result === null) return;
      setNotice(`요구사항 ${result.count}건을 뽑았습니다 — 위 단추로 초안을 쓰세요.`);
      setNotParsed(null);
      setTick((n) => n + 1);
    } catch (error: unknown) {
      setParseError(describeFailure(error));
    } finally {
      setParsing(false);
      setParsePhase(null);
    }
  };

  useEffect(() => {
    let alive = true;
    getAdoptedEvidence(noticeId, ctx)
      .then((value) => {
        if (!alive) return;
        setAdopted(value);
        setNotParsed(null);
        setCountFailed(null);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        // 404 만 「요구사항을 아직 뽑지 않은 공고」다 — 다른 실패는 그 사유를 그대로 보인다(29차 R28-10).
        if (error instanceof ApiError && error.status === 404) setNotParsed(describeFailure(error));
        else setCountFailed(describeFailure(error));
      });
    getRfpRequirements(noticeId)
      .then((value) => alive && setRfpRole(value.document_role === "notice" ? "notice" : "rfp"))
      .catch(() => alive && setRfpRole(null)); // 분석 전 · 못 읽음 — 막지 않는다(쓰기를 누르면 서버가 사유를 준다)
    getBidPlan(noticeId, ctx)
      .then((value) => {
        if (!alive) return;
        setDoc(value);
        setDocFailed(null);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        // 404 만 「만든 적 없음」이다 — 다른 실패는 사유를 보인다(위 getAdoptedEvidence 와 같은 꼴 · 2.0.6)
        setDoc(null);
        setDocFailed(error instanceof ApiError && error.status === 404 ? null : describeFailure(error));
      });
    return () => {
      alive = false;
    };
  }, [noticeId, ctx, tick]);

  const write = async (writer: PlanWriterName) => {
    // 2.7.0 — 있던 초안을 통째로 새로 쓴다(옛 판은 서버가 bid_plan_versions 에 보관) · 취소면 요청 0
    const consent = rewriteConsent(writerOf(writer).label, doc !== null, Boolean(doc?.quality?.approval));
    if (consent && !(await requestConsent(consent))) return;
    setBusy(writer);
    setFailure(null);
    setNotice(null);
    try {
      setDoc(await createBidPlan(noticeId, writer, ctx));
      setDocFailed(null); // (2.0.6) 방금 쓴 초안 위에 「저장된 전체 초안을 읽지 못했습니다」가 남았다
      setApproveFailure(null); // 새 초안이면 옛 승인 실패 글은 맞지 않는다
      onSaved();
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setNotice(`${describeFailure(error)} — 1분 뒤 다시 읽습니다.`);
        window.setTimeout(() => setTick((n) => n + 1), 60_000);
      } else if (isConnectionCut(error)) {
        waitAndReread();
      } else setFailure(describeFailure(error));
    } finally {
      setBusy(null);
    }
  };

  if (notParsed && adopted === null) {
    return (
      <section className="flex min-w-0 flex-col gap-3" aria-label="제안서 초안">
        <BidSteps current={1} />
        <EmptyState
          title="먼저 공고를 분석합니다"
          action={
            <div className="flex flex-col items-center gap-2">
              <Button variant="primary" onClick={() => void analyze()} disabled={parsing || parseBlock !== null} aria-busy={parsing} aria-describedby={parseBlock && !parsing ? "plan-analyze-block" : undefined} data-plan-analyze>
                {parsing ? (parsePhase ? RFP_PARSE_PHASE_LABEL[parsePhase] : "분석 중…") : "공고 분석 시작"}
              </Button>
              {parseBlock && !parsing && <p id="plan-analyze-block" className="text-[12.5px] text-cosmos-amber">{parseBlock}</p>}
              {parseError && <InlineAlert tone="fail">공고 분석에 실패했습니다 — {parseError}</InlineAlert>}
            </div>
          }
        >
          제안서는 공고의 요구사항이 있어야 씁니다. 「공고 분석 시작」을 누르면 공고문 · 제안요청서에서 요구사항을 뽑고, 끝나면 이 화면에서 바로 초안을 쓸 수 있습니다.
          {" "}요구사항 표를 직접 보고 고치려면{" "}
          <Link href={requirementSheetHref(noticeId)} className="mc-focus rounded font-medium text-cosmos-cyan hover:underline">
            사업기회 › {SCREEN_NAMES.rfp} →
          </Link>
        </EmptyState>
      </section>
    );
  }
  // 11-06 — 초안 머리 줄도 미리 보기와 같은 양식 값으로(양식 칸이 없는 초안은 「예전 방식」)
  const draftHead = doc ? draftOutlineLine(doc) : null;
  const proposalBody = doc && draftHead ? (
    <div className="flex flex-col gap-3 border-t border-cosmos-border pt-3" data-plan-proposal>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={doc.generated_by === "llm" ? "info" : "muted"}>
          {doc.generated_by === "llm" ? "AI 초안" : "목차 · 빈칸만"}
          {runLabel(doc.executed_at)}
        </Badge>
        <span className={`text-[12px] ${draftHead.warn ? "text-cosmos-amber" : "text-cosmos-muted"}`} data-bid-outline>
          {draftHead.text}
        </span>
      </div>
      {/* 2.7.0 — quality 칸이 없는 옛 응답은 상태 패널 없이(빈칸 목록은 그대로) */}
      {doc.quality && (
        <BidQualityPanel
          quality={doc.quality}
          reportUrl={bidPlanQualityReportUrl(noticeId, ctx)}
          workbookUrl={bidPlanQualityReportUrl(noticeId, ctx, "xlsx")}
          roleBlock={approveRoleBlock}
          busy={approving}
          failure={approveFailure}
          onDecide={(approve, note) => void decide(approve, note)}
          pdfBlock={pdfBlock}
          pdfBusy={checkingPdf}
          pdfFailure={pdfFailure}
          onCheckPdf={(file) => void checkPdf(file)}
        />
      )}
      <PlanBlanksList blanks={doc.blanks ?? []} grouped />
      {bidMajors(doc.sections).map(([major, sections]) => (
        <section key={major} aria-label={major} className="flex flex-col gap-2">
          <h3 className="text-[13.5px] font-semibold text-cosmos-text">{major}</h3>
          {sections.map((section) => (
            <BidSectionView key={section.key} section={section} tables={doc.tables} />
          ))}
        </section>
      ))}
    </div>
  ) : null;

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-label="제안서 초안">
      <BidSteps current={adopted === null ? null : doc ? 3 : 2} />
      <SectionHeader as="h2" title="제안서 초안(입찰)" description="제안요청서가 정한 「제안서 목차 및 작성 방법」과 기술능력 평가 기준대로 대항목마다 씁니다. 회사 자료(사업영역 · 인증 · 보유 자격 · 외부 사용 「가능」 실적)만 근거로 쓰고, 일반현황 칸은 회사자료로 채웁니다. 회사만 아는 값(투입 인력 성명 · 경력)은 「(담당자 입력)」 빈칸으로 둡니다. 제출용 파일에는 근거 표식 · 확인 메모가 없고, 검토용에만 근거 · 경고 · 담당자가 채울 항목이 실립니다. 입찰 분석의 「제안서 PDF」도 여기서 쓴 초안입니다(파일 이름은 승인 전 「초안」 · 승인 뒤 「제출용」)." />
      <p className="text-[13px] leading-5 text-cosmos-text" data-plan-adopted title="보내기 싫은 실적은 회사자료 › 실적 원장에서 외부 사용을 끄세요.">
        {adopted
          ? "AI 에 보내는 것 — 제안요청서 발췌 · 평가 기준 · 회사 사업영역 · 인증 · 보유 자격 · 외부 사용 「가능」 실적(공고와 가까운 6건). 사업자번호 · 대표자 · 연락처 · 주소 · 금액은 보내지 않습니다."
          : countFailed
            ? `요구사항을 읽지 못했습니다 — ${countFailed}`
            : "요구사항을 확인하는 중…"}
      </p>
      <BidOutlinePanel noticeId={noticeId} ctx={ctx} saved={doc?.format} />
      <div className="flex flex-wrap items-center gap-2">
        <WriterButtons status={status} busy={busy} elapsed={elapsed} extraBlock={blockReason} onWrite={(writer) => void write(writer)} evidenceCount={null} />
        {!closedBlock && <PlanBlockLine reason={blockReason} />}
        {/* 2.8.0 — 한글 파일을 받으면 서버가 만든 파일을 다시 읽어 검사한다 · 품질 패널 「한글 파일 검사」 줄을 새로 읽는다(onHwpxDone) */}
        {doc && (
          <PlanDownloadLinks
            programId={noticeId}
            urlFor={(format, variant) => bidPlanExportUrl(noticeId, { format, variant }, ctx)}
            fileStem="제안서"
            hwpx
            variants={downloadVariants(doc.format)}
            blindOnly={isBlindOnly(doc.format)}
            blanks={doc.submit_blanks ?? null}
            submitLabel={submitFileLabel(doc.quality)}
            submitTitle={DRAFT_FILE_TITLE}
            onHwpxDone={() => setTick((n) => n + 1)}
          />
        )}
      </div>
      {rfpRole === "notice" && (
        <InlineAlert tone="warn" role="status">
          {retriedRfp && !parsing && !parseError ? (
            <span data-bid-no-rfp>{NO_RFP_FOUND}</span>
          ) : (
            <span data-bid-no-rfp>
              {NO_RFP_NOTE}{" "}
              <Button
                variant="secondary"
                onClick={() => {
                  setRetriedRfp(true);
                  void analyze();
                }}
                disabled={parsing || parseBlock !== null}
                aria-busy={parsing}
                aria-describedby={parseBlock && !parsing ? "bid-rfp-block" : undefined}
              >
                {parsing ? (parsePhase ? RFP_PARSE_PHASE_LABEL[parsePhase] : "분석 중…") : "제안요청서로 다시 분석"}
              </Button>
              {parseBlock && !parsing && <span id="bid-rfp-block" className="block text-[12.5px]">{parseBlock}</span>}
            </span>
          )}
          {parseError && <span className="block">공고 분석에 실패했습니다 — {parseError}</span>}
        </InlineAlert>
      )}
      {doc?.stale && <InlineAlert tone="warn" role="status">초안을 쓴 뒤 공고 분석(요구사항)이 바뀌었습니다 — 새 제안요청서로 초안을 다시 쓰세요.</InlineAlert>}
      {closedBlock && (
        <p className="text-[12.5px] leading-5 text-cosmos-amber" role="status" data-plan-closed>
          {closedBlock}
        </p>
      )}
      {docFailed && <InlineAlert tone="warn" role="status">저장된 전체 초안을 읽지 못했습니다 — {docFailed.replace(/[.\s]+$/, "")}. 초안이 이미 있을 수 있으니 새로 쓰기 전에 화면을 다시 열어 보세요.</InlineAlert>}
      {(isUsageLimit(failure) || isUsageLimit(doc?.llm_note)) && (
        <InlineAlert tone="warn" role="status">사용 한도 — AI 사용 한도에 걸렸습니다. 몇 시간 뒤 다시 누르거나 다른 쪽(Claude · Codex)으로 쓰세요. 실패한 소항목은 빈칸으로 남습니다.</InlineAlert>
      )}
      {doc?.llm_note && <InlineAlert tone="warn" role="status">{doc.llm_note}</InlineAlert>}
      {notice && <InlineAlert tone="info" role="status">{notice}</InlineAlert>}
      {failure && <InlineAlert tone="fail" role="status">제안서 초안을 만들지 못했습니다 — {failure}</InlineAlert>}
      {proposalBody ?? (!docFailed && (
        <p className="text-[12.5px] text-cosmos-muted" data-plan-proposal-empty>
          아직 쓴 제안서 초안이 없습니다 — {closedBlock ? "마감된 공고라 새로 쓸 수 없습니다." : "위 단추로 Claude · Codex 를 골라 쓰세요(약 3~5분)."}
        </p>
      ))}
    </section>
  );
}

/** 11-03 — 분석 원문이 입찰공고문뿐일 때(제안요청서가 본공고 첨부에 없음). 다시 분석하면 연결된 사전규격의 제안요청서를 받는다. */
const NO_RFP_BLOCK = "제안요청서가 없어 입찰공고문만 분석했습니다 — 아래 「제안요청서로 다시 분석」을 누르세요";
const NO_RFP_NOTE =
  "제안요청서가 없어 입찰공고문만 분석했습니다. 공고문에는 입찰 절차 조항만 있어 제안서를 쓸 수 없습니다 — 다시 분석하면 연결된 사전규격의 제안요청서를 받습니다(받을 파일 이름을 먼저 보여 줍니다).";
const NO_RFP_FOUND =
  "다시 분석했지만 이 공고에 연결된 사전규격 제안요청서를 찾지 못했습니다(사전규격이 없거나 받은 목록에 없음) — 나라장터 공고 원문에서 제안요청서를 확인하세요.";
const DEMO_BID_BLOCK = "가상 예시 공고는 제안서 초안을 쓰지 않습니다 — 실제 나라장터 공고를 고르세요";

/** 대항목별로 묶는다(저장 순서 그대로). */
function bidMajors(sections: BidPlanSection[]): [string, BidPlanSection[]][] {
  const out: [string, BidPlanSection[]][] = [];
  for (const section of sections) {
    const last = out[out.length - 1];
    if (last && last[0] === section.major_title) last[1].push(section);
    else out.push([section.major_title, [section]]);
  }
  return out;
}

/** 소항목 하나 — 칸(일반현황) · 문장 · 딸린 표. 경고는 검토용과 같은 글(제출용 파일에는 없다). */
function BidSectionView({ section, tables }: { section: BidPlanSection; tables: BidPlanTable[] }) {
  const own = tables.filter((table) => (section.tables ?? []).includes(table.key));
  // 소항목 없이 대항목 하나뿐인 절(「Ⅵ. 결과 활용성 부문」)은 같은 제목을 두 번 달지 않는다
  const sameTitle = section.major_title.split(". ").slice(1).join(". ") === section.section;
  return (
    <div className="flex min-w-0 flex-col gap-1 pl-2" data-bid-section={section.key}>
      {section.kind !== "table_only" && !sameTitle && <h4 className="text-[12.5px] font-semibold text-cosmos-secondary">{section.section}</h4>}
      {section.kind === "fields" ? (
        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[12.5px]">
          {(section.fields ?? []).map((field) => (
            <Fragment key={field.label}>
              <dt className="text-cosmos-muted">{field.label}</dt>
              <dd className="min-w-0 break-words text-cosmos-secondary">{field.value}</dd>
            </Fragment>
          ))}
        </dl>
      ) : (
        <ul className="flex flex-col gap-1">
          {section.sentences.map((sentence, index) => (
            <li key={index} className="min-w-0 break-words text-[12.5px] leading-5 text-cosmos-secondary">
              {sentence.text}
              {sentence.flags && sentence.flags.length > 0 && <span className="block text-[11.5px] text-cosmos-amber">{sentence.flags.join(" · ")}</span>}
            </li>
          ))}
        </ul>
      )}
      {section.llm_error && <p className="text-[12px] text-cosmos-amber">AI 가 쓰지 못한 소항목 — {section.llm_error}</p>}
      {own.map((table) => (
        <div key={table.key} className="overflow-x-auto">
          <table className="min-w-full border-collapse text-[12px]" aria-label={table.title}>
            <caption className="py-1 text-left text-[12px] font-medium text-cosmos-secondary">{table.title}</caption>
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column} scope="col" className="border border-cosmos-border px-2 py-1 text-left font-medium text-cosmos-muted">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="border border-cosmos-border px-2 py-1 text-cosmos-secondary">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 페이지
// ---------------------------------------------------------------------------

export default function PlanPage() {
  const target = useSyncExternalStore(subscribeSelection, readTarget, readTargetServer);
  const backHref = useSyncExternalStore(subscribeSelection, readBackHref, readBackHrefServer);
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();
  const days = usePeriodDays();
  const nowMs = useNowMs();
  const [status, setStatus] = useState<PlanWriterStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedPlanDraft[]>([]);
  const [savedFailed, setSavedFailed] = useState<string | null>(null);
  const [savedTick, setSavedTick] = useState(0);
  const [supportItems, setSupportItems] = useState<UnifiedOpportunity[] | null>(null);
  const [bidItems, setBidItems] = useState<UnifiedOpportunity[] | null>(null);
  const [listFailed, setListFailed] = useState<string | null>(null);
  // (2.0.6) 서버는 한 출처만 실패해도 200 + source_errors 로 답한다 — 그 탭이 「0건 중 0건」으로 「없음」처럼 보였다
  const [sourceFailed, setSourceFailed] = useState<Record<Target["kind"], string | null>>({ support: null, notice: null });
  const [tab, setTab] = useState<"support" | "notice">("support");
  const [query, setQuery] = useState("");
  // 목록(조회 기간) 밖 공고의 머리 — id 로 상세를 읽는다(29차 R28-09 · 2.0.6 부터 목록은 자르지 않는다).
  const [detail, setDetail] = useState<{ id: string; title: string; agency: string | null; archivedNote?: string | null; archivedClosed?: boolean; bidClosed?: boolean | null } | null>(null);
  // 45차 M1 — 상세를 한 번 읽어 본 공고(성공 · 실패 모두). 그전에는 마감 여부를 몰라 단추가 눌리는 것처럼 보였다가 잠겼다
  const [detailTried, setDetailTried] = useState<string | null>(null);
  // (2.0.6) 상세 읽기 실패 — 머리 제목이 원시 id 로만 남는데 실패라는 말이 없었다
  const [detailFailed, setDetailFailed] = useState<{ id: string; reason: string } | null>(null);

  useEffect(() => {
    getPlanWriterStatus()
      .then(setStatus)
      .catch((error: unknown) => setStatusFailed(describeFailure(error)));
  }, []);
  useEffect(() => {
    let alive = true;
    listPlanDrafts(organizationId)
      .then((value) => {
        if (!alive) return;
        setSaved(value.items);
        setSavedFailed(null);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        setSaved([]);
        setSavedFailed(describeFailure(error));
      });
    return () => {
      alive = false;
    };
  }, [organizationId, savedTick]);
  useEffect(() => {
    let alive = true;
    Promise.all([
      // 머리(제목 · 기관 · D-day · 판정)는 사업기회 행 어디서 와도 채워지게 다 받는다(28차 검수 R2-02) — 고르기는 앞 30건만 그린다.
      // 자르지 않는다 — 200건에서 잘라 「200건 중」이라 적었는데 사업기회는 208건이었고, 뒤 8건은 찾기에도 없었다(2.0.6).
      // 마감 · 불가도 받는다 — 사업기회 「불가 포함」 · 「마감 포함」 행에서 오면 머리에 판정 · 마감이 사라졌다(2.0.6). 고르기는 isPickable 로 거른다.
      getBusinessOpportunities({ organizationId, source: "bizinfo", days, includeBlocked: true, includeClosed: true }),
      getBusinessOpportunities({ organizationId, source: "g2b", days, includeBlocked: true, includeClosed: true }),
    ])
      .then(([support, bid]) => {
        if (!alive) return;
        setSupportItems(support.items);
        setBidItems(bid.items);
        // 항목이 왔으면(저장본으로 대신 받은 날) 실패가 아니다 — 서버 failed_sources 와 같은 규칙(sourceFailure)
        setSourceFailed({ support: sourceFailure(support, "bizinfo"), notice: sourceFailure(bid, "g2b") });
      })
      .catch((error: unknown) => alive && setListFailed(describeFailure(error)));
    return () => {
      alive = false;
    };
  }, [organizationId, days]);

  const onSaved = useCallback(() => setSavedTick((n) => n + 1), []);
  const savedById = useMemo(() => new Map(saved.map((row) => [row.id, row])), [saved]);
  const unifiedById = useMemo(() => new Map([...(supportItems ?? []), ...(bidItems ?? [])].map((item) => [item.id, item])), [supportItems, bidItems]);

  const here = target ? unifiedById.get(target.id) ?? null : null;
  const demo = target?.kind === "notice" && isDemoProcurementId(target.id);
  const listsReady = supportItems !== null && bidItems !== null;
  // 목록을 못 읽어도 상세로 제목을 읽는다 — 머리에 원시 id 가 나왔다(30차 R29-14)
  const needsDetail = Boolean(target && !demo && (listsReady || listFailed) && !here);
  useEffect(() => {
    if (!target || !needsDetail) return;
    let alive = true;
    const read =
      target.kind === "support"
        ? getSupportProgram(target.id, organizationId).then((value) => ({
            id: target.id,
            title: value.program.title,
            agency: value.program.agency,
            archivedNote: value.archived ? value.archived_note ?? null : null,
            archivedClosed: Boolean(value.archived && value.archived_closed),
          }))
        : getProcurementNotice(target.id).then((value) => ({
            id: target.id,
            title: value.title,
            agency: value.agency,
            // 목록 밖 입찰의 마감 여부 — 입찰 마감이 지났으면 잠근다 · 없으면 모른다(null · 2.0.6 마지막 검토)
            bidClosed: value.deadline_at ? Date.parse(value.deadline_at) <= Date.now() : null,
          }));
    read
      .then((value) => {
        if (!alive) return;
        setDetail(value);
        setDetailFailed(null);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        setDetail(null);
        setDetailFailed({ id: target.id, reason: describeFailure(error) });
      })
      .finally(() => alive && setDetailTried(target.id));
    return () => {
      alive = false;
    };
  }, [target, needsDetail, organizationId]);
  const far = detail && target && detail.id === target.id ? detail : null;
  // 새 초안 잠금 — 목록에 있으면 목록의 마감, 목록 밖이면 상세의 입찰 마감(목록에 있을 때만 잠가 「목록에서 빠진 공고 — 저장본만」으로 열면
  // 마감 입찰에도 새 AI 초안이 나갔다 · 2.0.6 마지막 검토). 상세를 못 읽었으면 마감 여부를 몰라 잠근다.
  const bidClosed = here ? here.closed : far ? far.bidClosed === true : detailFailed?.id === target?.id && detailFailed !== null;
  const farFailed = !here && detailFailed && target && detailFailed.id === target.id ? detailFailed.reason : null;
  // (2.0.6) 주소로 받은 대상을 기억한다 — 메뉴 「대시보드」 · 회사자료 「보던 공고로 돌아가기」가 전에 본 공고로 갔다(/support 의 27차 LNK-01 과 같은 규칙).
  // id · 종류만 본다 — 주소를 다시 써 대상 객체가 바뀌어도 한 번 더 돌지 않게. 가상 예시는 지금처럼 남기지 않는다.
  const targetKind = target?.kind ?? null;
  const targetId = target?.id ?? null;
  const found = Boolean(here || far);
  useEffect(() => {
    if (!targetId || demo || !found) return;
    if (targetKind === "support") rememberSupport(targetId);
    else writeSelection(targetId, "replace");
  }, [targetKind, targetId, demo, found]);
  const infoLoading = Boolean(target && !demo && !here && (!(listsReady || listFailed) || (needsDetail && !far && detailTried !== target.id)));
  const title = here?.title ?? (demo ? DEMO_NOTICE.title : target ? far?.title ?? savedById.get(target.id)?.title ?? target.id : "");
  const headDeadline = here ? headDeadlineOf(here, nowMs) : null;
  // (2.0.6) 판정은 사업기회 행 · 지원사업 화면과 같은 verdictOf — 공급기업 자리면 「확인 필요」가 아니라 「간접 참여」
  const headVerdict = here && (here.eligibility_gate || here.participation) ? verdictOf(here.eligibility_gate, here.participation) : null;
  // (2.0.6) 판정 · 마감을 그리지 못한 이유 — 말없이 비우지 않는다(상세 읽기 실패가 먼저 · 목록에서 내려간 지원사업은 위 안내가 말한다).
  // 이때는 머리에 「공고 원문 ↗」 링크가 없다 — 따라 할 수 있는 길만 적는다(조회 기간은 사업기회와 이 화면이 같은 값).
  const headGap =
    !target || here || demo
      ? null
      : farFailed
        ? `공고 정보를 읽지 못했습니다 — ${farFailed}`
        : (listsReady || listFailed) && detailTried === target.id && !far?.archivedNote
          ? listFailed || sourceFailed[target.kind]
            ? "목록을 받지 못해 판정 · 마감을 여기서 보이지 못합니다 — 잠시 뒤 화면을 다시 열어 보세요"
            : "사업기회 목록(조회 기간 안)에 없는 공고라 판정 · 마감을 여기서 보이지 못합니다 — 사업기회에서 조회 기간을 넓혀 그 행에서 확인하세요"
          : null;

  // 고르기 목록 — 저장본이 있는 공고가 위(목록에서 빠진 공고도 보인다) · 찾기는 받아 온 목록 전체에서(29차 R28-11)
  const needle = query.trim().toLowerCase();
  const matches = (text: string | null | undefined) => !needle || (text ?? "").toLowerCase().includes(needle);
  const listed = (kind: "support" | "notice") => ((kind === "support" ? supportItems : bidItems) ?? []).filter((item) => isPickable(item) && (matches(item.title) || matches(item.agency)));
  const rows = (kind: "support" | "notice") => {
    const items = listed(kind);
    const savedRows = saved.filter((row) => (kind === "support" ? row.kind === "support" : row.kind === "proposal") && (matches(row.title) || matches(unifiedById.get(row.id)?.title)));
    const savedIds = new Set(savedRows.map((row) => row.id));
    // (2.0.6) 행 마감 글도 머리와 같은 headDeadlineOf — 따로 세어 등록마감만 지난 열린 입찰이 행은 「마감」, 머리는 「등록마감 지남」이었다(마감일 없는 행은 예전처럼 비운다)
    const deadlineTextOf = (item: UnifiedOpportunity | undefined) => (item && realDeadline(item) ? headDeadlineOf(item, nowMs).text : null);
    const fromSaved = savedRows.map((row) => ({ id: row.id, title: unifiedById.get(row.id)?.title ?? row.title ?? row.id, agency: unifiedById.get(row.id)?.agency ?? "목록에서 빠진 공고 — 저장본만", deadlineText: deadlineTextOf(unifiedById.get(row.id)) }));
    const rest = items.filter((item) => !savedIds.has(item.id)).slice(0, 30).map((item) => ({ id: item.id, title: item.title, agency: item.agency, deadlineText: deadlineTextOf(item) }));
    const demoRow = kind === "notice" && !savedIds.has(DEMO_NOTICE.id) && matches(DEMO_NOTICE.title) ? [{ id: DEMO_NOTICE.id, title: DEMO_NOTICE.title, agency: SYNTHETIC_NOTICE, deadlineText: null }] : [];
    return [...fromSaved, ...demoRow, ...rest];
  };

  return (
    <AppShell headerAside={<OrganizationPicker id="plan-organization" list={organizations.list} organizationId={organizationId} />}>
      <div className="flex min-w-0 flex-col gap-4" data-plan-target={target?.id ?? ""}>
        {/* 메뉴에서 빠져 사업기회 안으로 들어왔다(37차 §3-E · 담당자 결정 2026-10-14) — 길 표시와 돌아가기(들어온 탭 · 정렬 · 검색 그대로) */}
        <nav aria-label="길 표시" data-plan-breadcrumb className="-mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
          <Link href={backHref} data-plan-back className="mc-focus rounded font-medium text-cosmos-cyan hover:underline">
            {BACK_TO_OPPORTUNITIES}
          </Link>
          <span className="text-cosmos-muted">
            <Link href={backHref} className="mc-focus rounded hover:text-cosmos-text hover:underline">
              {SCREEN_NAMES.opportunities}
            </Link>
            {" › "}
            <span aria-current="page" className="text-cosmos-secondary">{SCREEN_NAMES.plan}</span>
          </span>
        </nav>
        <SectionHeader
          as="h1"
          title={SCREEN_NAMES.plan}
          description="지원사업은 사업계획서, 입찰은 제안서 초안을 씁니다. AI(Claude · Codex)는 단추를 누를 때만 쓰고, 공고 내용과 회사가 허락한 자료만 보냅니다."
          aside={
            target ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setTab(target.kind); // 보던 갈래로 돌아간다(29차 R28-11)
                  openTarget(null);
                }}
              >
                ← 공고 고르기
              </Button>
            ) : undefined
          }
        />
        <WriterLine status={status} failed={statusFailed} />

        {!target && (
          <section className="flex flex-col gap-3" aria-label="공고 고르기">
            <div role="group" aria-label="갈래" className="flex flex-wrap items-center gap-1">
              {([["support", "지원사업(사업계획서)"], ["notice", "입찰(제안서 초안)"]] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={tab === key}
                  onClick={() => setTab(key)}
                  className={`mc-focus min-h-10 rounded-lg border px-4 text-[14px] font-medium ${tab === key ? "border-cosmos-cyan/60 bg-cosmos-panel text-cosmos-text" : "border-transparent text-cosmos-secondary hover:border-cosmos-border"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="plan-search" className="text-[13px] text-cosmos-secondary">
                찾기
              </label>
              <input
                id="plan-search"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="공고명 · 기관"
                className="mc-focus min-h-10 w-full max-w-xs rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 text-[14px] text-cosmos-text placeholder:text-cosmos-muted"
              />
              {(tab === "support" ? supportItems : bidItems) !== null && !sourceFailed[tab] && (
                <span className="text-[12.5px] text-cosmos-muted" data-plan-picker-count>
                  {listed(tab).length}건 중 {Math.min(30, listed(tab).length)}건 표시{listed(tab).length > 30 ? " — 찾기로 좁히세요" : ""} · 마감 · 불가 · 관련 낮음은 사업기회처럼 뺌 · 저장본은 늘 위에
                </span>
              )}
            </div>
            {listFailed && <InlineAlert tone="warn" role="status">사업기회 목록을 읽지 못했습니다 — {listFailed}{savedFailed ? "" : " (저장본은 아래에 그대로 보입니다)"}</InlineAlert>}
            {!listFailed && sourceFailed[tab] && (
              <InlineAlert tone="warn" role="status">
                {tab === "support" ? "기업마당" : "나라장터"} 목록을 받지 못했습니다 — {sourceFailed[tab]} (공고가 없다는 뜻이 아닙니다)
              </InlineAlert>
            )}
            {savedFailed && <InlineAlert tone="warn" role="status">저장된 초안 목록을 읽지 못했습니다 — {savedFailed}</InlineAlert>}
            {(tab === "support" ? supportItems : bidItems) === null && !listFailed ? (
              <LoadingState label="사업기회 목록을 불러오는 중" rows={4} />
            ) : (
              <ul className="flex flex-col border-t border-cosmos-border" data-plan-picker={tab}>
                {rows(tab).map((row) => {
                  const badge = savedBadge(savedById.get(row.id), savedFailed !== null);
                  return (
                    <li key={row.id} className="border-b border-cosmos-border">
                      <button type="button" onClick={() => openTarget({ kind: tab, id: row.id })} className="mc-focus flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-2 py-2.5 text-left hover:bg-cosmos-elevated/40">
                        {/* 최소 너비 — 옆 글(「목록에서 빠진 공고 — 저장본만」)이 길면 390 폭에서 이름이 한 줄 몇 글자 기둥이 됐다. 좁으면 옆 글이 다음 줄로 */}
                        <span className="min-w-[12rem] flex-1 break-keep text-[14px] text-cosmos-text">{row.title}</span>
                        <span className="text-[12.5px] text-cosmos-muted">{row.agency}</span>
                        {row.deadlineText && <span className="text-[12.5px] text-cosmos-secondary">{row.deadlineText}</span>}
                        <Badge tone={badge.tone}>{badge.label}</Badge>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        )}

        {target && (
          <>
            <div className="flex flex-col gap-1.5 border-b border-cosmos-border pb-3" data-plan-head>
              <p className="text-[16px] font-semibold text-cosmos-text">{title}</p>
              <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-cosmos-secondary">
                <span>{here?.agency ?? far?.agency ?? (demo ? SYNTHETIC_NOTICE : target.kind === "support" ? "기업마당 지원사업" : "나라장터 입찰")}</span>
                {headDeadline && <Badge tone={headDeadline.closed ? "fail" : "muted"}>{headDeadline.text}</Badge>}
                {headDeadline?.bidLine && <span className="text-cosmos-muted">{headDeadline.bidLine}</span>}
                {!here && far?.archivedNote && (
                  <span className="text-cosmos-amber" data-plan-archived>
                    {far.archivedNote}
                  </span>
                )}
                {headVerdict && (
                  <Badge tone={headVerdict.tone} title={headVerdict.title}>
                    {headVerdict.label}
                  </Badge>
                )}
                {headGap && (
                  <span className="text-cosmos-amber" role="status" data-plan-head-gap>
                    {headGap}
                  </span>
                )}
                {here?.detail_url && (
                  <a href={here.detail_url} target="_blank" rel="noreferrer noopener" className="mc-focus rounded text-cosmos-cyan hover:underline">
                    공고 원문 ↗
                  </a>
                )}
                <Link href={target.kind === "support" ? `/analysis?support=${encodeURIComponent(target.id)}` : `/analysis?notice=${encodeURIComponent(target.id)}`} className="mc-focus rounded text-cosmos-cyan hover:underline">
                  {SCREEN_NAMES.analysis} →
                </Link>
                {/* 들어온 조건(탭 · 정렬 · 검색)이 있으면 그대로 — 머리 「← 사업기회로」와 같은 주소(38차 FRONTEND-05) */}
                <Link href={backHref !== "/opportunities" ? backHref : `/opportunities?${target.kind}=${encodeURIComponent(target.id)}`} className="mc-focus rounded text-cosmos-cyan hover:underline">
                  {SCREEN_NAMES.opportunities} →
                </Link>
              </div>
            </div>
            {target.kind === "support" ? (
              <SupportWriter
                key={`${target.id}-${organizationId}`}
                programId={target.id}
                organizationId={organizationId}
                status={status}
                onSaved={onSaved}
                closedNote={here?.closed ? CLOSED_BLOCK : !here && far?.archivedClosed ? far.archivedNote ?? null : null}
                infoLoading={infoLoading}
              />
            ) : (
              <BidWriter key={`${target.id}-${organizationId}`} noticeId={target.id} organizationId={organizationId} status={status} onSaved={onSaved} closed={bidClosed} infoLoading={infoLoading} />
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
