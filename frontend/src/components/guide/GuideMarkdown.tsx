/**
 * 실전 가이드 본문 한 절을 그린다 — 서버 컴포넌트(32차 §3-A-2).
 *
 * - `react-markdown` + `remark-gfm`: GFM 표 · 체크박스 · 중첩 목록을 손으로 다시 만들지 않는다(깨지기 쉬움).
 * - 바깥 링크는 새 탭 ↗ · `noopener` · 민간 사본(thevc) 표시 · 안쪽 링크(`/company#readiness`)는 앱 안 이동.
 * - 표는 표 안쪽만 가로로 스크롤 · 체크박스는 읽기 전용(GFM 기본 disabled).
 * - 8장 번호 항목은 `g-8-13` id · 출처를 확인 못 한 값(「확인 필요」)은 8장으로 가는 점선 표시 — 판정 「확인 필요」(주황 칩)와 다른 모양.
 */

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import ReactMarkdown from "react-markdown";

import { GUIDE_REMARK_PLUGINS } from "@/lib/guideRemark";

/** hast 의 필요한 꼴만 — 타입 패키지를 따로 들이지 않는다. */
interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

/** 출처 확인 표시를 붙이는 장 — 4장(쓰기 지시) · 6 · 7장(판정 이름 「확인 필요」) · 8장(목록 자체)은 뺀다. */
const SOURCE_CHECK_CHAPTERS = new Set<number | null>([null, 0, 1, 2, 3, 5]);
const SOURCE_CHECK = "확인 필요";

function rehypeGuide(options: { chapter: number | null }) {
  const { chapter } = options;
  return (tree: HastNode) => {
    const walk = (node: HastNode, inLinkOrHeading: boolean) => {
      if (!node.children) return;
      if (chapter === 8 && node.tagName === "ol") {
        const start = Number(node.properties?.start ?? 1) || 1;
        node.children
          .filter((child) => child.tagName === "li")
          .forEach((li, index) => {
            li.properties = { ...li.properties, id: `g-8-${start + index}`, tabIndex: -1 };
          });
      }
      const blocked = inLinkOrHeading || node.tagName === "a" || /^h[1-6]$/.test(node.tagName ?? "");
      const next: HastNode[] = [];
      for (const child of node.children) {
        if (child.type === "text" && !blocked && SOURCE_CHECK_CHAPTERS.has(chapter) && child.value?.includes(SOURCE_CHECK)) {
          const parts = child.value.split(SOURCE_CHECK);
          parts.forEach((part, index) => {
            if (part) next.push({ type: "text", value: part });
            if (index < parts.length - 1) {
              next.push({
                type: "element",
                tagName: "a",
                properties: { href: "#g-8", className: ["guide-check"], title: "출처를 확인하지 못한 값 — 8장 「확인 필요 목록」" },
                children: [{ type: "text", value: SOURCE_CHECK }],
              });
            }
          });
          continue;
        }
        walk(child, blocked);
        next.push(child);
      }
      node.children = next;
    };
    walk(tree, false);
  };
}

const PRIVATE_COPY = /(^|\.)thevc\.kr$/;
/** 체크 칸 설명 글의 id — 화면(page.tsx)이 같은 id 로 한 줄을 둔다. */
export const GUIDE_CHECKBOX_NOTE_ID = "guide-checkbox-note";

// react-markdown 이 넘기는 `node`(hast 객체)는 DOM 속성이 아니다 — `...rest` 로 새면 링크마다 node="[object Object]"(33차 §3-E G8)
function GuideLink({ href = "", children, node, ...rest }: ComponentProps<"a"> & { node?: unknown }) {
  void node;
  if (/^https?:\/\//.test(href)) {
    let host = "";
    try {
      host = new URL(href).hostname;
    } catch {
      host = "";
    }
    return (
      <a {...rest} href={href} target="_blank" rel="noopener noreferrer" className="guide-external">
        {children}
        <span aria-hidden="true"> ↗</span>
        {PRIVATE_COPY.test(host) && <span className="text-cosmos-muted"> (민간 사본)</span>}
      </a>
    );
  }
  if (href.startsWith("/")) {
    return (
      <Link href={href} className="guide-internal">
        {children}
      </Link>
    );
  }
  return (
    <a {...rest} href={href}>
      {children}
    </a>
  );
}

function GuideTable({ children }: { children?: ReactNode }) {
  return (
    // 표 안쪽만 가로로 스크롤 — 390 폭에서 화면 전체가 옆으로 밀리지 않게
    <div className="guide-table my-3 overflow-x-auto rounded-lg border border-cosmos-border" tabIndex={0} role="region" aria-label="표">
      <table className="min-w-[36rem] border-collapse text-[14px] leading-6">{children}</table>
    </div>
  );
}

export function GuideMarkdown({ markdown, chapter }: { markdown: string; chapter: number | null }) {
  if (!markdown.trim()) return null;
  return (
    <ReactMarkdown
      remarkPlugins={GUIDE_REMARK_PLUGINS}
      rehypePlugins={[[rehypeGuide, { chapter }]]}
      components={{
        a: GuideLink,
        table: GuideTable,
        // 체크 칸은 읽기 전용(GFM 기본 disabled) — 왜 못 누르는지 화면 머리의 한 줄이 말한다(aria-describedby)
        input: ({ type, checked }) =>
          type === "checkbox" ? <input type="checkbox" disabled checked={Boolean(checked)} aria-describedby={GUIDE_CHECKBOX_NOTE_ID} /> : null,
        th: ({ children }) => <th className="border-b border-cosmos-border bg-cosmos-elevated/60 px-3 py-2 text-left align-top font-semibold">{children}</th>,
        td: ({ children }) => <td className="border-b border-cosmos-border/60 px-3 py-2 align-top">{children}</td>,
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}
