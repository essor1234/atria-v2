import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export interface MenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  shortcut?: string;
  disabled?: boolean;
}

interface Props {
  x: number;
  y: number;
  items: Array<MenuItem | 'divider'>;
  onClose: () => void;
}

export function NodeContextMenu({ x, y, items, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  // Keep menu within viewport
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const overflowX = rect.right - window.innerWidth;
    const overflowY = rect.bottom - window.innerHeight;
    if (overflowX > 0) el.style.left = `${x - overflowX - 8}px`;
    if (overflowY > 0) el.style.top = `${y - overflowY - 8}px`;
  }, [x, y]);

  return createPortal(
    <div
      ref={ref}
      role="menu"
      style={{ left: x, top: y }}
      className="fixed z-50 min-w-[180px] bg-canvas border border-hairline-soft rounded-md shadow-lg py-1 text-[12.5px] font-mono"
    >
      {items.map((it, i) => {
        if (it === 'divider') return <div key={`d-${i}`} className="my-1 border-t border-hairline-soft/60" />;
        return (
          <button
            key={it.label}
            role="menuitem"
            disabled={it.disabled}
            onClick={() => { if (!it.disabled) { it.onSelect(); onClose(); } }}
            className={`w-full text-left px-3 py-1.5 flex items-center gap-3 transition-colors cursor-pointer ${
              it.disabled
                ? 'text-ink/30 cursor-not-allowed'
                : it.danger
                  ? 'text-rose-400/90 hover:bg-rose-500/10'
                  : 'text-ink/85 hover:bg-ink/5'
            }`}
          >
            <span className="flex-1 truncate">{it.label}</span>
            {it.shortcut && <span className="text-[11px] text-ink/35">{it.shortcut}</span>}
          </button>
        );
      })}
    </div>,
    document.body,
  );
}
