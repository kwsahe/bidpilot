"use client";

/**
 * 「과제소개서 받기」 (30차 · prompt_20 §3-A · 담당자 지시 「과제소개서도 다운받도록」).
 *
 * 공공기관 제안형 공고는 과제의 현황 · 문제 · 쓸 공공데이터 · 협업 요구사항을 별첨 「과제소개서」에 적는다 — 공고문에는
 * 과제 제목 한 줄뿐이다. 그 첨부가 있는 공고에서만 보이고, **누를 때만** 기업마당에서 파일 1개를 받아 비공개 폴더에 둔다.
 * 시연 고정 모드에서도 된다(저장된 공고 목록은 바꾸지 않는다). 받은 뒤에는 「과제소개서 있음 · n쪽 · 받은 날」.
 */

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { fetchSupportAnnex, getSupportAnnex, type SupportAnnexView } from "@/lib/api";
import { describeFailure } from "@/lib/errors";

function dayOf(iso: string | null | undefined): string {
  const at = iso ? new Date(iso) : null;
  return at && !Number.isNaN(at.getTime()) ? `${at.getMonth() + 1}월 ${at.getDate()}일` : "날짜 모름";
}

/** 서버가 붙여 보내는 앞말 — 화면이 같은 말을 또 붙이지 않게 뗀다(31차 R30-35). */
const FAIL_HEAD = "과제소개서를 받지 못했습니다";

export default function AnnexFetch({
  programId,
  onFetched,
  onFetchable,
}: {
  programId: string;
  onFetched?: () => void;
  /** 받기 단추가 보이는가 — 빈칸 목록의 「과제소개서 받기로 →」 링크를 그때만 그린다(31차 R30-36). */
  onFetchable?: (fetchable: boolean) => void;
}) {
  const [view, setView] = useState<SupportAnnexView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getSupportAnnex(programId)
      .then((value) => alive && setView(value))
      .catch(() => alive && setView(null)); // 상태를 못 읽으면 단추를 보이지 않는다(누를 수 없는 것을 보이지 않게)
    return () => {
      alive = false;
    };
  }, [programId]);

  useEffect(() => {
    onFetchable?.(Boolean(view?.attachment) && view?.record?.status !== "text");
  }, [view, onFetchable]);

  const record = view?.record?.status === "text" ? view.record : null;
  // 받아 둔 과제소개서는 첨부가 안 보여도(목록에서 내려간 공고 · 첨부 목록 못 읽음) 그대로 보인다(34차 R33-A4)
  if (!view || (!view.attachment && !record)) return null;
  const message = error ? error.replace(new RegExp(`^${FAIL_HEAD}\\s*[—-]\\s*`), "") : null;

  const fetchNow = () => {
    setBusy(true);
    setError(null);
    fetchSupportAnnex(programId)
      .then((value) => {
        setView(value);
        onFetched?.();
      })
      .catch((e: unknown) => setError(describeFailure(e)))
      .finally(() => setBusy(false));
  };

  return (
    <div id="plan-annex" className="flex scroll-mt-24 flex-wrap items-center gap-2 text-[12.5px] leading-5" data-annex-fetch>
      {record ? (
        <span className="text-cosmos-text" data-annex-state="have">
          과제소개서 있음 · {record.pages}쪽 · {dayOf(record.downloaded_at)} 받음
          <span className="text-cosmos-muted"> — 고른 과제의 절만 초안에 씁니다</span>
        </span>
      ) : (
        <>
          <Button size="sm" variant="secondary" onClick={fetchNow} disabled={busy || view.running} aria-busy={busy} data-annex-state="none">
            {busy ? "과제소개서 받는 중…" : "과제소개서 받기"}
          </Button>
          <span className="text-cosmos-muted">
            {view.running && !busy
              ? "다른 과제소개서를 받는 중입니다 — 끝난 뒤 다시 누르세요."
              : `기업마당에서 파일 1개(${view.attachment?.name ?? "과제소개서"})를 받습니다 — 과제의 현황 · 문제 · 공공데이터 · 요구사항이 이 파일에 있습니다.`}
          </span>
        </>
      )}
      {message && (
        <span className="basis-full text-cosmos-amber" role="status">
          {FAIL_HEAD} — {message}
        </span>
      )}
    </div>
  );
}
