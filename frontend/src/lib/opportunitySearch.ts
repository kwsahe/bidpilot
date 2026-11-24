/**
 * 사업기회 목록의 검색 판정 (0919 §4-B-6).
 *
 * 이 파일이 따로 있는 이유는 둘이다.
 *
 * 1. **테스트할 수 있어야 한다.** 목록 화면은 "use client" 컴포넌트라 `node --test` 가
 *    그대로 부를 수 없다. 판정 규칙만 떼어 두면 규칙을 고칠 때마다 확인할 수 있다.
 * 2. 검색은 **캐시 안에서만** 한다. 여기에는 네트워크가 없다 — 이미 받아 둔 목록을 거를 뿐이다.
 */

/** 검색이 훑을 글자를 한 줄로 잇는다. 빈 값은 버리고 공백은 하나로 줄인다. */
export function buildHaystack(parts: Array<string | null | undefined>): string {
  return parts
    .filter((part): part is string => typeof part === "string" && part.trim().length > 0)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/**
 * 검색어가 이 글자 뭉치에 맞는가.
 *
 * **낱말을 따로 본다(모두 포함).** 예전에는 입력한 글자를 통째로 찾았는데, 검색 범위를
 * 넓히고 나면 그 방식이 오히려 덜 찾는다 — 「AI 교육」의 「AI」는 과업 키워드 칩에 있고
 * 「교육」은 제목에 있어서, 둘을 이어 붙인 문자열은 어디에도 없기 때문이다.
 *
 * 순서도 보지 않는다. 「교육 AI」로도 같은 것을 찾는다 — 담당자가 외운 순서와 문서에 적힌
 * 순서가 같을 이유가 없다.
 */
export function matchesQuery(haystack: string, query: string): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  // 띄어쓰기를 뺀 글자로도 본다 — 나라장터 공고명 검색이 띄어쓰기를 무시해서 「스마트팩토리」로 찾은 「스마트 팩토리 …」가 빠졌다(2.0.7)
  const compact = haystack.replace(/ /g, "");
  return terms.every((term) => haystack.includes(term) || compact.includes(term));
}
