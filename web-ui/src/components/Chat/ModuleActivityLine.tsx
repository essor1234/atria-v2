import type { Message } from '../../types';

interface Props {
  message: Message;
  hasResult: boolean;
}

const GENERIC = { running: 'Working…', done: 'Done' };

export type ActivityView = {
  kind: 'running' | 'done' | 'error';
  text: string;
  /** Verbose error detail — tool name, raw error, stack hint. Only set on error. */
  detail?: string;
  /** Machine-readable payload for the debug popover (only on error). */
  debug?: {
    tool?: string;
    args?: Record<string, unknown>;
    error?: string;
    result?: unknown;
    call_id?: string;
  };
};

/**
 * Extract a human-readable error string from every place the backend might
 * stash it: `tool_error`, `tool_result.error`, `tool_result.content` when
 * `success === false`, or the stringified result as a last resort.
 */
function extractError(message: Message): string {
  if (message.tool_error) return String(message.tool_error);
  const r = message.tool_result as any;
  if (r && typeof r === 'object') {
    if (r.error) return String(r.error);
    if (r.success === false && r.content) return String(r.content);
    if (r.message) return String(r.message);
  }
  if (typeof r === 'string' && r) return r;
  return 'no error message';
}

/**
 * Pure helper: derives the view state from a message and whether a result has
 * arrived. Exported for unit testing without a DOM environment.
 */
export function activityView(message: Message, hasResult: boolean): ActivityView {
  const failed =
    message.tool_success === false ||
    (message.tool_result && (message.tool_result as any).success === false) ||
    !!message.tool_error;

  if (failed) {
    const err = extractError(message);
    const tool = message.tool_name || 'tool';
    const firstLine = err.split('\n')[0].trim();
    return {
      kind: 'error',
      text: `Couldn’t finish — ${tool} failed: ${firstLine}`,
      detail: err,
      debug: {
        tool: message.tool_name,
        args: message.tool_args,
        error: err,
        result: message.tool_result,
        call_id: message.tool_call_id,
      },
    };
  }

  const labels = message.activity ?? GENERIC;
  return hasResult
    ? { kind: 'done', text: labels.done }
    : { kind: 'running', text: labels.running };
}

/**
 * Friendly, non-technical activity line shown in Simple Mode in place of the
 * technical tool-call card. No commands, paths, or buttons — just plain
 * language with a spinner while running and a quiet checkmark when done.
 */
import { useState } from 'react';

export function ModuleActivityLine({ message, hasResult }: Props) {
  const view = activityView(message, hasResult);
  const [expanded, setExpanded] = useState(false);

  if (view.kind === 'error') {
    const debugJson = view.debug
      ? JSON.stringify(view.debug, null, 2)
      : '';
    return (
      <div className="px-3 py-2 text-[13px] text-block-coral space-y-1">
        <div className="flex items-start gap-2">
          <span aria-hidden className="mt-0.5">⚠️</span>
          <span className="flex-1 break-words">{view.text}</span>
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="text-[11px] font-mono opacity-70 hover:opacity-100 transition-opacity flex-shrink-0"
            aria-label={expanded ? 'Hide error detail' : 'Show error detail'}
          >
            {expanded ? '− hide' : '+ details'}
          </button>
        </div>
        {expanded && (
          <pre
            className="ml-6 text-[11px] font-mono whitespace-pre-wrap break-words bg-block-coral/10 border border-block-coral/30 rounded-md px-2 py-1.5 max-h-64 overflow-auto"
            aria-label="Error debug payload"
          >
{debugJson || view.detail}
          </pre>
        )}
      </div>
    );
  }

  if (view.kind === 'running') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-ink/70">
        <span className="inline-block w-3 h-3 border-[1.5px] border-ink/30 border-t-transparent rounded-full animate-spin flex-shrink-0" />
        <span>{view.text}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-semantic-success">
      <span aria-hidden>✅</span>
      <span>{view.text}</span>
    </div>
  );
}
