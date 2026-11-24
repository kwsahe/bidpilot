/**
 * `@/…` 별칭을 `src/…` 로 푸는 해석 훅 (테스트 전용).
 *
 * 왜 필요했나: `npm test` 는 `node --test` 로 `.ts` 를 그대로 돌리는데, Node 는
 * tsconfig 의 `paths` 를 모른다. 그래서 지금까지 테스트는 «별칭을 안 쓰는 파일»만
 * 부를 수 있었고(`opportunitySearch.ts` 등), `lib/cosmos/*` 처럼 별칭으로 엮인 순수
 * 로직에는 단위 테스트를 달 수 없었다. prompt_01 §4-B-1 이 요구하는
 * `supportFocusOfStep` 테스트가 그 벽에 걸렸다.
 *
 * 하는 일은 하나다 — 「@/x」를 「<src>/x」로 바꾸고 확장자를 찾아 준다.
 * 번들러도 변환기도 아니다. React 부품(.tsx)은 `import type` 으로만 쓰이므로
 * 타입 제거 단계에서 지워져 여기까지 오지 않는다.
 */

import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "..", "src");

/** 확장자 없는 경로에 붙여 볼 후보. 디렉터리면 index 를 본다. */
const CANDIDATES = ["", ".ts", ".tsx", ".mjs", ".js", "/index.ts", "/index.tsx"];

function resolveOnDisk(basePath) {
  for (const suffix of CANDIDATES) {
    const candidate = basePath + suffix;
    if (suffix !== "" && existsSync(candidate)) return candidate;
    if (suffix === "" && existsSync(candidate) && path.extname(candidate)) return candidate;
  }
  return null;
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    const target = resolveOnDisk(path.join(SRC, specifier.slice(2)));
    if (!target) throw new Error(`별칭을 풀지 못했습니다: ${specifier} (찾은 곳: ${SRC})`);
    return nextResolve(pathToFileURL(target).href, context);
  }

  // 소스는 확장자 없는 상대 경로(`./runStamp`)도 쓴다 — 번들러가 붙여 주던 것이다.
  // Node ESM 은 그러지 않으므로 여기서 같은 후보를 찾아 준다.
  if (specifier.startsWith(".") && context.parentURL?.startsWith("file:")) {
    const parentDir = path.dirname(fileURLToPath(context.parentURL));
    const target = resolveOnDisk(path.resolve(parentDir, specifier));
    if (target) return nextResolve(pathToFileURL(target).href, context);
  }

  // `next/server` 는 패키지 exports 가 없어 Node ESM 이 확장자를 못 붙인다 — 중계 시험(proxyRetry)이 부른다(10-31).
  if (specifier === "next/server") return nextResolve("next/server.js", context);

  return nextResolve(specifier, context);
}
