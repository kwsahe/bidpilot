"use client";

/**
 * 세션이 끝났거나 곧 끝날 때의 띠 (43차 M28).
 *
 * 세션은 로그인 때부터 12시간이고 늘어나지 않는다. 밤새 열어 둔 탭에서 직접 넣기 다섯 칸을 채우고 저장하면
 * 「로그인이 필요합니다.」 한 줄만 떴고, 다시 로그인하려고 새로 고치면 붙여 넣은 글과 폼이 사라졌다.
 *
 * - 401 을 받으면(`SESSION_EXPIRED_EVENT`) 「세션이 끝났습니다 — 새 탭에서 다시 로그인」. 이 화면은 그대로 둔다 —
 *   새 탭에서 로그인하면 쿠키가 같아 이 탭에서 다시 누르면 저장된다.
 * - 만료 5분 전이면 「곧 끝납니다 — 쓰던 글을 먼저 저장하세요」(표시 쿠키의 만료 시각 · 서버는 이 값을 믿지 않는다).
 * - 게이트가 없는 로컬은 그리지 않는다.
 */

import { useEffect, useState } from "react";

import { SESSION_EXPIRED_EVENT } from "@/lib/api";
import { readCurrentUser, useCurrentUser } from "@/lib/currentUser";
import { useDeploymentMode } from "@/lib/useDeploymentMode";

const WARN_BEFORE_MS = 5 * 60_000;

function loginHref(): string {
  const here = typeof window === "undefined" ? "/" : `${window.location.pathname}${window.location.search}`;
  return `/login?next=${encodeURIComponent(here)}`;
}

export function SessionHost() {
  const mode = useDeploymentMode();
  const me = useCurrentUser();
  // 401 을 받은 때의 만료 시각 — 새 탭에서 다시 로그인해 만료 시각이 바뀌면 띠를 내린다
  const [lost, setLost] = useState<{ exp: number | null; disabled: boolean } | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState<number | null>(null);

  useEffect(() => {
    const onLost = (event: Event) => {
      const detail = event instanceof CustomEvent && typeof event.detail === "string" ? event.detail : "";
      setLost({ exp: readCurrentUser()?.expiresAt ?? null, disabled: detail.startsWith("계정이 꺼졌습니다") });
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onLost);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onLost);
  }, []);

  useEffect(() => {
    // 30초마다 다시 그린다 — 표시 쿠키(로그인 · 다시 로그인)와 남은 시간을 다시 읽는다
    const tick = () => setNow(Date.now());
    tick();
    const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, []);

  if (!mode?.gated || now === null) return null;
  const exp = me?.expiresAt ?? null;
  const relogged = exp !== null && exp > now && (lost === null || exp !== lost.exp);
  const expired = (lost !== null && !relogged) || (exp !== null && exp <= now);
  const warn = !expired && exp !== null && exp - now <= WARN_BEFORE_MS && dismissed !== exp;
  if (!expired && !warn) return null;

  const minutes = exp !== null ? Math.max(1, Math.ceil((exp - now) / 60_000)) : 0;
  return (
    <div
      role={expired ? "alert" : "status"}
      data-session-banner={expired ? "expired" : "warn"}
      className="fixed inset-x-3 bottom-3 z-[60] mx-auto flex max-w-2xl flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-cosmos-amber/60 bg-cosmos-panel px-4 py-3 text-[14px] leading-6 text-cosmos-text shadow-lg"
    >
      <span className="min-w-0 flex-1">
        {expired && lost?.disabled
          ? "계정이 꺼졌습니다 — 관리자에게 문의하세요. 다시 로그인해도 들어갈 수 없습니다(쓰던 글은 이 화면에 그대로 있습니다)."
          : expired
          ? "세션이 끝났습니다 — 쓰던 글은 이 화면에 그대로 있습니다. 새 탭에서 다시 로그인한 뒤 이 화면으로 돌아와 다시 저장하세요."
          : `세션이 ${minutes}분 안에 끝납니다 — 쓰던 글을 먼저 저장하세요(끝나도 이 화면의 글은 남고, 새 탭에서 다시 로그인하면 이어서 저장할 수 있습니다).`}
      </span>
      {!(expired && lost?.disabled) && (
        <a href={loginHref()} target="_blank" rel="noopener" className="mc-focus shrink-0 rounded font-medium text-cosmos-cyan hover:underline">
          새 탭에서 다시 로그인 ↗
        </a>
      )}
      {!expired && exp !== null && (
        <button type="button" className="mc-focus shrink-0 rounded text-cosmos-muted hover:text-cosmos-text" onClick={() => setDismissed(exp)}>
          닫기
        </button>
      )}
    </div>
  );
}
