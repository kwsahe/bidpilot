"use client";

/**
 * 접속 상태와 로그아웃.
 *
 * 로그아웃 라우트(POST /api/logout)는 예전부터 있었는데 그것을 부르는 화면 요소가
 * 코드베이스에 하나도 없었다 — 로그인은 되는데 나갈 방법이 없는 상태였다.
 *
 * 게이트가 걸려 있을 때만 그린다. 로컬 개발처럼 게이트가 없으면 로그아웃할 것도 없다.
 * 이름은 대시보드 머리(TopBar)와 같이 「이름 · 역할」이다 — 직원별 계정이 생긴 뒤에도 「공용 접근계정으로 로그인됨」과
 * 「직원별 계정·권한은 아직 없습니다」를 적고 있었다 (CMN-07). 로그아웃이 실패하면 제자리에 이유를 적는다.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import PasswordChange from "@/components/ui/PasswordChange";
import { ROLE_LABELS, useCurrentUser } from "@/lib/currentUser";
import { accessLabel } from "@/lib/deploymentMode";
import { useDeploymentMode } from "@/lib/useDeploymentMode";
import { clearAllDrafts, confirmSignOut } from "@/lib/unsavedGuard";
import { clearSelectionMemory } from "@/lib/selection";

export function SessionControls() {
  const mode = useDeploymentMode();
  const router = useRouter();
  const me = useCurrentUser();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // 모드를 모르거나 게이트가 없으면 아무것도 그리지 않는다.
  if (!mode?.gated) return null;

  async function signOut() {
    if (!(await confirmSignOut())) return;  // 43차 M28 — 저장 안 된 글이 있으면 먼저 묻는다(45차 L5 화면 안 창)
    setBusy(true);
    setFailed(false);
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      // 이 브라우저에 남은 임시 저장본을 지운다 (N3). 공용 PC 에서 다음 사람이
      // 앞 사람의 결정 사유·조건 메모·회사 프로필 폼을 보는 것을 막는다.
      clearAllDrafts();
      clearSelectionMemory();
      router.replace("/login");
      router.refresh();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="hidden truncate text-[12px] text-cosmos-muted lg:inline" title={me ? `아이디 ${me.user}` : undefined}>
        {me ? `${me.displayName} · ${ROLE_LABELS[me.role]}` : accessLabel(mode)}
      </span>
      {me && <PasswordChange />}
      <button
        type="button"
        onClick={signOut}
        disabled={busy}
        className="mc-focus rounded-md border border-cosmos-border px-2 py-1 text-[12px] text-cosmos-secondary transition-colors hover:bg-cosmos-elevated disabled:opacity-50"
      >
        {busy ? "나가는 중…" : "로그아웃"}
      </button>
      {failed && (
        <span role="alert" className="text-[12px] text-cosmos-red">
          로그아웃하지 못했습니다 — 다시 눌러 주세요
        </span>
      )}
    </span>
  );
}
