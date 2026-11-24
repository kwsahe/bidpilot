"use client";

/**
 * 사업기회 레이더 — 관제 스코프(2D SVG).
 *
 * 3D와 **같은 정보**를 그린다. 좌표·크기·색은 `lib/radar/layout.ts` 계산을 그대로 쓴다.
 * 순수 SVG이며 외부 라이브러리를 쓰지 않는다. 렌더 중에 window/document를 만지지 않는다.
 * 키보드 조작은 「순위 목록」 버튼 리스트가 담당한다 (그림은 role="img").
 *
 * 관제 화면 문법을 쓰되 **눈금이 가리키는 값은 전부 실제 데이터**다.
 *
 *  - 반경 = **마감까지 남은 시간의 순서**다. 안쪽일수록 마감이 이르다.
 *    날짜 «수»가 아니라 이 화면에 실제로 있는 마감일들의 순서라, 링은 데이터에서 나오고
 *    없는 날짜의 눈금은 그리지 않는다. 마감일이 없는 항목은 축 밖에 따로 세운다.
 *  - 노드 크기 = 회사 기준 검토 우선순위 **점수**다(이 화면 안에서의 상대 크기).
 *    그 점수에 **마감은 들어가지 않는다**(0922 §4-B-0) — 거리와 크기는 서로 다른 축이다.
 *  - 방향(섹터) = **출처**다. 위 절반이 나라장터, 아래 절반이 기업마당이다.
 *    각도의 절대값은 뜻이 없으므로 방위 숫자(0°·45°…)를 적지 않는다 — 대신 섹터 이름과 건수를 적는다.
 *  - 스윕은 장식이다. 실시간 탐지를 뜻하지 않는다 — 조회 시각은 상단 telemetry 가 따로 적는다.
 *
 * 접점(contact) 표기는 항공 관제의 관례를 따른다: 심볼 + 진행 방향 틱 + 리더선 + 데이터 블록.
 * 데이터 블록에는 순위·점수·마감만 적는다(제목은 한 줄). 전부 적으면 12개가 서로 겹친다.
 */

import type { PointerEvent as ReactPointerEvent } from "react";

import {
  PLANE_PATH,
  TOWER_ANTENNA_PATH,
  TOWER_CAB_PATH,
  TOWER_MAST_PATH,
  TOWER_ROOF_PATH,
} from "@/components/icons/aviation";
import { formatDDay } from "@/lib/cosmos/format";
import { COSMOS_COLORS, withAlpha } from "@/lib/cosmos/theme";
import {
  BLIP_FLOOR,
  RADAR_RADIUS_MAX,
  RADAR_RADIUS_MIN,
  SWEEP_ARC_DEG,
  SWEEP_SECONDS,
  bandLabelAngleAt,
  blipPhaseSeconds,
  radarAriaLabel,
  scoreText,
  shouldShowLabel,
  sweepAlphaAt,
  type RadarNode,
  type RadarSceneProps,
  type SourceSectorSpec,
} from "@/lib/radar/layout";

/** 단위 반지름 1 → SVG 좌표 px. */
const R = 100;
/** 정사각 viewBox — 베젤과 데이터 블록이 잘리지 않을 만큼 여백을 둔다. */
const VIEW = 268;
/** 방위 베젤 반지름 (가장 바깥 링보다 조금 밖). */
const BEZEL = 112;

const SCOPE = "rdr2d";

/** 중심 관제탑 글리프 배율 — 24 격자를 스코프 좌표로 줄인다. 너무 크면 안쪽 노드를 덮는다. */
const TOWER_SCALE = 1.05;

const SCOPED_CSS = `
.${SCOPE}-svg { display: block; touch-action: manipulation; user-select: none; -webkit-user-select: none; }
.${SCOPE}-node { cursor: pointer; }
.${SCOPE}-label {
  paint-order: stroke;
  stroke: ${COSMOS_COLORS.bg};
  stroke-width: 3px;
  stroke-linejoin: round;
  pointer-events: none;
}
@keyframes ${SCOPE}-ping {
  0%   { opacity: 0.9; transform: scale(1); }
  55%  { opacity: 0.2; transform: scale(1.2); }
  100% { opacity: 0.9; transform: scale(1); }
}
.${SCOPE}-ping { transform-box: fill-box; transform-origin: center; animation: ${SCOPE}-ping 2.1s ease-in-out infinite; }
@keyframes ${SCOPE}-beacon {
  0%   { opacity: 0.55; transform: scale(0.94); }
  50%  { opacity: 0.16; transform: scale(1.12); }
  100% { opacity: 0.55; transform: scale(0.94); }
}
.${SCOPE}-beacon { transform-box: fill-box; transform-origin: center; animation: ${SCOPE}-beacon 3.6s ease-in-out infinite; }
`;

/**
 * 스윕 꼬리를 이루는 부채꼴 조각 수.
 *
 * 왜 조각으로 나누는가 — SVG `linearGradient` 로는 **각도 방향** 페이드를 만들 수 없다.
 * 예전에는 선형 그라데이션 한 장을 썼는데, 그건 반경 방향(중심이 어둡고 바깥이 밝은) 페이드라
 * 3D 캔버스의 빔과 **다르게 생긴 그림**이었다. 조각마다 같은 `sweepAlphaAt` 값을 칠하면
 * 두 화면이 같은 모양이 된다. 조각 수가 많을수록 부드럽지만 정적 path 가 늘어난다.
 */
const SWEEP_BANDS = 12;
/** 조각 경계의 하얀 실선(안티에일리어싱 틈)을 없애기 위한 겹침(도). */
const SWEEP_BAND_OVERLAP_DEG = 0.6;

/** 스윕 꼬리 한 조각. 각도는 수학 좌표계(0=3시, +가 반시계)이며 polar() 가 화면 좌표로 뒤집는다. */
function sweepBand(radius: number, degFrom: number, degTo: number): string {
  const [x1, y1] = polar(degFrom, radius);
  const [x2, y2] = polar(degTo, radius);
  return `M 0 0 L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${radius} ${radius} 0 0 0 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
}

/** 각도(도) → SVG 좌표. 수학 좌표계(90°=12시)를 화면 좌표(y 아래)로 뒤집는다. */
function polar(deg: number, radius: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [Math.cos(a) * radius, -Math.sin(a) * radius];
}

/** 섹터 부채꼴 — 중심에서 radius 까지. 출처가 차지하는 방향 범위를 아주 옅게 칠한다. */
function sectorWedge(spec: SourceSectorSpec, radius: number): string {
  const [x1, y1] = polar(spec.centerDeg - spec.spanDeg / 2, radius);
  const [x2, y2] = polar(spec.centerDeg + spec.spanDeg / 2, radius);
  const large = spec.spanDeg > 180 ? 1 : 0;
  return `M 0 0 L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${radius} ${radius} 0 ${large} 0 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
}

/** 섹터가 차지하는 호만 — 베젤 위에 덧그려 경계를 눈에 보이게 한다. */
function sectorArc(spec: SourceSectorSpec, radius: number): string {
  const [x1, y1] = polar(spec.centerDeg - spec.spanDeg / 2, radius);
  const [x2, y2] = polar(spec.centerDeg + spec.spanDeg / 2, radius);
  const large = spec.spanDeg > 180 ? 1 : 0;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${radius} ${radius} 0 ${large} 0 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

export default function RadarScene2D({
  layout,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
  reducedMotion,
  companyName,
  compact,
}: RadarSceneProps) {
  const activeId = hoveredId ?? selectedId;
  const dimOthers = selectedId !== null;
  // 좁은 화면에서는 글자를 조금 키운다 (같은 정보를 더 크게). 외부 점검 UI g — 1366×768 에서 눈금 · 블록 글자가 9~10px 이라 기본도 키움(겹침은 사진으로 확인)
  // 배율을 1.25 · 1.4 로 키워 보았으나 원래 있던 데이터 블록 · 고리 라벨 · 눈금 겹침이 커져 되돌렸다(2.0.4 화면 확인) — 대비는 흐림을 없애 높였다
  const fs = compact ? 1.2 : 1;

  const handleBackground = (event: ReactPointerEvent<SVGRectElement>) => {
    event.preventDefault();
    onSelect(null);
  };

  return (
    <div role="img" aria-label={radarAriaLabel(layout, companyName)} className="h-full w-full">
      <svg
        aria-hidden="true"
        className={`${SCOPE}-svg h-full w-full`}
        viewBox={`${-VIEW / 2} ${-VIEW / 2} ${VIEW} ${VIEW}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <style>{SCOPED_CSS}</style>
        <defs>
          {/* 중심 비컨 — 현재 회사 */}
          <radialGradient id={`${SCOPE}-core`}>
            <stop offset="0%" stopColor={COSMOS_COLORS.cyan} stopOpacity="0.9" />
            <stop offset="45%" stopColor={COSMOS_COLORS.blue} stopOpacity="0.3" />
            <stop offset="100%" stopColor={COSMOS_COLORS.blue} stopOpacity="0" />
          </radialGradient>
          {/* 스코프 바닥 — 가운데가 아주 조금 밝다 */}
          <radialGradient id={`${SCOPE}-floor`}>
            <stop offset="0%" stopColor={COSMOS_COLORS.blue} stopOpacity="0.075" />
            <stop offset="65%" stopColor={COSMOS_COLORS.blue} stopOpacity="0.022" />
            <stop offset="100%" stopColor={COSMOS_COLORS.blue} stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* 배경 클릭 = 선택 해제 */}
        <rect
          x={-VIEW / 2}
          y={-VIEW / 2}
          width={VIEW}
          height={VIEW}
          fill="transparent"
          onPointerDown={handleBackground}
        />

        {/* ---- 스코프 바닥 ---- */}
        <circle cx={0} cy={0} r={RADAR_RADIUS_MAX * R} fill={`url(#${SCOPE}-floor)`} pointerEvents="none" />

        {/* ---- 출처 섹터 — 레이더의 «방향»이 뜻하는 것 ---- */}
        <g pointerEvents="none">
          {layout.sectors.map((sector) => (
            <path
              key={sector.sourceType}
              d={sectorWedge(sector.spec, RADAR_RADIUS_MAX * R)}
              fill={sector.color}
              fillOpacity={sector.count === 0 ? 0.02 : 0.045}
            />
          ))}
          {/* 섹터 경계선 — 여기서 출처가 갈린다 */}
          {layout.sectors.flatMap((sector) =>
            [-1, 1].map((side) => {
              const deg = sector.spec.centerDeg + (side * sector.spec.spanDeg) / 2;
              const a = (deg * Math.PI) / 180;
              return (
                <line
                  key={`${sector.sourceType}${side}`}
                  x1={0}
                  y1={0}
                  x2={Math.cos(a) * RADAR_RADIUS_MAX * R}
                  y2={-Math.sin(a) * RADAR_RADIUS_MAX * R}
                  stroke={sector.color}
                  strokeWidth={0.5}
                  strokeOpacity={0.35}
                />
              );
            }),
          )}
          {/* 눈금 축 — 섹터 사이 빈틈. 왼쪽엔 띠 이름, 오른쪽엔 D-day 눈금이 놓인다 */}
          <line
            x1={-RADAR_RADIUS_MAX * R}
            y1={0}
            x2={RADAR_RADIUS_MAX * R}
            y2={0}
            stroke={COSMOS_COLORS.borderStrong}
            strokeWidth={0.5}
            strokeOpacity={0.6}
          />
        </g>

        {/* ---- 스윕 (장식 · reduced motion 이면 그리지 않는다) ---- */}
        {!reducedMotion && (
          <g pointerEvents="none">
            <g>
              {/* 꼬리 — 선행 엣지(각도 0)에서 뒤로 갈수록 옅어진다. 알파식은 3D와 같은 것을 쓴다. */}
              {Array.from({ length: SWEEP_BANDS }, (_, index) => {
                const t0 = index / SWEEP_BANDS;
                const t1 = (index + 1) / SWEEP_BANDS;
                return (
                  <path
                    key={index}
                    d={sweepBand(
                      RADAR_RADIUS_MAX * R,
                      t0 * SWEEP_ARC_DEG,
                      t1 * SWEEP_ARC_DEG + SWEEP_BAND_OVERLAP_DEG,
                    )}
                    fill={COSMOS_COLORS.cyan}
                    fillOpacity={sweepAlphaAt((t0 + t1) / 2)}
                  />
                );
              })}
              <line
                x1={0}
                y1={0}
                x2={RADAR_RADIUS_MAX * R}
                y2={0}
                stroke={COSMOS_COLORS.cyan}
                strokeWidth={0.9}
                strokeOpacity={0.5}
              />
              <animateTransform
                attributeName="transform"
                type="rotate"
                from="0 0 0"
                to="360 0 0"
                dur={`${SWEEP_SECONDS}s`}
                repeatCount="indefinite"
              />
            </g>
          </g>
        )}

        {/* ---- 반경 눈금 = 점수 링 ---- */}
        {layout.rings.map((ring, index) => {
          // 세 라벨을 한 칸씩 벌린다 — 같은 방향에 두면 서로 겹친다.
          const bandAngle = bandLabelAngleAt(layout, index);
          const lx = Math.cos(bandAngle) * ring.labelRadius * R;
          const ly = -Math.sin(bandAngle) * ring.labelRadius * R;
          return (
            <g key={ring.label} pointerEvents="none">
              <circle
                cx={0}
                cy={0}
                r={ring.radius * R}
                fill="none"
                stroke={COSMOS_COLORS.borderStrong}
                strokeWidth={0.8}
                strokeDasharray="3 4"
              />
              <text
                className={`${SCOPE}-label`}
                x={lx}
                y={ly + 2}
                textAnchor="middle"
                fontSize={7 * fs}
                fill={COSMOS_COLORS.textMuted}
              >
                {ring.label}
              </text>
            </g>
          );
        })}

        {/* ---- 반경 눈금 (3시 방향 빈틈 = 시간 축) ---- */}
        <g pointerEvents="none">
          {layout.rings.map((ring) => (
            <text
              key={ring.days}
              className={`${SCOPE}-label`}
              x={ring.radius * R}
              y={-3.5}
              textAnchor="middle"
              fontSize={5.6 * fs}
              fill={COSMOS_COLORS.textMuted}
              fontFamily="ui-monospace, monospace"
            >
              {ring.tick}
            </text>
          ))}
          {/* 축의 안쪽 끝 = 이 화면에서 가장 급한 마감. 실제 값을 적는다 — 없는 눈금은 적지 않는다. */}
          {layout.deadlineAxis.stops.length > 0 && (
            <text
              className={`${SCOPE}-label`}
              x={RADAR_RADIUS_MIN * R}
              y={-3.5}
              textAnchor="middle"
              fontSize={5.2 * fs}
              fill={COSMOS_COLORS.textMuted}
              fontFamily="ui-monospace, monospace"
            >
              {formatDDay(layout.deadlineAxis.stops[0])}
            </text>
          )}
        </g>

        {/* ---- 섹터 베젤 + 출처 이름 (각도 숫자는 적지 않는다 — 방향의 뜻은 «출처»다) ---- */}
        <g pointerEvents="none">
          <circle cx={0} cy={0} r={BEZEL} fill="none" stroke={COSMOS_COLORS.border} strokeWidth={0.7} />
          {layout.sectors.map((sector) => {
            const a = (sector.spec.centerDeg * Math.PI) / 180;
            const lx = Math.cos(a) * (BEZEL + 9);
            // 10-31 최종 점검 — 위쪽 섹터(나라장터)는 두 줄이 원 쪽으로 쌓여 「n건」이 바깥 원 선에 걸렸다 → 위쪽이면 두 줄을 원 밖으로 올린다(글자 크기 그대로)
            const ly = -Math.sin(a) * (BEZEL + 9) - (Math.sin(a) > 0 ? 4.5 : 0);
            // 섹터 호 — 베젤 위에 그 출처가 차지하는 구간을 굵게 덧그린다
            return (
              <g key={sector.sourceType} opacity={sector.count === 0 ? 0.4 : 1}>
                <path
                  d={sectorArc(sector.spec, BEZEL)}
                  fill="none"
                  stroke={sector.color}
                  strokeWidth={1.6}
                  strokeOpacity={0.55}
                  strokeLinecap="round"
                />
                <text
                  className={`${SCOPE}-label`}
                  x={lx}
                  y={ly + 2}
                  textAnchor="middle"
                  fontSize={6.4 * fs}
                  fontWeight={600}
                  fill={sector.color}
                >
                  {compact ? sector.spec.label.split(" ")[0] : sector.spec.label}
                </text>
                <text
                  className={`${SCOPE}-label`}
                  x={lx}
                  y={ly + 9.5}
                  textAnchor="middle"
                  fontSize={5.4 * fs}
                  fill={COSMOS_COLORS.textMuted}
                  fontFamily="ui-monospace, monospace"
                >
                  {sector.count}건
                </text>
              </g>
            );
          })}
        </g>

        {/* ---- 선택 항목 ↔ 중심 연결선 ---- */}
        {layout.nodes
          .filter((node) => node.id === selectedId)
          .map((node) => (
            <line
              key={`link-${node.id}`}
              x1={0}
              y1={0}
              x2={node.x * R}
              y2={-node.y * R}
              stroke={node.color}
              strokeWidth={1.4}
              strokeOpacity={0.75}
              strokeDasharray="2 3"
              pointerEvents="none"
            />
          ))}

        {/* ---- 중심 = 관제탑 (현재 회사). 이름표는 노드 위에 그리도록 맨 뒤로 ---- */}
        <g pointerEvents="none">
          <circle
            className={reducedMotion ? undefined : `${SCOPE}-beacon`}
            cx={0}
            cy={0}
            r={30}
            fill={`url(#${SCOPE}-core)`}
          />
          <circle cx={0} cy={0} r={13} fill={withAlpha(COSMOS_COLORS.blue, 15)} stroke={COSMOS_COLORS.blue} strokeWidth={0.9} />
          {/* 관제탑 글리프 — 건물이 아니라 「이 시스템의 기준점」을 뜻한다 */}
          <g
            transform={`translate(0 0) scale(${TOWER_SCALE}) translate(-12 -12)`}
            fill="none"
            stroke={COSMOS_COLORS.cyan}
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d={TOWER_ANTENNA_PATH} />
            <path d={TOWER_ROOF_PATH} />
            <path d={TOWER_CAB_PATH} fill={withAlpha(COSMOS_COLORS.cyan, 22)} />
            <path d={TOWER_MAST_PATH} />
          </g>
        </g>

        {/* ---- 중심 이름표 — 45차 M18 접점 밑으로(맨 위에 두니 가운데 가까운 1위가 이 상자에 가렸다) ---- */}
        <g pointerEvents="none">
          <rect
            x={-48}
            y={16}
            width={96}
            height={22}
            rx={3}
            fill={withAlpha(COSMOS_COLORS.bg, 92)}
            stroke={COSMOS_COLORS.borderStrong}
            strokeWidth={0.6}
          />
          <text x={0} y={25.5} textAnchor="middle" fontSize={8.5} fontWeight={600} fill={COSMOS_COLORS.textPrimary}>
            {companyName}
          </text>
          <text
            x={0}
            y={33.5}
            textAnchor="middle"
            fontSize={5.6}
            fill={COSMOS_COLORS.textMuted}
            letterSpacing="0.1em"
          >
            우리 회사 (가운데 기준)
          </text>
        </g>
        {/* ---- 접점(contact) — 45차 M18 높은 순위 · 선택 · hover 를 나중에(위에) 그린다 ---- */}
        {paintOrder(layout.nodes, selectedId, activeId).map((node) => (
          <Contact
            key={node.id}
            node={node}
            selected={node.id === selectedId}
            active={node.id === activeId}
            dim={dimOthers && node.id !== selectedId && node.id !== activeId}
            showBlock={shouldShowLabel(node, activeId, compact)}
            reducedMotion={reducedMotion}
            fs={fs}
            onSelect={onSelect}
            onHover={onHover}
          />
        ))}

      </svg>
    </div>
  );
}

/** SVG 는 나중에 그린 것이 위다 — 낮은 순위부터, 선택 · hover 는 맨 끝(45차 M18 「3위 · 59」가 「2위 · 60」을 덮었다). */
export function paintOrder<T extends { id: string; rank: number }>(nodes: T[], selectedId: string | null, activeId: string | null): T[] {
  const weight = (node: T) => (node.id === activeId ? 2 : node.id === selectedId ? 1 : 0);
  return [...nodes].sort((a, b) => weight(a) - weight(b) || b.rank - a.rank);
}

// ---------------------------------------------------------------------------
// 접점 하나 — 심볼 + 진행 방향 틱 + 리더선 + 데이터 블록
// ---------------------------------------------------------------------------

interface ContactProps {
  node: RadarNode;
  selected: boolean;
  active: boolean;
  dim: boolean;
  showBlock: boolean;
  reducedMotion: boolean;
  fs: number;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
}

function Contact({ node, selected, active, dim, showBlock, reducedMotion, fs, onSelect, onHover }: ContactProps) {
  const cx = node.x * R;
  const cy = -node.y * R;
  // 선택한 항목만 키운다 — 강조는 선택 상태 전용이다.
  const r = node.unitRadius * R * (selected ? 1.28 : 1);
  const opacity = dim ? 0.35 : 1;

  // 바깥 방향 단위벡터 — 방향 틱과 데이터 블록을 중심 반대쪽으로 민다.
  const away = Math.hypot(node.x, node.y) || 1;
  const ux = node.x / away;
  const uy = -node.y / away;

  const ringWidth = 0.8 + node.urgencyStrength * 2;
  const urgentColor = node.urgency === "urgent" ? COSMOS_COLORS.red : COSMOS_COLORS.amber;

  // 기체를 중심 쪽으로 돌린다. 기본 기수는 위(0,-1)이므로 그 기준 회전각을 구한다.
  const inboundDeg = (Math.atan2(-ux, uy) * 180) / Math.PI;
  // 24 격자 아이콘을 마커 크기에 맞춘다. 날개폭이 지름의 약 1.2배가 되도록.
  const planeScale = (r * 2.4) / 24;

  // 기체 채움 불투명도. 깜빡임은 이 값과 바닥값 사이에서만 흔든다.
  const baseFill = active || selected ? 1 : 0.88;
  const blipFloor = (baseFill * BLIP_FLOOR).toFixed(3);

  // 데이터 블록은 리더선 끝에 붙는다. 오른쪽 반원이면 왼쪽 정렬, 왼쪽 반원이면 오른쪽 정렬.
  const leadFrom = r + 2.5;
  const leadTo = r + 11;
  const bx = cx + ux * leadTo;
  const by = cy + uy * leadTo;
  const anchor = ux >= 0 ? "start" : "end";
  const pad = ux >= 0 ? 2.5 : -2.5;

  return (
    <g
      className={`${SCOPE}-node`}
      opacity={opacity}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(node.id);
      }}
      onPointerEnter={() => onHover(node.id)}
      onPointerLeave={() => onHover(null)}
    >
      {/* 마감 임박 링 (마감일이 없으면 그리지 않는다) */}
      {node.urgencyStrength > 0 && (
        <circle
          className={reducedMotion || node.urgency !== "urgent" ? undefined : `${SCOPE}-ping`}
          cx={cx}
          cy={cy}
          r={r + 4}
          fill="none"
          stroke={urgentColor}
          strokeWidth={ringWidth}
          strokeOpacity={0.4 + node.urgencyStrength * 0.5}
        />
      )}

      {/* 선택 레티클 — 네 귀퉁이 괄호 */}
      {selected && (
        <g pointerEvents="none">
          {[
            [-1, -1],
            [1, -1],
            [-1, 1],
            [1, 1],
          ].map(([sx, sy]) => {
            const d = r + 7;
            const arm = 3.2;
            return (
              <path
                key={`${sx}${sy}`}
                d={`M ${cx + sx * d} ${cy + sy * d - sy * arm} L ${cx + sx * d} ${cy + sy * d} L ${cx + sx * d - sx * arm} ${cy + sy * d}`}
                fill="none"
                stroke={node.color}
                strokeWidth={1.1}
                strokeLinecap="round"
              />
            );
          })}
        </g>
      )}

      {/*
        기체 심볼 — 출처와 무관하게 **모두 같은 모양**이다.
        출처는 섹터(위/아래)와 색이 나르므로, 여기서 모양까지 나누면 같은 정보를 세 번 말하게 되고
        「나라장터는 원, 기업마당은 다이아몬드」처럼 서로 다른 사물로 읽힌다.

        기수는 중심(관제탑)을 향하도록 돌린다. 이건 **데이터가 아니라** 구도다 — 항목마다
        진행 방향이 다른 것처럼 보이지 않도록 전부 안쪽을 향하게 고정했다.
      */}
      <path
        d={PLANE_PATH}
        transform={`translate(${cx} ${cy}) rotate(${inboundDeg}) scale(${planeScale}) translate(-12 -12)`}
        fill={node.color}
        fillOpacity={baseFill}
        stroke={active || selected ? COSMOS_COLORS.textPrimary : "none"}
        strokeWidth={active || selected ? 0.7 / planeScale : 0}
        strokeLinejoin="round"
      >
        {/*
          깜빡임 — 스윕이 이 접점을 지나는 순간 밝아졌다가 사그라든다.

          2D 에는 JS 시계가 없으므로 SMIL 로 낸다. 스윕(animateTransform)과 이 애니메이션은
          **같은 SVG 타임라인**에서 시작하므로, `begin` 을 「빔이 이 각도를 지나는 시각」으로 주면
          3D 와 같은 순간에 같은 접점이 밝아진다 (계산은 layout.blipPhaseSeconds 한 곳에서 한다).

          **밝기만** 흔든다 — 마커 크기는 실제 값을 뜻하므로 애니메이션으로 키우지 않는다.
          바닥값(BLIP_FLOOR) 아래로 내려가지 않아 접점이 사라진 것처럼 보이지 않는다.
        */}
        {!reducedMotion && !dim && (
          <animate
            attributeName="fill-opacity"
            begin={`${blipPhaseSeconds(node.angle).toFixed(2)}s`}
            dur={`${SWEEP_SECONDS}s`}
            repeatCount="indefinite"
            values={`${baseFill};${(baseFill * 0.84).toFixed(3)};${blipFloor};${blipFloor}`}
            keyTimes="0;0.08;0.26;1"
            calcMode="spline"
            keySplines="0.4 0 0.6 1;0.4 0 0.6 1;0 0 1 1"
          />
        )}
      </path>

      {/* 순위 — 기체 안에는 넣을 수 없으므로 상위 3건만 옆에 작게 (나머지는 데이터 블록·목록에서).
          숫자는 **같은 출처 안 순위** — 섞은 자리 번호면 기업마당 1위가 「2」였다 (27차 RDR-06). 출처는 섹터 · 색이 나른다. */}
      {node.index < 3 && (
        <text
          x={cx - ux * (r + 5)}
          y={cy - uy * (r + 5) + 2.4}
          textAnchor="middle"
          fontSize={6.4}
          fontWeight={700}
          fill={COSMOS_COLORS.textPrimary}
          pointerEvents="none"
          className={`${SCOPE}-label`}
        >
          {node.sourceRank}
        </text>
      )}

      {/* 리더선 + 데이터 블록 */}
      {showBlock && (
        <g pointerEvents="none">
          <line
            x1={cx + ux * leadFrom}
            y1={cy + uy * leadFrom}
            x2={bx}
            y2={by}
            stroke={node.color}
            strokeWidth={0.6}
            strokeOpacity={0.6}
          />
          {/*
            1행: 순위 · 점수 · 마감.
            관제 데이터 블록은 짧은 코드만 담는다 — 제목까지 늘 띄우면 안쪽 띠에 몰린 항목끼리
            블록이 겹쳐 읽을 수 없게 된다. 제목은 바로 옆 「추적 중인 사업기회」에 전부 있고,
            여기서는 마우스를 올리거나 고른 항목만 펼친다.
          */}
          <text
            className={`${SCOPE}-label`}
            x={bx + pad}
            y={by + 2}
            textAnchor={anchor}
            fontSize={5.8 * fs}
            fontFamily="ui-monospace, monospace"
            fill={active || selected ? COSMOS_COLORS.textPrimary : COSMOS_COLORS.textSecondary}
          >
            {`${node.sourceRank}위 · ${scoreText(node.item.company_priority_score)} · ${node.deadlineLabel}`}
          </text>
          {/* 2행: 제목 — hover·선택일 때만 펼친다 · 줄 간격도 글자 배율만큼(배율 1이면 예전 9.4 · 외부 점검 UI g — 키운 글자가 1행에 닿지 않게) */}
          {(active || selected) && (
            <text
              className={`${SCOPE}-label`}
              x={bx + pad}
              y={by + 2 + 7.4 * fs}
              textAnchor={anchor}
              fontSize={6.2 * fs}
              fill={COSMOS_COLORS.textPrimary}
            >
              {node.shortTitle}
            </text>
          )}
        </g>
      )}

      {/* 점수 미산정은 데이터 블록의 「미산정」이 말한다 — 블록이 늘 떠 있어(ISSUE-109) 따로 그리던 분기는 한 번도 나오지 않아 뺐다 (27차 RDR-23). */}
    </g>
  );
}
