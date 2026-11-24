/**
 * 기업마당 지원사업 (backend/app/schemas/business_opportunity.py).
 * 조달공고(추천등급)와 지원사업(지원 적합도)은 다른 개념이다 — 점수를 섞지 않는다.
 */

export type SupportSource = "bizinfo" | "cached" | "sample";
export type SupportFitLabel = "적합" | "검토" | "낮음";

export interface SupportProgram {
  id: string;
  title: string;
  agency: string;
  executing_agency: string | null;
  summary: string | null;
  apply_start: string | null;
  /** 날짜만(YYYY-MM-DD) 온다. 시각 계산에는 lib/deadline.normalizeApplyEnd 를 거쳐라. */
  apply_end: string | null;
  /** 날짜로 못 읽은 접수 기간의 원문 — '상시 접수' 등 */
  apply_period_text?: string | null;
  /**
   * 접수 기간의 «성격». 백엔드는 예전부터 내려주는데 이 타입이 빠뜨리고 있었다.
   * 상시·예산 소진 건을 「신청 종료」로 읽지 않으려면 이 값이 필요하다.
   * 옛 스냅샷 응답에는 없을 수 있어 optional 이다.
   */
  apply_period_kind?: "dated" | "always_open" | "until_budget" | "conditional" | "unknown";
  category: string | null;
  subcategory: string | null;
  hashtags: string[];
  target: string | null;
  url: string | null;
  created_at: string | null;
  // 사업기회 카드 「접수 정보」(2.3.0) — 목록 응답이 예전부터 싣던 칸. 옛 스냅샷에는 없을 수 있어 선택이다.
  /** 요약문의 「☞ …」 대상 요건 문장(원문 그대로). */
  requirement_sentences?: string[];
  region_tags?: string[];
  /** 신청방법 · 제출서류 원문(`reqstMthPapersCn`). */
  apply_method?: string | null;
  /** 문의처 원문(`refrncNm`). */
  contact?: string | null;
  /** 접수처 홈페이지(`rceptEngnHmpgUrl`). */
  reception_url?: string | null;
  attachments?: { name: string; url: string; kind: string }[];
}

export interface SupportFitComponent {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  reason: string;
}

export interface SupportFit {
  label: SupportFitLabel;
  score: number;
  components: SupportFitComponent[];
  /** keyword_rule — 의미 매칭이 아니다 */
  method: string;
  note: string;
}

export interface SupportProgramView {
  kind: "support";
  program: SupportProgram;
  support_fit: SupportFit;
}

export interface SupportProgramListResponse {
  source: SupportSource;
  bizinfo_api_configured: boolean;
  fetched_at: string | null;
  total_fetched: number;
  count: number;
  error: string | null;
  /** 실응답 필드 매핑을 확인했는지 — false면 화면에 「매핑 미검증」을 붙인다 */
  field_mapping_verified: boolean;
  /** 시연 고정 모드인가 (`BIZINFO_LIVE_FETCH=0`). 옛 스냅샷에는 없다. */
  frozen?: boolean;
  /** 옛 `?refresh=…` 를 보냈고 서버가 무시했다 (N1). 다시 받아 오려면 POST `…/refresh`. */
  refresh_ignored?: boolean;
  items: SupportProgramView[];
}

export interface TemplateField {
  key: string;
  label: string;
  source: string;
  required: boolean;
}

export interface TemplateInfo {
  id: string;
  title: string;
  description: string;
  kind: string;
  status: string;
  fields: TemplateField[];
  file_name: string | null;
  note: string;
}

export interface TemplateListResponse {
  count: number;
  status: string;
  note: string;
  templates: TemplateInfo[];
}

export interface TemplateRenderResult {
  template_id: string;
  template_title: string;
  procurement_id: string;
  status: string;
  verified: boolean;
  file_name: string;
  download_path: string;
  size_bytes: number;
  sha256: string;
  rendered_at: string;
  values: Record<string, string>;
  validation: {
    zip_ok: boolean;
    required_members_ok: boolean;
    missing_members: string[];
    xml_ok: boolean;
    xml_errors: string[];
    mimetype_ok: boolean;
    section_count: number;
  };
  verification: {
    extracted_chars: number;
    fields_checked: number;
    fields_found: number;
    missing_fields: string[];
    unresolved_placeholders: string[];
  };
  note: string;
}
