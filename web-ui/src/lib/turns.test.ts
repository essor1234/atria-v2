import { describe, it, expect } from 'vitest';
import { computeTurns, serializeMessageForClipboard, serializeTurnForClipboard } from './turns';
import type { Message } from '../types';

const u = (content: string): Message => ({ role: 'user', content });
const a = (content: string): Message => ({ role: 'assistant', content });
const tc = (name: string, summary: string): Message => ({
  role: 'tool_call',
  content: '',
  tool_name: name,
  tool_args: { x: 1 },
  tool_summary: summary,
});

describe('computeTurns', () => {
  it('returns one turn per user message, extending to next user', () => {
    const msgs = [u('hi'), a('hello'), tc('bash', 'ran'), u('again'), a('ok')];
    const turns = computeTurns(msgs);
    expect(turns).toEqual([
      { turnId: 'turn-0', startIndex: 0, endIndex: 2 },
      { turnId: 'turn-3', startIndex: 3, endIndex: 4 },
    ]);
  });

  it('handles transcript that does not start with a user message', () => {
    const msgs = [a('orphan'), u('hi'), a('hello')];
    const turns = computeTurns(msgs);
    expect(turns).toEqual([
      { turnId: 'turn-0', startIndex: 0, endIndex: 0 },
      { turnId: 'turn-1', startIndex: 1, endIndex: 2 },
    ]);
  });

  it('returns empty for empty input', () => {
    expect(computeTurns([])).toEqual([]);
  });
});

describe('serializeMessageForClipboard', () => {
  it('strips simple markdown from assistant text', () => {
    const m: Message = { role: 'assistant', content: '**bold** and `code` and _i_' };
    expect(serializeMessageForClipboard(m)).toBe('bold and code and i');
  });

  it('renders tool_call with summary', () => {
    expect(serializeMessageForClipboard(tc('bash', 'exit 0'))).toContain('[tool: bash]');
    expect(serializeMessageForClipboard(tc('bash', 'exit 0'))).toContain('exit 0');
  });

  it('falls back to placeholder for empty image message', () => {
    const m: Message = { role: 'image_message', content: '' };
    expect(serializeMessageForClipboard(m)).toBe('[image]');
  });
});

describe('serializeTurnForClipboard', () => {
  it('joins items with double newline and skips system', () => {
    const msgs: Message[] = [
      u('hi'),
      { role: 'system', content: 'hidden' },
      a('hello'),
    ];
    const turn = { turnId: 'turn-0', startIndex: 0, endIndex: 2 };
    const out = serializeTurnForClipboard(msgs, turn);
    expect(out).toBe('hi\n\nhello');
  });

  it('returns [empty turn] when nothing serializes', () => {
    const msgs: Message[] = [{ role: 'system', content: '' }];
    const turn = { turnId: 'turn-0', startIndex: 0, endIndex: 0 };
    expect(serializeTurnForClipboard(msgs, turn)).toBe('[empty turn]');
  });
});
