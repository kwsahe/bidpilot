import { createContext } from "react";

/**
 * 「요구사항 정리표 열기」 — 선택 저장 + 사업기회의 「요구사항 정리표」 탭 + 맨 위로 (28차 §3-C).
 * 사업기회 페이지가 준다. 카드 · 쉬운 보기 행 · 「검토 중」 탭(29차 R28-02)이 같은 함수를 쓴다 —
 * 같은 페이지 주소로 가는 링크는 탭 상태가 `review` 로 남아 눌러도 반응이 없었다.
 * 페이지 밖(제공자 없음)이면 null — 부르는 쪽이 링크로 대신한다.
 */
export const OpenSheetContext = createContext<((noticeId: string) => void) | null>(null);

/**
 * 사업기회의 지금 조건(「?src=…&sort=…」 · 없으면 빈 문자열) — 행의 「사업계획서 작성 →」가 `from` 으로 실어
 * 사업계획서 작성 페이지의 「← 사업기회로」가 같은 탭 · 정렬 · 검색으로 돌아온다(37차 §3-E-3).
 */
export const PlanBackContext = createContext<string>("");
