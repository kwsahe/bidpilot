import type { Metadata } from "next";
import { Geist, Geist_Mono, Noto_Sans_KR } from "next/font/google";
import "./globals.css";
import { ConsentHost } from "@/components/ui/ConsentHost";
import { SessionHost } from "@/components/ui/SessionHost";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const notoSansKr = Noto_Sans_KR({
  variable: "--font-noto-sans-kr",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

export const metadata: Metadata = {
  // 대시보드 · 없는 주소의 탭 제목. 다른 화면은 제 폴더 layout · page 가 「화면 이름 · BidPilot AI」로 덮는다 (CMN-12).
  title: "BidPilot AI",
  description: "공공입찰 제안요청서의 요구사항을 회사 근거와 잇고 제출 전에 원문과 맞춰 보는 근거 기반 AI 수주 도우미",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme — 기본 어두운 화면. 밝은 화면을 고른 브라우저는 아래 <head> 스크립트가 그리기 전에 바꾼다(2.4.0 ⑥ · lib/theme.ts).
    // suppressHydrationWarning — 그 스크립트가 바꾼 <html> 속성만 하이드레이션 경고에서 뺀다(Next 16 안내 § Themes).
    <html
      lang="ko"
      data-theme="dark"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${notoSansKr.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        {children}
        {/* 화면 안 확인 창 한 곳(제안요청서 받기 등) — 브라우저 기본 창 대신 (28차 §A-6) */}
        <ConsentHost />
        {/* 세션이 끝났거나 5분 안에 끝날 때의 띠(43차 M28) — 쓰던 폼은 그대로 두고 새 탭에서 다시 로그인하게 한다 */}
        <SessionHost />
      </body>
    </html>
  );
}
