/**
 * 3D 우주가 화면에 적는 «말».
 *
 * 같은 그래프 구조 위에 입찰공고와 지원사업이 나란히 서게 되는데, 3D 안에는
 * 「발주기관」·「나라장터 저장본」·「AI Auditor」 같은 입찰 어휘가 JSX 에 그대로 박혀 있었다.
 * 기업마당 지원사업을 그 화면에 태우면 출처가 기업마당인데도 「나라장터 저장본」라고 적힌다 —
 * 용어가 어색한 정도가 아니라 **거짓 정보**다.
 *
 * 그래서 3D 가 쓰는 문구를 이 객체 하나로 모아 «주입 가능»하게 만든다. 기본값
 * `BID_VOCABULARY` 는 **오늘 화면에 떠 있는 입찰 문자열 그대로**이고, 넘기지 않으면
 * 그것이 쓰인다(기존 호출부 무변경).
 *
 * 주의: 이 파일에 옮겨온 것은 «문구»뿐이다. 여기서 문구를 다듬지 마라 —
 * 배포 중인 입찰 8단계 화면의 출력은 한 글자도 바뀌지 않아야 한다.
 */

import { SYNTHETIC_NOTICE } from "@/lib/terms";
import type { CosmosGraph } from "@/lib/cosmos/graph";
import { coverageNoun } from "@/lib/cosmos/mission";
import type { KeyLabel } from "@/lib/cosmos/guidedFlow";
import { keyLabelMap } from "@/lib/cosmos/guidedFlow";

// 3D 라벨 전용 마감 포맷터는 labels.tsx 가 갖고 있다. 여기서 복제하면 두 곳이 갈라져
// «같은 마감일이 화면마다 달리 적히는» 일이 생기므로 옮기지 않고 그대로 가져다 쓴다.
// 금액은 화면 공통 한 꼴(`formatBudgetCompact` — 「6,000만원」 · 없으면 「예산 미공개」)이다 (27차 UNI-08).
import { formatDeadline } from "@/components/cosmos/three/labels";
import { formatBudgetCompact } from "@/lib/cosmos/format";
import { STATION_IDS, STATION_NAMES } from "@/lib/cosmos/stations";

/** 중앙 카드의 단순 키-값 행. 배열에서 빼면 그 행은 그려지지 않는다. */
export interface CenterRow {
  label: string;
  value: string;
  /** 등폭 숫자로 그릴까 (지금 「마감일」·「예산」이 true) */
  mono?: boolean;
  /** 합성 데모 꼬리표를 붙일까 */
  demo?: boolean;
}

/**
 * 3D 가 화면에 적는 «말». 모든 키가 필수다 — 다른 어휘를 만들 때 하나라도
 * 빠뜨리면 컴파일이 멈추게 하려는 것이다. optional 로 만들지 말 것.
 */
export interface CosmosVocabulary {
  /** 뷰 전체 ARIA 설명 */
  ariaLabel: string;
  /** 중앙 카드 eyebrow. 입찰: "① 분석 대상 공고" */
  centerEyebrow: string;
  /** 중앙 카드 오른쪽 위 출처 문구 */
  originLabel: (graph: CosmosGraph) => string;
  /** 중앙 카드 키-값 행 (적합도/후보 행과 현재단계 행은 제외) */
  centerRows: (graph: CosmosGraph) => CenterRow[];
  /** 적합도/후보 행을 그릴까 */
  showFitRow: boolean;
  /**
   * 중앙 카드에 적는 «지금 화면에 펼쳐 놓은 단계» 라벨.
   *
   * 「현재 단계」가 아니다. 이 값은 사용자가 3D 에서 고르거나 오른쪽 패널에서 열어 본 단계일 뿐,
   * 실제 진행 상황이 아니다. 예전 문구 때문에 진행 현황 2/8 인 공고에서 「현재 단계: 8. 담당자
   * 최종 결정」이 나란히 떠 서로 다른 말을 했다.
   */
  centerStepLabel: string;
  /** 진행바. null 이면 진행바 DOM 자체를 그리지 않는다 (0% 로 그리지 않는다) */
  centerProgress: (graph: CosmosGraph) => number | null;
  /** proposal 허브 칩의 수치. null 이면 수치 span 을 그리지 않는다 */
  proposalBadge: (graph: CosmosGraph) => string | null;
  /** audit 허브 칩의 수치. null 이면 수치 span 을 그리지 않는다 */
  auditBadge: (graph: CosmosGraph) => string | null;
  /** 합성 데모 꼬리표를 붙일까 */
  showDemoTag: (graph: CosmosGraph, hub: "proposal" | "audit") => boolean;
  /** 3D 위에 떠 있는 핵심 라벨 (최대 5개). nodeId → KeyLabel */
  keyLabels: (graph: CosmosGraph) => Map<string, KeyLabel>;
}

/**
 * 입찰 기본 어휘 = **오늘 화면에 떠 있는 문자열 그대로**.
 * 전부 원래 JSX 에서 잘라 옮긴 것이고, 새로 쓴 문구는 하나도 없다.
 */
export const BID_VOCABULARY: CosmosVocabulary = {
  // 지금 지도(27차 §3-D)를 말한다 — 정거장 이름은 사전에서 · 지금 정거장만 기호와 이름표(검수 R27D-08 · R27REQ-08).
  ariaLabel: `Evidence Cosmos 3D 지도 — ${STATION_IDS.map((id) => STATION_NAMES[id]).join(" → ")}, 정거장 8개의 길. 지금 정거장만 기호와 이름표가 있고 나머지는 이름 알약. 항목 목록은 우측 패널과 「목록」 보기에서 키보드로 탐색`,

  centerEyebrow: "분석 대상 공고",

  originLabel: (graph) => {
    const { origin } = graph.source;
    return origin.kind === "demo"
      ? SYNTHETIC_NOTICE
      : origin.source === "g2b"
        ? "실제 나라장터 공고"
        : "나라장터 저장본";
  },

  centerRows: (graph) => {
    const { notice } = graph.source;
    return [
      { label: "발주기관", value: notice.agency },
      { label: "마감일", value: formatDeadline(notice.deadline_at), mono: true },
      { label: "예산", value: formatBudgetCompact(notice.budget), mono: true },
    ];
  },

  showFitRow: true,

  centerStepLabel: "현재 보는 단계",

  centerProgress: (graph) => graph.progress,

  proposalBadge: (graph) => `${coverageNoun(graph)} ${graph.coverage.total}개 중 ${graph.coverage.covered}개 반영`,

  auditBadge: (graph) => `발견 ${graph.counts.findings}건`,

  // 실제로 생성한 제안서·실제로 돌린 검사면 데모 꼬리표를 붙이지 않는다 —
  // 실결과를 데모로 읽히게 하면 안 된다.
  showDemoTag: (graph, hub) =>
    hub === "proposal" ? !graph.source.analysis.proposal : !graph.source.analysis.audit,


  keyLabels: (graph) => keyLabelMap(graph),
};
