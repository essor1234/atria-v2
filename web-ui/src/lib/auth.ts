/**
 * Cross-store reset + sign-out helper.
 *
 * The chat / artifacts / projects / file* / viewer stores are plain in-memory
 * Zustand singletons. Switching users in the same browser tab does NOT reload
 * the page, so without an explicit reset the new user inherits the previous
 * user's sidebar, cached messages, open tabs, etc.
 *
 * Call resetAllStores() any time the active user identity changes, and
 * signOut() to log out + reset + bounce to /login.
 */
import { apiClient } from '../api/client';
import { wsClient } from '../api/websocket';
import { useChatStore } from '../stores/chat';
import { useArtifactsStore } from '../stores/artifacts';
import { useProjectsStore } from '../stores/projects';
import { useFileExplorerStore } from '../stores/fileExplorer';
import { useViewerTabsStore } from '../stores/viewerTabs';

export function resetAllStores(): void {
  // Chat — clear cached per-session messages, current session, status,
  // pending review state, running set. Keep UI prefs (sidebarCollapsed,
  // thinkingLevel) since those are user-agnostic.
  useChatStore.setState({
    sessionStates: {},
    currentSessionId: null,
    hasWorkspace: false,
    status: null,
    runningSessions: new Set<string>(),
    sessionListVersion: 0,
  });

  useArtifactsStore.setState({
    artifacts: {},
    loading: {},
    scanning: false,
  });

  useProjectsStore.setState({
    projects: [],
    conversations: {},
    workspaceProjectId: null,
    expandedProjects: new Set<string>(),
    isLoading: false,
    error: null,
  });

  // File explorer / viewer tabs are keyed by conv id; wipe them
  // so a fresh login doesn't leak the previous user's directory tree.
  useFileExplorerStore.setState({
    treesByConv: {},
  });

  useViewerTabsStore.setState({
    tabsByConv: {},
  });
}

/**
 * Hit the logout endpoint, wipe in-memory state, and drop the WebSocket so
 * the next connect carries the new (or absent) auth cookie.
 */
export async function signOut(): Promise<void> {
  try {
    await apiClient.logout();
  } catch {
    // Even if the server call fails (e.g. offline), still clear local state.
  }
  try {
    wsClient.disconnect();
  } catch {
    // disconnect is best-effort
  }
  resetAllStores();
}
