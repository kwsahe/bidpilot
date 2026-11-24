/**
 * 레이더 축 검사 — 실데이터로 불변식과 분포를 확인한다.
 *
 * 프론트엔드에는 테스트 러너가 없다. 그렇다고 좌표 계산을 아무것도 안 붙잡고 둘 수는 없어서,
 * 로컬 백엔드의 실제 목록을 가져와 `lib/radar/layout.ts` 와 **같은 규칙**을 다시 계산해
 * 두 불변식과 축 사용률을 검사한다.
 *
 *   단조 — 남은 일수가 적을수록 반지름이 작다(안쪽이다)
 *   동치 — 축 위 두 항목의 반지름이 같다 ⟺ 남은 일수가 같다
 *
 * 실행:  node scripts/check_radar_axis.mjs
 *        node scripts/check_radar_axis.mjs --limit 12 --sort deadline
 *
 * 주의: 반지름 상수는 layout.ts 와 **손으로 맞춘 사본**이다. layout.ts 를 고치면 여기도 고친다.
 * 남은 일수 계산만은 사본을 두지 않고 lib/deadline 을 직접 불러 쓴다 (Node 22 는 .ts 를 읽는다).
 */

import { daysUntil } from "../frontend/src/lib/deadline.ts";

const API = process.env.BIDPILOT_API ?? "http://127.0.0.1:8110";
const RADAR_RADIUS_MIN = 0.34;
const RADAR_AXIS_END = 0.86;
const RADAR_RADIUS_UNDATED = 0.94;
const RADAR_RADIUS_CLOSED = 1;

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

/** layout.buildDeadlineAxis 와 같은 규칙. */
function buildDeadlineAxis(days, closed) {
  const values = [...new Set(days.filter((d, i) => d !== null && d >= 0 && !closed[i]))].sort(
    (a, b) => a - b,
  );
  const n = values.length;
  if (n === 0) return { stops: [], radii: [] };
  if (n === 1) return { stops: values, radii: [(RADAR_RADIUS_MIN + RADAR_AXIS_END) / 2] };
  const span = RADAR_AXIS_END - RADAR_RADIUS_MIN;
  return { stops: values, radii: values.map((_, i) => RADAR_RADIUS_MIN + (span * i) / (n - 1)) };
}

/** layout.radiusForDeadline 와 같은 규칙. */
function radiusForDeadline(days, closed, axis) {
  if (closed || (days !== null && days < 0)) return RADAR_RADIUS_CLOSED;
  if (days === null) return RADAR_RADIUS_UNDATED;
  const { stops, radii } = axis;
  if (stops.length === 0) return RADAR_RADIUS_UNDATED;
  if (days <= stops[0]) return radii[0];
  if (days >= stops[stops.length - 1]) return radii[radii.length - 1];
  for (let i = 0; i < stops.length - 1; i += 1) {
    if (days <= stops[i + 1]) {
      const t = (days - stops[i]) / (stops[i + 1] - stops[i]);
      return radii[i] + (radii[i + 1] - radii[i]) * t;
    }
  }
  return radii[radii.length - 1];
}

/**
 * 남은 일수는 **화면이 쓰는 그 함수**를 그대로 불러 쓴다 (아래 import).
 *
 * 예전에는 여기에 `Math.ceil((마감 - 지금) / 하루)` 사본을 두었다. 그 뒤 lib/deadline 이
 * 한국시간 달력 날짜 차이로 바뀌면서 사본만 옛 규칙으로 남아, 이 검사가 화면과 다른 값을
 * 재고 있었다. 사본을 지우고 원본을 불러 그 틈을 없앤다.
 */

const limit = arg("limit", "20");
const sort = arg("sort", "priority");
const url = `${API}/api/business-opportunities?organization_id=org-sample&sort=${sort}&limit=${limit}`;

const response = await fetch(url);
if (!response.ok) {
  console.error(`백엔드 응답 ${response.status} — 로컬 백엔드가 떠 있는지 확인하세요 (${API})`);
  process.exit(2);
}
const data = await response.json();
const nowMs = Date.now();
const items = data.items;
const days = items.map((i) => daysUntil(i.deadline, nowMs));
const closed = items.map((i) => Boolean(i.closed));
const axis = buildDeadlineAxis(days, closed);
const radii = items.map((_, i) => radiusForDeadline(days[i], closed[i], axis));

console.log(`정렬 ${sort} · ${items.length}건 · 사다리 ${axis.stops.length}칸  [${axis.stops.join(", ")}]`);
console.log("");

let failures = 0;
const onAxis = items
  .map((item, i) => ({ item, days: days[i], radius: radii[i], closed: closed[i] }))
  .filter((n) => !n.closed && n.days !== null);

// 불변식 1 — 단조
for (const a of onAxis) {
  for (const b of onAxis) {
    if (a.days < b.days && a.radius > b.radius + 1e-9) {
      console.error(`✗ 단조 위반: D-${a.days}(r ${a.radius.toFixed(3)}) 가 D-${b.days}(r ${b.radius.toFixed(3)}) 보다 바깥`);
      failures += 1;
    }
  }
}

// 불변식 2 — 동치
for (const a of onAxis) {
  for (const b of onAxis) {
    const sameRadius = Math.abs(a.radius - b.radius) < 1e-9;
    const sameDays = a.days === b.days;
    if (sameRadius !== sameDays) {
      console.error(`✗ 동치 위반: D-${a.days} r ${a.radius.toFixed(4)} vs D-${b.days} r ${b.radius.toFixed(4)}`);
      failures += 1;
    }
  }
}

// 축 사용률
const usable = RADAR_AXIS_END - RADAR_RADIUS_MIN;
const axisRadii = onAxis.map((n) => n.radius);
const used = axisRadii.length > 1 ? Math.max(...axisRadii) - Math.min(...axisRadii) : 0;
const pct = ((used / usable) * 100).toFixed(1);

console.log(`축 사용률: ${pct}%  (${axisRadii.length}건이 축 위)`);
console.log(`축 밖: 마감일 없음 ${items.filter((it, i) => !closed[i] && days[i] === null).length}건 · 마감됨 ${closed.filter(Boolean).length}건`);
console.log("");
console.log("D-day  반지름  제목");
console.log("-".repeat(70));
for (const n of [...onAxis].sort((a, b) => a.days - b.days)) {
  console.log(`${String(n.days).padStart(5)}  ${n.radius.toFixed(3)}  ${n.item.title.slice(0, 46)}`);
}

console.log("");
if (failures > 0) {
  console.error(`✗ 불변식 위반 ${failures}건`);
  process.exit(1);
}
console.log("✓ 단조·동치 불변식 통과");
if (axisRadii.length > 1 && Number(pct) < 99.9) {
  console.error(`✗ 축 사용률이 100% 가 아니다 (${pct}%) — 순서 축은 언제나 양 끝을 써야 한다`);
  process.exit(1);
}
console.log("✓ 축 사용률 100%");
