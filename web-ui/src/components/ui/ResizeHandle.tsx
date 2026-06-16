import { useCallback, useRef } from 'react';

interface Props {
  /** Which edge of the panel the handle sits on. 'left' = dragging left grows the panel. */
  side: 'left' | 'right';
  /** Current panel width (px). */
  width: number;
  min: number;
  max: number;
  /** Called continuously during the drag with the new, clamped width. */
  onResize: (width: number) => void;
  className?: string;
  style?: React.CSSProperties;
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

/**
 * A thin, draggable vertical divider for resizing a panel. Uses native pointer
 * events with pointer capture so the drag keeps tracking even when the cursor
 * leaves the 2px strip — more reliable than library handles here.
 */
export function ResizeHandle({ side, width, min, max, onResize, className, style }: Props) {
  const start = useRef<{ x: number; w: number } | null>(null);

  const compute = useCallback(
    (clientX: number) => {
      if (!start.current) return null;
      const dx = clientX - start.current.x;
      const delta = side === 'left' ? -dx : dx;
      return clamp(start.current.w + delta, min, max);
    },
    [side, min, max],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      start.current = { x: e.clientX, w: width };
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    [width],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const next = compute(e.clientX);
      if (next != null) onResize(next);
    },
    [compute, onResize],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!start.current) return;
      const next = compute(e.clientX);
      if (next != null) onResize(next);
      start.current = null;
      try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* ignore */ }
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    },
    [compute, onResize],
  );

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className={
        className ??
        `absolute top-0 bottom-0 ${side === 'left' ? '-left-1' : '-right-1'} w-2 cursor-col-resize hover:bg-sky-400/30 transition-colors z-30`
      }
      style={{ touchAction: 'none', ...style }}
    />
  );
}
