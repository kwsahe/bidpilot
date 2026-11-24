"use client";

/**
 * 회사정보·수행근거 — 여러 회사를 등록하고, 회사별로 회사자료를 등록·검토·승인·색인하는 화면.
 *
 * 용어: 모델을 "학습"시키는 것이 아니라 **등록 · 분석 · 승인 · 근거로 사용**이다.
 *   («학습»이라고 적으면 담당자는 올리기만 하면 AI가 알아서 익힌다고 읽는다. 실제로는 담당자가
 *    채택·승인한 문단만 색인에 들어가고, 그것만 공고 분석의 근거가 된다.)
 * 흐름: 회사 생성 → 기본정보 → 자료 업로드 → 텍스트 추출 → 후보 문단 채택/제외 → 근거 등록(승인) → 색인 갱신 → 테스트 검색 → 완료.
 * - 하나의 공고 분석은 하나의 회사에 고정된다. 여기서 고른 회사가 Mission Control 분석의 근거 범위가 된다.
 * - 실제 자료는 내부 전용(data/private/organizations, Git 제외)이며 합성 자료와 자동으로 섞이지 않는다.
 * - 임베딩 키가 없으면 "승인 · 색인 대기"로 정직하게 남긴다. 가짜 색인을 만들지 않는다.
 * - 다른 회사의 자료는 이 화면에 절대 나타나지 않는다 (조직별 저장소·API).
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { describeFailure } from "@/lib/errors";
import { clearDraft, loadDraft, saveDraft } from "@/lib/unsavedGuard";
import { useDeploymentMode } from "@/lib/useDeploymentMode";

import BidQualificationCard from "@/components/company/BidQualificationCard";
import PlanGeneralCard from "@/components/company/PlanGeneralCard";
import { keepSelectedDocument } from "@/components/company/documentSelection";
import AppShell from "@/components/ui/AppShell";
import { OrganizationPicker } from "@/components/ui/OrganizationPicker";
import { Badge, Button, EmptyState, InlineAlert, KpiCard, LoadingState, SectionHeader } from "@/components/ui/primitives";
import { SourceBadge } from "@/components/ui/SourceBadge";
import {
  ApiError,
  approveOrganizationDocument,
  createOrganization,
  deleteOrganizationDocument,
  getAuditLog,
  getLedgerProfiles,
  getLedgerSummary,
  getOrganizationDocument,
  getOrganizationDocumentUsage,
  getOrganizationProfile,
  importLedger,
  inspectLedger,
  listOrganizationDocuments,
  previewLedger,
  rebuildOrganizationIndex,
  reextractOrganizationDocument,
  retireOrganizationDocument,
  reviewOrganizationCandidates,
  isStaleWrite,
  saveOrganizationProfile,
  searchOrganizationIndex,
  uploadOrganizationDocument,
} from "@/lib/api";
import StaleReload from "@/components/ui/StaleReload";
import { formatDateTime } from "@/lib/cosmos/format";
import { SCREEN_NAMES, VIEW_RELOAD_TERM } from "@/lib/terms";
import { isDemoNoticeId, isSupportProgramId, readSelection, readSelectionServer, subscribeSelection } from "@/lib/selection";
import { COSMOS_COLORS, type Tone } from "@/lib/cosmos/theme";
import { ROLE_LABELS, currentUserName, useCurrentUser } from "@/lib/currentUser";
import { requestConsent } from "@/lib/consentPrompt";
import { actionLabel, resultText, visibleActivity } from "@/lib/activityLog";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import type { AuditLogEntry } from "@/types/audit";
import { DEFAULT_ORGANIZATION_ID, findOrganization, setOrganizationId, useOrganizationId, useOrganizations } from "@/lib/organization";
import {
  DATA_CLASS_LABELS,
  DOCUMENT_STATUS_LABELS,
  OUT_OF_PERIOD_LABEL,
  documentStatusLabel,
  withinValidity,
  type CompanyDocument,
  type CompanyDocumentDetail,
  type DataClass,
  type DocumentListResponse,
  type DocumentStatus,
  type Scope,
  type UsageResponse,
} from "@/types/company";
import type {
  IndexSearchResult,
  LedgerImportProfile,
  LedgerImportResult,
  LedgerInspectResult,
  LedgerPreviewResult,
  LedgerSummary,
  OrganizationListResponse,
  OrganizationProfile,
  OrganizationSummary,
  ProfileSource,
} from "@/types/organization";

const subscribeNever = () => () => {};
const getHydrated = () => true;
const getHydratedServer = () => false;

/** 이 PC 의 오늘 「YYYY-MM-DD」 — 유효기간 비교용. */
function localToday(): string {
  return new Date().toLocaleDateString("sv-SE");
}

const STATUS_TONE: Record<DocumentStatus, Tone> = {
  pending: "muted",
  extracting: "info",
  review: "warn",
  approved: "ok",
  indexing: "info",
  indexed: "pass",
  failed: "fail",
  rejected: "muted",
  retired: "muted",
};

const DOC_TYPES = ["회사소개", "수행실적", "인력정보", "인증", "교육 커리큘럼", "운영 매뉴얼", "계약 증빙", "제안서", "기타"];

const LEDGER_FIELD_LABELS: Record<string, string> = {
  seq: "연번 (필수)",
  year: "연도",
  period: "기간",
  field: "분야",
  title: "사업·과제명 (필수)",
  agency: "주관·발주기관",
  summary: "주요 내용·성과",
  amount: "금액",
  amount_basis: "금액 구분",
  status: "상태 (필수)",
  external_use: "외부 사용 가능 (필수)",
  evidence_note: "증빙·주의사항",
};

const inputClass =
  "mc-focus min-h-9 w-full rounded-lg border border-cosmos-border bg-cosmos-elevated/70 px-3 text-[13px] text-cosmos-text placeholder:text-cosmos-muted";

/** 화면에 찍을 한 문장. 서버가 준 한국어 사유가 있으면 그것이 이긴다 (예: AI 검색 설정 없음 503). */
function describe(error: unknown, fallback: string): string {
  return describeFailure(error, fallback);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const dataClassTone = (dataClass: DataClass): Tone => (dataClass === "synthetic" ? "demo" : dataClass === "anonymized" ? "info" : "ok");

/**
 * AI 검색 이름표 — 「설정 없음」은 키가 없을 때만 맞고, 시연 고정 모드(키 있음 · 꺼 둠)에서는 옆 사유
 * 「꺼져 있습니다」와 어긋났다 (CMP-26). 「꺼짐」은 두 경우 모두 참이다 — 왜 꺼졌는지는 서버 사유가 말한다.
 */
const AI_SEARCH_ON = "AI 검색 켜짐";
const AI_SEARCH_OFF = "AI 검색 꺼짐";

/** 프로필 출처를 사람 말로 — 프로필 카드와 회사 레코드 줄이 같이 쓴다 (CMP-29: 「프로필 출처 file」). */
const profileSourceLabel = (source: ProfileSource): string =>
  source === "file" ? "담당자 입력" : source === "legacy_file" ? "기존 파일(이관 전)" : "예시 값";

/**
 * 회사 등급과 다른 등급의 문서는 매칭에서 조용히 빠진다(합성 회사는 합성 문단만 · 실제 자료 회사는 실제·비식별 문단만).
 * 고를 때 그 사실을 말한다 (CMP-06).
 */
function classMismatchNote(organizationClass: DataClass | null, chosen: DataClass): string | null {
  if (!organizationClass || (organizationClass === "synthetic") === (chosen === "synthetic")) return null;
  return organizationClass === "synthetic"
    ? "이 회사는 가상 예시 회사라 실제 자료 등급 문서는 분석에 쓰이지 않습니다."
    : "이 회사는 실제 자료 회사라 가상 예시 자료 등급 문서는 분석에 쓰이지 않습니다.";
}

/**
 * 요약이 새로 내려주는 「승인」의 조각들.
 *
 * 예전에는 요약의 `approved_document_count`(= 승인 + 색인 완료) 하나뿐이라, 같은 화면의
 * 문서 목록 `counts.approved`(= 색인 «전»만)와 둘 다 「승인 N건」이라 적혀 서로 다른 수가 떴다.
 * 백엔드가 조각을 갈라 내려주므로(`OrganizationSummary`) 라벨도 갈라 쓴다.
 * 공용 타입(`src/types/organization.ts`)에는 아직 없어 여기서 좁게 선언한다 — 그 파일은 다른 작업자 담당이다.
 */
type SummaryCounts = {
  indexed_document_count?: number;
  approved_not_indexed_document_count?: number;
  active_evidence_document_count?: number;
  document_registry_note?: string | null;
};

const counted = (summary: OrganizationSummary | null): SummaryCounts => (summary ?? {}) as SummaryCounts;

// ---------------------------------------------------------------------------
// 회사 정보 · 새 회사 등록 (회사 선택기는 머리 오른쪽 맨 앞 — 모든 화면이 같은 부품 · 27차 UNI-07)
// ---------------------------------------------------------------------------

function OrganizationBar({
  list,
  error,
  organizationId,
  onCreate,
  readOnly,
}: {
  list: OrganizationListResponse | null;
  error: string | null;
  organizationId: string;
  onCreate: () => void;
  readOnly: boolean;
}) {
  const deploymentMode = useDeploymentMode();
  // 45차 M4 — 새 회사 등록은 관리자만(서버가 그렇게 막는다 · 편집자에게 켜져 있었다). 로그인 없는 로컬은 그대로
  const me = useCurrentUser();
  const notAdmin = me !== null && me.role !== "admin";
  const current = findOrganization(list, organizationId);
  const name = current?.organization.display_name ?? (organizationId === DEFAULT_ORGANIZATION_ID ? "주식회사 샘플에듀" : organizationId);
  return (
    <section className="mc-panel flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3" aria-label="회사" data-tour="company-organization">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        <span className="shrink-0 text-[12px] text-cosmos-muted">회사</span>
        <p className="min-w-0 max-w-full truncate text-[16px] font-semibold text-cosmos-text" title={`${name} · ${organizationId}`}>
          {name}
        </p>
        <span className="font-mono text-[12px] text-cosmos-muted" title="회사 코드 — 자료 폴더와 주소에 쓰는 영구 식별자입니다 (영문 표기 organization_id)">
          {organizationId}
        </span>
        {current && (
          <>
            <Badge tone={dataClassTone(current.organization.data_class)}>{DATA_CLASS_LABELS[current.organization.data_class]}</Badge>
            {/* KPI 「공개 데모 사용」과 같은 값을 본다 — 실제 자료 회사는 공개 승인해도 공개되지 않는다 (CMP-16). */}
            <Badge tone={current.usable_in_public_demo ? "pass" : "muted"} title="공개 배포본(가상 예시)에 노출해도 되는지 — 가상 예시 자료이고 공개 승인한 회사만 「공개 가능」">
              {current.usable_in_public_demo ? "공개 가능" : "내부 전용"}
            </Badge>
            {current.organization.status !== "active" && <Badge tone="fail">비활성</Badge>}
          </>
        )}
        {list?.local_admin_mode && (
          <Badge tone="info" title="인증 없이 로컬에서 실행 중 — 로그인한 배포에서는 편집자·관리자만 바꿀 수 있습니다">
            로컬 관리자 모드
          </Badge>
        )}
        {list?.public_demo_mode && <Badge tone="demo" title="공개 배포 모드 — 생성·업로드·승인이 막혀 있고 가상 예시 자료만 씁니다">공개 배포 모드</Badge>}
        {/* 지금 무엇으로 돌고 있는지 사실대로 적는다. 없는 권한 체계를 있는 것처럼 쓰지 않는다. */}
        {deploymentMode?.backend === "proxy" && (
          <Badge
            tone="pass"
            title="회사 서버의 실백엔드에 연결돼 있고, 승인된 내부자료만 분석에 사용합니다."
          >
            사내 배포 · 내부자료 사용
          </Badge>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" onClick={onCreate} disabled={readOnly || notAdmin} title={notAdmin ? "새 회사 등록은 관리자만 합니다" : readOnly ? "공개 배포 모드 · 열람자는 회사를 등록할 수 없습니다" : undefined}>
          새 회사 등록
        </Button>
      </div>
      {error && (
        <p className="basis-full text-[12px] text-cosmos-amber" role="status">
          {error} — 기본 회사({DEFAULT_ORGANIZATION_ID})로 표시합니다.
        </p>
      )}
      <p className="basis-full text-[12px] leading-4 text-cosmos-muted">
        하나의 공고 분석은 하나의 회사에 고정됩니다. 회사를 바꾸면 입찰 분석의 제안서·제출 전 점검·조건 결과는 새 회사 기준으로 다시 실행해야 하며, 다른 회사의 자료는 이 화면에 보이지 않습니다.
      </p>
    </section>
  );
}

function CreateOrganizationDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [form, setForm] = useState({ display_name: "", legal_name: "", organization_id: "", data_class: "real" as DataClass, approved_for_public: false, created_by: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!form.display_name.trim() || !form.created_by.trim()) {
      setError("회사명과 등록자는 필수입니다.");
      return;
    }
    if (form.organization_id && !/^org-(?!-)(?:[a-z0-9]+-?){2,48}(?<!-)$/.test(form.organization_id)) {
      setError("회사 코드는 org- 로 시작하는 영문 소문자·숫자·하이픈이어야 합니다 (예: org-demo-company). 비우면 자동 생성됩니다.");
      return;
    }
    setBusy(true);
    setError(null);
    createOrganization({
      display_name: form.display_name.trim(),
      legal_name: form.legal_name.trim() || null,
      organization_id: form.organization_id.trim() || null,
      data_class: form.data_class,
      approved_for_public: form.approved_for_public,
      created_by: form.created_by.trim(),
      note: form.note.trim() || null,
    })
      .then((created) => onCreated(created.organization_id))
      .catch((e: unknown) => setError(describe(e, "회사를 등록하지 못했습니다.")))
      .finally(() => setBusy(false));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-cosmos-bg/70 p-2 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-org-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="mc-panel flex w-full max-w-[560px] flex-col gap-3 p-4">
        <div className="flex items-center gap-2">
          <h2 id="create-org-title" className="text-[15px] font-semibold text-cosmos-text">새 회사 등록</h2>
          <span className="text-[12px] text-cosmos-muted">1단계 · 회사 생성</span>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={onClose} aria-label="닫기">
            ✕
          </Button>
        </div>
        {error && <InlineAlert tone="fail">{error}</InlineAlert>}
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted sm:col-span-2">
            회사명 (필수)
            {/* 열리면 첫 칸에 초점 — 키보드로 연 사람이 대화상자 밖에서 헤매지 않게 (CMP-31). */}
            <input autoFocus className={inputClass} value={form.display_name} onChange={(e) => setForm((p) => ({ ...p, display_name: e.target.value }))} placeholder="예: 데모교육연구소" />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
            법인명
            <input className={inputClass} value={form.legal_name} onChange={(e) => setForm((p) => ({ ...p, legal_name: e.target.value }))} />
          </label>
          {/* 저장 필드 이름(organization_id)은 담당자에게 보여 줄 말이 아니다 — 영문 원어는 툴팁으로만 남긴다. */}
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted" title="영문 표기 organization_id — 자료 폴더와 주소에 쓰는 영구 식별자">
            회사 코드 (비우면 자동)
            <input className={`${inputClass} font-mono`} value={form.organization_id} onChange={(e) => setForm((p) => ({ ...p, organization_id: e.target.value }))} placeholder="org-demo-company" />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
            자료 등급
            <select
              className={inputClass}
              value={form.data_class}
              onChange={(e) => {
                const dataClass = e.target.value as DataClass;
                // 실제 자료는 공개하지 않는다 — 체크가 남으면 막대는 「공개 가능」, KPI 는 「불가」가 같이 떴다 (CMP-16).
                setForm((p) => ({ ...p, data_class: dataClass, approved_for_public: dataClass === "synthetic" ? p.approved_for_public : false }));
              }}
            >
              {(Object.keys(DATA_CLASS_LABELS) as DataClass[]).map((k) => (
                <option key={k} value={k}>
                  {DATA_CLASS_LABELS[k]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
            등록자 (필수)
            <input className={inputClass} value={form.created_by} onChange={(e) => setForm((p) => ({ ...p, created_by: e.target.value }))} placeholder="담당자 이름" />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted sm:col-span-2">
            메모
            <input className={inputClass} value={form.note} onChange={(e) => setForm((p) => ({ ...p, note: e.target.value }))} />
          </label>
          <label className="flex items-center gap-2 text-[12.5px] text-cosmos-secondary sm:col-span-2">
            <input
              type="checkbox"
              checked={form.approved_for_public}
              disabled={form.data_class !== "synthetic"}
              onChange={(e) => setForm((p) => ({ ...p, approved_for_public: e.target.checked }))}
            />
            공개 데모에 사용 허용 {form.data_class === "synthetic" ? "(가상 예시 회사만)" : "— 가상 예시 회사만 고를 수 있습니다. 실제 자료는 공개 데모에 쓰지 않습니다."}
          </label>
        </div>
        <p className="text-[12px] leading-4 text-cosmos-muted">
          만든 뒤 바로 「기본정보」를 저장하세요 — 저장 전에는 사업영역 · 주요 고객 · 활동 지역에 예시 값이 들어 있고 참가 가능 여부(지역) 판정에도 쓰입니다. 그다음 자료를 올려 쓸 문장을 고르면 근거가 됩니다. 사업자등록번호 · 대표자 같은 확인되지 않은 정보는 시스템이 채우지 않습니다. 입찰을 하려면 「입찰 자격 자료」에 나라장터 등록 업종 코드도 적어 두세요.
        </p>
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button size="sm" variant="primary" disabled={busy} onClick={submit} aria-busy={busy}>
            {busy ? "등록 중…" : "회사 생성"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 회사 요약 · 등록 단계
// ---------------------------------------------------------------------------


/**
 * 회사자료 화면 맨 위 — 「지금 무엇을 해야 하는가」.
 *
 * 예전에는 8단계 진행 막대와 숫자 카드만 있었다. 숫자는 상태를 말하지만 «다음 행동»을
 * 말하지 않아서, 검토 필요 7건과 실패 1건이 화면 아래 목록에 묻혀 있었다.
 * 여기서는 행동이 필요한 것만 골라 버튼과 함께 올린다.
 */
function NextActions({
  list,
  summary,
  onPick,
}: {
  list: DocumentListResponse | null;
  summary: OrganizationSummary | null;
  onPick: (documentId: string) => void;
}) {
  const docs = list?.documents ?? [];
  const needsReview = docs.filter((d) => d.status === "review");
  const failed = docs.filter((d) => d.status === "failed");
  // 「사용 중」은 유효기간 안일 때만(31차 R30-32)
  const today = localToday();
  const indexed = docs.filter((d) => d.status === "indexed" && withinValidity(d.metadata, today));
  const approvedChunks = summary?.index_chunk_count ?? 0;

  if (docs.length === 0) return null;

  const rows: Array<{ tone: Tone; label: string; detail: string; action?: { label: string; onClick: () => void } }> = [];
  if (failed.length > 0) {
    rows.push({
      tone: "fail",
      label: `글자 읽기 실패 ${failed.length}건`,
      detail: failed.map((d) => d.file_name).slice(0, 2).join(", "),
      action: { label: "실패 원인 보기", onClick: () => onPick(failed[0].id) },
    });
  }
  if (needsReview.length > 0) {
    rows.push({
      tone: "warn",
      label: `문장 고르기 필요 ${needsReview.length}건`,
      detail: "제안서에 쓸 문장을 고르면 근거가 됩니다",
      action: { label: "고르기 시작", onClick: () => onPick(needsReview[0].id) },
    });
  }
  rows.push({
    tone: approvedChunks > 0 ? "pass" : "muted",
    // 색인 파일의 문단 수다 — 비활성 처리한 문서의 문단도 새 색인 전까지 남는다 (CMP-11). 이름을 그 사실대로.
    label: `AI가 찾는 문장 ${approvedChunks}개`,
    detail: `사용 중인 문서 ${indexed.length}건 · 올린 문서 ${docs.length}건`,
  });

  return (
    <section className="mc-panel flex flex-col gap-2 p-3" aria-label="지금 할 일">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">지금 할 일</h2>
      <ul className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <li key={row.label} className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <Badge tone={row.tone}>{row.label}</Badge>
            <span className="min-w-0 flex-1 truncate text-[12.5px] text-cosmos-secondary">{row.detail}</span>
            {row.action && (
              <Button size="sm" variant="secondary" onClick={row.action.onClick}>
                {row.action.label}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function RegistrationSteps({ summary, list, profile, searchTried, loading }: { summary: OrganizationSummary | null; list: DocumentListResponse | null; profile: OrganizationProfile | null; searchTried: boolean; loading: boolean }) {
  const docs = list?.documents ?? [];
  const split = counted(summary);
  const steps: Array<{ label: string; done: boolean; hint: string }> = [
    // 코드(org-…)를 적어 두면 「지금 어느 회사인가」를 담당자가 코드로 읽게 된다 — 이름을 적는다.
    { label: "회사 만들기", done: Boolean(summary), hint: summary ? summary.organization.display_name : "회사 없음" },
    { label: "기본정보 입력", done: profile?.source === "file" || profile?.source === "legacy_file", hint: profile ? (profile.source === "default_synthetic" ? "예시 값 — 저장 필요" : "저장됨") : "-" },
    { label: "자료 올리기", done: docs.length > 0, hint: `${docs.length}건` },
    { label: "글자 읽기", done: docs.some((d) => d.candidate_count > 0), hint: `뽑은 문장 ${docs.reduce((n, d) => n + d.candidate_count, 0)}개` },
    { label: "쓸 문장 고르기", done: docs.some((d) => d.approved_chunk_count > 0), hint: `고른 문장 ${docs.reduce((n, d) => n + d.approved_chunk_count, 0)}개` },
    // 「승인 N건」을 그대로 두면 아래 「등록 문서」 카드의 「승인·색인 대기 N」과 다른 수가 나란히 뜬다.
    // 요약의 approved_document_count 는 색인 완료까지 포함하므로, 무엇을 세는지 함께 적는다.
    {
      label: "근거로 등록",
      done: docs.some((d) => d.status === "approved" || d.status === "indexed"),
      hint: `등록 ${summary?.approved_document_count ?? 0}건 (사용 중 ${split.indexed_document_count ?? 0} · 검색 준비 전 ${split.approved_not_indexed_document_count ?? 0})`,
    },
    // 힌트는 색인이 «있는지» 기준 — ✓(42문단)인데 「색인 대기」라고 적어 KPI 「색인 대기 0건」과 모순이었다 (CMP-18).
    // 안내(AI 검색)를 시각보다 앞에 둔다 — 좁은 칸에서 잘리는 쪽이 안내가 아니라 시각이 되게.
    {
      label: "AI 검색 준비",
      done: Boolean(summary && summary.index_chunk_count > 0),
      hint: summary
        ? [
            summary.index_chunk_count > 0 ? `문장 ${summary.index_chunk_count}개` : "준비 전",
            summary.embedding_available ? null : "새로 준비하려면 AI 검색을 켜야 함",
            summary.index_chunk_count > 0 && summary.index_built_at ? formatDateTime(summary.index_built_at) : null,
          ]
            .filter(Boolean)
            .join(" · ")
        : "-",
    },
    { label: "찾아보기 확인", done: searchTried, hint: "아래 검색창에서 확인" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  // 45차 M1 — 회사 · 문서 목록이 오기 전에는 「1단계 회사 없음 · 0 / 8 단계 완료」가 0.3~4초 보였다
  if (loading) {
    return <LoadingState label="회사 등록 단계를 불러오는 중" rows={1} />;
  }
  return (
    <ol className="mc-panel grid grid-cols-2 gap-2 p-3 sm:grid-cols-4 xl:grid-cols-8" aria-label="회사 등록 진행 단계">
      {steps.map((s, i) => (
        <li key={s.label} className="flex min-w-0 flex-col gap-0.5 rounded-lg px-2 py-1.5" style={{ borderLeft: `2px solid ${s.done ? COSMOS_COLORS.green : COSMOS_COLORS.slate}` }}>
          <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">
            {i + 1}단계 {s.done ? "✓" : ""}
          </span>
          <span className={`text-[12.5px] font-medium ${s.done ? "text-cosmos-text" : "text-cosmos-secondary"}`}>{s.label}</span>
          {/* 두 줄까지 — 7단계 「· 새 색인은 AI 검색을 켜야 함」이 한 줄 말줄임에 숨어 title 로만 보였다 (CMP-18). */}
          <span className="line-clamp-2 break-words text-[12px] text-cosmos-muted" title={s.hint}>
            {s.hint}
          </span>
        </li>
      ))}
      <li className="col-span-full text-[12px] text-cosmos-muted">
        {doneCount === steps.length ? "등록 완료 — 이 회사의 승인 근거가 공고 요구사항과 근거 매칭에 쓰입니다." : `${doneCount} / ${steps.length} 단계 완료. 승인되지 않은 자료는 분석에 쓰이지 않습니다.`}
      </li>
    </ol>
  );
}

// ---------------------------------------------------------------------------
// 프로필
// ---------------------------------------------------------------------------

/** 저장된 프로필 → 편집 칸 값. 「취소」가 이 값으로 되돌린다 (CMP-05). */
function profileForm(profile: OrganizationProfile) {
  return {
    name: profile.name,
    business_domains: profile.business_domains.join(", "),
    target_clients: profile.target_clients.join(", "),
    preferred_regions: profile.preferred_regions.join(", "),
    certifications: profile.certifications.join(", "),
    certification_history: (profile.certification_history ?? []).join(", "),
    address: profile.address ?? "",
    phone: profile.phone ?? "",
    website: profile.website ?? "",
    founded_year: profile.founded_year ? String(profile.founded_year) : "",
    employee_count: profile.employee_count !== null ? String(profile.employee_count) : "",
    data_class: profile.data_class as DataClass,
    approved_for_public: profile.approved_for_public,
    // 43차 TEAM-03 — 수정자는 지금 로그인한 사람(지난 수정자 「system:split-tool」이 미리 채워져 그 이름으로 남았다)
    updated_by: currentUserName(),
    note: profile.note ?? "",
  };
}

function ProfileCard({ organizationId, profile, onSaved, readOnly }: { organizationId: string; profile: OrganizationProfile; onSaved: (p: OrganizationProfile) => void; readOnly: boolean }) {
  /**
   * 프로필 수정은 칸이 열두 개다. 다 채우고 저장을 누르기 전에 새로고침하거나 회사를 바꾸면
   * **전부** 말없이 사라졌다 (TASK-012). 회사별로 임시 저장하고 돌아오면 되살린다.
   *
   * 폼 전체를 JSON 한 덩어리로 넣는다 — 칸마다 키를 두면 되살릴 때 일부만 살아나
   * 「내가 뭘 고쳤더라」가 더 헷갈린다.
   */
  const draftKey = `company-profile:${organizationId}`;
  const restored = useMemo(() => {
    const raw = loadDraft(draftKey);
    if (!raw) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
    } catch {
      // 옛 형식이거나 깨진 값 — 없는 것으로 본다. 되살리기 실패가 화면을 막으면 안 된다.
      return null;
    }
  }, [draftKey]);
  // 되살릴 것이 있으면 편집 화면을 열어 둔다. 열지 않으면 「되살아났다」가 보이지 않는다.
  const [editing, setEditing] = useState(restored !== null);
  // 44차 TEAM-R36-01 — 임시 저장본은 처음 읽은 저장 시각(`_base`)과 함께 둔다. 되살려 저장해도 그사이 남의 저장을 덮지 않는다(서버 409).
  const { _base: restoredBase, ...restoredFields } = (restored ?? {}) as Record<string, unknown> & { _base?: string | null };
  const [baseAt, setBaseAt] = useState<string | null>(restored && restoredBase !== undefined ? restoredBase : profile.updated_at ?? null);
  const [stale, setStale] = useState(false);
  const [form, setForm] = useState({ ...profileForm(profile), ...restoredFields });
  // 「되살렸습니다」는 되살린 그 편집에만 — 저장·취소 뒤 다시 편집할 때는 뜨지 않는다 (CMP-05).
  const [showRestored, setShowRestored] = useState(restored !== null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const split = (value: string) => value.split(",").map((v) => v.trim()).filter(Boolean);

  // 편집 중에만 남긴다. 보기 모드의 값은 서버에 이미 있는 값이라 남길 것이 없다.
  useEffect(() => {
    if (!editing) return;
    saveDraft(draftKey, JSON.stringify({ ...form, _base: baseAt }));
  }, [editing, form, draftKey, baseAt]);

  const save = () => {
    if (!form.updated_by.trim() || !form.name.trim()) {
      setError("상호와 수정자는 필수입니다.");
      return;
    }
    // 「2015년」은 조용히 「미공개」로, 「95」는 어느 칸인지 모른 채 실패했다 — 칸 이름과 함께 막는다 (CMP-19).
    const year = form.founded_year.trim();
    if (year && (!/^\d{4}$/.test(year) || Number(year) < 1900 || Number(year) > 2100)) {
      setError("「설립연도」는 네 자리 숫자로 적어 주세요 (예: 2015 · 비우면 미공개).");
      return;
    }
    const staff = form.employee_count.trim();
    if (staff && !/^\d+$/.test(staff)) {
      setError("「상시 근로자 수(4대보험 기준 · 대표 제외)」는 숫자만 적어 주세요 (예: 12 · 비우면 미공개).");
      return;
    }
    setBusy(true);
    setError(null);
    setStale(false);
    saveOrganizationProfile(organizationId, {
      expected_updated_at: baseAt,
      name: form.name.trim(),
      business_domains: split(form.business_domains),
      target_clients: split(form.target_clients),
      preferred_regions: split(form.preferred_regions),
      certifications: split(form.certifications),
      certification_history: split(form.certification_history),
      address: form.address.trim() || null,
      phone: form.phone.trim() || null,
      website: form.website.trim() || null,
      founded_year: year ? Number(year) : null,
      employee_count: staff ? Number(staff) : null,
      data_class: form.data_class,
      approved_for_public: form.approved_for_public,
      updated_by: form.updated_by.trim(),
      note: form.note.trim() || null,
    })
      .then((saved) => {
        onSaved(saved);
        setBaseAt(saved.updated_at ?? null);
        // 저장했으므로 임시 저장본을 지운다 — 남겨 두면 다음에 열 때 편집 화면이 또 열린다.
        clearDraft(draftKey);
        setShowRestored(false);
        setEditing(false);
      })
      .catch((e: unknown) => {
        setStale(isStaleWrite(e));
        setError(describe(e, "프로필을 저장하지 못했습니다."));
      })
      .finally(() => setBusy(false));
  };

  const sourceLabel = profileSourceLabel(profile.source);

  return (
    <section className="mc-panel flex flex-col gap-3 p-4" aria-label="회사 프로필">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-cosmos-text">회사 프로필</h2>
        <span className="text-[12px] text-cosmos-muted">2단계 · 기본정보</span>
        <SourceBadge kind={profile.source === "default_synthetic" ? "demo" : "human"} label={sourceLabel} />
        <Badge tone={dataClassTone(profile.data_class)}>{DATA_CLASS_LABELS[profile.data_class]}</Badge>
        {/* 위 회사 막대의 「공개 가능/내부 전용」(실제 공개 여부)과 다른 값이다 — 프로필에 적힌 승인 표시라 이름을 가른다 (CMP-16). */}
        <Badge tone={profile.approved_for_public ? "pass" : "muted"} title="프로필에 기록된 공개 승인 — 실제 공개 여부는 위 회사 막대가 말합니다">
          {profile.approved_for_public ? "프로필 공개 승인" : "프로필 공개 미승인"}
        </Badge>
        <div className="ml-auto flex gap-1.5">
          <Button
            size="sm"
            variant={editing ? "ghost" : "secondary"}
            onClick={() => {
              if (editing) {
                // 취소는 고친 값을 버린다 — 칸에 남겨 두면 다시 「수정」할 때 버린 값이 되살아나 그대로 저장될 수 있었다 (CMP-05).
                clearDraft(draftKey);
                setForm(profileForm(profile));
                setShowRestored(false);
                setError(null);
                setStale(false);
              }
              // 고치기는 지금 저장본에서 시작한다 — 기준 시각도 지금 것으로(44차 TEAM-R36-01)
              setBaseAt(profile.updated_at ?? null);
              setEditing((v) => !v);
            }}
            disabled={readOnly}
          >
            {editing ? "취소" : "수정"}
          </Button>
          {editing && (
            <Button size="sm" variant="primary" disabled={busy} onClick={save}>
              {busy ? "저장 중…" : "저장"}
            </Button>
          )}
        </div>
      </div>
      {error && (
        <InlineAlert tone="fail">
          {error}
          {stale && <StaleReload draftKeys={[draftKey]} />}
        </InlineAlert>
      )}
      {profile.source === "default_synthetic" && (
        // 새 회사는 저장 전까지 합성 기본 프로필(사업영역·주요 고객·활동 지역)을 보여 주고, 자격 판정의 지역 규칙도 이 값을 쓴다 (CMP-04).
        <InlineAlert tone="warn" role="status">
          아직 저장한 프로필이 없어 예시 값을 보여 줍니다. 이 값이 참가 가능 여부(지역) 판정에도 쓰이니 「수정」을 눌러 우리 회사 값으로 저장하세요.
        </InlineAlert>
      )}
      {showRestored && editing && (
        <p className="text-[12px] text-cosmos-amber" role="status">
          저장하지 않은 수정이 남아 있어 되살렸습니다. 「저장」을 누르거나 「취소」로 버리세요.
          {baseAt !== (profile.updated_at ?? null) && (
            <>
              {" "}그사이 다른 사람이 저장했습니다 — 저장하면 막히니 새 값에서 고치세요.
              <StaleReload draftKeys={[draftKey]} />
            </>
          )}
        </p>
      )}
      {!editing ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
          {[
            ["상호", profile.name],
            ["사업영역", profile.business_domains.join(", ") || "미입력"],
            ["주요 고객", profile.target_clients.join(", ") || "미입력"],
            ["활동 지역", profile.preferred_regions.join(", ") || "미입력 (자격 판정의 지역 규칙이 「확인 필요」로 남습니다)"],
            ["인증(현재 유효)", profile.certifications.join(", ") || "미입력"],
            ["인증 이력", (profile.certification_history ?? []).join(", ") || "없음 · 미입력"],
            ["주소", profile.address ?? "미입력"],
            ["전화", profile.phone ?? "미입력"],
            ["설립연도 · 상시 근로자", `${profile.founded_year ?? "미공개"} · ${profile.employee_count ?? "미공개"}`],
            // 편집 칸에만 있고 보기에는 없었다 (CMP-20).
            ["웹사이트", profile.website ?? "미입력"],
            ["메모", profile.note ?? "-"],
            ["최근 수정", profile.updated_at ? `${formatDateTime(profile.updated_at)} · ${profile.updated_by ?? ""}` : "저장된 프로필 없음 (예시 값 표시)"],
          ].map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-cosmos-muted">{label}</dt>
              <dd className="min-w-0 break-words text-cosmos-text">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["name", "상호 (필수)"],
              ["business_domains", "사업영역 (쉼표로 구분)"],
              ["target_clients", "주요 고객 (쉼표)"],
              ["preferred_regions", "활동 지역 (쉼표)"],
              ["certifications", "인증 — 지금 유효한 것만 (쉼표 · 판정 · 사업계획서에 씀)"],
              ["certification_history", "인증 이력 — 지난 지정 · 만료 (쉼표 · 판정에 쓰지 않음)"],
              ["address", "주소"],
              ["phone", "전화"],
              ["website", "웹사이트"],
              ["founded_year", "설립연도 (숫자, 비우면 미공개)"],
              ["employee_count", "상시 근로자 수(4대보험 기준 · 대표 제외) — 숫자, 비우면 미공개"],
              ["updated_by", "수정자 (필수)"],
              ["note", "메모"],
            ] as Array<[keyof typeof form, string]>
          ).map(([key, label]) => (
            <label key={key} className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              {label}
              <input
                className={inputClass}
                value={String(form[key] ?? "")}
                inputMode={key === "founded_year" || key === "employee_count" ? "numeric" : undefined}
                onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
              />
            </label>
          ))}
          <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
            자료 등급
            <select className={inputClass} value={form.data_class} onChange={(e) => setForm((prev) => ({ ...prev, data_class: e.target.value as DataClass }))}>
              {(Object.keys(DATA_CLASS_LABELS) as DataClass[]).map((k) => (
                <option key={k} value={k}>
                  {DATA_CLASS_LABELS[k]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 self-end text-[12.5px] text-cosmos-secondary">
            <input type="checkbox" checked={form.approved_for_public} onChange={(e) => setForm((prev) => ({ ...prev, approved_for_public: e.target.checked }))} />
            공개 배포본에 노출 허용 (회사 승인 필요)
          </label>
        </div>
      )}
      <p className="text-[12px] leading-4 text-cosmos-muted">
        프로필은 서식 자동 채움(입찰참가신청서·회사 일반현황)과 지원사업 적합도 규칙, 자격 판정의 지역 규칙에 쓰입니다. 사업자등록번호·대표자 등 확인되지 않은 항목은 시스템이 채우지 않습니다.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 업로드
// ---------------------------------------------------------------------------

function UploadForm({
  organizationId,
  organizationDataClass,
  onUploaded,
  readOnly,
}: {
  organizationId: string;
  /** 회사 등급 — 자료 등급 기본값이 이것을 따른다. 합성 회사에 「실제 자료」가 기본이라 매칭에서 조용히 빠졌다 (CMP-06). */
  organizationDataClass: DataClass | null;
  onUploaded: (doc: CompanyDocumentDetail) => void;
  readOnly: boolean;
}) {
  const viewer = useViewerLock();
  const [file, setFile] = useState<File | null>(null);
  // 올린 뒤 파일 칸을 비운다 — 이름이 남은 채 단추만 회색이 되고, 같은 파일을 다시 고르면 반응이 없었다 (CMP-21).
  const [fileKey, setFileKey] = useState(0);
  const [docType, setDocType] = useState("수행실적");
  const [pickedClass, setPickedClass] = useState<DataClass | null>(null);
  const dataClass = pickedClass ?? organizationDataClass ?? "real";
  const mismatch = classMismatchNote(organizationDataClass, dataClass);
  const [uploader, setUploader] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    uploadOrganizationDocument(organizationId, file, { docType, dataClass, uploadedBy: uploader.trim() || undefined })
      .then((doc) => {
        onUploaded(doc);
        setFile(null);
        setFileKey((k) => k + 1);
      })
      .catch((e: unknown) => setError(describe(e, "업로드에 실패했습니다.")))
      .finally(() => setBusy(false));
  };

  return (
    <section className="mc-panel flex flex-col gap-3 p-4" aria-label="회사자료 등록">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-cosmos-text">회사자료 등록</h2>
        <span className="text-[12px] text-cosmos-muted">3~4단계 · 자료 올리기 → 글자 읽기</span>
        <span className="text-[12px] text-cosmos-muted">PDF · HWP · HWPX · DOCX · MD · TXT, 20MB 이하 · 이 회사 저장소에만 저장</span>
      </div>
      {error && <InlineAlert tone="fail">{error}</InlineAlert>}
      {readOnly && !viewer && <InlineAlert tone="demo" role="status">공개 배포 모드에서는 업로드·승인이 막혀 있습니다. 로컬 실행에서 등록하세요.</InlineAlert>}
      {viewer && <InlineAlert tone="info" role="status">{VIEWER_LOCK_LABEL} — {VIEWER_LOCK_REASON}</InlineAlert>}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted sm:col-span-2">
          파일
          <input key={fileKey} type="file" accept=".pdf,.hwp,.hwpx,.docx,.md,.txt" className={`${inputClass} py-1.5`} disabled={readOnly} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
          문서 종류
          <select className={inputClass} value={docType} onChange={(e) => setDocType(e.target.value)}>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
          자료 등급
          <select className={inputClass} value={dataClass} onChange={(e) => setPickedClass(e.target.value as DataClass)}>
            {(Object.keys(DATA_CLASS_LABELS) as DataClass[]).map((k) => (
              <option key={k} value={k}>
                {DATA_CLASS_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted sm:col-span-2">
          등록자
          <input className={inputClass} value={uploader} onChange={(e) => setUploader(e.target.value)} placeholder="담당자 이름" />
        </label>
        <div className="flex flex-wrap items-end gap-x-3 gap-y-1 sm:col-span-2">
          <Button variant="primary" disabled={!file || busy || readOnly} onClick={submit} aria-busy={busy} aria-describedby={!file && !readOnly ? "company-upload-reason" : undefined}>
            {busy ? "읽는 중…" : "올리고 글자 읽기"}
          </Button>
          {/* 왜 못 누르는지 화면 글자로 — 회색 단추만 두면 이유를 모른다 (§3-H ③). */}
          {!file && !readOnly && (
            <span id="company-upload-reason" className="text-[12px] text-cosmos-muted">
              파일을 고르면 누를 수 있습니다.
            </span>
          )}
        </div>
      </div>
      {mismatch && (
        <InlineAlert tone="warn" role="status">
          {mismatch}
        </InlineAlert>
      )}
      <p className="text-[12px] leading-4 text-cosmos-muted">
        올린 파일은 글을 뽑아 문장 후보로 보여줍니다. 담당자가 고른 문장만 근거로 등록되며, 같은 회사 안에서 같은 내용의 파일은 중복으로 거부됩니다.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 실적 원장(Excel) 변환 — 시트·열 매핑 확인 → 미리보기 → 승인 후 등록
// ---------------------------------------------------------------------------

function LedgerImportPanel({ organizationId, onChanged, readOnly }: { organizationId: string; onChanged: () => void; readOnly: boolean }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [profiles, setProfiles] = useState<LedgerImportProfile[]>([]);
  const [summary, setSummary] = useState<LedgerSummary | null>(null);
  const [inspect, setInspect] = useState<LedgerInspectResult | null>(null);
  const [sheet, setSheet] = useState("");
  const [profileId, setProfileId] = useState("");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [approvedValues, setApprovedValues] = useState("");
  const [completedStatuses, setCompletedStatuses] = useState("");
  const [amountUnit, setAmountUnit] = useState("");
  const [preview, setPreview] = useState<LedgerPreviewResult | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [approve, setApprove] = useState(false);
  const [result, setResult] = useState<LedgerImportResult | null>(null);
  const [busy, setBusy] = useState<"inspect" | "preview" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLedgerSummary(organizationId).then((s) => {
      if (!cancelled) setSummary(s);
    }, () => {
      if (!cancelled) setSummary(null);
    });
    return () => {
      cancelled = true;
    };
  }, [organizationId, result]);

  useEffect(() => {
    if (!open || profiles.length > 0) return;
    let cancelled = false;
    getLedgerProfiles(organizationId).then((r) => {
      if (!cancelled) setProfiles(r.profiles);
    }, () => undefined);
    return () => {
      cancelled = true;
    };
  }, [open, organizationId, profiles.length]);

  const applyProfile = (id: string, list: LedgerImportProfile[] = profiles) => {
    setProfileId(id);
    const p = list.find((x) => x.profile_id === id);
    if (p) {
      setApprovedValues(p.approved_values.join(", "));
      setCompletedStatuses(p.completed_statuses.join(", "));
      setAmountUnit(p.amount_unit);
    }
  };

  const runInspect = () => {
    if (!file) return;
    setBusy("inspect");
    setError(null);
    setPreview(null);
    setResult(null);
    inspectLedger(organizationId, file)
      .then((r) => {
        setInspect(r);
        setSheet(r.suggested_sheet ?? r.sheets[0]?.name ?? "");
        setOverrides({});
        applyProfile(r.suggested_profile_id);
      })
      .catch((e: unknown) => setError(describe(e, "실적 목록 파일을 읽지 못했습니다.")))
      .finally(() => setBusy(null));
  };

  const split = (value: string) => value.split(",").map((v) => v.trim()).filter(Boolean);
  const body = () => ({
    upload_id: inspect?.upload_id ?? "",
    profile_id: profileId,
    sheet: sheet || null,
    column_overrides: overrides,
    approved_values: approvedValues.trim() ? split(approvedValues) : null,
    completed_statuses: completedStatuses.trim() ? split(completedStatuses) : null,
    amount_unit: amountUnit.trim() || null,
  });

  const runPreview = () => {
    setBusy("preview");
    setError(null);
    previewLedger(organizationId, body())
      .then(setPreview)
      .catch((e: unknown) => setError(describe(e, "미리보기에 실패했습니다.")))
      .finally(() => setBusy(null));
  };

  const runImport = () => {
    if (!reviewer.trim()) {
      setError("검토자를 입력해야 등록할 수 있습니다.");
      return;
    }
    // 등록하면 이 회사의 실적 원장 파일이 통째로 새 파일로 바뀐다 — 공고 분석의 「원장 실적 대조」가 읽는 파일이다 (CMP-03).
    if (summary?.available && !window.confirm(`기존 실적 목록(${summary.counts?.total ?? 0}행)을 이 파일로 바꿉니다. 공고 분석의 「실적 목록과 대조」가 새 실적 목록을 읽습니다. 계속할까요?`)) return;
    setBusy("import");
    setError(null);
    importLedger(organizationId, { ...body(), reviewer: reviewer.trim(), approve, source_name: file?.name ?? null })
      .then((r) => {
        setResult(r);
        onChanged();
      })
      .catch((e: unknown) => setError(describe(e, "실적 목록 등록에 실패했습니다.")))
      .finally(() => setBusy(null));
  };

  const sheetInfo = inspect?.sheets.find((s) => s.name === sheet) ?? null;
  const fieldKeys = useMemo(() => {
    const p = profiles.find((x) => x.profile_id === profileId);
    const keys = p ? Object.keys(p.columns) : Object.keys(LEDGER_FIELD_LABELS);
    return keys;
  }, [profiles, profileId]);
  const mappingOf = (key: string) => overrides[key] ?? sheetInfo?.suggested_mapping[key] ?? "";
  const missingRequired = ["seq", "title", "status", "external_use"].filter((k) => !mappingOf(k));

  return (
    <section className="mc-panel flex flex-col gap-3 p-4" aria-label="실적 목록 올리기">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-cosmos-text">실적 목록(엑셀) 올리기</h2>
        <span className="text-[12px] text-cosmos-muted">회사별 열 매핑 확인 → 미리보기 → 승인 후 근거 등록</span>
        {summary?.available ? (
          <Badge tone="ok" title={`${summary.source_file ?? ""} · 시트 ${summary.sheet ?? "-"} · 금액 단위 ${summary.amount_unit ?? "-"}`}>
            실적 목록 있음 · 외부 가능 {summary.counts?.eligible ?? 0} / 전체 {summary.counts?.total ?? 0}행
          </Badge>
        ) : (
          <Badge tone="muted">실적 목록 없음</Badge>
        )}
        <Button size="sm" variant="secondary" className="ml-auto" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "접기" : "실적 목록 올리기"}
        </Button>
      </div>
      {open && (
        <div className="flex flex-col gap-3">
          {error && <InlineAlert tone="fail">{error}</InlineAlert>}
          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              실적 목록 파일 (.xlsx)
              <input
                type="file"
                accept=".xlsx,.xlsm"
                className={`${inputClass} py-1.5`}
                disabled={readOnly}
                onChange={(e) => {
                  // 파일을 바꾸면 이전 파일의 확인 결과를 버린다 — 남겨 두면 이전 내용이 새 파일 이름·날짜로 등록됐다 (CMP-07).
                  setFile(e.target.files?.[0] ?? null);
                  setInspect(null);
                  setPreview(null);
                  setResult(null);
                }}
              />
            </label>
            <div className="flex items-end">
              <Button variant="secondary" disabled={!file || busy !== null || readOnly} onClick={runInspect} aria-busy={busy === "inspect"}>
                {busy === "inspect" ? "읽는 중…" : "시트·열 확인"}
              </Button>
            </div>
          </div>
          {inspect && (
            <>
              <p className="text-[12px] text-cosmos-secondary">{inspect.note}</p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                  시트
                  <select className={inputClass} value={sheet} onChange={(e) => { setSheet(e.target.value); setOverrides({}); setPreview(null); }}>
                    {inspect.sheets.map((s) => (
                      <option key={s.name} value={s.name}>
                        {s.name} ({s.row_count}행{s.header_row === null ? " · 머리글 못 찾음" : ""})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                  엑셀 양식(회사별)
                  <select className={inputClass} value={profileId} onChange={(e) => { applyProfile(e.target.value); setPreview(null); }}>
                    {profiles.length === 0 && <option value={profileId}>{profileId}</option>}
                    {profiles.map((p) => (
                      <option key={p.profile_id} value={p.profile_id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                  외부 사용 가능 값 (쉼표)
                  <input className={inputClass} value={approvedValues} onChange={(e) => setApprovedValues(e.target.value)} placeholder="가능" />
                </label>
                <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
                  완료 상태 값 (쉼표) · 금액 단위
                  <span className="flex gap-1">
                    <input className={inputClass} value={completedStatuses} onChange={(e) => setCompletedStatuses(e.target.value)} placeholder="완료, 확정" />
                    <input className={`${inputClass} max-w-[80px]`} value={amountUnit} onChange={(e) => setAmountUnit(e.target.value)} placeholder="천원" aria-label="금액 단위" />
                  </span>
                </label>
              </div>
              {sheetInfo && (
                <div className="flex flex-col gap-1.5">
                  <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
                    칸 맞추기(앱 칸 → 엑셀 머리글) · 상태값 {sheetInfo.status_values.slice(0, 6).join(" / ") || "-"} · 외부 사용값 {sheetInfo.external_use_values.slice(0, 6).join(" / ") || "-"}
                  </p>
                  <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
                    {fieldKeys.map((key) => (
                      <label key={key} className="flex flex-col gap-0.5 text-[12px] text-cosmos-muted">
                        {LEDGER_FIELD_LABELS[key] ?? key}
                        <select className={inputClass} value={mappingOf(key)} onChange={(e) => { setOverrides((p) => ({ ...p, [key]: e.target.value })); setPreview(null); }}>
                          <option value="">(없음)</option>
                          {sheetInfo.headers.map((h) => (
                            <option key={h} value={h}>
                              {h}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                  {missingRequired.length > 0 && <InlineAlert tone="warn" role="status">필수 열이 비어 있습니다: {missingRequired.map((k) => LEDGER_FIELD_LABELS[k] ?? k).join(", ")}. 머리글을 고르거나 다른 프로필을 선택하세요.</InlineAlert>}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="secondary" disabled={busy !== null || missingRequired.length > 0} onClick={runPreview} aria-busy={busy === "preview"}>
                  {busy === "preview" ? "계산 중…" : "미리보기"}
                </Button>
                <span className="text-[12px] text-cosmos-muted">금액은 원본 단위 그대로 보존하며 자동 환산하지 않습니다. 미완료·외부 사용 불가 행은 제외됩니다.</span>
              </div>
            </>
          )}
          {preview && (
            <div className="flex flex-col gap-2 rounded-lg border border-cosmos-border bg-cosmos-elevated/50 p-3">
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px]">
                <span className="text-cosmos-text">전체 {preview.total_rows}행</span>
                <span className="text-cosmos-green">포함 {preview.included}</span>
                <span className="text-cosmos-amber">제외 {preview.excluded}</span>
                <span className="text-cosmos-muted">시트 {preview.sheet} · 금액 단위 {preview.amount_unit}</span>
              </div>
              {Object.keys(preview.exclusion_reasons).length > 0 && (
                <p className="text-[12px] text-cosmos-secondary">
                  제외 사유: {Object.entries(preview.exclusion_reasons).map(([k, v]) => `${k} ${v}`).join(" · ")}
                </p>
              )}
              {Object.keys(preview.by_group).length > 0 && <p className="text-[12px] text-cosmos-secondary">문서 그룹: {Object.entries(preview.by_group).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>}
              {preview.warnings.map((w) => (
                <InlineAlert key={w} tone="warn" role="status">{w}</InlineAlert>
              ))}
              <div className="mc-scroll max-h-[240px] overflow-auto">
                <table className="w-full min-w-[560px] border-collapse text-[12px]" aria-label="실적 목록 미리보기">
                  <thead>
                    <tr className="text-left text-[12px] uppercase tracking-[0.1em] text-cosmos-muted">
                      <th className="px-2 py-1">행</th>
                      <th className="px-2 py-1">연번</th>
                      <th className="px-2 py-1">사업명</th>
                      <th className="px-2 py-1">상태</th>
                      <th className="px-2 py-1">외부</th>
                      <th className="px-2 py-1">판정</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.slice(0, 80).map((r) => (
                      <tr key={`${r.row_number}-${r.seq}`} className="border-t border-cosmos-border/60">
                        <td className="px-2 py-1 font-mono text-cosmos-muted">{r.row_number}</td>
                        <td className="px-2 py-1 font-mono text-cosmos-muted">{r.seq}</td>
                        <td className="max-w-[260px] truncate px-2 py-1 text-cosmos-secondary" title={r.title}>{r.title}</td>
                        <td className="px-2 py-1 text-cosmos-secondary">{r.status}</td>
                        <td className="px-2 py-1 text-cosmos-secondary">{r.external_use}</td>
                        <td className="px-2 py-1">{r.eligible ? <Badge tone="ok">포함</Badge> : <Badge tone="muted" title={r.exclusion_reason ?? ""}>{r.exclusion_reason ?? "제외"}</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input className={`${inputClass} max-w-[200px]`} placeholder="검토자 (필수)" value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-label="검토자" />
                <label className="flex items-center gap-1.5 text-[12px] text-cosmos-secondary">
                  <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} />
                  포함 행을 바로 승인 (아니면 「검토 필요」로 남김)
                </label>
                <Button size="sm" variant="primary" disabled={busy !== null || readOnly || preview.included === 0} onClick={runImport} aria-busy={busy === "import"}>
                  {busy === "import" ? "등록 중…" : `근거 문서 ${preview.documents.length}건 등록`}
                </Button>
                {summary?.available && (
                  <span className="basis-full text-[12px] text-cosmos-amber" role="note">
                    기존 실적 목록({summary.counts?.total ?? 0}행)을 이 파일로 바꿉니다.
                  </span>
                )}
              </div>
            </div>
          )}
          {result && (
            <InlineAlert tone="ok" role="status">
              등록 완료 — 포함 {result.included} · 제외 {result.excluded} · 문서 {result.registered.length}건{result.skipped_duplicates.length > 0 ? ` · 중복 건너뜀 ${result.skipped_duplicates.length}` : ""} · {result.approved ? "승인됨" : "검토 필요"} · {result.note}
            </InlineAlert>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 테스트 검색 — 이 회사의 승인·색인 문단만
// ---------------------------------------------------------------------------

function TestSearchPanel({
  organizationId,
  embeddingAvailable,
  offReason,
  onTried,
}: {
  organizationId: string;
  embeddingAvailable: boolean;
  /** AI 검색이 꺼진 이유(서버 문구). 꺼져 있으면 검색은 늘 실패한다 — 누르게 두지 않고 이유를 적는다 (CMP-08). */
  offReason: string | null;
  onTried: () => void;
}) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<IndexSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 한 글자는 서버가 받지 않는다 — 누르면 엉뚱한 「입력한 값을 저장할 수 없습니다」가 떴다 (CMP-08).
  const tooShort = query.trim().length < 2;
  const blocked = !embeddingAvailable || tooShort;
  const run = () => {
    if (blocked || busy) return;
    setBusy(true);
    setError(null);
    searchOrganizationIndex(organizationId, query.trim(), 5)
      .then((r) => {
        setResult(r);
        // 「인덱스가 아직 없습니다」로 끝난 검색은 8단계 확인이 아니다 (CMP-22).
        if (r.available) onTried();
      })
      .catch((e: unknown) => setError(describe(e, "검색에 실패했습니다.")))
      .finally(() => setBusy(false));
  };

  return (
    <section className="mc-panel flex flex-col gap-3 p-4" aria-label="테스트 검색">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-cosmos-text">테스트 검색</h2>
        <span className="text-[12px] text-cosmos-muted">8단계 · 등록한 근거가 공고 요구사항 문장과 맞는지 찾아보기</span>
        <SourceBadge kind={embeddingAvailable ? "computed" : "not_run"} label={embeddingAvailable ? "내부 승인자료" : AI_SEARCH_OFF} />
      </div>
      {error && <InlineAlert tone="fail">{error}</InlineAlert>}
      <div className="flex flex-wrap gap-2">
        <input className={`${inputClass} flex-1`} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} placeholder="예: 생성형 AI 활용 실무교육 운영 실적" aria-label="검색어" />
        <Button variant="secondary" disabled={blocked || busy} onClick={run} aria-busy={busy} aria-describedby={blocked ? "company-search-reason" : undefined}>
          {busy ? "검색 중…" : "검색"}
        </Button>
        {blocked && (
          <p id="company-search-reason" className={`basis-full text-[12px] ${embeddingAvailable ? "text-cosmos-muted" : "text-cosmos-amber"}`} role="note">
            {!embeddingAvailable ? (offReason ?? "AI 검색이 꺼져 있어 검색할 수 없습니다.") : "검색어를 두 글자 이상 적으면 누를 수 있습니다."}
          </p>
        )}
      </div>
      {/* 사유는 백엔드 문구를 그대로 적는다. 「등록부를 읽지 못했습니다 — JSON 이 깨져 격리됐습니다」와
          「자료가 없습니다」는 다른 말이라, 여기서 「없음」으로 뭉개면 안 된다. */}
      {result && !result.available && <InlineAlert tone="warn" role="status">{result.reason ?? "검색할 수 없습니다."}</InlineAlert>}
      {result?.available && result.hits.length === 0 && (
        // 근거가 없을 때 «비슷한 문장»을 지어내지 않는다는 것을 화면이 말한다.
        <p className="text-[12.5px] leading-5 text-cosmos-secondary">
          일치하는 승인 근거가 없습니다. AI가 근거를 만들지 않습니다 — 현재 등록된 회사자료에서 확인할 수 없는 내용입니다.
          계약서 · 실적증명서 · 결과보고서 등 자료를 추가해 주세요.
        </p>
      )}
      {result?.available && result.hits.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {result.hits.map((h) => (
            <li key={h.evidence_id} className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2 text-[12px] text-cosmos-muted">
                <span className="font-mono">{h.score.toFixed(3)}</span>
                <span className="truncate" title={h.document_name}>{h.document_name}</span>
                <span>p.{h.page ?? "-"}</span>
                <Badge tone={dataClassTone(h.data_class)}>{DATA_CLASS_LABELS[h.data_class]}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] leading-5 text-cosmos-secondary">{h.source_text}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 문서 상세 (후보 검토 · 승인 · 비활성 · 인용 역추적)
// ---------------------------------------------------------------------------

function DocumentDetail({
  organizationId,
  documentId,
  onChanged,
  onClose,
  readOnly,
  nextReview,
  onGoNext,
  organizationDataClass,
}: {
  organizationId: string;
  documentId: string;
  /** 회사 등급 — 승인 칸에서 고른 자료 등급이 회사와 다르면 매칭에서 빠진다고 말한다 (CMP-06). */
  organizationDataClass: DataClass | null;
  onChanged: () => void;
  onClose: () => void;
  readOnly: boolean;
  /** 이 문서 **다음에** 검토할 문서. 없으면 null — 「다음 문서로」를 내보내지 않는다. */
  nextReview: { id: string; title: string } | null;
  onGoNext: (documentId: string) => void;
}) {
  const [detail, setDetail] = useState<CompanyDocumentDetail | null>(null);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  /**
   * 체크한 문단 (0919 §4-B-4).
   *
   * 「채택/제외」와 따로 둔다. 체크는 «무엇을 한꺼번에 처리할지»를 고르는 것이고,
   * 채택/제외는 그 처리 결과다. 둘을 한 값으로 묶으면 「제외로 표시한 것」과
   * 「아직 안 고른 것」이 구분되지 않는다.
   */
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [approveForm, setApproveForm] = useState<{ data_class: DataClass; scope: Scope; valid_to: string }>({ data_class: "real", scope: "internal", valid_to: "" });

  const load = useCallback(() => {
    getOrganizationDocument(organizationId, documentId)
      .then((d) => {
        setDetail(d);
        setApproveForm((prev) => ({ ...prev, data_class: d.metadata.data_class }));
        setDecisions(Object.fromEntries(d.candidates.filter((c) => c.approved !== null).map((c) => [c.id, c.approved as boolean])));
      })
      .catch((e: unknown) => setError(describe(e, "문서를 불러오지 못했습니다.")));
    getOrganizationDocumentUsage(organizationId, documentId).then(setUsage).catch(() => setUsage(null));
  }, [organizationId, documentId]);

  useEffect(() => {
    load();
  }, [load]);

  const run = (task: Promise<unknown>, fallback: string) => {
    setBusy(true);
    setError(null);
    task
      .then(() => {
        load();
        onChanged();
      })
      .catch((e: unknown) => setError(describe(e, fallback)))
      .finally(() => setBusy(false));
  };

  /**
   * 검토 결과를 저장한다. `goToId` 가 있으면 저장에 **성공했을 때만** 그 문서로 넘어간다.
   *
   * 실패했는데 넘어가면 방금 고른 채택·제외가 조용히 사라진다. 그래서 `run` 을 쓰지 않고
   * 여기서 따로 처리한다 — `run` 은 결과와 상관없이 목록만 다시 읽는다.
   */
  function saveReview(goToId: string | null) {
    setBusy(true);
    setError(null);
    reviewOrganizationCandidates(organizationId, documentId, {
      reviewer: reviewer.trim(),
      reviews: Object.entries(decisions).map(([candidate_id, approved]) => ({ candidate_id, approved })),
    })
      .then(() => {
        onChanged();
        if (goToId) {
          onGoNext(goToId);
          return;
        }
        load();
        setPicked(new Set());
      })
      .catch((e: unknown) => setError(describe(e, "검토 결과를 저장하지 못했습니다.")))
      .finally(() => setBusy(false));
  }

  if (!detail) return <div className="mc-panel p-4">{error ? <InlineAlert tone="fail">{error}</InlineAlert> : <LoadingState label="문서 불러오는 중" rows={3} />}</div>;

  const pendingReview = detail.candidates.filter((c) => c.approved === null).length;
  const chosen = Object.values(decisions).filter(Boolean).length;
  /**
   * 「전체 선택」이 담는 것 — **규칙이 「근거 아님」으로 표시한 문단은 뺀다.**
   *
   * 목차·표지·머리글 같은 것들이라 한꺼번에 채택하면 근거가 오염된다. 한 건씩 체크해서
   * 넣는 것은 막지 않는다 — 그건 담당자가 보고 내린 판단이다.
   */
  const bulkTargets = detail.candidates.filter((c) => !c.is_gap);
  const allPicked = bulkTargets.length > 0 && bulkTargets.every((c) => picked.has(c.id));
  const pickedCount = picked.size;

  /** 체크한 문단을 한꺼번에 채택/제외로 표시한다. 저장은 아직이다 — 승인은 사람이 누른다. */
  function markPicked(approved: boolean) {
    if (picked.size === 0) return;
    setDecisions((prev) => {
      const next = { ...prev };
      for (const id of picked) next[id] = approved;
      return next;
    });
  }
  // 비활성 문서도 「근거로 등록」으로 되살릴 수 있다(서버가 받는다) — 예전에는 막혀 있고 틀린 사유가 떴다 (CMP-09).
  const canApprove = ["review", "approved", "indexed", "failed", "retired"].includes(detail.status) && detail.approved_chunk_count > 0;
  // 서버가 검토를 받는 상태 — 비활성 문서에서 누르면 「현재 상태(retired)…」 오류가 그대로 떴다 (CMP-09).
  const canReview = ["review", "approved", "indexed", "failed"].includes(detail.status);
  const locked = busy || readOnly;
  const approveMismatch = classMismatchNote(organizationDataClass, approveForm.data_class);

  return (
    <aside className="mc-panel flex max-h-[80vh] min-h-0 flex-col" aria-label={`${detail.title} 상세`}>
      <div className="flex shrink-0 items-center gap-2 border-b border-cosmos-border px-4 py-2.5">
        <Badge tone={documentStatusLabel(detail, localToday()) === OUT_OF_PERIOD_LABEL ? "warn" : STATUS_TONE[detail.status]} glyph>
          {documentStatusLabel(detail, localToday())}
        </Badge>
        <p className="min-w-0 flex-1 truncate text-[13px] font-medium text-cosmos-text" title={detail.file_name}>
          {detail.title}
        </p>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="닫기">
          ✕
        </Button>
      </div>
      <div className="mc-scroll flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
        {error && <InlineAlert tone="fail">{error}</InlineAlert>}

        {/* 추출에 실패한 문서에는 다시 시도할 길을 준다.
            원인 문구만 보여 주고 끝내면 담당자가 할 수 있는 일이 없다. */}
        {detail.status === "failed" && (
          <InlineAlert tone="fail">
            <span className="block">{detail.error ?? "글자를 읽지 못했습니다."}</span>
            <Button
              size="sm"
              variant="secondary"
              disabled={locked}
              onClick={() => {
                setBusy(true);
                setError(null);
                reextractOrganizationDocument(organizationId, documentId)
                  .then((d) => {
                    setDetail(d);
                    onChanged();
                  })
                  .catch((e: unknown) => setError(describe(e, "글자를 다시 읽지 못했습니다.")))
                  .finally(() => setBusy(false));
              }}
            >
              {busy ? "글자를 다시 읽는 중…" : "글자 다시 읽기"}
            </Button>
          </InlineAlert>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
          {[
            ["회사 코드", detail.organization_id ?? organizationId],
            ["파일", `${detail.file_name} · ${formatBytes(detail.size_bytes)} · ${detail.doc_format ?? "형식 미확인"}`],
            ["등록", `${formatDateTime(detail.uploaded_at)} · ${detail.uploaded_by ?? "등록자 미상"}`],
            ["등급", `${DATA_CLASS_LABELS[detail.metadata.data_class]} · ${detail.metadata.scope === "internal" ? "내부 전용" : "공개 데모 허용(지금은 효과 없음)"}`],
            ["유효기간", detail.metadata.valid_to ? `${detail.metadata.valid_from ?? "-"} ~ ${detail.metadata.valid_to}` : "제한 없음"],
            ["승인", detail.metadata.approved ? `${detail.metadata.approved_by} · ${detail.metadata.approved_at ? formatDateTime(detail.metadata.approved_at) : ""} · v${detail.metadata.version}` : "미승인"],
            ["AI 검색", detail.indexed_at ? `문장 ${detail.indexed_chunk_count}개 · ${formatDateTime(detail.indexed_at)}` : "준비 전"],
            ["파일 지문", detail.sha256.slice(0, 16) + "…"],
          ].map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-cosmos-muted">{label}</dt>
              <dd className="min-w-0 break-words text-cosmos-secondary">{value}</dd>
            </div>
          ))}
        </dl>
        {/* 추출 실패 문구는 위 빨간 상자가 이미 말한다 — 같은 문장을 두 번 그리지 않는다 (CMP-23). */}
        {detail.status !== "failed" && detail.error && <InlineAlert tone="warn">{detail.error}</InlineAlert>}
        {detail.note && <p className="text-[12px] leading-4 text-cosmos-muted">{detail.note}</p>}

        <section className="flex flex-col gap-2">
          <h3 className="flex items-center justify-between text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">
            뽑은 문장 {detail.candidates.length}
            <span className="font-mono text-[12px] tabular-nums">안 본 문장 {pendingReview} · 고른 문장 {detail.approved_chunk_count}</span>
          </h3>
          {/* 한 화면에서 여러 개 (0919 §4-B-4). 예전에는 문단마다 두 번씩 눌러야 했다. */}
          {detail.candidates.length > 0 && !readOnly && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-cosmos-border px-3 py-2">
              <label className="mc-focus flex cursor-pointer items-center gap-1.5 text-[12px] text-cosmos-secondary">
                <input
                  type="checkbox"
                  checked={allPicked}
                  onChange={(e) =>
                    setPicked(() => (e.target.checked ? new Set(bulkTargets.map((c) => c.id)) : new Set()))
                  }
                  aria-label="근거 후보 전체 선택"
                />
                전체 선택
                <span className="font-mono tabular-nums text-cosmos-muted">{bulkTargets.length}</span>
              </label>
              <Button size="sm" variant="secondary" disabled={locked || pickedCount === 0} onClick={() => markPicked(true)}>
                고른 것 모두 쓰기
              </Button>
              <Button size="sm" variant="ghost" disabled={locked || pickedCount === 0} onClick={() => markPicked(false)}>
                고른 것 모두 빼기
              </Button>
              <span className="text-[12px] text-cosmos-muted">
                {pickedCount > 0 ? `${pickedCount}건 고름` : "문장을 체크하면 한꺼번에 처리합니다"}
                {bulkTargets.length < detail.candidates.length &&
                  ` · 「근거 아님(규칙)」 ${detail.candidates.length - bulkTargets.length}건은 전체 선택에서 뺐습니다`}
              </span>
            </div>
          )}
          {detail.candidates.length === 0 ? (
            <p className="text-[12px] text-cosmos-muted">뽑은 문장이 없습니다.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {detail.candidates.map((c) => {
                const value = decisions[c.id];
                return (
                  <li key={c.id} className="rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2" style={{ borderLeft: `2px solid ${value === true ? COSMOS_COLORS.cyan : value === false ? COSMOS_COLORS.slate : COSMOS_COLORS.amber}` }}>
                    <div className="flex flex-wrap items-center gap-2 text-[12px] text-cosmos-muted">
                      {!readOnly && (
                        <input
                          type="checkbox"
                          checked={picked.has(c.id)}
                          onChange={(e) =>
                            setPicked((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(c.id);
                              else next.delete(c.id);
                              return next;
                            })
                          }
                          aria-label={`${c.id.split(":")[1]} 문단 선택`}
                        />
                      )}
                      <span className="font-mono">{c.id.split(":")[1]}</span>
                      <span>{c.page ? `${c.page}쪽` : "쪽 모름"}</span>
                      {c.is_gap && <Badge tone="warn">근거 아님(규칙)</Badge>}
                      {c.reviewer && <span className="whitespace-nowrap">· {c.reviewer} 검토</span>}
                      {/* 눌린 상태를 보조기기에도 알린다 · 누르기 쉬운 높이 (CMP-31). */}
                      <span className="ml-auto flex gap-1">
                        <button type="button" disabled={readOnly} aria-pressed={value === true} className={`mc-focus min-h-8 rounded px-2 ${value === true ? "bg-cosmos-cyan/25 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"}`} onClick={() => setDecisions((p) => ({ ...p, [c.id]: true }))}>
                          쓰기
                        </button>
                        <button type="button" disabled={readOnly} aria-pressed={value === false} className={`mc-focus min-h-8 rounded px-2 ${value === false ? "bg-cosmos-slate/60 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"}`} onClick={() => setDecisions((p) => ({ ...p, [c.id]: false }))}>
                          빼기
                        </button>
                      </span>
                    </div>
                    <p className="mt-1 text-[12.5px] leading-5 text-cosmos-secondary">{c.source_text}</p>
                    {c.note && <p className="mt-1 text-[12px] text-cosmos-muted">{c.note}</p>}
                  </li>
                );
              })}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input className={`${inputClass} max-w-[200px]`} placeholder="검토자 (필수)" value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-label="검토자" />
            <Button
              size="sm"
              variant="secondary"
              disabled={locked || !canReview || !reviewer.trim() || Object.keys(decisions).length === 0}
              onClick={() => saveReview(null)}
            >
              고른 문장 저장 ({chosen}개)
            </Button>
            {/*
              8건을 연달아 보는 일이라 저장할 때마다 목록으로 돌아가 다음 것을 찾는 것이
              가장 지루하다. 「다음 검토 문서」는 **지금 문서의 자리** 다음 것이다 —
              「검토 필요 상태인 첫 문서」로 고르면 방금 저장한 이 문서가 다시 열린다.
            */}
            {nextReview && (
              <Button
                size="sm"
                variant="primary"
                disabled={locked || !canReview || !reviewer.trim() || Object.keys(decisions).length === 0}
                title={`다음 검토 문서: ${nextReview.title}`}
                onClick={() => saveReview(nextReview.id)}
              >
                저장하고 다음 문서로
              </Button>
            )}
          </div>
          {/* 단추가 왜 잠겼는지 화면 글자로 (§3-H ③ · CMP-09). */}
          {!readOnly && !canReview ? (
            <p className="text-[12px] leading-4 text-cosmos-amber" role="note">
              {detail.status === "retired"
                ? "비활성 문서는 검토를 저장할 수 없습니다 — 다시 쓰려면 아래 「근거로 등록」을 누르세요."
                : `지금 상태(${DOCUMENT_STATUS_LABELS[detail.status]})에서는 검토를 저장할 수 없습니다.`}
            </p>
          ) : (
            !readOnly &&
            !reviewer.trim() && (
              <p className="text-[12px] leading-4 text-cosmos-muted" role="note">
                검토자 이름을 적으면 저장 · 승인 · 비활성을 누를 수 있습니다.
              </p>
            )
          )}
          {nextReview && (
            <p className="text-[12px] leading-4 text-cosmos-muted">
              다음 검토 문서: {nextReview.title}
            </p>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">근거로 등록</h3>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              자료 등급
              <select className={inputClass} value={approveForm.data_class} onChange={(e) => setApproveForm((p) => ({ ...p, data_class: e.target.value as DataClass }))}>
                {(Object.keys(DATA_CLASS_LABELS) as DataClass[]).map((k) => (
                  <option key={k} value={k}>
                    {DATA_CLASS_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              공개 범위
              <select className={inputClass} value={approveForm.scope} onChange={(e) => setApproveForm((p) => ({ ...p, scope: e.target.value as Scope }))}>
                <option value="internal">내부 전용</option>
                <option value="public_demo">공개 배포에 써도 됨(지금은 쓰지 않음)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-cosmos-muted">
              유효기간 종료 (비우면 제한 없음)
              <input type="date" className={inputClass} value={approveForm.valid_to} onChange={(e) => setApproveForm((p) => ({ ...p, valid_to: e.target.value }))} />
            </label>
          </div>
          {/* 공개 데모 분석은 합성 인덱스만 읽고, 내부 분석은 두 값 모두 쓴다 — 고르면 사실을 말한다 (CMP-24). */}
          {approveForm.scope === "public_demo" && (
            <p className="text-[12px] leading-4 text-cosmos-muted" role="note">
              공개 데모 분석은 가상 예시 자료만 읽어 회사자료를 쓰지 않습니다. 이 선택은 지금 어느 분석에도 차이가 없습니다.
            </p>
          )}
          {approveMismatch && (
            <InlineAlert tone="warn" role="status">
              {approveMismatch}
            </InlineAlert>
          )}
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="primary"
              disabled={locked || !reviewer.trim() || !canApprove}
              title={!canApprove ? "고른 문장을 먼저 저장해야 근거로 등록할 수 있습니다" : undefined}
              onClick={() =>
                run(
                  approveOrganizationDocument(organizationId, documentId, { reviewer: reviewer.trim(), data_class: approveForm.data_class, scope: approveForm.scope, valid_to: approveForm.valid_to || null }),
                  "승인에 실패했습니다.",
                )
              }
            >
              근거로 등록
            </Button>
            {/*
              비활성 사유가 `title` 툴팁에만 있었다 (ISSUE-033). 툴팁은 마우스를 올려야
              보인다 — 터치 화면에서는 아예 볼 수 없고 스크린리더도 읽지 않는다.
              「왜 못 누르는가」는 화면 글자로 있어야 한다.
            */}
            {detail.status === "retired" ? (
              <p className="basis-full text-[12px] leading-4 text-cosmos-amber" role="note">
                비활성 문서입니다 — 다시 쓰려면 「근거로 등록」을 누르세요.
              </p>
            ) : (
              !canApprove && (
                <p className="basis-full text-[12px] leading-4 text-cosmos-amber" role="note">
                  고른 문장을 먼저 저장해야 근거로 등록할 수 있습니다.
                </p>
              )
            )}
            {detail.status !== "retired" && (
              <Button
                size="sm"
                variant="ghost"
                disabled={locked || !reviewer.trim()}
                onClick={async () => {
                  // 확인 없이 바로 빠졌다 (CMP-09). 되살리는 길(「근거로 등록」)도 함께 알린다(45차 L5 화면 안 창).
                  if (!(await requestConsent({ title: "이 문서를 비활성할까요?", body: "공고 분석의 근거에서 빠집니다. 다시 쓰려면 「근거로 등록」을 누르면 됩니다.", confirmLabel: "비활성", cancelLabel: "그만두기" }))) return;
                  run(retireOrganizationDocument(organizationId, documentId, { reviewer: reviewer.trim() }), "비활성 처리에 실패했습니다.");
                }}
              >
                비활성
              </Button>
            )}
            {!["approved", "indexed"].includes(detail.status) && (
              <Button
                size="sm"
                variant="ghost"
                className="text-cosmos-red"
                disabled={locked}
                onClick={async () => {
                  if (await requestConsent({ title: "이 문서를 삭제할까요?", body: "이 문서와 후보 · 원본 파일을 지웁니다. 되돌릴 수 없습니다.", confirmLabel: "삭제", cancelLabel: "그만두기" })) {
                    setBusy(true);
                    deleteOrganizationDocument(organizationId, documentId)
                      .then(() => {
                        onChanged();
                        onClose();
                      })
                      .catch((e: unknown) => setError(describe(e, "삭제에 실패했습니다.")))
                      .finally(() => setBusy(false));
                  }
                }}
              >
                삭제
              </Button>
            )}
          </div>
          <p className="text-[12px] leading-4 text-cosmos-muted">근거로 등록하면 고른 문장이 이 회사의 근거가 되고, AI 검색이 켜져 있으면 검색 준비가 저절로 됩니다. 꺼져 있으면 「등록됨(검색 준비 전)」으로 남습니다. 등록한 문서는 근거에서 뺀 뒤에만 지울 수 있습니다.</p>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">어디에 인용됐나</h3>
          {!usage || usage.used_in.length === 0 ? (
            <p className="text-[12px] text-cosmos-muted">이 회사의 저장된 제안서 초안에서 이 문서를 인용한 문장이 없습니다.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-[12px] text-cosmos-secondary">
              {usage.used_in.map((u) => (
                <li key={`${u.procurement_id}:${u.sentence_id}`}>
                  {u.procurement_id} · {u.requirement_id ?? "-"} · 문장 {u.sentence_id ?? "-"} ({u.where === "proposal" ? "핵심 섹션" : "전체 초안"})
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// 최근 활동 (관리자 전용)
// ---------------------------------------------------------------------------

/** 응답 상태를 사람 말로. 숫자는 그대로 남긴다 — 사유를 좁히려면 결국 그 숫자가 필요하다. */
function resultLabel(status: number): { text: string; tone: Tone } {
  const text = resultText(status);
  if (status >= 200 && status < 300) return { text, tone: "pass" };
  if (status >= 500) return { text, tone: "fail" };
  if (status >= 400) return { text, tone: "warn" };
  return { text, tone: "muted" };
}

/**
 * 기록의 역할 값은 계약상 셋 중 하나다. 화면에는 한국어만 찍는다 —
 * 툴팁(title)에도 영문 enum 을 넣지 않는다. title 은 그대로 접근성 이름이 되어
 * 화면낭독기가 「편집자」 대신 「editor」를 읽어 준다.
 * 셋 중 어느 것도 아닌 값이 오면 그때만 원래 값을 밝힌다 — 기록이 깨진 것을 숨기지 않는다.
 */
function roleLabel(role: string): string {
  // 로그인 없는 로컬 실행은 「local」로 남는다 — 깨진 기록이 아니다 (CMP-10).
  if (role === "local") return "로컬(로그인 없음)";
  const known = (ROLE_LABELS as Record<string, string>)[role];
  return known ?? `확인 안 됨 (${role})`;
}

/**
 * 최근 활동 — 누가 언제 무엇을 바꿨는가.
 *
 * 왜 관리자에게만 보이는가: 이 표는 사람의 행동 기록이다. 서로의 작업 시각까지
 * 다 보이면 감시 도구가 된다. 백엔드도 관리자만 통과시키므로(계약서 6장) 화면만
 * 숨겨서 되는 것은 아니고, 둘 다 막는다.
 *
 * 기록을 못 받으면 **아무것도 지어내지 않는다.** 표는 비고, 사유만 한 줄 남긴다.
 * (아직 `GET /api/audit-log` 가 없는 배포에서는 여기가 늘 비어 있다.)
 */
function RecentActivityPanel({ localMode, organizationName }: { localMode: boolean; organizationName: (id: string) => string | null }) {
  const [rows, setRows] = useState<AuditLogEntry[] | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // 43차 TEAM-04 — 자동 계산 · 같은 일의 두 번째 줄을 빼고 20줄을 채우려고 넉넉히 받는다
    getAuditLog(100)
      .then((entries) => {
        if (!alive) return;
        setRows(visibleActivity(entries));
        setNote(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setRows([]);
        /**
         * 404 를 공용 문구에 맡기면 「아직 저장된 결과가 없습니다. 분석을 먼저 실행해 주세요」가
         * 뜬다 — 활동 기록과 아무 상관 없는 말이다. 여기서만 사유를 갈라 적는다.
         * 「기록이 없다」와 「기록 기능이 없다」를 같은 문장으로 뭉개지 않는다.
         */
        if (e instanceof ApiError && e.status === 404) {
          setNote("이 배포본에는 활동 기록이 아직 없습니다. 서버가 기록을 남기기 시작하면 여기에 보입니다.");
          return;
        }
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setNote("이 계정으로는 활동 기록을 볼 수 없습니다. 관리자 계정으로 확인해 주세요.");
          return;
        }
        setNote(describe(e, "기록을 불러오지 못했습니다."));
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <section className="mc-panel flex flex-col gap-3 p-4" aria-label="최근 활동">
      <SectionHeader
        as="h2"
        title="최근 활동"
        description={`사람이 바꾼 것만 보입니다(조회 · 공고를 고를 때의 자동 판정 계산은 뺍니다). 본문·검색어·비밀번호는 기록하지 않습니다. 최신 20건.${localMode ? " 로그인 없는 로컬 실행에서는 이 화면(회사자료)의 저장이 기록되지 않습니다 — 조항 확인 · 목록 새로 받기만 남습니다." : ""}`}
      />
      {rows === null ? (
        <LoadingState label="최근 활동 불러오는 중" rows={3} />
      ) : rows.length === 0 ? (
        <p className="text-[12.5px] leading-5 text-cosmos-muted">
          {note ?? "아직 기록된 활동이 없습니다."}
        </p>
      ) : (
        <div className="mc-scroll max-h-[420px] overflow-auto">
          <table className="mc-sticky-head w-full min-w-[720px] border-collapse text-[13px]" aria-label="최근 활동 목록">
            <thead>
              <tr className="border-b border-cosmos-border text-left text-[12px] uppercase tracking-[0.1em] text-cosmos-muted">
                <th scope="col" className="w-40 px-3 py-2.5 font-semibold">시각</th>
                <th scope="col" className="w-28 px-3 py-2.5 font-semibold">사용자</th>
                <th scope="col" className="w-20 px-3 py-2.5 font-semibold">역할</th>
                <th scope="col" className="px-3 py-2.5 font-semibold">동작</th>
                <th scope="col" className="w-36 px-3 py-2.5 font-semibold">조직</th>
                <th scope="col" className="w-24 px-3 py-2.5 font-semibold">결과</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const result = resultLabel(row.status);
                return (
                  <tr key={`${row.ts}:${row.user}:${row.path}:${i}`} className="border-b border-cosmos-border/70 last:border-b-0">
                    <td className="px-3 py-2 text-[12px] text-cosmos-muted">{formatDateTime(row.ts)}</td>
                    <td className="max-w-[7rem] truncate px-3 py-2 text-cosmos-text" title={`아이디 ${row.user}`}>{row.display_name || row.user}</td>
                    <td className="px-3 py-2 text-[12px] text-cosmos-secondary">{roleLabel(row.role)}</td>
                    <td className="px-3 py-2 text-[12.5px] text-cosmos-text" title={`${row.method} ${row.path}`}>
                      {actionLabel(row)}
                    </td>
                    {/* 45차 H6 — 회사 코드(org-…) 대신 회사 이름 · 코드는 칸 풀이에만 */}
                    <td className="max-w-[9rem] truncate px-3 py-2 text-[12px] text-cosmos-secondary" title={row.organization_id ? `회사 코드 ${row.organization_id}` : undefined}>
                      {row.organization_id ? organizationName(row.organization_id) ?? row.organization_id : "—"}
                    </td>
                    {/* 결과는 사람 말 — 응답 번호는 칸 풀이(title)에만 남긴다(사유를 좁힐 때 쓴다) */}
                    <td className="px-3 py-2" title={`응답 번호 ${row.status}`}>
                      <Badge tone={result.tone}>{result.text}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 페이지
// ---------------------------------------------------------------------------

export default function CompanyPage() {
  const hydrated = useSyncExternalStore(subscribeNever, getHydrated, getHydratedServer);
  const organizationId = useOrganizationId();
  const organizations = useOrganizations();
  const me = useCurrentUser();
  const [profile, setProfile] = useState<OrganizationProfile | null>(null);
  const [list, setList] = useState<DocumentListResponse | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rebuildMessage, setRebuildMessage] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [searchTried, setSearchTried] = useState<string | null>(null);

  const reloadOrganizations = organizations.reload;
  const reload = useCallback(() => {
    const target = organizationId;
    Promise.allSettled([getOrganizationProfile(target), listOrganizationDocuments(target)]).then(([p, l]) => {
      // 실패한 쪽은 **이전 회사 값을 지운다.** 남겨 두면 A사의 문서·프로필이 B사 화면에
      // 그대로 보이고, 그 상태에서 「수정 → 저장」을 누르면 A사 상호·주소·연락처가
      // B사 레코드에 덮인다. 회사 격리를 정면으로 깨는 일이라, 비어 보이는 편이 낫다.
      const documentsNow = l.status === "fulfilled" ? l.value.documents : null;
      setProfile(p.status === "fulfilled" ? p.value : null);
      setList(l.status === "fulfilled" ? l.value : null);
      // 열린 문서는 새 목록에 없을 때만 닫는다 — 저장·승인·업로드가 끝날 때마다 상세가 닫혔다 (CMP-01).
      setSelectedId((prev) => keepSelectedDocument(prev, documentsNow));
      // 프로필과 목록은 각자 자기 실패만 말한다 — 프로필만 실패해도 목록 자리에 「목록을 못 불러왔다」가 뜨고
      // 같은 문장이 세 번 보였다 (CMP-25). 실패한 카드는 「불러오는 중」이 아니라 실패와 「다시 시도」를 보인다.
      setProfileError(p.status === "rejected" ? describe(p.reason, "회사 프로필을 불러오지 못했습니다.") : null);
      setListError(l.status === "rejected" ? describe(l.reason, "문서 목록을 불러오지 못했습니다.") : null);
      setLoadedFor(target);
    });
    reloadOrganizations();
  }, [organizationId, reloadOrganizations]);

  useEffect(() => {
    if (hydrated) reload();
  }, [hydrated, reload]);

  /** 회사를 바꾼 뒤 — 고른 문서 · 재색인 안내를 푼다. 묻고 바꾸는 일은 회사 선택기가 한다 (27차 UNI-07). */
  const afterOrganizationChange = useCallback(() => {
    setSelectedId(null);
    setRebuildMessage(null);
  }, []);

  const summary = findOrganization(organizations.list, organizationId);
  const demoReadOnly = Boolean(organizations.list?.public_demo_mode);
  // 43차 마지막 검토(M26) — 열람자는 회사자료 저장 · 올리기 · 승인 · 원장 가져오기 단추도 잠근다(서버도 막는다 · 누른 뒤에야 403 을 봤다)
  const viewer = useViewerLock();
  const readOnly = demoReadOnly || viewer;
  const stale = loadedFor !== organizationId;
  const counts = stale ? {} : (list?.counts ?? {});
  const index = stale ? null : (list?.index ?? null);
  const documents = useMemo(() => (stale ? [] : (list?.documents ?? [])), [list, stale]);

  /**
   * 「다음 검토 문서」 — 지금 보고 있는 문서 **다음 자리**의 검토 필요 문서 (0919 §4-B-4).
   *
   * 「검토 필요 상태인 첫 문서」로 고르면 안 된다. 저장해도 문서는 채택 문단이 생겼을 뿐
   * 아직 `검토 필요` 상태라서, 방금 저장한 바로 그 문서가 다시 열린다.
   */
  const nextReview = useMemo(() => {
    const queue = documents.filter((d) => d.status === "review");
    if (queue.length === 0) return null;
    const here = queue.findIndex((d) => d.id === selectedId);
    const next = here >= 0 ? queue[here + 1] : queue.find((d) => d.id !== selectedId);
    return next ? { id: next.id, title: next.title } : null;
  }, [documents, selectedId]);
  const inUse = documents.filter((d) => d.status === "indexed" && withinValidity(d.metadata, localToday())).length;
  const split = counted(summary);
  const registryNote = split.document_registry_note ?? null;
  /**
   * 「최근 활동」을 볼 수 있는가.
   *
   * 로그인했으면 역할이 관리자일 때만이다. 로그인 자체가 없는 상태(로컬 관리자 모드)는
   * 백엔드도 전권으로 보므로(신원 판정 1항) 여기서만 숨겨 봐야 의미가 없다 — 같이 보여준다.
   * 공개 배포본은 두 조건 모두 아니어서 표가 아예 그려지지 않는다.
   */
  const canSeeActivity = me ? me.role === "admin" : Boolean(organizations.list?.local_admin_mode);

  // 머리 오른쪽 순서: 회사 → (보기 전환 없음 — 전체 보기만) → 화면 단추 (27차 §3-E-4).
  const headerAside = (
    <>
      <OrganizationPicker id="company-organization-picker" list={organizations.list} organizationId={organizationId} onChanged={afterOrganizationChange} />
      {index && <SourceBadge kind={index.embedding_available ? "computed" : "not_run"} label={index.embedding_available ? AI_SEARCH_ON : AI_SEARCH_OFF} />}
      <Button size="sm" variant="secondary" onClick={reload}>
        {VIEW_RELOAD_TERM}
      </Button>
    </>
  );

  return (
    <AppShell headerAside={headerAside}>
      <SectionHeader
        as="h1"
        title={SCREEN_NAMES.company}
        description="회사 소개서 · 실적 자료를 올리고, 제안서에 써도 되는 문장을 골라 근거로 등록하세요. 등록한 문장만 공고 분석과 제안서에 쓰입니다. 올린 자료는 이 회사 안에만 보관됩니다."
        aside={<BackToSelectionLink />}
      />

      <OrganizationBar list={organizations.list} error={organizations.error} organizationId={organizationId} onCreate={() => setCreating(true)} readOnly={readOnly} />
      {creating && (
        <CreateOrganizationDialog
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setOrganizationId(id);
            setSelectedId(null);
          }}
        />
      )}

      {/* 「등록된 회사자료가 없습니다」로 뭉개면 자료가 증발한 것과 구분되지 않는다.
          등록부를 못 읽었으면 백엔드가 보낸 사유를 그대로 올린다. */}
      {registryNote && <InlineAlert tone="fail">{registryNote}</InlineAlert>}

      {/* 카드 힌트는 한 줄로 잘린다(KpiCard). 6장을 1366px 한 줄에 밀어 넣으면
          「검토 대기 8 · 승인·색인 대기 0 …」처럼 갈라 적은 숫자가 도로 잘려 보인다 — 3장씩 두 줄로 둔다. */}
      <section aria-label="회사자료 현황 요약" className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
        {/* 「승인 N건」이 카드와 진행 단계에서 서로 다른 수를 말하고 있었다.
            여기 힌트는 상태별 원자료(counts)라 「승인·색인 대기」로 갈라 적는다. */}
        <KpiCard
          label="등록 자료"
          value={stale ? "…" : list ? documents.length : "—"}
          unit="건"
          hint={`문장 고르기 필요 ${counts.review ?? 0} · 검색 준비 전 ${counts.approved ?? 0} · 사용 중 ${counts.indexed ?? 0}`}
          tone="info"
          badge={<SourceBadge kind="human" label="담당자 등록" />}
        />
        <KpiCard
          label="근거로 쓰는 문서"
          value={stale ? "…" : (split.indexed_document_count ?? counts.indexed ?? 0)}
          unit="건"
          hint={`등록 ${summary?.approved_document_count ?? 0}건 중 ${split.approved_not_indexed_document_count ?? counts.approved ?? 0}건은 검색 준비 전`}
          tone={(split.indexed_document_count ?? 0) > 0 ? "pass" : "muted"}
          badge={<SourceBadge kind={(split.indexed_document_count ?? 0) > 0 ? "computed" : "not_run"} label={(split.indexed_document_count ?? 0) > 0 ? "검색 준비됨" : "검색 준비 전"} />}
        />
        <KpiCard
          label="AI가 찾는 문장"
          value={index?.company_index.exists ? index.company_index.chunk_count : stale ? "…" : "없음"}
          unit={index?.company_index.exists ? "개" : undefined}
          hint={index?.company_index.built_at ? `준비 ${formatDateTime(index.company_index.built_at)}` : "근거로 등록한 문서를 AI 검색 준비하면 만들어집니다"}
          tone={index?.company_index.exists ? "ok" : "muted"}
          badge={<SourceBadge kind={index?.company_index.exists ? "computed" : "not_run"} label={index?.company_index.exists ? "내부 승인자료" : "아직 안 만듦"} />}
        />
        {/* 「분석에 사용 중」을 색인 완료 건수로만 세면, 비활성 처리했거나 유효기간이 지난 승인 문서까지
            쓰이는 것처럼 읽힌다. 백엔드가 실제 매칭 대상(is_active)을 세어 내려주므로 그것을 쓴다. */}
        <KpiCard
          label="공고 분석에 쓰는 문서"
          value={stale ? "…" : (split.active_evidence_document_count ?? inUse)}
          unit="건"
          hint="근거로 등록 · 유효기간 안 · 근거에서 빼지 않음 — 검색 준비된 고른 문장만 공고와 연결"
          tone={(split.active_evidence_document_count ?? inUse) > 0 ? "pass" : "muted"}
          // AI 검색이 꺼져 있으면 새로 승인한 문서는 색인되지 않아 매칭에 들어가지 않는다 — 「매칭 가능」이라고 단정하지 않는다 (CMP-11).
          badge={
            <SourceBadge
              kind={(split.active_evidence_document_count ?? inUse) > 0 ? "analysis" : "not_run"}
              label={(split.active_evidence_document_count ?? inUse) > 0 ? (index?.embedding_available ? "공고와 연결됨" : "예전 준비분만") : "연결 안 됨"}
            />
          }
        />
        <KpiCard label="검색 준비 전" value={index?.pending_documents ?? (stale ? "…" : 0)} unit="건" hint={index?.note ?? ""} tone={index && index.pending_documents > 0 ? "warn" : "pass"} badge={<SourceBadge kind={index?.embedding_available ? "computed" : "not_run"} label={index?.embedding_available ? "AI 검색 준비됨" : AI_SEARCH_OFF} />} />
        <KpiCard
          label="공개 배포에 씀"
          value={summary ? (summary.usable_in_public_demo ? "가능" : "불가") : "…"}
          hint={summary ? (summary.usable_in_public_demo ? "가상 예시 자료 · 공개 승인됨" : "내부 전용 — 공개 배포본에는 가상 예시 자료만 실립니다") : "회사 정보 확인 중"}
          tone={summary?.usable_in_public_demo ? "demo" : "muted"}
          badge={<SourceBadge kind={summary?.usable_in_public_demo ? "demo" : "human"} label={summary ? DATA_CLASS_LABELS[summary.organization.data_class] : "확인 중"} />}
        />
      </section>

      {/* 규칙을 화면이 직접 말한다. 「올려 두면 AI가 알아서 익힌다」로 읽히지 않게 한다.
          코드에서는 세 번 강제된다 — 채택 0문단이면 승인 차단 · 승인된 것만 색인 · 매칭 시점 재확인. */}
      <p className="text-[12.5px] leading-5 text-cosmos-secondary">
        담당자가 고르고 근거로 등록한 문장만 쓰입니다. 등록하지 않은 문장, 근거에서 뺐거나 유효기간이 지난 자료는 공고 분석에 쓰이지 않습니다.
        {summary && (
          <>
            {" · "}
            <span className="text-cosmos-muted">
              마지막 갱신 {summary.last_updated_at ? formatDateTime(summary.last_updated_at) : "기록 없음"}
            </span>
          </>
        )}
      </p>

      <NextActions
        list={stale ? null : list}
        summary={summary}
        onPick={(id) => {
          setSelectedId(id);
          // 45차 M12 — 상세가 약 4,300px 아래에 열리고 화면은 그대로였다 · 문서 목록과 상세로 굴린다
          window.requestAnimationFrame(() => document.getElementById("company-documents")?.scrollIntoView({ block: "start", behavior: "smooth" }));
        }}
      />
      <RegistrationSteps summary={summary} list={stale ? null : list} profile={stale ? null : profile} searchTried={searchTried === organizationId} loading={stale || (summary === null && organizations.list === null && !organizations.error)} />

      {summary && (
        <p className="text-[12px] leading-4 text-cosmos-muted">
          회사 레코드: 생성 {formatDateTime(summary.organization.created_at)}
          {summary.organization.created_by ? ` · ${summary.organization.created_by}` : ""}
          {summary.organization.migrated_from_legacy ? " · 기존 단일 회사 저장소에서 이관됨" : ""} · 프로필 출처 {profileSourceLabel(summary.profile_source)}
        </p>
      )}

      {index && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={!index.embedding_available || readOnly || rebuilding}
            aria-busy={rebuilding}
            title={!index.embedding_available ? (index.note ?? "AI 검색이 꺼져 있어 검색 준비를 할 수 없습니다") : undefined}
            onClick={() => {
              // 누르는 동안 잠근다 — 전체 재색인이 여러 번 걸릴 수 있었다 (CMP-30).
              setRebuilding(true);
              rebuildOrganizationIndex(organizationId)
                .then((r) => {
                  setRebuildMessage(r.ok ? `AI 검색 준비 끝 — 문서 ${r.document_count}건 · 문장 ${r.chunk_count}개` : r.reason);
                  reload();
                })
                .catch((e: unknown) => setRebuildMessage(describe(e, "AI 검색 다시 준비에 실패했습니다.")))
                .finally(() => setRebuilding(false));
            }}
          >
            {rebuilding ? "준비 중…" : "AI 검색 다시 준비 (7단계)"}
          </Button>
          {rebuildMessage && <span className="text-[12px] text-cosmos-secondary">{rebuildMessage}</span>}
          {/* 비활성 사유는 툴팁이 아니라 화면 글자로 (ISSUE-033).
              **왜** 못 쓰는지는 백엔드가 말한다(`index.note`) — 크레딧이 바닥난 것을
              「설정이 없다」고만 적으면 있지도 않은 키 문제를 찾아 헤맨다
              (0920 §4-B-5 · ISSUE-078). */}
          {!index.embedding_available && (
            <span className="text-[12px] text-cosmos-amber" role="note">
              {index.note ?? "AI 검색이 꺼져 있어 검색 준비를 할 수 없습니다. 등록한 자료는 「등록됨(검색 준비 전)」으로 남습니다."}
            </span>
          )}
        </div>
      )}

      {/* 실패를 「불러오는 중」으로 보여주면 담당자가 기다리면 될 줄 안다.
          오류가 있으면 다시 시도할 길을 준다. */}
      {/* 자격 판정이 쓰는 값을 사람이 적는 자리 (0921 §4-D-3).
          예전에는 적을 자리가 없어 판정이 언제나 「확인 필요」에서 멈췄다. */}
      {!stale && <BidQualificationCard key={`${organizationId}-bid`} organizationId={organizationId} readOnly={demoReadOnly} />}

      {!stale && profile ? (
        <ProfileCard key={organizationId} organizationId={organizationId} profile={profile} onSaved={setProfile} readOnly={readOnly} />
      ) : !stale && profileError ? (
        <EmptyState title="회사 프로필을 불러오지 못했습니다" action={<Button variant="primary" onClick={reload}>다시 시도</Button>}>
          {profileError}
        </EmptyState>
      ) : (
        <LoadingState label="회사 프로필 불러오는 중" rows={3} />
      )}
      {/* 사업계획서 일반현황 — 문서를 조립할 때만 칸에 들어간다(AI 에 보내지 않음 · 29차 §3-B) */}
      {!stale && <PlanGeneralCard key={`${organizationId}-plan-general`} organizationId={organizationId} readOnly={demoReadOnly} />}

      <UploadForm
        key={`upload-${organizationId}`}
        organizationId={organizationId}
        organizationDataClass={summary?.organization.data_class ?? null}
        readOnly={readOnly}
        onUploaded={(doc) => {
          reload();
          setSelectedId(doc.id);
        }}
      />

      <LedgerImportPanel key={`ledger-${organizationId}`} organizationId={organizationId} onChanged={reload} readOnly={readOnly} />

      <section id="company-documents" aria-label="문서 목록과 상세" className="grid min-w-0 scroll-mt-20 gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0">
          {!stale && !list && listError ? (
            <EmptyState title="문서 목록을 불러오지 못했습니다" action={<Button variant="primary" onClick={reload}>다시 시도</Button>}>
              {listError}
            </EmptyState>
          ) : stale || !list ? (
            <LoadingState label="문서 목록 불러오는 중" rows={4} />
          ) : documents.length === 0 ? (
            // 목록이 비어 보이는 이유가 둘이다 — 「아직 안 올렸다」와 「등록부를 못 읽었다」.
            // 뒤쪽이면 사유를 그대로 적는다. 뭉개면 올려 둔 자료가 증발한 것으로 읽힌다.
            <EmptyState title={registryNote ? "회사자료 목록을 읽지 못했습니다" : "이 회사에 등록된 회사자료가 없습니다"}>
              {registryNote ??
                "AI가 근거를 만들지 않습니다. 위에서 계약서 · 실적증명서 · 결과보고서 등 파일을 올리면 글자를 읽어 문장을 뽑습니다. 그중 「쓰기」로 고른 문장만 근거가 됩니다. PDF · HWP · HWPX · DOCX · MD · TXT 를 그대로 올릴 수 있습니다. 다른 회사의 자료와 공개 데모의 가상 예시 자료는 여기 목록에 섞이지 않습니다."}
            </EmptyState>
          ) : (
            <div className="mc-panel overflow-hidden">
              <div className="mc-scroll max-h-[60vh] overflow-auto">
                <table className="mc-sticky-head w-full min-w-[720px] border-collapse text-[13px]" aria-label="회사자료 목록">
                  <thead>
                    <tr className="border-b border-cosmos-border text-left text-[12px] uppercase tracking-[0.1em] text-cosmos-muted">
                      <th scope="col" className="px-3 py-2.5 font-semibold">문서</th>
                      <th scope="col" className="w-24 px-3 py-2.5 font-semibold">종류</th>
                      <th scope="col" className="w-28 px-3 py-2.5 font-semibold">등급</th>
                      <th scope="col" className="w-32 px-3 py-2.5 font-semibold">상태</th>
                      <th scope="col" className="w-28 px-3 py-2.5 font-semibold">뽑은 · 고른 문장</th>
                      <th scope="col" className="w-36 px-3 py-2.5 font-semibold">등록</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((doc: CompanyDocument) => {
                      const active = doc.id === selectedId;
                      return (
                        // 행을 키보드로도 고를 수 있어야 한다 (ISSUE-033). 예전에는 행 전체를 단추(role=button)로 만들어
                        // 표의 행·칸 구조가 보조기기에서 사라졌다 (CMP-31) — 단추는 제목 칸 안에 두고, 행 클릭은 마우스용으로 남긴다.
                        <tr
                          key={doc.id}
                          onClick={() => setSelectedId(active ? null : doc.id)}
                          className={`cursor-pointer border-b border-cosmos-border/70 transition-colors last:border-b-0 ${active ? "bg-cosmos-blue/15" : "hover:bg-cosmos-elevated/50"}`}
                        >
                          <td className="px-3 py-2.5">
                            <button
                              type="button"
                              aria-pressed={active}
                              aria-label={`${doc.title} 상세 ${active ? "닫기" : "열기"}`}
                              onClick={(event) => {
                                event.stopPropagation();
                                setSelectedId(active ? null : doc.id);
                              }}
                              className="mc-focus block max-w-[360px] rounded text-left"
                            >
                              <span className="block truncate font-medium text-cosmos-text" title={doc.title}>{doc.title}</span>
                              <span className="block truncate text-[12px] text-cosmos-muted" title={doc.file_name}>{doc.file_name} · {formatBytes(doc.size_bytes)}</span>
                            </button>
                          </td>
                          <td className="px-3 py-2.5 text-cosmos-secondary">{doc.doc_type}</td>
                          <td className="px-3 py-2.5">
                            <Badge tone={dataClassTone(doc.metadata.data_class)}>{DATA_CLASS_LABELS[doc.metadata.data_class]}</Badge>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge tone={documentStatusLabel(doc, localToday()) === OUT_OF_PERIOD_LABEL ? "warn" : STATUS_TONE[doc.status]} glyph>
                              {documentStatusLabel(doc, localToday())}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[12px] tabular-nums text-cosmos-secondary">
                            {doc.candidate_count}개 중 {doc.approved_chunk_count}개 고름
                          </td>
                          <td className="px-3 py-2.5 text-[12px] text-cosmos-muted">{formatDateTime(doc.uploaded_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {list?.snapshot_note ? (
                // 배포 스냅샷이 직원 실명 때문에 뺀 문서가 있다는 표시.
                // 목록이 조용히 짧아지면 자료가 없는 것으로 오해한다.
                <p className="border-t border-cosmos-border px-3 py-2.5 text-[12px] leading-4 text-cosmos-muted">
                  {list.snapshot_note}
                </p>
              ) : null}
            </div>
          )}
        </div>
        {/* 좁은 폭(1280 미만)에서는 아래에서 올라오는 판 — 반투명 판 뒤로 표 글자가 비쳐 읽기 어려웠다. 판 밑에 불투명 바탕을 깐다. */}
        <div className={`${selectedId ? "fixed inset-x-2 bottom-2 z-40 flex max-h-[80vh] flex-col rounded-xl bg-cosmos-bg xl:static xl:max-h-none xl:rounded-none xl:bg-transparent" : "hidden xl:block"} xl:sticky xl:top-20 xl:z-auto xl:self-start`}>
          {selectedId ? (
            <DocumentDetail
              key={`${organizationId}:${selectedId}`}
              organizationId={organizationId}
              documentId={selectedId}
              onChanged={reload}
              onClose={() => setSelectedId(null)}
              readOnly={readOnly}
              nextReview={nextReview}
              onGoNext={(id) => setSelectedId(id)}
              organizationDataClass={summary?.organization.data_class ?? null}
            />
          ) : (
            <div className="mc-panel p-5 text-[13px] leading-6 text-cosmos-secondary">
              <p className="text-[14px] font-semibold text-cosmos-text">문서를 고르면 뽑은 문장을 봅니다 (5~6단계)</p>
              <p className="mt-2">고른 문장만 근거로 등록되고, 승인 시 자료 등급·공개 범위·유효기간을 기록합니다. 비활성 처리한 문서와 유효기간이 지난 문서는 매칭에서 빠집니다.</p>
            </div>
          )}
        </div>
      </section>

      <TestSearchPanel key={`search-${organizationId}`} organizationId={organizationId} embeddingAvailable={Boolean(index?.embedding_available)} offReason={index?.note ?? null} onTried={() => setSearchTried(organizationId)} />

      {/* 관리자에게만 보인다. hydration 전에는 쿠키를 읽을 수 없으므로 그때까지 그리지 않는다. */}
      {hydrated && canSeeActivity && (
        <RecentActivityPanel
          localMode={Boolean(organizations.list?.local_admin_mode)}
          organizationName={(id) => findOrganization(organizations.list, id)?.organization.display_name ?? null}
        />
      )}

      {/*
        여기 있던 문장은 담당자가 아니라 «운영자»에게 하는 말이었다.
        「organization_admin · editor · reviewer · viewer 권한, 사용자 인증, DB 저장,
        저장 자료 암호화가 필요합니다」 — 회사자료를 올리러 온 사람에게는 읽을 이유가
        없는 개발 용어이고, 화면 아래에 상시 붙어 있었다 (ISSUE-016 · ISSUE-021).
        운영 요건은 README 로 옮기고, 여기서는 **지금 이 사람에게 해당하는 사실**만 남긴다.

        「사내 배포 · 승인된 내부자료만」도 지운다. 그것은 화면이 정할 수 없는 값이고
        (로컬 개발에서도 그렇게 떴다), 배포 모드 문장은 이미 푸터가 한 곳에서 말한다.
      */}
      <p className="text-[12px] leading-4 text-cosmos-muted">
        {organizations.list?.local_admin_mode
          ? "지금은 로그인 없이 열려 있습니다. 누구든 이 화면에서 회사자료를 고칠 수 있으니, 공용 컴퓨터에서는 열어 두지 마세요."
          : me
            ? `${me.displayName}(${ROLE_LABELS[me.role]}) 계정으로 보고 있습니다. 바꾼 내용은 이 계정 이름으로 남습니다.`
            : "계정은 팀이 함께 쓰는 하나입니다. 누가 무엇을 바꿨는지는 각 기록의 「수정한 사람」으로만 남습니다."}
      </p>
    </AppShell>
  );
}

/**
 * 「← 보던 공고로 돌아가기」 — 저장된 선택(입찰 · 지원사업)으로. 고른 것이 없으면(합성 데모 포함) 숨긴다 (27차 LNK-06).
 * 자료를 승인한 뒤 근거를 다시 연결하러 돌아갈 길이 상단 메뉴뿐이었고, 지원사업에서 왔으면 그마저 없었다.
 */
function BackToSelectionLink() {
  const viewing = useSyncExternalStore(subscribeSelection, readSelection, readSelectionServer);
  if (!viewing || isDemoNoticeId(viewing)) return null;
  const support = isSupportProgramId(viewing);
  return (
    <Link
      href={support ? `/support/${encodeURIComponent(viewing)}` : `/analysis?notice=${encodeURIComponent(viewing)}`}
      className="mc-focus inline-flex min-h-9 items-center rounded-lg border border-cosmos-border-strong px-3 text-[12.5px] font-medium text-cosmos-cyan hover:border-cosmos-cyan/60"
      data-back-to-selection
    >
      ← 보던 {support ? "지원사업으로" : "공고로"} 돌아가기
    </Link>
  );
}
