import { useCallback, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

export interface TooltipPoint {
  x: number;
  y: number;
}
export function tooltipPosition(
  anchor: TooltipPoint,
  size: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  const gap = 16,
    edge = 8;
  const side =
    anchor.x + gap + size.width <= viewport.width - edge ? "right" : "left";
  const x = side === "right" ? anchor.x + gap : anchor.x - gap - size.width;
  const y =
    anchor.y + gap + size.height <= viewport.height - edge
      ? anchor.y + gap
      : anchor.y - gap - size.height;
  return {
    x: Math.max(edge, Math.min(x, viewport.width - size.width - edge)),
    y: Math.max(edge, Math.min(y, viewport.height - size.height - edge)),
    side,
  };
}

/** A viewport-bounded portal avoids clipping inside SVG/map containers. */
export function MapTooltip({
  id,
  anchor,
  children,
  onEnter,
  onLeave,
}: {
  id: string;
  anchor: TooltipPoint;
  children: ReactNode;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const currentAnchor = useRef(anchor);
  const size = useRef({ width: 0, height: 0 });
  const place = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    const position = tooltipPosition(currentAnchor.current, size.current, {
      width: window.innerWidth, height: window.innerHeight,
    });
    element.style.left = `${position.x}px`;
    element.style.top = `${position.y}px`;
    element.dataset.side = position.side;
  }, []);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      size.current = element.getBoundingClientRect();
      place();
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [place, children]);
  useLayoutEffect(() => {
    currentAnchor.current = anchor;
    place();
  }, [anchor, place]);
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      className="map-tooltip"
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onFocusCapture={onEnter}
      onBlurCapture={event => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onLeave();
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
