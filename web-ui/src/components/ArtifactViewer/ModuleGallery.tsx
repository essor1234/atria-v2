import { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, Search, Boxes } from 'lucide-react';
import { useModulesStore } from '../../stores/modules';
import { useViewerTabsStore } from '../../stores/viewerTabs';
import { NewModuleSheet } from './NewModuleSheet';

interface Props {
  convId: string;
}

function firstSummaryLine(skill_md: string): string {
  let inFrontmatter = false;
  let seenFence = false;
  for (const raw of skill_md.split('\n')) {
    const line = raw.trim();
    // Skip a leading YAML frontmatter block (--- … ---) so we don't grab the fence.
    if (line === '---') {
      if (!seenFence) {
        seenFence = true;
        inFrontmatter = true;
        continue;
      }
      inFrontmatter = false;
      continue;
    }
    if (inFrontmatter) continue;
    if (!line) continue;
    if (line.startsWith('#')) continue;
    return line.length > 90 ? line.slice(0, 87) + '…' : line;
  }
  return '';
}

function relativeTime(mtimeSec: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - mtimeSec);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function ModuleGallery({ convId }: Props) {
  const { modules, loading, error, refresh, remove } = useModulesStore();
  const openModuleTab = useViewerTabsStore(s => s.openModuleTab);
  const [query, setQuery] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? modules.filter(
          m => m.name.toLowerCase().includes(q) || m.skill_md.toLowerCase().includes(q),
        )
      : modules.slice();
    list.sort((a, b) => b.mtime - a.mtime);
    return list;
  }, [modules, query]);

  const onDelete = async (name: string) => {
    if (!window.confirm(`Delete module "${name}"? This removes the folder.`)) return;
    await remove(name);
  };

  return (
    <div className="relative flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-hairline-soft/60 flex-shrink-0">
        <span className="text-[11px] uppercase tracking-wide text-ink/50">Modules</span>
        <span className="text-[10px] text-ink/35">
          {filtered.length}
          {query && filtered.length !== modules.length ? ` / ${modules.length}` : ''}
        </span>
        <div className="flex-1" />
        <button
          onClick={() => setSheetOpen(true)}
          aria-label="New module"
          title="New module"
          className="p-1 rounded text-ink/55 hover:text-ink hover:bg-surface-soft cursor-pointer transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Search */}
      {modules.length > 0 && (
        <div className="px-2 py-1.5 border-b border-hairline-soft/60 flex-shrink-0">
          <div className="relative">
            <Search className="absolute left-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-ink/35" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search modules…"
              className="w-full pl-6 pr-2 py-1 text-xs rounded bg-canvas border border-hairline-soft"
            />
          </div>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {loading && modules.length === 0 && (
          <div className="px-2 py-3 text-[11px] text-ink/40">Loading…</div>
        )}
        {error && <div className="px-2 py-3 text-[11px] text-semantic-danger">{error}</div>}

        {!loading && modules.length === 0 && (
          <div className="flex flex-col items-center justify-center text-center px-4 py-8 gap-2 select-none">
            <div className="w-10 h-10 rounded-full border border-hairline-soft flex items-center justify-center text-ink/25">
              <Boxes className="w-4 h-4" />
            </div>
            <div className="text-[12px] text-ink/55">No modules yet</div>
            <div className="text-[11px] text-ink/40 leading-snug max-w-[180px]">
              Modules add reusable skill prompts and python helpers to the agent.
            </div>
            <button
              onClick={() => setSheetOpen(true)}
              className="mt-1 inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded bg-sky-500/90 text-white hover:bg-sky-500 active:scale-[0.98] whitespace-nowrap cursor-pointer transition-colors duration-fast"
            >
              <Plus className="w-3 h-3" /> Create one
            </button>
          </div>
        )}

        {modules.length > 0 && filtered.length === 0 && (
          <div className="px-2 py-4 text-center text-[11px] text-ink/40">
            No matches for “{query}”.
          </div>
        )}

        <div className="px-1.5 py-1.5 space-y-1">
          {filtered.map(m => {
            const summary = m.description?.trim() || firstSummaryLine(m.skill_md);
            const hasBody = m.skill_md.trim().length > 0 || m.files.length > 1;
            return (
              <div
                key={m.name}
                onClick={() => openModuleTab(convId, m.name)}
                className="group relative rounded-md border border-hairline-soft/60 bg-surface hover:border-hairline-soft hover:bg-surface-soft/40 cursor-pointer transition-colors px-2.5 py-2"
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      hasBody ? 'bg-emerald-500' : 'bg-ink/25'
                    }`}
                    title={hasBody ? 'Active' : 'Draft (empty)'}
                  />
                  <div className="font-medium text-[12.5px] truncate">{m.name}</div>
                  <div className="flex-1" />
                  <span className="text-[10px] text-ink/40 flex-shrink-0">
                    {relativeTime(m.mtime)}
                  </span>
                  <button
                    onClick={e => {
                      e.stopPropagation();
                      onDelete(m.name);
                    }}
                    aria-label={`Delete ${m.name}`}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-ink/45 hover:text-semantic-danger hover:bg-surface-soft cursor-pointer transition"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
                {summary && (
                  <div className="mt-0.5 ml-3 text-[11px] text-ink/55 leading-snug line-clamp-2">
                    {summary}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <NewModuleSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onCreated={name => openModuleTab(convId, name)}
      />
    </div>
  );
}
