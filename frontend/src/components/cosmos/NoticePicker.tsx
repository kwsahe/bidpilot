"use client";

/**
 * 공고 선택창 — **네 화면이 함께 쓰는 한 벌** (0920 §4-B-4 · ISSUE-077-a).
 *
 * ## 왜 따로 떼어 냈나
 *
 * 대시보드와 RFP 분석이 **각자 선택창을 갖고 있었다.** 같은 공고 목록인데
 *
 * - 대시보드: 마감 공고를 숨기고(토글로 편다), 시연용 고정 공고를 따로 묶고,
 *   「[B · 69] 제목 · 기관 · 공고번호」로 적었다.
 * - RFP 분석: 마감을 그대로 섞어 보여주고, 시연용 묶음이 없고, 등급·우선순위를 아예 안 적었다.
 *   순서도 달랐다 — 목록 응답 순서(추천 점수)를 그대로 썼기 때문이다.
 *
 * 그래서 담당자가 대시보드에서 3번째로 보던 공고가 RFP 화면에서는 14번째에 있었다.
 * 규칙을 두 곳에 적어 두면 반드시 갈라진다 — 그래서 **여기 하나만 둔다.**
 */

import { useState } from "react";

import Link from "next/link";

import { SourceBadge, noticeSourceKind } from "@/components/ui/SourceBadge";
import { GRADE_LABELS, labelOf, reviewPriorityText } from "@/lib/scoreNames";
import { formatDateTime } from "@/lib/cosmos/format";
import { SCREEN_NAMES, SYNTHETIC_NOTICE } from "@/lib/terms";
import { isSupportProgramId } from "@/lib/selection";
import { isDemoProcurementId } from "@/lib/cosmos/demoNotice";
import type { NoticeOrigin } from "@/lib/cosmos/graph";
import { limitNoticeOptions, pickerHiddenLabel } from "@/lib/cosmos/noticePicker";
import type { NoticeListInfo, NoticeOption } from "@/lib/cosmos/useCosmosDashboard";

/** 고를 수 없는 「목록을 받지 못했습니다」 줄의 값 — 실제 공고 id 와 겹치면 그 줄이 「지금 고른 것」 자리에 선다(2.0.5). */
const G2B_LIST_ERROR_VALUE = "__g2b-list-error__";
const SUPPORT_LIST_ERROR_VALUE = "__support-list-error__";

// 공고 선택기 앞의 키워드 등급 표시. 자리가 좁아 한 글자로 줄인다.
// 뜻은 `lib/scoreNames.ts` 의 사전과 같다 — 거기 값을 첫 글자로만 쓴다.
const TIER_SHORT: Record<string, string> = {
  high: "상",
  medium: "중",
  low: "하",
  none: "-",
};

/**
 * 기업마당 지원사업 항목 문구.
 *
 * 입찰 공고와 같은 모양으로 적으면 같은 흐름인 줄 안다. 그래서 순위·점수 앞에
 * **신청 자격부터** 적는다 — 점수가 높아도 신청할 수 없는 사업이 실제로 있다
 * (실측: 부산 AX클리닉 72점, 회사 활동 지역 밖).
 */
function supportOptionLabel(option: NoticeOption): string {
  // 출처 안 순번(`order` = 같은 출처 순위) — 두 출처를 섞은 번호(1 · 2 · 3 · 4 · 5 · 9)를 쓰지 않는다(38차 FRONTEND-05).
  const shown = option.order ?? option.rank;
  const rank = shown != null ? `${shown}. ` : "";
  const gate = option.gate === "FAIL" ? "[불가] " : "";
  const score = option.score != null ? ` · ${reviewPriorityText(option.score)}` : "";
  // 읽는 중 자리표시 줄은 기관이 비어 있다 — 「지원사업 불러오는 중… · 」로 끝나지 않게(10-31 최종 점검 A3)
  return `${rank}${gate}${option.title}${option.agency ? ` · ${option.agency}` : ""}${score}`;
}

/**
 * `order` — 이 묶음 안에서 **보이는 차례**(검토 우선순위 순으로 세운 뒤의 1, 2, 3…). 예전에는 추천 점수 순위(option.rank)를
 * 적어 우선순위 순 목록 앞 번호가 「3. 1. 7.」처럼 뒤섞여 보였다 (RFP-09).
 */
function noticeOptionLabel(option: NoticeOption, order?: number): string {
  if (option.demo) return `${SYNTHETIC_NOTICE} — ${option.title}`;
  if (option.support) return supportOptionLabel(option);
  // 등급 구간만으로는 같은 등급 안에서 무엇을 먼저 볼지 알 수 없다. 차례를 앞에 둔다.
  const shownRank = order ?? option.rank;
  const rank = shownRank != null ? `${shownRank}. ` : "";
  // 「추천등급 · 검토 우선순위」를 함께 적는다 (0920 §4-B-1). 목록·레이더가 쓰는 값과
  // 같은 값이라, 같은 공고가 어느 화면에서든 같은 숫자로 보인다.
  // 회사 목록 밖(참가 불가 · 실제 마감 지남)이면 추천등급보다 그 사실을 먼저 — 「[추천 A]」를 고르면 「접수 끝남」이 열렸다(2.0.6).
  // 판정이 불가인데 고정 예시라 통합 목록에 남은 공고도 같다 — 「[추천 A]」로 서면 고른 뒤 「참가할 수 없습니다」가 열렸다(2.0.6 실측 2건).
  const grade = option.outside
    ? "[불가·마감] "
    : option.gate === "FAIL"
    ? "[불가] "
    : option.grade
    ? `[추천 ${labelOf(GRADE_LABELS, option.grade)}${option.score != null ? ` · 검토 ${Math.round(option.score)}` : ""}] `
    : option.tier
      ? `[${TIER_SHORT[option.tier] ?? "-"}] `
      : "";
  // 공고번호를 붙인다 — 같은 제목이 여러 건 보일 때 사람이 특정할 수 있는 유일한 값이다.
  const no = option.noticeNo ? ` · ${option.noticeNo}` : "";
  // 정정 · 재공고로 차수가 여러 개면 최신 하나만 보이므로 몇 개가 접혔는지 밝힌다. 「정정 N번」은 재공고까지 정정으로 세고
  // 빈 차수가 있으면 틀렸다 — 셈이 보장하는 말만(31차 R30-37).
  const rev = option.revisionCount > 1 ? ` (차수 ${option.revisionCount}개 중 최신)` : "";
  return `${rank}${grade}${option.title}${option.agency ? ` · ${option.agency}` : ""}${no}${rev}`;
}

/**
 * 공고 선택기 + 데이터 출처 표기. 실공고와 데모를 optgroup 으로 갈라 놓는다.
 *
 * **내보낸다** — RFP 분석 화면이 같은 것을 쓴다 (0920 §4-B-4 · ISSUE-077-a).
 * 예전에는 RFP 에 선택창이 아예 없어서, 「왜 이 공고가 떠 있는지」를 알 수 없었다
 * (마지막으로 연 공고를 브라우저 기록으로 따라갔다). 두 벌을 만들면 마감 숨김 규칙·
 * 시연용 그룹·라벨이 갈린다.
 */
export function NoticePicker({
  notices,
  selectedNoticeId,
  onSelectNotice,
  noticeList,
  supportError,
  disabled,
  disabledReason,
  origin: originOfGraph,
  pinned,
  bare = false,
}: {
  notices: NoticeOption[];
  selectedNoticeId: string;
  onSelectNotice: (id: string) => void;
  noticeList: NoticeListInfo;
  supportError: string | null;
  disabled: boolean;
  /** 잠긴 이유 — 잠겼을 때만 선택 상자 툴팁으로 (DSH-28) */
  disabledReason?: string;
  /**
   * 지금 고른 공고의 출처. 대시보드·RFP 가 각자 만든 그래프에서 꺼내 준다.
   *
   * 그래프 대신 **출처만** 받는다 — RFP 화면은 파싱 전이면 그래프가 아예 없는데,
   * 그때도 「합성 데모인지 실공고인지」는 이미 알고 있기 때문이다.
   */
  origin?: NoticeOrigin | null;
  /** 되살려 붙인 시연용 고정 공고인가. 목록이 실시간이어도 방금 받아 온 것이 아니다. */
  pinned?: boolean;
  /** 쉬운 보기(24차): 선택 상자만 — 「마감 n건 보기」 · 출처 칩 · 목록 건수 · 「전체 목록」을 그리지 않는다 */
  bare?: boolean;
}) {
  const [showClosed, setShowClosed] = useState(false);
  const demoOptions = notices.filter((n) => n.demo);
  const supportOptions = notices.filter((n) => n.support);
  const everyReal = notices.filter((n) => !n.demo && !n.support);
  /**
   * 마감 공고는 기본으로 숨긴다 (ISSUE-035).
   *
   * 나라장터 6건 중 3건이 「[마감]」이었고, 고르면 참여할 수 없는 공고의 분석 화면으로
   * 들어간다. 지울 수는 없다 — 지난 공고를 다시 열어 보는 일이 실제로 있다.
   * 지금 선택된 공고가 마감이면 그것만은 남긴다(안 그러면 select 가 값을 잃는다).
   *
   * **시연용 고정 공고는 예외로 언제나 보인다** (ISSUE-056). 저장해 둔 4건 중 3건이 이미
   * 마감이라, 숨겨 버리면 시연 동선이 날짜에 묶인다. 고정 공고는 저장본이 있어 마감 뒤에도
   * 분석 화면이 그대로 열린다 — 다만 마감 배지와 참여 불가 상태는 사실이므로 그대로 둔다.
   */
  // 회사 목록 밖(불가 · 실제 마감)도 같이 접는다 — 레이더 · 사업기회는 숨기는데 여기만 후보로 세면 후보 수가 갈렸다(188 대 116 · 2.0.6).
  const isClosed = (n: NoticeOption) => n.grade === "NO_GO" || Boolean(n.outside) || n.gate === "FAIL";
  const closedWord = everyReal.some((n) => (n.outside || n.gate === "FAIL") && !n.pinned) ? "마감 · 불가" : "마감";
  const visibleReal = showClosed
    ? everyReal
    : everyReal.filter((n) => !isClosed(n) || n.pinned || n.id === selectedNoticeId);
  // 마감된 고정 공고는 따로 묶는다. 일반 후보 사이에 끼면 「참여할 수 있는 공고」로 읽힌다.
  const pinnedClosedOptions = visibleReal.filter((n) => isClosed(n) && n.pinned);
  const allReal = visibleReal.filter((n) => !(isClosed(n) && n.pinned));
  // 토글이 여닫는 것은 고정이 아닌 마감 공고뿐이다 — 고정은 이미 보이므로 세지 않는다.
  const closedCount = everyReal.filter((n) => isClosed(n) && !n.pinned).length;
  /*
   * **검토 우선순위 순으로 세운다** (0920 §4-B-1 · ISSUE-074-c).
   *
   * 예전에는 `/api/procurements` 응답 순서(= 추천 점수 순, 기본 회사 기준)를 그대로 썼다.
   * 목록·레이더는 검토 우선순위 순(선택 회사 기준)이라 **순서가 뒤집혀 있었다** — 개발 공고가
   * 선택창에서는 1~3위, 목록에서는 14~16위였다. 같은 회사 기준 값 하나로 세운다.
   *
   * 우선순위를 못 받은 건(통합 목록에 없거나 조회 실패)은 **뒤로 보내되 버리지 않는다.**
   * 그 안에서는 받아 온 순서를 지킨다 — 파이썬 정렬처럼 안정 정렬이다.
   */
  // **회사 방식의 순번**으로 세운다(37차 §3-C-4) — 샘플에듀 실무 우선순위 · 그 밖 점수순(동점이면 마감 빠른 순 ·
  // UI-R36-03: 점수만 보면 동점인 1위가 「2.」로 보였다). 순번이 없으면 점수로, 그래도 같으면 받아 온 순서(안정 정렬).
  const ranked = [...allReal].sort((a, b) => {
    const leftOrder = a.order ?? Number.POSITIVE_INFINITY;
    const rightOrder = b.order ?? Number.POSITIVE_INFINITY;
    if (leftOrder !== rightOrder) return leftOrder < rightOrder ? -1 : 1;
    return (b.score ?? -1) - (a.score ?? -1);
  });
  // 드롭다운이 길어지면 시연 중 찾기 어렵다. 상위 N개만 보여주고 전체는 목록 화면에서 본다.
  const realOptions = limitNoticeOptions(ranked, selectedNoticeId);
  // 셈은 접지 않은 후보만 — 지금 보는 공고가 마감 · 불가라 남아 있어도 「n건 중」에 넣지 않는다(레이더 · 사업기회 건수와 같게 · 2.0.6).
  const hiddenLabel = pickerHiddenLabel(allReal.filter((n) => !isClosed(n)).length, realOptions.filter((n) => !isClosed(n)).length);
  // 쉬운 보기에는 「마감 n건 보기」 단추가 없다 — 숨겼다는 사실은 묶음 이름에 남긴다 (EZ-18)
  const closedHint = bare && closedCount > 0 ? ` · ${closedWord} ${closedCount}건 숨김 — 전체 보기에서 보기` : "";

  // 검토 순서(통합 목록)를 받기 전에도 「불러오는 중」 — 불가 · 관련 낮음을 접지 못해 「220건 · 마감 41건 숨김」으로 섰고
  // 나중에 접힐 공고를 1위로 고를 수 있었다(10-31 최종 점검 · 사업기회 · 대시보드와 같은 140건이 된 뒤에 연다).
  const listLoading = (noticeList.status === "loading" && allReal.length === 0) || Boolean(noticeList.priorityPending);
  const g2bListError = !listLoading && realOptions.length === 0 && !closedHint && noticeList.status === "error" && Boolean(noticeList.message);
  // 목록을 못 받아 아무것도 열지 않았는데(가상 예시 자리 id 만 있음) 칸이 「가상 예시」를 고른 것처럼 보이지 않게 — 오류 줄에 선다(2.0.5).
  // 목록은 받았지만 처음 열 공고를 정하지 못한 오류 화면도 같다 — 열지 않은 가상 예시가 골라진 것처럼 보였고, 그 줄을 골라도 같은 값이라 아무 일이 없었다(2.0.6).
  const nothingOpen = Boolean(noticeList.openFailed) && !g2bListError && isDemoProcurementId(selectedNoticeId) && originOfGraph?.kind !== "demo";
  const selectValue =
    (g2bListError || nothingOpen) && isDemoProcurementId(selectedNoticeId) && originOfGraph?.kind !== "demo" ? G2B_LIST_ERROR_VALUE : selectedNoticeId;
  // 후보 수는 접지 않은 공고(마감 · 불가 뺌) — 레이더 · 사업기회의 나라장터 건수와 같은 셈(2.0.6 · 예전 「235건 후보」는 불가까지 셌다).
  const countLabel =
    noticeList.totalFetched !== null && noticeList.count !== null
      ? `${noticeList.totalFetched}건 중 ${everyReal.filter((n) => !isClosed(n)).length}건 후보`
      : null;

  // 현재 선택된 공고의 출처 — 실공고(실시간/캐시)인지 합성 데모인지 항상 보여준다.
  // 그래프가 아직(또는 영영) 없어도 데모 공고인 것은 id 로 안다 — 파싱 전 RFP 화면이 그렇다.
  const origin: NoticeOrigin | null =
    originOfGraph ?? (isDemoProcurementId(selectedNoticeId) ? { kind: "demo" } : null);
  // 지원사업을 보는 중이면 공고 출처 칩이 없다 — 「공고 확인 중」에 멈춰 있지 않게 그리지 않는다 (27차 검수 R27U-MSC-13).
  const originBadge = isSupportProgramId(selectedNoticeId) || nothingOpen ? null : origin ? (
    origin.kind === "demo" ? (
      <SourceBadge kind="demo" label={SYNTHETIC_NOTICE} />
    ) : (
      // 되살려 붙인 고정 공고는 목록이 실시간이어도 방금 받아온 것이 아니다.
      <SourceBadge kind={noticeSourceKind(origin.source, pinned)} fetchedAt={origin.fetchedAt} />
    )
  ) : (
    <SourceBadge kind="not_run" label={noticeList.status === "loading" ? "공고 확인 중" : "출처 확인 중"} />
  );

  return (
    <div
      data-tour="topbar-notice"
      className="flex w-full min-w-0 basis-full flex-wrap items-center gap-2 md:w-auto md:flex-1 md:basis-auto md:flex-nowrap"
    >
      <label className="sr-only" htmlFor="cosmos-notice-picker">
        분석 대상 공고 선택
      </label>
      <select
        id="cosmos-notice-picker"
        value={selectValue}
        disabled={disabled || listLoading}
        title={disabled ? disabledReason : undefined}
        onChange={(event) => onSelectNotice(event.target.value)}
        className="mc-focus min-h-9 w-full min-w-[12rem] max-w-full flex-1 truncate rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5 text-[12.5px] text-cosmos-text backdrop-blur transition-colors hover:border-cosmos-border-strong disabled:cursor-not-allowed disabled:opacity-50 md:max-w-[440px]"
      >
        {/* 45차 M1 — 목록이 오기 전에는 「불러오는 중」 한 줄만(가상 예시 공고가 골라진 것처럼 2.6~17초 떠 있다가 실제 1위로 바뀌었다) */}
        {listLoading && <option value={selectedNoticeId}>공고 목록을 불러오는 중…</option>}
        {nothingOpen && (
          <option value={G2B_LIST_ERROR_VALUE} disabled>
            열린 공고 없음 — 아래에서 공고를 고르세요
          </option>
        )}
        {!listLoading && (realOptions.length > 0 || closedHint) && (
          <optgroup
            label={`${
              hiddenLabel
                ? `나라장터 실공고 후보 — ${hiddenLabel}`
                : `나라장터 실공고 후보 (${realOptions.length})`
            }${closedHint}${
              // 검토 순서(통합 목록)를 못 받으면 순서가 말없이 추천등급 순으로 바뀌었다 — 그 사실과 사유를 적는다(2.0.6)
              noticeList.priorityMessage ? ` · 검토 순서를 받지 못해 추천등급 순 (${noticeList.priorityMessage})` : ""
            }`}
          >
            {realOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {/* 상위 N개 밖에서 붙인 선택 공고도 제 차례로 (ranked 안의 자리) */}
                {noticeOptionLabel(option, ranked.indexOf(option) + 1)}
              </option>
            ))}
          </optgroup>
        )}
        {/* 기업마당과 같다 — 못 받은 출처를 말없이 빼지 않는다(2.0.5). 사유가 있을 때만(목록 요청 실패) — 가상 예시 자료만 실패한 경우는 아니다.
            값은 실제 공고와 겹치지 않게 — 겹치면 앞선 이 줄이 「지금 고른 것」 자리에 섰다. */}
        {g2bListError && (
          <optgroup label="나라장터 실공고 후보">
            <option value={G2B_LIST_ERROR_VALUE} disabled>
              목록을 받지 못했습니다 — {noticeList.message} · 새로고침해 주세요
            </option>
          </optgroup>
        )}
        {!listLoading && pinnedClosedOptions.length > 0 && (
          <optgroup label="예시 공고(마감) — 저장된 자료로 분석 화면이 열립니다">
            {pinnedClosedOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {/* 순위 묶음이 아니다 — 번호(받아 온 순서)를 달면 「1. [불가] …」가 1위로 읽혔다(2.0.6 실측) */}
                {noticeOptionLabel({ ...option, rank: null })}
              </option>
            ))}
          </optgroup>
        )}
        {!listLoading && supportOptions.length > 0 && (
          <optgroup
            label={
              supportError
                ? // 목록을 못 받았는데 지금 보는 사업 하나만 들어 있다 — 「(1)」로 적으면 지원사업이 하나뿐인 것으로 읽힌다(2.0.5)
                  `기업마당 지원사업 — 목록을 받지 못해 지금 보는 사업만 (${supportError})`
                : // 앞 12건만 싣는다 — 「(12)」만 적으면 지원사업이 12건뿐인 줄 읽혔다(2.0.6 · 나라장터 묶음과 같은 「N건 중 상위」)
                  `기업마당 지원사업 — ${
                    pickerHiddenLabel(noticeList.supportTotal ?? supportOptions.length, supportOptions.length) ?? `${supportOptions.length}건`
                  } · 고르면 신청 분석 화면으로`
            }
          >
            {supportOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {noticeOptionLabel(option)}
              </option>
            ))}
          </optgroup>
        )}
        {!listLoading && supportOptions.length === 0 && supportError && (
          <optgroup label="기업마당 지원사업">
            {/* 「없음」이 아니라 「못 받았음」이다. 빈 목록으로 단정하지 않는다. */}
            <option value={SUPPORT_LIST_ERROR_VALUE} disabled>
              목록을 받지 못했습니다 — {supportError}
            </option>
          </optgroup>
        )}
        {!listLoading && (
          <optgroup label={SYNTHETIC_NOTICE}>
            {demoOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {noticeOptionLabel(option)}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      {!bare && closedCount > 0 && (
        <button
          type="button"
          onClick={() => setShowClosed((v) => !v)}
          aria-pressed={showClosed}
          className="mc-focus shrink-0 rounded-lg border border-cosmos-border px-2 py-1 text-[12px] text-cosmos-muted transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
          title="마감됐거나 참가할 수 없는 공고는 레이더 · 사업기회처럼 기본으로 숨깁니다 (시연용으로 저장해 둔 공고는 마감이어도 항상 보입니다)"
        >
          {showClosed ? `${closedWord} ${closedCount}건 숨기기` : `${closedWord} ${closedCount}건 보기`}
        </button>
      )}
      {!bare && originBadge}
      {!bare && (
      <span
        className="hidden shrink-0 whitespace-nowrap text-[12px] text-cosmos-muted 2xl:inline"
        title={
          noticeList.fetchedAt
            ? `목록 조회 ${formatDateTime(noticeList.fetchedAt)}${noticeList.message ? ` · ${noticeList.message}` : ""}`
            : (noticeList.message ?? undefined)
        }
      >
        {countLabel ? `목록 ${countLabel}` : ""}
      </span>
      )}
      {!bare && (
      <Link
        href="/opportunities"
        className="mc-focus hidden min-h-8 shrink-0 items-center whitespace-nowrap rounded-lg border border-cosmos-border px-2.5 text-[12px] text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text xl:inline-flex"
        title="공고 목록에서 순위·추천등급과 산정 근거를 표로 본다"
      >
        {SCREEN_NAMES.opportunities} 목록 →
      </Link>
      )}
    </div>
  );
}
