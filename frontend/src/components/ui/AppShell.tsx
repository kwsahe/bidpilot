"use client";

/**
 * 공통 App Shell — 브랜드 + 화면 간 내비게이션(Mission Control / 공고 탐색 / RFP Matrix).
 * 대시보드("/")는 TopBar 안에 BrandNav만 끼워 넣고, 하위 화면은 AppShell 전체를 쓴다.
 * 페이지를 이동해도 같은 제품이라는 인상을 주기 위해 배경·패널·여백 규칙을 여기서 고정한다.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

import { SessionControls } from "@/components/ui/SessionControls";
import {
  hrefWithNotice,
  isSupportProgramId,
  readSelectedNotice,
  readSelection,
  readSelectionServer,
  readSelectedNoticeServer,
  subscribeSelection,
} from "@/lib/selection";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { WhyBidPilotButton } from "@/components/ui/WhyBidPilotDialog";
import { useDisplayMode } from "@/lib/viewMode";
import { modeFooterLine } from "@/lib/deploymentMode";
import { confirmDiscard } from "@/lib/unsavedGuard";
import { useDeploymentMode } from "@/lib/useDeploymentMode";
import { FULL_VIEW_ONLY_TAG, GUIDE_SHORT_NAME, SCREEN_NAMES } from "@/lib/terms";

export interface NavItem {
  href: string;
  label: string;
  short: string;
  description: string;
}

/** 메뉴 이름 = 화면 제목(h1) — `lib/terms` SCREEN_NAMES 하나 (27차 UNI-12 · LNK-05). */
export const NAV_ITEMS: NavItem[] = [
  // 2.1.0 — 대시보드는 사업기회 통계(오늘 검토할 사업 · 새 공고 · 마감)이고, 공고 하나를 보는 8단계 화면은 「입찰 분석」(/analysis)이다.
  { href: "/", label: SCREEN_NAMES.dashboard, short: SCREEN_NAMES.dashboard, description: "오늘 검토할 사업 · 새 공고 · 마감을 한눈에 — 숫자를 누르면 같은 조건의 사업기회 목록이 열립니다" },
  { href: "/analysis", label: SCREEN_NAMES.analysis, short: SCREEN_NAMES.analysis, description: "공고 → 요구사항 → 회사 근거 → 제안서 → 제출 전 점검을 한 화면에서" },
  { href: "/radar", label: SCREEN_NAMES.radar, short: SCREEN_NAMES.radar, description: "사업기회 레이더 — 나라장터 입찰과 기업마당 지원사업을 회사 기준 검토 우선순위로" },
  // 사업계획서 작성은 메뉴에서 빠지고 사업기회 행의 「사업계획서 작성 →」 · 「제안서 작성 →」 단추로 들어간다(37차 §3-E · 담당자 결정 2026-10-14).
  // 페이지(/plan)는 그대로다 — 대시보드 6단계 · 지원사업 상세의 링크도 그대로 그리로 간다.
  { href: "/opportunities", label: SCREEN_NAMES.opportunities, short: SCREEN_NAMES.opportunities, description: "나라장터 입찰공고와 기업마당 지원사업 전체 목록 · 검색 · 정렬 · 사업계획서 · 제안서 작성" },
  { href: "/company", label: SCREEN_NAMES.company, short: SCREEN_NAMES.company, description: "회사자료 등록 및 근거 색인 — 담당자가 확인한 문단만 근거가 된다" },
  // 32차 §3-A-3 — 처음 하는 회사를 위한 실전 가이드(문서 화면 · 두 보기 같은 한 화면).
  { href: "/guide", label: SCREEN_NAMES.guide, short: GUIDE_SHORT_NAME, description: "처음 하는 회사를 위한 입찰 · 지원사업 실전 가이드 — 등록 · 인증서 · 확인서 · 제출 순서와 출처" },
];

/** 쉬운 보기가 없는 화면 (24차 §3-1) — 쉬운 보기에서 그리로 가는 링크 옆에 「(전체 보기)」를 적는다(보기 전환 이름과 같은 말 · CMN-17). */
const FULL_ONLY_HREFS = new Set(["/company", "/radar"]);

function hasSimpleView(pathname: string | null): boolean {
  if (!pathname) return false;
  // 사업계획서 작성(/plan)은 두 보기가 같은 한 화면이다 — 「전체 보기만 있습니다」 줄을 달지 않는다 (28차 §3-D).
  // 실전 가이드(/guide)도 두 보기가 같은 한 화면 — 문서라 보기 구분이 없다(32차 §3-A-3).
  return pathname === "/" || pathname === "/analysis" || pathname === "/cosmos" || pathname.startsWith("/opportunities") || pathname.startsWith("/support/") || pathname.startsWith("/plan") || pathname.startsWith("/guide");
}

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/") return pathname === "/";
  if (href === "/analysis") return pathname === "/analysis" || pathname === "/cosmos";
  // 지원사업 신청 분석(/support/…) · 사업계획서 작성(/plan · 37차 §3-E)은 사업기회에서 들어가는 화면이라 「사업기회」를 활성으로 둔다.
  if (href === "/opportunities") return pathname.startsWith("/opportunities") || pathname.startsWith("/support") || pathname.startsWith("/plan");
  return pathname.startsWith(href);
}

/**
 * 메뉴 · 로고로 떠날 때도 저장 안 된 글을 묻는다 — 상세 링크 · 공고 바꾸기는 물었는데 메뉴는 묻지 않아 검사할 초안이 말없이 사라졌다.
 * 떠나기로 하면 표시도 정리돼, 떠난 뒤 엉뚱한 화면에서 「사라집니다」라고 다시 묻지 않는다(2.0.6).
 */
function leaveGuard(event: MouseEvent<HTMLAnchorElement>): void {
  if (!confirmDiscard("작성 중인 내용")) event.preventDefault();
}

export function BrandMark({ compact = false, compactBelowSm = false }: { compact?: boolean; compactBelowSm?: boolean }) {
  // 대시보드에서 로고를 누르면 떠나는 것이 아니다 — 묻고 확인하면 작성 표시만 지워져 그 뒤 보호가 꺼졌다(2.0.6)
  const onHome = usePathname() === "/";
  return (
    <Link
      href="/"
      data-tour="topbar-brand"
      onClick={onHome ? undefined : leaveGuard}
      className="mc-focus flex min-w-0 shrink-0 items-center gap-2.5 rounded-lg leading-tight"
      aria-label="BidPilot AI — 대시보드 홈"
    >
      <span
        aria-hidden="true"
        className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cosmos-cyan/40 bg-cosmos-cyan/10"
      >
        <span className="absolute h-3.5 w-3.5 rounded-full border border-cosmos-cyan/70" />
        <span className="h-1.5 w-1.5 rounded-full bg-cosmos-cyan shadow-[0_0_10px_var(--cosmos-cyan)]" />
      </span>
      <span className="flex min-w-0 flex-col">
        {!compact && (
          <span
            // 대문자 변환을 뺐다 — 「EVIDENCE-BASED AI 수주 AGENT」로 읽혔다 (CMN-16). 표어 자체를 한국어로 할지는 담당자 결정.
            className={`truncate text-[12px] font-medium tracking-[0.18em] text-cosmos-cyan ${
              compactBelowSm ? "hidden sm:block" : ""
            }`}
          >
            근거 기반 AI 수주 도우미
          </span>
        )}
        <span className="truncate text-[15px] font-semibold text-cosmos-text">BidPilot AI</span>
      </span>
    </Link>
  );
}

export function BrandNav({ className = "" }: { className?: string }) {
  const pathname = usePathname();
  // 지금 고른 공고를 링크에 얹는다 — 고정 문자열이면 상단 메뉴를 누르는 순간 선택이 사라졌다.
  //
  // 구독해서 읽는다 — 이 화면들은 정적으로 prerender 되므로 그냥 함수를 부르면
  // 빌드 시점 값(null)이 그대로 굳어 링크가 갱신되지 않는다.
  const selected = useSyncExternalStore(subscribeSelection, readSelectedNotice, readSelectedNoticeServer);
  /**
   * 지금 보고 있는 것이 기업마당 지원사업인가 — 입찰을 싣지 않는다(받는 화면이 저장된 지원사업을 연다 · 27차 LNK-01).
   * 예전 메뉴 잠금(지원사업이면 요구사항 정리표를 회색으로)은 없앴다 — 한 번 지원사업을 누르면 모든 화면에서
   * 잠긴 채 남아 「들어갈 때도, 못 들어갈 때도」 있었다 (28차 §3-C · 담당자 지시).
   */
  const viewing = useSyncExternalStore(subscribeSelection, readSelection, readSelectionServer);
  const onSupport = isSupportProgramId(viewing);
  // 저장된 보기가 쉬운 보기면 어느 화면에서든 꼬리표를 단다 — 전체 보기만 있는 화면에 와서도
  // 그 사실을 알 수 있게 (27차 LNK-12). 예전에는 그 화면에 닿는 순간 꼬리표가 모두 사라졌다.
  const simple = useDisplayMode() === "simple";

  return (
    <nav aria-label="화면 이동" className={`flex max-w-full flex-wrap items-center gap-0.5 rounded-lg border border-cosmos-border bg-cosmos-panel p-0.5 backdrop-blur ${className}`}>
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            // 지원사업을 보는 중이면 입찰을 싣지 않는다 — 쿼리 없이 가면 받는 화면이 저장된 지원사업을 연다(27차 LNK-01).
            href={hrefWithNotice(item.href, onSupport ? null : selected)}
            // 지금 보고 있는 메뉴는 떠나는 것이 아니다 — 묻지 않는다(2.0.6 · 위 로고와 같다)
            onClick={active ? undefined : leaveGuard}
            aria-current={active ? "page" : undefined}
            title={item.description}
            // 640px 미만은 두 보기 모두 좁은 여백 — 메뉴가 여럿이라 390 폭에서 넘치지 않게(32차 §3-A-3 · 37차부터 다섯 · 2.1.0 여섯부터는 nav 가 줄을 바꿔 360 폭도 가로 스크롤 없음).
            className={`mc-focus min-h-8 whitespace-nowrap rounded-md px-1.5 py-1 text-center text-[12px] font-medium transition-colors sm:px-2.5 ${active ? "bg-cosmos-blue/25 text-cosmos-text" : "text-cosmos-secondary hover:text-cosmos-text"}`}
          >
            <span className="hidden sm:inline">{item.label}</span>
            <span className="sm:hidden">{item.short}</span>
            {/* 640px 미만에서는 이름 아래 둘째 줄로 — 옆에 붙이면 메뉴가 창 밖으로 넘친다 (27차 LNK-12). */}
            {simple && FULL_ONLY_HREFS.has(item.href) && (
              <span className="block text-cosmos-muted sm:inline" data-full-only>
                <span className="hidden sm:inline"> </span>
                {FULL_VIEW_ONLY_TAG}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}


export interface AppShellProps {
  /** 헤더 우측 (상태 배지·새로고침 등) */
  headerAside?: ReactNode;
  children: ReactNode;
  /** 본문 최대 폭 */
  width?: "wide" | "max";
}

export default function AppShell({ headerAside, children, width = "wide" }: AppShellProps) {
  const deployment = useDeploymentMode();
  const modeLine = modeFooterLine(deployment);
  // 44차 S11 — 회사 서버(중계 · 로그인 게이트)에서는 대회 이름 줄을 뺀다. 공개 데모(스냅샷)는 그대로 · 키트는 30차부터 뺌.
  const contestLine = process.env.NEXT_PUBLIC_KIT === "1" || (deployment?.backend === "proxy" && deployment.gated) ? "" : "2026 전남광주 청년 AI 솔버톤 B트랙 · ";
  // 쉬운 보기가 없는 화면(/company · /radar)에 쉬운 보기로 왔을 때 한 줄 (27차 LNK-12 · §3-E-4).
  const pathname = usePathname();
  const fullOnlyNote = useDisplayMode() === "simple" && !hasSimpleView(pathname);

  return (
    <div className="mc-page-bg flex min-h-dvh flex-col font-sans text-[14px] text-cosmos-text">
      <header className="sticky top-0 z-30 border-b border-cosmos-border bg-cosmos-bg/85 backdrop-blur print:hidden">
        <div
          className={`mx-auto flex min-h-14 w-full flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 sm:px-5 ${
            width === "wide" ? "max-w-[1440px]" : ""
          }`}
        >
          <BrandMark compactBelowSm />
          <div className="mx-1 hidden h-6 w-px shrink-0 bg-cosmos-border md:block" aria-hidden="true" />
          <BrandNav />
          {/* 오른쪽 순서는 모든 화면이 같다 — 회사 선택기 → 보기 전환 → (화면 단추) → 접속 → 「?」 (27차 §3-E-4). */}
          <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2">
            {headerAside}
            <SessionControls />
            <ThemeToggle />
            <WhyBidPilotButton variant="icon" />
          </div>
        </div>
      </header>
      <main
        className={`mx-auto flex w-full min-w-0 flex-1 flex-col gap-5 px-3 py-4 sm:px-5 sm:py-6 ${
          width === "wide" ? "max-w-[1440px]" : ""
        }`}
      >
        {fullOnlyNote && (
          <p role="note" data-full-only-note className="-mb-2 text-[12.5px] text-cosmos-muted">
            이 화면은 쉬운 보기가 없습니다. 다른 화면으로 가면 다시 쉬운 보기로 보입니다.
          </p>
        )}
        {children}
      </main>
      <footer className="border-t border-cosmos-border px-3 py-2 text-[12px] text-cosmos-muted sm:px-5 print:hidden">
        {/* 자료 출처 문장은 실제 배포 모드에서 나온다. 모드를 모르면 아예 쓰지 않는다 —
            실회사자료를 띄워 놓고 「합성 자료만 사용」이라고 말하던 것이 이 자리였다.
            「낙찰·선정 확률이 아니다」는 어느 모드에서나 참이라 항상 남는다(기업마당 지원 적합도 포함 · CLAUDE.md §12).
            모드를 모를 때도 구분자가 남는다 — 「…B트랙 추천등급…」으로 붙어 읽혔다 (CMN-18). */}
        {/* 키트(범용 설치)에서는 대회 이름 줄을 뺀다(30차 §3-G · NEXT_PUBLIC_KIT=1). */}
        {`BidPilot AI · ${contestLine}${modeLine ? `${modeLine} · ` : ""}추천등급·적합도는 낙찰·선정 확률이 아닙니다.`}
      </footer>
    </div>
  );
}
