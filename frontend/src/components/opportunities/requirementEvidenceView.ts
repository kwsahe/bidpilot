/**
 * 요구사항 정리표의 「회사 근거 연결」 한 벌 — KPI · 필터 설명 · 표 행 · 상세가 이것 하나만 읽는다 (27차 §3-F).
 *
 * 상태 코드는 대시보드와 같은 `evidenceRunState` 에서 온다(RFP-05 — 여기만 3단계를 따로 세던 것). 그 위에 이
 * 화면만 아는 두 사실을 얹는다:
 *  - **공고 출처** — 「합성 데모 공고라 합성 회사자료로 …」는 합성 데모 공고에서만 참이다. 실공고의 옛 공개 초안이
 *    합성 근거를 인용했을 뿐인데 그 문장이 붙었다(RFP-01 · ISSUE-162).
 *  - **레거시 공개 결과** — 이 회사 기준 분석이 없어 예전 공개 제안서를 대신 읽은 것은 「이 회사가 돌려 실패했다」가
 *    아니다. 행마다 「연결 실패」가 붙었다(RFP-03).
 */

import { evidenceRunState, type CosmosGraph } from "@/lib/cosmos/graph";
import { SYNTHETIC_NOTICE } from "@/lib/terms";

/** not_run 근거 연결 전 · old 지금 쓸 수 없는 이전 결과 · failed 돌렸는데 붙은 것 없음 · off AI 검색 꺼 둠(원장 후보에서 고름) · ran 연결됨 */
export type EvidenceMode = "not_run" | "old" | "failed" | "off" | "ran";

export interface RfpEvidenceView {
  mode: EvidenceMode;
  /** 합성 데모 공고의 합성 근거 연결인가 — 이때만 행별 연결(시나리오)이 있다 */
  demo: boolean;
  /** 행마다 연결 정보가 있는가. 실공고 결과는 제안서 문장 단위로만 저장돼 행 상태를 알 수 없다(RFP-04). */
  rowLinks: boolean;
  /** 사람이 읽는 한 줄 — 필터 설명 · 상세가 같은 글을 쓴다 */
  note: string;
  /** KPI 칸 짧은 값 · 힌트 */
  kpiValue: string | null;
  kpiHint: string;
  groundedCount: number;
  documentCount: number;
}

/** 「9월 16일」 — 옛 실패 사유가 지금 상태처럼 읽히지 않게 실행 날짜를 붙인다(RFP-07). */
export function runDateText(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

export function rfpEvidenceView(graph: CosmosGraph): RfpEvidenceView {
  const evidence = evidenceRunState(graph);
  const proposal = graph.source.analysis.proposal ?? null;
  const demo = graph.source.origin.kind === "demo";
  const base = { demo: false, rowLinks: false, groundedCount: evidence.groundedCount, documentCount: evidence.documentCount };
  const ranOn = runDateText(proposal?.generated_at);

  // 실공고에 합성 근거가 섞인 결과(옛 공개 초안 인용 · 규칙 전 저장본)는 쓸 수 없는 이전 결과다.
  if (!demo && evidence.synthetic) {
    return {
      ...base,
      mode: "old",
      note: "가상 예시 근거가 섞인 이전 결과입니다 — 이 회사 기준으로 제안서를 다시 만드세요.",
      kpiValue: "이전 결과",
      kpiHint: "가상 예시 근거가 섞여 있어 쓰지 않습니다",
    };
  }
  if (!demo && proposal?.legacy_result) {
    return {
      ...base,
      mode: "not_run",
      note: "이 회사 기준 근거 연결 결과가 없습니다 — 예전 공개 결과만 있어 근거 연결 전으로 봅니다.",
      kpiValue: "연결 전",
      kpiHint: "이 회사 기준 결과 없음 · 예전 공개 결과만 있음",
    };
  }
  switch (evidence.status) {
    case "not_run":
      return {
        ...base,
        mode: "not_run",
        note: "회사 근거 연결을 아직 하지 않았습니다 — 제안서를 만들 때 함께 합니다. 근거를 찾다가 못 찾았다는 뜻이 아닙니다.",
        kpiValue: "연결 전",
        kpiHint: "회사 근거 연결은 제안서를 만들 때 함께 합니다",
      };
    case "stale":
      return {
        ...base,
        mode: "old",
        note: "요구사항이 바뀌기 전의 근거 연결 결과입니다 — 제안서를 다시 만들어야 지금 표와 맞습니다.",
        kpiValue: "이전 결과",
        kpiHint: "요구사항이 바뀌기 전 결과",
      };
    case "off":
      // 45차 H5 — AI 검색을 꺼 둔 것은 실패가 아니다. 행마다 「붙이기 실패」가 붙었다
      return {
        ...base,
        mode: "off",
        note: "회사 근거 연결(AI 검색)은 꺼 두었습니다 — 실패가 아닙니다. 행 상세 「실적 원장 후보」에서 쓸 것을 「채택」하면 다음에 만드는 초안부터 근거로 씁니다.",
        kpiValue: "AI 검색 꺼 둠",
        kpiHint: "실적 원장 후보에서 고르기",
      };
    case "failed_key":
    case "failed_credit":
    case "failed_other": {
      const when = ranOn ? ` (${ranOn} 실행 결과)` : "";
      return {
        ...base,
        mode: "failed",
        note: `근거 연결은 실행했지만 붙은 근거가 없습니다 — ${evidence.failureNote ?? "사유 미확인"}${when}`,
        kpiValue: "0건",
        kpiHint: ranOn ? `${ranOn} 실행 결과 · 사유는 아래 설명` : "사유는 아래 설명",
      };
    }
    default:
      if (demo) {
        return {
          ...base,
          demo: true,
          rowLinks: true,
          mode: "ran",
          note: `${SYNTHETIC_NOTICE}라 가상 예시 회사자료로 만든 근거 연결이 반영돼 있습니다.`,
          kpiValue: null,
          kpiHint: "",
        };
      }
      return {
        ...base,
        mode: "ran",
        note: `회사자료 ${evidence.documentCount}종 · 제안서 ${evidence.groundedCount}문장에 연결된 결과입니다. 항목별 연결은 저장되지 않아 표의 항목은 「항목별 기록 없음」입니다.`,
        kpiValue: `${evidence.groundedCount}문장`,
        kpiHint: `회사자료 ${evidence.documentCount}종 · 제안서 문장 기준`,
      };
  }
}
