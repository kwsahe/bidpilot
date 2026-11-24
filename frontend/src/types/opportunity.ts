import type { WorkKind, WorkTrack } from "@/types/capability";
import type { SemanticFitFields } from "@/types/procurement";

/**
 * 통합 사업기회 — 나라장터 입찰공고 + 기업마당 지원사업
 * (backend/app/schemas/business_opportunity.py).
 *
 * 두 출처는 업무 성격이 다르다:
 * - 나라장터 = 샘플에듀가 용역을 **수주**하는 입찰 → 입찰 분석 흐름
 * - 기업마당 = 샘플에듀가 지원금·바우처를 **신청**하는 사업 → 지원사업 신청 분석 흐름
 *
 * 원본 점수(추천등급 / 지원 적합도)는 source_specific_score 에 그대로 남고, 그 위에
 * 회사 기준 검토 우선순위(company_priority_score)만 얹는다. 확률이 아니다.
 */

/** 출처 셋 — 나라장터 · 기업마당 · 직접 넣음(사람이 넣은 공고 · 38차 §3-E). 순위는 출처 안에서만. */
export type SourceType = "g2b" | "bizinfo" | "manual";
/** 「pre_spec」 — 나라장터 사전규격(본공고 전 · 38차 §3-D). 39차부터 입찰 목록 밖 「선제준비」 칸(`prepare`)에만 온다 · 공고 분석 · 제안서 단추가 없다. */
export type OpportunityType = "procurement" | "support_program" | "pre_spec";
export type Confidence = "high" | "medium" | "low";
/**
 * 「미확인」은 «점수를 내지 못했다»이다 — 뒤로 보낸 「후순위」와 다른 뜻이다.
 * 회사 자료가 없거나 공고에 예산·지역이 없어 배점을 못 낸 항목이 여기 온다.
 */
export type PriorityLabel = "우선 검토" | "검토" | "후순위" | "미확인" | "마감";
export type EligibilityGate = "PASS" | "CHECK" | "FAIL";
/** 「pre_spec」 — 본공고가 아직 없는 사전규격(`path` 가 비어 있다 · 규격서는 `detail_url`). */
export type NextRouteKind = "procurement_analysis" | "support_application" | "pre_spec" | "manual";
/**
 * 서버 정렬 (37차 §3-C) — 실무 우선순위 · 회사 기준 검토 우선순위(점수) · 마감 여유 · 마감 임박 · 최신 등록 · 예산(레이더 「금액」).
 * 비워 보내면 회사 방식(`ranking_method`)의 기본 정렬이다.
 */
export type OpportunitySort = "practical" | "priority" | "slack" | "deadline" | "recent" | "value";

export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  g2b: "나라장터 입찰",
  bizinfo: "기업마당 지원사업",
  manual: "직접 넣은 공고",
};

export const OPPORTUNITY_TYPE_LABELS: Record<OpportunityType, string> = {
  procurement: "입찰공고",
  support_program: "지원사업",
  pre_spec: "사전규격(본공고 전)",
};

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  // 「점수 근거」는 바로 앞 「검토 우선순위 83」에 붙어 「83 점」으로 읽혔다(단위 없음 규칙 · UNI-14) — 「판단 근거」
  high: "판단 근거 충분",
  medium: "판단 근거 보통",
  low: "판단 근거 부족",
};

/** 검토 우선순위 구성 항목. score=null 은 **미확인**이며 0점이 아니다. */
export interface PriorityComponent {
  key: string;
  label: string;
  /** 배점 (합 100) */
  weight: number;
  score: number | null;
  reason: string;
}

/** 선택하면 어디로 가는가. 출처마다 분석 흐름이 다르다. */
export interface NextRoute {
  kind: NextRouteKind;
  path: string;
  label: string;
}

/**
 * `SemanticFitFields` 를 물려받는다 — 나라장터 항목의 사업영역 적합도를 의미 유사도로 잰
 * 경우 그 값을 실을 자리다. 통합 목록 응답은 아직 이 필드를 싣지 않으므로 지금은 항상
 * 비어 있고, 비어 있으면 화면은 그대로 키워드 규칙 결과를 보여 준다.
 */
export interface UnifiedOpportunity extends SemanticFitFields {
  id: string;
  source_type: SourceType;
  opportunity_type: OpportunityType;
  title: string;
  agency: string;
  summary: string | null;
  /** 조달=입찰 마감, 지원=신청 종료일 23:59(KST). 없으면 deadline_text 를 본다 */
  deadline: string | null;
  /** '상시 접수' 같은 원문 문구. 마감일이 없다고 0으로 취급하지 않는다 */
  deadline_text: string | null;
  /**
   * 접수 기간의 «성격». 기업마당만 값이 있고 나라장터는 null 이다.
   * 마감일이 없는 이유를 구분한다 — 상시·예산 소진 건을 「신청 종료」로 읽지 않기 위해 필요하다.
   * 예전 스냅샷 응답에는 이 필드가 없으므로 optional 이다.
   */
  apply_period_kind?: "dated" | "always_open" | "until_budget" | "conditional" | "unknown" | null;
  /** 나라장터 항목의 수주 적합도. 기업마당은 null */
  procurement_fit_score?: number | null;
  /** 기업마당 항목의 지원 적합도. 나라장터는 null */
  support_fit_score?: number | null;
  /** company_priority_score 와 같은 값 — 「검토 우선순위」라는 이름을 쓸 때 */
  review_priority_score?: number | null;
  /**
   * 같은 출처 «안에서의» 순위. 화면이 보여줄 순위는 이쪽이다.
   * priority_rank 는 두 출처가 섞인 통합 순위라 비교 근거가 아니다.
   * 옛 스냅샷에는 없으므로 기본 0.
   */
  source_rank?: number;
  /** 같은 출처 안의 전체 건수 (「3 / 100」처럼 적기 위해) */
  source_total?: number;
  detail_url: string | null;
  organization_id: string;
  /** 0~100. 낙찰·선정 확률이 아니다. 계산 가능한 항목이 없으면 null */
  company_priority_score: number | null;
  priority_rank: number;
  priority_label: PriorityLabel;
  /** 점수보다 먼저 보는 참여 가능성. FAIL은 높은 키워드 점수와 무관하게 후순위다. */
  eligibility_gate?: EligibilityGate;
  gate_reason?: string | null;
  confidence: Confidence;
  score_components: PriorityComponent[];
  /** 조달: {kind:"recommendation", grade, score} · 지원: {kind:"support_fit", label, score} */
  source_specific_score: Record<string, unknown>;
  next_route: NextRoute;
  /** 데이터 출처: g2b | cached | bizinfo | sample */
  source: string;
  /**
   * 이번 조회 결과에 없어 고정 공고 저장소에서 되살려 붙인 항목인가.
   * 옛 배포 스냅샷에는 이 필드가 없다.
   */
  pinned?: boolean;
  closed: boolean;
  reasons: string[];
  checks: string[];
  /** 조달=예산(원). 지원사업은 목록에 지원 규모가 없어 null — 0원으로 표시하지 않는다 */
  budget: number | null;
  /** 일의 종류(갈래). 나라장터 공고에만 있는 축 — 기업마당 항목은 빈 배열이다. */
  work_kinds?: WorkKind[];
  work_tracks?: WorkTrack[];
  work_basis?: string | null;
  /** 「왜 맞나」 한 줄 (0921 §4-C-3). 근거가 없으면 null — 빈 말을 만들지 않는다. */
  fit_line?: string | null;
  /** 「주의」 한 줄. 볼 것이 없으면 null. */
  caution_line?: string | null;
  /** 계약방법·낙찰방식·기술:가격·공동수급 한 줄. **판정이 아니라 정보다.** */
  award_line?: string | null;
  /** 기업마당 지역 태그(대표 이름). 「전남광주」처럼 통합 이름으로 접힌다. */
  region_tags?: string[];
  /** 기업마당 요약문의 「☞ …」 대상 요건 문장. **원문 그대로다.** */
  requirement_sentences?: string[];
  /** 자격 규칙 결과 (나라장터·기업마당 같은 모양). 「열리는 조건」이 여기 붙는다. */
  eligibility_rules?: EligibilityRule[] | null;
  /**
   * **무엇을 갖추면 열리는가** (0921 §4-B). 「소프트웨어사업자(1468) 등록 시 가능」 같은
   * 문장. 빈 목록은 「지금 판정에 열 수 있는 길이 없다」는 뜻이다.
   */
  unlock_conditions?: string[];
  /** 분석 상태 (0920 §4-B-3). 나라장터 공고만 채워진다. */
  analysis_state?: AnalysisState | null;
  /** 조달=지역, 지원=지원분야 대분류 */
  category: string | null;
  /**
   * **참가자격 등록 마감** (`bidQlfctRgstDt`, 0922 §4-B-8).
   *
   * 실제 데드라인은 입찰마감이 아니라 이쪽인 경우가 많다 — 한남대·KISTI 는 입찰 9-28 인데
   * 등록은 9-27 18:00 이다. 카드는 두 줄로 적고 D-day 는 **더 이른 쪽**을 쓴다.
   */
  qualification_deadline?: string | null;
  /** 공고문 일정표의 가장 이른 마감(참가신청 · 입찰등록 · 제출 · 필수 현장설명 · 43차 결정 1). 실제 마감은 세 마감 중 가장 이른 것. */
  schedule_deadline?: string | null;
  /** 그 마감의 이름 — 「참가신청 마감」 · 「입찰등록 마감」 · 「제출 마감」 · 「현장설명」. */
  schedule_deadline_label?: string | null;
  /** 그 마감의 시각을 공고문에서 읽었나(44차 M3). false 면 날짜만 — 화면은 「MM/DD(시각 원문 확인)」, 판정 · 순서는 그날 끝으로 센다. */
  schedule_deadline_time_known?: boolean | null;
  /** 개찰일시 — **마감이 아니다**(43차 H1). 입찰 마감이 비면 「마감 미상 — 개찰 MM/DD」로만 보인다. */
  opening_at?: string | null;
  /** 필수 현장설명(불참 시 참가 불가). 모르면 null. */
  briefing_required?: boolean | null;
  /** 변경공고 게시일 — `published_at` 은 원공고 게시일(43차 M2). */
  amended_at?: string | null;
  /**
   * 갈래 안에서의 순위 (0922 §4-B-7). `{"development": 3}`.
   *
   * 나라장터와 기업마당을 한 축에 섞어 하나의 1위를 만들지 않는다 — 순위는 같은 출처·같은
   * 갈래 안에서만 뜻이 있다.
   */
  track_ranks?: Record<string, number>;
  /**
   * 「관련 낮음」인 이유 (0922 §4-C-2). null 이면 관련 있는 사업이다.
   *
   * 기업마당 1,582건에는 식품·관광·융자처럼 회사와 상관없는 사업이 섞여 있다. **지우지
   * 않고** 기본으로 접는다 — 규칙이 틀렸을 때 담당자가 찾을 수 있어야 한다.
   */
  relevance_note?: string | null;
  /**
   * **회사가 맡을 자리가 신청 주체가 아닐 때의 표시** (0924 §4-A-4). 예 「간접(공급기업)」.
   *
   * 도입기업이 신청하고 공급기업이 수행하는 구조에서는 회사가 신청 주체가 아니다.
   * 그것을 「불가」로 닫으면 실제로 들어갈 수 있는 길이 화면에서 사라진다.
   * null 이면 직접 신청이다.
   */
  participation?: string | null;
  /** **「회사에 뜻하는 것」 한 줄** (0924 §4-A-6) — 역할 · 받는 것 · 부담 · 마감. */
  company_meaning?: string | null;
  /**
   * **「확인 필요」가 어느 쪽 때문인가** (0925 §4-E-4).
   *
   * `"company"` 는 회사가 아직 안 적은 값(매출·연구소·상시근로자 수) 때문이고,
   * `"notice"` 는 공고 원문을 더 봐야 하는 것이다. 앞쪽은 지금 당장 손댈 수 없어
   * 「이번 주 할 일」의 지원사업 자리에서 뺀다. 판정이 「확인 필요」가 아니면 null.
   */
  check_side?: "company" | "notice" | null;
  /**
   * 회사가 신청 주체가 아닐 수 있다는 안내 (ISSUE-125).
   *
   * 「이번 주 할 일」이 이것을 보고 뺀다 — 「원문에서 확인하세요」는 아침에 읽고 바로 할 수
   * 있는 일이 아니다. 목록에서는 지우지 않는다. 옛 스냅샷에는 없으므로 undefined 를 허용한다.
   */
  audience_note?: string | null;
  /** 공고문 원문을 읽고 판정했는가. 나라장터 공고는 null(해당 없음). */
  document_read?: boolean | null;
  /** 못 읽은 이유 (「공고문 이미지」·「아직 안 받음」). 읽었으면 null. */
  document_note?: string | null;
  /** 판정 근거로 쓴 **공고문 원문 인용**. 지어낸 문장이 아니다 (0924 §3-14). */
  clause_quotes?: string[];
  // --- 실무 우선순위 (37차 · 기획서 §4-1 1-1~1-4) — 옛 스냅샷에는 없다 ---
  /** 공고(등록)일 — 나라장터 bidNtceDt · 기업마당 creatPnttm. */
  published_at?: string | null;
  /** 접수방식 — 나라장터 bidMethdNm 그대로 · 기업마당은 신청방법 글로 가린 것(여럿이면 모두). */
  submission_methods?: string[];
  /** 기업마당 신청방법 원문 한 줄(접수방식은 글로 가린 것이라 원문을 함께 본다). */
  submission_text?: string | null;
  /** 모집 성격 — 「입찰(매출)」 · 「수행기관 모집(매출)」 · 「수혜(지원금)」. */
  recruit_kind?: string | null;
  /** 설명회 일시 — 날짜만 보이고 판정에는 쓰지 않는다. */
  briefing_at?: string | null;
  /** 공동수급협정 마감. */
  joint_agreement_deadline?: string | null;
  /** SAMPLEEDU 유형(근사) — A1 · A2 · B1 · B2 · C · D · 수혜. 점수에는 쓰지 않는다. */
  fit_type?: string | null;
  fit_type_basis?: string | null;
  /** 시간 등급 T1~T6. */
  time_tier?: string | null;
  /** 분류 칸 — 선제준비 · 신규+여유 · 직접도전 · 조건부 · 일반 접수 중 · 긴급 · 비추천 · 제외. */
  practical_group?: string | null;
  /** 실무 우선순위로 세운 자리(1부터 · 목록 전체). 같은 출처 안에서만 견준다. */
  practical_order?: number;
  /** 사전규격의 의견등록 마감 — **입찰 마감이 아니다**(D-day · 마감 임박순 · 긴급 칸에 들지 않는다 · 38차 §3-D). */
  opinion_deadline?: string | null;
  /** 본공고 행 — 「사전규격 n일 전 공개」(사전규격 저장본에 그 번호가 있을 때만). */
  pre_spec_note?: string | null;
  /** 사전규격 행 — 본공고가 나왔으면 그 공고 id(「본공고 나옴 →」). */
  main_notice_id?: string | null;
  /** 직접 넣은 공고의 출처 층(P1 · P2 · P3 · IRIS · HRD). */
  source_layer?: string | null;
  /** D8 「단독으로는 큼 · 파트너형」 — 점수는 그대로. */
  partner_scale?: boolean;
  /** 근거 줄 — 「근거: 공고문 p.N 「…」(QC-xx)」 · 읽지 않았으면 「공고문 아직 안 읽음」(38차 §3-C-2). */
  evidence_line?: string | null;
  /** 읽은 참가자격 조항 수(나라장터). */
  clause_count?: number;
  /** 최근 7일 안에 바뀐 것 — 「마감 · 첨부 · 차수 · 종류」(38차 §3-C-5). */
  changed_fields?: string[];
  /** 실무순 세 덩어리 — 「본업」 · 「연구 · 감리 · 구매」 · 「대형 · 파트너형 후보」(38차 D12). */
  practical_block?: string | null;
  /** 대형 꼬리표 — 브리핑 판단 낱말과 같은 값(서버 `practical_priority.partner_tag` · 38차 D14 · DOCS-01). 대형이 아니면 null. */
  partner_tag?: string | null;
  /** 44차 결정 4 — 등록 업종에 없는 업종 + 공동수급 허용(`allowed`) · 모름(`unknown`)이면 파트너형 덩어리(서버 `eligibility_engine.industry_partner`). */
  industry_partner?: "allowed" | "unknown" | null;
  /** 저장된 결정 한 줄 — 「참여 · 담당자 · 10/24」 · 「신청 안 함 · …」(44차 M4 · 서버 `practical_priority.decision_text`). 없으면 null. */
  decision_text?: string | null;
  /** 「규모 큼(단독 상한 n억)」 — 교육 · 컨설팅이 상한보다 크고 2배 이하라 본업에 남는 공고(서버 `practical_priority.scale_tag` · 39차 결정 2). */
  scale_tag?: string | null;
  /** 「주제 확인 — 공고명에 회사 사업 주제가 없음」(40차 결정 1 · 서버 `practical_priority.topic_of`) — 본업 칸 안에서 주제가 맞는 공고 뒤. */
  topic_note?: string | null;
  /** 「AI: 본업 아닐 수 있음 · <이유>」(40차 결정 2 · AI 판단 — 참고용) — 「주제 확인」과 같은 자리. 판정 · 점수에는 쓰지 않는다. */
  ai_fit_note?: string | null;
  /** 실제 마감 3일 이하 — 「원칙적으로 후순위」. */
  deadline_note?: string | null;
  /** 기업마당 — 사업 목적이 회사 갈래인가(`support_kinds.is_ours`). 나라장터는 null. */
  kind_fit?: boolean | null;
  /** 「같은 사업 n건 · 광주 · 전남 운영기관 먼저」(43차 Q9) — 같은 기업마당 사업이 여러 운영기관으로 온 묶음. */
  same_program_note?: string | null;
  /** 사전규격 행의 「본공고 예상 · 사업기간 · 할 일」(43차 Q16). */
  prespec_plan?: string | null;
  /** 나라장터 수요기관(43차 M6) — 광주 · 전남 판정 기준. 조달청 대행이면 기관 칸이 「수요기관(조달청 대행)」. */
  demand_agency?: string | null;
}

/**
 * 공고 하나의 분석 상태 (0920 §4-B-3 · ISSUE-076).
 *
 * 결정·검토·조건·발견 항목을 대시보드만 읽고 있어서, 사업기회 행은 요구사항 55건이 이미
 * 있는 공고에도 「입찰 분석 시작」이라고 적었고 레이더는 「참여 안 함」으로 정한 공고를
 * 한복판에 남겨 두었다. 백엔드가 한 벌 만들고 네 화면이 그대로 그린다.
 *
 * **모르는 것은 null 이다** — 0 으로 단정하지 않는다.
 */
export interface AnalysisState {
  /** 요구사항을 뽑아 둔 적이 있는가. */
  parsed: boolean;
  requirement_count: number | null;
  /** 「확인 필요」 — 기계가 정하지 못해 사람이 봐야 하는 항목 수. */
  check_count: number | null;
  /** 담당자가 확인·정정한 항목 수. 위와 **다른 값**이다. */
  confirmed_count: number | null;
  /** 저장된 참여 결정 (GO·HOLD·NO_GO·UNREVIEWED). 파일이 없으면 null. */
  decision: string | null;
  review: string | null;
  open_findings: number;
  /** 참가를 막는 조건 수. 탐지한 적이 없으면 null — 0 이 아니다. */
  blocking_conditions: number | null;
  last_activity_at: string | null;
}

/**
 * 자격 규칙 한 줄 (0921 §4-B).
 *
 * 나라장터(ELIG-*)와 기업마당(BIZ-*)이 **같은 모양**을 쓴다 — 화면이 두 출처를 한 벌의
 * 어휘로 그린다. `unlock_condition` 은 「무엇을 갖추면 열리는가」이고, 없으면 길이 없다.
 */
export interface EligibilityRule {
  rule_id: string;
  label: string;
  status: "PASS" | "CHECK" | "FAIL";
  method: string;
  source: string;
  reason: string;
  requirement_id?: string | null;
  unlock_condition?: string | null;
}

/** 건수의 단일 분모. 백엔드가 한 벌만 센다. */
export interface OpportunitySummary {
  /** 마감 전 전체. 화면의 「전체」는 이 값이다. */
  open_total: number;
  open_g2b: number;
  open_bizinfo: number;
  /** 직접 넣은 공고(38차 §3-E · 옛 응답에는 없음). */
  open_manual?: number;
  /** 「우선 검토」 건수. **전체 기준** — 레이더가 그린 12건 안에서 센 값이 아니다. */
  priority: number;
  /** 마감된 건수 (시연용 고정 포함). */
  closed: number;
  /** 그중 시연용으로 고정해 둔 것. 목록이 따로 묶는다. */
  closed_pinned: number;
  /** 이 목록이 본 조회 기간(일). 네 화면이 같은 값을 쓴다. */
  days: number;
  /** 참가·신청할 수 없다고 판정한 건수. **지운 것이 아니다** — 「불가 포함」으로 돌아온다. */
  blocked?: number;
  /**
   * 「새 공고」로 볼 기간(일). 백엔드가 정한다 (0920 §4-B-5 · ISSUE-078).
   *
   * 예전에는 목록 화면이 `NEW_WINDOW_DAYS = 3` 을 자기가 들고 있었고, 대시보드 띠는
   * 응답의 `new_days` 를 읽었다 — 같은 「새 공고」를 두 곳에서 따로 정하고 있었다.
   */
  new_days: number;
  /** 자료를 **마지막으로 받아온** 시각 (두 출처 중 오래된 쪽). 없으면 null. */
  fetched_at: string | null;
}

export interface UnifiedOpportunityListResponse {
  organization_id: string;
  organization_name: string;
  total_count: number;
  g2b_count: number;
  bizinfo_count: number;
  /** 직접 넣은 공고 수(38차 §3-E · 옛 응답에는 없음). */
  manual_count?: number;
  closed_count: number;
  /** 자격 판정이 「불가」인 건수. 기본 목록에서는 숨기고 「불가 포함」으로 되돌린다. */
  blocked_count?: number;
  /** 각 출처의 실제 데이터 상태 (g2b|cached / bizinfo|cached|sample) */
  source_status: Record<string, string | null>;
  /** 한쪽이 실패해도 다른 쪽은 살린다. 실패 사유 */
  source_errors: Record<string, string | null>;
  /** 시연 고정 모드인가 (두 출처 중 하나라도 고정이면 true). 옛 스냅샷에는 없다. */
  frozen?: boolean;
  /** 매일 아침 자동 받기의 마지막 성공(48시간 안일 때만 · 38차 §3-C-4). */
  auto_collect_at?: string | null;
  /** 자동 받기 한 줄(39차 §3-F-2 · 서버 `auto_collect.collect_state`) — 화면 다섯 곳이 이 값 하나로 고른다(`collectTerm`). */
  collect_state?: CollectState | null;
  /** 옛 `?refresh=…` 를 보냈고 서버가 무시했다 (N1). 다시 받아 오려면 POST `…/refresh`. */
  refresh_ignored?: boolean;
  fetched_at: string;
  /**
   * 건수의 **단일 분모** (0920 §4-B-2 · ISSUE-075).
   *
   * 같은 화면 안에서도 숫자가 갈려 있었다 — 머리는 「전체 107」, 바로 아래 탭은 「전체 (104)」.
   * 화면은 건수를 **다시 세지 않는다.** 이 값을 그대로 적는다.
   */
  summary: OpportunitySummary;
  /** 나라장터를 「어떻게 받았는가」 (0920 §4-A-3). 옛 캐시로 답하면 없을 수 있다. */
  collected_by?: string | null;
  /** 그 수집에서 나라장터를 부른 횟수. */
  collect_calls?: number | null;
  sort: OpportunitySort;
  /** 회사가 고른 순서 방식(37차) — 기본 정렬이 이것을 따른다. 옛 스냅샷에는 없다(점수순). */
  ranking_method?: "score" | "practical";
  ranking_method_label?: string;
  field_mapping_verified: boolean;
  note: string;
  /** 갈래별 건수. limit 자르기 **전** 기준이라 「상위 N건」에 흔들리지 않는다. */
  track_counts?: Partial<Record<WorkTrack, number>>;
  items: UnifiedOpportunity[];
  /** 「선제준비」 칸 — 사전규격 · 발주계획(39차 결정 1). 입찰 목록 밖이다. 브리핑 경로에서만 채운다(아니면 null). */
  prepare?: PrepareSection | null;
}

/**
 * 자동 받기 상태(39차 §3-F-2 · 40차 D30 「켤 때 받기」 · 서버 `auto_collect.collect_state`). none = 자동 받기 기록도 예약 작업도 없음(키트) ·
 * ok = 오늘 받음 · missed = 오늘 아직(경고) · running = 받는 중 · off = 예약 작업 꺼 둠 · 없음.
 * `suffix` = 「 · 일부 실패(…)」 · 「 · 기업마당 못 받음」 — 줄인 글에도 남긴다(COLLECT-01).
 */
export interface CollectState {
  kind: "none" | "ok" | "missed" | "running" | "off" | "waiting";
  text?: string | null;
  last_success?: string | null;
  suffix?: string | null;
  /** 경고색(44차 OPS-10 — 기업마당 3일 넘게 못 받음 등). 옛 응답에는 없다. */
  warn?: boolean;
}

/** 발주계획(발주 예정) 한 줄 — 기관이 미리 적은 계획. 점수 · 판정이 없다. */
export interface OrderPlanRow {
  title: string;
  agency: string;
  /** 발주 시기(「2026-12」). */
  when: string;
  amount?: number | null;
  method: string;
  /** 공식 상세 주소(g2b.go.kr 만). */
  url?: string | null;
  /** 본공고가 이미 났다(`ntceNticeYn=Y` · `bidNtceNoList`) — 「공고 전」이라 하지 않는다(PRESPEC-03). */
  main_out: boolean;
  /** 그 본공고가 지금 목록에 있으면 그 id. */
  main_notice_id?: string | null;
  /** 같은 사업의 사전규격이 이미 나왔다(43차) — 「사전규격 나옴 →」 위 칸에 있다. */
  prespec_out?: boolean;
  /** 발주 시기가 지났는데 본공고 · 사전규격이 안 났다(43차 Q17) — 「발주 지연」. */
  delayed?: boolean;
  /** 유형(근사) · 45차 M16 */
  fit_type?: string | null;
  /** 「주제 확인 — …」 또는 접은 사유 */
  note?: string | null;
}

/**
 * 사업기회 「선제준비」 칸(39차 결정 1). 한 사전규격은 한 곳에만 든다 —
 * 본공고 나옴(`merged` · 칸에서 뺌) → 본업 아님(`others` · 접음) → 의견 마감 지남(`opinion_passed` · 접음) → 보임(`items`).
 */
export interface PrepareSection {
  items: UnifiedOpportunity[];
  others: UnifiedOpportunity[];
  opinion_passed: UnifiedOpportunity[];
  merged: UnifiedOpportunity[];
  plans: OrderPlanRow[];
  /** 본업 덩어리 밖(유형 B2 · D) 발주계획 — 사유(note)와 함께 접는다(45차 M16) */
  plans_folded?: OrderPlanRow[];
  plans_low: number;
  /** 마지막 받기에서 발주계획이 크게 줄었으면 그 글(39차 §3-F-4 · 지난 자료는 합쳐 그대로 남는다). */
  plans_note?: string | null;
  fetched_at?: string | null;
  plans_fetched_at?: string | null;
  /** 접힌 묶음 건수(45차 M2 · part=main — 목록은 펼칠 때 part=folds 로) */
  others_count?: number | null;
  opinion_passed_count?: number | null;
  merged_count?: number | null;
  /** 나라장터 목록을 읽지 못한 사유(2.0.6 — 빈 칸이 「없음」으로 보이지 않게). 읽었으면 null · 옛 응답에는 없다. */
  source_error?: string | null;
}

export interface OpportunityQuery {
  organizationId?: string;
  source?: "all" | SourceType;
  days?: number;
  sort?: OpportunitySort;
  limit?: number;
  includeClosed?: boolean;
  includeLow?: boolean;
  /**
   * 참가·신청할 수 없다고 판정한 사업까지 받는다 (0921 §4-C-2).
   *
   * 기본은 false — 목록 1,712건 중 1,002건이 「불가」(대부분 다른 지역)라 그대로 두면
   * 담당자가 볼 수 없는 것을 매번 스크롤해 지나가게 된다. **지우는 것이 아니다.**
   */
  includeBlocked?: boolean;
  /** 레이더가 그리는 것만 — 나라장터 「관련 낮음」을 빼고 자른다(38차 §5 검토 · 사전규격은 39차부터 목록에 없다). */
  forRadar?: boolean;
  refresh?: boolean;
}

// ---------------------------------------------------------------------------
// 지원사업 신청 분석 (입찰 분석과 단계·용어가 다르다)
// ---------------------------------------------------------------------------

/** confirmed = 기업마당 원문에 있음 · unknown = 원문 상세 확인 필요 (지어내지 않는다) */
export type SupportItemStatus = "confirmed" | "unknown";

export interface SupportRequirementItem {
  key: string;
  label: string;
  value: string | null;
  status: SupportItemStatus;
  source_field: string | null;
  note: string | null;
}

export interface SupportEvidenceMatch {
  condition: string;
  evidence_id: string;
  document_name: string;
  page: number | null;
  source_text: string;
  similarity_score: number | null;
  selected: boolean;
  synthetic: boolean;
}

export interface SupportDraftSection {
  section: string;
  basis: string;
  grounded: boolean;
  note: string | null;
  /** 공고문 조항 **원문 그대로**. 요약하지 않는다. 옛 스냅샷에는 없다. */
  quotes?: string[];
  /** 그 절과 맞은 **회사 사실**. 미입력 값은 들어오지 않는다. 옛 스냅샷에는 없다. */
  company_facts?: string[];
}

/**
 * 사업계획서 초안 문장 (prompt_02 §4-B).
 *
 * `type` 은 입찰과 **같은 enum** 이다. 지원사업에서 `RFP_GROUNDED` 는 「공고문 근거」로
 * 읽는다 — 저장 값은 그대로 두고 **화면 라벨만** 그렇게 적는다(0921 §3-11).
 */
export type PlanSentenceType = "RFP_GROUNDED" | "COMPANY_EVIDENCE_GROUNDED" | "AI_SUGGESTION";

export interface PlanSentence {
  text: string;
  /**
   * 문장 유형. **`null` 이면 근거가 아니라 「확인 필요」 안내**다 (ISSUE-119 · prompt_03 §4-D-1).
   *
   * 예전에는 안내 문장에도 `RFP_GROUNDED` 를 달아, 「근거를 찾지 못했습니다」라는 말에
   * 화면이 「공고문 근거」 배지를 붙였다. 근거가 아니라 빈칸 표시다.
   */
  type: PlanSentenceType | null;
  /** 조항 원문 또는 근거 id. 없으면 「확인 필요」 문장이다. */
  source: string | null;
  /** 유형 없는 안내인가. 저장 파일이 `type: null` 과 함께 적는다. */
  note?: boolean;
  /** 25차 — 가리킨 근거 조각 id · 규칙 검증 표시(근거 확인 필요 · 금칙어 · 공고 문장 복사) · AI 가 쓴 문장인가 · 「공고 요구」 인용 줄인가 */
  source_ids?: string[];
  flags?: string[];
  ai?: boolean;
  notice_quote?: boolean;
}

/** 25차 양식 초안의 칸(일반 현황 · 기업 현황). 사람만 채우는 칸은 AI 가 채우지 않는다. */
export interface PlanField {
  label: string;
  value: string;
  human_only: boolean;
  source_ids?: string[];
  /** 문서 조립 때 회사자료로 채운 칸 (29차 §3-B) — 출처 「회사자료」. */
  filled_by?: "company";
  source?: string;
}

export interface PlanDraftSection {
  section: string;
  grounded: boolean;
  sentences: PlanSentence[];
  /** 아래는 25차 양식 초안에만 있다 — 없으면 예전 6절 초안이다. */
  key?: string;
  kind?: "item" | "fields";
  major_key?: string;
  major_title?: string;
  optional?: boolean;
  tables?: string[];
  eval_targets?: string[];
  fields?: PlanField[];
  llm_error?: string | null;
  by?: "llm" | "rules";
}

/** 양식 표 — 열은 양식 그대로 고정이다. */
export interface PlanTable {
  key: string;
  title: string;
  columns: string[];
  rows: string[][];
  human_only?: boolean;
  by?: "llm" | "rules" | "company";
  /** 회사자료로 채운 칸이 있는 표 (29차 §3-B). */
  filled_by?: string;
}

export interface PlanBlank {
  field: string;
  why: string;
  section?: string;
  /** (2.10.0) 채울 때 필요한 자료 — 증빙 서류 · 회사자료 칸 이름(입찰 제안서만 · 없으면 칸 없음) */
  proof?: string;
}

export interface PlanTask {
  no: number;
  agency: string | null;
  title: string;
  /** 회사 사업영역 · 역량과 겹친 낱말(규칙). 고르는 것은 사람이다. */
  match_words?: string[];
  /** 과제소개서 「협업 창업기업 기준요건 및 요구사항」 ▪ 줄 그대로(받아 둔 경우만 · 30차 §3-A). */
  annex_requirements?: string[];
}

/** 공고 양식 요약 (plan_form_service). */
export interface PlanFormView {
  source: "notice" | "standard";
  notice?: string | null;
  title?: string | null;
  tasks: PlanTask[];
  selected_task?: PlanTask | null;
}

/** 완성도 점검표 (plan_completeness) — 선정 가능성이 아니라 「무엇이 비었는가」다. */
export interface PlanChecklist {
  legacy?: boolean;
  summary: string;
  form?: { items_filled: number; items_total: number; empty_items: string[]; tables_present: number; tables_total: number; tables_filled: number };
  evaluation?: {
    covered: number;
    total: number;
    items: { name: string; sections: string[] }[];
    bonus: { name: string; points: number; applies: boolean | null; basis: string }[];
  };
  /** `company_sources` — 서로 다른 회사 근거 수(같은 한 줄을 절마다 되풀이해도 하나 · 27차 검수 D4). 옛 저장본에는 없다. */
  grounding?: { company: number; notice: number; suggestion: number; total: number; company_sources?: number };
  copy?: { count: number; ai_total: number; percent: number; tone: "pass" | "warn"; sentences: string[] };
  numbers?: {
    mismatches: number;
    schedule_out: number;
    examples_left: number;
    budget: { total_krw: number; cap_krw: number | null; over_cap: boolean; items_outside: string[]; total_mismatch?: boolean; blank_rows?: number } | null;
  };
  length?: {
    chars: number;
    recommended: number | null;
    percent: number | null;
    tone: "pass" | "warn" | null;
    /** 쉬운 문장(30차 §3-B) — 문장 평균 · 최장 글자 수 · 「·」 수 · 120자 넘는 문장 수. */
    sentence_avg?: number | null;
    sentence_max?: number | null;
    dots?: number;
    over_120?: number;
  };
  blanks?: { count: number; fields: string[]; task_pending: boolean };
  kind?: { label: string; generated_by: "llm" | "rules"; provider: string | null; model: string | null; failed_sections: number };
  /** 일반현황 자동 채움 셈 (29차 §3-B) — 화면 응답 · 내려받기에서만 붙는다. `fillable` = 회사자료에 입력하면 채워질 칸. */
  company_fill?: { filled: number; filled_fields: string[]; filled_table_cells: number; remaining: number; fillable: number; fillable_fields: string[] } | null;
}

export interface PlanDraft {
  program_id?: string;
  executed_at?: string;
  /** "rules" = AI 없이 만든 초안. "llm" = 다듬기까지 탄 초안. */
  generated_by?: "rules" | "llm";
  sections: PlanDraftSection[];
  sentence_count?: number;
  ai_sentence_count?: number;
  /** 크레딧이 확인됐는가. 거짓이면 단추 문구가 「AI 없이 규칙으로 초안 만들기」다. */
  credit_ok?: boolean;
  /** AI 초안을 쓰기로 했는가 (`LLM_LIVE` · 16차 ISSUE-130). 크레딧과 **다른 문**이다. */
  llm_live?: boolean;
  /** 25차 — 양식 초안 */
  tables?: PlanTable[];
  blanks?: PlanBlank[];
  /** 평가위원 검토가 짚었지만 고쳐 쓰지 못한 약점(호출 상한) — 담당자가 고칠 때 본다. */
  review_notes?: { section: string; items: string[] }[];
  /** 평가위원 채점(검토 메모 · 29차 §3-C) — 평가 항목별 상 · 중 · 하 · 이유 · 고칠 문장 · 「하」라서 고쳐 썼는가. 제출용 파일에는 없다. */
  review_scores?: { eval_item: string; grade: "상" | "중" | "하"; reason: string; sections: string[]; fixes: { section: string; sentence: string; fix: string }[]; rewritten: boolean }[];
  llm_note?: string | null;
  provider?: string | null;
  model?: string | null;
  llm_provider?: string;
  form?: PlanFormView;
  checklist?: PlanChecklist | null;
  /** 제출용 문서에 남는 「(담당자 입력)」 수 — 내려받기 단추 옆 「제출 전 채울 칸 n개」(30차 §3-B). */
  submit_blanks?: number | null;
  /** AI 초안을 규칙 초안으로 덮지 않고 유지했다(지금은 AI 꺼짐). */
  kept_llm_draft?: boolean;
  /** 옛 AI 초안을 유지했을 때 새 AI 초안이 없는 이유 — 「AI 꺼짐」 · 「과제 미선택」 · 「AI 작성 실패: …」(26차 ISSUE-148). */
  kept_reason?: string | null;
  /** 이 회사 · 공고의 초안을 서버가 지금 만드는 중인가 — 새로고침한 화면이 기다린다 (28차 §3-D). */
  in_progress?: boolean;
}

export interface SupportAttachment {
  name: string;
  /** 내려받기 주소(`fileDown.do`). 기업마당이 준 `getImageFile.do` 는 뷰어 HTML 이라 눌러도 파일이 안 온다. */
  url: string;
  /** 30차 §3-A — 이름으로 단 종류: 과제소개서 · 신청 매뉴얼 · 신청 서식 · 공고문. */
  kind: "form" | "notice" | "annex" | "manual";
  /** 신청 서식 칸 안의 순번(공고문 칸은 없음). */
  index?: number | null;
  /** 기업마당 원래 주소(뷰어). 「보기」 보조 링크. 옛 스냅샷에는 없다. */
  view_url?: string | null;
  /** 이름에서 읽은 확장자(hwpx · pdf · hwp). 옛 스냅샷에는 없다. */
  ext?: string | null;
}

export interface SupportProgramDetail {
  id: string;
  title: string;
  agency: string;
  executing_agency: string | null;
  summary: string | null;
  apply_start: string | null;
  apply_end: string | null;
  apply_period_text: string | null;
  apply_period_kind: "dated" | "always_open" | "until_budget" | "conditional" | "unknown";
  category: string | null;
  subcategory: string | null;
  hashtags: string[];
  target: string | null;
  url: string | null;
  created_at: string | null;
  updated_at: string | null;
  apply_method: string | null;
  contact: string | null;
  reception_url: string | null;
  attachments: SupportAttachment[];
}

/** 지원사업 신청 분석 결과. 입찰의 요구사항 매트릭스에 대응하지만 용어가 다르다. */
export interface SupportApplicationResult {
  /** 목록에서 빠진 사업을 남겨 둔 공고 정보로 보이는 중(33차). 옛 응답엔 없다. */
  archived?: boolean;
  /** 그 사본의 마감일이 지났다 — 이때만 새 초안을 서버가 막는다(34차 R33-A1). */
  archived_closed?: boolean;
  archived_note?: string | null;
  program_id: string;
  organization_id: string;
  evidence_scope: string;
  source: string;
  field_mapping_verified: boolean;
  generated_at: string;
  program: SupportProgramDetail;
  support_fit: import("@/types/support").SupportFit;
  company_priority_score: number | null;
  priority_label: PriorityLabel;
  /** (2.0.6) 목록 행과 같은 분류 칸(「긴급」 · 「일반 접수 중」 …). 목록 메모가 없거나 옛 응답이면 없음 · null */
  practical_group?: string | null;
  /** (2.0.6) 회사 순서 방식 — 실무순이면 「우선 검토」 대신 분류 칸을 보인다(레이더 상세와 같은 규칙). 옛 응답엔 없다 */
  ranking_method?: "score" | "practical";
  eligibility_gate?: EligibilityGate;
  gate_reason?: string | null;
  confidence: Confidence;
  score_components: PriorityComponent[];
  source_specific_score: Record<string, unknown>;
  reasons: string[];
  plan: {
    eligibility: SupportRequirementItem[];
    conditions: SupportRequirementItem[];
    schedule: SupportRequirementItem[];
    documents: SupportRequirementItem[];
  };
  unknown_count: number;
  confirmed_count: number;
  /** 공고문 원문을 읽고 판정했는가. 옛 스냅샷에는 없다 — 없으면 「못 읽음」으로 본다. */
  document_read?: boolean | null;
  /** 공고문을 못 읽은 사유 (백엔드가 이미 준다 — 쉬운 보기 출처 줄에 쓴다) */
  document_note?: string | null;
  /** 역할 · 받는 것 · 부담 · 마감 한 줄 — 목록 카드의 「회사에 뜻하는 것」과 같은 값 */
  company_meaning?: string | null;
  /** 간접 참여 자리 이름. 있으면 판정 자리에 「간접」 (lib/verdict) */
  participation?: string | null;
  /** 무엇을 갖추면 열리는가 — 백엔드 상세가 이미 준다(SUP-09). 옛 스냅샷에는 없다. */
  unlock_conditions?: string[];
  evidence_matches: SupportEvidenceMatch[];
  evidence_summary: import("@/types/organization").EvidenceScopeInfo | null;
  draft_outline: SupportDraftSection[];
  pre_submit_checks: string[];
  note: string;
}

/** 지원사업 신청 분석 단계. 입찰의 Mission Control 단계와 1:1 대응하지 않는다. */
export const SUPPORT_STEPS = [
  { key: "eligibility", label: "신청자격", hint: "지원 대상·기업 유형·지역" },
  { key: "conditions", label: "필수·우대조건", hint: "지원 분야·방식·규모·자부담" },
  { key: "schedule", label: "신청기간", hint: "접수 기간과 접수 방법" },
  { key: "documents", label: "제출서류", hint: "신청 서식·공고문·문의처" },
  { key: "evidence", label: "회사 적합 근거", hint: "승인된 회사자료 연결" },
  { key: "draft", label: "사업계획서", hint: "근거 기반 목차 초안" },
  { key: "check", label: "신청 전 점검", hint: "미확인 항목과 확인 사항" },
] as const;

export type SupportStepKey = (typeof SUPPORT_STEPS)[number]["key"];

/**
 * 나라장터 공고의 **추천등급 값**(A·B·C·D·NO_GO). 기업마당이면 null — 그 축이 없다.
 *
 * `source_specific_score` 는 출처마다 모양이 다른 원본 점수 주머니다(`Record<string, unknown>`).
 * 세 화면(목록 행·레이더 상세·RFP 머리)이 각자 풀어 읽으면 반드시 갈린다 — 그래서 여기 한 번만
 * 푼다 (0920 §4-B 완료 조건 · §3-12).
 */
export function gradeOf(item: Pick<UnifiedOpportunity, "source_specific_score">): string | null {
  const bag = item.source_specific_score;
  const read = (key: string): string | null => {
    const value = bag?.[key];
    return typeof value === "string" && value.trim() ? value : null;
  };
  if (read("kind") !== "recommendation") return null;
  return read("grade");
}

/**
 * 갭 리포트 — 「무엇을 갖추면 몇 건이 열리는가」 (0921 §4-B).
 *
 * `blocked` 와 `pending` 을 합치지 않는다. 「불가가 풀린다」와 「판정이 확정된다」는
 * 다른 사실이고, 확정 결과가 「가능」이라는 보장은 없다.
 */
export interface EligibilityGap {
  condition: string;
  rule_id: string;
  label: string;
  blocked: number;
  pending: number;
  blocked_examples: string[];
  pending_examples: string[];
}

export interface EligibilityGapReport {
  organization_id: string | null;
  days: number;
  evaluated_at: string;
  total: number;
  blocked_total: number;
  gaps: EligibilityGap[];
  /**
   * 「막는 0 · 확정 0」이라 목록에서 뺀 조건 수 (0923 §3-1 · ISSUE-091).
   *
   * 지금 아무것도 붙잡고 있지 않은 조건은 화면에 적지 않는다 — 「등록하면 뭔가 열린다」는
   * 잘못된 인상만 남는다. 그래도 **뺐다는 사실은 숨기지 않는다**.
   */
  empty_dropped?: number;
  /**
   * 사업자등록증 **종목** → 나라장터 **등록 업종** 「등록 후보」 힌트 (0922 §4-A-6).
   *
   * 종목이 있다고 업종이 자동으로 등록되는 것이 아니다. **판정이 아니라 힌트다** —
   * 「이 종목이 있으니 등록 신청이 가능해 보인다. 나라장터 등록증에서 확인하라」.
   */
  registration_hints?: IndustryRegistrationHint[];
  note: string;
}

export interface IndustryRegistrationHint {
  /** 사업자등록증에 적힌 종목 (담당자 확인값). */
  business_item: string;
  /** 대응하는 나라장터 업종코드 (예 "1468"). */
  code: string;
  /** 업종 이름 (예 "소프트웨어사업자(컴퓨터관련서비스사업)"). */
  name: string;
  /** 화면에 그대로 적는 한 줄. */
  hint: string;
}

/**
 * 저장해 둔 엑셀 한 줄 (0924 §4-C-2).
 *
 * 파일만 남기면 「어떤 조건으로 뽑은 표인가」를 나중에 알 수 없다. 날짜·조건·건수를 함께 적는다.
 */
export interface SavedExport {
  file: string;
  saved_at: string;
  conditions: string;
  rows: number;
  bytes: number;
  sheets: string[];
}

export interface SavedExportList {
  organization_id: string;
  count: number;
  files: SavedExport[];
  note: string;
}
