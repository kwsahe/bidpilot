"use client";

/**
 * 회사자료 빈칸 안내 (38차 §3-C-7) — **비어 있어서 판정이 멈춘 칸**과 그 칸 때문에 「확인 필요」로 남은 공고 수.
 *
 * recheck30 §4-4: 입찰 자격 칸이 비어 판정 낱말이 거의 모두 「조건부 검토」였다. 무엇을 적으면 판정이 정리되는지를
 * 칸마다 숫자로 보인다. 수는 서버가 지금 목록(마감 전)에서 센 것이다 — 화면이 다시 세지 않는다. 값을 가정하지 않는다.
 *
 * 41차 D31 — 회사 값을 다 줄 수는 없다(담당자 10-20). 칸마다 「안 적음(그대로 둠)」을 고르면 그 칸은 이 안내에서 빠진다.
 * **판정은 그대로 「확인 필요」**(값을 가정하지 않음) · 「다시 안내」로 되돌리거나 칸을 적으면 풀린다. 화면이 대신 고르지 않는다.
 */

import { useEffect, useState } from "react";

import StaleReload from "@/components/ui/StaleReload";
import { getBlankFields, isStaleWrite, saveLeftBlank, type BlankFieldsResponse } from "@/lib/api";
import { currentUserName } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import { analysisContext } from "@/lib/organization";
import type { DeliveryCapacity } from "@/types/capability";

import { applyLeftBlank } from "./leftBlank";

const CHIP_BUTTON =
  "mc-focus inline-flex min-h-7 items-center rounded border border-cosmos-border px-2 text-[12px] text-cosmos-secondary hover:border-cosmos-blue hover:text-cosmos-text disabled:opacity-50";

export default function BlankFieldsNotice({
  organizationId,
  capacityUpdatedAt,
  locked = false,
  onCapacitySaved,
}: {
  organizationId: string;
  /** 입찰 자격 자료를 읽은 때의 저장 시각(43차 M25) — 그사이 남이 저장했으면 「안 적음」 저장을 막는다. */
  capacityUpdatedAt?: string | null;
  /** 열람자 · 공개 배포 — 「안 적음」 단추를 감춘다(43차 M26). */
  locked?: boolean;
  /** 저장 뒤 카드의 저장 시각을 맞춘다 — 안 그러면 같은 사람의 다음 「저장」이 제 「안 적음」 저장에 막힌다. */
  onCapacitySaved?: (saved: DeliveryCapacity) => void;
}) {
  const [data, setData] = useState<BlankFieldsResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let alive = true;
    getBlankFields(analysisContext("", organizationId))
      .then((value) => alive && setData(value))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [organizationId]);

  if (failed) return null;
  if (!data) {
    return <p className="text-[12px] text-cosmos-muted">비어 있어서 판정이 멈춘 칸을 세는 중…</p>;
  }
  // 대표가 적는 칸은 걸린 공고가 0건이어도 보인다 — 「안 적음」을 고를 자리(44차 대표 결정 1)
  const blank = data.fields.filter((field) => field.blank && !field.left_blank && (field.count > 0 || field.owner_value));
  const kept = data.fields.filter((field) => field.blank && field.left_blank);

  /** 「안 적음」 열쇠 전부를 저장한다 — 사람이 누를 때만(화면이 대신 고르지 않는다).
   *  저장 응답을 바로 반영하고 다시 읽기가 끝날 때까지 단추를 막는다(42차 FRONT-R41-01 — 연달아 누르면 앞 선택이 사라졌다). */
  const saveKeys = (keys: string[]) => {
    if (saving) return;
    setSaving(true);
    setSaveError(null);
    setStale(false);
    const ctx = analysisContext("", organizationId);
    saveLeftBlank(keys, currentUserName() || "담당자", ctx, capacityUpdatedAt)
      .then((saved) => {
        onCapacitySaved?.(saved);
        setData((prev) => (prev ? applyLeftBlank(prev, saved.left_blank ?? keys) : prev));
        // 다시 읽기 실패는 저장 실패가 아니다 — 저장 응답으로 이미 그렸다.
        return getBlankFields(ctx).then(setData, () => undefined);
      })
      .catch((error: unknown) => {
        setStale(isStaleWrite(error));  // 44차 TEAM-R36-07
        setSaveError(describeFailure(error));
      })
      .finally(() => setSaving(false));
  };
  const keptKeys = kept.map((field) => field.key);

  const keptLine =
    kept.length > 0 ? (
      <p className="flex flex-wrap items-center gap-1.5 text-[12px] leading-5 text-cosmos-muted" data-left-blank>
        <span>
          대표 결정으로 비워 둠: {kept.map((field) => field.label).join(" · ")} — 판정은 그대로 「확인 필요」입니다(값을 가정하지 않음).
        </span>
        {kept.map((field) => (
          <button
            key={field.key}
            type="button"
            className={CHIP_BUTTON}
            disabled={saving || locked}
            onClick={() => saveKeys(keptKeys.filter((key) => key !== field.key))}
          >
            {field.label} 다시 안내
          </button>
        ))}
      </p>
    ) : null;
  // 45차 M12 — 단추가 흐린 채 2~12초 아무 말이 없었다(다시 세는 시간)
  const savingLine = saving ? (
    <p className="text-[12px] text-cosmos-cyan" role="status" data-left-blank-saving>
      저장 중… 걸린 공고를 다시 세는 데 몇 초 걸립니다.
    </p>
  ) : null;
  const errorLine = saveError ? (
    <p className="text-[12px] text-cosmos-red" role="alert">
      저장하지 못했습니다 — {saveError}
      {stale && <StaleReload />}
    </p>
  ) : null;

  if (blank.length === 0) {
    return (
      <div className="flex flex-col gap-1" data-blank-fields>
        <p className="text-[12.5px] text-cosmos-secondary">비어 있어서 판정이 멈춘 칸이 없습니다.</p>
        {keptLine}
        {savingLine}
        {errorLine}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-cosmos-amber/40 bg-cosmos-panel px-3 py-2" data-blank-fields>
      <p className="text-[13px] font-semibold text-cosmos-text">비어 있어서 판정이 멈춘 칸</p>
      <ul className="flex flex-col gap-1">
        {blank.map((field) => (
          <li key={field.key} className="text-[12.5px] leading-5 text-cosmos-secondary">
            <strong className="text-cosmos-text">{field.label}</strong>
            {field.reference ? (
              // 43차 Q25 — 적어도 판정이 바뀌지 않는 칸(파트너는 공고마다 정함) · 「채우면」으로 권하지 않는다
              <> — <span className="text-cosmos-muted">참고: 이 칸은 「있음 · 없음」 어느 쪽으로 적어도 판정이 바뀌지 않습니다(공동수급은 공고마다 정함) · 걸린 공고 {field.count.toLocaleString("ko-KR")}건</span></>
            ) : (
              <>
                {" "}— 이 칸도 걸린 공고{" "}
                <strong className="tabular-nums text-cosmos-amber">{field.count.toLocaleString("ko-KR")}건</strong>
                {typeof field.only_count === "number" && (
                  <> · 이 칸만 걸린 공고 <strong className="tabular-nums text-cosmos-text">{field.only_count.toLocaleString("ko-KR")}건</strong>(채우면 판정이 바뀔 수 있는 것 — 「가능」이 저절로 늘지는 않습니다)</>
                )}
              </>
            )}
            <span className="text-cosmos-muted"> · {field.where}</span>
            {field.examples.length > 0 && (
              <span className="block truncate text-[12px] text-cosmos-muted" title={field.examples.map((e) => e.title).join(" · ")}>
                예: {field.examples.map((e) => e.title).join(" · ")}
              </span>
            )}
            <button
              type="button"
              className={`${CHIP_BUTTON} mt-0.5`}
              disabled={saving || locked}
              data-left-blank-button={field.key}
              title="이 칸은 지금 적지 않고 그대로 둡니다 — 안내에서만 빠지고, 판정은 그대로 「확인 필요」입니다. 「다시 안내」로 되돌릴 수 있습니다."
              onClick={() => saveKeys([...keptKeys, field.key])}
            >
              안 적음(그대로 둠)
            </button>
          </li>
        ))}
      </ul>
      <p className="text-[12px] leading-4 text-cosmos-muted">{data.note}</p>
      {keptLine}
      {savingLine}
      {errorLine}
    </div>
  );
}
