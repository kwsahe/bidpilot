/**
 * 2.4.0 ⑦ 공고문에 질문하기 — 쪽 표기 · 상태 글 · 예시 질문(lib/noticeQa 직접) · 다섯 자리 연결(소스 글).
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/noticeQa.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
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
} from "../src/lib/noticeQa.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

describe("쪽 표기", () => {
  it("PDF 는 그 쪽 · 한글 · 워드 원본은 「약」", () => {
    assert.equal(citationLabel("입찰공고문", 3, false), "입찰공고문 3쪽");
    assert.equal(citationLabel("제안요청서", 17, true), "제안요청서 약 17쪽");
    assert.equal(
      documentsLine([
        { name: "입찰공고문", role: "notice", pages: 7, page_is_approximate: false },
        { name: "제안요청서", role: "rfp", pages: 35, page_is_approximate: true },
      ]),
      "읽을 원문: 입찰공고문 7쪽 · 제안요청서 약 35쪽",
    );
  });
});

describe("상태 글", () => {
  it("AI 줄 — 켜짐(오늘 n/30) · 다 씀 · 꺼짐 사유 + 낱말 찾기", () => {
    assert.equal(aiLine({ ai_ready: true, ai_note: null, used_today: 3, daily_limit: 30 }), "AI(Claude)로 답합니다 · 오늘 3/30번");
    assert.match(aiLine({ ai_ready: true, ai_note: null, used_today: 30, daily_limit: 30 }), /^오늘 AI 답 30번을 다 썼습니다/);
    assert.equal(
      aiLine({ ai_ready: false, ai_note: "이 서버에서는 AI(Claude)가 꺼져 있습니다", used_today: 0, daily_limit: 30 }),
      "이 서버에서는 AI(Claude)가 꺼져 있습니다 — 원문에서 낱말이 맞는 줄을 찾습니다",
    );
    assert.equal(askLabel({ ai_ready: true, used_today: 3, daily_limit: 30 }), "질문하기");
    assert.equal(askLabel({ ai_ready: false, used_today: 0, daily_limit: 30 }), "원문에서 찾기");
    assert.equal(askLabel({ ai_ready: true, used_today: 30, daily_limit: 30 }), "원문에서 찾기");
    assert.equal(waitingText(12), "답을 찾는 중… 12초 (최대 2분)");
  });

  it("원문 없음 — 출처마다 할 일 · 지원사업 글에는 입찰 말이 없다", () => {
    // 화면의 단추 이름과 같게(「공고 분석 시작」 · 11-04 검토)
    assert.match(noSourceText("bid"), /입찰 분석 화면에서 「공고 분석 시작」/);
    assert.equal(noSourceText("support"), "이 지원사업 공고문을 아직 받지 않았습니다 — 매일 받기 때 받습니다");
    assert.equal(noSourceText("manual"), "공고문 파일을 올리면 질문할 수 있습니다");
    for (const text of [noSourceText("support"), ...exampleQuestions("support")]) {
      assert.doesNotMatch(text, /입찰|제안서|요구사항|나라장터/);
    }
  });

  it("답 머리 · 뺀 문장 · 보낸 쪽", () => {
    assert.equal(statusHeading("answered", "bid"), "AI 답 — 원문 근거를 꼭 확인하세요");
    assert.equal(statusHeading("not_found", "bid"), "공고문에서 답을 찾지 못했습니다");
    assert.equal(statusHeading("search_only", "support"), "원문에서 낱말이 맞는 줄");
    assert.equal(statusHeading("no_source", "manual"), noSourceText("manual"));
    assert.equal(droppedText(0), null);
    assert.equal(droppedText(2), "원문에서 근거를 확인하지 못한 문장 2개는 뺐습니다");
    assert.equal(pagesSentText({ pages_sent: 40, pages_total: 40 }), null);
    assert.equal(pagesSentText({ pages_sent: 0, pages_total: 40 }), null);
    assert.equal(pagesSentText({ pages_sent: 12, pages_total: 61 }), "AI 에 보낸 쪽 12 / 61쪽(질문과 맞는 쪽부터)");
  });
});

describe("예시 질문 · 질문 칸", () => {
  it("출처마다 3~4개", () => {
    for (const kind of ["bid", "support", "manual"] as const) {
      const list = exampleQuestions(kind);
      assert.ok(list.length >= 3 && list.length <= 4, kind);
      assert.ok(list.every((q) => tidyQuestion(q) === q), kind);
    }
  });

  it("서버와 같은 규칙 — 공백 정리 · 2~300자", () => {
    assert.equal(tidyQuestion("  제출   서류는?  "), "제출 서류는?");
    assert.equal(tidyQuestion(" 가 "), null);
    assert.equal(tidyQuestion("질".repeat(301)), null);
    assert.equal(tidyQuestion("질".repeat(300))?.length, 300);
  });
});

describe("다섯 자리 연결 · 부품 규칙", () => {
  const places: [string, string[], RegExp][] = [
    ["사업기회 쉬운 보기 카드 펼침", ["app", "opportunities", "page.tsx"], /<ReceptionBox row=\{row\} \/>\s*\{\/\*[^]*?\*\/\}\s*<NoticeQaPanel key=\{row\.id\}/],
    ["사업기회 전체 보기 「자세히」", ["app", "opportunities", "page.tsx"], /function RowDetail[^]*<NoticeQaPanel key=\{row\.id\} itemId=\{row\.id\}/],
    ["입찰 분석 쉬운 보기", ["components", "cosmos", "SimpleDashboard.tsx"], /origin\.kind === "real" &&[^]*<NoticeQaPanel key=\{notice\.id\} itemId=\{notice\.id\} kind="bid" \/>/],
    ["입찰 분석 전체 보기 공고 상세", ["components", "cosmos", "DetailPanel.tsx"], /!embedded && <NoticeQaPanel key=\{notice\.id\} itemId=\{notice\.id\} kind="bid" \/>/],
    ["지원사업 쉬운 보기", ["components", "support", "SupportSimpleView.tsx"], /<NoticeQaPanel key=\{result\.program_id\} itemId=\{result\.program_id\} kind="support" \/>/],
    ["지원사업 전체 보기", ["components", "support", "SupportShell.tsx"], /<SupportStepNav[^]*?\/>[^]*?<NoticeQaPanel key=\{result\.program_id\} itemId=\{result\.program_id\} kind="support" \/>/],
  ];
  for (const [name, path, pattern] of places) {
    it(name, () => assert.match(read(...path), pattern));
  }

  it("패널은 중립 자리 — 입찰 지도 부품을 불러오지 않고 토큰 밖 색이 없다", () => {
    const panel = read("components", "ui", "NoticeQaPanel.tsx");
    assert.doesNotMatch(panel, /from "@\/components\/cosmos\//);
    assert.doesNotMatch(panel, /#[0-9a-fA-F]{3,8}\b|rgba?\(|COSMOS_COLORS|COSMOS_HEX/);
    // 쉬운 틀 안에서 14px 로 오르지 않는 작은 글자 클래스
    assert.doesNotMatch(panel, /text-(xs|sm)\b/);
  });

  it("열람자 잠금 · 끊김 · 401 띠(api.ts 함수만) · 처음 펼칠 때만 묻기", () => {
    const panel = read("components", "ui", "NoticeQaPanel.tsx");
    assert.match(panel, /VIEWER_LOCK_LABEL\} — 질문은 편집자 이상이 합니다/);
    assert.match(panel, /disabled=\{viewer \|\| busy\}\s*aria-describedby=/);
    assert.match(panel, /isConnectionCut\(error\) \? NOTICE_QA_CUT/);
    assert.doesNotMatch(panel, /\bfetch\(/);
    assert.match(panel, /\{opened && <NoticeQaBody/);
    const api = read("lib", "api.ts");
    assert.match(api, /getJson<NoticeQaState>\(`\/api\/notice-qa\//);
    assert.match(api, /postJson<NoticeQaAnswer>\(`\/api\/notice-qa\//);
  });

  it("활동 기록 낱말", () => {
    assert.match(read("lib", "activityLog.ts"), /\["POST", \/\^\\\/api\\\/notice-qa\\\/\[\^\/\]\+\$\/, "공고문에 질문하기"\]/);
  });
});
