/**
 * 선택 상태 검사 — 「고른 것이 새로고침·링크 공유·뒤로가기를 견디는가」.
 *
 * ## 무엇을 막는가
 *
 * 통합 대시보드에서 기업마당 지원사업을 고르면 화면은 지원사업 분석으로 바뀌었지만
 * 주소는 이전 나라장터 공고(`/analysis?notice=g2b-…`)로 남아 있었다. 그 상태로 새로고침하거나
 * 링크를 공유하면 **고른 적 없는 이전 입찰**이 열렸다.
 *
 * 원인은 안전장치였다 — 지원사업 id 가 입찰 저장값(`bidpilot.notice.v1`)에 들어가면
 * 상단 네비게이션의 「RFP 분석」이 있지도 않은 공고를 찾으므로, 예전 코드는 지원사업을
 * **아무 데도 저장하지 않고** 그냥 돌아왔다. 그래서 주소가 갱신되지 않았다.
 *
 * 지금은 저장소를 둘로 나눈다(`?notice=` / `?support=`). 이 검사는 그 두 가지를 함께 지킨다:
 * 지원사업이 주소에 남을 것, 그리고 입찰 저장값을 오염시키지 않을 것.
 *
 * ## 어떻게 검사하는가
 *
 * 화면이 실제로 쓰는 `lib/selection.ts` 를 그대로 불러, 최소한의 가짜 브라우저
 * (주소 · localStorage · history 스택)를 붙여 돌린다. 사본을 만들지 않는다.
 *
 * 실행:  node scripts/check_selection.mjs
 */

let failed = 0;
let passed = 0;

function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ✓ ${name}`);
  } else {
    failed += 1;
    console.log(`  ✗ ${name}\n      기대 ${JSON.stringify(expected)} · 실제 ${JSON.stringify(actual)}`);
  }
}

// ---------------------------------------------------------------------------
// 최소 가짜 브라우저
// ---------------------------------------------------------------------------

function makeWindow(startHref = "http://localhost:3110/") {
  const store = new Map();
  const stack = [startHref];
  let index = 0;
  const listeners = new Map();

  const win = {
    get location() {
      return { get href() { return stack[index]; }, get search() { return new URL(stack[index]).search; } };
    },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => void store.set(k, String(v)),
      removeItem: (k) => void store.delete(k),
    },
    history: {
      state: null,
      pushState(_state, _title, url) {
        stack.splice(index + 1);
        stack.push(url);
        index = stack.length - 1;
      },
      replaceState(_state, _title, url) {
        stack[index] = url;
      },
      /** 뒤로가기 — 실제 브라우저처럼 주소만 바꾸고 popstate 를 쏜다. */
      back() {
        if (index > 0) index -= 1;
        win.dispatchEvent({ type: "popstate" });
      },
      forward() {
        if (index < stack.length - 1) index += 1;
        win.dispatchEvent({ type: "popstate" });
      },
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
    },
    removeEventListener(type, fn) {
      listeners.get(type)?.delete(fn);
    },
    dispatchEvent(event) {
      for (const fn of listeners.get(event.type) ?? []) fn(event);
      return true;
    },
    _store: store,
    _stack: stack,
    _index: () => index,
  };
  return win;
}

globalThis.window = makeWindow();
globalThis.Event = class { constructor(type) { this.type = type; } };

const sel = await import("../frontend/src/lib/selection.ts");

function reset(href = "http://localhost:3110/") {
  globalThis.window = makeWindow(href);
}

const NOTICE = "g2b-R26BK01707959-000"; // 늘 목록에 있는 시연용 고정 공고(28차 — 9-29 캐시 교체로 1718694 가 빠짐)
const OTHER_NOTICE = "g2b-R26BK01704406-000"; // 두 번째 시연용 고정 공고
const SUPPORT = "bizinfo-PBLN_000000000112345";

// ---------------------------------------------------------------------------

console.log("A · 나라장터 공고 선택");
reset();
sel.writeSelection(NOTICE, "push");
check("주소에 ?notice= 가 붙는다", new URL(window.location.href).searchParams.get("notice"), NOTICE);
check("저장값도 같이 남는다", window.localStorage.getItem("bidpilot.notice.v1"), NOTICE);
check("지금 열어야 할 것", sel.readSelection(), NOTICE);

console.log("\nB · 새로고침 (주소만 들고 다시 켠다)");
{
  const href = window.location.href;
  reset(href);
  check("같은 입찰이 열린다", sel.readSelection(), NOTICE);
}

console.log("\nC · 기업마당 지원사업 선택");
reset();
sel.writeSelection(NOTICE, "push");
sel.writeSelection(SUPPORT, "push");
check("주소에 ?support= 가 붙는다", new URL(window.location.href).searchParams.get("support"), SUPPORT);
check("?notice= 는 주소에서 빠진다", new URL(window.location.href).searchParams.get("notice"), null);
check("지금 열어야 할 것은 지원사업", sel.readSelection(), SUPPORT);
check("**입찰 저장값은 오염되지 않는다**", window.localStorage.getItem("bidpilot.notice.v1"), NOTICE);
check("지원사업은 자기 저장소에", window.localStorage.getItem("bidpilot.support.v1"), SUPPORT);
check("상단 네비게이션이 실어 나르는 값은 여전히 입찰", sel.readSelectedNotice(), NOTICE);

console.log("\nD · 지원사업 링크를 새 탭에서 열기");
{
  const shared = window.location.href;
  reset(shared);
  check("같은 지원사업이 열린다", sel.readSelection(), SUPPORT);
  check("저장값이 비어 있어도 주소가 이긴다", window.localStorage.getItem("bidpilot.support.v1"), null);
}

console.log("\nE · 뒤로가기 · 앞으로가기");
reset();
sel.writeSelection(NOTICE, "push");
sel.writeSelection(SUPPORT, "push");
sel.writeSelection(OTHER_NOTICE, "push");
check("지금은 두 번째 입찰", sel.readSelection(), OTHER_NOTICE);
window.history.back();
check("뒤로 → 지원사업", sel.readSelection(), SUPPORT);
window.history.back();
check("뒤로 → 첫 입찰", sel.readSelection(), NOTICE);
window.history.forward();
check("앞으로 → 지원사업", sel.readSelection(), SUPPORT);
{
  let notified = 0;
  const stop = sel.subscribeSelection(() => { notified += 1; });
  window.history.back();
  stop();
  check("뒤로가기가 구독자에게 알려진다", notified > 0, true);
}

console.log("\nF · 메뉴 링크는 입찰만 싣는다 · 요구사항 정리표는 사업기회 탭 (28차 §3-C)");
check("사업계획서 작성에 입찰을 싣는다", sel.hrefWithNotice("/plan", NOTICE), `/plan?notice=${encodeURIComponent(NOTICE)}`);
check("합성 데모는 싣지 않는다", sel.hrefWithNotice("/plan", "synthetic-rfp-0001"), "/plan");
check("옛 /rfp 는 더 이상 싣지 않는다(넘김 주소)", sel.hrefWithNotice("/rfp", NOTICE), "/rfp");
check("정리표 주소 = 사업기회 탭", sel.requirementSheetHref(NOTICE), `/opportunities?tab=sheet&notice=${encodeURIComponent(NOTICE)}`);
check("정리표 주소에 요구사항", sel.requirementSheetHref(NOTICE, "REQ-003"), `/opportunities?tab=sheet&notice=${encodeURIComponent(NOTICE)}&req=REQ-003`);
check("회사자료 화면에는 붙이지 않는다", sel.hrefWithNotice("/company", NOTICE), "/company");
check("지원사업 id 는 애초에 입찰 저장값이 될 수 없다", (() => {
  reset();
  sel.writeSelectedNotice(SUPPORT);
  return window.localStorage.getItem("bidpilot.notice.v1");
})(), null);

console.log("\nG · 종류 판정 · 데모 처리");
check("bizinfo- 는 지원사업", sel.isSupportProgramId(SUPPORT), true);
check("g2b- 는 입찰", sel.isSupportProgramId(NOTICE), false);
check("null 은 입찰로 본다", sel.selectionKindOf(null), "notice");
{
  reset();
  sel.writeSelection(NOTICE, "push");
  sel.writeSelection("synthetic-rfp-0001", "push");
  check("합성 데모는 저장하지 않는다", window.localStorage.getItem("bidpilot.notice.v1"), null);
  check("합성 데모는 주소에도 남지 않는다", new URL(window.location.href).searchParams.get("notice"), null);
}

console.log("\nH · 쿼리 없이 `/` 로 돌아왔을 때 마지막에 본 것을 연다");
{
  reset();
  sel.writeSelection(NOTICE, "push");
  sel.writeSelection(SUPPORT, "push");
  const store = window._store;
  reset();                                   // 주소는 깨끗한 `/`
  for (const [k, v] of store) window.localStorage.setItem(k, v);
  check("마지막이 지원사업이었으면 지원사업", sel.readSelection(), SUPPORT);
  sel.clearSelectedSupport();
  check("지원사업을 닫으면 입찰로 돌아간다", sel.readSelection(), NOTICE);
}

console.log("\nI · 지원사업 화면(`/support/<id>`)은 저장소에만 남긴다 (27차 LNK-01)");
{
  reset("http://localhost:3110/support/" + SUPPORT);
  window.localStorage.setItem("bidpilot.notice.v1", NOTICE);   // 그 전에 입찰을 보고 있었다
  sel.rememberSupport(SUPPORT);
  check("주소는 그대로", window.location.href, "http://localhost:3110/support/" + SUPPORT);
  check("지금 보는 것 = 이 지원사업", sel.readSelection(), SUPPORT);
  check("입찰 저장값은 그대로 (정리표 탭 · 메뉴가 싣는 값)", sel.readSelectedNotice(), NOTICE);
  sel.rememberSupport(NOTICE);
  check("입찰 id 는 지원사업 저장값이 될 수 없다", window.localStorage.getItem("bidpilot.support.v1"), SUPPORT);
}

console.log("\nJ · 목록 ↔ 레이더 링크가 조건을 싣는다 (27차 LNK-09)");
check(
  "고른 조건만 싣는다",
  sel.hrefWithConditions("/radar", { src: "g2b", track: "all", sort: "deadline", closed: true }),
  "/radar?src=g2b&sort=deadline&closed=1",
);
// 37차 §3-C — 기본 정렬은 회사 방식(sort null)이라 주소에 쓰지 않는다. 「점수순」을 고른 것은 회사 기본이 실무순일 수 있어 남긴다.
check("기본 조건이면 주소가 깨끗하다", sel.hrefWithConditions("/opportunities", { src: "all", track: "all", sort: null, closed: false }), "/opportunities");
check("고른 정렬은 회사 기본과 같아 보여도 싣는다", sel.hrefWithConditions("/opportunities", { src: "all", track: "all", sort: "priority", closed: false }), "/opportunities?sort=priority");

console.log(`\n${failed === 0 ? "✓" : "✗"} 선택 상태 검사 — 통과 ${passed} · 실패 ${failed}`);
process.exit(failed === 0 ? 0 : 1);
