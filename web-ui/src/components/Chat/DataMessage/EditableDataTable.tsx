import { useMemo, useState, useCallback } from 'react';
import type { DataColumn } from '../../../types';
import { apiClient } from '../../../api/client';
import { useChatStore } from '../../../stores/chat';

const MAX_EDIT_ROWS = 2000;

interface Props {
  messageId: string;
  title: string;
  columns: DataColumn[];
  rows: Record<string, any>[];
  source: { module: string; file: string };
  warning?: string;
}

/**
 * Inline editable grid bound to a module CSV dataset. Edits live in local state
 * and are persisted to the module via PUT /api/modules/{module}/data/write on
 * Save. Everything is defensive: a failed save keeps the user's edits and shows
 * an inline error rather than crashing the chat.
 */
export function EditableDataTable({ messageId, title, columns, rows, source, warning }: Props) {
  const updateDataMessageRows = useChatStore((s) => s.updateDataMessageRows);
  // Stable column list; fall back to keys of the first row if columns are absent.
  const cols: DataColumn[] = useMemo(() => {
    if (columns && columns.length) return columns;
    const first = rows && rows[0];
    if (first && typeof first === 'object') {
      return Object.keys(first).map((name) => ({ name, type: 'string' as const }));
    }
    return [];
  }, [columns, rows]);

  const [editRows, setEditRows] = useState<Record<string, any>[]>(() =>
    (rows || []).map((r) => ({ ...r })),
  );
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const overflow = editRows.length > MAX_EDIT_ROWS;
  const visibleRows = overflow ? editRows.slice(0, MAX_EDIT_ROWS) : editRows;

  const setCell = useCallback((rowIdx: number, colName: string, value: string) => {
    setEditRows((prev) => {
      const next = prev.slice();
      next[rowIdx] = { ...next[rowIdx], [colName]: value };
      return next;
    });
    setDirty(true);
    setNote(null);
  }, []);

  const addRow = useCallback(() => {
    setEditRows((prev) => {
      const blank: Record<string, any> = {};
      for (const c of cols) blank[c.name] = '';
      return [...prev, blank];
    });
    setDirty(true);
    setNote(null);
  }, [cols]);

  const deleteRow = useCallback((rowIdx: number) => {
    setEditRows((prev) => prev.filter((_, i) => i !== rowIdx));
    setDirty(true);
    setNote(null);
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const res = await apiClient.writeDataset(source.module, source.file, cols, editRows);
      setDirty(false);
      setNote(`Saved ${res?.rows ?? editRows.length} rows to ${source.file}`);
      // Keep the stored snapshot in sync so leaving the chat (e.g. to view the
      // module dashboard) and coming back doesn't revert to the pre-edit values.
      updateDataMessageRows(messageId, cols, editRows.map((r) => ({ ...r })));
    } catch (e: any) {
      setError(e?.message ? String(e.message) : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }, [cols, editRows, source.module, source.file, messageId, updateDataMessageRows]);

  const reload = useCallback(async () => {
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const data = await apiClient.readDataset(source.module, source.file);
      const fresh = (data?.rows || []).map((r) => ({ ...r }));
      setEditRows(fresh);
      setDirty(false);
      setNote('Reloaded from source');
      updateDataMessageRows(messageId, cols, fresh);
    } catch (e: any) {
      setError(e?.message ? String(e.message) : 'Failed to reload');
    } finally {
      setSaving(false);
    }
  }, [source.module, source.file, messageId, cols, updateDataMessageRows]);

  return (
    <div className="my-3 relative">
      <div className="rounded-lg border border-border-300/15 bg-bg-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border-300/15">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-text-000 truncate">{title || 'Data'}</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-accent-main-100/10 text-accent-main-100 border border-accent-main-100/20">
              editable
            </span>
            {warning && (
              <span
                className="text-[11px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30"
                title={warning}
              >
                {warning}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={addRow}
              disabled={saving}
              className="px-2 py-1 text-xs rounded border border-border-300/15 text-text-200 hover:bg-bg-200 disabled:opacity-50"
            >
              + Row
            </button>
            <button
              onClick={reload}
              disabled={saving}
              className="px-2 py-1 text-xs rounded border border-border-300/15 text-text-300 hover:bg-bg-200 disabled:opacity-50"
              title="Discard changes and reload from the saved file"
            >
              Reload
            </button>
            <button
              onClick={save}
              disabled={saving || !dirty}
              className="px-2.5 py-1 text-xs rounded bg-accent-main-100 text-bg-000 hover:bg-accent-main-100/90 disabled:opacity-40"
            >
              {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
            </button>
          </div>
        </div>

        {error && (
          <div className="px-3 py-2 text-xs text-red-400 bg-red-500/10 border-b border-red-500/20">
            {error}
          </div>
        )}
        {note && !error && (
          <div className="px-3 py-2 text-xs text-emerald-400 bg-emerald-500/10 border-b border-emerald-500/20">
            {note}
          </div>
        )}

        {/* Body */}
        <div className="overflow-auto max-h-96">
          {cols.length === 0 ? (
            <div className="px-3 py-4 text-sm text-text-300">No columns.</div>
          ) : (
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="sticky top-0 bg-bg-100 z-10">
                  {cols.map((col) => (
                    <th
                      key={col.name}
                      className="px-2 py-2 text-left font-medium text-text-100 border-b border-border-300/15 whitespace-nowrap"
                    >
                      {col.name}
                      {col.editable === false && (
                        <span className="ml-1 opacity-40" title="read-only">
                          🔒
                        </span>
                      )}
                    </th>
                  ))}
                  <th className="px-2 py-2 border-b border-border-300/15 w-8" />
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row, ri) => (
                  <tr key={ri} className={ri % 2 === 0 ? 'bg-transparent' : 'bg-bg-000/30'}>
                    {cols.map((col) => {
                      const readOnly = col.editable === false;
                      const value = row[col.name];
                      return (
                        <td
                          key={col.name}
                          className="px-1 py-0.5 border-b border-border-300/10 align-middle"
                        >
                          {readOnly ? (
                            <span className="px-1 text-text-300 whitespace-nowrap">
                              {value == null ? '' : String(value)}
                            </span>
                          ) : (
                            <input
                              value={value == null ? '' : String(value)}
                              onChange={(e) => setCell(ri, col.name, e.target.value)}
                              inputMode={col.type === 'number' ? 'decimal' : undefined}
                              className="w-full min-w-[80px] bg-transparent text-text-100 px-1 py-1 rounded border border-transparent hover:border-border-300/20 focus:border-accent-main-100/50 focus:bg-bg-000/40 outline-none"
                            />
                          )}
                        </td>
                      );
                    })}
                    <td className="px-1 py-0.5 border-b border-border-300/10 text-center">
                      <button
                        onClick={() => deleteRow(ri)}
                        disabled={saving}
                        title="Delete row"
                        className="text-text-300 hover:text-red-400 disabled:opacity-50 px-1"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between px-3 py-1.5 text-[11px] text-text-300 border-t border-border-300/10">
          <span>
            {editRows.length.toLocaleString()} row{editRows.length === 1 ? '' : 's'}
            {overflow && ` · editing first ${MAX_EDIT_ROWS.toLocaleString()}`}
          </span>
          <span className="opacity-60 truncate">
            {source.module}/{source.file}
          </span>
        </div>
      </div>
    </div>
  );
}
