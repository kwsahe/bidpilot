"use client";

/**
 * 내보내기 — **엑셀 · 표 · CSV, 그리고 지난번에 뽑은 파일** (0924.md §4-C).
 *
 * ## 왜 필요한가
 *
 * 담당자가 실제로 쓰는 도구는 엑셀이다. 그런데 지금까지 내려받기는 Markdown 과 CSV 뿐이었고,
 * CSV 는 시트가 하나라 「나라장터」와 「기업마당」과 「이번 주 할 일」을 한 파일에 담을 수
 * 없었다. 그리고 내려받은 뒤에는 **어떤 조건으로 뽑은 표인지** 아무 데도 남지 않았다.
 *
 * 그래서 두 가지를 한 자리에 둔다.
 *
 *   1. 엑셀 내려받기 — 시트 일곱(사업기회·나라장터·기업마당·이번 주 할 일·갭 리포트·근거·브리핑)
 *   2. 저장된 파일 — 언제·어떤 조건·몇 건이었는지와 함께 다시 내려받기
 *
 * ## 규칙
 *
 * - **화면이 보고 있는 것과 같은 조건**을 그대로 넘긴다. 파일과 화면이 갈리면 담당자가
 *   어느 쪽을 남에게 보내야 할지 알 수 없다.
 * - 저장된 파일 목록은 **조회만** 한다. 여기서 지우지 않는다.
 */

import { useCallback, useEffect, useState } from "react";

import { DownloadLink } from "@/components/ui/DownloadLink";
import { Popover } from "@/components/ui/overlays";
import { getSavedExports, opportunityExportUrl, savedExportUrl } from "@/lib/api";
import type { OpportunityQuery, SavedExport } from "@/types/opportunity";

/** 「2026. 9. 18. 14:30」 — 목록 다른 곳과 같은 표기다. */
function stamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "시각 없음";
  return date.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * 저장 이력의 조건 줄은 백엔드가 쓴 글 그대로다 — 옛 저장본에는 정렬이 영문 코드(「priority 정렬」)로 남아 있어
 * 화면에서 사람 말로 바꿔 적는다 (OPP-14). 백엔드 쪽 글도 바꾸면 이 줄은 아무 일도 하지 않는다.
 */
const SORT_WORDS: Record<string, string> = {
  practical: "실무 우선순위순",
  priority: "회사 기준 검토 우선순위순",
  slack: "마감 여유순",
  deadline: "마감 임박순",
  recent: "최신 등록순",
  value: "예산순",
};

function conditionsText(conditions: string): string {
  return conditions.replace(/\b(practical|priority|slack|deadline|recent|value) 정렬/g, (_, key: string) => SORT_WORDS[key]);
}

function sizeText(bytes: number): string {
  if (!bytes) return "";
  const kilobytes = bytes / 1024;
  return kilobytes >= 1024 ? `${(kilobytes / 1024).toFixed(1)}MB` : `${Math.round(kilobytes)}KB`;
}

export interface ExportMenuProps {
  /** 화면이 보고 있는 조건 그대로. */
  query: OpportunityQuery;
  /** 조건 한 줄 설명 — 팝오버 맨 위에 적는다. 파일에 **무엇이 반영되고 무엇이 안 되는지** 사실대로. */
  hint?: string;
  /** 패널을 어느 쪽에 맞출지. 메뉴 안(왼쪽 기준)에서는 start — 오른쪽 맞춤이면 좁은 폭에서 화면 왼쪽 밖으로 열렸다 (OPP-07). */
  align?: "start" | "end";
}

/** 팝오버가 열릴 때마다 저장 목록을 다시 읽는다 — 엑셀을 받은 뒤 다시 열면 늘어난 목록이 보인다 (OPP-32). */
function ReloadOnOpen({ reload }: { reload: () => void }) {
  useEffect(reload, [reload]);
  return null;
}

export default function ExportMenu({ query, hint, align = "end" }: ExportMenuProps) {
  const [saved, setSaved] = useState<SavedExport[] | null>(null);
  const [savedError, setSavedError] = useState(false);
  const organizationId = query.organizationId;

  const reload = useCallback(() => {
    if (!organizationId) return;
    getSavedExports({ organizationId })
      .then((response) => {
        setSaved(response.files);
        setSavedError(false);
      })
      .catch(() => {
        // 부가 정보다 — 내려받기는 그대로 된다. 다만 「불러오는 중…」에 멈춰 있지 않게 실패를 적는다 (OPP-32).
        // 처음부터 못 받았으면 saved 는 null 그대로 — 모르는 수를 「0개」로 적지 않는다.
        setSavedError(true);
      });
  }, [organizationId]);

  useEffect(reload, [reload]);

  const savedCount = saved?.length ?? 0;
  return (
    <Popover
      align={align}
      width="360px"
      // 숫자는 **저장된 파일 수**다 — 단위를 붙이고 읽는 프로그램 이름에도 넣는다 (OPP-33).
      triggerLabel={`내보내기 — 엑셀·표·CSV와 저장된 파일${savedCount > 0 ? ` ${savedCount}개` : ""}`}
      title="내보내기"
      trigger={
        <>
          내보내기 ↓
          {savedCount > 0 && (
            <span className="ml-1 text-[12px] tabular-nums text-cosmos-muted">저장 {savedCount}</span>
          )}
        </>
      }
    >
      <ReloadOnOpen reload={reload} />
      <div className="flex flex-col gap-2.5">
        <p className="text-[12px] leading-5 text-cosmos-secondary">
          {hint ?? "지금 화면이 보고 있는 조건 그대로 내려받습니다."}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <DownloadLink
            href={opportunityExportUrl({ ...query, format: "xlsx" })}
            // 받은 엑셀은 서버에도 남는다 — 팝오버를 닫았다 열지 않아도 저장 목록과 「저장 N」이 바로 는다 (OPP-32).
            onDone={reload}
            title="시트 일곱 — 사업기회 · 나라장터 · 기업마당 · 이번 주 할 일 · 갭 리포트 · 자격 판정 근거 · 브리핑"
            className="mc-focus rounded-lg bg-cosmos-blue-strong px-3 py-1.5 text-[12.5px] font-semibold text-white"
          >
            엑셀 내려받기
          </DownloadLink>
          <DownloadLink
            href={opportunityExportUrl({ ...query, format: "md" })}
            title="담당자에게 보낼 수 있는 표 (Markdown)"
            className="mc-focus rounded px-1 text-[12.5px] text-cosmos-cyan hover:underline"
          >
            표(Markdown)
          </DownloadLink>
          <DownloadLink
            href={opportunityExportUrl({ ...query, format: "csv" })}
            title="엑셀에서 여는 한 장짜리 표"
            className="mc-focus rounded px-1 text-[12.5px] text-cosmos-cyan hover:underline"
          >
            CSV
          </DownloadLink>
          {/* 37차 §3-H — 화면 조건과 상관없이 전체를 회사 방식 순서로 한 장. 받을 때마다 순위표를 남겨 다음 브리핑이 견준다. */}
          <DownloadLink
            href={opportunityExportUrl({ organizationId: query.organizationId, days: query.days, format: "brief" })}
            title="오늘 볼 공고를 한 장으로 — 매출 → 지원금 · 회사 방식 순서 · 지난 브리핑 대비 달라진 것"
            className="mc-focus rounded px-1 text-[12.5px] text-cosmos-cyan hover:underline"
          >
            오늘 브리핑(마크다운)
          </DownloadLink>
        </div>

        <div className="flex flex-col gap-1 border-t border-cosmos-border pt-2">
          <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-cosmos-muted">
            저장된 파일 {saved === null ? "" : `${saved.length}개`}
          </p>
          {/* 20 은 백엔드 export_store.MAX_FILES 와 같아야 한다 — 말없이 지워지던 것을 미리 알린다 (OPP-01) */}
          <p className="text-[12px] leading-5 text-cosmos-muted">
            엑셀로 내려받을 때마다 같은 파일이 회사 폴더에 한 벌 남습니다. 최근 20개까지만 두고, 넘으면 가장 오래된 것부터 지웁니다.
          </p>
          {savedError && <p className="text-[12px] leading-5 text-cosmos-red-text">저장된 파일 목록을 불러오지 못했습니다 — 내려받기는 그대로 됩니다.</p>}
          {saved === null ? (
            savedError ? null : <p className="text-[12px] text-cosmos-muted">불러오는 중…</p>
          ) : saved.length === 0 ? (
            savedError ? null : (
              <p className="text-[12px] leading-5 text-cosmos-muted">아직 없습니다.</p>
            )
          ) : (
            <ul className="flex max-h-56 flex-col gap-1.5 overflow-y-auto">
              {saved.map((file) => (
                <li key={file.file} className="flex flex-col gap-0.5">
                  <DownloadLink
                    href={savedExportUrl(file.file, organizationId)}
                    fallbackName={file.file}
                    className="mc-focus truncate rounded text-left text-[12.5px] text-cosmos-cyan hover:underline"
                    title={file.file}
                  >
                    {file.file}
                  </DownloadLink>
                  <span className="text-[12px] leading-4 text-cosmos-muted">
                    {stamp(file.saved_at)} · {conditionsText(file.conditions)} · {sizeText(file.bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Popover>
  );
}
