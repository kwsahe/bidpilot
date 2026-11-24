import type { CosmosGraph } from "@/lib/cosmos/graph";

/**
 * 「공고 다시 분석」 단추 — 전체 보기 `TopBar` 와 쉬운 보기 4단계 펼침 머리가 **같은 이름 · 같은 확인**을 쓴다 (24차 §3-2).
 *
 * 같은 「다시 하기」가 화면마다 재분석·분석 실행·다시 파싱·다시 탐지·검사 실행으로
 * 다르게 불렸다. 담당자는 그것들이 같은 것인지 다른 것인지 알 수 없다 (ISSUE-019).
 * 이 버튼의 이름은 「공고 다시 분석」 하나다.
 *
 * 다시 분석하면 첨부를 다시 내려받아 요구사항을 새로 뽑는다. 요구사항이 바뀌면
 * 이미 만든 제안서·점검 결과가 «구버전»이 되고, 승인·GO 도 다시 받아야 한다.
 * 클릭 한 번으로 그렇게 되면 안 된다 — 한 번 묻는다.
 * 아직 한 번도 분석하지 않았으면 잃을 것이 없으므로 묻지 않는다.
 */
export function analyzeControl(graph: CosmosGraph | null, analyzing: boolean, onAnalyze: () => void) {
  const alreadyParsed = Boolean(graph && graph.counts.requirements > 0);
  return {
    label: analyzing ? "분석 중…" : alreadyParsed ? "공고 다시 분석" : "공고 분석 시작",
    title: alreadyParsed ? "첨부를 다시 내려받아 요구사항을 새로 뽑습니다 (확인 후 실행)" : "첨부를 내려받아 요구사항을 뽑습니다",
    run: () => {
      if (!alreadyParsed) {
        onAnalyze();
        return;
      }
      const ok = window.confirm(
        `공고를 다시 분석하면 요구사항을 새로 뽑습니다.
요구사항이 바뀌면 지금 제안서와 점검 결과는 구버전이 되고, 다시 만들어야 합니다.

계속할까요?`,
      );
      if (ok) onAnalyze();
    },
  };
}
