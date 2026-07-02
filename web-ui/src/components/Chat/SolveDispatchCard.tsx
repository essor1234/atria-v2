import { Link } from 'react-router-dom';
import { Rocket } from 'lucide-react';
import type { Message } from '../../types';
import { useSolverJobsStore } from '../../stores/solverJobs';

interface Props {
  message: Message;
}

const STRATEGY_META: Record<string, { label: string; color: string; bg: string }> = {
  divide:   { label: 'divide',   color: 'text-emerald-400', bg: 'bg-emerald-400/10' },
  parallel: { label: 'parallel', color: 'text-amber-400',   bg: 'bg-amber-400/10' },
};

const STATUS_META: Record<string, { label: string; color: string; dot: string; pulse: boolean }> = {
  running: { label: 'Đang chạy',  color: 'text-amber-400',        dot: 'bg-amber-400',      pulse: true  },
  done:    { label: 'Hoàn thành', color: 'text-emerald-400',      dot: 'bg-emerald-500',    pulse: false },
  failed:  { label: 'Thất bại',   color: 'text-semantic-danger',  dot: 'bg-semantic-danger', pulse: false },
  pending: { label: 'Chuẩn bị',   color: 'text-text-400',         dot: 'bg-text-500',       pulse: true  },
};

function short(id: string): string {
  return id ? id.slice(0, 8) : '?';
}

function extractDispatch(message: Message): {
  strategy: string;
  request: string;
  module?: string;
  jobId?: string;
} {
  const args = (message.tool_args ?? {}) as Record<string, unknown>;
  const result = (message.tool_result ?? {}) as Record<string, unknown>;
  const strategy = String(args.strategy ?? '').toLowerCase();
  const request = String(args.request ?? args.task ?? args.prompt ?? '');
  const module = args.module ? String(args.module) : undefined;
  const jobId = result.job_id ? String(result.job_id) : undefined;
  return { strategy, request, module, jobId };
}

export function SolveDispatchCard({ message }: Props) {
  const { strategy, request, module, jobId } = extractDispatch(message);
  const job = useSolverJobsStore((s) => (jobId ? s.jobs[jobId] : undefined));

  const stratMeta = STRATEGY_META[strategy] ?? {
    label: strategy || 'dispatch',
    color: 'text-text-400',
    bg: 'bg-text-500/10',
  };

  const status = job?.status ?? (jobId ? 'running' : 'pending');
  const statusMeta = STATUS_META[status] ?? STATUS_META.pending;

  // Divide: task count. Parallel: solver count.
  let progressLine: string | null = null;
  let pct: number | null = null;
  if (job?.strategy === 'divide') {
    const total = job.tasks.length;
    const done = job.tasks.filter(
      (t) => t.status === 'done' || t.status === 'failed' || t.status === 'skipped',
    ).length;
    progressLine = `${done}/${total} task${total === 1 ? '' : 's'}`;
    pct = total ? (done / total) * 100 : 0;
  } else if (job?.strategy === 'parallel') {
    progressLine = `${job.done}/${job.n} solver${job.n === 1 ? '' : 's'}`;
    pct = job.n ? (job.done / job.n) * 100 : 0;
  }

  const summary = job?.strategy === 'divide' ? job.summary : undefined;

  return (
    <div className="mx-3 my-2 rounded-lg border border-border-300/20 bg-bg-000 overflow-hidden">
      <div className="flex items-start gap-2 px-3 py-2 border-b border-border-300/10">
        <Rocket aria-hidden className="w-3.5 h-3.5 mt-0.5 text-accent-magenta flex-shrink-0" strokeWidth={1.5} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] font-mono text-text-300">Đã giao task cho subagent</span>
            <span
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10px] font-mono ${stratMeta.color} ${stratMeta.bg}`}
              aria-label={`strategy ${stratMeta.label}`}
            >
              {stratMeta.label}
            </span>
            {module && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-mono text-text-400 bg-bg-100/40">
                {module}
              </span>
            )}
            {jobId && (
              <span className="text-[10px] font-mono text-text-500" title={jobId}>
                #{short(jobId)}
              </span>
            )}
            <span
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10px] font-mono ${statusMeta.color}`}
              aria-label={`status ${statusMeta.label}`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${statusMeta.dot} ${statusMeta.pulse ? 'animate-pulse-dot' : ''}`}
                aria-hidden
              />
              {statusMeta.label}
            </span>
            {progressLine && (
              <span className="text-[10px] font-mono text-text-500 ml-auto">{progressLine}</span>
            )}
          </div>
        </div>
      </div>

      {request && (
        <div className="px-3 py-2 text-[13px] text-ink whitespace-pre-wrap leading-relaxed break-words">
          {request}
        </div>
      )}

      {pct != null && (
        <div className="h-0.5 bg-bg-100">
          <div
            className={`h-full transition-all duration-slow ${status === 'running' ? 'bg-amber-400' : statusMeta.dot}`}
            style={{ width: `${Math.max(pct, 3)}%` }}
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemax={100}
          />
        </div>
      )}

      {summary && (
        <div className="px-3 py-2 border-t border-border-300/10 bg-bg-100/30 text-[12px] text-text-300 leading-relaxed">
          <span className="font-mono text-text-500 mr-1">Kết quả:</span>
          {summary}
        </div>
      )}

      <div className="px-3 py-1.5 border-t border-border-300/10 flex items-center justify-between text-[11px]">
        <span className="text-text-500 font-mono">
          {status === 'done'
            ? 'Đã hoàn thành. Kết quả trên Dispatch page.'
            : 'Đang chạy nền. Bạn có thể tiếp tục trò chuyện.'}
        </span>
        <Link
          to="/dispatch"
          className="font-mono text-text-400 hover:text-text-200 transition-colors"
          aria-label="Xem trên Dispatch"
        >
          Xem chi tiết →
        </Link>
      </div>
    </div>
  );
}
