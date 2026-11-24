/**
 * 로그인 밖 `/health` 응답(42차 · 회사 서버) — nginx `location = /health` · 점검이 부른다.
 * 백엔드 health 에서 **판 · 규칙 판 · ok 만** 고른다. 설정(키 있음 · 받기 문 · 모델 이름 · 회사 id)은 싣지 않는다.
 * 로그인한 화면은 예전처럼 백엔드 health 전부를 받는다(`app/health/route.ts`).
 */
export interface PublicHealth {
  status: "ok" | "down";
  version: string | null;
  rules_version: number | null;
}

export function publicHealth(body: unknown): PublicHealth {
  const row = body !== null && typeof body === "object" ? (body as Record<string, unknown>) : {};
  return {
    status: row.status === "ok" ? "ok" : "down",
    version: typeof row.version === "string" ? row.version : null,
    rules_version: typeof row.rules_version === "number" ? row.rules_version : null,
  };
}
