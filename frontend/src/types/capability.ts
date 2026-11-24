/**
 * 개발 수행역량 판정 — `GET /api/capability/{procurement_id}` 응답.
 *
 * 판정값이 넷인 이유는 「모른다」와 「모자란다」를 섞지 않기 위해서다.
 * `unknown` 은 **회사가 못 한다는 뜻이 아니라** 판정할 근거가 아직 없다는 뜻이다.
 */

export type CapabilityStatus = "supported" | "gap" | "unknown" | "info";

export type WorkKind =
  | "development"
  | "education"
  | "consulting"
  | "supervision"
  | "research"
  | "procurement"
  | "construction";

export const WORK_KIND_LABELS: Record<WorkKind, string> = {
  development: "개발·구축",
  education: "교육·연수",
  consulting: "컨설팅·자문",
  supervision: "감리",
  research: "연구·조사",
  procurement: "구매·도입",
  construction: "공사·시설",
};

/**
 * 목록 화면에서 「따로 보는」 축. 일곱 갈래를 사람이 고를 수 있는 크기로 접은 것이다.
 * 새 분류가 아니라 WorkKind 의 순수 투영이며, 낱말 규칙은 backend work_kinds.py 한 곳에만 있다.
 */
export type WorkTrack = "education" | "development" | "other" | "unclassified";

export const WORK_TRACK_LABELS: Record<WorkTrack, string> = {
  education: "AI 교육·컨설팅",
  development: "AI 개발·구축",
  other: "그 밖 (감리·연구·구매·공사)",
  unclassified: "갈래 미분류",
};

/** 공고 하나의 갈래 판정 — GET /api/procurements 응답의 work 필드. */
export interface NoticeWork {
  kinds: WorkKind[];
  tracks: WorkTrack[];
  /** 무엇을 보고 판정했는지 — "공고명·요약". */
  basis: string;
  method: string;
}

export interface CapabilityEvidence {
  /** 공고 원문에서 그대로 따온 문장(또는 API 필드값). */
  notice_quote: string | null;
  /** 그 문장이 어디서 왔는가 — "과업지시서" · "공고 필드: 참가자격 등록 마감" 등. */
  notice_where: string | null;
  /** 회사자료에 적힌 사실. */
  company_fact: string | null;
  /** 그 사실의 출처. */
  company_where: string | null;
}

export interface CapabilityFinding {
  finding_id: string;
  label: string;
  status: CapabilityStatus;
  reason: string;
  evidence: CapabilityEvidence;
  next_action: string | null;
}

export interface CapabilityReport {
  procurement_id: string;
  organization_id: string;
  work_kinds: WorkKind[];
  is_development: boolean;
  findings: CapabilityFinding[];
  /** 회사 개발역량 자료가 등록돼 있는가. false 면 대부분 unknown 이 된다. */
  capacity_recorded: boolean;
  /** 공고 원문(파싱된 요구사항)까지 읽고 판정했는가. false 면 공고명·요약만 본 것이다. */
  used_requirements: boolean;
  counts: Partial<Record<CapabilityStatus, number>>;
  headline: string;
  evaluated_at: string | null;
  schema_version: number;
}

export interface DeliveryCapacitySkill {
  name: string;
  level: "proven" | "none";
  aliases: string[];
  note: string | null;
  source: string;
}

/** 중소기업(소상공인) 확인서에 적힌 기업 구분(10-10). */
export type SmeGrade = "중기업" | "소기업" | "소상공인";

export interface DeliveryCapacityCredential {
  name: string;
  held: boolean | null;
  note: string | null;
  source: string | null;
  /** 유효기간 끝나는 날 「YYYY-MM-DD」(31차 §3-B). 옛 응답에는 없다. */
  valid_until?: string | null;
  /** 「중소기업(소상공인) 확인서」 줄의 기업 구분 — 판정에 쓴다(10-10). 다른 줄은 비운다. 옛 응답에는 없다. */
  grade?: SmeGrade | null;
}

/** 사업기회 순서 방식(37차 · 담당자 결정 2026-10-14) — 점수는 어느 방식에서나 같고 순서 · 분류 칸만 다르다. */
export type RankingMethod = "score" | "practical";

/** 회사 단위 확인 한 칸(43차 결정 2) — 사람이 등록증 · 조회 결과를 보고 적는다. 프로그램은 값을 고르지 않는다. */
export interface CompanyCheck {
  confirmed_on: string;
  valid_until: string;
  confirmed_by: string;
  note?: string | null;
}

/** 회사 단위 확인 칸 이름 — 백엔드 `COMPANY_CHECK_LABELS` 와 같다. */
export const COMPANY_CHECK_LABELS: Record<string, string> = {
  g2b_registration: "나라장터 입찰참가자격 등록",
  no_sanction: "부정당 제재 없음",
  no_tax_arrears: "국세 · 지방세 체납 없음",
};

export interface DeliveryCapacity {
  organization_id: string;
  developer_count: number | null;
  team_note: string | null;
  skills: DeliveryCapacitySkill[];
  credentials: DeliveryCapacityCredential[];
  budget_ceiling_krw: number | null;
  concurrent_project_limit: number | null;
  // --- 입찰 자격 판정 v2 (0921 §4-B) ---
  /** 나라장터 **등록 업종**. 빈 목록은 「미입력」이지 「등록한 업종이 없다」가 아니다. */
  registered_industries: { code: string; name: string }[];
  /** 사업자등록증 **종목**. 판정에 쓰지 않는다 — 「등록 후보」 힌트다. */
  business_items: string[];
  /** 회사 **소재 광역**(예 「전남광주」). 활동 지역과 다른 축이다. */
  location_region: string | null;
  /** 공동수급 파트너. null 이면 확인되지 않은 것이다. */
  joint_bid_partner: { available: boolean; note: string | null } | null;
  /** 제안서를 쓰는 데 필요한 최소 일수. 마감이 이보다 가까우면 「촉박」이다. */
  proposal_lead_days: number;
  /** 사업기회 순서 방식(37차) — score 점수순(기본) · practical 실무 우선순위. 옛 응답에는 없다(점수순으로 본다). */
  ranking_method?: RankingMethod;
  // --- 기업마당 공고문 판정 v2 (0924 §4-A-5) ---
  /** 지난해 매출(원). 「매출 10억 이상」 요건을 이것으로 잰다. null 이면 미입력. */
  revenue_krw_last_year: number | null;
  /** 기업부설연구소·연구개발전담부서 보유 여부. null 이면 확인되지 않았다. */
  has_research_department: boolean | null;
  /** 둔 것이 무엇인가 — lab 기업부설연구소 · dept_only 연구개발전담부서만 · null 종류 모름(옛 「보유」 · 36차 R35-DV-02). 옛 응답에는 없다. */
  research_department_kind?: "lab" | "dept_only" | null;
  /** 인증·평가 대상이 되는 데이터 상품. */
  data_products: string[];
  /** 등록해 둔 공급기업 풀(스마트공장 공급기업 등). */
  supplier_registrations: string[];
  /** 완료한 선행 사업. 「없음 확인」은 «모른다»가 아니라 «확인했고 없다»다. */
  completed_programs: string[];
  /** 「안 적음(그대로 둠)」으로 고른 빈칸 열쇠(41차 D31). 옛 응답에는 없다. */
  left_blank?: string[];
  /** 회사 단위 한 번 확인(43차 결정 2) — 열쇠 g2b_registration · no_sanction · no_tax_arrears. 옛 응답에는 없다. */
  company_checks?: Record<string, CompanyCheck>;
  /** 직접생산 보유 품명(43차 Q24). 옛 응답에는 없다. */
  direct_production_items?: string[];
  /** 보유 디지털 제품(서비스)(43차 Q14). 옛 응답에는 없다. */
  digital_products?: string[];
  /** "absent" 면 회사자료가 아직 등록되지 않은 것이다. */
  source: "file" | "absent";
  updated_at: string | null;
  updated_by: string | null;
  note: string | null;
  schema_version: number;
}

/** 역량 자료 저장 요청 (0921 §4-B). 화면이 보내는 키가 백엔드 모델과 같아야 버려지지 않는다. */
export interface DeliveryCapacityUpdate {
  developer_count: number | null;
  team_note: string | null;
  skills: DeliveryCapacitySkill[];
  credentials: DeliveryCapacityCredential[];
  budget_ceiling_krw: number | null;
  concurrent_project_limit: number | null;
  registered_industries: { code: string; name: string }[];
  business_items: string[];
  location_region: string | null;
  joint_bid_partner: { available: boolean; note: string | null } | null;
  proposal_lead_days: number;
  /** 비워 보내면 서버가 저장된 값을 그대로 둔다(37차). */
  ranking_method?: RankingMethod | null;
  // --- 기업마당 공고문 판정 v2 (0924 §4-A-5) ---
  /** 지난해 매출(원). 「매출 10억 이상」 요건을 이것으로 잰다. null 이면 미입력. */
  revenue_krw_last_year: number | null;
  /** 기업부설연구소·연구개발전담부서 보유 여부. null 이면 확인되지 않았다. */
  has_research_department: boolean | null;
  /** 둔 것이 무엇인가 — lab 기업부설연구소 · dept_only 연구개발전담부서만 · null 종류 모름(옛 「보유」 · 36차 R35-DV-02). 옛 응답에는 없다. */
  research_department_kind?: "lab" | "dept_only" | null;
  /** 인증·평가 대상이 되는 데이터 상품. */
  data_products: string[];
  /** 등록해 둔 공급기업 풀(스마트공장 공급기업 등). */
  supplier_registrations: string[];
  /** 완료한 선행 사업. 「없음 확인」은 «모른다»가 아니라 «확인했고 없다»다. */
  completed_programs: string[];
  /** 직접생산 보유 품명 · 보유 디지털 제품(43차). 비워 보내면(생략) 서버가 저장된 값을 그대로 둔다. */
  direct_production_items?: string[];
  digital_products?: string[];
  updated_by: string;
  note: string | null;
  /** 폼을 연 때 읽은 `updated_at`(43차 M25) — 그사이 다른 사람이 저장했으면 서버가 409 로 막는다. null = 처음 저장. */
  expected_updated_at?: string | null;
}
