"use client";

/**
 * 사업기회 「선제준비」 탭 (39차 담당자 결정 1). 메뉴는 그대로 다섯이다.
 *
 * 사전규격은 **입찰 목록 밖**이다 — 입찰 순위 · 대시보드 첫 공고 · 고르기 칸 · 제안서 고르기 · 레이더에 들지 않는다.
 * 한 사전규격은 한 곳에만 든다(서버 `prespec_service.section`):
 * - 본업이고 의견 마감이 남은 것 — 기본으로 보인다(의견 마감 남은 것 → 등록일 새것).
 * - 본업이 아닌 것(관련 낮음 · 연구 · 감리 · 구매 · 대형) — 「다른 사전규격 n건」으로 접는다.
 * - 의견 마감이 지난 것 — 「의견 마감 지남 n건」으로 접는다.
 * - 본공고가 나온 것 — 칸에서 빼고 본공고 행에 「사전규격 n일 전 공개」로 남는다(여기서는 수만).
 * 발주계획(발주 예정)은 아래 표 — 본공고가 이미 났으면 「본공고 나옴 →」이고 「공고 전」이라 하지 않는다(PRESPEC-03).
 *
 * 처음 하는 대표가 읽는 화면이다 — 「의견 마감은 입찰 마감이 아니다」를 먼저 적는다(memory: owner-first-time-bidder).
 */

import { useEffect, useState } from "react";
import Link from "next/link";

import { PracticalTags } from "@/components/opportunities/PracticalTags";
import { InlineAlert } from "@/components/ui/primitives";
import { getPrepareSection } from "@/lib/api";
import { formatBudgetCompact, formatDate, formatDateTime } from "@/lib/cosmos/format";
import { describeFailure } from "@/lib/errors";
import { reviewPriorityText } from "@/lib/scoreNames";
import type { OrderPlanRow, PrepareSection, UnifiedOpportunity } from "@/types/opportunity";

const linkClass = "mc-focus rounded text-[14px] text-cosmos-cyan hover:underline";

function PreSpecRow({ item }: { item: UnifiedOpportunity }) {
  return (
    <li data-prepare-row={item.id} className="mc-panel flex min-w-0 flex-col gap-1 p-3">
      <p className="break-keep text-[15px] font-medium leading-snug text-cosmos-text [overflow-wrap:anywhere]">{item.title}</p>
      <p className="text-[13px] text-cosmos-secondary [overflow-wrap:anywhere]">
        {item.agency} · 배정예산 {formatBudgetCompact(item.budget ?? null)} · 공개 {formatDate(item.published_at ?? null)}
      </p>
      <p className="flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-cosmos-secondary">
        <span className="text-cosmos-text">{item.deadline_text ?? "의견 마감일 없음"}</span>
        <span className="tabular-nums">{reviewPriorityText(item.company_priority_score)}</span>
      </p>
      {/* 41차 FRONT-R40-02 — 유형(근사) · 「주제 확인」 · AI 「본업 아닐 수 있음」(실무 우선순위 회사는 이 꼬리표가 칸 안 순서의 이유다) */}
      <PracticalTags item={item} withGroup={false} />
      {/* 43차 M13 · Q16 — 본공고 예상(실측 범위) · 사업기간 · 할 일 */}
      {item.prespec_plan && <p className="text-[13px] leading-5 text-cosmos-text" data-prepare-plan>{item.prespec_plan}</p>}
      {item.relevance_note && <p className="text-[13px] leading-5 text-cosmos-muted">{item.relevance_note}</p>}
      <div className="flex flex-wrap items-center gap-3 pt-0.5">
        {item.detail_url && (
          <a href={item.detail_url} target="_blank" rel="noreferrer noopener" className={linkClass}>
            규격서(나라장터) ↗
          </a>
        )}
      </div>
    </li>
  );
}

/** 접힌 묶음 — 펼칠 때 받는다(45차 M2 · `items` 가 null 이면 아직 안 받음). */
function Folded({ label, count, items, testId, onOpen, failed }: { label: string; count: number; items: UnifiedOpportunity[] | null; testId: string; onOpen: () => void; failed: string | null }) {
  if (count === 0) return null;
  return (
    <details data-prepare-fold={testId} className="min-w-0 rounded-lg border border-cosmos-border px-3 py-2" onToggle={(event) => event.currentTarget.open && onOpen()}>
      <summary className="mc-focus cursor-pointer rounded text-[14px] text-cosmos-secondary">
        {label} {count}건
      </summary>
      {items === null ? (
        failed ? <InlineAlert tone="fail">{failed}</InlineAlert> : <p className="mt-2 text-[13px] text-cosmos-muted" role="status">묶음을 받는 중…</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2" role="list">
          {items.map((item) => (
            <PreSpecRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </details>
  );
}

function PlanRow({ plan }: { plan: OrderPlanRow }) {
  return (
    <li data-plan-row className="flex min-w-0 flex-col gap-0.5 border-b border-cosmos-border/60 py-2 last:border-b-0">
      <p className="break-keep text-[14px] text-cosmos-text [overflow-wrap:anywhere]">{plan.title}</p>
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px] text-cosmos-secondary">
        <span className="[overflow-wrap:anywhere]">{plan.agency}</span>
        <span>발주 {plan.when}</span>
        <span>{formatBudgetCompact(plan.amount ?? null)}</span>
        <span>{plan.method}</span>
        {plan.fit_type && <span title="유형(근사) — 제목 낱말로 본 갈래(점수 · 판정이 아닙니다)">유형(근사) {plan.fit_type}</span>}
        {plan.main_out ? (
          plan.main_notice_id ? (
            <Link href={`/analysis?notice=${encodeURIComponent(plan.main_notice_id)}`} className={linkClass}>
              본공고 나옴 →
            </Link>
          ) : (
            <span className="text-cosmos-text">본공고 나옴(나라장터에서 확인)</span>
          )
        ) : plan.prespec_out ? (
          <span className="text-cosmos-text">사전규격 나옴 → 위 선제준비 칸</span>
        ) : (
          <span>{plan.delayed ? <strong className="text-cosmos-amber">발주 지연 · 공고 전</strong> : "공고 전"}</span>
        )}
        {plan.url && (
          <a href={plan.url} target="_blank" rel="noreferrer noopener" className={linkClass}>
            발주계획 ↗
          </a>
        )}
      </p>
      {plan.note && <p className="text-[13px] leading-5 text-cosmos-muted">{plan.note}</p>}
    </li>
  );
}

export default function PreparePanel({ organizationId }: { organizationId: string }) {
  // 받은 값은 어느 회사 것인지와 함께 든다 — 회사를 바꾸면 옛 회사의 칸을 그리지 않고 「읽는 중」이다.
  const [loaded, setLoaded] = useState<{ org: string; section: PrepareSection | null; error: string | null } | null>(null);
  // 접힌 묶음(펼칠 때 한 번 받는다 · 회사마다)
  const [folds, setFolds] = useState<{ org: string; section: PrepareSection | null; error: string | null } | null>(null);
  const [foldsAsked, setFoldsAsked] = useState<string | null>(null);
  const openFolds = () => {
    if (foldsAsked === organizationId) return;
    setFoldsAsked(organizationId);
    const org = organizationId;
    getPrepareSection(org, "folds").then(
      (value) => setFolds({ org, section: value, error: null }),
      (failure: unknown) => setFolds({ org, section: null, error: describeFailure(failure, "묶음을 받지 못했습니다.") }),
    );
  };

  useEffect(() => {
    let alive = true;
    getPrepareSection(organizationId, "main")
      .then((value) => {
        if (alive) setLoaded({ org: organizationId, section: value, error: null });
      })
      .catch((failure: unknown) => {
        if (alive) setLoaded({ org: organizationId, section: null, error: describeFailure(failure, "선제준비 칸을 읽지 못했습니다.") });
      });
    return () => {
      alive = false;
    };
  }, [organizationId]);

  const current = loaded?.org === organizationId ? loaded : null;
  const section = current?.section ?? null;
  const error = current?.error ?? null;
  const waiting = current === null;
  const foldsHere = folds?.org === organizationId ? folds : null;
  const othersCount = section ? (section.others_count ?? section.others.length) : 0;
  const passedCount = section ? (section.opinion_passed_count ?? section.opinion_passed.length) : 0;
  const mergedCount = section ? (section.merged_count ?? section.merged.length) : 0;
  const pending = section ? section.plans.filter((p) => !p.main_out && !p.prespec_out).length : 0;
  return (
    <div className="flex min-w-0 flex-col gap-6" data-prepare-panel>
      <section aria-labelledby="prepare-head" className="flex min-w-0 flex-col gap-3">
        <h2 id="prepare-head" className="text-[17px] font-semibold text-cosmos-text">
          선제준비 — 본업 사전규격 {section ? `${section.items.length}건` : "…"}
        </h2>
        <p className="text-[14px] leading-6 text-cosmos-secondary">
          사전규격은 본공고 전에 기관이 미리 공개하는 규격서입니다. <strong className="text-cosmos-text">「의견 마감」은 입찰 마감이 아닙니다</strong> —
          이때 준비를 시작하면 본공고가 나왔을 때 여유가 생깁니다. 판정은 모두 「확인 필요 — 본공고 전」이고, 입찰 순위에는 넣지 않습니다.
          순서는 의견 마감 남은 것 → 의견 마감 7일 묶음(이번 주 · 다음 주 …) → 묶음 안 유형(교육 운영 → 콘텐츠 → 컨설팅 → 개발) · 점수 → 등록일 새것이고, 실무 우선순위 회사는 그 앞에 주제 맞음 먼저(「주제 확인」 · AI 꼬리표는 뒤)입니다.
        </p>
        {section?.fetched_at && (
          <p className="text-[13px] text-cosmos-muted">
            사전규격 받은 때 {formatDateTime(section.fetched_at)}
            {section.plans_fetched_at ? ` · 발주계획 받은 때 ${formatDateTime(section.plans_fetched_at)}` : ""}
          </p>
        )}
        {error && <InlineAlert tone="fail">{error}</InlineAlert>}
        {/* (2.0.6) 서버는 나라장터만 못 읽어도 200 으로 답한다 — 빈 칸을 「보일 것이 없습니다」로 적지 않고 사유를 보인다 */}
        {section?.source_error && (
          <InlineAlert tone="fail">
            나라장터 목록을 읽지 못해 사전규격을 고르지 못했습니다 — {section.source_error}
          </InlineAlert>
        )}
        {waiting && (
          <p className="text-[14px] text-cosmos-muted" role="status">
            사전규격을 읽는 중…
          </p>
        )}
        {section && !section.source_error && section.items.length === 0 && (
          <p className="rounded-lg border border-dashed border-cosmos-border px-3 py-4 text-[14px] text-cosmos-muted">
            {/* 접힌 묶음이 없으면 「아래에 나머지」라고 하지 않는다(39차 키트 — 받은 사전규격이 없는 PC) */}
            {passedCount + othersCount > 0
              ? "지금 본업으로 분류된 사전규격 중 의견 마감이 남은 것이 없습니다. 아래 접힌 묶음에 나머지가 있습니다."
              : section.fetched_at
                ? "받아 둔 사전규격 중 여기에 보일 것이 없습니다."
                : "사전규격 목록을 아직 받지 않았습니다."}
          </p>
        )}
        {section && section.items.length > 0 && (
          <ul className="flex flex-col gap-2" role="list">
            {section.items.map((item) => (
              <PreSpecRow key={item.id} item={item} />
            ))}
          </ul>
        )}
        {section && (
          <>
            <Folded label="의견 마감 지남" count={passedCount} items={foldsHere?.section?.opinion_passed ?? null} failed={foldsHere?.error ?? null} onOpen={openFolds} testId="opinion-passed" />
            <Folded label="다른 사전규격(본업 아님 · 연구 · 감리 · 구매 · 대형)" count={othersCount} items={foldsHere?.section?.others ?? null} failed={foldsHere?.error ?? null} onOpen={openFolds} testId="others" />
            {mergedCount > 0 && (
              <p className="text-[13px] leading-5 text-cosmos-muted">
                본공고가 나온 사전규격 {mergedCount}건은 여기서 뺐습니다 — 입찰 목록의 그 공고 행에 「사전규격 n일 전 공개」로 남아 있습니다.
              </p>
            )}
          </>
        )}
      </section>

      {section && (
        <section aria-labelledby="plan-head" className="flex min-w-0 flex-col gap-2">
          <h2 id="plan-head" className="text-[17px] font-semibold text-cosmos-text">
            발주 예정(발주계획) — 본공고 전 {pending}건
          </h2>
          <p className="text-[14px] leading-6 text-cosmos-secondary">
            기관이 미리 적은 발주 계획입니다. 실제 공고와 다를 수 있습니다. 본공고가 이미 났으면 「본공고 나옴」으로 적습니다
            {section.plans_low > 0 ? ` · 낱말만 걸리고 후보가 아닌 ${section.plans_low}건은 뺐습니다` : ""}.
          </p>
          {section.plans_note && <InlineAlert tone="warn">{section.plans_note}</InlineAlert>}
          {section.plans.length === 0 ? (
            <p className="rounded-lg border border-dashed border-cosmos-border px-3 py-4 text-[14px] text-cosmos-muted">발주 예정 후보가 없습니다.</p>
          ) : (
            <ul className="mc-panel flex flex-col px-3" role="list">
              {section.plans.map((plan, index) => (
                <PlanRow key={`${plan.title}-${index}`} plan={plan} />
              ))}
            </ul>
          )}
          {(section.plans_folded?.length ?? 0) > 0 && (
            <details data-plan-folded className="min-w-0 rounded-lg border border-cosmos-border px-3 py-2">
              <summary className="mc-focus cursor-pointer rounded text-[14px] text-cosmos-secondary">
                본업 덩어리 밖(연구 · 감리 · 구매 · 제작) {section.plans_folded?.length}건 — 사유와 함께 접음
              </summary>
              <ul className="mt-1 flex flex-col" role="list">
                {section.plans_folded?.map((plan, index) => (
                  <PlanRow key={`folded-${plan.title}-${index}`} plan={plan} />
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
