import { useState } from 'react';
import { Check, X, BarChart2, FileText, ArrowRight } from 'lucide-react';
import type { Message, DeepAnalyzePhase, DeepAnalyzePhaseStatus } from '../../types';
import { wsClient } from '../../api/websocket';

interface Props {
  message: Message;
}

const PHASES: { key: DeepAnalyzePhase; label: string }[] = [
  { key: 'load',      label: 'Load'      },
  { key: 'profile',   label: 'Profile'   },
  { key: 'explore',   label: 'Explore'   },
  { key: 'plan',      label: 'Plan'      },
  { key: 'extract',   label: 'Extract'   },
  { key: 'synthesize', label: 'Synthesize' },
  { key: 'report',    label: 'Report'    },
];

const STATUS_COLORS = {
  running:        'text-amber-400',
  clarifying:     'text-sky-400',
  plan_reviewing: 'text-purple-400',
  done:           'text-emerald-400',
  error:          'text-red-400',
  cancelled:      'text-text-400',
} as const;

const STATUS_LABELS = {
  running:        'Analyzing…',
  clarifying:     'Awaiting clarification',
  plan_reviewing: 'Awaiting plan review',
  done:           'Complete',
  error:          'Error',
  cancelled:      'Cancelled',
} as const;

function phaseClass(status: DeepAnalyzePhaseStatus | undefined): string {
  switch (status) {
    case 'done':
      return 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300';
    case 'running':
      return 'bg-amber-500/15 border-amber-500/40 text-amber-300';
    default:
      return 'bg-bg-200/40 border-border-300/15 text-text-400';
  }
}

function phaseIcon(status: DeepAnalyzePhaseStatus | undefined) {
  if (status === 'done') {
    return <Check className="w-3 h-3 flex-shrink-0" strokeWidth={2.5} />;
  }
  if (status === 'running') {
    return (
      <span className="inline-block w-2.5 h-2.5 border-2 border-current border-t-transparent rounded-full animate-spin flex-shrink-0" />
    );
  }
  return (
    <span className="inline-block w-2 h-2 rounded-full bg-current opacity-30 flex-shrink-0" />
  );
}

function ItemRow({ name, status, error, suffix }: { name: string; status: 'done' | 'failed'; error?: string; suffix?: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1 text-xs font-mono">
      {status === 'done' ? (
        <Check className="w-3 h-3 text-emerald-400 flex-shrink-0" strokeWidth={2.5} />
      ) : (
        <X className="w-3 h-3 text-red-400 flex-shrink-0" strokeWidth={2.5} />
      )}
      <span className={`flex-1 truncate ${status === 'done' ? 'text-text-200' : 'text-text-400 line-through'}`}>{name}</span>
      {suffix && <span className="text-text-500 flex-shrink-0">{suffix}</span>}
      {status === 'failed' && error && (
        <span className="text-red-400/80 text-[10px] truncate max-w-[16ch]" title={error}>{error}</span>
      )}
    </div>
  );
}

// ─── Clarify Q&A panel ────────────────────────────────────────────────────────

function ClarifyPanel({ message }: { message: Message }) {
  const { da_clarify_request_id, da_clarify_questions, da_clarify_iteration, da_job_id, da_domain_brief } = message;
  const questions = da_clarify_questions ?? [];
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);

  // Reset state when a new question batch arrives (different request id).
  const prevRequestId = useState(da_clarify_request_id)[0];
  if (prevRequestId !== da_clarify_request_id && submitted) {
    setSubmitted(false);
    setAnswers({});
  }

  const setAnswer = (id: string, value: string) =>
    setAnswers(prev => ({ ...prev, [id]: value }));

  const submit = () => {
    if (!da_clarify_request_id || submitted) return;
    setSubmitted(true);
    wsClient.send({
      type: 'analyze_clarify_response',
      data: {
        requestId: da_clarify_request_id,
        job_id: da_job_id,
        answers: questions.map(q => ({ id: q.id, answer: (answers[q.id] || '').trim() })),
      },
    });
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="p-4 space-y-3 border-t border-border-300/10 bg-sky-500/5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono font-semibold text-sky-300">
          Clarifying questions
          {da_clarify_iteration ? ` · round ${da_clarify_iteration}` : ''}
        </span>
        <span className="text-xs font-mono text-text-500">
          ({questions.length} question{questions.length !== 1 ? 's' : ''})
        </span>
      </div>

      {da_domain_brief && (
        <details className="text-xs font-mono text-text-400">
          <summary className="cursor-pointer hover:text-text-200">Current domain brief</summary>
          <p className="mt-1.5 pl-3 border-l-2 border-sky-500/30 leading-relaxed whitespace-pre-wrap">
            {da_domain_brief}
          </p>
        </details>
      )}

      <div className="space-y-2.5">
        {questions.map((q, i) => (
          <div key={q.id} className="space-y-1">
            <label className="flex items-start gap-2 text-xs font-mono">
              <span className="text-text-500 flex-shrink-0">{i + 1}.</span>
              <span className="flex-1 text-text-200">
                {q.text}
                {q.column && (
                  <span className="text-text-500"> (column: <code className="text-text-300">{q.column}</code>)</span>
                )}
                <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded border ${
                  q.kind === 'intent'
                    ? 'bg-purple-500/10 text-purple-300 border-purple-500/30'
                    : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                }`}>
                  {q.kind}
                </span>
              </span>
            </label>
            <textarea
              value={answers[q.id] || ''}
              onChange={(e) => setAnswer(q.id, e.target.value)}
              onKeyDown={handleKey}
              disabled={submitted}
              rows={2}
              placeholder="Your answer (leave blank to skip)…"
              className="w-full px-2.5 py-1.5 text-xs font-mono bg-bg-000/60 border border-border-300/20 rounded text-text-200 placeholder:text-text-500 focus:outline-none focus:border-sky-500/50 resize-y disabled:opacity-50"
            />
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-2 pt-1">
        <span className="text-[10px] font-mono text-text-500">⌘/Ctrl + Enter to submit</span>
        <button
          onClick={submit}
          disabled={submitted}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono font-semibold bg-sky-500/20 text-sky-300 border border-sky-500/40 rounded hover:bg-sky-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {submitted ? (
            <>
              <span className="inline-block w-2.5 h-2.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
              <span>Submitting…</span>
            </>
          ) : (
            <>
              <ArrowRight className="w-3 h-3" strokeWidth={2.5} />
              <span>Submit answers</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// ─── Plan review panel ────────────────────────────────────────────────────────

const CHART_TYPE_COLOR: Record<string, string> = {
  bar:     'bg-blue-500/15 text-blue-300 border-blue-500/30',
  line:    'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  scatter: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  hist:    'bg-amber-500/15 text-amber-300 border-amber-500/30',
  pie:     'bg-pink-500/15 text-pink-300 border-pink-500/30',
};

function PlanReviewPanel({ message }: { message: Message }) {
  const { da_plan_review_request_id, da_plan, da_job_id } = message;
  const [instructions, setInstructions] = useState('');
  const [pending, setPending] = useState<'modify' | 'regenerate' | 'accept' | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<number>>(() => new Set([0]));
  const [sqlOpen, setSqlOpen] = useState(false);

  // Reset spinner when backend sends a new plan (after modify/regenerate)
  const prevRequestId = useState(da_plan_review_request_id)[0];
  if (prevRequestId !== da_plan_review_request_id && pending !== null) {
    setPending(null);
    setInstructions('');
  }

  const send = (action: 'modify' | 'regenerate' | 'accept') => {
    if (!da_plan_review_request_id || pending) return;
    if (action === 'modify' && !instructions.trim()) return;
    setPending(action);
    wsClient.send({
      type: 'analyze_plan_response',
      data: {
        requestId: da_plan_review_request_id,
        job_id: da_job_id,
        action,
        ...(action === 'modify' && { instructions: instructions.trim() }),
      },
    });
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send('modify'); }
  };

  const toggleSection = (i: number) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });
  };

  const sections = da_plan?.sections ?? [];
  const charts = da_plan?.charts ?? [];
  const subTables = da_plan?.sub_tables ?? [];

  // Build chart lookup by name
  const chartByName = Object.fromEntries(charts.map(c => [c.name, c]));

  return (
    <div className="p-4 space-y-4">
      {/* Summary line */}
      {da_plan?.summary && (
        <p className="text-xs text-text-300 font-mono leading-relaxed border-l-2 border-accent-main-100/40 pl-2">
          {da_plan.summary}
        </p>
      )}

      {/* Sections + charts */}
      {sections.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-text-400 font-mono">
            {sections.length} sections · {charts.length} charts · {subTables.length} sub-tables
          </p>
          <div className="space-y-1">
            {sections.map((sec, i) => {
              const open = expandedSections.has(i);
              const sectionCharts = (sec.chart_names ?? []).map(n => chartByName[n]).filter(Boolean);
              return (
                <div key={i} className="rounded border border-border-300/15 bg-bg-200/20 overflow-hidden">
                  {/* Section header */}
                  <button
                    onClick={() => toggleSection(i)}
                    className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-bg-200/40 transition-colors"
                  >
                    <span className="text-text-500 font-mono text-xs flex-shrink-0 mt-0.5">{i + 1}.</span>
                    <span className="flex-1 min-w-0">
                      <span className="text-text-100 text-xs font-semibold font-mono">{sec.name}</span>
                      {sec.key_question && !open && (
                        <span className="text-text-400 text-xs font-mono ml-2 truncate">{sec.key_question}</span>
                      )}
                    </span>
                    <span className="text-text-500 font-mono text-xs flex-shrink-0">
                      {sectionCharts.length} chart{sectionCharts.length !== 1 ? 's' : ''} {open ? '▲' : '▼'}
                    </span>
                  </button>

                  {/* Expanded detail */}
                  {open && (
                    <div className="px-3 pb-3 space-y-2 border-t border-border-300/10">
                      {sec.key_question && (
                        <p className="text-xs text-text-300 font-mono pt-2 italic">
                          Q: {sec.key_question}
                        </p>
                      )}
                      {sectionCharts.length > 0 && (
                        <div className="space-y-1.5 pt-1">
                          {sectionCharts.map(chart => (
                            <div key={chart.name} className="rounded bg-bg-100/60 border border-border-300/10 px-2.5 py-2 space-y-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono font-semibold uppercase tracking-wide ${CHART_TYPE_COLOR[chart.type] ?? 'bg-bg-200 text-text-300 border-border-300/20'}`}>
                                  {chart.type}
                                </span>
                                <span className="text-xs text-text-100 font-mono font-semibold">{chart.title}</span>
                              </div>
                              <p className="text-[11px] text-text-400 font-mono">
                                x: <span className="text-text-200">{chart.x}</span>
                                {' · '}
                                y: <span className="text-text-200">{chart.y?.join(', ')}</span>
                                {' · '}
                                from <span className="text-text-200">{chart.source_table}</span>
                              </p>
                              {chart.insight && (
                                <p className="text-[11px] text-text-400 font-mono leading-relaxed">
                                  <span className="text-text-500">insight: </span>{chart.insight}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Sub-tables SQL — collapsible */}
      {subTables.length > 0 && (
        <div className="rounded border border-border-300/15 overflow-hidden">
          <button
            onClick={() => setSqlOpen(o => !o)}
            className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-bg-200/40 transition-colors"
          >
            <span className="text-xs font-mono text-text-400 flex-1">
              SQL sub-tables ({subTables.length})
            </span>
            <span className="text-text-500 font-mono text-xs">{sqlOpen ? '▲' : '▼'}</span>
          </button>
          {sqlOpen && (
            <div className="border-t border-border-300/10 divide-y divide-border-300/10">
              {subTables.map((tbl, i) => (
                <div key={i} className="px-3 py-2.5 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-bg-200 border border-border-300/20 text-text-300 font-mono">
                      t_{tbl.name}
                    </span>
                    {tbl.why && (
                      <span className="text-[11px] text-text-400 font-mono">{tbl.why}</span>
                    )}
                  </div>
                  <pre className="text-[10px] text-text-300 font-mono bg-bg-000/40 rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap break-all leading-relaxed">
                    {tbl.sql}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Modification input */}
      <div className="space-y-1.5">
        <label className="text-xs text-text-400 font-mono">Request changes</label>
        <div className="flex gap-2 items-end">
          <textarea
            className="flex-1 bg-bg-100 border border-border-300/20 focus:border-accent-main-100/50 rounded-md px-3 py-2 text-sm text-text-100 font-mono resize-none outline-none transition-colors placeholder:text-text-500 min-h-[2.5rem]"
            rows={2}
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            onKeyDown={handleKey}
            placeholder='e.g. "add a scatter plot of salary vs experience", "remove the pie chart", "rename section 2 to Regional Breakdown"'
            disabled={pending !== null}
          />
          <button
            onClick={() => send('modify')}
            disabled={pending !== null || !instructions.trim()}
            className="flex-shrink-0 px-3 py-2 bg-bg-200/60 hover:bg-bg-200 disabled:opacity-40 disabled:cursor-not-allowed border border-border-300/20 text-text-200 text-xs font-semibold font-mono rounded transition-colors h-10"
          >
            {pending === 'modify' ? (
              <span className="inline-block w-3.5 h-3.5 border-2 border-text-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <ArrowRight className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
        <p className="text-xs text-text-500 font-mono">Enter to apply · Shift+Enter for new line</p>
      </div>

      {/* Primary actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={() => send('regenerate')}
          disabled={pending !== null}
          className="px-4 py-1.5 bg-bg-200/60 hover:bg-bg-200 disabled:opacity-40 disabled:cursor-not-allowed border border-border-300/20 text-text-200 text-xs font-semibold font-mono rounded transition-colors"
        >
          {pending === 'regenerate' ? (
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 border-2 border-text-400 border-t-transparent rounded-full animate-spin" />
              Regenerating…
            </span>
          ) : 'Regenerate'}
        </button>
        <button
          onClick={() => send('accept')}
          disabled={pending !== null}
          className="flex-1 px-4 py-1.5 bg-accent-main-100 hover:bg-accent-main-100/90 disabled:opacity-40 disabled:cursor-not-allowed text-bg-000 text-xs font-semibold font-mono rounded transition-colors"
        >
          {pending === 'accept' ? (
            <span className="flex items-center justify-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 border-2 border-bg-000/60 border-t-transparent rounded-full animate-spin" />
              Starting…
            </span>
          ) : 'Run Analysis ↗'}
        </button>
      </div>
    </div>
  );
}

export function DeepAnalyzeBlock({ message }: Props) {
  const {
    da_job_id,
    da_status = 'running',
    da_phases = {},
    da_load_rows,
    da_load_cols,
    da_plan_subtables,
    da_subtables = [],
    da_report_path,
    da_error,
    da_failed_phase,
  } = message;

  const doneCount = PHASES.filter(p => da_phases[p.key] === 'done').length;
  const statusKey: keyof typeof STATUS_LABELS =
    da_status === 'cancelled'      ? 'cancelled' :
    da_status === 'error'          ? 'error' :
    da_status === 'done'           ? 'done' :
    da_status === 'plan_reviewing' ? 'plan_reviewing' :
    da_status === 'clarifying'     ? 'clarifying' : 'running';

  return (
    <div className="bg-bg-000 border border-border-300/15 rounded-lg overflow-hidden">

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border-300/10">
        <BarChart2 className="w-4 h-4 text-accent-main-100 flex-shrink-0" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-text-300">deep analyze</span>
            <span className={`text-xs font-mono font-semibold ${STATUS_COLORS[statusKey]}`}>
              {STATUS_LABELS[statusKey]}
            </span>
          </div>
          {(da_load_rows != null || da_load_cols != null) && (
            <p className="text-xs text-text-400 font-mono mt-0.5">
              {da_load_rows != null && <span>{da_load_rows.toLocaleString()} rows</span>}
              {da_load_rows != null && da_load_cols != null && <span> · </span>}
              {da_load_cols != null && <span>{da_load_cols} cols</span>}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0 text-xs font-mono text-text-400">
          <span>{doneCount}/{PHASES.length}</span>
          {da_job_id && <span className="text-text-500 opacity-50 truncate max-w-[16ch]">{da_job_id}</span>}
        </div>
      </div>

      {/* Status stripe */}
      <div className={
        da_status === 'done'           ? 'h-0.5 bg-emerald-500/60' :
        da_status === 'error'          ? 'h-0.5 bg-red-500/60' :
        da_status === 'cancelled'      ? 'h-0.5 bg-text-500/40' :
        da_status === 'plan_reviewing' ? 'h-0.5 bg-purple-500/40' :
        da_status === 'clarifying'     ? 'h-0.5 bg-sky-500/40' :
        'h-0.5 bg-bg-200'
      }>
        {da_status === 'running' && (
          <div
            className="h-full bg-accent-main-100 transition-all duration-500"
            style={{ width: `${Math.max((doneCount / PHASES.length) * 100, 3)}%` }}
          />
        )}
      </div>

      {/* Phase pills */}
      <div className="px-4 py-3 flex flex-wrap gap-1.5">
        {PHASES.map(p => {
          const st = da_phases[p.key];
          return (
            <div
              key={p.key}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono ${phaseClass(st)}`}
            >
              {phaseIcon(st)}
              <span>{p.label}</span>
            </div>
          );
        })}
      </div>

      {/* Clarify Q&A panel */}
      {da_status === 'clarifying' && <ClarifyPanel message={message} />}

      {/* Plan review panel */}
      {da_status === 'plan_reviewing' && <PlanReviewPanel message={message} />}

      {/* Error message */}
      {da_status === 'error' && da_error && (
        <div className="mx-4 mb-3 px-3 py-2 text-xs text-red-400 font-mono bg-red-500/5 border border-red-500/30 rounded-md">
          {da_failed_phase && <span className="font-semibold mr-1">{da_failed_phase}:</span>}
          {da_error}
        </div>
      )}

      {/* Sub-tables */}
      {da_subtables.length > 0 && (
        <div className="mx-4 mb-3 border border-border-300/10 rounded-md overflow-hidden">
          <div className="px-3 py-1.5 bg-bg-200/40 flex items-center justify-between">
            <span className="text-xs font-semibold text-text-200 font-mono">Sub-tables</span>
            <span className="text-xs text-text-500 font-mono">
              {da_subtables.filter(s => s.status === 'done').length}/{da_plan_subtables ?? da_subtables.length}
            </span>
          </div>
          <div className="divide-y divide-border-300/10">
            {da_subtables.map((s, i) => (
              <ItemRow
                key={i}
                name={s.name}
                status={s.status}
                error={s.error}
                suffix={s.status === 'done' ? `${s.rows.toLocaleString()} rows` : undefined}
              />
            ))}
          </div>
        </div>
      )}

      {/* Final report */}
      {da_report_path && (
        <div className="mx-4 mb-4 flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-md">
          <FileText className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
          <span className="text-xs font-mono text-emerald-300 truncate" title={da_report_path}>
            Report: {da_report_path}
          </span>
        </div>
      )}
    </div>
  );
}
