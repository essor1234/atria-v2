import { useEffect, useState, useCallback } from 'react';
import { useCopyToClipboard } from 'usehooks-ts';
import type { DataColumn, Message } from '../../../types';
import { apiClient } from '../../../api/client';
import { EditableDataTable } from './EditableDataTable';

function SqlDisclosure({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [, copyToClipboard] = useCopyToClipboard();

  const copy = useCallback(async () => {
    const ok = await copyToClipboard(sql);
    if (!ok) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [sql, copyToClipboard]);

  return (
    <div className="border-b border-border-300/15 bg-bg-000/20">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 w-full px-3 py-1.5 text-[11px] text-text-300 hover:text-text-100"
      >
        <span className={`transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
        <span className="font-mono opacity-70">SQL</span>
        <span className="truncate opacity-50 flex-1 text-left">{!open && sql.replace(/\s+/g, ' ').slice(0, 80)}</span>
      </button>
      {open && (
        <div className="relative px-3 pb-3">
          <pre className="text-[11px] font-mono text-text-200 bg-bg-000/40 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
            {sql}
          </pre>
          <button
            onClick={copy}
            className="absolute top-1 right-4 px-1.5 py-0.5 text-[10px] rounded border border-border-300/15 text-text-300 hover:bg-bg-200"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      )}
    </div>
  );
}

export function DataMessage({ message }: { message: Message }) {
  // Editable variant (send_editable_table): render an inline editable grid bound
  // to the module CSV. Falls through to the read-only renderer if the binding is
  // malformed, so a bad payload never breaks the chat.
  const src = message.data_source;
  if (message.data_editable && src && src.module && src.file) {
    return (
      <EditableDataTable
        messageId={message.data_message_id ?? ''}
        title={message.data_title || 'Data'}
        columns={message.data_columns ?? []}
        rows={message.data_rows ?? []}
        source={src}
        warning={message.data_warning}
      />
    );
  }

  const messageId = message.data_message_id ?? '';

  const [fetchedColumns, setFetchedColumns] = useState<DataColumn[]>(message.data_columns ?? []);
  const [fetchedRows, setFetchedRows] = useState<Record<string, any>[]>(message.data_rows ?? []);
  const [fetchedImageSrc, setFetchedImageSrc] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Lazy-fetch table rows when not embedded in the event
  useEffect(() => {
    if (fetchedRows.length > 0) return;
    if (!message.data_db_path || !message.data_table_name) return;
    apiClient
      .fetchTableData(message.data_db_path, message.data_table_name)
      .then(({ columns, rows }) => {
        setFetchedColumns(columns);
        setFetchedRows(rows);
      })
      .catch((e) => setFetchError(String(e)));
  }, [message.data_db_path, message.data_table_name]);

  // Lazy-fetch chart PNG from disk path (session reload path)
  useEffect(() => {
    if (message.data_image_src || fetchedImageSrc) return;
    if (!message.data_image_path) return;
    apiClient
      .fetchChartImage(message.data_image_path)
      .then(setFetchedImageSrc)
      .catch((e) => setFetchError(String(e)));
  }, [message.data_image_path]);

  const columns = fetchedColumns;
  const rows = fetchedRows;

  const imageSrc = message.data_image_src || fetchedImageSrc || null;
  const hasData = rows.length > 0;

  const [view, setView] = useState<'preview' | 'table'>(imageSrc ? 'preview' : 'table');
  const TABLE_PAGE = 200;

  // Auto-switch to preview when image arrives after initial mount
  useEffect(() => {
    if (imageSrc) setView('preview');
  }, [!!imageSrc]);

  if (fetchError) {
    return (
      <div className="my-3 rounded-lg border border-red-500/30 bg-bg-100 px-3 py-2 text-sm text-red-400">
        Failed to load chart data: {fetchError}
      </div>
    );
  }

  const pendingImageFetch = !!message.data_image_path && !imageSrc && !fetchError;
  const nothingReady = !imageSrc && !hasData && !pendingImageFetch;
  if (!messageId || nothingReady) {
    return (
      <div className="my-3 rounded-lg border border-border-300/15 bg-bg-100 px-3 py-2 text-sm text-text-300">
        {pendingImageFetch ? (message.data_title || 'Loading chart…') : 'Loading data…'}
      </div>
    );
  }

  return (
    <div className="my-3 relative">
      <div className="rounded-lg border border-border-300/15 bg-bg-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border-300/15">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-text-000 truncate">
              {message.data_title || 'Data'}
            </span>
            {message.data_warning && (
              <span
                className="text-[11px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30"
                title={message.data_warning}
              >
                {message.data_warning}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <div className="flex rounded border border-border-300/15 overflow-hidden text-xs">
              {imageSrc && (
                <button
                  onClick={() => setView('preview')}
                  className={`px-2 py-1 ${view === 'preview' ? 'bg-accent-main-100/15 text-accent-main-100' : 'text-text-300 hover:bg-bg-200'}`}
                >
                  Chart
                </button>
              )}
              {hasData && (
                <button
                  onClick={() => setView('table')}
                  className={`px-2 py-1 ${imageSrc ? 'border-l border-border-300/15' : ''} ${view === 'table' ? 'bg-accent-main-100/15 text-accent-main-100' : 'text-text-300 hover:bg-bg-200'}`}
                >
                  Table <span className="opacity-60">({rows.length.toLocaleString()})</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Body */}
        {view === 'preview' && imageSrc ? (
          <div>
            <div className="p-3 flex justify-center">
              <img
                src={imageSrc}
                alt={message.data_title || 'Chart'}
                className="max-w-full rounded"
              />
            </div>
            {message.data_sql && <SqlDisclosure sql={message.data_sql} />}
          </div>
        ) : (
          <div className="overflow-auto max-h-80">
            {message.data_sql && (
              <SqlDisclosure sql={message.data_sql} />
            )}
            {rows.length === 0 ? (
              <div className="px-3 py-4 text-sm text-text-300">No data.</div>
            ) : (
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="sticky top-0 bg-bg-100 z-10">
                    {columns.map((col) => (
                      <th
                        key={col.name}
                        className="px-3 py-2 text-left font-medium text-text-100 border-b border-border-300/15 whitespace-nowrap"
                      >
                        {col.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, TABLE_PAGE).map((row, i) => (
                    <tr key={i} className={i % 2 === 0 ? 'bg-transparent' : 'bg-bg-000/30'}>
                      {columns.map((col) => (
                        <td
                          key={col.name}
                          className="px-3 py-1.5 text-text-200 border-b border-border-300/10 whitespace-nowrap max-w-[200px] truncate"
                          title={String(row[col.name] ?? '')}
                        >
                          {row[col.name] == null ? <span className="opacity-30">—</span> : String(row[col.name])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {rows.length > TABLE_PAGE && (
              <div className="px-3 py-2 text-xs text-text-300 border-t border-border-300/10">
                Showing first {TABLE_PAGE.toLocaleString()} of {rows.length.toLocaleString()} rows
              </div>
            )}
          </div>
        )}
      </div>

    </div>
  );
}
