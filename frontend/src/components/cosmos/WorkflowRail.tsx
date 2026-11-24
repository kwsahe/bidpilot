"use client";

/**
 * 좌측 워크플로 레일(8단계). 1024px 미만에서는 상단 가로 칩으로 바뀐다.
 * 클릭하면 Shell이 stage·카메라·선택 노드을 바꾼다.
 * 상태는 색 + 글리프 + 텍스트로 함께 전달한다 (완료 / 진행 중 / 확인 필요 / 실패 / 대기).
 */

import type { WorkflowStage, WorkflowStepView } from "@/lib/cosmos/graph";
import { isStepSettled } from "@/lib/cosmos/graph";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import { withAlpha } from "@/lib/cosmos/theme";

export interface WorkflowRailProps {
  steps: WorkflowStepView[];
  /** 현재 보고 있는 단계 (등장 애니메이션·발표 모드가 조절) */
  stage: WorkflowStage;
  onStepClick: (step: WorkflowStepView) => void;
  reducedMotion: boolean;
  /** 실제 backend 요청이 진행 중인 단계 (실행 타임라인과 연결) */
  runningStages?: ReadonlySet<WorkflowStage>;
  /** 데스크톱에서 번호만 남기고 접기 (3D 가로 공간 확보) */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

// 상태 기호 사전은 lib 로 옮겼다 — 지도 · 범례 · 쉬운 보기가 같이 읽는다(27차 §3-D-2). 옛 import 는 그대로 된다.
export { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";

export default function WorkflowRail({
  steps,
  stage,
  onStepClick,
  reducedMotion,
  runningStages,
  collapsed = false,
  onToggleCollapsed,
}: WorkflowRailProps) {
  /**
   * 「끝난 단계」의 정의는 graph.ts 의 진행률과 **같은 함수**여야 한다.
   * 여기서 따로 세면 반드시 어긋난다 — 실제로 어긋났었다: 레일이 done+attention 을,
   * 진행률이 done+failed 를 세서 같은 화면에 「7/8」과 「38%」가 나란히 떴다.
   * 그래서 조건을 복사해 오지 않고 isStepSettled 를 부른다.
   */
  const done = steps.filter(isStepSettled).length;
  return (
    <nav
      aria-label="분석 워크플로 (8단계)"
      data-tour="rail"
      className={`mc-panel flex w-full min-w-0 shrink-0 flex-col gap-2 p-2 lg:overflow-y-auto lg:overflow-x-hidden ${
        collapsed ? "lg:w-[64px] lg:p-2" : "lg:w-[236px] lg:p-3"
      }`}
    >
      <div className={`hidden items-center gap-1 px-1 lg:flex ${collapsed ? "flex-col" : "justify-between"}`}>
        {!collapsed && (
          <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted" title="실제 분석 업무 흐름 — 지도의 정거장 8개와 같다 (지도 아래 5단계 안내와 별개)">
            분석 업무 흐름
          </p>
        )}
        <p
          className="font-mono text-[12px] tabular-nums text-cosmos-muted"
          title="진행 현황 — 저장된 결과로 실제 끝난 단계 수입니다. 화면에서 열어 본 단계와는 다릅니다."
        >
          <span className="sr-only">진행 현황 </span>
          {done}/{steps.length}
        </p>
        {onToggleCollapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "워크플로 레일 펼치기" : "워크플로 레일 접기"}
            className="mc-focus flex h-6 w-6 items-center justify-center rounded-md text-[12px] text-cosmos-muted hover:bg-cosmos-elevated hover:text-cosmos-text"
          >
            {collapsed ? "»" : "«"}
          </button>
        )}
      </div>
      {/* 모바일에서는 가로 스크롤 대신 줄바꿈해 모든 단계가 화면 안에서 읽히게 한다.
          lg 이상은 세로 타임라인. */}
      <ol className="relative flex min-w-0 flex-1 flex-wrap gap-1.5 lg:flex-col lg:flex-nowrap lg:gap-1">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-5 left-[21px] top-5 hidden w-px bg-cosmos-border lg:block"
        />
        {steps.map((step) => {
          const meta = STEP_STATUS_META[step.status];
          const current = step.id === stage;
          const revealed = step.id <= stage;
          const running = runningStages?.has(step.id) ?? false;
          const pulse = (step.status === "active" || running) && !reducedMotion;
          return (
            <li key={step.id} className="relative min-w-0 shrink lg:w-full lg:shrink-0">
              <button
                type="button"
                onClick={() => onStepClick(step)}
                data-tour={`rail-step-${step.id}`}
                aria-current={current ? "step" : undefined}
                aria-label={`${step.id}단계 ${step.label} — ${running ? "실행 중" : meta.label}. ${step.summary}`}
                title={collapsed ? `${step.id}. ${step.label} — ${running ? "실행 중" : meta.label}` : undefined}
                className={`mc-focus flex min-h-10 w-full items-center gap-2.5 rounded-lg border px-2 py-1.5 text-left transition-colors lg:gap-3 lg:py-2 ${collapsed ? "lg:justify-center lg:px-1" : ""} ${
                  current
                    ? "border-cosmos-border-strong bg-cosmos-elevated shadow-[inset_2px_0_0_var(--cosmos-cyan)]"
                    : "border-transparent hover:border-cosmos-border hover:bg-cosmos-elevated/60"
                } ${revealed ? "opacity-100" : "opacity-55"}`}
              >
                <span
                  aria-hidden="true"
                  className="relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[12px] font-bold"
                  style={{
                    color: meta.color,
                    borderColor: withAlpha(meta.color, 47),
                    backgroundColor: current ? withAlpha(meta.color, 20) : withAlpha(meta.color, 10),
                    animation: pulse ? "mc-pulse-ring 2.4s ease-in-out infinite" : undefined,
                  }}
                >
                  {running ? (
                    <span
                      className="h-3 w-3 rounded-full border-2 border-current border-t-transparent"
                      style={{ animation: reducedMotion ? undefined : "mc-spin 0.9s linear infinite" }}
                    />
                  ) : (
                    meta.glyph
                  )}
                </span>
                <span className={`min-w-0 flex-1 ${collapsed ? "lg:hidden" : ""}`}>
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-mono text-[12px] tabular-nums text-cosmos-muted">{step.id}</span>
                    <span className={`truncate text-[13px] font-medium ${current ? "text-cosmos-text" : "text-cosmos-text/90"}`}>
                      {step.label}
                    </span>
                  </span>
                  <span className="hidden truncate text-[12px] text-cosmos-secondary lg:block">{step.summary}</span>
                </span>
                <span
                  className={`hidden shrink-0 rounded-full border px-1.5 py-px text-[12px] font-medium ${collapsed ? "" : "lg:inline"}`}
                  style={{ color: meta.color, borderColor: withAlpha(meta.color, 33) }}
                >
                  {running ? "실행 중" : meta.label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
