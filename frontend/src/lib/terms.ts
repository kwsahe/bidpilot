/**
 * 화면 공통 사전 — **같은 것을 한 이름으로** (27차 §3-E-1 「말 한 벌」).
 *
 * ## 왜 이 파일이 있나
 *
 * 한 공고를 대시보드 · 사업기회 · 레이더 · 요구사항 정리표 · 지원사업 화면에서 보면 같은 것을
 * 다섯 이름으로 불렀다 — 참가 판정(「확인 필요」 / 「사람 확인 필요」), 미정 상태(「결정 미정」 ·
 * 「미결정」 · 「결정 대기」), 회사 쪽 근거(「수행근거」 · 「증빙」), 합성 이름표 여덟 가지,
 * /rfp 화면 이름 다섯(「RFP 분석」 · 「공고 분석」 · 「요구사항 매트릭스」…). 담당자는 이름이
 * 다르면 다른 것으로 읽는다(2026-10-13 통일 점검 UNI-05 · 15 · 16 · 17 · LNK-05).
 *
 * ## 규칙
 *
 * - 화면 글자는 여기 낱말을 쓴다. 옛 말은 `scripts/check_screen_vocabulary.mjs` 의 `OLD_TERMS` 가 막는다.
 * - 저장 값(enum)은 바꾸지 않는다 — 바뀌는 것은 표기뿐이다.
 * - 이미 있던 사전(`lib/scoreNames`)은 그대로 두고 여기서 다시 내보낸다. 사본을 만들면 갈린다.
 * - 숫자 표기 함수는 제자리에 있다 — 금액 `formatBudgetCompact`(lib/cosmos/format, 「6,000만원」 꼴 ·
 *   없으면 `NO_BUDGET`) · 검토 우선순위 `reviewPriorityText`(아래 다시 내보냄 · 단위 없음 · 없으면 `UNSCORED`) ·
 *   「7일 안 마감」 `withinDaysText`(lib/deadline). 「마감 N」은 이미 마감된 것에만 쓴다.
 */

import { DECISION_LABELS, ELIGIBILITY_GATE_LABELS, UNSCORED_WORD } from "@/lib/scoreNames";
import type { CollectState } from "@/types/opportunity";

export { reviewPriorityText } from "@/lib/scoreNames";

/** 단계 이름 8 — **레일 이름이 기준**이다(graph `WORKFLOW_STEPS` 가 여기서 읽는다). 지도 짧은 이름은 이 낱말에서만 고른다. */
export const STEP_NAMES = {
  1: "공고 탐색",
  2: "우리 회사 적합도",
  3: "참가 가능 여부",
  4: "요구사항 정리",
  5: "회사 수행근거 연결",
  6: "제안서 초안",
  7: "제출 전 누락 점검",
  8: "담당자 최종 결정",
} as const;

/** 참가 판정 셋 — 「가능 · 확인 필요 · 불가」. 제목(「입찰 참가 가능 여부」)이 이미 「참가」를 말한다. */
export const ELIGIBILITY_TERMS = ELIGIBILITY_GATE_LABELS;

/** 회사 쪽 근거. 「증빙」은 증빙 서류(계약 증빙 · 사업장 증빙)에만 쓴다. */
export const COMPANY_EVIDENCE = "회사 근거";
/** 회사 문서(올리고 승인하는 것) — 메뉴 이름과 같다. */
export const COMPANY_DOCUMENTS = "회사자료";
/** 요구사항에 붙은 회사 근거가 없을 때. */
export const NO_EVIDENCE = "근거 없음";
/** 「근거 없음」 · 「회사 쪽 확인」 자리에서 회사자료 화면으로 가는 링크 — 입찰 · 지원사업이 같은 말 (27차 LNK-03). 끝 「→」는 쓰는 곳이 붙인다(쉬운 보기는 「(전체 보기) →」 · `FULL_VIEW_ONLY_TAG`). */
export const REGISTER_COMPANY_DOCUMENTS = "회사자료 등록·승인하러 가기";

/** 아직 참여 결정을 내리지 않은 상태 (`decision.status = UNREVIEWED`). */
export const UNDECIDED = DECISION_LABELS.UNREVIEWED;
/** 저장된 결정을 읽지 못함 — 「미결정」과 다르다(저장된 결정이 있을 수 있다 · 2.0.6). 8단계 · 출처 표지 · 결정 칸이 같은 말. */
export const DECISION_READ_FAILED = "결정 확인 못 함 — 새로고침";
/** 결정한 뒤의 배지 문장 — 결정마다 따로(「참여 안 함하기로 함」 비문 · 31차 R30-27). */
export const DECIDED_SENTENCES: Record<string, string> = {
  GO: "참여하기로 함",
  HOLD: "보류함",
  NO_GO: "참여 안 하기로 함",
};

/** 합성 이름표는 둘뿐 — 공고 · 시나리오 쪽 */
export const SYNTHETIC_NOTICE = "가상 예시 공고";
/** 합성 이름표는 둘뿐 — 회사 쪽 */
export const SYNTHETIC_COMPANY = "가상 예시 회사자료";

/** 저장해 둔 응답으로 그린다는 표시 — 「캐시」는 개발 말(30차 §3-F 사전 변경 채택) */
export const CACHE_TERM = "저장본";
/** 바깥을 부르지 않는 설정(평소 기본값) — 「시연 고정」(30차 §3-F 사전 변경 채택) */
export const FROZEN_TERM = "새 공고 받기 꺼짐";

/** 자동 받기 상태를 아직 모를 때(불러오는 중 · 통합 목록 실패) — 「꺼짐 · 관리자에게 고정 해제」를 그리지 않는다(40차 FRONT-05 · SCREEN-01). */
export const COLLECT_UNKNOWN_TERM = "확인 중"; // 41차 FRONT-R40-06 — 앞에 「자료 상태」가 붙는 자리뿐이다

/** 레이더 머리 같은 좁은 배지의 짧은 글(40차 D30) — 오늘 받음은 아래 함수가 꼬리를 붙인다. */
const COLLECT_SHORT: Record<"missed" | "running" | "off" | "waiting", string> = {
  missed: "오늘 목록 아직",
  running: "받는 중",
  off: "자동 받기 꺼 둠",
  // 43차 M27 — 회사 서버가 오늘 받을 시각(07:30 · 09:30 · 11:30) 전. 경고가 아니다(새벽마다 헛경고가 떴다).
  waiting: "받을 예정",
};

/**
 * 고정 모드의 자동 받기 한 줄 — **이 함수 하나**가 고른다(39차 §3-F-2 · 대시보드 맨 위 줄 · 사업기회 · 레이더 자료 상태 · 레이더 머리 배지 ·
 * 읽어 주는 이름 · 두 화면 팝오버). 글은 서버 `auto_collect.collect_state` 가 정한다(40차 D30 「켤 때 받기」) — 「매일 처음 켤 때 자동으로 받음 ·
 * 오늘 HH:MM」 · 「오늘 목록 받는 중」 · 「오늘 목록을 아직 받지 않았습니다 …」 · 「자동 받기 꺼 둠 …」. 자동 받기 기록도 예약 작업도 없으면(키트)
 * 「새 공고 받기 꺼짐」 그대로 · 상태를 아직 모르면 「확인 중」(앞에 「자료 상태」가 붙는 자리).
 * `fetchedAt` 이 같은 분이면 오늘 받은 날은 「자동으로 받음」 + 꼬리만(바로 앞 「목록 받은 때」와 같은 시각 · 38차 §5 시인성).
 * `short` — 좁은 배지용(레이더 머리). 일부 실패 · 기업마당 못 받음은 줄인 글에도 「 · 일부 실패」로 남긴다(COLLECT-01).
 */
export function collectTerm(state?: CollectState | null, fetchedAt?: string | null, short = false): string {
  if (!state) return COLLECT_UNKNOWN_TERM;
  if (state.kind === "none" || !state.text) return FROZEN_TERM;
  if (state.kind !== "ok") return short ? COLLECT_SHORT[state.kind] : state.text;
  // 44차 마지막 검토 — AI 보조 쉼 꼬리 하나만 있으면 받기는 다 성공했다(「일부 실패」 아님)
  const failed = !!state.suffix && /일부 실패|기업마당/.test(state.suffix);
  if (short) return `자동으로 받음${state.warn ? " · 기업마당 못 받음" : failed ? " · 일부 실패" : ""}`;
  if (fetchedAt && state.last_success && Math.abs(Date.parse(fetchedAt) - Date.parse(state.last_success)) < 60_000) {
    return `자동으로 받음${state.suffix ?? ""}`;
  }
  return state.text;
}

/** 경고 색(⏸ 호박)으로 적을까 — 자동 받기 기록이 없거나(키트) 오늘 목록을 아직 안 받았을 때만. 모름 · 받는 중 · 꺼 둠 · 오늘 받음은 보통색. */
export function collectWarns(state?: CollectState | null): boolean {
  return Boolean(state) && (state!.kind === "none" || state!.kind === "missed" || Boolean(state!.warn));
}
/** 저장 목록을 바깥에서 새로 받아 바꾸는 동작에만 쓴다 (사업기회 「나라장터 재수집」). */
export const RECOLLECT_TERM = "새로 받기";
/** 저장 목록은 그대로 두고 캐시를 건너뛰어 출처를 다시 부르는 동작(레이더). */
export const RELOAD_TERM = "다시 불러오기";
/**
 * 서버에 있는 목록을 화면만 다시 읽는 동작(바깥을 부르지 않는다 · 사업기회 데이터 상태) — 「다시 불러오기」(출처 호출)와
 * 한 이름을 쓰면 다른 두 일이 같은 일처럼 보였다(27차 §3-E 검증 G1-R4).
 */
export const VIEW_RELOAD_TERM = "화면 다시 읽기";

/** 메뉴 이름 = 화면 제목(h1). */
export const SCREEN_NAMES = {
  dashboard: "대시보드",
  // 2.1.0 — 공고 하나를 8단계로 보는 화면(3D · 예전 대시보드). 대시보드는 사업기회 통계로 바뀌었다(대표 결정 2026-10-28).
  analysis: "입찰 분석",
  radar: "레이더",
  opportunities: "사업기회",
  // 메뉴에는 없다 — 사업기회 안의 탭 이름(28차 §3-C)
  rfp: "요구사항 정리표",
  // 메뉴에는 없다 — 사업기회의 「사업계획서 작성 →」 · 「제안서 작성 →」 단추로 들어간다(37차 §3-E · 담당자 결정 2026-10-14)
  plan: "사업계획서 작성",
  company: COMPANY_DOCUMENTS,
  // 32차 §3-A — 가이드 화면(메뉴 다섯째 · 37차에 사업계획서 작성이 빠져). 「처음 안내」(「?」 창) · 「안내 ▾」와 다른 이름.
  guide: "실전 가이드",
} as const;
/** 사업기회 행 · 자세히의 단추 (37차 §3-E-2) — 지원사업은 사업계획서, 입찰은 제안서(같은 사업계획서 작성 페이지의 입찰 탭). */
export const WRITE_PLAN_BUTTON = "사업계획서 작성 →";
export const WRITE_PROPOSAL_BUTTON = "제안서 작성 →";
/** 사업계획서 작성 페이지 위 길 표시 · 돌아가기 (37차 §3-E-3). */
export const BACK_TO_OPPORTUNITIES = "← 사업기회로";
/** 좁은 화면 메뉴 이름(640px 미만). */
export const GUIDE_SHORT_NAME = "가이드";

/**
 * 쉬운 보기에서 쉬운 보기가 없는 화면(회사자료 · 레이더)으로 가는 링크 꼬리표 — 머리의 보기 전환 「전체 보기」와 같은 말.
 * 「(전체 화면)」은 브라우저 전체화면(F11)으로 읽혔다 (CMN-17).
 */
export const FULL_VIEW_ONLY_TAG = "(전체 보기)";

/** 요구사항 정리표(사업기회 안의 탭)로 가는 링크 문구 — 같은 탭 이동이라 「→」 (새 탭만 「↗」 · 28차 §3-C). */
export const OPEN_REQUIREMENT_SHEET = `${SCREEN_NAMES.rfp} 열기 →`;

/** 「등록마감」 도움말 — 법정 용어는 그대로 두고 처음 한 번 풀이한다(30차 §3-F #25). */
export const REGISTRATION_HELP = "입찰참가자격 등록 마감 — 이때까지 나라장터에 자격 등록을 마쳐야 입찰할 수 있습니다(입찰마감보다 빠를 수 있음)";

/**
 * 사업계획서 빈칸 — 단위가 다른 두 수를 같은 말로 부르지 않는다(31차 R30-28). 제출용 파일에 남는 「(담당자 입력)」 표시 수와
 * 담당자가 채울 항목 수(일반현황 · 인력 · 금액 등)는 다르다(79 · 49).
 */
export const SUBMIT_BLANK_MARKS = "제출용 파일 속 빈칸 표시";
export const OWNER_FILL_ITEMS = "담당자가 채울 항목";
/** 두 숫자의 풀이 한 줄(44차 S2 · N10) — 셈 대상이 달라 같은 화면에서 숫자가 달랐다(46 · 60). */
export const BLANK_COUNT_NOTE =
  "「담당자가 채울 항목」은 채울 항목 수, 「제출용 파일 속 빈칸 표시」는 내려받은 파일에 남은 (담당자 입력) 자리 수입니다 — 한 항목이 표지 · 표 여러 곳에 나오면 곳마다 셉니다.";
/** AI 가 공고 밖에서 덧붙인 문장 — 「AI 제안」 · 「AI 가 덧붙인 문장」 두 이름을 하나로. */
export const AI_ADDED_SENTENCES = "AI가 덧붙인 문장";
/** 그 문장의 짧은 이름표(배지 · 표식) — 화면과 내보낸 파일(`proposal_export` · `plan_export_service` 「AI 덧붙임」)이 같은 말(31차 마지막 검토). */
export const AI_ADDED_LABEL = "AI 덧붙임";

/** 예산 값이 없을 때 (0원으로 적지 않는다). */
export const NO_BUDGET = "예산 미공개";
/** 검토 우선순위가 없을 때 — 0점으로 단정하지 않는다 (CLAUDE.md §12). */
export const UNSCORED = UNSCORED_WORD;

/* -------------------------------------------------------------------------------------------------
 * 처음 하는 사람 안내 (31차 §3-B · 가이드 원본 `frontend/content/first_time_guide.md` · 제품 반영 안 우선 1 · 2 · 3-2)
 *
 * 규칙: 화면 글은 「무엇을 · 어느 사이트에서」까지. **숫자 · 기간 · 비용은 문서에만** — 화면 예외 셋:
 * 등록마감은 보통 입찰마감 전날 18:00 · 중소기업 확인서는 매년 3월 31일 만료 · 창업기업 확인서 발급에 시간이 걸림(공고마다 다름).
 * 일반 절차 안내에는 늘 `GENERAL_GUIDE_NOTE` 를 붙여 공고에서 찾은 조건과 섞지 않는다(CLAUDE.md §11).
 * 가이드 8장 「확인 필요」 값(제출 순서 · 메뉴 위치 · 인증서 종류 · 비용 등)은 여기 쓰지 않는다.
 * ------------------------------------------------------------------------------------------------- */

/** 일반 절차 안내 꼬리표 — 공고문이 늘 우선한다. */
export const GENERAL_GUIDE_NOTE = "일반 절차 안내 · 공고문이 우선";
/** 실전 가이드 화면(32차 §3-A-4) — 머리 · 준비 상태 칸. 가이드 화면만 숫자 · 기간을 출처 · 기준일과 함께 둔다(담당자 결정 10-07). */
export const GUIDE_LEGAL_NOTE = "법률 자문이 아닙니다 · 공고문과 기관 안내가 우선합니다";
export const GUIDE_READINESS_TITLE = "우리 회사 준비 상태(읽기만)";
export const GUIDE_NO_RECORD_NOTE =
  "체크리스트의 나머지 항목(나라장터 개인회원 가입 · K-Startup 대표 가입 · 사업자등록과 등기 일치 · 체납 · 연체 · 자부담)은 기록 칸이 없습니다 — 직접 확인하세요.";

/**
 * 첫 진입 환영 창(2.0.5 · 대표 요청 2026-10-27) — 「BidPilot AI로 무엇을 할 수 있나」.
 * 위 규칙 그대로 숫자 · 기간 · 비용과 성과 주장은 넣지 않는다. `where` 는 메뉴 이름(SCREEN_NAMES)을 그대로 쓴다.
 */
export const WELCOME_TITLE = "BidPilot AI에 오신 것을 환영합니다";
export const WELCOME_LEAD = "공공 입찰 · 지원사업 공고를 찾는 일부터 제출 전 점검까지, 근거를 보여 주며 돕는 수주 도우미입니다.";
export const WELCOME_FEATURES_TITLE = "BidPilot AI로 할 수 있는 것";
export const WELCOME_FEATURES: ReadonlyArray<{ title: string; detail: string; where: string }> = [
  {
    title: "공고 찾기",
    detail: "나라장터 입찰과 기업마당 지원사업을 한곳에 모아, 우리 회사 기준으로 먼저 볼 순서대로 보여 줍니다.",
    where: `${SCREEN_NAMES.dashboard} · ${SCREEN_NAMES.opportunities} · ${SCREEN_NAMES.radar}`,
  },
  {
    title: "참가 가능 여부 확인",
    detail: "지역 · 업종 · 마감처럼 참가를 막는 조건을 정해 둔 규칙으로 보고, 판단마다 공고 원문 근거를 붙입니다.",
    where: SCREEN_NAMES.analysis,
  },
  {
    title: "요구사항 정리",
    detail: "제안요청서에서 해야 할 일과 조건을 항목별로 뽑아 쪽수와 원문을 함께 보여 줍니다.",
    where: `${SCREEN_NAMES.opportunities} › ${SCREEN_NAMES.rfp}`,
  },
  {
    title: "제안서 · 사업계획서 초안",
    detail: "회사자료에서 고른 근거로 핵심 부분 초안을 씁니다. 근거가 없는 내용은 「확인 필요」로 남깁니다.",
    where: `공고마다 「${WRITE_PROPOSAL_BUTTON}」 · 「${WRITE_PLAN_BUTTON}」`,
  },
  {
    title: "제출 전 점검",
    detail: "빠진 요구사항, 맞지 않는 숫자, 근거 없는 주장을 제안요청서 원문과 맞춰 찾아 줍니다.",
    where: SCREEN_NAMES.analysis,
  },
  {
    title: "회사자료 한 번 등록",
    detail: "실적 · 인력 · 인증을 한 번 등록해 두면 모든 공고에서 근거로 다시 씁니다.",
    where: SCREEN_NAMES.company,
  },
];
export const WELCOME_CLOSING = "AI는 돕기만 합니다. 근거를 확인하고 참가 결정과 제출은 담당자가 직접 합니다.";
export const WELCOME_START = "시작하기";
export const WELCOME_FIRST_TIME = "입찰 · 지원사업이 처음이라면";
export const WELCOME_HELP_NOTE = "시작 순서와 화면 사용법은 상단 「?」 버튼에서 언제든 다시 볼 수 있습니다.";

/** 「?」 처음 안내 창 — 한 번만 하는 준비. */
export const FIRST_TIME_TITLE = "입찰 · 지원사업이 처음이라면 — 먼저 한 번 준비할 것";
export const FIRST_TIME_G2B_TITLE = "나라장터 입찰";
export const FIRST_TIME_G2B: readonly string[] = [
  "사업자등록증과 법인등기의 상호 · 대표자 · 주소가 서로 같은지 확인",
  "회사 이름의 인증서(사업자 범용 공동인증서) 준비 — 대표 개인 인증서로는 회사 이름으로 서명할 수 없습니다",
  "중소기업(소상공인) 확인서 발급(sminfo.mss.go.kr) — 매년 3월 31일 만료",
  "나라장터(g2b.go.kr) 개인회원 가입 → 입찰참가자격 등록(업종 포함) → 승인. 등록한 업종의 공고에만 참가할 수 있습니다",
  "제안서로 평가받는 입찰(협상에 의한 계약)을 노린다면 신용평가등급확인서를 공고가 나기 전에 받아 두기",
];
export const FIRST_TIME_SUPPORT_TITLE = "지원사업";
export const FIRST_TIME_SUPPORT: readonly string[] = [
  "접수처(K-Startup · 기업마당 · 소관기관)에 대표 본인 명의로 가입",
  "회사 이름의 인증서 준비 — 대표 개인 인증서로는 기업인증이 안 됩니다",
  "창업기업이라면 창업기업 확인서(cert.k-startup.go.kr) — 발급에 시간이 걸리니(공고마다 다름) 공고 전에 받아 두기",
  "국세 · 지방세 체납과 금융 연체가 없는지 확인",
  "회사가 돈을 보태야 하는 사업(자부담)인지 공고에서 확인",
];
// 앱 안에 가이드 화면이 생겼다(32차 §3-A-9) — 문서 이름 대신 그 화면으로 가는 링크(GUIDE_OPEN_LINK)를 옆에 단다.
// 꼬리표를 문장에 그대로 붙인 비문(「…공고문이 우선합니다」)도 풀어 썼다.
export const FIRST_TIME_END =
  "처음 한 번만 하면 됩니다. 자세한 순서 · 기간 · 비용은 실전 가이드에서 보세요. 일반적인 절차 안내이고, 공고문이 늘 우선합니다.";
/** 판정 카드 — 공고문을 아직 안 읽은 실공고(조항 0 · QUAL-DOC 확인 필요). 「참가자격 조항 없음」은 「조건이 없다」로 읽혔다(32차 §3-B-1). */
export const DOC_UNREAD_GATE_LINE = "공고문을 아직 안 읽어 참가자격 조항을 모릅니다 — 4단계 「공고 분석 시작」";
/** 3단계 등록 줄 — 준비 상태에 「있음」을 적어도 판정이 그대로인 이유(32차 §3-B-6). */
export const READINESS_NOT_USED = "회사자료 준비 상태는 참고용 — 판정에는 중소기업(소상공인) 확인서 줄만 씁니다";
/** 지원사업 쉬운 보기 마무리 「어디서 무엇을」 한 줄(32차 §3-B-5) — 자세한 순서는 가이드 3-7 링크. */
export const SUPPORT_WHERE_LINE = "접수처(K-Startup · 기업마당 · 소관기관)에서 대표 본인이 신청하고, 마지막에 「제출완료」와 접수증을 확인하세요.";
/** /plan 사업계획서 — 쓰기 단추 옆 AI 초안 주의(32차 §3-B-4 · 가이드 4-8 — 숫자 · 제재 기간은 가이드에만). */
export const AI_DRAFT_CAUTION = "AI 초안은 출발점입니다 — 숫자 · 실적은 직접 대조하고, 남의 글과 비슷해지지 않게 우리 회사 말로 다시 쓰세요. 사실과 다른 내용을 내면 제재를 받습니다.";
/** 「제출용」 단추 옆 한 줄 — 받은 파일을 그대로 내는 것이 아니다. */
export const SUBMIT_DRAFT_NOTE = "제출용 = 공고 양식에 옮겨 쓸 초안";
/** 공고 양식을 못 찾아 표준 양식으로 쓴 초안 표시. */
export const STANDARD_FORM_BADGE = "참고용 — 공고 양식이 아닌 표준 양식";
/** 내려받기 아래 「다음 할 일」(일반 절차 · 공고문이 우선). `place` 는 공고의 신청 방법(없으면 일반 말). */
export const PLAN_NEXT_STEPS_TITLE = "다음 할 일";
export function planNextSteps(place: string | null): readonly string[] {
  return [
    "받은 초안을 공고에 붙은 신청 양식 파일에 옮겨 붙입니다",
    `${place ? `접수처(${place})` : "공고의 「신청 방법」에 적힌 접수처"}에서 대표 본인이 신청합니다`,
    "마지막에 「제출완료」 · 접수 완료를 확인하고 접수증을 PDF로 보관합니다",
  ];
}
/** 가이드 화면으로 가는 링크 글 — 「?」 창 · 환영 창. */
export const GUIDE_OPEN_LINK = "실전 가이드 열기 →";
/** 화면 곳곳의 가이드 문맥 링크 글(32차 §3-A-9) — 화면 글은 늘리지 않고 링크만. 주소는 `lib/guide` GUIDE_LINKS. */
export const GUIDE_LINK_TEXT = {
  firstBid: "처음 등록하는 법(실전 가이드) →",
  register: "처음 등록하는 법 →",
  outside: "가격 · 보증 · 계약 자세히(실전 가이드) →",
  consortium: "함께 참가 · 하도급(실전 가이드) →",
  supportSubmit: "신청 순서(실전 가이드) →",
  aiDraft: "AI 초안 쓸 때 지킬 선 →",
  readiness: "어디서 받나 →",
  validity: "유효기간 달력 →",
} as const;

/** 공고 상세 1단계 한 줄 — 처음 입찰하는 사람에게 등록이 먼저라는 것. */
export const FIRST_BID_LINE =
  "처음 입찰한다면: 나라장터 입찰참가자격 등록(업종 포함)이 먼저입니다. 등록마감이 지나면 이 공고에는 쓸 수 없습니다. 준비할 것은 맨 위 「?」에 있습니다.";
/** 일반 절차 안내 꼬리 — 공고 조건 설명 옆에 붙는 안내 문장 끝에 붙인다(31차 마지막 검토 — 공고 조건과 섞였다). */
const GUIDE_TAIL = ` (${GENERAL_GUIDE_NOTE})`;
/** 가상 예시 공고에서 「이 공고」 안내 앞에 붙이는 말(32차 R31-14) — 등록마감 · 마감 할 일은 실제 공고 이야기다. */
export const IF_REAL_NOTICE = "실제 공고라면 —";
/** 쉬운 보기 첫 화면 한 줄(32차 §3-B-3) — 「지금 할 일」에 1단계가 없어도 처음 입찰하는 사람이 먼저 보게. 자세한 것은 가이드 링크. */
export const FIRST_BID_SHORT = "처음 입찰이라면 나라장터 입찰참가자격 등록(업종 포함)이 먼저입니다.";
/** 가상 예시 공고에서 실제 공고로 가는 링크 글. */
export const PICK_REAL_NOTICE = "사업기회에서 실제 공고 고르기 →";
/** 지원사업 「신청자격」 설명 끝 한 문장. */
export const FIRST_SUPPORT_LINE =
  `처음 신청한다면 공고의 「신청 방법」에 적힌 접수처에 대표 본인 명의로 가입하고 기업인증을 먼저 해 두세요.${GUIDE_TAIL}`;

/** 공고 상세 8단계 접는 칸 — 실제 제출 · 보증 · 계약은 BidPilot 밖에서 사람이 한다. */
export const OUTSIDE_TITLE = "BidPilot 밖에서 할 일";
export const OUTSIDE_G2B: readonly string[] = [
  "나라장터(g2b.go.kr)에서 공고가 정한 서류(제안서 등)와 가격입찰서를 냅니다. 내는 순서와 방법은 공고문을 따르세요 — 빠지면 무효가 될 수 있습니다.",
  "낸 뒤 나라장터 제출내역에서 모두 들어갔는지 확인하고 화면을 캡처해 둡니다. 낸 입찰서는 고치거나 취소할 수 없습니다.",
  "마감 직전에는 인증 실패로 놓치기 쉽습니다. 여유 있게 내세요.",
  "입찰보증금을 요구하는 공고라면 보증서 · 현금(면제면 지급각서)을 기한 안에 냅니다.",
  "발표평가가 있으면 공고에 적힌 방식대로 준비합니다.",
  "뽑히면 기술협상 → 계약 → 계약보증금 → 착수 순서입니다. 일이 끝나면 실적증명서를 받아 회사자료 실적 목록에 남깁니다.",
];
export const OUTSIDE_NOTE = `${GENERAL_GUIDE_NOTE} — 공고문과 발주기관 안내가 우선합니다.`;
/** 다음 행동(완료) — 실공고만. 가상 예시 공고는 「나라장터」가 어색해 옛 문장을 쓴다. */
export const SUBMIT_OUTSIDE_LINE =
  "시스템은 자동 제출하지 않습니다. 나라장터에서 담당자가 공고가 정한 서류와 가격입찰서를 직접 냅니다(8단계 「BidPilot 밖에서 할 일」).";

/** 지원사업 마무리 문장 — 세 화면 같은 글(쉬운 보기는 앞 두 문장만). */
export const SUPPORT_FINISH_LINES: readonly string[] = [
  "최종 신청은 담당자가 합니다.",
  "시스템이 신청을 대신 제출하지 않습니다.",
  "접수처에서 대표 본인이 신청하고, 마지막에 접수가 끝났는지(K-Startup은 「제출완료」) 확인한 뒤 접수증을 PDF로 보관하세요.",
  `선정되면 협약 확약서 · 협약 · 전용 계좌가 이어지고, 사업비는 공고와 협약서 규정대로만 씁니다.${GUIDE_TAIL}`,
];

/**
 * 마감 며칠 전 할 일 — 나라장터 입찰(공고 상세 1단계 한 줄). 단계 경계는 `lib/deadline` 의 `URGENCY_DAYS` 하나.
 * 「여유 있음」 · 「마감일 없음(14일 넘게)」은 같은 문장이다. 마감이 지났으면 줄을 내지 않는다(위험 표시가 대신함).
 */
export const BID_DEADLINE_STEPS = {
  // 신용평가등급확인서는 뺐다 — 공고일 전에 받은 것만 인정되어 이 공고에는 이미 늦다(32차 R31-09 · 가이드 1-10 「다음 공고를 위해」).
  early: "업종 등록 · 중소기업 확인서가 없으면 지금 시작하세요. 발급에 시간이 걸립니다.",
  soon: "등록마감을 확인하세요. 보통 입찰마감 전날 18:00이고, 조달청은 평일 근무시간에만 승인합니다. 보증서가 필요하면 발급일을 거꾸로 세어 두세요.",
  urgent: "등록마감이 주말이면 그 전 평일 근무시간 안에 승인까지 끝나야 합니다. 공고가 정한 서류와 가격입찰서를 공고문대로 내고, 마감 직전은 피하세요.",
} as const;
/** 등록마감이 입찰마감보다 먼저일 때 앞에 붙는 말. */
export const BID_DEADLINE_REGISTRATION_FIRST = "등록마감이 입찰마감보다 먼저 닫힙니다 — 등록마감 기준으로 셉니다.";
/** 지원사업 「신청기간」 설명 끝 고정 문장(날짜로 바뀌지 않는다). */
export const SUPPORT_DEADLINE_LINE =
  "마감이 다가오면: 창업기업 확인서가 필요한 공고는 미리 신청(발급에 시간이 걸림 · 공고마다 다름) → 접수처 가입 · 기업인증 → 마감 직전을 피해 신청하고 접수 완료 확인. 상시 · 예산 소진 공고는 신청 방법 원문을 먼저 보세요." +
  GUIDE_TAIL;

/** 회사자료 「준비 상태」 — 나라장터 등록 · 인증서 · 확인서. 저장은 기존 `credentials` 목록. */
export const READINESS_TITLE = "준비 상태 (나라장터 등록 · 인증서 · 확인서)";
export const READINESS_HELP =
  "모르면 「모름」으로 두세요. 시스템은 이 칸을 대신 채우지 않습니다. 참가 가능 여부 판정에는 중소기업(소상공인) 확인서 줄(있음 · 구분 · 유효기간)만 씁니다 — 공고가 중소기업 · 소기업 · 소상공인을 요구할 때 이 줄로 가립니다. 유효기간 끝나는 날을 적으면 「이번 주 할 일」이 곧 만료 · 만료됨을 알립니다. 중소기업 확인서는 매년 3월 31일에 만료됩니다.";
/** 중소기업(소상공인) 확인서 줄의 「확인서 구분」(10-10) — 확인서에 적힌 그대로. */
export const SME_GRADE_LABEL = "확인서 구분";
export const SME_GRADES = ["중기업", "소기업", "소상공인"] as const;
export const SME_GRADE_HELP = "확인서에 적힌 그대로 고르세요. 「중기업」이면 소기업 · 소상공인만 받는 공고에는 참가할 수 없습니다.";
export const READINESS_ROWS: readonly string[] = [
  "나라장터 입찰참가자격 등록",
  "사업자 범용 공동인증서",
  "중소기업(소상공인) 확인서",
  "창업기업 확인서",
  "소프트웨어사업자 신고(1468)",
  "직접생산확인증명서",
  "신용평가등급확인서",
];
export const READINESS_HELD_LABELS = { yes: "있음", no: "없음", unknown: "모름" } as const;
/** 30일 안 만료 · 지난 날짜 — 「이번 주 할 일」 안내 줄. */
export const EXPIRING_SOON_HEAD = "곧 만료";
export const EXPIRED_HEAD = "만료됨";
// 모든 서류에 「그 뒤 공고에 낼 수 없다」고 했다 — 그 서류가 필요한 공고에만 해당한다(32차 R31-13)
export const EXPIRING_SOON_TAIL = "갱신하지 않으면 그 뒤 마감하는 공고 가운데 이 서류가 필요한 공고에 낼 수 없습니다";
export const EXPIRED_TAIL = "갱신하기 전에는 이 서류가 필요한 공고에 낼 수 없습니다";

// --- 37차 회사별 우선순위 계산 방식 · 실무 우선순위 (담당자 결정 2026-10-14 · 기획서 §4-1) ---------------------
/** 회사자료 칸 이름 — 「모름」은 없다(비우면 점수순). */
export const RANKING_METHOD_FIELD = "우선순위 계산 방식";
/** 고르기 둘과 한 줄 풀이 (prompt_27 §3-A-2). */
export const RANKING_METHODS = {
  score: { label: "점수순", help: "점수순 — 회사 기준 검토 우선순위 높은 순" },
  practical: { label: "실무 우선순위", help: "실무 우선순위 — 본업 안에서 주제 맞음 먼저(주제 확인 · AI 꼬리표는 뒤) · 최근 공고 · 준비기간 긴 것 먼저, 마감 임박은 아래 긴급 칸으로" },
} as const;
/** 사업기회 목록 머리의 「정렬: 실무 우선순위(회사 설정)」 — 회사 기본 정렬일 때만 「(회사 설정)」을 붙인다. */
export function sortHeadLine(label: string, companyDefault: boolean): string {
  return `정렬: ${label}${companyDefault ? "(회사 설정)" : ""}`;
}
/** 유형은 근사치다 — 사업담당자 운영매뉴얼 v1.2 를 받기 전(prompt_27 §0). */
export const TYPE_APPROX = "유형(근사)";
/** D8 꼬리표 — 점수는 그대로 두고 붙인다. */
export const PARTNER_SCALE_TAG = "단독으로는 큼 · 파트너형";
/** 실무 문서 §2.5 「3일 이하: 원칙적으로 후순위」(D3). */
export const LATE_TAG = "원칙적으로 후순위";
/** 「새로 올라온 것(3일)」과 실무순 「신규(7일)」은 다른 이름이다(D10). */
export const FRESH_TAG = "신규(7일)";
