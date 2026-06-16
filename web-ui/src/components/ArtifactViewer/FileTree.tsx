import { useEffect, useMemo, useState } from 'react';
import { Search, Eye, EyeOff, RefreshCw, FilePlus, FolderPlus } from 'lucide-react';
import { useFileExplorerStore } from '../../stores/fileExplorer';
import { FileTreeNode } from './FileTreeNode';
import { PendingRow } from './tree/PendingRow';
import { NodeContextMenu, type MenuItem } from './tree/NodeContextMenu';
import { fsScopeKey, type FsScope } from '../../types';

interface Props {
  /** Conversation id (used to key viewer tabs). */
  convId: string;
  /** Filesystem scope: either the conversation's working dir, or a module folder. */
  scope: FsScope;
  /** Show the dotfile toggle (only meaningful for conv scope). */
  showHiddenToggle?: boolean;
  /** Auto-expand certain top-level folders when they appear. */
  autoExpand?: string[];
}

export function FileTree({ convId, scope, showHiddenToggle = true, autoExpand }: Props) {
  const key = useMemo(() => fsScopeKey(scope), [scope]);
  const tree = useFileExplorerStore(s => s.treesByScope[key]);
  const loadDir = useFileExplorerStore(s => s.loadDir);
  const toggleExpand = useFileExplorerStore(s => s.toggleExpand);
  const setShowHidden = useFileExplorerStore(s => s.setShowHidden);
  const setSearch = useFileExplorerStore(s => s.setSearch);
  const refresh = useFileExplorerStore(s => s.refresh);
  const beginCreate = useFileExplorerStore(s => s.beginCreate);
  const cancelPending = useFileExplorerStore(s => s.cancelPending);
  const confirmPending = useFileExplorerStore(s => s.confirmPending);

  const [rootMenu, setRootMenu] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!tree?.rootLoaded) void loadDir(scope, '');
  }, [key, tree?.rootLoaded, loadDir, scope]);

  useEffect(() => {
    if (!tree?.rootLoaded || !autoExpand?.length) return;
    for (const name of autoExpand) {
      const has = tree.rootEntries.some(e => e.name === name && e.kind === 'dir');
      if (has && !tree.expanded.has(name)) {
        void toggleExpand(scope, name);
      }
    }
  }, [tree?.rootLoaded, tree?.rootEntries, tree?.expanded, scope, toggleExpand, autoExpand]);

  const showHidden = tree?.showHidden ?? false;
  const search = tree?.search ?? '';
  const rootEntries = tree?.rootEntries ?? [];
  const rootLoading = tree?.loadingPaths.has('') ?? false;
  const pendingEntry = tree?.pendingEntry ?? null;
  const searchTerm = search.trim().toLowerCase();
  const searchActive = searchTerm.length > 0;

  const canMutate = scope.kind === 'module';

  const buildRootMenu = (): Array<MenuItem | 'divider'> => ([
    { label: 'New File', onSelect: () => beginCreate(scope, '', 'file') },
    { label: 'New Folder', onSelect: () => beginCreate(scope, '', 'dir') },
  ]);

  // Tree-focused keyboard shortcuts (Cmd/Ctrl+N → new file at root)
  const onContainerKeyDown = (e: React.KeyboardEvent) => {
    if (!canMutate) return;
    const target = e.target as HTMLElement;
    if (target.tagName === 'INPUT') return;
    const meta = e.metaKey || e.ctrlKey;
    if (meta && !e.shiftKey && (e.key === 'n' || e.key === 'N')) {
      e.preventDefault();
      void beginCreate(scope, '', 'file');
    } else if (meta && e.shiftKey && (e.key === 'n' || e.key === 'N')) {
      e.preventDefault();
      void beginCreate(scope, '', 'dir');
    }
  };

  return (
    <div
      className="flex flex-col h-full bg-surface-soft/30"
      onKeyDown={onContainerKeyDown}
    >
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-hairline-soft/60">
        <div className="flex items-center gap-1 flex-1 bg-ink/5 rounded px-1.5 py-0.5">
          <Search className="w-3 h-3 text-ink/35 flex-shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(scope, e.target.value)}
            placeholder="Search files…"
            className="flex-1 bg-transparent text-[12px] font-mono text-ink placeholder:text-ink/35 outline-none min-w-0"
          />
        </div>
        {canMutate && (
          <>
            <button
              onClick={() => void beginCreate(scope, '', 'file')}
              title="New file (⌘N)"
              aria-label="New file"
              className="p-1 rounded text-ink/45 hover:text-ink/85 hover:bg-ink/5 cursor-pointer transition-colors"
            >
              <FilePlus className="w-3 h-3" />
            </button>
            <button
              onClick={() => void beginCreate(scope, '', 'dir')}
              title="New folder (⌘⇧N)"
              aria-label="New folder"
              className="p-1 rounded text-ink/45 hover:text-ink/85 hover:bg-ink/5 cursor-pointer transition-colors"
            >
              <FolderPlus className="w-3 h-3" />
            </button>
          </>
        )}
        {showHiddenToggle && (
          <button
            onClick={() => void setShowHidden(scope, !showHidden)}
            title={showHidden ? 'Hide dotfiles' : 'Show dotfiles'}
            aria-label={showHidden ? 'Hide dotfiles' : 'Show dotfiles'}
            className={`p-1 rounded transition-colors cursor-pointer ${showHidden ? 'text-sky-400/80 hover:text-sky-400' : 'text-ink/35 hover:text-ink/65'}`}
          >
            {showHidden ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
          </button>
        )}
        <button
          onClick={() => refresh(scope)}
          aria-label="Refresh tree"
          title="Refresh"
          className="p-1 rounded text-ink/35 hover:text-ink/65 cursor-pointer transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${rootLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Tree */}
      <div
        className="flex-1 overflow-auto py-1"
        onContextMenu={(e) => {
          if (!canMutate) return;
          // Only fire root menu when the click is on empty space (the container itself).
          if (e.target === e.currentTarget) {
            e.preventDefault();
            setRootMenu({ x: e.clientX, y: e.clientY });
          }
        }}
      >
        {rootLoading && rootEntries.length === 0 && (
          <p className="px-4 py-2 text-[12px] font-mono text-ink/35">Loading…</p>
        )}
        {!rootLoading && rootEntries.length === 0 && !pendingEntry && (
          <p className="px-4 py-2 text-[12px] font-mono text-ink/35">No files</p>
        )}
        {rootEntries.map(entry => (
          <FileTreeNode
            key={entry.name}
            convId={convId}
            scope={scope}
            parentPath=""
            entry={entry}
            depth={0}
            searchActive={searchActive}
            searchTerm={searchTerm}
          />
        ))}
        {/* Root-level pending row */}
        {pendingEntry && pendingEntry.parentPath === '' && (
          <PendingRow
            depth={0}
            kind={pendingEntry.kind}
            placeholder={pendingEntry.kind === 'file' ? 'untitled.txt' : 'new-folder'}
            onConfirm={(name) => confirmPending(scope, name)}
            onCancel={() => cancelPending(scope)}
          />
        )}
      </div>

      {rootMenu && (
        <NodeContextMenu
          x={rootMenu.x}
          y={rootMenu.y}
          items={buildRootMenu()}
          onClose={() => setRootMenu(null)}
        />
      )}
    </div>
  );
}
