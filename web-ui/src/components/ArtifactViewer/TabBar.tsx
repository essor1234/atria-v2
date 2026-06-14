import { X, FileText, Code2, Image as ImageIcon, BarChart3, File as FileIcon } from 'lucide-react';
import { useViewerTabsStore } from '../../stores/viewerTabs';
import { pickRenderer } from './viewers/extensions';
import type { ViewerTab } from '../../types';

interface Props {
  convId: string;
  onCollapse?: () => void;
}

function iconFor(tab: ViewerTab) {
  const kind = pickRenderer(tab.ext);
  if (kind === 'markdown') return FileText;
  if (kind === 'monaco') return Code2;
  if (kind === 'image') return ImageIcon;
  if (kind === 'csv' || kind === 'excel') return BarChart3;
  return FileIcon;
}

export function TabBar({ convId, onCollapse: _onCollapse }: Props) {
  const slice = useViewerTabsStore(s => s.tabsByConv[convId]);
  const setActive = useViewerTabsStore(s => s.setActive);
  const closeTab = useViewerTabsStore(s => s.closeTab);

  const tabs = slice?.tabs ?? [];
  const activeId = slice?.activeId ?? null;

  return (
    <div className="flex-1 flex items-center gap-0.5 overflow-x-auto px-1 py-1 min-w-0">
      {tabs.length === 0 && (
        <span className="text-[13px] font-mono text-ink/35 px-2 select-none">No file open</span>
      )}
      {tabs.map(tab => {
        const Icon = iconFor(tab);
        const isActive = tab.id === activeId;
        return (
          <div
            key={tab.id}
            onClick={() => setActive(convId, tab.id)}
            onMouseDown={(e) => {
              if (e.button === 1) { e.preventDefault(); closeTab(convId, tab.id); }
            }}
            className={`group inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-md text-[12px] font-mono cursor-pointer transition-colors whitespace-nowrap ${
              isActive
                ? 'bg-ink/10 text-ink border-b-2 border-b-sky-400/70 rounded-b-none'
                : 'text-ink/55 hover:bg-surface-soft hover:text-ink/80'
            }`}
            role="tab"
            aria-selected={isActive}
            title={tab.path}
          >
            <Icon className={`w-3 h-3 flex-shrink-0 ${isActive ? 'text-sky-400/80' : 'text-ink/40'}`} />
            <span className="truncate max-w-[140px]">{tab.name}</span>
            <button
              onClick={(e) => { e.stopPropagation(); closeTab(convId, tab.id); }}
              aria-label={`Close ${tab.name}`}
              className={`p-0.5 rounded hover:bg-ink/15 ${
                isActive ? 'opacity-60 hover:opacity-100' : 'opacity-0 group-hover:opacity-60'
              } transition-opacity`}
            >
              <X className="w-2.5 h-2.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
