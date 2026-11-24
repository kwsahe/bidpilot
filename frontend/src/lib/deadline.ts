/**
 * 마감 상태 용어 — 한 곳에서만 정한다.
 *
 * 마감 «여부» 판정은 백엔드가 이미 한다(opportunity_service._closed).
 * 나라장터는 notice.deadline_at, 기업마당은 apply_end → 그날 23:59 KST 로 정규화한 뒤
 * 같은 규칙으로 비교하고, 결과가 UnifiedOpportunity.closed 로 내려온다.
 * 프론트는 그 플래그를 **다시 계산하지 않고** 용어만 고른다.
 *
 * 이 파일이 생기기 전에는 용어가 화면마다 흩어져 있었고, 그중 하나는
 * 출처만 보고 「신청 종료」를 고정으로 붙여서 D-29 인 공고에도 「신청 종료 D-29」가 찍혔다.
 * (frontend/src/app/opportunities/page.tsx 의 옛 1280행)
 *
 * 용어 규칙 — 「마감」은 아직 남은 기한, 「종료」는 이미 지난 것이다:
 *
 *   출처        아직 안 지남    이미 지남
 *   나라장터    입찰 마감       입찰 종료
 *   기업마당    신청 마감       신청 종료
 *
 * 날짜가 아닌 접수(상시·예산 소진 시)는 위 축과 무관하므로 따로 뺀다.
 */

/** 기업마당 접수 기간의 «성격». 백엔드 SupportProgram.apply_period_kind 와 같은 값이다. */
export type ApplyPeriodKind = "dated" | "always_open" | "until_budget" | "conditional" | "unknown";

export type DeadlineSource = "g2b" | "bizinfo";

export interface DeadlineTermInput {
  source: DeadlineSource;
  /** 백엔드가 판정한 마감 여부. 프론트에서 다시 계산하지 말 것. */
  closed: boolean;
  /** 접수 기간 성격. 기업마당만 의미가 있다. */
  periodKind?: ApplyPeriodKind | null;
  /** 마감일(ISO). 없으면 날짜 없는 접수이거나 미상이다. */
  deadline?: string | null;
}

/** 날짜 축을 쓰지 않는 접수인가 — 상시 / 예산 소진 시. */
export function isOpenEnded(periodKind?: ApplyPeriodKind | null): boolean {
  return periodKind === "always_open" || periodKind === "until_budget";
}

/**
 * 화면에 쓸 마감 용어 한 마디.
 *
 * 상시·예산 소진 건은 마감/종료 어느 쪽도 아니므로 「상시·예산 소진 시」로 내보낸다.
 * 마감일이 아예 없고 성격도 모르면 「접수 기간 미정」이다 — 「종료」로 단정하지 않는다.
 */
export function deadlineTerm({ source, closed, periodKind, deadline }: DeadlineTermInput): string {
  if (isOpenEnded(periodKind)) return "상시·예산 소진 시";
  // 끝난 공고는 날짜가 비어도 「끝남」이다 — 「접수 기간 미정」으로 적으면 아직 받는 공고로 읽혔다(대시보드 머리 UI e 와 같은 말 · 2.0.6 제안서 화면).
  if (!deadline && closed) return source === "g2b" ? "입찰 종료" : "신청 종료";
  if (!deadline && (periodKind === "conditional" || periodKind === "unknown" || periodKind == null)) {
    // 날짜가 없는데 상시도 아니다 — 공고 원문을 그대로 보여 주는 편이 맞고,
    // 라벨은 단정하지 않는다. 호출부가 deadline_text 를 옆에 붙인다.
    return "접수 기간 미정";
  }
  if (source === "g2b") return closed ? "입찰 종료" : "입찰 마감";
  return closed ? "신청 종료" : "신청 마감";
}

/**
 * 기업마당 `apply_end` 는 날짜만(YYYY-MM-DD) 온다.
 * 그대로 Date.parse 하면 UTC 자정 = KST 09:00 으로 읽혀,
 * 백엔드 기준(그날 23:59 KST)보다 약 15시간 이르게 마감으로 잡힌다.
 * 백엔드와 같은 순간을 가리키도록 맞춘다.
 */
export function normalizeApplyEnd(applyEnd: string | null | undefined): string | null {
  if (!applyEnd) return null;
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(applyEnd.trim());
  if (!dateOnly) return applyEnd;
  return `${dateOnly[1]}-${dateOnly[2]}-${dateOnly[3]}T23:59:00+09:00`;
}

// ---------------------------------------------------------------------------
// D-day — 정의는 여기 하나뿐이다
// ---------------------------------------------------------------------------

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * 한국시간 기준 «며칠째인가». 자정마다 1 씩 오른다.
 *
 * D-day 를 `Math.ceil((마감 - 지금) / 하루)` 로 세면 **마감 시각**에 결과가 끌려간다.
 * 같은 9월 20일 마감이라도 23:59 로 적힌 기업마당은 D-5, 09:00(UTC 자정)으로 읽힌
 * 같은 값은 D-4 가 나왔다. 실제로 그렇게 어긋나 있었다 — 대시보드만 D-4, 나머지는 D-5.
 * 달력 날짜 차이로 세면 시각과 무관하게 한 값이 나온다.
 */
function kstDayNumber(ms: number): number {
  return Math.floor((ms + KST_OFFSET_MS) / DAY_MS);
}

/** 마감 문자열을 시각(ms)으로. 못 읽으면 null — 0 으로 꾸미지 않는다. */
export function deadlineMs(deadline: string | null | undefined): number | null {
  if (!deadline) return null;
  const ms = new Date(deadline).getTime();
  return Number.isNaN(ms) ? null : ms;
}

/**
 * 마감까지 남은 **달력 일수**(KST). 모든 화면이 이 함수 하나만 쓴다.
 *
 * - 이미 지난 마감은 -1 을 돌려준다. 마감일 당일이라도 **시각이 지났으면 D-Day 가 아니다.**
 * - 날짜만 있는 기업마당 값은 호출 전에 `normalizeApplyEnd` 로 23:59 KST 를 붙여야 한다.
 *   (그래야 마감일 «당일»이 D-Day 로 남는다. 날짜를 그대로 넘기면 UTC 자정 = 그날 09:00
 *   으로 읽혀 오전에 이미 마감으로 찍힌다.)
 */
export function daysUntil(deadline: string | null | undefined, nowMs: number): number | null {
  const ms = deadlineMs(deadline);
  if (ms === null) return null;
  if (ms <= nowMs) return -1;
  return kstDayNumber(ms) - kstDayNumber(nowMs);
}

/** 기업마당 지원사업의 마감 시각. 날짜만 오는 값을 그날 23:59 KST 로 맞춘다. */
export function supportDeadlineIso(program: { apply_end?: string | null }): string | null {
  return normalizeApplyEnd(program.apply_end ?? null);
}

/**
 * D-day 한 마디. 날짜 축을 쓰지 않는 접수는 남은 일수를 세지 않는다.
 *
 * 화면마다 「상시 접수인데 D-… 」가 찍히지 않도록 여기서 한 번에 갈라낸다.
 */
export function formatDDay(days: number | null): string {
  if (days === null) return "마감일 미정";
  if (days < 0) return "마감";
  if (days === 0) return "D-Day";
  return `D-${days}`;
}

export interface DDayInput {
  /** 이미 정규화된 마감 시각(ISO). 기업마당이면 supportDeadlineIso 를 거친 값. */
  deadline: string | null | undefined;
  periodKind?: ApplyPeriodKind | null;
  /** 지금 시각. 서버 렌더처럼 모를 때는 null — 「D-…」로 둔다. */
  nowMs: number | null;
}

/** 화면에 그대로 찍는 D-day 문구. 상시·예산 소진·미정을 D-숫자로 만들지 않는다. */
export function dDayText({ deadline, periodKind, nowMs }: DDayInput): string {
  if (isOpenEnded(periodKind)) return "상시·예산 소진 시";
  if (!deadline) return "마감일 미정";
  if (nowMs === null) return "D-…";
  return formatDDay(daysUntil(deadline, nowMs));
}

// ---------------------------------------------------------------------------
// 화면이 각자 만들고 있던 것들 — 여기로 모은다 (0920 §4-B-5 · ISSUE-078)
// ---------------------------------------------------------------------------

/**
 * 마감 날짜 한 줄. **한국시간 고정**이다.
 *
 * 같은 마감 하나가 화면마다 다른 글자였다 — 3D 중앙 카드는 「2026.09.30」(자체 포맷터,
 * 브라우저 시간대), 상세 패널은 「2026. 9. 30. 오후 6:00」, 상단 바 툴팁은 「2026. 9. 30.」.
 * 한 공고의 같은 값이 같은 세션 안에서 세 가지로 보였다.
 *
 * `short` 는 3D 라벨처럼 폭이 좁은 자리를 위한 것이다 — 사본을 만들지 말고 이 옵션을 쓴다.
 */
export function formatDeadlineDate(deadline: string | null | undefined, opts?: { short?: boolean }): string {
  const ms = deadlineMs(deadline);
  if (ms === null) return "마감일 미정";
  const date = new Date(ms);
  if (opts?.short) {
    // Intl 로 부품을 뽑아 쓴다 — getFullYear() 는 브라우저 시간대라 하루가 어긋난다.
    const parts = new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
    return `${pick("year")}.${pick("month")}.${pick("day")}`;
  }
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium" }).format(date);
}

/**
 * 마감이 **지난 지 며칠인가** (KST 달력일). 아직 안 지났거나 모르면 null.
 *
 * `daysUntil` 은 지난 마감을 전부 -1 로 뭉친다 — 「얼마나 지났는지」를 알 수 없다.
 * 검토 중 목록은 그 값이 필요하다(「마감 지남 3일」).
 */
export function daysOverdue(deadline: string | null | undefined, nowMs: number): number | null {
  const ms = deadlineMs(deadline);
  if (ms === null || ms > nowMs) return null;
  return Math.max(0, kstDayNumber(nowMs) - kstDayNumber(ms));
}

/**
 * 지난 마감까지 포함한 한 마디. 「D--3」은 읽히지 않는다.
 *
 * `formatDDay` 는 지난 것을 그냥 「마감」이라고만 한다. 검토 중 목록처럼 **얼마나
 * 지났는지**가 일인 화면은 이것을 쓴다.
 */
export function dDayOrOverdueText(deadline: string | null | undefined, nowMs: number | null): string {
  if (!deadline) return "마감일 미정";
  if (nowMs === null) return "D-…";
  const over = daysOverdue(deadline, nowMs);
  if (over !== null) return over === 0 ? "오늘 마감" : `마감 지남 ${over}일`;
  return formatDDay(daysUntil(deadline, nowMs));
}

/**
 * 「n일 안 마감」. 띠·목록 조건·레이더 링 설명이 같은 말을 쓰게 한다.
 * 맨 「마감 N」은 **이미 마감된 것**에만 쓴다 — 대시보드 띠 「마감 27」(곧 마감)과 선택기 「마감 68건 보기」(지난 것)가
 * 한 화면에서 반대 뜻이었다 (27차 UNI-06).
 */
export function withinDaysText(days: number): string {
  return `${days}일 안 마감`;
}

// --- 긴급도 ----------------------------------------------------------------

/**
 * 마감이 얼마나 급한가. **경계 값은 여기 한 곳에만 있다.**
 *
 * 예전에는 레이더가 3/7/14 로, 상단 바와 목록이 `days <= 7` 인라인으로, 위험 요약이
 * `days <= 3` 으로 각자 판정했다. 같은 공고가 화면에 따라 「마감 임박」이기도 하고
 * 아니기도 했다.
 */
export type UrgencyTier = "closed" | "urgent" | "soon" | "watch" | "none";

export const URGENCY_LABELS: Record<UrgencyTier, string> = {
  closed: "마감",
  urgent: "마감 임박",
  soon: "마감 주의",
  watch: "여유 있음",
  none: "마감일 없음",
};

/**
 * 긴급도 경계(일). **숫자가 화면 글자로 나가는 곳은 전부 여기서 읽는다.**
 *
 * 6차가 경계 «판정»은 이 파일로 모았지만, 레이더 「읽는 법」은 「D-3 이하가 가장 강함」을
 * 손으로 적어 두었다(6차 보고 §3 끝의 미착수). 값이 바뀌면 설명만 거짓말이 된다.
 */
export const URGENCY_DAYS = { urgent: 3, soon: 7, watch: 14 } as const;

export function urgencyTierOf(days: number | null, closed: boolean): UrgencyTier {
  if (closed) return "closed";
  if (days === null) return "none";
  if (days < 0) return "closed";
  if (days <= URGENCY_DAYS.urgent) return "urgent";
  if (days <= URGENCY_DAYS.soon) return "soon";
  if (days <= URGENCY_DAYS.watch) return "watch";
  return "none";
}

// ---------------------------------------------------------------------------
// 두 개의 마감 — 등록마감과 입찰마감 (0922.md §4-B-8)
// ---------------------------------------------------------------------------
//
// 나라장터 공고에는 마감이 둘이다. **실제 데드라인은 참가자격 등록 마감**
// (`bidQlfctRgstDt`) 쪽인 경우가 많다 — 한남대·KISTI 는 입찰마감이 9-28 인데 등록은
// 9-27 18:00 에 닫힌다. 담당자가 9-28 을 보고 준비하면 늦는다.
//
// 그래서 카드는 두 줄로 적고, D-day·정렬·「이번 주 할 일」은 **더 이른 쪽**을 쓴다.

export interface DeadlinePair {
  /** 참가자격 등록·공동수급협정 마감 — 공고문 일정표 마감(참가신청 · 입찰등록 · 제출)이 더 이르면 그것(43차 결정 1). 없으면 null. */
  qualification: string | null;
  /** 입찰(신청) 마감. 없으면 null — 개찰일을 넣지 않는다(43차 H1). */
  bid: string | null;
  /** `qualification` 자리의 이름 — 공고문 일정 마감이면 「참가신청 마감」 등, 없으면 「등록마감」(`firstLabel`). */
  firstLabel?: string | null;
  /** `qualification` 자리가 날짜만 있던 공고문 일정 마감이면 false(44차 M3) — 시각 대신 「(시각 원문 확인)」. */
  firstTimeKnown?: boolean;
}

/** 시각을 모르는 마감 뒤에 붙는 말(44차 M3) — 백엔드 `practical_priority.TIME_UNKNOWN_NOTE` 와 같은 글. */
export const TIME_UNKNOWN_NOTE = "(시각 원문 확인)";

/** `qualification` 자리의 이름 — 「등록마감」(나라장터 참가자격 등록) 또는 공고문 일정 마감 이름(43차). */
export function firstLabel(pair: DeadlinePair): string {
  return pair.firstLabel || "등록마감";
}

/**
 * 목록 행 · 레이더 · 이번 주 할 일이 읽는 마감 짝 — 등록마감과 공고문 일정표 마감 중 **이른 쪽**을 앞자리에 둔다(43차 결정 1 · M1).
 * 백엔드 `practical_priority.effective_deadline` 과 같은 값이다(입찰 · 등록 · 공고문 일정 중 가장 이른 것).
 */
export function pairOf(item: {
  qualification_deadline?: string | null;
  schedule_deadline?: string | null;
  schedule_deadline_label?: string | null;
  schedule_deadline_time_known?: boolean | null;
}, bid: string | null | undefined): DeadlinePair {
  const q = item.qualification_deadline ?? null;
  const s = item.schedule_deadline ?? null;
  const qMs = deadlineMs(q);
  const sMs = deadlineMs(s);
  if (sMs !== null && (qMs === null || sMs < qMs)) {
    return {
      qualification: s,
      bid: bid ?? null,
      firstLabel: item.schedule_deadline_label || "공고문 일정 마감",
      firstTimeKnown: item.schedule_deadline_time_known !== false,
    };
  }
  return { qualification: q, bid: bid ?? null };
}

/** 실제 데드라인 — 둘 중 **이른 쪽**. 둘 다 없으면 null. */
export function effectiveDeadline({ qualification, bid }: DeadlinePair): string | null {
  const a = deadlineMs(qualification);
  const b = deadlineMs(bid);
  if (a === null) return bid ?? null;
  if (b === null) return qualification ?? null;
  return a <= b ? qualification : bid;
}

/**
 * 대시보드가 여는 나라장터 공고 행에서 두 마감을 읽는다 — 등록마감은 행의 `qualification_deadline`(원본 `bidQlfctRgstDt` · 통합 목록의
 * `qualification_deadline` 과 같은 값). 대시보드만 입찰마감으로 세어 목록 · 레이더 「D-7」과 「D-8」로 갈렸다(27차 검수 R27U-MSC-01).
 */
export function noticeDeadlinePair(notice: { deadline_at: string | null; raw_data?: Record<string, unknown> | null }): DeadlinePair {
  // 목록 캐시의 공고 행은 매퍼가 `qualification_deadline` 으로 옮겨 둔다(원본 필드 이름이 남은 행도 읽는다)
  const raw = notice.raw_data?.["qualification_deadline"] ?? notice.raw_data?.["bidQlfctRgstDt"];
  // 43차 — 공고문 일정표 마감(백엔드가 공고를 읽을 때 `raw_data.schedule_deadline` 에 싣는다)
  const sched = notice.raw_data?.["schedule_deadline"];
  const label = notice.raw_data?.["schedule_deadline_label"];
  const timeKnown = notice.raw_data?.["schedule_deadline_time_known"];
  return pairOf(
    {
      qualification_deadline: typeof raw === "string" && raw.trim() ? raw : null,
      schedule_deadline: typeof sched === "string" && sched.trim() ? sched : null,
      schedule_deadline_label: typeof label === "string" ? label : null,
      schedule_deadline_time_known: timeKnown === false ? false : null,
    },
    notice.deadline_at,
  );
}

/**
 * 앞자리 마감(등록 · 공고문 일정)이 입찰마감보다 **먼저** 오는가 — 두 줄로 적어야 하는 경우다. 입찰 마감이 비어 있고 공고문 일정 마감만
 * 있으면(직찰 · 43차) 그 이름으로 적어야 하므로 참이다.
 */
export function registrationClosesFirst({ qualification, bid, firstLabel: label }: DeadlinePair): boolean {
  const a = deadlineMs(qualification);
  const b = deadlineMs(bid);
  if (a !== null && b === null) return Boolean(label);
  return a !== null && b !== null && a < b;
}

/**
 * 마감 **날짜 + 시각**. 「2026. 9. 30. 18:00」 — 한국시간·24시간 고정.
 *
 * 6차가 「미착수」로 남겨 둔 것이 이것이다. 같은 마감 하나가 3D 중앙 카드에서는
 * 「2026.09.30」(날짜만), 상세 패널에서는 「2026. 9. 30. 오후 6:00」(12시간제)이었다 —
 * 시각이 아예 없는 쪽과 오전/오후로 적는 쪽이 한 화면 안에 있었다. 입찰 마감은 10:00 과
 * 14:00 이 다른 일이라 **시각이 빠지면 안 되고**, 공고문은 24시간제로 적는다.
 *
 * 폭이 좁은 자리(3D 라벨)는 `formatDeadlineStamp` 로 연도만 뺀다 — **같은 값의 짧은 형태**다.
 * 두 표기가 같은 시각을 가리키는지는 `scripts/check_deadline.mjs` 가 지킨다.
 */
export function formatDeadlineDateTime(deadline: string | null | undefined): string {
  const ms = deadlineMs(deadline);
  if (ms === null) return "마감일 미정";
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(ms));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}. ${pick("month")}. ${pick("day")}. ${pick("hour")}:${pick("minute")}`;
}

/**
 * 짝 안의 마감 하나를 시각까지 적는다 — 날짜만 있던 공고문 일정 마감(44차 M3)은 23:59 대신 「(시각 원문 확인)」.
 * `style` 「stamp」 = 「10-30 18:00」(카드 · 목록) · 「datetime」 = 「2026. 10. 30. 18:00」(상세). 판정 · D-day 는 그날 끝으로 센다.
 */
export function formatPairDeadline(pair: DeadlinePair, deadline: string | null | undefined, style: "stamp" | "datetime" = "stamp"): string {
  const text = style === "stamp" ? formatDeadlineStamp(deadline) : formatDeadlineDateTime(deadline);
  if (deadlineMs(deadline) === null || pair.firstTimeKnown !== false || deadline !== pair.qualification) return text;
  return `${text.replace(/\s*\d{2}:\d{2}$/, "")}${TIME_UNKNOWN_NOTE}`;
}

/** 「9-27 18:00」. 연도를 빼 카드 한 줄에 두 개가 들어가게 한다. **한국시간 고정**이다. */
export function formatDeadlineStamp(deadline: string | null | undefined): string {
  const ms = deadlineMs(deadline);
  if (ms === null) return "미정";
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(ms));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}`;
}

/** 긴급도 색 단계의 **단일 출처**. D-3 이하 빨강 · D-7 이하 주황 · 그 밖 회색. */
export const URGENCY_TONE: Record<UrgencyTier, string> = {
  closed: "text-cosmos-muted",
  urgent: "text-cosmos-red",
  soon: "text-cosmos-amber",
  watch: "text-cosmos-secondary",
  none: "text-cosmos-muted",
};
