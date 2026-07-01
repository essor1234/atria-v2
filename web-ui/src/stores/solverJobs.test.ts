import { describe, it, expect, beforeEach } from 'vitest';
import { useSolverJobsStore } from './solverJobs';

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
