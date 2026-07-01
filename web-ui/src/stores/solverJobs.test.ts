import { describe, it, expect, beforeEach } from 'vitest';
import { useSolverJobsStore } from './solverJobs';
import type { DivideJobView, ParallelJobView } from './solverJobs';

const NOW = 1;

/** Simulate what the solver_started handler does for a divide job (no blackboard_task_id in payload). */
function seedDivideViaHandler(jobId: string) {
  const job: DivideJobView = {
    strategy: 'divide',
    jobId,
    module: 'm',
    request: 'r',
    tasks: [{ id: 't0', description: 'x', depends_on: [], status: 'pending', notes: [] }],
    status: 'running',
    startedAt: NOW,
    updatedAt: NOW,
  };
  // Derived convention: no explicit blackboard_task_id → use "dw_" + job_id
  const derivedBbId = `dw_${jobId}`;
  useSolverJobsStore.setState((state) => ({
    jobs: { ...state.jobs, [jobId]: job },
    order: state.order.includes(jobId) ? state.order : [jobId, ...state.order],
    bbToJob: { ...state.bbToJob, [derivedBbId]: jobId },
  }));
}

/** Simulate what the solver_started handler does for a parallel job (no blackboard_task_id in payload). */
function seedParallelViaHandler(jobId: string, n = 2) {
  const job: ParallelJobView = {
    strategy: 'parallel',
    jobId,
    task: 't',
    n,
    status: 'running',
    done: 0,
    threads: Array.from({ length: n }, (_, i) => ({
      thread: i,
      status: 'running' as const,
      notes: [],
    })),
    startedAt: NOW,
    updatedAt: NOW,
  };
  // Derived convention: no explicit blackboard_task_id → use "bb_" + job_id
  const derivedBbId = `bb_${jobId}`;
  useSolverJobsStore.setState((state) => ({
    jobs: { ...state.jobs, [jobId]: job },
    order: state.order.includes(jobId) ? state.order : [jobId, ...state.order],
    bbToJob: { ...state.bbToJob, [derivedBbId]: jobId },
  }));
}

function seedDivide() {
  useSolverJobsStore.setState({
    jobs: {
      job_a: {
        strategy: 'divide',
        jobId: 'job_a',
        module: 'm',
        request: 'r',
        tasks: [
          { id: 't0', description: 'x', depends_on: [], status: 'running', notes: [] },
        ],
        status: 'running',
        startedAt: 1,
        updatedAt: 1,
      },
    },
    order: ['job_a'],
  });
}

describe('solverJobs blackboard.note', () => {
  beforeEach(() => {
    useSolverJobsStore.getState().clear();
  });

  it('appends a note to a matching divide task', () => {
    seedDivide();
    useSolverJobsStore.getState().onBlackboardNote({
      task_id: 'dw_job_a',
      thread_id: 0,
      type: 'fact',
      content: 'hi',
      ts: 1,
    }, 'job_a');
    const job = useSolverJobsStore.getState().jobs.job_a as any;
    expect(job.tasks[0].notes.length).toBe(1);
    expect(job.tasks[0].notes[0].content).toBe('hi');
  });

  it('caps notes at 50, dropping oldest', () => {
    seedDivide();
    for (let i = 0; i < 60; i++) {
      useSolverJobsStore.getState().onBlackboardNote({
        task_id: 'dw_job_a',
        thread_id: 0,
        type: 'fact',
        content: `n${i}`,
        ts: i,
      }, 'job_a');
    }
    const job = useSolverJobsStore.getState().jobs.job_a as any;
    expect(job.tasks[0].notes.length).toBe(50);
    expect(job.tasks[0].notes[0].content).toBe('n10');
    expect(job.tasks[0].notes[49].content).toBe('n59');
  });
});

describe('solverJobs bbToJob derivation (Fix 1)', () => {
  beforeEach(() => {
    useSolverJobsStore.getState().clear();
  });

  it('divide: solver_started without blackboard_task_id populates bbToJob as "dw_<jobId>", note lands on task', () => {
    seedDivideViaHandler('jdiv1');

    // Verify bbToJob was set with the derived key
    expect(useSolverJobsStore.getState().bbToJob['dw_jdiv1']).toBe('jdiv1');

    // Dispatch a blackboard.note using task_id="dw_jdiv1" (no hintedJobId)
    useSolverJobsStore.getState().onBlackboardNote({
      task_id: 'dw_jdiv1',
      thread_id: 0,
      type: 'fact',
      content: 'divide-note',
      ts: 2,
    });

    const job = useSolverJobsStore.getState().jobs['jdiv1'] as DivideJobView;
    expect(job.tasks[0].notes.length).toBe(1);
    expect(job.tasks[0].notes[0].content).toBe('divide-note');
  });

  it('parallel: solver_started without blackboard_task_id populates bbToJob as "bb_<jobId>", note lands on thread', () => {
    seedParallelViaHandler('jpar1', 2);

    // Verify bbToJob was set with the derived key
    expect(useSolverJobsStore.getState().bbToJob['bb_jpar1']).toBe('jpar1');

    // Dispatch a blackboard.note using task_id="bb_jpar1" (no hintedJobId)
    useSolverJobsStore.getState().onBlackboardNote({
      task_id: 'bb_jpar1',
      thread_id: 1,
      type: 'progress',
      content: 'parallel-note',
      ts: 3,
    });

    const job = useSolverJobsStore.getState().jobs['jpar1'] as ParallelJobView;
    expect(job.threads[1].notes.length).toBe(1);
    expect(job.threads[1].notes[0].content).toBe('parallel-note');
  });
});
