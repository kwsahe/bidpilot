/**
 * 목록을 다시 읽은 뒤 열려 있던 문서를 그대로 둘지 (CMP-01 · ISSUE-163).
 *
 * 예전 `reload()` 는 결과가 오면 무조건 선택을 비웠다. 저장 · 승인 · 비활성 · 다시 추출 · 업로드가
 * 모두 `reload()` 를 부르므로, 끝나는 순간 문서 상세가 스스로 닫혔고 「저장하고 다음 문서로」는
 * 다음 문서를 잠깐 열었다가 닫았다. 새 목록에 그 문서가 **없을 때만** 비운다.
 */
export function keepSelectedDocument(previous: string | null, documents: readonly { id: string }[] | null): string | null {
  return previous && documents?.some((doc) => doc.id === previous) ? previous : null;
}
