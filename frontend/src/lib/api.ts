import type {
  HealthResponse,
  ProcurementListResponse,
} from "@/types/procurement";
import { requestConsent, type ConsentRequest } from "./consentPrompt.ts";
import type { CapabilityReport, DeliveryCapacity, DeliveryCapacityUpdate } from "@/types/capability";
import type { DemoCosmosScenario } from "@/types/cosmos";
import type {
  AuditReadiness,
  AuditRunResult,
  ChangeImpact,
  ClauseReviewRequest,
  EligibilityReport,
  FindingResolution,
  FindingResolutionList,
  FindingResolutionRequest,
  GeneratedProposalSection,
  ProposalDocumentView,
  ReviewDecision,
  ReviewDecisionRequest,
} from "@/types/analysis";
import type { Requirement, RfpParseResult } from "@/types/rfp";
import type { RecollectResult, RecollectSource } from "@/lib/recollect";
import type { CollectKeywordsResponse, CollectKeywordsState } from "@/types/collectKeywords";
import type { NoticeQaAnswer, NoticeQaState } from "@/lib/noticeQa";
import type {
  ActionChecklist,
  ActionCreateRequest,
  ActionItem,
  ActionUpdateRequest,
  BidDecision,
  ConditionUpdateRequest,
  CriticalConditionReport,
  DecisionRequest,
} from "@/types/gate";
import type {
  CandidateReviewRequest,
  CompanyDocument,
  CompanyDocumentDetail,
  DocumentApproveRequest,
  DocumentListResponse,
  IndexStatus,
  ReindexResult,
  UsageResponse,
} from "@/types/company";
import type {
  AnalysisContextParams,
  IndexSearchResult,
  LedgerImportProfile,
  LedgerImportResult,
  LedgerInspectResult,
  LedgerPreviewRequest,
  LedgerPreviewResult,
  LedgerSummary,
  Organization,
  OrganizationCreateRequest,
  OrganizationListResponse,
  OrganizationProfile,
  OrganizationProfileUpdate,
  OrganizationSummary,
  PlanGeneralInfo,
  PlanGeneralUpdate,
} from "@/types/organization";
import type { TodayDigest } from "@/types/digest";
import type {
  InboxEntry,
  InboxPasteResult,
  ManualNotice,
  ManualNoticeInput,
  ManualSaveResult,
  WatchSite,
  WatchSiteInput,
} from "@/types/manual";
import type { ReviewQueue } from "@/types/reviewQueue";
import type { SupportProgramListResponse, TemplateListResponse, TemplateRenderResult } from "@/types/support";
import type {
  OpportunityQuery,
  PlanDraft,
  PrepareSection,
  SupportApplicationResult,
  EligibilityGapReport,
  SavedExportList,
  UnifiedOpportunityListResponse,
} from "@/types/opportunity";

// 데모 모드(Vercel 배포본)에서는 백엔드가 없다. 이 앱의 라우트 핸들러가
// 저장해 둔 응답을 돌려주므로 상대경로로 부른다. 그 밖에는 로컬 백엔드를 쓴다.
const BACKEND_URL =
  process.env.NEXT_PUBLIC_DEMO_MODE === "1"
    ? ""
    : process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8110";

export class ApiError extends Error {
  readonly status: number;
  /** FastAPI HTTPException 의 detail — 문자열일 때만 */
  readonly detail: string | null;
  /**
   * detail 이 객체(`{code, message, …}`)일 때 그 message. `detail` 과 따로 둔다 — 「detail 이 비었으면 객체 사유」로
   * 가르는 화면이 있다(대시보드 점검 409 · DTL-12). 사용자 문장은 `describeFailure` 가 이것까지 본다 (CMN-11).
   */
  readonly serverMessage: string | null;
  /** detail 이 객체일 때 그 code(예: `stale_write` — 43차 M25). */
  readonly code: string | null;

  constructor(status: number, message: string, detail: string | null = null, serverMessage: string | null = null, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.serverMessage = serverMessage;
    this.code = code;
  }
}

/**
 * 세션이 끝났다는 알림(43차 M28) — `SessionHost` 가 받아 「세션이 끝났습니다 — 새 탭에서 다시 로그인」 띠를 띄운다.
 * 쓰던 폼은 그대로 둔다(로그인 화면으로 보내면 붙여 넣은 글이 사라졌다).
 */
export const SESSION_EXPIRED_EVENT = "bidpilot:session-expired";

/** 처음 읽은 뒤 다른 사람이 먼저 저장했다(43차 M25 · 서버 409 `code: stale_write`). */
export function isStaleWrite(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === "stale_write";
}

/** 오류 응답을 ApiError 로. 본문의 FastAPI detail(문자열 · 객체의 message)을 담는다. */
async function apiError(response: Response, message: string): Promise<ApiError> {
  let detail: string | null = null;
  let serverMessage: string | null = null;
  let code: string | null = null;
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const raw = (body as { detail: unknown }).detail;
      if (typeof raw === "string") detail = raw;
      else if (typeof raw === "object" && raw !== null && typeof (raw as { message?: unknown }).message === "string") {
        serverMessage = (raw as { message: string }).message;
        const rawCode = (raw as { code?: unknown }).code;
        if (typeof rawCode === "string") code = rawCode;
      }
    }
  } catch {
    // JSON이 아니거나 본문이 없으면 무시한다.
  }
  // 45차 L9 — 서버 문장을 띠에 넘긴다(계정이 꺼진 401 은 「다시 로그인」이 아니라 「관리자에게」)
  if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail }));
  return new ApiError(response.status, message, detail, serverMessage, code);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, init);

  if (!response.ok) {
    throw await apiError(response, `Backend request failed (${response.status})`);
  }

  return (await response.json()) as T;
}

function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function putJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function patchJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function deleteRequest(path: string): Promise<void> {
  const response = await fetch(`${BACKEND_URL}${path}`, { method: "DELETE" });
  if (!response.ok) {
    throw await apiError(response, `Backend request failed (${response.status})`);
  }
}

const enc = (value: string) => encodeURIComponent(value);

/**
 * 분석 컨텍스트(회사·근거 범위) → 쿼리스트링. 없으면 backend 호환 계층이 기본 조직·범위를 채운다.
 * 새 호출은 항상 컨텍스트를 넘긴다 — 하나의 분석은 하나의 회사에 고정된다.
 */
function ctxQuery(ctx?: AnalysisContextParams | null, extra?: Record<string, string>): string {
  const params = new URLSearchParams(extra ?? {});
  if (ctx) {
    params.set("organization_id", ctx.organization_id);
    params.set("evidence_scope", ctx.evidence_scope);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function ctxBody(ctx?: AnalysisContextParams | null): Record<string, string> {
  return ctx ? { organization_id: ctx.organization_id, evidence_scope: ctx.evidence_scope } : {};
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health");
}

export interface ProcurementQuery {
  /** 공고게시일 기준 조회 기간(일). backend 기본값 14 */
  days?: number;
  /** 업무 키워드만 맞는 low 등급까지 포함할지 */
  includeLow?: boolean;
}

export function getProcurements(
  query: ProcurementQuery = {},
): Promise<ProcurementListResponse> {
  const params = new URLSearchParams();
  if (query.days !== undefined) params.set("days", String(query.days));
  if (query.includeLow !== undefined) {
    params.set("include_low", String(query.includeLow));
  }
  const queryString = params.toString();
  const suffix = queryString ? `?${queryString}` : "";
  return getJson<ProcurementListResponse>(`/api/procurements${suffix}`);
}

export function getRfpRequirements(
  procurementId: string,
): Promise<RfpParseResult> {
  return getJson<RfpParseResult>(
    `/api/rfp/${encodeURIComponent(procurementId)}/requirements`,
  );
}

export function parseRfp(procurementId: string, options: { fetchAttachment?: boolean } = {}): Promise<RfpParseResult> {
  return postJson<RfpParseResult>("/api/rfp/parse", {
    procurement_id: procurementId,
    ...(options.fetchAttachment ? { fetch_attachment: true } : {}),
  });
}

export interface NoticeAttachment {
  index: number;
  name: string;
  url: string;
  is_rfp: boolean;
  downloadable: boolean;
  /** 로컬에 이미 받아 둔 첨부인가 */
  cached: boolean;
  /** 받아 둔 파일 크기(바이트). 아직 안 받았으면 null — 나라장터가 크기를 미리 알려 주지 않는다. */
  size_bytes: number | null;
  /** 제안요청서류(rfp)인가 입찰공고문(notice)인가 — 압축 파일은 안을 열어야 알아 null */
  document_role?: "rfp" | "notice" | null;
}

export interface NoticeAttachmentList {
  notice_id: string;
  notice_title: string;
  count: number;
  rfp_index: number | null;
  rfp_cached: boolean;
  notice_index: number | null;
  notice_cached: boolean;
  attachments: NoticeAttachment[];
}

export function getNoticeAttachments(noticeId: string): Promise<NoticeAttachmentList> {
  return getJson<NoticeAttachmentList>(`/api/procurements/${encodeURIComponent(noticeId)}/attachments`);
}

/** 받는 중인가 · 뽑는 중인가 — 화면 문구는 `RFP_PARSE_PHASE_LABEL` 하나로. */
export type RfpParsePhase = "fetching" | "parsing";
export const RFP_PARSE_PHASE_LABEL: Record<RfpParsePhase, string> = {
  // 받기와 뽑기는 서버 요청 하나다 — 받는 동안의 이름이 끝까지 간다(받으면 곧바로 뽑는다). 받는 문서가 제안요청서인지
  // 공고문인지는 확인 창이 이름으로 말했다 — 여기서는 「첨부」라고만 한다(27차 검수 C17).
  fetching: "첨부 받는 중…",
  parsing: "요구사항 뽑는 중…",
};

/** 「공고 분석」 동의 — 곧바로 뽑아도 되면 direct · 사람이 받기를 확인했으면 fetch · 취소면 null. */
export type RfpConsent = "direct" | "fetch";

function formatMegabytes(bytes: number | null): string {
  if (bytes === null || bytes <= 0) return "";
  return ` · ${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * 「공고 분석」 한 곳 — /rfp `runParse` 와 대시보드 `runAnalysis` 가 같이 쓴다 (27차 §3-A-3).
 *
 * 로컬에 제안요청서(없으면 입찰공고문)가 있으면 곧바로 뽑는다. 없으면 **사람이 파일 이름을 보고**
 * 확인해야 그 한 건을 받는다 — 확인하지 않으면 서버 요청이 하나도 나가지 않고 `null` 이다.
 * 첨부 목록을 못 읽거나 고를 첨부가 없으면 서버에 그대로 맡겨 실제 사유(422 · 409 등)를 받는다.
 */
export async function askRfpConsent(
  procurementId: string,
  // 화면 안 확인 창(Modal) — 브라우저 기본 창을 쓰지 않는다(28차 §A-6). 검사는 글을 받는 함수를 넘긴다.
  confirmFn: (message: string, request: ConsentRequest) => boolean | Promise<boolean> = (_message, request) => requestConsent(request),
): Promise<RfpConsent | null> {
  if (!procurementId.startsWith("g2b-")) return "direct";
  let list: NoticeAttachmentList;
  try {
    list = await getNoticeAttachments(procurementId);
  } catch {
    return "direct"; // 목록을 못 읽으면 서버에 맡겨 실제 사유를 받는다(받지는 않는다)
  }
  const targetIndex = list.rfp_index ?? list.notice_index;
  const target = list.attachments.find((file) => file.index === targetIndex);
  if (!target || target.cached || !target.downloadable) return "direct";
  // 받을 문서를 제 이름으로 — 「입찰공고」는 제안요청서 자리(3순위)로 골라져도 문서는 공고문이다(검수 C17 · C27).
  const role = target.document_role ?? (list.rfp_index === null ? "notice" : undefined);
  const what =
    role === "notice"
      ? "제안요청서가 첨부에 없어 입찰공고문 1개를"
      : role === "rfp"
        ? "이 공고의 제안요청서 1개를"
        : "이 공고의 첨부 1개(압축 파일 — 안에서 제안요청서를 먼저 엽니다)를";
  const ok = await confirmFn(
    `나라장터에서 ${what} 내려받아 분석합니다 — 「${target.name}」${formatMegabytes(target.size_bytes)}.
공고 목록과 점수는 바뀌지 않습니다.

받고 분석할까요?`,
    {
      title: "제안요청서를 받아 분석할까요?",
      body: `나라장터에서 ${what} 내려받아 요구사항을 뽑습니다. 인터넷이 필요하고, 공고 목록과 점수는 바뀌지 않습니다.`,
      fileName: target.name,
      size: formatMegabytes(target.size_bytes),
      confirmLabel: "받고 분석",
      cancelLabel: "취소",
    },
  );
  return ok ? "fetch" : null;
}

export async function parseRfpWithConsent(
  procurementId: string,
  options: { confirm?: (message: string, request: ConsentRequest) => boolean | Promise<boolean>; onPhase?: (phase: RfpParsePhase) => void } = {},
): Promise<RfpParseResult | null> {
  const consent = await askRfpConsent(procurementId, options.confirm);
  if (consent === null) return null;
  options.onPhase?.(consent === "fetch" ? "fetching" : "parsing");
  return parseRfp(procurementId, { fetchAttachment: consent === "fetch" });
}

/**
 * 시연용 합성 Evidence/Proposal/Auditor 시나리오 (source=demo_synthetic).
 * 실제 Evidence Mapping·Proposal·Auditor API가 생기면 이 함수만 교체한다.
 */
export function getDemoCosmosScenario(
  procurementId: string,
): Promise<DemoCosmosScenario> {
  return getJson<DemoCosmosScenario>(
    `/api/demo/cosmos/${encodeURIComponent(procurementId)}`,
  );
}

// ---------------------------------------------------------------------------
// Eligibility Gate (실판정) — backend/app/api/eligibility.py
// ---------------------------------------------------------------------------

/**
 * 사업기회 「재수집」 (20차 §4-G). 시연 고정 모드 · 이미 받는 중 · 축소 차단이면 409 와 사유(그대로 보인다).
 */
export function recollectOpportunities(source: RecollectSource): Promise<RecollectResult> {
  return postJson<RecollectResult>("/api/business-opportunities/recollect", { source });
}

/** 「찾는 낱말」(2.0.7) — 기본 낱말 · 추가 낱말 · 오늘 바로 찾기 횟수 · 이 서버의 바로 찾기 문. 읽기만(바깥 호출 없음). */
export function getCollectKeywords(): Promise<CollectKeywordsState> {
  return getJson<CollectKeywordsState>("/api/collect-keywords");
}

/**
 * 추가 낱말을 더하고(저장이 먼저) `search` 면 그 낱말 하나만 바로 찾는다. 규칙에 어긋나면 400 · 10개가 차면 400 · 그사이 남이 바꿨으면 409.
 * 문 꺼짐 · 하루 횟수 · 아침 받기 중 · 받기 실패는 200 + `search_error`(저장은 됐다).
 */
export function addCollectKeyword(word: string, search: boolean, expectedUpdatedAt: string | null): Promise<CollectKeywordsResponse> {
  return postJson<CollectKeywordsResponse>("/api/collect-keywords", { word, search, expected_updated_at: expectedUpdatedAt });
}

/** 이미 더한 추가 낱말을 다시 바로 찾는다 — 응답 꼴은 더하기와 같다. */
export function searchCollectKeyword(word: string): Promise<CollectKeywordsResponse> {
  return postJson<CollectKeywordsResponse>("/api/collect-keywords/search", { word });
}

export function removeCollectKeyword(word: string, expectedUpdatedAt: string | null): Promise<{ state: CollectKeywordsState }> {
  return postJson<{ state: CollectKeywordsState }>("/api/collect-keywords/remove", { word, expected_updated_at: expectedUpdatedAt });
}

/**
 * 저장된(없으면 새로 잰) 참가자격 판정을 **읽기로** 받는다(43차 M26). 열람자는 판정 요청(POST)이 막혀
 * 대시보드가 「아직 판정 전입니다」를 보였다 — 같은 판정을 GET 으로 읽는다.
 */
export function getEligibilityReport(procurementId: string, ctx?: AnalysisContextParams | null): Promise<EligibilityReport> {
  return getJson<EligibilityReport>(`/api/eligibility/${enc(procurementId)}${ctxQuery(ctx)}`);
}

/**
 * 참가자격 조항 하나를 담당자가 확인한다 (20차 §4-C). 응답은 그 확인을 합친 판정 전체다.
 * 충족·미충족은 근거 메모가 없으면 422, 이 공고에 없는 조항 id 는 404.
 */
export function saveClauseReview(
  procurementId: string,
  clauseId: string,
  body: ClauseReviewRequest,
  ctx?: AnalysisContextParams | null,
): Promise<EligibilityReport> {
  return putJson<EligibilityReport>(
    `/api/eligibility/${enc(procurementId)}/review/${enc(clauseId)}${ctxQuery(ctx)}`,
    body,
  );
}

/** 공고 필드 + 파싱된 RFP 자격 조항으로 PASS/CHECK/FAIL을 판정한다. 지역 규칙은 선택한 회사의 활동 지역을 쓴다. */
export function evaluateEligibility(
  procurementId: string,
  options: { useLlm?: boolean } = {},
  ctx?: AnalysisContextParams | null,
): Promise<EligibilityReport> {
  return postJson<EligibilityReport>("/api/eligibility/evaluate", {
    procurement_id: procurementId,
    use_llm: options.useLlm ?? false,
    ...ctxBody(ctx),
  });
}

// ---------------------------------------------------------------------------
// Proposal (실생성) — backend/app/api/proposal.py
// ---------------------------------------------------------------------------

/** 이미 생성·저장된 섹션을 읽는다. 아직 없으면 404. */
export function getProposal(procurementId: string, ctx?: AnalysisContextParams | null): Promise<GeneratedProposalSection> {
  return getJson<GeneratedProposalSection>(`/api/proposal/${enc(procurementId)}${ctxQuery(ctx)}`);
}

/** 요구사항 + 채택 Evidence로 핵심 섹션 1개를 새로 생성한다 (선택한 회사의 승인 근거만). */
export function generateProposal(
  procurementId: string,
  ctx?: AnalysisContextParams | null,
): Promise<GeneratedProposalSection> {
  return postJson<GeneratedProposalSection>("/api/proposal/generate", {
    procurement_id: procurementId,
    ...ctxBody(ctx),
  });
}

// ---------------------------------------------------------------------------
// AI Auditor (실검사) — backend/app/api/auditor.py
// ---------------------------------------------------------------------------

/** 붙여넣은 초안 텍스트를 RFP 원문과 역대조한다. */
export function runAuditor(
  procurementId: string,
  proposalText: string,
  options: { useLlm?: boolean } = {},
  ctx?: AnalysisContextParams | null,
): Promise<AuditRunResult> {
  return postJson<AuditRunResult>("/api/auditor/run", {
    procurement_id: procurementId,
    proposal_text: proposalText,
    use_llm: options.useLlm ?? false,
    ...ctxBody(ctx),
  });
}

/** 제안서 파일(DOCX/PDF/HWP/HWPX/TXT/MD)을 올려 검사한다. */
export function runAuditorUpload(
  procurementId: string,
  file: File,
  options: { useLlm?: boolean } = {},
  ctx?: AnalysisContextParams | null,
): Promise<AuditRunResult> {
  const form = new FormData();
  form.append("procurement_id", procurementId);
  form.append("file", file);
  form.append("use_llm", String(options.useLlm ?? false));
  if (ctx) {
    form.append("organization_id", ctx.organization_id);
    form.append("evidence_scope", ctx.evidence_scope);
  }
  return request<AuditRunResult>("/api/auditor/run/upload", {
    method: "POST",
    body: form,
  });
}

/**
 * 이 공고의 «가장 최근 저장된» 검사 결과. 아직 없으면 null.
 *
 * 검사를 다시 돌리지 않고 읽기만 한다. 공용 데모 공고의 결과는 모든 회사가 함께 보는
 * 자료라 **쓰기**가 기본 회사로 한정돼 있다 — 화면이 열릴 때마다 재검사를 요청하면
 * 다른 회사에서는 403 이 나고, 저장된 결과가 있는데도 「검사하지 않음」으로 보였다
 * (ISSUE-060). 읽기는 회사 구분 없이 열려 있다.
 *
 * 「아직 없음」은 204(본문 없음)다. 이 경로가 없는 옛 배포 스냅샷을 위해 404·405 도
 * 오류로 올리지 않고 null 로 돌려준다.
 */
export async function getLatestAuditRun(
  procurementId: string,
  ctx?: AnalysisContextParams | null,
): Promise<AuditRunResult | null> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/auditor/${enc(procurementId)}/latest${ctxQuery(ctx)}`);
    if (response.status === 204 || response.status === 404 || response.status === 405) return null;
    if (!response.ok) {
      throw await apiError(response, `검사 결과 조회 실패 (${response.status})`);
    }
    return (await response.json()) as AuditRunResult;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405)) return null;
    throw error;
  }
}

// ---------------------------------------------------------------------------
// Auditor 발견 항목 해결 처리 — backend/app/api/auditor.py (resolutions)
// ---------------------------------------------------------------------------

/**
 * 지금 Auditor 를 돌려도 되는가. 초안이 이전 요구사항 집합 기준이면 ready=false 다.
 *
 * 옛 배포 스냅샷에는 이 경로가 없다 — 404 를 오류로 올리지 않고 null 로 돌려,
 * 화면이 「알 수 없음」으로 조용히 물러나게 한다.
 */
export async function getAuditReadiness(
  procurementId: string,
  ctx?: AnalysisContextParams | null,
): Promise<AuditReadiness | null> {
  try {
    return await getJson<AuditReadiness>(`/api/auditor/${enc(procurementId)}/readiness${ctxQuery(ctx)}`);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405)) return null;
    throw error;
  }
}

/** 이전 요구사항 집합 → 현재 집합의 변화. 일반 감사 결과와 «분리해» 보여준다. */
export async function getChangeImpact(
  procurementId: string,
  ctx?: AnalysisContextParams | null,
): Promise<ChangeImpact | null> {
  try {
    return await getJson<ChangeImpact>(`/api/auditor/${enc(procurementId)}/change-impact${ctxQuery(ctx)}`);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405)) return null;
    throw error;
  }
}

/** 담당자가 해결/재오픈 처리한 발견 항목 기록. 없으면 빈 목록. */
export function getFindingResolutions(procurementId: string, ctx?: AnalysisContextParams | null): Promise<FindingResolutionList> {
  return getJson<FindingResolutionList>(`/api/auditor/${enc(procurementId)}/resolutions${ctxQuery(ctx)}`);
}

/** 발견 항목을 해결 또는 다시 열림으로 기록한다 (사람의 판단 — 검사 결과는 바꾸지 않는다). */
export function saveFindingResolution(
  procurementId: string,
  body: FindingResolutionRequest,
  ctx?: AnalysisContextParams | null,
): Promise<FindingResolution> {
  return request<FindingResolution>(`/api/auditor/${enc(procurementId)}/resolutions${ctxQuery(ctx)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// 담당자 최종 검토 (Human Review) — backend/app/api/review.py
// ---------------------------------------------------------------------------

/**
 * 저장된 검토 결과. 아직 저장한 적이 없으면 null.
 *
 * 서버는 「아직 없음」을 **204**(본문 없음)로 답한다 — 오류가 아니라 정상 상태다
 * (ISSUE-037). 예전 404 도 계속 받아 준다: 스냅샷 배포본은 옛 응답을 담고 있을 수 있다.
 */
export async function getReview(
  procurementId: string,
  ctx?: AnalysisContextParams | null,
): Promise<ReviewDecision | null> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/review/${enc(procurementId)}${ctxQuery(ctx)}`);
    if (response.status === 204 || response.status === 404) return null;
    if (!response.ok) {
      throw await apiError(response, `검토 결과 조회 실패 (${response.status})`);
    }
    return (await response.json()) as ReviewDecision;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** 검토 결과를 저장한다. 승인은 체크리스트를 모두 채워야 하며 아니면 422가 온다. */
export function saveReview(body: ReviewDecisionRequest, ctx?: AnalysisContextParams | null): Promise<ReviewDecision> {
  return postJson<ReviewDecision>("/api/review", { ...body, ...ctxBody(ctx) });
}

export type ProposalExportFormat = "docx" | "pdf" | "txt";

export interface ProposalExportOptions {
  /** 기본 docx. pdf는 서버의 Word로 변환한다 (없으면 503). */
  format?: ProposalExportFormat;
  /** 회사 근거가 없는 「확인 필요」 문장을 본문에서 빼고 문서 끝 확인 목록으로 옮긴다. */
  groundedOnly?: boolean;
}

function exportQuery(options: ProposalExportOptions, ctx?: AnalysisContextParams | null): string {
  const extra: Record<string, string> = {};
  if (options.format && options.format !== "docx") extra.format = options.format;
  if (options.groundedOnly) extra.grounded_only = "true";
  return ctxQuery(ctx, extra);
}

/** 제안서 초안 내려받기 주소. 근거(RFP 페이지·원문, 회사자료)가 문서에 함께 실린다. */
export function proposalExportUrl(
  procurementId: string,
  options: ProposalExportOptions = {},
  ctx?: AnalysisContextParams | null,
): string {
  return `${BACKEND_URL}/api/proposal/${enc(procurementId)}/export${exportQuery(options, ctx)}`;
}

/** 제안서 **전체** 초안 내려받기 주소 (섹션 여러 개). */
export function proposalFullExportUrl(
  procurementId: string,
  options: ProposalExportOptions = {},
  ctx?: AnalysisContextParams | null,
): string {
  return `${BACKEND_URL}/api/proposal/${enc(procurementId)}/full/export${exportQuery(options, ctx)}`;
}

/** 입찰참가신청서 서식 초안 내려받기 주소. 표 모양 때문에 docx·pdf만 지원한다. 상호·주소는 선택한 회사 프로필에서. */
export function bidApplicationExportUrl(
  procurementId: string,
  format: "docx" | "pdf" = "docx",
  ctx?: AnalysisContextParams | null,
): string {
  const params = new URLSearchParams();
  if (format !== "docx") params.set("format", format);
  if (ctx) params.set("organization_id", ctx.organization_id);
  const query = params.toString();
  return `${BACKEND_URL}/api/proposal/${enc(procurementId)}/application/export${query ? `?${query}` : ""}`;
}

/** 제안서 전체 초안을 생성한다 (요구사항 카테고리별 섹션). `useClaude` · `writer` 는 사업계획서 작성 페이지만 (28차 §3-D · 29차 §3-A). */
export function generateFullProposal(
  procurementId: string,
  options: { useLlm?: boolean; useClaude?: boolean; writer?: PlanWriterName } = {},
  ctx?: AnalysisContextParams | null,
): Promise<unknown> {
  return postJson("/api/proposal/generate/full", {
    procurement_id: procurementId,
    use_llm: options.useLlm ?? false,
    ...(options.useClaude ? { use_claude: true, writer: options.writer ?? "claude" } : {}),
    ...ctxBody(ctx),
  });
}

/** 나라장터 공고 한 건(후보 창 안) — 사업계획서 작성 머리가 목록 밖 공고를 읽을 때 (29차 R28-09). 없으면 404. */
export function getProcurementNotice(noticeId: string): Promise<{ id: string; title: string; agency: string | null; deadline_at: string | null }> {
  return getJson(`/api/procurements/${enc(noticeId)}`);
}

/** 저장된 제안서 전체 초안 (없으면 404). */
export function getFullProposal(procurementId: string, ctx?: AnalysisContextParams | null): Promise<ProposalDocumentView> {
  return getJson<ProposalDocumentView>(`/api/proposal/${enc(procurementId)}/full${ctxQuery(ctx)}`);
}

// ---------------------------------------------------------------------------
// 입찰 제안서 초안 — 제안요청서 목차 · 평가 기준대로(11-03 · 백엔드 `bid_proposal_service`)
// ---------------------------------------------------------------------------

export interface BidPlanSentence {
  text: string;
  type: "RFP_GROUNDED" | "COMPANY_EVIDENCE_GROUNDED" | "AI_SUGGESTION" | null;
  /** 검토용 경고(모호한 표현 · 근거 없는 숫자 등) — 제출용 문서에는 실리지 않는다 */
  flags?: string[];
  note?: boolean;
}

export interface BidPlanSection {
  key: string;
  /** item · fields(일반현황 칸) · table_only(평가항목별 조견표) */
  kind: string;
  section: string;
  major_title: string;
  sentences: BidPlanSentence[];
  fields?: { label: string; value: string; filled_by?: string }[];
  tables?: string[];
  llm_error?: string | null;
  by?: "llm" | "rules";
}

export interface BidPlanTable {
  key: string;
  title: string;
  columns: string[];
  rows: string[][];
  human_only?: boolean;
}

export interface BidPlanView {
  kind: string;
  title: string;
  generated_by: "llm" | "rules";
  executed_at: string;
  writer?: string | null;
  model?: string | null;
  /** rfp — 제안요청서의 「제안서 목차」대로 · unread — 목차 머리는 있는데 읽지 못해 표준 목차 · standard — 목차가 없어 표준 목차 */
  outline_source: "rfp" | "unread" | "standard";
  /** 다시 쓰기가 모두 실패해 있던 AI 초안을 그대로 둠(만들기 응답만) */
  kept_previous?: boolean;
  rfp_document?: string | null;
  evaluation_total?: number | null;
  sections: BidPlanSection[];
  tables: BidPlanTable[];
  blanks: { field: string; why: string; section: string }[];
  llm_note?: string | null;
  llm_failures?: string[];
  /** 제출용 문서에 남는 「(담당자 입력)」 수 */
  submit_blanks?: number | null;
  /** 초안을 쓴 뒤 공고 분석(요구사항)이 바뀜 */
  stale?: boolean;
  /** (11-06) 목차를 읽은 곳 · 형식 규정 · 쓰지 않은 목차 후보 — 이 칸이 없는 초안은 예전 방식으로 쓴 것 */
  outline_where?: BidOutlineWhere | null;
  /** 목차 머리는 찾았지만 읽지 못한 곳(표준 목차로 쓴 까닭 · 사람이 볼 쪽) */
  outline_found_at?: BidOutlineWhere | null;
  format?: BidFormatRules | null;
  outline_rejected?: BidOutlineRejected[];
  /** (2.7.0) 품질 게이트 — 저장하지 않는 계산값. 이 칸이 없는 옛 응답도 그대로 그린다. */
  quality?: BidQuality | null;
}

/** 품질 게이트 심각도 — 화면 낱말은 `lib/bidQuality` 의 차단 · 중요 · 보통 · 참고. */
export type BidQualitySeverity = "BLOCKER" | "MAJOR" | "MINOR" | "INFO";
/** 제출 상태 — 차단 · 검토 필요 · 자동검증 통과 · 제출 준비(사람 승인). */
export type BidQualityStatus = "BLOCKED" | "NEEDS_REVIEW" | "VERIFIED_DRAFT" | "READY_TO_SUBMIT";

export interface BidQualityFinding {
  code: string;
  severity: BidQualitySeverity;
  /** 한국어 한 줄 */
  title: string;
  /** 한국어 — 원문 · 위치 */
  detail: string;
  /** 소항목 제목 */
  section: string | null;
  count: number;
  /** (2.8.0) 어디 — 소항목 · 표 이름 · 행. 옛 응답은 없음 */
  location?: string | null;
  /** (2.8.0) 고치는 방법 한 줄(코드마다) */
  action?: string | null;
  /** (2.9.0 · 게이트 판 3) 갈래 — 앱이 고칠 것 · 담당자 입력 · 증빙 · 사실 확인. 옛 응답은 없음 */
  axis?: BidQualityAxis;
}

/** (2.9.0) 검사 갈래 — auto 앱이 고칠 것(자동 작성 결함) · input 정상 담당자 입력 · evidence 증빙 필요 · fact 사실 확인 필요. */
export type BidQualityAxis = "auto" | "input" | "evidence" | "fact";

/** (2.9.0) 자동 작성 검사 — 앱이 고칠 것만 본다(담당자 입력이 남았다는 이유로 실패하지 않음). */
export interface BidQualityGeneration {
  status: "PASS" | "REVIEW" | "FAIL" | "ERROR";
  label: string;
  counts: Record<BidQualitySeverity, number>;
}

/** (2.8.0) 평가 항목 하나가 제안서 어디에 대응하나 — 조견표 「제안서 해당 목차」와 그 본문. */
export interface BidEvaluationCoverage {
  name: string;
  area: string | null;
  kind: "정성" | "정량" | null;
  points: number | null;
  /** 대응 목차(「Ⅲ-2」) — 없으면 null */
  mapped: string | null;
  /** 짝 출처 — AI 가 적음 · 제목 이름 · 본문 소제목 · (2.9.0) 작성 방법 · AI 다시 물음 */
  source: "ai" | "title" | "heading" | "guide" | "ai_retry" | null;
  /** 그 목차 본문에 평가 기준 낱말이 있나(근사) */
  body: "확인" | "없음" | "미확인";
  status: "OK" | "REVIEW" | "MISSING";
  /** (2.9.0) 목차가 비었을 때 상태 — 본문에 내용 있음(자동 연결 실패) · 인력 · 증빙 항목 · 본문에 내용 없음 */
  gap?: "auto_link" | "evidence" | "no_body" | null;
  /** (2.9.0) 자동 연결 실패일 때 내용이 있는 목차(「Ⅲ-2」) */
  candidate?: string | null;
}

/** (2.8.0) 초안이 인용한 회사 근거의 상태 — 지금 회사 칸으로만 계산(증빙 확인 칸은 아직 없음). */
export interface BidEvidenceStatus {
  ledger: { cited: number; SELF_REPORTED: number; UNVERIFIED: number; MISSING: number };
  certifications: { cited: number; SELF_REPORTED: number; EXPIRED: number; MISSING: number };
  /** 참여인력 명부는 앱에 없다(11-08 결정) — 늘 MISSING */
  personnel: "MISSING";
  notes: string[];
}

/** (2.8.0) 마지막 한글(HWPX) 내려받기 때 만든 파일을 다시 읽어 게이트와 맞춘 결과. */
export interface BidHwpxCheck {
  at: string;
  /** 검사한 판 — 제출용 · 평가본(평가본은 식별 칸을 가려 미작성 칸 수가 적다) */
  variant?: "submit" | "blind";
  /** 평가본만 받는 공고(2.10.0 D8) — 평가본이 제출 파일 · 회사명 판은 「회사명 포함본」 */
  blind_only?: boolean;
  /** 한글 구조 검사 */
  ok: boolean;
  /** 만든 파일 글을 다시 읽음 */
  reextract_ok: boolean;
  /** 파일 안 미작성 칸 수 — 다시 읽지 못했으면 null */
  placeholders: number | null;
  /** 게이트가 센 미작성 칸 수 */
  gate_spots: number;
  match: boolean;
  /** 파일 안에서 겹친 대항목 번호 */
  duplicate_majors: string[];
}

export interface BidQualityApproval {
  by: string;
  by_name: string | null;
  at: string;
  note: string | null;
}

export interface BidQuality {
  status: BidQualityStatus;
  status_label: string;
  counts: Record<BidQualitySeverity, number>;
  /** (2.9.0) 자동 작성 검사 — 제출 상태(status)와 다른 축. 옛 응답은 없음 */
  generation?: BidQualityGeneration | null;
  /** (2.9.0) 갈래마다 참고를 뺀 항목 수 */
  axes?: Record<BidQualityAxis, number> | null;
  findings: BidQualityFinding[];
  /** 공고가 요구한 사람 몫 표(조직 및 인원 · 참여인력) 중 하나라도 빔 — 앱은 이름 · 경력을 짓지 않는다(역할 · 담당 업무는 본문 업무분장에서 옮김) */
  staffing_unconfirmed: boolean;
  /** 지금 초안 판에 묶인 사람 승인 — 초안이 바뀌면 서버가 풀어 null */
  approval: BidQualityApproval | null;
  draft_hash: string;
  /** 제출용 내려받기 파일 이름 — 「제출 준비」일 때만 「제출용」 */
  file_label: "초안" | "제출용";
  /** (2.8.0 · 아래 칸은 모두 옛 응답에 없음) 검사 규칙 판 */
  gate_version?: number;
  /** 검사한 시각(ISO) */
  checked_at?: string;
  /** 제출용 파일에 남는 미작성 칸 수 */
  submit_blanks?: number;
  /** 검토용 「담당자가 채울 항목」 건수 */
  review_blanks?: number;
  evaluation_coverage?: BidEvaluationCoverage[];
  evidence_status?: BidEvidenceStatus | null;
  /** 원문 사업기간 · 종료일 · 사업금액 글(없으면 null) */
  terms?: { period: string | null; end: string | null; budget: string | null } | null;
  /** 마지막 한글 내려받기 검사 — 아직 안 받았으면 null */
  hwpx_check?: BidHwpxCheck | null;
  /** (2.10.0) 마지막 「한글에서 저장한 PDF 검사」 — 지금 초안으로 아직 안 했으면 null · 제출 상태 · 승인과 따로(D10) */
  pdf_check?: BidPdfCheck | null;
}

/** (2.10.0 T8) 한글에서 저장한 PDF 검사 결과 — 쪽수 · A4 · 미작성 · 평가본 식별 낱말 · 표지 링크 · 예산 산수 · 조견표 실제 쪽. */
export interface BidPdfCheck {
  at: string;
  /** 검사한 초안 판 — 다시 쓰면 서버가 「아직 안 함」(null)으로 */
  draft_hash: string;
  /** unreadable — 읽지 못함(통과 아님) · issues — 차단 · 중요가 있음 · ok — 통과 */
  state: "unreadable" | "issues" | "ok";
  state_label: string;
  pages: number | null;
  page_limit: number | null;
  counts: Record<BidQualitySeverity, number>;
  findings: BidQualityFinding[];
}

/** 원문의 어디서 읽었나 — 파일 이름 · 쪽 · 머리 줄. */
export interface BidOutlineWhere {
  document: string | null;
  page: number | null;
  head: string | null;
}

/** 제안서 목차로 쓰지 않은 후보와 사유(문서 앞 목차 등). */
export interface BidOutlineRejected {
  head: string;
  page: number | null;
  reason: string;
}

/** 원문이 정한 제안서 형식 규정(11-06 · 백엔드 `read_format`). */
export interface BidFormatRules {
  page_limit: number | null;
  page_note?: string | null;
  /** 평가본에 회사명 · 대표자 표기 금지 */
  blind: boolean;
  blind_note?: string | null;
  /** (2.10.0 D8) 평가본 규정에 원본 · 사본 구분이 없음 — 평가본이 곧 제출 파일. 옛 초안에는 없다 */
  blind_only?: boolean;
  landscape: boolean;
  ppt: boolean;
  /** 정량 · 정성 제안서를 따로 냄 */
  two_volume: boolean;
  volumes?: string[];
  notes?: string[];
}

/** 쓰기 전에 「이 양식으로 씁니다」 — 제안서 목차 · 평가표 · 형식 규정(AI 없이 · 백엔드 `outline_preview`). */
export interface BidOutlinePreview {
  procurement_id: string;
  outline_source: "rfp" | "unread" | "standard";
  outline: { no: string; title: string; items: { no: string; title: string }[] }[];
  outline_where: BidOutlineWhere | null;
  /** 목차 머리는 찾았지만 읽지 못한 곳 — `outline_source` 가 unread 일 때 */
  outline_found_at?: BidOutlineWhere | null;
  outline_rejected: BidOutlineRejected[];
  evaluation: {
    items: { area: string | null; name: string; points: number | null; kind?: string | null }[];
    total: number | null;
    where: BidOutlineWhere | null;
  };
  format: BidFormatRules;
  documents: { name: string; role: string | null; pages: number | null }[];
  warnings: string[];
}

/** 제안서 양식 미리 보기(읽기만 · 열람자도). 분석 전이면 422 · 제안요청서가 없으면 409 와 사유. */
export function getBidPlanOutline(procurementId: string, ctx?: AnalysisContextParams | null): Promise<BidOutlinePreview> {
  return getJson<BidOutlinePreview>(`/api/proposal/${enc(procurementId)}/plan-outline${ctxQuery(ctx)}`);
}

/** 제안서 초안을 쓴다 — 대항목마다 Claude · Codex 한 번(최대 약 5분). 제안요청서가 없으면 422 와 사유. */
export function createBidPlan(procurementId: string, writer: PlanWriterName, ctx?: AnalysisContextParams | null): Promise<BidPlanView> {
  return postJson<BidPlanView>(`/api/proposal/${enc(procurementId)}/plan-draft`, { writer, ...ctxBody(ctx) });
}

/** 저장된 제안서 초안(없으면 404). */
export function getBidPlan(procurementId: string, ctx?: AnalysisContextParams | null): Promise<BidPlanView> {
  return getJson<BidPlanView>(`/api/proposal/${enc(procurementId)}/plan-draft${ctxQuery(ctx)}`);
}

/** 제안서 초안 승인(편집자 이상) — 갱신된 품질. 차단이 남으면 409 · 그사이 초안이 바뀌면 409 · 초안 없음 404 · 열람자 403(사유는 서버 글).
 *  `draftHash` 는 화면에서 본 초안 판(`quality.draft_hash`) — 다른 사람이 다시 쓴 판을 읽지 않고 승인하지 않게(2.7.0 검토).
 *  `note` 는 승인 메모(선택 · 200자 — 화면 `approvalNote` 가 다듬음 · 빈 글이면 보내지 않음 · 2.8.0). */
export function approveBidPlan(procurementId: string, ctx?: AnalysisContextParams | null, draftHash?: string | null, note?: string): Promise<BidQuality> {
  return postJson<BidQuality>(`/api/proposal/${enc(procurementId)}/plan-draft/approve`, {
    ...ctxBody(ctx),
    ...(draftHash ? { draft_hash: draftHash } : {}),
    ...(note ? { note } : {}),
  });
}

/** 제안서 초안 승인 취소 — 갱신된 품질. */
export function revokeBidPlanApproval(procurementId: string, ctx?: AnalysisContextParams | null): Promise<BidQuality> {
  return request<BidQuality>(`/api/proposal/${enc(procurementId)}/plan-draft/approve${ctxQuery(ctx)}`, { method: "DELETE" });
}

/** 제안서 초안 내려받기 — 제출용(표식 · 메모 없음) · 검토용 · 평가본(회사명 없음 · 11-06) × 워드 · PDF · 한글(HWPX · 11-03). */
export function bidPlanExportUrl(
  procurementId: string,
  options: { format?: "docx" | "pdf" | "hwpx"; variant?: "submit" | "review" | "blind" } = {},
  ctx?: AnalysisContextParams | null,
): string {
  const extra: Record<string, string> = { format: options.format ?? "docx", variant: options.variant ?? "submit" };
  return `${BACKEND_URL}/api/proposal/${enc(procurementId)}/plan-draft/export${ctxQuery(ctx, extra)}`;
}

/** 제안서 검증 보고서(2.8.0 · 열람자도) — 최신 검사 + 이 공고 검사 이력 줄(JSON 내려받기) · xlsx 는 검사 항목 · 담당자 확인 사항 · 제출 서류 세 시트(2.10.0). */
export function bidPlanQualityReportUrl(procurementId: string, ctx?: AnalysisContextParams | null, format: "json" | "xlsx" = "json"): string {
  return `${BACKEND_URL}/api/proposal/${enc(procurementId)}/plan-draft/quality-report${ctxQuery(ctx, format === "xlsx" ? { format } : undefined)}`;
}

/** (2.10.0 T8) 한글에서 저장한 PDF 를 올려 검사한다(편집자 이상 · 20MB) — 품질 보고서에 남고 제출 상태 · 승인은 그대로. */
export function checkBidPlanPdf(procurementId: string, file: File, ctx?: AnalysisContextParams | null): Promise<BidPdfCheck> {
  const form = new FormData();
  form.append("file", file);
  return request<BidPdfCheck>(`/api/proposal/${enc(procurementId)}/plan-draft/check-pdf${ctxQuery(ctx)}`, { method: "POST", body: form });
}

/** 공고문에 질문하기(2.4.0) — 읽을 원문 · AI 상태 · 오늘 쓴 횟수(읽기만 · 열람자도). */
export function getNoticeQa(itemId: string, ctx?: AnalysisContextParams | null): Promise<NoticeQaState> {
  return getJson<NoticeQaState>(`/api/notice-qa/${enc(itemId)}${ctxQuery(ctx)}`);
}

/** 공고문에 질문 하나 — AI 답(원문 쪽 · 인용) 또는 낱말 찾기(최대 약 2분 · 편집자 이상 · 저장하지 않음). */
export function askNoticeQuestion(itemId: string, question: string, ctx?: AnalysisContextParams | null): Promise<NoticeQaAnswer> {
  return postJson<NoticeQaAnswer>(`/api/notice-qa/${enc(itemId)}`, { question, ...ctxBody(ctx) });
}

/** AI 에 갈 근거 문장 수(승인된 회사자료 문단 중 유사도 기준으로 고른 것) — 보낼 본문과 같은 계산 (28차 §3-D). */
export function getAdoptedEvidence(procurementId: string, ctx?: AnalysisContextParams | null): Promise<{ adopted: number; mandatory: number; evidence_scope: string }> {
  return getJson(`/api/proposal/${enc(procurementId)}/adopted-evidence${ctxQuery(ctx)}`);
}

// ---------------------------------------------------------------------------
// 사업계획서 작성 페이지 (28차 §3-D)
// ---------------------------------------------------------------------------

/** 사업계획서 작성 페이지에서 고르는 쓰는 이 (29차 §3-A). */
export type PlanWriterName = "claude" | "codex";

/** CLI 하나의 연결 상태 — Claude · Codex 같은 모양. */
export interface PlanWriterCliStatus {
  enabled: boolean;
  model: string;
  cli: boolean;
  logged_in: boolean;
  auth_method: string | null;
  subscription_type: string | null;
  training_reminder: boolean;
  off_reason: string | null;
}

/** 맨 위 칸은 Claude(28차 모양 그대로) · Codex 는 `codex` 아래 (29차 §3-A). */
export interface PlanWriterStatus extends PlanWriterCliStatus {
  codex?: PlanWriterCliStatus;
}

export interface SavedPlanDraft {
  kind: "support" | "proposal";
  id: string;
  title: string | null;
  task: string | null;
  generated_by: "llm" | "rules" | null;
  provider: string | null;
  model: string | null;
  executed_at: string | null;
  elapsed_seconds: number | null;
  ai_sentences: number | null;
  blanks: number;
  versions: number;
}

export interface PlanDraftVersionMeta {
  name: string;
  generated_by: "llm" | "rules" | null;
  provider: string | null;
  model: string | null;
  executed_at: string | null;
  ai_sentences: number | null;
  blanks: number;
  kept_rules: boolean;
}

/** 「Claude 연결」 줄 — 꺼져 있으면 서버가 프로세스를 띄우지 않는다. */
export function getPlanWriterStatus(): Promise<PlanWriterStatus> {
  return getJson<PlanWriterStatus>("/api/plan-writer/status");
}

/** 이 회사의 저장된 사업계획서 · 제안서 초안(메타만) · 서버에서 Claude 로 만드는 중인가. */
export function listPlanDrafts(organizationId?: string): Promise<{ items: SavedPlanDraft[]; running: boolean }> {
  const suffix = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
  return getJson(`/api/plan-drafts${suffix}`);
}

/** 사업계획서 이전 판 목록(메타만 · 읽기 전용). */
export function listPlanDraftVersions(programId: string, organizationId?: string): Promise<{ items: PlanDraftVersionMeta[] }> {
  const suffix = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
  return getJson(`/api/support-programs/${enc(programId)}/plan-draft/versions${suffix}`);
}

// ---------------------------------------------------------------------------
// Critical Conditions · Action Checklist · GO/HOLD/NO_GO — backend/app/api/conditions.py
// ---------------------------------------------------------------------------

/** 저장된 조건 보고서. 없으면 backend가 규칙으로 즉시 탐지한다 (요구사항이 없으면 404). */
export function getConditions(procurementId: string, ctx?: AnalysisContextParams | null): Promise<CriticalConditionReport> {
  return getJson<CriticalConditionReport>(`/api/conditions/${enc(procurementId)}${ctxQuery(ctx)}`);
}

/**
 * 개발 수행역량 판정 — 「이 공고를 우리 개발진이 수행할 수 있나」.
 *
 * 저장하지 않고 매번 다시 계산한다. 회사 역량자료를 고치면 다음 조회에서 바로 반영된다.
 */
export function getCapability(procurementId: string, ctx?: AnalysisContextParams | null): Promise<CapabilityReport> {
  return getJson<CapabilityReport>(`/api/capability/${enc(procurementId)}${ctxQuery(ctx)}`);
}

/** 실적 원장 후보 하나(45차 H5) — AI 검색을 꺼 둔 회사가 쓸 것을 「채택」한다. */
export interface LedgerCandidate {
  requirement_id: string;
  evidence_id: string;
  document_name: string;
  source_text: string;
  /** 채택했으면 누가(적은 이름) · 서버가 본 사람 · 언제 */
  adopted: { by: string; recorded_by?: string | null; at: string } | null;
}

export interface LedgerView {
  procurement_id: string;
  /** AI 검색(회사 근거 연결)을 꺼 두었는가 — 꺼 두었을 때만 원장 후보가 온다 */
  ai_search_off: boolean;
  /** 이 회사 분석에 채택을 남길 수 있나(가상 예시 공고는 아님) */
  editable: boolean;
  candidates: LedgerCandidate[];
  adopted_count: number;
}

export function getLedgerCandidates(procurementId: string, ctx?: AnalysisContextParams | null): Promise<LedgerView> {
  return getJson<LedgerView>(`/api/evidence/${enc(procurementId)}/ledger${ctxQuery(ctx)}`);
}

export function setLedgerAdoption(
  procurementId: string,
  body: { requirement_id: string; evidence_id: string; adopted: boolean; by: string },
  ctx?: AnalysisContextParams | null,
): Promise<LedgerView> {
  return putJson<LedgerView>(`/api/evidence/${enc(procurementId)}/ledger${ctxQuery(ctx)}`, body);
}

/** 회사 개발역량 자료 (인원·기술·자격). 없으면 source="absent". */
export function getDeliveryCapacity(ctx?: AnalysisContextParams | null): Promise<DeliveryCapacity> {
  return getJson<DeliveryCapacity>(`/api/capability/profile${ctxQuery(ctx)}`);
}

/** 회사자료 빈칸 안내 한 칸 (38차 §3-C-7) — 비어 있어서 판정이 멈춘 칸과 그 칸 때문에 「확인 필요」로 남은 공고 수. */
export interface BlankField {
  key: string;
  label: string;
  where: string;
  blank: boolean;
  count: number;
  examples: { id: string; title: string; source: string }[];
  /** 41차 D31 — 담당자가 「안 적음(그대로 둠)」으로 고른 빈칸(세지 않음 · 판정은 그대로 「확인 필요」). */
  left_blank?: boolean;
  /** 43차 Q25 — 그 칸 하나만 걸린 공고 수 · 적어도 판정을 못 바꾸는 참고 칸(공동수급 파트너). 옛 응답에는 없다. */
  only_count?: number;
  reference?: boolean;
  /** 44차 대표 결정 1 — 대표가 적는 칸(회사 단위 확인 · 직접생산 품명 · 디지털 제품 · 개업일 · 여성기업 · 인증 이력). 걸린 공고가 0건이어도 보인다. */
  owner_value?: boolean;
}

export interface BlankFieldsResponse {
  organization_id: string;
  fetched_at: string | null;
  fields: BlankField[];
  note: string;
}

/** 회사자료 빈칸 안내 (38차 §3-C-7). 읽기 전용 · 네트워크는 서버 저장본만. */
export function getBlankFields(ctx?: AnalysisContextParams | null): Promise<BlankFieldsResponse> {
  return getJson<BlankFieldsResponse>(`/api/capability/blank-fields${ctxQuery(ctx)}`);
}

/** 빈 회사 칸 「안 적음(그대로 둠)」 열쇠 전부를 저장한다(41차 D31) — 판정은 바뀌지 않고 빈칸 안내에서만 빠진다. 회사 값은 쓰지 않는다. */
export function saveLeftBlank(
  keys: string[],
  updatedBy: string,
  ctx?: AnalysisContextParams | null,
  expectedUpdatedAt?: string | null,
): Promise<DeliveryCapacity> {
  // 43차 M25 — 처음 읽은 시각을 보내면 그사이 남이 저장했을 때 409(undefined 면 보내지 않는다 · 옛 호출)
  return putJson<DeliveryCapacity>(`/api/capability/left-blank${ctxQuery(ctx)}`, {
    keys,
    updated_by: updatedBy,
    ...(expectedUpdatedAt !== undefined ? { expected_updated_at: expectedUpdatedAt } : {}),
  });
}

/** 회사 단위 한 번 확인(43차 결정 2) — 열쇠마다 확인일 · 유효기간 · 확인한 사람, null 이면 지운다. 사람이 고른 값만 보낸다. */
export function saveCompanyChecks(
  checks: Record<string, { confirmed_on: string; valid_until: string; confirmed_by: string } | null>,
  updatedBy: string,
  ctx?: AnalysisContextParams | null,
  expectedUpdatedAt?: string | null,
): Promise<DeliveryCapacity> {
  return putJson<DeliveryCapacity>(`/api/capability/company-checks${ctxQuery(ctx)}`, {
    checks,
    updated_by: updatedBy,
    ...(expectedUpdatedAt !== undefined ? { expected_updated_at: expectedUpdatedAt } : {}),
  });
}

/** 회사 역량·입찰 자격 자료를 저장한다. **저장은 사람이 한다** — 화면이 자동으로 부르지 않는다. */
export function saveCapabilityProfile(
  body: DeliveryCapacityUpdate,
  ctx?: AnalysisContextParams | null,
): Promise<DeliveryCapacity> {
  return putJson<DeliveryCapacity>(`/api/capability/profile${ctxQuery(ctx)}`, body);
}

/** 규칙으로 조건을 다시 탐지한다 (LLM 없음). 사람의 해결 기록은 유지된다. */
export function detectConditions(procurementId: string, ctx?: AnalysisContextParams | null): Promise<CriticalConditionReport> {
  return postJson<CriticalConditionReport>("/api/conditions/detect", { procurement_id: procurementId, ...ctxBody(ctx) });
}

/** 담당자가 조건 상태를 바꾼다 (CLEARED는 사람만). */
export function updateCondition(
  procurementId: string,
  conditionId: string,
  body: ConditionUpdateRequest,
  ctx?: AnalysisContextParams | null,
): Promise<CriticalConditionReport> {
  return putJson<CriticalConditionReport>(`/api/conditions/${enc(procurementId)}/${enc(conditionId)}${ctxQuery(ctx)}`, body);
}

export function getActions(procurementId: string, ctx?: AnalysisContextParams | null): Promise<ActionChecklist> {
  return getJson<ActionChecklist>(`/api/actions/${enc(procurementId)}${ctxQuery(ctx)}`);
}

export function createAction(procurementId: string, body: ActionCreateRequest, ctx?: AnalysisContextParams | null): Promise<ActionItem> {
  return postJson<ActionItem>(`/api/actions/${enc(procurementId)}${ctxQuery(ctx)}`, body);
}

export function updateAction(
  procurementId: string,
  actionId: string,
  body: ActionUpdateRequest,
  ctx?: AnalysisContextParams | null,
): Promise<ActionItem> {
  return putJson<ActionItem>(`/api/actions/${enc(procurementId)}/${enc(actionId)}${ctxQuery(ctx)}`, body);
}

export function deleteAction(procurementId: string, actionId: string, ctx?: AnalysisContextParams | null): Promise<void> {
  return deleteRequest(`/api/actions/${enc(procurementId)}/${enc(actionId)}${ctxQuery(ctx)}`);
}

/** 내 비밀번호 바꾸기(44차 S5) — 지금 비밀번호가 틀리면 400 · 연속 실패면 429. 응답 본문 없음. */
export async function changeMyPassword(oldPassword: string, newPassword: string): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/api/auth/password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  if (!response.ok) throw await apiError(response, `Backend request failed (${response.status})`);
}

/** 결정. 저장한 적이 없으면 UNREVIEWED로 온다. */
export function getDecision(procurementId: string, ctx?: AnalysisContextParams | null): Promise<BidDecision> {
  return getJson<BidDecision>(`/api/decision/${enc(procurementId)}${ctxQuery(ctx)}`);
}

/** 사람이 GO/HOLD/NO_GO를 저장한다. 미해결 BLOCKER면 GO는 422. */
export function saveDecision(procurementId: string, body: DecisionRequest, ctx?: AnalysisContextParams | null): Promise<BidDecision> {
  return putJson<BidDecision>(`/api/decision/${enc(procurementId)}${ctxQuery(ctx)}`, body);
}

// ---------------------------------------------------------------------------
// 회사정보·수행근거 — 레거시 호환 API 는 **클라이언트에서 걷어냈다** (ISSUE-043)
//
// `/api/company/*` 는 backend 에 그대로 있다(기본 조직으로 위임). 다만 화면은 2026-09-07
// 다회사 구조 이후 전부 `/api/organizations/{id}/...` 만 쓰고, 여기 있던 래퍼 13개는
// 한 곳에서도 호출되지 않았다. 같은 일을 하는 함수가 두 벌 있으면 다음 사람이 어느 쪽을
// 고쳐야 하는지 알 수 없고, 조직 id 를 안 받는 쪽을 고르면 회사 격리가 조용히 깨진다.
//
// 되살릴 일이 있으면 아래 조직 함수에서 organizationId 를 빼면 그대로다.
// 서버 쪽 호환 경로를 지운 것이 아니다 — 스크립트·외부 호출은 그대로 동작한다.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// 조직(회사) — backend/app/api/organizations.py (다회사 구조)
//
// 아래 여덟 개는 **화면에서 아직 부르지 않는다**: activateOrganization ·
// deactivateOrganization · updateOrganization · getOrganization ·
// getOrganizationIndexStatus · generateFullProposal · getChangeImpact ·
// getDeliveryCapacity.
//
// 남겨 둔 이유: 위 레거시 래퍼들과 달리 **같은 일을 하는 다른 함수가 없다.** 백엔드에는
// 그 엔드포인트가 있고 화면만 아직 없는 것이라, 지우면 다음 사람이 「이 기능이 없나」로
// 읽는다. 쓰이기 시작하면 이 목록에서 지운다.
// ---------------------------------------------------------------------------

const org = (organizationId: string, suffix = "") => `/api/organizations/${enc(organizationId)}${suffix}`;

export function listOrganizations(): Promise<OrganizationListResponse> {
  return getJson<OrganizationListResponse>("/api/organizations");
}

export function createOrganization(body: OrganizationCreateRequest): Promise<Organization> {
  return postJson<Organization>("/api/organizations", body);
}

export function getOrganization(organizationId: string): Promise<OrganizationSummary> {
  return getJson<OrganizationSummary>(org(organizationId));
}

export function updateOrganization(
  organizationId: string,
  body: { display_name?: string; legal_name?: string | null; data_class?: string; approved_for_public?: boolean; updated_by: string; note?: string | null },
): Promise<Organization> {
  return patchJson<Organization>(org(organizationId), body);
}

export function activateOrganization(organizationId: string, updatedBy: string): Promise<Organization> {
  return postJson<Organization>(org(organizationId, "/activate"), { updated_by: updatedBy });
}

export function deactivateOrganization(organizationId: string, updatedBy: string): Promise<Organization> {
  return postJson<Organization>(org(organizationId, "/deactivate"), { updated_by: updatedBy });
}

export function getOrganizationProfile(organizationId: string): Promise<OrganizationProfile> {
  return getJson<OrganizationProfile>(org(organizationId, "/profile"));
}

export function saveOrganizationProfile(organizationId: string, body: OrganizationProfileUpdate): Promise<OrganizationProfile> {
  return putJson<OrganizationProfile>(org(organizationId, "/profile"), body);
}

/** 사업계획서 일반현황 (29차 §3-B) — 대표자 · 사업자등록번호 · 개업연월일 · 업태/종목 · 연도별 매출 · 고용 · 인력 구성. */
export function getPlanGeneral(organizationId: string): Promise<PlanGeneralInfo> {
  return getJson<PlanGeneralInfo>(org(organizationId, "/plan-general"));
}

export function savePlanGeneral(organizationId: string, body: PlanGeneralUpdate): Promise<PlanGeneralInfo> {
  return putJson<PlanGeneralInfo>(org(organizationId, "/plan-general"), body);
}

export function listOrganizationDocuments(organizationId: string): Promise<DocumentListResponse> {
  return getJson<DocumentListResponse>(org(organizationId, "/documents"));
}

export function uploadOrganizationDocument(
  organizationId: string,
  file: File,
  options: { docType?: string; dataClass?: string; uploadedBy?: string } = {},
): Promise<CompanyDocumentDetail> {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", options.docType ?? "기타");
  form.append("data_class", options.dataClass ?? "real");
  if (options.uploadedBy) form.append("uploaded_by", options.uploadedBy);
  return request<CompanyDocumentDetail>(org(organizationId, "/documents"), { method: "POST", body: form });
}

export function getOrganizationDocument(organizationId: string, documentId: string): Promise<CompanyDocumentDetail> {
  return getJson<CompanyDocumentDetail>(org(organizationId, `/documents/${enc(documentId)}`));
}

export function reextractOrganizationDocument(organizationId: string, documentId: string): Promise<CompanyDocumentDetail> {
  return postJson<CompanyDocumentDetail>(org(organizationId, `/documents/${enc(documentId)}/extract`), {});
}

export function reviewOrganizationCandidates(organizationId: string, documentId: string, body: CandidateReviewRequest): Promise<CompanyDocumentDetail> {
  return putJson<CompanyDocumentDetail>(org(organizationId, `/documents/${enc(documentId)}/candidates`), body);
}

export function approveOrganizationDocument(organizationId: string, documentId: string, body: DocumentApproveRequest): Promise<CompanyDocumentDetail> {
  return postJson<CompanyDocumentDetail>(org(organizationId, `/documents/${enc(documentId)}/approve`), body);
}

export function retireOrganizationDocument(
  organizationId: string,
  documentId: string,
  body: { reviewer: string; note?: string | null },
): Promise<CompanyDocument> {
  return postJson<CompanyDocument>(org(organizationId, `/documents/${enc(documentId)}/retire`), body);
}

export function deleteOrganizationDocument(organizationId: string, documentId: string): Promise<void> {
  return deleteRequest(org(organizationId, `/documents/${enc(documentId)}`));
}

export function getOrganizationDocumentUsage(organizationId: string, documentId: string): Promise<UsageResponse> {
  return getJson<UsageResponse>(org(organizationId, `/documents/${enc(documentId)}/usage`));
}

export function getOrganizationIndexStatus(organizationId: string): Promise<IndexStatus> {
  return getJson<IndexStatus>(org(organizationId, "/index"));
}

export function rebuildOrganizationIndex(organizationId: string): Promise<ReindexResult> {
  return postJson<ReindexResult>(org(organizationId, "/index/rebuild"), {});
}

/** 등록 흐름의 '테스트 검색' — 이 회사의 승인·색인 문단만 검색한다. */
export function searchOrganizationIndex(organizationId: string, query: string, topK = 5): Promise<IndexSearchResult> {
  return postJson<IndexSearchResult>(org(organizationId, "/index/search"), { query, top_k: topK });
}

export function inspectLedger(organizationId: string, file: File): Promise<LedgerInspectResult> {
  const form = new FormData();
  form.append("file", file);
  return request<LedgerInspectResult>(org(organizationId, "/ledger/inspect"), { method: "POST", body: form });
}

export function previewLedger(organizationId: string, body: LedgerPreviewRequest): Promise<LedgerPreviewResult> {
  return postJson<LedgerPreviewResult>(org(organizationId, "/ledger/preview"), body);
}

export function importLedger(
  organizationId: string,
  body: LedgerPreviewRequest & { reviewer: string; approve: boolean; source_name?: string | null },
): Promise<LedgerImportResult> {
  return postJson<LedgerImportResult>(org(organizationId, "/ledger/import"), body);
}

export function getLedgerSummary(organizationId: string): Promise<LedgerSummary> {
  return getJson<LedgerSummary>(org(organizationId, "/ledger/summary"));
}

export function getLedgerProfiles(organizationId: string): Promise<{ profiles: LedgerImportProfile[] }> {
  return getJson<{ profiles: LedgerImportProfile[] }>(org(organizationId, "/ledger/profiles"));
}

// ---------------------------------------------------------------------------
// 기업마당 지원사업 · 서식 템플릿 · 정정 — backend/app/api/{insights,templates}.py
// ---------------------------------------------------------------------------

/**
 * 통합 사업기회 — 나라장터 입찰 + 기업마당 지원사업을 **선택한 회사 기준 검토 우선순위**로.
 * 한쪽 출처가 실패해도 다른 쪽은 그대로 온다 (응답의 source_errors 를 화면에서 숨기지 않는다).
 */
export function getBusinessOpportunities(query: OpportunityQuery = {}): Promise<UnifiedOpportunityListResponse> {
  const params = new URLSearchParams();
  if (query.organizationId) params.set("organization_id", query.organizationId);
  if (query.source && query.source !== "all") params.set("source", query.source);
  if (query.days !== undefined) params.set("days", String(query.days));
  if (query.sort) params.set("sort", query.sort);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.includeClosed) params.set("include_closed", "true");
  if (query.includeLow) params.set("include_low", "true");
  if (query.includeBlocked) params.set("include_blocked", "true");
  if (query.forRadar) params.set("for_radar", "true");
  const suffix = params.toString();
  const path = `/api/business-opportunities${query.refresh ? "/refresh" : ""}${suffix ? `?${suffix}` : ""}`;
  /**
   * 「재수집」은 조회가 아니다 (S8).
   *
   * 바깥(나라장터·기업마당)을 실제로 부르고 그 결과로 저장소의 캐시 파일을 덮어쓴다.
   * GET 으로 두면 열람자도 부를 수 있고 활동 기록에도 남지 않으며, 쿠키가 `SameSite=Lax`
   * 라 다른 사이트의 링크 한 번으로도 도달한다. 그래서 재수집만 POST 로 보낸다.
   */
  return query.refresh
    ? postJson<UnifiedOpportunityListResponse>(path, {})
    : getJson<UnifiedOpportunityListResponse>(path);
}

/** 사업기회 「선제준비」 칸 — 사전규격 · 발주계획(39차 결정 1). 입찰 목록과 같은 저장본을 읽는다(조회만). */
export function getPrepareSection(organizationId?: string, part: "all" | "main" | "folds" = "all"): Promise<PrepareSection> {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  if (part !== "all") params.set("part", part);
  const suffix = params.toString();
  return getJson<PrepareSection>(`/api/business-opportunities/prepare${suffix ? `?${suffix}` : ""}`);
}

/** 지원사업 1건 + 신청 분석(신청자격·조건·기간·서류·근거·계획서 뼈대·신청 전 점검). 입찰 분석과 다른 흐름이다. */
export function getSupportProgram(programId: string, organizationId?: string): Promise<SupportApplicationResult> {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  const suffix = params.toString();
  return getJson<SupportApplicationResult>(`/api/support-programs/${enc(programId)}${suffix ? `?${suffix}` : ""}`);
}

/** 저장된 사업계획서 초안 (없으면 sections 가 빈 배열). */
export function getSupportPlanDraft(programId: string, organizationId?: string): Promise<PlanDraft> {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  const suffix = params.toString();
  return getJson<PlanDraft>(`/api/support-programs/${enc(programId)}/plan-draft${suffix ? `?${suffix}` : ""}`);
}

/**
 * 사업계획서 초안을 **만든다**. 크레딧이 없으면 규칙 경로(공고 양식 뼈대)로 만들어 돌려준다.
 * `task_no` = 사람이 고른 과제 · `force_rules` = 확인 창을 거쳐 AI 초안 대신 규칙 초안으로 바꿀 때만.
 */
export function createSupportPlanDraft(
  programId: string,
  organizationId?: string,
  body: { task_no?: number; force_rules?: boolean; use_claude?: boolean; writer?: PlanWriterName; no_ai?: boolean } = {},
): Promise<PlanDraft> {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  const suffix = params.toString();
  return postJson<PlanDraft>(`/api/support-programs/${enc(programId)}/plan-draft${suffix ? `?${suffix}` : ""}`, body);
}

/**
 * 지원사업 목록. **조회만 한다** — `refresh` 옵션은 없앴다 (N1 · S8).
 *
 * 다시 받아 오는 것은 `getBusinessOpportunities({ refresh: true })` 가 POST 로 처리한다.
 * GET 에 `refresh` 를 실으면 백엔드가 무시하고 응답에 `refresh_ignored: true` 를 붙인다.
 */
export function getSupportPrograms(options: { organizationId?: string } = {}): Promise<SupportProgramListResponse> {
  const params = new URLSearchParams();
  if (options.organizationId) params.set("organization_id", options.organizationId);
  const query = params.toString();
  return getJson<SupportProgramListResponse>(`/api/support-programs${query ? `?${query}` : ""}`);
}

/**
 * 「오늘 달라진 것」 한 줄 (0919 §4-B-1).
 *
 * **실호출을 하지 않는다** — 이미 받아 둔 목록에서만 센다. 그래서 응답의 `fetched_at`
 * (마지막으로 받아온 시각)을 화면에 반드시 함께 적는다.
 */
export function getTodayDigest(organizationId?: string): Promise<TodayDigest> {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  const query = params.toString();
  return getJson<TodayDigest>(`/api/dashboard/today${query ? `?${query}` : ""}`);
}

/**
 * 검토 중인 공고 — 손댄 흔적이 있는 것만 (0919 §4-B-3).
 *
 * **실호출을 하지 않는다.** 「내 것 먼저」의 기준은 서명된 신원이라 여기서 넘기지 않는다.
 */
export function getReviewQueue(organizationId?: string): Promise<ReviewQueue> {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  const query = params.toString();
  return getJson<ReviewQueue>(`/api/review-queue${query ? `?${query}` : ""}`);
}

export function getTemplates(): Promise<TemplateListResponse> {
  return getJson<TemplateListResponse>("/api/templates");
}

export function renderTemplate(
  templateId: string,
  procurementId: string,
  manual: Record<string, string> = {},
  ctx?: AnalysisContextParams | null,
): Promise<TemplateRenderResult> {
  return postJson<TemplateRenderResult>("/api/templates/render", {
    template_id: templateId,
    procurement_id: procurementId,
    manual,
    ...ctxBody(ctx),
  });
}

/** 렌더링한 한글 서식(HWPX) 파일 주소 (download_path는 backend가 주며 회사·범위 쿼리가 이미 붙어 있다). */
export function exportDownloadUrl(downloadPath: string): string {
  return `${BACKEND_URL}${downloadPath}`;
}

export interface ItemCorrectionBody {
  reviewer: string;
  review_status: "confirmed" | "corrected" | "rejected";
  item_type?: string;
  requirement_type?: "mandatory" | "optional";
  category?: string;
  title?: string;
  content?: string;
  page?: number;
  note?: string | null;
}

export interface ItemCorrectionResponse {
  item: Requirement;
  item_counts: Record<string, number>;
}

/** 담당자 정정 — 원본 추출 파일은 그대로 두고 이력으로 쌓인다. */
export function correctRfpItem(
  procurementId: string,
  requirementId: string,
  body: ItemCorrectionBody,
): Promise<ItemCorrectionResponse> {
  return putJson<ItemCorrectionResponse>(`/api/rfp/${enc(procurementId)}/items/${enc(requirementId)}`, body);
}

export interface ItemPerformanceMatch {
  procurement_id: string;
  organization_id?: string;
  evidence_scope?: string;
  requirement_id: string;
  is_performance_text: boolean;
  report: import("@/types/gate").PerformanceMatchReport;
}

/** 항목 문장의 실적 조건을 **선택한 회사의** 실적 원장(외부 가능 행)과 대조한다 — 힌트이며 판정이 아니다. */
export function getItemPerformanceMatch(
  procurementId: string,
  requirementId: string,
  ctx?: AnalysisContextParams | null,
): Promise<ItemPerformanceMatch> {
  return getJson<ItemPerformanceMatch>(`/api/rfp/${enc(procurementId)}/items/${enc(requirementId)}/performance-match${ctxQuery(ctx)}`);
}

/** 사람이 확정한 항목만 담은 Gold JSON 주소. 확정 항목이 없으면 422. */
/** 사업계획서 초안 내려받기 주소 (25차 §4-E) — 양식 순서 그대로 · **DOCX 만**(HWPX 는 28차 담당자 결정으로 없앰). */
/** 사업계획서 내려받기 주소 — DOCX · PDF × 제출용 · 검토용 (29차 §3-D · 기본 제출용 DOCX). */
export function planDraftExportUrl(
  programId: string,
  organizationId?: string,
  options: { format?: "docx" | "pdf"; variant?: "submit" | "review" } = {},
): string {
  const params = new URLSearchParams({ format: options.format ?? "docx", variant: options.variant ?? "submit" });
  if (organizationId) params.set("organization_id", organizationId);
  return `${BACKEND_URL}/api/support-programs/${enc(programId)}/plan-draft/export?${params.toString()}`;
}

/** 과제소개서([별첨 1]) — 첨부가 있는가 · 받아 두었는가 (30차 §3-A). */
export interface SupportAnnexView {
  attachment: { name: string; ext: string | null } | null;
  record: { status: "text" | "image" | "failed"; file_name: string | null; pages: number; chars: number; downloaded_at: string | null; note: string | null } | null;
  running: boolean;
}

export function getSupportAnnex(programId: string): Promise<SupportAnnexView> {
  return getJson<SupportAnnexView>(`/api/support-programs/${enc(programId)}/annex`);
}

/** 「과제소개서 받기」 — 기업마당에서 파일 1개(누를 때만). */
export function fetchSupportAnnex(programId: string): Promise<SupportAnnexView> {
  return postJson<SupportAnnexView>(`/api/support-programs/${enc(programId)}/annex`, {});
}

/** PDF 를 만들 수 있는가 — Edge/Chrome · Word 가 있는지(서버가 파일만 본다 · 29차 §3-D). 한 번 읽어 둔다. */
let pdfStatusPromise: Promise<{ available: boolean; method: string | null; reason: string | null }> | null = null;
export function getPlanPdfStatus(): Promise<{ available: boolean; method: string | null; reason: string | null }> {
  pdfStatusPromise ??= getJson<{ available: boolean; method: string | null; reason: string | null }>("/api/plan-drafts/pdf-status").catch((error: unknown) => {
    pdfStatusPromise = null;
    throw error;
  });
  return pdfStatusPromise;
}

/**
 * 사업기회 목록 내려받기 주소 (0921 §4-D-4).
 *
 * 검수자가 손으로 만든 `apply_candidates.md/.csv` 와 같은 열이다. 화면이 보고 있는 것과
 * **같은 조건**을 그대로 넘겨야 파일과 화면이 갈리지 않는다.
 */
export function opportunityExportUrl(query: OpportunityQuery & { format: "md" | "csv" | "xlsx" | "brief" }): string {
  const params = new URLSearchParams({ format: query.format });
  if (query.organizationId) params.set("organization_id", query.organizationId);
  if (query.source && query.source !== "all") params.set("source", query.source);
  if (query.days !== undefined) params.set("days", String(query.days));
  if (query.sort) params.set("sort", query.sort);
  if (query.includeClosed) params.set("include_closed", "true");
  if (query.includeBlocked) params.set("include_blocked", "true");
  return `${BACKEND_URL}/api/business-opportunities/export?${params.toString()}`;
}

/**
 * 저장해 둔 엑셀 이력 (0924 §4-C-2).
 *
 * 내보낼 때 같은 워크북을 회사 폴더에 한 벌 남긴다. 「지난주에 보낸 표가 어떤 조건이었나」
 * 를 나중에 알 수 있어야 해서다. 조회만 한다.
 */
export function getSavedExports(query: { organizationId?: string } = {}): Promise<SavedExportList> {
  const params = new URLSearchParams();
  if (query.organizationId) params.set("organization_id", query.organizationId);
  const suffix = params.toString();
  return getJson<SavedExportList>(`/api/business-opportunities/exports${suffix ? `?${suffix}` : ""}`);
}

/** 저장해 둔 엑셀을 다시 내려받는 주소. 이력에 없는 이름은 404 다. */
export function savedExportUrl(name: string, organizationId?: string): string {
  const params = new URLSearchParams();
  if (organizationId) params.set("organization_id", organizationId);
  const suffix = params.toString();
  return `${BACKEND_URL}/api/business-opportunities/exports/${enc(name)}${suffix ? `?${suffix}` : ""}`;
}

/** 갭 리포트 — 「무엇을 갖추면 몇 건이 열리는가」 (0921 §4-B). 조회만 한다. */
export function getEligibilityGaps(query: { organizationId?: string; days?: number } = {}): Promise<EligibilityGapReport> {
  const params = new URLSearchParams();
  if (query.organizationId) params.set("organization_id", query.organizationId);
  if (query.days !== undefined) params.set("days", String(query.days));
  const suffix = params.toString();
  return getJson<EligibilityGapReport>(`/api/eligibility/gaps${suffix ? `?${suffix}` : ""}`);
}

export function goldExportUrl(procurementId: string, format: "json" | "csv" = "json"): string {
  return `${BACKEND_URL}/api/exports/gold/${enc(procurementId)}${format === "csv" ? "?format=csv" : ""}`;
}

// ---------------------------------------------------------------------------
// 최근 활동 (감사 기록) — 관리자 전용
// ---------------------------------------------------------------------------

/**
 * 쓰기 요청 기록 조회. 백엔드가 **관리자만** 통과시킨다 (계약서 6장).
 *
 * 응답은 `{entries, count, limit}` 이고 최신순이다 — 실제 응답으로 확인했다.
 * 예전에는 봉투 키를 여섯 가지로 추측했는데, 그러면 어느 것이 진짜인지 아무도 모르는
 * 상태가 남는다. 하나로 못박고, 모양이 다르면 빈 배열을 돌려 화면이 「비어 있음」이 되게 한다.
 */
export async function getAuditLog(limit = 50): Promise<import("@/types/audit").AuditLogEntry[]> {
  const body = await getJson<{ entries?: unknown }>(
    `/api/audit-log?limit=${encodeURIComponent(String(limit))}`,
  );
  const entries = body?.entries;
  return Array.isArray(entries) ? (entries as import("@/types/audit").AuditLogEntry[]) : [];
}

// ---------------------------------------------------------------------------
// 공고 직접 넣기 · 확인 전 후보함 · 오늘 열어 본 곳 (38차 §3-E) — 판정 · 순위는 통합 목록(source=manual)이 한다
// ---------------------------------------------------------------------------

const orgQuery = (organizationId: string) => `?organization_id=${enc(organizationId)}`;

export function listManualNotices(organizationId: string): Promise<ManualNotice[]> {
  return getJson<ManualNotice[]>(`/api/manual-notices${orgQuery(organizationId)}`);
}

export function createManualNotice(organizationId: string, body: ManualNoticeInput): Promise<ManualSaveResult> {
  return postJson<ManualSaveResult>(`/api/manual-notices${orgQuery(organizationId)}`, body);
}

export function updateManualNotice(
  organizationId: string,
  noticeId: string,
  body: ManualNoticeInput,
  expectedUpdatedAt?: string | null,
): Promise<ManualNotice> {
  // 43차 M25 — 폼을 연 때 읽은 시각. 그사이 남이 고쳤으면 409(옛 폼이 남의 마감 고침을 되돌렸다)
  const expected = expectedUpdatedAt ? `&expected_updated_at=${enc(expectedUpdatedAt)}` : "";
  return putJson<ManualNotice>(`/api/manual-notices/${enc(noticeId)}${orgQuery(organizationId)}${expected}`, body);
}

/** 「원문 확인함 — 가능으로」(44차 M6) — 규칙에 불가 줄이 있으면 422 · 그사이 남이 고쳤으면 409. */
export function setManualHumanPass(
  organizationId: string,
  noticeId: string,
  body: { reason: string; by: string },
  expectedUpdatedAt?: string | null,
): Promise<ManualNotice> {
  const expected = expectedUpdatedAt ? `&expected_updated_at=${enc(expectedUpdatedAt)}` : "";
  return putJson<ManualNotice>(`/api/manual-notices/${enc(noticeId)}/human-pass${orgQuery(organizationId)}${expected}`, body);
}

/** 「가능」 되돌리기(44차 M6). */
export function clearManualHumanPass(organizationId: string, noticeId: string, by: string, expectedUpdatedAt?: string | null): Promise<ManualNotice> {
  const expected = expectedUpdatedAt ? `&expected_updated_at=${enc(expectedUpdatedAt)}` : "";
  return request<ManualNotice>(`/api/manual-notices/${enc(noticeId)}/human-pass${orgQuery(organizationId)}&by=${enc(by)}${expected}`, { method: "DELETE" });
}

export function deleteManualNotice(organizationId: string, noticeId: string): Promise<void> {
  return deleteRequest(`/api/manual-notices/${enc(noticeId)}${orgQuery(organizationId)}`);
}

export function uploadManualDocument(organizationId: string, noticeId: string, file: File): Promise<ManualNotice> {
  const form = new FormData();
  form.append("file", file);
  return request<ManualNotice>(`/api/manual-notices/${enc(noticeId)}/document${orgQuery(organizationId)}`, { method: "POST", body: form });
}

export function getNoticeInbox(organizationId: string): Promise<InboxEntry[]> {
  return getJson<InboxEntry[]>(`/api/notice-inbox${orgQuery(organizationId)}`);
}

export function pasteNoticeInbox(organizationId: string, text: string, preview = false): Promise<InboxPasteResult> {
  // 43차 N19 — 미리 보기(저장하지 않음)와 넣기를 나눈다
  const query = orgQuery(organizationId);
  const sep = query ? "&" : "?";
  return postJson<InboxPasteResult>(`/api/notice-inbox/paste${query}${preview ? `${sep}preview=true` : ""}`, { text });
}

export function discardInboxEntry(organizationId: string, entryId: string, reason: string): Promise<InboxEntry> {
  return postJson<InboxEntry>(`/api/notice-inbox/${enc(entryId)}/discard${orgQuery(organizationId)}`, { reason });
}

export function getWatchlist(organizationId: string): Promise<WatchSite[]> {
  return getJson<WatchSite[]>(`/api/watchlist${orgQuery(organizationId)}`);
}

export function saveWatchlist(organizationId: string, sites: WatchSiteInput[], base?: WatchSiteInput[]): Promise<WatchSite[]> {
  // 43차 M25 — `base` 는 고치기를 시작할 때 읽은 목록. 그사이 남이 바꿨으면 409(남이 더한 곳을 지우지 않게)
  return putJson<WatchSite[]>(`/api/watchlist${orgQuery(organizationId)}`, base ? { sites, base } : { sites });
}

/** 「열기」를 누른 시각만 적는다 — 서버는 그 사이트를 읽지 않는다. */
export function markWatchOpened(organizationId: string, siteId: string): Promise<WatchSite> {
  return postJson<WatchSite>(`/api/watchlist/${enc(siteId)}/opened${orgQuery(organizationId)}`, {});
}
