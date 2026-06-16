import { useEffect, useRef, useState } from 'react';
import { Folder, File as FileIcon } from 'lucide-react';

interface Props {
  depth: number;
  kind: 'file' | 'dir';
  placeholder?: string;
  initial?: string;
  selectExtension?: boolean;
  onConfirm: (name: string) => Promise<void> | void;
  onCancel: () => void;
}

export function PendingRow({ depth, kind, placeholder, initial = '', selectExtension = false, onConfirm, onCancel }: Props) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    if (initial && selectExtension) {
      const dot = initial.lastIndexOf('.');
      if (dot > 0) el.setSelectionRange(0, dot);
      else el.select();
    } else if (initial) {
      el.select();
    }
  }, [initial, selectExtension]);

  const submit = async () => {
    if (busy) return;
    const trimmed = value.trim();
    if (!trimmed) {
      onCancel();
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(trimmed);
    } catch (e: unknown) {
      setBusy(false);
      setErr(e instanceof Error ? e.message : 'Failed.');
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  };

  const Glyph = kind === 'dir' ? Folder : FileIcon;
  const glyphColor = kind === 'dir' ? 'text-sky-400/70' : 'text-ink/45';

  return (
    <div style={{ paddingLeft: 6 + depth * 14 }} className="flex flex-col">
      <div className="flex items-center gap-1.5 pr-2 py-[3px] text-[12.5px] font-mono">
        <span className="w-3 h-3 flex-shrink-0" />
        <Glyph className={`w-3.5 h-3.5 flex-shrink-0 ${glyphColor}`} />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); if (err) setErr(null); }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); void submit(); }
            else if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
          }}
          onBlur={() => { if (!err) void submit(); else onCancel(); }}
          placeholder={placeholder}
          aria-label={kind === 'file' ? 'New file name' : 'New folder name'}
          disabled={busy}
          className="flex-1 min-w-0 bg-ink/5 text-ink placeholder:text-ink/35 outline-none rounded px-1 py-0 leading-tight focus:ring-1 focus:ring-sky-400/60"
        />
      </div>
      {err && (
        <div style={{ paddingLeft: 6 + depth * 14 + 26 }} className="pb-1 pr-2 text-[11px] text-semantic-danger font-mono">
          {err}
        </div>
      )}
    </div>
  );
}
