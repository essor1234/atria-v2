import type { Message, Session, Project, Conversation, Artifact } from '../types';

const API_BASE = '/api';

class APIClient {
  // Chat endpoints
  async sendQuery(message: string, sessionId?: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/chat/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, sessionId }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async getMessages(): Promise<Message[]> {
    const response = await fetch(`${API_BASE}/chat/messages`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async clearChat(): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/chat/clear`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async fetchChartImage(pngPath: string): Promise<string> {
    const qs = new URLSearchParams({ path: pngPath });
    const response = await fetch(`${API_BASE}/analyze/chart-image?${qs.toString()}`);
    if (!response.ok) throw new Error(`chart-image error: ${response.statusText}`);
    const { src } = await response.json();
    return src as string;
  }

  async fetchTableData(dbPath: string, tableName: string, limit = 50000): Promise<{ columns: import('../types').DataColumn[]; rows: Record<string, any>[] }> {
    const qs = new URLSearchParams({ db_path: dbPath, table: tableName, limit: String(limit) });
    const response = await fetch(`${API_BASE}/analyze/table-data?${qs.toString()}`);
    if (!response.ok) throw new Error(`table-data error: ${response.statusText}`);
    return response.json();
  }

  // Generic GET method for any endpoint
  async get<T = any>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async interruptTask(): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/chat/interrupt`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // Session endpoints
  async listSessions(): Promise<Session[]> {
    const response = await fetch(`${API_BASE}/sessions`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async getCurrentSession(): Promise<Session> {
    const response = await fetch(`${API_BASE}/sessions/current`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async resumeSession(sessionId: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/resume`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async exportSession(sessionId: string): Promise<any> {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/export`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async verifyPath(path: string): Promise<{ exists: boolean; is_directory: boolean; path?: string; error?: string }> {
    const response = await fetch(`${API_BASE}/sessions/verify-path`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async browseDirectory(path: string = '', showHidden: boolean = false): Promise<{
    current_path: string;
    parent_path: string | null;
    directories: Array<{ name: string; path: string }>;
    error: string | null;
  }> {
    const response = await fetch(`${API_BASE}/sessions/browse-directory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, show_hidden: showHidden }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async getSessionMessages(sessionId: string): Promise<Message[]> {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
    if (!response.ok) {
      if (response.status === 404) return [];
      throw new Error(`API error: ${response.statusText}`);
    }
    return response.json();
  }

  async createSession(workspace: string): Promise<{ status: string; message: string; session: any }> {
    const response = await fetch(`${API_BASE}/sessions/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // Session model endpoints
  async getSessionModel(sessionId: string): Promise<Record<string, string>> {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/model`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async updateSessionModel(sessionId: string, overlay: Record<string, string | null>): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/model`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(overlay),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async clearSessionModel(sessionId: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/model`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // Config endpoints
  async getConfig(): Promise<any> {
    const response = await fetch(`${API_BASE}/config`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async updateConfig(config: any): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async listProviders(): Promise<any[]> {
    const response = await fetch(`${API_BASE}/config/providers`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async setMode(mode: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/config/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async setAutonomy(level: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/config/autonomy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async setThinkingLevel(level: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/config/thinking`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level }),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // File listing
  async listFiles(query?: string): Promise<{ files: Array<{ path: string; name: string; is_file: boolean }> }> {
    const url = query ? `${API_BASE}/sessions/files?query=${encodeURIComponent(query)}` : `${API_BASE}/sessions/files`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // Bridge mode
  async getBridgeInfo(): Promise<{ bridge_mode: boolean; session_id: string | null }> {
    const response = await fetch(`${API_BASE}/sessions/bridge-info`);
    if (!response.ok) return { bridge_mode: false, session_id: null };
    return response.json();
  }

  // Health check
  async health(): Promise<{ status: string; service: string }> {
    const response = await fetch(`${API_BASE}/health`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // Auth
  async login(email: string): Promise<{ username: string; email: string | null; role: string }> {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!response.ok) throw new Error((await response.json()).detail ?? response.statusText);
    return response.json();
  }

  async logout(): Promise<void> {
    await fetch(`${API_BASE}/auth/logout`, { method: 'POST' });
  }

  async me(): Promise<{ username: string; email: string | null; role: string } | null> {
    const response = await fetch(`${API_BASE}/auth/me`);
    if (response.status === 401) return null;
    if (!response.ok) return null;
    return response.json();
  }

  // ── Project endpoints ────────────────────────────────────────────────────

  async listProjects(): Promise<Project[]> {
    const res = await fetch(`${API_BASE}/projects`);
    if (!res.ok) throw new Error(`listProjects: ${res.statusText}`);
    return res.json();
  }

  async createProject(name: string): Promise<Project> {
    const res = await fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as any).detail || `createProject: ${res.statusText}`);
    }
    return res.json();
  }

  async deleteProject(projectId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/projects/${projectId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteProject: ${res.statusText}`);
  }

  async listConversations(projectId: string): Promise<Conversation[]> {
    const res = await fetch(`${API_BASE}/projects/${projectId}/conversations`);
    if (!res.ok) throw new Error(`listConversations: ${res.statusText}`);
    return res.json();
  }

  async createConversation(projectId: string, name: string): Promise<Conversation> {
    const res = await fetch(`${API_BASE}/projects/${projectId}/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as any).detail || `createConversation: ${res.statusText}`);
    }
    return res.json();
  }

  async deleteConversation(projectId: string, conversationId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/projects/${projectId}/conversations/${conversationId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteConversation: ${res.statusText}`);
  }

  // Artifacts
  async listArtifacts(conversationId: number): Promise<Artifact[]> {
    const response = await fetch(`${API_BASE}/artifacts?conversation_id=${conversationId}`);
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async createArtifact(data: {
    project_id: number;
    conversation_id?: number;
    type: string;
    title?: string;
    payload_ref?: string;
    source_mode?: string;
    pinned?: boolean;
  }): Promise<Artifact> {
    const response = await fetch(`${API_BASE}/artifacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async updateArtifact(artifactId: number, data: { title?: string; pinned?: boolean; payload_ref?: string }): Promise<Artifact> {
    const response = await fetch(`${API_BASE}/artifacts/${artifactId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  async deleteArtifact(artifactId: number): Promise<void> {
    const response = await fetch(`${API_BASE}/artifacts/${artifactId}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
  }

  async scanArtifacts(conversationId: number): Promise<Artifact[]> {
    const response = await fetch(`${API_BASE}/artifacts/scan?conversation_id=${conversationId}`, { method: 'POST' });
    if (!response.ok) throw new Error(`API error: ${response.statusText}`);
    return response.json();
  }

  // Filesystem (artifact viewer)
  async listFs(
    conversationId: number,
    path: string,
    showHidden: boolean,
  ): Promise<import('../types').FsListResponse> {
    const qs = new URLSearchParams({ path, show_hidden: String(showHidden) });
    const response = await fetch(
      `${API_BASE}/conversations/${conversationId}/fs/list?${qs.toString()}`,
    );
    if (!response.ok) throw new Error(`API error: ${response.status} ${response.statusText}`);
    return response.json();
  }

  async readFsText(conversationId: number, path: string): Promise<string> {
    const response = await fetch(this.readFsUrl(conversationId, path));
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.text();
  }

  async readFsBlob(conversationId: number, path: string): Promise<Blob> {
    const response = await fetch(this.readFsUrl(conversationId, path));
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.blob();
  }

  readFsUrl(conversationId: number, path: string): string {
    const qs = new URLSearchParams({ path });
    return `${API_BASE}/conversations/${conversationId}/fs/read?${qs.toString()}`;
  }
}

export const apiClient = new APIClient();
