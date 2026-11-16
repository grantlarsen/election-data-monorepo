import { useLayoutEffect, useRef, useState } from "react";
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
  const [position, setPosition] = useState({ x: 8, y: 8, side: "right" });
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      setPosition(
        tooltipPosition(anchor, rect, {
          width: window.innerWidth,
          height: window.innerHeight,
        }),
      );
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(measure);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, [anchor]);
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      className="map-tooltip"
      data-side={position.side}
      style={{ left: position.x, top: position.y }}
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
