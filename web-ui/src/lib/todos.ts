import type { Message, Todo } from '../types';

/**
 * Pure reducer for the `todos_updated` event, with timeline semantics that
 * match the backend persistence (web_ui_callback._persist_todos):
 *
 * - If the LAST message is a `todos` card, update it in place — a contiguous
 *   run of todo updates collapses into one card.
 * - Otherwise append a new card, so a `todos` update that follows other
 *   activity starts a fresh timeline checkpoint.
 * - An empty list removes a trailing card (clear_todos).
 *
 * Targeting the trailing card (not the first match) keeps live updates and
 * reload-rehydrated history consistent: after reload there may be several
 * persisted snapshots, and new updates must continue the latest one.
 *
 * Returns the original array reference when nothing changes so callers can skip
 * a state update.
 */
export function applyTodosUpdate(
  messages: Message[],
  todos: Todo[],
  timestamp: string,
): Message[] {
  const lastIdx = messages.length - 1;
  const lastIsTodos = lastIdx >= 0 && messages[lastIdx].role === 'todos';

  if (todos.length === 0) {
    return lastIsTodos ? messages.slice(0, -1) : messages;
  }

  if (lastIsTodos) {
    const next = [...messages];
    next[lastIdx] = { ...next[lastIdx], todos, timestamp };
    return next;
  }

  return [...messages, { role: 'todos', content: '', todos, timestamp }];
}
