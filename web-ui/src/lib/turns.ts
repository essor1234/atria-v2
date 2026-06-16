import type { Message } from '../types';

export interface TurnInfo {
  turnId: string;
  startIndex: number;
  endIndex: number; // inclusive
}

export function computeTurns(messages: Message[]): TurnInfo[] {
  if (messages.length === 0) return [];
  const turns: TurnInfo[] = [];
  let cursor = 0;

  // Leading non-user prefix becomes a turn rooted at index 0.
  if (messages[0].role !== 'user') {
    let end = 0;
    while (end + 1 < messages.length && messages[end + 1].role !== 'user') end++;
    turns.push({ turnId: 'turn-0', startIndex: 0, endIndex: end });
    cursor = end + 1;
  }

  while (cursor < messages.length) {
    const start = cursor;
    let end = cursor;
    while (end + 1 < messages.length && messages[end + 1].role !== 'user') end++;
    turns.push({ turnId: `turn-${start}`, startIndex: start, endIndex: end });
    cursor = end + 1;
  }

  return turns;
}

const MARKDOWN_STRIP_RE = /(\*\*|__|`+|^#{1,6}\s*|^\s*[-*+]\s+|^\s*\d+\.\s+|_(?=\w))/gm;

function stripMarkdown(text: string): string {
  return text.replace(MARKDOWN_STRIP_RE, '').replace(/[*_`]/g, '').trim();
}

const TOOL_RESULT_BYTE_CAP = 4096;
function truncate(s: string, cap = TOOL_RESULT_BYTE_CAP): string {
  return s.length > cap ? s.slice(0, cap) + '…' : s;
}

export function serializeMessageForClipboard(m: Message): string {
  switch (m.role) {
    case 'user':
    case 'assistant': {
      const stripped = stripMarkdown(m.content);
      return stripped || m.content;
    }
    case 'thinking':
      return `[thinking] ${m.content}`;
    case 'tool_call': {
      const argText = m.tool_args_display ?? JSON.stringify(m.tool_args ?? {});
      const result =
        typeof m.tool_summary === 'string'
          ? m.tool_summary
          : Array.isArray(m.tool_summary)
            ? m.tool_summary.join('\n')
            : (m.tool_result && typeof m.tool_result === 'string'
              ? m.tool_result
              : m.tool_result
                ? JSON.stringify(m.tool_result)
                : '');
      return `[tool: ${m.tool_name ?? 'unknown'}] ${argText}\n→ ${truncate(result)}`;
    }
    case 'tool_result':
      return ''; // collapsed into its parent tool_call
    case 'search_result': {
      const items = (m.search_results ?? [])
        .map(r => `  - ${r.title} — ${r.url}`)
        .join('\n');
      return `[search: ${m.search_query ?? ''}]\n${items}`;
    }
    case 'image_message':
      return m.image_caption || '[image]';
    case 'data_message':
      return `[data: ${m.data_title ?? m.data_message_id ?? ''}]`;
    case 'deep_research':
      return `[deep research: ${m.dr_topic ?? ''}]`;
    case 'deep_analyze':
      return `[deep analyze: ${m.da_job_id ?? ''}]`;
    case 'custom_block':
      return `[block: ${m.block_title ?? m.block_id ?? ''}]`;
    case 'system':
      return '';
    default:
      return m.content || '';
  }
}

export function serializeTurnForClipboard(messages: Message[], turn: TurnInfo): string {
  const parts: string[] = [];
  for (let i = turn.startIndex; i <= turn.endIndex; i++) {
    const s = serializeMessageForClipboard(messages[i]);
    if (s) parts.push(s);
  }
  return parts.length === 0 ? '[empty turn]' : parts.join('\n\n');
}
