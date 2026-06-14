import {
  ChevronRight, ChevronDown,
  Folder, FolderOpen,
  FileText, Code2, Image, Table2, Braces, FileType2,
  BookOpen, Database, Archive, Globe, Sheet,
  File as FileIcon,
} from 'lucide-react';
import { useFileExplorerStore } from '../../stores/fileExplorer';
import { useViewerTabsStore } from '../../stores/viewerTabs';
import type { FsEntry } from '../../types';

interface Props {
  convId: string;
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

export function FileTreeNode({ convId, parentPath, entry, depth, searchActive, searchTerm }: Props) {
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;

  const isExpanded = useFileExplorerStore(s => s.treesByConv[convId]?.expanded.has(fullPath) ?? false);
  const children = useFileExplorerStore(s => s.treesByConv[convId]?.childrenByPath[fullPath]);
  const loading = useFileExplorerStore(s => s.treesByConv[convId]?.loadingPaths.has(fullPath) ?? false);
  const activeTabId = useViewerTabsStore(s => s.tabsByConv[convId]?.activeId ?? null);
  const toggleExpand = useFileExplorerStore(s => s.toggleExpand);
  const openTab = useViewerTabsStore(s => s.openTab);

  if (searchActive && entry.kind === 'file' && !entry.name.toLowerCase().includes(searchTerm)) {
    return null;
  }

  const handleClick = () => {
    if (entry.kind === 'dir') void toggleExpand(convId, fullPath);
    else openTab(convId, fullPath);
  };

  const isActive = activeTabId === fullPath;
  const Chevron = isExpanded ? ChevronDown : ChevronRight;
  const FolderGlyph = isExpanded ? FolderOpen : Folder;
  const { Icon: FileGlyph, color: fileColor } = entry.kind === 'file' ? fileIcon(entry.ext) : { Icon: FileIcon, color: '' };

  return (
    <>
      <div
        onClick={handleClick}
        style={{ paddingLeft: 6 + depth * 14 }}
        className={`group flex items-center gap-1.5 pr-2 py-[3px] cursor-pointer transition-colors text-[12.5px] font-mono select-none ${
          isActive
            ? 'bg-sky-500/15 text-ink'
            : 'text-ink/75 hover:bg-ink/5 hover:text-ink/90'
        }`}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') handleClick(); }}
      >
        {/* Expand chevron (dirs) or spacer (files) */}
        {entry.kind === 'dir' ? (
          <Chevron className="w-3 h-3 flex-shrink-0 text-ink/35" />
        ) : (
          <span className="w-3 h-3 flex-shrink-0" />
        )}

        {/* Icon */}
        {entry.kind === 'dir' ? (
          <FolderGlyph className={`w-3.5 h-3.5 flex-shrink-0 ${isExpanded ? 'text-sky-400/90' : 'text-sky-400/70'}`} />
        ) : (
          <FileGlyph className={`w-3.5 h-3.5 flex-shrink-0 ${fileColor}`} />
        )}

        <span className="truncate leading-tight">{entry.name}</span>
        {loading && <span className="ml-auto text-[11px] text-ink/35 animate-pulse">…</span>}
      </div>

      {entry.kind === 'dir' && isExpanded && children?.map(child => (
        <FileTreeNode
          key={`${fullPath}/${child.name}`}
          convId={convId}
          parentPath={fullPath}
          entry={child}
          depth={depth + 1}
          searchActive={searchActive}
          searchTerm={searchTerm}
        />
      ))}
    </>
  );
}
