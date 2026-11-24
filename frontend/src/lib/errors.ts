/**
 * 사용자에게 보여줄 오류 문구 — 정의는 여기 하나뿐이다.
 *
 * ## 왜 필요한가
 *
 * 화면이 이런 말을 하고 있었다.
 *
 *   「Backend 응답 오류 (HTTP 500). 잠시 후 다시 시도해 주세요.」
 *   「Backend에 연결할 수 없습니다. http://localhost:8000 에서 FastAPI 서버가 실행 중인지 확인해 주세요.」
 *   「backend에서 찾지 못했습니다 (HTTP 404)」
 *
 * 이 도구를 쓰는 사람은 사업담당자다. FastAPI 가 무엇인지, 자기 컴퓨터의 8000번 포트를
 * 어떻게 확인하는지 모른다. 더 나쁜 것은 **그 안내가 틀렸다**는 점이다 — 서버는 멀쩡히
 * 떠 있는데 임베딩 키가 거부돼 500 이 났고, 그 500 에 CORS 헤더가 없어 브라우저가
 * `TypeError` 를 던졌으며, 프론트가 그것을 「서버 꺼짐」으로 단정했다.
 *
 * ## 규칙
 *
 * - 사용자 문장에는 **HTTP 코드·서버 주소·프레임워크 이름을 쓰지 않는다.**
 * - 문장은 「무슨 일이 있었나 + 다음에 무엇을 하면 되나」 두 조각이다.
 * - 서버가 한국어 `detail` 을 주면 **그것이 이긴다.** 서버만 아는 이유(키 설정, 변환기 없음)를
 *   우리가 일반 문장으로 덮으면 안 된다.
 * - 코드·주소가 필요한 사람(개발자)을 위해서는 `technicalNote()` 를 따로 두고,
 *   화면에서는 접힌 「기술 정보」 안에만 쓴다.
 */

import { ApiError } from "@/lib/api";

/** 상태 코드별 사용자 문장. 코드 자체는 문장에 넣지 않는다. */
export function describeHttpFailure(status: number | null): string {
  if (status === null) return "요청을 처리하지 못했습니다. 잠시 후 다시 시도하고, 계속되면 관리자에게 알려 주세요.";
  if (status === 404) return "아직 저장된 결과가 없습니다. 분석을 먼저 실행해 주세요.";
  if (status === 401 || status === 403) return "권한이 없습니다. 로그인 상태를 확인해 주세요.";
  if (status === 409) return "다른 작업이 먼저 처리됐습니다. 화면을 새로 고친 뒤 다시 시도해 주세요.";
  if (status === 413) return "파일이 너무 큽니다. 크기를 줄여 다시 올려 주세요.";
  if (status === 422) return "입력한 값을 저장할 수 없습니다. 내용을 확인해 주세요.";
  if (status === 429) return "요청이 몰렸습니다. 잠시 후 다시 시도해 주세요.";
  if (status === 503) return "이 기능이 지금 준비되지 않았습니다. 잠시 후 다시 시도하고, 계속되면 관리자에게 알려 주세요.";
  if (status >= 500) return "처리 중 문제가 생겼습니다. 다시 시도해 주세요. 계속되면 관리자에게 알려 주세요.";
  return "요청을 처리하지 못했습니다. 내용을 확인한 뒤 다시 시도해 주세요.";
}

/**
 * 네트워크가 끊겼을 때. 원인을 단정하지 않는다 — 「서버가 꺼졌다」도 「인터넷」도 아니다.
 * 로컬 운영에서는 대개 이 PC 의 서버 창이 꺼진 것이었는데 「인터넷 상태를 확인」이 엉뚱한 곳을 가리켰다 (CMN-26).
 */
export const SESSION_EXPIRED_MESSAGE =
  "저장하지 못했습니다 — 세션이 끝났습니다. 새 탭에서 다시 로그인한 뒤 이 화면으로 돌아와 다시 누르세요(쓰던 글은 이 화면에 그대로 있습니다).";

export const NETWORK_MESSAGE = "서버와 연결되지 않았습니다. 잠시 뒤 새로 고쳐 주세요. 계속되면 관리자에게 알려 주세요.";

/**
 * 어떤 실패든 사용자 문장 하나로.
 *
 * `fallback` 은 화면마다 다른 맥락 문장이다(예: 「공고 목록을 불러오지 못했습니다」).
 * 서버가 준 한국어 사유가 있으면 그 뒤에 붙인다.
 */
/**
 * 응답을 받기 전에 연결이 끊겼나(44차 M2) — 중계 · 게이트의 502 · 503 · 504 또는 fetch 자체 실패. 서버는 아직 일하는 중일 수 있어
 * 같은 요청을 다시 보내지 말고 저장된 결과를 다시 읽어야 한다(오래 걸리는 Claude · Codex 초안).
 */
export function isConnectionCut(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 502 || error.status === 503 || error.status === 504;
  return error instanceof TypeError;
}

export function describeFailure(error: unknown, fallback?: string): string {
  if (error instanceof ApiError) {
    // 43차 M28 — 세션이 끝났다. 서버 한 줄(「로그인이 필요합니다.」)만으로는 저장이 안 됐는지 · 무엇을 할지 몰랐다.
    // 45차 L9 — 계정이 꺼진 401 은 다시 로그인해도 안 된다 — 서버 문장 그대로(「관리자에게」)
    if (error.status === 401) return error.detail?.startsWith("계정이 꺼졌습니다") ? error.detail : SESSION_EXPIRED_MESSAGE;
    // 서버 사유가 객체(`{code, message}`)로 오면 message 를 쓴다 — 버리면 「다른 작업이 먼저 처리됐습니다」 같은 엉뚱한 일반 문장이 났다 (CMN-11).
    const detail = koreanDetail(error.detail) ?? koreanDetail(error.serverMessage);
    if (detail) return detail;
    return fallback ? `${fallback} ${describeHttpFailure(error.status)}` : describeHttpFailure(error.status);
  }
  // fetch 가 던지는 TypeError. 서버가 꺼진 것일 수도, CORS 헤더 없는 500 일 수도 있다 —
  // 어느 쪽인지 브라우저는 알려주지 않으므로 «단정하지 않는» 문장을 쓴다.
  if (error instanceof TypeError) return NETWORK_MESSAGE;
  return fallback ?? describeHttpFailure(null);
}

/** 서버가 준 사유가 사용자에게 보여줄 만한 한국어인가. 영문 스택·클래스명은 걸러낸다. */
export function koreanDetail(detail: string | null | undefined): string | null {
  if (!detail) return null;
  const text = detail.trim();
  if (!text) return null;
  // 한글이 한 글자도 없으면 개발자용 메시지로 본다.
  if (!/[가-힣]/.test(text)) return null;
  // 너무 길면 화면에 그대로 못 쓴다 (스택이 섞여 온 경우).
  return text.length > 300 ? `${text.slice(0, 299)}…` : text;
}

/**
 * 접힌 「기술 정보」에만 쓰는 한 줄. 화면 본문에 쓰지 말 것.
 *
 * 이 함수의 결과를 사용자 문장과 같은 자리에 두면 애초에 고치려던 문제로 돌아간다.
 */
export function technicalNote(error: unknown): string | null {
  if (error instanceof ApiError) {
    return `status ${error.status}${error.detail ? ` · ${error.detail}` : ""}`;
  }
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return null;
}

/**
 * 통합 목록의 한 출처가 실패했나 — 서버는 출처마다 예외를 잡아 200 + `source_errors` 로 답한다. 그 출처 항목이 **하나도 없을 때만** 실패다.
 * 저장본으로 대신 준 날(실시간 받기 실패 · 받은 양이 줄어 저장을 거절함)은 항목과 오류 글이 함께 온다 — 그날을 실패로 보면 첫 화면이
 * 오류로 가고 목록을 다 보이면서 「받지 못했습니다」를 띄웠다(2.0.6 통합 검토 · 서버 failed_sources 와 같은 규칙).
 */
export function sourceFailure(
  response: { items: ReadonlyArray<{ source_type: string }>; source_errors?: Record<string, string | null> | null },
  source: string,
): string | null {
  const message = response.source_errors?.[source] ?? null;
  if (!message) return null;
  return response.items.some((item) => item.source_type === source) ? null : message;
}
