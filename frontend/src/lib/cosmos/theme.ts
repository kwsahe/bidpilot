/**
 * Evidence Cosmos 디자인 토큰. 2D SVG · HTML 패널은 `COSMOS_COLORS`(CSS 변수 `var(--cosmos-…)`) —
 * 어두운 · 밝은 화면(globals.css `:root[data-theme="light"]`)을 따라간다(2.4.0 ⑥).
 * 16진만 받는 곳(3D THREE 재질 · 시험)은 `COSMOS_HEX`(어두운 판 · globals.css `:root` 와 같은 값).
 *
 * 상태색 의미 (전 화면 공통 · 판정 4색은 아래 `VERDICT_*` 한 곳):
 *  cyan   충족 · 가능 · 연결 · 진행
 *  amber  확인 필요 · 부분 충족
 *  red    문제 · 불가 · 중요 경고
 *  slate  판정 전 · 비활성 · 보조 정보
 *  blue   채움 주 단추(Button primary) — 상태색이 아니다
 *  violet 기업마당(출처) — 합성 · 데모 표시는 회청 점선 테두리 + ◇ (Badge tone "demo")
 * 초록은 판정색이 아니다 (27차 §3-E 「색 한 벌」 · 통일 점검 UNI-10).
 */

/** 어두운 판 16진값 — globals.css `:root` 와 같다. 3D(THREE.Color)처럼 CSS 변수를 못 읽는 곳만 쓴다. */
export const COSMOS_HEX = {
  bg: "#060B18",
  bgElevated: "#0B1326",
  panel: "rgba(11, 19, 38, 0.78)",
  border: "rgba(124, 150, 255, 0.16)",
  borderStrong: "rgba(124, 150, 255, 0.34)",
  textPrimary: "#E8EEFF",
  textSecondary: "#A3B0D4",
  textMuted: "#97A3C6",
  blue: "#4C7DFF",
  /** 어두운 면 위의 **파란 글자** (0925 §4-F-1). 면·테두리는 위의 `blue` 그대로. */
  blueText: "#8CAEFF",
  /** **흰 글자를 얹는 파란 단추 면** (0925 §4-F-1). 흰 글자가 4.73:1 이다. */
  blueStrong: "#3F6AE8",
  cyan: "#22D3EE",
  violet: "#8B7CFF",
  amber: "#F5B942",
  red: "#FF5C6C",
  /** 결정 문장용 붉은 글자(globals.css `--cosmos-red-text`). */
  redText: "#FF7A86",
  green: "#34D399",
  slate: "#7D8CB0",
} as const;

type CosmosColorKey = keyof typeof COSMOS_HEX;

/** 화면 색 — 같은 열쇠의 CSS 변수. SVG 속성 · style 에 그대로 넣는다(크롬은 SVG 속성의 var() · color-mix() 를 읽는다). */
export const COSMOS_COLORS = {
  bg: "var(--cosmos-bg)",
  bgElevated: "var(--cosmos-bg-elevated)",
  panel: "var(--cosmos-panel)",
  border: "var(--cosmos-border)",
  borderStrong: "var(--cosmos-border-strong)",
  textPrimary: "var(--cosmos-text)",
  textSecondary: "var(--cosmos-text-secondary)",
  textMuted: "var(--cosmos-text-muted)",
  blue: "var(--cosmos-blue)",
  blueText: "var(--cosmos-blue-text)",
  blueStrong: "var(--cosmos-blue-strong)",
  cyan: "var(--cosmos-cyan)",
  violet: "var(--cosmos-violet)",
  amber: "var(--cosmos-amber)",
  red: "var(--cosmos-red)",
  redText: "var(--cosmos-red-text)",
  green: "var(--cosmos-green)",
  slate: "var(--cosmos-slate)",
} as const satisfies Record<CosmosColorKey, string>;

/**
 * 색에 투명도를 준다 — 예전 「16진 + 알파 두 자리」(`#22D3EE1f`)를 대신한다. var() 색에도 먹는다.
 * percent 는 0~100(1f=12 · 26=15 · 38=22 · 55=33 · 66=40 · ea=92).
 */
export function withAlpha(color: string, percent: number): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}

const HEX_BY_VAR: Record<string, string> = Object.fromEntries(
  (Object.keys(COSMOS_HEX) as CosmosColorKey[]).map((key) => [COSMOS_COLORS[key], COSMOS_HEX[key]]),
);

/** 16진만 받는 곳(3D 재질 · 선) 앞에서 — `COSMOS_COLORS` 의 var() 를 어두운 판 16진으로. 그 밖 값은 그대로. */
export function cosmosHex(color: string): string {
  return HEX_BY_VAR[color] ?? color;
}

export type CosmosNodeState =
  | "neutral"
  | "ok"
  | "partial"
  | "check"
  | "missing"
  | "warning"
  /** Auditor가 찾았지만 담당자가 해결로 전환한 발견 */
  | "resolved";

/** 노드 상태 → 판정 4색 — 지도 노드색(`itemTypes` VERDICT_COLORS)과 같은 값. 해결된 발견은 충족 쪽, 후보 근거만은 확인 필요 쪽. */
export const STATE_COLORS: Record<CosmosNodeState, string> = {
  neutral: COSMOS_COLORS.slate,
  ok: COSMOS_COLORS.cyan,
  partial: COSMOS_COLORS.amber,
  check: COSMOS_COLORS.amber,
  missing: COSMOS_COLORS.slate,
  warning: COSMOS_COLORS.red,
  resolved: COSMOS_COLORS.cyan,
};

export const STATE_LABELS: Record<CosmosNodeState, string> = {
  // 「RFP 준수」는 「준수했다」로 읽혔다 — 판정 낱말(itemTypes VERDICT_WORDS)과 같은 「판정 전」 (DSH-08).
  neutral: "판정 전",
  ok: "근거 연결",
  partial: "후보 근거만",
  check: "확인 필요",
  missing: "근거 없음",
  warning: "제출 전 점검 경고",
  resolved: "해결됨",
};

export const KIND_COLORS = {
  notice: COSMOS_COLORS.blue,
  requirement: "#6F8BFF",
  // 묶음은 구성원과 같은 색을 쓴다 — 다른 색이면 다른 종류로 읽힌다.
  "requirement-group": "#6F8BFF",
  "finding-group": COSMOS_COLORS.red,
  evidence: COSMOS_COLORS.violet,
  proposal: COSMOS_COLORS.cyan,
  audit: COSMOS_COLORS.amber,
  finding: COSMOS_COLORS.red,
} as const;

export const KIND_LABELS = {
  notice: "입찰공고",
  requirement: "제안요청서 요구사항",
  "requirement-group": "요구사항 묶음",
  "finding-group": "발견 묶음",
  evidence: "회사 근거",
  proposal: "제안서 초안",
  audit: "제출 전 누락 점검",
  finding: "점검에서 발견된 문제",
} as const;

/**
 * 공통 상태 의미 색. **글자로 쓰이는 색**이라 파랑은 `blueText` 다 (0925 §4-F-1) —
 * `COSMOS_COLORS.blue` 를 글자로 쓰면 파란 칩 배경 위에서 4.44:1 이었다.
 */
export const TONE_COLORS = {
  ok: COSMOS_COLORS.cyan,
  // 「통과 · 승인 · 해결」 — 충족과 같은 청록, 글리프(✓)로만 가른다. 예전 초록은 판정색이 둘이 되게 했다(UNI-10).
  pass: COSMOS_COLORS.cyan,
  warn: COSMOS_COLORS.amber,
  fail: COSMOS_COLORS.red,
  info: COSMOS_COLORS.blueText,
  // 합성 · 데모 — 회청 + 점선 테두리 + ◇ (Badge 가 그린다). 보라 ◆ 는 기업마당 한 뜻이다(UNI-19).
  demo: COSMOS_COLORS.slate,
  muted: COSMOS_COLORS.slate,
} as const;

export type Tone = keyof typeof TONE_COLORS;

/**
 * **판정 4색** (27차 §3-E 「색 한 벌」) — 가능 · 충족 청록 · 확인 필요 호박 · 불가 · 문제 빨강 · 판정 전 회청.
 * 참가 판정(PASS · CHECK · FAIL)을 칠하는 곳 — 사업기회 · 이번 주 할 일 · 쉬운 보기 · 상세 패널 · 레이더 ·
 * 요구사항 정리표 · 지원사업 — 이 모두 여기서 읽는다. 「불가」는 어디서나 빨강이다(목록에서만 회색이던 UNI-10).
 */
export const VERDICT_TONES = { PASS: "ok", CHECK: "warn", FAIL: "fail", NONE: "muted" } as const satisfies Record<string, Tone>;
export type VerdictKey = keyof typeof VERDICT_TONES;

export const VERDICT_COLORS: Record<VerdictKey, string> = {
  PASS: TONE_COLORS[VERDICT_TONES.PASS],
  CHECK: TONE_COLORS[VERDICT_TONES.CHECK],
  FAIL: TONE_COLORS[VERDICT_TONES.FAIL],
  NONE: TONE_COLORS[VERDICT_TONES.NONE],
};

/**
 * 판정 상자(테두리 · 옅은 면)와 판정 문장 글자 — 쉬운 보기 판정 카드 · 상세 패널 판정 띠 · 지원사업 쉬운 보기가 같이 쓴다.
 * 빨강 글자만 `red-text`(결정 문장용 7:1 · globals.css)다. Tailwind 가 이 파일도 훑으므로 클래스는 글자 그대로 둔다.
 */
export const VERDICT_BOX_CLASS: Record<Exclude<VerdictKey, "NONE">, { box: string; text: string }> = {
  PASS: { box: "border-cosmos-cyan/50 bg-cosmos-cyan/10", text: "text-cosmos-cyan" },
  CHECK: { box: "border-cosmos-amber/50 bg-cosmos-amber/10", text: "text-cosmos-amber" },
  FAIL: { box: "border-cosmos-red/55 bg-cosmos-red/10", text: "text-cosmos-red-text" },
};
