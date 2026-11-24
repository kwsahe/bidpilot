/**
 * 실전 가이드 마크다운 플러그인 한 벌(33차 §3-E G1) — 화면(GuideMarkdown)과 시험이 같은 것을 쓴다.
 *
 * remark-gfm 은 기본으로 물결표 **하나**도 취소선으로 읽어 「1~2주 · 3~5일 · 당일~1일」이 「12주」처럼 그어져 보였다.
 * 가이드는 취소선을 쓰지 않으므로 물결표 둘(`~~ ~~`)만 취소선으로 둔다.
 */

import type { Options } from "react-markdown";
import remarkGfm from "remark-gfm";

export const GUIDE_REMARK_PLUGINS: NonNullable<Options["remarkPlugins"]> = [[remarkGfm, { singleTilde: false }]];
