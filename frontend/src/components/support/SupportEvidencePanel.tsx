"use client";

/**
 * 회사 적합 근거 · 사업계획서 뼈대 · 신청 전 점검.
 *
 * - 근거는 **승인·색인된 회사자료**에서 온 것만 보여준다. 없으면 만들지 않고 「근거 없음」으로 둔다.
 * - 사업계획서는 목차 뼈대만이며, 근거가 없는 항목(`grounded=false`)은 「확인 필요」로 명확히 표시한다.
 * - 신청 전 점검은 담당자가 직접 확인할 목록이다. 시스템이 신청을 대신 제출하지 않는다.
 * - 입찰 용어(제안서 평가항목·낙찰·투찰)를 쓰지 않는다.
 *
 * 정보량 규칙
 * - 한 번에 **한 단계**만 그린다 (`step`). 세 섹션을 동시에 펼치지 않는다.
 * - 항목당 배지는 최대 2개. 유사도·근거 id 같은 보조 값은 배지 대신 낮은 대비의 한 줄로 둔다.
 */

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { evidenceEmptyState, isLedgerMatch, isSearchOff, SUPPORT_LEDGER_LINE } from "@/components/support/evidenceEmpty";
import { SUPPORT_SECTION_SCROLL_MT, supportSectionId } from "@/components/support/SupportStepBar";
import { DownloadLink } from "@/components/ui/DownloadLink";
import { Badge, EmptyState, InlineAlert, Panel, SectionHeader } from "@/components/ui/primitives";
import { getPlanPdfStatus, getSupportPlanDraft, planDraftExportUrl } from "@/lib/api";
import { BLANK_PROOF_LABEL, blankGroups } from "@/lib/bidQuality";
import { BLIND_SUBMIT_TITLE, WITH_NAME_TITLE, variantButtonLabel, variantName } from "@/lib/bidOutline";
import { describeFailure } from "@/lib/errors";
import { formatPercent } from "@/lib/cosmos/format";
import { useCurrentUser } from "@/lib/currentUser";
import { useDeploymentMode } from "@/lib/useDeploymentMode";
import { AI_ADDED_LABEL, AI_ADDED_SENTENCES, BLANK_COUNT_NOTE, FULL_VIEW_ONLY_TAG, GENERAL_GUIDE_NOTE, GUIDE_LINK_TEXT, OWNER_FILL_ITEMS, REGISTER_COMPANY_DOCUMENTS, SCREEN_NAMES, SUBMIT_BLANK_MARKS, SYNTHETIC_COMPANY } from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import type {
  PlanBlank,
  PlanChecklist,
  PlanDraft,
  PlanDraftSection,
  PlanSentenceType,
  PlanTable,
  PlanTask,
  SupportDraftSection,
  SupportEvidenceMatch,
  SupportStepKey,
} from "@/types/opportunity";
import type { EvidenceScopeInfo } from "@/types/organization";

/** 근거 범위 배지 — 한 화면에 하나만 나오도록 가장 중요한 하나만 고른다. */
function ScopeBadge({ summary }: { summary: EvidenceScopeInfo | null }) {
  if (!summary) {
    return (
      <Badge tone="muted" glyph title="이 분석에 붙은 회사 근거 범위 정보가 없습니다">
        근거 범위 미표시
      </Badge>
    );
  }
  if (summary.real_evidence_used) {
    return (
      <Badge tone="ok" glyph title="담당자가 승인해 색인한 이 회사의 내부 자료">
        내부 승인자료 {summary.used_document_count}문서 · {summary.used_chunk_count}문단
      </Badge>
    );
  }
  if (summary.synthetic_evidence_used) {
    return (
      <Badge tone="demo" glyph title="공개 데모용 가상 예시 회사자료 — 실제 회사자료가 아닙니다">
        {SYNTHETIC_COMPANY}
      </Badge>
    );
  }
  // 자료는 있는데 검색을 하지 않았거나 실패했으면 「없음」이라고 하지 않는다 (27차 SUP-01).
  const empty = evidenceEmptyState(summary.note, summary.ai_search_off);
  if (!empty.showRegister) {
    return (
      <Badge tone="muted" glyph title="승인한 회사자료는 있지만 이번 분석에서 근거를 찾아 보지 못했습니다">
        {empty.badge}
      </Badge>
    );
  }
  return (
    <Badge tone="warn" glyph title="이 회사의 승인·색인된 근거가 매칭되지 않았습니다">
      연결된 근거 없음
    </Badge>
  );
}

function MatchCard({ match }: { match: SupportEvidenceMatch }) {
  // 45차 H5 — 실적 원장 후보는 규칙으로 맞춘 것이라 쪽 · 유사도가 없다(「쪽 모름 · 유사도 0%」로 보였다)
  const ledger = isLedgerMatch(match);
  return (
    <article className="rounded-lg border border-cosmos-border bg-cosmos-elevated/40 p-3">
      <header className="flex min-w-0 flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <p className="min-w-0 break-words text-[12.5px] font-semibold leading-5 text-cosmos-text">
          {match.document_name}
          <span className="ml-1.5 font-mono text-[12px] font-normal text-cosmos-muted">
            {ledger ? "실적 원장" : match.page === null ? "쪽 모름" : `${match.page}쪽`}
          </span>
        </p>
        <span className="flex shrink-0 items-center gap-1.5">
          {/* 채택은 유사도 기준으로 저절로 정해진다 — 이 화면에는 채택 단추가 없다 (27차 SUP-14).
              원장 후보는 참고만 — 사업계획서 초안은 원장에서 실적을 따로 고른다(외부 점검 P1-03 · 「미채택」이라 쓰면 채택할 길이 있는 듯 읽힌다). */}
          <Badge
            tone={match.selected ? "pass" : "muted"}
            glyph
            title={
              ledger
                ? "실적 원장에서 분야 낱말로 맞춘 참고 후보 — 이 화면에서는 고르지 않습니다(사업계획서 초안은 원장에서 실적을 따로 골라 「수행 실적 후보」 같은 줄로 적습니다)"
                : match.selected
                  ? "유사도가 기준을 넘어 자동으로 채택한 근거 — 담당자 확인 전"
                  : "후보 근거 — 유사도가 채택 기준에 못 미침"
            }
          >
            {ledger ? "원장 참고 후보" : match.selected ? "자동 채택" : "후보"}
          </Badge>
          {match.synthetic && (
            <Badge tone="demo" glyph title="공개 데모용 가상 예시 회사자료">
              가상 예시
            </Badge>
          )}
        </span>
      </header>
      <p className="mt-2 whitespace-pre-line break-words text-[12.5px] leading-5 text-cosmos-secondary">{match.source_text}</p>
      {/* 근거 id 는 담당자가 읽을 말이 아니다 — 마우스를 올리면 보인다 (27차 SUP-15). */}
      {match.similarity_score !== null && !ledger && (
        <p className="mt-1.5 min-w-0 font-mono text-[12px] leading-4 text-cosmos-muted" title={`근거 id ${match.evidence_id}`}>
          <span title="검색 유사도 — 적합 여부 판정이 아닙니다">유사도 {formatPercent(match.similarity_score)}</span>
        </p>
      )}
    </article>
  );
}

function EvidenceSection({
  matches,
  summary,
  organizationLabel,
  markFullScreenLinks = false,
}: {
  matches: SupportEvidenceMatch[];
  summary: EvidenceScopeInfo | null;
  organizationLabel: string;
  markFullScreenLinks?: boolean;
}) {
  // 어떤 신청 조건에 붙은 근거인지 조건별로 묶는다 (조건 문구는 backend 가 준 값 그대로).
  const grouped = new Map<string, SupportEvidenceMatch[]>();
  for (const match of matches) {
    const bucket = grouped.get(match.condition);
    if (bucket) bucket.push(match);
    else grouped.set(match.condition, [match]);
  }
  const headingId = `${supportSectionId("evidence")}-title`;
  const empty = evidenceEmptyState(summary?.note, summary?.ai_search_off);
  // 외부 점검 P1-03 — AI 검색을 꺼 두었을 때 백엔드 사유 글은 입찰 정리표용(「쓸 것을 골라 채택하세요」)이라 이 화면에서는 바꿔 적는다
  const searchOff = isSearchOff(summary?.note, summary?.ai_search_off);
  const note = searchOff ? (matches.length > 0 ? SUPPORT_LEDGER_LINE : null) : summary?.note;
  // 10-31 최종 점검 — AI 검색을 꺼 두면 아래는 원장 참고 후보인데 머리는 「승인·색인된 회사자료에서 …」라 서로 어긋났다
  const description = searchOff
    ? `${organizationLabel}의 실적 원장에서 분야 낱말로 맞춘 참고 후보를 보여 줍니다. 근거가 없으면 문장을 만들지 않습니다.`
    : `${organizationLabel}의 승인·색인된 회사자료에서 신청 조건과 연결된 문단만 보여줍니다. 근거가 없으면 문장을 만들지 않습니다.`;

  return (
    <div id={supportSectionId("evidence")} className={`min-w-0 ${SUPPORT_SECTION_SCROLL_MT}`}>
      <Panel ariaLabelledBy={headingId}>
        <SectionHeader
          id={headingId}
          eyebrow="신청 분석"
          title="회사 적합 근거"
          description={description}
          aside={<ScopeBadge summary={summary} />}
        />
        {/* 제목이 이미 사유를 말하면(검색 안 함) 한 번 더 적지 않는다 — 원문 사유는 title 에 (27차 SUP-01). */}
        {note && (matches.length > 0 || empty.showNote) && (
          <p className="mt-2 text-[12px] leading-5 text-cosmos-muted">{note}</p>
        )}

        {matches.length === 0 ? (
          <div className="mt-3" title={empty.showNote ? undefined : (note ?? undefined)} data-evidence-empty={empty.showRegister ? "none" : "skipped"}>
            <EmptyState
              title={empty.title}
              tone={empty.showRegister ? "warn" : "info"}
              action={
                empty.showRegister ? (
                  <Link
                    href="/company"
                    className="mc-focus inline-flex min-h-9 items-center justify-center rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 py-1.5 text-[13px] font-semibold text-cosmos-text transition-colors hover:border-cosmos-cyan/60"
                  >
                    {REGISTER_COMPANY_DOCUMENTS}{markFullScreenLinks && ` ${FULL_VIEW_ONLY_TAG}`} →
                  </Link>
                ) : undefined
              }
            >
              {empty.body}
            </EmptyState>
          </div>
        ) : (
          <ul className="mt-3 flex flex-col gap-4">
            {[...grouped.entries()].map(([condition, group]) => (
              <li key={condition} className="min-w-0">
                <p className="text-[13px] font-semibold text-cosmos-text">
                  {condition}
                  <span className="ml-2 text-[12px] font-normal text-cosmos-muted">근거 {group.length}건</span>
                </p>
                <div className="mt-2 flex flex-col gap-2">
                  {group.map((match) => (
                    <MatchCard key={`${condition}:${match.evidence_id}`} match={match} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/** 문장 유형 → 화면 말. 저장 값은 입찰과 같은 enum 이고 **여기서만** 지원사업 말로 읽는다. */
const SENTENCE_TONE: Record<PlanSentenceType, { label: string; tone: "pass" | "info" | "warn" }> = {
  RFP_GROUNDED: { label: "공고문 근거", tone: "pass" },
  COMPANY_EVIDENCE_GROUNDED: { label: "회사 근거", tone: "info" },
  AI_SUGGESTION: { label: AI_ADDED_LABEL, tone: "warn" },
};

/**
 * 유형이 없는 문장 = **빈칸 표시** (ISSUE-119 · prompt_03 §4-D-1).
 *
 * 「확인 필요 — 승인·색인된 회사자료에서 연결된 근거가 없습니다」에 「공고문 근거」
 * 배지가 달려 있었다. 근거가 없다는 말에 근거 배지가 붙은 자리다. 입찰 6단계의
 * 「확인 필요」 표시와 같은 말·같은 색을 쓴다.
 */
const NOTE_TONE = { label: "확인 필요", tone: "warn" } as const;

function sentenceBadge(type: PlanSentenceType | null) {
  return type ? SENTENCE_TONE[type] : NOTE_TONE;
}

/** 「(9월 18일 만듦)」. 저장된 시각을 화면 말로 — 「9-18」은 날짜로 바로 읽히지 않았다(31차 §3-D). */
export function runLabel(executedAt: string | undefined): string {
  if (!executedAt) return "";
  const at = new Date(executedAt);
  if (Number.isNaN(at.getTime())) return "";
  return ` (${at.getMonth() + 1}월 ${at.getDate()}일 만듦)`;
}

/** 「(담당자 입력)」 · 「(담당자 선택)」 — 사람이 채울 빈칸 (백엔드 plan_form_service 와 같은 말). */
const HUMAN_INPUT = "(담당자 입력)";

function krw(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toLocaleString("ko-KR")}원`;
}

/**
 * 과제 고르기 (25차 §4-B-5). 회사 낱말이 겹치는 과제가 위에 온다(규칙) — **고르는 것은 사람이다.**
 * 쉬운 보기 지원사업 초안 덩어리도 이 목록을 그대로 쓴다.
 */
export function PlanTaskPicker({
  tasks,
  selectedNo,
  busy,
  onPick,
}: {
  tasks: PlanTask[];
  selectedNo: number | null;
  busy: boolean;
  onPick: (no: number) => void;
}) {
  return (
    <ol className="flex max-h-72 flex-col gap-1 overflow-y-auto pr-1" aria-label="협업 과제 목록">
      {tasks.map((task) => (
        <li key={task.no}>
          <button
            type="button"
            disabled={busy}
            aria-pressed={selectedNo === task.no}
            onClick={() => onPick(task.no)}
            className={`mc-focus flex w-full flex-wrap items-baseline gap-x-2 rounded-md border px-2.5 py-1.5 text-left text-[12.5px] leading-5 transition-colors disabled:opacity-50 ${
              selectedNo === task.no ? "border-cosmos-cyan/70 bg-cosmos-elevated/60 text-cosmos-text" : "border-cosmos-border text-cosmos-secondary hover:border-cosmos-border-strong"
            }`}
          >
            <span className="font-mono tabular-nums text-cosmos-muted">{task.no}.</span>
            <span className="text-cosmos-muted">{task.agency ?? "기관 미상"}</span>
            <span className="min-w-0 flex-1 break-keep text-cosmos-text">{task.title}</span>
            {task.match_words && task.match_words.length > 0 && (
              <span className="text-[12px] text-cosmos-muted">겹침: {task.match_words.join(" · ")}</span>
            )}
          </button>
          {/* 과제소개서의 「기준요건 및 요구사항」 그대로 — 고르기 돕기(점수 · 판정 없음 · 30차 §3-A) */}
          {task.annex_requirements && task.annex_requirements.length > 0 && (
            <details className="ml-7 mt-0.5" data-task-requirements={task.no}>
              <summary className="mc-focus w-fit cursor-pointer rounded text-[12px] text-cosmos-secondary">과제소개서 기준요건 {task.annex_requirements.length}줄 ▸</summary>
              <ul className="mt-0.5 flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
                {task.annex_requirements.map((line, index) => (
                  <li key={index}>▪ {line}</li>
                ))}
              </ul>
            </details>
          )}
        </li>
      ))}
    </ol>
  );
}

type PlanVariant = "submit" | "review" | "blind";
/** 평가본(11-06) — 제출용과 같은 글에서 회사 이름 · 대표자 · 연락처 · 설립일 · 연혁을 뺀 판(공고가 평가용 문서에 회사 표기를 막을 때만 보인다 · 2.10.0 D5). */
const BLIND_TITLE = "평가본 — 제출용과 같고 회사 이름 · 대표자 · 연락처 · 설립일 · 연혁을 뺀 판(회사 이름 자리는 「당사」)";

/** 「DOCX 내려받기」 (25차 §4-E) — 양식 순서 그대로. 사업계획서 HWPX 는 28차 담당자 결정으로 없앴다(한컴 열림 미검증 · 품질).
 *  입찰 제안서는 HWPX 도(11-03 대표 · 한글 2024 로 열어 확인 · `hwpx`). */
export function PlanDownloadLinks({
  programId,
  organizationId,
  large = false,
  variants = ["submit", "review"],
  blanks,
  urlFor,
  fileStem = "사업계획서",
  hwpx = false,
  submitLabel = "제출용",
  submitTitle,
  onHwpxDone,
  blindOnly = false,
}: {
  programId: string;
  organizationId?: string;
  large?: boolean;
  /** 제출용 문서에 남는 빈칸 수 — 있으면 단추 옆에 「제출 전 채울 칸 n개」(30차 §3-B). */
  blanks?: number | null;
  /** 보일 판 — 쉬운 보기는 제출용만(컨트롤 상한 12 · 검토용은 사업계획서 작성 페이지에서 · 29차 §3-D). 평가본은 `urlFor` 와 함께만(11-06). */
  variants?: readonly PlanVariant[];
  /** 내려받기 주소 — 입찰 제안서(11-03)는 `bidPlanExportUrl`. 없으면 사업계획서 주소. */
  urlFor?: (format: "docx" | "pdf" | "hwpx", variant: PlanVariant) => string;
  /** 받는 파일 이름 머리(서버가 이름을 못 줄 때) — 「사업계획서」 · 「제안서」 */
  fileStem?: string;
  /** 한글(HWPX) 단추도 — 입찰 제안서만(`urlFor` 와 함께). */
  hwpx?: boolean;
  /** (2.7.0) 제출용 판의 이름 표시 — 입찰 품질 게이트 `file_label`. 「초안」이면 단추 옆 · 받는 파일 이름이 「초안」. */
  submitLabel?: "초안" | "제출용";
  /** 「초안」일 때 단추 설명(까닭) */
  submitTitle?: string;
  /** (2.8.0) 한글 파일을 받은 뒤 — 입찰 제안서는 서버가 만든 파일을 다시 읽어 검사하므로 품질 패널을 새로 읽는다 */
  onHwpxDone?: () => void;
  /** (2.10.0 D8) 원문이 평가본만 받는 공고 — 평가본이 제출할 판(「제출용」 · 「초안」) · 제출용 판은 「회사명 포함본」 */
  blindOnly?: boolean;
}) {
  const href = (format: "docx" | "pdf", variant: PlanVariant) =>
    urlFor ? urlFor(format, variant) : planDraftExportUrl(programId, organizationId, { format, variant: variant === "review" ? "review" : "submit" });
  const draftName = submitLabel === "초안";
  const submission: PlanVariant = blindOnly ? "blind" : "submit"; // 제출할 판 — 「초안」 까닭 · 이름 표시가 이 판에 붙는다
  const nameOf = (variant: PlanVariant) => variantName(variant, submitLabel, blindOnly);
  const titleOf = (variant: PlanVariant, normal: string) => {
    if (variant === submission && draftName && submitTitle) return submitTitle;
    if (blindOnly && variant !== "review") return variant === "blind" ? BLIND_SUBMIT_TITLE : WITH_NAME_TITLE;
    return normal;
  };
  const [pdf, setPdf] = useState<{ available: boolean; reason: string | null } | null>(null);
  useEffect(() => {
    let alive = true;
    getPlanPdfStatus()
      .then((value) => alive && setPdf(value))
      .catch(() => alive && setPdf(null)); // 못 읽으면 단추를 두고 누를 때 서버 사유를 보인다
    return () => {
      alive = false;
    };
  }, []);
  const linkClass = large
    ? "mc-focus inline-flex min-h-10 items-center rounded-lg border border-cosmos-border-strong px-4 text-[15px] font-medium text-cosmos-text hover:border-cosmos-text/60"
    : "mc-focus inline-flex min-h-8 items-center rounded-lg border border-cosmos-border-strong px-2.5 text-[12px] font-medium text-cosmos-text hover:border-cosmos-cyan/60";
  return (
    <span className="flex flex-wrap items-center gap-2" data-plan-downloads>
      {/* 제안서 내려받기와 같은 DownloadLink — 서버가 실패하면 새 탭 · 앱 밖 오류 글 대신 이 자리에 한국어 사유를 적는다 (EZ-29).
          29차 §3-D — 제출용(표식 · 검토 메모 없음) · 검토용(문장 유형 · AI 회색 · 근거 · 검토 메모) × DOCX · PDF. 36차 §3-F — 문서 모양(SPEC). */}
      {variants.filter((variant) => variant !== "blind" || urlFor).map((variant) => (
        <span key={variant} className="flex flex-wrap items-center gap-1.5" data-plan-download-variant={variant}>
          <span
            className={large ? "text-[14px] text-cosmos-secondary" : "text-[12px] text-cosmos-muted"}
            title={variant === submission && draftName ? submitTitle : undefined}
            data-plan-submit-label={variant === submission ? submitLabel : undefined}
          >
            {variantButtonLabel(variant, submitLabel, blindOnly)}
          </span>
          <DownloadLink
            href={href("docx", variant)}
            fallbackName={`${fileStem}_${nameOf(variant)}.docx`}
            className={linkClass}
            title={titleOf(variant, variant === "blind" ? BLIND_TITLE : variant === "submit" ? "제출용 워드 문서 — 표식 없는 판 · 공고 첨부 양식에 옮겨 내세요 · 빈칸은 점선 밑줄" : `검토용 워드 문서 — 문장 유형 · ${AI_ADDED_LABEL}은 회색 글자와 왼쪽 줄 · 근거 · 검토 메모`)}
          >
            DOCX
          </DownloadLink>
          {hwpx && urlFor && (
            <DownloadLink
              href={urlFor("hwpx", variant)}
              fallbackName={`${fileStem}_${nameOf(variant)}.hwpx`}
              className={linkClass}
              onDone={onHwpxDone}
              title={titleOf(variant, variant === "blind" ? BLIND_TITLE : variant === "submit" ? "제출용 한글 문서(HWPX) — 한글에서 열어 고쳐 쓰기 · 빈칸은 점선 밑줄" : "검토용 한글 문서(HWPX) — 근거 · 검토 메모")}
            >
              HWPX
            </DownloadLink>
          )}
          {pdf?.available === false ? (
            <span className={`${linkClass} cursor-not-allowed opacity-60`} aria-disabled="true" title={pdf.reason ?? undefined}>
              PDF — {pdf.reason ?? "만들 수 없음"}
            </span>
          ) : (
            <DownloadLink
              href={href("pdf", variant)}
              fallbackName={`${fileStem}_${nameOf(variant)}.pdf`}
              className={linkClass}
              title={titleOf(variant, variant === "blind" ? BLIND_TITLE : variant === "submit" ? "제출용 PDF — 워드 없이도 만든다(Edge · Chrome)" : "검토용 PDF")}
            >
              PDF
            </DownloadLink>
          )}
        </span>
      ))}
      {typeof blanks === "number" && blanks > 0 && (
        <span className={large ? "text-[14px] text-cosmos-amber" : "text-[12px] text-cosmos-amber"} data-submit-blanks title={BLANK_COUNT_NOTE}>
          {SUBMIT_BLANK_MARKS} {blanks}곳
          <span className="block text-[12px] text-cosmos-muted">{BLANK_COUNT_NOTE}</span>
        </span>
      )}
    </span>
  );
}

/** 완성도 점검표 (25차 §4-D) — 선정 가능성이 아니라 「제출 전에 무엇이 비었는가」다. */
export function PlanChecklistTable({ checklist }: { checklist: PlanChecklist }) {
  if (checklist.legacy || !checklist.form) {
    return <p className="text-[12.5px] leading-5 text-cosmos-muted">{checklist.summary}</p>;
  }
  const { form, evaluation, grounding, copy, numbers, length, blanks, kind } = checklist;
  // 복사 · 근거 불일치 · 예시 값 검사는 **AI 문장만** 본다 — 규칙 초안이면 돈 적이 없는데 「0% · 0」이 초록으로 보였다 (27차 SUP-04).
  const noAi = copy !== undefined && copy.ai_total === 0;
  const rows: { label: string; value: ReactNode; tone?: "pass" | "warn" }[] = [
    {
      label: "양식 칸 채움",
      value: (
        <>
          양식 칸 {form.items_total}개 중 {form.items_filled}개 채움 · 표 {form.tables_total}개 중 {form.tables_present}개 있음(내용까지 채운 표 {form.tables_filled}개)
          {form.empty_items.length > 0 && <span className="block text-cosmos-muted">비어 있는 항목: {form.empty_items.join(" · ")}</span>}
        </>
      ),
      tone: form.items_filled === form.items_total ? "pass" : "warn",
    },
    evaluation && {
      label: "심사 항목 반영",
      value: (
        <>
          {evaluation.covered}/{evaluation.total}
          {evaluation.items.map((item) => (
            <span key={item.name} className="block text-cosmos-muted">
              {item.name} → {item.sections.length ? item.sections.join(" · ") : "다룬 곳 없음"}
            </span>
          ))}
          {evaluation.bonus.map((bonus) => (
            <span key={bonus.name} className="block text-cosmos-muted">
              {bonus.name}: {bonus.basis}
            </span>
          ))}
        </>
      ),
      tone: evaluation.covered === evaluation.total ? "pass" : "warn",
    },
    grounding && {
      label: "근거 있는 문장",
      value: (
        <>
          회사 근거 {grounding.company}
          {grounding.company_sources !== undefined && grounding.company_sources < grounding.company ? `(서로 다른 근거 ${grounding.company_sources})` : ""} · 공고 근거{" "}
          {grounding.notice} · <span className="text-cosmos-amber">{AI_ADDED_SENTENCES} {grounding.suggestion}개(확인 필요)</span>
        </>
      ),
    },
    copy && {
      label: "공고 문장 복사",
      value: noAi ? (
        <span className="text-cosmos-muted">AI 문장 없음 — 검사 대상 없음</span>
      ) : (
        <>
          {copy.percent}% ({copy.count}/{copy.ai_total})
          {copy.sentences.slice(0, 3).map((s) => (
            <span key={s} className="block text-cosmos-muted">「{s.slice(0, 60)}」</span>
          ))}
        </>
      ),
      tone: noAi ? undefined : copy.tone,
    },
    numbers && noAi && !numbers.budget && {
      label: "숫자 검증",
      value: (
        <>
          <span className="text-cosmos-muted">AI 문장 없음 — 근거 불일치 · 예시 값 검사 대상 없음</span>
          {` · 일정 범위 밖 ${numbers.schedule_out}`}
        </>
      ),
      tone: numbers.schedule_out ? "warn" : undefined,
    },
    numbers && !(noAi && !numbers.budget) && {
      label: "숫자 검증",
      value: (
        <>
          근거 불일치 {numbers.mismatches} · 일정 범위 밖 {numbers.schedule_out} · 남은 양식 예시 값 {numbers.examples_left}
          {numbers.budget && (
            <span className="block text-cosmos-muted">
              사업비 합계 {krw(numbers.budget.total_krw)} / 상한 {krw(numbers.budget.cap_krw)}
              {numbers.budget.over_cap ? " — 상한 초과" : ""}
              {numbers.budget.items_outside.length > 0 ? ` · 허용 밖 비목 ${numbers.budget.items_outside.join(", ")}` : ""}
              {numbers.budget.total_mismatch ? " · 합계 줄이 항목 합과 다름" : ""}
              {numbers.budget.blank_rows ? ` · 금액 미입력 ${numbers.budget.blank_rows}행(상한 검사 전)` : ""}
            </span>
          )}
        </>
      ),
      tone:
        numbers.mismatches + numbers.schedule_out + numbers.examples_left === 0 && !numbers.budget?.over_cap && !numbers.budget?.items_outside.length && !numbers.budget?.total_mismatch && !numbers.budget?.blank_rows
          ? "pass"
          : "warn",
    },
    length && {
      label: "분량",
      value:
        (length.recommended
          ? `본문 ${length.chars.toLocaleString("ko-KR")}자 / 양식 권장 ${length.recommended.toLocaleString("ko-KR")}자 (${length.percent}%)`
          : `본문 ${length.chars.toLocaleString("ko-KR")}자 (양식 권장 분량 없음)`) +
        (length.sentence_avg ? ` · 문장 평균 ${length.sentence_avg}자 · 가장 긴 문장 ${length.sentence_max}자 · 가운뎃점(·) ${length.dots ?? 0}개` : ""),
      tone: length.tone ?? undefined,
    },
    checklist.company_fill && {
      label: "회사자료 자동 채움",
      value: `회사자료로 채움 ${checklist.company_fill.filled}칸${checklist.company_fill.filled_fields.length ? ` (${[...new Set(checklist.company_fill.filled_fields)].slice(0, 6).join(" · ")}${checklist.company_fill.filled_table_cells ? " · 표" : ""})` : ""}${checklist.company_fill.fillable ? ` · 회사자료에 입력하면 채워질 칸 ${checklist.company_fill.fillable}개 — ${checklist.company_fill.fillable_fields.slice(0, 6).join(" · ")}` : ""}`,
      tone: checklist.company_fill.fillable ? "warn" : "pass",
    },
    blanks && {
      label: "담당자가 채울 칸",
      value: blanks.count ? `${OWNER_FILL_ITEMS} ${blanks.count}개 — ${blanks.fields.slice(0, 8).join(" · ")}${blanks.fields.length > 8 ? " …" : ""} (항목 수 · 파일 속 빈칸 표시는 곳 수라 다를 수 있음)` : "없음",
      tone: blanks.count ? "warn" : "pass",
    },
    kind && {
      label: "초안 종류",
      value: `${kind.label}${kind.failed_sections ? ` · AI 작성 실패 절 ${kind.failed_sections}개` : ""}`,
    },
  ].filter(Boolean) as { label: string; value: ReactNode; tone?: "pass" | "warn" }[];
  return (
    <dl className="grid gap-x-4 gap-y-1.5 text-[12.5px] leading-5 sm:grid-cols-[minmax(110px,150px)_minmax(0,1fr)]" data-plan-checklist>
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="font-semibold text-cosmos-text">{row.label}</dt>
          <dd className={`min-w-0 break-words ${row.tone === "warn" ? "text-cosmos-amber" : row.tone === "pass" ? "text-cosmos-cyan" : "text-cosmos-secondary"}`}>
            {row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function PlanTableView({ table }: { table: PlanTable }) {
  return (
    <div className="mt-2 overflow-x-auto" data-plan-table={table.key}>
      <table className="w-full min-w-[420px] border-collapse text-[12px] leading-5">
        <caption className="pb-1 text-left text-[12px] font-semibold text-cosmos-secondary">
          &lt; {table.title} &gt;{table.filled_by ? ` — 일부 칸은 ${table.filled_by}로 채움` : table.human_only ? " — 담당자가 채우는 표" : ""}
        </caption>
        <thead>
          <tr>
            {table.columns.map((column) => (
              <th key={column} scope="col" className="border border-cosmos-border px-2 py-1 text-left font-semibold text-cosmos-text">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, c) => (
                <td key={c} className={`border border-cosmos-border px-2 py-1 ${cell === HUMAN_INPUT ? "text-cosmos-muted" : "text-cosmos-secondary"}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanSectionView({ section, tables }: { section: PlanDraftSection; tables: Map<string, PlanTable> }) {
  return (
    <li className="min-w-0" data-plan-section={section.key ?? section.section}>
      <p className="text-[12.5px] font-semibold leading-5 text-cosmos-text">
        {section.section}
        {section.optional ? <span className="font-normal text-cosmos-muted"> (선택)</span> : null}
        {section.eval_targets && section.eval_targets.length > 0 && (
          <span className="ml-2 font-normal text-cosmos-muted">평가: {section.eval_targets.join(" · ")}</span>
        )}
      </p>
      {section.llm_error && (
        <p className="mt-1 text-[12px] leading-5 text-cosmos-amber">이 절은 AI 작성 실패 — {section.llm_error}</p>
      )}
      {section.fields && section.fields.length > 0 ? (
        <dl className="mt-1 grid gap-x-3 gap-y-0.5 text-[12.5px] leading-5 sm:grid-cols-[minmax(120px,170px)_minmax(0,1fr)]">
          {section.fields.map((field) => (
            <div key={field.label} className="contents">
              <dt className="text-cosmos-muted">{field.label}</dt>
              <dd className={`min-w-0 break-words ${field.value === HUMAN_INPUT || field.value.startsWith("(담당자") ? "text-cosmos-muted" : "text-cosmos-secondary"}`}>
                {field.value}
                {field.filled_by === "company" && <span className="ml-1.5 text-[11.5px] text-cosmos-muted">· 회사자료</span>}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <ul className="mt-1 flex flex-col gap-1.5">
          {section.sentences.map((sentence, index) => (
            <li key={`${section.key ?? section.section}-${index}`} className="flex min-w-0 flex-wrap items-start gap-2">
              <Badge tone={sentenceBadge(sentence.type).tone}>{sentenceBadge(sentence.type).label}</Badge>
              <span className="min-w-0 flex-1 break-words text-[12.5px] leading-5 text-cosmos-secondary">
                {sentence.text}
                {sentence.flags && sentence.flags.length > 0 && (
                  <span className="block text-[12px] text-cosmos-amber">{sentence.flags.join(" · ")}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {(section.tables ?? []).map((key) => {
        const table = tables.get(key);
        return table ? <PlanTableView key={key} table={table} /> : null;
      })}
    </li>
  );
}

/** 「담당자가 채울 항목 n개 ▸」 — 사업계획서 · 입찰 제안서(2.7.0) 초안이 같이 쓴다. 비어 있으면 그리지 않는다. */
export function PlanBlanksList({ blanks, annexFetchable = false, grouped = false }: { blanks: readonly PlanBlank[]; annexFetchable?: boolean; grouped?: boolean }) {
  if (blanks.length === 0) return null;
  // 입찰 제안서(2.9.0 · 3차 지시서 §9) — 붙일 서류 · 확인할 원문 값 · 회사가 정할 값 · 본문에서 뺀 문장으로 묶는다(사업계획서는 한 목록 그대로)
  const groups = grouped ? blankGroups(blanks) : [{ key: "all", label: "", items: [...blanks] }];
  return (
    <details className="border-t border-cosmos-border pt-2" data-plan-blanks>
      <summary className="mc-focus w-fit cursor-pointer rounded py-1 text-[12.5px] text-cosmos-secondary">
        {/* 45차 M6 — 같은 항목이 여러 절에 있어도 하나(점검표 「담당자가 채울 칸」 · /plan 과 같은 수) */}
        {OWNER_FILL_ITEMS} {new Set(blanks.map((blank) => blank.field)).size}개 ▸
      </summary>
      {groups.map((group) => (
      <div key={group.key} data-plan-blank-group={group.key}>
      {group.label && <p className="mt-1.5 text-[12px] font-semibold text-cosmos-text">{group.label} · {group.items.length}건</p>}
      <ul className="mt-1 flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
        {group.items.map((blank, index) => (
          <li key={`${blank.field}-${index}`}>
            {blank.section ? `${blank.section} · ` : ""}
            {blank.field} — <span className="text-cosmos-muted">{blank.why}</span>
            {blank.proof && <span className="text-cosmos-muted"> · {BLANK_PROOF_LABEL}: {blank.proof}</span>}
            {blank.field === "과제소개서" && annexFetchable && (
              <a href="#plan-annex" className="mc-focus ml-1.5 rounded text-cosmos-cyan hover:underline">
                「과제소개서 받기」로 →
              </a>
            )}
          </li>
        ))}
      </ul>
      </div>
      ))}
    </details>
  );
}

/**
 * 사업계획서 초안 본문 — 점검표 · 양식 순서 절 · 빈칸 · 검토 약점 (28차 §3-D 에서 떼어 냄).
 * 사업계획서 작성 페이지(/plan)가 그린다. 지원사업 화면은 요약 한 줄만 두고 이 페이지로 보낸다.
 */
export function PlanDraftBody({ draft, annexFetchable = false }: { draft: PlanDraft; annexFetchable?: boolean }) {
  const tables = new Map((draft.tables ?? []).map((table) => [table.key, table]));
  // 대항목 머리로 묶는다 — 양식 순서 그대로.
  const groups: { major: string; sections: PlanDraftSection[] }[] = [];
  for (const section of draft.sections) {
    const major = section.major_title ?? "";
    if (!groups.length || groups[groups.length - 1].major !== major) groups.push({ major, sections: [] });
    groups[groups.length - 1].sections.push(section);
  }
  return (
    <div className="flex min-w-0 flex-col gap-3" data-plan-body>
      {draft.checklist && (
        <div className="border-t border-cosmos-border pt-3">
          <p className="mb-2 text-[12.5px] font-semibold text-cosmos-text">완성도 점검표 · {draft.checklist.summary}</p>
          <PlanChecklistTable checklist={draft.checklist} />
        </div>
      )}
      {draft.llm_note && <p className="text-[12px] leading-5 text-cosmos-muted">{draft.llm_note}</p>}
      {draft.sections.length > 0 && (
        <div className="flex flex-col gap-4 border-t border-cosmos-border pt-3">
          {groups.map((group, g) => (
            <section key={`${group.major}-${g}`} aria-label={group.major || "초안"}>
              {group.major && <h4 className="mb-1.5 text-[13px] font-semibold text-cosmos-text">□ {group.major}</h4>}
              <ol className="flex flex-col gap-3">
                {group.sections.map((section) => (
                  <PlanSectionView key={section.key ?? section.section} section={section} tables={tables} />
                ))}
              </ol>
            </section>
          ))}
        </div>
      )}
      {draft.blanks && <PlanBlanksList blanks={draft.blanks} annexFetchable={annexFetchable} />}
      {draft.review_scores && draft.review_scores.length > 0 && (
        <details className="border-t border-cosmos-border pt-2" data-plan-review-scores>
          <summary className="mc-focus w-fit cursor-pointer rounded py-1 text-[12.5px] text-cosmos-secondary">
            AI 모의 채점(실제 심사 아님 · 제출 파일엔 없음) — {draft.review_scores.map((s) => `${s.eval_item} ${s.grade}`).join(" · ")} ▸
          </summary>
          <ul className="mt-1 flex flex-col gap-1.5 text-[12px] leading-5 text-cosmos-secondary">
            {draft.review_scores.map((score) => (
              <li key={score.eval_item}>
                <span className="font-semibold text-cosmos-text">
                  {score.eval_item} · {score.grade}
                </span>
                {score.sections.length > 0 && <span className="text-cosmos-muted"> ({score.sections.join(" · ")})</span>} — {score.reason}
                {score.rewritten && <span className="text-cosmos-cyan"> · 「하」라서 한 번 고쳐 썼습니다</span>}
                {score.fixes.length > 0 && (
                  <ul className="mt-0.5 flex flex-col gap-0.5 pl-3">
                    {score.fixes.map((fix, index) => (
                      <li key={index} className="text-cosmos-muted">
                        「{fix.sentence}」 → {fix.fix}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {draft.review_notes && draft.review_notes.length > 0 && (
        <details className="border-t border-cosmos-border pt-2">
          <summary className="mc-focus w-fit cursor-pointer rounded py-1 text-[12.5px] text-cosmos-secondary">
            AI 모의 심사가 짚은 약점 — 아직 안 고침 {draft.review_notes.reduce((n, note) => n + note.items.length, 0)}개 ▸
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
            {draft.review_notes.flatMap((note) =>
              note.items.map((item, index) => (
                <li key={`${note.section}-${index}`}>
                  {note.section} · <span className="text-cosmos-muted">{item}</span>
                </li>
              )),
            )}
          </ul>
        </details>
      )}
    </div>
  );
}

/** 사업계획서 작성 페이지 주소 — 대시보드와 같은 키 (28차 §3-D). */
export function planPageHref(programId: string): string {
  return `/plan?support=${encodeURIComponent(programId)}`;
}

/** 저장본 요약 한 줄 — 「AI 초안 (9-29 실행) · 본문 문장 n개」 (쉬운 보기 ④ · 초안 칸이 같은 말). */
/**
 * 「회사자료에 입력하면 자동으로 채워지는 칸 k개 → 회사자료로」 (29차 §3-B). 채울 칸이 없으면 아무것도 그리지 않는다.
 * 회사자료 화면의 「사업계획서 일반현황」 묶음으로 간다 — 값은 문서를 조립할 때만 칸에 들어가고 AI 에는 가지 않는다.
 */
export function CompanyFillLink({ draft, large = false }: { draft: PlanDraft | null; large?: boolean }) {
  const fill = draft?.checklist?.company_fill;
  if (!fill || fill.fillable <= 0) return null;
  return (
    <Link
      href="/company#plan-general"
      className={`mc-focus rounded font-medium text-cosmos-cyan hover:underline ${large ? "text-[14px]" : "text-[12.5px]"}`}
      title={fill.fillable_fields.join(" · ")}
      data-company-fill-link
    >
      회사자료에 입력하면 자동으로 채워지는 칸 {fill.fillable}개 → 회사자료로
    </Link>
  );
}

export function planSummaryText(draft: PlanDraft | null, loadNote: string | null): string {
  if (draft?.checklist) return `${draft.checklist.summary}${runLabel(draft.executed_at)}`;
  if (draft && draft.sections.length > 0) return `${draft.generated_by === "llm" ? "AI 초안" : "기본 초안"}${runLabel(draft.executed_at)} · 문장 ${sentenceCounts(draft).body}개`;
  if (loadNote === null) return "저장된 초안을 불러오는 중…";
  if (loadNote) return `저장된 초안을 읽지 못했습니다 — ${loadNote}`;
  return "아직 만들지 않았습니다";
}

function DraftSection({
  outline,
  programId,
  organizationId,
}: {
  outline: SupportDraftSection[];
  programId: string;
  organizationId?: string;
}) {
  const headingId = `${supportSectionId("draft")}-title`;
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  // 저장본 읽기: null = 읽는 중 · "" = 읽음 · 글 = 못 읽은 사유 (27차 SUP-17 — 삼키면 「아직 만들지 않았습니다」와 같아 보였다).
  const [loadNote, setLoadNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getSupportPlanDraft(programId, organizationId)
      .then((saved) => {
        if (!alive) return;
        setDraft(saved);
        setLoadNote("");
      })
      .catch((error: unknown) => {
        if (alive) setLoadNote(describeFailure(error));
      });
    return () => {
      alive = false;
    };
  }, [programId, organizationId]);

  const form = draft?.form;
  const hasDraft = Boolean(draft && draft.sections.length > 0);

  return (
    <div id={supportSectionId("draft")} className={`min-w-0 ${SUPPORT_SECTION_SCROLL_MT}`}>
      <Panel ariaLabelledBy={headingId}>
        <SectionHeader
          id={headingId}
          eyebrow="신청 분석"
          title={`사업계획서 초안 — ${planFormName(draft)} 순서`}
          description="초안은 「사업계획서 작성」 페이지에서 만들고 고칩니다(Claude · Codex 로 쓰기 · 기본 초안 · 이전 판). 여기서는 저장된 초안 요약과 내려받기만 보입니다."
        />
        {form?.notice && <InlineAlert tone="warn" role="status">{form.notice}</InlineAlert>}
        {/* 28차 §3-D — 이 화면의 만들기 단추 · 과제 고르기는 사업계획서 작성 페이지로 옮겼다(같은 단추가 세 화면에 있었다). */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-cosmos-border pt-3">
          <p className="text-[12.5px] text-cosmos-text" data-plan-summary>
            {planSummaryText(draft, loadNote)}
          </p>
          {hasDraft && <PlanDownloadLinks programId={programId} organizationId={organizationId} blanks={draft?.submit_blanks} />}
          <Link href={planPageHref(programId)} className="mc-focus rounded text-[12.5px] font-medium text-cosmos-cyan hover:underline" data-plan-page-link>
            {SCREEN_NAMES.plan} →
          </Link>
          <CompanyFillLink draft={draft} />
        </div>

        {/* 예전 목차 뼈대(6절) — 공고 양식 이전의 근거 정리. 지우지 않고 접어 둔다. */}
        <details className="mt-3 border-t border-cosmos-border pt-2">
          <summary className="mc-focus w-fit cursor-pointer rounded py-1 text-[12.5px] text-cosmos-secondary">
            목차 근거(6절 · 공고 양식 이전) ▸
          </summary>
          <ol className="mt-2 flex flex-col">
            {outline.map((section, index) => (
              <li
                key={section.section}
                className="grid gap-1 border-t border-cosmos-border py-2.5 first:border-t-0 first:pt-0 sm:grid-cols-[minmax(150px,210px)_minmax(0,1fr)] sm:gap-x-4"
              >
                <div className="flex flex-wrap items-start gap-x-2">
                  <span aria-hidden="true" className="font-mono text-[12px] leading-5 text-cosmos-muted">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="text-[12.5px] font-semibold leading-5 text-cosmos-text">{section.section}</span>
                </div>
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Badge tone={section.grounded ? "pass" : "warn"} glyph>
                      {section.grounded ? "근거 있음" : "확인 필요"}
                    </Badge>
                    <span className="min-w-0 break-words text-[12.5px] leading-5 text-cosmos-secondary">{section.basis}</span>
                  </div>
                  {section.quotes && section.quotes.length > 0 && (
                    <ul className="flex flex-col gap-1">
                      {section.quotes.map((quote) => (
                        <li key={quote} className="border-l-2 border-cosmos-border-strong pl-2 text-[12px] leading-5 text-cosmos-secondary">
                          <span className="text-cosmos-muted">공고문 </span>「{quote}」
                        </li>
                      ))}
                    </ul>
                  )}
                  {section.company_facts && section.company_facts.length > 0 && (
                    <p className="break-words text-[12px] leading-5 text-cosmos-secondary">
                      <span className="text-cosmos-muted">맞은 회사 사실 </span>
                      {section.company_facts.join(" · ")}
                    </p>
                  )}
                  {section.note && <p className="break-words text-[12px] leading-5 text-cosmos-muted">{section.note}</p>}
                </div>
              </li>
            ))}
          </ol>
        </details>

        <p className="mt-3 text-[12px] leading-4 text-cosmos-muted">
          초안은 공고 양식 · 공고문 조항 · 회사 사실로만 만듭니다. 대표자 · 연락처 · 사업자등록번호 · 매출액 · 고용인원 · 수상 이력은
          담당자가 채웁니다. 본문 작성과 최종 신청은 담당자가 합니다.
        </p>
      </Panel>
    </div>
  );
}

/** 신청 전 점검 한 줄. */
function CheckItem({ text }: { text: string }) {
  return (
    <li className="flex min-w-0 items-start gap-2 text-[13px] leading-5 text-cosmos-text">
      <span aria-hidden="true" className="mt-px shrink-0 font-mono text-[13px] text-cosmos-amber">
        ☐
      </span>
      <span className="min-w-0 break-words">{text}</span>
    </li>
  );
}

const GENERAL_PROCEDURE_PREFIX = `[${GENERAL_GUIDE_NOTE}] `;
const NOT_FOUND_LINE = /찾지 못함|못 찾은 항목|요약에 없는 항목/;
const FINAL_REVIEW_LINE = /^제출 전 담당자 최종 검토/;

/**
 * 신청 전 점검을 화면에서 묶는다(32차 §3-B-5) — 목록 순서 · 마지막 줄 규칙은 백엔드 그대로.
 * 바로 할 일반 절차(접수 · 확인서 · 접수증 · 협약)가 「원문에서 확인」 줄들 뒤에 묻혀 있었다 → 일반 절차를 앞으로,
 * 「공고문에서 확인할 것」은 접어 두고, 「담당자 최종 검토」 줄은 맨 끝.
 */
export function groupChecks(checks: readonly string[]) {
  const general = checks.filter((c) => c.startsWith(GENERAL_PROCEDURE_PREFIX)).map((c) => c.slice(GENERAL_PROCEDURE_PREFIX.length));
  const notFound = checks.filter((c) => !c.startsWith(GENERAL_PROCEDURE_PREFIX) && NOT_FOUND_LINE.test(c));
  const final = checks.filter((c) => FINAL_REVIEW_LINE.test(c));
  const other = checks.filter((c) => !c.startsWith(GENERAL_PROCEDURE_PREFIX) && !NOT_FOUND_LINE.test(c) && !FINAL_REVIEW_LINE.test(c));
  return { general, notFound, final, other };
}

/** 「공고문에서 못 찾은 항목: 조직 형태 · 고용 인원 — …」 한 줄은 항목 수로 센다(32차 — 같은 꼴 12줄을 한 줄로 묶었다). */
export function notFoundCount(lines: readonly string[]): number {
  return lines.reduce((n, line) => {
    const names = /항목: (.+?) — /.exec(line)?.[1];
    return n + (names ? names.split(" · ").length : 1);
  }, 0);
}

function ChecksSection({ checks }: { checks: string[] }) {
  const headingId = `${supportSectionId("check")}-title`;
  const groups = groupChecks(checks);
  return (
    <div id={supportSectionId("check")} className={`min-w-0 ${SUPPORT_SECTION_SCROLL_MT}`}>
      <Panel ariaLabelledBy={headingId}>
        <SectionHeader
          id={headingId}
          eyebrow="신청 분석"
          title="신청 전 점검"
          description="신청 서류를 넣기 전에 담당자가 원문에서 직접 확인해야 하는 목록입니다."
        />
        {checks.length === 0 ? (
          <p className="mt-3 text-[13px] leading-5 text-cosmos-secondary">점검할 항목이 없습니다.</p>
        ) : (
          <div className="mt-3 flex flex-col gap-3" data-support-checks>
            {groups.other.length > 0 && (
              <ul className="flex flex-col gap-2">
                {groups.other.map((check) => (
                  <CheckItem key={check} text={check} />
                ))}
              </ul>
            )}
            {groups.general.length > 0 && (
              <div className="flex flex-col gap-1.5" data-support-checks-general>
                <p className="text-[12.5px] font-semibold text-cosmos-text">신청 절차 ({GENERAL_GUIDE_NOTE})</p>
                <ul className="flex flex-col gap-2">
                  {groups.general.map((check) => (
                    <CheckItem key={check} text={check} />
                  ))}
                </ul>
                <p className="text-[12.5px]">
                  <GuideContextLink href={GUIDE_LINKS.supportSubmit}>{GUIDE_LINK_TEXT.supportSubmit}</GuideContextLink>
                </p>
              </div>
            )}
            {groups.notFound.length > 0 && (
              <details className="rounded-lg border border-cosmos-border px-3 py-2" data-support-checks-notfound>
                <summary className="mc-focus cursor-pointer text-[12.5px] font-semibold text-cosmos-text">
                  공고문에서 확인할 것 {notFoundCount(groups.notFound)}
                </summary>
                <ul className="mt-2 flex flex-col gap-2">
                  {groups.notFound.map((check) => (
                    <CheckItem key={check} text={check} />
                  ))}
                </ul>
              </details>
            )}
            {groups.final.length > 0 && (
              <ul className="flex flex-col gap-2">
                {groups.final.map((check) => (
                  <CheckItem key={check} text={check} />
                ))}
              </ul>
            )}
          </div>
        )}
        <p className="mt-3 text-[12px] leading-4 text-cosmos-muted">
          이 목록은 저장되지 않습니다. 확인 결과는 담당자가 직접 관리하세요.
        </p>
      </Panel>
    </div>
  );
}

/**
 * 초안 만들기 단추 문구 — 전체 보기와 쉬운 보기가 같은 말을 쓴다(26차 ISSUE-150).
 *
 * **문이 둘이다** (ISSUE-130 · prompt_06 §4-A). 크레딧이 있어도 `LLM_LIVE` 가 꺼져
 * 있으면 AI 초안은 붙지 않는다. 옛 백엔드는 `llm_live` 를 안 주므로 그때는 예전대로 본다.
 */
export function planDraftButtonLabel(draft: PlanDraft | null, { busy, needsTask }: { busy: boolean; needsTask: boolean }): string {
  const ai = aiDraftReady(draft) && !needsTask;
  // 규칙 초안은 곧바로 나온다 — 「몇 분」은 AI 로 쓸 때만 (27차 SUP-21).
  if (busy) return ai ? `절 ${Math.max(1, draft?.checklist?.form?.items_total ?? 8)}개 작성 중 — 몇 분 걸릴 수 있습니다` : "기본 초안 만드는 중…";
  return ai ? `사업계획서 초안 만들기(AI · ${planFormName(draft)})` : "AI 없이 기본 초안 만들기";
}

/** AI 로 초안을 쓸 수 있는가 — 크레딧과 `LLM_LIVE` 두 문 (옛 백엔드는 `llm_live` 를 안 준다). */
function aiDraftReady(draft: PlanDraft | null): boolean {
  return (draft?.credit_ok ?? false) && (draft?.llm_live ?? true);
}

/** 「공고 양식」 · 「표준 양식」 — 공고문에서 양식을 못 찾으면 표준(창업 공통) 양식이다 (27차 SUP-18). */
export function planFormName(draft: PlanDraft | null): string {
  return draft?.form?.source === "standard" ? "표준 양식" : "공고 양식";
}

/** 본문 문장 · 빈칸 표시(유형 없는 「확인 필요」 줄) 수 (27차 SUP-20). */
export function sentenceCounts(draft: PlanDraft): { body: number; blank: number } {
  const sentences = draft.sections.flatMap((section) => section.sentences);
  const blank = sentences.filter((sentence) => sentence.type === null).length;
  return { body: sentences.length - blank, blank };
}

/**
 * 초안을 만들 수 없는 곳이면 그 이유 — 읽기 전용 배포(저장된 화면)는 쓰기를 모두 막고, 사내 배포 열람자는 권한이 없다.
 * 누른 뒤에야 실패하지 않게 단추를 미리 끈다 (27차 SUP-19 · 회사자료 화면과 같은 방식).
 */
export function useDraftBlockReason(): string | null {
  const mode = useDeploymentMode();
  const user = useCurrentUser();
  if (mode?.backend === "snapshot") return "저장된 화면(읽기 전용 배포)이라 초안을 만들 수 없습니다";
  if (user?.role === "viewer") return "열람자 계정은 초안을 만들 수 없습니다 — 편집 권한이 필요합니다";
  return null;
}

export default function SupportEvidencePanel({
  step,
  matches,
  evidenceSummary,
  outline,
  checks,
  organizationLabel,
  programId,
  organizationId,
  markFullScreenLinks = false,
}: {
  step: SupportStepKey;
  matches: SupportEvidenceMatch[];
  evidenceSummary: EvidenceScopeInfo | null;
  outline: SupportDraftSection[];
  checks: string[];
  organizationLabel: string;
  programId: string;
  organizationId?: string;
  /** 쉬운 보기(24차 §3-1): 쉬운 보기가 없는 화면(/company)으로 가는 링크 옆에 「(전체 보기)」(terms FULL_VIEW_ONLY_TAG · CMN-17) */
  markFullScreenLinks?: boolean;
}) {
  if (step === "evidence") {
    return (
      <EvidenceSection
        matches={matches}
        summary={evidenceSummary}
        organizationLabel={organizationLabel}
        markFullScreenLinks={markFullScreenLinks}
      />
    );
  }
  if (step === "draft")
    return (
      <DraftSection outline={outline} programId={programId} organizationId={organizationId} />
    );
  if (step === "check") return <ChecksSection checks={checks} />;
  return null;
}
