/**
 * 화면 곳곳에서 실전 가이드 절로 가는 작은 링크(32차 §3-A-9). 주소는 `lib/guide` 의 GUIDE_LINKS 에서만 고른다(앵커 시험).
 */

import Link from "next/link";
import type { ReactNode } from "react";

export function GuideContextLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return (
    <Link href={href} data-guide-link className={`mc-focus whitespace-nowrap text-cosmos-cyan underline-offset-2 hover:underline ${className}`}>
      {children}
    </Link>
  );
}
