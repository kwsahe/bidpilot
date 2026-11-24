"use client";

/**
 * 모든 항목을 **정거장 1~8 순서**로 나열하는 접근성/목록 뷰 (27차 §3-E UNI-04 — 예전에는 노드 종류별 묶음이라 지도의
 * 8정거장 순서와 달랐고, 지도에 그린 조건 ◆ · 자격 ▲ · 문장 ─ · 결정 ◉ 은 목록에 없었다).
 * 3D·2D 없이도 키보드만으로 핵심 업무(선택 → 상세 확인)가 가능해야 한다. 지도가 24 를 넘겨 「외 n건 · 전체 보기」로
 * 보낸 항목도 여기에는 모두 있다.
 */

import { useMemo, useEffect, useRef } from "react";

import { type CosmosGraph, type CosmosNode, type CosmosNodeKind, type WorkflowStage } from "@/lib/cosmos/graph";
import { SEVERITY_LABELS, formatPage, tintStyle } from "@/lib/cosmos/format";
import { nodeColorHex, verdictWord } from "@/lib/cosmos/itemTypes";
import { coverageNoun } from "@/lib/cosmos/mission";
import { requirementCode } from "@/lib/cosmos/reqCode";
import { STATION_GLYPHS, STATION_IDS, STATION_NAMES, stationItemCounts, stationMarkers, type MarkerShape, type StationMarker } from "@/lib/cosmos/stations";
import { COSMOS_COLORS, STATE_LABELS, withAlpha } from "@/lib/cosmos/theme";
import { SYNTHETIC_NOTICE } from "@/lib/terms";

/** 목록 머리의 기호 — 지도와 같은 모양(색은 판정만 말하므로 머리에는 색을 쓰지 않는다 · 27차 §3-D-4). */
const KIND_GLYPH: Record<CosmosNodeKind, string> = {
  notice: "●",
  requirement: "▪",
  "requirement-group": "▪",
  evidence: "▫",
  proposal: "─",
  audit: "⚠",
  finding: "⚠",
  "finding-group": "⚠",
};

/** 지도 표시(marker) 기호 — 지도와 같은 모양. */
const MARKER_GLYPH: Record<MarkerShape, string> = { diamond: "◆", triangle: "▲", bar: "─", target: "◉" };

/** 요구사항의 근거 연결 상태 — 판정 낱말(오른쪽 알약)과 겹치지 않는 중립 말(27차 검수 R27D-OWN-05). */
const EVIDENCE_LINK_WORDS: Record<string, string | null> = { matched: "근거 연결", partial: "근거 일부 연결", unmatched: "근거 미연결", check: null };

export interface NodeListProps {
  graph: CosmosGraph;
  stage: WorkflowStage;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** 단계 요약 행을 누르면 그 단계로(요약은 고를 수 있는 항목이 아니다) */
  onStation?: (stage: WorkflowStage) => void;
}

function nodeMeta(graph: CosmosGraph, node: CosmosNode): string | null {
  switch (node.kind) {
    case "requirement-group":
      // 묶음은 라벨에 이미 건수가 들어 있다. 펼칠 수 있다는 것만 덧붙인다.
      return node.expanded ? "펼침 — 눌러서 접기" : `${node.groupCount ?? 0}건 · 눌러서 펼치기`;
    case "finding-group":
      // 발견 묶음은 3D 에서 펼쳐지지 않는다 — 「펼치기」라고 적으면 눌러도 아무 일이 없는 것처럼 보인다.
      // 상세 패널이 그 묶음의 발견 목록을 연다.
      return `미해결 ${node.groupCount ?? 0}건${
        node.severity ? ` · 심각도 ${SEVERITY_LABELS[node.severity]}` : ""
      } · 눌러서 목록 보기`;
    case "requirement": {
      const req = graph.requirementByNodeId.get(node.id);
      if (!req) return null;
      // 증빙 매핑을 실행하지 않았으면 "근거 미연결" 같은 판정 문구를 붙이지 않는다.
      if (!graph.hasScenario) return `제안요청서 ${formatPage(req.page)}`;
      const link = EVIDENCE_LINK_WORDS[req.displayStatus];
      return link ? `${formatPage(req.page)} · ${link}` : formatPage(req.page);
    }
    case "evidence": {
      const ev = graph.evidenceByNodeId.get(node.id);
      return ev ? `${ev.doc_type} · ${formatPage(ev.page)} · 가상 예시` : null;
    }
    case "finding": {
      const f = graph.findingByNodeId.get(node.id);
      if (!f) return null;
      // 탈락 위험(critical)은 그 말 하나로 — 같은 말을 두 번 찍지 않는다(30차 §3-F #10).
      return `${f.severity === "critical" ? SEVERITY_LABELS.critical : `심각도 ${SEVERITY_LABELS[f.severity]}`}${f.requirement_id ? ` · ${requirementCode(graph.requirements, f.requirement_id)}` : ""}`;
    }
    case "notice":
      return graph.source.origin.kind === "demo"
        ? `${graph.source.notice.agency} · ${SYNTHETIC_NOTICE}`
        : `${graph.source.notice.agency} · ${
            graph.source.notice.pinned
              ? "고정 공고(저장본)"
              : graph.source.origin.source === "g2b"
                ? "나라장터 실시간"
                : "나라장터 저장본"
          }`;
    case "proposal":
      return `${graph.counts.sentences}문장 · 확인 필요 ${graph.counts.sentencesNeedingReview}`;
    case "audit":
      // 발견 141건 중 critical 16건이 「높음 0」 뒤에 숨던 실측이 있었다. 목록 첫 줄에서 먼저 보이게 한다.
      return `${graph.counts.findings}건 찾음${
        graph.counts.findingsBlockingOpen > 0 ? ` · ${SEVERITY_LABELS.critical} ${graph.counts.findingsBlockingOpen}건 안 고침` : ""
      } · ${coverageNoun(graph)} ${graph.coverage.total}개 중 ${graph.coverage.covered}개 반영${
        graph.source.analysis.audit ? " · 실제 검사" : ""
      }`;
  }
}

/**
 * 표시 행을 누르면 — 그 단계로 가서 오른쪽 상세의 **그 항목 줄**로 굴린다(29차 R28-12 · 예전에는 모두 「단계 요약」 · 같은 개요).
 * 상세에 그 줄이 없으면(묶음 · 제안서 문장 · 결정) 단계 개요만 연다 — 부가 줄이 그렇게 말한다.
 */
function revealStationItem(markerId: string): void {
  const reveal = (tries: number) => {
    const row = document.querySelector<HTMLElement>(`[data-station-item="${CSS.escape(markerId)}"]`);
    if (row) {
      row.scrollIntoView({ block: "center" });
      row.animate?.([{ outline: `2px solid ${withAlpha(COSMOS_COLORS.cyan, 90)}` }, { outline: "2px solid transparent" }], { duration: 1600 });
      return;
    }
    if (tries > 0) window.setTimeout(() => reveal(tries - 1), 150);
  };
  window.setTimeout(() => reveal(8), 50);
}

/** 표시 행의 부가 줄 — 누르면 실제로 무엇이 열리는지 사실대로. */
function markerHint(marker: StationMarker, section: WorkflowStage, stage: WorkflowStage): string {
  const where = section === stage ? "" : ` ${section} ${STATION_NAMES[section]} 단계로 가서`;
  if (marker.id.startsWith("cond:") || marker.id.startsWith("qual:")) return `누르면${where} 오른쪽 상세의 이 항목으로`;
  if (marker.count) return `${marker.count}건 묶음 — 누르면${where} 오른쪽 상세의 조건 · 자격 목록`;
  if (marker.id.startsWith("sent:")) return `누르면${where} 오른쪽 상세의 제안서 문장 목록`;
  return `누르면${where} 오른쪽 상세의 단계 개요`;
}

interface StationSection {
  id: WorkflowStage;
  name: string;
  nodes: CosmosNode[];
  markers: StationMarker[];
  count: number;
}

export default function NodeList({ graph, stage, selectedId, onSelect, onStation }: NodeListProps) {
  // 28차 §3-F — 대시보드 기본 화면이다. 지금 단계가 바뀌면 **목록 상자 안에서만** 그 단계 머리로 굴린다
  // (scrollIntoView 는 바깥 페이지까지 굴린다). 첫 화면이 ③ 에 내려앉는 규칙이 목록에서도 보인다.
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = boxRef.current;
    const head = box?.querySelector<HTMLElement>(`#nodelist-station-${stage}`);
    if (!box || !head) return;
    const top = head.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 8;
    box.scrollTo({ top: Math.max(0, top) });
  }, [stage]);
  const sections = useMemo<StationSection[]>(() => {
    const markers = stationMarkers(graph);
    // 45차 M6 — 머리 숫자는 지도 정거장과 같은 수(묶음 줄 하나가 아니라 그 안의 건수 · 「27건」 · 목록 「9」로 갈렸다).
    const counts = stationItemCounts(graph, markers);
    return STATION_IDS.map((id) => {
      const nodes = graph.nodes.filter((n) => n.stage === id);
      const own = markers.filter((m) => m.station === id);
      // 초안 · 점검 점은 지도가 세지 않는다(요약 글을 보인다) — 목록은 줄 수
      return { id, name: graph.steps[id - 1]?.label ?? STATION_NAMES[id], nodes, markers: own, count: counts[id - 1] || nodes.length + own.length };
    }).filter((section) => section.nodes.length + section.markers.length > 0);
  }, [graph]);

  return (
    <div ref={boxRef} className="h-full overflow-y-auto p-4" role="region" aria-label="단계별 항목 목록 — 1~8 단계 순서">
      <div className="mx-auto flex max-w-3xl flex-col gap-5">
        <p className="text-[13px] text-cosmos-secondary">
          이 공고의 항목을 1~8 단계 순서로 봅니다. 항목을 누르면 오른쪽 상세가 바뀝니다 — 조건 · 자격 줄은 상세의 그 항목으로 갑니다.
        </p>
        {sections.map((section) => (
          <section key={section.id} aria-labelledby={`nodelist-station-${section.id}`}>
            <h3
              id={`nodelist-station-${section.id}`}
              className={`mb-2 flex items-center gap-2 text-[13px] font-semibold ${section.id === stage ? "text-cosmos-text" : "text-cosmos-secondary"}`}
            >
              <span
                aria-hidden="true"
                className={`inline-flex h-6 w-6 items-center justify-center rounded-full border text-[13px] tabular-nums ${
                  section.id === stage ? "border-cosmos-cyan text-cosmos-cyan" : "border-cosmos-border-strong"
                }`}
              >
                {section.id}
              </span>
              {section.name}
              <span className="text-cosmos-muted" aria-hidden="true">
                {STATION_GLYPHS[section.id].map((g) => g.glyph).join(" ")}
              </span>
              <span className="font-mono tabular-nums text-cosmos-muted">{section.count}건</span>
              {section.id === stage && <span className="text-[12px] font-medium text-cosmos-cyan">지금</span>}
            </h3>
            <ul className="flex flex-col gap-1.5">
              {section.nodes.map((node) => {
                const selected = node.id === selectedId;
                const meta = nodeMeta(graph, node);
                return (
                  <li key={node.id}>
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelect(selected ? null : node.id)}
                      className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left text-[13px] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan ${
                        selected
                          ? "border-cosmos-border-strong bg-cosmos-elevated"
                          : "border-cosmos-border bg-cosmos-panel hover:border-cosmos-border-strong"
                      }`}
                    >
                      <span aria-hidden="true" className="w-3 shrink-0 text-center" style={{ color: nodeColorHex(node) }}>
                        {KIND_GLYPH[node.kind]}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-cosmos-text">{node.label}</span>
                        {meta && <span className="block truncate text-[12px] text-cosmos-muted">{meta}</span>}
                      </span>
                      <VerdictChip color={nodeColorHex(node)} state={node.state} />
                    </button>
                  </li>
                );
              })}
              {section.markers.map((marker) => (
                <li key={marker.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onStation?.(section.id);
                      if (marker.id.startsWith("cond:") || marker.id.startsWith("qual:")) revealStationItem(marker.id);
                    }}
                    disabled={!onStation}
                    className="flex w-full items-center gap-3 rounded-lg border border-cosmos-border bg-cosmos-panel px-3 py-2 text-left text-[13px] transition-colors hover:border-cosmos-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-cosmos-cyan disabled:cursor-default"
                  >
                    <span aria-hidden="true" className="w-3 shrink-0 text-center" style={{ color: nodeColorHex(marker) }}>
                      {MARKER_GLYPH[marker.shape]}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-cosmos-text">{marker.label}</span>
                      <span className="block truncate text-[12px] text-cosmos-muted">
                        {markerHint(marker, section.id, stage)}
                      </span>
                    </span>
                    <VerdictChip color={nodeColorHex(marker)} state={marker.state} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {sections.length === 0 && <p className="text-[13px] text-cosmos-muted">이 공고에 항목이 없습니다.</p>}
      </div>
    </div>
  );
}

function VerdictChip({ color, state }: { color: string; state: CosmosNode["state"] }) {
  return (
    <span className="shrink-0 rounded-full border px-2 py-0.5 text-[12px] font-medium" style={tintStyle(color)} title={STATE_LABELS[state]}>
      {verdictWord(state)}
    </span>
  );
}
