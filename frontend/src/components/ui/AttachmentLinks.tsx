import type { ReactNode } from "react";

/**
 * 첨부 내려받기 목록 — 나라장터 공고 상세 · 3단계 머리 · 사업기회 행 · 기업마당 신청 서류가 **같은 모양**을 쓴다
 * (20차 §4-E-3). 링크 여부는 부르는 쪽이 정한다(나라장터는 `lib/attachments.attachmentLinkOf`).
 * 링크는 새 창 · `noreferrer noopener`. 링크가 없는 항목은 이름만 적는다.
 */
export interface AttachmentLinkItem {
  key: string;
  name: string;
  ext: string | null;
  href: string | null;
  /** 앞에 붙는 구분 배지(예: 「신청 서식」·「공고문」) */
  badge?: ReactNode;
  /** 뒤에 붙는 보조 링크(예: 기업마당 「보기」) */
  extra?: ReactNode;
}

export default function AttachmentLinks({
  items,
  compact = false,
  collapseAfter,
}: {
  items: AttachmentLinkItem[];
  compact?: boolean;
  /** 쉬운 보기(24차): 앞 n개만 보이고 나머지는 「첨부 m개 더 ▸」 한 줄로 접는다. 없으면 전부 보인다 */
  collapseAfter?: number;
}) {
  const shown = collapseAfter === undefined ? items : items.slice(0, collapseAfter);
  const rest = collapseAfter === undefined ? [] : items.slice(collapseAfter);
  const listClass = `flex flex-col ${compact ? "gap-1" : "gap-1.5"}`;
  const row = (file: AttachmentLinkItem) => (
        <li key={file.key} className="flex min-w-0 flex-wrap items-center gap-2">
          {file.badge}
          {file.ext && (
            <span className="shrink-0 rounded border border-cosmos-border px-1 py-px font-mono text-[12px] uppercase leading-4 text-cosmos-secondary">
              {file.ext}
            </span>
          )}
          {file.href ? (
            <a
              href={file.href}
              target="_blank"
              rel="noreferrer noopener"
              className="mc-focus min-w-0 break-all rounded text-[12.5px] leading-5 text-cosmos-cyan underline underline-offset-2 hover:brightness-110"
            >
              {file.name}
              <span className="whitespace-nowrap text-cosmos-secondary"> · 내려받기 ↗</span>
            </a>
          ) : (
            <span className="min-w-0 break-all text-[12.5px] leading-5 text-cosmos-secondary">{file.name}</span>
          )}
          {file.extra}
        </li>
  );
  return (
    <>
      <ul className={listClass} data-attachment-links>
        {shown.map(row)}
      </ul>
      {rest.length > 0 && (
        <details className="group" data-attachment-more>
          <summary className="mc-focus w-fit cursor-pointer list-none rounded py-1 text-[12.5px] text-cosmos-secondary hover:text-cosmos-text">
            {/* 앞에 보인 것이 없으면 「더」가 아니라 「보기」(37차 — 쉬운 보기 공고 카드는 모두 접는다) */}
            첨부 {rest.length}개 {shown.length > 0 ? "더" : "보기"} <span className="group-open:hidden">▸</span>
            <span className="hidden group-open:inline">▾</span>
          </summary>
          <ul className={`${listClass} mt-1`}>{rest.map(row)}</ul>
        </details>
      )}
    </>
  );
}
