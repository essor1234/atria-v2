import { useState, useRef, useCallback } from 'react';
import { Paperclip, Square, SendHorizontal } from 'lucide-react';
import { DocumentIcon } from '@heroicons/react/24/outline';
import Mentions from 'rc-mentions';
import type { MentionsRef, DataDrivenOptionProps } from 'rc-mentions/es/Mentions';
import { useChatStore } from '../../stores/chat';
import { useArtifactsStore } from '../../stores/artifacts';
import { useArtifactUpload } from '../../hooks/useArtifactUpload';
import { apiClient } from '../../api/client';
import { PersonaSelector } from './PersonaSelector';
import { StatusBar } from './StatusBar';

export function InputBox() {
  const [input, setInput] = useState('');
  const [fileOptions, setFileOptions] = useState<DataDrivenOptionProps[]>([]);
  const [isMentionSearching, setIsMentionSearching] = useState(false);
  const mentionsRef = useRef<MentionsRef>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const sendMessage = useChatStore(state => state.sendMessage);
  const currentSessionId = useChatStore(state => state.currentSessionId);
  const { upload, uploading: fileUploading } = useArtifactUpload();
  const scanArtifacts = useArtifactsStore(state => state.scanArtifacts);

  const isLoading = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.isLoading ?? false : false;
  });
  const isConnected = useChatStore(state => state.isConnected);
  const hasActiveSession = !!currentSessionId;

  const isDeepResearchActive = useChatStore(state => {
    const sid = state.currentSessionId;
    if (!sid) return false;
    const msgs = state.sessionStates[sid]?.messages ?? [];
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m.role !== 'deep_research') continue;
      const s = m.dr_status;
      return s === 'reviewing' || s === 'queued' || s === 'running';
    }
    return false;
  });
  const sendLocked = isDeepResearchActive;

  const handleSend = () => {
    if (!input.trim() || !isConnected || !hasActiveSession || sendLocked) return;
    sendMessage(input.trim());
    setInput('');
    setFileOptions([]);
    setIsMentionSearching(false);
  };

  const handleStop = async () => {
    try {
      await apiClient.interruptTask();
    } catch (error) {
      console.error('Failed to interrupt task:', error);
    }
  };

  const handleChange = (text: string) => {
    setInput(text);
    // Reset searching state on each change; onSearch re-sets it if mention is still active
    setIsMentionSearching(false);
  };

  const handleSearch = async (query: string) => {
    setIsMentionSearching(true);
    try {
      const response = await apiClient.listFiles(query);
      setFileOptions(
        response.files.map(f => ({
          key: f.path,
          value: f.path,
          label: (
            <div className="flex items-center gap-2.5">
              <DocumentIcon className="w-3.5 h-3.5 text-ink/40 flex-shrink-0" />
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink truncate leading-tight">{f.name}</div>
                <div className="text-xs text-ink/50 truncate leading-tight">{f.path}</div>
              </div>
            </div>
          ),
        }))
      );
    } catch {
      setFileOptions([]);
    }
  };

  const handleSelect = () => {
    setIsMentionSearching(false);
    setFileOptions([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab' && isMentionSearching && fileOptions.length > 0) {
      e.preventDefault();
      // Trigger rc-mentions' built-in Enter selection by dispatching a native Enter keydown
      const textarea = mentionsRef.current?.textarea;
      if (textarea) {
        textarea.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true })
        );
      }
      return;
    }
    if (e.key === 'Escape') {
      setIsMentionSearching(false);
      if (isLoading) handleStop();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && !isMentionSearching) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileButtonClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileInputChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.currentTarget.files ?? []);
    e.currentTarget.value = '';
    if (!currentSessionId || files.length === 0) return;
    const convId = parseInt(currentSessionId, 10);
    if (isNaN(convId)) return;
    for (const file of files) {
      await upload(file, 'conversation', convId);
    }
    scanArtifacts(currentSessionId).catch(() => {});
  }, [currentSessionId, upload, scanArtifacts]);

  const inputPlaceholder = !hasActiveSession
    ? 'Select a session to start chatting...'
    : !isConnected
    ? 'Disconnected...'
    : sendLocked
    ? 'Deep research in progress — sending paused until it finishes…'
    : isLoading
    ? 'Type to queue a message...'
    : 'Type your message... (use @ to mention files)';

  return (
    <div className="bg-canvas border-t border-hairline-soft/50 px-4 py-3">
      <div className="w-full relative">
        <div className="rounded-xl border border-hairline-soft bg-canvas focus-within:border-ink/20 focus-within:shadow-soft transition-all duration-fast">
          <div className="flex gap-2 px-2 py-1.5 items-center">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileInputChange}
            />
            <div className="flex-1 min-w-0 mentions-input-wrapper">
              <Mentions
                ref={mentionsRef}
                prefix="@"
                value={input}
                onChange={handleChange}
                onSearch={handleSearch}
                onSelect={handleSelect}
                onKeyDown={handleKeyDown}
                options={fileOptions}
                filterOption={false}
                placement="top"
                autoSize={{ minRows: 1, maxRows: 7 }}
                notFoundContent={
                  <span className="mentions-not-found">No files found</span>
                }
                placeholder={inputPlaceholder}
                disabled={!isConnected || !hasActiveSession}
              />
            </div>
            <div className="flex gap-1.5 self-end">
              <button
                onClick={handleFileButtonClick}
                disabled={!isConnected || !hasActiveSession || fileUploading}
                className="p-1.5 rounded-lg transition-colors text-ink/30 hover:text-ink/60 hover:bg-surface-soft disabled:opacity-30 disabled:cursor-not-allowed"
                title="Upload file as artifact"
              >
                {fileUploading ? (
                  <div className="w-4 h-4 border-[1.5px] border-ink/40 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Paperclip className="w-4 h-4" />
                )}
              </button>
              {isLoading && (
                <button
                  onClick={handleStop}
                  className="p-1.5 rounded-lg transition-colors text-ink/50 hover:text-ink hover:bg-surface-soft"
                  title="Stop (Esc)"
                >
                  <Square className="w-4 h-4" />
                </button>
              )}
              <button
                onClick={handleSend}
                disabled={!input.trim() || !isConnected || !hasActiveSession || sendLocked}
                className="p-1.5 rounded-lg transition-colors bg-ink text-canvas hover:bg-ink/80 disabled:opacity-25 disabled:cursor-not-allowed"
                title="Send (Enter)"
              >
                <SendHorizontal className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {hasActiveSession && (
          <div className="flex items-center gap-3 flex-wrap mt-2 px-0.5">
            <StatusBar />
            <PersonaSelector />
          </div>
        )}
      </div>
    </div>
  );
}
