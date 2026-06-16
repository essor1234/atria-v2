import type { Message, Session, Project, Conversation, Artifact, FsScope } from '../types';
import type { Persona } from '../types';

const API_BASE = '/api';

function fsPath(scope: FsScope): string {
  return scope.kind === 'conv'
    ? `/conversations/${scope.id}/fs`
    : `/modules/${encodeURIComponent(scope.name)}/fs`;
}

function fsBase(scope: FsScope): string {
  return `${API_BASE}${fsPath(scope)}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  raw?: boolean;
}

async function apiError(response: Response): Promise<Error> {
  try {
    const data = await response.json();
    if (data && typeof data === 'object' && 'detail' in data && data.detail) {
      return new Error(String(data.detail));
    }
  } catch {
    // ignore non-JSON bodies
  }
  return new Error(`API error: ${response.status} ${response.statusText}`);
}

function buildQuery(query?: RequestOptions['query']): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined) continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, raw } = opts;
  const init: RequestInit = { method, credentials: 'include' };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(`${API_BASE}${path}${buildQuery(query)}`, init);
  if (!response.ok) throw await apiError(response);
  if (raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return response.json();
}

class APIClient {
  // Chat endpoints
  sendQuery(message: string, sessionId?: string) {
    return request<{ status: string; message: string }>('/chat/query', {
      method: 'POST',
      body: { message, sessionId },
    });
  }

  getMessages() {
    return request<Message[]>('/chat/messages');
  }

  clearChat() {
    return request<{ status: string; message: string }>('/chat/clear', { method: 'DELETE' });
  }

  async fetchChartImage(pngPath: string): Promise<string> {
    const { src } = await request<{ src: string }>('/analyze/chart-image', {
      query: { path: pngPath },
    });
    return src;
  }

  fetchTableData(dbPath: string, tableName: string, limit = 50000) {
    return request<{ columns: import('../types').DataColumn[]; rows: Record<string, any>[] }>(
      '/analyze/table-data',
      { query: { db_path: dbPath, table: tableName, limit } },
    );
  }

  // Generic GET method for any endpoint
  get<T = any>(endpoint: string) {
    return request<T>(endpoint);
  }

  interruptTask() {
    return request<{ status: string; message: string }>('/chat/interrupt', { method: 'POST' });
  }

  // Session endpoints
  listSessions() {
    return request<Session[]>('/sessions');
  }

  getCurrentSession() {
    return request<Session>('/sessions/current');
  }

  resumeSession(sessionId: string) {
    return request<{ status: string; message: string }>(`/sessions/${sessionId}/resume`, {
      method: 'POST',
    });
  }

  exportSession(sessionId: string) {
    return request<any>(`/sessions/${sessionId}/export`);
  }

  verifyPath(path: string) {
    return request<{ exists: boolean; is_directory: boolean; path?: string; error?: string }>(
      '/sessions/verify-path',
      { method: 'POST', body: { path } },
    );
  }

  browseDirectory(path: string = '', showHidden: boolean = false) {
    return request<{
      current_path: string;
      parent_path: string | null;
      directories: Array<{ name: string; path: string }>;
      error: string | null;
    }>('/sessions/browse-directory', {
      method: 'POST',
      body: { path, show_hidden: showHidden },
    });
  }

  async getSessionMessages(sessionId: string): Promise<Message[]> {
    try {
      return await request<Message[]>(`/sessions/${sessionId}/messages`);
    } catch (err) {
      if (err instanceof Error && /404/.test(err.message)) return [];
      throw err;
    }
  }

  createSession(workspace: string) {
    return request<{ status: string; message: string; session: any }>('/sessions/create', {
      method: 'POST',
      body: { workspace },
    });
  }

  deleteSession(sessionId: string) {
    return request<void>(`/sessions/${sessionId}`, { method: 'DELETE' });
  }

  deleteSessionTurn(sessionId: string, turnIndex: number) {
    return request<{ deleted: number; messages: any[] }>(
      `/sessions/${sessionId}/turns/${turnIndex}`,
      { method: 'DELETE' },
    );
  }

  // Session model endpoints
  getSessionModel(sessionId: string) {
    return request<Record<string, string>>(`/sessions/${sessionId}/model`);
  }

  updateSessionModel(sessionId: string, overlay: Record<string, string | null>) {
    return request<{ status: string; message: string }>(`/sessions/${sessionId}/model`, {
      method: 'PUT',
      body: overlay,
    });
  }

  clearSessionModel(sessionId: string) {
    return request<{ status: string; message: string }>(`/sessions/${sessionId}/model`, {
      method: 'DELETE',
    });
  }

  // Config endpoints
  getConfig() {
    return request<any>('/config');
  }

  updateConfig(config: any) {
    return request<{ status: string; message: string }>('/config', { method: 'PUT', body: config });
  }

  listProviders() {
    return request<any[]>('/config/providers');
  }

  setMode(mode: string) {
    return request<{ status: string; message: string }>('/config/mode', {
      method: 'POST',
      body: { mode },
    });
  }

  setAutonomy(level: string) {
    return request<{ status: string; message: string }>('/config/autonomy', {
      method: 'POST',
      body: { level },
    });
  }

  setThinkingLevel(level: string) {
    return request<{ status: string; message: string }>('/config/thinking', {
      method: 'POST',
      body: { level },
    });
  }

  // File listing
  listFiles(query?: string) {
    return request<{ files: Array<{ path: string; name: string; is_file: boolean }> }>(
      '/sessions/files',
      { query: query ? { query } : undefined },
    );
  }

  // Bridge mode
  async getBridgeInfo(): Promise<{ bridge_mode: boolean; session_id: string | null }> {
    try {
      return await request<{ bridge_mode: boolean; session_id: string | null }>(
        '/sessions/bridge-info',
      );
    } catch {
      return { bridge_mode: false, session_id: null };
    }
  }

  // Health check
  health() {
    return request<{ status: string; service: string }>('/health');
  }

  // Auth
  login(email: string) {
    return request<{ username: string; email: string | null; role: string }>('/auth/login', {
      method: 'POST',
      body: { email },
    });
  }

  async logout(): Promise<void> {
    try {
      await request<void>('/auth/logout', { method: 'POST' });
    } catch {
      // ignore — logout is best-effort
    }
  }

  async me(): Promise<{ username: string; email: string | null; role: string } | null> {
    try {
      return await request<{ username: string; email: string | null; role: string }>('/auth/me');
    } catch {
      return null;
    }
  }

  // ── Personas ─────────────────────────────────────────────────────────────

  listPersonas() {
    return request<Persona[]>('/personas');
  }

  createPersona(persona: Persona) {
    return request<Persona>('/personas', { method: 'POST', body: persona });
  }

  updatePersona(name: string, persona: Persona) {
    return request<Persona>(`/personas/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: persona,
    });
  }

  deletePersona(name: string) {
    return request<void>(`/personas/${encodeURIComponent(name)}`, { method: 'DELETE' });
  }

  // ── Module bridge ────────────────────────────────────────────────────────

  pushBlock(sessionId: string | null, moduleName: string, block: string, props: Record<string, unknown>) {
    return request<void>('/blocks/push', {
      method: 'POST',
      body: { session_id: sessionId, module: moduleName, block, props },
    });
  }

  async runModuleScript(
    moduleName: string,
    payload: { script: string; args: unknown[]; stdin?: unknown; timeout_ms?: number },
  ): Promise<{ ok: true; data: any } | { ok: false; status: number; message: string }> {
    const init: RequestInit = {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    };
    const response = await fetch(
      `${API_BASE}/modules/${encodeURIComponent(moduleName)}/run`,
      init,
    );
    if (!response.ok) {
      const message = await response.text().catch(() => response.statusText);
      return { ok: false, status: response.status, message: message || response.statusText };
    }
    return { ok: true, data: await response.json() };
  }

  // ── Project endpoints ────────────────────────────────────────────────────

  listProjects() {
    return request<Project[]>('/projects');
  }

  createProject(name: string) {
    return request<Project>('/projects', { method: 'POST', body: { name } });
  }

  deleteProject(projectId: string) {
    return request<void>(`/projects/${projectId}`, { method: 'DELETE' });
  }

  listConversations(projectId: string) {
    return request<Conversation[]>(`/projects/${projectId}/conversations`);
  }

  createConversation(projectId: string, name: string) {
    return request<Conversation>(`/projects/${projectId}/conversations`, {
      method: 'POST',
      body: { name },
    });
  }

  deleteConversation(projectId: string, conversationId: string) {
    return request<void>(`/projects/${projectId}/conversations/${conversationId}`, {
      method: 'DELETE',
    });
  }

  // Artifacts
  listArtifacts(conversationId: number) {
    return request<Artifact[]>('/artifacts', { query: { conversation_id: conversationId } });
  }

  createArtifact(data: {
    project_id: number;
    conversation_id?: number;
    type: string;
    title?: string;
    payload_ref?: string;
    source_mode?: string;
    pinned?: boolean;
  }) {
    return request<Artifact>('/artifacts', { method: 'POST', body: data });
  }

  updateArtifact(
    artifactId: number,
    data: { title?: string; pinned?: boolean; payload_ref?: string },
  ) {
    return request<Artifact>(`/artifacts/${artifactId}`, { method: 'PATCH', body: data });
  }

  deleteArtifact(artifactId: number) {
    return request<void>(`/artifacts/${artifactId}`, { method: 'DELETE' });
  }

  scanArtifacts(conversationId: number) {
    return request<Artifact[]>('/artifacts/scan', {
      method: 'POST',
      query: { conversation_id: conversationId },
    });
  }

  // Filesystem (artifact viewer + module editor)
  listFs(
    scope: FsScope,
    path: string,
    showHidden: boolean,
  ): Promise<import('../types').FsListResponse> {
    const query: Record<string, string> = { path };
    if (scope.kind === 'conv') query.show_hidden = String(showHidden);
    return request<import('../types').FsListResponse>(
      `${fsPath(scope)}/list`,
      { query },
    );
  }

  async readFsText(scope: FsScope, path: string): Promise<string> {
    const response = await fetch(this.readFsUrl(scope, path), { credentials: 'include' });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.text();
  }

  async readFsBlob(scope: FsScope, path: string): Promise<Blob> {
    const response = await fetch(this.readFsUrl(scope, path), { credentials: 'include' });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.blob();
  }

  readFsUrl(scope: FsScope, path: string): string {
    const qs = new URLSearchParams({ path });
    return `${fsBase(scope)}/read?${qs.toString()}`;
  }

  writeFsText(scope: FsScope, path: string, content: string): Promise<void> {
    return request<void>(`${fsPath(scope)}/write`, {
      method: 'PUT',
      body: { path, content },
    });
  }

  async writeFsBinary(
    scope: FsScope,
    path: string,
    bytes: Uint8Array,
  ): Promise<void> {
    const qs = new URLSearchParams({ path });
    // Wrap in a Blob — modern lib types reject raw Uint8Array as BodyInit.
    const body = new Blob([bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer], {
      type: 'application/octet-stream',
    });
    const response = await fetch(
      `${fsBase(scope)}/write-binary?${qs.toString()}`,
      {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/octet-stream' },
        body,
      },
    );
    if (!response.ok) throw await apiError(response);
  }

  deleteFsFile(scope: FsScope, path: string): Promise<void> {
    if (scope.kind !== 'module') {
      throw new Error('deleteFsFile only supported for module scope');
    }
    return request<void>(`${fsPath(scope)}/file`, {
      method: 'DELETE',
      query: { path },
    });
  }

  mkdirFs(scope: FsScope, path: string): Promise<void> {
    if (scope.kind !== 'module') throw new Error('mkdirFs only supported for module scope');
    return request<void>(`${fsPath(scope)}/mkdir`, {
      method: 'POST',
      body: { path },
    });
  }

  touchFs(scope: FsScope, path: string): Promise<void> {
    if (scope.kind !== 'module') throw new Error('touchFs only supported for module scope');
    return request<void>(`${fsPath(scope)}/touch`, {
      method: 'POST',
      body: { path },
    });
  }

  renameFs(scope: FsScope, from: string, to: string): Promise<void> {
    if (scope.kind !== 'module') throw new Error('renameFs only supported for module scope');
    return request<void>(`${fsPath(scope)}/rename`, {
      method: 'POST',
      body: { from, to },
    });
  }
}

export const apiClient = new APIClient();
