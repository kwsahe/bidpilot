/**
 * 최근 활동(감사 기록) — `data/private/audit_log.jsonl` 의 한 줄.
 *
 * 필드는 계정·권한 계약서 6장 그대로다. 본문·쿼리·헤더 값은 담기지 않는다
 * (토큰·비밀번호가 기록으로 새는 것을 막는다).
 *
 * 계약서는 **한 줄의 모양**만 정하고 `GET /api/audit-log` 의 응답 봉투는 정하지 않았다.
 * 그래서 화면은 배열과 흔한 봉투 키를 모두 받아들인다 (lib/api.ts 의 getAuditLog).
 */
export interface AuditLogEntry {
  /** ISO8601 시각 */
  ts: string;
  user: string;
  /** 계정의 표시 이름(44차 S4) — 계정 파일에 없으면 null · 화면은 아이디로. */
  display_name?: string | null;
  /** "viewer" | "editor" | "admin" — 화면에는 한국어로 옮겨 찍는다 */
  role: string;
  /** HTTP 메서드 (POST · PATCH · DELETE …) */
  method: string;
  path: string;
  organization_id: string | null;
  /** HTTP 응답 상태 */
  status: number;
  /** 사람이 한 일의 종류(조항 확인 · 목록 재수집 …) — 있는 줄만 (CMP-10) */
  event?: {
    kind?: string;
    procurement_id?: string;
    clause_id?: string;
    /** 「찾는 낱말」(2.0.7 · `collect_keyword_add` · `_remove` · `_search`) — 낱말 · 바로 찾기 건수(찾았으면) · 못 찾은 사유 */
    word?: string;
    found?: number | null;
    new?: number | null;
    search_error?: string | null;
  };
}
