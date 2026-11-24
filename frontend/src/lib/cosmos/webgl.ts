/**
 * WebGL 지원 여부 감지. 결과는 모듈 단위로 캐시한다.
 * 서버에서는 항상 false, 클라이언트에서는 mount 이후(useSyncExternalStore)에만 값이 확정된다.
 */

import { useSyncExternalStore } from "react";

let cached: boolean | null = null;

export function supportsWebGL(): boolean {
  if (cached !== null) return cached;
  if (typeof window === "undefined" || typeof document === "undefined") {
    return false;
  }
  try {
    if (!("WebGLRenderingContext" in window)) {
      cached = false;
      return cached;
    }
    const canvas = document.createElement("canvas");
    const context =
      canvas.getContext("webgl2") ??
      canvas.getContext("webgl") ??
      canvas.getContext("experimental-webgl");
    cached = context !== null;
    // 감지용 컨텍스트는 즉시 해제해 실제 3D 캔버스와 경쟁하지 않게 한다.
    if (
      context instanceof WebGLRenderingContext ||
      context instanceof WebGL2RenderingContext
    ) {
      context.getExtension("WEBGL_lose_context")?.loseContext();
    }
  } catch {
    cached = false;
  }
  return cached;
}

const subscribeNoop = () => () => {};
const getServerSnapshot = (): boolean | null => null;

/** null = 아직 감지 전(서버 렌더/하이드레이션), boolean = 감지 완료. */
export function useWebGLSupport(): boolean | null {
  return useSyncExternalStore(subscribeNoop, supportsWebGL, getServerSnapshot);
}
