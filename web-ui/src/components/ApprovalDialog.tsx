import { useEffect } from 'react';
import { TriangleAlert } from 'lucide-react';
import { useChatStore } from '../stores/chat';

export function ApprovalDialog() {
  const pendingApproval = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.pendingApproval ?? null : null;
  });
  const respondToApproval = useChatStore(state => state.respondToApproval);

  // Define handlers first (before hooks)
  const handleApprove = () => {
    if (pendingApproval) {
      respondToApproval(pendingApproval.id, true, false);
    }
  };

  const handleApproveAll = () => {
    if (pendingApproval) {
      respondToApproval(pendingApproval.id, true, true);
    }
  };

  const handleDeny = () => {
    if (pendingApproval) {
      respondToApproval(pendingApproval.id, false, false);
    }
  };

  // Debug log - MUST be before early return
  useEffect(() => {
    if (pendingApproval) {
      console.log('[ApprovalDialog] Showing approval dialog:', pendingApproval);
    } else {
      console.log('[ApprovalDialog] No pending approval');
    }
  }, [pendingApproval]);

  // Keyboard shortcuts - MUST be before early return
  useEffect(() => {
    if (!pendingApproval) return;

    const handleKeyPress = (e: KeyboardEvent) => {
      if (e.key === '1') {
        handleApprove();
      } else if (e.key === '2') {
        handleApproveAll();
      } else if (e.key === '3') {
        handleDeny();
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [pendingApproval]);

  // Early return AFTER all hooks
  if (!pendingApproval) {
    return null;
  }

  return (
    <div className="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-50 animate-fade-in">
      <div className="bg-bg-000 rounded-xl shadow-2xl border border-border-300/15 max-w-2xl w-full mx-4 max-h-[85vh] flex flex-col animate-slide-up">
        {/* Header */}
        <div className="border-b border-border-300/15 px-6 py-4 flex-shrink-0">
          <h2 className="text-lg font-semibold text-text-000">Approval Required</h2>
          <p className="text-sm text-text-300 mt-1">
            The assistant needs permission to execute the following operation
          </p>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1 min-h-0">
          {/* Tool Name */}
          <div>
            <div className="text-xs font-medium text-text-400 uppercase tracking-wider mb-1">
              Tool
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-accent-main-100" />
              <code className="text-sm font-mono bg-bg-100 px-2 py-1 rounded border border-border-300/15">
                {pendingApproval.tool_name}
              </code>
            </div>
          </div>

          {/* Description */}
          <div>
            <div className="text-xs font-medium text-text-400 uppercase tracking-wider mb-1">
              Description
            </div>
            <p className="text-sm text-text-000 leading-relaxed">
              {pendingApproval.description}
            </p>
          </div>

          {/* Preview */}
          {pendingApproval.preview && (
            <div>
              <div className="text-xs font-medium text-text-400 uppercase tracking-wider mb-2">
                Preview
              </div>
              <div className="bg-bg-100 rounded-lg border border-border-300/15 p-4 max-h-48 overflow-y-auto">
                <pre className="text-xs text-text-000 font-mono whitespace-pre-wrap">
                  {pendingApproval.preview}
                </pre>
              </div>
            </div>
          )}

          {/* Arguments */}
          {Object.keys(pendingApproval.arguments).length > 0 && (
            <div>
              <div className="text-xs font-medium text-text-400 uppercase tracking-wider mb-2">
                Arguments
              </div>
              <div className="bg-bg-100 rounded-lg border border-border-300/15 p-4 max-h-64 overflow-y-auto">
                <pre className="text-xs text-text-000 font-mono whitespace-pre-wrap">
                  {JSON.stringify(pendingApproval.arguments, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Warning */}
          <div className="bg-warning-100/10 border border-warning-100/20 rounded-lg p-4">
            <div className="flex gap-3">
              <TriangleAlert className="w-5 h-5 text-warning-100 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-text-000">Review carefully before approving</p>
                <p className="text-xs text-text-300 mt-1">
                  This operation will be executed with your current permissions. Make sure you understand what it will do.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer - 3 Options */}
        <div className="border-t border-border-300/15 px-6 py-4 bg-bg-100 flex-shrink-0">
          <div className="space-y-2.5">
            {/* Option 1: Yes, run this command — mint color block */}
            <button
              onClick={handleApprove}
              className="w-full px-4 py-3.5 text-body-sm text-left bg-block-mint rounded-lg hover:brightness-95 transition-all flex items-center gap-3 group"
            >
              <div className="w-7 h-7 rounded-full bg-ink/10 group-hover:bg-ink/15 flex items-center justify-center text-ink font-mono font-semibold text-xs">
                1
              </div>
              <span className="text-ink">Yes, run this command</span>
            </button>

            {/* Option 2: Yes, and auto-approve — lilac color block */}
            <button
              onClick={handleApproveAll}
              className="w-full px-4 py-3.5 text-body-sm text-left bg-block-lilac rounded-lg hover:brightness-95 transition-all flex items-center gap-3 group"
            >
              <div className="w-7 h-7 rounded-full bg-ink/10 group-hover:bg-ink/15 flex items-center justify-center text-ink font-mono font-semibold text-xs">
                2
              </div>
              <div className="flex-1">
                <div className="text-ink">Yes, and auto-approve all <span className="font-[540]">{pendingApproval.tool_name}</span> commands</div>
                <div className="text-[13px] text-ink/70 mt-0.5">Future similar commands will run automatically</div>
              </div>
            </button>

            {/* Option 3: No, cancel — coral color block */}
            <button
              onClick={handleDeny}
              className="w-full px-4 py-3.5 text-body-sm text-left bg-block-coral rounded-lg hover:brightness-95 transition-all flex items-center gap-3 group"
            >
              <div className="w-7 h-7 rounded-full bg-ink/10 group-hover:bg-ink/15 flex items-center justify-center text-ink font-mono font-semibold text-xs">
                3
              </div>
              <span className="text-ink">No, cancel and provide feedback</span>
            </button>
          </div>

          {/* Keyboard shortcuts hint */}
          <div className="mt-4 pt-3 border-t border-border-300/15 text-center">
            <p className="text-xs text-text-500">
              Press <kbd className="px-1.5 py-0.5 bg-bg-200 border border-border-300/20 rounded text-xs font-mono">1</kbd>, <kbd className="px-1.5 py-0.5 bg-bg-200 border border-border-300/20 rounded text-xs font-mono">2</kbd>, or <kbd className="px-1.5 py-0.5 bg-bg-200 border border-border-300/20 rounded text-xs font-mono">3</kbd> to select
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
