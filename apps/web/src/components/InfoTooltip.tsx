// Shared `ⓘ` tooltip — adapts to the device's input mode:
//
//   Hover-capable (desktop, mouse, trackpad):
//     mouseenter / focus → open · mouseleave / blur → close (with a short
//     hide-delay so the cursor can travel from the trigger into the
//     popover without it disappearing).
//
//   Touch-primary (phones, tablets):
//     tap the icon → toggle open · tap anywhere outside → close.
//     Hover events never fire on touch, so the mouse handlers would just
//     be no-ops — we drop them entirely on touch and bind a document-
//     level pointerdown listener instead.
//
// Capability is detected at runtime via `window.matchMedia('(hover: hover)')`
// — this asks the browser about *input capability*, not screen width, so a
// tablet with a paired mouse correctly picks the hover path and a
// touchscreen laptop in tablet mode picks the tap path.
//
// Rendering: the popover goes through a body portal with fixed positioning
// so overflow:hidden ancestors can't clip it, and viewport-edge collision
// is handled in JS. Styling (color, font size) is left to the caller via
// `contentClassName` / `triggerClassName`.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import { cn } from "../lib/cn";

interface Props {
  children: ReactNode;
  width?: number;
  ariaLabel?: string;
  iconSize?: "sm" | "md";
  // Override the default `ⓘ` glyph (e.g. a `Bug` for debug tooltips).
  icon?: ReactNode;
  triggerClassName?: string;
  contentClassName?: string;
}

const POPOVER_H_EST = 140;
const MARGIN = 8;

export function InfoTooltip({
  children,
  width = 320,
  ariaLabel = "More info",
  iconSize = "sm",
  icon,
  triggerClassName,
  contentClassName,
}: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  // Tracks `(hover: hover)`. Defaults to `true` (desktop assumption) so
  // SSR / first-paint stays consistent; the effect below corrects it on
  // mount and on subsequent media-query changes (e.g. a Surface user
  // detaches the keyboard).
  const [canHover, setCanHover] = useState(true);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const hideTimer = useRef<number | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(hover: hover)");
    setCanHover(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setCanHover(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Outside-tap dismissal — only relevant on touch (hover devices close
  // via mouseleave). Attached only while the popover is open AND we're on
  // a touch-primary device, so desktop doesn't pay for an extra global
  // listener.
  useEffect(() => {
    if (canHover || !open) return;
    function onPointerDown(e: PointerEvent) {
      const t = e.target as Node | null;
      if (!t) return;
      if (btnRef.current?.contains(t)) return;
      if (popoverRef.current?.contains(t)) return;
      setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [canHover, open]);

  function computePos() {
    if (!btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = r.left;
    if (left + width + MARGIN > vw) {
      left = Math.max(MARGIN, vw - width - MARGIN);
    }
    let top = r.bottom + 4;
    if (top + POPOVER_H_EST + MARGIN > vh) {
      top = Math.max(MARGIN, r.top - POPOVER_H_EST - 4);
    }
    setPos({ left, top });
  }

  function show() {
    if (hideTimer.current) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    computePos();
    setOpen(true);
  }

  function scheduleHide() {
    if (hideTimer.current) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => setOpen(false), 120);
  }

  function toggle() {
    if (open) {
      setOpen(false);
    } else {
      computePos();
      setOpen(true);
    }
  }

  const iconClass = iconSize === "md" ? "h-4 w-4" : "h-3.5 w-3.5";

  // Hover/focus handlers fire on desktop only — on touch we want a single
  // tap to act as toggle (not "focus opens, blur closes" which feels
  // wrong on touch and fights the outside-tap dismissal).
  const hoverHandlers = canHover
    ? {
        onMouseEnter: show,
        onMouseLeave: scheduleHide,
        onFocus: show,
        onBlur: scheduleHide,
      }
    : {};

  return (
    <span className="relative inline-flex" {...hoverHandlers}>
      <button
        ref={btnRef}
        type="button"
        aria-label={ariaLabel}
        onClick={canHover ? undefined : toggle}
        className={cn(
          "inline-flex items-center justify-center rounded transition flex-shrink-0",
          triggerClassName,
        )}
      >
        {icon ?? <Info className={iconClass} strokeWidth={2.5} />}
      </button>
      {open && pos && createPortal(
        <div
          ref={popoverRef}
          role="tooltip"
          style={{ position: "fixed", left: pos.left, top: pos.top, width }}
          className={cn(
            // Shared base — every tooltip in the app inherits the same
            // surface, font, and text color. Callers only pass deltas
            // (e.g. `tabular-nums` for numeric panels).
            "z-50 rounded-md border border-gray-200 bg-white shadow-lg p-3",
            "text-xs text-gray-800 leading-snug",
            contentClassName,
          )}
          {...(canHover
            ? { onMouseEnter: show, onMouseLeave: scheduleHide }
            : {})}
        >
          {children}
        </div>,
        document.body,
      )}
    </span>
  );
}
