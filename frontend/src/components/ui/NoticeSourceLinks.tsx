"use client";

import { useEffect, useState } from "react";

import { getNoticeAttachments } from "@/lib/api";
import { rfpLinkOf, type RfpLink } from "@/lib/noticeLinks";

/**
 * 제안요청서 링크 — 첨부 목록 API 를 한 번 읽는다(사전규격 규격서까지 붙여 고른 제안요청서 · 2.9.1).
 * 나라장터 공고(`g2b-`)만 · 목록을 못 읽으면 링크 없음(첨부 목록은 1단계 · 전체 보기에 그대로 있다).
 * 돌려주는 값: 읽는 중 `undefined` · 제안요청서 없음 `null` — 쉬운 보기는 읽는 동안 접힌 첨부 목록을 그렸다가 바꾸지 않는다.
 */
export function useRfpLink(noticeId: string): RfpLink | null | undefined {
  const [found, setFound] = useState<{ id: string; link: RfpLink | null } | null>(null);
  useEffect(() => {
    if (!noticeId.startsWith("g2b-")) return;
    let alive = true;
    getNoticeAttachments(noticeId)
      .then((list) => alive && setFound({ id: noticeId, link: rfpLinkOf(list) }))
      .catch(() => alive && setFound({ id: noticeId, link: null }));
    return () => {
      alive = false;
    };
  }, [noticeId]);
  if (!noticeId.startsWith("g2b-")) return null;
  // 다른 공고로 옮긴 직후에는 앞 공고의 링크를 그리지 않는다(새 공고는 읽는 중)
  return found?.id === noticeId ? found.link : undefined;
}

/** 「제안요청서 내려받기 ↗」 — 새 창 · 원본 주소. 사전규격에 붙은 문서면 그렇다고 적는다(본공고 화면에는 공고서만 보일 수 있다). */
export function RfpDownloadLink({ link, className }: { link: RfpLink; className: string }) {
  return (
    <a
      href={link.href}
      target="_blank"
      rel="noreferrer noopener"
      title={link.name}
      data-rfp-download
      className={className}
    >
      제안요청서 내려받기{link.fromPrespec ? "(사전규격)" : ""}
      {link.ext ? ` · ${link.ext.toUpperCase()}` : ""} ↗
    </a>
  );
}
