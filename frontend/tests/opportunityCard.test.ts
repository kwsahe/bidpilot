/**
 * 사업기회 카드(2.3.0) — 카드 세 줄 · D-day 색 · 인증 대상 거르기. 목록 응답에 있는 값만 옮기고, 없으면 줄을 뺀다.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { bidLines, cleanLine, ddayTone, mentionsCertTarget, supportLines } from "../src/lib/opportunityCard.ts";

const NOW = Date.parse("2026-11-04T10:00:00+09:00");

describe("D-day 색", () => {
  it("3일 이하 빨강 · 7일 이하 호박 · 그 밖 보통 · 지남 · 모름", () => {
    assert.equal(ddayTone("2026-11-06T18:00:00+09:00", NOW), "urgent");
    assert.equal(ddayTone("2026-11-10T18:00:00+09:00", NOW), "soon");
    assert.equal(ddayTone("2026-11-30T18:00:00+09:00", NOW), "normal");
    assert.equal(ddayTone("2026-11-01T18:00:00+09:00", NOW), "closed");
    assert.equal(ddayTone(null, NOW), "none");
    assert.equal(ddayTone("2026-11-30T18:00:00+09:00", null), "none");
  });
});

describe("지원사업 세 줄", () => {
  it("대상은 ☞ 요건 원문 먼저 · 지원은 받는 것이 드러난 문장 · 신청은 신청방법 원문", () => {
    const lines = supportLines({
      target: "중소기업",
      requirementSentences: ["☞ 광주 소재 중소 제조기업"],
      summary: "관내 제조기업의 디지털 전환을 돕습니다. 기업당 최대 2,000만원을 지원합니다.",
      submissionText: "이메일 접수",
    });
    assert.deepEqual(lines, [
      { label: "대상", text: "광주 소재 중소 제조기업" },
      { label: "지원", text: "기업당 최대 2,000만원을 지원합니다." },
      { label: "신청", text: "이메일 접수" },
    ]);
  });

  it("값이 없는 줄은 뺀다 — 빈 말로 채우지 않는다", () => {
    assert.deepEqual(supportLines({ target: "중소기업" }), [{ label: "대상", text: "중소기업" }]);
    assert.deepEqual(supportLines({}), []);
  });

  it("신청방법 원문이 없으면 신청방법 칸의 첫 줄", () => {
    const lines = supportLines({ applyMethod: "\r\n방문 접수\r\n- 접수처 : 강릉시청" });
    assert.deepEqual(lines, [{ label: "신청", text: "방문 접수" }]);
  });
});

describe("입찰 세 줄", () => {
  it("사업(예산 · 일의 종류) · 계약 · 접수(+설명회)", () => {
    const lines = bidLines({
      budgetText: "예산 2.8억원",
      workText: "교육 운영",
      awardLine: "제한경쟁 · 협상에 의한 계약",
      submissionMethods: ["전자입찰"],
      briefingText: "설명회 2026.11.12",
    });
    assert.deepEqual(lines, [
      { label: "사업", text: "예산 2.8억원 · 교육 운영" },
      { label: "계약", text: "제한경쟁 · 협상에 의한 계약" },
      { label: "접수", text: "전자입찰 · 설명회 2026.11.12" },
    ]);
  });

  it("모르는 값은 줄에서 뺀다", () => {
    assert.deepEqual(bidLines({ awardLine: "일반경쟁" }), [{ label: "계약", text: "일반경쟁" }]);
    assert.deepEqual(bidLines({}), []);
  });
});

describe("인증 대상 거르기 · 줄 정리", () => {
  it("사회적기업 · 사회적경제 · 여성기업 낱말", () => {
    assert.equal(mentionsCertTarget(["2026 사회적경제기업 판로 지원"]), true);
    assert.equal(mentionsCertTarget([null, "여성 기업 대상 컨설팅"]), true);
    assert.equal(mentionsCertTarget(["중소기업 디지털 전환", undefined]), false);
  });

  it("줄머리 기호와 겹 공백을 걷는다", () => {
    assert.equal(cleanLine("  ☞  광주   소재 기업 "), "광주 소재 기업");
    assert.equal(cleanLine(null), "");
  });
});
