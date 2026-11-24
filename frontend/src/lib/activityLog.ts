/**
 * 관리자 「최근 활동」 표의 줄 고르기 · 낱말 (43차 TEAM-04).
 *
 * 공고를 고르기만 해도 자동 판정 계산이 「실행 · 등록 요청」으로 한 줄씩 남았고(공고 6건이면 6줄), 회사 값 저장 · 안 적음 ·
 * 직접 넣기 고침이 모두 「저장 요청」 한 낱말이었다. 조항 확인 한 번은 두 줄(요청 줄 + 사건 줄)이었다.
 * 무엇을 바꿨는지로 적고, 자동 계산 · 같은 일의 두 번째 줄은 뺀다(기록 파일은 그대로 — 화면에서만 고른다).
 */

import type { AuditLogEntry } from "@/types/audit";

/** 사람이 바꾼 것이 아닌 자동 계산(공고를 고르면 화면이 부르는 판정) — 표에서 뺀다. */
const AUTO_PATHS = [/^\/api\/eligibility\/evaluate$/, /^\/api\/opportunities\/rank$/, /^\/api\/evidence\/match$/];

/** 화면 서버가 로그인 확인 때 남기는 자기 신원(45차 H6 — 표가 「api-token · 실행 · 등록 요청」 줄로 가득했다). 사람이 아니다. */
const SERVICE_USERS = new Set(["api-token"]);

/** (방법, 주소) → 바꾼 것. 위에서부터 처음 맞는 것. */
const PATH_LABELS: [string, RegExp, string][] = [
  ["PUT", /^\/api\/capability\/profile$/, "입찰 자격 자료 저장"],
  ["PUT", /^\/api\/capability\/left-blank$/, "「안 적음」 고름"],
  ["PUT", /^\/api\/capability\/company-checks$/, "회사 단위 확인 저장"],
  ["POST", /^\/api\/manual-notices$/, "공고 직접 넣기"],
  ["PUT", /^\/api\/manual-notices\/[^/]+$/, "직접 넣은 공고 고침"],
  ["DELETE", /^\/api\/manual-notices\/[^/]+$/, "직접 넣은 공고 지움"],
  ["POST", /^\/api\/manual-notices\/[^/]+\/document$/, "직접 넣은 공고문 올림"],
  ["PUT", /^\/api\/manual-notices\/[^/]+\/human-pass$/, "직접 넣은 공고 「가능」으로(원문 확인)"],
  ["DELETE", /^\/api\/manual-notices\/[^/]+\/human-pass$/, "직접 넣은 공고 「가능」 되돌림"],
  ["POST", /^\/api\/notice-inbox\/paste$/, "후보함 붙여넣기"],
  ["POST", /^\/api\/notice-inbox\/[^/]+\/discard$/, "후보 버림"],
  ["PUT", /^\/api\/watchlist$/, "열어 볼 곳 목록 고침"],
  ["POST", /^\/api\/watchlist\/[^/]+\/opened$/, "기관 게시판 열기"],
  ["PUT", /^\/api\/decision\/[^/]+$/, "참여 · 신청 결정 저장"],
  ["POST", /^\/api\/auth\/password$/, "내 비밀번호 바꿈"],
  ["PUT", /^\/api\/eligibility\/[^/]+\/review\/[^/]+$/, "조항 확인"],
  // 45차 H6 — 「실행 · 등록 요청」 · 「저장 요청」 · 「삭제 요청」으로만 나오던 흔한 일
  ["POST", /^\/api\/auditor\/run$/, "제출 전 점검 실행"],
  ["PUT", /^\/api\/auditor\/[^/]+\/resolutions$/, "점검 결과 해결 처리"],
  ["POST", /^\/api\/proposal\/generate$/, "제안서 초안 만들기"],
  ["POST", /^\/api\/proposal\/generate\/full$/, "제안서 전체 초안 만들기"],
  ["POST", /^\/api\/proposal\/[^/]+\/plan-draft$/, "제안서 초안 쓰기(제안요청서 목차대로)"],
  // 2.4.0 — 질문 · 답은 저장하지 않는다(기록에는 공고 주소만)
  ["POST", /^\/api\/notice-qa\/[^/]+$/, "공고문에 질문하기"],
  ["PUT", /^\/api\/evidence\/[^/]+\/ledger$/, "원장 실적 채택 · 취소"],
  ["POST", /^\/api\/rfp\/parse$/, "공고 분석(요구사항 뽑기)"],
  ["PUT", /^\/api\/rfp\/[^/]+\/items\/[^/]+$/, "요구사항 정정 · 확정"],
  ["POST", /^\/api\/conditions\/detect$/, "놓치면 안 되는 조건 찾기"],
  ["PUT", /^\/api\/conditions\/[^/]+\/[^/]+$/, "조건 해결 처리"],
  ["POST", /^\/api\/actions\/[^/]+$/, "할 일 추가"],
  ["PUT", /^\/api\/actions\/[^/]+\/[^/]+$/, "할 일 고침"],
  ["DELETE", /^\/api\/actions\/[^/]+\/[^/]+$/, "할 일 지움"],
  ["POST", /^\/api\/review$/, "검토 승인 · 다시 검토"],
  ["POST", /^\/api\/support-programs\/[^/]+\/plan-draft$/, "사업계획서 기본 초안 만들기"],
  ["POST", /^\/api\/support-programs\/[^/]+\/annex$/, "과제소개서 받기"],
  ["POST", /^\/api\/business-opportunities\/recollect$/, "목록 새로 받기"],
  // 2.0.7 「찾는 낱말」 — 더하기(바로 찾기 함께) · 지우기 · 이미 더한 낱말 다시 찾기
  ["POST", /^\/api\/collect-keywords$/, "찾는 낱말 더함"],
  ["POST", /^\/api\/collect-keywords\/remove$/, "찾는 낱말 지움"],
  ["POST", /^\/api\/collect-keywords\/search$/, "찾는 낱말 바로 찾기"],
  ["POST", /^\/api\/organizations$/, "새 회사 등록"],
  ["PUT", /^\/api\/organizations\/[^/]+\/profile$/, "회사 프로필 저장"],
  ["PUT", /^\/api\/organizations\/[^/]+\/plan-general$/, "사업계획서 일반현황 저장"],
  ["POST", /^\/api\/organizations\/[^/]+\/documents$/, "회사자료 올림"],
  ["PUT", /^\/api\/organizations\/[^/]+\/documents\/[^/]+\/candidates$/, "회사자료 문장 고름"],
  ["POST", /^\/api\/organizations\/[^/]+\/documents\/[^/]+\/approve$/, "회사자료 근거로 등록"],
  ["POST", /^\/api\/organizations\/[^/]+\/documents\/[^/]+\/retire$/, "회사자료 근거에서 뺌"],
  ["DELETE", /^\/api\/organizations\/[^/]+\/documents\/[^/]+$/, "회사자료 지움"],
  ["POST", /^\/api\/organizations\/[^/]+\/ledger\/import$/, "실적 목록(엑셀) 등록"],
];

const EVENT_LABELS: Record<string, string> = {
  clause_review: "조항 확인",
  recollect: "목록 새로 받기",
  capacity_setting: "순서 방식 · 단독 상한 · AI 보조 바꿈",
  // 2.0.7 「찾는 낱말」 — 서버 `insights._audit_keyword` 의 사건 줄(낱말 · 건수)
  collect_keyword_add: "찾는 낱말 더함",
  collect_keyword_remove: "찾는 낱말 지움",
  collect_keyword_search: "찾는 낱말 바로 찾기",
};
const SETTING_NAMES: Record<string, string> = { ranking_method: "순서 방식", budget_ceiling_krw: "단독 상한", ai_fit_assist: "AI 보조" };
const METHOD_LABELS: Record<string, string> = { POST: "실행 · 등록", PUT: "저장", PATCH: "수정", DELETE: "삭제" };

/** 동작 칸 — 주소 원문 대신 바꾼 것. 모르는 요청은 요청 종류만 적는다(지어내지 않는다). */
export function actionLabel(row: AuditLogEntry): string {
  const event = row.event as Record<string, string | undefined> | undefined;
  const kind = event?.kind;
  if (kind === "capacity_setting" && event) {
    const changes = Object.entries(event)
      .filter(([key]) => key !== "kind")
      .map(([key, value]) => `${SETTING_NAMES[key] ?? key} ${value}`);
    return [EVENT_LABELS[kind], ...changes].join(" · ");
  }
  if (kind?.startsWith("collect_keyword_") && EVENT_LABELS[kind]) {
    // 어떤 낱말을 더했는지 · 지웠는지 · 몇 건 찾았는지 — 지운 낱말은 목록에서 사라지므로 여기에만 남는다
    const { word, found, new: fresh, search_error: searchError } = row.event ?? {};
    const searched = typeof found === "number" ? `${found}건 찾음(새 공고 ${fresh ?? 0})` : searchError ? "바로 찾기 못 함" : null;
    return [EVENT_LABELS[kind], word ? `「${word}」` : null, searched].filter(Boolean).join(" · ");
  }
  if (kind && EVENT_LABELS[kind]) return [EVENT_LABELS[kind], event?.clause_id, event?.procurement_id].filter(Boolean).join(" · ");
  const known = PATH_LABELS.find(([method, pattern]) => method === row.method && pattern.test(row.path));
  return known ? known[2] : `${METHOD_LABELS[row.method] ?? "요청"} 요청`;
}

const MS = (iso: string) => Date.parse(iso);

/** 결과 칸 — 사람 말로(45차 H6 · 「성공 200 · 권한 거부 403」). 응답 번호는 칸 풀이(title)에만. */
export function resultText(status: number): string {
  if (status >= 200 && status < 300) return "성공";
  if (status === 401) return "로그인 필요";
  if (status === 403) return "권한 없음";
  if (status === 409) return "먼저 바뀜(다시 불러오기)";
  if (status === 404) return "없음";
  if (status >= 400 && status < 500) return "거절됨";
  if (status >= 500) return "서버 오류";
  return "확인 안 됨";
}

/**
 * 표에 둘 줄 — 자동 계산 줄을 빼고, 같은 사람 · 같은 주소의 사건 줄(조항 확인 · 설정 전후)이 10초 안에 있으면 요청 줄은 뺀다.
 * 최신순 그대로 `limit` 줄까지.
 */
export function visibleActivity(rows: readonly AuditLogEntry[], limit = 20): AuditLogEntry[] {
  const events = rows.filter((row) => row.event?.kind);
  return rows
    .filter((row) => !SERVICE_USERS.has(row.user))
    .filter((row) => !AUTO_PATHS.some((pattern) => pattern.test(row.path)))
    .filter(
      (row) =>
        Boolean(row.event?.kind) ||
        !events.some((ev) => ev.user === row.user && ev.path === row.path && Math.abs(MS(ev.ts) - MS(row.ts)) <= 10_000),
    )
    .slice(0, limit);
}
