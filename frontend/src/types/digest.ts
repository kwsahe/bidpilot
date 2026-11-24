/** 「오늘 달라진 것」 한 줄 (`GET /api/dashboard/today`). */

import type { CollectState } from "./opportunity";

/** 숫자 하나와 «무엇을 근거로 셌는가». 근거 없는 숫자는 화면에 올리지 않는다. */
export interface DigestCount {
  value: number;
  /** 툴팁에 그대로 쓴다. 예: "공고 게시일이 최근 3일 이내" */
  basis: string;
}

export interface TodayDigest {
  /** 이 집계를 낸 시각 */
  as_of: string;
  /**
   * 공고 목록을 **마지막으로 받아온** 시각. 아직 받아온 적이 없으면 null.
   *
   * 반드시 숫자와 함께 보여준다 — 언제 기준인지 모르는 숫자는 없느니만 못하다.
   */
  fetched_at: string | null;
  source: string | null;
  /** 시연 고정 모드인가. 켜져 있으면 변경 감지가 멈춰 있다. */
  frozen: boolean;
  /** 매일 아침 자동 받기의 마지막 성공(48시간 안일 때만 · 38차 §3-C-4). 없으면 null. */
  auto_collect_at?: string | null;
  /** 자동 받기 한 줄(39차 §3-F-2) — 목록 응답과 같은 값. */
  collect_state?: CollectState | null;
  new_days: number;
  due_days: number;
  total_notices: number;
  /** 요구사항이 저장된(= 분석을 시작한) 공고 수 */
  analysed_notices: number;
  new_notices: DigestCount;
  changed_notices: DigestCount;
  due_soon: DigestCount;
  awaiting_decision: DigestCount;
  /** 「참여 미정」 중 마감 전 · 마감 지남(목록에서 내려감 포함) — 43차 Q26. 옛 응답에는 없다. */
  awaiting_open?: number;
  awaiting_closed?: number;
  /**
   * 내용이 바뀐 공고 id. 목록 화면이 「변경된 것만」으로 거르는 데 쓴다.
   *
   * 새 공고·마감은 목록만 있으면 화면에서 셀 수 있지만, 변경 여부는 버전 기록을 읽어야
   * 알 수 있어 화면이 스스로 판단하지 못한다. 그래서 이것만 id 로 내려온다.
   */
  changed_ids: string[];
  /**
   * 분석을 시작했는데 아직 참여 여부를 정하지 않은 공고 id. 같은 이유로 id 가 필요하다 —
   * 「결정했는가」는 저장소를 읽어야 알 수 있어 목록만으로는 판단하지 못한다.
   */
  pending_ids: string[];
  /** 숫자를 그대로 읽으면 안 되는 사정. 예: 고정 모드라 변경 감지가 멈춰 있다. */
  notes: string[];
}
