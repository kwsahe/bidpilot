"use client";

/**
 * 공통 오버레이 — 시트(드로어·바텀시트)와 팝오버.
 *
 * 화면을 단순하게 만들면서도 **정보를 삭제하지 않기 위한** 그릇이다.
 * 기본 화면에서 뺀 설명·고급 필터·데이터 상태는 지우지 말고 여기로 옮긴다.
 *
 * 접근성 규칙 (「?」 대화상자 WhyBidPilotDialog 도 같은 두 훅을 쓴다)
 * - 열리면 첫 요소로 포커스를 옮기고, 닫히면 열었던 버튼으로 되돌린다.
 * - Escape 로 닫는다. 배경을 눌러도 닫힌다(배경 「닫기」는 Tab 정지점이 아니다).
 * - 시트 · 가운데 대화상자는 `role="dialog" aria-modal="true"` 이고 Tab 이 밖으로 나가지 않는다.
 * - 팝오버는 비모달이라 `aria-expanded` 로 상태를 알린다.
 * - 좁은 화면에서 시트는 아래에서 올라오는 bottom sheet 가 된다 (터치 영역 확보).
 */

import { createPortal } from "react-dom";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

/**
 * 열려 있는 동안 Escape 로 닫고, 닫힐 때 이전 포커스로 되돌린다.
 *
 * `onClose` 는 ref 로 든다 — 부르는 쪽은 대개 렌더마다 새 화살표 함수를 넘긴다. 의존성에 두면 시트 안에서
 * 체크박스 하나만 눌러도(부모가 다시 그려짐) 정리 함수가 돌아 초점이 시트 뒤 「연 단추」로 튀었다 (CMN-08 · OPP-13).
 */
export function useDismissable(open: boolean, onClose: () => void) {
  const restoreRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      restoreRef.current?.focus?.({ preventScroll: true });
    };
  }, [open]);
}

// ---------------------------------------------------------------------------
// Sheet — 데스크톱·태블릿은 우측 드로어, 모바일은 바텀시트
// ---------------------------------------------------------------------------

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  /** 시트 제목 (aria-labelledby 로 연결된다) */
  title: string;
  /** 제목 아래 한 줄 설명 */
  description?: ReactNode;
  children: ReactNode;
  /** 하단 고정 영역 (적용·닫기 버튼 등) */
  footer?: ReactNode;
  /** 넓은 화면에서의 폭. 기본 380px */
  width?: string;
}

export function Sheet({ open, onClose, title, description, children, footer, width = "380px" }: SheetProps) {
  const headingId = useId();
  useDismissable(open, onClose);
  // aria-modal 인데 Tab 이 시트 뒤 목록으로 나갔다 — 가운데 대화상자와 같은 가둠 (CMN-23). 첫 초점은 머리의 ✕.
  const boxRef = useFocusTrap(open);

  if (!open || typeof document === "undefined") return null;

  // body 로 그린다(45차 H1) — 머리(`backdrop-blur`)처럼 filter 가 있는 조상 안에서는 `fixed` 가 화면이 아니라 그 조상에 붙어
  // 시트가 머리 높이로 잘렸다(비밀번호 바꾸기 창의 입력 칸이 안 보임). 「?」 대화상자와 같은 방식.
  // 쉬운 보기 글자 크기 규칙(`[data-view="simple"] …`)은 조상 속성에 기댄다 — body 로 옮겨도 그 값을 잇는다
  const view = document.querySelector("[data-view]")?.getAttribute("data-view") ?? undefined;
  return createPortal(
    <div data-view={view} className="fixed inset-0 z-50 flex items-end justify-center sm:items-stretch sm:justify-end">
      <button
        type="button"
        aria-label="닫기"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-cosmos-bg/70 backdrop-blur-[2px]"
      />
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        style={{ backgroundColor: "var(--cosmos-overlay)", width: `min(100%, ${width})` }}
        className="relative flex max-h-[86vh] w-full flex-col rounded-t-2xl border border-cosmos-border shadow-[0_-12px_40px_var(--cosmos-shadow)] sm:max-h-none sm:h-full sm:rounded-none sm:rounded-l-2xl sm:shadow-[-16px_0_44px_var(--cosmos-shadow)]"
      >
        {/* 모바일 손잡이 */}
        <span aria-hidden="true" className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-cosmos-border-strong sm:hidden" />

        <div className="flex shrink-0 items-start justify-between gap-3 px-4 pb-3 pt-3 sm:px-5 sm:pt-5">
          <div className="min-w-0">
            <h2 id={headingId} className="text-[15px] font-semibold leading-tight text-cosmos-text">
              {title}
            </h2>
            {description && <p className="mt-1 text-[12px] leading-5 text-cosmos-secondary">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="mc-focus -mr-1 -mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-cosmos-secondary transition-colors hover:bg-cosmos-elevated hover:text-cosmos-text"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        <div className="mc-scroll min-h-0 flex-1 overflow-y-auto px-4 pb-4 sm:px-5">{children}</div>

        {footer && <div className="shrink-0 border-t border-cosmos-border px-4 py-3 sm:px-5">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Popover — 트리거 버튼 + 작은 패널 (비모달)
// ---------------------------------------------------------------------------

export interface PopoverProps {
  /** 트리거 버튼 안에 넣을 내용 */
  trigger: ReactNode;
  /** 트리거의 접근성 이름 */
  triggerLabel: string;
  triggerClassName?: string;
  title: string;
  children: ReactNode;
  /** 패널을 오른쪽 끝에 맞출지 (기본 왼쪽 정렬) */
  align?: "start" | "end";
  width?: string;
}

export function Popover({
  trigger,
  triggerLabel,
  triggerClassName = "",
  title,
  children,
  align = "start",
  width = "300px",
}: PopoverProps) {
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismissable(open, close);

  // 패널이 화면 가장자리를 넘으면 안으로 민다 — 트리거 기준 왼쪽 · 오른쪽 끝에만 붙이면 390 에서 화면 왼쪽 밖(x<0)으로
  // 열려 읽을 수 없었다 (CMN-09 · OPP-07). fixed 로 띄우면 흐림(backdrop-blur) 머리 안에서 자리가 틀어진다 — 잰 만큼만 옮긴다.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !panel) return;
    const rect = panel.getBoundingClientRect();
    const right = document.documentElement.clientWidth - 12;
    const dx = rect.left < 12 ? 12 - rect.left : rect.right > right ? right - rect.right : 0;
    if (dx) panel.style.transform = `translateX(${Math.round(dx)}px)`;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus({ preventScroll: true });
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <div ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={triggerLabel}
        onClick={() => setOpen((value) => !value)}
        className={`mc-focus inline-flex min-h-8 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors ${
          open
            ? "border-cosmos-cyan/60 bg-cosmos-elevated text-cosmos-text"
            : "border-cosmos-border bg-cosmos-panel text-cosmos-secondary hover:border-cosmos-border-strong hover:text-cosmos-text"
        } ${triggerClassName}`}
      >
        {trigger}
      </button>
      {open && (
        <div
          ref={panelRef}
          tabIndex={-1}
          role="dialog"
          aria-labelledby={headingId}
          style={{ backgroundColor: "var(--cosmos-overlay)", width }}
          className={`mc-scroll absolute top-[calc(100%+6px)] z-40 max-h-[70vh] max-w-[calc(100vw-24px)] overflow-y-auto rounded-xl border border-cosmos-border p-3.5 shadow-[0_16px_40px_var(--cosmos-shadow)] ${
            align === "end" ? "right-0" : "left-0"
          }`}
        >
          <h3 id={headingId} className="text-[12px] font-semibold uppercase tracking-[0.1em] text-cosmos-muted">
            {title}
          </h3>
          <div className="mt-2 flex flex-col gap-2 text-[12.5px] leading-5 text-cosmos-secondary">{children}</div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal — 가운데 대화상자 (포커스 가둠 포함)
// ---------------------------------------------------------------------------

/**
 * 포커스를 이 안에 가둔다 (ISSUE-033 · TASK-021).
 *
 * `role="dialog" aria-modal="true"` 만으로는 Tab 이 대화상자 밖으로 나간다. 키보드로
 * 쓰는 사람은 뒤 화면의 3D 무대·상단바 버튼 사이를 헤매게 되고, 그동안 화면에 보이는
 * 것은 대화상자다 — 지금 어디에 있는지 알 수 없다.
 *
 * 마지막 요소에서 Tab 을 누르면 처음으로, 처음에서 Shift+Tab 이면 마지막으로 돌린다.
 */
export function useFocusTrap(open: boolean) {
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const box = boxRef.current;
    if (!box) return;

    const focusable = () =>
      [...box.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)].filter(
        (el) => !el.hasAttribute("disabled") && el.tabIndex !== -1,
      );

    focusable()[0]?.focus({ preventScroll: true });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !box.contains(active))) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    };

    box.addEventListener("keydown", onKeyDown);
    return () => box.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return boxRef;
}

const FOCUSABLE_SELECTOR =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  /** 제목 (aria-labelledby 로 연결된다) */
  title: string;
  children: ReactNode;
  /** 최대 폭 Tailwind 클래스. 기본 max-w-md */
  maxWidth?: string;
}

/**
 * 가운데 대화상자. Escape 로 닫히고, 닫히면 열었던 버튼으로 포커스가 돌아가며,
 * 열려 있는 동안 Tab 이 밖으로 나가지 않는다.
 *
 * 화면마다 따로 만들던 대화상자를 여기로 모은다 — 접근성 처리를 각자 다시 하면
 * 그중 하나는 반드시 빠진다.
 */
export function Modal({ open, onClose, title, children, maxWidth = "max-w-md" }: ModalProps) {
  const headingId = useId();
  useDismissable(open, onClose);
  const boxRef = useFocusTrap(open);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="닫기" tabIndex={-1} onClick={onClose} className="absolute inset-0 cursor-default bg-black/60" />
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className={`mc-panel relative flex w-full ${maxWidth} flex-col gap-2.5 bg-cosmos-bg p-4`}
      >
        <h2 id={headingId} className="text-[14px] font-semibold text-cosmos-text">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
