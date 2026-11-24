"use client";

/**
 * 입찰 자격 회사자료 — **판정이 쓰는 값을 사람이 적는 자리** (0921.md §4-D-3).
 *
 * ## 왜 필요한가
 *
 * 자격 판정 v2 는 회사 쪽 사실을 본다 — 나라장터 등록 업종·소재지·혼자 맡을 수 있는 최대 사업비·공동수급
 * 파트너·제안서 준비 일수. 그런데 그 값을 적을 자리가 화면 어디에도 없었다. 그래서 판정이
 * 언제나 「확인 필요」에서 멈췄고, 갭 리포트는 「적으면 33건이 확정된다」고만 말했다.
 *
 * ## 규칙
 *
 * - **저장은 사람이 한다.** 화면이 자동으로 채우거나 저장하지 않는다.
 * - **빈 칸은 「미입력」이다.** 「없음」이 아니다 — 판정은 빈 값을 「불가」로 읽지 않는다.
 * - **사업자등록증 종목은 판정에 쓰지 않는다.** 나라장터 등록 업종과 다른 것이라
 *   「등록 후보」 힌트로만 보여 준다(0921 §2).
 */

import { useEffect, useState } from "react";

import { Button, InlineAlert, LoadingState } from "@/components/ui/primitives";
import { getDeliveryCapacity, isStaleWrite, saveCapabilityProfile } from "@/lib/api";
import { currentUserName } from "@/lib/currentUser";
import { formatDateTime } from "@/lib/cosmos/format";
import { describeFailure } from "@/lib/errors";
import { isSmeRow, readinessRows, readinessToSave, validityOf, type ReadinessRow } from "@/lib/firstTimeGuide";
import type { SmeGrade } from "@/types/capability";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import { analysisContext } from "@/lib/organization";
import { jointPartnerToSave, partnerChoiceOf, textLines, type PartnerChoice } from "@/lib/capacityForm";
import {
  EXPIRED_HEAD,
  EXPIRING_SOON_HEAD,
  GUIDE_LINK_TEXT,
  RANKING_METHOD_FIELD,
  RANKING_METHODS,
  READINESS_HELD_LABELS,
  READINESS_HELP,
  READINESS_TITLE,
  SME_GRADE_HELP,
  SME_GRADE_LABEL,
  SME_GRADES,
} from "@/lib/terms";
import { GuideContextLink } from "@/components/guide/GuideContextLink";
import BlankFieldsNotice from "@/components/company/BlankFieldsNotice";
import CompanyChecksPanel from "@/components/company/CompanyChecksPanel";
import { clearDraft, loadDraft, saveDraft } from "@/lib/unsavedGuard";
import { requestConsent } from "@/lib/consentPrompt";
import { VIEWER_LOCK_LABEL, VIEWER_LOCK_REASON, useViewerLock } from "@/lib/viewerLock";
import { READINESS_GUIDE } from "@/lib/guide";
import type { DeliveryCapacity, RankingMethod } from "@/types/capability";

/** 사업자등록증 종목 → 나라장터 등록 업종 후보. **자동 등록이 아니라 힌트다** (0921 §2). */
const INDUSTRY_HINTS: { item: string; code: string; name: string }[] = [
  { item: "응용 소프트웨어 개발 및 공급업", code: "1426", name: "소프트웨어개발업" },
  { item: "컴퓨터 시스템 통합 자문 및 구축 서비스업", code: "1468", name: "소프트웨어사업자(컴퓨터관련서비스사업)" },
  { item: "데이터베이스 및 온라인 정보 제공업", code: "1470", name: "데이터베이스및온라인정보제공업" },
];

const LABEL = "text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted";
const INPUT =
  "mc-focus min-h-9 w-full rounded-lg border border-cosmos-border bg-cosmos-panel px-2.5 text-[12.5px] text-cosmos-text";

/** 「1468:소프트웨어사업자」 한 줄씩. 코드만 적어도 받는다. */
function parseIndustries(text: string): { code: string; name: string }[] {
  return text
    .split(/[\n,]+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [code, ...rest] = line.split(":");
      return { code: code.trim(), name: rest.join(":").trim() };
    })
    .filter((entry) => entry.code);
}

/**
 * 원 단위 칸 — 숫자와 쉼표만 받는다 (CMP-12). 예전에는 숫자 아닌 글자를 지우고 저장해
 * 「2억」이 2원이 되었고, 그 뒤로 모든 공고가 규모 초과로 판정됐다. 빈 칸은 미입력(null).
 */
function wonOrNull(label: string, raw: string): number | null {
  const value = raw.trim();
  if (!value) return null;
  if (!/^[\d,]+$/.test(value)) throw new Error(`「${label}」은 숫자만 적어 주세요 (예: 200000000). 「억」·「만」 같은 단위는 읽지 않습니다.`);
  return Number(value.replace(/,/g, ""));
}

/** 제안서 준비 일수 — 0~60 사이 숫자 (CMP-13). 빈 칸 · 「4일」을 0으로 저장해 「촉박」 판정이 사라지던 것을 막는다. */
function leadDaysOrThrow(raw: string): number {
  const value = raw.trim();
  if (!/^\d+$/.test(value) || Number(value) > 60) throw new Error("「제안서 준비 일수」는 0~60 사이 숫자로 적어 주세요 (비울 수 없습니다).");
  return Number(value);
}

function formatIndustries(rows: { code: string; name: string }[]): string {
  return rows.map((row) => (row.name ? `${row.code}:${row.name}` : row.code)).join("\n");
}

/** 연구소 칸 네 갈래 + 옛 「보유」(종류 모름). 저장 모양은 하위 호환 — has_research_department 그대로 + research_department_kind. */
type ResearchChoice = "" | "lab" | "dept" | "no" | "legacy";

function researchChoiceOf(has: boolean | null | undefined, kind: "lab" | "dept_only" | null): ResearchChoice {
  if (has === false) return "no";
  if (has !== true) return "";
  return kind === "lab" ? "lab" : kind === "dept_only" ? "dept" : "legacy";
}

function researchToSave(choice: ResearchChoice): { has_research_department: boolean | null; research_department_kind: "lab" | "dept_only" | null } {
  if (choice === "lab") return { has_research_department: true, research_department_kind: "lab" };
  if (choice === "dept") return { has_research_department: true, research_department_kind: "dept_only" };
  if (choice === "legacy") return { has_research_department: true, research_department_kind: null };
  if (choice === "no") return { has_research_department: false, research_department_kind: null };
  return { has_research_department: null, research_department_kind: null };
}

/** 입찰 자격 자료 폼 칸 전부 — 임시 저장 · 되살리기 · 「바뀐 것이 있나」를 이 한 덩어리로 본다(43차 M28). */
interface QualificationForm {
  industries: string;
  items: string;
  region: string;
  ceiling: string;
  leadDays: string;
  partner: PartnerChoice;
  partnerNote: string;
  rankingMethod: RankingMethod;
  revenue: string;
  research: ResearchChoice;
  dataProducts: string;
  digitalProducts: string;
  directItems: string;
  suppliers: string;
  programs: string;
  readiness: ReadinessRow[];
}

function formOf(value: DeliveryCapacity): QualificationForm {
  return {
    industries: formatIndustries(value.registered_industries ?? []),
    items: (value.business_items ?? []).join("\n"),
    region: value.location_region ?? "",
    ceiling: value.budget_ceiling_krw === null ? "" : String(value.budget_ceiling_krw),
    leadDays: String(value.proposal_lead_days ?? 4),
    partner: partnerChoiceOf(value.joint_bid_partner),
    partnerNote: value.joint_bid_partner?.note ?? "",
    rankingMethod: value.ranking_method ?? "score",
    revenue: value.revenue_krw_last_year == null ? "" : String(value.revenue_krw_last_year),
    research: researchChoiceOf(value.has_research_department, value.research_department_kind ?? null),
    dataProducts: (value.data_products ?? []).join("\n"),
    digitalProducts: (value.digital_products ?? []).join("\n"),
    directItems: (value.direct_production_items ?? []).join("\n"),
    suppliers: (value.supplier_registrations ?? []).join("\n"),
    programs: (value.completed_programs ?? []).join("\n"),
    readiness: readinessRows(value.credentials ?? []),
  };
}

/** 단독 상한 글(원 · 빈칸) → 「2억원 · 미입력」 — 확인 창 전후 값(43차 Q28). */
function ceilingWord(text: string): string {
  const digits = text.replace(/[^0-9]/g, "");
  if (!digits) return "미입력";
  const won = Number(digits);
  return won >= 100_000_000 ? `${(won / 100_000_000).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}억원` : `${won.toLocaleString("ko-KR")}원`;
}

export default function BidQualificationCard({ organizationId, readOnly }: { organizationId: string; readOnly: boolean }) {
  const viewer = useViewerLock();
  // 43차 M26 — 열람자는 칸 · 저장을 잠근다(서버도 막는다 · 다 채운 뒤에야 403 을 봤다)
  const locked = readOnly || viewer;
  const draftKey = `bid-qualification:${organizationId}`;
  const [restoredNote, setRestoredNote] = useState(false);
  // 고치기를 시작한 저장본의 시각(43차 마지막 검토) — 임시 저장본을 되살리면 그 저장본이 읽었던 시각으로 저장해, 그사이 남이 저장했으면 409 로 막는다
  const [baseAt, setBaseAt] = useState<string | null>(null);
  const [staleNote, setStaleNote] = useState(false);
  const [capacity, setCapacity] = useState<DeliveryCapacity | null>(null);
  const [industries, setIndustries] = useState("");
  const [items, setItems] = useState("");
  const [region, setRegion] = useState("");
  const [ceiling, setCeiling] = useState("");
  const [leadDays, setLeadDays] = useState("4");
  const [partner, setPartner] = useState<PartnerChoice>("");
  const [partnerNote, setPartnerNote] = useState("");
  // 우선순위 계산 방식(37차 §3-A) — 「모름」이 없다. 옛 응답(칸 없음)은 점수순.
  const [rankingMethod, setRankingMethod] = useState<RankingMethod>("score");
  // 기업마당 공고문 판정이 쓰는 값 (0924 §4-A-5). 빈 칸은 **미입력**이다.
  const [revenue, setRevenue] = useState("");
  // 연구소 네 갈래(36차 R35-DV-02) — 「전담부서 인정서만 보유한 기업은 미포함」 공고를 가른다. legacy = 옛 「보유」(종류 모름)
  const [research, setResearch] = useState<ResearchChoice>("");
  const [dataProducts, setDataProducts] = useState("");
  // 43차 Q14 · Q24 — 대표가 적는 칸(프로그램은 값을 고르지 않음). 비면 「확인 필요」
  const [digitalProducts, setDigitalProducts] = useState("");
  const [directItems, setDirectItems] = useState("");
  const [suppliers, setSuppliers] = useState("");
  const [programs, setPrograms] = useState("");
  // 준비 상태(나라장터 등록 · 인증서 · 확인서) — 이미 저장되는 `credentials` 를 화면에 보인다(31차 §3-B · 제품 반영 안 2-1 · 3-2)
  const [readiness, setReadiness] = useState<ReadinessRow[]>([]);
  const nowMs = useNowMs();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function applyForm(f: QualificationForm) {
    setIndustries(f.industries);
    setItems(f.items);
    setRegion(f.region);
    setCeiling(f.ceiling);
    setLeadDays(f.leadDays);
    setPartner(f.partner);
    setPartnerNote(f.partnerNote);
    setRankingMethod(f.rankingMethod);
    setRevenue(f.revenue);
    setResearch(f.research);
    setDataProducts(f.dataProducts);
    setDigitalProducts(f.digitalProducts);
    setDirectItems(f.directItems);
    setSuppliers(f.suppliers);
    setPrograms(f.programs);
    setReadiness(f.readiness);
  }

  useEffect(() => {
    let alive = true;
    getDeliveryCapacity(analysisContext("", organizationId))
      .then((value: DeliveryCapacity) => {
        if (!alive) return;
        setCapacity(value);
        // 43차 M28 — 저장하지 않은 폼이 남아 있으면 되살린다(세션이 끝나 새로 고쳐도 잃지 않게)
        const raw = loadDraft(draftKey);
        let restored: QualificationForm | null = null;
        let restoredBase: string | null | undefined;
        try {
          const parsed = raw ? (JSON.parse(raw) as Partial<QualificationForm> & { _base?: string | null }) : null;
          if (parsed) {
            const { _base, ...fields } = parsed;
            restored = { ...formOf(value), ...fields };
            restoredBase = _base;
          }
        } catch {
          restored = null;
        }
        applyForm(restored ?? formOf(value));
        setRestoredNote(restored !== null);
        setBaseAt(restoredBase !== undefined ? restoredBase : value.updated_at ?? null);
        // 「회사자료에서 고치기 →」(`/company#readiness`)로 오면 카드가 늦게 그려져 그 자리까지 내려가지 않는다 — 그린 뒤 내려간다
        if (window.location.hash === "#readiness") {
          requestAnimationFrame(() => document.getElementById("readiness")?.scrollIntoView({ block: "start" }));
        }
      })
      .catch((e: unknown) => {
        if (alive) setError(describeFailure(e, "회사 역량 자료를 불러오지 못했습니다."));
      });
    return () => {
      alive = false;
    };
  }, [organizationId, draftKey]);

  const form: QualificationForm = {
    industries, items, region, ceiling, leadDays, partner, partnerNote, rankingMethod, revenue, research,
    dataProducts, digitalProducts, directItems, suppliers, programs, readiness,
  };
  const dirty = capacity !== null && !locked && JSON.stringify(form) !== JSON.stringify(formOf(capacity));
  const formJson = JSON.stringify(form);
  useEffect(() => {
    if (capacity === null) return;
    if (dirty) saveDraft(draftKey, JSON.stringify({ ...(JSON.parse(formJson) as QualificationForm), _base: baseAt }));
    else clearDraft(draftKey);
  }, [capacity, dirty, draftKey, formJson, baseAt]);

  /** 회사 단위 확인 · 「안 적음」 저장(내 저장) 뒤 — 고치기 기준이 지금 저장본이었으면 함께 앞으로(옛 임시 저장본 기준이면 그대로 두어 409). */
  const onChildSaved = (saved: DeliveryCapacity) => {
    setBaseAt((prev) => (prev === (capacity?.updated_at ?? null) ? saved.updated_at ?? null : prev));
    setCapacity(saved);
  };

  // 불러오는 동안 · 실패했을 때도 자리를 남긴다 — 예전에는 카드가 통째로 사라져 실패가 보이지 않았다 (CMP-32).
  if (capacity === null) {
    return error ? (
      <section className="mc-panel flex flex-col gap-2 px-4 py-3" aria-label="입찰 자격 자료">
        <h2 className="text-[14px] font-semibold text-cosmos-text">입찰 자격 자료</h2>
        <InlineAlert tone="fail">{error}</InlineAlert>
      </section>
    ) : (
      <LoadingState label="입찰 자격 자료 불러오는 중" rows={2} />
    );
  }

  async function save() {
    if (!capacity) return;
    setMessage(null);
    setError(null);
    let ceilingKrw: number | null;
    let revenueKrw: number | null;
    let lead: number;
    try {
      ceilingKrw = wonOrNull("혼자 맡을 수 있는 최대 사업비(원)", ceiling);
      revenueKrw = wonOrNull("지난해 매출 (원)", revenue);
      lead = leadDaysOrThrow(leadDays);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    // 43차 Q28 — 순서 방식 · 단독 상한은 사업기회 순서 전체를 바꾼다. 전후 값을 보이고 묻는다(활동 기록에도 남는다).
    const before = formOf(capacity);
    const changes = [
      before.rankingMethod !== rankingMethod
        ? `순서 방식: ${RANKING_METHODS[before.rankingMethod].label} → ${RANKING_METHODS[rankingMethod].label}`
        : null,
      ceilingWord(before.ceiling) !== ceilingWord(ceiling) ? `단독 상한: ${ceilingWord(before.ceiling)} → ${ceilingWord(ceiling)}` : null,
    ].filter((line): line is string => line !== null);
    if (changes.length > 0) {
      // 45차 L5 — 화면 안 확인 창
      const ok = await requestConsent({
        title: "순서 방식 · 단독 상한을 바꿀까요?",
        body: `${changes.join(" · ")} — 사업기회 목록 · 레이더 · 브리핑의 순서와 대형 · 파트너형 구분이 바뀝니다. 다른 사람 화면에도 그대로 보입니다.`,
        confirmLabel: "저장",
        cancelLabel: "취소",
      });
      if (!ok) {
        // 45차 M23 — 「취소」면 고른 순서 방식 · 상한도 저장된 값으로 되돌린다(라디오가 새 값에 남아 임시 저장됐다)
        setRankingMethod(before.rankingMethod);
        setCeiling(before.ceiling);
        return;
      }
    }
    setBusy(true);
    try {
      const saved = await saveCapabilityProfile(
        {
          developer_count: capacity.developer_count,
          team_note: capacity.team_note,
          skills: capacity.skills,
          // 「모름 + 메모 없음」 기본 줄은 보내지 않는다 · 이미 저장된 줄은 이름 · 출처 그대로(31차 §3-B)
          credentials: readinessToSave(readiness, `회사자료 준비 상태 · ${currentUserName() || "담당자"}`),
          concurrent_project_limit: capacity.concurrent_project_limit,
          note: capacity.note,
          // 빈 칸은 **미입력(null)** 이다. 0 이나 빈 문자열로 저장하면 「없다」가 되어
          // 판정이 잘못된 근거를 갖는다.
          budget_ceiling_krw: ceilingKrw,
          registered_industries: parseIndustries(industries),
          business_items: items.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean),
          location_region: region.trim() || null,
          // 저장본이 「모름(null)」이고 칸을 건드리지 않았으면 null 그대로 — 「없다고 적음」으로 바꾸지 않는다(33차 §3-B-3)
          joint_bid_partner: jointPartnerToSave(partner, partnerNote),
          proposal_lead_days: lead,
          ranking_method: rankingMethod,
          // 기업마당 공고문 판정이 쓰는 값 (0924 §4-A-5).
          revenue_krw_last_year: revenueKrw,
          ...researchToSave(research),
          data_products: textLines(dataProducts),
          digital_products: textLines(digitalProducts),
          direct_production_items: textLines(directItems),
          supplier_registrations: textLines(suppliers),
          // 한 줄 안의 쉼표는 그 줄의 글이다 — 「없음 확인 — …(검수자 조사 …, docs/…)」가 두 줄로 쪼개졌다(33차 §3-B-3)
          completed_programs: textLines(programs),
          updated_by: currentUserName() || "담당자",
          // 43차 M25 — 처음 읽은 저장 시각. 그사이 다른 사람이 저장했으면 서버가 막는다(말없이 되돌리지 않게)
          expected_updated_at: baseAt,
        },
        analysisContext("", organizationId),
      );
      clearDraft(draftKey);
      setRestoredNote(false);
      setStaleNote(false);
      setBaseAt(saved.updated_at ?? null);
      setCapacity(saved);
      // 저장된 값을 칸에 다시 보여 준다 — 쉼표를 뺀 숫자 그대로가 서버 값이다.
      setCeiling(saved.budget_ceiling_krw === null ? "" : String(saved.budget_ceiling_krw));
      setRevenue(saved.revenue_krw_last_year == null ? "" : String(saved.revenue_krw_last_year));
      setLeadDays(String(saved.proposal_lead_days ?? lead));
      setReadiness(readinessRows(saved.credentials ?? []));
      setPartner(partnerChoiceOf(saved.joint_bid_partner));
      setPartnerNote(saved.joint_bid_partner?.note ?? "");
      setRankingMethod(saved.ranking_method ?? "score");
      setMessage("저장했습니다. 사업기회 목록이나 레이더를 새로고침하면 참가자격 판정 · 순서에 반영됩니다.");
    } catch (e: unknown) {
      setStaleNote(isStaleWrite(e));
      setError(describeFailure(e, "저장하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  const hinted = INDUSTRY_HINTS.filter((hint) =>
    items.split(/[\n,]+/).some((line) => line.trim() && hint.item.includes(line.trim())),
  );

  return (
    <section className="mc-panel flex flex-col gap-3 px-4 py-3" aria-label="입찰 자격 자료">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[14px] font-semibold text-cosmos-text">입찰 자격 자료</h2>
        <p className="text-[12px] text-cosmos-muted">
          참가 가능 여부 판정에 쓰는 값입니다. 모르는 칸은 비워 두세요. <strong className="text-cosmos-text">빈 칸은 「불가」가 아니라 「확인 필요」로</strong> 남습니다.
        </p>
      </div>

      {/* 38차 §3-C-7 — 비어 있어서 판정이 멈춘 칸과 그 칸 때문에 「확인 필요」로 남은 공고 수 */}
      <BlankFieldsNotice organizationId={organizationId} capacityUpdatedAt={capacity.updated_at ?? null} locked={locked} onCapacitySaved={onChildSaved} />

      {/* 43차 결정 2 — 나라장터 등록 · 부정당 제재 · 체납을 회사 단위로 한 번(유효기간) */}
      <CompanyChecksPanel organizationId={organizationId} capacity={capacity} readOnly={locked} onSaved={onChildSaved} />
      {restoredNote && (
        <InlineAlert tone={baseAt !== (capacity.updated_at ?? null) ? "warn" : "info"} role="status">
          저장하지 않은 입찰 자격 자료를 되살렸습니다 — 확인하고 「저장」을 누르세요.
          {baseAt !== (capacity.updated_at ?? null) && " 그사이 다른 사람이 저장했습니다 — 저장하면 막히니 「다시 불러오기」로 새 값에서 고치세요."}
        </InlineAlert>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={LABEL}>나라장터 등록 업종</span>
          <textarea
            className={`${INPUT} min-h-[4.5rem] py-1.5`}
            value={industries}
            onChange={(e) => setIndustries(e.target.value)}
            disabled={locked}
            // 예시가 적어 둔 값처럼 보였다(39차 §3-G) — 「예:」를 붙이고 어디서 확인하는지 적는다(흐린 글)
            placeholder={"예: 1468 — 경쟁입찰참가자격등록증의 업종 표에서 확인\n(한 줄에 하나 · 코드만 적어도 됩니다)"}
          />
          <span className="text-[12px] leading-4 text-cosmos-muted">
            한 줄에 하나. 「코드:이름」 또는 코드만. <strong className="text-cosmos-text">판정에 쓰는 것은 이 칸뿐입니다.</strong>
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className={LABEL}>사업자등록증 종목</span>
          <textarea
            className={`${INPUT} min-h-[4.5rem] py-1.5`}
            value={items}
            onChange={(e) => setItems(e.target.value)}
            disabled={locked}
            placeholder={"응용 소프트웨어 개발 및 공급업"}
          />
          <span className="text-[12px] leading-4 text-cosmos-muted">
            세무서 종목입니다. 나라장터 등록 업종과 <strong className="text-cosmos-text">다른 것</strong>이라 판정에 쓰지 않습니다.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className={LABEL}>직접생산 보유 품명</span>
          <textarea
            className={`${INPUT} min-h-[4.5rem] py-1.5`}
            value={directItems}
            onChange={(e) => setDirectItems(e.target.value)}
            disabled={locked}
            placeholder={"예: 품명 세부품명번호(10자리) — 직접생산확인증명서에서 확인\n(한 줄에 하나)"}
          />
          <span className="text-[12px] leading-4 text-cosmos-muted">
            공고가 요구하는 세부품명과 견줍니다. 맞으면 그 조항은 통과, 다르면 「확인 필요 — 보유 ○ · 요구 ○」. 비우면 「확인 필요」.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className={LABEL}>본사 시·도</span>
          <input
            className={INPUT}
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            disabled={locked}
            placeholder="전남광주"
          />
          <span className="text-[12px] leading-4 text-cosmos-muted">
            지역 제한 공고는 <strong className="text-cosmos-text">본사 주소의 시·도</strong>로 판정합니다(위 「활동 지역」과 별개). 비우면 회사 주소에서 읽습니다.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className={LABEL}>혼자 맡을 수 있는 최대 사업비(원)</span>
          <input
            className={INPUT}
            value={ceiling}
            onChange={(e) => setCeiling(e.target.value)}
            disabled={locked}
            inputMode="numeric"
            placeholder="200,000,000 (2억)"
          />
          <span className="text-[12px] leading-4 text-cosmos-muted">
            이보다 큰 공고는 숨기지 않고 「확인 필요」로 봅니다 — 다른 회사와 함께 참가할 수 있는지에 따라 할 일을 알려 줍니다. 숫자만(쉼표 가능). 비워도 「확인 필요」로 남습니다.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className={LABEL}>제안서 준비 일수</span>
          <input
            className={INPUT}
            value={leadDays}
            onChange={(e) => setLeadDays(e.target.value)}
            disabled={locked}
            inputMode="numeric"
          />
          <span className="text-[12px] leading-4 text-cosmos-muted">
            0~60 사이 숫자. 마감까지 이보다 적게 남은 공고는 「촉박」으로 봅니다.
          </span>
        </label>

        <div className="flex flex-col gap-1">
          <span className={LABEL}>공동수급 파트너</span>
          <select
            className={INPUT}
            aria-label="공동수급 파트너"
            value={partner}
            onChange={(e) => {
              const next = e.target.value as PartnerChoice;
              setPartner(next);
              // 「모름」이면 메모는 저장되지 않는다(저장할 때만 null · jointPartnerToSave) — 칸은 잠그되 글은 비우지 않는다.
              // 비우면 잠깐 「모름」으로 바꿨다 되돌릴 때 저장된 메모가 지워졌다(36차 PLAN-05 · 35차 FD-10 의 부작용).
            }}
            disabled={locked}
          >
            <option value="">모름</option>
            <option value="yes">있음 — 함께 참가할 회사를 확보했다</option>
            <option value="no">없음(확인함)</option>
          </select>
          <input
            className={INPUT}
            aria-label="공동수급 파트너 메모"
            value={partnerNote}
            onChange={(e) => setPartnerNote(e.target.value)}
            disabled={locked || partner === ""}
            placeholder={partner === "" ? "있음 · 없음을 고르면 메모를 적을 수 있습니다" : "파트너 후보·메모"}
          />
          {partner === "" && (
            <span className="text-[12px] leading-4 text-cosmos-muted" data-partner-note-hint>
              모름이면 메모는 저장되지 않습니다.
            </span>
          )}
        </div>

        {/* 우선순위 계산 방식 (37차 §3-A · 담당자 결정 2026-10-14) — 점수는 그대로이고 사업기회 · 레이더 · 대시보드 첫 공고의 순서만 바뀐다. */}
        <div className="flex flex-col gap-1 sm:col-span-2" data-ranking-method>
          <span className={LABEL}>{RANKING_METHOD_FIELD}</span>
          <div role="radiogroup" aria-label={RANKING_METHOD_FIELD} className="flex flex-col gap-1.5">
            {(Object.keys(RANKING_METHODS) as RankingMethod[]).map((key) => (
              <label key={key} className="flex items-start gap-2 text-[12.5px] text-cosmos-text">
                <input
                  type="radio"
                  name="ranking-method"
                  className="mt-0.5"
                  value={key}
                  checked={rankingMethod === key}
                  onChange={() => setRankingMethod(key)}
                  disabled={locked}
                />
                <span>{RANKING_METHODS[key].help}</span>
              </label>
            ))}
          </div>
          <span className="text-[12px] leading-4 text-cosmos-muted">
            점수(회사 기준 검토 우선순위)는 어느 방식에서나 같습니다. 사업기회 목록 · 레이더 · 입찰 분석 첫 공고의 순서만 바뀝니다.
          </span>
        </div>
      </div>

      {/*
        **기업마당 공고문 판정이 쓰는 값** (0924 §4-A-5).
        공고문이 요구하는데 앱이 회사 쪽 값을 몰라 판정하지 못하던 것들이다.
        비워 두면 「확인 필요」에서 멈춘다 — 「없다」로 읽지 않는다.
      */}
      <div className="flex flex-col gap-2 border-t border-cosmos-border pt-3">
        <p className="text-[12px] text-cosmos-muted">
          <strong className="text-cosmos-text">기업마당 지원사업 판정</strong>이 쓰는 값입니다. 공고문이 매출·연구소·
          데이터 상품·선행 사업을 요구할 때 이 칸이 비어 있으면 판정이 「확인 필요」에서 멈춥니다.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1">
            <span className={LABEL}>지난해 매출 (원)</span>
            <input
              className={INPUT}
              value={revenue}
              onChange={(e) => setRevenue(e.target.value)}
              disabled={locked}
              inputMode="numeric"
              placeholder="1,000,000,000 (10억)"
            />
            <span className="text-[12px] leading-4 text-cosmos-muted">
              「매출 10억 이상」 같은 요건을 이 값으로 잽니다. 비우면 판정하지 않습니다.
            </span>
          </label>

          <label className="flex flex-col gap-1">
            <span className={LABEL}>기업부설연구소·전담부서</span>
            <select
              className={INPUT}
              value={research}
              onChange={(e) => setResearch(e.target.value as ResearchChoice)}
              disabled={locked}
            >
              <option value="">모름</option>
              <option value="lab">기업부설연구소</option>
              <option value="dept">연구개발전담부서만</option>
              <option value="no">없음(확인함)</option>
              {research === "legacy" && <option value="legacy">보유(종류를 골라 주세요)</option>}
            </select>
            <span className="text-[12px] leading-4 text-cosmos-muted">
              「기업부설연구소만 인정(전담부서 미포함)」 공고가 있어 둘을 나눕니다. 「없음(확인함)」은 «모른다»가 아니라 «확인했고 없다»입니다 — 그때만 「불가」로 갑니다.
            </span>
          </label>

          <label className="flex flex-col gap-1">
            <span className={LABEL}>데이터 상품</span>
            <textarea
              className={`${INPUT} min-h-[4.5rem] py-1.5`}
              value={dataProducts}
              onChange={(e) => setDataProducts(e.target.value)}
              disabled={locked}
              placeholder={"AI 학습용 공공조달 데이터셋"}
            />
            <span className="text-[12px] leading-4 text-cosmos-muted">
              데이터 품질인증·가치평가 지원사업이 이 값을 요구합니다. 한 줄에 하나.
            </span>
          </label>

          <label className="flex flex-col gap-1">
            <span className={LABEL}>보유 디지털 제품(서비스)</span>
            <textarea
              className={`${INPUT} min-h-[4.5rem] py-1.5`}
              value={digitalProducts}
              onChange={(e) => setDigitalProducts(e.target.value)}
              disabled={locked}
              placeholder={"예: 제품 · 서비스 이름(한 줄에 하나)"}
            />
            <span className="text-[12px] leading-4 text-cosmos-muted">
              「디지털 제품(서비스)를 보유한 기업」 요건이 이 값을 봅니다. 사업영역 낱말로는 「가능」을 내지 않습니다 — 비우면 「확인 필요」.
            </span>
          </label>

          <label className="flex flex-col gap-1">
            <span className={LABEL}>공급기업 등록</span>
            <textarea
              className={`${INPUT} min-h-[4.5rem] py-1.5`}
              value={suppliers}
              onChange={(e) => setSuppliers(e.target.value)}
              disabled={locked}
              placeholder={"스마트공장 공급기업\n데이터바우처 공급기업"}
            />
            <span className="text-[12px] leading-4 text-cosmos-muted">
              공급기업으로 등록해 둔 사업. 간접 참여(공급기업) 판정이 이 값을 봅니다.
            </span>
          </label>

          <label className="flex flex-col gap-1 sm:col-span-2">
            <span className={LABEL}>완료한 선행 사업</span>
            <textarea
              className={`${INPUT} min-h-[3.5rem] py-1.5`}
              value={programs}
              onChange={(e) => setPrograms(e.target.value)}
              disabled={locked}
              placeholder={"예: 스마트제조혁신R&D 완료과제"}
            />
            <span className="text-[12px] leading-4 text-cosmos-muted">
              「스마트제조혁신R&amp;D 완료과제」처럼 후속 과제의 신청 자격이 되는 사업입니다.
              확인해 보니 없으면 <strong className="text-cosmos-text">「없음 확인」</strong>이라고 적으세요 —
              빈 칸(모름)과 달리 그때는 판정이 「불가」로 확정됩니다.
            </span>
          </label>
        </div>
      </div>

      {/*
        준비 상태 — 나라장터 등록 · 인증서 · 확인서 (31차 §3-B · 제품 반영 안 2-1 · 3-2). 기존 카드 안의 묶음 하나다.
        판정에는 **중소기업(소상공인) 확인서 줄만** 쓴다(10-10 담당자 결정 — 나머지 줄은 3-3 을 하지 않은 그대로 참고용).
        있음/없음/모름 · 메모 · 유효기간 끝나는 날 · 중소기업 확인서 줄만 「확인서 구분」.
      */}
      {/* id — 실전 가이드 · 다른 화면에서 `/company#readiness` 로 바로 온다(32차 §3-A-6) */}
      <fieldset id="readiness" className="flex min-w-0 scroll-mt-24 flex-col gap-2 border-t border-cosmos-border pt-3">
        <legend className="text-[12.5px] font-semibold text-cosmos-text">{READINESS_TITLE}</legend>
        <p className="text-[12px] leading-5 text-cosmos-muted">{READINESS_HELP}</p>
        <ul className="flex flex-col gap-2">
          {readiness.map((row, index) => {
            const state = nowMs === null ? null : validityOf(row.validUntil, nowMs);
            const update = (patch: Partial<ReadinessRow>) =>
              setReadiness((rows) => rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
            return (
              <li
                key={`${row.label}-${index}`}
                className="grid min-w-0 gap-1.5 rounded-lg border border-cosmos-border px-2.5 py-2 sm:grid-cols-[minmax(0,12rem)_auto_minmax(0,1fr)_auto] sm:items-center"
              >
                <span className="min-w-0 break-words text-[12.5px] text-cosmos-text">
                  {row.label}
                  {READINESS_GUIDE[row.label] && (
                    <>
                      {" "}
                      <GuideContextLink href={READINESS_GUIDE[row.label]} className="text-[12px]">
                        {GUIDE_LINK_TEXT.readiness}
                      </GuideContextLink>
                    </>
                  )}
                  {state && (
                    <span className={`ml-1.5 text-[12px] ${state === "expired" ? "text-cosmos-red" : "text-cosmos-amber"}`}>
                      {state === "expired" ? EXPIRED_HEAD : EXPIRING_SOON_HEAD}
                    </span>
                  )}
                </span>
                <select
                  className={`${INPUT} sm:w-24`}
                  aria-label={`${row.label} — 있음 · 없음 · 모름`}
                  value={row.held === true ? "yes" : row.held === false ? "no" : ""}
                  onChange={(e) => update({ held: e.target.value === "yes" ? true : e.target.value === "no" ? false : null })}
                  disabled={locked}
                >
                  <option value="">{READINESS_HELD_LABELS.unknown}</option>
                  <option value="yes">{READINESS_HELD_LABELS.yes}</option>
                  <option value="no">{READINESS_HELD_LABELS.no}</option>
                </select>
                <input
                  className={INPUT}
                  aria-label={`${row.label} 메모`}
                  value={row.note}
                  onChange={(e) => update({ note: e.target.value })}
                  disabled={locked}
                  maxLength={400}
                  placeholder="메모 (발급처 · 번호 끝자리 등)"
                />
                <label className="flex min-w-0 items-center gap-1.5 text-[12px] text-cosmos-muted">
                  <span className="shrink-0 whitespace-nowrap">유효기간</span>
                  <input
                    type="date"
                    className={`${INPUT} min-w-0 flex-1 sm:w-40 sm:flex-none`}
                    aria-label={`${row.label} 유효기간 끝나는 날`}
                    value={row.validUntil}
                    onChange={(e) => update({ validUntil: e.target.value })}
                    disabled={locked}
                  />
                </label>
                {isSmeRow(row.label) && (
                  // 확인서 구분 — 「있음」일 때만 고른다. 나라장터 「소기업 · 소상공인만」 조항을 이것으로 가른다(10-10)
                  <label className="flex min-w-0 flex-wrap items-center gap-1.5 text-[12px] text-cosmos-muted sm:col-span-4">
                    <span className="shrink-0 whitespace-nowrap">{SME_GRADE_LABEL}</span>
                    <select
                      className={`${INPUT} sm:w-32`}
                      aria-label={`${row.label} ${SME_GRADE_LABEL}`}
                      value={row.grade ?? ""}
                      onChange={(e) => update({ grade: (e.target.value || null) as SmeGrade | null })}
                      disabled={locked || row.held !== true}
                    >
                      <option value="">{READINESS_HELD_LABELS.unknown}</option>
                      {SME_GRADES.map((grade) => (
                        <option key={grade} value={grade}>
                          {grade}
                        </option>
                      ))}
                    </select>
                    <span className="min-w-0 basis-full leading-4 sm:basis-auto">
                      {row.held === true ? SME_GRADE_HELP : "「있음」을 고르면 구분을 적을 수 있습니다."}
                    </span>
                  </label>
                )}
              </li>
            );
          })}
        </ul>
      </fieldset>

      {hinted.length > 0 && (
        <p className="rounded-md border border-cosmos-cyan/35 bg-cosmos-cyan/10 px-2.5 py-2 text-[12px] leading-5 text-cosmos-cyan" role="note">
          등록 후보:{" "}
          {hinted.map((hint) => `${hint.name}(${hint.code})`).join(" · ")} — 사업자등록증에 이 종목이 있어
          나라장터 등록 신청이 가능해 보입니다. <strong>나라장터 등록증에서 확인하세요.</strong>
        </p>
      )}

      {message && <InlineAlert tone="pass">{message}</InlineAlert>}
      {error && (
        <InlineAlert tone="fail">
          {error}
          {staleNote && (
            <>
              {" "}
              <button
                type="button"
                className="mc-focus rounded font-medium underline"
                onClick={() => {
                  // 새 값을 불러온다 — 지금 고친 것은 버린다(남의 저장을 덮지 않게)
                  clearDraft(draftKey);
                  window.location.reload();
                }}
              >
                다시 불러오기
              </button>
              {" "}(지금 고친 것은 버려집니다 — 새 값에서 다시 고치세요)
            </>
          )}
        </InlineAlert>
      )}

      <div className="flex items-center gap-2">
        {viewer ? (
          <span className="text-[12px] text-cosmos-muted" title={VIEWER_LOCK_REASON} data-viewer-lock>{VIEWER_LOCK_LABEL} — {VIEWER_LOCK_REASON}</span>
        ) : (
          <>
            <Button size="sm" variant="primary" onClick={save} disabled={readOnly || busy} aria-busy={busy}>
              {busy ? "저장 중…" : "저장"}
            </Button>
            {/* 45차 M23 — 저장 안 한 값 버리기(되살린 임시 저장본 포함 · 회사 프로필 카드의 「취소」와 같은 일) */}
            {dirty && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={async () => {
                  if (!(await requestConsent({ title: "저장하지 않은 값을 버릴까요?", body: "입찰 자격 자료를 저장된 값으로 되돌립니다.", confirmLabel: "버리기", cancelLabel: "그만두기" }))) return;
                  applyForm(formOf(capacity));
                  setBaseAt(capacity.updated_at ?? null);
                  clearDraft(draftKey);
                  setRestoredNote(false);
                }}
              >
                취소(저장 안 한 값 버리기)
              </Button>
            )}
          </>
        )}
        {readOnly && <span className="text-[12px] text-cosmos-muted">공개 배포 모드에서는 저장할 수 없습니다.</span>}
        {capacity.updated_at && (
          <span className="ml-auto text-[12px] text-cosmos-muted">
            마지막 저장 {formatDateTime(capacity.updated_at)} · {capacity.updated_by ?? "저장한 사람 미상"}
          </span>
        )}
      </div>
    </section>
  );
}
