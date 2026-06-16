import { useEffect, useMemo, useRef, useState, Suspense, lazy } from 'react';
import Papa from 'papaparse';
import { apiClient } from '../../../api/client';
import { DataTable } from './DataTable';
import { wsClient } from '../../../api/websocket';
import { fsScopeKey, type FsScope, type WSMessage } from '../../../types';

const MonacoViewer = lazy(() =>
  import('./MonacoViewer').then(m => ({ default: m.MonacoViewer })),
);

interface Props { scope: FsScope; path: string }

interface Parsed {
  columns: string[];
  rows: (string | number | null)[][];
  total: number;
}

type SaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const SAVE_DEBOUNCE_MS = 500;

export function CsvViewer({ scope, path }: Props) {
  const scopeKey = useMemo(() => fsScopeKey(scope), [scope]);
  const [state, setState] = useState<
    { kind: 'loading' } | { kind: 'ok'; data: Parsed } | { kind: 'error'; msg: string }
  >({ kind: 'loading' });
  const [editing, setEditing] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ignoreNextChangeRef = useRef(false);
  const reloadRef = useRef<() => void>(() => {});

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      setState({ kind: 'loading' });
      apiClient.readFsText(scope, path).then(text => {
        const result = Papa.parse<string[]>(text, { skipEmptyLines: true });
        if (cancelled) return;
        if (result.errors.length > 0 && result.data.length === 0) {
          setState({ kind: 'error', msg: result.errors[0].message });
          return;
        }
        const rows = result.data;
        const columns = (rows[0] ?? []).map(c => String(c));
        const body = rows.slice(1) as (string | number | null)[][];
        setState({ kind: 'ok', data: { columns, rows: body, total: body.length } });
      }).catch(e => {
        if (!cancelled) setState({ kind: 'error', msg: String(e) });
      });
    };
    reloadRef.current = load;
    load();
    return () => { cancelled = true; };
  }, [scopeKey, path]);

  // React to remote edits (e.g. user editing in another tab) — skip if we
  // just authored the write ourselves.
  useEffect(() => {
    const unsubscribe = wsClient.on('artifact.changed', (msg: WSMessage) => {
      const d = (msg as { scope?: string; conversation_id?: number; module?: string; path?: string });
      if (d.path !== path) return;
      if (scope.kind === 'conv' && (d.scope !== 'conv' || d.conversation_id !== scope.id)) return;
      if (scope.kind === 'module' && (d.scope !== 'module' || d.module !== scope.name)) return;
      if (ignoreNextChangeRef.current) {
        ignoreNextChangeRef.current = false;
        return;
      }
      reloadRef.current();
    });
    return () => unsubscribe();
  }, [scopeKey, path, scope]);

  const scheduleSave = (next: Parsed) => {
    setSaveStatus('pending');
    setSaveError(null);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const text = Papa.unparse([next.columns, ...next.rows]);
      setSaveStatus('saving');
      ignoreNextChangeRef.current = true;
      apiClient.writeFsText(scope, path, text).then(() => {
        setSaveStatus('saved');
      }).catch(err => {
        ignoreNextChangeRef.current = false;
        setSaveStatus('error');
        setSaveError(err instanceof Error ? err.message : String(err));
      });
    }, SAVE_DEBOUNCE_MS);
  };

  const handleCellChange = (rowIndex: number, colIndex: number, value: string) => {
    if (state.kind !== 'ok') return;
    const rows = state.data.rows.map((r, i) =>
      i === rowIndex ? r.map((c, j) => (j === colIndex ? value : c)) : r,
    );
    const next = { ...state.data, rows };
    setState({ kind: 'ok', data: next });
    scheduleSave(next);
  };

  const handleColumnChange = (colIndex: number, value: string) => {
    if (state.kind !== 'ok') return;
    const columns = state.data.columns.map((c, i) => (i === colIndex ? value : c));
    const next = { ...state.data, columns };
    setState({ kind: 'ok', data: next });
    scheduleSave(next);
  };

  useEffect(() => () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
  }, []);

  if (state.kind === 'loading') {
    return <div className="p-4 text-xs font-mono text-ink/45">Parsing CSV…</div>;
  }
  if (state.kind === 'error') {
    return (
      <div className="flex flex-col h-full">
        <div className="px-3 py-1.5 text-[13px] font-mono text-block-coral border-b border-hairline-soft bg-surface-soft/70">
          CSV parse failed: {state.msg}. Showing raw text.
        </div>
        <div className="flex-1">
          <Suspense fallback={<div className="p-4 text-xs font-mono text-ink/45">Loading…</div>}>
            <MonacoViewer scope={scope} path={path} />
          </Suspense>
        </div>
      </div>
    );
  }

  const statusLabel: Record<SaveStatus, string> = {
    idle: '',
    pending: 'editing…',
    saving: 'saving…',
    saved: 'saved',
    error: saveError ? `error: ${saveError}` : 'error',
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-1.5 text-[12px] font-mono border-b border-hairline-soft bg-surface-soft/70">
        <button
          type="button"
          onClick={() => setEditing(v => !v)}
          className="px-2 py-0.5 rounded border border-hairline-soft hover:bg-canvas transition-colors"
        >
          {editing ? 'Done' : 'Edit'}
        </button>
        {editing && (
          <span
            className={
              saveStatus === 'error'
                ? 'text-block-coral'
                : saveStatus === 'saved'
                  ? 'text-ink/60'
                  : 'text-ink/45'
            }
          >
            {statusLabel[saveStatus]}
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0">
        <DataTable
          columns={state.data.columns}
          rows={state.data.rows}
          truncatedFrom={state.data.total}
          editable={editing}
          onCellChange={handleCellChange}
          onColumnChange={handleColumnChange}
        />
      </div>
    </div>
  );
}
