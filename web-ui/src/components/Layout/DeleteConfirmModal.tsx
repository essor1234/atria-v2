import { useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { AlertTriangle } from 'lucide-react';

interface DeleteConfirmModalProps {
  isOpen: boolean;
  workspacePath: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function DeleteConfirmModal({ isOpen, workspacePath, onConfirm, onCancel }: DeleteConfirmModalProps) {
  const [isDeleting, setIsDeleting] = useState(false);
  const reduce = useReducedMotion();

  const handleConfirm = async () => {
    setIsDeleting(true);
    await onConfirm();
    setIsDeleting(false);
  };

  const modalContent = (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={onCancel}
        >
          <motion.div
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.97 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="bg-canvas rounded-lg border border-hairline-soft shadow-modal w-full max-w-md p-6 m-4"
          >
            {/* Header: coral block accent matches the destructive intent */}
            <div className="flex items-center gap-3 mb-5">
              <div className="w-12 h-12 rounded-full bg-block-coral flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-6 h-6 text-ink" strokeWidth={1.5} />
              </div>
              <div>
                <h2 className="text-headline tracking-[-0.26px] font-[540] text-ink">Delete workspace</h2>
                <p className="text-body-sm text-ink/60">This action cannot be undone.</p>
              </div>
            </div>

            <div className="mb-6">
              <p className="text-body-sm text-ink mb-3">
                Delete this workspace and all its sessions?
              </p>
              <div className="px-4 py-3 bg-surface-soft border border-hairline-soft rounded-md">
                <span className="font-mono uppercase tracking-[0.54px] text-[11px] text-ink/60 block mb-1">Workspace</span>
                <p className="text-[13px] text-ink font-mono break-all">{workspacePath}</p>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={onCancel}
                disabled={isDeleting}
                className="flex-1 px-6 py-3 rounded-pill bg-canvas text-ink border border-hairline-soft hover:border-ink text-btn disabled:opacity-40 disabled:cursor-not-allowed transition-colors active:scale-[0.98] whitespace-nowrap"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={isDeleting}
                className="flex-1 px-6 py-3 rounded-pill bg-ink text-inverse-ink hover:bg-ink/90 text-btn disabled:opacity-40 disabled:cursor-not-allowed transition-colors active:scale-[0.98] whitespace-nowrap"
              >
                {isDeleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  return createPortal(modalContent, document.body);
}
