"use client";

/**
 * 상세 범례 — 오른쪽 Side Sheet. 3D 핵심 영역을 가리지 않는다.
 * 닫기 버튼·Esc·바깥 클릭으로 닫히고, 열릴 때 제목에 focus를 준다.
 */

import { useEffect, useId, useRef } from "react";

import { Badge } from "@/components/ui/primitives";
import { STRUCTURE_LINE } from "@/components/cosmos/GuidedFlowBar";
import { VERDICT_KEY } from "@/lib/cosmos/itemTypes";
import { STEP_STATUS_META } from "@/lib/cosmos/stepStatus";
import { SYNTHETIC_NOTICE } from "@/lib/terms";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";

export interface LegendSheetProps {
  open: boolean;
  onClose: () => void;
  /** 2D 흐름도인지 3D인지 (설명 문장이 다르다) */
  viewMode: "3d" | "2d" | "list";
}

/**
 * 기호 — **종류당 하나** (21차 · prompt_11 §3-3). 모양이 종류를, 색이 판정을 말한다(아래 STATUSES).
 * 3D 와 2D 가 같은 기호를 쓴다.
 */
const NODE_KINDS: Array<{ label: string; glyph: string; meaning: string }> = [
  { label: "1 공고", glyph: "●", meaning: "분석 대상 입찰공고 — 공고명·발주기관·마감·예산" },
  { label: "3 놓치면 안 되는 조건", glyph: "◆", meaning: "설명회 필참 · 제출 기한처럼 놓치면 참가가 막히는 조건 (이름표 앞 「조건 · 」)" },
  { label: "3 참가자격 조항", glyph: "▲", meaning: "입찰공고문의 참가자격 — 3단계 체크리스트와 같은 줄 (이름표 앞 「자격 · 」)" },
  { label: "4 요구사항", glyph: "▪", meaning: "제안요청서에서 뽑은 과업·조건 (묶음은 큰 네모)" },
  { label: "5 회사 근거", glyph: "▫", meaning: "담당자가 승인한 회사자료 문서" },
  { label: "6 제안서 · 문장", glyph: "─", meaning: "제안서 초안(긴 막대)과 대응 문장(짧은 막대)" },
  { label: "7 점검 · 발견", glyph: "⚠", meaning: "제출 전 누락 점검(큰 삼각형)과 그것이 찾은 문제(작은 삼각형)" },
  { label: "8 결정", glyph: "◉", meaning: "담당자 최종 결정 · 초안 검토 · 입찰 참여 여부" },
];

/**
 * 색은 판정 뜻만 — 네 가지. **낱말은 지도 아래 범례 줄과 글자까지 같다**(`VERDICT_KEY` · 27차 §3-D-4).
 * 뜻풀이만 여기서 붙인다.
 */
const VERDICT_MEANING: Record<string, string> = {
  충족: "근거가 채택됐거나 조항을 충족 — 해결된 발견도 여기",
  "확인 필요": "모호한 조건 · 후보 근거만 있음 · 높음 미만 발견 — 자동으로 충족 처리하지 않음",
  문제: "참가를 막는 조항 · 점검에서 나온 높음 이상 문제",
  "판정 전": "아직 판정하지 않았거나 연결된 근거가 없음",
};
const STATUSES = VERDICT_KEY.map((key) => ({ label: key.word, color: key.color, meaning: VERDICT_MEANING[key.word] ?? "" }));

/** 선 셋 — 고른 항목에서 관련 정거장마다 하나(최대 3). 회청 선은 없다 (27차 §3-D-3 · 5). */
const LINKS: Array<{ label: string; color: string; dash: boolean; meaning: string }> = [
  { label: "연결됨", color: COSMOS_COLORS.cyan, dash: false, meaning: "채택된 근거 · 제안서 · 점검으로 이어진 연결" },
  { label: "확인이 필요한 연결", color: COSMOS_COLORS.amber, dash: true, meaning: "후보 근거만 있거나 높음 미만 발견이 걸린 연결" },
  { label: "문제", color: COSMOS_COLORS.red, dash: false, meaning: "높음 이상 발견이 걸린 연결 — 밝기가 천천히 깜빡인다" },
];

export default function LegendSheet({ open, onClose, viewMode }: LegendSheetProps) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus({ preventScroll: true });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      // aria-modal 창이다 — Tab 이 뒤 화면으로 빠져나가지 않게 처음 ↔ 끝을 잇는다 (DSH-30).
      const box = panelRef.current;
      if (event.key !== "Tab" || !box) return;
      const items = [...box.querySelectorAll<HTMLElement>('button, a[href], [tabindex]:not([tabindex="-1"])')];
      const edge = event.shiftKey ? items[0] : items[items.length - 1];
      if (edge && (document.activeElement === edge || !box.contains(document.activeElement))) {
        event.preventDefault();
        (event.shiftKey ? items[items.length - 1] : items[0]).focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      restoreRef.current?.focus({ preventScroll: true });
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" aria-label="상세 범례 닫기" onClick={onClose} className="absolute inset-0 cursor-default bg-cosmos-bg/40" />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="mc-scroll relative flex h-full w-full max-w-[360px] flex-col gap-4 overflow-y-auto border-l border-cosmos-border p-4 shadow-[-12px_0_40px_var(--cosmos-shadow)]"
        style={{ backgroundColor: "var(--cosmos-overlay)", animation: "mc-fade-up 160ms ease-out" }}
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-cosmos-cyan">범례</p>
            <h2 id={headingId} ref={headingRef} tabIndex={-1} className="mc-focus mt-0.5 text-[17px] font-semibold text-cosmos-text">
              상세 범례 · 읽는 법
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기 (Esc)"
            className="mc-focus min-h-9 rounded-lg border border-cosmos-border px-2.5 text-[13px] text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
          >
            ✕
          </button>
        </div>

        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">구조</h3>
          <p className="text-[13px] leading-6 text-cosmos-text">{STRUCTURE_LINE}</p>
          <p className="text-[13px] leading-5 text-cosmos-secondary">
            왼쪽에서 오른쪽으로 가는 정거장 8개의 길입니다(레일 8단계와 같은 이름·순서). <strong className="text-cosmos-text">지금 정거장에만</strong> 기호와 이름표가 붙고,
            나머지 일곱 정거장은 이름 알약(번호 · 이름 · 개수 · 상태 기호{" "}
            {(["done", "active", "attention", "failed", "pending"] as const).map((k) => `${STEP_STATUS_META[k].glyph} ${STEP_STATUS_META[k].label}`).join(" · ")})으로 남고, 레일이 「확인 필요」 ·
            「실패」인 단계에는 같은 낱말 알약이 붙습니다(칸이 좁으면 기호 하나). 알약을 누르면 그 정거장으로 갑니다. 정거장 이름 아래 글은 지금
            정거장이면 그 단계 요약(레일과 같은 글), 나머지는 항목 수입니다. 선은 항목(기호나 이름표)을 누르면 관련 정거장마다 하나씩(최대 셋)
            마지막 줄 아래 길을 따라 보입니다. 이름표 끝 「!」 · 「✕」는 칸이 좁아 줄인 「확인 필요」 · 「문제」입니다. 3 참가 여부가
            「불가」면 붉게 잠기고 3→4 길이 끊깁니다.{viewMode === "2d" ? " 2D 는 같은 길을 평면으로 그린 것입니다." : ""}
          </p>
          {/* 2D 드래그는 이동 · 좁은 화면 레일은 위쪽 · 휠만 굴리면 페이지가 내려간다 (DSH-18 · DSH-22) */}
          <p className="text-[13px] leading-5 text-cosmos-muted">
            조작: 레일(넓은 화면은 왼쪽 · 좁은 화면은 위쪽)의 단계를 누르면 그 정거장으로 · 드래그 {viewMode === "2d" ? "이동" : "회전"} · Ctrl+휠
            확대 · Esc 선택 해제 · 지도 아래 도구막대(안내 · 범례 · 선택 해제)
          </p>
        </section>

        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">기호 (종류당 하나)</h3>
          <ul className="flex flex-col gap-1.5">
            {NODE_KINDS.map((k) => (
              <li key={k.label} className="flex items-start gap-2 text-[13px] leading-5">
                <span aria-hidden="true" className="w-4 shrink-0 text-center text-[15px] leading-5 text-cosmos-text">
                  {k.glyph}
                </span>
                <span className="min-w-0">
                  <span className="font-semibold text-cosmos-text">{k.label}</span>
                  <span className="block text-cosmos-secondary">{k.meaning}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="flex flex-col gap-1.5 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 p-3">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">헷갈리기 쉬운 것</h3>
          <p className="text-[12px] leading-5 text-cosmos-secondary">
            <span className="font-semibold text-cosmos-text">과업 vs 필수 요구사항</span> — 과업은 「무엇을 수행하나」(교육 운영, 교재 개발), 요구사항은 「어떤 조건을 충족하나」(인력 5년 이상, 계정 1인 1개). 과업은 제안서 수행계획이, 요구사항은 회사 근거가 답합니다.
          </p>
          <p className="text-[12px] leading-5 text-cosmos-secondary">
            <span className="font-semibold text-cosmos-text">놓치면 안 되는 조건 vs 참가 가능 여부</span> — 참가 가능 여부는 지역·업종·등록 같은 자격을 「가능 · 확인 필요 · 불가」로 판정한 것이고, 놓치면 안 되는 조건은 설명회 필참·보증금·방문제출처럼 사람이 행동해야 하는 항목입니다. 참가를 막는 조건이 남아 있으면 「참여」를 저장할 수 없습니다.
          </p>
        </section>

        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">상태 색</h3>
          <ul className="flex flex-col gap-1">
            {STATUSES.map((s) => (
              <li key={s.label} className="flex items-start gap-2 text-[12px] leading-5">
                <span aria-hidden="true" className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: s.color }} />
                <span>
                  <span className="font-semibold text-cosmos-text">{s.label}</span>
                  <span className="text-cosmos-secondary"> — {s.meaning}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">연결선</h3>
          <ul className="flex flex-col gap-1">
            {LINKS.map((l) => (
              <li key={l.label} className="flex items-start gap-2 text-[12px] leading-5">
                <svg aria-hidden="true" width="26" height="8" className="mt-2 shrink-0">
                  <line x1="1" y1="4" x2="25" y2="4" stroke={l.color} strokeWidth="2.5" strokeLinecap="round" strokeDasharray={l.dash ? "4 3" : undefined} />
                </svg>
                <span>
                  <span className="font-semibold text-cosmos-text">{l.label}</span>
                  <span className="text-cosmos-secondary"> — {l.meaning}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">값의 출처</h3>
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="ok" glyph="●">실제 나라장터 공고</Badge>
            <Badge tone="info" glyph="◐">나라장터 저장본</Badge>
            <Badge tone="demo">{SYNTHETIC_NOTICE}</Badge>
            <Badge tone="info" glyph="▣">규칙 기반</Badge>
            <Badge tone="pass" glyph="✓">AI 분석</Badge>
            <Badge tone="pass" glyph="✎">사람 확인</Badge>
            <Badge tone="muted" glyph="○">아직 안 함</Badge>
          </div>
          <p className="text-[12px] leading-4 text-cosmos-muted">「아직 안 함」은 값이 0이라는 뜻이 아니라 그 단계를 아직 하지 않았다는 뜻입니다.</p>
        </section>
      </aside>
    </div>
  );
}
