/**
 * 3D 노드 라벨에 **같은 건수가 두 번 나오지 않는다** (ISSUE-124 · prompt_04 §3-A-5).
 *
 * 실행: `npm test` (frontend 폴더에서).
 *
 * ## 무엇이 틀렸나
 *
 * 담당자 화면에 「과업 17 17건」이 떴다. 짧은 라벨의 이름(`short`)에 건수를 붙여 두고,
 * 그 뒤에 상태 조각(`shortBadge`)이 다시 「17건」을 붙였기 때문이다. hover 하면 긴 라벨이
 * 「과업 17건 17건」이었다 — 검수 보고에는 짧은 라벨만 적혀 있었지만 둘 다였다.
 *
 * 규칙은 하나다: **이름은 `short`, 건수는 상태 조각.** 나눠 두면 이름이 길어 잘릴 때도
 * (`truncate(node.short, 14)`) 건수는 남는다. 긴 라벨은 건수가 든 `label` 을 그대로 쓰므로
 * 조각을 더하지 않는다.
 *
 * ## 왜 원문(소스 텍스트)을 보는가
 *
 * 이 문자열을 만드는 자리는 `buildCosmosGraph`·`buildSupportGraph` 안이고, 부르려면 RFP
 * 분석 결과 한 벌이 필요하다. 그리고 고치기 전까지 **이 문자열을 지키는 테스트가 하나도
 * 없었다** — 라벨을 아무렇게나 고쳐도 62개가 전부 통과했다. 가장 싼 그물부터 건다.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");

const GRAPHS = [
  ["graph.ts", read("../src/lib/cosmos/graph.ts")],
  ["supportGraph.ts", read("../src/lib/cosmos/support/supportGraph.ts")],
] as const;

const GROUP_KINDS = /kind: "(?:requirement-group|finding-group)"/g;
const GROUP_WITH_LABEL = /kind: "(?:requirement-group|finding-group)",\s*\n\s*label: `([^`]*)`/g;

test("짧은 라벨은 수치로 끝나지 않는다 — 건수는 상태 조각이 맡는다", () => {
  for (const [name, source] of GRAPHS) {
    for (const match of source.matchAll(/short: `([^`]*)`/g)) {
      assert.ok(
        !/\$\{[^}]*\}$/.test(match[1]),
        `${name}: 짧은 라벨이 수치 보간으로 끝난다 — 「${match[1]}」. ` +
          "상태 조각이 같은 건수를 또 붙여 「과업 17 17건」이 된다.",
      );
    }
  }
});

test("묶음 노드의 긴 이름(label)에는 건수가 있다", () => {
  for (const [name, source] of GRAPHS) {
    const kinds = [...source.matchAll(GROUP_KINDS)].length;
    const labels = [...source.matchAll(GROUP_WITH_LABEL)];
    // 짝을 못 찾으면 «조용히 통과»한다 — 그러면 검사가 아니다.
    assert.equal(labels.length, kinds, `${name}: 묶음 ${kinds}개 중 ${labels.length}개만 label 을 찾았다`);
    assert.ok(kinds > 0, `${name}: 묶음 노드를 찾지 못했다`);
    for (const match of labels) {
      assert.match(match[1], /건`?$/, `${name}: 묶음 label 에 건수가 없다 — 「${match[1]}」`);
    }
  }
});

test("묶음 긴 라벨은 건수 조각을 덧붙이지 않는다", () => {
  const nodes = read("../src/components/cosmos/three/nodes.tsx");
  /* JSX 로 그리는 `{node.groupCount}건` 만 본다. 상태 조각의 템플릿 문자열
     (`${node.groupCount}건`)은 **건수를 맡은 쪽**이므로 걸리면 안 된다 — 앞에 `$` 가
     붙는지로 가른다. (이 구분을 빼먹어 이 검사가 처음에 거짓 실패를 냈다.) */
  assert.doesNotMatch(
    nodes,
    /(?<!\$)\{node\.groupCount\}건/,
    "묶음 label 이 이미 「과업 17건」처럼 건수로 끝난다 — 조각을 더하면 「과업 17건 17건」이 된다.",
  );
});
