/**
 * 「공고 직접 넣기」 양식 (38차 §3-E) — https 만 · 필수 다섯 · 모집 대상 기본값 없음 · 마감 KST · 공고문 형식 · 크기.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPTY_FORM,
  REGION_CUSTOM,
  chooseRegion,
  documentProblem,
  formErrors,
  kstIso,
  regionChoiceOf,
  toInput,
  toLocalInput,
  uploadMessage,
  watchSiteProblem,
} from "../src/lib/manualForm.ts";

const FILLED = {
  ...EMPTY_FORM,
  url: "https://www.kosac.re.kr/menus/281/reg",
  title: "AI 교육 운영 수행기관 모집",
  agency: "한국과학창의재단",
  deadline: "2026-10-28T16:00",
  recruit: "operator" as const,
};

describe("직접 넣기 양식", () => {
  it("빈 양식은 필수 다섯을 모두 알려 주고 모집 대상은 미리 골라 두지 않는다", () => {
    const errors = formErrors(EMPTY_FORM);
    assert.deepEqual(Object.keys(errors).sort(), ["agency", "deadline", "recruit", "title", "url"]);
    assert.equal(EMPTY_FORM.recruit, "");
  });

  it("https 가 아닌 주소 · 위험한 주소는 받지 않는다", () => {
    for (const url of ["http://a.go.kr/x", "javascript:alert(1)", "https://a b.kr", "ftp://a.kr/x"]) {
      assert.ok(formErrors({ ...FILLED, url }).url, url);
    }
    assert.deepEqual(formErrors(FILLED), {});
  });

  it("마감은 KST 로 보낸다 · 다시 고칠 때도 같은 시각", () => {
    assert.equal(kstIso("2026-10-28T16:00"), "2026-10-28T16:00:00+09:00");
    assert.equal(kstIso("2026-10-28"), null);
    assert.equal(toLocalInput("2026-10-28T07:00:00Z"), "2026-10-28T16:00");
    assert.equal(toInput(FILLED).deadline, "2026-10-28T16:00:00+09:00");
    assert.equal(toInput({ ...FILLED, budgetText: "  " }).budget_text, null);
  });

  it("공고문은 pdf · hwp · hwpx · docx · 20MB 까지", () => {
    assert.equal(documentProblem({ name: "공고문.HWPX", size: 10 }), null);
    assert.ok(documentProblem({ name: "공고문.exe", size: 10 }));
    assert.ok(documentProblem({ name: "공고문.pdf", size: 0 }));
    assert.ok(documentProblem({ name: "공고문.pdf", size: 20 * 1024 * 1024 + 1 }));
  });
});

describe("39차 직접 넣기 화면 도우미", () => {
  it("지역 제한은 고르기 — 미리 정한 값 · 직접 적기 · 비움 (MANUAL-01)", () => {
    assert.equal(regionChoiceOf({ regionLimit: "", regionCustom: false }), "");
    assert.equal(regionChoiceOf({ regionLimit: "제한 없음", regionCustom: false }), "제한 없음");
    assert.equal(regionChoiceOf({ regionLimit: "서울 제외", regionCustom: false }), REGION_CUSTOM);
    const custom = chooseRegion({ regionLimit: "광주", regionCustom: false }, REGION_CUSTOM);
    assert.deepEqual(custom, { regionLimit: "", regionCustom: true });
    assert.deepEqual(chooseRegion(custom, "전남"), { regionLimit: "전남", regionCustom: false });
  });

  it("오늘 열어 본 곳 줄 검사는 서버와 같다 (MANUAL-07 · FRONTEND-02)", () => {
    assert.equal(watchSiteProblem({ name: "광주테크노파크", url: "https://www.gjtp.or.kr/board" }), null);
    assert.ok(watchSiteProblem({ name: "사내", url: "https://intranet/board" }));
    assert.ok(watchSiteProblem({ name: "빈칸", url: "https://www.gjtp.or.kr/board list" }));
    assert.ok(watchSiteProblem({ name: "가".repeat(121), url: null }));
    assert.ok(watchSiteProblem({ name: "메모", url: null, memo: "m".repeat(301) }));
    assert.ok(watchSiteProblem({ name: " ", url: null }));
  });

  it("공고문을 올린 뒤 조항을 못 찾았으면 그렇게 말한다 (FRONTEND-03)", () => {
    assert.equal(uploadMessage({ status: "ok" }), "공고문에서 자격 조항을 읽어 판정했습니다.");
    const said = uploadMessage({ status: "no_section", note: "머리글을 찾지 못했습니다" });
    assert.ok(said.includes("자격 조항을 찾지 못했습니다(머리글을 찾지 못했습니다)"));
    assert.ok(said.includes("판정은 「공고문 아직 안 읽음」 그대로"));
  });
});
