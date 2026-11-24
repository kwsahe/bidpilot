"use client";

/**
 * 「다시 불러오기」 — 저장이 409 「○○ 님이 먼저 바꿨습니다」에 막혔을 때 그 자리에 붙인다(43차 M25 · 44차 TEAM-R36-01 · 07).
 * 지금 고친 것(임시 저장본 포함)을 버리고 새 값을 읽는다 — 남의 저장을 덮지 않게.
 */

import { clearDraft } from "@/lib/unsavedGuard";

export default function StaleReload({ draftKeys = [] }: { draftKeys?: string[] }) {
  return (
    <>
      {" "}
      <button
        type="button"
        className="mc-focus rounded font-medium underline"
        data-stale-reload
        onClick={() => {
          draftKeys.forEach((key) => clearDraft(key));
          window.location.reload();
        }}
      >
        다시 불러오기
      </button>{" "}
      (지금 고친 것은 버려집니다 — 새 값에서 다시 고치세요)
    </>
  );
}
