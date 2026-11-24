"use client";

/**
 * 대시보드 맨 위 — 「지금 무엇을 해야 하는가」.
 *
 * 첫 화면에 조작과 정보가 너무 많았다. 3D/2D/목록 전환, 화면 초기화, 핵심 흐름, 제품 설명,
 * 재분석, 발표 모드, 상세 튜토리얼, 5개 요약 지표, 8단계 레일, 별도 5단계 설명, 3D 화면,
 * 상세 패널, 조건·체크리스트·위험·최종 결정이 한 화면에 동시에 있었다.
 * 처음 온 직원이 「그래서 뭘 눌러야 하나」를 알아내는 데 시간이 걸린다.
 *
 * **기능은 하나도 없애지 않는다.** 위에 답을 먼저 놓을 뿐이다.
 * 값은 전부 lib/cosmos/mission.ts 가 이미 계산하던 것을 그대로 쓴다 —
 * riskSummary(마감·필수조건 경고)와 nextActions(가장 먼저 해야 할 행동).
 * 새 계산 규칙을 만들지 않는다. 새로 만들면 아래 지표와 말이 갈린다.
 */

import Link from "next/link";

import { Badge, Button } from "@/components/ui/primitives";
import { currentStep, type CosmosGraph, type WorkflowStage } from "@/lib/cosmos/graph";
import { nextActions, riskSummary, type NextActionKind } from "@/lib/cosmos/mission";
import { TONE_COLORS } from "@/lib/cosmos/theme";
import { SCREEN_NAMES } from "@/lib/terms";

export interface TodayPanelProps {
  graph: CosmosGraph;
  nowMs: number | null;
  onNavigate: (stage: WorkflowStage, nodeId: string | null) => void;
  /**
   * 「제안서 새 버전 만들기」를 눌렀을 때 **실제로 생성한다.**
   *
   * 예전에는 이 주 버튼이 `onNavigate` 에 묶여 있어서 제안서 노드로 이동해
   * *기존 구버전 초안*을 보여줄 뿐이었다. 생성 요청은 나가지 않았다.
   * 담당자는 「눌렀는데 왜 그대로지? 만들어진 건가?」로 읽는다.
   */
  onGenerateProposal: () => void;
  /** 생성이 진행 중인가. 눌린 뒤 아무 일도 안 일어나는 것처럼 보이지 않게 한다. */
  generating: boolean;
  /** 「사업기회 목록 →」 — 목록 화면으로. */
  opportunitiesHref: string;
  /** 첫 줄이 「제안요청서 파싱」이면 그 자리에서 상단 「공고 분석 시작」과 같은 일을 한다 (DSH-09). */
  onAnalyze?: () => void;
  analyzing?: boolean;
}

/** 한 화면에 보여줄 경고 개수. 나머지는 아래 상세 패널에 그대로 있다.
 *
 * 3 → 2. 요구사항 변경 배너가 붙으면서 이 블록이 254px 까지 커져 3D 를 아래로
 * 밀어냈다. 맨 위는 «가장 급한 것»만 보이면 되고, 나머지는 상세 패널에서 본다. */
const RISK_LIMIT = 2;

/** 「다음」 배지 색 — 위험 줄을 대신하면 그 위험의 색을 이어받는다(참가 불가·막는 조건은 붉게) (22차 검토). */
const NEXT_TONE: Partial<Record<NextActionKind, "fail" | "warn">> = {
  eligibility_fail: "fail",
  blockers: "fail",
  clauses: "warn",
  regenerate_proposal: "warn",
};

/** 「다음」 행동과 같은 말을 하는 위험 항목 (mission.ts 의 같은 문구). */
const RISK_OF_ACTION: Partial<Record<NextActionKind, string>> = {
  eligibility_fail: "eligibility-fail",
  clauses: "eligibility-check",
  blockers: "conditions-blocker",
};

export default function TodayPanel({
  graph,
  nowMs,
  onNavigate,
  opportunitiesHref,
  onGenerateProposal,
  generating,
  onAnalyze,
  analyzing = false,
}: TodayPanelProps) {
  const actions = nextActions(graph);
  const first = actions[0] ?? null;
  // 「다음」 줄이 이미 말하는 참가자격·조건 차단은 위험 줄에서 빼 한 번만 적는다 (22차 — 같은 문구가 두 번 나왔다).
  const sameAsNext = first ? RISK_OF_ACTION[first.kind] : undefined;
  const risks = riskSummary(graph, nowMs)
    .filter((risk) => risk.id !== sameAsNext)
    .slice(0, RISK_LIMIT);
  // 맨 위에는 순차 진행 단계가 아니라 사용자가 지금 먼저 처리할 조치를 보여준다.
  const step = first ? graph.steps.find((candidate) => candidate.id === first.stage) ?? currentStep(graph.steps) : currentStep(graph.steps);
  const readiness = graph.source.analysis.readiness;
  const stale = readiness && readiness.blockers.includes("stale_requirements") ? readiness : null;

  return (
    <section
      className="mc-panel flex flex-col gap-2.5 p-3 sm:px-4"
      aria-label="지금 할 일"
      data-tour="today"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">
          지금 할 일
        </h2>
        {/* 다음 할 일 — 진행 현황(완료 수)·현재 보는 단계와 **다른 말**이다.
            낮은 진행 현황과 뒤 단계 조치가 함께 보여도 모순으로 읽히지 않게 이름을 분리했다. */}
        <p className="min-w-0 truncate text-[12px] text-cosmos-secondary">
          다음 할 일 · <span className="font-medium text-cosmos-text">{step.id}. {step.label}</span>
          <span className="text-cosmos-muted"> — {step.summary}</span>
        </p>
      </div>

      {/* 초안이 이전 요구사항 집합 기준이면 **가장 먼저** 말한다.
          이것을 말하지 않으면 아래 Coverage·위험 숫자가 다른 기준끼리 견준 값인데도
          「지금 초안의 결함」으로 읽힌다. */}
      {stale && (
        <div
          className="rounded-md border border-cosmos-amber/40 bg-cosmos-amber/10 px-3 py-2"
          role="status"
          aria-label="요구사항 변경 알림"
        >
          <p className="text-[12.5px] font-medium text-cosmos-text">
            {stale.message}
            <span className="ml-1 font-normal text-cosmos-muted">
              일반 검사는 실행하지 않았습니다.
            </span>
          </p>
          {stale.actions.length > 0 && (
            <p className="mt-0.5 text-[12px] text-cosmos-muted">
              할 수 있는 것: {stale.actions.map((a) => a.label).join(" · ")}
            </p>
          )}

        </div>
      )}

      {/* 마감·필수조건 경고 — 있을 때만. 없으면 자리를 차지하지 않는다. */}
      {risks.length > 0 && (
        <ul className="flex flex-col gap-1.5" aria-label="확인이 필요한 것">
          {risks.map((risk) => (
            <li key={risk.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: TONE_COLORS[risk.tone] }}
              />
              <button
                type="button"
                onClick={() => onNavigate(risk.stage, risk.nodeId)}
                className="mc-focus min-w-0 rounded text-left text-[12.5px] font-medium text-cosmos-text hover:underline"
              >
                {risk.label}
              </button>
              <span className="min-w-0 flex-1 truncate text-[12px] text-cosmos-muted">{risk.detail}</span>
            </li>
          ))}
        </ul>
      )}

      {/* 가장 먼저 해야 할 행동 + 대표 버튼 둘 */}
      <div className="flex flex-wrap items-center gap-2">
        {first ? (
          <>
            <Badge tone={NEXT_TONE[first.kind] ?? "info"}>다음</Badge>
            <span className="min-w-0 flex-1 truncate text-[12.5px] text-cosmos-secondary">
              <span className="font-medium text-cosmos-text">{first.label}</span> — {first.detail}
            </span>
            {/*
              라벨이 「만들기」면 실제로 만든다. 이동만 한다면 그렇게 적는다 —
              버튼의 말과 하는 일이 다르면 담당자는 결과를 믿을 수 없다.
            */}
            {first.kind === "regenerate_proposal" ? (
              <Button
                size="sm"
                variant="primary"
                disabled={generating}
                onClick={() => {
                  onNavigate(first.stage, first.nodeId);
                  onGenerateProposal();
                }}
              >
                {generating ? "만드는 중…" : "제안서 새 버전 만들기"}
              </Button>
            ) : first.kind === "parse" && onAnalyze ? (
              <Button size="sm" variant="primary" disabled={analyzing} onClick={onAnalyze}>
                {analyzing ? "분석 중…" : "공고 분석 시작"}
              </Button>
            ) : (
              // 이동만 하는 단추는 이동한다고 적는다 — 「진행 중인 분석 계속하기」는 분석을 이어 돌리는 것처럼 읽혔다 (DSH-09).
              <Button size="sm" variant="primary" onClick={() => onNavigate(first.stage, first.nodeId)}>
                {first.stage}단계로 이동
              </Button>
            )}
          </>
        ) : (
          <span className="min-w-0 flex-1 text-[12.5px] text-cosmos-secondary">
            이 공고에서 실행할 단계가 남아 있지 않습니다. 아래에서 최종 결정을 남기세요.
          </span>
        )}
        <Link
          href={opportunitiesHref}
          className="mc-focus rounded-md border border-cosmos-border px-2.5 py-1 text-[12px] font-medium text-cosmos-secondary transition-colors hover:bg-cosmos-elevated"
        >
          {SCREEN_NAMES.opportunities} 목록 →
        </Link>
      </div>
    </section>
  );
}
