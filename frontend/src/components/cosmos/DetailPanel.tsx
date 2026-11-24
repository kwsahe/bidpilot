"use client";

/**
 * 우측 상세 패널. 선택 노드 종류별 내용 + 하단 고정 Human Review 블록.
 * 모든 수치는 CosmosGraph에서 계산된 값만 쓰고, 증빙·제안서·Auditor는 "데모 데이터"임을 표시한다.
 */

import { requirementSheetHref } from "@/lib/selection";
import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { WORK_KIND_LABELS, type CapabilityStatus } from "@/types/capability";

import AuditorRunPanel from "@/components/cosmos/AuditorRunPanel";
import GatePanel from "@/components/cosmos/GatePanel";
import GuidedDetail from "@/components/cosmos/GuidedDetail";
import { RunTimelineList } from "@/components/cosmos/RunTimeline";
import { DownloadLink } from "@/components/ui/DownloadLink";
import AttachmentLinks from "@/components/ui/AttachmentLinks";
import NoticeQaPanel from "@/components/ui/NoticeQaPanel";
import { attachmentLinkOf } from "@/lib/attachments";
import { RfpDownloadLink, useRfpLink } from "@/components/ui/NoticeSourceLinks";

import { blockingText, checklistOrder, eligibilityGateView, endedWithoutDate, inClauseSection, pendingSidesText } from "@/lib/cosmos/eligibilityGate";
import { describeFailure, koreanDetail } from "@/lib/errors";
import { REVIEWER_STORAGE_KEY, clearDraft, confirmDiscard, loadDraft, saveDraft } from "@/lib/unsavedGuard";
import { Badge } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import {
  bidApplicationExportUrl,
  exportDownloadUrl,
  getTemplates,
  proposalExportUrl,
  bidPlanExportUrl,
  renderTemplate,
} from "@/lib/api";
import { useAnalysisLoading, useNotRunLabel } from "@/lib/cosmos/analysisLoading";
import { scopeBadge, syntheticMixLock } from "@/lib/organization";
import { currentUserName } from "@/lib/currentUser";
import type { AnalysisContextParams } from "@/types/organization";
import {
  CRITICALITY_COLORS,
  CRITICALITY_LABELS,
  ITEM_TYPE_COLORS,
  ITEM_TYPE_LABELS,
  ITEM_TYPE_WHAT,
  REVIEW_STATUS_LABELS,
  criticalityOf,
  displayCodeOf,
  itemTypeOf,
  mandatoryCount,
  nodeColorHex,
  verdictWord,
} from "@/lib/cosmos/itemTypes";
import { guidedStepDef, type GuidedStep } from "@/lib/cosmos/guidedFlow";
import { coverageNoun, nextActions, riskSummary } from "@/lib/cosmos/mission";
import { STALE_CARD_CLASS, STALE_CARD_LABEL, STALE_VALUE_LABEL, staleBlockReason, staleReadiness } from "@/lib/cosmos/stale";
import { runStamp, type RunStampKey } from "@/lib/cosmos/runStamp";
import { NOTICE_DOCUMENT_WARNING, parseSourceLabel, parsedFromNotice } from "@/lib/cosmos/provenance";
import {
  AUDIT_NODE_ID,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  evidenceNodeId,
  findingGroupKeyOf,
  findingNodeId,
  findingTypeLabel,
  isSevere,
  requirementNodeId,
  proposalDraftText,
  severityRank,
  sourceBadges,
  NOT_RUN_SUMMARY,
  type CosmosGraph,
  type CosmosNode,
  type NoticeOrigin,
  type EvidenceView,
  type FindingView,
  type RequirementView,
  type ReviewDecision,
  type WorkflowStage,
  currentStep,
  detailNodeOf,
  evidenceRunSentence,
  evidenceRunState,
  type EvidenceRunState,
} from "@/lib/cosmos/graph";
import {
  ELIGIBILITY_LABELS,
  CANDIDATE_TIER_LABELS,
  clauseRefText,
  DECISION_LABELS,
  GENERATION_METHOD_LABELS,
  groundingLabel,
  REQUIREMENT_STATUS_LABELS,
  REQUIREMENT_TYPE_LABELS,
  SEVERITY_LABELS,
  formatBudgetCompact,
  formatDateTime,
  formatPage,
  formatSimilarity,
  seriousText,
  tintStyle,
} from "@/lib/cosmos/format";
import { daysUntil, effectiveDeadline, firstLabel, formatDeadlineDateTime, formatPairDeadline, noticeDeadlinePair, registrationClosesFirst, urgencyTierOf } from "@/lib/deadline";
import { bidDeadlineAdvice } from "@/lib/firstTimeGuide";
import { useNowMs, type AnalysisActions, type RunLog } from "@/lib/cosmos/useCosmosDashboard";
import {
  GRADE_LABELS,
  METHOD_LABELS,
  RECOMMENDATION_GRADE,
  REVIEW_PRIORITY,
  labelOf,
} from "@/lib/scoreNames";
import { COSMOS_COLORS, KIND_LABELS, STATE_COLORS, STATE_LABELS, TONE_COLORS, VERDICT_BOX_CLASS, VERDICT_COLORS } from "@/lib/cosmos/theme";
import {
  COMPANY_EVIDENCE,
  DOC_UNREAD_GATE_LINE,
  FIRST_BID_LINE,
  IF_REAL_NOTICE,
  GENERAL_GUIDE_NOTE,
  GUIDE_LINK_TEXT,
  READINESS_NOT_USED,
  FULL_VIEW_ONLY_TAG,
  NO_EVIDENCE,
  OPEN_REQUIREMENT_SHEET,
  OUTSIDE_G2B,
  OUTSIDE_NOTE,
  OUTSIDE_TITLE,
  REGISTER_COMPANY_DOCUMENTS,
  REGISTRATION_HELP,
  SCREEN_NAMES,
  SYNTHETIC_COMPANY,
  SYNTHETIC_NOTICE,
} from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import { isDemoProcurementId } from "@/lib/cosmos/demoNotice";
import { DIRECT_CHECK_HEAD, UNLOCK_HEAD, isDirectCheck, isOverCeilingRow } from "@/lib/unlock";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import type { DetectedBy, EligibilityReport, FindingResolution, RequirementAuditState } from "@/types/analysis";
import type { AuditFinding, EligibilityResult, FindingType, GroundingType, ProposalSentence, Severity } from "@/types/cosmos";
import { noticeAttachments } from "@/types/procurement";
import { ReqCodeProvider, requirementCode, useReqCode } from "@/lib/cosmos/reqCode";
import { requestConsent } from "@/lib/consentPrompt";
import type { TemplateInfo, TemplateRenderResult } from "@/types/support";

/** 공고 정보 칸 원문 · 제안요청서 단추(같은 모양). */
const SOURCE_BUTTON =
  "w-fit rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-cyan transition-colors hover:border-cosmos-cyan/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan";

export interface DetailPanelProps {
  graph: CosmosGraph;
  /** 제안서 생성 · Auditor 검사 · 자격 재판정 실행기 */
  actions: AnalysisActions;
  selectedId: string | null;
  /** 현재 워크플로 단계 — 선택 노드가 없을 때 개요는 이 단계 기준으로 그린다 */
  stage: WorkflowStage;
  /** 실행 타임라인 (실제 요청 상태) */
  runLog: RunLog;
  onSelect: (id: string | null) => void;
  /** 단계·노드로 이동 (KPI·위험·다음 행동에서 사용) */
  onNavigate: (stage: WorkflowStage, nodeId: string | null) => void;
  reviewDecision: ReviewDecision;
  onReviewDecision: (decision: ReviewDecision) => void;
  reducedMotion: boolean;
  /** 작은 화면 드로어 닫기 (없으면 버튼 숨김) */
  onClose?: () => void;
  /** Guided Flow(5단계 화면 이해 흐름) 현재 단계. 노드를 고르지 않았을 때 네 질문 구성으로 보여준다 */
  guidedStep?: GuidedStep | null;
  onGuidedNext?: () => void;
  onGuidedGoTo?: (step: GuidedStep) => void;
  onGuidedExit?: () => void;
  /** 다회사 구조: 현재 분석이 고정된 회사·근거 범위 (내려받기 링크·배지에 쓴다) */
  context?: AnalysisContextParams | null;
  organizationName?: string | null;
  /**
   * 쉬운 보기(24차 §3-2)의 단계 펼침 안에 들어간다 — 맨 위 참가 가능 여부 띠 · 맨 아래 사람의 최종 결정 ·
   * 개요의 결정 블록 · 3단계 체크리스트를 그리지 않는다(판정 카드 · 결정 덩어리와 두 번 나오지 않게).
   * 자체 스크롤 상자도 두지 않는다 — 페이지가 스크롤된다. 기본 = 지금처럼.
   */
  embedded?: boolean;
}

// ---------------------------------------------------------------------------
// 작은 프리미티브
// ---------------------------------------------------------------------------

const SEVERITY_COLORS: Record<Severity, string> = {
  // 참가를 막는 것과 보완 가능한 것을 같은 붉은색으로 칠하면 우선순위가 사라진다.
  critical: COSMOS_COLORS.red,
  high: COSMOS_COLORS.red,
  medium: COSMOS_COLORS.amber,
  low: COSMOS_COLORS.slate,
  info: COSMOS_COLORS.slate,
};

/**
 * 「참가 차단」이 무슨 뜻인가. 여러 곳에서 같은 문장을 써야 뜻이 갈리지 않는다.
 *
 * 실측: 실공고 g2b-R26BK01690926-000 은 발견 141건 중 «critical 16건»이었는데,
 * 화면은 「높음 미해결 0」과 최종 승인 칸의 「없음」만 보여줬다 — 가장 급한 16건이
 * 통째로 빠져 있었다. 보완하면 되는 「높음」과 제출 자체가 막히는 것은 다른 말이다.
 */
const BLOCKING_WHAT = "이대로 내면 형식 요건에서 탈락할 수 있습니다. 먼저 고치세요.";

/**
 * 발견 유형별 «왜 문제인가». 검사 종류를 설명하는 고정 문구이며 데이터가 아니다.
 * (없는 값을 지어내지 않으려고, 개별 발견에서 읽을 수 없는 것은 여기에 두지 않는다.)
 */
const FINDING_TYPE_WHY: Record<FindingType, string> = {
  missing_requirement:
    "제안요청서가 요구한 항목인데 초안에서 대응 문장을 찾지 못했습니다. 필수 항목이 빠지면 감점되거나 형식 요건에서 탈락할 수 있습니다.",
  number_mismatch:
    "제안요청서 원문의 수치와 초안의 수치가 다릅니다. 횟수·기간·인원·금액은 원문 그대로 맞춰야 합니다.",
  unsupported_claim:
    "회사 근거(수행실적·인증 등)에 연결되지 않은 주장입니다. 근거 없는 문장은 확인 요청을 받거나 신뢰를 잃습니다.",
  unchecked_condition:
    // 영문 판정값을 화면에 내지 않는다 (규칙 11 · 0922 §4-D-6).
    "직접 확인할 조건입니다. 시스템은 「가능」도 「불가」도 아닌 「확인 필요」로 남기고 판단은 담당자가 합니다.",
  missing_document:
    "제출서류 목록에 있는 문서가 준비 목록에서 확인되지 않았습니다. 서류 누락은 형식 요건 탈락 사유입니다.",
  blind_identity:
    "공고가 평가본에 회사를 알아볼 수 있는 정보(회사 이름 · 대표자 · 연락처 · 번호 · 실적 기관)를 막습니다. 올린 글에 그 값이 남아 있습니다(값은 기록에 남기지 않습니다).",
};

const GROUNDING_COLORS: Record<GroundingType, string> = {
  // 두 화면 밝기 토큰(어두운 #6f8bff 그대로 · 밝은 #1f45b5 — 흰 패널 12% 칩 위 6.7:1 · 11-04 검토)
  RFP_GROUNDED: "var(--cosmos-rfp)",
  COMPANY_EVIDENCE_GROUNDED: COSMOS_COLORS.cyan,
  AI_SUGGESTION: COSMOS_COLORS.violet,
};

/** 발견이 «어디서 답하는 항목인가» — 백엔드 item_classifier.RESPONSE_SCOPE_LABEL 과 같은 말(영어 코드를 화면에 내지 않는다). */
const RESPONSE_SCOPE_LABELS: Record<string, string> = {
  PROPOSAL_BODY: "제안서 본문",
  ELIGIBILITY_DOCUMENT: "자격 증빙",
  SUBMISSION_CHECKLIST: "제출 체크리스트",
  PRICE_PROPOSAL: "가격제안서",
  CONTRACT_COMPLIANCE: "계약 준수",
  INTERNAL_ACTION: "사전 행동",
  REFERENCE_ONLY: "참고",
  CONDITIONAL: "조건부",
  NOT_APPLICABLE: "해당 없음",
};

const DETECTED_BY_LABELS: Record<DetectedBy, string> = {
  RULE: "규칙으로 찾음",
  AI_EXTRACTION: "AI 정밀 검사",
};

const DETECTED_BY_COLORS: Record<DetectedBy, string> = {
  RULE: COSMOS_COLORS.blueText,
  AI_EXTRACTION: COSMOS_COLORS.violet,
};

/** 요구사항 상태 — 판정 4색(지도 노드색과 같다 · 후보 근거만은 확인 필요 쪽 호박 · 27차 §3-E UNI-10). */
const DISPLAY_STATUS_COLORS: Record<RequirementView["displayStatus"], string> = {
  matched: STATE_COLORS.ok,
  partial: STATE_COLORS.partial,
  unmatched: STATE_COLORS.missing,
  check: STATE_COLORS.check,
};

/**
 * 상태 칩. `tintStyle` 이 같은 색을 **글자·면·테두리**에 함께 쓴다.
 *
 * 그래서 넘기는 색은 «글자로 쓸 수 있는 색»이어야 한다 — 파랑은 `COSMOS_COLORS.blue` 가
 * 아니라 `blueText` 다. 면용 파랑(#4c7dff)을 글자로 쓰면 이 칩 배경 위에서 **4.44:1** 이고
 * 12px 글자에 필요한 4.5:1 에 못 미친다. 이것은 0925 §4-F-1 이 토큰을 둘로 나눈 이유이고
 * (`globals.css` 의 `--cosmos-blue-text` 주석), `theme.ts:90` 이 같은 말을 적어 두었는데도
 * 이 파일 여덟 자리가 면용 파랑을 쓰고 있었다. 검사가 낮은 창 측정을 고치고 나서 잡았다.
 */
function Chip({ color, children, title }: { color: string; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      data-chip
      className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[12px] font-medium"
      style={tintStyle(color)}
    >
      {children}
    </span>
  );
}

/** 합성 표시 — 회청 점선 + ◇ (`Badge` tone demo 한 곳 · 보라 ◆ 는 기업마당 · 27차 §3-E UNI-19). */
function DemoChip({ label = SYNTHETIC_NOTICE }: { label?: string }) {
  return (
    <Badge tone="demo" glyph>
      {label}
    </Badge>
  );
}

/**
 * 섹션 하나.
 *
 * `stale` 를 주면 **구버전 결과**로 그린다 — 채도를 낮추고 머리에 출처를 적는다.
 * 지우지 않는 이유는 lib/cosmos/stale.ts 에 적어 두었다.
 */
function Section({
  title,
  aside,
  children,
  stale = false,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  stale?: boolean;
}) {
  return (
    <section className={`flex flex-col gap-2 ${stale ? STALE_CARD_CLASS : ""}`}>
      <h3 className="flex items-center justify-between gap-2 text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
        <span>{title}</span>
        {aside}
      </h3>
      {stale && (
        <p className="rounded-md border border-cosmos-amber/40 bg-cosmos-amber/10 px-2 py-1 text-[12px] leading-4 text-cosmos-amber" role="note">
          {STALE_CARD_LABEL} · {STALE_VALUE_LABEL}
        </p>
      )}
      {children}
    </section>
  );
}

/** 접히는 섹션 — 접혀 있어도 요약(BLOCKER·높음 건수 등)은 보인다. */
function Collapsible({
  title,
  summary,
  defaultOpen,
  children,
}: {
  title: string;
  summary?: ReactNode;
  defaultOpen: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="mc-focus flex min-h-7 w-full items-center justify-between gap-2 rounded-md text-left"
      >
        {/* 대문자로 바꾸지 않는다 — 「BidPilot 밖에서 할 일」이 「BIDPILOT」으로 보였다(31차) */}
        <span className="text-[12px] font-semibold tracking-[0.14em] text-cosmos-muted">{title}</span>
        <span className="flex min-w-0 items-center gap-1.5">
          {summary}
          <span aria-hidden="true" className="text-[12px] text-cosmos-muted">
            {open ? "▾" : "▸"}
          </span>
        </span>
      </button>
      {open && children}
    </section>
  );
}

/**
 * 처음 입찰하는 사람 — 등록이 먼저 · 마감 며칠 전 할 일(31차 §3-B · 제품 반영 안 1-1 · 1-4 · 2-2). 1단계 개요와 레일 1단계가 여는
 * 공고 상세가 같이 쓴다. 「등록마감」 풀이는 마우스를 올려야만 보여 여기 한 번 적는다. 마감이 지났으면 할 일 줄은 없다.
 */
function FirstBidNote({ notice }: { notice: { id?: string; deadline_at: string | null; raw_data?: Record<string, unknown> | null } }) {
  const nowMs = useNowMs();
  // 가상 예시 공고에는 「이 공고」 등록마감 · 마감 할 일을 내지 않는다 — 날짜가 화면을 연 날부터 세는 예시 값이다(32차 R31-14)
  const demo = Boolean(notice.id && isDemoProcurementId(notice.id));
  const advice = demo ? null : bidDeadlineAdvice(noticeDeadlinePair(notice), nowMs);
  return (
    <>
      <p className="text-[12.5px] leading-5 text-cosmos-secondary">
        {demo && <span className="text-cosmos-muted">{IF_REAL_NOTICE} </span>}
        {FIRST_BID_LINE} <span className="text-cosmos-muted">(등록마감 = {REGISTRATION_HELP})</span>{" "}
        <GuideContextLink href={GUIDE_LINKS.firstBid}>{GUIDE_LINK_TEXT.firstBid}</GuideContextLink>
      </p>
      {advice && <p className="text-[12.5px] leading-5 text-cosmos-amber">{advice}</p>}
      {/* 공고 사실 바로 아래라 일반 안내임을 밝힌다(31차 마지막 검토) */}
      <p className="text-[12px] leading-5 text-cosmos-muted">{GENERAL_GUIDE_NOTE}</p>
    </>
  );
}

function Facts({ items }: { items: Array<{ label: string; value: ReactNode; mono?: boolean }> }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[13px]">
      {items.map((item) => (
        <div key={item.label} className="contents">
          <dt className="text-cosmos-muted">{item.label}</dt>
          <dd className={`min-w-0 break-words text-cosmos-text ${item.mono ? "font-mono tabular-nums" : ""}`}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Quote({ text, page, label }: { text: string; page?: number | null; label?: string }) {
  return (
    <blockquote className="rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 py-2 text-[13px] leading-6 text-cosmos-secondary">
      {(label || page !== undefined) && (
        <p className="mb-1 flex items-center gap-2 font-mono text-[12px] tabular-nums text-cosmos-muted">
          {label && <span>{label}</span>}
          {page !== undefined && <span>{formatPage(page)}</span>}
        </p>
      )}
      <p className="whitespace-pre-wrap">{text}</p>
    </blockquote>
  );
}

function RowButton({
  onClick,
  children,
  accent,
  ariaLabel,
}: {
  onClick: () => void;
  children: ReactNode;
  accent?: string;
  ariaLabel?: string;
}) {
  const style: CSSProperties | undefined = accent ? { borderLeftColor: accent } : undefined;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      style={style}
      className={`w-full rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2 text-left text-[13px] transition-colors hover:border-cosmos-border-strong hover:bg-cosmos-elevated focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan ${
        accent ? "border-l-2" : ""
      }`}
    >
      {children}
    </button>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[13px] text-cosmos-muted">{children}</p>;
}

/**
 * 참가 차단(critical) 미해결을 「높음」보다 «앞»에 세우는 경고 줄.
 * 0건이면 아무것도 그리지 않는다 — 검사를 돌리지 않은 상태를 0으로 단정하지 않기 위해
 * 「미실행」 표시는 각 호출부가 따로 한다.
 */
function BlockingBanner({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <p role="note" className="rounded-lg border px-3 py-2 text-[12.5px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
      <span className="font-semibold">탈락 위험 {count}건 안 고침</span> — {BLOCKING_WHAT}
    </p>
  );
}

/**
 * 코드가 길게 나열되던 자리. 「REQ-001, REQ-002, …」가 한 줄을 다 먹어
 * 정작 «몇 건인지»가 읽히지 않았다. 건수를 먼저 보여주고 목록은 펼침으로 옮긴다(지우지 않는다).
 */
function CodeListDetails({ label, codes, tone }: { label: string; codes: string[]; tone: string }) {
  if (codes.length === 0) return null;
  return (
    <details className="text-[12px] leading-5" style={{ color: tone }}>
      <summary className="mc-focus cursor-pointer list-none">
        {label} {codes.length}건 <span className="text-cosmos-muted">· 항목 코드 펼치기</span>
      </summary>
      <p className="mt-1 break-words font-mono text-[12px] text-cosmos-secondary">{codes.join(", ")}</p>
    </details>
  );
}

/** 「… 결과는 참고자료입니다」 — 점검이 규칙만으로 돌았으면 「규칙 검사」라 적는다(같은 화면 칩 · 출처 줄과 같은 말 · EZ-15). */
function referenceNote(graph: CosmosGraph): string {
  return graph.source.analysis.audit?.llm_used === false ? "규칙으로 검사한 결과는 참고자료입니다" : "AI 결과는 참고자료입니다";
}

function CoverageBar({ graph, breakdown = true }: { graph: CosmosGraph; breakdown?: boolean }) {
  const { covered, total, partial = 0 } = graph.coverage;
  const ratio = total === 0 ? 0 : covered / total;
  const audited = Boolean(graph.source.analysis.audit);
  const sheetMandatory = mandatoryCount(graph.requirements);
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span
          className="text-[13px] text-cosmos-secondary"
          title={audited ? "제출 전 점검이 본 요구사항 중 초안이 답한 수" : "제안서에 답하는 문장이 있는 필수 요구사항 수"}
        >
          {coverageNoun(graph)} 반영
        </span>
        <span className="font-mono text-[20px] font-semibold tabular-nums text-cosmos-text">
          {covered}
          <span className="text-cosmos-muted"> / {total}</span>
        </span>
      </div>
      <div
        className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-cosmos-slate/60"
        role="progressbar"
        aria-label="요구사항 반영률"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={covered}
      >
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{
            width: `${ratio * 100}%`,
            backgroundColor: graph.coverage.missingRequirementIds.length > 0 ? COSMOS_COLORS.amber : COSMOS_COLORS.cyan,
          }}
        />
      </div>
      {/* 정리표 「필수」와 다른 수를 같은 이름으로 부르지 않는다 — 왜 다른지 한 줄 (UI c) */}
      {audited && total !== sheetMandatory && (
        <p className="mt-1 text-[12px] leading-5 text-cosmos-muted">
          점검 대상은 정리표 「필수」({sheetMandatory}건)와 수가 다릅니다 — 점검은 평가 항목도 배점 · 서식 안내가 아니면 함께 세고, 서식 · 확약서 안내는 뺍니다.
        </p>
      )}
      {/* 점검은 「부분 반영」을 막대 수에 넣지 않는다 — 함께 적어야 아래 「필수 N건 중 M건에 대응 문장」(완전 + 부분)과 수가 맞는다 (DTL 검증 R-4). */}
      {breakdown && partial > 0 && (
        <p className="mt-1 text-[12px] leading-5 text-cosmos-muted">
          제출 전 점검 기준 — 반영 {covered} · 일부 반영 {partial} · 제안서에 빠짐 {graph.coverage.missingRequirementIds.length}
        </p>
      )}
      {graph.coverage.missingRequirementIds.length > 0 && (
        <div className="mt-1.5">
          <CodeListDetails label="미반영" codes={graph.coverage.missingRequirementIds} tone={COSMOS_COLORS.amber} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 공용 목록 조각
// ---------------------------------------------------------------------------

function FindingRow({
  finding,
  onSelect,
  resolved = false,
}: {
  finding: AuditFinding;
  onSelect: (id: string) => void;
  /** 담당자가 해결로 전환한 발견 — 탐지 기록은 그대로 두고 표시만 바꾼다 */
  resolved?: boolean;
}) {
  const nodeId = findingNodeId(finding.id);
  const code = useReqCode();
  return (
    <RowButton onClick={() => onSelect(nodeId)} accent={resolved ? TONE_COLORS.pass : SEVERITY_COLORS[finding.severity]}>
      <span className="flex flex-wrap items-center gap-1.5">
        {resolved ? (
          <Chip color={TONE_COLORS.pass}>해결됨</Chip>
        ) : (
          <Chip color={SEVERITY_COLORS[finding.severity]}>{SEVERITY_LABELS[finding.severity]}</Chip>
        )}
        <span className={`font-medium ${resolved ? "text-cosmos-secondary line-through decoration-cosmos-cyan/60" : "text-cosmos-text"}`}>
          {findingTypeLabel(finding.finding_type)}
        </span>
        {finding.detected_by && (
          <Chip color={DETECTED_BY_COLORS[finding.detected_by]}>
            {DETECTED_BY_LABELS[finding.detected_by]}
          </Chip>
        )}
        {finding.requirement_id && (
          <span className="ml-auto font-mono text-[12px] text-cosmos-muted">{code(finding.requirement_id)}</span>
        )}
      </span>
      {finding.source_text && (
        <span className="mt-1 block truncate text-[12px] text-cosmos-secondary">
          {formatPage(finding.source_page)} “{finding.source_text}”
        </span>
      )}
    </RowButton>
  );
}

function SentenceRow({
  sentence,
  onSelect,
  showLinks,
  canOpen = () => true,
}: {
  sentence: ProposalSentence;
  onSelect: (id: string) => void;
  showLinks: boolean;
  /** 이 id 로 상세가 열리는가 — 옛 공개 초안의 EV-·REQ- 코드는 지금 그래프에 없을 수 있다 (DTL-16) */
  canOpen?: (nodeId: string) => boolean;
}) {
  const reqId = sentence.requirement_id;
  const evId = sentence.evidence_id;
  const chip =
    "rounded-md border border-cosmos-border px-2 py-0.5 font-mono text-[12px] text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan";
  // 열 곳이 없으면 단추가 아니라 글자로 둔다 — 눌러도 개요로 튀지 않게.
  const codeChip = (code: string, nodeId: string) =>
    canOpen(nodeId) ? (
      <button type="button" onClick={() => onSelect(nodeId)} className={chip}>
        {code}
      </button>
    ) : (
      <span className="px-2 py-0.5 font-mono text-[12px] text-cosmos-muted" title="지금 공고 분석에는 이 항목이 없어 열 수 없습니다">
        {code}
      </span>
    );
  return (
    <li className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip color={GROUNDING_COLORS[sentence.grounding_type]}>{groundingLabel(sentence)}</Chip>
        {sentence.needs_review && <Chip color={COSMOS_COLORS.amber}>확인 필요</Chip>}
        <span className="ml-auto font-mono text-[12px] text-cosmos-muted">{sentence.id}</span>
      </div>
      <p className="mt-1.5 text-[13px] leading-6 text-cosmos-text">{sentence.text}</p>
      {showLinks && (reqId || evId) && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {reqId && codeChip(reqId, requirementNodeId(reqId))}
          {evId && codeChip(evId, evidenceNodeId(evId))}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// 종류별 본문
// ---------------------------------------------------------------------------

/**
 * 정거장에서 그 일을 하는 화면으로 — 같은 탭 이동이라 `→` (27차 §3-D-10). 떠나기 전에 저장 안 한 글(결정 사유 ·
 * 조건 메모 · 검사할 초안 입력)이 있으면 한 번 묻는다.
 */
export function PageLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      // 검사할 초안 입력도 공통 확인이 함께 묻는다 — 상단 메뉴와 같은 확인(2.0.6)
      onClick={(event) => {
        if (!confirmDiscard("작성 중인 내용")) event.preventDefault();
      }}
      className="mc-focus w-fit rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-cyan transition-colors hover:border-cosmos-cyan/60"
    >
      {children}
    </Link>
  );
}

/**
 * 「근거 없음」 · 「회사 쪽 확인」 자리의 회사자료 링크 — 지원사업 흐름과 같은 말 (27차 LNK-03 · lib/terms).
 * 쉬운 보기에서는 전체 화면뿐인 곳이라 꼬리표를 단다.
 */
function CompanyDocsLink({ embedded = false }: { embedded?: boolean }) {
  return <PageLink href="/company">{`${REGISTER_COMPANY_DOCUMENTS}${embedded ? ` ${FULL_VIEW_ONLY_TAG}` : ""} →`}</PageLink>;
}

/**
 * 「공고 정보」 마감 칸 — 위 카드와 같은 **실제 마감**(43차 결정 1 · 공고문 일정 · 등록 마감이 더 이르면 그 날 · 45차 M8).
 * 입찰 마감 원본만 적어 한 화면에 마감이 둘이었다(카드 「D-6 참가신청 마감 10/30」 · 상세 「마감일 미정」). 앞자리 마감이 따로 있으면
 * 그 이름과 입찰 마감을 두 줄로 적는다.
 */
function deadlineFacts(notice: CosmosGraph["source"]["notice"]): { label: string; value: string; mono?: boolean }[] {
  const pair = noticeDeadlinePair(notice);
  const real = effectiveDeadline(pair);
  if (registrationClosesFirst(pair)) {
    return [
      { label: firstLabel(pair), value: formatPairDeadline(pair, real, "datetime"), mono: true },
      { label: "입찰 마감", value: formatDeadlineDateTime(notice.deadline_at), mono: true },
    ];
  }
  return [{ label: "마감일", value: formatPairDeadline(pair, real, "datetime"), mono: true }];
}

/** 45차 H5 — AI 검색을 꺼 둔 회사: 「채택하세요」 자리에서 실적 원장 후보를 고르는 정리표 행으로(그 행 상세에 「채택」 단추). */
function LedgerPickLink({ noticeId, requirementId }: { noticeId: string; requirementId?: string }) {
  return <PageLink href={requirementSheetHref(noticeId, requirementId)}>요구사항 정리표에서 실적 원장 후보 고르기 →</PageLink>;
}

function CountPill({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-2 py-1.5">
      <dt className="text-[12px] text-cosmos-muted">{label}</dt>
      <dd className="font-mono text-[18px] font-semibold tabular-nums" style={{ color }}>
        {value}
      </dd>
    </div>
  );
}

function RequirementMiniRow({ req, onSelect }: { req: RequirementView; onSelect: (id: string) => void }) {
  return (
    <RowButton onClick={() => onSelect(req.nodeId)} accent={nodeColorHex({ state: req.nodeState })}>
      <span className="flex items-center gap-2">
        <span className="font-mono text-[12px] text-cosmos-muted">{displayCodeOf(req)}</span>
        <span className="min-w-0 flex-1 truncate font-medium text-cosmos-text">{req.title}</span>
        <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">{formatPage(req.page)}</span>
        <Chip color={nodeColorHex({ state: req.nodeState })} title={STATE_LABELS[req.nodeState]}>{verdictWord(req.nodeState)}</Chip>
      </span>
    </RowButton>
  );
}

/** 단계별 개요 — 레일·KPI에서 고른 단계에 맞춰 오른쪽 패널이 함께 바뀐다. */
function StageBrief({
  graph,
  stage,
  actions,
  onSelect,
  embedded = false,
  context = null,
}: {
  graph: CosmosGraph;
  stage: WorkflowStage;
  actions: AnalysisActions;
  onSelect: (id: string) => void;
  embedded?: boolean;
  context?: AnalysisContextParams | null;
}) {
  const { notice, origin, scenario, parse, analysis } = graph.source;
  const step = graph.steps[stage - 1];
  const rfpHref = requirementSheetHref(notice.id);
  // 마감 공고는 사업계획서 작성 페이지가 새 초안을 잠근다 — 쉬운 보기와 같은 조건으로 「쓰기」를 약속하지 않는다(2.0.6 통합 검토)
  const writeClosed = useWriteClosed(graph);
  // 불러오는 중에는 「미실행」이라고 말하지 않는다 (ISSUE-011).
  const notRun = useNotRunLabel();

  switch (stage) {
    case 1: {
      return (
        <Section title="공고 탐색" aside={<OriginChip origin={origin} />}>
          <p className="text-[14px] font-semibold leading-5 text-cosmos-text">{notice.title}</p>
          <Facts
            items={[
              { label: "발주기관", value: notice.agency },
              ...deadlineFacts(notice),
              { label: "예산", value: formatBudgetCompact(notice.budget), mono: true },
              { label: "지역", value: notice.region ?? "확인 필요" },
            ]}
          />
          <FirstBidNote notice={notice} />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onSelect(graph.nodes[0].id)}
              className="mc-focus rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60"
            >
              공고 상세 · 첨부 보기
            </button>
            <PageLink href="/opportunities">사업기회에서 다른 공고 고르기 →</PageLink>
          </div>
        </Section>
      );
    }
    case 2:
      return (
        <Section
          title={scenario ? `우리 회사 적합도 (${SYNTHETIC_NOTICE})` : "우리 회사 적합도 (낱말 기준)"}
          aside={scenario ? <DemoChip /> : notice.candidate ? <Chip color={COSMOS_COLORS.blueText}>낱말 기준</Chip> : undefined}
        >
          {scenario ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[28px] font-semibold tabular-nums text-cosmos-cyan">
                  {Math.round(scenario.semantic_match.fit_score * 100)}
                </span>
                <span className="text-[12px] text-cosmos-muted">/ 100 · {scenario.semantic_match.label}</span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {scenario.semantic_match.matched_domains.map((d) => (
                  <Chip key={d} color={COSMOS_COLORS.violet}>
                    {d}
                  </Chip>
                ))}
              </div>
              <p className="text-[13px] leading-6 text-cosmos-secondary">{scenario.semantic_match.reason}</p>
              <p className="text-[12px] leading-5 text-cosmos-muted">
                AI 의미 매칭은 쓰지 않습니다(순위는 낱말 기준만). 이 값은 가상 예시 공고에 미리 적어 둔 것입니다.
              </p>
            </>
          ) : notice.candidate ? (
            <>
              <div className="flex flex-wrap items-center gap-1.5">
                <Chip color={notice.candidate.tier === "high" ? COSMOS_COLORS.cyan : COSMOS_COLORS.blueText}>
                  낱말 관련도 {labelOf(CANDIDATE_TIER_LABELS, notice.candidate.tier)}
                </Chip>
                {[...notice.candidate.matched_ai_keywords, ...notice.candidate.matched_work_keywords].map((k) => (
                  <Chip key={k} color={COSMOS_COLORS.violet}>
                    {k}
                  </Chip>
                ))}
              </div>
              {notice.recommendation && (
                <Facts
                  items={[
                    {
                      label: RECOMMENDATION_GRADE.label,
                      value: `${labelOf(GRADE_LABELS, notice.recommendation.grade)} (${RECOMMENDATION_GRADE.scope})`,
                    },
                    // 0~1 값은 화면에 내지 않는다 — 사람이 읽는 척도가 아니다 (0920 §4-B-1).
                    // 순위는 「몇 번째로 볼 것인가」라 그대로 둔다.
                    ...(notice.rank != null
                      ? [{ label: REVIEW_PRIORITY.label, value: `${notice.rank}번째로 볼 공고` }]
                      : []),
                  ]}
                />
              )}
              <p className="text-[12px] leading-5 text-cosmos-muted">
                공고 글에 우리 사업 낱말(AI·교육 등)이 들어 있는지로만 고른 결과입니다. AI로 내용을 비교하지는 않습니다. 낙찰확률이 아닙니다.
              </p>
            </>
          ) : (
            <NotRunNote />
          )}
        </Section>
      );
    case 3:
      return <EligibilitySection graph={graph} actions={actions} hideChecklist={embedded} />;
    case 4: {
      const categories = new Map<string, number>();
      for (const r of graph.requirements) categories.set(r.category, (categories.get(r.category) ?? 0) + 1);
      const topCategories = [...categories.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
      const mandatory = mandatoryCount(graph.requirements);  // 45차 M6 — 정리표와 같은 수(참고 · 평가 뺌)
      const attention = graph.requirements.filter((r) => r.nodeState === "check" || r.nodeState === "warning" || r.nodeState === "missing");
      return (
        <Section
          title="요구사항 정리"
          aside={parse ? origin.kind === "demo" ? <DemoChip label={parseSourceLabel(graph)} /> : <Chip color={COSMOS_COLORS.cyan}>{parseSourceLabel(graph)}</Chip> : <NotRunChip />}
        >
          {!parse ? (
            // 쉬운 보기는 단추가 화면 위가 아니라 이 칸 바로 위에 있다 (P1-01)
            <NotRunNote>
              {embedded
                ? "제안요청서를 아직 읽지 않았습니다. 이 칸 바로 위 「공고 분석 시작」 단추를 누르면 첨부에서 요구사항을 뽑습니다."
                : "제안요청서를 아직 읽지 않았습니다. 화면 위 「공고 분석 시작」을 누르면 첨부에서 요구사항을 뽑습니다."}
            </NotRunNote>
          ) : (
            <>
              <dl className="grid grid-cols-3 gap-2">
                <CountPill label="요구사항" value={graph.counts.requirements} color={COSMOS_COLORS.blueText} />
                <CountPill label="필수" value={mandatory} color={COSMOS_COLORS.red} />
                <CountPill label="쪽" value={`${parse.page_count}쪽`} color={COSMOS_COLORS.cyan} />
              </dl>
              <p className="text-[12px] leading-5 text-cosmos-muted">
                {parse.document}
                {parse.page_is_approximate ? " · 한글 파일이라 쪽 번호는 대략입니다" : ""}
                {parse.truncated ? ` · 찾은 ${parse.candidate_count ?? "?"}개 중 앞 ${parse.count}개만 정리했습니다` : ""}
              </p>
              {/* 제안요청서가 없어 입찰공고문에서 뽑았다 — /rfp 와 같은 글 (27차 §3-A-4) */}
              {parsedFromNotice(graph) && (
                <p role="note" className="rounded-lg border border-cosmos-amber/40 bg-cosmos-amber/10 px-3 py-2 text-[12.5px] leading-5 text-cosmos-text">
                  {NOTICE_DOCUMENT_WARNING}
                </p>
              )}
              <div className="flex flex-wrap gap-1.5">
                {topCategories.map(([name, count]) => (
                  <Chip key={name} color={COSMOS_COLORS.blueText}>
                    {name} {count}
                  </Chip>
                ))}
              </div>
              {attention.length > 0 && (
                <>
                  <p className="text-[12px] font-medium text-cosmos-amber">주의 항목 {attention.length}건</p>
                  <div className="flex flex-col gap-1.5">
                    {attention.slice(0, 5).map((r) => (
                      <RequirementMiniRow key={r.id} req={r} onSelect={onSelect} />
                    ))}
                  </div>
                </>
              )}
            </>
          )}
          {/* 파싱 전에도 보인다 — 요구사항 정리표 화면에서 분석할 수 있다. 쉬운 보기에서는 전체 화면뿐인 곳이라 꼬리표. */}
          <PageLink href={rfpHref}>{OPEN_REQUIREMENT_SHEET}</PageLink>
        </Section>
      );
    }
    case 5: {
      const matched = graph.requirements.filter((r) => r.displayStatus === "matched").length;
      const partial = graph.requirements.filter((r) => r.displayStatus === "partial").length;
      const missing = graph.requirements.filter((r) => r.evidence.length === 0);
      // KPI · 출처 칩과 같은 실행 상태 한 벌 — 예전에는 합성 데모인가만 봐서 실공고는 늘 「미실행」이었다 (DTL-03 · ISSUE-166).
      const run = evidenceRunState(graph);
      return (
        <Section
          title="회사 수행근거 연결"
          stale={staleReadiness(graph) !== null}
          aside={graph.hasScenario ? <DemoChip label={SYNTHETIC_COMPANY} /> : run.status === "not_run" ? <NotRunChip /> : <Chip color={run.status === "done" ? COSMOS_COLORS.cyan : COSMOS_COLORS.amber}>{run.label}</Chip>}
        >
          <RunStampLine graph={graph} which="evidence" />
          {!graph.hasScenario ? (
            run.status === "not_run" ? (
              <NotRunNote>{evidenceRunSentence(run)}</NotRunNote>
            ) : (
              <>
                <p className="text-[12.5px] leading-5 text-cosmos-secondary">{evidenceRunSentence(run)}</p>
                {run.status === "off" && <LedgerPickLink noticeId={graph.source.notice.id} />}
              </>
            )
          ) : (
            <>
              <dl className="grid grid-cols-3 gap-2">
                <CountPill label="근거 연결" value={matched} color={COSMOS_COLORS.cyan} />
                <CountPill label="후보만" value={partial} color={STATE_COLORS.partial} />
                <CountPill label={NO_EVIDENCE} value={missing.length} color={STATE_COLORS.missing} />
              </dl>
              <p className="text-[12px] leading-5 text-cosmos-muted">
                회사 자료 {graph.counts.evidenceDocuments}종 · 채택 {graph.counts.selectedLinks}건. 가상 예시/비식별 자료이며 실제
                수행실적이 아닙니다.
              </p>
              {missing.length > 0 && (
                <>
                  <p className="text-[12px] font-medium text-cosmos-amber">근거 없음 — 자동으로 충족 처리하지 않습니다</p>
                  <div className="flex flex-col gap-1.5">
                    {missing.slice(0, 5).map((r) => (
                      <RequirementMiniRow key={r.id} req={r} onSelect={onSelect} />
                    ))}
                  </div>
                </>
              )}
              {graph.evidence.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {graph.evidence.slice(0, 8).map((ev) => (
                    <button
                      key={ev.id}
                      type="button"
                      onClick={() => onSelect(ev.nodeId)}
                      className="mc-focus rounded-full border px-2 py-0.5 text-[12px] font-medium transition-colors hover:brightness-110"
                      style={tintStyle(nodeColorHex({ state: ev.nodeState }))}
                    >
                      {ev.doc_type}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
          {/* 근거가 없거나 모자라면 회사자료를 등록 · 승인하는 화면으로(지원사업 흐름과 같은 자리 · 27차 §3-D-10 · LNK-03) */}
          <CompanyDocsLink embedded={embedded} />
        </Section>
      );
    }
    case 6:
      return (
        <Section
          title="제안서 초안"
          aside={
            analysis.proposal ? (
              <Chip color={COSMOS_COLORS.cyan}>{GENERATION_METHOD_LABELS[analysis.proposal.generation_method]}</Chip>
            ) : graph.hasProposal ? (
              <DemoChip />
            ) : (
              <NotRunChip />
            )
          }
        >
          {graph.hasProposal ? (
            <>
              <CoverageBar graph={graph} />
              <p className="text-[12px] leading-5 text-cosmos-muted">
                {graph.proposal?.title} · {graph.counts.sentences}문장 · 확인 필요 {graph.counts.sentencesNeedingReview}건.
                채택된 회사 근거만 사용하며 근거 없는 문장은 자동 확정하지 않습니다.
              </p>
              <button
                type="button"
                onClick={() => onSelect(PROPOSAL_NODE_ID)}
                className="mc-focus w-fit rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60"
              >
                문장별 근거 보기
              </button>
            </>
          ) : (
            <NotRunNote>제안서 초안을 아직 만들지 않았습니다. 아래 단추를 누르면 요구사항과 고른 회사 근거만으로 핵심 부분 1개를 씁니다.</NotRunNote>
          )}
          <GenerateProposalButton graph={graph} actions={actions} label={graph.hasProposal ? "제안서 다시 만들기" : undefined} />
          {/* 규칙 생성은 그대로(시연 동선) — AI(Claude · Codex)로 쓰는 것은 사업계획서 작성 페이지 한 곳 (28차 §3-D · 29차 §3-A). */}
          <PageLink href={`/plan?notice=${encodeURIComponent(notice.id)}`}>
            {/* 저장된 초안이 있는지는 여기서 모른다 — 「저장된 초안 보기」라 약속하면 가서 「초안 없음」을 만났다(2.0.6 마지막 검토) */}
            {writeClosed ? `${SCREEN_NAMES.plan} 페이지 열기 — 마감이라 새로 쓰기는 잠김 →` : `${SCREEN_NAMES.plan} 페이지에서 Claude · Codex로 쓰기 →`}
          </PageLink>
          {/* 45차 M12 — 만든 직후 여기서 바로 내려받는다(「문장별 근거 보기」를 눌러야 나타났다) */}
          {analysis.proposal && (
            <ProposalDownloadLinks procurementId={analysis.proposal.procurement_id} context={context} locked={syntheticMixLock(analysis.proposal)} />
          )}
          {/* 참고표 · 한글 서식은 제안서 없이도 만든다 — 제안서를 만든 뒤에는 제안서 칸 안에 같은 것이 있다 (DTL-22). */}
          {!analysis.proposal && origin.kind === "real" && (
            <div className="flex flex-col gap-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2 text-[12px] leading-5 text-cosmos-muted">
              <BidApplicationLinks procurementId={notice.id} context={context} />
            </div>
          )}
        </Section>
      );
    case 7:
      return (
        <Section
          title="제출 전 누락 점검"
          aside={
            analysis.audit ? (
              <Chip color={COSMOS_COLORS.cyan}>{analysis.audit.llm_used ? "규칙 + AI로 검사" : "규칙으로 검사"}</Chip>
            ) : graph.hasAudit ? (
              <DemoChip />
            ) : (
              <NotRunChip />
            )
          }
        >
          <RunStampLine graph={graph} which="audit" />
          {graph.hasAudit ? (
            <>
              <CoverageBar graph={graph} />
              {/* 참가 차단은 「높음」보다 앞이다 — 보완 가능한 것과 제출 자체가 막히는 것을 같은 칸에 두지 않는다. */}
              <BlockingBanner count={graph.counts.findingsBlockingOpen} />
              {/* 칸 순서 — 「그중」이 가리킬 것이 먼저: 안 고친 문제 → 그중 심각 → 심각 중 탈락 위험 → 해결(31차 R30-30) */}
              <dl className={`grid gap-2 ${graph.counts.findingsBlockingOpen > 0 ? "grid-cols-2" : "grid-cols-3"}`}>
                {/* 허브와 같은 규칙 — 높음 이상 미해결이 있을 때만 빨강 · 그 밖의 미해결은 호박(27차 §3-D-4) */}
                <CountPill
                  label="안 고친 문제"
                  value={graph.counts.findingsOpen}
                  color={graph.counts.findingsHighOpen > 0 ? COSMOS_COLORS.red : graph.counts.findingsOpen > 0 ? COSMOS_COLORS.amber : COSMOS_COLORS.cyan}
                />
                <CountPill label="그중 심각" value={graph.counts.findingsHighOpen} color={COSMOS_COLORS.red} />
                {graph.counts.findingsBlockingOpen > 0 && (
                  <CountPill label={`심각 중 ${SEVERITY_LABELS.critical}`} value={graph.counts.findingsBlockingOpen} color={COSMOS_COLORS.red} />
                )}
                <CountPill label="해결" value={graph.counts.findingsResolved} color={COSMOS_COLORS.cyan} />
              </dl>
              {graph.findings.length === 0 ? (
                <Empty>발견된 문제가 없습니다.</Empty>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {graph.findings.map((f) => (
                    <FindingRow key={f.id} finding={f} onSelect={onSelect} resolved={f.resolved} />
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <NotRunNote>
                제출 전 누락 점검을 아직 하지 않았습니다. 아래에 초안을 붙여넣고 「제출 전 점검」을 누르면 빠진 요구사항 · 틀린 숫자 · 근거 없는 문장을 찾습니다.
              </NotRunNote>
              <AuditorSection graph={graph} actions={actions} />
            </>
          )}
        </Section>
      );
    case 8:
    default: {
      const gateVerdict = eligibilityGateView(graph.eligibility, graph.source.analysis.eligibility?.verdict ?? null)?.verdict ?? null;
      return (
        <Section title="담당자 최종 결정" aside={<Chip color={graph.reviewDecision ? TONE_COLORS.pass : COSMOS_COLORS.amber}>{step.summary}</Chip>}>
          <p className="text-[13px] leading-6 text-cosmos-secondary">
            {referenceNote(graph)}. 담당자가 원문과 수정 권고를 확인한 뒤 제출 여부를 직접 결정합니다. 시스템은 자동 제출하지
            않습니다.
          </p>
          <ul className="flex flex-col gap-1 text-[12.5px] text-cosmos-secondary">
            <li className="flex items-center gap-2">
              {graph.hasAudit ? <Chip color={COSMOS_COLORS.cyan}>완료</Chip> : <NotRunChip />}
              제출 전 누락 점검 {graph.hasAudit ? `— 발견 ${graph.counts.findings}건` : ""}
            </li>
            {/*
              참가 차단은 승인 화면에서 «반드시» 보여야 한다. 예전에는 이 자리에 「높음」 한 줄뿐이라
              critical 16건이 있는 공고에서도 「없음」이라고 답했다.
            */}
            <li className="flex items-start gap-2">
              <Chip color={!graph.hasAudit ? COSMOS_COLORS.slate : graph.counts.findingsBlockingOpen > 0 ? COSMOS_COLORS.red : COSMOS_COLORS.cyan}>
                {!graph.hasAudit ? notRun : graph.counts.findingsBlockingOpen > 0 ? `${graph.counts.findingsBlockingOpen}건` : "없음"}
              </Chip>
              <span className="min-w-0">
                탈락 위험(안 고침)
                {graph.hasAudit && graph.counts.findingsBlockingOpen > 0 && (
                  <span className="block text-[12px] text-cosmos-red">{BLOCKING_WHAT}</span>
                )}
                {!graph.hasAudit && (
                  <span className="block text-[12px] text-cosmos-muted">
                    검사를 실행하지 않았습니다 — 「없음」이 아니라 아직 확인하지 않은 상태입니다.
                  </span>
                )}
              </span>
            </li>
            <li className="flex items-center gap-2">
              <Chip color={!graph.hasAudit ? COSMOS_COLORS.slate : graph.counts.findingsHighOpen > 0 ? COSMOS_COLORS.red : COSMOS_COLORS.cyan}>
                {!graph.hasAudit ? notRun : graph.counts.findingsHighOpen > 0 ? `${graph.counts.findingsHighOpen}건` : "없음"}
              </Chip>
              {SEVERITY_LABELS.high} 안 고침({SEVERITY_LABELS.critical} 포함)
              {graph.counts.findingsResolved > 0 ? ` · 해결 처리 ${graph.counts.findingsResolved}건` : ""}
            </li>
            <li className="flex items-center gap-2">
              {/* 띠 · 결정 칸과 같은 서버 종합 판정 · 판정 4색 — 「불가」가 여기서만 호박이던 것 (DTL-21). */}
              <Chip color={gateVerdict ? VERDICT_COLORS[gateVerdict] : COSMOS_COLORS.slate}>
                {gateVerdict ? ELIGIBILITY_LABELS[gateVerdict] : notRun}
              </Chip>
              참가자격 판정
            </li>
          </ul>
          {/* 실제 제출 · 보증 · 계약 — BidPilot 밖에서 사람이 한다(31차 §3-B · 제품 반영 안 1-2). 처음엔 접혀 있다. */}
          <Collapsible title={OUTSIDE_TITLE} defaultOpen={false}>
            <ol className="flex flex-col gap-1 text-[12.5px] leading-5 text-cosmos-secondary">
              {OUTSIDE_G2B.map((line, index) => (
                <li key={line} className="flex gap-2">
                  <span className="font-mono text-cosmos-muted">{index + 1}.</span>
                  <span className="min-w-0">{line}</span>
                </li>
              ))}
            </ol>
            <p className="text-[12px] text-cosmos-muted">
              {OUTSIDE_NOTE} <GuideContextLink href={GUIDE_LINKS.outside}>{GUIDE_LINK_TEXT.outside}</GuideContextLink>
            </p>
          </Collapsible>
          <p className="text-[12px] text-cosmos-muted">아래 「담당자 최종 결정」에서 검토 승인 또는 다시 검토를 고르면 8단계가 끝납니다.</p>
        </Section>
      );
    }
  }
}

function OverviewDetail({
  graph,
  actions,
  stage,
  runLog,
  onSelect,
  onNavigate,
  reducedMotion,
  embedded = false,
  context = null,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  stage: WorkflowStage;
  runLog: RunLog;
  onSelect: (id: string) => void;
  onNavigate: (stage: WorkflowStage, nodeId: string | null) => void;
  reducedMotion: boolean;
  embedded?: boolean;
  context?: AnalysisContextParams | null;
}) {
  const nowMs = useNowMs();
  const badges = sourceBadges(graph);
  const toneKind = { sample: "not_run", real: "computed", demo: "demo" } as const;
  const risks = riskSummary(graph, nowMs);
  const next = nextActions(graph);

  // 「실행」은 실제로 무언가를 돌리는 행동만 — 나머지는 그 단계로 옮겨 사람이 한다.
  // 제안서 업데이트는 옮겨서 「제안서 다시 생성」을 누른다(초안을 말없이 덮지 않는다 · DTL-04).
  const NAVIGATE_ONLY = new Set<(typeof next)[number]["kind"]>(["review", "audit", "decision", "eligibility_fail", "clauses", "blockers", "regenerate_proposal"]);
  const runAction = (kind: (typeof next)[number]["kind"], target: (typeof next)[number]) => {
    switch (kind) {
      case "eligibility":
        actions.refreshEligibility({ useLlm: false });
        onNavigate(3, target.nodeId);
        return;
      case "conditions":
        actions.detectConditions();
        onNavigate(3, target.nodeId);
        return;
      case "proposal":
        actions.generateProposal();
        onNavigate(6, null);
        return;
      default:
        onNavigate(target.stage, target.nodeId);
    }
  };

  const conditionReport = graph.source.analysis.conditions;
  const blockerCount = conditionReport?.counts.blocker ?? 0;
  const decisionStatus = graph.source.analysis.decision?.status;
  const gateSummary = conditionReport ? (
    <>
      {blockerCount > 0 && <Chip color={COSMOS_COLORS.red}>참가 차단 {blockerCount}</Chip>}
      {conditionReport.counts.action + conditionReport.counts.check > 0 && (
        <Chip color={COSMOS_COLORS.amber}>할 일 · 확인 {conditionReport.counts.action + conditionReport.counts.check}</Chip>
      )}
      {decisionStatus && decisionStatus !== "UNREVIEWED" && <Chip color={TONE_COLORS.pass}>{DECISION_LABELS[decisionStatus]}</Chip>}
    </>
  ) : (
    <NotRunChip />
  );
  const failRisks = risks.filter((r) => r.tone === "fail").length;
  const warnRisks = risks.filter((r) => r.tone === "warn").length;

  return (
    <>
      <StageBrief graph={graph} stage={stage} actions={actions} onSelect={onSelect} embedded={embedded} context={context} />

      {(stage === 3 || stage === 8 || conditionReport) && (
        <Collapsible
          title={embedded ? "놓치면 안 되는 조건 · 할 일" : "놓치면 안 되는 조건 · 할 일 · 참여 결정"}
          summary={gateSummary}
          defaultOpen={stage === 3 || stage === 8}
        >
          <GatePanel graph={graph} actions={actions} onSelect={onSelect} hideDecision={embedded} hideError={embedded} />
        </Collapsible>
      )}

      <Collapsible
        title="주요 위험"
        summary={
          <>
            {failRisks > 0 && <Chip color={COSMOS_COLORS.red}>위험 {failRisks}</Chip>}
            {warnRisks > 0 && <Chip color={COSMOS_COLORS.amber}>주의 {warnRisks}</Chip>}
            {risks.length === 0 && <span className="font-mono text-[12px] text-cosmos-muted">0</span>}
          </>
        }
        defaultOpen={failRisks > 0}
      >
        {risks.length === 0 ? (
          <Empty>지금 데이터에서 파생된 위험이 없습니다.</Empty>
        ) : (
          <div className="flex flex-col gap-1.5">
            {risks.map((risk) => (
              <RowButton
                key={risk.id}
                onClick={() => onNavigate(risk.stage, risk.nodeId)}
                accent={TONE_COLORS[risk.tone]}
                ariaLabel={`${risk.label} — ${risk.detail}. ${risk.stage}단계로 이동`}
              >
                <span className="flex items-center gap-2">
                  <Chip color={TONE_COLORS[risk.tone]}>{risk.tone === "fail" ? "위험" : risk.tone === "warn" ? "주의" : "안내"}</Chip>
                  <span className="min-w-0 flex-1 truncate font-medium text-cosmos-text">{risk.label}</span>
                  <span className="font-mono text-[12px] text-cosmos-muted">{risk.stage}단계</span>
                </span>
                <span className="mt-1 block truncate text-[12px] text-cosmos-secondary">{risk.detail}</span>
              </RowButton>
            ))}
          </div>
        )}
      </Collapsible>

      {/* 쉬운 보기는 「지금 할 일」 하나만 둔다 — 펼친 칸마다 같은 목록이 또 나왔다 (EZ-12) */}
      {!embedded && (
      <Section title="다음 행동" stale={staleReadiness(graph) !== null}>
        {next.length === 0 ? (
          <Empty>모든 단계를 마쳤습니다. 아래 「담당자 최종 결정」에서 최종 판단을 남기세요.</Empty>
        ) : (
          <ol className="flex flex-col gap-1.5">
            {next.map((action, index) => {
              const busy =
                (action.kind === "eligibility" && actions.eligibilityBusy) ||
                (action.kind === "proposal" && actions.proposalBusy) ||
                (action.kind === "audit" && actions.auditBusy);
              return (
                <li key={action.kind} className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cosmos-blue/25 font-mono text-[12px] text-cosmos-text">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-cosmos-text">{action.label}</span>
                    {action.kind !== "done" && action.kind !== "parse" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => runAction(action.kind, action)}
                        className="mc-focus shrink-0 rounded-md border border-cosmos-border-strong px-2 py-0.5 text-[12px] font-semibold text-cosmos-cyan transition-colors hover:border-cosmos-cyan/60 disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        {busy ? "실행 중…" : NAVIGATE_ONLY.has(action.kind) ? "이동" : "실행"}
                      </button>
                    )}
                  </div>
                  <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{action.detail}</p>
                </li>
              );
            })}
          </ol>
        )}
      </Section>
      )}

      <Collapsible title="데이터 출처" summary={<span className="font-mono text-[12px] text-cosmos-muted">{badges.length}</span>} defaultOpen={false}>
        <div className="flex flex-wrap gap-1.5">
          {badges.map((b) => (
            <SourceBadge
              key={b.label}
              kind={b.tone === "sample" && b.label.startsWith("공고") ? "demo" : toneKind[b.tone]}
              label={b.label}
            />
          ))}
        </div>
        <p className="text-[12px] text-cosmos-muted">
          「아직 안 함」은 값이 0이라는 뜻이 아니라 그 단계를 아직 하지 않았다는 뜻입니다. 「가상 예시 공고」 · 「가상 예시 회사자료」는 연습용 가상 예시 데이터입니다.
        </p>
      </Collapsible>

      <Collapsible title="실행 기록" defaultOpen={false}>
        <RunTimelineList runLog={runLog} reducedMotion={reducedMotion} />
      </Collapsible>
    </>
  );
}

/** 마감 입찰인가 — 6단계 링크 글 · 「다시 만들기」 단추가 같은 조건(2.0.6 · 10-31 최종 점검). */
function useWriteClosed(graph: CosmosGraph): boolean {
  const nowMs = useNowMs();
  const deadline = effectiveDeadline(noticeDeadlinePair(graph.source.notice));
  return urgencyTierOf(nowMs === null ? null : daysUntil(deadline, nowMs), endedWithoutDate(graph.eligibility, deadline)) === "closed";
}

/** 사업계획서 작성 페이지(/plan)의 마감 잠금 글과 같은 말. */
const CLOSED_WRITE_BLOCK = "마감된 공고라 새 초안을 만들 수 없습니다 — 저장된 초안 보기 · 내려받기만 됩니다";

/** 제안서 생성 버튼. 요구사항이 없으면 만들 수 없으므로 안내만 남긴다. */
function GenerateProposalButton({
  graph,
  actions,
  label,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  label?: string;
}) {
  // 45차 M4 — 열람자 잠금(훅은 이른 반환보다 먼저)
  const viewer = useViewerLock();
  // 10-31 최종 점검 — 마감 입찰은 단추도 잠근다(바로 아래 링크는 「마감이라 새로 쓰기는 잠김」인데 단추만 열려 있었다).
  // 가상 예시 공고(마감)는 시연 동선이라 그대로 둔다.
  const closed = useWriteClosed(graph) && graph.source.origin.kind === "real";
  if (!graph.hasRequirements) {
    return <Empty>요구사항이 아직 추출되지 않아 제안서를 만들 수 없습니다.</Empty>;
  }
  /*
    **누르기 전에 무엇이 나올지 말한다** (ISSUE-130 · prompt_06 §4-A-4).

    이 경로는 AI 가 꺼져 있어도 규칙으로 초안을 만든다(`proposal_service` 가 요구사항과
    채택 근거로 문장을 쓰고, LLM 은 그것을 다듬을 뿐이다). 그래서 단추는 살아 있고
    문구만 바뀐다 — 지원사업 화면이 이미 그렇게 한다. 모를 때(null)는 예전 문구 그대로다.
  */
  const aiOff = actions.aiDraft === false;
  return (
    <div className="flex flex-col gap-1.5">
      {viewer && <p className="text-[12px] text-cosmos-muted" data-viewer-lock>{VIEWER_LOCK_LABEL} — 초안 만들기는 편집자 이상이 합니다.</p>}
      {closed && <p className="text-[12px] text-cosmos-muted" data-closed-lock>{CLOSED_WRITE_BLOCK}</p>}
      <button
        type="button"
        disabled={actions.proposalBusy || viewer || closed}
        title={viewer ? VIEWER_LOCK_REASON : closed ? CLOSED_WRITE_BLOCK : undefined}
        onClick={actions.generateProposal}
        // 채움 주 단추는 파랑 하나(Button primary 와 같은 면) — 청록은 상태색이다 (27차 §3-E · UNI-23).
        className="w-fit rounded-lg bg-cosmos-blue-strong px-3 py-1.5 text-[12px] font-semibold text-white transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
      >
        {actions.proposalBusy
          ? "생성 중…"
          : aiOff
            ? graph.hasProposal
              ? "AI 없이 규칙으로 다시 만들기"
              : "AI 없이 규칙으로 초안 만들기"
            : (label ?? "제안서 초안 만들기")}
      </button>
      {actions.aiDraft !== null && (
        <p className="text-[12px] leading-5 text-cosmos-muted">
          AI 초안 {actions.aiDraft ? "켜짐" : "꺼짐"} —{" "}
          {actions.aiDraft
            ? "요구사항과 채택 근거로 규칙이 쓴 문장을 AI 가 다듬습니다."
            : "요구사항과 채택 근거만으로 만듭니다. AI 를 부르지 않습니다."}
        </p>
      )}
      {actions.proposalError && (
        <p role="alert" className="rounded-lg border px-3 py-2 text-[12px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
          {actions.proposalError}
        </p>
      )}
    </div>
  );
}

const DOWNLOAD_FORMATS = ["docx", "pdf", "txt"] as const;
/** 파일 형식은 쉬운 말로(30차 §3-F #8 — 「docx」는 개발 말). */
const FORMAT_LABELS: Record<(typeof DOWNLOAD_FORMATS)[number], string> = { docx: "워드", pdf: "PDF", txt: "텍스트" };

/** 제안서 초안이 서버에 없을 때(404) — 이 화면에는 제안서 초안을 쓰는 단추가 없다(제안서 작성 페이지에서 쓴다). */
const FULL_DRAFT_MISSING = "제안서 초안이 아직 없습니다 — 제안서 작성 페이지에서 Claude · Codex 로 먼저 쓰세요.";

/**
 * 실제로 생성한 초안만 내려받을 수 있다. 데모 시나리오는 서버에 파일이 없으므로 링크를 만들지 않는다.
 *
 * `locked` 는 실제 회사 결과에 **합성(가상) 근거가 섞인** 경우다 (ISSUE-018 · TASK-017).
 * 그 초안을 내려받으면 「(합성)」 문서를 인용한 문장이 그대로 제출 문서로 흘러간다.
 * 막고, 왜 막혔는지와 무엇을 하면 되는지를 함께 적는다.
 */
function ProposalDownloadLinks({
  procurementId,
  context,
  locked,
}: {
  procurementId: string;
  context?: AnalysisContextParams | null;
  locked?: string | null;
}) {
  const link =
    "rounded-md border border-cosmos-border px-2 py-0.5 font-mono text-[12px] uppercase text-cosmos-text transition-colors hover:border-cosmos-cyan hover:text-cosmos-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan";
  const [fullError, setFullError] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2 text-[12px] leading-5 text-cosmos-muted">
      {/* 잠긴 이유는 이 한 줄만 — 다섯 단추마다 같은 문장을 되풀이하던 것(DTL-05). */}
      {locked && (
        <p className="rounded-lg border border-cosmos-red/50 bg-cosmos-red/10 px-3 py-2 text-[12px] leading-5 text-cosmos-red">
          재생성 필요 — {locked}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold text-cosmos-text">초안 내려받기</span>
        <span>· 근거 있는 문장만:</span>
        {DOWNLOAD_FORMATS.map((format) => (
          <DownloadLink
            key={format}
            className={link}
            href={proposalExportUrl(procurementId, { format, groundedOnly: true }, context)}
            fallbackName={`제안서초안.${format}`}
            disabled={Boolean(locked)}
            title="회사 근거가 없는 「확인 필요」 문장은 본문에서 빼고 문서 끝 확인 목록에 남깁니다"
          >
            {FORMAT_LABELS[format]}
          </DownloadLink>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span>· 확인 필요 문장까지:</span>
        <DownloadLink
          className={link}
          href={proposalExportUrl(procurementId, {}, context)}
          fallbackName="제안서초안.docx"
          disabled={Boolean(locked)}
          title="확인 필요 문장까지 전부 실은 문서"
        >
          워드
        </DownloadLink>
        <DownloadLink
          className={link}
          href={bidPlanExportUrl(procurementId, { format: "pdf", variant: "submit" }, context)}
          fallbackName="제안서.pdf"
          disabled={Boolean(locked)}
          title="제안서 작성 페이지에서 쓴 초안 — 제안요청서의 제안서 목차대로 · 근거 표식 · 확인 메모 없는 판 · 파일 이름은 자동 검사 · 승인 상태에 따라 「초안」 또는 「제출용」"
          notFoundMessage={FULL_DRAFT_MISSING}
          onError={(message) => setFullError(message === null ? null : koreanDetail(message) ?? FULL_DRAFT_MISSING)}
        >
          {/* 2.8.0 — 상태(제출용)를 글자에 박지 않는다 · 이름은 서버 품질 게이트가 정한다 */}
          제안서 PDF
        </DownloadLink>
        {/* 서버가 영어로 「아직 없다」고 답하면 사람 말로 (DTL-06) — 전체 초안을 만드는 단추는 이 화면에 없다(담당자 결정). */}
        {fullError && (
          <span role="alert" className="w-full text-[12px] leading-5 text-cosmos-red">
            {fullError}
          </span>
        )}
      </div>
      <p className="text-[12px] text-cosmos-muted/80">
        문장마다 제안요청서 쪽 · 원문과 회사 근거를 함께 싣습니다. 완성본이 아니라 초안이며, PDF는 서버의 Word로
        변환합니다.
      </p>
      <BidApplicationLinks procurementId={procurementId} context={context} />
    </div>
  );
}

/**
 * 입찰참가신청서 참고표 · 한글 서식 — 제안서와 따로다 (DTL-22).
 * 이 둘은 공고 · 회사 정보만 쓰고 제안서를 읽지 않는데, 제안서 내려받기 칸 안에만 있어 제안서를 만들기 전에는
 * 보이지 않았다. 제안서 칸과 6단계 개요(제안서 전)가 같은 부품을 쓴다.
 */
function BidApplicationLinks({ procurementId, context }: { procurementId: string; context?: AnalysisContextParams | null }) {
  const link =
    "rounded-md border border-cosmos-border px-2 py-0.5 font-mono text-[12px] uppercase text-cosmos-text transition-colors hover:border-cosmos-cyan hover:text-cosmos-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan";
  return (
    <>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 border-t border-cosmos-border pt-2">
        <span className="font-semibold text-cosmos-text">입찰참가신청서 참고표</span>
        {/*
          예전 문구는 「발주기관 서식 표에 … 채운 초안」이었다. 실제로는 발주기관 첨부파일을 열지 않는다 —
          backend/app/services/bid_application_export.py 는 «구분·항목·기재 내용·근거/비고» 4열 표를 «새로» 만든다.
          공공입찰에서 지정 서식 미사용은 형식 탈락 사유라, 이 오해가 가장 비싸다.
        */}
        <DownloadLink
          className={link}
          href={bidApplicationExportUrl(procurementId, "docx", context)}
          fallbackName="입찰참가신청서참고표.docx"
          title="발주기관 서식과 같은 항목을 근거와 함께 정리한 참고표입니다. 제출용 서식은 공고 첨부의 원본을 쓰고 여기 값을 옮겨 적으세요"
        >
          docx
        </DownloadLink>
        <DownloadLink
          className={link}
          href={bidApplicationExportUrl(procurementId, "pdf", context)}
          fallbackName="입찰참가신청서참고표.pdf"
          title="같은 참고표를 PDF로. 제출용 서식이 아닙니다"
        >
          pdf
        </DownloadLink>
        <p className="w-full text-[12px] leading-5 text-cosmos-muted/80">
          발주기관 서식과 «같은 항목»을 근거와 함께 정리한 참고표입니다. 제출용 서식은 공고 첨부의 원본을 쓰고 여기 값을
          옮겨 적으세요. 공고·입찰공고문에서 채울 수 있는 칸만 채우고, 대표자·주민등록번호·인감 등 개인정보 칸은 빈칸으로
          둡니다.
        </p>
      </div>

      <HwpxTemplateLinks procurementId={procurementId} context={context} />
    </>
  );
}

/**
 * 한글(HWPX) 서식 만들기 — 베타.
 *
 * `getTemplates` / `renderTemplate` / `exportDownloadUrl` 는 lib/api.ts 에 있었지만
 * «부르는 화면이 한 곳도 없었다». 그래서 백엔드가 만드는 한글 서식을 담당자가 받을 길이 없었다.
 *
 * 능력보다 크게 말하지 않는다 — backend/app/services/hwpx_template_service.py 가 실제로 하는 일은
 * ZIP 무결성·필수 멤버·XML 파싱 검사와, 넣은 값이 파일 안에 남아 있는지 «다시 추출해» 확인하는 것까지다.
 * 한컴오피스에서 열리는지는 그 환경에서 확인하지 못했고, 표 셀 속성(cellAddr/cellSz)을 넣지 않아
 * 표가 흐트러질 수 있다. 그래서 verified 를 「검증됨」이라고 쓰지 않는다.
 */
function HwpxTemplateLinks({
  procurementId,
  context,
}: {
  procurementId: string;
  context?: AnalysisContextParams | null;
}) {
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState<TemplateInfo[] | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, TemplateRenderResult>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const link =
    "rounded-md border border-cosmos-border px-2 py-0.5 font-mono text-[12px] text-cosmos-text transition-colors hover:border-cosmos-cyan hover:text-cosmos-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan";

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (!next || templates !== null || listBusy) return;
    setListBusy(true);
    setListError(null);
    getTemplates()
      .then((res) => setTemplates(res.templates))
      .catch((err: unknown) => setListError(describeFailure(err, "서식 목록을 불러오지 못했습니다.")))
      .finally(() => setListBusy(false));
  };

  const make = (template: TemplateInfo) => {
    setBusyId(template.id);
    setErrors((prev) => ({ ...prev, [template.id]: "" }));
    // 실패해도 위쪽 DOCX 내려받기는 그대로 쓸 수 있어야 한다 — 이 블록 안에서만 오류를 표시한다.
    renderTemplate(template.id, procurementId, {}, context)
      .then((result) => setResults((prev) => ({ ...prev, [template.id]: result })))
      .catch((err: unknown) =>
        setErrors((prev) => ({
          ...prev,
          [template.id]: describeFailure(err, "서식을 만들지 못했습니다."),
        })),
      )
      .finally(() => setBusyId(null));
  };

  return (
    <div className="mt-1 flex flex-col gap-1.5 border-t border-cosmos-border pt-2">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="mc-focus flex w-full items-center gap-1.5 rounded-md text-left"
      >
        <span className="font-semibold text-cosmos-text">한글 서식</span>
        <Chip color={COSMOS_COLORS.violet}>베타</Chip>
        <span aria-hidden="true" className="ml-auto text-[12px] text-cosmos-muted">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <>
          <p className="text-[12px] leading-5 text-cosmos-muted/90">
            공고·회사 프로필에서 채울 수 있는 값만 넣어 HWPX 파일을 만듭니다. 표 칸의 위치·크기 정보를 넣지 않아
            한글 프로그램에서 표가 흐트러질 수 있습니다. <span className="text-cosmos-amber">최종 제출 전 한글
            프로그램에서 반드시 열어 확인하세요.</span>
          </p>
          {listBusy && <p className="text-[12px] text-cosmos-muted">서식 목록을 불러오는 중…</p>}
          {listError && (
            <p role="alert" className="rounded-lg border px-3 py-2 text-[12px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
              {listError} — 한글 서식만 실패했습니다. 위의 DOCX·PDF 내려받기는 그대로 쓸 수 있습니다.
            </p>
          )}
          {templates?.length === 0 && <p className="text-[12px] text-cosmos-muted">등록된 서식이 없습니다.</p>}
          {templates?.map((template) => {
            const result = results[template.id];
            const error = errors[template.id];
            return (
              <div key={template.id} className="rounded-lg border border-cosmos-border bg-cosmos-bg/40 px-2.5 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[12px] font-medium text-cosmos-text">{template.title}</span>
                  <button
                    type="button"
                    disabled={busyId === template.id}
                    onClick={() => make(template)}
                    className="mc-focus ml-auto min-h-7 rounded-md border border-cosmos-border-strong px-2 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {busyId === template.id ? "만드는 중…" : result ? "다시 만들기" : "만들기"}
                  </button>
                </div>
                <p className="mt-0.5 text-[12px] leading-5 text-cosmos-muted">{template.description}</p>
                {error && (
                  <p role="alert" className="mt-1 rounded-md border px-2 py-1 text-[12px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
                    {error}
                  </p>
                )}
                {result && (
                  <div className="mt-1 flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {/* 파일이 없거나 오류면 JSON 화면으로 떠나지 않고 이유를 옆에 적는다 (DTL-24). */}
                      <DownloadLink className={link} href={exportDownloadUrl(result.download_path)} fallbackName={result.file_name}>
                        {result.file_name}
                      </DownloadLink>
                      <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">
                        {result.size_bytes.toLocaleString()}B
                      </span>
                    </div>
                    <p className="text-[12px] leading-5 text-cosmos-secondary">
                      {result.verified
                        ? "넣은 값이 파일 안에 있음 · 한글 프로그램에서 열리는지는 미확인"
                        : `넣은 값 일부를 파일에서 찾지 못했습니다 (${result.verification.fields_found}/${result.verification.fields_checked})${
                            result.verification.missing_fields.length > 0
                              ? ` — ${result.verification.missing_fields.join(", ")}`
                              : ""
                          }`}
                    </p>
                    {/* 서버 메모의 영문 머리(「Beta ·」)와 내부 파일 경로는 화면에 내지 않는다 — 머리의 「베타」 칩 하나 (DTL-23). */}
                    <p className="text-[12px] leading-5 text-cosmos-muted/90" title={result.note}>
                      {result.note.replace(/^Beta\s*·\s*/i, "").replace(/\(data\/[^)]*\)/g, "")}
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

/** Auditor 실행 입력. 초안 기본값이 바뀌면 key로 다시 마운트한다. */
function AuditorSection({ graph, actions }: { graph: CosmosGraph; actions: AnalysisActions }) {
  const draft = proposalDraftText(graph.proposal);
  // 대조할 요구사항이 없으면 점검은 늘 실패한다 — 제안서 단추처럼 이유를 먼저 말한다 (DTL-20).
  if (!graph.hasRequirements) {
    return <Empty>요구사항을 먼저 뽑아야 점검할 수 있습니다 — 「공고 분석 시작」으로 제안요청서에서 요구사항을 뽑습니다.</Empty>;
  }
  return (
    <AuditorRunPanel
      key={`${graph.source.notice.id}:${graph.proposal?.id ?? "none"}:${graph.source.analysis.proposal?.generated_at ?? "demo"}:${draft.length}`}
      defaultText={draft}
      busy={actions.auditBusy}
      error={actions.auditError}
      onRun={actions.runAudit}
      onUpload={actions.runAuditUpload}
      aiDraft={actions.aiDraft}
    />
  );
}

/**
 * 「언제 돌린 결과인가」 한 줄 (0923 §3-3 · ISSUE-093).
 *
 * KPI·8단계 레일과 **같은 문구**를 쓴다 — `runStamp` 하나가 만든다. 실행한 적이 없으면
 * 아무것도 그리지 않는다(「미실행」은 바로 위 칩이 이미 말한다).
 */
function RunStampLine({ graph, which }: { graph: CosmosGraph; which: RunStampKey }) {
  const stamp = runStamp(graph.source.analysis, which);
  if (!stamp.text) return null;
  return (
    <p className={`text-[12px] leading-5 ${stamp.needsRerun ? "text-cosmos-amber" : "text-cosmos-muted"}`}>
      {stamp.text.replace(/^\(|\)$/g, "")}
    </p>
  );
}

function NotRunNote({ children }: { children?: ReactNode }) {
  // 불러오는 중에는 「아직 실행되지 않았다」고 말하지 않는다 (ISSUE-011).
  // 담당자는 그 문장을 「안 돌렸구나」로 읽고 이미 돌아간 분석을 다시 누른다.
  const loading = useAnalysisLoading();
  return (
    <p className="rounded-lg border border-dashed border-cosmos-border-strong px-3 py-2 text-[13px] leading-6 text-cosmos-muted">
      {loading ? "결과를 불러오는 중입니다…" : children ?? `${NOT_RUN_SUMMARY}. 이 단계는 아직 실행되지 않아 표시할 결과가 없습니다.`}
    </p>
  );
}

/** 「미실행」 칩. 불러오는 중에는 「불러오는 중…」으로 바뀐다 (ISSUE-011). */
function NotRunChip({ children }: { children?: ReactNode }) {
  const label = useNotRunLabel();
  return <Chip color={COSMOS_COLORS.slate}>{children ?? label}</Chip>;
}

/** 근거 범위 배지 — 내부 승인자료 / 합성 데모자료 / 레거시 공개 결과. 회사·범위를 조용히 섞어 보이지 않는다. */
function EvidenceScopeChip({ result }: { result: Parameters<typeof scopeBadge>[0] }) {
  const badge = scopeBadge(result);
  return (
    <Badge tone={badge.tone} glyph={badge.tone === "demo"} title={badge.detail}>
      {badge.label}
    </Badge>
  );
}

/** 공고 출처 배지 — 실공고와 데모 시나리오를 절대 섞어 보이지 않는다. */
function OriginChip({ origin }: { origin: NoticeOrigin }) {
  if (origin.kind === "demo") return <DemoChip />;
  return (
    <Chip
      color={COSMOS_COLORS.cyan}
      title={origin.fetchedAt ? `조회 ${formatDateTime(origin.fetchedAt)}` : undefined}
    >
      {origin.source === "g2b" ? "실제 나라장터 공고" : "나라장터 저장본"}
    </Chip>
  );
}

/** 참가자격 판정 섹션 — 공고 상세와 3단계 개요가 같이 쓴다. */
/** 판정값별 색. 「모른다(unknown)」는 빨강이 아니다 — 부족이 아니라 미확인이다. */
const CAPABILITY_COLORS: Record<CapabilityStatus, string> = {
  supported: COSMOS_COLORS.cyan,
  gap: COSMOS_COLORS.amber,
  unknown: COSMOS_COLORS.slate,
  info: COSMOS_COLORS.blueText,
};

const CAPABILITY_LABELS: Record<CapabilityStatus, string> = {
  supported: "확인됨",
  gap: "어긋남",
  unknown: "확인 필요",
  info: "참고",
};

/**
 * 개발 수행역량 — 「이 일을 우리 개발진이 해낼 수 있는가」.
 *
 * 「이 일이 우리 사업인가(후보 판정)」와 「참가할 수 있는가(Eligibility)」 사이에 놓는다.
 * 읽는 순서가 곧 판단 순서다.
 *
 * 이 블록은 **상태를 바꾸지 않는다.** GO/NO-GO 도, 자격판정도 건드리지 않는다.
 */
function DevCapabilitySection({ graph }: { graph: CosmosGraph }) {
  const report = graph.source.analysis.capability;
  if (!report) {
    return (
      <Section title="개발 수행역량">
        <NotRunNote>
          개발 수행역량 판정은 아직 안 했습니다. 근거 없이 수행 가능 여부를 단정하지 않습니다.
        </NotRunNote>
      </Section>
    );
  }

  const kinds = report.work_kinds.map((kind) => WORK_KIND_LABELS[kind]).join(" · ");
  return (
    <Section
      title="개발 수행역량 (우리 개발진 기준)"
      aside={<Chip color={COSMOS_COLORS.cyan}>규칙 기반 판정</Chip>}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {kinds && <Chip color={report.is_development ? COSMOS_COLORS.cyan : COSMOS_COLORS.amber}>{kinds}</Chip>}
        {(["supported", "gap", "unknown"] as CapabilityStatus[]).map((status) =>
          report.counts[status] ? (
            <Chip key={status} color={CAPABILITY_COLORS[status]}>
              {CAPABILITY_LABELS[status]} {report.counts[status]}
            </Chip>
          ) : null,
        )}
      </div>

      <p className="text-[13px] leading-6 text-cosmos-secondary">{report.headline}</p>
      <p className="text-[12px] leading-5 text-cosmos-muted">
        {report.used_requirements
          ? "과업 원문까지 읽고 판정했습니다."
          : "공고명·요약만 보고 판정했습니다 — 「공고 분석 시작」으로 과업 원문을 읽으면 다시 판정합니다."}{" "}
        {report.capacity_recorded
          ? "회사 개발역량 자료를 기준으로 대조했습니다."
          : "회사 개발역량 자료가 없어 대부분 확인 필요로 남습니다."}{" "}
        「확인 필요」는 <strong className="text-cosmos-secondary">할 수 없다는 뜻이 아니라</strong> 판정할 근거가
        아직 없다는 뜻입니다.
      </p>

      <ul className="flex flex-col gap-2">
        {report.findings.map((finding) => (
          <li
            key={finding.finding_id}
            className="rounded-lg border border-cosmos-border bg-cosmos-elevated/50 px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Chip color={CAPABILITY_COLORS[finding.status]}>{CAPABILITY_LABELS[finding.status]}</Chip>
              <span className="text-[13px] font-medium text-cosmos-text">{finding.label}</span>
            </div>
            <p className="mt-1 text-[13px] leading-6 text-cosmos-secondary">{finding.reason}</p>
            {finding.evidence.notice_quote && (
              <div className="mt-1.5">
                <Quote text={finding.evidence.notice_quote} label={finding.evidence.notice_where ?? "공고 원문"} />
              </div>
            )}
            {finding.evidence.company_fact && (
              <p className="mt-1.5 text-[12px] leading-5 text-cosmos-muted">
                회사자료: {finding.evidence.company_fact}
                {finding.evidence.company_where ? ` (${finding.evidence.company_where})` : ""}
              </p>
            )}
            {finding.next_action && (
              <p className="mt-1.5 text-[12px] leading-5 text-cosmos-muted">→ {finding.next_action}</p>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

/**
 * 3단계를 **두 절**로 나눈다 (19차 §4-C · 담당자 지시 「따로 판단하도록 해줘」).
 *
 * - 「참가자격 조항」 — 입찰공고문(·제안요청서·RFP)에서 가져온 조항. **조항마다 한 줄**이고(20차 §4-B)
 *   줄마다 담당자가 「충족 확인」「미충족」「보류」로 확인한다(20차 §4-C · 담당자 「하나하나씩 체크 및 확인」).
 *   공고문을 못 읽었다는 줄(QUAL-DOC)도 여기 두되 확인 단추는 없다 — 조항이 아니다.
 * - 「공고 필드 검사」 — 나라장터 목록 API 필드로 도는 줄(마감·예산·계약방식·면허표·지역표 …).
 *
 * 줄 가르기는 `inClauseSection`(lib/cosmos/eligibilityGate) — 지도 ③ 정거장도 같은 줄을 쓴다(21차).
 */
const CHECK_SIDE_LABELS: Record<"company" | "notice", string> = {
  company: "회사 정보 필요",
  notice: "공고문 더 읽기",
};
/** 「공고 기본정보 확인」 절 도움말(30차 §3-F #1). */
const FIELD_SECTION_HELP = "나라장터에 적힌 마감·예산·지역·계약방식·업종 칸으로 본 결과입니다";

function clauseHeading(report: EligibilityReport, count: number): string {
  if (report.clauses_status === "ok") {
    const pages = report.clause_pages ? ` ${report.clause_pages}` : "";
    return `참가자격 조항 ${count}개 — 입찰공고문${pages}`;
  }
  if (!report.notice_available || report.procurement_id.startsWith("synthetic-")) {
    return `참가자격 조항 ${count}개 — ${SYNTHETIC_NOTICE} · 공고문 없음`;
  }
  return `참가자격 조항 ${count}개 — 공고문을 읽지 못했습니다`;
}

/** 「입찰공고문 7 · 제안요청서 3 · RFP 2」 — 출처가 둘 이상일 때만. */
function clauseSources(rows: EligibilityResult[]): string | null {
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (row.clause_id && row.source_document) counts.set(row.source_document, (counts.get(row.source_document) ?? 0) + 1);
  }
  return counts.size > 1 ? [...counts].map(([name, n]) => `${name} ${n}`).join(" · ") : null;
}

// 대문자 변환(uppercase)은 쓰지 않는다 — 「p.1」이 「P.1」로 바뀐다.
const GROUP_TITLE = "text-[12px] font-semibold tracking-[0.08em] text-cosmos-muted";

export function EligibilityGroups({
  graph,
  actions,
  collapseFields = false,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  /** 쉬운 보기(24차): 공고 필드 검사를 「공고 필드 검사 m개 ▸」 한 줄로 접는다. 기본 = 지금처럼 펼침 */
  collapseFields?: boolean;
}) {
  const report = graph.source.analysis.eligibility;
  if (!report) {
    // 데모 시나리오 고정값(스냅샷 배포) — 조항 묶음이 없던 때의 모양 그대로 한 목록이다.
    return <EligibilityList rows={graph.eligibility} />;
  }
  return (
    <ReqCodeProvider requirements={graph.requirements}>
      <EligibilityGroupsBody graph={graph} actions={actions} collapseFields={collapseFields} report={report} />
    </ReqCodeProvider>
  );
}

function EligibilityGroupsBody({
  graph,
  actions,
  collapseFields,
  report,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  collapseFields: boolean;
  report: NonNullable<CosmosGraph["source"]["analysis"]["eligibility"]>;
}) {
  const clauseRows = checklistOrder(graph.eligibility.filter(inClauseSection));
  const fields = graph.eligibility.filter((e) => !inClauseSection(e));
  const view = eligibilityGateView(graph.eligibility, report.verdict);
  const synthetic = !report.notice_available || report.procurement_id.startsWith("synthetic-");
  const sources = clauseSources(clauseRows);
  const documents = report.clause_documents ?? [];
  return (
    <div className="flex flex-col gap-3">
      <section id="eligibility-checklist" className="flex flex-col gap-1.5" aria-label="참가자격 조항">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h4 className={GROUP_TITLE}>{clauseHeading(report, view?.total ?? 0)}</h4>
          {view && view.total > 0 && (
            <span className="text-[12px] font-semibold text-cosmos-text" data-clause-progress>
              확인 {view.done}/{view.total}
            </span>
          )}
        </div>
        {sources && <p className="text-[12px] leading-5 text-cosmos-muted">{sources}</p>}
        {documents.length > 0 && (
          // 그 조항을 읽은 **문서 자체**를 내려받는다 (20차 §4-E-2) — 원본 주소만, 로컬 사본은 내보내지 않는다.
          <AttachmentLinks
            compact
            items={documents.map((d, index) => ({
              key: `${d.source_document}:${index}`,
              name: `${d.source_document} · ${d.name}`,
              ext: d.format ?? null,
              href: d.url ?? null,
            }))}
          />
        )}
        {synthetic && (
          <p className="text-[12px] leading-5 text-cosmos-muted">
            가상 예시 공고라 입찰공고문이 없습니다. 제안요청서의 자격 조항만 같은 규칙으로 봅니다.
          </p>
        )}
        {clauseRows.length === 0 ? (
          <p className="text-[12px] leading-5 text-cosmos-muted">견줄 참가자격 조항이 없습니다.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {clauseRows.map((row) =>
              row.clause_id ? (
                <ClauseRow key={row.rule_id} row={row} actions={actions} />
              ) : (
                <EligibilityRow key={row.rule_id} row={row} />
              ),
            )}
          </ul>
        )}
        {/* 회사 값이 없어 못 가린 조항 — 값을 넣을 곳으로 (27차 LNK-03). 쉬운 보기(collapseFields)는 꼬리표. */}
        {view && view.company > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-1" data-company-side-link>
            <p className="text-[12px] leading-5 text-cosmos-muted">
              {CHECK_SIDE_LABELS.company} {view.company}개 — 회사자료에 그 값이 있어야 판정할 수 있습니다.
            </p>
            <CompanyDocsLink embedded={collapseFields} />
          </div>
        )}
        {actions.clauseReviewError && (
          <p role="alert" className="rounded-lg border px-3 py-2 text-[12px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
            {actions.clauseReviewError}
          </p>
        )}
      </section>
      {collapseFields ? (
        <details className="group" aria-label="공고 기본정보 확인" data-fields-collapsed>
          <summary className="mc-focus w-fit cursor-pointer list-none rounded py-1 text-[12px] font-semibold text-cosmos-secondary hover:text-cosmos-text" title={FIELD_SECTION_HELP}>
            공고 기본정보 확인 {fields.length}개 <span className="group-open:hidden">▸</span>
            <span className="hidden group-open:inline">▾</span>
          </summary>
          <div className="mt-1.5">
            <EligibilityList rows={fields} />
          </div>
        </details>
      ) : (
        <section className="flex flex-col gap-1.5" aria-label="공고 기본정보 확인">
          <h4 className={GROUP_TITLE} title={FIELD_SECTION_HELP}>공고 기본정보 확인 ({fields.length}개)</h4>
          <EligibilityList rows={fields} />
        </section>
      )}
    </div>
  );
}

/**
 * 참가자격 줄의 방식 — 백엔드는 규칙 판정에 AI 설명을 붙이면 방식을 AI_EXTRACTION 으로 바꾼다. 그때 「원문에서 뽑음」은
 * 틀린 말이라(발견 쪽은 같은 값이 「AI 정밀 검사」) 「AI 설명 추가」로 적는다 (DTL-37).
 */
function eligibilityMethodLabel(method: EligibilityResult["method"]): string {
  return method === "AI_EXTRACTION" ? "AI 설명 추가" : METHOD_LABELS[method];
}

type ClauseChoice = "met" | "unmet" | "pending";

const CLAUSE_CHOICES: { state: ClauseChoice; label: string; color: string }[] = [
  { state: "met", label: "충족 확인", color: VERDICT_COLORS.PASS },
  { state: "unmet", label: "미충족", color: VERDICT_COLORS.FAIL },
  { state: "pending", label: "보류", color: VERDICT_COLORS.CHECK },
];

/**
 * 참가자격 조항 한 줄 — 원문 인용 · 회사 사실과 견준 판정 · 담당자 확인 (20차 §4-D-2).
 *
 * 충족·미충족은 **근거 메모가 없으면 저장 단추가 잠긴다**(백엔드도 422 로 막는다 — 빈 메모로 「충족」을 남기면
 * 근거 없는 가능이다). 확인한 줄은 흐리게 · 「담당자 확인 · 이름 · 시각」. 확인 뒤 원문이 바뀌면 「다시 확인」.
 * 메모 칸은 `input` 이다 — 리허설 캡처가 문서의 첫 `textarea` 에 결함 초안을 붙여 넣는다(10번 장면).
 */
/** 「갖추면 가능」 · 「직접 확인」 줄 — 나라장터 등록은 등록증으로 직접 확인할 일이라 머리말이 다르다(32차 §3-B-2). */
function UnlockLine({ condition, ruleId }: { condition: string; ruleId: string }) {
  const direct = isDirectCheck(condition, ruleId);
  return (
    <p className="mt-1 text-[12px] leading-5 text-cosmos-cyan">
      {direct ? DIRECT_CHECK_HEAD : UNLOCK_HEAD}: {condition}
      {direct && (
        <>
          {" "}
          <GuideContextLink href={GUIDE_LINKS.register}>{GUIDE_LINK_TEXT.register}</GuideContextLink>
          <span className="block text-cosmos-muted">{READINESS_NOT_USED}</span>
        </>
      )}
    </p>
  );
}

function ClauseRow({ row, actions }: { row: EligibilityResult; actions: AnalysisActions }) {
  const viewer = useViewerLock();
  const code = useReqCode();
  const [choice, setChoice] = useState<ClauseChoice | null>(null);
  const [memo, setMemo] = useState("");
  const [name, setName] = useState(() => defaultResolutionReviewer());
  const rowRef = useRef<HTMLLIElement>(null);
  // 45차 M12 — 저장하면 줄이 목록 맨 아래로 옮겨 가 화면에서 사라졌다. 옮긴 뒤 그 줄로 굴리고 잠깐 「저장했습니다」를 남긴다
  const [justSaved, setJustSaved] = useState(false);
  useEffect(() => {
    if (!justSaved) return;
    const frame = window.requestAnimationFrame(() => {
      rowRef.current?.scrollIntoView({ block: "center" });
      rowRef.current?.querySelector<HTMLButtonElement>("button[aria-pressed]")?.focus({ preventScroll: true });
    });
    const timer = window.setTimeout(() => setJustSaved(false), 5000);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [justSaved, row.review_state, row.reviewed_at]);
  const clauseId = row.clause_id as string;
  const reviewed = row.review_state === "met" || row.review_state === "unmet";
  const busy = actions.clauseReviewBusy === clauseId;
  const needsMemo = choice === "met" || choice === "unmet";
  const canSave = choice !== null && name.trim() !== "" && (!needsMemo || memo.trim() !== "") && !busy;
  const where = `${row.source_document ?? "원문"}${row.page ? ` ${formatPage(row.page)}` : ""} · ${clauseRefText(clauseId)}`;

  const save = () => {
    if (!canSave || choice === null) return;
    storeReviewer(name.trim());
    // 저장된 뒤에만 입력을 닫는다 — 실패하면 고른 것 · 메모가 남는다 (DTL-09).
    // 43차 M25 — 화면이 읽은 확인 시각(없던 칸 · 바뀐 조항이면 null). 그사이 남이 확인했으면 서버가 막는다.
    const expected = row.review_state && row.review_state !== "stale" ? (row.reviewed_at ?? null) : null;
    void actions.saveClauseReview(clauseId, { state: choice, note: memo.trim() || null, decided_by: name.trim(), expected_decided_at: expected }).then((saved) => {
      if (!saved) return;
      setChoice(null);
      setMemo("");
      // 저장 단추가 사라져도 초점은 같은 줄 첫 선택 단추로 — 줄이 목록 뒤로 옮겨 가도 따라간다 (DTL-25 · 45차 M12 굴리기는 위 효과)
      setJustSaved(true);
    });
  };

  return (
    <li
      ref={rowRef}
      data-clause-row={clauseId}
      data-station-item={`qual:${row.rule_id}`}
      className={`rounded-lg border px-3 py-2 ${
        row.status === "FAIL" ? "border-cosmos-red/45 bg-cosmos-red/5" : "border-cosmos-border bg-cosmos-elevated/60"
      } ${reviewed ? "opacity-75" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Chip color={VERDICT_COLORS[row.status]}>{ELIGIBILITY_LABELS[row.status]}</Chip>
        <span className="min-w-0 flex-1 text-[13px] font-medium text-cosmos-text">{row.label}</span>
        {row.review_state === "stale" && <Chip color={COSMOS_COLORS.amber}>다시 확인</Chip>}
        {row.status === "CHECK" && row.check_side && (
          <span className="text-[12px] text-cosmos-amber">{CHECK_SIDE_LABELS[row.check_side]}</span>
        )}
        <span className="text-[12px] text-cosmos-muted">{eligibilityMethodLabel(row.method)}</span>
      </div>
      {row.clause_text ? (
        <blockquote className="mt-1.5 border-l-2 border-cosmos-border-strong pl-2">
          <p className="font-mono text-[12px] leading-5 text-cosmos-muted">{where}</p>
          <p className="text-[12.5px] leading-5 text-cosmos-text">「{row.clause_text}」</p>
        </blockquote>
      ) : (
        <p className="mt-1 break-words text-[12px] leading-5 text-cosmos-muted">근거: {row.source}</p>
      )}
      <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{row.reason}</p>
      {row.unlock_condition && row.status !== "PASS" && <UnlockLine condition={row.unlock_condition} ruleId={row.rule_id} />}
      {(reviewed || row.review_state === "pending") && (
        <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">
          {row.review_state === "pending" ? "보류" : "담당자 확인"} · {row.reviewed_by} · {formatDateTime(row.reviewed_at ?? null)}
          {row.review_note ? ` — ${row.review_note}` : ""}
        </p>
      )}
      {justSaved && reviewed && (
        <p className="mt-1 text-[12px] leading-5 text-cosmos-teal" role="status" data-clause-saved>
          저장했습니다 — {row.review_state === "unmet" ? "미충족 조항은 목록 위쪽(막는 조항)으로 옮겨 둡니다." : "확정한 조항은 목록 아래쪽으로 옮겨 둡니다."}
        </p>
      )}
      {row.review_state === "stale" && (
        <p className="mt-1 text-[12px] leading-5 text-cosmos-amber">
          조항이 바뀌었습니다 — 다시 확인하세요. 이전 확인: {row.reviewed_by} · {formatDateTime(row.reviewed_at ?? null)}
        </p>
      )}
      {row.requirement_id && <p className="mt-1 font-mono text-[12px] text-cosmos-muted">요구사항 {code(row.requirement_id)}</p>}
      {viewer ? (
        // 43차 M26 — 열람자는 조항 확인을 저장할 수 없다(서버도 막는다) · 단추 대신 이유를 적는다
        <p className="mt-2 text-[12px] text-cosmos-muted" title={VIEWER_LOCK_REASON} data-viewer-lock>{VIEWER_LOCK_LABEL}</p>
      ) : (
      <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label={`${row.label} ${clauseId} 확인`}>
        {CLAUSE_CHOICES.map((c) => (
          <button
            key={c.state}
            type="button"
            aria-pressed={choice === c.state}
            disabled={busy}
            onClick={() => setChoice(choice === c.state ? null : c.state)}
            className="rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            style={choice === c.state ? tintStyle(c.color) : undefined}
          >
            {c.label}
          </button>
        ))}
        {busy && <span className="text-[12px] text-cosmos-muted">저장 중…</span>}
      </div>
      )}
      {choice !== null && !viewer && (
        <div className="mt-2 flex flex-col gap-1.5">
          <input
            type="text"
            value={memo}
            maxLength={500}
            onChange={(event) => setMemo(event.target.value)}
            placeholder={needsMemo ? "근거 한 줄 (필수) — 무엇을 보고 확인했나" : "메모 (선택)"}
            aria-label="확인 근거 메모"
            className="rounded-md border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5 text-[12.5px] text-cosmos-text placeholder:text-cosmos-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
          />
          <input
            type="text"
            value={name}
            maxLength={60}
            onChange={(event) => setName(event.target.value)}
            placeholder="확인한 사람"
            aria-label="확인한 사람"
            className="rounded-md border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5 text-[12.5px] text-cosmos-text placeholder:text-cosmos-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!canSave}
              onClick={save}
              className="rounded-md border border-cosmos-cyan/60 px-3 py-1 text-[12px] font-semibold text-cosmos-cyan disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            >
              저장
            </button>
            <button
              type="button"
              onClick={() => setChoice(null)}
              className="rounded-md px-2 py-1 text-[12px] text-cosmos-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
            >
              취소
            </button>
            {needsMemo && memo.trim() === "" && (
              <span className="text-[12px] leading-5 text-cosmos-muted">충족·미충족은 근거 메모가 있어야 저장됩니다.</span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function EligibilityRow({ row: e }: { row: EligibilityResult }) {
  const code = useReqCode();
  return (
    <li className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2" data-station-item={`qual:${e.rule_id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Chip color={VERDICT_COLORS[e.status]}>{ELIGIBILITY_LABELS[e.status]}</Chip>
        <span className="min-w-0 flex-1 text-[13px] font-medium text-cosmos-text">{e.label}</span>
        {e.status === "CHECK" && e.check_side && (
          <span className="text-[12px] text-cosmos-amber">{CHECK_SIDE_LABELS[e.check_side]}</span>
        )}
        <span className="text-[12px] text-cosmos-muted">{eligibilityMethodLabel(e.method)}</span>
      </div>
      <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">
        {e.reason}
        {/* 사업 규모가 상한을 넘었을 때만 함께 참가 · 하도급 안내(33차 §3-B-5 · 34차 R33-S3) */}
        {isOverCeilingRow(e) && (
          <>
            {" "}
            <GuideContextLink href={GUIDE_LINKS.consortium}>{GUIDE_LINK_TEXT.consortium}</GuideContextLink>
          </>
        )}
      </p>
      {e.unlock_condition && e.status !== "PASS" && <UnlockLine condition={e.unlock_condition} ruleId={e.rule_id} />}
      <p className="mt-1 break-words text-[12px] leading-5 text-cosmos-muted">근거: {e.source}</p>
      {e.requirement_id && (
        <p className="mt-1 font-mono text-[12px] text-cosmos-muted">요구사항 {code(e.requirement_id)}</p>
      )}
    </li>
  );
}

function EligibilityList({ rows }: { rows: EligibilityResult[] }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map((e) => (
        <EligibilityRow key={e.rule_id} row={e} />
      ))}
    </ul>
  );
}

/**
 * 3단계 체크리스트로 — 상세 본문 스크롤 상자 안에서만 옮긴다(창 전체를 끌어 내리지 않는다).
 * 부드러운 스크롤은 쓰지 않는다 — 다시 그려지는 동안 멈추거나 끊겨 제자리에 남는 일이 있었다.
 */
function scrollToChecklist(): void {
  const target = document.getElementById("eligibility-checklist");
  const box = target?.closest<HTMLElement>('[data-panel-region="body"]');
  if (!target || !box) return;
  box.scrollTop = target.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 8;
}

/**
 * 「입찰 참가 가능 여부」 띠 — 상세 본문 **맨 위** (20차 §4-D-1 · ISSUE-140).
 *
 * 담당자 말: 「안 맞으면 입찰 신청 자체를 못 하니까 더 강조되면서 보여줘야 함.」 어느 노드를 골라도 먼저 보인다.
 * 불가 = 붉은 띠(막는 줄과 조항 원문) · 확인 필요 = 호박색(확인 전 조항 수) · 가능 = 녹색.
 * 본문 스크롤 상자 **안**에 둔다 — 상세 열의 머리·결정 블록 높이 예산(시인성 검사)을 건드리지 않는다.
 */
export function eligibilityBannerText(graph: CosmosGraph) {
  const report = graph.source.analysis.eligibility;
  const view = eligibilityGateView(graph.eligibility, report?.verdict ?? null);
  if (!view) return null;
  const synthetic = report
    ? !report.notice_available || report.procurement_id.startsWith("synthetic-")
    : Boolean(graph.source.scenario);
  let message: string;
  let button: string;
  if (view.verdict === "FAIL") {
    message = `참가할 수 없습니다 — ${view.blocking ? blockingText(view.blocking) : "막는 조건이 있습니다"}`;
    button = "3단계 보기";
  } else if (view.verdict === "CHECK") {
    message =
      view.total === 0
        ? view.docUnread
          ? `${view.docNote ?? DOC_UNREAD_GATE_LINE} · 공고 기본정보에서 확인할 것 ${view.fieldCheck}개`
          : `참가자격 조항 없음 · 공고 기본정보에서 확인할 것 ${view.fieldCheck}개`
        : view.pending === 0
          ? `조항 ${view.total}개 다 확정 · 공고 기본정보에서 확인할 것 ${view.fieldCheck}개`
          : `아직 확정 안 한 조항 ${view.pending}개(보류 포함 · 전체 ${view.total}개) — ${pendingSidesText(view)}`;
    button = "하나씩 확인하기";
  } else {
    message = `참가 가능 — 조항 ${view.done}개 확인 완료`;
    button = "3단계 보기";
  }
  const note =
    view.verdict === "CHECK" && view.pending > 0 && view.fieldCheck > 0
      ? `공고 기본정보에서 확인할 것 ${view.fieldCheck}개도 함께 남아 있습니다.`
      : null;
  return { view, synthetic, message, note, button };
}

function EligibilityBanner({ graph, onOpenChecklist }: { graph: CosmosGraph; onOpenChecklist: () => void }) {
  const text = eligibilityBannerText(graph);
  if (!text) return null;
  const { view, synthetic, message, note, button } = text;
  // 판정 4색 한 곳 — 쉬운 보기 판정 카드와 같은 상자 · 글자 (27차 §3-E · UNI-10).
  const tone = VERDICT_BOX_CLASS[view.verdict];
  return (
    // 알림(role=alert)이 아니다 — 상세 본문은 노드를 고를 때마다 다시 붙어서, 알림이면 누를 때마다 화면 낭독기가
    // 「참가할 수 없습니다」로 읽던 것을 끊는다. 늘 있는 요약이므로 이름 붙은 영역이다.
    <section
      data-eligibility-banner={view.verdict}
      aria-label="입찰 참가 가능 여부"
      className={`flex flex-col gap-1.5 rounded-lg border px-3 py-2 ${tone.box}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-semibold text-cosmos-secondary">입찰 참가 가능 여부</span>
        {synthetic && <DemoChip />}
      </div>
      <p className={`text-[13px] font-semibold leading-5 ${tone.text}`}>{message}</p>
      {note && <p className="text-[12px] leading-5 text-cosmos-secondary">{note}</p>}
      <button
        type="button"
        onClick={onOpenChecklist}
        className="w-fit rounded-md border border-cosmos-border-strong px-2.5 py-1 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
      >
        {button}
      </button>
    </section>
  );
}

function EligibilitySection({
  graph,
  actions,
  hideChecklist = false,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  /** 쉬운 보기(24차): 체크리스트는 판정 카드에 있다 — 여기서 다시 그리지 않는다(`id="eligibility-checklist"` 하나) */
  hideChecklist?: boolean;
}) {
  const { scenario } = graph.source;
  const report = graph.source.analysis.eligibility;
  return (
    <Section
      title="참가 가능 여부"
      aside={
        report ? (
          <Chip color={COSMOS_COLORS.cyan}>{report.llm_used ? "규칙+AI 판정" : "규칙 기반 판정"}</Chip>
        ) : scenario ? (
          <DemoChip />
        ) : undefined
      }
    >
      {report && (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            {/* 영문 판정값을 화면에 내보내지 않는다 (규칙 11). 어휘는 ELIGIBILITY_LABELS 하나에서 온다. */}
            <Chip color={VERDICT_COLORS[report.verdict]}>종합 {ELIGIBILITY_LABELS[report.verdict]}</Chip>
            <Chip color={COSMOS_COLORS.cyan}>{ELIGIBILITY_LABELS.PASS} {report.counts.passed}</Chip>
            <Chip color={COSMOS_COLORS.amber}>{ELIGIBILITY_LABELS.CHECK} {report.counts.check}</Chip>
            <Chip color={COSMOS_COLORS.red}>{ELIGIBILITY_LABELS.FAIL} {report.counts.failed}</Chip>
          </div>
          <p className="text-[12px] leading-5 text-cosmos-muted">
            판정 {formatDateTime(report.evaluated_at)} · 공고 기본정보{" "}
            {report.notice_available ? "사용" : "없음"} · 공고문 조항{" "}
            {report.clauses_status === "ok" ? `${report.clause_count ?? 0}개` : "못 읽음"} · 제안요청서 자격조항{" "}
            {report.requirements_available ? "사용" : "없음"}. 모호한 조건은 「가능」도 「불가」도 아닌
            「확인 필요」로 남깁니다.
          </p>
        </>
      )}

      {graph.eligibility.length === 0 ? (
        <NotRunNote>
          참가 가능 여부(가능 / 확인 필요 / 불가)는 아직 판정하지 않았습니다. 근거 없이 자격을 단정하지 않습니다.
        </NotRunNote>
      ) : hideChecklist ? (
        <p className="text-[12px] leading-5 text-cosmos-muted">
          조항 체크리스트는 위 「이 입찰에 참가할 수 있나요?」 카드에서 하나씩 확인합니다.
        </p>
      ) : (
        <EligibilityGroups graph={graph} actions={actions} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={actions.eligibilityBusy}
          onClick={() => actions.refreshEligibility({ useLlm: false })}
          className="rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
        >
          {actions.eligibilityBusy ? "판정 중…" : "다시 판정"}
        </button>
        {/* AI 가 꺼져 있으면 눌러도 규칙 결과만 온다 — 점검의 AI 체크상자처럼 잠그고 이유를 적는다 (DTL-27). */}
        <button
          type="button"
          disabled={actions.eligibilityBusy || actions.aiDraft === false}
          onClick={() => actions.refreshEligibility({ useLlm: true })}
          aria-describedby={actions.aiDraft === false ? "eligibility-ai-off" : undefined}
          className="rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-violet transition-colors hover:border-cosmos-cyan/60 disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
        >
          AI 보강 재판정{actions.aiDraft === false ? " (AI 꺼짐)" : ""}
        </button>
        {actions.aiDraft === false && (
          <span id="eligibility-ai-off" className="text-[12px] leading-5 text-cosmos-muted">
            AI 가 꺼져 있어 규칙으로만 다시 판정합니다.
          </span>
        )}
      </div>
      {actions.eligibilityError && (
        <p role="alert" className="rounded-lg border px-3 py-2 text-[12px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
          {actions.eligibilityError}
        </p>
      )}
    </Section>
  );
}

function NoticeDetail({
  graph,
  actions,
  stage,
  onSelect,
  embedded = false,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  /** 지금 보고 있는 단계 — 레일에서 고른 것 */
  stage: WorkflowStage;
  onSelect?: (id: string) => void;
  embedded?: boolean;
}) {
  const { notice, origin, scenario } = graph.source;
  const attachments = noticeAttachments(notice);
  const rfp = useRfpLink(origin.kind === "real" ? notice.id : "");
  const candidate = notice.candidate;
  const viewedStep = graph.steps[stage - 1] ?? currentStep(graph.steps);

  return (
    <>
      <Section title="공고 정보" aside={<OriginChip origin={origin} />}>
        <Facts
          items={[
            { label: "공고번호", value: notice.notice_no, mono: true },
            { label: "발주기관", value: notice.agency },
            { label: "공고일", value: formatDateTime(notice.published_at), mono: true },
            ...deadlineFacts(notice),
            { label: "예산", value: formatBudgetCompact(notice.budget), mono: true },
            { label: "지역", value: notice.region ?? "확인 필요" },
          ]}
        />
        <FirstBidNote notice={notice} />
        {notice.description && (
          <p className="text-[13px] leading-6 text-cosmos-secondary">{notice.description}</p>
        )}
        {(notice.source_url || rfp) && (
          <div className="flex flex-wrap gap-2">
            {notice.source_url && (
              <a href={notice.source_url} target="_blank" rel="noreferrer noopener" className={SOURCE_BUTTON}>
                나라장터 공고 원문 열기 ↗
              </a>
            )}
            {/* 첨부 목록 API 가 고른 제안요청서(사전규격 규격서 포함 · 원본 주소 · 2.9.1) */}
            {rfp && <RfpDownloadLink link={rfp} className={SOURCE_BUTTON} />}
          </div>
        )}
      </Section>

      {origin.kind === "real" && (
        <Section title={`첨부파일 ${attachments.length}`}>
          {attachments.length === 0 ? (
            <Empty>첨부파일 정보가 없습니다.</Empty>
          ) : (
            // 원본(나라장터) 주소로만 내려받는다 (20차 §4-E-1) — 로컬 사본은 내보내지 않는다.
            <AttachmentLinks
              items={attachments.map((file, index) => ({ key: `${index}:${file.url || file.name}`, ...attachmentLinkOf(file) }))}
            />
          )}
          {/* 요구사항을 이미 뽑았으면 「아직 실행되지 않았다」고 쓰지 않는다 — 어느 문서에서 몇 건인지 (DTL-07). */}
          <p className="text-[12px] text-cosmos-muted">
            {graph.source.parse
              ? `${parseSourceLabel(graph)} · ${graph.source.parse.document} · 요구사항 ${graph.counts.requirements}건`
              : embedded
                ? "제안요청서 첨부를 아직 읽지 않았습니다 — 4단계를 펼쳐 「공고 분석 시작」을 누르면 읽습니다."
                : "제안요청서 첨부를 아직 읽지 않았습니다 — 위 「공고 분석 시작」을 누르면 읽습니다."}
          </p>
          {/* 2.4.0 ⑦ — 전체 보기만(쉬운 보기는 맨 아래 덩어리에 같은 칸이 있다 · 두 번 그리지 않음) */}
          {!embedded && <NoticeQaPanel key={notice.id} itemId={notice.id} kind="bid" />}
        </Section>
      )}

      <Section
        title={scenario ? `우리 회사 적합도 (${SYNTHETIC_NOTICE})` : "우리 회사 적합도 (낱말 기준)"}
        aside={scenario ? <DemoChip /> : <Chip color={COSMOS_COLORS.blueText}>낱말 기준</Chip>}
      >
        {scenario ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip color={COSMOS_COLORS.cyan}>적합도 {scenario.semantic_match.label}</Chip>
              {scenario.semantic_match.matched_domains.map((d) => (
                <Chip key={d} color={COSMOS_COLORS.violet}>
                  {d}
                </Chip>
              ))}
            </div>
            <p className="text-[13px] leading-6 text-cosmos-secondary">{scenario.semantic_match.reason}</p>
          </>
        ) : candidate ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip color={candidate.tier === "high" ? COSMOS_COLORS.cyan : COSMOS_COLORS.blueText}>
                낱말 관련도 {labelOf(CANDIDATE_TIER_LABELS, candidate.tier)}
              </Chip>
              {[...candidate.matched_ai_keywords, ...candidate.matched_work_keywords].map((k) => (
                <Chip key={k} color={COSMOS_COLORS.violet}>
                  {k}
                </Chip>
              ))}
              <span className="text-[12px] text-cosmos-muted">판정 {labelOf(METHOD_LABELS, candidate.method)}</span>
            </div>
            <p className="text-[12px] leading-5 text-cosmos-muted">
              공고 글에 우리 사업 낱말(AI·교육 등)이 들어 있는지로만 고른 결과입니다. AI로 내용을 비교하지는 않습니다.
            </p>
          </>
        ) : (
          <NotRunNote />
        )}
      </Section>

      <DevCapabilitySection graph={graph} />

      <EligibilitySection graph={graph} actions={actions} hideChecklist={embedded} />

      <GatePanel graph={graph} actions={actions} onSelect={(id) => onSelect?.(id)} hideDecision={embedded} hideError={embedded} />

      {/* «지금 보고 있는 단계»다 — 예전에는 진행 현황의 다음 단계(currentStep)를 적어 제목과 달랐다(DTL-28). 이름은 레일 이름. */}
      <Section title="현재 보는 단계">
        <p className="text-[13px] text-cosmos-secondary">
          {viewedStep.id}. {viewedStep.label} — {viewedStep.summary}
        </p>
        {/* 레일 1단계로 오면 공고가 골라져 이 상세가 열린다 — 단계 개요의 「다른 공고 고르기」가 여기에도(27차 검수 R27REQ-04) */}
        <PageLink href="/opportunities">사업기회에서 다른 공고 고르기 →</PageLink>
      </Section>
    </>
  );
}

function RequirementDetail({
  req,
  noticeId,
  hasScenario,
  evidenceRun,
  hasProposal,
  hasAudit,
  auditState,
  pageApproximate,
  resolvedFindingIds,
  onSelect,
}: {
  req: RequirementView;
  /** 요구사항 정리표에서 이 행을 골라 열도록 `?req=` 를 싣는다 (27차 LNK-07). */
  noticeId: string;
  hasScenario: boolean;
  /** 공고 전체의 회사 근거 연결 상태 — 5단계 · KPI 와 같은 판정 (DTL-03) */
  evidenceRun: EvidenceRunState;
  hasProposal: boolean;
  hasAudit: boolean;
  /** 실검사에서 이 요구사항이 어떻게 판정됐는지 (없으면 미실행) */
  auditState: RequirementAuditState | null;
  /** HWP/HWPX는 페이지가 없어 문단 묶음으로 근사한 값이다 */
  pageApproximate: boolean;
  /** 담당자가 해결 처리한 발견 id */
  resolvedFindingIds: ReadonlySet<string>;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      <Section title={ITEM_TYPE_LABELS[itemTypeOf(req)]} aside={<SourceBadge kind={req.extraction_method === "HUMAN" ? "human" : "rule"} />}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[12px] text-cosmos-text" title={`저장 id ${req.requirement_id}`}>
            {displayCodeOf(req)}
          </span>
          <Chip color={ITEM_TYPE_COLORS[itemTypeOf(req)]}>{ITEM_TYPE_LABELS[itemTypeOf(req)]}</Chip>
          {criticalityOf(req) !== "normal" && (
            <Chip color={CRITICALITY_COLORS[criticalityOf(req)]}>{CRITICALITY_LABELS[criticalityOf(req)]}</Chip>
          )}
          {req.review_status && req.review_status !== "unreviewed" && (
            <Chip color={TONE_COLORS.pass}>{REVIEW_STATUS_LABELS[req.review_status]}</Chip>
          )}
          <Chip color={COSMOS_COLORS.blueText}>{req.category}</Chip>
          <Chip color={req.requirement_type === "mandatory" ? COSMOS_COLORS.red : COSMOS_COLORS.slate}>
            {REQUIREMENT_TYPE_LABELS[req.requirement_type]}
          </Chip>
          {/* 판정은 지도와 같은 낱말 · 색 하나(노드 상태) — 근거 연결 상태는 판정색 없는 중립 글자로(27차 검수 R27D-OWN-05:
              지도 「문제」 옆에 패널 「확인 필요」가 붙어 한 항목에 판정이 둘이었다). */}
          <Chip color={nodeColorHex({ state: req.nodeState })} title={STATE_LABELS[req.nodeState]}>
            {verdictWord(req.nodeState)}
          </Chip>
          {req.displayStatus !== "check" && (
            <span className="text-[12px] text-cosmos-secondary">{REQUIREMENT_STATUS_LABELS[req.displayStatus]}</span>
          )}
        </div>
        <p className="text-[15px] font-semibold text-cosmos-text">{req.title}</p>
        <p className="text-[13px] leading-6 text-cosmos-secondary">{req.content}</p>
        <Quote text={req.source_text} page={req.page} label="제안요청서 원문" />
        <p className="text-[12px] text-cosmos-muted">
          추출 방식: {METHOD_LABELS[req.extraction_method]}
          {pageApproximate ? " · 페이지는 문단 묶음 기준 근사값(HWP)" : ""}
        </p>
        <div className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2 text-[12px] leading-5 text-cosmos-secondary">
          <p>
            <span className="font-semibold text-cosmos-text">무엇</span> · {ITEM_TYPE_WHAT[itemTypeOf(req)]}
          </p>
          <p>
            <span className="font-semibold text-cosmos-text">왜 중요</span> ·{" "}
            {criticalityOf(req) === "blocker"
              ? `참가 자체를 막을 수 있는 조건입니다. 해결 전에는 「${DECISION_LABELS.GO}」를 저장할 수 없습니다.`
              : req.action_required
                ? "담당자의 행동(등록·서류 준비·참석)이 필요한 항목입니다. 「놓치면 안 되는 조건」에서 관리합니다."
                : req.requirement_type === "mandatory"
                  ? "필수 항목이라 제안서 초안과 제출 전 누락 점검에서 꼭 답해야 하는 항목입니다."
                  : "선택 항목이라 누락돼도 탈락 사유는 아니지만 가점·완성도에 영향을 줍니다."}
            {req.due_at ? ` 기한 ${formatDateTime(req.due_at)}.` : ""}
          </p>
        </div>
        {/* 같은 항목을 요구사항 정리표에서 — 그 행이 골라진 채로 열린다 (27차 LNK-07). */}
        <PageLink href={requirementSheetHref(noticeId, req.requirement_id)}>
          {SCREEN_NAMES.rfp}에서 이 항목 보기 →
        </PageLink>
      </Section>

      <Section
        title={hasScenario ? `연결된 근거 ${req.evidence.length}` : "연결된 근거"}
        aside={hasScenario ? <DemoChip label={SYNTHETIC_COMPANY} /> : undefined}
      >
        {!hasScenario ? (
          <>
            {evidenceRun.status === "not_run" ? (
              <NotRunNote>{evidenceRunSentence(evidenceRun)}</NotRunNote>
            ) : (
              <p className="text-[12.5px] leading-5 text-cosmos-secondary">{evidenceRunSentence(evidenceRun)}</p>
            )}
            {evidenceRun.status === "off" && <LedgerPickLink noticeId={noticeId} requirementId={req.requirement_id} />}
            <CompanyDocsLink />
          </>
        ) : req.evidence.length === 0 ? (
          // 근거 없음 자리에 회사자료로 — 지원사업 흐름과 같은 자리 (27차 LNK-03). 합성 시나리오는 합성 회사자료라 해당 없다
          // (요구사항 정리표 상태 줄과 같은 규칙 · 검증 G4-V4) — 여기는 hasScenario 가지라 링크를 두지 않는다.
          <Empty>연결된 회사 수행근거가 없습니다. 자동으로 충족 처리하지 않습니다.</Empty>
        ) : (
          <div className="flex flex-col gap-1.5">
            {req.evidence.map((ev) => (
              <RowButton
                key={ev.evidence_id}
                onClick={() => onSelect(evidenceNodeId(ev.evidence_id))}
                accent={ev.selected ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet}
              >
                <span className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium text-cosmos-text">{ev.document.document_name}</span>
                  <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">{formatPage(ev.document.page)}</span>
                  <span className="font-mono text-[12px] tabular-nums text-cosmos-secondary">
                    유사도 {formatSimilarity(ev.similarity_score)}
                  </span>
                  <Chip color={ev.selected ? COSMOS_COLORS.cyan : COSMOS_COLORS.slate}>{ev.selected ? "채택" : "후보"}</Chip>
                </span>
                <span className="mt-1 block truncate text-[12px] text-cosmos-secondary">“{ev.document.source_text}”</span>
                {ev.note && <span className="mt-1 block text-[12px] text-cosmos-muted">메모: {ev.note}</span>}
              </RowButton>
            ))}
          </div>
        )}
      </Section>

      <Section title={hasProposal ? `제안서 문장 ${req.sentences.length}` : "제안서 문장"}>
        {!hasProposal ? (
          <NotRunNote>제안서 초안을 아직 만들지 않았습니다.</NotRunNote>
        ) : req.sentences.length === 0 ? (
          <Empty>대응 문장 없음</Empty>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {req.sentences.map((s) => (
              <SentenceRow key={s.id} sentence={s} onSelect={onSelect} showLinks={false} />
            ))}
          </ul>
        )}
      </Section>

      <Section title="제출 전 점검 판단">
        {!hasAudit ? (
          <NotRunNote>제출 전 누락 점검을 아직 실행하지 않았습니다.</NotRunNote>
        ) : (
          <>
            {auditState && (
              <div className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip color={DISPLAY_STATUS_COLORS[auditState.status]}>
                    {REQUIREMENT_STATUS_LABELS[auditState.status]}
                  </Chip>
                  <Chip color={DETECTED_BY_COLORS[auditState.method]}>{DETECTED_BY_LABELS[auditState.method]}</Chip>
                  <span className="ml-auto font-mono text-[12px] tabular-nums text-cosmos-muted">
                    일치도 {formatSimilarity(auditState.score)}
                  </span>
                </div>
                {auditState.reason && (
                  <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{auditState.reason}</p>
                )}
              </div>
            )}
            {req.findings.length === 0 ? (
              <Empty>이 요구사항에 대한 점검 발견이 없습니다.</Empty>
            ) : (
              <div className="flex flex-col gap-1.5">
                {req.findings.map((f) => (
                  <div key={f.id} className="flex flex-col gap-1.5">
                    <FindingRow finding={f} onSelect={onSelect} resolved={resolvedFindingIds.has(f.id)} />
                    <p className="px-1 text-[12px] leading-5 text-cosmos-secondary">권고: {f.recommendation}</p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Section>
    </>
  );
}

/** 증빙 출처 배지. 합성 자료와 비식별한 실제 자료를 화면에서 구분한다. */
function EvidenceOriginChip({ ev }: { ev: EvidenceView }) {
  if (ev.synthetic) return <DemoChip label={SYNTHETIC_COMPANY} />;
  return (
    <Chip color={COSMOS_COLORS.cyan} title="공개 자료 기반 · 식별정보 비식별 처리">
      실제 자료 (비식별)
    </Chip>
  );
}

function EvidenceDetail({
  ev,
  resolvedFindingIds,
  onSelect,
}: {
  ev: EvidenceView;
  resolvedFindingIds: ReadonlySet<string>;
  onSelect: (id: string) => void;
}) {
  const code = useReqCode();
  return (
    <>
      <Section title={COMPANY_EVIDENCE} aside={<EvidenceOriginChip ev={ev} />}>
        <p className="text-[15px] font-semibold text-cosmos-text">{ev.document_name}</p>
        <Facts
          items={[
            { label: "유형", value: ev.doc_type },
            { label: "페이지", value: formatPage(ev.page), mono: true },
            { label: "상태", value: <Chip color={nodeColorHex({ state: ev.nodeState })} title={STATE_LABELS[ev.nodeState]}>{verdictWord(ev.nodeState)}</Chip> },
          ]}
        />
        <Quote text={ev.source_text} page={ev.page} label="문서 원문" />
      </Section>

      <Section title={`연결된 요구사항 ${ev.links.length}`}>
        {ev.links.length === 0 ? (
          <Empty>연결된 요구사항이 없습니다.</Empty>
        ) : (
          <div className="flex flex-col gap-1.5">
            {ev.links.map((link) => (
              <RowButton
                key={link.requirement_id}
                onClick={() => onSelect(requirementNodeId(link.requirement_id))}
                accent={link.selected ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet}
              >
                <span className="flex items-center gap-2">
                  <span className="font-mono text-[12px] text-cosmos-muted">{code(link.requirement_id)}</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-cosmos-text">{link.requirement.title}</span>
                  <span className="font-mono text-[12px] tabular-nums text-cosmos-secondary">
                    {formatSimilarity(link.similarity_score)}
                  </span>
                  <Chip color={link.selected ? COSMOS_COLORS.cyan : COSMOS_COLORS.slate}>{link.selected ? "채택" : "후보"}</Chip>
                </span>
                {link.note && <span className="mt-1 block text-[12px] text-cosmos-muted">메모: {link.note}</span>}
              </RowButton>
            ))}
          </div>
        )}
      </Section>

      <Section title="점검 관련 발견">
        {ev.findings.length === 0 ? (
          <Empty>이 근거와 관련된 발견이 없습니다.</Empty>
        ) : (
          <div className="flex flex-col gap-1.5">
            {ev.findings.map((f) => (
              <FindingRow key={f.id} finding={f} onSelect={onSelect} resolved={resolvedFindingIds.has(f.id)} />
            ))}
          </div>
        )}
      </Section>
    </>
  );
}

function ProposalDetail({
  graph,
  actions,
  onSelect,
  context,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  onSelect: (id: string) => void;
  context?: AnalysisContextParams | null;
}) {
  const section = graph.proposal;
  const generated = graph.source.analysis.proposal;

  if (!section) {
    return (
      <>
        <Section title="제안서 초안" stale={staleReadiness(graph) !== null}>
          <NotRunNote>
            제안서 초안을 아직 만들지 않았습니다. 아래 「제안서 초안 만들기」를 누르면 고른 회사 근거만으로 쓰고, 근거가 없는 문장은
            「확인 필요」로 남깁니다.
          </NotRunNote>
          <GenerateProposalButton graph={graph} actions={actions} />
        </Section>
      </>
    );
  }

  return (
    <>
      <Section
        title="제안서 초안"
        aside={
          generated ? (
            <span className="flex flex-wrap items-center justify-end gap-1">
              <Chip color={COSMOS_COLORS.cyan}>
                {GENERATION_METHOD_LABELS[generated.generation_method]}
              </Chip>
              <EvidenceScopeChip result={generated} />
            </span>
          ) : (
            <DemoChip />
          )
        }
      >
        <p className="text-[15px] font-semibold text-cosmos-text">{section.title}</p>
        <CoverageBar graph={graph} />
        {generated ? (
          <>
            <dl className="grid grid-cols-3 gap-2">
              {[
                { label: COMPANY_EVIDENCE, value: generated.evidence_grounded_count, color: GROUNDING_COLORS.COMPANY_EVIDENCE_GROUNDED },
                { label: "공고문 근거", value: generated.rfp_grounded_count, color: GROUNDING_COLORS.RFP_GROUNDED },
                { label: "확인 필요", value: generated.needs_review_count, color: COSMOS_COLORS.amber },
              ].map((item) => (
                <div key={item.label} className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-2 py-1.5">
                  <dt className="text-[12px] text-cosmos-muted">{item.label}</dt>
                  <dd className="font-mono text-[18px] font-semibold tabular-nums" style={{ color: item.color }}>
                    {item.value}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-[12px] leading-5 text-cosmos-muted">
              점검 대상 요구사항 {generated.mandatory_total}건(제안서 본문 기준 — 서식 · 참고 문구만 빼고 평가 항목도 셈 · 정리표 「필수」와 셈이 다름) 중 {generated.requirements_with_sentence}건에 대응 문장을
              만들었습니다. 생성 시각 {formatDateTime(generated.generated_at)}.
            </p>
            {generated.requirements_without_sentence.length > 0 && (
              <div className="text-[12px] leading-5 text-cosmos-amber">
                <CodeListDetails
                  label="문장 미생성"
                  codes={generated.requirements_without_sentence}
                  tone={COSMOS_COLORS.amber}
                />
                <p className="text-cosmos-muted">근거가 없어 지어내지 않았습니다.</p>
              </div>
            )}
            <ProposalDownloadLinks
              procurementId={generated.procurement_id}
              context={context}
              locked={syntheticMixLock(graph.source.analysis.proposal)}
            />
          </>
        ) : (
          <p className="text-[12px] text-cosmos-muted">
            {graph.counts.sentences}문장 · 확인 필요 {graph.counts.sentencesNeedingReview}건. 채택된 회사 근거만 사용하며
            근거 없는 문장은 자동 확정하지 않습니다.
          </p>
        )}
        <GenerateProposalButton
          graph={graph}
          actions={actions}
          label={generated ? "제안서 다시 만들기" : "제안서 초안 만들기"}
        />
      </Section>

      <Section title="문장별 근거">
        {section.sentences.length === 0 ? (
          <Empty>생성된 문장이 없습니다.</Empty>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {section.sentences.map((s) => (
              <SentenceRow key={s.id} sentence={s} onSelect={onSelect} showLinks canOpen={(id) => detailNodeOf(graph, id) !== null} />
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

type FindingGroup = CosmosGraph["cluster"]["findingGroups"][number];

/**
 * 발견을 «백엔드가 정한 묶음 순서»대로 나눈다.
 *
 * 순서를 화면이 다시 정하면 「참가 불가 위험을 맨 위로」라고 정한 rank(10 … 90)가 무너진다.
 * `graph.cluster.findingGroups` 는 이미 rank 순으로 내려오므로 그대로 쓴다.
 */
function findingsByGroup(graph: CosmosGraph): Array<{ group: FindingGroup; items: FindingView[] }> {
  return graph.cluster.findingGroups.map((group) => ({
    group,
    items: graph.findings.filter((f) => findingGroupKeyOf(f) === group.key),
  }));
}

/** 묶음 하나. 접혀 있어도 이름·미해결 건수·심각도는 보인다 (색만으로 구분하지 않는다). */
function FindingGroupBlock({
  group,
  items,
  onSelect,
  defaultOpen,
}: {
  group: FindingGroup;
  items: FindingView[];
  onSelect: (id: string) => void;
  defaultOpen?: boolean;
}) {
  const blocking = items.filter((f) => f.severity === "critical" && !f.resolved).length;
  return (
    <Collapsible
      title={group.label}
      defaultOpen={defaultOpen ?? (group.open > 0 && isSevere({ severity: group.severity }))}
      summary={
        <span className="flex flex-wrap items-center justify-end gap-1">
          {blocking > 0 && <Chip color={COSMOS_COLORS.red}>탈락 위험 {blocking}</Chip>}
          <Chip color={group.open > 0 ? SEVERITY_COLORS[group.severity] : TONE_COLORS.pass}>
            {group.open > 0 ? `${SEVERITY_LABELS[group.severity]} · 미해결 ${group.open}` : "모두 해결 처리"}
          </Chip>
          <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">전체 {group.total}</span>
        </span>
      }
    >
      <div className="flex flex-col gap-1.5">
        {[...items]
          .sort((a, b) => Number(a.resolved) - Number(b.resolved) || severityRank(a.severity) - severityRank(b.severity))
          .map((f) => (
            <FindingRow key={f.id} finding={f} onSelect={onSelect} resolved={f.resolved} />
          ))}
      </div>
    </Collapsible>
  );
}

function AuditDetail({
  graph,
  actions,
  onSelect,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  onSelect: (id: string) => void;
}) {
  const run = graph.source.analysis.audit;
  return (
    <>
      <Section
        title="제출 전 누락 점검"
        aside={
          run ? (
            <Chip color={COSMOS_COLORS.cyan}>{run.llm_used ? "규칙 + AI로 검사" : "규칙으로 검사"}</Chip>
          ) : graph.hasAudit ? (
            <DemoChip />
          ) : undefined
        }
      >
        {graph.hasAudit ? (
          <>
            {/* 10-31 최종 점검 — 점검 결과가 있으면 아래 「점검 대상 요구사항 n건 중 …」 한 줄만(같은 반영 수가 두 줄이었다) */}
            <CoverageBar graph={graph} breakdown={!run} />
            <BlockingBanner count={graph.counts.findingsBlockingOpen} />
            <p className="text-[12px] leading-5 text-cosmos-muted">
              초안을 공고 원문과 맞춰 봤습니다 — 찾은 문제 {graph.counts.findings}건 · 그중{" "}
              {seriousText(graph.counts.findingsHigh, graph.counts.findingsBlocking, "건")} · 해결 {graph.counts.findingsResolved}건
            </p>
            {run && (
              <p className="text-[12px] leading-5 text-cosmos-muted">
                {/* 점검 문장 수는 6단계 「문장 n」과 셈이 달라 두 수로 보였다 — 처음 쓰는 직원에게는 6단계 수 하나면 된다 (UI d) */}
                점검 대상 요구사항 {run.coverage.total}건 중 반영 {run.coverage.covered} · 일부 반영 {run.coverage.partial} · 빠짐{" "}
                {run.coverage.missing}
              </p>
            )}
            {run?.coverage.truncated && (
              <p className="text-[12px] leading-5 text-cosmos-amber">
                ⚠ 한 번에 검사하는 수에 한도가 있어 요구사항 후보 {run.coverage.candidate_count ?? "?"}건 중{" "}
                {run.coverage.total}건만 검사했습니다. 반영 상태는 검사한 범위 안에서만 유효합니다.
              </p>
            )}
            {run?.source_document && (
              <p className="text-[12px] text-cosmos-secondary">검사 문서: {run.source_document}</p>
            )}
            {run?.llm_note && <p className="text-[12px] text-cosmos-amber">{run.llm_note}</p>}
            {run && (
              <p className="text-[12px] text-cosmos-muted" title={run.id}>
                점검 시각 {formatDateTime(run.created_at)}
              </p>
            )}
          </>
        ) : (
          <NotRunNote>
            제출 전 누락 점검을 아직 실행하지 않았습니다. 아래 초안을 확인하고 「제출 전 점검」을 누르면 요구사항 누락 ·
            수치 불일치 · 근거 없는 주장을 원문과 대조해 찾아냅니다.
          </NotRunNote>
        )}
      </Section>

      <Section title="검사 실행" stale={staleReadiness(graph) !== null}>
        <AuditorSection graph={graph} actions={actions} />
      </Section>

      <Section
        title="발견 목록"
        aside={
          graph.hasAudit && graph.findings.length > 0 ? (
            <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">
              미해결 {graph.counts.findingsOpen} · 해결 {graph.counts.findingsResolved}
            </span>
          ) : undefined
        }
      >
        {!graph.hasAudit ? (
          <Empty>검사를 실행하면 여기에 발견 항목이 표시됩니다.</Empty>
        ) : graph.findings.length === 0 ? (
          <Empty>발견된 문제가 없습니다.</Empty>
        ) : (
          <div className="flex flex-col gap-2.5">
            {findingsByGroup(graph).map(({ group, items }) => (
              <FindingGroupBlock key={group.key} group={group} items={items} onSelect={onSelect} />
            ))}
          </div>
        )}
        <ResolvedButGone graph={graph} />
      </Section>
    </>
  );
}


function readStoredReviewer(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(REVIEWER_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

/**
 * 해결 처리자 입력칸의 기본값. 로그인했으면 그 이름, 아니면 지금까지처럼 브라우저 기억값이다.
 * 이 이름이 「누가 이 발견 항목을 해결했다고 했는가」로 그대로 저장되므로, 손으로 적어
 * 사람마다 다르게 쓰이는 일을 줄인다. 잠그지는 않는다 — 대신 적는 경우가 있다.
 */
function defaultResolutionReviewer(): string {
  return currentUserName() || readStoredReviewer();
}

function storeReviewer(name: string): void {
  try {
    window.localStorage.setItem(REVIEWER_STORAGE_KEY, name);
  } catch {
    // 저장 실패는 무시한다 — 이번 요청은 그대로 보낸다.
  }
}

/** 재검사 결과에는 없지만 예전에 해결 처리해 둔 항목 — 초안을 고쳐 실제로 사라진 것들이다. */
function ResolvedButGone({ graph }: { graph: CosmosGraph }) {
  const currentKeys = new Set(graph.findings.map((f) => f.resolutionKey));
  const gone = graph.resolutions.filter((r) => r.status === "resolved" && !currentKeys.has(r.key));
  if (gone.length === 0) return null;
  return (
    <div className="rounded-lg border border-cosmos-cyan/40 bg-cosmos-cyan/10 px-3 py-2 text-[12px] leading-5 text-cosmos-secondary">
      <span className="font-semibold text-cosmos-cyan">재검사에서 사라진 해결 항목 {gone.length}건</span> —{" "}
      {gone
        .slice(0, 6)
        .map((r) => `${findingTypeLabel(r.finding_type)}${r.requirement_id ? ` ${requirementCode(graph.requirements, r.requirement_id)}` : ""}`)
        .join(", ")}
      . 담당자가 해결 처리한 뒤 다시 점검했을 때 더 이상 찾지 않은 항목입니다.
    </div>
  );
}

/** 담당자 해결/재오픈 입력. 검사 결과를 바꾸는 것이 아니라 사람의 판단을 기록한다. */
function ResolutionForm({
  finding,
  noticeId,
  actions,
}: {
  finding: FindingView;
  noticeId: string;
  actions: AnalysisActions;
}) {
  const [reviewer, setReviewer] = useState(defaultResolutionReviewer);
  /**
   * 「무엇을 어떻게 고쳤는지」는 점검 결과를 바꾸지 않고 사람의 판단만 남기는 기록이다.
   * 저장 전에 공고를 바꾸거나 새로고침하면 말없이 사라졌다 (TASK-012).
   * 발견별로 임시 저장하고 돌아오면 되살린다.
   */
  // 공고 · 발견 열쇠(resolutionKey)로 — 번호(AF-001)만 쓰면 공고 · 점검 회차마다 겹쳐 다른 공고의 메모가 되살아났다(2.0.6).
  const noteKey = `finding-note:${noticeId}:${finding.resolutionKey}`;
  const [note, setNote] = useState(() => loadDraft(noteKey));
  // 열쇠가 바뀌면(다른 공고 · 발견을 같은 칸으로 다시 그림) 그 저장본으로 다시 채운다(2.0.6 — 판정 칸과 같은 규칙)
  const [noteLoadedKey, setNoteLoadedKey] = useState(noteKey);
  if (noteLoadedKey !== noteKey) {
    setNoteLoadedKey(noteKey);
    setNote(loadDraft(noteKey));
  }
  const editNote = (value: string) => {
    setNote(value);
    saveDraft(noteKey, value);
  };
  const trimmedReviewer = reviewer.trim();
  const nextStatus = finding.resolved ? "open" : "resolved";

  const submit = () => {
    if (!trimmedReviewer) return;
    storeReviewer(trimmedReviewer);
    // 저장된 뒤에만 메모 · 임시 저장본을 비운다 — 실패하면 적은 글이 남는다 (DTL-09).
    void actions
      .setFindingResolution(finding, { status: nextStatus, reviewer: trimmedReviewer, note: note.trim() || null })
      .then((saved) => {
        if (!saved) return;
        clearDraft(noteKey);
        setNote("");
      });
  };

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="resolution-reviewer" className="text-[12px] text-cosmos-secondary">
          검토자
        </label>
        <input
          id="resolution-reviewer"
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          placeholder="이름"
          maxLength={60}
          className="mc-focus min-h-8 w-32 rounded-md border border-cosmos-border bg-cosmos-bg/60 px-2 text-[12.5px] text-cosmos-text placeholder:text-cosmos-muted"
        />
      </div>
      <label htmlFor="resolution-note" className="sr-only">
        처리 메모
      </label>
      <textarea
        id="resolution-note"
        value={note}
        onChange={(e) => editNote(e.target.value)}
        rows={2}
        maxLength={2000}
        placeholder={
          finding.resolved
            ? "다시 여는 이유 (선택)"
            : "무엇을 어떻게 고쳤는지 (예: 운영계획에 만족도 조사 절차 문장 추가)"
        }
        className="mc-focus w-full resize-y rounded-md border border-cosmos-border bg-cosmos-bg/60 px-2.5 py-1.5 text-[12.5px] leading-5 text-cosmos-text placeholder:text-cosmos-muted"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={actions.resolutionBusy || !trimmedReviewer}
          onClick={submit}
          className={`mc-focus min-h-8 rounded-lg px-3 text-[12px] font-semibold transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45 ${
            finding.resolved ? "border border-cosmos-amber/60 text-cosmos-amber" : "bg-cosmos-blue-strong text-white"
          }`}
        >
          {actions.resolutionBusy ? "저장 중…" : finding.resolved ? "다시 열기" : "해결로 전환"}
        </button>
        {!trimmedReviewer && <span className="text-[12px] text-cosmos-muted">검토자 이름을 적어야 기록됩니다</span>}
      </div>
      {actions.resolutionError && (
        <p role="alert" className="rounded-lg border px-3 py-2 text-[12px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
          {actions.resolutionError}
        </p>
      )}
      <p className="text-[12px] leading-5 text-cosmos-muted">
        해결 처리는 담당자의 판단으로 기록되며 점검 결과 자체는 바뀌지 않습니다. 초안을 실제로 고쳤다면
        「제출 전 점검」으로 다시 점검하세요 — 다시 점검했을 때 항목이 사라지는 것이 진짜 확인입니다.
      </p>
    </div>
  );
}

function ResolutionHistory({ resolution }: { resolution: FindingResolution }) {
  const resolved = resolution.status === "resolved";
  return (
    <div
      className="rounded-lg border px-3 py-2 text-[12.5px] leading-5"
      style={tintStyle(resolved ? TONE_COLORS.pass : COSMOS_COLORS.amber)}
    >
      <p className="font-semibold">
        {resolved ? "해결됨" : "다시 열림"} · {resolution.reviewer} · {formatDateTime(resolution.decided_at)}
      </p>
      {resolution.note && <p className="mt-0.5 text-cosmos-text">{resolution.note}</p>}
      {/* 내부 키 · 실행 id 는 화면 문장에 내지 않는다 — 개발자용 title 로만 (DTL-32). */}
      <p
        className="mt-0.5 text-[12px] text-cosmos-muted"
        title={`${resolution.method} · ${resolution.key}${resolution.audit_run_id ? ` · ${resolution.audit_run_id}` : ""}`}
      >
        사람이 기록
      </p>
    </div>
  );
}

function FindingDetail({
  finding,
  noticeId,
  realRun,
  actions,
  onSelect,
}: {
  finding: FindingView;
  /** 이 발견이 속한 공고 — 해결 메모 임시 저장 키에 넣는다(2.0.6) */
  noticeId: string;
  /** 실제 검사 결과인지 (데모 시나리오 발견이면 false) */
  realRun: boolean;
  actions: AnalysisActions;
  onSelect: (id: string) => void;
}) {
  const requirement = finding.requirement;
  const evidence = finding.evidence;
  return (
    <>
      <Section
        title="점검에서 찾은 문제"
        aside={
          finding.resolved ? (
            <Chip color={TONE_COLORS.pass}>담당자 해결 처리</Chip>
          ) : realRun ? (
            <Chip color={COSMOS_COLORS.amber}>미해결</Chip>
          ) : (
            <DemoChip />
          )
        }
      >
        <div className="flex flex-wrap items-center gap-1.5">
          {finding.severity === "critical" && <Chip color={COSMOS_COLORS.red}>탈락 위험</Chip>}
          <Chip color={SEVERITY_COLORS[finding.severity]}>심각도 {SEVERITY_LABELS[finding.severity]}</Chip>
          {/* 어느 묶음에서 왔는지 — 목록에서 본 이름과 상세가 같은 말을 써야 찾을 수 있다. */}
          {finding.group_label && <Chip color={COSMOS_COLORS.slate}>묶음 {finding.group_label}</Chip>}
          {finding.detected_by && (
            <Chip color={DETECTED_BY_COLORS[finding.detected_by]}>
              {DETECTED_BY_LABELS[finding.detected_by]}
            </Chip>
          )}
          {typeof finding.score === "number" && (
            <Chip color={COSMOS_COLORS.slate}>일치도 {formatSimilarity(finding.score)}</Chip>
          )}
          <span className="font-mono text-[12px] text-cosmos-muted">{finding.id}</span>
        </div>
        <p className="text-[15px] font-semibold text-cosmos-text">{findingTypeLabel(finding.finding_type)}</p>
        {finding.severity === "critical" && (
          <p className="text-[12.5px] leading-5 text-cosmos-red">{BLOCKING_WHAT}</p>
        )}
        {requirement && (
          <p className="text-[13px] text-cosmos-secondary">
            대상 <span className="font-mono">{displayCodeOf(requirement)}</span> {requirement.title}
          </p>
        )}
        {finding.response_scope && (
          <p className="text-[12.5px] text-cosmos-secondary">
            어디서 답하는 항목인가: {RESPONSE_SCOPE_LABELS[finding.response_scope] ?? "확인 필요"}
          </p>
        )}
      </Section>

      <Section title="왜 문제인가">
        <p className="text-[13px] leading-6 text-cosmos-secondary">{FINDING_TYPE_WHY[finding.finding_type]}</p>
      </Section>

      <Section title="관련 제안요청서 원문">
        {finding.source_text ? (
          <Quote text={finding.source_text} page={finding.source_page} label="제안요청서" />
        ) : (
          // 값이 없다는 것과 «검사하지 않았다»는 것은 다른 말이다. 「없음」으로 뭉치지 않는다.
          <Empty>이 점검은 제안요청서 원문을 인용하지 않았습니다(원문과 맞춰 보는 항목이 아닙니다).</Empty>
        )}
      </Section>

      <Section title="제안서 문장">
        {finding.proposal_text ? (
          <Quote text={finding.proposal_text} label={finding.sentence_id ?? "제안서 초안"} />
        ) : finding.finding_type === "missing_requirement" || finding.finding_type === "missing_document" ? (
          <p className="rounded-lg border border-dashed border-cosmos-red/50 px-3 py-2 text-[13px] text-cosmos-red">
            대응 문장 없음 — 초안에서 이 항목에 답하는 문장을 찾지 못했습니다. 그것이 이 발견의 내용입니다.
          </p>
        ) : (
          <Empty>이 검사에서는 제안서 문장을 확인하지 않았습니다.</Empty>
        )}
      </Section>

      <Section title="회사 근거">
        {evidence ? (
          <RowButton onClick={() => onSelect(evidenceNodeId(evidence.id))} accent={COSMOS_COLORS.violet}>
            <span className="block truncate font-medium text-cosmos-text">{evidence.document_name}</span>
            <span className="mt-1 block truncate text-[12px] text-cosmos-secondary">
              {formatPage(evidence.page)} “{evidence.source_text}”
            </span>
          </RowButton>
        ) : finding.finding_type === "unsupported_claim" ? (
          <p className="rounded-lg border border-dashed border-cosmos-amber/50 px-3 py-2 text-[13px] text-cosmos-amber">
            연결된 회사 근거가 없습니다 — 그것이 이 발견의 내용입니다.
          </p>
        ) : (
          <Empty>이 검사에서는 회사 근거를 확인하지 않았습니다.</Empty>
        )}
      </Section>

      <Section title="담당자가 할 일 · 수정 권고">
        <p className="rounded-lg border border-cosmos-amber/40 bg-cosmos-amber/10 px-3 py-2 text-[13px] leading-6 text-cosmos-text">
          {finding.recommendation}
        </p>
      </Section>

      <Section
        title="담당자 해결 처리"
        aside={<Chip color={finding.resolved ? TONE_COLORS.pass : COSMOS_COLORS.amber}>{finding.resolved ? "해결됨" : "미해결"}</Chip>}
      >
        {finding.resolution && <ResolutionHistory resolution={finding.resolution} />}
        <ResolutionForm finding={finding} noticeId={noticeId} actions={actions} />
      </Section>

      <div className="flex flex-wrap gap-2">
        {requirement && (
          <button
            type="button"
            onClick={() => onSelect(requirementNodeId(requirement.requirement_id))}
            className="rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
          >
            요구사항 보기
          </button>
        )}
        <button
          type="button"
          onClick={() => onSelect(PROPOSAL_NODE_ID)}
          className="rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
        >
          제안서 보기
        </button>
      </div>
    </>
  );
}

/**
 * 발견 묶음 노드 상세.
 *
 * 예전에는 3D 에서 묶음 구체를 눌러도 상세 패널 «본문이 통째로 비어» 있었다 —
 * 종류별 분기에 `finding-group` 자리가 없어 body 가 undefined 로 남았기 때문이다.
 * 발견이 10건을 넘으면 3D 는 묶음만 그리므로, 그 상태에서는 아무 발견도 열어볼 수 없었다.
 */
function FindingGroupDetail({
  graph,
  node,
  onSelect,
}: {
  graph: CosmosGraph;
  node: CosmosNode;
  onSelect: (id: string) => void;
}) {
  const entry = findingsByGroup(graph).find(({ group }) => group.key === node.groupKey);
  if (!entry || entry.items.length === 0) {
    return (
      <Section title="발견 묶음">
        <Empty>이 묶음에 해당하는 발견을 찾지 못했습니다. 아래 「전체 발견 목록 보기」에서 확인하세요.</Empty>
        <RowButton onClick={() => onSelect(AUDIT_NODE_ID)}>전체 발견 목록 보기</RowButton>
      </Section>
    );
  }
  const { group, items } = entry;
  const blocking = items.filter((f) => f.severity === "critical" && !f.resolved).length;
  return (
    <>
      <Section
        title="발견 묶음"
        aside={
          <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">
            미해결 {group.open} / 전체 {group.total}
          </span>
        }
      >
        <p className="text-[15px] font-semibold text-cosmos-text">{group.label}</p>
        <BlockingBanner count={blocking} />
        <p className="text-[12px] leading-5 text-cosmos-muted">
          같은 원인에서 나온 발견을 한 묶음으로 모았습니다. 묶음의 심각도는 그 안에서 가장 높은 것을 씁니다 —{" "}
          {SEVERITY_LABELS[group.severity]}. 항목을 누르면 원문·초안·조치가 열립니다.
        </p>
      </Section>

      <Section title="이 묶음의 발견">
        <div className="flex flex-col gap-1.5">
          {[...items]
            .sort((a, b) => Number(a.resolved) - Number(b.resolved) || severityRank(a.severity) - severityRank(b.severity))
            .map((f) => (
              <FindingRow key={f.id} finding={f} onSelect={onSelect} resolved={f.resolved} />
            ))}
        </div>
      </Section>

      <RowButton onClick={() => onSelect(AUDIT_NODE_ID)}>다른 묶음까지 전체 발견 목록 보기</RowButton>
    </>
  );
}

/** 요구사항 묶음 노드 상세. 발견 묶음과 같은 이유로 본문이 비어 있던 자리다. */
function RequirementGroupDetail({
  graph,
  node,
  onSelect,
}: {
  graph: CosmosGraph;
  node: CosmosNode;
  onSelect: (id: string) => void;
}) {
  const type = node.itemType;
  const category = graph.cluster.categories.find((c) => c.key === type);
  const members = type ? graph.requirements.filter((req) => itemTypeOf(req) === type) : [];
  if (!type || members.length === 0) {
    return (
      <Section title="요구사항 묶음">
        <Empty>이 묶음에 해당하는 항목을 찾지 못했습니다.</Empty>
      </Section>
    );
  }
  return (
    <>
      <Section
        title="요구사항 묶음"
        aside={
          <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">
            {members.length}건{category && category.attention > 0 ? ` · 확인 필요 ${category.attention}` : ""}
          </span>
        }
      >
        <p className="text-[15px] font-semibold text-cosmos-text">{ITEM_TYPE_LABELS[type]}</p>
        <p className="text-[12.5px] leading-5 text-cosmos-secondary">{ITEM_TYPE_WHAT[type]}</p>
        {category?.blocker && (
          <p role="note" className="rounded-lg border px-3 py-2 text-[12.5px] leading-5" style={tintStyle(COSMOS_COLORS.red)}>
            <span className="font-semibold">미해결 참가 차단 조건 있음</span> — 이 묶음에 참가 자체가 막힐 수 있는 항목이 있습니다.
          </p>
        )}
      </Section>

      <Section title="이 묶음의 항목">
        <div className="flex flex-col gap-1.5">
          {members.map((req) => (
            <RequirementMiniRow key={req.id} req={req} onSelect={onSelect} />
          ))}
        </div>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------------------
// Human Review
// ---------------------------------------------------------------------------

export function HumanReviewBlock({
  graph,
  decision,
  onDecision,
  decisionHere = false,
}: {
  graph: CosmosGraph;
  decision: ReviewDecision;
  onDecision: (d: ReviewDecision) => void;
  /** 참여 결정 칸이 바로 위에 있다(쉬운 보기 ⑥) — 안내 문장이 없는 곳을 가리키지 않게 (EZ-17) */
  decisionHere?: boolean;
}) {
  const highOpen = graph.counts.findingsHighOpen;
  // 참가 차단은 승인 버튼 옆에서도 보여야 한다 — 「높음」 문구에 섞이면 제출이 막힌다는 뜻이 사라진다.
  const blockingOpen = graph.counts.findingsBlockingOpen;
  /**
   * 구버전 결과로는 승인할 수 없다.
   *
   * 이 화면의 Coverage·발견 건수는 이전 요구사항 기준으로 잰 값이다. 그것을 보고 누른 승인은
   * 근거가 없다. backend 도 같은 이유로 422 를 낸다(review_service). 보류는 막지 않는다 —
   * 「지금은 판단 보류」가 이 상황에서 정확한 기록이다.
   */
  const stale = staleReadiness(graph);
  const notRun = useNotRunLabel("제출 전 누락 점검 아직 안 함");
  // 43차 M17 · E2E-08 — 점검 전에도 남은 참가 차단 · 확인 전 자격 조항 수를 승인 단추 옆에(승인을 막지는 않는다 — 대표가 정할 일)
  const conditionBlockers = graph.source.analysis.conditions?.counts.blocker ?? 0;
  // 45차 M6 — 위 「참가 여부」 카드와 같은 수(확정 안 한 참가자격 조항 · 보류 포함). 예전에는 확인 필요 판정 줄 전체(기본정보 줄 포함)를 셌다.
  const pendingClauses = eligibilityGateView(graph.eligibility, graph.source.analysis.eligibility?.verdict ?? null)?.pending ?? 0;
  // 45차 M4 — 열람자는 누를 수 없다(서버 403 인데 화면이 「임시 (저장 전)」 · 「✓ 다시 검토」로 바뀌었다)
  const viewer = useViewerLock();
  // 45차 M17 — 전체 보기 아래에 늘 붙어 1920×1080 에서 상세가 150~300px 만 보였다 · 접으면 머리 한 줄만
  const [folded, setFolded] = useState(false);
  const summary = decision === "approved" ? "검토 승인" : decision === "hold" ? "다시 검토" : "검토 전";
  return (
    <div data-tour="panel-human-review" data-panel-region="decision" className={`shrink-0 border-t border-cosmos-border px-4 ${folded ? "py-2" : "py-3"}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted" title="초안 검토(검토 승인 · 다시 검토) — 입찰 참여 여부는 「참여 · 보류 · 참여 안 함」에서 따로 저장합니다">담당자 최종 결정{folded ? ` · ${summary}` : ""}</p>
        <span className="flex items-center gap-2">
          {!folded && <span className="text-[12px] text-cosmos-muted">{graph.hasAudit ? referenceNote(graph) : notRun}</span>}
          <button type="button" className="mc-focus rounded px-1.5 py-0.5 text-[12px] text-cosmos-secondary hover:text-cosmos-text" aria-expanded={!folded} onClick={() => setFolded((v) => !v)}>
            {folded ? "펼치기 ▴" : "접기 ▾"}
          </button>
        </span>
      </div>
      {!folded && (<>
      {/* 좁은 패널에서 참가 차단 경고가 옆에 붙으면 단추 글자가 단어 중간에서 끊겼다 — 단추는 줄이지 않고 경고를 다음 줄로 (DTL 검증 R-7) */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={stale !== null || viewer}
          title={viewer ? VIEWER_LOCK_REASON : stale ? staleBlockReason(stale) : undefined}
          onClick={async () => {
            // 눌린 승인을 다시 누르면 저장된 승인이 「검토 전」으로 돌아간다 — 확인 없이 지우지 않는다 (DTL-08 · 45차 L5 화면 안 창).
            if (decision === "approved" && !(await requestConsent({ title: "「검토 승인」을 취소할까요?", body: "저장된 「검토 승인」이 「검토 전」으로 돌아갑니다.", confirmLabel: "취소하기", cancelLabel: "그대로 두기" }))) return;
            onDecision(decision === "approved" ? null : "approved");
          }}
          aria-pressed={decision === "approved"}
          aria-describedby={stale ? "review-stale-reason" : undefined}
          className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan disabled:cursor-not-allowed disabled:opacity-45 ${
            decision === "approved"
              ? "bg-cosmos-blue-strong text-white"
              : "border border-cosmos-border-strong text-cosmos-text hover:border-cosmos-cyan/60"
          }`}
        >
          검토 승인
        </button>
        <button
          type="button"
          disabled={viewer}
          title={viewer ? VIEWER_LOCK_REASON : undefined}
          onClick={async () => {
            if (decision === "hold" && !(await requestConsent({ title: "「다시 검토」를 취소할까요?", body: "저장된 「다시 검토」가 「검토 전」으로 돌아갑니다.", confirmLabel: "취소하기", cancelLabel: "그대로 두기" }))) return;
            onDecision(decision === "hold" ? null : "hold");
          }}
          aria-pressed={decision === "hold"}
          className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan disabled:cursor-not-allowed disabled:opacity-45 ${
            decision === "hold"
              ? "bg-cosmos-amber text-cosmos-bg"
              : "border border-cosmos-amber/50 text-cosmos-amber hover:bg-cosmos-amber/10"
          }`}
        >
          다시 검토
        </button>
        {blockingOpen > 0 ? (
          <p className="min-w-[12rem] flex-1 text-[12px] leading-4 text-cosmos-red" role="note">
            탈락 위험 {blockingOpen}건 안 고침 — 이대로 내면 형식 요건에서 탈락할 수 있습니다
            {highOpen > blockingOpen ? ` · ${SEVERITY_LABELS.high}(${SEVERITY_LABELS.critical} 포함) ${highOpen}건` : ""}
          </p>
        ) : (
          highOpen > 0 &&
          decision !== "hold" && (
            <p className="min-w-[12rem] flex-1 text-[12px] leading-4 text-cosmos-amber" role="note">
              {SEVERITY_LABELS.high} {highOpen}건 안 고침
            </p>
          )
        )}
      </div>
      {(conditionBlockers > 0 || pendingClauses > 0) && (
        <p className="mt-1.5 text-[12px] leading-4 text-cosmos-amber" role="note" data-review-open-conditions>
          남은 것: 참가 차단 {conditionBlockers}건 · 확인 전 자격 조항 {pendingClauses}건 — 「검토 승인」은 초안 검토 기록일 뿐, 이 조건들을 풀지 않습니다.
        </p>
      )}
      {viewer && <p className="mt-1.5 text-[12px] leading-4 text-cosmos-muted">{VIEWER_LOCK_LABEL} — {VIEWER_LOCK_REASON}</p>}
      {/* 잠긴 이유를 풍선 도움말에만 두지 않는다 — 터치 · 키보드로도 읽힌다 (DTL-31). */}
      {stale && (
        <p id="review-stale-reason" className="mt-1.5 text-[12px] leading-4 text-cosmos-amber" title={staleBlockReason(stale)}>
          검토 승인 잠김 — {STALE_CARD_LABEL}입니다. 새 제안서 버전을 만든 뒤 승인하세요.
        </p>
      )}
      <p className="mt-2 text-[12px] text-cosmos-secondary" aria-live="polite">
        {decision === "approved"
          ? "검토 승인 — 담당자가 확인했습니다. 시스템이 자동 제출하지 않습니다."
          : decision === "hold"
            ? "다시 검토 — 수정 권고를 반영한 뒤 다시 봅니다."
            : "검토 승인 또는 다시 검토를 고르면 8단계가 끝납니다. 입찰 참여 여부는 「참여 · 보류 · 참여 안 함」에서 따로 저장합니다."}
        {graph.source.analysis.decision && graph.source.analysis.decision.status !== "UNREVIEWED"
          ? ` 저장된 참여 결정: ${DECISION_LABELS[graph.source.analysis.decision.status]}${graph.source.analysis.decision.decided_by ? ` (${graph.source.analysis.decision.decided_by})` : ""}.`
          : decisionHere
            ? " 참여 결정은 바로 위 「참여 · 보류 · 참여 안 함」에서 사유와 함께 저장합니다."
            : " 참여 · 보류 · 참여 안 함은 공고 상세 또는 8단계 개요에서 사유와 함께 저장합니다."}
      </p>
      </>)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 패널
// ---------------------------------------------------------------------------

export default function DetailPanel({
  graph,
  actions,
  selectedId,
  stage,
  runLog,
  onSelect,
  onNavigate,
  reviewDecision,
  onReviewDecision,
  reducedMotion,
  onClose,
  guidedStep = null,
  onGuidedNext,
  onGuidedGoTo,
  onGuidedExit,
  context = null,
  organizationName = null,
  embedded = false,
}: DetailPanelProps) {
  // 묶음으로 접혀 그림에 없는 요구사항 · 발견도 상세는 연다 (ISSUE-161 · DTL-01 · LNK-R8).
  const node = detailNodeOf(graph, selectedId);
  // 띠의 「하나씩 확인하기」 — 3단계 상세가 **새로 그려진 뒤** 한 번만 체크리스트로 굴린다(타이머는 엇갈렸다).
  const scrollPending = useRef(false);
  useEffect(() => {
    if (!scrollPending.current) return;
    scrollPending.current = false;
    const frame = window.requestAnimationFrame(() => scrollToChecklist());
    return () => window.cancelAnimationFrame(frame);
  }, [selectedId, stage, graph]);
  const resolvedFindingIds = new Set(graph.findings.filter((f) => f.resolved).map((f) => f.id));
  const guided = guidedStep !== null && onGuidedNext !== undefined && onGuidedGoTo !== undefined;
  // 머리 색 = 지도 기호 색(판정) — 예전에는 종류 색이라 열린 발견이 있는 점검 허브가 지도는 빨강 · 머리는 호박이었다(27차 §3-D-4).
  const headerColor = node ? nodeColorHex(node) : COSMOS_COLORS.cyan;
  const headerLabel = node
    ? KIND_LABELS[node.kind]
    : guided
      ? `안내 ${guidedStep}/5 · ${guidedStepDef(guidedStep).title}`
      : // 머리 이름 = 레일 이름(글자까지) — 한 단계를 이름 여럿으로 부르지 않는다(27차 §3-D-9).
        `${stage}단계 · ${graph.steps[stage - 1]?.label ?? `${stage}단계`}`;

  let body: ReactNode;
  if (!node && guided) {
    body = (
      <GuidedDetail
        graph={graph}
        step={guidedStep}
        onSelect={onSelect}
        onNavigate={onNavigate}
        onNext={onGuidedNext}
        onGoTo={onGuidedGoTo}
      />
    );
  } else if (!node) {
    body = (
      <OverviewDetail
        graph={graph}
        actions={actions}
        stage={stage}
        runLog={runLog}
        onSelect={onSelect}
        onNavigate={onNavigate}
        reducedMotion={reducedMotion}
        embedded={embedded}
        context={context}
      />
    );
  } else {
    switch (node.kind) {
      case "notice":
        body = <NoticeDetail graph={graph} actions={actions} stage={stage} onSelect={onSelect} embedded={embedded} />;
        break;
      case "requirement": {
        const req = graph.requirementByNodeId.get(node.id);
        body = req ? (
          <RequirementDetail
            req={req}
            noticeId={graph.source.notice.id}
            hasScenario={graph.hasScenario}
            evidenceRun={evidenceRunState(graph)}
            hasProposal={graph.hasProposal}
            hasAudit={graph.hasAudit}
            auditState={
              graph.source.analysis.audit?.requirement_states.find(
                (state) => state.requirement_id === req.requirement_id,
              ) ?? null
            }
            pageApproximate={graph.source.parse?.page_is_approximate ?? false}
            resolvedFindingIds={resolvedFindingIds}
            onSelect={onSelect}
          />
        ) : (
          <Empty>요구사항을 찾을 수 없습니다.</Empty>
        );
        break;
      }
      case "evidence": {
        const ev = graph.evidenceByNodeId.get(node.id);
        body = ev ? (
          <EvidenceDetail ev={ev} resolvedFindingIds={resolvedFindingIds} onSelect={onSelect} />
        ) : (
          <Empty>근거를 찾을 수 없습니다.</Empty>
        );
        break;
      }
      case "proposal":
        body = <ProposalDetail graph={graph} actions={actions} onSelect={onSelect} context={context} />;
        break;
      case "audit":
        body = <AuditDetail graph={graph} actions={actions} onSelect={onSelect} />;
        break;
      // 묶음 노드는 3D 에서 항목이 많을 때만 나타난다. 분기가 없으면 눌러도 본문이 비어 버린다.
      case "requirement-group":
        body = <RequirementGroupDetail graph={graph} node={node} onSelect={onSelect} />;
        break;
      case "finding-group":
        body = <FindingGroupDetail graph={graph} node={node} onSelect={onSelect} />;
        break;
      case "finding": {
        const finding = graph.findingByNodeId.get(node.id);
        body = finding ? (
          <FindingDetail
            finding={finding}
            noticeId={graph.source.notice.id}
            realRun={graph.source.analysis.audit !== null}
            actions={actions}
            onSelect={onSelect}
          />
        ) : (
          <Empty>발견 항목을 찾을 수 없습니다.</Empty>
        );
        break;
      }
    }
  }

  return (
    <ReqCodeProvider requirements={graph.requirements}>
    <aside
      aria-label={embedded ? "단계 상세" : "상세 패널"}
      data-tour={embedded ? undefined : "panel"}
      data-detail-embedded={embedded ? "" : undefined}
      className={embedded ? "flex flex-col rounded-lg border border-cosmos-border bg-cosmos-deep/40" : "mc-panel flex h-full min-h-0 flex-col"}
    >
      {/*
        머리글은 두 줄이다. 패널 열은 380px 고정인데 제목·회사 배지·공용 결과 배지를 한 줄에 같이 두면
        배지가 폭 40px 남짓까지 눌려 글자마다 줄이 바뀌어 읽을 수 없었다. 배지를 숨기거나 지우는 대신
        아랫줄을 내어 준다 — 「공용 데모 결과」 배지는 다른 회사에서 수정이 막힌다는 유일한 예고다.
      */}
      <div data-panel-region="head" className="flex shrink-0 flex-col border-b border-cosmos-border px-4 py-2.5">
        {/* 좁은 드로어(390)에서 단추가 넘치면 아랫줄로 — 노드 이름이 「…」만 남거나 ✕ 가 밀려나던 것 (DTL-33). */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            aria-hidden="true"
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: headerColor, boxShadow: `0 0 8px ${headerColor}` }}
          />
          <p className="shrink-0 text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted" aria-live="polite">
            {headerLabel}
          </p>
          {node && (
            <p className="min-w-24 flex-1 truncate text-[13px] font-medium text-cosmos-text" title={node.label}>
              {node.label}
            </p>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-1">
            {node && (
              <button
                type="button"
                onClick={() => onSelect(null)}
                className="rounded-md px-2 py-1 text-[12px] text-cosmos-secondary transition-colors hover:text-cosmos-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
              >
                {guided ? "안내로 돌아가기" : "개요로"}
              </button>
            )}
            {!node && guided && onGuidedExit && (
              <button
                type="button"
                onClick={onGuidedExit}
                className="rounded-md px-2 py-1 text-[12px] text-cosmos-secondary transition-colors hover:text-cosmos-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
                title="안내를 끄고 단계 개요를 봅니다"
              >
                단계 개요
              </button>
            )}
            {node && node.kind !== "audit" && node.id !== AUDIT_NODE_ID && graph.findings.length > 0 && (
              <button
                type="button"
                onClick={() => onSelect(AUDIT_NODE_ID)}
                className="rounded-md px-2 py-1 text-[12px] text-cosmos-secondary transition-colors hover:text-cosmos-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
                title="제출 전 누락 점검 결과로 이동"
              >
                점검 결과
              </button>
            )}
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="상세 패널 닫기"
                className="rounded-md px-2 py-1 text-[13px] text-cosmos-secondary transition-colors hover:text-cosmos-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan lg:hidden"
              >
                ✕
              </button>
            )}
          </div>
        </div>
        {context && organizationName && !node && (
          // 아랫줄이라 자리가 넉넉하다. 넘치면 줄바꿈으로 흐르게 두고, 글자 단위로 쪼개지지 않게 막는다.
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className="max-w-full shrink-0 truncate whitespace-nowrap rounded-full border border-cosmos-cyan/40 px-2 py-0.5 text-[12px] text-cosmos-secondary" title={`이 분석은 ${organizationName} · ${context.evidence_scope === "internal" ? "내부 승인자료" : SYNTHETIC_COMPANY} 범위에 고정됩니다`}>
              {organizationName} · {context.evidence_scope === "internal" ? "내부 승인자료" : SYNTHETIC_COMPANY}
            </span>
            {/*
              데모 공고의 결과는 회사 구분 없이 **한 파일**이다. 어느 회사로 보든 같은 것을 본다.
              그 사실을 적지 않으면 「내 회사 분석」으로 읽고, 다른 사람이 만지면 화면이 바뀐 이유를 알 수 없다.
              (쓰기 자체는 기본 조직만 가능하다 — backend analysis_store.guard_public_demo_write)
            */}
            {context.evidence_scope === "public_demo" && (
              <span
                // 좁은 화면에서 숨기지 않는다 — 이 배지가 「다른 회사에서는 수정할 수 없다」는 유일한 예고다.
                className="max-w-full shrink-0 whitespace-nowrap rounded-full border border-cosmos-amber/40 bg-cosmos-amber/10 px-2 py-0.5 text-[12px] text-cosmos-amber"
                title="가상 예시 공고의 분석 결과는 모든 회사가 같은 것을 봅니다. 회사별 결과는 실제 공고에서 만들어집니다."
              >
                공용 데모 결과 · 모든 회사 공통
              </span>
            )}
          </div>
        )}
      </div>

      <div
        key={selectedId ?? (guided ? `guided:${guidedStep}` : `overview:${stage}`)}
        data-panel-region="body"
        /* 넓은 화면에서 스크롤 본문의 바닥값 160px (prompt_04 §3-B-1).
           `min-h-0` 은 남긴다 — 그래야 이 칸이 머리·결정 블록에 자리를 내주며 줄어든다.
           바닥값을 여기(셸이 아니라 패널)에 두는 이유: 셸에서 「열 560 − 머리 − 결정」으로
           간접 보장하면 머리가 한 줄 늘어날 때 조용히 160 아래로 내려간다. */
        // 10-31 최종 점검 G5 — relative: 안의 sr-only(절대 위치) 글이 스크롤 칸 밖 페이지 맨 아래에 놓여 문서가 4,625px 로 늘고 빈 화면이 생겼다
        className={embedded ? "flex flex-col gap-5 px-4 py-4" : "mc-scroll relative flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-4 lg:min-h-[160px]"}
        style={reducedMotion ? undefined : { animation: "cosmos-panel-in 200ms ease-out" }}
      >
        {!embedded && <EligibilityBanner
          graph={graph}
          onOpenChecklist={() => {
            scrollPending.current = true;
            onNavigate(3, NOTICE_NODE_ID);
            // 이미 3단계 · 공고를 보고 있으면 다시 그려지지 않는다 — 그때는 바로 굴린다.
            if (stage === 3 && selectedId === NOTICE_NODE_ID) {
              scrollPending.current = false;
              scrollToChecklist();
            }
          }}
        />}
        {body}
      </div>

      {!embedded && <HumanReviewBlock graph={graph} decision={reviewDecision} onDecision={onReviewDecision} />}
    </aside>
    </ReqCodeProvider>
  );
}
