import { useEffect } from 'react';
import { Search, Eye, EyeOff, RefreshCw } from 'lucide-react';
import { useFileExplorerStore } from '../../stores/fileExplorer';
import { FileTreeNode } from './FileTreeNode';

interface Props { convId: string }

export function FileTree({ convId }: Props) {
  const tree = useFileExplorerStore(s => s.treesByConv[convId]);
  const loadDir = useFileExplorerStore(s => s.loadDir);
  const toggleExpand = useFileExplorerStore(s => s.toggleExpand);
  const setShowHidden = useFileExplorerStore(s => s.setShowHidden);
  const setSearch = useFileExplorerStore(s => s.setSearch);
  const refresh = useFileExplorerStore(s => s.refresh);

  useEffect(() => {
    if (!tree?.rootLoaded) void loadDir(convId, '');
  }, [convId, tree?.rootLoaded, loadDir]);

  // Auto-expand .artifacts when it appears in the root listing
  useEffect(() => {
    if (!tree?.rootLoaded) return;
    const hasArtifacts = tree.rootEntries.some(e => e.name === '.artifacts' && e.kind === 'dir');
    if (hasArtifacts && !tree.expanded.has('.artifacts')) {
      void toggleExpand(convId, '.artifacts');
    }
  }, [tree?.rootLoaded, tree?.rootEntries, tree?.expanded, convId, toggleExpand]);

  const showHidden = tree?.showHidden ?? false;
  const search = tree?.search ?? '';
  const rootEntries = tree?.rootEntries ?? [];
  const rootLoading = tree?.loadingPaths.has('') ?? false;
  const searchTerm = search.trim().toLowerCase();
  const searchActive = searchTerm.length > 0;

  return (
    <div className="flex flex-col h-full bg-surface-soft/30">
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-hairline-soft/60">
        <div className="flex items-center gap-1 flex-1 bg-ink/5 rounded px-1.5 py-0.5">
          <Search className="w-3 h-3 text-ink/35 flex-shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(convId, e.target.value)}
            placeholder="Search files…"
            className="flex-1 bg-transparent text-[12px] font-mono text-ink placeholder:text-ink/35 outline-none min-w-0"
          />
        </div>
        <button
          onClick={() => void setShowHidden(convId, !showHidden)}
          title={showHidden ? 'Hide dotfiles' : 'Show dotfiles'}
          aria-label={showHidden ? 'Hide dotfiles' : 'Show dotfiles'}
          className={`p-1 rounded transition-colors cursor-pointer ${showHidden ? 'text-sky-400/80 hover:text-sky-400' : 'text-ink/35 hover:text-ink/65'}`}
        >
          {showHidden ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
        </button>
        <button
          onClick={() => refresh(convId)}
          aria-label="Refresh tree"
          className="p-1 rounded text-ink/35 hover:text-ink/65 cursor-pointer transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${rootLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-auto py-1">
        {rootLoading && rootEntries.length === 0 && (
          <p className="px-4 py-2 text-[12px] font-mono text-ink/35">Loading…</p>
        )}
        {!rootLoading && rootEntries.length === 0 && (
          <p className="px-4 py-2 text-[12px] font-mono text-ink/35">No files</p>
        )}
        {rootEntries.map(entry => (
          <FileTreeNode
            key={entry.name}
            convId={convId}
            parentPath=""
            entry={entry}
            depth={0}
            searchActive={searchActive}
            searchTerm={searchTerm}
          />
        ))}
      </div>
    </div>
  );
}
