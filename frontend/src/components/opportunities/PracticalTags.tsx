"use client";

/**
 * 목록 행 꼬리표 (37차 §3-B-5 · D11) — 접수방식 · 유형(근사) · 분류(신규 · 긴급 등) · 「단독으로는 큼 · 파트너형」.
 *
 * 값은 모두 서버가 매겨 보낸 것이다(`practical_priority`) — 화면이 다시 계산하지 않는다. **점수가 아니다** — 순서와 칸의 이유를
 * 보이는 표시다. 작게(12px), 한 줄에서 넘치면 줄을 바꾼다(check_visibility 겹침 · check_screen_rules 가로 넘침).
 */

import { createContext, useContext } from "react";

import type { Tone } from "@/lib/cosmos/theme";
import { LATE_TAG, TYPE_APPROX } from "@/lib/terms";
import type { UnifiedOpportunity } from "@/types/opportunity";

/** 회사가 고른 순서 방식 — 실무 우선순위 회사는 분류 칸이 「우선 검토 · 검토」 표시를 대신한다(§3-B-4). */
export const RankingMethodContext = createContext<"score" | "practical">("score");

export function useRankingMethod(): "score" | "practical" {
  return useContext(RankingMethodContext);
}

/** 분류 칸 색 — 색만으로 말하지 않게 글자와 함께 쓴다. */
export const GROUP_TONE: Record<string, Tone> = {
  선제준비: "info",
  "신규+여유": "pass",
  직접도전: "pass",
  조건부: "warn",
  "일반 접수 중": "ok",
  긴급: "warn",
  "파트너형 후보": "muted",
  비추천: "muted",
  제외: "fail",
};

/** 분류 칸의 한 줄 풀이(도움말). */
export const GROUP_HELP: Record<string, string> = {
  선제준비: "사전규격 — 본공고 전에 준비할 것. 입찰 목록이 아니라 「선제준비」 탭에 따로 있습니다(의견 마감은 입찰 마감이 아닙니다)",
  "신규+여유": "공고 7일 이내 · 실제 마감까지 21일 이상 — 가장 먼저 볼 것",
  직접도전: "참가 「가능」 · 마감까지 14일 이상",
  조건부: "「확인 필요」 — 회사자료에 값을 적거나 직접 확인하면 정해집니다",
  "일반 접수 중": "마감까지 14일 이상 또는 마감일 없음",
  // 43차 RANK-11 — 실무 문서 §2.5: 8~13일은 긴급 검토, 7일 이하만 자료 · 파트너가 이미 있을 때
  긴급: "실제 마감까지 13일 이하 — 8~13일은 긴급 검토, 7일 이하는 자료 · 파트너가 이미 있을 때만",
  "파트너형 후보":
    "사업비가 회사가 혼자 맡을 수 있는 최대 사업비를 넘는 공고 — 개발 · 연구 · 그 밖은 상한 초과, 교육 · 컨설팅은 상한의 2배 초과(광주 · 전남 발주는 본업 칸에 남김) — 또는 우리 등록 업종에 없는 업종을 요구해 공동수급이 필요한 공고(크기 · 지역과 상관없이). 본업 공고 뒤에 따로 모읍니다",
  비추천: "회사 본업과 관련이 낮음 — 사유가 행에 적혀 있습니다",
  제외: "마감 또는 참가 「불가」",
};

const TYPE_HELP: Record<string, string> = {
  A1: "교육 운영",
  A2: "교육 콘텐츠 · 교재 · 과정 개발",
  B1: "컨설팅",
  B2: "연구",
  C: "개발 · 구축",
  D: "감리 · 구매 · 공사 · 미분류",
  수혜: "지원금을 받는 사업(매출 아님)",
};

const TAG = "inline-flex shrink-0 items-center whitespace-nowrap rounded border px-1.5 py-px leading-4";
/** 긴 꼬리표(이유가 붙은 AI · 주제 · 대형) — 줄바꿈을 허용한다(41차 FRONT-R40-01 · 375 · 390 폭에서 화면 밖으로 넘쳤다). */
const TAG_WRAP = "inline-flex min-w-0 max-w-full items-center whitespace-normal break-keep [overflow-wrap:anywhere] rounded border px-1.5 py-px leading-4";
const LONG_TAG = 16;

/**
 * 꼬리표 줄. `withGroup` 이면 분류 칸도 꼬리표로 적는다 — 실무 우선순위 회사는 분류가 판정 옆 배지 자리에 이미 있어 뺀다.
 */
export function PracticalTags({ item, withGroup, size = "sm" }: { item: UnifiedOpportunity | null; withGroup: boolean; size?: "sm" | "md" }) {
  // 41차 FRONT-R40-04 — 점수순 회사는 꼬리표만 붙고 순서는 그대로다(「뒤에 둡니다」는 실무 우선순위 회사만)
  const method = useRankingMethod();
  if (!item) return null;
  const moves = method === "practical";
  const methods = (item.submission_methods ?? []).filter(Boolean);
  const type = item.fit_type ?? null;
  const tags: { key: string; text: string; title: string; tone?: "amber" }[] = [];
  if (methods.length > 0) {
    tags.push({
      key: "method",
      text: `접수 ${methods.join(" · ")}`,
      title: item.submission_text ? `접수방식 — 신청방법 원문: 「${item.submission_text}」` : "접수방식(나라장터 공고 필드 그대로)",
    });
  }
  if (type) {
    tags.push({
      key: "type",
      text: `${TYPE_APPROX} ${type}`,
      title: `${TYPE_HELP[type] ?? type}${item.fit_type_basis ? ` — ${item.fit_type_basis}` : ""} · 사업담당자 운영매뉴얼을 받기 전 근사치이고 점수에는 쓰지 않습니다`,
    });
  }
  if (item.recruit_kind === "수행기관 모집(매출)") {
    tags.push({ key: "recruit", text: item.recruit_kind, title: "지원금을 받는 사업이 아니라 사업을 운영할 기관을 뽑는 공고입니다 — 입찰처럼 수행 자격을 확인하세요" });
  }
  if (withGroup && item.practical_group) {
    tags.push({ key: "group", text: item.practical_group, title: GROUP_HELP[item.practical_group] ?? item.practical_group });
  }
  // 38차 D14 · DOCS-01 — 꼬리표 글은 서버가 정한 값 그대로(브리핑 판단 낱말과 같은 함수). 공동수급 불허면 「파트너형」이라 하지 않는다.
  if (item.partner_tag) {
    tags.push({
      key: "partner",
      text: item.partner_tag,
      title: item.industry_partner
        ? "우리 등록 업종에 없는 업종을 요구하지만 공동수급을 허용(또는 아직 모름)하는 공고 — 그 업종을 가진 회사와 공동수급할 때만 참가할 수 있어 크기 · 지역과 상관없이 「파트너형 후보」 칸에 모입니다. 공동이행은 보통 구성원 모두 그 업종이 필요합니다(공고문 확인)"
        : "사업비가 회사가 적은 「혼자 맡을 수 있는 최대 사업비」를 넘는 공고(개발 · 연구 · 그 밖은 상한 초과, 교육 · 컨설팅은 상한의 2배 초과) — 점수는 그대로이고, 실무 우선순위에서는 본업 공고 뒤 「파트너형 후보」 칸에 모입니다(광주 · 전남 발주는 본업 칸에 남김). 공동수급이 안 되면 파트너로 자격을 보완할 수 없습니다",
      tone: "amber",
    });
  }
  // 39차 결정 2 — 교육 · 컨설팅이 단독 상한보다 크고 2배 이하(본업 칸에 남음). 글은 서버 값 그대로.
  if (item.scale_tag) {
    tags.push({
      key: "scale",
      text: item.scale_tag,
      title: "교육 · 컨설팅 사업비가 회사가 적은 「혼자 맡을 수 있는 최대 사업비」보다 크지만 2배 안이라 본업 칸에 남깁니다 — 2배를 넘으면 「파트너형 후보」 칸으로 갑니다. 점수는 그대로입니다",
      tone: "amber",
    });
  }
  // 40차 결정 1 · D23 — 교육 · 컨설팅인데 공고명에 회사 사업 주제가 없음(본업 칸 안에서 주제가 맞는 공고 뒤). 글은 서버 값 그대로.
  if (item.topic_note) {
    tags.push({
      key: "topic",
      text: item.topic_note,
      title:
        "교육 · 컨설팅 공고인데 공고명에 회사 사업 주제(AI · 디지털 · 데이터 · ESG · 이러닝 등)가 없습니다 — " +
        (moves
          ? "숨기지 않고 본업 칸 안에서 주제가 맞는 공고 뒤에 둡니다. 판정 · 점수는 그대로입니다"
          : "점수순 회사라 순서는 바꾸지 않고 꼬리표만 붙입니다. 판정 · 점수 · 순서는 그대로 — 원문으로 확인하세요"),
      tone: "amber",
    });
  }
  // 40차 결정 2 · D24 — AI 적합도 보조(참고용). 「주제 확인」과 같은 자리로 보낼 뿐 판정 · 점수 · 접기에는 쓰지 않습니다.
  if (item.ai_fit_note) {
    tags.push({
      key: "ai-fit",
      text: item.ai_fit_note,
      title:
        "AI 판단 — 참고용. 공고명 · 분류 · 기관 · 예산만 보고 AI 가 「본업이 아닐 수 있다」고 본 공고입니다 — " +
        (moves ? "본업 칸 뒤쪽에 둘 뿐 판정 · 점수는 그대로입니다. 원문으로 확인하세요" : "순서 · 판정 · 점수는 그대로입니다. 원문으로 확인하세요"),
      tone: "amber",
    });
  }
  // 43차 Q9 — 같은 기업마당 사업이 여러 운영기관으로 온 묶음(붙여 세우고 광주 · 전남 운영기관 먼저). 글은 서버 값 그대로.
  if (item.same_program_note) {
    tags.push({ key: "same-program", text: item.same_program_note, title: "같은 사업을 운영기관마다 따로 모집합니다 — 붙여 세우고 광주 · 전남 운영기관을 앞에 둡니다. 점수 · 판정은 각자 그대로입니다" });
  }
  // 38차 §3-C-5 — 최근 7일 안에 마감 · 첨부 · 차수 · 종류가 바뀐 공고(지역 변경은 뺌).
  if ((item.changed_fields ?? []).length > 0) {
    tags.push({
      key: "changed",
      text: `변경됨 · ${(item.changed_fields ?? []).join(" · ")}`,
      title: "최근 7일 안에 나라장터 공고의 마감 · 첨부 · 차수 · 종류가 바뀌었습니다 — 공고 원문에서 무엇이 바뀌었는지 확인하세요",
      tone: "amber",
    });
  }
  if (item.deadline_note) {
    tags.push({ key: "late", text: LATE_TAG, title: "실제 마감까지 3일 이하 — 사업담당자 기준 「원칙적으로 후순위」", tone: "amber" });
  }
  if (tags.length === 0) return null;
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1" data-practical-tags>
      {tags.map((tag) => (
        <span
          key={tag.key}
          title={tag.title}
          className={`${tag.text.length > LONG_TAG ? TAG_WRAP : TAG} ${size === "md" ? "text-[14px]" : "text-[12px]"} ${tag.tone === "amber" ? "border-cosmos-amber/50 text-cosmos-amber" : "border-cosmos-border text-cosmos-secondary"}`}
        >
          {tag.text}
        </span>
      ))}
    </span>
  );
}
