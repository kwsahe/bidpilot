/**
 * 실전 가이드 마크다운(33차 §3-E G1) — 물결표 범위「1~2주」가 취소선(<del>)이 되지 않는다.
 *
 * 실행: `npm test` (frontend 폴더에서). JSX 없이 createElement 로 그린다.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";

import { GUIDE_REMARK_PLUGINS } from "../src/lib/guideRemark.ts";

const render = (markdown: string) => renderToStaticMarkup(createElement(Markdown, { remarkPlugins: GUIDE_REMARK_PLUGINS }, markdown));

test("물결표 하나는 범위 — 「1~2주 · 3~5일 · 당일~1일」 그대로", () => {
  const html = render("준비 **1~2주** · 3~5일 · 당일~1일");
  assert.equal((html.match(/<del>/g) ?? []).length, 0, html);
  assert.ok(html.includes("1~2주") && html.includes("3~5일") && html.includes("당일~1일"), html);
});

test("가이드 본문 전체에 취소선 0 · 표는 그대로 표", () => {
  const markdown = readFileSync(join(import.meta.dirname, "..", "content", "first_time_guide.md"), "utf8");
  const html = render(markdown);
  assert.equal((html.match(/<del>/g) ?? []).length, 0);
  assert.ok(html.includes("<table>"), "GFM 표는 여전히 표");
});
