import { create } from 'zustand';
import type { Message, ApprovalRequest, StatusInfo, AskUserRequest, PlanApprovalRequest, PerSessionState, ToolCallInfo, DataColumn, ChartSuggestion } from '../types';
import { apiClient } from '../api/client';
import { wsClient } from '../api/websocket';
import { useToastStore } from './toast';
import { useArtifactsStore } from './artifacts';

// ─── Helpers ────────────────────────────────────────────────────────────────

const DEFAULT_SESSION: PerSessionState = {
  messages: [],
  isLoading: false,
  error: null,
  pendingApproval: null,
  pendingAskUser: null,
  pendingPlanApproval: null,
  progressMessage: null,
  queuedMessages: [],
  selectedPersona: null,
  draft: '',
};

function getSessionState(states: Record<string, PerSessionState>, id: string): PerSessionState {
  return states[id] ?? DEFAULT_SESSION;
}

function patchSession(
  state: ChatState,
  sessionId: string,
  patch: Partial<PerSessionState> | ((prev: PerSessionState) => Partial<PerSessionState>),
): { sessionStates: Record<string, PerSessionState> } {
  const prev = getSessionState(state.sessionStates, sessionId);
  const updates = typeof patch === 'function' ? patch(prev) : patch;
  return {
    sessionStates: {
      ...state.sessionStates,
      [sessionId]: { ...prev, ...updates },
    },
  };
}

/** Recursively expand tool calls (including nested) into flat message list. */
function expandToolCalls(
  toolCalls: ToolCallInfo[],
  timestamp: string | undefined,
  depth: number = 0,
): Message[] {
  const messages: Message[] = [];
  for (const tc of toolCalls) {
    const toolResult = tc.error
      ? { success: false, error: tc.error }
      : tc.result ?? '';
    messages.push({
      role: 'tool_call',
      content: `Calling ${tc.name}`,
      tool_call_id: tc.id,
      tool_name: tc.name,
      tool_args: tc.parameters,
      tool_args_display: undefined,
      tool_result: toolResult,
      tool_summary: tc.result_summary || null,
      tool_success: !tc.error,
      tool_error: tc.error || null,
      timestamp,
      depth: depth > 0 ? depth : undefined,
    });
    // Reconstruct the chart bubble from persisted send_data tool calls so
    // it survives session reload (the live WS data_message event isn't
    // replayed from DB).
    if ((tc.name === 'send_data' || tc.name === 'send_editable_table') && !tc.error && depth === 0) {
      const payload = extractDataPayload(tc.result);
      if (payload) {
        messages.push({
          role: 'data_message',
          content: payload.title || '',
          data_message_id: `data-${tc.id}`,
          data_title: payload.title,
          data_columns: payload.columns as DataColumn[] | undefined,
          data_rows: payload.rows as Record<string, any>[] | undefined,
          data_suggestions: payload.suggestions as ChartSuggestion[] | undefined,
          data_warning: payload.warning as string | undefined,
          data_editable: payload.editable as boolean | undefined,
          data_source: payload.source as { module: string; file: string } | undefined,
          timestamp,
        });
      }
    }
    // Recurse into nested tool calls
    if (tc.nested_tool_calls && tc.nested_tool_calls.length > 0) {
      messages.push(...expandToolCalls(tc.nested_tool_calls, timestamp, depth + 1));
    }
  }
  return messages;
}

function extractDataPayload(result: unknown): {
  title?: string;
  columns?: unknown;
  rows?: unknown;
  suggestions?: unknown;
  warning?: unknown;
  editable?: unknown;
  source?: unknown;
} | null {
  if (!result) return null;
  let parsed: any = result;
  if (typeof parsed === 'string') {
    try {
      parsed = JSON.parse(parsed);
    } catch {
      return null;
    }
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const payload = parsed.data_payload;
  if (!payload || typeof payload !== 'object') return null;
  return payload;
}

/** Expand raw API messages (with tool_calls arrays) into flat message list. */
function expandMessages(rawMessages: Message[]): Message[] {
  const expanded: Message[] = [];
  for (const msg of rawMessages) {
    // Reconstruct deep_analyze block from persisted metadata
    if (msg.metadata?.type === 'deep_analyze') {
      const m = msg.metadata;
      expanded.push({
        role: 'deep_analyze',
        content: m.file_name || '',
        da_job_id: m.job_id,
        da_status: m.da_status || 'done',
        da_phases: m.da_phases,
        da_subtables: m.da_subtables || [],
        da_plan_subtables: m.da_subtables?.length,
        da_report_path: m.da_report_path,
        timestamp: msg.timestamp,
      });
      // Reconstruct chart image + insight blocks from saved chart metadata
      for (const chart of (m.da_charts || [])) {
        if (!chart.png_path) continue;
        expanded.push({
          role: 'data_message',
          content: chart.title || chart.name || '',
          data_message_id: `da_chart_${chart.name}`,
          data_title: chart.title || chart.name || '',
          data_image_path: chart.png_path,
          data_sql: chart.sql || undefined,
          timestamp: msg.timestamp,
        });
        if (chart.insight_md) {
          expanded.push({
            role: 'assistant',
            content: `**${chart.title || chart.name}**\n\n${chart.insight_md}`,
            timestamp: msg.timestamp,
          });
        }
      }
      // Restore final agent summary message
      if (m.da_agent_message) {
        expanded.push({
          role: 'assistant',
          content: m.da_agent_message,
          timestamp: msg.timestamp,
        });
      }
      continue;
    }

    // Emit thinking traces before content (matches TUI hydration order)
    if (msg.thinking_trace && msg.thinking_trace.trim()) {
      expanded.push({
        role: 'thinking',
        content: msg.thinking_trace,
        metadata: { level: 'Medium' },
        timestamp: msg.timestamp,
      });
    }
    if (msg.reasoning_content && msg.reasoning_content.trim()) {
      expanded.push({
        role: 'thinking',
        content: msg.reasoning_content,
        metadata: { level: 'Medium' },
        timestamp: msg.timestamp,
      });
    }

    if (msg.role === 'custom_block') {
      const meta = msg.metadata || {};
      expanded.push({
        role: 'custom_block',
        content: meta.title || msg.content || '',
        block_id: meta.block_id,
        block_module: meta.module,
        block_file: meta.block,
        block_src: meta.src,
        block_props: meta.props || {},
        block_height: meta.height ?? 'auto',
        block_title: meta.title,
        timestamp: msg.timestamp,
      });
      continue;
    }

    if (msg.tool_calls && msg.tool_calls.length > 0) {
      if (msg.content && msg.content.trim()) {
        expanded.push({
          role: msg.role as any,
          content: msg.content,
          timestamp: msg.timestamp,
        });
      }
      expanded.push(...expandToolCalls(msg.tool_calls, msg.timestamp));
    } else {
      if (msg.content && msg.content.trim()) {
        expanded.push({
          role: msg.role as any,
          content: msg.content,
          timestamp: msg.timestamp,
        });
      }
    }
  }
  return expanded;
}

// ─── Store Interface ────────────────────────────────────────────────────────

interface ChatState {
  // Per-session state (the big change)
  sessionStates: Record<string, PerSessionState>;

  // Global state
  isConnected: boolean;
  currentSessionId: string | null;
  hasWorkspace: boolean;
  status: StatusInfo | null;
  thinkingLevel: 'Off' | 'Low' | 'Medium' | 'High';
  runningSessions: Set<string>;
  sessionListVersion: number;
  sidebarCollapsed: boolean;
  settingsModalOpen: boolean;

  // Actions
  loadSession: (sessionId: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  clearChat: () => Promise<void>;
  deleteTurn: (sessionId: string, turnIndex: number) => Promise<void>;
  setConnected: (connected: boolean) => void;
  respondToApproval: (approvalId: string, approved: boolean, autoApprove?: boolean) => void;
  setHasWorkspace: (hasWorkspace: boolean) => void;
  setStatus: (status: StatusInfo) => void;
  toggleMode: () => void;
  cycleAutonomy: () => void;
  cycleThinkingLevel: () => void;
  respondToAskUser: (requestId: string, answers: Record<string, any> | null) => void;
  respondToPlanApproval: (requestId: string, action: string, feedback?: string) => void;
  sendInterrupt: () => void;
  bumpSessionList: () => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setSelectedPersona: (personaName: string | null) => void;
  setDraft: (sessionId: string, text: string) => void;
  updateDataMessageRows: (
    dataMessageId: string,
    columns: DataColumn[],
    rows: Record<string, any>[],
  ) => void;
  openSettingsModal: () => void;
  closeSettingsModal: () => void;
}

const AUTONOMY_CYCLE: Array<'Manual' | 'Semi-Auto' | 'Auto'> = ['Manual', 'Semi-Auto', 'Auto'];
const THINKING_CYCLE: Array<'Off' | 'Low' | 'Medium' | 'High'> = ['Off', 'Low', 'Medium', 'High'];

export const useChatStore = create<ChatState>((set, get) => ({
  sessionStates: {},
  isConnected: false,
  currentSessionId: null,
  hasWorkspace: false,
  status: null,
  thinkingLevel: 'Medium',
  runningSessions: new Set<string>(),
  sessionListVersion: 0,
  sidebarCollapsed: false,
  settingsModalOpen: false,

  bumpSessionList: () => set(state => ({ sessionListVersion: state.sessionListVersion + 1 })),
  toggleSidebar: () => set(state => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
  setSelectedPersona: (personaName: string | null) => {
    const sessionId = get().currentSessionId;
    if (sessionId) {
      set(state => ({
        ...patchSession(state, sessionId, { selectedPersona: personaName }),
      }));
    }
  },
  setDraft: (sessionId: string, text: string) => {
    if (!sessionId) return;
    set(state => ({ ...patchSession(state, sessionId, { draft: text }) }));
  },
  // After an editable table saves, fold the saved rows back into the stored
  // data_message so the snapshot stays in sync — switching away to a module and
  // back no longer reverts to the pre-edit values.
  updateDataMessageRows: (dataMessageId, columns, rows) => {
    const sessionId = get().currentSessionId;
    if (!sessionId || !dataMessageId) return;
    set(state => ({
      ...patchSession(state, sessionId, prev => ({
        messages: prev.messages.map(m =>
          m.data_message_id === dataMessageId
            ? { ...m, data_columns: columns, data_rows: rows }
            : m,
        ),
      })),
    }));
  },
  openSettingsModal: () => set({ settingsModalOpen: true }),
  closeSettingsModal: () => set({ settingsModalOpen: false }),
  loadSession: async (sessionId: string) => {
    console.log(`[Frontend] Loading session ${sessionId}`);

    const existing = get().sessionStates[sessionId];
    if (existing && existing.messages.length > 0) {
      // Instant switch — already cached
      console.log(`[Frontend] Session ${sessionId} cached (${existing.messages.length} msgs), instant switch`);
      set({ currentSessionId: sessionId, hasWorkspace: true });
    } else {
      // Need to fetch messages
      set(state => ({
        currentSessionId: sessionId,
        hasWorkspace: true,
        ...patchSession(state, sessionId, { isLoading: true, error: null }),
      }));

      try {
        console.log(`[Frontend] Fetching messages for session ${sessionId}`);
        const rawMessages = await apiClient.getSessionMessages(sessionId);
        const messages = expandMessages(rawMessages);
        console.log(`[Frontend] Loaded ${messages.length} messages for ${sessionId}`);

        set(state => ({
          ...patchSession(state, sessionId, { messages, isLoading: false }),
        }));
      } catch (error) {
        console.error(`[Frontend] Failed to load session ${sessionId}:`, error);
        set(state => ({
          ...patchSession(state, sessionId, {
            error: error instanceof Error ? error.message : 'Failed to load session',
            isLoading: false,
          }),
        }));
      }
    }

    // Fire-and-forget: resume on backend for config context
    apiClient.resumeSession(sessionId).catch(() => {});

    // Refresh status after session change
    try {
      const configData = await apiClient.getConfig();
      set({
        thinkingLevel: configData.thinking_level || 'Medium',
        status: {
          mode: configData.mode || 'normal',
          autonomy_level: configData.autonomy_level || 'Manual',
          thinking_level: configData.thinking_level || 'Medium',
          model: configData.model,
          working_dir: configData.working_dir || '',
          git_branch: configData.git_branch,
          simple_mode: configData.simple_mode ?? true,
        },
      });
    } catch (_) { /* ignore */ }

    console.log(`[Frontend] Session ${sessionId} loaded successfully`);

    // Scan the conversation folder for artifacts (fire-and-forget)
    if (!isNaN(parseInt(sessionId, 10))) {
      useArtifactsStore.getState().scanArtifacts(sessionId).catch(() => {});
    }
  },

  sendMessage: async (content: string) => {
    const sessionId = get().currentSessionId;
    if (!sessionId) return;

    const sessionState = getSessionState(get().sessionStates, sessionId);
    const isQueuing = sessionState.isLoading;

    const userMessage: Message = {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    };

    set(state => ({
      ...patchSession(state, sessionId, prev => ({
        messages: [...prev.messages, userMessage],
        isLoading: true,
        error: null,
        queuedMessages: isQueuing
          ? [...prev.queuedMessages, content]
          : prev.queuedMessages,
      })),
    }));

    try {
      const persona = getSessionState(get().sessionStates, sessionId).selectedPersona ?? null;
      wsClient.send({
        type: 'query',
        data: {
          message: content,
          session_id: sessionId,
          ...(persona ? { persona_name: persona } : {}),
        },
      });
    } catch (error) {
      set(state => ({
        ...patchSession(state, sessionId, {
          error: error instanceof Error ? error.message : 'Failed to send message',
          isLoading: false,
        }),
      }));
    }
  },

  clearChat: async () => {
    const sessionId = get().currentSessionId;
    try {
      await apiClient.clearChat();
      if (sessionId) {
        set(state => ({
          ...patchSession(state, sessionId, { messages: [], error: null }),
        }));
      }
    } catch (error) {
      if (sessionId) {
        set(state => ({
          ...patchSession(state, sessionId, {
            error: error instanceof Error ? error.message : 'Failed to clear chat',
          }),
        }));
      }
    }
  },

  deleteTurn: async (sessionId: string, turnIndex: number) => {
    try {
      const result = await apiClient.deleteSessionTurn(sessionId, turnIndex);
      const messages = expandMessages((result.messages || []) as Message[]);
      set(state => ({
        ...patchSession(state, sessionId, { messages, error: null }),
      }));
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to delete turn';
      useToastStore.getState().addToast(msg, 'error');
    }
  },

  setConnected: (connected: boolean) => {
    set({ isConnected: connected });
  },

  respondToApproval: (approvalId: string, approved: boolean, autoApprove: boolean = false) => {
    wsClient.send({
      type: 'approve',
      data: { approvalId, approved, autoApprove },
    });
    const sessionId = get().currentSessionId;
    if (sessionId) {
      set(state => ({
        ...patchSession(state, sessionId, { pendingApproval: null }),
      }));
    }
  },

  setHasWorkspace: (hasWorkspace: boolean) => {
    set({ hasWorkspace });
  },

  setStatus: (status: StatusInfo) => {
    set({ status });
  },

  toggleMode: () => {
    const { status } = get();
    if (!status) return;
    const newMode = status.mode === 'normal' ? 'plan' : 'normal';
    apiClient.setMode(newMode).catch(console.error);
    set({ status: { ...status, mode: newMode } });
  },

  cycleAutonomy: () => {
    const { status } = get();
    if (!status) return;
    const currentIdx = AUTONOMY_CYCLE.indexOf(status.autonomy_level);
    const nextLevel = AUTONOMY_CYCLE[(currentIdx + 1) % AUTONOMY_CYCLE.length];
    apiClient.setAutonomy(nextLevel).catch(console.error);
    set({ status: { ...status, autonomy_level: nextLevel } });
  },

  cycleThinkingLevel: () => {
    const { status } = get();
    const currentLevel = status?.thinking_level || get().thinkingLevel;
    const currentIdx = THINKING_CYCLE.indexOf(currentLevel as any);
    const nextLevel = THINKING_CYCLE[(currentIdx + 1) % THINKING_CYCLE.length];
    apiClient.setThinkingLevel(nextLevel).catch(console.error);
    set({
      thinkingLevel: nextLevel,
      status: status ? { ...status, thinking_level: nextLevel } : status,
    });
  },

  respondToAskUser: (requestId: string, answers: Record<string, any> | null) => {
    wsClient.send({
      type: 'ask_user_response',
      data: { requestId, answers, cancelled: answers === null },
    });
    const sessionId = get().currentSessionId;
    if (sessionId) {
      set(state => ({
        ...patchSession(state, sessionId, { pendingAskUser: null }),
      }));
    }
  },

  respondToPlanApproval: (requestId: string, action: string, feedback?: string) => {
    wsClient.send({
      type: 'plan_approval_response',
      data: { requestId, action, feedback: feedback || '' },
    });
    const sessionId = get().currentSessionId;
    if (sessionId) {
      set(state => ({
        ...patchSession(state, sessionId, { pendingPlanApproval: null }),
      }));
    }
  },

  sendInterrupt: () => {
    const sessionId = get().currentSessionId;
    if (!sessionId) return;

    apiClient.interruptTask().catch(console.error);

    set(state => ({
      ...patchSession(state, sessionId, prev => ({
        isLoading: false,
        pendingApproval: null,
        pendingAskUser: null,
        pendingPlanApproval: null,
        messages: markLastToolCallInterrupted(prev.messages),
      })),
    }));
  },
}));

/** Mark the last pending tool_call message as interrupted. */
function markLastToolCallInterrupted(messages: Message[]): Message[] {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'tool_call' && !messages[i].tool_result) {
      const updated = [...messages];
      updated[i] = {
        ...messages[i],
        tool_result: { success: false, error: 'Interrupted' },
        tool_success: false,
        tool_error: 'Interrupted',
      };
      return updated;
    }
  }
  return messages;
}

// ─── WebSocket Event Handlers ───────────────────────────────────────────────

/** Resolve the session ID from a WS event, falling back to currentSessionId. */
function resolveSessionId(data: any): string | null {
  return data?.session_id || useChatStore.getState().currentSessionId;
}

let connectionStableTimer: number | null = null;
let wasEverStable = false;

wsClient.on('connected', () => {
  useChatStore.getState().setConnected(true);
  if (wasEverStable) {
    useToastStore.getState().addToast('Reconnected to server', 'success');
  }
  connectionStableTimer = window.setTimeout(() => {
    wasEverStable = true;
  }, 2000);
});

wsClient.on('disconnected', () => {
  useChatStore.getState().setConnected(false);
  if (connectionStableTimer) {
    clearTimeout(connectionStableTimer);
    connectionStableTimer = null;
  }
  if (wasEverStable) {
    useToastStore.getState().addToast('Disconnected from server', 'warning');
  }
});

wsClient.on('user_message', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const content = message.data.content;
  const sessionState = getSessionState(useChatStore.getState().sessionStates, sid);
  const msgs = sessionState.messages;
  // Dedup: skip if last user message already has this content (optimistic add from sendMessage)
  const lastUserMsg = [...msgs].reverse().find(m => m.role === 'user');
  if (lastUserMsg && lastUserMsg.content === content) return;
  useChatStore.setState(state => ({
    ...patchSession(state, sid, prev => ({
      messages: [...prev.messages, {
        role: 'user' as const,
        content,
        timestamp: new Date().toISOString(),
      }],
    })),
  }));
});

wsClient.on('message_start', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { isLoading: true }),
  }));
});

wsClient.on('message_chunk', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const msgs = sessionState.messages;
    const lastMessage = msgs[msgs.length - 1];

    let newMessages: Message[];
    if (lastMessage && lastMessage.role === 'assistant') {
      newMessages = [
        ...msgs.slice(0, -1),
        { ...lastMessage, content: lastMessage.content + message.data.content },
      ];
    } else {
      newMessages = [
        ...msgs,
        { role: 'assistant' as const, content: message.data.content },
      ];
    }

    return patchSession(state, sid, { messages: newMessages });
  });
});

wsClient.on('message_complete', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  console.log('[Frontend] Received message_complete');
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { isLoading: false, queuedMessages: [] }),
  }));
  // Re-scan artifacts — agent may have written new files during its turn
  if (!isNaN(parseInt(sid, 10))) {
    useArtifactsStore.getState().scanArtifacts(sid).catch(() => {});
  }
});

wsClient.on('error', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  useChatStore.setState(state => ({
    ...patchSession(state, sid, {
      error: message.data.message,
      isLoading: false,
    }),
  }));
  useToastStore.getState().addToast(message.data.message || 'An error occurred', 'error');
});

wsClient.on('approval_required', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  console.log('[Frontend] Received approval_required:', message.data);
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { pendingApproval: message.data as ApprovalRequest }),
  }));
});

wsClient.on('approval_resolved', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { pendingApproval: null }),
  }));
});

wsClient.on('tool_call', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  const toolCallMessage: Message = {
    role: 'tool_call',
    content: message.data.description || `Calling ${message.data.tool_name}`,
    tool_call_id: message.data.tool_call_id,
    tool_name: message.data.tool_name,
    tool_args: message.data.arguments,
    tool_args_display: message.data.arguments_display || null,
    activity: message.data.activity || null,
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...sessionState.messages, toolCallMessage] });
  });
});

wsClient.on('tool_result', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const msgs = sessionState.messages;
    const callId = message.data.tool_call_id;

    for (let i = msgs.length - 1; i >= 0; i--) {
      if (
        msgs[i].role === 'tool_call' &&
        msgs[i].tool_call_id === callId &&
        !msgs[i].tool_result
      ) {
        const updatedMessages = [...msgs];
        updatedMessages[i] = {
          ...msgs[i],
          tool_result: message.data.raw_result ?? message.data.output,
          tool_summary: message.data.summary,
          tool_success: message.data.success,
          tool_error: message.data.error || null,
        };
        return patchSession(state, sid, { messages: updatedMessages });
      }
    }

    console.warn(`Received tool_result for ${message.data.tool_name} but no matching tool_call found`);
    return {};
  });
});

wsClient.on('thinking_block', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, {
      messages: [
        ...sessionState.messages,
        {
          role: 'thinking' as const,
          content: message.data.content,
          metadata: { level: message.data.level },
        },
      ],
    });
  });
});

wsClient.on('image_message', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, {
      messages: [
        ...sessionState.messages,
        {
          role: 'image_message' as const,
          content: message.data.caption || '',
          image_src: message.data.src,
          image_mime: message.data.mime_type,
          image_caption: message.data.caption,
          timestamp: new Date().toISOString(),
        },
      ],
    });
  });
});

wsClient.on('data_message', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  const dataMessageId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `data-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, {
      messages: [
        ...sessionState.messages,
        {
          role: 'data_message' as const,
          content: message.data.title || '',
          data_message_id: dataMessageId,
          data_title: message.data.title,
          data_columns: message.data.columns,
          data_rows: message.data.rows,
          data_suggestions: message.data.suggestions,
          data_warning: message.data.warning,
          data_editable: message.data.editable,
          data_source: message.data.source,
          timestamp: new Date().toISOString(),
        },
      ],
    });
  });
});

wsClient.on('custom_block', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, {
      messages: [
        ...sessionState.messages,
        {
          role: 'custom_block' as const,
          content: message.data.title || '',
          block_id: message.data.block_id,
          block_module: message.data.module,
          block_file: message.data.block,
          block_src: message.data.src,
          block_props: message.data.props || {},
          block_height: message.data.height ?? 'auto',
          block_title: message.data.title,
          timestamp: new Date().toISOString(),
        },
      ],
    });
  });
});

wsClient.on('custom_block_update', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const blockId = message.data.block_id;
  if (!blockId) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const idx = sessionState.messages.findIndex(
      m => m.role === 'custom_block' && m.block_id === blockId,
    );
    if (idx < 0) return {};
    const updated = [...sessionState.messages];
    const prev = updated[idx];
    updated[idx] = {
      ...prev,
      block_props: { ...(prev.block_props || {}), ...(message.data.props || {}) },
      ...(message.data.height !== undefined ? { block_height: message.data.height } : {}),
      ...(message.data.title !== undefined ? { block_title: message.data.title } : {}),
    };
    return patchSession(state, sid, { messages: updated });
  });
});

wsClient.on('custom_block_remove', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const blockId = message.data.block_id;
  if (!blockId) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, {
      messages: sessionState.messages.filter(
        m => !(m.role === 'custom_block' && m.block_id === blockId),
      ),
    });
  });
});

wsClient.on('block_rpc_result', (message) => {
  const detail = {
    block_id: message.data?.block_id,
    req_id: message.data?.req_id,
    ok: message.data?.ok ?? !message.data?.error,
    data: message.data?.data,
    error: message.data?.error,
  };
  window.dispatchEvent(new CustomEvent('block-rpc-result', { detail }));
});

wsClient.on('status_update', (message) => {
  const { status } = useChatStore.getState();
  const newStatus = {
    ...status,
    ...message.data,
  } as StatusInfo;
  useChatStore.setState({
    status: newStatus,
    thinkingLevel: newStatus.thinking_level || useChatStore.getState().thinkingLevel,
  });
});

wsClient.on('ask_user_required', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  console.log('[Frontend] Received ask_user_required:', message.data);
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { pendingAskUser: message.data as AskUserRequest }),
  }));
});

wsClient.on('ask_user_resolved', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { pendingAskUser: null }),
  }));
});

wsClient.on('session_activity', (message) => {
  const { session_id, status } = message.data;
  useChatStore.setState((state) => {
    const next = new Set(state.runningSessions);
    if (status === 'running') next.add(session_id);
    else next.delete(session_id);
    return { runningSessions: next };
  });
  useChatStore.getState().bumpSessionList();
});

// ─── Plan Approval Events ────────────────────────────────────────────────────

wsClient.on('plan_approval_required', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  console.log('[Frontend] Received plan_approval_required:', message.data);
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { pendingPlanApproval: message.data as PlanApprovalRequest }),
  }));
});

wsClient.on('plan_approval_resolved', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  useChatStore.setState(state => ({
    ...patchSession(state, sid, { pendingPlanApproval: null }),
  }));
});

// ─── Subagent Events ─────────────────────────────────────────────────────────

wsClient.on('subagent_start', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { agent_type, description, tool_call_id } = message.data;
  console.log('[Frontend] Subagent start:', agent_type, description);

  const subagentMessage: Message = {
    role: 'tool_call',
    content: `Spawning ${agent_type} agent`,
    tool_call_id: tool_call_id,
    tool_name: 'spawn_subagent',
    tool_args: { agent_type, description },
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...sessionState.messages, subagentMessage] });
  });
});

wsClient.on('subagent_complete', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { tool_call_id, success } = message.data;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const msgs = sessionState.messages;

    for (let i = msgs.length - 1; i >= 0; i--) {
      if (
        msgs[i].role === 'tool_call' &&
        msgs[i].tool_name === 'spawn_subagent' &&
        msgs[i].tool_call_id === tool_call_id &&
        !msgs[i].tool_result
      ) {
        const updatedMessages = [...msgs];
        updatedMessages[i] = {
          ...msgs[i],
          tool_result: { success, output: success ? 'Agent completed' : 'Agent failed' },
          tool_summary: success ? 'Agent completed successfully' : 'Agent failed',
          tool_success: success,
        };
        return patchSession(state, sid, { messages: updatedMessages });
      }
    }
    return {};
  });
});

wsClient.on('task_completed', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  console.log('[Frontend] Task completed:', message.data.summary);
});

// ─── Progress Events ─────────────────────────────────────────────────────────

wsClient.on('progress', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { status, message: progressMsg } = message.data;

  if (status === 'complete') {
    useChatStore.setState(state => ({
      ...patchSession(state, sid, { progressMessage: null }),
    }));
  } else {
    useChatStore.setState(state => ({
      ...patchSession(state, sid, { progressMessage: progressMsg || 'Working...' }),
    }));
  }
});

// ─── Nested Tool Events ──────────────────────────────────────────────────────

wsClient.on('nested_tool_call', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { tool_name, arguments: args, depth, parent } = message.data;

  const nestedMsg: Message = {
    role: 'tool_call',
    content: `Calling ${tool_name}`,
    tool_name,
    tool_args: args || {},
    tool_call_id: `nested-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    depth: depth || 1,
    parent_tool_call_id: parent,
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...sessionState.messages, nestedMsg] });
  });
});

wsClient.on('nested_tool_result', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { tool_name, success, summary, depth } = message.data;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const msgs = sessionState.messages;

    // Find the last matching nested tool_call without a result
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (
        msgs[i].role === 'tool_call' &&
        msgs[i].tool_name === tool_name &&
        msgs[i].depth === depth &&
        !msgs[i].tool_result
      ) {
        const updated = [...msgs];
        updated[i] = {
          ...msgs[i],
          tool_result: { success, output: summary },
          tool_summary: summary || (success ? 'Completed' : 'Failed'),
          tool_success: success,
        };
        return patchSession(state, sid, { messages: updated });
      }
    }
    return {};
  });
});

// ─── Search Events ────────────────────────────────────────────────────────────

wsClient.on('search_done', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { query, result_count, results, provider } = message.data;

  const searchMsg: Message = {
    role: 'search_result',
    content: query,
    search_query: query,
    search_result_count: result_count,
    search_results: results || [],
    search_provider: provider || '',
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...sessionState.messages, searchMsg] });
  });
});

// ─── Thinking Token Streaming ─────────────────────────────────────────────────

wsClient.on('thinking', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { token } = message.data;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const msgs = sessionState.messages;
    const last = msgs[msgs.length - 1];

    if (last && last.role === 'thinking' && last.streaming) {
      const updated = [...msgs];
      updated[updated.length - 1] = { ...last, content: last.content + token };
      return patchSession(state, sid, { messages: updated });
    }

    return patchSession(state, sid, {
      messages: [
        ...msgs,
        {
          role: 'thinking' as const,
          content: token,
          metadata: { level: 'Medium' },
          streaming: true,
          timestamp: new Date().toISOString(),
        },
      ],
    });
  });
});

// ─── Deep Research Events ─────────────────────────────────────────────────────

/** Find the deep_research message for a given job_id (searching backwards). */
function findDeepResearchIdx(msgs: Message[], jobId: string): number {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'deep_research' && msgs[i].dr_job_id === jobId) return i;
  }
  return -1;
}

wsClient.on('deep_research_taxonomy_ready', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, taxonomy, request_id, topic } = message.data;
  const resolvedTopic = topic ?? taxonomy?.topic ?? '';

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    // Regeneration: update existing reviewing message for this job_id
    const existingIdx = findDeepResearchIdx(ss.messages, job_id);
    if (existingIdx !== -1) {
      const updated = [...ss.messages];
      updated[existingIdx] = {
        ...updated[existingIdx],
        dr_topic: resolvedTopic,
        dr_taxonomy: taxonomy,
        dr_review_request_id: request_id,
        dr_status: 'reviewing',
      };
      return patchSession(state, sid, { messages: updated });
    }
    // First time — create the reviewing message
    const msg: Message = {
      role: 'deep_research',
      content: resolvedTopic,
      dr_job_id: job_id,
      dr_topic: resolvedTopic,
      dr_taxonomy: taxonomy,
      dr_status: 'reviewing',
      dr_review_request_id: request_id,
      dr_progress: 0,
      dr_sections: [],
      timestamp: new Date().toISOString(),
    };
    return patchSession(state, sid, { messages: [...ss.messages, msg] });
  });
});

wsClient.on('deep_research_queued', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, topic, taxonomy } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    // If we already have a reviewing message for this job_id, update it.
    const existingIdx = findDeepResearchIdx(ss.messages, job_id);
    if (existingIdx !== -1) {
      const updated = [...ss.messages];
      updated[existingIdx] = {
        ...updated[existingIdx],
        dr_topic: topic,
        dr_taxonomy: taxonomy,
        dr_status: 'queued',
        dr_review_request_id: undefined,
      };
      return patchSession(state, sid, { messages: updated });
    }
    // No existing message — create a new one (non-web path / fallback).
    const msg: Message = {
      role: 'deep_research',
      content: topic,
      dr_job_id: job_id,
      dr_topic: topic,
      dr_taxonomy: taxonomy,
      dr_status: 'queued',
      dr_progress: 0,
      dr_sections: [],
      timestamp: new Date().toISOString(),
    };
    return patchSession(state, sid, { messages: [...ss.messages, msg] });
  });
});

wsClient.on('deep_research_start', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const idx = findDeepResearchIdx(ss.messages, job_id);
    if (idx === -1) return {};
    const updated = [...ss.messages];
    updated[idx] = { ...updated[idx], dr_status: 'running' };
    return patchSession(state, sid, { messages: updated });
  });
});

wsClient.on('deep_research_section_start', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, category, subtopic } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const idx = findDeepResearchIdx(ss.messages, job_id);
    if (idx === -1) return {};
    const updated = [...ss.messages];
    updated[idx] = { ...updated[idx], dr_active_section: { category, subtopic } };
    return patchSession(state, sid, { messages: updated });
  });
});

wsClient.on('deep_research_section_done', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, category, subtopic, content, progress } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const idx = findDeepResearchIdx(ss.messages, job_id);
    if (idx === -1) return {};
    const prev = ss.messages[idx];
    const sections = [...(prev.dr_sections || []), { category, subtopic, content }];
    const updated = [...ss.messages];
    updated[idx] = { ...prev, dr_sections: sections, dr_progress: progress, dr_active_section: undefined };
    return patchSession(state, sid, { messages: updated });
  });
});

wsClient.on('deep_research_done', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, sections, report_path } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const idx = findDeepResearchIdx(ss.messages, job_id);
    if (idx === -1) return {};
    const updated = [...ss.messages];
    updated[idx] = {
      ...updated[idx],
      dr_status: 'done',
      dr_progress: 1,
      dr_sections: sections,
      dr_active_section: undefined,
      dr_report_path: report_path || undefined,
    };
    return patchSession(state, sid, { messages: updated });
  });
});

wsClient.on('deep_research_error', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, error } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const idx = findDeepResearchIdx(ss.messages, job_id);
    if (idx === -1) return {};
    const updated = [...ss.messages];
    updated[idx] = { ...updated[idx], dr_status: 'error', dr_error: error };
    return patchSession(state, sid, { messages: updated });
  });
});

wsClient.on('thinking_done', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;

  useChatStore.setState(state => {
    const sessionState = getSessionState(state.sessionStates, sid);
    const msgs = sessionState.messages;
    const lastIdx = msgs.length - 1;
    if (lastIdx >= 0 && msgs[lastIdx].role === 'thinking' && msgs[lastIdx].streaming) {
      const updated = [...msgs];
      updated[lastIdx] = { ...msgs[lastIdx], streaming: false };
      return patchSession(state, sid, { messages: updated });
    }
    return {};
  });
});

// ─── Deep Analyze Events ──────────────────────────────────────────────────────

const DA_PHASES = ['load', 'profile', 'explore', 'plan', 'extract', 'synthesize', 'report'] as const;

/** Find the deep_analyze message for a given job_id (searching backwards). */
function findDeepAnalyzeIdx(msgs: Message[], jobId: string): number {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'deep_analyze' && msgs[i].da_job_id === jobId) return i;
  }
  return -1;
}

/** Upsert the deep_analyze message and apply a patch. Creates the message on first event. */
function upsertDeepAnalyzeMessage(
  sid: string,
  jobId: string,
  patch: (prev: Message) => Message,
) {
  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const idx = findDeepAnalyzeIdx(ss.messages, jobId);
    if (idx === -1) {
      const initial: Message = {
        role: 'deep_analyze',
        content: '',
        da_job_id: jobId,
        da_status: 'running',
        da_phases: { explore: 'pending', load: 'pending', profile: 'pending',
                     plan: 'pending', extract: 'pending',
                     synthesize: 'pending', report: 'pending' },
        da_subtables: [],
        timestamp: new Date().toISOString(),
      };
      const created = patch(initial);
      return patchSession(state, sid, { messages: [...ss.messages, created] });
    }
    const updated = [...ss.messages];
    updated[idx] = patch(updated[idx]);
    return patchSession(state, sid, { messages: updated });
  });
}

wsClient.on('analyze.started', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, file_name } = message.data;
  if (!job_id) return;
  upsertDeepAnalyzeMessage(sid, job_id, prev => ({
    ...prev,
    content: file_name || prev.content || '',
  }));
});

wsClient.on('analyze.phase', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, phase, status, rows, cols, sub_tables, charts } = message.data;
  if (!job_id || !DA_PHASES.includes(phase)) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => {
    const phases = { ...(prev.da_phases || {}) };
    phases[phase as typeof DA_PHASES[number]] = status === 'done' ? 'done' : 'running';
    const next: Message = { ...prev, da_phases: phases };
    if (phase === 'load' && status === 'done') {
      next.da_load_rows = rows;
      next.da_load_cols = cols;
    } else if (phase === 'plan' && status === 'done') {
      next.da_plan_subtables = sub_tables;
      next.da_plan_charts = charts;
    }
    return next;
  });
});

wsClient.on('analyze.subtable', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, name, rows, status, error } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => {
    const subtables = [...(prev.da_subtables || []), { name, rows, status, error }];
    return { ...prev, da_subtables: subtables };
  });
});

wsClient.on('analyze.plan_ready', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, plan, request_id } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => ({
    ...prev,
    da_status: 'plan_reviewing',
    da_plan: plan,
    da_plan_review_request_id: request_id,
  }));
});

wsClient.on('analyze.clarify', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, request_id, questions, iteration, domain_brief } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => ({
    ...prev,
    da_status: 'clarifying',
    da_clarify_request_id: request_id,
    da_clarify_questions: questions ?? [],
    da_clarify_iteration: iteration,
    da_domain_brief: domain_brief,
  }));
});

wsClient.on('analyze.chart_image', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { name, title, sql, src, columns, rows, suggestions } = message.data;

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    const existing = ss.messages.find(m => m.data_message_id === `da_chart_${name}`);

    if (existing) {
      // Merge image + table data into the existing data_message (preserve what's already there)
      const messages = ss.messages.map(m =>
        m.data_message_id === `da_chart_${name}`
          ? {
              ...m,
              data_image_src: src,
              data_sql: sql || m.data_sql,
              // Only fill columns/rows if the chart_data event didn't already set them
              data_columns: m.data_columns?.length ? m.data_columns : (columns ?? []),
              data_rows: m.data_rows?.length ? m.data_rows : (rows ?? []),
              data_suggestions: m.data_suggestions?.length ? m.data_suggestions : (suggestions ?? []),
            }
          : m
      );
      return patchSession(state, sid, { messages });
    }

    // No prior chart_data message — create a full one now
    const dataMsg: Message = {
      role: 'data_message',
      content: title || name || '',
      data_message_id: `da_chart_${name}`,
      data_title: title || name || '',
      data_image_src: src,
      data_sql: sql || undefined,
      data_columns: columns ?? [],
      data_rows: rows ?? [],
      data_suggestions: suggestions ?? [],
      timestamp: new Date().toISOString(),
    };
    return patchSession(state, sid, { messages: [...ss.messages, dataMsg] });
  });
});

wsClient.on('analyze.section_synthesized', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, status } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => {
    const phases = { ...(prev.da_phases || {}) };
    if (status === 'done') phases['synthesize'] = 'done';
    return { ...prev, da_phases: phases };
  });
});

wsClient.on('analyze.chart_insight', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { title, insight } = message.data;
  if (!insight) return;

  const insightMsg: Message = {
    role: 'assistant',
    content: `**${title || 'Chart insight'}**\n\n${insight}`,
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...ss.messages, insightMsg] });
  });
});

wsClient.on('analyze.agent_message', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { content } = message.data;
  if (!content) return;

  const agentMsg: Message = {
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...ss.messages, agentMsg] });
  });
});

wsClient.on('analyze.report', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, pdf_path } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => ({ ...prev, da_report_path: pdf_path }));
});

wsClient.on('analyze.done', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => {
    const phases = { ...(prev.da_phases || {}) };
    for (const p of DA_PHASES) {
      if (phases[p] !== 'done') phases[p] = 'done';
    }
    return { ...prev, da_status: 'done', da_phases: phases };
  });
});

wsClient.on('analyze.failed', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, phase, error } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => ({
    ...prev, da_status: 'error', da_failed_phase: phase, da_error: error,
  }));
});

wsClient.on('analyze.cancelled', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => ({ ...prev, da_status: 'cancelled' }));
});

// File-based modules: refresh the modules store when SKILL.md / script.py
// changes on disk (watcher → WS broadcast). Lazy-imported to avoid a
// circular dependency between chat and modules stores.
wsClient.on('modules.changed', () => {
  import('./modules').then(({ useModulesStore }) => {
    useModulesStore.getState().refresh();
  });
});

// Session messages were replaced server-side (e.g. a turn was deleted).
// Envelope is top-level: { type, session_id, messages }. Broadcast to all
// clients, so we filter by session_id and ignore unknown sessions.
wsClient.on('session_messages_replaced', (message) => {
  const payload = message as any;
  const sid: string | undefined = payload.session_id;
  const rawMessages: any[] = payload.messages || [];
  if (!sid) return;
  const state = useChatStore.getState();
  if (!state.sessionStates[sid]) return;
  const messages = expandMessages(rawMessages as Message[]);
  useChatStore.setState(s => ({
    ...patchSession(s, sid, { messages }),
  }));
});
