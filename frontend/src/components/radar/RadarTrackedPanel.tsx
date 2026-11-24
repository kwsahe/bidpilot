"use client";

/**
 * 추적 중인 사업기회 — 스코프 오른쪽 패널.
 *
 * 두 상태를 한 자리에서 다룬다.
 *   선택 없음 → 상위 항목 카드 (여기서 바로 고를 수 있다)
 *   선택 있음 → 기존 `RadarDetail` 을 그대로 띄운다
 *
 * 상세는 **재설계하지 않고 재사용**한다. 배점표·적합한 이유·확인 사항·원문 링크·다음 분석 버튼이
 * 전부 거기 들어 있고, 그걸 다시 만들면 기능이 조용히 빠진다.
 *
 * 점수는 원형 게이지로 그린다. `company_priority_score` 는 **낙찰·선정 확률이 아니라**
 * 회사 기준 검토 우선순위이며, null 이면 게이지를 0으로 그리지 않고 「미확인」으로 둔다.
 */

import { useEffect, useRef } from "react";

import RadarDetail from "@/components/radar/RadarDetail";
import { GROUP_TONE, useRankingMethod } from "@/components/opportunities/PracticalTags";
import { REVIEW_PRIORITY } from "@/lib/scoreNames";
import { PlaneTargetIcon } from "@/components/icons/aviation";
import { COSMOS_COLORS, TONE_COLORS, withAlpha } from "@/lib/cosmos/theme";
import { scoreText, stripHtml, type RadarNode } from "@/lib/radar/layout";
import type { PriorityLabel } from "@/types/opportunity";

// ---------------------------------------------------------------------------
// 점수 게이지
// ---------------------------------------------------------------------------

const GAUGE_R = 15;
const GAUGE_C = 2 * Math.PI * GAUGE_R;

/**
 * 원형 점수 게이지.
 * 점수가 없으면 호를 그리지 않고 점선 테두리와 「미확인」만 남긴다 — 0점처럼 보이면 안 된다.
 */
function ScoreGauge({ score, color }: { score: number | null; color: string }) {
  const known = score !== null;
  const ratio = known ? Math.max(0, Math.min(100, score)) / 100 : 0;
  return (
    <div className="flex shrink-0 flex-col items-center gap-0.5">
      <div className="relative h-[38px] w-[38px]">
        <svg viewBox="0 0 38 38" className="h-full w-full -rotate-90" aria-hidden="true">
          <circle
            cx="19"
            cy="19"
            r={GAUGE_R}
            fill="none"
            stroke={COSMOS_COLORS.borderStrong}
            strokeWidth="2.5"
            strokeDasharray={known ? undefined : "2 3"}
          />
          {known && (
            <circle
              cx="19"
              cy="19"
              r={GAUGE_R}
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeDasharray={`${(GAUGE_C * ratio).toFixed(2)} ${GAUGE_C.toFixed(2)}`}
            />
          )}
        </svg>
        <span
          className={`absolute inset-0 flex items-center justify-center font-mono font-semibold tabular-nums ${
            known ? "text-[13px]" : "text-[12px]"
          }`}
          style={{ color: known ? COSMOS_COLORS.textPrimary : COSMOS_COLORS.textMuted }}
        >
          {scoreText(score)}
        </span>
      </div>
      {/* uppercase 라 화면에는 「SCORE」로 보였다. 값은 검토 우선순위(0~100)다. */}
      <span className="text-[12px] font-semibold leading-none tracking-[0.14em] text-cosmos-muted">
        {REVIEW_PRIORITY.label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 카드 하나
// ---------------------------------------------------------------------------

/** 왼쪽 세로 강조선 색 — **순위가 아니라 상태**로 정한다 (1위라서 빨강이 되면 안 된다). */
function accentOf(node: RadarNode, practical: boolean): string {
  if (node.closed) return COSMOS_COLORS.slate;
  if (node.item.eligibility_gate === "FAIL") return COSMOS_COLORS.red;
  if (node.urgency === "urgent") return COSMOS_COLORS.red;
  if (node.urgency === "soon") return COSMOS_COLORS.amber;
  // (2.0.6) 실무 우선순위 회사는 「신규+여유」가 「우선 검토」 자리다 — 사업기회 머리 숫자와 같은 칸(37차 §3-B-4)
  if (practical ? node.item.practical_group === "신규+여유" : node.item.priority_label === "우선 검토") return COSMOS_COLORS.cyan;
  return COSMOS_COLORS.borderStrong;
}

const PRIORITY_TEXT: Partial<Record<PriorityLabel, string>> = {
  "우선 검토": "우선 검토",
  마감: "마감",
};

function TrackedCard({
  node,
  selected,
  onSelect,
  onHover,
}: {
  node: RadarNode;
  selected: boolean;
  /** byKeyboard — Enter · Space 로 누른 클릭은 `detail` 이 0 이다. */
  onSelect: (id: string, byKeyboard: boolean) => void;
  onHover?: (id: string | null) => void;
}) {
  const practical = useRankingMethod() === "practical";
  const accent = accentOf(node, practical);
  const urgent = node.urgency === "urgent" || node.urgency === "closed";
  const stateTag = node.closed
    ? "마감"
    : node.item.eligibility_gate === "FAIL"
      ? "불가"
    : node.urgency === "urgent"
      ? "마감 임박"
      : practical
        ? (node.item.practical_group ?? null) // (2.0.6) 사업기회 행 배지와 같은 분류 칸
        : (PRIORITY_TEXT[node.item.priority_label] ?? null);
  // 꼬리표 글자색 — 강조선의 회색 칸(borderStrong · 반투명)을 글자에 쓰면 거의 안 보였고 `1f` 배경도 깨졌다.
  // 실무순 분류 칸은 사업기회 배지와 같은 색(GROUP_TONE), 그 밖 회색 칸은 읽히는 회청(2.0.6).
  const tagColor =
    practical && node.item.practical_group && stateTag === node.item.practical_group
      ? TONE_COLORS[GROUP_TONE[node.item.practical_group] ?? "muted"]
      : accent === COSMOS_COLORS.borderStrong
        ? COSMOS_COLORS.slate
        : accent;

  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={(event) => onSelect(node.id, event.detail === 0)}
        onMouseEnter={() => onHover?.(node.id)}
        onMouseLeave={() => onHover?.(null)}
        onFocus={() => onHover?.(node.id)}
        onBlur={() => onHover?.(null)}
        className={`mc-focus group relative flex w-full min-w-0 items-start gap-3 rounded-lg border py-2.5 pl-3.5 pr-3 text-left transition-colors ${
          selected
            ? "border-cosmos-cyan/50 bg-cosmos-elevated"
            : "border-cosmos-border bg-cosmos-panel hover:border-cosmos-border-strong hover:bg-cosmos-elevated/60"
        }`}
      >
        {/* 상태 강조선 */}
        <span
          aria-hidden="true"
          className="absolute bottom-2 left-0 top-2 w-[2.5px] rounded-full"
          style={{ backgroundColor: accent }}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {/* 순위 · 상태 · 출처 */}
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            {/* 같은 출처 «안»의 순위다 (0922 §4-B-7). 두 출처를 섞은 자리 번호가 아니다. */}
            <span
              className="font-mono text-[12px] font-semibold leading-none tabular-nums text-cosmos-secondary"
              title={`${node.sourceLabel} ${node.sourceRank}/${node.sourceTotal}`}
            >
              {node.sourceRank}
            </span>
            {stateTag && (
              <span
                className="rounded-[3px] px-1.5 py-[2px] text-[12px] font-semibold leading-none"
                style={{ color: tagColor, backgroundColor: withAlpha(tagColor, 12) }}
              >
                {stateTag}
              </span>
            )}
            <span className="inline-flex items-center gap-1 text-[12px] leading-none text-cosmos-muted">
              <PlaneTargetIcon filled size={11} style={{ color: node.color }} />
              {node.sourceLabel}
            </span>
          </div>

          {/* 제목 */}
          <p className="line-clamp-2 text-[13px] font-medium leading-[1.45] text-cosmos-text">
            {stripHtml(node.item.title)}
          </p>

          {/* 기관 · 분야 */}
          <p className="truncate text-[12px] leading-4 text-cosmos-muted">
            {node.item.agency}
            {node.item.category ? ` · ${node.item.category}` : ""}
          </p>

          {/* 마감 */}
          <p
            className="font-mono text-[12px] leading-4 tabular-nums"
            style={{ color: urgent ? COSMOS_COLORS.amber : COSMOS_COLORS.textMuted }}
          >
            {node.deadlineLabel}
          </p>
        </div>

        {node.item.eligibility_gate === "FAIL" ? (
          // 화면 글자는 한국어 — 판정 말은 한 벌(가능 · 확인 필요 · 불가) (27차 §3-F · 영문 「FAIL」 배지)
          <span className="shrink-0 rounded-full border border-cosmos-red/45 bg-cosmos-red/10 px-2 py-1 text-[12px] font-semibold text-cosmos-red">
            불가
          </span>
        ) : (
          <ScoreGauge score={node.item.company_priority_score} color={accent} />
        )}
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// 패널
// ---------------------------------------------------------------------------

export interface RadarTrackedPanelProps {
  /** 선택된 항목. 있으면 상세를 띄운다. */
  node: RadarNode | null;
  /** 미선택 상태에 보여줄 상위 항목. */
  topNodes: RadarNode[];
  selectedId: string | null;
  fetchedAt: string | null;
  companyName: string;
  totalTracked: number;
  /** null 이면 선택을 풀고 상위 목록으로 돌아간다 (27차 RDR-41). */
  onSelect: (id: string | null) => void;
  onHover?: (id: string | null) => void;
  /** 「순위 목록」 시트 열기 — 키보드로 전부 고를 수 있는 자리. */
  onOpenList?: () => void;
  loading: boolean;
  error: string | null;
  /** 통합 보기 — 상위 카드는 정렬 순서가 아니라 출처별 상위를 번갈아 고른 순서다 (27차 RDR-39). */
  interleaved?: boolean;
}

export default function RadarTrackedPanel({
  node,
  topNodes,
  selectedId,
  fetchedAt,
  companyName,
  totalTracked,
  onSelect,
  onHover,
  onOpenList,
  loading,
  error,
  interleaved = false,
}: RadarTrackedPanelProps) {
  const backRef = useRef<HTMLButtonElement | null>(null);
  const keyboardPick = useRef(false);
  const nodeId = node?.id ?? null;
  /*
   * 카드를 키보드로 고르면 누른 카드가 상세로 바뀌며 사라져 포커스가 body 로 떨어졌다 —
   * 그때만 「← 상위 목록」으로 옮긴다 (27차 RDR-41). 예전에는 「포커스가 body 」도 조건이라
   * 주소에 공고 선택이 실린 채 처음 열면 아무것도 누르지 않았는데 포커스가 이 단추로 갔다.
   */
  const sectionRef = useRef<HTMLElement | null>(null);
  const keyboardBack = useRef(false);
  useEffect(() => {
    if (!nodeId) {
      // 「← 상위 목록」을 키보드로 누르면 단추가 사라져 포커스가 body 로 떨어졌다 — 목록 첫 카드로(§3-F RDR-41 검증)
      if (keyboardBack.current) {
        keyboardBack.current = false;
        sectionRef.current?.querySelector<HTMLElement>("button, a[href]")?.focus({ preventScroll: true });
      }
      return;
    }
    if (!keyboardPick.current) return;
    keyboardPick.current = false;
    backRef.current?.focus({ preventScroll: true });
  }, [nodeId]);
  const pickCard = (id: string, byKeyboard: boolean) => {
    keyboardPick.current = byKeyboard;
    onSelect(id);
  };
  return (
    <section
      ref={sectionRef}
      aria-label="추적 중인 사업기회"
      className="flex min-h-0 min-w-0 flex-col rounded-xl border border-cosmos-border bg-cosmos-panel"
    >
      {/* 머리말 */}
      <header className="flex items-baseline justify-between gap-3 border-b border-cosmos-border px-3.5 py-2.5">
        <div className="min-w-0">
          <h2 className="text-[14px] font-semibold leading-tight text-cosmos-text">먼저 볼 사업기회</h2>
          {/* 영문 부제 「Tracked Opportunities」 → 한국어 (27차 RDR-34) */}
          <p className="mt-0.5 text-[12px] font-semibold leading-none tracking-[0.12em] text-cosmos-muted">지켜보는 공고</p>
        </div>
        {onOpenList && (
          <button
            type="button"
            onClick={onOpenList}
            className="mc-focus shrink-0 rounded text-[12px] font-medium text-cosmos-secondary transition-colors hover:text-cosmos-cyan"
          >
            순위 목록 <span aria-hidden="true">→</span>
          </button>
        )}
      </header>

      {/* 본문 */}
      <div className="mc-scroll min-h-0 flex-1 overflow-y-auto p-3">
        {node ? (
          <>
            {/* 패널 안에서 상위 목록으로 돌아가는 길 — 예전에는 순위 목록 시트에서 같은 항목을 다시 눌러야 했다 (27차 RDR-41). */}
            <button
              ref={backRef}
              type="button"
              onClick={(event) => {
                keyboardBack.current = event.detail === 0;
                onSelect(null);
              }}
              className="mc-focus mb-2 inline-flex items-center gap-1 rounded text-[12px] font-medium text-cosmos-secondary transition-colors hover:text-cosmos-cyan"
            >
              <span aria-hidden="true">←</span> 상위 목록
            </button>
            <RadarDetail bare node={node} fetchedAt={fetchedAt} companyName={companyName} />
          </>
        ) : loading ? (
          <p className="px-1 py-6 text-center text-[12px] text-cosmos-muted">사업기회를 불러오는 중…</p>
        ) : error ? (
          <p className="px-1 py-6 text-center text-[12px] leading-5 text-cosmos-muted">
            목록을 불러오지 못했습니다. 위 「자료 상태」에서 다시 시도하세요.
          </p>
        ) : topNodes.length === 0 ? (
          <p className="px-1 py-6 text-center text-[12px] leading-5 text-cosmos-muted">
            {companyName} 기준으로 표시할 사업기회가 없습니다.
          </p>
        ) : (
          <>
            <p className="mb-2 px-0.5 text-[12px] leading-4 text-cosmos-muted">
              {interleaved
                ? "나라장터 · 기업마당 상위를 번갈아 고른 순서입니다(순위는 같은 출처 안). 고르면 왼쪽 그림에도 표시됩니다."
                : "지금 정렬 순서입니다. 고르면 왼쪽 그림에도 표시됩니다."}
            </p>
            <ul className="flex flex-col gap-2">
              {topNodes.map((top) => (
                <TrackedCard
                  key={top.id}
                  node={top}
                  selected={top.id === selectedId}
                  onSelect={pickCard}
                  onHover={onHover}
                />
              ))}
            </ul>
            {totalTracked > topNodes.length && (
              <p className="mt-2.5 px-0.5 text-[12px] leading-4 text-cosmos-muted">
                {/* 외부 점검 UI a — 앞 3건은 위 줄의 순서(출처 번갈아 · 실무 · 마감순)라 점수가 높은 순이 아닐 수 있다 */}
                지켜보는 {totalTracked}건 가운데 위 순서의 앞 {topNodes.length}건입니다. 나머지는 「순위 목록 →」에서 봅니다.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}
