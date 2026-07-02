import { Settings2, Lock, Brain } from 'lucide-react';
import { useChatStore } from '../../stores/chat';

const MODE_STYLES = {
  normal: 'bg-bg-400/40 text-text-200 border-hairline-soft hover:bg-bg-400/60',
  plan: 'bg-accent-secondary-900 text-accent-secondary-100 border-accent-secondary-900/50 hover:bg-accent-secondary-900/80',
} as const;

const AUTONOMY_STYLES = {
  'Manual': 'bg-bg-400/40 text-text-200 border-hairline-soft hover:bg-bg-400/60',
  'Semi-Auto': 'bg-accent-secondary-900 text-accent-secondary-100 border-accent-secondary-900/50 hover:bg-accent-secondary-900/80',
  'Auto': 'bg-success-100/10 text-success-100 border-success-100/20 hover:bg-success-100/15',
} as const;

const THINKING_STYLES: Record<string, string> = {
  'Off':           'bg-bg-200 text-text-500 border-hairline-soft hover:bg-bg-300',
  'Low':           'bg-cyan-500/10 text-cyan-600 border-cyan-500/20 hover:bg-cyan-500/15',
  'Medium':        'bg-success-100/10 text-success-100 border-success-100/20 hover:bg-success-100/15',
  'High':          'bg-yellow-500/10 text-yellow-600 border-yellow-500/20 hover:bg-yellow-500/15',
} as const;

export function StatusBar() {
  const status = useChatStore(state => state.status);
  const thinkingLevel = useChatStore(state => state.thinkingLevel);
  const toggleMode = useChatStore(state => state.toggleMode);
  const cycleAutonomy = useChatStore(state => state.cycleAutonomy);
  const cycleThinkingLevel = useChatStore(state => state.cycleThinkingLevel);

  if (!status) return null;

  const pillBase = 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium cursor-pointer transition-colors select-none hover:scale-105 active:scale-[0.98] whitespace-nowrap';

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Mode pill */}
      <button
        onClick={toggleMode}
        className={`${pillBase} ${MODE_STYLES[status.mode]}`}
        title="Normal: full tool access · Plan: read-only exploration. Click to toggle (Shift+Tab)"
      >
        <Settings2 className="w-3 h-3" strokeWidth={2} />
        Mode: {status.mode === 'normal' ? 'Normal' : 'Plan'}
      </button>

      {/* Autonomy pill */}
      <button
        onClick={cycleAutonomy}
        className={`${pillBase} ${AUTONOMY_STYLES[status.autonomy_level]}`}
        title="Manual: approve each tool · Semi-Auto: auto-approve safe tools · Auto: approve all. Click to cycle (Ctrl+Shift+A)"
      >
        <Lock className="w-3 h-3" strokeWidth={2} />
        Approval: {status.autonomy_level}
      </button>

      {/* Thinking pill */}
      <button
        onClick={cycleThinkingLevel}
        className={`${pillBase} ${THINKING_STYLES[thinkingLevel] || THINKING_STYLES['Medium']}`}
        title="Controls how much the AI reasons before responding. Click to cycle (Ctrl+Shift+T)"
      >
        <Brain className="w-3 h-3" strokeWidth={2} />
        Think: {thinkingLevel}
      </button>
    </div>
  );
}
