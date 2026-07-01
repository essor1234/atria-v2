import { describe, it, expect } from 'vitest';
import { applyTodosUpdate } from './todos';
import type { Message, Todo } from '../types';

const T = (id: string, status: Todo['status'], title = id): Todo => ({ id, title, status });
const base: Message[] = [
  { role: 'user', content: 'hi' },
  { role: 'assistant', content: 'ok' },
];

describe('applyTodosUpdate', () => {
  it('appends a single todos card on first update', () => {
    const next = applyTodosUpdate(base, [T('todo-1', 'todo')], 'ts');
    expect(next).toHaveLength(3);
    expect(next[2].role).toBe('todos');
    expect(next[2].todos).toHaveLength(1);
  });

  it('updates the existing card in place (no duplicate, same position)', () => {
    const first = applyTodosUpdate(base, [T('todo-1', 'todo')], 'ts');
    const idx = first.findIndex(m => m.role === 'todos');
    const second = applyTodosUpdate(first, [T('todo-1', 'doing')], 'ts');
    expect(second.filter(m => m.role === 'todos')).toHaveLength(1);
    expect(second.findIndex(m => m.role === 'todos')).toBe(idx);
    expect(second[idx].todos?.[0].status).toBe('doing');
  });

  it('removes the card when the list becomes empty (clear_todos)', () => {
    const first = applyTodosUpdate(base, [T('todo-1', 'todo')], 'ts');
    const cleared = applyTodosUpdate(first, [], 'ts');
    expect(cleared.some(m => m.role === 'todos')).toBe(false);
    expect(cleared).toHaveLength(2);
  });

  it('returns the same reference when empty and no card exists (no-op)', () => {
    const next = applyTodosUpdate(base, [], 'ts');
    expect(next).toBe(base);
  });
});
