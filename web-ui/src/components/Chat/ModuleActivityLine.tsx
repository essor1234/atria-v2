import type { Message } from '../../types';

interface Props {
  message: Message;
  hasResult: boolean;
}

const GENERIC = { running: 'Working…', done: 'Done' };

export type ActivityView = { kind: 'running' | 'done' | 'error'; text: string };

/**
 * Pure helper: derives the view state from a message and whether a result has
 * arrived. Exported for unit testing without a DOM environment.
 */
export function activityView(message: Message, hasResult: boolean): ActivityView {
  const failed =
    message.tool_success === false ||
    (message.tool_result && (message.tool_result as any).success === false) ||
    !!message.tool_error;

  if (failed) return { kind: 'error', text: 'Couldn’t finish that — nothing was changed.' };

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
export function ModuleActivityLine({ message, hasResult }: Props) {
  const view = activityView(message, hasResult);

  if (view.kind === 'error') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-block-coral">
        <span aria-hidden>⚠️</span>
        <span>{view.text}</span>
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
