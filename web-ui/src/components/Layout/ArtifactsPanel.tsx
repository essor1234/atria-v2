import { useEffect } from 'react';
import {
  FileText,
  Code2,
  Image as ImageIcon,
  BarChart3,
  Paperclip,
  Globe,
  Pin,
  X,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react';
import { useArtifactsStore } from '../../stores/artifacts';
import { useChatStore } from '../../stores/chat';
import { useViewerTabsStore } from '../../stores/viewerTabs';
import type { Artifact } from '../../types';

// ── Type icon + color ─────────────────────────────────────────────────────────

const TYPE_META: Record<string, { Icon: LucideIcon; color: string; label: string }> = {
  report: { Icon: FileText,  color: 'text-blue-400',   label: 'Report' },
  code:   { Icon: Code2,     color: 'text-accent-magenta', label: 'Code'   },
  image:  { Icon: ImageIcon, color: 'text-pink-400',   label: 'Image'  },
  data:   { Icon: BarChart3, color: 'text-green-400',  label: 'Data'   },
  web:    { Icon: Globe,     color: 'text-orange-400', label: 'Web'    },
  file:   { Icon: Paperclip, color: 'text-text-400',   label: 'File'   },
};

function getFilename(ref: string | null): string {
  if (!ref) return 'Untitled';
  return ref.split('/').pop() ?? ref;
}

function ArtifactRow({
  artifact,
  conversationId,
}: {
  artifact: Artifact;
  conversationId: string;
}) {
  const { togglePin, deleteArtifact } = useArtifactsStore();
  const openTab = useViewerTabsStore(s => s.openTab);
  const meta = TYPE_META[artifact.type] ?? TYPE_META.file;
  const TypeIcon = meta.Icon;
  const name = artifact.title || getFilename(artifact.payload_ref);

  const openable = !!artifact.payload_ref;

  const handleOpen = () => {
    if (!artifact.payload_ref) return;
    openTab(conversationId, artifact.payload_ref);
  };

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!openable) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleOpen();
    }
  };

  return (
    <div
      role={openable ? 'button' : undefined}
      tabIndex={openable ? 0 : -1}
      onClick={openable ? handleOpen : undefined}
      onKeyDown={onKey}
      aria-label={openable ? `Open ${name}` : undefined}
      className={`group flex items-center gap-1.5 px-2 py-1 hover:bg-bg-200/40 rounded transition-colors ${
        openable ? 'cursor-pointer' : ''
      }`}
    >
      <TypeIcon className={`w-3.5 h-3.5 flex-shrink-0 ${meta.color}`} aria-label={meta.label} />

      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-text-200 font-mono truncate leading-tight" title={artifact.payload_ref ?? ''}>
          {name}
        </p>
        {artifact.payload_ref && (
          <p className="text-[10px] text-text-500 font-mono truncate leading-none mt-0.5">
            {artifact.payload_ref.replace(/^.*\/([^/]+\/[^/]+)$/, '$1')}
          </p>
        )}
      </div>

      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={e => {
            e.stopPropagation();
            togglePin(conversationId, artifact.id, artifact.pinned);
          }}
          className={`p-0.5 rounded cursor-pointer transition-colors ${artifact.pinned ? 'text-amber-400' : 'text-text-500 hover:text-amber-400'}`}
          title={artifact.pinned ? 'Unpin' : 'Pin'}
        >
          <Pin className={`w-3 h-3 ${artifact.pinned ? 'fill-current' : ''}`} />
        </button>
        <button
          onClick={e => {
            e.stopPropagation();
            deleteArtifact(conversationId, artifact.id);
          }}
          className="p-0.5 rounded cursor-pointer text-text-500 hover:text-semantic-danger transition-colors"
          title="Remove"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {artifact.pinned && (
        <Pin className="w-2.5 h-2.5 text-amber-400 flex-shrink-0 opacity-60 fill-current" />
      )}
    </div>
  );
}

export function ArtifactsPanel() {
  const currentSessionId = useChatStore(s => s.currentSessionId);
  const { artifacts, loading, scanning, scanArtifacts } = useArtifactsStore();

  // Auto-scan the conversation folder whenever the active session changes.
  // scanArtifacts walks the working directory and upserts new files into DB.
  useEffect(() => {
    if (!currentSessionId || isNaN(parseInt(currentSessionId, 10))) return;
    scanArtifacts(currentSessionId).catch(() => {});
  }, [currentSessionId]);

  if (!currentSessionId) {
    return null;
  }

  const convInt = parseInt(currentSessionId, 10);
  if (isNaN(convInt)) return null;

  const items = artifacts[currentSessionId] ?? [];
  const isLoading = loading[currentSessionId] ?? false;

  return (
    <div className="border-t border-border-300/10 flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5">
        <span className="text-[11px] font-mono font-semibold text-text-400 uppercase tracking-wider">
          Artifacts
          {items.length > 0 && (
            <span className="ml-1.5 text-text-500 font-normal normal-case">{items.length}</span>
          )}
        </span>
        <button
          onClick={() => scanArtifacts(currentSessionId)}
          disabled={scanning}
          title="Scan working directory"
          className="p-0.5 rounded text-text-500 hover:text-text-200 disabled:opacity-40 transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${scanning ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Content */}
      <div className="overflow-y-auto max-h-48 pb-1">
        {isLoading && items.length === 0 && (
          <p className="text-[11px] text-text-500 font-mono px-3 py-1">Loading…</p>
        )}
        {!isLoading && items.length === 0 && (
          <div className="px-3 py-2 text-center">
            <p className="text-[11px] text-text-500 font-mono">No artifacts yet</p>
            <button
              onClick={() => scanArtifacts(currentSessionId)}
              className="text-[11px] text-accent-main-100 hover:text-accent-main-100/80 font-mono mt-1"
            >
              <span className="inline-flex items-center gap-1">Scan workspace <RefreshCw className="w-3 h-3" /></span>
            </button>
          </div>
        )}
        {items.map(artifact => (
          <ArtifactRow
            key={artifact.id}
            artifact={artifact}
            conversationId={currentSessionId}
          />
        ))}
      </div>
    </div>
  );
}
