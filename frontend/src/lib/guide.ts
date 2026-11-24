/**
 * 실전 가이드 화면(`/guide`)의 규칙 — 원본은 `frontend/content/first_time_guide.md` 한 곳(32차 §3-A).
 *
 * - 절 나누기 · 고정 앵커(절 번호): `## 2.` → `g-2` · `### 1-7.` → `g-1-7` · 번호 없는 절은 장 안 순서대로 `g-7-a` · `g-7-b` …
 * - 8장 「확인 필요 목록」 번호 항목은 `g-8-13` 처럼 번호 그대로.
 * - 화면 곳곳의 문맥 링크는 `GUIDE_LINKS` 하나 — 시험(`tests/guideAnchors.test.ts`)이 모든 `/guide#…` 가 실제 id 를 가리키는지 본다.
 */

export const GUIDE_PATH = "/guide";

export interface GuideSection {
  level: 1 | 2 | 3;
  title: string;
  id: string;
  /** 이 제목 아래 · 다음 제목 전까지의 마크다운 */
  body: string;
  chapter: number | null;
}

const H2_NUMBER = /^(\d+)\.\s+/;
const H3_NUMBER = /^(\d+)-(\d+)\.\s+/;

/** 마크다운을 제목마다 자른다 — 장(##) · 절(###). 맨 앞 `#` 은 문서 제목(화면 h1 은 메뉴 이름이라 따로). */
export function parseGuide(markdown: string): GuideSection[] {
  const sections: GuideSection[] = [];
  let chapter: number | null = null;
  const unnumbered = new Map<number, number>();
  let current: GuideSection | null = null;
  const lines: string[] = [];
  const flush = () => {
    if (current) {
      current.body = lines.join("\n").trim();
      sections.push(current);
    }
    lines.length = 0;
  };
  let fenced = false;
  for (const line of markdown.replace(/\r\n/g, "\n").split("\n")) {
    if (line.startsWith("```")) fenced = !fenced;
    const h = fenced ? null : /^(#{1,3})\s+(.+?)\s*$/.exec(line);
    if (!h) {
      lines.push(line);
      continue;
    }
    flush();
    const level = h[1].length as 1 | 2 | 3;
    const title = h[2];
    if (level === 1) {
      current = { level, title, id: "g-top", body: "", chapter: null };
    } else if (level === 2) {
      const n = H2_NUMBER.exec(title);
      chapter = n ? Number(n[1]) : null;
      current = { level, title, id: n ? `g-${n[1]}` : `g-x-${sections.length}`, body: "", chapter };
    } else {
      const n = H3_NUMBER.exec(title);
      let id: string;
      if (n) id = `g-${n[1]}-${n[2]}`;
      else {
        const key = chapter ?? -1;
        const order = unnumbered.get(key) ?? 0;
        unnumbered.set(key, order + 1);
        id = `g-${chapter ?? "x"}-${String.fromCharCode(97 + order)}`;
      }
      current = { level, title, id, body: "", chapter };
    }
  }
  flush();
  return sections;
}

/** 8장 번호 항목(`1. **…**`)의 id — `g-8-1` … */
export function confirmItemIds(sections: readonly GuideSection[]): string[] {
  const ids: string[] = [];
  for (const section of sections) {
    if (section.chapter !== 8) continue;
    for (const line of section.body.split("\n")) {
      const m = /^(\d+)\.\s/.exec(line);
      if (m) ids.push(`g-8-${m[1]}`);
    }
  }
  return ids;
}

/** 화면 링크가 가리킬 수 있는 모든 id. */
export function guideAnchorIds(markdown: string): Set<string> {
  const sections = parseGuide(markdown);
  return new Set([...sections.map((s) => s.id), ...confirmItemIds(sections)]);
}

/** 문서 기준일 — 머리 인용문의 「기준일: YYYY-MM-DD」. */
export function guideBaseDate(markdown: string): string | null {
  return /기준일:\s*(\d{4}-\d{2}-\d{2})/.exec(markdown)?.[1] ?? null;
}

/** 제목 글에서 번호를 뗀 이름(목차 · 링크 글). */
export function sectionLabel(section: GuideSection): string {
  return section.title.replace(H3_NUMBER, "").replace(H2_NUMBER, "");
}

/** 제목 앞 번호(「1-7」 · 「2」) — 없으면 빈 글. */
export function sectionNumber(section: GuideSection): string {
  return H3_NUMBER.exec(section.title)?.slice(1, 3).join("-") ?? H2_NUMBER.exec(section.title)?.[1] ?? "";
}

export const guideHref = (id: string): string => `${GUIDE_PATH}#${id}`;

/**
 * 맨 위 「지금 하려는 일」 세 갈래 — 걸음 점검 문서의 절 순서 그대로(32차 §3-A-5).
 * 범위(`1-0~1-8`)는 그 사이 절을 모두 넣는다.
 */
export const GUIDE_PATHS: ReadonlyArray<{ key: string; title: string; ids: readonly string[] }> = [
  { key: "pick", title: "공고 고르기 · 참가 판단", ids: ["g-0-1", "g-2-1", "g-2-3", "g-2-4"] },
  {
    key: "g2b",
    title: "나라장터 입찰이 처음",
    ids: ["g-0-2", ...range(1, 0, 8), "g-1-12", ...range(2, 7, 12)],
  },
  {
    key: "support",
    title: "지원사업 사업계획서",
    ids: ["g-3-2", "g-3-6", ...range(4, 1, 9), "g-3-7", "g-3-9"],
  },
];

function range(chapter: number, from: number, to: number): string[] {
  return Array.from({ length: to - from + 1 }, (_, i) => `g-${chapter}-${from + i}`);
}

/** 화면 곳곳에서 가이드로 가는 문맥 링크 — 모두 여기서 고른다(앵커 시험이 본다). */
export const GUIDE_LINKS = {
  start: guideHref("g-0-2"),
  firstBid: guideHref("g-1-6"),
  register: guideHref("g-1-7"),
  industry: guideHref("g-1-5"),
  validity: guideHref("g-1-12"),
  judge: guideHref("g-2-3"),
  contract: guideHref("g-2-4"),
  // 33차 §3-B-5 — 「규모 큼」 · 「공동수급 파트너 확보 시」 · 상세 사업 규모 줄(확인 필요)
  consortium: guideHref("g-2-6"),
  outside: guideHref("g-2-7"),
  supportSubmit: guideHref("g-3-7"),
  supportAgreement: guideHref("g-3-9"),
  planFill: guideHref("g-4-5"),
  aiDraft: guideHref("g-4-8"),
  screenWords: guideHref("g-7-d"),
} as const;

/** 회사자료 「준비 상태」 줄 → 가이드 절(32차 §3-A-9). 이름은 `READINESS_ROWS` 그대로. */
export const READINESS_GUIDE: Readonly<Record<string, string>> = {
  "나라장터 입찰참가자격 등록": guideHref("g-1-7"),
  "사업자 범용 공동인증서": guideHref("g-1-2"),
  "중소기업(소상공인) 확인서": guideHref("g-1-3"),
  "창업기업 확인서": guideHref("g-1-4"),
  "소프트웨어사업자 신고(1468)": guideHref("g-1-5"),
  "직접생산확인증명서": guideHref("g-1-9"),
  "신용평가등급확인서": guideHref("g-1-10"),
};

/** 기준일부터 지난 날 수(KST 날짜 기준). 날짜가 없으면 null. */
export function daysSince(baseDate: string | null, nowMs: number): number | null {
  if (!baseDate) return null;
  const base = Date.parse(`${baseDate}T00:00:00+09:00`);
  if (Number.isNaN(base)) return null;
  return Math.max(0, Math.floor((nowMs - base) / 86_400_000));
}
