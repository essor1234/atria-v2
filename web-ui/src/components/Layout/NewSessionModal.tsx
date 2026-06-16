import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, ChevronRight, Folder, Search, ArrowUp } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useChatStore } from '../../stores/chat';

interface NewSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface DirEntry {
  name: string;
  path: string;
}

const getBreadcrumbs = (absPath: string) => {
  const parts = absPath.split('/').filter(Boolean);
  return parts.map((part, i) => ({
    label: part,
    path: '/' + parts.slice(0, i + 1).join('/'),
  }));
};

export function NewSessionModal({ isOpen, onClose }: NewSessionModalProps) {
  const [currentPath, setCurrentPath] = useState('');
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [directories, setDirectories] = useState<DirEntry[]>([]);
  const [manualPath, setManualPath] = useState('');
  const [showHidden, setShowHidden] = useState(false);
  const [isLoadingDirs, setIsLoadingDirs] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const loadSession = useChatStore(state => state.loadSession);
  const bumpSessionList = useChatStore(state => state.bumpSessionList);

  const fetchDirectory = async (path: string, hidden?: boolean) => {
    setIsLoadingDirs(true);
    setBrowseError(null);
    try {
      const result = await apiClient.browseDirectory(path, hidden ?? showHidden);
      setCurrentPath(result.current_path);
      setParentPath(result.parent_path);
      setDirectories(result.directories);
      setManualPath(result.current_path);
      setFilterText('');
      if (result.error) {
        setBrowseError(result.error);
      }
    } catch (err) {
      setBrowseError('Failed to browse directory');
    } finally {
      setIsLoadingDirs(false);
    }
  };

  // Load home directory on open
  useEffect(() => {
    if (isOpen) {
      fetchDirectory('');
    }
  }, [isOpen]);

  // Refetch when showHidden toggles
  useEffect(() => {
    if (isOpen && currentPath) {
      fetchDirectory(currentPath, showHidden);
    }
  }, [showHidden]);

  const handleManualGo = () => {
    if (manualPath.trim()) {
      fetchDirectory(manualPath.trim());
    }
  };

  const handleSelect = async () => {
    if (!currentPath) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      const result = await apiClient.createSession(currentPath);
      bumpSessionList();
      if (result.session?.id) {
        await loadSession(result.session.id);
      }
      onClose();
    } catch (err) {
      console.error('Failed to create session:', err);
      setCreateError(
        err instanceof Error ? err.message : 'Failed to create session. Please try again.'
      );
    } finally {
      setIsCreating(false);
    }
  };

  if (!isOpen) return null;

  const breadcrumbs = currentPath ? getBreadcrumbs(currentPath) : [];

  const modalContent = (
    <div
      className="fixed inset-0 bg-black/60 z-[99999] flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-modal max-w-lg w-full max-h-[80vh] flex flex-col mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Select Workspace</h2>
          <button
            aria-label="Close dialog"
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-gray-600"
          >
            <X className="w-[18px] h-[18px]" strokeWidth={1.5} />
          </button>
        </div>

        {/* Path input bar */}
        <div className="px-5 pt-4 pb-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleManualGo();
              }}
              placeholder="/path/to/directory"
              className="flex-1 px-3 py-2 text-sm font-mono border border-gray-300 rounded-lg"
            />
            <button
              onClick={handleManualGo}
              disabled={!manualPath.trim()}
              className="px-4 py-2 text-sm font-medium bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-gray-700 border border-gray-300"
            >
              Go
            </button>
          </div>
        </div>

        {/* Breadcrumb bar */}
        <div className="px-5 py-2 flex items-center gap-1 flex-wrap">
          <button
            onClick={() => fetchDirectory('/')}
            className="text-xs font-medium text-amber-600 hover:text-amber-800 hover:underline"
          >
            /
          </button>
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.path} className="flex items-center gap-1">
              <ChevronRight className="w-3 h-3 text-ink/40" strokeWidth={1.5} />
              <button
                onClick={() => fetchDirectory(crumb.path)}
                className={`text-xs font-medium ${
                  i === breadcrumbs.length - 1
                    ? 'text-gray-900'
                    : 'text-amber-600 hover:text-amber-800 hover:underline'
                }`}
              >
                {crumb.label}
              </button>
            </span>
          ))}
          <label className="ml-auto flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(e) => setShowHidden(e.target.checked)}
              className="rounded border-gray-300 text-amber-500"
            />
            Show hidden
          </label>
        </div>

        {/* Directory listing */}
        <div className="flex-1 overflow-y-auto border-t border-gray-100 min-h-0">
          {isLoadingDirs ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-6 h-6 border-2 border-gray-200 border-t-amber-500 rounded-full animate-spin" />
            </div>
          ) : browseError ? (
            <div className="px-5 py-8 text-center">
              <p className="text-sm text-semantic-danger">{browseError}</p>
            </div>
          ) : (
            <div className="py-1">
              {/* Filter input */}
              {directories.length > 0 && (
                <div className="px-5 py-2">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink/40" strokeWidth={1.5} />
                    <input
                      type="text"
                      value={filterText}
                      onChange={(e) => setFilterText(e.target.value)}
                      placeholder="Filter folders..."
                      className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-md"
                    />
                  </div>
                </div>
              )}

              {/* Parent directory row */}
              {parentPath && (
                <button
                  onClick={() => fetchDirectory(parentPath)}
                  className="w-full px-5 py-2.5 flex items-center gap-3 hover:bg-amber-50 text-left"
                >
                  <ArrowUp className="w-4 h-4 text-ink/40 flex-shrink-0" strokeWidth={1.5} />
                  <span className="text-sm text-gray-600">..</span>
                </button>
              )}

              {/* Directory rows */}
              {(() => {
                const filteredDirs = directories.filter(d =>
                  d.name.toLowerCase().includes(filterText.toLowerCase())
                );
                if (directories.length === 0 && !parentPath) {
                  return (
                    <div className="px-5 py-8 text-center">
                      <p className="text-sm text-gray-400">No subdirectories</p>
                    </div>
                  );
                }
                if (directories.length === 0 && parentPath) {
                  return (
                    <div className="px-5 py-6 text-center">
                      <p className="text-sm text-gray-400">No subdirectories</p>
                    </div>
                  );
                }
                if (filteredDirs.length === 0) {
                  return (
                    <div className="px-5 py-6 text-center">
                      <p className="text-sm text-gray-400">No matching folders</p>
                    </div>
                  );
                }
                return filteredDirs.map((dir) => (
                  <button
                    key={dir.path}
                    onClick={() => fetchDirectory(dir.path)}
                    className="w-full px-5 py-2.5 flex items-center gap-3 hover:bg-amber-50 text-left"
                  >
                    <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" strokeWidth={1.5} />
                    <span className="text-sm text-gray-800 truncate">{dir.name}</span>
                  </button>
                ));
              })()}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-gray-200">
          {createError && (
            <p className="text-sm text-semantic-danger mb-3">{createError}</p>
          )}
          <div className="flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-mono text-gray-500 truncate" title={currentPath}>
              {currentPath}
            </p>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium border border-gray-300 bg-white hover:bg-gray-50 rounded-lg text-gray-700"
          >
            Cancel
          </button>
          <button
            onClick={handleSelect}
            disabled={!currentPath || isCreating}
            className="px-4 py-2 text-sm font-medium bg-amber-500 hover:bg-amber-600 disabled:bg-gray-300 disabled:cursor-not-allowed text-white rounded-lg"
          >
            {isCreating ? 'Creating...' : 'Select This Directory'}
          </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
