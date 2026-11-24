"use client";

/**
 * 파일 내려받기 단추 — **실패해도 앱을 떠나지 않는다.**
 *
 * ## 왜 필요한가
 *
 * 내려받기가 평범한 `<a href>` 였다. 서버가 500 을 내면 브라우저가 그 응답으로 «이동»해서
 * 사용자는 `Internal Server Error` 한 줄짜리 흰 화면에 남겨졌다. 만들던 분석 화면은 사라지고,
 * 뒤로가기를 눌러야 돌아온다. 실제로 모든 내보내기가 500 이던 기간에 그렇게 보였다.
 *
 * 여기서는 fetch 로 받아 blob 으로 저장한다. 실패하면 화면에 그대로 머문 채 이유만 적는다.
 *
 * ## 오류를 어떻게 말하는가
 *
 * 서버가 준 한국어 `detail` 이 있으면 그것을 쓴다(예: PDF 변환기가 없는 서버의 503).
 * 없으면 lib/errors 의 사용자 문장으로 바꾼다 — 화면에 HTTP 코드나 서버 주소를 쓰지 않는다.
 *
 * ## 놓는 자리
 *
 * **부모가 `flex flex-wrap`(가로 줄) 또는 `flex flex-col`(세로 목록)이어야 한다.** 비활성 사유 · 실패 글은 `w-full` 로
 * 다음 줄에 선다 — 줄바꿈 없는 가로 줄(탭 `nav` 등) 안에 두면 글이 좁은 세로 기둥이 된다 (27차 ISSUE-159).
 */

import { useCallback, useState } from "react";

import { describeHttpFailure, koreanDetail } from "@/lib/errors";

export interface DownloadLinkProps {
  /** 받을 주소. 이미 회사·범위 질의가 붙은 완성된 URL. */
  href: string;
  /** 저장될 파일 이름. 서버가 Content-Disposition 으로 주면 그것이 이긴다. */
  fallbackName?: string;
  title?: string;
  className?: string;
  children: React.ReactNode;
  /** 실패 사유를 바깥(패널)에 알린다. 주지 않으면 단추 옆에 직접 적는다. */
  onError?: (message: string | null) => void;
  /** 누를 수 없는 상태인가. 누르기 전에 이유가 보여야 한다. */
  disabled?: boolean;
  /** 비활성 사유. 툴팁에만 두지 않고 화면에도 적는다 (마우스가 없는 사람도 읽어야 한다). */
  disabledReason?: string;
  /** 받기에 성공한 뒤 — 저장 목록처럼 받은 결과를 다시 읽어야 하는 곳이 쓴다 (OPP-32). */
  onDone?: () => void;
  /** 404(서버 사유 없음)일 때 쓸 문장(45차 M10 — 공용 「분석을 먼저 실행해 주세요」가 「전체 초안이 없다」는 뜻을 가렸다). */
  notFoundMessage?: string;
}

/** Content-Disposition 에서 파일 이름을 꺼낸다. RFC 5987(`filename*=UTF-8''…`)을 먼저 본다. */
function nameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
    } catch {
      // 디코딩 실패면 아래 일반 filename 으로 넘어간다.
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : null;
}

export function DownloadLink({
  href,
  fallbackName,
  title,
  className = "",
  children,
  onError,
  disabled = false,
  disabledReason,
  onDone,
  notFoundMessage,
}: DownloadLinkProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const report = useCallback(
    (message: string | null) => {
      setError(message);
      onError?.(message);
    },
    [onError],
  );

  const run = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    report(null);
    let url: string | null = null;
    try {
      const response = await fetch(href, { credentials: "same-origin" });
      if (!response.ok) {
        // 서버가 한국어로 이유를 말해 주면 그대로 전한다 (예: PDF 변환기 없음 503). 영어 사유(「Not Found」 · 예외 이름)는
        // 사용자 문장으로 바꾼다 — 대시보드 상세만 따로 막았고 나머지 내려받기 단추는 영어를 그대로 띄웠다 (DTL-06).
        let detail: string | null = null;
        try {
          const body = await response.json();
          const raw = typeof body?.detail === "string" ? body.detail : typeof body?.detail?.message === "string" ? body.detail.message : null;
          detail = koreanDetail(raw);
        } catch {
          // 본문이 JSON 이 아니면 아래 공통 문장으로.
        }
        report(detail ?? (response.status === 404 && notFoundMessage ? notFoundMessage : describeHttpFailure(response.status)));
        return;
      }
      const blob = await response.blob();
      url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = nameFromDisposition(response.headers.get("content-disposition")) ?? fallbackName ?? "download";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      onDone?.();
    } catch {
      report(describeHttpFailure(null));
    } finally {
      if (url) URL.revokeObjectURL(url);
      setBusy(false);
    }
  }, [busy, href, fallbackName, report, onDone, notFoundMessage]);

  return (
    <>
      <button
        type="button"
        onClick={run}
        disabled={busy || disabled}
        // 사유가 따로 없는 비활성이면 원래 설명이라도 남긴다 — 풍선 도움말이 비어 있었다 (DTL-05).
        title={disabled ? (disabledReason ?? title) : title}
        className={`${className} disabled:cursor-not-allowed disabled:opacity-50`}
      >
        {busy ? "받는 중…" : children}
      </button>
      {disabled && disabledReason && (
        <span className="w-full text-[12px] leading-5 text-cosmos-muted">{disabledReason}</span>
      )}
      {error && !onError && (
        <span role="alert" className="w-full text-[12px] leading-5 text-cosmos-red">
          {error}
        </span>
      )}
    </>
  );
}
