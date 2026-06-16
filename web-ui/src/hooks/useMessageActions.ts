import { useCallback } from 'react';
import { useChatStore } from '../stores/chat';
import { useToastStore } from '../stores/toast';
import { writeClipboardText } from '../lib/clipboard';
import {
  serializeMessageForClipboard,
  serializeTurnForClipboard,
  type TurnInfo,
} from '../lib/turns';
import type { Message } from '../types';

export function useMessageActions() {
  const sessionId = useChatStore(s => s.currentSessionId);
  const deleteTurn = useChatStore(s => s.deleteTurn);
  const messages = useChatStore(s => {
    const sid = s.currentSessionId;
    return sid ? s.sessionStates[sid]?.messages ?? [] : [];
  });
  const isLoading = useChatStore(s => {
    const sid = s.currentSessionId;
    return sid ? s.sessionStates[sid]?.isLoading ?? false : false;
  });

  const copyMessage = useCallback(async (m: Message) => {
    const text = serializeMessageForClipboard(m) || m.content;
    const ok = await writeClipboardText(text);
    useToastStore.getState().addToast(
      ok ? 'Copied message' : 'Copy failed',
      ok ? 'success' : 'error',
    );
  }, []);

  const copyTurn = useCallback(async (turn: TurnInfo) => {
    const ok = await writeClipboardText(serializeTurnForClipboard(messages, turn));
    useToastStore.getState().addToast(
      ok ? 'Copied turn' : 'Copy failed',
      ok ? 'success' : 'error',
    );
  }, [messages]);

  const deleteTurnAction = useCallback(async (turn: TurnInfo) => {
    if (!sessionId) return;
    await deleteTurn(sessionId, turn.startIndex);
  }, [sessionId, deleteTurn]);

  return { copyMessage, copyTurn, deleteTurn: deleteTurnAction, isLoading };
}
