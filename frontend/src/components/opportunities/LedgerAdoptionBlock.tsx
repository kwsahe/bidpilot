"use client";

/**
 * 실적 원장 후보 · 채택 (45차 H5 — 43차 결정 3 의 빈 곳).
 *
 * AI 검색(회사 근거 연결)을 꺼 둔 회사는 실적 원장에서 분야 낱말로 맞춘 **후보(미채택)** 만 받는다. 「쓸 것을 골라 채택하세요」라고
 * 적어 놓고 고를 단추가 없었다. 요구사항 하나의 후보를 보이고 「채택」 · 「채택 취소」를 둔다 — 누가 · 언제를 남기고, 열람자는 잠근다.
 * 채택한 실적만 다음에 만드는 초안에 근거로 쓴다(이미 만든 초안은 그대로 — 다시 만들어야 반영).
 */

import { useState } from "react";

import { Badge, Button, InlineAlert } from "@/components/ui/primitives";
import { setLedgerAdoption, type LedgerView } from "@/lib/api";
import { formatDateTime } from "@/lib/cosmos/format";
import { currentUserName } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import { analysisContext, readOrganizationId } from "@/lib/organization";
import { useViewerLock, VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON } from "@/lib/viewerLock";

export function LedgerAdoptionBlock({
  noticeId,
  requirementId,
  ledger,
  onChanged,
}: {
  noticeId: string;
  requirementId: string;
  ledger: LedgerView | null;
  onChanged: (next: LedgerView) => void;
}) {
  const viewer = useViewerLock();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  if (!ledger?.ai_search_off) return null;
  const candidates = ledger.candidates.filter((c) => c.requirement_id === requirementId);

  const toggle = async (evidenceId: string, adopted: boolean) => {
    setBusy(evidenceId);
    setMessage(null);
    try {
      const next = await setLedgerAdoption(
        noticeId,
        { requirement_id: requirementId, evidence_id: evidenceId, adopted, by: currentUserName() || "담당자" },
        analysisContext(noticeId, readOrganizationId()),
      );
      onChanged(next);
      setMessage({ tone: "info", text: adopted ? "채택했습니다 — 다음에 만드는 초안부터 이 실적을 근거로 씁니다." : "채택을 취소했습니다." });
    } catch (error: unknown) {
      setMessage({ tone: "error", text: describeFailure(error, "채택을 저장하지 못했습니다.") });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="flex flex-col gap-2" id={`ledger-${requirementId}`} data-ledger-block>
      <h3 className="flex items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
        실적 원장 후보 {candidates.length}
        {viewer && <Badge tone="muted" title={VIEWER_LOCK_REASON}>{VIEWER_LOCK_LABEL}</Badge>}
      </h3>
      {candidates.length === 0 ? (
        <p className="rounded-lg border border-dashed border-cosmos-border-strong px-3 py-2 text-[12.5px] leading-5 text-cosmos-muted">
          이 요구사항에 맞는 실적 원장 후보가 없습니다 — 근거 없이 「충족」으로 표시하지 않습니다.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {candidates.map((c) => (
            <li key={c.evidence_id} className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 text-[13px] font-medium text-cosmos-text">{c.document_name}</span>
                {c.adopted ? (
                  <Badge tone="ok">채택 · {c.adopted.by} · {formatDateTime(c.adopted.at)}</Badge>
                ) : (
                  <Badge tone="muted">후보(미채택)</Badge>
                )}
                {!viewer && ledger.editable && (
                  <Button
                    size="sm"
                    variant={c.adopted ? "ghost" : "secondary"}
                    disabled={busy !== null}
                    onClick={() => void toggle(c.evidence_id, !c.adopted)}
                  >
                    {busy === c.evidence_id ? "저장 중…" : c.adopted ? "채택 취소" : "채택"}
                  </Button>
                )}
              </div>
              <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">“{c.source_text}”</p>
            </li>
          ))}
        </ul>
      )}
      <p className="text-[12px] leading-5 text-cosmos-muted">
        분야 낱말로 맞춘 후보입니다 — 실제로 이 요구사항에 맞는 실적인지 보고 고르세요. 채택한 실적만 다음에 만드는 초안의 근거 문장이 됩니다.
      </p>
      {message && (
        <InlineAlert tone={message.tone === "error" ? "fail" : "info"} role="status">
          {message.text}
        </InlineAlert>
      )}
    </section>
  );
}
