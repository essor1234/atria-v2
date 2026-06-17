import { useEffect, useMemo, useState, Suspense, lazy } from 'react';
import Papa from 'papaparse';
import { apiClient } from '../../../api/client';
import { DataTable } from './DataTable';
import { EditableCsvTable } from './EditableCsvTable';
import { fsScopeKey, type FsScope } from '../../../types';

const MonacoViewer = lazy(() =>
  import('./MonacoViewer').then(m => ({ default: m.MonacoViewer })),
);

interface Props { scope: FsScope; path: string }

interface Parsed {
  columns: string[];
  rows: (string | number | null)[][];
  total: number;
}

export function CsvViewer({ scope, path }: Props) {
  const scopeKey = useMemo(() => fsScopeKey(scope), [scope]);
  const [state, setState] = useState<
    { kind: 'loading' } | { kind: 'ok'; data: Parsed } | { kind: 'error'; msg: string }
  >({ kind: 'loading' });

  useEffect(() => {
    let cancelled = false;
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
    return () => { cancelled = true; };
  }, [scopeKey, path]);

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
  // Module-scope CSVs are writable (PUT /api/modules/{name}/fs/write), so they
  // get the editable grid. Conversation-scope files have no write route → keep
  // them read-only.
  if (scope.kind === 'module') {
    return (
      <EditableCsvTable
        key={`${scopeKey}:${path}`}
        columns={state.data.columns}
        rows={state.data.rows}
        total={state.data.total}
        scope={scope}
        path={path}
      />
    );
  }

  return (
    <DataTable
      columns={state.data.columns}
      rows={state.data.rows}
      truncatedFrom={state.data.total}
    />
  );
}
