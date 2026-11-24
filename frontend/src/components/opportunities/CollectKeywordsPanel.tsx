"use client";

/**
 * 「찾는 낱말」 패널 (2.0.7 · 대표 10-27 「낱말 추가를 대시보드에서 할 수 있게 · 그리고 바로 재검색」) — 대시보드 「오늘 · 이번 주」 띠와 사업기회가 함께 쓴다.
 *
 * 추가 낱말 칩(다시 찾기 · 지우기) · 입력칸 + 「더하고 바로 찾기」 · 결과 한 줄 · 바로 찾기를 못 한 사유 한 줄 · 기본 낱말(접어 둠 · 고칠 수 없음).
 * 판단과 문장은 `lib/collectKeywords` 하나다. 읽는 중 · 못 읽음 · 비어 있음을 가른다(못 읽었는데 「더한 낱말 없음」이라 적지 않는다).
 * 열람자는 보기만 — 막는 일은 서버가 한다(403). 저장은 처음 읽은 시각을 함께 보내 그사이 남이 바꿨으면 409 「다시 불러오기」(43차 M25).
 */

import Link from "next/link";
import { useCallback, useEffect, useId, useState, type FormEvent, type ReactNode } from "react";

import { Badge, Button, InlineAlert } from "@/components/ui/primitives";
import { addCollectKeyword, getCollectKeywords, isStaleWrite, removeCollectKeyword, searchCollectKeyword } from "@/lib/api";
import {
  keywordFullReason,
  keywordInputProblem,
  keywordNextCollect,
  keywordSearchLock,
  keywordSearchSummary,
  normalizeKeyword,
} from "@/lib/collectKeywords";
import { requestConsent } from "@/lib/consentPrompt";
import { formatDateTime } from "@/lib/cosmos/format";
import { describeFailure } from "@/lib/errors";
import { SCREEN_NAMES } from "@/lib/terms";
import { useDeploymentMode } from "@/lib/useDeploymentMode";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import type { CollectKeywordsResponse, CollectKeywordsState, KeywordSearchResult } from "@/types/collectKeywords";
import type { CollectState } from "@/types/opportunity";

type Note =
  | { kind: "result"; result: KeywordSearchResult }
  | { kind: "info"; text: string }
  | { kind: "searchError"; text: string }
  | { kind: "error"; text: string; stale: boolean };

interface CollectKeywordsPanelProps {
  /** 바로 찾기가 끝났다 — 부르는 쪽이 목록을 다시 받는다 */
  onSearched?: (result: KeywordSearchResult) => void;
  /** 결과 한 줄 옆에 놓을 링크 · 단추(대시보드 「사업기회에서 결과 보기 →」 · 사업기회 「관련 낮음 포함해서 보기」) */
  resultAction?: (result: KeywordSearchResult) => ReactNode;
  onClose?: () => void;
  id?: string;
  /** 자동 받기 상태(서버 `collect_state`) — 「다음에 이 낱말로 찾는 때」를 고른다(꺼 둠 · 키트에는 아침 받기가 없다). 모르면 null. */
  collectState?: CollectState | null;
}

const chipButton =
  "mc-focus rounded-full px-2 py-0.5 text-[12px] text-cosmos-secondary hover:bg-cosmos-panel hover:text-cosmos-text disabled:cursor-not-allowed disabled:opacity-45";

export default function CollectKeywordsPanel({ onSearched, resultAction, onClose, id, collectState = null }: CollectKeywordsPanelProps) {
  const viewer = useViewerLock();
  // 노트북 · 키트(direct)는 그 PC 의 백엔드다 — 더한 낱말이 회사 서버로 가지 않는다(frontend-2)
  const localPc = useDeploymentMode()?.backend === "direct";
  const next = keywordNextCollect(collectState);
  const inputId = useId();
  const [state, setState] = useState<CollectKeywordsState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [word, setWord] = useState("");
  /** 지금 도는 일 — 「add」 또는 다시 찾기 · 지우는 낱말. 하나가 도는 동안 다른 단추는 잠근다(연타 · 겹침 방지). */
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);

  // 효과 본문에서 곧바로 setState 하지 않는다 — 응답이 온 뒤에만 상태를 건드린다.
  const fetchState = useCallback(
    () =>
      getCollectKeywords().then(
        (next) => {
          setState(next);
          setLoadError(null);
        },
        (error: unknown) => setLoadError(describeFailure(error, "찾는 낱말 목록을 읽지 못했습니다.")),
      ),
    [],
  );
  useEffect(() => {
    void fetchState();
  }, [fetchState]);

  const reread = () => {
    setLoadError(null);
    setNote(null);
    void fetchState();
  };

  /** 저장은 됐다 — 바로 찾기 결과 · 못 한 사유 · 안내 중 하나를 남긴다. `added` 는 더하기일 때 더한 낱말. */
  const apply = (response: CollectKeywordsResponse, added: string | null) => {
    setState(response.state);
    const saved = added ? `「${added}」 낱말을 더했습니다.` : null;
    if (response.search) {
      setNote({ kind: "result", result: response.search });
      onSearched?.(response.search);
    } else if (response.search_error) {
      // 더한 직후 못 찾았는데 지금 다시 찾을 수 있으면(문 꺼짐 · 오늘 횟수 다 씀이 아니면) 누를 곳을 적는다 —
      // 입력칸은 비었고 같은 낱말을 다시 적으면 「이미 있는 낱말」이라 「더하고 바로 찾기」가 꺼진다(frontend-7).
      const retry =
        added && keywordSearchLock(response.state, viewer, collectState) === null
          ? ` — 위 「${added}」 칩의 「다시 찾기」로 다시 찾을 수 있습니다`
          : "";
      const reason = retry ? response.search_error.replace(/\.\s*$/, "") : response.search_error;
      setNote({ kind: "searchError", text: `${saved ? `${saved} ` : ""}${reason}${retry}` });
    } else {
      setNote(saved ? { kind: "info", text: `${saved} ${next} 이 낱말로 찾습니다.` } : null);
    }
  };
  const fail = (error: unknown, fallback: string) =>
    setNote({ kind: "error", text: describeFailure(error, fallback), stale: isStaleWrite(error) });

  const searchLock = state ? keywordSearchLock(state, viewer, collectState) : null;
  const full = state ? state.extra.length >= state.max_extra : false;
  const problem = state ? keywordInputProblem(word, state) : null;
  const hint = full ? keywordFullReason(state?.max_extra ?? 0) : problem;
  const canAdd = state !== null && !viewer && busy === null && normalizeKeyword(word) !== "" && hint === null;

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!state || !canAdd) return;
    const clean = normalizeKeyword(word);
    setBusy("add");
    setNote(null);
    try {
      // 바로 찾기가 잠겼으면(문 꺼짐 · 오늘 횟수 다 씀) 저장만 한다 — 서버에 일부러 실패를 만들지 않는다.
      const response = await addCollectKeyword(clean, searchLock === null, state.updated_at);
      setWord("");
      apply(response, clean);
    } catch (error) {
      fail(error, "낱말을 더하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  }

  async function research(target: string) {
    setBusy(target);
    setNote(null);
    try {
      apply(await searchCollectKeyword(target), null);
    } catch (error) {
      fail(error, `「${target}」로 찾지 못했습니다.`);
    } finally {
      setBusy(null);
    }
  }

  async function remove(target: string) {
    if (!state) return;
    const expected = state.updated_at;
    const ok = await requestConsent({
      title: `「${target}」 낱말을 지울까요?`,
      body: `${next} 이 낱말로는 찾지 않습니다. 이 낱말로만 받은 공고는 그때 목록에서 빠질 수 있습니다.`,
      confirmLabel: "지우기",
      cancelLabel: "그만두기",
    });
    if (!ok) return;
    setBusy(target);
    setNote(null);
    try {
      const response = await removeCollectKeyword(target, expected);
      setState(response.state);
      setNote({ kind: "info", text: `「${target}」 낱말을 지웠습니다.` });
    } catch (error) {
      fail(error, "낱말을 지우지 못했습니다.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section id={id} aria-label="찾는 낱말" data-collect-keywords className="mc-panel flex flex-col gap-2.5 px-3 py-3 text-[13px] leading-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-[14px] font-semibold text-cosmos-text">나라장터 공고를 찾는 낱말</h2>
        {state && (
          <span className="text-[12px] text-cosmos-muted" data-keyword-searches>
            바로 찾기 오늘 {state.searches_today}/{state.searches_limit}
          </span>
        )}
        {viewer && (
          <Badge tone="muted" title={VIEWER_LOCK_REASON}>
            {VIEWER_LOCK_LABEL}
          </Badge>
        )}
        {onClose && (
          <button type="button" onClick={onClose} className="mc-focus ml-auto rounded px-1.5 text-[12px] text-cosmos-secondary hover:text-cosmos-text">
            닫기
          </button>
        )}
      </div>
      <p className="text-cosmos-secondary">
        낱말을 더하면 나라장터 목록을 받을 때 공고명에 그 낱말이 든 입찰도 함께 받습니다.{" "}
        {localPc ? (
          <>
            <strong className="text-cosmos-text">이 PC 전체에 적용됩니다</strong>(이 PC 의 모든 회사 · 모든 사람의 목록 · 회사 서버와는 따로).
          </>
        ) : (
          <>
            <strong className="text-cosmos-text">이 서버 전체에 적용됩니다</strong>(모든 회사 · 모든 사람의 목록).
          </>
        )}
      </p>

      {state === null ? (
        loadError ? (
          <InlineAlert tone="warn">
            {loadError}{" "}
            <button type="button" onClick={reread} className="mc-focus rounded font-medium underline">
              다시 읽기
            </button>
          </InlineAlert>
        ) : (
          <p role="status" className="text-cosmos-muted">
            찾는 낱말을 읽는 중…
          </p>
        )
      ) : (
        <>
          <div className="flex flex-col gap-1">
            <p className="text-[12px] font-semibold text-cosmos-secondary">
              더한 낱말 {state.extra.length}/{state.max_extra}
            </p>
            {state.extra.length === 0 ? (
              <p className="text-cosmos-muted">아직 더한 낱말이 없습니다.</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {state.extra.map((entry) => (
                  <li
                    key={entry.word}
                    data-keyword-chip
                    className="inline-flex items-center gap-0.5 rounded-full border border-cosmos-border bg-cosmos-elevated/60 py-0.5 pl-3 pr-1"
                  >
                    <span className="font-medium text-cosmos-text" title={`${entry.added_by_name} · ${formatDateTime(entry.added_at)}에 더함`}>
                      {entry.word}
                    </span>
                    {!viewer && (
                      <>
                        <button
                          type="button"
                          disabled={busy !== null || searchLock !== null}
                          title={searchLock ?? `「${entry.word}」로 지금 다시 찾습니다`}
                          onClick={() => void research(entry.word)}
                          className={chipButton}
                        >
                          {busy === entry.word ? "찾는 중…" : "다시 찾기"}
                        </button>
                        <button
                          type="button"
                          disabled={busy !== null}
                          aria-label={`「${entry.word}」 지우기`}
                          onClick={() => void remove(entry.word)}
                          className={chipButton}
                        >
                          지우기
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {viewer ? (
            <p className="text-[12px] text-cosmos-muted" data-viewer-lock>
              {VIEWER_LOCK_REASON}
            </p>
          ) : (
            <>
              <form onSubmit={(event) => void add(event)} className="flex flex-wrap items-center gap-2">
                <label htmlFor={inputId} className="sr-only">
                  더할 낱말
                </label>
                <input
                  id={inputId}
                  value={word}
                  onChange={(event) => setWord(event.target.value)}
                  placeholder="예: 메타버스"
                  disabled={full || busy !== null}
                  aria-describedby={hint ? `${inputId}-hint` : undefined}
                  className="mc-focus min-h-9 min-w-0 flex-1 rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-2.5 text-[13px] text-cosmos-text placeholder:text-cosmos-muted sm:max-w-[240px]"
                />
                <Button type="submit" variant="primary" size="sm" disabled={!canAdd} data-keyword-add>
                  {busy === "add" ? (searchLock === null ? "더하고 찾는 중…" : "더하는 중…") : searchLock === null ? "더하고 바로 찾기" : "더하기"}
                </Button>
              </form>
              {hint && (
                <p id={`${inputId}-hint`} className="text-[12px] text-cosmos-amber" data-keyword-hint>
                  {hint}
                </p>
              )}
              {searchLock && (
                <p className="text-[12px] text-cosmos-muted" data-keyword-search-lock>
                  {searchLock}
                </p>
              )}
            </>
          )}
        </>
      )}

      {note?.kind === "result" && (
        <div role="status" data-keyword-result className="flex flex-wrap items-center gap-x-3 gap-y-1 text-cosmos-green">
          <span>{keywordSearchSummary(note.result, collectState)}</span>
          {resultAction?.(note.result)}
        </div>
      )}
      {note?.kind === "info" && (
        <p role="status" className="text-cosmos-secondary">
          {note.text}
        </p>
      )}
      {note?.kind === "searchError" && (
        <InlineAlert tone="warn" role="status">
          <span data-keyword-search-error>{note.text}</span>
        </InlineAlert>
      )}
      {note?.kind === "error" && (
        <InlineAlert tone="warn">
          {note.text}
          {note.stale && (
            <>
              {" "}
              <button type="button" onClick={reread} className="mc-focus rounded font-medium underline" data-stale-reload>
                다시 불러오기
              </button>{" "}
              (쓰던 낱말은 입력칸에 그대로 있습니다)
            </>
          )}
        </InlineAlert>
      )}

      {state && (
        <details className="text-[12px] text-cosmos-secondary">
          <summary className="mc-focus w-fit cursor-pointer rounded">기본 낱말 {state.base.length}개 보기(고칠 수 없음)</summary>
          <p className="mt-1 leading-5" data-keyword-base>
            {state.base.join(" · ")}
          </p>
        </details>
      )}
      <ul className="flex flex-col gap-0.5 text-[12px] text-cosmos-muted">
        <li>바로 찾기는 나라장터 입찰만 — 사전규격 · 발주계획 · 공고문은 {next} 함께 받습니다.</li>
        <li>
          기업마당은 전체를 받으므로 낱말과 상관없습니다(관심 분야는{" "}
          <Link href="/company" className="mc-focus rounded underline underline-offset-2 hover:text-cosmos-text">
            {SCREEN_NAMES.company} › 사업영역
          </Link>
          ).
        </li>
      </ul>
    </section>
  );
}
