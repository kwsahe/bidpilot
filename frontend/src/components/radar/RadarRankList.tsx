"use client";

/**
 * 사업기회 순위 목록.
 *
 * 같은 목록을 세 곳에서 쓴다 — 모바일 기본 화면 · 「순위 목록」 시트 · 3D 전체화면의 목록 전환.
 * 3D/2D 그림은 마우스·터치 조작이라, **키보드로 모든 항목을 고를 수 있는 자리**가 여기다.
 *
 * 배지를 쓰지 않고 한 줄 텍스트(순위 · 출처 · 점수 · 마감)로 적어 시각 밀도를 낮춘다.
 * 색만으로 출처를 구분하지 않는다 — 모양 글리프(●/◆)와 이름을 함께 쓴다.
 */

import { PlaneTargetIcon } from "@/components/icons/aviation";
import { REVIEW_PRIORITY } from "@/lib/scoreNames";
import { COSMOS_COLORS, withAlpha } from "@/lib/cosmos/theme";
import { scoreText, stripHtml, type RadarNode } from "@/lib/radar/layout";

export interface RadarRankListProps {
  nodes: RadarNode[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onHover?: (id: string | null) => void;
  /** 항목을 고르면 실행 (시트를 닫는 등). */
  onPick?: () => void;
  className?: string;
}

export default function RadarRankList({
  nodes,
  selectedId,
  onSelect,
  onHover,
  onPick,
  className = "",
}: RadarRankListProps) {
  return (
    <ul className={`flex min-w-0 flex-col gap-1 ${className}`}>
      {nodes.map((node) => {
        const active = node.id === selectedId;
        const urgent = node.urgency === "urgent" || node.urgency === "closed";
        // 순위·점수만 적으면 「불가」인 사업이 목록 안에서 평범한 후보로 읽힌다.
        // 실측: 부산 AX클리닉은 72점(업무 적합도 상위)인데 회사 활동 지역 밖이라 신청할 수 없다.
        // 자격은 점수보다 먼저 와야 하므로 순위 바로 옆에 글자로 적는다 (색만으로 구분하지 않는다).
        const blocked = node.item.eligibility_gate === "FAIL";
        return (
          <li key={node.id}>
            <button
              type="button"
              aria-pressed={active}
              onClick={() => {
                onSelect(active ? null : node.id);
                onPick?.();
              }}
              onMouseEnter={() => onHover?.(node.id)}
              onMouseLeave={() => onHover?.(null)}
              onFocus={() => onHover?.(node.id)}
              onBlur={() => onHover?.(null)}
              className={`mc-focus flex w-full min-w-0 items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors ${
                active
                  ? "bg-cosmos-elevated ring-1 ring-cosmos-cyan/50"
                  : "hover:bg-cosmos-elevated/70"
              } ${
                // 「참여 안 함」으로 정한 공고는 흐리게. 지우지 않는 이유는 결정을 되돌리는
                // 일이 있기 때문이다 (0920 §4-B-3 · ISSUE-076-d).
                node.declined ? "opacity-50" : ""
              }`}
            >
              <PlaneTargetIcon
                filled
                size={13}
                className="mt-[3px] shrink-0"
                style={{ color: node.color }}
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-baseline gap-x-1.5 text-[12px] leading-4 text-cosmos-muted">
                  {/* 같은 출처 안 순위를 출처 이름과 함께 — 섞은 자리 번호(기업마당 1위가 「2위」)는 비교 근거가 아니다 (27차 RDR-06). */}
                  <span className="text-cosmos-secondary">
                    {node.sourceLabel} <span className="font-mono tabular-nums">{node.sourceRank}위</span>
                  </span>
                  {blocked && (
                    <span
                      className="rounded-[3px] border px-1 text-[12px] font-semibold"
                      style={{ color: COSMOS_COLORS.red, borderColor: withAlpha(COSMOS_COLORS.red, 40) }}
                      title={node.item.gate_reason ?? "신청 자격이 맞지 않아 보입니다 — 상세에서 사유를 확인하세요"}
                    >
                      불가
                    </span>
                  )}
                  {node.declined && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>참여 안 함</span>
                    </>
                  )}
                  <span aria-hidden="true">·</span>
                  {/* 같은 값이 상세·게이지·여기서 다른 이름이었다 — 이름을 하나로 (0920 §4-B-1). */}
                  <span className="tabular-nums" title={REVIEW_PRIORITY.description}>
                    {REVIEW_PRIORITY.label} <span className="font-mono">{scoreText(node.item.company_priority_score)}</span>
                  </span>
                  <span aria-hidden="true">·</span>
                  <span
                    className="font-mono tabular-nums"
                    style={urgent ? { color: COSMOS_COLORS.amber } : undefined}
                  >
                    {node.deadlineLabel}
                  </span>
                </span>
                <span className="mt-0.5 line-clamp-2 block text-[13px] font-medium leading-5 text-cosmos-text">
                  {stripHtml(node.item.title)}
                </span>
                {blocked && node.item.gate_reason && (
                  <span className="mt-0.5 line-clamp-2 block text-[12px] leading-4" style={{ color: COSMOS_COLORS.red }}>
                    {node.item.gate_reason}
                  </span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
