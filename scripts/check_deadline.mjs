/**
 * D-day 계산 검사 — 화면마다 다른 값이 나오던 문제를 붙잡아 둔다.
 *
 * ## 무엇을 막는가
 *
 * 같은 기업마당 지원사업의 마감이 화면마다 달랐다.
 *
 *   통합 3D 대시보드  D-4      ← `apply_end` 를 날짜 그대로 넘겨 UTC 자정(=그날 09:00 KST)으로 읽음
 *   지원사업 전용 화면 D-5
 *   사업기회 목록      D-5
 *   레이더            D-5
 *
 * 두 가지가 겹친 결과다. (1) 정규화를 거치지 않은 화면이 있었고,
 * (2) 남은 일수를 `Math.ceil((마감 - 지금) / 하루)` 로 세서 **마감 시각**에 값이 끌려갔다.
 * 지금은 `lib/deadline` 한 곳에서 한국시간 달력 날짜 차이로 센다.
 *
 * ## 어떻게 검사하는가
 *
 * 손으로 베낀 사본이 아니라 **화면이 실제로 쓰는 모듈을 그대로 불러** 검사한다.
 * (Node 22 는 .ts 를 직접 읽는다. 사본을 두면 원본이 바뀔 때 조용히 어긋난다 —
 *  scripts/check_radar_axis.mjs 가 그렇게 어긋나 있었다.)
 *
 * 실행:  node scripts/check_deadline.mjs
 */

import {
  dDayText,
  daysUntil,
  effectiveDeadline,
  formatDDay,
  formatDeadlineDateTime,
  formatDeadlineStamp,
  normalizeApplyEnd,
  registrationClosesFirst,
  supportDeadlineIso,
} from "../frontend/src/lib/deadline.ts";
import { readFileSync } from "node:fs";

/** 줄바꿈. 소스에 정규식 리터럴로 적으면 편집 중에 잘 깨져서 상수로 둔다. */
const LINE_BREAK = /\r?\n/;

let failed = 0;
let passed = 0;

function check(name, actual, expected) {
  const ok = actual === expected;
  if (ok) {
    passed += 1;
    console.log(`  ✓ ${name}`);
  } else {
    failed += 1;
    console.log(`  ✗ ${name}\n      기대 ${JSON.stringify(expected)} · 실제 ${JSON.stringify(actual)}`);
  }
}

/** 기준 시각: 2026-09-16(수) 10:00 KST. 오전으로 잡아야 「UTC 자정」 버그가 드러난다. */
const NOW = Date.parse("2026-09-16T10:00:00+09:00");
/** 같은 날 늦은 밤. 시각이 달라도 D-day 는 같아야 한다. */
const NOW_LATE = Date.parse("2026-09-16T23:30:00+09:00");

console.log("A · 기업마당(날짜만) 마감 — 정규화 후 달력 일수");
check("오늘 마감 → D-Day", dDayText({ deadline: normalizeApplyEnd("2026-09-16"), nowMs: NOW }), "D-Day");
check("내일 마감 → D-1", dDayText({ deadline: normalizeApplyEnd("2026-09-17"), nowMs: NOW }), "D-1");
check("나흘 뒤 마감 → D-4", dDayText({ deadline: normalizeApplyEnd("2026-09-20"), nowMs: NOW }), "D-4");
check("어제 마감 → 마감", dDayText({ deadline: normalizeApplyEnd("2026-09-15"), nowMs: NOW }), "마감");

console.log("\nB · 같은 날 안에서 시각이 달라도 값이 같다");
check("오전 10시 기준 D-4", dDayText({ deadline: normalizeApplyEnd("2026-09-20"), nowMs: NOW }), "D-4");
check("밤 11시반 기준 D-4", dDayText({ deadline: normalizeApplyEnd("2026-09-20"), nowMs: NOW_LATE }), "D-4");

console.log("\nC · 나라장터(시각 포함) 마감 — 원본 시각을 보존한 채 같은 규칙으로 센다");
check("나흘 뒤 18시 → D-4", dDayText({ deadline: "2026-09-20T18:00:00+09:00", nowMs: NOW }), "D-4");
check("나흘 뒤 자정 직전 → D-4", dDayText({ deadline: "2026-09-20T23:59:00+09:00", nowMs: NOW }), "D-4");
check("오늘 18시(아직 안 지남) → D-Day", dDayText({ deadline: "2026-09-16T18:00:00+09:00", nowMs: NOW }), "D-Day");
check("오늘 09시(이미 지남) → 마감", dDayText({ deadline: "2026-09-16T09:00:00+09:00", nowMs: NOW }), "마감");
check("UTC 표기도 같은 순간이면 같은 값", dDayText({ deadline: "2026-09-20T09:00:00Z", nowMs: NOW }), "D-4");

console.log("\nD · 날짜 축을 쓰지 않는 접수");
check("상시 접수", dDayText({ deadline: null, periodKind: "always_open", nowMs: NOW }), "상시·예산 소진 시");
check("예산 소진 시", dDayText({ deadline: null, periodKind: "until_budget", nowMs: NOW }), "상시·예산 소진 시");
check("상시인데 날짜가 붙어 있어도 일수를 세지 않는다",
  dDayText({ deadline: normalizeApplyEnd("2026-09-20"), periodKind: "always_open", nowMs: NOW }),
  "상시·예산 소진 시");
check("마감일 미상", dDayText({ deadline: null, periodKind: "unknown", nowMs: NOW }), "마감일 미정");
check("시각을 아직 모를 때(서버 렌더)", dDayText({ deadline: "2026-09-20T18:00:00+09:00", nowMs: null }), "D-…");

console.log("\nE · 네 화면이 같은 값을 낸다 (같은 사업 · 같은 순간)");
{
  const program = { apply_end: "2026-09-20", apply_period_kind: "dated" };
  // 대시보드·지원사업 상세: apply_end → supportDeadlineIso
  const dashboard = dDayText({ deadline: supportDeadlineIso(program), periodKind: program.apply_period_kind, nowMs: NOW });
  const detail = dDayText({ deadline: normalizeApplyEnd(program.apply_end), periodKind: program.apply_period_kind, nowMs: NOW });
  // 목록·레이더: 백엔드가 이미 23:59 KST 로 내려준 UnifiedOpportunity.deadline
  const backendDeadline = "2026-09-20T23:59:00+09:00";
  const list = formatDDay(daysUntil(backendDeadline, NOW));
  const radar = formatDDay(daysUntil(backendDeadline, NOW));
  check("대시보드 = 지원사업 상세", dashboard, detail);
  check("대시보드 = 사업기회 목록", dashboard, list);
  check("대시보드 = 레이더", dashboard, radar);
  check("네 화면 모두 D-4", [dashboard, detail, list, radar].join("/"), "D-4/D-4/D-4/D-4");
}

console.log("\nF · 정규화 자체");
check("날짜만 → 그날 23:59 KST", normalizeApplyEnd("2026-09-20"), "2026-09-20T23:59:00+09:00");
check("이미 시각이 있으면 그대로", normalizeApplyEnd("2026-09-20T18:00:00+09:00"), "2026-09-20T18:00:00+09:00");
check("없으면 null", normalizeApplyEnd(null), null);
check("읽을 수 없는 값은 0 으로 꾸미지 않는다", daysUntil("올해 안", NOW), null);

console.log("\nG · 3D 중앙 카드와 상세 패널이 같은 마감을 같은 글자로 적는다 (0921 §4-E)");
{
  /*
   * 6차가 「미착수」로 남긴 것. 같은 마감 하나가 3D 카드에서는 「2026.09.30」(날짜만),
   * 상세 패널에서는 「2026. 9. 30. 오후 6:00」(12시간제)이었다. 입찰 마감은 10:00 과
   * 14:00 이 다른 일이라 **시각이 빠지면 안 된다.**
   *
   * 3D 라벨은 폭이 좁아 연도만 뺀다 — 그래서 「같은 글자」가 아니라 **「같은 시각」**을 잰다.
   */
  const iso = "2026-09-30T18:00:00+09:00";
  const full = formatDeadlineDateTime(iso);
  const short = formatDeadlineStamp(iso);
  check("상세 패널 — 날짜+시각 24시간", full, "2026. 9. 30. 18:00");
  check("3D 카드 — 연도만 뺀 같은 값", short, "9-30 18:00");
  /*
   * 3D 라벨 모듈은 `.tsx` 라 Node 가 직접 못 읽는다(JSX 변환이 필요하다). 그래서 **원본을
   * 읽어** 자체 포맷터를 두지 않았는지 본다 — 사본이 생기면 두 화면이 다시 갈린다.
   */
  const labels = readFileSync(new URL("../frontend/src/components/cosmos/three/labels.tsx", import.meta.url), "utf8");
  check("3D 카드는 lib/deadline 을 그대로 쓴다", /return formatDeadlineStamp\(iso\)/.test(labels), true);
  // 주석에 적힌 «과거 이야기»는 세지 않는다 — 코드 줄만 본다.
  const labelCode = labels
    .split(/\r?\n/)
    .filter((line) => !/^\s*(\*|\/\/|\/\*)/.test(line))
    .join(" ");
  check("3D 카드에 자체 날짜 포맷터가 없다", /getFullYear\(\)|getMonth\(\)|new Intl\.DateTimeFormat/.test(labelCode), false);
  check("오전/오후를 쓰지 않는다", /오전|오후/.test(full + short), false);
  // 같은 시각을 가리키는가 — 월·일·시·분이 전부 들어 있어야 한다.
  check("월·일·시·분이 겹친다", full.includes("9. 30. 18:00") && short === "9-30 18:00", true);
  check("값이 없으면 지어내지 않는다", formatDeadlineDateTime(null), "마감일 미정");
}

console.log("\nG2 · 마감을 적는 화면이 전부 lib/deadline 을 쓴다 (0922 §4-D-6)");
{
  /*
   * 6차가 「형식이 다르다」고 적었을 때 고친 곳은 3D 라벨 하나였다. 나머지 자리는 그대로
   * `format.ts` 의 범용 날짜시각(12시간제)이나 자체 정규식 포맷터를 쓰고 있었다.
   * **자리를 세어 둔다** — 새로 생긴 화면이 또 자기 포맷터를 만들면 여기서 잡힌다.
   */
  const files = [
    "frontend/src/components/cosmos/Cosmos2D.tsx",
    "frontend/src/components/cosmos/DetailPanel.tsx",
    "frontend/src/components/cosmos/GuidedDetail.tsx",
    "frontend/src/components/cosmos/three/labels.tsx",
    "frontend/src/components/radar/RadarDetail.tsx",
    "frontend/src/components/support/SupportShell.tsx",
    "frontend/src/components/wireframe/panels.tsx",
    // 쉬운 보기(24차 §4-E): 대시보드 공고 카드 · 목록 행 · 지원사업 카드
    "frontend/src/components/cosmos/SimpleDashboard.tsx",
    "frontend/src/app/opportunities/page.tsx",
    "frontend/src/components/support/SupportSimpleView.tsx",
  ];
  const offenders = [];
  for (const file of files) {
    const text = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    const code = text
      .split(LINE_BREAK)
      .filter((line) => !/^\s*(\*|\/\/|\/\*)/.test(line))
      .join(" ");
    // 마감 값에 범용 날짜시각 포맷터를 쓰면 12시간제(「오후 6:00」)가 되어 형식이 갈린다.
    if (/format(Date|DateTime)\(\s*\w*\.?(deadline|apply_end)/.test(code)) offenders.push(file);
  }
  check("마감에 범용 날짜 포맷터를 쓰는 화면", offenders.join(", "), "");
}

console.log("\nH · 실제 데드라인은 등록마감이 이르면 그쪽이다 (0922 §4-B-8)");
{
  const bid = "2026-09-28T14:00:00+09:00";
  const registration = "2026-09-27T18:00:00+09:00";
  check("이른 쪽을 고른다", effectiveDeadline({ qualification: registration, bid }), registration);
  check("등록이 늦으면 입찰마감", effectiveDeadline({ qualification: "2026-09-29T18:00:00+09:00", bid }), bid);
  check("등록이 없으면 입찰마감", effectiveDeadline({ qualification: null, bid }), bid);
  check("둘 다 없으면 null", effectiveDeadline({ qualification: null, bid: null }), null);
  check("두 줄로 적어야 하는가", registrationClosesFirst({ qualification: registration, bid }), true);
  check("같으면 두 줄이 아니다", registrationClosesFirst({ qualification: bid, bid }), false);
}

console.log(`\n${failed === 0 ? "✓" : "✗"} D-day 검사 — 통과 ${passed} · 실패 ${failed}`);
process.exit(failed === 0 ? 0 : 1);
