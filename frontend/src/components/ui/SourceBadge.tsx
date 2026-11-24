"use client";

/**
 * 데이터 출처 배지 — 실제 나라장터 데이터 / 캐시 / 데모 시나리오 / 실분석 / 미실행을
 * 전 화면에서 같은 모양·색·글리프로 표시한다. 실데이터와 데모를 절대 섞어 보이지 않는다.
 */

import { Badge, TONE_GLYPH } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/cosmos/format";
import { TONE_COLORS } from "@/lib/cosmos/theme";
import { CACHE_TERM, FROZEN_TERM, SYNTHETIC_NOTICE, collectTerm, collectWarns } from "@/lib/terms";
import type { CollectState } from "@/types/opportunity";

export type SourceKind =
  /** 나라장터 OpenAPI 실시간 응답 */
  | "g2b"
  /** 실호출 실패로 디스크 캐시 사용 */
  | "cached"
  /** 고정 목록(시연용 4건)에 있는 공고. 캐시에서 왔든 저장소에서 되살렸든 같다 (ISSUE-134) */
  | "pinned"
  /** 합성 데모 시나리오 고정값 */
  | "demo"
  /** 실제 backend 분석 결과 (규칙/AI) */
  | "analysis"
  /** 로컬 규칙 파싱 등 실제 계산 결과 */
  | "computed"
  /** 아직 실행하지 않음 */
  | "not_run"
  /**
   * 실행했는데 실패했다.
   *
   * 「미실행」과 반드시 갈라야 한다 — 담당자는 칩을 먼저 읽고, 「미실행」이면 같은 버튼을
   * 다시 누른다. 실패는 다시 눌러도 같은 결과다 (ISSUE-058).
   */
  | "failed"
  /** 결정론적 규칙(정규식·필드 비교)으로 계산 — LLM 없음 */
  | "rule"
  /** 담당자가 직접 확인·저장한 값 */
  | "human";

const SOURCE_STYLE: Record<SourceKind, { label: string; tone: "ok" | "warn" | "demo" | "pass" | "muted" | "info"; glyph: string }> = {
  g2b: { label: "나라장터 실시간", tone: "ok", glyph: "●" },
  cached: { label: "나라장터 저장본", tone: "info", glyph: "◐" },
  // 「시연용」을 앞에 둔다 — 이 배지가 붙은 공고는 마감이어도 목록·선택기에 남는다 (ISSUE-056).
  pinned: { label: "예시 공고(마감)", tone: "warn", glyph: "⚑" },
  // ◇ 회청 점선 — 보라 ◆ 는 기업마당(출처) 한 뜻이다 (27차 §3-E · UNI-19).
  demo: { label: SYNTHETIC_NOTICE, tone: "demo", glyph: TONE_GLYPH.demo },
  analysis: { label: "AI 분석 결과", tone: "pass", glyph: "✓" },
  // 45차 M21 — ● 는 「나라장터 실시간」 한 뜻(같은 색 같은 기호로 두 뜻이었다)
  computed: { label: "실제 자료", tone: "ok", glyph: "◉" },
  not_run: { label: "아직 안 함", tone: "muted", glyph: "○" },
  failed: { label: "실패", tone: "warn", glyph: "!" },
  rule: { label: "규칙 기반", tone: "info", glyph: "▣" },
  human: { label: "사람 확인", tone: "pass", glyph: "✎" },
};

/**
 * **데이터 상태 칩** — 사업기회 머리 · 레이더 머리(와 레이더 계기의 상태 점)가 같은 기호 · 색 · 말을 쓴다
 * (27차 §3-E · UNI-18). 예전에는 같은 캐시가 목록 「● 캐시」 주황 · 레이더 「◐ 캐시」 회색 · 출처 배지
 * 「◐ 나라장터 캐시」 파랑이었고, 시연 고정도 목록은 「캐시」 · 레이더는 「시연 고정」이라 적었다.
 * 기호 · 색은 위 출처 배지(SOURCE_STYLE)에서 오고, 시연 고정은 시연 고정 안내(FrozenNotice)의 ⏸ 호박이다.
 */
export type DataStatus = "live" | "cached" | "frozen" | "sample" | "error" | "loading";

const styleMark = (kind: SourceKind) => ({ glyph: SOURCE_STYLE[kind].glyph, color: TONE_COLORS[SOURCE_STYLE[kind].tone] });

export const DATA_STATUS_MARK: Record<DataStatus, { glyph: string; color: string; word: string }> = {
  live: { ...styleMark("g2b"), word: "실시간" },
  cached: { ...styleMark("cached"), word: CACHE_TERM },
  frozen: { glyph: "⏸", color: TONE_COLORS.warn, word: FROZEN_TERM },
  sample: { ...styleMark("demo"), word: SYNTHETIC_NOTICE },
  error: { glyph: "✕", color: TONE_COLORS.fail, word: "오류" },
  loading: { ...styleMark("not_run"), word: "불러오는 중" },
};

/** 데이터 상태 칩의 속 — 「◐ 데이터 캐시」 「⏸ 데이터 시연 고정」. 두 화면이 이것 하나를 트리거에 넣는다(좁은 레이더 머리에 맞춰 짧게). */
export function DataStatusLabel({
  status,
  collectState,
  short = false,
}: {
  status: DataStatus;
  collectState?: CollectState | null;
  /** 좁은 머리(레이더)에서는 받은 때 글을 짧게 — 긴 글은 팝오버 안 안내에만(40차 FRONT-01). */
  short?: boolean;
}) {
  const mark = DATA_STATUS_MARK[status];
  // 고정 모드라도 자동 받기 기록이 있으면 그 한 줄(39차 §3-F-2 · 40차 D30 — `collectTerm` 하나).
  // 경고(키트 · 오늘 아직)일 때만 ⏸ 호박 — 오늘 받음 · 받는 중 · 꺼 둠 · 모름은 ● 보통색(40차 COLLECT-08 · FRONT-06).
  const word = status === "frozen" ? collectTerm(collectState, null, short) : mark.word;
  const calm = status === "frozen" && !collectWarns(collectState);
  return (
    <>
      <span aria-hidden="true" style={calm ? undefined : { color: mark.color }}>
        {calm ? "●" : mark.glyph}
      </span>
      자료 상태 · {word}
    </>
  );
}

/** 배지 한 개가 차지해도 되는 글자 수 상한. 넘치면 잘라 보이고 전체는 tooltip 으로 남긴다. */
const BADGE_LABEL_LIMIT = 46;

export function SourceBadge({
  kind,
  label,
  fetchedAt,
  size = "sm",
  className,
}: {
  kind: SourceKind;
  /** 기본 문구 대신 쓸 라벨 (예: "제안서: 실생성") */
  label?: string;
  fetchedAt?: string | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const style = SOURCE_STYLE[kind];
  // 라벨에 첨부 파일명이 통째로 들어오는 자리가 있다(「과업·요구사항: 실제 공고 첨부 파싱 (…)」).
  // 실측: 1366×768 에서 이 배지 하나가 770px 을 차지해 하단 출처 줄이 화면 밖으로 흘렀고
  // 페이지에 가로 스크롤이 생겼다. 배지는 «무엇에서 왔는가»를 알리는 것이므로 잘라 보이고,
  // 전체 문구는 마우스를 올리면 보이게 남긴다 — 정보를 지우지 않는다.
  const shown = label ?? style.label;
  const overlong = shown.length > BADGE_LABEL_LIMIT;
  const title =
    kind === "g2b" || kind === "cached"
      ? fetchedAt
        ? `조회 시각 ${formatDateTime(fetchedAt)}`
        : undefined
      : kind === "demo"
        ? "가상 예시 공고 · 가상 예시 회사자료의 고정값 — 실제 분석 결과가 아닙니다"
        : kind === "not_run"
          ? "이 단계는 아직 하지 않았습니다 — 0이 아니라 값이 없는 것입니다"
          : kind === "rule"
            ? "정해 둔 규칙(글자·숫자 비교)으로 낸 결과입니다. AI 판단이 아니라 언제 해도 같은 답이 나옵니다."
            : kind === "human"
              ? "담당자가 직접 확인해 저장한 값"
              : undefined;
  return (
    <Badge
      tone={style.tone}
      glyph={style.glyph}
      size={size}
      title={overlong ? (title ? `${shown}
${title}` : shown) : title}
      className={className}
    >
      {overlong ? `${shown.slice(0, BADGE_LABEL_LIMIT - 1).trimEnd()}…` : shown}
    </Badge>
  );
}

/** 공고 목록 응답의 source → 배지 종류.
 *
 * 고정 공고는 목록 전체가 "g2b"(실시간)라도 방금 받아온 것이 아니다. 그 행만은
 * 「시연용 고정 공고」로 적는다 — 마감이어도 목록·선택기에 남고 저장본으로 분석 화면이
 * 열리는, 다른 행과 성질이 다른 행이기 때문이다.
 * 옛 배포 스냅샷에는 pinned 가 없어 undefined 다.
 */
export function noticeSourceKind(
  source: "g2b" | "cached" | null | undefined,
  pinned?: boolean | null,
): SourceKind {
  if (pinned) return "pinned";
  return source === "g2b" ? "g2b" : source === "cached" ? "cached" : "not_run";
}
