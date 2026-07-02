import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Settings, Folder, Plus, Trash2 } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { useChatStore } from '../../stores/chat';
import { SettingsModal } from '../Settings/SettingsModal';
import { NewSessionModal } from './NewSessionModal';
import { DeleteConfirmModal } from './DeleteConfirmModal';
import { SessionModelModal } from './SessionModelModal';
import { apiClient } from '../../api/client';

interface Session {
  id: string;
  working_dir: string;
  message_count: number;
  token_usage: {
    prompt_tokens: number;
    completion_tokens: number;
  };
  created_at: string;
  updated_at: string;
  title?: string;
  status?: 'active' | 'answered' | 'open';
  has_session_model?: boolean;
}

interface WorkspaceGroup {
  path: string;
  sessions: Session[];
  mostRecent: Session;
}

const getProjectName = (path: string): string => {
  const parts = path.replace(/\/$/, '').split('/');
  return parts[parts.length - 1] || path;
};

export function SessionsSidebar() {
  const reduceMotion = useReducedMotion();
  const [_sessions, setSessions] = useState<Session[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceGroup[]>([]);
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isNewSessionOpen, setIsNewSessionOpen] = useState(false);
  const [deleteWorkspace, setDeleteWorkspace] = useState<WorkspaceGroup | null>(null);
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);
  const [showCollapsedContent, setShowCollapsedContent] = useState(false);
  const [sessionModelSessionId, setSessionModelSessionId] = useState<string | null>(null);
  const [sessionModelLabel, setSessionModelLabel] = useState('');
  const swapTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Get loadSession + sidebar state from chat store
  const loadSession = useChatStore(state => state.loadSession);
  const currentSessionId = useChatStore(state => state.currentSessionId);
  const sessionListVersion = useChatStore(state => state.sessionListVersion);
  const runningSessions = useChatStore(state => state.runningSessions);
  const sessionStates = useChatStore(state => state.sessionStates);
  const isCollapsed = useChatStore(state => state.sidebarCollapsed);
  const toggleSidebar = useChatStore(state => state.toggleSidebar);

  // Disable "New Chat" when the current session has no messages yet
  const currentSessionIsEmpty = currentSessionId !== null && (
    (sessionStates[currentSessionId]?.messages ?? []).length === 0
  );

  useEffect(() => {
    fetchSessions();
  }, [sessionListVersion]);

  // Delayed content swap: clips naturally via overflow-hidden
  useEffect(() => {
    if (swapTimerRef.current !== null) {
      clearTimeout(swapTimerRef.current);
      swapTimerRef.current = null;
    }

    if (isCollapsed) {
      // COLLAPSING: keep expanded content while width shrinks, swap at ~250ms
      swapTimerRef.current = setTimeout(() => {
        setShowCollapsedContent(true);
        swapTimerRef.current = null;
      }, 250);
    } else {
      // EXPANDING: swap to expanded content immediately, revealed as width grows
      setShowCollapsedContent(false);
    }

    return () => {
      if (swapTimerRef.current !== null) {
        clearTimeout(swapTimerRef.current);
        swapTimerRef.current = null;
      }
    };
  }, [isCollapsed]);

  const fetchSessions = async () => {
    try {
      const data = (await apiClient.listSessions()) as unknown as Session[];
      setSessions(data);

      // Group sessions by workspace
      const grouped = groupByWorkspace(data);
      setWorkspaces(grouped);
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const groupByWorkspace = (sessions: Session[]): WorkspaceGroup[] => {
    const groups: Record<string, Session[]> = {};

    // Filter out sessions without a working directory
    sessions.forEach(session => {
      if (!session.working_dir || session.working_dir.trim() === '') {
        return; // Skip sessions without working_dir
      }
      const path = session.working_dir;
      if (!groups[path]) {
        groups[path] = [];
      }
      groups[path].push(session);
    });

    // Convert to array and sort each group by updated_at
    return Object.entries(groups).map(([path, sessions]) => {
      const sorted = sessions.sort((a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
      return {
        path,
        sessions: sorted,
        mostRecent: sorted[0],
      };
    }).sort((a, b) =>
      new Date(b.mostRecent.updated_at).getTime() - new Date(a.mostRecent.updated_at).getTime()
    );
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const toggleWorkspace = (workspacePath: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedWorkspaces(prev => {
      const next = new Set(prev);
      if (next.has(workspacePath)) {
        next.delete(workspacePath);
      } else {
        next.add(workspacePath);
      }
      return next;
    });
  };

  const handleSessionClick = async (session: Session, e: React.MouseEvent) => {
    e.stopPropagation();
    await loadSession(session.id);
  };

  const handleNewWorkspace = () => {
    setIsNewSessionOpen(true);
  };

  const handleNewSessionInWorkspace = async (workspacePath: string, e: React.MouseEvent) => {
    e.stopPropagation();

    try {
      const result = await apiClient.createSession(workspacePath);

      // Refresh sessions list
      await fetchSessions();

      // Load the new session
      if (result.session && result.session.id) {
        await loadSession(result.session.id);
      }
    } catch (error) {
      console.error('[SessionsSidebar] Failed to create session:', error);
      alert('Failed to create new session');
    }
  };

  const handleDeleteWorkspace = (workspace: WorkspaceGroup, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteWorkspace(workspace);
  };

  const handleDeleteSession = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteSessionId(sessionId);
  };

  const confirmDeleteSession = async () => {
    if (!deleteSessionId) return;

    try {
      await apiClient.deleteSession(deleteSessionId);

      // Clean up per-session state
      const { sessionStates: currentStates } = useChatStore.getState();
      const updated = { ...currentStates };
      delete updated[deleteSessionId];
      useChatStore.setState({ sessionStates: updated });

      // If deleting the currently viewed session, clear it
      if (deleteSessionId === useChatStore.getState().currentSessionId) {
        useChatStore.setState({ currentSessionId: null, hasWorkspace: false });
      }

      // Refresh the sessions list
      await fetchSessions();

      setDeleteSessionId(null);
    } catch (error) {
      console.error('Failed to delete session:', error);
      alert('Failed to delete session');
    }
  };

  const confirmDelete = async () => {
    if (!deleteWorkspace) return;

    try {
      const currentSid = useChatStore.getState().currentSessionId;
      let needsClearCurrent = false;

      // Delete all sessions for this workspace
      for (const session of deleteWorkspace.sessions) {
        await apiClient.deleteSession(session.id);

        // Clean up per-session state
        const { sessionStates: currentStates } = useChatStore.getState();
        const updated = { ...currentStates };
        delete updated[session.id];
        useChatStore.setState({ sessionStates: updated });

        if (session.id === currentSid) {
          needsClearCurrent = true;
        }
      }

      if (needsClearCurrent) {
        useChatStore.setState({ currentSessionId: null, hasWorkspace: false });
      }

      // Refresh the sessions list
      await fetchSessions();

      // Remove from expanded workspaces if it was expanded
      setExpandedWorkspaces(prev => {
        const next = new Set(prev);
        next.delete(deleteWorkspace.path);
        return next;
      });

      setDeleteWorkspace(null);
    } catch (error) {
      console.error('Failed to delete workspace:', error);
      alert('Failed to delete workspace');
    }
  };

  const getSessionLabel = (session: Session): string => {
    return session.title || session.id.substring(0, 8);
  };

  return (
    <motion.aside
      initial={reduceMotion ? false : { opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="h-full flex flex-col relative overflow-hidden flex-shrink-0 bg-surface-soft border-r border-hairline-soft"
      style={{
        width: isCollapsed ? 64 : 320,
        transition: 'width 300ms cubic-bezier(0.25, 0.46, 0.45, 0.94)',
      }}
    >
      {showCollapsedContent ? (
        <div className="min-w-[64px] flex flex-col h-full animate-content-fade">
          {/* Collapsed Workspace Icons */}
          <div className="flex-1 overflow-y-auto py-3 space-y-2 flex flex-col items-center">
            {workspaces.slice(0, 5).map((workspace) => {
              const hasActiveSession = workspace.sessions.some(s => s.id === currentSessionId);
              const hasRunningSession = workspace.sessions.some(s => runningSessions.has(s.id));
              const projectName = getProjectName(workspace.path);

              return (
                <div
                  key={workspace.path}
                  className="relative group"
                  title={`${projectName} (${workspace.sessions.length} sessions)`}
                >
                  <button
                    onClick={() => {
                      toggleSidebar();
                      setTimeout(() => {
                        setExpandedWorkspaces(prev => new Set([...prev, workspace.path]));
                      }, 100);
                    }}
                    className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      hasActiveSession
                        ? 'bg-amber-100 border-2 border-amber-400 shadow-sm'
                        : 'bg-surface-soft hover:bg-surface-soft border border-hairline-soft hover:shadow-md'
                    }`}
                  >
                    <Folder className={`w-5 h-5 ${hasActiveSession ? 'text-amber-600' : 'text-text-muted'}`} />
                  </button>
                  {hasRunningSession && (
                    <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-[1.5px] border-amber-200 border-t-amber-500 animate-spin" />
                  )}

                  {/* Tooltip */}
                  <div data-surface="dark" className="absolute left-full ml-2 top-1/2 transform -translate-y-1/2 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap opacity-60 group-hover:opacity-100 pointer-events-none z-50 shadow-soft">
                    <div className="font-medium text-sm mb-1">{projectName}</div>
                    <div className="text-gray-300 text-xs">{workspace.sessions.length} session{workspace.sessions.length !== 1 ? 's' : ''}</div>
                    {hasActiveSession && <div className="text-amber-300 text-xs mt-1">Active</div>}
                    <div className="absolute right-full top-1/2 transform -translate-y-1/2 border-4 border-transparent border-r-gray-900"></div>
                  </div>
                </div>
              );
            })}

            {/* New Workspace Button (Collapsed) */}
            <button
              onClick={() => {
                if (currentSessionIsEmpty) return;
                toggleSidebar();
                setTimeout(() => setIsNewSessionOpen(true), 100);
              }}
              disabled={currentSessionIsEmpty}
              className={`w-10 h-10 rounded-lg flex items-center justify-center text-white shadow-md transition-all ${
                currentSessionIsEmpty
                  ? 'bg-gray-300 cursor-not-allowed opacity-50'
                  : 'bg-gradient-to-br from-accent-cobalt to-accent-violet hover:from-accent-cobalt hover:to-accent-violet hover:shadow-lg'
              }`}
              title={currentSessionIsEmpty ? 'Send a message before starting a new session' : 'Start Conversation'}
            >
              <Plus className="w-5 h-5" />
            </button>
          </div>

          {/* Collapsed Footer */}
          <div className="p-2 border-t border-hairline-soft bg-surface-soft">
            <button
              onClick={() => setIsSettingsOpen(true)}
              className="w-full p-2 text-text-secondary hover:text-ink bg-canvas hover:bg-amber-50/30 border border-hairline-soft hover:border-amber-300 rounded-xl flex items-center justify-center"
              title="Settings"
            >
              <Settings className="w-5 h-5" />
            </button>
          </div>
        </div>
      ) : (
        <div className="min-w-[320px] flex flex-col h-full animate-content-fade">
          {/* Compact New Chat Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-hairline-soft">
            <button
              onClick={currentSessionIsEmpty ? undefined : handleNewWorkspace}
              disabled={currentSessionIsEmpty}
              title={currentSessionIsEmpty ? 'Send a message before starting a new session' : undefined}
              className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg flex items-center justify-center gap-2 transition-all ${
                currentSessionIsEmpty
                  ? 'bg-gray-200 text-text-muted cursor-not-allowed'
                  : 'bg-gradient-to-r from-accent-cobalt to-accent-violet hover:from-accent-cobalt hover:to-accent-violet text-white shadow-sm hover:shadow-md'
              }`}
            >
              <Plus className="w-4 h-4" />
              <span>New Chat</span>
            </button>
          </div>

          {/* Workspaces Header */}
          <div className="px-5 py-4 border-b border-hairline-soft">
            <h2 className="text-xs font-semibold text-text-muted uppercase tracking-wider">Workspaces</h2>
          </div>

          {/* Workspaces List */}
          <div className="flex-1 overflow-y-auto px-4 py-3">
            {isLoading ? (
              <div className="space-y-3 px-0 py-3">
                <div className="skeleton-shimmer h-16 rounded-xl" />
                <div className="skeleton-shimmer h-16 rounded-xl" />
                <div className="skeleton-shimmer h-16 rounded-xl" />
              </div>
            ) : workspaces.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                <div className="w-16 h-16 rounded-full bg-surface-soft flex items-center justify-center mb-4">
                  <Folder className="w-8 h-8 text-text-muted" />
                </div>
                <h3 className="text-sm font-medium text-ink mb-1">No workspaces yet</h3>
                <p className="text-xs text-text-muted max-w-[200px]">
                  Start a conversation to create your first workspace
                </p>
              </div>
            ) : (
              <div className="space-y-3 animate-fade-in">
                {workspaces.map((workspace) => {
                  const isExpanded = expandedWorkspaces.has(workspace.path);
                  const hasActiveSession = workspace.sessions.some(s => s.id === currentSessionId);
                  const projectName = getProjectName(workspace.path);

                  return (
                    <div
                      key={workspace.path}
                      className="relative w-full rounded-xl bg-canvas border border-hairline-soft hover:border-hairline hover:shadow-sm"
                    >
                      {/* Workspace Header */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleWorkspace(workspace.path, e);
                        }}
                        className="w-full px-4 py-3.5 text-left group cursor-pointer hover:bg-surface-soft rounded-t-xl"
                      >
                        <div className="flex items-start gap-2 pr-10">
                          <ChevronDown
                            className={`mt-0.5 w-4 h-4 flex-shrink-0 text-text-muted ${
                              isExpanded ? 'rotate-0' : '-rotate-90'
                            }`}
                            style={{ transition: 'transform 200ms ease' }}
                          />

                          <div className="mt-0.5 w-4 h-4 rounded flex-shrink-0 flex items-center justify-center bg-surface-soft group-hover:bg-gray-200">
                            <Folder className="w-2.5 h-2.5 text-text-muted" />
                          </div>

                          <div className="flex-1 min-w-0">
                            <h3 className="text-sm font-semibold text-ink truncate" title={workspace.path}>
                              {projectName}
                            </h3>
                            <div className="flex items-center justify-between text-xs mt-1">
                              <span className="text-text-muted truncate" title={workspace.path}>
                                {formatDate(workspace.mostRecent.updated_at)}
                              </span>
                              <span className={`ml-2 px-1.5 py-0.5 rounded-full text-xs flex-shrink-0 ${
                                hasActiveSession
                                  ? 'bg-amber-100 text-amber-700 font-medium'
                                  : 'bg-gray-200 text-text-secondary'
                              }`}>
                                {workspace.sessions.length}
                              </span>
                            </div>
                          </div>
                        </div>
                      </button>

                      {/* Delete Button */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteWorkspace(workspace, e);
                        }}
                        className="absolute top-3.5 right-3 w-7 h-7 rounded-md flex items-center justify-center hover:bg-red-100 text-text-muted hover:text-red-600 bg-surface-soft shadow-sm z-10 delete-glow"
                        title="Delete workspace"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>

                      {/* Sessions List (Animated expand/collapse) */}
                      <div
                        className="overflow-hidden transition-all duration-300"
                        style={{
                          maxHeight: isExpanded ? '1000px' : '0px',
                          opacity: isExpanded ? 1 : 0,
                        }}
                      >
                        <div className="px-4 pb-3 space-y-1.5 border-t border-hairline-soft pt-2">
                          {/* Add New Session Button */}
                          <button
                            onClick={currentSessionIsEmpty ? undefined : (e) => handleNewSessionInWorkspace(workspace.path, e)}
                            disabled={currentSessionIsEmpty}
                            title={currentSessionIsEmpty ? 'Send a message before starting a new session' : undefined}
                            className={`w-full px-4 py-3 rounded-lg text-left border-2 border-dashed flex items-center gap-2 ${
                              currentSessionIsEmpty
                                ? 'bg-surface-soft border-hairline-soft text-text-muted cursor-not-allowed'
                                : 'cursor-pointer bg-amber-50/50 hover:bg-amber-50 border-amber-300 hover:border-amber-400 text-amber-700'
                            }`}
                          >
                            <Plus className="w-3.5 h-3.5" />
                            <span className="text-xs font-medium">New Session</span>
                          </button>

                          {/* Sessions List */}
                          {workspace.sessions.map((session) => {
                            const isActiveSession = currentSessionId === session.id;
                            const sessionLabel = getSessionLabel(session);
                            const isRunning = runningSessions.has(session.id);
                            const sState = sessionStates[session.id];
                            const needsAttention = !!(sState?.pendingApproval || sState?.pendingAskUser);

                            return (
                              <div key={session.id} className="relative group">
                                <button
                                  onClick={(e) => handleSessionClick(session, e)}
                                  className={`w-full px-4 py-3 pr-10 rounded-lg text-left cursor-pointer ${
                                    isActiveSession
                                      ? 'bg-amber-50 border-l-4 animate-border-breathe'
                                      : 'bg-canvas border border-hairline-soft hover:border-amber-300 hover:bg-amber-50/30 hover:scale-[1.01] hover:shadow-sm transition-all duration-200'
                                  }`}
                                >
                                  <div className="flex items-center gap-1.5">
                                    {isRunning && (
                                      <div className="w-3.5 h-3.5 rounded-full border-2 border-amber-200 border-t-amber-500 animate-spin flex-shrink-0" />
                                    )}
                                    {needsAttention && !isRunning && (
                                      <div className="w-4 h-4 rounded-full bg-orange-500 text-white text-[9px] font-bold flex items-center justify-center flex-shrink-0">!</div>
                                    )}
                                    <div className={`text-xs font-medium truncate ${
                                      isActiveSession ? 'text-amber-900' : 'text-ink'
                                    }`} title={session.title || session.id}>
                                      {sessionLabel}
                                    </div>
                                    {needsAttention && isRunning && (
                                      <div className="w-4 h-4 rounded-full bg-orange-500 text-white text-[9px] font-bold flex items-center justify-center flex-shrink-0">!</div>
                                    )}
                                    {session.has_session_model && (
                                      <span className="w-2 h-2 rounded-full bg-purple-400 flex-shrink-0" title="Custom model" />
                                    )}
                                  </div>
                                  <div className="flex items-center justify-between text-xs mt-1">
                                    <span className={`${
                                      isActiveSession ? 'text-amber-600' : 'text-text-muted'
                                    }`}>
                                      {formatDate(session.updated_at)}
                                    </span>
                                    <span className={`${
                                      isActiveSession ? 'text-amber-600' : 'text-text-muted'
                                    }`}>
                                      {session.message_count} msgs
                                    </span>
                                  </div>
                                </button>

                                {/* Session Action Buttons */}
                                <div className="absolute top-1.5 right-1.5 flex gap-0.5 opacity-60 group-hover:opacity-100 z-10">
                                  {/* Session Model Button */}
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSessionModelSessionId(session.id);
                                      setSessionModelLabel(getSessionLabel(session));
                                    }}
                                    className="w-6 h-6 rounded flex items-center justify-center hover:bg-amber-100 text-text-muted hover:text-amber-600"
                                    title="Session models"
                                  >
                                    <Settings className="w-3.5 h-3.5" />
                                  </button>
                                  {/* Delete Session Button */}
                                  <button
                                    onClick={(e) => handleDeleteSession(session.id, e)}
                                    className="w-6 h-6 rounded flex items-center justify-center hover:bg-red-100 text-text-muted hover:text-red-600 delete-glow"
                                    title="Delete session"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Footer - Expanded */}
          <div className="p-4 border-t border-hairline-soft bg-surface-soft">
            <button
              onClick={() => setIsSettingsOpen(true)}
              className="w-full px-4 py-2.5 text-sm font-medium text-text-secondary hover:text-ink bg-canvas hover:bg-amber-50/30 border border-hairline-soft hover:border-amber-300 rounded-xl flex items-center justify-center gap-2"
            >
              <Settings className="w-4 h-4" />
              <span>Settings</span>
            </button>
          </div>
        </div>
      )}

      {/* ===== MODALS (always accessible, outside conditional blocks) ===== */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />

      <NewSessionModal
        isOpen={isNewSessionOpen}
        onClose={() => setIsNewSessionOpen(false)}
      />

      <DeleteConfirmModal
        isOpen={deleteWorkspace !== null}
        workspacePath={deleteWorkspace?.path || ''}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteWorkspace(null)}
      />

      <SessionModelModal
        sessionId={sessionModelSessionId}
        sessionLabel={sessionModelLabel}
        onClose={() => {
          setSessionModelSessionId(null);
          fetchSessions();
        }}
      />

      {deleteSessionId && createPortal(
        <div
          className="fixed inset-0 bg-black/50 z-[99999] flex items-center justify-center"
          onClick={() => setDeleteSessionId(null)}
        >
          <div
            className="bg-canvas p-6 rounded-xl min-w-[400px] shadow-modal animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-ink mb-3">
              Delete Session
            </h3>
            <p className="text-sm text-text-muted mb-5">
              Are you sure you want to delete session <strong className="text-text-secondary">{deleteSessionId.substring(0, 8)}</strong>?
              <br />
              This action cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteSessionId(null)}
                className="px-4 py-2 border border-hairline-soft bg-canvas rounded-lg text-sm font-medium text-text-secondary hover:bg-surface-soft transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteSession}
                className="px-4 py-2 bg-semantic-danger hover:bg-semantic-danger/90 text-white rounded-lg text-sm font-medium transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </motion.aside>
  );
}
