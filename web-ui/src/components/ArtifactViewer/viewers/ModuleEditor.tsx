import { useEffect, useMemo, useState } from 'react';
import { Boxes, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useModulesStore } from '../../../stores/modules';
import { useFileExplorerStore } from '../../../stores/fileExplorer';
import { FileTree } from '../FileTree';
import { DeleteConfirmDialog } from '../tree/DeleteConfirmDialog';
import type { FsScope } from '../../../types';

interface Props {
  convId: string;
  name: string;
}

export function ModuleEditor({ convId, name }: Props) {
  const { modules, refresh, remove } = useModulesStore();
  const scope = useMemo<FsScope>(() => ({ kind: 'module', name }), [name]);
  const refreshTree = useFileExplorerStore(s => s.refresh);
  const found = modules.find(m => m.name === name);
  const [confirmDel, setConfirmDel] = useState(false);

  useEffect(() => {
    if (!found) refresh();
  }, [found, refresh]);

  useEffect(() => {
    refreshTree(scope);
  }, [scope, refreshTree, found?.mtime]);

  if (!found) {
    return <div className="p-4 text-ink/50 text-sm">Loading module {name}…</div>;
  }

  return (
    <div className="flex flex-col h-full min-h-0 bg-canvas">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-hairline-soft/60 flex-shrink-0">
        <Boxes className="w-4 h-4 text-sky-400/80" />
        <span className="font-medium text-[13px]">{name}</span>
        <span className="text-[10.5px] font-mono text-ink/40">
          {found.files.length} file{found.files.length === 1 ? '' : 's'}
        </span>
        <div className="flex-1" />
        <button
          onClick={() => setConfirmDel(true)}
          className="p-1 rounded text-ink/45 hover:text-semantic-danger hover:bg-surface-soft cursor-pointer transition-colors"
          aria-label={`Delete module ${name}`}
          title="Delete module"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      <DeleteConfirmDialog
        open={confirmDel}
        title="Delete module"
        message={`Delete module "${name}" and all of its files? This cannot be undone.`}
        onConfirm={() => remove(name)}
        onClose={() => setConfirmDel(false)}
      />

      <div className="flex flex-1 min-h-0">
        <div className="w-[220px] flex-shrink-0 border-r border-hairline-soft/60">
          <FileTree
            convId={convId}
            scope={scope}
            showHiddenToggle={false}
            autoExpand={['scripts', 'templates']}
          />
        </div>
        <div className="flex-1 min-w-0 overflow-auto">
          {found.skill_md.trim() ? (
            <div className="prose prose-invert max-w-none p-5 text-sm">
              <ReactMarkdown>{found.skill_md}</ReactMarkdown>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-1 select-none">
              <Boxes className="w-5 h-5 text-ink/25" />
              <div className="text-[12px] text-ink/45">SKILL.md is empty</div>
              <div className="text-[11px] text-ink/35">Open it from the tree to add content.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
