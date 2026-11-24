/**
 * 기업마당 지원사업 «신청 분석» 결과를 3D 우주가 읽는 그래프로 옮긴다.
 *
 * `buildCosmosGraph`(입찰 빌더)를 **부르지 않는다.** 부르면 그 안에 박힌 문자열
 * (「입찰공고」·「RFP 요구사항」·「AI Auditor」)이 그대로 따라붙어, 기업마당 사업 화면에
 * 나라장터 어휘가 뜬다 — 어색한 정도가 아니라 거짓 정보다.
 *
 * ## 지어내지 않기 위해 «비워 두는» 것
 *
 * `requirements`·`evidence`·`findings`·`eligibility`·`resolutions` 는 **언제나 빈 배열**,
 * `requirementByNodeId`·`evidenceByNodeId`·`findingByNodeId` 는 **언제나 빈 Map** 이다.
 * 이 파생 뷰들은 `page`·`source_text`·`displayStatus`·`sentences`·`findings`·`severity` 를
 * 요구하는데 지원사업 응답에는 그런 값이 없다. 채우려면 전부 지어내야 한다.
 *
 * 비워 두면 연쇄로 안전해진다:
 *  - `three/nodes.tsx:641-647 riskFindingOf` 가 null 을 돌려 `renderRiskTooltip` 이 null →
 *    `three/tooltip.tsx:33` 의 「Auditor · 심각도」 줄이 **아예 렌더되지 않는다**.
 *  - finding 노드에 `severity` 를 붙이지 않으므로 `three/nodes.tsx:806-811` 의 심각도 배지
 *    (「참가 차단」 포함)도 뜨지 않는다.
 *
 * ## 반드시 «채우는» 것
 *
 * `nodeById`·`linksByNode`·`neighbors` 는 3D 기하(Cosmos3D:99-100, CameraRig)가 의존한다.
 * 비우면 카메라가 노드를 못 찾고 연결선이 조용히 사라진다.
 *
 * ## 숫자에 대한 규칙
 *
 *  - `company_priority_score` 는 노드 크기·거리에 **절대** 넣지 않는다. 점수는 검토
 *    우선순위지 선정확률이 아니다.
 *  - `budget`·`region` 은 목록에 없다 → `null`. 0 이나 「미정」으로 적지 않는다.
 *  - `coverage`·`counts` 는 구조상 0 이지만 지원사업 어휘가 그 수를 읽지 않는다
 *    (`SUPPORT_VOCABULARY` 의 `proposalBadge`/`auditBadge` 가 응답에서 직접 센다).
 */

import {
  AUDIT_NODE_ID,
  EMPTY_ANALYSIS,
  LAYOUT,
  MAX_EXPANDED_CHILDREN,
  MAX_PRIMARY_NODES,
  NOTICE_NODE_ID,
  PROPOSAL_NODE_ID,
  evidenceNodeId,
  ringPosition,
  ringPosition2d,
} from "@/lib/cosmos/graph";
import type {
  CosmosGraph,
  CosmosLink,
  CosmosNode,
  CosmosSource,
  NoticeOrigin,
} from "@/lib/cosmos/graph";
import type { CosmosNodeState } from "@/lib/cosmos/theme";
import { truncate } from "@/lib/cosmos/format";
import { normalizeApplyEnd } from "@/lib/deadline";
import type { ProcurementNotice } from "@/types/procurement";
import {
  SUPPORT_STEPS,
  type SupportApplicationResult,
  type SupportRequirementItem,
  type SupportStepKey,
} from "@/types/opportunity";

import { SUPPORT_STAGE, buildSupportSteps, supportProgress } from "./supportSteps";

// ---------------------------------------------------------------------------
// 노드 id — 입찰 id 와 절대 겹치지 않게 "sup-" 접두를 붙인다
// ---------------------------------------------------------------------------

/** 단계 묶음 노드 (신청자격·필수우대조건·신청기간·제출서류). */
export const supportGroupNodeId = (key: SupportStepKey) => `reqgroup:sup-${key}`;
/** 묶음을 펼쳤을 때 나오는 개별 항목 노드. */
export const supportItemNodeId = (step: SupportStepKey, key: string) => `req:sup-${step}-${key}`;
/** 「회사자료 검색 기준」 묶음 — 회사 적합 근거가 매달리는 단 하나의 자리. */
export const SUPPORT_EVIDENCE_BASIS_NODE_ID = "reqgroup:sup-basis";
/** 신청 전 확인 사항 노드. `pre_submit_checks` 는 string[] 이라 색인이 유일한 키다. */
export const supportCheckNodeId = (index: number) => `finding:sup-${index}`;

// ---------------------------------------------------------------------------
// 노드 예산
// ---------------------------------------------------------------------------

/**
 * 접었을 때 언제나 서 있는 뼈대 = 코어 1 + 단계 묶음 4 + 검색 기준 1 + 사업계획서 1 + 점검 1.
 * 나머지 자리를 회사 적합 근거와 확인 사항이 나눠 쓴다.
 */
const SKELETON_NODE_COUNT = 8;

/**
 * 회사 적합 근거 / 확인 사항 노드를 몇 개씩 그릴지.
 *
 * 실측(2026-09-14, org-sample · 11개 사업): 근거 0~9건, 확인 사항 10~13건.
 * 전부 그리면 주요 노드가 30개가 되어 `MAX_PRIMARY_NODES`(18)를 크게 넘고, 3D 라벨이
 * 서로 겹쳐 아무것도 읽히지 않는다(입찰에서 이미 겪은 일 — graph.ts 「집계 모드」 주석).
 *
 * 고정 분배는 쓰지 않는다. 실측 11건 중 7건이 **근거 0건**이라, 반씩 나누면 근거 쪽 자리
 * 5칸이 늘 비어 있고 확인 사항만 잘려 나갔다. 한쪽이 적으면 남는 자리를 다른 쪽에 준다.
 *
 * **자른 건수는 버리지 않는다** — 묶음 노드의 `groupCount` 에 언제나 «원문 전체 건수» 를
 * 넣으므로 `groupCount - 실제로 그린 자식 수` 로 몇 건이 접혔는지 알 수 있다.
 * 전체 목록은 3D 가 아니라 단계별 패널(SupportPlanPanel/SupportEvidencePanel)이 보여준다.
 */
function splitNodeBudget(evidenceTotal: number, checkTotal: number): { evidence: number; check: number } {
  const budget = Math.max(MAX_PRIMARY_NODES - SKELETON_NODE_COUNT, 0);
  const half = Math.floor(budget / 2);
  const evidence = Math.min(evidenceTotal, Math.max(half, budget - checkTotal));
  const check = Math.min(checkTotal, budget - evidence);
  return { evidence, check };
}

// ---------------------------------------------------------------------------
// 옵션
// ---------------------------------------------------------------------------

/**
 * 회사 적합 근거 집계.
 *
 * `matches` = 백엔드가 돌려준 검색 결과 건수(진행 바가 쓰는 수), `unique` = 실제 근거 건수.
 * **같은 근거가 앵커(검색 기준)마다 반복돼 온다.** 백엔드가 「사업 개요」·「지원 분야」·
 * 「지원 대상」 세 앵커로 따로 검색해 결과를 이어 붙이기 때문이다
 * (support_application_service.py:138-163·174-177).
 * 실측 2026-09-14 · org-sample: 126458 은 6건 중 3건, 126450 은 9건 중 5건이 실제 근거였다.
 *
 * 두 수를 구분해 두지 않으면 3D 에 구체 3개를 그려 놓고 「6건」이라 적게 된다.
 */
export function supportEvidenceTally(result: SupportApplicationResult): {
  matches: number;
  unique: number;
} {
  const unique = new Set(result.evidence_matches.map((match) => match.evidence_id)).size;
  return { matches: result.evidence_matches.length, unique };
}

export interface SupportGraphOptions {
  /** 펼쳐 놓은 묶음. null 이면 전부 접힌 Overview */
  expandedGroup?: SupportStepKey | null;
}

/** 단계 묶음으로 그릴 네 단계. 나머지 셋(evidence·draft·check)은 모양이 다르다. */
const PLAN_STEPS = ["eligibility", "conditions", "schedule", "documents"] as const;

function planStepLabel(key: SupportStepKey): string {
  return SUPPORT_STEPS.find((step) => step.key === key)?.label ?? key;
}

/** 원문에 값이 있으면 「확인됨」, 없으면 「확인 필요」. 두 상태뿐이고 지어낸 등급은 없다. */
function itemState(item: SupportRequirementItem): CosmosNodeState {
  return item.status === "unknown" ? "check" : "ok";
}

function groupState(items: SupportRequirementItem[]): CosmosNodeState {
  if (items.length === 0) return "neutral";
  return items.some((item) => item.status === "unknown") ? "check" : "ok";
}

/**
 * 기업마당 출처를 `NoticeOrigin` 에 억지로 끼우지 않는다.
 *
 * `NoticeOrigin` 에는 기업마당을 적을 칸이 없어 실시간/캐시 구분만 보존한다.
 * **화면 문구는 이 값을 읽지 않는다** — `SUPPORT_VOCABULARY.originLabel` 이
 * `source.support.source` 를 직접 읽어 「기업마당 실시간 / 기업마당 캐시 / 합성 샘플」로 적는다
 * (`labels.tsx:885` 이 어휘를 통해서만 출처를 그린다).
 */
function supportOrigin(result: SupportApplicationResult): NoticeOrigin {
  if (result.source === "sample") return { kind: "demo" };
  return {
    kind: "real",
    source: result.source === "bizinfo" ? "g2b" : "cached",
    fetchedAt: result.generated_at,
  };
}

/**
 * 지원사업을 `ProcurementNotice` 모양에 담는다 (3D 중앙 카드가 이 타입을 받는다).
 *
 * 없는 값을 만들지 않는다: 지원 규모·지역·공고번호는 기업마당 목록에 없으므로
 * `budget=null`·`region=null`·`notice_no=""` 로 둔다. 0 으로 적으면 「0원 사업」으로 읽힌다.
 */
function supportNotice(result: SupportApplicationResult): ProcurementNotice {
  const program = result.program;
  return {
    id: result.program_id,
    notice_no: "",
    title: program.title,
    agency: program.agency,
    // 기업마당 등록일이 없으면 빈 문자열 — 분석 생성 시각을 등록일인 척 적지 않는다.
    published_at: program.created_at ?? "",
    // 날짜만(YYYY-MM-DD) 오므로 백엔드와 같은 순간(그날 23:59 KST)으로 맞춘다.
    deadline_at: normalizeApplyEnd(program.apply_end),
    budget: null,
    region: null,
    description: program.summary,
    source_url: program.url,
    raw_data: {},
  };
}

/**
 * 지원사업 신청 분석 결과 → 3D 그래프.
 *
 * 순수 함수다. 같은 입력이면 같은 그래프라서, 늦게 도착한 응답이 화면에 섞이는
 * 문제가 구조적으로 생기지 않는다(`useMemo(() => buildSupportCosmosGraph(result, …))`).
 */
export function buildSupportCosmosGraph(
  result: SupportApplicationResult,
  options: SupportGraphOptions = {},
): CosmosGraph {
  const expandedGroup = options.expandedGroup ?? null;
  const nodes: CosmosNode[] = [];
  const links: CosmosLink[] = [];

  // --- 1. 중앙 코어: 지원사업 ---------------------------------------------
  nodes.push({
    id: NOTICE_NODE_ID,
    kind: "notice",
    label: result.program.title,
    short: "지원사업",
    state: "neutral",
    stage: 1,
    position: [0, 0, 0],
    position2d: [0, 0],
  });

  // --- 2. 단계 묶음 4개 + 펼친 항목 ---------------------------------------
  //
  // 묶음은 `requirement-group` 이라 3D 에서 **이름이 언제나 보인다**
  // (`nodes.tsx:673-679` 의 라벨 억제 규칙). 개별 항목은 입찰과 똑같이 hover 로 읽는다.
  // 궤도 자리는 5칸: 네 묶음 + 「회사자료 검색 기준」. 같은 링을 쓰면 겹치지 않는다.
  const RING_SLOTS = PLAN_STEPS.length + 1;
  let hiddenInExpanded = 0;

  PLAN_STEPS.forEach((key, slot) => {
    const items = result.plan[key];
    const groupId = supportGroupNodeId(key);
    const stage = SUPPORT_STAGE[key];
    const pending = items.filter((item) => item.status === "unknown").length;

    nodes.push({
      id: groupId,
      kind: "requirement-group",
      label: `${planStepLabel(key)} ${items.length}건`,
      // 이름만 (§3-A-5). 건수는 상태 조각이 맡는다 — 붙이면 「신청자격 5 5건」이 된다.
      short: planStepLabel(key),
      state: groupState(items),
      stage,
      position: ringPosition(slot, RING_SLOTS, LAYOUT.requirementRadius, LAYOUT.requirementY),
      position2d: ringPosition2d(slot, RING_SLOTS, LAYOUT.requirementRadius2d),
      // 원문 전체 건수다. 펼친 자식 수와 다르면 그만큼 접힌 것이다.
      groupCount: items.length,
      groupKey: key,
      expanded: expandedGroup === key,
    });
    links.push({
      id: `link:notice:group:sup-${key}`,
      source: NOTICE_NODE_ID,
      target: groupId,
      kind: "notice-group",
      state: pending > 0 ? "warning" : "neutral",
      stage,
    });

    if (expandedGroup !== key) return;

    // 펼쳤을 때 그리는 자식 수는 입찰과 같은 상한을 쓴다. 나머지는 단계별 패널에 있다.
    const shown = items.slice(0, MAX_EXPANDED_CHILDREN);
    hiddenInExpanded = items.length - shown.length;
    shown.forEach((item, i) => {
      const itemId = supportItemNodeId(key, item.key);
      nodes.push({
        id: itemId,
        kind: "requirement",
        // 원문에 값이 없으면 「원문 확인 필요」 — 빈칸이나 「-」로 두면 확인한 것처럼 보인다.
        label: `${item.label} — ${item.value ?? "원문 확인 필요"}`,
        short: item.label,
        state: itemState(item),
        stage,
        position: ringPosition(i, shown.length, LAYOUT.requirementRadius * 1.55, LAYOUT.requirementY),
        position2d: ringPosition2d(i, shown.length, LAYOUT.requirementRadius2d * 1.5),
      });
      links.push({
        id: `link:group:sup-${key}:${item.key}`,
        source: groupId,
        target: itemId,
        kind: "group-requirement",
        state: item.status === "unknown" ? "warning" : "neutral",
        stage,
      });
    });
  });

  // --- 3. 회사자료 검색 기준 + 회사 적합 근거 -----------------------------
  //
  // `evidence_matches[].condition` 은 「사업 개요」·「지원 분야」·「지원 대상」 셋뿐이고
  // (backend support_application_service.py:138-163·174-177), 그 셋은 어느 단계 묶음과도
  // 이어진 적이 없다. 그래서 근거를 단계 묶음에 매달지 않고 **검색 기준 묶음 하나**에만 잇는다.
  // 이어 붙이면 백엔드가 계산한 적 없는 매핑을 화면이 지어내는 것이 된다.
  //
  // 같은 근거가 앵커마다 반복돼 오므로(supportEvidenceTally 주석) 처음 나온 것만 남긴다.
  // 그대로 노드를 만들면 **id 가 겹쳐 `nodeById` 가 노드 배열보다 작아지고**
  // (실측: 18개를 그렸는데 nodeById 16개), 연결선 id 도 중복돼 3D 가 선을 조용히 덜 그린다.
  const uniqueMatches = [
    ...new Map(result.evidence_matches.map((match) => [match.evidence_id, match])).values(),
  ];
  const evidenceTotal = uniqueMatches.length;
  const checkTotal = result.pre_submit_checks.length;
  const budget = splitNodeBudget(evidenceTotal, checkTotal);

  const evidenceStage = SUPPORT_STAGE.evidence;
  nodes.push({
    id: SUPPORT_EVIDENCE_BASIS_NODE_ID,
    kind: "requirement-group",
    label: `회사자료 검색 기준 · 연결된 근거 ${evidenceTotal}건`,
    // 이름만 (§3-A-5). 건수는 상태 조각이 맡는다.
    short: "검색 기준",
    // 근거 0건은 «틀렸다»가 아니라 «아직 없다»다 — 회사자료를 등록·승인하면 채워진다.
    state: evidenceTotal > 0 ? "ok" : "check",
    stage: evidenceStage,
    position: ringPosition(
      PLAN_STEPS.length,
      RING_SLOTS,
      LAYOUT.requirementRadius * 1.25,
      LAYOUT.evidenceY,
    ),
    position2d: ringPosition2d(PLAN_STEPS.length, RING_SLOTS, LAYOUT.requirementRadius2d * 1.25),
    groupCount: evidenceTotal,
    groupKey: "basis",
  });
  links.push({
    id: "link:notice:group:sup-basis",
    source: NOTICE_NODE_ID,
    target: SUPPORT_EVIDENCE_BASIS_NODE_ID,
    kind: "notice-group",
    state: evidenceTotal > 0 ? "neutral" : "warning",
    stage: evidenceStage,
  });

  const shownEvidence = uniqueMatches.slice(0, budget.evidence);
  shownEvidence.forEach((match, i, all) => {
    const nodeId = evidenceNodeId(match.evidence_id);
    nodes.push({
      id: nodeId,
      kind: "evidence",
      label: match.document_name,
      short: truncate(match.document_name, 10),
      // 담당자가 아직 고르지 않은 «후보» 다. selected=true 여야 채택된 근거다.
      state: match.selected ? "ok" : "partial",
      stage: evidenceStage,
      position: ringPosition(
        i,
        all.length,
        LAYOUT.evidenceRadius,
        LAYOUT.evidenceY,
        -Math.PI / 2 + Math.PI / all.length,
      ),
      position2d: ringPosition2d(
        i,
        all.length,
        LAYOUT.evidenceRadius2d,
        -Math.PI / 2 + Math.PI / all.length,
      ),
      evidenceId: match.evidence_id,
    });
    links.push({
      id: `link:sup-basis:${match.evidence_id}`,
      source: SUPPORT_EVIDENCE_BASIS_NODE_ID,
      target: nodeId,
      kind: "requirement-evidence",
      state: match.selected ? "active" : "candidate",
      stage: evidenceStage,
    });
  });

  // --- 4. 사업계획서 초안 --------------------------------------------------
  const draftStage = SUPPORT_STAGE.draft;
  const grounded = result.draft_outline.filter((section) => section.grounded).length;
  nodes.push({
    id: PROPOSAL_NODE_ID,
    kind: "proposal",
    label: "사업계획서 초안",
    short: "사업계획서",
    state: grounded < result.draft_outline.length ? "check" : "ok",
    stage: draftStage,
    position: [0, LAYOUT.proposalY, 0],
    position2d: [0, LAYOUT.proposalY2d],
    groupCount: result.draft_outline.length,
  });
  if (shownEvidence.length > 0) {
    for (const match of shownEvidence) {
      links.push({
        id: `link:${match.evidence_id}:proposal`,
        source: evidenceNodeId(match.evidence_id),
        target: PROPOSAL_NODE_ID,
        kind: "evidence-proposal",
        state: "neutral",
        stage: draftStage,
      });
    }
  } else {
    // 근거가 하나도 없으면 초안 노드가 그래프에서 떨어져 나간다(카메라가 길을 잃는다).
    // 검색 기준 묶음에 이어 둔다 — 「근거를 찾아본 결과가 초안으로 간다」는 구조는 참이다.
    links.push({
      id: "link:sup-basis:proposal",
      source: SUPPORT_EVIDENCE_BASIS_NODE_ID,
      target: PROPOSAL_NODE_ID,
      kind: "requirement-proposal",
      state: "neutral",
      stage: draftStage,
    });
  }

  // --- 5. 신청 전 점검 ----------------------------------------------------
  //
  // `pre_submit_checks` 는 string[] 이라 **우선순위 근거가 데이터에 없다.**
  // 정렬하지 않고 백엔드가 준 원문 순서를 그대로 지킨다 (순서를 바꾸면 없는 중요도를 지어내는 것이다).
  const checkStage = SUPPORT_STAGE.check;
  const shownChecks = result.pre_submit_checks.slice(0, budget.check);
  nodes.push({
    id: AUDIT_NODE_ID,
    kind: "audit",
    label: "신청 전 점검",
    short: "신청 전 점검",
    state: checkTotal > 0 ? "check" : "ok",
    stage: checkStage,
    position: [0, LAYOUT.auditY, 0],
    position2d: [0, LAYOUT.auditY2d],
    // 원문 전체 건수. 그린 노드 수와의 차이가 «접힌 건수» 다.
    groupCount: checkTotal,
    groupKey: "check",
  });
  links.push({
    id: "link:proposal:audit",
    source: PROPOSAL_NODE_ID,
    target: AUDIT_NODE_ID,
    kind: "audit-finding",
    state: "neutral",
    stage: checkStage,
  });

  const checkRadius = Math.max(LAYOUT.findingRadius, shownChecks.length * 0.34);
  const checkRadius2d = Math.max(LAYOUT.findingRadius2d, shownChecks.length * 16);
  shownChecks.forEach((text, i, all) => {
    const nodeId = supportCheckNodeId(i);
    nodes.push({
      id: nodeId,
      kind: "finding",
      label: text,
      short: truncate(text, 12),
      // 전부 「확인 필요」다. severity 는 **붙이지 않는다** — 백엔드가 심각도를 매긴 적이 없고,
      // 붙이면 `nodes.tsx:806-811` 이 「참가 차단」 같은 입찰 배지를 그린다.
      state: "check",
      stage: checkStage,
      position: ringPosition(i, all.length, checkRadius, LAYOUT.auditY, Math.PI / 2),
      position2d: (() => {
        const [x, y] = ringPosition2d(i, all.length, checkRadius2d, Math.PI / 2);
        return [x, y + LAYOUT.auditY2d] as [number, number];
      })(),
    });
    links.push({
      id: `link:audit:sup-${i}`,
      source: AUDIT_NODE_ID,
      target: nodeId,
      kind: "audit-finding",
      state: "warning",
      stage: checkStage,
    });
  });

  // --- 6. 색인 ------------------------------------------------------------
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const linksByNode = new Map<string, CosmosLink[]>();
  const neighbors = new Map<string, Set<string>>();
  for (const link of links) {
    for (const [a, b] of [
      [link.source, link.target],
      [link.target, link.source],
    ]) {
      linksByNode.set(a, [...(linksByNode.get(a) ?? []), link]);
      if (!neighbors.has(a)) neighbors.set(a, new Set());
      neighbors.get(a)!.add(b);
    }
  }

  const steps = buildSupportSteps(result);

  // `support` 에 응답을 그대로 싣는다 — 어휘(SUPPORT_VOCABULARY)와 상세가 여기서 읽는다.
  const source: CosmosSource = {
    notice: supportNotice(result),
    origin: supportOrigin(result),
    parse: null,
    scenario: null,
    analysis: EMPTY_ANALYSIS,
    support: result,
  };

  return {
    source,
    // 입찰 단계를 하나도 실행한 적이 없다. true 로 두면 3D 가 없는 결과를 있다고 읽는다.
    hasScenario: false,
    hasRequirements: false,
    hasEligibility: false,
    hasProposal: false,
    hasAudit: false,
    eligibility: [],
    proposal: null,
    nodes,
    links,
    nodeById,
    linksByNode,
    neighbors,
    // 지어낸 파생 뷰를 만들지 않는다 (파일 맨 위 주석 참고).
    requirements: [],
    requirementByNodeId: new Map(),
    evidence: [],
    evidenceByNodeId: new Map(),
    findings: [],
    findingByNodeId: new Map(),
    resolutions: [],
    cluster: {
      // 항목은 언제나 묶음으로 그리고 펼쳤을 때만 개별 노드가 나온다.
      requirementsClustered: true,
      findingsClustered: false,
      // `expandedCategory` 는 입찰의 ItemType 이다. 지원사업 단계 키를 넣을 칸이 아니다
      // (펼친 묶음은 노드의 `expanded` 플래그가 갖고 있다).
      expandedCategory: null,
      hiddenInExpanded,
      categories: [],
      findingGroups: [],
      primaryNodeCount: nodes.filter((node) => node.kind !== "requirement").length,
    },
    // 「반영 n/m」은 입찰 요구사항 커버리지 개념이고 지원사업에는 그런 개념이 **없다**.
    // 0 이지만 어떤 라벨도 이 값을 읽지 않는다 (SUPPORT_VOCABULARY 가 응답에서 직접 센다).
    coverage: { total: 0, covered: 0, missingRequirementIds: [] },
    counts: {
      requirements: 0,
      evidenceDocuments: 0,
      selectedLinks: 0,
      requirementsWithoutEvidence: 0,
      sentences: 0,
      sentencesNeedingReview: 0,
      findings: 0,
      findingsHigh: 0,
      findingsOpen: 0,
      findingsResolved: 0,
      findingsHighOpen: 0,
      findingsBlocking: 0,
      findingsBlockingOpen: 0,
    },
    steps,
    progress: supportProgress(steps),
    reviewDecision: null,
  };
}
