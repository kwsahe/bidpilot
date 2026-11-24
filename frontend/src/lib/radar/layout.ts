/**
 * 통합 Opportunity Radar — 좌표·크기·색 계산.
 *
 * 3D(react-three-fiber)와 2D(SVG)가 **같은 함수**를 써서 같은 그림을 그린다.
 * 여기서는 단위 좌표(반지름 0~1)만 계산하고, 실제 픽셀/월드 크기는 각 렌더러가 곱한다.
 *
 * 인코딩 규칙 (범례·「읽는 법」과 반드시 일치해야 한다):
 *  - 중심까지의 거리 ← **마감까지 남은 시간의 순서.** 안쪽일수록 마감이 이르다.
 *    날짜 «수»가 아니라 이 화면에 실제로 있는 마감일들을 등간격으로 늘어놓은 사다리다.
 *    마감일이 없으면 축에 못 올리므로 축 **밖**(RADAR_RADIUS_UNDATED)에 세운다 — 「멀다」가 아니다.
 *  - 노드 크기      ← 회사 기준 검토 우선순위 점수. 이 화면 안에서의 **상대** 크기다.
 *    점수가 null 이면 **미확인**이며 0점이 아니다 → 크기로 말하지 않고 점선 테두리로 표시한다.
 *  - 방향(섹터)     ← 출처. 나라장터는 위쪽 섹터, 기업마당은 아래쪽 섹터에 모인다.
 *  - 링/pulse 세기  ← 마감 임박도의 **절대값**. 거리가 순서를 나르므로 이쪽이 절대값을 맡는다.
 *  - 모양           ← **출처와 무관하게 하나**(기체 심볼). 출처는 섹터 위치와 색이 나르므로
 *    모양까지 나누면 서로 다른 사물처럼 읽힌다. 색만으로 구분하지 않는 조건은 섹터가 만족시킨다.
 *
 * 위치 계산은 세 단계로 나뉜다 — 각 단계가 다른 정보를 담당한다.
 *     radius = radiusForDeadline(남은 일수, 마감여부, 마감 사다리)   // 중심 거리 = 마감 순서
 *     sector = sectorOf(출처)                                       // 방향     = 출처
 *     angle  = angleWithinSector(sector, 섹터 내 순번)              // 섹터 안에서 겹치지 않게
 * 각도의 **절대값**은 사용자에게 보여주지 않는다(방위 숫자 없음). 보여 주는 것은 섹터 이름이다.
 *
 * 왜 «값»이 아니라 «순서»인가 — 어떤 변수를 얹든 실제 값이 좁은 구간에 몰리면 노드가 한 띠에 뭉친다.
 * 점수를 쓰던 때는 62~81점이 몰려 축의 26%만 썼고, 마감 일수를 그대로 쓰면 마감 임박순 상위 20건이
 * D-1~D-7 뿐이라 20~34%로 도로 무너진다. 순서 축은 정렬·필터·건수와 무관하게 축을 100% 쓴다.
 * 대신 간격의 절대값이 흐려지므로, 링에 실제 D 값을 적고 화면 문구가 「날짜 수가 아니라 순서」라고 말한다.
 *
 * 순수 함수만 둔다 — Date.now()/Math.random() 을 쓰지 않는다(서버·클라이언트 렌더 결과가 같아야 한다).
 */

import type { SourceKind } from "@/components/ui/SourceBadge";
import {
  daysUntil,
  effectiveDeadline,
  formatDDay,
  isOpenEnded,
  registrationClosesFirst,
  pairOf,
  firstLabel,
  urgencyTierOf,
  withinDaysText,
  type UrgencyTier,
} from "@/lib/deadline";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { UNSCORED } from "@/lib/terms";
import { SOURCE_TYPE_LABELS, type SourceType, type UnifiedOpportunity } from "@/types/opportunity";

// ---------------------------------------------------------------------------
// 상수 — 반지름 띠
// ---------------------------------------------------------------------------

/** 축 시작 — 이 화면에서 **마감이 가장 이른** 항목이 놓이는 자리. 중심 관제탑과 겹치지 않는 최소값. */
export const RADAR_RADIUS_MIN = 0.34;
/** 축 끝 — 이 화면에서 마감이 가장 늦은 항목이 놓이는 자리. */
export const RADAR_AXIS_END = 0.86;
/**
 * 축 **밖** — 마감일이 없는 항목(상시 접수·예산 소진 시).
 * 「마감이 아주 멀다」는 뜻이 **아니라** 시간축에 올릴 수 없다는 뜻이다. 그래서 축 끝보다 밖에 따로 세운다.
 */
export const RADAR_RADIUS_UNDATED = 0.94;
/** 축 밖 — 이미 마감된 항목. */
export const RADAR_RADIUS_CLOSED = 1;
/** 스코프 바깥 경계 — 섹터 쐐기·스윕·바닥면 전용. 축의 뜻과 무관하다. */
export const RADAR_RADIUS_MAX = 1;

/** 노드 반지름(단위 좌표). 렌더러는 여기에 자기 배율만 곱한다 — 3D·2D 크기 규칙을 한 곳에 둔다. */
export const NODE_UNIT_MIN = 0.042;
export const NODE_UNIT_MAX = 0.092;

/** 가장 낮은 점수도 이만큼은 크다 — 누를 수 있는 대상이 사라지지 않게. */
const SIZE_FLOOR = 0.25;
/** 이 화면의 점수가 전부 같을 때. 크기로 구분되지 않는다는 뜻이므로 모두 중간값. */
const SIZE_FLAT = 0.6;
/** 점수 미확인 — **0점이 아니다.** 항상 점선 테두리와 함께 그려 크기로 되읽히지 않게 한다. */
const SIZE_UNKNOWN = 0.45;

export type RadarShape = "sphere" | "diamond";

/**
 * 긴급도는 **`lib/deadline` 이 정한다** (0920 §4-B-5 · ISSUE-078).
 *
 * 경계 값 3/7/14 가 여기에만 있어서, 상단 바와 목록은 `days <= 7` 을 인라인으로,
 * 위험 요약은 `days <= 3` 을 각자 적고 있었다 — 같은 공고가 화면에 따라 「마감 임박」
 * 이기도 하고 아니기도 했다. 여기서는 이름만 다시 내보낸다(호출부가 많다).
 */
export { URGENCY_LABELS, urgencyTierOf, type UrgencyTier } from "@/lib/deadline";

/** 링 세기 (0~1). reduced motion 이면 pulse 대신 링 두께로만 쓴다. */
const URGENCY_STRENGTH: Record<UrgencyTier, number> = {
  closed: 0,
  urgent: 1,
  soon: 0.55,
  watch: 0.22,
  none: 0,
};

// ---------------------------------------------------------------------------
// 순수 계산
// ---------------------------------------------------------------------------

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

/**
 * 각도 배치 보폭.
 *
 * 노드는 `count` 등분한 자리에 하나씩만 놓아 서로 겹치지 않게 한다. 그러면서도 순위가
 * 붙어 있는 항목(= 점수가 비슷해 반지름도 비슷한 항목)이 옆자리에 오지 않도록,
 * count 와 서로소인 보폭으로 자리를 건너뛴다. 무작위가 아니라 항상 같은 배치가 나온다.
 */
export function angularStride(count: number): number {
  if (count < 3) return 1;
  const target = Math.max(1, Math.round(count / 2.618));
  for (let delta = 0; delta < count; delta += 1) {
    for (const candidate of [target + delta, target - delta]) {
      if (candidate >= 1 && candidate < count && gcd(candidate, count) === 1) return candidate;
    }
  }
  return 1;
}

/**
 * 마감 사다리 — 이 화면에 실제로 있는 **서로 다른 D-day 값**만 모은 것.
 *
 * 반지름을 「남은 일수」에 직접 얹으면 병이 그대로 돌아온다. 실측: 마감 임박순 상위 20건은
 * D-1~D-7 뿐이라 절대 매핑을 쓰면 축 사용률이 20~34% 로 도로 무너진다.
 * 그래서 값이 아니라 **순서**에 못 박는다 — 화면에 있는 마감일들을 등간격으로 늘어놓는다.
 */
export interface DeadlineAxis {
  /** 오름차순, 중복 없는 D-day. 축에 올릴 항목이 없으면 빈 배열. */
  stops: number[];
  /** stops[i] 의 반지름. stops 와 길이가 같다. */
  radii: number[];
}

export function buildDeadlineAxis(
  days: readonly (number | null)[],
  closed: readonly boolean[],
): DeadlineAxis {
  const values = [
    ...new Set(days.filter((d, i): d is number => d !== null && d >= 0 && !closed[i])),
  ].sort((a, b) => a - b);
  const n = values.length;
  if (n === 0) return { stops: [], radii: [] };
  // 하나뿐이면 안쪽 끝에 붙이지 않는다 — 「가장 급하다」는 뜻이 아니라 「비교할 게 없다」는 뜻이다.
  if (n === 1) return { stops: values, radii: [(RADAR_RADIUS_MIN + RADAR_AXIS_END) / 2] };
  const span = RADAR_AXIS_END - RADAR_RADIUS_MIN;
  return { stops: values, radii: values.map((_, i) => RADAR_RADIUS_MIN + (span * i) / (n - 1)) };
}

/**
 * 남은 일수 → 중심으로부터의 거리. **노드와 안내 링이 같은 함수를 쓴다** —
 * 그래야 「D-7 링 안쪽 = 7일 이내」가 언제나 참이다.
 *
 * 지키는 불변식 두 개:
 *   단조 — d1 < d2 이면 radius(d1) <= radius(d2)
 *   동치 — 축 위 두 노드의 반지름이 같다 ⟺ D-day 가 같다
 */
export function radiusForDeadline(
  days: number | null,
  closed: boolean,
  axis: DeadlineAxis,
): number {
  if (closed || (days !== null && days < 0)) return RADAR_RADIUS_CLOSED;
  if (days === null) return RADAR_RADIUS_UNDATED;
  const { stops, radii } = axis;
  if (stops.length === 0) return RADAR_RADIUS_UNDATED;
  if (days <= stops[0]) return radii[0];
  if (days >= stops[stops.length - 1]) return radii[radii.length - 1];
  for (let i = 0; i < stops.length - 1; i += 1) {
    if (days <= stops[i + 1]) {
      const t = (days - stops[i]) / (stops[i + 1] - stops[i]);
      return radii[i] + (radii[i + 1] - radii[i]) * t;
    }
  }
  return radii[radii.length - 1];
}

/**
 * 점수 축 — 이 화면에 있는 점수의 최소·최대.
 *
 * 절대 축(0~100)을 쓸 수 없는 이유는 산수다. 실측 점수 폭이 62~81(19점)인데, 이걸 0~100 에
 * 얹으면 340px 캔버스에서 지름이 18.5~20.9px 즉 **2.4px** 차이다. 나란히 놓아도 구분되지 않는다.
 */
export interface ScoreAxis {
  min: number;
  max: number;
}

export function buildScoreAxis(scores: readonly (number | null)[]): ScoreAxis | null {
  const values = scores.filter((s): s is number => s !== null);
  if (values.length === 0) return null;
  return { min: Math.min(...values), max: Math.max(...values) };
}

/** 점수 → 상대 크기(0~1). 미확인은 크기로 말하지 않는다 — 점선 테두리가 따로 말한다. */
export function sizeForScore(score: number | null, axis: ScoreAxis | null): number {
  if (score === null || axis === null) return SIZE_UNKNOWN;
  if (axis.max <= axis.min) return SIZE_FLAT;
  const t = clamp((score - axis.min) / (axis.max - axis.min), 0, 1);
  return SIZE_FLOOR + (1 - SIZE_FLOOR) * t;
}

/** 노드 반지름(단위 좌표). 3D는 월드 배율, 2D는 px 배율을 곱해 쓴다. */
export function unitNodeRadius(size: number): number {
  return NODE_UNIT_MIN + (NODE_UNIT_MAX - NODE_UNIT_MIN) * clamp(size, 0, 1);
}

export interface RadarRing {
  /** 경계 원의 반지름. */
  radius: number;
  /** 이 경계가 뜻하는 남은 일수. 눈금 숫자의 단일 출처. */
  days: number;
  /** 3시 방향 빈틈에 적는 눈금 — "D-7". */
  tick: string;
  /** 9시 방향 빈틈에 적는 **안쪽 띠**의 이름. */
  label: string;
  hint: string;
  /** 띠 이름을 적을 반지름 (경계 바로 안쪽). */
  labelRadius: number;
}

/**
 * 링을 그릴 후보 경계(일). 축 범위 밖이면 그리지 않는다 — 없는 눈금을 적지 않는다.
 *
 * **내보낸다.** 레이더 「읽는 법」이 「D-3 · D-7 같은 숫자」를 손으로 적고 있었는데
 * (6차 보고 §3 끝의 미착수), 그러면 후보가 바뀔 때 설명만 거짓말이 된다.
 */
export const RING_DAY_CANDIDATES: ReadonlyArray<{ days: number; label: string }> = [
  // 「이번 주 · 이달 안」은 달력으로 읽혔다 — 실제는 7일 · 30일(30차 §3-F #27 · 사실 오류)
  { days: 3, label: "3일 안" },
  { days: 7, label: "7일 안" },
  { days: 14, label: "14일 안" },
  { days: 30, label: "30일 안" },
];
/** 링끼리 이만큼은 떨어져야 글자가 겹치지 않는다. */
const RING_MIN_GAP = 0.08;

/**
 * 안내 링 — **데이터에서 나온다.** 축에 그 날짜가 없으면 링도 없다.
 *
 * 고정 링(점수 70·45 경계)을 쓰던 때와 달리, 여기서는 링 위치가 화면마다 달라진다.
 * 대신 링 위의 숫자가 언제나 실제 값이라 「D-7 이라 적힌 원 안쪽 = 7일 이내」가 항상 참이다.
 */
export function buildRings(axis: DeadlineAxis): RadarRing[] {
  if (axis.stops.length === 0) return [];
  const first = axis.stops[0];
  const last = axis.stops[axis.stops.length - 1];
  const rings: RadarRing[] = [];
  for (const candidate of RING_DAY_CANDIDATES) {
    if (candidate.days < first || candidate.days > last) continue;
    const radius = radiusForDeadline(candidate.days, false, axis);
    if (rings.length > 0 && radius - rings[rings.length - 1].radius < RING_MIN_GAP) continue;
    if (radius - RADAR_RADIUS_MIN < RING_MIN_GAP / 2) continue;
    rings.push({
      radius,
      days: candidate.days,
      // 문자열을 다시 조립하지 않는다 — 그러면 days===0 에서 「D-Day」 대신 「D-0」이 된다.
      tick: formatDDay(candidate.days),
      label: candidate.label,
      hint: withinDaysText(candidate.days),
      labelRadius: radius - 0.055,
    });
  }
  return rings;
}

// ---------------------------------------------------------------------------
// 출처 섹터 — 레이더의 «방향»이 뜻하는 것
// ---------------------------------------------------------------------------

export interface SourceSectorSpec {
  /** 섹터 이름. 레이더 외곽에 이 글자를 적는다 (각도 숫자는 적지 않는다). */
  label: string;
  /** 섹터 중심 방향(도). 수학 좌표계 — 0°=3시, 90°=12시, 반시계 방향이 +. */
  centerDeg: number;
  /** 섹터가 차지하는 각도(도). 이웃 섹터와 겹치지 않게 둔다. */
  spanDeg: number;
}

/**
 * 출처 → 섹터.
 *
 * 위 절반은 나라장터(수주하는 입찰), 아래 절반은 기업마당(신청하는 지원사업)이다.
 * 두 섹터 사이에 30°씩 빈 각도를 남겨 두는데, 그 자리는 장식이 아니라 눈금 자리다
 * (왼쪽 빈틈 = 점수 띠 이름, 오른쪽 빈틈 = 점수 눈금). 섹터가 맞닿아 있으면 경계가 안 보인다.
 *
 * **출처를 추가할 때** — 레이더에 그릴 출처(`RadarSourceType`)에 값을 더하면 이 Record 가 컴파일 오류를 내므로
 * 빠뜨릴 수 없다. 세 곳이 되면 spanDeg 를 줄여 (예: 100°씩) 빈틈을 유지한다.
 * 각도 값은 여기 한 곳에만 있고 렌더러는 이 설정만 읽는다.
 * 직접 넣은 공고(`manual` · 38차 §3-E)는 레이더에 그리지 않는다 — `RadarShell` 이 거른다(사업기회 「직접 넣기 · 후보함」에서 본다).
 */
export type RadarSourceType = Exclude<SourceType, "manual">;

export const SOURCE_SECTORS: Record<RadarSourceType, SourceSectorSpec> = {
  g2b: { label: "나라장터 입찰", centerDeg: 90, spanDeg: 150 },
  bizinfo: { label: "기업마당 지원사업", centerDeg: 270, spanDeg: 150 },
};

// ---------------------------------------------------------------------------
// 스윕 (도는 빔) — 2D SVG 와 3D 캔버스가 **같은 속도·같은 방향**으로 돌아야 하므로 여기서 한 번만 정한다
// ---------------------------------------------------------------------------

/**
 * 스윕은 **장식이다.** 실시간 탐지를 뜻하지 않는다 — 조회 시각은 상단 telemetry 가 따로 적는다.
 * 그래도 관제 화면의 문법이므로, 두 화면이 서로 다른 속도로 돌면 같은 그림이 아니게 된다.
 *
 * 도는 방향은 **화면 기준 시계방향**이다.
 *   - 2D(SVG): `<animateTransform type="rotate" from="0" to="360">` — SVG 는 y축이 아래라
 *     각도가 커질수록 화면에서 시계방향으로 돈다.
 *   - 3D(three.js): 수학 좌표계(y축 위)라 같은 방향을 내려면 `rotation.z` 를 **음수로** 굴려야 한다.
 * 부호를 한쪽만 바꾸면 두 화면이 반대로 돈다.
 */
export const SWEEP_SECONDS = 9;
/** 빔 부채꼴이 덮는 각도(도). 선행 엣지가 밝고 뒤로 사그라든다. */
export const SWEEP_ARC_DEG = 58;

/**
 * 빔 꼬리의 불투명도. `t=0` 이 선행 엣지, `t=1` 이 꼬리 끝이다.
 *
 * **각도 방향** 페이드다 — 빔이 «막 지나간 자리»가 가장 밝고 뒤로 갈수록 사라진다.
 * 반경 방향(중심이 어둡고 바깥이 밝은)으로 만들면 레이더가 아니라 그냥 빛나는 파이 조각이 된다.
 * 두 화면이 **같은 모양**의 빔을 그려야 하므로 식은 여기 한 곳에만 둔다
 * (3D 는 꼭짓점 알파로, 2D 는 부채꼴 조각의 fill-opacity 로 같은 값을 쓴다).
 */
export const SWEEP_ALPHA_HEAD = 0.24;
export const SWEEP_ALPHA_FALLOFF = 2.6;

export function sweepAlphaAt(t: number): number {
  return (1 - t) ** SWEEP_ALPHA_FALLOFF * SWEEP_ALPHA_HEAD;
}

/** 빔이 지나간 뒤 접점이 사그라드는 시간(초). 한 바퀴(9초) 안에 충분히 어두워질 만큼 짧게. */
export const BLIP_DECAY_SECONDS = 1.9;
/**
 * 접점 밝기의 **바닥값**. 0 으로 두면 빔이 지나간 직후 말고는 접점이 없는 것처럼 보인다.
 * 화면에서 정보가 사라지면 안 되므로, 깜빡임은 이 바닥 위에서만 흔든다.
 *
 * 지켜야 하는 부등식: **가장 어두운 깜빡임이 「흐려진 항목」보다 밝아야 한다.**
 * 흐림(dim, 선택 시 나머지)이 0.4, 기본 밝기가 0.9 이므로
 *     0.9 × BLIP_FLOOR > 0.4   →   BLIP_FLOOR > 0.444
 * 이 깨지면 「빔이 방금 안 지나간 항목」과 「내가 흐려 놓은 항목」이 같은 밝기로 보인다.
 * 프론트엔드에는 테스트가 없으므로 이 부등식을 지키는 건 이 주석뿐이다.
 */
export const BLIP_FLOOR = 0.58;

const TWO_PI = Math.PI * 2;

/**
 * 빔이 `angle`(라디안, 수학 좌표계) 을 마지막으로 지나간 뒤 흐른 시간(초).
 *
 * 빔은 t=0 에 3시 방향(각도 0)에서 출발해 시계방향으로 돈다 → `beam(t) = -t·ω`.
 * 0 을 지나 한 바퀴 뒤 다시 같은 자리로 오므로 반환값은 항상 `[0, SWEEP_SECONDS)` 안에 있다.
 */
export function blipAgeSeconds(angle: number, elapsedSeconds: number): number {
  const omega = TWO_PI / SWEEP_SECONDS;
  const beam = -elapsedSeconds * omega;
  const delta = (((angle - beam) % TWO_PI) + TWO_PI) % TWO_PI;
  return delta / omega;
}

/** 접점 밝기 배수 0~1. 빔이 막 지나갔으면 1, 시간이 지나면 지수적으로 사그라든다. */
export function blipIntensity(angle: number, elapsedSeconds: number): number {
  return Math.exp(-blipAgeSeconds(angle, elapsedSeconds) / BLIP_DECAY_SECONDS);
}

/**
 * 한 주기 안에서 빔이 이 각도를 지나는 시각(초). `[0, SWEEP_SECONDS)`.
 * 2D 는 JS 시계가 없으므로 SMIL `<animate begin=…>` 오프셋으로 같은 타이밍을 낸다.
 */
export function blipPhaseSeconds(angle: number): number {
  const norm = ((-angle % TWO_PI) + TWO_PI) % TWO_PI;
  return (norm / TWO_PI) * SWEEP_SECONDS;
}

/** 섹터 사이 빈 각도의 중심(라디안). 눈금·띠 이름을 노드와 겹치지 않는 이 자리에 적는다. */
export const BAND_LABEL_ANGLE = Math.PI; // 9시 방향 빈틈
export const SCALE_TICK_ANGLE = 0; // 3시 방향 빈틈
/** 띠 이름 세 개를 서로 벌릴 각도(라디안). 빈틈(30°) 안에서만 흔든다. */
export const BAND_LABEL_STEP = (8 * Math.PI) / 180;

const DEG = Math.PI / 180;

/** 출처가 속한 섹터. */
export function sectorOf(sourceType: SourceType): SourceSectorSpec {
  return SOURCE_SECTORS[sourceType === "g2b" ? "g2b" : "bizinfo"];
}

/**
 * 섹터 안에서의 자리.
 *
 * 섹터를 `countInSector` 등분해 한 칸씩 차지한다. 그냥 순서대로 놓으면 점수가 비슷한
 * (= 반지름이 비슷한) 항목이 옆자리에 붙으므로, count 와 서로소인 보폭으로 건너뛴다.
 * `angularStride` 는 예전 전역 배치에서 쓰던 함수를 그대로 재사용한 것이다 — 무작위가 아니라
 * 같은 입력이면 항상 같은 배치가 나온다.
 */
export function angleWithinSector(
  sector: SourceSectorSpec,
  indexInSector: number,
  countInSector: number,
): number {
  if (countInSector <= 1) return sector.centerDeg * DEG;
  const stride = angularStride(countInSector);
  const slot = (indexInSector * stride) % countInSector;
  const startDeg = sector.centerDeg - sector.spanDeg / 2;
  return (startDeg + (sector.spanDeg * (slot + 0.5)) / countInSector) * DEG;
}

export function shapeOf(sourceType: SourceType): RadarShape {
  return sourceType === "g2b" ? "sphere" : "diamond";
}

/** 출처색. 마감된 항목은 회색으로 낮춘다. 색은 보조 신호이며 모양·텍스트가 항상 함께 간다. */
export function colorOf(item: UnifiedOpportunity): string {
  if (item.closed) return COSMOS_COLORS.slate;
  return item.source_type === "g2b" ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet;
}

/**
 * HTML 태그가 섞인 원문 요약을 평문으로 만든다.
 * 기업마당 summary 는 실제로 `<p>…</p>` 를 담고 있다 — 절대 HTML로 렌더하지 않는다.
 */
export function stripHtml(text: string | null): string {
  if (!text) return "";
  return text
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/(p|div|li|tr|h[1-6])>/gi, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#0?39;/gi, "'")
    .replace(/\s+/g, " ")
    .trim();
}

/** 검토 우선순위 숫자. 단위를 붙이지 않고(목록 「검토 우선순위 83」과 같게) null 은 「미산정」 — 절대 0으로 그리지 않는다 (27차 UNI-14). */
export function scoreText(score: number | null): string {
  return score === null ? UNSCORED : String(score);
}

/**
 * 마감 표시. 날짜가 없으면 원문 문구(‘상시 접수’ 등)를 그대로 쓴다.
 *
 * `apply_period_kind` 를 함께 넘긴다 — 예전에는 보지 않아서, 상시 접수인데 마감일이
 * 붙어 있으면 D-숫자가 나왔다 (0920 §4-B-5).
 */
export function deadlineText(item: UnifiedOpportunity, days: number | null): string {
  const pair = pairOf(item, item.deadline);
  // (2.0.6) 입찰 마감 원본이 아니라 실제 마감(effectiveDeadline)으로 가른다 — 입찰 마감이 비고 공고문 일정 · 등록 마감만 있는
  // 공고는 D-day(days)를 이미 그 마감으로 셌는데 글만 「마감일 미정」이었다(대시보드 상세 · 사업기회 행과 같은 마감).
  if (effectiveDeadline(pair)) {
    if (isOpenEnded(item.apply_period_kind)) return "상시·예산 소진 시";
    // D-day 는 더 이른 참가자격 등록 마감 기준이다(effectiveDeadline) — 그럴 때는 「등록」을 붙인다.
    // 순위 목록 · 3D 라벨 · 추적 카드가 입찰 마감처럼 적었다. 사업기회 목록과 같은 말 (27차 RDR-03).
    if (days !== null && !item.closed && item.source_type === "g2b" && registrationClosesFirst(pair)) {
      const label = firstLabel(pair);
      return days < 0 ? `${label} 지남` : `${label} ${formatDDay(days)}`;
    }
    return formatDDay(days);
  }
  return item.deadline_text ?? "마감일 미정";
}

/**
 * 응답의 데이터 출처 문자열 → 공통 출처 배지.
 * 실데이터·캐시·합성 샘플을 절대 섞어 보이지 않는다. 모르는 값은 「미실행」으로 둔다.
 */
export function sourceBadgeOf(
  source: string | null | undefined,
  sourceType: SourceType,
  pinned?: boolean | null,
): { kind: SourceKind; label: string } {
  const origin = sourceType === "g2b" ? "나라장터" : "기업마당";
  // 되살려 붙인 고정 공고는 목록 전체가 실시간이어도 방금 받아온 것이 아니다.
  if (pinned) return { kind: "pinned", label: "고정 공고" };
  if (source === "g2b") return { kind: "g2b", label: "나라장터 실시간" };
  if (source === "bizinfo") return { kind: "computed", label: "기업마당 실시간" };
  if (source === "cached") return { kind: "cached", label: `${origin} 캐시` };
  if (source === "sample") return { kind: "demo", label: `${origin} 가상 예시 공고` };
  return { kind: "not_run", label: `${origin} 상태 미상` };
}

// ---------------------------------------------------------------------------
// 노드
// ---------------------------------------------------------------------------

export interface RadarNode {
  id: string;
  item: UnifiedOpportunity;
  /** 화면에 보이는 순번 (0부터). 크기 계산의 기준. */
  index: number;
  /** 화면 표시용 순위 (1부터). */
  rank: number;
  /** 같은 출처 안에서의 순위. 화면이 적는 것은 이쪽이다 (0922 §4-B-7). */
  sourceRank: number;
  sourceTotal: number;
  shape: RadarShape;
  color: string;
  /** 출처 라벨 — 색 없이도 출처를 알 수 있게 항상 텍스트로 같이 쓴다. */
  sourceLabel: string;
  /** 0(중심)~1(외곽). 회사 적합도가 높을수록 작다. */
  radius: number;
  /** 라디안. */
  angle: number;
  /** 단위 좌표 (-1~1). z 는 3D 깊이감을 위한 아주 작은 흔들림이다. */
  x: number;
  y: number;
  z: number;
  /** 0.3 / 0.62 / 1 세 단계 상대 크기. 현재 정렬 기준 상위일수록 크다. */
  size: number;
  /** 단위 좌표 기준 노드 반지름 — 3D·2D가 같은 값을 쓴다. */
  unitRadius: number;
  urgency: UrgencyTier;
  /** 0~1 링/pulse 세기. */
  urgencyStrength: number;
  /** 남은 일수. 마감일이 없거나 아직 시각을 모르면 null. */
  days: number | null;
  deadlineLabel: string;
  scoreUnknown: boolean;
  /**
   * 「참여 안 함」으로 정한 공고인가 (0920 §4-B-3 · ISSUE-076-d).
   *
   * 레이더가 결정을 몰라서, 담당자가 참여하지 않기로 한 공고가 「우선 검토」로 한복판에
   * 남아 있었다. 지우지는 않는다 — 결정을 되돌리는 일이 있다. 흐리게 하고 뒤로 보낸다.
   */
  declined: boolean;
  closed: boolean;
  /** 노드 옆에 띄우는 짧은 제목. */
  shortTitle: string;
}

export interface RadarLayout {
  nodes: RadarNode[];
  /** 이 화면의 마감 사다리. 노드·링이 같이 쓴다. 축에 올릴 항목이 없으면 stops 가 비어 있다. */
  deadlineAxis: DeadlineAxis;
  /** 이 화면의 점수 범위. 점수가 하나도 없으면 null. */
  scoreAxis: ScoreAxis | null;
  /** 실제로 그릴 안내 링. 축에 그 날짜가 없으면 링도 없다 — 없는 눈금을 적지 않는다. */
  rings: RadarRing[];
  g2bCount: number;
  bizinfoCount: number;
  /** 점수를 계산할 수 없는 항목 수. 크기가 아니라 점선 테두리로 표시한다. */
  unknownScoreCount: number;
  /** 마감 임박(D-3 이하) 항목 수. */
  urgentCount: number;
  /** 이미 마감된 항목 수(마감 포함으로 볼 때만 0보다 크다). */
  closedCount: number;
  /**
   * 띠 이름(사흘 안·이번 주·…)을 적을 방향(라디안).
   * 섹터 **사이의 빈 각도**라서 노드와 겹치지 않는다.
   */
  bandLabelAngle: number;
  /** 띠 이름을 서로 한 칸씩 떨어뜨릴 각도(라디안). 라벨이 같은 자리에 겹치지 않게 한다. */
  bandLabelStep: number;
  /** 그릴 섹터 — 이름·방향·폭과 그 안에 실제로 들어간 건수. 렌더러는 이것만 보고 그린다. */
  sectors: RadarSectorView[];
}

/** 화면에 그릴 섹터 하나. */
export interface RadarSectorView {
  sourceType: SourceType;
  spec: SourceSectorSpec;
  /** 이 섹터에 실제로 배치된 항목 수. 0이면 흐리게 그린다(자리는 남긴다). */
  count: number;
  color: string;
}

/** 항목이 없어도 섹터 틀은 그린다 — 「여기가 나라장터 자리」라는 정보 자체가 유용하다. */
function emptySectors(): RadarSectorView[] {
  return (Object.keys(SOURCE_SECTORS) as RadarSourceType[]).map((sourceType) => ({
    sourceType,
    spec: SOURCE_SECTORS[sourceType],
    count: 0,
    color: sourceType === "g2b" ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet,
  }));
}

const EMPTY_LAYOUT: RadarLayout = {
  nodes: [],
  deadlineAxis: { stops: [], radii: [] },
  scoreAxis: null,
  rings: [],
  g2bCount: 0,
  bizinfoCount: 0,
  unknownScoreCount: 0,
  urgentCount: 0,
  closedCount: 0,
  bandLabelAngle: BAND_LABEL_ANGLE,
  bandLabelStep: BAND_LABEL_STEP,
  sectors: emptySectors(),
};

/** 노드 옆 라벨용 짧은 제목 — 18자까지. 전체 제목은 상세 패널에서 본다. */
export function shortTitleOf(title: string): string {
  const clean = stripHtml(title);
  return clean.length <= 18 ? clean : `${clean.slice(0, 17).trimEnd()}…`;
}

/**
 * 겹침 풀기 — **각도만 흔든다. 반지름은 건드리지 않는다.**
 *
 * 예전에는 반지름을 밀어냈다. 반지름이 점수였을 때는 「조금 더 바깥」이 「조금 더 낮은 점수」라
 * 견딜 만한 거짓말이었지만, 지금 반지름은 마감 사다리의 칸이라 밀어내는 순간
 * 「반지름이 같다 ⟺ 마감이 같다」는 불변식이 깨진다. 실측으로도 예전 방식은
 * 12건 중 7개, 20건 중 15개의 반지름을 옮기고 있었다 — 그림을 위해 뜻을 너무 많이 바꿨다.
 *
 * 각도는 다르다. 섹터 **안에서의** 각도는 원래 뜻이 없다(보여 주는 것은 섹터 이름뿐이다).
 * 그래서 같은 칸에 선 노드들을 자기 섹터 안에서만 좌우로 벌린다. 섹터를 벗어나지 않으므로
 * 「방향 = 출처」는 그대로다. 벌릴 여지가 없으면 그대로 둔다.
 */
function separate(nodes: RadarNode[]): void {
  const byRadius = new Map<string, RadarNode[]>();
  for (const node of nodes) {
    const key = `${node.item.source_type}:${node.radius.toFixed(4)}`;
    const bucket = byRadius.get(key);
    if (bucket) bucket.push(node);
    else byRadius.set(key, [node]);
  }

  for (const bucket of byRadius.values()) {
    if (bucket.length < 2) continue;
    const sector = sectorOf(bucket[0].item.source_type);
    const halfSpan = ((sector.spanDeg / 2) * DEG) * 0.92; // 섹터 경계에 딱 붙지 않게 조금 안쪽까지만
    const centerRad = sector.centerDeg * DEG;
    // 같은 칸에 선 노드가 몇이든 섹터 폭을 등분해 나눠 선다. 순서는 index 로 고정 — 매번 같은 그림이다.
    const ordered = [...bucket].sort((a, b) => a.index - b.index);
    const count = ordered.length;
    ordered.forEach((node, i) => {
      const ratio = count === 1 ? 0.5 : i / (count - 1);
      node.angle = centerRad - halfSpan + halfSpan * 2 * ratio;
      node.x = Math.cos(node.angle) * node.radius;
      node.y = Math.sin(node.angle) * node.radius;
    });
  }
}

/**
 * 목록 → 레이더 배치.
 * @param items  이미 정렬·자른 목록 (배열 순서가 곧 현재 정렬 순위다)
 * @param nowMs  현재 시각(ms). 서버 렌더 중에는 null — 마감 계산을 건너뛴다.
 */
export function buildRadarLayout(items: UnifiedOpportunity[], nowMs: number | null): RadarLayout {
  if (items.length === 0) return EMPTY_LAYOUT;

  // 출처별로 묶는다 — 각도는 섹터 안에서만 나눈다. 섹터 배정이 곧 «방향의 뜻»이다.
  const bySource = new Map<SourceType, string[]>();
  for (const item of items) {
    const bucket = bySource.get(item.source_type);
    if (bucket) bucket.push(item.id);
    else bySource.set(item.source_type, [item.id]);
  }
  const angleById = new Map<string, number>();
  for (const [sourceType, ids] of bySource) {
    const sector = sectorOf(sourceType);
    ids.forEach((id, indexInSector) => {
      angleById.set(id, angleWithinSector(sector, indexInSector, ids.length));
    });
  }

  // 두 축을 먼저 만든다 — 둘 다 «이 화면에 실제로 있는 값»에서 나온다.
  // **실제 데드라인**을 본다 — 참가자격 등록이 먼저 닫히면 그쪽이다 (0922 §4-B-8).
  const allDays = items.map((item) =>
    nowMs === null
      ? null
      : daysUntil(
          effectiveDeadline(pairOf(item, item.deadline)),
          nowMs,
        ),
  );
  const deadlineAxis = buildDeadlineAxis(allDays, items.map((item) => item.closed));
  const scoreAxis = buildScoreAxis(items.map((item) => item.company_priority_score));

  const nodes: RadarNode[] = items.map((item, index) => {
    const days = allDays[index];
    const radius = radiusForDeadline(days, item.closed, deadlineAxis);
    const angle = angleById.get(item.id) ?? sectorOf(item.source_type).centerDeg * DEG;
    const size = sizeForScore(item.company_priority_score, scoreAxis);
    const urgency = urgencyTierOf(days, item.closed);
    return {
      id: item.id,
      item,
      index,
      rank: index + 1,
      // 화면에 적는 순위는 **같은 출처 안에서의 순위**다 (0922 §4-B-7).
      //
      // `rank` 는 이 화면이 그린 배열 안의 자리라 두 출처가 섞여 있다. 나라장터(우리가
      // 수주하는 사업)와 기업마당(우리가 지원금을 신청하는 사업)을 한 축에 세워
      // 「1위 기업마당 SW개발자 채용」이라고 적으면 담당자가 그것을 이번 주의 첫 일로 읽는다.
      sourceRank: item.source_rank ?? index + 1,
      sourceTotal: item.source_total ?? items.length,
      shape: shapeOf(item.source_type),
      color: colorOf(item),
      sourceLabel: SOURCE_TYPE_LABELS[item.source_type],
      radius,
      angle,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
      // 결정론적인 아주 작은 깊이차 — 원근감만 주고 "중심까지의 거리" 해석을 흐리지 않는다.
      z: Math.sin(index * 1.7) * 0.06,
      size,
      unitRadius: unitNodeRadius(size),
      urgency,
      urgencyStrength: URGENCY_STRENGTH[urgency],
      days,
      deadlineLabel: deadlineText(item, days),
      scoreUnknown: item.company_priority_score === null,
      declined: item.analysis_state?.decision === "NO_GO",
      closed: item.closed,
      shortTitle: shortTitleOf(item.title),
    };
  });

  // 겹침 풀기는 **반지름만** 바꾸므로 각도(=섹터)는 그대로 유지된다.
  // 즉 노드가 자기 출처 섹터를 벗어나는 일은 구조적으로 일어나지 않는다.
  separate(nodes);

  return {
    nodes,
    deadlineAxis,
    scoreAxis,
    rings: buildRings(deadlineAxis),
    g2bCount: nodes.filter((n) => n.item.source_type === "g2b").length,
    bizinfoCount: nodes.filter((n) => n.item.source_type === "bizinfo").length,
    unknownScoreCount: nodes.filter((n) => n.scoreUnknown).length,
    urgentCount: nodes.filter((n) => n.urgency === "urgent").length,
    closedCount: nodes.filter((n) => n.closed).length,
    bandLabelAngle: BAND_LABEL_ANGLE,
    bandLabelStep: BAND_LABEL_STEP,
    sectors: emptySectors().map((sector) => ({
      ...sector,
      count: nodes.filter((n) => n.item.source_type === sector.sourceType).length,
    })),
  };
}

/** 3D/2D 캔버스를 감싸는 div 의 aria-label. 화면을 못 보는 사람에게 그림의 뜻을 말해 준다. */
export function radarAriaLabel(layout: RadarLayout, companyName: string): string {
  if (layout.nodes.length === 0) {
    return `사업기회 레이더 — 현재 회사 ${companyName} 기준으로 표시할 사업기회가 없습니다.`;
  }
  // 두 축이 서로 다른 항목을 1위로 지목한다. 화면을 못 보는 사람에게는 **둘 다** 말해야 한다 —
  // 「가장 급한 것」과 「점수가 가장 높은 것」이 같은 사업이라는 보장이 없다.
  const onAxis = layout.nodes.filter((n) => !n.closed && n.days !== null);
  const soonest = onAxis.length > 0
    ? onAxis.reduce((a, b) => ((b.days ?? 0) < (a.days ?? 0) ? b : a))
    : null;
  const scored = layout.nodes.filter((n) => !n.scoreUnknown);
  const best = scored.length > 0
    ? scored.reduce((a, b) =>
        (b.item.company_priority_score ?? 0) > (a.item.company_priority_score ?? 0) ? b : a,
      )
    : null;
  const undated = layout.nodes.filter((n) => !n.closed && n.days === null).length;
  return (
    `사업기회 레이더 — 가운데는 현재 회사 ${companyName}, 주변은 사업기회 ${layout.nodes.length}건입니다. ` +
    `위쪽 절반은 나라장터 입찰 ${layout.g2bCount}건(청록색), 아래쪽 절반은 기업마당 지원사업 ${layout.bizinfoCount}건(보라색)입니다. ` +
    // 두 축을 한 문장에 붙여 적는다 — 마감은 점수에 들어가지 않는다 (0923 §3-2 · ISSUE-092).
    // 크기의 이름은 목록 · 상세와 같은 「검토 우선순위」 (27차 RDR-22).
    `방향은 출처, 거리는 마감, 크기는 검토 우선순위입니다. 검토 우선순위에는 마감이 들어가지 않습니다. ` +
    (soonest
      ? `마감이 가장 급한 것은 ${stripHtml(soonest.item.title)} (${soonest.sourceLabel}, ${soonest.deadlineLabel}). `
      : "") +
    (best
      ? `검토 우선순위가 가장 높은 것은 ${stripHtml(best.item.title)} (${best.sourceLabel}, 검토 우선순위 ${scoreText(best.item.company_priority_score)}). `
      : "") +
    (undated > 0 ? `마감일이 없어 축 밖에 둔 항목이 ${undated}건 있습니다. ` : "") +
    `같은 항목을 「순위 목록」 버튼에서 키보드로 고를 수 있습니다.`
  );
}

/**
 * 3D 씬과 2D SVG 대체 화면이 **똑같이** 받는 props.
 * 두 렌더러는 서로를 대체할 수 있어야 하므로 계약을 한 곳에 둔다 (React 의존 없음).
 */
export interface RadarSceneProps {
  layout: RadarLayout;
  selectedId: string | null;
  hoveredId: string | null;
  /** null 이면 선택 해제. */
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
  /** `prefers-reduced-motion: reduce` — 지속 회전·강한 pulse 를 끈다. */
  reducedMotion: boolean;
  /** 중심 노드에 쓸 현재 회사 이름. */
  companyName: string;
  /** 좁은 화면(모바일) — 라벨을 줄이고 글자를 키운다. */
  compact: boolean;
}

/**
 * 라벨을 띄울 노드인지 — **전부** 띄운다 (ISSUE-109 · prompt_01 §4-A-3).
 *
 * 예전에는 `!compact && node.index < 3` 이라 1·2·3위와 선택·hover 만 이름이 있었다.
 * 실측으로 12점 중 9점이 무명이었고, 담당자는 「각 3D 요소에 설명하는 문구가 디폴트로
 * 들어가야 할 듯」이라고 짚었다. 겹침은 숨기는 것으로 막을 일이 아니라 **짧게 적어**
 * 막는다 — 전체 라벨은 「순위 · 제목 앞 10자 · D-day」 한 줄이고(`RadarScene3D`),
 * 좁은 화면에서는 순위 번호만 남는다.
 *
 * 남겨 둔 인자(`activeId`)는 호출부가 그대로 쓰고 있고, 선택·hover 는 여전히 **긴**
 * 라벨을 받는다 — 무엇을 보여줄지는 호출부가 이 값으로 가른다.
 */
export function shouldShowLabel(node: RadarNode, activeId: string | null, compact: boolean): boolean {
  // 인자는 호출부 계약을 지키려고 남긴다. 「띄울지」는 이제 언제나 참이고, 「무엇을
  // 적을지」(짧게/넓게)는 호출부가 activeId·compact 로 가른다.
  void node;
  void activeId;
  void compact;
  return true;
}

/**
 * 띠 이름을 적을 각도. 같은 방향에 두면 서로 겹치므로 한 칸(노드 자리 간격)씩 벌린다.
 * 벌린 자리도 여전히 노드 자리 **사이**의 빈 각도다.
 *
 * 라벨 개수가 **고정이 아니다** — 링은 데이터에서 나오므로 0~4개가 된다.
 * 그래서 개수와 무관하게 가운데를 기준으로 대칭이 되도록 벌린다
 * (예전에는 `ringIndex - 1` 로 세 개를 전제하고 있었다).
 */
export function bandLabelAngleAt(layout: RadarLayout, ringIndex: number): number {
  const count = Math.max(1, layout.rings.length);
  const offset = ringIndex - (count - 1) / 2;
  return layout.bandLabelAngle + offset * layout.bandLabelStep;
}

/** 원(링) 하나를 이루는 점 배열. 3D Line·2D path 가 같은 함수를 쓴다. */
export function ringPoints(radius: number, segments = 96): Array<[number, number]> {
  const points: Array<[number, number]> = [];
  for (let i = 0; i <= segments; i += 1) {
    const angle = (i / segments) * Math.PI * 2;
    points.push([Math.cos(angle) * radius, Math.sin(angle) * radius]);
  }
  return points;
}
