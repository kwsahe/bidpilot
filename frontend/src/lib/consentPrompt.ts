/**
 * 화면 안 확인 창 한 곳 — 브라우저 기본 확인 창(`window.confirm`)을 쓰지 않는다(28차 §A-6).
 *
 * `lib/api` 처럼 React 밖에서도 「사람에게 물어보고 답을 기다린다」를 부를 수 있게 약속(Promise)으로 준다.
 * 답은 루트 레이아웃의 `ConsentHost`(components/ui/ConsentHost.tsx)가 `Modal` 로 받는다.
 * 창을 그릴 곳이 없으면(검사 · 서버) **묻지 않고 거절** — 받기 요청이 하나도 나가지 않는다.
 */

export interface ConsentRequest {
  title: string;
  /** 무엇을 하는가 — 한두 문장 */
  body: string;
  fileName?: string;
  size?: string;
  confirmLabel: string;
  cancelLabel?: string;
}

type Pending = { request: ConsentRequest; resolve: (ok: boolean) => void };

let pending: Pending | null = null;
let hosts = 0;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function subscribeConsent(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function readConsent(): ConsentRequest | null {
  return pending?.request ?? null;
}

/** 루트에 창이 붙어 있는가 — 붙은 동안만 묻는다. */
export function registerConsentHost(): () => void {
  hosts += 1;
  return () => {
    hosts -= 1;
    if (hosts === 0) answerConsent(false);
  };
}

export function requestConsent(request: ConsentRequest): Promise<boolean> {
  if (hosts === 0) return Promise.resolve(false);
  // 앞의 질문이 남아 있으면 거절로 닫고 새로 묻는다(두 창이 겹치지 않게)
  answerConsent(false);
  return new Promise<boolean>((resolve) => {
    pending = { request, resolve };
    emit();
  });
}

export function answerConsent(ok: boolean): void {
  const current = pending;
  if (!current) return;
  pending = null;
  current.resolve(ok);
  emit();
}
