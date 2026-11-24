"use client";

/**
 * 사업기회 「직접 넣기 · 후보함」 탭 (38차 §3-E · 담당자 결정 3). 메뉴는 그대로 다섯이다.
 *
 * 세 덩어리:
 * 1. **직접 넣은 공고** — 나라장터 · 기업마당에 없는 공고(기관 홈페이지 · 이메일 · PMS 접수)를 넣는다. 판정 · 순위는 서버가
 *    같은 규칙으로 매기고(출처 「직접 넣음」 안에서만), 공고문 원문을 사람이 확인하기 전에는 「가능」이 되지 않는다(D16).
 * 2. **확인 전 후보함** — GPT · 사람이 찾은 결과를 붙여 넣으면 링크 · 공고명 · 기관 · 날짜 글자만 기계적으로 뽑는다(점수 · 판정 없음).
 * 3. **오늘 열어 본 곳** — 기관 게시판 목록. 「열기」는 새 탭으로 열고 그 시각만 적는다(서버는 그 사이트를 읽지 않는다).
 *
 * 처음 하는 대표가 읽는 화면이다 — 어려운 말 대신 「무엇을 하면 무엇이 되는지」를 적는다(memory: owner-first-time-bidder).
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";

import { PracticalTags } from "@/components/opportunities/PracticalTags";
import ManualConfirm from "@/components/opportunities/ManualConfirm";
import { Badge, Button, InlineAlert } from "@/components/ui/primitives";
import {
  createManualNotice,
  deleteManualNotice,
  discardInboxEntry,
  getNoticeInbox,
  getWatchlist,
  isStaleWrite,
  listManualNotices,
  markWatchOpened,
  pasteNoticeInbox,
  saveWatchlist,
  updateManualNotice,
  uploadManualDocument,
} from "@/lib/api";
import { formatDateTime } from "@/lib/cosmos/format";
import { TONE_COLORS } from "@/lib/cosmos/theme";
import { dDayText, effectiveDeadline, firstLabel, pairOf } from "@/lib/deadline";
import { readCurrentUser } from "@/lib/currentUser";
import { describeFailure } from "@/lib/errors";
import {
  DOCUMENT_ACCEPT,
  EMPTY_FORM,
  REGION_CUSTOM,
  REGION_PRESETS,
  chooseRegion,
  documentProblem,
  formErrors,
  fromNotice,
  regionChoiceOf,
  toInput,
  uploadMessage,
  watchSiteProblem,
  type ManualFormState,
} from "@/lib/manualForm";
import { clearDraft, loadDraft, markDirty, saveDraft } from "@/lib/unsavedGuard";
import { verdictOf } from "@/lib/verdict";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import {
  MAX_PASTE_CHARS,
  RECRUIT_CHOICES,
  SOURCE_LAYERS,
  SOURCE_LAYER_HELP,
  SUBMIT_METHODS,
  type InboxEntry,
  type InboxPasteResult,
  type ManualNotice,
  type WatchSite,
  type WatchSiteInput,
} from "@/types/manual";
import type { UnifiedOpportunity } from "@/types/opportunity";

const fieldClass =
  "mc-focus min-h-10 w-full min-w-0 rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 text-[14px] text-cosmos-text placeholder:text-cosmos-muted";
const labelClass = "flex min-w-0 flex-col gap-1 text-[14px] text-cosmos-secondary";

/** 저장본에 이미 있는 공고로 가는 주소 — 나라장터는 대시보드, 기업마당은 지원사업 신청 분석, 직접 넣음은 이 탭. */
/** 붙여 넣은 표의 공고일 글(「10/16」 · 「2026-10-16」) → `<input type="date">` 값(43차 M15). 못 읽으면 빈칸. */
function isoDay(text: string | null | undefined): string {
  const m = (text ?? "").match(/(?:(20\d{2})[-./]\s?)?(\d{1,2})[-./]\s?(\d{1,2})/);
  if (!m) return "";
  const year = m[1] ?? String(new Date().getFullYear());
  return `${year}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
}

function existingHref(id: string): string {
  if (id.startsWith("bizinfo-")) return `/support/${encodeURIComponent(id)}`;
  if (id.startsWith("manual-")) return `/opportunities?tab=manual&manual=${encodeURIComponent(id)}`;
  // 44차 TEAM-R36-03 — 사전규격은 입찰 목록 밖 「선제준비」 탭에 있다(대시보드 `/analysis?notice=g2bpre-…` 는 가상 예시 공고를 열었다)
  if (id.startsWith("g2bpre-")) return "/opportunities?tab=prepare";
  return `/analysis?notice=${encodeURIComponent(id)}`;
}

function existingLabel(id: string, lookup: (id: string) => UnifiedOpportunity | undefined): string {
  if (id.startsWith("g2bpre-")) return "선제준비 칸에 있음";
  const hit = lookup(id);
  if (!hit) return "이미 있음(지금 목록 밖 — 마감 · 불가일 수 있음)";
  return `이미 있음(${hit.source_rank ?? "–"}위 · ${verdictOf(hit.eligibility_gate, hit.participation).label})`;
}

function openedText(iso: string | null, nowMs: number | null, by?: string | null): string {
  if (!iso) return "아직 안 열어 봄";
  const ms = Date.parse(iso);
  // 43차 TEAM-05 — 누가 열었는지 함께(회사 하나로 세어 「오늘 봤다」고 여기고 건너뛸 수 있었다)
  const who = by ? ` · ${by}` : "";
  if (nowMs !== null && new Date(ms + 9 * 3600e3).toISOString().slice(0, 10) === new Date(nowMs + 9 * 3600e3).toISOString().slice(0, 10)) {
    return `오늘 ${new Date(ms + 9 * 3600e3).toISOString().slice(11, 16)} 열어 봄${who}`;
  }
  return `마지막 ${formatDateTime(iso)}${who}`;
}

/** 후보함 붙여넣기 임시 저장 열쇠(43차 M28) — 회사별(2.0.6 · 회사를 바꾸면 다른 회사 칸에 되살아났다 · 회사자료 카드와 같은 규칙). */
const pasteDraftKey = (organizationId: string) => `manual-inbox-paste:${organizationId}`;

// ---------------------------------------------------------------------------
// 넣는 양식 (대화상자 — 브라우저 기본 <dialog>: 포커스 가두기 · Esc 닫기를 브라우저가 한다)
// ---------------------------------------------------------------------------

function ManualDialog({
  organizationId,
  open,
  initial,
  editingId,
  expectedUpdatedAt,
  lookup,
  onClose,
  onSaved,
}: {
  organizationId: string;
  open: boolean;
  initial: ManualFormState;
  editingId: string | null;
  /** 고치기를 연 때 읽은 저장 시각(43차 M25) — 그사이 남이 고쳤으면 저장을 막는다. 새로 넣기는 null. */
  expectedUpdatedAt: string | null;
  lookup: (id: string) => UnifiedOpportunity | undefined;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  // 43차 M28 — 쓰던 폼을 임시 저장한다(세션이 끝나 새로 고쳐도 되살린다). 고치기는 공고마다, 새로 넣기는 후보 줄마다.
  // 2.0.6 — 회사별로 나눈다(「새로 넣기」 폼이 다른 회사 칸에 되살아나 저장하면 그 회사에 들어갔다).
  const draftKey = `manual-form.${organizationId}.${editingId ?? (initial.inboxId ? `inbox-${initial.inboxId}` : "new")}`;
  const ref = useRef<HTMLDialogElement | null>(null);
  const titleId = useId();
  // 연 단추 — 닫히면(✕ · 그만두기 · 저장 뒤 · Esc) 그 단추로 초점을 돌려준다(39차 FRONTEND-09 · 대화상자가 사라지며 문서 처음으로 갔다)
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => opener?.focus();
  }, []);
  const [state, setState] = useState<ManualFormState>(initial);
  const [file, setFile] = useState<File | null>(null);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<{ id: string; reason: string | null; maybe?: boolean } | null>(null);
  // 43차 H4 — 「같은 공고일 수 있음」을 보고 「그래도 새로 넣기」를 누르면 다음 저장에 confirm_new
  const [confirmNew, setConfirmNew] = useState(false);
  const [restoredNote, setRestoredNote] = useState(false);
  // 45차 M14 — 먼저 바뀜(409) 뒤 「다시 불러오기」: 쓴 글은 그대로 두고 새 저장 시각만 받는다(창을 닫으면 쓴 글이 사라졌다)
  const [stale, setStale] = useState(false);
  const [reloadNote, setReloadNote] = useState<string | null>(null);
  // 고치기를 시작한 저장 시각(43차 마지막 검토) — 되살린 임시 저장본은 그때 시각으로 저장해 그사이 남이 고쳤으면 막힌다
  const [baseAt, setBaseAt] = useState<string | null>(expectedUpdatedAt);
  const dirty = file !== null || JSON.stringify(state) !== JSON.stringify(initial);
  // 45차 H2 — 첫 그림에서는 저장본을 지우지 않는다. 이 효과가 아래 「열기」 효과(되살리기)보다 먼저 돌아 dirty=false 로
  // 저장본을 지운 뒤라, 다시 열면 늘 빈 칸이었다. 되살리기를 마친 뒤부터 쓰고 지운다.
  const restoredRef = useRef(false);

  useEffect(() => {
    if (!restoredRef.current) return;
    if (dirty) saveDraft(draftKey, JSON.stringify({ ...state, _base: baseAt }));
    else clearDraft(draftKey);
  }, [dirty, draftKey, state, baseAt]);

  /** ✕ · 그만두기 · Esc — 쓴 것이 있으면 묻는다(43차 M28 · 확인 없이 닫혔다). 닫기로 했으면 임시 저장본도 지운다. */
  const requestClose = () => {
    if (dirty && !window.confirm("쓰던 내용을 버리고 닫을까요?")) return;
    clearDraft(draftKey);
    markDirty(draftKey, false);
    onClose();
  };

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      const raw = loadDraft(draftKey);
      let restored: ManualFormState | null = null;
      let restoredBase: string | null | undefined;
      try {
        const parsed = raw ? (JSON.parse(raw) as Partial<ManualFormState> & { _base?: string | null }) : null;
        if (parsed) {
          const { _base, ...fields } = parsed;
          restored = { ...initial, ...fields };
          restoredBase = _base;
        }
      } catch {
        restored = null; // 깨진 임시 저장본 — 없는 것으로 본다
      }
      setState(restored ?? initial);
      setRestoredNote(restored !== null);
      setBaseAt(restoredBase !== undefined ? restoredBase : expectedUpdatedAt);
      setFile(null);
      setTouched(false);
      setFailure(null);
      setDuplicate(null);
      setConfirmNew(false);
      setStale(false);
      setReloadNote(null);
      restoredRef.current = true;
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initial, draftKey, expectedUpdatedAt]);

  const errors = formErrors(state);
  const fileProblem = file ? documentProblem(file) : null;
  const set = <K extends keyof ManualFormState>(key: K, value: ManualFormState[K]) => setState((prev) => ({ ...prev, [key]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (Object.keys(errors).length > 0 || fileProblem) return;
    setBusy(true);
    setFailure(null);
    try {
      let noticeId: string;
      if (editingId) {
        noticeId = (await updateManualNotice(organizationId, editingId, toInput(state), baseAt)).id;
      } else {
        const result = await createManualNotice(organizationId, { ...toInput(state), confirm_new: confirmNew });
        if (!result.notice) {
          setDuplicate({ id: result.duplicate_of ?? "", reason: result.duplicate_reason, maybe: result.maybe_duplicate });
          return;
        }
        noticeId = result.notice.id;
      }
      clearDraft(draftKey);
      const head = editingId ? "고쳤습니다." : "넣었습니다.";
      if (!file) {
        onSaved(editingId ? "고쳤습니다. 판정 · 순위를 다시 매겼습니다." : "넣었습니다. 공고문 파일을 올리면 자격 조항으로 판정합니다.");
        return;
      }
      try {
        const saved = await uploadManualDocument(organizationId, noticeId, file);
        onSaved(`${head} ${uploadMessage(saved.document)}`);
      } catch (error: unknown) {
        // 공고는 저장됐다 — 파일만 실패했다고 말하고 목록을 새로 고친다(39차 FRONTEND-05 · 다시 넣으면 「이미 있음」이 났다)
        onSaved(`${head} 다만 공고문 파일은 올리지 못했습니다 — ${describeFailure(error, "올리기 실패")} 목록의 「공고문 올리기」로 다시 올려 주세요.`);
      }
    } catch (error: unknown) {
      if (isStaleWrite(error)) {
        // 43차 M25 · 45차 M14 — 이 창의 「다시 불러오기」로 새 저장 시각을 받는다(쓴 글은 남김)
        setStale(true);
        setFailure(describeFailure(error));
      } else {
        setFailure(describeFailure(error, "저장하지 못했습니다."));
      }
    } finally {
      setBusy(false);
    }
  };

  const show = (key: keyof ManualFormState) => (touched ? errors[key] : undefined);

  const reloadBase = async () => {
    try {
      const fresh = (await listManualNotices(organizationId)).find((n) => n.id === editingId);
      if (!fresh) {
        setFailure("이 공고를 찾지 못했습니다 — 누가 지웠을 수 있습니다. 창을 닫고 목록을 보세요.");
        return;
      }
      setBaseAt(fresh.updated_at);
      setStale(false);
      setFailure(null);
      const who = fresh.updated_by_name ?? fresh.updated_by ?? fresh.created_by_name ?? fresh.created_by;
      setReloadNote(`새 값을 받았습니다${who ? ` — ${who} · ${formatDateTime(fresh.updated_at)} 저장` : ""}. 쓰신 글은 그대로입니다. 목록에서 바뀐 칸을 확인한 뒤 다시 저장하세요 — 저장하면 이 창의 값으로 바뀝니다.`);
    } catch (error: unknown) {
      setFailure(describeFailure(error, "새 값을 받지 못했습니다."));
    }
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(event) => {
        // Esc — 쓴 것이 있으면 묻는다(43차 M28)
        if (!dirty) return;
        event.preventDefault();
        requestClose();
      }}
      // 45차 M14 — 불투명 바탕(반투명 패널 색이라 뒤 목록 글이 입력 칸 사이로 비쳤다)
      className="mc-scroll m-auto w-[min(640px,calc(100vw-24px))] max-h-[calc(100dvh-24px)] overflow-y-auto rounded-xl border border-cosmos-border bg-cosmos-panel-solid p-0 text-cosmos-text backdrop:bg-black/60"
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-4 p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-[18px] font-semibold">{editingId ? "직접 넣은 공고 고치기" : "공고 직접 넣기"}</h2>
            <p className="mt-1 text-[14px] leading-6 text-cosmos-secondary">
              공고 원문 페이지에 있는 그대로 적어 주세요. 별표(*)는 꼭 적을 칸입니다. 공고문 파일을 함께 올리면 자격 조항을 읽어 판정합니다.
            </p>
          </div>
          <Button variant="ghost" onClick={requestClose} aria-label="닫기">✕</Button>
        </div>
        {restoredNote && (
          <InlineAlert tone="info" role="status">저장하지 않은 내용을 되살렸습니다 — 고쳐서 저장하거나 「그만두기」로 버리세요.</InlineAlert>
        )}

        <label className={labelClass}>
          공식 원문 주소 *
          <input className={fieldClass} type="url" inputMode="url" placeholder="https://… (기관 공고 페이지)" value={state.url} onChange={(e) => set("url", e.target.value)} aria-invalid={Boolean(show("url"))} />
          {show("url") && <span className="text-[13px] text-cosmos-red-text">{show("url")}</span>}
        </label>
        <label className={labelClass}>
          공고명 *
          <input className={fieldClass} value={state.title} maxLength={200} onChange={(e) => set("title", e.target.value)} aria-invalid={Boolean(show("title"))} />
          {show("title") && <span className="text-[13px] text-cosmos-red-text">{show("title")}</span>}
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className={labelClass}>
            기관 *
            <input className={fieldClass} value={state.agency} maxLength={120} onChange={(e) => set("agency", e.target.value)} aria-invalid={Boolean(show("agency"))} />
            {show("agency") && <span className="text-[13px] text-cosmos-red-text">{show("agency")}</span>}
          </label>
          <label className={labelClass}>
            마감 날짜 · 시각 *
            <input className={fieldClass} type="datetime-local" value={state.deadline} disabled={state.deadlineOpen} onChange={(e) => set("deadline", e.target.value)} aria-invalid={Boolean(show("deadline"))} />
            {/* 43차 Q20 — 마감이 없는 공고(상시 · 미정) */}
            <span className="flex items-center gap-1.5 text-[13px] text-cosmos-secondary">
              <input type="checkbox" checked={state.deadlineOpen} onChange={(e) => set("deadlineOpen", e.target.checked)} /> 상시 · 미정(마감이 아직 없음)
            </span>
            {show("deadline") && <span className="text-[13px] text-cosmos-red-text">{show("deadline")}</span>}
          </label>
          <label className={labelClass}>
            참가신청 · 등록 · 협정 마감(있으면)
            <input className={fieldClass} type="datetime-local" value={state.applyDeadline} onChange={(e) => set("applyDeadline", e.target.value)} aria-invalid={Boolean(show("applyDeadline"))} />
            <span className="text-[13px] leading-5 text-cosmos-muted">입찰 마감보다 이르면 이 날로 D-day 를 셉니다.</span>
            {show("applyDeadline") && <span className="text-[13px] text-cosmos-red-text">{show("applyDeadline")}</span>}
          </label>
          {/* 43차 Q18 — 사람이 본업으로 확인하면 낱말 규칙(비추천)으로 접지 않는다 · 판정 · 점수는 그대로 */}
          <label className="flex items-start gap-2 text-[14px] text-cosmos-text sm:col-span-2">
            <input type="checkbox" className="mt-1" checked={state.coreConfirmed} onChange={(e) => set("coreConfirmed", e.target.checked)} />
            <span>
              사람이 본업으로 확인했습니다
              <span className="block text-[13px] leading-5 text-cosmos-muted">공고명 낱말만 보고 「비추천」으로 접지 않습니다. 판정 · 점수는 그대로입니다.</span>
            </span>
          </label>
        </div>
        <fieldset className="flex min-w-0 flex-col gap-2">
          <legend className="text-[14px] text-cosmos-secondary">누구를 모집하나요? *</legend>
          <div className="flex flex-col gap-2">
            {RECRUIT_CHOICES.map((choice) => (
              <label key={choice.key} className="flex cursor-pointer items-start gap-2 rounded-lg border border-cosmos-border px-3 py-2 text-[14px] has-[:checked]:border-cosmos-cyan/60">
                <input type="radio" name="recruit" className="mt-1" checked={state.recruit === choice.key} onChange={() => set("recruit", choice.key)} />
                <span className="min-w-0">
                  <span className="font-medium text-cosmos-text">{choice.label}</span>
                  <span className="block text-[13px] leading-5 text-cosmos-muted">{choice.help}</span>
                </span>
              </label>
            ))}
          </div>
          {show("recruit") && <span className="text-[13px] text-cosmos-red-text">{show("recruit")}</span>}
        </fieldset>

        <details className="rounded-lg border border-cosmos-border px-3 py-2">
          <summary className="mc-focus cursor-pointer text-[14px] text-cosmos-secondary">더 적기(선택) — 공고일 · 접수방식 · 사업비 · 지역 · 공고문 파일 …</summary>
          <div className="mt-3 flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className={labelClass}>
                공고일
                <input className={fieldClass} type="date" value={state.publishedOn} onChange={(e) => set("publishedOn", e.target.value)} />
                {/* 43차 M15 · SOURCE-07 — 공고일이 없으면 신규로 세지 않는다(신규+여유 · 「가장 먼저 볼 것」에 오르지 못한다) */}
                {!state.publishedOn && <span className="text-[13px] leading-5 text-cosmos-amber">공고일이 없으면 신규로 세지 않습니다.</span>}
              </label>
              <label className={labelClass}>
                사업비(원문 숫자 그대로)
                <input className={fieldClass} placeholder="예: 150,000,000원" value={state.budgetText} maxLength={300} onChange={(e) => set("budgetText", e.target.value)} />
              </label>
            </div>
            <fieldset className="flex min-w-0 flex-col gap-1">
              <legend className="text-[14px] text-cosmos-secondary">접수방식</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {SUBMIT_METHODS.map((method) => (
                  <label key={method} className="flex items-center gap-1.5 text-[14px] text-cosmos-text">
                    <input
                      type="checkbox"
                      checked={state.methods.includes(method)}
                      onChange={(e) => set("methods", e.target.checked ? [...state.methods, method] : state.methods.filter((m) => m !== method))}
                    />
                    {method}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className={labelClass}>
                지역 제한
                <select className={fieldClass} value={regionChoiceOf(state)} onChange={(e) => setState((prev) => chooseRegion(prev, e.target.value))}>
                  <option value="">모름(비워 둠)</option>
                  {REGION_PRESETS.map((region) => (
                    <option key={region} value={region}>{region}</option>
                  ))}
                  <option value={REGION_CUSTOM}>그 밖 — 직접 적기</option>
                </select>
                {state.regionCustom && (
                  <input
                    className={fieldClass}
                    aria-label="지역 제한 직접 적기"
                    placeholder="예: 서울특별시 · 경기도 (「○○ 제외」는 확인 필요로 둡니다)"
                    value={state.regionLimit}
                    maxLength={300}
                    onChange={(e) => set("regionLimit", e.target.value)}
                  />
                )}
              </label>
              <label className={labelClass}>
                어디서 찾았나(출처 층)
                <select className={fieldClass} value={state.layer} onChange={(e) => set("layer", e.target.value as ManualFormState["layer"])}>
                  <option value="">모름</option>
                  {SOURCE_LAYERS.map((layer) => (
                    <option key={layer} value={layer}>{`${layer} — ${SOURCE_LAYER_HELP[layer]}`}</option>
                  ))}
                </select>
              </label>
              <label className={labelClass}>
                설명회
                <input className={fieldClass} placeholder="예: 10/20 14:00 필수 참석" value={state.briefing} maxLength={300} onChange={(e) => set("briefing", e.target.value)} />
              </label>
              <label className={labelClass}>
                공동수급(여러 회사가 함께 참가)
                <input className={fieldClass} placeholder="예: 공동이행 허용 · 공동수급 불허" value={state.joint} maxLength={300} onChange={(e) => set("joint", e.target.value)} />
              </label>
            </div>
            <label className={labelClass}>
              공고 본문 붙여넣기
              <textarea className={`${fieldClass} min-h-28 py-2`} value={state.bodyText} maxLength={50000} onChange={(e) => set("bodyText", e.target.value)} />
            </label>
            <label className={labelClass}>
              공고문 파일(pdf · hwp · hwpx · docx · 20MB 까지)
              <input type="file" accept={DOCUMENT_ACCEPT} className="text-[14px] text-cosmos-secondary" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              {fileProblem && <span className="text-[13px] text-cosmos-red-text">{fileProblem}</span>}
            </label>
          </div>
        </details>

        {duplicate && (
          <InlineAlert tone="info" role="status">
            새로 만들지 않았습니다 — {duplicate.reason ?? "이미 있는 공고입니다"}.{" "}
            {duplicate.id && (
              <Link href={existingHref(duplicate.id)} className="underline" onClick={onClose}>
                {existingLabel(duplicate.id, lookup)} 열기 →
              </Link>
            )}
            {duplicate.maybe && (
              <>
                {" "}다른 공고라면{" "}
                <button type="button" className="underline" onClick={() => { setConfirmNew(true); setDuplicate(null); }}>
                  그래도 새로 넣기
                </button>
                를 누른 뒤 「넣기」를 다시 누르세요.
              </>
            )}
          </InlineAlert>
        )}
        {failure && (
          <InlineAlert tone="fail">
            {failure}
            {stale && editingId && (
              <>
                {" "}
                <button type="button" className="mc-focus rounded font-medium underline" data-stale-reload onClick={() => void reloadBase()}>
                  다시 불러오기
                </button>{" "}
                (쓰신 글은 그대로 두고 새 저장 시각만 받습니다)
              </>
            )}
          </InlineAlert>
        )}
        {reloadNote && <InlineAlert tone="info" role="status">{reloadNote}</InlineAlert>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" onClick={requestClose}>그만두기</Button>
          <Button variant="primary" type="submit" disabled={busy}>{busy ? "저장 중…" : editingId ? "고친 것 저장" : "넣기"}</Button>
        </div>
      </form>
    </dialog>
  );
}

// ---------------------------------------------------------------------------
// 패널
// ---------------------------------------------------------------------------

export default function ManualInboxPanel({
  organizationId,
  items,
  lookup,
  focusId,
  nowMs,
  loading,
  listError = null,
  onChanged,
}: {
  organizationId: string;
  /** 통합 목록을 못 읽었을 때 그 사유 — 이 탭에도 보인다(39차 FRONTEND-08 · 「모두 마감」으로 읽혔다). */
  listError?: string | null;
  /** 통합 목록을 받는 중인가 — 그동안 「0건」을 최종처럼 적지 않는다. */
  loading: boolean;
  /** 통합 목록의 직접 넣은 공고(서버가 판정 · 순위를 매긴 것). */
  items: UnifiedOpportunity[];
  /** 통합 목록에서 공고 찾기 — 후보함 「이미 있음(n위 · 판정)」. */
  lookup: (id: string) => UnifiedOpportunity | undefined;
  focusId: string | null;
  nowMs: number | null;
  /** 넣기 · 고치기 · 지우기 뒤 — 통합 목록을 다시 받는다(판정 · 순위는 서버가 다시 매긴다). */
  onChanged: () => void;
}) {
  const [notices, setNotices] = useState<ManualNotice[] | null>(null);
  const [inbox, setInbox] = useState<InboxEntry[] | null>(null);
  const [sites, setSites] = useState<WatchSite[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // 45차 M12 — 결과 글은 누른 곳 가까이(후보함 단추의 결과가 약 700px 위 화면 밖에 떴다) · 지운 줄 · 버린 후보는 응답 즉시 뺀다(다시 읽기 7~10초 동안 남았다)
  const [messageAt, setMessageAt] = useState<"list" | "inbox">("list");
  const [gone, setGone] = useState<ReadonlySet<string>>(() => new Set());
  const [dialog, setDialog] = useState<{ initial: ManualFormState; editingId: string | null; expectedUpdatedAt: string | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  // 43차 M28 — 붙여 넣은 글도 임시 저장한다(세션이 끝나 새로 고쳐도 남는다)
  // 회사가 바뀌면 페이지가 이 패널을 새로 그린다(key) — 처음 읽은 회사의 열쇠로 충분하다
  const [paste, setPasteState] = useState(() => loadDraft(pasteDraftKey(organizationId)));
  // 45차 H2 — 되살린 붙여 넣을 글도 한 줄로 알린다(말없이 되살아나 남이 쓰던 글인지 헷갈렸다)
  const [pasteRestored, setPasteRestored] = useState(() => Boolean(loadDraft(pasteDraftKey(organizationId))));
  const setPaste = (value: string) => {
    setPasteState(value);
    saveDraft(pasteDraftKey(organizationId), value);
  };
  const viewer = useViewerLock();
  // 고치기를 시작할 때 읽은 목록(43차 M25) — 저장할 때 함께 보내 그사이 남이 바꿨으면 막는다
  const [siteBase, setSiteBase] = useState<WatchSiteInput[] | null>(null);
  const [siteStale, setSiteStale] = useState(false);
  const [pasteResult, setPasteResult] = useState<InboxPasteResult | null>(null);
  const [discarding, setDiscarding] = useState<{ id: string; reason: string } | null>(null);
  const [editingSites, setEditingSites] = useState<WatchSiteInput[] | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    Promise.all([listManualNotices(organizationId), getNoticeInbox(organizationId), getWatchlist(organizationId)])
      .then(([n, i, w]) => {
        setNotices(n);
        setInbox(i);
        setSites(w);
        setLoadError(null);
      })
      .catch((error: unknown) => setLoadError(describeFailure(error, "직접 넣기 · 후보함을 읽지 못했습니다.")));
  }, [organizationId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const noticeById = useMemo(() => new Map((notices ?? []).map((n) => [n.id, n])), [notices]);
  const ranked = useMemo(() => [...items].filter((item) => !gone.has(item.id)).sort((a, b) => (a.source_rank ?? 1e9) - (b.source_rank ?? 1e9)), [items, gone]);
  const offList = useMemo(() => {
    // 40차 마지막 검토 — 목록 오류면 판정 · 순위 줄을 그리지 않으니 넣어 둔 공고 **모두**를 고치기 · 지우기 줄로(지난 응답의 items 에 든 공고가 빠졌다)
    if (listError) return (notices ?? []).filter((notice) => !gone.has(notice.id));
    const listed = new Set(items.map((item) => item.id));
    return (notices ?? []).filter((notice) => !listed.has(notice.id) && !gone.has(notice.id));
  }, [items, notices, listError, gone]);
  const pending = (inbox ?? []).filter((e) => e.status === "pending" && !gone.has(e.id));
  const withUrl = (sites ?? []).filter((s) => s.url);
  const openedToday = withUrl.filter((s) => s.last_opened_at && openedText(s.last_opened_at, nowMs).startsWith("오늘")).length;
  // 44차 S3 — 사람별: 「나 n/m」(회사 하나로만 세면 남이 연 것을 내가 본 줄 알고 건너뛸 수 있었다 · 로그인 없는 로컬은 없음)
  const me = readCurrentUser()?.user ?? null;
  const openedByMe = me
    ? withUrl.filter((s) => s.last_opened_at && s.last_opened_by === me && openedText(s.last_opened_at, nowMs).startsWith("오늘")).length
    : null;

  /** `task` 가 글을 돌려주면 그 글을 알림으로(올린 공고문의 조항을 찾았는지 · 39차 FRONTEND-03). */
  const run = async (task: () => Promise<unknown>, done: string, after: { goneId?: string; at?: "list" | "inbox" } = {}) => {
    setBusy(true);
    setMessage(null);
    setMessageAt(after.at ?? "list");
    try {
      const said = await task();
      if (after.goneId) setGone((prev) => new Set(prev).add(after.goneId as string));
      setMessage(typeof said === "string" && said ? said : done);
      reload();
      onChanged();
    } catch (error: unknown) {
      setMessage(describeFailure(error, "처리하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  const submitPaste = async (preview = false) => {
    if (!paste.trim()) {
      setMessageAt("inbox");
      setMessage("붙여 넣을 글이 없습니다 — 위 칸에 GPT 결과(표 · 링크)를 붙여 넣으세요.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const result = await pasteNoticeInbox(organizationId, paste, preview);
      setPasteResult(result);
      if (preview) return;
      // 43차 SOURCE-15 — 300줄을 넘어 안 읽은 줄이 있으면 입력 칸을 비우지 않는다(어디서부터 다시 붙일지 아래에 적는다)
      if (!result.first_unread_line) setPaste("");
      reload();
    } catch (error: unknown) {
      setMessageAt("inbox");
      setMessage(describeFailure(error, "붙여 넣은 글을 읽지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-6" data-manual-panel>
      <section aria-labelledby="manual-head" className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="manual-head" className="text-[17px] font-semibold text-cosmos-text">직접 넣은 공고 {loading || listError ? "…" : `${items.length}건`}</h2>
          {viewer ? (
            <Badge tone="muted" title={VIEWER_LOCK_REASON}>{VIEWER_LOCK_LABEL}</Badge>
          ) : (
            <Button variant="primary" onClick={() => setDialog({ initial: EMPTY_FORM, editingId: null, expectedUpdatedAt: null })}>+ 공고 직접 넣기</Button>
          )}
        </div>
        {viewer && <p className="text-[13px] text-cosmos-muted" data-viewer-lock>{VIEWER_LOCK_REASON}</p>}
        <p className="text-[14px] leading-6 text-cosmos-secondary">
          나라장터 · 기업마당에 없는 공고(기관 홈페이지 · 이메일 · PMS 접수)를 넣으면 같은 규칙으로 판정하고 「직접 넣음」 안에서 순위를 매깁니다.
          직접 넣은 공고는 <strong className="text-cosmos-text">공고문 원문을 사람이 확인하기 전에는 「가능」이 되지 않습니다</strong> — 공고문 파일을 올리면 자격 조항을 읽어 근거를 붙입니다. 원문을 직접 보고 자격이 맞으면 줄마다 「원문 확인함 — 가능으로」(편집자 · 관리자 · 이유 한 줄 · 되돌리기 있음)를 누릅니다 — 누르기 전에는 줄의 판정이 「확인 필요」로 남습니다.
        </p>
        {loadError && <InlineAlert tone="fail">{loadError}</InlineAlert>}
        {message && messageAt === "list" && <InlineAlert tone="info" role="status">{message}</InlineAlert>}
        {listError ? (
          // 40차 FRONT-04 · MANUAL-02 — 목록 오류면 「계산하는 중 · 0건 · 아직 없음」 대신 오류만 · 넣은 공고는 아래에서 고치거나 지울 수 있다
          <InlineAlert tone="warn">
            목록을 읽지 못했습니다 — {listError} (직접 넣은 공고의 판정 · 순위를 지금 보일 수 없습니다 · 넣어 둔 공고는 아래에서 고치거나 지울 수 있습니다)
          </InlineAlert>
        ) : loading && ranked.length === 0 ? (
          <p className="text-[14px] text-cosmos-muted" role="status">판정 · 순위를 계산하는 중…</p>
        ) : ranked.length === 0 ? (
          <p className="rounded-lg border border-dashed border-cosmos-border px-3 py-4 text-[14px] text-cosmos-muted">
            아직 직접 넣은 공고가 없습니다. 「+ 공고 직접 넣기」나 아래 후보함의 「정식으로 넣기」로 넣으세요.
          </p>
        ) : (
          <ul className="flex flex-col gap-2" role="list">
            {ranked.map((item) => {
              const verdict = verdictOf(item.eligibility_gate, item.participation);
              const raw = noticeById.get(item.id);
              const focused = focusId === item.id;
              // 2.0.6 — D-day 는 실제 마감(위 입력 창 안내대로 참가신청 · 등록 마감이 이르면 그 날 · 이번 주 할 일 `deadlineOf` · 서버 실무순과 같은 셈)
              const pair = pairOf(item, item.deadline);
              const primary = effectiveDeadline(pair);
              const byRegistration = pair.qualification != null && primary === pair.qualification && primary !== item.deadline;
              return (
                <li key={item.id} data-manual-row={item.id} className={`mc-panel flex min-w-0 flex-col gap-1.5 p-3 ${focused ? "ring-1 ring-cosmos-blue-text/70" : ""}`}>
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[14px]">
                    <span className="tabular-nums text-cosmos-secondary">{item.source_rank ?? "–"}위/{item.source_total ?? items.length}</span>
                    <span style={{ color: TONE_COLORS[verdict.tone] }} title={verdict.title}>{verdict.label}</span>
                    <Badge tone="muted">{item.recruit_kind ?? "모집 대상 미상"}</Badge>
                    {item.source_layer && <Badge tone="muted">{item.source_layer}</Badge>}
                    <span className="ml-auto tabular-nums text-cosmos-secondary">
                      {byRegistration && <span className="text-cosmos-amber" title="입찰 마감보다 먼저 닫힙니다">{firstLabel(pair)} </span>}
                      {dDayText({ deadline: primary, periodKind: null, nowMs })}
                    </span>
                  </div>
                  <p className="break-keep text-[15px] font-medium leading-snug text-cosmos-text [overflow-wrap:anywhere]">{item.title}</p>
                  <p className="truncate text-[13px] text-cosmos-secondary">{item.agency}</p>
                  {/* 41차 FRONT-R40-07 — 「전체」 탭의 같은 공고 행과 같은 꼬리표(주제 확인 · 규모 큼 · 분류 칸) */}
                  <PracticalTags item={item} withGroup />
                  {item.gate_reason && <p className="text-[13px] leading-5 text-cosmos-secondary">{item.gate_reason}</p>}
                  {item.evidence_line && <p className="text-[13px] leading-5 text-cosmos-muted" data-evidence-line>{item.evidence_line}</p>}
                  {raw?.document && raw.document.status !== "ok" && (
                    <p className="text-[13px] text-cosmos-amber">올린 공고문에서 자격 조항을 찾지 못했습니다{raw.document.note ? ` — ${raw.document.note}` : ""}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <a href={item.detail_url ?? undefined} target="_blank" rel="noreferrer noopener" className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline">
                      공고 원문 ↗
                    </a>
                    {!viewer && (<>
                    <label className="mc-focus cursor-pointer rounded text-[14px] text-cosmos-cyan hover:underline">
                      {raw?.document ? "공고문 다시 올리기" : "공고문 올리기"}
                      <input
                        type="file"
                        accept={DOCUMENT_ACCEPT}
                        className="sr-only"
                        onChange={(e) => {
                          const picked = e.target.files?.[0];
                          e.target.value = "";
                          if (!picked) return;
                          const problem = documentProblem(picked);
                          if (problem) {
                            setMessage(problem);
                            return;
                          }
                          void run(() => uploadManualDocument(organizationId, item.id, picked).then((saved) => uploadMessage(saved.document)), "공고문을 올렸습니다.");
                        }}
                      />
                    </label>
                    {raw && (
                      <button type="button" className="mc-focus rounded text-[14px] text-cosmos-cyan hover:underline" onClick={() => setDialog({ initial: fromNotice(raw), editingId: raw.id, expectedUpdatedAt: raw.updated_at })}>
                        고치기
                      </button>
                    )}
                    {confirmDelete === item.id ? (
                      <span className="flex flex-wrap items-center gap-2 text-[14px]">
                        정말 지울까요?
                        <Button size="sm" variant="danger" disabled={busy} onClick={() => { setConfirmDelete(null); void run(() => deleteManualNotice(organizationId, item.id), "지웠습니다.", { goneId: item.id }); }}>지우기</Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>그만두기</Button>
                      </span>
                    ) : (
                      <button type="button" className="mc-focus rounded text-[14px] text-cosmos-muted hover:text-cosmos-text" onClick={() => setConfirmDelete(item.id)}>
                        지우기
                      </button>
                    )}
                    </>)}
                    {/* 43차 TEAM-03 — 누가 · 언제 고쳤는지 */}
                    {raw && (
                      <span className="text-[12px] text-cosmos-muted">
                        {raw.updated_by || raw.created_by ? `${raw.updated_by ? (raw.updated_by_name ?? raw.updated_by) : (raw.created_by_name ?? raw.created_by)} · ` : ""}
                        {formatDateTime(raw.updated_at)} {raw.updated_by ? "고침" : "넣음"}
                      </span>
                    )}
                  </div>
                  {/* 44차 M4 · M6 — 신청 · 참여 결정과 「원문 확인함 — 가능으로」 */}
                  {raw && <ManualConfirm organizationId={organizationId} raw={raw} item={item} viewer={viewer} onChanged={() => { reload(); onChanged(); }} />}
                </li>
              );
            })}
          </ul>
        )}
        {(listError || !loading) && offList.length > 0 && (
          // 통합 목록은 마감 지난 공고를 빼고 온다 — 그래도 넣은 공고는 고치거나 지울 수 있어야 한다(38차 검토).
          // 목록 오류여도 원본 목록(직접 넣기 저장본)의 고치기 · 지우기는 보인다(40차 MANUAL-02 — 문제의 공고를 고칠 길이 사라졌다).
          <div className="flex min-w-0 flex-col gap-2" data-manual-offlist>
            <p className="text-[14px] text-cosmos-secondary">
              {listError
                ? `넣어 둔 공고 ${offList.length}건 — 목록을 읽지 못해 판정 · 순위 없이 보입니다. 날짜를 잘못 적었으면 고치세요.`
                : `목록에 없는 직접 넣은 공고 ${offList.length}건 — 마감이 지났습니다. 필터의 「마감된 건도 포함」을 켜면 판정과 함께 보입니다. 마감일을 잘못 적었으면 고치세요.`}
            </p>
            <ul className="flex flex-col gap-1" role="list">
              {offList.map((raw) => (
                <li key={raw.id} data-manual-row={raw.id} className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-[14px]">
                  <span className="min-w-0 text-cosmos-text [overflow-wrap:anywhere]">{raw.title}</span>
                  <span className="tabular-nums text-cosmos-muted">마감 {formatDateTime(raw.deadline)}</span>
                  {!viewer && (<>
                  <button type="button" className="mc-focus rounded text-cosmos-cyan hover:underline" onClick={() => setDialog({ initial: fromNotice(raw), editingId: raw.id, expectedUpdatedAt: raw.updated_at })}>
                    고치기
                  </button>
                  {confirmDelete === raw.id ? (
                    <span className="flex flex-wrap items-center gap-2">
                      정말 지울까요?
                      <Button size="sm" variant="danger" disabled={busy} onClick={() => { setConfirmDelete(null); void run(() => deleteManualNotice(organizationId, raw.id), "지웠습니다.", { goneId: raw.id }); }}>지우기</Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>그만두기</Button>
                    </span>
                  ) : (
                    <button type="button" className="mc-focus rounded text-cosmos-muted hover:text-cosmos-text" onClick={() => setConfirmDelete(raw.id)}>
                      지우기
                    </button>
                  )}
                  </>)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section aria-labelledby="inbox-head" className="flex min-w-0 flex-col gap-3">
        <h2 id="inbox-head" className="text-[17px] font-semibold text-cosmos-text">확인 전 후보함 {pending.length}건</h2>
        {message && messageAt === "inbox" && <InlineAlert tone="info" role="status">{message}</InlineAlert>}
        <p className="text-[14px] leading-6 text-cosmos-secondary">
          GPT 나 사람이 찾은 결과(표 · 링크)를 붙여 넣으면 줄마다 링크 · 공고명 · 기관 · 날짜 글자만 뽑아 둡니다. <strong className="text-cosmos-text">점수 · 판정은 붙이지 않습니다</strong> —
          원문을 확인하고 「정식으로 넣기」를 누르면 판정이 붙습니다. https 링크만 받고, 200KB · 300줄까지 읽습니다.
        </p>
        <label className={labelClass}>
          붙여 넣을 글
          <textarea
            className={`${fieldClass} min-h-32 py-2`}
            value={paste}
            disabled={viewer}
            maxLength={MAX_PASTE_CHARS}
            placeholder={"| 공고 | 기관 | 마감 | 링크 |\n| AI 교육 운영 | ○○재단 | 10/30 | [바로가기](https://…) |"}
            onChange={(e) => {
              setPaste(e.target.value);
              setPasteRestored(false);
            }}
          />
        </label>
        {pasteRestored && paste && (
          <InlineAlert tone="info" role="status">저장하지 않은 붙여 넣을 글을 되살렸습니다 — 그대로 넣거나 지우고 새로 붙여 넣으세요.</InlineAlert>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {viewer ? (
            <Badge tone="muted" title={VIEWER_LOCK_REASON}>{VIEWER_LOCK_LABEL}</Badge>
          ) : (
            <>
              <Button variant="ghost" disabled={busy} onClick={() => void submitPaste(true)}>미리 보기</Button>
              <Button variant="secondary" disabled={busy} onClick={() => void submitPaste()}>후보함에 넣기</Button>
            </>
          )}
          {pasteResult && (
            <span role="status" className="text-[14px] text-cosmos-secondary">
              {pasteResult.preview ? "미리 보기(아직 넣지 않음) — " : ""}
              새 후보 {pasteResult.added}건 · 이미 후보함에 있음 {pasteResult.already_in_inbox} · 저장본에 있는 공고 {pasteResult.existing}{pasteResult.maybe_existing ? ` · 같은 공고일 수 있음 ${pasteResult.maybe_existing}` : ""} · 링크 없는 줄 {pasteResult.lines_without_link}
              {pasteResult.preview && pasteResult.entries.length > 0 && ` · 넣을 후보: ${pasteResult.entries.slice(0, 5).map((e) => e.title ?? "(공고명 못 뽑음)").join(" / ")}${pasteResult.entries.length > 5 ? " …" : ""}`}
              {pasteResult.first_unread_line && ` · ${pasteResult.first_unread_line}번째 줄부터 다시 붙여 넣으세요(「${pasteResult.first_unread_text ?? ""}」)`}
              {pasteResult.rejected.length > 0 && ` · 받지 않은 링크 ${pasteResult.rejected.length}(${[...new Set(pasteResult.rejected.map((r) => r.reason))].join(" · ")})`}
              {pasteResult.truncated_lines > 0 && ` · 300줄을 넘어 안 읽은 줄 ${pasteResult.truncated_lines}`}
              {(pasteResult.refused_full ?? 0) > 0 && ` · 확인 전 후보가 500건이라 받지 못한 줄 ${pasteResult.refused_full} — 위 후보를 넣거나 버린 뒤 다시 붙여 넣으세요`}
            </span>
          )}
        </div>
        {pending.length > 0 && (
          <ul className="flex flex-col divide-y divide-cosmos-border rounded-lg border border-cosmos-border" role="list">
            {pending.map((entry) => (
              <li key={entry.id} className="flex min-w-0 flex-col gap-1 px-3 py-2" data-inbox-row>
                <p className="break-keep text-[14px] font-medium text-cosmos-text [overflow-wrap:anywhere]">{entry.title ?? "(공고명을 뽑지 못함 — 원문에서 확인)"}</p>
                <p className="text-[13px] text-cosmos-secondary">
                  {[entry.agency, entry.published_text && `공고일 「${entry.published_text}」`, entry.date_text && `마감 「${entry.date_text}」`].filter(Boolean).join(" · ") || "기관 · 날짜 못 뽑음"}
                </p>
                {/* 43차 Q19 — GPT 가 적은 판단 · 제외 사유(점수 · 판정 없음) */}
                {entry.gpt_note && <p className="text-[13px] text-cosmos-amber">{entry.gpt_note}</p>}
                <div className="flex flex-wrap items-center gap-2 text-[14px]">
                  <a href={entry.url} target="_blank" rel="noreferrer noopener" className="mc-focus max-w-full truncate rounded text-cosmos-cyan hover:underline">원문 ↗</a>
                  {/* 44차 TEAM-R36-05 — 공고명만 같으면 단정하지 않는다: 「같은 공고일 수 있음 →」과 「정식으로 넣기」를 함께 */}
                  {!entry.existing_id && entry.maybe_existing_id && (
                    <Link href={existingHref(entry.maybe_existing_id)} className="mc-focus rounded text-cosmos-amber hover:underline">
                      같은 공고일 수 있음 →
                    </Link>
                  )}
                  {entry.existing_id ? (
                    <Link href={existingHref(entry.existing_id)} className="mc-focus rounded text-cosmos-cyan hover:underline">
                      {existingLabel(entry.existing_id, lookup)} →
                    </Link>
                  ) : viewer ? null : (
                    <button
                      type="button"
                      className="mc-focus rounded text-cosmos-cyan hover:underline"
                      onClick={() => setDialog({ initial: { ...EMPTY_FORM, url: entry.url, title: entry.title ?? "", agency: entry.agency ?? "", inboxId: entry.id, publishedOn: isoDay(entry.published_text) }, editingId: null, expectedUpdatedAt: null })}
                    >
                      정식으로 넣기
                    </button>
                  )}
                  {viewer ? null : discarding?.id === entry.id ? (
                    <span className="flex min-w-0 flex-wrap items-center gap-2">
                      <input
                        className={`${fieldClass} min-h-9 w-56 max-w-full`}
                        aria-label="버리는 사유"
                        placeholder="사유(예: 교육 아님 · 지역 다름)"
                        value={discarding.reason}
                        maxLength={300}
                        onChange={(e) => setDiscarding({ id: entry.id, reason: e.target.value })}
                      />
                      <Button size="sm" variant="danger" disabled={busy || !discarding.reason.trim()} onClick={() => { const reason = discarding.reason; setDiscarding(null); void run(() => discardInboxEntry(organizationId, entry.id, reason), "후보를 버렸습니다(사유를 남김).", { goneId: entry.id, at: "inbox" }); }}>
                        버리기
                      </Button>
                      {!discarding.reason.trim() && <span className="text-[13px] text-cosmos-muted">사유를 적으면 버릴 수 있습니다</span>}
                      <Button size="sm" variant="ghost" onClick={() => setDiscarding(null)}>그만두기</Button>
                    </span>
                  ) : (
                    <button type="button" className="mc-focus rounded text-cosmos-muted hover:text-cosmos-text" onClick={() => setDiscarding({ id: entry.id, reason: "" })}>
                      버리기(사유)
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="watch-head" className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="watch-head" className="text-[17px] font-semibold text-cosmos-text">오늘 열어 본 곳 {openedToday}/{withUrl.length}{openedByMe !== null && ` · 나 ${openedByMe}/${withUrl.length}`}</h2>
          {viewer ? (
            <Badge tone="muted" title={VIEWER_LOCK_REASON}>{VIEWER_LOCK_LABEL}</Badge>
          ) : editingSites === null ? (
            <Button
              variant="secondary"
              size="sm"
              // 목록을 못 읽었으면 막는다 — 빈 목록에서 고쳐 저장하면 저장된 목록 전체를 덮어썼다(39차 FRONTEND-04)
              disabled={sites === null || Boolean(loadError)}
              title={sites === null || loadError ? "목록을 읽지 못해 고칠 수 없습니다 — 화면을 새로 고친 뒤 다시 누르세요" : undefined}
              onClick={() => {
                setSiteError(null);
                setSiteStale(false);
                const rows = (sites ?? []).map(({ id, name, url, layer, memo }) => ({ id, name, url, layer, memo }));
                setSiteBase(rows);
                setEditingSites(rows);
              }}
            >
              고치기 · 더하기
            </Button>
          ) : null}
        </div>
        <p className="text-[14px] leading-6 text-cosmos-secondary">
          BidPilot 이 자동으로 읽지 않는 기관 게시판입니다. 「열기」를 누르면 새 탭으로 열리고 연 시각과 연 사람만 적습니다 — 서버가 그 사이트를 읽지 않습니다{viewer ? "(열람자는 연 시각을 남기지 않습니다)" : ""}.
          거기서 맞는 공고를 찾으면 위 「공고 직접 넣기」로 넣으세요.
        </p>
        {editingSites === null ? (
          <ul className="flex flex-col divide-y divide-cosmos-border rounded-lg border border-cosmos-border" role="list">
            {(sites ?? []).map((site) => (
              <li key={site.id} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[14px]" data-watch-row>
                <span className="min-w-0 flex-1 break-keep font-medium text-cosmos-text">
                  {site.name}
                  {site.layer && <span className="ml-2 text-[12px] text-cosmos-muted">{site.layer}</span>}
                </span>
                <span className="text-[13px] text-cosmos-muted">{openedText(site.last_opened_at, nowMs, site.last_opened_by_name ?? site.last_opened_by)}</span>
                {site.url ? (
                  <a
                    href={site.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mc-focus rounded text-cosmos-cyan hover:underline"
                    onClick={() => {
                      // 열람자는 서버가 막는다(403) — 부르지 않고 사이트만 연다(43차 TEAM-05 · 오류를 삼켜 아무 안내도 없었다)
                      if (viewer) return;
                      void markWatchOpened(organizationId, site.id)
                        .then(reload)
                        .catch((error: unknown) => setMessage(`사이트는 새 탭으로 열었지만 연 시각을 적지 못했습니다 — ${describeFailure(error)}`));
                    }}
                  >
                    열기 ↗
                  </a>
                ) : (
                  <span className="text-[13px] text-cosmos-amber">주소 없음 — 「고치기 · 더하기」에서 넣기</span>
                )}
                {site.memo && <span className="basis-full text-[12px] leading-5 text-cosmos-muted">{site.memo}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex flex-col gap-2">
            {editingSites.map((site, index) => (
              <div key={site.id ?? `new-${index}`} data-watch-edit-row className={`grid min-w-0 gap-2 rounded-lg border p-2 sm:grid-cols-[1fr_1.4fr_auto] ${watchSiteProblem(site) ? "border-cosmos-amber/70" : "border-cosmos-border"}`}>
                <input className={fieldClass} aria-label="이름" value={site.name} onChange={(e) => setEditingSites(editingSites.map((s, i) => (i === index ? { ...s, name: e.target.value } : s)))} />
                <input className={fieldClass} aria-label="주소(https)" placeholder="https://…" value={site.url ?? ""} onChange={(e) => setEditingSites(editingSites.map((s, i) => (i === index ? { ...s, url: e.target.value } : s)))} />
                <Button size="sm" variant="ghost" onClick={() => setEditingSites(editingSites.filter((_, i) => i !== index))}>빼기</Button>
                <input className={`${fieldClass} sm:col-span-3`} aria-label="메모" placeholder="메모(선택)" value={site.memo ?? ""} onChange={(e) => setEditingSites(editingSites.map((s, i) => (i === index ? { ...s, memo: e.target.value } : s)))} />
                {watchSiteProblem(site) && <span className="text-[13px] text-cosmos-amber sm:col-span-3">{watchSiteProblem(site)}</span>}
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => setEditingSites([...editingSites, { name: "", url: "" }])}>+ 줄 더하기</Button>
              <span className="flex-1" />
              <Button size="sm" variant="ghost" onClick={() => { setEditingSites(null); setSiteStale(false); }}>그만두기</Button>
              {editingSites.some((s) => watchSiteProblem(s)) && (
                <span className="text-[13px] text-cosmos-amber">노란 테두리 줄을 고치면 저장할 수 있습니다</span>
              )}
              <Button
                size="sm"
                variant="primary"
                disabled={busy || editingSites.some((s) => watchSiteProblem(s))}
                onClick={() => {
                  const rows = editingSites.map((s) => ({ ...s, url: s.url?.trim() ? s.url.trim() : null }));
                  setBusy(true);
                  setSiteError(null);
                  // 저장이 끝난 뒤에만 편집을 닫는다 — 서버가 거절하면 고친 것을 그대로 두고 사유를 적는다(39차 FRONTEND-02)
                  saveWatchlist(organizationId, rows, siteBase ?? undefined)
                    .then(() => {
                      setEditingSites(null);
                      setMessage("목록을 저장했습니다.");
                      reload();
                    })
                    .catch((error: unknown) => {
                      setSiteStale(isStaleWrite(error));
                      setSiteError(describeFailure(error, "목록을 저장하지 못했습니다."));
                    })
                    .finally(() => setBusy(false));
                }}
              >
                저장
              </Button>
            </div>
            {siteError && (
              <InlineAlert tone="fail">
                {siteStale ? (
                  <>
                    {siteError}{" "}
                    <button type="button" className="mc-focus rounded font-medium underline" onClick={() => { setEditingSites(null); setSiteStale(false); setSiteError(null); reload(); }}>
                      다시 불러오기
                    </button>
                    {" "}(지금 고친 것은 버려집니다 — 새 목록에서 다시 고치세요)
                  </>
                ) : (
                  <>{siteError} — 고친 것은 그대로 있습니다. 틀린 줄을 고친 뒤 다시 저장하세요.</>
                )}
              </InlineAlert>
            )}
            <p className="text-[13px] text-cosmos-muted">주소는 https:// 로 시작하는 것만 받습니다.</p>
          </div>
        )}
      </section>

      {dialog && (
        <ManualDialog
          organizationId={organizationId}
          open
          initial={dialog.initial}
          editingId={dialog.editingId}
          expectedUpdatedAt={dialog.expectedUpdatedAt}
          lookup={lookup}
          onClose={() => setDialog(null)}
          onSaved={(text) => {
            // 후보함 「정식으로 넣기」에서 연 창이면 결과는 후보함 머리에 · 넣은 후보 줄은 바로 뺀다
            const inboxId = dialog.initial.inboxId;
            if (inboxId) setGone((prev) => new Set(prev).add(inboxId));
            setMessageAt(inboxId ? "inbox" : "list");
            setDialog(null);
            setMessage(text);
            reload();
            onChanged();
          }}
        />
      )}
    </div>
  );
}
