import { useEffect, useMemo, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import { Save, Loader2 } from 'lucide-react';
import { apiClient } from '../../../api/client';
import { monacoLanguageFor } from './extensions';
import { fsScopeKey, type FsScope } from '../../../types';

interface Props {
  scope: FsScope;
  path: string;
  languageOverride?: string;
  /** Allow editing + save (currently only honored for module scope). */
  editable?: boolean;
}

export function MonacoViewer({ scope, path, languageOverride, editable = false }: Props) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const scopeKey = useMemo(() => fsScopeKey(scope), [scope]);
  const canSave = editable && scope.kind === 'module';

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setError(null);
    setDirty(false);
    apiClient.readFsText(scope, path)
      .then(t => { if (!cancelled) setText(t); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [scopeKey, path]);

  const dirtyRef = useRef(dirty);
  const savingRef = useRef(saving);
  const textRef = useRef(text);
  dirtyRef.current = dirty;
  savingRef.current = saving;
  textRef.current = text;

  const onSave = async () => {
    if (!canSave || savingRef.current || !dirtyRef.current || textRef.current == null) return;
    setSaving(true);
    try {
      await apiClient.writeFsText(scope, path, textRef.current);
      setDirty(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  useEffect(() => {
    if (!canSave) return;
    const handler = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        onSaveRef.current();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [canSave]);

  if (error) {
    return (
      <div className="p-4 text-xs font-mono text-block-coral">
        Failed to load file: {error}
      </div>
    );
  }
  if (text === null) {
    return <div className="p-4 text-xs font-mono text-ink/45">Loading…</div>;
  }

  const dot = path.lastIndexOf('.');
  const ext = dot >= 0 ? path.slice(dot) : '';
  const language = languageOverride ?? monacoLanguageFor(ext);

  const editor = (
    <Editor
      value={text}
      language={language}
      theme="vs"
      onChange={canSave ? (v) => { setText(v ?? ''); setDirty(true); } : undefined}
      options={{
        readOnly: !canSave,
        automaticLayout: true,
        minimap: { enabled: false },
        wordWrap: 'off',
        scrollBeyondLastLine: false,
        fontSize: 13,
      }}
    />
  );

  if (!canSave) return editor;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-hairline-soft/60 bg-surface-soft/20 flex-shrink-0">
        <span className="text-[11px] font-mono text-ink/55 truncate">{path}</span>
        {dirty ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-600 text-[10px] font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> unsaved · ⌘S
          </span>
        ) : (
          <span className="text-[10px] text-ink/35 font-mono">saved</span>
        )}
        <div className="flex-1" />
        <button
          onClick={onSave}
          disabled={!dirty || saving}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-sky-500/90 text-white hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
          Save
        </button>
      </div>
      <div className="flex-1 min-h-0">{editor}</div>
    </div>
  );
}
