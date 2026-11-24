/** 「검토 중」 줄 (`GET /api/review-queue`). */

export interface ReviewQueueItem {
  procurement_id: string;
  /**
   * 갈래(2.0.6) — 입찰 · 지원사업(기업마당) · 직접 넣은 공고. 셋 다 같은 결정 파일을 써서 지원사업이 입찰처럼 그려졌다.
   * 옛 응답에는 없다(입찰로 본다).
   */
  kind?: "bid" | "support" | "manual";
  /** 누르면 갈 곳(지원사업 신청 분석 · 직접 넣기 탭). 입찰은 null — 화면이 대시보드 주소를 만든다. */
  open_path?: string | null;
  /** 캐시에 있으면 공고명, 없으면 공고 id 를 그대로. 지어내지 않는다. */
  title: string;
  agency: string | null;
  /**
   * 이 공고가 아직 받아 둔 목록에 있는가.
   *
   * `false` 면 제목 자리에 공고 id 가 온다 — 화면은 그 이유를 반드시 적어야 한다.
   * 설명 없는 id 는 고장으로 읽힌다.
   */
  notice_known: boolean;
  /** 받아 둔 캐시에는 있다(관련 낮음이라 대시보드 목록에만 없을 수 있다 · 27차 검수 LNK-R1). 옛 응답에는 없다. */
  in_cache?: boolean;
  /** 목록에서 내려간 공고의 제안요청서 파일 이름. 없을 수도 있다. */
  document: string | null;
  deadline_at: string | null;
  days_left: number | null;
  last_activity_at: string | null;
  /** 「참여 결정」 · 「최종 검토」 · 「발견 항목 처리」 중 마지막 것. */
  last_activity_kind: string | null;
  recorded_by: string | null;
  decision_label: string | null;
  review_label: string | null;
  resolution_label: string | null;
  /** 이 공고에서 다음에 할 일 한 줄. 서버가 저장된 것만 보고 정한다. */
  next_step: string;
  /** 살아 있음 · 마감 지남 · 목록에서 내려감(43차 N4). 옛 응답에는 없다. */
  queue_state?: "live" | "closed" | "gone";
}

export interface ReviewQueue {
  as_of: string;
  /** 「내 것 먼저」의 기준이 된 계정. 인증이 꺼져 있으면 null. */
  mine: string | null;
  /** 갈래별 수(43차 N4). 옛 응답에는 없다. */
  counts?: { live: number; closed: number; gone: number };
  total: number;
  truncated: boolean;
  items: ReviewQueueItem[];
}
