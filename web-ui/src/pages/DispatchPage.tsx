import { useSolverJobsStore } from '../stores/solverJobs';
import type {
  SolverJob,
  DivideJobView,
  DivideTaskView,
  ParallelJobView,
  ThreadState,
} from '../stores/solverJobs';

// ─── SVG icons ────────────────────────────────────────────────────────────────

function IconDivide() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="flex-shrink-0">
      <circle cx="8" cy="3" r="1.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 4.5V8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M8 8L4 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M8 8L12 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="4" cy="13" r="1.5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="12" cy="13" r="1.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function IconBranch() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="flex-shrink-0">
      <circle cx="5" cy="3" r="1.5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="5" cy="13" r="1.5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="11" cy="6" r="1.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5 4.5v7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M5 4.5C5 7 11 6 11 7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true" className="flex-shrink-0">
      <path d="M2.5 7L5.5 10L11.5 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconX() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true" className="flex-shrink-0">
      <path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconStar() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="currentColor" aria-hidden="true" className="flex-shrink-0">
      <path d="M6.5 1L7.98 4.77L12 5.24L9.05 7.97L9.9 12L6.5 10.1L3.1 12L3.95 7.97L1 5.24L5.02 4.77L6.5 1Z" />
    </svg>
  );
}

// ─── Status badges ────────────────────────────────────────────────────────────

const JOB_STATUS_CONFIG = {
  running: { color: 'text-amber-400', bg: 'bg-amber-400/10', dot: 'bg-amber-400', label: 'Running' },
  done:    { color: 'text-emerald-400', bg: 'bg-emerald-400/10', dot: 'bg-emerald-500', label: 'Done' },
  failed:  { color: 'text-semantic-danger', bg: 'bg-semantic-danger/10', dot: 'bg-semantic-danger', label: 'Failed' },
} as const;

const TASK_STATUS_CONFIG = {
  pending: { color: 'text-text-500', bg: 'bg-text-500/10', dot: 'bg-text-500', label: 'Pending', strike: false },
  running: { color: 'text-amber-400', bg: 'bg-amber-400/10', dot: 'bg-amber-400', label: 'Running', strike: false },
  done:    { color: 'text-emerald-400', bg: 'bg-emerald-400/10', dot: 'bg-emerald-500', label: 'Done', strike: false },
  failed:  { color: 'text-semantic-danger', bg: 'bg-semantic-danger/10', dot: 'bg-semantic-danger', label: 'Failed', strike: false },
  skipped: { color: 'text-text-500', bg: 'bg-text-500/10', dot: 'bg-text-500', label: 'Skipped', strike: true },
} as const;

const THREAD_STATUS_CONFIG = {
  running: { color: 'text-amber-400', bg: 'bg-amber-400/10', dot: 'bg-amber-400', label: 'Running' },
  done:    { color: 'text-emerald-400', bg: 'bg-emerald-400/10', dot: 'bg-emerald-500', label: 'Done' },
  dropped: { color: 'text-semantic-danger', bg: 'bg-semantic-danger/10', dot: 'bg-semantic-danger', label: 'Dropped' },
} as const;

function Badge({
  cfg,
  pulse,
}: {
  cfg: { color: string; bg: string; dot: string; label: string };
  pulse: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[11px] font-mono font-[500] ${cfg.color} ${cfg.bg}`}
      aria-label={cfg.label}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot} ${pulse ? 'animate-pulse-dot' : ''}`} aria-hidden="true" />
      {cfg.label}
    </span>
  );
}

/** Compact "1m 12s" / "8s" duration between two epoch-ms timestamps. */
function fmtDuration(fromMs: number, toMs: number): string {
  const s = Math.max(0, Math.round((toMs - fromMs) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

/** Small pill marking which strategy produced a job. */
function StrategyTag({ strategy }: { strategy: SolverJob['strategy'] }) {
  return (
    <span className="text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded-sm bg-bg-200 text-text-400">
      {strategy}
    </span>
  );
}

// ─── Divide card ────────────────────────────────────────────────────────────

function TaskRow({ task }: { task: DivideTaskView }) {
  const isSkipped = task.status === 'skipped';
  return (
    <div className="flex items-start gap-3 px-4 py-2 border-t border-border-300/10 transition-colors duration-150 hover:bg-bg-100/30">
      <span className={`font-mono text-[11px] text-text-400 mt-0.5 w-16 flex-shrink-0 ${isSkipped ? 'line-through opacity-50' : ''}`}>
        {task.id}
      </span>
      <Badge cfg={TASK_STATUS_CONFIG[task.status]} pulse={task.status === 'running'} />
      <div className="flex-1 min-w-0 space-y-0.5">
        <span className={`block text-xs text-text-300 truncate ${isSkipped ? 'line-through opacity-50' : ''}`} title={task.description}>
          {task.description}
        </span>
        {task.depends_on.length > 0 && (
          <span className="text-[11px] font-mono text-text-500 truncate block">
            &larr; {task.depends_on.join(', ')}
          </span>
        )}
        {task.status === 'done' && task.result && (
          <span className="block text-[11px] text-text-400 truncate" title={task.result}>
            {task.result}
          </span>
        )}
      </div>
    </div>
  );
}

function DivideCard({ job }: { job: DivideJobView }) {
  const statusCfg = JOB_STATUS_CONFIG[job.status];
  const total = job.tasks.length;
  const done = job.tasks.filter(
    (t) => t.status === 'done' || t.status === 'failed' || t.status === 'skipped',
  ).length;
  const pct = total ? Math.max((done / total) * 100, 3) : 3;
  return (
    <div
      className="bg-bg-000 border border-border-300/15 rounded-lg overflow-hidden transition-shadow duration-300 hover:shadow-hover focus-visible:outline-none focus-visible:shadow-focus-ring"
      role="region"
      tabIndex={0}
      aria-label={`Divide job ${job.jobId.slice(0, 8)}, ${done} of ${total} tasks done`}
    >
      <div className="flex items-start gap-3 px-4 py-3 border-b border-border-300/10">
        <IconDivide />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-mono text-text-400">{job.jobId.slice(0, 8)}</span>
            <StrategyTag strategy="divide" />
            <Badge cfg={statusCfg} pulse={job.status === 'running'} />
            <span className="text-[11px] font-mono text-text-500">{job.module}</span>
            <span className="text-[11px] font-mono text-text-500">{done}/{total} tasks</span>
            <span className="text-[11px] font-mono text-text-500" title="Elapsed">
              {fmtDuration(job.startedAt, job.status === 'running' ? job.updatedAt : job.updatedAt)}
            </span>
          </div>
          <p className="text-sm text-text-100 font-[330] truncate mt-0.5" title={job.request}>
            {job.request}
          </p>
        </div>
      </div>

      {job.status === 'running' ? (
        <div className="h-0.5 bg-bg-200">
          <div
            className="h-full bg-amber-400 transition-all duration-slow"
            style={{ width: `${pct}%` }}
            role="progressbar"
            aria-valuenow={done}
            aria-valuemax={total}
          />
        </div>
      ) : (
        <div className={`h-0.5 ${statusCfg.dot}`} />
      )}

      <div>
        {job.tasks.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>

      {(job.status === 'done' || job.status === 'failed') && job.summary && (
        <div className="px-4 py-3 border-t border-border-300/10 bg-bg-100/20">
          <p className="text-xs text-text-300 leading-relaxed">
            <span className="font-mono text-text-500 mr-1">Summary:</span>
            {job.summary}
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Parallel card ──────────────────────────────────────────────────────────

function ThreadRow({ thread }: { thread: ThreadState }) {
  return (
    <div className="flex items-start gap-3 px-4 py-2 border-t border-border-300/10 transition-colors hover:bg-bg-100/30">
      <span className="font-mono text-[11px] text-text-400 mt-0.5 w-16 flex-shrink-0">
        Thread {thread.thread}
      </span>
      <Badge cfg={THREAD_STATUS_CONFIG[thread.status]} pulse={thread.status === 'running'} />
      {thread.summary && (
        <span className="flex-1 text-xs text-text-300 truncate min-w-0" title={thread.summary}>
          {thread.summary}
        </span>
      )}
      {thread.winner && (
        <span className="flex items-center gap-1 text-amber-400 text-[11px] font-mono font-[500] flex-shrink-0 ml-auto">
          <IconStar />
          winner
        </span>
      )}
    </div>
  );
}

function ParallelCard({ job }: { job: ParallelJobView }) {
  const overallStatus = job.status === 'running' ? 'running' : 'done';
  const statusCfg = THREAD_STATUS_CONFIG[overallStatus];
  return (
    <div
      className="bg-bg-000 border border-border-300/15 rounded-lg overflow-hidden transition-shadow duration-fast hover:shadow-hover"
      role="region"
      aria-label={`Parallel job ${job.jobId.slice(0, 8)}`}
    >
      <div className="flex items-start gap-3 px-4 py-3 border-b border-border-300/10">
        <IconBranch />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-mono text-text-400">{job.jobId.slice(0, 8)}</span>
            <StrategyTag strategy="parallel" />
            <Badge cfg={statusCfg} pulse={job.status === 'running'} />
            {job.status === 'running' && (
              <span className="text-[11px] font-mono text-text-500">
                {job.done}/{job.n} solvers
              </span>
            )}
          </div>
          <p className="text-sm text-text-100 font-[330] truncate mt-0.5" title={job.task}>
            {job.task}
          </p>
        </div>
      </div>

      {job.status === 'running' ? (
        <div className="h-0.5 bg-bg-200">
          <div
            className="h-full bg-amber-400 transition-all duration-slow"
            style={{ width: `${job.n > 0 ? Math.max((job.done / job.n) * 100, 3) : 3}%` }}
            role="progressbar"
            aria-valuenow={job.done}
            aria-valuemax={job.n}
          />
        </div>
      ) : (
        <div className={`h-0.5 ${statusCfg.dot}`} />
      )}

      <div>
        {job.threads.map((t) => (
          <ThreadRow key={t.thread} thread={t} />
        ))}
      </div>

      {job.status === 'done' && (
        <div className="px-4 py-3 border-t border-border-300/10 space-y-2 bg-bg-100/20">
          <div className="flex items-center gap-2">
            {job.applied ? (
              <span className="flex items-center gap-1.5 text-emerald-400 text-xs font-mono">
                <IconCheck />
                <span>Applied</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-semantic-danger text-xs font-mono">
                <IconX />
                <span>Not applied</span>
              </span>
            )}
          </div>
          {job.reasoning && (
            <p className="text-xs text-text-300 leading-relaxed">
              <span className="font-mono text-text-500 mr-1">Judge:</span>
              {job.reasoning}
            </p>
          )}
          {job.conflictedFiles && job.conflictedFiles.length > 0 && (
            <div className="space-y-0.5">
              <p className="text-[11px] font-mono text-semantic-danger">
                {job.conflictedFiles.length} conflicted file{job.conflictedFiles.length !== 1 ? 's' : ''}
              </p>
              {job.conflictedFiles.map((f) => (
                <p key={f} className="text-[11px] font-mono text-text-400 ml-2 truncate" title={f}>
                  └ {f}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function JobCard({ job }: { job: SolverJob }) {
  return job.strategy === 'divide' ? <DivideCard job={job} /> : <ParallelCard job={job} />;
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 px-6 text-center">
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true" className="text-text-500 mb-4">
        <circle cx="20" cy="8" r="4" stroke="currentColor" strokeWidth="1.5" />
        <path d="M20 12V20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M20 20L10 28" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M20 20L30 28" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="10" cy="32" r="4" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="30" cy="32" r="4" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <p className="text-sm text-text-300 font-[330] max-w-xs">
        No dispatch jobs yet.{' '}
        <span className="font-mono text-text-400">Run solve</span>{' '}
        with strategy <span className="font-mono text-text-400">divide</span> or{' '}
        <span className="font-mono text-text-400">parallel</span> to fan out work.
      </p>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function DispatchPage() {
  const jobs = useSolverJobsStore((s) => s.jobs);
  const order = useSolverJobsStore((s) => s.order);
  const clear = useSolverJobsStore((s) => s.clear);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-canvas">
      <main>
        <div className="max-w-content mx-auto px-6 py-8">
          <div className="flex items-start justify-between mb-8">
            <div>
              <h1 className="text-headline text-ink tracking-[-0.26px]">Dispatch</h1>
              <p className="text-body-sm text-ink/60 mt-1">
                Live task dispatch — divide (DAG decomposition) and parallel
                (worktree-isolated solvers, judged and applied) in one view.
              </p>
            </div>

            {order.length > 0 && (
              <button
                onClick={clear}
                className="px-3 py-1.5 text-[13px] font-mono text-ink/60 hover:text-ink hover:bg-surface-soft rounded-md transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:shadow-focus-ring"
                aria-label="Clear all jobs"
              >
                Clear
              </button>
            )}
          </div>

          {order.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-4">
              {order.map((jobId) => {
                const job = jobs[jobId];
                if (!job) return null;
                return <JobCard key={jobId} job={job} />;
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
