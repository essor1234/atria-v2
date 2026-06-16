import { useState, useEffect } from 'react';
import { Copy, CopyPlus, Trash2, Check, X } from 'lucide-react';

interface Props {
  align?: 'left' | 'right';
  onCopyMessage: () => void;
  onCopyBlock?: () => void;
  onDeleteBlock?: () => void;
  deleteDisabled?: boolean;
}

export function MessageActions({
  align = 'left',
  onCopyMessage,
  onCopyBlock,
  onDeleteBlock,
  deleteDisabled,
}: Props) {
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!confirming) return;
    const id = setTimeout(() => setConfirming(false), 4000);
    return () => clearTimeout(id);
  }, [confirming]);

  const wrapClass = [
    'absolute left-0 right-0 top-full -mt-0.5 z-10',
    'flex items-center gap-0.5',
    align === 'right' ? 'justify-end' : 'pl-[26px]',
    'opacity-0 group-hover:opacity-100 focus-within:opacity-100',
    'transition-opacity duration-150 pointer-events-none group-hover:pointer-events-auto focus-within:pointer-events-auto',
    'max-md:opacity-40 max-md:pointer-events-auto',
    confirming ? '!opacity-100 pointer-events-auto' : '',
  ].join(' ');

  const btn =
    'cursor-pointer p-1 rounded-md text-ink/40 hover:text-ink hover:bg-surface-soft ' +
    'focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink/40 ' +
    'disabled:opacity-40 disabled:cursor-not-allowed transition-colors';

  return (
    <div className={wrapClass}>
      <button
        type="button"
        className={btn}
        onClick={onCopyMessage}
        aria-label="Copy message"
        title="Copy message"
      >
        <Copy className="w-3.5 h-3.5" />
      </button>

      {onCopyBlock && (
        <button
          type="button"
          className={btn}
          onClick={onCopyBlock}
          aria-label="Copy entire turn"
          title="Copy entire turn"
        >
          <CopyPlus className="w-3.5 h-3.5" />
        </button>
      )}

      {onDeleteBlock && !confirming && (
        <button
          type="button"
          className={btn}
          onClick={() => setConfirming(true)}
          aria-label="Delete turn"
          title="Delete turn"
          disabled={deleteDisabled}
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}

      {onDeleteBlock && confirming && (
        <span className="inline-flex items-center gap-0.5">
          <button
            type="button"
            className={btn + ' text-red-600'}
            onClick={() => {
              setConfirming(false);
              onDeleteBlock?.();
            }}
            aria-label="Confirm delete"
            title="Confirm"
          >
            <Check className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            className={btn}
            onClick={() => setConfirming(false)}
            aria-label="Cancel delete"
            title="Cancel"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
    </div>
  );
}
