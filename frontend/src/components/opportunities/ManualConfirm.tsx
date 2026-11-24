"use client";

/**
 * 직접 넣은 공고 한 줄의 사람 몫(44차 M4 · M6).
 *
 * - 신청 · 참여 결정 — 나라장터 결정과 같은 꼴(`DecisionPanel`). 수혜는 「신청 · 검토 중 · 신청 안 함」, 입찰 · 수행은 「참여 · 보류 · 참여 안 함」.
 * - 「원문 확인함 — 가능으로」(D16 · SOURCE-09) — 편집자 · 관리자만. 누가 · 한 줄 이유 필수 · 되돌리기 · 그사이 남이 고쳤으면 409 ·
 *   활동 기록에 남는다. 규칙에 불가 줄이 있으면 단추가 없다(서버도 거절). 자동으로는 여전히 「가능」이 아니다.
 */

import { useState } from "react";

import DecisionPanel from "@/components/opportunities/DecisionPanel";
import StaleReload from "@/components/ui/StaleReload";
import { Button } from "@/components/ui/primitives";
import { clearManualHumanPass, isStaleWrite, setManualHumanPass } from "@/lib/api";
import { formatDateTime } from "@/lib/cosmos/format";
import { currentUserName } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import type { ManualNotice } from "@/types/manual";
import type { UnifiedOpportunity } from "@/types/opportunity";

const FIELD =
  "mc-focus min-h-9 rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[13px] text-cosmos-text";
const LINK = "mc-focus rounded text-[14px] text-cosmos-cyan hover:underline";

export default function ManualConfirm({
  organizationId,
  raw,
  item,
  viewer,
  onChanged,
}: {
  organizationId: string;
  raw: ManualNotice;
  item: UnifiedOpportunity;
  viewer: boolean;
  onChanged: () => void;
}) {
  const support = raw.recruit === "benefit";
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [form, setForm] = useState<{ reason: string; by: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  const run = async (task: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    setStale(false);
    try {
      await task();
      setForm(null);
      onChanged();
    } catch (e: unknown) {
      setStale(isStaleWrite(e));
      setError(describeFailure(e, "저장하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  const pass = raw.human_pass ?? null;
  return (
    <div className="flex flex-col gap-1.5 pt-1" data-manual-confirm>
      {item.decision_text && <p className="text-[13px] text-cosmos-secondary">결정: {item.decision_text}</p>}
      {pass ? (
        <p className="text-[13px] text-cosmos-teal" data-human-pass>
          사람 확인 뒤 가능 — {pass.by} · {formatDateTime(pass.at)} · {pass.reason}
          {!viewer && (
            <>
              {" "}
              <button type="button" className={LINK} disabled={busy} onClick={() => void run(() => clearManualHumanPass(organizationId, raw.id, currentUserName() || pass.by, raw.updated_at))}>
                되돌리기
              </button>
            </>
          )}
        </p>
      ) : (
        !viewer &&
        item.eligibility_gate !== "FAIL" &&
        (form ? (
          <span className="flex flex-wrap items-center gap-1.5">
            <input className={`${FIELD} w-64 max-w-full`} aria-label="확인한 이유" placeholder="이유 한 줄(필수 — 예: 원문 참가자격 · 지역 확인)" maxLength={200} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            <input className={`${FIELD} w-32`} aria-label="확인한 사람" placeholder="확인한 사람" maxLength={60} value={form.by} onChange={(e) => setForm({ ...form, by: e.target.value })} />
            <Button size="sm" variant="primary" disabled={busy || !form.reason.trim() || !form.by.trim()} onClick={() => void run(() => setManualHumanPass(organizationId, raw.id, { reason: form.reason.trim(), by: form.by.trim() }, raw.updated_at))}>
              「가능」으로
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setForm(null)}>그만두기</Button>
          </span>
        ) : (
          // 「참여 결정」처럼 줄 왼쪽에 — 맨 단추는 틀 폭으로 늘어나 가운데에 떴다(44차 화면 한 바퀴)
          <span>
            <button type="button" className={LINK} title="공고 원문을 직접 보고 자격이 맞는 것을 확인했을 때만 — 자동으로는 「가능」이 되지 않습니다" onClick={() => setForm({ reason: "", by: currentUserName() })}>
              원문 확인함 — 가능으로
            </button>
          </span>
        ))
      )}
      <span>
        <button type="button" className={LINK} onClick={() => setDecisionOpen((v) => !v)} aria-expanded={decisionOpen}>
          {decisionOpen ? "결정 닫기" : support ? "신청 여부 결정" : "참여 결정"}
        </button>
      </span>
      {decisionOpen && <DecisionPanel targetId={raw.id} organizationId={organizationId} support={support} onSaved={onChanged} />}
      {error && (
        <p className="text-[13px] text-cosmos-red-text" role="alert">
          {error}
          {stale && <StaleReload />}
        </p>
      )}
    </div>
  );
}
