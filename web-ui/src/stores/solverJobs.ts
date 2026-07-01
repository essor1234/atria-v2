import { create } from 'zustand';
import { wsClient } from '../api/websocket';
import { useToastStore } from './toast';
import type {
  ParallelSolverProgressData,
  ParallelSolverDoneData,
} from '../types';

// ─── Blackboard notes ─────────────────────────────────────────────────────────

export interface BBNote {
  type: string;
  content: string;
  ts: number;
  thread_id: number;
}

const MAX_NOTES = 50;

// ─── Divide (DAG decomposition) shapes ───────────────────────────────────────

export interface DivideTaskView {
  id: string;
  description: string;
  depends_on: string[];
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  result?: string;
  notes: BBNote[];
}

export interface DivideJobView {
  strategy: 'divide';
  jobId: string;
  module: string;
  request: string;
  tasks: DivideTaskView[];
  status: 'running' | 'done' | 'failed';
  summary?: string;
  startedAt: number;
  updatedAt: number;
}

// ─── Parallel (worktree fan-out + judge) shapes ──────────────────────────────

export interface ThreadState {
  thread: number;
  status: 'running' | 'done' | 'dropped';
  ok?: boolean;
  summary?: string;
  winner?: boolean;
  notes: BBNote[];
}

export interface ParallelJobView {
  strategy: 'parallel';
  jobId: string;
  task: string;
  n: number;
  status: 'running' | 'done';
  done: number;
  threads: ThreadState[];
  applied?: boolean;
  winnerThread?: number;
  reasoning?: string;
  conflictedFiles?: string[];
  droppedThreads?: number[];
  startedAt: number;
  updatedAt: number;
}

/** A single dispatched solve job, discriminated by `strategy`. */
export type SolverJob = DivideJobView | ParallelJobView;

interface SolverJobsState {
  jobs: Record<string, SolverJob>;
  order: string[];
  bbToJob: Record<string, string>;
  clear(): void;
  onBlackboardNote(
    payload: { task_id: string; thread_id: number; type: string; content: string; ts: number },
    hintedJobId?: string,
  ): void;
}

// ─── Persistence (P2) — survive full page reloads ────────────────────────────
// In-app navigation already keeps the store (module singleton); only an F5 wiped
// it. We persist to sessionStorage (per-tab, no cross-user leak — unlike a Redis
// SCAN of all jobs) so the Dispatch history rehydrates on reload.
const STORAGE_KEY = 'atria.solverJobs.v1';

function loadPersisted(): Pick<SolverJobsState, 'jobs' | 'order'> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (p && typeof p === 'object' && p.jobs && Array.isArray(p.order)) {
        return { jobs: p.jobs as Record<string, SolverJob>, order: p.order as string[] };
      }
    }
  } catch {
    /* ignore corrupt/unavailable storage */
  }
  return { jobs: {}, order: [] };
}

export const useSolverJobsStore = create<SolverJobsState>((set, _get) => ({
  ...loadPersisted(),
  bbToJob: {},
  clear: () => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    set({ jobs: {}, order: [], bbToJob: {} });
  },
  onBlackboardNote: (payload, hintedJobId) => {
    set((state) => {
      const jobId = hintedJobId ?? state.bbToJob[payload.task_id];
      if (!jobId) return {};
      const job = state.jobs[jobId];
      if (!job) return {};

      const note: BBNote = {
        type: payload.type,
        content: payload.content,
        ts: payload.ts,
        thread_id: payload.thread_id,
      };

      if (job.strategy === 'divide') {
        const idx = job.tasks.findIndex((t) => t.id === `t${payload.thread_id}`);
        if (idx < 0) return {};
        const tasks = [...job.tasks];
        const existing = tasks[idx].notes ?? [];
        const merged = [...existing, note];
        if (merged.length > MAX_NOTES) merged.splice(0, merged.length - MAX_NOTES);
        tasks[idx] = { ...tasks[idx], notes: merged };
        return { jobs: { ...state.jobs, [jobId]: { ...job, tasks, updatedAt: Date.now() } } };
      }

      // parallel
      const idx = job.threads.findIndex((t) => t.thread === payload.thread_id);
      if (idx < 0) return {};
      const threads = [...job.threads];
      const existing = threads[idx].notes ?? [];
      const merged = [...existing, note];
      if (merged.length > MAX_NOTES) merged.splice(0, merged.length - MAX_NOTES);
      threads[idx] = { ...threads[idx], notes: merged };
      return { jobs: { ...state.jobs, [jobId]: { ...job, threads, updatedAt: Date.now() } } };
    });
  },
}));

// Mirror every change into sessionStorage so a reload restores the job list.
useSolverJobsStore.subscribe((state) => {
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ jobs: state.jobs, order: state.order }),
    );
  } catch {
    /* ignore quota / serialization errors */
  }
});

/** Count of jobs still running — used for the nav activity badge. */
export function runningSolverCount(state: SolverJobsState): number {
  return Object.values(state.jobs).filter((j) => j.status === 'running').length;
}

// ─── WS subscriptions — register once at module load ─────────────────────────

let _initialized = false;

function upsertOrder(order: string[], jobId: string): string[] {
  return order.includes(jobId) ? order : [jobId, ...order];
}

export function initSolverJobsStore() {
  if (_initialized) return;
  _initialized = true;

  // ── started ──────────────────────────────────────────────────────────────
  wsClient.on('solver_started', (msg) => {
    const data = msg.data as { strategy: 'divide' | 'parallel'; job_id: string } & Record<
      string,
      unknown
    >;
    const now = Date.now();
    let job: SolverJob;

    if (data.strategy === 'divide') {
      const d = data as unknown as {
        job_id: string;
        module: string;
        request: string;
        tasks: { id: string; description: string; depends_on: string[] }[];
      };
      job = {
        strategy: 'divide',
        jobId: d.job_id,
        module: d.module,
        request: d.request,
        tasks: d.tasks.map((t) => ({
          id: t.id,
          description: t.description,
          depends_on: t.depends_on,
          status: 'pending' as const,
          notes: [],
        })),
        status: 'running',
        startedAt: now,
        updatedAt: now,
      };
    } else {
      const p = data as unknown as { job_id: string; task: string; n: number };
      job = {
        strategy: 'parallel',
        jobId: p.job_id,
        task: p.task,
        n: p.n,
        status: 'running',
        done: 0,
        threads: Array.from({ length: p.n }, (_, i) => ({
          thread: i,
          status: 'running' as const,
          notes: [],
        })),
        startedAt: now,
        updatedAt: now,
      };
    }

    const bbTaskId = (data as Record<string, unknown>).blackboard_task_id as string | undefined;
    useSolverJobsStore.setState((state) => ({
      jobs: { ...state.jobs, [data.job_id]: job },
      order: upsertOrder(state.order, data.job_id),
      bbToJob: bbTaskId
        ? { ...state.bbToJob, [bbTaskId]: data.job_id }
        : state.bbToJob,
    }));
  });

  // ── progress ─────────────────────────────────────────────────────────────
  wsClient.on('solver_progress', (msg) => {
    const data = msg.data as { strategy: 'divide' | 'parallel'; job_id: string } & Record<
      string,
      unknown
    >;
    useSolverJobsStore.setState((state) => {
      const job = state.jobs[data.job_id];
      if (!job) return state;

      if (job.strategy === 'divide' && data.strategy === 'divide') {
        const d = data as unknown as {
          task_id: string;
          status: DivideTaskView['status'];
          result?: string;
        };
        const tasks = job.tasks.map((t) =>
          t.id === d.task_id ? { ...t, status: d.status, result: d.result } : t
        );
        return {
          jobs: {
            ...state.jobs,
            [data.job_id]: { ...job, tasks, updatedAt: Date.now() },
          },
        };
      }

      if (job.strategy === 'parallel' && data.strategy === 'parallel') {
        const p = data as unknown as ParallelSolverProgressData;
        return {
          jobs: {
            ...state.jobs,
            [data.job_id]: { ...job, done: p.done, updatedAt: Date.now() },
          },
        };
      }

      return state;
    });
  });

  // ── done ─────────────────────────────────────────────────────────────────
  wsClient.on('solver_done', (msg) => {
    const data = msg.data as { strategy: 'divide' | 'parallel'; job_id: string } & Record<
      string,
      unknown
    >;
    useSolverJobsStore.setState((state) => {
      const job = state.jobs[data.job_id];
      if (!job) return state;

      if (job.strategy === 'divide' && data.strategy === 'divide') {
        const d = data as unknown as { status: 'done' | 'failed'; summary: string };
        return {
          jobs: {
            ...state.jobs,
            [data.job_id]: {
              ...job,
              status: d.status,
              summary: d.summary,
              updatedAt: Date.now(),
            },
          },
        };
      }

      if (job.strategy === 'parallel' && data.strategy === 'parallel') {
        const p = data as unknown as ParallelSolverDoneData;
        const droppedSet = new Set(p.dropped_threads ?? []);
        const candidateMap = new Map((p.candidates ?? []).map((c) => [c.thread, c]));
        const threads: ThreadState[] = job.threads.map((t) => {
          if (droppedSet.has(t.thread)) return { ...t, status: 'dropped' as const };
          const candidate = candidateMap.get(t.thread);
          return {
            ...t,
            status: 'done' as const,
            ok: candidate?.ok,
            summary: candidate?.summary,
            winner: t.thread === p.winner_thread,
          };
        });
        return {
          jobs: {
            ...state.jobs,
            [data.job_id]: {
              ...job,
              status: 'done',
              applied: p.applied,
              winnerThread: p.winner_thread,
              reasoning: p.reasoning,
              conflictedFiles: p.conflicted_files ?? [],
              droppedThreads: p.dropped_threads ?? [],
              threads,
              updatedAt: Date.now(),
            },
          },
        };
      }

      return state;
    });

    // Completion notification (P1) — surfaces even when the user is on Chat.
    if (!useSolverJobsStore.getState().jobs[data.job_id]) return;
    const short = data.job_id.slice(0, 8);
    const toast = useToastStore.getState().addToast;
    if (data.strategy === 'divide') {
      const ok = (data as { status?: string }).status !== 'failed';
      toast(
        `Dispatch ${short} ${ok ? 'hoàn tất' : 'thất bại'}`,
        ok ? 'success' : 'error',
      );
    } else if (data.strategy === 'parallel') {
      const applied = Boolean((data as { applied?: boolean }).applied);
      toast(
        `Solve ${short} xong${applied ? ' · đã áp dụng diff' : ' · chưa áp dụng'}`,
        applied ? 'success' : 'info',
      );
    }
  });

  // ── blackboard notes ──────────────────────────────────────────────────────
  wsClient.on('blackboard.note', (msg) => {
    useSolverJobsStore.getState().onBlackboardNote(
      msg.data as { task_id: string; thread_id: number; type: string; content: string; ts: number },
    );
  });
}

// Self-init at module load — mirrors how the previous per-strategy stores did.
initSolverJobsStore();
