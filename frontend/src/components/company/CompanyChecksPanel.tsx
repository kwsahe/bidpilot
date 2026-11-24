"use client";

/**
 * 회사 단위 한 번 확인(43차 결정 2) — 나라장터 「가능」에 닿는 길.
 *
 * 나라장터 입찰참가자격 등록 · 부정당 제재 없음 · 국세 · 지방세 체납 없음을 **사람이 등록증 · 조회 결과를 보고** 확인일 · 유효기간 ·
 * 확인한 사람과 함께 적는다. 셋이 유효하면 공고마다 되풀이하던 등록 · 결격 줄이 「통과(회사 확인 날짜)」가 되고, 유효기간이
 * 지나면 다시 「확인 필요 — 다시 확인」이다. 프로그램은 값을 고르지 않는다(빈 칸은 빈 칸 그대로).
 */

import { useState } from "react";

import { Button, InlineAlert } from "@/components/ui/primitives";
import StaleReload from "@/components/ui/StaleReload";
import { isStaleWrite, saveCompanyChecks } from "@/lib/api";
import { currentUserName } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import { analysisContext } from "@/lib/organization";
import { COMPANY_CHECK_LABELS, type CompanyCheck, type DeliveryCapacity } from "@/types/capability";

const INPUT =
  "mc-focus min-h-9 w-full rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[12.5px] text-cosmos-text";

type Draft = { confirmed_on: string; valid_until: string; confirmed_by: string };

function draftOf(check: CompanyCheck | undefined): Draft {
  return { confirmed_on: check?.confirmed_on ?? "", valid_until: check?.valid_until ?? "", confirmed_by: check?.confirmed_by ?? "" };
}

function todayKst(): string {
  return new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);
}

export default function CompanyChecksPanel({
  organizationId,
  capacity,
  readOnly,
  onSaved,
}: {
  organizationId: string;
  capacity: DeliveryCapacity;
  readOnly: boolean;
  onSaved: (saved: DeliveryCapacity) => void;
}) {
  const keys = Object.keys(COMPANY_CHECK_LABELS);
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(keys.map((key) => [key, draftOf(capacity.company_checks?.[key])])),
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const today = todayKst();

  function set(key: string, field: keyof Draft, value: string) {
    setDrafts((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));
  }

  async function submit(key: string, clear: boolean) {
    const draft = drafts[key];
    setMessage(null);
    setError(null);
    setStale(false);
    if (!clear && (!draft.confirmed_on || !draft.valid_until || !draft.confirmed_by.trim())) {
      setError(`${COMPANY_CHECK_LABELS[key]} — 확인일 · 유효기간 · 확인한 사람을 모두 적어 주세요.`);
      return;
    }
    setBusy(key);
    try {
      const saved = await saveCompanyChecks(
        { [key]: clear ? null : { ...draft, confirmed_by: draft.confirmed_by.trim() } },
        currentUserName() || draft.confirmed_by.trim() || "담당자",
        analysisContext("", organizationId),
        capacity.updated_at ?? null,  // 43차 M25 — 그사이 남이 저장했으면 서버가 막는다
      );
      setDrafts((prev) => ({ ...prev, [key]: draftOf(saved.company_checks?.[key]) }));
      onSaved(saved);
      setMessage(clear ? `${COMPANY_CHECK_LABELS[key]} 확인을 지웠습니다.` : `${COMPANY_CHECK_LABELS[key]}을(를) 저장했습니다. 목록을 새로고침하면 판정에 반영됩니다.`);
    } catch (e: unknown) {
      setStale(isStaleWrite(e));  // 44차 TEAM-R36-07 — 그사이 남이 저장했으면 그 자리에 「다시 불러오기」
      setError(describeFailure(e, "저장하지 못했습니다."));
    } finally {
      setBusy(null);
    }
  }

  const stored = capacity.company_checks ?? {};
  const allValid = keys.every((key) => stored[key] && stored[key].valid_until >= today);
  // 44차 대표 결정 1 — 「안 적음」으로 둔 회사 단위 확인은 「가능」으로 가는 길을 권하지 않는다(판정은 그대로 확인 필요)
  const leftBlank = (capacity.left_blank ?? []).includes("company_checks") && !allValid;

  return (
    <div className="flex flex-col gap-2 border-t border-cosmos-border pt-3" id="company-checks">
      {leftBlank ? (
        <p className="text-[12px] leading-5 text-cosmos-muted" data-company-checks-left-blank>
          <strong className="text-cosmos-text">회사 단위 확인 — 대표 결정으로 비워 둠</strong>. 판정은 그대로 「확인 필요」이고 나라장터 「가능」은
          나오지 않습니다(가장 높은 칸은 「조건부 검토」 — 정상). 나중에 적으면 그때부터 등록 · 결격 줄이 「통과(회사 확인 날짜)」가 됩니다.
        </p>
      ) : (
        <p className="text-[12px] leading-5 text-cosmos-muted">
          <strong className="text-cosmos-text">회사 단위 확인 — 나라장터 「가능」으로 가는 길</strong>. 등록증 · 조회 결과를 보고 세 칸을 적으면 공고마다
          되풀이하던 「입찰 참가 제한(결격)」 · 결격 조항 줄이 <strong className="text-cosmos-text">「통과(회사 확인 날짜)」</strong>가 됩니다. 유효기간이
          지나면 다시 「확인 필요」입니다. 업종 · 실적 · 기업 유형 조항은 공고마다 따로 봅니다.
          {allValid && <span className="text-cosmos-teal"> 지금 세 칸 모두 유효합니다.</span>}
        </p>
      )}
      <div className="flex flex-col gap-2">
        {keys.map((key) => {
          const draft = drafts[key];
          const saved = stored[key];
          const expired = saved !== undefined && saved.valid_until < today;
          return (
            <fieldset key={key} className="grid gap-2 rounded-lg border border-cosmos-border px-3 py-2 sm:grid-cols-[1.4fr_1fr_1fr_1fr_auto] sm:items-end">
              <legend className="sr-only">{COMPANY_CHECK_LABELS[key]}</legend>
              <span className="text-[12.5px] font-semibold text-cosmos-text">
                {COMPANY_CHECK_LABELS[key]}
                <span className={`block text-[12px] font-normal ${expired ? "text-cosmos-amber" : "text-cosmos-muted"}`}>
                  {saved ? (expired ? `유효기간 지남(${saved.valid_until}) — 다시 확인` : `확인 ${saved.confirmed_on} · ${saved.confirmed_by}`) : leftBlank ? "대표 결정으로 비워 둠" : "아직 확인 안 함"}
                </span>
              </span>
              <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                확인일
                <input type="date" className={INPUT} value={draft.confirmed_on} max={today} onChange={(e) => set(key, "confirmed_on", e.target.value)} disabled={readOnly} />
              </label>
              <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                유효기간(까지)
                <input type="date" className={INPUT} value={draft.valid_until} min={draft.confirmed_on || undefined} onChange={(e) => set(key, "valid_until", e.target.value)} disabled={readOnly} />
              </label>
              <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                확인한 사람
                <input className={INPUT} value={draft.confirmed_by} maxLength={60} onChange={(e) => set(key, "confirmed_by", e.target.value)} disabled={readOnly} />
              </label>
              {!readOnly && (
                <span className="flex gap-1.5">
                  <Button size="sm" onClick={() => void submit(key, false)} disabled={busy !== null}>
                    {busy === key ? "저장 중…" : "저장"}
                  </Button>
                  {saved && (
                    <Button size="sm" variant="ghost" onClick={() => void submit(key, true)} disabled={busy !== null}>
                      지우기
                    </Button>
                  )}
                </span>
              )}
            </fieldset>
          );
        })}
      </div>
      {message && <InlineAlert tone="pass">{message}</InlineAlert>}
      {error && (
        <InlineAlert tone="fail">
          {error}
          {stale && <StaleReload />}
        </InlineAlert>
      )}
    </div>
  );
}
