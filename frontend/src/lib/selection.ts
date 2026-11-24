/**
 * 지금 보고 있는 공고 — 화면이 바뀌어도 유지된다.
 *
 * 예전에는 화면마다 따로 관리했다. 대시보드는 URL `?notice=` + localStorage 를 쓰고,
 * RFP 분석은 URL 만 읽었으며, 상단 네비게이션 링크는 쿼리를 붙이지 않는 고정 문자열이었다.
 * 그래서 사업기회 → 실공고 분석 → 상단 「RFP 분석」을 누르는 순간 선택이 사라지고
 * 합성 RFP(synthetic-rfp-0001)로 되돌아갔다.
 *
 * 규칙:
 *  - **저장소가 하나다.** URL 이 우선이고, 없으면 localStorage 를 본다.
 *  - 고른 사람은 URL 과 localStorage 에 **함께** 쓴다. 한쪽만 쓰면 다음 화면에서 잃는다.
 *  - 합성 데모 공고는 저장하지 않는다 — 「아무것도 안 고른 상태」와 같게 둔다.
 *    그래야 사용자가 명시적으로 고르지 않는 한 데모가 되살아나지 않는다.
 *
 * 회사(organization_id)는 별도 키로 이미 유지되고 있다 — lib/organization.ts. 건드리지 않는다.
 */

export const NOTICE_QUERY_KEY = "notice";
export const NOTICE_STORAGE_KEY = "bidpilot.notice.v1";

/**
 * 기업마당 지원사업은 **따로 기억한다.**
 *
 * 나라장터 선택값(`bidpilot.notice.v1`)은 상단 네비게이션이 `/rfp` 로 실어 나르는 값이다.
 * 거기에 지원사업 id 가 들어가면 제안요청서 화면이 있지도 않은 공고를 찾는다.
 * 그래서 예전 코드는 지원사업을 **아무 데도 저장하지 않았고**, 그 결과 주소가
 * `/analysis?notice=g2b-…` 로 남아 새로고침하면 이전 입찰로 되돌아갔다.
 *
 * 저장소를 나누면 둘 다 지킨다 — 입찰 선택은 오염되지 않고, 지원사업도 주소에 남는다.
 */
export const SUPPORT_QUERY_KEY = "support";
export const SUPPORT_STORAGE_KEY = "bidpilot.support.v1";
/** 마지막으로 고른 것이 둘 중 무엇인가. 쿼리 없이 `/` 로 돌아왔을 때 어느 쪽을 열지 정한다. */
export const SELECTION_KIND_KEY = "bidpilot.selection-kind.v1";

export type SelectionKind = "notice" | "support";

/**
 * 기업마당 지원사업 id 인가. 판정은 여기 하나뿐이다.
 *
 * 대시보드는 나라장터 입찰을 8단계로, 지원사업을 7단계로 분석한다 — **불러오는 경로가 다르고**
 * 이 판정 하나로 갈린다. 이 구분이 없으면 나라장터 목록에서 id 를 못 찾아 조용히 데모로 되돌아간다.
 */
export function isSupportProgramId(id: string | null | undefined): boolean {
  return typeof id === "string" && id.startsWith("bizinfo-");
}

/** 고른 것의 종류. id 모양만 보고 정한다 — 저장값과 어긋날 여지를 만들지 않는다. */
export function selectionKindOf(id: string | null | undefined): SelectionKind {
  return isSupportProgramId(id) ? "support" : "notice";
}

/**
 * 선택이 바뀌었음을 같은 탭 안에서 알린다.
 *
 * `storage` 이벤트는 **다른 탭**에서만 날아온다. 같은 탭의 상단 네비게이션이
 * 즉시 따라오게 하려면 우리가 직접 알려야 한다.
 */
export const NOTICE_CHANGE_EVENT = "bidpilot:notice-change";

function announce(): void {
  try {
    window.dispatchEvent(new Event(NOTICE_CHANGE_EVENT));
  } catch {
    // 이벤트 발행 실패는 무시한다.
  }
}

/** 선택 변화를 구독한다 (useSyncExternalStore 용). */
export function subscribeSelection(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(NOTICE_CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  // 뒤로가기·앞으로가기는 주소만 바꾸고 아무 이벤트도 쏘지 않는다.
  // 이것을 듣지 않으면 주소는 이전 공고인데 화면은 그대로인 상태가 된다.
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener(NOTICE_CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
    window.removeEventListener("popstate", onChange);
  };
}

/** 서버(정적 생성)에서는 선택을 알 수 없다. */
export function readSelectedNoticeServer(): string | null {
  return null;
}

/** 합성 데모 공고인가. 저장·복원 대상에서 뺀다. */
export function isDemoNoticeId(id: string | null | undefined): boolean {
  return !id || id.startsWith("synthetic-");
}

/** 주소에 선택을 반영한다. 두 키는 **동시에 존재하지 않는다** — 한쪽을 쓰면 다른 쪽은 지운다. */
type HistoryMode = "push" | "replace";

function applyUrl(kind: SelectionKind, id: string | null, mode: HistoryMode): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete(NOTICE_QUERY_KEY);
    url.searchParams.delete(SUPPORT_QUERY_KEY);
    if (id) url.searchParams.set(kind === "support" ? SUPPORT_QUERY_KEY : NOTICE_QUERY_KEY, id);
    const next = url.toString();
    // 같은 주소를 또 push 하면 뒤로가기가 제자리걸음이 된다.
    if (next === window.location.href) return;
    if (mode === "push") window.history.pushState(window.history.state, "", next);
    else window.history.replaceState(window.history.state, "", next);
  } catch {
    // history 접근 실패는 무시한다 — 선택 자체는 동작해야 한다.
  }
}

function writeStore(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // 저장 실패는 무시한다 (시크릿 창 등). 주소에는 이미 남아 있다.
  }
}

/**
 * 고른 공고 · 지원사업 · 종류 기억을 지운다 — 로그아웃 때(2.0.6). 남기면 같은 PC 의 다음 계정이 메뉴 · 「보던 공고로 돌아가기」로
 * 앞 사람이 보던 공고를 따라갔다. 회사 · 기간 · 보기 기억은 사람의 것이 아니라 남긴다.
 */
export function clearSelectionMemory(): void {
  writeStore(NOTICE_STORAGE_KEY, null);
  writeStore(SUPPORT_STORAGE_KEY, null);
  writeStore(SELECTION_KIND_KEY, null);
  announce();
}

function readStore(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function readQuery(key: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(key);
  } catch {
    return null;
  }
}

/**
 * 지금 선택된 **입찰 공고**. URL 이 먼저다 — 링크로 들어온 사람이 이긴다.
 *
 * 지원사업을 보고 있어도 이 값은 마지막 입찰 공고를 그대로 돌려준다.
 * 상단 네비게이션의 `/rfp` 링크가 이것을 쓰기 때문이다 — 지원사업 id 로 오염시키지 않는다.
 */
export function readSelectedNotice(): string | null {
  if (typeof window === "undefined") return null;
  const fromUrl = readQuery(NOTICE_QUERY_KEY);
  if (fromUrl) return fromUrl;
  return readStore(NOTICE_STORAGE_KEY);
}

/** 지금 선택된 **기업마당 지원사업**. */
export function readSelectedSupport(): string | null {
  if (typeof window === "undefined") return null;
  const fromUrl = readQuery(SUPPORT_QUERY_KEY);
  if (fromUrl) return fromUrl;
  return readStore(SUPPORT_STORAGE_KEY);
}

/**
 * 대시보드가 **지금 열어야 할 것** 하나.
 *
 * 순서: 주소의 `?support=` → 주소의 `?notice=` → 마지막으로 고른 종류의 저장값 → 입찰 저장값.
 * 문자열 하나만 돌려준다 — useSyncExternalStore 의 getSnapshot 으로 쓰이므로 매번 새 객체를
 * 만들면 무한 렌더가 된다.
 */
export function readSelection(): string | null {
  if (typeof window === "undefined") return null;
  const support = readQuery(SUPPORT_QUERY_KEY);
  if (support) return support;
  const notice = readQuery(NOTICE_QUERY_KEY);
  if (notice) return notice;
  const kind = readStore(SELECTION_KIND_KEY);
  if (kind === "support") {
    const saved = readStore(SUPPORT_STORAGE_KEY);
    if (saved) return saved;
  }
  return readStore(NOTICE_STORAGE_KEY);
}

/** 서버(정적 생성)에서는 선택을 알 수 없다. */
export function readSelectionServer(): string | null {
  return null;
}

/**
 * 고른 것을 주소와 저장소에 남긴다. 종류는 id 모양이 정한다.
 *
 * `mode`:
 *  - `"push"`  — 사람이 직접 고른 것. 뒤로가기로 이전 선택으로 돌아갈 수 있어야 한다.
 *  - `"replace"` — 링크로 들어온 선택을 저장소에 맞추는 것뿐. 히스토리를 늘리지 않는다.
 */
export function writeSelection(id: string, mode: HistoryMode = "replace"): void {
  const kind = selectionKindOf(id);
  if (kind === "support") {
    applyUrl("support", id, mode);
    writeStore(SUPPORT_STORAGE_KEY, id);
    writeStore(SELECTION_KIND_KEY, "support");
    announce();
    return;
  }
  const demo = isDemoNoticeId(id);
  applyUrl("notice", demo ? null : id, mode);
  writeStore(NOTICE_STORAGE_KEY, demo ? null : id);
  // 데모(=선택 없음)로 돌아갔다면 「마지막에 지원사업을 봤다」는 기억도 지운다.
  writeStore(SELECTION_KIND_KEY, "notice");
  announce();
}

/** 고른 공고를 URL 과 저장소 **양쪽에** 남긴다. 한쪽만 쓰면 화면을 옮길 때 잃는다. */
export function writeSelectedNotice(id: string, mode: HistoryMode = "replace"): void {
  // 지원사업 id 가 입찰 저장값으로 새어 들어가는 것을 막는다.
  // 그 값은 상단 네비게이션이 `/rfp` 로 실어 나르므로, 들어가면 없는 공고를 찾게 된다.
  if (isSupportProgramId(id)) return;
  writeSelection(id, mode);
}

/** 기업마당 지원사업 선택을 남긴다. 입찰 저장값은 건드리지 않는다. */
export function writeSelectedSupport(id: string, mode: HistoryMode = "replace"): void {
  if (!isSupportProgramId(id)) return;
  writeSelection(id, mode);
}

/**
 * 지원사업을 **저장소에만** 남긴다 — 주소는 그대로 (`/support/<id>` 화면).
 *
 * 그 화면은 주소에 `?support=` 가 없어서, 남기지 않으면 상단 메뉴가 마지막 입찰을 따라갔다 —
 * 「요구사항 정리표」가 잠기지 않고 직전 입찰의 표를 열었다 (27차 LNK-01). 입찰 저장값은 건드리지 않는다.
 */
export function rememberSupport(id: string): void {
  if (!isSupportProgramId(id)) return;
  writeStore(SUPPORT_STORAGE_KEY, id);
  writeStore(SELECTION_KIND_KEY, "support");
  announce();
}

/** 선택을 지운다 (공고가 목록에서 사라졌을 때 등). */
export function clearSelectedNotice(): void {
  applyUrl("notice", null, "replace");
  writeStore(NOTICE_STORAGE_KEY, null);
  writeStore(SELECTION_KIND_KEY, "notice");
  announce();
}

/** 지원사업 선택만 지운다 (입찰로 돌아갈 때). */
export function clearSelectedSupport(): void {
  writeStore(SUPPORT_STORAGE_KEY, null);
  writeStore(SELECTION_KIND_KEY, "notice");
  announce();
}

/**
 * 화면 이동 링크에 현재 선택을 얹는다.
 *
 * 상단 네비게이션이 고정 문자열 `/rfp` 를 쓰는 바람에 선택이 매번 날아갔다.
 * 공고를 다루는 화면끼리만 붙인다 — 회사자료 화면에는 공고 개념이 없다.
 */
export function hrefWithNotice(href: string, noticeId: string | null): string {
  if (!noticeId || isDemoNoticeId(noticeId)) return href;
  if (!CARRIES_NOTICE.has(href)) return href;
  return `${href}?${NOTICE_QUERY_KEY}=${encodeURIComponent(noticeId)}`;
}

/**
 * 사업기회 목록 ↔ 레이더 링크에 조건을 얹는다 — 두 화면은 같은 주소 키(`src` · `track` · `sort` · `closed`)를 쓴다.
 * 예전에는 `/radar` · `/opportunities` 고정 문자열이라 건너가면 늘 기본 조건으로 열렸다 (27차 LNK-09).
 * 기본값은 적지 않는다. 받는 화면이 모르는 값(목록에만 있는 정렬 등)은 그쪽이 버린다.
 */
export function hrefWithConditions(
  path: string,
  /** sort = 고른 정렬. null 이면 회사 설정(기본) — 주소에 쓰지 않는다(37차 §3-C · 기본은 회사마다 다르다). */
  conditions: { src: string; track: string; sort: string | null; closed: boolean },
): string {
  const query = new URLSearchParams();
  if (conditions.src !== "all") query.set("src", conditions.src);
  if (conditions.track !== "all") query.set("track", conditions.track);
  if (conditions.sort) query.set("sort", conditions.sort);
  if (conditions.closed) query.set("closed", "1");
  const search = query.toString();
  return search ? `${path}?${search}` : path;
}

/**
 * 선택한 공고를 이어받는 화면들.
 *
 * 목록·레이더를 더했다 (0920 §4-B-4 · ISSUE-077-c). 예전에는 대시보드와 RFP 분석만
 * 이어받아서, 목록이나 레이더에 갔다 오면 고른 공고를 잃었다 — 「같은 공고를 네 화면에서
 * 본다」가 상단 메뉴만으로는 되지 않았다.
 *
 * 회사자료(`/company`)는 넣지 않는다. 그 화면에는 공고라는 개념이 없다. 대시보드(`/`)도 넣지 않는다 — 2.1.0 부터 통계 화면이고,
 * 공고 하나를 보는 화면은 입찰 분석(`/analysis`)이다.
 */
const CARRIES_NOTICE = new Set(["/analysis", "/opportunities", "/radar", "/plan"]);

/**
 * 요구사항 정리표 주소 — 사업기회 「요구사항 정리표」 탭 (28차 §3-C · 예전 `/rfp`). 모든 화면의 정리표 링크가 이것 하나를 쓴다.
 */
export function requirementSheetHref(noticeId: string, reqId?: string | null): string {
  const query = new URLSearchParams({ tab: "sheet", [NOTICE_QUERY_KEY]: noticeId });
  if (reqId) query.set("req", reqId);
  return `/opportunities?${query.toString()}`;
}
