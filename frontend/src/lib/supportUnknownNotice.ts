/**
 * 「확인 필요」 배너 문구 — **두 화면이 같은 말을 하게 하는 단일 출처**
 * (ISSUE-113 · prompt_01 §4-E).
 *
 * ## 무엇이 틀렸나
 *
 * 「원문 상세 확인이 필요한 항목 12건 — **기업마당 목록 정보만으로** 판정할 수 없는
 * 조건은 채우지 않았습니다」가 **공고문을 읽은 공고에도** 그대로 떴다(A1 · 126482).
 * 공고문을 내려받아 조항까지 뽑아 놓고 「목록 정보만으로」라고 말하면, 담당자는
 * 앱이 아직 원문을 안 봤다고 읽는다 — 실제로 한 일을 스스로 부정하는 문구다.
 *
 * 11차 §4-B-4 는 건수만 바꿨고 문구는 그대로였다(재검증 §3-3).
 *
 * ## 지키는 것
 *
 * 두 사실을 갈라 말한다.
 *   공고문을 읽었다   → 「공고문에서 못 찾은 조항」 (원문을 봤는데도 없더라)
 *   못 읽었다         → 「목록 정보만으로」        (원문을 아직 못 봤다)
 *
 * 문구가 `SupportShell` 과 `SupportDashboardBody` 두 곳에 복사돼 있어서 11차에 한 곳만
 * 고쳐질 뻔했다. 여기 하나만 둔다.
 */

/**
 * 「확인 필요」 배너 한 줄 — 공고문을 읽었으면 **조항**만 「공고문에서 못 찾은 조항」으로 세고, 공고문에서 찾아본 적 없는
 * 항목(지원 방식 · 규모 · 서류 …)은 따로 센다(분석 기준 팝오버와 같은 수 · SUP-07). 신청 분석 화면과 대시보드 지원사업 보기가
 * 같은 함수를 두 벌 갖고 있던 것을 여기 하나로 — 두 화면 모두 이것을 부른다.
 */
export function supportUnknownBanner(result: {
  unknown_count: number;
  document_read?: boolean | null;
  plan: { eligibility: Array<{ key: string; status: string }> };
}): string {
  if (!result.document_read) return supportUnknownNotice(result.unknown_count, result.document_read);
  const clauses = result.plan.eligibility.filter((item) => item.key.startsWith("clause_") && item.status === "unknown").length;
  const rest = result.unknown_count - clauses;
  const other = rest > 0 ? `목록 정보에 없는 항목 ${rest}건(지원 방식·규모 등)도 공고 원문에서 확인하세요.` : "";
  return clauses > 0 ? `${supportUnknownNotice(clauses, true)}${other ? ` ${other}` : ""}` : other;
}

/**
 * @param count 확인이 필요한 항목 수 (`result.unknown_count`)
 * @param documentRead 공고문 원문을 읽고 판정했는가. 옛 스냅샷에는 없어 undefined 가 온다.
 */
export function supportUnknownNotice(count: number, documentRead: boolean | null | undefined): string {
  if (documentRead) {
    return `공고문에서 못 찾은 조항 ${count}건 — 원문에서 확인하세요.`;
  }
  return (
    `원문 상세 확인이 필요한 항목 ${count}건 — 기업마당 목록 정보만으로 판정할 수 없는 조건은 ` +
    "채우지 않았습니다. 공고 원문·첨부 공고문에서 직접 확인하세요."
  );
}
