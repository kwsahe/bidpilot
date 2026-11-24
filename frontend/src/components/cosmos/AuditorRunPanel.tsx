"use client";

/**
 * AI Auditor 실행 패널.
 *
 * 제안서 초안을 붙여넣거나(기본값은 생성된 제안서 문장) 파일로 올려
 * `POST /api/auditor/run` · `/api/auditor/run/upload`을 호출한다.
 *
 * 초안 텍스트 초기값은 부모가 `key`로 다시 마운트해 갱신한다
 * (effect 안에서 setState를 호출하지 않기 위한 규칙).
 */

import { useEffect, useRef, useState } from "react";

import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { tintStyle } from "@/lib/cosmos/format";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import { markDirty } from "@/lib/unsavedGuard";

const ACCEPT = ".docx,.txt,.md,.pdf,.hwp,.hwpx";

// ---------------------------------------------------------------------------
// 「손댄 초안이 있는가」 — 화면을 떠날 때 잃을 것이 있는지 판단하는 데 쓴다.
//
// 이 입력칸은 **어디에도 저장되지 않는다**. 담당자가 초안을 고쳐 놓고 다른 공고를
// 잠깐 열면 그대로 사라졌다. 「바뀌었다」는 사실만 공통 확인(unsavedGuard)에 알린다 (텍스트 자체는 내보내지 않는다).
// 예전엔 이 모듈만의 표시라 공고 바꾸기 · 상세 링크만 묻고 상단 메뉴로 떠날 때는 묻지 않았다(2.0.6) — 이제 한 곳이 묻는다.
// ---------------------------------------------------------------------------

function publishDirty(next: boolean): void {
  markDirty("auditor-draft", next);
}

export interface AuditorRunPanelProps {
  /** 초안 텍스트 기본값 (생성된 제안서 문장을 줄바꿈으로 이은 것) */
  defaultText: string;
  busy: boolean;
  error: string | null;
  /** LLM 2차 판단을 쓸 수 있는지 (백엔드 키 설정 여부와 무관하게 요청은 가능) */
  onRun: (proposalText: string, options: { useLlm: boolean }) => void;
  onUpload: (file: File, options: { useLlm: boolean }) => void;
  /** 입력칸이 기본값에서 바뀌었는지 알린다 (공고 전환 시 확인 대화상자 판단용). */
  onDirtyChange?: (dirty: boolean) => void;
  /**
   * AI 정밀 검사를 **실제로 쓸 수 있는가** (`LLM_LIVE` + 크레딧 · ISSUE-130 · §4-A-4).
   *
   * `null` 은 모른다 — 그때는 예전처럼 체크상자를 그대로 둔다. 거짓이면 체크상자를 잠그고
   * 왜 잠겼는지 적는다. 눌렀다가 조용히 규칙 결과만 받는 것보다 낫다.
   */
  aiDraft?: boolean | null;
}

export default function AuditorRunPanel({
  defaultText,
  busy,
  error,
  onRun,
  onUpload,
  onDirtyChange,
  aiDraft = null,
}: AuditorRunPanelProps) {
  const [text, setText] = useState(defaultText);
  const [useLlm, setUseLlm] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 부모는 defaultText 가 바뀌면 key 로 다시 마운트한다 — 그때 「손댄 적 없음」으로 돌아간다.
  useEffect(() => {
    publishDirty(false);
    return () => publishDirty(false);
  }, []);

  const changeText = (next: string) => {
    setText(next);
    const dirty = next !== defaultText;
    publishDirty(dirty);
    onDirtyChange?.(dirty);
  };

  const trimmed = text.trim();
  // 화면에 보이는 체크 상태 그대로 보낸다 — AI 상태가 늦게 「꺼짐」으로 오면 체크는 풀려 보이는데 요청엔 AI 가 실렸다 (DTL-15).
  const effectiveLlm = useLlm && aiDraft !== false;
  const lineCount = trimmed ? trimmed.split(/\n+/).filter((l) => l.trim()).length : 0;

  // 45차 M4 — 열람자는 점검을 실행하지 못한다(누른 뒤에야 「편집자 이상만」이 떴다) · 저장된 결과는 읽기로 본다(M5)
  const viewer = useViewerLock();
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="auditor-draft" className="text-[12px] text-cosmos-secondary">
        검사할 제안서 초안 (문장마다 줄바꿈)
      </label>
      <textarea
        id="auditor-draft"
        value={text}
        onChange={(e) => changeText(e.target.value)}
        rows={8}
        spellCheck={false}
        placeholder="제안서 초안을 붙여넣으세요. 제안요청서 요구사항이 빠졌는지 문장마다 맞춰 봅니다."
        className="w-full resize-y rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 py-2 font-mono text-[12px] leading-5 text-cosmos-text placeholder:text-cosmos-muted focus:border-cosmos-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
      />

      {viewer && <p className="text-[12px] text-cosmos-muted" data-viewer-lock>{VIEWER_LOCK_LABEL} — 점검 실행은 편집자 이상이 합니다. 저장된 점검 결과는 위에서 봅니다.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy || trimmed.length === 0 || viewer}
          title={viewer ? VIEWER_LOCK_REASON : undefined}
          onClick={() => onRun(trimmed, { useLlm: effectiveLlm })}
          // 채움 주 단추는 파랑 하나(27차 §3-E 색 한 벌 · 검증 G2-V1 — 호박은 「확인 필요」 판정색이다)
          className="rounded-lg bg-cosmos-blue-strong px-3 py-1.5 text-[12px] font-semibold text-white transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
        >
          {busy ? "점검 중…" : "제출 전 점검"}
        </button>

        <button
          type="button"
          disabled={busy || viewer}
          title={viewer ? VIEWER_LOCK_REASON : undefined}
          onClick={() => fileRef.current?.click()}
          className="rounded-lg border border-cosmos-border-strong px-3 py-1.5 text-[12px] font-medium text-cosmos-text transition-colors hover:border-cosmos-cyan/60 disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan"
        >
          파일로 검사
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            setFileName(file.name);
            onUpload(file, { useLlm: effectiveLlm });
          }}
        />

        {/*
          AI 가 꺼져 있으면 **체크상자를 잠근다** (ISSUE-130 · prompt_06 §4-A-4).
          켜 둔 채 눌러도 규칙 결과만 나오는데, 담당자는 「AI 가 봤다」고 읽는다.
        */}
        <label
          className={`flex items-center gap-1.5 text-[12px] ${
            aiDraft === false ? "text-cosmos-muted" : "text-cosmos-secondary"
          }`}
          title={
            aiDraft === false
              ? "AI 초안이 꺼져 있습니다. 규칙 검사는 그대로 실행됩니다."
              : undefined
          }
        >
          <input
            type="checkbox"
            checked={useLlm && aiDraft !== false}
            disabled={aiDraft === false}
            onChange={(e) => setUseLlm(e.target.checked)}
            className="h-3.5 w-3.5 accent-cosmos-cyan disabled:cursor-not-allowed"
          />
          AI 정밀 검사{aiDraft === false ? " (AI 초안 꺼짐)" : ""}
        </label>

        {lineCount > 0 && (
          <span className="ml-auto font-mono text-[12px] tabular-nums text-cosmos-muted">
            {lineCount}줄
          </span>
        )}
      </div>

      {fileName && (
        <p className="text-[12px] text-cosmos-muted">최근 업로드: {fileName}</p>
      )}

      <p className="text-[12px] leading-5 text-cosmos-muted">
        규칙 검사는 언제나 실행되며 AI 설정이 없어도 완전한 결과가 나옵니다. 「AI 정밀 검사」는 규칙이
        놓친 요구사항만 AI 로 다시 확인해 <b>표현이 달라 놓친 것</b>이면 심각도를 낮추고 이유를
        답니다. 항목을 지우지는 않으며 최종 판단은 사람이 합니다. 실패하면 규칙 결과를 그대로
        유지합니다. 파일은 docx · pdf · hwp · hwpx · txt · md 를 받습니다 — 여기서 받은 워드 초안을 고친 그대로
        올리면 됩니다.
      </p>

      {error && (
        <p
          role="alert"
          className="rounded-lg border px-3 py-2 text-[12px] leading-5"
          style={tintStyle(COSMOS_COLORS.red)}
        >
          {error}
        </p>
      )}
    </div>
  );
}
