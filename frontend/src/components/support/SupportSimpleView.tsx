"use client";

/**
 * 쉬운 보기 — 기업마당 지원사업 신청 분석 (24차 · prompt_14 §3-4).
 *
 * `/support/[id]`(SupportShell)와 대시보드 `/analysis?support=`(DashboardShell) 두 곳이 **이 컴포넌트 하나**를 쓴다.
 * 덩어리는 넷: 사업 · 「신청할 수 있나요?」 · 진행 단계(펼침 = 전체 보기 패널 그대로) · 사업계획서 초안 한 줄.
 * 지원사업에는 「지금 할 일」과 결정 저장이 없으므로 그 덩어리는 두지 않는다(새 판정 · 새 API 없음).
 *
 * 입찰 부품(DetailPanel · TodayPanel · MissionStrip …)은 가져오지 않는다 — check_support_vocabulary C 규칙.
 * 글자 크기는 바깥 틀 `[data-view="simple"]` 의 CSS 가 올린다(globals.css).
 */

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import SupportEvidencePanel, { CompanyFillLink, PlanDownloadLinks, planPageHref, planSummaryText } from "@/components/support/SupportEvidencePanel";
import SupportPlanPanel from "@/components/support/SupportPlanPanel";
import NoticeQaPanel from "@/components/ui/NoticeQaPanel";
import { getSupportPlanDraft } from "@/lib/api";
import { buildSupportSteps } from "@/lib/cosmos/support/supportSteps";
import { VERDICT_BOX_CLASS } from "@/lib/cosmos/theme";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { dDayText, daysUntil, deadlineTerm, formatDeadlineDate, isOpenEnded, supportDeadlineIso, urgencyTierOf } from "@/lib/deadline";
import { describeFailure } from "@/lib/errors";
import { supportSourceBadge } from "@/lib/supportSource";
import { verdictOf } from "@/lib/verdict";
import { GUIDE_LINK_TEXT, SCREEN_NAMES, SUPPORT_FINISH_LINES, SUPPORT_WHERE_LINE } from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import type { PlanDraft, SupportApplicationResult, SupportProgramDetail, SupportStepKey } from "@/types/opportunity";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";

const SECTION = "flex flex-col gap-3 border-t border-cosmos-border pt-6";
const SECTION_TITLE = "text-[15px] font-semibold text-cosmos-secondary";

function scrollToId(id: string): void {
  window.requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
}

/**
 * 머리 마감은 D-day 줄 한 곳 — 10-31 최종 점검: 「… · 예산 소진시까지」(뜻 줄 꼬리) · 「상시·예산 소진 시」 · 「예산 소진시까지」로 세 번 적혔다.
 * 뜻 줄(서버 `company_meaning_line`)의 마감 조각(「n월 n일 마감」 · 날짜가 없으면 신청기간 원문)은 떼고,
 * 상시 · 예산 소진 공고는 D-day 칸이 이미 그 말이라 옆 칸에는 날짜(있을 때)만 둔다.
 */
function headDeadlineParts(
  program: Pick<SupportProgramDetail, "apply_end" | "apply_period_text" | "apply_period_kind">,
  meaning: string | null,
  closed: boolean,
): { meaning: string | null; note: string | null } {
  const end = program.apply_end ? /^\d{4}-(\d{2})-(\d{2})/.exec(program.apply_end) : null;
  const tail = end ? `${Number(end[1])}월 ${Number(end[2])}일 마감` : program.apply_period_text;
  const trimmed = meaning && tail && meaning.endsWith(` · ${tail}`) ? meaning.slice(0, -(tail.length + 3)) : meaning;
  const kind = program.apply_period_kind;
  const note = program.apply_end
    ? isOpenEnded(kind)
      ? `${formatDeadlineDate(program.apply_end)}까지`
      : `${deadlineTerm({ source: "bizinfo", closed, periodKind: kind, deadline: program.apply_end })} ${formatDeadlineDate(program.apply_end)}`
    : isOpenEnded(kind)
      ? null
      : (program.apply_period_text ?? "신청기간 원문 확인 필요");
  return { meaning: trimmed, note };
}

export default function SupportSimpleView({
  result,
  organizationLabel,
  footer = null,
}: {
  result: SupportApplicationResult;
  organizationLabel: string;
  /** 맨 아래 이동 줄 — 지원사업 화면은 되돌아가기, 대시보드는 신청 분석 화면 링크 (27차 LNK-02 · LNK-11). */
  footer?: ReactNode;
}) {
  const nowMs = useNowMs();
  const [itemsOpen, setItemsOpen] = useState(false);
  const [open, setOpen] = useState<SupportStepKey | null>(null);
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  // 저장본 읽기: null = 읽는 중 · "" = 읽음 · 글 = 못 읽은 사유 (27차 SUP-17 — 삼키면 「아직 만들지 않았습니다」와 같아 보였다).
  const [loadNote, setLoadNote] = useState<string | null>(null);

  // 초안 요약 줄 — 저장본을 읽는다(만들기는 이 줄의 단추 · 펼친 초안 단계의 단추). 펼침이 바뀌면 다시 읽어 방금 만든 초안도 보인다.
  useEffect(() => {
    let alive = true;
    getSupportPlanDraft(result.program_id, result.organization_id)
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
  }, [result.program_id, result.organization_id]);

  const { program } = result;
  // 43차 Q11 — 수행기관 모집(제목 · 백엔드 `is_operator_call` 과 같은 꼴)
  const operatorCall = /(주관기관|운영기관|수행기관|전문기관|관리기관)\s*(?:공개)?\s*모집/.test(program.title);
  const source = supportSourceBadge(result.source, result.archived_closed);
  const deadline = supportDeadlineIso(program);
  const days = nowMs === null ? null : daysUntil(deadline, nowMs);
  const tier = urgencyTierOf(days, false);
  const verdict = verdictOf(result.eligibility_gate, result.participation);
  // 판정 상자 · 글자 — 대시보드 쉬운 보기 판정 카드와 같은 `VERDICT_BOX_CLASS` (27차 §3-E · UNI-10). 간접 · 미확인은 무색.
  const verdictBox = !result.participation && result.eligibility_gate ? VERDICT_BOX_CLASS[result.eligibility_gate] : null;
  const steps = buildSupportSteps(result);
  const money = result.plan.eligibility.find((item) => item.key === "clause_money" && item.status === "confirmed");
  const head = headDeadlineParts(program, result.company_meaning ?? null, result.priority_label === "마감");

  const toggleStep = (key: SupportStepKey) => {
    // 신청자격 단계는 판정 카드 안에서 펼친다 — 같은 패널을 두 번 그리지 않는다(id 하나).
    if (key === "eligibility") {
      setItemsOpen(true);
      scrollToId("support-simple-verdict");
      return;
    }
    setOpen((current) => (current === key ? null : key));
  };

  return (
    <div data-view="simple" className="mx-auto flex w-full max-w-[960px] flex-col gap-6 pb-16 pt-4">
      {/* ① 사업 */}
      <section aria-labelledby="support-simple-title" className="flex flex-col gap-2" data-simple-chunk="program">
        <h1 id="support-simple-title" className="break-keep text-[20px] font-semibold leading-snug text-cosmos-text [overflow-wrap:anywhere]">
          {program.title}
        </h1>
        <p className="text-[15px] text-cosmos-secondary">
          {program.agency}
          {program.executing_agency ? ` · ${program.executing_agency}` : ""}
        </p>
        {/* 목록에서 빠진 사업 — 마감인지 · 내려간 것인지(33차 §3-A-6 · 34차 R33-A1 · A2). 대시보드 쉬운 보기도 이 줄 */}
        {result.archived && result.archived_note && (
          <p role="status" className="text-[15px] text-cosmos-amber" data-support-archived>
            {result.archived_note}
          </p>
        )}
        {head.meaning ? (
          <p className="text-[15px] text-cosmos-text">
            <span className="text-cosmos-secondary">우리 회사 입장에서 </span>
            {head.meaning}
          </p>
        ) : money ? (
          <p className="text-[15px] text-cosmos-text">
            <span className="text-cosmos-secondary">{money.label} </span>
            {money.value}
          </p>
        ) : null}
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span
            className={`text-[28px] font-semibold tabular-nums ${
              tier === "closed" ? "text-cosmos-red-text" : tier === "urgent" || tier === "soon" ? "text-cosmos-amber" : "text-cosmos-text"
            }`}
          >
            {dDayText({ deadline, periodKind: program.apply_period_kind, nowMs })}
          </span>
          {head.note && <span className="text-[14px] text-cosmos-secondary">{head.note}</span>}
        </p>
        {program.url && (
          <a href={program.url} target="_blank" rel="noreferrer noopener" className="mc-focus w-fit rounded text-[15px] text-cosmos-cyan underline underline-offset-4">
            기업마당 공고 원문 ↗
          </a>
        )}
        <p className="text-[14px] text-cosmos-secondary" data-simple-source>
          출처: {source.label} · {result.document_read ? "공고문 파일까지 읽음" : (result.document_note ?? "공고 요약만 읽음")}
        </p>
      </section>

      {/* ② 신청할 수 있나요? — 판정은 백엔드 값(eligibility_gate · gate_reason) 그대로 */}
      <section
        id="support-simple-verdict"
        aria-labelledby="support-simple-question"
        data-simple-verdict={result.eligibility_gate ?? "none"}
        className={`flex scroll-mt-52 flex-col gap-3 rounded-xl border-2 px-5 py-4 sm:scroll-mt-40 lg:scroll-mt-28 ${verdictBox ? verdictBox.box : "border-cosmos-border"}`}
      >
        <h2 id="support-simple-question" className={SECTION_TITLE}>
          신청할 수 있나요?
        </h2>
        <p className={`break-keep text-[22px] font-semibold leading-snug [overflow-wrap:anywhere] ${verdictBox ? verdictBox.text : "text-cosmos-text"}`}>
          {verdict.label}
          {result.gate_reason ? <span className="text-cosmos-text"> — {result.gate_reason}</span> : null}
        </p>
        {/* 「간접」 한 낱말만으로는 뜻을 모른다 — 판정 사전의 설명 한 줄(회사가 직접 신청하는 자리가 아님 · EZ-32) */}
        {result.participation && <p className="text-[15px] leading-6 text-cosmos-text">{verdict.title}</p>}
        {result.plan.eligibility.length > 0 && (
          <>
            <button
              type="button"
              aria-expanded={itemsOpen}
              onClick={() => setItemsOpen((v) => !v)}
              className="mc-focus min-h-10 w-fit rounded text-left text-[15px] font-medium text-cosmos-text underline-offset-4 hover:underline"
            >
              신청 요건 {result.plan.eligibility.length}개 하나씩 보기 {itemsOpen ? "▾" : "▸"}
            </button>
            {itemsOpen && <SupportPlanPanel step="eligibility" plan={result.plan} attachments={program.attachments} showSourceFields={false} />}
          </>
        )}
      </section>

      {/* ③ 진행 단계 — 펼치면 전체 보기 패널 그대로 */}
      <section aria-labelledby="support-simple-steps" className={SECTION} data-simple-chunk="steps">
        <h2 id="support-simple-steps" className={SECTION_TITLE}>
          진행 {steps.length}단계
        </h2>
        <div className="@container">
          <ol className="grid grid-cols-1 gap-2 @min-[700px]:grid-cols-7">
            {steps.map((step) => {
              const key = step.key as SupportStepKey;
              const expanded = key === "eligibility" ? itemsOpen : open === key;
              return (
                <li key={step.key} className="flex">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    data-simple-step={step.id}
                    onClick={() => toggleStep(key)}
                    className={`mc-focus flex w-full items-baseline gap-2 rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-wait disabled:opacity-60 @min-[700px]:flex-col @min-[700px]:gap-1 ${
                      expanded ? "border-cosmos-text bg-cosmos-elevated/60" : "border-cosmos-border hover:border-cosmos-border-strong"
                    }`}
                  >
                    {/* 레일 · 대시보드 쉬운 보기와 같은 상태 기호 · 색(27차 §3-E UNI-09 — 「실패」 · 「진행 중」이 「○」로 보였다) */}
                    <span className="shrink-0 font-mono text-[15px] text-cosmos-secondary" title={STEP_STATUS_META[step.status].label}>
                      <span aria-hidden="true" style={{ color: STEP_STATUS_META[step.status].color }}>
                        {STEP_STATUS_META[step.status].glyph}
                      </span>
                      <span className="sr-only">{STEP_STATUS_META[step.status].label} </span> {step.id}
                    </span>
                    {/* 띄어쓰기 없는 「필수·우대조건」이 7칸(약 800px)에서 칸 밖으로 삐졌다 — 넘칠 때만 끊는다 (27차 SUP-30). */}
                    <span className="break-keep text-[14px] leading-snug text-cosmos-text [overflow-wrap:anywhere]">{step.label}</span>
                    <span className="ml-auto break-keep text-right text-[14px] leading-snug text-cosmos-secondary @min-[700px]:ml-0 @min-[700px]:text-left">
                      {step.summary}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
        {open && (
          // 고정 머리(390 에서는 여러 줄) 아래에 패널 머리가 오게 (27차 SUP-31 — scroll-mt 16px 은 머리에 가렸다).
          <div id="support-simple-step-panel" className="flex scroll-mt-52 flex-col gap-3 sm:scroll-mt-40 lg:scroll-mt-28">
            <SupportPlanPanel step={open} plan={result.plan} attachments={program.attachments} collapseAttachmentsAfter={2} showSourceFields={false} />
            <SupportEvidencePanel
              step={open}
              matches={result.evidence_matches}
              evidenceSummary={result.evidence_summary}
              outline={result.draft_outline}
              programId={result.program_id}
              organizationId={result.organization_id}
              checks={result.pre_submit_checks}
              organizationLabel={organizationLabel}
              markFullScreenLinks
            />
          </div>
        )}
      </section>

      {/*
        ④ 사업계획서 초안 — 요약 한 줄 + DOCX + 「사업계획서 작성 →」 (28차 §3-D). 만들기 · 과제 고르기 · 규칙 초안으로 바꾸기는
        사업계획서 작성 페이지 한 곳으로 옮겼다 — 같은 단추가 세 화면에 있었고 두 단추를 맞추는 코드가 따로 있었다.
      */}
      <section aria-labelledby="support-simple-draft" className={SECTION} data-simple-chunk="draft">
        <h2 id="support-simple-draft" className={SECTION_TITLE}>
          사업계획서 초안
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-[15px] text-cosmos-text" data-plan-summary>
            {planSummaryText(draft, loadNote)}
          </p>
          {draft && draft.sections.length > 0 && (
            <PlanDownloadLinks programId={result.program_id} organizationId={result.organization_id} large variants={["submit"]} blanks={draft.submit_blanks} />
          )}
          <Link
            href={planPageHref(result.program_id)}
            className="mc-focus inline-flex min-h-10 items-center rounded-lg border border-cosmos-border-strong px-4 text-[15px] font-medium text-cosmos-text hover:border-cosmos-text/60"
            data-plan-page-link
          >
            {operatorCall ? "수행 제안서 · 수행계획 쓰기" : SCREEN_NAMES.plan} →
          </Link>
          <CompanyFillLink draft={draft} large />
        </div>
        {/* 43차 Q11 · BIZ-08 — 수행기관 모집은 지원금 신청서가 아니라 운영 제안서 */}
        {operatorCall && (
          <p className="text-[14px] text-cosmos-secondary">수행기관 모집(매출) — 지원금 신청서가 아니라 사업을 운영할 기관의 제안서입니다. 공고문의 제안서 양식 · 평가 항목을 먼저 보세요.</p>
        )}
        {/* 외부 점검 T4 — 표준 양식 안내는 서버 글 하나(/plan · 전체 보기와 같은 글) */}
        {draft?.form?.source === "standard" && draft.form.notice && <p className="text-[14px] text-cosmos-secondary">{draft.form.notice}</p>}
        {/* 쉬운 보기는 글자가 커서 앞의 두 문장만(31차 §3-B) */}
        <p className="text-[14px] font-semibold text-cosmos-text">{SUPPORT_FINISH_LINES.slice(0, 2).join(" ")}</p>
        {/* 어디서 무엇을 — 전체 보기에만 있던 접수처 · 제출완료 · 접수증(32차 §3-B-5). 글자가 큰 보기라 한 줄 + 링크 */}
        <p className="text-[14px] text-cosmos-secondary" data-simple-support-where>
          {SUPPORT_WHERE_LINE} <GuideContextLink href={GUIDE_LINKS.supportSubmit}>{GUIDE_LINK_TEXT.supportSubmit}</GuideContextLink>
        </p>
      </section>
      {/* 2.4.0 ⑦ 공고문에 질문하기 — 맨 아래(첫 화면 단추 수를 늘리지 않는 자리 · 접힌 칸) */}
      <section aria-label="공고문에 질문하기" className={SECTION} data-simple-chunk="notice-qa">
        <NoticeQaPanel key={result.program_id} itemId={result.program_id} kind="support" />
      </section>
      {footer}
    </div>
  );
}
