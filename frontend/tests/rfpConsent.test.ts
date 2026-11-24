/**
 * 「공고 분석」 확인 흐름 (27차 §3-A-3 · §3-A-5) — 로컬에 없는 실공고 첨부는 사람이 확인해야 받는다.
 *
 * `fetch` 를 가짜로 바꿔 서버에 무엇이 나갔는지만 센다. 네트워크를 타지 않는다.
 */

import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import { parseRfpWithConsent, type NoticeAttachmentList } from "../src/lib/api.ts";

interface Sent {
  method: string;
  url: string;
  body: Record<string, unknown> | null;
}

const realFetch = globalThis.fetch;

function stubFetch(list: NoticeAttachmentList | null): Sent[] {
  const sent: Sent[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    sent.push({ method, url, body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null });
    if (url.includes("/attachments")) {
      return list ? new Response(JSON.stringify(list), { status: 200 }) : new Response("{}", { status: 404 });
    }
    return new Response(JSON.stringify({ procurement_id: "x", requirements: [] }), { status: 200 });
  }) as typeof fetch;
  return sent;
}

function listWith(cached: boolean, rfpIndex: number | null = 1): NoticeAttachmentList {
  return {
    notice_id: "g2b-R26BK01716907-000",
    notice_title: "시험 공고",
    count: 2,
    rfp_index: rfpIndex,
    rfp_cached: rfpIndex !== null && cached,
    notice_index: 0,
    notice_cached: cached,
    attachments: [
      { index: 0, name: "입찰공고문.hwpx", url: "https://www.g2b.go.kr/a", is_rfp: false, downloadable: true, cached, size_bytes: cached ? 2_097_152 : null, document_role: "notice" },
      { index: 1, name: "제안요청서.hwp", url: "https://www.g2b.go.kr/b", is_rfp: true, downloadable: true, cached, size_bytes: cached ? 1_048_576 : null, document_role: "rfp" },
    ],
  };
}

const posts = (sent: Sent[]) => sent.filter((call) => call.method === "POST");

afterEach(() => {
  globalThis.fetch = realFetch;
});

describe("공고 분석 확인 흐름", () => {
  it("캐시에 있으면 묻지 않고 플래그 없이 보낸다", async () => {
    const sent = stubFetch(listWith(true));
    let asked = 0;
    const result = await parseRfpWithConsent("g2b-R26BK01716907-000", { confirm: () => ((asked += 1), true) });
    assert.notEqual(result, null);
    assert.equal(asked, 0);
    assert.equal(posts(sent).length, 1);
    assert.equal(posts(sent)[0].body?.fetch_attachment, undefined);
  });

  it("캐시에 없으면 파일 이름을 보여 주고, 확인했을 때만 플래그를 보낸다", async () => {
    const sent = stubFetch(listWith(false));
    let message = "";
    const phases: string[] = [];
    await parseRfpWithConsent("g2b-R26BK01716907-000", {
      confirm: (text) => ((message = text), true),
      onPhase: (phase) => phases.push(phase),
    });
    assert.match(message, /「제안요청서\.hwp」/);
    assert.match(message, /공고 목록과 점수는 바뀌지 않습니다/);
    assert.equal(posts(sent).length, 1);
    assert.equal(posts(sent)[0].body?.fetch_attachment, true);
    assert.deepEqual(phases, ["fetching"]);
  });

  it("취소하면 POST 가 하나도 나가지 않는다", async () => {
    const sent = stubFetch(listWith(false));
    const result = await parseRfpWithConsent("g2b-R26BK01716907-000", { confirm: () => false });
    assert.equal(result, null);
    assert.equal(posts(sent).length, 0);
  });

  it("제안요청서 자리에 입찰공고가 골라져도 입찰공고문이라고 말한다 (서버가 실제로 주는 모양 · 검수 C27)", async () => {
    // 첨부가 공고문뿐이면 서버의 rfp_index 는 null 이 아니라 그 공고문이다(제안요청서 자리 3순위) — 역할은 notice.
    const list = listWith(false, 0);
    list.attachments = [list.attachments[0]];
    stubFetch(list);
    let message = "";
    await parseRfpWithConsent("g2b-R26BK01716907-000", { confirm: (text) => ((message = text), false) });
    assert.match(message, /입찰공고문 1개/);
    assert.doesNotMatch(message, /제안요청서 1개/);
    assert.match(message, /「입찰공고문\.hwpx」/);
  });

  it("압축 파일은 안을 열어야 알므로 「첨부 1개」라고 말한다", async () => {
    const list = listWith(false, 0);
    list.attachments = [{ ...list.attachments[0], name: "입찰공고서 및 제출서식.zip", document_role: null }];
    stubFetch(list);
    let message = "";
    await parseRfpWithConsent("g2b-R26BK01716907-000", { confirm: (text) => ((message = text), false) });
    assert.match(message, /첨부 1개/);
  });

  it("합성 공고는 첨부 목록을 읽지 않고 곧바로 뽑는다", async () => {
    const sent = stubFetch(null);
    await parseRfpWithConsent("synthetic-rfp-0001", { confirm: () => false });
    assert.equal(sent.filter((call) => call.url.includes("/attachments")).length, 0);
    assert.equal(posts(sent).length, 1);
  });
});
