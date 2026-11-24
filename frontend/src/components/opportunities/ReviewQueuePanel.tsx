"use client";

/**
 * 「검토 중」 — 내가 손댄 공고가 어디까지 갔는가 (0919 §4-B-3).
 *
 * 목록 탭은 **새로 들어온 것**을 보여준다. 담당자가 실제로 잃어버리는 것은 「며칠 전에
 * 열어서 뭔가 하다 만 공고」다. 요구사항을 뽑았거나(참여 결정 전) 참여 결정·최종 검토·발견 항목
 * 처리를 남긴 공고를 최근 활동 순으로 세운다(백엔드 `review_queue_service` · OPP-35).
 *
 * 각 줄이 말하는 것은 셋이다: **무엇인가**(공고명·마감 D-n) · **어디까지 갔는가**(결정·검토·
 * 발견 항목 상태) · **다음에 뭘 해야 하는가**(한 줄). 세 번째가 없으면 목록을 보고도
 * 무엇을 눌러야 할지 모른다.
 */

import Link from "next/link";
import { Fragment, useContext, useEffect, useState } from "react";

import ExportMenu from "@/components/opportunities/ExportMenu";
import { OpenSheetContext } from "@/components/opportunities/openSheetContext";
import { useRankingMethod } from "@/components/opportunities/PracticalTags";
import { Badge, EmptyState, InlineAlert, LoadingState } from "@/components/ui/primitives";
import { getReviewQueue } from "@/lib/api";
import { formatDateTime } from "@/lib/cosmos/format";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { dDayOrOverdueText, daysOverdue } from "@/lib/deadline";
import { describeFailure } from "@/lib/errors";
import { isDemoNoticeId, requirementSheetHref } from "@/lib/selection";
import { OPEN_REQUIREMENT_SHEET } from "@/lib/terms";
import type { ReviewQueue, ReviewQueueItem } from "@/types/reviewQueue";

/**
 * 마감까지 남은 날. 이미 지났으면 그렇게 말한다 — 「D--3」은 읽히지 않는다.
 *
 * **백엔드가 센 `days_left` 를 쓰지 않는다** (0920 §4-B-5 · ISSUE-078). 그쪽은
 * `(deadline - now).days` 라 **절삭**이다 — 2일 23시간이 남으면 2 가 된다. 다른 화면은
 * 전부 KST 달력일 차이(`daysUntil`)로 3 을 적었으므로, 같은 공고가 이 패널에서만
 * D-2, 목록·레이더에서 D-3 으로 보였다. 응답의 `deadline_at` 으로 같은 규칙을 쓴다.
 */
/** 「검토 중」 갈래 머리줄(43차 N4). */
const QUEUE_HEADS: Record<string, string> = {
  live: "살아 있는 공고 — 지금 결정할 것",
  closed: "마감 지남 — 결정 기록만 남기면 됩니다",
  gone: "목록에서 내려감 — 받아 둔 목록 밖(마감 · 기간 밖)",
};

function Row({ item, mine }: { item: ReviewQueueItem; mine: string | null }) {
  const nowMs = useNowMs();
  const due = item.deadline_at ? dDayOrOverdueText(item.deadline_at, nowMs) : null;
  const isMine = Boolean(mine && item.recorded_by === mine);
  const overdue = nowMs !== null && daysOverdue(item.deadline_at, nowMs) !== null;
  /**
   * 대시보드로 열 수 있는가 — 받아 둔 목록에서 내려간 공고는 대시보드 목록에도 없어, 누르면 데모로 떨어졌다 (27차 LNK-04).
   * 합성 데모 공고는 목록과 상관없이 열린다.
   */
  const openable = item.notice_known || isDemoNoticeId(item.procurement_id);
  const openSheet = useContext(OpenSheetContext);
  // (2.0.6) 지원사업 · 직접 넣은 공고는 그 화면으로 — 대시보드 · 입찰 정리표는 입찰에만(정리표 단추가 직전에 보던 다른 입찰을 열었다)
  const bid = (item.kind ?? "bid") === "bid";

  return (
    <li className="mc-panel flex flex-col gap-1.5 px-3 py-2.5 sm:px-4">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {openable ? (
          <Link
            href={item.open_path ?? `/analysis?notice=${encodeURIComponent(item.procurement_id)}`}
            className="mc-focus rounded text-[13px] font-semibold text-cosmos-text underline-offset-2 hover:underline"
          >
            {item.title}
          </Link>
        ) : (
          <span className="text-[13px] font-semibold text-cosmos-text">{item.title}</span>
        )}
        {item.agency && <span className="text-[12px] text-cosmos-muted">{item.agency}</span>}
        {isMine && <Badge tone="info">내가 본 건</Badge>}
        {due && (
          <span className={`font-mono text-[12px] tabular-nums ${overdue ? "text-cosmos-muted" : "text-cosmos-amber"}`}>
            {due}
          </span>
        )}
      </div>

      {/* 제목 자리에 공고 id 가 온 이유. 이 줄이 없으면 고장으로 읽힌다. */}
      {!item.notice_known && (
        <p className="text-[12px] leading-4 text-cosmos-muted" data-review-dropped={openable ? undefined : ""}>
          {item.in_cache
            ? "관련 낮음으로 입찰 분석 목록에 없는 공고입니다."
            : item.title === item.procurement_id
              ? "받아 둔 목록에서 내려간 공고입니다 — 공고명 대신 공고 id 를 씁니다."
              : // 10-31 최종 점검 — 서버가 다른 기록에서 공고명을 찾아 넣었으면 「id 를 씁니다」는 틀린 말
                "받아 둔 목록에서 내려간 공고입니다."}
          {!openable && " 입찰 분석으로는 열 수 없습니다."}
          {item.document && ` 제안요청서: ${item.document}`}
          {/* 요구사항이 없어도 정리표가 「분석 전」으로 받는다 — 막다른 길을 두지 않는다(검수 LNK-R1) */}
          {!openable && bid && (
            <>
              {" "}
              {/* 사업기회 안에서는 행 입구와 같은 함수(선택 저장 + 탭 상태) — 같은 주소 링크는 탭이 review 로 남았다(29차 R28-02) */}
              {openSheet ? (
                <button
                  type="button"
                  onClick={() => openSheet(item.procurement_id)}
                  className="mc-focus rounded font-medium text-cosmos-cyan underline-offset-2 hover:underline"
                  data-review-sheet-open
                >
                  {OPEN_REQUIREMENT_SHEET}
                </button>
              ) : (
                <Link
                  href={requirementSheetHref(item.procurement_id)}
                  className="mc-focus rounded font-medium text-cosmos-cyan underline-offset-2 hover:underline"
                >
                  {OPEN_REQUIREMENT_SHEET}
                </Link>
              )}
            </>
          )}
        </p>
      )}

      <p className="text-[12.5px] text-cosmos-secondary">
        <span className="text-cosmos-muted">다음 할 일</span> {item.next_step}
      </p>

      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-cosmos-muted">
        {/* 「참여 참여 안 함」이 되지 않게 앞말은 「결정」으로 둔다. */}
        {item.decision_label && <span>결정 {item.decision_label}</span>}
        {item.review_label && <span>최종 검토 {item.review_label}</span>}
        {item.resolution_label && <span>발견 항목 {item.resolution_label}</span>}
        <span className="ml-auto">
          {item.last_activity_kind ?? "활동"} {item.last_activity_at ? formatDateTime(item.last_activity_at) : "시각 없음"}
          {item.recorded_by && ` · ${item.recorded_by}`}
        </span>
      </div>
    </li>
  );
}

/** 회사를 바꾸면 이전 회사의 목록이 남아 있으면 안 된다. 그래서 결과를 «어느 회사 것인지»와 함께 들고 있는다. */
interface Loaded {
  key: string;
  queue: ReviewQueue | null;
  error: string | null;
}

export default function ReviewQueuePanel({ organizationId }: { organizationId: string }) {
  // 내보낸 파일의 순서는 회사 방식이다(38차 FRONTEND-04 — 샘플에듀 파일은 실무순인데 「검토 우선순위순」이라 적었다).
  const rankingMethod = useRankingMethod();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  /** 「다시 시도」 — 이미 이 탭일 때 다시 부를 길이 새로고침뿐이었다 (OPP-34). */
  const [attempt, setAttempt] = useState(0);
  const key = `${organizationId}|${attempt}`;

  useEffect(() => {
    let alive = true;
    getReviewQueue(organizationId)
      .then((value) => {
        if (alive) setLoaded({ key, queue: value, error: null });
      })
      .catch((failure) => {
        if (alive) {
          setLoaded({ key, queue: null, error: describeFailure(failure, "검토 중인 공고를 불러오지 못했습니다.") });
        }
      });
    return () => {
      alive = false;
    };
  }, [organizationId, key]);

  // effect 안에서 state 를 비우면 렌더가 한 번 더 돌고 린트도 막는다. 「어느 회사 것인가」를
  // 비교해 판단한다 — 이 화면의 다른 목록들과 같은 방식이다.
  const fresh = loaded && loaded.key === key ? loaded : null;
  if (fresh?.error)
    return (
      <InlineAlert tone="fail">
        {fresh.error}{" "}
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className="mc-focus rounded font-semibold text-cosmos-cyan underline">
          다시 시도
        </button>
      </InlineAlert>
    );
  if (!fresh || fresh.queue === null) return <LoadingState label="검토 중인 공고를 불러오는 중" rows={3} />;
  const queue = fresh.queue;

  if (queue.items.length === 0) {
    return (
      <EmptyState title="검토 중인 공고가 없습니다">
        요구사항을 뽑았거나, 참여 여부 · 최종 검토 · 발견 항목 처리를 남긴 공고가 여기에 모입니다.
      </EmptyState>
    );
  }

  return (
    <>
      {/*
        **여기서도 엑셀로 내보낸다** (0924 §4-C-3). 담당자가 검토 중인 것을 남에게 보낼 때
        목록 탭으로 돌아가 다시 조건을 맞출 이유가 없다. 워크북의 「사업기회」 시트가 지금
        조건 그대로이고, 「이번 주 할 일」 시트가 마감이 닥친 것만 따로 담는다.
      */}
      <div className="flex justify-end">
        {/* 조건을 넘기지 않으므로 서버 기본 조건 그대로다 — 안내도 그 사실대로 (OPP-12) */}
        <ExportMenu
          query={{ organizationId }}
          hint={`파일에 반영: 기본 조건(최근 30일 · 마감 · 불가 제외 · ${rankingMethod === "practical" ? "실무 우선순위순" : "회사 기준 검토 우선순위순"} — 회사 방식) 목록 — 엑셀 시트 일곱. 검토 중 시트는 따로 없고, 마감됐거나 30일 밖의 검토 중 공고는 들어가지 않습니다.`}
        />
      </div>
      <p className="text-[12px] text-cosmos-muted">
        요구사항을 뽑았거나 참여 결정 · 최종 검토 · 발견 항목 처리를 남긴 공고를 최근 활동 순으로 보여줍니다(결정 전이면 「활동 시각 없음」일 수 있습니다).
        {queue.mine
          ? " 내가 남긴 것을 앞에 둡니다."
          : " 계정 로그인이 꺼져 있어 「내 것 먼저」는 적용하지 않았습니다."}
        {queue.truncated && ` 전체 ${queue.total}건 중 ${queue.items.length}건만 보여줍니다.`}
      </p>
      {queue.counts && (
        <p className="text-[13px] text-cosmos-secondary" data-review-counts>
          살아 있는 공고 {queue.counts.live}건 · 마감 지남 {queue.counts.closed}건 · 목록에서 내려감 {queue.counts.gone}건
        </p>
      )}
      <ul className="flex flex-col gap-2" aria-label="검토 중인 공고">
        {queue.items.map((item, index) => {
          // 43차 N4 — 살아 있음 → 마감 지남 → 목록에서 내려감 머리줄(서버가 그 순서로 보낸다)
          const state = item.queue_state;
          const head = state && state !== queue.items[index - 1]?.queue_state ? QUEUE_HEADS[state] : null;
          return (
            <Fragment key={item.procurement_id}>
              {head && <li className="pt-1 text-[12.5px] font-semibold text-cosmos-muted" role="presentation">{head}</li>}
              <Row item={item} mine={queue.mine} />
            </Fragment>
          );
        })}
      </ul>
    </>
  );
}
