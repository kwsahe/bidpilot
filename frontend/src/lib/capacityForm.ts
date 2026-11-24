/**
 * 입찰 자격 카드가 저장할 값 만들기(33차 §3-B-3 · 34차 R33-S4 · S5) — 화면 저장이 회사자료를 몰래 바꾸지 않게.
 *
 * - 공동수급 파트너: 「모름 · 있음 · 없음」 세 갈래. 「모름」은 null 이다 — 메모만 적고 고르지 않았을 때
 *   「없음」(`{available: false}`)이 되면 공동수급 필수 조항이 「불가」로 간다(33차에 고친 것의 남은 길).
 * - 완료한 선행 사업 · 데이터 상품 · 공급기업 등록: 줄바꿈으로만 나눈다. 한 줄 안의 쉼표는 그 줄의 글이다.
 */

export type JointPartner = { available: boolean; note: string | null };
export type PartnerChoice = "" | "yes" | "no";

export function partnerChoiceOf(saved: JointPartner | null | undefined): PartnerChoice {
  if (saved == null) return "";
  return saved.available ? "yes" : "no";
}

export function jointPartnerToSave(choice: PartnerChoice, note: string): JointPartner | null {
  if (choice === "") return null;
  return { available: choice === "yes", note: note.trim() || null };
}

export function textLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}
