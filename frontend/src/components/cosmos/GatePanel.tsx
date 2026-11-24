"use client";

/**
 * Go / Hold / No-Go · Critical Conditions · Action Checklist — 상세 패널 안의 "게이트" 블록.
 *
 * - 조건은 규칙이 찾고(규칙 기반), 해결(CLEARED)은 사람만 한다(사람 확인). 시스템은 자동으로 풀지 않는다.
 * - 미해결 BLOCKER가 있으면 GO 버튼을 막고 사유를 그대로 보여준다 (backend도 422로 막는다).
 * - 완료 표시는 사람이 하고, 근거(evidence)를 함께 적게 한다.
 */

import { useState, type ReactNode } from "react";

import { Badge, Button } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { CONDITION_STATUS_LABELS, DECISION_LABELS, PANEL_TITLES, formatDateTime, formatPage, sourceFieldText } from "@/lib/cosmos/format";
import { requirementNodeId, type CosmosGraph } from "@/lib/cosmos/graph";
import { staleBlockReason, staleReadiness } from "@/lib/cosmos/stale";
import { blockingText, decisionGateLine, eligibilityGateView } from "@/lib/cosmos/eligibilityGate";
import { runStamp } from "@/lib/cosmos/runStamp";
import { useAnalysisLoading } from "@/lib/cosmos/analysisLoading";
import { REVIEWER_STORAGE_KEY, clearDraft, loadDraft, saveDraft } from "@/lib/unsavedGuard";
import { useOrganizationId } from "@/lib/organization";
import { currentUserName } from "@/lib/currentUser";
import { COSMOS_COLORS, TONE_COLORS, type Tone } from "@/lib/cosmos/theme";
import type { AnalysisActions } from "@/lib/cosmos/useCosmosDashboard";
import type {
  ActionItem,
  ConditionFreshness,
  ConditionStatus,
  CriticalCondition,
  DecisionStatus,
  PerformanceMatchReport,
} from "@/types/gate";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import { useReqCode } from "@/lib/cosmos/reqCode";
import { requestConsent } from "@/lib/consentPrompt";
import { groupActions } from "@/lib/cosmos/actionGroups";


/** 담당자 이름은 화면마다 다시 묻지 않는다 — 최종 검토 저장(셸)도 같은 값을 쓴다. */
export function readReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storeReviewer(name: string): void {
  try {
    window.localStorage.setItem(REVIEWER_STORAGE_KEY, name);
  } catch {
    // 저장 실패는 무시한다.
  }
}

/**
 * 담당자 입력칸의 기본값.
 *
 * 로그인했으면 그 이름으로 채운다 — 결정·해결 처리는 「누가 했는가」가 기록의 전부인데,
 * 매번 손으로 적으면 「홍길동」·「홍 길동」·「hong」이 한 사람의 기록으로 흩어진다.
 * 로그인하지 않았으면(로컬 개발) 지금까지처럼 브라우저에 기억해 둔 값을 쓴다.
 *
 * 채워 넣기만 하고 잠그지는 않는다 — 대신 결재하거나 대리로 적는 일이 실제로 있다.
 */
export function defaultReviewer(): string {
  return currentUserName() || readReviewer();
}

const CONDITION_TONE: Record<ConditionStatus, Tone> = {
  BLOCKER: "fail",
  ACTION: "warn",
  CHECK: "warn",
  CLEARED: "pass",
  INFO: "info",
};

// 라벨 사전은 lib/cosmos/format.ts 한 곳에 둔다 (ISSUE-016).
const CONDITION_LABEL = CONDITION_STATUS_LABELS;

/**
 * 저장된 조건 보고서가 «지금 요구사항 집합» 기준인지.
 *
 * `unknown` 은 옛 저장본(탐지 당시 해시가 없다)이다. 이것을 「최신」이라고 적으면
 * 확인한 적 없는 것을 확인했다고 말하는 것이라, 「확인 안 됨」으로 적는다.
 */
const FRESHNESS_LABEL: Record<ConditionFreshness, string> = {
  current: "최신 기준",
  stale: "요구사항이 바뀐 뒤 다시 안 찾음",
  unknown: "기준 확인 안 됨",
};
const FRESHNESS_TONE: Record<ConditionFreshness, Tone> = { current: "pass", stale: "warn", unknown: "muted" };

const DECISION_TONE: Record<DecisionStatus, Tone> = { GO: "pass", HOLD: "warn", NO_GO: "fail", UNREVIEWED: "muted" };
const DECISION_LABEL = DECISION_LABELS;

const PRIORITY_COLOR: Record<ActionItem["priority"], string> = {
  urgent: COSMOS_COLORS.red,
  high: COSMOS_COLORS.amber,
  normal: COSMOS_COLORS.blue,
  low: COSMOS_COLORS.slate,
};

function Block({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center justify-between gap-2 text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
        <span>{title}</span>
        {aside}
      </h3>
      {children}
    </section>
  );
}

const inputClass =
  "mc-focus min-h-8 w-full rounded-md border border-cosmos-border bg-cosmos-elevated/70 px-2 text-[12px] text-cosmos-text placeholder:text-cosmos-muted";

// ---------------------------------------------------------------------------
// 결정
// ---------------------------------------------------------------------------

export function DecisionBlock({ graph, actions }: { graph: CosmosGraph; actions: AnalysisActions }) {
  const { decision, conditions } = graph.source.analysis;
  const decisionError = graph.source.analysis.decisionError ?? null;
  const status: DecisionStatus = decision?.status ?? "UNREVIEWED";
  const gate = conditions?.gate ?? null;
  const loading = useAnalysisLoading();
  const viewer = useViewerLock();
  const [reviewer, setReviewer] = useState(defaultReviewer);
  /**
   * 사유는 「왜 참여하지 않기로 했는가」를 설명하는 유일한 기록이다. 공고를 바꾸거나
   * 새로고침하면 말없이 사라졌다 (ISSUE-010). 공고별로 임시 저장하고 돌아오면 되살린다.
   */
  // 회사도 넣는다 — 회사를 바꾸면 쓰던 사유가 다른 회사의 같은 공고 칸에 되살아났다(회사자료 카드와 같은 규칙 · 2.0.6).
  const organizationId = useOrganizationId();
  const draftKey = `decision:${organizationId}:${graph.source.notice.id}`;
  const [reasons, setReasons] = useState(() => loadDraft(draftKey));
  // 열쇠(회사 · 공고)가 바뀌면 그 열쇠의 저장본으로 다시 채운다 — 처음 한 번만 읽어, 회사를 바꿔도 앞 회사 글이 남아 새 회사 결정으로 저장됐다(2.0.6).
  const [reasonsKey, setReasonsKey] = useState(draftKey);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<DecisionStatus | null>(null);
  if (reasonsKey !== draftKey) {
    setReasonsKey(draftKey);
    setReasons(loadDraft(draftKey));
    // 메모 · 「결정자와 사유가 필요합니다」 경고도 앞 회사 · 공고의 것이다 — 남기면 다른 회사 결정에 함께 저장됐다(2.0.6 마지막 검토)
    setNote("");
    setPending(null);
  }

  const editReasons = (value: string) => {
    setReasons(value);
    saveDraft(draftKey, value);
  };

  const submit = (next: DecisionStatus) => {
    const lines = reasons
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (!reviewer.trim() || lines.length === 0) {
      setPending(next);
      return;
    }
    storeReviewer(reviewer.trim());
    setPending(null);
    // 저장된 뒤에만 비운다 — 서버가 거절하면(권한 · 검사 · 끊김) 적은 사유가 남아야 한다 (DTL-09).
    void actions.saveDecision({ status: next, reasons: lines, decided_by: reviewer.trim(), note: note.trim() || null }).then((saved) => {
      if (!saved) return;
      clearDraft(draftKey);
      setReasons("");
      setNote("");
    });
  };

  /**
   * GO 를 막는 두 가지.
   *
   * 1) 참가를 막는 미해결 조건(BLOCKER) — 예전부터 있던 규칙.
   * 2) **구버전 결과** — 지금 보이는 판정이 이전 요구사항 기준이면 그 근거로 참여를 결정할 수 없다.
   *    backend 도 422 로 막는다(decision_service._refuse_stale_go). 화면에서만 막으면
   *    다른 경로로 저장될 수 있고, backend 에서만 막으면 사용자가 이유 없이 실패를 본다.
   */
  const stale = staleReadiness(graph);
  // 참가자격 종합이 불가면 「참여」를 막는다 (20차 §4-C-4) — 백엔드도 422 로 막는다. 화면이 먼저 이유를 말한다.
  const eligibility = eligibilityGateView(graph.eligibility, graph.source.analysis.eligibility?.verdict ?? null);
  const ineligible = eligibility?.verdict === "FAIL";
  const ineligibleReason = ineligible
    ? `참가자격이 「불가」라 「참여」를 저장할 수 없습니다 — ${eligibility?.blocking ? blockingText(eligibility.blocking) : "막는 조건이 있습니다"}`
    : null;
  const goBlocked = (gate !== null && !gate.can_go) || stale !== null || ineligible;
  const goBlockReason = ineligibleReason ?? (stale ? staleBlockReason(stale) : gate?.reason);
  // 확정 안 한 조항 · 공고 분석 전이면 「차단 조건 없음」이라 하지 않는다 (P1-02)
  const gateLine = gate ? decisionGateLine(gate, conditions?.requirements_available ?? true, eligibility) : null;
  return (
    <Block title="참여 · 보류 · 참여 안 함" aside={<SourceBadge kind={decisionError ? "failed" : status === "UNREVIEWED" ? "not_run" : "human"} />}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={DECISION_TONE[status]} size="md" glyph>
          {decisionError ? "확인 못 함" : loading && !decision ? "불러오는 중…" : DECISION_LABEL[status]}
        </Badge>
        {decision?.decided_at && (
          <span className="text-[12px] text-cosmos-muted">
            {decision.decided_by} · {formatDateTime(decision.decided_at)}
          </span>
        )}
      </div>
      {decisionError && (
        <p role="alert" data-decision-read-error className="text-[12px] leading-5 text-cosmos-amber">
          저장된 결정을 읽지 못했습니다 — {decisionError} · 저장된 결정을 덮지 않도록 결정 단추를 잠갔습니다. 새로고침해 주세요.
        </p>
      )}
      {decision && decision.reasons.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
          {decision.reasons.map((r) => (
            <li key={r}>• {r}</li>
          ))}
        </ul>
      )}
      {ineligibleReason && (
        <p className="rounded-md border border-cosmos-red/40 bg-cosmos-red/10 px-2.5 py-1.5 text-[12px] leading-5 text-cosmos-red-text" role="note">
          {/* 사유가 마침표로 끝나면 두 번 찍혔다(「…공고입니다.. 「참여 안 함」」) · 말줄임(…)으로 끝나면 마침표를 붙이지 않는다(10-31 최종 점검 「15….」) */}
          {ineligibleReason.replace(/[.\s]+$/, "")}
          {ineligibleReason.trimEnd().endsWith("…") ? " " : ". "}「참여 안 함」이나 「보류」로 기록하세요.
        </p>
      )}
      {stale && (
        <p className="rounded-md border border-cosmos-amber/40 bg-cosmos-amber/10 px-2.5 py-1.5 text-[12px] leading-5 text-cosmos-amber" role="note">
          {staleBlockReason(stale)}
        </p>
      )}
      {gate && gateLine && (
        <p
          className={`text-[12px] leading-5 ${!gate.can_go ? "text-cosmos-red" : gateLine.open ? "text-cosmos-amber" : "text-cosmos-muted"}`}
          role={gateLine.open ? "note" : undefined}
          data-decision-gate-line
        >
          {gateLine.text}
        </p>
      )}
      {viewer ? (
        // 43차 M26 — 열람자는 결정을 저장할 수 없다(서버도 막는다) · 사유 칸 · 단추 대신 이유를 적는다
        <p className="text-[12px] leading-5 text-cosmos-muted" data-viewer-lock>{VIEWER_LOCK_LABEL} — {VIEWER_LOCK_REASON}</p>
      ) : (
      <>
      <div className="grid gap-1.5">
        {/* 로그인 이름으로 미리 채워져 placeholder 가 안 보인다 — 무슨 칸인지 보이는 이름 (DTL-34). */}
        <label className="flex items-center gap-2 text-[12px] text-cosmos-secondary">
          <span className="w-12 shrink-0">결정자</span>
          <input className={inputClass} placeholder="이름 (필수)" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </label>
        <textarea
          className={`${inputClass} min-h-14 py-1.5`}
          placeholder="사유 — 한 줄에 하나 (필수)"
          value={reasons}
          onChange={(e) => editReasons(e.target.value)}
          aria-label="결정 사유"
        />
        <input className={inputClass} placeholder="메모 (선택)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="메모" />
      </div>
      {pending && (
        <p className="text-[12px] text-cosmos-amber" role="alert">
          {DECISION_LABEL[pending]} 저장에는 결정자와 사유가 필요합니다.
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="primary" disabled={actions.gateBusy || goBlocked || Boolean(decisionError)} onClick={() => submit("GO")} title={goBlocked ? goBlockReason : `이 사업에 ${DECISION_LABELS.GO}하기로 결정한다`}>
          {DECISION_LABELS.GO}
        </Button>
        <Button size="sm" variant="secondary" disabled={actions.gateBusy || Boolean(decisionError)} onClick={() => submit("HOLD")} title={`지금은 판단을 미룬다 (${DECISION_LABELS.HOLD})`}>
          {DECISION_LABELS.HOLD}
        </Button>
        <Button size="sm" variant="secondary" disabled={actions.gateBusy || Boolean(decisionError)} onClick={() => submit("NO_GO")} className="border-cosmos-red/50 text-cosmos-red" title={`${DECISION_LABELS.NO_GO}으로 결정한다`}>
          {DECISION_LABELS.NO_GO}
        </Button>
      </div>
      </>
      )}
      <p className="text-[12px] leading-4 text-cosmos-muted">결정은 사람이 저장합니다. 시스템은 제출을 확정하지 않습니다.</p>
    </Block>
  );
}

// ---------------------------------------------------------------------------
// 조건
// ---------------------------------------------------------------------------

function formatThousand(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${Number.isInteger(value) ? value.toLocaleString("ko-KR") : value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}천원`;
}

/** 실적 조건 ↔ 회사 실적 원장 대조 결과. 판정이 아니라 힌트다 — 상태는 바꾸지 않는다. */
export function LedgerMatchBlock({ report }: { report: PerformanceMatchReport }) {
  const { criteria } = report;
  const tone: Tone = report.likely_sufficient === true ? "pass" : report.likely_sufficient === false ? "warn" : "info";
  const criteriaChips = [
    criteria.years !== null ? `최근 ${criteria.years}년` : null,
    criteria.min_count !== null ? `${criteria.min_count}건 이상` : null,
    criteria.min_amount_thousand !== null ? `${formatThousand(criteria.min_amount_thousand)} 이상${criteria.amount_mode === "cumulative" ? " (누적)" : criteria.amount_mode === "single" ? " (단일)" : ""}` : null,
    ...criteria.domains.map((d) => `분야 ${d}`),
    ...criteria.agency_types,
    criteria.similar ? "유사·동종 (사람 판단)" : null,
  ].filter((c): c is string => c !== null);
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-cosmos-border bg-cosmos-panel px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">실적 목록과 대조</span>
        <SourceBadge kind="rule" />
        {report.ledger_date && <span className="text-[12px] text-cosmos-muted">실적 목록 {report.ledger_date}</span>}
        <Badge tone={tone} glyph className="ml-auto">
          {report.likely_sufficient === true ? "충족 가능성" : report.likely_sufficient === false ? "실적 목록 기준 부족" : "판정 기준 없음"}
        </Badge>
      </div>
      {criteriaChips.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {criteriaChips.map((c) => (
            <Badge key={c} tone="info">
              {c}
            </Badge>
          ))}
        </div>
      )}
      <p className="text-[12px] leading-5 text-cosmos-secondary">{report.verdict_hint}</p>
      {report.hits.length > 0 && (
        <ul className="flex flex-col gap-1">
          {report.hits.slice(0, 5).map((h) => (
            <li key={h.seq} className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-cosmos-secondary">
              <span className="font-mono text-[12px] text-cosmos-muted">[{h.year}]</span>
              <span className="min-w-0 flex-1 text-cosmos-text">{h.title}</span>
              <span className="text-cosmos-muted">{h.agency}</span>
              <span className="font-mono tabular-nums">{formatThousand(h.amount_thousand_krw)}</span>
            </li>
          ))}
          {report.hit_count > 5 && <li className="text-[12px] text-cosmos-muted">외 {report.hit_count - 5}건</li>}
        </ul>
      )}
      {report.notes.map((n) => (
        <p key={n} className="text-[12px] leading-4 text-cosmos-muted">
          · {n}
        </p>
      ))}
      <p className="text-[12px] leading-4 text-cosmos-muted">해당 실적의 계약서·계산서·완료확인서를 대조한 뒤 담당자가 해결 처리합니다.</p>
    </div>
  );
}

function ConditionRow({
  condition,
  noticeId,
  actions,
  onSelect,
}: {
  condition: CriticalCondition;
  /** 이 조건이 속한 공고 — 메모 임시 저장 열쇠에 넣는다(2.0.6) */
  noticeId: string;
  actions: AnalysisActions;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const code = useReqCode();
  const [reviewer, setReviewer] = useState(defaultReviewer);
  /**
   * 「무엇을 확인했는지」 메모는 조건을 해결 처리한 근거다. 저장하기 전에 공고를 바꾸거나
   * 새로고침하면 말없이 사라졌다 (TASK-012). 조건별로 임시 저장하고 돌아오면 되살린다.
   */
  const organizationId = useOrganizationId();
  // 공고도 넣는다 — 자격 규칙 조건의 id 는 규칙에서 나와 공고마다 같다. 넣지 않으면 다른 공고의 같은 조건 칸에 메모가 되살아나 차단 해제 근거로 저장됐다(2.0.6).
  const noteKey = `condition-note:${organizationId}:${noticeId}:${condition.id}`;
  const [note, setNote] = useState(() => loadDraft(noteKey));
  const [noteLoadedKey, setNoteLoadedKey] = useState(noteKey);
  if (noteLoadedKey !== noteKey) {
    setNoteLoadedKey(noteKey);
    setNote(loadDraft(noteKey));
  }
  const editNote = (value: string) => {
    setNote(value);
    saveDraft(noteKey, value);
  };
  const tone = CONDITION_TONE[condition.status];
  // 참가 차단 조건은 무엇을 확인했는지 적어야 풀린다 — 참가자격 조항 확인과 같은 규칙(근거 없는 해결 금지 · DTL-11).
  // 「해결 처리」뿐 아니라 「확인 필요로」도 차단을 푼다(게이트는 BLOCKER 만 센다) — 둘 다 같은 잠금(28차).
  const blocker = condition.detected_status === "BLOCKER";
  const blockerNeedsNote = blocker && !note.trim();
  const clearReason = !reviewer.trim()
    ? "담당자 이름을 적어야 저장됩니다"
    : blockerNeedsNote
      ? "참가 차단 조건을 풀려면 무엇을 확인했는지 메모를 적어야 합니다"
      : null;

  const resolve = (status: ConditionStatus) => {
    if (!reviewer.trim()) return;
    storeReviewer(reviewer.trim());
    // 저장된 뒤에만 메모를 비우고 접는다 — 실패하면 적은 메모가 남는다 (DTL-09).
    void actions.updateCondition(condition.id, { status, reviewer: reviewer.trim(), note: note.trim() || null }).then((saved) => {
      if (!saved) return;
      clearDraft(noteKey);
      setNote("");
      setOpen(false);
    });
  };

  return (
    <li
      className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 scroll-mt-4"
      style={{ borderLeft: `2px solid ${TONE_COLORS[tone]}` }}
      data-station-item={`cond:${condition.id}`}
    >
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mc-focus flex w-full flex-col gap-1 rounded-lg px-3 py-2 text-left">
        <span className="flex items-center gap-2">
          <Badge tone={tone} glyph>
            {CONDITION_LABEL[condition.status]}
          </Badge>
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-cosmos-text">{condition.title}</span>
          {condition.requirement_id && <span className="font-mono text-[12px] text-cosmos-muted">{code(condition.requirement_id)}</span>}
        </span>
        <span className="line-clamp-2 text-[12px] leading-5 text-cosmos-secondary">{condition.content}</span>
        <span className="flex flex-wrap items-center gap-2 text-[12px] text-cosmos-muted">
          <span>{condition.source_page ? `제안요청서 ${formatPage(condition.source_page)}` : condition.source_field ? sourceFieldText(condition.source_field) : "근거 없음"}</span>
          {condition.due_at && <span>· 기한 {formatDateTime(condition.due_at)}</span>}
          {condition.status !== condition.detected_status && <span>· 규칙 판정 {CONDITION_LABEL[condition.detected_status]} → 사람이 변경</span>}
          {condition.ledger_match && (
            <span className={condition.ledger_match.likely_sufficient === true ? "text-cosmos-cyan" : condition.ledger_match.likely_sufficient === false ? "text-cosmos-amber" : ""}>
              · 실적 목록 {condition.ledger_match.hit_count}건
              {condition.ledger_match.likely_sufficient === true ? " (충족 가능성)" : condition.ledger_match.likely_sufficient === false ? " (부족)" : ""}
            </span>
          )}
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-2 border-t border-cosmos-border px-3 py-2">
          {condition.source_text && (
            <blockquote className="rounded-md border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5 text-[12px] leading-5 text-cosmos-secondary">
              “{condition.source_text}”
            </blockquote>
          )}
          {condition.resolution_note && (
            <p className="text-[12px] text-cosmos-secondary">
              {condition.resolved_by} · {condition.resolved_at ? formatDateTime(condition.resolved_at) : ""} — {condition.resolution_note}
            </p>
          )}
          {condition.ledger_match && <LedgerMatchBlock report={condition.ledger_match} />}
          {condition.requirement_id && (
            <button type="button" onClick={() => onSelect(requirementNodeId(condition.requirement_id as string))} className="mc-focus w-fit text-[12px] text-cosmos-cyan hover:underline">
              항목 보기 →
            </button>
          )}
          <div className="grid gap-1.5">
            <label className="flex items-center gap-2 text-[12px] text-cosmos-secondary">
              <span className="w-12 shrink-0">담당자</span>
              <input className={inputClass} placeholder="이름 (필수)" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </label>
            <input className={inputClass} placeholder={blocker ? "메모 — 무엇을 확인했는지 (필수)" : "메모 — 무엇을 확인했는지"} value={note} onChange={(e) => editNote(e.target.value)} aria-label="메모" />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {condition.status !== "CLEARED" ? (
              <Button
                size="sm"
                variant="primary"
                disabled={actions.gateBusy || !reviewer.trim() || blockerNeedsNote}
                aria-describedby={clearReason ? `condition-clear-reason-${condition.id}` : undefined}
                onClick={() => resolve("CLEARED")}
              >
                해결 처리
              </Button>
            ) : (
              <Button size="sm" variant="secondary" disabled={actions.gateBusy || !reviewer.trim()} onClick={() => resolve(condition.detected_status)}>
                다시 열기 ({CONDITION_LABEL[condition.detected_status]})
              </Button>
            )}
            {condition.status !== "CHECK" && condition.status !== "CLEARED" && (
              <Button
                size="sm"
                variant="ghost"
                disabled={actions.gateBusy || !reviewer.trim() || blockerNeedsNote}
                aria-describedby={clearReason ? `condition-clear-reason-${condition.id}` : undefined}
                onClick={() => resolve("CHECK")}
              >
                확인 필요로
              </Button>
            )}
            {clearReason && condition.status !== "CLEARED" && (
              <span id={`condition-clear-reason-${condition.id}`} className="text-[12px] leading-5 text-cosmos-muted">
                {clearReason}
              </span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function ConditionsBlock({ graph, actions, onSelect }: { graph: CosmosGraph; actions: AnalysisActions; onSelect: (id: string) => void }) {
  const report = graph.source.analysis.conditions;
  const [showAll, setShowAll] = useState(false);
  // 결과를 받는 동안 「아직 탐지하지 않았습니다 · 조건 찾기」를 먼저 보이지 않는다 (DTL-35).
  const loading = useAnalysisLoading();
  if (!report && loading) {
    return (
      <Block title={PANEL_TITLES.conditions}>
        <p className="text-[12.5px] leading-5 text-cosmos-muted">결과를 불러오는 중입니다…</p>
      </Block>
    );
  }
  if (!report) {
    return (
      <Block title={PANEL_TITLES.conditions} aside={<SourceBadge kind="not_run" />}>
        <p className="rounded-lg border border-dashed border-cosmos-border-strong px-3 py-2 text-[12.5px] leading-5 text-cosmos-muted">
          {graph.hasRequirements
            ? "설명회 필참·사전등록·지역제한·보증금·방문제출 같은 참가 조건을 아직 찾지 않았습니다."
            : "제안요청서를 읽은 뒤에 조건을 찾을 수 있습니다."}
        </p>
        {graph.hasRequirements && (
          <Button size="sm" variant="primary" disabled={actions.gateBusy} onClick={actions.detectConditions}>
            {actions.gateBusy ? "찾는 중…" : "조건 찾기"}
          </Button>
        )}
      </Block>
    );
  }
  const visible = showAll ? report.conditions : report.conditions.filter((c) => c.status !== "INFO");
  // 옛 저장본에는 freshness 자체가 없다 — 없는 것을 「최신」으로 읽지 않는다.
  const freshness: ConditionFreshness = report.freshness ?? "unknown";
  return (
    <Block
      title={PANEL_TITLES.conditions}
      aside={
        <span className="flex items-center gap-1">
          <SourceBadge kind="rule" />
          {report.counts.cleared > 0 && <SourceBadge kind="human" label={`해결 ${report.counts.cleared}`} />}
        </span>
      }
    >
      {/* 조건은 «감추지 않는다». 낡았다는 사실만 위에 한 줄로 적는다 —
          감추면 담당자가 참가 조건 자체를 못 보게 되어 지금보다 나빠진다. */}
      {report.stale === true && (
        <p
          role="status"
          className="rounded-md border border-cosmos-amber/40 bg-cosmos-amber/10 px-2.5 py-1.5 text-[12px] leading-5 text-cosmos-amber"
        >
          요구사항을 다시 뽑은 뒤 조건을 다시 찾지 않았습니다 — 아래 「조건 다시 찾기」를 눌러 주세요.
          {report.stale_reason ? <span className="text-cosmos-secondary"> ({report.stale_reason})</span> : null}
        </p>
      )}
      {/* 10-31 최종 점검 — 요구사항을 뽑은 적이 없으면 견줄 기준이 없다 — 「기준 확인 안 됨」 대신 아래 「아직 모름」 한 줄만 */}
      {(report.requirements_available || report.stale === true) && (
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={FRESHNESS_TONE[freshness]} glyph={freshness !== "current"}>
            {FRESHNESS_LABEL[freshness]}
          </Badge>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        <Badge tone="fail" glyph title="참가를 막는 조건 — 해결 전에는 「참여」 결정을 저장할 수 없습니다">{CONDITION_STATUS_LABELS.BLOCKER} {report.counts.blocker}</Badge>
        <Badge tone="warn">할 일 {report.counts.action}</Badge>
        <Badge tone="warn">확인 {report.counts.check}</Badge>
        <Badge tone="info">참고 {report.counts.info}</Badge>
        <Badge tone="pass">해결 {report.counts.cleared}</Badge>
      </div>
      <p className={`text-[12px] leading-5 ${report.gate.can_go ? "text-cosmos-muted" : "text-cosmos-red"}`}>{report.gate.reason}</p>
      {visible.length === 0 ? (
        <p className="text-[12px] text-cosmos-muted">
          {report.requirements_available
            ? "규칙이 찾은 조건이 없습니다. 원문에 없는 조건을 만들지 않습니다."
            : "아직 모름 — 제안요청서를 아직 읽지 않았습니다. 0건은 「없음」이 아닙니다."}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {visible.map((c) => (
            <ConditionRow key={c.id} condition={c} noticeId={graph.source.notice.id} actions={actions} onSelect={onSelect} />
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {report.counts.info > 0 && (
          <button type="button" onClick={() => setShowAll((v) => !v)} className="mc-focus text-[12px] text-cosmos-secondary hover:text-cosmos-text">
            {showAll ? "참고 조건 숨기기" : `참고 조건 ${report.counts.info}건 보기`}
          </button>
        )}
        {/*
          「언제 찾은 조건인가」 — 공고가 그 뒤로 바뀌었으면 그 사실을 함께 적는다
          (0923 §3-3 · ISSUE-093). 문구는 KPI·레일과 같은 `runStamp` 가 만든다.
        */}
        {runStamp(graph.source.analysis, "conditions").needsRerun && (
          <span className="text-[12px] text-cosmos-amber">공고가 바뀐 뒤 다시 찾지 않았습니다 — 다시 실행 필요</span>
        )}
        <button type="button" onClick={actions.detectConditions} disabled={actions.gateBusy} className="mc-focus ml-auto text-[12px] text-cosmos-secondary hover:text-cosmos-text disabled:opacity-50">
          조건 다시 찾기 · {formatDateTime(report.detected_at)}
        </button>
      </div>
    </Block>
  );
}

// ---------------------------------------------------------------------------
// 체크리스트
// ---------------------------------------------------------------------------

function ActionGroup({ base, items, codes, actions }: { base: string; items: ActionItem[]; codes: string[]; actions: AnalysisActions }) {
  const code = useReqCode();
  const done = items.filter((i) => i.status === "done" || i.status === "na").length;
  return (
    <li className="rounded-lg border border-cosmos-border bg-cosmos-elevated/40" data-action-group>
      <details>
        <summary className="mc-focus cursor-pointer list-none px-3 py-2 text-[13px] text-cosmos-text">
          <span className="font-medium">{base}</span>
          <span className="text-cosmos-muted"> — {items.length}건 · 끝냄 {done}/{items.length}{codes.length > 0 ? ` · ${codes.map(code).join(" · ")}` : ""} ▸</span>
        </summary>
        <ul className="flex flex-col gap-1.5 px-2 pb-2">
          {items.map((item) => (
            <ActionRow key={item.id} item={item} actions={actions} />
          ))}
        </ul>
      </details>
    </li>
  );
}

function ActionRow({ item, actions }: { item: ActionItem; actions: AnalysisActions }) {
  /**
   * 완료 근거는 체크박스를 누르기 «전»까지 화면에만 있다. 공고를 바꾸거나 새로고침하면
   * 말없이 사라졌다 (TASK-012). 항목별로 임시 저장하고 돌아오면 되살린다.
   * 이미 저장된 근거가 있으면 그것이 우선이다 — 임시 저장본은 아직 못 보낸 글이다.
   */
  const organizationId = useOrganizationId();
  const evidenceKey = `action-evidence:${organizationId}:${item.procurement_id}:${item.id}`;
  const [evidence, setEvidence] = useState(() => item.evidence ?? loadDraft(evidenceKey));
  const [evidenceLoadedKey, setEvidenceLoadedKey] = useState(evidenceKey);
  if (evidenceLoadedKey !== evidenceKey) {
    setEvidenceLoadedKey(evidenceKey);
    setEvidence(item.evidence ?? loadDraft(evidenceKey));
  }
  const editEvidence = (value: string) => {
    setEvidence(value);
    saveDraft(evidenceKey, value);
  };
  const done = item.status === "done";
  const na = item.status === "na";
  const code = useReqCode();
  // 제목 끝 저장 id(REQ-083)도 정리표와 같은 코드로(45차 M7)
  const shownTitle = item.title.replace(/\b(REQ-\d+)\b/g, (id) => code(id));
  // 조건에서 자동으로 올라온 항목은 지우지 않는다 (ISSUE-027).
  // 지워도 「조건 다시 찾기」를 누르면 그대로 되살아난다 — 지운 사람은 그것을 고장으로 읽는다.
  // 대신 「해당 없음」으로 둔다. 되살아나도 그 표시가 남고, 셈에서도 빠진다.
  const auto = item.origin === "auto";
  const toggle = () => {
    actions.updateAction(item.id, done ? { status: "todo" } : { status: "done", evidence: evidence.trim() || null });
    // 보냈으므로 임시 저장본을 지운다 — 남겨 두면 다음에 열 때 이미 저장한 글이 또 뜬다.
    clearDraft(evidenceKey);
  };
  const remove = async () => {
    // 45차 L5 — 화면 안 확인 창
    if (!(await requestConsent({ title: "할 일을 지울까요?", body: `「${item.title}」 — 되돌릴 수 없습니다.`, confirmLabel: "지우기", cancelLabel: "그만두기" }))) return;
    actions.deleteAction(item.id);
  };
  const markNotApplicable = async () => {
    if (na) {
      actions.updateAction(item.id, { status: "todo" });
      return;
    }
    if (!(await requestConsent({ title: "「해당 없음」으로 둘까요?", body: `「${item.title}」 — 목록에는 남고 셈에서만 빠집니다.`, confirmLabel: "해당 없음으로", cancelLabel: "그만두기" }))) return;
    actions.updateAction(item.id, { status: "na" });
  };
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2" style={{ borderLeft: `2px solid ${PRIORITY_COLOR[item.priority]}` }}>
      <div className="flex items-start gap-2">
        <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-2">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-cosmos-cyan" checked={done} onChange={toggle} disabled={actions.gateBusy || na} aria-label={`${item.title} 완료`} />
          <span className="min-w-0 flex-1">
            <span className={`block text-[13px] font-medium ${done || na ? "text-cosmos-muted line-through" : "text-cosmos-text"}`}>{shownTitle}</span>
            <span className="flex flex-wrap gap-2 text-[12px] text-cosmos-muted">
              <span>{item.priority === "urgent" ? "긴급" : item.priority === "high" ? "높음" : item.priority === "normal" ? "보통" : "낮음"}</span>
              {item.due_at && <span>· 기한 {formatDateTime(item.due_at)}</span>}
              {auto && <span>· 조건에서 자동 생성</span>}
              {na && <span>· 해당 없음</span>}
              {item.completed_at && <span>· 완료 {formatDateTime(item.completed_at)}</span>}
            </span>
          </span>
        </label>
        {auto ? (
          <button
            type="button"
            onClick={markNotApplicable}
            disabled={actions.gateBusy}
            className="mc-focus shrink-0 rounded px-1.5 py-0.5 text-[12px] text-cosmos-muted hover:text-cosmos-text disabled:opacity-50"
            title="조건에서 자동으로 올라온 항목은 지워도 다시 찾으면 되살아납니다. 대신 「해당 없음」으로 둡니다."
          >
            {na ? "되돌리기" : "해당 없음"}
          </button>
        ) : (
          <button
            type="button"
            onClick={remove}
            disabled={actions.gateBusy}
            className="mc-focus shrink-0 rounded px-1.5 py-0.5 text-[12px] text-cosmos-muted hover:text-cosmos-red disabled:opacity-50"
            aria-label={`${item.title} 삭제`}
          >
            삭제
          </button>
        )}
      </div>
      {!done && !na && (
        <input className={inputClass} placeholder="완료 근거 (예: 등록 확인 메일 9/10)" value={evidence} onChange={(e) => editEvidence(e.target.value)} aria-label="완료 근거" />
      )}
      {done && item.evidence && <p className="text-[12px] text-cosmos-secondary">근거: {item.evidence}</p>}
    </li>
  );
}

function ChecklistBlock({ graph, actions }: { graph: CosmosGraph; actions: AnalysisActions }) {
  const checklist = graph.source.analysis.checklist;
  const loading = useAnalysisLoading();
  const [title, setTitle] = useState("");
  const add = () => {
    if (!title.trim()) return;
    actions.createAction({ title: title.trim(), priority: "normal" });
    setTitle("");
  };
  return (
    <Block
      title={PANEL_TITLES.actionChecklist}
      aside={
        checklist ? (
          <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">
            {checklist.counts.done}/{checklist.counts.total}
            {checklist.counts.overdue > 0 ? ` · 기한 지남 ${checklist.counts.overdue}` : ""}
          </span>
        ) : (
          <SourceBadge kind="not_run" />
        )
      }
    >
      {!checklist && loading ? (
        <p className="text-[12px] text-cosmos-muted">결과를 불러오는 중입니다…</p>
      ) : !checklist || checklist.items.length === 0 ? (
        <p className="text-[12px] text-cosmos-muted">항목이 없습니다. 조건을 찾으면 할 일이 있는 조건이 저절로 올라오고, 아래에서 직접 추가할 수도 있습니다. 공고마다 공통으로 할 일(등록 · 인증서 · 제출)은 8단계 「BidPilot 밖에서 할 일」을 보세요.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {groupActions(checklist.items).map((group) =>
            group.items.length === 1 ? (
              <ActionRow key={group.items[0].id} item={group.items[0]} actions={actions} />
            ) : (
              <ActionGroup key={group.base} base={group.base} items={group.items} codes={group.codes} actions={actions} />
            ),
          )}
        </ul>
      )}
      <div className="flex gap-1.5">
        <input className={inputClass} placeholder="할 일 추가" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && add()} aria-label="할 일 추가" />
        <Button
          size="sm"
          variant="secondary"
          disabled={actions.gateBusy || !title.trim()}
          aria-describedby={!title.trim() ? "checklist-add-reason" : undefined}
          onClick={add}
        >
          추가
        </Button>
        {/* 회색인 이유 — 할 일 이름을 적어야 추가된다 (화면 규칙 ③) */}
        {!title.trim() && (
          <span id="checklist-add-reason" className="sr-only">
            할 일 이름을 적으면 추가할 수 있습니다
          </span>
        )}
      </div>
    </Block>
  );
}

// ---------------------------------------------------------------------------

export default function GatePanel({
  graph,
  actions,
  onSelect,
  hideDecision = false,
  hideError = false,
}: {
  graph: CosmosGraph;
  actions: AnalysisActions;
  onSelect: (id: string) => void;
  /** 쉬운 보기(24차): 결정은 화면 맨 아래 덩어리에 한 번만 — 조건 · 체크리스트 블록은 그대로 */
  hideDecision?: boolean;
  /** 쉬운 보기(26차 ISSUE-154): 오류 줄은 결정 덩어리가 한 번만 알린다 — `role=alert` 가 두 번 울렸다 */
  hideError?: boolean;
}) {
  return (
    <>
      {actions.gateError && !hideError && (
        <p role="alert" className="rounded-lg border border-cosmos-red/40 bg-cosmos-red/10 px-3 py-2 text-[12px] text-cosmos-red">
          {actions.gateError}
        </p>
      )}
      {!hideDecision && <DecisionBlock graph={graph} actions={actions} />}
      <ConditionsBlock graph={graph} actions={actions} onSelect={onSelect} />
      <ChecklistBlock graph={graph} actions={actions} />
    </>
  );
}
