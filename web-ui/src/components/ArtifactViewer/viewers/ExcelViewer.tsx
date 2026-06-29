import { useEffect, useMemo, useRef, useState } from 'react';
import * as XLSX from 'xlsx';
import { apiClient } from '../../../api/client';
import { BinaryFallback } from './BinaryFallback';
import { wsClient } from '../../../api/websocket';
import { fsScopeKey, type FsScope, type WSMessage } from '../../../types';
import { createUniverInstance, type UniverHandle } from './excel/setupUniver';
import {
  workbookToSnapshot,
  snapshotToWorkbook,
  type UniverWorkbook,
} from './excel/xlsxBridge';

interface Props {
  scope: FsScope;
  path: string;
}

type SaveStatus = 'idle' | 'pending' | 'confirming' | 'saving' | 'saved' | 'error';

const SAVE_DEBOUNCE_MS = 1000;
const LARGE_WORKBOOK_BYTES = 5 * 1024 * 1024;

function lossyAckKey(scope: FsScope, path: string): string {
  return `atria.xlsx.lossyAck.${fsScopeKey(scope)}.${path}`;
}

export function ExcelViewer({ scope, path }: Props) {
  const scopeKey = useMemo(() => fsScopeKey(scope), [scope]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<UniverHandle | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ignoreNextChangeRef = useRef(false);

  const [loadError, setLoadError] = useState<string | null>(null);
  const [parsing, setParsing] = useState(true);
  const [largeWarning, setLargeWarning] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showLossyModal, setShowLossyModal] = useState(false);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [remoteChange, setRemoteChange] = useState(false);

  const persistSave = async () => {
    const handle = handleRef.current;
    if (!handle) return;
    setSaveStatus('saving');
    setSaveError(null);
    try {
      const snapshot = handle.univerAPI.getActiveWorkbook().save() as UniverWorkbook;
      const wb = snapshotToWorkbook(snapshot);
      const bytes = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as Uint8Array;
      ignoreNextChangeRef.current = true;
      await apiClient.writeFsBinary(scope, path, bytes);
      setSaveStatus('saved');
    } catch (err) {
      ignoreNextChangeRef.current = false;
      setSaveStatus('error');
      setSaveError(err instanceof Error ? err.message : String(err));
      console.error('[ExcelViewer] save failed', err);
    }
  };

  const scheduleSave = () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    const ackd = localStorage.getItem(lossyAckKey(scope, path)) === '1';
    if (!ackd) {
      setSaveStatus('confirming');
      setShowLossyModal(true);
      return;
    }
    setSaveStatus('pending');
    saveTimerRef.current = setTimeout(() => {
      void persistSave();
    }, SAVE_DEBOUNCE_MS);
  };

  useEffect(() => {
    let cancelled = false;
    setParsing(true);
    setLoadError(null);
    setLargeWarning(false);
    setSaveStatus('idle');
    setRemoteChange(false);

    apiClient
      .readFsBlob(scope, path)
      .then(async (blob) => {
        if (cancelled) return;
        if (blob.size > LARGE_WORKBOOK_BYTES) setLargeWarning(true);
        const buf = await blob.arrayBuffer();
        const wb = XLSX.read(buf, {
          type: 'array',
          cellFormula: true,
          cellNF: true,
          cellStyles: true,
        });
        const snapshot = workbookToSnapshot(wb);
        if (cancelled) return;
        const container = containerRef.current;
        if (!container) return;
        handleRef.current?.dispose();
        handleRef.current = createUniverInstance(container, snapshot);
        setParsing(false);

        const univerAPI = handleRef.current.univerAPI;
        const disposable = univerAPI.addEvent(
          univerAPI.Event.CommandExecuted,
          (event: { id?: string }) => {
            const id = event?.id ?? '';
            if (!id.startsWith('sheet.mutation.')) return;
            scheduleSave();
          },
        );
        const baseDispose = handleRef.current.dispose;
        handleRef.current.dispose = () => {
          try {
            disposable?.dispose?.();
          } catch {
            /* noop */
          }
          baseDispose();
        };
      })
      .catch((e) => {
        if (!cancelled) setLoadError(String(e));
      });

    return () => {
      cancelled = true;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      handleRef.current?.dispose();
      handleRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey, path]);

  useEffect(() => {
    const unsubscribe = wsClient.on('artifact.changed', (msg: WSMessage) => {
      const d = msg as {
        scope?: string;
        conversation_id?: number;
        module?: string;
        path?: string;
      };
      if (d.path !== path) return;
      if (scope.kind === 'conv' && (d.scope !== 'conv' || d.conversation_id !== scope.id))
        return;
      if (scope.kind === 'module' && (d.scope !== 'module' || d.module !== scope.name))
        return;
      if (ignoreNextChangeRef.current) {
        ignoreNextChangeRef.current = false;
        return;
      }
      setRemoteChange(true);
    });
    return () => unsubscribe();
  }, [scopeKey, path, scope]);

  const handleConfirmLossySave = () => {
    if (dontShowAgain) localStorage.setItem(lossyAckKey(scope, path), '1');
    setShowLossyModal(false);
    setSaveStatus('pending');
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      void persistSave();
    }, SAVE_DEBOUNCE_MS);
  };

  const handleCancelLossySave = () => {
    try {
      const undoMgr = handleRef.current?.univerAPI.getUndoRedoManager?.();
      while (undoMgr?.canUndo?.()) {
        undoMgr.undo();
      }
    } catch (err) {
      console.warn('[ExcelViewer] undo on cancel failed', err);
    }
    setShowLossyModal(false);
    setSaveStatus('idle');
  };

  const handleReloadRemote = async () => {
    setRemoteChange(false);
    const container = containerRef.current;
    if (!container) return;
    const blob = await apiClient.readFsBlob(scope, path);
    const buf = await blob.arrayBuffer();
    const wb = XLSX.read(buf, {
      type: 'array',
      cellFormula: true,
      cellNF: true,
      cellStyles: true,
    });
    const snapshot = workbookToSnapshot(wb);
    handleRef.current?.dispose();
    handleRef.current = createUniverInstance(container, snapshot);
    setParsing(false);
  };

  if (loadError) {
    return <BinaryFallback path={path} url={apiClient.readFsUrl(scope, path)} />;
  }

  const statusLabel: Record<SaveStatus, string> = {
    idle: '',
    pending: 'editing…',
    confirming: 'awaiting confirmation',
    saving: 'saving…',
    saved: 'saved',
    error: saveError ? `error: ${saveError}` : 'error',
  };

  return (
    <div className="flex flex-col h-full relative">
      <div className="flex items-center gap-3 px-3 py-1.5 text-[12px] font-mono border-b border-hairline-soft bg-surface-soft/70">
        <span className="text-ink/65">Excel</span>
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
        {largeWarning && (
          <span className="text-ink/45">Large workbook — saving may stutter.</span>
        )}
        {remoteChange && (
          <span className="ml-auto flex items-center gap-2 text-ink/65">
            File changed elsewhere.
            <button
              type="button"
              onClick={handleReloadRemote}
              className="px-2 py-0.5 rounded border border-hairline-soft hover:bg-canvas"
            >
              Reload
            </button>
          </span>
        )}
      </div>

      {parsing && (
        <div className="p-4 text-xs font-mono text-ink/45">Parsing workbook…</div>
      )}

      <div ref={containerRef} className="flex-1 min-h-0" />

      {showLossyModal && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30">
          <div className="max-w-md rounded border border-hairline-soft bg-canvas p-4 text-[13px] font-mono shadow-lg">
            <p className="mb-3 text-ink">
              Saving will preserve cells, formulas, and basic formatting. Charts,
              images, pivot tables, conditional formatting, and data-validation
              rules in this file will be removed.
            </p>
            <label className="mb-3 flex items-center gap-2 text-ink/70">
              <input
                type="checkbox"
                checked={dontShowAgain}
                onChange={(e) => setDontShowAgain(e.target.checked)}
              />
              Don&apos;t show again for this file
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={handleCancelLossySave}
                className="px-3 py-1 rounded border border-hairline-soft hover:bg-surface-soft"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmLossySave}
                className="px-3 py-1 rounded bg-ink/85 text-canvas hover:bg-ink"
              >
                Save anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
