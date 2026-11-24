"use client";

/**
 * 공고문에 질문하기 (판 2.4.0 · 대표 11-04 「2단계」 ⑦) — 입찰 · 지원사업 · 직접 넣은 공고가 함께 쓰는 접는 칸.
 *
 * - 처음 펼칠 때만 원문 상태를 묻는다(목록 카드 열 개를 펼쳐도 요청이 몰리지 않게) · 한 번 펼친 뒤에는 접어도 이번 질문 · 답이 남는다.
 * - 질문 · 답은 저장하지 않는다(이번 열람 동안 이 칸 안에서만 · 새것이 위).
 * - 열람자는 칸 · 단추를 잠그고 이유를 적는다(서버도 403) · 연결이 끊기면 같은 요청을 다시 보내지 않는다.
 * - 중립 자리(components/ui) — 지원사업 화면도 쓰므로 입찰 지도 부품을 불러오지 않는다. 색은 토큰 클래스만(두 화면 밝기 모두 따라감).
 */

import { useEffect, useId, useRef, useState } from "react";

import { ApiError, askNoticeQuestion, getNoticeQa } from "@/lib/api";
import { describeFailure, isConnectionCut } from "@/lib/errors";
import {
  NOTICE_QA_CUT,
  NOTICE_QA_INTRO,
  NOTICE_QA_KEEP_OPEN,
  NOTICE_QA_SESSION,
  NOTICE_QA_MATCH_HEAD,
  NOTICE_QA_MAX_CHARS,
  NOTICE_QA_NO_MATCH,
  NOTICE_QA_SEND_SCOPE,
  NOTICE_QA_TITLE,
  NOTICE_QA_TOO_SHORT,
  aiLine,
  askLabel,
  citationLabel,
  documentsLine,
  droppedText,
  exampleQuestions,
  noSourceText,
  pagesSentText,
  statusHeading,
  tidyQuestion,
  waitingText,
  type NoticeQaAnswer,
  type NoticeQaKind,
  type NoticeQaState,
} from "@/lib/noticeQa";
import { analysisContext, useOrganizationId } from "@/lib/organization";
import { VIEWER_LOCK_LABEL, useViewerLock } from "@/lib/viewerLock";
import { Button, InlineAlert } from "@/components/ui/primitives";

interface Entry {
  id: number;
  question: string;
  answer?: NoticeQaAnswer;
  error?: string;
}

/** 실패를 한 줄로 — 401 은 저장하지 않는 이 칸에 맞는 문장으로(공통 문장은 「저장하지 못했습니다」로 시작함). */
function failureText(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 401 && !error.detail?.startsWith("계정이 꺼졌습니다")) return NOTICE_QA_SESSION;
  return describeFailure(error, fallback);
}

export default function NoticeQaPanel({ itemId, kind }: { itemId: string; kind: NoticeQaKind }) {
  const [opened, setOpened] = useState(false);
  return (
    <details className="group" data-notice-qa onToggle={(event) => event.currentTarget.open && setOpened(true)}>
      <summary className="mc-focus w-fit cursor-pointer list-none rounded py-1 text-[14px] font-semibold text-cosmos-text hover:text-cosmos-cyan">
        {NOTICE_QA_TITLE} <span aria-hidden="true" className="group-open:hidden">▸</span>
        <span aria-hidden="true" className="hidden group-open:inline">▾</span>
      </summary>
      {opened && <NoticeQaBody itemId={itemId} kind={kind} />}
    </details>
  );
}

function NoticeQaBody({ itemId, kind }: { itemId: string; kind: NoticeQaKind }) {
  const organizationId = useOrganizationId();
  const viewer = useViewerLock();
  const baseId = useId();
  const fieldId = `${baseId}-question`;
  const viewerId = `${baseId}-viewer`;
  const waitId = `${baseId}-wait`;
  const hintId = `${baseId}-hint`;
  const nextId = useRef(1);
  const [state, setState] = useState<NoticeQaState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [history, setHistory] = useState<Entry[]>([]);
  // 화면 읽기 프로그램에 한 번씩만 알리는 칸(시작 · 끝) — 경과 초 줄은 알리지 않는다(1초마다 읽혔다 · 11-04 검토)
  const [announce, setAnnounce] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getNoticeQa(itemId, analysisContext(itemId, organizationId)).then(
      (value) => {
        if (!cancelled) setState(value);
      },
      (error: unknown) => {
        if (!cancelled) setLoadError(failureText(error, "원문 상태를 불러오지 못했습니다."));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [itemId, organizationId, reload]);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  async function submit() {
    const text = tidyQuestion(question);
    if (!text) {
      setHint(NOTICE_QA_TOO_SHORT);
      return;
    }
    setHint(null);
    setSeconds(0);
    setBusy(true);
    setAnnounce("답을 찾는 중입니다");
    const id = nextId.current++;
    try {
      const answer = await askNoticeQuestion(itemId, text, analysisContext(itemId, organizationId));
      setHistory((prev) => [{ id, question: text, answer }, ...prev]);
      setState((prev) => (prev ? { ...prev, used_today: answer.used_today } : prev));
      // 기다리는 동안 칸에 다음 질문을 적었으면 지우지 않는다(11-04 검토)
      setQuestion((current) => (tidyQuestion(current) === text ? "" : current));
      setAnnounce(statusHeading(answer.status, kind));
    } catch (error) {
      // 끊김은 서버가 아직 찾는 중일 수 있다 — 같은 요청을 다시 보내지 않고 알리기만 한다
      const message = isConnectionCut(error) ? NOTICE_QA_CUT : failureText(error, "답을 받지 못했습니다.");
      setHistory((prev) => [{ id, question: text, error: message }, ...prev]);
      setAnnounce(message);
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <div className="mt-2 flex flex-col items-start gap-2">
        <InlineAlert>{loadError}</InlineAlert>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setLoadError(null);
            setReload((n) => n + 1);
          }}
        >
          다시 불러오기
        </Button>
      </div>
    );
  }
  if (!state) {
    return (
      <p role="status" className="mt-2 text-[13px] text-cosmos-muted">
        원문 확인 중…
      </p>
    );
  }

  const describedBy = viewer ? viewerId : undefined;
  const willAsk = askLabel(state) === "질문하기";
  return (
    <div className="mt-2 flex flex-col gap-3" data-notice-qa-body>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>
      <p className="text-[13px] leading-6 text-cosmos-secondary">{NOTICE_QA_INTRO}</p>
      {!state.available ? (
        <InlineAlert tone="info" role="status">
          {noSourceText(kind)}
        </InlineAlert>
      ) : (
        <>
          <div className="flex flex-col gap-0.5 text-[13px] leading-6 text-cosmos-secondary">
            <p>{documentsLine(state.documents)}</p>
            <p>{aiLine(state)}</p>
            {/* AI 를 부를 때만 — 꺼짐 · 상한이면 보내는 것이 없다(11-04 검토) */}
            {willAsk && <p className="text-cosmos-muted">{NOTICE_QA_SEND_SCOPE}</p>}
          </div>
          {state.warning && (
            <InlineAlert tone="warn" role="status">
              {state.warning}
            </InlineAlert>
          )}
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="예시 질문">
            {exampleQuestions(kind).map((example) => (
              <Button
                key={example}
                size="sm"
                variant="secondary"
                disabled={viewer}
                aria-describedby={describedBy}
                onClick={() => {
                  setQuestion(example);
                  setHint(null);
                }}
              >
                {example}
              </Button>
            ))}
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={fieldId} className="text-[13px] font-semibold text-cosmos-secondary">
              질문
            </label>
            <textarea
              id={fieldId}
              value={question}
              maxLength={NOTICE_QA_MAX_CHARS}
              disabled={viewer}
              aria-describedby={describedBy ?? (hint ? hintId : undefined)}
              placeholder={`예: ${exampleQuestions(kind)[0]}`}
              onChange={(event) => {
                setQuestion(event.target.value);
                if (hint) setHint(null);
              }}
              className="mc-focus min-h-20 w-full resize-y rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 py-2 text-[14px] leading-6 text-cosmos-text placeholder:text-cosmos-muted disabled:cursor-not-allowed disabled:opacity-60"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              disabled={viewer || busy}
              aria-describedby={describedBy ?? (busy ? waitId : hint ? hintId : undefined)}
              onClick={() => void submit()}
            >
              {askLabel(state)}
            </Button>
            {busy && (
              <p id={waitId} className="text-[13px] tabular-nums text-cosmos-secondary">
                {waitingText(seconds)}
                <span className="block text-cosmos-muted">{NOTICE_QA_KEEP_OPEN}</span>
              </p>
            )}
            {hint && (
              <p id={hintId} role="alert" className="text-[13px] text-cosmos-amber">
                {hint}
              </p>
            )}
            <span className="ml-auto text-[12px] tabular-nums text-cosmos-muted">
              {question.length}/{NOTICE_QA_MAX_CHARS}
            </span>
          </div>
          {viewer && (
            <p id={viewerId} data-viewer-lock className="text-[13px] text-cosmos-amber">
              {VIEWER_LOCK_LABEL} — 질문은 편집자 이상이 합니다
            </p>
          )}
        </>
      )}
      {history.length > 0 && (
        <ol className="flex flex-col gap-3" aria-label="이번에 물어본 것">
          {history.map((entry) => (
            <li key={entry.id} className="flex flex-col gap-2 border-t border-cosmos-border pt-3">
              <p className="text-[13px] font-semibold text-cosmos-text [overflow-wrap:anywhere]">질문 · {entry.question}</p>
              {entry.answer ? <AnswerView answer={entry.answer} kind={kind} /> : <InlineAlert>{entry.error}</InlineAlert>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function AnswerView({ answer, kind }: { answer: NoticeQaAnswer; kind: NoticeQaKind }) {
  const heading = statusHeading(answer.status, kind);
  const dropped = droppedText(answer.dropped);
  const sent = pagesSentText(answer);
  const showMatches = answer.status === "not_found" || answer.status === "search_only";
  return (
    <div className="flex flex-col gap-2" data-notice-qa-answer={answer.status}>
      <p className="text-[13px] font-semibold text-cosmos-text">{heading}</p>
      {answer.note && answer.note !== heading && <p className="text-[13px] leading-6 text-cosmos-secondary">{answer.note}</p>}
      {answer.lines.length > 0 && (
        <ul className="flex flex-col gap-3">
          {answer.lines.map((line, index) => (
            <li key={index} className="flex flex-col gap-1">
              <p className="text-[14px] leading-6 text-cosmos-text [overflow-wrap:anywhere]">{line.text}</p>
              {line.citations.map((cite, citeIndex) => (
                <p key={citeIndex} className="border-l-2 border-cosmos-cyan/50 pl-3 text-[13px] leading-6 text-cosmos-secondary [overflow-wrap:anywhere]">
                  <span className="font-semibold text-cosmos-muted">{citationLabel(cite.document, cite.page, cite.page_is_approximate)}</span> “{cite.quote}”
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
      {dropped && <p className="text-[12px] text-cosmos-muted">{dropped}</p>}
      {showMatches &&
        (answer.matches.length > 0 ? (
          <div className="flex flex-col gap-1">
            {answer.status === "not_found" && <p className="text-[13px] font-semibold text-cosmos-secondary">{NOTICE_QA_MATCH_HEAD}</p>}
            <ul className="flex flex-col gap-1">
              {answer.matches.map((match, index) => (
                <li key={index} className="text-[13px] leading-6 text-cosmos-secondary [overflow-wrap:anywhere]">
                  <span className="font-semibold text-cosmos-muted">{citationLabel(match.document, match.page, match.page_is_approximate)}</span> {match.text}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-[13px] text-cosmos-muted">{NOTICE_QA_NO_MATCH}</p>
        ))}
      {sent && <p className="text-[12px] text-cosmos-muted">{sent}</p>}
    </div>
  );
}
