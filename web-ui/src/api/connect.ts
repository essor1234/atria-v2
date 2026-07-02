/**
 * Connect API client — manage channel connections (Telegram).
 * Mirrors api/mcp.ts.
 */

const API_BASE = '/api';

export interface ConnectRecipient {
  role: string;
  name: string;
  chat_id: string;
}

export interface ConnectConnection {
  id: string;
  type: string;
  label: string;
  enabled: boolean;
  bot_token_masked: string;
  status: string;
  bot_username: string | null;
  last_error: string | null;
  recipients: ConnectRecipient[];
  recipient_count: number;
}

export interface PendingContact {
  chat_id: string;
  name: string;
}

async function fetchAPI<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `API error: ${response.statusText}`);
  }
  return response.json();
}

export function listConnections(): Promise<{ connections: ConnectConnection[] }> {
  return fetchAPI('/connect/connections');
}

export function createConnection(body: {
  type?: string;
  label?: string;
  bot_token: string;
  enabled?: boolean;
}): Promise<any> {
  return fetchAPI('/connect/connections', { method: 'POST', body: JSON.stringify(body) });
}

export function updateConnection(
  id: string,
  body: { label?: string; bot_token?: string; enabled?: boolean }
): Promise<any> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function deleteConnection(id: string): Promise<any> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function testConnection(id: string): Promise<{ ok: boolean; bot_username?: string; error?: string }> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}/test`, { method: 'POST' });
}

export function enableConnection(id: string): Promise<any> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}/enable`, { method: 'POST' });
}

export function disableConnection(id: string): Promise<any> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}/disable`, { method: 'POST' });
}

export function getPendingContacts(id: string): Promise<{ pending: PendingContact[] }> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}/pending-contacts`);
}

export function addRecipient(
  id: string,
  body: { role: string; name: string; chat_id: string }
): Promise<any> {
  return fetchAPI(`/connect/connections/${encodeURIComponent(id)}/recipients`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function removeRecipient(id: string, chatId: string): Promise<any> {
  return fetchAPI(
    `/connect/connections/${encodeURIComponent(id)}/recipients/${encodeURIComponent(chatId)}`,
    { method: 'DELETE' }
  );
}
