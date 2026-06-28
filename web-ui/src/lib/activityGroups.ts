import type { Message } from '../types';

/** One entry in a render list: either a standalone message or a coalesced
 *  group of intra-turn "activity" (thinking + tool exec) messages. */
export type RenderItem =
  | { kind: 'message'; message: Message; index: number }
  | { kind: 'activity'; key: string; entries: Array<{ message: Message; index: number }> };

/** Minimum consecutive activity messages before we collapse them into a group.
 *  A lone tool call or thinking block is left inline (not worth a disclosure). */
export const ACTIVITY_GROUP_MIN = 2;

const ACTIVITY_ROLES = new Set(['thinking', 'tool_call', 'tool_result', 'search_result']);

/** Whether a message is low-signal "activity" that should fold into a group.
 *  Subagent cards and todo cards are deliberately surfaced, so they stay inline. */
export function isActivityMessage(m: Message): boolean {
  if (m.role === 'tool_call' && m.tool_name === 'spawn_subagent') return false;
  return ACTIVITY_ROLES.has(m.role);
}

/**
 * Coalesce runs of consecutive activity messages into `activity` groups so the
 * real conversation (user/assistant text, todo + subagent cards) stays
 * prominent. Runs shorter than {@link ACTIVITY_GROUP_MIN} are emitted inline.
 */
export function groupActivity(messages: Message[]): RenderItem[] {
  const items: RenderItem[] = [];
  let buf: Array<{ message: Message; index: number }> = [];

  const flush = () => {
    if (buf.length === 0) return;
    if (buf.length >= ACTIVITY_GROUP_MIN) {
      items.push({ kind: 'activity', key: `act-${buf[0].index}`, entries: buf });
    } else {
      for (const e of buf) items.push({ kind: 'message', message: e.message, index: e.index });
    }
    buf = [];
  };

  messages.forEach((message, index) => {
    if (isActivityMessage(message)) {
      buf.push({ message, index });
    } else {
      flush();
      items.push({ kind: 'message', message, index });
    }
  });
  flush();
  return items;
}

const READ_TOOLS = new Set([
  'read_file', 'read_pdf', 'list_files', 'list_directory', 'search', 'search_code',
  'web_search', 'fetch_url', 'find_symbol', 'find_referencing_symbols',
]);
const EDIT_TOOLS = new Set([
  'write_file', 'edit_file', 'apply_patch', 'notebook_edit',
  'insert_before_symbol', 'insert_after_symbol', 'replace_symbol_body', 'rename_symbol',
]);
const COMMAND_TOOLS = new Set(['run_command', 'bash_execute']);

export interface ActivitySummary {
  steps: number;
  reads: number;
  edits: number;
  commands: number;
  thinking: number;
  other: number;
}

/** Tally an activity group's entries into coarse buckets for the collapsed header. */
export function summarizeActivity(entries: Array<{ message: Message }>): ActivitySummary {
  const s: ActivitySummary = { steps: 0, reads: 0, edits: 0, commands: 0, thinking: 0, other: 0 };
  for (const { message } of entries) {
    if (message.role === 'thinking') { s.thinking++; continue; }
    if (message.role !== 'tool_call') continue; // tool_result/search_result fold into their call
    s.steps++;
    const name = message.tool_name ?? '';
    if (READ_TOOLS.has(name)) s.reads++;
    else if (EDIT_TOOLS.has(name)) s.edits++;
    else if (COMMAND_TOOLS.has(name)) s.commands++;
    else s.other++;
  }
  return s;
}
