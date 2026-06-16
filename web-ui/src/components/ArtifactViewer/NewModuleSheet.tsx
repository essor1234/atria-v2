import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Sparkles, CheckCircle2, AlertCircle } from 'lucide-react';
import { useModulesStore } from '../../stores/modules';
import { useToastStore } from '../../stores/toast';
import type { ModuleTemplate } from '../../api/modules';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (name: string) => void;
}

const NAME_RE = /^[a-z0-9][a-z0-9_-]*$/;
const NAME_MAX = 64;
const SUMMARY_MAX = 200;

interface ValidationResult {
  ok: boolean;
  error: string | null;
}

function validateName(raw: string, existing: string[]): ValidationResult {
  if (!raw) return { ok: false, error: null };
  const name = raw.trim();
  if (name !== raw) return { ok: false, error: 'No leading or trailing spaces.' };
  if (name.length > NAME_MAX) return { ok: false, error: `Max ${NAME_MAX} characters.` };
  if (/[A-Z]/.test(name)) return { ok: false, error: 'Use lowercase letters only.' };
  if (/\s/.test(name)) return { ok: false, error: 'No spaces — use - or _ instead.' };
  if (!/^[a-z0-9]/.test(name)) return { ok: false, error: 'Must start with a letter or digit.' };
  if (!NAME_RE.test(name)) return { ok: false, error: 'Only a–z, 0–9, _ and - are allowed.' };
  if (existing.includes(name)) return { ok: false, error: 'A module with this name already exists.' };
  return { ok: true, error: null };
}

function validateSummary(raw: string): ValidationResult {
  if (raw.length > SUMMARY_MAX) return { ok: false, error: `Max ${SUMMARY_MAX} characters.` };
  return { ok: true, error: null };
}

const TEMPLATES: Record<ModuleTemplate, { label: string; hint: string }> = {
  blank: {
    label: 'Blank',
    hint: 'Empty SKILL.md. Add files yourself.',
  },
  skill: {
    label: 'Skill only',
    hint: 'A SKILL.md prompt block. No scripts.',
  },
  skill_script: {
    label: 'Skill + script',
    hint: 'SKILL.md plus scripts/main.py starter.',
  },
  skill_dashboard: {
    label: 'Skill + dashboard',
    hint: 'SKILL.md, scripts/main.py, and templates/dashboard.html.',
  },
};

export function NewModuleSheet({ open, onClose, onCreated }: Props) {
  const { modules, create } = useModulesStore();
  const addToast = useToastStore(s => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [template, setTemplate] = useState<ModuleTemplate>('skill');
  const [busy, setBusy] = useState(false);
  const [nameTouched, setNameTouched] = useState(false);
  const [summaryTouched, setSummaryTouched] = useState(false);
  const [submitAttempted, setSubmitAttempted] = useState(false);

  useEffect(() => {
    if (open) {
      setName('');
      setSummary('');
      setTemplate('skill');
      setBusy(false);
      setNameTouched(false);
      setSummaryTouched(false);
      setSubmitAttempted(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const existingNames = useMemo(() => modules.map(m => m.name), [modules]);
  const nameCheck = useMemo(() => validateName(name, existingNames), [name, existingNames]);
  const summaryCheck = useMemo(() => validateSummary(summary), [summary]);
  const formOk = nameCheck.ok && summaryCheck.ok;
  const showNameError = (nameTouched || submitAttempted) && !!nameCheck.error;
  const showSummaryError = (summaryTouched || submitAttempted) && !!summaryCheck.error;

  // Escape closes the dialog
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const onSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (busy) return;
    setSubmitAttempted(true);
    if (!formOk) {
      // Surface the first error as a toast so the user knows why the click did nothing.
      const msg = nameCheck.error || summaryCheck.error || 'Please fix the highlighted fields.';
      addToast(msg, 'warning');
      // Focus the bad field
      if (!nameCheck.ok) inputRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      await create(name, template, summary.trim());
      addToast(`Module “${name}” created.`, 'success');
      onCreated(name);
      onClose();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      addToast(`Failed to create module: ${msg}`, 'error');
      setBusy(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/55 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-module-title"
      onClick={onClose}
    >
      <form
        onSubmit={onSubmit}
        onClick={e => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-lg border border-hairline-soft bg-canvas shadow-modal"
      >
        <div className="flex items-center gap-2 px-5 py-3 border-b border-hairline-soft/60 flex-shrink-0">
          <Sparkles className="w-4 h-4 text-ink/55" />
          <span id="new-module-title" className="text-[14px] font-medium tracking-tight">New module</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded text-ink/45 hover:text-ink hover:bg-surface-soft cursor-pointer transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400/60"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-auto">
          <label className="block">
            <span className="block text-[11px] uppercase tracking-wide text-ink/50 mb-1">Name</span>
            <div className="relative">
              <input
                ref={inputRef}
                value={name}
                onChange={e => setName(e.target.value)}
                onBlur={() => setNameTouched(true)}
                placeholder="e.g. my-module"
                spellCheck={false}
                autoCapitalize="none"
                autoComplete="off"
                aria-invalid={showNameError}
                aria-describedby="name-help"
                className={`w-full px-3 py-2 pr-10 text-sm rounded-md border bg-canvas font-mono transition-colors focus:outline-none focus-visible:ring-1 ${
                  showNameError
                    ? 'border-semantic-danger focus-visible:ring-semantic-danger/60'
                    : nameCheck.ok && name
                      ? 'border-emerald-500/60 focus-visible:ring-emerald-500/60'
                      : 'border-hairline-soft focus-visible:ring-sky-400/60'
                }`}
              />
              {name && (
                nameCheck.ok ? (
                  <CheckCircle2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-emerald-500" aria-hidden="true" />
                ) : showNameError ? (
                  <AlertCircle className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-semantic-danger" aria-hidden="true" />
                ) : null
              )}
            </div>
            <div id="name-help" className="mt-1 flex items-start justify-between gap-3 min-h-[16px]">
              <span className={`text-[11px] leading-snug ${showNameError ? 'text-semantic-danger' : 'text-ink/45'}`}>
                {showNameError
                  ? nameCheck.error
                  : 'Lowercase letters, digits, _ and -. Starts with a letter or digit.'}
              </span>
              <span className={`text-[10px] font-mono tabular-nums ${name.length > NAME_MAX ? 'text-semantic-danger' : 'text-ink/35'}`}>
                {name.length}/{NAME_MAX}
              </span>
            </div>
          </label>

          <label className="block">
            <span className="block text-[11px] uppercase tracking-wide text-ink/50 mb-1">Summary <span className="text-ink/40 normal-case tracking-normal">(optional)</span></span>
            <input
              value={summary}
              onChange={e => setSummary(e.target.value)}
              onBlur={() => setSummaryTouched(true)}
              placeholder="One line shown to the agent."
              aria-invalid={showSummaryError}
              aria-describedby="summary-help"
              className={`w-full px-3 py-2 text-sm rounded-md border bg-canvas transition-colors focus:outline-none focus-visible:ring-1 ${
                showSummaryError
                  ? 'border-semantic-danger focus-visible:ring-semantic-danger/60'
                  : 'border-hairline-soft focus-visible:ring-sky-400/60'
              }`}
            />
            <div id="summary-help" className="mt-1 flex items-start justify-between gap-3 min-h-[16px]">
              <span className={`text-[11px] leading-snug ${showSummaryError ? 'text-semantic-danger' : 'text-ink/45'}`}>
                {showSummaryError ? summaryCheck.error : 'A short hint that helps the agent decide when to use this module.'}
              </span>
              <span className={`text-[10px] font-mono tabular-nums ${summary.length > SUMMARY_MAX ? 'text-semantic-danger' : 'text-ink/35'}`}>
                {summary.length}/{SUMMARY_MAX}
              </span>
            </div>
          </label>

          <div>
            <span className="block text-[11px] uppercase tracking-wide text-ink/50 mb-2">Start from</span>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {(Object.keys(TEMPLATES) as ModuleTemplate[]).map(k => {
                const active = template === k;
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setTemplate(k)}
                    aria-pressed={active}
                    className={`text-left rounded-md border px-3 py-2.5 h-full cursor-pointer transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400/60 ${
                      active
                        ? 'border-sky-500 bg-sky-500/10 ring-1 ring-sky-500/40'
                        : 'border-hairline-soft bg-canvas hover:bg-surface-soft/60'
                    }`}
                  >
                    <div className={`text-[13px] font-medium leading-tight ${active ? 'text-sky-600' : 'text-ink'}`}>{TEMPLATES[k].label}</div>
                    <div className={`text-[11px] leading-snug mt-1 ${active ? 'text-ink/70' : 'text-ink/55'}`}>{TEMPLATES[k].hint}</div>
                  </button>
                );
              })}
            </div>
          </div>

        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-hairline-soft/60 bg-surface-soft/30 flex-shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-[13px] rounded text-ink/65 hover:text-ink hover:bg-surface-soft cursor-pointer transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ink/40"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            aria-disabled={!formOk || busy}
            className={`px-4 py-1.5 text-[13px] rounded text-white whitespace-nowrap cursor-pointer transition-colors duration-fast focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400 ${
              formOk
                ? 'bg-sky-500/90 hover:bg-sky-500 active:scale-[0.98]'
                : 'bg-sky-500/40 hover:bg-sky-500/50'
            } disabled:opacity-60 disabled:cursor-not-allowed`}
          >
            {busy ? 'Creating…' : 'Create →'}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
