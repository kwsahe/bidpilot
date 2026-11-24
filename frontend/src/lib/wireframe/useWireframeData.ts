"use client";

/**
 * 와이어프레임 대시보드 데이터 훅.
 *
 * Evidence Cosmos(useCosmosDashboard)와 **같은 backend API**를 호출하되,
 * 순차 등장·카메라·발표 모드 같은 연출 상태는 갖지 않는다.
 * 이 화면의 목적은 "어느 패널이 어떤 API로 채워지고 어디가 아직 비어 있는지"를
 * 설계도처럼 보여주는 것이므로, 실패하거나 아직 없는 단계는 숨기지 않고 null로 남긴다
 * (가짜 수치를 만들지 않는다 — CLAUDE.md §11).
 *
 * 로드는 2단계다.
 *  1) health + 공고목록 + 선택 공고 + RFP 파싱결과 + (데모라면) 데모 시나리오 → 먼저 그린다
 *  2) 자격판정 → 제안서 → Auditor 를 뒤이어 채운다 (하나가 실패해도 나머지는 진행)
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  evaluateEligibility,
  getDemoCosmosScenario,
  getHealth,
  getProcurements,
  getProposal,
  getRfpRequirements,
  parseRfp,
  runAuditor,
} from "@/lib/api";
import { describeFailure, koreanDetail } from "@/lib/errors";
import {
  DEMO_NOTICE,
  DEMO_PROCUREMENT_ID,
  isDemoProcurementId,
} from "@/lib/cosmos/demoNotice";
import { proposalDraftText } from "@/lib/cosmos/graph";
import type {
  AuditRunResult,
  EligibilityReport,
  GeneratedProposalSection,
} from "@/types/analysis";
import type { DemoCosmosScenario } from "@/types/cosmos";
import type {
  CandidateTier,
  HealthResponse,
  ProcurementListResponse,
  ProcurementNotice,
  RecommendationGrade,
} from "@/types/procurement";
import type { RfpParseResult } from "@/types/rfp";

const NOTICE_QUERY_KEY = "notice";

export type WireframeStatus = "loading" | "error" | "ready";

/** 공고 선택기 항목. */
export interface WireframeNoticeOption {
  id: string;
  title: string;
  agency: string;
  tier: CandidateTier | null;
  /** 검토 우선순위 (1부터). 백엔드가 추천 점수 순으로 매겨 보낸다. */
  rank: number | null;
  /** 추천등급 A/B/C/D/NO_GO */
  grade: RecommendationGrade | null;
  demo: boolean;
}

/** 선택한 공고 하나에 대해 모은 결과. 없는 것은 null로 남긴다. */
interface WireframeSnapshot {
  notice: ProcurementNotice | null;
  parse: RfpParseResult | null;
  /** RFP 요구사항이 아직 없음(404) — 오류가 아니라 "미추출" */
  parseMissing: boolean;
  scenario: DemoCosmosScenario | null;
  eligibility: EligibilityReport | null;
  proposal: GeneratedProposalSection | null;
  audit: AuditRunResult | null;
}

const EMPTY_SNAPSHOT: WireframeSnapshot = {
  notice: null,
  parse: null,
  parseMissing: false,
  scenario: null,
  eligibility: null,
  proposal: null,
  audit: null,
};

export interface WireframeData extends WireframeSnapshot {
  status: WireframeStatus;
  /** status === "error" 일 때의 메시지 */
  error: string | null;
  /** 2단계(자격판정·제안서·Auditor) 로딩 중 */
  analysisLoading: boolean;
  health: HealthResponse | null;
  list: ProcurementListResponse | null;
  /** 공고 목록 조회 경고/실패 메시지 */
  listError: string | null;
  options: WireframeNoticeOption[];
  selectedId: string;
  selectNotice: (id: string) => void;
  reload: () => void;
  /** POST /api/rfp/parse — 이 공고의 제안요청서를 새로 파싱한다 */
  runParse: () => void;
  parsing: boolean;
  parseError: string | null;
}

// ---------------------------------------------------------------------------
// 오류 문구
// ---------------------------------------------------------------------------

/** 오류 문장 — HTTP 코드 · 서버 주소 · 프레임워크 이름을 쓰지 않는다(lib/errors 규칙 · CMN-24). */
function describeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return `나라장터 조회에 실패했고 캐시도 없습니다. ${koreanDetail(error.detail) ?? ""}`.trim();
  }
  return describeFailure(error, "데이터를 불러오지 못했습니다.");
}

// ---------------------------------------------------------------------------
// 로딩
// ---------------------------------------------------------------------------

/** 404는 "아직 파싱하지 않음"이라 오류로 올리지 않는다. */
function loadParse(
  procurementId: string,
): Promise<{ parse: RfpParseResult | null; missing: boolean }> {
  return getRfpRequirements(procurementId).then(
    (parse) => ({ parse, missing: false }),
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 404) {
        return { parse: null, missing: true };
      }
      throw error;
    },
  );
}

interface FirstPass {
  health: HealthResponse | null;
  list: ProcurementListResponse | null;
  listError: string | null;
  snapshot: WireframeSnapshot;
  /** 선택 공고를 아예 찾지 못했을 때의 사유 */
  fatal: string | null;
}

async function loadFirstPass(selectedId: string): Promise<FirstPass> {
  const [healthResult, listResult] = await Promise.allSettled([
    getHealth(),
    getProcurements(),
  ]);

  const health = healthResult.status === "fulfilled" ? healthResult.value : null;
  const list = listResult.status === "fulfilled" ? listResult.value : null;
  const listError =
    listResult.status === "rejected"
      ? describeError(listResult.reason)
      : (list?.error ?? null);

  if (isDemoProcurementId(selectedId)) {
    const [parseResult, scenarioResult] = await Promise.allSettled([
      loadParse(DEMO_PROCUREMENT_ID),
      getDemoCosmosScenario(DEMO_PROCUREMENT_ID),
    ]);
    if (parseResult.status === "rejected") {
      return {
        health,
        list,
        listError,
        snapshot: EMPTY_SNAPSHOT,
        fatal: describeError(parseResult.reason),
      };
    }
    return {
      health,
      list,
      listError,
      snapshot: {
        ...EMPTY_SNAPSHOT,
        notice: DEMO_NOTICE,
        parse: parseResult.value.parse,
        parseMissing: parseResult.value.missing,
        scenario:
          scenarioResult.status === "fulfilled" ? scenarioResult.value : null,
      },
      fatal: null,
    };
  }

  const notice = list?.notices.find((n) => n.id === selectedId) ?? null;
  if (!notice) {
    return {
      health,
      list,
      listError,
      snapshot: EMPTY_SNAPSHOT,
      fatal:
        listError ??
        "선택한 공고를 현재 후보 목록에서 찾지 못했습니다. 공고 조회 기간이 지났을 수 있습니다 — 다른 공고를 선택해 주세요.",
    };
  }

  const parseResult = await loadParse(selectedId).catch(() => ({
    parse: null,
    missing: true,
  }));

  return {
    health,
    list,
    listError,
    snapshot: {
      ...EMPTY_SNAPSHOT,
      notice,
      parse: parseResult.parse,
      parseMissing: parseResult.missing,
    },
    fatal: null,
  };
}

/**
 * 자격판정 → 제안서 → Auditor. 전부 best-effort다.
 * useCosmosDashboard.loadAnalysis 와 같은 순서·같은 기본값(use_llm=false)을 쓴다.
 */
async function loadAnalysis(
  procurementId: string,
  hasRequirements: boolean,
): Promise<Pick<WireframeSnapshot, "eligibility" | "proposal" | "audit">> {
  const eligibility = await evaluateEligibility(procurementId).catch(() => null);
  if (!hasRequirements) return { eligibility, proposal: null, audit: null };

  const proposal = await getProposal(procurementId).catch(() => null);
  const draft = proposalDraftText(proposal);
  const audit = draft
    ? await runAuditor(procurementId, draft).catch(() => null)
    : null;
  return { eligibility, proposal, audit };
}

// ---------------------------------------------------------------------------
// 선택 상태 (URL ?notice=)
// ---------------------------------------------------------------------------

function readInitialNoticeId(): string {
  if (typeof window === "undefined") return DEMO_PROCUREMENT_ID;
  try {
    const fromUrl = new URLSearchParams(window.location.search).get(
      NOTICE_QUERY_KEY,
    );
    if (fromUrl) return fromUrl;
  } catch {
    // URL 파싱 실패는 무시한다.
  }
  return DEMO_PROCUREMENT_ID;
}

function persistNoticeId(id: string): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set(NOTICE_QUERY_KEY, id);
    window.history.replaceState(window.history.state, "", url.toString());
  } catch {
    // history 접근 실패는 무시한다 — 선택 자체는 동작해야 한다.
  }
}

function buildOptions(
  list: ProcurementListResponse | null,
  selectedId: string,
): WireframeNoticeOption[] {
  const options: WireframeNoticeOption[] = [
    {
      id: DEMO_PROCUREMENT_ID,
      title: DEMO_NOTICE.title,
      agency: DEMO_NOTICE.agency,
      tier: null,
      rank: null,
      grade: null,
      demo: true,
    },
    ...(list?.notices ?? []).map((n) => ({
      id: n.id,
      title: n.title,
      agency: n.agency,
      tier: n.candidate?.tier ?? null,
      rank: n.rank ?? null,
      grade: n.recommendation?.grade ?? null,
      demo: false,
    })),
  ];
  if (!options.some((o) => o.id === selectedId)) {
    options.push({
      id: selectedId,
      title: selectedId,
      agency: "목록에서 확인되지 않음",
      tier: null,
      rank: null,
      grade: null,
      demo: false,
    });
  }
  return options;
}

// ---------------------------------------------------------------------------
// 훅
// ---------------------------------------------------------------------------

export function useWireframeData(): WireframeData {
  const [selectedId, setSelectedId] = useState<string>(readInitialNoticeId);
  const [status, setStatus] = useState<WireframeStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [list, setList] = useState<ProcurementListResponse | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<WireframeSnapshot>(EMPTY_SNAPSHOT);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  // 늦게 도착한 응답을 무시하기 위한 요청 토큰.
  const requestRef = useRef(0);

  // 로딩 상태는 요청을 유발한 쪽(선택·새로고침)에서 미리 세팅한다.
  // effect 본문에서 setState를 동기 호출하면 연쇄 렌더가 생긴다 (react-hooks/set-state-in-effect).
  useEffect(() => {
    const token = ++requestRef.current;

    loadFirstPass(selectedId).then(
      (first) => {
        if (token !== requestRef.current) return;
        setHealth(first.health);
        setList(first.list);
        setListError(first.listError);

        if (first.fatal) {
          setSnapshot(EMPTY_SNAPSHOT);
          setError(first.fatal);
          setStatus("error");
          return;
        }

        setSnapshot(first.snapshot);
        setStatus("ready");
        setAnalysisLoading(true);

        const hasRequirements =
          (first.snapshot.parse?.requirements.length ?? 0) > 0;
        void loadAnalysis(selectedId, hasRequirements).then(
          (analysis) => {
            if (token !== requestRef.current) return;
            setSnapshot((prev) => ({ ...prev, ...analysis }));
            setAnalysisLoading(false);
          },
          () => {
            if (token !== requestRef.current) return;
            setAnalysisLoading(false);
          },
        );
      },
      (loadError: unknown) => {
        if (token !== requestRef.current) return;
        setSnapshot(EMPTY_SNAPSHOT);
        setError(describeError(loadError));
        setStatus("error");
      },
    );

    return () => {
      requestRef.current += 1;
    };
  }, [selectedId, reloadToken]);

  const selectNotice = useCallback(
    (id: string) => {
      if (id === selectedId) return;
      persistNoticeId(id);
      setStatus("loading");
      setError(null);
      setSnapshot(EMPTY_SNAPSHOT);
      setParseError(null);
      setSelectedId(id);
    },
    [selectedId],
  );

  const reload = useCallback(() => {
    setStatus("loading");
    setError(null);
    setParseError(null);
    setReloadToken((n) => n + 1);
  }, []);

  const runParse = useCallback(() => {
    setParsing(true);
    setParseError(null);
    parseRfp(selectedId)
      .then(
        () => {
          setStatus("loading");
          setError(null);
          setReloadToken((n) => n + 1);
        },
        (rfpError: unknown) => {
          if (rfpError instanceof ApiError && rfpError.status === 404) {
            setParseError(
              "이 공고의 제안요청서는 아직 파싱할 수 없습니다 (첨부 문서 미지원 또는 추출 실패).",
            );
            return;
          }
          setParseError(describeError(rfpError));
        },
      )
      .finally(() => setParsing(false));
  }, [selectedId]);

  return {
    ...snapshot,
    status,
    error,
    analysisLoading,
    health,
    list,
    listError,
    options: buildOptions(list, selectedId),
    selectedId,
    selectNotice,
    reload,
    runParse,
    parsing,
    parseError,
  };
}
