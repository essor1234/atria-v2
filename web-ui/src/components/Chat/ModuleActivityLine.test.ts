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
    const result = activityView(
      msg({ tool_success: false, tool_name: 'spawn_subagent', tool_error: 'boom' }),
      true,
    );
    expect(result.kind).toBe('error');
    expect(result.text).toContain('spawn_subagent');
    expect(result.text).toContain('boom');
    expect(result.detail).toBe('boom');
    expect(result.debug?.tool).toBe('spawn_subagent');
  });

  it('returns error kind when tool_error is set (surfaces error inline)', () => {
    const result = activityView(msg({ tool_name: 'read_file', tool_error: 'ENOENT: foo' }), false);
    expect(result.kind).toBe('error');
    expect(result.text).toContain('read_file');
    expect(result.text).toContain('ENOENT: foo');
    expect(result.debug?.error).toBe('ENOENT: foo');
  });

  it('returns error kind when tool_result.success is false and pulls error from content', () => {
    const result = activityView(
      msg({
        tool_name: 'spawn_subagent',
        tool_result: { success: false, content: "'NoneType' object is not subscriptable" },
      }),
      true,
    );
    expect(result.kind).toBe('error');
    expect(result.text).toContain('NoneType');
    expect(result.detail).toContain('NoneType');
  });

  it('only shows first line of multiline error in headline; full text goes to detail', () => {
    const result = activityView(
      msg({ tool_name: 'divide', tool_error: 'boom\ntraceback line 1\ntraceback line 2' }),
      true,
    );
    expect(result.text).toContain('boom');
    expect(result.text).not.toContain('traceback line 1');
    expect(result.detail).toContain('traceback line 1');
    expect(result.detail).toContain('traceback line 2');
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
