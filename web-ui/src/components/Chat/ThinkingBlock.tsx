import { useState, useRef, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';

interface ThinkingBlockProps {
  content: string;
  level?: string;
  isActive?: boolean;
}

export function ThinkingBlock({ content, level, isActive }: ThinkingBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState(0);

  const isCritique = content.startsWith('[Critique]');

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setContentHeight(el.scrollHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="animate-slide-up pl-[26px]">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        aria-label={isExpanded ? 'Collapse thinking' : 'Expand thinking'}
        className={`flex items-center gap-1.5 py-0.5 text-left cursor-pointer rounded transition-colors ${isActive ? 'thinking-shimmer' : ''}`}
      >
        <span className="text-ink/30 text-[13px] select-none">{isCritique ? '◆' : '◇'}</span>
        <span className="text-[13px] text-ink/50 font-medium">
          {isCritique ? 'Critique' : 'Thought'}
        </span>
        {level && (
          <span className="text-[11px] text-ink/30 font-mono">· {level}</span>
        )}
        <ChevronDown
          className={`w-3 h-3 text-ink/30 transition-transform duration-fast ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>

      <div
        className="overflow-hidden transition-all duration-base ease-motion-out"
        style={{ maxHeight: isExpanded ? `${contentHeight + 16}px` : '0px' }}
      >
        <div ref={contentRef} className="mt-2 ml-4 border-l border-hairline-soft pl-3 pb-2">
          <pre className="text-[12.5px] text-ink/50 whitespace-pre-wrap font-mono leading-[1.55] m-0 p-0 bg-transparent border-0">
            {content}
          </pre>
        </div>
      </div>
    </div>
  );
}
