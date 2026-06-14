import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { ChevronRight, ChevronDown, ArrowRight, FileText, ClipboardList } from 'lucide-react';
import type { Message, TaxonomyCategory, DeepResearchSection } from '../../types';
import { wsClient } from '../../api/websocket';

interface Props {
  message: Message;
}

const DEPTH_OPTIONS = [
  { value: 'shallow', label: 'Shallow', desc: 'Quick overview' },
  { value: 'standard', label: 'Standard', desc: 'Balanced' },
  { value: 'deep', label: 'Deep', desc: 'Comprehensive' },
] as const;
type Depth = 'shallow' | 'standard' | 'deep';

const STATUS_COLORS = {
  reviewing: 'text-purple-400',
  queued:    'text-text-400',
  running:   'text-amber-400',
  done:      'text-emerald-400',
  error:     'text-red-400',
} as const;

const STATUS_LABELS = {
  reviewing: 'Awaiting review',
  queued:    'Queued',
  running:   'Researching…',
  done:      'Complete',
  error:     'Error',
} as const;

// ─── Read-only taxonomy tree ──────────────────────────────────────────────────

function TaxonomyTree({ categories }: { categories: TaxonomyCategory[] }) {
  const [openCats, setOpenCats] = useState<Set<number>>(() => new Set(categories.map((_, i) => i)));

  return (
    <div className="space-y-1.5">
      {categories.map((cat, ci) => (
        <div key={ci} className="border border-border-300/15 rounded-md overflow-hidden">
          <button
            onClick={() => setOpenCats(prev => {
              const next = new Set(prev);
              next.has(ci) ? next.delete(ci) : next.add(ci);
              return next;
            })}
            className="w-full flex items-center gap-2 px-3 py-1.5 bg-bg-200/40 hover:bg-bg-200/70 transition-colors text-left"
          >
            <ChevronRight
              className={`w-3 h-3 text-text-400 flex-shrink-0 transition-transform ${openCats.has(ci) ? 'rotate-90' : ''}`}
            />
            <span className="text-xs font-semibold text-text-100 font-mono flex-1">{cat.name}</span>
            <span className="text-xs text-text-500 font-mono">{cat.sub_topics.length}</span>
          </button>
          {openCats.has(ci) && (
            <div className="px-3 py-1.5 space-y-0.5">
              {cat.sub_topics.map((sub, si) => (
                <div key={si} className="flex items-start gap-1.5">
                  <span className="text-text-500 font-mono text-xs mt-0.5">└</span>
                  <span className="text-xs text-text-300 font-mono">{sub.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Review panel — blocks until user accepts or requests regeneration ────────

function ReviewPanel({ message }: { message: Message }) {
  const { dr_review_request_id, dr_taxonomy, dr_job_id, dr_topic } = message;

  const [topicDraft] = useState(dr_topic ?? '');
  const [modifyInstructions, setModifyInstructions] = useState('');
  const [depth, setDepth] = useState<Depth>('standard');
  const [pending, setPending] = useState<'modify' | 'regenerate' | 'accept' | null>(null);

  // Reset local state when a new taxonomy arrives (after modify/regenerate)
  const prevRequestId = useState(dr_review_request_id)[0];
  if (prevRequestId !== dr_review_request_id && pending !== null) {
    setPending(null);
    setModifyInstructions('');
  }

  const send = (action: 'modify' | 'regenerate' | 'accept') => {
    if (!dr_review_request_id || pending) return;
    if (action === 'modify' && !modifyInstructions.trim()) return;
    setPending(action);
    wsClient.send({
      type: 'deep_research_taxonomy_response',
      data: {
        requestId: dr_review_request_id,
        job_id: dr_job_id,
        action,
        topic: topicDraft.trim() || dr_topic,
        taxonomy: dr_taxonomy,
        depth,
        ...(action === 'modify' && { instructions: modifyInstructions.trim() }),
      },
    });
  };

  const handleModifyKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send('modify');
    }
  };

  const categories = dr_taxonomy?.taxonomy ?? [];
  const totalSubs = categories.reduce((acc, c) => acc + (c.sub_topics?.length ?? 0), 0);

  return (
    <div className="p-4 space-y-4">

      {/* Generated taxonomy — read-only, collapsible */}
      {categories.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-text-400 font-mono">
            Taxonomy — {categories.length} categories, {totalSubs} subtopics
          </p>
          <TaxonomyTree categories={categories} />
        </div>
      )}

      {/* Modification request input */}
      <div className="space-y-1.5">
        <label className="text-xs text-text-400 font-mono">Request changes</label>
        <div className="flex gap-2 items-end">
          <textarea
            className="flex-1 bg-bg-100 border border-border-300/20 focus:border-accent-main-100/50 rounded-md px-3 py-2 text-sm text-text-100 font-mono resize-none outline-none transition-colors placeholder:text-text-500 min-h-[2.5rem]"
            rows={2}
            value={modifyInstructions}
            onChange={e => setModifyInstructions(e.target.value)}
            onKeyDown={handleModifyKey}
            placeholder={'e.g. "translate all to Vietnamese", "add a category on economics", "remove mental health subtopic"...'}
            disabled={pending !== null}
          />
          <button
            onClick={() => send('modify')}
            disabled={pending !== null || !modifyInstructions.trim()}
            className="flex-shrink-0 px-3 py-2 bg-bg-200/60 hover:bg-bg-200 disabled:opacity-40 disabled:cursor-not-allowed border border-border-300/20 text-text-200 text-xs font-semibold font-mono rounded transition-colors h-10"
            title="Apply changes (Enter)"
          >
            {pending === 'modify' ? (
              <span className="inline-block w-3.5 h-3.5 border-2 border-text-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <ArrowRight className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
        <p className="text-xs text-text-500 font-mono">Press Enter or ↵ to apply · Shift+Enter for new line</p>
      </div>

      {/* Depth selector */}
      <div className="space-y-1.5">
        <p className="text-xs text-text-400 font-mono">Research depth</p>
        <div className="flex gap-2">
          {DEPTH_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setDepth(opt.value as Depth)}
              disabled={pending !== null}
              className={`flex-1 px-3 py-1.5 rounded text-xs font-mono border transition-colors disabled:opacity-40 ${
                depth === opt.value
                  ? 'bg-accent-main-100/15 border-accent-main-100/50 text-accent-main-100'
                  : 'bg-bg-200/40 border-border-300/15 text-text-300 hover:border-border-300/40 hover:text-text-200'
              }`}
              title={opt.desc}
            >
              {opt.label}
            </button>
          ))}
        </div>
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
          ) : 'Start Research ↗'}
        </button>
      </div>
    </div>
  );
}

// ─── Section accordion (running / done state) ─────────────────────────────────

function SectionAccordion({ sections }: { sections: DeepResearchSection[] }) {
  const [open, setOpen] = useState<string | null>(null);

  const grouped: Record<string, DeepResearchSection[]> = {};
  for (const s of sections) {
    if (!grouped[s.category]) grouped[s.category] = [];
    grouped[s.category].push(s);
  }

  return (
    <div className="space-y-1">
      {Object.entries(grouped).map(([cat, secs], ci) => (
        <div key={ci} className="border border-border-300/10 rounded-md overflow-hidden">
          <div className="px-3 py-1.5 bg-bg-200/50 text-xs font-semibold text-text-200 font-mono">
            {cat}
          </div>
          {secs.map((sec, si) => {
            const key = `${ci}-${si}`;
            const isOpen = open === key;
            return (
              <div key={si} className="border-t border-border-300/10">
                <button
                  className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-bg-100/40 transition-colors text-left"
                  onClick={() => setOpen(isOpen ? null : key)}
                >
                  <span className="text-xs text-text-200 font-mono truncate">{sec.subtopic}</span>
                  <ChevronDown
                    className={`w-3 h-3 text-text-400 flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                  />
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 prose prose-sm max-w-none text-text-200">
                    <ReactMarkdown
                      components={{
                        h3({ children }) { return <h3 className="text-text-100 text-sm font-semibold mt-2 mb-1">{children}</h3>; },
                        p({ children }) { return <p className="text-xs text-text-200 mb-1.5 leading-relaxed">{children}</p>; },
                        ul({ children }) { return <ul className="list-disc pl-4 space-y-0.5 mb-1.5">{children}</ul>; },
                        li({ children }) { return <li className="text-xs text-text-200">{children}</li>; },
                        strong({ children }) { return <strong className="font-semibold text-text-100">{children}</strong>; },
                      }}
                    >
                      {sec.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ─── Static taxonomy tree (post-confirmation) ─────────────────────────────────

function StaticTaxonomyTree({ categories }: { categories: TaxonomyCategory[] }) {
  return (
    <div className="space-y-2">
      {categories.map((cat, ci) => (
        <div key={ci}>
          <div className="text-xs font-semibold text-text-100 font-mono">{cat.name}</div>
          <div className="ml-3 mt-0.5 space-y-0.5">
            {cat.sub_topics.map((sub, si) => (
              <div key={si} className="text-xs text-text-300 font-mono">└ {sub.name}</div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main block ───────────────────────────────────────────────────────────────

export function DeepResearchBlock({ message }: Props) {
  const [showTaxonomy, setShowTaxonomy] = useState(false);
  const {
    dr_job_id, dr_topic, dr_taxonomy, dr_status = 'queued',
    dr_progress = 0, dr_sections = [], dr_active_section, dr_error, dr_report_path,
  } = message;

  const categories = dr_taxonomy?.taxonomy ?? [];
  const totalSubs = categories.reduce((acc, c) => acc + c.sub_topics.length, 0);
  const doneSubs = dr_sections.length;
  const isReviewing = dr_status === 'reviewing';

  return (
    <div className="bg-bg-000 border border-border-300/15 rounded-lg overflow-hidden">

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border-300/10">
        <ClipboardList className="w-4 h-4 text-accent-main-100 flex-shrink-0" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-text-300">deep research</span>
            <span className={`text-xs font-mono font-semibold ${STATUS_COLORS[dr_status]}`}>
              {STATUS_LABELS[dr_status]}
            </span>
          </div>
          {dr_topic && (
            <p className="text-sm text-text-100 font-medium truncate mt-0.5">{dr_topic}</p>
          )}
        </div>

        {!isReviewing && (
          <div className="flex items-center gap-2 flex-shrink-0 text-xs font-mono text-text-400">
            {dr_status !== 'error' && <span>{doneSubs}/{totalSubs}</span>}
            <span className="text-text-500 opacity-50">{dr_job_id}</span>
          </div>
        )}
      </div>

      {/* Progress / status stripe */}
      {isReviewing && <div className="h-0.5 bg-purple-500/40" />}
      {dr_status === 'queued' && <div className="h-0.5 bg-bg-200" />}
      {dr_status === 'running' && (
        <div className="h-0.5 bg-bg-200">
          <div
            className="h-full bg-accent-main-100 transition-all duration-500"
            style={{ width: `${Math.max(dr_progress * 100, 3)}%` }}
          />
        </div>
      )}
      {dr_status === 'done'  && <div className="h-0.5 bg-emerald-500/60" />}
      {dr_status === 'error' && <div className="h-0.5 bg-red-500/60" />}

      {/* Review panel — completely blocks until user responds */}
      {isReviewing && <ReviewPanel message={message} />}

      {/* Active section indicator */}
      {dr_active_section && dr_status === 'running' && (
        <div className="px-4 py-2 border-b border-border-300/10 flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
          <span className="text-xs text-text-300 font-mono truncate">
            {dr_active_section.category} → {dr_active_section.subtopic}
          </span>
        </div>
      )}

      {/* Error message */}
      {dr_status === 'error' && dr_error && (
        <div className="px-4 py-2 text-xs text-red-400 font-mono border-b border-border-300/10">
          {dr_error}
        </div>
      )}

      {/* Post-confirmation body (queued / running / done / error) */}
      {!isReviewing && (
        <div className="p-4 space-y-3">

          {/* Report saved path */}
          {dr_status === 'done' && dr_report_path && (
            <div className="flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-md">
              <FileText className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
              <span className="text-xs font-mono text-emerald-300 truncate" title={dr_report_path}>
                Saved: {dr_report_path}
              </span>
            </div>
          )}

          {/* Taxonomy toggle */}
          {categories.length > 0 && (
            <div>
              <button
                onClick={() => setShowTaxonomy(v => !v)}
                className="flex items-center gap-1.5 text-xs text-text-400 hover:text-text-200 transition-colors font-mono"
              >
                <ChevronRight className={`w-3 h-3 transition-transform ${showTaxonomy ? 'rotate-90' : ''}`} />
                Research plan ({categories.length} categories, {totalSubs} subtopics)
              </button>
              {showTaxonomy && (
                <div className="mt-2 pl-2 border-l border-border-300/20">
                  <StaticTaxonomyTree categories={categories} />
                </div>
              )}
            </div>
          )}

          {/* Completed sections */}
          {dr_sections.length > 0 && (
            <div>
              <p className="text-xs font-mono text-text-400 mb-1.5">
                {dr_sections.length} section{dr_sections.length !== 1 ? 's' : ''} completed
              </p>
              <SectionAccordion sections={dr_sections} />
            </div>
          )}

        </div>
      )}
    </div>
  );
}
