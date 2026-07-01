import { Bot, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import type { Message } from '../../types';

interface Props {
  message: Message;
  hasResult: boolean;
}

function prettifyAgentType(raw: string): string {
  if (!raw) return 'Subagent';
  return raw
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/**
 * Distinct card for a spawned subagent. Rendered regardless of Simple Mode so the
 * spawn is always visible (not collapsed into a generic activity line). The
 * subagent's nested tool activity renders indented below via the message `depth`
 * padding already applied by MessageList.
 */
export function SubagentCard({ message, hasResult }: Props) {
  const args = message.tool_args ?? {};
  const agentType = prettifyAgentType(args.subagent_type || args.agent_type || '');
  const task: string = args.description || message.content || '';

  const result = message.tool_result as any;
  const failed =
    message.tool_success === false ||
    (result && result.success === false) ||
    !!message.tool_error;
  const running = !hasResult && !failed;

  const statusText = failed ? 'Failed' : running ? 'Running' : 'Completed';
  const summary =
    typeof message.tool_summary === 'string'
      ? message.tool_summary
      : Array.isArray(message.tool_summary)
        ? message.tool_summary.join(' ')
        : '';

  return (
    <section
      className={`rounded-md border overflow-hidden bg-surface-soft/30 ${
        running ? 'border-hairline-soft/60 tool-executing' : failed ? 'border-block-coral/40' : 'border-hairline-soft/60'
      }`}
      aria-label={`Subagent ${agentType}, ${statusText}`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Bot className="w-3.5 h-3.5 text-ink/50 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
        <span className="text-[13px] font-[500] text-ink/75">{agentType}</span>
        {task && (
          <span className="text-[12px] text-ink/45 truncate max-w-[280px]">{task}</span>
        )}
        <span className="ml-auto flex items-center gap-1.5 flex-shrink-0">
          {running ? (
            <Loader2 className="w-3.5 h-3.5 text-ink/55 animate-spin motion-reduce:animate-none" strokeWidth={2} aria-hidden="true" />
          ) : failed ? (
            <AlertCircle className="w-3.5 h-3.5 text-block-coral" strokeWidth={2} aria-hidden="true" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 text-semantic-success" strokeWidth={2} aria-hidden="true" />
          )}
          <span
            className={`text-[12px] font-[450] ${
              failed ? 'text-block-coral' : running ? 'text-ink/50' : 'text-semantic-success'
            }`}
          >
            {statusText}
          </span>
        </span>
      </div>

      {!running && summary && (
        <div className="px-3 pb-2 pl-[30px] text-[12px] leading-5 text-ink/45 font-mono">
          {summary}
        </div>
      )}
    </section>
  );
}
