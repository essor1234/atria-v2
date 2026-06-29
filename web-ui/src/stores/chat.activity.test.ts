import { describe, it, expect } from 'vitest';

// Pure shape check: the tool_call WS payload maps data.activity onto the message.
function buildToolCallMessage(data: any) {
  return {
    role: 'tool_call' as const,
    content: data.description || `Calling ${data.tool_name}`,
    tool_call_id: data.tool_call_id,
    tool_name: data.tool_name,
    tool_args: data.arguments,
    tool_args_display: data.arguments_display || null,
    activity: data.activity || null,
  };
}

describe('tool_call activity mapping', () => {
  it('carries the activity payload onto the message', () => {
    const msg = buildToolCallMessage({
      tool_call_id: 'c1',
      tool_name: 'bash_execute',
      arguments: { command: 'python /m/warehouse/scripts/inventory.py receive' },
      activity: { running: 'Receiving stock…', done: 'Stock received' },
    });
    expect(msg.activity).toEqual({ running: 'Receiving stock…', done: 'Stock received' });
  });

  it('defaults activity to null when absent', () => {
    const msg = buildToolCallMessage({ tool_call_id: 'c2', tool_name: 'read_file', arguments: {} });
    expect(msg.activity).toBeNull();
  });
});
