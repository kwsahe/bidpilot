"use client";

/**
 * 회사 선택기 — 모든 화면이 이 부품 하나를 쓴다 (27차 §3-E-4 · 통일 점검 UNI-07 · LNK-13).
 *
 * 예전에는 화면마다 이름(「현재 회사」 · 「기준 회사」 · 「회사 변경」 · 이름 없음) · 항목(비활성 회사를
 * 거르는 곳과 안 거르는 곳) · 「(합성)」 꼬리표 · 바꿀 때 동작(대시보드만 확인)이 달랐다. 값은 모두 같은
 * 저장소라, 한 화면에서 말없이 바꾸면 대시보드 회사도 조용히 바뀌었다.
 *
 * - 이름 「회사」 하나 · 자리는 화면 머리 오른쪽 맨 앞(그다음 보기 전환 → 「?」).
 * - 항목: 활성 회사 + 지금 회사 · 합성 회사는 「(합성)」.
 * - 바꿀 때: 작성 중인 글이 있으면 언제나 묻고, 바꾸면 사라지는 결과가 있는 화면은 `loseMessage` 로 한 번 더 묻는다.
 */

import { organizationName, setOrganizationId } from "@/lib/organization";
import { confirmDiscard } from "@/lib/unsavedGuard";
import type { OrganizationListResponse } from "@/types/organization";

export function OrganizationPicker({
  list,
  organizationId,
  disabled = false,
  disabledReason,
  loseMessage = null,
  onChanged,
  id = "organization-picker",
}: {
  list: OrganizationListResponse | null;
  organizationId: string;
  disabled?: boolean;
  /** 막혀 있을 때 까닭 (예: 분석 중 · 발표 중) */
  disabledReason?: string;
  /** 바꾸면 사라지는 결과가 있을 때 묻는 말. 없으면 묻지 않는다 */
  loseMessage?: string | null;
  /** 바꾼 뒤 이 화면이 할 일 (선택 지우기 등) */
  onChanged?: (id: string) => void;
  id?: string;
}) {
  const options = (list?.organizations ?? []).filter(
    (o) => o.organization.status === "active" || o.organization.organization_id === organizationId,
  );
  const missing = list !== null && !options.some((o) => o.organization.organization_id === organizationId);
  const name = organizationName(list, organizationId);

  function change(next: string) {
    if (next === organizationId) return;
    // 작성 중인 글이 먼저다 — 결과는 다시 실행하면 되지만 쓴 글은 돌아오지 않는다.
    if (!confirmDiscard("작성 중인 내용")) return;
    if (loseMessage && !window.confirm(loseMessage)) return;
    setOrganizationId(next);
    onChanged?.(next);
  }

  return (
    <label htmlFor={id} className="flex min-w-0 shrink-0 items-center gap-1.5 text-[12px] text-cosmos-muted" data-organization-picker>
      회사
      <select
        id={id}
        value={organizationId}
        disabled={disabled}
        onChange={(event) => change(event.target.value)}
        title={disabled && disabledReason ? disabledReason : `${name} — 바꾸면 모든 화면이 이 회사 기준으로 바뀝니다`}
        className="mc-focus min-h-8 w-[160px] min-w-0 truncate rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-2 py-1 text-[12.5px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 disabled:cursor-not-allowed disabled:opacity-50 sm:w-[200px]"
      >
        {missing && <option value={organizationId}>{name} (등록되지 않음)</option>}
        {list === null && <option value={organizationId}>{name}</option>}
        {options.map((o) => (
          <option key={o.organization.organization_id} value={o.organization.organization_id}>
            {o.organization.display_name}
            {o.organization.data_class === "synthetic" ? " (가상 예시)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
