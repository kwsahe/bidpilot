"use client";

/**
 * 요구사항 정리표 — 요구사항 구조화와 근거 검증 작업 칸. 사업기회 「요구사항 정리표」 탭 안에 그린다(28차 §3-C).
 *
 * - 예전 `/rfp` 페이지였다(주소는 `/opportunities?tab=sheet` 로 넘긴다 · next.config.ts). 표 · 상세 · 정정 부품은 그대로다.
 * - 표시 상태는 대시보드와 같은 buildCosmosGraph로 계산한다. 근거 연결 여부도 **대시보드와 같은
 *   규칙**(`graph.evidenceRunState`)으로 판정한다 (0920 §4-B-5 · ISSUE-078).
 * - 원문(source_text·페이지)과 규칙으로 뽑은 구조화 결과(title·content·category)를 나란히, 구분해서 보여준다.
 *   추출은 규칙만 쓴다 — AI 를 부르지 않는다 (27차 ISSUE-158).
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { dDayText, deadlineTerm, effectiveDeadline, firstLabel, pairOf, registrationClosesFirst } from "@/lib/deadline";
import { REGISTER_COMPANY_DOCUMENTS, RELOAD_TERM, SCREEN_NAMES, SYNTHETIC_COMPANY, WRITE_PROPOSAL_BUTTON } from "@/lib/terms";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { describeFailure } from "@/lib/errors";

import { DownloadLink } from "@/components/ui/DownloadLink";
import { Badge, Button, Chip, EmptyState, InlineAlert, KpiCard, LoadingState, SectionHeader } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { ApiError, correctRfpItem, getAuditReadiness, getConditions, getDemoCosmosScenario, getItemPerformanceMatch, getLatestAuditRun, getLedgerCandidates, getProposal, getRfpRequirements, goldExportUrl, parseRfpWithConsent, RFP_PARSE_PHASE_LABEL, type ItemPerformanceMatch, type LedgerView, type RfpParsePhase } from "@/lib/api";
import { LedgerAdoptionBlock } from "./LedgerAdoptionBlock";
import { analysisContext, readOrganizationId, useOrganizationId } from "@/lib/organization";
import { currentUserName } from "@/lib/currentUser";
import { LedgerMatchBlock } from "@/components/cosmos/GatePanel";
import AnalysisStateBadges from "@/components/ui/AnalysisStateBadges";
import {
  ELIGIBILITY_GATE_LABELS,
  GRADE_LABELS,
  RECOMMENDATION_GRADE,
  REVIEW_PRIORITY,
  labelOf,
  reviewPriorityText,
} from "@/lib/scoreNames";
import {
  CRITICALITY_COLORS,
  CRITICALITY_LABELS,
  ITEM_TABS,
  ITEM_TYPE_COLORS,
  ITEM_TYPE_LABELS,
  ITEM_TYPE_ORDER,
  ITEM_TYPE_WHAT,
  REVIEW_STATUS_LABELS,
  countByType,
  criticalityOf,
  displayCodeOf,
  groupCounts,
  itemTypeOf,
  requirementTypeChip,
  type ItemTab,
} from "@/lib/cosmos/itemTypes";
import { DEMO_NOTICE, isDemoProcurementId, isParsableNoticeId } from "@/lib/cosmos/demoNotice";
import { CONDITION_STATUS_LABELS, formatDateTime, formatPage, formatSimilarity, METHOD_LABELS } from "@/lib/cosmos/format";
import { EMPTY_ANALYSIS, buildCosmosGraph, type CosmosGraph, type RequirementView } from "@/lib/cosmos/graph";
import { NOTICE_DOCUMENT_WARNING } from "@/lib/cosmos/provenance";
import { rfpEvidenceView, type RfpEvidenceView } from "./requirementEvidenceView";
import { COSMOS_COLORS, STATE_COLORS, TONE_COLORS, VERDICT_TONES, type Tone } from "@/lib/cosmos/theme";
import type { DemoCosmosScenario } from "@/types/cosmos";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import type { UnifiedOpportunity } from "@/types/opportunity";
import type { ProcurementListResponse, ProcurementNotice } from "@/types/procurement";
import type { Criticality, ItemType, RequirementStatus, RfpParseResult } from "@/types/rfp";

// ---------------------------------------------------------------------------
// URL의 ?notice= (hydration-safe)
// ---------------------------------------------------------------------------

const subscribeNever = () => () => {};
const readNoticeServer = (): string | null => null;
/** `?req=<requirement_id>` — 대시보드에서 보던 요구사항. 첫 화면에서 그 행을 골라 연다 (27차 LNK-07). */
const readReqFromUrl = (): string | null => {
  try {
    return new URLSearchParams(window.location.search).get("req");
  } catch {
    return null;
  }
};

/** 대시보드로 — 이 화면의 단계(4 요구사항 정리)로 내려앉게 `?stage=4` 를 싣는다 (27차 LNK-07). */
function dashboardHref(noticeId: string): string {
  // 합성도 id 를 싣는다 — 빼면 대시보드가 저장된 다른 실공고 4단계로 도착했다(27차 검수 LNK-R3).
  return `/analysis?notice=${encodeURIComponent(noticeId)}&stage=4`;
}

/** 회사자료 화면으로 — 대시보드 · 지원사업 흐름과 같은 말 (27차 LNK-03). */
function CompanyDocsLink() {
  return (
    <Link href="/company" className="mc-focus whitespace-nowrap rounded font-medium text-cosmos-cyan underline-offset-2 hover:underline">
      {REGISTER_COMPANY_DOCUMENTS} →
    </Link>
  );
}
const getHydrated = () => true;
const getHydratedServer = () => false;

// ---------------------------------------------------------------------------
// 상태 라벨 — 파싱 단계 상태와 회사 근거 매칭 상태를 구분한다
// ---------------------------------------------------------------------------

type DisplayStatus = RequirementStatus | "not_run" | "old" | "failed" | "off" | "no_row_link";

const STATUS_META: Record<DisplayStatus, { label: string; color: string; tone: Tone }> = {
  // 판정 4색 — 상세 패널 · 지도와 같은 색. 「부분 연결」(후보 근거만)은 확인 필요 쪽 호박이다(보라는 기업마당 · 27차 §3-E).
  matched: { label: "회사 근거 있음", color: STATE_COLORS.ok, tone: "ok" },
  partial: { label: "후보만 있음", color: STATE_COLORS.partial, tone: "warn" },
  unmatched: { label: "회사 근거 없음", color: STATE_COLORS.missing, tone: "muted" },
  check: { label: "확인 필요", color: STATE_COLORS.check, tone: "warn" },
  not_run: { label: "아직 안 붙임", color: COSMOS_COLORS.slate, tone: "muted" },
  // 요구사항이 바뀌기 전 결과 · 합성 근거가 섞인 결과 — 지금 표와 견줄 수 없다 (RFP-01 · RFP-05).
  old: { label: "이전 결과", color: COSMOS_COLORS.slate, tone: "muted" },
  // 「돌렸는데 아무것도 못 붙었다」는 「아직 안 돌렸다」와 **다른 사실**이다. 같은 회색으로
  // 뭉쳐 두면 담당자가 같은 단추를 다시 누른다 (0920 §4-B-5 · ISSUE-078).
  failed: { label: "붙이기 실패", color: COSMOS_COLORS.amber, tone: "warn" },
  // 45차 H5 — AI 검색을 꺼 둔 것은 실패가 아니다. 행에는 「근거 없음(원장 후보 n)」 · 채택했으면 「원장 실적 채택 n」(ledgerStatusText).
  off: { label: "근거 없음", color: COSMOS_COLORS.slate, tone: "muted" },
  // 실공고 근거는 제안서 문장 단위로만 저장된다 — 행마다 「근거 미연결」로 적으면 거짓이다 (RFP-04).
  no_row_link: { label: "항목별 기록 없음", color: COSMOS_COLORS.slate, tone: "muted" },
};

/** HWP · HWPX 쪽수는 문단 묶음 기준 근사값이다 — 표 · 카드에서도 정확한 쪽처럼 보이지 않게 「≈」 (RFP-27). */
function pageText(page: number | null, approximate: boolean): string {
  return approximate && page !== null ? `≈${formatPage(page)}` : formatPage(page);
}

/** 담당자가 확정 · 정정한 항목 — 분류 확인은 끝났다 (RFP-11). */
function isReviewed(req: RequirementView): boolean {
  return req.review_status === "confirmed" || req.review_status === "corrected";
}

function displayStatusOf(req: RequirementView, view: RfpEvidenceView): DisplayStatus {
  if (req.status === "check" && !isReviewed(req)) return "check";
  if (view.mode !== "ran") return view.mode;
  if (!view.rowLinks) return "no_row_link";
  if (req.evidence.some((e) => e.selected)) return "matched";
  return req.evidence.length > 0 ? "partial" : "unmatched";
}

/**
 * 중대성 배지.
 *
 * `CRITICALITY_LABELS.blocker` 는 아직 「BLOCKER」라는 영단어다(lib/cosmos/itemTypes.ts).
 * 담당자가 표에서 읽어야 하는 말은 「참가 차단」이므로 화면 글자는 format.ts 의 조건 상태
 * 사전을 쓰고, 영문 원어는 title 툴팁으로만 남긴다.
 */
function CriticalityBadge({ level, className, glyph = false }: { level: Criticality; className?: string; glyph?: boolean | string }) {
  const blocker = level === "blocker";
  return (
    <Badge color={CRITICALITY_COLORS[level]} className={className} glyph={glyph} title={blocker ? "BLOCKER" : undefined}>
      {blocker ? CONDITION_STATUS_LABELS.BLOCKER : CRITICALITY_LABELS[level]}
    </Badge>
  );
}

/**
 * 담당자 검토 배지 — 확정 · 정정 · 반려. 표에 검토 상태가 없어 무엇을 확정했는지 보이지 않았다 (RFP-11).
 * 반려는 「항목 아님」이라 초록이 아니다 (RFP-32).
 */
function ReviewBadge({ req, className }: { req: RequirementView; className?: string }) {
  const review = req.review_status;
  if (!review || review === "unreviewed") return null;
  return (
    <Badge tone={review === "rejected" ? "muted" : "ok"} className={className} glyph={review === "rejected" ? "✕" : "✎"}>
      {REVIEW_STATUS_LABELS[review]}
    </Badge>
  );
}

/**
 * 이 화면의 중대성 — 참가 차단은 표 배지와 같은 기준(미해결 조건 · RFP-26)이다. 조건 점검에서 참가 차단이 아니면(해결 · 비해당)
 * 추출 「참가 차단」은 「높음」으로 세운다 — 「중대성」 정렬에서만 「참가 차단」이 다시 보였다 (RFP-24).
 */
function levelOf(req: RequirementView, blocked: boolean): Criticality {
  if (blocked) return "blocker";
  const level = criticalityOf(req);
  return level === "blocker" ? "high" : level;
}

/** 미해결 참가 차단 조건이 걸린 항목 — 표 · 카드 · 상세가 같은 배지 (RFP-26). */
function BlockerBadge({ className, label = CONDITION_STATUS_LABELS.BLOCKER }: { className?: string; label?: string }) {
  return (
    <Badge color={CRITICALITY_COLORS.blocker} className={className} glyph="!">
      {label}
    </Badge>
  );
}

type LoadState =
  | { kind: "loading" }
  | { kind: "not_parsed"; notice: ProcurementNotice }
  | { kind: "error"; message: string }
  | { kind: "ready"; graph: CosmosGraph; result: RfpParseResult };

function placeholderNotice(id: string): ProcurementNotice {
  return {
    id,
    notice_no: id,
    title: id,
    agency: "목록에서 확인되지 않음",
    published_at: "",
    deadline_at: null,
    budget: null,
    region: null,
    description: null,
    source_url: null,
    raw_data: {},
  };
}

async function loadMatrix(id: string, list: ProcurementListResponse | null): Promise<LoadState> {
  const demo = isDemoProcurementId(id);
  const notice = demo ? DEMO_NOTICE : (list?.notices.find((n) => n.id === id) ?? placeholderNotice(id));
  let parse: RfpParseResult;
  try {
    parse = await getRfpRequirements(id);
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) return { kind: "not_parsed", notice };
    return { kind: "error", message: describeFailure(error, "요구사항을 불러오지 못했습니다.") };
  }
  let scenario: DemoCosmosScenario | null = null;
  if (demo) scenario = await getDemoCosmosScenario(id).catch(() => null);
  /**
   * 제안서 결과를 함께 읽는다 — **여기에 근거 연결의 실행 여부와 실패 사유가 들어 있다**
   * (0920 §4-B-5 · ISSUE-078).
   *
   * 예전에는 `analysis: EMPTY_ANALYSIS` 를 고정으로 넘겨서, 대시보드가 쓰는 값
   * (`evidence_summary`·`evidence_grounded_count`)이 이 화면에 **닿지도 않았다.** 그래서
   * 판정할 것이 「합성 데모인가」밖에 없었다.
   *
   * 없으면(404) null 이고 그것이 「미실행」이다. 실패해도 요구사항 표는 그대로 떠야 하므로
   * 여기서 오류를 올리지 않는다 — 표를 못 보여 주는 것이 더 나쁘다.
   */
  const ctx = analysisContext(id, readOrganizationId());
  /*
   * 조건 · 검사 결과 · 초안 기준도 대시보드처럼 읽는다(읽기만 — 검사를 돌리지 않는다). 없으면 참가 차단 배지가 사람이
   * 해결 처리한 조건에도 남고 「경고 N」이 이 화면에 한 번도 안 나왔다(RFP-26). 요구사항이 바뀐 뒤의 초안이면
   * 검사 결과를 쓰지 않는다 — 대시보드와 같은 규칙이다.
   */
  const [proposal, conditions, readiness] = await Promise.all([
    getProposal(id, ctx).catch(() => null),
    getConditions(id, ctx).catch(() => null),
    getAuditReadiness(id, ctx).catch(() => null),
  ]);
  const audit = readiness?.blockers.includes("stale_requirements") ? null : await getLatestAuditRun(id, ctx).catch(() => null);
  const graph = buildCosmosGraph({
    notice,
    origin: demo ? { kind: "demo" } : { kind: "real", source: list?.source ?? "cached", fetchedAt: list?.fetched_at ?? null },
    parse,
    scenario,
    analysis: { ...EMPTY_ANALYSIS, proposal, conditions, readiness, audit },
  });
  return { kind: "ready", graph, result: parse };
}

/** 통합 목록 항목으로 만든 공고 한 줄 — 공고 목록 응답을 기다리지 않고 머리 · 그래프에 이름을 준다(28차 §3-C). */
function listFromUnified(unified: UnifiedOpportunity | null): ProcurementListResponse | null {
  if (!unified || unified.source_type !== "g2b") return null;
  const notice: ProcurementNotice = {
    ...placeholderNotice(unified.id),
    title: unified.title,
    agency: unified.agency,
    deadline_at: unified.deadline,
    description: unified.summary,
    source_url: unified.detail_url ?? null,
  };
  return {
    source: "cached",
    g2b_api_configured: false,
    fetched_at: "",
    total_fetched: 1,
    count: 1,
    error: null,
    notices: [notice],
  } as ProcurementListResponse;
}

/**
 * 요구사항 정리표 — 사업기회 「요구사항 정리표」 탭 안에 그린다(28차 §3-C · 담당자 지시 「사업기회에 통합」).
 *
 * 예전 `/rfp` 페이지는 상단 메뉴 잠금 · 공고 목록 기다림 때문에 「들어갈 때도, 못 들어갈 때도」 있었다.
 * 여기서는 **목록 응답을 기다리지 않는다** — 공고 id · 회사가 바뀔 때만 표를 읽는다.
 * 선택이 없으면 합성 데모를 저절로 열지 않는다(시연은 주소에 `synthetic-rfp-0001` 을 적는다).
 */
export function RequirementSheet({
  noticeId,
  list = null,
  unified = null,
  listLoading = false,
  listError = null,
  listTab = "전체 목록",
  onBack,
}: {
  noticeId: string | null;
  /** 사업기회가 받은 나라장터 목록(대시보드가 공고를 찾는 목록과 같다 · 2.0.6) — 통합 목록에 없을 때 제목 · 「대시보드에서 열기」를 정한다. */
  list?: ProcurementListResponse | null;
  unified?: UnifiedOpportunity | null;
  /** 통합 목록을 아직 받는 중(45차 M1) — 그동안은 「목록에 없는 공고」라 단정하지 않는다(주소로 열면 약 5초 그렇게 보였다). */
  listLoading?: boolean;
  /** 통합 목록(순위 · 판정) 받기 실패 사유(2.0.6) — 「목록에 없는 공고」가 아니라 받지 못했다고 적는다. */
  listError?: string | null;
  /** 빈 안내가 가리킬 목록 탭 이름 — 쉬운 보기는 「입찰」, 전체 보기는 「전체 목록」(29차 R28-13). */
  listTab?: string;
  onBack: () => void;
}) {
  const hydrated = useSyncExternalStore(subscribeNever, getHydrated, getHydratedServer);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsePhase, setParsePhase] = useState<RfpParsePhase | null>(null);
  const [parseNote, setParseNote] = useState<string | null>(null);
  // undefined = 아직 안 골랐다 → 주소의 `?req=` 를 따른다. 고르거나 공고를 바꾸면 그 값이 이긴다.
  const urlReq = useSyncExternalStore(subscribeNever, readReqFromUrl, readNoticeServer);
  const [pickedReqId, setSelectedReqId] = useState<string | null | undefined>(undefined);
  const selectedReqId = pickedReqId === undefined ? urlReq : pickedReqId;
  // 늦게 끝난 분석이 새 공고 아래에 들어오지 않게 지금 공고를 잰다 (RFP-18).
  const currentNotice = useRef(noticeId);
  useEffect(() => {
    currentNotice.current = noticeId;
  }, [noticeId]);

  /*
   * 공고가 바뀌면 이전 공고의 선택 · 알림 · 표를 비운다. 첫 화면(하이드레이션 뒤)은 주소의 `?req=` 를
   * 지켜야 하므로 처음 한 번은 기억만 한다.
   */
  const [shownNotice, setShownNotice] = useState<string | null | undefined>(undefined);
  if (hydrated && shownNotice !== noticeId) {
    if (shownNotice !== undefined) {
      setSelectedReqId(null);
      setParseError(null);
      setParseNote(null);
      setState({ kind: "loading" });
    }
    setShownNotice(noticeId);
  }

  const organizationId = useOrganizationId();
  const bidId = noticeId && !noticeId.startsWith("bizinfo-") ? noticeId : null;
  // 통합 목록 줄이 먼저 · 없으면(실제 마감이 지나 빠졌거나 받지 못함) 나라장터 목록으로 이름을 찾는다(2.0.6 — 제목이 공고 id 로 나왔다)
  const sheetList = listFromUnified(unified) ?? list;
  const listRef = useRef(sheetList);
  useEffect(() => {
    listRef.current = sheetList;
  }, [sheetList]);

  // 공고 · 회사가 바뀔 때만 읽는다 — 목록 응답을 기다리지 않는다(28차). 회사별 제안서 반영 상태 때문에 회사도 본다.
  useEffect(() => {
    if (!hydrated || !bidId) return;
    let cancelled = false;
    loadMatrix(bidId, listRef.current).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => {
      cancelled = true;
    };
  }, [hydrated, bidId, organizationId]);

  // 주소로 온 요구사항은 표가 그려진 뒤 그 행을 화면 안으로 굴린다 (27차 LNK-07). 한 번 연 뒤에는 주소에서 req 를 뺀다.
  useEffect(() => {
    if (state.kind !== "ready" || !urlReq || pickedReqId !== undefined) return;
    const frame = window.requestAnimationFrame(() => {
      const rows = document.querySelectorAll<HTMLElement>(`[data-req-row="${CSS.escape(urlReq)}"]`);
      [...rows].find((row) => row.offsetParent !== null)?.scrollIntoView({ block: "center" });
      setSelectedReqId(urlReq);
      try {
        const url = new URL(window.location.href);
        url.searchParams.delete("req");
        window.history.replaceState(window.history.state, "", url.toString());
      } catch {
        // 주소를 못 고쳐도 선택은 그대로다
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [state.kind, urlReq, pickedReqId]);

  // 45차 M12 — 정정 · 채택 저장 뒤 조용히 다시 읽는다(표를 「불러오는 중」으로 바꾸면 폼이 접히고 화면이 맨 위로 가 「저장했습니다」를 못 봤다)
  const reload = useCallback(() => {
    if (!bidId) return;
    // 오류 화면에서 누른 「다시 불러오기」는 눌린 것이 보이게 「불러오는 중」(45차 마지막 검토 — 몇 초 동안 아무 변화가 없었다)
    setState((prev) => (prev.kind === "ready" ? prev : { kind: "loading" }));
    void loadMatrix(bidId, listRef.current).then(setState);
  }, [bidId]);

  async function runParse() {
    if (!bidId) return;
    const id = bidId;
    setParsing(true);
    setParseError(null);
    setParseNote(null);
    setParsePhase(null);
    try {
      // 로컬에 없는 실공고 첨부는 사람이 파일 이름을 보고 확인해야 받는다 (27차 §3-A-3). 취소면 요청 0.
      const result = await parseRfpWithConsent(id, { onPhase: setParsePhase });
      if (result === null) return;
      const next = await loadMatrix(id, listRef.current);
      if (currentNotice.current !== id) return;
      setState(next);
      setParseNote(`요구사항 ${result.count}건으로 다시 정리했습니다.`);
    } catch (error: unknown) {
      // 사유 끝 마침표는 떼고 문장 끝에 하나만(10-31 최종 점검 — 「… 할 수 있습니다.. 아래 표는」)
      const detail = error instanceof ApiError && error.detail ? ` — ${error.detail.replace(/[.\s]+$/, "")}` : "";
      // 이미 표시 중인 표는 유지하고 (CLAUDE.md 20), 오류만 위에 띄운다.
      setParseError(`공고 분석에 실패했습니다${detail}.`);
    } finally {
      setParsing(false);
      setParsePhase(null);
    }
  }
  const parsingLabel = parsePhase ? RFP_PARSE_PHASE_LABEL[parsePhase] : "분석 중…";
  const nowMs = useNowMs();
  // 10-31 최종 점검 — 열람자는 분석(쓰기)을 미리 잠근다(누른 뒤 403 이었다 · 45차 M4 · /plan 2.1.2 와 같게). 다시 불러오기(읽기)는 그대로.
  const viewerLock = useViewerLock();

  const backLink = (
    <Button size="sm" variant="secondary" onClick={onBack}>
      ← 목록으로
    </Button>
  );

  if (!noticeId) {
    return (
      <section className="flex flex-col gap-3" data-sheet-notice="">
        <SectionHeader as="h2" title={SCREEN_NAMES.rfp} aside={backLink} />
        <EmptyState title="목록에서 입찰을 고르세요">
          「{listTab}」 탭에서 나라장터 입찰의 「요구사항 정리표 열기」를 누르면 여기서 그 공고의 요구사항 표가 열립니다.
        </EmptyState>
      </section>
    );
  }
  if (!bidId) {
    return (
      <section className="flex flex-col gap-3" data-sheet-notice={noticeId}>
        <SectionHeader as="h2" title={SCREEN_NAMES.rfp} aside={backLink} />
        <EmptyState
          title="지원사업은 요구사항 정리표가 없습니다"
          action={
            <Link href={`/support/${encodeURIComponent(noticeId)}`} className="mc-focus rounded font-medium text-cosmos-cyan underline-offset-2 hover:underline">
              지원사업 신청 분석 열기 →
            </Link>
          }
        >
          기업마당 지원사업은 입찰 제안요청서가 아니라 공고문 조항으로 신청 여부를 봅니다 — 신청 분석 화면에서 확인하세요.
        </EmptyState>
      </section>
    );
  }

  const supported = isParsableNoticeId(bidId);
  const graph = state.kind === "ready" ? state.graph : null;
  // 목록 이름이 먼저 — 주소로 열면 목록보다 표를 먼저 읽어 그래프의 공고가 자리표시(제목 = id)다 (28차 검수 R2-01).
  const graphTitle = graph && graph.source.notice.title !== bidId ? graph.source.notice.title : null;
  // 목록 밖 공고(캐시에서 빠진 옛 분석)는 제목을 알 수 없다 — id 옆에 분석한 문서 이름을 붙인다.
  const docName = state.kind === "ready" ? state.result.document : null;
  // 2.0.6 — 나라장터 목록에서 찾은 공고(통합 목록에 없을 때 제목 · 대시보드 링크) · 표를 목록보다 먼저 읽었어도 이름을 준다
  const listNotice = list?.notices.find((n) => n.id === bidId) ?? null;
  const title =
    unified?.title ??
    graphTitle ??
    listNotice?.title ??
    (isDemoProcurementId(bidId) ? DEMO_NOTICE.title : listLoading ? "공고 이름을 불러오는 중…" : docName ? `${bidId} · 「${docName}」` : bidId);
  // 대시보드로 열 수 있는 공고인가 — 합성이거나 사업기회 목록에 있을 때만(목록 밖이면 대시보드가 다른 공고로 떨어진다 · 27차 LNK-R4 · 28차 검수 R2-03).
  // 2.0.6 — 대시보드는 같은 기간의 나라장터 목록(비추천 포함)에서 찾는다. 그 목록에 있으면 연다 — 실제 마감이 지나 통합 목록에서 빠진 공고를
  // 대시보드에서 막 열어 왔는데 「대시보드 목록에 없는 공고」라 했다. 그 목록도 못 받았고 통합 목록이 실패했으면 모른다 — 링크를 숨기지 않는다.
  const onDashboardList = list ? listNotice !== null : listError !== null;
  const openableOnDashboard = isDemoProcurementId(bidId) || unified !== null || onDashboardList;
  const dashboardLink = (label: string) =>
    openableOnDashboard ? (
      <Link
        href={dashboardHref(bidId)}
        className="mc-focus inline-flex min-h-9 items-center rounded-lg border border-cosmos-border-strong px-3 text-[12.5px] font-medium text-cosmos-cyan hover:border-cosmos-cyan/60"
      >
        {label}
      </Link>
    ) : listLoading ? null : (
      <span className="text-[12.5px] text-cosmos-muted">입찰 분석 목록에 없는 공고라 여기서만 볼 수 있습니다</span>
    );

  return (
    <section className="flex flex-col gap-3" data-sheet-notice={bidId}>
      <SectionHeader
        as="h2"
        title={SCREEN_NAMES.rfp}
        description={title}
        aside={
          <div className="flex flex-wrap items-center gap-2">
            {backLink}
            {dashboardLink("입찰 분석에서 열기 →")}
            {/* 2.1.2 — 분석을 마친 뒤 제안서 작성으로 돌아오는 길(대표 10-30 「돌아오는 게 어렵다」) · 요구사항이 있을 때만 */}
            {state.kind === "ready" && (
              <Link
                href={`/plan?notice=${encodeURIComponent(bidId)}`}
                data-sheet-plan-link
                className="mc-focus inline-flex min-h-9 items-center rounded-lg border border-cosmos-border-strong px-3 text-[12.5px] font-medium text-cosmos-cyan hover:border-cosmos-cyan/60"
              >
                {WRITE_PROPOSAL_BUTTON}
              </Link>
            )}
            {/* 불러오기에 실패했으면 다시 분석이 아니라 다시 불러오기다 (RFP-19) · 서버가 받지 않는 주소면 분석을 막고 이유를 잇는다 (RFP-13). */}
            <Button
              size="sm"
              variant="primary"
              onClick={state.kind === "error" ? reload : runParse}
              disabled={parsing || state.kind === "loading" || !supported || (viewerLock && state.kind !== "error")}
              aria-busy={parsing || state.kind === "loading"}
              aria-describedby={!supported ? "rfp-unsupported" : viewerLock && state.kind !== "error" ? "rfp-viewer-lock" : undefined}
              title={viewerLock && state.kind !== "error" ? VIEWER_LOCK_REASON : undefined}
            >
              {parsing ? parsingLabel : state.kind === "loading" ? "불러오는 중…" : state.kind === "error" ? RELOAD_TERM : state.kind === "ready" ? "공고 다시 분석" : "공고 분석 시작"}
            </Button>
            {viewerLock && state.kind !== "error" && (
              <span id="rfp-viewer-lock" className="text-[12px] text-cosmos-muted" data-viewer-lock>
                {VIEWER_LOCK_LABEL} — 공고 분석은 편집자 이상이 합니다
              </span>
            )}
          </div>
        }
      />
      <p className="text-[12.5px] leading-5 text-cosmos-secondary">
        제안요청서에서 해야 할 일 · 조건 · 제출물을 한 줄씩 뽑아 표로 만듭니다. 줄마다 몇 쪽 어느 문장에서 나왔는지 함께 보여 줍니다(AI 없이 정해진 규칙으로 뽑습니다).
      </p>

      {/* 지금 공고의 한 줄 — 다른 화면과 같은 값(통합 목록에서 그대로 · 여기서 다시 세지 않는다). */}
      {unified && (
        <div className="flex flex-wrap items-center gap-1.5">
          {typeof unified.source_specific_score?.grade === "string" && (
            <Badge tone="info" title={RECOMMENDATION_GRADE.description}>
              {RECOMMENDATION_GRADE.label} {labelOf(GRADE_LABELS, unified.source_specific_score.grade)}
            </Badge>
          )}
          <Badge tone="muted" title={REVIEW_PRIORITY.description}>
            {reviewPriorityText(unified.company_priority_score)}
          </Badge>
          <AnalysisStateBadges state={unified.analysis_state} />
          {unified.eligibility_gate && (
            <Badge tone={VERDICT_TONES[unified.eligibility_gate]} title={unified.gate_reason ?? undefined}>
              {labelOf(ELIGIBILITY_GATE_LABELS, unified.eligibility_gate)}
            </Badge>
          )}
          {/* 등록마감이 먼저 닫히면 그쪽이 실제 데드라인 — 대시보드 상단 · 목록 · 레이더와 같은 규칙(27차 R27U-MSC-01 · 28차 검사) */}
          <Badge tone={unified.closed ? "fail" : "muted"}>
            {!unified.closed && registrationClosesFirst(pairOf(unified, unified.deadline))
              ? firstLabel(pairOf(unified, unified.deadline))
              : deadlineTerm({ source: "g2b", closed: unified.closed, periodKind: null, deadline: unified.deadline })}
            {!unified.closed &&
              ` ${dDayText({ deadline: effectiveDeadline(pairOf(unified, unified.deadline)), periodKind: null, nowMs })}`}
          </Badge>
        </div>
      )}

      {/* 2.0.6 — 통합 목록 실패는 목록 탭에만 적혀, 여기서는 판정 · 마감 배지가 왜 없는지 알 수 없었다 */}
      {listError && !unified && (
        <InlineAlert tone="warn">이 공고의 판정 · 마감 배지를 보일 수 없습니다 — {listError}</InlineAlert>
      )}
      {parseError && <InlineAlert tone="warn">{parseError} {state.kind === "ready" ? "아래 표는 마지막으로 성공한 분석 결과입니다." : ""}</InlineAlert>}
      {parseNote && <InlineAlert tone="ok">{parseNote}</InlineAlert>}

      {state.kind === "loading" && <LoadingState label="요구사항을 불러오는 중" rows={6} />}
      {state.kind === "error" && (
        <EmptyState
          title="요구사항을 불러오지 못했습니다"
          tone="fail"
          action={
            <Button variant="secondary" onClick={reload}>
              {RELOAD_TERM}
            </Button>
          }
        >
          {state.message}
        </EmptyState>
      )}
      {state.kind === "not_parsed" && !supported && (
        <EmptyState title="지원하지 않는 공고 주소입니다">
          <span id="rfp-unsupported">「{bidId}」는 공고 id 모양이 아니라 분석할 수 없습니다 — 목록에서 공고를 고르세요.</span>
        </EmptyState>
      )}
      {state.kind === "not_parsed" && supported && (
        <EmptyState
          title="아직 공고 분석 결과가 없습니다"
          // 10-31 독립 검토 — 빈 화면의 이 단추도 열람자에게 미리 잠근다(머리 단추만 잠갔었다)
          action={
            <Button variant="primary" onClick={runParse} disabled={parsing || viewerLock} title={viewerLock ? VIEWER_LOCK_REASON : undefined}>
              {parsing ? parsingLabel : "공고 분석 시작"}
            </Button>
          }
        >
          {isDemoProcurementId(bidId)
            ? "가상 예시 공고 첨부를 분석하면 요구사항 표가 만들어집니다."
            : `「${title}」의 첨부 제안요청서를 아직 분석하지 않았습니다. 분석을 시작하면 HWP/HWPX/PDF에서 요구사항을 뽑습니다.`}
        </EmptyState>
      )}
      {state.kind === "ready" && (
        <MatrixView
          graph={state.graph}
          result={state.result}
          selectedReqId={selectedReqId}
          onSelectReq={setSelectedReqId}
          onReload={reload}
          dashboardLink={dashboardLink("입찰 분석에서 이 공고 열기 →")}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 매트릭스 (KPI · 필터 · 표/카드 · 상세)
// ---------------------------------------------------------------------------

type SortKey = "id" | "page" | "category" | "status" | "criticality";
const CRITICALITY_RANK = { blocker: 0, high: 1, normal: 2, low: 3 } as const;

const STATUS_FILTERS: DisplayStatus[] = ["matched", "partial", "unmatched", "check", "not_run", "old", "failed", "off", "no_row_link"];

/**
 * 「근거 없음(원장 후보 n)」 · 「원장 실적 채택 n」 — 행 상태 칸의 사실 그대로(45차 H5).
 * 2.0.6 — 읽는 중 · 읽기 실패는 「근거 없음」이 아니다(셋 다 null 이라 같은 글이었다 · 채택해 둔 공고도 「근거 없음」).
 */
function ledgerStatusText(ledger: LedgerView | null, requirementId: string, read: "loading" | "failed" | "ready" = "ready"): string {
  if (read === "loading") return "원장 후보 읽는 중";
  if (read === "failed") return "확인 못 함";
  const mine = ledger?.candidates.filter((c) => c.requirement_id === requirementId) ?? [];
  const adopted = mine.filter((c) => c.adopted).length;
  if (adopted > 0) return `원장 실적 채택 ${adopted}`;
  return mine.length > 0 ? `근거 없음(원장 후보 ${mine.length})` : "근거 없음";
}

function MatrixView({
  graph,
  result,
  selectedReqId,
  onSelectReq,
  onReload,
  dashboardLink,
}: {
  graph: CosmosGraph;
  result: RfpParseResult;
  selectedReqId: string | null;
  onSelectReq: (id: string | null) => void;
  /** 정정을 저장한 뒤 표를 다시 읽는다 — 예전에는 「다음에 불러올 때 반영됩니다」로 끝났다. */
  onReload: () => void;
  /** 대시보드로 가는 링크(또는 목록에 없다는 한 줄) — 페이지가 만든다 */
  dashboardLink: React.ReactNode;
}) {
  /**
   * 근거 연결 상태 — **대시보드와 같은 규칙**(0920 §4-B-5 · ISSUE-078).
   *
   * 예전에는 `graph.hasScenario`(= 합성 데모인가) 한 줄이 이 화면의 KPI·상태 칩·표 행·안내
   * 문구를 전부 지배했다. 그래서 실공고는 근거 연결을 돌려 놓아도 언제나 「매칭 미실행」,
   * 데모는 언제나 「합성 회사자료」였다. 같은 순간 대시보드는 「회사자료 3종 · 4문장에
   * 연결」이라고 적고 있었다.
   */
  const view = useMemo(() => rfpEvidenceView(graph), [graph]);
  // 45차 H5 — AI 검색을 꺼 둔 회사의 실적 원장 후보 · 채택(행 상태 칸과 행 상세 「채택」 단추가 같은 값을 쓴다)
  const ledgerNoticeId = graph.source.notice.id;
  const ledgerApplies = graph.source.origin.kind !== "demo" && !isDemoProcurementId(ledgerNoticeId);
  const [ledger, setLedger] = useState<LedgerView | null>(null);
  // 2.0.6 — 어느 요청까지 읽었는지 · 실패 사유(읽는 중 · 실패 · 받음을 가른다) · 「다시 불러오기」
  const [ledgerRead, setLedgerRead] = useState<{ key: string; error: string | null } | null>(null);
  const [ledgerTick, setLedgerTick] = useState(0);
  const ledgerKey = `${ledgerNoticeId}|${ledgerTick}`;
  useEffect(() => {
    if (!ledgerApplies) return;
    let cancelled = false;
    getLedgerCandidates(ledgerNoticeId, analysisContext(ledgerNoticeId, readOrganizationId()))
      .then((next) => {
        if (cancelled) return;
        setLedger(next);
        setLedgerRead({ key: ledgerKey, error: null });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLedger(null);
        setLedgerRead({ key: ledgerKey, error: describeFailure(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [ledgerNoticeId, ledgerApplies, ledgerKey]);
  const ledgerLoading = ledgerApplies && ledgerRead?.key !== ledgerKey;
  const ledgerError = ledgerApplies && !ledgerLoading ? (ledgerRead?.error ?? null) : null;
  const ledgerState = ledgerLoading ? "loading" : ledgerError !== null ? "failed" : "ready";
  // 행 상세의 원장 후보 · 채택 칸 자리 — 읽는 중 · 실패면 칸을 말없이 지우지 않고 한 줄로.
  // 2.0.6 — 실패는 근거 모드와 상관없이 적는다: 제안서를 만들기 전(연결 전)에도 채택 칸은 서고, 못 읽으면 AI 검색이 꺼졌는지도 알 수 없다.
  const ledgerNote =
    ledgerError !== null ? `실적 원장 후보를 읽지 못했습니다 — ${ledgerError}` : view.mode === "off" && ledgerLoading ? "실적 원장 후보를 읽는 중…" : null;
  const statusText = (status: DisplayStatus, requirementId: string) =>
    status === "off" ? ledgerStatusText(ledger, requirementId, ledgerState) : STATUS_META[status].label;
  // 「참가 차단」 — 대시보드 지도와 같은 기준: 조건 보고서가 있으면 미해결 BLOCKER(사람이 해결하면 빠진다), 없으면 항목 중대성 (RFP-26).
  const blockerIds = useMemo(() => {
    const report = graph.source.analysis.conditions;
    return new Set(
      report
        ? report.conditions.flatMap((c) => (c.status === "BLOCKER" && c.requirement_id ? [c.requirement_id] : []))
        : graph.requirements.filter((r) => criticalityOf(r) === "blocker").map((r) => r.requirement_id),
    );
  }, [graph]);
  /**
   * 담당자가 직접 확인·정정한 항목 수.
   *
   * 0 이면 내려받을 것이 없어 서버가 422 를 낸다. 예전에는 그대로 눌리고 새 탭에 오류가 떴다 —
   * 누르기 전에 「왜 안 되는지」가 보여야 한다.
   */
  const confirmedCount = useMemo(
    () => graph.requirements.filter((r) => r.review_status === "confirmed" || r.review_status === "corrected").length,
    [graph.requirements],
  );
  const rows = useMemo(
    () => graph.requirements.map((req) => ({ req, status: displayStatusOf(req, view) })),
    [graph.requirements, view],
  );

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [statuses, setStatuses] = useState<Set<DisplayStatus>>(() => new Set());
  const [type, setType] = useState<"all" | "mandatory" | "optional">("all");
  const [sortKey, setSortKey] = useState<SortKey>("id");
  const [tab, setTab] = useState<ItemTab["key"]>("all");
  const tabTypes = useMemo(() => ITEM_TABS.find((t) => t.key === tab)?.types ?? null, [tab]);
  const typeCounts = useMemo(() => countByType(rows.map(({ req }) => req)), [rows]);
  const groups = useMemo(() => groupCounts(rows.map(({ req }) => req)), [rows]);

  const categories = useMemo(() => {
    const map = new Map<string, number>();
    for (const { req } of rows) map.set(req.category, (map.get(req.category) ?? 0) + 1);
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = rows.filter(({ req, status }) => {
      if (tabTypes && !tabTypes.includes(itemTypeOf(req))) return false;
      if (category !== "all" && req.category !== category) return false;
      // 43차 E2E-13 — 참고 · 평가 항목은 「필수」 칩에 넣지 않는다(건수 · 칸과 같은 함수)
      if (type !== "all" && (requirementTypeChip(req).mandatory ? "mandatory" : "optional") !== type) return false;
      if (statuses.size > 0 && !statuses.has(status)) return false;
      // 표에 보이는 코드(TSK-004)로도 찾는다 — 저장 id(REQ-004)로만 찾아졌다 (RFP-20).
      if (q && !`${displayCodeOf(req)} ${req.requirement_id} ${req.title} ${req.content} ${req.source_text}`.toLowerCase().includes(q)) return false;
      return true;
    });
    const statusRank: Record<DisplayStatus, number> = { check: 0, failed: 1, old: 2, unmatched: 3, off: 3, partial: 4, not_run: 5, no_row_link: 6, matched: 7 };
    return list.sort((a, b) => {
      switch (sortKey) {
        case "page":
          return (a.req.page ?? 9999) - (b.req.page ?? 9999) || a.req.requirement_id.localeCompare(b.req.requirement_id);
        case "category":
          return a.req.category.localeCompare(b.req.category, "ko") || a.req.requirement_id.localeCompare(b.req.requirement_id);
        case "status":
          return statusRank[a.status] - statusRank[b.status] || a.req.requirement_id.localeCompare(b.req.requirement_id);
        case "criticality":
          return (
            CRITICALITY_RANK[levelOf(a.req, blockerIds.has(a.req.requirement_id))] - CRITICALITY_RANK[levelOf(b.req, blockerIds.has(b.req.requirement_id))] ||
            a.req.requirement_id.localeCompare(b.req.requirement_id)
          );
        default:
          return a.req.requirement_id.localeCompare(b.req.requirement_id);
      }
    });
  }, [rows, query, category, type, statuses, sortKey, tabTypes, blockerIds]);

  const counts = useMemo(() => {
    const tally: Record<DisplayStatus, number> = { matched: 0, partial: 0, unmatched: 0, check: 0, not_run: 0, old: 0, failed: 0, off: 0, no_row_link: 0 };
    for (const { status } of rows) tally[status] += 1;
    return tally;
  }, [rows]);
  const mandatory = rows.filter(({ req }) => requirementTypeChip(req).mandatory).length;
  const optional = rows.length - mandatory;
  // 반려(항목 아님)는 건수에서 빼지 않고 따로 적는다 — 표 · 탭 건수에 그대로 남아 있어 무엇이 반려인지 보이게 (RFP-32).
  const rejected = rows.filter(({ req }) => req.review_status === "rejected").length;
  const selected = selectedReqId ? rows.find(({ req }) => req.requirement_id === selectedReqId) ?? null : null;
  const activeTabLabel = ITEM_TABS.find((t) => t.key === tab)?.label ?? "";
  const onlyTab = tab !== "all" && !query.trim() && category === "all" && type === "all" && statuses.size === 0;
  // 상세의 ← → 는 지금 보이는 표 순서 안에서 — 탭에 없는 항목으로 건너뛰었다 (RFP-31).
  const visibleIds = useMemo(() => filtered.map(({ req }) => req.requirement_id), [filtered]);

  const toggleStatus = (s: DisplayStatus) =>
    setStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });

  return (
    <>
      {/* 제안요청서가 없어 입찰공고문에서 뽑았으면 표가 짧은 이유를 먼저 알린다 (27차 §3-A-4). */}
      {result.document_role === "notice" && <InlineAlert tone="warn">{NOTICE_DOCUMENT_WARNING}</InlineAlert>}
      {/* 2.0.6 — AI 검색을 꺼 둔 회사는 원장 후보가 근거의 유일한 길이다. 못 읽었으면 「근거 없음」 대신 사유와 다시 불러오기 */}
      {/* 제안서를 만들기 전(연결 전)에도 — 그때도 행 상세에서 채택한다(43차 결정 3) */}
      {ledgerError !== null && (
        <InlineAlert tone="warn">
          실적 원장 후보를 읽지 못했습니다 — {ledgerError}
          {view.mode === "off" ? " 행 상태는 「확인 못 함」으로 둡니다." : ""}{" "}
          <button type="button" className="mc-focus rounded font-medium text-cosmos-cyan underline" onClick={() => setLedgerTick((n) => n + 1)}>
            다시 불러오기
          </button>
        </InlineAlert>
      )}
      {/* KPI */}
      <section aria-label="요구사항 요약" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard
          label="요구사항"
          value={result.count}
          unit="건"
          // 문서 이름은 상세 「출처 문서」에 있다 — 여기 두면 긴 이름 뒤 「(근사)」가 늘 잘렸다 (RFP-10).
          hint={`${result.page_count}쪽${result.page_is_approximate ? "(근사)" : ""}${result.truncated ? ` · 후보 ${result.candidate_count ?? "?"}건 중 상한` : ""}`}
          tone={result.truncated ? "warn" : "ok"}
          badge={<SourceBadge kind="computed" label="규칙 추출" />}
        />
        <KpiCard
          label="수행 / 조건 / 제출·일정"
          value={
            <>
              {groups.perform}
              <span className="text-cosmos-muted"> / </span>
              {groups.conditions}
              <span className="text-cosmos-muted"> / </span>
              {groups.submit}
            </>
          }
          hint={`필수 ${mandatory} · 선택 ${result.count - mandatory - groups.other} · 참고·평가 ${groups.other}${rejected > 0 ? ` · 반려 ${rejected}` : ""}`}
          tone="info"
          badge={<SourceBadge kind="rule" label="유형 분류" />}
        />
        <KpiCard
          label="회사 근거 붙은 항목"
          value={
            view.kpiValue ?? (
              <>
                {counts.matched}
                <span className="text-cosmos-muted"> / </span>
                {result.count}
              </>
            )
          }
          hint={
            view.kpiValue !== null
              ? view.kpiHint
              : `후보만 ${counts.partial} · 근거 없음 ${counts.unmatched}` + (view.documentCount > 0 ? ` · 쓴 회사자료 ${view.documentCount}종` : "")
          }
          tone={view.mode === "failed" || view.mode === "old" ? "warn" : view.mode === "not_run" || view.mode === "off" ? "muted" : view.rowLinks && counts.unmatched > 0 ? "warn" : "ok"}
          ratio={view.rowLinks && result.count > 0 ? counts.matched / result.count : null}
          badge={
            <SourceBadge
              kind={view.mode === "not_run" || view.mode === "off" ? "not_run" : view.mode === "ran" ? (view.demo ? "demo" : "analysis") : "failed"}
              // 회사 쪽 근거의 합성 표시는 「합성 회사자료」 — 합성 데모 공고에서만 (RFP-01 · 27차 §3-E 검증 G1-R1) · 45차 마지막 검토 「AI 검색 꺼 둠」(「! 실패」였다)
              label={view.mode === "old" ? "다시 만들어야 함" : view.mode === "off" ? "AI 검색 꺼 둠" : view.mode === "ran" && view.demo ? SYNTHETIC_COMPANY : undefined}
            />
          }
        />
        <KpiCard
          label="확인 필요"
          value={counts.check}
          unit="건"
          hint="사람이 확인·정정해야 하는 항목"
          tone={counts.check > 0 ? "warn" : "pass"}
        />
      </section>

      {/* 항목 유형 탭 — 무엇을 수행 / 어떤 조건 / 무엇을 언제 제출 */}
      {/* 탭 짝 — 탭마다 아래 목록(tabpanel)을 가리킨다 (RFP-21 · 화면 규칙 ④). */}
      <div role="tablist" aria-label="항목 유형" className="mc-scroll flex gap-1 overflow-x-auto rounded-lg border border-cosmos-border bg-cosmos-panel p-1">
        {ITEM_TABS.map((t) => {
          const count = t.types ? t.types.reduce((sum, k) => sum + typeCounts[k], 0) : rows.length;
          const active = tab === t.key;
          const color = t.types ? ITEM_TYPE_COLORS[t.types[0]] : COSMOS_COLORS.cyan;
          return (
            <button
              key={t.key}
              id={`rfp-tab-${t.key}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls="rfp-tabpanel"
              onClick={() => setTab(t.key)}
              className={`mc-focus flex min-h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 text-[12.5px] font-medium transition-colors ${
                active ? "bg-cosmos-blue/25 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"
              }`}
            >
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
              {t.label}
              <span className="font-mono text-[12px] tabular-nums opacity-80">{count}</span>
            </button>
          );
        })}
      </div>
      {/*
        확정 항목이 0 이면 서버가 422 를 낸다. 예전에는 새 탭이 열려 JSON 오류 페이지가 떴다 —
        이제 화면 안에 사유만 뜬다. 라벨에서 「Gold JSON」·422 같은 말은 뺐다.
        탭 줄(줄바꿈 없는 가로 스크롤) 밖 제 줄에 둔다 — 안에 두면 비활성 사유(`w-full`)가 약 800px 에서
        세로 기둥이 됐다 (27차 ISSUE-159). `DownloadLink` 의 부모는 flex-wrap 이어야 한다.
      */}
      <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
        <DownloadLink
          href={goldExportUrl(graph.source.notice.id, "csv")}
          fallbackName="확인한항목.csv"
          disabled={confirmedCount === 0}
          disabledReason="담당자가 확인·정정한 항목이 아직 없습니다. 표에서 항목을 눌러 상세의 「담당자 정정 · 확정」에서 먼저 저장하세요."
          className="mc-focus flex min-h-8 shrink-0 items-center whitespace-nowrap rounded-md px-3 text-[12px] text-cosmos-secondary hover:text-cosmos-text"
          title="담당자가 확인·정정한 항목만 파일로 내려받습니다. 확인한 항목이 없으면 내려받을 것이 없습니다"
        >
          확인한 항목 내려받기 ↓
        </DownloadLink>
      </div>
      {tabTypes && tabTypes.length === 1 && (
        <p className="-mt-2 text-[12px] leading-5 text-cosmos-muted">{ITEM_TYPE_WHAT[tabTypes[0]]}</p>
      )}

      {/* 필터 */}
      <section aria-label="검색과 필터" className="mc-panel flex flex-col gap-3 p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="rfp-search">
            요구사항 검색
          </label>
          <input
            id="rfp-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="코드 · 제목 · 내용 · 원문 검색"
            className="mc-focus min-h-9 w-full flex-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 text-[13px] text-cosmos-text placeholder:text-cosmos-muted sm:max-w-sm"
          />
          <label className="flex items-center gap-1.5 text-[12px] text-cosmos-muted">
            구분
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="mc-focus min-h-9 rounded-lg border border-cosmos-border bg-cosmos-panel px-2 text-[12.5px] text-cosmos-text"
            >
              <option value="all">전체 ({rows.length})</option>
              {categories.map(([name, count]) => (
                <option key={name} value={name}>
                  {name} ({count})
                </option>
              ))}
            </select>
          </label>
          <div role="group" aria-label="정렬" className="ml-auto flex items-center gap-1 rounded-lg border border-cosmos-border bg-cosmos-panel p-0.5">
            {(
              [
                ["id", "코드"],
                ["criticality", "중대성"],
                ["page", "페이지"],
                ["category", "구분"],
                ["status", "상태"],
              ] as Array<[SortKey, string]>
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={sortKey === key}
                onClick={() => setSortKey(key)}
                className={`mc-focus min-h-8 rounded-md px-2.5 text-[12px] font-medium transition-colors ${
                  sortKey === key ? "bg-cosmos-blue/25 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">상태</span>
          {STATUS_FILTERS.filter((s) => counts[s] > 0).map((s) => (
            <Chip key={s} active={statuses.has(s)} color={STATUS_META[s].color} onClick={() => toggleStatus(s)}>
              {STATUS_META[s].label}
              <span className="font-mono text-[12px] tabular-nums opacity-80">{counts[s]}</span>
            </Chip>
          ))}
          <span className="ml-3 mr-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">필수 여부</span>
          {/* 건수를 달고 0건은 숨긴다 — 「선택」 칩은 대부분 0건인데 늘 보였다 (RFP-15). */}
          {(
            [
              ["all", "전체", rows.length],
              ["mandatory", "필수", mandatory],
              ["optional", "선택", optional],
            ] as Array<["all" | "mandatory" | "optional", string, number]>
          )
            .filter(([key, , count]) => key === "all" || count > 0 || type === key)
            .map(([key, label, count]) => (
              <Chip key={key} active={type === key} color={key === "mandatory" ? COSMOS_COLORS.red : COSMOS_COLORS.cyan} onClick={() => setType(key)}>
                {label}
                <span className="font-mono text-[12px] tabular-nums opacity-80">{count}</span>
              </Chip>
            ))}
          <span className="ml-auto font-mono text-[12px] tabular-nums text-cosmos-muted">
            {filtered.length} / {rows.length}건
          </span>
        </div>
        <p className="text-[12px] leading-5 text-cosmos-muted">
          「상태」는 회사 근거 연결 상태입니다. 분류를 직접 확인할 항목은 「확인 필요」가 먼저 보입니다. {view.note}
          {/* 실공고는 근거를 채울 곳으로 — 합성 데모는 합성 회사자료라 해당 없다 (27차 LNK-03). */}
          {!view.demo && (
            <>
              {" "}
              <CompanyDocsLink />
            </>
          )}
        </p>
      </section>

      {/* master-detail */}
      {/*
        상세 칸은 1280px 부터만 옆에 둔다 — 1024~1279 에서 400px 칸이 붙으면 표 칸이 약 560px 뿐이라(표 최소 720)
        「페이지」 · 「상태」 열이 가로 스크롤 밖에 있었다 (RFP-06 · 행을 고른 뒤도 같았다). 1280 미만에서 고르면 아래 시트다.
      */}
      <section
        id="rfp-tabpanel"
        role="tabpanel"
        aria-labelledby={`rfp-tab-${tab}`}
        className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_400px]"
      >
        <div className="min-w-0">
          {filtered.length === 0 ? (
            // 탭만 걸렸는데 0건이면 필터 탓이 아니다 — 이 공고에 그 유형이 없다 (RFP-25).
            onlyTab ? (
              <EmptyState title={`이 공고에는 「${activeTabLabel}」 항목이 없습니다`}>다른 탭을 고르거나 「전체」를 보세요.</EmptyState>
            ) : (
              <EmptyState title="조건에 맞는 요구사항이 없습니다">필터를 줄이거나 검색어를 바꿔 보세요.</EmptyState>
            )
          ) : (
            <>
              <div className="mc-panel hidden overflow-hidden md:block">
                <div className="mc-scroll max-h-[72vh] overflow-auto">
                  <table className="mc-sticky-head w-full min-w-[720px] border-collapse text-[13px]" aria-label="제안요청서 요구사항 목록">
                    <thead>
                      <tr className="border-b border-cosmos-border text-left text-[12px] uppercase tracking-[0.1em] text-cosmos-muted">
                        <th scope="col" className="w-28 px-3 py-2.5 font-semibold">코드</th>
                        <th scope="col" className="w-24 px-3 py-2.5 font-semibold">항목 유형</th>
                        <th scope="col" className="w-20 px-3 py-2.5 font-semibold">필수 여부</th>
                        <th scope="col" className="px-3 py-2.5 font-semibold">요구사항</th>
                        <th scope="col" className="w-16 px-3 py-2.5 font-semibold">페이지</th>
                        <th scope="col" className="w-28 px-3 py-2.5 font-semibold">상태</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map(({ req, status }) => {
                        const active = req.requirement_id === selectedReqId;
                        return (
                          <tr
                            key={req.id}
                            data-req-row={req.requirement_id}
                            aria-selected={active}
                            onClick={() => onSelectReq(active ? null : req.requirement_id)}
                            className={`cursor-pointer border-b border-cosmos-border/70 align-top transition-colors last:border-b-0 ${
                              active ? "bg-cosmos-blue/15" : "hover:bg-cosmos-elevated/50"
                            }`}
                          >
                            <td className="px-3 py-2.5 font-mono text-[12px] text-cosmos-text">
                              <button
                                type="button"
                                className="mc-focus rounded"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onSelectReq(active ? null : req.requirement_id);
                                }}
                                aria-pressed={active}
                                aria-label={`${displayCodeOf(req)} 상세 보기`}
                                title={`저장 id ${req.requirement_id}`}
                              >
                                {displayCodeOf(req)}
                              </button>
                              {blockerIds.has(req.requirement_id) ? (
                                <BlockerBadge className="ml-1" />
                              ) : (
                                // 「중대성」으로 세웠을 때는 높음 · 낮음도 보인다 — 왜 이 순서인지 표에서 읽히게 (RFP-24).
                                sortKey === "criticality" && levelOf(req, false) !== "normal" && <CriticalityBadge level={levelOf(req, false)} className="ml-1" />
                              )}
                              <ReviewBadge req={req} className="ml-1 mt-1" />
                            </td>
                            <td className="px-3 py-2.5">
                              <Badge color={ITEM_TYPE_COLORS[itemTypeOf(req)]}>{ITEM_TYPE_LABELS[itemTypeOf(req)]}</Badge>
                              <p className="mt-0.5 text-[12px] text-cosmos-muted">{req.category}</p>
                            </td>
                            <td className="px-3 py-2.5">
                              <Badge tone={requirementTypeChip(req).mandatory ? "fail" : "muted"}>
                                {requirementTypeChip(req).label}
                              </Badge>
                            </td>
                            <td className="px-3 py-2.5">
                              <p className="font-medium text-cosmos-text">{req.title}</p>
                              <p className="mt-0.5 line-clamp-2 text-[12.5px] leading-5 text-cosmos-secondary">{req.content}</p>
                            </td>
                            <td className="px-3 py-2.5 font-mono text-[12px] text-cosmos-secondary" title={result.page_is_approximate ? "문단 묶음 기준 근사 쪽수" : undefined}>
                              {pageText(req.page, result.page_is_approximate)}
                            </td>
                            <td className="px-3 py-2.5">
                              <Badge color={STATUS_META[status].color} glyph={status === "check" ? "!" : status === "matched" ? "●" : "○"}>
                                {statusText(status, req.requirement_id)}
                              </Badge>
                              {req.findings.length > 0 && (
                                <Badge tone="fail" className="ml-1">
                                  경고 {req.findings.length}
                                </Badge>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
              <ul className="flex flex-col gap-2 md:hidden" aria-label="요구사항 카드 목록">
                {filtered.map(({ req, status }) => {
                  const active = req.requirement_id === selectedReqId;
                  return (
                    <li key={req.id} data-req-row={req.requirement_id}>
                      <button
                        type="button"
                        onClick={() => onSelectReq(active ? null : req.requirement_id)}
                        aria-pressed={active}
                        className={`mc-focus mc-panel flex w-full flex-col gap-1.5 p-3 text-left ${active ? "border-cosmos-cyan/60" : ""}`}
                      >
                        <span className="flex items-center gap-2">
                          <span className="font-mono text-[12px] text-cosmos-muted">{displayCodeOf(req)}</span>
                          {/* 폰 목록에서도 참가를 막는 항목을 알아보게 (RFP-28) */}
                          {blockerIds.has(req.requirement_id) && <BlockerBadge />}
                          <ReviewBadge req={req} />
                          <Badge color={ITEM_TYPE_COLORS[itemTypeOf(req)]}>{ITEM_TYPE_LABELS[itemTypeOf(req)]}</Badge>
                          <Badge tone={requirementTypeChip(req).mandatory ? "fail" : "muted"}>{requirementTypeChip(req).label}</Badge>
                          <span className="ml-auto font-mono text-[12px] text-cosmos-muted">{pageText(req.page, result.page_is_approximate)}</span>
                        </span>
                        <span className="text-[14px] font-semibold text-cosmos-text">{req.title}</span>
                        <span className="line-clamp-2 text-[12.5px] leading-5 text-cosmos-secondary">{req.content}</span>
                        <span className="flex items-center gap-1.5">
                          <Badge color={STATUS_META[status].color}>{statusText(status, req.requirement_id)}</Badge>
                          {req.findings.length > 0 && <Badge tone="fail">경고 {req.findings.length}</Badge>}
                          <Badge tone="info">{req.category}</Badge>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>

        {/* 상세: 데스크톱은 우측 고정, 모바일은 하단 시트 */}
        <div
          className={`${selected ? "fixed inset-x-2 bottom-2 z-40 flex max-h-[70vh] flex-col xl:static xl:max-h-none" : "hidden xl:block"} xl:sticky xl:top-20 xl:z-auto xl:self-start`}
        >
          {selected ? (
            <RequirementDrawer
              graph={graph}
              req={selected.req}
              status={selected.status}
              result={result}
              view={view}
              blocked={blockerIds.has(selected.req.requirement_id)}
              visibleIds={visibleIds}
              onClose={() => onSelectReq(null)}
              onSelectReq={onSelectReq}
              onReload={onReload}
              dashboardLink={dashboardLink}
              ledger={ledger}
              ledgerNote={ledgerNote}
              onLedgerChange={setLedger}
            />
          ) : (
            <div className="mc-panel p-5 text-[13px] leading-6 text-cosmos-secondary">
              <p className="text-[14px] font-semibold text-cosmos-text">행을 선택하면 원문과 근거를 나란히 봅니다</p>
              <p className="mt-2">
                제안요청서 원문(쪽)과 규칙으로 뽑은 결과를 나눠 보여 주고, 붙은 회사 근거와 충족 상태, 확인할 이유를 함께 봅니다.
              </p>
              <p className="mt-2 text-[12px] text-cosmos-muted">데이터가 없는 항목은 「확인되지 않음」으로 두고 그럴듯한 내용을 만들어 넣지 않습니다.</p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// 상세 Drawer
// ---------------------------------------------------------------------------

/**
 * 실적 조건 항목 ↔ 회사 실적 원장 대조 (버튼을 눌러야 조회한다 — 힌트이며 판정이 아니다).
 *
 * 합성 데모 공고는 공개 자료라 회사 실적 원장을 쓰지 않는다 — 단추를 누르면 늘 개발자 명령이 담긴 안내가 떴다(RFP-02).
 * 원장이 없다는 서버 문장도 개발자용이라 화면에서는 사람 말로 바꾼다.
 */
function PerformanceMatchSection({ req, noticeId, demo }: { req: RequirementView; noticeId: string; demo: boolean }) {
  const [state, setState] = useState<{ kind: "idle" } | { kind: "loading" } | { kind: "ready"; value: ItemPerformanceMatch } | { kind: "error"; message: string }>({ kind: "idle" });
  const run = () => {
    setState({ kind: "loading" });
    getItemPerformanceMatch(noticeId, req.requirement_id, analysisContext(noticeId, readOrganizationId()))
      .then((value) => setState({ kind: "ready", value }))
      .catch((e: unknown) => setState({ kind: "error", message: describeFailure(e, "조회하지 못했습니다.") }));
  };
  return (
    <section className="flex flex-col gap-2 border-t border-cosmos-border pt-3">
      <h3 className="flex items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
        실적 요건 대조
        {!demo && (
          <Button size="sm" variant="secondary" onClick={run} disabled={state.kind === "loading"}>
            {state.kind === "loading" ? "대조 중…" : state.kind === "ready" ? "다시 대조" : "실적 목록과 대조"}
          </Button>
        )}
      </h3>
      {demo && <p className="text-[12px] text-cosmos-muted">가상 예시 공고에는 회사 실적 목록을 쓰지 않습니다 — 실공고에서 이 회사의 실적 목록과 대조합니다.</p>}
      {!demo && state.kind === "idle" && <p className="text-[12px] text-cosmos-muted">이 항목의 건수·금액·기간 조건을 회사 실적 목록(외부에 낼 수 있는 실적)과 대조합니다. 결과는 힌트이며 인정 여부는 담당자가 정합니다.</p>}
      {state.kind === "error" && <p className="text-[12px] text-cosmos-red">{state.message}</p>}
      {state.kind === "ready" && !state.value.report.ledger_available && (
        <p className="text-[12px] text-cosmos-muted">
          이 회사의 실적 목록이 없어 대조하지 못했습니다 — 회사자료 화면에서 실적 목록을 먼저 올리세요. <CompanyDocsLink />
        </p>
      )}
      {state.kind === "ready" && state.value.report.ledger_available && <LedgerMatchBlock report={state.value.report} />}
    </section>
  );
}

/** 담당자 정정 — 유형·필수여부·페이지를 고치거나 확정/반려한다. 원본 추출 파일은 그대로, 이력으로 쌓인다. */
function CorrectionForm({ req, noticeId, onSaved }: { req: RequirementView; noticeId: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  // 로그인했으면 정정자 이름을 채워 둔다 — 이 이름이 정정 이력에 그대로 남는다.
  // 로그인하지 않았으면 지금까지처럼 빈 칸이다.
  const [reviewer, setReviewer] = useState(() => currentUserName() || readReviewer());
  const [itemType, setItemType] = useState<ItemType>(itemTypeOf(req));
  const [reqType, setReqType] = useState(req.requirement_type);
  const [page, setPage] = useState(req.page ? String(req.page) : "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // 45차 M4 — 열람자는 정정 · 확정 못 함(누른 뒤에야 「편집자 이상만」이 떴다)
  const viewer = useViewerLock();

  const submit = (status: "confirmed" | "corrected" | "rejected") => {
    if (!reviewer.trim()) {
      setMessage("검토자 이름이 필요합니다.");
      return;
    }
    setBusy(true);
    setMessage(null);
    rememberReviewer(reviewer.trim());
    correctRfpItem(noticeId, req.requirement_id, {
      reviewer: reviewer.trim(),
      review_status: status,
      item_type: status === "corrected" ? itemType : undefined,
      requirement_type: status === "corrected" ? reqType : undefined,
      page: status === "corrected" && page ? Number(page) : undefined,
      note: note.trim() || null,
    })
      .then((r) => {
        setMessage(`저장했습니다 — ${displayCodeOf(r.item)} · ${REVIEW_STATUS_LABELS[r.item.review_status ?? "unreviewed"]}`);
        // 표의 상태 배지를 바로 갱신한다. 예전에는 「다음에 불러올 때 반영됩니다」로 끝나서
        // 담당자가 저장이 됐는지 확인할 방법이 없었다.
        onSaved();
      })
      .catch((e: unknown) => setMessage(describeFailure(e, "저장하지 못했습니다.")))
      .finally(() => setBusy(false));
  };

  return (
    <section className="flex flex-col gap-2 border-t border-cosmos-border pt-3">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mc-focus flex min-h-8 items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
        담당자 정정 · 확정
        <span className="font-normal normal-case tracking-normal text-cosmos-secondary">{open ? "접기" : "열기"}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              항목 유형
              <select className="mc-focus min-h-8 rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2 text-[12px] text-cosmos-text" value={itemType} onChange={(e) => setItemType(e.target.value as ItemType)}>
                {ITEM_TYPE_ORDER.map((t) => (
                  <option key={t} value={t}>
                    {ITEM_TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              필수 여부
              <select className="mc-focus min-h-8 rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2 text-[12px] text-cosmos-text" value={reqType} onChange={(e) => setReqType(e.target.value as "mandatory" | "optional")}>
                <option value="mandatory">필수</option>
                <option value="optional">선택</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              페이지
              <input className="mc-focus min-h-8 rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2 text-[12px] text-cosmos-text" value={page} onChange={(e) => setPage(e.target.value.replace(/\D/g, ""))} inputMode="numeric" />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              검토자 (필수)
              <input className="mc-focus min-h-8 rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2 text-[12px] text-cosmos-text" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </label>
          </div>
          <input className="mc-focus min-h-8 rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2 text-[12px] text-cosmos-text" placeholder="메모 (왜 고쳤는지)" value={note} onChange={(e) => setNote(e.target.value)} />
          {viewer && <p className="text-[12px] text-cosmos-muted" title={VIEWER_LOCK_REASON} data-viewer-lock>{VIEWER_LOCK_LABEL} — 정정 · 확정은 편집자 이상이 합니다.</p>}
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="primary" disabled={busy || viewer} onClick={() => submit("confirmed")}>
              확정 (그대로 맞음)
            </Button>
            <Button size="sm" variant="secondary" disabled={busy || viewer} onClick={() => submit("corrected")}>
              정정 저장
            </Button>
            <Button size="sm" variant="ghost" disabled={busy || viewer} onClick={() => submit("rejected")} className="text-cosmos-red">
              반려 (항목 아님)
            </Button>
          </div>
          {message && <p className="text-[12px] text-cosmos-secondary">{message}</p>}
          <p className="text-[12px] leading-4 text-cosmos-muted">항목 코드 앞자리는 고른 유형을 따라 바뀝니다(지금 {displayCodeOf(req)} · 뒤 번호는 그대로). 확정·정정한 항목만 「확인한 항목 내려받기」에 담깁니다.</p>
          {/* 정정 기록은 공고 단위 공용 파일이다 — 어느 회사에서 고쳐도 모두의 표가 바뀐다 (RFP-14). */}
          <p className="text-[12px] leading-4 text-cosmos-amber">정정 · 확정 기록은 회사 구분 없이 이 공고를 보는 모든 회사 화면에 함께 반영됩니다.</p>
        </div>
      )}
    </section>
  );
}

/** 출처 문서 칸의 저장 코드 → 사람 말 (RFP-33). */
const SOURCE_NAMES: Record<string, string> = { g2b_attachment: "나라장터 첨부", synthetic_fixture: "가상 예시 공고 첨부" };

/** 1280 미만에서는 상세가 표를 덮는 아래 시트다 (RFP-29) — 옆 칸 400px 이 붙으면 표의 「상태」 열이 밀려났다. */
const SHEET_QUERY = "(max-width: 1279.98px)";
function subscribeSheet(onChange: () => void): () => void {
  const media = window.matchMedia(SHEET_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const readSheet = () => window.matchMedia(SHEET_QUERY).matches;
const readSheetServer = () => false;

/** 마지막으로 쓴 검토자 이름 — 로그인하지 않은 로컬에서 항목마다 다시 적어야 했다 (RFP-30). 이 브라우저에만 남는다. */
const REVIEWER_KEY = "bidpilot.rfp.reviewer";
function readReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}
function rememberReviewer(name: string): void {
  try {
    window.localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    // 저장소를 못 써도 저장은 그대로 된다
  }
}

function Field({ label, children, mono = false }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="contents">
      <dt className="text-[12px] text-cosmos-muted">{label}</dt>
      <dd className={`min-w-0 break-words text-[13px] text-cosmos-text ${mono ? "font-mono tabular-nums" : ""}`}>{children}</dd>
    </div>
  );
}

function RequirementDrawer({
  graph,
  req,
  status,
  result,
  view,
  blocked,
  visibleIds,
  onClose,
  onSelectReq,
  onReload,
  dashboardLink,
  ledger,
  ledgerNote,
  onLedgerChange,
}: {
  graph: CosmosGraph;
  req: RequirementView;
  status: DisplayStatus;
  result: RfpParseResult;
  view: RfpEvidenceView;
  blocked: boolean;
  visibleIds: string[];
  onClose: () => void;
  onSelectReq: (id: string) => void;
  onReload: () => void;
  dashboardLink: React.ReactNode;
  ledger: LedgerView | null;
  /** 원장 후보를 읽는 중 · 못 읽음 한 줄(2.0.6) — 있으면 채택 칸 자리에 적는다. */
  ledgerNote: string | null;
  onLedgerChange: (next: LedgerView) => void;
}) {
  const meta = STATUS_META[status];
  const noticeId = graph.source.notice.id;
  const reasons: string[] = [];
  if (req.status === "check" && !isReviewed(req)) {
    if (/현장\s*설명|설명회|현장\s*방문/.test(req.content)) {
      reasons.push("참석이 입찰 조건일 수 있습니다. 일시·장소·사전 신청기한과 참석 증빙을 공고문에서 확인하세요.");
    } else {
      reasons.push("자동으로 확정할 수 없는 조건입니다. 원문을 확인하고 담당자가 분류와 충족 여부를 확정해야 합니다.");
    }
  }
  if (status === "unmatched") reasons.push("연결된 회사 근거가 없습니다. 자동으로 충족 처리하지 않습니다.");
  if (status === "partial") reasons.push("후보 근거만 있고 채택된 근거가 없습니다.");
  if (status === "not_run") reasons.push("회사 근거 연결을 하지 않았습니다. 실공고에서는 회사자료 색인과 AI 검색 설정이 필요합니다.");
  // 연결 실패 · 이전 결과의 사유는 바로 위 「연결된 회사 근거」 칸에 한 번만 적는다 — 같은 문장이 두 번 나왔다 (RFP-07).
  if (result.page_is_approximate) reasons.push("HWP/HWPX는 페이지 정보가 없어 문단 묶음 기준 근사 페이지입니다.");
  for (const f of req.findings) reasons.push(`제출 전 점검 경고: ${f.recommendation}`);

  // 지금 보이는 표(탭 · 필터 · 정렬) 순서 안에서 옮긴다 (RFP-31).
  const index = visibleIds.indexOf(req.requirement_id);
  const prev = index > 0 ? visibleIds[index - 1] : null;
  const next = index >= 0 && index < visibleIds.length - 1 ? visibleIds[index + 1] : null;

  // 아래 시트일 때는 대화상자다 — 열리면 초점을 옮기고 Esc 로 닫는다(표 뒤에 초점이 남았다 · RFP-29).
  // 처음 열 때만 옮긴다 — 항목마다 옮기면 ← → 로 넘길 때 초점이 단추에서 시트 전체로 튀었다.
  const sheet = useSyncExternalStore(subscribeSheet, readSheet, readSheetServer);
  const asideRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (sheet) asideRef.current?.focus();
  }, [sheet]);
  // 첫 · 마지막 항목에서 누른 ← → 는 막힌 단추가 되어 초점이 화면 밖(body)으로 빠진다 — 그때만 상세로 받는다.
  // 시트가 열린 채 뒤쪽 표에서 다른 행을 고르면 초점이 대화상자 밖에 남았다 — 그때도 상세로 받는다(§3-F RFP-29 검증).
  useEffect(() => {
    const active = document.activeElement;
    if (active instanceof HTMLButtonElement && active.disabled && asideRef.current?.contains(active)) asideRef.current.focus();
    else if (sheet && !asideRef.current?.contains(active)) asideRef.current?.focus();
    // sheet 는 일부러 뺀다 — 여닫힘은 위 effect 가 맡고, 이것은 항목이 바뀔 때만
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req.requirement_id]);
  useEffect(() => {
    if (!sheet) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheet, onClose]);

  return (
    <aside
      ref={asideRef}
      tabIndex={-1}
      role={sheet ? "dialog" : undefined}
      aria-modal={sheet || undefined}
      // 이름은 화면에 보이는 코드로 — 저장 id(REQ-011)가 읽혔다 (RFP-21).
      aria-labelledby="rfp-drawer-title"
      // 시트는 표 위를 덮으므로 비치지 않게 (투명 판 아래 글이 겹쳐 읽혔다)
      className="mc-panel flex max-h-[70vh] min-h-0 flex-col outline-none max-xl:bg-cosmos-panel-solid! xl:max-h-[calc(100dvh-6rem)]"
    >
      {/* 390 에서 「필수 요구사항」+「근거 연결 전」이면 ✕ 가 창 밖으로 밀렸다 — 줄을 넘긴다 (RFP-08). */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-cosmos-border px-4 py-2.5">
        <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color, boxShadow: `0 0 8px ${meta.color}` }} />
        <p id="rfp-drawer-title" className="font-mono text-[12px] text-cosmos-text" title={`저장 id ${req.requirement_id}`}>
          {displayCodeOf(req)}
          <span className="sr-only"> 상세</span>
        </p>
        <Badge color={ITEM_TYPE_COLORS[itemTypeOf(req)]}>{ITEM_TYPE_LABELS[itemTypeOf(req)]}</Badge>
        <Badge color={meta.color} glyph={status === "check" ? "!" : "●"}>
          {meta.label}
        </Badge>
        <div className="ml-auto flex items-center gap-1">
          {/* 지금 보이는 표 안의 자리 — 첫 · 마지막에서 ← → 가 왜 막혔는지도 이것이 말한다 */}
          <span className="px-1 font-mono text-[12px] tabular-nums text-cosmos-muted">
            {index >= 0 ? `${index + 1} / ${visibleIds.length}` : "표 밖 항목"}
          </span>
          <Button size="sm" variant="ghost" disabled={!prev} onClick={() => prev && onSelectReq(prev)} aria-label="이전 요구사항">
            ←
          </Button>
          <Button size="sm" variant="ghost" disabled={!next} onClick={() => next && onSelectReq(next)} aria-label="다음 요구사항">
            →
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="상세 닫기">
            ✕
          </Button>
        </div>
      </div>
      <div className="mc-scroll flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4" style={{ animation: "mc-fade-up 160ms ease-out" }}>
        <section className="flex flex-col gap-2">
          <h3 className="flex items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
            제안요청서 원문
            {/* 합성 원문은 합성 표시 — 초록 「실데이터」 색에 라벨만 합성이었다 (RFP-33). */}
            <SourceBadge kind={graph.source.origin.kind === "demo" ? "demo" : "computed"} label={graph.source.origin.kind === "demo" ? "가상 예시 공고 첨부 원문" : "제안요청서 원문"} />
          </h3>
          <blockquote className="rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 py-2 text-[13px] leading-6 text-cosmos-secondary">
            <p className="mb-1 font-mono text-[12px] text-cosmos-muted">
              {result.document} · {formatPage(req.page)}
              {result.page_is_approximate ? " (근사)" : ""}
            </p>
            <p className="whitespace-pre-wrap">{req.source_text || "확인되지 않음"}</p>
          </blockquote>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="flex items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
            구조화 결과
            <Badge tone="info" glyph="◇">
              {METHOD_LABELS[req.extraction_method]}
            </Badge>
          </h3>
          <p className="text-[15px] font-semibold leading-snug text-cosmos-text">{req.title}</p>
          <p className="text-[13px] leading-6 text-cosmos-secondary">{req.content}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
            <Field label="항목 유형">
              <span className="flex flex-wrap items-center gap-1.5">
                <Badge color={ITEM_TYPE_COLORS[itemTypeOf(req)]}>{ITEM_TYPE_LABELS[itemTypeOf(req)]}</Badge>
                {/* 참가 차단은 아래 「충족 상태」의 「참가 차단 조건」 한 곳 — 여기서는 높음 · 낮음만 (RFP-26) */}
                {levelOf(req, blocked) !== "normal" && levelOf(req, blocked) !== "blocker" && <CriticalityBadge level={levelOf(req, blocked)} />}
                {req.action_required && <Badge tone="warn">할 일 있음</Badge>}
                <ReviewBadge req={req} />
              </span>
            </Field>
            {req.due_at && (
              <Field label="기한" mono>
                {formatDateTime(req.due_at)}
              </Field>
            )}
            <Field label="구분">{req.category}</Field>
            <Field label="필수 여부">
              <Badge tone={requirementTypeChip(req).mandatory ? "fail" : "muted"}>{requirementTypeChip(req).label}</Badge>
            </Field>
            <Field label="출처 문서">
              {result.document} · {result.doc_format ?? /\.([a-z0-9]+)$/i.exec(result.document)?.[1]?.toLowerCase() ?? "형식 미확인"} ·{" "}
              {SOURCE_NAMES[result.source] ?? result.source}
            </Field>
            <Field label="추출 시각" mono>
              {formatDateTime(result.generated_at)}
            </Field>
          </dl>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="flex items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
            연결된 회사 근거 {view.rowLinks ? req.evidence.length : ""}
            {/* 표 머리와 **같은 판정**을 쓴다 (0920 §4-B-5 · RFP-05). */}
            <SourceBadge
              kind={view.mode === "not_run" || view.mode === "off" ? "not_run" : view.mode === "ran" ? (view.demo ? "demo" : "analysis") : "failed"}
              label={view.mode === "ran" ? (view.demo ? SYNTHETIC_COMPANY : "회사자료") : view.mode === "off" ? "AI 검색 꺼 둠" : STATUS_META[view.mode].label}
            />
          </h3>
          {view.mode !== "ran" || !view.rowLinks ? (
            <p
              className={`rounded-lg border border-dashed px-3 py-2 text-[12.5px] leading-5 ${
                view.mode === "failed" || view.mode === "old" ? "border-cosmos-amber/50 text-cosmos-amber" : "border-cosmos-border-strong text-cosmos-muted"
              }`}
            >
              {view.note} {view.mode === "not_run" && "근거 없이 「충족」으로 표시하지 않습니다."} {!view.demo && <CompanyDocsLink />}
            </p>
          ) : req.evidence.length === 0 ? (
            <p className="rounded-lg border border-dashed border-cosmos-amber/50 px-3 py-2 text-[12.5px] leading-5 text-cosmos-amber">
              연결된 회사 근거가 없습니다 — 근거 없음. 자동으로 충족 처리하지 않습니다.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {req.evidence.map((ev) => (
                <li
                  key={ev.evidence_id}
                  className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2"
                  style={{ borderLeft: `2px solid ${ev.selected ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet}` }}
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-cosmos-text">{ev.document.document_name}</span>
                    <span className="font-mono text-[12px] text-cosmos-muted">{formatPage(ev.document.page)}</span>
                    <span className="font-mono text-[12px] tabular-nums text-cosmos-secondary">유사도 {formatSimilarity(ev.similarity_score)}</span>
                    <Badge tone={ev.selected ? "ok" : "muted"}>{ev.selected ? "채택" : "후보"}</Badge>
                  </div>
                  <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">“{ev.document.source_text}”</p>
                  <p className="mt-1 text-[12px] text-cosmos-muted">
                    {ev.document.doc_type} · {ev.document.synthetic ? "가상 예시 자료" : "실제 자료 (비식별)"}
                    {ev.note ? ` · ${ev.note}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 45차 H5 — AI 검색을 꺼 둔 회사는 실적 원장 후보에서 고른다(채택 단추 · 누가 · 언제 · 열람자 잠금) */}
        {ledgerNote ? (
          <p className="rounded-lg border border-dashed border-cosmos-border-strong px-3 py-2 text-[12.5px] leading-5 text-cosmos-amber" role="status">
            {ledgerNote}
          </p>
        ) : (
          <LedgerAdoptionBlock noticeId={noticeId} requirementId={req.requirement_id} ledger={ledger} onChanged={onLedgerChange} />
        )}

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">충족 상태 · 검토 필요 사유</h3>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge color={meta.color} size="md" glyph={status === "check" ? "!" : "●"}>
              {meta.label}
            </Badge>
            {/* 두 번째 배지는 새 사실이 있을 때만 — 「근거 연결」+「충족」 · 「확인 필요」+「확인 필요」처럼 같은 뜻이 두 번이었고,
                점검을 돌린 적 없는 참가 차단 항목에 「Auditor 경고」가 붙었다 (RFP-12). */}
            {blocked && <BlockerBadge label="참가 차단 조건" />}
            {req.findings.length > 0 && (
              <Badge tone="fail" glyph>
                제출 전 점검 경고 {req.findings.length}
              </Badge>
            )}
          </div>
          {reasons.length === 0 ? (
            <p className="text-[12.5px] text-cosmos-muted">추가 검토 사유가 없습니다.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-[12.5px] leading-5 text-cosmos-secondary">
              {reasons.map((r) => (
                <li key={r} className="flex gap-2">
                  <span aria-hidden="true" style={{ color: TONE_COLORS.warn }}>
                    •
                  </span>
                  {r}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/*
          `key` 가 없으면 두 컴포넌트의 useState 가 **이전 항목의 값을 그대로 들고 있는다.**
          REQ-A 에서 유형을 바꿔 두고 REQ-B 로 옮긴 뒤 「정정 저장」을 누르면 A 의 값이 B 에 기록됐다.
          원장 대조 결과도 이전 항목 것이 남아 있었다. 항목이 바뀌면 새로 만든다.
        */}
        {/* 서버 is_performance_text 와 같은 낱말 — 납품 · 용역 경험도 실적이다 (RFP-02) */}
        {/실적|수행\s*경험|납품\s*경험|용역\s*경험|계약\s*(?:건수|금액)/.test(`${req.content} ${req.source_text}`) && (
          <PerformanceMatchSection key={req.requirement_id} req={req} noticeId={noticeId} demo={graph.source.origin.kind === "demo"} />
        )}

        <CorrectionForm key={req.requirement_id} req={req} noticeId={noticeId} onSaved={onReload} />

        <div className="flex flex-wrap gap-2 border-t border-cosmos-border pt-3">{dashboardLink}</div>
      </div>
    </aside>
  );
}
