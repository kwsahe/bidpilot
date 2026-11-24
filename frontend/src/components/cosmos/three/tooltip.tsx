"use client";

/**
 * 위험 노드 hover 툴팁 내용 (계약 파일). 스타일은 라벨 칩과 같은 글래스 언어를 쓴다.
 * nodes.tsx가 FloatingLabel 안에 이 카드를 넣어 렌더한다.
 */

import { findingTypeLabel, findingWhy, type FindingView } from "@/lib/cosmos/graph";
import { SEVERITY_LABELS as SEVERITY_LABEL } from "@/lib/cosmos/format";
import { COSMOS_HEX } from "@/lib/cosmos/theme";
import { displayCodeOf } from "@/lib/cosmos/itemTypes";

// 심각도 이름은 사전 하나(`SEVERITY_LABELS`) — 3D 툴팁만 「참가 차단 · 높음」으로 달랐다(31차 R30-31).

export function RiskTooltipCard({ finding }: { finding: FindingView }) {
  // 해결 = 충족(청록) — 지도 기호 · 상세 패널과 같은 색(27차 §3-E 검증 G2-V2 · 예전 초록)
  const accent = finding.resolved
    ? COSMOS_HEX.cyan
    : finding.severity === "critical" || finding.severity === "high"
      ? COSMOS_HEX.red
      : COSMOS_HEX.amber;
  return (
    <div
      className="w-[236px] rounded-lg border border-cosmos-border-strong bg-cosmos-panel px-3 py-2.5 shadow-[0_10px_28px_rgba(0,0,0,0.45)] backdrop-blur-md"
      style={{ boxShadow: `0 10px 28px rgba(0,0,0,0.45), inset 3px 0 0 ${accent}` }}
    >
      <div className="flex items-center gap-1.5">
        <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: accent }} />
        <span className="text-[13px] font-medium uppercase tracking-[0.12em] text-cosmos-muted">
          제출 전 점검 · 심각도 {SEVERITY_LABEL[finding.severity]}
          {finding.resolved ? " · 담당자 해결 처리" : ""}
        </span>
      </div>
      <p className="mt-1 text-[13px] font-semibold leading-[1.35] text-cosmos-text">
        {findingTypeLabel(finding.finding_type)}
        {finding.requirement_id && (
          <span className="ml-1.5 font-mono text-[13px] font-normal text-cosmos-secondary">
            {/* 45차 마지막 검토 — 패널과 같은 화면 코드(EVL-026 · 저장 id REQ-026 이 보였다) */}
            {finding.requirement ? displayCodeOf(finding.requirement) : finding.requirement_id}
          </span>
        )}
      </p>
      <p className="mt-1 text-[13px] leading-[1.45] text-cosmos-secondary">{findingWhy(finding)}</p>
      {finding.resolved && finding.resolution && (
        <p className="mt-1 text-[13px] leading-[1.4] text-cosmos-cyan">
          {finding.resolution.reviewer} 해결 처리{finding.resolution.note ? ` — ${finding.resolution.note}` : ""}
        </p>
      )}
      {finding.proposal_text && (
        <p className="mt-1.5 line-clamp-2 text-[13px] leading-[1.4] text-cosmos-muted">
          초안: “{finding.proposal_text}”
        </p>
      )}
    </div>
  );
}
