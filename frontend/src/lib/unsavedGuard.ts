"use client";

/**
 * 작성 중인 글이 말없이 사라지지 않게 한다 (ISSUE-010 · TASK-012).
 *
 * ## 무엇이 문제였나
 *
 * GO/HOLD 사유, 조건 메모, 조치 근거, 해결 처리 메모가 공고 전환·회사 전환·새로고침·
 * 탭 닫기에서 **아무 말 없이** 지워졌다. 확인 창은 검토 텍스트와 붙여넣기 두 곳뿐이었고
 * `beforeunload` 는 한 곳도 없었다.
 *
 * 담당자는 「아까 쓴 사유 어디 갔지?」가 된다. 그 사유는 나중에 「왜 참여하지 않기로
 * 했는가」를 설명하는 유일한 기록이다.
 *
 * ## 두 겹으로 막는다
 *
 * 1. **묻는다** — 탭을 닫거나 새로고침하면 브라우저가 묻고(`beforeunload`),
 *    공고·회사를 바꾸면 우리가 묻는다(`confirmDiscard`).
 * 2. **남긴다** — 그래도 사라질 수 있으므로 긴 입력은 localStorage 에 임시 저장하고
 *    (`loadDraft`/`saveDraft`) 돌아오면 복원한다. 저장에 성공하면 지운다.
 *
 * 둘 중 하나만으로는 부족하다. 묻기만 하면 브라우저가 죽었을 때 잃고,
 * 남기기만 하면 담당자가 사라진 줄 알고 다시 쓴다.
 *
 * ## 왜 전역 레지스트리인가
 *
 * 입력은 서로 다른 화면·패널에 흩어져 있고, 전환을 감지하는 곳(대시보드 훅)은 그것들을
 * 알지 못한다. 컴포넌트마다 prop 을 내리면 그 사이 컴포넌트를 전부 손봐야 한다.
 * 「지금 저장 안 된 글이 있는가」는 화면 전체에 하나뿐인 사실이라 모듈 수준에 둔다.
 */

import { requestConsent } from "@/lib/consentPrompt";

const dirty = new Set<string>();
const DRAFT_PREFIX = "bidpilot.draft.";

/**
 * 담당자가 이름을 적어 두는 칸의 기억값. 임시 저장본과 함께 지워야 할 대상이다 (N3).
 * 값 자체는 `GatePanel`·`DetailPanel` 이 쓰고, 여기서는 «로그아웃 때 지울 것» 목록으로만 안다.
 */
export const REVIEWER_STORAGE_KEY = "bidpilot.reviewer.v1";

/**
 * 임시 저장본을 **사람별로** 나눈다 (N3).
 *
 * 공용 PC 에서 A 가 결정 사유를 쓰다 말고 로그아웃하면, 다음에 앉은 B 가 같은 공고를 열었을 때
 * A 가 쓰던 글이 그대로 떴다. 회사 프로필 편집은 **폼 전체**가 되살아난다. 열람자 계정이
 * 편집자의 초안을 읽는 셈이다.
 *
 * 그래서 키에 계정 아이디를 넣는다. 표시 전용 쿠키에서 읽으므로 **권한 판정이 아니다** —
 * 이름표일 뿐이고, 고쳐 봐야 자기 초안이 안 보이게 될 뿐이다. 게이트가 꺼진 로컬은 `local`.
 */
function currentOwner(): string {
  try {
    const raw = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith("bidpilot_user="));
    if (!raw) return "local";
    const parsed: unknown = JSON.parse(decodeURIComponent(raw.slice("bidpilot_user=".length)));
    const user = parsed && typeof parsed === "object" ? (parsed as { u?: unknown }).u : null;
    // 키에 쓰는 값이라 모양을 좁힌다. 이상하면 `local` 로 떨어뜨린다 — 섞이는 것보다 낫다.
    return typeof user === "string" && /^[A-Za-z0-9._-]{1,64}$/.test(user) ? user : "local";
  } catch {
    return "local";
  }
}

/** 저장소에 들어갈 실제 키. `bidpilot.draft.<사람>.<칸>` */
function storageKey(key: string): string {
  return `${DRAFT_PREFIX}${currentOwner()}.${key}`;
}

/**
 * 이 브라우저에 남은 임시 저장본과 담당자 기억값을 **전부** 지운다 (N3).
 *
 * 로그아웃할 때 부른다. 내 것만 지우지 않고 전부 지우는 이유: 공용 PC 에서 로그아웃은
 * 「다음 사람에게 넘긴다」는 뜻이다. 남의 초안이 남아 있을 이유가 없다.
 */
export function clearAllDrafts(): void {
  dirty.clear();
  try {
    const doomed: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const name = window.localStorage.key(i);
      if (name && (name.startsWith(DRAFT_PREFIX) || name === REVIEWER_STORAGE_KEY)) doomed.push(name);
    }
    for (const name of doomed) window.localStorage.removeItem(name);
  } catch {
    // 저장소를 못 쓰는 브라우저 — 지울 것도 없다.
  }
}

let listenerAttached = false;

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (dirty.size === 0) return;
  // 문구는 브라우저가 정한다 — 우리 문장은 무시된다. preventDefault 가 「묻기」의 신호다.
  event.preventDefault();
  event.returnValue = "";
}

function ensureListener(): void {
  if (listenerAttached || typeof window === "undefined") return;
  window.addEventListener("beforeunload", onBeforeUnload);
  listenerAttached = true;
}

/** 이 칸에 저장 안 된 글이 있는가를 알린다. `false` 면 표시를 지운다. */
export function markDirty(key: string, isDirty: boolean): void {
  ensureListener();
  if (isDirty) dirty.add(key);
  else dirty.delete(key);
}

/** 저장 안 된 글이 하나라도 있는가. */
export function hasUnsaved(): boolean {
  return dirty.size > 0;
}

/** 호출한 쪽이 이미 물어 「떠난다」고 정했을 때 표시만 정리한다(임시 저장본은 그대로 · 2.0.6 — 두 번 묻지 않게). */
export function forgetUnsaved(): void {
  dirty.clear();
}

/**
 * 화면을 떠나기 전에 묻는다. 저장 안 된 글이 없으면 묻지 않고 `true`.
 *
 * `true` 를 돌려주면 호출한 쪽이 이동해도 된다는 뜻이며, 이동하기로 했으므로
 * 여기서 표시를 정리한다.
 */
export function confirmDiscard(what = "작성 중인 내용"): boolean {
  if (dirty.size === 0) return true;
  const ok = window.confirm(`저장하지 않은 ${what}이 있습니다. 화면을 옮기면 사라집니다.\n\n계속할까요?`);
  if (ok) dirty.clear();
  return ok;
}

/**
 * 로그아웃 전에 묻는다(43차 M28). 로그아웃은 공용 PC 보호로 임시 저장본을 모두 지운다 — 지우는 것은 그대로 두고, 저장 안 된 글이 있으면 먼저 묻는다.
 */
export async function confirmSignOut(): Promise<boolean> {
  if (dirty.size === 0) return true;
  // 45차 L5 — 화면 안 확인 창(브라우저 기본 창은 앱과 모양이 다르고 녹화에 안 잡혔다)
  return requestConsent({
    title: "로그아웃할까요?",
    body: "저장하지 않은 글이 있습니다. 로그아웃하면 이 PC 에 임시로 남긴 글도 지웁니다(공용 PC 보호).",
    confirmLabel: "로그아웃",
    cancelLabel: "그만두기",
  });
}

/** 저장에 성공했을 때. 표시와 임시 저장본을 함께 지운다. */
export function clearDraft(key: string): void {
  markDirty(key, false);
  try {
    window.localStorage.removeItem(storageKey(key));
  } catch {
    // 저장소를 못 쓰는 브라우저 — 임시 저장만 못 할 뿐 화면은 그대로 동작한다.
  }
}

/** 긴 입력을 임시 저장한다. 빈 값이면 지운다. */
export function saveDraft(key: string, value: string): void {
  markDirty(key, value.trim().length > 0);
  try {
    if (value.trim().length === 0) window.localStorage.removeItem(storageKey(key));
    else window.localStorage.setItem(storageKey(key), value);
  } catch {
    // 무시 — 임시 저장은 보조 수단이다.
  }
}

/** 임시 저장본을 읽는다. 없으면 빈 문자열. */
export function loadDraft(key: string): string {
  try {
    return window.localStorage.getItem(storageKey(key)) ?? "";
  } catch {
    return "";
  }
}
