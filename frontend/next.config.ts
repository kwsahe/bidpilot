import type { NextConfig } from "next";

/**
 * 포트 4120은 와이어프레임 대시보드 전용 서버다 (`npm run dev:wireframe`).
 *
 * - 루트(`/`)를 `/wireframe` 으로 rewrite 해서 http://localhost:4120 을 열면 바로 와이어프레임이 뜬다.
 * - 3110번(Evidence Cosmos) 서버와 동시에 켤 수 있어야 하므로 빌드 캐시 폴더를 나눈다.
 *   같은 `.next` 를 두 dev 서버가 함께 쓰면 캐시가 깨진다.
 *
 * `next dev --port 4120` 이 포트를 확정한 뒤 `process.env.PORT` 에 넣어 주고,
 * 그 다음에 이 설정 파일을 읽는다.
 */
const WIREFRAME_PORT = "4120";
const isWireframeServer = process.env.PORT === WIREFRAME_PORT;

const nextConfig: NextConfig = {
  distDir: isWireframeServer ? ".next-wireframe" : ".next",

  // 42차 — 로그인 게이트(proxy.ts)를 지나는 요청 본문은 기본 10MB 에서 잘린다(Next 16 · docs proxyClientMaxBodySize).
  // 회사자료 업로드 상한 20MB(company_service) · nginx 24m 에 맞춘다 — 회사 서버는 업로드가 이 길(/api 중계)로 온다.
  experimental: {
    proxyClientMaxBodySize: "24mb",
  },

  // 요구사항 정리표는 사업기회 안의 탭이 됐다 — 옛 주소(북마크 · 문서 · 보고서)는 넘긴다(28차 §3-C).
  // 요청 쿼리(`?notice=` · `?req=`)는 Next 가 그대로 붙인다(docs 01-app/03-api-reference/05-config/01-next-config-js/redirects.md).
  async redirects() {
    return [
      { source: "/rfp", destination: "/opportunities?tab=sheet", permanent: false },
      // 2.1.0 — 공고 하나를 보는 화면이 /analysis(입찰 분석)로 옮겼다. 옛 주소(북마크 · 내려받은 브리핑 · 엑셀)의
      // `/?notice=` · `/?support=` · `/?stage=` 와 입찰 분석 옵션만 단 `/?view=` · `/?guided=` 는 그리로 넘긴다 — 쿼리는 Next 가 그대로 붙인다.
      // 쿼리 없는 `/` · `/?welcome=0` · `/?mode=` 는 대시보드(통계)다. 와이어프레임 서버(4120)는 `/` 가 와이어프레임이고
      // 공고를 고르면 `/?notice=` 를 쓰므로 넘기지 않는다(새로고침하면 와이어프레임을 떠났다 · 2.1.0 검토).
      ...(isWireframeServer
        ? []
        : ["notice", "support", "stage", "view", "guided"].map((key) => ({ source: "/", has: [{ type: "query" as const, key }], destination: "/analysis", permanent: false }))),
    ];
  },

  async rewrites() {
    // beforeFiles 여야 한다. 배열로 반환하면 afterFiles가 되는데,
    // 그 단계에서는 "/"가 이미 app/page.tsx(Cosmos)에 매칭돼 rewrite가 무시된다.
    return {
      beforeFiles: isWireframeServer
        ? // 이 서버에서도 /wireframe·/cosmos 경로는 그대로 살아 있다. 루트만 덮어쓴다.
          [{ source: "/", destination: "/wireframe" }]
        : [],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
