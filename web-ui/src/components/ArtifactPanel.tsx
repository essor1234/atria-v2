import { useMemo, useState } from 'react';
import { LayoutGrid, Filter, FileText, Trash2 } from 'lucide-react';
import type { Artifact } from '../types';
import { ArtifactThumbnail } from './ArtifactThumbnail';

type ScopeFilter = 'all' | 'conversation' | 'project';
type ViewMode = 'grid' | 'list';

interface ArtifactPanelProps {
  artifacts: Artifact[];
  isLoading?: boolean;
  onDelete?: (artifactId: number) => void;
  onPreview?: (artifact: Artifact) => void;
  className?: string;
}

export function ArtifactPanel({
  artifacts,
  isLoading = false,
  onDelete,
  onPreview,
  className = '',
}: ArtifactPanelProps) {
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  // Filter and search artifacts
  const filteredArtifacts = useMemo(() => {
    return artifacts.filter((artifact) => {
      // Apply scope filter
      if (scopeFilter === 'conversation' && !artifact.conversation_id) return false;
      if (scopeFilter === 'project' && artifact.conversation_id) return false;

      // Apply search filter
      const title = artifact.title?.toLowerCase() || '';
      const query = searchQuery.toLowerCase();
      return title.includes(query);
    });
  }, [artifacts, scopeFilter, searchQuery]);

  const hasBothScopes = artifacts.some((a) => a.conversation_id) &&
    artifacts.some((a) => !a.conversation_id);

  return (
    <div className={`artifact-panel flex flex-col h-full bg-white ${className}`}>
      {/* Header */}
      <div className="flex-shrink-0 border-b border-gray-200 p-4">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Artifacts</h2>

        {/* Search Bar */}
        <div className="mb-4">
          <input
            type="text"
            placeholder="Search artifacts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Controls */}
        <div className="flex items-center justify-between">
          {/* Scope Filter */}
          {hasBothScopes && (
            <div className="flex gap-2">
              <button
                onClick={() => setScopeFilter('all')}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  scopeFilter === 'all'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                All
              </button>
              <button
                onClick={() => setScopeFilter('conversation')}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  scopeFilter === 'conversation'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Conversation
              </button>
              <button
                onClick={() => setScopeFilter('project')}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  scopeFilter === 'project'
                    ? 'bg-purple-100 text-purple-700'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Project
              </button>
            </div>
          )}

          {/* View Mode Toggle */}
          <div className="flex gap-1 ml-auto">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded transition-colors ${
                viewMode === 'grid'
                  ? 'bg-blue-100 text-blue-600'
                  : 'text-gray-400 hover:text-gray-600'
              }`}
              title="Grid view"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded transition-colors ${
                viewMode === 'list'
                  ? 'bg-blue-100 text-blue-600'
                  : 'text-gray-400 hover:text-gray-600'
              }`}
              title="List view"
            >
              <Filter className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center h-full">
            <div className="text-gray-500">
              <div className="inline-block animate-spin">⏳</div>
              <p className="mt-2 text-sm">Loading artifacts...</p>
            </div>
          </div>
        )}

        {!isLoading && filteredArtifacts.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 p-4">
            <FileText className="w-12 h-12 mb-3 text-gray-300" />
            <p className="text-center">
              {artifacts.length === 0
                ? 'No artifacts yet'
                : 'No artifacts match your search'}
            </p>
          </div>
        )}

        {!isLoading && filteredArtifacts.length > 0 && viewMode === 'grid' && (
          <div className="p-4 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-2 lg:grid-cols-3">
            {filteredArtifacts.map((artifact) => (
              <ArtifactThumbnail
                key={artifact.id}
                artifact={artifact}
                onDelete={onDelete}
                onPreview={onPreview}
              />
            ))}
          </div>
        )}

        {!isLoading && filteredArtifacts.length > 0 && viewMode === 'list' && (
          <div className="divide-y divide-gray-200">
            {filteredArtifacts.map((artifact) => (
              <div
                key={artifact.id}
                className="p-4 hover:bg-gray-50 cursor-pointer transition-colors"
                onClick={() => onPreview?.(artifact)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">
                      {artifact.title || 'Untitled'}
                    </h3>
                    <div className="flex gap-2 mt-1">
                      <span
                        className={`inline-block text-xs font-medium px-2 py-1 rounded ${
                          artifact.conversation_id
                            ? 'bg-blue-100 text-blue-700'
                            : 'bg-purple-100 text-purple-700'
                        }`}
                      >
                        {artifact.conversation_id ? 'Conversation' : 'Project'}
                      </span>
                      <span className="inline-block text-xs font-medium px-2 py-1 bg-gray-100 text-gray-700 rounded">
                        {artifact.type}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {new Date(artifact.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete?.(artifact.id);
                    }}
                    className="ml-4 p-1.5 text-gray-400 hover:text-red-600 rounded transition-colors"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer Stats */}
      {!isLoading && (
        <div className="flex-shrink-0 border-t border-gray-200 p-3 bg-gray-50 text-xs text-gray-600">
          Showing {filteredArtifacts.length} of {artifacts.length} artifacts
        </div>
      )}
    </div>
  );
}
