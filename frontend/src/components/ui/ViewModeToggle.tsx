"use client";

/**
 * 「쉬운 보기 ⇄ 전체 보기」 토글 (24차 · prompt_14 §3-1).
 *
 * 쉬운 보기가 있는 세 화면(대시보드 · 사업기회 목록 · 지원사업 신청 분석)의 머리에만 둔다 — 공통 머리(메뉴 · 세션 · 「?」)에는 넣지 않는다.
 * `ViewModeSwitch` 는 저장소를 바로 쓰는 판(AppShell `headerAside` 용), 대시보드는 안내 중 임시 전체 보기가 있어 `ViewModeToggle` 에 제 손잡이를 넘긴다.
 */

import { useId } from "react";

import { setDisplayMode, useDisplayMode, type DisplayMode } from "@/lib/viewMode";

export type ViewTitles = Record<DisplayMode, string>;

const OPTIONS: Array<{ mode: DisplayMode; label: string }> = [
  { mode: "simple", label: "쉬운 보기" },
  { mode: "full", label: "전체 보기" },
];

/**
 * 도움말은 화면마다 — 부르는 쪽이 `titles` 로 넘긴다. 주소로 짐작하면 대시보드 안 지원사업(`/analysis?support=`)에
 * 입찰의 「지금 할 일 · 지도 · 레일」을 약속했다 (OPP-19 · SUP-33 · EZ-35). 넘기지 않으면 대시보드 말.
 */
const DASHBOARD_VIEW_TITLES: ViewTitles = {
  simple: "한 열로 — 공고 · 참가 판정 · 지금 할 일 · 진행 단계 · 결정만",
  full: "지금까지의 전체 화면 — 지도 · KPI · 레일 · 안내 메뉴까지",
};
export const OPPORTUNITIES_VIEW_TITLES: ViewTitles = {
  simple: "한 줄 목록 — 탭 · 검색 · 「더 보기」 메뉴 하나",
  full: "카드 목록 — 필터 · 정렬 · 자료 상태 · 점수 산정 근거까지",
};
/** 지원사업 — 신청 분석 화면 · 대시보드 안 지원사업 보기가 같은 말. */
export const SUPPORT_VIEW_TITLES: ViewTitles = {
  simple: "한 열로 — 사업 · 신청할 수 있나요? · 7단계 · 초안 한 줄",
  full: "개요 · 7단계 전체 — 쉬운 보기에서 접은 것까지",
};

export function ViewModeToggle({
  mode,
  onChange,
  disabled = false,
  disabledReason,
  titles = DASHBOARD_VIEW_TITLES,
}: {
  mode: DisplayMode;
  onChange: (mode: DisplayMode) => void;
  disabled?: boolean;
  /** 막혀 있을 때 단추 설명 (예: 발표 중). 「 — 」 앞부분은 토글 옆에 글로도 적는다 — 터치에는 풍선 도움말이 없다 (EZ-36). */
  disabledReason?: string;
  /** 화면별 도움말 */
  titles?: ViewTitles;
}) {
  const noteId = useId();
  const lockNote = disabled && disabledReason ? disabledReason.split(" — ")[0] : null;
  return (
    <>
      <div
        role="group"
        aria-label="보기 방식"
        data-view-toggle={mode}
        className="flex shrink-0 items-center rounded-lg border border-cosmos-border bg-cosmos-panel p-0.5 backdrop-blur"
      >
        {OPTIONS.map((option) => {
          const active = mode === option.mode;
          return (
            <button
              key={option.mode}
              type="button"
              aria-pressed={active}
              aria-describedby={lockNote ? noteId : undefined}
              data-view-mode={option.mode}
              disabled={disabled}
              title={disabled && disabledReason ? disabledReason : titles[option.mode]}
              onClick={() => {
                if (!active) onChange(option.mode);
              }}
              // 쉬운 보기는 본문 단추(40~44px)에 맞춰 손가락으로 누르기 쉽게 (EZ-37).
              className={`mc-focus ${mode === "simple" ? "min-h-10" : "min-h-8"} whitespace-nowrap rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                active ? "bg-cosmos-blue/25 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {lockNote && (
        <span id={noteId} className="text-[12px] text-cosmos-muted">
          {lockNote}
        </span>
      )}
    </>
  );
}

/** 저장소를 바로 쓰는 토글 — 사업기회 목록 · 지원사업 신청 분석의 머리(`headerAside`)에 둔다. */
export function ViewModeSwitch({ titles }: { titles?: ViewTitles }) {
  const mode = useDisplayMode();
  return <ViewModeToggle mode={mode} onChange={setDisplayMode} titles={titles} />;
}
