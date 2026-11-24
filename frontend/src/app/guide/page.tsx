/**
 * 실전 가이드 — 처음 하는 회사를 위한 공공입찰 · 정부 지원사업 안내(32차 §3-A · 담당자 지시 10-07).
 *
 * 내용은 `frontend/content/first_time_guide.md` 한 곳 — 서버 컴포넌트가 `process.cwd()`(= frontend) 기준으로 읽는다.
 * 개발 · 빌드 · 키트 · Vercel 모두 frontend 가 루트라 같은 파일을 읽고, 빌드 때 읽어 정적으로 그린다(배포에 docs/ 가 없어도 된다).
 * 이 화면만 숫자 · 기간 · 비용을 출처 · 기준일과 함께 둔다(문서 화면 · 담당자 결정). 회사 「준비 상태」는 읽기만.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { GuideHashFocus, GuideNotice, GuideOrganizationPicker, GuidePrintButtons, GuideReadiness } from "@/components/guide/GuideClient";
import { GUIDE_CHECKBOX_NOTE_ID, GuideMarkdown } from "@/components/guide/GuideMarkdown";
import { GuideToc } from "@/components/guide/GuideToc";
import AppShell from "@/components/ui/AppShell";
import { SectionHeader } from "@/components/ui/primitives";
import { guideBaseDate, parseGuide } from "@/lib/guide";
import { GUIDE_LEGAL_NOTE, SCREEN_NAMES } from "@/lib/terms";

export default async function GuidePage() {
  const markdown = await readFile(join(process.cwd(), "content", "first_time_guide.md"), "utf8");
  const sections = parseGuide(markdown);
  const baseDate = guideBaseDate(markdown);
  const top = sections.find((s) => s.level === 1);

  return (
    <AppShell headerAside={<GuideOrganizationPicker />}>
      <div className="guide-doc flex min-w-0 flex-col gap-4">
        <GuideHashFocus />
        <SectionHeader as="h1" title={SCREEN_NAMES.guide} description={top?.title} aside={<GuidePrintButtons />} />
        <GuideNotice baseDate={baseDate} />
        <p id={GUIDE_CHECKBOX_NOTE_ID} className="text-[13px] leading-5 text-cosmos-muted print:hidden">
          체크 칸은 읽기 전용입니다 — 인쇄해서 쓰거나, 회사자료 「준비 상태」에 기록하세요.
        </p>
        <p data-print-only className="guide-print-head">
          기준일 {baseDate} · {GUIDE_LEGAL_NOTE} · 인쇄한 날 <span data-print-date />
        </p>
        <div className="grid min-w-0 gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <GuideToc sections={sections} />
          <article className="guide-body min-w-0 max-w-[72ch]">
            {top && <GuideMarkdown markdown={top.body} chapter={null} />}
            {sections
              .filter((s) => s.level > 1)
              .map((section) => (
                <section key={section.id} data-guide-id={section.id} className="guide-section">
                  {section.level === 2 ? (
                    <h2 id={section.id} tabIndex={-1}>
                      {section.title}
                    </h2>
                  ) : (
                    <h3 id={section.id} tabIndex={-1}>
                      {section.title}
                    </h3>
                  )}
                  <GuideMarkdown markdown={section.body} chapter={section.chapter} />
                  {section.id === "g-0-2" && <GuideReadiness />}
                </section>
              ))}
          </article>
        </div>
      </div>
    </AppShell>
  );
}
