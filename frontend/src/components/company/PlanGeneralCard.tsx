"use client";

/**
 * 사업계획서 일반현황 (29차 · prompt_19 §3-B) — 담당자 결정 「회사자료에 있는 값은 전부 채운다」.
 *
 * - 여기 적은 값은 사업계획서를 **조립할 때만**(화면 · DOCX · PDF) 이 PC 에서 칸에 들어간다. AI 에 보내지 않는다.
 * - 주소 · 전화 · 홈페이지 · 사업영역은 위 「회사 프로필」 값을 그대로 쓴다(두 번 적지 않게).
 * - 인력 구성은 **성명 없이** 직무 · 인원만. 「수행역량에서 가져오기」는 개발 인원을 한 줄로 넣을 뿐 — 고쳐서 저장한다.
 * - 사업자등록증 이미지에서 값을 뽑지 않는다 — 사람이 입력한다.
 * - 30차 R29-05 · 06 · 12 — 칸 상한(백엔드와 같은 값)을 칸 이름과 함께 막는다 · 저장 안 한 변경은 임시 저장본으로 되살린다 ·
 *   공개(읽기 전용) 배포에서는 일반현황을 부르지 않고 중립 안내만.
 */

import { useEffect, useState } from "react";

import { Button, InlineAlert, LoadingState } from "@/components/ui/primitives";
import StaleReload from "@/components/ui/StaleReload";
import { getDeliveryCapacity, getPlanGeneral, isStaleWrite, savePlanGeneral } from "@/lib/api";
import { formatDateTime } from "@/lib/cosmos/format";
import { currentUserName } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import { analysisContext } from "@/lib/organization";
import { clearDraft, loadDraft, saveDraft } from "@/lib/unsavedGuard";
import type { PlanGeneralInfo, YearAmount } from "@/types/organization";
import { VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";

const inputClass =
  "mc-focus min-h-9 w-full rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 text-[13px] text-cosmos-text placeholder:text-cosmos-muted";

/** 최근 3년 — 올해를 뺀 앞 세 해(결산이 끝난 해). */
function recentYears(): number[] {
  const last = new Date().getFullYear() - 1;
  return [last - 2, last - 1, last];
}

type Form = {
  representative: string;
  business_number: string;
  opened_on: string;
  business_type: string;
  business_item: string;
  revenue: Record<number, string>;
  employees: Record<number, string>;
  staff: { role: string; count: string }[];
  updated_by: string;
};

function toForm(info: PlanGeneralInfo | null): Form {
  const years = recentYears();
  const pick = (rows: YearAmount[] | undefined) =>
    Object.fromEntries(years.map((year) => [year, String(rows?.find((r) => r.year === year)?.value ?? "")])) as Record<number, string>;
  return {
    representative: info?.representative ?? "",
    business_number: info?.business_number ?? "",
    opened_on: info?.opened_on ?? "",
    business_type: info?.business_type ?? "",
    business_item: info?.business_item ?? "",
    revenue: pick(info?.revenue_by_year),
    employees: pick(info?.employees_by_year),
    staff: (info?.staff ?? []).map((s) => ({ role: s.role, count: String(s.count) })),
    updated_by: currentUserName() || info?.updated_by || "",
  };
}

/** 칸 상한 — 백엔드 `PlanGeneralUpdate` 와 같은 값(30차 R29-05). 넘으면 칸 이름과 함께 막는다. */
const LIMITS = { representative: 40, business_type: 60, business_item: 120, updated_by: 60 } as const;
const LIMIT_LABELS: Record<keyof typeof LIMITS, string> = { representative: "대표자", business_type: "업태", business_item: "종목", updated_by: "수정자" };

/** 「수행역량에서 가져오기」 종목 — 상한 안에서 항목 단위로만 잇는다. 넘친 항목 수를 함께 돌려준다. */
export function joinWithinLimit(items: readonly string[], limit: number): { text: string; dropped: number } {
  let text = "";
  let kept = 0;
  for (const item of items) {
    const next = text ? `${text}, ${item}` : item;
    if (next.length > limit) break;
    text = next;
    kept += 1;
  }
  return { text, dropped: items.length - kept };
}

/** 숫자 칸 — 숫자와 쉼표만(「억」 · 「명」은 읽지 않는다). 빈 칸은 null. */
function numberOrNull(label: string, raw: string): number | null {
  const value = raw.trim();
  if (!value) return null;
  if (!/^[\d,]+$/.test(value)) throw new Error(`「${label}」은 숫자만 적어 주세요 (예: 310000000). 「억」 · 「명」 같은 단위는 읽지 않습니다.`);
  return Number(value.replace(/,/g, ""));
}

function won(value: number | null | undefined): string {
  return value === null || value === undefined ? "미입력" : `${value.toLocaleString("ko-KR")}원`;
}

export default function PlanGeneralCard({ organizationId, readOnly }: { organizationId: string; readOnly: boolean }) {
  // 43차 마지막 검토(M26) — 열람자는 고치기 단추를 잠근다(일반현황은 읽어 보인다)
  const viewer = useViewerLock();
  const [info, setInfo] = useState<PlanGeneralInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Form>(() => toForm(null));
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 44차 TEAM-R36-01 — 고치기를 시작한 때의 저장 시각(임시 저장본에도 `_base` 로 둔다). 그사이 남이 저장했으면 서버가 409.
  const [baseAt, setBaseAt] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  // 저장 안 한 변경 — 회사 전환 · 새로고침 · 탭 닫기에서 말없이 사라졌다(30차 R29-06). 프로필 카드와 같은 임시 저장본.
  const draftKey = `plan-general:${organizationId}`;

  useEffect(() => {
    if (readOnly) return; // 공개(읽기 전용) 배포 — 일반현황을 부르지 않는다(30차 R29-12)
    let alive = true;
    getPlanGeneral(organizationId)
      .then((value) => {
        if (!alive) return;
        setInfo(value);
        const raw = loadDraft(draftKey);
        let restored: Form | null = null;
        let restoredBase: string | null | undefined;
        try {
          const parsed = raw ? (JSON.parse(raw) as Partial<Form> & { _base?: string | null }) : null;
          if (parsed) {
            const { _base, ...fields } = parsed;
            restored = { ...toForm(value), ...fields } as Form;
            restoredBase = _base;
          }
        } catch {
          restored = null; // 깨진 임시 저장본 — 없는 것으로 본다
        }
        setForm(restored ?? toForm(value));
        const base = restored && restoredBase !== undefined ? restoredBase : value.updated_at ?? null;
        setBaseAt(base);
        if (restored) {
          setEditing(true);
          setMessage(
            base !== (value.updated_at ?? null)
              ? "저장하지 않은 일반현황을 되살렸습니다 — 그사이 다른 사람이 저장했습니다. 저장하면 막히니 「취소」 뒤 새 값에서 고치세요."
              : "저장하지 않은 일반현황을 되살렸습니다 — 고쳐서 저장하거나 취소하세요.",
          );
        }
      })
      .catch((e: unknown) => alive && setLoadError(describeFailure(e, "사업계획서 일반현황을 불러오지 못했습니다.")));
    return () => {
      alive = false;
    };
  }, [organizationId, readOnly, draftKey]);

  // 「→ 회사자료로」(`/company#plan-general`)로 오면 카드가 늦게 그려져 그 자리까지 내려가지 않았다(30차 R29-13).
  const loaded = info !== null || readOnly;
  useEffect(() => {
    if (loaded && typeof window !== "undefined" && window.location.hash === "#plan-general") {
      document.getElementById("plan-general")?.scrollIntoView({ block: "start" });
    }
  }, [loaded]);

  // 편집 중에만 남긴다(보기 모드의 값은 서버에 이미 있다).
  useEffect(() => {
    if (!editing) return;
    // 편집을 열기만 하면 남기지 않는다 — 고친 것이 있을 때만(대표자 · 사업자번호가 괜히 브라우저에 남지 않게 · 30차 §4 마지막 검토)
    const changed = JSON.stringify(form) !== JSON.stringify(toForm(info));
    if (changed) saveDraft(draftKey, JSON.stringify({ ...form, _base: baseAt }));
    else clearDraft(draftKey);
  }, [editing, form, draftKey, info, baseAt]);

  const fromCapacity = () => {
    getDeliveryCapacity(analysisContext("", organizationId))
      .then((capacity) => {
        const rows = [...form.staff];
        if (capacity.developer_count && !rows.some((r) => r.role === "개발")) rows.push({ role: "개발", count: String(capacity.developer_count) });
        // 종목은 상한(120자) 안에서 항목 단위로만 잇는다 — 126자를 넣어 저장이 422 로 막혔다(30차 R29-05)
        const joined = joinWithinLimit(capacity.business_items ?? [], LIMITS.business_item);
        setForm((prev) => ({
          ...prev,
          staff: rows.length ? rows : prev.staff,
          business_item: prev.business_item || joined.text,
        }));
        const overflow = !form.business_item && joined.dropped > 0 ? ` 종목이 ${LIMITS.business_item}자를 넘어 ${joined.dropped}개는 넣지 않았습니다 — 꼭 필요한 것만 남기세요.` : "";
        setMessage(
          capacity.developer_count || capacity.business_items?.length
            ? `수행역량에서 가져왔습니다(개발 ${capacity.developer_count ?? 0}명 · 종목 ${(capacity.business_items ?? []).length}개) — 고쳐서 저장하세요.${overflow}${capacity.team_note ? ` 인력 메모: ${capacity.team_note}` : ""}`
            : "수행역량에 개발 인원 · 종목이 아직 없습니다.",
        );
      })
      .catch((e: unknown) => setError(describeFailure(e, "수행역량을 읽지 못했습니다.")));
  };

  const save = () => {
    setError(null);
    setMessage(null);
    const number = form.business_number.trim();
    if (number && !/^\d{3}-\d{2}-\d{5}$/.test(number)) {
      setError("「사업자등록번호」는 000-00-00000 모양으로 적어 주세요 (비우면 지웁니다).");
      return;
    }
    if (!form.updated_by.trim()) {
      setError("수정자는 필수입니다.");
      return;
    }
    // 백엔드 상한과 같은 검사 — 어느 칸인지 말한다(30차 R29-05)
    for (const key of Object.keys(LIMITS) as (keyof typeof LIMITS)[]) {
      const length = form[key].trim().length;
      if (length > LIMITS[key]) {
        setError(`「${LIMIT_LABELS[key]}」은 ${LIMITS[key]}자까지입니다 — 지금 ${length}자입니다.`);
        return;
      }
    }
    let body;
    try {
      const years = recentYears();
      body = {
        representative: form.representative.trim() || null,
        business_number: number || null,
        opened_on: form.opened_on || null,
        business_type: form.business_type.trim() || null,
        business_item: form.business_item.trim() || null,
        revenue_by_year: years.map((year) => ({ year, value: numberOrNull(`${year}년 매출`, form.revenue[year] ?? "") })).filter((r) => r.value !== null),
        employees_by_year: years.map((year) => ({ year, value: numberOrNull(`${year}년 고용 인원`, form.employees[year] ?? "") })).filter((r) => r.value !== null),
        staff: form.staff
          .filter((s) => s.role.trim())
          .map((s) => ({ role: s.role.trim(), count: numberOrNull(`「${s.role}」 인원`, s.count) ?? 0 })),
        updated_by: form.updated_by.trim(),
        expected_updated_at: baseAt,
      };
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    setBusy(true);
    setStale(false);
    savePlanGeneral(organizationId, body)
      .then((saved) => {
        setInfo(saved);
        setBaseAt(saved.updated_at ?? null);
        setForm(toForm(saved));
        setEditing(false);
        clearDraft(draftKey);
        setMessage("저장했습니다 — 사업계획서를 열거나 내려받으면 이 값이 칸에 들어갑니다.");
      })
      .catch((e: unknown) => {
        setStale(isStaleWrite(e));
        setError(describeFailure(e, "일반현황을 저장하지 못했습니다."));
      })
      .finally(() => setBusy(false));
  };

  const years = recentYears();
  return (
    <section id="plan-general" className="mc-panel flex scroll-mt-24 flex-col gap-3 p-4" aria-label="사업계획서 일반현황" data-plan-general>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-cosmos-text">사업계획서 일반현황</h2>
        <span className="text-[12px] text-cosmos-muted">사업계획서의 대표자 · 사업자등록번호 · 매출 · 인력 칸에 자동으로 들어갑니다</span>
        <div className="ml-auto flex gap-1.5">
          <Button
            size="sm"
            variant={editing ? "ghost" : "secondary"}
            disabled={readOnly || info === null || viewer}
            title={viewer ? VIEWER_LOCK_REASON : undefined}
            onClick={() => {
              if (editing) {
                setForm(toForm(info));
                clearDraft(draftKey);
                setStale(false);
              }
              setBaseAt(info?.updated_at ?? null);  // 고치기는 지금 저장본에서 시작(44차 TEAM-R36-01)
              setError(null);
              setEditing((v) => !v);
            }}
          >
            {editing ? "취소" : "수정"}
          </Button>
          {editing && (
            <Button size="sm" variant="primary" disabled={busy} onClick={save}>
              {busy ? "저장 중…" : "저장"}
            </Button>
          )}
        </div>
      </div>
      <p className="text-[12.5px] leading-5 text-cosmos-secondary">
        여기 적은 값은 사업계획서를 화면에 열거나 DOCX · PDF 로 받을 때만 이 PC 에서 칸에 넣습니다 — <strong className="font-semibold text-cosmos-text">AI(Claude · Codex)에는 보내지 않습니다.</strong> 주소 · 전화 · 홈페이지 · 사업영역은 위 「회사 프로필」 값을 씁니다.
      </p>
      {readOnly && (
        <InlineAlert tone="info" role="status">
          공개 배포에서는 일반현황(대표자 · 사업자등록번호 · 매출 · 인력)을 보이지 않습니다 — 사내 설치에서 입력합니다.
        </InlineAlert>
      )}
      {loadError && <InlineAlert tone="fail">{loadError}</InlineAlert>}
      {error && (
        <InlineAlert tone="fail">
          {error}
          {stale && <StaleReload draftKeys={[draftKey]} />}
        </InlineAlert>
      )}
      {message && <InlineAlert tone="info" role="status">{message}</InlineAlert>}
      {!readOnly && info === null && !loadError && <LoadingState label="일반현황을 불러오는 중" rows={2} />}
      {info !== null && !editing && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
          {[
            ["대표자", info.representative ?? "미입력"],
            ["사업자등록번호", info.business_number ?? "미입력"],
            ["개업연월일", info.opened_on ?? "미입력"],
            ["업태 / 종목", [info.business_type, info.business_item].filter(Boolean).join(" / ") || "미입력"],
            ...years.map((year) => [`${year}년 매출 · 고용`, `${won(info.revenue_by_year.find((r) => r.year === year)?.value)} · ${info.employees_by_year.find((r) => r.year === year)?.value ?? "미입력"}${info.employees_by_year.some((r) => r.year === year) ? "명" : ""}`]),
            ["인력 구성", info.staff.length ? info.staff.map((s) => `${s.role} ${s.count}명`).join(" · ") : "미입력"],
            ["최근 수정", info.updated_at ? `${formatDateTime(info.updated_at)} · ${info.updated_by ?? ""}` : "아직 저장하지 않았습니다"],
          ].map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-cosmos-muted">{label}</dt>
              <dd className={`min-w-0 break-words ${String(value).startsWith("미입력") ? "text-cosmos-muted" : "text-cosmos-text"}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {info !== null && editing && (
        <div className="flex flex-col gap-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              대표자
              <input className={inputClass} value={form.representative} maxLength={LIMITS.representative} onChange={(e) => setForm((p) => ({ ...p, representative: e.target.value }))} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              사업자등록번호 (000-00-00000)
              <input className={inputClass} value={form.business_number} inputMode="numeric" placeholder="000-00-00000" onChange={(e) => setForm((p) => ({ ...p, business_number: e.target.value }))} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              개업연월일
              <input className={inputClass} type="date" value={form.opened_on} onChange={(e) => setForm((p) => ({ ...p, opened_on: e.target.value }))} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              업태
              <input className={inputClass} value={form.business_type} maxLength={LIMITS.business_type} placeholder="예: 서비스" onChange={(e) => setForm((p) => ({ ...p, business_type: e.target.value }))} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted sm:col-span-2">
              종목 ({LIMITS.business_item}자까지)
              <input className={inputClass} value={form.business_item} maxLength={LIMITS.business_item} placeholder="예: 교육 컨설팅, 소프트웨어 개발" onChange={(e) => setForm((p) => ({ ...p, business_item: e.target.value }))} />
            </label>
          </div>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-[12.5px] font-semibold text-cosmos-text">연도별 매출(원) · 고용 인원(명) — 최근 3년</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {years.map((year) => (
                <div key={year} className="flex flex-col gap-1">
                  <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                    {year}년 매출
                    <input className={inputClass} inputMode="numeric" value={form.revenue[year] ?? ""} onChange={(e) => setForm((p) => ({ ...p, revenue: { ...p.revenue, [year]: e.target.value } }))} />
                  </label>
                  <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                    {year}년 고용 인원
                    <input className={inputClass} inputMode="numeric" value={form.employees[year] ?? ""} onChange={(e) => setForm((p) => ({ ...p, employees: { ...p.employees, [year]: e.target.value } }))} />
                  </label>
                </div>
              ))}
            </div>
          </fieldset>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-[12.5px] font-semibold text-cosmos-text">인력 구성 — 성명 없이 직무 · 인원</legend>
            {form.staff.map((member, index) => (
              <div key={index} className="flex flex-wrap items-center gap-2">
                <input className={`${inputClass} max-w-xs`} aria-label={`${index + 1}번째 직무`} value={member.role} placeholder="직무(예: AI 교육 강사)" onChange={(e) => setForm((p) => ({ ...p, staff: p.staff.map((s, i) => (i === index ? { ...s, role: e.target.value } : s)) }))} />
                <input className={`${inputClass} max-w-[90px]`} aria-label={`${index + 1}번째 인원`} inputMode="numeric" value={member.count} placeholder="인원" onChange={(e) => setForm((p) => ({ ...p, staff: p.staff.map((s, i) => (i === index ? { ...s, count: e.target.value } : s)) }))} />
                <Button size="sm" variant="ghost" onClick={() => setForm((p) => ({ ...p, staff: p.staff.filter((_, i) => i !== index) }))} aria-label={`${index + 1}번째 줄 지우기`}>
                  지우기
                </Button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => setForm((p) => ({ ...p, staff: [...p.staff, { role: "", count: "" }] }))}>
                줄 더하기
              </Button>
              <Button size="sm" variant="secondary" onClick={fromCapacity}>
                수행역량에서 가져오기
              </Button>
            </div>
          </fieldset>
          <label className="flex max-w-xs flex-col gap-1 text-[12px] text-cosmos-muted">
            수정자 (필수)
            <input className={inputClass} value={form.updated_by} maxLength={LIMITS.updated_by} onChange={(e) => setForm((p) => ({ ...p, updated_by: e.target.value }))} />
          </label>
        </div>
      )}
    </section>
  );
}
