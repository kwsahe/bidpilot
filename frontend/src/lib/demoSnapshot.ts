/**
 * 읽기 전용 데모 배포용 응답 저장소.
 *
 * 로컬 백엔드(:8110)의 GET 응답을 `scripts/snapshot_demo_api.py` 로 떠 둔 것이다.
 * Vercel 배포본은 백엔드 없이 이 스냅샷만으로 화면을 그린다.
 * 다시 뜨려면: 백엔드를 켜고 `python scripts/snapshot_demo_api.py`.
 */
import snapshot from "@/data/demo-snapshot.json";

const store = snapshot as Record<string, unknown>;

/**
 * 데모 모드 판정은 `@/lib/demoMode` 에 있다 — 이 파일은 6MB JSON 을 import 하므로
 * **클라이언트 컴포넌트는 여기서 가져오면 안 된다** (번들에 JSON 이 통째로 딸려간다).
 * 서버 쪽 기존 import 호환을 위해 재수출만 한다.
 */
export { demoMode } from "@/lib/demoMode";

/** 저장된 응답. 쿼리스트링이 달라 못 찾으면 경로만으로 한 번 더 찾는다. */
export function lookup(pathWithQuery: string): unknown | undefined {
  if (pathWithQuery in store) return store[pathWithQuery];
  const bare = pathWithQuery.split("?")[0];
  return store[bare];
}
