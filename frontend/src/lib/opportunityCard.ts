/**
 * 사업기회 카드(2.3.0 · 대표 11-04 「vster 처럼 시인성 · 1단계」) — 카드에 싣는 글을 정하는 순수 함수.
 *
 * **목록 응답에 이미 있는 값만 쓴다** — AI 요약을 만들지 않고, 값이 없으면 그 줄을 뺀다(「확인 필요」 같은 빈 말로 채우지 않는다).
 * 부스터(vster)는 AI 요약이 광주 공고의 지역을 「대전」으로 적었다 — 여기서는 원문 칸을 그대로 옮긴다.
 */

import { daysUntil, urgencyTierOf } from "@/lib/deadline";

export type CardLine = { label: string; text: string };

/** D-day 칩 색 — 3일 이하 빨강 · 7일 이하 호박 · 그 밖 보통 · 지남 회색. 칩에 「D-n」 글이 함께 있어 색만으로 뜻을 전하지 않는다. */
export type DdayTone = "urgent" | "soon" | "normal" | "closed" | "none";

export function ddayTone(deadline: string | null | undefined, nowMs: number | null): DdayTone {
  if (!deadline || nowMs === null) return "none";
  const tier = urgencyTierOf(daysUntil(deadline, nowMs), false);
  if (tier === "closed") return "closed";
  if (tier === "urgent") return "urgent";
  if (tier === "soon") return "soon";
  return "normal";
}

/** 줄머리 기호 · 겹 공백을 걷은 한 줄. */
export function cleanLine(text: string | null | undefined): string {
  return String(text ?? "")
    .replace(/\s+/g, " ")
    .replace(/^[\s☞※○●◦·•\-–—▶▷>]+/, "")
    .trim();
}

/** 「받는 것」이 드러나는 문장 — 무료 · 전액 · 최대 · 금액 · 비율 · 선정 수. */
const RECEIVE_RE = /무료|전액|최대|지원금|\d[\d,.]*\s*(?:만|억|천)?\s*원|\d+\s*%|\d+\s*(?:개사|개 기업|명|팀|곳)/;

function sentences(text: string | null | undefined): string[] {
  return String(text ?? "")
    .split(/(?<=[.。!?])\s+|\r?\n+|(?=☞)|(?=○)/)
    .map(cleanLine)
    .filter((s) => s.length >= 4);
}

export interface SupportCardInput {
  target?: string | null;
  requirementSentences?: string[] | null;
  summary?: string | null;
  /** 기업마당 신청방법 원문 한 줄(서버 `submission_text`). 없으면 `applyMethod` 첫 줄. */
  submissionText?: string | null;
  applyMethod?: string | null;
}

/** 지원사업 카드 세 줄 — 대상 · 지원 · 신청. */
export function supportLines(input: SupportCardInput): CardLine[] {
  const lines: CardLine[] = [];
  const target = cleanLine(input.requirementSentences?.find((s) => cleanLine(s))) || cleanLine(input.target);
  if (target) lines.push({ label: "대상", text: target });
  const body = sentences(input.summary).filter((s) => s !== target);
  const receive = body.find((s) => RECEIVE_RE.test(s)) ?? body[0];
  if (receive) lines.push({ label: "지원", text: receive });
  const apply = cleanLine(input.submissionText) || cleanLine(String(input.applyMethod ?? "").split(/\r?\n/).find((s) => cleanLine(s)));
  if (apply) lines.push({ label: "신청", text: apply });
  return lines;
}

export interface BidCardInput {
  /** 「예산 2.8억원」처럼 이미 만든 글. 모르면 null. 기관 · 지역은 카드 메타 줄에 있어 여기 넣지 않는다. */
  budgetText?: string | null;
  /** 일의 종류(「교육 운영 · 콘텐츠 개발」). */
  workText?: string | null;
  awardLine?: string | null;
  submissionMethods?: string[] | null;
  /** 「설명회 2026.11.12(필수)」처럼 이미 만든 글. */
  briefingText?: string | null;
}

/** 입찰 카드 세 줄 — 사업 · 계약 · 접수. */
export function bidLines(input: BidCardInput): CardLine[] {
  const lines: CardLine[] = [];
  const scale = [input.budgetText, cleanLine(input.workText)].filter(Boolean).join(" · ");
  if (scale) lines.push({ label: "사업", text: scale });
  const award = cleanLine(input.awardLine);
  if (award) lines.push({ label: "계약", text: award });
  const intake = [(input.submissionMethods ?? []).map(cleanLine).filter(Boolean).join(" · "), input.briefingText].filter(Boolean).join(" · ");
  if (intake) lines.push({ label: "접수", text: intake });
  return lines;
}

/** 샘플에듀 이 가진 인증(사회적기업 · 여성기업)이 대상에 들어간 공고 — 낱말이 보이는가만 본다(판정이 아니라 거르기). */
const CERT_TARGET_RE = /사회적\s*(?:기업|경제)|여성\s*기업/;

export function mentionsCertTarget(texts: Array<string | null | undefined>): boolean {
  return texts.some((text) => !!text && CERT_TARGET_RE.test(text));
}
