import { Circle, CheckCircle2, Loader2, ListChecks } from 'lucide-react';
import type { Message, Todo } from '../../types';

interface Props {
  message: Message;
}

/**
 * Live task checklist rendered inline in the chat flow. Driven by the
 * `todos_updated` WS event; the same card updates in place as the agent moves
 * items through todo -> doing -> done.
 */
export function TodoListCard({ message }: Props) {
  const todos: Todo[] = message.todos ?? [];
  if (todos.length === 0) return null;

  const done = todos.filter(t => t.status === 'done').length;
  const total = todos.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <section
      className="rounded-md border border-hairline-soft/60 overflow-hidden bg-surface-soft/30"
      aria-label={`Tasks, ${done} of ${total} done`}
    >
      {/* Header: label + progress count + bar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-hairline-soft/40">
        <ListChecks className="w-3.5 h-3.5 text-ink/45 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
        <span className="text-[13px] font-[500] text-ink/70">Tasks</span>
        <span className="text-[12px] text-ink/40 font-mono ml-0.5">{done}/{total} done</span>
        <div
          className="ml-auto h-1 w-20 rounded-full bg-hairline-soft/50 overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
        >
          <div
            className="h-full bg-semantic-success transition-all duration-base ease-motion-out"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Items */}
      <ul className="py-1">
        {todos.map(todo => (
          <li key={todo.id} className="flex items-start gap-2 px-3 py-1">
            {todo.status === 'done' ? (
              <CheckCircle2 className="w-3.5 h-3.5 mt-[2px] text-semantic-success flex-shrink-0" strokeWidth={2} aria-hidden="true" />
            ) : todo.status === 'doing' ? (
              <Loader2 className="w-3.5 h-3.5 mt-[2px] text-ink/70 flex-shrink-0 animate-spin motion-reduce:animate-none" strokeWidth={2} aria-hidden="true" />
            ) : (
              <Circle className="w-3.5 h-3.5 mt-[2px] text-ink/30 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
            )}
            <span
              className={`text-[13px] leading-5 ${
                todo.status === 'done'
                  ? 'text-ink/40 line-through'
                  : todo.status === 'doing'
                    ? 'text-ink/85 font-[450]'
                    : 'text-ink/60'
              }`}
            >
              {todo.status === 'doing' && todo.active_form ? todo.active_form : todo.title}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
