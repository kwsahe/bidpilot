/**
 * 항공 관제 아이콘 패밀리 — 사업기회 레이더 전용.
 *
 * 24×24 격자, 선 굵기 1.6, 둥근 끝·모서리로 통일한다. 한 가족처럼 보이게 하는 건 결국
 * 격자·굵기·곡률 세 가지라서, 새 아이콘을 더할 때도 이 값을 지킨다.
 *
 * 두 가지 형태로 쓴다.
 *   - `*_PATH` 상수: 레이더 SVG 안에서 `<path d={…} transform=…>` 로 직접 그린다.
 *     스코프는 자기 좌표계(단위 반지름)를 쓰므로 중첩 `<svg>` 를 넣을 수 없다.
 *   - React 컴포넌트: 패널·헤더처럼 평범한 HTML 자리에서 쓴다.
 * 같은 path 를 공유하므로 두 자리의 그림이 어긋나지 않는다.
 *
 * 채움 vs 선:
 *   레이더 마커는 8~16px로 아주 작다. 이 크기에서 선만 쓰면 형태가 뭉개지므로 **채움**을 쓴다.
 *   패널 아이콘은 14px 이상이라 **선**으로 그린다. 둘 다 같은 실루엣이라 가족으로 읽힌다.
 */

import type { CSSProperties, SVGProps } from "react";

// ---------------------------------------------------------------------------
// path 데이터 (24×24 기준, 위쪽이 기수)
// ---------------------------------------------------------------------------

/**
 * 위에서 본 여객기 실루엣. 후퇴익 + 수평미익.
 * 전투기가 아니라 **민항기** 비례다 — 동체가 길고 날개가 완만하게 뒤로 눕는다.
 */
export const PLANE_PATH =
  "M12 2c.95 0 1.55 1.2 1.62 3.3l.08 3.9 7.8 4.98v1.62l-7.8-2.42v4.5l2.9 2.2v1.1L12 19.9l-4.6 1.28v-1.1l2.9-2.2v-4.5l-7.8 2.42v-1.62l7.8-4.98.08-3.9C10.45 3.2 11.05 2 12 2Z";

/*
 * 관제탑 — 안테나 · 처마 · 전망대(캡) · 아래로 벌어지는 기둥 · 바닥.
 *
 * 처음에는 좌우에 전파 아크를 넣었는데, 캡 높이에 팔처럼 붙어 **사람 형상으로 읽혔다**
 * (실제 화면에서 확인). 관제탑을 알아보게 하는 건 전파가 아니라 «처마가 튀어나온 전망대»라서,
 * 아크를 빼고 그 실루엣을 살렸다. 전파가 필요하면 안테나 끝에만 작게 붙인다.
 */
/** 처마 — 캡보다 넓게 내밀어야 관제탑으로 읽힌다. */
export const TOWER_ROOF_PATH = "M7.4 6.4h9.2";
/** 전망대 — 아래로 살짝 좁아지는 사다리꼴. 창문은 그리지 않는다. */
export const TOWER_CAB_PATH = "M8.5 6.4 9.5 10.4h5l1-4Z";
/** 기둥과 바닥 — 아래로 아주 조금 벌어진다. */
export const TOWER_MAST_PATH = "M10.2 10.4 9.6 19.6M13.8 10.4l.6 9.2M8.2 19.6h7.6";
export const TOWER_ANTENNA_PATH = "M12 2.4v4";
/** 안테나 끝의 작은 전파. 기본은 쓰지 않는다 — 중심 마커에서는 형태를 흐린다. */
export const TOWER_WAVE_PATH = "M9.6 3.6a3.4 3.4 0 0 0-.5 1.6M14.4 3.6a3.4 3.4 0 0 1 .5 1.6";

// ---------------------------------------------------------------------------
// 공통 래퍼
// ---------------------------------------------------------------------------

export interface AviationIconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  /** 한 변 px. 기본 16. */
  size?: number;
  /** 선 굵기. 작은 크기에서 굵으면 뭉개지므로 기본 1.6을 유지한다. */
  strokeWidth?: number;
  title?: string;
  style?: CSSProperties;
}

function IconRoot({
  size = 16,
  strokeWidth = 1.6,
  title,
  children,
  ...rest
}: AviationIconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      {...rest}
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// 아이콘
// ---------------------------------------------------------------------------

/**
 * 추적 중인 사업기회 = 한 대의 기체.
 * 출처(나라장터·기업마당)로 **모양을 바꾸지 않는다** — 출처는 섹터 위치와 색으로 구분한다.
 */
export function PlaneTargetIcon({ filled = false, ...props }: AviationIconProps & { filled?: boolean }) {
  return (
    <IconRoot {...props}>
      <path d={PLANE_PATH} fill={filled ? "currentColor" : "none"} />
    </IconRoot>
  );
}

/** 관제 중심 = 현재 회사. 건물이 아니라 「이 시스템의 기준점」을 뜻한다. */
export function ControlTowerIcon({ waves = false, ...props }: AviationIconProps & { waves?: boolean }) {
  return (
    <IconRoot {...props}>
      <path d={TOWER_ANTENNA_PATH} />
      {waves && <path d={TOWER_WAVE_PATH} opacity={0.6} />}
      <path d={TOWER_ROOF_PATH} />
      <path d={TOWER_CAB_PATH} />
      <path d={TOWER_MAST_PATH} />
    </IconRoot>
  );
}

/** 탐지 대상 — 스코프와 스윕선. */
export function RadarSweepIcon(props: AviationIconProps) {
  return (
    <IconRoot {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4" opacity={0.5} />
      <path d="M12 12 19 7.4" />
      <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </IconRoot>
  );
}

/** 마감 임박 — 남은 시간. */
export function DeadlineIcon(props: AviationIconProps) {
  return (
    <IconRoot {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 6.8V12l3.4 2.2" />
    </IconRoot>
  );
}

/** 점수 미확인 — 신호가 잡히지 않은 접점. */
export function SignalLostIcon(props: AviationIconProps) {
  return (
    <IconRoot {...props}>
      <path d="M4.8 14.4a9 9 0 0 1 5-5.4M19.2 14.4a9 9 0 0 0-2.6-3.8" opacity={0.7} />
      <path d="M8.6 15.6a5 5 0 0 1 1.8-1.9M15.4 15.6a5 5 0 0 0-.8-1" opacity={0.7} />
      <circle cx="12" cy="18" r="1.1" fill="currentColor" stroke="none" />
      <path d="M4.4 4.4 19.6 19.6" />
    </IconRoot>
  );
}

/** 마감 포함 — 착륙해 활주로에 선 기체(= 더 이상 추적하지 않는 건). */
export function LandedIcon(props: AviationIconProps) {
  return (
    <IconRoot {...props}>
      <path d="M4 19.4h16" />
      <path
        d="M11.2 5.2c.6-.5 1.4-.3 1.6.5l1.1 3.5 5.5 1.5c.7.2.9.9.4 1.3l-.7.6-6.4-.9-2.3 2.9-2 .3.9-3.6-3.4-.5-1.5 1.6-1.2-.5.9-2.6 1-1.5Z"
        fill="currentColor"
        stroke="none"
        opacity={0.9}
      />
    </IconRoot>
  );
}

/** 자료 수신 상태 — 전파를 받고 있는지. */
export function DataFeedIcon(props: AviationIconProps) {
  return (
    <IconRoot {...props}>
      <circle cx="12" cy="16.8" r="1.6" fill="currentColor" stroke="none" />
      <path d="M8.4 13.6a5 5 0 0 1 7.2 0" />
      <path d="M5.6 10.4a9 9 0 0 1 12.8 0" opacity={0.65} />
    </IconRoot>
  );
}

/** 우선 검토 — 먼저 다룰 기체. 기체 위에 우선 표시를 얹는다. */
export function PriorityContactIcon(props: AviationIconProps) {
  return (
    <IconRoot {...props}>
      <path d={PLANE_PATH} fill="currentColor" stroke="none" opacity={0.9} transform="translate(0 1.4) scale(0.86) translate(1.95 0)" />
      <path d="M6.6 4.6 8.2 2.4l1.6 2.2" />
    </IconRoot>
  );
}
