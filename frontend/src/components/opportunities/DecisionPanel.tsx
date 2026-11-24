"use client";

/**
 * 신청 · 참여 결정(44차 M4 · BIZ-08 · Q11) — 기업마당 · 직접 넣은 공고에도 나라장터 결정과 **같은 꼴**(결정 · 사유 · 누가 · 언제)을 남긴다.
 * 지원금(수혜)은 「신청 · 검토 중 · 신청 안 함」, 입찰 · 수행기관 모집(매출)은 「참여 · 보류 · 참여 안 함」(서버 `decision_service` 와 같은 낱말).
 * 사람이 고른다 — 프로그램은 결정하지 않는다. 그사이 남이 정했으면 409 · 열람자는 보기만.
 */

import { useEffect, useState } from "react";

import StaleReload from "@/components/ui/StaleReload";
import { Button, InlineAlert } from "@/components/ui/primitives";
import { getDecision, isStaleWrite, saveDecision } from "@/lib/api";
import { formatDateTime } from "@/lib/cosmos/format";
import { currentUserName } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import { analysisContext } from "@/lib/organization";
import { DECISION_LABELS, SUPPORT_DECISION_LABELS } from "@/lib/scoreNames";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import type { BidDecision, DecisionStatus } from "@/types/gate";

const INPUT =
  "mc-focus min-h-9 w-full rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[13px] text-cosmos-text";

export default function DecisionPanel({
  targetId,
  organizationId,
  support,
  onSaved,
}: {
  targetId: string;
  organizationId: string;
  /** 지원금(수혜)이면 신청 낱말 · 아니면 참여 낱말. */
  support: boolean;
  /** 저장 뒤 — 목록의 「결정:」 줄을 새 값으로 다시 읽는다(45차 M13). */
  onSaved?: () => void;
}) {
  const labels = support ? SUPPORT_DECISION_LABELS : DECISION_LABELS;
  const viewer = useViewerLock();
  const [decision, setDecision] = useState<BidDecision | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  // 2.0.6 — 읽는 중 · 읽기 실패를 가른다. 실패도 null 이라 「검토 전」으로 보였고(목록 · 이번 주 할 일은 「결정: 신청」), 그대로 누르면
  // 아무도 안 바꿨는데 「먼저 바꿨습니다」(409)가 났다. 결정을 읽기 전에는 단추를 잠근다.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const loadKey = `${targetId}|${organizationId}|${reloadTick}`;

  useEffect(() => {
    let alive = true;
    getDecision(targetId, analysisContext(targetId, organizationId))
      .then((value) => {
        if (!alive) return;
        setDecision(value);
        setLoadError(null);
        setLoadedKey(loadKey);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setDecision(null);
        setLoadError(describeFailure(e));
        setLoadedKey(loadKey);
      });
    return () => {
      alive = false;
    };
  }, [targetId, organizationId, loadKey]);
  const loaded = loadedKey === loadKey;
  const locked = busy || !loaded || loadError !== null;

  const save = async (status: DecisionStatus) => {
    if (status !== "UNREVIEWED" && !reason.trim()) {
      setError("사유를 한 줄 적어 주세요(예: 지원 대상이 맞음 · 자부담이 커서 안 함).");
      return;
    }
    setBusy(true);
    setError(null);
    setStale(false);
    try {
      const saved = await saveDecision(
        targetId,
        {
          status,
          reasons: status === "UNREVIEWED" ? [] : [reason.trim()],
          decided_by: currentUserName() || "담당자",
          expected_decided_at: decision?.decided_at ?? null,
        },
        analysisContext(targetId, organizationId),
      );
      setDecision(saved);
      setReason("");
      onSaved?.();
    } catch (e: unknown) {
      setStale(isStaleWrite(e));
      setError(describeFailure(e, "결정을 저장하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  const status = decision?.status ?? "UNREVIEWED";
  const decided = status !== "UNREVIEWED";
  return (
    <section className="mc-panel flex flex-col gap-2 p-3" aria-label={support ? "신청 여부 결정" : "참여 결정"} data-decision-panel>
      <p className="text-[13px] text-cosmos-secondary">
        <strong className="text-cosmos-text">{support ? "신청 여부" : "참여 결정"}</strong> —{" "}
        {!loaded ? (
          <span role="status">저장된 결정을 읽는 중…</span>
        ) : loadError ? (
          <span className="text-cosmos-amber" role="alert">
            저장된 결정을 읽지 못했습니다 — {loadError}{" "}
            <button type="button" className="mc-focus rounded font-medium text-cosmos-cyan underline" onClick={() => setReloadTick((n) => n + 1)}>
              다시 불러오기
            </button>
            {" "}(읽을 때까지 결정 단추를 잠급니다)
          </span>
        ) : decided ? (
          <>
            <strong className="text-cosmos-text">{labels[status]}</strong>
            {decision?.decided_by && ` · ${decision.decided_by}`}
            {decision?.decided_at && ` · ${formatDateTime(decision.decided_at)}`}
            {decision?.reasons?.length ? ` — ${decision.reasons.join(" · ")}` : ""}
          </>
        ) : (
          <span>{labels.UNREVIEWED}(사람이 정합니다 — 프로그램은 정하지 않습니다)</span>
        )}
      </p>
      {viewer ? (
        <p className="text-[12px] text-cosmos-muted" title={VIEWER_LOCK_REASON}>{VIEWER_LOCK_LABEL}</p>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            className={`${INPUT} sm:w-72`}
            aria-label="결정 사유"
            placeholder="사유 한 줄(필수)"
            value={reason}
            maxLength={200}
            onChange={(e) => setReason(e.target.value)}
          />
          {(["GO", "HOLD", "NO_GO"] as const).map((key) => (
            <Button key={key} size="sm" variant={key === "GO" ? "primary" : "secondary"} disabled={locked} onClick={() => void save(key)}>
              {labels[key]}
            </Button>
          ))}
          {decided && (
            <Button size="sm" variant="ghost" disabled={locked} onClick={() => void save("UNREVIEWED")}>
              {labels.UNREVIEWED}으로
            </Button>
          )}
          {/* 45차 M12 — 4초 동안 흐리기만 했다 */}
          {busy && <span className="text-[12px] text-cosmos-cyan" role="status">저장 중…</span>}
        </div>
      )}
      {error && (
        <InlineAlert tone="fail">
          {error}
          {stale && <StaleReload />}
        </InlineAlert>
      )}
    </section>
  );
}
