/**
 * MCP Settings Component - Table View
 *
 * Displays MCP servers in a table format similar to terminal /mcp list
 * with real-time WebSocket updates
 */

import { useState, useEffect, useRef } from 'react';
import { CircleAlert, X, ArrowRight, Check, EllipsisVertical, Pencil, Trash2 } from 'lucide-react';
import { AddMCPServerModal } from './AddMCPServerModal';
import { EditMCPServerModal } from './EditMCPServerModal';
import { MCPToolsModal } from './MCPToolsModal';
import { wsClient } from '../../api/websocket';
import type { MCPServer, MCPServerCreateRequest, MCPServerUpdateRequest, MCPTool } from '../../types/mcp';
import type { WSMessage } from '../../types';
import {
  listMCPServers,
  connectMCPServer,
  disconnectMCPServer,
  testMCPServer,
  createMCPServer,
  updateMCPServer,
  deleteMCPServer,
  getMCPServer,
} from '../../api/mcp';

export function MCPSettings() {
  // Server list state
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal states
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showToolsModal, setShowToolsModal] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [selectedServerTools, setSelectedServerTools] = useState<MCPTool[]>([]);

  // Action states
  const [processingServer, setProcessingServer] = useState<string | null>(null);

  // Load servers on mount
  useEffect(() => {
    console.log('[MCPSettings] Component mounted, loading servers...');
    loadServers();
  }, []);

  // WebSocket event listener for real-time updates
  useEffect(() => {
    const handleWSMessage = (message: WSMessage) => {
      if (message.type === 'mcp_status_update') {
        const { server_name, status } = message.data;
        console.log('[MCPSettings] Status update via WebSocket:', { server_name, status });
        setServers(prev => prev.map(server =>
          server.name === server_name ? { ...server, status } : server
        ));
      } else if (message.type === 'mcp_servers_update') {
        console.log('[MCPSettings] Full update via WebSocket:', message.data);
        setServers(message.data.servers);
      }
    };

    const unsubscribe1 = wsClient.on('mcp_status_update', handleWSMessage);
    const unsubscribe2 = wsClient.on('mcp_servers_update', handleWSMessage);

    return () => {
      unsubscribe1();
      unsubscribe2();
    };
  }, []);

  const loadServers = async () => {
    setIsLoading(true);
    setError(null);
    try {
      console.log('[MCPSettings] Fetching from /api/mcp/servers...');
      const response = await listMCPServers();
      console.log('[MCPSettings] API Response:', response);
      console.log('[MCPSettings] Servers loaded:', response.servers?.length || 0, 'servers');
      setServers(response.servers || []);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to load servers';
      console.error('[MCPSettings] Load error:', errorMsg, err);
      setError(errorMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConnect = async (name: string) => {
    setProcessingServer(name);
    try {
      await connectMCPServer(name);
      await loadServers(); // Reload to update UI
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect');
    } finally {
      setProcessingServer(null);
    }
  };

  const handleDisconnect = async (name: string) => {
    setProcessingServer(name);
    try {
      await disconnectMCPServer(name);
      await loadServers(); // Reload to update UI
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disconnect');
    } finally {
      setProcessingServer(null);
    }
  };

  const handleTest = async (name: string) => {
    setProcessingServer(name);
    try {
      const response = await testMCPServer(name);
      alert(response.message || 'Connection test successful');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setProcessingServer(null);
    }
  };

  const handleViewTools = async (name: string) => {
    try {
      const serverDetail = await getMCPServer(name);
      setSelectedServerTools(serverDetail.tools);
      setSelectedServer(servers.find(s => s.name === name) || null);
      setShowToolsModal(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tools');
    }
  };

  const handleEdit = (server: MCPServer) => {
    setSelectedServer(server);
    setShowEditModal(true);
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Remove "${name}"? This action cannot be undone.`)) return;

    try {
      await deleteMCPServer(name);
      await loadServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove server');
    }
  };

  const handleAddServer = async (server: MCPServerCreateRequest) => {
    try {
      await createMCPServer(server);
      await loadServers();
      setShowAddModal(false);
    } catch (err) {
      throw err;
    }
  };

  const handleUpdateServer = async (name: string, update: MCPServerUpdateRequest) => {
    try {
      await updateMCPServer(name, update);
      await loadServers();
      setShowEditModal(false);
      setSelectedServer(null);
    } catch (err) {
      throw err;
    }
  };

  // Debug render
  console.log('[MCPSettings] Rendering with:', { isLoading, serversCount: servers.length, error });

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-ink">MCP Servers</h3>
          <p className="text-sm text-text-muted mt-0.5">
            Manage Model Context Protocol server connections
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-5 py-2 text-sm font-[480] text-inverse-ink bg-ink rounded-pill hover:bg-ink/90 transition-colors active:scale-[0.98] whitespace-nowrap"
        >
          Add Server
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex items-center justify-between px-4 py-3 bg-red-50 border border-semantic-danger rounded-lg">
          <div className="flex items-center gap-3">
            <CircleAlert className="w-5 h-5 text-semantic-danger" />
            <p className="text-sm text-semantic-danger">{error}</p>
          </div>
          <button onClick={() => setError(null)} className="text-semantic-danger hover:opacity-80">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <LoadingState />
      ) : servers.length === 0 ? (
        <EmptyState />
      ) : (
        <ServerTable
          servers={servers}
          processingServer={processingServer}
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          onTest={handleTest}
          onViewTools={handleViewTools}
          onEdit={handleEdit}
          onDelete={handleDelete}
        />
      )}

      {/* Footer Info */}
      <div className="pt-4 border-t border-hairline-soft">
        <p className="text-xs text-text-muted">
          <strong>Note:</strong> Connected servers are available in both terminal and web interface.
          Changes take effect immediately.
        </p>
      </div>

      {/* Modals */}
      <AddMCPServerModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSubmit={handleAddServer}
      />

      <EditMCPServerModal
        isOpen={showEditModal}
        server={selectedServer}
        onClose={() => {
          setShowEditModal(false);
          setSelectedServer(null);
        }}
        onSubmit={handleUpdateServer}
      />

      <MCPToolsModal
        isOpen={showToolsModal}
        serverName={selectedServer?.name || ''}
        tools={selectedServerTools}
        onClose={() => {
          setShowToolsModal(false);
          setSelectedServer(null);
          setSelectedServerTools([]);
        }}
      />
    </div>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

function LoadingState() {
  return (
    <div className="text-center py-12 bg-surface-soft rounded-lg border border-hairline-soft">
      <div className="inline-flex items-center justify-center w-12 h-12 mb-3">
        <div className="w-8 h-8 border-3 border-hairline-soft border-t-gray-900 rounded-full animate-spin" />
      </div>
      <p className="text-sm text-text-secondary">Loading MCP servers...</p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-12 bg-surface-soft rounded-lg border-2 border-dashed border-hairline-soft">
      <ArrowRight className="w-12 h-12 mx-auto text-text-muted mb-3" />
      <p className="text-sm text-text-secondary font-medium mb-1">No MCP servers configured</p>
      <p className="text-xs text-text-muted">
        Click "Add Server" above to add your first MCP server
      </p>
    </div>
  );
}

interface ServerTableProps {
  servers: MCPServer[];
  processingServer: string | null;
  onConnect: (name: string) => void;
  onDisconnect: (name: string) => void;
  onTest: (name: string) => void;
  onViewTools: (name: string) => void;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string) => void;
}

function ServerTable({
  servers,
  processingServer,
  onConnect,
  onDisconnect,
  onTest,
  onViewTools,
  onEdit,
  onDelete,
}: ServerTableProps) {
  return (
    <div className="bg-canvas border border-hairline-soft rounded-lg overflow-x-auto">
      <table className="w-full divide-y divide-hairline-soft">
        <colgroup>
          <col style={{ width: '40%' }} /> {/* Name */}
          <col style={{ width: '15%' }} /> {/* Status */}
          <col style={{ width: '15%' }} /> {/* Enabled */}
          <col style={{ width: '15%' }} /> {/* Auto-start */}
          <col style={{ width: '15%' }} /> {/* Actions */}
        </colgroup>
        <thead className="bg-surface-soft">
          <tr>
            <th className="px-4 py-3 text-left text-sm font-semibold text-text-secondary uppercase whitespace-nowrap">
              Name
            </th>
            <th className="px-4 py-3 text-center text-sm font-semibold text-text-secondary uppercase whitespace-nowrap">
              Status
            </th>
            <th className="px-4 py-3 text-center text-sm font-semibold text-text-secondary uppercase whitespace-nowrap">
              Enabled
            </th>
            <th className="px-4 py-3 text-center text-sm font-semibold text-text-secondary uppercase whitespace-nowrap">
              Auto-start
            </th>
            <th className="px-4 py-3 text-center text-sm font-semibold text-text-secondary uppercase whitespace-nowrap">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="bg-canvas">
          {servers.map((server) => (
            <ServerRow
              key={server.name}
              server={server}
              isProcessing={processingServer === server.name}
              onConnect={onConnect}
              onDisconnect={onDisconnect}
              onTest={onTest}
              onViewTools={onViewTools}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ServerRowProps {
  server: MCPServer;
  isProcessing: boolean;
  onConnect: (name: string) => void;
  onDisconnect: (name: string) => void;
  onTest: (name: string) => void;
  onViewTools: (name: string) => void;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string) => void;
}

function ServerRow({
  server,
  isProcessing,
  onConnect,
  onDisconnect,
  onTest,
  onViewTools,
  onEdit,
  onDelete,
}: ServerRowProps) {
  const isConnected = server.status === 'connected';

  const handleTest = () => {
    onTest(server.name);
  };

  return (
    <tr className="hover:bg-surface-soft transition-colors">
      {/* Name + Action Buttons */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-ink truncate">{server.name}</div>
            <div className="text-xs text-text-muted">{server.config_location}</div>
          </div>
          <div className="flex items-center gap-2">
            {/* Connect Button */}
            <button
              onClick={() => onConnect(server.name)}
              disabled={isProcessing || isConnected}
              className="px-4 py-1.5 text-sm font-[480] text-inverse-ink bg-ink hover:bg-ink/90 rounded-pill transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap active:scale-[0.98]"
            >
              Connect
            </button>

            {/* Disconnect Button */}
            <button
              onClick={() => onDisconnect(server.name)}
              disabled={isProcessing || !isConnected}
              className="px-3 py-1.5 text-sm font-medium text-text-secondary bg-canvas border border-hairline-soft hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              Disconnect
            </button>

            {/* Test Button */}
            <button
              onClick={handleTest}
              disabled={isProcessing}
              className="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 hover:bg-blue-100 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              Test
            </button>

            {/* Tools Button */}
            <button
              onClick={() => onViewTools(server.name)}
              disabled={isProcessing || !isConnected}
              className="px-3 py-1.5 text-sm font-medium text-text-secondary bg-canvas border border-hairline-soft hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              Tools
            </button>
          </div>
        </div>
      </td>

      {/* Status */}
      <td className="px-4 py-3 text-center whitespace-nowrap">
        {isProcessing ? (
          <div className="w-4 h-4 border-2 border-hairline-soft border-t-gray-900 rounded-full animate-spin mx-auto" />
        ) : isConnected ? (
          <div className="flex items-center justify-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-semantic-success" />
            <span className="text-sm font-medium text-green-700">On</span>
          </div>
        ) : (
          <div className="flex items-center justify-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-gray-300" />
            <span className="text-sm text-text-muted">Off</span>
          </div>
        )}
      </td>

      {/* Enabled */}
      <td className="px-4 py-3 text-center whitespace-nowrap">
        {server.config.enabled ? (
          <Check className="w-5 h-5 text-green-600 mx-auto" />
        ) : (
          <span className="text-text-muted">-</span>
        )}
      </td>

      {/* Auto-start */}
      <td className="px-4 py-3 text-center whitespace-nowrap">
        {server.config.auto_start ? (
          <Check className="w-5 h-5 text-green-600 mx-auto" />
        ) : (
          <span className="text-text-muted">-</span>
        )}
      </td>

      {/* Actions - Dropdown only */}
      <td className="px-4 py-3 text-center whitespace-nowrap">
        <div className="flex items-center justify-center">
          <DropdownMenu
            server={server}
            isProcessing={isProcessing}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        </div>
      </td>
    </tr>
  );
}

// ============================================================================
// Dropdown Menu Component
// ============================================================================

interface DropdownMenuProps {
  server: MCPServer;
  isProcessing: boolean;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string) => void;
}

function DropdownMenu({ server, isProcessing, onEdit, onDelete }: DropdownMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Dropdown Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={isProcessing}
        className="p-2 text-text-muted hover:text-text-secondary hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        title="More actions"
      >
        <EllipsisVertical className="w-5 h-5" />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-1 w-32 bg-canvas border border-hairline-soft rounded-lg shadow-soft z-10 overflow-hidden">
          <button
            onClick={() => {
              onEdit(server);
              setIsOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-sm text-text-secondary hover:bg-surface-soft transition-colors flex items-center gap-2"
          >
            <Pencil className="w-4 h-4" />
            Edit
          </button>
          <button
            onClick={() => {
              onDelete(server.name);
              setIsOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-sm text-semantic-danger hover:bg-red-50 transition-colors flex items-center gap-2"
          >
            <Trash2 className="w-4 h-4" />
            Remove
          </button>
        </div>
      )}
    </div>
  );
}
