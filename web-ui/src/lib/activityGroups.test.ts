import { describe, it, expect } from 'vitest';
import { groupActivity, summarizeActivity, isActivityMessage } from './activityGroups';
import type { Message } from '../types';

const user = (c: string): Message => ({ role: 'user', content: c });
const asst = (c: string): Message => ({ role: 'assistant', content: c });
const tool = (name: string): Message => ({ role: 'tool_call', content: '', tool_name: name });
const think = (): Message => ({ role: 'thinking', content: '...' });
const spawn = (): Message => ({ role: 'tool_call', content: '', tool_name: 'spawn_subagent' });
const todos = (): Message => ({ role: 'todos', content: '', todos: [] });

describe('groupActivity', () => {
  it('coalesces a run of >=2 activity messages into one group', () => {
    const items = groupActivity([user('x'), think(), tool('read_file'), tool('edit_file'), asst('done')]);
    expect(items.map(i => i.kind)).toEqual(['message', 'activity', 'message']);
    const group = items[1] as Extract<typeof items[number], { kind: 'activity' }>;
    expect(group.entries).toHaveLength(3);
  });

  it('leaves a lone activity message inline (below threshold)', () => {
    const items = groupActivity([user('x'), tool('read_file'), asst('done')]);
    expect(items.map(i => i.kind)).toEqual(['message', 'message', 'message']);
  });

  it('keeps subagent and todo cards inline (not grouped)', () => {
    expect(isActivityMessage(spawn())).toBe(false);
    expect(isActivityMessage(todos())).toBe(false);
    const items = groupActivity([tool('read_file'), spawn(), tool('edit_file'), tool('run_command')]);
    // read_file is a lone run (1) -> inline; spawn inline; edit+run -> group
    expect(items.map(i => i.kind)).toEqual(['message', 'message', 'activity']);
  });

  it('preserves original indices for actions/turn mapping', () => {
    const items = groupActivity([user('x'), think(), tool('read_file')]);
    const group = items[1] as Extract<typeof items[number], { kind: 'activity' }>;
    expect(group.entries.map(e => e.index)).toEqual([1, 2]);
  });
});

describe('summarizeActivity', () => {
  it('tallies reads/edits/commands and thinking', () => {
    const s = summarizeActivity([
      { message: think() },
      { message: tool('read_file') },
      { message: tool('list_files') },
      { message: tool('edit_file') },
      { message: tool('run_command') },
    ]);
    expect(s).toMatchObject({ steps: 4, reads: 2, edits: 1, commands: 1, thinking: 1 });
  });
});
