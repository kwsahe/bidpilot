/**
 * 2.9.1 입찰 분석 「나라장터 공고 원문 ↗ · 제안요청서 내려받기 ↗」 — 원본(나라장터) 주소만 · 사전규격 규격서 · 공고문은 제안요청서 아님.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import type { NoticeAttachment, NoticeAttachmentList } from "../src/lib/api.ts";
import { noticeSourceHref, rfpLinkOf } from "../src/lib/noticeLinks.ts";

const SOURCE = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK01805118&bidPbancOrd=000";

function file(index: number, name: string, url: string, role: NoticeAttachment["document_role"] = "rfp"): NoticeAttachment {
  return { index, name, url, is_rfp: false, downloadable: true, cached: false, size_bytes: null, document_role: role };
}

function list(rfpIndex: number | null, attachments: NoticeAttachment[], noticeIndex: number | null = null): NoticeAttachmentList {
  return { notice_id: "g2b-x", notice_title: "t", count: attachments.length, rfp_index: rfpIndex, rfp_cached: false,
           notice_index: noticeIndex, notice_cached: false, attachments };
}

describe("공고 원문 · 제안요청서 링크(2.9.1)", () => {
  it("공고 원문은 나라장터 https 주소만", () => {
    assert.equal(noticeSourceHref(` ${SOURCE} `), SOURCE);
    for (const bad of [null, undefined, "", "http://www.g2b.go.kr/x", "https://evil.com/?g2b.go.kr", "javascript:alert(1)"]) {
      assert.equal(noticeSourceHref(bad), null, String(bad));
    }
  });

  it("제안요청서 — 고른 첨부 · 사전규격 규격서 · 공고문이면 없음 · 다른 곳 주소면 없음", () => {
    const own = file(1, "2. 제안요청서.hwp", "https://www.g2b.go.kr/fs/a?x=1");
    assert.deepEqual(rfpLinkOf(list(1, [file(0, "1. 입찰공고문.pdf", "https://www.g2b.go.kr/fs/n", "notice"), own])),
                     { name: "2. 제안요청서.hwp", ext: "hwp", href: "https://www.g2b.go.kr/fs/a?x=1", fromPrespec: false });
    const spec = file(2, "사전규격 규격서 1(R26BD00288735)", "https://www.g2b.go.kr/fs/spec?no=1");
    assert.deepEqual(rfpLinkOf(list(2, [spec])), { name: spec.name, ext: null, href: spec.url, fromPrespec: true });
    // 제안요청서가 없어 공고문이 골라졌으면 — 제안요청서라고 부르지 않는다
    assert.equal(rfpLinkOf(list(0, [file(0, "입찰공고문.hwpx", "https://www.g2b.go.kr/fs/n", "notice")])), null);
    assert.equal(rfpLinkOf(list(0, [file(0, "제안요청서.hwp", "https://evil.com/f")])), null);
    assert.equal(rfpLinkOf(list(null, [own])), null);
    assert.equal(rfpLinkOf(null), null);
  });

  it("(검토) 공고 묶음 압축은 제안요청서라 부르지 않는다 — 같은 첨부가 공고문으로도 골라졌거나 · 압축 이름에 제안요청 · 과업이 없으면", () => {
    const zip = (name: string) => file(0, name, "https://www.g2b.go.kr/fs/z", null);
    assert.equal(rfpLinkOf(list(0, [zip("입찰공고.zip")], 0)), null);
    assert.equal(rfpLinkOf(list(0, [zip("입찰공고-업체작성양식.zip")])), null);
    assert.equal(rfpLinkOf(list(0, [zip("과업 내용서.zip")]))?.ext, "zip");
    assert.equal(rfpLinkOf(list(0, [zip("제안요청서 일체.zip")]))?.name, "제안요청서 일체.zip");
  });

  it("쉬운 보기 머리 · 공고 정보 칸이 같은 링크를 쓴다(제안요청서가 있으면 접힌 첨부 목록 대신 — 첫 화면 단추 12개 상한)", () => {
    const simple = readFileSync(join(import.meta.dirname, "../src/components/cosmos/SimpleDashboard.tsx"), "utf-8");
    assert.match(simple, /data-simple-notice-links/);
    assert.match(simple, /\{rfp === null && attachments\.length > 0 && \(/);
    const detail = readFileSync(join(import.meta.dirname, "../src/components/cosmos/DetailPanel.tsx"), "utf-8");
    assert.match(detail, /<RfpDownloadLink link=\{rfp\} className=\{SOURCE_BUTTON\} \/>/);
  });
});
