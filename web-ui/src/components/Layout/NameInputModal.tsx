import { useState, useRef, useEffect, type ReactNode } from 'react';

interface NameInputModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  inputLabel: string;
  placeholder?: string;
  submitLabel: string;
  submittingLabel?: string;
  emptyError: string;
  onSubmit: (value: string) => Promise<unknown>;
  children?: (value: string) => ReactNode;
}

/**
 * Shared modal for "create X" flows that take a single name input.
 * Shared by CreateProjectModal and CreateConversationModal.
 */
export function NameInputModal({
  isOpen,
  onClose,
  title,
  subtitle,
  inputLabel,
  placeholder,
  submitLabel,
  submittingLabel = 'Creating…',
  emptyError,
  onSubmit,
  children,
}: NameInputModalProps) {
  const [name, setName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setName('');
      setError('');
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) { setError(emptyError); return; }
    setIsSubmitting(true);
    setError('');
    try {
      await onSubmit(trimmed);
      onClose();
    } catch (err) {
      setError((err as Error).message || 'Failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div data-surface="dark" className="bg-bg-000 border border-border-300/20 rounded-xl shadow-modal w-full max-w-md mx-4 p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-base font-semibold text-text-000 mb-1">{title}</h2>
        {subtitle && <div className="text-xs text-text-400 font-mono mb-4">{subtitle}</div>}
        {!subtitle && <div className="mb-4" />}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-text-300 font-mono mb-1">{inputLabel}</label>
            <input
              ref={inputRef}
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder={placeholder}
              className="w-full bg-bg-100 border border-border-300/20 rounded-lg px-3 py-2 text-sm text-text-000 placeholder-text-400"
            />
            {error && <p className="text-xs text-semantic-danger mt-1">{error}</p>}
          </div>
          {children?.(name)}
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="px-4 py-1.5 text-sm text-text-300 hover:text-text-100 transition-colors">Cancel</button>
            <button
              type="submit"
              disabled={isSubmitting || !name.trim()}
              className="px-4 py-1.5 text-sm bg-accent-main-100 text-white rounded-lg hover:bg-accent-main-100/80 disabled:opacity-40 transition-colors"
            >
              {isSubmitting ? submittingLabel : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
