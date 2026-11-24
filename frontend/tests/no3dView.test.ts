/**
 * 10-31 대표 결정 — 3D 는 화면에서 뺀다(「보기도 힘들고 메리트도 없다」 · 코드 · three.js 는 남김).
 * 입찰 분석 · 지원사업 분석은 목록 · 2D 지도만, 레이더는 2D 평면도만. 옛 주소 ?view=3d 도 2D.
 *
 * 부품(.tsx)은 node 시험이 바로 불러오지 못한다 — 고친 자리의 소스 글을 본다.
 * 실행: `node --import ./tests/_register.mjs --test tests/no3dView.test.ts` (frontend 폴더에서).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOT = join(import.meta.dirname, "..");
const read = (...parts: string[]) => readFileSync(join(ROOT, "src", ...parts), "utf8");

test("입찰 분석 — 보기 단추에 3D 가 없고, 어디서 고른 3D(주소 · 안내 · 발표)도 2D 로 그린다", () => {
  const top = read("components", "cosmos", "TopBar.tsx");
  assert.doesNotMatch(top, /\{ mode: "3d"/);
  const shell = read("components", "cosmos", "DashboardShell.tsx");
  assert.match(shell, /const mapDefault: CosmosViewMode = "2d";/);
  assert.match(shell, /const viewMode: CosmosViewMode = pickedView === "3d" \? "2d" : pickedView;/);
});

test("지원사업 신청 분석 — 「그림으로 보기(3D)」 단추가 없다", () => {
  const body = read("components", "cosmos", "SupportDashboardBody.tsx");
  assert.doesNotMatch(body, /그림으로 보기\(3D\)/);
  assert.match(body, /const showPicture = false;/);
});

test("레이더 — 기본 2D · 3D/2D 전환 단추 없음 · ?view=3d 는 기본(2D)으로", () => {
  const sheet = read("components", "radar", "RadarFilterSheet.tsx");
  assert.match(sheet, /viewMode: "2d",/);
  assert.doesNotMatch(sheet, /title="3D 레이더"/);
  const shell = read("components", "radar", "RadarShell.tsx");
  assert.doesNotMatch(shell, /\(\["3d", "2d"\] as const\)/);
  assert.match(shell, /view: rawView === "2d" \? \(rawView as ViewMode\) : undefined,/);
});

test("사람이 보는 안내 글에 3D 가 남지 않는다(레이더 링크 · 지원사업 링크 · 튜토리얼 · 레이더 읽는 법)", () => {
  assert.doesNotMatch(read("app", "opportunities", "page.tsx"), /3D 레이더로 봅니다/);
  assert.doesNotMatch(read("components", "support", "SupportShell.tsx"), /신청 7단계와 3D/);
  const tutorial = read("lib", "cosmos", "tutorial.ts");
  assert.doesNotMatch(tutorial, /3D 화면 조작|화면을 직접 돌리거나|「2D」 버튼을 눌러/);
  // 튜토리얼은 지도로 시작하므로 과제는 「목록」으로 바꿔 보기다(「지도」를 누르라 하면 변화가 없었다).
  assert.match(tutorial, /「목록」 버튼을 눌러 보세요/);
  const legend = read("components", "radar", "RadarLegend.tsx");
  assert.doesNotMatch(legend, /3D · 2D · 순위 목록|3D는 짧은 제목|좁은 화면의 3D/);
  assert.doesNotMatch(read("components", "cosmos", "GuidedFlowBar.tsx"), /드래그 회전/);
  assert.doesNotMatch(read("components", "cosmos", "SupportDashboardBody.tsx"), /3D에는 한 번만/);
});
