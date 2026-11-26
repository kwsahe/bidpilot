/**
 * 11-06 갈래 B-2 — /plan 「이 제안서 양식」 문장 · 경고 고르기(lib/bidOutline 직접) · 화면 연결(소스 글).
 *
 * 실행: `node --import ./tests/_register.mjs --test tests/bidOutline.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { ApiError, type BidFormatRules } from "../src/lib/api.ts";
import {
  BEFORE_RULE_NOTE,
  OLD_DRAFT_NOTE,
  OUTLINE_SESSION,
  WITH_NAME_LABEL,
  documentLabel,
  documentsLine,
  downloadVariants,
  draftOutlineLine,
  entryLabel,
  evaluationLine,
  formatLines,
  isBlindOnly,
  outlineFailureText,
  outlineLine,
  rejectedLine,
  variantButtonLabel,
  variantName,
} from "../src/lib/bidOutline.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

const OUTLINE = [
  { no: "Ⅰ", title: "제안개요", items: [{ no: "1", title: "제안 목적" }, { no: "2", title: "추진 전략" }] },
  { no: "Ⅱ", title: "제안사 일반", items: [{ no: "1", title: "일반현황" }] },
];
const WHERE = { document: "1_제안요청서(개인정보 교육).hwpx", page: 31, head: "□ 제안서 목차 및 작성 방법" };
const NO_RULES: BidFormatRules = { page_limit: null, blind: false, landscape: false, ppt: false, two_volume: false };

describe("목차 줄", () => {
  it("원문 목차 — 문서 · 쪽 · 머리 줄 · 대항목 · 소항목 수", () => {
    assert.equal(documentLabel(WHERE.document), "제안요청서(개인정보 교육)");
    assert.equal(documentLabel("첨부.zip > 4_제안서 평가 기준 및 작성 방법.pdf"), "제안서 평가 기준 및 작성 방법");
    assert.deepEqual(outlineLine({ outline_source: "rfp", outline: OUTLINE, outline_where: WHERE }), {
      text: "제안요청서(개인정보 교육) 31쪽 「□ 제안서 목차 및 작성 방법」의 목차로 씁니다 — 대항목 2 · 소항목 3",
      warn: false,
    });
  });

  it("번호 없는 대항목 · 끝맺은 번호", () => {
    assert.equal(entryLabel("Ⅰ", "제안개요"), "Ⅰ. 제안개요");
    assert.equal(entryLabel("", "제안사"), "제안사");
    assert.equal(entryLabel("1)", "추진 전략"), "1) 추진 전략");
    assert.equal(entryLabel("가.", "교육 운영"), "가. 교육 운영");
  });

  it("표준 목차는 이유와 함께 경고 색", () => {
    const unread = outlineLine({ outline_source: "unread", outline: OUTLINE, outline_where: null });
    assert.equal(unread.warn, true);
    assert.match(unread.text, /읽지 못해 표준 목차로 씁니다/);
    // 검토 11-06 — 머리를 찾은 쪽을 목차 줄이 말한다(경고 상자와 두 번 말하지 않음)
    const found = { document: "1_제안요청서.hwpx", page: 31, head: "□ 제안서 목차" };
    assert.match(outlineLine({ outline_source: "unread", outline: OUTLINE, outline_where: null, outline_found_at: found }).text, /^제안요청서 31쪽의 제안서 목차를 읽지 못해 표준 목차로 씁니다/);
    assert.match(outlineLine({ outline_source: "standard", outline: OUTLINE, outline_where: null }).text, /^원문에 제안서 목차가 없어 표준 목차로/);
  });

  it("쓰지 않은 후보 — 쪽 · 머리 · 사유", () => {
    assert.equal(rejectedLine({ head: "목 차", page: 1, reason: "문서 앞 목차(제안요청서 장 목록)" }), "1쪽 「목 차」 — 문서 앞 목차(제안요청서 장 목록)");
    // 1805118 실측 — 문서 목차 한 줄 통째가 머리 줄로 온다
    const long = "I. 사업개요1. 사업명 2. 목적3. 사업기간4. 사업금액5. 주요 내용6. 추진 일정7. 사업 결과물Ⅱ. 제안요청사항";
    assert.equal(rejectedLine({ head: long, page: 1, reason: "문서 앞 목차" }), `1쪽 「${long.slice(0, 40)}…」 — 문서 앞 목차`);
    assert.equal(
      documentsLine([{ name: "사전규격 규격서 1(R26BD00288735)", role: "spec", pages: 22 }, { name: "공고서_개인정보.hwpx", role: "notice", pages: null }]),
      "읽은 원문: 사전규격 규격서 1(R26BD00288735) 전체 22쪽 · 공고서_개인정보",
    );
  });
});

describe("평가표 · 형식 규정", () => {
  it("기술평가 n항목 · m점 · 정량이 섞이면 나눠 센다 · 못 읽으면 경고", () => {
    const items = [{ area: "사업 이해도", name: "목표 이해", points: 10, kind: "정성" }];
    assert.deepEqual(evaluationLine({ items, total: 100, where: null }), { text: "기술평가 1항목 · 100점 — 조견표로 넣습니다", warn: false });
    const mixed = [...items, { area: "실적", name: "유사 실적", points: 10, kind: "정량" }];
    assert.equal(evaluationLine({ items: mixed, total: 100, where: null }).text, "평가 2항목(정성 1 · 정량 1) · 100점 — 조견표로 넣습니다");
    assert.deepEqual(evaluationLine({ items: [], total: null, where: { document: "제안요청서.pdf", page: 40, head: null } }), {
      text: "평가표를 읽지 못했습니다 — 제안요청서 40쪽 평가표를 확인하세요",
      warn: true,
    });
  });

  it("앱이 맞추는 것과 직접 맞춰야 할 것을 가른다", () => {
    assert.deepEqual(formatLines(NO_RULES), []);
    const lines = formatLines({ ...NO_RULES, page_limit: 50, blind: true, landscape: true, ppt: true, two_volume: true, volumes: ["정량", "정성"] });
    assert.deepEqual(
      lines.map((line) => [line.manual, line.text.split(" — ")[0]]),
      [
        [false, "50쪽 이내로 냅니다"],
        [false, "평가본에는 회사명 · 대표자를 넣지 않습니다"],
        // 2.10.0 D5 · D7 — 설립일 · 연혁은 앱이 빼고 회사 이름 · 연락처 · 번호 · 실적 기관 이름은 품질 검사가 찾는다
        [true, "평가본에 영문 회사 이름 · 로고 · 인증 이름 속 회사 표기가 남지 않았는지 직접 확인하세요"],
        [true, "A4 가로로 내야 합니다"],
        [true, "발표 자료(PPT) 꼴로 내야 합니다"],
        [true, "정량 · 정성 제안서를 따로 냅니다(정량 · 정성)"],
      ],
    );
  });

  it("평가본 원문 규정을 직접 맞출 줄로 보인다(검토 11-06 #17) · 자르지 않는다", () => {
    const note = "- 1부는 제안사를 기재하고, 7부는 제안사를 인지할 수 있는 어떠한 표시도 불가(회사소개, 연혁, 실적 등 기재불가)";
    const lines = formatLines({ ...NO_RULES, blind: true, blind_note: note });
    assert.deepEqual(lines.map((line) => line.manual), [false, true, true]);
    assert.equal(lines[1].text, `원문: ${note}`);
    const long = "가".repeat(90);
    assert.equal(formatLines({ ...NO_RULES, blind: true, blind_note: long })[1].text, `원문: ${long}`);
    assert.equal(formatLines({ ...NO_RULES, blind: true, blind_note: "  " }).length, 2);
  });

  it("(2.11.0 T3 · T4 · T3b) 원본 · 사본 표시 · 목차 쪽은 앱이 · 원문 표지 서식은 직접 맞춘다", () => {
    const toc = { line: "◦ 표지, 목차를 포함하여 작성", document: "제안요청서.hwp", page: 9 };
    const cover = { line: "□ 서식 2. 제안서 표지 (본교양식 준수)", document: "제안요청서.hwp", page: 25 };
    const lines = formatLines({ ...NO_RULES, blind: true, original_copy: true, toc_required: toc, cover_form: cover });
    assert.deepEqual(
      lines.map((line) => [line.manual, line.text.split(" — ")[0]]),
      [
        [false, "평가본에는 회사명 · 대표자를 넣지 않습니다"],
        [true, "평가본에 영문 회사 이름 · 로고 · 인증 이름 속 회사 표기가 남지 않았는지 직접 확인하세요"],
        [false, "표지에 원본 · 사본을 적습니다"],
        [false, "원문이 목차를 요구합니다"],
        [true, "원문이 제안서 표지 서식을 정했습니다(「□ 서식 2. 제안서 표지 (본교양식 준수)」 · 제안요청서 25쪽)"],
      ],
    );
    // 내려받는 파일은 저장 초안 형식 — 2.11.0 전에 쓴 초안(원본 · 사본 칸 없음)이면 두 「앱이 넣는다」 줄에 그 말을 붙인다
    const fresh = { ...NO_RULES, original_copy: true, toc_required: toc };
    const notes = (saved?: Partial<typeof fresh> | null) => formatLines(fresh, saved).map((line) => line.text.endsWith(BEFORE_RULE_NOTE));
    assert.deepEqual(notes({ page_limit: 20, blind: true }), [true, true]); // 옛 초안
    assert.deepEqual(notes({ page_limit: 20, blind: true, original_copy: false }), [false, false]); // 2.11.0 뒤 초안
    assert.deepEqual(notes(undefined), [false, false]); // 초안 없음
    assert.deepEqual(notes(null), [false, false]);
    // 옛 초안(칸 없음) · 빈 값은 줄을 만들지 않는다
    assert.deepEqual(formatLines({ ...NO_RULES, original_copy: false, toc_required: null, cover_form: null }), []);
    assert.deepEqual(formatLines({ ...NO_RULES, cover_form: { line: "  ", document: null, page: null } }), []);
    assert.equal(formatLines({ ...NO_RULES, cover_form: { ...cover, document: null } })[0].text.includes("쪽)"), false);
  });

  it("평가본 단추는 원문이 회사명 표기를 막을 때만", () => {
    assert.deepEqual(downloadVariants(null), ["submit", "review"]);
    assert.deepEqual(downloadVariants({ ...NO_RULES, blind: true }), ["submit", "review", "blind"]);
  });

  it("(2.10.0 D8) 원본 · 사본 구분 없는 평가본 공고는 평가본이 첫 단추 · 「제출용」 이름 · 회사명 판은 「회사명 포함본」", () => {
    const only = { ...NO_RULES, blind: true, blind_only: true };
    assert.equal(isBlindOnly(only), true);
    assert.equal(isBlindOnly({ ...NO_RULES, blind: true }), false); // 옛 초안(칸 없음) · 구분 있는 공고는 지금 그대로
    assert.equal(isBlindOnly({ ...NO_RULES, blind_only: true }), false);
    assert.deepEqual(downloadVariants(only), ["blind", "review", "submit"]);
    // 이름 — 서버 `plan_export_service.variant_label` 과 같은 규칙
    assert.equal(variantName("blind", "초안", true), "초안");
    assert.equal(variantName("blind", "제출용", true), "제출용");
    assert.equal(variantName("submit", "제출용", true), WITH_NAME_LABEL);
    assert.equal(variantName("review", "초안", true), "검토용");
    assert.equal(variantName("blind", "초안", false), "평가본");
    assert.equal(variantName("submit", "초안", false), "초안");
    assert.equal(variantButtonLabel("blind", "초안", true), "초안(회사명 없음)");
    assert.equal(variantButtonLabel("blind", "제출용", false), "평가본(회사명 없음)");
    assert.equal(variantButtonLabel("submit", "제출용", true), WITH_NAME_LABEL);
    // 형식 줄 — 평가본이 제출 파일이라고 먼저 말한다
    const lines = formatLines(only);
    assert.equal(lines[0].manual, false);
    assert.match(lines[0].text, /^이 공고는 회사명 없는 평가본만 냅니다 — 「제출용」 파일이 평가본/);
  });
});

describe("초안 머리 줄", () => {
  it("예전 초안(양식 칸 없음)은 다시 쓰라고 한다", () => {
    assert.deepEqual(draftOutlineLine({ outline_source: "rfp", evaluation_total: 100, rfp_document: "규격서" }), { text: OLD_DRAFT_NOTE, warn: true });
  });

  it("새 초안은 미리 보기와 같은 값으로", () => {
    const line = draftOutlineLine({ outline_source: "rfp", evaluation_total: 100, rfp_document: "규격서", outline_where: WHERE, format: { ...NO_RULES, page_limit: 30 } });
    assert.deepEqual(line, {
      text: "제안요청서(개인정보 교육) 31쪽 「□ 제안서 목차 및 작성 방법」의 목차대로 썼습니다 · 기술능력 평가 기준 100점 반영 · 30쪽 이내에 맞춤",
      warn: false,
    });
    assert.equal(draftOutlineLine({ outline_source: "standard", outline_where: null, format: null }).warn, true);
  });
});

describe("실패 글", () => {
  it("401 은 읽기 칸에 맞는 문장 · 409 · 422 는 서버 사유 그대로", () => {
    assert.equal(outlineFailureText(new ApiError(401, "x", "로그인이 필요합니다.")), OUTLINE_SESSION);
    assert.match(outlineFailureText(new ApiError(401, "x", "계정이 꺼졌습니다 — 관리자에게 문의하세요")), /^계정이 꺼졌습니다/);
    const noRfp = "제안요청서가 없어 입찰공고문만 분석했습니다 — 공고 분석을 다시 하세요";
    assert.equal(outlineFailureText(new ApiError(409, "x", noRfp)), noRfp);
  });
});

describe("화면 연결", () => {
  const page = read("app", "plan", "page.tsx");
  it("쓰기 단추 위 접는 칸 · 처음 펼칠 때만 읽는다 · 초안 머리 줄 · 평가본 단추", () => {
    assert.match(page, /data-bid-outline-panel/);
    assert.match(page, /onToggle=\{\(event\) => event\.currentTarget\.open && setOpened\(true\)\}/);
    assert.match(page, /getBidPlanOutline\(/);
    const writer = page.slice(page.indexOf("function BidWriter("));
    assert.ok(writer.indexOf("<BidOutlinePanel") > 0 && writer.indexOf("<BidOutlinePanel") < writer.indexOf("<WriterButtons"), "양식 칸은 쓰기 단추 위");
    assert.match(page, /draftOutlineLine\(doc\)/);
    assert.match(page, /variants=\{downloadVariants\(doc\.format\)\}/);
    assert.match(page, /blindOnly=\{isBlindOnly\(doc\.format\)\}/);
    assert.match(page, /NO_FORMAT_RULES/);
    // 형식 줄은 저장 초안 형식도 받는다(2.11.0 전 초안이면 「다시 쓰면 들어갑니다」)
    assert.match(page, /<BidOutlinePanel noticeId=\{noticeId\} ctx=\{ctx\} saved=\{doc\?\.format\} \/>/);
    assert.match(page, /formatLines\(preview\.format, saved\)/);
  });

  it("내려받기 부품이 평가본 이름을 안다", () => {
    const panel = read("components", "support", "SupportEvidencePanel.tsx");
    assert.match(panel, /variantName\(variant, submitLabel, blindOnly\)/);
    assert.match(panel, /variantButtonLabel\(variant, submitLabel, blindOnly\)/);
  });
});
