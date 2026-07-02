import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Editorial modal: scrim fade + scale-in panel. Follows DESIGN.md
 * shadow-light rhythm — the scrim is matte black at 60% per the
 * `{colors.overlay-scrim}` spec, the panel is white canvas with `rounded-lg`.
 */
export function Modal({ isOpen, onClose, title, children, className = '' }: ModalProps) {
  const reduce = useReducedMotion();

  useEffect(() => {
    if (!isOpen) return;
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          key="modal-scrim"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[hsl(var(--overlay-scrim)/0.72)] backdrop-blur-sm"
          aria-labelledby="modal-title"
          role="dialog"
          aria-modal="true"
          onClick={onClose}
        >
          <motion.div
            key="modal-panel"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.97 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className={`relative bg-canvas rounded-xl shadow-cosmos w-full max-w-md m-4 border border-hairline-soft ${className}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-hairline-soft">
              <h2 id="modal-title" className="text-[18px] font-[540] text-ink tracking-[-0.14px]">
                {title}
              </h2>
              <button
                onClick={onClose}
                className="p-1.5 rounded-full text-text-muted hover:bg-surface-soft hover:text-ink"
                aria-label="Close modal"
              >
                <X className="w-[18px] h-[18px]" strokeWidth={1.5} />
              </button>
            </div>
            <div className="p-6">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
