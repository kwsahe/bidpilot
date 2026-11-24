"use client";

/**
 * 대시보드 안에서 여는 **기업마당 지원사업** 본문.
 *
 * 입찰 8단계(요구사항 → 회사 근거 → 제안서 → 제출 전 누락 점검)와 나란히 놓이지만
 * 흐름도 말도 다르다. 지원사업은 신청자격 → 필수·우대조건 → 신청기간 → 제출서류 →
 * 회사 적합 근거 → 사업계획서 → 신청 전 점검 7단계다.
 *
 * 지키는 것:
 * - 여기서 쓰지 않는 말: 입찰 · 낙찰 · 투찰 · RFP · 제안서 · 수주 · 평가항목 ·
 *   발주기관 · 나라장터 · Auditor · 참가자격 · 요구사항 · 증빙.
 *   3D 안의 문구는 `SUPPORT_VOCABULARY` 가 통째로 갈아끼운다 — 넘기지 않으면 조용히
 *   입찰 어휘로 떨어져 기업마당 사업에 「나라장터 캐시」·「발주기관」이 적힌다.
 * - 입찰 전용 부품(Cosmos2D · NodeList · CosmosStage · MissionStrip · DetailPanel ·
 *   BottomStrip · TodayPanel · WorkflowRail · CosmosLegend)을 **import 하지 않는다.**
 *   `scripts/check_support_vocabulary.mjs` 가 이것을 기계로 검사한다.
 * - 3D 는 «더하는 것»이지 대체가 아니다. 7단계 본문(SupportPlanPanel ·
 *   SupportEvidencePanel)은 그대로 있고, WebGL 이 없으면 본문만 남는다.
 * - 점수는 「회사 기준 검토 우선순위」다. 선정확률이 아니다.
 * - 미확인을 0 이나 완료로 적지 않는다.
 *
 * CosmosStage 를 거치지 않는 이유: 그 컴포넌트는 WebGL 이 없거나 3D 가 예외를 던지면
 * `Cosmos2D` 로 자동 대체하는데, Cosmos2D 는 「참가 가능 여부 / 제안서 초안 / AI Audit」
 * 같은 입찰 문구를 하드코딩해 두었다. 지원사업 화면이 그 경로로 떨어지면 말이 어긋난다.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import SupportEvidencePanel from "@/components/support/SupportEvidencePanel";
import SupportPlanPanel from "@/components/support/SupportPlanPanel";
import SupportStepBar, { SupportStepNav } from "@/components/support/SupportStepBar";
import { Badge, InlineAlert, Panel } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { formatDate } from "@/lib/cosmos/format";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { dDayText, deadlineTerm, supportDeadlineIso } from "@/lib/deadline";
import { supportUnknownBanner } from "@/lib/supportUnknownNotice";
import { supportSourceBadge } from "@/lib/supportSource";
import { SUPPORT_FINISH_LINES, reviewPriorityText } from "@/lib/terms";
import {
  buildSupportCosmosGraph,
  supportEvidenceTally,
} from "@/lib/cosmos/support/supportGraph";
import {
  SUPPORT_STAGE,
  supportFocusOfStep,
  supportNodeIdOfStep,
  supportStepOfNodeId,
  supportStepStats,
} from "@/lib/cosmos/support/supportSteps";
import { SUPPORT_VOCABULARY } from "@/lib/cosmos/support/supportVocabulary";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import type { SupportApplicationResult, SupportStepKey } from "@/types/opportunity";

/** 3D 는 브라우저에서만 뜬다 (서버 렌더 금지 — three.js 가 window 를 본다). */
const Cosmos3D = dynamic(() => import("@/components/cosmos/three/Cosmos3D"), {
  ssr: false,
  loading: () => <StageNote>3D 화면을 준비하는 중입니다…</StageNote>,
});

function StageNote({ children }: { children: React.ReactNode }) {
  return (
    <div role="status" aria-live="polite" className="flex h-full w-full items-center justify-center px-4 text-center">
      <p className="rounded-full border border-cosmos-border bg-cosmos-panel px-4 py-2 text-[13px] text-cosmos-secondary backdrop-blur">
        {children}
      </p>
    </div>
  );
}

/**
 * 같은 사업의 **신청 분석 화면**(`/support/<id>`)으로 — 대시보드 안(`/analysis?support=`)과 그 화면이 서로 잇는다 (27차 LNK-02).
 * 들어온 길(선택창 · 이번 주 할 일 · 목록)에 따라 두 화면으로 갈려도 한 번에 건너간다.
 */
export function SupportPageLink({ programId }: { programId: string }) {
  return (
    <Link
      href={`/support/${encodeURIComponent(programId)}`}
      className="mc-focus w-fit shrink-0 rounded text-[12.5px] font-medium text-cosmos-cyan underline-offset-2 hover:underline"
      title="같은 지원사업을 신청 분석 화면(7단계 목록 · 개요 · 우선순위 산출 근거)에서 봅니다"
    >
      신청 분석 화면에서 보기 →
    </Link>
  );
}

export interface SupportDashboardBodyProps {
  result: SupportApplicationResult;
  /** 현재 분석 회사 이름 (근거 패널이 «누구의 자료인가»를 적는다) */
  organizationLabel: string;
  reducedMotion: boolean;
  /** 3D 를 그릴 수 있는가. null = 아직 감지 전 */
  webglSupported: boolean | null;
}

export default function SupportDashboardBody({
  result,
  organizationLabel,
  reducedMotion,
  webglSupported,
}: SupportDashboardBodyProps) {
  const nowMs = useNowMs();
  const [step, setStep] = useState<SupportStepKey>("eligibility");
  // 그림(3D)은 사람이 켤 때만 — 기본은 단계 본문이 전체 폭 (28차 §3-F · 지원사업 지도에 네 번째 개편은 하지 않는다).
  // 10-31 대표 결정 — 3D 는 화면에서 뺀다(「보기도 힘들고 메리트도 없다」 · 코드는 남김). 그림 단추를 두지 않는다.
  const showPicture = false;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [resetSignal, setResetSignal] = useState(0);

  /**
   * 보고 있는 단계가 곧 «펼친 묶음»이다.
   * 1~4단계는 그 항목들을 펼치고, 5단계 이후는 전부 접어 관계가 보이게 둔다.
   */
  const expandedGroup: SupportStepKey | null =
    step === "eligibility" || step === "conditions" || step === "schedule" || step === "documents" ? step : null;

  const graph = useMemo(
    () => buildSupportCosmosGraph(result, { expandedGroup }),
    [result, expandedGroup],
  );
  const stats = useMemo(() => supportStepStats(result), [result]);
  const tally = useMemo(() => supportEvidenceTally(result), [result]);
  /** 지금 단계가 3D 에서 무엇을 밝히고 어디서 보는가. 입찰 모드의 `focus` 와 같은 자리다. */
  const focus = useMemo(() => supportFocusOfStep(step, graph), [step, graph]);

  /** 노드를 누르면 본문이 그 단계로 간다. 코어(사업)를 누르면 단계를 바꾸지 않는다. */
  const selectNode = useCallback((id: string | null) => {
    setSelectedId(id);
    if (!id) {
      // 선택을 풀면 전체 보기로 돌아간다. 이것이 resetSignal 의 제 역할이다 —
      // 단계 이동에서 올리면 방금 잡은 노드 포커스를 되돌려 버린다(위 selectStep 주석).
      setResetSignal((n) => n + 1);
      return;
    }
    const target = supportStepOfNodeId(id);
    if (target) setStep(target);
  }, []);

  /**
   * 오른쪽에서 단계를 고르면 3D 에서도 그 노드를 고른 것으로 친다.
   *
   * 예전에는 선택을 통째로 풀어서(`setSelectedId(null)`) 두 화면이 서로 다른 곳을 가리켰다 —
   * 본문은 「제출서류」인데 3D 에는 아무것도 강조되지 않았다. 같은 것을 보고 있다는 게
   * 눈으로 보여야 3D 가 장식이 아니라 흐름을 읽는 도구가 된다.
   */
  const selectStep = useCallback((key: SupportStepKey) => {
    setStep(key);
    setSelectedId(supportNodeIdOfStep(key));
    setHoveredId(null);
    // resetSignal 을 올리지 않는다. CameraRig 에서 그 효과(3)가 focusNodeId 효과(2)
    // **뒤에** 선언되어 있어, 단계를 누를 때마다 방금 잡은 노드 포커스를 overview 로
    // 되돌려 버렸다 — 「카메라가 그대로」로 보이던 것의 실제 원인이다(ISSUE-110).
    // 전체 보기로 되돌리는 것은 노드 선택 해제(코어 클릭)가 할 일이지 단계 이동이 아니다.
  }, []);

  const program = result.program;
  /**
   * 마감 표기는 다른 화면과 **같은 함수**로 만든다.
   *
   * 예전에는 여기서만 `apply_end` 를 그대로 넘겼다. 기업마당은 날짜만(YYYY-MM-DD) 주므로
   * 그 값은 UTC 자정 = 그날 09:00 KST 로 읽혔고, 같은 사업이 이 화면에서만 D-4,
   * 목록·레이더·지원사업 상세에서는 D-5 로 찍혔다. supportDeadlineIso 가 23:59 KST 를 붙인다.
   * nowMs 는 서버 렌더 때 null 이다 (시각을 모르는 상태 — 0 으로 꾸미지 않는다).
   */
  const applyEndAt = supportDeadlineIso(program);
  const dDay = dDayText({ deadline: applyEndAt, periodKind: program.apply_period_kind, nowMs });
  const score = result.company_priority_score;

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 px-3 pb-3 sm:px-5">
      {/* 머리 — 지금 무엇을 보고 있는가. 입찰 공고와 헷갈리지 않게 종류를 먼저 적는다. */}
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {/* 보라 ◆ = 기업마당(출처) — 사업기회 카드 · 레이더 · 지원사업 화면과 같은 표시 (27차 §3-E · UNI-19) */}
        <Badge color={COSMOS_COLORS.violet} glyph="◆">
          기업마당 지원사업 · 신청
        </Badge>
        {/* 출처 배지 하나(34차 R33-A2) — 목록에서 빠진 실공고 사본이 「가상 예시 공고」로 보였다 */}
        <SourceBadge {...supportSourceBadge(result.source, result.archived_closed)} />
        {/* 좁은 폭에서는 제목이 제 줄 — flex-1 · basis 0 이면 390 에서 폭이 0 이 되어 제목이 안 보였다(검증 G5-V6) */}
        <span className="min-w-0 basis-full truncate text-[13px] font-semibold text-cosmos-text sm:basis-0 sm:flex-1" title={program.title}>
          {program.title}
        </span>
        {/* 기관 · 마감 · 우선순위 · 링크는 둘째 줄 — 한 줄에 두면 제목이 남은 폭(800 에서 82px · 1024 에서 34px)만 받아 잘렸다 (EZ-23) */}
        <div className="flex min-w-0 basis-full flex-wrap items-center gap-2">
          <span className="shrink-0 text-[12px] text-cosmos-secondary">{program.agency}</span>
          <span className="shrink-0 font-mono text-[12px] tabular-nums text-cosmos-secondary">
            {/* 마감 머리 낱말도 다른 화면(목록 · 레이더 · 지원사업)과 같은 「신청 마감 D-7」(UNI-21 · 검증 G5-V1) */}
            {applyEndAt
              ? `${deadlineTerm({ source: "bizinfo", closed: result.priority_label === "마감", periodKind: program.apply_period_kind, deadline: applyEndAt })} ${dDay} · ${formatDate(applyEndAt)}`
              : (program.apply_period_text ?? dDay)}
          </span>
          <span
            className="shrink-0 rounded-full border border-cosmos-border px-2 py-px text-[12px] text-cosmos-secondary"
            title="회사 기준 검토 우선순위 — 선정확률이 아닙니다"
          >
            {/* 숫자 한 벌 — 「검토 우선순위 82」(단위 없음) · 없으면 「미산정」 (27차 §3-E-3 · check_page_unity) */}
            {reviewPriorityText(score)}
          </span>
          <SupportPageLink programId={result.program_id} />
          {/* 「공고 원문에서 확인하세요」라고 하면서 원문으로 가는 길이 이 보기에만 없었다 — 쉬운 보기 · 신청 분석 화면과 같은 링크 (EZ-22) */}
          {program.url && (
            <a
              href={program.url}
              target="_blank"
              rel="noreferrer noopener"
              className="mc-focus w-fit shrink-0 rounded text-[12.5px] font-medium text-cosmos-cyan underline-offset-2 hover:underline"
            >
              기업마당 공고 원문 ↗
            </a>
          )}
        </div>
      </div>

      {result.archived && result.archived_note && (
        <InlineAlert tone="warn" role="status">
          <span data-support-archived>{result.archived_note}</span>
        </InlineAlert>
      )}

      {result.eligibility_gate === "FAIL" && result.gate_reason && (
        <InlineAlert tone="fail" role="status">
          <strong>신청자격 우선 확인 · 지금은 불가</strong> — {result.gate_reason}
        </InlineAlert>
      )}

      {(result.unknown_count > 0 || !result.field_mapping_verified) && (
        <InlineAlert tone="warn" role="status">
          {result.unknown_count > 0 && (
            // 조항만 「공고문에서 못 찾은 조항」으로 센다 — 신청 분석 화면과 같은 함수 (SUP-07)
            <>{supportUnknownBanner(result)}{" "}</>
          )}
          {!result.field_mapping_verified && <>기업마당 자료의 항목을 아직 다 맞춰 보지 못했습니다. 금액·기간은 공고 원문에서 한 번 더 확인하세요.</>}
        </InlineAlert>
      )}

      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <SupportStepBar stats={stats} active={step} onSelect={selectStep} />
        </div>
      </div>

      {/* 무대 + 본문. 그림을 켜면 입찰 화면과 같은 배치(왼쪽 그림 · 오른쪽 읽을 것) · 끄면 본문이 전체 폭. */}
      <div className={`flex min-h-0 flex-1 flex-col gap-3 ${showPicture ? "lg:flex-row" : ""}`}>
        {showPicture && (
        <section
          aria-label="지원사업 신청 분석 3D"
          className="relative min-h-[380px] min-w-0 flex-1 overflow-hidden rounded-xl border border-cosmos-border bg-cosmos-deep/40 lg:min-h-[520px]"
        >
          {webglSupported === false ? (
            <StageNote>
              이 브라우저에서는 3D를 그릴 수 없습니다(WebGL 미지원). 오른쪽 단계별 내용은 그대로 볼 수 있습니다.
            </StageNote>
          ) : (
            <Cosmos3D
              graph={graph}
              vocabulary={SUPPORT_VOCABULARY}
              stage={SUPPORT_STAGE[step]}
              selectedId={selectedId}
              hoveredId={hoveredId}
              onSelect={selectNode}
              onHover={setHoveredId}
              highlightNodeIds={focus.nodeIds}
              highlightLinkIds={EMPTY_SET}
              cameraPreset={focus.cameraPreset}
              focusNodeId={selectedId}
              resetSignal={resetSignal}
              reducedMotion={reducedMotion}
              paused={false}
            />
          )}
          {/* 자막은 «지금 보고 있는 단계»를 말한다. 오른쪽 단계 바와 같은 말이어야
              같은 것을 보고 있다는 게 전달된다(ISSUE-110). */}
          <p className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-cosmos-bg/90 to-transparent px-3 py-1.5 text-[12px] text-cosmos-muted">
            {focus.caption} · 노드를 누르면 그 단계로 이동합니다
          </p>
        </section>
        )}

        {/* `lg:max-h-[520px]` — 입찰 대시보드의 우측 열과 같은 이유다 (ISSUE-122 · prompt_04 §3-B-1).
            페이지 높이를 뷰포트에 묶지 않게 되면서 행 높이가 **내용**으로 정해진다. 이 열은
            내부 스크롤 상자(`lg:overflow-y-auto`)라 내용이 길면 그만큼 커지는데, 그러면 3D
            무대까지 같이 늘어난다 — 2000×669 에서 무대가 **1,359px** 이 됐다(실측). 상한을
            무대의 최소 높이(`lg:min-h-[520px]`)와 같은 값으로 두어 둘이 같은 바닥을 갖게 한다. */}
        <div className={`mc-scroll flex min-h-0 w-full flex-col gap-3 ${showPicture ? "lg:max-h-[520px] lg:w-[420px] lg:shrink-0 lg:overflow-y-auto" : ""}`}>
          <SupportPlanPanel step={step} plan={result.plan} attachments={result.program.attachments} programId={result.program_id} />
          <SupportEvidencePanel
            step={step}
            matches={result.evidence_matches}
            evidenceSummary={result.evidence_summary}
            outline={result.draft_outline}
            programId={result.program_id}
            organizationId={result.organization_id}
            checks={result.pre_submit_checks}
            organizationLabel={organizationLabel}
          />
          {step === "evidence" && tally.matches !== tally.unique && (
            <p className="text-[12px] leading-5 text-cosmos-muted">
              검색 결과 {tally.matches}건 가운데 서로 다른 자료는 {tally.unique}건입니다 — 같은 자료가 여러 기준에서
              걸린 것입니다.
            </p>
          )}
          <SupportStepNav active={step} onSelect={selectStep} />
          <Panel className="p-3">
            <p className="text-[12.5px] leading-5 text-cosmos-secondary">
              <strong className="font-semibold text-cosmos-text">{SUPPORT_FINISH_LINES.slice(0, 2).join(" ")}</strong>{" "}
              {SUPPORT_FINISH_LINES.slice(2).join(" ")}
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}

/** 강조 없음. 매 렌더 새 Set 을 만들면 3D 가 쓸데없이 다시 계산한다. */
const EMPTY_SET: ReadonlySet<string> = new Set<string>();
