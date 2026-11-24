"use client";

/**
 * Guided Flow 상세 — 오른쪽 패널을 네 질문(무엇인가 / 왜 중요한가 / 무엇과 연결됐는가 / 다음에 무엇을 하나)으로 구성한다.
 * 그 아래 원문·페이지·출처·관련 위험·다음 단계 버튼. 숫자는 전부 그래프에서 읽고, 미실행은 미실행이라고 말한다.
 */

import type { ReactNode } from "react";

import { SourceBadge, type SourceKind } from "@/components/ui/SourceBadge";
import { CANDIDATE_TIER_LABELS, ELIGIBILITY_LABELS, GENERATION_METHOD_LABELS, formatBudgetCompact, formatPage, seriousText } from "@/lib/cosmos/format";
import Link from "next/link";

import { AI_ADDED_LABEL, REGISTER_COMPANY_DOCUMENTS, SYNTHETIC_COMPANY, SYNTHETIC_NOTICE } from "@/lib/terms";
import { eligibilityGateView, gateCounts } from "@/lib/cosmos/eligibilityGate";
import { formatDeadlineDateTime } from "@/lib/deadline";
import { GUIDED_STEPS, guidedStepDef, representativeEvidence, representativeFinding, representativeRequirement, type GuidedStep } from "@/lib/cosmos/guidedFlow";
import { evidenceRunSentence, evidenceRunState, findingTypeLabel, findingWhy, isSevere, type CosmosGraph, type WorkflowStage } from "@/lib/cosmos/graph";
import { CRITICALITY_LABELS, ITEM_TYPE_LABELS, ITEM_TYPE_WHAT, criticalityOf, displayCodeOf, groupCounts, itemTypeOf } from "@/lib/cosmos/itemTypes";
import { riskSummary } from "@/lib/cosmos/mission";
import { requirementCode } from "@/lib/cosmos/reqCode";
import { evidenceSource, parseSourceLabel } from "@/lib/cosmos/provenance";
import { COSMOS_COLORS, TONE_COLORS } from "@/lib/cosmos/theme";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";

export interface GuidedDetailProps {
  graph: CosmosGraph;
  step: GuidedStep;
  onSelect: (id: string | null) => void;
  onNavigate: (stage: WorkflowStage, nodeId: string | null) => void;
  onNext: () => void;
  onGoTo: (step: GuidedStep) => void;
}

function Q({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">{label}</p>
      <div className="text-[13px] leading-6 text-cosmos-text">{children}</div>
    </div>
  );
}

function Quote({ text, page, label, approximate }: { text: string; page?: number | null; label: string; approximate?: boolean }) {
  return (
    <blockquote className="rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 py-2 text-[12.5px] leading-6 text-cosmos-secondary">
      <p className="mb-1 font-mono text-[12px] text-cosmos-muted">
        {label}
        {page !== undefined ? ` · ${formatPage(page)}${approximate ? " (근사)" : ""}` : ""}
      </p>
      <p className="whitespace-pre-wrap">{text}</p>
    </blockquote>
  );
}

function LinkButton({ onClick, children, accent = COSMOS_COLORS.cyan }: { onClick: () => void; children: ReactNode; accent?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mc-focus w-full rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2 text-left text-[12.5px] leading-5 text-cosmos-text transition-colors hover:border-cosmos-border-strong"
      style={{ borderLeft: `2px solid ${accent}` }}
    >
      {children}
    </button>
  );
}

export default function GuidedDetail({ graph, step, onSelect, onNavigate, onNext, onGoTo }: GuidedDetailProps) {
  const nowMs = useNowMs();
  const def = guidedStepDef(step);
  const { notice, origin, parse, analysis, scenario } = graph.source;
  const rep = representativeRequirement(graph);
  const ev = representativeEvidence(graph);
  const finding = representativeFinding(graph);
  const groups = groupCounts(graph.requirements);
  const originKind: SourceKind = origin.kind === "demo" ? "demo" : origin.source === "g2b" ? "g2b" : "cached";
  const originLabel = origin.kind === "demo" ? SYNTHETIC_NOTICE : origin.source === "g2b" ? "실제 나라장터 공고" : "나라장터 저장본";
  const stageOfStep: Record<GuidedStep, WorkflowStage> = { 1: 1, 2: 4, 3: 5, 4: 6, 5: 7 };
  const risks = riskSummary(graph, nowMs).filter((r) => r.stage === stageOfStep[step] || (step === 2 && r.stage === 3) || (step === 5 && r.stage === 8));
  const blockers = analysis.conditions?.conditions.filter((c) => c.status === "BLOCKER") ?? [];

  let what: ReactNode;
  let why: ReactNode;
  let connected: ReactNode;
  let evidence: ReactNode = null;
  let sources: ReactNode;

  switch (step) {
    case 1: {
      const fit = scenario
        ? `${scenario.semantic_match.label} (${SYNTHETIC_NOTICE})`
        : notice.candidate
          ? // 등급을 HIGH/MED/LOW 로 찍으면 담당자가 영어를 판단 기준으로 읽게 된다 — 라벨 사전을 쓴다.
            `낱말 관련도 ${CANDIDATE_TIER_LABELS[notice.candidate.tier] ?? "확인 필요"} (AI 의미 매칭은 쓰지 않음)`
          : "적합도 아직 안 잼";
      // ③ 의 두 수 — 정거장 캡션 · KPI 타일과 같은 말 (22차 §4-B).
      const gateView = eligibilityGateView(graph.eligibility, analysis.eligibility?.verdict ?? null);
      // 앞에 「참가 가능 여부:」가 붙는 값이다 — 같은 말을 또 적지 않는다(「참가 가능 여부: 참가 가능 여부 …」 · 31차 §3-D).
      const elig = analysis.eligibility
        ? `${ELIGIBILITY_LABELS[analysis.eligibility.verdict] ?? analysis.eligibility.verdict}${gateView ? ` — ${gateCounts(gateView)}` : ""}`
        : gateView
          ? `${gateCounts(gateView)} (${SYNTHETIC_NOTICE})`
          : "아직 판정 안 함";
      what = (
        <>
          <p className="font-semibold">{notice.title}</p>
          <p className="text-cosmos-secondary">
            {/* 마감은 `lib/deadline` 하나가 정한다 — 3D 중앙 카드와 형식이 갈리면 안 된다 (0921 §4-E). */}
            {notice.agency} · 마감 {formatDeadlineDateTime(notice.deadline_at)} · 예산 {formatBudgetCompact(notice.budget)}
          </p>
        </>
      );
      why = (
        <p>
          우리 회사와 맞는 정도: <span className="font-semibold">{fit}</span>. 참가 가능 여부: {elig}. 다음: 맞는 공고면 해야 할 일과 참가 조건을 봅니다.
        </p>
      );
      connected = parse ? (
        <p>
          이 공고에서 과업 {groups.perform}건 · 조건 {groups.conditions + groups.submit}건을 뽑았습니다 ({parse.page_count}p{parse.page_is_approximate ? " 근사" : ""}).
          {blockers.length > 0 ? ` 참가를 막는 조건 ${blockers.length}건이 걸려 있습니다.` : ""}
        </p>
      ) : (
        <p className="text-cosmos-muted">제안요청서를 아직 읽지 않았습니다. 화면 위 「공고 분석 시작」을 누르면 첨부에서 요구사항을 뽑습니다.</p>
      );
      evidence = notice.description ? <Quote text={notice.description} label="공고 개요" /> : null;
      sources = (
        <>
          <SourceBadge kind={originKind} label={originLabel} />
          <SourceBadge kind={scenario ? "demo" : notice.candidate ? "rule" : "not_run"} label={scenario ? `적합도: ${SYNTHETIC_NOTICE}` : notice.candidate ? "적합도: 낱말 기준" : "적합도: 아직 안 함"} />
        </>
      );
      break;
    }
    case 2: {
      if (!rep) {
        what = <p className="text-cosmos-muted">아직 항목이 없습니다. 제안요청서를 읽으면 과업 · 조건이 지도의 「4. 요구사항」 단계에 놓입니다.</p>;
        why = <p>과업은 실제 수행할 일이고, 조건은 참가와 제출을 위해 반드시 지켜야 하는 사항입니다.</p>;
        connected = null;
        sources = <SourceBadge kind="not_run" label="아직 안 읽음" />;
        break;
      }
      const type = itemTypeOf(rep);
      const repNode = graph.nodeById.get(rep.nodeId);
      what = (
        <>
          <p className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-full border border-cosmos-border px-2 py-0.5 text-[12px] text-cosmos-secondary">{ITEM_TYPE_LABELS[type]}</span>
            <span className="font-mono text-[12px] text-cosmos-muted">{displayCodeOf(rep)}</span>
            {repNode?.blocker && <span className="rounded-full border border-cosmos-red/50 px-2 py-0.5 text-[12px] text-cosmos-red" title="참가를 막는 조건">참가 차단</span>}
          </p>
          <p className="font-semibold">{rep.title}</p>
          <p className="text-cosmos-secondary">
            전체: 과업 {groups.perform}건 · 요구사항·자격·특이 {groups.conditions}건 · 제출·일정 {groups.submit}건
          </p>
        </>
      );
      why = (
        <p>
          {ITEM_TYPE_WHAT[type]}{" "}
          {repNode?.blocker
            ? "이 항목은 점수 문제가 아니라 놓치면 입찰에 참여할 수 없는 조건이라 지도에서 붉게 표시됩니다."
            : criticalityOf(rep) !== "normal"
              ? `중대성 ${CRITICALITY_LABELS[criticalityOf(rep)]} — 담당자의 행동이 필요합니다.`
              : "필수 항목은 제안서 초안과 제출 전 누락 점검에서 꼭 답해야 하는 항목입니다."}
        </p>
      );
      connected = (
        <div className="flex flex-col gap-1.5">
          <p>
            회사 근거 {rep.evidence.length}건 · 제안서 문장 {rep.sentences.length}개 · 제출 전 점검 발견 {rep.findings.length}건
          </p>
          <LinkButton onClick={() => onSelect(rep.nodeId)}>이 항목 자세히 보기 →</LinkButton>
        </div>
      );
      evidence = <Quote text={rep.source_text} page={rep.page} label="제안요청서 원문" approximate={parse?.page_is_approximate} />;
      sources = (
        <>
          <SourceBadge kind={origin.kind === "demo" ? "demo" : "computed"} label={parseSourceLabel(graph)} />
          <SourceBadge kind="rule" label="항목 유형: 규칙 분류" />
          {analysis.conditions && <SourceBadge kind="rule" label="조건: 규칙 기반 판정" />}
        </>
      );
      break;
    }
    case 3: {
      if (!graph.hasScenario) {
        // 실공고는 KPI · 5단계 상세와 같은 실행 상태 한 벌 — 근거를 돌린 공고에서도 「미실행」이라 했다 (CMN-02 검증).
        const run = evidenceRunState(graph);
        what =
          run.status === "not_run" ? (
            <p className="text-cosmos-muted">이 공고에서는 회사 근거 연결을 아직 하지 않았습니다.</p>
          ) : (
            <p>{evidenceRunSentence(run)}</p>
          );
        why = <p>승인된 회사자료만 수행근거로 연결하며, 근거가 없으면 확인 필요로 남깁니다. 근거 없이 「충족」으로 표시하지 않습니다.</p>;
        // 지도 5단계로만 옮기던 단추 — 이름대로 회사자료 화면으로 간다 (DSH-09 · LNK-03 과 같은 말).
        connected = (
          <Link href="/company" className="mc-focus self-start rounded text-[13px] font-medium text-cosmos-cyan underline-offset-2 hover:underline">
            {REGISTER_COMPANY_DOCUMENTS} →
          </Link>
        );
        sources = <SourceBadge kind={evidenceSource(graph).kind} label={run.status === "not_run" ? "근거 연결 아직 안 함" : `근거 연결: ${run.label}`} />;
        break;
      }
      const matched = graph.requirements.filter((r) => r.displayStatus === "matched").length;
      const noEvidence = graph.counts.requirementsWithoutEvidence;
      what = (
        <>
          <p className="font-semibold">회사 수행근거 {graph.counts.evidenceDocuments}종 · 채택 연결 {graph.counts.selectedLinks}건</p>
          <p className="text-cosmos-secondary">{[...new Set(graph.evidence.map((e) => e.doc_type))].join(" · ")}</p>
        </>
      );
      why = (
        <p>
          근거 연결 {matched}/{graph.counts.requirements}건. 근거 없는 항목 {noEvidence}건은 자동으로 충족 처리하지 않고 「확인 필요」로 남깁니다.
        </p>
      );
      connected = (
        <div className="flex flex-col gap-1.5">
          {rep && (
            <p>
              대표 항목 「{rep.title}」에 {rep.evidence.length > 0 ? `근거 ${rep.evidence.length}건 (채택 ${rep.evidence.filter((e) => e.selected).length})` : "연결된 회사 수행근거가 없습니다"}.
            </p>
          )}
          {ev && (
            <LinkButton onClick={() => onSelect(ev.nodeId)} accent={COSMOS_COLORS.violet}>
              {ev.document_name} · {ev.doc_type} →
            </LinkButton>
          )}
        </div>
      );
      evidence = ev ? <Quote text={ev.source_text} page={ev.page} label={ev.document_name} /> : null;
      sources = (
        <>
          <SourceBadge kind="demo" label={ev?.synthetic === false ? "회사자료 (비식별)" : SYNTHETIC_COMPANY} />
          {/* 합성 시나리오에 미리 넣어 둔 연결이다 — ● AI 의미 매칭이라 적으면 실제 매칭처럼 읽힌다 (DSH-06) */}
          <SourceBadge kind="demo" label={`연결: ${SYNTHETIC_NOTICE} 고정값`} />
        </>
      );
      break;
    }
    case 4: {
      if (!graph.hasProposal || !graph.proposal) {
        what = <p className="text-cosmos-muted">제안서 초안을 아직 만들지 않았습니다.</p>;
        why = <p>제안요청서 원문과 회사 근거가 연결된 제안서 문장을 확인합니다. 근거 없는 문장은 「확인 필요」로 남습니다.</p>;
        connected = <LinkButton onClick={() => onNavigate(6, null)}>6단계에서 「제안서 초안 만들기」를 누르면 요구사항과 고른 근거만으로 초안을 씁니다</LinkButton>;
        sources = <SourceBadge kind="not_run" label="제안서 아직 안 만듦" />;
        break;
      }
      const sentence = rep?.sentences[0] ?? graph.proposal.sentences[0];
      what = (
        <>
          <p className="font-semibold">{graph.proposal.title}</p>
          <p className="text-cosmos-secondary">
            문장 {graph.counts.sentences}개 · 요구사항 {graph.coverage.covered}/{graph.coverage.total} 반영 · 확인할 문장 {graph.counts.sentencesNeedingReview}
          </p>
        </>
      );
      why = <p>문장마다 공고문 근거 · 회사 근거 · {AI_ADDED_LABEL}을 구분합니다. 근거 없는 문장은 자동 확정하지 않습니다.</p>;
      connected = (
        <div className="flex flex-col gap-1.5">
          {rep && <p>대표 항목 「{rep.title}」 → 대응 문장 {rep.sentences.length}개</p>}
          <LinkButton onClick={() => onSelect("proposal")}>문장별 근거 보기 →</LinkButton>
        </div>
      );
      evidence = sentence ? <Quote text={sentence.text} label={`제안서 문장 ${sentence.id}${sentence.needs_review ? " · 확인 필요" : ""}`} /> : null;
      sources = (
        <SourceBadge
          kind={analysis.proposal ? "analysis" : "demo"}
          label={analysis.proposal ? GENERATION_METHOD_LABELS[analysis.proposal.generation_method] : SYNTHETIC_NOTICE}
        />
      );
      break;
    }
    case 5:
    default: {
      if (!graph.hasAudit) {
        what = <p className="text-cosmos-muted">제출 전 누락 점검을 아직 실행하지 않았습니다.</p>;
        why = <p>제출 전 누락 점검이 빠진 요구사항, 숫자 불일치와 근거 없는 주장을 제출 전에 찾습니다.</p>;
        connected = <LinkButton onClick={() => onNavigate(7, null)}>7단계에서 초안을 붙여넣고 「제출 전 점검」을 누릅니다</LinkButton>;
        sources = <SourceBadge kind="not_run" label="제출 전 누락 점검 아직 안 함" />;
        break;
      }
      what = (
        <>
          <p className="font-semibold">
            찾은 문제 {graph.counts.findings}건 · 안 고친 문제 {graph.counts.findingsOpen} · 그중 {seriousText(graph.counts.findingsHighOpen, graph.counts.findingsBlockingOpen)}
          </p>
          <p className="text-cosmos-secondary">제안서에 빠진 요구사항 {graph.coverage.missingRequirementIds.length}건 · 해결 {graph.counts.findingsResolved}건</p>
        </>
      );
      why = <p>점검에서 찾은 문제는 내기 전에 고칠 곳입니다. 판정은 참고자료이고, 해결 표시와 최종 결정은 담당자가 합니다.</p>;
      connected = (
        <div className="flex flex-col gap-1.5">
          {finding && (
            <LinkButton onClick={() => onSelect(finding.nodeId)} accent={isSevere(finding) ? COSMOS_COLORS.red : COSMOS_COLORS.amber}>
              {findingTypeLabel(finding.finding_type)}
              {finding.requirement_id ? ` · ${requirementCode(graph.requirements, finding.requirement_id)}` : ""} — {findingWhy(finding)}
            </LinkButton>
          )}
          <LinkButton onClick={() => onSelect("audit")}>찾은 문제 전체 보기 →</LinkButton>
        </div>
      );
      evidence = finding?.source_text ? <Quote text={finding.source_text} page={finding.source_page} label="제안요청서 원문 (찾은 문제의 근거)" /> : null;
      sources = (
        <SourceBadge
          kind={analysis.audit ? "analysis" : "demo"}
          label={analysis.audit ? (analysis.audit.llm_used ? "규칙+AI 검사" : "규칙 검사") : SYNTHETIC_NOTICE}
        />
      );
      break;
    }
  }

  return (
    <div className="flex flex-col gap-4" style={{ animation: "mc-fade-up 160ms ease-out" }}>
      <div className="rounded-xl border border-cosmos-cyan/30 bg-cosmos-cyan/5 px-3 py-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-cyan">
          안내 {def.id}/5 · {def.title}
        </p>
        <p className="mt-0.5 text-[12.5px] leading-5 text-cosmos-secondary">{def.caption}</p>
      </div>

      <Q label="이것은 무엇인가">{what}</Q>
      <Q label="왜 중요한가">{why}</Q>
      {connected && <Q label="무엇과 연결됐는가">{connected}</Q>}
      {evidence && <Q label="원문 · 페이지">{evidence}</Q>}
      <Q label="데이터 출처">
        <div className="flex flex-wrap gap-1.5">{sources}</div>
      </Q>
      {risks.length > 0 && (
        <Q label="관련 위험">
          <ul className="flex flex-col gap-1">
            {risks.slice(0, 3).map((r) => (
              <li key={r.id}>
                <LinkButton onClick={() => onNavigate(r.stage, r.nodeId)} accent={TONE_COLORS[r.tone]}>
                  <span className="font-semibold">{r.label}</span>
                  <span className="block text-[12px] text-cosmos-secondary">{r.detail}</span>
                </LinkButton>
              </li>
            ))}
          </ul>
        </Q>
      )}
      <Q label="다음에 무엇을 해야 하나">
        <div className="flex flex-col gap-1.5">
          <button
            type="button"
            onClick={onNext}
            className="mc-focus min-h-10 rounded-lg bg-cosmos-blue-strong px-3 text-[13px] font-semibold text-white transition-[filter] hover:brightness-110"
          >
            {def.nextLabel}
          </button>
          <div className="flex flex-wrap gap-1">
            {GUIDED_STEPS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => onGoTo(s.id)}
                aria-current={s.id === step ? "step" : undefined}
                className={`mc-focus min-h-8 rounded-md px-2 text-[12px] ${s.id === step ? "bg-cosmos-cyan/20 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"}`}
              >
                {s.id}. {s.title}
              </button>
            ))}
          </div>
        </div>
      </Q>
    </div>
  );
}
