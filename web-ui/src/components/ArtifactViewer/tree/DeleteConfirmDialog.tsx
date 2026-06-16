import { useEffect, useState } from 'react';
import { Modal } from '../../ui/Modal';

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}

export function DeleteConfirmDialog({ open, title, message, confirmLabel = 'Delete', onConfirm, onClose }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setErr(null);
      setBusy(false);
    }
  }, [open]);

  const handleConfirm = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm();
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen={open} onClose={busy ? () => {} : onClose} title={title}>
      <p className="text-[13px] text-ink/80 leading-relaxed">{message}</p>
      {err && <p className="mt-3 text-[12px] text-semantic-danger font-mono">{err}</p>}
      <div className="mt-5 flex items-center justify-end gap-2">
        <button
          onClick={onClose}
          disabled={busy}
          autoFocus
          className="px-3 py-1.5 text-[13px] rounded text-ink/75 hover:bg-surface-soft active:scale-[0.98] whitespace-nowrap cursor-pointer transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Cancel
        </button>
        <button
          onClick={handleConfirm}
          disabled={busy}
          className="px-3 py-1.5 text-[13px] rounded bg-semantic-danger text-white hover:opacity-90 active:scale-[0.98] whitespace-nowrap cursor-pointer transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
