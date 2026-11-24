"use client";

/**
 * 지원사업 **신청** 분석 7단계 진행 바.
 *
 * 입찰(Mission Control)의 단계와 1:1 대응하지 않는다 — 용어가 다르다.
 * 단계 정의는 `SUPPORT_STEPS`(types/opportunity.ts)가 단일 출처이며 여기서 다시 만들지 않는다.
 *
 * 정보량 규칙
 * - 얇은 진행 바다. 단계마다 설명 문장을 늘어놓지 않는다(설명은 title 툴팁과 본문 단계 설명에 있다).
 * - **현재 단계 하나만** 강조하고, 본문에도 그 단계의 내용만 보인다.
 * - 확인/미확인 건수는 작은 숫자로만 (색만으로 구분하지 않도록 ✓ · ! 글리프를 함께 쓴다).
 */

import { tintStyle } from "@/lib/cosmos/format";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { SUPPORT_STEPS, type SupportStepKey } from "@/types/opportunity";

/** 단계 섹션 id — 진행 바(aria-controls)와 본문 섹션이 같은 규칙을 쓴다. */
export function supportSectionId(key: SupportStepKey): string {
  return `support-${key}`;
}

/**
 * 단계 절의 scroll-margin — 고정 머리 아래에 절 머리(「신청 분석」 · 제목)가 오게.
 * 머리 높이 실측: 640 미만 181px · 640~1023 최대 143px · 1024 이상 최대 101px (27차 SUP-23 — scroll-mt-24 는 390 에서 가렸다).
 */
export const SUPPORT_SECTION_SCROLL_MT = "scroll-mt-52 sm:scroll-mt-40 lg:scroll-mt-28";

/** 단계별 건수. done=원문에서 확인된 것, pending=담당자가 확인해야 하는 것. */
export interface SupportStepStat {
  key: SupportStepKey;
  done: number;
  pending: number;
  /** 공고문을 읽었는데 그 갈래 조항이 없던 줄(43차 N10) — 「확인 필요」로 세지 않는다. */
  absent?: number;
}

export default function SupportStepBar({
  stats,
  active,
  onSelect,
}: {
  stats: SupportStepStat[];
  active: SupportStepKey;
  onSelect: (key: SupportStepKey) => void;
}) {
  const byKey = new Map(stats.map((stat) => [stat.key, stat]));

  return (
    <nav aria-label="지원사업 신청 분석 단계" className="min-w-0">
      <ol className="mc-scroll flex snap-x items-stretch gap-1 overflow-x-auto pb-1 sm:grid sm:grid-cols-4 sm:gap-1.5 sm:overflow-visible sm:pb-0 lg:grid-cols-7">
        {SUPPORT_STEPS.map((step, index) => {
          const stat = byKey.get(step.key);
          const current = step.key === active;
          const counts: string[] = [];
          if (stat && stat.done > 0) counts.push(`확인 ${stat.done}`);
          if (stat && stat.pending > 0) counts.push(`남음 ${stat.pending}`);
          if (stat?.absent) counts.push(`조항 없음 ${stat.absent}`);
          const countLabel =
            stat === undefined
              ? ""
              : ` — 확인 ${stat.done}건, 확인 필요 ${stat.pending}건${stat.absent ? `, 공고문에 조항 없음 ${stat.absent}건` : ""}`;

          return (
            <li key={step.key} className="min-w-[118px] shrink-0 snap-start sm:min-w-0">
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                // 본문에는 고른 단계 하나만 있다 — 없는 id 를 가리키지 않게 지금 단계에만 (27차 SUP-32).
                aria-controls={current ? supportSectionId(step.key) : undefined}
                title={`${index + 1}단계 ${step.label} — ${step.hint}${countLabel}`}
                onClick={() => onSelect(step.key)}
                // relative — 안의 sr-only(절대 위치)가 가로 스크롤 줄 밖 문서 폭을 늘리지 않게(390 에서 755px 가 됐다).
                className={`mc-focus relative flex h-full w-full min-w-0 flex-col gap-0.5 rounded-lg border px-2.5 py-1.5 text-left transition-colors ${
                  current
                    ? "shadow-[0_0_16px_color-mix(in_srgb,var(--cosmos-violet)_22%,transparent)]"
                    : "border-transparent hover:border-cosmos-border hover:bg-cosmos-elevated/50"
                }`}
                style={current ? tintStyle(COSMOS_COLORS.violet) : undefined}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <span
                    aria-hidden="true"
                    className={`shrink-0 font-mono text-[12px] leading-none ${current ? "" : "text-cosmos-muted"}`}
                  >
                    {index + 1}
                  </span>
                  <span
                    className={`truncate text-[12.5px] font-semibold leading-5 ${
                      current ? "" : "text-cosmos-secondary"
                    }`}
                  >
                    {step.label}
                  </span>
                </span>
                {counts.length > 0 && (
                  <span
                    aria-hidden="true"
                    className={`font-mono text-[12px] leading-4 ${current ? "opacity-80" : "text-cosmos-muted"}`}
                  >
                    {counts.join(" ")}
                  </span>
                )}
                {/* ✓ · ! 는 보이는 글자일 뿐 — 화면 읽기 프로그램에는 말로 (27차 SUP-32). */}
                {stat && (stat.done > 0 || stat.pending > 0) && (
                  <span className="sr-only">
                    {` 확인 ${stat.done}건, 확인 필요 ${stat.pending}건`}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** 단계 사이 이동 — 숨긴 단계로 돌아갈 자리를 본문 아래에도 둔다. */
export function SupportStepNav({
  active,
  onSelect,
}: {
  active: SupportStepKey;
  onSelect: (key: SupportStepKey) => void;
}) {
  const index = SUPPORT_STEPS.findIndex((step) => step.key === active);
  const prev = index > 0 ? SUPPORT_STEPS[index - 1] : null;
  const next = index >= 0 && index < SUPPORT_STEPS.length - 1 ? SUPPORT_STEPS[index + 1] : null;
  const linkClass =
    "mc-focus inline-flex min-h-9 max-w-full items-center gap-1.5 rounded-lg border border-cosmos-border bg-cosmos-panel px-3 py-1.5 text-[12.5px] font-semibold text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text";

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      {prev ? (
        <button type="button" className={linkClass} onClick={() => onSelect(prev.key)}>
          <span aria-hidden="true">←</span>
          <span className="truncate">{index}단계 {prev.label}</span>
        </button>
      ) : (
        <span />
      )}
      {next && (
        <button type="button" className={linkClass} onClick={() => onSelect(next.key)}>
          <span className="truncate">{index + 2}단계 {next.label}</span>
          <span aria-hidden="true">→</span>
        </button>
      )}
    </div>
  );
}
