export type RequirementType = "mandatory" | "optional";
export type RequirementStatus = "matched" | "partial" | "unmatched" | "check";
export type ExtractionMethod = "RULE" | "AI_EXTRACTION" | "HUMAN";

/**
 * 문서 항목 유형 (backend/app/services/item_classifier.py).
 * "무엇을 수행"(TASK) · "어떤 조건"(REQUIREMENT·ELIGIBILITY·SPECIAL_CONDITION) · "무엇을 언제 제출"(SUBMISSION·SCHEDULE)
 * · 평가기준 · 참고정보를 구분한다. 저장 id(REQ-nnn)는 유형과 무관하게 그대로다.
 */
export type ItemType =
  | "TASK"
  | "REQUIREMENT"
  | "ELIGIBILITY"
  | "SUBMISSION"
  | "SCHEDULE"
  | "EVALUATION"
  | "SPECIAL_CONDITION"
  | "REFERENCE";

export type Criticality = "blocker" | "high" | "normal" | "low";

/** 담당자 검토 상태. 시스템은 unreviewed만 만든다. */
export type ReviewStatus = "unreviewed" | "confirmed" | "corrected" | "rejected";

export interface Requirement {
  id: string;
  procurement_id: string;
  /** 저장·참조 키 (REQ-nnn). 유형이 바뀌어도 그대로다. */
  requirement_id: string;
  category: string;
  requirement_type: RequirementType;
  title: string;
  content: string;
  page: number | null;
  source_text: string;
  status: RequirementStatus;
  extraction_method: ExtractionMethod;
  /** 예전 파일(schema_version 1)은 읽을 때 backend가 채운다. */
  item_type?: ItemType;
  criticality?: Criticality;
  /** 자격·제출·일정·특이사항처럼 담당자의 행동이 필요한 항목 */
  action_required?: boolean;
  /** 본문에 날짜가 명시된 경우에만 (KST ISO). 추측하지 않는다. */
  due_at?: string | null;
  page_is_approximate?: boolean;
  review_status?: ReviewStatus;
  /** 화면용 코드 (TSK-003 등). 없으면 item_type + requirement_id로 만든다. */
  display_code?: string | null;
}

export interface PageInfo {
  page: number;
  char_count: number;
}

export interface RfpParseResult {
  procurement_id: string;
  /** synthetic_fixture | g2b_attachment 등 파싱 출처 */
  source: string;
  document: string;
  /** pdf | hwp | hwpx (합성 fixture는 null일 수 있다) */
  doc_format: string | null;
  /** HWP/HWPX는 페이지 정보가 없어 문단 묶음으로 근사한다 (docs/real_data_migration.md 4) */
  page_is_approximate: boolean;
  /** 요구사항을 뽑은 문서 — 제안요청서류(rfp)인가, 제안요청서가 없어 입찰공고문(notice)에서 뽑았나 (27차 §3-A-4) */
  document_role?: "rfp" | "notice";
  page_count: number;
  pages: PageInfo[];
  empty_pages: number[];
  count: number;
  /** 추출 상한 적용 전 후보 수. count보다 크면 문서 뒤쪽이 잘렸다는 뜻이다. */
  candidate_count: number | null;
  /** 상한에 잘렸는지. true면 count는 문서 전체 요구사항 수가 아니다. */
  truncated: boolean;
  requirements: Requirement[];
  generated_at: string;
  /** 저장 형식 버전 (1 = 항목 유형 이전, 2 = item_type 포함) */
  schema_version?: number;
  /** 유형별 건수 (탭 배지). backend가 계산한다. */
  item_counts?: Partial<Record<ItemType, number>>;
}
