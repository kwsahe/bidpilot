/**
 * 공고 직접 넣기 · 확인 전 후보함 · 오늘 열어 본 곳 (backend/app/schemas/manual_notice.py · 38차 §3-E).
 *
 * 셋 모두 사람이 가져온 글이다 — 서버가 https 만 받고 길이를 막는다. 서버는 사람이 준 주소를 열지 않는다.
 */

/** 모집 대상 — **기본값 없음**(수혜 ≠ 수행). 입찰 · 수행기관 모집은 매출, 수혜는 지원금. */
export type RecruitChoice = "bid" | "operator" | "benefit";

export const RECRUIT_CHOICES: Array<{ key: RecruitChoice; label: string; help: string }> = [
  { key: "bid", label: "입찰(매출)", help: "기관이 일을 맡길 회사를 고르는 입찰 — 우리가 일하고 돈을 받습니다" },
  { key: "operator", label: "수행기관 모집(매출)", help: "기관 사업을 대신 운영할 회사를 모집 — 우리가 운영하고 돈을 받습니다" },
  { key: "benefit", label: "지원금 받기(수혜)", help: "우리 회사가 지원금 · 바우처를 받는 사업 — 매출이 아닙니다" },
];

export const SUBMIT_METHODS = ["이메일", "PMS/기관시스템", "온라인폼", "IRIS", "나라장터", "방문/우편", "직찰 · 대학 자체 전자입찰"] as const;
export type SubmitMethod = (typeof SUBMIT_METHODS)[number];

export const SOURCE_LAYERS = ["P1", "P2", "P3", "IRIS", "HRD"] as const;
export type SourceLayer = (typeof SOURCE_LAYERS)[number];

export const SOURCE_LAYER_HELP: Record<SourceLayer, string> = {
  P1: "기관 홈페이지 자체 공고",
  P2: "대학 · 산학협력단 자체",
  P3: "나라장터 · 기업마당에도 있는 것",
  IRIS: "IRIS(연구 사업)",
  HRD: "직업훈련(HRD)",
};

export interface ManualNoticeInput {
  url: string;
  title: string;
  agency: string;
  /** ISO 8601 (KST 오프셋 포함) — 「상시 · 미정」(`deadline_open`)이면 null(43차 Q20). */
  deadline: string | null;
  recruit: RecruitChoice;
  deadline_open?: boolean;
  /** 참가신청 · 등록 · 협정 마감(43차 Q20). */
  apply_deadline?: string | null;
  /** 사람이 본업으로 확인(43차 Q18 · 낱말 규칙으로 접지 않음). */
  core_confirmed?: boolean;
  published_on?: string | null;
  methods?: SubmitMethod[];
  budget_text?: string | null;
  region_limit?: string | null;
  briefing?: string | null;
  joint?: string | null;
  layer?: SourceLayer | null;
  body_text?: string | null;
  inbox_id?: string | null;
  /** 「공고명이 같은 나라장터 공고가 있음」을 보고도 새로 넣기(43차 H4). */
  confirm_new?: boolean;
}

export interface ManualDocument {
  file_name: string;
  size_bytes: number;
  sha256: string;
  format: string | null;
  /** 「ok」(조항 읽음) · 「no_section」 · 「image」 · 「error」 */
  status: string;
  note: string | null;
  uploaded_at: string;
}

export interface ManualNotice extends ManualNoticeInput {
  id: string;
  organization_id: string;
  created_at: string;
  created_by: string | null;
  updated_at: string;
  /** 마지막으로 고친 사람(43차 M25). 옛 저장본에는 없다. */
  updated_by?: string | null;
  /** 화면용 이름(45차 M11 — 서버가 계정 표시 이름으로 채움 · 계정이 아니면 아이디 그대로) */
  created_by_name?: string | null;
  updated_by_name?: string | null;
  document: ManualDocument | null;
  /** 「원문 확인함 — 가능으로」(44차 M6) — 누가 · 언제 · 이유. 없으면 null(자동으로는 「가능」이 아님). */
  human_pass?: { by: string; at: string; reason: string; recorded_by?: string | null } | null;
}

export interface ManualSaveResult {
  notice: ManualNotice | null;
  /** 저장본에 이미 있는 공고(나라장터 · 기업마당 · 같은 주소로 넣은 공고)면 그 id — 새로 만들지 않았다. */
  duplicate_of: string | null;
  duplicate_reason: string | null;
  /** 공고명만 같은 「같은 공고일 수 있음」(43차 H4) — 「그래도 새로 넣기」를 고를 수 있다. */
  maybe_duplicate?: boolean;
}

export interface InboxEntry {
  id: string;
  url: string;
  title: string | null;
  agency: string | null;
  date_text: string | null;
  /** 붙여 넣은 표의 공고일 글(43차 M15). */
  published_text?: string | null;
  /** GPT 표의 판단 · 제외 사유(43차 Q19). */
  gpt_note?: string | null;
  existing_id: string | null;
  /** 공고명만 같은 공고(44차 TEAM-R36-05) — 「같은 공고일 수 있음 →」과 「정식으로 넣기」를 함께. 옛 응답에는 없다. */
  maybe_existing_id?: string | null;
  status: "pending" | "added" | "discarded";
  discard_reason: string | null;
  manual_id: string | null;
  line_no: number;
  created_at: string;
}

export interface InboxPasteResult {
  /** 미리 보기였나(저장하지 않음 · 43차 N19). */
  preview?: boolean;
  /** 300줄을 넘었을 때 다시 붙여 넣을 첫 줄 번호 · 그 글(43차 SOURCE-15). */
  first_unread_line?: number | null;
  first_unread_text?: string | null;
  added: number;
  already_in_inbox: number;
  existing: number;
  /** 공고명만 같은 공고가 있는 줄(따로 셈 · 44차 TEAM-R36-05). 옛 응답에는 없다. */
  maybe_existing?: number;
  lines_without_link: number;
  rejected: Array<{ line_no: number; reason: string }>;
  truncated_lines: number;
  entries: InboxEntry[];
  /** 확인 전 후보가 상한(500)이라 받지 못한 줄 수(39차 MANUAL-05 — 오래된 줄을 말없이 지우지 않는다). 옛 응답에는 없다. */
  refused_full?: number;
}

export interface WatchSite {
  id: string;
  name: string;
  url: string | null;
  layer: string | null;
  memo: string | null;
  last_opened_at: string | null;
  /** 마지막으로 연 사람(43차 TEAM-05). 옛 저장본에는 없다. */
  last_opened_by?: string | null;
  last_opened_by_name?: string | null;
}

export interface WatchSiteInput {
  id?: string | null;
  name: string;
  url?: string | null;
  layer?: string | null;
  memo?: string | null;
}

/** 붙여 넣기 상한 — 서버(`MAX_PASTE_BYTES`)와 같은 값. 화면이 먼저 알려 준다. */
export const MAX_PASTE_CHARS = 200 * 1024;
