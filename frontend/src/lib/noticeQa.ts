/**
 * 공고문에 질문하기 (판 2.4.0 · 대표 11-04 「2단계」 ⑦) — 패널(`components/ui/NoticeQaPanel`)이 쓰는 타입 · 글.
 *
 * 받아 둔 공고문 원문에서 찾아 답하고, 답 문장마다 원문 쪽 번호와 인용을 붙인다(서버 `notice_qa_service`).
 * 판단 · 글은 여기 한 곳에 두고 시험한다(`tests/noticeQa.test.ts`) — 부품은 그리기만 한다.
 */

/** 출처 — 입찰(나라장터) · 지원사업(기업마당) · 직접 넣은 공고. */
export type NoticeQaKind = "bid" | "support" | "manual";
export type NoticeQaRole = "rfp" | "notice" | "support" | "annex" | "manual";
export type NoticeQaStatus = "answered" | "not_found" | "search_only" | "no_source";

export interface NoticeQaDocument {
  name: string;
  role: NoticeQaRole;
  pages: number;
  page_is_approximate: boolean;
}

/** 패널을 열 때 받는 원문 상태(읽기만). */
export interface NoticeQaState {
  item_id: string;
  documents: NoticeQaDocument[];
  available: boolean;
  warning: string | null;
  ai_ready: boolean;
  ai_note: string | null;
  used_today: number;
  daily_limit: number;
}

export interface NoticeQaCitation {
  document: string;
  page: number;
  page_is_approximate: boolean;
  quote: string;
}

export interface NoticeQaLine {
  text: string;
  citations: NoticeQaCitation[];
}

export interface NoticeQaMatch {
  document: string;
  page: number;
  page_is_approximate: boolean;
  text: string;
}

/** 질문 하나의 답 — 저장하지 않는다(이번 열람 동안 패널 안에서만). */
export interface NoticeQaAnswer {
  status: NoticeQaStatus;
  lines: NoticeQaLine[];
  dropped: number;
  matches: NoticeQaMatch[];
  note: string | null;
  documents: NoticeQaDocument[];
  pages_sent: number;
  pages_total: number;
  used_today: number;
  daily_limit: number;
}

export const NOTICE_QA_TITLE = "공고문에 질문하기";
export const NOTICE_QA_INTRO = "받아 둔 공고문 원문에서 찾아 답합니다 · 답마다 원문 쪽을 붙입니다";
export const NOTICE_QA_SEND_SCOPE = "AI 에 보내는 것 — 이 공고의 원문과 질문만(회사 자료는 보내지 않음)";
export const NOTICE_QA_ANSWER_HEAD = "AI 답 — 원문 근거를 꼭 확인하세요";
export const NOTICE_QA_MATCH_HEAD = "원문에서 낱말이 맞는 줄";
export const NOTICE_QA_NOT_FOUND = "공고문에서 답을 찾지 못했습니다";
export const NOTICE_QA_NO_MATCH = "낱말이 맞는 줄도 없습니다 — 다른 낱말로 물어 보세요";
export const NOTICE_QA_TOO_SHORT = "질문을 2자 이상 적어 주세요";
export const NOTICE_QA_CUT =
  "답을 받기 전에 연결이 끊겼습니다 — 서버는 아직 찾는 중일 수 있습니다. 질문 · 답은 저장하지 않으니 2분쯤 뒤 다시 물어 주세요";
/** 401 — 공통 문장(「저장하지 못했습니다 — …」)은 저장하지 않는 이 칸에 맞지 않는다(11-04 검토). */
export const NOTICE_QA_SESSION =
  "세션이 끝났습니다 — 새 탭에서 다시 로그인한 뒤 이 화면으로 돌아와 다시 물어 주세요(쓰던 질문은 칸에 그대로 있습니다)";
/** 답을 기다리는 동안 — 카드를 접거나 다른 공고를 열면 이 칸이 사라진다(답도 함께 · 11-04 검토). */
export const NOTICE_QA_KEEP_OPEN = "답이 올 때까지 이 칸을 접거나 다른 공고를 열지 마세요 — 답이 사라집니다";
export const NOTICE_QA_MAX_CHARS = 300;

/** 쪽 표기 — 「입찰공고문 3쪽」 · 한글 · 워드 원본은 쪽이 대략이라 「제안요청서 약 17쪽」. */
export function citationLabel(document: string, page: number, approx: boolean): string {
  return `${document} ${approx ? "약 " : ""}${page}쪽`;
}

/** 「읽을 원문: 입찰공고문 7쪽 · 제안요청서 약 35쪽」 */
export function documentsLine(documents: NoticeQaDocument[]): string {
  return `읽을 원문: ${documents.map((d) => citationLabel(d.name, d.pages, d.page_is_approximate)).join(" · ")}`;
}

/** AI 줄 — 켜졌으면 오늘 쓴 횟수, 꺼졌거나 다 썼으면 사유와 「낱말 찾기」. */
export function aiLine(state: Pick<NoticeQaState, "ai_ready" | "ai_note" | "used_today" | "daily_limit">): string {
  if (state.ai_ready && state.used_today >= state.daily_limit) {
    return `오늘 AI 답 ${state.daily_limit}번을 다 썼습니다 — 원문에서 낱말이 맞는 줄을 찾습니다`;
  }
  if (state.ai_ready) return `AI(Claude)로 답합니다 · 오늘 ${state.used_today}/${state.daily_limit}번`;
  return `${state.ai_note ?? "AI 를 쓸 수 없습니다"} — 원문에서 낱말이 맞는 줄을 찾습니다`;
}

/** 묻기 단추 글 — AI 를 못 쓰면 무엇을 하는지 그대로. */
export function askLabel(state: Pick<NoticeQaState, "ai_ready" | "used_today" | "daily_limit"> | null): string {
  return state && state.ai_ready && state.used_today < state.daily_limit ? "질문하기" : "원문에서 찾기";
}

export function waitingText(seconds: number): string {
  return `답을 찾는 중… ${seconds}초 (최대 2분)`;
}

/** 원문이 아직 없을 때 — 출처마다 무엇을 하면 되는지. */
export function noSourceText(kind: NoticeQaKind): string {
  if (kind === "support") return "이 지원사업 공고문을 아직 받지 않았습니다 — 매일 받기 때 받습니다";
  if (kind === "manual") return "공고문 파일을 올리면 질문할 수 있습니다";
  return "이 공고의 원문을 아직 받지 않았습니다 — 입찰 분석 화면에서 「공고 분석 시작」을 누르면 제안요청서를 받아 읽습니다";
}

/** 답 머리 — 상태마다 한 줄. */
export function statusHeading(status: NoticeQaStatus, kind: NoticeQaKind): string {
  if (status === "answered") return NOTICE_QA_ANSWER_HEAD;
  if (status === "not_found") return NOTICE_QA_NOT_FOUND;
  if (status === "search_only") return NOTICE_QA_MATCH_HEAD;
  return noSourceText(kind);
}

/** 근거를 원문에서 확인하지 못해 뺀 문장 수(0 이면 글 없음). */
export function droppedText(dropped: number): string | null {
  return dropped > 0 ? `원문에서 근거를 확인하지 못한 문장 ${dropped}개는 뺐습니다` : null;
}

/** 보낸 쪽이 일부일 때만 — 「보낸 쪽 12 / 61쪽(질문과 맞는 쪽부터)」. */
export function pagesSentText(answer: Pick<NoticeQaAnswer, "pages_sent" | "pages_total">): string | null {
  return answer.pages_sent > 0 && answer.pages_sent < answer.pages_total
    ? `AI 에 보낸 쪽 ${answer.pages_sent} / ${answer.pages_total}쪽(질문과 맞는 쪽부터)`
    : null;
}

/** 예시 질문 — 누르면 칸에 채운다. 지원사업 글에는 입찰 말을 쓰지 않는다. */
export function exampleQuestions(kind: NoticeQaKind): string[] {
  if (kind === "support") return ["지원 대상은 누구인가요?", "신청 기간은 언제까지인가요?", "제출 서류는 무엇인가요?", "지원 금액은 얼마인가요?"];
  if (kind === "manual") return ["신청 자격은 무엇인가요?", "마감은 언제인가요?", "제출 서류는 무엇인가요?"];
  return ["참가 자격은 무엇인가요?", "제출 서류는 무엇인가요?", "사업 기간과 예산은 얼마인가요?", "제안서 평가 기준은 무엇인가요?"];
}

/** 질문 칸 정리 — 서버와 같은 규칙(공백 정리 · 2~300자). 맞지 않으면 null. */
export function tidyQuestion(raw: string): string | null {
  const text = raw.split(/\s+/).filter(Boolean).join(" ");
  return text.length >= 2 && text.length <= NOTICE_QA_MAX_CHARS ? text : null;
}
