import { useCallback, useRef, useState } from 'react';
import Papa from 'papaparse';
import { apiClient } from '../../../api/client';
import type { FsScope } from '../../../types';
import { DataTable } from './DataTable';

const MAX_EDIT_ROWS = 2000;

interface Props {
  columns: string[];
  rows: (string | number | null | undefined)[][];
  total: number;
  scope: FsScope;
  path: string;
}

function toStr(v: string | number | null | undefined): string {
  return v == null ? '' : String(v);
}

/**
 * Editable CSV grid for the file viewer. Renders the parsed CSV as a table that
 * the user can edit in place (cells, header names, add/delete rows) and Save
 * back to the file via the module fs write endpoint. View mode looks like the
 * read-only DataTable; Edit mode swaps in controlled inputs.
 *
 * Everything is defensive: Save/Revert are wrapped in try/catch and a failed
 * save keeps the user's edits and shows an inline error rather than crashing.
 */
export function EditableCsvTable({ columns, rows, total, scope, path }: Props) {
  const tooLarge = rows.length > MAX_EDIT_ROWS;

  const [editing, setEditing] = useState(false);
  const [cols, setCols] = useState<string[]>(() => columns.map((c) => String(c)));
  const [data, setData] = useState<string[][]>(() => rows.map((r) => r.map(toStr)));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // The last persisted snapshot (initially the file as parsed from disk; updated
  // on each successful save). Revert restores to this. The working copy (cols/
  // data) is the single source of truth for BOTH edit and view mode, so entering
  // or leaving edit mode never reverts the just-saved data.
  const baseline = useRef<{ cols: string[]; data: string[][] }>({
    cols: columns.map((c) => String(c)),
    data: rows.map((r) => r.map(toStr)),
  });

  const revert = useCallback(() => {
    setCols(baseline.current.cols.slice());
    setData(baseline.current.data.map((r) => r.slice()));
    setDirty(false);
    setError(null);
    setNote(null);
  }, []);

  const setCell = useCallback((ri: number, ci: number, value: string) => {
    setData((prev) => {
      const next = prev.slice();
      const row = next[ri].slice();
      row[ci] = value;
      next[ri] = row;
      return next;
    });
    setDirty(true);
    setNote(null);
  }, []);

  const setHeader = useCallback((ci: number, value: string) => {
    setCols((prev) => {
      const next = prev.slice();
      next[ci] = value;
      return next;
    });
    setDirty(true);
    setNote(null);
  }, []);

  const addRow = useCallback(() => {
    setData((prev) => [...prev, cols.map(() => '')]);
    setDirty(true);
    setNote(null);
  }, [cols]);

  const deleteRow = useCallback((ri: number) => {
    setData((prev) => prev.filter((_, i) => i !== ri));
    setDirty(true);
    setNote(null);
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const csv = Papa.unparse({ fields: cols, data });
      await apiClient.writeFsText(scope, path, csv);
      // The saved state is now the baseline (so Revert returns here, and view
      // mode keeps showing the saved data).
      baseline.current = { cols: cols.slice(), data: data.map((r) => r.slice()) };
      setDirty(false);
      setNote(`Saved ${data.length} row${data.length === 1 ? '' : 's'}`);
    } catch (e: any) {
      setError(e?.message ? String(e.message) : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }, [cols, data, scope, path]);

  // Files too large to edit comfortably in DOM inputs stay read-only.
  if (tooLarge) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-3 py-1.5 text-[13px] font-mono text-block-coral border-b border-hairline-soft bg-surface-soft/70">
          {total.toLocaleString()} rows — too large to edit here (read-only).
        </div>
        <div className="flex-1">
          <DataTable columns={columns} rows={rows} truncatedFrom={total} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-hairline-soft bg-surface-soft/40">
        {!editing ? (
          <button
            onClick={() => setEditing(true)}
            className="px-2 py-0.5 text-[12px] rounded border border-hairline text-ink/80 hover:bg-surface-soft"
          >
            Edit
          </button>
        ) : (
          <>
            <button
              onClick={addRow}
              disabled={saving}
              className="px-2 py-0.5 text-[12px] rounded border border-hairline text-ink/80 hover:bg-surface-soft disabled:opacity-50"
            >
              + Row
            </button>
            <button
              onClick={revert}
              disabled={saving}
              className="px-2 py-0.5 text-[12px] rounded border border-hairline text-ink/55 hover:bg-surface-soft disabled:opacity-50"
              title="Discard changes"
            >
              Revert
            </button>
            <button
              onClick={save}
              disabled={saving || !dirty}
              className="px-2.5 py-0.5 text-[12px] rounded bg-accent-main-100 text-bg-000 hover:bg-accent-main-100/90 disabled:opacity-40"
            >
              {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
            </button>
            <button
              onClick={() => setEditing(false)}
              disabled={saving}
              className="px-2 py-0.5 text-[12px] rounded border border-hairline text-ink/55 hover:bg-surface-soft disabled:opacity-50"
            >
              Done
            </button>
          </>
        )}
        <span className="ml-auto text-[11px] font-mono text-ink/40">
          {data.length.toLocaleString()} row{data.length === 1 ? '' : 's'}
        </span>
      </div>

      {error && (
        <div className="px-3 py-1.5 text-[12px] font-mono text-block-coral border-b border-hairline-soft bg-block-coral/10">
          {error}
        </div>
      )}
      {note && !error && (
        <div className="px-3 py-1.5 text-[12px] font-mono text-block-mint border-b border-hairline-soft bg-block-mint/10">
          {note}
        </div>
      )}

      {/* Body */}
      {!editing ? (
        <div className="flex-1 min-h-0">
          <DataTable columns={cols} rows={data} truncatedFrom={data.length} />
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="text-[13px] font-mono w-max min-w-full border-collapse">
            <thead className="sticky top-0 bg-canvas backdrop-blur z-10">
              <tr>
                {cols.map((c, ci) => (
                  <th
                    key={ci}
                    className="text-left px-1 py-1 border-b border-hairline text-ink/80"
                  >
                    <input
                      value={c}
                      onChange={(e) => setHeader(ci, e.target.value)}
                      className="w-full min-w-[80px] bg-transparent text-ink/80 font-semibold px-1 py-0.5 rounded border border-transparent hover:border-hairline focus:border-accent-main-100/50 focus:bg-surface-soft/60 outline-none"
                    />
                  </th>
                ))}
                <th className="px-1 py-1 border-b border-hairline w-8" />
              </tr>
            </thead>
            <tbody>
              {data.map((row, ri) => (
                <tr key={ri} className="hover:bg-surface-soft/40">
                  {cols.map((_, ci) => (
                    <td key={ci} className="px-1 py-0.5 border-b border-hairline-soft">
                      <input
                        value={row[ci] ?? ''}
                        onChange={(e) => setCell(ri, ci, e.target.value)}
                        className="w-full min-w-[80px] bg-transparent text-ink px-1 py-0.5 rounded border border-transparent hover:border-hairline focus:border-accent-main-100/50 focus:bg-surface-soft/60 outline-none"
                      />
                    </td>
                  ))}
                  <td className="px-1 py-0.5 border-b border-hairline-soft text-center">
                    <button
                      onClick={() => deleteRow(ri)}
                      disabled={saving}
                      title="Delete row"
                      className="text-ink/35 hover:text-block-coral disabled:opacity-50 px-1"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
