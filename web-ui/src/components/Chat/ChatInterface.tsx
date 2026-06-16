import { useCallback, useEffect, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload } from 'lucide-react';
import { useChatStore } from '../../stores/chat';
import { useArtifactsStore } from '../../stores/artifacts';
import { useToastStore } from '../../stores/toast';
import { useArtifactUpload } from '../../hooks/useArtifactUpload';
import { apiClient } from '../../api/client';
import { MessageList } from './MessageList';
import { QueueBar } from './QueueBar';
import { InputBox } from './InputBox';
import { LandingPage } from './LandingPage';

export function ChatInterface() {
  const error = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.error ?? null : null;
  });
  const currentSessionId = useChatStore(state => state.currentSessionId);
  const loadSession = useChatStore(state => state.loadSession);
  const [bridgeChecked, setBridgeChecked] = useState(false);
  const addToast = useToastStore(state => state.addToast);

  const { upload, uploading } = useArtifactUpload();
  const scanArtifacts = useArtifactsStore(state => state.scanArtifacts);

  // Auto-join TUI session in bridge mode
  useEffect(() => {
    let cancelled = false;
    apiClient.getBridgeInfo().then(info => {
      if (cancelled) return;
      if (info.bridge_mode && info.session_id) {
        loadSession(info.session_id);
      }
      setBridgeChecked(true);
    }).catch(() => {
      if (!cancelled) setBridgeChecked(true);
    });
    return () => { cancelled = true; };
  }, [loadSession]);

  const { getRootProps, isDragActive } = useDropzone({
    onDrop: useCallback(async (acceptedFiles: File[]) => {
      if (!currentSessionId || acceptedFiles.length === 0) return;
      const convId = parseInt(currentSessionId, 10);
      if (isNaN(convId)) return;
      let uploaded = 0;
      for (const file of acceptedFiles) {
        const result = await upload(file, 'conversation', convId);
        if (result) uploaded++;
      }
      if (uploaded > 0) {
        scanArtifacts(currentSessionId).catch(() => {});
        addToast(
          uploaded === 1
            ? `"${acceptedFiles[0].name}" uploaded`
            : `${uploaded} files uploaded`,
          'success',
          3000,
        );
      }
    }, [currentSessionId, upload, scanArtifacts, addToast]),
    noClick: true,
    noKeyboard: true,
    disabled: !currentSessionId,
  });

  // Brief null render while checking bridge info (imperceptible)
  if (!bridgeChecked && !currentSessionId) {
    return null;
  }

  if (!currentSessionId) {
    return <LandingPage />;
  }

  return (
    <div
      {...getRootProps()}
      className="flex flex-col h-full relative animate-fade-in"
    >
      {error && (
        <div className="bg-red-50 border border-semantic-danger text-semantic-danger px-4 py-3 mx-6 mt-4 rounded-lg">
          <strong className="font-semibold">Error:</strong> {error}
        </div>
      )}

      <MessageList />
      <QueueBar />
      <InputBox />

      {/* Drag-and-drop overlay */}
      {isDragActive && (
        <div className="absolute inset-0 z-50 flex items-center justify-center pointer-events-none">
          <div className="absolute inset-0 bg-accent-main-100/10 border-2 border-dashed border-accent-main-100 rounded-lg m-2" />
          <div className="relative bg-canvas border border-hairline-soft rounded-xl px-6 py-4 shadow-soft flex items-center gap-3">
            <Upload className="w-6 h-6 text-accent-main-100" />
            <span className="text-sm font-medium text-ink">Drop files to upload as artifacts</span>
          </div>
        </div>
      )}

      {/* Upload progress indicator */}
      {uploading && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-40 bg-canvas border border-hairline-soft rounded-lg px-4 py-2 shadow-md flex items-center gap-2 text-sm text-ink">
          <div className="w-3 h-3 border-2 border-accent-main-100 border-t-transparent rounded-full animate-spin" />
          Uploading…
        </div>
      )}

    </div>
  );
}
