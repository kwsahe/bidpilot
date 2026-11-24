/**
 * 화면 밝기 — 어두운 화면(기본 · 지금 그대로) · 밝은 화면 (2.4.0 ⑥ · 대표 11-04 「2단계 진행」).
 *
 * - 둘뿐이다. 시스템 라이트/다크 설정은 따라가지 않는다.
 * - **기억한다** — `localStorage['bidpilot.theme.v1']`(이 기기 · 이 브라우저). 보기(쉬운 · 전체)를 기억하지 않는 37차 결정은
 *   보기 모드 이야기이고, 화면 밝기는 눈 · 기기 설정이라 다르게 둔다. 로그아웃이 지우지 않는다.
 * - 첫 그림 깜빡임 방지: 루트 layout 의 <head> 인라인 스크립트(`THEME_INIT_SCRIPT`)가 그리기 전에 <html data-theme> 를 바꾼다
 *   (Next 16 안내 preventing-flash-before-hydration § Themes). 쿠키 · cookies() 는 쓰지 않는다(정적 렌더 유지).
 * - 이 파일은 React 를 import 하지 않는다 — 서버 컴포넌트(layout)가 스크립트 글을 가져간다. 훅 `useTheme` 은 `components/ui/ThemeToggle.tsx`.
 */

export type Theme = "dark" | "light";

export const THEME_KEY = "bidpilot.theme.v1";

/** <head> 인라인 스크립트 — 저장 값이 'light' 일 때만 붙인다(기본 어두운 화면은 layout 의 data-theme="dark" 그대로). */
export const THEME_INIT_SCRIPT = `(function(){try{if(localStorage.getItem(${JSON.stringify(THEME_KEY)})==="light")document.documentElement.setAttribute("data-theme","light")}catch(e){}})()`;

const listeners = new Set<() => void>();
/** 이 페이지에서 정한 값 — 처음 읽을 때 저장소에서. 저장소를 못 쓰는 창에서도 이번 페이지 동안은 고른 값이 남는다. */
let cached: Theme | null = null;

export function readTheme(): Theme {
  if (cached) return cached;
  try {
    cached = window.localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    cached = "dark";
  }
  return cached;
}

/** <html data-theme> 에 붙인다. */
export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

/** 사람이 고른 값 — 속성 · 저장 · 구독자 알림. */
export function setTheme(theme: Theme): void {
  cached = theme;
  applyTheme(theme);
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // 저장 실패는 무시 — 이번 페이지에서만 바뀐다
  }
  for (const listener of listeners) listener();
}

export function subscribeTheme(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}
