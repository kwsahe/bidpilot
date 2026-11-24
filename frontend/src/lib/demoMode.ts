/**
 * 읽기 전용 데모 배포 여부 — **스냅샷 JSON을 import 하지 않는 가벼운 모듈**.
 *
 * `lib/demoSnapshot.ts` 는 6MB 짜리 `data/demo-snapshot.json` 을 정적 import 한다.
 * 클라이언트 컴포넌트가 그 모듈에서 `demoMode()` 하나만 가져와도 번들러는 모듈 단위로 묶기 때문에
 * **JSON 전체가 브라우저 번들에 딸려 들어간다** (실제로 6.2MB 청크가 생기는 것을 빌드 산출물에서 확인했다).
 *
 * 그래서 판정 함수만 여기로 분리한다. 브라우저에서 도는 코드는 반드시 이 파일에서 가져온다.
 * 스냅샷을 실제로 읽는 쪽(라우트 핸들러 = 서버)만 `lib/demoSnapshot` 을 쓴다.
 */

/** 데모 모드인가. 배포본에서만 1로 켠다. */
export function demoMode(): boolean {
  return process.env.NEXT_PUBLIC_DEMO_MODE === "1";
}
