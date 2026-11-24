"use client";

/**
 * 기업마당 지원사업 **신청** 분석 화면 (`/support/[id]`).
 *
 * 입찰(Mission Control)과 디자인 언어는 같지만 흐름과 용어가 다르다.
 *   입찰:     참가자격 → 특이조건 → 요구사항 → 회사 근거 → 제안서 → AI Auditor
 *   지원사업: 신청자격 → 필수·우대조건 → 신청기간 → 제출서류 → 회사 적합 근거 → 사업계획서 → 신청 전 점검
 *
 * 지키는 것:
 * - 여기서 쓰지 않는 말: 입찰자격 · 낙찰 · 투찰 · RFP · 제안서 평가항목 · 수주확률.
 * - `company_priority_score` 는 **회사 기준 검토 우선순위**다. 선정확률·성공확률이 아니다.
 * - 점수가 null 이면 **미확인**이며 0점으로 그리지 않는다.
 * - 목록 API에 없는 조건은 지어내지 않고 「원문 상세 확인 필요」로 남긴다.
 * - 지원 규모는 목록에 없다 — 0원으로 표시하지 않는다.
 * - 하나의 분석은 하나의 회사에 고정된다. 회사를 바꾸면 섞지 않고 다시 조회한다.
 *
 * 정보량 규칙 (기능·데이터는 그대로, 한 화면에 보이는 양만 줄인다):
 * - 상단은 사업명 · 출처 · 주관기관 · 신청 마감 · 회사 우선순위 · 원문/접수처까지만.
 *   수행기관·지원분야·등록일·전체 요약은 지우지 않고 「개요 자세히」 시트로 옮긴다.
 * - KPI는 3개(우선순위 · 신청 마감 · 확인 필요). 확인된 항목 수와 근거 건수는 해당 단계에서 본다.
 * - 7단계는 얇은 진행 바이고, 본문에는 **선택한 한 단계**만 그린다.
 * - 「원문 상세 확인 필요」 경고는 상단에서 한 번만. 항목에는 작은 상태 표시만 둔다.
 * - 점수 산정 근거는 기본으로 접혀 있다(시트).
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { GROUP_TONE } from "@/components/opportunities/PracticalTags";
import SupportEvidencePanel from "@/components/support/SupportEvidencePanel";
import SupportPlanPanel, { plainText } from "@/components/support/SupportPlanPanel";
import SupportSimpleView from "@/components/support/SupportSimpleView";
import DecisionPanel from "@/components/opportunities/DecisionPanel";
import { supportSourceBadge } from "@/lib/supportSource";
import SupportStepBar, { SupportStepNav, supportSectionId } from "@/components/support/SupportStepBar";
import AppShell from "@/components/ui/AppShell";
import NoticeQaPanel from "@/components/ui/NoticeQaPanel";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { SUPPORT_VIEW_TITLES, ViewModeSwitch } from "@/components/ui/ViewModeToggle";
import { useDisplayMode } from "@/lib/viewMode";
import { clearSelectedSupport, readSelectedSupport, rememberSupport } from "@/lib/selection";
import { Popover, Sheet } from "@/components/ui/overlays";
import { Badge, Button, EmptyState, InlineAlert, KpiCard, LoadingState, Panel, SectionHeader, type Tone } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { describeFailure } from "@/lib/errors";
import { supportUnknownBanner } from "@/lib/supportUnknownNotice";
import { verdictOf } from "@/lib/verdict";
import { ApiError, getSupportProgram } from "@/lib/api";
import { formatDate, formatDateTime, formatPercent } from "@/lib/cosmos/format";
import { dDayText, deadlineTerm, formatDeadlineDate, normalizeApplyEnd } from "@/lib/deadline";
import { FULL_VIEW_ONLY_TAG, SCREEN_NAMES, SUPPORT_FINISH_LINES, UNSCORED, VIEW_RELOAD_TERM } from "@/lib/terms";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { supportStepStats } from "@/lib/cosmos/support/supportSteps";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { organizationName, useOrganizationId, useOrganizations } from "@/lib/organization";
import { EVIDENCE_SCOPE_LABELS, type EvidenceScope } from "@/types/organization";
import {
  CONFIDENCE_LABELS,
  type PriorityLabel,
  type SupportApplicationResult,
  type SupportStepKey,
} from "@/types/opportunity";

/** 되돌아갈 화면. `/radar` 는 같이 만드는 중인 화면이라 경로만 문자열로 둔다. */
const BACK_LINKS: Array<{ href: string; label: string; hint: string }> = [
  // 상단 메뉴(AppShell)가 이 화면을 「레이더」라고 부른다 — 돌아가는 버튼도 같은 이름이어야 길을 잃지 않는다.
  { href: "/radar", label: SCREEN_NAMES.radar, hint: "나라장터 입찰과 기업마당 지원사업을 회사 기준 검토 우선순위로 한 화면에" },
  { href: "/opportunities", label: SCREEN_NAMES.opportunities, hint: "나라장터 입찰공고와 기업마당 지원사업 전체 목록" },
];

/**
 * 「← 사업기회」 주소(2.0.6) — 사업기회 행이 `from` 으로 실어 준 조건(탭 · 정렬 · 검색) 그대로. 작성 화면(`plan/page.tsx` `readBackHref`)과 같은 규칙:
 * 주소 조각(`?…`)만 받는다 — 다른 곳으로 가는 주소를 만들지 않는다. 없거나 모양이 다르면 그냥 `/opportunities`.
 */
const subscribeNever = () => () => {};
function readOpportunitiesHref(): string {
  const from = new URLSearchParams(window.location.search).get("from") ?? "";
  return /^\?[^#\s]*$/.test(from) ? `/opportunities${from}` : "/opportunities";
}
const readOpportunitiesHrefServer = (): string => "/opportunities";
/** 「← 레이더」 주소(2.0.6) — 레이더 상세가 `rfrom` 으로 실어 준 레이더 조건 그대로. 같은 규칙(주소 조각만 받음). */
function readRadarHref(): string {
  const from = new URLSearchParams(window.location.search).get("rfrom") ?? "";
  return /^\?[^#\s]*$/.test(from) ? `/radar${from}` : "/radar";
}
const readRadarHrefServer = (): string => "/radar";

const LINK_BUTTON =
  "mc-focus inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 py-1.5 text-[13px] font-semibold text-cosmos-text transition-colors hover:border-cosmos-cyan/60";

/** 보조 동작(시트 열기) — 링크 버튼보다 약하게, 그러나 눌러야 할 것으로 보이게. */
const CHIP_BUTTON =
  "mc-focus inline-flex min-h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-cosmos-border bg-cosmos-panel px-2.5 py-1 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text";

/** 검토 우선순위 라벨 → 색. 확률이 아니라 검토 순서다. */
const PRIORITY_TONE: Record<PriorityLabel, Tone> = {
  "우선 검토": "pass",
  검토: "info",
  후순위: "muted",
  미확인: "warn",
  마감: "fail",
};

/** 지원 적합도 판정 방식 원값 → 담당자 말. 「keyword_rule」을 화면에 그대로 쓰지 않는다. */
const FIT_METHOD_LABELS: Record<string, string> = {
  keyword_rule: "낱말 기준",
};

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return describeFailure(error, "지원사업 정보를 불러오지 못했습니다.");
  }
  return describeFailure(null, "지원사업 정보를 불러오지 못했습니다.");
}

interface LoadState {
  key: string;
  result: SupportApplicationResult | null;
  error: string | null;
  notFound: boolean;
}


export default function SupportShell({ programId }: { programId: string }) {
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();
  const nowMs = useNowMs();
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<LoadState | null>(null);
  // 본문에는 이 단계 하나만 그린다. 다른 단계는 진행 바로 언제든 되돌아갈 수 있다.
  const [step, setStep] = useState<SupportStepKey>("eligibility");

  // 회사·사업이 바뀌면 키가 바뀌고, 응답이 도착할 때까지 이전 회사 결과를 보여주지 않는다.
  const requestKey = `${programId}::${organizationId}::${tick}`;

  useEffect(() => {
    let cancelled = false;
    getSupportProgram(programId, organizationId).then(
      (value) => {
        if (!cancelled) setLoaded({ key: requestKey, result: value, error: null, notFound: false });
      },
      (error: unknown) => {
        if (!cancelled) {
          setLoaded({
            key: requestKey,
            result: null,
            error: describeError(error),
            notFound: error instanceof ApiError && error.status === 404,
          });
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [programId, organizationId, requestKey]);

  const fresh = loaded !== null && loaded.key === requestKey ? loaded : null;
  const loading = fresh === null;
  const result = fresh?.result ?? null;

  // 찾은 사업만 선택 저장소에 남긴다(주소는 그대로) — 상단 메뉴 · 회사자료 「돌아가기」가 이 사업을 따른다 (27차 LNK-01).
  // 없는 사업이면 저장해 둔 같은 id 를 비운다 — 「돌아가기」 · 레이더가 없는 사업을 계속 가리켰다(대시보드 404 와 같은 규칙 · 2.0.5).
  const notFound = fresh?.notFound ?? false;
  useEffect(() => {
    if (result) rememberSupport(programId);
    else if (notFound && readSelectedSupport() === programId) clearSelectedSupport();
  }, [result, notFound, programId]);

  const currentName = organizationName(organizations.list, organizationId);
  const stats = useMemo(() => (result ? supportStepStats(result) : []), [result]);
  const source = result ? supportSourceBadge(result.source, result.archived_closed) : null;

  const simple = useDisplayMode() === "simple";
  const opportunitiesHref = useSyncExternalStore(subscribeNever, readOpportunitiesHref, readOpportunitiesHrefServer);
  const radarHref = useSyncExternalStore(subscribeNever, readRadarHref, readRadarHrefServer);

  // 머리 오른쪽 순서: 회사 → 보기 전환 → 화면 단추 (27차 §3-E-4). 바꾸면 이 회사 기준으로 다시 조회한다.
  const headerAside = (
    <>
      <OrganizationPicker id="support-organization" list={organizations.list} organizationId={organizationId} />
      <ViewModeSwitch titles={SUPPORT_VIEW_TITLES} />
      <Button
        size="sm"
        variant="secondary"
        onClick={() => setTick((value) => value + 1)}
        disabled={loading}
        title="이 사업을 다시 분석합니다 — 새 공고 받기가 꺼져 있으면 저장해 둔 기업마당 목록으로 다시 계산만 합니다"
      >
        {VIEW_RELOAD_TERM}
      </Button>
    </>
  );

  const backLinks = (
    <nav aria-label="되돌아가기" className="flex flex-wrap items-center gap-2">
      {BACK_LINKS.map((link) => (
        <Link key={link.href} href={link.href === "/opportunities" ? opportunitiesHref : link.href === "/radar" ? radarHref : link.href} className={LINK_BUTTON} title={link.hint}>
          <span aria-hidden="true">←</span>
          {link.label}
          {/* 쉬운 보기에서 전체 화면뿐인 곳(레이더)으로 가는 링크는 꼬리표 (24차 규칙 · 27차 LNK-11) */}
          {simple && link.href === "/radar" && ` ${FULL_VIEW_ONLY_TAG}`}
        </Link>
      ))}
      {/* 같은 사업을 대시보드(신청 7단계 + 3D)에서도 연다 — 두 화면이 서로 잇는다 (27차 LNK-02).
          결과가 있을 때만 — 「없는 사업」 · 실패 화면에서 따라가면 대시보드가 없는 사업을 선택으로 저장했다(검증 G4-V1). */}
      {result && (
      <Link
        href={`/analysis?support=${encodeURIComponent(programId)}`}
        className={LINK_BUTTON}
        title="같은 지원사업을 입찰 분석 화면에서 신청 7단계로 봅니다"
      >
        입찰 분석 화면에서 보기<span aria-hidden="true"> →</span>
      </Link>
      )}
    </nav>
  );

  return (
    <AppShell headerAside={headerAside}>
      {/* 쉬운 보기(24차 §3-4)는 제목(h1)을 사업 카드가 갖는다 — 불러오는 중 · 없음 · 오류는 두 보기가 같다. */}
      {(!simple || !result) && (
      <SectionHeader
        as="h1"
        eyebrow="기업마당 지원사업 · 신청"
        title={result ? result.program.title : "지원사업 신청 분석"}
        aside={
          <>
            <Badge
              color={COSMOS_COLORS.violet}
              glyph="◆"
              title="지원금·바우처를 신청하는 사업 — 공공조달 수주 흐름과 단계·용어가 다릅니다. 신청자격·필수조건·신청기간·제출서류를 원문 근거와 함께 정리합니다."
            >
              지원사업 · 신청
            </Badge>
            {/* 캐시를 받은 시각은 응답에 없다 — 분석 시각을 「조회 시각」으로 적으면 늘 방금 받은 것처럼 보였다 (27차 SUP-06). */}
            {source && result && (
              <span title={`기업마당 목록에서 읽었습니다 · 분석 시각 ${formatDateTime(result.generated_at)}`}>
                <SourceBadge kind={source.kind} label={source.label} />
              </span>
            )}
          </>
        }
      />
      )}

      {organizations.error && <InlineAlert tone="warn">{organizations.error}</InlineAlert>}

      {loading && <LoadingState label={`${currentName} 기준으로 지원사업 신청 분석을 불러오는 중`} rows={5} />}

      {!loading && fresh?.notFound && (
        <EmptyState title="현재 목록에 없는 지원사업입니다" tone="warn" action={backLinks}>
          기업마당 목록(실호출·캐시·샘플)에서 <span className="font-mono break-all">{programId}</span> 을(를) 찾지 못했습니다. 목록이 갱신되면서
          빠졌거나 사업 id가 바뀌었을 수 있습니다.
        </EmptyState>
      )}

      {!loading && fresh?.error && !fresh.notFound && (
        <>
          <InlineAlert tone="fail">{fresh.error}</InlineAlert>
          {backLinks}
        </>
      )}

      {/* 목록에서 빠진 사업(33차 §3-A-6 · 34차 R33-A1). 쉬운 보기는 그 안의 같은 줄 */}
      {result?.archived && !simple && (
        <InlineAlert tone="warn" role="status">
          <span data-support-archived>{result.archived_note}</span>
        </InlineAlert>
      )}

      {/* 쉬운 보기에도 되돌아가기 — 전체 보기와 같은 줄 (27차 LNK-11). */}
      {result && simple && (
        <SupportSimpleView
          result={result}
          organizationLabel={currentName}
          footer={
            <>
              {/* 44차 M4 — 신청 여부 결정(나라장터 참여 결정과 같은 꼴) */}
              <DecisionPanel targetId={programId} organizationId={organizationId} support />
              {backLinks}
            </>
          }
        />
      )}

      {result && !simple && (
        <>
          <ProgramHeader result={result} organizationLabel={currentName} nowMs={nowMs} />
          <div className="mt-3">
            <DecisionPanel targetId={programId} organizationId={organizationId} support />
          </div>

          {(result.unknown_count > 0 || !result.field_mapping_verified) && (
            <InlineAlert tone="warn" role="status">
              {/* 조항만 「공고문에서 못 찾은 조항」으로 센다 — 대시보드 지원사업 보기와 같은 함수 (SUP-07) */}
              {result.unknown_count > 0 && <>{supportUnknownBanner(result)} </>}
              {!result.field_mapping_verified && <>기업마당 자료의 항목을 아직 다 맞춰 보지 못했습니다. 금액·기간은 공고 원문에서 한 번 더 확인하세요.</>}
            </InlineAlert>
          )}

          <SupportStepBar stats={stats} active={step} onSelect={setStep} />

          <SupportPlanPanel step={step} plan={result.plan} attachments={result.program.attachments} programId={result.program_id} />
          <SupportEvidencePanel
            step={step}
            matches={result.evidence_matches}
            evidenceSummary={result.evidence_summary}
            outline={result.draft_outline}
            programId={result.program_id}
            organizationId={result.organization_id}
            checks={result.pre_submit_checks}
            organizationLabel={currentName}
          />

          {/* 아래 「n단계 →」는 새 단계의 머리로 올려 준다 — 긴 6단계 끝에서 누르면 바닥에 남았다 (27차 SUP-23). */}
          <SupportStepNav
            active={step}
            onSelect={(key) => {
              setStep(key);
              window.requestAnimationFrame(() => document.getElementById(supportSectionId(key))?.scrollIntoView({ block: "start" }));
            }}
          />

          {/* 2.4.0 ⑦ 공고문에 질문하기 — 단계 이동 아래 · 처음 펼칠 때만 원문 상태를 묻는다 */}
          <div className="mt-4 border-t border-cosmos-border pt-3">
            <NoticeQaPanel key={result.program_id} itemId={result.program_id} kind="support" />
          </div>

          {/* 마무리 — 「어디서 · 무엇을」까지(31차 §3-B · 제품 반영 안 1-2 · 세 화면 같은 글) */}
          <p className="text-[12.5px] leading-5 text-cosmos-secondary">
            <strong className="font-semibold text-cosmos-text">{SUPPORT_FINISH_LINES.slice(0, 2).join(" ")}</strong>{" "}
            {SUPPORT_FINISH_LINES.slice(2).join(" ")}
          </p>

          {backLinks}
        </>
      )}
    </AppShell>
  );
}


/**
 * 상단 개요 — 사업명(h1)은 위에 있고 여기서는 판단에 바로 필요한 것만 남긴다.
 * 뺀 정보(수행기관·지원분야·등록일·전체 요약·점수 산정 근거)는 지우지 않고 시트로 옮겼다.
 */
function ProgramHeader({
  result,
  organizationLabel,
  nowMs,
}: {
  result: SupportApplicationResult;
  organizationLabel: string;
  nowMs: number | null;
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [scoreOpen, setScoreOpen] = useState(false);
  // 닫기 손잡이를 고정한다 — 분마다 다시 그릴 때 새 함수가 가면 열린 시트의 포커스가 뒤로 빠졌다 (27차 SUP-27).
  const closeDetail = useCallback(() => setDetailOpen(false), []);
  const closeScore = useCallback(() => setScoreOpen(false), []);

  const program = result.program;
  /**
   * 회사 코드(저장·주소에 쓰는 영구 식별자)는 담당자가 읽을 말이 아니다 — 이름을 보이고 코드는 툴팁에 둔다.
   * 등록부를 못 읽어 이름을 모를 때만 코드를 쓰고, 그때는 「회사 코드」라고 불러 준다.
   * 근거 범위도 같은 이유로 원값(internal 등) 대신 라벨 사전을 거친다.
   */
  const organizationKnown = organizationLabel !== result.organization_id;
  const scopeLabel = EVIDENCE_SCOPE_LABELS[result.evidence_scope as EvidenceScope] ?? result.evidence_scope;
  // 실무 우선순위 회사는 「우선 검토 · 검토」 대신 목록 · 레이더와 같은 분류 칸(CLAUDE.md §12 · 2.0.6 통합 검토 cross-2)
  const practicalGroup = result.ranking_method === "practical" ? result.practical_group ?? null : null;
  const priorityTone = practicalGroup ? GROUP_TONE[practicalGroup] ?? "muted" : PRIORITY_TONE[result.priority_label];
  const score = result.company_priority_score;
  const totalItems = result.confirmed_count + result.unknown_count;
  const summary = program.summary ? plainText(program.summary) : null;
  const verdict = verdictOf(result.eligibility_gate, result.participation);
  // 풀리는 조건은 백엔드가 이미 준다(목록 카드와 같은 값 · SUP-09).
  const unlock = result.unlock_conditions ?? [];
  // 공고문에서 읽은 「받는 것·부담」(1단계). 있으면 개요 시트의 「지원 규모 미확인」 문장을 바꾼다 (27차 SUP-02).
  const money = result.plan.eligibility.find((item) => item.key === "clause_money" && item.status === "confirmed" && item.value);

  // apply_end 는 날짜만(YYYY-MM-DD) 온다. 그대로 파싱하면 UTC 자정(=KST 09:00)으로 읽혀
  // 마감 당일 오전부터 「마감」으로 바뀐다. 백엔드와 같은 23:59 KST 로 맞춘다.
  const applyEndAt = normalizeApplyEnd(program.apply_end);
  // D-day 문구는 대시보드·목록·레이더와 **같은 함수**로 만든다 (lib/deadline.dDayText).
  // 상시·예산 소진 접수는 남은 일수를 세지 않고 그 사실을 적는다.
  const deadlineValue = dDayText({
    deadline: applyEndAt,
    periodKind: program.apply_period_kind,
    nowMs,
  });
  // 이름은 목록 · 레이더 · 지도 카드와 같은 `deadlineTerm` 이 고른다 — 「신청 마감」 칸 안에 「접수 마감 …」이
  // 겹쳐 적히고 지난 사업에도 「마감」이 붙었다 (27차 UNI-21). 마감 여부는 백엔드 판정(supportVocabulary 와 같다).
  const deadlineLabel = deadlineTerm({
    source: "bizinfo",
    closed: result.priority_label === "마감",
    periodKind: program.apply_period_kind,
    deadline: applyEndAt,
  });
  const deadlineHint = program.apply_end
    ? formatDeadlineDate(program.apply_end)
    : (program.apply_period_text ?? "신청기간 원문 확인 필요");

  return (
    <Panel ariaLabel="지원사업 개요">
      {result.eligibility_gate === "FAIL" && result.gate_reason ? (
        <div className="mb-3 rounded-lg border border-cosmos-red/45 bg-cosmos-red/10 px-3 py-2.5" role="alert">
          <p className="text-[12.5px] font-semibold text-cosmos-red">지금은 신청할 수 없습니다 — 신청자격부터 확인하세요</p>
          <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{result.gate_reason}</p>
          {/* 조치는 막는 조항마다 다르다 — 지역 예외 증빙 한 줄로 고정하지 않는다 (27차 SUP-09). */}
          <p className="mt-1 text-[12px] text-cosmos-muted">
            {unlock.length > 0
              ? `이것이 확인되면 신청할 수 있습니다: ${unlock.join(" · ")} — 확인 전에는 사업계획서를 쓰지 마세요.`
              : "막는 조항이 풀리기 전에는 사업계획서 작성을 시작하지 마세요."}
          </p>
        </div>
      ) : (
        // 「신청할 수 있나요?」 — 쉬운 보기와 같은 판정 알약 · 사유 (27차 SUP-08). 불가는 위 상자가 말한다.
        <div className="mb-3 flex min-w-0 flex-col gap-1" data-support-verdict={result.eligibility_gate ?? "none"}>
          <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-cosmos-secondary">
            <span className="font-semibold text-cosmos-text">신청할 수 있나요?</span>
            <Badge tone={verdict.tone} glyph title={verdict.title}>
              {verdict.label}
            </Badge>
            {result.gate_reason && <span className="min-w-0 break-words">{result.gate_reason}</span>}
          </p>
          {result.company_meaning && (
            <p className="min-w-0 break-words text-[12.5px] text-cosmos-secondary">
              <span className="text-cosmos-muted">우리 회사 입장에서 </span>
              {result.company_meaning}
            </p>
          )}
        </div>
      )}
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px]">
        <span className="min-w-0 break-words text-cosmos-secondary">
          <span className="text-cosmos-muted">주관 기관 </span>
          {program.agency}
        </span>
        {/* 줄 오른쪽 끝에 붙이고 왼쪽으로 연다 — 390 에서 기관명 뒤에 붙으면 창 오른쪽 밖으로 열렸다 (27차 SUP-24). */}
        <span className="ml-auto">
        <Popover
          trigger={
            <>
              <span aria-hidden="true">◈</span>
              분석 기준 · {organizationLabel}
            </>
          }
          triggerLabel={`분석 기준 회사 ${organizationLabel} — 기준과 분석 정보 보기`}
          title="이 분석의 기준"
          align="end"
          width="320px"
        >
          <p>
            이 분석은 현재 회사 <strong className="text-cosmos-text">{organizationLabel}</strong> 기준입니다. 회사를 바꾸면 그 회사의 프로필과 승인
            자료로 다시 계산하며, 여러 회사의 결과를 섞지 않습니다.
          </p>
          <p className="text-cosmos-muted">{result.note}</p>
          <p className="text-[12px] leading-4 text-cosmos-muted">
            분석 시각 {formatDateTime(result.generated_at)} ·{" "}
            {organizationKnown ? (
              <>
                회사 <span title={`회사 코드 ${result.organization_id}`}>{organizationLabel}</span>
              </>
            ) : (
              <>
                회사 코드 <span className="font-mono">{result.organization_id}</span>
              </>
            )}{" "}
            · 근거 범위 <span title={`근거 범위 코드 ${result.evidence_scope}`}>{scopeLabel}</span>
          </p>
        </Popover>
        </span>
      </div>

      {summary && (
        <p className="mt-2 line-clamp-2 whitespace-pre-line break-words text-[12.5px] leading-5 text-cosmos-secondary sm:line-clamp-3">
          {summary}
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <button type="button" className={CHIP_BUTTON} onClick={() => setDetailOpen(true)} aria-haspopup="dialog">
          <span aria-hidden="true">＋</span>
          개요 자세히
        </button>
        {program.url && (
          <a href={program.url} target="_blank" rel="noreferrer noopener" className={LINK_BUTTON}>
            기업마당 공고 원문<span aria-hidden="true"> ↗</span>
          </a>
        )}
        {program.reception_url && (
          <a href={program.reception_url} target="_blank" rel="noreferrer noopener" className={LINK_BUTTON}>
            접수처 바로가기<span aria-hidden="true"> ↗</span>
          </a>
        )}
      </div>

      <section aria-label="신청 분석 요약" className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="회사 기준 검토 우선순위"
          value={score === null ? UNSCORED : score}
          // 1024 세 칸에서 잘리지 않게 짧게 — 「자격 우선 확인」은 위 불가 상자가 말한다 (27차 SUP-25).
          hint={`${result.eligibility_gate === "FAIL" ? "불가" : practicalGroup ?? result.priority_label} · 검토 순서(선정확률 아님)`}
          tone={result.eligibility_gate === "FAIL" ? "fail" : score === null ? "muted" : priorityTone}
          ratio={score === null ? null : score / 100}
          badge={<SourceBadge kind="rule" label="규칙 계산" />}
        />
        <KpiCard
          label={deadlineLabel}
          value={deadlineValue}
          hint={deadlineHint}
          tone={program.apply_end ? "info" : "muted"}
          badge={<SourceBadge kind="computed" label="접수 기간" />}
        />
        <KpiCard
          // 7단계 「점검 줄」과 다른 것을 센다 — 이름을 갈랐다 (27차 SUP-26). 값은 규칙이 원문과 대조해 센 수다 (SUP-10).
          label="직접 확인할 조건"
          value={result.unknown_count}
          unit="건"
          hint={`신청 조건 ${totalItems}건 중 공고 원문에서 확인한 것 ${result.confirmed_count}건`}
          tone={result.unknown_count > 0 ? "warn" : "pass"}
          badge={<SourceBadge kind="rule" label="원문 대조" />}
        />
      </section>

      <div className="mt-2.5">
        <button type="button" className={CHIP_BUTTON} onClick={() => setScoreOpen(true)} aria-haspopup="dialog">
          <span aria-hidden="true">＋</span>
          점수 계산 내역 · {result.score_components.length}개 항목
        </button>
      </div>

      <Sheet
        open={detailOpen}
        onClose={closeDetail}
        title="사업 개요 자세히"
        description="기업마당 목록 원문에 있는 값만 그대로 옮긴 것입니다."
        width="420px"
      >
        <dl className="flex flex-col">
          <DetailRow label="주관 기관" value={program.agency} />
          <DetailRow label="수행 기관" value={program.executing_agency} />
          <DetailRow label="지원 분야" value={[program.category, program.subcategory].filter(Boolean).join(" · ") || null} />
          <DetailRow label="지원 대상" value={program.target} />
          <DetailRow label="신청기간 원문" value={program.apply_period_text} />
          <DetailRow
            label="등록 · 수정"
            value={`${formatDate(program.created_at)}${program.updated_at ? ` · ${formatDate(program.updated_at)}` : ""}`}
          />
        </dl>
        {summary && (
          <div className="mt-3 border-t border-cosmos-border pt-3">
            <p className="text-[12px] font-semibold text-cosmos-text">사업 개요 (원문)</p>
            <p className="mt-1.5 whitespace-pre-line break-words text-[12.5px] leading-5 text-cosmos-secondary">{summary}</p>
          </div>
        )}
        <p className="mt-3 text-[12px] leading-4 text-cosmos-muted">
          {money ? (
            <>
              지원 규모는 공고문에서 읽었습니다 — <strong className="text-cosmos-text">{money.value}</strong> (1단계 「{money.label}」).
            </>
          ) : (
            <>
              지원 규모는 {result.document_read ? "공고문에서 찾지 못했습니다" : "기업마당 목록 정보에 없습니다"} — 0원이 아니라{" "}
              <strong className="text-cosmos-amber">미확인</strong>입니다. 공고 원문에서 확인하세요.
            </>
          )}
        </p>
      </Sheet>

      <Sheet
        open={scoreOpen}
        onClose={closeScore}
        title="회사 기준 검토 우선순위 산출 근거"
        description="신청 순서를 정하기 위한 값입니다. 선정 여부·성공 가능성을 뜻하지 않습니다."
        width="440px"
      >
        <p className="text-[12px] leading-5 text-cosmos-secondary">
          배점의 합은 100입니다. 계산할 수 없는 항목은 <strong className="text-cosmos-amber">미확인</strong>이며 0점이 아닙니다.
        </p>
        <ul className="mt-2 flex flex-col">
          {result.score_components.map((component) => (
            <li key={component.key} className="border-t border-cosmos-border py-2.5 first:border-t-0 first:pt-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[12.5px] font-semibold text-cosmos-text">{component.label}</span>
                <span className="font-mono text-[12px] text-cosmos-muted">만점 {component.weight}</span>
                <Badge tone={component.score === null ? "warn" : "info"} mono glyph>
                  {component.score === null ? "미확인" : formatPercent(component.score)}
                </Badge>
              </div>
              <p className="mt-1 min-w-0 break-words text-[12px] leading-5 text-cosmos-secondary">{component.reason}</p>
            </li>
          ))}
        </ul>

        {result.reasons.length > 0 && (
          <div className="mt-3 border-t border-cosmos-border pt-3">
            <p className="text-[12px] font-semibold text-cosmos-text">회사와 연결된 이유</p>
            {/* 긴 이유(사업영역 세 개 나열)가 줄바꿈 없는 배지로 시트 폭을 넘었다 — 글 줄로 (27차 SUP-28). */}
            <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 text-[12px] leading-5 text-cosmos-secondary">
              {result.reasons.map((reason) => (
                <li key={reason} className="min-w-0 break-words">
                  {reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-3 border-t border-cosmos-border pt-3">
          <p className="text-[12px] font-semibold text-cosmos-text">
            기업마당 원본 축 · 지원 적합도{" "}
            <span className="font-mono text-cosmos-secondary">
              {result.support_fit.label} {formatPercent(result.support_fit.score)}
            </span>
          </p>
          <p className="mt-1 text-[12px] leading-4 text-cosmos-muted">
            판정 방식 <span title={result.support_fit.method}>{FIT_METHOD_LABELS[result.support_fit.method] ?? result.support_fit.method}</span> ·{" "}
            {result.support_fit.note}
          </p>
          <p className="mt-1 text-[12px] leading-4 text-cosmos-muted">
            이 값도 <strong className="text-cosmos-amber">선정확률·성공확률이 아닙니다</strong> — 회사 프로필과 공고 문구가 얼마나 겹치는지를
            {/* 의미 매칭을 켠 서버에서는 규칙이 아니다 (27차 SUP-29). */}
            {result.support_fit.method === "keyword_rule" ? " 규칙으로 센 것입니다." : " AI 의미 매칭으로 잰 것입니다."}
          </p>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-cosmos-border pt-3">
          <Badge tone="muted" title="점수를 계산할 근거가 얼마나 확인됐는지">
            {CONFIDENCE_LABELS[result.confidence]}
          </Badge>
          <Badge
            tone={result.field_mapping_verified ? "pass" : "warn"}
            glyph
            title="기업마당 자료의 항목을 실제 응답과 맞춰 봤는지"
          >
            {result.field_mapping_verified ? "값 점검 완료" : "값 점검 전"}
          </Badge>
        </div>
      </Sheet>
    </Panel>
  );
}

function DetailRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex min-w-0 gap-2 border-t border-cosmos-border py-2 first:border-t-0 first:pt-0">
      <dt className="w-[92px] shrink-0 text-[12px] text-cosmos-muted">{label}</dt>
      <dd className="min-w-0 break-words text-[12.5px] leading-5 text-cosmos-text">
        {value ?? <span className="text-cosmos-amber">원문 확인 필요</span>}
      </dd>
    </div>
  );
}
