/**
 * 실전 가이드 목차 — 맨 위 「지금 하려는 일」 세 갈래 + 0~8장(32차 §3-A-5).
 * 넓은 화면(lg)은 옆에 고정, 좁은 화면은 맨 위에 접힌 칸. 인쇄할 때는 숨긴다.
 */

import { GUIDE_PATHS, sectionLabel, sectionNumber, type GuideSection } from "@/lib/guide";

const PAST_EXAMPLE_CHAPTER = 5;

function TocBody({ sections }: { sections: readonly GuideSection[] }) {
  const byId = new Map(sections.map((s) => [s.id, s]));
  const chapters = sections.filter((s) => s.level === 2);
  return (
    <div className="flex flex-col gap-4 text-[14px] leading-6">
      <div>
        <p className="mb-1 text-[12.5px] font-semibold text-cosmos-cyan">지금 하려는 일</p>
        <ul className="flex flex-col gap-2">
          {GUIDE_PATHS.map((path) => (
            <li key={path.key}>
              <details>
                <summary className="mc-focus cursor-pointer rounded font-medium text-cosmos-text">{path.title}</summary>
                <ol className="mt-1 flex flex-col gap-0.5 border-l border-cosmos-border pl-3">
                  {path.ids.map((id) => {
                    const section = byId.get(id);
                    if (!section) return null;
                    return (
                      <li key={id}>
                        <a href={`#${id}`} className="mc-focus text-cosmos-secondary hover:text-cosmos-text">
                          {sectionNumber(section)}. {sectionLabel(section)}
                        </a>
                      </li>
                    );
                  })}
                </ol>
              </details>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-1 text-[12.5px] font-semibold text-cosmos-cyan">장</p>
        <ol className="flex flex-col gap-1">
          {chapters.map((chapter) => {
            const children = sections.filter((s) => s.level === 3 && s.chapter === chapter.chapter);
            return (
              <li key={chapter.id}>
                <details>
                  <summary className="mc-focus cursor-pointer rounded text-cosmos-text">
                    <a href={`#${chapter.id}`} className="hover:underline">
                      {chapter.title}
                    </a>
                    {chapter.chapter === PAST_EXAMPLE_CHAPTER && <span className="text-cosmos-muted"> (지난 공고)</span>}
                  </summary>
                  {children.length > 0 && (
                    <ol className="mt-1 flex flex-col gap-0.5 border-l border-cosmos-border pl-3">
                      {children.map((section) => (
                        <li key={section.id}>
                          <a href={`#${section.id}`} className="mc-focus text-cosmos-secondary hover:text-cosmos-text">
                            {section.title}
                          </a>
                        </li>
                      ))}
                    </ol>
                  )}
                </details>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

export function GuideToc({ sections }: { sections: readonly GuideSection[] }) {
  return (
    <div className="min-w-0 print:hidden" data-guide-toc>
      <details className="rounded-xl border border-cosmos-border bg-cosmos-panel/60 p-3 lg:hidden">
        <summary className="mc-focus cursor-pointer text-[14px] font-semibold text-cosmos-text">목차 — 지금 하려는 일 · 0~8장</summary>
        <nav aria-label="가이드 목차" className="mt-3">
          <TocBody sections={sections} />
        </nav>
      </details>
      <nav
        aria-label="가이드 목차"
        className="sticky top-24 hidden max-h-[calc(100dvh-7rem)] overflow-y-auto rounded-xl border border-cosmos-border bg-cosmos-panel/60 p-4 lg:block"
      >
        <TocBody sections={sections} />
      </nav>
    </div>
  );
}
