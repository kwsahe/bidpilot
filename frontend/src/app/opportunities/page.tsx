"use client";

/**
 * 사업기회 목록 — 전체 검색·정렬·관리 화면.
 *
 * 3D Opportunity Radar(/radar)는 상위 소수만 보여준다. 이 화면은 **전부**를 보여주는 업무 화면이라
 * 절대 없애지 않는다. 레이더에서 뺀 것(전체 목록·검색·기간·마감 포함·상세 정렬·출처 상태)이 여기로 온다.
 *
 * 데이터는 세 곳을 함께 쓴다. 하나가 실패해도 나머지는 그대로 보여준다.
 * - `GET /api/procurements`      나라장터 원본 목록 (추천등급·키워드 근거·캐시 여부)
 * - `GET /api/support-programs`  기업마당 원본 목록 (지원 적합도·규칙 근거)
 * - `GET /api/business-opportunities` 통합 목록 → **id로 조인**해서 회사 기준 검토 우선순위만 얹는다.
 *
 * 원칙:
 * - 통합 점수는 `company_priority_score` = **회사 기준 검토 우선순위**다. 낙찰·선정 확률이 아니다.
 * - 원본 점수(추천등급 / 지원 적합도)는 덮어쓰지 않고 그대로 함께 보여준다(행 펼치기 안).
 * - `company_priority_score === null` 은 **미산정**이며 0점이 아니다.
 * - 지원사업은 목록 API에 지원 규모가 없다 → 「지원 규모 미확인」. 0원으로 그리지 않는다.
 * - 마감일이 없고 원문 문구(`deadline_text`)만 있으면 그 문구를 그대로 보여준다('상시 접수' 등).
 * - 기업마당은 입찰이 아니다 → 신청자격·신청기간·제출서류·신청 분석 용어만 쓴다.
 *
 * 정보 위계(2026-09 정리):
 * - 기본 화면 = 한 줄 요약 + 도구모음 한 줄 + 목록 하나. 카드형 KPI·Top3 카드·긴 산정 설명은 없앤 게 아니라
 *   「점수 기준」 팝오버 · 「데이터 상태」 팝오버 · 「필터」 시트 · 행 펼치기로 **옮겼다**.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import AttachmentLinks from "@/components/ui/AttachmentLinks";
import NoticeQaPanel from "@/components/ui/NoticeQaPanel";
import { attachmentLinkOf } from "@/lib/attachments";
import AppShell from "@/components/ui/AppShell";
import { Popover, Sheet } from "@/components/ui/overlays";
import { Badge, Button, Chip, EmptyState, InlineAlert, LoadingState, SectionHeader } from "@/components/ui/primitives";
import ManualInboxPanel from "@/components/opportunities/ManualInboxPanel";
import PreparePanel from "@/components/opportunities/PreparePanel";
import { interleaveSources } from "@/lib/interleave";
import {
  NO_DIGEST,
  bizinfoRowsOf,
  digestOn,
  displayDeadline,
  g2bRowsOf,
  isClosedRow,
  parseMs,
  rowEffectiveDeadline,
  rowMatchesDigest,
  rowRegisteredAt,
  rowShown,
  type DigestConditions,
  type ManualRow,
  type Row,
  type SourceRow,
} from "@/lib/opportunityRows";
import { DATA_STATUS_MARK, DataStatusLabel, SourceBadge, noticeSourceKind, type DataStatus, type SourceKind } from "@/components/ui/SourceBadge";
import ReviewQueuePanel from "@/components/opportunities/ReviewQueuePanel";
import CollectKeywordsPanel from "@/components/opportunities/CollectKeywordsPanel";
import { OpenSheetContext, PlanBackContext } from "@/components/opportunities/openSheetContext";
import AnalysisStateBadges from "@/components/ui/AnalysisStateBadges";
import ExportMenu from "@/components/opportunities/ExportMenu";
import { FrozenNotice, FROZEN_RELOAD_REASON } from "@/components/ui/FrozenNotice";
import { describeFailure } from "@/lib/errors";
import { RECOLLECT_LABELS, recollectLock, recollectSummary, type RecollectSource } from "@/lib/recollect";
import { verdictOf } from "@/lib/verdict";
import { buildHaystack, matchesQuery } from "@/lib/opportunitySearch";
import { DEFAULT_PERIOD_DAYS, PERIOD_OPTIONS, setPeriodDays, usePeriodDays, type PeriodDays } from "@/lib/period";
import {
  ELIGIBILITY_GATE_LABELS,
  GRADE_HINTS,
  GRADE_LABELS,
  PRIORITY_THRESHOLDS,
  RECOMMENDATION_GRADE,
  REVIEW_PRIORITY,
  labelOf,
} from "@/lib/scoreNames";
import {
  ApiError,
  getBusinessOpportunities,
  getHealth,
  getProcurements,
  getSupportPrograms,
  getTodayDigest,
  recollectOpportunities,
} from "@/lib/api";
import { useOrganizationId, useOrganizations } from "@/lib/organization";
import {
  NOTICE_QUERY_KEY,
  SUPPORT_QUERY_KEY,
  hrefWithConditions,
  readSelectedNotice,
  readSelectedNoticeServer,
  readSelection,
  readSelectionServer,
  subscribeSelection,
  writeSelectedNotice,
} from "@/lib/selection";
import { RequirementSheet } from "@/components/opportunities/RequirementSheet";
import type { SupportProgramListResponse, SupportProgramView } from "@/types/support";
import { formatBudgetCompact, formatDateTime } from "@/lib/cosmos/format";
import { CACHE_TERM, FULL_VIEW_ONLY_TAG, GUIDE_LINK_TEXT, OPEN_REQUIREMENT_SHEET, RECOLLECT_TERM, REGISTRATION_HELP, SCREEN_NAMES, SYNTHETIC_NOTICE, UNDECIDED, UNSCORED, VIEW_RELOAD_TERM, WRITE_PLAN_BUTTON, WRITE_PROPOSAL_BUTTON, collectTerm, sortHeadLine } from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import { GUIDE_LINKS } from "@/lib/guide";
import { CONSORTIUM_UNLOCK, DIRECT_CHECK_HEAD, UNLOCK_HEAD, isOverCeilingCaution, splitUnlocks } from "@/lib/unlock";
import {
  dDayText,
  effectiveDeadline,
  formatDeadlineStamp,
  registrationClosesFirst,
  pairOf,
  firstLabel,
  daysUntil,
  deadlineTerm,
  formatDeadlineDate,
  formatPairDeadline,
  normalizeApplyEnd,
  TIME_UNKNOWN_NOTE,
  urgencyTierOf,
  withinDaysText,
} from "@/lib/deadline";
import { COSMOS_COLORS, TONE_COLORS, withAlpha, type Tone } from "@/lib/cosmos/theme";
import { WORK_KIND_LABELS, WORK_TRACK_LABELS, type WorkTrack } from "@/types/capability";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { parseDisplayMode, useDisplayMode, type DisplayMode } from "@/lib/viewMode";
import { bidLines, ddayTone, mentionsCertTarget, supportLines, type CardLine, type DdayTone } from "@/lib/opportunityCard";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { OPPORTUNITIES_VIEW_TITLES, ViewModeSwitch } from "@/components/ui/ViewModeToggle";
import { GROUP_HELP, GROUP_TONE, PracticalTags, RankingMethodContext, useRankingMethod } from "@/components/opportunities/PracticalTags";
import {
  CONFIDENCE_LABELS,
  OPPORTUNITY_TYPE_LABELS,
  SOURCE_TYPE_LABELS,
  type PriorityLabel,
  type UnifiedOpportunity,
  type UnifiedOpportunityListResponse,
  type OpportunitySort,
  gradeOf,
} from "@/types/opportunity";
import {
  noticeAttachments,
  semanticFitOf,
  type CandidateTier,
  type ProcurementListResponse,
  type ProcurementNotice,
  type Recommendation,
  type RecommendationGrade,
} from "@/types/procurement";

type BackendStatus = "checking" | "connected" | "disconnected";
/** 출처 선택. 조달공고(추천등급)와 지원사업(지원 적합도)은 다른 개념이라 원본 점수를 섞지 않는다. */
/** 목록에 한 번에 그리는 최대 건수. 「더 보기」로 이만큼씩 늘린다. */
const PAGE_SIZE = 20;

/** 주소창 조건 읽기 — useSyncExternalStore 용. 서버에서는 빈 문자열이다. */
const subscribeNever = () => () => {};
const readSearchString = () => (typeof window === "undefined" ? "" : window.location.search);
const readSearchServer = () => "";

/**
 * 주소가 바뀌면 알린다(2.0.6) — 같은 페이지 링크(상단 메뉴 「사업기회」 · 후보함 「선제준비 칸에 있음 →」 · 「… 열기 →」)는
 * 페이지를 다시 만들지 않아(Next 16 · 41차 FRONT-R40-03) 주소만 바뀌고 탭은 그대로였다. `useSearchParams` 는 Suspense 안에서만(로그인 화면과 같은 꼴).
 */
function SearchWatcher({ onChange }: { onChange: () => void }) {
  const search = useSearchParams().toString();
  useEffect(() => onChange(), [search, onChange]);
  return null;
}

interface UrlConditions extends DigestConditions {
  q: string | null;
  src: SourceTab | null;
  days: PeriodDays | null;
  sort: SortKey | null;
  track: WorkTrack | "all" | null;
  closed: boolean;
  blocked: boolean;
  unrelated: boolean;
  /**
   * 어느 탭인가 (0919 §4-B-3).
   *
   * 「전체 목록」은 **새로 들어온 것**을, 「검토 중」은 **손댄 흔적이 있는 것**을 보여준다.
   * 두 목록은 데이터도 정렬 축도 달라서 같은 필터를 공유하지 않는다.
   */
  tab: ListTab;
  /**
   * 「쉬운 보기 ⇄ 전체 보기」 (24차 §3-1). 값은 저장소가 정하고(`lib/viewMode`), 여기서는 **주소에 있었는지만** 본다 —
   * 아래 주소 쓰기 effect 가 주소를 처음부터 다시 만들므로, 들어올 때 있던 `mode` 를 옮겨 적지 않으면 첫 렌더 뒤 지워진다.
   */
  mode: DisplayMode | null;
  /** 직접 넣은 공고 하나를 짚어 연다(`?tab=manual&manual=manual-…`). */
  manualFocus: string | null;
}

/** 「manual」 — 직접 넣기 · 후보함(38차 §3-E) · 「prepare」 — 선제준비(사전규격 · 발주계획 · 39차 결정 1). 메뉴는 그대로 다섯. */
type ListTab = "list" | "review" | "sheet" | "manual" | "prepare";

/** 행의 「요구사항 정리표 열기」 — 컨텍스트 하나로 준다(`openSheetContext`). 제공자 밖이면 아무것도 하지 않는다. */
const NO_SHEET = (): void => {};


/**
 * 띠에서 온 조건을 사람 말로. 무엇이 걸려 있는지 화면에 적어 주지 않으면 목록이 왜 짧은지 알 수 없다.
 *
 * 「새 공고」 기간은 **응답이 정한다**(`summary.new_days`). 아직 못 받았으면 일수를 적지 않는다 —
 * 3 이라고 지어 적으면 백엔드가 다른 기간으로 세고 있을 때 화면이 거짓말을 한다 (0920 §4-B-5).
 */
function digestLabels(d: DigestConditions, newDays: number | null): string[] {
  const out: string[] = [];
  if (d.onlyNew) out.push(newDays === null ? "새 공고" : `최근 ${newDays}일 새 공고`);
  if (d.newToday) out.push("오늘 올라온 공고");
  if (d.onlyChanged) out.push("내용이 바뀐 공고");
  if (d.dueWithin > 0) out.push(withinDaysText(d.dueWithin));
  if (d.dueToday) out.push("오늘 마감");
  if (d.onlyPending) out.push(UNDECIDED);
  if (d.onlyPass) out.push("참가 · 신청 가능");
  return out;
}

/**
 * 띠 조건이 걸리는 출처(2.1.0) — 새 공고 · 마감 · 가능은 나라장터 · 기업마당에, 변경 · 결정 대기는 나라장터에만 걸린다(`rowMatchesDigest`).
 * 직접 넣은 공고는 어느 조건에도 들지 않는다.
 */
function digestScopeLabel(d: DigestConditions, tab: SourceTab): string {
  if (d.onlyChanged || d.onlyPending || tab === "g2b") return "나라장터 공고만";
  if (tab === "bizinfo") return "기업마당 지원사업만";
  return "나라장터 · 기업마당(직접 넣은 공고 뺌)";
}

/** 주소창 문자열을 조건으로 바꾼다. 모르는 값은 null 로 두고 기본값이 이기게 한다. */
function parseParams(search: string): UrlConditions {
  const p = new URLSearchParams(search);
  const rawDays = Number(p.get("days"));
  const days = PERIOD_OPTIONS.includes(rawDays as PeriodDays) ? (rawDays as PeriodDays) : null;
  // 잘못된 링크(?src=x · ?track=x)는 기본값으로 — 빈 정렬 칸 · 눌린 탭 없음 · 「일의 종류 undefined」가 났다(OPP-15).
  const src = p.get("src");
  const track = p.get("track");
  return {
    q: p.get("q"),
    src: SOURCE_TABS.some((t) => t.key === src) ? (src as SourceTab) : null,
    days,
    // 모르는 정렬(레이더의 「value」 등)은 버린다 — 목록 ↔ 레이더가 같은 주소 키를 쓴다 (27차 LNK-09).
    sort: SORT_OPTIONS.some((option) => option.key === p.get("sort")) ? (p.get("sort") as SortKey) : null,
    track: track === "all" || (track !== null && Object.hasOwn(WORK_TRACK_LABELS, track)) ? (track as WorkTrack | "all") : null,
    closed: p.get("closed") === "1",
    // 「불가 포함」도 주소에 남긴다 — 조건을 맞춘 목록을 남에게 보낼 수 있어야 한다.
    blocked: p.get("blocked") === "1",
    unrelated: p.get("unrelated") === "1",
    onlyNew: p.get("new") === "1",
    newToday: p.get("new") === "today",
    onlyChanged: p.get("changed") === "1",
    onlyPending: p.get("pending") === "1",
    dueWithin: Number(p.get("due")) > 0 ? Math.min(Number(p.get("due")), 60) : 0,
    dueToday: p.get("due") === "today",
    onlyPass: p.get("pass") === "1",
    tab: p.get("tab") === "review" ? "review" : p.get("tab") === "sheet" ? "sheet" : p.get("tab") === "manual" ? "manual" : p.get("tab") === "prepare" ? "prepare" : "list",
    // 「직접 넣은 공고 보기」(브리핑 · 이번 주 할 일) — 그 행을 테두리로 짚는다
    manualFocus: /^manual-[0-9a-f]{12}$/.test(p.get("manual") ?? "") ? p.get("manual") : null,
    mode: parseDisplayMode(p.get("mode")),
  };
}


type SourceTab = "all" | "g2b" | "bizinfo";

/**
 * 「전라남도 소재」 해석을 기다리는 건을 가리는 말 (0924 §4-B-3·4).
 *
 * 백엔드가 「열리는 조건」에 적어 준 문장의 일부다 — 화면이 규칙을 다시 만들지 않는다.
 * 문장이 바뀌면 `support_application_service.MERGED_REGION_UNLOCK` 과 함께 고친다.
 */
const MERGED_REGION_HINT = "전남사회적경제통합지원센터";

/**
 * 숫자 풀이(39차 §3-G) — 같은 「나라장터」 수가 화면마다 달랐다(사업기회 머리 · 자료 상태 · 쉬운 보기 「n위/N」 · 레이더). 무엇을 세는지 한 줄씩.
 */
const COUNT_HELP = {
  header: "머리 「나라장터 N」은 마감 전 입찰 전부(비추천 · 불가 포함 · 사전규격은 「선제준비」 탭)",
  rank: "목록 「n위/N」은 지금 조건에 보이는 입찰(불가 · 관련 낮음은 켰을 때만)",
  radar: "레이더는 그릴 수 있는 것만(비추천 · 사전규격 · 직접 넣음 뺌)",
} as const;

/** 머리 칸 · 카드 점수 줄의 통합 점수 이름 — CLAUDE.md §12 의 긴 이름 그대로(줄인 「검토 우선순위」는 추천등급 설명과 헷갈렸다 · OPP-37). */
const REVIEW_PRIORITY_FULL = REVIEW_PRIORITY.label.startsWith("회사 기준") ? REVIEW_PRIORITY.label : `회사 기준 ${REVIEW_PRIORITY.label}`;

const SOURCE_TABS: Array<{ key: SourceTab; label: string; hint: string }> = [
  { key: "all", label: "전체", hint: "입찰과 지원사업을 회사 기준 검토 우선순위로 함께 — 원본 점수 축은 그대로 분리" },
  { key: "g2b", label: "나라장터 입찰", hint: "우리 회사가 용역을 따내는 입찰 · 추천등급(낙찰확률 아님)" },
  { key: "bizinfo", label: "기업마당 지원사업", hint: "우리 회사가 지원금·바우처를 신청하는 사업(수행기관 · 주관기관 모집은 매출) · 지원 적합도(규칙)" },
];

type ProcurementStatus = "loading" | "ready" | "error";
type DashboardResults = Awaited<ReturnType<typeof fetchDashboard>>;

// 조회 기간은 `lib/period.ts` 하나가 정한다 (0920 §4-B-2-e).
// 예전에는 이 화면만 고를 수 있었고 대시보드·레이더·RFP 는 14일로 굳어 있어서,
// 여기서 60일로 찾은 공고가 저쪽 선택창에 없었다.

function fetchDashboard(days: number) {
  // 38차 D15 — 나라장터 후보 아님(관련 낮음)도 받는다. 기업마당 「관련 낮음」처럼 사유와 함께 접어 두고 「관련 낮음 포함」으로 연다.
  return Promise.allSettled([getHealth(), getProcurements({ days, includeLow: true })]);
}

/**
 * 키워드 등급 라벨.
 *
 * `medium` 은 더 이상 어떤 공고도 받지 않는다 — AI 키워드만 걸린 공고는 「AI타워」처럼
 * «AI» 가 건물 이름인 경우가 대부분이라 `low` 로 내려갔다 (backend `opportunity_filter.py`).
 * 옛 캐시·스냅샷 JSON 에 남아 있어 값 자체는 지운 게 아니므로 라벨도 남긴다.
 */
const TIER_LABEL: Record<CandidateTier, string> = {
  high: "높음 · AI + 업무·개발 낱말",
  medium: "보통 · 더 이상 쓰지 않는 등급 (옛 데이터)",
  low: "낮음 · 한쪽만 있음 (AI만, 또는 업무 낱말만)",
  none: "해당 없음",
};

/** 칩·배지에 찍는 짧은 이름. 화면에 HIGH·LOW 를 그대로 쓰지 않는다. */
const TIER_SHORT: Record<CandidateTier, string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
  none: "해당 없음",
};

const TIER_COLOR: Record<CandidateTier, string> = {
  high: COSMOS_COLORS.cyan,
  medium: COSMOS_COLORS.blueText, // 글자로 쓰인다(칩 · 배지) — 면용 blue 는 4.44:1(26차 검수 FE-4)
  low: COSMOS_COLORS.slate,
  none: COSMOS_COLORS.slate,
};

const GRADES: RecommendationGrade[] = ["A", "B", "C", "D", "NO_GO"];

const GRADE_TONE: Record<RecommendationGrade, Tone> = {
  A: "pass",
  B: "ok",
  C: "warn",
  D: "muted",
  NO_GO: "fail",
};

// 등급 표기·설명은 `lib/scoreNames.ts` 하나만 쓴다 (0920 §4-B-1).
// 예전에는 여기서 NO_GO 를 「참여 불가」로 적었는데, 백엔드에서 그 값은
// **「입찰 마감이 지났다」만 뜻한다** — 사람이 내린 결정처럼 읽히면 안 된다.

/** 통합 우선순위 라벨 색. 색만으로 전달하지 않도록 글리프·문구를 함께 쓴다. */
const PRIORITY_TONE: Record<PriorityLabel, Tone> = {
  "우선 검토": "pass",
  검토: "ok",
  후순위: "muted",
  미확인: "warn",
  마감: "fail",
};

const FIT_TONE: Record<SupportProgramView["support_fit"]["label"], Tone> = { 적합: "pass", 검토: "warn", 낮음: "muted" };

function gradeLabel(grade: RecommendationGrade): string {
  return labelOf(GRADE_LABELS, grade);
}

/**
 * 데이터 출처 문자열 → 공통 출처 배지. 지어내지 않고 backend 값을 그대로 옮긴다.
 * 두 출처 모두 실패 시 `cached`를 쓰므로, 어느 쪽 캐시인지는 sourceType으로 구분해야 한다.
 */
function unifiedSourceBadge(source: string, sourceType: "g2b" | "bizinfo" = "g2b"): { kind: SourceKind; label?: string } {
  switch (source) {
    case "g2b":
      return { kind: "g2b" };
    case "cached":
      return sourceType === "bizinfo" ? { kind: "cached", label: `기업마당 ${CACHE_TERM}` } : { kind: "cached" };
    case "bizinfo":
      return { kind: "computed", label: "기업마당 실시간" };
    case "sample":
      return { kind: "demo", label: SYNTHETIC_NOTICE };
    default:
      return { kind: "not_run", label: source };
  }
}

// ---------------------------------------------------------------------------
// 행 모델 — 두 출처를 한 목록에 놓되 원본 데이터는 그대로 들고 다닌다
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// 정렬 — 출처마다 고를 수 있는 항목이 다르다
// ---------------------------------------------------------------------------

/**
 * 정렬 다섯 (37차 §3-C · 담당자 결정 2026-10-14) — 서버 `sort` 와 같은 열쇠다(내보내기가 그대로 받는다).
 * 기본은 **회사 방식**(회사자료 「우선순위 계산 방식」) — 샘플에듀 실무순 · 그 밖 점수순. 점수는 어느 정렬에서나 같다.
 */
type SortKey = "practical" | "priority" | "slack" | "deadline" | "recent";

const SORT_OPTIONS: Array<{ key: SortKey; label: string; tabs: SourceTab[]; hint: string }> = [
  { key: "practical", label: "실무 우선순위순", tabs: ["all", "g2b", "bizinfo"], hint: "본업 안에서 주제 맞음 먼저(주제 확인 · AI 꼬리표는 뒤) · 최근 공고 · 준비기간 긴 것 먼저, 마감 임박은 아래 긴급 칸으로 · 점수는 그대로 · 확률 아님" },
  { key: "priority", label: "회사 기준 검토 우선순위순", tabs: ["all", "g2b", "bizinfo"], hint: "회사 기준 검토 우선순위 점수 높은 순 · 같으면 마감 빠른 순 · 확률 아님" },
  { key: "slack", label: "마감 여유순", tabs: ["all", "g2b", "bizinfo"], hint: "실제 마감(등록 마감이 더 이르면 그 날)이 먼 순. 날짜가 없는 건은 뒤로" },
  { key: "deadline", label: "마감 임박순", tabs: ["all", "g2b", "bizinfo"], hint: "마감일·신청 종료일이 이른 순. 날짜가 없는 건은 뒤로" },
  { key: "recent", label: "최신 등록순", tabs: ["all", "g2b", "bizinfo"], hint: "공고 게시일 / 지원사업 등록일이 최근인 순" },
];

/** 회사 방식 → 기본 정렬. 응답을 아직 못 받았으면 점수순(옛 응답에는 방식이 없다). */
function companySortOf(listing: UnifiedOpportunityListResponse | null): SortKey {
  return listing?.ranking_method === "practical" ? "practical" : "priority";
}

function sortsFor(tab: SourceTab): typeof SORT_OPTIONS {
  return SORT_OPTIONS.filter((s) => s.tabs.includes(tab));
}

const INF = Number.POSITIVE_INFINITY;

/** 오름차순(이른 것 먼저). 값이 없으면 맨 뒤. */
function ascWithNullsLast(a: string | null | undefined, b: string | null | undefined): number {
  return (parseMs(a) ?? INF) - (parseMs(b) ?? INF);
}

/** 내림차순(최근 먼저). 값이 없으면 맨 뒤. */
function descWithNullsLast(a: string | null | undefined, b: string | null | undefined): number {
  return (parseMs(b) ?? -INF) - (parseMs(a) ?? -INF);
}

/** 통합 순위. 통합 목록에 없는 건(조회 실패·마감 제외 등)은 맨 뒤로 보낸다. */
function unifiedRank(item: UnifiedOpportunity | null): number {
  return item?.priority_rank ?? INF;
}

/** 실무 우선순위 자리(서버가 매긴 `practical_order`). 없으면 맨 뒤. */
function practicalRank(item: UnifiedOpportunity | null): number {
  return item?.practical_order || INF;
}

/** 백엔드가 매겨 보낸 나라장터 추천 우선순위 그대로. 순위가 없으면 점수로 대체한다. */
function byRank(a: ProcurementNotice, b: ProcurementNotice): number {
  if (a.rank != null && b.rank != null) return a.rank - b.rank;
  const noGoA = a.recommendation?.grade === "NO_GO" ? 1 : 0;
  const noGoB = b.recommendation?.grade === "NO_GO" ? 1 : 0;
  if (noGoA !== noGoB) return noGoA - noGoB;
  return (b.recommendation?.score ?? 0) - (a.recommendation?.score ?? 0);
}


/**
 * 「회사에 뜻하는 것」 한 줄에서 **받는 것**만 굵게 (0925 §4-F-3 · ISSUE-105).
 *
 * 이 줄은 「신청 주체(수요기업) · 무료 · 정부지원 비율 80% · 자부담 비율 20% ·
 * 예산 소진시까지」처럼 넷을 한 줄에 담는다. 담당자가 이 줄에서 먼저 찾는 것은
 * **얼마를 받는가**인데 10차에는 네 조각이 모두 같은 굵기·같은 회색이었다.
 *
 * **문구는 바꾸지 않는다** (0925 §4-F 하지 말 것) — 백엔드가 만든 글자 그대로 두고
 * 굵기만 다르게 그린다. 조각을 나누는 「 · 」도 그대로다.
 */
const RECEIVE_RE = /무료|전액|최대|만원|억원|비율\s*\d+%|\d+%/;

function ReceiveLine({ text }: { text: string }) {
  const parts = text.split(" · ");
  return (
    <>
      {parts.map((part, index) => (
        <span key={`${part}-${index}`}>
          {index > 0 && " · "}
          {RECEIVE_RE.test(part) ? <strong className="font-semibold text-cosmos-text">{part}</strong> : part}
        </span>
      ))}
    </>
  );
}

/** 이 행에 붙일 마감 용어(입찰 마감 / 신청 종료 / 상시·예산 소진 시 …). */
function rowDeadlineTerm(row: Row, nowMs: number | null): string {
  return deadlineTerm({
    source: row.kind === "g2b" ? "g2b" : "bizinfo",
    closed: isClosedRow(row, nowMs),
    periodKind: row.kind === "bizinfo" ? row.view.program.apply_period_kind : null,
    deadline: displayDeadline(row),
  });
}

function displayDeadlineText(row: Row): string | null {
  if (row.kind === "g2b") return row.unified?.deadline_text ?? "마감 미상 — 공고문 확인";
  if (row.kind === "manual") return row.unified.deadline_text ?? null;
  if (row.unified?.deadline_text) return row.unified.deadline_text;
  // ISO 원문(「~ 2026-09-30」)을 화면에 내보내지 않는다 — 다른 자리는 전부
  // 「2026. 9. 30.」이다 (0920 §4-B-5 · ISSUE-078).
  const applyEnd = normalizeApplyEnd(row.view.program.apply_end);
  return applyEnd ? `~ ${formatDeadlineDate(applyEnd)}` : "신청 기간 원문 확인 필요";
}

/** 조달=예산(원). 지원사업은 목록 응답에 지원 규모가 없어 null — 0원이 아니다. */
function rowBudget(row: Row): number | null {
  return row.kind === "g2b" ? row.notice.budget : row.unified?.budget ?? null;
}

/** 통합 순위가 없을 때의 대체 정렬값 — 출처별 원본 점수(0~1). */
function fallbackScore(row: Row): number {
  if (row.kind === "manual") return (row.unified.company_priority_score ?? 0) / 100;
  return row.kind === "g2b" ? row.notice.recommendation?.score ?? 0 : row.view.support_fit.score;
}

/** 덩어리 경계 머리줄(43차 설명) — 서버 `practical_priority.BLOCK_*` 이름 그대로를 풀어 쓴다. */
const BLOCK_HEADS: Record<string, string> = {
  // 43차 설명(BRIEF-10 · RANK-01) — 주제 확인이 시간 등급보다 앞(회사 결정 D23)
  본업: "본업 — 교육 운영 · 콘텐츠 · 컨설팅 · 개발(대형 아님) · 「주제 확인」 공고는 마감 여유가 커도 주제 맞는 긴급 공고 뒤",
  "연구 · 감리 · 구매": "여기부터 연구 · 감리 · 구매(B2 · D) — 본업 뒤에 둡니다",
  "대형 · 파트너형 후보":
    "여기부터 대형 · 파트너형 후보 — 회사 단독 상한을 넘는 공고(광주 · 전남 발주는 본업 칸에 남김) · 등록 업종이 없어 공동수급이 필요한 공고",
  비추천: "여기부터 비추천(관련 낮음)",
  제외: "여기부터 제외(불가 · 마감)",
};

/**
 * 머리 줄을 가르는 열쇠 — 10-31 최종 점검: 서버 정렬(`practical_key`)은 비추천 · 제외를 덩어리보다 먼저 가른다.
 * 덩어리만 보면 「관련 낮음 · 불가 포함」을 켰을 때 머리 줄이 되풀이되고 비추천 · 제외 행이 엉뚱한 머리 아래 섰다.
 */
function blockHeadKey(row: Row): string | null {
  const group = row.unified?.practical_group;
  return group === "비추천" || group === "제외" ? group : row.unified?.practical_block ?? null;
}

/** 통합 목록에 없는 건끼리의 대체 순서 — 예전 「검토 우선순위순」과 같다. */
/** 출처 차례 — 서버 `SOURCE_TYPES` · `lib/interleave.ts` 와 같다(나라장터 → 기업마당 → 직접 넣음). */
const ROW_KIND_ORDER: Record<Row["kind"], number> = { g2b: 0, bizinfo: 1, manual: 2 };

function fallbackCompare(a: Row, b: Row): number {
  if (a.kind !== b.kind) return ROW_KIND_ORDER[a.kind] - ROW_KIND_ORDER[b.kind];
  if (a.kind === "g2b" && b.kind === "g2b") return byRank(a.notice, b.notice);
  return fallbackScore(b) - fallbackScore(a);
}

const CONFIDENCE_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

/**
 * 서버 `_sort_key` 의 뒤 키 — 날짜가 같으면 점수 높은 순 → (마감 임박순만) 신뢰도 → id(38차 FRONTEND-02 · 화면 n위가 엑셀 n위와 달랐다).
 * 점수가 없으면 맨 뒤(서버 `-(score if not None else -1)`).
 */
function serverTieBreak(a: Row, b: Row, withConfidence: boolean): number {
  const score = (row: Row) => row.unified?.company_priority_score ?? -1;
  const conf = (row: Row) => CONFIDENCE_ORDER[row.unified?.confidence ?? ""] ?? 3;
  return score(b) - score(a) || (withConfidence ? conf(a) - conf(b) : 0) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

/** 서버 `_sort_key` 의 앞 두 키 — 마감 · 불가는 날짜 정렬에서도 뒤로. 화면과 내려받은 파일이 같은 순서가 된다(37차 마지막 검토). */
function holdBackCompare(a: Row, b: Row): number {
  const rank = (row: Row) => (row.unified?.closed ? 2 : 0) + (row.unified?.eligibility_gate === "FAIL" ? 1 : 0);
  return rank(a) - rank(b);
}

function compareRows(a: Row, b: Row, key: SortKey): number {
  switch (key) {
    case "practical": {
      const left = practicalRank(a.unified);
      const right = practicalRank(b.unified);
      return left !== right ? (left < right ? -1 : 1) : fallbackCompare(a, b);
    }
    case "deadline":
      // 실제 마감(등록 마감이 더 이르면 그 날 · 38차 FRONTEND-01 — 입찰 마감으로 세워 오늘 18:00 등록 마감 넷이 23:59 기업마당 뒤에 섰다)
      return holdBackCompare(a, b) || ascWithNullsLast(rowEffectiveDeadline(a), rowEffectiveDeadline(b)) || serverTieBreak(a, b, true);
    case "slack":
      return holdBackCompare(a, b) || descWithNullsLast(rowEffectiveDeadline(a), rowEffectiveDeadline(b)) || serverTieBreak(a, b, false);
    case "recent":
      return holdBackCompare(a, b) || descWithNullsLast(rowRegisteredAt(a), rowRegisteredAt(b)) || serverTieBreak(a, b, false);
    case "priority":
    default: {
      const left = unifiedRank(a.unified);
      const right = unifiedRank(b.unified);
      return left !== right ? (left < right ? -1 : 1) : fallbackCompare(a, b);
    }
  }
}


/**
 * 검색이 훑는 글자 (0919 §4-B-6).
 *
 * 예전에는 제목·기관·공고번호뿐이었다. 그래서 「RAG」·「챗봇」처럼 **본문에만 있는 말**로는
 * 한 건도 찾지 못했다 — 담당자가 찾는 말은 대개 제목에 없다.
 *
 * 화면에 이미 보이는 것을 그대로 넣는다: 한 줄 요약 · 과업 키워드 칩 · 갈래 · 지역, 그리고
 * 지원사업의 해시태그·지원대상. **캐시 안에서 거르는 것뿐이고 새 요청을 만들지 않는다.**
 *
 * 화면에 없는 값(원문 전체·`raw_data`)은 넣지 않는다. 찾아 놓고 «왜 걸렸는지» 보이지 않으면
 * 목록이 고장난 것처럼 읽힌다.
 */
function rowHaystack(row: Row): string {
  const parts: string[] = [rowSummaryLine(row), row.unified?.summary ?? ""];
  if (row.kind === "g2b") {
    const { notice } = row;
    parts.push(
      notice.title,
      notice.agency,
      notice.notice_no,
      notice.region ?? "",
      notice.description ?? "",
      ...(notice.candidate?.matched_ai_keywords ?? []),
      ...(notice.candidate?.matched_work_keywords ?? []),
      ...(notice.work?.kinds ?? []).map((kind) => WORK_KIND_LABELS[kind] ?? ""),
      ...(notice.work?.tracks ?? []).map((track) => WORK_TRACK_LABELS[track] ?? ""),
    );
    return buildHaystack(parts);
  }
  if (row.kind === "manual") {
    return buildHaystack([...parts, row.unified.title, row.unified.agency, row.unified.recruit_kind ?? "", row.unified.evidence_line ?? ""]);
  }
  const { program } = row.view;
  parts.push(
    program.title,
    program.agency,
    program.executing_agency ?? "",
    program.category ?? "",
    program.subcategory ?? "",
    program.summary ?? "",
    program.target ?? "",
    ...program.hashtags,
  );
  return buildHaystack(parts);
}


/** 「사회적기업 · 여성기업 대상」 칩(2.3.0) — 샘플에듀 인증이 공고 대상 글에 보이는가. 판정이 아니라 거르기라 제목 · 요약 · 대상 칸 낱말만 본다. */
function rowCertTarget(row: Row): boolean {
  const item = row.unified;
  const texts: Array<string | null | undefined> = [item?.title, item?.summary, ...(item?.requirement_sentences ?? [])];
  if (row.kind === "g2b") texts.push(row.notice.title);
  if (row.kind === "bizinfo") {
    const { program } = row.view;
    texts.push(program.title, program.summary, program.target, ...program.hashtags, ...(program.requirement_sentences ?? []));
  }
  return mentionsCertTarget(texts);
}

/** 공통 조건(검색어 · 마감 포함 여부)만 적용한 노출 여부. 출처별 건수와 목록이 어긋나면 안 된다 — 검색어 밖 조건은 `rowShown`(대시보드 통계와 같은 술어). */
function rowVisible(
  row: Row,
  query: string,
  includeClosed: boolean,
  nowMs: number | null,
  includeBlocked: boolean = true,
  includeUnrelated: boolean = true,
): boolean {
  if (!rowShown(row, includeClosed, nowMs, includeBlocked, includeUnrelated)) return false;
  if (!query) return true;
  return matchesQuery(rowHaystack(row), query);
}

/** 추천 이유·위험은 backend 산정 항목(components)에서만 뽑는다 — 새 점수를 만들지 않는다. */
function reasonsOf(rec: Recommendation): { reasons: string[]; risks: string[] } {
  const scored = rec.components.filter((c) => c.score !== null);
  const reasons = [...scored]
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .filter((c) => (c.score ?? 0) >= 0.6)
    .slice(0, 2)
    .map((c) => `${c.label}: ${c.reason}`);
  const risks = [
    ...(rec.gate_reason ? [rec.gate_reason] : []),
    ...scored.filter((c) => (c.score ?? 0) < 0.5).slice(0, 2).map((c) => `${c.label}: ${c.reason}`),
  ];
  return { reasons, risks };
}

/** 카드 한 줄 요약 — backend가 준 문장만 쓴다. 없으면 비운다. */
function rowSummaryLine(row: Row): string {
  const parts: string[] = [];
  if (row.unified) {
    parts.push(...row.unified.reasons.slice(0, 1), ...row.unified.checks.slice(0, 1));
  } else if (row.kind === "g2b" && row.notice.recommendation) {
    const { reasons, risks } = reasonsOf(row.notice.recommendation);
    parts.push(...reasons.slice(0, 1), ...risks.slice(0, 1));
  } else if (row.kind === "bizinfo") {
    parts.push(row.view.support_fit.note);
  }
  return parts.filter(Boolean).join(" · ");
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return `나라장터 조회와 저장된 자료 모두 사용할 수 없습니다. ${error.detail ?? ""}`.trim();
    }
    return describeFailure(error, "공고 목록을 불러오지 못했습니다.");
  }
  return describeFailure(error, "공고 목록을 불러오지 못했습니다.");
}

/** 통합 목록 실패 사유만(2.0.6) — 「출처별 목록은 그대로 표시합니다」는 목록 탭 경고에서만 붙인다(정리표 · 직접 넣기 탭에는 출처별 목록이 없다). */
function describeUnifiedError(error: unknown): string {
  return describeFailure(error instanceof ApiError ? error : null, "통합 순위를 계산하지 못했습니다.");
}

const inputClass =
  "mc-focus min-h-9 rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-2.5 text-[12.5px] text-cosmos-text placeholder:text-cosmos-muted";

// ---------------------------------------------------------------------------
// 페이지
// ---------------------------------------------------------------------------

export default function OpportunitiesPage() {
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();

  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");
  const [g2bConfigured, setG2bConfigured] = useState<boolean | null>(null);
  /**
   * 사업영역 점수를 AI 의미 유사도로 냈는가 (SEMANTIC_FIT · ISSUE-129).
   *
   * null 은 「모른다」다(서버가 안 알려 주는 옛 버전·연결 끊김). 화면은 그때 이 줄을
   * 아예 적지 않는다 — 꺼졌다고 단정하면 켜 놓고 시연하는 사람이 반대로 속는다.
   */
  const [semanticFit, setSemanticFit] = useState<boolean | null>(null);
  /**
   * 제안서·사업계획서·점검을 AI 로 만드는가 (LLM_LIVE + 크레딧 · ISSUE-130).
   *
   * 순위·유사도와 **다른 문**이다. 담당자 방침이 「순위와 유사도는 규칙만, AI 는 초안과
   * 점검에만」이라 한 화면에서 둘을 구분해 읽을 수 있어야 한다. null 은 「모른다」다.
   */
  const [aiDraft, setAiDraft] = useState<boolean | null>(null);
  /** 출처별 실호출 문 (20차 §4-G) — 「재수집」 단추를 연다. 모르면 null(잠근다). */
  const [liveFlags, setLiveFlags] = useState<{ g2b_live?: boolean; bizinfo_live?: boolean; keyword_search_live?: boolean } | null>(null);
  const [recollecting, setRecollecting] = useState<RecollectSource | null>(null);
  const [recollectNote, setRecollectNote] = useState<{ ok: boolean; text: string } | null>(null);
  /** 「찾는 낱말」 패널(2.0.7) — 쉬운 보기 「더 보기 ⋯」 · 전체 보기 도구모음의 단추로 연다. 기본은 닫힘(쉬운 보기 컨트롤 12 그대로). */
  const [keywordsOpen, setKeywordsOpen] = useState(false);
  const [procurementStatus, setProcurementStatus] = useState<ProcurementStatus>("loading");
  const [procurements, setProcurements] = useState<ProcurementListResponse | null>(null);
  const [procurementError, setProcurementError] = useState<string | null>(null);
  const [procurementDays, setProcurementDays] = useState<number | null>(null);

  const [support, setSupport] = useState<SupportProgramListResponse | null>(null);
  const [supportError, setSupportError] = useState<string | null>(null);
  const [supportLoadedFor, setSupportLoadedFor] = useState<string | null>(null);

  const [unified, setUnified] = useState<UnifiedOpportunityListResponse | null>(null);
  const [unifiedError, setUnifiedError] = useState<string | null>(null);
  const [unifiedLoadedKey, setUnifiedLoadedKey] = useState<string | null>(null);

  /**
   * 조건은 «사용자가 만진 값이 있으면 그것, 없으면 주소창 값, 그것도 없으면 기본값» 이다.
   *
   * 주소창을 effect 로 읽어 setState 하면 첫 렌더에 기본 조건 목록이 잠깐 보였다가 바뀐다.
   * 서버(정적 생성)에서는 주소를 알 수 없으므로 getServerSnapshot 이 기본값을 준다 —
   * React 가 hydration 을 맞춘 뒤 실제 값으로 넘어간다.
   */
  const urlSearch = useSyncExternalStore(subscribeNever, readSearchString, readSearchServer);
  /** 지금 보는 공고 · 지원사업 — 메뉴가 `?notice=` 로 싣고 온 것(없으면 저장값). 그 행을 표시한다 (27차 LNK-08). */
  const viewing = useSyncExternalStore(subscribeSelection, readSelection, readSelectionServer);
  /** 정리표 공고 — 입찰 선택만 본다(지원사업 우선인 `viewing` 을 쓰지 않는다 · 28차 §3-C). */
  const sheetNotice = useSyncExternalStore(subscribeSelection, readSelectedNotice, readSelectedNoticeServer);
  const displayMode = useDisplayMode();
  const urlParams = useMemo(() => parseParams(urlSearch), [urlSearch]);

  const [sourceTabOverride, setSourceTab] = useState<SourceTab | null>(null);
  const [sortKeyOverride, setSortKey] = useState<SortKey | null>(null);
  /** 「초기화」를 눌렀나 — 그 뒤로는 들어올 때 주소의 정렬도 쓰지 않는다(38차 FRONTEND-03). */
  const [sortCleared, setSortCleared] = useState(false);
  const [queryOverride, setQuery] = useState<string | null>(null);
  const [includeClosedOverride, setIncludeClosed] = useState<boolean | null>(null);
  const [includeBlockedOverride, setIncludeBlocked] = useState<boolean | null>(null);
  const [includeUnrelatedOverride, setIncludeUnrelated] = useState<boolean | null>(null);
  // 기간은 저장소 하나가 정한다. 화면별 override 를 두지 않는다.
  const days = usePeriodDays();

  const sourceTab = sourceTabOverride ?? urlParams.src ?? "all";
  // 기본 정렬 = 회사 방식(37차 §3-C-2) — 샘플에듀 실무순 · 그 밖 점수순. 응답 전에는 점수순으로 그린다.
  const companySortKey = companySortOf(unified);
  const practicalCompany = unified?.ranking_method === "practical";
  /** 「신규+여유」 건수(공고 7일 이내 · 실제 마감 21일 이상) — 서버가 매긴 분류를 세기만 한다. */
  const freshCount = useMemo(() => (unified ? unified.items.filter((item) => item.practical_group === "신규+여유").length : null), [unified]);
  const sortKey = sortKeyOverride ?? (sortCleared ? null : urlParams.sort) ?? companySortKey;
  const query = queryOverride ?? urlParams.q ?? "";
  const includeClosed = includeClosedOverride ?? urlParams.closed;
  /**
   * 참가할 수 없는 사업까지 볼 것인가 (0921 §4-C-2 · §4-D-1).
   *
   * 기본은 끔 — 목록 1,712건 중 1,002건이 「불가」(대부분 다른 지역)라 그대로 두면
   * 담당자가 볼 수 없는 것을 매번 스크롤해 지나가게 된다. **지우는 것이 아니다.**
   * 건수(`summary`)는 끄든 켜든 같은 값이라 화면의 「전체 n건」이 흔들리지 않는다.
   */
  const includeBlocked = includeBlockedOverride ?? urlParams.blocked;
  /**
   * 회사와 관련이 낮다고 판정한 지원사업까지 볼 것인가 (0922 §4-C-2).
   *
   * 기본은 끔. **지우는 것이 아니다** — 규칙이 틀렸을 때 담당자가 찾을 수 있어야 하고,
   * 행을 펼치면 「왜 관련이 낮다고 보았는가」가 근거 낱말과 함께 적혀 있다.
   */
  const includeUnrelated = includeUnrelatedOverride ?? urlParams.unrelated;

  /**
   * 한 번에 DOM 에 그리는 개수. 104건을 통째로 그리면 느리고, 화면을 훑기도 어렵다.
   * 페이지를 나누는 대신 「더 보기」로 늘린다 — 뒤로 가기로 돌아왔을 때 스크롤 위치가
   * 그대로 남고, 목록 중간을 가리키는 링크가 깨지지 않는다.
   */
  const [shown, setShown] = useState<{ key: string; count: number }>({ key: "", count: PAGE_SIZE });
  const [reloadTick, setReloadTick] = useState(0);

  // 나라장터 전용 필터 — 기본 화면에서 뺐지만 「필터」 시트에서 그대로 쓴다.
  const [grades, setGrades] = useState<Set<RecommendationGrade>>(() => new Set());
  const [tiers, setTiers] = useState<Set<CandidateTier>>(() => new Set());
  const [trackOverride, setTrack] = useState<WorkTrack | "all" | null>(null);
  const track = trackOverride ?? urlParams.track ?? "all";
  const [filterOpen, setFilterOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  // 쉬운 보기 목록 모양(2.3.0 · 대표 11-04 「vster 처럼 시인성」) — 열 때마다 카드(지난번 고른 보기를 기억하지 않는 37차 §3-F 와 같은 규칙).
  const [layout, setLayout] = useState<"card" | "list">("card");
  // 「사회적기업 · 여성기업 대상」 칩 — 쉬운 보기에서만 걸린다(칩도 쉬운 보기에만 있다).
  const [certOnly, setCertOnly] = useState(false);

  const nowMs = useNowMs();
  const unifiedKey = `${organizationId}|${days}|${includeClosed}|${reloadTick}`;

  /**
   * 「오늘 달라진 것」에서 온 조건 (0919 §4-B-1). 「전체 보기」를 누르면 끈다 —
   * 다른 필터와 같은 방식(override state)이라 주소도 따라서 정리된다.
   */
  const [tabOverride, setTab] = useState<ListTab | null>(null);
  const tab: ListTab = tabOverride ?? urlParams.tab;
  /**
   * 「전체」 탭 직접 넣음 행의 「직접 넣기 탭에서 보기 →」(41차 FRONT-R40-03) — 같은 페이지 안 이동은 주소를 다시 읽지 않아(탭 단추를 한 번
   * 누른 뒤에는 `tabOverride` 가 이겨) 탭이 바뀌지 않았다. 탭과 짚은 공고를 화면 상태로 바꾸고 주소도 맞춘다.
   */
  const [manualFocusOverride, setManualFocusOverride] = useState<string | null>(null);
  const openManual = useCallback((id: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", "manual");
    url.searchParams.set("manual", id);
    window.history.replaceState(null, "", url.pathname + url.search);
    setManualFocusOverride(id);
    setTab("manual");
    window.scrollTo({ top: 0 });
  }, []);
  const openSheet = useCallback((noticeId: string) => {
    // 탭은 화면 상태라 뒤로가기가 되살리지 못한다 — 기록을 쌓지 않는다(탭 단추와 같다 · 28차 검수 R2-04).
    writeSelectedNotice(noticeId, "replace");
    setTab("sheet");
    window.scrollTo({ top: 0 });
  }, []);
  /**
   * 주소가 바뀌면(같은 페이지 링크 · 이 화면이 맞춘 주소) 탭 · 짚은 직접 넣은 공고는 주소를 따른다(2.0.6) — 화면 상태가 이겨 링크를 눌러도
   * 탭이 안 바뀌었다. 탭 단추로 고른 탭도 아래 주소 쓰기 effect 가 곧 주소에 적으므로(`openManual` 은 먼저 적는다) 여기서 비워도 같은 탭이다.
   * 다시 그려 주소를 새로 읽는다.
   */
  const [, rereadUrl] = useReducer((n: number) => n + 1, 0);
  const followUrl = useCallback(() => {
    setTab(null);
    setManualFocusOverride(null);
    rereadUrl();
  }, []);
  // 정리표 「← 목록으로」는 들어온 탭으로(2.0.6) — 늘 「전체」로 돌아가 검토 중 · 직접 넣기에서 연 사람이 자리를 잃었다.
  const [lastTab, setLastTab] = useState<ListTab>(tab);
  const [sheetBack, setSheetBack] = useState<ListTab>("list");
  if (tab !== lastTab) {
    setLastTab(tab);
    if (tab === "sheet") setSheetBack(lastTab);
  }

  const [digestCleared, setDigestCleared] = useState(false);
  const digest: DigestConditions = useMemo(
    () =>
      digestCleared
        ? NO_DIGEST
        : {
            onlyNew: urlParams.onlyNew,
            newToday: urlParams.newToday,
            onlyChanged: urlParams.onlyChanged,
            onlyPending: urlParams.onlyPending,
            dueWithin: urlParams.dueWithin,
            dueToday: urlParams.dueToday,
            onlyPass: urlParams.onlyPass,
          },
    [digestCleared, urlParams],
  );
  const digestActive = digestOn(digest);

  /**
   * 새 공고·마감은 목록만 있으면 여기서 셀 수 있다. **변경 여부와 결정 대기는 아니다** —
   * 공고 버전 기록과 결정 저장소를 읽어야 알 수 있어 화면이 스스로 판단하지 못한다.
   * 그래서 그 두 조건일 때만 집계를 한 번 불러 id 목록을 받는다. 그 밖에는 요청을 늘리지
   * 않는다. 이 호출도 실호출을 하지 않는다(`cached_only`).
   */
  const needIds = digest.onlyChanged || digest.onlyPending;
  const [digestIds, setDigestIds] = useState<{ changed: Set<string>; pending: Set<string> } | null>(null);
  // 받기 실패와 읽는 중을 가른다(2.0.6) — 읽는 동안에도 「받지 못해」가 떴다.
  const [digestIdsFailed, setDigestIdsFailed] = useState(false);
  useEffect(() => {
    if (!needIds) return;
    let alive = true;
    getTodayDigest(organizationId)
      .then((value) => {
        if (!alive) return;
        setDigestIds({ changed: new Set(value.changed_ids), pending: new Set(value.pending_ids) });
        setDigestIdsFailed(false);
      })
      .catch(() => {
        if (!alive) return;
        setDigestIds(null);
        setDigestIdsFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [needIds, organizationId]);
  const changedIds = digest.onlyChanged ? (digestIds?.changed ?? null) : null;
  const pendingIds = digest.onlyPending ? (digestIds?.pending ?? null) : null;
  /** 조건은 걸렸는데 id 목록이 아직 없는 상태 — 읽는 중이면 그렇다고, 못 받았으면 그렇다고 목록 위에 적는다. */
  const digestIdsNote =
    needIds && digestIds === null
      ? digestIdsFailed
        ? " — 변경·결정 목록을 받지 못해 그 조건은 적용하지 않았습니다"
        : " — 변경·결정 목록을 읽는 중입니다(읽을 때까지 그 조건은 걸지 않았습니다)"
      : null;

  // --- 나라장터 원본 목록 + 헬스 --------------------------------------------
  const applyDashboard = useCallback((results: DashboardResults, forDays: number) => {
    const [healthResult, procurementResult] = results;

    if (healthResult.status === "fulfilled") {
      setBackendStatus(healthResult.value.status === "ok" ? "connected" : "disconnected");
      setG2bConfigured(healthResult.value.g2b_api_configured);
      setSemanticFit(healthResult.value.semantic_fit ?? null);
      setAiDraft(
        healthResult.value.llm_live === undefined
          ? null
          : Boolean(healthResult.value.llm_live && healthResult.value.llm_credit_ok),
      );
      setLiveFlags({
        g2b_live: healthResult.value.g2b_live,
        bizinfo_live: healthResult.value.bizinfo_live,
        keyword_search_live: healthResult.value.keyword_search_live,
      });
    } else {
      setLiveFlags(null);
      setBackendStatus("disconnected");
      setG2bConfigured(null);
      setSemanticFit(null);
      setAiDraft(null);
    }

    if (procurementResult.status === "fulfilled") {
      setProcurements(procurementResult.value);
      setProcurementError(null);
      setProcurementStatus("ready");
    } else {
      setProcurements(null);
      setProcurementError(describeError(procurementResult.reason));
      setProcurementStatus("error");
    }
    setProcurementDays(forDays);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const forDays = days;
    void fetchDashboard(forDays).then((results) => {
      if (!cancelled) applyDashboard(results, forDays);
    });
    return () => {
      cancelled = true;
    };
  }, [applyDashboard, days, reloadTick]);

  // --- 기업마당 원본 목록 (회사가 바뀌면 다시) -------------------------------
  useEffect(() => {
    let cancelled = false;
    const key = `${organizationId}|${reloadTick}`;
    getSupportPrograms({ organizationId })
      .then((value) => {
        if (cancelled) return;
        setSupport(value);
        setSupportError(null);
        setSupportLoadedFor(key);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setSupportError(describeError(error));
        setSupportLoadedFor(key);
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId, reloadTick]);

  // --- 통합 목록 (회사·기간·마감 포함 여부가 바뀌면 순위를 다시 계산) ---------
  // sort는 항상 priority로 받는다. priority_rank가 「회사 기준 검토 우선순위」 순위여야
  // 화면에서 다른 정렬을 골라도 순위 숫자의 의미가 흔들리지 않는다.
  useEffect(() => {
    let cancelled = false;
    const key = unifiedKey;
    // **언제나 「불가」까지 받는다.** 이 화면은 나라장터·기업마당 목록을 따로 받아 통합
    // 응답을 id 로 붙이는 구조라, 여기서 빼 버리면 그 행이 「통합 순위 없음」으로 남는다
    // (숨기는 것이 아니라 근거를 잃는다). 숨기기는 아래에서 행 단위로 한다.
    getBusinessOpportunities({ organizationId, source: "all", days, sort: "priority", includeClosed, includeBlocked: true })
      .then((value) => {
        if (cancelled) return;
        setUnified(value);
        setUnifiedError(null);
        setUnifiedLoadedKey(key);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setUnifiedError(describeUnifiedError(error));
        setUnifiedLoadedKey(key);
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId, days, includeClosed, unifiedKey]);

  /**
   * 쉬운 보기 「더 보기 ⋯」(네이티브 details) — 바깥을 누르거나 Escape 면 닫는다. 폰 폭에서 정렬을 바꾼 뒤에도 목록을
   * 덮은 채 남았다 (OPP-06). 안에서 연 팝오버가 있으면 Escape 는 그 팝오버만 닫는다.
   */
  const moreRef = useRef<HTMLDetailsElement | null>(null);
  useEffect(() => {
    const dismiss = (event: Event) => {
      const menu = moreRef.current;
      if (!menu?.open) return;
      if (event instanceof KeyboardEvent) {
        if (event.key !== "Escape" || menu.querySelector('[aria-expanded="true"]')) return;
        menu.open = false;
        menu.querySelector("summary")?.focus();
      } else if (!menu.contains(event.target as Node) && !(event.target as Element | null)?.closest?.('[role="dialog"]')) {
        menu.open = false;
      }
    };
    window.addEventListener("pointerdown", dismiss);
    window.addEventListener("keydown", dismiss);
    return () => {
      window.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("keydown", dismiss);
    };
  }, []);

  /**
   * 전체 보기 머리의 「내보내기 · 점수 기준」이 제목 아래 **왼쪽**으로 떨어졌는가 — 그러면 패널을 왼쪽에 맞춘다.
   * 오른쪽 맞춤 그대로면 390 · 800 에서 화면 왼쪽 밖(-220px 안팎)으로 열렸다 (OPP-07). 줄바꿈 자리는 설명 글 길이가 정해
   * 폭 경계로는 못 맞춘다 — 실제 자리를 잰다.
   */
  const headerAsideRef = useRef<HTMLSpanElement | null>(null);
  const [headerAsideLeft, setHeaderAsideLeft] = useState(false);
  useEffect(() => {
    const measure = () => {
      const el = headerAsideRef.current;
      if (el) setHeaderAsideLeft(el.getBoundingClientRect().left < window.innerWidth / 2);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [displayMode]);

  // 시트의 onClose 를 렌더마다 새로 만들면 공용 useDismissable 이 다시 돌며 초점을 「필터」 단추로 되돌렸다 —
  // 체크 한 번 · 1분 시계마다 (OPP-13). 공용 쪽 고침은 공통 부품 몫이다.
  const closeFilter = useCallback(() => setFilterOpen(false), []);

  function reloadAll() {
    setBackendStatus("checking");
    setProcurementStatus("loading");
    setReloadTick((n) => n + 1);
  }

  function changeDays(next: PeriodDays) {
    if (next === days) return;
    setProcurementStatus("loading");
    setPeriodDays(next);
  }


  /** 쉬운 보기 「조건: … ✕」 — 검색어는 그대로 두고 조건만 푼다(검색창은 바로 위에 따로 보인다). */
  function clearConditions() {
    const keep = query;
    resetConditions();
    setQuery(keep);
  }

  function resetConditions() {
    // 탭은 조건이 아니다. 「조건 초기화」로 보던 목록이 바뀌면 안 된다.
    setDigestCleared(true);
    setQuery("");
    setIncludeClosed(false);
    // 비운다 — 회사 기본 정렬을 명시값으로 박으면 회사를 바꿔도 옛 정렬이 남았다(38차 FRONTEND-03)
    setSortKey(null);
    setSortCleared(true);
    setGrades(new Set());
    setTiers(new Set());
    // 조건 줄(쉬운 보기)에 보이는 셋 — 「✕」가 이것도 되돌린다(26차 ISSUE-154). 필터 수(filterCount)에도 들어가 있었다.
    setTrack("all");
    setIncludeBlocked(false);
    setIncludeUnrelated(false);
    setCertOnly(false);
    changeDays(DEFAULT_PERIOD_DAYS);
  }

  // --- 파생 데이터 ------------------------------------------------------------
  const unifiedLoading = unifiedLoadedKey !== unifiedKey;
  const supportLoading = supportLoadedFor !== `${organizationId}|${reloadTick}`;
  const procurementStale = procurementDays !== days;

  const unifiedById = useMemo(() => {
    const map = new Map<string, UnifiedOpportunity>();
    for (const item of unified?.items ?? []) map.set(item.id, item);
    return map;
  }, [unified]);

  const trimmedQuery = query.trim().toLowerCase();

  // 38차 §3-E — 「직접 넣기 · 후보함」 탭. 판정 · 순위는 통합 목록(서버)이 매긴 그대로다. 넣기 · 고치기 · 지우기 뒤에는 목록을 다시 받는다.
  // 패널의 「n위」 · 「이미 있음(n위)」는 회사 방식 순위다 — 실무순 회사면 출처 안에서 `practical_order` 로 다시 센다
  // (이 화면은 언제나 점수순으로 받아 `source_rank` 가 점수순이다 · 브리핑의 직접 넣은 공고 표와 같은 순서 · 38차 검토).
  const companyRanked = useMemo(() => {
    const items = unified?.items ?? [];
    if (unified?.ranking_method !== "practical") return unifiedById;
    const map = new Map<string, UnifiedOpportunity>();
    for (const source of new Set(items.map((item) => item.source_type))) {
      items
        .filter((item) => item.source_type === source)
        .sort((a, b) => (a.practical_order || 1e9) - (b.practical_order || 1e9))
        .forEach((item, index) => map.set(item.id, { ...item, source_rank: index + 1 }));
    }
    return map;
  }, [unified, unifiedById]);
  const manualItems = useMemo(
    () => (unified?.items ?? []).filter((item) => item.source_type === "manual").map((item) => companyRanked.get(item.id) ?? item),
    [unified, companyRanked],
  );
  const manualPanel = (
    <ManualInboxPanel
      // 회사가 바뀌면 새로 그린다(2.0.6) — 열어 둔 「직접 넣기」 창 · 붙여 넣던 글이 다른 회사 칸에 남아 저장되면 그 회사에 들어갔다(임시 저장본은 회사별로 남는다).
      key={organizationId}
      organizationId={organizationId}
      items={manualItems}
      lookup={(id) => companyRanked.get(id)}
      focusId={manualFocusOverride ?? urlParams.manualFocus}
      nowMs={nowMs}
      loading={unified === null || unifiedLoadedKey !== unifiedKey}
      // 40차 FRONT-04 — 직접 넣음 출처만 실패해도(통합 목록은 성공) 이 탭에 그 사유를 보인다(「0건 · 아직 없음」으로 읽혔다)
      listError={unifiedError ?? unified?.source_errors?.manual ?? null}
      onChanged={() => setReloadTick((n) => n + 1)}
    />
  );

  // 45차 M9 — 통합 목록을 다 받았고 마감을 켜지 않았으면 거기 없는 입찰(실제 마감 지남)은 뺀다(`g2bRowsOf` · 대시보드 통계와 같은 규칙)
  const g2bRows = useMemo<SourceRow[]>(
    () => g2bRowsOf(procurements?.notices ?? [], unifiedById, unified !== null && !unifiedLoading && !includeClosed),
    [procurements, unifiedById, unified, unifiedLoading, includeClosed],
  );

  const bizinfoRows = useMemo<SourceRow[]>(() => bizinfoRowsOf(support?.items ?? [], unifiedById), [support, unifiedById]);

  const manualRows = useMemo<Row[]>(
    () => (unified?.items ?? []).filter((item) => item.source_type === "manual").map((item) => ({ kind: "manual" as const, id: item.id, unified: item })),
    [unified],
  );

  /**
   * 「새 공고」로 볼 기간(일) — **응답이 정한다** (0920 §4-B-5 · ISSUE-078).
   *
   * 아직 못 받았으면 null 이고, 그때는 그 조건을 걸지 않는다. 화면이 3 을 지어 쓰면
   * 백엔드가 다른 기간으로 세고 있을 때 띠의 숫자와 목록의 건수가 조용히 갈린다.
   */
  const newDays = unified?.summary?.new_days ?? null;

  /**
   * 갈래 · 추천등급 · 키워드 등급 — 나라장터 전용 필터. 목록 · 출처별 건수 · 시연용 묶음이 **같은 술어**를 쓴다
   * (예전에는 건수만 이것을 빼고 세어 「나라장터 입찰 (45)」인데 목록은 「현재 조건 10건」이었다 · OPP-03).
   */
  const passesG2bFilters = useCallback(
    (row: Row) => {
      // 갈래는 등급·키워드보다 **먼저** 본다. 기업마당 행까지 걸러야 하기 때문이다 —
      // 지원사업에는 「무슨 일을 시키는가」라는 축이 없어 갈래를 고르면 목록에서 빠진다.
      // 옛 배포 스냅샷에는 work 필드 자체가 없다. `?? []` 로 막는다.
      if (track !== "all") {
        if (row.kind !== "g2b") return false;
        if (!(row.notice.work?.tracks ?? []).includes(track)) return false;
      }
      if (row.kind !== "g2b") return true;
      const { notice } = row;
      if (grades.size > 0 && !(notice.recommendation && grades.has(notice.recommendation.grade))) return false;
      if (tiers.size > 0 && !(notice.candidate && tiers.has(notice.candidate.tier))) return false;
      return true;
    },
    [track, grades, tiers],
  );

  // 출처 선택 옆 건수 = 지금 조건에서 실제로 보이는 건수. 목록과 어긋나면 안 된다.
  const visibleG2bCount = useMemo(
    () =>
      g2bRows.filter(
        (row) =>
          rowVisible(row, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated) &&
          rowMatchesDigest(row, digest, nowMs, changedIds, pendingIds, newDays) &&
          passesG2bFilters(row),
      ).length,
    [g2bRows, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated, digest, changedIds, pendingIds, newDays, passesG2bFilters],
  );
  const visibleBizinfoCount = useMemo(
    () =>
      bizinfoRows.filter(
        (row) =>
          rowVisible(row, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated) &&
          rowMatchesDigest(row, digest, nowMs, changedIds, pendingIds, newDays) &&
          passesG2bFilters(row),
      ).length,
    [bizinfoRows, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated, digest, changedIds, pendingIds, newDays, passesG2bFilters],
  );
  // 40차 마지막 검토 — 「전체」 탭 목록에는 직접 넣은 공고도 선다(D27) — 건수도 같은 범위로 센다
  const visibleManualCount = useMemo(
    () =>
      manualRows.filter(
        (row) =>
          rowVisible(row, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated) &&
          rowMatchesDigest(row, digest, nowMs, changedIds, pendingIds, newDays) &&
          passesG2bFilters(row),
      ).length,
    [manualRows, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated, digest, changedIds, pendingIds, newDays, passesG2bFilters],
  );

  const sortOptions = sortsFor(sourceTab);
  const effectiveSort: SortKey = sortOptions.some((s) => s.key === sortKey) ? sortKey : companySortKey;
  const sortHint = sortOptions.find((s) => s.key === effectiveSort)?.hint ?? "";
  const sortLabel = sortOptions.find((s) => s.key === effectiveSort)?.label ?? "회사 기준 검토 우선순위순";
  /** 머리 「정렬: 실무 우선순위순(회사 설정)」 — 회사 기본 정렬일 때만 「(회사 설정)」(37차 §3-A-4). */
  // 응답 전에는 회사 방식을 모른다 — 「점수순(회사 설정)」으로 지어 적지 않는다.
  const sortHead =
    unified === null && sortKeyOverride === null && (sortCleared || urlParams.sort === null)
      ? "정렬: 회사 설정 확인 중…"
      : sortHeadLine(sortLabel, unified !== null && effectiveSort === companySortKey);

  /** 출처 + 공통 조건까지 적용한 집합. 등급·키워드 칩 건수도 여기서 센다. */
  const commonRows = useMemo(() => {
    // 40차 D27 — 「전체」 탭에는 직접 넣은 공고도 선다(내려받은 파일 · 머리 건수와 같은 범위)
    const base = sourceTab === "g2b" ? g2bRows : sourceTab === "bizinfo" ? bizinfoRows : [...g2bRows, ...bizinfoRows, ...manualRows];
    return base.filter(
      (row) =>
        rowVisible(row, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated) &&
        rowMatchesDigest(row, digest, nowMs, changedIds, pendingIds, newDays),
    );
  }, [sourceTab, g2bRows, bizinfoRows, manualRows, trimmedQuery, includeClosed, nowMs, includeBlocked, includeUnrelated, digest, changedIds, pendingIds, newDays]);

  /**
   * 등급·키워드 필터는 나라장터 공고에만 적용한다 (지원사업에는 그 축이 없다).
   * 「전체」 탭의 회사 순서(실무순 · 점수순)는 출처를 번갈아 세운다 — 행의 「n위」는 출처 안 순위 그대로(39차 D22 · 서버와 같은 규칙).
   */
  const certApplies = certOnly && displayMode === "simple";
  /** 「사회적기업 · 여성기업 대상」 칩 옆 수 — 칩을 켜기 전 목록에서 센다(켜면 목록 수와 같다). */
  const certCount = useMemo(() => commonRows.filter((row) => passesG2bFilters(row) && rowCertTarget(row)).length, [commonRows, passesG2bFilters]);
  const visibleRows = useMemo(() => {
    const sorted = commonRows
      .filter((row) => passesG2bFilters(row) && (!certApplies || rowCertTarget(row)))
      .sort((a, b) => compareRows(a, b, effectiveSort));
    if (sourceTab !== "all" || (effectiveSort !== "practical" && effectiveSort !== "priority")) return sorted;
    return interleaveSources(
      sorted,
      (row) => ({
        source: row.kind,
        closed: row.unified?.closed ?? false,
        blocked: row.unified?.eligibility_gate === "FAIL",
        notRecommended: row.unified?.practical_group === "비추천",
      }),
      effectiveSort === "practical",
    );
  }, [commonRows, passesG2bFilters, effectiveSort, sourceTab, certApplies]);

  /**
   * 조건이 달라지면 다시 처음 20건부터.
   *
   * effect 로 되돌리면 한 번 더 렌더가 돌면서 「직전 조건의 100건」이 잠깐 보인다.
   * 조건 키를 개수와 함께 들고 있다가 렌더 중에 비교하는 편이 정확하다.
   */
  const conditionKey = `${sourceTab}|${sortKey}|${query}|${includeClosed}|${days}|${track}|${[...grades].join()}|${[...tiers].join()}|${digest.onlyNew}${digest.newToday}${digest.onlyChanged}${digest.onlyPending}${digest.dueWithin}${digest.dueToday}${digest.onlyPass}|${certApplies}`;
  const shownCount = shown.key === conditionKey ? shown.count : PAGE_SIZE;

  /**
   * 지금 조건의 주소 조각 — 주소 쓰기와 「사업계획서 작성 →」의 돌아갈 주소(37차 §3-E-3)가 **같은 값**을 쓴다.
   * 렌더 중에 만든다 — 주소창을 읽으면 effect 가 주소를 고치기 전 값(한 박자 늦은 조건)이 실렸다.
   */
  const conditionSearch = useMemo(() => {
    const next = new URLSearchParams();
    if (query.trim()) next.set("q", query.trim());
    if (sourceTab !== "all") next.set("src", sourceTab);
    if (days !== DEFAULT_PERIOD_DAYS) next.set("days", String(days));
    // 회사 기본과 같은 정렬이면 주소에 쓰지 않는다(「기본 조건이면 주소가 깨끗하다」 · check_selection).
    // 회사 방식을 아직 모르면(응답 전) 들어온 주소의 정렬을 그대로 둔다 — 지우면 링크로 고른 정렬을 잃는다.
    const chosenSort = sortKeyOverride ?? (sortCleared ? null : urlParams.sort);
    if (chosenSort && (unified === null || chosenSort !== companySortKey)) next.set("sort", chosenSort);
    if (track !== "all") next.set("track", track);
    if (includeClosed) next.set("closed", "1");
    if (includeBlocked) next.set("blocked", "1");
    if (includeUnrelated) next.set("unrelated", "1");
    // 「오늘 달라진 것」에서 온 조건도 그대로 남긴다. 여기서 빠뜨리면 이 effect 가
    // 첫 렌더 직후 주소를 다시 쓰면서 방금 눌러 들어온 조건을 지운다.
    if (digest.onlyNew) next.set("new", "1");
    else if (digest.newToday) next.set("new", "today");
    if (digest.onlyChanged) next.set("changed", "1");
    if (digest.onlyPending) next.set("pending", "1");
    if (digest.dueWithin > 0) next.set("due", String(digest.dueWithin));
    else if (digest.dueToday) next.set("due", "today");
    if (digest.onlyPass) next.set("pass", "1");
    if (tab !== "list") next.set("tab", tab);
    // 주소로 들어온 보기(`?mode=`)는 남긴다 — 값은 지금 토글 상태를 따른다 (24차).
    if (urlParams.mode) next.set("mode", displayMode);
    return next.toString();
  }, [query, sourceTab, days, sortKeyOverride, sortCleared, urlParams.sort, unified, companySortKey, track, includeClosed, includeBlocked, includeUnrelated, digest, tab, urlParams.mode, displayMode]);

  /**
   * 조건을 주소창에 남긴다.
   *
   * 예전에는 전부 useState 뿐이라 새로고침·뒤로 가기·링크 공유에서 조건이 사라졌다.
   * replace 를 쓰므로 조건을 만질 때마다 뒤로 가기 기록이 쌓이지 않는다.
   * 기본값은 주소에 적지 않는다 — 깨끗한 URL 이 공유하기 좋다.
   */
  useEffect(() => {
    // hydration 첫 렌더에서는 urlSearch 가 아직 서버 스냅샷(빈 문자열)이다.
    // 그 상태로 주소를 쓰면 링크로 들어온 조건을 우리가 지워 버린다 — 따라잡을 때까지 기다린다.
    if (urlSearch !== window.location.search) return;

    const next = new URLSearchParams(conditionSearch);
    // 공고 선택(`notice` · `support`)은 lib/selection 의 몫이다 — 지우지 않는다. 지우면 메뉴로 온 공고를
    // 이 화면이 표시하지도 못하고 주소에서도 잃었다 (27차 LNK-08).
    const current = new URLSearchParams(window.location.search);
    // `req`(정리표에서 열 요구사항)도 남긴다 — 빼면 첫 렌더에 지워져 대시보드에서 온 항목이 안 열렸다 (28차 §3-C).
    // `manual`(직접 넣은 공고 하나를 짚어 연 주소)도 남긴다 — 지우면 그 행 테두리가 그려지기 전에 사라졌다(39차 FRONTEND-01).
    for (const key of [NOTICE_QUERY_KEY, SUPPORT_QUERY_KEY, "req", "manual"]) {
      const value = current.get(key);
      if (value) next.set(key, value);
    }

    const search = next.toString();
    const url = search ? `${window.location.pathname}?${search}` : window.location.pathname;
    if (url !== window.location.pathname + window.location.search) {
      window.history.replaceState(null, "", url);
    }
  }, [urlSearch, conditionSearch]);

  /**
   * 카드 칩의 「지원 n/N」 — **지금 화면 조건**에서의 자리 (0925 §4-D-2 · ISSUE-101).
   *
   * 백엔드의 `source_total` 은 거르기 전 전체(기업마당 1,578)다. 「우선 검토」가 같은
   * 출처 상위 15% 를 보기 때문에 그 분모가 전체여야 하고, 그래서 그 값은 그대로 둔다.
   * 그런데 이 화면은 **불가까지 받아 클라이언트에서 거른다** — 그래서 바로 위 제목이
   * 「현재 조건 277건」인데 칩은 「지원 1/1578」이었다. 한 화면이 기업마당 숫자를
   * 셋(탭 277 · 칩 1578 · 머리 1578) 말한 자리다.
   *
   * 칩은 **담당자가 지금 보고 있는 목록**에서 몇 번째인가를 말한다. 머리줄의
   * 「기업마당 1,578 (불가 1,038 숨김)」이 전체를 말하는 자리다 — 숫자 하나에 설명 하나.
   */
  const sourcePlaces = useMemo(() => {
    const places = new Map<string, { rank: number; total: number }>();
    for (const kind of ["g2b", "bizinfo", "manual"] as const) {
      const same = visibleRows.filter((row) => row.kind === kind);
      same.forEach((row, index) => {
        places.set(`${row.kind}-${row.id}`, { rank: index + 1, total: same.length });
      });
    }
    return places;
  }, [visibleRows]);

  const pagedRows = visibleRows.slice(0, shownCount);
  const hasMore = visibleRows.length > pagedRows.length;
  // 도구 메뉴 「더 보기 ⋯」와 이름이 겹치지 않게 늘리는 수를 앞에 적는다 (OPP-25) · 천 단위 쉼표 (R27U-MSC-07).
  const moreLabel = `${Math.min(PAGE_SIZE, visibleRows.length - pagedRows.length)}건 더 보기 · 남은 ${(visibleRows.length - pagedRows.length).toLocaleString("ko-KR")}건`;

  /**
   * 지원사업 탭 요약 띠 (0924 §4-B-3).
   *
   * 「가능·확인 필요」만으로는 무엇부터 손댈지 알 수 없다. 담당자가 실제로 나누는 축은
   * 셋이다 — 바로 신청 가능 · 소재 해석만 남음 · 공급기업으로 간접 참여.
   * **여기서 새 판정을 만들지 않는다.** 백엔드가 준 게이트·간접 표시·열리는 조건만 센다.
   */
  const supportBand = useMemo(() => {
    const rows = visibleRows.filter((row) => row.kind === "bizinfo");
    let ready = 0;
    let region = 0;
    let indirect = 0;
    // 불가(「불가 포함」을 켰을 때)와 판정이 아직 없는 행은 「확인 필요」에 섞지 않고 따로 센다 (OPP-16).
    let blocked = 0;
    let pending = 0;
    for (const row of rows) {
      const item = row.unified;
      if (!item) pending += 1;
      else if (item.eligibility_gate === "FAIL") blocked += 1;
      else if (item.participation) indirect += 1;
      else if (item.eligibility_gate === "PASS") ready += 1;
      else if ((item.unlock_conditions ?? []).some((condition) => condition.includes(MERGED_REGION_HINT)))
        region += 1;
    }
    return { total: rows.length, ready, region, indirect, blocked, pending, rest: rows.length - ready - region - indirect - blocked - pending };
  }, [visibleRows]);

  /**
   * 마감됐지만 시연용으로 고정해 둔 공고 (0920 §4-B-2-b).
   *
   * 마감을 켜면 일반 목록에 섞여 들어오므로 그때는 여기서 비운다 — 같은 공고가 두 번 보이면
   * 건수가 맞지 않는다.
   */
  const pinnedClosedRows = useMemo(() => {
    // 기업마당 탭 · 「오늘 달라진 것」 조건 · 나라장터 전용 필터가 걸렸으면 붙이지 않는다 — 빈 목록 안내 아래에도
    // 나라장터 마감 공고가 나왔다(OPP-04).
    if (includeClosed || sourceTab === "bizinfo" || digestActive) return [];
    return g2bRows.filter(
      (row) =>
        row.kind === "g2b" &&
        row.notice.pinned &&
        isClosedRow(row, nowMs) &&
        rowVisible(row, trimmedQuery, true, nowMs) &&
        passesG2bFilters(row),
    );
  }, [g2bRows, includeClosed, sourceTab, digestActive, nowMs, trimmedQuery, passesG2bFilters]);

  /**
   * 메뉴가 `?notice=` 로 싣고 온 공고(또는 저장된 선택)가 **그려진 행에 없을 때** 목록 머리에 한 줄 (R27U-LNK-R6).
   * 강조 표시는 그려진 행에만 붙어, 첫 20건 밖이거나 조건에 걸려 숨은 공고로 오면 아무 표시도 없었다.
   * 받은 목록에 아예 없는 공고(합성 데모 등)는 말하지 않는다.
   */
  const sheetUnified = sheetNotice ? g2bRows.find((row) => row.id === sheetNotice)?.unified ?? null : null;
  const viewingRow = viewing ? g2bRows.find((row) => row.id === viewing) ?? bizinfoRows.find((row) => row.id === viewing) ?? null : null;
  const viewingIndex = viewingRow ? visibleRows.indexOf(viewingRow) : -1;
  const viewingNote =
    !viewingRow || pinnedClosedRows.includes(viewingRow) || (viewingIndex >= 0 && viewingIndex < shownCount) ? null : (
      <p role="status" data-viewing-note className="text-[12.5px] leading-5 text-cosmos-secondary">
        <span className="font-semibold text-cosmos-blue-text">{viewingRow.kind === "g2b" ? "지금 보는 공고" : "지금 보는 사업"}</span>
        {": "}
        {viewingRow.kind === "g2b" ? viewingRow.notice.title : viewingRow.view.program.title}
        {" — "}
        {viewingIndex < 0 ? (
          "지금 조건(출처 · 검색어 · 필터 · 불가/관련 낮음/마감 숨김)에서 숨겨져 있습니다."
        ) : (
          <>
            이 조건 {(viewingIndex + 1).toLocaleString("ko-KR")}번째{" "}
            <button
              type="button"
              className="mc-focus rounded font-semibold text-cosmos-cyan underline"
              onClick={() => {
                setShown({ key: conditionKey, count: Math.ceil((viewingIndex + 1) / PAGE_SIZE) * PAGE_SIZE });
                requestAnimationFrame(() => document.querySelector("[data-current-notice]")?.scrollIntoView({ block: "center" }));
              }}
            >
              펼치기
            </button>
          </>
        )}
      </p>
    );

  /** 건수의 단일 분모 (0920 §4-B-2). 이 화면은 건수를 **다시 세지 않는다**. */
  const summary = unified?.summary ?? null;
  /**
   * 기본으로 함께 접는 「관련 낮음」 건수 — 백엔드 요약에 없는 수라 받은 행에서 센다(불가는 요약의 숨김 수에 이미 있다).
   * 머리줄이 이것을 적지 않으면 「마감 전 N」과 「현재 조건 N건」의 차이가 설명되지 않았다 (OPP-23).
   */
  const unrelatedHidden = useMemo(
    () =>
      [...g2bRows, ...bizinfoRows].filter(
        (row) => row.unified?.relevance_note && row.unified.eligibility_gate !== "FAIL" && !isClosedRow(row, nowMs),
      ).length,
    [g2bRows, bizinfoRows, nowMs],
  );

  const sourceErrors = useMemo(
    () =>
      Object.entries(unified?.source_errors ?? {}).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0,
      ),
    [unified],
  );

  const anyLoading = procurementStatus === "loading" || procurementStale || supportLoading || unifiedLoading;
  const hasAnyRow = g2bRows.length + bizinfoRows.length > 0;
  // 45차 M1 — 통합 목록(순위 · 판정)이 처음 오기 전에는 행을 그리지 않는다. 입찰 원본으로 먼저 그린 임시 목록이
  // 3~6초 동안 「1위/511 · 마감 미상 · 판정 계산 중…」으로 서 있다가 통째로 바뀌었다. 통합 목록이 실패하면 원본 행을 그대로 보인다.
  const awaitingUnified = unified === null && unifiedError === null && unifiedLoading;
  const filterCount =
    (includeClosed ? 1 : 0) +
    (includeBlocked ? 1 : 0) +
    (includeUnrelated ? 1 : 0) +
    grades.size +
    tiers.size +
    (track === "all" ? 0 : 1);
  const conditionsChanged =
    filterCount > 0 || trimmedQuery.length > 0 || days !== DEFAULT_PERIOD_DAYS || effectiveSort !== companySortKey || digestActive;

  /**
   * 헤더 상태 칩 — 캐시/샘플/오류를 한눈에 알리고 자세한 건 팝오버 안에 둔다.
   * 기호 · 색 · 말은 레이더 칩과 같은 `DATA_STATUS_MARK` (27차 §3-E · UNI-18) — 시연 고정이면 「캐시」가 아니라 「시연 고정」.
   */
  const dataFrozen = Boolean(procurements?.frozen || support?.frozen || unified?.frozen);
  const dataStatus: DataStatus =
    backendStatus === "disconnected" || procurementStatus === "error" || sourceErrors.length > 0
      ? "error"
      : support?.source === "sample"
        ? "sample"
        : procurements?.source === "cached" || support?.source === "cached"
          ? dataFrozen
            ? "frozen"
            : "cached"
          : backendStatus === "checking" || anyLoading
            ? "loading"
            : "live";
  // 고정 모드라도 매일 아침 자동 받기가 돌았으면 그 말 — 단추 글자와 읽어 주는 이름 · 쉬운 보기 줄이 같은 말이다(38차 §5 검토)
  const dataToneNote =
    dataStatus === "live" || dataStatus === "loading"
      ? null
      : dataStatus === "frozen"
        ? collectTerm(unified?.collect_state)
        : DATA_STATUS_MARK[dataStatus].word;
  /**
   * 시연 고정 모드에서는 서버가 조회 기간과 상관없이 저장된 목록(30일치)을 그대로 준다. 기간을 바꿨으면 그 사실을
   * 적는다 — 조건 줄 · 내보내기 안내에 「최근 14일」만 적혀 있어 실제로 거른 줄 알았다 (OPP-02). 서버 동작은 그대로.
   */
  const periodFrozenNote =
    dataFrozen && days !== DEFAULT_PERIOD_DAYS
      ? `화면에서는 새로 받지 않아 조회 기간을 바꿔도 목록은 저장된 그대로입니다${procurements?.collected_by ? ` — 저장된 목록: ${procurements.collected_by}` : ""}.`
      : null;

  /**
   * 「재수집」 (20차 §4-G · 담당자 「사업기회에 재수집 버튼 추가. 나라장터, 기업마당으로.」).
   * 확인 대화상자 → 받는 동안 「받는 중…」 → 결과 한 줄 + 목록 다시 읽기. 409·오류는 문구 그대로 보인다.
   */
  async function recollect(source: RecollectSource) {
    const label = RECOLLECT_LABELS[source];
    if (!window.confirm(`${label} 공고 목록을 새로 받습니다. 지금 저장된 목록이 새 목록으로 바뀝니다. 계속할까요?`)) return;
    setRecollecting(source);
    setRecollectNote(null);
    try {
      const result = await recollectOpportunities(source);
      setRecollectNote({ ok: true, text: recollectSummary(result) });
      reloadAll();
    } catch (error) {
      setRecollectNote({ ok: false, text: describeFailure(error, `${label} 새로 받기를 하지 못했습니다.`) });
    } finally {
      setRecollecting(null);
    }
  }

  /**
   * 재수집 잠김 이유 — 서버 상태를 못 받았으면(연결 끊김) 「시연 고정 모드」라고 단정하지 않는다 (OPP-18).
   * 판단과 문장은 `lib/recollect` 하나다(`recollectLock(null)` = 「서버 상태를 몰라 재수집 잠김」) — 이 화면에 사본을 두지 않는다.
   */
  const recollectReasons: Record<RecollectSource, string | null> = {
    g2b: recollectLock(liveFlags, "g2b"),
    bizinfo: recollectLock(liveFlags, "bizinfo"),
  };
  const recollectReasonText =
    recollectReasons.g2b && recollectReasons.g2b === recollectReasons.bizinfo
      ? recollectReasons.g2b
      : (["g2b", "bizinfo"] as const)
          .flatMap((source) => (recollectReasons[source] ? [`${RECOLLECT_LABELS[source]} ${recollectReasons[source]}`] : []))
          .join(" · ");
  // 데이터 상태 팝오버 — 메뉴 안(왼쪽 기준)에서는 start 로 연다 (OPP-07). 읽는 프로그램 이름에 캐시 · 오류도 (OPP-33).
  const dataStatusPopoverFor = (align: "start" | "end") => (
    <Popover
      align={align}
      width="340px"
      triggerLabel={`자료 상태${dataToneNote ? ` · ${dataToneNote}` : ""} · 출처와 조회 시각 보기`}
      title="자료 상태"
      // 「매일 아침 자동으로 받음 · 마지막 …」은 길다 — 390 폭 「더 보기 ⋯」 안에서 창 밖으로 나가지 않게 줄을 바꾼다
      triggerClassName="max-w-full text-left whitespace-normal!"
      trigger={<DataStatusLabel status={dataStatus} collectState={unified?.collect_state ?? null} />}
    >
      <DataStatusPanel
        backendStatus={backendStatus}
        g2bConfigured={g2bConfigured}
        semanticFit={semanticFit}
        aiDraft={aiDraft}
        procurements={procurements}
        support={support}
        unified={unified}
        loading={anyLoading}
        onReload={reloadAll}
        recollectLocks={recollectReasons}
        keywordSearchLive={liveFlags?.keyword_search_live === true}
      />
    </Popover>
  );
  // 잠긴 재수집 단추 옆에 이유를 **보이게** 적는다 — 팝오버를 열어야만 보였다 (OPP-18 · 화면 규칙 ③).
  const recollectButtons = (
    <>
      {(["g2b", "bizinfo"] as const).map((source) => {
        const lock = recollectReasons[source];
        return (
          <button
            key={source}
            type="button"
            data-recollect={source}
            disabled={lock !== null || recollecting !== null}
            aria-describedby={lock ? "opp-recollect-reason" : undefined}
            onClick={() => void recollect(source)}
            title={lock ?? `${RECOLLECT_LABELS[source]} 목록을 새로 받습니다`}
            className="mc-focus inline-flex min-h-8 shrink-0 items-center rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text disabled:cursor-not-allowed disabled:opacity-50"
          >
            {recollecting === source ? "받는 중…" : `${RECOLLECT_LABELS[source]} ${RECOLLECT_TERM}`}
          </button>
        );
      })}
      {recollectReasonText && (
        <span id="opp-recollect-reason" className="text-[12px] leading-4 text-cosmos-muted">
          {recollectReasonText}
        </span>
      )}
      {/* 잠김 사유 글 뒤에 둔다 — 앞에 있으면 그 글이 이 단추 설명처럼 읽혔다(바로 찾기는 따로 열린다 · frontend-3) */}
      <button
        type="button"
        data-collect-keywords-toggle
        aria-expanded={keywordsOpen}
        aria-controls={keywordsOpen ? "opp-keywords" : undefined}
        onClick={() => {
          setKeywordsOpen((open) => !open);
          // 쉬운 보기 「더 보기 ⋯」 안에서 눌렀으면 메뉴를 닫는다 — 패널은 목록 위에 펼친다.
          if (moreRef.current) moreRef.current.open = false;
        }}
        title="나라장터 공고를 찾는 낱말을 보고 더합니다"
        className="mc-focus inline-flex min-h-8 shrink-0 items-center rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
      >
        찾는 낱말
      </button>
    </>
  );
  /**
   * 「찾는 낱말」 패널 (2.0.7) — 바로 찾기로 찾은 것이 있으면 목록을 다시 읽고 검색칸에 그 낱말을 넣어 결과만 보인다.
   * 찾은 것 중 「관련 낮음」(기본 목록에서 접힘)이 있으면 접힌 것을 함께 보는 단추를 준다.
   */
  const keywordsPanel = keywordsOpen && (
    <CollectKeywordsPanel
      id="opp-keywords"
      onClose={() => setKeywordsOpen(false)}
      collectState={unified?.collect_state ?? null}
      onSearched={(result) => {
        if (result.found === 0) return;
        reloadAll();
        setTab("list");
        if (sourceTab === "bizinfo") setSourceTab("g2b");
        // 「n건 찾음」과 옮겨 간 목록이 같게 — 기본으로 숨는 참가 불가 · 실제 마감이 지난 공고도 켠다(frontend-1 · 대시보드 결과 주소도 같다)
        setIncludeBlocked(true);
        setIncludeClosed(true);
        setQuery(result.word);
      }}
      resultAction={(result) =>
        result.low > 0 &&
        !includeUnrelated && (
          <Button size="sm" variant="secondary" onClick={() => setIncludeUnrelated(true)} data-keyword-include-low>
            관련 낮음 포함해서 보기
          </Button>
        )
      }
    />
  );
  // 파일은 화면 정렬 다섯을 그대로 받는다(37차 §3-C-3) — 서버 `sort` 와 같은 열쇠다.
  const fileSort: OpportunitySort = effectiveSort;
  const fileSortLabel = sortLabel;
  /**
   * 안내는 **파일에 실제로 들어가는 조건**만 적는다 (OPP-05). 예전 「지금 조건 그대로」는 검색어 · 필터 · 관련 낮음 숨김 ·
   * 다른 정렬이 빠지는데도 그렇게 말해, 기본 조건에서도 파일 행 수가 화면 「현재 조건 N건」보다 많았다.
   */
  const exportHint =
    `파일에 반영: 최근 ${days}일${periodFrozenNote ? "(목록은 저장된 그대로)" : ""} · ${SOURCE_TABS.find((t) => t.key === sourceTab)?.label ?? "전체"}${includeClosed ? " · 마감 포함" : ""}${includeBlocked ? " · 불가 포함" : ""} · ${fileSortLabel}` +
    ". " +
    "검색어 · 필터(등급 · 일의 종류) · 「관련 낮음」 숨김 · 「오늘 달라진 것」 조건은 파일에 반영되지 않습니다.";
  const exportMenuFor = (align: "start" | "end") => (
    <ExportMenu
      align={align}
      query={{
        organizationId,
        days,
        includeClosed,
        includeBlocked,
        source: sourceTab === "all" ? undefined : sourceTab,
        sort: fileSort,
      }}
      hint={exportHint}
    />
  );
  const listAlerts = (
    <>
      {tab === "list" && procurementStatus === "error" && !procurementStale && (
        <InlineAlert tone="fail">
          {procurementError ?? "나라장터 공고를 불러오지 못했습니다."}{" "}
          <button type="button" onClick={reloadAll} className="mc-focus rounded font-semibold text-cosmos-cyan underline">
            다시 시도
          </button>
        </InlineAlert>
      )}
      {tab === "list" && supportError && <InlineAlert tone="warn">기업마당 목록: {supportError}</InlineAlert>}
      {tab === "list" && unifiedError && <InlineAlert tone="warn">{unifiedError} 출처별 목록은 그대로 표시합니다.</InlineAlert>}
      {(tab === "list" ? sourceErrors : []).map(([key, message]) => (
        <InlineAlert key={key} tone="warn" role="status">
          {/* 2.0.6 — 직접 넣음 키가 「manual 수집 문제」로 나왔다 · 화면 낱말로 */}
          {key === "g2b" ? "나라장터 수집" : key === "bizinfo" ? "기업마당 수집" : key === "manual" ? "직접 넣은 공고 목록" : "다른 출처 목록"} 문제: {message} — 나머지 출처는 그대로 표시합니다.
        </InlineAlert>
      ))}
    </>
  );
  const listStates = (
    <>
      {((anyLoading && !hasAnyRow) || awaitingUnified) && <LoadingState label="사업기회를 불러오는 중" rows={4} />}

      {!anyLoading && !hasAnyRow && procurementStatus !== "error" && (
        <EmptyState title="조회 기간 안에 사업기회가 없습니다" action={<Button variant="primary" onClick={reloadAll}>{VIEW_RELOAD_TERM}</Button>}>
          조회 기간을 넓히거나 「필터」에서 마감된 건도 포함해 보세요.
        </EmptyState>
      )}

      {hasAnyRow && visibleRows.length === 0 && (
        <EmptyState title="조건에 맞는 사업기회가 없습니다" action={<Button variant="secondary" onClick={resetConditions}>조건 초기화</Button>}>
          검색어를 바꾸거나 필터를 줄여 보세요. 마감된 건은 「필터」에서 포함할 수 있습니다.
        </EmptyState>
      )}
    </>
  );
  // 지금 실제로 숨긴 것만 센다 — 「불가 포함」을 켰는데도 「불가 N건이 숨겨져」라고 적지 않게.
  const hiddenParts = [
    ...(!includeBlocked && summary?.blocked ? [`불가 ${summary.blocked.toLocaleString("ko-KR")}건`] : []),
    ...(!includeUnrelated && unrelatedHidden > 0 ? [`관련 낮음 ${unrelatedHidden.toLocaleString("ko-KR")}건`] : []),
  ];
  // 고급 옵션 — 기본 화면에서 뺐지만 지우지 않았다
  const filterSheet = (
    <Sheet
      open={filterOpen}
      onClose={closeFilter}
      title="필터"
      description={`검색·기간·정렬은 ${displayMode === "simple" ? "「더 보기 ⋯」 메뉴" : "도구모음"}에 있고, 여기에는 불가·관련 낮음 포함 · 마감 포함 · 나라장터 전용 필터와 출처가 있습니다.`}
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={resetConditions}>
            조건 초기화
          </Button>
          <Button variant="primary" size="sm" onClick={() => setFilterOpen(false)}>
            닫기
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4 pt-1">
        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">지원 가능</p>
          <label className="mc-focus flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border border-cosmos-border px-3 text-[12.5px] text-cosmos-secondary">
            <input type="checkbox" checked={includeBlocked} onChange={(e) => setIncludeBlocked(e.target.checked)} />
            참가·신청할 수 없다고 판정한 건도 포함
          </label>
          <label className="mc-focus flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border border-cosmos-border px-3 text-[12.5px] text-cosmos-secondary">
            <input
              type="checkbox"
              checked={includeUnrelated}
              onChange={(e) => setIncludeUnrelated(e.target.checked)}
            />
            회사와 관련이 낮다고 판정한 지원사업도 포함
          </label>
          <p className="text-[12px] leading-4 text-cosmos-muted">
            기본은 <strong className="text-cosmos-text">가능 · 확인 필요</strong>이면서 관련 낮음이 아닌 것만 보여 줍니다.
            {hiddenParts.length > 0 ? ` 지금 ${hiddenParts.join(" · ")}이 숨겨져 있습니다.` : ""}{" "}
            {/* 쉬운 보기 행에는 「자세히」의 판정 근거가 없다 (OPP-27) */}
            판정 이유는 각 {displayMode === "simple" ? "행을 펼치면" : "카드의 「자세히」에서"} 볼 수 있습니다.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">마감</p>
          <label className="mc-focus flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border border-cosmos-border px-3 text-[12.5px] text-cosmos-secondary">
            <input
              type="checkbox"
              checked={includeClosed}
              onChange={(e) => {
                setIncludeClosed(e.target.checked);
                // 마감을 끄면 숨겨지는 「마감」 등급 칩의 선택도 푼다 — 안 보이는 칩이 목록을 비우지 않게.
                if (!e.target.checked) setGrades((s) => (s.has("NO_GO") ? toggleSet(s, "NO_GO" as RecommendationGrade) : s));
              }}
            />
            마감된 건도 포함
          </label>
          <p className="text-[12px] leading-4 text-cosmos-muted">마감 여부는 서버 판정을 그대로 씁니다. 마감일이 없는 건은 마감으로 보지 않습니다.</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">추천등급 (나라장터 전용)</p>
          <div className="flex flex-wrap gap-1.5">
            {/* 「마감」 등급은 마감 포함을 켜야 목록에 있다 — 켜기 전에는 늘 0건이라 그리지 않는다 (OPP-20) */}
            {GRADES.filter((grade) => grade !== "NO_GO" || includeClosed).map((grade) => (
              <Chip
                key={grade}
                active={grades.has(grade)}
                color={TONE_COLORS[GRADE_TONE[grade]]}
                onClick={() => setGrades((s) => toggleSet(s, grade))}
                title={`${gradeLabel(grade)} · ${GRADE_HINTS[grade]}`}
              >
                {gradeLabel(grade)}
                <span className="font-mono text-[12px] tabular-nums opacity-80">
                  {commonRows.filter((r) => r.kind === "g2b" && r.notice.recommendation?.grade === grade).length}
                </span>
              </Chip>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">낱말 관련도 (나라장터)</p>
          <div className="flex flex-wrap gap-1.5">
            {/* 「보통」은 더 이상 어떤 공고도 받지 않는다 — 옛 자료에 남아 있을 때만 그린다 (OPP-20) */}
            {(["high", "medium", "low"] as CandidateTier[])
              .filter((tier) => tier !== "medium" || commonRows.some((r) => r.kind === "g2b" && r.notice.candidate?.tier === "medium"))
              .map((tier) => (
              <Chip key={tier} active={tiers.has(tier)} color={TIER_COLOR[tier]} onClick={() => setTiers((s) => toggleSet(s, tier))} title={TIER_LABEL[tier]}>
                {TIER_SHORT[tier]}
                <span className="font-mono text-[12px] tabular-nums opacity-80">
                  {commonRows.filter((r) => r.kind === "g2b" && r.notice.candidate?.tier === tier).length}
                </span>
              </Chip>
            ))}
          </div>
          <p className="text-[12px] leading-4 text-cosmos-muted">
            등급 · 낱말 관련도는 나라장터 공고에만 있는 축이라 기업마당 지원사업에는 적용하지 않습니다.
          </p>
        </div>

        {/* 갈래 정보가 없는 응답(옛 스냅샷)에서는 그리지 않는다 — 항상 0건인 필터는 고장으로 읽힌다. */}
        {commonRows.some((r) => r.kind === "g2b" && r.notice.work !== undefined) && (
        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">일의 종류 (나라장터 전용)</p>
          <div className="flex flex-wrap gap-1.5">
            {(["all", "education", "development", "other", "unclassified"] as Array<WorkTrack | "all">).map((key) => (
              <Chip
                key={key}
                active={track === key}
                color={key === "other" ? COSMOS_COLORS.amber : undefined}
                onClick={() => setTrack(key)}
                title={key === "all" ? "일의 종류로 좁히지 않습니다" : WORK_TRACK_LABELS[key]}
              >
                {key === "all" ? "전체" : WORK_TRACK_LABELS[key]}
                {key !== "all" && (
                  <span className="font-mono text-[12px] tabular-nums opacity-80">
                    {commonRows.filter((r) => r.kind === "g2b" && (r.notice.work?.tracks ?? []).includes(key)).length}
                  </span>
                )}
              </Chip>
            ))}
          </div>
          <p className="text-[12px] leading-4 text-cosmos-muted">
            「무슨 일을 시키는가」로 좁힙니다. 교육이면서 개발인 공고는 양쪽에 모두 나옵니다.
            갈래를 고르면 기업마당 지원사업은 빠집니다 — 지원사업에는 이 축이 없습니다.
          </p>
        </div>
        )}

        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">출처</p>
          <p className="text-[12px] leading-5 text-cosmos-muted">
            {/* 45차 M10 — 출처마다 다른 정렬이 있다고 적었는데 정렬은 어느 출처든 같은 다섯 가지다 */}
            정렬은 어느 출처에서나 같은 다섯 가지(실무 우선순위 · 검토 우선순위 · 마감 여유 · 마감 임박 · 최신 등록)입니다. 순위는 출처 안에서만 매깁니다.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {SOURCE_TABS.filter((t) => t.key !== "all").map((t) => (
              <Chip key={t.key} active={sourceTab === t.key} color={t.key === "g2b" ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet} onClick={() => setSourceTab(t.key)}>
                {t.label}
              </Chip>
            ))}
            <Chip active={sourceTab === "all"} onClick={() => setSourceTab("all")}>
              전체
            </Chip>
          </div>
        </div>
      </div>
    </Sheet>
  );

  // 두 갈래(쉬운 · 전체)가 **같은 감싸개**로 토글을 넘긴다 — 모양이 다르면 토글이 다시 만들어져 키보드 초점을 잃었다(26차 ISSUE-154).
  // 머리 오른쪽 순서: 회사 → 보기 전환 → 화면 단추 (27차 §3-E-4). 회사를 바꾸면 순위를 다시 계산한다.
  const headerAsideFor = (full: boolean) => (
    <>
      <OrganizationPicker id="opp-organization" list={organizations.list} organizationId={organizationId} />
      <ViewModeSwitch titles={OPPORTUNITIES_VIEW_TITLES} />
      {full && headerAsideRest}
    </>
  );
  // 레이더로 건널 때 지금 조건(출처 · 갈래 · 정렬 · 마감 포함)을 싣는다 (27차 LNK-09).
  const radarHref = hrefWithConditions("/radar", { src: sourceTab, track, sort: effectiveSort === companySortKey ? null : effectiveSort, closed: includeClosed });
  const headerAsideRest = (
    <>
      <Link
        href={radarHref}
        className="mc-focus inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[12px] font-medium text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
        title="같은 데이터를 레이더 평면도로 봅니다. 이 목록 화면은 그대로 유지됩니다."
      >
        <span aria-hidden="true">◎</span>
        레이더로 보기
      </Link>
      {dataStatusPopoverFor("end")}
      {recollectButtons}
    </>
  );

  /**
   * 쉬운 보기 (24차 · prompt_14 §3-3) — 탭 넷 · 검색 · 「더 보기 ⋯」 하나 · 한 줄 행.
   * 조건 · 정렬 · 순위 · 판정은 전체 보기와 **같은 값**이다(위에서 계산한 것을 그대로 쓴다). 새 판정이 없다.
   */
  if (displayMode === "simple") {
    const simpleTab: SimpleTab = tab === "list" ? sourceTab : tab;
    const conditionLabels = [
      ...(digestActive ? [...digestLabels(digest, newDays), digestScopeLabel(digest, sourceTab)] : []),
      ...(includeClosed ? ["마감 포함"] : []),
      ...(effectiveSort !== companySortKey ? [sortLabel] : []),
      ...(days !== DEFAULT_PERIOD_DAYS ? [`최근 ${days}일${periodFrozenNote ? "(목록은 저장된 그대로)" : ""}`] : []),
      ...(grades.size + tiers.size > 0 ? [`필터 ${grades.size + tiers.size}개`] : []),
      ...(track !== "all" ? [`일의 종류 ${WORK_TRACK_LABELS[track]}`] : []),
      ...(includeBlocked ? ["불가 포함"] : []),
      ...(includeUnrelated ? ["관련 낮음 포함"] : []),
      ...(certApplies ? ["사회적기업 · 여성기업 대상만"] : []),
    ];
    return (
      <RankingMethodContext.Provider value={unified?.ranking_method ?? "score"}>
      <PlanBackContext.Provider value={conditionSearch ? `?${conditionSearch}` : ""}>
      <OpenSheetContext.Provider value={openSheet}>
      <Suspense fallback={null}>
        <SearchWatcher onChange={followUrl} />
      </Suspense>
      <AppShell headerAside={headerAsideFor(false)}>
        <div data-view="simple" className={`mx-auto flex w-full flex-col gap-4 ${tab === "sheet" ? "" : "max-w-[960px]"}`}>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="text-[20px] font-semibold text-cosmos-text">{SCREEN_NAMES.opportunities}</h1>
            <span className="text-[14px] text-cosmos-muted" data-sort-head title={sortHint}>{sortHead}</span>
            {/* 「회사자료 (전체 보기) →」 링크는 뺐다 — 위 메뉴에 같은 항목이 있고, 쉬운 보기 단추 12개 상한에 인증 칩 자리를 냈다(2.3.0). */}
            {unifiedLoading && <span className="text-[14px] text-cosmos-muted sm:ml-auto">순위 재계산 중…</span>}
          </div>
          {organizations.error && <InlineAlert tone="warn">{organizations.error}</InlineAlert>}
          {recollectNote && (
            <p role={recollectNote.ok ? "status" : "alert"} data-recollect-result className={`text-[14px] ${recollectNote.ok ? "text-cosmos-green" : "text-cosmos-red-text"}`}>
              {recollectNote.text}
            </p>
          )}
          {keywordsPanel}

          <div className="flex flex-wrap items-center gap-2">
            {/* 쉬운 보기 탭은 누름 단추 묶음이다 — tabs 규칙(탭 패널 · 화살표 키)을 다 갖추지 않았으므로 aria-pressed(26차 ISSUE-154). */}
            <div role="group" aria-label="목록 보기" className="flex flex-wrap items-center gap-1">
              {/* 「요구사항 정리표」는 열려 있을 때만 — 입찰 행 「요구사항 정리표 열기」로 들어간다(39차 · 선제준비 탭을 더해도 쉬운 보기 컨트롤 12 이하). */}
              {SIMPLE_TABS.filter((entry) => entry.key !== "sheet" || tab === "sheet").map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  aria-pressed={simpleTab === entry.key}
                  aria-label={entry.label}
                  data-simple-tab={entry.key}
                  onClick={() => {
                    if (entry.key === "review" || entry.key === "sheet" || entry.key === "manual" || entry.key === "prepare") {
                      setTab(entry.key);
                    } else {
                      setTab("list");
                      setSourceTab(entry.key);
                    }
                  }}
                  className={`mc-focus min-h-10 rounded-lg border px-4 text-[15px] font-medium transition-colors ${
                    simpleTab === entry.key
                      ? "border-cosmos-text/70 text-cosmos-text"
                      : "border-transparent text-cosmos-secondary hover:border-cosmos-border hover:text-cosmos-text"
                  }`}
                >
                  {entry.label}
                </button>
              ))}
            </div>
            {tab === "list" && (
              <>
                <label className="sr-only" htmlFor="opp-search">
                  사업명·기관·공고번호 검색
                </label>
                <input
                  id="opp-search"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="사업명 · 기관 · 공고번호 검색"
                  className={`${inputClass} min-h-10 w-full min-w-0 sm:w-auto sm:min-w-[15rem] sm:flex-1`}
                />
                {/* 샘플에듀 인증(사회적기업 · 여성기업)이 대상 글에 보이는 공고만(2.3.0 · 부스터의 「지원대상」 칩) — 판정이 아니라 낱말 거르기 */}
                <button
                  type="button"
                  aria-pressed={certOnly}
                  onClick={() => setCertOnly((value) => !value)}
                  data-cert-chip
                  title="제목 · 요약 · 대상 글에 「사회적기업 · 사회적경제 · 여성기업」이 보이는 공고만 — 신청 자격 판정은 아닙니다"
                  className={`mc-focus inline-flex min-h-10 items-center gap-1.5 whitespace-nowrap rounded-full border px-4 text-[15px] font-medium transition-colors ${
                    certOnly
                      ? "border-cosmos-cyan/70 bg-cosmos-cyan/15 text-cosmos-text"
                      : "border-cosmos-border text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
                  }`}
                >
                  {certOnly && <span aria-hidden="true">✓</span>}
                  사회적기업 · 여성기업 대상
                  <span className="font-mono tabular-nums text-cosmos-muted">{certCount.toLocaleString("ko-KR")}</span>
                </button>
              </>
            )}
            {/* 기간 · 정렬 · 필터 · 점수 기준 · 데이터 상태 · 내보내기 · 재수집 둘 — 한 메뉴 안(재수집 잠김 규칙 그대로). */}
            {/* 640px 미만에서는 제 줄에 둔다 — 「검토 중」 탭(검색칸 없음)에서 탭 옆에 서면 왼쪽 기준 상자가 오른쪽 밖으로 열렸다(26차 검수 FE-2). */}
            <details ref={moreRef} className="group relative basis-full sm:basis-auto" data-more-menu>
              <summary className="mc-focus flex min-h-10 w-fit cursor-pointer list-none items-center rounded-lg border border-cosmos-border px-4 text-[15px] text-cosmos-text hover:border-cosmos-border-strong">
                더 보기 ⋯
              </summary>
              {/* 640px 미만에서는 단추 왼쪽에 맞춘다 — 오른쪽에 맞추면 폰 폭에서 화면 왼쪽 밖(x≈-249)으로 열렸다(26차 ISSUE-151). */}
              <div className="absolute left-0 top-full z-30 mt-1 flex w-[min(92vw,380px)] max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-lg border border-cosmos-border-strong bg-cosmos-panel-solid p-3 shadow-[0_12px_32px_var(--cosmos-shadow)] sm:left-auto sm:right-0">
                {/* 목록 모양(2.3.0) — 한 번 정하면 되는 설정이라 메뉴 안(쉬운 보기 단추 12개 상한) · 열 때마다 카드 */}
                {tab === "list" && (
                  <div role="group" aria-label="목록 모양" className="flex flex-wrap items-center gap-2" data-layout-toggle={layout}>
                    <span className="text-[14px] text-cosmos-secondary">목록 모양</span>
                    {(["card", "list"] as const).map((value) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={layout === value}
                        onClick={() => setLayout(value)}
                        className={`mc-focus min-h-9 rounded-lg border px-3 text-[14px] ${
                          layout === value ? "border-cosmos-text/70 text-cosmos-text" : "border-cosmos-border text-cosmos-secondary hover:text-cosmos-text"
                        }`}
                      >
                        {value === "card" ? "카드" : "한 줄 목록"}
                      </button>
                    ))}
                  </div>
                )}
                {/* 기간 · 정렬 · 필터는 「검토 중」 목록에 걸리지 않는다 — 전체 보기처럼 그 탭에서는 감춘다 (OPP-21). */}
                {tab === "list" && (
                <div className="flex flex-wrap items-center gap-2">
                  <select aria-label="조회 기간" className={inputClass} value={days} onChange={(e) => changeDays(Number(e.target.value) as PeriodDays)}>
                    {PERIOD_OPTIONS.map((d) => (
                      <option key={d} value={d}>
                        최근 {d}일
                      </option>
                    ))}
                  </select>
                  <select aria-label="정렬 기준" className={inputClass} value={effectiveSort} onChange={(e) => setSortKey(e.target.value as SortKey)} title={sortHint}>
                    {sortOptions.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <Button size="sm" variant="secondary" onClick={() => setFilterOpen(true)} aria-haspopup="dialog">
                    필터
                    {filterCount > 0 && <span className="font-mono tabular-nums text-cosmos-cyan">{filterCount}</span>}
                  </Button>
                </div>
                )}
                {/*
                  세 팝오버는 한 줄에 하나씩 · 왼쪽 맞춤 — 패널(340~360px)이 이 메뉴(380px) 폭 안에서 열린다.
                  오른쪽 맞춤이면 좁은 폭 · 「검토 중」 탭에서 화면 왼쪽 밖으로 열렸다 (OPP-07).
                */}
                <div className="flex flex-col items-start gap-2">
                  <ScoreBasisPopover semanticFit={semanticFit} simple align="start" />
                  {dataStatusPopoverFor("start")}
                  {exportMenuFor("start")}
                </div>
                <div className="flex flex-wrap items-center gap-2">{recollectButtons}</div>
                <Link href={radarHref} className="mc-focus w-fit rounded text-[14px] text-cosmos-cyan hover:underline">
                  레이더로 보기 {FULL_VIEW_ONLY_TAG} →
                </Link>
              </div>
            </details>
          </div>

          {tab === "list" && conditionLabels.length > 0 && (
            <p className="text-[14px] text-cosmos-secondary" role="status" data-simple-conditions>
              조건: {conditionLabels.join(" · ")}
              {digestIdsNote}{" "}
              <button type="button" onClick={clearConditions} aria-label="조건 풀기" className="mc-focus rounded px-1 text-cosmos-text hover:underline">
                ✕
              </button>
            </p>
          )}
          {/* 캐시·샘플·오류는 메뉴 안으로 숨기지 않는다 (§20) — 목록 탭은 아래 한 줄에 합쳤다(2.3.0 · 안내 문장 줄이기) */}
          {dataToneNote && tab !== "list" && (
            <p className="text-[14px] text-cosmos-secondary" data-simple-data-note>
              자료 상태: {dataToneNote} — 받은 시각은 「더 보기 ⋯ › 자료 상태」에서 봅니다
            </p>
          )}

          {tab === "review" && <ReviewQueuePanel organizationId={organizationId} />}
          {tab === "manual" && manualPanel}
          {tab === "prepare" && <PreparePanel organizationId={organizationId} />}
          {tab === "sheet" && <RequirementSheet noticeId={sheetNotice} unified={sheetUnified} list={procurements} listError={unifiedError} listLoading={unified === null && unifiedError === null} listTab="입찰" onBack={() => setTab(sheetBack)} />}

          {tab === "list" && (
            <section aria-label="사업기회 목록" className="flex flex-col gap-2">
              {listAlerts}
              {/* 두 줄(자료 상태 · 확률 안내)을 한 줄로(2.3.0) — 받은 시각 자세히는 「더 보기 ⋯ › 자료 상태」 */}
              <p className="text-[14px] text-cosmos-secondary" data-simple-data-note={dataToneNote ? "" : undefined}>
                {dataToneNote ? `자료: ${dataToneNote} · ` : ""}검토 우선순위는 낙찰·선정 확률이 아닙니다
              </p>
              {viewingNote}
              {listStates}
              {visibleRows.length > 0 && !awaitingUnified && (
                <div role="list" className={layout === "card" ? "flex flex-col gap-3" : "flex flex-col border-t border-cosmos-border"} data-simple-rows data-layout={layout}>
                  {layout === "list" && (
                  <div aria-hidden="true" className={`hidden border-b border-cosmos-border px-2 py-1.5 text-[14px] text-cosmos-muted min-[700px]:grid ${SIMPLE_ROW_COLUMNS}`}>
                    <span>순위</span>
                    <span>출처</span>
                    <span>사업명</span>
                    <span>마감</span>
                    {/* 기업마당은 「신청」 말만 쓴다 (파일 머리 규칙 · OPP-22) */}
                    <span>{sourceTab === "bizinfo" ? "신청 가능?" : sourceTab === "g2b" ? "참가 가능?" : "참가·신청 가능?"}</span>
                    {/* 두 줄로 접혀도 「우선순위」가 쪼개지지 않게(§3-F OPP-37 검증) */}
                    <span className="break-keep">{REVIEW_PRIORITY_FULL}</span>
                  </div>
                  )}
                  {pagedRows.map((row, index) => {
                    // 43차 설명 — 실무 우선순위의 덩어리 경계 머리줄(본업 → 연구 · 감리 · 구매 → 대형 · 파트너형 후보 · 나라장터 탭에서만)
                    const block = blockHeadKey(row);
                    const prevBlock = index > 0 ? blockHeadKey(pagedRows[index - 1]) : null;
                    const blockHead =
                      effectiveSort === "practical" && sourceTab === "g2b" && block && block !== prevBlock && (index > 0 || block !== "본업")
                        ? BLOCK_HEADS[block] ?? block
                        : null;
                    const body =
                      row.kind === "manual" ? (
                        layout === "card" ? (
                          // 직접 넣은 공고는 원래 카드 모양(전체 보기 판)을 쓴다 — 고치기 · 공고문 올리기는 「직접 넣기」 탭에서
                          <div key={`manual-${row.id}`} role="listitem" data-simple-row data-layout="card">
                            <ManualListRow row={row} sourcePlace={sourcePlaces.get(`manual-${row.id}`) ?? null} nowMs={nowMs} onOpen={openManual} />
                          </div>
                        ) : (
                          <ManualListRow key={`manual-${row.id}`} row={row} sourcePlace={sourcePlaces.get(`manual-${row.id}`) ?? null} nowMs={nowMs} simple onOpen={openManual} />
                        )
                      ) : layout === "card" ? (
                        <SimpleOpportunityCard
                          key={`${row.kind}-${row.id}`}
                          row={row}
                          sourcePlace={sourcePlaces.get(`${row.kind}-${row.id}`) ?? null}
                          open={openId === row.id}
                          onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
                          unifiedLoading={unifiedLoading}
                          current={viewing === row.id}
                        />
                      ) : (
                        <SimpleOpportunityRow
                          key={`${row.kind}-${row.id}`}
                          row={row}
                          sourcePlace={sourcePlaces.get(`${row.kind}-${row.id}`) ?? null}
                          open={openId === row.id}
                          onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
                          unifiedLoading={unifiedLoading}
                          current={viewing === row.id}
                        />
                      );
                    return blockHead ? (
                      <Fragment key={`block-${row.kind}-${row.id}`}>
                        <p
                          role="presentation"
                          data-block-head
                          className={
                            layout === "card"
                              ? "px-1 pt-2 text-[14px] font-semibold text-cosmos-secondary"
                              : "border-b border-cosmos-border bg-cosmos-elevated/40 px-2 py-1 text-[13px] font-semibold text-cosmos-secondary"
                          }
                        >
                          {blockHead}
                        </p>
                        {body}
                      </Fragment>
                    ) : (
                      body
                    );
                  })}
                </div>
              )}
              {!includeClosed && pinnedClosedRows.length > 0 && (
                <div role="list" aria-label="예시 공고(마감)" className={layout === "card" ? "mt-2 flex flex-col gap-3" : "mt-2 flex flex-col border-t border-cosmos-border"}>
                  <p className="px-2 py-1.5 text-[14px] text-cosmos-muted">예시 공고(마감) {pinnedClosedRows.length}건 — 저장된 자료로 분석 화면이 열립니다.</p>
                  {pinnedClosedRows.map((row) => layout === "card" ? (
                    <SimpleOpportunityCard
                      key={`pinned-${row.kind}-${row.id}`}
                      row={row}
                      sourcePlace={null}
                      open={openId === row.id}
                      onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
                      unifiedLoading={unifiedLoading}
                      current={viewing === row.id}
                    />
                  ) : (
                    <SimpleOpportunityRow
                      key={`pinned-${row.kind}-${row.id}`}
                      row={row}
                      sourcePlace={null}
                      open={openId === row.id}
                      onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
                      unifiedLoading={unifiedLoading}
                      current={viewing === row.id}
                    />
                  ))}
                </div>
              )}
              {hasMore && (
                <div className="flex justify-center pt-1">
                  <Button variant="secondary" onClick={() => setShown({ key: conditionKey, count: shownCount + PAGE_SIZE })} data-list-more>
                    {moreLabel}
                  </Button>
                </div>
              )}
            </section>
          )}
        </div>
        {filterSheet}
      </AppShell>
      </OpenSheetContext.Provider>
      </PlanBackContext.Provider>
      </RankingMethodContext.Provider>
    );
  }

  return (
    <RankingMethodContext.Provider value={unified?.ranking_method ?? "score"}>
    <PlanBackContext.Provider value={conditionSearch ? `?${conditionSearch}` : ""}>
    <OpenSheetContext.Provider value={openSheet}>
    <Suspense fallback={null}>
      <SearchWatcher onChange={followUrl} />
    </Suspense>
    <AppShell headerAside={headerAsideFor(true)}>
      <SectionHeader
        as="h1"
        title={SCREEN_NAMES.opportunities}
        description="나라장터 입찰과 기업마당 지원사업을 한 화면에서 찾고 정렬합니다. 숫자는 「회사 기준 검토 우선순위」(먼저 볼 순서)이고, 낙찰·선정 가능성이 아닙니다."
        aside={
          // 좁으면 제목 아래 왼쪽으로 떨어진다 — 그때는 패널을 왼쪽 맞춤 · 640 미만은 한 줄에 하나(OPP-07).
          <span ref={headerAsideRef} className="flex flex-col items-start gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            {/*
              내려받기 (0921 §4-D-4). 검수자가 손으로 만든 표와 **같은 열**이고,
              **화면이 보고 있는 것과 같은 조건**을 그대로 넘긴다 — 파일과 화면이 갈리면
              담당자가 어느 쪽을 남에게 보내야 할지 알 수 없다.
            */}
            {exportMenuFor(headerAsideLeft ? "start" : "end")}
            <ScoreBasisPopover semanticFit={semanticFit} simple={false} align={headerAsideLeft ? "start" : "end"} />
          </span>
        }
      />
      {recollectNote && (
        // 재수집 결과 한 줄 — 409·오류도 숨기지 않고 문구 그대로 (20차 §4-G).
        <p
          role={recollectNote.ok ? "status" : "alert"}
          data-recollect-result
          className={`rounded-md border px-3 py-2 text-[12.5px] leading-5 ${
            recollectNote.ok
              ? "border-cosmos-green/40 bg-cosmos-green/10 text-cosmos-green"
              : "border-cosmos-red/40 bg-cosmos-red/10 text-cosmos-red-text"
          }`}
        >
          {recollectNote.text}
        </p>
      )}
      {keywordsPanel}

      {/* 한 줄 요약 — 카드 대신 보조 텍스트 한 줄 (회사 선택기는 머리 오른쪽 맨 앞으로 옮김 · 27차 UNI-07) */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/*
          건수는 **백엔드가 센 것 하나만** 쓴다 (0920 §4-B-2 · ISSUE-075).
          예전에는 여기서 `total_count`(마감 포함)를 적고 바로 아래 탭은 마감을 뺀 수를 적어,
          같은 화면이 「전체 107」과 「전체 (104)」를 나란히 말했다.
        */}
        <p className="text-[12.5px] text-cosmos-secondary" title={COUNT_HELP.header}>
          <span className="text-cosmos-muted">마감 전 </span>
          <strong className="font-mono font-semibold tabular-nums text-cosmos-text">{summary ? summary.open_total.toLocaleString("ko-KR") : "–"}</strong>
          <span className="text-cosmos-muted">건(나라장터 </span>
          <span className="font-mono tabular-nums">{summary ? summary.open_g2b.toLocaleString("ko-KR") : "–"}</span>
          <span className="text-cosmos-muted"> · 기업마당 </span>
          <span className="font-mono tabular-nums">{summary ? summary.open_bizinfo.toLocaleString("ko-KR") : "–"}</span>
          {(summary?.open_manual ?? 0) > 0 && (
            <>
              <span className="text-cosmos-muted"> · 직접 넣음 </span>
              <span className="font-mono tabular-nums">{(summary?.open_manual ?? 0).toLocaleString("ko-KR")}</span>
            </>
          )}
          {/* 실무 우선순위 회사는 분류 칸이 「우선 검토」를 대신한다(37차 §3-B-4) — 머리 숫자도 「신규+여유」(서버가 매긴 분류 그대로) */}
          <span className="text-cosmos-muted">) · {practicalCompany ? "신규+여유 " : "우선 검토 "}</span>
          <span className="font-mono tabular-nums" style={{ color: TONE_COLORS.pass }}>
            {practicalCompany ? (freshCount ?? "–").toLocaleString("ko-KR") : summary ? summary.priority.toLocaleString("ko-KR") : "–"}
          </span>
          <span className="text-cosmos-muted">건</span>
          {summary && summary.closed > 0 && (
            <span className="text-cosmos-muted">
              {" · 마감 "}
              {summary.closed.toLocaleString("ko-KR")}건
              {summary.closed_pinned > 0 ? `(예시 공고 ${summary.closed_pinned.toLocaleString("ko-KR")}건)` : ""}
            </span>
          )}
          {/*
            **숫자 하나에 설명 하나** (0925 §4-D-2). 이 줄은 마감 전 전체를 말하는데
            아래 탭과 카드 칩은 지금 조건의 수를 말한다. 그 차이가 무엇인지 적지 않으면
            담당자가 한 화면에서 「기업마당 1,578」과 「기업마당 578」을 읽고 어느 쪽이
            진짜인지 모른다 — 차이는 「불가」·「관련 낮음」을 숨긴 것이고, 그것은 되돌릴 수 있다.
            숨김 수는 두 출처를 합친 값이라 제 이름(「숨김」)을 단 마지막 조각으로 둔다 — 「기업마당 N」 바로 뒤 괄호에 붙어
            기업마당 몫으로 읽혔다(OPP-23). 「마감 전 N · 나라장터」 순서는 리허설 캡처가 기다리는 글이라 그대로.
          */}
          {summary && ((!includeBlocked && (summary.blocked ?? 0) > 0) || (!includeUnrelated && unrelatedHidden > 0)) && (
            <span className="text-cosmos-muted">
              {" · 숨긴 것: "}
              {[
                ...(!includeBlocked && (summary.blocked ?? 0) > 0 ? [`참가 불가 ${(summary.blocked ?? 0).toLocaleString("ko-KR")}건`] : []),
                ...(!includeUnrelated && unrelatedHidden > 0 ? [`관련 낮음 ${unrelatedHidden.toLocaleString("ko-KR")}건`] : []),
              ].join(", ")}
              {" — 「필터」에서 다시 볼 수 있음"}
            </span>
          )}
        </p>

        <div className="flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto">
          {unifiedLoading && <span className="text-[12px] text-cosmos-muted">순위 재계산 중…</span>}
          <Link href="/company" className="mc-focus rounded text-[12px] text-cosmos-cyan hover:underline">
            회사자료 →
          </Link>
        </div>
      </div>

      {organizations.error && <InlineAlert tone="warn">{organizations.error}</InlineAlert>}

      {/*
        두 목록을 나란히 둔다 (0919 §4-B-3).

        「전체 목록」은 **새로 들어온 것**을, 「검토 중」은 **손댄 흔적이 있는 것**을 본다.
        데이터도 정렬 축도 달라서 검색·출처·기간·정렬은 「검토 중」에 걸리지 않는다 — 그래서
        그 탭에서는 도구모음을 감춘다. 쓸 수 없는 조작을 남겨 두면 눌러 보고 아무 일도 일어나지
        않는 쪽이 더 나쁘다.
      */}
      {/*
        탭 규칙을 다 갖춘다 — 탭마다 패널(`opp-panel-*`) · 좌우 화살표 · 고른 탭만 Tab 순서에 (OPP-24 · 화면 규칙 ④).
      */}
      <div
        role="tablist"
        aria-label="목록 보기"
        className="flex flex-wrap items-center gap-1"
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const order: ListTab[] = ["list", "prepare", "review", "sheet", "manual"];
          const step = event.key === "ArrowRight" ? 1 : order.length - 1;
          const next: ListTab = order[(order.indexOf(tab) + step) % order.length];
          setTab(next);
          document.getElementById(`opp-tab-${next}`)?.focus();
        }}
      >
        {([
          { key: "list" as ListTab, label: "전체 목록", hint: "지금 조건에 맞는 사업기회 전부" },
          { key: "prepare" as ListTab, label: "선제준비", hint: "본공고 전 사전규격(본업만 먼저) · 발주 예정 — 입찰 순위에는 넣지 않습니다" },
          { key: "review" as ListTab, label: "검토 중", hint: "요구사항을 뽑았거나 참여 결정·최종 검토·발견 항목 처리를 남긴 공고" },
          { key: "sheet" as ListTab, label: SCREEN_NAMES.rfp, hint: "고른 입찰의 제안요청서 요구사항 표 — 페이지 · 원문 근거와 함께" },
          { key: "manual" as ListTab, label: "직접 넣기 · 후보함", hint: "나라장터 · 기업마당에 없는 공고를 넣고, GPT 결과를 붙여 넣고, 기관 게시판을 열어 봅니다" },
        ]).map((entry) => (
          <button
            key={entry.key}
            id={`opp-tab-${entry.key}`}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            aria-controls={`opp-panel-${entry.key}`}
            tabIndex={tab === entry.key ? 0 : -1}
            // title 을 그대로 두면 그것이 «이름»이 되어 읽는 프로그램이 「검토 중」 대신
            // 긴 설명을 읽는다. 이름은 보이는 글자로 고정하고 title 은 마우스 도움말로만 쓴다.
            aria-label={entry.label}
            title={entry.hint}
            onClick={() => setTab(entry.key)}
            className={`mc-focus min-h-8 rounded-lg border px-3 text-[12.5px] font-medium transition-colors ${
              tab === entry.key
                ? "border-cosmos-cyan/60 bg-cosmos-panel text-cosmos-text"
                : "border-transparent text-cosmos-secondary hover:border-cosmos-border hover:text-cosmos-text"
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div id="opp-panel-review" role="tabpanel" aria-labelledby="opp-tab-review" className={`flex-col gap-2.5 ${tab === "review" ? "flex" : "hidden"}`}>
        {tab === "review" && <ReviewQueuePanel organizationId={organizationId} />}
      </div>
      {/* 패널 틀은 늘 둔다(탭의 aria-controls 대상) — 표는 탭이 열렸을 때만 그린다(목록 응답과 따로 읽는다). */}
      <div id="opp-panel-manual" role="tabpanel" aria-labelledby="opp-tab-manual" className={`flex-col gap-2.5 ${tab === "manual" ? "flex" : "hidden"}`}>
        {tab === "manual" && manualPanel}
      </div>
      <div id="opp-panel-prepare" role="tabpanel" aria-labelledby="opp-tab-prepare" className={`flex-col gap-2.5 ${tab === "prepare" ? "flex" : "hidden"}`}>
        {tab === "prepare" && <PreparePanel organizationId={organizationId} />}
      </div>
      <div id="opp-panel-sheet" role="tabpanel" aria-labelledby="opp-tab-sheet" className={`flex-col gap-2.5 ${tab === "sheet" ? "flex" : "hidden"}`}>
        {tab === "sheet" && <RequirementSheet noticeId={sheetNotice} unified={sheetUnified} list={procurements} listError={unifiedError} listLoading={unified === null && unifiedError === null} listTab="전체 목록" onBack={() => setTab(sheetBack)} />}
      </div>

      {/* 도구모음 한 줄 — 검색 · 출처 · 기간 · 정렬 · 필터 */}
      <section aria-label="검색과 정렬" className={`flex-wrap items-center gap-2 ${tab === "list" ? "flex" : "hidden"}`}>
        <label className="sr-only" htmlFor="opp-search">
          사업명·기관·공고번호 검색
        </label>
        <input
          id="opp-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="사업명 · 기관 · 공고번호 검색"
          className={`${inputClass} w-full min-w-0 sm:w-auto sm:flex-1 sm:max-w-sm`}
        />
        <select
          aria-label="출처"
          className={inputClass}
          value={sourceTab}
          onChange={(e) => setSourceTab(e.target.value as SourceTab)}
          title={SOURCE_TABS.find((t) => t.key === sourceTab)?.hint}
        >
          {SOURCE_TABS.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
              {` (${(t.key === "all" ? visibleG2bCount + visibleBizinfoCount + visibleManualCount : t.key === "g2b" ? visibleG2bCount : visibleBizinfoCount).toLocaleString("ko-KR")})`}
            </option>
          ))}
        </select>
        <select
          aria-label="조회 기간"
          className={inputClass}
          value={days}
          onChange={(e) => changeDays(Number(e.target.value) as PeriodDays)}
          title="나라장터 공고 게시일 기준 조회 기간"
        >
          {PERIOD_OPTIONS.map((d) => (
            <option key={d} value={d}>
              최근 {d}일
            </option>
          ))}
        </select>
        <select aria-label="정렬 기준" className={inputClass} value={effectiveSort} onChange={(e) => setSortKey(e.target.value as SortKey)} title={sortHint}>
          {sortOptions.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
        <Button size="sm" variant="secondary" onClick={() => setFilterOpen(true)} aria-haspopup="dialog">
          필터
          {filterCount > 0 && <span className="font-mono text-[12px] tabular-nums text-cosmos-cyan">{filterCount}</span>}
        </Button>
        {conditionsChanged && (
          <Button size="sm" variant="ghost" onClick={resetConditions}>
            초기화
          </Button>
        )}
        {periodFrozenNote && <p className="basis-full text-[12px] leading-5 text-cosmos-muted">{periodFrozenNote}</p>}
      </section>

      {/* 실패는 숨기지 않는다. 캐시·샘플 같은 정상 대체는 「데이터 상태」에 있다. */}
      {listAlerts}

      {/* 「오늘 달라진 것」에서 눌러 들어왔을 때. 무엇이 걸렸는지 적지 않으면 목록이 왜 짧은지 알 수 없다. */}
      {tab === "list" && digestActive && (
        <InlineAlert tone="info" role="status">
          <span className="font-semibold">누른 숫자의 조건</span>: {digestLabels(digest, newDays).join(" · ")} · {digestScopeLabel(digest, sourceTab)}{includeClosed && " · 마감 포함"}
          {digestIdsNote}{" "}
          <button
            type="button"
            onClick={() => setDigestCleared(true)}
            className="mc-focus rounded font-semibold text-cosmos-cyan underline"
          >
            {/* 머리의 보기 전환 「전체 보기」와 이름이 같았다 — 쉬운 보기 ✕ 와 같은 이름 (OPP-25) */}
            조건 풀기
          </button>
        </InlineAlert>
      )}

      {/*
        지원사업 탭 요약 띠 (0924 §4-B-3).

        지원사업은 「가능·확인 필요」만으로는 무엇부터 손댈지 알 수 없다. 담당자가 실제로
        나누는 축은 셋이다 — **지금 바로 신청할 수 있는가 · 소재 해석만 남았는가 ·
        공급기업으로 간접 참여하는가**. 세는 것은 화면이 하지만 **판정은 백엔드가 준 값**이다.
      */}
      {tab === "list" && sourceTab === "bizinfo" && supportBand.total > 0 && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-cosmos-secondary" role="status">
          <span>
            <span className="text-cosmos-muted">바로 신청 가능 </span>
            <strong className="font-mono tabular-nums" style={{ color: TONE_COLORS.pass }}>
              {supportBand.ready.toLocaleString("ko-KR")}
            </strong>
            건
          </span>
          <span>
            <span className="text-cosmos-muted">회사 주소지 확인 필요 </span>
            <strong className="font-mono tabular-nums" style={{ color: TONE_COLORS.warn }}>
              {supportBand.region.toLocaleString("ko-KR")}
            </strong>
            건
          </span>
          <span>
            <span className="text-cosmos-muted">공급기업으로 참여 </span>
            <strong className="font-mono tabular-nums text-cosmos-text">{supportBand.indirect.toLocaleString("ko-KR")}</strong>건
          </span>
          {supportBand.blocked > 0 && (
            <span>
              <span className="text-cosmos-muted">불가 </span>
              <strong className="font-mono tabular-nums" style={{ color: TONE_COLORS.fail }}>
                {supportBand.blocked.toLocaleString("ko-KR")}
              </strong>
              건
            </span>
          )}
          <span className="text-cosmos-muted">· 나머지 {supportBand.rest.toLocaleString("ko-KR")}건은 확인 필요</span>
          {supportBand.pending > 0 && (
            <span className="text-cosmos-muted">
              · 판정 {unifiedLoading ? "계산 중" : "없음"} {supportBand.pending.toLocaleString("ko-KR")}건
            </span>
          )}
        </p>
      )}

      {/* 전체 목록 */}
      <section
        id="opp-panel-list"
        role="tabpanel"
        aria-labelledby="opp-list-heading"
        className={`flex-col gap-2.5 ${tab === "list" ? "flex" : "hidden"}`}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          {/* 「수집」과 「현재 조건」을 나눠 적는다. 두 숫자가 다른 것은 정상이며,
              예전에는 상단 104 와 목록 4 가 아무 설명 없이 나란히 있어 오해를 샀다. */}
          <h2 id="opp-list-heading" className="text-[13px] font-semibold text-cosmos-text">
            사업기회{" "}
            <span className="font-mono tabular-nums text-cosmos-muted">
              — 마감 전 {summary ? summary.open_total.toLocaleString("ko-KR") : "–"}건 중 지금 조건에 맞는{" "}
              {unifiedLoading && summary === null ? "계산 중…" : `${visibleRows.length.toLocaleString("ko-KR")}건`}
            </span>
            {pagedRows.length < visibleRows.length && (
              <span className="ml-1 font-mono text-[12px] tabular-nums text-cosmos-muted">
                (위에서부터 {pagedRows.length.toLocaleString("ko-KR")}건 보는 중)
              </span>
            )}
          </h2>
          <p className="text-[12px] text-cosmos-muted" data-sort-head>{sortHead} · {sortHint}</p>
        </div>

        {viewingNote}
        {listStates}

        {visibleRows.length > 0 && !awaitingUnified && (
          <ul className="flex flex-col gap-2" aria-label="사업기회 목록">
            {pagedRows.map((row, index) => (
              <li key={`${row.kind}-${row.id}`}>
                {row.kind === "manual" ? (
                  <ManualListRow row={row} sourcePlace={sourcePlaces.get(`manual-${row.id}`) ?? null} nowMs={nowMs} onOpen={openManual} />
                ) : (
                <OpportunityRowCard
                  row={row}
                  // 41차 FRONT-R40-08 — 직접 넣음 행(번호 없음)은 세지 않는다(1 · 2 · 4 로 건너뛰었다)
                  position={pagedRows.slice(0, index + 1).filter((r) => r.kind !== "manual").length}
                  emphasizeTop={sourceTab !== "all"}
                  sortLabel={sortLabel}
                  sourcePlace={sourcePlaces.get(`${row.kind}-${row.id}`) ?? null}
                  sourceBadge={
                    row.kind === "g2b"
                      ? { kind: noticeSourceKind(procurements?.source, row.notice.pinned) }
                      : unifiedSourceBadge(support?.source ?? "", "bizinfo")
                  }
                  fetchedAt={row.kind === "g2b" ? procurements?.fetched_at ?? null : support?.fetched_at ?? null}
                  open={openId === row.id}
                  onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
                  unifiedLoading={unifiedLoading}
                  current={viewing === row.id}
                />
                )}
              </li>
            ))}
          </ul>
        )}

        {/*
          시연용 (마감) — 대시보드 선택창에 있는 그룹을 목록에도 둔다 (0920 §4-B-2-b · ISSUE-075-b).

          마감된 고정 공고는 저장된 자료가 있어 분석 화면이 그대로 열린다. 그런데 목록에서만
          사라져서, 대시보드·레이더에는 보이는 공고가 목록에는 없었다. 일반 후보 사이에 끼우면
          「참여할 수 있는 공고」로 읽히므로 따로 묶는다.
        */}
        {tab === "list" && !includeClosed && pinnedClosedRows.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-cosmos-border pt-3">
            <p className="text-[12px] text-cosmos-muted">
              예시 공고(마감) {pinnedClosedRows.length}건 — 저장된 자료로 분석 화면이 열립니다. 마감 배지는 그대로입니다.
            </p>
            <ul className="flex flex-col gap-2" aria-label="예시 공고(마감)">
              {pinnedClosedRows.map((row) => (
                <li key={`pinned-${row.kind}-${row.id}`}>
                  <OpportunityRowCard
                    row={row}
                    position={null}
                    sortLabel={sortLabel}
                    sourcePlace={null}
                    sourceBadge={{ kind: noticeSourceKind(procurements?.source, true) }}
                    fetchedAt={procurements?.fetched_at ?? null}
                    open={openId === row.id}
                    onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
                    unifiedLoading={unifiedLoading}
                    current={viewing === row.id}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}

        {hasMore && (
          <div className="flex justify-center pt-1">
            <Button variant="secondary" size="sm" onClick={() => setShown({ key: conditionKey, count: shownCount + PAGE_SIZE })} data-list-more>
              {moreLabel}
            </Button>
          </div>
        )}
      </section>

      {filterSheet}
    </AppShell>
    </OpenSheetContext.Provider>
    </PlanBackContext.Provider>
    </RankingMethodContext.Provider>
  );
}

function toggleSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

// ---------------------------------------------------------------------------
// 오버레이: 점수 기준 · 데이터 상태
// ---------------------------------------------------------------------------

/**
 * 산정 방식 설명을 여기 한 번만 둔다 (본문에서 반복하지 않는다).
 * `semanticFit` — 서버가 알려 준 AI 의미 매칭 켜짐 여부(null 은 모름). `simple` — 쉬운 보기에서 열었는가(행에 「자세히」 산정 근거가 없다).
 */
function ScoreBasisPopover({ semanticFit, simple, align = "end" }: { semanticFit: boolean | null; simple: boolean; align?: "start" | "end" }) {
  // 산정 근거가 보이는 자리 — 쉬운 보기 행에는 없어 전체 보기로 보낸다 (OPP-27).
  const detailSpot = simple ? "전체 보기 카드의 「자세히」" : "카드의 「자세히」";
  // 외부 점검 UI b — 실무 우선순위 회사는 목록이 점수순이 아니다(37차) · 「전체」 탭은 출처를 번갈아 보인다(39차 D22)
  const practical = useRankingMethod() === "practical";
  return (
    <Popover triggerLabel="점수 기준 · 산정 방식 보기" title="점수 기준" width="340px" align={align} trigger={<>점수 기준</>}>
      <p>
        <strong className="text-cosmos-text">회사 기준 검토 우선순위</strong> (0~100)는 선택한 회사 기준으로 공고가 우리 회사와
        얼마나 맞는지 잰 점수입니다. 낙찰 · 선정 확률이 아닙니다.
      </p>
      {practical && (
        <p>
          <strong className="text-cosmos-text">목록 순서는 점수순이 아닙니다.</strong> 이 회사는 「실무 우선순위」로 세웁니다 — 본업인지,
          마감까지 남은 기간, 접수 방식, 일의 종류를 먼저 보고 점수는 그다음입니다. 그래서 60점 공고가 70점 공고보다 위에 있을 수 있습니다.
        </p>
      )}
      {/* backend `opportunity_priority.PRIORITY_WEIGHTS` 와 같은 배점이어야 한다 (추천등급 배점과 다르다). */}
      <ul className="flex flex-col gap-0.5 text-[12px] text-cosmos-secondary">
        <li>회사 사업영역 적합도 35 · 참여·신청자격 적합도 25</li>
        <li>수행근거·보유역량 20 · 규모 적합도 10 · 전략적 가치 10</li>
      </ul>
      {/*
        8차에서 「일정 여유」를 뺐다 (0922 §4-B-0 · ISSUE-083). 마감이 배점에 있으면 키워드가
        맞는 공고끼리는 마감 순서가 곧 순위가 된다 — 실측에서 81점 8건·77점 25건이 그 항목
        하나로 갈렸고, 검수자가 고른 1순위가 23위였다.
      */}
      <p>
        {/* 추천등급에는 일정 여유가 있다 — 이 문장이 그것까지 부정하는 것처럼 읽혔다 (OPP-26) */}
        <strong className="text-cosmos-text">마감은 회사 기준 검토 우선순위에 들어가지 않습니다</strong>(나라장터 추천등급에는 일정
        여유 20%가 있습니다). 「우리와 맞는가」(적합도)와
        「언제까지인가」(긴급도)는 다른 축입니다. 마감은 D-day 표시 · 「마감 임박순」 정렬 · 「이번 주 할 일」 ·
        촉박 배지에서만 씁니다. 점수순으로 볼 때 <strong className="text-cosmos-text">점수가 같으면 마감이 빠른 쪽</strong>이 앞에 섭니다.
      </p>
      <p>
        <strong className="text-cosmos-text">규모 적합도</strong>는 회사가 적은 혼자 맡을 수 있는 최대 사업비로 잽니다. 적지 않았으면
        권장 상한 2억으로 재고 그 사실을 근거에 적습니다 — 시스템이 회사 대신 상한을 정하지 않습니다.
        공동수급이 허용되면 큰 사업도 나눌 길이 있어 가산합니다.
      </p>
      {/*
        「우선 검토」와 「검토」를 가르는 경계 (0920 §4-B-6 · ISSUE-080).
        화면에는 라벨만 보이고 **경계 값이 어디에도 없었다** — 담당자는 68점이 왜 「검토」인지
        알 수 없었다. 숫자는 `scoreNames.PRIORITY_THRESHOLDS` 하나에서 온다
        (백엔드 `opportunity_priority.PRIORITY_HIGH/MID` 와 같아야 하는 값이다).
      */}
      <p>
        <strong className="text-cosmos-text">{PRIORITY_THRESHOLDS.high}점 이상</strong>이거나{" "}
        <strong className="text-cosmos-text">같은 출처 상위 {Math.round(PRIORITY_THRESHOLDS.topRatio * 100)}%</strong>면
        우선 검토 · <strong className="text-cosmos-text">{PRIORITY_THRESHOLDS.mid}점 이상</strong> 검토 · 그 미만
        후순위. 마감된 건과 참가 불가·관련 낮음은 점수와 무관하게 「우선 검토」로 부르지 않습니다.
      </p>
      <p>
        순위는 <strong className="text-cosmos-text">갈래 탭 안에서만</strong> 뜻이 있습니다. 나라장터(우리가 수주하는
        사업)와 기업마당(우리가 지원금을 신청하는 사업 · 수행기관 모집은 매출)은 목적이 달라 한 축에 섞어 하나의 1위를 만들지 않습니다.
        「전체」 탭을 회사 설정 정렬로 볼 때는 나라장터 1위 · 기업마당 1위 · 나라장터 2위 …처럼 출처별 순위를 번갈아 보여 줍니다. 줄 앞의 「n위」는 그 출처 안 순위입니다.
      </p>
      <p>
        계산할 수 없는 항목은 <strong className="text-cosmos-text">0점이 아니라 「미확인」</strong>으로 남기고, 나머지 항목
        배점으로 다시 나눕니다. 나라장터 공고의 수행근거는 제안요청서를 읽어야 계산되므로 목록 단계에서는 미확인으로 빠지고,
        대신 신뢰도가 낮아집니다.
      </p>
      <p>
        <strong className="text-cosmos-text">나라장터 추천등급</strong>은 1차 AI 낱말(AI·인공지능·생성형 AI·LLM 등)과 2차 업무
        낱말(교육·연수·컨설팅 등)로 후보를 고른 뒤 항목별 점수를 가중 합산한 A/B/C/D 검토 등급입니다(회사 기준 검토
        우선순위와 다른 값입니다).
      </p>
      <p>
        <strong className="text-cosmos-text">기업마당 지원 적합도</strong>는 지역·대상·기간을 규칙으로 보고, 사업영역만 아래와
        같이 방식이 갈립니다. 두 원본 점수는 축이 달라 합치지 않고 각각 그대로 둡니다.
      </p>
      {/*
        같은 목록 안에서 공고마다 판정 방식이 갈릴 수 있다. 어느 쪽으로 쟀는지 모르면 두 점수를
        같은 눈금으로 읽게 되므로, 섞인다는 사실과 확인하는 자리를 함께 적는다.
      */}
      {/* 서버가 AI 의미 매칭을 껐다고 알려 주면 「섞입니다」라고 단정하지 않는다 — 같은 화면 데이터 상태가 「AI 의미 매칭 꺼짐」이다 (OPP-08) */}
      {semanticFit === false ? (
        <p>
          <strong className="text-cosmos-text">회사 사업영역 적합도</strong>는 지금 <strong className="text-cosmos-text">낱말 기준</strong>만
          씁니다(AI 의미 매칭 꺼짐 — 같은 공고의 점수가 날마다 바뀌지 않게 고정). 공고마다 어떻게 쟀는지는 {detailSpot}에서 산정 근거 맨 위에 표시됩니다.
        </p>
      ) : (
        <p>
          <strong className="text-cosmos-text">회사 사업영역 적합도</strong>는 공고마다 판정 방식이 다를 수 있습니다. 회사 프로필과
          공고 내용을 뜻으로 견주는 <strong className="text-cosmos-text">AI 의미 매칭</strong>으로 잰 값과, 그것을 쓸 수 없어{" "}
          <strong className="text-cosmos-text">낱말 기준</strong>으로 잰 값이 한 목록에 섞입니다. 공고마다 어느 쪽인지는 {detailSpot}를
          펼치면 산정 근거 맨 위에 표시됩니다.
        </p>
      )}
      {/* 목록도 공고 필드로 판정한다(배지 · 「참가」 열 · 불가 숨김) — 「판정하지 않는다」는 낡은 말이었다 (OPP-09) */}
      <p className="text-cosmos-muted">
        목록에서는 나라장터 기본정보로 참가자격을 1차 판정(가능 · 확인 필요 · 불가)만 하고, 조항 단위 판정은 건별 분석 화면에서 합니다.
        어느 방식으로 재든 이 점수는 검토 우선순위이며 낙찰확률이 아닙니다.
      </p>
    </Popover>
  );
}

/** 출처 배지·조회 시각·수집 요약·새로고침을 한곳에 모은다. */
function DataStatusPanel({
  backendStatus,
  g2bConfigured,
  semanticFit,
  aiDraft,
  procurements,
  support,
  unified,
  loading,
  onReload,
  recollectLocks,
  keywordSearchLive,
}: {
  backendStatus: BackendStatus;
  g2bConfigured: boolean | null;
  semanticFit: boolean | null;
  aiDraft: boolean | null;
  procurements: ProcurementListResponse | null;
  support: SupportProgramListResponse | null;
  unified: UnifiedOpportunityListResponse | null;
  loading: boolean;
  onReload: () => void;
  /** 재수집 단추가 잠긴 이유 — 출처별. 열려 있으면 null (20차 §4-G). */
  recollectLocks: Record<RecollectSource, string | null>;
  /** 「찾는 낱말」 바로 찾기 문(`/health` `keyword_search_live`) — 켜져 있으면 「화면에서 받지 않는다」 풀이에 예외를 적는다(2.0.7). */
  keywordSearchLive: boolean;
}) {
  // 두 출처 중 하나라도 고정이면 목록 전체가 「지금 받아온 것」이 아니다.
  const frozen = Boolean(procurements?.frozen || support?.frozen || unified?.frozen);
  return (
    <div className="flex flex-col gap-3">
      {frozen && <FrozenNotice collectState={unified?.collect_state ?? null} keywordSearchLive={keywordSearchLive} />}
      <p className="text-[12px] leading-5 text-cosmos-secondary" data-recollect-state>
        {RECOLLECT_TERM} · {RECOLLECT_LABELS.g2b} {recollectLocks.g2b ?? "켜짐"} · {RECOLLECT_LABELS.bizinfo} {recollectLocks.bizinfo ?? "켜짐"}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {/* 「Backend」는 사업담당자의 말이 아니다. 상태만 알려 주면 된다. */}
        <Badge tone={backendStatus === "connected" ? "ok" : backendStatus === "checking" ? "muted" : "fail"} glyph>
          {backendStatus === "checking" ? "서버 연결 확인 중" : backendStatus === "connected" ? "서버 연결됨" : "서버 연결 끊김"}
        </Badge>
        <Badge tone={g2bConfigured ? "ok" : "muted"} glyph title="공공데이터포털 나라장터 OpenAPI 서비스키 설정 여부">
          나라장터 키 {g2bConfigured === null ? "-" : g2bConfigured ? "설정됨" : "없음"}
        </Badge>
        {/*
          점수를 **무엇으로 냈는가** (ISSUE-129 · 15차). 사업영역 점수는 AI 의미 유사도로
          낼 수도 있고 키워드 규칙으로 낼 수도 있는데, 둘의 값이 다르다 — 실제로 같은 공고가
          목록 85점·상세 74점으로 갈렸다. 담당자가 화면의 점수를 큐시트와 견줄 때
          「어느 쪽으로 낸 점수인지」를 알아야 한다. 모르면(null) 적지 않는다.
        */}
        {semanticFit !== null && (
          <Badge
            tone={semanticFit ? "ok" : "muted"}
            glyph
            title={
              semanticFit
                ? "사업영역 점수를 AI 의미 매칭으로 냅니다. 낱말 기준일 때와 점수가 다릅니다."
                : "사업영역 점수를 낱말 기준으로만 냅니다. 같은 공고의 점수가 날마다 바뀌지 않게 고정한 상태입니다."
            }
          >
            AI 의미 매칭 {semanticFit ? "켜짐" : "꺼짐"}
          </Badge>
        )}
        {/*
          **순위와 초안은 다른 문이다** (ISSUE-130 · 16차). 담당자 방침이 「순위와 유사도는
          규칙만, AI 는 제안서·사업계획서 초안과 제출 전 점검에만」이라, 한 화면에서 둘을
          따로 읽을 수 있어야 한다. 위 뱃지는 점수를, 이 뱃지는 초안을 말한다.
        */}
        {aiDraft !== null && (
          <Badge
            tone={aiDraft ? "ok" : "muted"}
            glyph
            title={
              aiDraft
                ? "제안서·사업계획서 초안과 제출 전 점검을 AI 가 다듬습니다. 순위와 점수는 그대로 규칙입니다."
                : "제안서·사업계획서 초안과 제출 전 점검을 규칙으로만 만듭니다. AI 를 부르지 않습니다."
            }
          >
            AI 초안 {aiDraft ? "켜짐" : "꺼짐"}
          </Badge>
        )}
      </div>

      <div className="flex flex-col gap-1 border-t border-cosmos-border pt-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-cyan">나라장터 입찰</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge kind={noticeSourceKind(procurements?.source)} fetchedAt={procurements?.fetched_at ?? null} />
          {procurements && <span className="text-[12px] text-cosmos-muted">조회 {formatDateTime(procurements.fetched_at)}</span>}
        </div>
        {procurements && (
          <p className="text-[12px] text-cosmos-secondary">
            받아 온 것 <span className="font-mono tabular-nums">{procurements.total_fetched}</span>건 → 회사 사업영역 후보{" "}
            <span className="font-mono tabular-nums">{procurements.count}</span>건 (마감 포함 · 비추천 포함 · 사전규격 뺌)
          </p>
        )}
        {/* 39차 §3-G — 같은 나라장터 수가 화면마다 다르게 보였다(머리 · 자료 상태 · 쉬운 보기 · 레이더). 무엇을 세는지 한 줄씩. */}
        <p className="text-[12px] leading-5 text-cosmos-muted" data-count-help>
          숫자 풀이 — {COUNT_HELP.header} · {COUNT_HELP.rank} · {COUNT_HELP.radar}
        </p>
        {/*
          「어떻게 받았는가」 (0920 §4-A-3). 이 줄이 없으면, 수집 방식을 고쳐도 담당자는
          여전히 옛 방식으로 받는 줄 안다 — 「공고가 1건뿐인가」라는 질문이 거기서 나왔다.
          옛 캐시에는 이 값이 없다. 그때는 지어내지 않고 적지 않는다.
        */}
        {procurements?.collected_by && (
          <p className="text-[12px] text-cosmos-muted">
            수집 방식 {procurements.collected_by}
            {typeof procurements.collect_calls === "number" && ` · 호출 ${procurements.collect_calls}회`}
          </p>
        )}
        {procurements && (
          <p className="text-[12px] text-cosmos-muted">
            추천등급 {GRADES.map((g) => `${gradeLabel(g)} ${procurements.notices.filter((n) => n.recommendation?.grade === g).length}`).join(" · ")}
          </p>
        )}
        {procurements?.error && <p className="text-[12px]" style={{ color: TONE_COLORS.warn }}>실호출 실패로 캐시 사용: {procurements.error}</p>}
      </div>

      <div className="flex flex-col gap-1 border-t border-cosmos-border pt-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.12em]" style={{ color: COSMOS_COLORS.violet }}>
          기업마당 지원사업
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge {...unifiedSourceBadge(support?.source ?? "", "bizinfo")} fetchedAt={support?.fetched_at ?? null} />
          {support?.fetched_at && <span className="text-[12px] text-cosmos-muted">조회 {formatDateTime(support.fetched_at)}</span>}
          {support && !support.bizinfo_api_configured && <Badge tone="muted">인증키 없음</Badge>}
        </div>
        {support && (
          <p className="text-[12px] text-cosmos-secondary">
            전체 수집 <span className="font-mono tabular-nums">{support.total_fetched}</span>건 → 표시{" "}
            <span className="font-mono tabular-nums">{support.count}</span>건
          </p>
        )}
        {support && !support.field_mapping_verified && (
          <p className="text-[12px] text-cosmos-muted">기업마당 자료의 항목을 아직 다 맞춰 보지 못했습니다. 금액·기간 같은 중요한 값은 공고 원문에서 한 번 더 확인하세요.</p>
        )}
        {support?.error && <p className="text-[12px] text-cosmos-muted">{support.error}</p>}
      </div>

      <div className="flex flex-col gap-1 border-t border-cosmos-border pt-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">통합 순위</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge kind="computed" label="규칙 계산" />
          {unified && <span className="text-[12px] text-cosmos-muted">조회 {formatDateTime(unified.fetched_at)}</span>}
        </div>
        {unified && <p className="text-[12px] text-cosmos-muted">회사 {unified.organization_name}</p>}
        <p className="text-[12px] text-cosmos-muted">목록에서는 나라장터 기본정보로 참가자격을 1차 판정(가능 · 확인 필요 · 불가)만 하고, 조항 단위 판정은 건별 분석 화면에서 합니다.</p>
      </div>

      <Button
        size="sm"
        variant="secondary"
        onClick={onReload}
        disabled={loading || frozen}
        title={frozen ? FROZEN_RELOAD_REASON : undefined}
        className="self-start"
      >
        {frozen ? `${VIEW_RELOAD_TERM} 잠김` : loading ? "불러오는 중…" : VIEW_RELOAD_TERM}
      </Button>
      {frozen && <p className="text-[12px] text-cosmos-muted">{FROZEN_RELOAD_REASON}.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 공통 표시 조각
// ---------------------------------------------------------------------------

/**
 * 마감/신청 종료 D-day. 날짜가 없고 원문 문구만 있으면 그 문구를 그대로 쓴다.
 *
 * 글자와 긴급도 경계는 `lib/deadline` 이 정한다 — 이 함수는 상단 바의 `DeadlineBadge` 와
 * **문자 그대로 같은 복제**였고, 시각을 모를 때만 여기서 「미정」(다른 곳은 「마감일 미정」)
 * 이라고 달리 적었다 (0920 §4-B-5 · ISSUE-078).
 */
function DeadlineText({ deadline, className = "" }: { deadline: string | null; className?: string }) {
  const nowMs = useNowMs();
  const days = nowMs === null ? null : daysUntil(deadline, nowMs);
  const tier = urgencyTierOf(days, false);
  const tone = tier === "closed" ? "text-cosmos-red" : tier === "urgent" || tier === "soon" ? "text-cosmos-amber" : "text-cosmos-text";
  return (
    <span className={`font-mono tabular-nums ${tone} ${className}`}>{dDayText({ deadline, periodKind: null, nowMs })}</span>
  );
}

/**
 * 마감 한 줄 — **등록마감이 더 이르면 두 줄이다** (0922 §4-B-8).
 *
 * 나라장터 공고에는 마감이 둘이다. 실제 데드라인은 참가자격 등록 마감 쪽인 경우가 많다 —
 * 한남대·KISTI 는 입찰마감이 9-28 인데 등록은 9-27 18:00 에 닫힌다. 담당자가 9-28 을 보고
 * 준비하면 늦는다. D-day 는 **이른 쪽** 기준이고, 뒤쪽은 회색으로 함께 적는다.
 */
function DeadlineLine({
  deadline,
  deadlineText,
  item = null,
  closed = false,
}: {
  deadline: string | null;
  deadlineText: string | null;
  /** 등록마감 · 공고문 일정 마감을 읽을 통합 행(43차 결정 1 — 이른 쪽이 앞자리). */
  item?: Pick<UnifiedOpportunity, "qualification_deadline" | "schedule_deadline" | "schedule_deadline_label" | "schedule_deadline_time_known"> | null;
  /** 이미 마감 — 앞의 용어가 「입찰 종료」라 D-day 칸(「마감」)을 붙이지 않는다. 대시보드 상단과 같은 규칙 (R27U-MSC-08). */
  closed?: boolean;
}) {
  const nowMs = useNowMs();
  const pair = pairOf(item ?? {}, deadline);
  const primary = effectiveDeadline(pair);
  if (primary) {
    const twoLines = !closed && registrationClosesFirst(pair);
    // 등록마감만 지났으면 「등록마감 마감」이 아니라 「등록마감 지남」 한 낱말 (27차 §3-F NEW).
    const registrationPassed = twoLines && nowMs !== null && (parseMs(primary) ?? Infinity) < nowMs;
    return (
      <span className="flex flex-wrap items-center justify-end gap-x-1.5 gap-y-0.5 text-right">
        <span className="flex items-center gap-1.5">
          {twoLines && (
            <span className={`text-[12px] ${registrationPassed ? "text-cosmos-red" : "text-cosmos-amber"}`} title={REGISTRATION_HELP}>
              {registrationPassed ? `${firstLabel(pair)} 지남` : firstLabel(pair)}
            </span>
          )}
          {!closed && !registrationPassed && <DeadlineText deadline={primary} />}
          <span className="text-[12px] text-cosmos-muted">{formatPairDeadline(pair, closed ? (deadline ?? primary) : primary)}</span>
        </span>
        {twoLines && deadline && (
          <span className="text-[12px] text-cosmos-muted" title="입찰서 제출 마감">
            입찰마감 {formatDeadlineStamp(deadline)}
          </span>
        )}
      </span>
    );
  }
  return <span className="text-[12px] text-cosmos-muted">{deadlineText ?? "마감일 미정"}</span>;
}

/** 적합 이유 / 확인할 사항 — backend가 준 문장만 쓴다. */
function ReasonsAndChecks({ reasons, checks }: { reasons: string[]; checks: string[] }) {
  return (
    <div className="flex flex-col gap-1.5 text-[12.5px] leading-5">
      <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-cyan">적합 이유</p>
      {reasons.length > 0 ? (
        reasons.map((r) => (
          <p key={r} className="text-cosmos-secondary">
            {r}
          </p>
        ))
      ) : (
        <p className="text-cosmos-muted">제시할 근거 문장이 없습니다</p>
      )}
      <p className="mt-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-amber">확인할 사항</p>
      {checks.length > 0 ? (
        checks.map((c) => (
          <p key={c} className="text-cosmos-secondary">
            {c}
          </p>
        ))
      ) : (
        <p className="text-cosmos-muted">규칙이 지적한 확인 사항 없음</p>
      )}
    </div>
  );
}

/**
 * 통합 우선순위 항목별 산정 근거. score=null은 「미확인」으로 쓴다.
 * 제목의 자리는 **지금 조건의 같은 출처 안** — 예전 「통합 #N」은 숨긴 불가·관련 낮음·마감까지 센 두 출처 번호라
 * 화면 어느 숫자와도 맞지 않았다 (OPP-10).
 */
function UnifiedBreakdown({ item, sourcePlace }: { item: UnifiedOpportunity; sourcePlace: { rank: number; total: number } | null }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">
        이 점수가 나온 이유
        {sourcePlace && ` · ${item.source_type === "g2b" ? "입찰" : "지원사업"} 중 ${sourcePlace.rank.toLocaleString("ko-KR")}위/${sourcePlace.total.toLocaleString("ko-KR")}건`}
      </p>
      <ul className="flex flex-col gap-1.5">
        {item.score_components.map((c) => (
          <li key={c.key} className="grid grid-cols-[6.5rem_2.5rem_3.5rem_1fr] items-baseline gap-x-2 text-[12px] sm:grid-cols-[9rem_3rem_4rem_1fr]">
            <span className="break-keep font-medium text-cosmos-text">{c.label}</span>
            <span className="font-mono tabular-nums text-cosmos-muted">{c.weight}점 중</span>
            <span className={`font-mono font-semibold tabular-nums ${c.score === null ? "text-cosmos-muted" : "text-cosmos-cyan"}`}>
              {c.score === null ? "미확인" : `${Math.round(c.score * c.weight)}점`}
            </span>
            <span className="text-cosmos-secondary">{c.reason}</span>
          </li>
        ))}
      </ul>
      <ReasonsAndChecks reasons={item.reasons} checks={item.checks} />
      <p className="text-[12px] leading-4 text-cosmos-muted">
        {CONFIDENCE_LABELS[item.confidence]} · 미확인 항목은 0점이 아니라 배점에서 빼고, 나머지 항목 배점으로 다시 나눕니다. 확률이 아닙니다.
      </p>
    </div>
  );
}

/**
 * 산정 방식의 한국어 이름. 화면에 영문 코드값을 그대로 내보내지 않는다.
 * 모르는 값이 오면 지어내지 않고 원값을 그대로 보여 준다.
 */
const METHOD_LABELS: Record<string, string> = {
  RULE: "규칙 기반",
  KEYWORD: "낱말 기준",
  EMBEDDING: "AI 의미 매칭",
  LLM: "AI 분석",
};

function methodLabel(method: string): string {
  return METHOD_LABELS[method] ?? method;
}

/** 나라장터 추천등급 원본 산정 근거. */
function ScoreBreakdown({ rec, notice }: { rec: Recommendation; notice: ProcurementNotice }) {
  // 사업영역 적합도를 무엇으로 쟀는지. backend 가 값을 주기 전에는 null 이라 이 줄이 나오지 않는다.
  const fit = semanticFitOf(notice, rec);
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">추천등급 산정 근거 (원본)</p>
      {/* 43차 M4 · N6 — 원본 추천등급은 순서에 쓰지 않는다. 위 「이 점수가 나온 이유」(회사 기준)와 배점 · 값이 달라도 정상이다 */}
      <p className="text-[12px] leading-4 text-cosmos-muted">
        나라장터 공고마다 처음 매긴 원본 등급입니다. <strong className="text-cosmos-secondary">목록 순서와 회사 기준 검토 우선순위 점수에는 쓰지 않습니다</strong> — 배점이 달라 위 「이 점수가 나온 이유」와 값이 다를 수 있습니다.
      </p>
      {fit && (
        <div className="flex flex-col gap-1">
          <Badge tone={fit.measured ? "ok" : "info"} glyph title={fit.reason ?? undefined}>
            적합도 판정: {fit.methodLabel}
            {fit.measured && fit.score !== null ? ` · ${Math.round(fit.score * 100)}점` : ""}
            {fit.measured && fit.label ? ` (${fit.label})` : ""}
          </Badge>
          {fit.reason && <p className="text-[12px] leading-4 text-cosmos-secondary">{fit.reason}</p>}
        </div>
      )}
      {rec.gate_reason && (
        <InlineAlert tone="fail" role="status">
          {/*
            0~1 값과 영문 등급이 한 문장에 함께 새어 나오던 자리다 (ISSUE-074-b·g · 0921 §4-E).
            화면에 0~1 은 내지 않고(사람이 읽는 척도가 아니다), `NO_GO` 는 백엔드에서
            **「입찰 마감이 지났다」만 뜻하므로** 사전을 거쳐 「마감」으로 적는다.
            사유는 마감만이 아니다 — 사업영역 밖(D) · 개발만(B 상한)에도 붙는다. 그 등급을 그대로 적는다(「마감」이라 적고 있었다).
          */}
          {rec.gate_reason}{" "}
          {rec.grade === "NO_GO"
            ? `점수와 무관하게 「${labelOf(GRADE_LABELS, "NO_GO")}」으로 분류했습니다.`
            : `원본 추천등급만 「${labelOf(GRADE_LABELS, rec.grade)}」에 두었습니다(목록 순서와는 따로).`}
        </InlineAlert>
      )}
      <ul className="flex flex-col gap-1.5">
        {rec.components.map((item) => (
          <li key={item.key} className="grid grid-cols-[6.5rem_2.5rem_3.5rem_1fr] items-baseline gap-x-2 text-[12px] sm:grid-cols-[8rem_3rem_3.5rem_1fr]">
            <span className="break-keep font-medium text-cosmos-text">{item.label}</span>
            <span className="font-mono tabular-nums text-cosmos-muted">{Math.round(item.weight * 100)}점 중</span>
            <span className={`font-mono font-semibold tabular-nums ${item.score === null ? "text-cosmos-muted" : "text-cosmos-cyan"}`}>
              {item.score === null ? "미확인" : `${Math.round(item.score * item.weight * 100)}점`}
            </span>
            <span className="text-cosmos-secondary">{item.reason}</span>
          </li>
        ))}
      </ul>
      <p className="text-[12px] leading-4 text-cosmos-muted">
        {rec.note} 판정 방식 {methodLabel(rec.method)}
        {rec.skipped.length > 0 ? ` · 미확인 항목은 0점이 아니라 빼고 나머지 항목 배점으로 다시 나눔: ${rec.skipped.join(", ")}` : ""}
      </p>
    </div>
  );
}

/** 기업마당 지원 적합도 원본 산정 근거. */
function SupportFitBreakdown({ view }: { view: SupportProgramView }) {
  const { support_fit } = view;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">
        지원 적합도 산정 근거 (원본) · {support_fit.label} {Math.round(support_fit.score * 100)}점
      </p>
      <ul className="flex flex-col gap-1">
        {support_fit.components.map((c) => (
          <li key={c.key} className="grid grid-cols-[6.5rem_3.5rem_1fr] items-baseline gap-x-2 text-[12px]">
            <span className="break-keep font-medium text-cosmos-text">{c.label}</span>
            <span className={`font-mono tabular-nums ${c.score === null ? "text-cosmos-muted" : "text-cosmos-cyan"}`}>
              {c.score === null ? "미확인" : Math.round(c.score * 100)}
            </span>
            <span className="text-cosmos-secondary">{c.reason}</span>
          </li>
        ))}
      </ul>
      <p className="text-[12px] leading-4 text-cosmos-muted">{support_fit.note}</p>
    </div>
  );
}

/** 원본 점수 배지 — 조달=추천등급, 지원=지원 적합도. 두 축을 합치지 않는다. */
function OriginalScoreBadge({ row }: { row: SourceRow }) {
  if (row.kind === "g2b") {
    const rec = row.notice.recommendation;
    if (!rec) return <Badge tone="muted">추천등급 {UNSCORED}</Badge>;
    return (
      <Badge
        tone={GRADE_TONE[rec.grade]}
        glyph
        title={`${GRADE_HINTS[rec.grade]} · ${RECOMMENDATION_GRADE.description} (${RECOMMENDATION_GRADE.scope})`}
      >
        {RECOMMENDATION_GRADE.label} {gradeLabel(rec.grade)} · {GRADE_HINTS[rec.grade]}
      </Badge>
    );
  }
  const fit = row.view.support_fit;
  return (
    <Badge tone={FIT_TONE[fit.label]} glyph title="기업마당 지원 적합도 — 규칙 기반이며 선정 여부를 뜻하지 않습니다">
      지원 적합도 {fit.label} · {Math.round(fit.score * 100)}점
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// 목록 카드 — 기본은 최소 정보, 보조정보는 「자세히」 안으로
// ---------------------------------------------------------------------------

/**
 * 카드와 쉬운 보기 행이 **같은 글자 · 같은 주소**로 옮겨 간다 (24차 §3-3).
 * 이미 요구사항을 뽑아 둔 공고에 「시작」이라고 적으면 처음부터 다시 하는 줄 안다.
 * 주소도 글자도 백엔드(`next_route`)가 정한다 — 레이더 상세와 같은 공고가 같은 단추 이름을 갖는다(「입찰 분석 열기」 ·
 * 「분석 계속」 · 「지원사업 신청 분석 열기」 · RDR-19). 화살표는 쓰는 곳이 한 번만 붙이므로 백엔드 글의 끝 「→」는 뗀다(RDR-18).
 * 도움말도 같은 글자로 시작해 보이는 말과 갈리지 않게 한다(OPP-29). 통합 목록 값이 없을 때만 이 화면의 말로.
 */
function rowRoute(row: Row, back = ""): { path: string; label: string; help: string } {
  const item = row.unified;
  const isG2b = row.kind === "g2b";
  const base = item?.next_route.path ?? (isG2b ? `/analysis?notice=${encodeURIComponent(row.id)}` : `/support/${encodeURIComponent(row.id)}`);
  // 2.0.6 — 지원사업 신청 분석도 `from`(지금 조건)을 싣는다 · 그 화면의 「← 사업기회」가 「전체」 · 기본 정렬 · 빈 검색으로 돌아갔다(작성 화면 `planHref` 와 같은 값)
  const path = back && base.startsWith("/support/") ? `${base}${base.includes("?") ? "&" : "?"}from=${encodeURIComponent(back)}` : base;
  const label = item?.next_route.label.replace(/\s*→\s*$/, "") || (isG2b ? "입찰 분석 열기" : "지원사업 신청 분석 열기");
  return { path, label, help: `${label} — ${isG2b ? "입찰 분석에서 이 공고를 엽니다" : "지원사업 신청 분석 화면을 엽니다"}` };
}

/**
 * 카드의 사유 줄 — 불가 사유 · 왜 맞나 · 주의 · 관련 낮음 · 열리는 조건 · 회사에 뜻하는 것 · 공고문 인용 ·
 * 대상 요건 · 요약 순서. 카드는 전부, 쉬운 보기 행은 앞 셋을 「왜 이 순위인가」로 · 나머지는 「자세히」 안에.
 * 없는 줄은 배열에 들어가지 않는다.
 */
function reasonLines(row: Row): ReactNode[] {
  const item = row.unified;
  const summary = rowSummaryLine(row);
  return [
    item?.eligibility_gate === "FAIL" && item.gate_reason && (
      // 결정 문장이라 7:1 이 필요하다 — 테두리·배경은 그대로 두고 글자만 밝힌다.
      <p key="gate" className="rounded-md border border-cosmos-red/35 bg-cosmos-red/10 px-2.5 py-2 text-[12px] leading-5 text-cosmos-red-text">
        {item.gate_reason}
      </p>
    ),
    /* 저장된 결정 한 줄(45차 M13) — 직접 넣은 공고 · 이번 주 할 일에만 있었다. 브리핑 · 엑셀과 같은 값(`decision_text`). */
    item?.decision_text && (
      <p key="decision" className="text-[12px] leading-5 text-cosmos-text" data-decision-line>
        결정: {item.decision_text}
      </p>
    ),
    /*
      「왜 맞나」·「주의」 한 줄 (0921 §4-C-3 · §4-D-1).
  
      이유가 여러 줄 붙어 있는데 담당자가 100건을 훑을 때 읽는 것은 첫 줄 하나다.
      검수자가 손으로 만든 기준 답안도 공고마다 한 줄씩 적었다 — 같은 모양으로 둔다.
      LLM 이 아니라 회사가 적어 둔 검증 역량과 공고 필드로 만든 문장이다.
    */
    item?.fit_line && (
      <p key="fit" className="text-[12px] leading-5 text-cosmos-secondary">
        <span className="text-cosmos-muted">왜 맞나 </span>
        {item.fit_line}
      </p>
    ),
    item?.caution_line && (
      <p key="caution" className="text-[12px] leading-5 text-cosmos-amber">
        <span className="opacity-80">주의 </span>
        {item.caution_line}
        {isOverCeilingCaution(item.caution_line) && (
          <>
            {" "}
            <GuideContextLink href={GUIDE_LINKS.consortium}>{GUIDE_LINK_TEXT.consortium}</GuideContextLink>
          </>
        )}
      </p>
    ),
    /*
      「관련 낮음」인 이유를 **근거 낱말과 함께** 적는다 (0922 §4-C-2).
      기본 목록에서는 접히지만 「관련 낮음 포함」을 켜면 이 줄이 보인다 — 규칙이 틀렸을 때
      담당자가 무엇 때문에 접혔는지 알아야 되돌릴 수 있다.
    */
    /* 사전규격 이음(38차 §3-D) — 본공고 행 「사전규격 n일 전 공개」. */
    item?.pre_spec_note && (
      <p key="prespec" className="text-[12px] leading-5 text-cosmos-cyan">
        {item.pre_spec_note}
      </p>
    ),
    item?.relevance_note && (
      <p key="relevance" className="text-[12px] leading-5 text-cosmos-muted">
        <span className="opacity-80">관련 낮음 </span>
        {item.relevance_note}
      </p>
    ),
    /* 무엇을 갖추면 열리는가 (0921 §4-B). 「불가」를 그냥 닫아 두지 않는다. */
    ...(() => {
      const { gain, direct } = splitUnlocks(item?.unlock_conditions ?? []);
      return [
        gain.length ? (
          <p key="unlock" className="text-[12px] leading-5 text-cosmos-cyan">
            <span className="text-cosmos-muted">{UNLOCK_HEAD}: </span>
            {gain.join(" · ")}
            {gain.includes(CONSORTIUM_UNLOCK) && (
              <>
                {" "}
                <GuideContextLink href={GUIDE_LINKS.consortium}>{GUIDE_LINK_TEXT.consortium}</GuideContextLink>
              </>
            )}
          </p>
        ) : null,
        // 나라장터 등록은 등록증으로 직접 확인할 일 — 「갖추면 가능」이 아니다(32차 §3-B-2)
        direct.length ? (
          <p key="direct" className="text-[12px] leading-5 text-cosmos-cyan">
            <span className="text-cosmos-muted">{DIRECT_CHECK_HEAD}: </span>
            {direct.join(" · ")} <GuideContextLink href={GUIDE_LINKS.register}>{GUIDE_LINK_TEXT.register}</GuideContextLink>
          </p>
        ) : null,
      ];
    })(),
    /*
      **「회사에 뜻하는 것」 한 줄** (0924 §4-A-6) — 역할 · 받는 것 · 부담 · 마감.
      기준 답안 표의 「받는 것 / 부담 / 회사 역할」 열과 같은 뜻이다.
    */
    item?.company_meaning && (
      <p key="meaning" className="text-[13px] leading-5 text-cosmos-text">
        <span className="text-cosmos-muted">우리 회사 입장에서 </span>
        <ReceiveLine text={item.company_meaning} />
      </p>
    ),
    /*
      **공고문 원문 인용** (0924 §4-A-3 · §3-14). 판정의 근거는 지어낸 문장이 아니라
      공고문에 실제로 있는 글이다. 못 읽었으면 그 사실을 적는다 — 읽은 척하지 않는다.
    */
    item?.clause_quotes?.length ? (
      <ul key="quotes" className="flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
        {item.clause_quotes.slice(0, 2).map((line) => (
          <li key={line} className="line-clamp-2">
            <span className="text-cosmos-muted">공고문 </span>
            「{line}」
          </li>
        ))}
      </ul>
    ) : item?.document_note ? (
      <p key="document" className="text-[12px] leading-5 text-cosmos-muted">{item.document_note}</p>
    ) : null,
    /* 기업마당 대상 요건은 **원문 그대로** 인용한다 — 요약하지 않는다 (0921 §4-D-1). */
    item?.requirement_sentences?.length ? (
      <ul key="requirements" className="flex flex-col gap-0.5 text-[12px] leading-5 text-cosmos-secondary">
        {item.requirement_sentences.map((line) => (
          <li key={line} className="line-clamp-2">
            <span className="text-cosmos-muted">☞ </span>
            {line}
          </li>
        ))}
      </ul>
    ) : null,
    summary && <p key="summary" className="line-clamp-2 text-[12px] leading-5 text-cosmos-muted">{summary}</p>,
  ].filter(Boolean);
}

function OpportunityRowCard({
  row,
  position,
  emphasizeTop = true,
  sortLabel,
  sourcePlace,
  sourceBadge,
  fetchedAt,
  open,
  onToggle,
  unifiedLoading = false,
  current = false,
}: {
  row: SourceRow;
  /** 지금 정렬에서의 자리. 시연용 (마감) 묶음은 순위가 아니라 null — 번호 대신 「⚑ 시연용」만 (OPP-04). */
  position: number | null;
  /** 1~3번 강조색. 두 출처를 섞은 「전체」에서는 끈다 — 하나의 1위를 만들지 않는다 (OPP-10). */
  emphasizeTop?: boolean;
  sortLabel: string;
  /** 지금 화면 조건에서 **같은 출처 안의 자리** (0925 §4-D-2). `sourcePlaces` 주석 참고. */
  sourcePlace: { rank: number; total: number } | null;
  sourceBadge: { kind: SourceKind; label?: string };
  fetchedAt: string | null;
  open: boolean;
  onToggle: () => void;
  /** 통합 목록 응답을 **아직 기다리는 중인가** (0922 §4-D-3). 임시 상태를 최종처럼 적지 않는다. */
  unifiedLoading?: boolean;
  /** 지금 보는 공고인가 — 다른 화면에서 고른 것 (27차 LNK-08). */
  current?: boolean;
}) {
  const nowMs = useNowMs();
  const openSheet = useContext(OpenSheetContext) ?? NO_SHEET;
  const rankingMethod = useRankingMethod();
  const item = row.unified;
  const isG2b = row.kind === "g2b";
  const accent = item ? TONE_COLORS[PRIORITY_TONE[item.priority_label]] : COSMOS_COLORS.slate;
  const sourceColor = isG2b ? COSMOS_COLORS.cyan : COSMOS_COLORS.violet;
  const top = emphasizeTop && position !== null && position <= 3;

  const title = isG2b ? row.notice.title : row.view.program.title;
  const agency = isG2b
    ? row.notice.agency
    : `${row.view.program.agency}${row.view.program.executing_agency ? ` · ${row.view.program.executing_agency}` : ""}`;
  const state = item?.analysis_state ?? null;
  const route = rowRoute(row, useContext(PlanBackContext));
  const externalUrl = isG2b ? row.notice.source_url : row.view.program.url;
  const detailId = `opp-detail-${row.kind}-${row.id}`;
  // 판정 배지 — 말과 색은 대시보드 「이번 주 할 일」과 같은 곳에서 온다 (0925 §4-F-3).
  const verdict = verdictOf(item?.eligibility_gate, item?.participation);

  return (
    <article
      className={`mc-panel flex flex-col gap-2 p-3 sm:px-4 ${current ? "ring-1 ring-cosmos-blue-text/70" : ""}`}
      aria-label={position === null ? `예시 공고(마감) ${title}` : `${sortLabel} ${position}번째 ${title}`}
      aria-current={current ? "true" : undefined}
      data-current-notice={current ? row.id : undefined}
    >
      {/*
        머리줄: 순위 · 판정 · 출처 · 유형 … 마감
        `data-visibility-strip` 은 `scripts/check_visibility.mjs` 가 형제 요소의
        사각형 겹침을 재는 표시다 (0925 §4-F-4·6).
      */}
      <div
        data-visibility-strip="card-head"
        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]"
      >
        {position !== null && (
          <span
            aria-hidden={!top}
            title={`${sortLabel} 기준 ${position}번째`}
            className={`flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full px-1.5 font-mono text-[12px] font-bold tabular-nums ${
              top ? "border" : "text-cosmos-muted"
            }`}
            style={top ? { color: accent, borderColor: withAlpha(accent, 40), backgroundColor: withAlpha(accent, 10) } : undefined}
          >
            {position}
          </span>
        )}
        {/*
          **판정을 첫 줄에** (0925 §4-F-3 · ISSUE-105).

          10차 카드에서 가장 밝은 줄은 모든 카드에 똑같이 붙는 「주의 …」였고, 정작
          판정은 어디에도 배지가 없었다 — 대시보드 「이번 주 할 일」에는 있는데 목록에는
          없었다. 색·말은 `verdictOf` 한 곳에서 오므로 두 화면이 어긋나지 않는다.
        */}
        {item && (
          <Badge tone={verdict.tone} title={verdict.title}>
            {verdict.label}
          </Badge>
        )}
        {current && (
          <Badge tone="info" title="다른 화면에서 고른 것 — 상단 메뉴가 이 공고를 이어 줍니다">
            {isG2b ? "지금 보는 공고" : "지금 보는 사업"}
          </Badge>
        )}
        {/* 유형(「입찰공고」 · 「지원사업」)은 출처 이름과 같은 말이라 따로 적지 않고 도움말로 둔다 (OPP-30). */}
        <span className="font-medium" style={{ color: sourceColor }} title={OPPORTUNITY_TYPE_LABELS[isG2b ? "procurement" : "support_program"]}>
          <span aria-hidden="true" className="mr-1 text-[12px]">
            {isG2b ? "●" : "◆"}
          </span>
          {SOURCE_TYPE_LABELS[isG2b ? "g2b" : "bizinfo"]}
        </span>
        {/*
          출처 «안에서의» 순위. 이것이 실제로 비교 가능한 숫자다.
          나라장터는 우리가 수주해 매출을 얻는 사업이고 기업마당은 우리가 지원금을 신청하는
          사업이라, 두 출처를 하나의 1~104위에 세우면 뜻이 없다. 맨 앞의 번호는 현재 정렬에서의
          자리이고, 이 칩이 「같은 출처 안에서 몇 번째인가」를 말한다.
        */}
        {item && sourcePlace && (
          <span
            className="shrink-0 rounded border border-cosmos-border px-1.5 py-px font-mono text-[12px] tabular-nums text-cosmos-secondary"
            title={`지금 조건의 ${isG2b ? "나라장터 입찰" : "기업마당 지원사업"} ${sourcePlace.total.toLocaleString("ko-KR")}건 중 ${sourcePlace.rank.toLocaleString("ko-KR")}번째 — 다른 출처와 비교한 순위가 아닙니다 (전체 건수는 머리줄에 있습니다)`}
          >
            {isG2b ? "입찰" : "지원사업"} {sourcePlace.rank.toLocaleString("ko-KR")}위/{sourcePlace.total.toLocaleString("ko-KR")}건
          </span>
        )}
        {/*
          시연용으로 저장해 둔 공고 (ISSUE-056).

          이 표시가 없으면 「마감인데 왜 목록에 있지?」가 된다 — 고정 공고는 마감이어도
          남겨 두기 때문이다. 발표자에게는 「이 행으로 시연한다」는 표시이기도 하다.
        */}
        {item?.pinned && (
          <span
            className="shrink-0 whitespace-nowrap rounded border border-cosmos-amber/50 bg-cosmos-amber/10 px-1.5 py-px text-[12px] text-cosmos-amber"
            title="저장된 자료가 있어 마감 뒤에도 분석 화면이 열립니다"
          >
            ⚑ 예시 공고
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {/* 용어는 lib/deadline.ts 한 곳에서 정한다 — 출처만 보고 「종료」를 고정으로 붙이면
              D-29 인 공고가 「신청 종료 D-29」로 읽힌다. */}
          {/* 45차 L3 — 값 글이 용어로 시작하면(「상시·예산 소진 시」) 용어를 한 번만 */}
          {!(displayDeadlineText(row) ?? "").startsWith(rowDeadlineTerm(row, nowMs)) && (
            <span className="text-cosmos-muted">{rowDeadlineTerm(row, nowMs)}</span>
          )}
          <DeadlineLine
            deadline={displayDeadline(row)}
            deadlineText={displayDeadlineText(row)}
            item={item ?? null}
            closed={isClosedRow(row, nowMs)}
          />
        </span>
      </div>

      {/* 본문: 제목 · 기관 · 꼬리표(접수방식 · 유형(근사) · 분류 · 파트너형 — 37차 §3-B-5) */}
      <div className="min-w-0">
        <h3 className="line-clamp-2 text-[14.5px] font-semibold leading-snug text-cosmos-text">{title}</h3>
        <p className="mt-0.5 truncate text-[12px] text-cosmos-secondary">{agency}</p>
        <div className="mt-1">
          <PracticalTags item={item} withGroup={rankingMethod !== "practical"} />
        </div>
        {/* 근거 줄 — 쉬운 보기와 같은 값(39차 §3-G · 전체 보기 카드에는 없었다). 판정에 쓰인 조항을 먼저 고른다(서버 `evidence_line`). */}
        {item?.evidence_line && (
          <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-cosmos-muted" data-evidence-line>
            {item.evidence_line}
          </p>
        )}
      </div>

      {/* 점수 한 줄 + 이유 한 줄. 하드 자격 FAIL은 점수보다 먼저 말한다. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {item && item.company_priority_score !== null ? (
          <p className="text-[12.5px] text-cosmos-secondary" title={REVIEW_PRIORITY.description}>
            {REVIEW_PRIORITY_FULL}{" "}
            <strong className="font-mono text-[15px] font-semibold tabular-nums" style={{ color: accent }}>
              {item.company_priority_score}
            </strong>
          </p>
        ) : (
          /*
           * **아직 오지 않은 것과 잴 수 없는 것을 구분한다** (0922 §4-D-3 · ISSUE-088).
           *
           * 통합 목록 응답은 1,700건을 판정하느라 2초 넘게 걸린다. 그동안 「미산정」이라고
           * 적으면 담당자는 그것을 **최종 상태**로 읽는다 — 실제로 화면이 몇 초간
           * 「미산정 · 통합 순위 없음」을 보여 주고 있었다.
           */
          <p
            className="text-[12.5px] text-cosmos-muted"
            title={
              unifiedLoading
                ? "통합 목록 응답을 기다리는 중입니다"
                : "계산할 수 있는 항목이 없어 점수를 내지 않았습니다 — 0점이 아닙니다"
            }
          >
            {REVIEW_PRIORITY_FULL} {unifiedLoading ? "계산 중…" : UNSCORED}
          </p>
        )}
        {/* 추천등급 — 대시보드 선택창·레이더·RFP 와 **같은 자리에 같은 말** (0920 §4-B 완료 조건).
            예전에는 접힌 「자세히」 안에만 있어서 행만 보면 등급을 알 수 없었다. */}
        {item && gradeOf(item) && (
          <Badge tone="info" title={`${RECOMMENDATION_GRADE.description} (${RECOMMENDATION_GRADE.scope})`}>
            {RECOMMENDATION_GRADE.label} {labelOf(GRADE_LABELS, gradeOf(item) as string)}
          </Badge>
        )}
        {/* 분석 상태 — 레이더 상세와 **같은 컴포넌트**를 쓴다 (0920 §4-B-3). */}
        <AnalysisStateBadges state={state} />
        {/*
          **신청 주체가 아닐 때의 자리** (0924 §4-A-4). 도입기업이 신청하고 공급기업이
          수행하는 구조에서는 회사가 신청 주체가 아니다 — 그것을 「불가」로 닫으면 실제로
          들어갈 수 있는 길이 화면에서 사라진다.
        */}
        {item?.participation && (
          <Badge tone="warn" title="우리 회사가 직접 신청하는 사업이 아니라 제공자로 참여하는 사업입니다">
            {item.participation}
          </Badge>
        )}
        {item && rankingMethod === "practical" && item.practical_group ? (
          // 실무 우선순위 회사는 분류 칸이 「우선 검토 · 검토」 표시를 대신한다(37차 §3-B-4) — 점수는 그대로다.
          <Badge tone={GROUP_TONE[item.practical_group] ?? "muted"} glyph title={GROUP_HELP[item.practical_group] ?? item.practical_group}>
            {item.practical_group}
          </Badge>
        ) : item ? (
          // 「불가」는 머리 판정 배지가 이미 말한다 — 여기서는 우선순위 이름만 (한 카드에 「불가」 두 번 · OPP-30).
          <Badge
            tone={PRIORITY_TONE[item.priority_label]}
            glyph
            title={item.gate_reason ?? "회사 기준 검토 우선순위 — 낙찰·선정 확률이 아닙니다"}
          >
            {item.priority_label}
          </Badge>
        ) : (
          <Badge
            tone="muted"
            glyph
            title={
              unifiedLoading
                ? "통합 목록 응답을 기다리는 중입니다"
                : "통합 순위 목록에 포함되지 않았습니다 (마감 제외·조회 실패 등)"
            }
          >
            {unifiedLoading ? "판정 계산 중…" : "판정 못 함"}
          </Badge>
        )}
      </div>
      {reasonLines(row)}

      {/* 동선 */}
      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        {route.path ? (
          <Link
            href={route.path}
            className="mc-focus inline-flex min-h-9 items-center rounded-lg bg-cosmos-blue-strong px-3 text-[12.5px] font-semibold text-white transition-[filter] hover:brightness-110"
            title={route.help}
          >
            {route.label} →
          </Link>
        ) : (
          <span className="text-[12.5px] text-cosmos-muted" title={route.help}>
            {route.label}
          </span>
        )}
        {/* 모든 입찰 행 — 분석 전이면 탭에서 「공고 분석 시작」 (28차 §3-C · 예전 /rfp 링크는 분석한 공고에만 있었다). */}
        {isG2b && (
          <button type="button" onClick={() => openSheet(row.id)} className="mc-focus rounded px-1 text-[12px] text-cosmos-cyan hover:underline">
            {OPEN_REQUIREMENT_SHEET}
          </button>
        )}
        <PlanLink row={row} className="mc-focus rounded px-1 text-[12px] text-cosmos-cyan hover:underline" />
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={detailId}
          className="mc-focus rounded px-1 text-[12px] text-cosmos-cyan hover:underline"
        >
          {open ? "자세히 닫기" : "자세히"}
        </button>
        {externalUrl && (
          <a
            href={externalUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="mc-focus ml-auto rounded px-1 text-[12px] text-cosmos-muted hover:text-cosmos-text hover:underline"
          >
            {isG2b ? "나라장터" : "공고 원문"} ↗
          </a>
        )}
      </div>

      {open && (
        <div id={detailId} className="mt-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/50 p-3">
          <RowDetail row={row} sourceBadge={sourceBadge} fetchedAt={fetchedAt} item={item} sourcePlace={sourcePlace} />
        </div>
      )}
    </article>
  );
}

/**
 * 사업계획서 작성 페이지 — 대시보드와 같은 키(`notice` · `support`) (28차 §3-D).
 * `from` = 사업기회의 지금 조건(탭 · 정렬 · 검색) — 그 페이지의 「← 사업기회로」가 같은 목록으로 돌아온다(37차 §3-E-3).
 */
function planHref(row: Row, back: string): string {
  const key = row.kind === "g2b" ? "notice" : "support";
  return `/plan?${key}=${encodeURIComponent(row.id)}${back ? `&from=${encodeURIComponent(back)}` : ""}`;
}

/** 「사업계획서 작성 →」(지원사업) · 「제안서 작성 →」(입찰 — 같은 페이지의 입찰 탭) (37차 §3-E-2). */
function PlanLink({ row, className }: { row: Row; className: string }) {
  const back = useContext(PlanBackContext);
  return (
    <Link href={planHref(row, back)} className={className} data-plan-link={row.kind}>
      {row.kind === "g2b" ? WRITE_PROPOSAL_BUTTON : WRITE_PLAN_BUTTON}
    </Link>
  );
}

/** 쉬운 보기 행 칸 — 순위 · 출처 · 사업명 · 마감 · 참가 · 검토 우선순위 (700px 이상) */
// items-center 는 ≥700px 에서만 — 좁은 폭의 세로 두 줄에 걸리면 둘째 줄이 가운데로 밀린다.
const SIMPLE_ROW_COLUMNS = "grid-cols-[96px_44px_minmax(0,1fr)_88px_84px_104px] gap-x-3 min-[700px]:items-center";

type SimpleTab = SourceTab | "review" | "sheet" | "manual" | "prepare";

const SIMPLE_TABS: { key: SimpleTab; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "g2b", label: "입찰" },
  { key: "bizinfo", label: "지원사업" },
  { key: "prepare", label: "선제준비" },
  { key: "review", label: "검토 중" },
  { key: "sheet", label: SCREEN_NAMES.rfp },
  { key: "manual", label: "직접 넣기 · 후보함" },
];

/**
 * 쉬운 보기 한 줄 행 (24차 §3-3). 행 전체가 단추 하나 — 누르면 아래로 「왜 이 순위인가」 셋 · 이동 · 공고 원문.
 * 순위는 카드의 `sourcePlace` 그대로(출처 안의 자리) — 두 출처를 이어 매기지 않는다.
 * 참가 판정은 칩이 아니라 `verdictOf` 색 글자다.
 */
/**
 * 「전체」 탭의 직접 넣은 공고 한 줄(40차 D27 · FRONT-02) — 판정 · 순위 · 근거 줄은 서버 값 그대로다. 고치기 · 공고문 올리기는
 * 「직접 넣기 · 후보함」 탭에서(이 줄은 그 탭으로 가는 길). `simple` 이면 쉬운 보기 표 칸에 맞춘다.
 */
function ManualListRow({
  row,
  sourcePlace,
  nowMs,
  simple = false,
  onOpen,
}: {
  row: ManualRow;
  sourcePlace: { rank: number; total: number } | null;
  nowMs: number | null;
  simple?: boolean;
  /** 같은 페이지 안에서 「직접 넣기」 탭으로 바꾼다(41차 FRONT-R40-03) — 없으면 주소 이동만. */
  onOpen?: (id: string) => void;
}) {
  const item = row.unified;
  const verdict = verdictOf(item.eligibility_gate, item.participation);
  const rank = sourcePlace ? `${sourcePlace.rank.toLocaleString("ko-KR")}위/${sourcePlace.total.toLocaleString("ko-KR")}` : "–";
  // 2.0.6 — D-day 는 실제 마감(참가신청 · 등록 마감이 이르면 그 날 · 이번 주 할 일 `deadlineOf` · 서버 실무순과 같은 셈) · 입찰 마감으로만 세어 입력 창 안내와 어긋났다
  const pair = pairOf(item, item.deadline);
  const primary = effectiveDeadline(pair);
  const byRegistration = pair.qualification != null && primary === pair.qualification && primary !== item.deadline;
  const links = (
    <span className="flex flex-wrap gap-x-3 text-[14px]">
      <Link
        href={`/opportunities?tab=manual&manual=${encodeURIComponent(item.id)}`}
        className="mc-focus rounded text-cosmos-cyan hover:underline"
        onClick={(event) => {
          if (!onOpen || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
          event.preventDefault();
          onOpen(item.id);
        }}
      >
        직접 넣기 탭에서 보기 →
      </Link>
      {item.detail_url && (
        <a href={item.detail_url} target="_blank" rel="noreferrer noopener" className="mc-focus rounded text-cosmos-cyan hover:underline">
          공고 원문 ↗
        </a>
      )}
    </span>
  );
  if (simple) {
    return (
      <div role="listitem" className="border-b border-cosmos-border" data-simple-row data-manual-list-row={item.id}>
        <div className={`flex w-full flex-col gap-1 px-2 py-2 min-[700px]:grid ${SIMPLE_ROW_COLUMNS}`}>
          <span className="line-clamp-2 break-keep text-[15px] font-medium leading-snug text-cosmos-text [overflow-wrap:anywhere] min-[700px]:col-start-3 min-[700px]:row-start-1">
            {item.title}
          </span>
          <span className="flex flex-wrap items-baseline gap-x-3 text-[14px] min-[700px]:contents">
            <span className="tabular-nums text-cosmos-secondary min-[700px]:col-start-1 min-[700px]:row-start-1">{rank}</span>
            <span className="text-cosmos-secondary min-[700px]:col-start-2 min-[700px]:row-start-1" title="직접 넣은 공고">직접</span>
            <span className="break-keep tabular-nums text-cosmos-secondary min-[700px]:col-start-4 min-[700px]:row-start-1">
              {primary ? (
                <>
                  {byRegistration && <span className="block text-cosmos-amber" title="입찰 마감보다 먼저 닫힙니다">{firstLabel(pair)}</span>}
                  {dDayText({ deadline: primary, periodKind: null, nowMs })}
                </>
              ) : (
                item.deadline_text ?? "마감일 미정"
              )}
            </span>
            <span className="min-[700px]:col-start-5 min-[700px]:row-start-1" style={{ color: TONE_COLORS[verdict.tone] }} title={verdict.title}>
              {verdict.label}
            </span>
            <span className="tabular-nums text-cosmos-text min-[700px]:col-start-6 min-[700px]:row-start-1" title={REVIEW_PRIORITY.description}>
              <span className="text-cosmos-secondary min-[700px]:sr-only">{REVIEW_PRIORITY.label} </span>
              {item.company_priority_score ?? <span className="text-cosmos-muted">{UNSCORED}</span>}
            </span>
          </span>
        </div>
        <div className="flex flex-col gap-1 px-2 pb-2">
          <PracticalTags item={item} withGroup size="md" />
          {links}
        </div>
      </div>
    );
  }
  return (
    <div className="mc-panel flex min-w-0 flex-col gap-1.5 p-3" data-manual-list-row={item.id}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[14px]">
        <Badge tone="muted">직접 넣음 {rank}</Badge>
        <span style={{ color: TONE_COLORS[verdict.tone] }} title={verdict.title}>{verdict.label}</span>
        {item.recruit_kind && <Badge tone="muted">{item.recruit_kind}</Badge>}
        <span className="ml-auto tabular-nums text-cosmos-secondary">
          {byRegistration && <span className="text-cosmos-amber" title="입찰 마감보다 먼저 닫힙니다">{firstLabel(pair)} </span>}
          {dDayText({ deadline: primary, periodKind: null, nowMs })}
        </span>
      </div>
      <p className="break-keep text-[15px] font-medium leading-snug text-cosmos-text [overflow-wrap:anywhere]">{item.title}</p>
      <p className="truncate text-[13px] text-cosmos-secondary">{item.agency}</p>
      {item.gate_reason && <p className="text-[13px] leading-5 text-cosmos-secondary">{item.gate_reason}</p>}
      {item.evidence_line && <p className="text-[13px] leading-5 text-cosmos-muted" data-evidence-line>{item.evidence_line}</p>}
      <PracticalTags item={item} withGroup size="md" />
      {links}
    </div>
  );
}

function SimpleOpportunityRow({
  row,
  sourcePlace,
  open,
  onToggle,
  unifiedLoading,
  current = false,
}: {
  row: SourceRow;
  sourcePlace: { rank: number; total: number } | null;
  open: boolean;
  onToggle: () => void;
  unifiedLoading: boolean;
  /** 지금 보는 공고인가 (27차 LNK-08) */
  current?: boolean;
}) {
  const openSheet = useContext(OpenSheetContext) ?? NO_SHEET;
  const item = row.unified;
  const isG2b = row.kind === "g2b";
  const title = isG2b ? row.notice.title : row.view.program.title;
  const verdict = verdictOf(item?.eligibility_gate, item?.participation);
  const deadlinePair = pairOf(item ?? {}, displayDeadline(row));
  const primaryDeadline = effectiveDeadline(deadlinePair);
  const route = rowRoute(row, useContext(PlanBackContext));
  const externalUrl = isG2b ? row.notice.source_url : row.view.program.url;
  const reasons = reasonLines(row);
  const detailId = `opp-simple-${row.kind}-${row.id}`;
  return (
    <div
      role="listitem"
      className={`border-b border-cosmos-border ${current ? "border-l-2 border-l-cosmos-blue-text" : ""}`}
      data-simple-row
      aria-current={current ? "true" : undefined}
      data-current-notice={current ? row.id : undefined}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? detailId : undefined}
        onClick={onToggle}
        className={`mc-focus flex w-full flex-col gap-1 px-2 py-2 text-left transition-colors hover:bg-cosmos-elevated/40 min-[700px]:grid ${SIMPLE_ROW_COLUMNS} ${open ? "bg-cosmos-elevated/40" : ""}`}
      >
        <span className="line-clamp-2 break-keep text-[15px] font-medium leading-snug text-cosmos-text [overflow-wrap:anywhere] min-[700px]:col-start-3 min-[700px]:row-start-1">
          {/* 「지금 보는」 표시는 파랑(정보) 한 색 — 청록은 「가능」 판정색이라 같은 줄에서 헷갈렸다(27차 §3-E 검증 G4-V5) */}
          {current && <span className="mr-1.5 text-[14px] font-semibold text-cosmos-blue-text">{isG2b ? "지금 보는 공고" : "지금 보는 사업"} ·</span>}
          {title}
        </span>
        <span className="flex flex-wrap items-baseline gap-x-3 text-[14px] min-[700px]:contents">
          <span className="tabular-nums text-cosmos-secondary min-[700px]:col-start-1 min-[700px]:row-start-1">
            {sourcePlace ? `${sourcePlace.rank.toLocaleString("ko-KR")}위/${sourcePlace.total.toLocaleString("ko-KR")}` : item?.pinned ? "예시 공고" : "–"}
          </span>
          <span className="text-cosmos-secondary min-[700px]:col-start-2 min-[700px]:row-start-1">
            {isG2b ? "입찰" : "지원"}
          </span>
          <span className="break-keep min-[700px]:col-start-4 min-[700px]:row-start-1">
            {primaryDeadline ? (
              <>
                {/* 88px 칸에 「등록마감 D-11」을 한 줄로 두면 넘쳐 겹쳤다(33차 최신화 뒤 실데이터 · 시인성 검사) — 위아래 두 줄 */}
                {registrationClosesFirst(deadlinePair) && <span className="block text-cosmos-amber" title={REGISTRATION_HELP}>{firstLabel(deadlinePair)}</span>}
                <DeadlineText deadline={primaryDeadline} />
              </>
            ) : (
              // 43차 — 88px 칸에 「마감 미상 — 개찰 MM/DD(제출 마감 아님)」 · 「공고에 마감일 없음」이 두세 줄로 접혀 한 화면 행이 줄었다(시인성 검사) — 짧게 · 전체는 풀이로
              <span className="text-cosmos-muted" title={displayDeadlineText(row) ?? undefined}>
                {row.kind === "g2b" ? "마감 미상" : displayDeadlineText(row) ?? "마감일 미정"}
              </span>
            )}
          </span>
          <span className="min-[700px]:col-start-5 min-[700px]:row-start-1" style={{ color: item ? TONE_COLORS[verdict.tone] : undefined }} title={item ? verdict.title : undefined}>
            {item ? verdict.label : <span className="text-cosmos-muted">{unifiedLoading ? "판정 계산 중…" : "판정 못 함"}</span>}
          </span>
          <span className="tabular-nums text-cosmos-text min-[700px]:col-start-6 min-[700px]:row-start-1" title={REVIEW_PRIORITY.description}>
            <span className="text-cosmos-secondary min-[700px]:sr-only">{REVIEW_PRIORITY.label} </span>
            {item && item.company_priority_score !== null ? item.company_priority_score : <span className="text-cosmos-muted">{unifiedLoading ? "계산 중…" : UNSCORED}</span>}
          </span>
        </span>
      </button>
      {open && (
        <div id={detailId} className="flex flex-col gap-2 px-2 pb-4 pt-1">
          {/* 꼬리표(37차 §3-B-5) — 쉬운 보기는 펼친 칸 맨 위에(행 높이를 늘리면 한 화면 10행 기준을 못 지켰다) · 분류 칸도 꼬리표로 */}
          <PracticalTags item={item} withGroup size="md" />
          {/* 근거 줄(38차 §3-C-2) — 「근거: 공고문 p.N 「…」(QC-xx)」 · 못 읽었으면 「공고문 아직 안 읽음」(읽은 척하지 않는다) */}
          {item?.evidence_line && (
            <p className="text-[14px] leading-6 text-cosmos-secondary" data-evidence-line>
              {item.evidence_line}
            </p>
          )}
          <p className="text-[14px] font-semibold text-cosmos-secondary">왜 이 순위인가</p>
          {reasons.length > 0 ? reasons.slice(0, 3) : <p className="text-[14px] text-cosmos-muted">적어 둔 사유가 없습니다.</p>}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            {route.path ? (
              <Link
                href={route.path}
                title={route.help}
                className="mc-focus inline-flex min-h-10 items-center rounded-lg bg-cosmos-blue-strong px-4 text-[15px] font-semibold text-white transition-[filter] hover:brightness-110"
              >
                {route.label} →
              </Link>
            ) : (
              <span className="text-[14px] text-cosmos-muted" title={route.help}>
                {route.label}
              </span>
            )}
            {/* 모든 입찰 행 — 같은 화면의 「요구사항 정리표」 탭으로 (28차 §3-C). */}
            {isG2b && (
              <button type="button" onClick={() => openSheet(row.id)} className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline">
                {OPEN_REQUIREMENT_SHEET}
              </button>
            )}
            <PlanLink row={row} className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline" />
            {externalUrl && (
              <a href={externalUrl} target="_blank" rel="noreferrer noopener" className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline">
                공고 원문 ↗
              </a>
            )}
          </div>
          {reasons.length > 3 && (
            <details className="group">
              <summary className="mc-focus w-fit cursor-pointer list-none rounded py-1 text-[14px] text-cosmos-secondary hover:text-cosmos-text">
                자세히 <span className="group-open:hidden">▸</span>
                <span className="hidden group-open:inline">▾</span>
              </summary>
              <div className="mt-2 flex flex-col gap-2">{reasons.slice(3)}</div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/** 판정 칩 기호 — 색만으로 뜻을 전하지 않게 글자 앞에 붙인다(2.3.0). */
const VERDICT_MARKS: Record<string, string> = { 가능: "✓", "확인 필요": "?", 불가: "✕", "간접 참여": "↗", 미확인: "–" };

/** D-day 칩 — 3일 이하 빨강 · 7일 이하 호박(대시보드 · 이번 주 할 일과 같은 `URGENCY_DAYS`). */
const DDAY_CHIP: Record<DdayTone, string> = {
  urgent: "border-cosmos-red/60 bg-cosmos-red/15 text-cosmos-red-text",
  soon: "border-cosmos-amber/60 bg-cosmos-amber/10 text-cosmos-amber",
  normal: "border-cosmos-border-strong text-cosmos-text",
  closed: "border-cosmos-border text-cosmos-muted",
  none: "border-cosmos-border text-cosmos-muted",
};

const CARD_CHIP = "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-[14px] font-medium leading-5";

/** 카드 세 줄 — 목록 응답 값만(lib/opportunityCard). 입찰은 사업 · 계약 · 접수, 지원사업은 대상 · 지원 · 신청. */
function cardLines(row: SourceRow): CardLine[] {
  const item = row.unified;
  if (row.kind === "g2b") {
    const { notice } = row;
    const kinds = (notice.work?.kinds ?? []).map((kind) => WORK_KIND_LABELS[kind]).filter(Boolean);
    return bidLines({
      budgetText: notice.budget !== null ? `예산 ${formatBudgetCompact(notice.budget)}` : null,
      workText: kinds.join(" · ") || null,
      awardLine: item?.award_line,
      submissionMethods: item?.submission_methods,
      briefingText: item?.briefing_at ? `설명회 ${formatDeadlineDate(item.briefing_at, { short: true })}${item.briefing_required ? "(필수)" : ""}` : null,
    });
  }
  const { program } = row.view;
  return supportLines({
    target: program.target,
    requirementSentences: program.requirement_sentences ?? item?.requirement_sentences,
    summary: program.summary ?? item?.summary,
    submissionText: item?.submission_text,
    applyMethod: program.apply_method,
  });
}

/**
 * 「접수 정보」 상자(2.3.0 · 부스터 상세의 오른쪽 상자) — 목록 응답에 이미 있는 값만. 값이 없는 줄은 만들지 않는다.
 * 나라장터 담당자 전화는 받을 때 가려 두었다(`procurement_service` — 원문 확인) — 여기서도 싣지 않는다.
 */
function ReceptionBox({ row }: { row: SourceRow }) {
  const item = row.unified;
  const facts: Array<{ label: string; value: ReactNode }> = [];
  const links: Array<{ href: string; label: string }> = [];
  if (row.kind === "g2b") {
    const { notice } = row;
    const pair = pairOf(item ?? {}, displayDeadline(row));
    if (registrationClosesFirst(pair) && pair.qualification) facts.push({ label: firstLabel(pair), value: formatDateTime(pair.qualification) });
    if (pair.bid) facts.push({ label: "입찰 마감", value: formatDateTime(pair.bid) });
    if (item?.schedule_deadline) {
      const when = item.schedule_deadline_time_known === false ? `${formatDeadlineDate(item.schedule_deadline)}${TIME_UNKNOWN_NOTE}` : formatDateTime(item.schedule_deadline);
      facts.push({ label: "공고문 일정", value: `${item.schedule_deadline_label ?? "마감"} ${when}` });
    }
    if (item?.briefing_at) facts.push({ label: "설명회", value: `${formatDateTime(item.briefing_at)}${item.briefing_required ? " (필수 — 불참하면 참가 불가)" : ""}` });
    if (item?.joint_agreement_deadline) facts.push({ label: "공동수급협정", value: formatDateTime(item.joint_agreement_deadline) });
    if (item?.opening_at) facts.push({ label: "개찰", value: `${formatDateTime(item.opening_at)} (제출 마감 아님)` });
    if (item?.submission_methods?.length) facts.push({ label: "접수 방식", value: item.submission_methods.join(" · ") });
    if (item?.award_line) facts.push({ label: "계약 방법", value: item.award_line });
    if (item?.demand_agency) facts.push({ label: "수요기관", value: item.demand_agency });
    facts.push({ label: "공고번호", value: <span className="font-mono">{notice.notice_no}</span> });
    if (notice.source_url) links.push({ href: notice.source_url, label: "나라장터 공고 원문 ↗" });
  } else {
    const { program } = row.view;
    const period =
      program.apply_start || program.apply_end
        ? `${program.apply_start ? formatDeadlineDate(program.apply_start) : "-"} ~ ${program.apply_end ? formatDeadlineDate(normalizeApplyEnd(program.apply_end)) : "-"}`
        : program.apply_period_text ?? displayDeadlineText(row);
    if (period) facts.push({ label: "접수 기간", value: period });
    if (program.apply_method?.trim()) facts.push({ label: "신청 · 서류", value: <span className="whitespace-pre-line">{program.apply_method.trim()}</span> });
    if (program.contact?.trim()) facts.push({ label: "문의처", value: program.contact.trim() });
    const agencies = [program.agency, program.executing_agency].filter((name, index, all) => name && all.indexOf(name) === index);
    if (agencies.length) facts.push({ label: "소관 · 수행", value: agencies.join(" · ") });
    if (program.region_tags?.length) facts.push({ label: "지역", value: program.region_tags.join(" · ") });
    if (program.attachments?.length) {
      facts.push({
        label: `첨부 ${program.attachments.length}`,
        value: (
          <span className="flex flex-col gap-0.5">
            {program.attachments.map((file) => (
              <a key={file.url} href={file.url} target="_blank" rel="noreferrer noopener" className="mc-focus w-fit rounded text-cosmos-cyan hover:underline [overflow-wrap:anywhere]">
                {file.name}
              </a>
            ))}
          </span>
        ),
      });
    }
    if (program.reception_url) links.push({ href: program.reception_url, label: "접수 페이지 ↗" });
    if (program.url) links.push({ href: program.url, label: "기업마당 공고 원문 ↗" });
  }
  return (
    // 카드 안에 또 테두리 상자를 두지 않는다(상자 안 상자 · hallmark 점검) — 위쪽 가는 선과 제목만
    <section aria-label="접수 정보" className="flex flex-col gap-2 border-t border-cosmos-border pt-3" data-reception-box>
      <h4 className="text-[15px] font-semibold text-cosmos-text">접수 정보</h4>
      <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[14px] leading-6">
        {facts.map((fact) => (
          <div key={fact.label} className="contents">
            <dt className="text-cosmos-muted">{fact.label}</dt>
            <dd className="min-w-0 text-cosmos-secondary [overflow-wrap:anywhere]">{fact.value}</dd>
          </div>
        ))}
      </dl>
      {links.length > 0 && (
        <span className="flex flex-wrap gap-x-4 text-[14px]">
          {links.map((link) => (
            <a key={link.href} href={link.href} target="_blank" rel="noreferrer noopener" className="mc-focus rounded text-cosmos-cyan hover:underline">
              {link.label}
            </a>
          ))}
        </span>
      )}
    </section>
  );
}

/**
 * 쉬운 보기 카드(2.3.0 · 대표 11-04 「vster 처럼 시인성 좋게」) — 한 공고가 한 덩어리.
 * 칩(출처 · D-day · 판정 · 분류) → 굵은 제목 → 기관 · 지역 · 마감 · 순위 · 점수 → 세 줄(목록 응답 값만 · 없는 줄은 뺀다).
 * 누르면 펼친다 — 꼬리표 · 근거 줄 · 접수 정보 · 「왜 이 순위인가」 · 이동(한 줄 목록의 펼침과 같은 내용 + 접수 정보).
 * 순위는 출처 안의 자리 그대로 — 두 출처를 이어 매기지 않는다.
 */
function SimpleOpportunityCard({
  row,
  sourcePlace,
  open,
  onToggle,
  unifiedLoading,
  current = false,
}: {
  row: SourceRow;
  sourcePlace: { rank: number; total: number } | null;
  open: boolean;
  onToggle: () => void;
  unifiedLoading: boolean;
  current?: boolean;
}) {
  const nowMs = useNowMs();
  const openSheet = useContext(OpenSheetContext) ?? NO_SHEET;
  const route = rowRoute(row, useContext(PlanBackContext));
  const item = row.unified;
  const isG2b = row.kind === "g2b";
  const title = isG2b ? row.notice.title : row.view.program.title;
  const verdict = verdictOf(item?.eligibility_gate, item?.participation);
  const pair = pairOf(item ?? {}, displayDeadline(row));
  const primary = effectiveDeadline(pair);
  const tone = ddayTone(primary, nowMs);
  const externalUrl = isG2b ? row.notice.source_url : row.view.program.url;
  const reasons = reasonLines(row);
  const lines = cardLines(row);
  const detailId = `opp-card-${row.kind}-${row.id}`;
  const agency = item?.agency ?? (isG2b ? row.notice.agency : row.view.program.agency);
  // 전국 사업은 지역 태그가 17개까지 붙는다 — 셋이 넘으면 「앞 둘 외 n곳」(전부는 펼친 「접수 정보」 · 원문에서)
  const regionTags = isG2b ? [] : row.view.program.region_tags ?? item?.region_tags ?? [];
  const region = isG2b ? row.notice.region : regionTags.length > 3 ? `${regionTags.slice(0, 2).join(" · ")} 외 ${regionTags.length - 2}곳` : regionTags.join(" · ") || null;
  const sourceWord = isG2b ? "입찰" : item?.recruit_kind?.startsWith("수행기관") ? "수행기관 모집" : "지원사업";
  const deadlineWord = primary ? dDayText({ deadline: primary, periodKind: null, nowMs }) : isG2b ? "마감 미상" : displayDeadlineText(row) ?? "마감일 미정";
  const rank = sourcePlace ? `${sourcePlace.rank.toLocaleString("ko-KR")}위/${sourcePlace.total.toLocaleString("ko-KR")}` : item?.pinned ? "예시 공고" : null;
  return (
    <article
      role="listitem"
      className={`rounded-xl border bg-cosmos-panel transition-colors ${current ? "border-cosmos-blue-text" : open ? "border-cosmos-border-strong" : "border-cosmos-border hover:border-cosmos-border-strong"}`}
      data-simple-row
      data-layout="card"
      aria-current={current ? "true" : undefined}
      data-current-notice={current ? row.id : undefined}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? detailId : undefined}
        onClick={onToggle}
        className="mc-focus flex w-full flex-col gap-2 rounded-xl px-4 py-3 text-left"
      >
        <span className="flex flex-wrap items-center gap-1.5">
          {current && <span className={`${CARD_CHIP} border-cosmos-blue-text/60 text-cosmos-blue-text`}>{isG2b ? "지금 보는 공고" : "지금 보는 사업"}</span>}
          {/* 테두리 칩은 급한 둘(D-day · 판정)만 — 출처 · 분류는 글자로 낮춘다(칩 더미 · hallmark 점검) */}
          <span className="text-[14px] font-medium text-cosmos-secondary">{sourceWord}</span>
          <span className={`${CARD_CHIP} font-mono tabular-nums ${DDAY_CHIP[tone]}`} title={primary ? `마감 ${formatDateTime(primary)}` : undefined}>
            {deadlineWord}
          </span>
          <span className={CARD_CHIP} style={{ color: item ? TONE_COLORS[verdict.tone] : undefined, borderColor: "currentColor" }} title={item ? verdict.title : undefined}>
            {item ? (
              <>
                <span aria-hidden="true">{VERDICT_MARKS[verdict.label] ?? ""}</span>
                {verdict.label}
              </>
            ) : (
              <span className="text-cosmos-muted">{unifiedLoading ? "판정 계산 중…" : "판정 못 함"}</span>
            )}
          </span>
          {item?.practical_group && (
            <span className="text-[14px] text-cosmos-muted" title={GROUP_HELP[item.practical_group]}>
              {item.practical_group}
            </span>
          )}
        </span>
        <span className="line-clamp-2 break-keep text-[17px] font-semibold leading-snug text-cosmos-text [overflow-wrap:anywhere]">{title}</span>
        <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[14px] text-cosmos-secondary">
          <span className="[overflow-wrap:anywhere]">{agency}</span>
          {region && <span aria-hidden="true">·</span>}
          {region && <span>{region}</span>}
          {primary && <span aria-hidden="true">·</span>}
          {primary && (
            <span className="tabular-nums">
              {/* 등록 마감이 앞서면 그 이름을 호박색으로(「등록마감 마감」처럼 겹치지 않게) */}
              {registrationClosesFirst(pair) ? (
                <span className="text-cosmos-amber" title={REGISTRATION_HELP}>
                  {firstLabel(pair)}
                </span>
              ) : (
                "마감"
              )}{" "}
              {formatDeadlineDate(primary)}
            </span>
          )}
          <span className="ml-auto flex items-baseline gap-x-3 tabular-nums">
            {rank && <span>{rank}</span>}
            <span title={`${REVIEW_PRIORITY.description} — 낙찰·선정 확률이 아닙니다`}>
              {REVIEW_PRIORITY_FULL}{" "}
              <strong className="font-semibold text-cosmos-text">
                {item && item.company_priority_score !== null ? item.company_priority_score : <span className="font-normal text-cosmos-muted">{unifiedLoading ? "계산 중…" : UNSCORED}</span>}
              </strong>
            </span>
          </span>
        </span>
        {lines.length > 0 && (
          <span className="flex flex-col gap-1 border-t border-cosmos-border pt-2" data-card-lines>
            {lines.map((line) => (
              <span key={line.label} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-2 text-[14px] leading-6">
                <span className="font-medium text-cosmos-muted">{line.label}</span>
                {/* 접힌 카드는 한 줄씩(한 화면에 카드 서너 장) · 펼치면 다 보인다 */}
                <span className={`${open ? "" : "line-clamp-1"} text-cosmos-secondary [overflow-wrap:anywhere]`}>{line.text}</span>
              </span>
            ))}
          </span>
        )}
      </button>
      {open && (
        <div id={detailId} className="flex flex-col gap-3 border-t border-cosmos-border px-4 pb-4 pt-3">
          <PracticalTags item={item} withGroup size="md" />
          {item?.evidence_line && (
            <p className="text-[14px] leading-6 text-cosmos-secondary" data-evidence-line>
              {item.evidence_line}
            </p>
          )}
          <ReceptionBox row={row} />
          {/* 2.4.0 ⑦ — 받아 둔 공고문에서 찾아 답한다(처음 펼칠 때만 원문 상태를 묻는다) */}
          <NoticeQaPanel key={row.id} itemId={row.id} kind={isG2b ? "bid" : "support"} />
          <div className="flex flex-col gap-2">
            <p className="text-[14px] font-semibold text-cosmos-secondary">왜 이 순위인가</p>
            {reasons.length > 0 ? reasons.slice(0, 3) : <p className="text-[14px] text-cosmos-muted">적어 둔 사유가 없습니다.</p>}
            {reasons.length > 3 && (
              <details className="group">
                <summary className="mc-focus w-fit cursor-pointer list-none rounded py-1 text-[14px] text-cosmos-secondary hover:text-cosmos-text">
                  자세히 <span className="group-open:hidden">▸</span>
                  <span className="hidden group-open:inline">▾</span>
                </summary>
                <div className="mt-2 flex flex-col gap-2">{reasons.slice(3)}</div>
              </details>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {route.path ? (
              <Link
                href={route.path}
                title={route.help}
                className="mc-focus inline-flex min-h-10 items-center rounded-lg bg-cosmos-blue-strong px-4 text-[15px] font-semibold text-white transition-[filter] hover:brightness-110"
              >
                {route.label} →
              </Link>
            ) : (
              <span className="text-[14px] text-cosmos-muted" title={route.help}>
                {route.label}
              </span>
            )}
            {isG2b && (
              <button type="button" onClick={() => openSheet(row.id)} className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline">
                {OPEN_REQUIREMENT_SHEET}
              </button>
            )}
            <PlanLink row={row} className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline" />
            {externalUrl && (
              <a href={externalUrl} target="_blank" rel="noreferrer noopener" className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline">
                공고 원문 ↗
              </a>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

/** 기본 화면에서 뺀 보조정보를 전부 여기에 둔다 — 원본 점수·출처·예산·지역·키워드·산정 근거. */
function RowDetail({
  row,
  sourceBadge,
  fetchedAt,
  item,
  sourcePlace,
}: {
  row: SourceRow;
  sourceBadge: { kind: SourceKind; label?: string };
  fetchedAt: string | null;
  /** 통합 목록 항목 — 자격 판정이 여기 있다. 없으면 「미판정」이다. */
  item: UnifiedOpportunity | null;
  sourcePlace: { rank: number; total: number } | null;
}) {
  const isG2b = row.kind === "g2b";
  const budget = rowBudget(row);
  const facts: Array<{ label: string; value: ReactNode }> = [];

  if (isG2b) {
    const notice = row.notice;
    const attachments = noticeAttachments(notice);
    const keywords = notice.candidate ? [...notice.candidate.matched_ai_keywords, ...notice.candidate.matched_work_keywords] : [];
    facts.push(
      { label: "예산", value: <span className="font-mono tabular-nums">{formatBudgetCompact(notice.budget)}</span> },
      { label: "지역", value: notice.region ?? "제한 없음/확인 필요" },
      { label: "게시일", value: formatDateTime(notice.published_at) },
      {
        label: "공고번호",
        value: (
          <span className="font-mono text-[12px]">
            {notice.notice_no}
          </span>
        ),
      },
      ...(attachments.length > 0
        ? [
            {
              // 공고 상세와 **같은 부품** (20차 §4-E-3) — 원본(나라장터) 주소로만 내려받는다.
              label: `첨부 ${attachments.length}`,
              value: (
                <AttachmentLinks
                  compact
                  items={attachments.map((file, index) => ({ key: `${index}:${file.url || file.name}`, ...attachmentLinkOf(file) }))}
                />
              ),
            },
          ]
        : []),
      {
        label: "낱말 관련도",
        value: notice.candidate ? (
          <span className="flex flex-wrap items-center gap-1.5">
            <Badge
              color={TIER_COLOR[notice.candidate.tier]}
              title={`${TIER_LABEL[notice.candidate.tier]} · 판정 ${notice.candidate.method === "KEYWORD" ? "낱말 기준" : notice.candidate.method}`}
            >
              {TIER_SHORT[notice.candidate.tier]}
            </Badge>
            {keywords.length > 0 && <span className="text-[12px] text-cosmos-muted">{keywords.join(", ")}</span>}
          </span>
        ) : (
          "낱말 판정 없음"
        ),
      },
      {
        label: "참가자격",
        // 실제 판정이 있으면 그것을 적는다. 고정 문구 「미판정」은 자격을 이미 판정한
        // 공고에도 그대로 붙어 있었다 (ISSUE-076-c).
        value: item?.eligibility_gate ? (
          <span className={item.eligibility_gate === "FAIL" ? "text-cosmos-red" : "text-cosmos-secondary"}>
            {ELIGIBILITY_GATE_LABELS[item.eligibility_gate] ?? "미확인"}
            {item.gate_reason ? ` · ${item.gate_reason}` : ""}
          </span>
        ) : (
          <span className="text-cosmos-muted">미판정 · 입찰 분석 화면에서 실행</span>
        ),
      },
    );
  } else {
    const { program } = row.view;
    facts.push(
      {
        label: "지원 규모",
        value: budget === null ? <span className="text-cosmos-muted">지원 규모 미확인</span> : <span className="font-mono tabular-nums">{formatBudgetCompact(budget)}</span>,
      },
      {
        // ISO 원문(「2026-09-01 ~ 2026-09-30」)과 「- ~ -」 대신 다른 자리와 같은 「2026. 9. 30.」 · 원문 문구 (OPP-31).
        label: "신청기간",
        value:
          program.apply_start || program.apply_end
            ? `${program.apply_start ? formatDeadlineDate(program.apply_start) : "-"} ~ ${program.apply_end ? formatDeadlineDate(normalizeApplyEnd(program.apply_end)) : "-"}`
            : displayDeadlineText(row),
      },
      { label: "지원 대상", value: program.target ?? "원문 확인 필요" },
      {
        label: "지원 분야",
        value: program.category ? `${program.category}${program.subcategory ? ` / ${program.subcategory}` : ""}` : "원문 확인 필요",
      },
      { label: "등록일", value: program.created_at ? formatDateTime(program.created_at) : "-" },
    );
  }
  // 실무 우선순위 값 (37차 §3-B-1) — 설명회는 날짜만(필수 참석인지는 공고문) · 값이 없으면 줄을 만들지 않는다(「없음」으로 단정하지 않는다).
  if (item?.submission_methods?.length) {
    facts.push({
      label: "접수방식",
      value: `${item.submission_methods.join(" · ")}${item.submission_text ? ` — 원문 「${item.submission_text}」` : ""}`,
    });
  }
  if (item?.recruit_kind) facts.push({ label: "모집 성격", value: item.recruit_kind });
  // 43차 H6 · M1 — 공고문 일정표 마감 · 필수 설명회 · 개찰(제출 마감 아님) · 변경공고 날짜
  if (item?.schedule_deadline) {
    // 44차 M3 — 날짜만 있던 줄은 23:59 를 적지 않는다
    const when = item.schedule_deadline_time_known === false ? `${formatDeadlineDate(item.schedule_deadline)}${TIME_UNKNOWN_NOTE}` : formatDateTime(item.schedule_deadline);
    facts.push({ label: "공고문 일정", value: `${item.schedule_deadline_label ?? "마감"} ${when}` });
  }
  if (item?.briefing_at) {
    facts.push({
      label: "설명회",
      value: `${formatDateTime(item.briefing_at)} ${item.briefing_required ? "(필수 — 불참하면 참가 불가)" : "(필수 참석인지는 공고문에서)"}`,
    });
  }
  if (!item?.deadline && item?.opening_at) facts.push({ label: "개찰", value: `${formatDateTime(item.opening_at)} (제출 마감 아님)` });
  if (item?.amended_at) facts.push({ label: "변경공고", value: formatDateTime(item.amended_at) });
  if (item?.joint_agreement_deadline) facts.push({ label: "공동수급협정 마감", value: formatDateTime(item.joint_agreement_deadline) });
  if (item?.practical_group) {
    facts.push({ label: "분류", value: `${item.practical_group} — ${GROUP_HELP[item.practical_group] ?? ""}` });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <OriginalScoreBadge row={row} />
        <SourceBadge {...sourceBadge} fetchedAt={fetchedAt} />
      </div>

      <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-[12px] sm:grid-cols-[6.5rem_1fr]">
        {facts.map((f) => (
          <div key={f.label} className="contents">
            <dt className="text-cosmos-muted">{f.label}</dt>
            <dd className="min-w-0 text-cosmos-secondary">{f.value}</dd>
          </div>
        ))}
      </dl>

      {!isG2b && row.view.program.summary && (
        <p className="text-[12px] leading-5 text-cosmos-secondary">{row.view.program.summary}</p>
      )}

      <div className="flex flex-col gap-4 border-t border-cosmos-border pt-3 lg:flex-row lg:gap-6">
        <div className="min-w-0 flex-1">
          {row.unified ? (
            <UnifiedBreakdown item={row.unified} sourcePlace={sourcePlace} />
          ) : (
            <p className="text-[12px] text-cosmos-muted">통합 순위 목록에 포함되지 않아 회사 기준 우선순위 근거가 없습니다 (마감 제외·조회 실패 등).</p>
          )}
        </div>
        <div className="min-w-0 flex-1">
          {isG2b ? row.notice.recommendation && <ScoreBreakdown rec={row.notice.recommendation} notice={row.notice} /> : <SupportFitBreakdown view={row.view} />}
        </div>
      </div>

      {/* 2.4.0 ⑦ — 쉬운 보기 카드 펼침과 같은 칸 */}
      <div className="border-t border-cosmos-border pt-3">
        <NoticeQaPanel key={row.id} itemId={row.id} kind={isG2b ? "bid" : "support"} />
      </div>
    </div>
  );
}
