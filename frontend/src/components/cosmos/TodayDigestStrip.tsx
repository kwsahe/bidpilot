"use client";

/**
 * 「오늘 달라진 것」 — 담당자가 아침에 이 화면을 여는 이유 (0919 §4-B-1).
 *
 * 지금은 아침에 열어도 어제와 같은 화면이다. 달라진 것이 있는지 알려면 목록을 눈으로
 * 훑어야 한다. 한 줄로 먼저 말한다. 누르면 목록 화면이 그 조건으로 열린다.
 *
 * ## 반드시 함께 적는 것
 *
 * **「언제 기준인가」.** 이 숫자는 실호출 없이 «이미 받아 둔 목록»에서 센 것이다.
 * 기준 시각을 빼면 담당자는 방금 확인한 값으로 읽는다. 고정 모드면 그것도 적는다 —
 * 그때는 「변경된 공고」가 0 이어도 「변경이 없다」는 뜻이 아니라 「그동안 받아온 적이
 * 없다」는 뜻이기 때문이다.
 *
 * 값을 못 받아도 **화면을 막지 않는다.** 이 줄은 부가 정보이고, 아래 「지금 할 일」이
 * 본체다. 실패하면 조용히 자리를 비운다.
 */

import Link from "next/link";

import { formatDateTime } from "@/lib/cosmos/format";
import { withinDaysText } from "@/lib/deadline";
import { collectTerm, collectWarns, UNDECIDED } from "@/lib/terms";
import type { DigestCount, TodayDigest } from "@/types/digest";

interface Item {
  label: string;
  count: DigestCount;
  href: string;
}

/**
 * 응답은 부르는 쪽(`DayStrip`)이 한 번 받아 넘긴다 (21차) — 접힌 줄의 숫자와 펼친 이 패널의 숫자가 **같은 응답**이다.
 */
export default function TodayDigestStrip({ digest }: { digest: TodayDigest }) {

  /*
   * `closed=1` 이 붙은 링크와 아닌 링크가 섞여 있는 것은 실수가 아니다. 목록 화면은
   * 기본으로 마감된 건을 숨기므로, **마감된 것까지 세는 숫자**는 그 조건을 함께 넘겨야
   * 누른 숫자와 도착한 목록이 같아진다. 「내 결정 대기 5건」을 눌렀더니 2건이 나온 적이
   * 있다 — 다섯 중 셋이 이미 마감된 공고였다. 「n일 내 마감」은 애초에 지난 것을 세지
   * 않으므로 붙이지 않는다. 「최근 n일 새 공고」도 2.1.0 부터 실제 마감이 지난 것을 세지 않아
   * 붙이지 않는다 — 대시보드 「새 공고」와 같은 범위(2.1.0 검토 4).
   */
  // 이 응답은 나라장터만 센다 — 사업기회의 새 공고 · 마감 조건은 2.1.0 부터 기업마당에도 걸리므로 `src=g2b` 로 범위를 맞춘다
  const items: Item[] = [
    // 「곧 마감」은 일수를 적는데 「새 공고」만 안 적고 있었다. 같은 응답이 기간을 말해
    // 주므로(`new_days`) 같은 형식으로 적는다 — 목록 화면의 조건 줄과도 같은 문구가 된다
    // (0920 §4-B-5 · ISSUE-078).
    { label: `최근 ${digest.new_days}일 새 공고`, count: digest.new_notices, href: "/opportunities?src=g2b&new=1" },
    { label: "변경된 공고", count: digest.changed_notices, href: "/opportunities?src=g2b&changed=1&closed=1" },
    { label: withinDaysText(digest.due_days), count: digest.due_soon, href: `/opportunities?src=g2b&due=${digest.due_days}` },
    // 「검토 중」 탭으로 보낸다 (0920 §4-B-3 · ISSUE-076-a). 이 숫자만 목록 범위를 벗어나므로
    // (목록에서 내려간 공고도 검토 중인 일은 끝내야 한다) 목록 필터로 보내면 다시 어긋난다.
    // 43차 Q26 · NUM-09 — 「참여 미정」은 마감 전 · 마감 지남(목록에서 내려감 포함)으로 나눠 적는다(18건 중 살아 있는 것은 1건이었다)
    {
      label: digest.awaiting_open != null ? `참여 ${UNDECIDED}(마감 전 ${digest.awaiting_open} · 지남 ${digest.awaiting_closed ?? 0})` : `참여 ${UNDECIDED}`,
      count: digest.awaiting_decision,
      href: "/opportunities?tab=review",
    },
  ];

  return (
    <section
      className="mc-panel flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-2 sm:px-4"
      aria-label="오늘 달라진 것"
    >
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">오늘 달라진 것</h2>
      {/* 43차 NUM-03 — 숫자가 무엇을 세는지(누르면 가는 목록과 같은 범위) */}
      <span className="text-[12px] text-cosmos-muted">나라장터 후보 · 참가 불가 뺌</span>

      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        {items.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            title={item.count.basis}
            className="mc-focus inline-flex items-baseline gap-1 rounded px-1 text-[12.5px] text-cosmos-secondary hover:text-cosmos-text"
          >
            {item.label}
            <span
              className={`font-mono tabular-nums ${item.count.value > 0 ? "font-semibold text-cosmos-text" : "text-cosmos-muted"}`}
            >
              {item.count.value}
            </span>
            건
          </Link>
        ))}
      </div>

      {/* 언제 기준인지. 이것이 없으면 위 숫자는 「방금 확인한 값」으로 읽힌다. */}
      <p className="ml-auto flex flex-wrap items-center gap-x-2 text-[12px] text-cosmos-muted">
        <span>
          목록 받은 때 {digest.fetched_at ? formatDateTime(digest.fetched_at) : "없음"}
        </span>
        {digest.frozen && (
          <span className={collectWarns(digest.collect_state) ? "text-cosmos-amber" : "text-cosmos-secondary"}>· {collectTerm(digest.collect_state, digest.fetched_at)}</span>
        )}
      </p>

      {digest.notes.length > 0 && (
        <p className="basis-full text-[12px] leading-4 text-cosmos-muted" role="note">
          {digest.notes.join(" ")}
        </p>
      )}
    </section>
  );
}
