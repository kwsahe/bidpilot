"use client";

/**
 * 「시연 고정 모드」 안내 — 문구를 한 곳에만 둔다.
 *
 * 목록 조회는 캐시가 15분 지나면 나라장터를 다시 부르고, 그 결과로 저장소가 추적하는
 * 캐시 파일을 덮어쓴다. 시연 중 그 한 번으로 「수집 107건」이 다른 숫자가 되고 큐시트·
 * 리허설 캡처와 어긋난다 (ISSUE-062). 그래서 시연 때는 `G2B_LIVE_FETCH=0` 으로 띄운다.
 *
 * 화면은 그 상태를 **숨기지 않는다.** 「캐시」 배지만으로는 「키가 없어서」와 「키가 있는데
 * 일부러 안 부름」이 구분되지 않기 때문이다. 새로고침 단추도 함께 잠근다 — 눌러도 같은
 * 값이 나오는 단추를 열어 두면 발표자가 「먹통이다」라고 읽는다.
 */

import { KEYWORD_SEARCH_EXCEPTION } from "@/lib/collectKeywords";
import { collectTerm, collectWarns } from "@/lib/terms";
import { useDeploymentMode } from "@/lib/useDeploymentMode";
import type { CollectState } from "@/types/opportunity";

export const FROZEN_LABEL = "새 공고 받기 꺼짐 — 마지막으로 받아 둔 목록입니다";

/**
 * 고정 모드는 발표 때만이 아니라 평소 기본값이다 — 「발표 중 … 일부러 잠가 두었습니다」는 낡은 말이었다 (CMN-06 · RDR-42).
 * 통합 목록은 두 출처가 **모두** 풀려야 풀린다 — 하나만 켜면 이 안내가 그대로 남는다.
 * 설정 이름은 화면에 적지 않는다 — 담당자가 읽을 말이 아니다(27차 §3-H · 어휘 검사).
 */
export const FROZEN_DETAIL =
  "나라장터·기업마당을 새로 부르지 않고 저장된 목록만 씁니다. " +
  "새 공고를 받으려면 서버 관리자에게 고정 해제를 요청하세요 — 나라장터 · 기업마당 둘 다 풀어야 목록이 새로 바뀝니다.";

/** 새로고침 단추에 붙일 사유. 잠긴 이유를 단추 옆에서 바로 읽을 수 있게 한다. */
export const FROZEN_RELOAD_REASON = "화면에서는 새로 받지 않습니다 — 저장된 목록만 씁니다";

/** 자동 받기가 켜진 PC(예약 작업)의 풀이 — 「관리자에게 고정 해제를 요청하세요」를 쓰지 않는다(39차 §3-F-2 · 40차 D30 「켤 때 받기」). */
export const COLLECT_DETAIL = "새 공고는 하루에 한 번, PC 를 처음 켜거나 잠금을 풀 때 자동으로 받습니다 — 화면에서 바로 받지는 않습니다.";
/** 회사 서버(로그인 · 중계)의 풀이(43차 M27) — 노트북 「켤 때 받기」 글이 서버 화면에 그대로 나왔다. */
export const COLLECT_DETAIL_SERVER =
  "새 공고는 회사 서버가 매일 아침 07:30 에 받습니다(못 받으면 09:30 · 11:30 에 다시) — 화면에서 바로 받지는 않습니다. 11:30 시도까지 못 받았다는 줄이 보이면 관리자에게 「지금 받기」를 부탁하세요.";

/** `keywordSearchLive` — 「찾는 낱말」 바로 찾기 문이 켜진 서버(2.0.7). 「화면에서 바로 받지 않습니다」 아래에 그 예외를 적는다. */
export function FrozenNotice({
  className = "",
  collectState = null,
  keywordSearchLive = false,
}: {
  className?: string;
  collectState?: CollectState | null;
  keywordSearchLive?: boolean;
}) {
  // 예약 작업이 있는 PC 는 자동 받기 한 줄(`collectTerm` — 머리 줄 · 배지 · 읽어 주는 이름과 같은 함수) · 키트(none)는 예전 안내 그대로 ·
  // 상태를 아직 모르면(불러오는 중 · 통합 목록 실패) 중립 한 줄 — 「관리자에게 고정 해제」를 그리지 않는다(40차 FRONT-05 · SCREEN-01).
  // 꺼 둠(D28)은 「자동으로 받습니다」 풀이를 붙이지 않는다.
  const kit = collectState?.kind === "none" || (collectState != null && !collectState.text);
  const scheduled = collectState != null && !kit;
  const warn = collectWarns(collectState);
  const server = useDeploymentMode()?.backend === "proxy";
  const collectDetail = server ? COLLECT_DETAIL_SERVER : COLLECT_DETAIL;
  const detail = kit ? FROZEN_DETAIL : scheduled && collectState?.kind !== "off" ? collectDetail : FROZEN_RELOAD_REASON;
  return (
    <div
      className={`rounded-md border px-2.5 py-2 ${warn ? "border-cosmos-amber/40 bg-cosmos-amber/10" : "border-cosmos-border bg-cosmos-panel"} ${className}`}
      role="status"
    >
      <p className={`text-[12px] font-semibold ${warn ? "text-cosmos-amber" : "text-cosmos-text"}`}>
        <span aria-hidden="true">{warn ? "⏸ " : "● "}</span>
        {kit ? FROZEN_LABEL : collectTerm(collectState)}
      </p>
      <p className="mt-0.5 text-[12px] text-cosmos-secondary">{detail}</p>
      {keywordSearchLive && <p className="mt-0.5 text-[12px] text-cosmos-secondary">{KEYWORD_SEARCH_EXCEPTION}</p>}
    </div>
  );
}
