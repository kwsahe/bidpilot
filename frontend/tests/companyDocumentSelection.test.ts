/**
 * 회사자료 — 목록을 다시 읽어도 열린 문서 상세가 닫히지 않는다 (CMP-01 · ISSUE-163 · prompt_17 §3-F).
 *
 * 실행: `npm test` (frontend 폴더에서).
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { keepSelectedDocument } from "@/components/company/documentSelection";

const docs = [{ id: "CD-a" }, { id: "CD-b" }];

test("새 목록에 있으면 선택을 그대로 둔다 — 저장 · 승인 · 업로드 뒤에도 상세가 열려 있다", () => {
  assert.equal(keepSelectedDocument("CD-a", docs), "CD-a");
  // 「저장하고 다음 문서로」: 다음 문서로 바꾼 뒤 늦게 끝난 reload 가 그 선택을 지우지 않는다.
  assert.equal(keepSelectedDocument("CD-b", docs), "CD-b");
});

test("새 목록에 없을 때만 지운다 — 삭제한 문서 · 목록을 못 읽음 · 고른 것 없음", () => {
  assert.equal(keepSelectedDocument("CD-gone", docs), null);
  assert.equal(keepSelectedDocument("CD-a", null), null);
  assert.equal(keepSelectedDocument(null, docs), null);
});
