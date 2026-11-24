/**
 * 「공고 직접 넣기」 양식 도우미 (38차 §3-E). 서버가 다시 검사한다 — 여기서는 먼저 알려 주기만 한다.
 */
import type { ManualNotice, ManualNoticeInput, RecruitChoice, SourceLayer, SubmitMethod } from "@/types/manual";

export interface ManualFormState {
  url: string;
  title: string;
  agency: string;
  /** `<input type="datetime-local">` 값(YYYY-MM-DDTHH:MM · KST로 읽는다) */
  deadline: string;
  recruit: RecruitChoice | "";
  publishedOn: string;
  methods: SubmitMethod[];
  budgetText: string;
  regionLimit: string;
  /** 지역 제한을 「그 밖 — 직접 적기」로 골랐나(39차 MANUAL-01 — 고르기 + 직접 적기). */
  regionCustom: boolean;
  briefing: string;
  joint: string;
  layer: SourceLayer | "";
  bodyText: string;
  inboxId: string | null;
  /** 43차 Q20 — 마감 「상시 · 미정」 · 참가신청 · 등록 · 협정 마감(datetime-local) */
  deadlineOpen: boolean;
  applyDeadline: string;
  /** 43차 Q18 — 사람이 본업으로 확인(낱말 규칙으로 접지 않음) */
  coreConfirmed: boolean;
}

export const EMPTY_FORM: ManualFormState = {
  url: "",
  title: "",
  agency: "",
  deadline: "",
  recruit: "",
  publishedOn: "",
  methods: [],
  budgetText: "",
  regionLimit: "",
  regionCustom: false,
  briefing: "",
  joint: "",
  layer: "",
  bodyText: "",
  inboxId: null,
  deadlineOpen: false,
  applyDeadline: "",
  coreConfirmed: false,
};

export const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;

/**
 * 지역 제한 고르기(39차 MANUAL-01). 「지역 제한 없음」을 칸에 그대로 적으면 지역 이름으로 읽혀 「불가」가 됐다 — 고르게 한다.
 * 그 밖은 직접 적는다(「서울 제외」처럼 빼는 지역은 서버가 「확인 필요」로 둔다).
 */
export const REGION_PRESETS: readonly string[] = ["제한 없음", "광주", "전남", "광주 · 전남"];
export const REGION_CUSTOM = "__custom__";

/** 고르기 칸의 값 — 미리 정한 것 · 직접 적기 · 비움. */
export function regionChoiceOf(state: Pick<ManualFormState, "regionLimit" | "regionCustom">): string {
  if (state.regionCustom) return REGION_CUSTOM;
  if (REGION_PRESETS.includes(state.regionLimit)) return state.regionLimit;
  return state.regionLimit ? REGION_CUSTOM : "";
}

/** 고르기를 바꾸면 — 직접 적기로 가면 미리 정한 글을 지우고 칸을 연다. */
export function chooseRegion<T extends Pick<ManualFormState, "regionLimit" | "regionCustom">>(state: T, value: string): T {
  if (value === REGION_CUSTOM) return { ...state, regionCustom: true, regionLimit: REGION_PRESETS.includes(state.regionLimit) ? "" : state.regionLimit };
  return { ...state, regionCustom: false, regionLimit: value };
}

/**
 * 「오늘 열어 본 곳」 한 줄 검사 — 서버(`WatchSiteInput`)와 같은 규칙(39차 MANUAL-07 · FRONTEND-02): 이름 1~120자 ·
 * 주소는 비우거나 https://점 있는 호스트 · 빈칸 없음 · 메모 300자. 문제가 없으면 null.
 */
export function watchSiteProblem(site: { name: string; url?: string | null; memo?: string | null }): string | null {
  const name = site.name.trim();
  if (!name) return "이름을 적어 주세요";
  if (name.length > 120) return `이름은 120자까지(지금 ${name.length}자)`;
  const url = (site.url ?? "").trim();
  if (url && (!/^https:\/\/[^\s/?#]+\.[^\s/?#]+/i.test(url) || /\s/.test(url))) return "주소는 https:// 로 시작하고 점(.)이 있는 공식 주소만 받습니다(빈칸 없이)";
  if ((site.memo ?? "").trim().length > 300) return "메모는 300자까지";
  return null;
}

/** 공고문을 올린 뒤 한 줄 — 조항을 못 찾았으면 그렇게 말한다(39차 FRONTEND-03 · 읽은 척하지 않는다). */
export function uploadMessage(document: { status: string; note?: string | null } | null | undefined): string {
  if (document?.status === "ok") return "공고문에서 자격 조항을 읽어 판정했습니다.";
  const why = document?.note ? `(${document.note})` : "";
  return `공고문은 올렸지만 자격 조항을 찾지 못했습니다${why} — 판정은 「공고문 아직 안 읽음」 그대로입니다.`;
}
export const DOCUMENT_ACCEPT = ".pdf,.hwp,.hwpx,.docx";

/** `2026-10-28T16:00` → `2026-10-28T16:00:00+09:00` (KST). 꼴이 아니면 null. */
export function kstIso(local: string): string | null {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local) ? `${local}:00+09:00` : null;
}

/** ISO 시각 → `<input type="datetime-local">` 값(KST). */
export function toLocalInput(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const kst = new Date(ms + 9 * 3600 * 1000);
  return kst.toISOString().slice(0, 16);
}

/** 빈칸 · 꼴 오류를 칸마다 한 줄씩. 비면 보낼 수 있다. */
export function formErrors(state: ManualFormState): Partial<Record<keyof ManualFormState, string>> {
  const errors: Partial<Record<keyof ManualFormState, string>> = {};
  const url = state.url.trim();
  if (!url) errors.url = "공식 원문 주소를 적어 주세요";
  else if (!/^https:\/\/[^\s/?#]+\.[^\s/?#]+/i.test(url) || /\s/.test(url)) errors.url = "https:// 로 시작하는 공식 주소만 받습니다";
  if (!state.title.trim()) errors.title = "공고명을 적어 주세요";
  if (!state.agency.trim()) errors.agency = "기관을 적어 주세요";
  if (!state.deadlineOpen && !kstIso(state.deadline)) errors.deadline = "마감 날짜와 시각을 고르거나 「상시 · 미정」을 고르세요";
  if (state.applyDeadline && !kstIso(state.applyDeadline)) errors.applyDeadline = "참가신청 · 등록 마감의 날짜와 시각을 골라 주세요";
  if (!state.recruit) errors.recruit = "누구를 모집하는지 골라 주세요(입찰 · 수행기관 모집 · 지원금 받기)";
  return errors;
}

const blank = (value: string) => (value.trim() ? value.trim() : null);

export function toInput(state: ManualFormState): ManualNoticeInput {
  return {
    url: state.url.trim(),
    title: state.title.trim(),
    agency: state.agency.trim(),
    deadline: state.deadlineOpen ? null : kstIso(state.deadline) ?? "",
    deadline_open: state.deadlineOpen,
    apply_deadline: state.applyDeadline ? kstIso(state.applyDeadline) : null,
    core_confirmed: state.coreConfirmed,
    recruit: state.recruit as RecruitChoice,
    published_on: blank(state.publishedOn),
    methods: state.methods,
    budget_text: blank(state.budgetText),
    region_limit: blank(state.regionLimit),
    briefing: blank(state.briefing),
    joint: blank(state.joint),
    layer: state.layer || null,
    body_text: blank(state.bodyText),
    inbox_id: state.inboxId,
  };
}

export function fromNotice(notice: ManualNotice): ManualFormState {
  return {
    url: notice.url,
    title: notice.title,
    agency: notice.agency,
    deadline: notice.deadline ? toLocalInput(notice.deadline) : "",
    recruit: notice.recruit,
    publishedOn: notice.published_on ?? "",
    methods: notice.methods ?? [],
    budgetText: notice.budget_text ?? "",
    regionLimit: notice.region_limit ?? "",
    regionCustom: Boolean(notice.region_limit) && !REGION_PRESETS.includes(notice.region_limit ?? ""),
    briefing: notice.briefing ?? "",
    joint: notice.joint ?? "",
    layer: notice.layer ?? "",
    bodyText: notice.body_text ?? "",
    inboxId: null,
    deadlineOpen: Boolean(notice.deadline_open),
    applyDeadline: notice.apply_deadline ? toLocalInput(notice.apply_deadline) : "",
    coreConfirmed: Boolean(notice.core_confirmed),
  };
}

/** 공고문 파일 — 형식 · 크기를 먼저 본다(서버도 본다). 문제가 없으면 null. */
export function documentProblem(file: Pick<File, "name" | "size">): string | null {
  const suffix = file.name.toLowerCase().match(/\.[a-z0-9]+$/)?.[0] ?? "";
  if (!DOCUMENT_ACCEPT.split(",").includes(suffix)) return "공고문은 pdf · hwp · hwpx · docx 파일만 받습니다";
  if (file.size === 0) return "빈 파일입니다";
  if (file.size > MAX_DOCUMENT_BYTES) return "공고문 파일은 20MB 까지 받습니다";
  return null;
}
