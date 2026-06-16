import { X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useToastStore, type ToastVariant } from '../../stores/toast';

/**
 * Editorial toast surfaces — pastel color blocks instead of generic
 * SaaS green/red/yellow. See DESIGN.md "Color-Block Sections (signature)".
 */
const VARIANT_STYLES: Record<ToastVariant, string> = {
  info:    'bg-block-cream text-ink',
  success: 'bg-block-mint  text-ink',
  warning: 'bg-block-lilac text-ink',
  error:   'bg-block-coral text-ink',
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
            className={`pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-lg shadow-soft text-body-sm ${VARIANT_STYLES[toast.variant]}`}
          >
            <span className="flex-1 leading-snug">{toast.message}</span>
            <button
              onClick={() => removeToast(toast.id)}
              aria-label="Dismiss notification"
              className="flex-shrink-0 opacity-60 hover:opacity-100 rounded-full p-0.5"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
