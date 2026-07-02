import { X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useToastStore, type ToastVariant } from '../../stores/toast';

/**
 * Celesnity toasts — a quiet glass surface (readable ink text in both Cosmos
 * and Daybreak) with a colored accent stripe carrying the status meaning.
 */
const VARIANT_ACCENT: Record<ToastVariant, string> = {
  info:    'before:bg-accent-cobalt',
  success: 'before:bg-semantic-success',
  warning: 'before:bg-accent-magenta',
  error:   'before:bg-semantic-danger',
};

export function ToastContainer() {
  const toasts = useToastStore(state => state.toasts);
  const removeToast = useToastStore(state => state.removeToast);
  const reduce = useReducedMotion();

  return (
    <div className="fixed top-14 right-4 z-[10000] flex flex-col gap-2 max-w-sm pointer-events-none">
      <AnimatePresence>
        {toasts.map(toast => (
          <motion.div
            key={toast.id}
            layout
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.97 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, x: 12, scale: 0.97 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className={`glass-card pointer-events-auto relative overflow-hidden flex items-center gap-3 pl-5 pr-4 py-3 rounded-md shadow-cosmos text-body-sm text-ink before:absolute before:left-0 before:inset-y-0 before:w-1 ${VARIANT_ACCENT[toast.variant]}`}
          >
            <span className="flex-1 leading-snug">{toast.message}</span>
            <button
              onClick={() => removeToast(toast.id)}
              aria-label="Dismiss notification"
              className="flex-shrink-0 text-text-muted hover:text-ink rounded-full p-0.5"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
