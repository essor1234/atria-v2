/**
 * Channel connections ("Connect") settings tab.
 *
 * Manage Telegram bot connections: add a bot token, enable/disable, and assign
 * owner/manager recipients (the allowlist). Mirrors MCPSettings.tsx.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  listConnections,
  createConnection,
  deleteConnection,
  enableConnection,
  disableConnection,
  getPendingContacts,
  addRecipient,
  removeRecipient,
  type ConnectConnection,
  type PendingContact,
} from '../../api/connect';

export function ChannelSettings() {
  const [connections, setConnections] = useState<ConnectConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // add-connection form
  const [label, setLabel] = useState('');
  const [token, setToken] = useState('');
  const [adding, setAdding] = useState(false);

  // per-connection pending contacts
  const [pending, setPending] = useState<Record<string, PendingContact[]>>({});

  const load = useCallback(async () => {
    try {
      setError(null);
      const res = await listConnections();
      setConnections(res.connections);
    } catch (e: any) {
      setError(e.message || 'Failed to load connections');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async () => {
    if (!token.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await createConnection({ type: 'telegram', label: label.trim(), bot_token: token.trim() });
      setLabel('');
      setToken('');
      await load();
    } catch (e: any) {
      setError(e.message || 'Failed to add connection');
    } finally {
      setAdding(false);
    }
  };

  const handleToggle = async (c: ConnectConnection) => {
    setError(null);
    try {
      await (c.enabled ? disableConnection(c.id) : enableConnection(c.id));
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleDelete = async (id: string) => {
    setError(null);
    try {
      await deleteConnection(id);
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const refreshPending = async (id: string) => {
    try {
      const res = await getPendingContacts(id);
      setPending((p) => ({ ...p, [id]: res.pending }));
    } catch {
      /* ignore */
    }
  };

  const handleAddRecipient = async (id: string, role: string, c: PendingContact) => {
    try {
      await addRecipient(id, { role, name: c.name, chat_id: c.chat_id });
      await load();
      await refreshPending(id);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleRemoveRecipient = async (id: string, chatId: string) => {
    try {
      await removeRecipient(id, chatId);
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const statusColor = (s: string) =>
    s === 'running'
      ? 'text-green-600'
      : s === 'conflict' || s === 'error'
      ? 'text-red-600'
      : 'text-gray-500';

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">Connect</h3>
        <p className="text-sm text-gray-500 mt-1">
          Connect a chat app so your team can message the agent. First channel: Telegram (a bot).
          Setup: create a bot with <span className="font-mono">@BotFather</span>, paste its token
          below, then have each person tap <span className="font-mono">/start</span> on the bot and
          add them as Owner/Manager.
        </p>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Add a Telegram connection */}
      <div className="rounded-lg border border-gray-200 p-4 space-y-3">
        <p className="text-sm font-medium text-gray-900">Add Telegram bot</p>
        <input
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
          placeholder="Label (e.g. Acme Logistics)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <input
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
          placeholder="Bot token from @BotFather (e.g. 123456:ABC-DEF...)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button
          onClick={handleAdd}
          disabled={adding || !token.trim()}
          className="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-md hover:bg-gray-700 disabled:opacity-50"
        >
          {adding ? 'Validating…' : 'Add & Enable'}
        </button>
      </div>

      {/* Connections list */}
      {loading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : connections.length === 0 ? (
        <p className="text-sm text-gray-500">No connections yet.</p>
      ) : (
        <div className="space-y-4">
          {connections.map((c) => (
            <div key={c.id} className="rounded-lg border border-gray-200 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-900">
                    {c.label}{' '}
                    {c.bot_username && (
                      <span className="text-gray-400 font-normal">@{c.bot_username}</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-500 font-mono">{c.bot_token_masked}</p>
                  <p className={`text-xs mt-0.5 ${statusColor(c.status)}`}>
                    {c.status}
                    {c.last_error ? ` — ${c.last_error}` : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleToggle(c)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
                  >
                    {c.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={() => handleDelete(c.id)}
                    className="px-3 py-1.5 text-xs font-medium text-red-600 border border-red-200 rounded-md hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Recipients (the allowlist) */}
              <div className="border-t border-gray-100 pt-3">
                <p className="text-xs font-medium text-gray-700 mb-2">
                  Recipients (allowed to use the bot)
                </p>
                {c.recipients.length === 0 ? (
                  <p className="text-xs text-gray-400">None yet.</p>
                ) : (
                  <ul className="space-y-1">
                    {c.recipients.map((r) => (
                      <li key={r.chat_id} className="flex items-center justify-between text-xs">
                        <span>
                          <span className="font-medium">{r.role}</span> — {r.name || '(no name)'}{' '}
                          <span className="text-gray-400 font-mono">{r.chat_id}</span>
                        </span>
                        <button
                          onClick={() => handleRemoveRecipient(c.id, r.chat_id)}
                          className="text-red-500 hover:underline"
                        >
                          remove
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                {/* Pending contacts (tapped /start, not yet added) */}
                <div className="mt-3">
                  <button
                    onClick={() => refreshPending(c.id)}
                    className="text-xs text-gray-600 hover:underline"
                  >
                    Refresh pending contacts
                  </button>
                  {(pending[c.id] || []).length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {(pending[c.id] || []).map((p) => (
                        <li key={p.chat_id} className="flex items-center justify-between text-xs">
                          <span>
                            {p.name} <span className="text-gray-400 font-mono">{p.chat_id}</span>
                          </span>
                          <span className="flex gap-2">
                            <button
                              onClick={() => handleAddRecipient(c.id, 'owner', p)}
                              className="text-gray-700 hover:underline"
                            >
                              + Owner
                            </button>
                            <button
                              onClick={() => handleAddRecipient(c.id, 'manager', p)}
                              className="text-gray-700 hover:underline"
                            >
                              + Manager
                            </button>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
