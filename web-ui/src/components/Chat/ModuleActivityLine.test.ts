import { describe, it, expect } from 'vitest';
import { activityView } from './ModuleActivityLine';
import type { Message } from '../../types';

function msg(over: Partial<Message>): Message {
  return { role: 'tool_call', content: '', timestamp: '', ...over } as Message;
}

describe('activityView', () => {
  it('shows running label while running with activity', () => {
    const result = activityView(
      msg({ activity: { running: 'Receiving stock…', done: 'Stock received' } }),
      false,
    );
    expect(result).toEqual({ kind: 'running', text: 'Receiving stock…' });
  });

  it('shows done label after completion with activity', () => {
    const result = activityView(
      msg({
        activity: { running: 'Receiving stock…', done: 'Stock received' },
        tool_success: true,
      }),
      true,
    );
    expect(result).toEqual({ kind: 'done', text: 'Stock received' });
  });

  it('returns error kind when tool_success is false', () => {
    const result = activityView(msg({ tool_success: false }), true);
    expect(result.kind).toBe('error');
    expect(result.text).toContain('Couldn’t finish that');
  });

  it('returns error kind when tool_error is set', () => {
    const result = activityView(msg({ tool_error: 'boom' }), false);
    expect(result.kind).toBe('error');
    expect(result.text).toContain('Couldn’t finish that');
  });

  it('returns error kind when tool_result.success is false', () => {
    const result = activityView(msg({ tool_result: { success: false } }), true);
    expect(result.kind).toBe('error');
  });

  it('falls back to generic running label with no activity', () => {
    const result = activityView(msg({}), false);
    expect(result).toEqual({ kind: 'running', text: 'Working…' });
  });

  it('falls back to generic done label with no activity and hasResult', () => {
    const result = activityView(msg({}), true);
    expect(result).toEqual({ kind: 'done', text: 'Done' });
  });
});
