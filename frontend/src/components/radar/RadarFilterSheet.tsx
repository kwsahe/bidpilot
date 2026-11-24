"use client";

/**
 * 레이더 보기 설정 시트.
 *
 * 기본 화면에서 뺀 조작(정렬 · 표시 개수 · 3D/2D · 마감된 항목 포함)을 **지우지 않고** 여기로 옮겼다.
 * 기본값이 아닌 항목이 있으면 [필터] 버튼에 개수 배지가 붙어, 숨겨진 설정이 있다는 것을 알린다.
 *
 * 공용 `Sheet`(넓은 화면=우측 드로어, 좁은 화면=바텀시트)를 그대로 쓴다 — Escape·배경 클릭으로 닫힌다.
 */

import { Button, Chip } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/overlays";
import type { OpportunitySort } from "@/types/opportunity";

export const VISIBLE_OPTIONS = [12, 20] as const;
export type VisibleCount = (typeof VISIBLE_OPTIONS)[number];
export type ViewMode = "3d" | "2d";

export interface RadarFilterState {
  /** null = 회사 설정(회사자료 「우선순위 계산 방식」의 기본 정렬 · 37차 §3-C-4). 고르면 그 정렬. */
  sort: OpportunitySort | null;
  visibleCount: VisibleCount;
  viewMode: ViewMode;
  includeClosed: boolean;
}

export const DEFAULT_FILTERS: RadarFilterState = {
  sort: null,
  visibleCount: 12,
  // 10-31 대표 결정 — 3D 는 화면에서 뺀다(코드는 남김). 레이더는 2D 평면도만.
  viewMode: "2d",
  includeClosed: false,
};

const SORTS: Array<{ key: OpportunitySort; label: string; hint: string }> = [
  // 37차 §3-C — 회사 방식이 실무 우선순위면 이것이 기본이다(사업담당자 방식 · 점수는 그대로).
  { key: "practical", label: "실무 우선순위", hint: "본업 안에서 주제 맞음 먼저(주제 확인 · AI 꼬리표는 뒤) · 최근 공고 · 준비기간 긴 것 먼저, 마감 임박은 아래 긴급 칸으로" },
  { key: "priority", label: "검토 우선순위", hint: "선택한 회사 기준 검토 우선순위 점수 높은 순" },
  { key: "deadline", label: "마감 임박", hint: "마감이 이른 순 (마감일 없는 항목은 뒤로)" },
  // 사업기회의 「마감 여유순」 · 「최신 등록순」으로 건너와도 켜진 칩이 보이게(37차 마지막 검토 — 칩 없이 배지만 1)
  { key: "slack", label: "마감 여유", hint: "실제 마감(등록 마감이 더 이르면 그 날)이 먼 순 (날짜가 없는 항목은 뒤로)" },
  { key: "recent", label: "최신 등록", hint: "공고 게시일 · 지원사업 등록일이 최근인 순" },
  // 기업마당은 목록에 금액이 없다 — 기업마당 쪽 순서는 검토 우선순위와 같다 (27차 RDR-20).
  { key: "value", label: "금액·지원 규모", hint: "예산이 큰 순 (금액이 없는 항목은 뒤로 · 기업마당은 금액이 없어 순서가 바뀌지 않습니다)" },
];

/** 기본값과 다른 설정 개수 — [필터] 버튼 배지에 쓴다. */
export function changedFilterCount(state: RadarFilterState): number {
  let count = 0;
  if (state.sort !== null) count += 1;
  if (state.visibleCount !== DEFAULT_FILTERS.visibleCount) count += 1;
  // 보기 방식(3D/2D)은 거르는 조건이 아니다 — 지도 머리에 전환이 있으므로 필터 수에서 뺀다(27차 §3-E UNI-03).
  if (state.includeClosed !== DEFAULT_FILTERS.includeClosed) count += 1;
  return count;
}

function Group({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-cosmos-border pt-3 first:border-t-0 first:pt-0">
      <h3 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">{label}</h3>
      {hint && <p className="mt-0.5 text-[12px] leading-5 text-cosmos-muted">{hint}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">{children}</div>
    </section>
  );
}

export interface RadarFilterSheetProps {
  open: boolean;
  onClose: () => void;
  state: RadarFilterState;
  onChange: (next: RadarFilterState) => void;
  /** 3D를 쓸 수 없을 때(WebGL 차단) 안내 문구. */
  webglBlocked: boolean;
  /** 회사 방식의 기본 정렬(응답 `sort` — 정렬을 고르지 않았을 때). 그 칩을 누르면 「회사 설정」으로 돌아간다. */
  companySort: OpportunitySort;
}

export default function RadarFilterSheet({ open, onClose, state, onChange, companySort }: RadarFilterSheetProps) {
  const changed = changedFilterCount(state);
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="보기 설정"
      description="여기서 바꾼 설정은 레이더와 순위 목록에 함께 적용됩니다."
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={() => onChange(DEFAULT_FILTERS)} disabled={changed === 0}>
            기본값으로
          </Button>
          <Button variant="secondary" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* 정렬은 서버 순서를 바꿔 그림에 오르는 상위 N건 자체가 바뀐다 — 「순서만 바꾼다」는 거짓이었다 (27차 RDR-04). */}
        <Group
          label="정렬 기준"
          hint={`정렬을 바꾸면 그림에 오르는 상위 ${state.visibleCount}건이 바뀌고, 거리(마감 순서)와 크기(검토 우선순위)도 새로 오른 ${state.visibleCount}건 안에서 다시 잽니다. 「금액·지원 규모」는 나라장터만 가릅니다 — 기업마당은 금액이 없어 순서가 그대로입니다.`}
        >
          {SORTS.map((option) => (
            <Chip
              key={option.key}
              active={(state.sort ?? companySort) === option.key}
              title={option.hint}
              // 회사 기본과 같은 정렬을 고르면 「회사 설정」(null)로 둔다 — 주소가 깨끗하고 회사 방식을 바꾸면 따라간다.
              onClick={() => onChange({ ...state, sort: option.key === companySort ? null : option.key })}
            >
              {option.label}
              {option.key === companySort && <span className="text-cosmos-muted"> (회사 설정)</span>}
            </Chip>
          ))}
        </Group>

        <Group label="표시 개수" hint="그림에 그릴 상위 항목 수입니다. 나머지는 사업기회 목록에서 봅니다.">
          {VISIBLE_OPTIONS.map((count) => (
            <Chip
              key={count}
              active={state.visibleCount === count}
              title={`상위 ${count}건만 그림에 표시합니다`}
              onClick={() => onChange({ ...state, visibleCount: count })}
            >
              {count}건
            </Chip>
          ))}
        </Group>

        <Group label="마감된 항목" hint="이미 마감된 공고는 회색 노드로 표시되며 「마감」으로 적습니다.">
          {/* 글자는 고정 · 켜짐은 aria-pressed 로만 — 글자와 눌림이 함께 바뀌면 「마감 제외, 눌리지 않음」으로 읽혔다 (27차 RDR-21). */}
          <Chip
            active={state.includeClosed}
            title="마감된 항목까지 함께 표시합니다"
            onClick={() => onChange({ ...state, includeClosed: !state.includeClosed })}
          >
            마감된 항목 포함
          </Chip>
        </Group>
      </div>
    </Sheet>
  );
}
