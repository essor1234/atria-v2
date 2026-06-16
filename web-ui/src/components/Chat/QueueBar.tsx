import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useChatStore } from '../../stores/chat';

export function QueueBar() {
  const [expanded, setExpanded] = useState(false);

  const queuedMessages = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.queuedMessages ?? [] : [];
  });

  if (queuedMessages.length === 0) return null;

  return (
    <div className="px-4">
      <div className="border-t border-border-300/15 bg-bg-200/50 rounded-t-lg overflow-hidden">
        <button
          onClick={() => setExpanded(prev => !prev)}
          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-300 hover:text-text-100 transition-colors"
        >
          <ChevronRight className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`} />
          <span>
            {queuedMessages.length} message{queuedMessages.length !== 1 ? 's' : ''} queued
          </span>
        </button>

        <div
          className="transition-all duration-fast ease-motion-out overflow-hidden"
          style={{ maxHeight: expanded ? `${queuedMessages.length * 40 + 8}px` : '0px' }}
        >
          <div className="px-3 pb-2 space-y-1">
            {queuedMessages.map((msg, i) => (
              <div
                key={i}
                className="text-xs text-text-300 bg-bg-100/60 rounded px-2.5 py-1.5 truncate"
                title={msg}
              >
                {msg}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
