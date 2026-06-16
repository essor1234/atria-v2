import { useMemo, useState } from 'react';
import {
  ChevronRight, ChevronDown,
  Folder, FolderOpen,
  FileText, Code2, Image, Table2, Braces, FileType2,
  BookOpen, Database, Archive, Globe, Sheet,
  File as FileIcon,
  FilePlus, FolderPlus, MoreHorizontal,
} from 'lucide-react';
import { useFileExplorerStore } from '../../stores/fileExplorer';
import { useViewerTabsStore } from '../../stores/viewerTabs';
import { fsScopeKey, type FsEntry, type FsScope } from '../../types';
import { PendingRow } from './tree/PendingRow';
import { NodeContextMenu, type MenuItem } from './tree/NodeContextMenu';
import { DeleteConfirmDialog } from './tree/DeleteConfirmDialog';

interface Props {
  convId: string;
  scope: FsScope;
  parentPath: string;
  entry: FsEntry;
  depth: number;
  searchActive: boolean;
  searchTerm: string;
}

function fileIcon(ext: string) {
  const e = ext.toLowerCase();
  if (['.md', '.mdx', '.txt', '.rst', '.org'].includes(e)) return { Icon: FileText, color: 'text-amber-400/80' };
  if (['.py'].includes(e)) return { Icon: Code2, color: 'text-blue-400/80' };
  if (['.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs'].includes(e)) return { Icon: Code2, color: 'text-yellow-400/80' };
  if (['.go', '.rs', '.rb', '.java', '.cpp', '.c', '.h', '.cs', '.php', '.swift', '.kt'].includes(e))
    return { Icon: Code2, color: 'text-emerald-400/80' };
  if (['.json', '.yaml', '.yml', '.toml', '.ini', '.env'].includes(e)) return { Icon: Braces, color: 'text-orange-400/80' };
  if (['.csv', '.tsv'].includes(e)) return { Icon: Table2, color: 'text-purple-400/80' };
  if (['.xlsx', '.xls', '.ods'].includes(e)) return { Icon: Sheet, color: 'text-green-400/80' };
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'].includes(e))
    return { Icon: Image, color: 'text-pink-400/80' };
  if (['.pdf'].includes(e)) return { Icon: FileType2, color: 'text-red-400/80' };
  if (['.ipynb'].includes(e)) return { Icon: BookOpen, color: 'text-violet-400/80' };
  if (['.db', '.duckdb', '.sqlite', '.sqlite3'].includes(e)) return { Icon: Database, color: 'text-cyan-400/80' };
  if (['.html', '.htm'].includes(e)) return { Icon: Globe, color: 'text-sky-400/80' };
  if (['.zip', '.tar', '.gz', '.rar', '.7z'].includes(e)) return { Icon: Archive, color: 'text-ink/50' };
  return { Icon: FileIcon, color: 'text-ink/45' };
}

export function FileTreeNode({ convId, scope, parentPath, entry, depth, searchActive, searchTerm }: Props) {
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  const key = useMemo(() => fsScopeKey(scope), [scope]);

  const isExpanded = useFileExplorerStore(s => s.treesByScope[key]?.expanded.has(fullPath) ?? false);
  const children = useFileExplorerStore(s => s.treesByScope[key]?.childrenByPath[fullPath]);
  const loading = useFileExplorerStore(s => s.treesByScope[key]?.loadingPaths.has(fullPath) ?? false);
  const pendingEntry = useFileExplorerStore(s => s.treesByScope[key]?.pendingEntry ?? null);
  const renamingPath = useFileExplorerStore(s => s.treesByScope[key]?.renamingPath ?? null);
  const selectedPath = useFileExplorerStore(s => s.treesByScope[key]?.selectedPath ?? null);

  const tabId = scope.kind === 'module' ? `module:${scope.name}:${fullPath}` : fullPath;
  const activeTabId = useViewerTabsStore(s => s.tabsByConv[convId]?.activeId ?? null);
  const toggleExpand = useFileExplorerStore(s => s.toggleExpand);
  const openTab = useViewerTabsStore(s => s.openTab);
  const openModuleFileTab = useViewerTabsStore(s => s.openModuleFileTab);
  const select = useFileExplorerStore(s => s.select);
  const beginCreate = useFileExplorerStore(s => s.beginCreate);
  const beginRename = useFileExplorerStore(s => s.beginRename);
  const cancelRename = useFileExplorerStore(s => s.cancelRename);
  const confirmRename = useFileExplorerStore(s => s.confirmRename);
  const cancelPending = useFileExplorerStore(s => s.cancelPending);
  const confirmPending = useFileExplorerStore(s => s.confirmPending);
  const removePath = useFileExplorerStore(s => s.removePath);

  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);

  if (searchActive && entry.kind === 'file' && !entry.name.toLowerCase().includes(searchTerm)) {
    return null;
  }

  const canMutate = scope.kind === 'module' && !(entry.name === 'SKILL.md' && parentPath === '');
  const isRenaming = renamingPath === fullPath;
  const isSelected = selectedPath === fullPath;

  const handleClick = () => {
    select(scope, fullPath);
    if (entry.kind === 'dir') {
      void toggleExpand(scope, fullPath);
    } else if (scope.kind === 'module') {
      openModuleFileTab(convId, scope.name, fullPath);
    } else {
      openTab(convId, fullPath);
    }
  };

  const onCreateInside = (kind: 'file' | 'dir') => {
    void beginCreate(scope, fullPath, kind);
  };

  const buildMenu = (): Array<MenuItem | 'divider'> => {
    const items: Array<MenuItem | 'divider'> = [];
    if (entry.kind === 'dir') {
      items.push({ label: 'New File', onSelect: () => onCreateInside('file') });
      items.push({ label: 'New Folder', onSelect: () => onCreateInside('dir') });
      items.push('divider');
    } else {
      items.push({ label: 'Open', onSelect: handleClick });
      items.push('divider');
    }
    items.push({
      label: 'Rename',
      shortcut: 'F2',
      onSelect: () => beginRename(scope, fullPath),
      disabled: !canMutate,
    });
    items.push({
      label: 'Delete',
      shortcut: '⌫',
      onSelect: () => setConfirmDel(true),
      danger: true,
      disabled: !canMutate,
    });
    return items;
  };

  const isActive = activeTabId === tabId;
  const Chevron = isExpanded ? ChevronDown : ChevronRight;
  const FolderGlyph = isExpanded ? FolderOpen : Folder;
  const { Icon: FileGlyph, color: fileColor } = entry.kind === 'file' ? fileIcon(entry.ext) : { Icon: FileIcon, color: '' };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (isRenaming) return;
    if (e.key === 'Enter') { e.preventDefault(); handleClick(); return; }
    if (e.key === 'F2' && canMutate) { e.preventDefault(); beginRename(scope, fullPath); return; }
    if ((e.key === 'Delete' || e.key === 'Backspace') && canMutate) {
      e.preventDefault();
      setConfirmDel(true);
      return;
    }
    if (entry.kind === 'dir') {
      if (e.key === 'ArrowRight' && !isExpanded) { e.preventDefault(); void toggleExpand(scope, fullPath); }
      else if (e.key === 'ArrowLeft' && isExpanded) { e.preventDefault(); void toggleExpand(scope, fullPath); }
    }
  };

  return (
    <>
      {isRenaming ? (
        <PendingRow
          depth={depth}
          kind={entry.kind}
          initial={entry.name}
          selectExtension={entry.kind === 'file'}
          onConfirm={(name) => confirmRename(scope, name)}
          onCancel={() => cancelRename(scope)}
        />
      ) : (
        <div
          onClick={handleClick}
          onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY }); }}
          onKeyDown={onKeyDown}
          style={{ paddingLeft: 6 + depth * 14 }}
          className={`group flex items-center gap-1.5 pr-1 py-[3px] cursor-pointer transition-colors text-[12.5px] font-mono select-none ${
            isActive
              ? 'bg-sky-500/15 text-ink'
              : isSelected
                ? 'bg-ink/10 text-ink/90'
                : 'text-ink/75 hover:bg-ink/5 hover:text-ink/90'
          }`}
          role="treeitem"
          aria-selected={isSelected}
          aria-expanded={entry.kind === 'dir' ? isExpanded : undefined}
          tabIndex={0}
        >
          {entry.kind === 'dir' ? (
            <Chevron className="w-3 h-3 flex-shrink-0 text-ink/35" />
          ) : (
            <span className="w-3 h-3 flex-shrink-0" />
          )}

          {entry.kind === 'dir' ? (
            <FolderGlyph className={`w-3.5 h-3.5 flex-shrink-0 ${isExpanded ? 'text-sky-400/90' : 'text-sky-400/70'}`} />
          ) : (
            <FileGlyph className={`w-3.5 h-3.5 flex-shrink-0 ${fileColor}`} />
          )}

          <span className="truncate leading-tight flex-1">{entry.name}</span>

          {loading && <span className="text-[11px] text-ink/35 animate-pulse">…</span>}

          {/* Hover/focus row actions */}
          {!loading && canMutate && (
            <span className="hidden group-hover:flex group-focus-within:flex items-center gap-0.5 flex-shrink-0">
              {entry.kind === 'dir' && (
                <>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onCreateInside('file'); }}
                    aria-label={`New file in ${entry.name}`}
                    title="New file"
                    className="p-0.5 rounded text-ink/45 hover:text-ink/90 hover:bg-ink/5 cursor-pointer"
                  >
                    <FilePlus className="w-3 h-3" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onCreateInside('dir'); }}
                    aria-label={`New folder in ${entry.name}`}
                    title="New folder"
                    className="p-0.5 rounded text-ink/45 hover:text-ink/90 hover:bg-ink/5 cursor-pointer"
                  >
                    <FolderPlus className="w-3 h-3" />
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); const r = (e.target as HTMLElement).getBoundingClientRect(); setMenu({ x: r.left, y: r.bottom + 2 }); }}
                aria-label={`Actions for ${entry.name}`}
                title="More actions"
                className="p-0.5 rounded text-ink/45 hover:text-ink/90 hover:bg-ink/5 cursor-pointer"
              >
                <MoreHorizontal className="w-3 h-3" />
              </button>
            </span>
          )}
        </div>
      )}

      {entry.kind === 'dir' && isExpanded && children?.map(child => (
        <FileTreeNode
          key={`${fullPath}/${child.name}`}
          convId={convId}
          scope={scope}
          parentPath={fullPath}
          entry={child}
          depth={depth + 1}
          searchActive={searchActive}
          searchTerm={searchTerm}
        />
      ))}

      {/* Pending child create for this dir */}
      {entry.kind === 'dir' && isExpanded && pendingEntry && pendingEntry.parentPath === fullPath && (
        <PendingRow
          depth={depth + 1}
          kind={pendingEntry.kind}
          placeholder={pendingEntry.kind === 'file' ? 'untitled.txt' : 'new-folder'}
          onConfirm={(name) => confirmPending(scope, name)}
          onCancel={() => cancelPending(scope)}
        />
      )}

      {menu && (
        <NodeContextMenu x={menu.x} y={menu.y} items={buildMenu()} onClose={() => setMenu(null)} />
      )}

      <DeleteConfirmDialog
        open={confirmDel}
        title={`Delete ${entry.kind === 'dir' ? 'folder' : 'file'}`}
        message={
          entry.kind === 'dir'
            ? `Delete folder "${entry.name}" and all of its contents? This cannot be undone.`
            : `Delete "${entry.name}"? This cannot be undone.`
        }
        onConfirm={() => removePath(scope, fullPath, entry.kind)}
        onClose={() => setConfirmDel(false)}
      />
    </>
  );
}
