/**
 * 지원사업 5단계 「회사 적합 근거」가 0건일 때 **왜 0건인지** 가른다 (27차 SUP-01 · ISSUE-164).
 *
 * 고정 모드에서는 회사 근거 검색(임베딩)을 부르지 않아 거의 모든 사업이 0건인데, 화면은 「자료를
 * 등록·승인하라」고 크게 안내했다 — 승인 자료가 42문단 있는 회사에도. 백엔드 사유 문장
 * (`evidence_summary.note` · evidence_service.match_requirements)으로 가른다:
 *   - 「…꺼져 있습니다…」          검색을 하지 않았다(시연 고정 모드)   → 등록 단추 숨김
 *   - 「AI 검색 설정이 없어…」     검색을 하지 않았다(검색 설정 없음)   → 등록 단추 숨김
 *   - 「…연결에 실패했습니다…」     검색이 실패했다                      → 등록 단추 숨김
 *   - 그 밖(자료 없음 · 등록부 읽기 실패 · 사유 없음)                    → 예전 안내 그대로
 * 세 경우 모두 승인 자료가 있는 회사다(백엔드는 자료가 없으면 검색 전에 「자료 없음」 사유로 돌아간다).
 */

export interface EvidenceEmptyState {
  title: string;
  body: string;
  /** 「회사자료 등록·승인하러 가기」를 보일까 — 자료가 있는데 검색을 안 한 것이면 숨긴다 */
  showRegister: boolean;
  /** 백엔드 사유 한 줄을 따로 보일까 — 제목이 이미 같은 말을 하면 숨긴다 */
  showNote: boolean;
  /** 머리 배지 글 — 「AI 검색 꺼 둠」은 실패가 아니다(45차 H5 · 「근거 검색 실패」로 보였다) */
  badge: string;
}

/** 실적 원장 후보(규칙으로 맞춘 미채택 · 유사도 · 쪽이 없다) — 45차 H5. */
export function isLedgerMatch(match: { evidence_id: string }): boolean {
  return match.evidence_id.startsWith("ledger-");
}

const KEPT = "승인한 자료는 그대로 있습니다";

/** 사업계획서 초안이 실제로 실적을 고르는 방식(plan_draft_service.build_bundle — 원장 외부 사용 「가능」 행을 과제 낱말로 매겨 3개) */
const DRAFT_PICKS =
  "사업계획서 초안은 실적 원장에서 외부 사용이 「가능」인 실적을 3개까지 따로 골라 「수행 실적 후보」 같은 줄로 적습니다 — 초안에서 맞지 않는 줄은 지우거나 고치세요.";

/**
 * 외부 점검 P1-03 — 지원사업 5단계 원장 후보 위 한 줄. 백엔드 사유 글(「쓸 것을 골라 채택하세요」)은 입찰 정리표용이라
 * 채택 단추가 없는 이 화면에는 쓰지 않는다.
 */
export const SUPPORT_LEDGER_LINE = `회사 근거 연결(AI 검색)은 꺼 두었습니다. 아래 실적은 이 사업과 분야 낱말이 맞아 참고로 보여 드리는 것이고, 이 화면에서는 고르지 않습니다. ${DRAFT_PICKS}`;

/** 46차 H5 — 지금 AI 검색이 꺼져 있나(서버 상태 값) · 값이 없는 옛 응답만 사유 글 낱말로 본다(대시보드와 같은 규칙). */
export function isSearchOff(note: string | null | undefined, aiSearchOff?: boolean | null): boolean {
  return aiSearchOff ?? /꺼 두었습니다/.test(note ?? "");
}

export function evidenceEmptyState(note: string | null | undefined, aiSearchOff?: boolean | null): EvidenceEmptyState {
  const reason = note ?? "";
  if (isSearchOff(note, aiSearchOff)) {
    // 43차 결정 3 — 회사 근거 연결(AI 검색)은 꺼 두었다 · 외부 점검 P1-03: 초안이 실제로 하는 일을 적고, 입찰용 백엔드 사유 글은 숨긴다
    return {
      title: `회사 근거 연결(AI 검색)은 꺼 두었습니다 — ${KEPT}`,
      body: `이 사업과 분야 낱말이 맞는 원장 실적이 지금은 없습니다. ${DRAFT_PICKS}`,
      showRegister: false,
      showNote: false,
      badge: "AI 검색 꺼 둠",
    };
  }
  if (/꺼져 있/.test(reason)) {
    return {
      title: `AI 검색이 꺼져 있어 회사 근거 검색을 하지 않았습니다 — ${KEPT}`,
      body: "바깥 AI 를 부르지 않도록 검색을 꺼 두었습니다. 검색을 켠 서버에서 다시 열면 고른 근거 문장이 원문과 함께 여기에 붙습니다. 근거가 없으면 실적을 적지 않습니다.",
      showRegister: false,
      showNote: false,
      badge: "근거 검색 안 함",
    };
  }
  if (/설정이 없어/.test(reason)) {
    return {
      title: `AI 검색 설정이 없어 회사 근거 검색을 하지 않았습니다 — ${KEPT}`,
      body: "이 서버에는 회사 근거 검색(AI 의미 매칭) 설정이 없습니다. 설정이 있는 서버에서 다시 열면 고른 근거 문장이 원문과 함께 여기에 붙습니다. 근거가 없으면 실적을 적지 않습니다.",
      showRegister: false,
      showNote: false,
      badge: "근거 검색 안 함",
    };
  }
  if (/연결에 실패/.test(reason)) {
    return {
      title: `회사 근거 검색이 실패했습니다 — ${KEPT}`,
      body: "잠시 뒤 「화면 다시 읽기」로 다시 분석하세요. 근거 없이 실적을 지어내지 않습니다.",
      showRegister: false,
      showNote: true,
      badge: "근거 검색 실패",
    };
  }
  return {
    title: "연결된 승인 근거가 없습니다",
    body:
      "이 회사의 승인·색인된 자료에서 신청 조건과 연결되는 문단을 찾지 못했습니다. 회사소개서·수행실적·인증자료를 등록하고 " +
      "담당자가 확인한 문단을 승인하면 여기에 원문과 함께 표시됩니다. 근거 없이 실적을 지어내지 않습니다.",
    showRegister: true,
    // 「…회사자료가 없습니다 …(회사 코드 · 옛 화면 이름)」은 본문이 같은 말을 한다 — 등록부 읽기 실패 같은 다른 사유만 따로 적는다.
    showNote: !/회사자료가 없습니다/.test(reason),
    badge: "연결된 근거 없음",
  };
}
