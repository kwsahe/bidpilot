/**
 * 지원사업 3D 가 화면에 적는 «말».
 *
 * 3D 안에는 입찰 어휘가 JSX 에 그대로 박혀 있었다. 기업마당 사업을 그 화면에 태우면
 * 출처가 기업마당인데도 「나라장터 캐시」라고 적히고(`labels.tsx:880-885`), 허브 칩에는
 * 「발견 0건」·「반영 0/0」이 뜬다 — 어색한 정도가 아니라 **거짓 정보**다.
 * 이 객체가 그 자리를 전부 갈아끼운다.
 *
 * 쓰면 안 되는 말(기업마당 화면 기준):
 *   입찰 · 낙찰 · 투찰 · RFP · 제안서 · 수주 · 평가항목 ·
 *   발주기관 · 나라장터 · Auditor · 참가자격 · 참가 차단 · 요구사항 · 증빙
 * (`scripts/check_support_vocabulary.mjs` 가 기계로 검사한다. 내부 필드명은 화면 용어가
 *  아니므로 검사 대상이 아니다 — 구분할 것.)
 *
 * 숫자는 전부 `graph.source.support`(응답 원본)에서 직접 센다.
 * `graph.coverage`·`graph.counts` 는 지원사업에서 구조상 0 이라 읽으면 안 된다
 * (읽으면 「근거 있는 목차 0/0」처럼 실행한 적 없는 결과를 0 으로 확정해 버린다).
 */

import { supportSourceBadge } from "@/lib/supportSource";
import type { KeyLabel } from "@/lib/cosmos/guidedFlow";
import type { CenterRow, CosmosVocabulary } from "@/lib/cosmos/vocabulary";
import type { CosmosGraph } from "@/lib/cosmos/graph";
import { AUDIT_NODE_ID, NOTICE_NODE_ID, PROPOSAL_NODE_ID } from "@/lib/cosmos/graph";
import { deadlineTerm, formatDeadlineDate, supportDeadlineIso } from "@/lib/deadline";
import type { SupportApplicationResult } from "@/types/opportunity";

import {
  SUPPORT_EVIDENCE_BASIS_NODE_ID,
  supportEvidenceTally,
  supportGroupNodeId,
} from "./supportGraph";

/** 지원사업 그래프가 아니면 undefined. 그때는 어떤 문구도 지어내지 않는다. */
function supportOf(graph: CosmosGraph): SupportApplicationResult | undefined {
  return graph.source.support;
}

function shorten(text: string, max: number): string {
  const t = text.trim();
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
}

/** 사업계획서 목차 중 근거가 붙은 것 / 전체. `draft_outline[].grounded` 를 그대로 센다. */
function draftTally(result: SupportApplicationResult): { grounded: number; total: number } {
  return {
    grounded: result.draft_outline.filter((section) => section.grounded).length,
    total: result.draft_outline.length,
  };
}

/**
 * 접수 기간 표기.
 *
 * `SupportShell.tsx:309-311` 과 **같은 규칙**이다 — 마감일이 있으면 날짜, 없으면 원문
 * 기간 문구, 그것도 없으면 「원문 확인 필요」. 상시·예산 소진 접수를 날짜로 꾸미지 않는다.
 */
function applyEndRow(result: SupportApplicationResult): CenterRow {
  const program = result.program;
  // 라벨도 `lib/deadline` 이 고른다 (0920 §4-B-5 · ISSUE-078). 예전에는 「신청 마감」이
  // 고정이라 이미 지난 건에도 「신청 마감」이 붙었고, 상시 접수도 날짜로 꾸며졌다.
  // `source` 는 반드시 "bizinfo" 다 — 「입찰」 계열 낱말은 이 화면에서 금지다
  // (`scripts/check_support_vocabulary.mjs`).
  const deadline = supportDeadlineIso(program);
  const label = deadlineTerm({
    source: "bizinfo",
    // 마감 여부는 **백엔드 판정**을 쓴다 — 프론트에서 다시 계산하지 않는다
    // (`lib/deadline` 머리말). 마감된 건은 서버가 우선순위 라벨을 「마감」으로 준다.
    closed: result.priority_label === "마감",
    periodKind: program.apply_period_kind,
    deadline,
  });
  if (deadline) {
    return { label, value: formatDeadlineDate(deadline), mono: true };
  }
  return {
    label,
    value: program.apply_period_text?.trim() || "원문 확인 필요",
  };
}

export const SUPPORT_VOCABULARY: CosmosVocabulary = {
  ariaLabel:
    "지원사업 신청 분석 3D 뷰 — 가운데 분석 대상 지원사업, 첫 궤도 신청자격·필수우대조건·신청기간·제출서류 묶음과 회사자료 검색 기준, 바깥 궤도 회사 적합 근거, 위쪽 사업계획서 초안과 신청 전 점검 항목. 항목 전체 목록은 아래 단계별 패널에서 키보드로 볼 수 있다",

  // 지원사업 지도는 번호 칩 규칙 그대로 — 핵심 라벨 ①~⑤ 가 이어진다(27차 검수 R27D-03 · 입찰 지도만 원문자를 뺐다).
  centerEyebrow: "① 분석 대상 지원사업",

  // 출처 배지와 같은 함수 하나(34차 R33-A2 — `lib/supportSource.ts`). 나라장터 라벨을 재사용하지 않는다.
  originLabel: (graph) => {
    const result = supportOf(graph);
    return result ? supportSourceBadge(result.source, result.archived_closed).label : "출처 확인 필요";
  },

  // 「예산」 행을 **내보내지 않는다** — 지원 규모는 기업마당 목록에 없다(budget=null).
  // 행을 두면 「확인 필요」가 뜨는데, 그건 우리가 확인하지 않은 것이 아니라 애초에 없는 칸이다.
  centerRows: (graph) => {
    const result = supportOf(graph);
    if (!result) return [];
    const program = result.program;
    return [
      { label: "주관기관", value: program.agency },
      applyEndRow(result),
      { label: "신청 방법", value: program.apply_method?.trim() || "원문 확인 필요" },
    ];
  },

  // 적합도/후보 행은 키워드 등급·의미매칭 같은 입찰 판정을 읽는다. 지원사업에는 그 판정이 없다.
  showFitRow: false,

  centerStepLabel: "현재 보는 단계",

  // 진행바를 **그리지 않는다**. 어느 단계도 「실행」한 적이 없어서 0% 든 43% 든
  // 「돌려 봤더니 이만큼」으로 읽힌다. null 이면 진행바 DOM 자체가 렌더되지 않는다.
  centerProgress: () => null,

  proposalBadge: (graph) => {
    const result = supportOf(graph);
    if (!result) return null;
    const { grounded, total } = draftTally(result);
    return total === 0 ? null : `근거 있는 목차 ${grounded}/${total}`;
  },

  auditBadge: (graph) => {
    const result = supportOf(graph);
    if (!result) return null;
    return `확인할 항목 ${result.pre_submit_checks.length}건`;
  },

  // 지원사업 분석은 합성 시나리오를 쓰지 않는다 — 언제나 기업마당 응답이다.
  showDemoTag: () => false,

  // 근거 문서의 종류를 백엔드가 내려준 적이 없다. 지어내는 대신 기본 모양을 쓴다.

  /**
   * 3D 위에 떠 있는 핵심 라벨 5개.
   *
   * 이것이 없으면 지원사업 화면에서 라벨이 통째로 사라진다 —
   * `requirement`·`evidence`·`finding` 은 hover/선택/keyLabel 없이는 이름이 안 보인다
   * (`nodes.tsx:673-679`). 앵커는 «언제나 만들어지는 노드»만 고른다.
   *
   * `KeyLabel.step` 은 1..5 이고, 여기 다섯 앵커의 순서와 그대로 맞춘다.
   */
  keyLabels: (graph) => {
    const result = supportOf(graph);
    if (!result) return new Map();

    const labels: KeyLabel[] = [];

    labels.push({
      nodeId: NOTICE_NODE_ID,
      title: "지원사업",
      subtitle: shorten(result.program.title, 22),
      step: 1,
    });

    const eligibilityId = supportGroupNodeId("eligibility");
    if (graph.nodeById.has(eligibilityId)) {
      const items = result.plan.eligibility;
      const pending = items.filter((item) => item.status === "unknown").length;
      labels.push({
        nodeId: eligibilityId,
        title: "신청자격",
        subtitle: `확인 ${items.length - pending}건 · 확인 필요 ${pending}건`,
        step: 2,
      });
    }

    // 대표 근거 1개. 근거가 하나도 없으면 「검색 기준」 묶음이 그 자리를 대신한다 —
    // 라벨을 통째로 빼면 「회사자료를 아직 연결하지 않았다」는 사실이 화면에서 사라진다.
    //
    // 수는 «실제 근거 수»를 적는다. 검색 결과 건수(진행 바가 쓰는 수)와 다르면 괄호로
    // 함께 보인다 — 구체 3개를 그려 놓고 「6건」이라 적으면 담당자가 2개를 못 찾은 줄 안다.
    const tally = supportEvidenceTally(result);
    const representative = graph.nodes.find((node) => node.kind === "evidence");
    const evidenceAnchor = representative?.id ?? SUPPORT_EVIDENCE_BASIS_NODE_ID;
    if (graph.nodeById.has(evidenceAnchor)) {
      labels.push({
        nodeId: evidenceAnchor,
        title: "회사 적합 근거",
        subtitle:
          tally.unique === 0
            ? "검색으로 연결한 근거 없음"
            : tally.matches > tally.unique
              ? `연결된 근거 ${tally.unique}건 · 검색 결과 ${tally.matches}건`
              : `연결된 근거 ${tally.unique}건`,
        step: 3,
      });
    }

    if (graph.nodeById.has(PROPOSAL_NODE_ID)) {
      const { grounded, total: sections } = draftTally(result);
      labels.push({
        nodeId: PROPOSAL_NODE_ID,
        title: "사업계획서",
        subtitle: sections === 0 ? "목차 없음" : `근거 있는 목차 ${grounded}/${sections}`,
        step: 4,
      });
    }

    if (graph.nodeById.has(AUDIT_NODE_ID)) {
      const checks = result.pre_submit_checks.length;
      labels.push({
        nodeId: AUDIT_NODE_ID,
        title: "신청 전 점검",
        subtitle: checks > 0 ? `확인할 항목 ${checks}건` : "확인할 항목 없음",
        step: 5,
      });
    }

    return new Map(labels.map((label) => [label.nodeId, label]));
  },
};
