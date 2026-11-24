/**
 * 로그인 시도 제한 — **주소(IP) 단위** (S11).
 *
 * ## 왜 여기인가
 *
 * 백엔드도 연속 실패를 세지만 «아이디 단위»다. 브라우저가 백엔드를 직접 부르지 않고
 * 이 서버가 중계하므로, 백엔드가 보는 주소는 전부 이 서버 하나다. 주소로 세면 한 사람이
 * 틀릴 때 전원이 잠긴다. 반대로 아이디로만 세면 아이디를 매번 바꿔 가며 두드리는 쪽을
 * 못 막는다 — 한 번에 pbkdf2 60만 회(0.2초)를 시키는 일이라 그것만으로도 서버가 눕는다.
 *
 * 브라우저의 주소가 보이는 자리는 여기뿐이다. 그래서 두 겹으로 나눈다.
 *
 *     주소 단위 (여기)  — 한 주소에서 1분에 10번까지
 *     아이디 단위 (백엔드) — 5회 틀리면 60초부터 배로 늘려 잠금
 *
 * ## 한계 (알고 두는 것)
 *
 * - 세는 곳이 **이 프로세스의 메모리**다. 인스턴스가 여러 개면 각자 센다. 재시작하면 지워진다.
 *   사내 도구 한 대 규모에서는 이 정도가 맞다고 보고 Redis 같은 것을 끌어오지 않았다.
 * - 주소는 `x-forwarded-for` 의 **맨 뒤** 값이다 (N2). 맨 앞이 아니다 — 그 자리는 클라이언트가
 *   직접 써 보낼 수 있어서, 요청마다 다른 값을 넣으면 제한을 그냥 지나간다. 맨 뒤는 우리
 *   바로 앞의 프록시가 «덧붙인» 값이라 클라이언트가 고를 수 없다. 프록시가 하나일 때 그것이
 *   브라우저 주소다. 프록시가 둘 이상이면 우리에게 가장 가까운 홉이 되어 제한이 거칠어지지만,
 *   **거친 제한이 우회 가능한 제한보다 낫다.** 헤더가 없으면 한 덩어리로 묶어 센다.
 * - 주소를 바꿔 가며 두드리는 쪽은 여기서 못 막는다. 그쪽은 백엔드의 아이디 단위 잠금과
 *   `API_TOKEN` 이 막는다.
 */

/** 한 주소가 창 안에서 시도할 수 있는 횟수. 사람은 한 번에 두세 번이면 충분하다. */
export const MAX_ATTEMPTS = 10;
/** 세는 창(밀리초). */
export const WINDOW_MS = 60_000;
/** 기억해 둘 주소 수 상한. 임의의 헤더를 보내 메모리를 불리지 못하게 한다. */
export const MAX_TRACKED = 2048;

interface Bucket {
  count: number;
  /** 창이 시작된 시각(ms). */
  since: number;
}

const buckets = new Map<string, Bucket>();

/** 요청에서 셀 기준이 될 주소를 뽑는다. 없으면 `"unknown"` 한 덩어리로 묶는다. */
export function clientKey(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) {
    const hops = forwarded.split(",").map((h) => h.trim()).filter(Boolean);
    // **마지막** 홉을 쓴다 (N2). 앞쪽은 클라이언트가 지어낼 수 있다.
    const last = hops[hops.length - 1];
    // 길이를 자른다 — 헤더는 사용자가 정하는 값이라 그대로 키로 쓰면 안 된다.
    if (last) return last.slice(0, 64);
  }
  const real = headers.get("x-real-ip")?.trim();
  if (real) return real.slice(0, 64);
  return "unknown";
}

/**
 * 한 번 시도했다고 세고, 넘었는지 알려준다.
 *
 * @returns 넘었으면 `{ limited: true, retryAfterSeconds }`.
 */
export function noteAttempt(key: string, now: number = Date.now()): {
  limited: boolean;
  retryAfterSeconds: number;
} {
  const bucket = buckets.get(key);
  if (bucket === undefined || now - bucket.since >= WINDOW_MS) {
    if (buckets.size >= MAX_TRACKED) prune(now);
    buckets.set(key, { count: 1, since: now });
    return { limited: false, retryAfterSeconds: 0 };
  }
  bucket.count += 1;
  if (bucket.count > MAX_ATTEMPTS) {
    return {
      limited: true,
      retryAfterSeconds: Math.max(1, Math.ceil((bucket.since + WINDOW_MS - now) / 1000)),
    };
  }
  return { limited: false, retryAfterSeconds: 0 };
}

/** 성공했을 때. 맞게 들어온 사람에게 다음 시도까지 제한을 물려주지 않는다. */
export function clearAttempts(key: string): void {
  buckets.delete(key);
}

/**
 * 창이 지난 기록부터 버린다. 그래도 넘치면 **오래된 것부터** 버린다 (N2).
 *
 * 예전에는 넘칠 때 통째로 비웠다(`buckets.clear()`). 그러면 서로 다른 주소 2048개를 만들어
 * 보내는 것이 곧 **제한 해제 수단**이 된다 — 지금 잠겨 있는 사람까지 함께 풀려난다.
 * 오래된 순으로 4분의 1만 버리면, 넘치게 만들어도 방금 두드린 주소는 살아남는다.
 */
function prune(now: number): void {
  for (const [key, bucket] of buckets) {
    if (now - bucket.since >= WINDOW_MS) buckets.delete(key);
  }
  if (buckets.size < MAX_TRACKED) return;
  /**
   * **지금 잠긴 주소를 마지막에 버린다.**
   *
   * 「오래된 것부터」만으로는 부족하다 — 잠긴 주소는 대개 가장 먼저 만들어졌으므로 곧 가장
   * 오래된 것이 된다. 그러면 새 주소를 잔뜩 보내는 것이 그대로 잠금 해제 수단이 된다
   * (실제로 테스트에서 그렇게 풀렸다). 넘치지 않은 것부터, 그 안에서 오래된 것부터 버린다.
   *
   * 남는 한계: 가짜 주소마다 한도까지 두드려 «잠긴» 항목으로 표를 채우면 결국 밀어낼 수
   * 있다. 그때는 2048개 × 11회 = 2만 번 넘게 보내야 하고, 그쯤이면 이 표가 아니라 서버를
   * 두드리는 일이다. 메모리 상한은 지켜야 하므로 여기서 멈춘다.
   */
  const order = [...buckets.entries()].sort((a, b) => {
    const aLocked = a[1].count > MAX_ATTEMPTS ? 1 : 0;
    const bLocked = b[1].count > MAX_ATTEMPTS ? 1 : 0;
    if (aLocked !== bLocked) return aLocked - bLocked;
    return a[1].since - b[1].since;
  });
  const drop = Math.max(1, Math.floor(MAX_TRACKED / 4));
  for (let i = 0; i < drop && i < order.length; i += 1) buckets.delete(order[i][0]);
}

/** 테스트·운영자용. */
export function resetAll(): void {
  buckets.clear();
}
