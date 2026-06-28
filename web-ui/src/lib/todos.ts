import type { Message, Todo } from '../types';

/**
 * Pure reducer for the `todos_updated` event: keep exactly one `todos` card in
 * the message flow, updating it in place; an empty list removes the card.
 *
 * Returns the original array reference when nothing changes so callers can skip
 * a state update.
 */
export function applyTodosUpdate(
  messages: Message[],
  todos: Todo[],
  timestamp: string,
): Message[] {
  const existingIdx = messages.findIndex(m => m.role === 'todos');

  if (todos.length === 0) {
    return existingIdx === -1 ? messages : messages.filter(m => m.role !== 'todos');
  }

  if (existingIdx !== -1) {
    const next = [...messages];
    next[existingIdx] = { ...next[existingIdx], todos };
    return next;
  }

  return [...messages, { role: 'todos', content: '', todos, timestamp }];
}
