/**
 * 공고 첨부 내려받기 링크 (20차 §4-E · 담당자 「공고문 hwp, pdf를 직접 다운받을 수 있는 링크도 추가」).
 *
 * 링크는 원본 주소만 — 나라장터(https + g2b.go.kr)가 아니면 이름만 적는다(백엔드 `is_allowed_url` 과 같은 규칙).
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { attachmentExt, attachmentLinkOf, isAllowedAttachmentUrl } from "../src/lib/attachments.ts";

const G2B = "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01731641&fileSeq=1";

describe("첨부 링크", () => {
  it("첨부 3건(허용 2 · 비허용 1)이면 링크 2개 · 이름 3개", () => {
    const links = [
      { name: "1. 입찰공고문.pdf", url: G2B },
      { name: "2. 제안요청서.hwp", url: "https://g2b.go.kr/x/downloadFile.do?fileSeq=2" },
      { name: "3. 서식.hwpx", url: "http://evil.example.com/g2b.go.kr/서식.hwpx" },
    ].map(attachmentLinkOf);
    assert.equal(links.filter((l) => l.href !== null).length, 2);
    assert.deepEqual(links.map((l) => l.name), ["1. 입찰공고문.pdf", "2. 제안요청서.hwp", "3. 서식.hwpx"]);
    assert.deepEqual(links.map((l) => l.ext), ["pdf", "hwp", "hwpx"]);
  });

  it("https 가 아니거나 나라장터가 아닌 주소는 링크가 아니다", () => {
    assert.equal(isAllowedAttachmentUrl(G2B), true);
    assert.equal(isAllowedAttachmentUrl(G2B.replace("https:", "http:")), false);
    assert.equal(isAllowedAttachmentUrl("https://g2b.go.kr.evil.com/a.pdf"), false);
    assert.equal(isAllowedAttachmentUrl("https://notg2b.go.kr/a.pdf"), false);
    assert.equal(isAllowedAttachmentUrl("javascript:alert(1)"), false);
    assert.equal(isAllowedAttachmentUrl(""), false);
  });

  it("모르는 확장자는 형식 칩을 붙이지 않는다", () => {
    assert.equal(attachmentExt("공고문.PDF"), "pdf");
    assert.equal(attachmentExt("첨부"), null);
    assert.equal(attachmentExt("사진.jpg"), null);
  });
});
