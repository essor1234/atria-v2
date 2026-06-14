import { useState } from 'react';
import { Search, ChevronDown, ExternalLink } from 'lucide-react';
import type { Message } from '../../types';

interface Props {
  message: Message;
}

export function SearchResultBlock({ message }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { search_query, search_result_count = 0, search_results = [], search_provider } = message;
  const hasResults = search_results.length > 0;

  return (
    <div className="bg-bg-000 border border-border-300/15 rounded-lg overflow-hidden animate-slide-up">
      {/* Header row */}
      <button
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-bg-100/50 transition-colors text-left"
        onClick={() => hasResults && setExpanded(v => !v)}
        disabled={!hasResults}
      >
        {/* Search icon */}
        <Search className="w-4 h-4 text-accent-secondary-100 flex-shrink-0" />

        <div className="flex-1 min-w-0">
          <span className="text-xs font-mono text-text-300 mr-2">searched</span>
          <span className="text-sm text-text-100 font-medium truncate">{search_query}</span>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {search_provider && (
            <span className="text-xs text-text-400 font-mono">{search_provider}</span>
          )}
          <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-bg-200 text-text-300 border border-border-300/20">
            {search_result_count} results
          </span>
          {hasResults && (
            <ChevronDown className={`w-3.5 h-3.5 text-text-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
          )}
        </div>
      </button>

      {/* Expanded results */}
      {expanded && hasResults && (
        <div className="border-t border-border-300/10 divide-y divide-border-300/10">
          {search_results.map((result, i) => (
            <a
              key={i}
              href={result.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-3 px-4 py-2 hover:bg-bg-100/50 transition-colors group"
            >
              {/* Favicon placeholder */}
              <div className="w-4 h-4 mt-0.5 rounded-sm bg-bg-300 flex-shrink-0 flex items-center justify-center">
                <span className="text-text-400 text-[8px] font-bold uppercase leading-none">
                  {result.domain?.[0] || '?'}
                </span>
              </div>

              <div className="flex-1 min-w-0">
                <p className="text-xs text-text-100 font-medium truncate group-hover:text-accent-secondary-100 transition-colors">
                  {result.title || result.url}
                </p>
                <p className="text-[11px] text-text-400 font-mono truncate mt-0.5">{result.domain}</p>
              </div>

              <ExternalLink className="w-3 h-3 text-text-400 flex-shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
